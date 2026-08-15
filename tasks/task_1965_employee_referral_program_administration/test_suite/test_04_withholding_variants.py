"""Tax withholding variant tests (PRD §3.6)."""
from test_helpers import (
    validate_success,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_employee_headers,
    create_employee,
    create_open_requisition,
    create_active_policy,
    submit_referral,
    setup_program,
    setup_verified_tax_profile,
    advance_referral_to_offer,
    hire_referral,
    get_hire_milestone,
    create_open_batch,
    add_milestone_to_batch,
    api_client,
)


def _hire_with_verified_profile(api, program, emp_overrides, profile_overrides, candidate_email):
    """Create employee + verified tax profile + hired IC referral; return (emp, referral)."""
    emp = create_employee(**emp_overrides)
    setup_verified_tax_profile(emp["id"], **profile_overrides)
    ref = submit_referral(emp["id"], program["req"]["id"], candidate_email=candidate_email)
    advance_referral_to_offer(ref["id"], program["rec"]["id"], program["hm"]["id"])
    hire_referral(ref["id"], program["hm"]["id"])
    return emp, ref


class TestTaxWithholdingFlatVsAggregate:
    def test_flat_variant_withholding(self, api):
        """PRD §3.6: "Under `FLAT`, the rate is the profile's `supplemental_rate_bps`
        when set, else the default 2200 basis points, and the `withholding_cents` is the
        milestone's `amount_cents` multiplied by that rate and divided by 10000, rounded
        half-up to whole cents. Under `AGGREGATE`, the system applies a progressive bracket
        over cumulative referral wages: the bracket tax on an amount is fifteen percent of
        the amount while the amount is at least zero and below 500000 cents; 75000 cents
        plus twenty-five percent of the excess over 500000 cents while the amount is at
        least 500000 and below 1500000 cents; and 325000 cents plus thirty-five percent of
        the excess over 1500000 cents once the amount reaches 1500000 cents — each
        bracket's lower bound inclusive. Either way, `net_cents` is `amount_cents` minus
        `withholding_cents`."

        A 45000-cent HIRE milestone under FLAT withholds 9900, net 35100.

        Design: Difficulty/dual_variant_calc/tax_withholding_flat_vs_aggregate
        """
        program = setup_program(req_overrides={"openings": 5})
        emp, ref = _hire_with_verified_profile(
            api, program,
            {"employee_number": "E101", "full_name": "Ann A", "email": "anna@corp.com"},
            {"withholding_method": "FLAT"},
            "ca@x.com",
        )
        ms = get_hire_milestone(ref["id"])
        assert ms["amount_cents"] == 45000

        pp = TEST_USERS["payroll_processor_headers"]
        data = get_success_data(api.approve_milestone(ms["id"], pp))
        assert data["withholding_cents"] == 9900
        assert data["net_cents"] == 35100

    def test_aggregate_variant_withholding_diverges_from_flat(self, api):
        """PRD §3.6: "Under `AGGREGATE`, the system applies a progressive bracket over
        cumulative referral wages: the bracket tax on an amount is fifteen percent of the
        amount while the amount is at least zero and below 500000 cents; 75000 cents plus
        twenty-five percent of the excess over 500000 cents while the amount is at least
        500000 and below 1500000 cents; and 325000 cents plus thirty-five percent of the
        excess over 1500000 cents once the amount reaches 1500000 cents — each bracket's
        lower bound inclusive. The milestone's `withholding_cents` is then the bracket tax
        on the cumulative base plus this milestone's amount, minus the bracket tax on the
        cumulative base alone, rounded half-up to whole cents; the same milestone amount
        can therefore withhold differently depending on year-to-date totals and on
        approval order."

        The identical 45000-cent milestone under AGGREGATE withholds 6750 — divergent from
        the FLAT 9900.

        Design: Difficulty/dual_variant_calc/tax_withholding_flat_vs_aggregate
        """
        program = setup_program(req_overrides={"openings": 5})
        emp, ref = _hire_with_verified_profile(
            api, program,
            {"employee_number": "E102", "full_name": "Bob B", "email": "bob@corp.com"},
            {"withholding_method": "AGGREGATE"},
            "cb@x.com",
        )
        ms = get_hire_milestone(ref["id"])
        assert ms["amount_cents"] == 45000

        pp = TEST_USERS["payroll_processor_headers"]
        data = get_success_data(api.approve_milestone(ms["id"], pp))
        # bracket_tax(45000) - bracket_tax(0) = 6750 - 0
        assert data["withholding_cents"] == 6750
        assert data["net_cents"] == 38250


class TestAggregateBracketStraddle:
    def test_aggregate_withholding_bracket_straddle(self, api):
        """PRD §3.6: "the bracket tax on an amount is fifteen percent of the amount while
        the amount is at least zero and below 500000 cents; 75000 cents plus twenty-five
        percent of the excess over 500000 cents while the amount is at least 500000 and
        below 1500000 cents — each bracket's lower bound inclusive. The milestone's
        `withholding_cents` is then the bracket tax on the cumulative base plus this
        milestone's amount, minus the bracket tax on the cumulative base alone" — and
        "Both variants first establish the cumulative base as the profile's
        `ytd_carryover_cents` plus its `ytd_paid_gross_cents`".

        ytd 490000 + amount 30000 straddles the 500000 bracket: withholding 6500
        (80000 - 73500), net 23500.

        Design: Corner/calculations/aggregate_withholding_bracket_straddle
        """
        program = setup_program(policy_overrides={"tier_ic_cents": 100000})
        emp, ref = _hire_with_verified_profile(
            api, program,
            {"employee_number": "E101", "full_name": "Ann A", "email": "anna@corp.com"},
            {"withholding_method": "AGGREGATE", "ytd_carryover_cents": 490000},
            "c1@x.com",
        )
        ms = get_hire_milestone(ref["id"])
        assert ms["amount_cents"] == 30000

        pp = TEST_USERS["payroll_processor_headers"]
        data = get_success_data(api.approve_milestone(ms["id"], pp))
        assert data["withholding_cents"] == 6500, (
            f"bracket_tax(520000) - bracket_tax(490000) = 80000 - 73500 = 6500, got {data['withholding_cents']}"
        )
        assert data["net_cents"] == 23500


