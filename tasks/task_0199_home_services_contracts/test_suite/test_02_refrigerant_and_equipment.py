"""Refrigerant mass-balance, the deep-recovery equipment cascade, decommission, and
equipment registration.

Covers Difficulty queue: combinatorial_formula (running balance), transitive_cascade
(deep-recovery), boundary_precision_check (decommission zero-charge), compensating_invariant
(mass conservation); plus corner entities/validations on equipment.
"""
from test_helpers import (
    validate_success,
    validate_error,
    api_client,
    TEST_USERS,
    make_technician_headers,
    create_refrigerant_log_payload,
    create_equipment_payload,
    ApiErrorId,
    setup_visit_on_site,
    setup_active_membership_with_tech,
    book_visit,
    drive_visit_to_on_site,
    create_site,
    create_customer,
    get_equipment,
    get_membership,
)

ADMIN = TEST_USERS["contract_admin_headers"]


def _post_log(api, visit_id, tech_id, action, grams, expect_status=201):
    return validate_success(
        api.post_refrigerant_log(visit_id, create_refrigerant_log_payload("eq", action, grams),
                                 make_technician_headers(tech_id)),
        expect_status,
    )


# ===========================================================================
# Difficulty / combinatorial_formula — order-pinned running accumulator
# ===========================================================================
def test_refrigerant_recover_then_add_returns_to_nameplate(api):
    """PRD §3.7: "A unit's `current_charge_grams` is reconstructed as its
    `nameplate_charge_grams` plus the total grams of all `ADD` logs minus the total grams
    of all `RECOVER` logs, with logs processed in ascending `created_at` order."
    PRD §3.7: "if a visit recovers some number of grams from a unit and later adds the
    same number of grams back to the same unit, the unit's `current_charge_grams` returns
    to its pre-visit value."

    Design: Difficulty/combinatorial_formula/refrigerant_running_balance_evaluation_order_pinned
    """
    ctx = setup_visit_on_site(equipment_overrides={"nameplate_charge_grams": 4000, "refrigerant_type": "R410A"})
    visit_id, eq_id, tech_id = ctx["visit"]["id"], ctx["equipment"]["id"], ctx["technician"]["id"]
    tech_headers = make_technician_headers(tech_id)

    validate_success(
        api.post_refrigerant_log(visit_id, create_refrigerant_log_payload(eq_id, "RECOVER", 600), tech_headers), 201
    )
    validate_success(
        api.post_refrigerant_log(visit_id, create_refrigerant_log_payload(eq_id, "ADD", 600), tech_headers), 201
    )
    eq = get_equipment(eq_id)
    assert eq["current_charge_grams"] == 4000, (
        f"RECOVER 600 then ADD 600 nets to nameplate 4000, got {eq['current_charge_grams']}"
    )


def test_refrigerant_intermediate_balance_after_recover(api):
    """PRD §3.7: "A unit's `current_charge_grams` is reconstructed as its
    `nameplate_charge_grams` plus the total grams of all `ADD` logs minus the total grams
    of all `RECOVER` logs, with logs processed in ascending `created_at` order."

    Design: Difficulty/combinatorial_formula/refrigerant_running_balance_evaluation_order_pinned
    """
    ctx = setup_visit_on_site(equipment_overrides={"nameplate_charge_grams": 4000, "refrigerant_type": "R410A"})
    visit_id, eq_id, tech_id = ctx["visit"]["id"], ctx["equipment"]["id"], ctx["technician"]["id"]
    validate_success(
        api.post_refrigerant_log(visit_id, create_refrigerant_log_payload(eq_id, "RECOVER", 600),
                                 make_technician_headers(tech_id)), 201
    )
    # After a single RECOVER of 600 the running balance is nameplate - 600 = 3400.
    eq = get_equipment(eq_id)
    assert eq["current_charge_grams"] == 3400, (
        f"4000 - 600 = 3400 after one RECOVER, got {eq['current_charge_grams']}"
    )


