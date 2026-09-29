"""Composite setup helpers.

Every helper builds its preconditions from scratch through the endpoints the
PRD declares, because each test begins against an empty database. Setup calls
use the lenient success reader so that a broken precondition surfaces as a
setup failure rather than as a confusing assertion.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .constants import CLOCK_EPOCH
from .test_users import (
    TEST_USERS,
    make_bms_gateway_headers,
    make_energy_analyst_headers,
    make_energy_manager_headers,
    make_store_manager_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["energy_manager_headers"]
ANALYST = TEST_USERS["energy_analyst_headers"]
OFFICER = TEST_USERS["food_safety_officer_headers"]
TECH = TEST_USERS["maintenance_tech_headers"]


# ----------------------------------------------------------------------
# Logical clock
# ----------------------------------------------------------------------
def set_clock(api, current_utc: str = CLOCK_EPOCH) -> dict:
    """Set the logical clock and return the sweep report."""
    return get_success_data(api.set_current_utc(current_utc, ADMIN))


# ----------------------------------------------------------------------
# Stores and setpoint standards
# ----------------------------------------------------------------------
def create_store(api, **overrides) -> dict:
    return get_success_data(api.create_store(f.create_store_payload(**overrides), ADMIN))


def create_standard(api, **overrides) -> dict:
    return get_success_data(
        api.create_setpoint_standard(f.create_setpoint_standard_payload(**overrides), MANAGER)
    )


def publish_standard(api, standard_id: str) -> dict:
    return get_success_data(api.publish_setpoint_standard(standard_id, MANAGER))


def create_published_standard(api, **overrides) -> dict:
    """Draft a standard and publish it, returning the published row."""
    standard = create_standard(api, **overrides)
    return publish_standard(api, standard["id"])


def commission_store(api, store_id: str, standard_id: str, expected_store_version: int) -> dict:
    return get_success_data(
        api.commission_bms(
            store_id,
            f.commission_bms_payload(standard_id, expected_store_version),
            MANAGER,
        )
    )


def activate_store_bms(api, store_id: str) -> dict:
    return get_success_data(api.activate_bms(store_id, MANAGER))


def read_store(api, store_id: str) -> dict:
    return get_success_data(api.get_store(store_id, ADMIN))


def setup_commissioned_store(api, clock: str = CLOCK_EPOCH, standard=None, **store_overrides) -> dict:
    """Register a store, publish a standard governing its scope, commission and
    activate the building management system.

    Returns {"store", "standard", "store_id", "standard_id"} where "store" is
    the representation after activation.
    """
    set_clock(api, clock)
    store = create_store(api, **store_overrides)
    if standard is None:
        standard = create_published_standard(
            api,
            climate_zone=store["climate_zone"],
            store_format=store["store_format"],
        )
    commissioned = commission_store(api, store["id"], standard["id"], store["version"])
    activated = activate_store_bms(api, store["id"])
    return {
        "store": activated,
        "store_id": store["id"],
        "standard": standard,
        "standard_id": standard["id"],
        "version_at_creation": store["version"],
        "version_at_commissioning": commissioned["version"],
    }


def setup_uncommissioned_store(api, clock: str = CLOCK_EPOCH, **store_overrides) -> dict:
    """Register a store and leave its building management system NOT_DEPLOYED."""
    set_clock(api, clock)
    store = create_store(api, **store_overrides)
    return {"store": store, "store_id": store["id"]}


# ----------------------------------------------------------------------
# Utility accounts, metering and bills
# ----------------------------------------------------------------------
def create_account(api, store_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_utility_account(store_id, f.create_utility_account_payload(**overrides), MANAGER)
    )


def ingest_intervals(api, account_id: str, intervals: list, headers=None) -> list:
    return get_success_data(
        api.ingest_demand_intervals(
            account_id, f.ingest_intervals_payload(intervals), headers or ANALYST
        )
    )


def create_bill(api, account_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_utility_bill(account_id, f.create_utility_bill_payload(**overrides), ANALYST)
    )


def recompute_bill(api, bill_id: str, headers=None) -> dict:
    return get_success_data(api.recompute_utility_bill(bill_id, headers or ANALYST))


def read_account(api, account_id: str) -> dict:
    return get_success_data(api.get_utility_account(account_id, MANAGER))


def setup_store_with_account(api, clock: str = CLOCK_EPOCH, store_overrides=None,
                             account_overrides=None, commissioned: bool = False) -> dict:
    """A store plus one utility account. The building management system is
    deployed only when commissioned is True."""
    store_overrides = store_overrides or {}
    account_overrides = account_overrides or {}
    if commissioned:
        ctx = setup_commissioned_store(api, clock=clock, **store_overrides)
    else:
        ctx = setup_uncommissioned_store(api, clock=clock, **store_overrides)
    account = create_account(api, ctx["store_id"], **account_overrides)
    ctx["account"] = account
    ctx["account_id"] = account["id"]
    return ctx


def setup_validated_bill(api, clock: str = CLOCK_EPOCH, store_overrides=None,
                         account_overrides=None, intervals=None, bill_overrides=None) -> dict:
    """An account with metered intervals and one recomputed bill."""
    ctx = setup_store_with_account(
        api, clock=clock, store_overrides=store_overrides, account_overrides=account_overrides
    )
    if intervals is None:
        intervals = [f.demand_interval("2026-06-15T14:00:00Z", 1200.0, True)]
    ingest_intervals(api, ctx["account_id"], intervals)
    bill = create_bill(api, ctx["account_id"], **(bill_overrides or {}))
    ctx["bill"] = recompute_bill(api, bill["id"])
    ctx["bill_id"] = bill["id"]
    return ctx


# ----------------------------------------------------------------------
# Demand response events
# ----------------------------------------------------------------------
def create_event(api, account_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_demand_response_event(
            account_id, f.create_demand_response_event_payload(**overrides), MANAGER
        )
    )


def notify_event(api, event_id: str) -> dict:
    return get_success_data(api.notify_demand_response_event(event_id, MANAGER))


def activate_event(api, event_id: str) -> dict:
    return get_success_data(api.activate_demand_response_event(event_id, MANAGER))


def settle_event(api, event_id: str) -> dict:
    return get_success_data(api.settle_demand_response_event(event_id, ANALYST))


def setup_notified_event(api, clock: str = CLOCK_EPOCH, store_overrides=None,
                         account_overrides=None, baseline_intervals=None,
                         event_overrides=None, commissioned: bool = False) -> dict:
    """An account whose event has been notified, freezing its baseline."""
    ctx = setup_store_with_account(
        api,
        clock=clock,
        store_overrides=store_overrides,
        account_overrides=account_overrides,
        commissioned=commissioned,
    )
    if baseline_intervals is None:
        baseline_intervals = [f.demand_interval("2026-07-15T14:00:00Z", 1200.0, True)]
    if baseline_intervals:
        ingest_intervals(api, ctx["account_id"], baseline_intervals)
    event = create_event(api, ctx["account_id"], **(event_overrides or {}))
    ctx["event_id"] = event["id"]
    ctx["event"] = notify_event(api, event["id"])
    return ctx


def setup_completed_event(api, clock: str = CLOCK_EPOCH, store_overrides=None,
                          account_overrides=None, baseline_intervals=None,
                          event_overrides=None, curtailment_intervals=None) -> dict:
    """An event notified, activated at its curtailment start and completed by the
    sweep once the clock passes its curtailment end."""
    ctx = setup_notified_event(
        api,
        clock=clock,
        store_overrides=store_overrides,
        account_overrides=account_overrides,
        baseline_intervals=baseline_intervals,
        event_overrides=event_overrides,
    )
    event = ctx["event"]
    if curtailment_intervals:
        ingest_intervals(api, ctx["account_id"], curtailment_intervals)
    set_clock(api, event["curtailment_start_iso"])
    ctx["event"] = activate_event(api, ctx["event_id"])
    ctx["sweep"] = set_clock(api, event["curtailment_end_iso"])
    return ctx


# ----------------------------------------------------------------------
# Refrigeration cases, readings and excursions
# ----------------------------------------------------------------------
def create_case(api, store_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_refrigeration_case(
            store_id, f.create_refrigeration_case_payload(**overrides), MANAGER
        )
    )


def post_reading(api, case_id: str, store_id: str, temp_f: float, reading_iso: str) -> dict:
    """A reading is ingested by the gateway of the case's own store."""
    return get_success_data(
        api.post_reading(
            case_id,
            f.reading_payload(temp_f, reading_iso),
            make_bms_gateway_headers(store_id),
        )
    )


