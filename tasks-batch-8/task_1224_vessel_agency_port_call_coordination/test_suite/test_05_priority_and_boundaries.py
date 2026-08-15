"""Validation-priority pairs and boundary-precision checks."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    set_clock, create_principal, create_port_call, create_da_for_call,
    add_manual_line, create_berth_window, create_husbandry_case,
    file_all_notifications, drive_call_to_cleared, drive_call_to_alongside,
    send_da_and_fund,
    make_agency_ops_headers, make_agency_finance_headers,
    make_port_authority_headers, make_husbandry_officer_headers,
)
from test_helpers.api_client import api_client


# ---------------------------------------------------------------------------
# Queue A: priority_pair_validation_conflict / sailing_state_vs_funding_priority
# ---------------------------------------------------------------------------

def test_sailing_on_nominated_call_reports_state_not_funding(api):
    """PRD §2.7: "6. **State-machine legality** — the target resource's state
    machine must permit the requested transition from its current state ...
    otherwise `ERR_INVALID_STATE` (HTTP 409)." and "11. **Fiscal gates** —
    funding sufficiency at sailing, the principal credit gate, and the
    settlement preconditions." (state stage precedes fiscal stage)
    PRD §3.3: record-sailing moves "the call from `ALONGSIDE` to `SAILED`".

    Design: Difficulty/priority_pair_validation_conflict/sailing_state_vs_funding_priority
    """
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex Shipping", credit_limit_cents=0)
    pc = create_port_call(
        principal["id"], eta="2026-06-10T20:00:00Z", etd="2026-06-13T01:00:00Z")
    da = create_da_for_call(pc)  # PRO_FORMA, no advances — would fail funding too
    bw = create_berth_window(pc["id"], berth_code="B4",
                             start_at="2026-06-10T18:00:00Z", end_at="2026-06-14T06:00:00Z")
    resp = api_client.record_sailing(
        pc["id"], {"berth_window_id": bw["id"]}, make_agency_ops_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    pc_now = validate_success(api_client.get_port_call(pc["id"], make_agency_ops_headers()))
    assert pc_now["ops_status"] == "NOMINATED", "no side effects fired"
    da_now = validate_success(api_client.get_disbursement_account(da["id"], make_agency_ops_headers()))
    assert da_now["status"] == "PRO_FORMA"


def test_sailing_on_nominated_call_never_reaches_funding_gate(api):
    """PRD §2.7: "The API evaluates every request through a fixed pipeline,
    earlier stages first" — with state-machine legality at stage 6 and fiscal
    gates at stage 11, a call in NOMINATED cannot produce
    `ERR_FUNDING_SHORTFALL` even with an unfunded account.

    Design: Difficulty/priority_pair_validation_conflict/sailing_state_vs_funding_priority
    """
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex Shipping", credit_limit_cents=0)
    pc = create_port_call(
        principal["id"], eta="2026-06-10T20:00:00Z", etd="2026-06-13T01:00:00Z")
    da = create_da_for_call(pc)
    add_manual_line(da["id"], 10000, description="stores")  # advance_required > 0, no advances
    bw = create_berth_window(pc["id"], berth_code="B4",
                             start_at="2026-06-10T18:00:00Z", end_at="2026-06-14T06:00:00Z")
    resp = api_client.record_sailing(
        pc["id"], {"berth_window_id": bw["id"]}, make_agency_ops_headers())
    body = resp.json()
    assert body["data"]["error_id"] == "ERR_INVALID_STATE", (
        f"state error must win over the funding gate; got {body['data']['error_id']}")
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Queue A: priority_pair_validation_conflict / sailing_safety_vs_referential_priority
# ---------------------------------------------------------------------------

def _setup_alongside_with_critical_case():
    """Call ALONGSIDE with all gates satisfied (DA sent + funded via 820 on
    total 1025) except an open CRITICAL unwaived husbandry case; plus a second
    call with its own REQUESTED window to use as a mismatched berth ref."""
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex Shipping", credit_limit_cents=0)
    pc1 = create_port_call(
        principal["id"], eta="2026-06-10T20:00:00Z", etd="2026-06-13T01:00:00Z")
    da = create_da_for_call(pc1)
    add_manual_line(da["id"], 1000, description="stores")
    pc1, bw1 = drive_call_to_alongside(pc1, berth_code="B5")
    send_da_and_fund(da["id"], 820)
    hc = create_husbandry_case(pc1["id"], case_type="MEDICAL", severity="CRITICAL",
                               summary="suspected appendicitis")
    pc2 = create_port_call(
        principal["id"], vessel_name="SS Otter", imo_number="9000021",
        vessel_gt=4000, eta="2026-06-20T10:00:00Z", etd="2026-06-22T10:00:00Z")
    bw2 = create_berth_window(pc2["id"], berth_code="B6",
                              start_at="2026-06-20T08:00:00Z", end_at="2026-06-22T20:00:00Z")
    return pc1, bw1, hc, pc2, bw2, da


def test_sailing_safety_gate_beats_berth_mismatch(api):
    """PRD §2.7: "7. **Safety gates** — the critical-husbandry gate at
    sailing; `ERR_OPEN_CRITICAL_HUSBANDRY` (HTTP 422)." precedes "9.
    **Business constraints** — per-call uniqueness, notification coverage,
    berth and crew gates at movement operations ...".

    Design: Difficulty/priority_pair_validation_conflict/sailing_safety_vs_referential_priority
    """
    pc1, bw1, hc, pc2, bw2, da = _setup_alongside_with_critical_case()
    resp = api_client.record_sailing(
        pc1["id"], {"berth_window_id": bw2["id"]}, make_agency_ops_headers())
    body = resp.json()
    assert body["data"]["error_id"] == "ERR_OPEN_CRITICAL_HUSBANDRY", (
        f"safety gate must precede the berth-window-mismatch constraint; got {body['data']['error_id']}")
    assert resp.status_code == 422


def test_sailing_safety_gate_leaves_state_untouched(api):
    """PRD §3.3: "No husbandry case of this call with `severity` `CRITICAL`
    may sit in `OPEN` or `IN_TREATMENT` without its `departure_waiver_granted`
    flag set (`ERR_OPEN_CRITICAL_HUSBANDRY`)."

    Design: Difficulty/priority_pair_validation_conflict/sailing_safety_vs_referential_priority
    """
    pc1, bw1, hc, pc2, bw2, da = _setup_alongside_with_critical_case()
    resp = api_client.record_sailing(
        pc1["id"], {"berth_window_id": bw2["id"]}, make_agency_ops_headers())
    validate_error(resp, ApiErrorId.ERR_OPEN_CRITICAL_HUSBANDRY)
    pc1_now = validate_success(api_client.get_port_call(pc1["id"], make_agency_ops_headers()))
    assert pc1_now["ops_status"] == "ALONGSIDE"
    bw2_now = validate_success(api_client.get_berth_window(bw2["id"], make_agency_ops_headers()))
    assert bw2_now["status"] == "REQUESTED"
    hc_now = validate_success(api_client.get_husbandry_case(hc["id"], make_husbandry_officer_headers()))
    assert hc_now["status"] == "OPEN"
    assert hc_now["departure_waiver_granted"] is False


# ---------------------------------------------------------------------------
# Queue A: boundary_precision_check / funding_gate_exact_equality
# ---------------------------------------------------------------------------

def _setup_alongside_call_with_da(berth_code, vessel_name, imo_number,
                                  principal_id):
    """ALONGSIDE call at NODUE with DA holding two SUNDRY 3333 lines (total
    6832, advance_required 5466), sent. Returns (pc, bw, da)."""
    pc = create_port_call(
        principal_id, vessel_name=vessel_name, imo_number=imo_number,
        eta="2026-06-10T20:00:00Z", etd="2026-06-13T01:00:00Z")
    da = create_da_for_call(pc)
    add_manual_line(da["id"], 3333, description="a1")
    add_manual_line(da["id"], 3333, description="a2")
    pc, bw = drive_call_to_alongside(pc, berth_code=berth_code)
    get_success_data(api_client.send_disbursement_account(da["id"], make_agency_ops_headers()))
    return pc, bw, da


def test_funding_gate_exact_equality_sails(api):
    """PRD §3.3: "the account's net funding, meaning `advances_received_cents`
    minus `advances_refunded_cents`, must be at least `advance_required_cents`,
    with exact equality satisfying the gate (`ERR_FUNDING_SHORTFALL`)."

    Design: Difficulty/boundary_precision_check/funding_gate_exact_equality
    """
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex Shipping", credit_limit_cents=0)
    pc, bw, da = _setup_alongside_call_with_da("B7", "MV Equal", "9000030", principal["id"])
    get_success_data(api_client.create_funding_advance(
        da["id"], {"amount_cents": 5466}, make_agency_finance_headers()))
    da_now = validate_success(api_client.get_disbursement_account(da["id"], make_agency_ops_headers()))
    assert da_now["status"] == "FUNDED"
    assert da_now["advance_required_cents"] == 5466
    set_clock("2026-06-13T23:00:00Z")
    pc = validate_success(api_client.record_sailing(
        pc["id"], {"berth_window_id": bw["id"]}, make_agency_ops_headers()))
    assert pc["ops_status"] == "SAILED", "5466 >= 5466 passes at exact equality"


def test_funding_gate_one_cent_short_rejected(api):
    """PRD §3.3: "the account's net funding, meaning `advances_received_cents`
    minus `advances_refunded_cents`, must be at least `advance_required_cents`,
    with exact equality satisfying the gate (`ERR_FUNDING_SHORTFALL`)."
    PRD §3.8: "whenever a refund, or a totals recompute that raises the
    requirement, breaks the gate, an account in `FUNDED` reverts to
    `SENT_TO_PRINCIPAL`" (and, symmetrically, the gate never fires while
    funding is short).

    Design: Difficulty/boundary_precision_check/funding_gate_exact_equality
    """
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex Shipping", credit_limit_cents=0)
    pc, bw, da = _setup_alongside_call_with_da("B8", "MV Short", "9000031", principal["id"])
    get_success_data(api_client.create_funding_advance(
        da["id"], {"amount_cents": 5465}, make_agency_finance_headers()))
    da_now = validate_success(api_client.get_disbursement_account(da["id"], make_agency_ops_headers()))
    assert da_now["status"] == "SENT_TO_PRINCIPAL", "auto-FUNDED never fires one cent short"
    set_clock("2026-06-13T23:00:00Z")
    resp = api_client.record_sailing(
        pc["id"], {"berth_window_id": bw["id"]}, make_agency_ops_headers())
    validate_error(resp, ApiErrorId.ERR_FUNDING_SHORTFALL)
    pc_now = validate_success(api_client.get_port_call(pc["id"], make_agency_ops_headers()))
    assert pc_now["ops_status"] == "ALONGSIDE"


# ---------------------------------------------------------------------------
# Queue A: boundary_precision_check / berth_adjacency_half_open_boundary
# ---------------------------------------------------------------------------

def _setup_confirmed_w1_with_candidates():
    set_clock("2026-05-01T00:00:00Z")
    principal = create_principal(name="Apex Shipping", credit_limit_cents=0)
    pc = create_port_call(
        principal["id"], eta="2026-06-01T08:00:00Z", etd="2026-06-03T08:00:00Z")
    w1 = create_berth_window(pc["id"], berth_code="BERTH-09",
                             start_at="2026-06-01T08:00:00Z", end_at="2026-06-01T20:00:00Z")
    get_success_data(api_client.confirm_berth_window(w1["id"], make_port_authority_headers()))
    w2 = create_berth_window(pc["id"], berth_code="BERTH-09",
                             start_at="2026-06-01T20:00:00Z", end_at="2026-06-02T08:00:00Z")
    w3 = create_berth_window(pc["id"], berth_code="BERTH-09",
                             start_at="2026-06-01T19:59:00Z", end_at="2026-06-01T21:00:00Z")
    return pc, w1, w2, w3


def test_berth_adjacency_exact_touch_is_not_conflict(api):
    """PRD §2.9: "Mere adjacency — one window's `end_at` exactly equal to the
    other's `start_at` — is not a conflict."

    Design: Difficulty/boundary_precision_check/berth_adjacency_half_open_boundary
    """
    pc, w1, w2, w3 = _setup_confirmed_w1_with_candidates()
    w2 = validate_success(api_client.confirm_berth_window(w2["id"], make_port_authority_headers()))
    assert w2["status"] == "CONFIRMED", "adjacent at exactly W1.end == W2.start: allowed"


def test_berth_one_minute_overlap_rejected(api):
    """PRD §2.9: "A candidate window conflicts with an existing window on the
    same `berth_code` in `CONFIRMED` or `OCCUPIED` status if and only if the
    existing window starts strictly before the candidate ends and the
    candidate starts strictly before the existing window ends ... A
    conflicting confirmation is rejected with `ERR_BERTH_WINDOW_OVERLAP`
    (HTTP 409)."

    Design: Difficulty/boundary_precision_check/berth_adjacency_half_open_boundary
    """
    pc, w1, w2, w3 = _setup_confirmed_w1_with_candidates()
    resp = api_client.confirm_berth_window(w3["id"], make_port_authority_headers())
    validate_error(resp, ApiErrorId.ERR_BERTH_WINDOW_OVERLAP)
    w3_now = validate_success(api_client.get_berth_window(w3["id"], make_agency_ops_headers()))
    assert w3_now["status"] == "REQUESTED", "rejection leaves state untouched"
