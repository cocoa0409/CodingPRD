"""Numeric / temporal boundary precision: the advance tier breakpoint, the
appointment check-in window boundary, and the preparer-vs-client overlap
adjacency rules.
"""
from test_helpers import (
    validate_success, validate_error,
    create_client, create_return, create_refund_advance,
    setup_office_with_preparer, api_client, TEST_USERS,
)

OM = TEST_USERS["office_manager_headers"]
FD = TEST_USERS["front_desk_headers"]
BO = TEST_USERS["bank_officer_headers"]


# ─── Queue A: boundary_precision_check / advance_tier_boundary_99999_vs_100000

def _bank_office_low_client():
    office = validate_success(api_client.create_office(
        {"name": "Bound Office", "efin": "101010", "state_code": "NV",
         "bank_product_enabled": True}, OM), 201)
    client = create_client(office["id"], full_name="Bd Bob", ssn_last4="1616", risk_band="LOW")
    return office, client


def test_advance_tier_below_breakpoint_ineligible(api):
    """PRD §3.8: "a refund below 100000 cents yields a cap of 0 (no advance
    under one thousand dollars)"

    Design: Difficulty/boundary_precision_check/advance_tier_boundary_99999_vs_100000
    """
    office, client = _bank_office_low_client()
    ret = create_return(office["id"], client["id"], tax_year=2025, expected_refund_cents=99999)
    adv = create_refund_advance(ret["id"], 50000)
    res = api.underwrite_refund_advance(adv["id"], {"decision": "APPROVE"}, BO)
    validate_error(res, "ERR_ADVANCE_INELIGIBLE", expected_status=409)
    after = validate_success(api.get_refund_advance(adv["id"], BO), 200)
    assert after["status"] == "REQUESTED", "ineligible advance must stay REQUESTED"


def test_advance_tier_at_breakpoint_approves(api):
    """PRD §3.8: "a refund from 100000 cents up to but not including 300000
    cents yields a cap of 50000 cents ... The tier boundaries are inclusive at
    the lower edge, so a refund of exactly 300000 cents lands in the 150000-cent
    cap tier."

    Design: Difficulty/boundary_precision_check/advance_tier_boundary_99999_vs_100000
    """
    office, client = _bank_office_low_client()
    ret = create_return(office["id"], client["id"], tax_year=2024,
                        return_kind="PRIOR_YEAR", expected_refund_cents=100000)
    adv = create_refund_advance(ret["id"], 50000)
    approved = validate_success(api.underwrite_refund_advance(
        adv["id"], {"decision": "APPROVE"}, BO), 200)
    # tier(100000)=50000; round(100000*0.75)=75000; min=50000; min(50000,50000)=50000.
    assert approved["approved_cents"] == 50000, f"expected 50000, got {approved['approved_cents']}"
    assert approved["status"] == "APPROVED"


# ─── Queue A: boundary_precision_check / appointment_checkin_at_exact_start_boundary

def test_appointment_checkin_before_start_rejected_then_at_start_succeeds(api):
    """PRD §3.2: "From SCHEDULED it may move to CHECKED_IN, but only once the
    logical clock has reached or passed the appointment's start_utc — checking
    in before the window opens is rejected with ERR_APPOINTMENT_WINDOW_NOT_OPEN."

    Design: Difficulty/boundary_precision_check/appointment_checkin_at_exact_start_boundary
    """
    office, _, prep, _ = setup_office_with_preparer()
    client = create_client(office["id"], full_name="Ap Cli", ssn_last4="1717")
    appt = validate_success(api.create_appointment(
        office["id"],
        {"client_id": client["id"], "preparer_id": prep["id"],
         "start_utc": "2026-06-10T09:00:00Z", "end_utc": "2026-06-10T10:00:00Z"}, FD), 201)

    validate_success(api.set_clock({"to_iso8601": "2026-06-10T08:59:59Z"}, OM), 200)
    res = api.transition_appointment(appt["id"], {"to": "CHECKED_IN"}, FD)
    validate_error(res, "ERR_APPOINTMENT_WINDOW_NOT_OPEN", expected_status=409)

    validate_success(api.set_clock({"to_iso8601": "2026-06-10T09:00:00Z"}, OM), 200)
    ok = validate_success(api.transition_appointment(appt["id"], {"to": "CHECKED_IN"}, FD), 200)
    assert ok["status"] == "CHECKED_IN", "check-in at exactly start_utc must succeed (>= boundary)"


