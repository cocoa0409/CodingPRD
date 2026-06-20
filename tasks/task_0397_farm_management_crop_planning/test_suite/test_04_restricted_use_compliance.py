"""Restricted-use applications: confirmation gating, REI/PHI windows, the
compliance cascade, validation precedence, and seasonal rate cap.

Difficulty queue A: transitive_cascade (confirm restricted -> parcel RESTRICTED ->
next confirm blocked), priority_pair_validation_conflict (state beats safety),
boundary_precision_check (REI exact-expiry clear).
Corner queue B: state_machines (begin-harvest PHI block, confirm idempotency),
calculations (seasonal rate cap), validations (applicator mismatch).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    make_applicator_headers,
    set_clock, setup_growing_plan, setup_confirmed_restricted_application,
    create_restricted_product, create_input_product, create_applicator,
    log_application,
)

FM = TEST_USERS["farm_manager_headers"]
AG = TEST_USERS["agronomist_headers"]


# ===========================================================================
# Difficulty: transitive_cascade — confirm_restricted_app_cascade_depth3
# ===========================================================================
def test_confirm_restricted_app_cascades_to_parcel_then_blocks_next(api):
    """PRD §3.4: "The parcel's `status` is set to `RESTRICTED`; the parcel's
    `reentry_blocked_until` is recomputed as the latest `reentry_clear_at` across all
    `ACTIVE` compliance records on that parcel".
    PRD §3.4: "if the parcel's `status` is `RESTRICTED` and the current clock is earlier
    than the parcel's `reentry_blocked_until`, the confirm is rejected with
    `ERR_REENTRY_INTERVAL_ACTIVE`".

    Design: Difficulty/transitive_cascade/confirm_restricted_app_cascade_depth3_parcel_restrict_then_block
    """
    # First restricted app confirmed at 2026-06-10, REI 48h -> blocked until 2026-06-12.
    ctx = setup_confirmed_restricted_application(
        reentry_interval_hours=48, preharvest_interval_days=7,
        confirm_clock="2026-06-10T00:00:00Z", initial_clock="2026-06-10T00:00:00Z",
        rate_per_acre=1.0, acres_treated=50.0)
    parcel = validate_success(api.get_parcel(ctx["parcel"]["id"], FM))
    assert parcel["status"] == "RESTRICTED", f"parcel must be RESTRICTED, got {parcel['status']}"
    assert parcel["reentry_blocked_until"] == "2026-06-12T00:00:00.000Z", (
        f"reentry_blocked_until must be 2026-06-12T00:00:00.000Z, got {parcel['reentry_blocked_until']}")

    # A second logged restricted app on the same parcel; confirm is blocked by REI.
    rec2 = log_application(ctx["plan"]["id"], ctx["chem_product"]["id"],
                           ctx["applicator"]["id"], rate_per_acre=1.0, acres_treated=50.0)
    resp = api.confirm_application(rec2["id"], make_applicator_headers(ctx["applicator"]["id"]))
    validate_error(resp, ApiErrorId.ERR_REENTRY_INTERVAL_ACTIVE.value)


def test_confirm_restricted_app_creates_active_compliance_record(api):
    """PRD §3.4: "A **compliance record** is created in `ACTIVE` status capturing the
    regulatory snapshot: its `application_record_id`, the denormalized `crop_plan_id`,
    the `applicator_user_id`, and point-in-time snapshots of `reentry_interval_hours`,
    `preharvest_interval_days`, and `reentry_clear_at`."

    Design: Difficulty/transitive_cascade/confirm_restricted_app_cascade_depth3_parcel_restrict_then_block
    """
    ctx = setup_confirmed_restricted_application(
        reentry_interval_hours=48, preharvest_interval_days=7,
        confirm_clock="2026-06-10T00:00:00Z", initial_clock="2026-06-10T00:00:00Z")
    listed = validate_success(api.list_compliance_records(
        FM, params={"crop_plan_id": ctx["plan"]["id"]}))
    assert len(listed) == 1, f"expected one compliance record, got {len(listed)}"
    cr = listed[0]
    assert cr["status"] == "ACTIVE", f"compliance record must be ACTIVE, got {cr['status']}"
    assert cr["application_record_id"] == ctx["app_record"]["id"]
    assert cr["crop_plan_id"] == ctx["plan"]["id"]


# ===========================================================================
# Difficulty: priority_pair_validation_conflict — state_beats_safety_on_confirm
# ===========================================================================
def test_state_check_beats_safety_when_plan_not_growing(api):
    """PRD §3.4: "The owning plan must be in `GROWING`, else `ERR_PLAN_NOT_GROWING`. If
    the product is restricted, the acting applicator must be certified — the
    `Applicator`'s `certified` flag must be true, else `ERR_APPLICATOR_NOT_CERTIFIED`".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_confirm_when_plan_not_growing
    """
    from test_helpers import create_parcel, create_draft_plan
    parcel = create_parcel(name="PF1", acreage=100.0)
    chem = create_restricted_product(
        name="RU Chem2", unit_cost=10.0, reentry_interval_hours=24, preharvest_interval_days=5)
    appl = create_applicator(full_name="Uncert", license_no="RU-X", certified=False)
    # Plan is APPROVED (not GROWING).
    plan = create_draft_plan(parcel["id"], crop="CORN", planned_acres=100.0)
    validate_success(api.approve_crop_plan(plan["id"], {"expected_parcel_version": parcel["version"]}, FM))
    rec = log_application(plan["id"], chem["id"], appl["id"], rate_per_acre=1.0, acres_treated=10.0)
    # Both plan-not-growing AND applicator-not-certified hold; PRD prose orders state first.
    resp = api.confirm_application(rec["id"], make_applicator_headers(appl["id"]))
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_GROWING.value)


def test_confirm_non_restricted_blocked_when_plan_not_growing(api):
    """PRD §3.4: "Confirmation is exclusively an `Applicator` action and is where
    compliance is enforced, advancing the record from `LOGGED` to `CONFIRMED`. The owning
    plan must be in `GROWING`, else `ERR_PLAN_NOT_GROWING`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_confirm_when_plan_not_growing
    """
    from test_helpers import create_parcel, create_draft_plan
    parcel = create_parcel(name="PF1b", acreage=100.0)
    fert = create_input_product(name="Fert NG", category="FERTILIZER", unit="GAL", unit_cost=5.0)
    appl = create_applicator(full_name="Cert", license_no="RU-NG", certified=True)
    # Plan in DRAFT (not GROWING).
    plan = create_draft_plan(parcel["id"], crop="CORN", planned_acres=100.0)
    rec = log_application(plan["id"], fert["id"], appl["id"], rate_per_acre=1.0, acres_treated=10.0)
    resp = api.confirm_application(rec["id"], make_applicator_headers(appl["id"]))
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_GROWING.value)


# ===========================================================================
# Difficulty: boundary_precision_check — reentry_interval_exact_expiry_is_clear
# ===========================================================================
def test_reentry_at_exact_expiry_is_clear(api):
    """PRD §3.4: "the boundary is inclusive of clearance, meaning a clock exactly equal
    to `reentry_blocked_until` is permitted (the block applies strictly before that
    instant)."

    Design: Difficulty/boundary_precision_check/reentry_interval_exact_expiry_is_clear
    """
    # First restricted app confirmed at 2026-06-10, REI 48h -> blocked until 2026-06-12.
    ctx = setup_confirmed_restricted_application(
        reentry_interval_hours=48, preharvest_interval_days=3,
        confirm_clock="2026-06-10T00:00:00Z", initial_clock="2026-06-10T00:00:00Z",
        rate_per_acre=1.0, acres_treated=50.0)
    # Second app logged; advance clock to EXACTLY reentry_blocked_until.
    rec2 = log_application(ctx["plan"]["id"], ctx["chem_product"]["id"],
                           ctx["applicator"]["id"], rate_per_acre=1.0, acres_treated=50.0)
    set_clock("2026-06-12T00:00:00Z")
    data = validate_success(api.confirm_application(
        rec2["id"], make_applicator_headers(ctx["applicator"]["id"])))
    assert data["status"] == "CONFIRMED", (
        f"confirm at exact expiry must succeed (CONFIRMED), got {data['status']}")


def test_reentry_one_second_before_expiry_blocked(api):
    """PRD §3.4: "if the parcel's `status` is `RESTRICTED` and the current clock is
    earlier than the parcel's `reentry_blocked_until`, the confirm is rejected with
    `ERR_REENTRY_INTERVAL_ACTIVE`; the boundary is inclusive of clearance, meaning a
    clock exactly equal to `reentry_blocked_until` is permitted (the block applies
    strictly before that instant)."

    Design: Difficulty/boundary_precision_check/reentry_interval_exact_expiry_is_clear
    """
    ctx = setup_confirmed_restricted_application(
        reentry_interval_hours=48, preharvest_interval_days=3,
        confirm_clock="2026-06-10T00:00:00Z", initial_clock="2026-06-10T00:00:00Z",
        rate_per_acre=1.0, acres_treated=50.0)
    rec2 = log_application(ctx["plan"]["id"], ctx["chem_product"]["id"],
                           ctx["applicator"]["id"], rate_per_acre=1.0, acres_treated=50.0)
    # One second before the 2026-06-12T00:00:00Z expiry: still blocked.
    set_clock("2026-06-11T23:59:59Z")
    resp = api.confirm_application(rec2["id"], make_applicator_headers(ctx["applicator"]["id"]))
    validate_error(resp, ApiErrorId.ERR_REENTRY_INTERVAL_ACTIVE.value)


# ===========================================================================
# Corner: begin-harvest PHI gate, confirm idempotency, applicator mismatch,
#         seasonal rate cap
# ===========================================================================
def test_begin_harvest_blocked_by_active_phi(api):
    """PRD §3.4: "Begin-harvest is blocked while the current clock is earlier than the
    latest such instant across the plan's restricted applications; a clock exactly equal to
    that instant satisfies the pre-harvest interval and is allowed (the block applies
    strictly before the instant)."
    PRD §3.4: "When the gate is not satisfied the transition fails with
    `ERR_PREHARVEST_INTERVAL_ACTIVE`."

    Design: Corner/state_machines/begin_harvest_blocked_by_active_phi
    """
    # Restricted app PHI=7d confirmed at 2026-06-10 -> earliest harvest 2026-06-17.
    ctx = setup_confirmed_restricted_application(
        reentry_interval_hours=12, preharvest_interval_days=7,
        confirm_clock="2026-06-10T00:00:00Z", initial_clock="2026-06-10T00:00:00Z",
        rate_per_acre=1.0, acres_treated=50.0)
    set_clock("2026-06-15T00:00:00Z")  # before 2026-06-17 -> PHI active.
    resp = api.begin_harvest(ctx["plan"]["id"], AG)
    validate_error(resp, ApiErrorId.ERR_PREHARVEST_INTERVAL_ACTIVE.value)


def test_confirm_already_confirmed_application_invalid_state(api):
    """PRD §3.4: "Confirmation is exclusively an `Applicator` action and is where
    compliance is enforced, advancing the record from `LOGGED` to `CONFIRMED`."
    PRD §2.10: "the target resource must be in a state from which the requested transition
    is defined, else `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/state_machines/confirm_application_from_logged_invalid_when_already_confirmed
    """
    set_clock("2026-06-10T00:00:00Z")
    ctx = setup_growing_plan(crop="CORN", planned_acres=40.0, acreage=100.0)
    fert = create_input_product(name="Fert ID", category="FERTILIZER", unit="GAL", unit_cost=5.0)
    appl = create_applicator(full_name="A", license_no="RU-61", certified=True)
    rec = log_application(ctx["plan"]["id"], fert["id"], appl["id"], rate_per_acre=1.0, acres_treated=10.0)
    validate_success(api.confirm_application(rec["id"], make_applicator_headers(appl["id"])))
    # Second confirm on an already-CONFIRMED record.
    resp = api.confirm_application(rec["id"], make_applicator_headers(appl["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_applicator_mismatch_on_restricted_confirm(api):
    """PRD §3.4: "the acting applicator's `id` must equal the record's
    `applicator_user_id`, else `ERR_APPLICATOR_MISMATCH`."

    Design: Corner/validations/applicator_mismatch_on_restricted_confirm
    """
    set_clock("2026-06-10T00:00:00Z")
    ctx = setup_growing_plan(crop="CORN", planned_acres=100.0, acreage=100.0)
    chem = create_restricted_product(
        name="RU AM", unit_cost=10.0, reentry_interval_hours=12, preharvest_interval_days=3)
    appl_x = create_applicator(full_name="X", license_no="RU-X1", certified=True)
    appl_y = create_applicator(full_name="Y", license_no="RU-Y1", certified=True)
    rec = log_application(ctx["plan"]["id"], chem["id"], appl_x["id"],
                          rate_per_acre=1.0, acres_treated=50.0)
    # Y (certified) attempts to confirm X's record.
    resp = api.confirm_application(rec["id"], make_applicator_headers(appl_y["id"]))
    validate_error(resp, ApiErrorId.ERR_APPLICATOR_MISMATCH.value)


def test_seasonal_rate_cap_exceeded_on_second_confirm(api):
    """PRD §3.4: "when the product's `max_seasonal_rate_per_acre` is set, the cumulative
    confirmed `rate_per_acre` for that product on that plan plus this record's
    `rate_per_acre` must not exceed the cap, else `ERR_SEASONAL_RATE_EXCEEDED`."

    Design: Corner/calculations/seasonal_rate_cap_at_boundary
    """
    set_clock("2026-06-10T00:00:00Z")
    ctx = setup_growing_plan(crop="CORN", planned_acres=100.0, acreage=100.0)
    capped = create_input_product(
        name="Capped Fert", category="FERTILIZER", unit="GAL", unit_cost=5.0,
        max_seasonal_rate_per_acre=3)
    appl = create_applicator(full_name="A", license_no="RU-80", certified=True)
    rec1 = log_application(ctx["plan"]["id"], capped["id"], appl["id"],
                           rate_per_acre=2.0, acres_treated=50.0)
    validate_success(api.confirm_application(rec1["id"], make_applicator_headers(appl["id"])))
    rec2 = log_application(ctx["plan"]["id"], capped["id"], appl["id"],
                           rate_per_acre=2.0, acres_treated=50.0)
    # cumulative 2 + 2 = 4 > cap 3.
    resp = api.confirm_application(rec2["id"], make_applicator_headers(appl["id"]))
    validate_error(resp, ApiErrorId.ERR_SEASONAL_RATE_EXCEEDED.value)


def test_actual_input_cost_visible_immediately_after_confirm(api):
    """PRD §2.5: "whenever an event changes the inputs to another entity's derived
    state, the server immediately recomputes and re-persists that dependent state in the
    same operation, with no separate client request required."
    PRD §3.4: "recomputes the plan's `actual_input_cost` and `provisional_cost_per_acre`."

    Design: Corner/consistency_model/immediate_visibility_actual_input_cost_after_confirm
    """
    set_clock("2026-06-10T00:00:00Z")
    ctx = setup_growing_plan(crop="CORN", planned_acres=100.0, acreage=100.0)
    fert = create_input_product(name="Fert IMM", category="FERTILIZER", unit="GAL", unit_cost=12.50)
    appl = create_applicator(full_name="A", license_no="RU-90", certified=True)
    rec = log_application(ctx["plan"]["id"], fert["id"], appl["id"],
                          rate_per_acre=2.0, acres_treated=40.0)
    validate_success(api.confirm_application(rec["id"], make_applicator_headers(appl["id"])))
    # Immediate read reflects the recomputed cost: 2 * 40 * 12.50 = 1000.00.
    data = validate_success(api.get_crop_plan(ctx["plan"]["id"], FM))
    assert data["actual_input_cost"] == 1000.00, (
        f"actual_input_cost must be 1000.00 immediately, got {data['actual_input_cost']}")