def post_readings(api, case_id: str, store_id: str, readings: list) -> list:
    """readings is a list of (temp_f, reading_iso) pairs, posted in order."""
    return [post_reading(api, case_id, store_id, temp, iso) for temp, iso in readings]


def read_excursion(api, excursion_id: str) -> dict:
    return get_success_data(api.get_excursion(excursion_id, OFFICER))


def setup_case_on_commissioned_store(api, clock: str = CLOCK_EPOCH, store_overrides=None,
                                     case_overrides=None) -> dict:
    ctx = setup_commissioned_store(api, clock=clock, **(store_overrides or {}))
    case = create_case(api, ctx["store_id"], **(case_overrides or {}))
    ctx["case"] = case
    ctx["case_id"] = case["id"]
    return ctx


def setup_open_excursion(api, clock: str = "2026-08-01T09:00:00Z", store_overrides=None,
                         case_overrides=None, breach_temp_f: float = 43.0,
                         first_iso: str = "2026-08-01T04:00:00Z",
                         second_iso: str = "2026-08-01T04:15:00Z") -> dict:
    """Two consecutive breaching readings open an excursion in OPEN and move the
    case ARMED -> ALARM."""
    ctx = setup_case_on_commissioned_store(
        api, clock=clock, store_overrides=store_overrides, case_overrides=case_overrides
    )
    readings = post_readings(
        api,
        ctx["case_id"],
        ctx["store_id"],
        [(breach_temp_f, first_iso), (breach_temp_f, second_iso)],
    )
    ctx["readings"] = readings
    ctx["excursion_id"] = readings[-1]["excursion_id"]
    return ctx


