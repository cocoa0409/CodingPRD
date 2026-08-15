"""Environmental sampling: two-tier classification boundaries, excursion
creation, and severity scoring."""
from test_helpers import (
    ENV_TECH,
    NON_EXISTENT_UUID,
    QA,
    ApiErrorId,
    add_sampling_point,
    assert_environmental_sample,
    assert_excursion,
    assert_severity_score_value,
    close_excursion,
    create_room,
    create_sample_payload,
    get_success_data,
    record_excursion_sample,
    record_sample,
    set_clock,
    validate_error,
    validate_success,
)


def _iso7_particle_room(room_code):
    room = create_room(room_code=room_code)
    point = add_sampling_point(room["id"], point_code=f"SP-{room_code}",
                               metric="PARTICLE")
    return room, point


class TestSampleClassificationBoundary:
    def test_sample_below_alert_limit_stays_in_control(self, api):
        """PRD §3.3: "a `result_value` at or above the room's action limit for
        the point's metric yields `ACTION_EXCEEDED`; otherwise a value at or
        above the alert limit yields `ALERT_EXCEEDED`; otherwise the sample
        stands `IN_CONTROL`. Any classification other than `IN_CONTROL`
        automatically creates an excursion within the same request."

        Design: Difficulty/boundary_precision_check/sample_exactly_at_alert_limit_trips_excursion
        """
        room, point = _iso7_particle_room("CR-K")
        resp = api.create_sample(
            create_sample_payload(point["id"], result_value=299999,
                                  sampled_at="2026-08-01T09:00:00Z"),
            ENV_TECH,
        )
        sample = validate_success(resp, 201)
        assert_environmental_sample(sample)
        assert sample["classification"] == "IN_CONTROL", (
            f"299999 < alert 300000 must stay IN_CONTROL, got {sample['classification']}")
        assert sample["triggered_excursion_id"] is None

    def test_sample_exactly_at_alert_limit_trips_alert_excursion(self, api):
        """PRD §2.6: "The comparison boundary includes equality on both tiers —
        a result exactly equal to the alert limit exceeds the alert tier, and a
        result exactly equal to the action limit exceeds the action tier."
        PRD §3.3: "its `severity` mirroring the sample's classification
        (`ALERT_EXCEEDED` becomes `ALERT`; `ACTION_EXCEEDED` becomes `ACTION`)".

        Design: Difficulty/boundary_precision_check/sample_exactly_at_alert_limit_trips_excursion
        """
        room, point = _iso7_particle_room("CR-K")
        resp = api.create_sample(
            create_sample_payload(point["id"], result_value=300000,
                                  sampled_at="2026-08-01T09:05:00Z"),
            ENV_TECH,
        )
        sample = validate_success(resp, 201)
        assert sample["classification"] == "ALERT_EXCEEDED", (
            "300000 >= alert 300000: the boundary is inclusive")
        assert sample["triggered_excursion_id"], (
            "a non-IN_CONTROL classification must auto-create an excursion")
        excursion = get_success_data(
            api.get_excursion(sample["triggered_excursion_id"], QA))
        assert_excursion(excursion)
        assert excursion["severity"] == "ALERT", (
            "300000 < action 352000, so the excursion is alert-severity")
        assert excursion["status"] == "OPEN"
        assert excursion["sample_id"] == sample["id"]
        assert excursion["cleanroom_id"] == room["id"]

    def test_sample_action_limit_boundary_pair(self, api):
        """PRD §2.6: "The comparison boundary includes equality on both tiers —
        a result exactly equal to the alert limit exceeds the alert tier, and a
        result exactly equal to the action limit exceeds the action tier."

        Design: Corner/calculations/action_boundary_sample_trips_action_excursion
        """
        room, point = _iso7_particle_room("CR-C1")
        below = record_sample(point["id"], 351999,
                              sampled_at="2026-08-01T09:00:00Z")
        assert below["classification"] == "ALERT_EXCEEDED", (
            "351999 < action 352000 but >= alert 300000")

        at_action = record_sample(point["id"], 352000,
                                  sampled_at="2026-08-01T09:05:00Z")
        assert at_action["classification"] == "ACTION_EXCEEDED", (
            "352000 >= action 352000: the boundary is inclusive")
        excursion = get_success_data(
            api.get_excursion(at_action["triggered_excursion_id"], QA))
        assert excursion["severity"] == "ACTION"