# ===========================================================================
# Difficulty / compensating_invariant — conserved refrigerant mass
# ===========================================================================
def test_refrigerant_mass_conserved_after_compensating_add(api):
    """PRD §3.7: "The conservation property is exact — if a visit recovers some number of
    grams from a unit and later adds the same number of grams back to the same unit, the
    unit's `current_charge_grams` returns to its pre-visit value."

    Design: Difficulty/compensating_invariant/refrigerant_recover_then_charge_conserves_equipment_mass
    """
    ctx = setup_visit_on_site(equipment_overrides={"nameplate_charge_grams": 4000, "refrigerant_type": "R410A"})
    visit_id, eq_id, tech_id = ctx["visit"]["id"], ctx["equipment"]["id"], ctx["technician"]["id"]
    tech_headers = make_technician_headers(tech_id)
    validate_success(
        api.post_refrigerant_log(visit_id, create_refrigerant_log_payload(eq_id, "RECOVER", 600), tech_headers), 201
    )
    validate_success(
        api.post_refrigerant_log(visit_id, create_refrigerant_log_payload(eq_id, "ADD", 600), tech_headers), 201
    )
    eq = get_equipment(eq_id)
    assert eq["current_charge_grams"] == 4000, (
        f"net-zero compensating pair conserves mass at nameplate 4000, got {eq['current_charge_grams']}"
    )


def test_refrigerant_mass_conserved_for_larger_compensating_pair(api):
    """PRD §3.7: "The conservation property is exact — if a visit recovers some number of
    grams from a unit and later adds the same number of grams back to the same unit, the
    unit's `current_charge_grams` returns to its pre-visit value."

    Design: Difficulty/compensating_invariant/refrigerant_recover_then_charge_conserves_equipment_mass
    """
    ctx = setup_visit_on_site(equipment_overrides={"nameplate_charge_grams": 4000, "refrigerant_type": "R410A"})
    visit_id, eq_id, tech_id = ctx["visit"]["id"], ctx["equipment"]["id"], ctx["technician"]["id"]
    tech_headers = make_technician_headers(tech_id)
    # A larger but still-compensating pair (2500 out, 2500 back) also conserves mass.
    validate_success(
        api.post_refrigerant_log(visit_id, create_refrigerant_log_payload(eq_id, "RECOVER", 2500), tech_headers), 201
    )
    validate_success(
        api.post_refrigerant_log(visit_id, create_refrigerant_log_payload(eq_id, "ADD", 2500), tech_headers), 201
    )
    eq = get_equipment(eq_id)
    assert eq["current_charge_grams"] == 4000, (
        f"RECOVER 2500 then ADD 2500 returns to pre-visit nameplate 4000, got {eq['current_charge_grams']}"
    )


# ===========================================================================
# Difficulty / transitive_cascade — deep recovery flags equipment on completion
# ===========================================================================
def test_visit_complete_deep_recovery_flags_equipment_and_counts_consumption(api):
    """PRD §3.8: "Third, the system applies the deep-recovery equipment cascade. If any
    `RECOVER` refrigerant log posted during the visit left a piece of equipment's
    `current_charge_grams` below ten percent of its `nameplate_charge_grams`, that
    equipment's `operational_status` cascades from `OPERATIONAL` to `NEEDS_SERVICE`."
    PRD §3.8: "Second, the membership's `visits_consumed` becomes the recomputed count of
    the membership's visits that have reached `COMPLETED` within the current term window."

    Design: Difficulty/transitive_cascade/visit_complete_deep_recovery_flags_equipment_and_bumps_consumption
    """
    ctx = setup_visit_on_site(equipment_overrides={"nameplate_charge_grams": 4000, "refrigerant_type": "R410A"})
    visit_id, eq_id, tech_id = ctx["visit"]["id"], ctx["equipment"]["id"], ctx["technician"]["id"]
    tech_headers = make_technician_headers(tech_id)
    # RECOVER 3700 -> current 300, which is below 10% of 4000 (= 400).
    validate_success(
        api.post_refrigerant_log(visit_id, create_refrigerant_log_payload(eq_id, "RECOVER", 3700), tech_headers), 201
    )
    completed = validate_success(api.complete_service_visit(visit_id, tech_headers), 200)
    assert completed["status"] == "COMPLETED"

    eq = get_equipment(eq_id)
    assert eq["current_charge_grams"] == 300, f"current_charge_grams should be 300, got {eq['current_charge_grams']}"
    assert eq["operational_status"] == "NEEDS_SERVICE", (
        f"deep recovery (300 < 400 = 10% of 4000) cascades to NEEDS_SERVICE, got {eq['operational_status']}"
    )
    membership = get_membership(ctx["membership"]["id"])
    assert membership["visits_consumed"] == 1, f"one completion -> visits_consumed 1, got {membership['visits_consumed']}"


