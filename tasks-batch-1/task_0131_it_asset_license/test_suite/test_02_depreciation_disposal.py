"""Straight-line depreciation (provisional book vs disposal-final variant),
the disposal settlement chain, and book-value conservation under reversal.

Queue A (difficulty) instances are each covered by multiple focused tests; the
Design line on every test names the single instance it translates.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    set_clock, create_vendor, create_hardware,
    submit_and_approve_disposal, dispose_asset,
    setup_product_with_active_entitlement, create_active_install,
)

MGR = TEST_USERS["asset_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]


def _depreciation_asset():
    """Asset: purchase 360000, salvage 0, life 36, in_service 2024-01-01.
    Clock at 2025-07-15 (18 whole months elapsed). Returns the created read."""
    set_clock("2025-07-15T00:00:00.000Z")
    vendor = create_vendor(vendor_type="HARDWARE", name="HW Corp")
    return create_hardware(
        vendor["id"], asset_tag="TAG-001", category="LAPTOP",
        purchase_cost_cents=360000, in_service_date="2024-01-01T00:00:00.000Z",
        useful_life_months=36, salvage_value_cents=0,
    )


# ─── dual_variant_calc / depreciation_book_vs_disposal_divergence ───

def test_provisional_depreciation_uses_whole_month_floor(api):
    """PRD 3.2: "the number of whole months elapsed is the count of complete
    months from the in-service date to the current server clock, never less
    than zero, and capped at the useful life in months; a partial final month
    is *floored away* and does not count."

    Design: Difficulty/dual_variant_calc/depreciation_book_vs_disposal_divergence
    """
    asset = _depreciation_asset()
    # 18 whole months floored: 360000/36 = 10000/month; 18*10000 = 180000 booked.
    assert asset["accumulated_depreciation_cents"] == 180000
    assert asset["net_book_value_cents"] == 180000


def test_disposal_final_depreciation_counts_partial_month_as_whole(api):
    """PRD 3.6: "a partial final month is counted as a *whole* month — rounded
    up rather than floored — though still capped at the useful life in months.
    Because a mid-month disposal therefore books one additional month of
    depreciation compared with the provisional floor, identical inputs yield a
    different `accumulated_depreciation_cents` and `net_book_value_cents` at
    disposal than a pre-disposal read would have shown."

    Design: Difficulty/dual_variant_calc/depreciation_book_vs_disposal_divergence
    """
    asset = _depreciation_asset()
    assert asset["net_book_value_cents"] == 180000  # provisional, for the divergence
    request = submit_and_approve_disposal(
        asset["id"], reason="END_OF_LIFE", proposed_proceeds_cents=150000,
    )
    validate_success(api.complete_disposal(request["id"], CO))
    disposed = validate_success(api.get_hardware(asset["id"], CO))
    # Disposal variant ceils the partial month → 19 months booked.
    assert disposed["accumulated_depreciation_cents"] == 190000
    assert disposed["net_book_value_cents"] == 170000
    assert disposed["status"] == "DISPOSED"


def test_disposal_gain_loss_is_proceeds_minus_final_book_value(api):
    """PRD 3.6: "its `disposal_gain_loss_cents` is computed as the disposal
    proceeds minus that net book value at disposal, a signed figure where a
    positive result is a gain and a negative result a loss."

    Design: Difficulty/dual_variant_calc/depreciation_book_vs_disposal_divergence
    """
    asset = _depreciation_asset()
    request = submit_and_approve_disposal(
        asset["id"], reason="END_OF_LIFE", proposed_proceeds_cents=150000,
    )
    validate_success(api.complete_disposal(request["id"], CO))
    disposed = validate_success(api.get_hardware(asset["id"], CO))
    # 150000 proceeds - 170000 final net book value = -20000 (loss).
    assert disposed["disposal_gain_loss_cents"] == -20000


# ─── transitive_cascade / disposal_complete_cascade_depth3 ───

def _asset_with_one_active_install():
    """Asset hosting 1 ACTIVE install charged to an entitlement (entitled=5),
    asset RETIRED via an approved disposal. Returns (asset, entitlement,
    install_id, request)."""
    set_clock("2025-03-01T00:00:00.000Z")
    vendor, product, entitlement = setup_product_with_active_entitlement(
        vendor_type="BOTH", license_model="PER_SEAT", entitled_units=5,
    )
    asset = create_hardware(vendor["id"], asset_tag="TAG-DISP", category="DESKTOP")
    install = create_active_install(product["id"], asset["id"], entitlement["id"])
    request = submit_and_approve_disposal(asset["id"], reason="END_OF_LIFE")
    return asset, entitlement, install["id"], request


def test_disposal_complete_disposes_asset(api):
    """PRD 3.6: "On completion the asset transitions from `RETIRED` to
    `DISPOSED`, and a sequence of settlements fires atomically."

    Design: Difficulty/transitive_cascade/disposal_complete_cascade_depth3
    """
    asset, entitlement, install_id, request = _asset_with_one_active_install()
    validate_success(api.complete_disposal(request["id"], CO))
    disposed = validate_success(api.get_hardware(asset["id"], CO))
    assert disposed["status"] == "DISPOSED"


def test_disposal_complete_cascades_uninstall_and_releases_units(api):
    """PRD 3.6: "every install still `ACTIVE` on the disposed asset is moved to
    `UNINSTALLED`, each releasing its charged units back to its entitlement's
    ledger."

    Design: Difficulty/transitive_cascade/disposal_complete_cascade_depth3
    """
    asset, entitlement, install_id, request = _asset_with_one_active_install()
    validate_success(api.complete_disposal(request["id"], CO))

    install_after = validate_success(api.get_installation(install_id, CO))
    assert install_after["status"] == "UNINSTALLED"  # hop 2 caused by hop 1

    ent_after = validate_success(api.get_entitlement(entitlement["id"], CO))
    assert ent_after["consumed_units"] == 0  # hop 3 caused by hop 2


# ─── compensating_invariant / total_net_book_value_conserved_dispose_reverse ───

def _dispose_then_reverse_asset():
    """Asset purchase=360000, salvage=0, life=36, in_service 2024-01-01, clock
    2025-07-15 (provisional nbv=180000). Disposed (proceeds 150000) then ready
    to reverse. Returns (asset, request, nbv_pre)."""
    set_clock("2025-07-15T00:00:00.000Z")
    vendor = create_vendor(vendor_type="HARDWARE", name="HW Corp")
    asset = create_hardware(
        vendor["id"], asset_tag="TAG-CI2", category="LAPTOP",
        purchase_cost_cents=360000, in_service_date="2024-01-01T00:00:00.000Z",
        useful_life_months=36, salvage_value_cents=0,
    )
    nbv_pre = asset["net_book_value_cents"]
    request = dispose_asset(asset["id"], reason="DAMAGED", proposed_proceeds_cents=150000)
    return asset, request, nbv_pre


def test_reversal_restores_provisional_book_value(api):
    """PRD 3.6: "It zeroes the asset's `disposal_proceeds_cents` and
    `disposal_gain_loss_cents`, recomputes `accumulated_depreciation_cents` and
    `net_book_value_cents` from the server clock on the provisional basis to
    restore the pre-disposal book value, returns the asset from `DISPOSED` to
    `RETIRED`, and marks the request `REVERSED`."

    Design: Difficulty/compensating_invariant/total_net_book_value_conserved_dispose_reverse
    """
    asset, request, nbv_pre = _dispose_then_reverse_asset()
    assert nbv_pre == 180000
    validate_success(api.reverse_disposal(request["id"], CO))
    restored = validate_success(api.get_hardware(asset["id"], CO))
    assert restored["net_book_value_cents"] == 180000  # back to provisional value
    assert restored["status"] == "RETIRED"


def test_reversal_zeroes_disposal_gain_loss(api):
    """PRD 3.6: "It zeroes the asset's `disposal_proceeds_cents` and
    `disposal_gain_loss_cents`, recomputes `accumulated_depreciation_cents` and
    `net_book_value_cents` from the server clock on the provisional basis to
    restore the pre-disposal book value".

    Design: Difficulty/compensating_invariant/total_net_book_value_conserved_dispose_reverse
    """
    asset, request, nbv_pre = _dispose_then_reverse_asset()
    validate_success(api.reverse_disposal(request["id"], CO))
    restored = validate_success(api.get_hardware(asset["id"], CO))
    assert restored["disposal_gain_loss_cents"] == 0


# ─── state_machines / transition_disposed_asset_is_terminal_locked ───

def test_transition_disposed_asset_is_terminal_locked(api):
    """PRD 3.6: "On completion the asset transitions from `RETIRED` to
    `DISPOSED`". PRD 3.2: "attempting a transition from the wrong starting state
    yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/transition_disposed_asset_is_terminal_locked
    """
    set_clock("2025-03-01T00:00:00.000Z")
    vendor = create_vendor(vendor_type="HARDWARE", name="HW Corp")
    asset = create_hardware(
        vendor["id"], asset_tag="TAG-TERM", category="LAPTOP",
        purchase_cost_cents=100000, in_service_date="2025-01-01T00:00:00.000Z",
    )
    dispose_asset(asset["id"], reason="END_OF_LIFE")
    resp = api.transition_hardware(asset["id"], "IN_REPAIR", MGR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