class TestSampleValidation:
    def test_sample_negative_result_value_rejected(self, api):
        """PRD §3.3: "the measured `result_value` — a non-negative integer
        count, particles per cubic meter or CFU per cubic meter depending on
        the point's `metric`".
        PRD §2.10: "Structural request validity — required fields present, enum
        values valid, each action limit strictly greater than its alert limit,
        an audit's `window_end` strictly after its `window_start`,
        `dwell_minutes` not negative, `result_value` not negative, and
        `root_cause` at least 20 characters long (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/sample_result_value_negative_rejected
        """
        room, point = _iso7_particle_room("CR-E6")
        resp = api.create_sample(
            create_sample_payload(point["id"], result_value=-1,
                                  sampled_at="2026-08-01T09:00:00Z"),
            ENV_TECH,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_sample_with_nonexistent_sampling_point_returns_404(self, api):
        """PRD §2.10: "Existence of every identifier in the path and every
        foreign-key identifier in the body, validated left to right
        (`ERR_NOT_FOUND`)."

        Design: Corner/validations/nonexistent_fk_in_body_returns_404
        """
        resp = api.create_sample(
            create_sample_payload(NON_EXISTENT_UUID, result_value=5,
                                  sampled_at="2026-08-01T09:00:00Z"),
            ENV_TECH,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_recurrence_link_to_open_excursion_rejected(self, api):
        """PRD §3.3: "Optionally the technician declares
        `recurrence_of_excursion_id`, a self-link asserting that this result
        recurs an earlier excursion at the same location; the link must point
        to a `CLOSED` excursion at the same sampling point, otherwise the
        record is rejected with `ERR_REFERENTIAL_INTEGRITY`."

        Design: Corner/validations/referential_integrity_recurrence_target_not_closed
        """
        room = create_room(room_code="CR-V3", iso_class="ISO_5",
                           particle_alert_limit=100000,
                           particle_action_limit=352000,
                           viable_alert_limit=10, viable_action_limit=20)
        point = add_sampling_point(room["id"], point_code="SP-V3", metric="VIABLE")
        _sample, excursion_id = record_excursion_sample(point["id"], 15)

        resp = api.create_sample(
            create_sample_payload(point["id"], result_value=16,
                                  sampled_at="2026-08-01T10:00:00Z",
                                  recurrence_of_excursion_id=excursion_id),
            ENV_TECH,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_INTEGRITY)

    def test_retired_point_rejects_new_sample(self, api):
        """PRD §3.1: "A point spends its life `ACTIVE`; QA may retire it,
        moving it from `ACTIVE` to `RETIRED` — permitted only while the point
        is `ACTIVE`, otherwise `ERR_INVALID_STATE` — and a retired point
        rejects any new sample, also with `ERR_INVALID_STATE`."

        Design: Corner/errors/error_invalid_state_on_retired_point_sample
        """
        room, point = _iso7_particle_room("CR-ERF")
        retired = validate_success(api.retire_sampling_point(point["id"], QA), 200)
        assert retired["status"] == "RETIRED"

        resp = api.create_sample(
            create_sample_payload(point["id"], result_value=5,
                                  sampled_at="2026-08-01T09:00:00Z"),
            ENV_TECH,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestExcursionSeverityScore:
    def _iso5_viable_room(self, room_code):
        room = create_room(room_code=room_code, iso_class="ISO_5",
                           particle_alert_limit=100000,
                           particle_action_limit=352000,
                           viable_alert_limit=10, viable_action_limit=20)
        point = add_sampling_point(room["id"], point_code=f"SP-{room_code}",
                                   metric="VIABLE")
        return room, point

    def _close(self, excursion_id, investigator_id, approver_id, root_cause):
        close_excursion(excursion_id, product_impact="NONE", disposition="RELEASE",
                        root_cause=root_cause, investigator_id=investigator_id,
                        approver_id=approver_id)

    def test_severity_score_viable_iso5_with_two_recurrences(self, api):
        """PRD §3.3: "The severity score combines three factors. The base
        weight is 10 when the sampling point's `metric` is `VIABLE` and 4 when
        it is `PARTICLE`. The zone multiplier is read from the point's
        `zone_iso_class`: 3 for `ISO_5`, 2.5 for `ISO_6`, 2 for `ISO_7`, and 1
        for `ISO_8`. The recurrence factor counts how many excursions at the
        same sampling point already stand `CLOSED` with their triggering
        sample's `sampled_at` falling inside the trailing 30-day window before
        this sample's `sampled_at`; the window includes its lower bound exactly
        thirty days back and excludes this sample's own instant, the count is
        taken only from excursions closed before this excursion's creation, and
        the new excursion never counts itself. The score is the base weight
        multiplied by the zone multiplier, multiplied by one plus one quarter
        of the recurrence count, rounded half-up to two decimal places."

        Design: Difficulty/combinatorial_formula/severity_score_three_input_nonlinear
        """
        room, point = self._iso5_viable_room("CR-C")
        _s1, exc1 = record_excursion_sample(
            point["id"], 25, sampled_at="2026-08-01T09:00:00Z", tech_user_id="tech-c")
        self._close(exc1, "qa-c1", "qa-c2", "First root cause narrative here")
        _s2, exc2 = record_excursion_sample(
            point["id"], 30, sampled_at="2026-08-01T10:00:00Z", tech_user_id="tech-c")
        self._close(exc2, "qa-c1", "qa-c2", "Second root cause narrative here")
        set_clock("2026-08-20T00:00:00Z")

        sample3 = record_sample(point["id"], 25, sampled_at="2026-08-20T00:00:00Z")
        exc3 = get_success_data(api.get_excursion(sample3["triggered_excursion_id"], QA))
        assert exc3["severity"] == "ACTION", "25 >= viable action limit 20"
        # base 10 (VIABLE) * zone 3 (ISO_5) * (1 + 0.25 * 2 closed recurrences)
        assert_severity_score_value(exc3["severity_score"], 45.0)

    def test_severity_score_accumulates_recurrence_across_siblings(self, api):
        """PRD §3.3: "The recurrence factor counts how many excursions at the
        same sampling point already stand `CLOSED` with their triggering
        sample's `sampled_at` falling inside the trailing 30-day window before
        this sample's `sampled_at`; the window includes its lower bound exactly
        thirty days back and excludes this sample's own instant, the count is
        taken only from excursions closed before this excursion's creation, and
        the new excursion never counts itself."

        Design: Difficulty/combinatorial_formula/severity_score_three_input_nonlinear
        """
        room, point = self._iso5_viable_room("CR-C")
        _s1, exc1 = record_excursion_sample(
            point["id"], 25, sampled_at="2026-08-01T09:00:00Z", tech_user_id="tech-c")
        first = get_success_data(api.get_excursion(exc1, QA))
        # No closed siblings at creation: 10 * 3 * (1 + 0.25 * 0) = 30.0
        assert_severity_score_value(first["severity_score"], 30.0)

        self._close(exc1, "qa-c1", "qa-c2", "First root cause narrative here")
        _s2, exc2 = record_excursion_sample(
            point["id"], 30, sampled_at="2026-08-01T10:00:00Z", tech_user_id="tech-c")
        second = get_success_data(api.get_excursion(exc2, QA))
        # One sibling closed before creation: 10 * 3 * (1 + 0.25 * 1) = 37.5
        assert_severity_score_value(second["severity_score"], 37.5)

    def test_severity_recurrence_window_excludes_out_of_window(self, api):
        """PRD §3.3: "The recurrence factor counts how many excursions at the
        same sampling point already stand `CLOSED` with their triggering
        sample's `sampled_at` falling inside the trailing 30-day window before
        this sample's `sampled_at`; the window includes its lower bound exactly
        thirty days back and excludes this sample's own instant, the count is
        taken only from excursions closed before this excursion's creation, and
        the new excursion never counts itself."

        Design: Corner/calculations/severity_recurrence_window_excludes_out_of_window
        """
        room, point = self._iso5_viable_room("CR-C3")
        _s, old_exc = record_excursion_sample(
            point["id"], 15, sampled_at="2026-06-30T00:00:00Z", tech_user_id="tech-c3")
        self._close(old_exc, "qa-c3a", "qa-c3b",
                    "Old excursion investigation narrative")

        sample = record_sample(point["id"], 15, sampled_at="2026-07-31T00:00:00Z")
        excursion = get_success_data(
            api.get_excursion(sample["triggered_excursion_id"], QA))
        # 2026-06-30 is 31 days before 2026-07-31: outside [2026-07-01, 2026-07-31)
        assert_severity_score_value(excursion["severity_score"], 30.0)
        assert excursion["severity"] == "ALERT", "15 >= viable alert 10, < action 20"


class TestImmediatePostureConsistency:
    def test_action_sample_immediately_reflects_on_room_read(self, api):
        """PRD §3.3: "The room posture is recomputed in the same breath — a
        first alert-severity excursion moves `IN_CONTROL` to `ALERT`, and an
        action-severity excursion raises the room to `ACTION`."

        Design: Corner/consistency_model/sample_creation_immediately_reflects_excursion_on_room_read
        """
        room, point = _iso7_particle_room("CR-CM1")
        sample = record_sample(point["id"], 400000,
                               sampled_at="2026-08-01T09:00:00Z")
        room_after = get_success_data(api.get_room(room["id"], QA))
        assert room_after["environment_posture"] == "ACTION", (
            "the very next read after the sample POST must show ACTION — "
            "no reconciliation delay")
        excursion = get_success_data(
            api.get_excursion(sample["triggered_excursion_id"], QA))
        assert excursion["status"] == "OPEN"
        assert excursion["severity"] == "ACTION"


class TestSamplingPointListing:
    def test_sampling_point_list_scoped_to_room(self, api):
        """PRD §3.1: "Within a room, QA defines the sampling plan as a set of
        sampling points."
        PRD §4: "`/cleanroom/rooms/{id}/sampling-points` | List sampling points
        of a room".

        Design: Corner/endpoints/sampling_point_filtered_list_by_room
        """
        room_l1 = create_room(room_code="CR-L1")
        room_l2 = create_room(room_code="CR-L2", iso_class="ISO_8",
                              particle_alert_limit=3500000,
                              particle_action_limit=3520000,
                              viable_alert_limit=100, viable_action_limit=200)
        add_sampling_point(room_l1["id"], point_code="SP-L1A", metric="PARTICLE")
        add_sampling_point(room_l1["id"], point_code="SP-L1B", metric="VIABLE")
        add_sampling_point(room_l2["id"], point_code="SP-L2A", metric="PARTICLE")

        data = validate_success(api.list_sampling_points(room_l1["id"], QA), 200)
        assert isinstance(data, list), "sub-resource listing returns an array"
        assert len(data) == 2, f"expected exactly room L1's 2 points, got {len(data)}"
        assert all(point["cleanroom_id"] == room_l1["id"] for point in data)
        assert {point["point_code"] for point in data} == {"SP-L1A", "SP-L1B"}
