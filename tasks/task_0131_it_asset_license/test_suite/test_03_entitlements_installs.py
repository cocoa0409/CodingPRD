"""Entitlement capacity charging: per-core required-units math, the exact
capacity boundary, install/uninstall conservation, cross-entity activation
gating, the expiry cascade, and state-vs-fiscal precedence.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    set_clock, create_vendor, create_hardware,
    setup_product_with_active_entitlement, create_active_install,
    create_pending_install, setup_entitlement_with_active_installs,
)

MGR = TEST_USERS["asset_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# ─── combinatorial_formula / per_core_required_units_nested_max_ceil ───

def test_per_core_required_units_max_of_floor_and_ceil_product(api):
    """PRD 3.4: "For a per-core product it is the larger of the product's
    `min_core_units` and the machine's physical core count multiplied by the
    product's `core_factor` and rounded up to the next whole number — the
    ceiling is applied to that product before the minimum floor is taken".

    Design: Difficulty/combinatorial_formula/per_core_required_units_nested_max_ceil
    """
    _, product, entitlement = setup_product_with_active_entitlement(
        vendor_type="SOFTWARE", license_model="PER_CORE", entitled_units=50,
        core_factor=0.5, min_core_units=4,
    )
    asset = create_hardware(
        product["vendor_id"], asset_tag="SRV-10C", category="SERVER",
        physical_cores=10, purchase_cost_cents=500000,
        in_service_date="2025-01-01T00:00:00.000Z",
    )
    install = create_pending_install(product["id"], asset["id"], entitlement["id"])
    # max(4, ceil(10 * 0.5)) = max(4, 5) = 5 — ceil/multiply wins over the floor.
    assert install["required_core_units"] == 5


def test_per_core_required_units_floor_wins_when_ceil_smaller(api):
    """PRD 3.4: "For a per-core product it is the larger of the product's
    `min_core_units` and the machine's physical core count multiplied by the
    product's `core_factor` and rounded up to the next whole number — the
    ceiling is applied to that product before the minimum floor is taken".

    Design: Difficulty/combinatorial_formula/per_core_required_units_nested_max_ceil
    """
    _, product, entitlement = setup_product_with_active_entitlement(
        vendor_type="SOFTWARE", license_model="PER_CORE", entitled_units=50,
        core_factor=0.5, min_core_units=4,
    )
    # cores=6 → ceil(6*0.5)=3, max(4, 3)=4 — the per-install minimum floor wins.
    asset = create_hardware(
        product["vendor_id"], asset_tag="SRV-6C", category="SERVER",
        physical_cores=6, purchase_cost_cents=500000,
        in_service_date="2025-01-01T00:00:00.000Z",
    )
    install = create_pending_install(product["id"], asset["id"], entitlement["id"])
    assert install["required_core_units"] == 4


# ─── boundary_precision_check / entitlement_exceeded_at_exact_capacity ───

def test_activate_install_at_exact_capacity_succeeds(api):
    """PRD 3.4: "the entitlement's current `consumed_units` plus this install's
    `required_core_units` must not exceed its `entitled_units`; if charging this
    install would push consumption past the entitled pool, activation is
    rejected with `ERR_ENTITLEMENT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/entitlement_exceeded_at_exact_capacity
    """
    # entitled=5, 4 already consumed; one more PENDING ready → activating it makes 5 == 5.
    vendor, product, entitlement, asset, active_ids, pending_ids = (
        setup_entitlement_with_active_installs(
            num_active=4, entitled_units=5, license_model="PER_SEAT", extra_pending=1
        )
    )
    fifth = pending_ids[0]
    activated = validate_success(api.activate_installation(fifth, MGR))
    assert activated["status"] == "ACTIVE"  # consumed 4 + 1 == 5, boundary allowed


def test_activate_install_one_past_capacity_rejected(api):
    """PRD 3.4: "the entitlement's current `consumed_units` plus this install's
    `required_core_units` must not exceed its `entitled_units`; if charging this
    install would push consumption past the entitled pool, activation is
    rejected with `ERR_ENTITLEMENT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/entitlement_exceeded_at_exact_capacity
    """
    # entitled=5, 5 already consumed; a 6th PENDING ready → activating it makes 6 > 5.
    vendor, product, entitlement, asset, active_ids, pending_ids = (
        setup_entitlement_with_active_installs(
            num_active=5, entitled_units=5, license_model="PER_SEAT", extra_pending=1
        )
    )
    sixth = pending_ids[0]
    resp = api.activate_installation(sixth, MGR)
    validate_error(resp, ApiErrorId.ERR_ENTITLEMENT_EXCEEDED.value)


# ─── cross_entity_state_dependency / install_activate_requires_entitlement_active ───

def test_install_activate_requires_entitlement_active(api):
    """PRD 3.4: "Activation requires the install to be `PENDING` ...; the charged
    entitlement to be `ACTIVE`, with a non-active entitlement rejected as
    `ERR_ENTITLEMENT_NOT_ACTIVE`".

    Design: Difficulty/cross_entity_state_dependency/install_activate_requires_entitlement_active
    """
    vendor, product, entitlement = setup_product_with_active_entitlement(
        vendor_type="SOFTWARE", license_model="PER_SEAT", entitled_units=5,
    )
    asset = create_hardware(vendor["id"], asset_tag="TAG-CE1", category="DESKTOP")
    install = create_pending_install(product["id"], asset["id"], entitlement["id"])
    # Suspend the entitlement, then try to activate the pending install.
    validate_success(api.transition_entitlement(entitlement["id"], "SUSPENDED", CO))
    resp = api.activate_installation(install["id"], MGR)
    validate_error(resp, ApiErrorId.ERR_ENTITLEMENT_NOT_ACTIVE.value)


def test_install_activate_against_active_entitlement_succeeds(api):
    """PRD 3.4: "Activation requires the install to be `PENDING` ...; the charged
    entitlement to be `ACTIVE`, with a non-active entitlement rejected as
    `ERR_ENTITLEMENT_NOT_ACTIVE`".

    Design: Difficulty/cross_entity_state_dependency/install_activate_requires_entitlement_active
    """
    vendor, product, entitlement = setup_product_with_active_entitlement(
        vendor_type="SOFTWARE", license_model="PER_SEAT", entitled_units=5,
    )
    asset = create_hardware(vendor["id"], asset_tag="TAG-CE1B", category="DESKTOP")
    install = create_pending_install(product["id"], asset["id"], entitlement["id"])
    # Entitlement is ACTIVE → activation passes the cross-entity gate.
    activated = validate_success(api.activate_installation(install["id"], MGR))
    assert activated["status"] == "ACTIVE"


# ─── compensating_invariant / entitlement_consumed_units_conserved_install_uninstall ───

def test_uninstall_conserves_consumed_units(api):
    """PRD 3.4: "uninstalling decreases the entitlement's `consumed_units` by
    exactly the units that install had charged and recomputes `available_units`,
    so that the consumed total is conserved across the install-then-uninstall
    cycle."

    Design: Difficulty/compensating_invariant/entitlement_consumed_units_conserved_install_uninstall
    """
    vendor, product, entitlement = setup_product_with_active_entitlement(
        vendor_type="SOFTWARE", license_model="PER_SEAT", entitled_units=5,
    )
    asset = create_hardware(vendor["id"], asset_tag="TAG-CI1", category="DESKTOP")
    install = create_active_install(product["id"], asset["id"], entitlement["id"])
    validate_success(api.transition_installation(install["id"], "UNINSTALLED", MGR))
    ent_after = validate_success(api.get_entitlement(entitlement["id"], MGR))
    assert ent_after["consumed_units"] == 0  # back to pre-install value


def test_uninstall_recomputes_available_units(api):
    """PRD 3.4: "uninstalling decreases the entitlement's `consumed_units` by
    exactly the units that install had charged and recomputes `available_units`,
    so that the consumed total is conserved across the install-then-uninstall
    cycle."

    Design: Difficulty/compensating_invariant/entitlement_consumed_units_conserved_install_uninstall
    """
    vendor, product, entitlement = setup_product_with_active_entitlement(
        vendor_type="SOFTWARE", license_model="PER_SEAT", entitled_units=5,
    )
    asset = create_hardware(vendor["id"], asset_tag="TAG-CI1B", category="DESKTOP")
    install = create_active_install(product["id"], asset["id"], entitlement["id"])
    validate_success(api.transition_installation(install["id"], "UNINSTALLED", MGR))
    ent_after = validate_success(api.get_entitlement(entitlement["id"], MGR))
    assert ent_after["available_units"] == 5  # 5 entitled - 0 consumed


# ─── priority_pair_validation_conflict / state_beats_fiscal_on_install_activate ───

def test_reactivate_active_install_returns_state_not_fiscal(api):
    """PRD 2.8: "Only after all four pass does the system evaluate state legality
    (fifth), then optimistic-concurrency staleness (sixth), then the
    domain-specific business rules." PRD 3.4: "Activation requires the install
    to be `PENDING` (else `ERR_INVALID_STATE`)".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_install_activate
    """
    # entitled=1, one install activated → pool full AND install already ACTIVE.
    vendor, product, entitlement, asset, active_ids, _ = (
        setup_entitlement_with_active_installs(
            num_active=1, entitled_units=1, license_model="PER_SEAT", extra_pending=0
        )
    )
    # Re-activating the now-ACTIVE install: state violation (p5) outranks the
    # fiscal exhaustion (p17) → ERR_INVALID_STATE, not ERR_ENTITLEMENT_EXCEEDED.
    resp = api.activate_installation(active_ids[0], MGR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_state_check_precedes_fiscal_on_install_activate(api):
    """PRD 2.8: "Only after all four pass does the system evaluate state legality
    (fifth), then optimistic-concurrency staleness (sixth), then the
    domain-specific business rules." PRD 3.4: "Activation requires the install
    to be `PENDING` (else `ERR_INVALID_STATE`)".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_install_activate
    """
    # entitled=1, one install activated → pool exhausted. A *fresh* PENDING
    # install on the exhausted pool has only the fiscal violation and returns
    # ERR_ENTITLEMENT_EXCEEDED; the already-ACTIVE install (state + fiscal both
    # failing) instead returns ERR_INVALID_STATE — proving state pre-empts fiscal.
    vendor, product, entitlement, asset, active_ids, pending_ids = (
        setup_entitlement_with_active_installs(
            num_active=1, entitled_units=1, license_model="PER_SEAT", extra_pending=1
        )
    )
    fiscal_only = api.activate_installation(pending_ids[0], MGR)
    validate_error(fiscal_only, ApiErrorId.ERR_ENTITLEMENT_EXCEEDED.value)

    state_and_fiscal = api.activate_installation(active_ids[0], MGR)
    validate_error(state_and_fiscal, ApiErrorId.ERR_INVALID_STATE.value)


# ─── state_machines / activate_already_active_entitlement_returns_invalid_state ───

def test_activate_already_active_entitlement_returns_invalid_state(api):
    """PRD 3.4: "Activating it moves it from `DRAFT` to `ACTIVE`; activation
    requires that it currently be `DRAFT` (else `ERR_INVALID_STATE`)".

    Design: Corner/state_machines/activate_already_active_entitlement_returns_invalid_state
    """
    vendor, product, entitlement = setup_product_with_active_entitlement(
        vendor_type="SOFTWARE", license_model="PER_SEAT", entitled_units=5,
    )
    # Entitlement already ACTIVE → a second activate is illegal.
    resp = api.activate_entitlement(entitlement["id"], MGR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ─── state_machines / install_id_and_system_fields (PENDING + computed) ───
# (covered in test_01 as install_id_and_system_fields_server_generated)


# ─── state_machines / entitlement_expire_cascade_uninstalls_active_installs ───

def test_entitlement_expire_cascade_uninstalls_active_installs(api):
    """PRD 3.4: "Expiry moves the entitlement to `EXPIRED` and cascades: every
    install currently `ACTIVE` and charged to that entitlement is moved to
    `UNINSTALLED`, each decrementing the entitlement's `consumed_units` by the
    units it had charged."

    Design: Corner/state_machines/entitlement_expire_cascade_uninstalls_active_installs
    """
    set_clock("2025-04-01T00:00:00.000Z")
    vendor = create_vendor(vendor_type="BOTH", name="Mixed")
    from test_helpers import create_software_product, create_entitlement, activate_entitlement
    product = create_software_product(vendor["id"], license_model="PER_SEAT")
    entitlement = create_entitlement(
        product["id"], vendor["id"], entitled_units=5,
        term_start="2025-01-01T00:00:00.000Z", term_end="2025-05-31T00:00:00.000Z",
    )
    activate_entitlement(entitlement["id"])
    asset = create_hardware(vendor["id"], asset_tag="TAG-EXC", category="DESKTOP")
    install = create_active_install(product["id"], asset["id"], entitlement["id"])
    # Advance the clock strictly past term_end, then force-expire.
    set_clock("2025-06-01T00:00:00.000Z")
    validate_success(api.transition_entitlement(entitlement["id"], "EXPIRED", CO))

    install_after = validate_success(api.get_installation(install["id"], CO))
    assert install_after["status"] == "UNINSTALLED"

    ent_after = validate_success(api.get_entitlement(entitlement["id"], CO))
    assert ent_after["consumed_units"] == 0
