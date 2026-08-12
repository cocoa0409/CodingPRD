"""Cross-entity state dependencies and shared-resource overlap checks."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    set_clock, create_principal, create_port_call, create_da_for_call,
    create_berth_window, create_notification, create_vendor, create_service_order,
    drive_call_to_alongside,
    make_agency_ops_headers, make_agency_finance_headers,
    make_port_authority_headers, make_vendor_rep_headers,
)
from test_helpers.api_client import api_client


# ---------------------------------------------------------------------------
# Queue A: cross_entity_state_dependency / sailing_blocked_until_da_sent
# ---------------------------------------------------------------------------

def _setup_alongside_call_proforma_da():
    """ALONGSIDE call with a zero-line DA still in PRO_FORMA (advance_required
    0, so sending alone satisfies the money gate)."""
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex Shipping", credit_limit_cents=0)
    pc = create_port_call(
        principal["id"], eta="2026-06-10T20:00:00Z", etd="2026-06-13T01:00:00Z")
    da = create_da_for_call(pc)
    pc, bw = drive_call_to_alongside(pc, berth_code="B10")
    set_clock("2026-06-13T23:00:00Z")
    return pc, bw, da


def test_sailing_rejected_while_da_proforma(api):
    """PRD §3.3: "a non-`SUPERSEDED` disbursement account must exist in one of
    `SENT_TO_PRINCIPAL`, `FUNDED`, `FINAL`, `DISPUTED`, or `SETTLED` — a call
    whose account is still `PRO_FORMA`, absent, or superseded fails with
    `ERR_DA_NOT_SENT`."

    Design: Difficulty/cross_entity_state_dependency/sailing_blocked_until_da_sent
    """
    pc, bw, da = _setup_alongside_call_proforma_da()
    resp = api_client.record_sailing(
        pc["id"], {"berth_window_id": bw["id"]}, make_agency_ops_headers())
    validate_error(resp, ApiErrorId.ERR_DA_NOT_SENT)
    pc_now = validate_success(api_client.get_port_call(pc["id"], make_agency_ops_headers()))
    assert pc_now["ops_status"] == "ALONGSIDE"


def test_sailing_succeeds_after_da_sent(api):
    """PRD §3.8: "an `AgencyOps` agent moves the account from `PRO_FORMA` to
    `SENT_TO_PRINCIPAL`"; PRD §3.3 lists `SENT_TO_PRINCIPAL` among the
    account statuses that satisfy the record-sailing account gate.

    Design: Difficulty/cross_entity_state_dependency/sailing_blocked_until_da_sent
    """
    pc, bw, da = _setup_alongside_call_proforma_da()
    resp = api_client.record_sailing(
        pc["id"], {"berth_window_id": bw["id"]}, make_agency_ops_headers())
    validate_error(resp, ApiErrorId.ERR_DA_NOT_SENT)
    da = validate_success(api_client.send_disbursement_account(da["id"], make_agency_ops_headers()))
    assert da["status"] == "SENT_TO_PRINCIPAL"
    assert da["advance_required_cents"] == 0
    pc = validate_success(api_client.record_sailing(
        pc["id"], {"berth_window_id": bw["id"]}, make_agency_ops_headers()))
    assert pc["ops_status"] == "SAILED"


# ---------------------------------------------------------------------------
# Queue A: cross_entity_state_dependency / berth_occupy_requires_harbor_master_ack
# ---------------------------------------------------------------------------

def _setup_confirmed_window_hm_submitted():
    """NOMINATED call; HARBOR_MASTER notification only SUBMITTED; berth window
    CONFIRMED [2026-06-02T10:00, 12:00]; clock inside the window."""
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex Shipping", credit_limit_cents=0)
    pc = create_port_call(
        principal["id"], eta="2026-06-02T10:00:00Z", etd="2026-06-03T10:00:00Z")
    n_hm = create_notification(pc["id"], "HARBOR_MASTER", payload_summary="hm")
    get_success_data(api_client.submit_notification(n_hm["id"], make_agency_ops_headers()))
    bw = create_berth_window(pc["id"], berth_code="B11",
                             start_at="2026-06-02T10:00:00Z", end_at="2026-06-02T12:00:00Z")
    get_success_data(api_client.confirm_berth_window(bw["id"], make_port_authority_headers()))
    set_clock("2026-06-02T11:00:00Z")
    return pc, n_hm, bw


def test_occupy_rejected_until_harbor_master_acknowledged(api):
    """PRD §3.3: "An `AgencyOps` agent marks a `CONFIRMED` window occupied
    once the logical clock has reached its `start_at` — an early attempt fails
    with `ERR_WINDOW_NOT_STARTED` — and only while the parent call's
    `HARBOR_MASTER` notification is `ACKNOWLEDGED`, failing otherwise with
    `ERR_HM_ACK_OUTSTANDING`."

    Design: Difficulty/cross_entity_state_dependency/berth_occupy_requires_harbor_master_ack
    """
    pc, n_hm, bw = _setup_confirmed_window_hm_submitted()
    resp = api_client.occupy_berth_window(bw["id"], make_agency_ops_headers())
    validate_error(resp, ApiErrorId.ERR_HM_ACK_OUTSTANDING)
    bw_now = validate_success(api_client.get_berth_window(bw["id"], make_agency_ops_headers()))
    assert bw_now["status"] == "CONFIRMED"


def test_occupy_succeeds_after_harbor_master_acknowledged(api):
    """PRD §3.3: "only while the parent call's `HARBOR_MASTER` notification is
    `ACKNOWLEDGED` ... occupation stamps `occupied_at` from the clock."

    Design: Difficulty/cross_entity_state_dependency/berth_occupy_requires_harbor_master_ack
    """
    pc, n_hm, bw = _setup_confirmed_window_hm_submitted()
    get_success_data(api_client.acknowledge_notification(
        n_hm["id"], {"authority_reference": "HM-9"}, make_port_authority_headers()))
    bw = validate_success(api_client.occupy_berth_window(bw["id"], make_agency_ops_headers()))
    assert bw["status"] == "OCCUPIED"
    assert bw["occupied_at"] == "2026-06-02T11:00:00Z", (
        f"occupied_at stamped from the logical clock; got {bw['occupied_at']}")


# ---------------------------------------------------------------------------
# Queue A: resource_temporal_overlap / berth_half_open_overlap_rejected
# ---------------------------------------------------------------------------

def test_berth_true_overlap_confirm_rejected(api):
    """PRD §2.9: "A candidate window conflicts with an existing window on the
    same `berth_code` in `CONFIRMED` or `OCCUPIED` status if and only if the
    existing window starts strictly before the candidate ends and the
    candidate starts strictly before the existing window ends ... A
    conflicting confirmation is rejected with `ERR_BERTH_WINDOW_OVERLAP`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/berth_half_open_overlap_rejected
    """
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex Shipping", credit_limit_cents=0)
    pc = create_port_call(
        principal["id"], eta="2026-06-03T08:00:00Z", etd="2026-06-05T08:00:00Z")
    w1 = create_berth_window(pc["id"], berth_code="BERTH-11",
                             start_at="2026-06-03T08:00:00Z", end_at="2026-06-03T20:00:00Z")
    get_success_data(api_client.confirm_berth_window(w1["id"], make_port_authority_headers()))
    w2 = create_berth_window(pc["id"], berth_code="BERTH-11",
                             start_at="2026-06-03T19:00:00Z", end_at="2026-06-03T23:00:00Z")
    resp = api_client.confirm_berth_window(w2["id"], make_port_authority_headers())
    validate_error(resp, ApiErrorId.ERR_BERTH_WINDOW_OVERLAP)
    w2_now = validate_success(api_client.get_berth_window(w2["id"], make_agency_ops_headers()))
    assert w2_now["status"] == "REQUESTED"


def test_berth_rejection_leaves_occupant_unchanged(api):
    """PRD §2.9: "Uncommitted reservations never occupy: a berth window in
    `REQUESTED` and a service order in `ORDERED` block nothing — each is only
    checked against the committed schedule at the moment of its own
    confirmation."

    Design: Difficulty/resource_temporal_overlap/berth_half_open_overlap_rejected
    """
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex Shipping", credit_limit_cents=0)
    pc = create_port_call(
        principal["id"], eta="2026-06-03T08:00:00Z", etd="2026-06-05T08:00:00Z")
    w1 = create_berth_window(pc["id"], berth_code="BERTH-11",
                             start_at="2026-06-03T08:00:00Z", end_at="2026-06-03T20:00:00Z")
    get_success_data(api_client.confirm_berth_window(w1["id"], make_port_authority_headers()))
    w2 = create_berth_window(pc["id"], berth_code="BERTH-11",
                             start_at="2026-06-03T19:00:00Z", end_at="2026-06-03T23:00:00Z")
    resp = api_client.confirm_berth_window(w2["id"], make_port_authority_headers())
    validate_error(resp, ApiErrorId.ERR_BERTH_WINDOW_OVERLAP)
    w1_now = validate_success(api_client.get_berth_window(w1["id"], make_agency_ops_headers()))
    assert w1_now["status"] == "CONFIRMED", "occupant unchanged by the rejected candidate"


# ---------------------------------------------------------------------------
# Queue A: resource_temporal_overlap / service_order_buffer_inflated_overlap
# ---------------------------------------------------------------------------

def _setup_confirmed_tug_with_candidates():
    """SO1 TUG on TUG-9 [10:00, 11:00] CONFIRMED; SO2 [11:45, 12:30] and SO3
    [12:31, 13:30] same unit, ORDERED."""
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex Shipping", credit_limit_cents=0)
    pc = create_port_call(
        principal["id"], eta="2026-06-04T08:00:00Z", etd="2026-06-05T08:00:00Z")
    vendor = create_vendor(name="TugCo", categories=["STORES"], contact_email="ops@tugco.example")
    vh = make_vendor_rep_headers(vendor["id"])
    so1 = create_service_order(
        pc["id"], kind="TUG", vendor_id=vendor["id"], resource_unit="TUG-9",
        window_start="2026-06-04T10:00:00Z", window_end="2026-06-04T11:00:00Z",
        estimated_cents=20000)
    get_success_data(api_client.confirm_service_order(so1["id"], vh))
    so2 = create_service_order(
        pc["id"], kind="TUG", vendor_id=vendor["id"], resource_unit="TUG-9",
        window_start="2026-06-04T11:45:00Z", window_end="2026-06-04T12:30:00Z",
        estimated_cents=20000)
    so3 = create_service_order(
        pc["id"], kind="TUG", vendor_id=vendor["id"], resource_unit="TUG-9",
        window_start="2026-06-04T12:31:00Z", window_end="2026-06-04T13:30:00Z",
        estimated_cents=20000)
    return pc, vendor, vh, so1, so2, so3


def test_service_order_45_minute_gap_conflicts(api):
    """PRD §2.9: "each requested window is inflated by forty-five minutes on
    both ends and compared as a closed interval ... Inflated intervals that
    merely touch do conflict, so two raw windows on the same unit are only
    safe when the gap between them is strictly greater than ninety minutes. A
    conflicting confirmation is rejected with `ERR_RESOURCE_UNIT_OVERLAP`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/service_order_buffer_inflated_overlap
    """
    pc, vendor, vh, so1, so2, so3 = _setup_confirmed_tug_with_candidates()
    # SO2 [11:45, 12:30]: inflated [11:00, 13:15] vs SO1 inflated [09:15, 11:45] — touch at 11:45/11:00
    resp = api_client.confirm_service_order(so2["id"], vh)
    validate_error(resp, ApiErrorId.ERR_RESOURCE_UNIT_OVERLAP)
    so2_now = validate_success(api_client.get_service_order(so2["id"], make_agency_ops_headers()))
    assert so2_now["status"] == "ORDERED"


def test_service_order_91_minute_gap_clears(api):
    """PRD §2.9: "two raw windows on the same unit are only safe when the gap
    between them is strictly greater than ninety minutes."

    Design: Difficulty/resource_temporal_overlap/service_order_buffer_inflated_overlap
    """
    pc, vendor, vh, so1, so2, so3 = _setup_confirmed_tug_with_candidates()
    # SO3 [12:31, 13:30]: raw gap after SO1 is 91 minutes (> 90) -> clears
    so3 = validate_success(api_client.confirm_service_order(so3["id"], vh))
    assert so3["status"] == "CONFIRMED"
