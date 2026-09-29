"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only, and uses the lenient success validator so a broken preamble
surfaces as a setup failure rather than as a confusing assertion error.
"""
from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_resident_representative_headers,
)

PROGRAM_ADMIN = TEST_USERS["program_admin_headers"]
CLINICAL_STAFF = TEST_USERS["clinical_staff_headers"]
CLINICAL_STAFF_ALT = TEST_USERS["clinical_staff_alt_headers"]
DIETITIAN = TEST_USERS["dietitian_headers"]
DIETITIAN_ALT = TEST_USERS["dietitian_alt_headers"]
DINING_MANAGER = TEST_USERS["dining_manager_headers"]
KITCHEN_LEAD = TEST_USERS["kitchen_lead_headers"]
BILLING_SPECIALIST = TEST_USERS["billing_specialist_headers"]

ALL_CARE_LEVELS = [
    "INDEPENDENT_LIVING",
    "ASSISTED_LIVING",
    "MEMORY_CARE",
    "SKILLED_NURSING",
]


# ==========================================================================
# Logical clock
# ==========================================================================
def set_clock(current_utc: str) -> dict:
    """Move the logical clock. Every stamped timestamp and window reads it."""
    return get_success_data(api_client.set_clock(current_utc, PROGRAM_ADMIN))


# ==========================================================================
# Program setup primitives
# ==========================================================================
def create_community(
    name: str = "Brookdale Riverbend",
    care_levels_offered: Optional[List[str]] = None,
    **overrides,
) -> dict:
    payload = {
        "name": name,
        "care_levels_offered": list(
            care_levels_offered
            if care_levels_offered is not None
            else ["ASSISTED_LIVING", "MEMORY_CARE"]
        ),
    }
    payload.update(overrides)
    return get_success_data(api_client.create_community(payload, PROGRAM_ADMIN))


def read_community(community_id: str) -> dict:
    return get_success_data(api_client.get_community(community_id, PROGRAM_ADMIN))


def create_venue(
    community_id: str,
    name: str = "Riverbend Main Dining",
    venue_kind: str = "MAIN_DINING",
    seat_capacity: int = 20,
    care_levels_served: Optional[List[str]] = None,
    **overrides,
) -> dict:
    payload = {
        "community_id": community_id,
        "name": name,
        "venue_kind": venue_kind,
        "seat_capacity": seat_capacity,
        "care_levels_served": list(
            care_levels_served
            if care_levels_served is not None
            else ["ASSISTED_LIVING", "MEMORY_CARE"]
        ),
    }
    payload.update(overrides)
    return get_success_data(api_client.create_venue(payload, PROGRAM_ADMIN))


def read_venue(venue_id: str) -> dict:
    return get_success_data(api_client.get_venue(venue_id, DINING_MANAGER))


def venue_version(venue_id: str) -> int:
    return read_venue(venue_id)["version"]


def create_resident(
    community_id: str,
    full_name: str = "Ada Lin",
    care_level: str = "ASSISTED_LIVING",
    baseline_weight_kg: float = 78.0,
    **overrides,
) -> dict:
    payload = {
        "community_id": community_id,
        "full_name": full_name,
        "care_level": care_level,
        "baseline_weight_kg": baseline_weight_kg,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_resident(payload, PROGRAM_ADMIN))


def read_resident(resident_id: str) -> dict:
    return get_success_data(api_client.get_resident(resident_id, CLINICAL_STAFF))


def resident_version(resident_id: str) -> int:
    return read_resident(resident_id)["version"]


def set_dining_status(resident_id: str, dining_status: str) -> dict:
    return get_success_data(
        api_client.set_dining_status(resident_id, dining_status, PROGRAM_ADMIN)
    )


# ==========================================================================
# Diet orders
# ==========================================================================
def create_diet_order(
    resident_id: str,
    texture_level: str = "REGULAR",
    liquid_consistency: str = "THIN",
    expected_resident_version: Optional[int] = None,
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    """Record a diet order, re-reading the resident's version when not pinned."""
    if expected_resident_version is None:
        expected_resident_version = resident_version(resident_id)
    payload = {
        "resident_id": resident_id,
        "texture_level": texture_level,
        "liquid_consistency": liquid_consistency,
        "expected_resident_version": expected_resident_version,
    }
    payload.update(overrides)
    return get_success_data(
        api_client.create_diet_order(payload, headers or CLINICAL_STAFF)
    )


def approve_diet_order(order_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.dietitian_review_diet_order(
            order_id, {"decision": "APPROVE"}, headers or DIETITIAN
        )
    )