def setup_escalated_excursion(api, clock: str = "2026-08-01T09:00:00Z", store_overrides=None,
                              case_overrides=None, breach_temp_f: float = 43.0) -> dict:
    """Three breaching readings spanning 120 minutes drive the excursion to
    ESCALATED and lock the store."""
    ctx = setup_open_excursion(
        api,
        clock=clock,
        store_overrides=store_overrides,
        case_overrides=case_overrides,
        breach_temp_f=breach_temp_f,
    )
    escalating = post_reading(
        api, ctx["case_id"], ctx["store_id"], breach_temp_f, "2026-08-01T06:00:00Z"
    )
    ctx["readings"].append(escalating)
    ctx["escalating_reading"] = escalating
    return ctx


# ----------------------------------------------------------------------
# Lighting overrides
# ----------------------------------------------------------------------
def create_override(api, store_id: str, **overrides) -> dict:
    """The requesting StoreManager is entity-backed on its own store."""
    return get_success_data(
        api.create_lighting_override(
            store_id,
            f.create_lighting_override_payload(**overrides),
            make_store_manager_headers(store_id),
        )
    )


def revoke_override(api, override_id: str, manager_user_id: str = "u_manager_1") -> dict:
    return get_success_data(
        api.revoke_lighting_override(override_id, make_energy_manager_headers(manager_user_id))
    )


