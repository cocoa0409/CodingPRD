"""Quote pricing math and the tint-compliance gates that run at price time.

Covers the combinatorial pricing formula (sum-then-round discount, circular
net-tier rush fee), the VLT legal-floor boundary, the empty-included-lines
guard, and the medical-exemption / windshield / material-compatibility gates.
"""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId,
    make_customer_headers, make_compliance_officer_headers,
)
from test_helpers import fixtures as fx

SM = fx.SM
CO = fx.CO


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/quote_discount_sum_then_round_order
# ---------------------------------------------------------------------------
def test_fleet_discount_rounded_once_on_summed_subtotal(api):
    """PRD §3.3: "discount_cents is the fleet discount applied to that summed
    subtotal: it is the subtotal multiplied by the fleet account's discount_bps
    divided by 10000, rounded half-up - and computed once on the sum, never line
    by line."
    PRD §3.3: "First, subtotal_cents is the sum of line_total_cents over the
    INCLUDED lines."

    Design: Difficulty/combinatorial_formula/quote_discount_sum_then_round_order
    """
    fx.create_regulation(state_code="NV", front_side_min_vlt_pct=35,
                         windshield_strip_max_inches=5, medical_exemption_allowed=False)
    shop = fx.create_shop(state_code="NV")
    fleet = fx.create_fleet(fleet_manager_user_id="fm-3", discount_bps=777,
                            credit_limit_cents=100000000, company_name="RoundCo")
    pkg_tint = fx.create_package(**fx.TINT_PACKAGE)
    pkg_ppf = fx.create_package(**fx.PPF_PACKAGE)
    mat_tint = fx.create_material("CER-NV", **fx.TINT_MATERIAL)
    mat_ppf = fx.create_material("PPF-NV", **fx.PPF_MATERIAL)
    veh = fx.create_vehicle(customer_user_id="cust-3", vin="VIN-ROUND")
    quote, v0 = fx.create_quote(veh["id"], shop["id"], fleet_account_id=fleet["id"], rushed=False)
    line1 = fx.add_line(quote["id"], v0, pkg_tint["id"], mat_tint["id"],
                        coverage="FULL", window_position="REAR_SIDE", requested_vlt_pct=50)
    line2 = fx.add_line(quote["id"], line1["version"], pkg_ppf["id"], mat_ppf["id"],
                        coverage="PARTIAL", window_position="BODY_PANEL")

    resp = api.price_quote(quote["id"], {"expected_quote_version": line2["version"]})
    data = validate_success(resp)

    assert data["subtotal_cents"] == 94600, f"subtotal {data['subtotal_cents']}"
    assert data["discount_cents"] == 7350, (
        f"sum-then-round discount must be 7350 (not per-line 7351), got {data['discount_cents']}")
    assert data["net_cents"] == 87250, f"net {data['net_cents']}"
    assert data["total_due_cents"] == 87250, f"total_due {data['total_due_cents']}"
    assert data["deposit_required_cents"] == 21813, f"deposit {data['deposit_required_cents']}"


