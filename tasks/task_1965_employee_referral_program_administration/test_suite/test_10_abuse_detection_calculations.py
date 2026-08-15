"""Abuse auto-detection, risk decay, cooldown clamp, and executive-uplift tests
(PRD §3.3, §3.7, §3.1, §3.2)."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_employee_headers,
    create_employee,
    create_open_requisition,
    create_active_policy,
    create_active_campaign,
    create_candidate,
    submit_referral,
    setup_program,
    get_employee,
    get_campaign,
    list_employee_abuse_cases,
    raise_abuse_case,
    confirm_abuse_case,
    set_clock,
    create_referral_payload,
    build_user_headers,
    api_client,
    assert_instant_eq,
)


class TestVelocityThreshold:
    def test_velocity_threshold_auto_case_at_limit(self, api):
        """PRD §3.3: "**velocity**: counting the referrer's referrals whose `submitted_at`
        falls within the closed window from seven days (604800 seconds) before the
        logical now up to and including now — the new referral included — the system
        auto-raises an abuse case of `case_type` `VELOCITY` with `raised_by_user_id`
        `system`, naming the new referral, whenever that count is at least the active
        policy's `velocity_limit`; the submission itself still succeeds."
        PRD §3.2: "`velocity_limit` 5".

        Four submissions raise nothing; the fifth succeeds AND raises one VELOCITY case.

        Design: Corner/calculations/velocity_threshold_auto_case_at_limit
        """
        create_active_policy()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        req = create_open_requisition(openings=5)

        for i in range(1, 5):
            resp = api.create_referral(
                create_referral_payload(
                    referrer_id=emp["id"], job_requisition_id=req["id"],
                    candidate_email=f"c{i}@x.com", candidate_full_name=f"C {i}",
                ),
                make_employee_headers(emp["id"]),
            )
            validate_success(resp, 201)

        cases_pre = list_employee_abuse_cases(emp["id"])
        assert cases_pre == [], f"no cases after 4 submissions, got {cases_pre}"

        resp5 = api.create_referral(
            create_referral_payload(
                referrer_id=emp["id"], job_requisition_id=req["id"],
                candidate_email="c5@x.com", candidate_full_name="C Five",
            ),
            make_employee_headers(emp["id"]),
        )
        data5 = validate_success(resp5, 201)
        assert data5["status"] == "SUBMITTED", "the 5th submission itself still succeeds"

        cases_post = list_employee_abuse_cases(emp["id"])
        assert len(cases_post) == 1, f"exactly one case after the 5th submission, got {cases_post}"
        assert cases_post[0]["case_type"] == "VELOCITY"
        assert cases_post[0]["raised_by_user_id"] == "system"
        assert cases_post[0]["referral_id"] == data5["id"]


class TestFraudRiskDecay:
    def test_fraud_risk_decay_after_halflife(self, api):
        """PRD §3.7: "Each confirmed case contributes its `risk_weight` multiplied by one
        half raised to the power of its age in half-lives: the case's age is the whole
        days between `confirmed_at` and the logical now (elapsed seconds divided by 86400
        and rounded down), divided by 180 using real division, and one half is raised to
        that quotient. The contributions are summed, the total is rounded half-up to an
        integer, and the score is capped at 500. Whenever the score is at least 100, the
        employee's `referral_suspended` flag is true" and "50 for `RESUME_FARM`".

        50 at confirmation; exactly one 180-day halflife later (2027-01-28) it decays to
        25; never suspended.

        Design: Corner/calculations/fraud_risk_decay_after_halflife
        """
        emp = create_employee(employee_number="E102", full_name="Shady S", email="shady@corp.com")
        case = raise_abuse_case(emp["id"], "RESUME_FARM")
        confirm_abuse_case(case["id"])

        emp_t0 = get_employee(emp["id"])
        assert emp_t0["risk_score"] == 50
        assert emp_t0["referral_suspended"] is False

        set_clock("2027-01-28T00:00:00Z")
        emp_t1 = get_employee(emp["id"])
        assert emp_t1["risk_score"] == 25, (
            f"50 * 0.5 ** (180/180) = 25 at exactly one halflife, got {emp_t1['risk_score']}"
        )
        assert emp_t1["referral_suspended"] is False


class TestCooldownMonthEndClamp:
    def test_cooldown_month_end_clamp(self, api):
        """PRD §2.4: "*Calendar-month addition* (used for candidate cooldowns) adds
        whole months to a timestamp and clamps the day-of-month to the target month's
        last day when the target month is shorter: for example, six months after
        2026-01-31 is 2026-07-31, while six months after 2025-08-31 is 2026-02-28."

        2025-08-31 + 6 months lands on 2026-02-28.

        Design: Corner/calculations/cooldown_month_end_clamp
        """
        ta = TEST_USERS["talent_admin_headers"]
        resp = api.create_candidate(
            {
                "full_name": "Clamp C", "email": "clamp@x.com",
                "prior_application_at": "2025-08-31T00:00:00Z",
            },
            ta,
        )
        data = validate_success(resp, 201)
        assert_instant_eq(data["cooldown_until"], "2026-02-28T00:00:00Z")


class TestDuplicateRingDetection:
    def test_duplicate_ring_auto_case_at_third_referrer(self, api):
        """PRD §3.3: "**duplicate-ring detection**: counting the distinct referrers over
        non-terminal referrals for the same candidate with `submitted_at` inside the
        rolling ninety-day window up to now, the system auto-raises an abuse case of
        `case_type` `DUPLICATE_RING` with `raised_by_user_id` `system` against the newest
        referral's referrer whenever that distinct count reaches at least three."

        The first two referrals raise nothing; the third succeeds and auto-raises
        DUPLICATE_RING on the third referrer only.

        Design: Corner/calculations/duplicate_ring_auto_case_at_third_referrer
        """
        create_active_policy()
        cand = create_candidate(full_name="Pop P", email="pop@x.com")
        emp1 = create_employee(employee_number="E101", full_name="Ann A", email="anna@corp.com")
        emp2 = create_employee(employee_number="E102", full_name="Bob B", email="bob@corp.com")
        emp3 = create_employee(employee_number="E103", full_name="Cid C", email="cid@corp.com")
        req1 = create_open_requisition(req_number="REQ-1", title="Role 1")
        req2 = create_open_requisition(req_number="REQ-2", title="Role 2")
        req3 = create_open_requisition(req_number="REQ-3", title="Role 3")

        for emp, req in ((emp1, req1), (emp2, req2)):
            resp = api.create_referral(
                {"referrer_id": emp["id"], "job_requisition_id": req["id"],
                 "candidate_id": cand["id"]},
                make_employee_headers(emp["id"]),
            )
            validate_success(resp, 201)

        assert list_employee_abuse_cases(emp1["id"]) == []
        assert list_employee_abuse_cases(emp2["id"]) == []

        resp3 = api.create_referral(
            {"referrer_id": emp3["id"], "job_requisition_id": req3["id"],
             "candidate_id": cand["id"]},
            make_employee_headers(emp3["id"]),
        )
        data3 = validate_success(resp3, 201)
        assert data3["status"] == "SUBMITTED", "the ring check never blocks intake"

        cases3 = list_employee_abuse_cases(emp3["id"])
        assert len(cases3) == 1
        assert cases3[0]["case_type"] == "DUPLICATE_RING"
        assert cases3[0]["raised_by_user_id"] == "system"
        assert cases3[0]["referral_id"] == data3["id"]

        # only the newest referrer is flagged
        assert list_employee_abuse_cases(emp1["id"]) == []
        assert list_employee_abuse_cases(emp2["id"]) == []


class TestExecutiveReferrerNoUplift:
    def test_executive_referrer_gets_no_campaign_uplift(self, api):
        """PRD §3.3: "If the referrer is an `EXECUTIVE`, the uplift is zero — executives
        earn the base tier only — yet the campaign still attaches and still counts toward
        `payouts_count`."
        PRD §3.2: "`tier_senior_cents` 300000".

        An EXECUTIVE referrer (different department, so not excluded) attaches the
        campaign with zero uplift and bare-tier gross.

        Design: Corner/state_machines/executive_referrer_gets_no_campaign_uplift
        """
        create_active_policy()
        exec_emp = create_employee(
            employee_number="E105", full_name="Exec E", email="exec@corp.com",
            department="SALES", job_level="EXECUTIVE",
        )
        req = create_open_requisition(
            req_number="REQ-SR-1", title="Sr Engineer", level="SENIOR", hard_to_fill=True,
        )
        camp = create_active_campaign(req["id"], budget_cents=1_000_000, name="push")

        resp = api.create_referral(
            create_referral_payload(
                referrer_id=exec_emp["id"], job_requisition_id=req["id"],
                candidate_email="cx@x.com", candidate_full_name="C X",
            ),
            make_employee_headers(exec_emp["id"]),
        )
        data = validate_success(resp, 201)
        assert data["campaign_id"] == camp["id"]
        assert data["campaign_uplift_cents"] == 0
        assert data["bonus_total_cents"] == 300000

        camp_now = get_campaign(camp["id"])
        assert camp_now["payouts_count"] == 1
        assert camp_now["reserved_cents"] == 0
