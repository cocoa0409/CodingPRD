"""Composite setup helpers for the builder-warranty domain (PRD §3 workflows).

Every helper builds its preconditions from scratch against a fresh server using
only PRD-declared endpoints, and uses the lenient get_success_data() validator
so setup failures surface as clear "Setup failed" errors.

Identity threading: after creating an entity-backed resource (Homeowner /
TradePartner), ownership-gated calls in the same chain use
make_homeowner_headers(entity["id"]) / make_trade_partner_headers(entity["id"]),
never the shared TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    assess_denial_payload,
    assess_warrantable_payload,
    create_administrator_claim_payload,
    create_chargeback_payload,
    create_home_payload,
    create_homeowner_payload,
    create_service_request_payload,
    create_trade_partner_payload,
    create_work_order_payload,
)
from .test_users import TEST_USERS, make_homeowner_headers, make_trade_partner_headers

MANAGER = TEST_USERS["manager_headers"]
REP = TEST_USERS["rep_headers"]
FINANCE = TEST_USERS["finance_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ─── Tier 1: master data ───────────────────────────────

def create_homeowner(**overrides) -> dict:
    """Register a homeowner (PRD §3.1). Returns the created Homeowner."""
    resp = api_client.create_homeowner(create_homeowner_payload(**overrides), MANAGER)
    return get_success_data(resp, 201)


def create_home(homeowner_id: str, **overrides) -> dict:
    """Create a warranted home (PRD §3.1); the reserve is auto-created."""
    resp = api_client.create_home(create_home_payload(homeowner_id, **overrides), MANAGER)
    return get_success_data(resp, 201)


def setup_home(**home_overrides):
    """Homeowner + home. Returns (homeowner, home)."""
    homeowner = create_homeowner(**home_overrides.pop("homeowner_overrides", {}))
    home = create_home(homeowner["id"], **home_overrides)
    return homeowner, home


def create_trade_partner(**overrides) -> dict:
    """Register a subcontractor (PRD §3.1). Returns the created TradePartner."""
    resp = api_client.create_trade_partner(
        create_trade_partner_payload(**overrides), MANAGER
    )
    return get_success_data(resp, 201)


# ─── Tier 1: clock and sweep ───────────────────────────

def set_clock(to_iso8601: str) -> dict:
    """Set the logical clock (PRD §2.4). Returns {current_utc}."""
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, MANAGER)
    return get_success_data(resp, 200)


def run_sweep() -> dict:
    """Run the operations checkpoint (PRD §3.7). Returns the sweep counts."""
    resp = api_client.run_sweep(MANAGER)
    return get_success_data(resp, 200)


# ─── Tier 2: service request lifecycle ─────────────────

def file_service_request(home_id: str, homeowner_id: str, **overrides) -> dict:
    """Homeowner intake of a service request (PRD §3.2). Returns RECEIVED request."""
    resp = api_client.create_service_request(
        create_service_request_payload(home_id, **overrides),
        make_homeowner_headers(homeowner_id),
    )
    return get_success_data(resp, 201)


def assess_request(request_id: str, payload: dict) -> dict:
    """WarrantyRep triage (PRD §3.2). Returns the updated request."""
    resp = api_client.assess_service_request(request_id, payload, REP)
    return get_success_data(resp, 200)


def create_approved_request(home_id: str, homeowner_id: str, **overrides) -> dict:
    """Intake + warrantable assess. Returns the APPROVED request."""
    request = file_service_request(home_id, homeowner_id, **overrides)
    return assess_request(request["id"], assess_warrantable_payload())


def create_denied_request(home_id: str, homeowner_id: str, **overrides) -> dict:
    """Intake + non-warrantable assess with reason + education packet (PRD §3.2).
    Returns the DENIED request."""
    denial_keys = {"denial_reason_code", "education_packet_code"}
    denial_overrides = {k: overrides.pop(k) for k in list(overrides) if k in denial_keys}
    request = file_service_request(home_id, homeowner_id, **overrides)
    return assess_request(request["id"], assess_denial_payload(**denial_overrides))


def dispute_request(request_id: str, homeowner_id: str, dispute_reason: str) -> dict:
    """Homeowner dispute of a denial (PRD §3.5). Returns the DISPUTED request."""
    resp = api_client.dispute_service_request(
        request_id,
        {"dispute_reason": dispute_reason},
        make_homeowner_headers(homeowner_id),
    )
    return get_success_data(resp, 200)


def resolve_dispute(request_id: str, outcome: str, resolution_notes: str) -> dict:
    """WarrantyManager dispute resolution (PRD §3.5). Returns the updated request."""
    resp = api_client.resolve_dispute(
        request_id, {"outcome": outcome, "resolution_notes": resolution_notes}, MANAGER
    )
    return get_success_data(resp, 200)


# ─── Tier 2/3: dispatch, completion, verification ──────

def dispatch_work_order(service_request_id: str, trade_partner_id: str, **overrides) -> dict:
    """Dispatch a trade partner to an APPROVED request (PRD §3.3).
    Returns the SCHEDULED work order."""
    resp = api_client.create_work_order(
        create_work_order_payload(service_request_id, trade_partner_id, **overrides), REP
    )
    return get_success_data(resp, 201)


def complete_work_order(work_order_id: str, trade_partner_id: str, actual_cost_cents: int) -> dict:
    """Trade partner marks the visit complete (PRD §3.4). Returns COMPLETED order."""
    resp = api_client.complete_work_order(
        work_order_id,
        {"actual_cost_cents": actual_cost_cents},
        make_trade_partner_headers(trade_partner_id),
    )
    return get_success_data(resp, 200)


def verify_work_order(work_order_id: str, homeowner_id: str, outcome="ACCEPT", **overrides) -> dict:
    """Homeowner verifies completed work (PRD §3.4). Returns the updated order."""
    payload = {"outcome": outcome}
    payload.update(overrides)
    resp = api_client.verify_work_order(
        work_order_id, payload, make_homeowner_headers(homeowner_id)
    )
    return get_success_data(resp, 200)


def setup_dispatched_work_order(
    item_category="PLUMBING",
    severity="STANDARD",
    trade="PLUMBING",
    window_start="2026-08-10T09:00:00Z",
    window_end="2026-08-10T11:00:00Z",
    estimated_cost_cents=150_000,
    defect_responsibility="SUBCONTRACTOR",
    request_description="Kitchen supply line leak",
    **home_overrides,
) -> dict:
    """Full chain: homeowner + home + approved request + trade partner +
    SCHEDULED work order. Returns a context dict."""
    homeowner, home = setup_home(**home_overrides)
    partner = create_trade_partner(trade=trade)
    request = create_approved_request(
        home["id"],
        homeowner["id"],
        item_category=item_category,
        severity=severity,
        description=request_description,
    )
    work_order = dispatch_work_order(
        request["id"],
        partner["id"],
        window_start=window_start,
        window_end=window_end,
        estimated_cost_cents=estimated_cost_cents,
        defect_responsibility=defect_responsibility,
    )
    return {
        "homeowner": homeowner,
        "home": home,
        "partner": partner,
        "request": request,
        "work_order": work_order,
    }


def setup_completed_work_order(actual_cost_cents=110_000, **kwargs) -> dict:
    """setup_dispatched_work_order + completion by the dispatched partner."""
    ctx = setup_dispatched_work_order(**kwargs)
    ctx["work_order"] = complete_work_order(
        ctx["work_order"]["id"], ctx["partner"]["id"], actual_cost_cents
    )
    return ctx


def setup_pending_followup_request(actual_cost_cents=60_000, **kwargs) -> dict:
    """Completed + homeowner-ACCEPTED work order; the parent request has bubbled
    up to PENDING_FOLLOWUP (PRD §3.4)."""
    ctx = setup_completed_work_order(actual_cost_cents=actual_cost_cents, **kwargs)
    ctx["work_order"] = verify_work_order(
        ctx["work_order"]["id"], ctx["homeowner"]["id"], outcome="ACCEPT"
    )
    return ctx


def setup_closed_request(satisfaction_score=5, **kwargs) -> dict:
    """Full lifecycle through CLOSED via the follow-up call (PRD §3.5)."""
    ctx = setup_pending_followup_request(**kwargs)
    resp = api_client.follow_up_service_request(
        ctx["request"]["id"],
        {"satisfaction_score": satisfaction_score, "notes": "All good"},
        REP,
    )
    ctx["request"] = get_success_data(resp, 200)
    return ctx


# ─── Tier 3: chargebacks ───────────────────────────────

def issue_chargeback(work_order_id: str) -> dict:
    """Issue a provisional chargeback on a SCHEDULED, SUBCONTRACTOR work order
    (PRD §3.6). Returns the ISSUED chargeback."""
    resp = api_client.create_chargeback(create_chargeback_payload(work_order_id), REP)
    return get_success_data(resp, 201)


def setup_issued_chargeback(**kwargs) -> dict:
    """setup_dispatched_work_order + issued chargeback. Context gains "chargeback"."""
    ctx = setup_dispatched_work_order(**kwargs)
    ctx["chargeback"] = issue_chargeback(ctx["work_order"]["id"])
    return ctx


def approve_chargeback(chargeback_id: str, **payload_overrides) -> dict:
    """Manager approval of an ISSUED chargeback (PRD §3.6)."""
    resp = api_client.approve_chargeback(chargeback_id, payload_overrides, MANAGER)
    return get_success_data(resp, 200)


def contest_chargeback(chargeback_id: str, trade_partner_id: str,
                       contest_reason="Not our scope") -> dict:
    """Charged partner contests within the window (PRD §3.6)."""
    resp = api_client.contest_chargeback(
        chargeback_id,
        {"contest_reason": contest_reason},
        make_trade_partner_headers(trade_partner_id),
    )
    return get_success_data(resp, 200)


def resolve_chargeback(chargeback_id: str, outcome: str, **payload_overrides) -> dict:
    """Manager resolution of a CONTESTED chargeback (PRD §3.6)."""
    payload = {"outcome": outcome}
    payload.update(payload_overrides)
    resp = api_client.resolve_chargeback(chargeback_id, payload, MANAGER)
    return get_success_data(resp, 200)


def record_payment(chargeback_id: str, amount_cents: int, **payload_overrides) -> dict:
    """FinanceAdmin cash application (PRD §3.6). Returns the updated chargeback."""
    payload = {"amount_cents": amount_cents}
    payload.update(payload_overrides)
    resp = api_client.record_payment(chargeback_id, payload, FINANCE)
    return get_success_data(resp, 200)


def setup_approved_chargeback(**kwargs) -> dict:
    """Issued chargeback + manager approval."""
    ctx = setup_issued_chargeback(**kwargs)
    ctx["chargeback"] = approve_chargeback(ctx["chargeback"]["id"])
    return ctx


def setup_contested_chargeback(contest_reason="Not our scope", **kwargs) -> dict:
    """Issued chargeback contested by the charged partner inside the window."""
    ctx = setup_issued_chargeback(**kwargs)
    ctx["chargeback"] = contest_chargeback(
        ctx["chargeback"]["id"], ctx["partner"]["id"], contest_reason
    )
    return ctx


# ─── Tier 4: reserves and ledger ───────────────────────

def get_reserve_for_home(home_id: str) -> dict:
    """Fetch a home's 1:1 reserve via the collection filter (PRD §2.8)."""
    resp = api_client.list_warranty_reserves(FINANCE, params={"home_id": home_id})
    data, meta = validate_paginated(resp)
    assert len(data) == 1, (
        f"Expected exactly one reserve for home {home_id}, got {len(data)}"
    )
    return data[0]


