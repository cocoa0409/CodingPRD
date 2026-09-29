"""Writes that succeed or fail purely on the status of a neighbouring entity."""

from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    assert_two_decimals,
    factories,
    fixtures,
    validate_error,
    validate_success,
)


class TestPacketDependsOnGoverningAssessmentStatus:
    def test_a_voided_assessment_cannot_govern_a_new_packet(self, client, roster):
        """The field is fine, the officer is fine; the evidence is what is stale.

        "The governing assessment must belong to the same field, must have
        `assessment_type` `IMPACT_ATTENUATION`, must still be `RECORDED`, and must
        have a `result` that is not `FAIL` — an `ADVISORY` reading is acceptable
        evidence at packet-opening time, a `FAIL` is not."

        "Any breach is refused with `ERR_GOVERNING_ASSESSMENT_NOT_CURRENT`, and a
        retired field is refused with `ERR_FIELD_RETIRED`."

        "When the voided assessment was an `IMPACT_ATTENUATION`,
        `latest_gmax_mean_value` does not simply go null: it **falls back** to the
        `gmax_mean_value` of the next most recent still-`RECORDED` impact assessment
        on the field, chosen by `assessed_at_utc` descending and then `created_at`
        descending, and becomes null only when no such assessment remains."

        "The safety component depends on the latest impact test: when
        `latest_gmax_mean_value` is null it takes the no-data value of 50.00 exactly,
        and otherwise it is the distance from the mandatory g-max limit of 200.0 down
        to the measured mean, divided by the distance from that mandatory limit down
        to an ideal value of 90.0, expressed as a percentage, clamped to lie between
        0.00 and 100.00, and rounded half up to two decimals."

        Design: Difficulty/cross_entity_state_dependency/packet_create_requires_governing_assessment_still_recorded
        """
        field = fixtures.register_grass_practice_3(client, roster)
        assessment = fixtures.record_impact_test(
            client, roster, field["id"], [120.0, 120.0, 120.0]
        )
        assert assessment["result"] == "PASS"
        assert (
            fixtures.read_field(client, roster, field["id"])["play_status"] == "OPEN"
        ), "a passing test opens no order"

        voided = fixtures.void_assessment(
            client, roster, assessment["id"], void_reason="CALIBRATION_DEFECT"
        )
        assert voided["status"] == "VOIDED"
        assert voided["void_reason"] == "CALIBRATION_DEFECT"
        # The verdict itself never changed; only the record's standing did.
        assert voided["result"] == "PASS"

        # A deliberately fresh token, so the refusal cannot be about concurrency.
        current = fixtures.read_field(client, roster, field["id"])
        assert current.get("latest_gmax_mean_value") is None
        # Wear 100.00 x 0.50 + age 91.67 x 0.20 + the no-data safety value
        # 50.00 x 0.30.
        assert_two_decimals(
            current["condition_index_agronomic"],
            83.33,
            "Field.condition_index_agronomic",
        )

        error = validate_error(
            client.create_certification_packet(
                factories.make_certification_packet_payload(
                    field_id=field["id"],
                    governing_assessment_id=assessment["id"],
                    competition_season_label="2026-FALL",
                    expected_field_version=current["version"],
                ),
                roster.cert_officer_headers,
            ),
            ApiErrorId.GOVERNING_ASSESSMENT_NOT_CURRENT,
            422,
        )
        assert error["error_id"] != ApiErrorId.STALE_FIELD_VERSION

        after = fixtures.read_field(client, roster, field["id"])
        assert after["play_status"] == "OPEN"
        assert after["open_certification_packet_count"] == 0, "no packet row was created"
        assert after["certification_status"] == "NOT_CERTIFIED"

    def test_the_dependency_is_re_read_at_submission_and_runs_both_ways(
        self, client, roster
    ):
        """A packet may open on live evidence, then lose it, then pin it in place.

        "The submitting officer's `submitted_by_staff_member_id` is recorded,
        `submitted_at_utc` is stamped from the logical clock, the governing assessment
        is re-checked against the same currency rule and refused with
        `ERR_GOVERNING_ASSESSMENT_NOT_CURRENT` if it has since been superseded or
        voided, and the field must not be retired."

        "Nor may an assessment be pulled out from under live certification paperwork
        — if any certification packet whose `status` is `SUBMITTED` or `APPROVED`
        names this assessment as its `governing_assessment_id`, the void is refused
        with `ERR_ASSESSMENT_IN_USE`."

        "The packet starts in `DRAFT` with `documentation_completeness_score` and
        `condition_index_certification` both null, `submitted_by_staff_member_id`,
        `decided_by_staff_member_id`, `submitted_at_utc`, `decided_at_utc`,
        `certified_until_utc` and `decision_notes` all null, and `return_count` at 0."

        Design: Difficulty/cross_entity_state_dependency/packet_create_requires_governing_assessment_still_recorded
        """
        built = fixtures.build_certifiable_synthetic_field(client, roster)
        field = built["field"]
        packet = fixtures.open_packet(
            client,
            roster,
            field["id"],
            built["impact"]["id"],
            field["version"],
            competition_season_label="2026-FALL",
        )
        assert packet["status"] == "DRAFT"
        assert packet.get("documentation_completeness_score") is None

        # A `DRAFT` packet is not live paperwork, so the void is permitted.
        assert (
            fixtures.void_assessment(client, roster, built["impact"]["id"])["status"]
            == "VOIDED"
        )

        validate_error(
            client.submit_certification_packet(
                packet["id"],
                factories.make_packet_submit_payload(roster.id_of("cert_officer")),
                roster.cert_officer_headers,
            ),
            ApiErrorId.GOVERNING_ASSESSMENT_NOT_CURRENT,
            422,
        )
        stalled = fixtures.read_packet(client, roster, packet["id"])
        assert stalled["status"] == "DRAFT"
        assert stalled.get("submitted_by_staff_member_id") is None
        assert stalled.get("submitted_at_utc") is None
        assert (
            fixtures.read_field(client, roster, field["id"])["certification_status"]
            == "NOT_CERTIFIED"
        )

        # Fresh evidence, a fresh packet, and now the dependency points the other way.
        replacement = fixtures.record_impact_test(
            client, roster, field["id"], [120.0, 120.0, 120.0]
        )
        assert replacement["status"] == "RECORDED"
        reread = fixtures.read_field(client, roster, field["id"])
        second = fixtures.open_packet(
            client,
            roster,
            field["id"],
            replacement["id"],
            reread["version"],
            competition_season_label="2026-FALL-REISSUE",
        )
        submitted = fixtures.submit_packet(client, roster, second["id"])
        assert submitted["status"] == "SUBMITTED"

        validate_error(
            client.void_safety_assessment(
                replacement["id"],
                factories.make_void_payload("CALIBRATION_DEFECT"),
                roster.headers_of("inspector"),
            ),
            ApiErrorId.ASSESSMENT_IN_USE,
            409,
        )
        assert (
            fixtures.read_assessment(client, roster, replacement["id"])["status"]
            == "RECORDED"
        )


