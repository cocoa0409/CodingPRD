"""Staff shift rules, compliance artifacts, drain-safety posture and the OPEN gate."""

from test_helpers import (
    ADMIN,
    INSPECTOR,
    ApiErrorId,
    assert_posture,
    cancel_staff_shift,
    create_staff_assignment_payload,
    open_closure_order,
    post_all_required_signage,
    post_drain_certification,
    read_artifacts,
    read_facility,
    read_staff_assignment,
    schedule_staff_shift,
    setup_facility_with_issued_permit,
    setup_operator_and_pool,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_cancelling_an_already_cancelled_shift_is_rejected(api):
    """PRD 3.8: The operator may cancel a shift that is still `SCHEDULED`, moving
    it `SCHEDULED → CANCELLED` with `cancel_reason` of `OPERATOR_REQUEST` and
    `cancelled_at` stamped from the logical clock, again recomputing the posture
    and bumping the version; cancelling one already in `CANCELLED` is
    `ERR_ASSIGNMENT_ALREADY_CANCELLED`.

    Design: Corner/state_machines/staff_assignment_cancel_twice_rejected
    """
    ctx = setup_facility_with_issued_permit()
    assignment = schedule_staff_shift(ctx["facility_id"], ctx["op_headers"])
    cancel_staff_shift(assignment["id"], ctx["op_headers"])

    validate_error(
        api.cancel_staff_assignment(assignment["id"], ctx["op_headers"]),
        ApiErrorId.ERR_ASSIGNMENT_ALREADY_CANCELLED.value, 409,
    )

    stored = read_staff_assignment(ctx["facility_id"], assignment["id"], ADMIN)
    assert stored["status"] == "CANCELLED"
    assert stored["cancel_reason"] == "OPERATOR_REQUEST"
    assert stored["cancelled_at"] == "2026-05-01T00:00:00.000Z"


def test_a_shift_starting_after_the_certification_lapses_is_rejected(api):
    """PRD 3.8: The individual's `certification_expires_on` must be on or after
    the date part of `shift_start_at`, or `ERR_CERTIFICATION_EXPIRED`.

    Design: Corner/validations/staff_shift_with_expired_certification_rejected
    """
    ctx = setup_facility_with_issued_permit()

    validate_error(
        api.create_staff_assignment(
            create_staff_assignment_payload(
                ctx["facility_id"], staff_ref="LG-009", staff_name="Dev Patel",
                certification_expires_on="2026-05-01",
                shift_start_at="2026-05-02T08:00:00Z",
                shift_end_at="2026-05-02T14:00:00Z",
            ),
            ctx["op_headers"],
        ),
        ApiErrorId.ERR_CERTIFICATION_EXPIRED.value, 409,
    )

    rows, meta = validate_paginated(
        api.list_staff_assignments(ctx["facility_id"], ADMIN)
    )
    assert meta["total_count"] == 0 and rows == []


def test_a_shift_longer_than_twelve_hours_is_rejected(api):
    """PRD 3.8: The shift's end must be strictly after its start and the shift
    may run no longer than 720 minutes — twelve hours — with any breach reported
    as `ERR_SHIFT_TOO_LONG` (HTTP 422).

    Design: Corner/validations/staff_shift_longer_than_the_maximum_rejected
    """
    ctx = setup_facility_with_issued_permit()

    validate_error(
        api.create_staff_assignment(
            create_staff_assignment_payload(
                ctx["facility_id"], staff_ref="LG-010", staff_name="Sam Cole",
                role_type="ATTENDANT",
                shift_start_at="2026-05-02T08:00:00Z",
                shift_end_at="2026-05-02T21:00:00Z",
            ),
            ctx["op_headers"],
        ),
        ApiErrorId.ERR_SHIFT_TOO_LONG.value, 422,
    )

    rows, meta = validate_paginated(
        api.list_staff_assignments(ctx["facility_id"], ADMIN)
    )
    assert meta["total_count"] == 0 and rows == []


def test_two_different_staff_refs_may_share_a_shift_window(api):
    """PRD 3.8: And the same person, identified by an identical `staff_ref`, may
    not hold two `SCHEDULED` shifts that overlap: two shifts overlap when the new
    start is strictly before the other's end and the other's start is strictly
    before the new end, so back-to-back shifts that merely touch — where one
    begins at the exact instant the other ends — do **not** conflict, while any
    genuine intersection is rejected with `ERR_STAFF_SHIFT_OVERLAP`.

    Design: Corner/validations/two_staff_refs_may_hold_identical_shift_windows
    """
    ctx = setup_facility_with_issued_permit()
    schedule_staff_shift(
        ctx["facility_id"], ctx["op_headers"],
        shift_start_at="2026-05-02T08:00:00Z", shift_end_at="2026-05-02T12:00:00Z",
    )

    second = validate_success(
        api.create_staff_assignment(
            create_staff_assignment_payload(
                ctx["facility_id"], staff_ref="LG-002", staff_name="Kim Lee",
                shift_start_at="2026-05-02T08:00:00Z",
                shift_end_at="2026-05-02T12:00:00Z",
            ),
            ctx["op_headers"],
        ),
        201,
    )
    assert second["status"] == "SCHEDULED"

    rows, meta = validate_paginated(
        api.list_staff_assignments(ctx["facility_id"], ADMIN)
    )
    assert meta["total_count"] == 2
    assert all(row["status"] == "SCHEDULED" for row in rows)


def test_an_artifact_carrying_the_other_types_fields_is_rejected(api):
    """PRD 3.8: An `artifact_type` of `SIGNAGE` documents a posted sign and
    requires a `signage_type` — one of `DEPTH_MARKERS`, `EMERGENCY_PHONE`,
    `DIARRHEA_NOTICE`, `NO_LIFEGUARD_WARNING` or `SPA_TEMP_WARNING` — while
    forbidding `drain_cover_model` and `sva_system_type`.
    PRD 3.8: Carrying a field belonging to the other type, or omitting one its
    own type requires, is rejected with `ERR_ARTIFACT_FIELDS_MISMATCH` (HTTP
    422).

    Design: Corner/validations/compliance_artifact_with_wrong_type_fields_rejected
    """
    ctx = setup_operator_and_pool()

    validate_error(
        api.create_compliance_artifact(
            ctx["facility_id"],
            {
                "artifact_type": "SIGNAGE",
                "effective_on": "2026-05-01",
                "signage_type": "DEPTH_MARKERS",
                "drain_cover_model": "AquaSafe VGB-12",
            },
            ctx["op_headers"],
        ),
        ApiErrorId.ERR_ARTIFACT_FIELDS_MISMATCH.value, 422,
    )

    validate_error(
        api.create_compliance_artifact(
            ctx["facility_id"],
            {
                "artifact_type": "DRAIN_CERTIFICATION",
                "effective_on": "2026-05-01",
                "drain_cover_model": "AquaSafe VGB-12",
            },
            ctx["op_headers"],
        ),
        ApiErrorId.ERR_ARTIFACT_FIELDS_MISMATCH.value, 422,
    )

    rows, meta = validate_paginated(
        api.list_compliance_artifacts(ctx["facility_id"], ADMIN)
    )
    assert meta["total_count"] == 0 and rows == []


def test_a_single_drain_venue_needs_a_secondary_avoidance_system(api):
    """PRD 3.8: Otherwise, if the venue has fewer than 2 submerged suction
    outlets and the governing certification's `sva_system_type` is `NONE` — a
    single unprotected drain, the exact configuration the federal rule was
    written to eliminate — the status is `NONCOMPLIANT`. In every other case it
    is `COMPLIANT`.
    PRD 3.8: `status` is derived and resolved in a fixed order: it is
    `SUPERSEDED` once a later artifact sharing the same facility, `artifact_type`
    and `signage_type` key has been created; otherwise `EXPIRED` when the
    logical-clock date is strictly after `expires_on`; otherwise `ACTIVE`.
    PRD 3.8: `expires_on` is computed as the inclusive last valid day: 365 days
    after `effective_on` for a sign, and 1825 days — five years — after
    `effective_on` for a drain certification.

    Design: Corner/calculations/vgb_single_drain_requires_a_secondary_avoidance_system
    """
    ctx = setup_operator_and_pool(drain_count=1)

    first_cert = post_drain_certification(
        ctx["facility_id"], ctx["op_headers"], sva_system_type="NONE"
    )
    assert first_cert["expires_on"] == "2031-04-30"
    assert (
        read_facility(ctx["facility_id"])["vgb_compliance_status"] == "NONCOMPLIANT"
    )

    second_cert = post_drain_certification(
        ctx["facility_id"], ctx["op_headers"], sva_system_type="SVRS"
    )
    assert second_cert["status"] == "ACTIVE"
    assert read_facility(ctx["facility_id"])["vgb_compliance_status"] == "COMPLIANT"

    artifacts = read_artifacts(ctx["facility_id"], ADMIN)
    by_id = {row["id"]: row for row in artifacts}
    assert by_id[first_cert["id"]]["status"] == "SUPERSEDED"
    assert by_id[second_cert["id"]]["status"] == "ACTIVE"


def test_a_certification_past_its_five_year_lifespan_reads_expired(api):
    """PRD 3.8: If the logical-clock date is strictly after that governing
    certification's `expires_on`, the status is `EXPIRED`.
    PRD 3.8: `expires_on` is computed as the inclusive last valid day: 365 days
    after `effective_on` for a sign, and 1825 days — five years — after
    `effective_on` for a drain certification.

    Design: Corner/calculations/vgb_certification_expires_after_the_cover_lifespan
    """
    ctx = setup_operator_and_pool()

    cert = post_drain_certification(
        ctx["facility_id"], ctx["op_headers"],
        sva_system_type="MULTIPLE_MAIN_DRAINS", effective_on="2020-01-01",
        drain_cover_model="LegacyDrain 5",
    )

    assert cert["expires_on"] == "2024-12-30"
    assert cert["status"] == "EXPIRED"
    assert read_facility(ctx["facility_id"])["vgb_compliance_status"] == "EXPIRED"

    rows, meta = validate_paginated(
        api.list_compliance_artifacts(
            ctx["facility_id"], ADMIN,
            params={"artifact_type": "DRAIN_CERTIFICATION"},
        )
    )
    assert meta["total_count"] == 1 and rows[0]["id"] == cert["id"]


def test_the_posture_reaches_open_only_when_every_clause_is_satisfied(api):
    """PRD 2.9: The facility's `lifeguard_required` is true and there is no staff
    assignment for this facility with status `SCHEDULED`, `role_type` of
    `LIFEGUARD`, and a shift interval covering the current logical clock instant
    — the interval is half-open, so a shift covers the clock when
    `shift_start_at` is at or before it and `shift_end_at` is strictly after it →
    `RESTRICTED` with reason `LIFEGUARD_COVERAGE_MISSING`.
    PRD 2.9: Otherwise → `OPEN` with reason `NONE`.
    PRD 3.8: A new assignment is created in `SCHEDULED` with `cancel_reason` and
    `cancelled_at` both null, and it recomputes the facility's
    `operating_posture` — potentially lifting a `LIFEGUARD_COVERAGE_MISSING`
    restriction — while incrementing the facility's `version` by 1.

    Design: Corner/calculations/facility_posture_reaches_open_when_every_clause_is_satisfied
    """
    ctx = setup_facility_with_issued_permit()
    post_drain_certification(
        ctx["facility_id"], ctx["op_headers"],
        sva_system_type="MULTIPLE_MAIN_DRAINS",
    )
    post_all_required_signage(
        ctx["facility_id"], ctx["op_headers"],
        ["DEPTH_MARKERS", "EMERGENCY_PHONE", "DIARRHEA_NOTICE"],
    )

    before = read_facility(ctx["facility_id"])
    assert_posture(before, "RESTRICTED", "LIFEGUARD_COVERAGE_MISSING")

    schedule_staff_shift(
        ctx["facility_id"], ctx["op_headers"],
        shift_start_at="2026-05-01T00:00:00Z", shift_end_at="2026-05-01T08:00:00Z",
    )

    after = read_facility(ctx["facility_id"])
    assert_posture(after, "OPEN", "NONE")
    assert after["vgb_compliance_status"] == "COMPLIANT"

    artifacts, meta = validate_paginated(
        api.list_compliance_artifacts(ctx["facility_id"], ADMIN)
    )
    assert meta["total_count"] == 4
    assert all(row["status"] == "ACTIVE" for row in artifacts)


class TestClosedPostureOutranksShiftOverlap:
    """One request breaching both rules must report the earlier ladder rung."""

    @staticmethod
    def _setup():
        ctx = setup_facility_with_issued_permit()
        ctx["existing"] = schedule_staff_shift(
            ctx["facility_id"], ctx["op_headers"],
            shift_start_at="2026-05-02T08:00:00Z",
            shift_end_at="2026-05-02T16:00:00Z",
        )
        ctx["order"] = open_closure_order(
            ctx["facility_id"], INSPECTOR, "CHEMICAL",
            note="Acid spill in the pump room",
        )
        return ctx

    def test_the_closed_posture_error_is_reported_not_the_overlap_error(self, api):
        """PRD 2.6: **Facility not closed** → `ERR_FACILITY_CLOSED` (409), on
        `POST /staff-assignments`.
        PRD 2.6: **Staff shift overlap** → `ERR_STAFF_SHIFT_OVERLAP` (409), on
        `POST /staff-assignments`.
        PRD 3.8: A shift may not be booked at a venue whose `operating_posture`
        is `CLOSED`, which is rejected with `ERR_FACILITY_CLOSED`.

        Design: Difficulty/priority_pair_validation_conflict/staff_assignment_facility_closed_outranks_shift_overlap
        """
        ctx = self._setup()

        response = api.create_staff_assignment(
            create_staff_assignment_payload(
                ctx["facility_id"],
                shift_start_at="2026-05-02T12:00:00Z",
                shift_end_at="2026-05-02T18:00:00Z",
            ),
            ctx["op_headers"],
        )

        validate_error(response, ApiErrorId.ERR_FACILITY_CLOSED.value, 409)
        assert response.json()["data"]["error_id"] != "ERR_STAFF_SHIFT_OVERLAP", (
            "LG-001 already holds 08:00-16:00, which the request overlaps by four hours"
        )

    def test_the_earlier_shift_survives_a_closure_window_that_never_covered_it(
        self, api
    ):
        """PRD 3.7: Then every staff assignment of that facility whose status is
        `SCHEDULED` and whose shift overlaps the closure window is cancelled with
        `cancel_reason` of `FACILITY_CLOSED` and `cancelled_at` stamped from the
        logical clock; a shift overlaps when its `shift_start_at` is strictly
        before the order's `earliest_reopen_at` and its `shift_end_at` is
        strictly after the order's `ordered_at`.
        PRD 2.9: The facility has at least one closure order whose status is
        `OPEN` or `REOPEN_REQUESTED` → `CLOSED` with reason `CLOSURE_ORDER_OPEN`.

        Design: Difficulty/priority_pair_validation_conflict/staff_assignment_facility_closed_outranks_shift_overlap
        """
        ctx = self._setup()

        surviving = read_staff_assignment(
            ctx["facility_id"], ctx["existing"]["id"], ADMIN
        )
        assert surviving["status"] == "SCHEDULED"
        assert surviving["cancel_reason"] is None

        rows, meta = validate_paginated(
            api.list_staff_assignments(ctx["facility_id"], ADMIN)
        )
        assert meta["total_count"] == 1

        assert_posture(
            read_facility(ctx["facility_id"]), "CLOSED", "CLOSURE_ORDER_OPEN"
        )


class TestHalfOpenShiftIntervals:
    """Shift occupancy is unbuffered and half-open on the staff_ref resource."""

    @staticmethod
    def _setup():
        ctx = setup_facility_with_issued_permit()
        ctx["first"] = schedule_staff_shift(
            ctx["facility_id"], ctx["op_headers"],
            shift_start_at="2026-05-02T08:00:00Z",
            shift_end_at="2026-05-02T12:00:00Z",
        )
        return ctx

    def test_a_back_to_back_shift_that_merely_touches_is_accepted(self, api):
        """PRD 3.8: two shifts overlap when the new start is strictly before the
        other's end and the other's start is strictly before the new end, so
        back-to-back shifts that merely touch — where one begins at the exact
        instant the other ends — do **not** conflict, while any genuine
        intersection is rejected with `ERR_STAFF_SHIFT_OVERLAP`.
        PRD 3.8: The shift interval is half-open: it includes its start and
        excludes its end.

        Design: Difficulty/resource_temporal_overlap/staff_shift_half_open_interval_touching_allowed_overlap_rejected
        """
        ctx = self._setup()

        touching = validate_success(
            api.create_staff_assignment(
                create_staff_assignment_payload(
                    ctx["facility_id"],
                    shift_start_at="2026-05-02T12:00:00Z",
                    shift_end_at="2026-05-02T16:00:00Z",
                ),
                ctx["op_headers"],
            ),
            201,
        )

        assert touching["status"] == "SCHEDULED"
        assert touching["shift_start_at"] == "2026-05-02T12:00:00.000Z"

    def test_a_shift_intersecting_the_interior_is_rejected(self, api):
        """PRD 3.8: And the same person, identified by an identical `staff_ref`,
        may not hold two `SCHEDULED` shifts that overlap: two shifts overlap when
        the new start is strictly before the other's end and the other's start is
        strictly before the new end, so back-to-back shifts that merely touch —
        where one begins at the exact instant the other ends — do **not**
        conflict, while any genuine intersection is rejected with
        `ERR_STAFF_SHIFT_OVERLAP`.

        Design: Difficulty/resource_temporal_overlap/staff_shift_half_open_interval_touching_allowed_overlap_rejected
        """
        ctx = self._setup()
        second = schedule_staff_shift(
            ctx["facility_id"], ctx["op_headers"],
            shift_start_at="2026-05-02T12:00:00Z",
            shift_end_at="2026-05-02T16:00:00Z",
        )

        validate_error(
            api.create_staff_assignment(
                create_staff_assignment_payload(
                    ctx["facility_id"],
                    shift_start_at="2026-05-02T15:59:00Z",
                    shift_end_at="2026-05-02T20:00:00Z",
                ),
                ctx["op_headers"],
            ),
            ApiErrorId.ERR_STAFF_SHIFT_OVERLAP.value, 409,
        )

        rows, meta = validate_paginated(
            api.list_staff_assignments(ctx["facility_id"], ADMIN)
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {ctx["first"]["id"], second["id"]}
        assert all(row["status"] == "SCHEDULED" for row in rows)
