"""Compensating cascades and conserved-quantity invariants: cancellation
releasing bay minutes + fleet credit then re-holding on reschedule, and a redo
callback re-reserving bay capacity.
"""
from test_helpers import (
    validate_success, make_installer_headers, make_customer_headers,
)
from test_helpers import fixtures as fx

SM = fx.SM


def _schedule(api, quote_id, bay_id, installer_id, scheduled_start, expected_quote_version):
    return api.create_work_order({
        "quote_id": quote_id, "bay_id": bay_id, "installer_id": installer_id,
        "scheduled_start": scheduled_start, "expected_quote_version": expected_quote_version}, SM)


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/cancel_workorder_releases_then_reschedule_reholds
# ---------------------------------------------------------------------------
def test_cancel_releases_bay_and_credit_then_reverts_quote(api):
    """PRD §3.8: "The order's duration_minutes plus cure_buffer_minutes is
    subtracted back from the bay's reserved_minutes. If the order is on a fleet
    account, the order's total_due_cents is subtracted from that account's
    held_credit_cents, releasing the held credit. The source quote is set back from
    CONVERTED to ACCEPTED so it can be scheduled afresh, and its version is
    incremented."

    Design: Difficulty/transitive_cascade/cancel_workorder_releases_then_reschedule_reholds
    """
    fx.create_regulation(state_code="CO", front_side_min_vlt_pct=27,
                         windshield_strip_max_inches=4, medical_exemption_allowed=False)
    shop = fx.create_shop(state_code="CO")
    fleet = fx.create_fleet(fleet_manager_user_id="fm-7", discount_bps=0,
                            credit_limit_cents=5000000, company_name="CascadeCo")
    pkg = fx.create_package(**fx.PPF_PACKAGE)  # dur 180, cure_buffer 30 -> 210
    mat = fx.create_material("PPF-CO", **fx.PPF_MATERIAL)
    veh = fx.create_vehicle(customer_user_id="cust-7", vin="VIN-CASC")
    bay = fx.create_bay(shop["id"], label="Bay B")
    inst = fx.create_installer(shop["id"], installer_user_id="inst-7",
                               certified_service_types=("PPF",))
    acc = fx.build_accepted_quote(shop["id"], veh["id"], "cust-7", pkg["id"], mat["id"],
                                  fleet_account_id=fleet["id"], coverage="PARTIAL",
                                  window_position="BODY_PANEL", requested_vlt_pct=None)
    wo = validate_success(_schedule(api, acc["id"], bay["id"], inst["id"],
                                    "2026-06-02T09:00:00Z", acc["version"]), 201)

    validate_success(api.cancel_work_order(
        wo["id"], {"expected_work_order_version": wo["version"]}, SM))

    bay_after = validate_success(api.get_bay(bay["id"], SM))
    assert bay_after["reserved_minutes"] == 0, (
        f"bay minutes released to 0, got {bay_after['reserved_minutes']}")
    fleet_after = validate_success(api.get_fleet_account(fleet["id"], SM))
    assert fleet_after["held_credit_cents"] == 0, (
        f"held credit released to 0, got {fleet_after['held_credit_cents']}")
    quote_after = validate_success(api.get_quote(acc["id"], SM))
    assert quote_after["status"] == "ACCEPTED", (
        f"quote reverts to ACCEPTED, got {quote_after['status']}")