def setup_store_with_override(api, clock: str = CLOCK_EPOCH, store_overrides=None,
                              override_overrides=None) -> dict:
    ctx = setup_commissioned_store(api, clock=clock, **(store_overrides or {}))
    override = create_override(api, ctx["store_id"], **(override_overrides or {}))
    ctx["override"] = override
    ctx["override_id"] = override["id"]
    return ctx


# ----------------------------------------------------------------------
# Fault diagnostics and work orders
# ----------------------------------------------------------------------
def create_fault(api, store_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_fault_diagnostic(
            store_id,
            f.create_fault_diagnostic_payload(**overrides),
            headers or TECH,
        )
    )


def triage_fault(api, fault_id: str, outcome: str = "WORK_ORDER", headers=None) -> dict:
    return get_success_data(
        api.triage_fault(fault_id, f.triage_payload(outcome), headers or TECH)
    )


def schedule_work_order(api, work_order_id: str, start_iso: str, end_iso: str) -> dict:
    return get_success_data(
        api.schedule_work_order(
            work_order_id, f.schedule_work_order_payload(start_iso, end_iso), TECH
        )
    )


def complete_work_order(api, work_order_id: str, note: str = "compressor replaced") -> dict:
    return get_success_data(
        api.complete_work_order(work_order_id, TECH, f.complete_work_order_payload(note))
    )


def setup_triaged_fault(api, clock: str = CLOCK_EPOCH, store_overrides=None,
                        fault_overrides=None) -> dict:
    """A commissioned store with one reported fault triaged into a work order."""
    ctx = setup_commissioned_store(api, clock=clock, **(store_overrides or {}))
    fault = create_fault(api, ctx["store_id"], **(fault_overrides or {}))
    triage = triage_fault(api, fault["id"])
    ctx["fault"] = fault
    ctx["fault_id"] = fault["id"]
    ctx["triage"] = triage
    ctx["work_order_id"] = triage["work_order_id"]
    return ctx


# ----------------------------------------------------------------------
# Capital retrofit projects
# ----------------------------------------------------------------------
def create_retrofit(api, store_id: str, proposer_user_id: str = "u_analyst_rt", **overrides) -> dict:
    return get_success_data(
        api.create_retrofit_project(
            store_id,
            f.create_retrofit_project_payload(**overrides),
            make_energy_analyst_headers(proposer_user_id),
        )
    )


def decide_retrofit(api, project_id: str, decision: str = "APPROVE",
                    approver_user_id: str = "u_mgr_rt") -> dict:
    return get_success_data(
        api.approve_retrofit_project(
            project_id,
            f.approve_retrofit_payload(decision),
            make_energy_manager_headers(approver_user_id),
        )
    )


def submit_measurement(api, project_id: str, **overrides) -> dict:
    return get_success_data(
        api.submit_retrofit_measurement(
            project_id, f.submit_measurement_payload(**overrides), ANALYST
        )
    )


def setup_approved_retrofit(api, clock: str = CLOCK_EPOCH, store_overrides=None,
                            project_overrides=None, proposer_user_id: str = "u_analyst_rt",
                            approver_user_id: str = "u_mgr_rt") -> dict:
    """A commissioned store with one retrofit project approved, so it has been
    re-scored on the risk-adjusted basis."""
    ctx = setup_commissioned_store(api, clock=clock, **(store_overrides or {}))
    project = create_retrofit(
        api, ctx["store_id"], proposer_user_id=proposer_user_id, **(project_overrides or {})
    )
    ctx["project_proposed"] = project
    ctx["project_id"] = project["id"]
    ctx["project"] = decide_retrofit(
        api, project["id"], "APPROVE", approver_user_id=approver_user_id
    )
    return ctx


def setup_verified_retrofit(api, clock: str = CLOCK_EPOCH, store_overrides=None,
                            project_overrides=None, measurement_overrides=None) -> dict:
    """An approved project carried through measurement and verification."""
    ctx = setup_approved_retrofit(
        api, clock=clock, store_overrides=store_overrides, project_overrides=project_overrides
    )
    ctx["project"] = submit_measurement(api, ctx["project_id"], **(measurement_overrides or {}))
    return ctx


