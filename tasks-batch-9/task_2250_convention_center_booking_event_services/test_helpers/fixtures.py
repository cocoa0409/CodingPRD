"""Composite state builders.

Nothing here asserts: every helper walks the documented endpoints with the
lenient success reader so that a test's own assertions are the only checks
that can fail. ``setup_event_lifecycle`` drives a booking as far along the
event lifecycle as a test needs; the atomic helpers below it cover the cases
where a test wants to stop between two rungs and inspect or perturb the state.
"""

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import MEETING_ROOM_301
from .factories import (
    booking_payload,
    catering_arrangement_payload,
    child_space_payload,
    client_payload,
    iso_utc,
    labor_call_payload,
    maintenance_blackout_payload,
    policy_window_payload,
    service_order_payload,
    settlement_line_item_payload,
    shift_days,
    space_payload,
    union_jurisdiction_payload,
    usage_record_payload,
    vendor_payload,
)
from .test_users import (
    ANALYST_ONE,
    ANALYST_TWO,
    TEST_USERS,
    make_analyst_headers,
    make_licensee_headers,
)

VENUE_ADMIN = TEST_USERS["venue_admin"]
SALES_MANAGER = TEST_USERS["sales_manager"]
EVENT_SERVICES = TEST_USERS["event_services_manager"]
SETTLEMENT_ANALYST = TEST_USERS["settlement_analyst"]
SETTLEMENT_ANALYST_TWO = TEST_USERS["settlement_analyst_two"]
FACILITIES_PLANNER = TEST_USERS["facilities_planner"]


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------


def read_client(api: ApiClient, client_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_client(client_id, headers=VENUE_ADMIN))


def read_space(api: ApiClient, space_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_space(space_id, headers=VENUE_ADMIN))


def read_policy_window(api: ApiClient, window_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_policy_window(window_id, headers=VENUE_ADMIN))


def read_booking(api: ApiClient, booking_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_booking(booking_id, headers=VENUE_ADMIN))


def read_hold(api: ApiClient, hold_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_hold(hold_id, headers=VENUE_ADMIN))


def read_license(api: ApiClient, license_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_license(license_id, headers=VENUE_ADMIN))


def read_vendor(api: ApiClient, vendor_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_vendor(vendor_id, headers=VENUE_ADMIN))


def read_union_jurisdiction(api: ApiClient, jurisdiction_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_union_jurisdiction(jurisdiction_id, headers=VENUE_ADMIN))


def read_service_order(api: ApiClient, order_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_service_order(order_id, headers=VENUE_ADMIN))


def read_labor_call(api: ApiClient, call_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_labor_call(call_id, headers=VENUE_ADMIN))


def read_catering_arrangement(api: ApiClient, arrangement_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_catering_arrangement(arrangement_id, headers=VENUE_ADMIN))


def read_settlement(api: ApiClient, settlement_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_settlement(settlement_id, headers=VENUE_ADMIN))


def read_maintenance_blackout(api: ApiClient, blackout_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_maintenance_blackout(blackout_id, headers=VENUE_ADMIN))


def read_line_items(api: ApiClient, settlement_id: str) -> List[Dict[str, Any]]:
    body = get_success_data(
        api.list_line_items_for_settlement(settlement_id, headers=VENUE_ADMIN, limit=100)
    )
    return body if isinstance(body, list) else body.get("items", [])


def read_usage_records(api: ApiClient, booking_id: str) -> List[Dict[str, Any]]:
    body = get_success_data(api.list_booking_usage_records(booking_id, headers=VENUE_ADMIN, limit=100))
    return body if isinstance(body, list) else body.get("items", [])


def read_holds_for_booking(api: ApiClient, booking_id: str) -> List[Dict[str, Any]]:
    body = get_success_data(api.list_holds(headers=VENUE_ADMIN, booking_id=booking_id, limit=100))
    return body if isinstance(body, list) else body.get("items", [])


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------