def test_quote_subtotal_is_sum_of_included_line_totals(api):
    """PRD §3.3: "First, subtotal_cents is the sum of line_total_cents over the
    INCLUDED lines."
    PRD §3.3: "rounds that product half-up to a whole number of cents, and only
    then adds the vehicle's integer size_surcharge_cents; the sum is the line's
    line_total_cents."

    Design: Difficulty/combinatorial_formula/quote_discount_sum_then_round_order
    """
    fx.create_regulation(state_code="NV", front_side_min_vlt_pct=35,
                         windshield_strip_max_inches=5, medical_exemption_allowed=False)
    shop = fx.create_shop(state_code="NV")
    fleet = fx.create_fleet(fleet_manager_user_id="fm-3", discount_bps=777,
                            credit_limit_cents=100000000, company_name="RoundCo")
    pkg_tint = fx.create_package(**fx.TINT_PACKAGE)
    pkg_ppf = fx.create_package(**fx.PPF_PACKAGE)
    mat_tint = fx.create_material("CER-NV", **fx.TINT_MATERIAL)
    mat_ppf = fx.create_material("PPF-NV", **fx.PPF_MATERIAL)
    veh = fx.create_vehicle(customer_user_id="cust-3", vin="VIN-ROUND")
    quote, v0 = fx.create_quote(veh["id"], shop["id"], fleet_account_id=fleet["id"], rushed=False)
    line1 = fx.add_line(quote["id"], v0, pkg_tint["id"], mat_tint["id"],
                        coverage="FULL", window_position="REAR_SIDE", requested_vlt_pct=50)
    line2 = fx.add_line(quote["id"], line1["version"], pkg_ppf["id"], mat_ppf["id"],
                        coverage="PARTIAL", window_position="BODY_PANEL")

    data = validate_success(api.price_quote(quote["id"], {"expected_quote_version": line2["version"]}))
    # 40600 (tint full sedan ceramic) + 54000 (ppf partial sedan std) = 94600.
    assert data["subtotal_cents"] == 94600, f"subtotal {data['subtotal_cents']}"


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/rush_fee_circular_net_tier
# ---------------------------------------------------------------------------
def test_rush_fee_keyed_off_net_tier_high_boundary(api):
    """PRD §3.3: "if the quote is rushed, a rush rate in basis points is chosen
    from the net tier - 500 basis points when net_cents is at least 100000, 800
    basis points when net_cents is at least 50000 but below 100000, and 1200 basis
    points when net_cents is below 50000 - and rush_fee_cents is net_cents
    multiplied by that rate divided by 10000, rounded half-up."

    Design: Difficulty/combinatorial_formula/rush_fee_circular_net_tier
    """
    fx.create_regulation(state_code="AZ", front_side_min_vlt_pct=33,
                         windshield_strip_max_inches=5, medical_exemption_allowed=False)
    shop = fx.create_shop(state_code="AZ")
    pkg = fx.create_package(name="Big Wrap", service_type="WRAP", base_rate_cents=100000,
                            duration_minutes=240, cure_buffer_minutes=60,
                            warranty_days=730, requires_proof=True)
    mat = fx.create_material("VINYL-AZ", category="WRAP_VINYL", cure_hours=12,
                             price_multiplier_bps=10000)
    veh = fx.create_vehicle(customer_user_id="cust-4", vin="VIN-RUSH")
    quote, v0 = fx.create_quote(veh["id"], shop["id"], rushed=True)
    line = fx.add_line(quote["id"], v0, pkg["id"], mat["id"], coverage="FULL",
                       window_position="BODY_PANEL")

    data = validate_success(api.price_quote(quote["id"], {"expected_quote_version": line["version"]}))

    assert data["net_cents"] == 100000, f"net {data['net_cents']}"
    assert data["rush_fee_cents"] == 5000, (
        f"rush_bps 500 at net>=100000 -> 5000, got {data['rush_fee_cents']}")
    assert data["total_due_cents"] == 105000, f"total_due {data['total_due_cents']}"


