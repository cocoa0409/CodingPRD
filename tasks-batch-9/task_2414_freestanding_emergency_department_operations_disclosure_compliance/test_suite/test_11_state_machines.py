"""Where each dimension starts, which edges exist, and which are refused outright.

The facility's posture ladder, the template's publication edge, the encounter's two
independent dimensions and the disclosure dimension's terminality are each exercised
once: a legal move with all of its side effects, or an illegal one with none of them.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_defect_count,
    assert_instant_equals,
    assert_ledger_entry,
    assert_posture,
    assert_total_count,
)
from test_helpers.factories import (
    make_ancillary_order_payload,
    make_complete_mse_payload,
    make_disclosure_decision_payload,
    make_discharge_payload,
    make_encounter_payload,
    make_observation_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    CLERK,
    OFFICER,
    PHYSICIAN,
    acknowledge_disclosure,
    attest_signage,
    begin_mse,
    create_facility,
    discharge,
    draft_template,
    ledger_entries,
    open_facility,
    publish_template,
    read_encounter,
    read_facility,
    register_encounter,
    screen_encounter,
    set_clock,
)
from test_helpers.test_users import ADMIN_USER_ID, CLERK_USER_ID, CO_USER_ID

WORKING_INSTANT = "2026-08-01T08:00:00Z"
ONE_YEAR_LATER_INSTANT = "2027-08-01T08:00:00Z"
NARROW_FACILITY = {
    "observation_bed_count": 2,
    "imaging_scope": ["XRAY", "CT"],
    "lab_scope": ["CBC", "TROPONIN"],
    "max_concurrent_physicians": 2,
}
SECOND_TEMPLATE_FEE_CENTS = 160000


def test_a_brand_new_facility_is_restricted_and_cannot_register_anyone():
    """No published disclosure means no patient may be quoted a fee.

    PRD 3.1: "A newly created facility is deliberately not yet open for business." and
    "Because signage is `PENDING` and no template is published, the very first posture
    computation lands on `RESTRICTED` with `restricted_service_codes` holding `MRI` and
    `THROMBOLYTIC`."  Registration is then refused by PRD 3.6's second gate: "And the
    facility must have a published disclosure to present: if
    `current_published_template_id` is null the attempt fails with
    `ERR_NO_PUBLISHED_DISCLOSURE`, because a patient cannot be quoted a fee that no
    adopted document states."

    Design: Corner/state_machines/new_facility_starts_restricted_until_template_and_signage_exist
    """
    set_clock(WORKING_INSTANT)
    facility = create_facility(ADMIN, **NARROW_FACILITY)

    assert_posture(facility, "RESTRICTED")
    assert facility["current_published_template_id"] is None
    assert facility["signage_attestation_status"] == "PENDING"

    validate_error(
        api_client.register_encounter(
            facility["id"],
            make_encounter_payload(
                patient_reference="PT-0701",
                acuity_level=2,
                presenting_service_line="GENERAL_MEDICAL",
            ),
            CLERK,
        ),
        ApiErrorId.ERR_NO_PUBLISHED_DISCLOSURE.value,
    )

    _, meta = validate_paginated(
        api_client.list_encounters(OFFICER, params={"facility_id": facility["id"]})
    )
    assert_total_count(meta, 0)


def test_publishing_a_second_template_retires_the_first_and_repoints_the_facility():
    """One publication moves three rows, and leaves the posture where it was.

    PRD 3.2: "On success the template moves `DRAFT → PUBLISHED`, `published_at` is stamped
    with the logical clock and `published_by_user_id` with the acting operator. The
    facility's previously published template — there is at most one — moves
    `PUBLISHED → RETIRED` in the same operation, with its own `updated_at` refreshed and
    its own `version` incremented by 1. The facility's `current_published_template_id` is
    rewritten to the newly published template's id, a ledger entry with `event_type`
    `TEMPLATE_PUBLISHED` is appended, the facility's `version` is incremented by 1, and the
    posture is recomputed".  The signage attestation is untouched by the second
    publication, so PRD 2.8's ladder still ends where it did: "otherwise the posture is
    `OPEN`".

    Design: Corner/state_machines/publishing_a_second_template_retires_the_first_and_repoints_the_facility
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)
    facility_id = context["facility_id"]
    first_template_id = context["template_id"]

    second = draft_template(
        facility_id,
        ADMIN,
        version_label="V2",
        facility_fee_cents=SECOND_TEMPLATE_FEE_CENTS,
        supersedes_version_label="V1",
    )
    published = publish_template(
        second["id"], read_facility(facility_id)["version"], ADMIN
    )

    assert published["status"] == "PUBLISHED"
    assert published["published_by_user_id"] == ADMIN_USER_ID
    assert_instant_equals(published["published_at"], WORKING_INSTANT, "published_at")

    retired = validate_success(
        api_client.get_disclosure_template(first_template_id, ADMIN)
    )
    assert retired["status"] == "RETIRED"

    facility = read_facility(facility_id)
    assert facility["current_published_template_id"] == second["id"]
    assert facility["signage_attestation_status"] == "ATTESTED"
    assert_posture(facility, "OPEN")

    assert_ledger_entry(
        ledger_entries(facility_id), "TEMPLATE_PUBLISHED", count=2
    )


