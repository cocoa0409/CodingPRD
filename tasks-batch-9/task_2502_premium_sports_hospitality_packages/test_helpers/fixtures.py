"""Composite setup helpers and pytest fixtures.

Every test runs against an empty database, so each precondition below is built
from scratch through the PRD-declared endpoints only. Setup calls use
``get_success_data`` so that a broken precondition reports the server's own
error identifier rather than a downstream KeyError.
"""

from typing import Any, Dict, List, Optional, Tuple

import pytest

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .test_users import (
    CLIENT_SERVICE_AGENT,
    COMMERCIAL_DIRECTOR,
    COMMERCIAL_MANAGER,
    FINANCE_CONTROLLER,
    OPERATIONS_MANAGER,
    RIGHTS_MANAGER,
)

# ==========================================================================
# Atomic builders
# ==========================================================================


def set_clock(api: ApiClient, current_utc: str) -> Dict[str, Any]:
    """Move the logical clock; the endpoint echoes back its new value (§2.4)."""
    return get_success_data(api.set_clock(f.clock_payload(current_utc), OPERATIONS_MANAGER))


def reset_clock(api: ApiClient) -> Dict[str, Any]:
    """Park the clock on its declared startup default, 2026-08-01T00:00:00Z."""
    return set_clock(api, "2026-08-01T00:00:00Z")


def make_event(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_event(f.event_payload(**overrides), RIGHTS_MANAGER), 201)


def make_deal(api: ApiClient, event_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_rights_deal(f.rights_deal_payload(event_id, **overrides), RIGHTS_MANAGER), 201
    )


def commit_deal(api: ApiClient, deal_id: str) -> Dict[str, Any]:
    return get_success_data(api.commit_rights_deal(deal_id, RIGHTS_MANAGER))


def make_committed_deal(api: ApiClient, event_id: str, **overrides: Any) -> Dict[str, Any]:
    """A rights deal walked DRAFT -> COMMITTED (§3.1)."""
    deal = make_deal(api, event_id, **overrides)
    return commit_deal(api, deal["id"])


def make_tranche(api: ApiClient, deal_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_release_tranche(f.release_tranche_payload(deal_id, **overrides), RIGHTS_MANAGER),
        201,
    )


def deal_version(api: ApiClient, deal_id: str) -> int:
    return get_success_data(api.get_rights_deal(deal_id, RIGHTS_MANAGER))["version"]


def confirm_tranche(api: ApiClient, tranche_id: str, deal_id: str,
                    confirmed_units: int) -> Dict[str, Any]:
    """Confirm a tranche, pinning the parent deal's current version (§2.6)."""
    return get_success_data(
        api.confirm_release_tranche(
            tranche_id,
            f.confirm_tranche_payload(deal_version(api, deal_id), confirmed_units),
            RIGHTS_MANAGER,
        )
    )


def release_deal(api: ApiClient, deal_id: str, promised_units: int,
                 confirmed_units: Optional[int] = None,
                 promised_release_at: str = "2026-10-01T00:00:00.000Z") -> Dict[str, Any]:
    """Record one promise against a committed deal and confirm it.

    Returns the tranche row *as the confirmation left it*, not the pre-confirmation
    row, so callers see the state the promise actually ended in.
    """
    tranche = make_tranche(
        api, deal_id, promised_units=promised_units, promised_release_at=promised_release_at
    )
    return confirm_tranche(
        api, tranche["id"], deal_id,
        promised_units if confirmed_units is None else confirmed_units,
    )


def make_block(api: ApiClient, deal_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_allocation_block(f.allocation_block_payload(deal_id, **overrides),
                                    COMMERCIAL_MANAGER),
        201,
    )


def read_block(api: ApiClient, block_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_allocation_block(block_id, COMMERCIAL_MANAGER))


def make_package(api: ApiClient, event_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_package_product(f.package_product_payload(event_id, **overrides),
                                   COMMERCIAL_MANAGER),
        201,
    )


