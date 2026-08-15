"""Deadline computation (calendar vs business basis, weekend shift, holidays),
filing timeliness boundaries, adjudication posture, and immediate consistency."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_appeal,
    appeal_determination,
    create_claim,
    create_employer,
    create_separation,
    create_state_rule,
    get_claim,
    get_determination,
    set_clock,
    setup_determined_claim,
    submit_response,
    validate_success,
    draft_response,
    attach_evidence,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["claims_analyst_headers"]
LIAISON = TEST_USERS["agency_liaison_headers"]


class TestResponseDeadlineDualBasis:
    def test_calendar_vs_business_basis_same_inputs(self, api):
        """PRD §2.6: "Under the `CALENDAR` basis, every day counts: the due date
        is the notice date plus the state's `response_window_days` calendar
        days. Under the `BUSINESS` basis, weekends and holidays never count, so
        identical inputs yield a later due date than the calendar basis."

        Design: Difficulty/dual_variant_calc/deadline_calendar_vs_business_basis
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX", response_window_days=10, window_basis="CALENDAR",
                          weekend_shift="NONE")
        create_state_rule("ZZ", response_window_days=10, window_basis="BUSINESS",
                          weekend_shift="NONE")
        employer = create_employer(legal_name="Acme")
        separation = create_separation(employer["id"])

        claim_cal = create_claim(employer["id"], separation["id"], state_code="XX",
                                 notice_received_at="2026-08-03T09:00:00Z")
        claim_biz = create_claim(employer["id"], separation["id"], state_code="ZZ",
                                 notice_received_at="2026-08-03T09:00:00Z")

        # CALENDAR: Mon 2026-08-03 + 10 days -> Thu 2026-08-13, pinned 17:00Z.
        assert claim_cal["response_due_at"] == "2026-08-13T17:00:00Z"
        # BUSINESS: ten weekdays after Mon 2026-08-03 -> Mon 2026-08-17.
        assert claim_biz["response_due_at"] == "2026-08-17T17:00:00Z"
        assert claim_cal["response_due_at"] != claim_biz["response_due_at"]

    def test_business_basis_skips_weekends_and_federal_holidays(self, api):
        """PRD §3.3: "each day falling Monday through Friday that is not a
        federal holiday decrements the counter by one, while Saturdays,
        Sundays, and federal holidays never decrement it, and the due date is
        the day the counter reaches zero."
        PRD §2.6: "The federal holiday calendar used by both bases — and by the
        weekend-shift rule below — is a fixed list of eleven 2026 dates:
        2026-01-01, 2026-01-19, 2026-02-16, 2026-05-25, 2026-06-19, 2026-07-03,
        2026-09-07, 2026-10-12, 2026-11-11, 2026-11-26, and 2026-12-25."

        Design: Difficulty/dual_variant_calc/deadline_calendar_vs_business_basis
        """
        set_clock("2026-09-04T09:00:00Z")
        create_state_rule("XB", response_window_days=1, window_basis="BUSINESS",
                          weekend_shift="NONE")
        create_state_rule("XC", response_window_days=1, window_basis="CALENDAR",
                          weekend_shift="NONE")
        employer = create_employer(legal_name="HolidayCo")
        separation = create_separation(employer["id"])

        claim_biz = create_claim(employer["id"], separation["id"], state_code="XB",
                                 notice_received_at="2026-09-04T09:00:00Z")
        claim_cal = create_claim(employer["id"], separation["id"], state_code="XC",
                                 notice_received_at="2026-09-04T09:00:00Z")

        # BUSINESS from Fri 2026-09-04: Sat/Sun skipped, Mon 2026-09-07 is a
        # federal holiday, so the single counting day is Tue 2026-09-08.
        assert claim_biz["response_due_at"] == "2026-09-08T17:00:00Z"
        # CALENDAR counts the next day regardless: Sat 2026-09-05.
        assert claim_cal["response_due_at"] == "2026-09-05T17:00:00Z"


