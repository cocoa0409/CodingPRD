"""Part B / Part C / Part D enrollment lifecycles, preconditions, and cascades.

Covers the Part C branching state machine, the confirm-supersede-disenroll
depth-3 cascade, cross-entity state dependencies (Plan RETIRED, Part D ACTIVE),
and the Part B / Part C / Part D preconditions and valid transitions.
"""
from test_helpers import (
    validate_success, validate_error, set_clock, create_beneficiary, create_plan,
    create_period, setup_beneficiary_with_active_part_b, setup_confirmed_part_c,
    setup_confirmed_mapd_with_bundled_part_d,
    setup_pending_part_d, file_part_c, confirm_part_c, read_beneficiary_version,
    create_part_b_enrollment_payload, create_part_c_enrollment_payload, confirm_part_c_payload,
    create_part_d_enrollment_payload, create_drug_claim_payload, ApiErrorId, TEST_USERS,
)

ADMIN = TEST_USERS["enrollment_admin_headers"]


# ─── Part C branching: ACTIVE -> SUPERSEDED via confirm of a newer enrollment ──

def test_part_c_active_superseded_by_newer_confirm(api):
    """PRD §3.6: "Any other PartCEnrollment of the same beneficiary currently in
    ACTIVE is transitioned to SUPERSEDED, incrementing that superseded enrollment's
    version."

    Design: Difficulty/non_linear_state_machine/part_c_branching_active_to_superseded_vs_disenrolled
    """
    set_clock("2024-06-01T00:00:00.000Z")
    ben, iep, _plan1, pce1 = setup_confirmed_part_c(
        plan_overrides={"name": "MA One", "monthly_premium_cents": 0, "star_rating": 4.0})
    assert pce1["status"] == "ACTIVE"

    aep = create_period(ben["id"], "AEP", aep_year=2024)
    ma2 = create_plan(name="MA Two", part_type="PART_C", monthly_premium_cents=0,
                      star_rating=4.5, includes_drug_coverage=False)
    set_clock("2024-11-01T00:00:00.000Z")
    pce2 = file_part_c(ben["id"], ma2["id"], aep["id"])
    pce2 = confirm_part_c(pce2["id"], ben["id"])

    pce1_after = validate_success(api.get_part_c_enrollment(pce1["id"], ADMIN), 200)
    assert pce1_after["status"] == "SUPERSEDED"
    assert pce2["status"] == "ACTIVE"


def test_part_c_active_disenrolled_by_operator(api):
    """PRD §3.6: "An EnrollmentAdmin may also voluntarily disenroll an ACTIVE Part C
    enrollment, requiring it to be ACTIVE and the beneficiary not DECEASED, moving it
    to DISENROLLED and incrementing its version."

    Design: Difficulty/non_linear_state_machine/part_c_branching_active_to_superseded_vs_disenrolled
    """
    set_clock("2024-06-01T00:00:00.000Z")
    _ben, _iep, _plan, pce = setup_confirmed_part_c(
        plan_overrides={"name": "MA Dis", "monthly_premium_cents": 0, "star_rating": 4.0})
    res = api.disenroll_part_c_enrollment(pce["id"], ADMIN)
    disenrolled = validate_success(res, 200)
    assert disenrolled["status"] == "DISENROLLED"
    assert disenrolled["version"] == pce["version"] + 1


# ─── Depth-3 cascade: confirm -> supersede MAPD -> bundled Part D DISENROLLED ──

