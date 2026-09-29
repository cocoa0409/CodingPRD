"""Coverage bubbling, sanitation hand-offs and credential revocation."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    STAFF_OPS_HEADERS,
    find_row,
    make_club_headers,
    make_manufacturer_headers,
)
from test_helpers.fixtures import (
    approve,
    assign,
    certify,
    check_in,
    confirm_assignment,
    new_club,
    new_demo_event,
    new_demonstrator,
    new_equipment_unit,
    new_food_product,
    new_manufacturer,
    new_non_food_product,
    reserve,
    set_clock,
    submit,
)
from test_helpers.types import (
    AssignmentRole,
    AssignmentStatus,
    BookingStatus,
    CertStatus,
    CertType,
    DayPart,
    EquipmentType,
    ProductCategory,
    ReservationAction,
    ReservationStatus,
    SanitationStatus,
    StaffingStatus,
)


def test_only_the_lead_check_in_pushes_coverage_past_fully_staffed(api):
    """PRD §3.6: "When the checking-in assignment has `role` `LEAD`, the check-in also drives the event's coverage dimension from `FULLY_STAFFED` to `EXECUTED`, which requires the event's `booking_status` to be `CONFIRMED` and requires that the transitioning assignment is indeed the lead; the event's `version` increments by 1 for that move."

    PRD §3.6: "A `SUPPORT` worker checking in never produces `EXECUTED`."

    PRD §3.6: "A successful check-in writes the recorded instant to `check_in_at` and then sets `late_check_in` to true when that instant falls strictly after 10 minutes past `scheduled_start_utc`, and to false otherwise — the ten-minute grace period is what separates a punctual arrival from a late one, and a late completion later costs the worker reliability points."

    PRD §3.4: "The event's `required_support_count` reads 1 when its `event_type` is `FOOD_SAMPLING` and its `allocated_sample_cases` has reached at least 6, and 0 otherwise."

    Design: Corner/state_machines/lead_check_in_bubbles_the_events_staffing_dimension_to_executed
    """
    vendor = new_manufacturer(api, legal_name="Quillhaven Housewares")
    club = new_club(api, club_number="C6016", daily_event_capacity=3, food_station_count=1)
    product = new_non_food_product(
        api,
        vendor["id"],
        sku="QH-VAC-016",
        name="Handheld Vacuum",
        category=ProductCategory.HOUSEHOLD,
        unit_cost_cents=4200,
        samples_per_case=2,
        weekly_sample_case_pool=20,
    )
    lead_worker = new_demonstrator(
        api, club["id"], full_name="Rina Delacroix", hourly_rate_cents=2400
    )
    support_worker = new_demonstrator(
        api, club["id"], full_name="Soren Hale", hourly_rate_cents=2000
    )
    event = new_demo_event(
        api,
        vendor["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MORNING,
        requested_sample_cases=8,
    )
    submit(api, event["id"], vendor["id"])
    confirmed = approve(api, event["id"], club["id"])
    assert confirmed["required_support_count"] == 0

    lead_assignment = assign(api, event["id"], lead_worker["id"], AssignmentRole.LEAD)
    support_assignment = assign(
        api, event["id"], support_worker["id"], AssignmentRole.SUPPORT
    )
    staffed = validate_success(api.get_demo_event(event["id"], STAFF_OPS_HEADERS))
    assert staffed["staffing_status"] == StaffingStatus.FULLY_STAFFED

    set_clock(api, "2026-09-14T09:00:00Z")
    confirm_assignment(api, lead_assignment["id"], lead_worker["id"])
    confirm_assignment(api, support_assignment["id"], support_worker["id"])

    support_checked_in = check_in(
        api, support_assignment["id"], support_worker["id"], "2026-09-14T08:15:00Z"
    )
    assert support_checked_in["assignment_status"] == AssignmentStatus.CHECKED_IN
    assert support_checked_in["late_check_in"] is False
    mid = validate_success(api.get_demo_event(event["id"], STAFF_OPS_HEADERS))
    assert mid["staffing_status"] == StaffingStatus.FULLY_STAFFED

    lead_checked_in = check_in(
        api, lead_assignment["id"], lead_worker["id"], "2026-09-14T08:27:00Z"
    )
    assert lead_checked_in["assignment_status"] == AssignmentStatus.CHECKED_IN
    assert lead_checked_in["late_check_in"] is True

    executed = validate_success(api.get_demo_event(event["id"], STAFF_OPS_HEADERS))
    assert executed["staffing_status"] == StaffingStatus.EXECUTED
    assert executed["booking_status"] == BookingStatus.CONFIRMED


def test_a_released_unit_must_be_cleaned_before_it_serves_again(api):
    """PRD §3.5: "Releasing from `ACTIVE` sets the unit's `sanitation_status` to `SOILED`, because a unit that has been in service must be cleaned before it can serve again, and likewise increments the reservation's `version` by 1."

    PRD §3.5: "Activation sets the unit's `sanitation_status` to `IN_USE` and increments the reservation's `version` by 1."

    PRD §3.5: "A unit is a capacity-one resource: only the reservations on that same `equipment_unit_id` whose `reservation_status` is `HELD` or `ACTIVE` are candidates, and released reservations are ignored entirely."

    PRD §3.5: "Club floor management (or head office) may do it only while the event's `booking_status` is `CONFIRMED`, only while the unit's `sanitation_status` reads `SANITIZED` — otherwise `ERR_EQUIPMENT_NOT_SANITIZED` — and only while the logical clock's current instant falls within the closed interval that begins 60 minutes before the reservation's `window_start_utc` and ends at its `window_end_utc`."

    Design: Corner/state_machines/reservation_transitions_drive_the_equipment_units_sanitation_status
    """
    vendor = new_manufacturer(api, legal_name="Redlow Electronics")
    club = new_club(api, club_number="C6017", daily_event_capacity=3, food_station_count=1)
    product = new_non_food_product(
        api,
        vendor["id"],
        sku="RE-SPK-017",
        name="Bluetooth Speaker",
        category=ProductCategory.ELECTRONICS,
        unit_cost_cents=4900,
        samples_per_case=2,
        weekly_sample_case_pool=12,
    )
    unit = new_equipment_unit(
        api, club["id"], asset_tag="EQ-6017-TV", equipment_type=EquipmentType.TV_CART
    )
    event = new_demo_event(
        api,
        vendor["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MORNING,
        requested_sample_cases=2,
    )
    submit(api, event["id"], vendor["id"])
    approve(api, event["id"], club["id"])
    club_headers = make_club_headers(club["id"])

    first_hold = reserve(
        api,
        club["id"],
        unit["id"],
        event["id"],
        "2026-09-14T08:00:00Z",
        "2026-09-14T13:30:00Z",
    )
    set_clock(api, "2026-09-14T08:00:00Z")

    activated = validate_success(
        api.reservation_transition(
            first_hold["id"], {"action": ReservationAction.ACTIVATE}, club_headers
        )
    )
    assert activated["reservation_status"] == ReservationStatus.ACTIVE
    in_use_unit = validate_success(api.get_equipment_unit(unit["id"], club_headers))
    assert in_use_unit["sanitation_status"] == SanitationStatus.IN_USE

    released = validate_success(
        api.reservation_transition(
            first_hold["id"], {"action": ReservationAction.RELEASE}, club_headers
        )
    )
    assert released["reservation_status"] == ReservationStatus.RELEASED
    soiled_unit = validate_success(api.get_equipment_unit(unit["id"], club_headers))
    assert soiled_unit["sanitation_status"] == SanitationStatus.SOILED

    second_hold = reserve(
        api,
        club["id"],
        unit["id"],
        event["id"],
        "2026-09-14T08:00:00Z",
        "2026-09-14T13:30:00Z",
    )
    assert second_hold["reservation_status"] == ReservationStatus.HELD

    validate_error(
        api.reservation_transition(
            second_hold["id"], {"action": ReservationAction.ACTIVATE}, club_headers
        ),
        ApiErrorId.EQUIPMENT_NOT_SANITIZED,
        422,
    )
    still_held = validate_success(api.get_reservation(second_hold["id"], club_headers))
    assert still_held["reservation_status"] == ReservationStatus.HELD


def test_revoking_a_credential_blocks_new_work_but_leaves_the_old_row_standing(api):
    """PRD §3.4: "Revoking a certificate — optionally with a `reason` — stamps `revoked_at` with the logical clock's current instant, drives `cert_status` to `REVOKED`, and increments the certificate's `version` by 1; the worker fails the certification gate from that instant onward."

    PRD §3.4: "For the purpose of staffing an event, a certificate is valid when its `revoked_at` is unset **and** its `expires_on` falls on or after the event's `event_date` — the boundary is inclusive, so a certificate expiring on the day of the demo still covers that demo."

    PRD §2.8: "**Food-handler certification.** Creating an assignment on a `FOOD_SAMPLING` event requires the demonstrator to hold a certification whose `cert_type` is `FOOD_HANDLER`, whose `revoked_at` is unset, and whose `expires_on` is on or after the event's `event_date` — otherwise `ERR_FOOD_CERT_INVALID` (422)."

    Design: Corner/state_machines/revoking_a_certification_marks_it_revoked_without_touching_past_assignments
    """
    vendor = new_manufacturer(api, legal_name="Sableridge Creamery")
    club = new_club(api, club_number="C6018", daily_event_capacity=3, food_station_count=2)
    product = new_food_product(
        api,
        vendor["id"],
        sku="SR-YOG-018",
        name="Skyr Cups",
        category=ProductCategory.DAIRY,
        unit_cost_cents=180,
        samples_per_case=60,
        weekly_sample_case_pool=24,
    )
    worker = new_demonstrator(
        api, club["id"], full_name="Tamsin Ocheda", hourly_rate_cents=2300
    )
    certificate = certify(
        api,
        worker["id"],
        cert_type=CertType.FOOD_HANDLER,
        certificate_number="FH-2026-6018",
        issued_on="2026-03-01",
        expires_on="2027-03-01",
    )
    assert certificate["cert_status"] == CertStatus.VALID

    first_event = new_demo_event(
        api,
        vendor["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MIDDAY,
        requested_sample_cases=3,
    )
    second_event = new_demo_event(
        api,
        vendor["id"],
        club["id"],
        product["id"],
        event_date="2026-09-21",
        day_part=DayPart.MIDDAY,
        requested_sample_cases=3,
    )
    submit(api, first_event["id"], vendor["id"])
    approve(api, first_event["id"], club["id"])
    submit(api, second_event["id"], vendor["id"])
    approve(api, second_event["id"], club["id"])

    earlier_assignment = assign(
        api, first_event["id"], worker["id"], AssignmentRole.LEAD
    )
    assert earlier_assignment["assignment_status"] == AssignmentStatus.ASSIGNED

    revoked = validate_success(
        api.revoke_certification(
            worker["id"],
            certificate["id"],
            {"reason": "health inspection audit finding"},
            STAFF_OPS_HEADERS,
        )
    )
    assert revoked["cert_status"] == CertStatus.REVOKED
    assert revoked["revoked_at"] is not None

    validate_error(
        api.create_assignment(
            second_event["id"],
            {"demonstrator_id": worker["id"], "role": AssignmentRole.LEAD},
            STAFF_OPS_HEADERS,
        ),
        ApiErrorId.FOOD_CERT_INVALID,
        422,
    )

    untouched = validate_success(
        api.get_assignment(earlier_assignment["id"], STAFF_OPS_HEADERS)
    )
    assert untouched["assignment_status"] == AssignmentStatus.ASSIGNED

    vendor_headers = make_manufacturer_headers(vendor["id"])
    first_after = validate_success(api.get_demo_event(first_event["id"], vendor_headers))
    second_after = validate_success(
        api.get_demo_event(second_event["id"], vendor_headers)
    )
    assert first_after["staffing_status"] == StaffingStatus.FULLY_STAFFED
    assert second_after["staffing_status"] == StaffingStatus.UNSTAFFED

    listed = validate_success(
        api.list_certifications(
            worker["id"], STAFF_OPS_HEADERS, {"cert_type": CertType.FOOD_HANDLER}
        )
    )
    assert len(listed) == 1
    assert find_row(listed, id=certificate["id"])["cert_status"] == CertStatus.REVOKED
