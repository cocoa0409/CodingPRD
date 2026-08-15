"""Bonus quote and milestone-split calculation tests (PRD §3.3, §3.4)."""
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
    submit_referral,
    setup_program,
    advance_referral_to_offer,
    hire_referral,
    get_campaign,
    get_hire_milestone,
    get_retention_milestone,
    get_employee,
    create_referral_payload,
    api_client,
)


class TestBonusQuoteMultiInputTiered:
    def test_bonus_quote_tier_campaign_multiplier_and_flat_addon(self, api):
        """PRD §3.3: "**Step 1 — tier base.** The `bonus_base_cents` is the tier amount
        for the requisition's `level`, read from the pinned policy" — and "**Step 3 —
        uplift computation.** If a campaign attaches and the referrer's `job_level` is not
        `EXECUTIVE`, the raw uplift is the tier base multiplied by the campaign's
        `multiplier_bps` and divided by 10000, rounded half-up to whole cents at this
        single rounding point, minus the tier base, plus the campaign's `flat_addon_cents`".
        PRD §3.2: "`tier_senior_cents` 300000".

        SENIOR base 300000 with multiplier 15000 and flat add-on 50000 yields uplift
        200000 and gross 500000.

        Design: Difficulty/combinatorial_formula/bonus_quote_multi_input_tiered
        """
        program = setup_program(
            req_overrides={"level": "SENIOR", "hard_to_fill": True, "req_number": "REQ-SR-1",
                           "title": "Sr Engineer"},
        )
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        camp = create_active_campaign(program["req"]["id"], budget_cents=1_000_000)

        resp = api.create_referral(
            create_referral_payload(
                referrer_id=emp["id"], job_requisition_id=program["req"]["id"],
                candidate_email="ca@x.com", candidate_full_name="C A",
            ),
            make_employee_headers(emp["id"]),
        )
        data = validate_success(resp, 201)
        assert data["bonus_base_cents"] == 300000
        assert data["campaign_uplift_cents"] == 200000
        assert data["bonus_total_cents"] == 500000
        assert data["campaign_id"] == camp["id"]

    def test_bonus_quote_reserves_campaign_budget(self, api):
        """PRD §3.3: "Attachment also reserves budget: the campaign's `reserved_cents`
        increases by the referral's `campaign_uplift_cents`".
        PRD §3.2: "The derived `payouts_count`, also starting at zero, tracks how many
        referrals are currently attached".

        After submission the campaign shows reserved 200000 and payouts_count 1.

        Design: Difficulty/combinatorial_formula/bonus_quote_multi_input_tiered
        """
        program = setup_program(
            req_overrides={"level": "SENIOR", "hard_to_fill": True, "req_number": "REQ-SR-1",
                           "title": "Sr Engineer"},
        )
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        camp = create_active_campaign(program["req"]["id"], budget_cents=1_000_000)

        resp = api.create_referral(
            create_referral_payload(
                referrer_id=emp["id"], job_requisition_id=program["req"]["id"],
                candidate_email="ca@x.com", candidate_full_name="C A",
            ),
            make_employee_headers(emp["id"]),
        )
        validate_success(resp, 201)

        camp_now = get_campaign(camp["id"])
        assert camp_now["reserved_cents"] == 200000
        assert camp_now["payouts_count"] == 1


class TestMilestoneSplitRoundingOrder:
    def test_milestone_split_hire_rounded_first_retention_absorbs(self, api):
        """PRD §3.4: "the `HIRE` milestone's `amount_cents` is the gross total multiplied
        by the policy's `hire_pct` and divided by 100, rounded half-up to whole cents —
        the hire share is rounded *first* — and it is created directly in `EARNED` status
        with `earned_at` stamped; the `RETENTION` milestone is created in `PENDING` with
        an `amount_cents` equal to the gross total minus the hire amount, so the two
        amounts always sum exactly to `bonus_total_cents`, the retention side absorbing
        the rounding."

        Gross 275001 splits HIRE 82500 / RETENTION 192501 (the 0.3 fraction lands on the
        retention side).

        Design: Difficulty/combinatorial_formula/milestone_split_rounding_order
        """
        program = setup_program()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        camp = create_active_campaign(
            program["req"]["id"], flat_addon_cents=50001, budget_cents=1_000_000,
            name="odd addon",
        )
        resp = api.create_referral(
            create_referral_payload(
                referrer_id=emp["id"], job_requisition_id=program["req"]["id"],
                candidate_email="ca@x.com", candidate_full_name="C A",
            ),
            make_employee_headers(emp["id"]),
        )
        ref = validate_success(resp, 201)
        # base 150000; raw uplift = round(150000*15000/10000) - 150000 + 50001 = 225000-150000+50001 = 125001
        assert ref["bonus_base_cents"] == 150000
        assert ref["campaign_uplift_cents"] == 125001
        assert ref["bonus_total_cents"] == 275001

        advance_referral_to_offer(ref["id"], program["rec"]["id"], program["hm"]["id"])
        hire_referral(ref["id"], program["hm"]["id"])

        pp = TEST_USERS["payroll_processor_headers"]
        milestones = get_success_data(api.list_referral_milestones(ref["id"], pp))
        by_kind = {m["kind"]: m for m in milestones}
        assert by_kind["HIRE"]["amount_cents"] == 82500, (
            f"HIRE must be round_half_up(275001*30/100) = 82500, got {by_kind['HIRE']['amount_cents']}"
        )
        assert by_kind["RETENTION"]["amount_cents"] == 192501, (
            f"RETENTION must absorb the remainder 192501, got {by_kind['RETENTION']['amount_cents']}"
        )

    def test_milestone_split_sums_exactly_to_gross(self, api):
        """PRD §3.4: "the two amounts always sum exactly to `bonus_total_cents`, the
        retention side absorbing the rounding."

        HIRE + RETENTION == 275001 exactly — no cent lost or duplicated.

        Design: Difficulty/combinatorial_formula/milestone_split_rounding_order
        """
        program = setup_program()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        create_active_campaign(
            program["req"]["id"], flat_addon_cents=50001, budget_cents=1_000_000,
            name="odd addon",
        )
        resp = api.create_referral(
            create_referral_payload(
                referrer_id=emp["id"], job_requisition_id=program["req"]["id"],
                candidate_email="ca@x.com", candidate_full_name="C A",
            ),
            make_employee_headers(emp["id"]),
        )
        ref = validate_success(resp, 201)
        advance_referral_to_offer(ref["id"], program["rec"]["id"], program["hm"]["id"])
        hire_referral(ref["id"], program["hm"]["id"])

        pp = TEST_USERS["payroll_processor_headers"]
        milestones = get_success_data(api.list_referral_milestones(ref["id"], pp))
        total = sum(m["amount_cents"] for m in milestones)
        assert total == 275001, f"HIRE + RETENTION must equal gross 275001, got {total}"
        assert total == ref["bonus_total_cents"]


