"""Exclusive operations, proved in pairs: the refusal and then the role that may.

A 403 on its own only shows a door is shut. Each test here shuts the door on one role and
then walks the correct role through it, so a blanket denial cannot pass for authorisation.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_mou_unit_ledger
from test_helpers.factories import (
    make_adjudicate_payload,
    make_begin_mse_payload,
    make_dispute_case_payload,
    make_transfer_decline_payload,
)
from test_helpers.fixtures import (
    CLERK,
    COORDINATOR,
    OFFICER,
    PAYER,
    PHYSICIAN,
    acknowledge_disclosure,
    closed_encounter_with_canonical_lines,
    create_claim,
    create_transfer_order,
    protected_nsa_contract,
    read_ambulance_mou,
    read_claim,
    read_encounter,
    register_encounter,
    transfer_ready_encounter,
)

WORKING_INSTANT = "2026-08-01T08:00:00Z"
NARROW_FACILITY = {
    "observation_bed_count": 2,
    "imaging_scope": ["XRAY", "CT"],
    "lab_scope": ["CBC", "TROPONIN"],
    "max_concurrent_physicians": 2,
}


def test_the_plan_adjudicates_and_the_facility_disputes_and_neither_may_do_the_other_s_job():
    """Two adjacent money operations, each exclusive to the other side of the table.

    PRD 3.9: "Adjudication belongs to the `PayerRepresentative`, accepts an optional
    `adjudication_note`, requires the claim to be in `DRAFT` (otherwise
    `ERR_INVALID_CLAIM_STATE`), re-checks that the payer contract is still `ACTIVE`
    (otherwise `ERR_PAYER_CONTRACT_NOT_ACTIVE`), and moves the claim `DRAFT → ADJUDICATED`."
    The dispute is the facility's move, not the plan's: "A `ComplianceOfficer` opens a dispute
    case on a claim that is `ADJUDICATED` (otherwise `ERR_INVALID_CLAIM_STATE`) whose payer
    contract has `idr_eligible` true (otherwise `ERR_IDR_NOT_ELIGIBLE`), with an optional
    `dispute_note`. The case is created with `status` `OPEN_NEGOTIATION`, its `claim_id`
    naming the out-of-network claim under dispute, `round_index` 0, `initiated_by_user_id` set
    to the acting officer, and `last_offer_cents`, `last_counteroffer_cents`,
    `last_offer_by_user_id`, `idr_award_cents` and `awarded_at` all null; the claim moves
    `ADJUDICATED → NEGOTIATION` with `negotiation_rounds_used` 0."  PRD 2.1 supplies the code
    for each refusal: "If both headers are well formed but the named role is not among the
    roles authorised for the endpoint being called, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/only_the_payer_representative_may_adjudicate_and_only_the_idr_entity_may_award
    """
    context = closed_encounter_with_canonical_lines(
        clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY
    )
    contract = protected_nsa_contract(context["facility_id"], OFFICER)
    claim = create_claim(context["encounter_id"], contract["id"], OFFICER)

    validate_error(
        api_client.adjudicate_claim(
            claim["id"], make_adjudicate_payload(adjudication_note="not my job"), OFFICER
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    assert read_claim(claim["id"])["status"] == "DRAFT"

    adjudicated = validate_success(
        api_client.adjudicate_claim(
            claim["id"],
            make_adjudicate_payload(adjudication_note="QPA recognised"),
            PAYER,
        )
    )
    assert adjudicated["status"] == "ADJUDICATED"

    validate_error(
        api_client.create_dispute_case(
            claim["id"],
            make_dispute_case_payload(dispute_note="open negotiation"),
            PAYER,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )

    case = validate_success(
        api_client.create_dispute_case(
            claim["id"],
            make_dispute_case_payload(dispute_note="open negotiation"),
            OFFICER,
        ),
        201,
    )
    assert case["status"] == "OPEN_NEGOTIATION"
    assert case["claim_id"] == claim["id"]
    assert read_claim(claim["id"])["status"] == "NEGOTIATION"


def test_the_coordinator_does_not_practise_medicine_and_the_physician_does_not_answer_for_the_hospital():
    """Two peer roles on the transfer path, and the one read they genuinely share.

    PRD 3.7: "The clinical dimension belongs to the `EmergencyPhysician`, and its first rule
    is a prohibition: no clinical transition anywhere in this system reads `disclosure_state`
    as a precondition."  The decline belongs to the receiving side: "POST |
    `/transfer-orders/{id}/decline` | Receiving hospital declines the transfer order,
    returning the encounter to its pre-transfer disposition and releasing the ambulance unit |
    `HospitalTransferCoordinator`", while the screening belongs to the clinical side: "POST |
    `/encounters/{id}/begin-mse` | Begin the medical screening examination and stamp its
    timeliness against the statutory deadline | `EmergencyPhysician`".  The read they share is
    declared for both: "GET | `/transfer-orders/{id}` | Read a single transfer order |
    `EmergencyPhysician`, `HospitalTransferCoordinator`, `ComplianceOfficer`,
    `FacilityAdministrator`".  Because the decline never ran, PRD 2.10's reservation
    identity still counts the order: "`units_reserved` equals the number of transfer orders
    referencing that memorandum whose status is `REQUESTED` or `ACCEPTED`".

    Design: Corner/rbac/clinical_and_transport_roles_cannot_cross_into_each_other_s_exclusive_operations
    """
    context = transfer_ready_encounter(
        clock=WORKING_INSTANT,
        acuity_level=4,
        service_line="CARDIAC",
        facility_overrides=NARROW_FACILITY,
    )
    order = create_transfer_order(
        context["encounter_id"],
        context["agreement_id"],
        context["mou_id"],
        context["encounter_version"],
    )
    waiting_patient = register_encounter(
        context["facility_id"],
        CLERK,
        patient_reference="PT-3801",
        acuity_level=2,
        presenting_service_line="GENERAL_MEDICAL",
    )
    acknowledge_disclosure(waiting_patient["id"])

    validate_error(
        api_client.begin_mse(
            waiting_patient["id"], make_begin_mse_payload(), COORDINATOR
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    assert read_encounter(waiting_patient["id"])["clinical_state"] == "ARRIVED"

    validate_error(
        api_client.decline_transfer_order(
            order["id"], make_transfer_decline_payload("CAPACITY"), PHYSICIAN
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )

    coordinator_read = validate_success(
        api_client.get_transfer_order(order["id"], COORDINATOR)
    )
    physician_read = validate_success(
        api_client.get_transfer_order(order["id"], PHYSICIAN)
    )
    assert coordinator_read["status"] == "REQUESTED"
    assert coordinator_read == physician_read

    assert_mou_unit_ledger(read_ambulance_mou(context["mou_id"]), reserved=1, available=1)
