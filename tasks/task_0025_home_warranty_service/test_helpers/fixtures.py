"""Composite setup helpers for the Home Warranty Service benchmark.

Every helper builds its preconditions from scratch through PRD-declared endpoints
(see PRD §3.x). The runner restarts the API server before every individual pytest
test, so each test starts from an empty database — no entities, no clock state.

These helpers use `get_success_data()` (lenient validator) so a setup failure
surfaces as a clear "Setup failed" trace rather than a cryptic assertion deep
inside a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_contract_package_payload,
    create_customer_payload,
    create_contract_payload,
    create_covered_item_payload,
    create_claim_payload,
    assess_claim_payload,
    reject_claim_payload,
    dispatch_claim_payload,
    resolve_claim_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
)


_ADMIN_HEADERS = TEST_USERS["platform_admin_headers"]
_DISPATCHER_HEADERS = TEST_USERS["dispatcher_headers"]
_TECHNICIAN_HEADERS = TEST_USERS["technician_headers"]
_ANON_HEADERS: dict = {}


# ─── Tier 0: clock control ──────────────────────────────────────


def set_clock(iso8601: str) -> dict:
    """Move the server's logical clock to the given ISO 8601 UTC instant (PRD §3.9)."""
    res = api_client.set_clock(set_clock_payload(iso8601), _ADMIN_HEADERS)
    return get_success_data(res)


def tick_clock() -> dict:
    """Fire eligible time-driven auto-transitions (PRD §3.9)."""
    res = api_client.tick_clock(_ADMIN_HEADERS)
    return get_success_data(res)


# ─── Tier 1: package, customer creation ─────────────────────────


def create_package(**overrides) -> dict:
    """POST /contract-packages as PlatformAdmin (PRD §3.1)."""
    res = api_client.create_contract_package(
        create_contract_package_payload(**overrides), _ADMIN_HEADERS
    )
    return get_success_data(res)


def create_default_package(**overrides) -> dict:
    """Standard PLUS-style package: premium 50000, service_fee 7500, cap 25000,
    share 0.20, return-visit window 30 days, max 5 items.
    All Difficulty/Corner instances default to this shape unless they override.
    """
    defaults = {
        "code": "PLUS",
        "name": "Plus Package",
        "annual_premium_cents": 50_000,
        "service_fee_cents": 7_500,
        "copay_cap_cents": 25_000,
        "copay_share_pct": 0.20,
        "return_visit_window_days": 30,
        "max_covered_items": 5,
    }
    defaults.update(overrides)
    return create_package(**defaults)


def register_customer(**overrides) -> dict:
    """POST /customers as Anonymous (PRD §3.1)."""
    res = api_client.register_customer(create_customer_payload(**overrides), _ANON_HEADERS)
    return get_success_data(res)


# ─── Tier 2: contracts ──────────────────────────────────────────


def create_pending_contract(customer: dict, package: dict) -> dict:
    """POST /contracts as the customer (PRD §3.2). Returns PENDING_PAYMENT contract."""
    headers = make_customer_headers(customer["id"])
    res = api_client.create_contract(
        create_contract_payload(customer["id"], package["id"]), headers
    )
    return get_success_data(res)


def activate_contract(contract: dict) -> dict:
    """POST /contracts/{id}/activate as PlatformAdmin (PRD §3.2). Returns ACTIVE contract."""
    res = api_client.activate_contract(contract["id"], _ADMIN_HEADERS)
    return get_success_data(res)


def setup_active_contract(activate_at: str = "2026-01-01T00:00:00Z",
                          **package_overrides) -> tuple:
    """Common composite: package + customer + activated contract.

    Sets the clock to `activate_at` before activation, so coverage_start_utc is
    deterministic. Returns (package, customer, active_contract).
    """
    set_clock(activate_at)
    package = create_default_package(**package_overrides)
    customer = register_customer()
    pending = create_pending_contract(customer, package)
    active = activate_contract(pending)
    return package, customer, active