def request_changes_on_diet_order(
    order_id: str, reviewer_note: Optional[str] = None, headers: Optional[dict] = None
) -> dict:
    payload = {"decision": "REQUEST_CHANGES"}
    if reviewer_note is not None:
        payload["reviewer_note"] = reviewer_note
    return get_success_data(
        api_client.dietitian_review_diet_order(order_id, payload, headers or DIETITIAN)
    )


def create_approved_diet_order(resident_id: str, **overrides) -> dict:
    """Create an order and approve it, leaving it ACTIVE / APPROVED."""
    order = create_diet_order(resident_id, **overrides)
    return approve_diet_order(order["id"])


def create_substitution_rule(
    resident_id: str,
    trigger_type: str,
    match_value: str,
    replacement_item_code: str,
    priority_rank: int = 1,
    **overrides,
) -> dict:
    payload = {
        "trigger_type": trigger_type,
        "match_value": match_value,
        "replacement_item_code": replacement_item_code,
        "priority_rank": priority_rank,
    }
    payload.update(overrides)
    return get_success_data(
        api_client.create_substitution_rule(resident_id, payload, CLINICAL_STAFF)
    )


# ==========================================================================
# Composite: a community with a venue, a resident and a verified diet order
# ==========================================================================
def setup_dining_program(
    clock: Optional[str] = None,
    community_name: str = "Brookdale Riverbend",
    care_levels: Optional[List[str]] = None,
    venue_name: str = "Riverbend Main Dining",
    venue_kind: str = "MAIN_DINING",
    seat_capacity: int = 20,
    seating_turn_minutes: Optional[int] = None,
    turnover_buffer_minutes: Optional[int] = None,
    resident_name: str = "Ada Lin",
    care_level: str = "ASSISTED_LIVING",
    baseline_weight_kg: float = 78.0,
    texture_level: str = "REGULAR",
    liquid_consistency: str = "THIN",
    therapeutic_codes: Optional[List[str]] = None,
    community_overrides: Optional[dict] = None,
    with_approved_order: bool = True,
) -> Dict[str, dict]:
    """Community + venue + ACTIVE resident + (optionally) a verified diet order.

    Returns a dict with keys `community`, `venue`, `resident` and `diet_order`
    (the latter is None when `with_approved_order` is False).
    """
    if clock is not None:
        set_clock(clock)
    community = create_community(
        community_name,
        care_levels if care_levels is not None else ["ASSISTED_LIVING", "MEMORY_CARE"],
        **(community_overrides or {}),
    )
    venue_extra = {}
    if seating_turn_minutes is not None:
        venue_extra["seating_turn_minutes"] = seating_turn_minutes
    if turnover_buffer_minutes is not None:
        venue_extra["turnover_buffer_minutes"] = turnover_buffer_minutes
    venue = create_venue(
        community["id"],
        name=venue_name,
        venue_kind=venue_kind,
        seat_capacity=seat_capacity,
        care_levels_served=list(community["care_levels_offered"]),
        **venue_extra,
    )
    resident = create_resident(
        community["id"],
        full_name=resident_name,
        care_level=care_level,
        baseline_weight_kg=baseline_weight_kg,
    )
    diet_order = None
    if with_approved_order:
        order_extra = {}
        if therapeutic_codes is not None:
            order_extra["therapeutic_codes"] = list(therapeutic_codes)
        diet_order = create_approved_diet_order(
            resident["id"],
            texture_level=texture_level,
            liquid_consistency=liquid_consistency,
            **order_extra,
        )
    return {
        "community": community,
        "venue": venue,
        "resident": resident,
        "diet_order": diet_order,
    }


def add_verified_resident(
    community: dict,
    full_name: str,
    care_level: str = "ASSISTED_LIVING",
    baseline_weight_kg: float = 78.0,
    texture_level: str = "REGULAR",
    liquid_consistency: str = "THIN",
) -> dict:
    """Admit one more ACTIVE resident and give them an ACTIVE/APPROVED order."""
    resident = create_resident(
        community["id"],
        full_name=full_name,
        care_level=care_level,
        baseline_weight_kg=baseline_weight_kg,
    )
    create_approved_diet_order(
        resident["id"],
        texture_level=texture_level,
        liquid_consistency=liquid_consistency,
    )
    return resident


# ==========================================================================
# Menu cycles, items, extensions, ballots
# ==========================================================================
def create_menu_cycle(
    community_id: str,
    cycle_number: int = 1,
    week_count: int = 1,
    effective_start_date: str = "2026-08-01",
    effective_end_date: str = "2026-08-31",
    **overrides,
) -> dict:
    payload = {
        "community_id": community_id,
        "cycle_number": cycle_number,
        "week_count": week_count,
        "effective_start_date": effective_start_date,
        "effective_end_date": effective_end_date,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_menu_cycle(payload, DINING_MANAGER))


