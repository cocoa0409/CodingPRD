"""Composite setup helpers for multi-step MSP Managed IT test prerequisites.

Each fixture builds its preconditions from scratch using only PRD-declared
endpoints; the test harness restarts the server before every test, so every
fixture starts against an empty database.

Identity threading (PRD §2.1):
- ServiceManager / Dispatcher / AccountManager are opaque; the shared TEST_USERS
  headers are sufficient.
- Technician is entity_backed:Technician — ownership-gated calls (arrive,
  complete, patch start/report) MUST use make_technician_headers(<Technician.id>).
- ClientContact is entity_backed:Client — ownership-gated calls (accept /
  request-revision / open own-client ticket) MUST use
  make_client_contact_headers(<Client.id>).

The logical clock starts at 2026-05-01T00:00:00Z (PRD §2.4). Fixtures that
require a specific time set the clock explicitly via set_clock().
"""
from typing import Optional, List, Tuple
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_client_payload,
    create_site_payload,
    create_technician_payload,
    create_contract_payload,
    create_asset_payload,
    create_patch_job_payload,
    create_ticket_payload,
    create_dispatch_payload,
    create_seat_adjustment_payload,
    create_quote_payload,
    create_procurement_order_payload,
    create_invoice_payload,
)
from .test_users import (
    TEST_USERS,
    make_technician_headers,
    make_client_contact_headers,
)


# --- Tier 0: Logical clock -------------------------------------------------

def set_clock(iso8601: str) -> dict:
    """Advance/rewind the server's logical clock (ServiceManager)."""
    return get_success_data(
        api_client.set_clock(iso8601, TEST_USERS["service_manager_headers"])
    )


# --- Tier 1: Single-entity creation ---------------------------------------

def create_client(**overrides) -> dict:
    """Register a client (ServiceManager). Returns the Client record."""
    payload = create_client_payload(**overrides)
    return get_success_data(
        api_client.create_client(payload, TEST_USERS["service_manager_headers"])
    )


def create_site(client_id: str, **overrides) -> dict:
    """Create a site under a client (ServiceManager)."""
    payload = create_site_payload(client_id, **overrides)
    return get_success_data(
        api_client.create_site(payload, TEST_USERS["service_manager_headers"])
    )


def create_technician(**overrides) -> dict:
    """Register a technician (ServiceManager)."""
    payload = create_technician_payload(**overrides)
    return get_success_data(
        api_client.create_technician(payload, TEST_USERS["service_manager_headers"])
    )


def create_contract(client_id: str, **overrides) -> dict:
    """Create a DRAFT managed-services contract (ServiceManager)."""
    payload = create_contract_payload(client_id, **overrides)
    return get_success_data(
        api_client.create_contract(payload, TEST_USERS["service_manager_headers"])
    )


def activate_contract(contract_id: str) -> dict:
    """Activate a DRAFT contract (ServiceManager). Returns the ACTIVE contract."""
    return get_success_data(
        api_client.activate_contract(contract_id, TEST_USERS["service_manager_headers"])
    )


def terminate_contract(contract_id: str) -> dict:
    """Terminate an ACTIVE contract (ServiceManager)."""
    return get_success_data(
        api_client.terminate_contract(contract_id, TEST_USERS["service_manager_headers"])
    )


def offboard_client(client_id: str) -> dict:
    """Offboard an ACTIVE client (ServiceManager); triggers cascade per PRD §2.6."""
    return get_success_data(
        api_client.offboard_client(client_id, TEST_USERS["service_manager_headers"])
    )


def create_asset(client_id: str, site_id: str, **overrides) -> dict:
    """Add an asset to inventory in UNMONITORED state (ServiceManager)."""
    payload = create_asset_payload(client_id, site_id, **overrides)
    return get_success_data(
        api_client.create_asset(payload, TEST_USERS["service_manager_headers"])
    )