class TestWeekendShift:
    def test_weekend_shift_moves_deadline_forward(self, api):
        """PRD §2.6: "When `weekend_shift` is `NEXT_BUSINESS_DAY`, a due date
        landing on a Saturday, Sunday, or federal holiday advances one day at a
        time until it lands on a business day; when `weekend_shift` is `NONE`,
        the computed date stands as-is."

        Design: Corner/calculations/weekend_shift_moves_deadline_forward
        """
        set_clock("2026-08-05T09:00:00Z")
        create_state_rule("WS", response_window_days=10, window_basis="CALENDAR",
                          weekend_shift="NEXT_BUSINESS_DAY")
        create_state_rule("WN", response_window_days=10, window_basis="CALENDAR",
                          weekend_shift="NONE")
        employer = create_employer(legal_name="WkndCo")
        separation = create_separation(employer["id"])

        claim_ws = create_claim(employer["id"], separation["id"], state_code="WS",
                                notice_received_at="2026-08-05T09:00:00Z")
        claim_wn = create_claim(employer["id"], separation["id"], state_code="WN",
                                notice_received_at="2026-08-05T09:00:00Z")

        # Wed 2026-08-05 + 10 calendar days = Sat 2026-08-15.
        assert claim_wn["response_due_at"] == "2026-08-15T17:00:00Z"
        # NEXT_BUSINESS_DAY walks Sat 15 -> Sun 16 -> Mon 2026-08-17.
        assert claim_ws["response_due_at"] == "2026-08-17T17:00:00Z"