# ----------------------------------------------------------------------
# Benchmarking portfolio
# ----------------------------------------------------------------------
def setup_benchmark_store(api, code: str, floor_area_sqft: int, billed_kwh: float,
                          climate_zone: str = "MIXED", store_format: str = "SUPERCENTER",
                          validate: bool = True, period_start_iso: str = "2026-06-01T00:00:00Z",
                          period_end_iso: str = "2026-07-01T00:00:00Z",
                          intervals=None) -> dict:
    """One peer-group member: a store, an account, metered intervals and a bill
    that is recomputed only when validate is True."""
    store = create_store(
        api,
        code=code,
        climate_zone=climate_zone,
        store_format=store_format,
        floor_area_sqft=floor_area_sqft,
    )
    account = create_account(api, store["id"])
    if intervals is None:
        intervals = [f.demand_interval("2026-06-15T14:00:00Z", 1200.0, True)]
    ingest_intervals(api, account["id"], intervals)
    bill = create_bill(
        api,
        account["id"],
        period_start_iso=period_start_iso,
        period_end_iso=period_end_iso,
        on_peak_kwh=billed_kwh * 0.4,
        off_peak_kwh=billed_kwh * 0.6,
        billed_kwh=billed_kwh,
        billed_peak_kw=1200.0,
        billed_amount_usd=58208.15,
    )
    if validate:
        bill = recompute_bill(api, bill["id"])
    return {
        "store": store,
        "store_id": store["id"],
        "account_id": account["id"],
        "bill": bill,
        "bill_id": bill["id"],
    }


# ----------------------------------------------------------------------
# Collection readers. Each returns the (rows, meta) pair of a list endpoint.
# ----------------------------------------------------------------------
def list_stores(api, headers=None, **params):
    return validate_paginated(api.list_stores(headers or ADMIN, params or None))


def list_standards(api, headers=None, **params):
    return validate_paginated(api.list_setpoint_standards(headers or MANAGER, params or None))


def list_accounts(api, store_id, headers=None, **params):
    return validate_paginated(
        api.list_store_utility_accounts(store_id, headers or MANAGER, params or None)
    )


def list_intervals(api, account_id, headers=None, **params):
    return validate_paginated(
        api.list_demand_intervals(account_id, headers or ANALYST, params or None)
    )


def list_bills(api, account_id, headers=None, **params):
    return validate_paginated(
        api.list_utility_bills(account_id, headers or ANALYST, params or None)
    )


def list_events(api, account_id, headers=None, **params):
    return validate_paginated(
        api.list_demand_response_events(account_id, headers or MANAGER, params or None)
    )


def list_cases(api, store_id, headers=None, **params):
    return validate_paginated(
        api.list_store_refrigeration_cases(store_id, headers or MANAGER, params or None)
    )


def list_excursions(api, case_id, headers=None, **params):
    return validate_paginated(
        api.list_case_excursions(case_id, headers or OFFICER, params or None)
    )


def list_overrides(api, store_id, headers=None, **params):
    return validate_paginated(
        api.list_store_lighting_overrides(store_id, headers or MANAGER, params or None)
    )


def list_faults(api, store_id, headers=None, **params):
    return validate_paginated(
        api.list_store_fault_diagnostics(store_id, headers or TECH, params or None)
    )


def list_work_orders(api, fault_id, headers=None, **params):
    return validate_paginated(
        api.list_fault_work_orders(fault_id, headers or TECH, params or None)
    )


def list_projects(api, store_id, headers=None, **params):
    return validate_paginated(
        api.list_store_retrofit_projects(store_id, headers or MANAGER, params or None)
    )


def find_row(rows, row_id):
    """The single row of a listing carrying the given id."""
    return next(row for row in rows if row["id"] == row_id)