def test_reschedule_after_cancel_reholds_bay_and_credit(api):
    """PRD §3.6: "adds the order's duration_minutes plus cure_buffer_minutes to the
    chosen bay's reserved_minutes, and - if the order is on a fleet account - adds
    the order's total_due_cents to that account's held_credit_cents."
    PRD §3.8: "The source quote is set back from CONVERTED to ACCEPTED so it can be
    scheduled afresh, and its version is incremented."

    Design: Difficulty/transitive_cascade/cancel_workorder_releases_then_reschedule_reholds
    """
    fx.create_regulation(state_code="CO", front_side_min_vlt_pct=27,
                         windshield_strip_max_inches=4, medical_exemption_allowed=False)
    shop = fx.create_shop(state_code="CO")
    fleet = fx.create_fleet(fleet_manager_user_id="fm-7", discount_bps=0,
                            credit_limit_cents=5000000, company_name="CascadeCo")
    pkg = fx.create_package(**fx.PPF_PACKAGE)
    mat = fx.create_material("PPF-CO2", **fx.PPF_MATERIAL)
    veh = fx.create_vehicle(customer_user_id="cust-7", vin="VIN-CASC2")
    bay = fx.create_bay(shop["id"], label="Bay B")
    inst = fx.create_installer(shop["id"], installer_user_id="inst-7",
                               certified_service_types=("PPF",))
    acc = fx.build_accepted_quote(shop["id"], veh["id"], "cust-7", pkg["id"], mat["id"],
                                  fleet_account_id=fleet["id"], coverage="PARTIAL",
                                  window_position="BODY_PANEL", requested_vlt_pct=None)
    wo = validate_success(_schedule(api, acc["id"], bay["id"], inst["id"],
                                    "2026-06-02T09:00:00Z", acc["version"]), 201)
    validate_success(api.cancel_work_order(
        wo["id"], {"expected_work_order_version": wo["version"]}, SM))
    quote_after = validate_success(api.get_quote(acc["id"], SM))

    # Re-schedule from the freshly-reverted quote (its version advanced).
    validate_success(_schedule(api, acc["id"], bay["id"], inst["id"],
                               "2026-06-03T09:00:00Z", quote_after["version"]), 201)

    bay_after = validate_success(api.get_bay(bay["id"], SM))
    assert bay_after["reserved_minutes"] == 210, (
        f"bay minutes re-held to 210, got {bay_after['reserved_minutes']}")
    fleet_after = validate_success(api.get_fleet_account(fleet["id"], SM))
    assert fleet_after["held_credit_cents"] == 54000, (
        f"held credit re-held to 54000, got {fleet_after['held_credit_cents']}")


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/redo_callback_reholds_bay_minutes
# ---------------------------------------------------------------------------
def test_redo_callback_rereserves_bay_minutes(api):
    """PRD §3.11: "A REDO outcome requires that the referenced work order be
    COMPLETED and triggers a free rework: the order's duration_minutes plus
    cure_buffer_minutes is added back onto that order's bay's reserved_minutes,
    re-reserving the same bay capacity for the redo".

    Design: Difficulty/transitive_cascade/redo_callback_reholds_bay_minutes
    """
    sc = fx.setup_scheduled_tint_workorder(state_code="GA", customer_user_id="cust-8",
                                           installer_user_id="inst-8", vin="VIN-REDO",
                                           front_side_min_vlt_pct=32)
    wo = sc["work_order"]
    fx.drive_to_released(sc, start_clock="2026-06-02T09:00:00Z",
                         release_clock="2026-06-04T00:00:00Z")
    # Bay released -> reserved_minutes 0 for this tint order (dur 120, cure_buffer 0).
    cb = fx.get_success_data(api.create_callback(
        {"work_order_id": wo["id"], "reason": "BUBBLING"}, make_customer_headers("cust-8")))

    resolved = validate_success(api.resolve_callback(cb["id"], {"outcome": "REDO"}, SM))
    assert resolved["outcome"] == "REDO", f"outcome {resolved['outcome']}"
    assert resolved["status"] == "RESOLVED", f"status {resolved['status']}"
    bay_after = validate_success(api.get_bay(sc["bay"]["id"], SM))
    assert bay_after["reserved_minutes"] == 120, (
        f"redo re-reserves duration+cure_buffer=120, got {bay_after['reserved_minutes']}")


