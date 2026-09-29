"""Composite setup helpers.

The harness restarts the API before every test, so each helper builds its
preconditions from scratch using only published endpoints.  Setup steps use the
lenient validator so a broken precondition surfaces as a setup failure rather
than as a confusing assertion error inside the test body.
"""

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_customer_admin_headers,
    make_field_technician_headers,
    make_fleet_ops_headers,
)

AM = TEST_USERS["account_manager_headers"]
BA = TEST_USERS["billing_analyst_headers"]
OPS = TEST_USERS["fleet_ops_headers"]

DEFAULT_PERIOD_START = "2026-08-01T00:00:00Z"
DEFAULT_PERIOD_END = "2026-09-01T00:00:00Z"
DEFAULT_VLAN_TAG = 2001
MONO_RATE = 9_375
COLOR_RATE = 61_875


# ---------------------------------------------------------------------------
# Read-back helpers
# ---------------------------------------------------------------------------
def fetch_contract(contract_id: str, client=None) -> Dict[str, Any]:
    client = client or api_client
    return get_success_data(client.get_service_contract(contract_id, AM))


def fetch_site(site_id: str, client=None) -> Dict[str, Any]:
    client = client or api_client
    return get_success_data(client.get_site(site_id, AM))


def fetch_device(device_id: str, client=None) -> Dict[str, Any]:
    client = client or api_client
    return get_success_data(client.get_device(device_id, OPS))


def fetch_technician(technician_id: str, client=None) -> Dict[str, Any]:
    client = client or api_client
    return get_success_data(client.get_technician(technician_id, OPS))


def fetch_meter_read(read_id: str, client=None) -> Dict[str, Any]:
    client = client or api_client
    return get_success_data(client.get_meter_read(read_id, OPS))


def fetch_billing_period(period_id: str, client=None) -> Dict[str, Any]:
    client = client or api_client
    return get_success_data(client.get_billing_period(period_id, BA))


def fetch_billing_statement(statement_id: str, client=None) -> Dict[str, Any]:
    client = client or api_client
    return get_success_data(client.get_billing_statement(statement_id, BA))


def fetch_statement_lines(statement_id: str, client=None, params: Optional[Dict] = None) -> List[Dict[str, Any]]:
    client = client or api_client
    return get_success_data(
        client.list_statement_lines(statement_id, BA, params=params or {"limit": 100})
    )


def fetch_consumable_order(order_id: str, client=None) -> Dict[str, Any]:
    client = client or api_client
    return get_success_data(client.get_consumable_order(order_id, OPS))


def fetch_service_ticket(ticket_id: str, client=None) -> Dict[str, Any]:
    client = client or api_client
    return get_success_data(client.get_service_ticket(ticket_id, OPS))


def fetch_quarterly_review(review_id: str, client=None) -> Dict[str, Any]:
    client = client or api_client
    return get_success_data(client.get_quarterly_review(review_id, AM))


def fetch_removal_order(removal_order_id: str, client=None) -> Dict[str, Any]:
    client = client or api_client
    return get_success_data(client.get_removal_order(removal_order_id, AM))


def fetch_part_stock(site_id: str, part_sku: str, client=None) -> Optional[Dict[str, Any]]:
    """Return the locker row for this SKU, or None when no row exists."""
    client = client or api_client
    rows = get_success_data(
        client.list_spare_part_stocks(site_id, OPS, params={"part_sku": part_sku, "limit": 100})
    )
    for row in rows:
        if row.get("part_sku") == part_sku:
            return row
    return None


def list_orders_for_device(device_id: str, status: Optional[str] = None, client=None) -> List[Dict[str, Any]]:
    client = client or api_client
    params: Dict[str, Any] = {"device_id": device_id, "limit": 100}
    if status:
        params["status"] = status
    return get_success_data(client.list_consumable_orders(OPS, params=params))


def open_order_for_device(device_id: str, client=None) -> Optional[Dict[str, Any]]:
    orders = list_orders_for_device(device_id, status="ORDERED", client=client)
    return orders[0] if orders else None


def list_reads_for_device(device_id: str, status: Optional[str] = None, client=None) -> List[Dict[str, Any]]:
    client = client or api_client
    params: Dict[str, Any] = {"device_id": device_id, "limit": 100}
    if status:
        params["status"] = status
    return get_success_data(client.list_meter_reads(OPS, params=params))


