"""Composite setup helpers for the Community Kitchen Meal Program API.

Every test runs against an empty database (the runner restarts the server
before each test), so each helper builds its preconditions from scratch using
only endpoints declared in PRD section 4.  Setup calls use the lenient
`get_success_data` validator so a broken precondition surfaces as a clear
"Setup step failed" rather than a confusing assertion later.
"""
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_equipment_asset_payload,
    create_food_batch_payload,
    create_guest_payload,
    create_meal_order_payload,
    create_meal_service_payload,
    create_menu_day_payload,
    create_menu_item_payload,
    create_site_payload,
    create_volunteer_payload,
    create_volunteer_shift_payload,
    create_waste_log_payload,
)
from .test_users import (
    make_food_safety_officer_headers,
    make_kitchen_manager_headers,
    make_program_admin_headers,
    make_volunteer_headers,
)

ADMIN = make_program_admin_headers()
MANAGER = make_kitchen_manager_headers()
OFFICER = make_food_safety_officer_headers()


# ---------------------------------------------------------------------------
# Tier 0 — primitive steps
# ---------------------------------------------------------------------------


def set_clock(to_iso8601: str) -> Dict[str, Any]:
    """Advance the logical clock (ProgramAdmin-only, PRD 2.5)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_site(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_site(create_site_payload(**overrides), ADMIN))


def create_menu_day(site_id: str, service_date: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_menu_day(
            create_menu_day_payload(site_id, service_date, **overrides), MANAGER
        )
    )


def create_menu_item(menu_day_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_menu_item(menu_day_id, create_menu_item_payload(**overrides), MANAGER)
    )


def create_food_batch(site_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_food_batch(create_food_batch_payload(site_id, **overrides), MANAGER)
    )


def inspect_batch(batch_id: str, result: str = "PASSED") -> Dict[str, Any]:
    """begin-inspection + record-inspection.  Returns the post-record batch."""
    get_success_data(api_client.begin_inspection(batch_id, OFFICER))
    return get_success_data(api_client.record_inspection(batch_id, {"result": result}, OFFICER))


def create_accepted_batch(site_id: str, **overrides: Any) -> Dict[str, Any]:
    """Receive a batch and drive it RECEIVED -> INSPECTING -> ACCEPTED."""
    batch = create_food_batch(site_id, **overrides)
    return inspect_batch(batch["id"], "PASSED")


def allocate(menu_item_id: str, food_batch_id: str, servings: int) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_allocation(
            menu_item_id, {"food_batch_id": food_batch_id, "servings": servings}, MANAGER
        )
    )


def confirm_item(menu_item_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.confirm_menu_item(menu_item_id, MANAGER))


def create_guest(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_guest(create_guest_payload(**overrides), MANAGER))


def create_volunteer(**overrides: Any) -> Dict[str, Any]:
    defaults = {
        "certification_level": "BASIC",
        "certification_expires_at": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return get_success_data(api_client.create_volunteer(create_volunteer_payload(**defaults), MANAGER))


def create_shift(
    site_id: str, volunteer_id: str, menu_day_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_volunteer_shift(
            create_volunteer_shift_payload(site_id, volunteer_id, menu_day_id, **overrides),
            MANAGER,
        )
    )


def get_menu_day(menu_day_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_menu_day(menu_day_id, MANAGER))


def lock_forecast(menu_day_id: str) -> Dict[str, Any]:
    """Lock the forecast, threading the current version for OCC (PRD 2.8)."""
    version = get_menu_day(menu_day_id)["version"]
    return get_success_data(
        api_client.lock_forecast(menu_day_id, {"expected_menu_day_version": version}, MANAGER)
    )


def start_production(menu_day_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.start_production(menu_day_id, MANAGER))


def create_service(menu_day_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_meal_service(
            create_meal_service_payload(menu_day_id, **overrides), MANAGER
        )
    )


def open_service(service_id: str) -> Dict[str, Any]:
    """Open a service, threading the parent menu day's current version (PRD 2.8)."""
    service = get_success_data(api_client.get_meal_service(service_id, MANAGER))
    menu_day = get_menu_day(service["menu_day_id"])
    return get_success_data(
        api_client.open_service(
            service_id, {"expected_menu_day_version": menu_day["version"]}, MANAGER
        )
    )