def test_redo_callback_sets_resolved_outcome(api):
    """PRD §3.11: "A ShopManager resolves an open ticket by supplying an outcome of
    either REDO or DENIED, which moves the ticket from OPEN to RESOLVED and
    increments its version."

    Design: Difficulty/transitive_cascade/redo_callback_reholds_bay_minutes
    """
    sc = fx.setup_scheduled_tint_workorder(state_code="GA", customer_user_id="cust-8b",
                                           installer_user_id="inst-8b", vin="VIN-REDO2",
                                           front_side_min_vlt_pct=32)
    wo = sc["work_order"]
    fx.drive_to_released(sc, start_clock="2026-06-02T09:00:00Z",
                         release_clock="2026-06-04T00:00:00Z")
    cb = fx.get_success_data(api.create_callback(
        {"work_order_id": wo["id"], "reason": "PEELING"}, make_customer_headers("cust-8b")))

    resolved = validate_success(api.resolve_callback(cb["id"], {"outcome": "REDO"}, SM))
    assert resolved["outcome"] == "REDO", f"outcome {resolved['outcome']}"
    assert resolved["status"] == "RESOLVED", f"status {resolved['status']}"


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/bay_minutes_conserved_on_schedule_cancel
# ---------------------------------------------------------------------------
def test_bay_minutes_conserved_across_schedule_cancel(api):
    """PRD §3.6: "adds the order's duration_minutes plus cure_buffer_minutes to the
    chosen bay's reserved_minutes".
    PRD §3.8: "The order's duration_minutes plus cure_buffer_minutes is subtracted
    back from the bay's reserved_minutes."

    Design: Difficulty/compensating_invariant/bay_minutes_conserved_on_schedule_cancel
    """
    fx.create_regulation(state_code="PA", front_side_min_vlt_pct=70,
                         windshield_strip_max_inches=3, medical_exemption_allowed=False)
    shop = fx.create_shop(state_code="PA")
    pkg = fx.create_package(**fx.PPF_PACKAGE)  # dur 180 + cure_buffer 30 = 210
    mat = fx.create_material("PPF-PA", **fx.PPF_MATERIAL)
    veh = fx.create_vehicle(customer_user_id="cust-17", vin="VIN-INVA")
    bay = fx.create_bay(shop["id"])
    inst = fx.create_installer(shop["id"], installer_user_id="inst-17",
                               certified_service_types=("PPF",))
    acc = fx.build_accepted_quote(shop["id"], veh["id"], "cust-17", pkg["id"], mat["id"],
                                  coverage="PARTIAL", window_position="BODY_PANEL",
                                  requested_vlt_pct=None)
    wo = validate_success(_schedule(api, acc["id"], bay["id"], inst["id"],
                                    "2026-06-02T09:00:00Z", acc["version"]), 201)

    bay_scheduled = validate_success(api.get_bay(bay["id"], SM))
    assert bay_scheduled["reserved_minutes"] == 210, (
        f"reserved 210 after schedule, got {bay_scheduled['reserved_minutes']}")

    validate_success(api.cancel_work_order(
        wo["id"], {"expected_work_order_version": wo["version"]}, SM))
    bay_cancelled = validate_success(api.get_bay(bay["id"], SM))
    assert bay_cancelled["reserved_minutes"] == 0, (
        f"reserved back to 0 after cancel, got {bay_cancelled['reserved_minutes']}")


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/fleet_credit_conserved_on_schedule_cancel
# ---------------------------------------------------------------------------
def test_fleet_credit_conserved_across_schedule_cancel(api):
    """PRD §3.6: "if the order is on a fleet account - adds the order's
    total_due_cents to that account's held_credit_cents."
    PRD §3.8: "If the order is on a fleet account, the order's total_due_cents is
    subtracted from that account's held_credit_cents, releasing the held credit."

    Design: Difficulty/compensating_invariant/fleet_credit_conserved_on_schedule_cancel
    """
    fx.create_regulation(state_code="NC", front_side_min_vlt_pct=35,
                         windshield_strip_max_inches=5, medical_exemption_allowed=False)
    shop = fx.create_shop(state_code="NC")
    fleet = fx.create_fleet(fleet_manager_user_id="fm-17", discount_bps=0,
                            credit_limit_cents=5000000, company_name="ConserveCo")
    pkg = fx.create_package(**fx.PPF_PACKAGE)
    mat = fx.create_material("PPF-NC", **fx.PPF_MATERIAL)
    veh = fx.create_vehicle(customer_user_id="cust-18", vin="VIN-INVB")
    bay = fx.create_bay(shop["id"])
    inst = fx.create_installer(shop["id"], installer_user_id="inst-18",
                               certified_service_types=("PPF",))
    acc = fx.build_accepted_quote(shop["id"], veh["id"], "cust-18", pkg["id"], mat["id"],
                                  fleet_account_id=fleet["id"], coverage="PARTIAL",
                                  window_position="BODY_PANEL", requested_vlt_pct=None)
    wo = validate_success(_schedule(api, acc["id"], bay["id"], inst["id"],
                                    "2026-06-02T09:00:00Z", acc["version"]), 201)

    fleet_scheduled = validate_success(api.get_fleet_account(fleet["id"], SM))
    assert fleet_scheduled["held_credit_cents"] == 54000, (
        f"held 54000 after schedule, got {fleet_scheduled['held_credit_cents']}")

    validate_success(api.cancel_work_order(
        wo["id"], {"expected_work_order_version": wo["version"]}, SM))
    fleet_cancelled = validate_success(api.get_fleet_account(fleet["id"], SM))
    assert fleet_cancelled["held_credit_cents"] == 0, (
        f"held back to 0 after cancel, got {fleet_cancelled['held_credit_cents']}")