class TestTournamentConfirmationDependsOnCertification:
    def _scheduled_tournament(self, client, roster, field_id):
        """A full-day tournament fixture on 5 August, five hundred expected."""
        booking = fixtures.request_booking(
            client,
            roster,
            field_id,
            activity_type="TOURNAMENT",
            window_start_utc="2026-08-05T09:00:00Z",
            window_end_utc="2026-08-05T17:00:00Z",
            expected_participant_count=500,
        )
        assert booking["status"] == "SCHEDULED", (
            "the certification dependency is not consulted at creation"
        )
        return booking

    def test_an_uncertified_sanctioned_field_refuses_the_confirmation(
        self, client, roster
    ):
        """Creation reads the posture axis; confirmation reads the other axis too.

        "An `OPEN` field accepts all four of `PRACTICE`, `GAME`, `TOURNAMENT` and
        `COMMUNITY`."

        "A third gate applies only here and not at request time: when the
        `activity_type` is `TOURNAMENT` **and** the field's `sanctioned_level` is
        anything other than `NONE`, the field's `certification_status` must be
        exactly `CERTIFIED`, and a field that is `NOT_CERTIFIED`, `PENDING_REVIEW` or
        `EXPIRED` is refused with `ERR_FIELD_NOT_CERTIFIED`."

        "The booking must be `SCHEDULED` — anything else is refused with
        `ERR_BOOKING_NOT_SCHEDULED`."

        Design: Difficulty/cross_entity_state_dependency/tournament_confirmation_requires_field_certification_status
        """
        field = fixtures.register_synthetic_stadium_1(client, roster)
        assert field["sanctioned_level"] == "REGIONAL"
        assert field["certification_status"] == "NOT_CERTIFIED"
        assert field.get("certified_until_utc") is None
        assert field["play_status"] == "OPEN"

        booking = self._scheduled_tournament(client, roster, field["id"])

        error = validate_error(
            client.confirm_usage_booking(booking["id"], roster.coordinator_headers),
            ApiErrorId.FIELD_NOT_CERTIFIED,
            422,
        )
        # The posture axis was never the problem.
        assert error["error_id"] != ApiErrorId.FIELD_NOT_PLAYABLE

        held = fixtures.read_booking(client, roster, booking["id"])
        assert held["status"] == "SCHEDULED"
        assert held.get("confirmed_at_utc") is None

        after = fixtures.read_field(client, roster, field["id"])
        assert after["certification_status"] == "NOT_CERTIFIED"
        assert after.get("certified_until_utc") is None
        assert after["play_status"] == "OPEN"

        # A gentler class on the same open field confirms without consulting the
        # certification axis at all.
        practice = fixtures.request_booking(
            client,
            roster,
            field["id"],
            activity_type="PRACTICE",
            window_start_utc="2026-08-06T09:00:00Z",
            window_end_utc="2026-08-06T17:00:00Z",
            expected_participant_count=500,
        )
        assert (
            fixtures.confirm_booking(client, roster, practice["id"])["status"]
            == "CONFIRMED"
        )

    def test_an_approved_packet_or_an_unsanctioned_field_lets_the_tournament_through(
        self, client, full_roster
    ):
        """Two independent ways to satisfy one dependency, and both are documented.

        "The field itself goes `PENDING_REVIEW → CERTIFIED` — a transition that
        requires the newly approved packet's `certified_until_utc` to be strictly
        later than the current instant — `Field.certified_until_utc` is set from that
        packet, `Field.open_certification_packet_count` decrements by 1, and
        `Field.version` increments by 1."

        "From this moment `TOURNAMENT` fixtures on the field may be confirmed."

        "A tournament on an unsanctioned field — `sanctioned_level` of `NONE` — needs
        no certification."

        Design: Difficulty/cross_entity_state_dependency/tournament_confirmation_requires_field_certification_status
        """
        built = fixtures.build_certifiable_synthetic_field(client, full_roster)
        field = built["field"]
        booking = self._scheduled_tournament(client, full_roster, field["id"])

        packet = fixtures.open_packet(
            client,
            full_roster,
            field["id"],
            built["impact"]["id"],
            field["version"],
            competition_season_label="2026-FALL",
        )
        submitted = fixtures.submit_packet(client, full_roster, packet["id"])
        # Every documentary component is in place on a 51.0 mm surface.
        assert_two_decimals(
            submitted["documentation_completeness_score"],
            100.00,
            "documentation_completeness_score",
        )
        pending = fixtures.read_field(client, full_roster, field["id"])
        assert pending["certification_status"] == "PENDING_REVIEW"
        # `PENDING_REVIEW` is not `CERTIFIED`, so the gate is still shut.
        validate_error(
            client.confirm_usage_booking(
                booking["id"], full_roster.coordinator_headers
            ),
            ApiErrorId.FIELD_NOT_CERTIFIED,
            422,
        )

        approved = fixtures.decide_packet(
            client, full_roster, packet["id"], decision="APPROVE"
        )
        assert approved["status"] == "APPROVED"
        certified = fixtures.read_field(client, full_roster, field["id"])
        assert certified["certification_status"] == "CERTIFIED"
        assert_instant_equals(
            certified["certified_until_utc"],
            "2027-08-01T00:00:00Z",
            "Field.certified_until_utc",
        )
        assert certified["open_certification_packet_count"] == 0

        confirmed = fixtures.confirm_booking(client, full_roster, booking["id"])
        assert confirmed["status"] == "CONFIRMED"

        # The other route through the gate: nobody sanctions this field, so nobody
        # asks it for a certificate.
        unsanctioned = fixtures.register_grass_main_1(
            client, full_roster, name="Grass Practice 9", sanctioned_level="NONE"
        )
        assert unsanctioned["certification_status"] == "NOT_CERTIFIED"
        loose_tournament = validate_success(
            client.create_usage_booking(
                factories.make_usage_booking_payload(
                    field_id=unsanctioned["id"],
                    requested_by_staff_member_id=full_roster.id_of("coordinator"),
                    activity_type="TOURNAMENT",
                    window_start_utc="2026-08-05T09:00:00Z",
                    window_end_utc="2026-08-05T17:00:00Z",
                    expected_participant_count=500,
                ),
                full_roster.coordinator_headers,
            ),
            201,
        )
        assert (
            fixtures.confirm_booking(client, full_roster, loose_tournament["id"])[
                "status"
            ]
            == "CONFIRMED"
        )