def test_visit_complete_recovery_at_ten_percent_does_not_flag_equipment(api):
    """PRD §3.8: "If any `RECOVER` refrigerant log posted during the visit left a piece of
    equipment's `current_charge_grams` below ten percent of its `nameplate_charge_grams`,
    that equipment's `operational_status` cascades from `OPERATIONAL` to `NEEDS_SERVICE`."

    Design: Difficulty/transitive_cascade/visit_complete_deep_recovery_flags_equipment_and_bumps_consumption
    """
    ctx = setup_visit_on_site(equipment_overrides={"nameplate_charge_grams": 4000, "refrigerant_type": "R410A"})
    visit_id, eq_id, tech_id = ctx["visit"]["id"], ctx["equipment"]["id"], ctx["technician"]["id"]
    tech_headers = make_technician_headers(tech_id)
    # RECOVER 3600 -> current 400, which is exactly 10% of 4000 (NOT below 10%).
    validate_success(
        api.post_refrigerant_log(visit_id, create_refrigerant_log_payload(eq_id, "RECOVER", 3600), tech_headers), 201
    )
    validate_success(api.complete_service_visit(visit_id, tech_headers), 200)
    eq = get_equipment(eq_id)
    assert eq["current_charge_grams"] == 400
    assert eq["operational_status"] == "OPERATIONAL", (
        f"400 == 10% of 4000 is not below 10%, so no NEEDS_SERVICE cascade, got {eq['operational_status']}"
    )


# ===========================================================================
# Difficulty / boundary_precision_check — decommission requires zero charge
# ===========================================================================
def test_equipment_decommission_succeeds_only_at_zero_charge(api):
    """PRD §3.9: "Decommissioning enforces the EPA recovery rule: a unit may not retire
    while it still holds refrigerant, so its `current_charge_grams` must be exactly 0,
    otherwise the request is rejected with `ERR_REFRIGERANT_NOT_EVACUATED`."

    Design: Difficulty/boundary_precision_check/equipment_decommission_requires_zero_charge_empty_set_boundary
    """
    ctx = setup_visit_on_site(equipment_overrides={"nameplate_charge_grams": 4000, "refrigerant_type": "R410A"})
    visit_id, eq_id, tech_id = ctx["visit"]["id"], ctx["equipment"]["id"], ctx["technician"]["id"]
    tech_headers = make_technician_headers(tech_id)
    # Recover the full 4000g so current_charge_grams == 0.
    validate_success(
        api.post_refrigerant_log(visit_id, create_refrigerant_log_payload(eq_id, "RECOVER", 4000), tech_headers), 201
    )
    validate_success(api.complete_service_visit(visit_id, tech_headers), 200)

    before = get_equipment(eq_id)
    assert before["current_charge_grams"] == 0, f"expected 0 after full recovery, got {before['current_charge_grams']}"

    result = validate_success(api.decommission_equipment(eq_id, ADMIN), 200)
    assert result["operational_status"] == "DECOMMISSIONED", (
        f"decommission at exactly 0 charge succeeds, got {result['operational_status']}"
    )


