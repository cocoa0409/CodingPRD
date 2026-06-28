"""Install execution lifecycle: estimated-vs-actual cure projection, warranty,
proof gate on start, the parallel install/payment dimensions, and the
clock-gated transition guards.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_installer_headers, make_customer_headers,
)
from test_helpers import fixtures as fx

SM = fx.SM


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/cure_complete_estimated_vs_actual_on_workorder
# ---------------------------------------------------------------------------
def test_actual_cure_supersedes_estimate_at_completion(api):
    """PRD §3.7: "The curing deadline cure_complete_at is recomputed in its actual
    form: the cure hours added to actual_completed_at, where the cure hours are
    the maximum cure_hours over the materials on the source quote's INCLUDED lines."
    PRD §3.7: "This actual figure supersedes the estimate that was set at
    scheduling - that estimate had anchored the same maximum cure hours onto the
    scheduled_start plus the order's duration_minutes."

    Design: Difficulty/dual_variant_calc/cure_complete_estimated_vs_actual_on_workorder
    """
    fx.create_regulation(state_code="CA", front_side_min_vlt_pct=35,
                         windshield_strip_max_inches=5, medical_exemption_allowed=True)
    shop = fx.create_shop(state_code="CA")
    pkg = fx.create_package(**fx.TINT_PACKAGE)  # dur 120, cure_buffer 0, warranty 365
    mat = fx.create_material("CER-TINT", **fx.TINT_MATERIAL)  # cure_hours 24
    veh = fx.create_vehicle(customer_user_id="cust-1", vin="VIN-DV-CURE")
    bay = fx.create_bay(shop["id"])
    inst = fx.create_installer(shop["id"], installer_user_id="inst-1",
                               certified_service_types=("TINT",))
    acc = fx.build_accepted_quote(shop["id"], veh["id"], "cust-1", pkg["id"], mat["id"],
                                  coverage="FULL", window_position="FRONT_SIDE", requested_vlt_pct=40)
    wo = validate_success(api.create_work_order({
        "quote_id": acc["id"], "bay_id": bay["id"], "installer_id": inst["id"],
        "scheduled_start": "2026-06-02T09:00:00Z",
        "expected_quote_version": acc["version"]}, SM), 201)
    # ESTIMATED = scheduled_start 09:00 + dur 120m -> 11:00 + 24h cure -> 2026-06-03T11:00.
    assert wo["cure_complete_at"] == "2026-06-03T11:00:00.000Z", (
        f"estimated cure {wo['cure_complete_at']}")

    fx.set_clock("2026-06-02T09:00:00Z")
    fx.get_success_data(api.start_work_order(wo["id"], make_installer_headers("inst-1")))
    fx.set_clock("2026-06-02T10:45:00Z")
    completed = validate_success(api.complete_install_work_order(
        wo["id"], make_installer_headers("inst-1")))

    # ACTUAL = actual_completed_at 10:45 + 24h cure -> 2026-06-03T10:45.
    assert completed["cure_complete_at"] == "2026-06-03T10:45:00.000Z", (
        f"actual cure {completed['cure_complete_at']}")
    assert completed["cure_complete_at"] != wo["cure_complete_at"], (
        "actual must differ from estimate")
    assert completed["warranty_expires_at"] == "2027-06-02T10:45:00.000Z", (
        f"warranty {completed['warranty_expires_at']}")


def test_warranty_expires_at_set_at_completion(api):
    """PRD §3.7: "The warranty deadline warranty_expires_at is actual_completed_at
    plus the warranty length in days, where that length is the maximum warranty_days
    over the source quote's INCLUDED lines' packages - the maximum across packages,
    never the sum."

    Design: Difficulty/dual_variant_calc/cure_complete_estimated_vs_actual_on_workorder
    """
    fx.create_regulation(state_code="CA", front_side_min_vlt_pct=35,
                         windshield_strip_max_inches=5, medical_exemption_allowed=True)
    shop = fx.create_shop(state_code="CA")
    pkg = fx.create_package(**fx.TINT_PACKAGE)  # warranty 365
    mat = fx.create_material("CER-TINT-W", **fx.TINT_MATERIAL)
    veh = fx.create_vehicle(customer_user_id="cust-1w", vin="VIN-DV-W")
    bay = fx.create_bay(shop["id"])
    inst = fx.create_installer(shop["id"], installer_user_id="inst-1w",
                               certified_service_types=("TINT",))
    acc = fx.build_accepted_quote(shop["id"], veh["id"], "cust-1w", pkg["id"], mat["id"],
                                  coverage="FULL", window_position="FRONT_SIDE", requested_vlt_pct=40)
    wo = validate_success(api.create_work_order({
        "quote_id": acc["id"], "bay_id": bay["id"], "installer_id": inst["id"],
        "scheduled_start": "2026-06-02T09:00:00Z",
        "expected_quote_version": acc["version"]}, SM), 201)
    fx.set_clock("2026-06-02T09:00:00Z")
    fx.get_success_data(api.start_work_order(wo["id"], make_installer_headers("inst-1w")))
    fx.set_clock("2026-06-02T10:45:00Z")
    completed = validate_success(api.complete_install_work_order(
        wo["id"], make_installer_headers("inst-1w")))
    # actual_completed_at 2026-06-02T10:45 + 365d -> 2027-06-02T10:45.
    assert completed["warranty_expires_at"] == "2027-06-02T10:45:00.000Z", (
        f"warranty {completed['warranty_expires_at']}")


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/workorder_parallel_install_and_payment
# ---------------------------------------------------------------------------
def test_pay_deposit_advances_payment_not_install(api):
    """PRD §3.9: "Payment status evolves on the same work order row but
    independently of install status."
    PRD §3.9: "a successful payment advances the order from DEPOSIT_DUE to
    DEPOSIT_PAID and increments its version."

    Design: Difficulty/non_linear_state_machine/workorder_parallel_install_and_payment
    """
    sc = fx.setup_scheduled_tint_workorder(state_code="WA", customer_user_id="cust-6",
                                           installer_user_id="inst-6", vin="VIN-PAR",
                                           front_side_min_vlt_pct=24)
    wo = sc["work_order"]
    paid = validate_success(api.pay_deposit_work_order(
        wo["id"], {"amount_cents": 10150}, make_customer_headers("cust-6")))
    assert paid["payment_status"] == "DEPOSIT_PAID", f"payment {paid['payment_status']}"
    assert paid["install_status"] == "SCHEDULED", (
        f"install must stay SCHEDULED after pay-deposit, got {paid['install_status']}")


def test_start_advances_install_not_payment(api):
    """PRD §3.9: "Payment status evolves on the same work order row but
    independently of install status."
    PRD §3.7: "The assigned Installer begins work, advancing the order from
    SCHEDULED to IN_PROGRESS."

    Design: Difficulty/non_linear_state_machine/workorder_parallel_install_and_payment
    """
    sc = fx.setup_scheduled_tint_workorder(state_code="WA", customer_user_id="cust-6b",
                                           installer_user_id="inst-6b", vin="VIN-PAR2",
                                           front_side_min_vlt_pct=24)
    wo = sc["work_order"]
    fx.get_success_data(api.pay_deposit_work_order(
        wo["id"], {"amount_cents": 10150}, make_customer_headers("cust-6b")))
    fx.set_clock("2026-06-02T09:00:00Z")
    started = validate_success(api.start_work_order(wo["id"], make_installer_headers("inst-6b")))
    assert started["install_status"] == "IN_PROGRESS", f"install {started['install_status']}"
    assert started["payment_status"] == "DEPOSIT_PAID", (
        f"payment must stay DEPOSIT_PAID after start, got {started['payment_status']}")


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/start_requires_approved_wrap_proof
# ---------------------------------------------------------------------------
def test_start_blocked_without_approved_proof(api):
    """PRD §3.7: "If the order's primary_service_type resolves to a package whose
    requires_proof is true, an APPROVED WrapProof must already exist for the order;
    otherwise the start is blocked with ERR_PROOF_NOT_APPROVED (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/start_requires_approved_wrap_proof
    """
    sc = fx.setup_scheduled_wrap_workorder_with_proof(state_code="UT",
                                                      customer_user_id="cust-13",
                                                      installer_user_id="inst-13")
    wo = sc["work_order"]  # proof exists but only PROOF_SUBMITTED.
    fx.set_clock("2026-06-02T09:00:00Z")
    resp = api.start_work_order(wo["id"], make_installer_headers("inst-13"))
    validate_error(resp, ApiErrorId.ERR_PROOF_NOT_APPROVED.value)
    after = validate_success(api.get_work_order(wo["id"], SM))
    assert after["install_status"] == "SCHEDULED", (
        f"install must remain SCHEDULED, got {after['install_status']}")


def test_start_succeeds_after_proof_approved(api):
    """PRD §3.7: "If the order's primary_service_type resolves to a package whose
    requires_proof is true, an APPROVED WrapProof must already exist for the order;
    otherwise the start is blocked with ERR_PROOF_NOT_APPROVED (HTTP 409)."
    PRD §3.10: "approve it (moving it from PROOF_SUBMITTED to the terminal APPROVED
    state)".

    Design: Difficulty/cross_entity_state_dependency/start_requires_approved_wrap_proof
    """
    sc = fx.setup_scheduled_wrap_workorder_with_proof(state_code="UT",
                                                      customer_user_id="cust-13b",
                                                      installer_user_id="inst-13b")
    wo = sc["work_order"]
    fx.get_success_data(api.approve_proof(sc["proof"]["id"], make_customer_headers("cust-13b")))
    fx.set_clock("2026-06-02T09:00:00Z")
    started = validate_success(api.start_work_order(wo["id"], make_installer_headers("inst-13b")))
    assert started["install_status"] == "IN_PROGRESS", f"install {started['install_status']}"


# ---------------------------------------------------------------------------
# Corner/consistency_model/schedule_response_reflects_estimated_cure_immediately
# ---------------------------------------------------------------------------
def test_schedule_response_carries_estimated_cure_immediately(api):
    """PRD §3.6: "The system sets the estimated cure_complete_at as described in
    §3.7".
    PRD §3.7: "that estimate had anchored the same maximum cure hours onto the
    scheduled_start plus the order's duration_minutes."

    Design: Corner/consistency_model/schedule_response_reflects_estimated_cure_immediately
    """
    fx.create_regulation(state_code="DE", front_side_min_vlt_pct=35,
                         windshield_strip_max_inches=5, medical_exemption_allowed=False)
    shop = fx.create_shop(state_code="DE")
    pkg = fx.create_package(**fx.TINT_PACKAGE)
    mat = fx.create_material("CER-DE", **fx.TINT_MATERIAL)
    veh = fx.create_vehicle(customer_user_id="c-imm", vin="VIN-IMM")
    bay = fx.create_bay(shop["id"])
    inst = fx.create_installer(shop["id"], installer_user_id="i-imm",
                               certified_service_types=("TINT",))
    acc = fx.build_accepted_quote(shop["id"], veh["id"], "c-imm", pkg["id"], mat["id"],
                                  coverage="FULL", window_position="REAR_SIDE", requested_vlt_pct=50)

    data = validate_success(api.create_work_order({
        "quote_id": acc["id"], "bay_id": bay["id"], "installer_id": inst["id"],
        "scheduled_start": "2026-06-02T09:00:00Z",
        "expected_quote_version": acc["version"]}, SM), 201)
    assert data["cure_complete_at"] == "2026-06-03T11:00:00.000Z", (
        f"estimated cure in same response {data['cure_complete_at']}")
    assert data["duration_minutes"] == 120, f"duration {data['duration_minutes']}"


# ---------------------------------------------------------------------------
# Corner/state_machines/start_before_scheduled_start_invalid_state
# ---------------------------------------------------------------------------
def test_start_before_scheduled_start_rejected(api):
    """PRD §3.7: "Starting requires that the order is SCHEDULED, that X-User-ID
    equal the assigned installer's installer_user_id, and that the logical clock
    has reached the scheduled_start."

    Design: Corner/state_machines/start_before_scheduled_start_invalid_state
    """
    sc = fx.setup_scheduled_tint_workorder(state_code="NM", customer_user_id="c-ear",
                                           installer_user_id="i-ear", vin="VIN-EAR",
                                           front_side_min_vlt_pct=20)
    wo = sc["work_order"]
    # Default clock 2026-04-01T00:00 < scheduled_start 2026-06-02T09:00.
    resp = api.start_work_order(wo["id"], make_installer_headers("i-ear"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Corner/state_machines/release_before_cure_complete_invalid_state
# ---------------------------------------------------------------------------
def test_release_before_cure_complete_rejected(api):
    """PRD §3.7: "A ShopManager releases a cured order, advancing it from CURING to
    the COMPLETED state, which is permitted only once the logical clock has reached
    the order's cure_complete_at."

    Design: Corner/state_machines/release_before_cure_complete_invalid_state
    """
    fx.create_regulation(state_code="TX", front_side_min_vlt_pct=25,
                         windshield_strip_max_inches=5, medical_exemption_allowed=False)
    shop = fx.create_shop(state_code="TX")
    pkg = fx.create_package(**fx.TINT_PACKAGE)
    mat = fx.create_material("M-CUR", category="TINT_FILM", cure_hours=24,
                             price_multiplier_bps=10000)
    veh = fx.create_vehicle(customer_user_id="c-cur", vin="VIN-CUR")
    bay = fx.create_bay(shop["id"])
    inst = fx.create_installer(shop["id"], installer_user_id="i-cur",
                               certified_service_types=("TINT",))
    acc = fx.build_accepted_quote(shop["id"], veh["id"], "c-cur", pkg["id"], mat["id"],
                                  coverage="FULL", window_position="REAR_SIDE", requested_vlt_pct=50)
    wo = validate_success(api.create_work_order({
        "quote_id": acc["id"], "bay_id": bay["id"], "installer_id": inst["id"],
        "scheduled_start": "2026-06-02T09:00:00Z",
        "expected_quote_version": acc["version"]}, SM), 201)
    fx.set_clock("2026-06-02T09:00:00Z")
    fx.get_success_data(api.start_work_order(wo["id"], make_installer_headers("i-cur")))
    fx.get_success_data(api.complete_install_work_order(wo["id"], make_installer_headers("i-cur")))
    # cure_complete_at (actual) = 09:00 + 24h = 2026-06-03T09:00; clock 10:00 same day < that.
    fx.set_clock("2026-06-02T10:00:00Z")

    resp = api.release_work_order(wo["id"], SM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_work_order(wo["id"], SM))
    assert after["install_status"] == "CURING", f"must remain CURING, got {after['install_status']}"


# ---------------------------------------------------------------------------
# Corner/state_machines/invoice_before_install_completed_invalid_state
# ---------------------------------------------------------------------------
def test_invoice_before_install_completed_rejected(api):
    """PRD §3.9: "A ShopManager invoices a deposit-paid order, advancing it from
    DEPOSIT_PAID to INVOICED. Invoicing is gated across the two dimensions: it
    requires that the order's install_status be COMPLETED."

    Design: Corner/state_machines/invoice_before_install_completed_invalid_state
    """
    sc = fx.setup_scheduled_tint_workorder(state_code="WA", customer_user_id="c-inv",
                                           installer_user_id="i-inv", vin="VIN-INV",
                                           front_side_min_vlt_pct=24)
    wo = sc["work_order"]
    fx.get_success_data(api.pay_deposit_work_order(
        wo["id"], {"amount_cents": 10150}, make_customer_headers("c-inv")))
    # install_status still SCHEDULED, payment DEPOSIT_PAID.
    resp = api.invoice_work_order(wo["id"], SM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Corner/endpoints/proof_not_required_rejected
# ---------------------------------------------------------------------------
def test_submit_proof_for_non_proof_package_rejected(api):
    """PRD §3.10: "Submitting a proof for an order whose primary_service_type
    resolves to a package that does not require a proof is rejected with
    ERR_PROOF_NOT_REQUIRED (HTTP 409)."

    Design: Corner/endpoints/proof_not_required_rejected
    """
    sc = fx.setup_scheduled_tint_workorder(state_code="AL", customer_user_id="c-pnr",
                                           installer_user_id="i-pnr", vin="VIN-PNR",
                                           front_side_min_vlt_pct=32)
    wo = sc["work_order"]
    resp = api.submit_proof(wo["id"], {"design_ref": "d-nope"}, make_installer_headers("i-pnr"))
    validate_error(resp, ApiErrorId.ERR_PROOF_NOT_REQUIRED.value)