def setup_active_contract_with_item(activate_at: str = "2026-01-01T00:00:00Z",
                                    category: str = "HVAC",
                                    pre_existing_flag: bool = False,
                                    **package_overrides) -> tuple:
    """Active contract + one CoveredItem (default HVAC). Returns
    (package, customer, contract, item).
    """
    package, customer, contract = setup_active_contract(
        activate_at=activate_at, **package_overrides
    )
    headers = make_customer_headers(customer["id"])
    res = api_client.create_covered_item(
        create_covered_item_payload(
            contract["id"], category=category, brand="B", model="M",
            install_year=2022, pre_existing_flag=pre_existing_flag,
        ),
        headers,
    )
    item = get_success_data(res)
    return package, customer, contract, item


# ─── Tier 3: claim lifecycle ────────────────────────────────────


def file_claim(contract: dict, customer: dict, item: dict,
               issue: str = "Stopped working") -> dict:
    """POST /claims as the contract's customer (PRD §3.4). Returns SUBMITTED claim."""
    headers = make_customer_headers(customer["id"])
    res = api_client.create_claim(
        create_claim_payload(contract["id"], item["id"], issue_summary=issue),
        headers,
    )
    return get_success_data(res)


def assess_claim(claim: dict, repair_cost_cents: int) -> dict:
    """POST /claims/{id}/assess as Dispatcher (PRD §3.4). Returns ASSESSED claim."""
    res = api_client.assess_claim(
        claim["id"], assess_claim_payload(repair_cost_cents), _DISPATCHER_HEADERS
    )
    return get_success_data(res)


def reject_claim(claim: dict, rejection_reason: str = "NOT_COVERED_CATEGORY") -> dict:
    """POST /claims/{id}/reject as Dispatcher (PRD §3.4). Returns REJECTED claim."""
    res = api_client.reject_claim(
        claim["id"], reject_claim_payload(rejection_reason), _DISPATCHER_HEADERS
    )
    return get_success_data(res)


def dispatch_claim(claim: dict, technician_id: str, scheduled_utc: str) -> dict:
    """POST /claims/{id}/dispatch as Dispatcher (PRD §3.5). Returns DISPATCHED claim."""
    res = api_client.dispatch_claim(
        claim["id"],
        dispatch_claim_payload(technician_id, scheduled_utc),
        _DISPATCHER_HEADERS,
    )
    return get_success_data(res)


def get_dispatch_for_claim(claim_id: str) -> dict:
    """List dispatches filtered by claim_id and return the (single) result.

    The dispatch transition creates exactly one Dispatch per claim (PRD §3.5).
    """
    res = api_client.list_dispatches(_DISPATCHER_HEADERS, params={"claim_id": claim_id})
    data = get_success_data(res)
    # Standard envelope: data is list when response_type == "array".
    if isinstance(data, list):
        items = data
    else:
        # Some test runners wrap; fall back to body['data'].
        items = data.get("data", data) if isinstance(data, dict) else []
    if not items:
        raise RuntimeError(f"No dispatch found for claim {claim_id}")
    return items[0]


def start_dispatch(dispatch: dict) -> dict:
    """POST /dispatches/{id}/start as Technician (PRD §3.5). Returns IN_PROGRESS dispatch."""
    res = api_client.start_dispatch(dispatch["id"], _TECHNICIAN_HEADERS)
    return get_success_data(res)


def complete_dispatch(dispatch: dict) -> dict:
    """POST /dispatches/{id}/complete as Technician (PRD §3.5). Returns COMPLETED dispatch."""
    res = api_client.complete_dispatch(dispatch["id"], _TECHNICIAN_HEADERS)
    return get_success_data(res)


def mark_dispatch_return_needed(dispatch: dict) -> dict:
    """POST /dispatches/{id}/mark-return-needed as Technician (PRD §3.5)."""
    res = api_client.mark_return_needed(dispatch["id"], _TECHNICIAN_HEADERS)
    return get_success_data(res)


def resolve_claim(claim: dict, actual_repair_cost_cents: int) -> dict:
    """POST /claims/{id}/resolve as Dispatcher (PRD §3.6). Returns RESOLVED claim."""
    res = api_client.resolve_claim(
        claim["id"], resolve_claim_payload(actual_repair_cost_cents), _DISPATCHER_HEADERS
    )
    return get_success_data(res)


def reopen_claim(claim: dict) -> dict:
    """POST /claims/{id}/reopen as Dispatcher (PRD §3.6). Returns ASSESSED claim."""
    res = api_client.reopen_claim(claim["id"], _DISPATCHER_HEADERS)
    return get_success_data(res)