def test_standard_quote_has_zero_rush_fee_total_equals_net(api):
    """PRD §3.3: "if the quote is not rushed the rush_fee_cents is 0 and
    total_due_cents equals net_cents".

    Design: Difficulty/combinatorial_formula/rush_fee_circular_net_tier
    """
    fx.create_regulation(state_code="AZ", front_side_min_vlt_pct=33,
                         windshield_strip_max_inches=5, medical_exemption_allowed=False)
    shop = fx.create_shop(state_code="AZ")
    pkg = fx.create_package(name="Big Wrap", service_type="WRAP", base_rate_cents=100000,
                            duration_minutes=240, cure_buffer_minutes=60,
                            warranty_days=730, requires_proof=True)
    mat = fx.create_material("VINYL-AZ2", category="WRAP_VINYL", cure_hours=12,
                             price_multiplier_bps=10000)
    veh = fx.create_vehicle(customer_user_id="cust-4b", vin="VIN-STD")
    quote, v0 = fx.create_quote(veh["id"], shop["id"], rushed=False)
    line = fx.add_line(quote["id"], v0, pkg["id"], mat["id"], coverage="FULL",
                       window_position="BODY_PANEL")

    data = validate_success(api.price_quote(quote["id"], {"expected_quote_version": line["version"]}))
    assert data["net_cents"] == 100000, f"net {data['net_cents']}"
    assert data["rush_fee_cents"] == 0, f"unrushed rush_fee must be 0, got {data['rush_fee_cents']}"
    assert data["total_due_cents"] == data["net_cents"], "total_due must equal net when unrushed"


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/tint_vlt_at_legal_floor_inclusive
# ---------------------------------------------------------------------------
def test_front_side_vlt_at_exact_floor_prices_ok(api):
    """PRD §3.4: "For a line whose window_position is FRONT_SIDE, the requested
    requested_vlt_pct must be at least the effective floor."
    PRD §3.3: "Pricing a quote drives the transition from DRAFT to PRICED."

    Design: Difficulty/boundary_precision_check/tint_vlt_at_legal_floor_inclusive
    """
    fx.create_regulation(state_code="CA", front_side_min_vlt_pct=35,
                         windshield_strip_max_inches=5, medical_exemption_allowed=True)
    shop = fx.create_shop(state_code="CA")
    pkg = fx.create_package(**fx.TINT_PACKAGE)
    mat = fx.create_material("CER-B1", **fx.TINT_MATERIAL)
    veh = fx.create_vehicle(customer_user_id="cust-11", vin="VIN-B1")
    quote, v0 = fx.create_quote(veh["id"], shop["id"])
    line = fx.add_line(quote["id"], v0, pkg["id"], mat["id"], coverage="FULL",
                       window_position="FRONT_SIDE", requested_vlt_pct=35)

    data = validate_success(api.price_quote(quote["id"], {"expected_quote_version": line["version"]}))
    assert data["status"] == "PRICED", f"35 >= 35 must price OK, status {data['status']}"
    assert data["subtotal_cents"] == 40600, f"subtotal {data['subtotal_cents']}"


def test_front_side_vlt_one_below_floor_rejected(api):
    """PRD §3.4: "A front-side line below its effective floor is rejected with
    ERR_TINT_BELOW_LEGAL_VLT (HTTP 422)."

    Design: Difficulty/boundary_precision_check/tint_vlt_at_legal_floor_inclusive
    """
    fx.create_regulation(state_code="CA", front_side_min_vlt_pct=35,
                         windshield_strip_max_inches=5, medical_exemption_allowed=True)
    shop = fx.create_shop(state_code="CA")
    pkg = fx.create_package(**fx.TINT_PACKAGE)
    mat = fx.create_material("CER-B1b", **fx.TINT_MATERIAL)
    veh = fx.create_vehicle(customer_user_id="cust-11b", vin="VIN-B1b")
    quote, v0 = fx.create_quote(veh["id"], shop["id"])
    line = fx.add_line(quote["id"], v0, pkg["id"], mat["id"], coverage="FULL",
                       window_position="FRONT_SIDE", requested_vlt_pct=34)

    resp = api.price_quote(quote["id"], {"expected_quote_version": line["version"]})
    validate_error(resp, ApiErrorId.ERR_TINT_BELOW_LEGAL_VLT.value)


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/empty_included_lines_blocks_price
# ---------------------------------------------------------------------------
def test_price_with_only_removed_line_rejected(api):
    """PRD §3.3: "pricing a quote with no included lines is rejected with
    ERR_NO_INCLUDED_LINES (HTTP 422)."
    PRD §3.3: "A line may be withdrawn, which marks its status as REMOVED; removed
    lines are excluded from all pricing."

    Design: Difficulty/boundary_precision_check/empty_included_lines_blocks_price
    """
    fx.create_regulation(state_code="ID", front_side_min_vlt_pct=35,
                         windshield_strip_max_inches=5, medical_exemption_allowed=False)
    shop = fx.create_shop(state_code="ID")
    pkg = fx.create_package(**fx.TINT_PACKAGE)
    mat = fx.create_material("CER-B2", **fx.TINT_MATERIAL)
    veh = fx.create_vehicle(customer_user_id="cust-12", vin="VIN-B2")
    quote, v0 = fx.create_quote(veh["id"], shop["id"])
    line = fx.add_line(quote["id"], v0, pkg["id"], mat["id"], coverage="FULL",
                       window_position="REAR_SIDE", requested_vlt_pct=50)
    fx.get_success_data(api.remove_quote_line(line["id"], SM))
    # Removing a line bumps the *quote's* version (PRD §3.3); re-read it for OCC.
    q_after_remove = validate_success(api.get_quote(quote["id"], SM))

    resp = api.price_quote(quote["id"], {"expected_quote_version": q_after_remove["version"]})
    validate_error(resp, ApiErrorId.ERR_NO_INCLUDED_LINES.value)
    # Quote stays DRAFT.
    after = validate_success(api.get_quote(quote["id"], SM))
    assert after["status"] == "DRAFT", f"quote must remain DRAFT, got {after['status']}"


