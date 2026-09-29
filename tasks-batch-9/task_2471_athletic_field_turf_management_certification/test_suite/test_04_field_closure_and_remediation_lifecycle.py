"""Booking confirmation, administrative closure and the remediation loop."""

from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    assert_remediation_order,
    assert_two_decimals,
    assert_version,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import DEFAULT_CLOCK_UTC


class TestBookingConfirmationIsNotIdempotent:
    def test_second_confirm_of_a_confirmed_booking_is_rejected(self, client, roster):
        """Repeating a successful transition is an error, not a no-op.

        "The booking must be `SCHEDULED` — anything else is refused with
        `ERR_BOOKING_NOT_SCHEDULED`."

        "Only a `SafetyInspector` may void, and only an assessment whose `status`
        is still `RECORDED`: an assessment already `SUPERSEDED` or already
        `VOIDED` is refused with `ERR_ASSESSMENT_NOT_RECORDED`."

        Design: Corner/state_machines/second_confirm_of_a_confirmed_booking_is_rejected
        """
        field = fixtures.register_grass_practice_3(client, roster)
        booking = fixtures.request_booking(
            client,
            roster,
            field["id"],
            activity_type="PRACTICE",
            window_start_utc="2026-08-05T19:00:00Z",
            window_end_utc="2026-08-05T21:00:00Z",
            expected_participant_count=30,
        )
        confirmed = fixtures.confirm_booking(client, roster, booking["id"])
        assert confirmed["status"] == "CONFIRMED"

        validate_error(
            client.confirm_usage_booking(booking["id"], roster.coordinator_headers),
            ApiErrorId.BOOKING_NOT_SCHEDULED,
            409,
        )

        after = fixtures.read_booking(client, roster, booking["id"])
        assert after["status"] == "CONFIRMED"
        assert_instant_equals(
            after["confirmed_at_utc"],
            DEFAULT_CLOCK_UTC,
            "UsageBooking.confirmed_at_utc",
        )

        bookings, meta = validate_paginated(
            client.list_usage_bookings(
                roster.coordinator_headers,
                params={"limit": 100, "field_id": field["id"]},
            )
        )
        assert meta["total_count"] == 1, "no duplicate booking was minted"
        assert bookings[0]["id"] == booking["id"]

        # The same non-idempotence governs voiding an assessment.
        assessment = fixtures.record_inspection(
            client, roster, field["id"], assessment_type="STRIPING_LAYOUT"
        )
        fixtures.void_assessment(client, roster, assessment["id"])
        validate_error(
            client.void_safety_assessment(
                assessment["id"],
                factories.make_void_payload("CALIBRATION_DEFECT"),
                roster.inspector_headers,
            ),
            ApiErrorId.ASSESSMENT_NOT_RECORDED,
            409,
        )


