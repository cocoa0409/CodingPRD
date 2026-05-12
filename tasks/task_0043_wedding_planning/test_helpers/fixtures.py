"""Composite setup helpers for the Wedding Planning test suite.

Most interesting test claims require the system to be in a specific state
that takes 5-15 API calls to reach: a project in PLANNING with vendors
approved, quotes offered, and at least one ACCEPTED contract; a settlement
walked all the way to FINALIZED with the project ledger updated; a project
in SETTLEMENT with all contracts FINALIZED ready to close. These helpers
encapsulate those preambles.

Identity threading (PRD §2.1):

- Planner, Couple, Auditor are opaque -- the shared TEST_USERS constants
  carry stable opaque ids (PLANNER_ID, AUDITOR_ID). Fixtures pass these
  same ids into the create-project payload as planner_user_id and
  auditor_user_id, so the constants are the legitimate owners of the
  resources they create. Tests that need a SECOND distinct planner (for
  segregation-of-duties: requester != approver, confirmer != finalizer)
  use planner_headers_alt / auditor_headers_alt.

- VendorRep is entity-backed -- 'X-User-ID is the id of the acting Vendor'.
  Any ownership-gated call (POST /vendors/{vid}/quotes,
  /quotes/{id}/offer, /quotes/{id}/withdraw, /contracts/{id}/revise,
  /settlement/confirm) MUST use make_vendor_rep_headers(vendor['id']) so
  X-User-ID resolves to a real Vendor.id. Falling back to TEST_USERS
  would defeat every ownership check.

Setup calls use get_success_data (lenient validator), so broken
preconditions surface as obvious 'Setup failed' errors rather than
confusing assertion failures inside test bodies.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .factories import (
    create_change_order_payload,
    create_contract_payload,
    create_guest_payload,
    create_milestone_payload,
    create_project_payload,
    create_quote_payload,
    create_settlement_payload,
    create_template_payload,
    create_timeline_slot_payload,
    create_vendor_payload,
    emit_event_payload,
    far_future_seconds,
    now_seconds,
    rsvp_payload,
)
from .test_users import (
    AUDITOR_ID,
    AUDITOR_ID_ALT,
    COUPLE_ID,
    PLANNER_ID,
    PLANNER_ID_ALT,
    PLANNER_ID_THIRD,
    TEST_USERS,
    make_auditor_headers,
    make_planner_headers,
    make_vendor_rep_headers,
)


# ===========================================================================
# Time helpers
# ===========================================================================
def t_after(seconds_from_now: int) -> int:
    return now_seconds() + seconds_from_now


# ===========================================================================
# Tier 0: low-level building blocks
# ===========================================================================
def create_project(
    *,
    planner_id: str = PLANNER_ID,
    auditor_id: str = AUDITOR_ID,
    total_budget_cents: int = 5_000_000,
    scale: str = "MEDIUM",
    style: str = "MODERN",
    ceremony_offset_seconds: int = 180 * 86400,
    template_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    **payload_overrides: Any,
) -> Dict[str, Any]:
    """Create a wedding project. The planner_id / auditor_id are written
    into the project as planner_user_id / auditor_user_id, so subsequent
    ownership-gated calls by Planner with X-User-ID==planner_id succeed."""
    headers = headers or make_planner_headers(planner_id)
    payload = create_project_payload(
        planner_user_id=planner_id,
        auditor_user_id=auditor_id,
        total_budget_cents=total_budget_cents,
        scale=scale,
        style=style,
        ceremony_date=t_after(ceremony_offset_seconds),
        template_id=template_id,
        **payload_overrides,
    )
    resp = api_client.create_project(payload, headers)
    return get_success_data(resp)


def add_milestone(
    project_id: str,
    *,
    label: str = "Milestone",
    due_at: Optional[int] = None,
    percent_of_budget: float = 100.0,
    planner_id: str = PLANNER_ID,
) -> Dict[str, Any]:
    headers = make_planner_headers(planner_id)
    resp = api_client.create_milestone(
        project_id,
        create_milestone_payload(
            label=label,
            due_at=due_at if due_at is not None else t_after(60 * 86400),
            percent_of_budget=percent_of_budget,
        ),
        headers,
    )
    return get_success_data(resp)


def add_full_milestones(
    project_id: str,
    *,
    planner_id: str = PLANNER_ID,
) -> List[Dict[str, Any]]:
    """Add a single milestone summing to 100.0 percent of budget so the
    project is eligible to activate."""
    return [add_milestone(
        project_id,
        label="Initial Milestone",
        percent_of_budget=100.0,
        planner_id=planner_id,
    )]


def activate_project(
    project_id: str,
    *,
    planner_id: str = PLANNER_ID,
) -> Dict[str, Any]:
    headers = make_planner_headers(planner_id)
    resp = api_client.activate_project(project_id, headers)
    return get_success_data(resp)


def create_approved_vendor(
    *,
    category: str = "PHOTOGRAPHY",
    name: Optional[str] = None,
    auditor_id: str = AUDITOR_ID,
) -> Dict[str, Any]:
    """Register a vendor and approve it. Returns the APPROVED vendor."""
    # POST /vendors needs role=VendorRep but no ownership check yet because
    # the vendor doesn't exist; PRD §2.1 says VendorRep X-User-ID compares
    # to the acting vendor's id. There is no acting vendor at registration,
    # so the fallback shared id is acceptable here.
    vrep_headers = TEST_USERS["vendor_rep_headers_fallback"]
    resp = api_client.create_vendor(
        create_vendor_payload(name=name, category=category),
        vrep_headers,
    )
    vendor = get_success_data(resp)

    auditor_headers = make_auditor_headers(auditor_id)
    resp2 = api_client.approve_vendor(vendor["id"], auditor_headers)
    approved = get_success_data(resp2)
    return approved


def create_offered_quote(
    vendor: Dict[str, Any],
    *,
    amount_cents: int = 100_000,
    valid_until_offset: int = 90 * 86400,
) -> Dict[str, Any]:
    """Create a Quote on the (already-APPROVED) vendor and transition it
    DRAFT -> OFFERED so a contract may bind it."""
    vrep_headers = make_vendor_rep_headers(vendor["id"])
    resp = api_client.create_quote(
        vendor["id"],
        create_quote_payload(
            amount_cents=amount_cents,
            valid_until=t_after(valid_until_offset),
        ),
        vrep_headers,
    )
    quote = get_success_data(resp)
    resp2 = api_client.offer_quote(vendor["id"], quote["id"], vrep_headers)
    return get_success_data(resp2)


def create_draft_contract(
    project_id: str,
    vendor: Dict[str, Any],
    quote: Dict[str, Any],
    *,
    planner_id: str = PLANNER_ID,
) -> Dict[str, Any]:
    """POST /wedding-projects/{p}/contracts; returns DRAFT contract."""
    headers = make_planner_headers(planner_id)
    resp = api_client.create_contract(
        project_id,
        create_contract_payload(vendor_id=vendor["id"], quote_id=quote["id"]),
        headers,
    )
    return get_success_data(resp)


def send_for_negotiation(
    project_id: str,
    contract_id: str,
    *,
    planner_id: str = PLANNER_ID,
) -> Dict[str, Any]:
    headers = make_planner_headers(planner_id)
    resp = api_client.send_for_negotiation(project_id, contract_id, headers)
    return get_success_data(resp)


def sign_contract(
    project_id: str,
    contract_id: str,
    *,
    planner_id: str = PLANNER_ID,
) -> Dict[str, Any]:
    headers = make_planner_headers(planner_id)
    resp = api_client.sign_contract(project_id, contract_id, headers)
    return get_success_data(resp)


def emit_esign_completed(envelope_id: str) -> Dict[str, Any]:
    """PRD §3.8: 'an ESIGN_COMPLETED event whose envelope_id matches a
    contract's e_sign_envelope_id is what makes that contract eligible for
    the SIGNED to ACCEPTED transition.'"""
    # Per PRD §3.8 the event hook is open to any authenticated role.
    headers = TEST_USERS["planner_headers"]
    resp = api_client.emit_event(
        emit_event_payload(kind="ESIGN_COMPLETED", envelope_id=envelope_id),
        headers,
    )
    if resp.status_code not in (200, 202):
        raise AssertionError(
            f"ESIGN_COMPLETED emit failed with status {resp.status_code}: "
            f"{resp.text[:200]}"
        )
    if resp.text:
        try:
            return resp.json()
        except Exception:
            return {}
    return {}


