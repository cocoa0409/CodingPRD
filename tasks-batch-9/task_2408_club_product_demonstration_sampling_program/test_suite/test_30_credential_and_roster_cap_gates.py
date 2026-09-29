"""Credential requirements that follow the product, and the weekly roster ceiling."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    STAFF_OPS_HEADERS,
    make_manufacturer_headers,
)
from test_helpers.fixtures import (
    approve,
    assign,
    certify,
    new_club,
    new_demo_event,
    new_demonstrator,
    new_food_product,
    new_manufacturer,
    new_non_food_product,
    submit,
)
from test_helpers.types import (
    AssignmentRole,
    AssignmentStatus,
    CertStatus,
    CertType,
    DayPart,
    ProductCategory,
    StaffingStatus,
)


def test_the_heat_credential_is_demanded_only_by_the_product_that_needs_it(api):
    """PRD §3.4: "The remaining checks then run in the ladder order of §2.8: the worker must be `ACTIVE`; a `FOOD_SAMPLING` event demands a valid `FOOD_HANDLER` certificate, with a valid `HEAT_EQUIPMENT` certificate on top when the product has `requires_heat_equipment` set and a valid `ALLERGEN_AWARENESS` certificate on top when it has `allergen_flag` set; the worker's `home_club_id` must equal the event's `club_id` unless the request sets `travel_authorized` to true; and then the schedule and cap tests below."

    PRD §2.8: "**Specialty certification.** When the demonstrated product has `requires_heat_equipment` set, the demonstrator must additionally hold a `HEAT_EQUIPMENT` certification, and when the product has `allergen_flag` set, an `ALLERGEN_AWARENESS` certification — each judged valid by the same test as rung 17. A missing one is `ERR_SPECIALTY_CERT_MISSING` (422)."

    PRD §3.4: "Coverage then reads `UNSTAFFED` when there are no held leads and no held supports; `FULLY_STAFFED` when there is at least one held lead and the held support count has reached at least `required_support_count`; and `PARTIALLY_STAFFED` in every remaining case."

    Design: Corner/validations/specialty_certification_is_required_only_when_the_product_flag_is_set
    """
    vendor = new_manufacturer(api, legal_name="Glenmara Kitchen", credit_limit_cents=900_000)
    club = new_club(
        api,
        club_number="C6029",
        name="Glenmara Club 6029",
        daily_event_capacity=3,
        food_station_count=2,
        health_permit_expires_on="2027-12-31",
    )
    plain_product = new_food_product(
        api,
        vendor["id"],
        sku="GK-SLS-029",
        name="Chilled Salsa",
        category=ProductCategory.SNACK,
        requires_heat_equipment=False,
        allergen_flag=False,
        unit_cost_cents=210,
        samples_per_case=60,
        weekly_sample_case_pool=24,
    )
    heat_product = new_food_product(
        api,
        vendor["id"],
        sku="GK-PIE-029",
        name="Baked Hand Pie",
        category=ProductCategory.BAKERY,
        requires_heat_equipment=True,
        allergen_flag=False,
        unit_cost_cents=240,
        samples_per_case=48,
        weekly_sample_case_pool=24,
    )
    assert heat_product["requires_heat_equipment"] is True

    worker = new_demonstrator(
        api, club["id"], full_name="Hana Sorrel", hourly_rate_cents=2500
    )
    certify(
        api,
        worker["id"],
        cert_type=CertType.FOOD_HANDLER,
        certificate_number="FH-2026-6029",
        issued_on="2026-02-01",
        expires_on="2027-02-01",
    )

    plain_event = new_demo_event(
        api,
        vendor["id"],
        club["id"],
        plain_product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MIDDAY,
        requested_sample_cases=3,
    )
    heat_event = new_demo_event(
        api,
        vendor["id"],
        club["id"],
        heat_product["id"],
        event_date="2026-09-21",
        day_part=DayPart.MIDDAY,
        requested_sample_cases=3,
    )
    submit(api, plain_event["id"], vendor["id"])
    approve(api, plain_event["id"], club["id"])
    submit(api, heat_event["id"], vendor["id"])
    approve(api, heat_event["id"], club["id"])

    plain_assignment = assign(
        api, plain_event["id"], worker["id"], AssignmentRole.LEAD
    )
    assert plain_assignment["assignment_status"] == AssignmentStatus.ASSIGNED

    refusal = validate_error(
        api.create_assignment(
            heat_event["id"],
            {"demonstrator_id": worker["id"], "role": AssignmentRole.LEAD},
            STAFF_OPS_HEADERS,
        ),
        ApiErrorId.SPECIALTY_CERT_MISSING,
        422,
    )
    assert refusal["error_id"] != ApiErrorId.FOOD_CERT_INVALID

    heat_certificate = certify(
        api,
        worker["id"],
        cert_type=CertType.HEAT_EQUIPMENT,
        certificate_number="HE-2026-6029",
        issued_on="2026-04-01",
        expires_on="2027-04-01",
    )
    assert heat_certificate["cert_status"] == CertStatus.VALID

    heat_assignment = assign(api, heat_event["id"], worker["id"], AssignmentRole.LEAD)
    assert heat_assignment["assignment_status"] == AssignmentStatus.ASSIGNED

    covered = validate_success(
        api.get_demo_event(heat_event["id"], make_manufacturer_headers(vendor["id"]))
    )
    assert covered["staffing_status"] == StaffingStatus.FULLY_STAFFED

    credentials = validate_success(api.list_certifications(worker["id"], STAFF_OPS_HEADERS))
    assert len(credentials) == 2


def test_two_shifts_that_never_touch_still_exhaust_one_workers_week(api):
    """PRD §3.4: "The weekly cap takes the Monday of the ISO week containing the new event's `event_date`, counts the worker's assignments whose event dates fall on or after that Monday and strictly before the Monday plus seven days, and refuses the request with `ERR_DEMONSTRATOR_WEEKLY_CAP_EXCEEDED` once that count has reached the worker's `max_weekly_events`."

    PRD §2.8: "**Worker weekly cap.** The demonstrator's count of same-ISO-week assignments in those four statuses must be strictly below that demonstrator's `max_weekly_events` — otherwise `ERR_DEMONSTRATOR_WEEKLY_CAP_EXCEEDED` (409)."

    PRD §3.4: "Adding a demonstrator captures a `home_club_id` naming the club the worker is rostered to, a `full_name`, an `hourly_rate_cents` of at least 1 that will price the invoice's staffing lines, and an optional `max_weekly_events` from 1 through 14 that defaults to 5."

    Design: Corner/validations/individually_legal_assignments_breach_the_weekly_aggregate_cap
    """
    vendor = new_manufacturer(api, legal_name="Hartsmere Supply", credit_limit_cents=900_000)
    club = new_club(
        api,
        club_number="C6030",
        name="Hartsmere Club 6030",
        daily_event_capacity=3,
        food_station_count=1,
        health_permit_expires_on="2027-06-30",
    )
    product = new_non_food_product(
        api,
        vendor["id"],
        sku="HS-BRD-030",
        name="Cutting Board",
        category=ProductCategory.HOUSEHOLD,
        unit_cost_cents=2000,
        samples_per_case=2,
        weekly_sample_case_pool=20,
    )
    capped_worker = new_demonstrator(
        api,
        club["id"],
        full_name="Ines Baratta",
        hourly_rate_cents=2200,
        max_weekly_events=1,
    )
    spare_worker = new_demonstrator(
        api, club["id"], full_name="Jonas Weir", hourly_rate_cents=2100
    )
    assert capped_worker["max_weekly_events"] == 1

    monday_event = new_demo_event(
        api,
        vendor["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MORNING,
        requested_sample_cases=2,
    )
    wednesday_event = new_demo_event(
        api,
        vendor["id"],
        club["id"],
        product["id"],
        event_date="2026-09-16",
        day_part=DayPart.MORNING,
        requested_sample_cases=2,
    )
    submit(api, monday_event["id"], vendor["id"])
    approve(api, monday_event["id"], club["id"])
    submit(api, wednesday_event["id"], vendor["id"])
    approve(api, wednesday_event["id"], club["id"])

    first_assignment = assign(
        api, monday_event["id"], capped_worker["id"], AssignmentRole.LEAD
    )
    assert first_assignment["assignment_status"] == AssignmentStatus.ASSIGNED

    refusal = validate_error(
        api.create_assignment(
            wednesday_event["id"],
            {"demonstrator_id": capped_worker["id"], "role": AssignmentRole.LEAD},
            STAFF_OPS_HEADERS,
        ),
        ApiErrorId.DEMONSTRATOR_WEEKLY_CAP_EXCEEDED,
        409,
    )
    assert refusal["error_id"] != ApiErrorId.DEMONSTRATOR_DAILY_CAP_EXCEEDED
    assert refusal["error_id"] != ApiErrorId.DEMONSTRATOR_DOUBLE_BOOKED

    spare_assignment = assign(
        api, wednesday_event["id"], spare_worker["id"], AssignmentRole.LEAD
    )
    assert spare_assignment["assignment_status"] == AssignmentStatus.ASSIGNED

    covered = validate_success(
        api.get_demo_event(
            wednesday_event["id"], make_manufacturer_headers(vendor["id"])
        )
    )
    assert covered["staffing_status"] == StaffingStatus.FULLY_STAFFED
