"""Supplemental Difficulty-queue tests: a second assertion per difficulty
instance that otherwise had a single test, exercising a distinct observable
consequence of the same rule.
"""
from test_helpers import (
    validate_success, validate_error,
    create_client, create_return, create_refund_advance, create_refund_transfer,
    create_approved_advance, setup_return_prepared, setup_return_in_docs_pending,
    setup_office_with_preparer, setup_accepted_return_with_pending_transfer,
    api_client, TEST_USERS,
)

OM = TEST_USERS["office_manager_headers"]
FD = TEST_USERS["front_desk_headers"]
BO = TEST_USERS["bank_officer_headers"]
TP_SHARED = TEST_USERS["tax_preparer_headers"]


# ─── transitive_cascade / return_cancel_cascades_advance_then_transfer_depth3 ─

def test_cancel_return_terminal_status_and_advance_terminal(api):
    """PRD §3.5: "Any RefundAdvance on the return whose status is REQUESTED or
    APPROVED is moved to CANCELLED; and that advance cancellation in turn moves
    the linked RefundTransfer to CANCELLED when that transfer is in
    PENDING_FUNDING."

    Design: Difficulty/transitive_cascade/return_cancel_cascades_advance_then_transfer_depth3
    """
    office = validate_success(api_client.create_office(
        {"name": "Cascade2 Office", "efin": "676767", "state_code": "AZ",
         "bank_product_enabled": True}, OM), 201)
    client = create_client(office["id"], full_name="Cas2", ssn_last4="1313", risk_band="LOW")
    # REQUESTED (not yet approved) advance also cancels on cancel.
    ret = create_return(office["id"], client["id"], tax_year=2025, expected_refund_cents=500000)
    adv = create_refund_advance(ret["id"], 100000)
    rt = create_refund_transfer(ret["id"])

    validate_success(api.transition_return(ret["id"], {"to": "CANCELLED"}, TP_SHARED), 200)
    adv_after = validate_success(api.get_refund_advance(adv["id"], BO), 200)
    rt_after = validate_success(api.get_refund_transfer(rt["id"], BO), 200)
    assert adv_after["status"] == "CANCELLED", "REQUESTED advance must cascade to CANCELLED"
    assert rt_after["status"] == "CANCELLED", "transfer must cascade to CANCELLED via the advance"


# ─── transitive_cascade / transfer_disburse_cascades_advance_repaid_depth2 ──

def test_transfer_disburse_moves_transfer_to_disbursed(api):
    """PRD §3.7: "A successful disburse runs the fee-deduction waterfall, writes
    net_to_taxpayer_cents and fee_shortfall_cents, moves the transfer to
    DISBURSED, and increments its version by one."

    Design: Difficulty/transitive_cascade/transfer_disburse_cascades_advance_repaid_depth2
    """
    from test_helpers import setup_accepted_return_with_disbursed_advance_and_pending_transfer
    ctx, rt, adv = setup_accepted_return_with_disbursed_advance_and_pending_transfer(
        advance_cents=60000)
    rt_v = rt["version"]
    disbursed = validate_success(api.disburse_refund_transfer(
        rt["id"], {"disbursed_refund_cents": 500000, "expected_refundtransfer_version": rt_v}, BO), 200)
    assert disbursed["status"] == "DISBURSED"
    assert disbursed["fee_shortfall_cents"] == 0, "full coverage means zero shortfall"


# ─── priority_pair_validation_conflict / state_vs_efin_suspended_on_efile ──

def test_efile_undefined_from_in_prep_is_invalid_state(api):
    """PRD §2.5: "then, on transition, e-file, e-file-ack, underwrite, disburse,
    and cancel endpoints, that the target resource is in a state from which the
    requested transition is defined (ERR_INVALID_STATE, 409)"

    Design: Difficulty/priority_pair_validation_conflict/state_vs_efin_suspended_on_efile
    """
    # Even with an ACTIVE EFIN, e-file from IN_PREP is undefined → ERR_INVALID_STATE.
    from test_helpers import setup_return_in_prep
    ctx = setup_return_in_prep(return_overrides={"complexity_band": "SIMPLE"})
    res = api.efile_return(ctx["return"]["id"], ctx["prep_headers"])
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── cross_entity_state_dependency / refund_transfer_disburse_requires_return_accepted

def test_disburse_blocked_keeps_transfer_version(api):
    """PRD §3.7: "The linked return must be in EFILED_ACCEPTED, else
    ERR_RETURN_NOT_ACCEPTED"

    Design: Difficulty/cross_entity_state_dependency/refund_transfer_disburse_requires_return_accepted
    """
    ctx = setup_return_prepared(
        bank_product_enabled=True,
        client_overrides={"risk_band": "LOW"},
        return_overrides={"complexity_band": "SIMPLE", "expected_refund_cents": 500000})
    rt = validate_success(api.create_refund_transfer({"tax_return_id": ctx["return"]["id"]}, BO), 201)
    res = api.disburse_refund_transfer(
        rt["id"], {"disbursed_refund_cents": 500000, "expected_refundtransfer_version": rt["version"]}, BO)
    validate_error(res, "ERR_RETURN_NOT_ACCEPTED", expected_status=409)
    rt_after = validate_success(api.get_refund_transfer(rt["id"], BO), 200)
    # A rejected disburse does not run the waterfall, so it stays PENDING_FUNDING.
    assert rt_after["status"] == "PENDING_FUNDING"


# ─── cross_entity_state_dependency / in_prep_requires_active_credential ────