def get_reserve(reserve_id: str) -> dict:
    resp = api_client.get_warranty_reserve(reserve_id, FINANCE)
    return get_success_data(resp, 200)


def list_reserve_entries(reserve_id: str, kind: str = None) -> list:
    params = {"kind": kind} if kind else None
    resp = api_client.list_reserve_entries(reserve_id, FINANCE, params=params)
    data, _meta = validate_paginated(resp)
    return data


def post_reserve_adjustment(reserve_id: str, payload: dict) -> dict:
    """OCC-guarded reserve posting (PRD §2.9/§3.7). Returns the new entry."""
    resp = api_client.post_reserve_adjustment(reserve_id, payload, FINANCE)
    return get_success_data(resp, 201)


def setup_accrued_reserve(sale_price_cents=40_000_000, closing_date="2026-06-01",
                          clock="2026-08-01T00:00:00Z", **home_overrides) -> dict:
    """Home + reserve with the sweep run at `clock`, posting the due monthly
    accruals (PRD §3.7). Returns {homeowner, home, reserve, sweep}."""
    homeowner, home = setup_home(
        sale_price_cents=sale_price_cents, closing_date=closing_date, **home_overrides
    )
    set_clock(clock)
    sweep = run_sweep()
    reserve = get_reserve_for_home(home["id"])
    return {"homeowner": homeowner, "home": home, "reserve": reserve, "sweep": sweep}


