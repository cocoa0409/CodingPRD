"""Reservation creation, amendment, and request-validation ordering."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_customer,
    create_catalog_item,
    create_catalog_item_payload,
    create_customer,
    create_customer_payload,
    create_hotel_partner,
    create_quoted_reservation,
    get_reservation,
    get_reservation_version,
    is_valid_uuid,
    make_customer_headers,
    setup_delivered_reservation,
    validate_error,
    validate_success,
)


class TestEntityCreation:
    def test_customer_creation_applies_defaults(self, api, anonymous_headers):
        """PRD 3.2: "New customers are `ACTIVE` with a `risk_score` of zero and
        both behavioral counters — `late_return_count` and
        `captured_damage_count` — at zero."
        PRD 2.4: "Every persisted resource has an `id` that is a server-minted
        UUID with no type prefix."

        Design: Corner/entities/customer_creation_applies_defaults
        """
        res = api.create_customer(
            create_customer_payload(
                full_name="Ada Lo", email="ada@example.com", phone="001"
            ),
            anonymous_headers,
        )
        customer = validate_success(res, 201)
        assert_customer(customer)
        assert customer["status"] == "ACTIVE"
        assert customer["risk_score"] == 0
        assert customer["late_return_count"] == 0
        assert customer["captured_damage_count"] == 0
        assert is_valid_uuid(customer["id"])

    def test_catalog_item_missing_required_field_rejected(self, api, ops_headers):
        """PRD 2.8: "Request shape — required fields present, types valid, enum
        members from the declared sets, and the uniqueness rules on customer
        `email`, unit `serial_number`, and plan `code`, else
        `ERR_INVALID_REQUEST` (400)."
        PRD 3.1: "each CatalogItem is created with a `name` (for example,
        "Deluxe Crib"), a `category` of `CRIB`, `STROLLER`, or `CARSEAT`, a
        `daily_rate_cents` and a `deposit_amount_cents` that must both be
        greater than zero"

        Omitting the required daily_rate_cents is rejected ERR_INVALID_REQUEST.

        Design: Corner/entities/catalog_item_missing_required_field_rejected
        """
        payload = create_catalog_item_payload()
        del payload["daily_rate_cents"]
        res = api.create_catalog_item(payload, ops_headers)
        validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)

    def test_reservation_not_found_returns_404(self, api, ops_headers):
        """PRD 2.8: "A missing reference yields the specific not-found error
        for that entity: `ERR_CUSTOMER_NOT_FOUND`, `ERR_CATALOG_ITEM_NOT_FOUND`,
        ... `ERR_RESERVATION_NOT_FOUND`, ... (all 404)."

        Design: Corner/entities/reservation_not_found_returns_404
        """
        res = api.get_reservation(NON_EXISTENT_UUID, ops_headers)
        validate_error(res, "ERR_RESERVATION_NOT_FOUND", expected_status=404)

    def test_reservation_line_fk_integrity_rejected(self, api):
        """PRD 2.8: "every identifier the request references must exist,
        validated left-to-right: path identifiers first, in the order they
        appear in the URL, then foreign keys in the request body."

        A reservation line referencing a non-existent catalog item is rejected
        ERR_CATALOG_ITEM_NOT_FOUND (404).

        Design: Corner/entities/reservation_line_fk_integrity_rejected
        """
        customer = create_customer()
        res = api.create_reservation(
            {
                "delivery_address": "31 Poplar Rd",
                "zone_code": "Z1",
                "start_date": "2026-06-10",
                "end_date": "2026-06-13",
                "lines": [{"catalog_item_id": NON_EXISTENT_UUID}],
            },
            make_customer_headers(customer["id"]),
        )
        validate_error(res, "ERR_CATALOG_ITEM_NOT_FOUND", expected_status=404)


class TestReservationBirth:
    def test_reservation_initial_state_quoted(self, api):
        """PRD 3.3: "The reservation is born in the `QUOTED` state with
        `payment_status` `DEPOSIT_PENDING`, every line `PENDING`, and a
        provisional quote computed immediately."

        Design: Corner/state_machines/reservation_initial_state_quoted
        """
        customer = create_customer()
        catalog = create_catalog_item()
        reservation = create_quoted_reservation(
            customer["id"], lines=[{"catalog_item_id": catalog["id"]}]
        )
        assert reservation["status"] == "QUOTED"
        assert reservation["payment_status"] == "DEPOSIT_PENDING"


class TestRequestValidation:
    def test_invalid_date_range_end_not_after_start(self, api):
        """PRD 2.8: "Date and window sanity — `end_date` strictly after
        `start_date` on reservation creation, an amended or requested extension
        end strictly after the reservation's current `end_date`, and a stop's
        time window falling within the route's `route_date` with a start
        strictly before its end, else `ERR_INVALID_DATE_RANGE` (422)."

        end_date equal to start_date is rejected.

        Design: Corner/validations/invalid_date_range_end_not_after_start
        """
        customer = create_customer()
        catalog = create_catalog_item()
        res = api.create_reservation(
            {
                "delivery_address": "47 Nyssa Rd",
                "zone_code": "Z1",
                "start_date": "2026-06-10",
                "end_date": "2026-06-10",
                "lines": [{"catalog_item_id": catalog["id"]}],
            },
            make_customer_headers(customer["id"]),
        )
        validate_error(res, "ERR_INVALID_DATE_RANGE", expected_status=422)

    def test_zone_mismatch_partner_vs_reservation_rejected(self, api):
        """PRD 3.2: "When a reservation names a `hotel_partner_id`, the
        reservation's own `zone_code` must equal the partner's `zone_code`; a
        mismatch is rejected with `ERR_ZONE_MISMATCH`."

        Design: Corner/validations/zone_mismatch_partner_vs_reservation_rejected
        """
        customer = create_customer()
        partner = create_hotel_partner(zone_code="Z2", commission_pct=0.12)
        catalog = create_catalog_item()
        res = api.create_reservation(
            {
                "hotel_partner_id": partner["id"],
                "delivery_address": "Seaside Inn Lobby",
                "zone_code": "Z1",
                "start_date": "2026-06-10",
                "end_date": "2026-06-13",
                "lines": [{"catalog_item_id": catalog["id"]}],
            },
            make_customer_headers(customer["id"]),
        )
        validate_error(res, "ERR_ZONE_MISMATCH", expected_status=422)

    def test_plan_rate_out_of_range_rejected(self, api, ops_headers):
        """PRD 3.1: "For a `PERCENT_OF_RENTAL` plan, `rate_value` is a fraction
        greater than zero and at most 0.25, applied to the gear subtotal. A
        `rate_value` out of range for its model is rejected with
        `ERR_INVALID_PLAN_RATE`."

        rate_value 0.30 exceeds the (0, 0.25] bound for PERCENT_OF_RENTAL.

        Design: Corner/validations/plan_rate_out_of_range_rejected
        """
        res = api.create_insurance_plan(
            {
                "code": "TOO_HIGH",
                "pricing_model": "PERCENT_OF_RENTAL",
                "rate_value": 0.30,
                "deductible_cents": 500,
                "coverage_cap_cents": 10000,
                "covered_severities": ["MINOR"],
            },
            ops_headers,
        )
        validate_error(res, "ERR_INVALID_PLAN_RATE", expected_status=422)

    def test_amend_nonexistent_reservation_returns_not_found(self, api):
        """PRD 2.8: "When several checks could reject the same request, they
        are evaluated in a fixed order, and the first failing check determines
        the response."
        PRD 2.8: "every identifier the request references must exist, validated
        left-to-right: path identifiers first, in the order they appear in the
        URL, then foreign keys in the request body."

        Existence (check 3) precedes date sanity (check 5): amending a
        non-existent reservation with an invalid date range returns
        ERR_RESERVATION_NOT_FOUND, not ERR_INVALID_DATE_RANGE.

        Design: Corner/validations/amend_nonexistent_reservation_returns_not_found
        """
        customer = create_customer()
        catalog = create_catalog_item()
        real = create_quoted_reservation(
            customer["id"], lines=[{"catalog_item_id": catalog["id"]}]
        )
        res = api.amend_reservation_dates(
            NON_EXISTENT_UUID,
            {
                "start_date": "2026-06-12",
                "end_date": "2026-06-11",
                "expected_reservation_version": real["version"],
            },
            make_customer_headers(customer["id"]),
        )
        validate_error(res, "ERR_RESERVATION_NOT_FOUND", expected_status=404)


class TestOccAmend:
    def test_occ_amend_stale_version_returns_412(self, api):
        """PRD 2.7: "If the reservation's current `version` has advanced since
        that observation — because a prior amend succeeded, an extension
        approval bumped it, or any other write landed in between — the request
        is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD 3.3: "A successful amendment is a self-loop within `QUOTED`: the
        provisional quote is recomputed end to end — `quoted_total_cents`,
        `gear_subtotal_cents`, and every line's `line_charge_cents` — and the
        reservation's `version` increments by one."

        Two sequential amends carrying the same observed version: the first
        succeeds (version advances by exactly one), the second is rejected 412.

        Design: Corner/cross_cutting_layers/occ_amend_stale_version_returns_412
        """
        customer = create_customer()
        catalog = create_catalog_item()
        reservation = create_quoted_reservation(
            customer["id"], lines=[{"catalog_item_id": catalog["id"]}]
        )
        observed_version = reservation["version"]

        first = api.amend_reservation_dates(
            reservation["id"],
            {
                "start_date": "2026-06-11",
                "end_date": "2026-06-14",
                "expected_reservation_version": observed_version,
            },
            make_customer_headers(customer["id"]),
        )
        amended = validate_success(first, 200)
        assert amended["version"] == observed_version + 1, (
            "amend must increment the reservation version by exactly one"
        )
        assert amended["status"] == "QUOTED"

        second = api.amend_reservation_dates(
            reservation["id"],
            {
                "start_date": "2026-06-12",
                "end_date": "2026-06-15",
                "expected_reservation_version": observed_version,
            },
            make_customer_headers(customer["id"]),
        )
        validate_error(second, "ERR_STALE_VERSION", expected_status=412)


class TestAmendValidationPriority:
    def test_shape_violation_on_delivered_reservation_reports_date_range(
        self, api
    ):
        """PRD 2.8: "When several checks could reject the same request, they
        are evaluated in a fixed order, and the first failing check determines
        the response."
        PRD 3.3: "The new end must be strictly after the new start, else
        `ERR_INVALID_DATE_RANGE`; a stale version is rejected with
        `ERR_STALE_VERSION`."

        Date sanity (check 5) precedes state preconditions (check 6): an amend
        against a DELIVERED reservation whose payload has end_date before
        start_date surfaces ERR_INVALID_DATE_RANGE, not ERR_INVALID_STATE.

        Design: Difficulty/priority_pair_validation_conflict/request_shape_beats_state_on_amend
        """
        ctx = setup_delivered_reservation()
        reservation = ctx["reservation"]
        customer = ctx["customer"]
        version = get_reservation_version(reservation["id"])
        res = api.amend_reservation_dates(
            reservation["id"],
            {
                "start_date": "2026-06-12",
                "end_date": "2026-06-11",
                "expected_reservation_version": version,
            },
            make_customer_headers(customer["id"]),
        )
        validate_error(res, "ERR_INVALID_DATE_RANGE", expected_status=422)

    def test_shape_violation_leaves_delivered_reservation_untouched(self, api):
        """PRD 2.8: "Date and window sanity — `end_date` strictly after
        `start_date` on reservation creation, an amended or requested extension
        end strictly after the reservation's current `end_date`, and a stop's
        time window falling within the route's `route_date` with a start
        strictly before its end, else `ERR_INVALID_DATE_RANGE` (422)."

        The rejected amend is atomic: the DELIVERED reservation keeps its
        status, dates, and version.

        Design: Difficulty/priority_pair_validation_conflict/request_shape_beats_state_on_amend
        """
        ctx = setup_delivered_reservation()
        reservation = ctx["reservation"]
        customer = ctx["customer"]
        version_before = reservation["version"]
        res = api.amend_reservation_dates(
            reservation["id"],
            {
                "start_date": "2026-06-12",
                "end_date": "2026-06-11",
                "expected_reservation_version": version_before,
            },
            make_customer_headers(customer["id"]),
        )
        validate_error(res, "ERR_INVALID_DATE_RANGE", expected_status=422)
        after = get_reservation(reservation["id"])
        assert after["status"] == "DELIVERED"
        assert after["version"] == version_before
        assert after["start_date"] == reservation["start_date"]
        assert after["end_date"] == reservation["end_date"]
