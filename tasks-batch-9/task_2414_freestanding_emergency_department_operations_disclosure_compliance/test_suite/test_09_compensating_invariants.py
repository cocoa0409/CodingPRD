"""Three quantities that must survive a round trip exactly: money, units, beds.

Each pair does a thing and then does its compensating opposite, and checks that the
conserved quantity is back to the value it held before — to the cent, to the unit, to
the bed — rather than merely close to it.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_bed_conservation,
    assert_defect_count,
    assert_facility_unit_totals,
    assert_instant_equals,
    assert_ledger_entry,
    assert_money_conservation,
    assert_mou_unit_ledger,
    assert_posture,
    assert_pre_award_snapshots_equal,
    assert_pre_award_snapshots_null,
    assert_settlement,
    assert_unit_conservation,
)
from test_helpers.factories import (
    make_observation_payload,
    make_transfer_decline_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    CLERK,
    COORDINATOR,
    IDRE,
    PHYSICIAN,
    acknowledge_disclosure,
    admit_to_observation,
    award_dispute,
    create_ambulance_mou,
    create_transfer_agreement,
    create_transfer_order,
    discharge,
    idr_initiated_case,
    ledger_entries,
    open_facility,
    read_ambulance_mou,
    read_claim,
    read_encounter,
    read_facility,
    register_encounter,
    screen_encounter,
    withdraw_award,
)

WORKING_INSTANT = "2026-08-01T08:00:00Z"
NEGOTIATION_ROUNDS = ((240000, 200000), (235000, 205000), (230000, 210000))
AWARD_CENTS = 210000
PRE_AWARD_SETTLEMENT = {
    "allowed": 190000,
    "plan_paid": 112001,
    "patient_responsibility": 77999,
    "written_off": 92500,
}
TWO_BED_FACILITY = {
    "observation_bed_count": 2,
    "imaging_scope": ["XRAY", "CT"],
    "lab_scope": ["CBC", "TROPONIN"],
    "max_concurrent_physicians": 2,
}


def _awarded_claim():
    """The canonical billed bundle, negotiated to exhaustion and awarded 210000 cents."""
    context = idr_initiated_case(rounds=NEGOTIATION_ROUNDS)
    context["awarded_case"] = award_dispute(context["case_id"], AWARD_CENTS, IDRE)
    return context


def test_the_award_snapshots_the_four_settlement_figures_before_recomputing_them():
    """The pre-award figures are captured, not merely overwritten.

    PRD 3.9: "First the four current settlement figures are captured:
    `pre_award_allowed_cents` takes `allowed_amount_cents`, `pre_award_plan_paid_cents`
    takes `plan_paid_cents`, `pre_award_patient_responsibility_cents` takes
    `patient_responsibility_cents`, and `pre_award_written_off_cents` takes
    `written_off_cents`."  The recomputation at the awarded allowed total moves every one
    of them, and PRD 2.10 requires the books to balance afterwards: "For every claim, at
    every moment after adjudication — including after an award is applied and again after
    an award is withdrawn — `billed_total_cents` equals `plan_paid_cents` plus
    `patient_responsibility_cents` plus `written_off_cents`."

    Design: Difficulty/compensating_invariant/award_then_withdrawal_restores_every_claim_money_field_with_zero_drift
    """
    context = _awarded_claim()

    assert context["awarded_case"]["status"] == "AWARDED"
    assert context["awarded_case"]["idr_award_cents"] == AWARD_CENTS

    claim = read_claim(context["claim_id"])
    assert claim["status"] == "RESOLVED"
    assert claim["billed_total_cents"] == 282500
    assert_settlement(
        claim,
        allowed=AWARD_CENTS,
        plan_paid=127999,
        patient_responsibility=82001,
        balance_bill=0,
        written_off=72500,
    )
    assert_pre_award_snapshots_equal(claim, **PRE_AWARD_SETTLEMENT)
    assert_money_conservation(claim)


def test_withdrawing_the_award_restores_every_money_field_with_zero_rounding_drift():
    """The withdrawal replays the snapshots rather than recomputing anything.

    PRD 3.9: "On the claim, `allowed_amount_cents`, `plan_paid_cents`,
    `patient_responsibility_cents` and `written_off_cents` are restored from their
    corresponding `pre_award_*` snapshots — each field taking back exactly its pre-award
    value, with no recomputation and therefore no rounding drift — while
    `balance_bill_amount_cents` is recomputed as `billed_total_cents` less the restored
    `allowed_amount_cents` when `protection_variant` is `UNPROTECTED`, and 0 for both
    protected variants. All four `pre_award_*` fields are then cleared to null."  PRD 3.9
    also pins the two state moves and the ledger finding: "The case moves
    `AWARDED → WITHDRAWN`, which is terminal, and `idr_award_cents` and `awarded_at` are
    set back to null." and "a ledger entry with `event_type` `IDR_AWARD_WITHDRAWN`,
    `severity` `MINOR`, `subject_type` `CLAIM` and `defect_counted` false is appended."

    Design: Difficulty/compensating_invariant/award_then_withdrawal_restores_every_claim_money_field_with_zero_drift
    """
    context = _awarded_claim()

    withdrawn = withdraw_award(context["case_id"], IDRE)

    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["idr_award_cents"] is None
    assert withdrawn["awarded_at"] is None

    claim = read_claim(context["claim_id"])
    assert claim["status"] == "IDR_PENDING"
    assert_settlement(claim, balance_bill=0, **PRE_AWARD_SETTLEMENT)
    assert_pre_award_snapshots_null(claim)
    assert_money_conservation(claim)

    assert_ledger_entry(
        ledger_entries(context["facility_id"]),
        "IDR_AWARD_WITHDRAWN",
        severity="MINOR",
        subject_type="CLAIM",
        subject_id=context["claim_id"],
        defect_counted=False,
        count=1,
    )


def _superseded_transfer_order():
    """One committed ambulance unit, reserved by a second order that cancelled the first."""
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=TWO_BED_FACILITY)
    facility_id = context["facility_id"]
    first_agreement = create_transfer_agreement(
        facility_id,
        ADMIN,
        destination_hospital_name="Trinity Regional Hospital",
        service_line="CARDIAC",
        capability_tier=3,
        accepts_unstable=True,
    )
    second_agreement = create_transfer_agreement(
        facility_id,
        ADMIN,
        destination_hospital_name="Bluff Creek Medical Center",
        service_line="CARDIAC",
        capability_tier=4,
        accepts_unstable=True,
    )
    mou = create_ambulance_mou(
        facility_id,
        ADMIN,
        carrier_name="Brazos EMS",
        level_of_care="CRITICAL_CARE",
        units_committed=2,
    )
    encounter = register_encounter(
        facility_id,
        CLERK,
        patient_reference="PT-1301",
        acuity_level=4,
        presenting_service_line="CARDIAC",
    )
    acknowledge_disclosure(encounter["id"])
    screened = screen_encounter(encounter["id"], "STABLE")
    first_order = create_transfer_order(
        encounter["id"], first_agreement["id"], mou["id"], screened["version"]
    )
    pending = read_encounter(encounter["id"])
    second_order = create_transfer_order(
        encounter["id"], second_agreement["id"], mou["id"], pending["version"]
    )
    context.update(
        {
            "mou_id": mou["id"],
            "encounter_id": encounter["id"],
            "first_order_id": first_order["id"],
            "first_order": first_order,
            "second_order_id": second_order["id"],
            "second_order": second_order,
        }
    )
    return context


def test_superseding_a_transfer_order_moves_the_unit_without_creating_or_destroying_one():
    """Two orders exist, one unit is held, and the memorandum's books still balance.

    PRD 3.8: "When a new order is created on an encounter already in `TRANSFER_PENDING`,
    the previous `REQUESTED` or `ACCEPTED` order on that encounter transitions to
    `CANCELLED` and releases its reserved ambulance unit — the memorandum's
    `units_reserved` drops by one and its availability, `saturation_state` and the
    facility's totals are all recomputed — while the new order is created `REQUESTED` with
    `reserved_unit_count` 1. The encounter stays in `TRANSFER_PENDING`".  PRD 2.10 gives
    the arithmetic the pair of moves must respect: "`units_reserved` equals the number of
    transfer orders referencing that memorandum whose status is `REQUESTED` or `ACCEPTED`"
    and "Declined, cancelled and completed orders hold no units."

    Design: Difficulty/compensating_invariant/supersede_then_decline_conserves_every_committed_ambulance_unit
    """
    context = _superseded_transfer_order()

    cancelled = validate_success(
        api_client.get_transfer_order(context["first_order_id"], COORDINATOR)
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["reserved_unit_count"] == 0

    assert context["second_order"]["status"] == "REQUESTED"
    assert context["second_order"]["reserved_unit_count"] == 1
    assert context["second_order"]["round_index"] == 1

    mou = read_ambulance_mou(context["mou_id"])
    assert_mou_unit_ledger(mou, reserved=1, available=1)
    assert mou["saturation_state"] == "AVAILABLE"
    assert_unit_conservation([mou])

    facility = read_facility(context["facility_id"])
    assert_facility_unit_totals(facility, committed=2, reserved=1)
    assert read_encounter(context["encounter_id"])["clinical_state"] == "TRANSFER_PENDING"


def test_declining_the_surviving_order_returns_the_reserved_count_to_its_original_value():
    """Two reservations and two releases later, the reserved sum is exactly zero again.

    PRD 2.10: "a reservation followed by its compensating release — a decline, a supersede
    cancellation, or a completion — must return the reserved sum to exactly the value it
    held before the reservation."  The decline path is PRD 3.8's: "`reserved_unit_count`
    drops to 0; because the order has left the reserving statuses, the memorandum's
    `units_reserved` decreases by one and `units_available` is recomputed as
    `units_committed` less `units_reserved`".  This patient never held a bed, so the
    clinical return path is PRD 3.8's second one — "`TRANSFER_PENDING → MSE_COMPLETE` when
    it is false" — and PRD 3.8 keeps the compliance record clean because "Declines for
    `CAPACITY` or `CAPABILITY` append no defect-counted entry and leave the posture alone."

    Design: Difficulty/compensating_invariant/supersede_then_decline_conserves_every_committed_ambulance_unit
    """
    context = _superseded_transfer_order()

    declined = validate_success(
        api_client.decline_transfer_order(
            context["second_order_id"],
            make_transfer_decline_payload("CAPACITY"),
            COORDINATOR,
        )
    )
    assert declined["status"] == "DECLINED"
    assert declined["reserved_unit_count"] == 0

    mou = read_ambulance_mou(context["mou_id"])
    assert_mou_unit_ledger(mou, reserved=0, available=2)
    assert mou["saturation_state"] == "AVAILABLE"
    assert_unit_conservation([mou])

    facility = read_facility(context["facility_id"])
    assert_facility_unit_totals(facility, committed=2, reserved=0)
    assert facility["transfer_capacity_state"] == "AVAILABLE"
    assert_defect_count(facility, 0)
    assert_posture(facility, "OPEN")

    encounter = read_encounter(context["encounter_id"])
    assert encounter["clinical_state"] == "MSE_COMPLETE"
    assert encounter["observation_bed_held"] is False
    assert encounter["declined_transfer_count"] == 1


def _three_screened_patients_and_two_licensed_beds():
    """Both beds filled by the first two patients, with a third waiting."""
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=TWO_BED_FACILITY)
    facility_id = context["facility_id"]
    encounters = {}
    for label, reference in (("a", "PT-1401"), ("b", "PT-1402"), ("c", "PT-1403")):
        encounter = register_encounter(
            facility_id,
            CLERK,
            patient_reference=reference,
            acuity_level=2,
            presenting_service_line="GENERAL_MEDICAL",
        )
        acknowledge_disclosure(encounter["id"])
        screen_encounter(encounter["id"], "STABLE")
        encounters[label] = encounter["id"]
    admit_to_observation(
        encounters["a"], PHYSICIAN, observation_plan_note="serial troponins"
    )
    admit_to_observation(
        encounters["b"], PHYSICIAN, observation_plan_note="asthma reassessment"
    )
    context["encounters"] = encounters
    return context


def test_the_third_admission_is_refused_while_both_licensed_beds_are_occupied():
    """The count is a hard bound, not an advisory one.

    PRD 3.7 lists the capacity precondition alongside the others: "`observation_beds_occupied`
    must be strictly below `observation_bed_count` (otherwise
    `ERR_OBSERVATION_CAPACITY_EXCEEDED`)."  PRD 2.10 pins what the occupancy figure is:
    "A facility's `observation_beds_occupied` always equals the number of that facility's
    encounters whose `observation_bed_held` is true, counted regardless of `clinical_state`"
    and "The count always satisfies the bounds of at least 0 and at most
    `observation_bed_count`".

    Design: Difficulty/compensating_invariant/observation_admission_and_discharge_conserve_the_licensed_bed_count
    """
    context = _three_screened_patients_and_two_licensed_beds()
    encounters = context["encounters"]

    facility = read_facility(context["facility_id"])
    assert facility["observation_beds_occupied"] == 2
    assert facility["observation_bed_count"] == 2

    validate_error(
        api_client.admit_to_observation(
            encounters["c"],
            make_observation_payload(observation_plan_note="no bed available"),
            PHYSICIAN,
        ),
        ApiErrorId.ERR_OBSERVATION_CAPACITY_EXCEEDED.value,
    )

    third = read_encounter(encounters["c"])
    assert third["clinical_state"] == "MSE_COMPLETE"
    assert third["observation_bed_held"] is False
    assert_bed_conservation(
        read_facility(context["facility_id"]),
        [read_encounter(encounters[label]) for label in ("a", "b", "c")],
    )


def test_a_discharge_frees_exactly_one_bed_and_the_waiting_patient_takes_it():
    """The compensating release returns the count, and the freed bed is immediately usable.

    PRD 3.7: "Discharging from observation sets `observation_bed_held` to false and
    recomputes `observation_beds_occupied` downward by one; discharging from `MSE_COMPLETE`
    releases nothing because nothing was held."  PRD 2.10 states the round-trip
    requirement: "an admission paired with its compensating release (a discharge, or a
    transfer completion) returns the count to its pre-admission value."  The discharged
    patient keeps the stamp PRD 3.7 wrote on admission, because `observation_started_at`
    "is stamped with the logical clock on first entry into observation".

    Design: Difficulty/compensating_invariant/observation_admission_and_discharge_conserve_the_licensed_bed_count
    """
    context = _three_screened_patients_and_two_licensed_beds()
    encounters = context["encounters"]

    validate_error(
        api_client.admit_to_observation(
            encounters["c"],
            make_observation_payload(observation_plan_note="no bed available"),
            PHYSICIAN,
        ),
        ApiErrorId.ERR_OBSERVATION_CAPACITY_EXCEEDED.value,
    )

    released = discharge(encounters["a"], PHYSICIAN)
    assert released["clinical_state"] == "DISCHARGED"
    assert released["observation_bed_held"] is False
    assert_instant_equals(
        released["observation_started_at"], WORKING_INSTANT, "observation_started_at"
    )
    assert read_facility(context["facility_id"])["observation_beds_occupied"] == 1

    admitted = admit_to_observation(
        encounters["c"], PHYSICIAN, observation_plan_note="bed freed by the discharge"
    )
    assert admitted["clinical_state"] == "OBSERVATION"
    assert admitted["observation_bed_held"] is True
    assert_instant_equals(
        admitted["observation_started_at"], WORKING_INSTANT, "observation_started_at"
    )

    facility = read_facility(context["facility_id"])
    assert facility["observation_beds_occupied"] == 2
    assert_bed_conservation(
        facility, [read_encounter(encounters[label]) for label in ("a", "b", "c")]
    )
