"""Assessment gating, the patent decision, the prosecution docket with its
cyclic office-action loop, cost rollups, and the write-off review cascade."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_cost,
    assert_same_instant,
    confirm_entry,
    create_cost_payload,
    create_inventor,
    create_patent_application_payload,
    decision_payload,
    finalize_payload,
    get_disclosure,
    make_inventor_headers,
    setup_certified_compliance_report,
    setup_department_and_inventor,
    setup_patent_pursued_disclosure,
    submit_disclosure,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    add_roster_entry_payload,
    assessment_payload,
    create_compliance_report_payload,
)
from test_helpers.fixtures import api_client
from test_helpers.test_users import make_compliance_officer_headers

ADMIN = TEST_USERS["system_admin_headers"]
TTO = TEST_USERS["tto_headers"]
CO = TEST_USERS["compliance_officer_headers"]


def _pursued():
    return setup_patent_pursued_disclosure()


def _open_application(disc_id, docket="DKT-1", app_type="PROVISIONAL"):
    return validate_success(
        api_client.create_patent_application(
            disc_id,
            create_patent_application_payload(docket_number=docket,
                                              application_type=app_type),
            TTO), 201)


class TestAssessmentGate:
    def test_assessment_before_finalize_rejected(self, api):
        """PRD: "Recording the assessment requires the disclosure to be in
        `INVENTORSHIP_CONFIRMED` — any other state yields
        `ERR_DISCLOSURE_INVALID_STATE`".

        Design: Corner/state_machines/assessment_before_finalize_rejected
        """
        _, inv = setup_department_and_inventor()
        disc = submit_disclosure(inv)
        resp = api.record_assessment(disc["id"], assessment_payload(), TTO)
        validate_error(resp, ApiErrorId.ERR_DISCLOSURE_INVALID_STATE, 409)
        refreshed = validate_success(api.get_disclosure(disc["id"], ADMIN))
        assert refreshed["status"] == "INVENTORSHIP_REVIEW"

    def test_low_patentability_blocks_pursue_but_allows_shelve(self, api):
        """PRD: "A `PURSUE_PATENT` decision is gated: both the
        `patentability_rating` and the `market_rating` must be `HIGH` or
        `MEDIUM`, and if either is `LOW` the decision is refused with
        `ERR_ASSESSMENT_GATE_FAILED`; success moves the disclosure to
        `PATENT_PURSUED`. A `SHELF` decision moves it to the terminal
        `SHELVED` state."

        Design: Corner/state_machines/low_patentability_blocks_pursue_but_allows_shelve
        """
        _, inv = setup_department_and_inventor()
        disc = submit_disclosure(inv)
        entry = validate_success(
            api.add_roster_entry(disc["id"],
                                 add_roster_entry_payload(inv["id"], 10000), TTO),
            201)
        confirm_entry(entry["id"], inv["id"])
        version = get_disclosure(disc["id"])["version"]
        validate_success(api.finalize_inventorship(
            disc["id"], finalize_payload(version), TTO))
        validate_success(api.record_assessment(
            disc["id"], assessment_payload("LOW", "HIGH"), TTO))
        resp = api.record_decision(disc["id"], decision_payload("PURSUE_PATENT"), TTO)
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_GATE_FAILED, 409)
        shelved = validate_success(
            api.record_decision(disc["id"], decision_payload("SHELF"), TTO))
        assert shelved["status"] == "SHELVED"

    def test_terminal_disclosure_lockdown(self, api):
        """PRD: "Only a `PATENT_PURSUED` disclosure supports downstream
        commercialization: creating a patent application, forming a startup,
        or opening a license on a disclosure not in `PATENT_PURSUED` is
        refused with `ERR_DISCLOSURE_INVALID_STATE`."

        Design: Corner/state_machines/terminal_disclosure_lockdown
        """
        _, inv = setup_department_and_inventor()
        disc = submit_disclosure(inv)
        entry = validate_success(
            api.add_roster_entry(disc["id"],
                                 add_roster_entry_payload(inv["id"], 10000), TTO),
            201)
        confirm_entry(entry["id"], inv["id"])
        version = get_disclosure(disc["id"])["version"]
        validate_success(api.finalize_inventorship(
            disc["id"], finalize_payload(version), TTO))
        validate_success(api.record_assessment(
            disc["id"], assessment_payload("LOW", "LOW"), TTO))
        validate_success(
            api.record_decision(disc["id"], decision_payload("WAIVE_TO_INVENTORS"),
                                TTO))
        resp1 = api.create_patent_application(
            disc["id"], create_patent_application_payload(), TTO)
        validate_error(resp1, ApiErrorId.ERR_DISCLOSURE_INVALID_STATE, 409)
        resp2 = api.create_startup(
            disc["id"],
            {"name": "SpinCo", "founded_date": "2026-02-01T00:00:00Z",
             "equity_model": "FIXED"},
            TTO)
        validate_error(resp2, ApiErrorId.ERR_DISCLOSURE_INVALID_STATE, 409)


class TestPatentProsecutionCycle:
    def test_patent_prosecution_cycle_to_grant(self, api):
        """PRD: "An office action moves an application from `FILED` to
        `OFFICE_ACTION_RECEIVED`, and — because office actions recur — also
        from `RESPONSE_FILED` back to `OFFICE_ACTION_RECEIVED`. Recording a
        response via its `response_date` moves an application from
        `OFFICE_ACTION_RECEIVED` to `RESPONSE_FILED`. A grant, recorded with
        its `grant_date`, is reachable from `FILED` or `RESPONSE_FILED` and
        lands in the terminal `GRANTED` state."

        Design: Difficulty/non_linear_state_machine/patent_prosecution_cycle
        """
        ctx = _pursued()
        app = _open_application(ctx["disclosure"]["id"])
        seq = []
        seq.append(validate_success(api.record_office_action(
            app["id"], {"received_date": "2026-03-01T00:00:00Z"}, TTO))["status"])
        seq.append(validate_success(api.file_response(
            app["id"], {"response_date": "2026-04-01T00:00:00Z"}, TTO))["status"])
        # Second office action after a response: the cycle repeats.
        seq.append(validate_success(api.record_office_action(
            app["id"], {"received_date": "2026-05-01T00:00:00Z"}, TTO))["status"])
        seq.append(validate_success(api.file_response(
            app["id"], {"response_date": "2026-06-01T00:00:00Z"}, TTO))["status"])
        seq.append(validate_success(api.grant_application(
            app["id"], {"grant_date": "2026-07-01T00:00:00Z"}, TTO))["status"])
        assert seq == [
            "OFFICE_ACTION_RECEIVED", "RESPONSE_FILED",
            "OFFICE_ACTION_RECEIVED", "RESPONSE_FILED", "GRANTED",
        ], f"prosecution cycle sequence, got {seq}"

    def test_patent_cycle_then_abandon_from_response_filed(self, api):
        """PRD: "Abandonment is reachable from `FILED`,
        `OFFICE_ACTION_RECEIVED`, or `RESPONSE_FILED` — any other state
        yields `ERR_PATENT_INVALID_STATE` — and lands in the terminal
        `ABANDONED` state."

        Design: Difficulty/non_linear_state_machine/patent_prosecution_cycle
        """
        ctx = _pursued()
        app = _open_application(ctx["disclosure"]["id"])
        validate_success(api.record_office_action(
            app["id"], {"received_date": "2026-03-01T00:00:00Z"}, TTO))
        validate_success(api.file_response(
            app["id"], {"response_date": "2026-04-01T00:00:00Z"}, TTO))
        abandoned = validate_success(api.abandon_application(app["id"], TTO))
        assert abandoned["status"] == "ABANDONED"

    def test_grant_from_office_action_rejected(self, api):
        """PRD: "A grant, recorded with its `grant_date`, is reachable from
        `FILED` or `RESPONSE_FILED` and lands in the terminal `GRANTED`
        state. Every prosecution event validates the application's current
        status and refuses out-of-order events with
        `ERR_PATENT_INVALID_STATE`".

        Design: Corner/state_machines/grant_from_office_action_rejected
        """
        ctx = _pursued()
        app = _open_application(ctx["disclosure"]["id"])
        validate_success(api.record_office_action(
            app["id"], {"received_date": "2026-03-01T00:00:00Z"}, TTO))
        resp = api.grant_application(
            app["id"], {"grant_date": "2026-04-01T00:00:00Z"}, TTO)
        validate_error(resp, ApiErrorId.ERR_PATENT_INVALID_STATE, 409)
        refreshed = validate_success(api.get_patent_application(app["id"], ADMIN))
        assert refreshed["status"] == "OFFICE_ACTION_RECEIVED"

    def test_granted_patent_terminal_lockdown(self, api):
        """PRD: "A grant, recorded with its `grant_date`, is reachable from
        `FILED` or `RESPONSE_FILED` and lands in the terminal `GRANTED`
        state. Every prosecution event validates the application's current
        status and refuses out-of-order events with
        `ERR_PATENT_INVALID_STATE`".

        Design: Corner/state_machines/granted_patent_terminal_lockdown
        """
        ctx = _pursued()
        app = _open_application(ctx["disclosure"]["id"])
        granted = validate_success(api.grant_application(
            app["id"], {"grant_date": "2026-04-01T00:00:00Z"}, TTO))
        assert granted["status"] == "GRANTED"
        resp1 = api.abandon_application(app["id"], TTO)
        validate_error(resp1, ApiErrorId.ERR_PATENT_INVALID_STATE, 409)
        resp2 = api.record_office_action(
            app["id"], {"received_date": "2026-05-01T00:00:00Z"}, TTO)
        validate_error(resp2, ApiErrorId.ERR_PATENT_INVALID_STATE, 409)


class TestWriteOffCascadeAndCostRollups:
    def test_patent_abandon_writeoff_cascade_blocks_new_filings(self, api):
        """PRD: "In the first hop, every cost row of that application whose
        `reimbursement_status` is `UNREIMBURSED` and whose
        `reimbursed_amount_cents` is still 0 flips to `WRITTEN_OFF`".
        PRD: "In the third hop, if the recomputed `written_off_cost_cents`
        has reached at least 5,000,000 cents, the disclosure's
        `cost_writeoff_review_required` flips to true, blocking new patent
        applications on the disclosure until the office clears the review."

        Design: Difficulty/transitive_cascade/patent_abandon_writeoff_cascade
        """
        ctx = _pursued()
        app = _open_application(ctx["disclosure"]["id"])
        add_cost(app["id"], 3_000_000, incurred_date="2026-03-01T00:00:00Z")
        add_cost(app["id"], 2_500_000, cost_type="FILING_FEE",
                 incurred_date="2026-03-02T00:00:00Z")
        abandoned = validate_success(api.abandon_application(app["id"], TTO))
        assert abandoned["status"] == "ABANDONED"
        costs = validate_paginated(api.list_costs(app["id"], ADMIN))[0]
        assert len(costs) == 2
        for c in costs:
            assert c["reimbursement_status"] == "WRITTEN_OFF", \
                "hop 1 writes off every fully-unreimbursed cost row"
        disc = validate_success(api.get_disclosure(ctx["disclosure"]["id"], ADMIN))
        assert disc["unreimbursed_cost_cents"] == 0
        assert disc["written_off_cost_cents"] == 5_500_000
        assert disc["cost_writeoff_review_required"] is True, \
            "hop 3: 5,500,000 >= 5,000,000 flips the review flag"
        resp = api.create_patent_application(
            ctx["disclosure"]["id"],
            create_patent_application_payload(docket_number="DKT-2",
                                              filed_date="2026-08-15T00:00:00Z"),
            TTO)
        validate_error(resp, ApiErrorId.ERR_COST_REVIEW_REQUIRED, 422)

    def test_patent_abandon_below_threshold_keeps_filings_open(self, api):
        """PRD: "it is true whenever `written_off_cost_cents` reaches at
        least 5,000,000 cents (fifty thousand dollars of written-off
        prosecution spend). While the flag is true, opening a new patent
        application on that disclosure is refused with
        `ERR_COST_REVIEW_REQUIRED`".

        Design: Difficulty/transitive_cascade/patent_abandon_writeoff_cascade
        """
        ctx = _pursued()
        app = _open_application(ctx["disclosure"]["id"])
        add_cost(app["id"], 4_000_000)
        validate_success(api.abandon_application(app["id"], TTO))
        disc = validate_success(api.get_disclosure(ctx["disclosure"]["id"], ADMIN))
        assert disc["written_off_cost_cents"] == 4_000_000
        assert disc["cost_writeoff_review_required"] is False, \
            "below the threshold, the review flag stays false"
        second = validate_success(api.create_patent_application(
            ctx["disclosure"]["id"],
            create_patent_application_payload(docket_number="DKT-2",
                                              filed_date="2026-08-15T00:00:00Z"),
            TTO), 201)
        assert second["status"] == "FILED"

    def test_writeoff_threshold_exact_boundary(self, api):
        """PRD: "Whenever these rollups are recomputed — at cost creation, at
        distribution approval, at distribution cancellation, and during the
        abandon and license-termination cascades — the disclosure's
        `cost_writeoff_review_required` flag is re-evaluated: it is true
        whenever `written_off_cost_cents` reaches at least 5,000,000 cents".

        Design: Corner/state_machines/writeoff_threshold_exact_boundary
        """
        # Disclosure A: 4,999,999 written off (one cent below the threshold).
        ctx_a = _pursued()
        app_a = _open_application(ctx_a["disclosure"]["id"], "DKT-A")
        add_cost(app_a["id"], 4_999_999)
        # Disclosure B: exactly 5,000,000 written off.
        ctx_b = _pursued()
        app_b = _open_application(ctx_b["disclosure"]["id"], "DKT-B")
        add_cost(app_b["id"], 5_000_000)

        validate_success(api.abandon_application(app_a["id"], TTO))
        validate_success(api.abandon_application(app_b["id"], TTO))
        disc_a = validate_success(
            api.get_disclosure(ctx_a["disclosure"]["id"], ADMIN))
        disc_b = validate_success(
            api.get_disclosure(ctx_b["disclosure"]["id"], ADMIN))
        assert disc_a["cost_writeoff_review_required"] is False, \
            "4,999,999 is below the threshold"
        assert disc_b["cost_writeoff_review_required"] is True, \
            "exactly 5,000,000 reaches the threshold (>=, not >)"

    def test_cost_review_clear_resets_block(self, api):
        """PRD: "a `TechTransferOfficer` clears the block through the
        cost-review clear action, and clearing while the flag is false is
        refused with `ERR_COST_REVIEW_NOT_REQUIRED`. The clear is sticky
        until the next recompute once again crosses the threshold."

        Design: Corner/state_machines/cost_review_clear_resets_block
        """
        ctx = _pursued()
        app = _open_application(ctx["disclosure"]["id"])
        add_cost(app["id"], 5_500_000)
        validate_success(api.abandon_application(app["id"], TTO))
        cleared = validate_success(
            api.clear_cost_review(ctx["disclosure"]["id"], TTO))
        assert cleared["cost_writeoff_review_required"] is False
        second = validate_success(api.create_patent_application(
            ctx["disclosure"]["id"],
            create_patent_application_payload(docket_number="DKT-2",
                                              filed_date="2026-08-15T00:00:00Z"),
            TTO), 201)
        assert second["status"] == "FILED", "clearing re-enables new filings"
        resp = api.clear_cost_review(ctx["disclosure"]["id"], TTO)
        validate_error(resp, ApiErrorId.ERR_COST_REVIEW_NOT_REQUIRED, 409)

    def test_cost_rollups_reconcile_after_cost_create(self, api):
        """PRD: "Recording a cost immediately recomputes the application's
        and the disclosure's cost rollups per §2.9."
        PRD: "On each application, `total_cost_cents` is the sum of
        `amount_cents` over all of its cost rows regardless of status, and
        `unreimbursed_cost_cents` sums the outstanding remainder — the
        difference between `amount_cents` and `reimbursed_amount_cents` —
        over rows still `UNREIMBURSED`."

        Design: Corner/entities/disclosure_cost_rollups_reconcile_after_cost_create
        """
        ctx = _pursued()
        app = _open_application(ctx["disclosure"]["id"])
        add_cost(app["id"], 125_000, cost_type="FILING_FEE",
                 incurred_date="2026-03-01T00:00:00Z")
        add_cost(app["id"], 75_000, incurred_date="2026-03-02T00:00:00Z")
        disc = validate_success(api.get_disclosure(ctx["disclosure"]["id"], ADMIN))
        assert disc["unreimbursed_cost_cents"] == 200_000
        app_after = validate_success(api.get_patent_application(app["id"], ADMIN))
        assert app_after["total_cost_cents"] == 200_000
        assert app_after["unreimbursed_cost_cents"] == 200_000


class TestElectionOfTitleGate:
    def test_nonprovisional_requires_election_of_title(self, api):
        """PRD: "when the disclosure's funding is `FEDERAL` or `MIXED` and
        the application type is `NON_PROVISIONAL` or `PCT`, the disclosure
        must already have an election-of-title compliance report whose status
        is `SUBMITTED` or `AGENCY_ACCEPTED` — otherwise creation is refused
        with `ERR_TITLE_NOT_ELECTED`."

        Design: Difficulty/cross_entity_state_dependency/nonprovisional_filing_requires_election_of_title
        """
        ctx = setup_patent_pursued_disclosure(funding_source="FEDERAL")
        disc_id = ctx["disclosure"]["id"]
        resp = api.create_patent_application(
            disc_id,
            create_patent_application_payload(docket_number="DKT-NP",
                                              application_type="NON_PROVISIONAL",
                                              filed_date="2026-08-10T00:00:00Z"),
            TTO)
        validate_error(resp, ApiErrorId.ERR_TITLE_NOT_ELECTED, 409)

        # PROVISIONAL filings are exempt from the gate.
        prov = validate_success(api.create_patent_application(
            disc_id,
            create_patent_application_payload(docket_number="DKT-P",
                                              application_type="PROVISIONAL",
                                              filed_date="2026-08-10T00:00:00Z"),
            TTO), 201)
        assert prov["status"] == "FILED"

        # Once the election-of-title report is certified (SUBMITTED), the
        # NON_PROVISIONAL filing succeeds.
        setup_certified_compliance_report(disc_id, "ELECTION_OF_TITLE")
        np_app = validate_success(api.create_patent_application(
            disc_id,
            create_patent_application_payload(docket_number="DKT-NP2",
                                              application_type="NON_PROVISIONAL",
                                              filed_date="2026-08-11T00:00:00Z"),
            TTO), 201)
        assert np_app["status"] == "FILED"

    def test_pct_gated_and_agency_accepted_report_satisfies(self, api):
        """PRD: "the disclosure must already have an election-of-title
        compliance report whose status is `SUBMITTED` or `AGENCY_ACCEPTED` —
        otherwise creation is refused with `ERR_TITLE_NOT_ELECTED`."

        Design: Difficulty/cross_entity_state_dependency/nonprovisional_filing_requires_election_of_title
        """
        ctx = setup_patent_pursued_disclosure(funding_source="FEDERAL")
        disc_id = ctx["disclosure"]["id"]
        resp = api.create_patent_application(
            disc_id,
            create_patent_application_payload(docket_number="DKT-PCT",
                                              application_type="PCT",
                                              filed_date="2026-08-10T00:00:00Z"),
            TTO)
        validate_error(resp, ApiErrorId.ERR_TITLE_NOT_ELECTED, 409)

        report = setup_certified_compliance_report(disc_id, "ELECTION_OF_TITLE")
        accepted = validate_success(api.record_agency_response(
            report["id"], {"outcome": "ACCEPTED"},
            TEST_USERS["compliance_director_headers"]))
        assert accepted["status"] == "AGENCY_ACCEPTED"
        pct = validate_success(api.create_patent_application(
            disc_id,
            create_patent_application_payload(docket_number="DKT-PCT2",
                                              application_type="PCT",
                                              filed_date="2026-08-11T00:00:00Z"),
            TTO), 201)
        assert pct["status"] == "FILED"


class TestValidationOrdering:
    def test_not_found_beats_state_and_business(self, api):
        """PRD: "The pipeline runs: first, authentication headers (§2.1,
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); second, role and
        ownership authorization (`ERR_FORBIDDEN`); third, left-to-right
        existence of path identifiers (the appropriate not-found error,
        §2.7); ... fifth, state-machine legality".

        Design: Corner/validations/not_found_beats_state_and_business
        """
        resp = api.record_office_action(
            NON_EXISTENT_UUID, {"received_date": "2026-03-01T00:00:00Z"}, TTO)
        validate_error(resp, ApiErrorId.ERR_PATENT_APPLICATION_NOT_FOUND, 404)

    def test_schema_beats_state(self, api):
        """PRD: "Because schema validation precedes state checks, a malformed
        body is always `ERR_INVALID_REQUEST` even when the target is also in
        the wrong state".

        Design: Corner/validations/schema_beats_state
        """
        _, inv = setup_department_and_inventor()
        disc = submit_disclosure(inv)  # INVENTORSHIP_REVIEW: wrong state for decision
        resp = api.record_decision(disc["id"], {"decision": "BUY_NOW"}, TTO)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
