"""Credit tallies, requirement satisfaction, carryover surplus, audit-risk
scores, deadline reminders, and cycle-end computation.
"""
import pytest

from test_helpers import (
    validate_success,
    get_success_data,
    factories as F,
    fixtures as FX,
    make_licensee_headers,
)

ADMIN = FX.ADMIN
ADMIN_INITIATOR = FX.ADMIN_INITIATOR


# ===========================================================================
# Difficulty/dual_variant_calc  (>=2 tests per instance)
# ===========================================================================
def test_credit_tally_provisional_vs_final_diverge(api):
    """PRD §3.5: "The provisional figure, `provisional_earned_hours`, is that
    base plus the sum of `awarded_hours` over every completion on the cycle whose
    status is `PENDING_VERIFICATION` or `VERIFIED`. The final figure,
    `final_earned_hours`, is that same base plus the sum of `awarded_hours` over
    only the completions whose status is `VERIFIED`."

    Design: Difficulty/dual_variant_calc/credit_tally_provisional_vs_final_on_renewal_cycle
    """
    base = FX.setup_board_provider_licensee_cycle()  # total 30, ETHICS 4, SUBSTANCE 2
    provider, licensee, cycle = base["provider"], base["licensee"], base["cycle"]
    course_g = FX.create_course(provider["id"], "GENERAL", 30.0)
    course_e = FX.create_course(provider["id"], "ETHICS", 6.0)

    # One GENERAL completion VERIFIED (30.0); one ETHICS completion left PENDING (6.0).
    FX.log_and_verify(licensee["id"], course_g["id"], cycle["id"])
    FX.log_completion(licensee["id"], course_e["id"], cycle["id"])

    data = get_success_data(api.get_renewal_cycle(cycle["id"], ADMIN))
    assert float(data["provisional_earned_hours"]) == pytest.approx(36.0, abs=0.01)
    assert float(data["final_earned_hours"]) == pytest.approx(30.0, abs=0.01)
    assert data["status"] == "OPEN"


def test_credit_tally_provisional_superset_of_final_after_verify(api):
    """PRD §3.5: "Because the provisional set is a superset of the final set,
    `provisional_earned_hours` is always at least `final_earned_hours`."

    Design: Difficulty/dual_variant_calc/credit_tally_provisional_vs_final_on_renewal_cycle
    """
    base = FX.setup_board_provider_licensee_cycle()
    provider, licensee, cycle = base["provider"], base["licensee"], base["cycle"]
    course_g = FX.create_course(provider["id"], "GENERAL", 30.0)
    course_e = FX.create_course(provider["id"], "ETHICS", 6.0)
    FX.log_and_verify(licensee["id"], course_g["id"], cycle["id"])
    FX.log_completion(licensee["id"], course_e["id"], cycle["id"])

    # Now verify the ETHICS completion too — provisional and final converge.
    comps = get_success_data(api.list_cycle_completions(cycle["id"], ADMIN))
    # final must rise to 36.0 once both are VERIFIED.
    pending = [c for c in comps if c["status"] == "PENDING_VERIFICATION"]
    FX.verify_completion(pending[0]["id"])

    data = get_success_data(api.get_renewal_cycle(cycle["id"], ADMIN))
    assert float(data["final_earned_hours"]) == pytest.approx(36.0, abs=0.01)
    assert float(data["provisional_earned_hours"]) == pytest.approx(36.0, abs=0.01)


def test_audit_risk_intake_counts_rejection(api):
    """PRD §3.9: "The intake variant, recomputed when a completion is rejected,
    is an early pessimistic estimate: it counts late completions whose status is
    `PENDING_VERIFICATION`, `VERIFIED`, or `REJECTED`, and counts all `REJECTED`
    completions."
    PRD §3.9: "each rejected completion contributes 5 points."

    Design: Difficulty/dual_variant_calc/audit_risk_score_intake_vs_review_final_on_licensee
    """
    base = FX.setup_board_provider_licensee_cycle()
    provider, licensee, cycle = base["provider"], base["licensee"], base["cycle"]
    course_e = FX.create_course(provider["id"], "ETHICS", 4.0)
    comp = FX.log_completion(licensee["id"], course_e["id"], cycle["id"])
    get_success_data(api.reject_completion(comp["id"], ADMIN, {"reason": "missing certificate"}))

    lic = get_success_data(api.get_licensee(licensee["id"], ADMIN))
    assert int(lic["audit_risk_score"]) == 5, "one REJECTED -> W_REJECT*1 == 5 (intake)"