# ─── Tier 4: full-lifecycle shortcuts ──────────────────────────


def walk_dispatch_to_completed(claim: dict, technician_id: str,
                                schedule_at: str,
                                start_at: str,
                                complete_at: str,
                                repair_cost_cents: int) -> tuple:
    """Drive a claim through ASSESSED→DISPATCHED→start→complete (no resolve).

    Returns (dispatched_claim, completed_dispatch). Setup helper for any test
    that needs a CoveredItem with last_dispatch_completed_utc stamped.
    """
    set_clock(schedule_at)  # ensure scheduled_utc >= clock_now
    dispatched = dispatch_claim(claim, technician_id, complete_at)
    dispatch = get_dispatch_for_claim(dispatched["id"])
    set_clock(start_at)
    start_dispatch(dispatch)
    set_clock(complete_at)
    completed_dispatch = complete_dispatch(dispatch)
    return dispatched, completed_dispatch


def setup_item_with_completed_dispatch(activate_at: str = "2026-01-01T00:00:00Z",
                                       complete_at: str = "2026-02-01T10:00:00Z",
                                       schedule_at: str = "2026-02-01T08:00:00Z",
                                       start_at: str = "2026-02-01T09:30:00Z",
                                       repair_cost_cents: int = 20_000,
                                       resolve_actual_cents: int = 20_000,
                                       resolve_first_claim: bool = True,
                                       **package_overrides) -> tuple:
    """Build a CoveredItem whose last_dispatch_completed_utc == `complete_at`.

    Walks the full first-claim cycle: file → assess → dispatch → start →
    complete. If `resolve_first_claim` is True, also resolves to clear the
    claim out of in-flight state. Useful for is_return_visit tests where a
    later claim/dispatch will need to see a prior completion stamp.

    Returns (package, customer, contract, item, completed_dispatch).
    """
    package, customer, contract, item = setup_active_contract_with_item(
        activate_at=activate_at, **package_overrides
    )
    claim = file_claim(contract, customer, item, issue="First failure")
    assess_claim(claim, repair_cost_cents)
    _, completed = walk_dispatch_to_completed(
        claim,
        technician_id="tech-A1",
        schedule_at=schedule_at,
        start_at=start_at,
        complete_at=complete_at,
        repair_cost_cents=repair_cost_cents,
    )
    if resolve_first_claim:
        resolve_claim(claim, resolve_actual_cents)
    return package, customer, contract, item, completed


# ─── Tier 5: contract auto-transitions ──────────────────────────


def setup_expiring_soon_contract(activate_at: str = "2026-01-01T00:00:00Z",
                                  tick_at: str = "2026-12-12T00:00:00Z",
                                  **package_overrides) -> tuple:
    """Active contract auto-transitioned into EXPIRING_SOON via /_clock/tick.

    PRD §3.8: when clock_now >= coverage_end_utc - 30 days, /_clock/tick fires
    ACTIVE → EXPIRING_SOON on eligible contracts. With activate_at = 2026-01-01,
    coverage_end_utc = 2027-01-01, so any tick_at on or after 2026-12-02 will
    trigger the transition. Default tick_at = 2026-12-12 ⇒ D = 20 days remaining
    (early-renewal tier).

    Returns (package, customer, expiring_soon_contract).
    """
    package, customer, contract = setup_active_contract(
        activate_at=activate_at, **package_overrides
    )
    set_clock(tick_at)
    tick_clock()
    # Re-read the contract to capture the EXPIRING_SOON status + bumped version.
    res = api_client.get_contract(contract["id"], _ADMIN_HEADERS)
    contract_es = get_success_data(res)
    return package, customer, contract_es


def setup_expired_contract(activate_at: str = "2026-01-01T00:00:00Z",
                            tick_at: str = "2027-02-01T00:00:00Z",
                            **package_overrides) -> tuple:
    """Active contract auto-transitioned to EXPIRED via tick past coverage_end_utc.

    Returns (package, customer, expired_contract).
    """
    package, customer, contract = setup_active_contract(
        activate_at=activate_at, **package_overrides
    )
    set_clock(tick_at)
    tick_clock()
    res = api_client.get_contract(contract["id"], _ADMIN_HEADERS)
    expired = get_success_data(res)
    return package, customer, expired