def add_menu_item(
    cycle_id: str,
    item_code: str = "CHICKEN-PLATE",
    name: str = "Roast Chicken Plate",
    day_index: int = 1,
    meal_period: str = "LUNCH",
    base_texture: str = "REGULAR",
    **overrides,
) -> dict:
    payload = {
        "item_code": item_code,
        "name": name,
        "day_index": day_index,
        "meal_period": meal_period,
        "base_texture": base_texture,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_menu_item(cycle_id, payload, DINING_MANAGER))


def submit_menu_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.submit_menu_cycle(cycle_id, DINING_MANAGER))


def publish_menu_cycle(cycle_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.publish_menu_cycle(cycle_id, headers or DIETITIAN)
    )


def author_and_approve_extension(menu_item_id: str, diet_code: str, **overrides) -> dict:
    """DRAFT -> SUBMITTED -> APPROVED, honouring segregation of duties."""
    payload = {"diet_code": diet_code}
    payload.update(overrides)
    extension = get_success_data(
        api_client.create_therapeutic_extension(menu_item_id, payload, DIETITIAN)
    )
    get_success_data(
        api_client.submit_therapeutic_extension(extension["id"], DIETITIAN)
    )
    return get_success_data(
        api_client.review_therapeutic_extension(
            extension["id"], {"decision": "APPROVE"}, DIETITIAN_ALT
        )
    )


def setup_published_menu_cycle(
    community_id: str,
    cycle_number: int = 1,
    week_count: int = 1,
    effective_start_date: str = "2026-08-01",
    effective_end_date: str = "2026-08-31",
    items: Optional[List[dict]] = None,
) -> Dict[str, object]:
    """Draft a cycle, stock it, submit it and publish it.

    `items` is a list of `add_menu_item` keyword dicts; it defaults to a single
    allergen-free REGULAR LUNCH dish on cycle day 1.  Any item declaring
    `required_therapeutic_codes` gets an approved extension for each declared
    code so the coverage gate passes.
    Returns `{"cycle": ..., "items": [...]}` with the cycle re-read after
    publication.
    """
    cycle = create_menu_cycle(
        community_id,
        cycle_number=cycle_number,
        week_count=week_count,
        effective_start_date=effective_start_date,
        effective_end_date=effective_end_date,
    )
    created_items = []
    for spec in items if items is not None else [{}]:
        item = add_menu_item(cycle["id"], **spec)
        for code in item.get("required_therapeutic_codes") or []:
            author_and_approve_extension(item["id"], code)
        created_items.append(item)
    submit_menu_cycle(cycle["id"])
    published = publish_menu_cycle(cycle["id"])
    return {"cycle": published, "items": created_items}


def cast_ballot(
    cycle_id: str, resident_id: str, menu_item_code: str, sentiment: str
) -> dict:
    return get_success_data(
        api_client.cast_committee_feedback(
            cycle_id,
            {
                "resident_id": resident_id,
                "menu_item_code": menu_item_code,
                "sentiment": sentiment,
            },
            make_resident_representative_headers(resident_id),
        )
    )


# ==========================================================================
# Reservations
# ==========================================================================
def create_reservation(
    resident_id: str,
    venue_id: str,
    service_date: str,
    meal_period: str,
    seat_start_utc: str,
    party_size: int = 1,
    expected_venue_version: Optional[int] = None,
    allow_waitlist: Optional[bool] = None,
    **overrides,
) -> dict:
    if expected_venue_version is None:
        expected_venue_version = venue_version(venue_id)
    payload = {
        "resident_id": resident_id,
        "venue_id": venue_id,
        "service_date": service_date,
        "meal_period": meal_period,
        "seat_start_utc": seat_start_utc,
        "party_size": party_size,
        "expected_venue_version": expected_venue_version,
    }
    if allow_waitlist is not None:
        payload["allow_waitlist"] = allow_waitlist
    payload.update(overrides)
    return get_success_data(api_client.create_reservation(payload, DINING_MANAGER))


def seat_reservation(reservation_id: str) -> dict:
    return get_success_data(api_client.seat_reservation(reservation_id, DINING_MANAGER))


def release_reservation(reservation_id: str, reason: Optional[str] = None) -> dict:
    payload = {} if reason is None else {"reason": reason}
    return get_success_data(
        api_client.release_reservation(reservation_id, payload, DINING_MANAGER)
    )


