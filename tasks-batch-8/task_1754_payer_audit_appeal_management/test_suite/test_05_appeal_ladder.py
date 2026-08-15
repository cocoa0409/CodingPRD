"""Appeal creation gates, level derivation and track labels, filing deadlines,
lazy expiry with terminal lockdown, decision amount rules, and appeal listing
filters."""
from test_helpers import (
    ApiErrorId,
    add_claim_line,
    advance_clock,
    begin_payer_review,
    create_audit_case,
    create_issue_code,
    create_packet,
    create_payer,
    decide_appeal,
    decision_payload,
    denied_outcome,
    file_appeal,
    get_appeal,
    make_payer_agent_headers,
    open_appeal,
    paid_outcome,
    post_determination,
    setup_determined_case,
    setup_level3_appeal,
    submit_records,
    validate_error,
    validate_paginated,
)
from test_helpers import TEST_USERS

HIM = TEST_USERS["him_headers"]
SPECIALIST = TEST_USERS["specialist_headers"]
READER = TEST_USERS["reader_headers"]


class TestAppealCreation:
    def test_first_appeal_born_draft_level1_with_computed_deadline(self, api):
        """PRD §3.4: "The first appeal on a line opens at `LEVEL_1` with
        `prior_appeal_id` null."
        PRD §3.4: "At creation the appeal snapshots the line's current
        `denied_amount_cents` into `appealed_denied_cents`, opens in `DRAFT`"
        PRD §3.4: "A `LEVEL_1` appeal's deadline is the case's
        `determination_issued_at` plus the payer's `l1_deadline_days` days."
        PRD §3.4: "on `MEDICARE`, `LEVEL_1` through `LEVEL_5` map to
        `REDETERMINATION`, `RECONSIDERATION`, `ALJ`, `COUNCIL`, and `FEDERAL`"

        Design: Corner/state_machines/appeal_initial_state_and_deadline
        """
        ctx = setup_determined_case(billed_amounts=(100000,),
                                    issue_code="MED_NEC",
                                    issue_category="CLINICAL",
                                    issue_description="Medical necessity")
        appeal = open_appeal(ctx["lines"][0]["id"])
        assert appeal["status"] == "DRAFT"
        assert appeal["level"] == "LEVEL_1"
        assert appeal["level_label"] == "REDETERMINATION"
        assert appeal["filed_deadline_at"] == "2026-08-31T00:00:00Z", (
            "determination at 2026-08-01 plus l1_deadline_days 30")
        assert appeal["appealed_denied_cents"] == 100000
        assert appeal["prior_appeal_id"] is None

    def test_appeal_on_paid_line_and_second_concurrent_appeal_rejected(
            self, api):
        """PRD §3.4: "The line must currently be `DENIED` or
        `PARTIALLY_DENIED`, and no other appeal of the same line may be sitting
        in `DRAFT` or `PENDING_DECISION`; either violation is rejected with
        `ERR_LINE_NOT_APPEALABLE` (HTTP 409)."

        Design: Corner/validations/appeal_on_non_denied_line_rejected
        """
        payer = create_payer(name="P1")
        issue = create_issue_code("MED_NEC", "CLINICAL", "Medical necessity")
        case = create_audit_case(payer["id"])
        la = add_claim_line(case["id"], "A-1", "PA-1",
                            billed_amount_cents=100000)
        lb = add_claim_line(case["id"], "B-2", "PA-2",
                            service_start_date="2026-01-04T00:00:00Z",
                            service_end_date="2026-01-06T00:00:00Z",
                            billed_amount_cents=50000)
        submit_records(case["id"])
        begin_payer_review(case["id"], payer["id"])
        post_determination(case["id"], payer["id"], [
            paid_outcome(la["id"]),
            denied_outcome(lb["id"], 50000, issue["id"], "CLINICAL"),
        ])
        resp = api.create_appeal(la["id"], {}, SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_LINE_NOT_APPEALABLE)
        open_appeal(lb["id"])
        resp2 = api.create_appeal(lb["id"], {}, SPECIALIST)
        validate_error(resp2, ApiErrorId.ERR_LINE_NOT_APPEALABLE)


class TestAppealTrackLimits:
    def test_commercial_track_tops_out_at_level3(self, api):
        """PRD §3.4: "requires the next level to exist within the payer's
        track: the `MEDICARE` track reaches `LEVEL_5`, while the `COMMERCIAL`
        track ends at `LEVEL_3`. Asking for a level beyond the track maximum,
        or for the next level while the prior appeal is undecided, is rejected
        with `ERR_APPEAL_LEVEL_NOT_AVAILABLE` (HTTP 409)."
        PRD §3.4: "on `COMMERCIAL`, `LEVEL_1` through `LEVEL_3` map to
        `INTERNAL_1`, `INTERNAL_2`, and `EXTERNAL_REVIEW`."

        Design: Corner/validations/appeal_beyond_track_max_rejected
        """
        ctx, ap3 = setup_level3_appeal(
            billed=100000, payer_type="COMMERCIAL",
            issue_code="AUTH", issue_category="TECHNICAL")
        # Labels along the COMMERCIAL ladder (matched by level, order-free).
        appeals, _meta = validate_paginated(
            api.list_line_appeals(ctx["lines"][0]["id"], READER))
        labels = {a["level"]: a["level_label"] for a in appeals}
        assert labels == {"LEVEL_1": "INTERNAL_1", "LEVEL_2": "INTERNAL_2",
                          "LEVEL_3": "EXTERNAL_REVIEW"}
        # File the LEVEL_3 appeal (packet born READY with an empty required
        # set) and decide it UNFAVORABLE, then the next level must refuse.
        packet = create_packet(ap3["id"])
        assert packet["status"] == "READY"
        file_appeal(ap3["id"])
        decide_appeal(ap3["id"], ctx["payer"]["id"], "UNFAVORABLE", 100000)
        resp = api.create_appeal(ctx["lines"][0]["id"], {}, SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_APPEAL_LEVEL_NOT_AVAILABLE)