def accept_signature(
    project_id: str,
    contract_id: str,
    *,
    planner_id: str = PLANNER_ID,
) -> Dict[str, Any]:
    headers = make_planner_headers(planner_id)
    resp = api_client.accept_signature(project_id, contract_id, headers)
    return get_success_data(resp)


def get_contract(project_id: str, contract_id: str,
                 *, planner_id: str = PLANNER_ID) -> Dict[str, Any]:
    resp = api_client.get_contract(
        project_id, contract_id, make_planner_headers(planner_id)
    )
    return get_success_data(resp)


def get_project(project_id: str,
                *, planner_id: str = PLANNER_ID) -> Dict[str, Any]:
    resp = api_client.get_project(
        project_id, make_planner_headers(planner_id)
    )
    return get_success_data(resp)


def get_vendor(vendor_id: str) -> Dict[str, Any]:
    """Vendor-fetch is a read; PRD §4 allows Planner, Auditor, VendorRep
    to GET /vendors/{vid}. We use a Planner header for read-only queries."""
    resp = api_client.get_vendor(vendor_id, TEST_USERS["planner_headers"])
    return get_success_data(resp)


def get_settlement(project_id: str, contract_id: str,
                   *, planner_id: str = PLANNER_ID) -> Dict[str, Any]:
    resp = api_client.get_settlement(
        project_id, contract_id, make_planner_headers(planner_id)
    )
    return get_success_data(resp)


