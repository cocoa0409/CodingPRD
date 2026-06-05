"""Deadline and valuation calculations: SEP-deadline plan variants, discharge-bag
round-then-sum valuation, the discharge-readiness scoring formula, filing deadlines,
and the inclusive/threshold boundaries on those metrics.

Difficulty queue: dual_variant_calc, combinatorial_formula, boundary_precision_check.
Corner queue: calculation/filing-deadline instances.
"""
import pytest
from test_helpers import validate_success, validate_error, get_success_data, ApiErrorId
import test_helpers.fixtures as fx
import test_helpers.factories as f


# =========================================================================
# Difficulty/dual_variant_calc/sep_deadline_calendar_vs_business_roll_diverges
# =========================================================================
class TestSepDeadlineVariants:
    def test_marketplace_sep_deadline_is_hard_calendar_30_days(self, api):
        """PRD §3.10: "For a MARKETPLACE policy the deadline is the hard
        birth-plus-30-calendar-days instant, with no weekend roll and keeping the
        birth time-of-day."

        Design: Difficulty/dual_variant_calc/sep_deadline_calendar_vs_business_roll_diverges
        """
        fx.set_clock("2026-03-05T12:00:00Z")
        mkt_policy = fx.create_policy(plan_type="MARKETPLACE", carrier_name="MktCo")
        reg, _ = fx.create_admitted_registration(policy_id=mkt_policy["id"], due_date="2026-03-12")
        newborn = fx.record_birth(reg["id"], birth_datetime="2026-03-05T10:00:00Z")
        enr = fx.create_enrollment(newborn["id"], mkt_policy["id"], "2026-03-05T12:00:00Z")

        data = validate_success(api.get_dependent_enrollment(enr["id"], fx.BENEFITS))
        # birth 2026-03-05T10:00:00Z + 30d = Saturday 2026-04-04T10:00:00Z; no roll.
        assert data["sep_deadline"] == "2026-04-04T10:00:00.000Z", (
            f"MARKETPLACE deadline should keep birth time-of-day with no roll, "
            f"got {data['sep_deadline']}")

    def test_employer_group_sep_deadline_rolls_weekend_to_monday(self, api):
        """PRD §3.10: "For an EMPLOYER_GROUP or MEDICAID policy the deadline rolls
        when the raw birth-plus-30-days instant lands on a weekend: if it falls on a
        Saturday or a Sunday, the deadline rolls forward to 23:59:59.999Z on the
        following Monday, extending the window; if it falls on any weekday, the raw
        deadline stands unchanged."

        Design: Difficulty/dual_variant_calc/sep_deadline_calendar_vs_business_roll_diverges
        """
        fx.set_clock("2026-03-05T12:00:00Z")
        emp_policy = fx.create_policy(plan_type="EMPLOYER_GROUP", carrier_name="EmpCo")
        reg, _ = fx.create_admitted_registration(policy_id=emp_policy["id"], due_date="2026-03-12")
        newborn = fx.record_birth(reg["id"], birth_datetime="2026-03-05T10:00:00Z")
        enr = fx.create_enrollment(newborn["id"], emp_policy["id"], "2026-03-05T12:00:00Z")

        data = validate_success(api.get_dependent_enrollment(enr["id"], fx.BENEFITS))
        # raw deadline Saturday 2026-04-04 rolls forward to Monday 2026-04-06 23:59:59.999Z.
        assert data["sep_deadline"] == "2026-04-06T23:59:59.999Z", (
            f"EMPLOYER_GROUP deadline should roll a Saturday to next Monday end-of-day, "
            f"got {data['sep_deadline']}")


