"""Disclosure intake, roster building, inventorship confirmation/dispute,
and finalization — including the OCC and share-sum gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_roster_entry,
    assert_disclosure,
    assert_roster_entry,
    confirm_entry,
    create_department,
    create_inventor,
    get_disclosure,
    make_inventor_headers,
    raise_dispute,
    resolve_dispute,
    setup_department_and_inventor,
    submit_disclosure,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    add_roster_entry_payload,
    create_disclosure_payload,
    create_inventor_payload,
    finalize_payload,
)
from test_helpers.fixtures import api_client

ADMIN = TEST_USERS["system_admin_headers"]
TTO = TEST_USERS["tto_headers"]


class TestDepartmentAndIntakeValidation:
    def test_create_department_applies_defaults(self, api):
        """PRD: "A `SystemAdmin` creates each department with its `name` and
        `college_name`; the department's `distribution_pool_cents` ledger
        begins at 0."
        PRD: "Every resource in this API carries a system-managed `id` (a
        server-minted UUID with no type prefix)".

        Design: Corner/entities/create_department_applies_defaults
        """
        resp = api.create_department({"name": "EECS", "college_name": "Engineering"},
                                     ADMIN)
        dept = validate_success(resp, 201)
        assert dept["distribution_pool_cents"] == 0, \
            "the department-pool ledger begins at 0"
        from test_helpers import is_valid_uuid
        assert is_valid_uuid(dept["id"]), "id is a bare UUID without type prefix"

    def test_create_inventor_missing_required_field_returns_invalid_request(self, api):
        """PRD: "An `Inventor` — whose profile carries `full_name`, `email`,
        a home `department_id`, and an `appointment_type` of `FACULTY`,
        `STAFF`, or `STUDENT`".
        PRD: "fourth, request-body schema conformance — required fields
        present, enum membership valid, integer ranges respected, unknown
        payload fields rejected — with `ERR_INVALID_REQUEST`".

        Design: Corner/entities/create_inventor_missing_required_field_returns_invalid_request
        """
        dept = create_department()
        resp = api.create_inventor(
            {"full_name": "Ada Lovelace", "email": "ada@uni.edu",
             "department_id": dept["id"]},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_create_federal_disclosure_without_grant_number_rejected(self, api):
        """PRD: "When the funding source is `FEDERAL` or `MIXED`, the
        `federal_agency` and `grant_number` are both required; when it is
        `NON_FEDERAL`, they remain null."

        Design: Corner/entities/create_federal_disclosure_without_grant_number_rejected
        """
        _, inv = setup_department_and_inventor()
        resp = api.create_disclosure(
            create_disclosure_payload(title="X", description="Y",
                                      funding_source="FEDERAL",
                                      federal_agency="NSF"),
            make_inventor_headers(inv["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_disclosure_unknown_payload_field_rejected(self, api):
        """PRD: "fourth, request-body schema conformance — required fields
        present, enum membership valid, integer ranges respected, unknown
        payload fields rejected — with `ERR_INVALID_REQUEST`".

        Design: Corner/entities/disclosure_unknown_payload_field_rejected
        """
        _, inv = setup_department_and_inventor()
        payload = create_disclosure_payload(title="X", description="Y",
                                            funding_source="NON_FEDERAL")
        payload["unreimbursed_cost_cents"] = 999  # computed field, not input
        resp = api.create_disclosure(payload, make_inventor_headers(inv["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_disclosure_invalid_enum_value_rejected(self, api):
        """PRD: "`funding_source` of `FEDERAL`, `NON_FEDERAL`, or `MIXED`."
        PRD: "fourth, request-body schema conformance — required fields
        present, enum membership valid, integer ranges respected, unknown
        payload fields rejected — with `ERR_INVALID_REQUEST`".

        Design: Corner/entities/disclosure_invalid_enum_value_rejected
        """
        _, inv = setup_department_and_inventor()
        resp = api.create_disclosure(
            create_disclosure_payload(title="X", description="Y",
                                      funding_source="CORPORATE"),
            make_inventor_headers(inv["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestDisclosureInitialState:
    def test_disclosure_initial_state(self, api):
        """PRD: "The server stamps the new disclosure with
        `submitter_inventor_id` taken from the caller's `X-User-ID`,
        initializes both cost rollups to zero, and places the disclosure in
        `INVENTORSHIP_REVIEW`."

        Design: Corner/state_machines/disclosure_initial_state
        """
        _, inv = setup_department_and_inventor()
        disc = validate_success(
            api.create_disclosure(create_disclosure_payload(
                title="X", description="Y", funding_source="NON_FEDERAL"),
                make_inventor_headers(inv["id"])), 201)
        assert_disclosure(disc)
        assert disc["status"] == "INVENTORSHIP_REVIEW"
        assert disc["submitter_inventor_id"] == inv["id"]
        assert disc["unreimbursed_cost_cents"] == 0
        assert disc["written_off_cost_cents"] == 0
        # Ratings are only stored by the assessment endpoint; absent or null
        # before that are both faithful serializations.
        assert disc.get("patentability_rating") is None
        assert disc.get("market_rating") is None


class TestRosterAndConfirmation:
    def test_roster_reverse_reachability_from_inventor(self, api):
        """PRD endpoint table: "GET /tlo/inventors/{id}/disclosure-entries —
        List roster entries naming this inventor".
        PRD: "A `TechTransferOfficer` then builds the inventorship roster by
        adding `DisclosureInventor` entries, each naming an `inventor_id` and a
        `share_bp` between 1 and 10000 basis points."

        Design: Corner/entities/roster_reverse_reachability_from_inventor
        """
        _, inv = setup_department_and_inventor()
        disc = submit_disclosure(inv)
        entry = add_roster_entry(disc["id"], inv["id"], 10000)
        data, meta = validate_paginated(
            api.list_inventor_disclosure_entries(inv["id"], ADMIN))
        assert len(data) == 1, "the inventor has exactly one roster entry"
        assert data[0]["id"] == entry["id"]
        assert data[0]["inventor_id"] == inv["id"]
        assert data[0]["disclosure_id"] == disc["id"]

    def test_duplicate_roster_inventor_rejected(self, api):
        """PRD: "The same inventor may not appear twice on one disclosure's
        roster — a duplicate attempt is refused with
        `ERR_DUPLICATE_INVENTOR`."

        Design: Corner/validations/duplicate_roster_inventor_rejected
        """
        _, inv = setup_department_and_inventor()
        disc = submit_disclosure(inv)
        add_roster_entry(disc["id"], inv["id"], 10000)
        resp = api.add_roster_entry(
            disc["id"], add_roster_entry_payload(inv["id"], 5000), TTO)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_INVENTOR, 422)

    def test_confirm_already_confirmed_entry_rejected(self, api):
        """PRD: "Confirmation requires the entry to be `PENDING`, the
        disclosure still in `INVENTORSHIP_REVIEW`, and the caller's
        `X-User-ID` to equal the entry's `inventor_id` — confirming someone
        else's entry is `ERR_FORBIDDEN`, a non-`PENDING` entry is
        `ERR_ENTRY_NOT_CONFIRMABLE`, and a disclosure outside review is
        `ERR_DISCLOSURE_INVALID_STATE`."

        Design: Corner/state_machines/confirm_already_confirmed_entry_rejected
        """
        _, inv = setup_department_and_inventor()
        disc = submit_disclosure(inv)
        entry = add_roster_entry(disc["id"], inv["id"], 10000)
        confirm_entry(entry["id"], inv["id"])
        resp = api.confirm_entry(entry["id"], make_inventor_headers(inv["id"]))
        validate_error(resp, ApiErrorId.ERR_ENTRY_NOT_CONFIRMABLE, 409)

    def test_confirm_other_inventors_entry_forbidden(self, api):
        """PRD: "the caller's `X-User-ID` to equal the entry's `inventor_id`
        — confirming someone else's entry is `ERR_FORBIDDEN`".

        Design: Corner/rbac/confirm_other_inventors_entry_forbidden
        """
        dept = create_department()
        inv1 = create_inventor(dept["id"], "Inv One", "i1@uni.edu", "FACULTY")
        inv2 = create_inventor(dept["id"], "Inv Two", "i2@uni.edu", "STAFF")
        disc = submit_disclosure(inv1)
        e1 = add_roster_entry(disc["id"], inv1["id"], 6000)
        add_roster_entry(disc["id"], inv2["id"], 4000)
        resp = api.confirm_entry(e1["id"], make_inventor_headers(inv2["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        entry = validate_success(api.get_entry(e1["id"], ADMIN))
        assert entry["confirmation_status"] == "PENDING"

    def test_dispute_by_nonroster_inventor_forbidden(self, api):
        """PRD: "the disputing caller must be an inventor on that
        disclosure's roster, else `ERR_FORBIDDEN`."

        Design: Corner/rbac/dispute_by_nonroster_inventor_forbidden
        """
        dept = create_department()
        inv1 = create_inventor(dept["id"], "Inv One", "i1@uni.edu", "FACULTY")
        inv2 = create_inventor(dept["id"], "Inv Two", "i2@uni.edu", "STAFF")
        disc = submit_disclosure(inv1)
        e1 = add_roster_entry(disc["id"], inv1["id"], 10000)
        resp = api.dispute_entry(e1["id"], {"reason": "I should be listed"},
                                 make_inventor_headers(inv2["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


class TestDisputes:
    def test_dispute_of_disputed_entry_rejected(self, api):
        """PRD: "The entry being disputed must be in `PENDING` or `CONFIRMED`
        status — anything else yields `ERR_ENTRY_NOT_DISPUTABLE`".

        Design: Corner/state_machines/dispute_of_disputed_entry_rejected
        """
        dept = create_department()
        inv1 = create_inventor(dept["id"], "Inv One", "i1@uni.edu", "FACULTY")
        inv2 = create_inventor(dept["id"], "Inv Two", "i2@uni.edu", "STAFF")
        disc = submit_disclosure(inv1)
        e1 = add_roster_entry(disc["id"], inv1["id"], 6000)
        add_roster_entry(disc["id"], inv2["id"], 4000)
        raise_dispute(e1["id"], inv2["id"], "Share too high")
        resp = api.dispute_entry(e1["id"], {"reason": "Again"},
                                 make_inventor_headers(inv2["id"]))
        validate_error(resp, ApiErrorId.ERR_ENTRY_NOT_DISPUTABLE, 409)

    def test_resolve_resolved_dispute_rejected(self, api):
        """PRD: "Disputes are adjudicated by a `TechTransferOfficer`, who
        resolves an `OPEN` dispute — resolving a dispute not in `OPEN` status
        yields `ERR_DISPUTE_NOT_OPEN`".

        Design: Corner/state_machines/resolve_resolved_dispute_rejected
        """
        dept = create_department()
        inv1 = create_inventor(dept["id"], "Inv One", "i1@uni.edu", "FACULTY")
        inv2 = create_inventor(dept["id"], "Inv Two", "i2@uni.edu", "STAFF")
        disc = submit_disclosure(inv1)
        e1 = add_roster_entry(disc["id"], inv1["id"], 6000)
        e2 = add_roster_entry(disc["id"], inv2["id"], 4000)
        dispute = raise_dispute(e1["id"], inv2["id"], "Share too high")
        resolve_dispute(dispute["id"],
                        [{"entry_id": e1["id"], "share_bp": 5000},
                         {"entry_id": e2["id"], "share_bp": 5000}])
        resp = api.resolve_dispute(
            dispute["id"],
            {"resolution_notes": "Again",
             "adjusted_shares": [{"entry_id": e1["id"], "share_bp": 5000},
                                 {"entry_id": e2["id"], "share_bp": 5000}]},
            TTO)
        validate_error(resp, ApiErrorId.ERR_DISPUTE_NOT_OPEN, 409)

    def test_resolve_with_bad_share_sum_rejected(self, api):
        """PRD: "The vector must name every roster entry exactly once, and
        its `share_bp` values must sum to exactly 10000 basis points;
        otherwise the resolve is refused with `ERR_SHARE_SUM_INVALID`."

        Design: Corner/state_machines/resolve_with_bad_share_sum_rejected
        """
        dept = create_department()
        inv1 = create_inventor(dept["id"], "Inv One", "i1@uni.edu", "FACULTY")
        inv2 = create_inventor(dept["id"], "Inv Two", "i2@uni.edu", "STAFF")
        disc = submit_disclosure(inv1)
        e1 = add_roster_entry(disc["id"], inv1["id"], 6000)
        e2 = add_roster_entry(disc["id"], inv2["id"], 4000)
        dispute = raise_dispute(e1["id"], inv2["id"], "Share too high")
        resp = api.resolve_dispute(
            dispute["id"],
            {"resolution_notes": "Bad math",
             "adjusted_shares": [{"entry_id": e1["id"], "share_bp": 5000},
                                 {"entry_id": e2["id"], "share_bp": 4999}]},
            TTO)
        validate_error(resp, ApiErrorId.ERR_SHARE_SUM_INVALID, 409)
        refreshed = validate_success(api.get_dispute(dispute["id"], ADMIN))
        assert refreshed["status"] == "OPEN", "a refused resolve leaves the dispute OPEN"
        disc_after = validate_success(api.get_disclosure(disc["id"], ADMIN))
        assert disc_after["status"] == "INVENTORSHIP_DISPUTED"


class TestFinalizeBoundaries:
    def test_finalize_share_sum_9999_rejected(self, api):
        """PRD: "The `share_bp` values must sum to exactly 10000 basis
        points, with a violation refused as `ERR_SHARE_SUM_INVALID`."

        Design: Difficulty/boundary_precision_check/share_sum_exactly_10000_boundary
        """
        dept = create_department()
        invs = [create_inventor(dept["id"], f"Inv {i}", f"i{i}@uni.edu", "STAFF")
                for i in range(3)]
        disc = submit_disclosure(invs[0])
        entries = [add_roster_entry(disc["id"], inv["id"], 3333) for inv in invs]
        for e, inv in zip(entries, invs):
            confirm_entry(e["id"], inv["id"])
        version = get_disclosure(disc["id"])["version"]
        resp = api.finalize_inventorship(disc["id"], finalize_payload(version), TTO)
        validate_error(resp, ApiErrorId.ERR_SHARE_SUM_INVALID, 409)
        disc_after = validate_success(api.get_disclosure(disc["id"], ADMIN))
        assert disc_after["status"] == "INVENTORSHIP_REVIEW", \
            "9999 basis points is one short of 10000 and must not finalize"

    def test_finalize_share_sum_10001_rejected_then_exact_10000_succeeds(self, api):
        """PRD: "The `share_bp` values must sum to exactly 10000 basis
        points, with a violation refused as `ERR_SHARE_SUM_INVALID`."
        PRD: "A successful finalize moves the disclosure to
        `INVENTORSHIP_CONFIRMED` and increments its `version` by 1."

        Design: Difficulty/boundary_precision_check/share_sum_exactly_10000_boundary
        """
        dept = create_department()
        invs = [create_inventor(dept["id"], f"Inv {i}", f"i{i}@uni.edu", "STAFF")
                for i in range(3)]
        disc = submit_disclosure(invs[0])
        entries = [add_roster_entry(disc["id"], invs[0]["id"], 3334)]
        entries.append(add_roster_entry(disc["id"], invs[1]["id"], 3334))
        entries.append(add_roster_entry(disc["id"], invs[2]["id"], 3333))
        for e, inv in zip(entries, invs):
            confirm_entry(e["id"], inv["id"])
        version = get_disclosure(disc["id"])["version"]
        resp = api.finalize_inventorship(disc["id"], finalize_payload(version), TTO)
        validate_error(resp, ApiErrorId.ERR_SHARE_SUM_INVALID, 409)

        # Rebuild an exactly-10000 roster on a fresh disclosure.
        disc2 = submit_disclosure(invs[0], title="Exact")
        entries2 = [add_roster_entry(disc2["id"], invs[0]["id"], 3334),
                    add_roster_entry(disc2["id"], invs[1]["id"], 3333),
                    add_roster_entry(disc2["id"], invs[2]["id"], 3333)]
        for e, inv in zip(entries2, invs):
            confirm_entry(e["id"], inv["id"])
        version2 = get_disclosure(disc2["id"])["version"]
        finalized = validate_success(
            api.finalize_inventorship(disc2["id"], finalize_payload(version2), TTO))
        assert finalized["status"] == "INVENTORSHIP_CONFIRMED"

    def test_finalize_with_pending_entry_rejected(self, api):
        """PRD: "Finalization is defined only while the disclosure is in
        `INVENTORSHIP_REVIEW` and requires at least one roster entry with all
        entries `CONFIRMED`; a disclosure in the wrong state, an empty
        roster, or any unconfirmed entry yields
        `ERR_INVENTORSHIP_NOT_FINALIZABLE`."

        Design: Difficulty/cross_entity_state_dependency/finalize_requires_all_entries_confirmed
        """
        dept = create_department()
        inv1 = create_inventor(dept["id"], "Inv One", "i1@uni.edu", "FACULTY")
        inv2 = create_inventor(dept["id"], "Inv Two", "i2@uni.edu", "STAFF")
        disc = submit_disclosure(inv1)
        e1 = add_roster_entry(disc["id"], inv1["id"], 6000)
        e2 = add_roster_entry(disc["id"], inv2["id"], 4000)
        confirm_entry(e1["id"], inv1["id"])
        version = get_disclosure(disc["id"])["version"]
        resp = api.finalize_inventorship(disc["id"], finalize_payload(version), TTO)
        validate_error(resp, ApiErrorId.ERR_INVENTORSHIP_NOT_FINALIZABLE, 409)

        # After the second inventor confirms, finalization succeeds.
        confirm_entry(e2["id"], inv2["id"])
        version2 = get_disclosure(disc["id"])["version"]
        finalized = validate_success(
            api.finalize_inventorship(disc["id"], finalize_payload(version2), TTO))
        assert finalized["status"] == "INVENTORSHIP_CONFIRMED"

    def test_finalize_with_empty_roster_rejected(self, api):
        """PRD: "a disclosure in the wrong state, an empty roster, or any
        unconfirmed entry yields `ERR_INVENTORSHIP_NOT_FINALIZABLE`."

        Design: Difficulty/cross_entity_state_dependency/finalize_requires_all_entries_confirmed
        """
        _, inv = setup_department_and_inventor()
        disc = submit_disclosure(inv)
        version = get_disclosure(disc["id"])["version"]
        resp = api.finalize_inventorship(disc["id"], finalize_payload(version), TTO)
        validate_error(resp, ApiErrorId.ERR_INVENTORSHIP_NOT_FINALIZABLE, 409)

    def test_occ_finalize_stale_after_dispute(self, api):
        """PRD: "The request must also carry `expected_disclosure_version`
        matching the disclosure's current `version`; if a dispute cycle has
        advanced the version since the officer last read the disclosure, the
        finalize is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_finalize_stale_after_dispute
        """
        dept = create_department()
        inv1 = create_inventor(dept["id"], "Inv One", "i1@uni.edu", "FACULTY")
        inv2 = create_inventor(dept["id"], "Inv Two", "i2@uni.edu", "STAFF")
        disc = submit_disclosure(inv1)
        e1 = add_roster_entry(disc["id"], inv1["id"], 6000)
        e2 = add_roster_entry(disc["id"], inv2["id"], 4000)
        confirm_entry(e1["id"], inv1["id"])
        confirm_entry(e2["id"], inv2["id"])
        stale_version = get_disclosure(disc["id"])["version"]
        # A rostered inventor raises a dispute, which bumps the version.
        raise_dispute(e2["id"], inv1["id"], "Share")
        resp = api.finalize_inventorship(
            disc["id"], finalize_payload(stale_version), TTO)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)


class TestDisputeResolveShareConservation:
    def test_dispute_resolve_cycles_conserve_share_total(self, api):
        """PRD: "Resolution overwrites each entry's `share_bp` from the
        vector, resets every entry's `confirmation_status` to `PENDING`,
        clears every `confirmed_at`, marks the dispute `RESOLVED` with its
        `resolution_notes` stored, returns the disclosure to
        `INVENTORSHIP_REVIEW`, and increments the disclosure's `version` by
        1."

        Design: Difficulty/compensating_invariant/inventorship_dispute_resolve_share_conservation
        """
        dept = create_department()
        inv1 = create_inventor(dept["id"], "Inv One", "i1@uni.edu", "FACULTY")
        inv2 = create_inventor(dept["id"], "Inv Two", "i2@uni.edu", "STAFF")
        disc = submit_disclosure(inv1)
        e1 = add_roster_entry(disc["id"], inv1["id"], 6000)
        e2 = add_roster_entry(disc["id"], inv2["id"], 4000)
        confirm_entry(e1["id"], inv1["id"])
        confirm_entry(e2["id"], inv2["id"])

        d1 = raise_dispute(e2["id"], inv2["id"], "Contribution underestimated")
        resolve_dispute(d1["id"],
                        [{"entry_id": e1["id"], "share_bp": 5000},
                         {"entry_id": e2["id"], "share_bp": 5000}],
                        "Adjust to equal")
        roster = validate_paginated(api.list_roster_entries(disc["id"], ADMIN))[0]
        by_id = {r["id"]: r for r in roster}
        assert by_id[e1["id"]]["share_bp"] == 5000
        assert by_id[e2["id"]]["share_bp"] == 5000
        assert sum(r["share_bp"] for r in roster) == 10000, "share total conserved"
        for r in roster:
            assert r["confirmation_status"] == "PENDING", \
                "resolve resets every entry to PENDING"
            assert r.get("confirmed_at") is None
        disc_mid = validate_success(api.get_disclosure(disc["id"], ADMIN))
        assert disc_mid["status"] == "INVENTORSHIP_REVIEW"

        confirm_entry(e1["id"], inv1["id"])
        confirm_entry(e2["id"], inv2["id"])
        d2 = raise_dispute(e1["id"], inv1["id"], "Restore original split")
        resolve_dispute(d2["id"],
                        [{"entry_id": e1["id"], "share_bp": 6000},
                         {"entry_id": e2["id"], "share_bp": 4000}], "Restore")
        roster2 = validate_paginated(api.list_roster_entries(disc["id"], ADMIN))[0]
        by_id2 = {r["id"]: r for r in roster2}
        assert by_id2[e1["id"]]["share_bp"] == 6000, "original vector restored"
        assert by_id2[e2["id"]]["share_bp"] == 4000
        disc_end = validate_success(api.get_disclosure(disc["id"], ADMIN))
        assert disc_end["status"] == "INVENTORSHIP_REVIEW"

    def test_resolve_requires_complete_roster_vector(self, api):
        """PRD: "The vector must name every roster entry exactly once, and
        its `share_bp` values must sum to exactly 10000 basis points;
        otherwise the resolve is refused with `ERR_SHARE_SUM_INVALID`."

        Design: Difficulty/compensating_invariant/inventorship_dispute_resolve_share_conservation
        """
        dept = create_department()
        inv1 = create_inventor(dept["id"], "Inv One", "i1@uni.edu", "FACULTY")
        inv2 = create_inventor(dept["id"], "Inv Two", "i2@uni.edu", "STAFF")
        disc = submit_disclosure(inv1)
        e1 = add_roster_entry(disc["id"], inv1["id"], 6000)
        add_roster_entry(disc["id"], inv2["id"], 4000)
        dispute = raise_dispute(e1["id"], inv2["id"], "Share")
        # Vector omits the second roster entry entirely.
        resp = api.resolve_dispute(
            dispute["id"],
            {"resolution_notes": "Partial",
             "adjusted_shares": [{"entry_id": e1["id"], "share_bp": 10000}]},
            TTO)
        validate_error(resp, ApiErrorId.ERR_SHARE_SUM_INVALID, 409)
        refreshed = validate_success(api.get_dispute(dispute["id"], ADMIN))
        assert refreshed["status"] == "OPEN"
