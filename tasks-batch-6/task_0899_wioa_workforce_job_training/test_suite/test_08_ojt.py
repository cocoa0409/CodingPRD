"""On-the-job-training contracts: reimbursement min-cap formula, aggregate slot capacity,
activation eligibility gate, and rate ceilings."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_area, intake_participant, make_eligible, enroll,
    create_employer, create_ojt, activate_ojt, setup_active_ojt_contract,
    create_ojt_payload,
    CM, BSR, FO, ANY,
)


def _eligible_enrolled(api, la_id, name):
    p = intake_participant(api, la_id, full_name=name)
    make_eligible(api, p["id"])
    enroll(api, p["id"])
    return p["id"]


# --- Reimbursement = min(round_half_up(rate*wage*hours), remaining obligation) ---
def test_reimbursement_second_post_capped_to_remaining_obligation(api):
    """PRD §3.6: "The amount actually reimbursed is the lesser of that gross figure and the
    contract's remaining obligation — `obligated_amount_cents` minus `amount_expended_cents`
    — and the contract's `amount_expended_cents` increases by that reimbursed amount."

    Design: Difficulty/combinatorial_formula/ojt_reimbursement_min_cap
    """
    ctx = setup_active_ojt_contract(api, obligated_amount_cents=100000,
                                    reimbursement_rate=0.5, wage_cents_per_hour=2000)
    # First: gross = 0.5*2000*80 = 80000 (<= remaining 100000) -> expended 80000.
    validate_success(api.reimburse_ojt(ctx["c_id"], {"hours_worked": 80}, FO))
    # Second: gross = 0.5*2000*40 = 40000, remaining = 20000 -> reimburse min = 20000.
    result = validate_success(api.reimburse_ojt(ctx["c_id"], {"hours_worked": 40}, FO))
    assert result["amount_expended_cents"] == 100000, result


def test_reimbursement_uses_gross_when_below_remaining(api):
    """PRD §3.6: "The gross reimbursement is the contract's `reimbursement_rate` multiplied
    by its `wage_cents_per_hour` and by the supplied hours worked, rounded half-up to a
    whole cent. The amount actually reimbursed is the lesser of that gross figure and the
    contract's remaining obligation".

    Design: Difficulty/combinatorial_formula/ojt_reimbursement_min_cap
    """
    ctx = setup_active_ojt_contract(api, obligated_amount_cents=100000,
                                    reimbursement_rate=0.5, wage_cents_per_hour=2000)
    # gross = 0.5*2000*40 = 40000 <= remaining 100000 -> reimburse the gross.
    result = validate_success(api.reimburse_ojt(ctx["c_id"], {"hours_worked": 40}, FO))
    assert result["amount_expended_cents"] == 40000, result


# --- Aggregate slot capacity (interval-stabbing count) ---
def test_activate_over_capacity_rejected(api):
    """PRD §3.6: "among the employer's currently-`ACTIVE` contracts whose half-open period
    overlaps this contract's half-open period, activation is refused if that overlapping
    count is already at or above `max_concurrent_ojt_slots`."

    Design: Difficulty/resource_temporal_overlap/ojt_slot_capacity_aggregate
    """
    area = create_area(api)
    emp = create_employer(api, area["id"], max_concurrent_ojt_slots=1)
    pa = _eligible_enrolled(api, area["id"], "P A")
    pb = _eligible_enrolled(api, area["id"], "P B")
    ca = create_ojt(api, emp["id"], pa, start_date="2026-06-01T00:00:00Z",
                    end_date="2026-09-01T00:00:00Z")
    activate_ojt(api, ca["id"])
    cb = create_ojt(api, emp["id"], pb, start_date="2026-07-01T00:00:00Z",
                    end_date="2026-10-01T00:00:00Z")  # overlaps cA
    resp = api.activate_ojt(cb["id"], BSR)
    validate_error(resp, ApiErrorId.ERR_OJT_CAPACITY_EXCEEDED.value)


def test_activate_adjacent_period_within_capacity_succeeds(api):
    """PRD §3.6: "up to the cap number of periods may overlap at once, and adjacency where
    one period ends exactly when another begins is not an overlap."

    Design: Difficulty/resource_temporal_overlap/ojt_slot_capacity_aggregate
    """
    area = create_area(api)
    emp = create_employer(api, area["id"], max_concurrent_ojt_slots=1)
    pa = _eligible_enrolled(api, area["id"], "P A")
    pc = _eligible_enrolled(api, area["id"], "P C")
    ca = create_ojt(api, emp["id"], pa, start_date="2026-06-01T00:00:00Z",
                    end_date="2026-09-01T00:00:00Z")
    activate_ojt(api, ca["id"])
    cc = create_ojt(api, emp["id"], pc, start_date="2026-09-01T00:00:00Z",
                    end_date="2026-12-01T00:00:00Z")  # adjacent, no overlap
    result = validate_success(api.activate_ojt(cc["id"], BSR))
    assert result["status"] == "ACTIVE", result


# --- Activation gated on participant eligibility + enrollment ---
def test_activate_ojt_with_pending_participant_rejected(api):
    """PRD §3.6: "rejected with `ERR_PARTICIPANT_NOT_ELIGIBLE` unless the trainee's
    eligibility is `ELIGIBLE` and enrollment is `ENROLLED`".

    Design: Difficulty/cross_entity_state_dependency/ojt_activate_requires_eligible_participant
    """
    area = create_area(api)
    emp = create_employer(api, area["id"], max_concurrent_ojt_slots=5)
    p = intake_participant(api, area["id"])  # PENDING, NOT_ENROLLED
    c = create_ojt(api, emp["id"], p["id"])
    resp = api.activate_ojt(c["id"], BSR)
    validate_error(resp, ApiErrorId.ERR_PARTICIPANT_NOT_ELIGIBLE.value)


def test_activate_ojt_with_eligible_but_not_enrolled_participant_rejected(api):
    """PRD §3.6: "rejected with `ERR_PARTICIPANT_NOT_ELIGIBLE` unless the trainee's
    eligibility is `ELIGIBLE` and enrollment is `ENROLLED`".

    Design: Difficulty/cross_entity_state_dependency/ojt_activate_requires_eligible_participant
    """
    area = create_area(api)
    emp = create_employer(api, area["id"], max_concurrent_ojt_slots=5)
    p = intake_participant(api, area["id"])
    make_eligible(api, p["id"])  # ELIGIBLE but still NOT_ENROLLED
    c = create_ojt(api, emp["id"], p["id"])
    resp = api.activate_ojt(c["id"], BSR)
    validate_error(resp, ApiErrorId.ERR_PARTICIPANT_NOT_ELIGIBLE.value)


def test_create_ojt_rate_over_large_ceiling_rejected(api):
    """PRD §3.6: "The reimbursement rate must be greater than zero and may not exceed the
    employer's size ceiling — 0.75 for a `SMALL` employer and 0.50 for a `LARGE` employer;
    a rate above the applicable ceiling is rejected with `ERR_OJT_RATE_EXCEEDED`."

    Design: Corner/validations/ojt_rate_over_large_employer_ceiling_returns_rate_exceeded
    """
    area = create_area(api)
    p = intake_participant(api, area["id"])
    emp = create_employer(api, area["id"], name="BigCo", size="LARGE", max_concurrent_ojt_slots=5)
    resp = api.create_ojt(emp["id"], create_ojt_payload(p["id"], reimbursement_rate=0.75), BSR)
    validate_error(resp, ApiErrorId.ERR_OJT_RATE_EXCEEDED.value)