def list_audit_entries(
    project_id: str,
    *,
    event_kind: Optional[str] = None,
    subject_type: Optional[str] = None,
    auditor_id: str = AUDITOR_ID,
) -> List[Dict[str, Any]]:
    headers = make_auditor_headers(auditor_id)
    params: Dict[str, Any] = {"limit": 100}
    if event_kind is not None:
        params["event_kind"] = event_kind
    if subject_type is not None:
        params["subject_type"] = subject_type
    resp = api_client.list_audit_entries(project_id, headers, params=params)
    data, _meta = validate_paginated(resp)
    return data


# ===========================================================================
# Tier 1: walking a single contract through its lifecycle
# ===========================================================================
def drive_contract_to_accepted(
    project_id: str,
    *,
    vendor_category: str = "PHOTOGRAPHY",
    quote_amount_cents: int = 100_000,
    planner_id: str = PLANNER_ID,
    auditor_id: str = AUDITOR_ID,
    vendor: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """End-to-end: create approved vendor + offered quote + contract,
    drive contract DRAFT -> NEGOTIATING -> SIGNED, emit ESIGN_COMPLETED,
    accept-signature -> ACCEPTED.

    Returns (vendor, quote, accepted_contract).
    """
    if vendor is None:
        vendor = create_approved_vendor(
            category=vendor_category, auditor_id=auditor_id,
        )
    quote = create_offered_quote(vendor, amount_cents=quote_amount_cents)
    contract = create_draft_contract(
        project_id, vendor, quote, planner_id=planner_id
    )
    send_for_negotiation(project_id, contract["id"], planner_id=planner_id)
    signed = sign_contract(project_id, contract["id"], planner_id=planner_id)
    envelope_id = signed.get("e_sign_envelope_id")
    if envelope_id:
        emit_esign_completed(envelope_id)
    accepted = accept_signature(
        project_id, contract["id"], planner_id=planner_id
    )
    return vendor, quote, accepted


# ===========================================================================
# Tier 2: project hierarchies in specific states
# ===========================================================================
def setup_project_in_planning(
    *,
    planner_id: str = PLANNER_ID,
    auditor_id: str = AUDITOR_ID,
    total_budget_cents: int = 5_000_000,
    scale: str = "MEDIUM",
    ceremony_offset_seconds: int = 180 * 86400,
) -> Dict[str, Any]:
    """Project DRAFT -> add full milestones -> activate -> PLANNING.
    Returns the PLANNING project."""
    project = create_project(
        planner_id=planner_id,
        auditor_id=auditor_id,
        total_budget_cents=total_budget_cents,
        scale=scale,
        ceremony_offset_seconds=ceremony_offset_seconds,
    )
    add_full_milestones(project["id"], planner_id=planner_id)
    return activate_project(project["id"], planner_id=planner_id)


def setup_project_in_execution(
    *,
    planner_id: str = PLANNER_ID,
    auditor_id: str = AUDITOR_ID,
    total_budget_cents: int = 10_000_000,
    scale: str = "MEDIUM",
    ceremony_offset_seconds: int = 180 * 86400,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Project PLANNING + ACCEPTED contracts for required categories
    (VENUE + CATERING) + start-execution -> EXECUTION.

    Returns (project_in_execution, venue_contract, catering_contract).
    """
    project = setup_project_in_planning(
        planner_id=planner_id,
        auditor_id=auditor_id,
        total_budget_cents=total_budget_cents,
        scale=scale,
        ceremony_offset_seconds=ceremony_offset_seconds,
    )
    _venue_v, _venue_q, venue_contract = drive_contract_to_accepted(
        project["id"], vendor_category="VENUE",
        quote_amount_cents=1_000_000,
        planner_id=planner_id, auditor_id=auditor_id,
    )
    _cat_v, _cat_q, cat_contract = drive_contract_to_accepted(
        project["id"], vendor_category="CATERING",
        quote_amount_cents=1_000_000,
        planner_id=planner_id, auditor_id=auditor_id,
    )

    headers = make_planner_headers(planner_id)
    resp = api_client.start_execution(project["id"], headers)
    project_in_exec = get_success_data(resp)
    return project_in_exec, venue_contract, cat_contract


def advance_clock_past_ceremony(
    project_id: str,
    *,
    planner_id: str = PLANNER_ID,
) -> None:
    """Read project's ceremony_date, then push the clock to ceremony_date+1."""
    project = get_project(project_id, planner_id=planner_id)
    target = int(project["ceremony_date"]) + 1
    headers = make_planner_headers(planner_id)
    resp = api_client.advance_clock(target, headers)
    if resp.status_code not in (200, 202):
        raise AssertionError(
            f"clock advance failed with status {resp.status_code}: "
            f"{resp.text[:200]}"
        )


def setup_project_in_settlement(
    *,
    planner_id: str = PLANNER_ID,
    auditor_id: str = AUDITOR_ID,
    total_budget_cents: int = 10_000_000,
    scale: str = "MEDIUM",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Project EXECUTION -> advance clock past ceremony_date ->
    enter-settlement -> SETTLEMENT.

    Returns (project_in_settlement, venue_contract, catering_contract).
    """
    project_exec, venue_contract, cat_contract = setup_project_in_execution(
        planner_id=planner_id, auditor_id=auditor_id,
        total_budget_cents=total_budget_cents, scale=scale,
        ceremony_offset_seconds=86400,  # short window so we can advance
    )
    advance_clock_past_ceremony(project_exec["id"], planner_id=planner_id)
    headers = make_planner_headers(planner_id)
    resp = api_client.enter_settlement(project_exec["id"], headers)
    project_settle = get_success_data(resp)
    return project_settle, venue_contract, cat_contract


# ===========================================================================
# Tier 3: settlement workflow shortcuts
# ===========================================================================
def create_settlement_for_contract(
    project_id: str,
    contract_id: str,
    *,
    breach_deduction_cents: Optional[int] = None,
    refund_cents: Optional[int] = None,
    planner_id: str = PLANNER_ID,
) -> Dict[str, Any]:
    headers = make_planner_headers(planner_id)
    resp = api_client.create_settlement(
        project_id, contract_id,
        create_settlement_payload(
            breach_deduction_cents=breach_deduction_cents,
            refund_cents=refund_cents,
        ),
        headers,
    )
    return get_success_data(resp)


def confirm_settlement(
    project_id: str,
    contract_id: str,
    vendor_id: str,
) -> Dict[str, Any]:
    """VendorRep confirms (DRAFT -> VENDOR_CONFIRMED). PRD §3.4 requires the
    acting VendorRep's X-User-ID to equal Vendor.id."""
    headers = make_vendor_rep_headers(vendor_id)
    resp = api_client.confirm_settlement(project_id, contract_id, headers)
    return get_success_data(resp)


def finalize_settlement(
    project_id: str,
    contract_id: str,
    *,
    auditor_id: str = AUDITOR_ID,
) -> Dict[str, Any]:
    """Auditor finalizes (VENDOR_CONFIRMED -> FINALIZED). PRD §3.4: the
    acting auditor's X-User-ID MUST differ from confirmed_by_user_id; we
    pass an auditor id distinct from the planner id so segregation
    succeeds (planner drafted the settlement; auditor finalizes)."""
    headers = make_auditor_headers(auditor_id)
    resp = api_client.finalize_settlement(project_id, contract_id, headers)
    return get_success_data(resp)


def drive_settlement_to_finalized(
    project_id: str,
    contract: Dict[str, Any],
    *,
    breach_deduction_cents: int = 0,
    refund_cents: int = 0,
    planner_id: str = PLANNER_ID,
    auditor_id: str = AUDITOR_ID,
) -> Dict[str, Any]:
    """Create -> confirm -> finalize the contract's settlement. Returns
    the FINALIZED settlement. The contract MUST be ACCEPTED already."""
    create_settlement_for_contract(
        project_id, contract["id"],
        breach_deduction_cents=breach_deduction_cents,
        refund_cents=refund_cents,
        planner_id=planner_id,
    )
    confirm_settlement(project_id, contract["id"], contract["vendor_id"])
    return finalize_settlement(
        project_id, contract["id"], auditor_id=auditor_id
    )


def setup_project_with_one_contract_accepted(
    *,
    planner_id: str = PLANNER_ID,
    auditor_id: str = AUDITOR_ID,
    total_budget_cents: int = 5_000_000,
    quote_amount_cents: int = 300_000,
    vendor_category: str = "PHOTOGRAPHY",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """PLANNING project with one ACCEPTED contract on the named category.
    Returns (project, vendor, quote, accepted_contract)."""
    project = setup_project_in_planning(
        planner_id=planner_id, auditor_id=auditor_id,
        total_budget_cents=total_budget_cents,
    )
    vendor, quote, contract = drive_contract_to_accepted(
        project["id"],
        vendor_category=vendor_category,
        quote_amount_cents=quote_amount_cents,
        planner_id=planner_id, auditor_id=auditor_id,
    )
    return project, vendor, quote, contract


# ===========================================================================
# Tier 4: change-order shortcuts
# ===========================================================================
def create_change_order(
    project_id: str,
    contract_id: str,
    *,
    delta_amount_cents: int,
    reason: str = "Scope change",
    requester_planner_id: str = PLANNER_ID,
) -> Dict[str, Any]:
    headers = make_planner_headers(requester_planner_id)
    resp = api_client.create_change_order(
        project_id, contract_id,
        create_change_order_payload(
            delta_amount_cents=delta_amount_cents,
            reason=reason,
        ),
        headers,
    )
    return get_success_data(resp)


def approve_change_order(
    project_id: str,
    contract_id: str,
    change_order_id: str,
    *,
    approver_planner_id: str = PLANNER_ID_ALT,
) -> Dict[str, Any]:
    """PRD §3.4: 'A second planner -- one whose X-User-ID differs from
    requested_by_user_id -- then either approves or rejects the change
    order.' Default approver_planner_id is PLANNER_ID_ALT, which is
    distinct from the default requester PLANNER_ID."""
    headers = make_planner_headers(approver_planner_id)
    resp = api_client.approve_change_order(
        project_id, contract_id, change_order_id, headers
    )
    return get_success_data(resp)


def add_two_change_orders_with_known_order(
    project_id: str,
    contract_id: str,
    *,
    deltas_in_approval_order: List[int],
) -> List[Dict[str, Any]]:
    """Create N change orders (each by the default planner) and approve
    them in the supplied order. Returns the approved change orders in
    approval order. Useful for the scaffold's evaluation-order tests
    (settlement final/preview variants depend on approval-time order).
    """
    cos: List[Dict[str, Any]] = []
    for delta in deltas_in_approval_order:
        co = create_change_order(
            project_id, contract_id,
            delta_amount_cents=delta,
            requester_planner_id=PLANNER_ID,
        )
        approved = approve_change_order(
            project_id, contract_id, co["id"],
            approver_planner_id=PLANNER_ID_ALT,
        )
        cos.append(approved)
    return cos


# ===========================================================================
# Tier 5: timeline-slot helpers (plus per-vendor and parallel-cap setup)
# ===========================================================================
def create_timeline_slot(
    project_id: str,
    *,
    start_at: int,
    end_at: int,
    label: str = "Slot",
    vendor_id: Optional[str] = None,
    setup_buffer_seconds: Optional[int] = None,
    kind: Optional[str] = None,
    planner_id: str = PLANNER_ID,
) -> Dict[str, Any]:
    headers = make_planner_headers(planner_id)
    resp = api_client.create_timeline_slot(
        project_id,
        create_timeline_slot_payload(
            start_at=start_at, end_at=end_at, label=label,
            vendor_id=vendor_id,
            setup_buffer_seconds=setup_buffer_seconds,
            kind=kind,
        ),
        headers,
    )
    return get_success_data(resp)


def setup_project_with_n_accepted_vendors(
    n: int,
    *,
    planner_id: str = PLANNER_ID,
    auditor_id: str = AUDITOR_ID,
    total_budget_cents: int = 50_000_000,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Build a PLANNING project plus N ACCEPTED contracts on N distinct
    vendors. The first vendor is in category VENUE, the second is CATERING
    (so we always satisfy the EXECUTION-required-category gate without
    extra effort if the test later wants EXECUTION). Remaining vendors
    rotate through PHOTOGRAPHY, FLORAL, MC, BAND.

    Returns (project, vendors, contracts).
    """
    project = setup_project_in_planning(
        planner_id=planner_id, auditor_id=auditor_id,
        total_budget_cents=total_budget_cents,
    )
    rotation = ["VENUE", "CATERING", "PHOTOGRAPHY", "FLORAL", "MC", "BAND"]
    vendors: List[Dict[str, Any]] = []
    contracts: List[Dict[str, Any]] = []
    for i in range(n):
        cat = rotation[i % len(rotation)]
        v, _q, c = drive_contract_to_accepted(
            project["id"],
            vendor_category=cat,
            quote_amount_cents=100_000,
            planner_id=planner_id, auditor_id=auditor_id,
        )
        vendors.append(v)
        contracts.append(c)
    return project, vendors, contracts


# ===========================================================================
# Tier 6: guest-list helpers
# ===========================================================================
def create_guest(
    project_id: str,
    *,
    full_name: str = "Guest",
    party_size: Optional[int] = None,
    planner_id: str = PLANNER_ID,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or make_planner_headers(planner_id)
    resp = api_client.create_guest(
        project_id,
        create_guest_payload(full_name=full_name, party_size=party_size),
        headers,
    )
    return get_success_data(resp)


def rsvp_confirm(
    project_id: str,
    guest_id: str,
    *,
    planner_id: str = PLANNER_ID,
    rsvp_status: str = "CONFIRMED",
) -> Dict[str, Any]:
    headers = make_planner_headers(planner_id)
    resp = api_client.rsvp_guest(
        project_id, guest_id, rsvp_payload(rsvp_status=rsvp_status), headers
    )
    return get_success_data(resp)


def setup_intimate_project_with_confirmed_party_size(
    *,
    confirmed_total: int,
    party_size_per_guest: int = 10,
    planner_id: str = PLANNER_ID,
    auditor_id: str = AUDITOR_ID,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """INTIMATE project (cap=50) where exactly `confirmed_total` seats are
    already confirmed; returns (project, list of guests already CONFIRMED).
    """
    project = setup_project_in_planning(
        planner_id=planner_id, auditor_id=auditor_id,
        scale="INTIMATE", total_budget_cents=5_000_000,
    )
    guests: List[Dict[str, Any]] = []
    seats_so_far = 0
    while seats_so_far < confirmed_total:
        size = min(party_size_per_guest, confirmed_total - seats_so_far)
        g = create_guest(
            project["id"], full_name=f"Guest-{len(guests)}",
            party_size=size, planner_id=planner_id,
        )
        confirmed = rsvp_confirm(
            project["id"], g["id"], planner_id=planner_id,
        )
        guests.append(confirmed)
        seats_so_far += size
    return project, guests


# ===========================================================================
# Tier 7: difficulty-design composite scenarios (consumed by test_99)
# ===========================================================================
def setup_settlement_dual_variant_scenario(
    *,
    planner_id: str = PLANNER_ID,
    planner_id_alt: str = PLANNER_ID_ALT,
    auditor_id: str = AUDITOR_ID,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Build the contract + change-order timeline that the dual-variant
    settlement test needs:

    - WeddingProject with total_budget_cents=2_000_000.
    - Catering vendor + offered Quote at 100_000.
    - Contract DRAFT -> ... -> ACCEPTED (pinned_amount_cents=100_000).
    - Two ChangeOrders approved in this order:
        CO1: delta=-150_000 approved at t1.
        CO2: delta=+200_000 approved at t2 > t1.

    Returns (project, accepted_contract, [co1, co2]).

    Approval ordering is enforced by sequential approval calls -- CO1 is
    approved BEFORE CO2 so any chronological ordering implementation will
    see CO1.created_at(audit) < CO2.created_at(audit).
    """
    project, _vendor, _quote, contract = setup_project_with_one_contract_accepted(
        planner_id=planner_id, auditor_id=auditor_id,
        total_budget_cents=2_000_000,
        quote_amount_cents=100_000,
        vendor_category="CATERING",
    )
    cos = add_two_change_orders_with_known_order(
        project["id"], contract["id"],
        deltas_in_approval_order=[-150_000, 200_000],
    )
    return project, contract, cos


def setup_two_finalized_settlements_for_vendor(
    vendor: Dict[str, Any],
    *,
    scores: Tuple[int, int],
    planner_id_a: str = PLANNER_ID,
    planner_id_b: str = PLANNER_ID_ALT,
    auditor_id_a: str = AUDITOR_ID,
    auditor_id_b: str = AUDITOR_ID_ALT,
) -> List[Dict[str, Any]]:
    """For the same vendor, build two completed projects each with one
    ACCEPTED contract and one FINALIZED settlement, attaching a
    PerformanceRating(score=scores[i]) to each.

    Each project uses an isolated planner_id so the planner-vs-auditor
    segregation check at project creation passes; each settlement is
    finalized by an auditor distinct from the drafting planner so the
    settlement-finalize segregation passes.

    Returns the two FINALIZED settlements.
    """
    settlements: List[Dict[str, Any]] = []
    project_a = setup_project_in_planning(
        planner_id=planner_id_a, auditor_id=auditor_id_a,
        total_budget_cents=1_000_000,
    )
    _v_a, _q_a, c_a = drive_contract_to_accepted(
        project_a["id"], vendor=vendor,
        quote_amount_cents=200_000,
        planner_id=planner_id_a, auditor_id=auditor_id_a,
    )
    s_a = drive_settlement_to_finalized(
        project_a["id"], c_a,
        planner_id=planner_id_a, auditor_id=auditor_id_a,
    )
    settlements.append(s_a)
    _attach_performance_rating(
        project_a["id"], c_a["id"], score=scores[0],
        planner_id=planner_id_a,
    )

    project_b = setup_project_in_planning(
        planner_id=planner_id_b, auditor_id=auditor_id_b,
        total_budget_cents=1_000_000,
    )
    _v_b, _q_b, c_b = drive_contract_to_accepted(
        project_b["id"], vendor=vendor,
        quote_amount_cents=200_000,
        planner_id=planner_id_b, auditor_id=auditor_id_b,
    )
    s_b = drive_settlement_to_finalized(
        project_b["id"], c_b,
        planner_id=planner_id_b, auditor_id=auditor_id_b,
    )
    settlements.append(s_b)
    _attach_performance_rating(
        project_b["id"], c_b["id"], score=scores[1],
        planner_id=planner_id_b,
    )

    return settlements


def _attach_performance_rating(
    project_id: str,
    contract_id: str,
    *,
    score: int,
    planner_id: str = PLANNER_ID,
) -> Dict[str, Any]:
    """Helper: planner attaches a PerformanceRating(score) to the
    FINALIZED settlement of (project_id, contract_id)."""
    from .factories import create_performance_rating_payload
    headers = make_planner_headers(planner_id)
    resp = api_client.create_performance_rating(
        project_id, contract_id,
        create_performance_rating_payload(score=score),
        headers,
    )
    return get_success_data(resp)


def setup_project_in_settlement_with_one_finalized_and_one_terminated(
    *,
    planner_id: str = PLANNER_ID,
    auditor_id: str = AUDITOR_ID,
    total_budget_cents: int = 10_000_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build a SETTLEMENT-stage project where:
    - the VENUE contract has its settlement walked all the way to
      FINALIZED, and
    - the CATERING contract has been TERMINATED (so the project's
      'every contract is FINALIZED-or-TERMINATED' precondition for /close
      is satisfied).

    Returns (project_in_settlement, venue_contract, terminated_cat_contract).
    """
    project_settle, venue_contract, cat_contract = setup_project_in_settlement(
        planner_id=planner_id, auditor_id=auditor_id,
        total_budget_cents=total_budget_cents,
    )
    drive_settlement_to_finalized(
        project_settle["id"], venue_contract,
        planner_id=planner_id, auditor_id=auditor_id,
    )
    # Terminate the catering contract so the project has no open contracts.
    headers = make_planner_headers(planner_id)
    resp = api_client.terminate_contract(
        project_settle["id"], cat_contract["id"], headers
    )
    terminated = get_success_data(resp)
    return project_settle, venue_contract, terminated


# ===========================================================================
# Tier 8: utility wrappers for tests
# ===========================================================================
def patch_guest(
    project_id: str,
    guest_id: str,
    payload: Dict[str, Any],
    *,
    planner_id: str = PLANNER_ID,
) -> Dict[str, Any]:
    headers = make_planner_headers(planner_id)
    resp = api_client.patch_guest(project_id, guest_id, payload, headers)
    return get_success_data(resp)


def patch_settlement(
    project_id: str,
    contract_id: str,
    payload: Dict[str, Any],
    *,
    planner_id: str = PLANNER_ID,
) -> Dict[str, Any]:
    headers = make_planner_headers(planner_id)
    resp = api_client.patch_settlement(
        project_id, contract_id, payload, headers
    )
    return get_success_data(resp)


__all__ = [
    "t_after",
    # Tier 0
    "create_project",
    "add_milestone",
    "add_full_milestones",
    "activate_project",
    "create_approved_vendor",
    "create_offered_quote",
    "create_draft_contract",
    "send_for_negotiation",
    "sign_contract",
    "emit_esign_completed",
    "accept_signature",
    "get_contract",
    "get_project",
    "get_vendor",
    "get_settlement",
    "list_audit_entries",
    # Tier 1
    "drive_contract_to_accepted",
    # Tier 2
    "setup_project_in_planning",
    "setup_project_in_execution",
    "setup_project_in_settlement",
    "advance_clock_past_ceremony",
    # Tier 3
    "create_settlement_for_contract",
    "confirm_settlement",
    "finalize_settlement",
    "drive_settlement_to_finalized",
    "setup_project_with_one_contract_accepted",
    # Tier 4
    "create_change_order",
    "approve_change_order",
    "add_two_change_orders_with_known_order",
    # Tier 5
    "create_timeline_slot",
    "setup_project_with_n_accepted_vendors",
    # Tier 6
    "create_guest",
    "rsvp_confirm",
    "setup_intimate_project_with_confirmed_party_size",
    # Tier 7
    "setup_settlement_dual_variant_scenario",
    "setup_two_finalized_settlements_for_vendor",
    "setup_project_in_settlement_with_one_finalized_and_one_terminated",
    # Tier 8
    "patch_guest",
    "patch_settlement",
]