def read_reservation(reservation_id: str) -> dict:
    return get_success_data(api_client.get_reservation(reservation_id, DINING_MANAGER))


def read_seat_availability(venue_id: str, service_date: str, meal_period: str) -> dict:
    return get_success_data(
        api_client.get_seat_availability(
            venue_id, service_date, meal_period, DINING_MANAGER
        )
    )


# ==========================================================================
# Meal tickets
# ==========================================================================
def issue_ticket(
    venue_id: str,
    ticket_type: str,
    service_date: str,
    meal_period: str,
    resident_id: Optional[str] = None,
    reservation_id: Optional[str] = None,
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    payload = {
        "venue_id": venue_id,
        "ticket_type": ticket_type,
        "service_date": service_date,
        "meal_period": meal_period,
    }
    if resident_id is not None:
        payload["resident_id"] = resident_id
    if reservation_id is not None:
        payload["reservation_id"] = reservation_id
    payload.update(overrides)
    return get_success_data(
        api_client.create_meal_ticket(payload, headers or DINING_MANAGER)
    )


def serve_ticket(ticket_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.serve_meal_ticket(ticket_id, headers or DINING_MANAGER)
    )


def void_ticket(ticket_id: str, void_reason: Optional[str] = None) -> dict:
    payload = {} if void_reason is None else {"void_reason": void_reason}
    return get_success_data(
        api_client.void_meal_ticket(ticket_id, payload, BILLING_SPECIALIST)
    )


def issue_and_serve_ticket(
    venue_id: str,
    ticket_type: str,
    service_date: str,
    meal_period: str,
    resident_id: Optional[str] = None,
    **overrides,
) -> dict:
    ticket = issue_ticket(
        venue_id,
        ticket_type,
        service_date,
        meal_period,
        resident_id=resident_id,
        **overrides,
    )
    return serve_ticket(ticket["id"])


def read_ticket(ticket_id: str) -> dict:
    return get_success_data(api_client.get_meal_ticket(ticket_id, BILLING_SPECIALIST))


def list_tickets(**filters) -> List[dict]:
    return get_success_data(
        api_client.list_meal_tickets(BILLING_SPECIALIST, params=filters or None)
    )


def tickets_for_reservation(reservation_id: str) -> List[dict]:
    """The tickets the seating cascade minted for one reservation."""
    return list_tickets(reservation_id=reservation_id)


def list_resident_reservations(resident_id: str) -> List[dict]:
    return get_success_data(
        api_client.list_reservations(DINING_MANAGER, params={"resident_id": resident_id})
    )


def list_observations(resident_id: str, **filters) -> List[dict]:
    return get_success_data(
        api_client.list_intake_observations(
            resident_id, CLINICAL_STAFF, params=filters or None
        )
    )


def reviews_for(resident_id: str, **filters) -> List[dict]:
    params = {"resident_id": resident_id}
    params.update(filters)
    return get_success_data(
        api_client.list_plan_of_care_reviews(DIETITIAN, params=params)
    )


def read_review(review_id: str) -> dict:
    return get_success_data(
        api_client.get_plan_of_care_review(review_id, DIETITIAN)
    )


def read_tray_card(resident_id: str, service_date: str, meal_period: str) -> dict:
    return get_success_data(
        api_client.get_tray_card(resident_id, service_date, meal_period, CLINICAL_STAFF)
    )


def list_rules(resident_id: str, **filters) -> List[dict]:
    return get_success_data(
        api_client.list_substitution_rules(
            resident_id, CLINICAL_STAFF, params=filters or None
        )
    )


def read_diet_order(order_id: str) -> dict:
    return get_success_data(api_client.get_diet_order(order_id, DIETITIAN))


def read_menu_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.get_menu_cycle(cycle_id, DINING_MANAGER))


def read_menu_item(item_id: str) -> dict:
    return get_success_data(api_client.get_menu_item(item_id, DINING_MANAGER))


# ==========================================================================
# Temperature logs and the posture ladder
# ==========================================================================
def log_temperature(
    venue_id: str,
    probe_point: str,
    temperature_f: float,
    corrective_action_code: Optional[str] = None,
) -> dict:
    payload = {"probe_point": probe_point, "temperature_f": temperature_f}
    if corrective_action_code is not None:
        payload["corrective_action_code"] = corrective_action_code
    return get_success_data(
        api_client.create_temperature_log(venue_id, payload, KITCHEN_LEAD)
    )


