"""Operations on one cycle that hinge on state living on a sibling cycle, prescription or memo.

A prescription pushed into authorization by a later cycle blocks the earlier cycle's roll, and a
goodwill credit raised by one cycle can only be consumed by a different, later cycle.
"""

from test_helpers import (
    TECHNICIAN_ID,
    ApiErrorId,
    api_client,
    assert_cycle_state,
    assert_memo,
    assert_patient_posture,
    assert_roll_state,
    create_cycle,
    do_adjudicate,
    do_generate_roll,
    do_respond,
    get_success_data,
    metformin_payload,
    open_authorization,
    ops_headers,
    read_cycle,
    read_memos,
    read_patient,
    read_prescription,
    read_roll,
    setup_adjudicated_cycle,
    setup_quarantined_roll,
    technician_headers,
    validate_error,
    validate_paginated,
)


def _two_cycles_sharing_one_exhausted_prescription():
    """An adjudicated cycle plus a later cycle that consumed the prescription's last refill."""
    scenario = setup_adjudicated_cycle(
        clock="2026-08-10T00:00:00Z",
        prescriptions=[
            lambda patient_id: metformin_payload(patient_id, refills_authorized=1)
        ],
        cycle_start_date="2026-08-15",
        day_supply_days=28,
    )
    successor = create_cycle(scenario.patient_id, "2026-09-12", 28)
    do_adjudicate(successor["id"])
    return scenario, successor


def _quarantined_cycle_with_goodwill_credit():
    """A cycle whose failed verification left a 500-cent goodwill memo on the patient."""
    return setup_quarantined_roll(
        clock="2026-08-10T00:00:00Z",
        prescriptions=[metformin_payload],
        cycle_start_date="2026-08-15",
        day_supply_days=28,
        image_confidence_pct=95,
    )