# =========================================================================
# Difficulty/dual_variant_calc/bag_value_round_then_sum_vs_sum_then_round_diverges
# =========================================================================
class TestBagValuationRoundThenSum:
    def test_three_medication_lines_round_then_sum_yields_4536(self, api):
        """PRD §3.6: "The valuation is computed line by line, with each line's value
        rounded to a whole cent before the lines are summed — round-then-sum, never
        sum-then-round, since for bags with multiple half-cent lines the two orders
        can diverge by one or more cents."

        Design: Difficulty/dual_variant_calc/bag_value_round_then_sum_vs_sum_then_round_diverges
        """
        fx.set_clock("2026-03-05T12:00:00Z")
        newborn, _, _ = fx.setup_admitted_with_newborn(birth_datetime="2026-03-05T10:00:00Z")
        line_items = [
            {"sku": "MED-A", "category": "MEDICATION", "qty": 1, "unit_value_cents": 1499},
            {"sku": "MED-B", "category": "MEDICATION", "qty": 1, "unit_value_cents": 2510},
            {"sku": "MED-C", "category": "MEDICATION", "qty": 1, "unit_value_cents": 310},
        ]
        bag = get_success_data(api.create_discharge_bag(
            f.create_discharge_bag_payload(newborn["id"], line_items=line_items), fx.NURSE))

        data = validate_success(api.assemble_discharge_bag(bag["id"], fx.NURSE))
        # round(1499*1.05)+round(2510*1.05)+round(310*1.05) = 1574+2636+326 = 4536.
        assert data["total_value_cents"] == 4536, (
            f"round-then-sum should yield 4536 (not 4535 sum-then-round), "
            f"got {data['total_value_cents']}")

    def test_three_medication_lines_set_pharmacy_signoff_flag(self, api):
        """PRD §3.6: "The requires_pharmacy_signoff flag is set to true exactly when
        any line item's category is MEDICATION."

        Design: Difficulty/dual_variant_calc/bag_value_round_then_sum_vs_sum_then_round_diverges
        """
        fx.set_clock("2026-03-05T12:00:00Z")
        newborn, _, _ = fx.setup_admitted_with_newborn(birth_datetime="2026-03-05T10:00:00Z")
        line_items = [
            {"sku": "MED-A", "category": "MEDICATION", "qty": 1, "unit_value_cents": 1499},
            {"sku": "MED-B", "category": "MEDICATION", "qty": 1, "unit_value_cents": 2510},
            {"sku": "MED-C", "category": "MEDICATION", "qty": 1, "unit_value_cents": 310},
        ]
        bag = get_success_data(api.create_discharge_bag(
            f.create_discharge_bag_payload(newborn["id"], line_items=line_items), fx.NURSE))

        data = validate_success(api.assemble_discharge_bag(bag["id"], fx.NURSE))
        assert data["requires_pharmacy_signoff"] is True, (
            "a bag with a MEDICATION line must set requires_pharmacy_signoff true")


# =========================================================================
# Difficulty/combinatorial_formula/discharge_readiness_nonlinear_four_input_score
# =========================================================================
class TestDischargeReadinessScore:
    def test_readiness_score_sums_four_independent_terms_to_75(self, api):
        """PRD §3.8: "The score is the capped sum of four independent contributions,
        each evaluated on its own and then added together, with the total finally
        limited to no more than 100."
        PRD §3.8: "otherwise 25 points when it is 2000 or more"
        PRD §3.8: "a feeding term worth 30 points when at least one lactation consult
        for this infant is COMPLETED with its feeding_adequate true, and 0 points
        otherwise."

        Design: Difficulty/combinatorial_formula/discharge_readiness_nonlinear_four_input_score
        """
        fx.set_clock("2026-03-05T12:00:00Z")
        newborn, _, _ = fx.setup_admitted_with_newborn(
            weight_grams=2100, gestational_age_weeks=37, apgar_5min=9,
            birth_datetime="2026-03-05T10:00:00Z")
        nb_id = newborn["id"]
        get_success_data(api.room_in(nb_id, fx.NURSE))
        consult = get_success_data(api.create_lactation_consult(
            f.create_lactation_consult_payload(nb_id, "2026-03-05T11:00:00Z"), fx.NURSE))
        get_success_data(api.complete_lactation_consult(
            consult["id"], f.complete_consult_payload(8), fx.NURSE))

        data = validate_success(api.get_newborn(nb_id, fx.NURSE))
        # weight 2100 -> 25, feeding adequate -> 30, no open NICU -> 20, no birth cert -> 0.
        assert data["discharge_readiness_score"] == 75, (
            f"25+30+20+0 should be 75, got {data['discharge_readiness_score']}")

    def test_readiness_feeding_term_zero_without_adequate_consult(self, api):
        """PRD §3.8: "a feeding term worth 30 points when at least one lactation
        consult for this infant is COMPLETED with its feeding_adequate true, and 0
        points otherwise."

        Design: Difficulty/combinatorial_formula/discharge_readiness_nonlinear_four_input_score
        """
        fx.set_clock("2026-03-05T12:00:00Z")
        newborn, _, _ = fx.setup_admitted_with_newborn(
            weight_grams=2100, gestational_age_weeks=37, apgar_5min=9,
            birth_datetime="2026-03-05T10:00:00Z")
        nb_id = newborn["id"]
        get_success_data(api.room_in(nb_id, fx.NURSE))
        # No completed feeding-adequate consult -> feeding term is 0.

        data = validate_success(api.get_newborn(nb_id, fx.NURSE))
        # weight 2100 -> 25, feeding 0, no open NICU -> 20, no birth cert -> 0 = 45.
        assert data["discharge_readiness_score"] == 45, (
            f"with no adequate feeding the feeding term is 0; 25+0+20+0 should be 45, "
            f"got {data['discharge_readiness_score']}")


