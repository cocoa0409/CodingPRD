"""Non-linear progressions: parallel dimensions, the chase orbit and the rework loop.

Three shapes share this file. A fill cycle carries two dimensions that advance on
different triggers, so a backward-then-forward payer move leaves the physical
dimension untouched. The prescriber chase orbits between two states through a
single operation until its round counter saturates and escalation is the only way
out. The pouch roll forks on its mismatch count and loops back to the state it
occupied at creation, capped by a monotone counter that strands it in a
non-terminal dead end.
"""

from test_helpers import (
    PHARMACIST_ID,
    TECHNICIAN_ID,
    TECHNICIAN_ID_2,
    ApiErrorId,
    api_client,
    assert_cycle_state,
    assert_line_state,
    assert_patient_posture,
    assert_roll_state,
    decide_vacation,
    do_adjudicate,
    do_chase,
    do_escalate,
    do_generate_roll,
    do_image_roll,
    do_pack,
    do_rework,
    do_verify,
    line_by_prescription,
    metformin_payload,
    open_authorization,
    pharmacist_headers,
    pouch_by_index,
    prescription_payload,
    read_cycle,
    read_lines,
    read_memos,
    read_patient,
    read_pouches,
    read_prescription,
    read_roll,
    request_vacation,
    set_clock,
    setup_adjudicated_cycle,
    setup_draft_cycle,
    setup_rolled_cycle,
    validate_error,
)

BUILD_CLOCK = "2026-08-10T00:00:00Z"


# ----------------------------------------------------------------------
# Parallel dimensions: the payer move that leaves packaging alone
# ----------------------------------------------------------------------
def _amlodipine_payload(patient_id):
    """A generic morning tablet last dispensed 2026-08-04 for thirty days.

    By the 2026-08-15 cycle start only eleven of those thirty days have elapsed,
    so this line fails the payer's refill-too-soon edit while the metformin line
    clears it exactly at the threshold.
    """
    return prescription_payload(
        patient_id,
        drug_name="Amlodipine",
        ndc="00093-0817-01",
        strength="5mg",
        form="TABLET",
        copay_tier="GENERIC",
        dose_times=["MORNING"],
        days_supply_written=30,
        last_dispensed_date="2026-08-04",
        last_dispensed_days_supply=30,
    )


def _cycle_rejected_too_soon_with_a_payer_override():
    """A staged cycle plus an approved payer-override travel exception of seven days."""
    scenario = setup_draft_cycle(
        clock=BUILD_CLOCK,
        plan_overrides={"allows_payer_vacation_override": True},
        prescriptions=[
            lambda pid: metformin_payload(pid, dose_times=["MORNING", "BEDTIME"]),
            _amlodipine_payload,
        ],
        cycle_start_date="2026-08-15",
        day_supply_days=28,
    )
    scenario.vacation = request_vacation(
        scenario.patient_id,
        travel_start_date="2026-09-01",
        travel_end_date="2026-09-14",
        requested_extra_days=7,
    )
    scenario.vacation = decide_vacation(
        scenario.vacation["id"], "APPROVE_PAYER_OVERRIDE", 7
    )
    return scenario


