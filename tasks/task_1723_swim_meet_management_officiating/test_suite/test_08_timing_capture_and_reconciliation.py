"""Timing readings: payload sanity, lane/event gates, the pinned backup-mean
rounding order, the auto-confirm threshold boundary, the two reconciliation
variants, and the reopen-timing cycle."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_entry,
    add_event,
    add_swimmer,
    add_team,
    create_open_meet,
    get_success_data,
    lane_for_entry,
    make_meet_referee_headers,
    make_team_coach_headers,
    readings_payload,
    seed_meet,
    setup_deck_coverage,
    setup_in_progress_event,
    start_event,
    submit_clean_readings,
    validate_error,
    validate_success,
    verify_entry,
)

DIRECTOR = TEST_USERS["meet_director_headers"]
TIMING = TEST_USERS["timing_operator_headers"]


def _seeded_lane(api, meet_name="RE10"):
    """Meet SEEDED, one seeded entry; returns (meet, event, entry, lane)."""
    meet = create_open_meet(meet_name=meet_name)
    team = add_team(meet["id"])
    swimmer = add_swimmer(team["id"], full_name="Sw A")
    event = add_event(meet["id"], qualifying_time_cs=3000)
    entry = add_entry(event["id"], swimmer["id"], team["id"],
                      seed_time_cs=2900)
    verify_entry(entry["id"])
    seed_meet(meet["id"])
    lane = lane_for_entry(entry["id"])
    return meet, team, event, entry, lane


class TestReadingsGates:
    def test_readings_on_voided_lane_rejected(self, api):
        """PRD §3.7: "the lane must be `ACTIVE` (`ERR_LANE_VOIDED` rejects
        readings on a voided lane)".

        Design: Corner/validations/readings_on_voided_lane_rejected
        """
        meet, team, event, entry, lane = _seeded_lane(api, meet_name="VL1")
        setup_deck_coverage(event["id"], meet["id"])
        validate_success(api.scratch_entry(entry["id"],
                                           make_team_coach_headers(team["id"])))
        start_event(event["id"])
        resp = api.submit_readings(
            lane["id"], readings_payload(pad_cs=2500, backup1_cs=2505,
                                         backup2_cs=2507), TIMING)
        validate_error(resp, ApiErrorId.ERR_LANE_VOIDED)

    def test_readings_before_event_start_rejected(self, api):
        """PRD §3.7: "and the event must be `IN_PROGRESS`
        (`ERR_EVENT_NOT_IN_PROGRESS`)."

        Design: Corner/errors/readings_before_event_start_rejected
        """
        _meet, _team, event, _entry, lane = _seeded_lane(api)
        # Event still SEEDED (never started); lane is ACTIVE.
        assert lane["lane_status"] == "ACTIVE"
        assert lane["reconciliation_status"] == "PENDING_READINGS"
        resp = api.submit_readings(
            lane["id"], readings_payload(pad_cs=2500, backup1_cs=2505,
                                         backup2_cs=2507), TIMING)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_IN_PROGRESS)

    def test_readings_empty_payload_rejected(self, api):
        """PRD §3.7: "Every submission must carry at least one of the four, or
        it fails with `ERR_INVALID_REQUEST`".

        Design: Corner/errors/readings_empty_payload_invalid_request
        """
        workspace = setup_in_progress_event(meet_name="RE15")
        lane = workspace["lanes"][0]
        resp = api.submit_readings(lane["id"], {}, TIMING)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestBackupMeanRoundingOrder:
    """Difficulty pair (nested rounding): pad 2543 with backups 2510/2515 —
    the rounded mean 2513 sits exactly at the 30cs threshold and auto-confirms;
    the raw mean 2512.5 would not."""

    def _setup(self, api):
        return setup_in_progress_event(meet_name="CF2")

    def test_rounded_first_mean_auto_confirms(self, api):
        """PRD §3.7: "Consider a pad reading of 2543 centiseconds with backups
        of 2510 and 2515: the raw mean is 2512.5, which sits 30.5 centiseconds
        from the pad and would exceed a 30-centisecond threshold, but the
        rounded mean is 2513, which sits exactly 30 away — at the threshold,
        not beyond it — so the lane auto-confirms. The rounded-first reading is
        authoritative."

        Design: Difficulty/combinatorial_formula/backup_mean_rounding_order_determines_auto_confirm
        """
        workspace = self._setup(api)
        lane = workspace["lanes"][0]
        resp = api.submit_readings(
            lane["id"], readings_payload(pad_cs=2543, backup1_cs=2510,
                                         backup2_cs=2515), TIMING)
        reconciled = validate_success(resp)
        assert reconciled["reconciliation_status"] == "AUTO_CONFIRMED", \
            "rounded mean 2513 gives delta 30 <= 30; raw 2512.5 would give 30.5"

    def test_auto_confirm_copies_pad_and_marks_primary(self, api):
        """PRD §3.7: "An auto-confirmed lane records `reconciled_variant`
        `PRIMARY_PRIORITY` and copies `pad_cs` into `final_time_cs`."

        Design: Difficulty/combinatorial_formula/backup_mean_rounding_order_determines_auto_confirm
        """
        workspace = self._setup(api)
        lane = workspace["lanes"][0]
        resp = api.submit_readings(
            lane["id"], readings_payload(pad_cs=2543, backup1_cs=2510,
                                         backup2_cs=2515), TIMING)
        reconciled = validate_success(resp)
        assert reconciled["final_time_cs"] == 2543
        assert reconciled["reconciled_variant"] == "PRIMARY_PRIORITY"


class TestTimingDeltaThresholdBoundary:
    """Difficulty pair: |pad - rounded backup mean| at exactly 30 vs 31."""

    def _setup(self, api):
        return setup_in_progress_event(meet_name="BP2",
                                       seed_times=(2900, 2910))

    def test_delta_exactly_at_threshold_auto_confirms(self, api):
        """PRD §3.7: "A submission auto-confirms — moving the lane from
        `PENDING_READINGS` to `AUTO_CONFIRMED` — when all of the following
        hold: the pad reading is present, `pad_status` is not `INVALID`, both
        backups are present, and the absolute difference between `pad_cs` and
        the rounded backup mean does not exceed the meet's
        `timing_delta_threshold_cs`."

        Design: Difficulty/boundary_precision_check/timing_delta_threshold_30_vs_31
        """
        workspace = self._setup(api)
        lane = workspace["lanes"][0]
        # backups 2501/2501 -> mean 2501; |2531 - 2501| == 30 == threshold.
        resp = api.submit_readings(
            lane["id"], readings_payload(pad_cs=2531, backup1_cs=2501,
                                         backup2_cs=2501), TIMING)
        reconciled = validate_success(resp)
        assert reconciled["reconciliation_status"] == "AUTO_CONFIRMED"
        assert reconciled["final_time_cs"] == 2531

    def test_delta_one_past_threshold_parks_for_review(self, api):
        """PRD §3.7: "Any submission falling short of those conditions — pad
        missing or flagged `INVALID`, a backup absent, or the delta strictly
        greater than the threshold — parks the lane in `MANUAL_REVIEW` with
        `final_time_cs` still null."

        Design: Difficulty/boundary_precision_check/timing_delta_threshold_30_vs_31
        """
        workspace = self._setup(api)
        lane = workspace["lanes"][1]
        # |2532 - 2501| == 31 > 30.
        resp = api.submit_readings(
            lane["id"], readings_payload(pad_cs=2532, backup1_cs=2501,
                                         backup2_cs=2501), TIMING)
        reconciled = validate_success(resp)
        assert reconciled["reconciliation_status"] == "MANUAL_REVIEW"
        assert reconciled.get("final_time_cs") is None


class TestReconciliationVariants:
    """Difficulty pair (dual variants): identical readings pad 2500, backups
    2530/2540 (rounded mean 2535, delta 35 > 30) resolve to different
    final_time_cs under the two variants."""

    def _setup(self, api):
        workspace = setup_in_progress_event(meet_name="DV1")
        lane = workspace["lanes"][0]
        resp = api.submit_readings(
            lane["id"], readings_payload(pad_cs=2500, backup1_cs=2530,
                                         backup2_cs=2540), TIMING)
        parked = validate_success(resp)
        assert parked["reconciliation_status"] == "MANUAL_REVIEW"
        return workspace, lane

    def test_primary_priority_trusts_the_pad(self, api):
        """PRD §3.7: "Under `PRIMARY_PRIORITY`, the first available source wins
        in this order: the pad reading if present and not flagged `INVALID`;
        then the rounded backup mean if both backups are present; then
        `backup1_cs`; then `backup2_cs`; then `watch_cs`."

        Design: Difficulty/dual_variant_calc/timing_reconciliation_primary_vs_backup_variants
        """
        _workspace, lane = self._setup(api)
        resp = api.resolve_lane(lane["id"], "PRIMARY_PRIORITY", TIMING)
        resolved = validate_success(resp)
        assert resolved["reconciliation_status"] == "RESOLVED"
        assert resolved["final_time_cs"] == 2500, \
            "PRIMARY_PRIORITY trusts the touchpad over the backup mean"
        assert resolved["reconciled_variant"] == "PRIMARY_PRIORITY"

    def test_backup_mean_priority_trusts_the_mean(self, api):
        """PRD §3.7: "Under `BACKUP_MEAN_PRIORITY`, the rounded backup mean
        leads — when both backups exist — followed by the pad reading if
        present and valid, then `backup1_cs`, `backup2_cs`, and finally
        `watch_cs`. Identical readings therefore yield a different
        `final_time_cs` under the two variants whenever the pad and the rounded
        backup mean disagree."
        PRD §3.7: "reopening a lane's timing returns it from `RESOLVED` or
        `AUTO_CONFIRMED` to `MANUAL_REVIEW`, clearing both `final_time_cs` and
        `reconciled_variant` to null".

        Design: Difficulty/dual_variant_calc/timing_reconciliation_primary_vs_backup_variants
        """
        workspace, lane = self._setup(api)
        referee_id = workspace["coverage"]["referee"]["id"]
        validate_success(api.resolve_lane(lane["id"], "PRIMARY_PRIORITY",
                                          TIMING))
        reopened = validate_success(api.reopen_timing(
            lane["id"], make_meet_referee_headers(referee_id)))
        assert reopened["reconciliation_status"] == "MANUAL_REVIEW"
        assert reopened.get("final_time_cs") is None
        resp = api.resolve_lane(lane["id"], "BACKUP_MEAN_PRIORITY", TIMING)
        resolved = validate_success(resp)
        assert resolved["reconciliation_status"] == "RESOLVED"
        assert resolved["final_time_cs"] == 2535, \
            "BACKUP_MEAN_PRIORITY yields the rounded mean (2530+2540)/2 = 2535"
        assert resolved["final_time_cs"] != 2500, \
            "the two variants disagree on identical readings"


class TestReopenTimingCycle:
    """Difficulty pair: the LaneAssignment reconciliation cycle with the
    lane_status parallel dimension untouched."""

    def _setup(self, api):
        workspace = setup_in_progress_event(meet_name="SM2")
        lane = workspace["lanes"][0]
        # mean (2510+2520)/2 = 2515, delta 15 <= 30 -> AUTO_CONFIRMED.
        resp = api.submit_readings(
            lane["id"], readings_payload(pad_cs=2500, backup1_cs=2510,
                                         backup2_cs=2520), TIMING)
        confirmed = validate_success(resp)
        assert confirmed["reconciliation_status"] == "AUTO_CONFIRMED"
        assert confirmed["final_time_cs"] == 2500
        return workspace, lane

    def test_reopen_clears_final_time_and_variant(self, api):
        """PRD §3.7: "reopening a lane's timing returns it from `RESOLVED` or
        `AUTO_CONFIRMED` to `MANUAL_REVIEW`, clearing both `final_time_cs` and
        `reconciled_variant` to null, and is lawful only while the event
        remains `IN_PROGRESS` (`ERR_EVENT_NOT_IN_PROGRESS`)."

        Design: Difficulty/non_linear_state_machine/lane_reconciliation_cycle_parallel_dims
        """
        workspace, lane = self._setup(api)
        referee_id = workspace["coverage"]["referee"]["id"]
        resp = api.reopen_timing(lane["id"],
                                 make_meet_referee_headers(referee_id))
        reopened = validate_success(resp)
        assert reopened["reconciliation_status"] == "MANUAL_REVIEW"
        assert reopened.get("final_time_cs") is None
        assert reopened.get("reconciled_variant") is None

    def test_cycle_preserves_lane_status_and_resolves_by_mean(self, api):
        """PRD §3.7: "Note that `lane_status` runs on a parallel dimension from
        `reconciliation_status`: a lane flips from `ACTIVE` to `VOIDED` on
        scratch, no-show, and withdrawal cascades, and returns from `VOIDED` to
        `ACTIVE` only through the seeded unscratch restore of §3.3."
        PRD §3.7: "Under `BACKUP_MEAN_PRIORITY`, the rounded backup mean leads
        — when both backups exist".

        Design: Difficulty/non_linear_state_machine/lane_reconciliation_cycle_parallel_dims
        """
        workspace, lane = self._setup(api)
        referee_id = workspace["coverage"]["referee"]["id"]
        validate_success(api.reopen_timing(
            lane["id"], make_meet_referee_headers(referee_id)))
        resp = api.resolve_lane(lane["id"], "BACKUP_MEAN_PRIORITY", TIMING)
        resolved = validate_success(resp)
        assert resolved["reconciliation_status"] == "RESOLVED"
        assert resolved["final_time_cs"] == 2515
        reread = get_success_data(api.get_lane_assignment(lane["id"], DIRECTOR))
        assert reread["lane_status"] == "ACTIVE", \
            "the reconciliation cycle never touches the parallel lane_status"