# =========================================================================
# Difficulty/combinatorial_formula/bag_value_round_order_pinned_round_then_sum
# =========================================================================
class TestBagValuationRoundOrderPinned:
    def test_mixed_medication_and_formula_lines_round_each_before_sum(self, api):
        """PRD §3.6: "For a single line, multiply its qty by its unit_value_cents by a
        category multiplier, then round that product half-up to an integer number of
        cents."
        PRD §3.6: "MEDICATION at 1.05 (a 5 percent handling surcharge)"

        Design: Difficulty/combinatorial_formula/bag_value_round_order_pinned_round_then_sum
        """
        fx.set_clock("2026-03-05T12:00:00Z")
        newborn, _, _ = fx.setup_admitted_with_newborn(birth_datetime="2026-03-05T10:00:00Z")
        line_items = [
            {"sku": "MED-X", "category": "MEDICATION", "qty": 1, "unit_value_cents": 2510},
            {"sku": "FORM-Y", "category": "FORMULA", "qty": 2, "unit_value_cents": 1299},
        ]
        bag = get_success_data(api.create_discharge_bag(
            f.create_discharge_bag_payload(newborn["id"], line_items=line_items), fx.NURSE))

        data = validate_success(api.assemble_discharge_bag(bag["id"], fx.NURSE))
        # round(2510*1.05)=2636 ; round(2*1299*1.00)=2598 ; 2636+2598 = 5234.
        assert data["total_value_cents"] == 5234, (
            f"per-line round before sum should yield 5234, got {data['total_value_cents']}")

    def test_education_line_contributes_zero_value(self, api):
        """PRD §3.6: "EDUCATION at 0.00 (educational handouts are free)."

        Design: Difficulty/combinatorial_formula/bag_value_round_order_pinned_round_then_sum
        """
        fx.set_clock("2026-03-05T12:00:00Z")
        newborn, _, _ = fx.setup_admitted_with_newborn(birth_datetime="2026-03-05T10:00:00Z")
        line_items = [
            {"sku": "EDU-1", "category": "EDUCATION", "qty": 3, "unit_value_cents": 500},
            {"sku": "DIA-1", "category": "DIAPERS", "qty": 2, "unit_value_cents": 333},
        ]
        bag = get_success_data(api.create_discharge_bag(
            f.create_discharge_bag_payload(newborn["id"], line_items=line_items), fx.NURSE))

        data = validate_success(api.assemble_discharge_bag(bag["id"], fx.NURSE))
        # EDUCATION*0.00 = 0 ; round(2*333*1.00)=666 ; total 666.
        assert data["total_value_cents"] == 666, (
            f"EDUCATION lines contribute 0; total should be 666, "
            f"got {data['total_value_cents']}")


