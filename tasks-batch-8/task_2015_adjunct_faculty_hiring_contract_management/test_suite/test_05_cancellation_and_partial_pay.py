"""Section cancellation tiers, partial-pay clause, contract void, and read-your-
write consistency (PRD Sections 2.2, 3.5, 3.6)."""
from test_helpers import (
    ApiErrorId,
    LATE_AT_EARLY_CENSUS_PAYABLE_CENTS,
    LATE_OCT19_PAYABLE_CENTS,
    PRE_CENSUS_PAYABLE_CENTS,
    activate_fall_term,
    create_department,
    create_section,
    create_term,
    get_faculty,
    get_success_data,
    issue_contract_in,
    set_clock,
    setup_active_contract_scenario,
    standard_fall_scenario,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

CHAIR = TEST_USERS["chair_headers"]
ADMIN = TEST_USERS["hr_admin_headers"]


def _active_pch_contract(dept_code):
    """ACTIVE PER_CONTACT_HOUR contract: gross 9,000,000 (200000 * 3.0 h * 15 weeks)."""
    return setup_active_contract_scenario(
        dept_code=dept_code,
        rate_basis="PER_CONTACT_HOUR",
        base_rate_cents=200000,
        longevity_step_cents=5000,
        longevity_step_cap=5,
        weekly_contact_hours=3.0,
    )


class TestProvisionalVsFinal:
    def test_contract_pay_provisional_variant_holds_until_terminal_event(self, api, hr_admin_headers):
        """PRD Section 3.5: "The contract's `payable_cents` starts out equal to
        `gross_pay_cents` and stays there until a terminal event reprices it."
        PRD Section 3.5: "Either way the result is rounded half up to whole cents
        exactly once, at the very end."

        Design: Difficulty/dual_variant_calc/contract_pay_provisional_vs_final_after_late_cancellation
        """
        scn = _active_pch_contract("MATH")
        contract = get_success_data(api.get_contract(scn["contract"]["id"], hr_admin_headers))
        assert contract["contract_status"] == "ACTIVE"
        assert contract["gross_pay_cents"] == 9000000, (
            "provisional gross: 200000 * 3.0 contact hours * 15 whole weeks"
        )
        assert contract["payable_cents"] == 9000000, (
            "provisional payable equals gross before any terminal event"
        )

    def test_contract_pay_final_variant_after_late_cancellation(self, api, hr_admin_headers):
        """PRD Section 3.6: "In the late tier — cancellation date on or after
        `early_census_date`, the boundary day included — the clause pays the larger
        of two independently rounded components. The earned component counts the
        term's total days inclusively from `start_date` through `end_date`, counts
        elapsed days inclusively from `start_date` through the cancellation date,
        and multiplies `gross_pay_cents` by the exact ratio of elapsed to total days
        carried at full precision before rounding the result half up to whole cents.
        The floor component is twenty-five percent of `gross_pay_cents`, rounded
        half up on its own. The payable amount is the maximum of the two, and the
        onboarding stipend is not paid in the late tier."

        Cancellation on 2026-10-19: elapsed 57 of 110 days -> earned 4,663,636 beats
        the 2,250,000 floor.

        Design: Difficulty/dual_variant_calc/contract_pay_provisional_vs_final_after_late_cancellation
        """
        scn = _active_pch_contract("MAT2")
        set_clock("2026-10-19T12:00:00Z")
        get_success_data(api.cancel_section(
            scn["section"]["id"], {"cancellation_reason": "PROGRAM_CUT"}, CHAIR))
        contract = get_success_data(api.get_contract(scn["contract"]["id"], hr_admin_headers))
        assert contract["contract_status"] == "CANCELLED_LATE"
        assert contract["gross_pay_cents"] == 9000000, "provisional gross snapshot is frozen"
        assert contract["payable_cents"] == LATE_OCT19_PAYABLE_CENTS, (
            "final variant: max(rhu(9000000*57/110), rhu(9000000*0.25)) = 4663636"
        )
        assert contract["payable_cents"] != contract["gross_pay_cents"], (
            "the two variants of the same contract data diverge"
        )


class TestNestedRoundingOrder:
    def test_cancel_at_early_census_boundary_is_late_tier(self, api, hr_admin_headers):
        """PRD Section 3.1: "Cancellation strictly before the early census date pays
        the pre-census tier, while cancellation on or after the early census date —
        a boundary that includes the day itself — pays the post-census tier"
        PRD Section 3.6: "attached contracts move to `CANCELLED_PRE_CENSUS` when the
        current logical date falls strictly before `early_census_date`, and to
        `CANCELLED_LATE` when it falls on or after that date."

        Design: Difficulty/combinatorial_formula/cancellation_pay_nested_rounding_order_pinned
        """
        scn = _active_pch_contract("MAT3")
        set_clock("2026-09-14T09:00:00Z")  # exactly the early census day
        get_success_data(api.cancel_section(
            scn["section"]["id"], {"cancellation_reason": "PROGRAM_CUT"}, CHAIR))
        contract = get_success_data(api.get_contract(scn["contract"]["id"], hr_admin_headers))
        assert contract["contract_status"] == "CANCELLED_LATE", (
            "the boundary day itself belongs to the late tier"
        )

    def test_cancel_pay_nested_rounding_order_pinned(self, api, hr_admin_headers):
        """PRD Section 3.6: "The earned component counts the term's total days
        inclusively from `start_date` through `end_date`, counts elapsed days
        inclusively from `start_date` through the cancellation date, and multiplies
        `gross_pay_cents` by the exact ratio of elapsed to total days carried at
        full precision before rounding the result half up to whole cents. The floor
        component is twenty-five percent of `gross_pay_cents`, rounded half up on
        its own. The payable amount is the maximum of the two, and the onboarding
        stipend is not paid in the late tier."

        At the early-census boundary: earned rhu(9000000 * 22/110) = 1,800,000;
        floor rhu(9000000 * 0.25) = 2,250,000; the maximum wins.

        Design: Difficulty/combinatorial_formula/cancellation_pay_nested_rounding_order_pinned
        """
        scn = _active_pch_contract("MAT4")
        set_clock("2026-09-14T09:00:00Z")
        get_success_data(api.cancel_section(
            scn["section"]["id"], {"cancellation_reason": "PROGRAM_CUT"}, CHAIR))
        contract = get_success_data(api.get_contract(scn["contract"]["id"], hr_admin_headers))
        assert contract["payable_cents"] == LATE_AT_EARLY_CENSUS_PAYABLE_CENTS, (
            "max of the two independently rounded components; no stipend in late tier"
        )


class TestPreCensusTier:
    def test_pre_census_cancel_pay_includes_stipend_and_ignores_elapsed(self, api, hr_admin_headers):
        """PRD Section 3.6: "In the pre-census tier — cancellation date strictly
        before `early_census_date` — the payable amount is ten percent of
        `gross_pay_cents`, and that base component is rounded half up to whole cents
        first; only then is the fixed onboarding stipend of 5,000 cents added, the
        stipend being already a whole-cent figure that is never rounded. Elapsed
        time is irrelevant in this tier."

        Cancellation on 2026-09-01 (< early census 2026-09-14):
        rhu(9000000 * 0.10) + 5000 = 905,000.

        Design: Corner/calculations/pre_census_cancel_pay_includes_stipend_and_ignores_elapsed
        """
        scn = _active_pch_contract("PREX")
        set_clock("2026-09-01T00:00:00Z")
        get_success_data(api.cancel_section(
            scn["section"]["id"], {"cancellation_reason": "ADMINISTRATIVE"}, CHAIR))
        contract = get_success_data(api.get_contract(scn["contract"]["id"], hr_admin_headers))
        assert contract["contract_status"] == "CANCELLED_PRE_CENSUS"
        assert contract["payable_cents"] == PRE_CENSUS_PAYABLE_CENTS


class TestLowEnrollmentPolicy:
    def _section(self, dept_code, enrollment, min_enrollment):
        dept = create_department(code=dept_code, contact_hour_value=1.00)
        create_term(code="2026FA")
        section = create_section(
            dept["id"], term_code="2026FA", course_code="PSY-101",
            weekly_contact_hours=3.0, enrollment=enrollment, min_enrollment=min_enrollment,
        )
        set_clock("2026-08-20T00:00:00Z")  # strictly before early census 2026-09-14
        return section

    def test_low_enrollment_cancel_at_exact_min_enrollment_rejected(self, api):
        """PRD Section 3.6: "a cancellation citing `LOW_ENROLLMENT` requires the
        section's `enrollment` to be strictly below `min_enrollment` and the current
        logical date to be strictly before the term's `early_census_date` — both
        strict — or the cancel is refused with `ERR_CANCELLATION_POLICY`."

        enrollment 5 == min_enrollment 5 is NOT strictly below.

        Design: Difficulty/boundary_precision_check/low_enrollment_cancel_at_exact_min_enrollment_rejected
        """
        section = self._section("PSYC", enrollment=5, min_enrollment=5)
        resp = api.cancel_section(
            section["id"], {"cancellation_reason": "LOW_ENROLLMENT"}, CHAIR)
        validate_error(resp, ApiErrorId.ERR_CANCELLATION_POLICY)
        after = get_success_data(api.get_section(section["id"], CHAIR))
        assert after["section_status"] == "SCHEDULED", "failed cancel leaves the section unchanged"

    def test_low_enrollment_cancel_one_below_min_enrollment_allowed(self, api):
        """PRD Section 3.6: "a cancellation citing `LOW_ENROLLMENT` requires the
        section's `enrollment` to be strictly below `min_enrollment` and the current
        logical date to be strictly before the term's `early_census_date` — both
        strict"

        enrollment 4 < min_enrollment 5 with the date condition met cancels.

        Design: Difficulty/boundary_precision_check/low_enrollment_cancel_at_exact_min_enrollment_rejected
        """
        section = self._section("PSY2", enrollment=4, min_enrollment=5)
        resp = api.cancel_section(
            section["id"], {"cancellation_reason": "LOW_ENROLLMENT"}, CHAIR)
        cancelled = validate_success(resp, 200)
        assert cancelled["section_status"] == "CANCELLED"


class TestImmediateConsistency:
    def test_immediate_consistency_after_section_cancel(self, api, hr_admin_headers):
        """PRD Section 2.2: "Unless otherwise noted, operations that create or
        modify a resource will return the created or updated resource object in the
        data field."
        PRD Section 3.6: "Both paths recompute every affected faculty member's load
        aggregates, bump the section's `version`, and reprice each cancelled
        contract"

        The cancel response and the immediately following reads all reflect the
        full cascade.

        Design: Corner/consistency_model/immediate_consistency_after_section_cancel
        """
        scn = _active_pch_contract("CONS")
        set_clock("2026-10-19T12:00:00Z")
        cancel_resp = validate_success(api.cancel_section(
            scn["section"]["id"], {"cancellation_reason": "PROGRAM_CUT"}, CHAIR), 200)
        assert cancel_resp["section_status"] == "CANCELLED", (
            "the cancel response itself carries the new section state"
        )

        contract = get_success_data(api.get_contract(scn["contract"]["id"], hr_admin_headers))
        assert contract["contract_status"] == "CANCELLED_LATE"
        assert contract["payable_cents"] == LATE_OCT19_PAYABLE_CENTS

        faculty = get_faculty(scn["faculty"]["id"])
        assert faculty["current_term_load_units"] == 0.00, (
            "load aggregate recomputed with no reconciliation lag"
        )


class TestContractVoid:
    def test_contract_void_only_from_issued(self, api, hr_admin_headers):
        """PRD Section 3.6: "An `HRAdmin` may void a contract that is still `ISSUED`
        — never activated"
        PRD Section 2.8: "`ERR_INVALID_STATE` (409) — the requested action exists as
        a transition from the target entity's current state. This single state error
        covers terminal-state lockdown and repeated-action (double-action) failures"

        Design: Corner/state_machines/contract_void_only_from_issued
        """
        scn = standard_fall_scenario(dept_code="VOID", load_cap_units=9.00)
        contract = issue_contract_in(scn)
        activate_fall_term()  # contract flips ISSUED -> ACTIVE

        refused = api.void_contract(contract["id"], hr_admin_headers)
        validate_error(refused, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_contract(contract["id"], hr_admin_headers))
        assert after["contract_status"] == "ACTIVE"
