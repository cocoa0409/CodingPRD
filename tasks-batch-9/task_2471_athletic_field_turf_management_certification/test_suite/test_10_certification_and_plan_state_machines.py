"""Two non-linear machines: a scoring cycle and a pair of independent axes."""

from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    assert_two_decimals,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
)


def _packet_at_one_third_programme(client, roster):
    """Submit a packet whose agronomic programme is one task in three complete.

    Returns the field id, the packet, and the second programme task so a caller
    can finish it between two submissions.
    """
    field = fixtures.register_synthetic_stadium_1(client, roster)
    impact = fixtures.record_impact_test(
        client, roster, field["id"], [120.0, 120.0, 120.0]
    )
    fixtures.record_inspection(
        client, roster, field["id"], assessment_type="STRIPING_LAYOUT"
    )
    fixtures.record_inspection(
        client, roster, field["id"], assessment_type="GOAL_ANCHORING"
    )

    grooming = fixtures.schedule_task(
        client,
        roster,
        field["id"],
        task_type="GROOMING",
        scheduled_start_utc="2026-08-01T06:00:00Z",
        scheduled_end_utc="2026-08-01T07:00:00Z",
        planned_for_certification_window=True,
    )
    infill = fixtures.schedule_task(
        client,
        roster,
        field["id"],
        task_type="INFILL_REDISTRIBUTION",
        scheduled_start_utc="2026-08-01T08:00:00Z",
        scheduled_end_utc="2026-08-01T09:00:00Z",
        planned_for_certification_window=True,
    )
    fixtures.schedule_task(
        client,
        roster,
        field["id"],
        task_type="SEAM_INSPECTION",
        scheduled_start_utc="2026-08-01T10:00:00Z",
        scheduled_end_utc="2026-08-01T11:00:00Z",
        planned_for_certification_window=True,
    )

    fixtures.set_clock(client, roster, "2026-08-02T00:00:00Z")
    fixtures.start_and_complete_task(
        client, roster, grooming["id"], "2026-08-02T00:00:00Z"
    )

    current = fixtures.read_field(client, roster, field["id"])
    packet = fixtures.open_packet(
        client,
        roster,
        field["id"],
        impact["id"],
        current["version"],
        competition_season_label="2026-FALL",
    )
    submitted = fixtures.submit_packet(client, roster, packet["id"])
    return field["id"], submitted, infill