def make_bronze_package(api: ApiClient, event_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_package_product(f.bronze_package_payload(event_id, **overrides),
                                   COMMERCIAL_MANAGER),
        201,
    )


def add_component(api: ApiClient, package_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_package_component(f.package_component_payload(package_id, **overrides),
                                     COMMERCIAL_MANAGER),
        201,
    )


def add_gold_components(api: ApiClient, package_id: str) -> List[Dict[str, Any]]:
    """The four canonical GOLD lines, added in ascending sequence_no order."""
    return [
        get_success_data(api.create_package_component(payload, COMMERCIAL_MANAGER), 201)
        for payload in f.gold_component_payloads(package_id)
    ]


def price_package(api: ApiClient, package_id: str) -> Dict[str, Any]:
    return get_success_data(api.price_package_product(package_id, COMMERCIAL_MANAGER))


def publish_package(api: ApiClient, package_id: str, version: Optional[int] = None) -> Dict[str, Any]:
    """Publish under the director's identity, pinning the reviewed version (§3.4)."""
    if version is None:
        version = get_success_data(api.get_package_product(package_id, COMMERCIAL_DIRECTOR))["version"]
    return get_success_data(
        api.publish_package_product(package_id, f.publish_payload(version), COMMERCIAL_DIRECTOR)
    )


def make_priced_gold_package(api: ApiClient, event_id: str, **overrides: Any) -> Dict[str, Any]:
    """The canonical GOLD package walked DRAFT -> PRICED."""
    package = make_package(api, event_id, **overrides)
    add_gold_components(api, package["id"])
    return price_package(api, package["id"])


def make_published_gold_package(api: ApiClient, event_id: str, **overrides: Any) -> Dict[str, Any]:
    """The canonical GOLD package walked DRAFT -> PRICED -> PUBLISHED."""
    priced = make_priced_gold_package(api, event_id, **overrides)
    return publish_package(api, priced["id"], priced["version"])


def make_published_bronze_package(api: ApiClient, event_id: str, **overrides: Any) -> Dict[str, Any]:
    """The round-numbered BRONZE package walked DRAFT -> PRICED -> PUBLISHED."""
    package = make_bronze_package(api, event_id, **overrides)
    add_component(api, package["id"], **f.BRONZE_COMPONENT_SPEC)
    priced = price_package(api, package["id"])
    return publish_package(api, priced["id"], priced["version"])


def make_client(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_client(f.client_payload(**overrides), CLIENT_SERVICE_AGENT), 201)


def read_client(api: ApiClient, client_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_client(client_id, CLIENT_SERVICE_AGENT))


def make_booking(api: ApiClient, client_id: str, package_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_booking(f.booking_payload(client_id, package_id, **overrides),
                           CLIENT_SERVICE_AGENT),
        201,
    )


def read_booking(api: ApiClient, booking_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_booking(booking_id, CLIENT_SERVICE_AGENT))


def allocate_booking(api: ApiClient, booking_id: str, block_id: str) -> Dict[str, Any]:
    """Commit inventory, reading the block's version immediately beforehand (§2.6)."""
    version = read_block(api, block_id)["version"]
    return get_success_data(
        api.allocate_booking(booking_id, f.allocate_payload(block_id, version), CLIENT_SERVICE_AGENT)
    )


def issue_credentials(api: ApiClient, booking_id: str) -> Dict[str, Any]:
    return get_success_data(api.issue_credentials(booking_id, CLIENT_SERVICE_AGENT))


def cancel_booking(api: ApiClient, booking_id: str) -> Dict[str, Any]:
    return get_success_data(api.cancel_booking(booking_id, CLIENT_SERVICE_AGENT))


def installments_of(api: ApiClient, booking_id: str, **filters: Any) -> List[Dict[str, Any]]:
    """A booking's installment rows, discoverable only through the list (§3.6)."""
    params: Dict[str, Any] = {"booking_id": booking_id, "limit": 100}
    params.update(filters)
    body = api.list_payment_installments(FINANCE_CONTROLLER, params).json()
    rows = body["data"]
    return sorted(rows, key=lambda row: row["sequence_no"])