class TestAdministrativeClosure:
    def test_reopen_after_administrative_closure_restores_open_posture(
        self, client, roster
    ):
        """Lifting a closure recomputes the posture from what actually remains.

        "A successful `REOPEN_ADMIN` sets `admin_closure_active` back to false,
        clears `admin_closure_reason_code` to null, recomputes the posture and
        increments `Field.version` by 1 — and where the posture lands depends on
        what else is outstanding. `CLOSED_ADMIN → OPEN` requires that
        `rest_debt_hours` is exactly 0.00 and `open_advisory_remediation_count` is
        zero"

        "A successful `CLOSE_ADMIN` sets `admin_closure_active` to true, records
        the supplied `reason_code` in `admin_closure_reason_code`, recomputes the
        posture and increments `Field.version` by 1."

        "A field whose `play_status` is `CLOSED_ADMIN`, `CLOSED_UNSAFE` or
        `RETIRED` accepts no allocation and the request is refused with
        `ERR_FIELD_NOT_PLAYABLE`"

        Design: Corner/state_machines/field_reopen_after_administrative_closure_restores_open_posture
        """
        field = fixtures.register_grass_practice_3(client, roster)
        assert_version(field, 1, "Field")

        closed = fixtures.close_field_administratively(
            client, roster, field["id"], reason_code="IRRIGATION_MAIN_BREAK"
        )
        assert closed["play_status"] == "CLOSED_ADMIN"
        assert closed["admin_closure_active"] is True
        assert closed["admin_closure_reason_code"] == "IRRIGATION_MAIN_BREAK"

        during = factories.make_usage_booking_payload(
            field_id=field["id"],
            requested_by_staff_member_id=roster.id_of("coordinator"),
            activity_type="PRACTICE",
            window_start_utc="2026-08-05T19:00:00Z",
            window_end_utc="2026-08-05T21:00:00Z",
            expected_participant_count=30,
        )
        validate_error(
            client.create_usage_booking(during, roster.coordinator_headers),
            ApiErrorId.FIELD_NOT_PLAYABLE,
            422,
        )

        reopened = fixtures.reopen_field_administratively(
            client, roster, field["id"], reason_code="REPAIR_COMPLETE"
        )
        assert reopened["play_status"] == "OPEN"
        assert reopened["admin_closure_active"] is False
        assert reopened.get("admin_closure_reason_code") is None
        # The registration, the closure and the reopen each bumped the token once.
        assert_version(reopened, 3, "Field")

        allowed = validate_success(
            client.create_usage_booking(during, roster.coordinator_headers), 201
        )
        assert allowed["status"] == "SCHEDULED"

    def test_closure_order_while_mandatory_remediation_open_is_rejected(
        self, client, roster
    ):
        """An administrative flag may not be laid over a safety finding.

        "Neither action may be layered on top of a safety problem: if the field's
        `open_mandatory_remediation_count` is anything other than zero, the
        closure order is refused with `ERR_UNSAFE_CLOSURE_IN_FORCE`, because the
        unsafe posture is the department's finding and an administrative flag must
        not be allowed to obscure or appear to resolve it."

        "lifting one requires that a closure *is* in force, so `REOPEN_ADMIN`
        against a field whose `admin_closure_active` is false is refused with
        `ERR_FIELD_NOT_CLOSED`."

        "When the last mandatory order on a field closes, by verification or by
        cancellation, the unsafe closure lifts — but where the posture lands
        depends on what remains. `CLOSED_UNSAFE → OPEN` requires that
        `admin_closure_active` is false, `rest_debt_hours` is exactly 0.00 and
        `open_advisory_remediation_count` is zero."

        Design: Corner/state_machines/reopen_while_mandatory_remediation_open_is_rejected
        """
        field = fixtures.register_grass_practice_3(client, roster)
        _assessment, order = fixtures.fail_field_unsafe(client, roster, field["id"])
        assert_remediation_order(order)
        assert order["severity"] == "MANDATORY"

        unsafe = fixtures.read_field(client, roster, field["id"])
        assert unsafe["play_status"] == "CLOSED_UNSAFE"
        assert unsafe["open_mandatory_remediation_count"] == 1
        # The closure is a projection of the finding, not an administrative flag.
        assert unsafe["admin_closure_active"] is False

        validate_error(
            client.place_closure_order(
                field["id"],
                factories.make_closure_order_payload(
                    action="CLOSE_ADMIN", reason_code="MANAGEMENT_OVERRIDE"
                ),
                roster.director_headers,
            ),
            ApiErrorId.UNSAFE_CLOSURE_IN_FORCE,
            409,
        )
        # There is no administrative closure to lift either.
        validate_error(
            client.place_closure_order(
                field["id"],
                factories.make_closure_order_payload(
                    action="REOPEN_ADMIN", reason_code="MANAGEMENT_OVERRIDE"
                ),
                roster.director_headers,
            ),
            ApiErrorId.FIELD_NOT_CLOSED,
            409,
        )

        still_unsafe = fixtures.read_field(client, roster, field["id"])
        assert still_unsafe["play_status"] == "CLOSED_UNSAFE"
        assert still_unsafe["open_mandatory_remediation_count"] == 1
        assert still_unsafe["admin_closure_active"] is False

        # Closing the order is what lifts the posture; no reopen call is involved.
        fixtures.set_clock(client, roster, "2026-08-02T00:00:00Z")
        retest = fixtures.record_impact_test(
            client,
            roster,
            field["id"],
            [120.0, 120.0, 120.0],
            assessed_at_utc="2026-08-02T00:00:00Z",
        )
        fixtures.submit_order_verification(client, roster, order["id"], retest["id"])
        closed_order = fixtures.decide_order_verification(
            client, roster, order["id"], decision="ACCEPT"
        )
        assert closed_order["status"] == "CLOSED_VERIFIED"

        recovered = fixtures.read_field(client, roster, field["id"])
        assert recovered["play_status"] == "OPEN"
        assert recovered["open_mandatory_remediation_count"] == 0


