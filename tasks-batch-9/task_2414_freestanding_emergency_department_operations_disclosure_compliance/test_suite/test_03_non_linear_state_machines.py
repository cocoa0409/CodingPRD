"""Two state machines that cycle rather than advance.

An encounter can walk observation to transfer-pending and back indefinitely, and a
dispute case can walk open-negotiation to offer-pending and back — but only three
times, because that loop carries an explicit termination condition.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_defect_count, assert_mou_unit_ledger
from test_helpers.factories import (
    make_offer_payload,
    make_transfer_decline_payload,
)
from test_helpers.fixtures import (
    CLERK,
    COORDINATOR,
    OFFICER,
    PAYER,
    PHYSICIAN,
    acknowledge_disclosure,
    adjudicate_claim,
    admit_to_observation,
    create_ambulance_mou,
    create_claim,
    create_dispute_case,
    create_transfer_agreement,
    create_transfer_order,
    discharge,
    negotiate_rounds,
    open_facility,
    protected_nsa_contract,
    read_ambulance_mou,
    read_claim,
    read_encounter,
    read_facility,
    register_encounter,
    screen_encounter,
)

CYCLE_FACILITY = {
    "observation_bed_count": 2,
    "imaging_scope": ["XRAY", "CT"],
    "lab_scope": ["CBC", "TROPONIN"],
}


def _observation_patient_with_a_live_transfer_order():
    """An acknowledged, screened patient in an observation bed with a REQUESTED order."""
    context = open_facility(facility_overrides=CYCLE_FACILITY)
    facility_id = context["facility_id"]
    agreement = create_transfer_agreement(
        facility_id,
        destination_hospital_name="Trinity Regional Hospital",
        service_line="CARDIAC",
        capability_tier=3,
        accepts_unstable=True,
    )
    mou = create_ambulance_mou(
        facility_id, carrier_name="Brazos EMS", level_of_care="CRITICAL_CARE", units_committed=2
    )
    encounter = register_encounter(
        facility_id,
        CLERK,
        patient_reference="PT-3001",
        acuity_level=4,
        presenting_service_line="CARDIAC",
    )
    acknowledge_disclosure(encounter["id"])
    screen_encounter(encounter["id"], "STABLE")
    in_observation = admit_to_observation(
        encounter["id"], PHYSICIAN, observation_plan_note="serial troponins"
    )
    order = create_transfer_order(
        encounter["id"], agreement["id"], mou["id"], in_observation["version"]
    )
    context.update(
        {
            "encounter_id": encounter["id"],
            "mou_id": mou["id"],
            "order_id": order["id"],
        }
    )
    return context


def test_declined_transfer_returns_the_patient_to_observation_with_the_bed_still_held():
    """The cycle closes back on OBSERVATION because the bed was never given up.

    PRD 3.8: "The encounter's `declined_transfer_count` is incremented by 1 and its
    `clinical_state` returns along one of two paths: `TRANSFER_PENDING → OBSERVATION`
    when `observation_bed_held` is true, and `TRANSFER_PENDING → MSE_COMPLETE` when
    it is false."  The bed survives the round trip because PRD 3.8 says
    "`observation_bed_held` and the facility's `observation_beds_occupied` are
    untouched while a transfer is pending", and PRD 3.8 adds that "Returning to
    observation performs **no** bed capacity re-check, because the bed was never
    released".  The order's round number follows PRD 3.8's rule that "Its
    `round_index` is 1 plus the number of `DECLINED` orders already on that
    encounter, so the first attempt is round 1".

    Design: Difficulty/non_linear_state_machine/encounter_observation_transfer_cycle_leaves_disclosure_dimension_untouched
    """
    context = _observation_patient_with_a_live_transfer_order()

    declined = validate_success(
        api_client.decline_transfer_order(
            context["order_id"], make_transfer_decline_payload("CAPACITY"), COORDINATOR
        )
    )

    assert declined["status"] == "DECLINED"
    assert declined["round_index"] == 1

    encounter = read_encounter(context["encounter_id"])
    assert encounter["clinical_state"] == "OBSERVATION"
    assert encounter["observation_bed_held"] is True
    assert encounter["declined_transfer_count"] == 1
    assert read_facility(context["facility_id"])["observation_beds_occupied"] == 1


def test_the_observation_transfer_cycle_leaves_the_disclosure_dimension_untouched():
    """A clinical round trip moves neither the disclosure state nor the defect count.

    PRD 3.6: "All four of `DISCLOSURE_ACKNOWLEDGED`, `DISCLOSURE_REFUSED`,
    `DISCLOSURE_WAIVED_EMERGENT` and `DISCLOSURE_DEFECT` are terminal for the
    disclosure dimension."  And PRD 3.8 keeps the compliance record clean for this
    decline reason: "Declines for `CAPACITY` or `CAPABILITY` append no
    defect-counted entry and leave the posture alone."  The released unit returns to
    the memorandum under PRD 2.10's rule that "`units_available` equals
    `units_committed` minus `units_reserved`".

    Design: Difficulty/non_linear_state_machine/encounter_observation_transfer_cycle_leaves_disclosure_dimension_untouched
    """
    context = _observation_patient_with_a_live_transfer_order()

    validate_success(
        api_client.decline_transfer_order(
            context["order_id"], make_transfer_decline_payload("CAPACITY"), COORDINATOR
        )
    )

    encounter = read_encounter(context["encounter_id"])
    assert encounter["disclosure_state"] == "DISCLOSURE_ACKNOWLEDGED"

    facility = read_facility(context["facility_id"])
    assert_defect_count(facility, 0)
    assert_mou_unit_ledger(read_ambulance_mou(context["mou_id"]), reserved=0, available=2)


def _dispute_case_on_a_facility_fee_only_claim():
    """An adjudicated 145000-cent claim with a freshly opened dispute case."""
    context = open_facility(facility_overrides=CYCLE_FACILITY)
    facility_id = context["facility_id"]
    contract = protected_nsa_contract(facility_id, OFFICER, payer_name="Lone Star Health")
    encounter = register_encounter(
        facility_id,
        CLERK,
        patient_reference="PT-4001",
        acuity_level=2,
        presenting_service_line="GENERAL_MEDICAL",
    )
    acknowledge_disclosure(encounter["id"])
    screen_encounter(encounter["id"], "STABLE")
    discharge(encounter["id"])
    claim = create_claim(encounter["id"], contract["id"])
    adjudicate_claim(claim["id"])
    case = create_dispute_case(claim["id"], OFFICER, dispute_note="facility fee only bundle")
    context.update({"claim_id": claim["id"], "case_id": case["id"], "case": case})
    return context


def test_round_index_advances_only_when_the_payer_answers_the_facility_offer():
    """The facility's offer parks the case; the payer's counteroffer closes the round.

    PRD 3.9: "A `ComplianceOfficer` submitting a facility offer requires the case to
    be in `OPEN_NEGOTIATION` and its `round_index` to be strictly below the
    three-round bound; it writes `last_offer_cents` and `last_offer_by_user_id`, and
    moves the case `OPEN_NEGOTIATION → OFFER_PENDING` **without** changing
    `round_index`."  The other half: "A round, in other words, is closed by the
    payer's answer, not by the facility's offer."

    Design: Difficulty/non_linear_state_machine/dispute_case_offer_counteroffer_cycle_bounded_at_three_rounds
    """
    context = _dispute_case_on_a_facility_fee_only_claim()
    assert context["case"]["status"] == "OPEN_NEGOTIATION"
    assert context["case"]["round_index"] == 0

    after_offer = validate_success(
        api_client.submit_offer(context["case_id"], make_offer_payload(240000), OFFICER)
    )
    assert after_offer["status"] == "OFFER_PENDING"
    assert after_offer["round_index"] == 0
    assert after_offer["last_offer_cents"] == 240000

    after_counteroffer = validate_success(
        api_client.submit_offer(context["case_id"], make_offer_payload(200000), PAYER)
    )
    assert after_counteroffer["status"] == "OPEN_NEGOTIATION"
    assert after_counteroffer["round_index"] == 1
    assert after_counteroffer["last_counteroffer_cents"] == 200000
    assert read_claim(context["claim_id"])["negotiation_rounds_used"] == 1


def test_a_fourth_facility_offer_is_refused_once_three_rounds_are_complete():
    """The negotiation cycle terminates rather than running forever.

    PRD 3.9: "a facility offer attempted when `round_index` has already reached 3 is
    `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`."  The three completed rounds each ended with
    the payer's answer, which per PRD 3.9 "increments `round_index` by 1, mirrors
    that value onto the claim's `negotiation_rounds_used`, and returns the case
    `OFFER_PENDING → OPEN_NEGOTIATION`", so the case is idle at round 3 when the
    fourth offer arrives.

    Design: Difficulty/non_linear_state_machine/dispute_case_offer_counteroffer_cycle_bounded_at_three_rounds
    """
    context = _dispute_case_on_a_facility_fee_only_claim()
    negotiate_rounds(
        context["case_id"], ((240000, 200000), (240000, 200000), (240000, 200000))
    )

    validate_error(
        api_client.submit_offer(context["case_id"], make_offer_payload(235000), OFFICER),
        ApiErrorId.ERR_NEGOTIATION_ROUNDS_EXHAUSTED.value,
    )

    case = validate_success(
        api_client.get_dispute_case(context["case_id"], OFFICER)
    )
    assert case["status"] == "OPEN_NEGOTIATION"
    assert case["round_index"] == 3
    assert case["last_offer_cents"] == 240000
    assert case["last_counteroffer_cents"] == 200000

    claim = read_claim(context["claim_id"])
    assert claim["negotiation_rounds_used"] == 3
    assert claim["status"] == "NEGOTIATION"
