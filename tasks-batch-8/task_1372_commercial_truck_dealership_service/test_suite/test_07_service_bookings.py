"""Service booking overlap semantics, operating hours, resource status, and
resource selection (PRD §3.5, §2.10)."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated, get_success_data,
    create_account, create_repair_order, create_bay, create_mobile_unit,
    create_bay_booking, create_service_booking_payload,
)

ADVISOR = TEST_USERS["service_advisor_headers"]
SERVICE_MGR = TEST_USERS["service_manager_headers"]

DAY = "2026-08-05"


def _ro():
    return create_repair_order(create_account(name="B")["id"])


def _count_bookings(**params):
    _, meta = validate_paginated(api_client.list_service_bookings(ADVISOR, params=params))
    return meta["total_count"]


# ---------------------------------------------------------------- Queue A ---

class TestBayBookingsHalfOpenAdjacency:
    def test_back_to_back_bay_booking_allowed(self, api):
        """PRD §3.5: "two bay bookings conflict only when the existing one's
        start is strictly before the new one's end and the new one's start is
        strictly before the existing one's end — so a booking beginning exactly
        when another ends is allowed."

        Design: Difficulty/resource_temporal_overlap/bay_bookings_half_open_adjacency_allowed
        """
        ro = _ro()
        bay = create_bay()
        create_bay_booking(ro["id"], bay["id"], f"{DAY}T09:00:00Z", f"{DAY}T11:00:00Z")
        resp = api_client.create_service_booking(
            create_service_booking_payload(repair_order_id=ro["id"],
                                           service_bay_id=bay["id"],
                                           start_at=f"{DAY}T11:00:00Z",
                                           end_at=f"{DAY}T13:00:00Z"),
            ADVISOR)
        data = validate_success(resp, 201)
        assert data["status"] == "BOOKED"

    def test_one_minute_setback_conflicts(self, api):
        """PRD §3.5: "Violations raise `ERR_BAY_BOOKING_OVERLAP`."
        PRD §3.5: "in both cases only bookings in `BOOKED` or `CHECKED_IN`
        status participate, against the same resource."

        Design: Difficulty/resource_temporal_overlap/bay_bookings_half_open_adjacency_allowed
        """
        ro = _ro()
        bay = create_bay()
        create_bay_booking(ro["id"], bay["id"], f"{DAY}T09:00:00Z", f"{DAY}T11:00:00Z")
        create_bay_booking(ro["id"], bay["id"], f"{DAY}T11:00:00Z", f"{DAY}T13:00:00Z")
        resp = api_client.create_service_booking(
            create_service_booking_payload(repair_order_id=ro["id"],
                                           service_bay_id=bay["id"],
                                           start_at=f"{DAY}T10:30:00Z",
                                           end_at=f"{DAY}T12:00:00Z"),
            ADVISOR)
        validate_error(resp, ApiErrorId.ERR_BAY_BOOKING_OVERLAP)
        assert _count_bookings(service_bay_id=bay["id"]) == 2


class TestMobileBookingsClosedInterval:
    def _setup_mobile(self):
        ro = _ro()
        msu = create_mobile_unit(default_travel_minutes=30)
        create = api_client.create_service_booking(
            create_service_booking_payload(repair_order_id=ro["id"],
                                           mobile_service_unit_id=msu["id"],
                                           start_at=f"{DAY}T09:00:00Z",
                                           end_at=f"{DAY}T11:00:00Z",
                                           travel_minutes=30),
            ADVISOR)
        assert create.status_code == 201, f"Setup failed: {create.text}"
        return ro, msu

    def test_exact_buffer_touch_conflicts(self, api):
        """PRD §3.5: "Mobile bookings instead expand to a closed interval
        covering one `travel_minutes` buffer on each side — from
        `travel_minutes` before the start to `travel_minutes` after the end —
        and two expanded intervals conflict whenever they touch at all; an
        exact buffer-to-buffer touch counts as a conflict, so adjacency is not
        allowed on the road. Violations raise `ERR_MOBILE_BOOKING_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/mobile_bookings_closed_interval_buffer_touch_conflicts
        """
        ro, msu = self._setup_mobile()
        # Existing effective window [08:30, 11:30]; new 11:30 booking expands to
        # [11:00, 14:00] and touches at 11:30.
        resp = api_client.create_service_booking(
            create_service_booking_payload(repair_order_id=ro["id"],
                                           mobile_service_unit_id=msu["id"],
                                           start_at=f"{DAY}T11:30:00Z",
                                           end_at=f"{DAY}T13:30:00Z",
                                           travel_minutes=30),
            ADVISOR)
        validate_error(resp, ApiErrorId.ERR_MOBILE_BOOKING_OVERLAP)

    def test_one_minute_past_buffer_clears(self, api):
        """PRD §3.5: "two expanded intervals conflict whenever they touch at
        all; an exact buffer-to-buffer touch counts as a conflict, so adjacency
        is not allowed on the road."

        Design: Difficulty/resource_temporal_overlap/mobile_bookings_closed_interval_buffer_touch_conflicts
        """
        ro, msu = self._setup_mobile()
        # 12:01 start expands to [11:31, 13:30]; 11:31 > 11:30 clears.
        resp = api_client.create_service_booking(
            create_service_booking_payload(repair_order_id=ro["id"],
                                           mobile_service_unit_id=msu["id"],
                                           start_at=f"{DAY}T12:01:00Z",
                                           end_at=f"{DAY}T13:00:00Z",
                                           travel_minutes=30),
            ADVISOR)
        data = validate_success(resp, 201)
        assert data["status"] == "BOOKED"
        assert _count_bookings(mobile_service_unit_id=msu["id"]) == 2


class TestHoursConstraintOutranksOverlap:
    def _setup(self):
        ro = _ro()
        bay = create_bay()  # default hours 7..19
        create_bay_booking(ro["id"], bay["id"], f"{DAY}T17:00:00Z", f"{DAY}T19:00:00Z")
        return ro, bay

    def test_combined_violation_reports_operating_hours(self, api):
        """PRD §2.10(12): "Operating-hours and resource-active checks —
        `ERR_BAY_OUTSIDE_OPERATING_HOURS` (422) / `ERR_RESOURCE_OUT_OF_SERVICE`
        (409)."
        PRD §2.10(16): "Booking overlap — `ERR_BAY_BOOKING_OVERLAP` /
        `ERR_MOBILE_BOOKING_OVERLAP` (409)."
        PRD §2.10: "When a request fails several rules, the first failing check
        by the following fixed priority determines the error returned".

        Design: Difficulty/priority_pair_validation_conflict/booking_constraint_error_outranks_overlap_temporal
        """
        ro, bay = self._setup()
        # 18:30-20:30 overlaps the 17:00-19:00 booking AND ends past close_hour 19.
        resp = api_client.create_service_booking(
            create_service_booking_payload(repair_order_id=ro["id"],
                                           service_bay_id=bay["id"],
                                           start_at=f"{DAY}T18:30:00Z",
                                           end_at=f"{DAY}T20:30:00Z"),
            ADVISOR)
        validate_error(resp, ApiErrorId.ERR_BAY_OUTSIDE_OPERATING_HOURS)
        assert _count_bookings(service_bay_id=bay["id"]) == 1

    def test_isolated_overlap_reports_overlap(self, api):
        """PRD §3.5: "Bay bookings must additionally respect the bay's day: the
        start hour must be at or after `open_hour` and the end must fall by
        `close_hour` of the same day, else `ERR_BAY_OUTSIDE_OPERATING_HOURS`."
        PRD §3.5: "Violations raise `ERR_BAY_BOOKING_OVERLAP`."

        Design: Difficulty/priority_pair_validation_conflict/booking_constraint_error_outranks_overlap_temporal
        """
        ro, bay = self._setup()
        # Within hours but overlapping -> overlap error surfaces.
        resp = api_client.create_service_booking(
            create_service_booking_payload(repair_order_id=ro["id"],
                                           service_bay_id=bay["id"],
                                           start_at=f"{DAY}T18:00:00Z",
                                           end_at=f"{DAY}T18:30:00Z"),
            ADVISOR)
        validate_error(resp, ApiErrorId.ERR_BAY_BOOKING_OVERLAP)
        assert _count_bookings(service_bay_id=bay["id"]) == 1


# ---------------------------------------------------------------- Queue B ---

def test_booking_on_out_of_service_resource_rejected(api):
    """PRD §3.5: "Both resources are born `ACTIVE` and may be set
    `OUT_OF_SERVICE` by the service manager; existing bookings stand when a
    resource goes down, but new bookings against it are refused with
    `ERR_RESOURCE_OUT_OF_SERVICE`."

    Design: Corner/validations/booking_on_out_of_service_resource_rejected
    """
    ro = _ro()
    bay = create_bay()
    validate_success(api_client.set_service_bay_status(
        bay["id"], {"status": "OUT_OF_SERVICE"}, SERVICE_MGR), 200)
    validate_error(api_client.create_service_booking(
        create_service_booking_payload(repair_order_id=ro["id"],
                                       service_bay_id=bay["id"]),
        ADVISOR), ApiErrorId.ERR_RESOURCE_OUT_OF_SERVICE)
    validate_success(api_client.set_service_bay_status(
        bay["id"], {"status": "ACTIVE"}, SERVICE_MGR), 200)
    resp = api_client.create_service_booking(
        create_service_booking_payload(repair_order_id=ro["id"],
                                       service_bay_id=bay["id"]),
        ADVISOR)
    assert validate_success(resp, 201)["status"] == "BOOKED"


def test_booking_resource_selection_exactly_one(api):
    """PRD §3.5: "reserving exactly one resource: `service_bay_id` or
    `mobile_service_unit_id`, never both, never neither — a violation is
    `ERR_SERVICE_RESOURCE_SELECTION`, as is a nonzero `travel_minutes` on a bay
    booking (travel buffer defaults to zero and applies to mobile bookings
    only)."

    Design: Corner/validations/booking_resource_selection_exactly_one
    """
    ro = _ro()
    bay = create_bay()
    msu = create_mobile_unit()
    base = {"repair_order_id": ro["id"], "start_at": f"{DAY}T09:00:00Z",
            "end_at": f"{DAY}T10:00:00Z"}
    # Neither resource.
    validate_error(api_client.create_service_booking(dict(base), ADVISOR),
                   ApiErrorId.ERR_SERVICE_RESOURCE_SELECTION)
    # Both resources.
    validate_error(api_client.create_service_booking(
        dict(base, service_bay_id=bay["id"], mobile_service_unit_id=msu["id"]), ADVISOR),
        ApiErrorId.ERR_SERVICE_RESOURCE_SELECTION)
    # Bay booking carrying a travel buffer.
    validate_error(api_client.create_service_booking(
        dict(base, service_bay_id=bay["id"], travel_minutes=15), ADVISOR),
        ApiErrorId.ERR_SERVICE_RESOURCE_SELECTION)
