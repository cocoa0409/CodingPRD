"""Composite setup helpers.

Each test runs against a freshly restarted, empty server, so every helper builds
its preconditions from scratch using only PRD-declared endpoints. Helpers use the
lenient get_success_data() so setup failures surface as clear "Setup failed"
errors rather than confusing assertion failures.

Ownership threading: after a Driver entity is created, every ownership-gated
Driver call uses make_driver_headers(driver["id"]) — never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import ENERGY_TARIFF, FUNDED_WALLET_CENTS, BASE_CLOCK
from .factories import (
    create_site_payload,
    create_stall_payload,
    create_driver_payload,
    create_emsp_payload,
    create_tariff_payload,
    create_session_payload,
    create_meter_event_payload,
    create_settlement_batch_payload,
    create_line_item_payload,
    create_reservation_payload,
)
from .test_users import TEST_USERS, make_driver_headers

CPO = TEST_USERS["cpo_headers"]
STATION = TEST_USERS["station_headers"]


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(iso: str):
    """Set the server's current UTC clock (operator-only, PRD §3.9)."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, CPO))


# --------------------------------------------------------------------------
# Primitive creators
# --------------------------------------------------------------------------
def create_emsp(commission_pct: float = 0.075, name: str = "Test eMSP") -> dict:
    return get_success_data(
        api_client.create_emsp(create_emsp_payload(name=name, commission_pct=commission_pct), CPO)
    )


def create_driver(emsp_id: str, email: str = "d@x.com", fund: int = 0) -> dict:
    drv = get_success_data(
        api_client.create_driver(create_driver_payload(emsp_id, email=email), CPO)
    )
    if fund:
        drv = get_success_data(
            api_client.adjust_wallet(drv["id"], {"amount_cents": fund}, CPO)
        )
    return drv


def create_site(**overrides) -> dict:
    return get_success_data(api_client.create_site(create_site_payload(**overrides), CPO))


def create_stall(site_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_stall(create_stall_payload(site_id, **overrides), CPO)
    )


def create_tariff(site_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_tariff(create_tariff_payload(site_id, **overrides), CPO)
    )


# --------------------------------------------------------------------------
# Tier 2: standard environment (eMSP + funded driver + site + tariff + stall)
# --------------------------------------------------------------------------
def setup_environment(
    *,
    clock: str = BASE_CLOCK,
    commission_pct: float = 0.075,
    fund: int = FUNDED_WALLET_CENTS,
    site_overrides: dict = None,
    tariff_overrides: dict = None,
    stall_overrides: dict = None,
    connector_type: str = "CCS",
    email: str = "env@x.com",
) -> dict:
    """Full priceable environment: clock set, eMSP, funded home driver, site with
    one CCS ENERGY tariff and one CCS stall. Returns a dict of the created rows.

    Pass tariff_overrides={} for the default ENERGY tariff, or skip the tariff by
    passing tariff_overrides=None and want_tariff=False (use setup_environment_no_tariff)."""
    set_clock(clock)
    emsp = create_emsp(commission_pct=commission_pct)
    driver = create_driver(emsp["id"], email=email, fund=fund)
    site = create_site(**(site_overrides or {}))
    tariff = create_tariff(
        site["id"], connector_type=connector_type, **(tariff_overrides or {})
    )
    stall = create_stall(site["id"], connector_type=connector_type, **(stall_overrides or {}))
    return {
        "emsp": emsp,
        "driver": driver,
        "site": site,
        "tariff": tariff,
        "stall": stall,
    }


# --------------------------------------------------------------------------
# Tier 1/3: session lifecycle progression
# --------------------------------------------------------------------------
def start_session(stall_id: str, driver_id: str, **overrides) -> dict:
    """POST /sessions as the owning Driver. Returns the PREPARING session."""
    return get_success_data(
        api_client.create_session(
            create_session_payload(stall_id, driver_id, **overrides),
            make_driver_headers(driver_id),
        )
    )


def post_meter(session_id: str, meter_kwh, sampled_at: str, context: str) -> dict:
    return get_success_data(
        api_client.create_meter_event(
            session_id,
            create_meter_event_payload(meter_kwh, sampled_at, context),
            STATION,
        )
    )


def begin_charging(session_id: str) -> dict:
    return get_success_data(api_client.begin_charging(session_id, STATION))


def suspend_session(session_id: str) -> dict:
    return get_success_data(api_client.suspend_session(session_id, STATION))


def stop_session(session_id: str, driver_id: str) -> dict:
    return get_success_data(
        api_client.stop_session(session_id, make_driver_headers(driver_id))
    )


def run_energy_session(
    env: dict,
    *,
    stall_id: str = None,
    begin_at: str = "2026-06-01T00:00:00Z",
    suspend_at: str = None,
    end_at: str = "2026-06-01T00:50:00Z",
    end_kwh: float = 35,
    is_roaming: bool = False,
    stop_by_station: bool = False,
) -> dict:
    """Run one full session start→charge→(optional suspend)→stop and return the
    stopped (RATED) session. begin meter is always 0 kWh.

    begin_at/suspend_at/end_at drive the server clock so charging_minutes and
    idle_minutes are deterministic. If suspend_at is given the session is
    suspended at that instant (idle accrues from suspend_at to end_at)."""
    stall_id = stall_id or env["stall"]["id"]
    driver_id = env["driver"]["id"]
    sess = start_session(stall_id, driver_id, is_roaming=is_roaming)
    set_clock(begin_at)
    post_meter(sess["id"], 0, begin_at, "TRANSACTION_BEGIN")
    begin_charging(sess["id"])
    if suspend_at is not None:
        set_clock(suspend_at)
        suspend_session(sess["id"])
    set_clock(end_at)
    post_meter(sess["id"], end_kwh, end_at, "TRANSACTION_END")
    if stop_by_station:
        return get_success_data(api_client.stop_session(sess["id"], STATION))
    return stop_session(sess["id"], driver_id)