def set_clock(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    return get_success_data(api.set_clock(to_iso8601, headers=VENUE_ADMIN))


# --------------------------------------------------------------------------
# Reference data
# --------------------------------------------------------------------------


def publish_window(
    api: ApiClient, event_class: str = "CONSUMER_SHOW", **overrides: Any
) -> Dict[str, Any]:
    payload = policy_window_payload(event_class, **overrides)
    return get_success_data(api.create_policy_window(payload=payload, headers=VENUE_ADMIN))


def publish_windows(api: ApiClient, *event_classes: str) -> Dict[str, Dict[str, Any]]:
    return {event_class: publish_window(api, event_class) for event_class in event_classes}


def register_space(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    payload = space_payload(**overrides)
    return get_success_data(api.create_space(payload=payload, headers=VENUE_ADMIN))


def register_child_space(api: ApiClient, parent_space_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = child_space_payload(parent_space_id, **overrides)
    return get_success_data(api.create_space(payload=payload, headers=VENUE_ADMIN))


def register_client(api: ApiClient, deposit_cents: Optional[int] = None, **overrides: Any) -> Dict[str, Any]:
    payload = client_payload(**overrides)
    client = get_success_data(api.create_client(payload=payload, headers=VENUE_ADMIN))
    if deposit_cents:
        client = pay_deposit(api, client["id"], deposit_cents)
    return client


def pay_deposit(api: ApiClient, client_id: str, amount_cents: int) -> Dict[str, Any]:
    get_success_data(api.record_deposit(client_id, amount_cents, headers=VENUE_ADMIN))
    return read_client(api, client_id)


def register_vendor(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    payload = vendor_payload(**overrides)
    return get_success_data(api.create_vendor(payload=payload, headers=VENUE_ADMIN))


def register_union_local(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    payload = union_jurisdiction_payload(**overrides)
    return get_success_data(api.create_union_jurisdiction(payload=payload, headers=VENUE_ADMIN))


# --------------------------------------------------------------------------
# Bookings and holds
# --------------------------------------------------------------------------


def create_booking(api: ApiClient, client_id: str, space_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = booking_payload(client_id, space_id, **overrides)
    return get_success_data(api.create_booking(payload=payload, headers=SALES_MANAGER))


def place_hold(api: ApiClient, booking_id: str) -> Dict[str, Any]:
    """Place a hold using the booking's current version."""
    booking = read_booking(api, booking_id)
    return get_success_data(
        api.create_hold(booking_id, expected_booking_version=booking["version"], headers=SALES_MANAGER)
    )


def place_hold_with_version(api: ApiClient, booking_id: str, expected_booking_version: int):
    """Place a hold with a caller-chosen version, for concurrency checks."""
    return api.create_hold(
        booking_id, expected_booking_version=expected_booking_version, headers=SALES_MANAGER
    )


def confirm_first_option(api: ApiClient, hold_id: str) -> Dict[str, Any]:
    return get_success_data(api.confirm_first_option(hold_id, headers=SALES_MANAGER))


# --------------------------------------------------------------------------
# Licenses
# --------------------------------------------------------------------------


def draft_license(api: ApiClient, booking_id: str) -> Dict[str, Any]:
    return get_success_data(api.create_license(booking_id, headers=SALES_MANAGER))


def issue_license(api: ApiClient, license_id: str) -> Dict[str, Any]:
    return get_success_data(api.issue_license(license_id, headers=SALES_MANAGER))


def countersign_license(api: ApiClient, license_id: str, client_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.countersign_license(license_id, headers=make_licensee_headers(client_id))
    )


def execute_license(api: ApiClient, booking_id: str, client_id: str) -> Dict[str, Any]:
    """Draft, issue and countersign in one step; returns the executed license."""
    license_row = draft_license(api, booking_id)
    issue_license(api, license_row["id"])
    return countersign_license(api, license_row["id"], client_id)


def amend_license(api: ApiClient, license_id: str, amendment_note: str) -> Dict[str, Any]:
    """Raise an amendment using the license's current version."""
    license_row = read_license(api, license_id)
    return get_success_data(
        api.create_amendment(
            license_id,
            expected_license_version=license_row["version"],
            amendment_note=amendment_note,
            headers=SALES_MANAGER,
        )
    )


def accept_amendment(api: ApiClient, license_id: str, client_id: str) -> Dict[str, Any]:
    return get_success_data(api.accept_amendment(license_id, headers=make_licensee_headers(client_id)))


def amendment_round_trip(api: ApiClient, license_id: str, client_id: str, amendment_note: str) -> Dict[str, Any]:
    """Raise an amendment and have the licensee accept it."""
    amend_license(api, license_id, amendment_note)
    return accept_amendment(api, license_id, client_id)


# --------------------------------------------------------------------------
# Event-day progression
# --------------------------------------------------------------------------


def confirm_definite(api: ApiClient, booking_id: str) -> Dict[str, Any]:
    return get_success_data(api.confirm_definite_booking(booking_id, headers=SALES_MANAGER))


def open_show(api: ApiClient, booking_id: str, at_utc: Optional[str] = None) -> Dict[str, Any]:
    booking = read_booking(api, booking_id)
    set_clock(api, at_utc or iso_utc(booking["move_in_start_date"], 8))
    return get_success_data(api.open_show(booking_id, headers=EVENT_SERVICES))


def close_booking(api: ApiClient, booking_id: str, at_utc: Optional[str] = None) -> Dict[str, Any]:
    booking = read_booking(api, booking_id)
    set_clock(api, at_utc or iso_utc(shift_days(booking["move_out_end_date"], 1), 9))
    return get_success_data(api.close_booking(booking_id, headers=EVENT_SERVICES))


def attest_usage_days(
    api: ApiClient, booking_id: str, days: Sequence[Tuple[str, str]]
) -> List[Dict[str, Any]]:
    """Record one usage row per ``(usage_date, usage_kind)`` pair."""
    records = []
    for usage_date, usage_kind in days:
        records.append(
            get_success_data(
                api.create_usage_record(
                    booking_id,
                    payload=usage_record_payload(usage_date, usage_kind),
                    headers=EVENT_SERVICES,
                )
            )
        )
    return records


# --------------------------------------------------------------------------
# Event services
# --------------------------------------------------------------------------


def order_service(
    api: ApiClient,
    booking_id: str,
    vendor_id: str,
    service_category: str,
    ordered_quantity: float,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_service_order(
            booking_id,
            payload=service_order_payload(vendor_id, service_category, ordered_quantity),
            headers=EVENT_SERVICES,
        )
    )


def approve_service_order(api: ApiClient, order_id: str) -> Dict[str, Any]:
    return get_success_data(api.approve_service_order(order_id, headers=EVENT_SERVICES))


def reconcile_service_order(api: ApiClient, order_id: str, actual_quantity: float) -> Dict[str, Any]:
    return get_success_data(
        api.reconcile_service_order(order_id, actual_quantity=actual_quantity, headers=EVENT_SERVICES)
    )


def schedule_labor_call(
    api: ApiClient,
    booking_id: str,
    jurisdiction_id: str,
    work_category: str,
    work_date: str,
    scheduled_start_hour: float,
    scheduled_end_hour: float,
    crew_size: int,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_labor_call(
            booking_id,
            payload=labor_call_payload(
                jurisdiction_id,
                work_category,
                work_date,
                scheduled_start_hour,
                scheduled_end_hour,
                crew_size,
            ),
            headers=EVENT_SERVICES,
        )
    )


def dispatch_labor_call(api: ApiClient, call_id: str) -> Dict[str, Any]:
    return get_success_data(api.dispatch_labor_call(call_id, headers=EVENT_SERVICES))


def actualize_labor_call(
    api: ApiClient, call_id: str, actual_start_hour: float, actual_end_hour: float
) -> Dict[str, Any]:
    return get_success_data(
        api.actualize_labor_call(
            call_id,
            actual_start_hour=actual_start_hour,
            actual_end_hour=actual_end_hour,
            headers=EVENT_SERVICES,
        )
    )


def propose_catering(
    api: ApiClient,
    booking_id: str,
    vendor_id: str,
    arrangement_type: str,
    estimated_fnb_cents: int,
    exception_reason: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_catering_arrangement(
            booking_id,
            payload=catering_arrangement_payload(
                vendor_id, arrangement_type, estimated_fnb_cents, exception_reason
            ),
            headers=EVENT_SERVICES,
        )
    )


def approve_catering(api: ApiClient, arrangement_id: str) -> Dict[str, Any]:
    return get_success_data(api.approve_catering_arrangement(arrangement_id, headers=EVENT_SERVICES))


# --------------------------------------------------------------------------
# Maintenance
# --------------------------------------------------------------------------


def propose_blackout(
    api: ApiClient,
    space_id: str,
    window_start_date: str,
    window_end_date: str,
    project_kind: str = "ROUTINE_MAINTENANCE",
    buffer_days: Optional[int] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_maintenance_blackout(
            payload=maintenance_blackout_payload(
                space_id, window_start_date, window_end_date, project_kind, buffer_days
            ),
            headers=FACILITIES_PLANNER,
        )
    )


def approve_blackout(api: ApiClient, blackout_id: str) -> Dict[str, Any]:
    return get_success_data(api.approve_maintenance_blackout(blackout_id, headers=FACILITIES_PLANNER))


# --------------------------------------------------------------------------
# Settlements
# --------------------------------------------------------------------------


def open_settlement(
    api: ApiClient, booking_id: str, basis: str = "CONTRACTED", analyst_id: str = ANALYST_ONE
) -> Dict[str, Any]:
    return get_success_data(
        api.create_settlement(booking_id, basis=basis, headers=make_analyst_headers(analyst_id))
    )


def append_line_item(
    api: ApiClient,
    settlement_id: str,
    line_kind: str,
    amount_cents: int,
    source_ref_id: Optional[str] = None,
    memo: Optional[str] = None,
    analyst_id: str = ANALYST_ONE,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_settlement_line_item(
            payload=settlement_line_item_payload(
                settlement_id, line_kind, amount_cents, source_ref_id, memo
            ),
            headers=make_analyst_headers(analyst_id),
        )
    )


def issue_settlement(api: ApiClient, settlement_id: str, analyst_id: str = ANALYST_ONE) -> Dict[str, Any]:
    return get_success_data(
        api.issue_settlement(settlement_id, headers=make_analyst_headers(analyst_id))
    )


def dispute_settlement(
    api: ApiClient, settlement_id: str, client_id: str, dispute_reason: str
) -> Dict[str, Any]:
    return get_success_data(
        api.dispute_settlement(
            settlement_id, dispute_reason=dispute_reason, headers=make_licensee_headers(client_id)
        )
    )


def finalize_settlement_after_dispute_window(
    api: ApiClient,
    settlement_id: str,
    *,
    at_utc: Optional[str] = None,
    analyst_id: str = ANALYST_TWO,
) -> Dict[str, Any]:
    """Advance the clock past ``dispute_deadline_utc`` and finalize."""
    settlement = read_settlement(api, settlement_id)
    deadline = settlement.get("dispute_deadline_utc")
    if at_utc is None and deadline:
        at_utc = iso_utc(shift_days(deadline[:10], 1), 10)
    if at_utc:
        set_clock(api, at_utc)
    return get_success_data(
        api.finalize_settlement(settlement_id, headers=make_analyst_headers(analyst_id))
    )


# --------------------------------------------------------------------------
# The lifecycle ladder
# --------------------------------------------------------------------------

LIFECYCLE_STAGES: List[str] = [
    "booking",
    "hold",
    "confirmed_hold",
    "license_draft",
    "license_issued",
    "license_executed",
    "definite",
    "in_house",
    "closed",
    "settlement_draft",
    "settlement_issued",
]


def _stage_index(stage: str) -> int:
    try:
        return LIFECYCLE_STAGES.index(stage)
    except ValueError:  # pragma: no cover - guards against typos in tests
        raise AssertionError(f"unknown lifecycle stage {stage!r}; choose from {LIFECYCLE_STAGES}")


def setup_event_lifecycle(
    api: ApiClient,
    stage: str = "booking",
    *,
    event_class: str = "CONSUMER_SHOW",
    window: Optional[Dict[str, Any]] = None,
    extra_windows: Iterable[str] = (),
    space: Optional[Dict[str, Any]] = None,
    client: Optional[Dict[str, Any]] = None,
    deposit_cents: Optional[int] = None,
    booking: Optional[Dict[str, Any]] = None,
    usage_records: Sequence[Tuple[str, str]] = (),
    settlement_basis: str = "CONTRACTED",
    rental_line_cents: Optional[int] = None,
    extra_lines: Sequence[Tuple[str, int]] = (),
    analyst_id: str = ANALYST_ONE,
    open_show_at: Optional[str] = None,
    close_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Drive one booking up to ``stage`` and return every row touched.

    ``window``/``space``/``client``/``booking`` are override dictionaries for
    the corresponding create payloads. ``deposit_cents`` defaults to exactly
    the booking's ``deposit_required_cents`` whenever the requested stage needs
    an issued license.

    Returned keys: ``policy_window``, ``windows``, ``space``, ``client``,
    ``booking``, ``hold``, ``license``, ``settlement``, ``usage_records``,
    ``line_items``, ``licensee_headers``.
    """
    target = _stage_index(stage)

    window_row = publish_window(api, event_class, **(window or {}))
    windows = {window_row["event_class"]: window_row}
    for other in extra_windows:
        extra = publish_window(api, other)
        windows[extra["event_class"]] = extra

    space_overrides = dict(MEETING_ROOM_301)
    space_overrides.update(space or {})
    space_row = register_space(api, **space_overrides)

    client_row = register_client(api, **(client or {}))
    if deposit_cents:
        client_row = pay_deposit(api, client_row["id"], deposit_cents)

    booking_overrides = dict(booking or {})
    booking_overrides.setdefault("event_class", event_class)
    booking_row = create_booking(api, client_row["id"], space_row["id"], **booking_overrides)

    result: Dict[str, Any] = {
        "policy_window": window_row,
        "windows": windows,
        "space": space_row,
        "client": client_row,
        "booking": booking_row,
        "hold": None,
        "license": None,
        "settlement": None,
        "usage_records": [],
        "line_items": [],
        "licensee_headers": make_licensee_headers(client_row["id"]),
    }
    if target == _stage_index("booking"):
        return result

    hold_row = place_hold(api, booking_row["id"])
    result["hold"] = hold_row
    result["booking"] = read_booking(api, booking_row["id"])
    if target == _stage_index("hold"):
        return result

    result["hold"] = confirm_first_option(api, hold_row["id"])
    result["booking"] = read_booking(api, booking_row["id"])
    if target == _stage_index("confirmed_hold"):
        return result

    license_row = draft_license(api, booking_row["id"])
    result["license"] = license_row
    if target == _stage_index("license_draft"):
        return result

    if not deposit_cents:
        result["client"] = pay_deposit(
            api, client_row["id"], read_booking(api, booking_row["id"])["deposit_required_cents"]
        )
    result["license"] = issue_license(api, license_row["id"])
    result["client"] = read_client(api, client_row["id"])
    if target == _stage_index("license_issued"):
        return result

    result["license"] = countersign_license(api, license_row["id"], client_row["id"])
    if target == _stage_index("license_executed"):
        return result

    result["booking"] = confirm_definite(api, booking_row["id"])
    if target == _stage_index("definite"):
        return result

    result["booking"] = open_show(api, booking_row["id"], at_utc=open_show_at)
    if usage_records:
        result["usage_records"] = attest_usage_days(api, booking_row["id"], usage_records)
    if target == _stage_index("in_house"):
        return result

    result["booking"] = close_booking(api, booking_row["id"], at_utc=close_at)
    if target == _stage_index("closed"):
        return result

    settlement_row = open_settlement(
        api, booking_row["id"], basis=settlement_basis, analyst_id=analyst_id
    )
    result["settlement"] = settlement_row
    if target == _stage_index("settlement_draft"):
        return result

    rental_amount = rental_line_cents
    if rental_amount is None:
        rental_amount = result["booking"]["contracted_rental_cents"]
    result["line_items"].append(
        append_line_item(
            api, settlement_row["id"], "RENTAL", rental_amount, analyst_id=analyst_id, memo="rental"
        )
    )
    for line_kind, amount_cents in extra_lines:
        result["line_items"].append(
            append_line_item(
                api, settlement_row["id"], line_kind, amount_cents, analyst_id=analyst_id
            )
        )
    result["settlement"] = issue_settlement(api, settlement_row["id"], analyst_id=analyst_id)
    return result