# ---------------------------------------------------------------------------
# Tier 1 — single-step primitives
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str, client=None, headers: Optional[Dict[str, str]] = None) -> None:
    """Move the logical clock. Any role may do this."""
    client = client or api_client
    get_success_data(client.set_clock(f.clock_payload(to_iso8601), headers or OPS))


def create_contract(client=None, **overrides) -> Dict[str, Any]:
    client = client or api_client
    return get_success_data(
        client.create_service_contract(f.service_contract_payload(**overrides), AM)
    )


def add_cost_tier(
    contract_id: str,
    page_class: str = "MONO",
    tier_index: int = 1,
    from_page: int = 1,
    to_page: Optional[int] = None,
    rate_micro_dollars_per_page: int = MONO_RATE,
    client=None,
) -> Dict[str, Any]:
    client = client or api_client
    payload: Dict[str, Any] = {
        "page_class": page_class,
        "tier_index": tier_index,
        "from_page": from_page,
        "rate_micro_dollars_per_page": rate_micro_dollars_per_page,
    }
    if to_page is not None:
        payload["to_page"] = to_page
    return get_success_data(client.create_cost_tier(contract_id, payload, AM))


def create_technician(client=None, **overrides) -> Dict[str, Any]:
    client = client or api_client
    return get_success_data(client.create_technician(f.technician_payload(**overrides), AM))


def create_site(contract_id: str, client=None, **overrides) -> Dict[str, Any]:
    client = client or api_client
    return get_success_data(client.create_site(f.site_payload(contract_id, **overrides), AM))


def create_device(contract_id: str, site_id: str, client=None, **overrides) -> Dict[str, Any]:
    client = client or api_client
    return get_success_data(
        client.create_device(f.device_payload(contract_id, site_id, **overrides), OPS)
    )


def activate_contract(contract_id: str, client=None) -> Dict[str, Any]:
    client = client or api_client
    return get_success_data(client.activate_service_contract(contract_id, AM))


def configure_secure_release(
    site_id: str,
    release_method: str = "PIN",
    probe_result: str = "PASS",
    network_vlan_tag: Optional[int] = DEFAULT_VLAN_TAG,
    client=None,
) -> Dict[str, Any]:
    """Run the secure print release probe as the site's own CustomerAdmin."""
    client = client or api_client
    payload: Dict[str, Any] = {"release_method": release_method, "probe_result": probe_result}
    if network_vlan_tag is not None:
        payload["network_vlan_tag"] = network_vlan_tag
    return get_success_data(
        client.configure_secure_release(site_id, payload, make_customer_admin_headers(site_id))
    )


def create_billing_period(
    contract_id: str,
    period_start: str = DEFAULT_PERIOD_START,
    period_end: str = DEFAULT_PERIOD_END,
    client=None,
) -> Dict[str, Any]:
    client = client or api_client
    return get_success_data(
        client.create_billing_period(
            f.billing_period_payload(contract_id, period_start=period_start, period_end=period_end),
            BA,
        )
    )


def adjust_part_stock(site_id: str, part_sku: str, qty_delta: int, client=None) -> Dict[str, Any]:
    client = client or api_client
    return get_success_data(
        client.adjust_spare_part_stock(site_id, f.spare_part_stock_payload(part_sku, qty_delta), OPS)
    )


def advance_device_to(
    device_id: str,
    technician_id: str,
    stage: str = "ACTIVE",
    client=None,
) -> Dict[str, Any]:
    """Walk a device along its lifecycle: PLACED, then NETWORKED, then ACTIVE."""
    client = client or api_client
    tech = make_field_technician_headers(technician_id)
    data = fetch_device(device_id, client)
    if stage == "ASSESSED":
        return data
    data = get_success_data(client.place_device(device_id, tech))
    if stage == "PLACED":
        return data
    data = get_success_data(client.network_integrate_device(device_id, tech))
    if stage == "NETWORKED":
        return data
    return get_success_data(client.activate_device(device_id, OPS))


def submit_automated_read(
    device_id: str,
    billing_period_id: str,
    mono_meter: int,
    color_meter: int = 0,
    toner_level_pct: int = 80,
    coverage_start: str = DEFAULT_PERIOD_START,
    coverage_end: str = "2026-08-08T00:00:00Z",
    user_id: str = "ops-1",
    client=None,
) -> Dict[str, Any]:
    """Capture an automated reading. Returns the created reading."""
    client = client or api_client
    payload = f.meter_read_payload(
        device_id,
        billing_period_id,
        mono_meter=mono_meter,
        color_meter=color_meter,
        toner_level_pct=toner_level_pct,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
    )
    return get_success_data(
        client.submit_automated_meter_read(payload, make_fleet_ops_headers(user_id))
    )