class TestRollGenerationBlockedByAnotherCyclesAuthorizationHold:
    """Roll generation on a cleared cycle reads the prescription status a sibling cycle wrote."""

    def test_authorization_hold_written_by_the_later_cycle_blocks_the_earlier_roll(self):
        """A prescription pushed into authorization by a later cycle blocks the earlier cycle's roll.

        Otherwise it becomes `HELD_AUTH` with `hold_reason` `NO_REFILLS_REMAINING` when the
        prescription's `refills_remaining` is zero, and that prescription simultaneously moves from
        `status` `ACTIVE` to `PENDING_AUTHORIZATION` with its `version` incremented.
        The payer dimension resolves by counting held lines: if at least one line ended
        `HELD_TOO_SOON`, `insurance_status` becomes `REJECTED_TOO_SOON`; otherwise if at least one
        line ended `HELD_AUTH`, it becomes `EDITS_PENDING`; otherwise every line adjudicated and
        it becomes `CLEARED`.
        Its gates are evaluated in this order: the cycle's `packaging_status` must be
        `LINES_ADJUDICATED`, otherwise `ERR_INVALID_CYCLE_STATE`; `insurance_status` must not be
        `EDITS_PENDING`, otherwise `ERR_CYCLE_NOT_CLEARED`; at least one line must have
        `line_status` `ADJUDICATED` and `packable_route` `POUCH`, otherwise
        `ERR_NO_PACKABLE_LINES`; every line whose `line_status` is `ADJUDICATED` must reference a
        prescription whose `status` is `ACTIVE`, otherwise `ERR_RX_PENDING_AUTHORIZATION`; the
        segment the new roll would occupy must not collide with a live roll of the same patient
        under closed-inclusive semantics, otherwise `ERR_REISSUE_SEGMENT_OVERLAP`; and only then,
        if `insurance_status` is `REJECTED_TOO_SOON`, the request fails with
        `ERR_REFILL_TOO_SOON`.
        The **first** rule whose condition holds returns its error immediately; no later rule is
        evaluated, and no state change is applied.

        Design: Difficulty/cross_entity_state_dependency/roll_generation_blocked_by_another_cycles_authorization_hold
        """
        scenario, successor = _two_cycles_sharing_one_exhausted_prescription()
        assert (
            read_prescription(scenario.rx_id())["status"] == "PENDING_AUTHORIZATION"
        ), read_prescription(scenario.rx_id())
        assert_cycle_state(read_cycle(successor["id"]), insurance_status="EDITS_PENDING")
        assert_cycle_state(
            read_cycle(scenario.cycle_id),
            packaging_status="LINES_ADJUDICATED",
            insurance_status="CLEARED",
        )

        response = api_client.generate_roll(
            scenario.cycle_id, technician_headers(TECHNICIAN_ID)
        )

        validate_error(response, ApiErrorId.RX_PENDING_AUTHORIZATION)
        rolls, _ = validate_paginated(
            api_client.list_pouch_rolls(
                ops_headers(), {"cycle_id": scenario.cycle_id, "limit": 100}
            )
        )
        assert rolls == [], rolls
        assert_cycle_state(
            read_cycle(scenario.cycle_id),
            packaging_status="LINES_ADJUDICATED",
            insurance_status="CLEARED",
        )

    def test_prescriber_approval_on_the_shared_prescription_unblocks_the_earlier_roll(
        self,
    ):
        """Once the prescriber approves the shared prescription the earlier cycle rolls normally.

        Because the request was approved, the prescription moves from `PENDING_AUTHORIZATION` back
        to `ACTIVE` with both `refills_authorized` and `refills_remaining` raised by
        `approved_refills`.
        Its gates are evaluated in this order: the cycle's `packaging_status` must be
        `LINES_ADJUDICATED`, otherwise `ERR_INVALID_CYCLE_STATE`; `insurance_status` must not be
        `EDITS_PENDING`, otherwise `ERR_CYCLE_NOT_CLEARED`; at least one line must have
        `line_status` `ADJUDICATED` and `packable_route` `POUCH`, otherwise
        `ERR_NO_PACKABLE_LINES`; every line whose `line_status` is `ADJUDICATED` must reference a
        prescription whose `status` is `ACTIVE`, otherwise `ERR_RX_PENDING_AUTHORIZATION`; the
        segment the new roll would occupy must not collide with a live roll of the same patient
        under closed-inclusive semantics, otherwise `ERR_REISSUE_SEGMENT_OVERLAP`; and only then,
        if `insurance_status` is `REJECTED_TOO_SOON`, the request fails with
        `ERR_REFILL_TOO_SOON`.
        One pouch is produced for each distinct pairing of a calendar date with a slot such that at
        least one contributing line both covers that date, meaning the date is on or after that
        line's `line_start_date` and strictly before its `line_end_date`, and lists that slot in
        its prescription's `dose_times`.
        `PouchRoll.pouch_count` is the number of such pairs, counting only pouches whose
        `verification_result` is not `VOID`, and the cycle's `roll_pouch_count` is set to that same
        figure.
        The roll itself is created with `verification_status` `BUILT`, a stamped human-readable
        `roll_serial`, `segment_start_date` equal to the earliest `line_start_date` among
        contributing lines, and `segment_end_date` equal to the latest `line_end_date` among
        contributing lines moved back by one day — because `segment_end_date` is inclusive, it
        names the last date for which a pouch exists, whereas `line_end_date` is exclusive.
        The cycle's `packaging_status` moves from `LINES_ADJUDICATED` to `ROLL_GENERATED` and its
        `version` increments.

        Design: Difficulty/cross_entity_state_dependency/roll_generation_blocked_by_another_cycles_authorization_hold
        """
        scenario, successor = _two_cycles_sharing_one_exhausted_prescription()
        authorization = open_authorization(scenario.rx_id(), 2)
        do_respond(authorization["id"], "APPROVE", approved_refills=2)
        assert read_prescription(scenario.rx_id())["status"] == "ACTIVE"

        roll = do_generate_roll(scenario.cycle_id, TECHNICIAN_ID)

        assert roll["pouch_count"] == 28, roll
        assert roll["segment_start_date"] == "2026-08-15", roll
        assert roll["segment_end_date"] == "2026-09-11", roll
        assert_roll_state(roll, verification_status="BUILT")
        assert_cycle_state(
            read_cycle(scenario.cycle_id), packaging_status="ROLL_GENERATED"
        )