def test_completing_the_screening_before_beginning_it_is_an_invalid_state():
    """`MSE_COMPLETE` has exactly one source state, and `ARRIVED` is not it.

    PRD 3.7: "Completing the screening moves the encounter
    `MSE_IN_PROGRESS → MSE_COMPLETE`, stamps `mse_completed_at`, and requires the physician
    to record a `stabilization_status` of either `STABLE` or `UNSTABLE`."  PRD 2.6 names the
    refusal: "An encounter's `clinical_state` must be a declared source state for the
    requested clinical transition and must not be terminal, else
    `ERR_INVALID_ENCOUNTER_STATE` (409). This catches beginning screening from anything
    other than `ARRIVED`, completing screening from anything other than `MSE_IN_PROGRESS`".
    The field it would have written stays where PRD 3.6 left it: "`stabilization_status`
    starts at `NOT_ASSESSED`."

    Design: Corner/state_machines/complete_mse_before_begin_mse_is_rejected_as_invalid_encounter_state
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)
    encounter = register_encounter(
        context["facility_id"],
        CLERK,
        patient_reference="PT-0801",
        acuity_level=2,
        presenting_service_line="GENERAL_MEDICAL",
    )
    acknowledge_disclosure(encounter["id"])

    validate_error(
        api_client.complete_mse(
            encounter["id"], make_complete_mse_payload("STABLE"), PHYSICIAN
        ),
        ApiErrorId.ERR_INVALID_ENCOUNTER_STATE.value,
    )

    unscreened = read_encounter(encounter["id"])
    assert unscreened["clinical_state"] == "ARRIVED"
    assert unscreened["mse_started_at"] is None
    assert unscreened["mse_completed_at"] is None
    assert unscreened["stabilization_status"] == "NOT_ASSESSED"


def test_a_discharged_encounter_refuses_a_second_discharge_an_admission_and_an_order():
    """Terminal on the clinical dimension means terminal for all three endpoints.

    PRD 2.6: "An encounter's `clinical_state` must be a declared source state for the
    requested clinical transition and must not be terminal, else
    `ERR_INVALID_ENCOUNTER_STATE` (409). This catches beginning screening from anything
    other than `ARRIVED`, completing screening from anything other than `MSE_IN_PROGRESS`,
    admitting to observation or discharging from `TRANSFER_PENDING`, `TRANSFERRED` or
    `DISCHARGED`, ordering a transfer from `ARRIVED`, `MSE_IN_PROGRESS`, `TRANSFERRED` or
    `DISCHARGED` (transfer ordering *is* permitted from `MSE_COMPLETE`, `OBSERVATION` and
    `TRANSFER_PENDING`, the last of these being the supersede path), and ordering an
    ancillary service on an encounter that has already reached `TRANSFERRED` or
    `DISCHARGED`."  Nothing was held to release, because PRD 3.7 says "discharging from
    `MSE_COMPLETE` releases nothing because nothing was held".

    Design: Corner/state_machines/terminal_discharged_encounter_rejects_further_orders_and_dispositions
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)
    encounter = register_encounter(
        context["facility_id"],
        CLERK,
        patient_reference="PT-0901",
        acuity_level=2,
        presenting_service_line="GENERAL_MEDICAL",
    )
    acknowledge_disclosure(encounter["id"])
    screen_encounter(encounter["id"], "STABLE")
    discharge(encounter["id"])

    for response in (
        api_client.discharge_encounter(
            encounter["id"], make_discharge_payload(discharge_instructions_ack=True), PHYSICIAN
        ),
        api_client.admit_to_observation(
            encounter["id"], make_observation_payload(), PHYSICIAN
        ),
        api_client.create_ancillary_order(
            encounter["id"],
            make_ancillary_order_payload("IMAGING", "CT", 1),
            PHYSICIAN,
        ),
    ):
        validate_error(response, ApiErrorId.ERR_INVALID_ENCOUNTER_STATE.value)

    closed = read_encounter(encounter["id"])
    assert closed["clinical_state"] == "DISCHARGED"
    assert closed["observation_bed_held"] is False
    assert read_facility(context["facility_id"])["observation_beds_occupied"] == 0

    _, meta = validate_paginated(
        api_client.list_ancillary_orders(encounter["id"], PHYSICIAN)
    )
    assert_total_count(meta, 0)