class TestAppealExpiry:
    def test_late_file_expires_and_terminal_lockdown(self, api):
        """PRD §3.4: "When the clock has passed `filed_deadline_at`, the filing
        attempt is rejected with `ERR_APPEAL_DEADLINE_PASSED` (HTTP 409) — and
        the attempt itself moves the appeal `DRAFT → EXPIRED`."
        PRD §3.4: "`DECIDED_FAVORABLE`, `DECIDED_PARTIAL`,
        `DECIDED_UNFAVORABLE`, `WITHDRAWN`, and `EXPIRED` are all terminal."

        Design: Corner/state_machines/expired_appeal_terminal_lockdown
        """
        ctx = setup_determined_case(billed_amounts=(100000,),
                                    issue_code="MED_NEC",
                                    issue_category="CLINICAL",
                                    issue_description="Medical necessity")
        appeal = open_appeal(ctx["lines"][0]["id"])
        advance_clock("2026-09-01T00:00:00Z")
        resp = api.file_appeal(appeal["id"], SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_APPEAL_DEADLINE_PASSED)
        assert get_appeal(appeal["id"])["status"] == "EXPIRED", (
            "The failed filing attempt itself expires the appeal")
        resp2 = api.file_appeal(appeal["id"], SPECIALIST)
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        resp3 = api.withdraw_appeal(appeal["id"], SPECIALIST)
        validate_error(resp3, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestAppealDecisions:
    def test_favorable_decision_with_nonzero_upheld_rejected(self, api):
        """PRD §3.5: "An `outcome` of `FAVORABLE` requires `upheld_cents` to be
        exactly zero."
        PRD §3.5: "Any other pairing of outcome and amount is rejected with
        `ERR_DETERMINATION_AMOUNT_INVALID` (HTTP 422)."

        Design: Corner/validations/decision_upheld_mismatch_rejected
        """
        ctx = setup_determined_case(billed_amounts=(100000,),
                                    issue_code="MED_NEC",
                                    issue_category="CLINICAL",
                                    issue_description="Medical necessity")
        appeal = open_appeal(ctx["lines"][0]["id"])
        file_appeal(appeal["id"])
        resp = api.decide_appeal(
            appeal["id"], decision_payload("FAVORABLE", 100),
            make_payer_agent_headers(ctx["payer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_DETERMINATION_AMOUNT_INVALID)
        assert get_appeal(appeal["id"])["status"] == "PENDING_DECISION"


class TestAppealListing:
    def test_appeals_filtered_by_prior_appeal(self, api, reader_headers):
        """PRD §3.4: "The appeal register lists appeals with optional
        `audit_case_id`, `claim_line_id`, `prior_appeal_id`, `status`, and
        `level` filters."
        PRD §3.4: "Each subsequent appeal opens at the previous appeal's level
        plus one, with `prior_appeal_id` referencing the appeal at the previous
        level whose decision opened this one."

        Design: Corner/endpoints/appeals_filtered_by_prior_appeal
        """
        ctx = setup_determined_case(billed_amounts=(100000,),
                                    issue_code="MED_NEC",
                                    issue_category="CLINICAL",
                                    issue_description="Medical necessity")
        line_id = ctx["lines"][0]["id"]
        payer_id = ctx["payer"]["id"]
        ap1 = open_appeal(line_id)
        file_appeal(ap1["id"])
        decide_appeal(ap1["id"], payer_id, "UNFAVORABLE", 100000)
        ap2 = open_appeal(line_id)
        assert ap2["prior_appeal_id"] == ap1["id"]
        assert ap2["level"] == "LEVEL_2"
        data, meta = validate_paginated(api.list_appeals(
            reader_headers, params={"prior_appeal_id": ap1["id"]}))
        assert meta["total_count"] == 1
        assert data[0]["id"] == ap2["id"]
        assert data[0]["level"] == "LEVEL_2"


class TestPacketLookup:
    def test_appeal_without_packet_returns_empty_collection(self, api,
                                                            reader_headers):
        """PRD §3.6: "Reading an appeal's packet returns a collection
        containing zero or one element"

        Design: Corner/endpoints/packet_lookup_returns_empty_array
        """
        ctx = setup_determined_case(billed_amounts=(100000,),
                                    issue_code="MED_NEC",
                                    issue_category="CLINICAL",
                                    issue_description="Medical necessity")
        appeal = open_appeal(ctx["lines"][0]["id"])
        data, meta = validate_paginated(
            api.get_appeal_evidence_packet(appeal["id"], reader_headers))
        assert data == [] and meta["total_count"] == 0, (
            "A packet-less appeal returns an empty collection, not an error")


class TestAppealRbac:
    def test_him_coordinator_cannot_file_appeal(self, api, him_headers):
        """PRD §2.1: "An attempt to perform an operation outside the caller's
        designated role is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §3.4: "Filing is performed by an `AppealsSpecialist`."

        Design: Corner/rbac/him_cannot_file_appeal
        """
        ctx = setup_determined_case(billed_amounts=(100000,),
                                    issue_code="MED_NEC",
                                    issue_category="CLINICAL",
                                    issue_description="Medical necessity")
        appeal = open_appeal(ctx["lines"][0]["id"])
        resp = api.file_appeal(appeal["id"], him_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        assert get_appeal(appeal["id"])["status"] == "DRAFT"