def drive_venue_violation_count(venue_id: str, count: int) -> List[dict]:
    """Log `count` consecutive out-of-range hot-holding readings.

    One violation leaves the venue COMPLIANT, two put it on WATCH, three or
    more SUSPEND it.
    """
    logs = []
    for index in range(count):
        logs.append(
            log_temperature(venue_id, "HOT_HOLDING", 120.0 - float(index))
        )
    return logs


def drive_venue_to_watch(venue_id: str) -> List[dict]:
    return drive_venue_violation_count(venue_id, 2)


def drive_venue_to_suspended(venue_id: str) -> List[dict]:
    return drive_venue_violation_count(venue_id, 3)


def recover_venue(venue_id: str, corrective_action_code: str = "CA-RESET") -> dict:
    """An in-range reading carrying a corrective action resets the counter."""
    return log_temperature(
        venue_id, "HOT_HOLDING", 140.0, corrective_action_code=corrective_action_code
    )


# ==========================================================================
# Intake observations and plan-of-care reviews
# ==========================================================================
def record_observation(
    resident_id: str,
    observation_date: str,
    meal_period: str,
    intake_pct: float,
    weight_kg: Optional[float] = None,
    headers: Optional[dict] = None,
) -> dict:
    payload = {
        "observation_date": observation_date,
        "meal_period": meal_period,
        "intake_pct": intake_pct,
    }
    if weight_kg is not None:
        payload["weight_kg"] = weight_kg
    return get_success_data(
        api_client.create_intake_observation(
            resident_id, payload, headers or CLINICAL_STAFF
        )
    )


def open_reviews_for(resident_id: str) -> List[dict]:
    """The resident's plan-of-care reviews currently in OPEN status."""
    response = api_client.list_plan_of_care_reviews(
        DIETITIAN, params={"resident_id": resident_id, "status": "OPEN"}
    )
    return get_success_data(response)


def setup_resident_with_open_review(
    community_id: Optional[str] = None,
    baseline_weight_kg: float = 78.0,
    first_clock: str = "2026-08-02T08:00:00Z",
    second_clock: str = "2026-08-20T08:00:00Z",
    first_weight_kg: float = 80.0,
    first_intake_pct: float = 80,
    second_weight_kg: float = 76.0,
    second_intake_pct: float = 60,
) -> Dict[str, object]:
    """Two weight-carrying observations 18 days apart that breach the rolling
    thirty-day trend and therefore open a plan-of-care review.

    Returns `{"community", "resident", "first_observation",
    "second_observation", "review"}`.
    """
    set_clock(first_clock)
    community = (
        {"id": community_id}
        if community_id
        else create_community("Brookdale Elmhurst", ["ASSISTED_LIVING", "MEMORY_CARE"])
    )
    resident = create_resident(
        community["id"], full_name="Bea Ortiz", baseline_weight_kg=baseline_weight_kg
    )
    first = record_observation(
        resident["id"],
        first_clock[:10],
        "LUNCH",
        first_intake_pct,
        weight_kg=first_weight_kg,
    )
    set_clock(second_clock)
    second = record_observation(
        resident["id"],
        second_clock[:10],
        "LUNCH",
        second_intake_pct,
        weight_kg=second_weight_kg,
    )
    reviews = open_reviews_for(resident["id"])
    return {
        "community": community,
        "resident": resident,
        "first_observation": first,
        "second_observation": second,
        "review": reviews[0] if reviews else None,
    }


def complete_review(
    review_id: str, outcome: str, note: Optional[str] = None, headers: Optional[dict] = None
) -> dict:
    payload = {"outcome": outcome}
    if note is not None:
        payload["note"] = note
    return get_success_data(
        api_client.complete_plan_of_care_review(
            review_id, payload, headers or DIETITIAN
        )
    )


# ==========================================================================
# Reconciliations
# ==========================================================================
def create_reconciliation(
    community_id: str, period_start_date: str, period_end_date: str
) -> dict:
    return get_success_data(
        api_client.create_reconciliation(
            {
                "community_id": community_id,
                "period_start_date": period_start_date,
                "period_end_date": period_end_date,
            },
            BILLING_SPECIALIST,
        )
    )


def finalize_reconciliation(
    reconciliation_id: str, variance_note: Optional[str] = None
) -> dict:
    payload = {} if variance_note is None else {"variance_note": variance_note}
    return get_success_data(
        api_client.finalize_reconciliation(
            reconciliation_id, payload, BILLING_SPECIALIST
        )
    )


def read_reconciliation(reconciliation_id: str) -> dict:
    return get_success_data(
        api_client.get_reconciliation(reconciliation_id, BILLING_SPECIALIST)
    )