class TestRemediationVerificationLoop:
    def test_order_returns_to_open_when_verification_is_rejected(self, client, roster):
        """A rejected re-test puts the order back where it started.

        "`REJECT` is the cycle in this state machine: it takes the order
        `VERIFICATION_SUBMITTED → OPEN`, increments `rejection_count` by 1, clears
        both `verification_assessment_id` and `submitted_by_staff_member_id` back
        to null so a different agronomist may try again, **retains**
        `remediation_notes` for audit, and leaves the posture unchanged. The loop
        `OPEN → VERIFICATION_SUBMITTED → OPEN` may repeat any number of times."

        "A permitted submission takes the order `OPEN → VERIFICATION_SUBMITTED`,
        records the three supplied values, and leaves the field's posture entirely
        alone — the order still counts toward its open-order counter, so a
        `CLOSED_UNSAFE` field stays closed while its verification is pending."

        "An accepted verification takes the order `VERIFICATION_SUBMITTED →
        CLOSED_VERIFIED`, stamps `closed_at_utc` from the logical clock,
        decrements whichever of `open_mandatory_remediation_count` or
        `open_advisory_remediation_count` this order was populating by 1,
        recomputes the posture, and increments `Field.version` by 1."

        Design: Corner/state_machines/remediation_order_returns_to_open_when_verification_is_rejected
        """
        field = fixtures.register_grass_practice_3(client, roster)
        _fail, order = fixtures.fail_field_unsafe(client, roster, field["id"])

        fixtures.set_clock(client, roster, "2026-08-02T00:00:00Z")
        retest = fixtures.record_impact_test(
            client,
            roster,
            field["id"],
            [120.0, 120.0, 120.0],
            assessed_at_utc="2026-08-02T00:00:00Z",
        )
        assert retest["result"] == "PASS"

        submitted = fixtures.submit_order_verification(
            client,
            roster,
            order["id"],
            retest["id"],
            remediation_notes="Base layer regraded and retested.",
        )
        assert submitted["status"] == "VERIFICATION_SUBMITTED"
        assert submitted["verification_assessment_id"] == retest["id"]
        assert submitted["submitted_by_staff_member_id"] == roster.id_of("agronomist")

        rejected = fixtures.decide_order_verification(
            client,
            roster,
            order["id"],
            decision="REJECT",
            decision_notes="Retest taken outside the remediated zone.",
        )
        # A state the order already occupied once before.
        assert rejected["status"] == "OPEN"
        assert rejected["rejection_count"] == 1
        assert rejected.get("verification_assessment_id") is None
        assert rejected.get("submitted_by_staff_member_id") is None
        assert rejected["remediation_notes"] == "Base layer regraded and retested."

        during_loop = fixtures.read_field(client, roster, field["id"])
        assert during_loop["open_mandatory_remediation_count"] == 1
        assert during_loop["play_status"] == "CLOSED_UNSAFE"

        resubmitted = fixtures.submit_order_verification(
            client, roster, order["id"], retest["id"]
        )
        assert resubmitted["status"] == "VERIFICATION_SUBMITTED"
        assert resubmitted["rejection_count"] == 1

        accepted = fixtures.decide_order_verification(
            client, roster, order["id"], decision="ACCEPT"
        )
        assert accepted["status"] == "CLOSED_VERIFIED"
        assert_instant_equals(
            accepted["closed_at_utc"],
            "2026-08-02T00:00:00Z",
            "RemediationOrder.closed_at_utc",
        )

        released = fixtures.read_field(client, roster, field["id"])
        assert released["open_mandatory_remediation_count"] == 0
        assert released["play_status"] == "OPEN"
        assert_two_decimals(released["rest_debt_hours"], 0.00, "Field.rest_debt_hours")