def test_confirm_supersede_disenrolls_bundled_mapd_part_d(api):
    """PRD §3.6: "Any other PartCEnrollment of the same beneficiary currently in
    ACTIVE is transitioned to SUPERSEDED, incrementing that superseded enrollment's
    version."
    PRD §3.6: "if the superseded plan was an MAPD - that is, its includes_drug_coverage
    was true - then the beneficiary's ACTIVE bundled drug enrollment, if any,
    transitions to DISENROLLED (incrementing its version), since the bundled drug
    coverage ends with the plan that carried it."

    Design: Difficulty/transitive_cascade/confirm_supersede_disenroll_bundled_mapd_depth3
    """
    set_clock("2024-06-01T00:00:00.000Z")
    # ACTIVE MAPD Part C with an ACTIVE bundled Part D. The bundled Part D is filed
    # while the MAPD is still PENDING (PRD §3.7 only forbids stacking on an ACTIVE
    # MAPD), then both are confirmed.
    ben, iep, _mapd1, _pdp, pce1, pde = setup_confirmed_mapd_with_bundled_part_d(
        mapd_plan_overrides={"name": "MAPD One", "monthly_premium_cents": 0, "star_rating": 4.0},
        pdp_plan_overrides={"name": "PDP Bundle", "monthly_premium_cents": 1500})
    assert pde["status"] == "ACTIVE"

    aep = create_period(ben["id"], "AEP", aep_year=2024)
    ma2 = create_plan(name="MA Two", part_type="PART_C", monthly_premium_cents=0,
                      star_rating=4.5, includes_drug_coverage=False)
    set_clock("2024-11-01T00:00:00.000Z")
    pce2 = file_part_c(ben["id"], ma2["id"], aep["id"])
    pce2 = confirm_part_c(pce2["id"], ben["id"])

    assert validate_success(api.get_part_c_enrollment(pce1["id"], ADMIN), 200)["status"] == "SUPERSEDED"
    assert validate_success(api.get_part_d_enrollment(pde["id"], ADMIN), 200)["status"] == "DISENROLLED"
    assert pce2["status"] == "ACTIVE"


# ─── Cross-entity state dependencies ──────────────────────────────────────────

