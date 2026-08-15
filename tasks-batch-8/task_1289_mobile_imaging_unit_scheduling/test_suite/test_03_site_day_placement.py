"""Site-day placement rules: temporal, geometry, pad power, modality, contract,
unit day-exclusivity, and listing filters."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_site_day,
    create_contract,
    create_facility,
    create_site_day_payload,
    publish_plan,
    set_clock,
    setup_bookable_day,
    setup_plan_context,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["operations_director_headers"]


def test_site_day_service_date_in_past_rejected(api):
    """PRD §3.2: "The service date must not precede the logical clock date
    (`ERR_SERVICE_DATE_IN_PAST`) and must fall inside the plan's seven-day
    week (`ERR_SERVICE_DATE_OUTSIDE_PLAN_WEEK`)."

    Design: Corner/validations/site_day_service_date_in_past_rejected
    """
    bundle = setup_plan_context()
    # Clock advanced into the plan week so 2026-08-04 is in the past yet still
    # inside the plan week — only the past-date rule can fire.
    set_clock("2026-08-05T00:00:00Z")
    payload = create_site_day_payload(
        bundle["plan"]["id"], bundle["facility"]["id"], bundle["contract"]["id"],
        "2026-08-04",
    )
    resp = api.create_site_day(payload, OPS)
    validate_error(resp, ApiErrorId.ERR_SERVICE_DATE_IN_PAST)


def test_site_day_outside_plan_week_rejected(api):
    """PRD §3.2: "The service date must not precede the logical clock date
    (`ERR_SERVICE_DATE_IN_PAST`) and must fall inside the plan's seven-day
    week (`ERR_SERVICE_DATE_OUTSIDE_PLAN_WEEK`)."
    PRD §3.2: "Creating a `RoutePlan` takes the `unit_id` being routed and a
    `week_start_date`, which is always a Monday; the plan covers the seven-day
    window from `week_start_date` through six days later, inclusive."

    Design: Corner/validations/site_day_outside_plan_week_rejected
    """
    bundle = setup_plan_context()  # week [2026-08-03 .. 2026-08-09]
    payload = create_site_day_payload(
        bundle["plan"]["id"], bundle["facility"]["id"], bundle["contract"]["id"],
        "2026-08-10",
    )
    resp = api.create_site_day(payload, OPS)
    validate_error(resp, ApiErrorId.ERR_SERVICE_DATE_OUTSIDE_PLAN_WEEK)


def test_window_geometry_violates_setup_minutes_rejected(api):
    """PRD §3.2: "The window must be geometrically well-formed:
    `first_patient_time` no earlier than `arrival_time` plus the unit's
    `setup_minutes`, and `departure_time` no earlier than `last_patient_time`
    plus the unit's `teardown_minutes` — otherwise `ERR_WINDOW_TOO_SHORT`."

    Design: Corner/validations/window_geometry_violates_setup_minutes_rejected
    """
    bundle = setup_plan_context()  # unit setup_minutes 60
    payload = create_site_day_payload(
        bundle["plan"]["id"], bundle["facility"]["id"], bundle["contract"]["id"],
        "2026-08-04", first_patient_time="07:30",  # < arrival 07:00 + 60 = 08:00
    )
    resp = api.create_site_day(payload, OPS)
    validate_error(resp, ApiErrorId.ERR_WINDOW_TOO_SHORT)


def test_pad_power_below_requirement_rejected_at_create(api):
    """PRD §3.1: "at site-day creation the facility's `pad_amps_available` must
    be at least the unit's `power_required_amps` and the facility's
    `pad_voltage` must equal the unit's `voltage_required`, failing which the
    placement is rejected with `ERR_PAD_POWER_INSUFFICIENT`."

    Design: Corner/validations/pad_power_below_requirement_rejected_at_create
    """
    bundle = setup_plan_context(facility_overrides={"pad_amps_available": 90})
    payload = create_site_day_payload(
        bundle["plan"]["id"], bundle["facility"]["id"], bundle["contract"]["id"],
        "2026-08-04",
    )
    resp = api.create_site_day(payload, OPS)
    validate_error(resp, ApiErrorId.ERR_PAD_POWER_INSUFFICIENT)


def test_modality_not_supported_by_facility_rejected(api):
    """PRD §3.1: "A facility must also host the unit's modality — a `PET` coach
    cannot be routed to a pad whose `supported_modalities` omits `PET` — or the
    placement fails with `ERR_MODALITY_NOT_SUPPORTED`."

    Design: Corner/validations/modality_not_supported_by_facility_rejected
    """
    bundle = setup_plan_context(
        facility_overrides={"supported_modalities": ["MRI"], "pad_amps_available": 200}
    )  # unit is CT
    payload = create_site_day_payload(
        bundle["plan"]["id"], bundle["facility"]["id"], bundle["contract"]["id"],
        "2026-08-04",
    )
    resp = api.create_site_day(payload, OPS)
    validate_error(resp, ApiErrorId.ERR_MODALITY_NOT_SUPPORTED)


def test_contract_facility_mismatch_rejected(api):
    """PRD §3.2: "The contract must belong to the day's facility, meaning the
    contract's `facility_id` equals the day's `facility_id`, or
    `ERR_CONTRACT_FACILITY_MISMATCH`."

    Design: Corner/validations/contract_facility_mismatch_rejected
    """
    bundle = setup_plan_context()
    other_facility = create_facility(name="Clinic B", address="2 B Ave")
    other_contract = create_contract(other_facility["id"])
    payload = create_site_day_payload(
        bundle["plan"]["id"], bundle["facility"]["id"], other_contract["id"],
        "2026-08-04",
    )
    resp = api.create_site_day(payload, OPS)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_FACILITY_MISMATCH)


def test_site_day_get_missing_id_returns_not_found(api):
    """PRD §2.8: "The existence family comprises `ERR_FACILITY_NOT_FOUND`,
    `ERR_UNIT_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_ROUTE_PLAN_NOT_FOUND`,
    `ERR_SITE_DAY_NOT_FOUND`, ... and the generic `ERR_NOT_FOUND`."

    Design: Corner/entities/site_day_get_missing_id_returns_not_found
    """
    resp = api.get_site_day(NON_EXISTENT_UUID, OPS)
    validate_error(resp, ApiErrorId.ERR_SITE_DAY_NOT_FOUND)


def test_site_days_filtered_by_facility(api):
    """PRD §2.3: "Many list endpoints additionally accept resource-specific
    filter query parameters (for example, the unit list accepts `modality` and
    `active_breakdown_id`, and the contract list accepts `facility_id`); each
    filter narrows the listing to exact matches on the named field".

    Design: Corner/endpoints/site_days_filtered_by_facility
    """
    bundle = setup_bookable_day()  # day A on 2026-08-04 at facility A
    facility_b = create_facility(name="Clinic B", address="2 B Ave")
    contract_b = create_contract(facility_b["id"])
    day_b = add_site_day(
        bundle["plan"]["id"], facility_b["id"], contract_b["id"], "2026-08-05"
    )

    data, meta = validate_paginated(
        api.list_site_days(OPS, params={"facility_id": facility_b["id"]})
    )
    assert meta["total_count"] == 1, f"Expected 1 site day for facility B, got {meta['total_count']}"
    assert data[0]["id"] == day_b["id"], (
        f"Filtered day must be {day_b['id']}, got {data[0]['id']}"
    )


def test_unit_day_double_booking_disjoint_windows_rejected(api):
    """PRD §3.2: "Finally, unit day-exclusivity is enforced: if any other site
    day exists for the same unit on the same `service_date` in a status other
    than `CANCELLED` or `RESCHEDULED`, creation is rejected with
    `ERR_UNIT_DAY_DOUBLE_BOOKED` — capacity is a whole calendar day, so two
    same-date days with disjoint time windows still conflict."

    Design: Difficulty/resource_temporal_overlap/unit_day_double_booking_discrete_capacity
    """
    bundle = setup_bookable_day()  # morning day on 2026-08-04, plan PUBLISHED
    facility_b = create_facility(name="Clinic B", address="2 B Ave")
    contract_b = create_contract(facility_b["id"])
    evening = create_site_day_payload(
        bundle["plan"]["id"], facility_b["id"], contract_b["id"], "2026-08-04",
        arrival_time="17:30", first_patient_time="18:30",
        last_patient_time="20:00", departure_time="20:45",
    )
    resp = api.create_site_day(evening, OPS)
    validate_error(resp, ApiErrorId.ERR_UNIT_DAY_DOUBLE_BOOKED)


def test_unit_day_double_booking_next_date_allowed(api):
    """PRD §3.2: "Finally, unit day-exclusivity is enforced: if any other site
    day exists for the same unit on the same `service_date` in a status other
    than `CANCELLED` or `RESCHEDULED`, creation is rejected with
    `ERR_UNIT_DAY_DOUBLE_BOOKED` — capacity is a whole calendar day, so two
    same-date days with disjoint time windows still conflict."

    Design: Difficulty/resource_temporal_overlap/unit_day_double_booking_discrete_capacity
    """
    bundle = setup_bookable_day()  # morning day on 2026-08-04
    facility_b = create_facility(name="Clinic B", address="2 B Ave")
    contract_b = create_contract(facility_b["id"])
    # Same evening geometry on the next date: no conflict.
    next_day = create_site_day_payload(
        bundle["plan"]["id"], facility_b["id"], contract_b["id"], "2026-08-05",
        arrival_time="17:30", first_patient_time="18:30",
        last_patient_time="20:00", departure_time="20:45",
    )
    resp = api.create_site_day(next_day, OPS)
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"
    assert data["service_date"] == "2026-08-05"