# ─── Queue A: resource_temporal_overlap / preparer_double_book_half_open_adjacency_allowed

def test_preparer_adjacent_booking_allowed_overlap_rejected(api):
    """PRD §3.2: "For the named preparer, the new appointment's half-open
    interval — start inclusive, end exclusive — must not overlap any existing
    non-terminal appointment for that preparer; adjacency, where one
    appointment's end equals the next appointment's start, is allowed. A
    preparer overlap is rejected with ERR_PREPARER_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/preparer_double_book_half_open_adjacency_allowed
    """
    office, _, prep, _ = setup_office_with_preparer()
    client_a = create_client(office["id"], full_name="Cl One", ssn_last4="2020")
    client_b = create_client(office["id"], full_name="Cl Two", ssn_last4="2121")
    client_c = create_client(office["id"], full_name="Cl Three", ssn_last4="2323")
    validate_success(api.create_appointment(
        office["id"],
        {"client_id": client_a["id"], "preparer_id": prep["id"],
         "start_utc": "2026-06-11T09:00:00Z", "end_utc": "2026-06-11T10:00:00Z"}, FD), 201)

    # Adjacent (end == next start) is allowed for the preparer.
    adjacent = validate_success(api.create_appointment(
        office["id"],
        {"client_id": client_b["id"], "preparer_id": prep["id"],
         "start_utc": "2026-06-11T10:00:00Z", "end_utc": "2026-06-11T11:00:00Z"}, FD), 201)
    assert adjacent["status"] == "SCHEDULED"

    # Interior overlap is rejected.
    res = api.create_appointment(
        office["id"],
        {"client_id": client_c["id"], "preparer_id": prep["id"],
         "start_utc": "2026-06-11T09:30:00Z", "end_utc": "2026-06-11T10:30:00Z"}, FD)
    validate_error(res, "ERR_PREPARER_DOUBLE_BOOKED", expected_status=409)


# ─── Queue A: resource_temporal_overlap / client_double_book_closed_adjacency_rejected

def test_client_adjacent_booking_rejected(api):
    """PRD §3.2: "For the named client, the interval is treated as closed on
    both ends, so a shared boundary collides: if the new appointment's start
    equals an existing appointment's end (or otherwise overlaps), it is rejected
    with ERR_CLIENT_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/client_double_book_closed_adjacency_rejected
    """
    office, _, prep_a, _ = setup_office_with_preparer(
        credential_overrides={"ptin": "P20202020"})
    cred_b = validate_success(api.create_credential(
        {"office_id": office["id"], "ptin": "P30303030", "holder_name": "Pb Ben",
         "expires_on": "2027-01-01T00:00:00Z"}, OM), 201)
    prep_b = validate_success(api.create_preparer(
        office["id"], {"credential_id": cred_b["id"], "full_name": "Pb Ben"}, OM), 201)
    client = create_client(office["id"], full_name="Cl Solo", ssn_last4="2424")

    validate_success(api.create_appointment(
        office["id"],
        {"client_id": client["id"], "preparer_id": prep_a["id"],
         "start_utc": "2026-06-12T09:00:00Z", "end_utc": "2026-06-12T10:00:00Z"}, FD), 201)

    # Same client, different preparer, adjacent (start == prior end) → collides.
    res = api.create_appointment(
        office["id"],
        {"client_id": client["id"], "preparer_id": prep_b["id"],
         "start_utc": "2026-06-12T10:00:00Z", "end_utc": "2026-06-12T11:00:00Z"}, FD)
    validate_error(res, "ERR_CLIENT_DOUBLE_BOOKED", expected_status=409)