def setup_expired_contract_with_item(activate_at: str = "2026-01-01T00:00:00Z",
                                     tick_at: str = "2027-02-01T00:00:00Z",
                                     category: str = "OVEN",
                                     **package_overrides) -> tuple:
    """Active contract with one CoveredItem registered, then expired via tick.

    Item is registered BEFORE the tick (while contract is still ACTIVE), so the
    CoveredItem row exists by the time we test against the expired contract.

    Returns (package, customer, expired_contract, item).
    """
    package, customer, contract, item = setup_active_contract_with_item(
        activate_at=activate_at, category=category, **package_overrides
    )
    set_clock(tick_at)
    tick_clock()
    res = api_client.get_contract(contract["id"], _ADMIN_HEADERS)
    expired = get_success_data(res)
    return package, customer, expired, item


# ─── Tier 6: claim-in-flight scenarios for cancel-blocking ──────


def setup_active_contract_with_dispatched_claim(
    activate_at: str = "2026-01-01T00:00:00Z",
    schedule_at: str = "2026-02-01T08:00:00Z",
    scheduled_utc: str = "2026-02-01T09:00:00Z",
    repair_cost_cents: int = 10_000,
    technician_id: str = "tech-A",
    **package_overrides,
) -> tuple:
    """Active contract with one ClaimTicket in DISPATCHED status.

    Returns (package, customer, contract, item, claim, dispatch).
    Useful for cancel-blocked tests and any test asserting in-flight claim states.
    """
    package, customer, contract, item = setup_active_contract_with_item(
        activate_at=activate_at, **package_overrides
    )
    claim = file_claim(contract, customer, item, issue="Open claim")
    assess_claim(claim, repair_cost_cents)
    set_clock(schedule_at)
    dispatched = dispatch_claim(claim, technician_id, scheduled_utc)
    dispatch = get_dispatch_for_claim(dispatched["id"])
    return package, customer, contract, item, dispatched, dispatch


def setup_dispatch_in_progress_after_start(
    activate_at: str = "2026-01-01T00:00:00Z",
    schedule_at: str = "2026-02-01T08:00:00Z",
    scheduled_utc: str = "2026-02-01T09:00:00Z",
    start_at: str = "2026-02-01T09:30:00Z",
    technician_id: str = "tech-IP",
    repair_cost_cents: int = 10_000,
    **package_overrides,
) -> tuple:
    """Claim DISPATCHED + linked Dispatch transitioned SCHEDULED→IN_PROGRESS.

    Returns (package, customer, contract, item, claim, dispatch_in_progress).
    """
    package, customer, contract, item, claim, dispatch = setup_active_contract_with_dispatched_claim(
        activate_at=activate_at,
        schedule_at=schedule_at,
        scheduled_utc=scheduled_utc,
        repair_cost_cents=repair_cost_cents,
        technician_id=technician_id,
        **package_overrides,
    )
    set_clock(start_at)
    in_progress = start_dispatch(dispatch)
    return package, customer, contract, item, claim, in_progress


def setup_dispatch_return_needed(
    activate_at: str = "2026-01-01T00:00:00Z",
    schedule_at: str = "2026-02-01T08:00:00Z",
    scheduled_utc: str = "2026-02-01T09:00:00Z",
    start_at: str = "2026-02-01T09:30:00Z",
    technician_id: str = "tech-RN",
    repair_cost_cents: int = 20_000,
    **package_overrides,
) -> tuple:
    """Claim DISPATCHED + Dispatch flagged RETURN_NEEDED, ready for /claims/{id}/reopen.

    Returns (package, customer, contract, item, claim, dispatch_return_needed).
    """
    package, customer, contract, item, claim, in_progress = setup_dispatch_in_progress_after_start(
        activate_at=activate_at,
        schedule_at=schedule_at,
        scheduled_utc=scheduled_utc,
        start_at=start_at,
        technician_id=technician_id,
        repair_cost_cents=repair_cost_cents,
        **package_overrides,
    )
    rn = mark_dispatch_return_needed(in_progress)
    return package, customer, contract, item, claim, rn
