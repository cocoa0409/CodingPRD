"""Class capacity boundary, registration listing/pagination, not-found and
creation-time eligibility rejections."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, MISSING_UUID,
    create_class_payload,
    create_event_with_class_and_zone, create_open_event,
    create_registrant_with_vehicle, create_registration,
    create_paid_registration, get_class,
)

ORG = TEST_USERS["organizer_headers"]
DESK = TEST_USERS["desk_headers"]


class TestClassCapacityBoundary:
    def _setup(self, api):
        ev, cls, zone = create_open_event(
            class_overrides={"code": "TINY", "capacity": 2})
        people = []
        for i, (year, make, model) in enumerate([
            (1970, "Ford", "Mustang"), (1971, "Chevrolet", "Chevelle"),
            (1972, "Pontiac", "GTO"),
        ]):
            reg, veh = create_registrant_with_vehicle(
                name=f"C{i}", email=f"c{i}@example.com",
                vehicle_overrides={"year": year, "make": make, "model": model})
            people.append((reg, veh))
        return ev, cls, people

    def test_create_at_exact_capacity_succeeds(self, api):
        """PRD §3.2: "once its `confirmed_count` has reached `capacity`, further
        creates are rejected with `ERR_CLASS_FULL`, while a create arriving below
        capacity succeeds — so the final seat is filled exactly at capacity."

        Design: Difficulty/boundary_precision_check/class_capacity_exact_boundary
        """
        ev, cls, people = self._setup(api)
        r1 = validate_success(api.create_registration(
            {"event_id": ev["id"], "registrant_id": people[0][0]["id"],
             "vehicle_id": people[0][1]["id"], "class_id": cls["id"]}, DESK), expected_status=201)
        r2 = validate_success(api.create_registration(
            {"event_id": ev["id"], "registrant_id": people[1][0]["id"],
             "vehicle_id": people[1][1]["id"], "class_id": cls["id"]}, DESK), expected_status=201)
        cls_after = get_class(ev["id"], cls["id"])
        assert cls_after["confirmed_count"] == 2, "exactly at capacity"

    def test_create_beyond_capacity_rejected_and_count_stable(self, api):
        """PRD §3.2: "once its `confirmed_count` has reached `capacity`, further
        creates are rejected with `ERR_CLASS_FULL`".

        Design: Difficulty/boundary_precision_check/class_capacity_exact_boundary
        """
        ev, cls, people = self._setup(api)
        for reg, veh in people[:2]:
            validate_success(api.create_registration(
                {"event_id": ev["id"], "registrant_id": reg["id"],
                 "vehicle_id": veh["id"], "class_id": cls["id"]}, DESK), expected_status=201)
        resp = api.create_registration(
            {"event_id": ev["id"], "registrant_id": people[2][0]["id"],
             "vehicle_id": people[2][1]["id"], "class_id": cls["id"]}, DESK)
        validate_error(resp, ApiErrorId.ERR_CLASS_FULL)
        cls_after = get_class(ev["id"], cls["id"])
        assert cls_after["confirmed_count"] == 2, "rejected create must not move the count"


class TestRegistrationListing:
    def _setup_two_registrations(self, api):
        ev, cls, zone = create_open_event()
        reg, v1 = create_registrant_with_vehicle(name="P1", email="p1@example.com")
        v2 = get_success_data(api.create_vehicle(
            reg["id"], {"year": 1971, "make": "Chevrolet", "model": "Chevelle"}, ORG))
        r1 = create_registration(ev["id"], reg["id"], v1["id"], cls["id"])
        r2 = create_registration(ev["id"], reg["id"], v2["id"], cls["id"])
        return ev, r1, r2

    def test_registrations_list_pagination_envelope(self, api):
        """PRD §2.3: "The `meta` object of a list response carries the four
        pagination fields `limit`, `offset`, `total_count`, and `has_more`".

        Design: Corner/entities/registrations_list_pagination_envelope
        """
        ev, r1, r2 = self._setup_two_registrations(api)
        page1, meta1 = validate_paginated(api.list_registrations(
            ORG, params={"event_id": ev["id"], "limit": 1, "offset": 0}))
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(api.list_registrations(
            ORG, params={"event_id": ev["id"], "limit": 1, "offset": 1}))
        assert len(page2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False
        ids = {page1[0]["id"], page2[0]["id"]}
        assert ids == {r1["id"], r2["id"]}, "pages must partition the result set"

    def test_registrations_filter_pagination_interaction(self, api):
        """PRD §3.2: "Registrations may be listed filtered by `event_id`,
        `registrant_id`, `vehicle_id`, `class_id`, `assigned_zone_id`, or
        `status`". PRD §2.3: "The `meta` object of a list response carries the
        four pagination fields `limit`, `offset`, `total_count`, and `has_more`".

        Design: Corner/endpoints/registrations_filter_pagination_interaction
        """
        ev, cls, zone = create_open_event()
        reg = get_success_data(api.create_registrant(
            {"full_name": "FP", "email": "fp@example.com"}, ORG))
        vehs = [
            get_success_data(api.create_vehicle(reg["id"], p, ORG))
            for p in [
                {"year": 1970, "make": "Ford", "model": "Mustang"},
                {"year": 1971, "make": "Chevrolet", "model": "Chevelle"},
                {"year": 1972, "make": "Pontiac", "model": "GTO"},
            ]
        ]
        r1 = create_paid_registration(ev["id"], reg["id"], vehs[0]["id"], cls["id"])
        r2 = create_paid_registration(ev["id"], reg["id"], vehs[1]["id"], cls["id"])
        r3 = create_registration(ev["id"], reg["id"], vehs[2]["id"], cls["id"])
        page, meta = validate_paginated(api.list_registrations(
            ORG, params={"event_id": ev["id"], "status": "CONFIRMED", "limit": 1, "offset": 0}))
        assert len(page) == 1
        assert meta["total_count"] == 2, "total_count reflects the filtered set"
        assert meta["has_more"] is True
        assert page[0]["id"] != r3["id"], "PENDING_PAYMENT registration must be filtered out"
        assert page[0]["status"] == "CONFIRMED"


class TestNotFound:
    def test_registration_get_not_found_returns_404(self, api):
        """PRD §2.9: "the first path identifier that does not resolve to an
        existing resource fails the request with `ERR_NOT_FOUND` (HTTP 404)".

        Design: Corner/entities/registration_get_not_found_returns_404
        """
        resp = api.get_registration(MISSING_UUID, ORG)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        resp2 = api.list_classes(MISSING_UUID, ORG)
        validate_error(resp2, ApiErrorId.ERR_NOT_FOUND)


class TestRegistrationEligibility:
    def test_duplicate_vehicle_registration_rejected(self, api):
        """PRD §3.2: "The same vehicle may hold only one non-terminal registration
        per event — a second create while the first is still alive in
        `PENDING_PAYMENT`, `CONFIRMED`, or `CHECKED_IN` is rejected with
        `ERR_DUPLICATE_REGISTRATION`."

        Design: Corner/validations/duplicate_vehicle_registration_rejected
        """
        # PRD §3.1 restricts class creation to DRAFT/PUBLISHED: build the second
        # class before the event is opened.
        ev, cls, zone = create_event_with_class_and_zone(
            class_overrides={"code": "C1", "min_year": 1950, "max_year": 1975,
                             "judging_mode": "JUDGED"})
        cls2 = get_success_data(api.create_class(
            ev["id"], create_class_payload(code="C2", min_year=1950, max_year=1975,
                                           prereg_fee_cents=2500, day_of_fee_cents=4000), ORG))
        get_success_data(api.publish_event(ev["id"], ORG))
        ev = get_success_data(api.open_registration(ev["id"], ORG))
        reg, veh = create_registrant_with_vehicle(name="DP", email="dp@example.com")
        create_registration(ev["id"], reg["id"], veh["id"], cls["id"])
        resp = api.create_registration(
            {"event_id": ev["id"], "registrant_id": reg["id"],
             "vehicle_id": veh["id"], "class_id": cls2["id"]}, DESK)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REGISTRATION)

    def test_vehicle_year_ineligible_rejected(self, api):
        """PRD §3.1: "an eligible model-year band from `min_year` through
        `max_year` with both ends inclusive". PRD §3.2: "The vehicle's `year` must
        fall inside the class's `min_year`-to-`max_year` band, else
        `ERR_VEHICLE_CLASS_INELIGIBLE`."

        Design: Corner/validations/vehicle_year_ineligible_rejected
        """
        ev, cls, zone = create_open_event(
            class_overrides={"code": "OLD", "min_year": 1950, "max_year": 1975,
                             "judging_mode": "JUDGED"})
        reg = get_success_data(api.create_registrant(
            {"full_name": "YR", "email": "yr@example.com"}, ORG))
        too_new = get_success_data(api.create_vehicle(
            reg["id"], {"year": 1980, "make": "DeLorean", "model": "DMC-12"}, ORG))
        boundary = get_success_data(api.create_vehicle(
            reg["id"], {"year": 1975, "make": "Chevrolet", "model": "Caprice"}, ORG))
        resp = api.create_registration(
            {"event_id": ev["id"], "registrant_id": reg["id"],
             "vehicle_id": too_new["id"], "class_id": cls["id"]}, DESK)
        validate_error(resp, ApiErrorId.ERR_VEHICLE_CLASS_INELIGIBLE)
        ok = validate_success(api.create_registration(
            {"event_id": ev["id"], "registrant_id": reg["id"],
             "vehicle_id": boundary["id"], "class_id": cls["id"]}, DESK), expected_status=201)
        assert ok["status"] == "PENDING_PAYMENT"

    def test_invalid_class_config_returns_400(self, api):
        """PRD §3.1: "a `min_year` greater than `max_year` is malformed and
        rejected with `ERR_VALIDATION`". PRD §2.9: "required fields present, enum
        values in range, numbers in range, a score sheet's `criteria_scores`
        holding exactly the five known criteria with integer points from 0 to 10,
        and class codes unique within the event: violations carry
        `ERR_VALIDATION`".

        Design: Corner/errors/invalid_class_config_returns_400
        """
        ev, cls, zone = create_open_event()
        bad_enum = api.create_class(ev["id"], create_class_payload(
            code="BAD1", judging_mode="RANKED"), ORG)
        validate_error(bad_enum, ApiErrorId.ERR_VALIDATION)
        bad_range = api.create_class(ev["id"], create_class_payload(
            code="BAD2", min_year=1990, max_year=1980), ORG)
        validate_error(bad_range, ApiErrorId.ERR_VALIDATION)
        classes = get_success_data(api.list_classes(ev["id"], ORG))
        assert all(c["code"] not in ("BAD1", "BAD2") for c in classes)