class TestCertificationReturnResubmitCycle:
    def test_resubmission_rescores_the_packet_from_scratch(self, client, full_roster):
        """Re-entering `SUBMITTED` is not a replay; the score is computed again.

        "A return takes the packet `SUBMITTED → RETURNED`, increments
        `return_count` by 1, stamps `decided_at_utc` and `decision_notes`, and
        clears `submitted_by_staff_member_id` back to null so that a *different*
        officer may resubmit — which is how the segregation control survives the
        cycle."

        "`SUBMITTED → RETURNED → SUBMITTED` may repeat any number of times, and
        each pass re-evaluates both scores against the state of the world at that
        moment."

        "Second, `documentation_completeness_score` must be at least 90.00, and
        anything lower is refused with
        `ERR_CERTIFICATION_DOCUMENTATION_INCOMPLETE`."

        Design: Difficulty/non_linear_state_machine/certification_packet_return_resubmit_cycle_rescores_completeness
        """
        field_id, first, infill = _packet_at_one_third_programme(client, full_roster)
        assert first["status"] == "SUBMITTED"
        # One programme task in three: 30.00 + 6.67 + 15.00 + 15.00 + 6.67 + 10.00.
        assert_two_decimals(
            first["documentation_completeness_score"],
            83.34,
            "first documentation_completeness_score",
        )

        returned = fixtures.decide_packet(
            client,
            full_roster,
            first["id"],
            decision="RETURN",
            decision_notes="Programme evidence incomplete for the window.",
        )
        assert returned["status"] == "RETURNED"
        assert returned["return_count"] == 1
        assert returned.get("submitted_by_staff_member_id") is None

        after_return = fixtures.read_field(client, full_roster, field_id)
        assert after_return["certification_status"] == "NOT_CERTIFIED"

        # The world moves on between the two submissions.
        fixtures.set_clock(client, full_roster, "2026-08-03T00:00:00Z")
        fixtures.start_and_complete_task(
            client, full_roster, infill["id"], "2026-08-03T00:00:00Z"
        )

        second = fixtures.submit_packet(client, full_roster, first["id"])
        assert second["status"] == "SUBMITTED"
        # Two programme tasks in three now: the agronomic component is 13.33.
        assert_two_decimals(
            second["documentation_completeness_score"],
            90.00,
            "second documentation_completeness_score",
        )
        # Resubmitting does not reset the loop counter.
        assert second["return_count"] == 1

        after_resubmit = fixtures.read_field(client, full_roster, field_id)
        assert after_resubmit["certification_status"] == "PENDING_REVIEW"

        approved = fixtures.decide_packet(
            client, full_roster, first["id"], decision="APPROVE"
        )
        assert approved["status"] == "APPROVED"
        # 365 days on from the deciding instant.
        assert_instant_equals(
            approved["certified_until_utc"],
            "2027-08-03T00:00:00Z",
            "CertificationPacket.certified_until_utc",
        )
        certified = fixtures.read_field(client, full_roster, field_id)
        assert certified["certification_status"] == "CERTIFIED"
        assert_instant_equals(
            certified["certified_until_utc"],
            "2027-08-03T00:00:00Z",
            "Field.certified_until_utc",
        )

    def test_the_loop_may_repeat_and_each_state_guards_its_own_entry(
        self, client, full_roster
    ):
        """Only the two documented origins may submit, and only `SUBMITTED` decides.

        "Submission is permitted from `DRAFT` and from `RETURNED` alike — `DRAFT →
        SUBMITTED` and `RETURNED → SUBMITTED` — and a packet in any other status is
        refused with `ERR_PACKET_NOT_SUBMITTABLE`."

        "The packet must be `SUBMITTED`, or the decision is refused with
        `ERR_PACKET_NOT_SUBMITTED`."

        "Crucially, **both scores are recomputed from scratch at every submission**
        and never carried over from a previous one, because a resubmission is a
        fresh assertion about a world that has moved on."

        Design: Difficulty/non_linear_state_machine/certification_packet_return_resubmit_cycle_rescores_completeness
        """
        _field_id, first, _infill = _packet_at_one_third_programme(client, full_roster)
        assert first["submitted_by_staff_member_id"] == full_roster.id_of("cert_officer")

        # A packet already in `SUBMITTED` cannot re-enter it directly.
        validate_error(
            client.submit_certification_packet(
                first["id"],
                factories.make_packet_submit_payload(
                    full_roster.id_of("cert_officer")
                ),
                full_roster.cert_officer_headers,
            ),
            ApiErrorId.PACKET_NOT_SUBMITTABLE,
            409,
        )

        returned = fixtures.decide_packet(
            client,
            full_roster,
            first["id"],
            decision="RETURN",
            decision_notes="Programme evidence incomplete for the window.",
        )
        assert returned["return_count"] == 1

        # And a packet sitting in `RETURNED` cannot be decided.
        validate_error(
            client.decide_certification_packet(
                first["id"],
                factories.make_packet_decide_payload(
                    decision="APPROVE",
                    decided_by_staff_member_id=full_roster.id_of("cert_officer_two"),
                ),
                full_roster.headers_of("cert_officer_two"),
            ),
            ApiErrorId.PACKET_NOT_SUBMITTED,
            409,
        )

        # The cleared submitter is what lets a different officer take the next lap.
        second = fixtures.submit_packet(
            client, full_roster, first["id"], officer_handle="cert_officer_two"
        )
        assert second["status"] == "SUBMITTED"
        assert second["submitted_by_staff_member_id"] == full_roster.id_of(
            "cert_officer_two"
        )
        # Nothing about the world changed, so the fresh computation lands the same.
        assert_two_decimals(
            second["documentation_completeness_score"],
            83.34,
            "second documentation_completeness_score",
        )
        assert second["return_count"] == 1

        second_return = fixtures.decide_packet(
            client,
            full_roster,
            first["id"],
            decision="RETURN",
            officer_handle="cert_officer",
            decision_notes="Still short of the programme evidence.",
        )
        assert second_return["status"] == "RETURNED"
        assert second_return["return_count"] == 2

        third = fixtures.submit_packet(
            client, full_roster, first["id"], officer_handle="cert_officer"
        )
        assert third["status"] == "SUBMITTED"
        assert third["return_count"] == 2
        assert_two_decimals(
            third["documentation_completeness_score"],
            83.34,
            "third documentation_completeness_score",
        )