def test_recording_the_same_disclosure_decision_twice_is_refused_the_second_time():
    """The decision is not idempotent, and the second call appends no second entry.

    PRD 3.6: "What the transition does require is that `disclosure_state` is still
    `DISCLOSURE_PRESENTED`; a second decision on the same encounter is rejected with
    `ERR_DISCLOSURE_DECISION_ALREADY_RECORDED`." and "In all three outcomes the acting
    operator is recorded as `disclosure_decided_by_user_id`".  The first decision's own
    effect is PRD 3.6's clean path: "It appends an informational ledger entry with
    `event_type` `DISCLOSURE_ACKNOWLEDGED` and `defect_counted` false, and leaves the
    posture untouched."

    Design: Corner/state_machines/second_disclosure_decision_is_rejected_as_already_recorded
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)
    encounter = register_encounter(
        context["facility_id"],
        CLERK,
        patient_reference="PT-1001",
        acuity_level=2,
        presenting_service_line="GENERAL_MEDICAL",
    )
    acknowledge_disclosure(encounter["id"])

    validate_error(
        api_client.record_disclosure_decision(
            encounter["id"], make_disclosure_decision_payload("ACKNOWLEDGED"), CLERK
        ),
        ApiErrorId.ERR_DISCLOSURE_DECISION_ALREADY_RECORDED.value,
    )

    decided = read_encounter(encounter["id"])
    assert decided["disclosure_state"] == "DISCLOSURE_ACKNOWLEDGED"
    assert decided["disclosure_decided_by_user_id"] == CLERK_USER_ID

    entries = ledger_entries(context["facility_id"])
    assert_ledger_entry(
        entries, "DISCLOSURE_ACKNOWLEDGED", defect_counted=False, count=1
    )
    assert_defect_count(read_facility(context["facility_id"]), 0)


def test_an_unstable_patient_may_never_be_discharged():
    """The hardest clinical prohibition in the system, and the encounter does not move.

    PRD 3.7: "Discharge is available from two source states, `MSE_COMPLETE → DISCHARGED`
    and `OBSERVATION → DISCHARGED`, accepts an optional `discharge_instructions_ack`, and
    carries the system's hardest clinical prohibition: `stabilization_status` must be
    `STABLE`. An `UNSTABLE` patient may never be discharged, only transferred, and the
    attempt is rejected with `ERR_STABILIZATION_REQUIRED`."  Because the disposition never
    landed, PRD 3.6's system-fired defect cannot fire either: it is triggered "at the
    moment a clinical disposition lands — when `clinical_state` reaches `TRANSFERRED` or
    `DISCHARGED`".

    Design: Corner/state_machines/discharge_of_an_unstable_patient_is_rejected_by_the_stabilization_precondition
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)
    encounter = register_encounter(
        context["facility_id"],
        CLERK,
        patient_reference="PT-1101",
        acuity_level=5,
        presenting_service_line="CARDIAC",
    )
    acknowledge_disclosure(encounter["id"])
    screen_encounter(encounter["id"], "UNSTABLE")

    validate_error(
        api_client.discharge_encounter(
            encounter["id"], make_discharge_payload(discharge_instructions_ack=True), PHYSICIAN
        ),
        ApiErrorId.ERR_STABILIZATION_REQUIRED.value,
    )

    held = read_encounter(encounter["id"])
    assert held["clinical_state"] == "MSE_COMPLETE"
    assert held["stabilization_status"] == "UNSTABLE"
    assert held["disclosure_state"] == "DISCLOSURE_ACKNOWLEDGED"
    assert_defect_count(read_facility(context["facility_id"]), 0)


