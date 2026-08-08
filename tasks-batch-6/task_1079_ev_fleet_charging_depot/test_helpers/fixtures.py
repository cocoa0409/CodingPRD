"""Composite setup helpers.

Every test runs against a freshly-restarted, empty database, so each fixture
builds all of its preconditions from scratch using only PRD-declared endpoints.
Setup calls use the lenient get_success_data() so setup failures surface as
clear "Setup failed" errors rather than confusing assertion failures.

Identity threading: Driver is the only entity-backed role; every claim submitted
in a fixture uses make_driver_headers(driver["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import (
    fm_headers, op_headers, mt_headers, finance_headers,
    make_finance_headers, make_driver_headers,
)
from . import factories as f


# ---------------------------------------------------------------------------
# Primitive builders
# ---------------------------------------------------------------------------

def new_depot(api, **overrides) -> dict:
    return get_success_data(api.create_depot(f.create_depot_payload(**overrides), fm_headers()))


def depot_version(api, depot_id) -> int:
    return get_success_data(api.get_depot(depot_id, fm_headers()))["version"]


def get_depot(api, depot_id) -> dict:
    return get_success_data(api.get_depot(depot_id, fm_headers()))


def new_charger(api, depot_id, **overrides) -> dict:
    return get_success_data(api.create_charger(f.create_charger_payload(depot_id, **overrides), fm_headers()))


def new_vehicle(api, depot_id, **overrides) -> dict:
    return get_success_data(api.create_vehicle(f.create_vehicle_payload(depot_id, **overrides), fm_headers()))


def new_driver(api, depot_id, **overrides) -> dict:
    return get_success_data(api.create_driver(f.create_driver_payload(depot_id, **overrides), fm_headers()))


def new_route(api, depot_id, vehicle_id, driver_id, **overrides) -> dict:
    return get_success_data(
        api.create_route(f.create_route_payload(depot_id, vehicle_id, driver_id, **overrides), op_headers())
    )


def schedule_session(api, depot_id, charger_id, vehicle_id, expected_depot_version, **overrides) -> dict:
    return get_success_data(
        api.create_session(
            f.create_session_payload(depot_id, charger_id, vehicle_id, expected_depot_version, **overrides),
            op_headers(),
        )
    )


def start_session(api, session_id, actual_start=None) -> dict:
    payload = {} if actual_start is None else {"actual_start": actual_start}
    return get_success_data(api.start_session(session_id, payload, op_headers()))


def complete_session(api, session_id, end_soc_pct, actual_end=None) -> dict:
    payload = {"end_soc_pct": end_soc_pct}
    if actual_end is not None:
        payload["actual_end"] = actual_end
    return get_success_data(api.complete_session(session_id, payload, op_headers()))


def cancel_session(api, session_id) -> dict:
    return get_success_data(api.cancel_session(session_id, op_headers()))


def open_work_order(api, asset_type, charger_id=None, vehicle_id=None, **overrides) -> dict:
    payload = f.create_work_order_payload(asset_type, **overrides)
    if charger_id is not None:
        payload["charger_id"] = charger_id
    if vehicle_id is not None:
        payload["vehicle_id"] = vehicle_id
    return get_success_data(api.create_work_order(payload, mt_headers()))


def transition_work_order(api, wo_id, target_status) -> dict:
    return get_success_data(api.transition_work_order(wo_id, {"target_status": target_status}, mt_headers()))


def submit_claim(api, driver_id, depot_id, expected_depot_version, **overrides) -> dict:
    return get_success_data(
        api.create_claim(
            f.create_claim_payload(driver_id, depot_id, expected_depot_version, **overrides),
            make_driver_headers(driver_id),
        )
    )


def review_claim(api, claim_id, decision, metered_kwh_verified=None, finance_user_id="fin-1") -> dict:
    payload = {"decision": decision}
    if metered_kwh_verified is not None:
        payload["metered_kwh_verified"] = metered_kwh_verified
    return get_success_data(api.review_claim(claim_id, payload, make_finance_headers(finance_user_id)))


def pay_claim(api, claim_id, finance_user_id="fin-2") -> dict:
    return get_success_data(api.pay_claim(claim_id, make_finance_headers(finance_user_id)))


def generate_invoice(api, depot_id, period_month) -> dict:
    return get_success_data(api.create_invoice(f.create_invoice_payload(depot_id, period_month), fm_headers()))


# ---------------------------------------------------------------------------
# Tier: state-progression / lifecycle shortcuts
# ---------------------------------------------------------------------------

def scheduled_session(api, depot_overrides=None, charger_overrides=None,
                      vehicle_overrides=None, session_overrides=None):
    """Depot + charger + vehicle + one SCHEDULED session.

    Returns (depot, charger, vehicle, session). Re-reads depot version between
    provisioning and scheduling so the OCC check passes.
    """
    depot = new_depot(api, **(depot_overrides or {}))
    charger = new_charger(api, depot["id"], **(charger_overrides or {}))
    vehicle = new_vehicle(api, depot["id"], **(vehicle_overrides or {}))
    v = depot_version(api, depot["id"])
    session = schedule_session(api, depot["id"], charger["id"], vehicle["id"], v,
                               **(session_overrides or {}))
    return depot, charger, vehicle, session


def active_session(api, start_actual="2026-05-10T10:00:00Z", **kwargs):
    """Depot + charger + vehicle + a session walked to ACTIVE.

    Returns (depot, charger, vehicle, session_after_start).
    """
    depot, charger, vehicle, session = scheduled_session(api, **kwargs)
    started = start_session(api, session["id"], actual_start=start_actual)
    return depot, charger, vehicle, started


def submitted_claim(api, depot_overrides=None, driver_overrides=None, claim_overrides=None):
    """Depot + driver + one SUBMITTED claim. Returns (depot, driver, claim)."""
    depot = new_depot(api, **(depot_overrides or {}))
    driver = new_driver(api, depot["id"], **(driver_overrides or {}))
    v = depot_version(api, depot["id"])
    claim = submit_claim(api, driver["id"], depot["id"], v, **(claim_overrides or {}))
    return depot, driver, claim


def approved_claim(api, metered_kwh_verified=100, approver="fin-1",
                   depot_overrides=None, driver_overrides=None, claim_overrides=None):
    """Depot + driver + claim submitted then APPROVED by `approver`.

    Returns (depot, driver, claim_after_approve).
    """
    depot, driver, claim = submitted_claim(
        api, depot_overrides=depot_overrides, driver_overrides=driver_overrides,
        claim_overrides=claim_overrides,
    )
    approved = review_claim(api, claim["id"], "APPROVE",
                            metered_kwh_verified=metered_kwh_verified, finance_user_id=approver)
    return depot, driver, approved


def assigned_route(api, vehicle_soc=90, required_soc=80):
    """Depot + READY vehicle + driver + a route walked to ASSIGNED.

    Returns (depot, vehicle, driver, route_after_assign).
    """
    depot = new_depot(api)
    vehicle = new_vehicle(api, depot["id"], current_soc_pct=vehicle_soc)
    driver = new_driver(api, depot["id"])
    route = new_route(api, depot["id"], vehicle["id"], driver["id"], required_soc_pct=required_soc)
    assigned = get_success_data(api.assign_route(route["id"], op_headers()))
    return depot, vehicle, driver, assigned


# ---------------------------------------------------------------------------
# Tier: threshold / calculation targeting (composite, reused by ≥2 tests)
# ---------------------------------------------------------------------------

def setup_demand_charge_invoice(api):
    """Two COMPLETED June sessions peaking concurrently at 250 kW; generate the
    June invoice. Returns the DRAFT invoice.

    S1 150kW [10:00,12:00), S2 100kW [11:00,13:00): concurrent load peaks 250 at
    11:00 (S2 start), so peak_demand_kw == 250; contracted 200 / demand 1000 /
    overage 2500 => demand_charge_cents == 325000.
    """
    depot = new_depot(api, max_load_kw=1000, contracted_capacity_kw=200,
                      demand_rate_cents_per_kw=1000, overage_rate_cents_per_kw=2500)
    ca = new_charger(api, depot["id"], name="CA", max_power_kw=200)
    cb = new_charger(api, depot["id"], name="CB", max_power_kw=200)
    va = new_vehicle(api, depot["id"], vin="VA", current_soc_pct=0)
    vb = new_vehicle(api, depot["id"], vin="VB", current_soc_pct=0)
    s1 = schedule_session(api, depot["id"], ca["id"], va["id"], depot_version(api, depot["id"]),
                          scheduled_start="2026-06-05T10:00:00Z", scheduled_end="2026-06-05T12:00:00Z",
                          target_soc_pct=50, power_kw=150)
    s2 = schedule_session(api, depot["id"], cb["id"], vb["id"], depot_version(api, depot["id"]),
                          scheduled_start="2026-06-05T11:00:00Z", scheduled_end="2026-06-05T13:00:00Z",
                          target_soc_pct=50, power_kw=100)
    start_session(api, s1["id"], actual_start="2026-06-05T10:00:00Z")
    start_session(api, s2["id"], actual_start="2026-06-05T11:00:00Z")
    complete_session(api, s1["id"], 50, actual_end="2026-06-05T12:00:00Z")
    complete_session(api, s2["id"], 50, actual_end="2026-06-05T13:00:00Z")
    return generate_invoice(api, depot["id"], "2026-06")


def setup_energy_subtotal_invoice(api):
    """Two COMPLETED July sessions each metering 5.02 kWh (raw 100.4c -> 100c).

    Returns (invoice, s1_id, s2_id). round-then-sum => energy_subtotal_cents 200.
    """
    depot = new_depot(api, max_load_kw=1000, contracted_capacity_kw=1000,
                      demand_rate_cents_per_kw=0, overage_rate_cents_per_kw=0)
    ca = new_charger(api, depot["id"], name="CA", max_power_kw=100)
    cb = new_charger(api, depot["id"], name="CB", max_power_kw=100)
    va = new_vehicle(api, depot["id"], vin="VA", current_soc_pct=0)
    vb = new_vehicle(api, depot["id"], vin="VB", current_soc_pct=0)
    s1 = schedule_session(api, depot["id"], ca["id"], va["id"], depot_version(api, depot["id"]),
                          scheduled_start="2026-07-05T10:00:00Z", scheduled_end="2026-07-05T11:00:00Z",
                          target_soc_pct=10, power_kw=50)
    s2 = schedule_session(api, depot["id"], cb["id"], vb["id"], depot_version(api, depot["id"]),
                          scheduled_start="2026-07-05T10:00:00Z", scheduled_end="2026-07-05T11:00:00Z",
                          target_soc_pct=10, power_kw=50)
    start_session(api, s1["id"], actual_start="2026-07-05T10:00:00Z")
    complete_session(api, s1["id"], 5.02, actual_end="2026-07-05T11:00:00Z")
    start_session(api, s2["id"], actual_start="2026-07-05T10:00:00Z")
    complete_session(api, s2["id"], 5.02, actual_end="2026-07-05T11:00:00Z")
    inv = generate_invoice(api, depot["id"], "2026-07")
    return inv, s1["id"], s2["id"]
