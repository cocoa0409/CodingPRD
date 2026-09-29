"""The two adherence scores and the auto-ship pause gate.

Both groups drive the same endpoint — the dose-event batch — but read different
consequences out of it: the pair of disagreeing scores exposed by the adherence
summary, and the strict comparison the pause gate applies to the rolling score.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_patient_posture,
    dose_event,
    do_dose_events,
    fill_cycle_payload,
    get_success_data,
    metformin_payload,
    ops_headers,
    read_cycle_events,
    read_patient,
    read_roll,
    set_clock,
    setup_rolled_cycle,
    sitagliptin_payload,
    validate_error,
)

BUILD_CLOCK = "2026-08-10T00:00:00Z"


def _read_summary(patient_id):
    """The computed adherence summary for one patient."""
    return get_success_data(api_client.get_adherence_summary(patient_id, ops_headers()))


# ----------------------------------------------------------------------
# One event stream, two disagreeing denominators
# ----------------------------------------------------------------------
def _three_slot_rolled_cycle():
    """A 84-pouch roll over three dose slots, with the clock at 2026-08-22.

    Metformin covers MORNING and BEDTIME, Sitagliptin covers EVENING, so the
    2026-08-15 .. 2026-09-12 cycle produces three pouches a day. Seven of those
    twenty-eight days have elapsed once the clock reaches 2026-08-22.
    """
    scenario = setup_rolled_cycle(
        clock=BUILD_CLOCK,
        prescriptions=[
            lambda pid: metformin_payload(pid, dose_times=["MORNING", "BEDTIME"]),
            sitagliptin_payload,
        ],
        cycle_start_date="2026-08-15",
        day_supply_days=28,
    )
    set_clock("2026-08-22T00:00:00Z")
    return scenario


#: Twenty reported events over the first seven elapsed days: sixteen taken and
#: four missed. The twenty-first elapsed pouch, 2026-08-21 BEDTIME, is never
#: reported at all, which is what makes the two denominators disagree.
_THREE_SLOT_EVENTS = [
    dose_event("POUCH_TAKEN", "2026-08-15T08:00:00Z", "MORNING", 1),
    dose_event("POUCH_TAKEN", "2026-08-15T18:00:00Z", "EVENING", 2),
    dose_event("POUCH_TAKEN", "2026-08-15T21:00:00Z", "BEDTIME", 3),
    dose_event("POUCH_TAKEN", "2026-08-16T08:00:00Z", "MORNING", 4),
    dose_event("POUCH_TAKEN", "2026-08-16T18:00:00Z", "EVENING", 5),
    dose_event("POUCH_TAKEN", "2026-08-16T21:00:00Z", "BEDTIME", 6),
    dose_event("POUCH_TAKEN", "2026-08-17T08:00:00Z", "MORNING", 7),
    dose_event("POUCH_TAKEN", "2026-08-17T18:00:00Z", "EVENING", 8),
    dose_event("POUCH_MISSED", "2026-08-17T21:00:00Z", "BEDTIME", 9),
    dose_event("POUCH_TAKEN", "2026-08-18T08:00:00Z", "MORNING", 10),
    dose_event("POUCH_TAKEN", "2026-08-18T18:00:00Z", "EVENING", 11),
    dose_event("POUCH_MISSED", "2026-08-18T21:00:00Z", "BEDTIME", 12),
    dose_event("POUCH_TAKEN", "2026-08-19T08:00:00Z", "MORNING", 13),
    dose_event("POUCH_TAKEN", "2026-08-19T18:00:00Z", "EVENING", 14),
    dose_event("POUCH_MISSED", "2026-08-19T21:00:00Z", "BEDTIME", 15),
    dose_event("POUCH_TAKEN", "2026-08-20T08:00:00Z", "MORNING", 16),
    dose_event("POUCH_TAKEN", "2026-08-20T18:00:00Z", "EVENING", 17),
    dose_event("POUCH_MISSED", "2026-08-20T21:00:00Z", "BEDTIME", 18),
    dose_event("POUCH_TAKEN", "2026-08-21T08:00:00Z", "MORNING", 19),
    dose_event("POUCH_TAKEN", "2026-08-21T18:00:00Z", "EVENING", 20),
]


class TestRollingVersusCycleScopedScore:
    """One event stream, two denominators: reported events against elapsed pouches."""

    def test_rolling_score_divides_by_the_reported_events_only(self):
        """The rolling window score divides sixteen taken by the twenty reported events.

        The eligible events are those whose `cycle_id` belongs to a fill cycle of this patient, whose `event_type` is `POUCH_TAKEN` or `POUCH_MISSED`, and whose `occurred_at` falls inside that window; pickup and delivery events never enter the score. Count the taken events and the missed events. When the two counts sum to zero, `adherence_score_pct` is 100. Otherwise it is one hundred multiplied by the taken count, divided by the sum of the two counts, floored to a whole percent. `taken_count` and `missed_count` are the two window counts, and `expected_pouch_count` is the cycle-scoped denominator.

        Design: Difficulty/dual_variant_calc/adherence_rolling_window_vs_cycle_scoped_score
        """
        scenario = _three_slot_rolled_cycle()

        do_dose_events(
            scenario.patient_id, scenario.cycle_id, _THREE_SLOT_EVENTS, as_patient=True
        )

        summary = _read_summary(scenario.patient_id)
        assert summary["taken_count"] == 16, summary
        assert summary["missed_count"] == 4, summary
        assert summary["rolling_28_day_score_pct"] == 80, summary
        assert_patient_posture(read_patient(scenario.patient_id), adherence_score_pct=80)

    def test_cycle_scoped_score_divides_by_every_elapsed_pouch(self):
        """The cycle-scoped score counts the unreported elapsed pouch against the patient.

        Its denominator is the number of pouches across the patient's rolls whose `dose_date` is strictly before the clock date and whose `verification_result` is not `VOID` — that is, every pouch whose dose date has already passed, whether or not the patient reported anything about it. When that count is zero the cycle-scoped score is 100; otherwise it is one hundred multiplied by the same taken count, divided by that expected count, floored to a whole percent. The rolling score ignores elapsed pouches that produced no event at all, while the cycle-scoped score counts them against the patient, so the cycle-scoped figure is the more pessimistic of the two whenever a dose went unreported.

        Design: Difficulty/dual_variant_calc/adherence_rolling_window_vs_cycle_scoped_score
        """
        scenario = _three_slot_rolled_cycle()
        assert read_roll(scenario.roll_id)["pouch_count"] == 84

        do_dose_events(
            scenario.patient_id, scenario.cycle_id, _THREE_SLOT_EVENTS, as_patient=True
        )

        summary = _read_summary(scenario.patient_id)
        assert summary["expected_pouch_count"] == 21, summary
        assert summary["cycle_scoped_score_pct"] == 76, summary
        assert summary["rolling_28_day_score_pct"] == 80, summary
        assert summary["cycle_scoped_score_pct"] < summary["rolling_28_day_score_pct"]

    def test_rolling_score_of_eighty_leaves_the_patient_on_active_autoship(self):
        """Only the rolling score reaches the posture, and eighty is not below eighty.

        Only the rolling score is written to `adherence_score_pct` and only the rolling score can pause auto-ship. If `adherence_score_pct` is strictly below 80, the patient's `autoship_status` moves from `ACTIVE` to `PAUSED_ADHERENCE` with `pause_reason` `ADHERENCE_GAP`. A score exactly equal to 80 does not pause.

        Design: Difficulty/dual_variant_calc/adherence_rolling_window_vs_cycle_scoped_score
        """
        scenario = _three_slot_rolled_cycle()

        do_dose_events(
            scenario.patient_id, scenario.cycle_id, _THREE_SLOT_EVENTS, as_patient=True
        )

        patient = read_patient(scenario.patient_id)
        assert_patient_posture(
            patient,
            autoship_status="ACTIVE",
            pause_reason=None,
            adherence_score_pct=80,
        )
        summary = _read_summary(scenario.patient_id)
        assert summary["cycle_scoped_score_pct"] == 76, summary
        assert summary["autoship_status"] == "ACTIVE", summary

    def test_patient_reported_batch_returns_one_event_per_element(self):
        """A batch reported by the patient returns twenty PATIENT_REPORTED events.

        One immutable adherence event is created per element, each carrying only `id` and `created_at` beyond its own payload; `source` is `PATIENT_REPORTED` when `X-User-Role` is `Patient` and `SYSTEM_SCAN` otherwise.

        Design: Difficulty/dual_variant_calc/adherence_rolling_window_vs_cycle_scoped_score
        """
        scenario = _three_slot_rolled_cycle()

        created = do_dose_events(
            scenario.patient_id, scenario.cycle_id, _THREE_SLOT_EVENTS, as_patient=True
        )

        assert len(created) == 20, created
        for event in created:
            assert event["source"] == "PATIENT_REPORTED", event


# ----------------------------------------------------------------------
# The pause gate's strict comparison, probed on either side of 80
# ----------------------------------------------------------------------
def _morning_only_rolled_cycle():
    """A 28-pouch MORNING-only roll, with the clock advanced to 2026-09-05.

    The rolling window is then [2026-08-08, 2026-09-05), which contains every
    event the boundary batches report.
    """
    scenario = setup_rolled_cycle(
        clock=BUILD_CLOCK,
        prescriptions=[metformin_payload],
        cycle_start_date="2026-08-15",
        day_supply_days=28,
    )
    set_clock("2026-09-05T00:00:00Z")
    return scenario


#: Sixteen taken then four missed: floor(100 * 16 / 20) is exactly 80.
_BATCH_AT_EIGHTY = [
    dose_event("POUCH_TAKEN", "2026-08-%02dT08:00:00Z" % day, "MORNING", index)
    for index, day in enumerate(range(15, 31), start=1)
] + [
    dose_event("POUCH_MISSED", "2026-08-31T08:00:00Z", "MORNING", 17),
    dose_event("POUCH_MISSED", "2026-09-01T08:00:00Z", "MORNING", 18),
    dose_event("POUCH_MISSED", "2026-09-02T08:00:00Z", "MORNING", 19),
    dose_event("POUCH_MISSED", "2026-09-03T08:00:00Z", "MORNING", 20),
]

#: One more missed pouch takes the same sixteen taken to floor(100 * 16 / 21) = 76.
_BATCH_CROSSING_BELOW = [
    dose_event("POUCH_MISSED", "2026-09-04T08:00:00Z", "MORNING", 21),
]


class TestPauseGateBoundaryOnDoseEvents:
    """The score gate fires strictly below 80, probed at 80 and at 76."""

    def test_score_of_exactly_eighty_does_not_pause_autoship(self):
        """Sixteen taken out of twenty reported scores 80 and auto-ship stays ACTIVE.

        After every dose-event batch and after every adherence review, the auto-ship gate is evaluated, and the score gate is evaluated **first**. If `adherence_score_pct` is strictly below 80, the patient's `autoship_status` moves from `ACTIVE` to `PAUSED_ADHERENCE` with `pause_reason` `ADHERENCE_GAP`. A score exactly equal to 80 does not pause.

        Design: Difficulty/boundary_precision_check/adherence_pause_threshold_exact_boundary_on_dose_events
        """
        scenario = _morning_only_rolled_cycle()

        do_dose_events(
            scenario.patient_id, scenario.cycle_id, _BATCH_AT_EIGHTY, as_patient=True
        )

        patient = read_patient(scenario.patient_id)
        assert_patient_posture(
            patient,
            autoship_status="ACTIVE",
            pause_reason=None,
            adherence_score_pct=80,
            consecutive_missed_pickups=0,
        )

    def test_score_of_seventy_six_pauses_autoship_with_an_adherence_gap(self):
        """One further missed pouch drops the score to 76 and trips the score gate.

        Otherwise it is one hundred multiplied by the taken count, divided by the sum of the two counts, floored to a whole percent. If `adherence_score_pct` is strictly below 80, the patient's `autoship_status` moves from `ACTIVE` to `PAUSED_ADHERENCE` with `pause_reason` `ADHERENCE_GAP`. Otherwise, if `consecutive_missed_pickups` is greater than or equal to 2, `autoship_status` moves from `ACTIVE` to `PAUSED_ADHERENCE` with `pause_reason` `MISSED_PICKUPS`.

        Design: Difficulty/boundary_precision_check/adherence_pause_threshold_exact_boundary_on_dose_events
        """
        scenario = _morning_only_rolled_cycle()
        do_dose_events(
            scenario.patient_id, scenario.cycle_id, _BATCH_AT_EIGHTY, as_patient=True
        )

        do_dose_events(
            scenario.patient_id,
            scenario.cycle_id,
            _BATCH_CROSSING_BELOW,
            as_patient=True,
        )

        patient = read_patient(scenario.patient_id)
        assert_patient_posture(
            patient,
            autoship_status="PAUSED_ADHERENCE",
            pause_reason="ADHERENCE_GAP",
            adherence_score_pct=76,
            consecutive_missed_pickups=0,
        )

    def test_pause_from_the_score_gate_blocks_the_next_cycle(self):
        """A patient paused by the score gate can no longer open a fill cycle.

        The patient's `autoship_status` must be `ACTIVE`, otherwise `ERR_AUTOSHIP_PAUSED` — a paused or cancelled auto-ship blocks cycle creation outright.

        Design: Difficulty/boundary_precision_check/adherence_pause_threshold_exact_boundary_on_dose_events
        """
        scenario = _morning_only_rolled_cycle()
        do_dose_events(
            scenario.patient_id, scenario.cycle_id, _BATCH_AT_EIGHTY, as_patient=True
        )
        do_dose_events(
            scenario.patient_id,
            scenario.cycle_id,
            _BATCH_CROSSING_BELOW,
            as_patient=True,
        )

        response = api_client.create_fill_cycle(
            fill_cycle_payload(scenario.patient_id, "2026-10-15", 28), ops_headers()
        )

        validate_error(response, ApiErrorId.AUTOSHIP_PAUSED)

    def test_both_batches_survive_as_one_ordered_immutable_stream(self):
        """All twenty-one reported events remain readable in occurrence order.

        Events are never edited or deleted once written. Two reads order differently: the adherence-event stream of one fill cycle is returned in ascending `occurred_at` order with ascending `created_at` as tie-break, and pouches are returned in ascending `pouch_index` order.

        Design: Difficulty/boundary_precision_check/adherence_pause_threshold_exact_boundary_on_dose_events
        """
        scenario = _morning_only_rolled_cycle()
        do_dose_events(
            scenario.patient_id, scenario.cycle_id, _BATCH_AT_EIGHTY, as_patient=True
        )
        do_dose_events(
            scenario.patient_id,
            scenario.cycle_id,
            _BATCH_CROSSING_BELOW,
            as_patient=True,
        )

        events = read_cycle_events(scenario.cycle_id)

        assert len(events) == 21, events
        occurrences = [event["occurred_at"] for event in events]
        assert occurrences == sorted(occurrences), occurrences
