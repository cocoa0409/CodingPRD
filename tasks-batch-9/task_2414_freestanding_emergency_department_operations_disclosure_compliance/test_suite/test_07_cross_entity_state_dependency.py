"""Operations whose legality is decided entirely by a *different* entity's state.

An observation admission that is perfectly legal on the encounter's own dimension is
refused because of the facility's licence, and a dispute case that is perfectly legal
on its own terms is refused because of its parent claim's status.  Both are shown
twice: refused, then accepted, with the operated-on entity untouched in between.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_instant_equals, assert_posture
from test_helpers.constants import RESTRICTED_CODES_WHEN_SUSPENDED
from test_helpers.factories import make_dispute_case_payload, make_observation_payload
from test_helpers.fixtures import (
    ADMIN,
    CLERK,
    OFFICER,
    PAYER,
    PHYSICIAN,
    acknowledge_disclosure,
    add_resulted_line,
    adjudicate_claim,
    create_claim,
    create_payer_contract,
    discharge,
    open_facility,
    read_claim,
    read_encounter,
    read_facility,
    register_encounter,
    restore_licence,
    screen_encounter,
    suspend_facility,
)
from test_helpers.test_users import CO_USER_ID

WORKING_INSTANT = "2026-08-01T08:00:00Z"
CROSS_ENTITY_FACILITY = {
    "observation_bed_count": 2,
    "imaging_scope": ["XRAY", "CT"],
    "lab_scope": ["CBC", "TROPONIN"],
    "max_concurrent_physicians": 2,
}
OBSERVATION_PLAN = {"observation_plan_note": "serial troponins"}


def _screened_patient_at_a_suspended_facility():
    """A patient ready for observation, whose facility has just lost its licence."""
    context = open_facility(
        clock=WORKING_INSTANT, facility_overrides=CROSS_ENTITY_FACILITY
    )
    facility_id = context["facility_id"]
    encounter = register_encounter(
        facility_id,
        CLERK,
        patient_reference="PT-1101",
        acuity_level=2,
        presenting_service_line="GENERAL_MEDICAL",
    )
    acknowledge_disclosure(encounter["id"])
    screen_encounter(encounter["id"], "STABLE")
    suspended = suspend_facility(facility_id, read_facility(facility_id)["version"], ADMIN)
    context.update(
        {
            "encounter_id": encounter["id"],
            "facility": suspended,
            "facility_version": suspended["version"],
        }
    )
    return context


def test_observation_admission_is_refused_while_the_facility_licence_is_suspended():
    """The encounter is in the one state that permits the move, and it is still refused.

    PRD 3.7 lists the four preconditions together: "the encounter must be in
    `MSE_COMPLETE` (an attempt from `ARRIVED` or `MSE_IN_PROGRESS` is
    `ERR_MSE_NOT_COMPLETE`, and one from a terminal or transfer-pending state is
    `ERR_INVALID_ENCOUNTER_STATE`), `stabilization_status` must be anything other than
    `NOT_ASSESSED`, the facility's `compliance_posture` must not be `SUSPENDED`
    (otherwise `ERR_FACILITY_POSTURE_BLOCKED`)".  The licence drives the posture through
    PRD 2.8's first rung — "if `license_status` is `SUSPENDED`, the posture is
    `SUSPENDED`" — and PRD 2.8 also fixes the derived list: "When the posture is
    `SUSPENDED` the list is all eleven ancillary codes: `XRAY`, `CT`, `ULTRASOUND`,
    `MRI`, `CBC`, `CHEMISTRY`, `TROPONIN`, `BLOOD_CULTURE`, `ANALGESIC`, `ANTIBIOTIC`,
    `THROMBOLYTIC`."

    Design: Difficulty/cross_entity_state_dependency/observation_admission_blocked_by_suspended_facility_then_allowed_after_licence_restored
    """
    context = _screened_patient_at_a_suspended_facility()

    assert_posture(context["facility"], "SUSPENDED")
    assert sorted(context["facility"]["restricted_service_codes"]) == sorted(
        RESTRICTED_CODES_WHEN_SUSPENDED
    )

    validate_error(
        api_client.admit_to_observation(
            context["encounter_id"], make_observation_payload(**OBSERVATION_PLAN), PHYSICIAN
        ),
        ApiErrorId.ERR_FACILITY_POSTURE_BLOCKED.value,
    )

    encounter = read_encounter(context["encounter_id"])
    assert encounter["clinical_state"] == "MSE_COMPLETE"
    assert encounter["observation_bed_held"] is False
    assert encounter["observation_started_at"] is None
    assert read_facility(context["facility_id"])["observation_beds_occupied"] == 0


def test_restoring_the_licence_makes_the_identical_observation_admission_legal():
    """Nothing about the encounter changes; only the facility's licence does.

    PRD 2.8's ladder ends at "otherwise the posture is `OPEN`", and PRD 2.8 adds that
    "When the posture is `OPEN` the list is empty".  With the gate lifted the transition
    proceeds exactly as PRD 3.7 describes: "On success the encounter moves
    `MSE_COMPLETE → OBSERVATION`, `observation_bed_held` becomes true,
    `observation_started_at` is stamped with the logical clock on first entry into
    observation, the facility's `observation_beds_occupied` is recomputed upward by one,
    and the facility's `version` is incremented by 1."

    Design: Difficulty/cross_entity_state_dependency/observation_admission_blocked_by_suspended_facility_then_allowed_after_licence_restored
    """
    context = _screened_patient_at_a_suspended_facility()

    validate_error(
        api_client.admit_to_observation(
            context["encounter_id"], make_observation_payload(**OBSERVATION_PLAN), PHYSICIAN
        ),
        ApiErrorId.ERR_FACILITY_POSTURE_BLOCKED.value,
    )

    reopened = restore_licence(
        context["facility_id"], context["facility_version"], ADMIN
    )
    assert_posture(reopened, "OPEN")
    assert reopened["restricted_service_codes"] == []

    admitted = validate_success(
        api_client.admit_to_observation(
            context["encounter_id"], make_observation_payload(**OBSERVATION_PLAN), PHYSICIAN
        )
    )

    assert admitted["clinical_state"] == "OBSERVATION"
    assert admitted["observation_bed_held"] is True
    assert_instant_equals(
        admitted["observation_started_at"], WORKING_INSTANT, "observation_started_at"
    )
    assert read_facility(context["facility_id"])["observation_beds_occupied"] == 1


def _draft_claim_on_a_single_imaging_line():
    """A billable discharged encounter whose claim has not yet been adjudicated."""
    context = open_facility(
        clock=WORKING_INSTANT, facility_overrides=CROSS_ENTITY_FACILITY
    )
    facility_id = context["facility_id"]
    contract = create_payer_contract(
        facility_id,
        OFFICER,
        payer_name="Lone Star Health",
        network_status="OUT_OF_NETWORK",
        state_protection_regime="FEDERAL_NSA_ONLY",
    )
    encounter = register_encounter(
        facility_id,
        CLERK,
        patient_reference="PT-1201",
        acuity_level=3,
        presenting_service_line="CARDIAC",
    )
    acknowledge_disclosure(encounter["id"])
    screen_encounter(encounter["id"], "STABLE")
    add_resulted_line(encounter["id"], "IMAGING", "CT", 2)
    discharge(encounter["id"])
    claim = create_claim(encounter["id"], contract["id"], OFFICER)
    context.update(
        {
            "contract": contract,
            "encounter_id": encounter["id"],
            "claim": claim,
            "claim_id": claim["id"],
        }
    )
    return context


def test_a_dispute_case_cannot_be_opened_while_its_parent_claim_is_still_draft():
    """The dispute's own creation legality is a function of the claim's status alone.

    PRD 3.9: "A `ComplianceOfficer` opens a dispute case on a claim that is `ADJUDICATED`
    (otherwise `ERR_INVALID_CLAIM_STATE`) whose payer contract has `idr_eligible` true
    (otherwise `ERR_IDR_NOT_ELIGIBLE`), with an optional `dispute_note`."  The contract is
    eligible by PRD 3.3's rule — "`idr_eligible` is true exactly when `network_status` is
    `OUT_OF_NETWORK` **and** `state_protection_regime` is anything other than
    `STATE_EXEMPT_FSED`" — so the claim's own state is the only thing standing in the way.

    Design: Difficulty/cross_entity_state_dependency/dispute_case_creation_blocked_by_draft_claim_then_allowed_after_adjudication
    """
    context = _draft_claim_on_a_single_imaging_line()

    assert context["contract"]["idr_eligible"] is True
    assert context["claim"]["status"] == "DRAFT"

    validate_error(
        api_client.create_dispute_case(
            context["claim_id"],
            make_dispute_case_payload(dispute_note="too early - claim is still DRAFT"),
            OFFICER,
        ),
        ApiErrorId.ERR_INVALID_CLAIM_STATE.value,
    )

    assert read_claim(context["claim_id"])["status"] == "DRAFT"

    cases, meta = validate_paginated(
        api_client.list_dispute_cases(context["claim_id"], OFFICER)
    )
    assert cases == []
    assert meta["total_count"] == 0


def test_adjudicating_the_claim_opens_the_dispute_and_drives_the_claim_onward():
    """The successful creation reaches back and moves the parent entity too.

    PRD 3.9: "The case is created with `status` `OPEN_NEGOTIATION`, its `claim_id` naming
    the out-of-network claim under dispute, `round_index` 0, `initiated_by_user_id` set to
    the acting officer, and `last_offer_cents`, `last_counteroffer_cents`,
    `last_offer_by_user_id`, `idr_award_cents` and `awarded_at` all null; the claim moves
    `ADJUDICATED → NEGOTIATION` with `negotiation_rounds_used` 0."

    Design: Difficulty/cross_entity_state_dependency/dispute_case_creation_blocked_by_draft_claim_then_allowed_after_adjudication
    """
    context = _draft_claim_on_a_single_imaging_line()

    validate_error(
        api_client.create_dispute_case(
            context["claim_id"],
            make_dispute_case_payload(dispute_note="too early - claim is still DRAFT"),
            OFFICER,
        ),
        ApiErrorId.ERR_INVALID_CLAIM_STATE.value,
    )

    adjudicated = adjudicate_claim(context["claim_id"], PAYER)
    assert adjudicated["status"] == "ADJUDICATED"

    case = validate_success(
        api_client.create_dispute_case(
            context["claim_id"],
            make_dispute_case_payload(dispute_note="open negotiation"),
            OFFICER,
        ),
        expected_status=201,
    )

    assert case["status"] == "OPEN_NEGOTIATION"
    assert case["round_index"] == 0
    assert case["claim_id"] == context["claim_id"]
    assert case["initiated_by_user_id"] == CO_USER_ID
    assert case["last_offer_cents"] is None
    assert case["last_counteroffer_cents"] is None
    assert case["idr_award_cents"] is None
    assert case["awarded_at"] is None

    claim = read_claim(context["claim_id"])
    assert claim["status"] == "NEGOTIATION"
    assert claim["negotiation_rounds_used"] == 0

    cases, meta = validate_paginated(
        api_client.list_dispute_cases(context["claim_id"], OFFICER)
    )
    assert [row["id"] for row in cases] == [case["id"]]
    assert meta["total_count"] == 1
