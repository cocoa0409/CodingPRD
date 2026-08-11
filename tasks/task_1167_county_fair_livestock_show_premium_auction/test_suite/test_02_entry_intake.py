"""Entry intake: payload well-formedness, posture gate, suspension, tag
uniqueness, deadline verification boundaries, ownership RBAC, listing
pagination, and terminal lockdown (PRD §2.1, §2.3, §2.5, §2.7, §3.1, §3.2).
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    advance_posture,
    api_client,
    assert_animal_entry,
    create_entry,
    create_entry_payload,
    create_exhibitor,
    create_fair,
    create_verified_entry,
    get_entry,
    make_exhibitor_headers,
    validate_error,
    validate_paginated,
    validate_success,
    verify_entry,
)

ADMIN = TEST_USERS["admin"]


def _fair_with_exhibitor(name="Fair T02", advance=True):
    fair = create_fair(name=name)
    if advance:
        advance_posture(fair["id"], "ENTRIES_OPEN")
    exhibitor = create_exhibitor(fair["id"])
    return fair, exhibitor


class TestEntryPayloadWellformedness:
    def test_entry_create_missing_required_species(self, api):
        """PRD §2.7: "payload well-formedness (failure: `ERR_INVALID_REQUEST`,
        covering missing required fields, invalid enum values, non-positive
        `weight_lbs`, an `ends_at` not after `starts_at`, a `weight_max_lbs`
        not greater than `weight_min_lbs`, non-positive `capacity`, and bad
        ranks)".

        Design: Corner/entities/entry_create_missing_required_species
        """
        fair, exhibitor = _fair_with_exhibitor("Fair C2")
        payload = create_entry_payload(fair["id"], exhibitor["id"])
        del payload["species"]
        resp = api_client.create_entry(
            payload, make_exhibitor_headers(exhibitor["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_entry_create_invalid_enum_species(self, api):
        """PRD §2.7: "payload well-formedness (failure: `ERR_INVALID_REQUEST`,
        covering missing required fields, invalid enum values, non-positive
        `weight_lbs`, an `ends_at` not after `starts_at`, a `weight_max_lbs`
        not greater than `weight_min_lbs`, non-positive `capacity`, and bad
        ranks)".

        Design: Corner/entities/entry_create_invalid_enum_species
        """
        fair, exhibitor = _fair_with_exhibitor("Fair C3")
        payload = create_entry_payload(
            fair["id"], exhibitor["id"], species="PIGEON"
        )
        resp = api_client.create_entry(
            payload, make_exhibitor_headers(exhibitor["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_entry_system_and_computed_fields_input_ignored(self, api):
        """PRD §3.2: "A fresh entry starts in `ENTERED` with
        `official_weight_lbs` null (it has never been weighed), `class_id`
        null (it has not been classified), `state_fair_qualified` false, and
        `disqualification_reason` null."

        Design: Corner/entities/entry_system_and_computed_fields_input_ignored
        """
        fair, exhibitor = _fair_with_exhibitor("Fair C4")
        entry = create_entry(fair["id"], exhibitor, tag_number="S-001")
        assert_animal_entry(entry)
        assert entry["status"] == "ENTERED"
        assert entry["official_weight_lbs"] is None
        assert entry["class_id"] is None
        assert entry["state_fair_qualified"] is False
        assert entry["disqualification_reason"] is None


class TestEntryIntakeGates:
    def test_entry_create_posture_forbidden_in_setup(self, api):
        """PRD §2.5: "Entry creation is allowed only in `ENTRIES_OPEN`; entry
        verification is allowed in `ENTRIES_OPEN` or `ENTRIES_LOCKED`; weigh-in
        and classification require `WEIGH_IN`; starting a ring slot and
        submitting placings require `SHOWING`; auction-lot operations require
        `AUCTION`; and invoice issue, invoice payments, premium approval, and
        premium payment all require `SETTLEMENT`. An operation attempted under
        the wrong posture is rejected with `ERR_POSTURE_FORBIDS` (HTTP 409)."

        Design: Corner/validations/entry_create_posture_forbidden_in_setup
        """
        fair, exhibitor = _fair_with_exhibitor("Fair V5", advance=False)
        resp = api_client.create_entry(
            create_entry_payload(fair["id"], exhibitor["id"]),
            make_exhibitor_headers(exhibitor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_POSTURE_FORBIDS)

    def test_exhibitor_suspended_blocks_entry_create(self, api):
        """PRD §3.1: "Suspending an exhibitor moves them to `SUSPENDED`: from
        that point, entry creation naming that exhibitor is rejected with
        `ERR_EXHIBITOR_SUSPENDED` (HTTP 409) no matter who files it, while
        their existing entries are unaffected."

        Design: Corner/validations/exhibitor_suspended_blocks_entry_create
        """
        fair, exhibitor = _fair_with_exhibitor("Fair V8")
        existing = create_entry(fair["id"], exhibitor, tag_number="S-001")
        suspended = validate_success(
            api_client.suspend_exhibitor(exhibitor["id"], ADMIN), 200
        )
        assert suspended["status"] == "SUSPENDED"

        resp = api_client.create_entry(
            create_entry_payload(
                fair["id"], exhibitor["id"], species="MARKET_LAMB",
                tag_number="L-001",
            ),
            make_exhibitor_headers(exhibitor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EXHIBITOR_SUSPENDED)
        assert get_entry(existing["id"])["status"] == "ENTERED"

    def test_duplicate_tag_number_returns_error(self, api):
        """PRD §3.2: "The `tag_number` must be unique within the fair — a
        duplicate is rejected with `ERR_DUPLICATE_TAG` (HTTP 409)."

        Design: Corner/validations/duplicate_tag_number_returns_error
        """
        fair, exhibitor = _fair_with_exhibitor("Fair V3")
        create_entry(fair["id"], exhibitor, tag_number="S-001")
        resp = api_client.create_entry(
            create_entry_payload(
                fair["id"], exhibitor["id"], species="MARKET_SWINE",
                tag_number="S-001",
            ),
            make_exhibitor_headers(exhibitor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_TAG)


class TestDeadlineVerification:
    def test_verify_nonexistent_entry_returns_not_found(self, api):
        """PRD §2.7: "existence of every referenced resource, validated
        left-to-right along the path identifiers first and then the body
        foreign keys (failure: `ERR_NOT_FOUND`)".

        Design: Corner/validations/verify_nonexistent_entry_returns_not_found
        """
        fair = create_fair(name="Fair V1")
        advance_posture(fair["id"], "ENTRIES_OPEN")
        resp = api_client.verify_entry(NON_EXISTENT_UUID, "APPROVE", ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_possession_deadline_missed_returns_error(self, api):
        """PRD §3.2: "Approval then checks the two deadlines in order, both
        boundaries inclusive: `ownership_acquired_at` must be on or before the
        fair's `ownership_deadline_at`, else `ERR_OWNERSHIP_DEADLINE_MISSED`
        (HTTP 422); then `possession_start_at` must be on or before the fair's
        `possession_deadline_at`, else `ERR_POSSESSION_DEADLINE_MISSED`
        (HTTP 422)."

        Design: Corner/validations/possession_deadline_missed_returns_error
        """
        fair, exhibitor = _fair_with_exhibitor("Fair V2")
        entry = create_entry(
            fair["id"], exhibitor, species="MARKET_GOAT", tag_number="G-001",
            possession_start_at="2026-06-16T00:00:00Z",
        )
        resp = api_client.verify_entry(entry["id"], "APPROVE", ADMIN)
        validate_error(resp, ApiErrorId.ERR_POSSESSION_DEADLINE_MISSED)
        assert get_entry(entry["id"])["status"] == "ENTERED"

    def test_ownership_deadline_exact_equality_passes_one_second_late_fails(self, api):
        """PRD §3.2: "Approval then checks the two deadlines in order, both
        boundaries inclusive: `ownership_acquired_at` must be on or before the
        fair's `ownership_deadline_at`, else `ERR_OWNERSHIP_DEADLINE_MISSED`
        (HTTP 422); then `possession_start_at` must be on or before the fair's
        `possession_deadline_at`, else `ERR_POSSESSION_DEADLINE_MISSED`
        (HTTP 422)."

        Design: Difficulty/boundary_precision_check/ownership_deadline_exact_equality_passes_one_second_late_fails
        """
        fair, exhibitor = _fair_with_exhibitor("Fair R6A")
        entry_ok = create_entry(
            fair["id"], exhibitor, species="MARKET_LAMB", tag_number="L-001",
            ownership_acquired_at="2026-06-01T00:00:00Z",
        )
        entry_late = create_entry(
            fair["id"], exhibitor, species="MARKET_LAMB", tag_number="L-002",
            ownership_acquired_at="2026-06-01T00:00:01Z",
        )
        verified = verify_entry(entry_ok["id"], "APPROVE")
        assert verified["status"] == "VERIFIED", (
            "ownership acquired exactly at the inclusive deadline must verify"
        )

        resp = api_client.verify_entry(entry_late["id"], "APPROVE", ADMIN)
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_DEADLINE_MISSED)
        assert get_entry(entry_late["id"])["status"] == "ENTERED"

    def test_ownership_deadline_not_consulted_on_reject(self, api):
        """PRD §3.2: "Verification is a `FairBoardAdmin` decision carrying
        `decision` — `APPROVE` or `REJECT` — plus an optional `note`."
        PRD §3.2: "Approval then checks the two deadlines in order, both
        boundaries inclusive: `ownership_acquired_at` must be on or before the
        fair's `ownership_deadline_at`, else `ERR_OWNERSHIP_DEADLINE_MISSED`
        (HTTP 422); then `possession_start_at` must be on or before the fair's
        `possession_deadline_at`, else `ERR_POSSESSION_DEADLINE_MISSED`
        (HTTP 422)."
        PRD §3.2: "An approved entry moves `ENTERED` → `VERIFIED`; a rejected
        one moves `ENTERED` → `REJECTED`, which is terminal."

        Design: Difficulty/boundary_precision_check/ownership_deadline_exact_equality_passes_one_second_late_fails
        """
        fair, exhibitor = _fair_with_exhibitor("Fair R6A-rej")
        entry = create_entry(
            fair["id"], exhibitor, species="MARKET_LAMB", tag_number="L-010",
            ownership_acquired_at="2026-06-02T00:00:00Z",
        )
        rejected = verify_entry(entry["id"], "REJECT")
        assert rejected["status"] == "REJECTED", (
            "rejection is unconditional on the approval-only deadline checks"
        )


class TestEntryOwnershipAndListing:
    def test_exhibitor_cannot_create_entry_for_another_exhibitor(self, api):
        """PRD §2.1: "When `X-User-Role` is `Exhibitor`, `X-User-ID` is the
        `id` of the acting Exhibitor record; ownership checks on any resource
        that references an exhibitor compare the resource's `exhibitor_id`
        field to `X-User-ID`, so an exhibitor creates entries, signs
        affidavits, and requests dispositions only for their own animals."
        PRD §2.1: "a caller whose role is not permitted for the endpoint, or
        who fails an entity-backed ownership check, is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/exhibitor_cannot_create_entry_for_another_exhibitor
        """
        fair = create_fair(name="Fair B1")
        advance_posture(fair["id"], "ENTRIES_OPEN")
        exh_a = create_exhibitor(fair["id"], full_name="Ann A")
        exh_b = create_exhibitor(
            fair["id"], full_name="Ben B", organization="FOUR_H"
        )
        resp = api_client.create_entry(
            create_entry_payload(
                fair["id"], exh_a["id"], species="MARKET_GOAT",
                tag_number="G-001",
            ),
            make_exhibitor_headers(exh_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_entries_list_pagination_defaults_and_has_more(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of returned items:
        it defaults to 10 when omitted, and any value below 1 or above 100 is
        invalid. The `offset` parameter skips a number of items from the front
        of the result set and defaults to 0. Every list response includes
        `limit`, `offset`, `total_count`, and `has_more` in the `meta` object
        of the envelope."

        Design: Corner/entities/entries_list_pagination_defaults_and_has_more
        """
        fair, exhibitor = _fair_with_exhibitor("Fair C8")
        for tag in ("S-001", "S-002", "S-003"):
            create_entry(fair["id"], exhibitor, tag_number=tag)

        data_default, meta_default = validate_paginated(
            api_client.list_entries(ADMIN)
        )
        assert len(data_default) == 3
        assert meta_default["limit"] == 10
        assert meta_default["offset"] == 0
        assert meta_default["total_count"] == 3
        assert meta_default["has_more"] is False

        page1, meta1 = validate_paginated(
            api_client.list_entries(ADMIN, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api_client.list_entries(ADMIN, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestDisqualifiedTerminalLockdown:
    def test_entry_disqualified_terminal_lockdown(self, api):
        """PRD §3.8: "It is permitted from `VERIFIED`, `WEIGHED`, `CLASSIFIED`,
        `SHOWN`, or `NOT_SOLD`; `SOLD` and `CLEARED` entries cannot be
        disqualified because the sale is final, and attempts there are rejected
        with `ERR_INVALID_STATE`."
        PRD §3.8: "A `FairBoardAdmin` disqualifies an entry manually with a
        `reason` recorded as `disqualification_reason`"

        Design: Corner/state_machines/entry_disqualified_terminal_lockdown
        """
        fair, exhibitor = _fair_with_exhibitor("Fair S5")
        entry = create_verified_entry(fair["id"], exhibitor, tag_number="S-001")
        disqualified = validate_success(
            api_client.disqualify_entry(entry["id"], "fraudulent papers", ADMIN),
            200,
        )
        assert disqualified["status"] == "DISQUALIFIED"
        assert disqualified["disqualification_reason"] == "fraudulent papers"

        again = api_client.disqualify_entry(entry["id"], "again", ADMIN)
        validate_error(again, ApiErrorId.ERR_INVALID_STATE)

        verify_resp = api_client.verify_entry(entry["id"], "APPROVE", ADMIN)
        validate_error(verify_resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_entry(entry["id"])["status"] == "DISQUALIFIED"