def create_order(
    service_id: str, guest_id: str, menu_item_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_meal_order(
            create_meal_order_payload(service_id, guest_id, menu_item_id, **overrides),
            MANAGER,
        )
    )


def create_equipment_asset(site_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_equipment_asset(
            create_equipment_asset_payload(site_id, **overrides), MANAGER
        )
    )


def create_waste_log(menu_day_id: str, food_batch_id: str, as_officer: bool = False, **overrides: Any) -> Dict[str, Any]:
    headers = OFFICER if as_officer else MANAGER
    return get_success_data(
        api_client.create_waste_log(
            create_waste_log_payload(menu_day_id, food_batch_id, **overrides), headers
        )
    )


# ---------------------------------------------------------------------------
# Tier 1 — state progression
# ---------------------------------------------------------------------------


def create_confirmed_item(
    menu_day_id: str,
    batch_id: str,
    planned_servings: int = 10,
    **item_overrides: Any,
) -> Dict[str, Any]:
    """Create a PLANNED item, allocate full coverage from an ACCEPTED batch,
    and confirm it (PLANNED -> CONFIRMED with ledger sync, PRD 3.2)."""
    item = create_menu_item(menu_day_id, planned_servings=planned_servings, **item_overrides)
    allocate(item["id"], batch_id, planned_servings)
    return confirm_item(item["id"])


