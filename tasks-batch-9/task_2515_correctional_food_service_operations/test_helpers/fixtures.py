"""Composite setup helpers.

The harness restarts the API against an empty database before every test, so
every helper here builds its preconditions from scratch. The helpers are layered:
each tier calls the tier below it and returns a dictionary of the rows it created,
so a test can stop at whatever depth it needs.

Tier 1  clock
Tier 2  contract, facility
Tier 3  active contract with a facility
Tier 4  facility with an ACTIVE menu cycle
Tier 5  locked forecast, planned batch, open service record, enrolled worker
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_success

from . import factories as f
from . import test_users as users
from .api_client import ApiClient
from .constants import CLOCK_DEFAULT_UTC

Json = Dict[str, Any]


# ---------------------------------------------------------------------------
# Tier 1 — logical clock
# ---------------------------------------------------------------------------


def set_clock(api: ApiClient, instant: str = CLOCK_DEFAULT_UTC) -> Json:
    """Pin the logical clock. Any recognised role may reposition it."""
    response = api.set_clock(instant, users.CONTRACT_ADMIN)
    return get_success_data(response)


# ---------------------------------------------------------------------------
# Tier 2 — contract and facility
# ---------------------------------------------------------------------------


def create_contract(api: ApiClient, **overrides: Any) -> Json:
    response = api.create_service_contract(
        f.service_contract_payload(**overrides), users.CONTRACT_ADMIN
    )
    return validate_success(response, 201)


def create_facility(api: ApiClient, contract_id: str, **overrides: Any) -> Json:
    response = api.create_facility(
        f.facility_payload(contract_id, **overrides), users.CONTRACT_ADMIN
    )
    return validate_success(response, 201)


# ---------------------------------------------------------------------------
# Tier 3 — an ACTIVE contract that owns a facility
# ---------------------------------------------------------------------------


def active_contract_with_facility(
    api: ApiClient,
    clock: str = CLOCK_DEFAULT_UTC,
    contract_overrides: Optional[Json] = None,
    facility_overrides: Optional[Json] = None,
) -> Json:
    """Clock pinned, contract created and activated, one facility registered."""
    set_clock(api, clock)
    contract = create_contract(api, **(contract_overrides or {}))
    facility = create_facility(api, contract["id"], **(facility_overrides or {}))
    activated = validate_success(
        api.activate_service_contract(contract["id"], users.CONTRACT_ADMIN)
    )
    return {"contract": activated, "facility": facility}


# ---------------------------------------------------------------------------
# Tier 4 — a facility with an ACTIVE menu cycle
# ---------------------------------------------------------------------------


def add_standard_day(api: ApiClient, cycle_id: str, cycle_day: int = 1) -> List[Json]:
    """Add the three standard components for one cycle day.

    Their per-item rounded figures sum to exactly 2800 kcal, 58.50 g of protein
    and 2000 mg of sodium at a raw cost of 315 cents.
    """
    items = []
    for builder in f.STANDARD_DAY_ITEMS:
        response = api.add_menu_cycle_item(
            cycle_id, builder(cycle_day=cycle_day), users.FOOD_SUPERVISOR
        )
        items.append(validate_success(response, 201))
    return items


def signed_menu_cycle(
    api: ApiClient,
    facility_id: str,
    cycle_length_days: int = 1,
    cycle_overrides: Optional[Json] = None,
) -> Json:
    """A NUTRITION_APPROVED cycle: complete for its length and signed."""
    overrides = dict(cycle_overrides or {})
    overrides.setdefault("cycle_length_days", cycle_length_days)
    cycle = validate_success(
        api.create_menu_cycle(
            f.menu_cycle_payload(facility_id, **overrides), users.FOOD_SUPERVISOR
        ),
        201,
    )
    items: List[Json] = []
    for day in range(1, cycle_length_days + 1):
        items.extend(add_standard_day(api, cycle["id"], cycle_day=day))
    signed = validate_success(
        api.nutrition_sign_menu_cycle(cycle["id"], users.DIETITIAN)
    )
    return {"cycle": signed, "items": items}


def facility_with_active_cycle(
    api: ApiClient,
    clock: str = CLOCK_DEFAULT_UTC,
    contract_overrides: Optional[Json] = None,
    facility_overrides: Optional[Json] = None,
) -> Json:
    """Full menu pathway: contract ACTIVE, cycle signed by the dietitian and
    activated by a different user, the contract administrator."""
    base = active_contract_with_facility(
        api,
        clock=clock,
        contract_overrides=contract_overrides,
        facility_overrides=facility_overrides,
    )
    signed = signed_menu_cycle(api, base["facility"]["id"])
    active_cycle = validate_success(
        api.activate_menu_cycle(signed["cycle"]["id"], users.CONTRACT_ADMIN)
    )
    return {
        "contract": base["contract"],
        "facility": base["facility"],
        "cycle": active_cycle,
        "items": signed["items"],
    }


# ---------------------------------------------------------------------------
# Tier 5 — roster, counts, forecasts, batches, service records, workers
# ---------------------------------------------------------------------------


def create_inmate(api: ApiClient, facility_id: str, **overrides: Any) -> Json:
    return validate_success(
        api.create_inmate(f.inmate_payload(facility_id, **overrides), users.OFFICER),
        201,
    )


def create_population_count(api: ApiClient, facility_id: str, **overrides: Any) -> Json:
    return validate_success(
        api.create_population_count(
            f.population_count_payload(facility_id, **overrides), users.OFFICER
        ),
        201,
    )


def locked_forecast(
    api: ApiClient,
    clock: str = CLOCK_DEFAULT_UTC,
    contract_overrides: Optional[Json] = None,
    facility_overrides: Optional[Json] = None,
    count_overrides: Optional[Json] = None,
    forecast_overrides: Optional[Json] = None,
) -> Json:
    """Everything needed to schedule production: an ACTIVE cycle, a population
    count and a LOCKED forecast."""
    base = facility_with_active_cycle(
        api,
        clock=clock,
        contract_overrides=contract_overrides,
        facility_overrides=facility_overrides,
    )
    facility_id = base["facility"]["id"]
    count = create_population_count(api, facility_id, **(count_overrides or {}))
    forecast = validate_success(
        api.create_meal_forecast(
            f.meal_forecast_payload(
                facility_id, count["id"], **(forecast_overrides or {})
            ),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )
    locked = validate_success(
        api.lock_meal_forecast(forecast["id"], users.FOOD_SUPERVISOR)
    )
    facility = validate_success(api.get_facility(facility_id, users.CONTRACT_ADMIN))
    return {
        "contract": base["contract"],
        "facility": facility,
        "cycle": base["cycle"],
        "items": base["items"],
        "population_count": count,
        "forecast": locked,
    }


def planned_batch(
    api: ApiClient,
    ctx: Optional[Json] = None,
    api_for_setup: Optional[ApiClient] = None,
    **batch_overrides: Any,
) -> Json:
    """A PLANNED / QA_PENDING batch against a locked forecast.

    `ctx` may be the dictionary returned by `locked_forecast`; when omitted the
    locked forecast is built here.
    """
    ctx = ctx or locked_forecast(api)
    facility = validate_success(
        api.get_facility(ctx["facility"]["id"], users.CONTRACT_ADMIN)
    )
    batch = validate_success(
        api.create_production_batch(
            f.production_batch_payload(
                facility["id"],
                ctx["forecast"]["id"],
                facility["version"],
                **batch_overrides,
            ),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )
    result = dict(ctx)
    result["facility"] = validate_success(
        api.get_facility(facility["id"], users.CONTRACT_ADMIN)
    )
    result["batch"] = batch
    return result


def open_service_record(
    api: ApiClient, ctx: Optional[Json] = None, **record_overrides: Any
) -> Json:
    """An OPEN service record whose expected tray count is frozen from the
    locked forecast."""
    ctx = ctx or locked_forecast(api)
    forecast = ctx["forecast"]
    payload = f.meal_service_record_payload(
        ctx["facility"]["id"],
        forecast["id"],
        service_date=forecast["service_date"],
        meal_slot=forecast["meal_slot"],
        **record_overrides,
    )
    record = validate_success(
        api.create_meal_service_record(payload, users.FOOD_SUPERVISOR), 201
    )
    result = dict(ctx)
    result["record"] = record
    return result


def closed_service_record(
    api: ApiClient, ctx: Optional[Json] = None, **record_overrides: Any
) -> Json:
    """A CLOSED service record with the contract ledger already posted."""
    ctx = open_service_record(api, ctx, **record_overrides)
    contract = validate_success(
        api.get_service_contract(ctx["contract"]["id"], users.CONTRACT_ADMIN)
    )
    closed = validate_success(
        api.close_meal_service_record(
            ctx["record"]["id"],
            f.close_service_record_payload(contract["version"]),
            users.FOOD_SUPERVISOR,
        )
    )
    result = dict(ctx)
    result["record"] = closed
    result["contract"] = validate_success(
        api.get_service_contract(ctx["contract"]["id"], users.CONTRACT_ADMIN)
    )
    return result


def enrolled_worker(
    api: ApiClient,
    facility_id: str,
    booking_number: str = "BK-W001",
    housing_unit: str = "GENERAL",
    **worker_overrides: Any,
) -> Json:
    """An inmate booked into the facility and enrolled as a CLEARED, UNASSIGNED
    kitchen worker."""
    inmate = create_inmate(
        api, facility_id, booking_number=booking_number, housing_unit=housing_unit
    )
    worker = validate_success(
        api.create_inmate_worker(
            f.inmate_worker_payload(inmate["id"], facility_id, **worker_overrides),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )
    return {"inmate": inmate, "worker": worker}


def issued_tool(
    api: ApiClient,
    facility_id: str,
    worker_id: str,
    **issuance_overrides: Any,
) -> Json:
    return validate_success(
        api.create_tool_issuance(
            f.tool_issuance_payload(facility_id, worker_id, **issuance_overrides),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )


def filed_grievance(
    api: ApiClient, inmate_id: str, facility_id: str, **overrides: Any
) -> Json:
    return validate_success(
        api.create_grievance(
            f.grievance_payload(inmate_id, facility_id, **overrides),
            users.GRIEVANCE_COORD,
        ),
        201,
    )


# ---------------------------------------------------------------------------
# Small read helpers
# ---------------------------------------------------------------------------


def read_facility(api: ApiClient, facility_id: str) -> Json:
    return validate_success(api.get_facility(facility_id, users.CONTRACT_ADMIN))


def read_contract(api: ApiClient, contract_id: str) -> Json:
    return validate_success(api.get_service_contract(contract_id, users.CONTRACT_ADMIN))


def read_batch(api: ApiClient, batch_id: str) -> Json:
    return validate_success(api.get_production_batch(batch_id, users.FOOD_SUPERVISOR))


def read_worker(api: ApiClient, worker_id: str) -> Json:
    return validate_success(api.get_inmate_worker(worker_id, users.FOOD_SUPERVISOR))


def read_tool(api: ApiClient, issuance_id: str) -> Json:
    return validate_success(api.get_tool_issuance(issuance_id, users.FOOD_SUPERVISOR))


def read_diet_order(api: ApiClient, order_id: str) -> Json:
    return validate_success(api.get_diet_order(order_id, users.DIETITIAN))


def read_grievance(api: ApiClient, grievance_id: str) -> Json:
    return validate_success(api.get_grievance(grievance_id, users.GRIEVANCE_COORD))


def read_service_record(api: ApiClient, record_id: str) -> Json:
    return validate_success(
        api.get_meal_service_record(record_id, users.FOOD_SUPERVISOR)
    )


def read_substitution(api: ApiClient, substitution_id: str) -> Json:
    return validate_success(
        api.get_menu_substitution(substitution_id, users.FOOD_SUPERVISOR)
    )