class TestBonusQuoteEvaluationOrderCapClip:
    def test_cap_clips_total_but_not_uplift(self, api):
        """PRD §3.3: "the granted `campaign_uplift_cents` is then the smaller of that raw
        uplift and the campaign's remaining budget at that instant (`budget_cents` minus
        `reserved_cents` minus `spent_cents`)" — computed at step 3, and "**Step 5 —
        provisional cap headroom.** The provisional cap remaining is the pinned policy's
        `annual_cap_cents` minus the referrer's current `annual_provisional_cents`,
        evaluated before this bonus is counted." — and "**Step 6 — provisional gross.**
        The `bonus_total_cents` is the smaller of base plus uplift and the provisional
        cap remaining, floored at zero."

        With a prior 45000 EARNED milestone against a 200000 cap, the second referral's
        uplift is still 125000 (computed pre-clip) while the gross is clipped to 155000.

        Design: Difficulty/combinatorial_formula/bonus_quote_evaluation_order_cap_clip
        """
        program = setup_program(policy_overrides={"annual_cap_cents": 200000},
                                req_overrides={"openings": 5})
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        # First referral hired -> HIRE 45000 EARNED counts into the provisional accumulator
        ref1 = submit_referral(emp["id"], program["req"]["id"], candidate_email="c1@x.com",
                               candidate_full_name="C One")
        advance_referral_to_offer(ref1["id"], program["rec"]["id"], program["hm"]["id"])
        hire_referral(ref1["id"], program["hm"]["id"])

        emp_read = get_employee(emp["id"])
        assert emp_read["annual_provisional_cents"] == 45000

        # Second requisition with a covering campaign
        req2 = create_open_requisition(req_number="REQ-IC-2", title="Engineer 2")
        create_active_campaign(req2["id"], budget_cents=1_000_000, name="push")

        resp = api.create_referral(
            create_referral_payload(
                referrer_id=emp["id"], job_requisition_id=req2["id"],
                candidate_email="c2@x.com", candidate_full_name="C Two",
            ),
            make_employee_headers(emp["id"]),
        )
        data = validate_success(resp, 201)
        assert data["bonus_base_cents"] == 150000
        assert data["campaign_uplift_cents"] == 125000, (
            "uplift computed BEFORE the cap clip: round(150000*1.5)-150000+50000 = 125000"
        )
        assert data["bonus_total_cents"] == 155000, (
            f"min(150000+125000, 200000-45000) = 155000, got {data['bonus_total_cents']}"
        )

    def test_cap_headroom_consumed_by_quote(self, api):
        """PRD §3.3: "**Step 5 — provisional cap headroom.** The provisional cap remaining
        is the pinned policy's `annual_cap_cents` minus the referrer's current
        `annual_provisional_cents`, evaluated before this bonus is counted."
        PRD §3.5: "The `annual_provisional_cents` accumulator sums the `amount_cents` of
        milestones in `EARNED`, `APPROVED`, `BATCHED`, or `PAID` status".

        The quote consumed exactly the remaining cap headroom after the first 45000 EARNED
        milestone.

        Design: Difficulty/combinatorial_formula/bonus_quote_evaluation_order_cap_clip
        """
        program = setup_program(policy_overrides={"annual_cap_cents": 200000},
                                req_overrides={"openings": 5})
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        ref1 = submit_referral(emp["id"], program["req"]["id"], candidate_email="c1@x.com",
                               candidate_full_name="C One")
        advance_referral_to_offer(ref1["id"], program["rec"]["id"], program["hm"]["id"])
        hire_referral(ref1["id"], program["hm"]["id"])

        emp_pre = get_employee(emp["id"])
        assert emp_pre["annual_provisional_cents"] == 45000

        req2 = create_open_requisition(req_number="REQ-IC-2", title="Engineer 2")
        create_active_campaign(req2["id"], budget_cents=1_000_000, name="push")
        resp = api.create_referral(
            create_referral_payload(
                referrer_id=emp["id"], job_requisition_id=req2["id"],
                candidate_email="c2@x.com", candidate_full_name="C Two",
            ),
            make_employee_headers(emp["id"]),
        )
        data = validate_success(resp, 201)
        # gross clipped to exactly the remaining headroom
        assert data["bonus_total_cents"] == 200000 - 45000