def create_menu_day_in_production(
    site_id: str,
    service_date: str,
    batch_id: Optional[str] = None,
    planned_servings: int = 10,
    **menu_day_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Menu day with one CONFIRMED item walked DRAFT -> FORECAST_LOCKED -> IN_PRODUCTION.

    Returns (menu_day, item, batch).  Creates its own ACCEPTED batch when none
    is supplied.
    """
    menu_day = create_menu_day(site_id, service_date, **menu_day_overrides)
    if batch_id is not None:
        batch = get_success_data(api_client.get_food_batch(batch_id, MANAGER))
    else:
        # Headroom over planned: allocating the LAST serving would drive the
        # batch ACCEPTED -> DEPLETED (PRD 3.3), and the confirm gate requires
        # status ACCEPTED (PRD 3.2).
        batch = create_accepted_batch(site_id, quantity_servings=planned_servings + 10)
    item = create_confirmed_item(menu_day["id"], batch["id"], planned_servings)
    lock_forecast(menu_day["id"])
    menu_day = start_production(menu_day["id"])
    return menu_day, item, batch


def create_serving_day(
    site_id: str,
    service_date: str,
    planned_servings: int = 10,
    service_model: str = "DINE_IN",
    capacity: int = 10,
    window_start: str = "2026-08-10T11:00:00Z",
    window_end: str = "2026-08-10T13:00:00Z",
    clock_during_service: str = "2026-08-10T10:30:00Z",
    **menu_day_overrides: Any,
) -> Dict[str, Any]:
    """Full chain to a SERVING menu day with one OPEN service.

    Returns a context dict:
        menu_day, item, batch, service, site_id
    The menu day is IN_PRODUCTION before the open and SERVING after (PRD 3.6).
    """
    menu_day, item, batch = create_menu_day_in_production(
        site_id, service_date, planned_servings=planned_servings, **menu_day_overrides
    )
    service = create_service(
        menu_day["id"],
        service_model=service_model,
        capacity=capacity,
        window_start=window_start,
        window_end=window_end,
    )
    if clock_during_service:
        set_clock(clock_during_service)
    service = open_service(service["id"])
    return {
        "menu_day": get_menu_day(menu_day["id"]),
        "item": item,
        "batch": batch,
        "service": service,
        "site_id": site_id,
    }


def create_reconciled_day(
    site_id: str,
    service_date: str,
    served_quantity: int,
    guest_id: str,
    volunteer_id: Optional[str] = None,
    batch_quantity: Optional[int] = None,
    planned_servings: Optional[int] = None,
    window_start: str = "2026-08-10T11:00:00Z",
    window_end: str = "2026-08-10T13:00:00Z",
    shift_start: str = "2026-08-10T10:00:00Z",
    shift_end: str = "2026-08-10T14:00:00Z",
    service_clock: str = "2026-08-10T10:30:00Z",
    service_capacity: int = 200,
    service_model: str = "DINE_IN",
    batch_use_by: str = "2026-08-20T00:00:00Z",
) -> Dict[str, Any]:
    """Drive one menu day from create to RECONCILED with exactly
    `served_quantity` servings served via a single order (PRD 3.2 input set).

    Steps: batch ACCEPTED -> menu day -> item -> allocate -> confirm ->
    lock-forecast -> start-production -> service create -> shift schedule ->
    clock to service window -> check-in -> service open -> order -> prep ->
    ready -> serve -> close -> reconcile.

    `batch_use_by` must be later than the logical clock at build time, or the
    batch is expired at birth and begin-inspection fails (PRD 3.3).

    Returns a context dict with keys: menu_day, item, batch, service, order,
    guest_id, volunteer_id, site_id.
    """
    planned = planned_servings if planned_servings is not None else served_quantity
    qty = batch_quantity if batch_quantity is not None else max(planned, served_quantity)
    batch = create_accepted_batch(site_id, quantity_servings=qty, use_by=batch_use_by)
    menu_day = create_menu_day(site_id, service_date)
    item = create_menu_item(menu_day["id"], planned_servings=planned)
    allocate(item["id"], batch["id"], planned)
    item = confirm_item(item["id"])
    lock_forecast(menu_day["id"])
    menu_day = start_production(menu_day["id"])
    service = create_service(
        menu_day["id"],
        service_model=service_model,
        window_start=window_start,
        window_end=window_end,
        capacity=service_capacity,
    )
    if volunteer_id is None:
        volunteer = create_volunteer()
        volunteer_id = volunteer["id"]
    # PREP role: start-prep requires a CHECKED_IN PREP or COOK shift covering
    # the current instant (PRD 3.7); serve carries no role requirement.
    shift = create_shift(
        site_id,
        volunteer_id,
        menu_day["id"],
        role_on_shift="PREP",
        starts_at=shift_start,
        ends_at=shift_end,
    )
    set_clock(service_clock)
    vol_headers = make_volunteer_headers(volunteer_id)
    get_success_data(api_client.check_in_shift(shift["id"], vol_headers))
    service = open_service(service["id"])
    order = create_order(service["id"], guest_id, item["id"], quantity=served_quantity)
    if served_quantity > 0:
        get_success_data(api_client.start_prep(order["id"], vol_headers))
        get_success_data(api_client.mark_ready(order["id"], vol_headers))
        get_success_data(api_client.serve_order(order["id"], vol_headers))
    get_success_data(api_client.close_service(service["id"], MANAGER))
    menu_day = get_success_data(api_client.reconcile_menu_day(menu_day["id"], MANAGER))
    return {
        "menu_day": menu_day,
        "item": item,
        "batch": batch,
        "service": service,
        "order": order,
        "guest_id": guest_id,
        "volunteer_id": volunteer_id,
        "site_id": site_id,
    }


# ---------------------------------------------------------------------------
# Tier 2 — entity hierarchy with staff
# ---------------------------------------------------------------------------


def create_site_with_staff(
    volunteer_overrides: Optional[Dict[str, Any]] = None,
    **site_overrides: Any,
) -> Dict[str, Any]:
    """Site + one BASIC-certified volunteer + one guest.  Returns ctx dict."""
    site = create_site(**site_overrides)
    volunteer = create_volunteer(**(volunteer_overrides or {}))
    guest = create_guest()
    return {"site": site, "volunteer": volunteer, "guest": guest}


def setup_open_service_with_volunteer(
    service_date: str = "2026-08-10",
    role_on_shift: str = "PREP",
    shift_start: str = "2026-08-10T10:00:00Z",
    shift_end: str = "2026-08-10T14:00:00Z",
    clock_now: str = "2026-08-10T10:30:00Z",
    capacity: int = 10,
    planned_servings: int = 10,
    service_model: str = "DINE_IN",
    guest_overrides: Optional[Dict[str, Any]] = None,
    item_overrides: Optional[Dict[str, Any]] = None,
    batch_overrides: Optional[Dict[str, Any]] = None,
    volunteer_overrides: Optional[Dict[str, Any]] = None,
    service_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Full serving chain ending in an OPEN DINE_IN service with a CHECKED_IN
    volunteer shift covering `clock_now`.

    Returns ctx: site, menu_day, item, batch, service, volunteer, guest, shift.
    """
    site = create_site()
    # Headroom over planned: exact-fit allocation would auto-DEPLETE the batch
    # (PRD 3.3) and the confirm gate requires status ACCEPTED (PRD 3.2).
    batch = create_accepted_batch(
        site["id"],
        **({"quantity_servings": planned_servings + 10} | (batch_overrides or {})),
    )
    menu_day = create_menu_day(site["id"], service_date)
    item = create_menu_item(
        menu_day["id"], planned_servings=planned_servings, **(item_overrides or {})
    )
    allocate(item["id"], batch["id"], planned_servings)
    item = confirm_item(item["id"])
    guest = create_guest(**(guest_overrides or {}))
    volunteer = create_volunteer(**(volunteer_overrides or {}))
    lock_forecast(menu_day["id"])
    menu_day = start_production(menu_day["id"])
    svc_kwargs = {
        "service_model": service_model,
        "capacity": capacity,
        "window_start": "2026-08-10T11:00:00Z",
        "window_end": "2026-08-10T13:00:00Z",
    }
    svc_kwargs.update(service_overrides or {})
    service = create_service(menu_day["id"], **svc_kwargs)
    shift = create_shift(
        site["id"],
        volunteer["id"],
        menu_day["id"],
        role_on_shift=role_on_shift,
        starts_at=shift_start,
        ends_at=shift_end,
    )
    set_clock(clock_now)
    vol_headers = make_volunteer_headers(volunteer["id"])
    get_success_data(api_client.check_in_shift(shift["id"], vol_headers))
    service = open_service(service["id"])
    return {
        "site": site,
        "menu_day": get_menu_day(menu_day["id"]),
        "item": item,
        "batch": batch,
        "service": service,
        "volunteer": volunteer,
        "volunteer_headers": vol_headers,
        "guest": guest,
        "shift": shift,
    }


# ---------------------------------------------------------------------------
# Tier 3 — order pipeline shortcuts
# ---------------------------------------------------------------------------


def prep_order_to_ready(ctx: Dict[str, Any], order_id: str) -> Dict[str, Any]:
    """Drive an order prep QUEUED -> IN_PREP -> READY as the ctx volunteer."""
    vol_headers = ctx["volunteer_headers"]
    get_success_data(api_client.start_prep(order_id, vol_headers))
    return get_success_data(api_client.mark_ready(order_id, vol_headers))


def serve_order(ctx: Dict[str, Any], order_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.serve_order(order_id, ctx["volunteer_headers"]))


def close_and_reconcile(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Close the ctx service and reconcile the menu day (PRD 3.8)."""
    get_success_data(api_client.close_service(ctx["service"]["id"], MANAGER))
    return get_success_data(api_client.reconcile_menu_day(ctx["menu_day"]["id"], MANAGER))