def test_audit_risk_review_final_excludes_resubmitted_verified(api):
    """PRD §3.9: "The review-final variant, recomputed when an attestation is
    submitted, is the settled figure: it counts late completions only among
    `VERIFIED` completions and excludes rejections that were later resubmitted
    and verified."

    Design: Difficulty/dual_variant_calc/audit_risk_score_intake_vs_review_final_on_licensee
    """
    base = FX.setup_board_provider_licensee_cycle()
    provider, licensee, cycle = base["provider"], base["licensee"], base["cycle"]
    course_e = FX.create_course(provider["id"], "ETHICS", 4.0)
    course_s = FX.create_course(provider["id"], "SUBSTANCE", 2.0)
    course_g = FX.create_course(provider["id"], "GENERAL", 24.0)
    lic = make_licensee_headers(licensee["id"])

    # ETHICS rejected, then resubmitted and verified.
    comp_e = FX.log_completion(licensee["id"], course_e["id"], cycle["id"])
    get_success_data(api.reject_completion(comp_e["id"], ADMIN, {"reason": "x"}))
    get_success_data(api.resubmit_completion(comp_e["id"], lic))
    FX.verify_completion(comp_e["id"])
    # SUBSTANCE and GENERAL verified -> requirement met (final 30.0).
    FX.log_and_verify(licensee["id"], course_s["id"], cycle["id"])
    FX.log_and_verify(licensee["id"], course_g["id"], cycle["id"])

    audit = FX.initiate_audit(cycle["id"], ADMIN_INITIATOR)
    get_success_data(api.request_attestation(audit["id"], ADMIN_INITIATOR))
    get_success_data(api.submit_attestation(
        audit["id"], F.submit_attestation_payload(30.0), lic))

    licensee_data = get_success_data(api.get_licensee(licensee["id"], ADMIN))
    assert int(licensee_data["audit_risk_score"]) == 0, (
        "review_final excludes the resubmitted-and-verified rejection; no late completions")


# ===========================================================================
# Difficulty/combinatorial_formula  (>=2 tests per instance)
# ===========================================================================
def test_requirement_unmet_when_substance_category_short(api):
    """PRD §3.6: "The requirement is met exactly when every non-`GENERAL`
    category's deficit is 0 and the general deficit is also 0."
    PRD §3.6: "For each non-`GENERAL` category that has a requirement with minimum
    *m*, the system allocates against that minimum the lesser of the category's
    hours and *m*; any hours beyond *m* are that category's overflow and spill
    into a shared general pool, while a shortfall below *m* is that category's
    deficit."

    Design: Difficulty/combinatorial_formula/requirement_satisfaction_waterfall_mode_a_nonlinear
    """
    base = FX.setup_board_provider_licensee_cycle()  # total 30, ETHICS 4, SUBSTANCE 2
    provider, licensee, cycle = base["provider"], base["licensee"], base["cycle"]
    # VERIFIED: ETHICS 5.0, SUBSTANCE 1.0, GENERAL 25.0 -> total 31.0, SUBSTANCE short by 1.0.
    FX.log_and_verify(licensee["id"],
                      FX.create_course(provider["id"], "ETHICS", 5.0)["id"], cycle["id"])
    FX.log_and_verify(licensee["id"],
                      FX.create_course(provider["id"], "SUBSTANCE", 1.0)["id"], cycle["id"])
    FX.log_and_verify(licensee["id"],
                      FX.create_course(provider["id"], "GENERAL", 25.0)["id"], cycle["id"])

    data = get_success_data(api.get_renewal_cycle(cycle["id"], ADMIN))
    assert float(data["final_earned_hours"]) == pytest.approx(31.0, abs=0.01)
    assert data["status"] == "OPEN", (
        "SUBSTANCE deficit 1.0 keeps it unmet despite total 31.0 >= 30.0")


def test_carryover_rounds_per_category_then_sums(api):
    """PRD §3.6: "Round each of the three category surpluses half-up to one
    decimal place *first*, then sum the three rounded surpluses to get the raw
    carryover, then cap that raw carryover at the board's `carryover_cap_hours`.
    The pinned order matters at fractional boundaries — three surpluses of 1.04,
    5.04, and 0.04 round per category to 1.0, 5.0, and 0.0 for a total of 6.0,
    which is not the same as rounding their 6.12 sum to 6.1."

    Design: Difficulty/combinatorial_formula/carryover_round_per_category_then_sum_mode_b
    """
    base = FX.setup_board_provider_licensee_cycle(
        board_overrides={"carryover_cap_hours": 10.0})
    provider, licensee, cycle = base["provider"], base["licensee"], base["cycle"]
    # ETHICS 5.04 (req 4.0 -> surplus 1.04), SUBSTANCE 2.04 (req 2.0 -> 0.04),
    # GENERAL 29.04 (general_required 24.0 -> 5.04).
    FX.log_and_verify(licensee["id"],
                      FX.create_course(provider["id"], "ETHICS", 5.04)["id"], cycle["id"])
    FX.log_and_verify(licensee["id"],
                      FX.create_course(provider["id"], "SUBSTANCE", 2.04)["id"], cycle["id"])
    FX.log_and_verify(licensee["id"],
                      FX.create_course(provider["id"], "GENERAL", 29.04)["id"], cycle["id"])

    data = get_success_data(api.get_renewal_cycle(cycle["id"], ADMIN))
    assert data["status"] == "REQUIREMENTS_MET"
    assert float(data["carryover_out_hours"]) == pytest.approx(6.0, abs=0.01), (
        "per-category round 1.0+5.0+0.0; sum-then-round would be 6.1")