def submit_manual_read(
    device_id: str,
    billing_period_id: str,
    technician_id: str,
    mono_meter: int,
    color_meter: int = 0,
    toner_level_pct: int = 80,
    coverage_start: str = DEFAULT_PERIOD_START,
    coverage_end: str = "2026-08-08T00:00:00Z",
    client=None,
) -> Dict[str, Any]:
    """Capture a manual reading as the technician who took it."""
    client = client or api_client
    payload = f.meter_read_payload(
        device_id,
        billing_period_id,
        mono_meter=mono_meter,
        color_meter=color_meter,
        toner_level_pct=toner_level_pct,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
    )
    return get_success_data(
        client.submit_manual_meter_read(payload, make_field_technician_headers(technician_id))
    )


def create_ticket(
    device_id: str,
    site_id: str,
    severity: str = "STANDARD",
    symptom_code: str = "PAPER_JAM",
    part_sku: Optional[str] = None,
    client=None,
) -> Dict[str, Any]:
    """Raise a ticket as the CustomerAdmin who owns the device's site."""
    client = client or api_client
    payload = f.service_ticket_payload(device_id, severity=severity, symptom_code=symptom_code)
    if part_sku is not None:
        payload["part_sku"] = part_sku
    return get_success_data(
        client.create_service_ticket(payload, make_customer_admin_headers(site_id))
    )


def dispatch_ticket(
    ticket_id: str,
    technician_id: str,
    window_start: str,
    window_end: str,
    client=None,
) -> Dict[str, Any]:
    client = client or api_client
    return get_success_data(
        client.dispatch_service_ticket(
            ticket_id, f.dispatch_payload(technician_id, window_start, window_end), OPS
        )
    )