def test_price_with_no_lines_at_all_rejected(api):
    """PRD §3.3: "pricing a quote with no included lines is rejected with
    ERR_NO_INCLUDED_LINES (HTTP 422)."

    Design: Difficulty/boundary_precision_check/empty_included_lines_blocks_price
    """
    fx.create_regulation(state_code="ID", front_side_min_vlt_pct=35,
                         windshield_strip_max_inches=5, medical_exemption_allowed=False)
    shop = fx.create_shop(state_code="ID")
    veh = fx.create_vehicle(customer_user_id="cust-12b", vin="VIN-B2b")
    quote, v0 = fx.create_quote(veh["id"], shop["id"])

    resp = api.price_quote(quote["id"], {"expected_quote_version": v0})
    validate_error(resp, ApiErrorId.ERR_NO_INCLUDED_LINES.value)


# ---------------------------------------------------------------------------
# Corner/validations/tint_below_legal_floor_no_exemption
# ---------------------------------------------------------------------------
def test_tint_below_floor_no_exemption_rejected(api):
    """PRD §3.4: "A front-side line below its effective floor is rejected with
    ERR_TINT_BELOW_LEGAL_VLT (HTTP 422)."

    Design: Corner/validations/tint_below_legal_floor_no_exemption
    """
    fx.create_regulation(state_code="CA", front_side_min_vlt_pct=35,
                         windshield_strip_max_inches=5, medical_exemption_allowed=True)
    shop = fx.create_shop(state_code="CA")
    pkg = fx.create_package(**fx.TINT_PACKAGE)
    mat = fx.create_material("M-BLF", **fx.TINT_MATERIAL)
    veh = fx.create_vehicle(customer_user_id="c-blf", vin="VIN-BLF")
    quote, v0 = fx.create_quote(veh["id"], shop["id"])
    line = fx.add_line(quote["id"], v0, pkg["id"], mat["id"], coverage="FULL",
                       window_position="FRONT_SIDE", requested_vlt_pct=34)

    resp = api.price_quote(quote["id"], {"expected_quote_version": line["version"]})
    validate_error(resp, ApiErrorId.ERR_TINT_BELOW_LEGAL_VLT.value)