def test_filing_the_signage_attestation_stamps_an_expiry_one_year_out_and_opens_the_facility():
    """Every declared side effect of the attestation lands in the one response.

    PRD 3.1: "An accepted attestation sets `signage_attestation_status` to `ATTESTED`,
    stamps `signage_attested_at` with the logical clock, computes `signage_expires_at` as
    that instant plus one year of validity (365 days), and records the acting operator as
    `signage_attested_by_user_id`." and "The attestation then appends a ledger entry with
    `event_type` `SIGNAGE_ATTESTED`, `severity` `INFO` and `defect_counted` false,
    recomputes the posture and `restricted_service_codes` with the same cascade behaviour
    as a configuration update, and increments the facility's `version` by 1."  The
    recomputed posture is visible in that same response, because PRD 2.8 says of the
    posture that "It is recomputed synchronously at the end of every facility-scoped
    mutation — facility creation, facility configuration update, a signage attestation, a
    template publication, and every side effect anywhere in the system that changes the
    facility's `open_compliance_defect_count`".

    Design: Corner/state_machines/signage_attestation_stamps_attested_at_and_expiry_three_hundred_sixty_five_days_later
    """
    set_clock(WORKING_INSTANT)
    facility = create_facility(ADMIN, **NARROW_FACILITY)
    template = draft_template(facility["id"], ADMIN)
    publish_template(template["id"], facility["version"], ADMIN)

    attested = attest_signage(
        facility["id"], OFFICER, attestation_note="quarterly walk-through"
    )

    assert attested["signage_attestation_status"] == "ATTESTED"
    assert attested["signage_attested_by_user_id"] == CO_USER_ID
    assert_instant_equals(
        attested["signage_attested_at"], WORKING_INSTANT, "signage_attested_at"
    )
    assert_instant_equals(
        attested["signage_expires_at"], ONE_YEAR_LATER_INSTANT, "signage_expires_at"
    )
    assert_posture(attested, "OPEN")

    assert_ledger_entry(
        ledger_entries(facility["id"]),
        "SIGNAGE_ATTESTED",
        severity="INFO",
        defect_counted=False,
        count=1,
    )


def test_discharging_a_patient_who_never_answered_the_disclosure_records_a_defect():
    """The fifth disclosure outcome, which no client ever requests.

    PRD 3.6: "`DISCLOSURE_PRESENTED → DISCLOSURE_DEFECT` is fired by the system at the
    moment a clinical disposition lands — when `clinical_state` reaches `TRANSFERRED` or
    `DISCHARGED` — while `disclosure_state` is still `DISCLOSURE_PRESENTED`." and "It
    appends a ledger entry with `event_type` `DISCLOSURE_DEFECT`, `severity` `MAJOR`,
    `subject_type` `ENCOUNTER`, `subject_id` the encounter's id and `defect_counted` true,
    increments `open_compliance_defect_count` by 1, and runs the same posture recomputation
    cascade as a refusal."  One defect is below the bar PRD 2.8 sets — "The defect threshold
    is inclusive — a count of exactly 3 restricts the facility, a count of 2 does not." — so
    the posture holds at `OPEN`.

    Design: Corner/state_machines/discharge_without_a_recorded_disclosure_decision_flips_the_disclosure_dimension_to_defect
    """
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=NARROW_FACILITY)
    encounter = register_encounter(
        context["facility_id"],
        CLERK,
        patient_reference="PT-1201",
        acuity_level=2,
        presenting_service_line="GENERAL_MEDICAL",
    )
    begin_mse(encounter["id"])
    screened = validate_success(
        api_client.complete_mse(
            encounter["id"], make_complete_mse_payload("STABLE"), PHYSICIAN
        )
    )
    assert screened["disclosure_state"] == "DISCLOSURE_PRESENTED"

    discharged = discharge(encounter["id"])

    assert discharged["clinical_state"] == "DISCHARGED"
    assert discharged["disclosure_state"] == "DISCLOSURE_DEFECT"

    facility = read_facility(context["facility_id"])
    assert_defect_count(facility, 1)
    assert_posture(facility, "OPEN")

    assert_ledger_entry(
        ledger_entries(context["facility_id"]),
        "DISCLOSURE_DEFECT",
        severity="MAJOR",
        subject_type="ENCOUNTER",
        subject_id=encounter["id"],
        defect_counted=True,
        count=1,
    )