# --------------------------------------------------------------------------
# Tier 4: multi-session CHARGING pool (for load-allocation tests)
# --------------------------------------------------------------------------
def setup_charging_pool(
    *,
    circuit_limit_kw: float,
    demand_charge_threshold_kw: float = None,
    allocation_policy: str = "PRIORITY",
    demand_avoidance_armed: bool = False,
    stalls: list = None,
    clock: str = BASE_CLOCK,
) -> dict:
    """Create a site + N CCS stalls + N home sessions, all begun-charging so all
    are simultaneously CHARGING. `stalls` is a list of dicts of stall overrides
    (e.g. {"max_power_kw": 60, "reservation_priority": 1}); sessions are created
    in list order so created_at ordering matches the list order.

    Returns {site, stalls:[...], sessions:[...], driver, emsp, tariff}."""
    if demand_charge_threshold_kw is None:
        demand_charge_threshold_kw = circuit_limit_kw
    set_clock(clock)
    emsp = create_emsp()
    driver = create_driver(emsp["id"], email="pool@x.com", fund=FUNDED_WALLET_CENTS)
    site = create_site(
        circuit_limit_kw=circuit_limit_kw,
        demand_charge_threshold_kw=demand_charge_threshold_kw,
        allocation_policy=allocation_policy,
        demand_avoidance_armed=demand_avoidance_armed,
    )
    tariff = create_tariff(site["id"], connector_type="CCS")
    stall_rows = []
    session_rows = []
    last = None
    for spec in (stalls or []):
        st = create_stall(site["id"], connector_type="CCS", **spec)
        stall_rows.append(st)
        sess = start_session(st["id"], driver["id"])
        post_meter(sess["id"], 0, clock, "TRANSACTION_BEGIN")
        last = begin_charging(sess["id"])
        session_rows.append(last)
    return {
        "emsp": emsp,
        "driver": driver,
        "site": site,
        "tariff": tariff,
        "stalls": stall_rows,
        "sessions": session_rows,
        "last_begin": last,
    }


# --------------------------------------------------------------------------
# Tier 5: settlement state shortcuts
# --------------------------------------------------------------------------
def rate_roaming_session(env: dict, *, end_kwh: float = 35,
                         begin_at: str = "2026-06-01T00:00:00Z",
                         suspend_at: str = "2026-06-01T00:50:00Z",
                         end_at: str = "2026-06-01T01:15:00Z") -> dict:
    """Run a roaming session to RATED. The standard 35 kWh / 50-charge / 25-idle
    session yields total_cost_cents 1825 under the canonical ENERGY tariff."""
    return run_energy_session(
        env,
        begin_at=begin_at,
        suspend_at=suspend_at,
        end_at=end_at,
        end_kwh=end_kwh,
        is_roaming=True,
        stop_by_station=True,
    )


def open_batch(emsp_id: str) -> dict:
    return get_success_data(
        api_client.create_settlement_batch(create_settlement_batch_payload(emsp_id), CPO)
    )


def add_line_item(batch_id: str, session_id: str) -> dict:
    return get_success_data(
        api_client.add_line_item(batch_id, create_line_item_payload(session_id), CPO)
    )


def lock_batch(batch_id: str) -> dict:
    return get_success_data(api_client.lock_batch(batch_id, CPO))


def setup_locked_batch_with_rated_session(*, end_kwh: float = 35) -> dict:
    """eMSP + one rated roaming session (1825) + a LOCKED batch holding its line
    item. Returns {emsp, driver, site, tariff, stall, session, batch, line_item,
    batch_version}."""
    env = setup_environment(commission_pct=0.075, email="lb@x.com")
    sess = rate_roaming_session(env)
    batch = open_batch(env["emsp"]["id"])
    li = add_line_item(batch["id"], sess["id"])
    locked = lock_batch(batch["id"])
    return {
        **env,
        "session": sess,
        "batch": batch,
        "line_item": li,
        "batch_version": locked["version"],
    }


# --------------------------------------------------------------------------
# Reservation shortcuts
# --------------------------------------------------------------------------
def create_reservation(env: dict, *, window_start: str, window_end: str,
                       hold_fee_cents: int = 0, stall_version: int = None) -> dict:
    """Create a REQUESTED reservation for env's driver on env's stall."""
    driver_id = env["driver"]["id"]
    if stall_version is None:
        stall = get_success_data(
            api_client.get_stall(env["stall"]["id"], make_driver_headers(driver_id))
        )
        stall_version = stall["version"]
    return get_success_data(
        api_client.create_reservation(
            create_reservation_payload(
                env["stall"]["id"], driver_id, stall_version,
                window_start=window_start, window_end=window_end,
                hold_fee_cents=hold_fee_cents,
            ),
            make_driver_headers(driver_id),
        )
    )


def confirm_reservation(reservation_id: str, driver_id: str) -> dict:
    return get_success_data(
        api_client.confirm_reservation(reservation_id, make_driver_headers(driver_id))
    )