class TestFillCycleDimensionsMoveIndependently:
    """The payer dimension walks backwards then forwards without moving packaging."""

    def test_override_readjudication_moves_only_the_payer_dimension(self):
        """Re-adjudicating a rejected cycle clears the payer dimension and leaves packaging.

        The packaging dimension moves from `DRAFT` to `LINES_ADJUDICATED`. The payer dimension resolves by counting held lines: if at least one line ended `HELD_TOO_SOON`, `insurance_status` becomes `REJECTED_TOO_SOON`; otherwise if at least one line ended `HELD_AUTH`, it becomes `EDITS_PENDING`; otherwise every line adjudicated and it becomes `CLEARED`. The cycle's `total_copay_cents` is recomputed, `insurance_status` becomes `CLEARED`, and `packaging_status` is not touched: it remains `LINES_ADJUDICATED`.

        Design: Difficulty/non_linear_state_machine/fill_cycle_insurance_and_packaging_dimensions_move_independently
        """
        scenario = _cycle_rejected_too_soon_with_a_payer_override()

        first = do_adjudicate(scenario.cycle_id)
        assert_cycle_state(
            first,
            packaging_status="LINES_ADJUDICATED",
            insurance_status="REJECTED_TOO_SOON",
        )

        second = do_adjudicate(
            scenario.cycle_id, vacation_exception_id=scenario.vacation["id"]
        )

        assert_cycle_state(
            second, packaging_status="LINES_ADJUDICATED", insurance_status="CLEARED"
        )
        assert second["approved_vacation_extra_days"] == 7, second
        assert second["vacation_exception_id"] == scenario.vacation["id"], second

    def test_line_that_already_adjudicated_is_not_dispensed_a_second_time(self):
        """The metformin line cleared on the first pass and is left alone on the second.

        Lines that were already `ADJUDICATED` on the first pass are **not** recomputed and their dispense is **not** stamped a second time. Then `days_dispensed_total` rises by the line's `days_supply_filled`, `refills_remaining` falls by 1 and `refills_consumed` rises by 1.

        Design: Difficulty/non_linear_state_machine/fill_cycle_insurance_and_packaging_dimensions_move_independently
        """
        scenario = _cycle_rejected_too_soon_with_a_payer_override()
        metformin_id = scenario.rx_named("Metformin ER")["id"]
        do_adjudicate(scenario.cycle_id)

        do_adjudicate(scenario.cycle_id, vacation_exception_id=scenario.vacation["id"])

        metformin = read_prescription(metformin_id)
        assert metformin["refills_remaining"] == 2, metformin
        assert metformin["days_dispensed_total"] == 28, metformin

    def test_held_line_is_recomputed_against_the_widened_allowance(self):
        """The held amlodipine line clears with an allowance widened by the travel days.

        On such a re-run the refill-too-soon edit is waived or satisfied for every line; each `HELD_TOO_SOON` line is recomputed — its `allowance_days` widening by `approved_vacation_extra_days` — becomes `ADJUDICATED` and stamps its dispense. Start with the smallest of three values: the plan's `max_day_supply_days`; the prescription's `days_supply_written` multiplied by one more than its `refills_remaining`; and the cycle's `day_supply_days` plus the line's `bridge_days_applied` plus the cycle's `approved_vacation_extra_days`. That exact value is then rounded half-up to whole cents and stored as `copay_cents`. The cycle's `total_copay_cents` is the sum of the already-rounded `copay_cents` over lines whose `line_status` is `ADJUDICATED` or `PACKED_OUT`.

        Design: Difficulty/non_linear_state_machine/fill_cycle_insurance_and_packaging_dimensions_move_independently
        """
        scenario = _cycle_rejected_too_soon_with_a_payer_override()
        amlodipine_id = scenario.rx_named("Amlodipine")["id"]
        do_adjudicate(scenario.cycle_id)

        cleared = do_adjudicate(
            scenario.cycle_id, vacation_exception_id=scenario.vacation["id"]
        )

        line = line_by_prescription(read_lines(scenario.cycle_id), amlodipine_id)
        assert_line_state(line, line_status="ADJUDICATED", hold_reason=None)
        assert line["allowance_days"] == 35, line
        assert line["copay_cents"] == 762, line
        assert cleared["total_copay_cents"] == 1524, cleared

    def test_roll_generation_moves_only_the_packaging_dimension(self):
        """Building the roll advances packaging while the payer dimension stays CLEARED.

        `insurance_status` is the payer dimension. It begins at `NOT_ADJUDICATED` and reaches one of `EDITS_PENDING`, `CLEARED` or `REJECTED_TOO_SOON`, with `CLEARED` as its terminal value. The cycle's `packaging_status` moves from `LINES_ADJUDICATED` to `ROLL_GENERATED` and its `version` increments. The set of slots the roll uses is the union of `dose_times` over the contributing lines' prescriptions.

        Design: Difficulty/non_linear_state_machine/fill_cycle_insurance_and_packaging_dimensions_move_independently
        """
        scenario = _cycle_rejected_too_soon_with_a_payer_override()
        do_adjudicate(scenario.cycle_id)
        do_adjudicate(scenario.cycle_id, vacation_exception_id=scenario.vacation["id"])

        roll = do_generate_roll(scenario.cycle_id, TECHNICIAN_ID)

        assert roll["pouch_count"] == 56, roll
        cycle = read_cycle(scenario.cycle_id)
        assert_cycle_state(
            cycle,
            packaging_status="ROLL_GENERATED",
            insurance_status="CLEARED",
            version=4,
        )


