"""Preclearance workflow: review/decision chain, OCC, screens, approval lane."""
from test_helpers import (
    ApiErrorId,
    admin_headers,
    api_client,
    as_insider,
    as_officer,
    assert_same_instant,
    create_approved_request,
    create_current_person,
    create_manual_restricted_entry,
    create_officer,
    create_event_window,
    create_quarterly_window,
    create_submitted_request,
    create_under_review_request,
    decide_request,
    get_success_data,
    run_sweep,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _setup_voided_request(api, officer_email, person_email):
    """Approved request for ACME proposed 2026-08-10, voided by a later-created
    event window that activates over the proposed date."""
    set_logical_clock("2026-08-01T00:00:00Z")
    officer = create_officer(officer_email)
    person = create_current_person("Insider H", person_email)
    approved = create_approved_request(
        person, officer, quantity=100, ticker="ACME", side="BUY",
        proposed_trade_date="2026-08-10T00:00:00Z",
    )
    set_logical_clock("2026-08-01T06:00:00Z")
    win = create_event_window(officer, "ACME", "2026-08-09T00:00:00Z",
                              "2026-08-12T00:00:00Z")
    set_logical_clock("2026-08-09T00:00:00Z")
    run_sweep(officer)
    return officer, person, approved, win


class TestDecisionStateRules:
    def test_decision_on_submitted_request_rejected(self, api):
        """PRD §3.4: "Decision-time checks run in order: the request must be
        `UNDER_REVIEW` (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/preclearance_decision_before_review_rejected
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer_s1@x.com")
        person = create_current_person("Insider S1", "insider_s1@x.com")
        req = create_submitted_request(person, proposed_trade_date="2026-08-20T00:00:00Z")

        resp = decide_request(req, officer, "APPROVE", req["version"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        fresh = get_success_data(api.get_preclearance_request(req["id"], admin_headers()))
        assert fresh["status"] == "SUBMITTED"

    def test_withdraw_on_denied_request_rejected(self, api):
        """PRD §3.4: "A `DENY` outcome stamps the same decision fields, records
        `denial_reason` as `OFFICER_DISCRETION`, and terminates the request. `DENIED`
        is terminal in either flavor — officer discretion or the restricted-list
        cascade of §3.3. The requesting insider may withdraw their own request from
        `SUBMITTED` or `UNDER_REVIEW`, moving it to the terminal `WITHDRAWN`."

        Design: Corner/state_machines/withdraw_terminal_request_rejected
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer_s2@x.com")
        person = create_current_person("Insider S2", "insider_s2@x.com")
        reviewed = create_under_review_request(
            person, officer, proposed_trade_date="2026-08-20T00:00:00Z"
        )
        get_success_data(
            decide_request(reviewed, officer, "DENY", reviewed["version"],
                           denial_reason="OFFICER_DISCRETION")
        )
        resp = api.withdraw_preclearance_request(reviewed["id"], as_insider(person))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        fresh = get_success_data(
            api.get_preclearance_request(reviewed["id"], admin_headers())
        )
        assert fresh["status"] == "DENIED"
        assert fresh["denial_reason"] == "OFFICER_DISCRETION"

    def test_second_decision_on_approved_request_rejected(self, api):
        """PRD §3.4: "Decision-time checks run in order: the request must be
        `UNDER_REVIEW` (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/double_decision_second_attempt_rejected
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer_s3@x.com")
        person = create_current_person("Insider S3", "insider_s3@x.com")
        approved = create_approved_request(
            person, officer, quantity=10, proposed_trade_date="2026-08-20T00:00:00Z"
        )
        resp = decide_request(approved, officer, "APPROVE", approved["version"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        fresh = get_success_data(
            api.get_preclearance_request(approved["id"], admin_headers())
        )
        assert fresh["status"] == "APPROVED"


class TestApprovalValidityHorizon:
    def test_approval_valid_until_is_48_hours_after_decision(self, api):
        """PRD §3.4: "An `APPROVE` outcome stamps `decided_at` and `decided_by`,
        computes `approval_valid_until` as exactly 48 hours after the decision
        instant, initializes `remaining_quantity` to the full `quantity`, and
        increments `version`."

        Design: Corner/calculations/approval_valid_until_constant_applied
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer_c2@x.com")
        person = create_current_person("Insider C2", "insider_c2@x.com")
        approved = create_approved_request(
            person, officer, quantity=10, proposed_trade_date="2026-08-20T00:00:00Z"
        )
        assert_same_instant(approved["decided_at"], "2026-08-01T00:00:00Z", "decided_at")
        assert_same_instant(
            approved["approval_valid_until"], "2026-08-03T00:00:00Z",
            "approval_valid_until",
        )
        assert approved["remaining_quantity"] == 10

    def test_decision_with_stale_version_rejected(self, api):
        """PRD §2.7: "If the request's version has since advanced — a review
        transition or another recorded mutation moved it past the observed value —
        the decision is rejected with `ERR_STALE_VERSION` (HTTP 412), and the deciding
        officer must re-read the request and decide against its current version."

        Design: Corner/cross_cutting_layers/decision_stale_version_returns_412
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer_x1@x.com")
        person = create_current_person("Insider X1", "insider_x1@x.com")
        reviewed = create_under_review_request(
            person, officer, proposed_trade_date="2026-08-20T00:00:00Z"
        )
        resp = decide_request(reviewed, officer, "APPROVE", reviewed["version"] - 1)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        fresh = get_success_data(
            api.get_preclearance_request(reviewed["id"], admin_headers())
        )
        assert fresh["status"] == "UNDER_REVIEW"
        assert fresh["version"] == reviewed["version"]


class TestRequestListing:
    def test_list_requests_filtered_by_covered_person(self, api):
        """PRD §4: "List preclearance requests (paginated; filterable by
        `covered_person_id`, `status`)". PRD §2.3: "Paginated list responses carry
        `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the
        envelope."

        Design: Corner/endpoints/list_preclearance_requests_filtered_by_person
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        pa = create_current_person("Filter A", "filter_a@x.com", department="A")
        pb = create_current_person("Filter B", "filter_b@x.com", department="B")
        req_a = create_submitted_request(
            pa, ticker="ACME", side="BUY", quantity=10,
            proposed_trade_date="2026-08-20T00:00:00Z",
        )
        create_submitted_request(
            pb, ticker="BETA", side="SELL", quantity=5,
            proposed_trade_date="2026-08-21T00:00:00Z",
        )

        data, meta = validate_paginated(
            api.list_preclearance_requests(
                admin_headers(), params={"covered_person_id": pa["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["id"] == req_a["id"]
        assert data[0]["covered_person_id"] == pa["id"]

        _, meta_all = validate_paginated(api.list_preclearance_requests(admin_headers()))
        assert meta_all["total_count"] == 2


class TestValidationPriority:
    def test_decision_on_voided_request_returns_invalid_state(self, api):
        """PRD §2.9: "When several checks could fail on the same call, the system
        evaluates them in a fixed order and reports the first failure." PRD §3.4:
        "Decision-time checks run in order: the request must be `UNDER_REVIEW`
        (`ERR_INVALID_STATE`), segregation of duties forbids deciding one's own
        request (`ERR_SELF_ACTION_FORBIDDEN`), the restricted-list screen applies
        (`ERR_SECURITY_RESTRICTED`), the provisional blackout screen applies
        (`ERR_TRADE_IN_BLACKOUT`), and the version must match (`ERR_STALE_VERSION`,
        enforced before any side effect)."

        Design: Difficulty/priority_pair_validation_conflict/decision_on_voided_request_state_beats_temporal
        """
        officer, person, approved, win = _setup_voided_request(
            api, "officer9@x.com", "insider_h@x.com"
        )
        voided = get_success_data(
            api.get_preclearance_request(approved["id"], admin_headers())
        )
        assert voided["status"] == "VOIDED"

        resp = decide_request(voided, officer, "APPROVE", voided["version"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_rejected_decision_leaves_voided_request_untouched(self, api):
        """PRD §2.9: "When several checks could fail on the same call, the system
        evaluates them in a fixed order and reports the first failure." PRD §3.4:
        "Every `APPROVED` request whose `proposed_trade_date` falls inside the
        activating window's half-open interval, and to which that window applies,
        moves to `VOIDED`".

        Design: Difficulty/priority_pair_validation_conflict/decision_on_voided_request_state_beats_temporal
        """
        officer, person, approved, win = _setup_voided_request(
            api, "officer9b@x.com", "insider_h2@x.com"
        )
        voided = get_success_data(
            api.get_preclearance_request(approved["id"], admin_headers())
        )
        resp = decide_request(voided, officer, "APPROVE", voided["version"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = get_success_data(
            api.get_preclearance_request(approved["id"], admin_headers())
        )
        assert after["status"] == "VOIDED"
        window = get_success_data(api.get_blackout_window(win["id"], as_officer(officer)))
        assert window["status"] == "ACTIVE"

    def test_restricted_ticker_create_returns_security_restricted(self, api):
        """PRD §3.4: "the restricted-list screen first (`ERR_SECURITY_RESTRICTED`),
        then the compliance-hold screen (`ERR_COMPLIANCE_HOLD`), then the blackout
        screen (`ERR_TRADE_IN_BLACKOUT`)". PRD §2.9: "When several checks could fail
        on the same call, the system evaluates them in a fixed order and reports the
        first failure."

        Design: Difficulty/priority_pair_validation_conflict/restricted_security_beats_blackout_on_create
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer10@x.com")
        person = create_current_person("Insider I", "insider_i@x.com")
        create_manual_restricted_entry(officer, "ACME", note="pending deal")
        create_quarterly_window(officer, "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z")

        resp = api.create_preclearance_request(
            {
                "covered_person_id": person["id"],
                "security_ticker": "ACME",
                "trade_side": "BUY",
                "quantity": 10,
                "proposed_trade_date": "2026-08-10T00:00:00Z",
            },
            as_insider(person),
        )
        validate_error(resp, ApiErrorId.ERR_SECURITY_RESTRICTED)

    def test_rejected_creation_persists_no_request(self, api):
        """PRD §3.4: "the restricted-list screen first (`ERR_SECURITY_RESTRICTED`),
        then the compliance-hold screen (`ERR_COMPLIANCE_HOLD`), then the blackout
        screen (`ERR_TRADE_IN_BLACKOUT`)". PRD §2.9: "When several checks could fail
        on the same call, the system evaluates them in a fixed order and reports the
        first failure."

        Design: Difficulty/priority_pair_validation_conflict/restricted_security_beats_blackout_on_create
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer10b@x.com")
        person = create_current_person("Insider I2", "insider_i2@x.com")
        create_manual_restricted_entry(officer, "ACME", note="pending deal")
        create_quarterly_window(officer, "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z")

        resp = api.create_preclearance_request(
            {
                "covered_person_id": person["id"],
                "security_ticker": "ACME",
                "trade_side": "BUY",
                "quantity": 10,
                "proposed_trade_date": "2026-08-10T00:00:00Z",
            },
            as_insider(person),
        )
        validate_error(resp, ApiErrorId.ERR_SECURITY_RESTRICTED)
        _, meta = validate_paginated(
            api.list_preclearance_requests(
                admin_headers(), params={"covered_person_id": person["id"]}
            )
        )
        assert meta["total_count"] == 0


class TestDecisionGatedByWindowState:
    def test_decision_blocked_while_quarterly_window_scheduled(self, api):
        """PRD §3.4: "The same screen, same bypass, and same error code apply when an
        officer later approves the request." PRD §3.4: "A submission is blocked when a
        `SCHEDULED` or `ACTIVE` blackout window that applies to the request — every
        `QUARTERLY` window applies; an `EVENT_DRIVEN` window applies when its ticker
        matches the request's `security_ticker` — has a half-open interval containing
        the `proposed_trade_date`."

        Design: Difficulty/cross_entity_state_dependency/decision_gated_by_blackout_window_state
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer12@x.com")
        person = create_current_person("Insider L", "insider_l@x.com")
        reviewed = create_under_review_request(
            person, officer, quantity=100, proposed_trade_date="2026-08-10T00:00:00Z"
        )
        create_quarterly_window(officer, "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z")

        resp = decide_request(reviewed, officer, "APPROVE", reviewed["version"])
        validate_error(resp, ApiErrorId.ERR_TRADE_IN_BLACKOUT)

    def test_decision_succeeds_after_window_cancelled(self, api):
        """PRD §3.2: "An officer may cancel a window, but only from `SCHEDULED` — the
        record moves to `CANCELLED`, and attempting to cancel from any other state is
        `ERR_INVALID_STATE` (409)." PRD §3.4: "The same screen, same bypass, and same
        error code apply when an officer later approves the request."

        Design: Difficulty/cross_entity_state_dependency/decision_gated_by_blackout_window_state
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer12b@x.com")
        person = create_current_person("Insider L2", "insider_l2@x.com")
        reviewed = create_under_review_request(
            person, officer, quantity=100, proposed_trade_date="2026-08-10T00:00:00Z"
        )
        win = create_quarterly_window(
            officer, "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z"
        )
        validate_error(
            decide_request(reviewed, officer, "APPROVE", reviewed["version"]),
            ApiErrorId.ERR_TRADE_IN_BLACKOUT,
        )

        cancelled = get_success_data(
            api.cancel_blackout_window(win["id"], as_officer(officer))
        )
        assert cancelled["status"] == "CANCELLED"

        approved = validate_success(
            decide_request(reviewed, officer, "APPROVE", reviewed["version"])
        )
        assert approved["status"] == "APPROVED"


class TestApprovalLane:
    def test_proposed_date_at_lane_end_conflicts(self, api):
        """PRD §3.4: "if the same person and ticker already hold an `APPROVED` request
        whose closed approval window — the interval from its `decided_at` through its
        `approval_valid_until`, both ends inclusive — contains the new
        `proposed_trade_date`, submission is rejected with `ERR_OVERLAPPING_APPROVAL`."

        Design: Difficulty/resource_temporal_overlap/approval_lane_closed_interval_containment
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer15@x.com")
        person = create_current_person("Insider N", "insider_n@x.com")
        create_approved_request(
            person, officer, quantity=100, proposed_trade_date="2026-08-02T00:00:00Z"
        )
        resp = api.create_preclearance_request(
            {
                "covered_person_id": person["id"],
                "security_ticker": "ACME",
                "trade_side": "SELL",
                "quantity": 10,
                "proposed_trade_date": "2026-08-03T00:00:00Z",
            },
            as_insider(person),
        )
        validate_error(resp, ApiErrorId.ERR_OVERLAPPING_APPROVAL)

    def test_proposed_date_past_lane_end_accepted(self, api):
        """PRD §3.4: "if the same person and ticker already hold an `APPROVED` request
        whose closed approval window — the interval from its `decided_at` through its
        `approval_valid_until`, both ends inclusive — contains the new
        `proposed_trade_date`, submission is rejected with `ERR_OVERLAPPING_APPROVAL`."

        Design: Difficulty/resource_temporal_overlap/approval_lane_closed_interval_containment
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        officer = create_officer("officer15b@x.com")
        person = create_current_person("Insider N2", "insider_n2@x.com")
        create_approved_request(
            person, officer, quantity=100, proposed_trade_date="2026-08-02T00:00:00Z"
        )
        resp = api.create_preclearance_request(
            {
                "covered_person_id": person["id"],
                "security_ticker": "ACME",
                "trade_side": "SELL",
                "quantity": 10,
                "proposed_trade_date": "2026-08-04T00:00:00Z",
            },
            as_insider(person),
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "SUBMITTED"