def test_equipment_decommission_with_remaining_charge_rejected(api):
    """PRD §3.9: "Decommissioning enforces the EPA recovery rule: a unit may not retire
    while it still holds refrigerant, so its `current_charge_grams` must be exactly 0,
    otherwise the request is rejected with `ERR_REFRIGERANT_NOT_EVACUATED`."

    Design: Difficulty/boundary_precision_check/equipment_decommission_requires_zero_charge_empty_set_boundary
    """
    ctx = setup_visit_on_site(equipment_overrides={"nameplate_charge_grams": 4000, "refrigerant_type": "R410A"})
    visit_id, eq_id, tech_id = ctx["visit"]["id"], ctx["equipment"]["id"], ctx["technician"]["id"]
    tech_headers = make_technician_headers(tech_id)
    # Recover all but 1 gram so current_charge_grams == 1 (just above the 0 boundary).
    validate_success(
        api.post_refrigerant_log(visit_id, create_refrigerant_log_payload(eq_id, "RECOVER", 3999), tech_headers), 201
    )
    validate_success(api.complete_service_visit(visit_id, tech_headers), 200)
    assert get_equipment(eq_id)["current_charge_grams"] == 1

    validate_error(api.decommission_equipment(eq_id, ADMIN), ApiErrorId.ERR_REFRIGERANT_NOT_EVACUATED.value)


# ===========================================================================
# Corner / validations — refrigerant balance overcharge
# ===========================================================================
def test_refrigerant_add_above_nameplate_rejected(api):
    """PRD §3.7: "an `ADD` may never drive `current_charge_grams` above
    `nameplate_charge_grams` (an overcharge); either violation is rejected with
    `ERR_REFRIGERANT_BALANCE`."

    Design: Corner/validations/refrigerant_add_exceeds_nameplate_balance_error
    """
    ctx = setup_visit_on_site(equipment_overrides={"nameplate_charge_grams": 4000, "refrigerant_type": "R410A"})
    visit_id, eq_id, tech_id = ctx["visit"]["id"], ctx["equipment"]["id"], ctx["technician"]["id"]
    # The unit is already full at 4000; ADD 1 would overcharge.
    validate_error(
        api.post_refrigerant_log(visit_id, create_refrigerant_log_payload(eq_id, "ADD", 1),
                                 make_technician_headers(tech_id)),
        ApiErrorId.ERR_REFRIGERANT_BALANCE.value,
    )


# ===========================================================================
# Corner / entities — equipment current_charge computed from nameplate
# ===========================================================================
def test_equipment_current_charge_initialized_from_nameplate(api):
    """PRD §3.7: "The unit also tracks its live refrigerant mass in
    `current_charge_grams`, which is set to `nameplate_charge_grams` at registration and
    thereafter accumulates the refrigerant logs posted against it."
    PRD §3.7: "The operational axis, `operational_status`, is one of `OPERATIONAL`,
    `NEEDS_SERVICE`, or `DECOMMISSIONED` and begins `OPERATIONAL`. The warranty axis,
    `warranty_status`, is one of `IN_WARRANTY`, `EXPIRED`, or `VOIDED` and begins
    `IN_WARRANTY`."

    Design: Corner/entities/equipment_current_charge_initialized_from_nameplate_computed
    """
    customer = create_customer()
    site = create_site(customer["id"])
    eq = validate_success(
        api.create_equipment(
            create_equipment_payload(site["id"], model="HP-2", refrigerant_type="R32",
                                     nameplate_charge_grams=2500), ADMIN), 201
    )
    assert eq["current_charge_grams"] == 2500, (
        f"current_charge_grams initialized to nameplate 2500, got {eq['current_charge_grams']}"
    )
    assert eq["operational_status"] == "OPERATIONAL"
    assert eq["warranty_status"] == "IN_WARRANTY"