def test_drug_claim_requires_active_part_d(api):
    """PRD §3.8: "A claim may post only to a Part D enrollment in ACTIVE status; a
    claim against any other status is rejected with ERR_INVALID_STATE (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/drug_claim_requires_partd_enrollment_active
    """
    set_clock("2024-11-01T00:00:00.000Z")
    _ben, _iep, _pdp, pde = setup_pending_part_d()
    assert pde["status"] == "PENDING"
    res = api.post_drug_claim(pde["id"],
                              create_drug_claim_payload(1000, "2024-11-05T00:00:00.000Z"), ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_part_c_confirm_rejects_retired_plan(api):
    """PRD §3.6: "the plan must be ACTIVE, with a RETIRED plan triggering
    ERR_PLAN_RETIRED (HTTP 409)."
    PRD §3.3: "A confirmation that references a RETIRED plan is rejected with
    ERR_PLAN_RETIRED (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/part_c_confirm_requires_plan_active_not_retired
    """
    set_clock("2024-06-01T00:00:00.000Z")
    ben, iep, _pbe = setup_beneficiary_with_active_part_b()
    ma = create_plan(name="MA R", part_type="PART_C", monthly_premium_cents=0,
                     star_rating=4.0, includes_drug_coverage=False)
    pce = file_part_c(ben["id"], ma["id"], iep["id"])
    validate_success(api.retire_plan(ma["id"], ADMIN), 200)
    ver = read_beneficiary_version(ben["id"])
    res = api.confirm_part_c_enrollment(pce["id"], confirm_part_c_payload(ver), ADMIN)
    validate_error(res, ApiErrorId.ERR_PLAN_RETIRED.value)


# ─── Preconditions: Part A required, Part B required ──────────────────────────

def test_activate_part_b_before_part_a_rejected(api):
    """PRD §3.5: "the beneficiary's part_a_status must be ENROLLED: Part A must be
    established before Part B can activate, and an attempt to activate before Part A
    is in place is rejected with ERR_PART_A_REQUIRED (HTTP 409)."

    Design: Corner/state_machines/activate_part_b_before_part_a_returns_part_a_required
    """
    set_clock("2024-06-01T00:00:00.000Z")
    ben = create_beneficiary(full_name="NoPA")
    iep = create_period(ben["id"], "IEP")
    pbe = validate_success(api.create_part_b_enrollment(
        create_part_b_enrollment_payload(ben["id"], iep["id"]), ADMIN), 201)
    res = api.activate_part_b_enrollment(pbe["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_PART_A_REQUIRED.value)


def test_confirm_part_c_without_part_b_rejected(api):
    """PRD §3.6: "the beneficiary's part_b_status must be ENROLLED, because Part C
    requires active Part B, and a confirm attempted otherwise is rejected with
    ERR_PART_B_REQUIRED (HTTP 409)"

    Design: Corner/state_machines/confirm_partc_without_part_b_returns_part_b_required
    """
    set_clock("2024-06-01T00:00:00.000Z")
    ben = create_beneficiary(full_name="NoPB")
    iep = create_period(ben["id"], "IEP")
    ma = create_plan(name="MA NoB", part_type="PART_C", monthly_premium_cents=0,
                     star_rating=4.0, includes_drug_coverage=False)
    pce = file_part_c(ben["id"], ma["id"], iep["id"])
    ver = read_beneficiary_version(ben["id"])
    res = api.confirm_part_c_enrollment(pce["id"], confirm_part_c_payload(ver), ADMIN)
    validate_error(res, ApiErrorId.ERR_PART_B_REQUIRED.value)


def test_confirm_already_active_part_c_rejected(api):
    """PRD §3.6: "the enrollment must currently be PENDING (ERR_INVALID_STATE, HTTP 409)"

    Design: Corner/state_machines/confirm_already_active_partc_returns_invalid_state
    """
    set_clock("2024-06-01T00:00:00.000Z")
    ben, _iep, _plan, pce = setup_confirmed_part_c(
        plan_overrides={"name": "MA Dbl", "monthly_premium_cents": 0, "star_rating": 4.0})
    assert pce["status"] == "ACTIVE"
    ver = read_beneficiary_version(ben["id"])
    res = api.confirm_part_c_enrollment(pce["id"], confirm_part_c_payload(ver), ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_confirm_part_d_with_creditable_coverage_no_penalty(api):
    """PRD §3.7: "At confirmation the system computes uncovered_months once and from it
    the lep_premium_cents, then increments the PartDEnrollment.version."
    PRD §3.7: "If there are no uncovered months the penalty is 0."

    Design: Corner/state_machines/confirm_partd_initial_state_pending_to_active_computes_lep_zero
    """
    set_clock("2024-11-01T00:00:00.000Z")
    # Creditable drug coverage held through the enrollment month: anchor month (Nov 2024)
    # equals the effective month, so the strictly-between count floors at 0 -> no penalty.
    _ben, _iep, _pdp, pde = setup_pending_part_d(part_d_creditable_since="2024-11-15T00:00:00.000Z")
    res = api.confirm_part_d_enrollment(pde["id"], ADMIN)
    confirmed = validate_success(res, 200)
    assert confirmed["uncovered_months"] == 0
    assert confirmed["lep_premium_cents"] == 0
    assert confirmed["status"] == "ACTIVE"


def test_part_d_confirm_immediate_consistency(api):
    """PRD §3.7: "At confirmation the system computes uncovered_months once and from it
    the lep_premium_cents, then increments the PartDEnrollment.version."
    PRD §3.7: "The raw penalty is one percent of the national base beneficiary premium
    - fixed at 3,470 cents - multiplied by the number of uncovered months. That raw
    amount is then rounded to the nearest dime: divide the raw cents by ten, round half
    up to the nearest whole dime, then multiply back by ten, yielding lep_premium_cents
    as an integer number of cents."

    Design: Corner/consistency_model/immediate_consistency_confirm_visible_in_same_response
    """
    set_clock("2024-11-01T00:00:00.000Z")
    _ben, _iep, _pdp, pde = setup_pending_part_d()
    set_clock("2026-01-15T00:00:00.000Z")
    res = api.confirm_part_d_enrollment(pde["id"], ADMIN)
    confirmed = validate_success(res, 200)
    assert confirmed["status"] == "ACTIVE"
    assert confirmed["lep_premium_cents"] == 450