def assign_asset_to_contract(asset_id: str, contract_id: str) -> dict:
    """Move UNMONITORED asset → ACTIVE against a contract (ServiceManager)."""
    return get_success_data(
        api_client.assign_contract_to_asset(
            asset_id, {"contract_id": contract_id},
            TEST_USERS["service_manager_headers"],
        )
    )


def unassign_asset(asset_id: str) -> dict:
    """Move ACTIVE asset → UNMONITORED (ServiceManager)."""
    return get_success_data(
        api_client.unassign_contract_from_asset(
            asset_id, TEST_USERS["service_manager_headers"],
        )
    )


def create_patch_job(asset_id: str, window_start: str, window_end: str,
                     as_role: str = "dispatcher", **overrides) -> dict:
    """Schedule a patch job on an asset. as_role: 'dispatcher' or 'technician'."""
    payload = create_patch_job_payload(window_start, window_end, **overrides)
    if as_role == "dispatcher":
        headers = TEST_USERS["dispatcher_headers"]
    else:
        raise ValueError("create_patch_job only supports dispatcher role in fixtures")
    return get_success_data(
        api_client.create_patch_job(asset_id, payload, headers)
    )


def start_patch_job(patch_job_id: str, technician_id: str) -> dict:
    """Technician (owning the patch work) starts a SCHEDULED patch job."""
    return get_success_data(
        api_client.start_patch_job(patch_job_id, make_technician_headers(technician_id))
    )


def report_patch_job(patch_job_id: str, technician_id: str,
                     outcome: str, **overrides) -> dict:
    """Technician reports a RUNNING patch job's outcome."""
    payload = {"outcome": outcome}
    payload.update(overrides)
    return get_success_data(
        api_client.report_patch_job(
            patch_job_id, payload, make_technician_headers(technician_id),
        )
    )


def create_ticket(client_id: str, contract_id: str, **overrides) -> dict:
    """Open a ticket against an ACTIVE contract (ServiceManager)."""
    payload = create_ticket_payload(client_id, contract_id, **overrides)
    return get_success_data(
        api_client.create_ticket(payload, TEST_USERS["service_manager_headers"])
    )


def assign_ticket(ticket_id: str, technician_id: str) -> dict:
    """Dispatcher assigns a NEW ticket to a technician."""
    return get_success_data(
        api_client.assign_ticket(
            ticket_id, {"technician_id": technician_id},
            TEST_USERS["dispatcher_headers"],
        )
    )


def create_dispatch(ticket_id: str, technician_id: str, mode: str,
                    scheduled_start: str, scheduled_end: str, **overrides) -> dict:
    """Dispatcher creates a dispatch on an IN_PROGRESS ticket."""
    payload = create_dispatch_payload(
        technician_id, mode, scheduled_start, scheduled_end, **overrides,
    )
    return get_success_data(
        api_client.create_dispatch(
            ticket_id, payload, TEST_USERS["dispatcher_headers"],
        )
    )


def complete_dispatch(dispatch_id: str, technician_id: str,
                      logged_minutes: int) -> dict:
    """Technician completes a dispatch (from ON_SITE for ONSITE, SCHEDULED for
    REMOTE) with logged_minutes of labor."""
    return get_success_data(
        api_client.complete_dispatch(
            dispatch_id, {"logged_minutes": logged_minutes},
            make_technician_headers(technician_id),
        )
    )


def arrive_dispatch(dispatch_id: str, technician_id: str) -> dict:
    """Technician marks an ONSITE dispatch arrived (SCHEDULED → ON_SITE)."""
    return get_success_data(
        api_client.arrive_dispatch(
            dispatch_id, make_technician_headers(technician_id),
        )
    )


def resolve_ticket(ticket_id: str) -> dict:
    """Dispatcher resolves an IN_PROGRESS ticket."""
    return get_success_data(
        api_client.resolve_ticket(ticket_id, TEST_USERS["dispatcher_headers"])
    )