class TestMilestoneApproveOrderChangesAggregateWithholding:
    def test_approve_order_changes_aggregate_withholding(self, api):
        """PRD §3.6: "Both variants first establish the cumulative base as the profile's
        `ytd_carryover_cents` plus its `ytd_paid_gross_cents`, evaluated at the approval
        instant — which means the order in which milestones are approved matters for the
        second variant." and "On success the milestone's withholding is computed and
        *locked* at that instant".
        PRD §3.6: "transitioning every attached `BATCHED` milestone to `PAID`
        (accumulating each referrer's `ytd_paid_gross_cents` by the milestone's
        `amount_cents` for the calendar year)".

        With ytd base 480000, approving the 45000 milestone first withholds 9250; once
        that milestone is paid (ytd_paid_gross grows by 45000), approving the 195000
        milestone withholds 48750.

        Design: Corner/calculations/milestone_approve_order_changes_aggregate_withholding
        """
        program = setup_program()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        setup_verified_tax_profile(
            emp["id"], withholding_method="AGGREGATE", ytd_carryover_cents=480000
        )
        req_dir = create_open_requisition(
            req_number="REQ-DIR-1", title="Director", level="DIRECTOR"
        )
        ref_ic = submit_referral(emp["id"], program["req"]["id"], candidate_email="c1@x.com",
                                 candidate_full_name="C One")
        ref_dir = submit_referral(emp["id"], req_dir["id"], candidate_email="c2@x.com",
                                  candidate_full_name="C Two")
        for r in (ref_ic, ref_dir):
            advance_referral_to_offer(r["id"], program["rec"]["id"], program["hm"]["id"])
            hire_referral(r["id"], program["hm"]["id"])

        ms_ic = get_hire_milestone(ref_ic["id"])
        ms_dir = get_hire_milestone(ref_dir["id"])
        assert ms_ic["amount_cents"] == 45000
        assert ms_dir["amount_cents"] == 195000

        pp = TEST_USERS["payroll_processor_headers"]
        ta = TEST_USERS["talent_admin_headers"]
        d_ic = get_success_data(api.approve_milestone(ms_ic["id"], pp))
        # bracket_tax(525000) - bracket_tax(480000) = 81250 - 72000
        assert d_ic["withholding_cents"] == 9250

        # Pay the first milestone so its gross enters ytd_paid_gross_cents before the
        # second approval evaluates its cumulative base.
        batch = create_open_batch()
        add_milestone_to_batch(batch["id"], ms_ic["id"], batch["version"])
        get_success_data(api.seal_payroll_batch(batch["id"], pp))
        get_success_data(api.export_payroll_batch(batch["id"], pp))
        get_success_data(api.confirm_paid_payroll_batch(batch["id"], ta))

        d_dir = get_success_data(api.approve_milestone(ms_dir["id"], pp))
        # bracket_tax(720000) - bracket_tax(525000) = 130000 - 81250
        assert d_dir["withholding_cents"] == 48750


class TestWithholdingFlatPrecisionRounding:
    def test_withholding_flat_precision_rounding(self, api):
        """PRD §2.6: "Rounding occurs only at explicitly marked rounding points, always
        using the *round half up* method to the nearest whole cent: the campaign uplift
        multiplication at referral submission, the hire/retention milestone split at hire
        time, and the withholding computation at milestone approval."
        PRD §3.6: "Under `FLAT`, the rate is the profile's `supplemental_rate_bps` when
        set, else the default 2200 basis points, and the `withholding_cents` is the
        milestone's `amount_cents` multiplied by that rate and divided by 10000, rounded
        half-up to whole cents."

        Gross 111110 splits HIRE 33333 exactly; FLAT withholding round_half_up(33333 *
        2200/10000) = round(7333.26) = 7333, net 26000.

        Design: Corner/calculations/withholding_flat_precision_rounding
        """
        program = setup_program(policy_overrides={"tier_ic_cents": 111110})
        emp, ref = _hire_with_verified_profile(
            api, program,
            {"employee_number": "E101", "full_name": "Ann A", "email": "anna@corp.com"},
            {"withholding_method": "FLAT"},
            "c1@x.com",
        )
        ms = get_hire_milestone(ref["id"])
        assert ms["amount_cents"] == 33333, (
            f"round_half_up(111110*30/100) = 33333.0 exactly, got {ms['amount_cents']}"
        )

        pp = TEST_USERS["payroll_processor_headers"]
        data = get_success_data(api.approve_milestone(ms["id"], pp))
        assert data["withholding_cents"] == 7333
        assert data["net_cents"] == 26000