# ---------------------------------------------------------------------------
# Corner/validations/windshield_strip_exceeds_limit
# ---------------------------------------------------------------------------
def test_windshield_strip_exceeds_limit_rejected(api):
    """PRD §3.4: "A windshield line exceeding the allowed depth is rejected with
    ERR_WINDSHIELD_STRIP_EXCEEDS_LIMIT (HTTP 422)."
    PRD §3.4: "For a line whose window_position is WINDSHIELD, the
    strip_depth_inches must be at most the regulation's windshield_strip_max_inches."

    Design: Corner/validations/windshield_strip_exceeds_limit
    """
    fx.create_regulation(state_code="CA", front_side_min_vlt_pct=35,
                         windshield_strip_max_inches=5, medical_exemption_allowed=True)
    shop = fx.create_shop(state_code="CA")
    pkg = fx.create_package(**fx.TINT_PACKAGE)
    mat = fx.create_material("M-WS", category="TINT_FILM", cure_hours=24,
                             price_multiplier_bps=10000)
    veh = fx.create_vehicle(customer_user_id="c-ws", vin="VIN-WS")
    quote, v0 = fx.create_quote(veh["id"], shop["id"])
    line = fx.add_line(quote["id"], v0, pkg["id"], mat["id"], coverage="ACCENT",
                       window_position="WINDSHIELD", requested_vlt_pct=70,
                       strip_depth_inches=6.0)

    resp = api.price_quote(quote["id"], {"expected_quote_version": line["version"]})
    validate_error(resp, ApiErrorId.ERR_WINDSHIELD_STRIP_EXCEEDS_LIMIT.value)


# ---------------------------------------------------------------------------
# Corner/validations/exemption_not_allowed_in_state
# ---------------------------------------------------------------------------
def test_exemption_not_allowed_in_state_rejected(api):
    """PRD §3.4: "If a front-side line sits below the statutory floor and an
    approved exemption does cover the vehicle, but the shop's state has
    medical_exemption_allowed set to false, the exemption cannot be honoured in
    that state and pricing is rejected with ERR_EXEMPTION_NOT_ALLOWED (HTTP 422)."

    Design: Corner/validations/exemption_not_allowed_in_state
    """
    fx.create_regulation(state_code="KY", front_side_min_vlt_pct=35,
                         windshield_strip_max_inches=5, medical_exemption_allowed=False)
    shop = fx.create_shop(state_code="KY")
    pkg = fx.create_package(**fx.TINT_PACKAGE)
    mat = fx.create_material("M-EX", category="TINT_FILM", cure_hours=24,
                             price_multiplier_bps=10000)
    veh = fx.create_vehicle(customer_user_id="c-ex", vin="VIN-EX")
    ex = fx.get_success_data(api.create_medical_exemption(
        {"vehicle_profile_id": veh["id"], "certificate_ref": "CERT-1", "exempt_min_vlt_pct": 20},
        make_customer_headers("c-ex")))
    fx.get_success_data(api.approve_medical_exemption(ex["id"], CO))
    quote, v0 = fx.create_quote(veh["id"], shop["id"])
    line = fx.add_line(quote["id"], v0, pkg["id"], mat["id"], coverage="FULL",
                       window_position="FRONT_SIDE", requested_vlt_pct=25)

    resp = api.price_quote(quote["id"], {"expected_quote_version": line["version"]})
    validate_error(resp, ApiErrorId.ERR_EXEMPTION_NOT_ALLOWED.value)


# ---------------------------------------------------------------------------
# Corner/validations/approved_exemption_lowers_floor_passes
# ---------------------------------------------------------------------------
def test_approved_exemption_lowers_floor_prices_ok(api):
    """PRD §3.4: "The effective floor is the regulation's front_side_min_vlt_pct,
    lowered to an approved exemption's exempt_min_vlt_pct only when the state's
    medical_exemption_allowed is true and an approved exemption covers the vehicle."

    Design: Corner/validations/approved_exemption_lowers_floor_passes
    """
    fx.create_regulation(state_code="CA", front_side_min_vlt_pct=35,
                         windshield_strip_max_inches=5, medical_exemption_allowed=True)
    shop = fx.create_shop(state_code="CA")
    pkg = fx.create_package(**fx.TINT_PACKAGE)
    mat = fx.create_material("M-EX2", **fx.TINT_MATERIAL)
    veh = fx.create_vehicle(customer_user_id="c-ex2", vin="VIN-EX2")
    ex = fx.get_success_data(api.create_medical_exemption(
        {"vehicle_profile_id": veh["id"], "certificate_ref": "CERT-2", "exempt_min_vlt_pct": 20},
        make_customer_headers("c-ex2")))
    fx.get_success_data(api.approve_medical_exemption(ex["id"], CO))
    quote, v0 = fx.create_quote(veh["id"], shop["id"])
    line = fx.add_line(quote["id"], v0, pkg["id"], mat["id"], coverage="FULL",
                       window_position="FRONT_SIDE", requested_vlt_pct=22)

    data = validate_success(api.price_quote(quote["id"], {"expected_quote_version": line["version"]}))
    assert data["status"] == "PRICED", f"exemption floor 20, 22>=20 -> PRICED, got {data['status']}"
    assert data["subtotal_cents"] == 40600, f"subtotal {data['subtotal_cents']}"