def reopen_ticket(ticket_id: str) -> dict:
    """Dispatcher reopens a RESOLVED ticket."""
    return get_success_data(
        api_client.reopen_ticket(ticket_id, TEST_USERS["dispatcher_headers"])
    )


def create_seat_adjustment(contract_id: str, delta: int, effective_at: str,
                           expected_contract_version: int, **overrides) -> dict:
    """Record a SeatAdjustment against a contract (ServiceManager)."""
    payload = create_seat_adjustment_payload(
        delta, effective_at, expected_contract_version, **overrides,
    )
    return get_success_data(
        api_client.create_seat_adjustment(
            contract_id, payload, TEST_USERS["service_manager_headers"],
        )
    )


def create_invoice(contract_id: str, variant: str) -> dict:
    """Generate a PROVISIONAL or FINAL invoice (ServiceManager)."""
    return get_success_data(
        api_client.create_invoice(
            contract_id, create_invoice_payload(variant),
            TEST_USERS["service_manager_headers"],
        )
    )


def create_quote(client_id: str, quote_type: str, line_items: list,
                 **overrides) -> dict:
    """AccountManager creates a quote (DRAFT)."""
    payload = create_quote_payload(client_id, quote_type, line_items, **overrides)
    return get_success_data(
        api_client.create_quote(payload, TEST_USERS["account_manager_headers"])
    )


def send_quote(quote_id: str) -> dict:
    """AccountManager sends a DRAFT quote."""
    return get_success_data(
        api_client.send_quote(quote_id, TEST_USERS["account_manager_headers"])
    )


def accept_quote(quote_id: str, client_id: str) -> dict:
    """ClientContact (owning the client) accepts a SENT quote."""
    return get_success_data(
        api_client.accept_quote(quote_id, make_client_contact_headers(client_id))
    )


def create_procurement_order(client_id: str, line_items: list,
                             **overrides) -> dict:
    """AccountManager creates a DRAFT procurement order."""
    payload = create_procurement_order_payload(client_id, line_items, **overrides)
    return get_success_data(
        api_client.create_procurement_order(
            payload, TEST_USERS["account_manager_headers"],
        )
    )


def place_procurement_order(order_id: str) -> dict:
    """AccountManager places a DRAFT order (debits credit)."""
    return get_success_data(
        api_client.place_procurement_order(
            order_id, TEST_USERS["account_manager_headers"],
        )
    )


def cancel_procurement_order(order_id: str) -> dict:
    """AccountManager cancels an order (refunds credit if placed)."""
    return get_success_data(
        api_client.cancel_procurement_order(
            order_id, TEST_USERS["account_manager_headers"],
        )
    )


# --- Tier 2: Composite preconditions ---------------------------------------

def setup_active_contract(client_overrides: Optional[dict] = None,
                          contract_overrides: Optional[dict] = None
                          ) -> Tuple[dict, dict]:
    """The most common preamble: create a client, create a SILVER-tier contract,
    and activate it. Returns (client, active_contract).

    The activated contract carries a bumped version (PRD §3.2) — read via
    `contract["version"]` if you need it for a seat-adjustment.
    """
    client = create_client(**(client_overrides or {}))
    contract = create_contract(client["id"], **(contract_overrides or {}))
    active_contract = activate_contract(contract["id"])
    return client, active_contract


def setup_active_contract_with_tech(**contract_kwargs) -> Tuple[dict, dict, dict]:
    """Active contract + a technician. Returns (client, contract, technician)."""
    client, contract = setup_active_contract(contract_overrides=contract_kwargs)
    tech = create_technician()
    return client, contract, tech


def setup_assigned_asset(seat_count: int = 5,
                        asset_type: str = "LAPTOP") -> Tuple[dict, dict, dict, dict]:
    """Client + site + active SILVER contract + one asset assigned (ACTIVE).
    Returns (client, site, contract, asset)."""
    client, contract = setup_active_contract(
        contract_overrides={"seat_count": seat_count},
    )
    site = create_site(client["id"])
    asset = create_asset(client["id"], site["id"], asset_type=asset_type)
    asset = assign_asset_to_contract(asset["id"], contract["id"])
    return client, site, contract, asset