# ─── Tier 5: administrator claims ──────────────────────

def setup_admin_claim(
    warranty_program="THIRD_PARTY_ADMINISTERED",
    item_category="FOUNDATION",
    severity="URGENT",
    claimed_amount_cents=900_000,
    sale_price_cents=50_000_000,
    **home_overrides,
) -> dict:
    """THIRD_PARTY home + APPROVED STRUCTURAL request + SUBMITTED claim
    (PRD §3.8). Returns a context dict including "claim"."""
    homeowner, home = setup_home(
        warranty_program=warranty_program,
        sale_price_cents=sale_price_cents,
        **home_overrides,
    )
    request = create_approved_request(
        home["id"],
        homeowner["id"],
        item_category=item_category,
        severity=severity,
        description="Foundation crack, garage wall",
    )
    resp = api_client.create_administrator_claim(
        create_administrator_claim_payload(
            request["id"], claimed_amount_cents=claimed_amount_cents
        ),
        REP,
    )
    claim = get_success_data(resp, 201)
    return {
        "homeowner": homeowner,
        "home": home,
        "request": request,
        "claim": claim,
    }


def decide_claim(claim_id: str, outcome: str, **payload_overrides) -> dict:
    """WarrantyAdministrator decision on a SUBMITTED claim (PRD §3.8)."""
    payload = {"outcome": outcome}
    payload.update(payload_overrides)
    resp = api_client.decide_administrator_claim(claim_id, payload, ADMIN)
    return get_success_data(resp, 200)