def test_carryover_saturates_at_board_cap(api):
    """PRD §3.6: "then cap that raw carryover at the board's
    `carryover_cap_hours`."
    PRD §3.6: "When the raw carryover exceeds the board cap, `carryover_out_hours`
    saturates at `carryover_cap_hours` and the surplus above the cap is forfeited."

    Design: Difficulty/combinatorial_formula/carryover_round_per_category_then_sum_mode_b
    """
    base = FX.setup_board_provider_licensee_cycle(
        board_overrides={"carryover_cap_hours": 5.0})  # cap below the raw surplus
    provider, licensee, cycle = base["provider"], base["licensee"], base["cycle"]
    # ETHICS 4.0 (surplus 0), SUBSTANCE 2.0 (surplus 0), GENERAL 34.0
    # (general_required 24.0 -> surplus 10.0). Raw carryover 10.0 > cap 5.0.
    FX.log_and_verify(licensee["id"],
                      FX.create_course(provider["id"], "ETHICS", 4.0)["id"], cycle["id"])
    FX.log_and_verify(licensee["id"],
                      FX.create_course(provider["id"], "SUBSTANCE", 2.0)["id"], cycle["id"])
    FX.log_and_verify(licensee["id"],
                      FX.create_course(provider["id"], "GENERAL", 34.0)["id"], cycle["id"])

    data = get_success_data(api.get_renewal_cycle(cycle["id"], ADMIN))
    assert data["status"] == "REQUIREMENTS_MET"
    assert float(data["carryover_out_hours"]) == pytest.approx(5.0, abs=0.01), (
        "raw carryover 10.0 saturates at the 5.0 board cap")


def test_requirement_met_when_all_categories_satisfied(api):
    """PRD §3.6: "The requirement is met exactly when every non-`GENERAL`
    category's deficit is 0 and the general deficit is also 0."

    Design: Difficulty/combinatorial_formula/requirement_satisfaction_waterfall_mode_a_nonlinear
    """
    met = FX.setup_requirements_met_cycle(
        ethics_hours=5.0, substance_hours=3.0, general_hours=24.0)
    data = met["cycle"]
    # ETHICS 5>=4, SUBSTANCE 3>=2, overflow 1+1=2 spills into general pool
    # (24 general + 2 overflow >= general_required 24) -> MET.
    assert data["status"] == "REQUIREMENTS_MET"


# ===========================================================================
# Corner/calculations
# ===========================================================================
def test_deadline_reminder_due_at_lead_window_boundary(api):
    """PRD §3.3: "When the current clock is at or after the reminder instant but
    before `cycle_end`, it is `DUE`."
    PRD §3.3: "Define the reminder instant as the cycle's `cycle_end` minus the
    board's `reminder_lead_days`."

    Design: Corner/calculations/deadline_reminder_due_at_lead_window_boundary
    """
    board = FX.create_board(with_requirements=False, reminder_lead_days=60)
    licensee = FX.create_licensee(board["id"])
    cycle = FX.open_cycle(licensee["id"], board["id"])  # [2026-01-01, 2028-01-01)
    FX.set_clock("2027-11-02T00:00:00Z")  # within 60 days of cycle_end

    data = get_success_data(
        api.get_cycle_reminder(cycle["id"], make_licensee_headers(licensee["id"])))
    assert data["reminder_status"] == "DUE", (
        "2027-11-02 is within 60 days of 2028-01-01 cycle_end")


def test_deadline_reminder_overdue_after_cycle_end(api):
    """PRD §3.3: "When the current clock is at or after `cycle_end`, it is
    `OVERDUE`."
    PRD §3.3: "exactly at `cycle_end` it is `OVERDUE`."

    Design: Corner/calculations/deadline_reminder_overdue_after_cycle_end
    """
    board = FX.create_board(with_requirements=False, reminder_lead_days=60)
    licensee = FX.create_licensee(board["id"])
    cycle = FX.open_cycle(licensee["id"], board["id"])  # cycle_end 2028-01-01
    FX.set_clock("2028-01-01T00:00:00Z")  # exactly cycle_end

    data = get_success_data(
        api.get_cycle_reminder(cycle["id"], make_licensee_headers(licensee["id"])))
    assert data["reminder_status"] == "OVERDUE", "clock == cycle_end uses >="


def test_cycle_end_computed_from_board_cycle_length(api):
    """PRD §3.3: "The system computes the exclusive `cycle_end` by adding the
    board's `cycle_length_months` to the start; the renewal deadline is exactly
    `cycle_end`."

    Design: Corner/calculations/cycle_end_computed_from_board_cycle_length
    """
    board = FX.create_board(with_requirements=False, cycle_length_months=24)
    licensee = FX.create_licensee(board["id"])

    data = validate_success(api.create_renewal_cycle(
        F.create_renewal_cycle_payload(licensee["id"], board["id"], "2026-01-01T00:00:00Z"),
        make_licensee_headers(licensee["id"])), 201)
    assert data["cycle_end"] == "2028-01-01T00:00:00.000Z", (
        "cycle_start 2026-01-01 + 24 months == 2028-01-01")
