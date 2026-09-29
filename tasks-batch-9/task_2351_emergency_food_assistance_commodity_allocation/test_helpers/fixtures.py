"""Composite setup helpers.

Every test starts against an empty database, so every precondition has to be
built from scratch through the API. The helpers below are layered:

* tier 1 — clock primitives and read helpers
* tier 2 — single-entity creators returning the created row
* tier 3 — eligibility paperwork and posted inventory
* tier 4 — allocation cycles taken to ALLOCATED / OPEN with entitlement rows
* tier 5 — whole-program scenarios (approved order, scheduled dock, delivered
  order, open recall) that several designs share

Fixture helpers use ``get_success_data`` so a setup step that answers 200 or 201
is accepted without every caller restating which one applies.
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .api_client import ApiClient
from .constants import CLOCK_EPOCH
from .test_users import (
    make_agency_coordinator_headers,
    make_compliance_reviewer_headers,
    make_second_compliance_reviewer_headers,
    make_state_admin_headers,
    make_warehouse_operator_headers,
)
from .types import FormulaVariant, MonitorPolicy, UrbanRural

ADMIN = make_state_admin_headers()
REVIEWER = make_compliance_reviewer_headers()
SECOND_REVIEWER = make_second_compliance_reviewer_headers()


# ===========================================================================
# Tier 1 — clock and generic reads
# ===========================================================================

def set_clock(api: ApiClient, instant: str) -> Dict[str, Any]:
    return get_success_data(api.set_clock(instant, headers=ADMIN))


def read_clock(api: ApiClient) -> Dict[str, Any]:
    return get_success_data(api.get_clock())


def reset_clock(api: ApiClient) -> Dict[str, Any]:
    return set_clock(api, CLOCK_EPOCH)


def list_rows(response) -> List[Dict[str, Any]]:
    rows, _meta = validate_paginated(response)
    return rows


def list_rows_and_meta(response):
    return validate_paginated(response)


# ===========================================================================
# Tier 2 — single-entity creators
# ===========================================================================

def create_service_area(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_service_area(f.service_area_payload(**kwargs), headers=ADMIN)
    )


def create_agency(api: ApiClient, service_area_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_agency(f.agency_payload(service_area_id, **kwargs), headers=ADMIN)
    )


def create_commodity(api: ApiClient, payload: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(api.create_commodity(payload, headers=ADMIN))


def create_bulk_rice(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    return create_commodity(api, f.bulk_rice_payload(**kwargs))


def create_frozen_chicken(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    return create_commodity(api, f.frozen_chicken_payload(**kwargs))


def create_canned_peaches(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    return create_commodity(api, f.canned_peaches_payload(**kwargs))


def create_warehouse(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_warehouse(f.warehouse_payload(**kwargs), headers=ADMIN)
    )


def create_inventory_lot(
    api: ApiClient, commodity_id: str, warehouse_id: str, **kwargs: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_inventory_lot(
            f.inventory_lot_payload(commodity_id, warehouse_id, **kwargs), headers=ADMIN
        )
    )


def post_inventory_lot(api: ApiClient, lot_id: str) -> Dict[str, Any]:
    return get_success_data(api.post_inventory_lot(lot_id, headers=ADMIN))


def create_posted_lot(
    api: ApiClient, commodity_id: str, warehouse_id: str, **kwargs: Any
) -> Dict[str, Any]:
    """Record a receipt and post it, so its cases are visible to reservation."""
    lot = create_inventory_lot(api, commodity_id, warehouse_id, **kwargs)
    return post_inventory_lot(api, lot["id"])


def read_lot(api: ApiClient, lot_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_inventory_lot(lot_id, headers=ADMIN))


def read_agency(api: ApiClient, agency_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_agency(agency_id, headers=ADMIN))


def read_service_area(api: ApiClient, service_area_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_service_area(service_area_id, headers=ADMIN))


def read_warehouse(api: ApiClient, warehouse_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_warehouse(warehouse_id, headers=ADMIN))


def read_cycle(api: ApiClient, cycle_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_allocation_cycle(cycle_id, headers=ADMIN))


def read_order(api: ApiClient, order_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_commodity_order(order_id, headers=ADMIN))


def read_order_lines(api: ApiClient, order_id: str) -> List[Dict[str, Any]]:
    return list_rows(api.list_order_lines_of_order(order_id, headers=ADMIN))


def read_appointment(api: ApiClient, appointment_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_delivery_appointment(appointment_id, headers=ADMIN))


def read_transfer(api: ApiClient, transfer_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_inventory_transfer(transfer_id, headers=ADMIN))


def read_recall(api: ApiClient, recall_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_recall(recall_id, headers=ADMIN))


def read_recall_action(api: ApiClient, action_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_recall_action(action_id, headers=ADMIN))


def read_distribution(api: ApiClient, distribution_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_household_distribution(distribution_id, headers=ADMIN))


# ===========================================================================
# Tier 3 — eligibility paperwork and posture
# ===========================================================================

def record_training(
    api: ApiClient,
    agency_id: str,
    completed_at: str = "2026-07-01T00:00:00Z",
    attendee_count: int = 4,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_civil_rights_training(
            agency_id,
            f.civil_rights_training_payload(completed_at, attendee_count),
            headers=REVIEWER,
        )
    )


def renew_agreement(
    api: ApiClient,
    agency_id: str,
    agreement_start_date: str = "2026-07-01",
    agreement_end_date: str = "2027-06-30",
) -> Dict[str, Any]:
    return get_success_data(
        api.create_agreement_renewal(
            agency_id,
            f.agreement_renewal_payload(agreement_start_date, agreement_end_date),
            headers=REVIEWER,
        )
    )


def make_agency_eligible(
    api: ApiClient,
    agency_id: str,
    completed_at: str = "2026-07-01T00:00:00Z",
    agreement_start_date: str = "2026-07-01",
    agreement_end_date: str = "2027-06-30",
) -> Dict[str, Any]:
    """Training first, then the agreement — the only order the PRD permits."""
    record_training(api, agency_id, completed_at=completed_at)
    return renew_agreement(api, agency_id, agreement_start_date, agreement_end_date)


def create_eligible_agency(
    api: ApiClient, service_area_id: str, **kwargs: Any
) -> Dict[str, Any]:
    agency = create_agency(api, service_area_id, **kwargs)
    return make_agency_eligible(api, agency["id"])


def run_compliance_sweep(api: ApiClient) -> Any:
    response = api.run_compliance_sweep(headers=ADMIN)
    return get_success_data(response)


def run_monitor(api: ApiClient, warehouse_id: Optional[str] = None) -> Any:
    payload: Dict[str, Any] = {}
    if warehouse_id is not None:
        payload["warehouse_id"] = warehouse_id
    return get_success_data(api.run_inventory_monitor(headers=ADMIN, payload=payload))


# ===========================================================================
# Tier 4 — allocation cycles and entitlement rows
# ===========================================================================

def create_cycle(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_allocation_cycle(f.allocation_cycle_payload(**kwargs), headers=ADMIN)
    )


def compute_allocations(api: ApiClient, cycle_id: str) -> Dict[str, Any]:
    get_success_data(api.compute_allocations(cycle_id, headers=ADMIN))
    return read_cycle(api, cycle_id)


def open_window(api: ApiClient, cycle_id: str) -> Dict[str, Any]:
    return get_success_data(api.open_order_window(cycle_id, headers=ADMIN))


def close_window(api: ApiClient, cycle_id: str) -> Dict[str, Any]:
    return get_success_data(api.close_order_window(cycle_id, headers=ADMIN))


def finalize_cycle(api: ApiClient, cycle_id: str) -> Dict[str, Any]:
    return get_success_data(api.finalize_cycle(cycle_id, headers=ADMIN))


def list_cycle_allocations(api: ApiClient, cycle_id: str) -> List[Dict[str, Any]]:
    return list_rows(api.list_cycle_allocations(cycle_id, headers=ADMIN))


def read_allocation(api: ApiClient, cycle_id: str, agency_id: str) -> Dict[str, Any]:
    """The entitlement row of one agency in one cycle, including its live version."""
    rows = list_rows(
        api.list_agency_allocations(
            headers=ADMIN, params={"cycle_id": cycle_id, "agency_id": agency_id}
        )
    )
    assert len(rows) == 1, (
        f"expected one entitlement for agency {agency_id} in cycle {cycle_id}, got {len(rows)}"
    )
    return rows[0]


def admin_funds_report(api: ApiClient, cycle_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_admin_funds_report(cycle_id, headers=ADMIN))


# ===========================================================================
# Tier 4b — orders, lines, review
# ===========================================================================

def create_order(
    api: ApiClient,
    cycle_id: str,
    agency_id: str,
    warehouse_id: str,
    expected_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Start a draft order, reading the entitlement version when not supplied."""
    if expected_version is None:
        expected_version = read_allocation(api, cycle_id, agency_id)["version"]
    return get_success_data(
        api.create_commodity_order(
            f.commodity_order_payload(cycle_id, agency_id, warehouse_id, expected_version),
            headers=make_agency_coordinator_headers(agency_id),
        )
    )