def pay_installment(api: ApiClient, installment_id: str, amount_cents: int) -> Dict[str, Any]:
    return get_success_data(
        api.pay_installment(installment_id, f.pay_payload(amount_cents), FINANCE_CONTROLLER)
    )


def pay_next_installment(api: ApiClient, booking_id: str) -> Dict[str, Any]:
    """Settle the lowest-numbered payable SCHEDULE line in full."""
    for line in installments_of(api, booking_id):
        if line["installment_state"] in ("SCHEDULED", "OVERDUE"):
            return pay_installment(api, line["id"], line["amount_cents"])
    raise AssertionError(f"booking {booking_id} has no payable installment")


def make_build(api: ApiClient, event_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_hospitality_build(f.hospitality_build_payload(event_id, **overrides),
                                     OPERATIONS_MANAGER),
        201,
    )


def approve_build(api: ApiClient, build_id: str) -> Dict[str, Any]:
    return get_success_data(api.approve_hospitality_build(build_id, FINANCE_CONTROLLER))


def ready_build(api: ApiClient, build_id: str) -> Dict[str, Any]:
    return get_success_data(api.ready_hospitality_build(build_id, OPERATIONS_MANAGER))


def make_ready_build(api: ApiClient, event_id: str, **overrides: Any) -> Dict[str, Any]:
    """A build walked PLANNED -> APPROVED -> READY (§3.7)."""
    build = make_build(api, event_id, **overrides)
    approve_build(api, build["id"])
    return ready_build(api, build["id"])


def make_host(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_on_site_host(f.on_site_host_payload(**overrides),
                                                    OPERATIONS_MANAGER), 201)


def read_host(api: ApiClient, host_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_on_site_host(host_id, OPERATIONS_MANAGER))


def make_assignment(api: ApiClient, host_id: str, booking_id: str, build_id: str,
                    **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_host_assignment(
            f.host_assignment_payload(host_id, booking_id, build_id, **overrides),
            OPERATIONS_MANAGER,
        ),
        201,
    )


def daily_run(api: ApiClient) -> Dict[str, Any]:
    return get_success_data(api.daily_run(OPERATIONS_MANAGER))


def read_event(api: ApiClient, event_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_event(event_id, RIGHTS_MANAGER))


def margin_report(api: ApiClient, event_id: str, variant: Optional[str] = None) -> Dict[str, Any]:
    return get_success_data(
        api.get_margin_report(event_id, FINANCE_CONTROLLER, f.margin_report_params(variant))
    )


# ==========================================================================
# Composite scenarios
# ==========================================================================


def gold_sales_floor(api: ApiClient, released_units: int = 60,
                     target_units: int = 40, channel: str = "CORPORATE",
                     priority_rank: int = 1,
                     client_overrides: Optional[Dict[str, Any]] = None,
                     ) -> Dict[str, Any]:
    """The canonical selling scenario used by most depth probes.

    One fixture, one committed TICKET deal, one channel block, the canonical
    GOLD package published, and one registered client. The block is created
    before the release is confirmed so the waterfall fills it on confirmation.
    """
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"])
    block = make_block(api, deal["id"], channel=channel, target_units=target_units,
                       priority_rank=priority_rank)
    release_deal(api, deal["id"], released_units)
    package = make_published_gold_package(api, event["id"])
    client = make_client(api, **(client_overrides or {}))
    return {
        "event": event,
        "deal": deal,
        "block": read_block(api, block["id"]),
        "package": package,
        "client": client,
    }


def bronze_sales_floor(api: ApiClient, released_units: int = 60,
                       target_units: int = 40, channel: str = "CORPORATE",
                       client_overrides: Optional[Dict[str, Any]] = None,
                       ) -> Dict[str, Any]:
    """The same shape as :func:`gold_sales_floor` but with the round-numbered
    BRONZE package, so every derived figure is a short literal."""
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"])
    block = make_block(api, deal["id"], channel=channel, target_units=target_units)
    release_deal(api, deal["id"], released_units)
    package = make_published_bronze_package(api, event["id"])
    client = make_client(api, **(client_overrides or {}))
    return {
        "event": event,
        "deal": deal,
        "block": read_block(api, block["id"]),
        "package": package,
        "client": client,
    }