class TestAppealTimelinessBoundary:
    def test_appeal_filed_exactly_at_deadline_is_on_time(self, api):
        """PRD §2.6: "the boundary between timely and late is always inclusive:
        a filing whose `filed_at` is exactly equal to the computed deadline is
        `ON_TIME`, not `LATE`."
        PRD §3.5: "its `appeal_due_at` is computed as the date part of
        `mailed_at` plus the state's `appeal_window_days` calendar days — the
        appeal window always counts calendar days regardless of `window_basis`
        — with `weekend_shift` applied and the result pinned to 17:00:00 UTC."

        Design: Difficulty/boundary_precision_check/appeal_filed_exactly_at_deadline_is_on_time
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX", appeal_window_days=30, weekend_shift="NONE")
        ctx = setup_determined_claim(mailed_at="2026-08-05T09:00:00Z")
        det = ctx["determination"]
        # 2026-08-05 + 30 calendar days = 2026-09-04, pinned to 17:00Z.
        assert det["appeal_due_at"] == "2026-09-04T17:00:00Z"

        set_clock("2026-09-04T17:00:00Z")
        appeal = appeal_determination(det["id"], appellant="EMPLOYER")
        assert_appeal(appeal)
        assert appeal["timeliness"] == "ON_TIME"
        assert appeal["status"] == "FILED"
        assert appeal["round_number"] == 1
        det_after = get_determination(det["id"])
        assert det_after["status"] == "APPEALED_BY_EMPLOYER"

    def test_claimant_appeal_at_deadline_flips_determination_by_appellant(self, api):
        """PRD §3.5: "A timely filing creates the appeal in `FILED` with
        `round_number` one, flips the determination to `APPEALED_BY_EMPLOYER`
        or `APPEALED_BY_CLAIMANT` according to the appellant, and moves the
        claim from `DETERMINED` to `HEARING_PENDING`."

        Design: Difficulty/boundary_precision_check/appeal_filed_exactly_at_deadline_is_on_time
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX", appeal_window_days=30, weekend_shift="NONE")
        ctx = setup_determined_claim(mailed_at="2026-08-05T09:00:00Z")
        det = ctx["determination"]

        set_clock("2026-09-04T17:00:00Z")
        appeal = appeal_determination(det["id"], appellant="CLAIMANT",
                                      grounds="Claimant contests the denial of waiting-week credit.",
                                      as_liaison=True)
        assert appeal["timeliness"] == "ON_TIME"
        assert appeal["status"] == "FILED"
        assert get_determination(det["id"])["status"] == "APPEALED_BY_CLAIMANT"
        assert get_claim(ctx["claim"]["id"])["status"] == "HEARING_PENDING"

    def test_late_appeal_dismissed_untimely(self, api):
        """PRD §3.5: "A late filing is detected at filing time: the appeal goes
        straight to `DISMISSED_UNTIMELY`, the determination becomes `FINAL`,
        and the claim stays `DETERMINED`."

        Design: Corner/validations/late_appeal_dismissed_untimely
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX", appeal_window_days=30, weekend_shift="NONE")
        ctx = setup_determined_claim(mailed_at="2026-08-05T09:00:00Z")
        det = ctx["determination"]
        assert det["appeal_due_at"] == "2026-09-04T17:00:00Z"

        # One second past the deadline.
        set_clock("2026-09-04T17:00:01Z")
        appeal = appeal_determination(det["id"], appellant="EMPLOYER",
                                      grounds="Filed one second late.")
        assert appeal["timeliness"] == "LATE"
        assert appeal["status"] == "DISMISSED_UNTIMELY"
        assert get_determination(det["id"])["status"] == "FINAL"
        assert get_claim(ctx["claim"]["id"])["status"] == "DETERMINED"


class TestAdjudicationPosture:
    def test_expedited_posture_near_deadline(self, api):
        """PRD §3.3: "While a claim sits in `NOTICE_RECEIVED` or
        `RESPONSE_IN_PROGRESS` and no more than 48 hours remain before
        `response_due_at`, its `adjudication_posture` reads `EXPEDITED`;
        otherwise it reads `STANDARD`."

        Design: Corner/cross_cutting_layers/expedited_posture_near_deadline
        """
        # At this clock reading the 2-day-window claim has 32 hours left
        # (within 48), the 10-day-window claim has over nine days left.
        set_clock("2026-08-04T09:00:00Z")
        create_state_rule("XX", response_window_days=2, window_basis="CALENDAR",
                          weekend_shift="NONE")
        create_state_rule("XY", response_window_days=10, window_basis="CALENDAR",
                          weekend_shift="NONE")
        employer = create_employer(legal_name="ExpPostCo")
        separation = create_separation(employer["id"])

        claim_fast = create_claim(employer["id"], separation["id"], state_code="XX",
                                  notice_received_at="2026-08-03T09:00:00Z")
        claim_slow = create_claim(employer["id"], separation["id"], state_code="XY",
                                  notice_received_at="2026-08-03T09:00:00Z")

        assert claim_fast["response_due_at"] == "2026-08-05T17:00:00Z"
        assert claim_fast["adjudication_posture"] == "EXPEDITED"
        assert claim_slow["response_due_at"] == "2026-08-13T17:00:00Z"
        assert claim_slow["adjudication_posture"] == "STANDARD"


class TestSubmitImmediateConsistency:
    def test_submit_response_immediate_visibility(self, api):
        """PRD §3.4: "On submission the server stamps `filed_at` from the
        logical clock and computes `timeliness`: `ON_TIME` when `filed_at` is
        at or before the claim's `response_due_at` — equality included — and
        `LATE` otherwise."
        PRD §1: "consistency is immediate — every filing, reversal, and
        reconciliation moves the affected ledgers at the moment it is
        recorded."

        Design: Corner/consistency_model/submit_response_immediate_visibility
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        employer = create_employer(legal_name="ImmCo")
        separation = create_separation(employer["id"])
        claim = create_claim(employer["id"], separation["id"])
        response = draft_response(claim["id"], response_type="NO_PROTEST",
                                  narrative="No protest.")
        attach_evidence(claim["id"], response["id"])

        set_clock("2026-08-04T09:00:00Z")
        submitted = submit_response(claim["id"], response["id"])
        assert submitted["filed_at"] == "2026-08-04T09:00:00Z"
        assert submitted["timeliness"] == "ON_TIME"
        assert submitted["status"] == "SUBMITTED"

        claim_after = get_claim(claim["id"])
        assert claim_after["status"] == "RESPONSE_SUBMITTED"
        assert claim_after["response_channel"] == "SELF"
