"""Booking-creation validation gates (PRD §3.6 creation chain, §2.9)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    TEST_USERS, create_booking_payload, create_downtime_event_payload,
    make_researcher_headers, make_external_client_headers,
    setup_canonical_stack, create_user, create_instrument, create_grant,
    enroll_and_certify, open_fiscal_year, create_effective_rate_set,
    create_approved_booking, create_booking_request, set_clock,
)

ADMIN = TEST_USERS["admin_headers"]
STAFF = TEST_USERS["staff_headers"]
FINANCE = TEST_USERS["finance_headers"]


def _researcher(stack):
    return make_researcher_headers(stack["u1"]["id"])


class TestBookingRequestShape:
    def test_booking_create_with_computed_field_in_input_yields_400(self, api):
        """PRD §2.9: "Field formats (`ERR_INVALID_REQUEST`): required fields
        present, enums valid, `end_at` after `start_at`, positive amounts where
        required, email format; unknown or system/computed-sourced fields in
        request bodies are rejected here as malformed."

        Design: Corner/entities/booking_create_with_computed_field_in_input_yields_400
        """
        stack = setup_canonical_stack()
        payload = create_booking_payload(
            stack["u1"]["id"], stack["i1"]["id"], grant_id=stack["g1"]["id"],
        )
        payload["estimated_charge_cents"] = 1
        res = api.create_booking(payload, _researcher(stack))
        validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)

    def test_booking_start_in_past(self, api):
        """PRD §3.6: "`start_at` must be strictly in the future
        (`ERR_BOOKING_IN_PAST`)".

        Design: Corner/validations/booking_start_in_past
        """
        stack = setup_canonical_stack()
        set_clock("2026-09-01T10:00:00Z")
        res = api.create_booking(
            create_booking_payload(
                stack["u1"]["id"], stack["i1"]["id"], grant_id=stack["g1"]["id"],
                start_at="2026-09-01T09:00:00Z", end_at="2026-09-01T10:30:00Z",
            ),
            _researcher(stack),
        )
        validate_error(res, "ERR_BOOKING_IN_PAST", expected_status=422)

    def test_booking_duration_out_of_range_both_ends(self, api):
        """PRD §3.6: "the duration from `start_at` to `end_at` must lie within
        the instrument's minimum-to-maximum booking window
        (`ERR_DURATION_OUT_OF_RANGE`)".

        Design: Corner/validations/booking_duration_out_of_range_both_ends
        """
        stack = setup_canonical_stack()
        too_short = api.create_booking(
            create_booking_payload(
                stack["u1"]["id"], stack["i1"]["id"], grant_id=stack["g1"]["id"],
                start_at="2026-09-01T09:00:00Z", end_at="2026-09-01T09:10:00Z",
            ),
            _researcher(stack),
        )
        validate_error(too_short, "ERR_DURATION_OUT_OF_RANGE", expected_status=422)
        too_long = api.create_booking(
            create_booking_payload(
                stack["u1"]["id"], stack["i1"]["id"], grant_id=stack["g1"]["id"],
                start_at="2026-09-02T09:00:00Z", end_at="2026-09-02T19:00:00Z",
            ),
            _researcher(stack),
        )
        validate_error(too_long, "ERR_DURATION_OUT_OF_RANGE", expected_status=422)

    def test_duplicate_booking_same_start(self, api):
        """PRD §3.6: "no duplicate — same user, same instrument, same
        `start_at` among bookings in `REQUESTED`, `APPROVED`, or `IN_PROGRESS`
        — may exist (`ERR_DUPLICATE_BOOKING`)". PRD §3.2: "`REQUESTED` bookings
        never block other bookings; only `APPROVED` and `IN_PROGRESS` bookings
        participate in overlap."

        Design: Corner/validations/duplicate_booking_same_start
        """
        stack = setup_canonical_stack()
        create_booking_request(stack)  # stays REQUESTED; never blocks overlap
        res = api.create_booking(
            create_booking_payload(
                stack["u1"]["id"], stack["i1"]["id"], grant_id=stack["g1"]["id"],
                start_at="2026-09-01T09:00:00Z", end_at="2026-09-01T11:00:00Z",
            ),
            _researcher(stack),
        )
        validate_error(res, "ERR_DUPLICATE_BOOKING", expected_status=409)


class TestGrantGates:
    def test_grant_window_violation(self, api):
        """PRD §3.6: "the booking date must fall within the grant's chargeable
        window from `start_date` through `end_date` inclusive
        (`ERR_GRANT_WINDOW_VIOLATION`)".

        Design: Corner/validations/grant_window_violation
        """
        stack = setup_canonical_stack()  # grant 2026-01-01..2026-12-31
        res = api.create_booking(
            create_booking_payload(
                stack["u1"]["id"], stack["i1"]["id"], grant_id=stack["g1"]["id"],
                start_at="2027-01-05T09:00:00Z", end_at="2027-01-05T10:30:00Z",
            ),
            _researcher(stack),
        )
        validate_error(res, "ERR_GRANT_WINDOW_VIOLATION", expected_status=422)

    def test_grant_not_authorized_user(self, api):
        """PRD §3.6: "the booker must be the grant's PI or appear in
        `authorized_user_ids` (`ERR_GRANT_NOT_AUTHORIZED`)". PRD §3.4: "The PI
        is always implicitly authorized to charge the grant;
        `authorized_user_ids` extends that to additional users."

        Design: Corner/validations/grant_not_authorized_user
        """
        stack = setup_canonical_stack()
        u2 = create_user(affiliation="INTERNAL", full_name="Sam Soo",
                         email="r2@uni.edu")
        enroll_and_certify(u2["id"], stack["i1"]["id"])
        res = api.create_booking(
            create_booking_payload(
                u2["id"], stack["i1"]["id"], grant_id=stack["g1"]["id"],
            ),
            make_researcher_headers(u2["id"]),
        )
        validate_error(res, "ERR_GRANT_NOT_AUTHORIZED", expected_status=403)

    def test_grant_affiliation_mismatch_both_directions(self, api):
        """PRD §3.6: "grant affiliation must match: an `INTERNAL` user must
        supply a `grant_id`, an `EXTERNAL` user must not
        (`ERR_GRANT_AFFILIATION_MISMATCH`)".

        Design: Corner/validations/grant_affiliation_mismatch_both_directions
        """
        stack = setup_canonical_stack()
        u3 = create_user(affiliation="EXTERNAL", full_name="Eve Ext",
                         email="eve@acme.com")
        enroll_and_certify(u3["id"], stack["i1"]["id"])

        internal_without_grant = api.create_booking(
            create_booking_payload(
                stack["u1"]["id"], stack["i1"]["id"],
            ),
            _researcher(stack),
        )
        validate_error(
            internal_without_grant, "ERR_GRANT_AFFILIATION_MISMATCH",
            expected_status=422,
        )

        external_with_grant = api.create_booking(
            create_booking_payload(
                u3["id"], stack["i1"]["id"], grant_id=stack["g1"]["id"],
                start_at="2026-09-03T09:00:00Z", end_at="2026-09-03T10:30:00Z",
            ),
            make_external_client_headers(u3["id"]),
        )
        validate_error(
            external_with_grant, "ERR_GRANT_AFFILIATION_MISMATCH",
            expected_status=422,
        )

    def test_closed_grant_blocks_new_bookings(self, api):
        """PRD §3.4: "Closing releases the remaining encumbrance in the sense
        that the grant's `APPROVED` bookings are *not* cancelled — but no new
        bookings may charge a `CLOSED` grant." PRD §3.6: "the grant must
        resolve `ACTIVE` (`ERR_GRANT_INACTIVE`)".

        Design: Corner/validations/closed_grant_blocks_new_bookings
        """
        stack = setup_canonical_stack()
        closed = validate_success(api.close_grant(stack["g1"]["id"], FINANCE), 200)
        assert closed["status"] == "CLOSED"
        res = api.create_booking(
            create_booking_payload(
                stack["u1"]["id"], stack["i1"]["id"], grant_id=stack["g1"]["id"],
            ),
            _researcher(stack),
        )
        validate_error(res, "ERR_GRANT_INACTIVE", expected_status=422)


class TestAvailabilityAndUserStateGates:
    def test_down_instrument_blocks_booking(self, api):
        """PRD §3.2: "The flips to `DOWN` and `MAINTENANCE` are system-driven:
        confirming a downtime event of kind `UNSCHEDULED_FAILURE` on an
        instrument flips it to `DOWN`, and confirming one of kind
        `PREVENTIVE_MAINTENANCE` or `CALIBRATION` flips it to `MAINTENANCE` —
        but only when the event window contains the current logical time."
        PRD §3.6: "the instrument must be `AVAILABLE`
        (`ERR_INSTRUMENT_UNAVAILABLE`)".

        Design: Corner/validations/down_instrument_blocks_booking
        """
        stack = setup_canonical_stack()
        set_clock("2026-09-01T08:30:00Z")
        dt1 = validate_success(
            api.create_downtime_event(
                create_downtime_event_payload(stack["i1"]["id"]), STAFF
            ),
            201,
        )
        validate_success(api.confirm_downtime_event(dt1["id"], STAFF), 200)
        instrument = validate_success(api.get_instrument(stack["i1"]["id"], ADMIN), 200)
        assert instrument["status"] == "DOWN"

        res = api.create_booking(
            create_booking_payload(
                stack["u1"]["id"], stack["i1"]["id"], grant_id=stack["g1"]["id"],
                start_at="2026-09-05T09:00:00Z", end_at="2026-09-05T10:30:00Z",
            ),
            _researcher(stack),
        )
        validate_error(res, "ERR_INSTRUMENT_UNAVAILABLE", expected_status=409)

    def test_suspended_user_blocks_booking(self, api):
        """PRD §3.6: "the user must be `ACTIVE` (`ERR_USER_SUSPENDED`)".

        Design: Corner/validations/suspended_user_blocks_booking
        """
        stack = setup_canonical_stack()
        validate_success(api.suspend_user(stack["u1"]["id"], ADMIN), 200)
        res = api.create_booking(
            create_booking_payload(
                stack["u1"]["id"], stack["i1"]["id"], grant_id=stack["g1"]["id"],
            ),
            _researcher(stack),
        )
        validate_error(res, "ERR_USER_SUSPENDED", expected_status=403)

    def test_training_expiring_before_session_end(self, api):
        """PRD §3.3: "When a certified record exists, its `expires_at` must be
        strictly after the booking's `end_at` — the certification must cover
        the entire session — otherwise the request fails with
        `ERR_TRAINING_EXPIRED`."

        Design: Corner/validations/training_expiring_before_session_end
        """
        # Grant window spans into 2027 so only the training-currency gate fires.
        stack = setup_canonical_stack(grant_end="2027-12-31")
        res = api.create_booking(
            create_booking_payload(
                stack["u1"]["id"], stack["i1"]["id"], grant_id=stack["g1"]["id"],
                start_at="2027-09-03T09:00:00Z", end_at="2027-09-03T10:30:00Z",
            ),
            _researcher(stack),
        )
        # Certified at the 2026-08-01 clock default -> expires 2027-08-01,
        # which is not strictly after the 2027-09-03 session end.
        validate_error(res, "ERR_TRAINING_EXPIRED", expected_status=422)

    def test_priority_booking_without_award(self, api):
        """PRD §3.6: "A booking may carry `priority` `PRIORITY` only when the
        booker holds an `ACTIVE` `SubsidyAward` with `conveys_priority` true;
        `EXTERNAL` users are never eligible, and any other shortfall is
        `ERR_PRIORITY_NOT_AVAILABLE`."

        Design: Corner/validations/priority_booking_without_award
        """
        stack = setup_canonical_stack()
        u3 = create_user(affiliation="EXTERNAL", full_name="Eve Ext",
                         email="eve@acme.com")
        enroll_and_certify(u3["id"], stack["i1"]["id"])

        internal_no_award = api.create_booking(
            create_booking_payload(
                stack["u1"]["id"], stack["i1"]["id"], grant_id=stack["g1"]["id"],
                priority="PRIORITY",
            ),
            _researcher(stack),
        )
        validate_error(internal_no_award, "ERR_PRIORITY_NOT_AVAILABLE",
                       expected_status=422)

        external_priority = api.create_booking(
            create_booking_payload(
                u3["id"], stack["i1"]["id"], priority="PRIORITY",
                start_at="2026-09-02T09:00:00Z", end_at="2026-09-02T10:30:00Z",
            ),
            make_external_client_headers(u3["id"]),
        )
        validate_error(external_priority, "ERR_PRIORITY_NOT_AVAILABLE",
                       expected_status=422)