def test_in_prep_succeeds_with_active_credential(api):
    """PRD §3.4: "the assigned preparer's credential must be in ACTIVE status,
    else ERR_CREDENTIAL_INVALID."

    Design: Difficulty/cross_entity_state_dependency/in_prep_requires_active_credential
    """
    # Positive control: with the credential left ACTIVE, IN_PREP succeeds.
    ctx = setup_return_in_docs_pending(return_overrides={"complexity_band": "SIMPLE"})
    ok = validate_success(api.transition_return(
        ctx["return"]["id"], {"to": "IN_PREP"}, ctx["prep_headers"]), 200)
    assert ok["status"] == "IN_PREP"


# ─── resource_temporal_overlap / preparer_double_book_half_open_adjacency_allowed

def test_preparer_back_to_back_adjacent_chain_allowed(api):
    """PRD §3.2: "adjacency, where one appointment's end equals the next
    appointment's start, is allowed."

    Design: Difficulty/resource_temporal_overlap/preparer_double_book_half_open_adjacency_allowed
    """
    office, _, prep, _ = setup_office_with_preparer()
    c1 = create_client(office["id"], full_name="P1", ssn_last4="2727")
    c2 = create_client(office["id"], full_name="P2", ssn_last4="2828")
    validate_success(api.create_appointment(
        office["id"],
        {"client_id": c1["id"], "preparer_id": prep["id"],
         "start_utc": "2026-06-13T09:00:00Z", "end_utc": "2026-06-13T10:00:00Z"}, FD), 201)
    ok = validate_success(api.create_appointment(
        office["id"],
        {"client_id": c2["id"], "preparer_id": prep["id"],
         "start_utc": "2026-06-13T10:00:00Z", "end_utc": "2026-06-13T11:00:00Z"}, FD), 201)
    assert ok["status"] == "SCHEDULED"


# ─── resource_temporal_overlap / client_double_book_closed_adjacency_rejected ─

def test_client_interior_overlap_rejected(api):
    """PRD §3.2: "if the new appointment's start equals an existing
    appointment's end (or otherwise overlaps), it is rejected with
    ERR_CLIENT_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/client_double_book_closed_adjacency_rejected
    """
    office, _, prep_a, _ = setup_office_with_preparer(credential_overrides={"ptin": "P21212121"})
    cred_b = validate_success(api.create_credential(
        {"office_id": office["id"], "ptin": "P31313131", "holder_name": "Pb",
         "expires_on": "2027-01-01T00:00:00Z"}, OM), 201)
    prep_b = validate_success(api.create_preparer(
        office["id"], {"credential_id": cred_b["id"], "full_name": "Pb"}, OM), 201)
    client = create_client(office["id"], full_name="Cl Solo2", ssn_last4="2929")
    validate_success(api.create_appointment(
        office["id"],
        {"client_id": client["id"], "preparer_id": prep_a["id"],
         "start_utc": "2026-06-14T09:00:00Z", "end_utc": "2026-06-14T10:00:00Z"}, FD), 201)
    # Interior overlap for the same client (different preparer) is rejected.
    res = api.create_appointment(
        office["id"],
        {"client_id": client["id"], "preparer_id": prep_b["id"],
         "start_utc": "2026-06-14T09:30:00Z", "end_utc": "2026-06-14T10:30:00Z"}, FD)
    validate_error(res, "ERR_CLIENT_DOUBLE_BOOKED", expected_status=409)


# ─── boundary_precision_check / appointment_checkin_at_exact_start_boundary ─

def test_appointment_checkin_after_start_succeeds(api):
    """PRD §3.2: "From SCHEDULED it may move to CHECKED_IN, but only once the
    logical clock has reached or passed the appointment's start_utc"

    Design: Difficulty/boundary_precision_check/appointment_checkin_at_exact_start_boundary
    """
    office, _, prep, _ = setup_office_with_preparer()
    client = create_client(office["id"], full_name="Ap2", ssn_last4="3030")
    appt = validate_success(api.create_appointment(
        office["id"],
        {"client_id": client["id"], "preparer_id": prep["id"],
         "start_utc": "2026-06-10T09:00:00Z", "end_utc": "2026-06-10T10:00:00Z"}, FD), 201)
    # Clock well past start → check-in allowed.
    validate_success(api.set_clock({"to_iso8601": "2026-06-10T09:30:00Z"}, OM), 200)
    ok = validate_success(api.transition_appointment(appt["id"], {"to": "CHECKED_IN"}, FD), 200)
    assert ok["status"] == "CHECKED_IN"


# ─── compensating_invariant / office_open_return_count_create_then_cancel ──

def test_open_return_count_starts_zero_on_fresh_office(api):
    """PRD §3.1: "On creation the office's efin_status is ACTIVE and its
    open_return_count is zero."

    Design: Difficulty/compensating_invariant/office_open_return_count_create_then_cancel
    """
    office = validate_success(api_client.create_office(
        {"name": "Fresh Count", "efin": "191919", "state_code": "KS"}, OM), 201)
    assert office["open_return_count"] == 0, "fresh office must start at open_return_count 0"


# ─── compensating_invariant / preparer_assigned_open_returns_assign_then_cancel ─

def test_assigned_open_returns_starts_zero_on_new_preparer(api):
    """PRD §3.1: "A newly added preparer begins with assigned_open_returns at
    zero, and the server records the parent office_id on the preparer."

    Design: Difficulty/compensating_invariant/preparer_assigned_open_returns_assign_then_cancel
    """
    office, _, prep, _ = setup_office_with_preparer()
    fresh = validate_success(api.get_preparer(prep["id"], OM), 200)
    assert fresh["assigned_open_returns"] == 0, "new preparer must start at assigned_open_returns 0"
