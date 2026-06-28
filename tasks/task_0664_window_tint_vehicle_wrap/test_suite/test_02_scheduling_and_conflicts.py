"""Work-order scheduling preconditions: bay/installer temporal overlap,
quote-state gate, installer certification, and fleet credit limit.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, make_customer_headers,
)
from test_helpers import fixtures as fx

SM = fx.SM


def _schedule(api, quote_id, bay_id, installer_id, scheduled_start, expected_quote_version):
    return api.create_work_order({
        "quote_id": quote_id, "bay_id": bay_id, "installer_id": installer_id,
        "scheduled_start": scheduled_start, "expected_quote_version": expected_quote_version}, SM)


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/bay_overlap_with_cure_backbuffer
# ---------------------------------------------------------------------------
def test_bay_overlap_within_cure_backbuffer_rejected(api):
    """PRD §3.6: "The work order's bay occupancy runs over the half-open interval
    from scheduled_start to scheduled_start plus the order's duration_minutes plus
    its cure_buffer_minutes; adjacency is allowed, but if this interval overlaps
    any existing active work order on the same bay the request is rejected with
    ERR_BAY_TIME_CONFLICT (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/bay_overlap_with_cure_backbuffer
    """
    fx.create_regulation(state_code="OH", front_side_min_vlt_pct=50,
                         windshield_strip_max_inches=5, medical_exemption_allowed=False)
    shop = fx.create_shop(state_code="OH")
    pkg = fx.create_package(**fx.PPF_PACKAGE)
    mat = fx.create_material("PPF-OH", **fx.PPF_MATERIAL)
    veh1 = fx.create_vehicle(customer_user_id="cust-15", vin="VIN-T1A")
    veh2 = fx.create_vehicle(customer_user_id="cust-15", vin="VIN-T1B")
    bay = fx.create_bay(shop["id"])
    inst1 = fx.create_installer(shop["id"], installer_user_id="inst-15a", full_name="Otto",
                                certified_service_types=("PPF",))
    inst2 = fx.create_installer(shop["id"], installer_user_id="inst-15b", full_name="Ola",
                                certified_service_types=("PPF",))
    acc1 = fx.build_accepted_quote(shop["id"], veh1["id"], "cust-15", pkg["id"], mat["id"],
                                   coverage="PARTIAL", window_position="BODY_PANEL",
                                   requested_vlt_pct=None)
    fx.get_success_data(_schedule(api, acc1["id"], bay["id"], inst1["id"],
                                  "2026-06-02T09:00:00Z", acc1["version"]))
    acc2 = fx.build_accepted_quote(shop["id"], veh2["id"], "cust-15", pkg["id"], mat["id"],
                                   coverage="PARTIAL", window_position="BODY_PANEL",
                                   requested_vlt_pct=None)

    # First job occupies [09:00, 12:30); 12:00 falls inside the cure tail.
    resp = _schedule(api, acc2["id"], bay["id"], inst2["id"],
                     "2026-06-02T12:00:00Z", acc2["version"])
    validate_error(resp, ApiErrorId.ERR_BAY_TIME_CONFLICT.value)


def test_bay_adjacent_booking_at_backbuffer_end_allowed(api):
    """PRD §3.6: "The work order's bay occupancy runs over the half-open interval
    from scheduled_start to scheduled_start plus the order's duration_minutes plus
    its cure_buffer_minutes; adjacency is allowed, but if this interval overlaps
    any existing active work order on the same bay the request is rejected with
    ERR_BAY_TIME_CONFLICT (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/bay_overlap_with_cure_backbuffer
    """
    fx.create_regulation(state_code="OH", front_side_min_vlt_pct=50,
                         windshield_strip_max_inches=5, medical_exemption_allowed=False)
    shop = fx.create_shop(state_code="OH")
    pkg = fx.create_package(**fx.PPF_PACKAGE)
    mat = fx.create_material("PPF-OH2", **fx.PPF_MATERIAL)
    veh1 = fx.create_vehicle(customer_user_id="cust-15", vin="VIN-T1C")
    veh2 = fx.create_vehicle(customer_user_id="cust-15", vin="VIN-T1D")
    bay = fx.create_bay(shop["id"])
    inst1 = fx.create_installer(shop["id"], installer_user_id="inst-15c", full_name="Otto",
                                certified_service_types=("PPF",))
    inst2 = fx.create_installer(shop["id"], installer_user_id="inst-15d", full_name="Ola",
                                certified_service_types=("PPF",))
    acc1 = fx.build_accepted_quote(shop["id"], veh1["id"], "cust-15", pkg["id"], mat["id"],
                                   coverage="PARTIAL", window_position="BODY_PANEL",
                                   requested_vlt_pct=None)
    fx.get_success_data(_schedule(api, acc1["id"], bay["id"], inst1["id"],
                                  "2026-06-02T09:00:00Z", acc1["version"]))
    acc2 = fx.build_accepted_quote(shop["id"], veh2["id"], "cust-15", pkg["id"], mat["id"],
                                   coverage="PARTIAL", window_position="BODY_PANEL",
                                   requested_vlt_pct=None)

    # 12:30 is exactly the half-open end of the first job's interval -> adjacency allowed.
    data = validate_success(_schedule(api, acc2["id"], bay["id"], inst2["id"],
                                      "2026-06-02T12:30:00Z", acc2["version"]), 201)
    assert data["install_status"] == "SCHEDULED", f"status {data['install_status']}"


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/installer_overlap_with_rest_frontbuffer
# ---------------------------------------------------------------------------
def test_installer_overlap_within_rest_frontbuffer_rejected(api):
    """PRD §3.6: "The installer is protected by a front rest buffer: the installer
    occupancy runs over the half-open interval from 45 minutes before
    scheduled_start up to scheduled_start plus the order's duration_minutes; if
    this interval overlaps any existing active work order for the same installer
    the request is rejected with ERR_INSTALLER_TIME_CONFLICT (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/installer_overlap_with_rest_frontbuffer
    """
    fx.create_regulation(state_code="MI", front_side_min_vlt_pct=35,
                         windshield_strip_max_inches=4, medical_exemption_allowed=False)
    shop = fx.create_shop(state_code="MI")
    pkg = fx.create_package(**fx.TINT_PACKAGE)
    mat = fx.create_material("CER-MI", **fx.TINT_MATERIAL)
    veh1 = fx.create_vehicle(customer_user_id="cust-16", vin="VIN-T2A")
    veh2 = fx.create_vehicle(customer_user_id="cust-16", vin="VIN-T2B")
    bay1 = fx.create_bay(shop["id"], label="Bay 1")
    bay2 = fx.create_bay(shop["id"], label="Bay 2")
    inst = fx.create_installer(shop["id"], installer_user_id="inst-16", full_name="Mac",
                               certified_service_types=("TINT",))
    acc1 = fx.build_accepted_quote(shop["id"], veh1["id"], "cust-16", pkg["id"], mat["id"],
                                   coverage="FULL", window_position="REAR_SIDE", requested_vlt_pct=50)
    fx.get_success_data(_schedule(api, acc1["id"], bay1["id"], inst["id"],
                                  "2026-06-02T09:00:00Z", acc1["version"]))
    acc2 = fx.build_accepted_quote(shop["id"], veh2["id"], "cust-16", pkg["id"], mat["id"],
                                   coverage="FULL", window_position="REAR_SIDE", requested_vlt_pct=50)

    # First job occupies installer [09:00,11:00). Second at 11:30 has front buffer
    # reaching back to 10:45, overlapping.
    resp = _schedule(api, acc2["id"], bay2["id"], inst["id"],
                     "2026-06-02T11:30:00Z", acc2["version"])
    validate_error(resp, ApiErrorId.ERR_INSTALLER_TIME_CONFLICT.value)


def test_installer_adjacent_booking_with_frontbuffer_allowed(api):
    """PRD §3.6: "The installer is protected by a front rest buffer: the installer
    occupancy runs over the half-open interval from 45 minutes before
    scheduled_start up to scheduled_start plus the order's duration_minutes; if
    this interval overlaps any existing active work order for the same installer
    the request is rejected with ERR_INSTALLER_TIME_CONFLICT (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/installer_overlap_with_rest_frontbuffer
    """
    fx.create_regulation(state_code="MI", front_side_min_vlt_pct=35,
                         windshield_strip_max_inches=4, medical_exemption_allowed=False)
    shop = fx.create_shop(state_code="MI")
    pkg = fx.create_package(**fx.TINT_PACKAGE)
    mat = fx.create_material("CER-MI2", **fx.TINT_MATERIAL)
    veh1 = fx.create_vehicle(customer_user_id="cust-16", vin="VIN-T2C")
    veh2 = fx.create_vehicle(customer_user_id="cust-16", vin="VIN-T2D")
    bay1 = fx.create_bay(shop["id"], label="Bay 1")
    bay2 = fx.create_bay(shop["id"], label="Bay 2")
    inst = fx.create_installer(shop["id"], installer_user_id="inst-16b", full_name="Mac",
                               certified_service_types=("TINT",))
    acc1 = fx.build_accepted_quote(shop["id"], veh1["id"], "cust-16", pkg["id"], mat["id"],
                                   coverage="FULL", window_position="REAR_SIDE", requested_vlt_pct=50)
    fx.get_success_data(_schedule(api, acc1["id"], bay1["id"], inst["id"],
                                  "2026-06-02T09:00:00Z", acc1["version"]))
    acc2 = fx.build_accepted_quote(shop["id"], veh2["id"], "cust-16", pkg["id"], mat["id"],
                                   coverage="FULL", window_position="REAR_SIDE", requested_vlt_pct=50)

    # 11:45 second job: front buffer reaches 11:00, exactly adjacent (half-open) -> allowed.
    data = validate_success(_schedule(api, acc2["id"], bay2["id"], inst["id"],
                                      "2026-06-02T11:45:00Z", acc2["version"]), 201)
    assert data["install_status"] == "SCHEDULED", f"status {data['install_status']}"


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/schedule_requires_quote_accepted
# ---------------------------------------------------------------------------
def test_schedule_from_priced_quote_rejected(api):
    """PRD §3.6: "The source quote must be ACCEPTED; a quote in any other state is
    rejected with ERR_QUOTE_NOT_ACCEPTED (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/schedule_requires_quote_accepted
    """
    fx.create_regulation(state_code="NM", front_side_min_vlt_pct=20,
                         windshield_strip_max_inches=5, medical_exemption_allowed=False)
    shop = fx.create_shop(state_code="NM")
    pkg = fx.create_package(**fx.TINT_PACKAGE)
    mat = fx.create_material("CER-CE2", **fx.TINT_MATERIAL)
    veh = fx.create_vehicle(customer_user_id="cust-14", vin="VIN-CE2")
    bay = fx.create_bay(shop["id"])
    inst = fx.create_installer(shop["id"], installer_user_id="inst-14",
                               certified_service_types=("TINT",))
    quote, v0 = fx.create_quote(veh["id"], shop["id"])
    line = fx.add_line(quote["id"], v0, pkg["id"], mat["id"], coverage="FULL",
                       window_position="REAR_SIDE", requested_vlt_pct=50)
    _, v2 = fx.price_quote(quote["id"], line["version"])

    resp = _schedule(api, quote["id"], bay["id"], inst["id"], "2026-06-02T09:00:00Z", v2)
    validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_ACCEPTED.value)
    after = validate_success(api.get_quote(quote["id"], SM))
    assert after["status"] == "PRICED", f"quote must remain PRICED, got {after['status']}"


def test_schedule_from_accepted_quote_succeeds(api):
    """PRD §3.6: "When all gates pass, a 201 work order is created."
    PRD §3.6: "Its install_status begins at SCHEDULED and its payment_status at
    DEPOSIT_DUE".

    Design: Difficulty/cross_entity_state_dependency/schedule_requires_quote_accepted
    """
    fx.create_regulation(state_code="NM", front_side_min_vlt_pct=20,
                         windshield_strip_max_inches=5, medical_exemption_allowed=False)
    shop = fx.create_shop(state_code="NM")
    pkg = fx.create_package(**fx.TINT_PACKAGE)
    mat = fx.create_material("CER-CE2b", **fx.TINT_MATERIAL)
    veh = fx.create_vehicle(customer_user_id="cust-14b", vin="VIN-CE2b")
    bay = fx.create_bay(shop["id"])
    inst = fx.create_installer(shop["id"], installer_user_id="inst-14b",
                               certified_service_types=("TINT",))
    acc = fx.build_accepted_quote(shop["id"], veh["id"], "cust-14b", pkg["id"], mat["id"])

    data = validate_success(_schedule(api, acc["id"], bay["id"], inst["id"],
                                      "2026-06-02T09:00:00Z", acc["version"]), 201)
    assert data["install_status"] == "SCHEDULED", f"install_status {data['install_status']}"
    assert data["payment_status"] == "DEPOSIT_DUE", f"payment_status {data['payment_status']}"


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/certification_beats_fleet_credit_on_schedule
# ---------------------------------------------------------------------------
def test_certification_failure_reported_before_fleet_credit(api):
    """PRD §3.6: "The assigned installer's certified_service_types must include
    that primary_service_type, or the request is rejected with
    ERR_INSTALLER_NOT_CERTIFIED (HTTP 422)."
    PRD §2.11: "Where two business rules can both apply to the same endpoint, the
    workflow in §3 names which is evaluated first."

    Design: Difficulty/priority_pair_validation_conflict/certification_beats_fleet_credit_on_schedule
    """
    fx.create_regulation(state_code="FL", front_side_min_vlt_pct=28,
                         windshield_strip_max_inches=6, medical_exemption_allowed=False)
    shop = fx.create_shop(state_code="FL")
    fleet = fx.create_fleet(fleet_manager_user_id="fm-9", discount_bps=0,
                            credit_limit_cents=1000, company_name="TightCo")
    pkg_tint = fx.create_package(**fx.TINT_PACKAGE)
    mat_tint = fx.create_material("CER-FL", **fx.TINT_MATERIAL)
    veh = fx.create_vehicle(customer_user_id="cust-10", vin="VIN-FL1")
    bay = fx.create_bay(shop["id"])
    # Installer certified only for WRAP, not the order's primary_service_type TINT.
    inst = fx.create_installer(shop["id"], installer_user_id="inst-10", full_name="Flo",
                               certified_service_types=("WRAP",))
    acc = fx.build_accepted_quote(shop["id"], veh["id"], "cust-10", pkg_tint["id"],
                                  mat_tint["id"], fleet_account_id=fleet["id"],
                                  coverage="FULL", window_position="REAR_SIDE", requested_vlt_pct=50)

    resp = _schedule(api, acc["id"], bay["id"], inst["id"], "2026-06-02T09:00:00Z", acc["version"])
    validate_error(resp, ApiErrorId.ERR_INSTALLER_NOT_CERTIFIED.value)


def test_uncertified_installer_rejected_simple(api):
    """PRD §3.6: "The assigned installer's certified_service_types must include
    that primary_service_type, or the request is rejected with
    ERR_INSTALLER_NOT_CERTIFIED (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/certification_beats_fleet_credit_on_schedule
    """
    fx.create_regulation(state_code="FL", front_side_min_vlt_pct=28,
                         windshield_strip_max_inches=6, medical_exemption_allowed=False)
    shop = fx.create_shop(state_code="FL")
    pkg_tint = fx.create_package(**fx.TINT_PACKAGE)
    mat_tint = fx.create_material("CER-FL2", **fx.TINT_MATERIAL)
    veh = fx.create_vehicle(customer_user_id="cust-10b", vin="VIN-FL2")
    bay = fx.create_bay(shop["id"])
    # Retail order (no fleet); only certification can fail.
    inst = fx.create_installer(shop["id"], installer_user_id="inst-10b", full_name="Flo",
                               certified_service_types=("WRAP",))
    acc = fx.build_accepted_quote(shop["id"], veh["id"], "cust-10b", pkg_tint["id"],
                                  mat_tint["id"], coverage="FULL",
                                  window_position="REAR_SIDE", requested_vlt_pct=50)

    resp = _schedule(api, acc["id"], bay["id"], inst["id"], "2026-06-02T09:00:00Z", acc["version"])
    validate_error(resp, ApiErrorId.ERR_INSTALLER_NOT_CERTIFIED.value)


# ---------------------------------------------------------------------------
# Corner/validations/fleet_credit_exceeded_at_schedule
# ---------------------------------------------------------------------------
def test_fleet_credit_exceeded_at_schedule_rejected(api):
    """PRD §3.6: "scheduling must not push the account's provisional held credit
    above its limit. The provisional available credit (the credit_limit_cents
    minus the current held_credit_cents) must be at least the order's
    total_due_cents at schedule time, or the request is rejected with
    ERR_FLEET_CREDIT_EXCEEDED (HTTP 409)."

    Design: Corner/validations/fleet_credit_exceeded_at_schedule
    """
    fx.create_regulation(state_code="MO", front_side_min_vlt_pct=35,
                         windshield_strip_max_inches=5, medical_exemption_allowed=False)
    shop = fx.create_shop(state_code="MO")
    fleet = fx.create_fleet(fleet_manager_user_id="fm-cap", discount_bps=0,
                            credit_limit_cents=100000, company_name="CapCo")
    pkg_tint = fx.create_package(**fx.TINT_PACKAGE)
    pkg_wrap = fx.create_package(name="BigWrap", service_type="WRAP", base_rate_cents=100000,
                                 duration_minutes=240, cure_buffer_minutes=60,
                                 warranty_days=730, requires_proof=False)
    mat_tint = fx.create_material("CER-MO", **fx.TINT_MATERIAL)
    mat_wrap = fx.create_material("VINYL-MO", category="WRAP_VINYL", cure_hours=12,
                                  price_multiplier_bps=10000)
    veh1 = fx.create_vehicle(customer_user_id="c-cap", vin="VIN-CAP1")
    veh2 = fx.create_vehicle(customer_user_id="c-cap", vin="VIN-CAP2")
    bay1 = fx.create_bay(shop["id"], label="B1")
    bay2 = fx.create_bay(shop["id"], label="B2")
    inst1 = fx.create_installer(shop["id"], installer_user_id="i-cap1",
                                certified_service_types=("TINT",))
    inst2 = fx.create_installer(shop["id"], installer_user_id="i-cap2",
                                certified_service_types=("WRAP",))
    acc1 = fx.build_accepted_quote(shop["id"], veh1["id"], "c-cap", pkg_tint["id"],
                                   mat_tint["id"], fleet_account_id=fleet["id"],
                                   coverage="FULL", window_position="REAR_SIDE", requested_vlt_pct=50)
    fx.get_success_data(_schedule(api, acc1["id"], bay1["id"], inst1["id"],
                                  "2026-06-02T09:00:00Z", acc1["version"]))
    acc2 = fx.build_accepted_quote(shop["id"], veh2["id"], "c-cap", pkg_wrap["id"],
                                   mat_wrap["id"], fleet_account_id=fleet["id"],
                                   coverage="FULL", window_position="BODY_PANEL",
                                   requested_vlt_pct=None)

    # held 40600 + 100000 > limit 100000.
    resp = _schedule(api, acc2["id"], bay2["id"], inst2["id"],
                     "2026-06-02T09:00:00Z", acc2["version"])
    validate_error(resp, ApiErrorId.ERR_FLEET_CREDIT_EXCEEDED.value)
