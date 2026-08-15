"""External referrals: send/dispose lifecycle, compensating withdraw, SLA breach."""
from datetime import datetime, timedelta

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_case,
    create_referral_payload,
    create_school,
    get_case,
    list_case_referrals,
    make_team_lead_headers,
    make_threat_assessor_headers,
    send_referral,
    set_clock,
    setup_case_under_assessment,
    triage_case,
    validate_error,
    validate_paginated,
    validate_success,
)

TA1 = make_threat_assessor_headers("ta_1")
TL1 = TEST_USERS["team_lead_headers"]


def _parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _setup_triaged_case():
    school = create_school(name="Invariant HS", school_code="IHS",
                           enrollment_count=540)
    case = create_case(school["id"], subject_alias="STU-I1",
                       summary="invariant case")
    triage_case(case["id"])
    return case


class TestSendWithdrawInvariant:
    def test_send_increments_open_referral_count(self, api):
        """PRD: "Creation is the send: the referral is born in `SENT` status,
        `auto_created` false, and the system writes `REFERRAL_SENT`."
        PRD: "Withdrawing moves it to `WITHDRAWN` and writes
        `REFERRAL_WITHDRAWN`; withdrawal is the compensating action for the
        send, returning the count of the case's `SENT` referrals to its
        pre-send value."

        Design: Difficulty/compensating_invariant/referral_send_withdraw_conserves_open_count
        """
        case = _setup_triaged_case()
        _before, meta_before = validate_paginated(api.list_case_referrals(
            case["id"], TL1, params={"status": "SENT"}))
        assert meta_before["total_count"] == 0

        referral = send_referral(case["id"], referral_type="MENTAL_HEALTH",
                                 agency_name="County MH", urgency="ROUTINE")
        assert referral["status"] == "SENT"
        assert referral["auto_created"] is False

        _after, meta_after = validate_paginated(api.list_case_referrals(
            case["id"], TL1, params={"status": "SENT"}))
        assert meta_after["total_count"] == 1, (
            "creation is the send: the open-referral count rises by one"
        )

    def test_withdraw_returns_open_referral_count_to_pre_send_value(self, api):
        """PRD: "Withdrawing moves it to `WITHDRAWN` and writes
        `REFERRAL_WITHDRAWN`; withdrawal is the compensating action for the
        send, returning the count of the case's `SENT` referrals to its
        pre-send value."

        Design: Difficulty/compensating_invariant/referral_send_withdraw_conserves_open_count
        """
        case = _setup_triaged_case()
        referral = send_referral(case["id"], referral_type="MENTAL_HEALTH",
                                 agency_name="County MH", urgency="ROUTINE")

        withdrawn = validate_success(
            api.withdraw_referral(referral["id"], TL1), 200)
        assert withdrawn["status"] == "WITHDRAWN"

        _after, meta_after = validate_paginated(api.list_case_referrals(
            case["id"], TL1, params={"status": "SENT"}))
        assert meta_after["total_count"] == 0, (
            "the compensating withdraw returns the SENT count to its "
            "pre-send value"
        )


class TestReferralStateGuards:
    def test_referral_acknowledge_twice_returns_not_sent(self, api):
        """PRD: "From `SENT`, three dispositions exist, each requiring the
        referral to still be `SENT` (`ERR_REFERRAL_NOT_SENT` otherwise) and
        each open to either a `ThreatAssessor` or a `TeamLead`."

        Design: Corner/state_machines/referral_acknowledge_twice_returns_not_sent
        """
        case = _setup_triaged_case()
        referral = send_referral(case["id"], referral_type="MENTAL_HEALTH",
                                 agency_name="County MH", urgency="ROUTINE")
        acked = validate_success(api.acknowledge_referral(referral["id"], TA1), 200)
        assert acked["status"] == "ACKNOWLEDGED"

        resp = api.acknowledge_referral(referral["id"], TL1)
        validate_error(resp, ApiErrorId.ERR_REFERRAL_NOT_SENT)


class TestReferralSlaBreach:
    def test_referral_unbreached_at_exact_deadline(self, api):
        """PRD: "Its response deadline `sla_due_at` is computed at the send
        instant — 72 hours later for an `URGENT` referral, 240 hours later for
        a `ROUTINE` one."
        PRD: "When a clock advance carries the current time past a referral's
        `sla_due_at` while the referral is still `SENT`, the server sets
        `sla_breached` to true, sets the case's `escalation_flag` to true, and
        writes `REFERRAL_SLA_BREACHED` — a lapsed agency response is an
        unresolved obligation that will, among other things, block case
        closure."

        Design: Corner/cross_cutting_complexity_layers/referral_sla_breach_fires_on_clock_advance
        """
        case = _setup_triaged_case()
        referral = send_referral(case["id"], referral_type="LAW_ENFORCEMENT",
                                 agency_name="City PD", urgency="URGENT")
        expected_due = _parse(referral["created_at"]) + timedelta(hours=72)
        assert _parse(referral["sla_due_at"]) == expected_due, (
            f"sla_due_at must be the send instant plus 72 hours: "
            f"{referral['created_at']} -> {referral['sla_due_at']}"
        )
        assert _parse(referral["sla_due_at"]) == _parse("2026-08-04T00:00:00Z")

        set_clock("2026-08-04T00:00:00Z")
        referrals, meta = validate_paginated(api.list_case_referrals(
            case["id"], TL1, params={"status": "SENT"}))
        assert meta["total_count"] == 1
        assert referrals[0]["sla_breached"] is False, (
            "the breach requires the clock strictly past the deadline"
        )

    def test_referral_breaches_one_second_past_deadline(self, api):
        """PRD: "When a clock advance carries the current time past a
        referral's `sla_due_at` while the referral is still `SENT`, the server
        sets `sla_breached` to true, sets the case's `escalation_flag` to
        true, and writes `REFERRAL_SLA_BREACHED` — a lapsed agency response is
        an unresolved obligation that will, among other things, block case
        closure."

        Design: Corner/cross_cutting_complexity_layers/referral_sla_breach_fires_on_clock_advance
        """
        case = _setup_triaged_case()
        referral = send_referral(case["id"], referral_type="LAW_ENFORCEMENT",
                                 agency_name="City PD", urgency="URGENT")

        set_clock("2026-08-04T00:00:01Z")
        referrals, meta = validate_paginated(api.list_case_referrals(
            case["id"], TL1, params={"status": "SENT"}))
        assert meta["total_count"] == 1
        assert referrals[0]["sla_breached"] is True

        case_after = get_case(case["id"])
        assert case_after["escalation_flag"] is True, (
            "an SLA breach escalates the case"
        )
