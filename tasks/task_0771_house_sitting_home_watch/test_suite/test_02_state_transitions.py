"""Invalid transitions, terminal-state lockdown, and state-guarded action errors."""
from test_helpers import validate_error, ApiErrorId, make_coordinator_headers
from test_helpers import factories as f
from test_helpers import fixtures as fx

COORD = make_coordinator_headers()


def test_submit_already_pending_booking_rejected(api):
    """PRD 3.3: "Submitting a booking that is not in DRAFT is rejected with ERR_BOOKING_NOT_DRAFT."

    Design: Corner/state_machines/resubmit_booking_from_pending_rejected
    """
    client = fx.create_client(api)
    prop = fx.create_property(api, client["id"])
    booking = fx.create_booking(api, prop["id"])
    fx.submit_booking(api, booking["id"])
    resp = api.submit_booking(booking["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_DRAFT.value, expected_status=409)
    assert fx.get_booking(api, booking["id"])["status"] == "PENDING_ASSIGNMENT"


def test_cancel_already_cancelled_booking_rejected(api):
    """PRD 3.9: "cancelling an already-terminal booking is rejected with ERR_BOOKING_NOT_CANCELLABLE."

    Design: Corner/state_machines/cancel_cancelled_booking_rejected
    """
    client = fx.create_client(api)
    prop = fx.create_property(api, client["id"])
    booking = fx.create_booking(api, prop["id"])
    api.cancel_booking(booking["id"], COORD)
    resp = api.cancel_booking(booking["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_CANCELLABLE.value, expected_status=409)
    assert fx.get_booking(api, booking["id"])["status"] == "CANCELLED"


def test_decide_already_cleared_background_check_rejected(api):
    """PRD 3.2: "Adjudicating a check that is not in SUBMITTED is rejected with ERR_BGCHECK_NOT_PENDING."

    Design: Corner/state_machines/background_check_decide_twice_rejected
    """
    sitter = fx.create_sitter(api)
    bg = fx.submit_background_check(api, sitter["id"])
    fx.clear_background_check(api, bg["id"])
    resp = api.decide_background_check(bg["id"], f.decide_payload("REJECTED"), COORD)
    validate_error(resp, ApiErrorId.ERR_BGCHECK_NOT_PENDING.value, expected_status=409)
    assert fx.get_success_data(api.get_background_check(bg["id"], COORD))["status"] == "CLEARED"


def test_mark_missed_before_window_close_rejected(api):
    """PRD 3.8: "marking a visit missed while its window is still open (clock before scheduled_end)
    is rejected with ERR_VISIT_WINDOW_OPEN."

    Design: Corner/state_machines/mark_missed_before_window_returns_409
    """
    ctx = fx.setup_scheduled_booking(api)  # clock at 2026-05-01, before the 06-01 window
    visit = ctx["visits"][0]
    resp = api.mark_missed_visit(visit["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_VISIT_WINDOW_OPEN.value, expected_status=409)
    assert fx.get_visit(api, visit["id"])["status"] == "SCHEDULED"


def test_report_lost_on_at_office_key_rejected(api):
    """PRD 3.5: "Both returning and reporting-lost require the assignment to be CHECKED_OUT;
    otherwise the request is rejected with ERR_KEY_NOT_CHECKED_OUT."

    Design: Corner/errors/report_lost_at_office_key_returns_409
    """
    client = fx.create_client(api)
    prop = fx.create_property(api, client["id"])
    sitter = fx.create_sitter(api)
    booking = fx.create_booking(api, prop["id"])
    key = fx.get_success_data(api.create_key_assignment(
        f.create_key_assignment_payload(prop["id"], sitter["id"], booking["id"]), COORD))
    resp = api.report_lost_key(key["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_KEY_NOT_CHECKED_OUT.value, expected_status=409)
    assert fx.get_key_assignment(api, key["id"])["status"] == "AT_OFFICE"


def test_checkout_key_with_no_copies_available_rejected(api):
    """PRD 3.5: "a checkout is refused with ERR_NO_KEY_COPIES_AVAILABLE when the property has
    zero copies available (available_key_copies less than one)."

    Design: Corner/errors/key_checkout_no_copies_available_returns_409
    """
    client = fx.create_client(api)
    prop = fx.create_property(api, client["id"], key_copies_total=1)
    sitter = fx.create_sitter(api)
    booking = fx.create_booking(api, prop["id"])
    key1 = fx.get_success_data(api.create_key_assignment(
        f.create_key_assignment_payload(prop["id"], sitter["id"], booking["id"]), COORD))
    key2 = fx.get_success_data(api.create_key_assignment(
        f.create_key_assignment_payload(prop["id"], sitter["id"], booking["id"]), COORD))
    fx.get_success_data(api.check_out_key(key1["id"], COORD))
    resp = api.check_out_key(key2["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_NO_KEY_COPIES_AVAILABLE.value, expected_status=409)
    assert fx.get_property(api, prop["id"])["available_key_copies"] == 0


def test_pay_draft_invoice_rejected(api):
    """PRD 3.9: "Payment requires the invoice to be in ISSUED (otherwise ERR_INVOICE_NOT_ISSUED)
    and the owning booking to be COMPLETED (otherwise ERR_BOOKING_NOT_COMPLETED)."

    Design: Corner/errors/pay_draft_invoice_not_issued_returns_409
    """
    ctx = fx.setup_scheduled_booking(api)  # invoice created in DRAFT, booking not activated
    invoice = ctx["invoice"]
    resp = api.pay_invoice(invoice["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_ISSUED.value, expected_status=409)
    assert fx.invoice_for_booking(api, ctx["booking"]["id"])["status"] == "DRAFT"
