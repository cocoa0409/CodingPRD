"""Validation corner cases: bad window, visit-kind mismatch, invalid QT tank,
overpayment, and payment on a non-payable invoice; plus the stale-version OCC
rejection on visit booking.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    make_field_tech_headers,
    make_customer_owner_headers,
    setup_active_system_with_tech,
    create_completed_visit,
    TEST_USERS,
)
from test_helpers.fixtures import create_contract, create_system, create_technician
from test_helpers import factories as f

AM = TEST_USERS["account_manager_headers"]
DISP = TEST_USERS["dispatcher_headers"]


def test_visit_window_start_after_end_rejected(api):
    """PRD §3.3: "the proposed window must be well-ordered: scheduled_start must be
    strictly before scheduled_end, and a window that is not is rejected with
    ERR_BAD_WINDOW."

    Design: Corner/validations/bad_visit_window_start_after_end_rejected
    """
    base = setup_active_system_with_tech(service_tier="BASIC", tech_user_id="tech-1",
                                         nominal_volume_l=200)
    resp = api.create_visit(
        f.create_visit_payload(base["system"]["id"], base["technician"]["id"],
                               base["system"]["version"],
                               scheduled_start="2026-03-01T11:00:00Z",
                               scheduled_end="2026-03-01T10:00:00Z"),
        DISP)
    validate_error(resp, ApiErrorId.ERR_BAD_WINDOW)


def test_routine_visit_with_emergency_call_id_rejected(api):
    """PRD §3.3: "an EMERGENCY visit requires emergency_call_id to be present and a
    ROUTINE visit must omit it; a violation is rejected with
    ERR_VISIT_KIND_MISMATCH."

    Design: Corner/validations/routine_visit_with_emergency_call_id_rejected
    """
    base = setup_active_system_with_tech(service_tier="BASIC", tech_user_id="tech-1",
                                         nominal_volume_l=200)
    emergency = validate_success(api.create_emergency(
        f.create_emergency_payload(base["system"]["id"], severity="LOW",
                                   trip_fee_cents=1000, reported_at="2026-03-01T08:00:00Z"),
        DISP), expected_status=201)
    resp = api.create_visit(
        f.create_visit_payload(base["system"]["id"], base["technician"]["id"],
                               base["system"]["version"],
                               scheduled_start="2026-03-01T09:00:00Z",
                               scheduled_end="2026-03-01T10:00:00Z",
                               visit_kind="ROUTINE", emergency_call_id=emergency["id"]),
        DISP)
    validate_error(resp, ApiErrorId.ERR_VISIT_KIND_MISMATCH)


def test_quarantine_in_non_freshwater_tank_rejected(api):
    """PRD §3.6: "The quarantine tank must be a SystemProfile whose system_kind is
    FRESHWATER; a tank of any other kind is rejected with ERR_INVALID_QT_TANK."

    Design: Corner/validations/quarantine_in_saltwater_tank_rejected
    """
    create_technician(tech_user_id="tech-1")
    contract = create_contract(customer_user_id="owner-1")
    home = create_system(contract["id"], system_kind="FRESHWATER",
                         nominal_volume_l=300, label="Home")
    reef = create_system(contract["id"], system_kind="REEF",
                        nominal_volume_l=300, label="Reef")
    validate_success(api.activate_contract(contract["id"], AM))
    validate_success(api.commission_system(home["id"], AM))
    reef = validate_success(api.commission_system(reef["id"], AM))
    tech_headers = make_field_tech_headers("tech-1")

    fish = validate_success(api.create_livestock(
        f.create_livestock_payload(home["id"], common_name="F",
                                   species_class="COMMUNITY", adult_length_cm=4),
        tech_headers), expected_status=201)
    resp = api.create_quarantine(
        f.create_quarantine_payload(fish["id"], reef["id"], reef["version"],
                                    window_start="2026-03-01T00:00:00Z",
                                    window_end="2026-03-03T00:00:00Z"),
        tech_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_QT_TANK)


def test_overpayment_on_invoice_rejected(api):
    """PRD §3.10: "The payment amount_cents must be strictly greater than zero and
    must not drive amount_paid_cents above total_cents; a non-positive payment or
    one that would overpay is rejected with ERR_OVERPAYMENT."

    BASIC visit at 30 min -> invoice total 6000; paying 7000 overpays.

    Design: Corner/validations/overpayment_on_invoice_rejected
    """
    base = create_completed_visit(service_tier="BASIC", customer_user_id="owner-1",
                                  tech_user_id="tech-1", labor_minutes=30,
                                  scheduled_start="2026-03-02T09:00:00Z",
                                  scheduled_end="2026-03-02T10:00:00Z")
    resp = api.pay_invoice(base["visit"]["invoice_id"], {"amount_cents": 7000}, AM)
    validate_error(resp, ApiErrorId.ERR_OVERPAYMENT)


def test_payment_on_void_invoice_rejected(api):
    """PRD §3.10: "A payment is only accepted on an invoice that is ISSUED or
    OVERDUE; a payment on a PAID or VOID invoice is rejected with
    ERR_INVOICE_NOT_PAYABLE."

    Disputing a completed visit voids its invoice; a subsequent payment is
    rejected.

    Design: Corner/validations/payment_on_void_invoice_rejected
    """
    base = create_completed_visit(service_tier="BASIC", customer_user_id="owner-1",
                                  tech_user_id="tech-1", labor_minutes=30,
                                  scheduled_start="2026-03-03T09:00:00Z",
                                  scheduled_end="2026-03-03T10:00:00Z")
    invoice_id = base["visit"]["invoice_id"]
    owner_headers = make_customer_owner_headers("owner-1")
    validate_success(api.dispute_visit(base["visit"]["id"], owner_headers))

    resp = api.pay_invoice(invoice_id, {"amount_cents": 1000}, AM)
    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_PAYABLE)


def test_stale_version_on_visit_booking_rejected(api):
    """PRD §2.7: "A request to book a visit must carry expected_system_version,
    the client's last observed version of the target SystemProfile named by
    system_id. If that value does not equal the system's current version ... the
    create is rejected with ERR_STALE_VERSION and HTTP status 412".

    A first booking advances the system version; a second booking reusing the old
    version (non-overlapping window) is rejected as stale.

    Design: Corner/errors/error_stale_version_on_visit_create
    """
    base = setup_active_system_with_tech(service_tier="BASIC", tech_user_id="tech-1",
                                         nominal_volume_l=200)
    system_id = base["system"]["id"]
    tech_id = base["technician"]["id"]
    stale_v = base["system"]["version"]

    validate_success(api.create_visit(
        f.create_visit_payload(system_id, tech_id, stale_v,
                               scheduled_start="2026-03-05T09:00:00Z",
                               scheduled_end="2026-03-05T10:00:00Z"),
        DISP), expected_status=201)
    resp = api.create_visit(
        f.create_visit_payload(system_id, tech_id, stale_v,
                               scheduled_start="2026-03-05T11:00:00Z",
                               scheduled_end="2026-03-05T12:00:00Z"),
        DISP)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
