"""ITA training-period overlap (half-open) and the ordered obligation preconditions
where an earlier-priority failure pre-empts a later one."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_training_ready, create_voucher, obligate_voucher, area_version,
    create_area, intake_participant, make_eligible, enroll, create_plan, activate_plan,
    setup_etpl_program,
    ADMIN, CM,
)


# --- Training period overlap (half-open) ---
def test_overlapping_training_period_rejected(api):
    """PRD §3.4: "the voucher's training period must not overlap the half-open training
    period of any other `OBLIGATED` voucher of the same participant
    (`ERR_TRAINING_PERIOD_OVERLAP`)".

    Design: Difficulty/resource_temporal_overlap/ita_training_period_overlap_halfopen
    """
    ctx = setup_training_ready(api)
    v1 = create_voucher(api, ctx["p_id"], ctx["prog_id"], ctx["cp_id"],
                        authorized_cost_cents=100000,
                        planned_start_date="2026-06-01T00:00:00Z",
                        planned_end_date="2026-09-01T00:00:00Z")
    obligate_voucher(api, v1["id"], ctx["la_version"])
    v2 = create_voucher(api, ctx["p_id"], ctx["prog_id"], ctx["cp_id"],
                        authorized_cost_cents=100000,
                        planned_start_date="2026-08-01T00:00:00Z",
                        planned_end_date="2026-11-01T00:00:00Z")  # overlaps v1
    fresh = area_version(api, ctx["la_id"])
    resp = api.obligate_voucher(v2["id"], {"expected_local_area_version": fresh}, CM)
    validate_error(resp, ApiErrorId.ERR_TRAINING_PERIOD_OVERLAP.value)


def test_adjacent_training_period_allowed(api):
    """PRD §2.6: "Consequently two back-to-back periods where one ends at exactly the instant
    the next begins do **not** overlap and are permitted."

    Design: Difficulty/resource_temporal_overlap/ita_training_period_overlap_halfopen
    """
    ctx = setup_training_ready(api)
    v1 = create_voucher(api, ctx["p_id"], ctx["prog_id"], ctx["cp_id"],
                        authorized_cost_cents=100000,
                        planned_start_date="2026-06-01T00:00:00Z",
                        planned_end_date="2026-09-01T00:00:00Z")
    obligate_voucher(api, v1["id"], ctx["la_version"])
    v3 = create_voucher(api, ctx["p_id"], ctx["prog_id"], ctx["cp_id"],
                        authorized_cost_cents=100000,
                        planned_start_date="2026-09-01T00:00:00Z",
                        planned_end_date="2026-12-01T00:00:00Z")  # adjacent to v1
    fresh = area_version(api, ctx["la_id"])
    result = validate_success(api.obligate_voucher(v3["id"], {"expected_local_area_version": fresh}, CM))
    assert result["status"] == "OBLIGATED", result


def _eligible_not_enrolled_training(api, authorized_cost_cents):
    """Area + ELIGIBLE-but-NOT-ENROLLED participant + ACTIVE plan + ETPL program +
    a DRAFT voucher of the given authorized cost. Returns the context dict."""
    area = create_area(api)
    p = intake_participant(api, area["id"])
    make_eligible(api, p["id"])
    cp = create_plan(api, p["id"])
    activate_plan(api, cp["id"])
    etpl = setup_etpl_program(api, area["id"])
    v = create_voucher(api, p["id"], etpl["prog_id"], cp["id"],
                       authorized_cost_cents=authorized_cost_cents)
    return {"la_id": area["id"], "la_version": area["version"], "p_id": p["id"], "v_id": v["id"]}


# --- Ordered obligation preconditions: state (p5) beats fiscal cap (p9) ---
def test_obligate_state_check_pre_empts_fiscal_cap(api):
    """PRD §3.4: "the participant's enrollment must be `ENROLLED`
    (`ERR_PARTICIPANT_NOT_ENROLLED`); the referenced career plan's status must be `ACTIVE`
    (`ERR_NO_ACTIVE_CAREER_PLAN`); the referenced program's status must be `ACTIVE`
    (`ERR_PROGRAM_NOT_ELIGIBLE`); the voucher's training period must not overlap the
    half-open training period of any other `OBLIGATED` voucher of the same participant
    (`ERR_TRAINING_PERIOD_OVERLAP`); the authorized cost must not exceed the area's
    `ita_individual_cap_cents` (`ERR_ITA_CAP_EXCEEDED`)".

    Design: Difficulty/priority_pair_validation_conflict/obligate_state_beats_fiscal
    """
    ctx = _eligible_not_enrolled_training(api, authorized_cost_cents=900000)  # > cap 800000
    resp = api.obligate_voucher(ctx["v_id"], {"expected_local_area_version": ctx["la_version"]}, CM)
    validate_error(resp, ApiErrorId.ERR_PARTICIPANT_NOT_ENROLLED.value)


def test_obligate_fiscal_cap_surfaces_once_enrollment_fixed(api):
    """PRD §3.4: "the participant's enrollment must be `ENROLLED`
    (`ERR_PARTICIPANT_NOT_ENROLLED`); ... the authorized cost must not exceed the area's
    `ita_individual_cap_cents` (`ERR_ITA_CAP_EXCEEDED`)".

    Design: Difficulty/priority_pair_validation_conflict/obligate_state_beats_fiscal
    """
    ctx = _eligible_not_enrolled_training(api, authorized_cost_cents=900000)
    enroll(api, ctx["p_id"])  # remove the state failure; the fiscal cap failure remains
    resp = api.obligate_voucher(ctx["v_id"], {"expected_local_area_version": ctx["la_version"]}, CM)
    validate_error(resp, ApiErrorId.ERR_ITA_CAP_EXCEEDED.value)


# --- Ordered obligation preconditions: constraint (p7) beats temporal (p8) ---
def test_obligate_program_constraint_pre_empts_temporal_overlap(api):
    """PRD §3.4: "the referenced program's status must be `ACTIVE`
    (`ERR_PROGRAM_NOT_ELIGIBLE`); the voucher's training period must not overlap the
    half-open training period of any other `OBLIGATED` voucher of the same participant
    (`ERR_TRAINING_PERIOD_OVERLAP`)".

    Design: Difficulty/priority_pair_validation_conflict/obligate_constraint_beats_temporal
    """
    ctx = setup_training_ready(api)
    v1 = create_voucher(api, ctx["p_id"], ctx["prog_id"], ctx["cp_id"],
                        authorized_cost_cents=100000,
                        planned_start_date="2026-06-01T00:00:00Z",
                        planned_end_date="2026-09-01T00:00:00Z")
    obligate_voucher(api, v1["id"], ctx["la_version"])
    validate_success(api.suspend_provider(ctx["prov_id"], ADMIN))  # program -> SUSPENDED
    v2 = create_voucher(api, ctx["p_id"], ctx["prog_id"], ctx["cp_id"],
                        authorized_cost_cents=100000,
                        planned_start_date="2026-08-01T00:00:00Z",
                        planned_end_date="2026-11-01T00:00:00Z")  # overlaps v1 AND program suspended
    fresh = area_version(api, ctx["la_id"])
    resp = api.obligate_voucher(v2["id"], {"expected_local_area_version": fresh}, CM)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ELIGIBLE.value)


def test_obligate_temporal_overlap_fires_when_program_active(api):
    """PRD §3.4: "the voucher's training period must not overlap the half-open training
    period of any other `OBLIGATED` voucher of the same participant
    (`ERR_TRAINING_PERIOD_OVERLAP`)".

    Design: Difficulty/priority_pair_validation_conflict/obligate_constraint_beats_temporal
    """
    ctx = setup_training_ready(api)
    v1 = create_voucher(api, ctx["p_id"], ctx["prog_id"], ctx["cp_id"],
                        authorized_cost_cents=100000,
                        planned_start_date="2026-06-01T00:00:00Z",
                        planned_end_date="2026-09-01T00:00:00Z")
    obligate_voucher(api, v1["id"], ctx["la_version"])
    v2 = create_voucher(api, ctx["p_id"], ctx["prog_id"], ctx["cp_id"],
                        authorized_cost_cents=100000,
                        planned_start_date="2026-08-01T00:00:00Z",
                        planned_end_date="2026-11-01T00:00:00Z")  # overlaps v1; program still ACTIVE
    fresh = area_version(api, ctx["la_id"])
    resp = api.obligate_voucher(v2["id"], {"expected_local_area_version": fresh}, CM)
    validate_error(resp, ApiErrorId.ERR_TRAINING_PERIOD_OVERLAP.value)