# ---------------------------------------------------------------------------
# Corner/validations/material_incompatible_on_line_add
# ---------------------------------------------------------------------------
def test_material_incompatible_on_line_add_rejected(api):
    """PRD §3.3: "the system checks that the chosen material's category is
    compatible with the package's service_type under the one-to-one mapping TINT
    with TINT_FILM, PPF with PPF_FILM, WRAP with WRAP_VINYL, and CERAMIC with
    CERAMIC_COATING; an incompatible pairing is rejected with
    ERR_MATERIAL_INCOMPATIBLE (HTTP 422)."

    Design: Corner/validations/material_incompatible_on_line_add
    """
    fx.create_regulation(state_code="FL", front_side_min_vlt_pct=28,
                         windshield_strip_max_inches=6, medical_exemption_allowed=False)
    shop = fx.create_shop(state_code="FL")
    pkg_tint = fx.create_package(**fx.TINT_PACKAGE)
    mat_ppf = fx.create_material("M-MISMATCH", category="PPF_FILM", cure_hours=48,
                                 price_multiplier_bps=10000)
    veh = fx.create_vehicle(customer_user_id="c-mis", vin="VIN-MIS")
    quote, v0 = fx.create_quote(veh["id"], shop["id"])

    resp = api.add_quote_line(quote["id"], {
        "service_package_id": pkg_tint["id"], "film_material_id": mat_ppf["id"],
        "coverage": "FULL", "window_position": "REAR_SIDE", "requested_vlt_pct": 50,
        "expected_quote_version": v0}, SM)
    validate_error(resp, ApiErrorId.ERR_MATERIAL_INCOMPATIBLE.value)


# ---------------------------------------------------------------------------
# Corner/validations/vlt_out_of_range_rejected
# ---------------------------------------------------------------------------
def test_vlt_out_of_range_on_line_add_rejected(api):
    """PRD §3.3: "requested_vlt_pct, the requested Visible Light Transmission
    percentage for the film (defaulting to 100, and required to fall between 0 and
    100 inclusive - a value outside that range is rejected with
    ERR_VLT_OUT_OF_RANGE)".

    Design: Corner/validations/vlt_out_of_range_rejected
    """
    fx.create_regulation(state_code="MN", front_side_min_vlt_pct=50,
                         windshield_strip_max_inches=5, medical_exemption_allowed=False)
    shop = fx.create_shop(state_code="MN")
    pkg = fx.create_package(**fx.TINT_PACKAGE)
    mat = fx.create_material("M-RNG", category="TINT_FILM", cure_hours=24,
                             price_multiplier_bps=10000)
    veh = fx.create_vehicle(customer_user_id="c-rng", vin="VIN-RNG")
    quote, v0 = fx.create_quote(veh["id"], shop["id"])

    resp = api.add_quote_line(quote["id"], {
        "service_package_id": pkg["id"], "film_material_id": mat["id"],
        "coverage": "FULL", "window_position": "FRONT_SIDE", "requested_vlt_pct": 150,
        "expected_quote_version": v0}, SM)
    validate_error(resp, ApiErrorId.ERR_VLT_OUT_OF_RANGE.value)
