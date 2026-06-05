"""Renewals (entitlement + coverage), renewal cost rounding, the entitlement
suspend/resume/renew cycle, coverage overlap arithmetic, renewal eligibility,
OCC stale-version on completion, and support-status reconciliation.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    set_clock, create_vendor, create_hardware, create_coverage,
    setup_product_with_active_entitlement, create_pending_install,
    create_entitlement_renewal_order, create_coverage_renewal_order,
)

MGR = TEST_USERS["asset_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# ─── combinatorial_formula / renewal_cost_round_then_sum_order ───

def test_renewal_cost_rounds_each_line_then_sums(api):
    """PRD 3.5: "the first line is the existing `entitled_units` times the
    `unit_price_cents` times the fraction `extend_months` divided by 12, rounded
    half up; the second line is the `added_units` times the `unit_price_cents`
    times that same `extend_months`-over-12 fraction, rounded half up."

    Design: Difficulty/combinatorial_formula/renewal_cost_round_then_sum_order
    """
    _, product, entitlement = setup_product_with_active_entitlement(
        vendor_type="SOFTWARE", license_model="PER_SEAT", entitled_units=7,
        unit_price_cents=1999,
    )
    order = create_entitlement_renewal_order(
        entitlement["id"], extend_months=6, added_units=3
    )
    resp = api.complete_renewal_order(
        order["id"], {"expected_entitlement_version": entitlement["version"]}, CO
    )
    completed = validate_success(resp)
    # round(7*1999*0.5)=round(6996.5)=6997 + round(3*1999*0.5)=round(2998.5)=2999 = 9996
    # (NOT round(9995.0)=9995, which sum-then-round would give).
    assert completed["quoted_cost_cents"] == 9996


def test_renewal_order_completes_with_quoted_cost(api):
    """PRD 3.5: "Completing a quoted order is what applies the extension and is
    where the cost is computed." PRD 3.5: "In all cases the order itself becomes
    `COMPLETED`."

    Design: Difficulty/combinatorial_formula/renewal_cost_round_then_sum_order
    """
    _, product, entitlement = setup_product_with_active_entitlement(
        vendor_type="SOFTWARE", license_model="PER_SEAT", entitled_units=7,
        unit_price_cents=1999,
    )
    order = create_entitlement_renewal_order(
        entitlement["id"], extend_months=6, added_units=3
    )
    resp = api.complete_renewal_order(
        order["id"], {"expected_entitlement_version": entitlement["version"]}, CO
    )
    completed = validate_success(resp)
    assert completed["status"] == "COMPLETED"


# ─── transitive_cascade / renewal_complete_cascade_depth2 ───

def test_renewal_completion_adds_units_to_entitlement(api):
    """PRD 3.5: "on success the entitlement's `term_end` is advanced by
    `extend_months` months, its `entitled_units` is increased by `added_units`,
    its `available_units` is recomputed, and its `version` increments."

    Design: Difficulty/transitive_cascade/renewal_complete_cascade_depth2
    """
    _, product, entitlement = setup_product_with_active_entitlement(
        vendor_type="SOFTWARE", license_model="PER_SEAT", entitled_units=5,
    )
    order = create_entitlement_renewal_order(
        entitlement["id"], extend_months=12, added_units=3
    )
    validate_success(api.complete_renewal_order(
        order["id"], {"expected_entitlement_version": entitlement["version"]}, CO
    ))
    ent_after = validate_success(api.get_entitlement(entitlement["id"], CO))
    assert ent_after["entitled_units"] == 8  # 5 + 3 added


def test_renewal_completion_recomputes_available_units(api):
    """PRD 3.5: "on success the entitlement's `term_end` is advanced by
    `extend_months` months, its `entitled_units` is increased by `added_units`,
    its `available_units` is recomputed, and its `version` increments."

    Design: Difficulty/transitive_cascade/renewal_complete_cascade_depth2
    """
    _, product, entitlement = setup_product_with_active_entitlement(
        vendor_type="SOFTWARE", license_model="PER_SEAT", entitled_units=5,
    )
    order = create_entitlement_renewal_order(
        entitlement["id"], extend_months=12, added_units=3
    )
    validate_success(api.complete_renewal_order(
        order["id"], {"expected_entitlement_version": entitlement["version"]}, CO
    ))
    ent_after = validate_success(api.get_entitlement(entitlement["id"], CO))
    assert ent_after["available_units"] == 8  # 8 entitled - 0 consumed


# ─── non_linear_state_machine / entitlement_cyclic_suspend_resume_renew_loop ───

def test_entitlement_suspend_then_resume_returns_to_active(api):
    """PRD 3.4: "Suspending an active entitlement moves it to `SUSPENDED`".
    PRD 3.4: "Resuming a suspended entitlement moves it back to `ACTIVE` and
    re-baselines the product's `compliance_status` to `COMPLIANT`".

    Design: Difficulty/non_linear_state_machine/entitlement_cyclic_suspend_resume_renew_loop
    """
    _, product, entitlement = setup_product_with_active_entitlement(
        vendor_type="SOFTWARE", license_model="PER_SEAT", entitled_units=5,
    )
    validate_success(api.transition_entitlement(entitlement["id"], "SUSPENDED", CO))
    resumed = validate_success(api.transition_entitlement(entitlement["id"], "ACTIVE", CO))
    assert resumed["status"] == "ACTIVE"


def test_entitlement_renewal_lands_back_on_active(api):
    """PRD 3.5: "The entitlement is marked `RENEWED` as the audit signal that a
    renewal occurred but immediately settles back to `ACTIVE` so that installs
    may continue to charge against it — this is the cyclic
    `ACTIVE → RENEWED → ACTIVE` pattern."

    Design: Difficulty/non_linear_state_machine/entitlement_cyclic_suspend_resume_renew_loop
    """
    _, product, entitlement = setup_product_with_active_entitlement(
        vendor_type="SOFTWARE", license_model="PER_SEAT", entitled_units=5,
    )
    # Suspend then resume, then renew — the full cycle.
    validate_success(api.transition_entitlement(entitlement["id"], "SUSPENDED", CO))
    resumed = validate_success(api.transition_entitlement(entitlement["id"], "ACTIVE", CO))
    order = create_entitlement_renewal_order(entitlement["id"], extend_months=6)
    validate_success(api.complete_renewal_order(
        order["id"], {"expected_entitlement_version": resumed["version"]}, CO
    ))
    ent_after = validate_success(api.get_entitlement(entitlement["id"], CO))
    assert ent_after["status"] == "ACTIVE"


# ─── resource_temporal_overlap / coverage_closed_interval_adjacency_allowed ───

def test_coverage_adjacent_window_allowed_then_overlap_rejected(api):
    """PRD 3.2: "the windows are treated as closed intervals, so zero-gap
    adjacency where one ends exactly as the next begins is permitted, but any
    true overlap is rejected with `ERR_COVERAGE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/coverage_closed_interval_adjacency_allowed
    """
    vendor = create_vendor(vendor_type="HARDWARE", name="Cov Co")
    asset = create_hardware(
        vendor["id"], asset_tag="TAG-OV2", category="SERVER",
        purchase_cost_cents=500000, in_service_date="2025-01-01T00:00:00.000Z",
    )
    create_coverage(
        asset["id"], vendor["id"], coverage_type="WARRANTY",
        coverage_start="2025-01-01T00:00:00.000Z", coverage_end="2025-06-30T00:00:00.000Z",
    )
    # Adjacent window starting the day after the prior end → accepted.
    cov2 = validate_success(api.create_coverage(
        {
            "hardware_asset_id": asset["id"], "vendor_id": vendor["id"],
            "coverage_type": "WARRANTY",
            "coverage_start": "2025-07-01T00:00:00.000Z",
            "coverage_end": "2025-12-31T00:00:00.000Z",
        },
        MGR,
    ), 201)
    assert cov2["status"] == "ACTIVE"


# ─── validations / coverage_renew_not_eligible_when_auto_renew_false ───

def test_coverage_renew_not_eligible_when_auto_renew_false(api):
    """PRD 3.5: "For a coverage target, the coverage must be `ACTIVE` and its
    `auto_renew` flag must be true; a coverage that is not active or not
    auto-renew-eligible is rejected with `ERR_RENEWAL_NOT_ELIGIBLE`."

    Design: Corner/validations/coverage_renew_not_eligible_when_auto_renew_false
    """
    vendor = create_vendor(vendor_type="HARDWARE", name="Cov Co")
    asset = create_hardware(
        vendor["id"], asset_tag="TAG-RNE", category="SERVER",
        purchase_cost_cents=500000, in_service_date="2025-01-01T00:00:00.000Z",
    )
    coverage = create_coverage(
        asset["id"], vendor["id"], coverage_type="LEASE",
        coverage_start="2025-01-01T00:00:00.000Z", coverage_end="2025-12-31T00:00:00.000Z",
        monthly_cost_cents=4500, auto_renew=False,
    )
    order = create_coverage_renewal_order(coverage["id"], extend_months=12)
    resp = api.complete_renewal_order(order["id"], {}, CO)
    validate_error(resp, ApiErrorId.ERR_RENEWAL_NOT_ELIGIBLE.value)


# ─── cross_cutting / occ_stale_version_on_renewal_complete_returns_412 ───

def test_renewal_complete_with_stale_entitlement_version_rejected(api):
    """PRD 2.7: "That completion request must include `expected_entitlement_version`
    carrying the entitlement `version` the order was quoted against. If the
    entitlement's `version` has advanced since the quote ... completion is
    rejected with `ERR_STALE_VERSION` (HTTP 412), and the renewal must be
    re-quoted against the current entitlement."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_renewal_complete_returns_412
    """
    vendor, product, entitlement = setup_product_with_active_entitlement(
        vendor_type="BOTH", license_model="PER_SEAT", entitled_units=5,
    )
    ev_stale = entitlement["version"]
    order = create_entitlement_renewal_order(entitlement["id"], extend_months=6)
    # An intervening install create bumps the entitlement version past ev_stale.
    asset = create_hardware(vendor["id"], asset_tag="TAG-OCC", category="DESKTOP")
    create_pending_install(product["id"], asset["id"], entitlement["id"])
    resp = api.complete_renewal_order(
        order["id"], {"expected_entitlement_version": ev_stale}, CO
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ─── cross_cutting / support_status_reconciles_to_out_of_warranty_after_clock_advance ───

def test_support_status_reconciles_to_in_warranty_while_active(api):
    """PRD 3.2: "Coverage of the asset by warranty or lease drives its
    `support_status`, a derived field that resolves to `IN_WARRANTY`, `LEASED`,
    `OUT_OF_WARRANTY`, or `UNCOVERED` based on whether an active coverage record
    spans the current server clock and whether that coverage is a warranty or a
    lease."

    Only the IN_WARRANTY branch is asserted: the PRD names the deciding inputs as
    "whether an active coverage record spans the current server clock and whether
    that coverage is a warranty or a lease", uniquely fixing the active-warranty
    case. The PRD gives no prose distinguishing OUT_OF_WARRANTY from UNCOVERED once
    a warranty is explicitly EXPIRED, so that branch is not asserted here.

    Design: Corner/cross_cutting_complexity_layers/support_status_reconciles_to_out_of_warranty_after_clock_advance
    """
    set_clock("2025-02-01T00:00:00.000Z")
    vendor = create_vendor(vendor_type="HARDWARE", name="Cov Co")
    asset = create_hardware(
        vendor["id"], asset_tag="TAG-SS", category="SERVER",
        purchase_cost_cents=500000, in_service_date="2025-01-01T00:00:00.000Z",
    )
    create_coverage(
        asset["id"], vendor["id"], coverage_type="WARRANTY",
        coverage_start="2025-01-01T00:00:00.000Z", coverage_end="2025-03-31T00:00:00.000Z",
    )
    # While an active warranty coverage spans the clock, the asset is in warranty.
    in_warranty = validate_success(api.get_hardware(asset["id"], MGR))
    assert in_warranty["support_status"] == "IN_WARRANTY"