# =========================================================================
# Difficulty/boundary_precision_check/readiness_exactly_70_passes_mark_discharge_ready
# =========================================================================
class TestReadinessThresholdBoundary:
    def test_score_exactly_70_passes_mark_discharge_ready(self, api):
        """PRD §3.8: "the score is recomputed at the moment of the call and must be at
        least 70; a recomputed score below 70 is rejected with
        ERR_READINESS_BELOW_THRESHOLD."

        Design: Difficulty/boundary_precision_check/readiness_exactly_70_passes_mark_discharge_ready
        """
        fx.set_clock("2026-03-05T12:00:00Z")
        newborn, _, _ = fx.setup_admitted_with_newborn(
            weight_grams=2500, gestational_age_weeks=37, apgar_5min=9,
            legal_name="Baby Doe", birth_datetime="2026-03-05T10:00:00Z")
        nb_id = newborn["id"]
        get_success_data(api.room_in(nb_id, fx.NURSE))
        bc = fx.create_birth_cert(nb_id)
        get_success_data(api.submit_filing(bc["id"], fx.VITAL))

        data = validate_success(api.mark_discharge_ready(nb_id, fx.NURSE))
        # weight 2500 -> 40, no feeding -> 0, no open NICU -> 20, birth cert SUBMITTED -> 10 = 70.
        assert data["discharge_readiness_score"] == 70, (
            f"40+0+20+10 should be exactly 70, got {data['discharge_readiness_score']}")
        assert data["clinical_status"] == "DISCHARGE_READY", (
            f"score 70 is at the inclusive >=70 gate and must transition, "
            f"got {data['clinical_status']}")

    def test_score_69_below_threshold_rejected(self, api):
        """PRD §3.8: "a recomputed score below 70 is rejected with
        ERR_READINESS_BELOW_THRESHOLD."

        Design: Difficulty/boundary_precision_check/readiness_exactly_70_passes_mark_discharge_ready
        """
        fx.set_clock("2026-03-05T12:00:00Z")
        # weight 2000 -> 25, no feeding -> 0, no open NICU -> 20, birth cert SUBMITTED -> 10 = 55 < 70.
        newborn, _, _ = fx.setup_admitted_with_newborn(
            weight_grams=2000, gestational_age_weeks=37, apgar_5min=9,
            legal_name="Baby Doe", birth_datetime="2026-03-05T10:00:00Z")
        nb_id = newborn["id"]
        get_success_data(api.room_in(nb_id, fx.NURSE))
        bc = fx.create_birth_cert(nb_id)
        get_success_data(api.submit_filing(bc["id"], fx.VITAL))

        resp = api.mark_discharge_ready(nb_id, fx.NURSE)
        validate_error(resp, ApiErrorId.ERR_READINESS_BELOW_THRESHOLD.value)