# ----------------------------------------------------------------------
# The chase orbit and its escalation exit
# ----------------------------------------------------------------------
def _levothyroxine_payload(patient_id):
    """A morning tablet written with no refills, so its line is held for authorization."""
    return prescription_payload(
        patient_id,
        drug_name="Levothyroxine",
        ndc="00074-4341-90",
        strength="75mcg",
        form="TABLET",
        copay_tier="GENERIC",
        dose_times=["MORNING"],
        days_supply_written=30,
        refills_authorized=0,
        last_dispensed_date="2026-07-18",
        last_dispensed_days_supply=30,
    )


def _open_chase_on_a_held_line():
    """An adjudicated cycle with one authorization hold and one open chase against it."""
    scenario = setup_adjudicated_cycle(
        clock=BUILD_CLOCK,
        prescriptions=[
            lambda pid: metformin_payload(pid, dose_times=["MORNING", "BEDTIME"]),
            _levothyroxine_payload,
        ],
        cycle_start_date="2026-08-15",
        day_supply_days=28,
    )
    scenario.authorization = open_authorization(
        scenario.rx_named("Levothyroxine")["id"], 2
    )
    return scenario


def _drive_chase_to_saturation(auth_id):
    """Orbit the request three times, advancing the clock past each response window."""
    rounds = []
    for due in ("2026-08-13T00:00:00Z", "2026-08-16T00:00:00Z", "2026-08-19T00:00:00Z"):
        set_clock(due)
        rounds.append(do_chase(auth_id))
        if due != "2026-08-19T00:00:00Z":
            rounds.append(do_chase(auth_id))
    return rounds


class TestRefillAuthorizationChaseLoop:
    """One operation drives both legs of the orbit; only escalation leaves it."""

    def test_chase_alternates_and_counts_only_the_silence_leg(self):
        """Five chases orbit SENT and NO_RESPONSE while chase_round rises only three times.

        The new request copies `prescriber_npi` from the prescription and starts with `status` `SENT`, `chase_round` 0, `escalation_level` 0, `first_sent_at` and `last_sent_at` both at the clock, `next_chase_due_at` at the clock advanced by 72 hours, `no_response_recorded_at` null, `approved_refills` null, `denial_reason` null and `version` 1. On success `status` becomes `NO_RESPONSE`, `chase_round` rises by 1 and `no_response_recorded_at` is set to the clock. From `NO_RESPONSE` it re-sends and restarts the window. There is no timing gate on this direction. `status` returns to `SENT`, `last_sent_at` is set to the clock, and `next_chase_due_at` is set to the clock advanced by 72 hours. The loop therefore alternates `SENT` to `NO_RESPONSE` to `SENT`, and `chase_round` rises only on the silence-recording direction.

        Design: Difficulty/non_linear_state_machine/refill_authorization_chase_loop_then_escalation_exit
        """
        scenario = _open_chase_on_a_held_line()
        auth = scenario.authorization
        assert auth["status"] == "SENT", auth
        assert auth["chase_round"] == 0, auth
        assert auth["next_chase_due_at"][:19] == "2026-08-13T00:00:00", auth

        first, second, third, fourth, fifth = _drive_chase_to_saturation(auth["id"])

        assert first["status"] == "NO_RESPONSE", first
        assert first["chase_round"] == 1, first
        assert second["status"] == "SENT", second
        assert second["chase_round"] == 1, second
        assert second["next_chase_due_at"][:19] == "2026-08-16T00:00:00", second
        assert third["status"] == "NO_RESPONSE", third
        assert third["chase_round"] == 2, third
        assert fourth["status"] == "SENT", fourth
        assert fourth["next_chase_due_at"][:19] == "2026-08-19T00:00:00", fourth
        assert fifth["status"] == "NO_RESPONSE", fifth
        assert fifth["chase_round"] == 3, fifth

    def test_escalation_is_the_only_exit_from_the_saturated_loop(self):
        """With chase_round at three the request escalates out of the orbit.

        Escalation is available only from `NO_RESPONSE`, otherwise `ERR_INVALID_AUTH_STATE`, and only once `chase_round` has reached 3, otherwise `ERR_ESCALATION_PREMATURE`. On success `status` becomes `ESCALATED` and `escalation_level` becomes 1. The request's `version` increments on either effect.

        Design: Difficulty/non_linear_state_machine/refill_authorization_chase_loop_then_escalation_exit
        """
        scenario = _open_chase_on_a_held_line()
        auth_id = scenario.authorization["id"]
        _drive_chase_to_saturation(auth_id)

        escalated = do_escalate(auth_id)

        assert escalated["status"] == "ESCALATED", escalated
        assert escalated["escalation_level"] == 1, escalated
        assert escalated["chase_round"] == 3, escalated
        assert escalated["version"] == 7, escalated

    def test_escalation_drops_the_held_line_and_clears_the_payer_dimension(self):
        """Escalating past the cycle start abandons the drug and clears the cycle.

        Escalation also has a conditional consequence for the held claim: if the clock date has reached the `cycle_start_date` of the cycle carrying the held line, that `HELD_AUTH` line becomes `EXCLUDED_HELD` with `hold_reason` `AUTH_ESCALATED` — the pharmacy gives up on the drug rather than delay the whole roll. When dropping the line leaves the cycle with no line whose `line_status` is `HELD_AUTH` or `HELD_TOO_SOON` and at least one line `ADJUDICATED`, the cycle's `insurance_status` moves from `EDITS_PENDING` to `CLEARED`, its `total_copay_cents` is recomputed over the `ADJUDICATED` lines and its `version` increments. Otherwise it becomes `HELD_AUTH` with `hold_reason` `NO_REFILLS_REMAINING` when the prescription's `refills_remaining` is zero, and that prescription simultaneously moves from `status` `ACTIVE` to `PENDING_AUTHORIZATION` with its `version` incremented.

        Design: Difficulty/non_linear_state_machine/refill_authorization_chase_loop_then_escalation_exit
        """
        scenario = _open_chase_on_a_held_line()
        held_rx_id = scenario.rx_named("Levothyroxine")["id"]
        assert_cycle_state(
            read_cycle(scenario.cycle_id), insurance_status="EDITS_PENDING"
        )
        _drive_chase_to_saturation(scenario.authorization["id"])

        do_escalate(scenario.authorization["id"])

        line = line_by_prescription(read_lines(scenario.cycle_id), held_rx_id)
        assert_line_state(
            line, line_status="EXCLUDED_HELD", hold_reason="AUTH_ESCALATED"
        )
        assert_cycle_state(read_cycle(scenario.cycle_id), insurance_status="CLEARED")
        assert read_prescription(held_rx_id)["status"] == "PENDING_AUTHORIZATION"