class TestReplacementPlanIndependentAxes:
    def test_the_disposal_axis_advances_while_funding_is_still_draft(
        self, client, roster
    ):
        """Manifesting the old carpet needs no funding decision at all.

        "The disposal axis advances on its own and, until the very last step,
        **never reads the funding axis**."

        "A permitted manifest takes the axis `PENDING → MANIFESTED`, records the
        four supplied values, and writes `diversion_ratio` as that same rounded
        quotient. `funding_status` is neither read nor changed."

        "Submitting a plan records the `submitted_by_staff_member_id`, stamps
        `submitted_at_utc`, and takes the funding axis `DRAFT → SUBMITTED`."

        "The disposal axis is untouched by submission."

        Design: Difficulty/non_linear_state_machine/replacement_plan_funding_and_disposal_axes_advance_independently
        """
        field = fixtures.register_synthetic_stadium_1(client, roster)
        budget = fixtures.authorize_budget(client, roster)
        plan = fixtures.draft_plan(
            client,
            roster,
            field["id"],
            budget["id"],
            field["version"],
            target_surface_type="SYNTHETIC_TURF",
            area_sq_ft=70000,
            priority_basis="CONDITION_RISK",
            planned_install_year=2028,
        )
        assert plan["funding_status"] == "DRAFT"
        assert plan["disposal_status"] == "PENDING"
        assert plan["plan_funding_amount_cents"] == 5243000

        manifested = fixtures.record_manifest(client, roster, plan["id"])
        assert manifested["disposal_status"] == "MANIFESTED"
        # The funding axis has not been consulted.
        assert manifested["funding_status"] == "DRAFT"
        assert manifested["manifest_reference"] == "MAN-2027-0001"
        assert manifested["disposal_facility_name"] == "Rivergate Polymer Recovery"
        # 46.0 of 50.0 tonnes diverted.
        assert_two_decimals(manifested["diversion_ratio"], 0.92, "diversion_ratio")

        # The one place the axes are read together refuses this combination.
        validate_error(
            client.complete_disposal(
                plan["id"],
                factories.make_disposal_complete_payload("2026-08-01T00:00:00Z"),
                roster.director_headers,
            ),
            ApiErrorId.DISPOSAL_COMPLETION_NOT_PERMITTED,
            409,
        )
        held = fixtures.read_plan(client, roster, plan["id"])
        assert held["disposal_status"] == "MANIFESTED"
        assert held.get("completed_at_utc") is None
        still_live = fixtures.read_field(client, roster, field["id"])
        assert still_live.get("retired_at") is None
        assert still_live["play_status"] == "OPEN"

        submitted = fixtures.submit_plan(client, roster, plan["id"])
        assert submitted["funding_status"] == "SUBMITTED"
        # The funding axis moved without disturbing the disposal axis.
        assert submitted["disposal_status"] == "MANIFESTED"

        after_budget = fixtures.read_budget(client, roster, budget["id"])
        assert after_budget["committed_amount_cents"] == 0
        assert after_budget["status"] == "OPEN"

    def test_completion_requires_both_axes_in_position_and_retires_the_field(
        self, client, full_roster
    ):
        """The single cross-axis guard, refused from either side and then satisfied.

        "It requires a `completed_at_utc` at or before the current logical instant,
        and it requires both axes to be in position: `disposal_status` must be
        `MANIFESTED` and `funding_status` must be `APPROVED`. Either one out of
        position is refused with `ERR_DISPOSAL_COMPLETION_NOT_PERMITTED`."

        "On success the axis moves `MANIFESTED → COMPLETED`, the supplied
        `completed_at_utc` is recorded on the plan, and the field is retired:
        `Field.retired_at` is set to that same `completed_at_utc`, which drives
        `play_status` to `RETIRED` from whichever posture it held"

        "**Every** non-terminal booking on the field is then cancelled, moving
        `SCHEDULED → CANCELLED_UNSAFE` and `CONFIRMED → CANCELLED_UNSAFE` with no
        window filter at all, unlike the unsafe cascade of §3.4 which spares
        fixtures already under way; each such cancellation appends its own
        `UNSAFE_CANCELLATION` ledger entry with a `wear_units_delta` of 0.00,
        increments `unsafe_cancellation_count` and forces a rest-debt recompute."

        Design: Difficulty/non_linear_state_machine/replacement_plan_funding_and_disposal_axes_advance_independently
        """
        field = fixtures.register_synthetic_stadium_1(client, full_roster)
        budget = fixtures.authorize_budget(client, full_roster)
        plan = fixtures.draft_plan(
            client,
            full_roster,
            field["id"],
            budget["id"],
            field["version"],
            target_surface_type="SYNTHETIC_TURF",
            area_sq_ft=70000,
            priority_basis="CONDITION_RISK",
            planned_install_year=2028,
        )

        # Refused from the disposal side: the axis is still `PENDING`.
        validate_error(
            client.complete_disposal(
                plan["id"],
                factories.make_disposal_complete_payload("2026-08-01T00:00:00Z"),
                full_roster.director_headers,
            ),
            ApiErrorId.DISPOSAL_COMPLETION_NOT_PERMITTED,
            409,
        )

        confirmed_booking = fixtures.request_booking(
            client,
            full_roster,
            field["id"],
            activity_type="PRACTICE",
            window_start_utc="2026-08-10T10:00:00Z",
            window_end_utc="2026-08-10T12:00:00Z",
            expected_participant_count=30,
        )
        scheduled_booking = fixtures.request_booking(
            client,
            full_roster,
            field["id"],
            activity_type="PRACTICE",
            window_start_utc="2026-08-11T10:00:00Z",
            window_end_utc="2026-08-11T12:00:00Z",
            expected_participant_count=30,
        )
        fixtures.confirm_booking(client, full_roster, confirmed_booking["id"])

        fixtures.record_manifest(client, full_roster, plan["id"])
        fixtures.submit_plan(client, full_roster, plan["id"])
        approved = fixtures.decide_plan(
            client, full_roster, plan["id"], decision="APPROVE"
        )
        assert approved["funding_status"] == "APPROVED"
        assert approved["disposal_status"] == "MANIFESTED"

        committed = fixtures.read_budget(client, full_roster, budget["id"])
        assert committed["committed_amount_cents"] == 5243000
        # Ninety percent of 5825556 rounds to 5243000, so the commitment reaches it.
        assert committed["lock_threshold_amount_cents"] == 5243000
        assert committed["status"] == "LOCKED"

        completed = fixtures.complete_disposal(
            client, full_roster, plan["id"], "2026-08-01T00:00:00Z"
        )
        assert completed["disposal_status"] == "COMPLETED"
        assert_instant_equals(
            completed["completed_at_utc"],
            "2026-08-01T00:00:00Z",
            "ReplacementPlan.completed_at_utc",
        )

        retired = fixtures.read_field(client, full_roster, field["id"])
        assert_instant_equals(
            retired["retired_at"], "2026-08-01T00:00:00Z", "Field.retired_at"
        )
        assert retired["play_status"] == "RETIRED"
        assert retired["certification_status"] == "NOT_CERTIFIED"
        assert retired["unsafe_cancellation_count"] == 2

        for booking_id in (confirmed_booking["id"], scheduled_booking["id"]):
            cancelled = fixtures.read_booking(client, full_roster, booking_id)
            assert cancelled["status"] == "CANCELLED_UNSAFE"

        entries, meta = validate_paginated(
            client.list_usage_ledger_entries(
                full_roster.coordinator_headers,
                params={
                    "limit": 100,
                    "field_id": field["id"],
                    "entry_type": "UNSAFE_CANCELLATION",
                },
            )
        )
        assert meta["total_count"] == 2
        for entry in entries:
            assert_two_decimals(entry["wear_units_delta"], 0.00, "wear_units_delta")