def unexposed_bronze_floor(api: ApiClient, client_overrides: Optional[Dict[str, Any]] = None,
                           ) -> Dict[str, Any]:
    """A selling scenario with no guarantee exposure: the TICKET deal has
    released its whole contracted quantity, so the surcharge of §3.5 is 0."""
    return bronze_sales_floor(api, released_units=60, client_overrides=client_overrides)


def exposed_bronze_floor(api: ApiClient, client_overrides: Optional[Dict[str, Any]] = None,
                         ) -> Dict[str, Any]:
    """A selling scenario that IS exposed: the TICKET deal is still owing units,
    so the guarantee surcharge of §3.5 applies."""
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"])
    block = make_block(api, deal["id"], target_units=40)
    release_deal(api, deal["id"], 40)
    package = make_published_bronze_package(api, event["id"])
    client = make_client(api, **(client_overrides or {}))
    return {
        "event": event,
        "deal": deal,
        "block": read_block(api, block["id"]),
        "package": package,
        "client": client,
    }


def allocated_gold_booking(api: ApiClient, units: int = 10,
                           channel: str = "CORPORATE") -> Dict[str, Any]:
    """A GOLD booking walked RESERVED -> ALLOCATED against a filled block."""
    floor = gold_sales_floor(api, channel=channel)
    booking = make_booking(api, floor["client"]["id"], floor["package"]["id"],
                           channel=channel, units=units)
    allocated = allocate_booking(api, booking["id"], floor["block"]["id"])
    floor["booking"] = allocated
    return floor


def credentialed_gold_booking(api: ApiClient, units: int = 10) -> Dict[str, Any]:
    """A GOLD booking walked all the way to CREDENTIALED, with a READY build."""
    scenario = allocated_gold_booking(api, units=units)
    build = make_ready_build(api, scenario["event"]["id"])
    scenario["build"] = build
    scenario["booking"] = issue_credentials(api, scenario["booking"]["id"])
    return scenario


def credentialed_booking_with_host(api: ApiClient, units: int = 10,
                                   max_concurrent_bookings: int = 2) -> Dict[str, Any]:
    """A CREDENTIALED booking with one ASSIGNED host on the match-day shift."""
    scenario = credentialed_gold_booking(api, units=units)
    host = make_host(api, max_concurrent_bookings=max_concurrent_bookings)
    assignment = make_assignment(api, host["id"], scenario["booking"]["id"],
                                 scenario["build"]["id"])
    scenario["host"] = host
    scenario["assignment"] = assignment
    scenario["booking"] = read_booking(api, scenario["booking"]["id"])
    return scenario


def two_zone_event(api: ApiClient) -> Dict[str, Any]:
    """A fixture with two declared hospitality zones and nothing else."""
    reset_clock(api)
    return make_event(api)


# ==========================================================================
# pytest fixtures
# ==========================================================================


@pytest.fixture
def api() -> ApiClient:
    """A client against the API under test; the database is empty per test."""
    return ApiClient()


@pytest.fixture
def clock(api: ApiClient) -> str:
    """The logical clock parked on its declared startup default."""
    reset_clock(api)
    return "2026-08-01T00:00:00.000Z"


@pytest.fixture
def event(api: ApiClient, clock: str) -> Dict[str, Any]:
    return make_event(api)


@pytest.fixture
def gold_floor(api: ApiClient) -> Dict[str, Any]:
    return gold_sales_floor(api)


@pytest.fixture
def bronze_floor(api: ApiClient) -> Dict[str, Any]:
    return bronze_sales_floor(api)


@pytest.fixture
def exposed_floor(api: ApiClient) -> Dict[str, Any]:
    return exposed_bronze_floor(api)