def setup_ticket_in_progress(priority: str = "P3",
                             contract_kwargs: Optional[dict] = None
                             ) -> Tuple[dict, dict, dict, dict]:
    """Client + active contract + technician + IN_PROGRESS ticket assigned to
    that technician. Returns (client, contract, technician, ticket)."""
    client, contract, tech = setup_active_contract_with_tech(**(contract_kwargs or {}))
    ticket = create_ticket(client["id"], contract["id"], priority=priority)
    ticket = assign_ticket(ticket["id"], tech["id"])
    return client, contract, tech, ticket


# --- Tier 3: Lifecycle shortcuts ------------------------------------------

def setup_full_offboard_precondition() -> dict:
    """Depth-3 cascade precondition (PRD §2.6):
    client + site + active contract + ACTIVE asset + SCHEDULED patch job on
    asset + NEW ticket referencing the asset. Returns a dict of all created
    entities so the test can assert every hop of the offboard cascade.
    """
    client, site, contract, asset = setup_assigned_asset(seat_count=5)
    patch_job = create_patch_job(
        asset["id"],
        window_start="2026-05-10T00:00:00Z",
        window_end="2026-05-10T02:00:00Z",
    )
    ticket = get_success_data(
        api_client.create_ticket(
            create_ticket_payload(
                client["id"], contract["id"],
                priority="P3", subject="won't boot",
                asset_id=asset["id"],
            ),
            TEST_USERS["dispatcher_headers"],
        )
    )
    return {
        "client": client, "site": site, "contract": contract,
        "asset": asset, "patch_job": patch_job, "ticket": ticket,
    }


def setup_remote_dispatch_scheduled(logged_minutes: int = 90,
                                    priority: str = "P2"
                                    ) -> Tuple[dict, dict, dict, dict, dict]:
    """Client + active contract + technician + IN_PROGRESS ticket + SCHEDULED
    REMOTE dispatch flagged to resolve the ticket. Returns
    (client, contract, tech, ticket, dispatch)."""
    client, contract, tech, ticket = setup_ticket_in_progress(priority=priority)
    dispatch = create_dispatch(
        ticket["id"], tech["id"], mode="REMOTE",
        scheduled_start="2026-05-01T05:00:00Z",
        scheduled_end="2026-05-01T06:30:00Z",
        resolves_ticket=True,
    )
    return client, contract, tech, ticket, dispatch


def setup_contract_with_seat_adjustment(
    seat_count: int = 10,
    per_seat_rate_cents: int = 5000,
    service_tier: str = "SILVER",
    activate_clock: str = "2026-06-01T00:00:00Z",
    adjustment_effective_at: str = "2026-06-16T00:00:00Z",
    adjustment_delta: int = 10,
    backup_addon: bool = False,
    security_addon: bool = False,
) -> Tuple[dict, dict, int]:
    """Composite precondition for PROVISIONAL-vs-FINAL invoice math (PRD §3.8):
    set clock → create client → create contract → activate (capture version) →
    advance clock to mid-period → apply seat adjustment.

    Returns (client, contract_after_activate, contract_version_at_activate).
    The returned `contract` still carries the version stamped at activation;
    callers that need the post-adjustment view should re-fetch via
    api_client.get_contract().
    """
    set_clock(activate_clock)
    client, contract = setup_active_contract(
        contract_overrides={
            "service_tier": service_tier,
            "seat_count": seat_count,
            "per_seat_rate_cents": per_seat_rate_cents,
            "backup_addon": backup_addon,
            "security_addon": security_addon,
        },
    )
    version_at_activate = contract["version"]
    set_clock(adjustment_effective_at)
    create_seat_adjustment(
        contract["id"],
        delta=adjustment_delta,
        effective_at=adjustment_effective_at,
        expected_contract_version=version_at_activate,
    )
    return client, contract, version_at_activate