# ---------------------------------------------------------------------------
# Tier 2 — the composite fleet environment
# ---------------------------------------------------------------------------
def setup_print_environment(
    client=None,
    contract: Optional[Dict[str, Any]] = None,
    mono_tiers: Sequence[Tuple[int, int, Optional[int], int]] = ((1, 1, None, MONO_RATE),),
    color_tiers: Sequence[Tuple[int, int, Optional[int], int]] = (),
    site: Optional[Dict[str, Any]] = None,
    devices: Any = 1,
    technician: Optional[Dict[str, Any]] = None,
    extra_technicians: Iterable[Dict[str, Any]] = (),
    release_method: str = "PIN",
    probe_result: str = "PASS",
    vlan_tag: Optional[int] = DEFAULT_VLAN_TAG,
    activate: bool = True,
    device_stage: str = "ACTIVE",
    period: Any = None,
    clock: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a managed print environment and return every id the tests need.

    The call order mirrors the platform's own dependencies: contract, rate-card
    rows, technician, site, devices, contract activation, the secure print
    release probe, then each device's lifecycle walk, then the billing period,
    then the clock.

    ``mono_tiers`` / ``color_tiers`` are tuples of
    ``(tier_index, from_page, to_page, rate_micro_dollars_per_page)``.
    ``devices`` is either a count of default mono devices or a list of override
    dicts.  ``period`` is ``None`` for no billing period, ``True`` for the
    default window, or a ``(period_start, period_end)`` pair.

    Returns a dict with keys: contract, contract_id, site, site_id, technician,
    technician_id, technicians, devices, device_ids, period, period_id,
    tech_headers, site_headers.
    """
    client = client or api_client

    contract_row = create_contract(client=client, **(contract or {}))
    contract_id = contract_row["id"]

    tiers: List[Dict[str, Any]] = []
    for tier_index, from_page, to_page, rate in mono_tiers:
        tiers.append(
            add_cost_tier(
                contract_id,
                page_class="MONO",
                tier_index=tier_index,
                from_page=from_page,
                to_page=to_page,
                rate_micro_dollars_per_page=rate,
                client=client,
            )
        )
    for tier_index, from_page, to_page, rate in color_tiers:
        tiers.append(
            add_cost_tier(
                contract_id,
                page_class="COLOR",
                tier_index=tier_index,
                from_page=from_page,
                to_page=to_page,
                rate_micro_dollars_per_page=rate,
                client=client,
            )
        )

    technician_row = create_technician(client=client, **(technician or {}))
    technician_rows = [technician_row]
    for extra in extra_technicians:
        technician_rows.append(create_technician(client=client, **extra))

    site_overrides = dict(site or {})
    site_overrides.setdefault("network_vlan_tag", vlan_tag)
    site_row = create_site(contract_id, client=client, **site_overrides)
    site_id = site_row["id"]

    if isinstance(devices, int):
        device_specs: List[Dict[str, Any]] = [{} for _ in range(devices)]
    else:
        device_specs = [dict(spec) for spec in devices]

    device_rows: List[Dict[str, Any]] = []
    for index, spec in enumerate(device_specs, start=1):
        spec.setdefault("asset_tag", f"MPS-{index:04d}")
        device_rows.append(create_device(contract_id, site_id, client=client, **spec))

    if activate:
        contract_row = activate_contract(contract_id, client=client)

    if probe_result is not None:
        site_row = configure_secure_release(
            site_id,
            release_method=release_method,
            probe_result=probe_result,
            network_vlan_tag=vlan_tag,
            client=client,
        )

    if device_stage != "ASSESSED":
        for device_row in device_rows:
            advance_device_to(
                device_row["id"], technician_row["id"], stage=device_stage, client=client
            )
        device_rows = [fetch_device(row["id"], client) for row in device_rows]

    period_row = None
    if period:
        if period is True:
            period_row = create_billing_period(contract_id, client=client)
        else:
            period_row = create_billing_period(
                contract_id, period_start=period[0], period_end=period[1], client=client
            )

    if clock:
        set_clock(clock, client=client)

    return {
        "contract": fetch_contract(contract_id, client),
        "contract_id": contract_id,
        "tiers": tiers,
        "site": fetch_site(site_id, client),
        "site_id": site_id,
        "technician": technician_row,
        "technician_id": technician_row["id"],
        "technicians": technician_rows,
        "devices": device_rows,
        "device_ids": [row["id"] for row in device_rows],
        "device": device_rows[0] if device_rows else None,
        "device_id": device_rows[0]["id"] if device_rows else None,
        "period": period_row,
        "period_id": period_row["id"] if period_row else None,
        "tech_headers": make_field_technician_headers(technician_row["id"]),
        "site_headers": make_customer_admin_headers(site_id),
    }


# ---------------------------------------------------------------------------
# Tier 3 — lifecycle shortcuts
# ---------------------------------------------------------------------------
def setup_environment_with_auto_toner_order(
    client=None,
    toner_level_pct: int = 10,
    mono_meter: int = 1000,
    coverage_start: str = DEFAULT_PERIOD_START,
    coverage_end: str = "2026-08-09T00:00:00Z",
    clock: str = "2026-08-10T00:00:00Z",
    **env_kwargs,
) -> Dict[str, Any]:
    """One active device whose accepted reading has driven an automatic order.

    Returns the environment dict with the extra keys ``read`` and ``order``.
    """
    client = client or api_client
    env_kwargs.setdefault("period", True)
    env = setup_print_environment(client=client, clock=clock, **env_kwargs)
    read = submit_automated_read(
        env["device_id"],
        env["period_id"],
        mono_meter=mono_meter,
        toner_level_pct=toner_level_pct,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        client=client,
    )
    env["read"] = read
    env["order"] = open_order_for_device(env["device_id"], client=client)
    env["device"] = fetch_device(env["device_id"], client)
    return env


def setup_dispatched_ticket(
    client=None,
    severity: str = "STANDARD",
    part_sku: Optional[str] = None,
    symptom_code: str = "PAPER_JAM",
    window_start: str = "2026-08-05T09:00:00Z",
    window_end: str = "2026-08-05T10:00:00Z",
    clock: str = "2026-08-05T08:00:00Z",
    **env_kwargs,
) -> Dict[str, Any]:
    """One active device with a ticket already dispatched to the technician.

    Returns the environment dict with the extra key ``ticket``.
    """
    client = client or api_client
    env = setup_print_environment(client=client, clock=clock, **env_kwargs)
    ticket = create_ticket(
        env["device_id"],
        env["site_id"],
        severity=severity,
        symptom_code=symptom_code,
        part_sku=part_sku,
        client=client,
    )
    env["ticket"] = dispatch_ticket(
        ticket["id"], env["technician_id"], window_start, window_end, client=client
    )
    env["ticket_id"] = ticket["id"]
    return env


def setup_onsite_ticket(client=None, **kwargs) -> Dict[str, Any]:
    """A dispatched ticket walked forward to ONSITE (no part named)."""
    client = client or api_client
    env = setup_dispatched_ticket(client=client, **kwargs)
    env["ticket"] = get_success_data(
        client.arrive_onsite(env["ticket_id"], make_field_technician_headers(env["technician_id"]))
    )
    return env


def generate_provisional_statement(period_id: str, client=None) -> Dict[str, Any]:
    """Read the period's current version, then draw the projected statement."""
    client = client or api_client
    period = fetch_billing_period(period_id, client)
    return get_success_data(
        client.generate_provisional_statement(
            period_id, f.provisional_statement_payload(period["version"]), BA
        )
    )


def run_sweep(period_id: str, client=None, user_id: str = "ops-1") -> Dict[str, Any]:
    client = client or api_client
    return get_success_data(client.run_meter_sweep(period_id, make_fleet_ops_headers(user_id)))


def close_period(period_id: str, client=None) -> Dict[str, Any]:
    """Close the period and return the FINAL statement it produces."""
    client = client or api_client
    return get_success_data(client.close_billing_period(period_id, BA))


def sweep_and_close_period(period_id: str, client=None) -> Dict[str, Any]:
    """Sweep, then close. Returns the FINAL statement."""
    client = client or api_client
    run_sweep(period_id, client=client)
    return close_period(period_id, client=client)


def setup_closed_period_with_final_statement(
    client=None,
    reads: Sequence[Dict[str, Any]] = (),
    close_clock: str = DEFAULT_PERIOD_END,
    read_clock: str = "2026-08-16T00:00:00Z",
    **env_kwargs,
) -> Dict[str, Any]:
    """Environment, accepted readings, then a swept and closed period.

    ``reads`` is a sequence of keyword dicts passed to ``submit_automated_read``;
    each entry may name ``device_index`` to pick the device it belongs to.
    Returns the environment dict with the extra keys ``reads`` and ``statement``.
    """
    client = client or api_client
    env_kwargs.setdefault("period", True)
    env = setup_print_environment(client=client, clock=read_clock, **env_kwargs)
    captured = []
    for spec in reads:
        spec = dict(spec)
        device_index = spec.pop("device_index", 0)
        captured.append(
            submit_automated_read(
                env["device_ids"][device_index], env["period_id"], client=client, **spec
            )
        )
    set_clock(close_clock, client=client)
    env["reads"] = captured
    env["statement"] = sweep_and_close_period(env["period_id"], client=client)
    env["period"] = fetch_billing_period(env["period_id"], client)
    return env


def setup_removal_order(
    contract_id: str,
    scheduled_for: str,
    stage: str = "REQUESTED",
    technician_id: Optional[str] = None,
    sanitization_method: str = "CRYPTO_ERASE",
    sanitization_certificate_ref: str = "CERT-2026-08-20-A",
    client=None,
) -> Dict[str, Any]:
    """Raise a removal order and walk it to ``stage``.

    Stages: REQUESTED, SCHEDULED, COLLECTED, SANITIZED, SETTLED.  Collection and
    sanitization are technician actions, so ``technician_id`` is required from
    the COLLECTED stage onwards.  The caller is responsible for advancing the
    clock to the collection moment before asking for COLLECTED or later.
    """
    client = client or api_client
    order = get_success_data(
        client.create_removal_order(f.removal_order_payload(contract_id, scheduled_for), AM)
    )
    order_id = order["id"]
    if stage == "REQUESTED":
        return order
    order = get_success_data(
        client.schedule_removal_order(order_id, f.schedule_removal_payload(scheduled_for), AM)
    )
    if stage == "SCHEDULED":
        return order
    tech = make_field_technician_headers(technician_id or "")
    order = get_success_data(client.collect_removal_order(order_id, tech))
    if stage == "COLLECTED":
        return order
    order = get_success_data(
        client.sanitize_removal_order(
            order_id,
            f.sanitize_payload(sanitization_method, sanitization_certificate_ref),
            tech,
        )
    )
    if stage == "SANITIZED":
        return order
    return get_success_data(client.settle_removal_order(order_id, BA))


def create_quarterly_review(contract_id: str, quarter_label: str = "2026-Q3", user_id: str = "am-1", client=None) -> Dict[str, Any]:
    """Author a quarterly review as a named AccountManager."""
    from .test_users import make_account_manager_headers

    client = client or api_client
    return get_success_data(
        client.create_quarterly_review(
            f.quarterly_review_payload(contract_id, quarter_label),
            make_account_manager_headers(user_id),
        )
    )