def add_line(
    api: ApiClient, order_id: str, agency_id: str, commodity_id: str, cases_requested: int = 10
) -> Dict[str, Any]:
    return get_success_data(
        api.add_order_line(
            order_id,
            f.order_line_payload(commodity_id, cases_requested),
            headers=make_agency_coordinator_headers(agency_id),
        )
    )


def submit_order(api: ApiClient, order_id: str, agency_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.submit_order(order_id, headers=make_agency_coordinator_headers(agency_id))
    )


def return_for_revision(
    api: ApiClient, order_id: str, reviewer_headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.return_order_for_revision(order_id, headers=reviewer_headers or REVIEWER)
    )


def approve_order(
    api: ApiClient,
    order_id: str,
    reviewer_headers: Optional[Dict[str, str]] = None,
    line_adjustments: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    payload = (
        f.line_adjustments_payload(list(line_adjustments))
        if line_adjustments is not None
        else {}
    )
    return get_success_data(
        api.approve_order(
            order_id, headers=reviewer_headers or SECOND_REVIEWER, payload=payload
        )
    )


def cancel_order(
    api: ApiClient, order_id: str, agency_id: str, cancel_reason: str = "WITHDRAWN"
) -> Dict[str, Any]:
    return get_success_data(
        api.cancel_order(
            order_id,
            f.cancel_reason_payload(cancel_reason),
            headers=make_agency_coordinator_headers(agency_id),
        )
    )


# ===========================================================================
# Tier 4c — dock appointments, transfers, recalls, distributions
# ===========================================================================

def book_appointment(
    api: ApiClient,
    order_id: str,
    dock_number: int = 1,
    window_start: str = "2026-08-10T10:00:00Z",
    window_end: str = "2026-08-10T12:00:00Z",
) -> Dict[str, Any]:
    return get_success_data(
        api.create_delivery_appointment(
            f.delivery_appointment_payload(order_id, dock_number, window_start, window_end),
            headers=ADMIN,
        )
    )


def confirm_delivery(api: ApiClient, appointment_id: str, warehouse_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.confirm_delivery(
            appointment_id, headers=make_warehouse_operator_headers(warehouse_id)
        )
    )


def propose_transfer(
    api: ApiClient,
    lot_id: str,
    agency_id: str,
    cases: int,
    expected_version: Optional[int] = None,
) -> Dict[str, Any]:
    if expected_version is None:
        expected_version = read_lot(api, lot_id)["version"]
    return get_success_data(
        api.create_inventory_transfer(
            f.inventory_transfer_payload(lot_id, agency_id, cases, expected_version),
            headers=ADMIN,
        )
    )


def accept_transfer(api: ApiClient, transfer_id: str, agency_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.accept_inventory_transfer(
            transfer_id, headers=make_agency_coordinator_headers(agency_id)
        )
    )


def decline_transfer(
    api: ApiClient, transfer_id: str, agency_id: str, decline_reason: str = "NO_DRY_SPACE"
) -> Dict[str, Any]:
    return get_success_data(
        api.decline_inventory_transfer(
            transfer_id,
            f.decline_reason_payload(decline_reason),
            headers=make_agency_coordinator_headers(agency_id),
        )
    )


def raise_recall(api: ApiClient, source_lot_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_recall(f.recall_payload(source_lot_id, **kwargs), headers=ADMIN)
    )


def dispatch_notices(api: ApiClient, recall_id: str) -> Dict[str, Any]:
    return get_success_data(api.dispatch_recall_notices(recall_id, headers=ADMIN))


def recall_actions_of(api: ApiClient, recall_id: str) -> List[Dict[str, Any]]:
    return list_rows(api.list_recall_actions_of_recall(recall_id, headers=ADMIN))


def acknowledge_action(api: ApiClient, action_id: str, agency_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.acknowledge_recall_action(
            action_id, headers=make_agency_coordinator_headers(agency_id)
        )
    )


def report_disposition(
    api: ApiClient, action_id: str, agency_id: str, disposition: str, cases_accounted: int
) -> Dict[str, Any]:
    return get_success_data(
        api.report_recall_disposition(
            action_id,
            f.disposition_payload(disposition, cases_accounted),
            headers=make_agency_coordinator_headers(agency_id),
        )
    )


def record_distribution(
    api: ApiClient, agency_id: str, cycle_id: str, commodity_id: str, **kwargs: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_household_distribution(
            f.household_distribution_payload(agency_id, cycle_id, commodity_id, **kwargs),
            headers=make_agency_coordinator_headers(agency_id),
        )
    )


def void_distribution(
    api: ApiClient, distribution_id: str, agency_id: str, void_reason: str = "DATA_ENTRY_ERROR"
) -> Dict[str, Any]:
    return get_success_data(
        api.void_household_distribution(
            distribution_id,
            f.void_reason_payload(void_reason),
            headers=make_agency_coordinator_headers(agency_id),
        )
    )


# ===========================================================================
# Tier 5 — whole-program scenarios
# ===========================================================================

def build_program(
    api: ApiClient,
    *,
    poverty_population: int = 40000,
    agency_name: str = "Alpha Food Bank",
    cold_storage_pallet_capacity: int = 10,
    prior_period_pounds_distributed: Optional[float] = None,
    prior_period_allocated_cases: Optional[int] = None,
    warehouse_kwargs: Optional[Dict[str, Any]] = None,
    commodity_payloads: Optional[Sequence[Dict[str, Any]]] = None,
    lot_cases: int = 300,
    post_lots: bool = True,
    allocatable_cases: int = 1000,
    admin_funds_pool_cents: int = 0,
    formula_variant: str = FormulaVariant.STANDARD,
    order_window_open_at: str = "2026-08-05T00:00:00Z",
    order_window_close_at: str = "2026-08-20T00:00:00Z",
    compute: bool = True,
    open_the_window: bool = True,
    clock_after_open: Optional[str] = "2026-08-06T00:00:00Z",
) -> Dict[str, Any]:
    """One eligible agency, one warehouse, posted inventory and a live cycle.

    Returns a dict with ``service_area``, ``agency``, ``warehouse``,
    ``commodities`` (keyed by code), ``lots`` (keyed by commodity code),
    ``cycle`` and, once the run has happened, ``allocation``.
    """
    agency_kwargs: Dict[str, Any] = {
        "name": agency_name,
        "cold_storage_pallet_capacity": cold_storage_pallet_capacity,
    }
    if prior_period_pounds_distributed is not None:
        agency_kwargs["prior_period_pounds_distributed"] = prior_period_pounds_distributed
    if prior_period_allocated_cases is not None:
        agency_kwargs["prior_period_allocated_cases"] = prior_period_allocated_cases

    service_area = create_service_area(api, poverty_population=poverty_population)
    agency = create_agency(api, service_area["id"], **agency_kwargs)
    agency = make_agency_eligible(api, agency["id"])

    warehouse = create_warehouse(api, **(warehouse_kwargs or {}))

    payloads = list(commodity_payloads or [f.bulk_rice_payload()])
    commodities: Dict[str, Dict[str, Any]] = {}
    lots: Dict[str, Dict[str, Any]] = {}
    for index, payload in enumerate(payloads):
        commodity = create_commodity(api, payload)
        commodities[commodity["code"]] = commodity
        lot_kwargs = {
            "federal_lot_code": f"FL-{index + 1:04d}",
            "cases_received": lot_cases,
        }
        if post_lots:
            lots[commodity["code"]] = create_posted_lot(
                api, commodity["id"], warehouse["id"], **lot_kwargs
            )
        else:
            lots[commodity["code"]] = create_inventory_lot(
                api, commodity["id"], warehouse["id"], **lot_kwargs
            )

    cycle = create_cycle(
        api,
        offered_commodity_codes=list(commodities.keys()),
        allocatable_cases=allocatable_cases,
        admin_funds_pool_cents=admin_funds_pool_cents,
        formula_variant=formula_variant,
        order_window_open_at=order_window_open_at,
        order_window_close_at=order_window_close_at,
    )

    env: Dict[str, Any] = {
        "service_area": service_area,
        "agency": agency,
        "warehouse": warehouse,
        "commodities": commodities,
        "lots": lots,
        "cycle": cycle,
        "coordinator": make_agency_coordinator_headers(agency["id"]),
        "operator": make_warehouse_operator_headers(warehouse["id"]),
    }

    if compute:
        env["cycle"] = compute_allocations(api, cycle["id"])
        env["allocation"] = read_allocation(api, cycle["id"], agency["id"])
    if compute and open_the_window:
        env["cycle"] = open_window(api, cycle["id"])
        if clock_after_open:
            set_clock(api, clock_after_open)

    return env


def build_two_agency_program(
    api: ApiClient,
    *,
    area_specs: Sequence[Dict[str, Any]] = (),
    allocatable_cases: int = 100,
    admin_funds_pool_cents: int = 0,
    formula_variant: str = FormulaVariant.STANDARD,
    compute: bool = True,
) -> Dict[str, Any]:
    """Two counties, one eligible agency each — the shape every share test needs.

    ``area_specs`` entries take ``poverty_population``, ``agency_name``,
    ``prior_period_pounds_distributed`` and ``prior_period_allocated_cases``.
    """
    specs = list(area_specs) or [
        {"poverty_population": 30000, "agency_name": "Alpha Food Bank"},
        {"poverty_population": 10000, "agency_name": "Bravo Pantry"},
    ]
    areas: List[Dict[str, Any]] = []
    agencies: List[Dict[str, Any]] = []
    for index, spec in enumerate(specs):
        area = create_service_area(
            api,
            name=f"County {index + 1}",
            county_code=f"CC{index + 1:02d}",
            poverty_population=spec.get("poverty_population", 10000),
        )
        agency_kwargs: Dict[str, Any] = {
            "name": spec.get("agency_name", f"Agency {index + 1}"),
        }
        for key in (
            "prior_period_pounds_distributed",
            "prior_period_allocated_cases",
            "cold_storage_pallet_capacity",
        ):
            if key in spec:
                agency_kwargs[key] = spec[key]
        agency = create_agency(api, area["id"], **agency_kwargs)
        agency = make_agency_eligible(api, agency["id"])
        areas.append(read_service_area(api, area["id"]))
        agencies.append(agency)

    commodity = create_bulk_rice(api)
    warehouse = create_warehouse(api)
    cycle = create_cycle(
        api,
        offered_commodity_codes=[commodity["code"]],
        allocatable_cases=allocatable_cases,
        admin_funds_pool_cents=admin_funds_pool_cents,
        formula_variant=formula_variant,
    )
    env: Dict[str, Any] = {
        "service_areas": areas,
        "agencies": agencies,
        "commodity": commodity,
        "warehouse": warehouse,
        "cycle": cycle,
    }
    if compute:
        env["cycle"] = compute_allocations(api, cycle["id"])
        env["allocations"] = list_cycle_allocations(api, cycle["id"])
    return env


def build_approved_order(
    api: ApiClient,
    env: Dict[str, Any],
    *,
    commodity_code: str = "BULK_RICE",
    cases_requested: int = 10,
    reviewer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Draft, line, submit and approve one order inside ``env``'s open cycle."""
    agency = env["agency"]
    order = create_order(api, env["cycle"]["id"], agency["id"], env["warehouse"]["id"])
    line = add_line(
        api,
        order["id"],
        agency["id"],
        env["commodities"][commodity_code]["id"],
        cases_requested,
    )
    submit_order(api, order["id"], agency["id"])
    order = approve_order(api, order["id"], reviewer_headers=reviewer_headers)
    env["order"] = order
    env["line"] = line
    return order


def build_scheduled_order(
    api: ApiClient,
    env: Dict[str, Any],
    *,
    commodity_code: str = "BULK_RICE",
    cases_requested: int = 10,
    dock_number: int = 1,
    window_start: str = "2026-08-10T10:00:00Z",
    window_end: str = "2026-08-10T12:00:00Z",
) -> Dict[str, Any]:
    build_approved_order(
        api, env, commodity_code=commodity_code, cases_requested=cases_requested
    )
    appointment = book_appointment(
        api, env["order"]["id"], dock_number, window_start, window_end
    )
    env["appointment"] = appointment
    return appointment


def build_delivered_order(
    api: ApiClient,
    env: Dict[str, Any],
    *,
    commodity_code: str = "BULK_RICE",
    cases_requested: int = 10,
    window_start: str = "2026-08-10T10:00:00Z",
    window_end: str = "2026-08-10T12:00:00Z",
    delivery_instant: str = "2026-08-10T10:00:00Z",
) -> Dict[str, Any]:
    """Take one order all the way to DELIVERED so the agency holds cases on hand."""
    build_scheduled_order(
        api,
        env,
        commodity_code=commodity_code,
        cases_requested=cases_requested,
        window_start=window_start,
        window_end=window_end,
    )
    set_clock(api, delivery_instant)
    appointment = confirm_delivery(
        api, env["appointment"]["id"], env["warehouse"]["id"]
    )
    env["appointment"] = appointment
    return appointment


def build_agency_with_cases_on_hand(
    api: ApiClient, env: Dict[str, Any], *, cases: int = 20, commodity_code: str = "BULK_RICE"
) -> Dict[str, Any]:
    """Move cases into the agency term of the case ledger through a transfer."""
    lot = env["lots"][commodity_code]
    transfer = propose_transfer(api, lot["id"], env["agency"]["id"], cases)
    accept_transfer(api, transfer["id"], env["agency"]["id"])
    env["transfer"] = read_transfer(api, transfer["id"])
    env["agency"] = read_agency(api, env["agency"]["id"])
    return env["agency"]


def build_open_recall_with_action(
    api: ApiClient,
    env: Dict[str, Any],
    *,
    commodity_code: str = "BULK_RICE",
    recall_class: str = "CLASS_I",
    exposed_cases: int = 20,
) -> Dict[str, Any]:
    """An agency holding transferred cases, then a recall raised on the source lot.

    The transfer gives the agency downstream exposure, so raising the recall
    creates exactly one recall action.
    """
    build_agency_with_cases_on_hand(api, env, cases=exposed_cases, commodity_code=commodity_code)
    recall = raise_recall(
        api, env["lots"][commodity_code]["id"], recall_class=recall_class
    )
    env["recall"] = recall
    env["recall_actions"] = recall_actions_of(api, recall["id"])
    return recall


COLD_WAREHOUSE_KWARGS = {
    "name": "WH Cold",
    "dock_count": 2,
    "dry_pallet_capacity": 100,
    "cold_pallet_capacity": 50,
    "frozen_pallet_capacity": 2,
}

DRY_ONLY_WAREHOUSE_KWARGS = {
    "name": "WH Dry",
    "dock_count": 2,
    "dry_pallet_capacity": 100,
    "cold_pallet_capacity": 0,
    "frozen_pallet_capacity": 0,
}

SHELF_LIFE_WAREHOUSE_KWARGS = {
    "name": "WH South",
    "dock_count": 2,
    "dry_pallet_capacity": 100,
    "cold_pallet_capacity": 50,
    "frozen_pallet_capacity": 20,
    "monitor_policy": MonitorPolicy.SHELF_LIFE_BASED,
}


def create_warehouse_with_policy(
    api: ApiClient, monitor_policy: str, **kwargs: Any
) -> Dict[str, Any]:
    payload = f.warehouse_payload(**kwargs)
    payload["monitor_policy"] = monitor_policy
    return get_success_data(api.create_warehouse(payload, headers=ADMIN))


def read_entitlement(api: ApiClient, allocation_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_agency_allocation(allocation_id, headers=ADMIN))


_PAPERWORK_KEYS = ("training", "attendee_count", "agreement")


def build_areas_and_agencies(
    api: ApiClient, area_specs: Sequence[Dict[str, Any]]
) -> Dict[str, Any]:
    """Create one service area per spec together with its agencies and paperwork.

    An area spec takes ``name``, ``county_code``, ``poverty_population``,
    ``urban_rural`` and an ``agencies`` list. Each agency spec takes the agency
    input fields plus ``training`` (the ``completed_at`` instant of a civil
    rights training, or absent for none), ``attendee_count`` and ``agreement``
    (a ``(agreement_start_date, agreement_end_date)`` pair, or absent for none).

    Returns ``areas`` re-read after all paperwork and ``agencies`` flattened in
    creation order.
    """
    areas: List[Dict[str, Any]] = []
    agencies: List[Dict[str, Any]] = []
    created_areas: List[str] = []
    for spec in area_specs:
        area_kwargs = {
            key: spec[key]
            for key in ("name", "county_code", "poverty_population", "urban_rural")
            if key in spec
        }
        area = create_service_area(api, **area_kwargs)
        created_areas.append(area["id"])
        for agency_spec in spec.get("agencies", []):
            agency_kwargs = {
                key: value
                for key, value in agency_spec.items()
                if key not in _PAPERWORK_KEYS
            }
            agency = create_agency(api, area["id"], **agency_kwargs)
            if agency_spec.get("training"):
                record_training(
                    api,
                    agency["id"],
                    completed_at=agency_spec["training"],
                    attendee_count=agency_spec.get("attendee_count", 4),
                )
            if agency_spec.get("agreement"):
                start, end = agency_spec["agreement"]
                renew_agreement(api, agency["id"], start, end)
            agencies.append(read_agency(api, agency["id"]))
    areas = [read_service_area(api, area_id) for area_id in created_areas]
    return {"areas": areas, "agencies": agencies}


def three_county_roster(
    training: str = "2026-07-01T00:00:00Z",
    agreement: Sequence[str] = ("2026-07-01", "2027-06-30"),
) -> List[Dict[str, Any]]:
    """Three counties of differing poverty, one eligible agency in each."""
    rows = (
        ("Area One", "C001", 40000, UrbanRural.URBAN, "Agency One", 120000, 400, 4),
        ("Area Two", "C002", 25000, UrbanRural.RURAL, "Agency Two", 90000, 380, 3),
        ("Area Three", "C003", 35000, UrbanRural.URBAN, "Agency Three", 30000, 200, 2),
    )
    return [
        {
            "name": name,
            "county_code": county_code,
            "poverty_population": poverty_population,
            "urban_rural": urban_rural,
            "agencies": [
                {
                    "name": agency_name,
                    "cold_storage_pallet_capacity": 10,
                    "prior_period_pounds_distributed": prior_pounds,
                    "prior_period_allocated_cases": prior_cases,
                    "training": training,
                    "attendee_count": attendees,
                    "agreement": tuple(agreement),
                }
            ],
        }
        for (
            name,
            county_code,
            poverty_population,
            urban_rural,
            agency_name,
            prior_pounds,
            prior_cases,
            attendees,
        ) in rows
    ]


__all__ = [name for name in dir() if not name.startswith("_")]