# ----------------------------------------------------------------------
# The rework loop and its monotone cap
# ----------------------------------------------------------------------
def _morning_only_roll():
    """A twenty-eight pouch roll, one morning tablet per pouch."""
    return setup_rolled_cycle(
        clock=BUILD_CLOCK,
        prescriptions=[metformin_payload],
        cycle_start_date="2026-08-15",
        day_supply_days=28,
    )


def _pack_image_and_fail_verification(roll_id):
    """One bench pass reading pouch 1 as empty, so verification quarantines the roll."""
    do_pack(roll_id, TECHNICIAN_ID)
    do_image_roll(
        roll_id, 95, [{"pouch_index": 1, "detected_pill_count": 0}], TECHNICIAN_ID_2
    )
    return do_verify(roll_id, PHARMACIST_ID)


class TestPouchRollReworkLoop:
    """Verification forks on the mismatch count; rework loops back to BUILT twice only."""

    def test_failed_verification_quarantines_and_rework_returns_the_roll_to_built(self):
        """A single mismatched pouch quarantines the roll, and rework rewinds it to BUILT.

        When it is one or more, the roll's `verification_status` becomes `FAILED_QUARANTINED` and the cycle's `packaging_status` moves **backwards** from `PACKED` to `ROLL_GENERATED`; in addition a credit memo is issued against the cycle with `reason` `FAILED_VERIFICATION`, `amount_cents` of 500, `status` `ISSUED` and `issued_at` at the clock, and the patient's `credit_balance_cents` rises by that amount as a goodwill gesture. On success `verification_status` returns to `BUILT`, `rework_count` rises by 1, and `packed_by_user_id`, `packed_at`, `verified_by_user_id` and `verified_at` are all cleared to null, which releases the segregation-of-duties constraint for the next pack attempt. Every pouch of the roll whose `verification_result` is not `VOID` resets to `PENDING` with `detected_pill_count`, `image_confidence_pct`, `imaged_by_user_id` and `imaged_at` cleared to null; a `VOID` pouch is left as it is. `mismatch_pouch_count` returns to 0 and the roll's `version` increments.

        Design: Difficulty/non_linear_state_machine/pouch_roll_rework_loop_saturates_at_two
        """
        scenario = _morning_only_roll()
        assert read_roll(scenario.roll_id)["pouch_count"] == 28

        quarantined = _pack_image_and_fail_verification(scenario.roll_id)
        assert_roll_state(
            quarantined,
            verification_status="FAILED_QUARANTINED",
            mismatch_pouch_count=1,
        )
        assert_cycle_state(
            read_cycle(scenario.cycle_id), packaging_status="ROLL_GENERATED"
        )

        reworked = do_rework(scenario.roll_id, PHARMACIST_ID)

        assert_roll_state(
            reworked,
            verification_status="BUILT",
            rework_count=1,
            mismatch_pouch_count=0,
        )
        assert reworked["packed_by_user_id"] is None, reworked
        assert reworked["verified_by_user_id"] is None, reworked
        assert reworked["pouch_count"] == 28, reworked
        first_pouch = pouch_by_index(read_pouches(scenario.roll_id), 1)
        assert first_pouch["verification_result"] == "PENDING", first_pouch

    def test_third_rework_is_refused_once_the_counter_reaches_two(self):
        """The loop can be re-entered but never rewound a third time.

        The roll's `verification_status` must be `FAILED_QUARANTINED`, otherwise `ERR_INVALID_ROLL_STATE`, and `rework_count` must be below 2, otherwise `ERR_REWORK_LIMIT_REACHED` — a roll may return to the bench at most twice. The **first** rule whose condition holds returns its error immediately; no later rule is evaluated, and no state change is applied.

        Design: Difficulty/non_linear_state_machine/pouch_roll_rework_loop_saturates_at_two
        """
        scenario = _morning_only_roll()
        _pack_image_and_fail_verification(scenario.roll_id)
        do_rework(scenario.roll_id, PHARMACIST_ID)
        _pack_image_and_fail_verification(scenario.roll_id)
        second = do_rework(scenario.roll_id, PHARMACIST_ID)
        assert_roll_state(second, verification_status="BUILT", rework_count=2)
        requarantined = _pack_image_and_fail_verification(scenario.roll_id)
        assert_roll_state(requarantined, verification_status="FAILED_QUARANTINED")

        response = api_client.rework_roll(scenario.roll_id, pharmacist_headers())

        validate_error(response, ApiErrorId.REWORK_LIMIT_REACHED)
        stranded = read_roll(scenario.roll_id)
        assert_roll_state(
            stranded, verification_status="FAILED_QUARANTINED", rework_count=2
        )

    def test_every_failed_verification_mints_its_own_goodwill_memo(self):
        """Three failed verifications leave three goodwill memos and a 1500 cent balance.

        Four reasons exist, and each is minted by exactly one event: `PARTIAL_REISSUE` when the untaken tail of a cycle is reissued, `COLD_CHAIN_EXCURSION` when a refrigerated parcel is returned after a temperature excursion, `ROUNDING_TRUEUP` when the provisional and final copays of a cycle differ, and `FAILED_VERIFICATION` as a goodwill gesture of 500 cents when a roll fails pack verification. A memo begins at `ISSUED`. The patient's `credit_balance_cents` is always the sum of `amount_cents` over that patient's memos whose `status` is `ISSUED`; issuing a memo raises it by the memo's `amount_cents`.

        Design: Difficulty/non_linear_state_machine/pouch_roll_rework_loop_saturates_at_two
        """
        scenario = _morning_only_roll()
        _pack_image_and_fail_verification(scenario.roll_id)
        do_rework(scenario.roll_id, PHARMACIST_ID)
        _pack_image_and_fail_verification(scenario.roll_id)
        do_rework(scenario.roll_id, PHARMACIST_ID)

        _pack_image_and_fail_verification(scenario.roll_id)

        memos = read_memos(scenario.patient_id)
        assert len(memos) == 3, memos
        for memo in memos:
            assert memo["reason"] == "FAILED_VERIFICATION", memo
            assert memo["amount_cents"] == 500, memo
            assert memo["status"] == "ISSUED", memo
            assert memo["cycle_id"] == scenario.cycle_id, memo
        assert_patient_posture(
            read_patient(scenario.patient_id), credit_balance_cents=1500
        )