class TestIssuedCreditLandsOnADifferentLaterCycle:
    """A goodwill memo raised by one cycle is never consumed by that same cycle."""

    def test_memo_stays_issued_against_the_cycle_that_raised_it(self):
        """The goodwill credit stays outstanding and never offsets the cycle that produced it.

        When it is one or more, the roll's `verification_status` becomes `FAILED_QUARANTINED` and
        the cycle's `packaging_status` moves **backwards** from `PACKED` to `ROLL_GENERATED`; in
        addition a credit memo is issued against the cycle with `reason` `FAILED_VERIFICATION`,
        `amount_cents` of 500, `status` `ISSUED` and `issued_at` at the clock, and the patient's
        `credit_balance_cents` rises by that amount as a goodwill gesture.
        A memo begins at `ISSUED`.
        A memo whose `cycle_id` is this cycle is not applied to this cycle.

        Design: Difficulty/cross_entity_state_dependency/issued_credit_can_only_land_on_a_different_later_cycle
        """
        scenario = _quarantined_cycle_with_goodwill_credit()

        memos = read_memos(scenario.patient_id)

        assert len(memos) == 1, memos
        assert_memo(
            memos[0],
            reason="FAILED_VERIFICATION",
            amount_cents=500,
            status="ISSUED",
            cycle_id=scenario.cycle_id,
            applied_to_cycle_id=None,
        )
        assert_patient_posture(
            read_patient(scenario.patient_id), credit_balance_cents=500
        )
        cycle = read_cycle(scenario.cycle_id)
        assert cycle["credit_applied_cents"] == 0, cycle

    def test_a_later_cycle_of_the_same_patient_consumes_the_memo(self):
        """A different, later cycle of the same patient consumes the outstanding credit on adjudication.

        It reaches `APPLIED` when a **later** cycle of the same patient adjudicates: outstanding
        memos are consumed in ascending `created_at` order while the adjudicating cycle still has
        copay left to offset, and a memo whose `cycle_id` is the adjudicating cycle itself is never
        applied to that cycle.
        Applying a memo stamps its `applied_to_cycle_id` with the consuming cycle and its
        `applied_at` with the clock, raises that cycle's `credit_applied_cents` by the memo's
        `amount_cents`, and drops the patient's `credit_balance_cents` by the same amount.
        That exact value is then rounded half-up to whole cents and stored as `copay_cents`.
        The cycle's `total_copay_cents` is the sum of the already-rounded `copay_cents` over lines
        whose `line_status` is `ADJUDICATED` or `PACKED_OUT`.

        Design: Difficulty/cross_entity_state_dependency/issued_credit_can_only_land_on_a_different_later_cycle
        """
        scenario = _quarantined_cycle_with_goodwill_credit()
        memo_id = read_memos(scenario.patient_id)[0]["id"]
        successor = create_cycle(scenario.patient_id, "2026-09-12", 28)

        adjudicated = do_adjudicate(successor["id"])

        assert adjudicated["total_copay_cents"] == 762, adjudicated
        assert adjudicated["credit_applied_cents"] == 500, adjudicated
        memo = get_success_data(api_client.get_credit_memo(memo_id, ops_headers()))
        assert_memo(
            memo,
            reason="FAILED_VERIFICATION",
            amount_cents=500,
            status="APPLIED",
            cycle_id=scenario.cycle_id,
            applied_to_cycle_id=successor["id"],
        )
        assert memo["applied_at"].startswith("2026-08-10T00:00:00"), memo
        assert_patient_posture(read_patient(scenario.patient_id), credit_balance_cents=0)
        issuing_cycle = read_cycle(scenario.cycle_id)
        assert issuing_cycle["credit_applied_cents"] == 0, issuing_cycle

    def test_consuming_the_memo_leaves_the_quarantined_roll_untouched(self):
        """Consuming the credit on a later cycle repairs neither the quarantined roll nor its cycle.

        When it is one or more, the roll's `verification_status` becomes `FAILED_QUARANTINED` and
        the cycle's `packaging_status` moves **backwards** from `PACKED` to `ROLL_GENERATED`; in
        addition a credit memo is issued against the cycle with `reason` `FAILED_VERIFICATION`,
        `amount_cents` of 500, `status` `ISSUED` and `issued_at` at the clock, and the patient's
        `credit_balance_cents` rises by that amount as a goodwill gesture.
        Applying a memo stamps its `applied_to_cycle_id` with the consuming cycle and its
        `applied_at` with the clock, raises that cycle's `credit_applied_cents` by the memo's
        `amount_cents`, and drops the patient's `credit_balance_cents` by the same amount.

        Design: Difficulty/cross_entity_state_dependency/issued_credit_can_only_land_on_a_different_later_cycle
        """
        scenario = _quarantined_cycle_with_goodwill_credit()
        successor = create_cycle(scenario.patient_id, "2026-09-12", 28)

        do_adjudicate(successor["id"])

        assert_roll_state(
            read_roll(scenario.roll_id), verification_status="FAILED_QUARANTINED"
        )
        assert_cycle_state(
            read_cycle(scenario.cycle_id), packaging_status="ROLL_GENERATED"
        )