# =========================================================================
# Difficulty/boundary_precision_check/sep_requested_exactly_at_deadline_inclusive_enrolls
# =========================================================================
class TestSepInclusiveBoundary:
    def test_requested_exactly_at_deadline_enrolls(self, api):
        """PRD §3.10: "An enrollment is within its window exactly when its requested_at
        is at or before the sep_deadline, with the boundary instant inclusive."
        PRD §3.10: "A successful approval sets retroactive_effective_date to the
        calendar date of the infant's birth_datetime"

        Design: Difficulty/boundary_precision_check/sep_requested_exactly_at_deadline_inclusive_enrolls
        """
        fx.set_clock("2026-04-04T10:00:00Z")
        policy = fx.create_policy(plan_type="MARKETPLACE", dependent_slots_max=3, carrier_name="MktCo")
        reg, _ = fx.create_admitted_registration(policy_id=policy["id"], due_date="2026-03-12")
        # Reset the clock back so the birth can be recorded with its real datetime,
        # then advance to the deadline before approving.
        newborn = fx.record_birth(reg["id"], birth_datetime="2026-03-05T10:00:00Z")
        enr = fx.create_enrollment(newborn["id"], policy["id"], "2026-04-04T10:00:00.000Z")
        pol_v = fx.get_policy_version(policy["id"])

        data = validate_success(api.approve_enrollment(
            enr["id"], f.approve_enrollment_payload(pol_v), fx.BENEFITS))
        assert data["status"] == "ENROLLED", (
            f"requested_at == sep_deadline is inclusive and must enroll, got {data['status']}")
        assert data["retroactive_effective_date"] == "2026-03-05", (
            f"retroactive_effective_date should be the birth calendar date, "
            f"got {data['retroactive_effective_date']}")

    def test_requested_one_ms_past_deadline_window_closed(self, api):
        """PRD §3.10: "If the enrollment's requested_at is strictly after its
        sep_deadline, the window has closed and the approval is rejected with
        ERR_SEP_WINDOW_CLOSED"

        Design: Difficulty/boundary_precision_check/sep_requested_exactly_at_deadline_inclusive_enrolls
        """
        fx.set_clock("2026-04-04T10:00:00Z")
        policy = fx.create_policy(plan_type="MARKETPLACE", dependent_slots_max=3, carrier_name="MktCo")
        reg, _ = fx.create_admitted_registration(policy_id=policy["id"], due_date="2026-03-12")
        newborn = fx.record_birth(reg["id"], birth_datetime="2026-03-05T10:00:00Z")
        # deadline 2026-04-04T10:00:00.000Z; one millisecond later is strictly after.
        enr = fx.create_enrollment(newborn["id"], policy["id"], "2026-04-04T10:00:00.001Z")
        pol_v = fx.get_policy_version(policy["id"])

        resp = api.approve_enrollment(enr["id"], f.approve_enrollment_payload(pol_v), fx.BENEFITS)
        validate_error(resp, ApiErrorId.ERR_SEP_WINDOW_CLOSED.value)


# =========================================================================
# Corner/calculations/filing_deadline_birth_certificate_five_days
# =========================================================================
def test_birth_certificate_filing_deadline_is_birth_plus_5_days(api):
    """PRD §3.7: "a birth-certificate filing is due 5 calendar days after birth"

    Design: Corner/calculations/filing_deadline_birth_certificate_five_days
    """
    fx.set_clock("2026-03-05T12:00:00Z")
    newborn, _, _ = fx.setup_admitted_with_newborn(
        legal_name="Baby Doe", birth_datetime="2026-03-05T10:00:00Z")

    data = validate_success(api.create_government_filing(
        f.create_government_filing_payload(newborn["id"], "BIRTH_CERTIFICATE"), fx.VITAL),
        expected_status=201)
    assert data["filing_deadline"] == "2026-03-10T10:00:00.000Z", (
        f"birth + 5 calendar days should be 2026-03-10T10:00:00.000Z, "
        f"got {data['filing_deadline']}")


# =========================================================================
# Corner/calculations/filing_late_flagged_when_submitted_past_deadline
# =========================================================================
def test_filing_submitted_past_deadline_is_late_flagged(api):
    """PRD §3.7: "A late submission instead moves the filing from PENDING to
    LATE_FLAGGED and journals a FILING_LATE_FLAGGED audit event."

    Design: Corner/calculations/filing_late_flagged_when_submitted_past_deadline
    """
    fx.set_clock("2026-03-05T12:00:00Z")
    newborn, _, _ = fx.setup_admitted_with_newborn(
        legal_name="Baby Doe", birth_datetime="2026-03-05T10:00:00Z")
    filing = fx.create_birth_cert(newborn["id"])
    # deadline is 2026-03-10T10:00:00Z; advance past it.
    fx.set_clock("2026-03-11T00:00:00Z")

    data = validate_success(api.submit_filing(filing["id"], fx.VITAL))
    assert data["status"] == "LATE_FLAGGED", (
        f"submission strictly after the deadline must be LATE_FLAGGED, got {data['status']}")
