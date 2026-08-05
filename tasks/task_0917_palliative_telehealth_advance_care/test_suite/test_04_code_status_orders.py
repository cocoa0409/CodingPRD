"""Goals of care: the code-status ladder and the document supersession chain."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId, assert_code_status_order, assert_same_instant
from test_helpers import factories as f
from test_helpers.fixtures import (
    PHYSICIAN,
    SOCIAL_WORKER,
    draft_code_status_order,
    effective_code_status_order,
    enroll_patient,
    executed_document,
    patient_version,
    read_patient,
    witnessed_document,
)


def _supersession_scenario():
    """Executed directive, its effective transcription, an in-flight draft and a
    successor directive that supersedes the first. Returns every id involved."""
    patient, _ = enroll_patient(
        clock="2026-06-01T00:00:00Z",
        full_name="Hana Bloomfield",
        jurisdiction_code="JUR_TWO_WITNESS",
    )
    first_document = executed_document(
        patient["id"], document_type="LIVING_WILL", stated_code_status="DNR"
    )
    effective_order = effective_code_status_order(
        patient["id"], "DNR", source_document_id=first_document["id"]
    )
    draft_order = draft_code_status_order(patient["id"], "DNR_DNI")
    second_document = witnessed_document(
        patient["id"],
        witnesses=2,
        document_type="LIVING_WILL",
        stated_code_status="COMFORT_MEASURES_ONLY",
        supersedes_document_id=first_document["id"],
    )
    return {
        "patient": patient,
        "first_document": first_document,
        "second_document": second_document,
        "effective_order": effective_order,
        "draft_order": draft_order,
    }


# ---------------------------------------------------------------------------
# The four-hop document execution cascade
# ---------------------------------------------------------------------------
def test_executing_a_successor_directive_supersedes_the_prior_document_and_its_order(api):
    """PRD 2.10: "**hop 1**, when the executed document's
    `supersedes_document_id` is non-null and the document it names is currently
    `EXECUTED`, that prior document moves to `SUPERSEDED`; **hop 2**, because that
    document was superseded, every code-status order whose `source_document_id`
    names it and whose `status` is `EFFECTIVE` moves to `SUPERSEDED`"
    PRD 3.3: "Executing stamps `executed_at` from the logical clock, sets
    `reattest_due_at` to exactly 365 days after `executed_at`, moves the document
    `PENDING_EXECUTION → EXECUTED`, and increments the patient's `version` by 1."

    Design: Difficulty/transitive_cascade/document_execution_drives_four_hop_supersession_chain
    """
    scenario = _supersession_scenario()
    patient_id = scenario["patient"]["id"]

    executed = validate_success(
        api.execute_document(
            scenario["second_document"]["id"],
            {"expected_patient_version": patient_version(patient_id)},
            PHYSICIAN,
        )
    )

    assert executed["status"] == "EXECUTED"
    assert_same_instant(
        executed["reattest_due_at"],
        "2027-06-01T00:00:00Z",
        "AdvanceCareDocument.reattest_due_at",
    )

    prior = validate_success(
        api.get_document(scenario["first_document"]["id"], SOCIAL_WORKER)
    )
    assert prior["status"] == "SUPERSEDED", (
        "the directive the new one replaces must move EXECUTED to SUPERSEDED"
    )

    transcription = validate_success(
        api.get_code_status_order(scenario["effective_order"]["id"], PHYSICIAN)
    )
    assert transcription["status"] == "SUPERSEDED", (
        "the order transcribing the superseded directive must follow it to SUPERSEDED"
    )


def test_supersession_rewrites_the_patient_code_status_and_parks_in_flight_orders(api):
    """PRD 2.10: "**hop 3**, because that order was superseded, the patient's
    `code_status` becomes the newly executed document's `stated_code_status` and
    `code_status_rank` is recomputed from it; **hop 4**, because the patient's
    `code_status` changed, every code-status order for this patient whose `status`
    is `DRAFT` or `ATTESTED` moves to `CONFLICT_HOLD`, since each of those orders
    captured a `prior_code_status` that is now stale."
    PRD 3.4: "Code status is modelled as a four-rung ladder running from most
    aggressive to least: `FULL_CODE` at rank 1, `DNR` at rank 2, `DNR_DNI` at rank
    3 and `COMFORT_MEASURES_ONLY` at rank 4."

    Design: Difficulty/transitive_cascade/document_execution_drives_four_hop_supersession_chain
    """
    scenario = _supersession_scenario()
    patient_id = scenario["patient"]["id"]

    before = read_patient(patient_id)
    assert before["code_status"] == "DNR"
    assert before["code_status_rank"] == 2

    validate_success(
        api.execute_document(
            scenario["second_document"]["id"],
            {"expected_patient_version": before["version"]},
            PHYSICIAN,
        )
    )

    after = read_patient(patient_id)
    assert after["code_status"] == "COMFORT_MEASURES_ONLY"
    assert after["code_status_rank"] == 4

    parked = validate_success(
        api.get_code_status_order(scenario["draft_order"]["id"], PHYSICIAN)
    )
    assert parked["status"] == "CONFLICT_HOLD", (
        "an in-flight DRAFT order must be parked once code_status moves underneath it"
    )


# ---------------------------------------------------------------------------
# The ladder rule
# ---------------------------------------------------------------------------
def test_a_two_rung_jump_is_refused_at_attestation(api):
    """PRD 3.4: "The absolute difference between the rank of
    `requested_code_status` and the rank of `prior_code_status` may be at most one
    rung, so `FULL_CODE` to `DNR` is allowed while `FULL_CODE` straight to
    `DNR_DNI` is refused with `ERR_CODE_STATUS_LADDER_VIOLATION`."
    PRD 3.4: "At creation the server captures `prior_code_status` from the
    patient's current `code_status` and derives `ladder_direction`:
    `DE_ESCALATION` when the requested rank is higher than the prior rank,
    `RE_ESCALATION` when it is lower, and `NO_CHANGE` when the two are equal. The
    order opens in `status` `DRAFT` with `attestation_count` 0."

    Design: Corner/validations/code_status_two_rung_jump_returns_ladder_violation
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Cleo Bergman")

    order = validate_success(
        api.create_code_status_order(
            f.code_status_order_payload(patient["id"], "DNR_DNI"), PHYSICIAN
        ),
        201,
    )
    assert_code_status_order(order)
    assert order["prior_code_status"] == "FULL_CODE"
    assert order["ladder_direction"] == "DE_ESCALATION"
    assert order["attestation_count"] == 0

    rejected = api.attest_code_status_order(
        order["id"],
        f.code_status_attestation_payload("CLINICIAN", attestation_text="goals discussed"),
        PHYSICIAN,
    )
    validate_error(rejected, ApiErrorId.ERR_CODE_STATUS_LADDER_VIOLATION.value, 422)

    unchanged = validate_success(api.get_code_status_order(order["id"], PHYSICIAN))
    assert unchanged["status"] == "DRAFT"
    assert unchanged["attestation_count"] == 0
    assert read_patient(patient["id"])["code_status"] == "FULL_CODE"


# ---------------------------------------------------------------------------
# The goals-conflict branch
# ---------------------------------------------------------------------------
def test_conflict_hold_needs_a_resolution_note_before_it_can_be_attested(api):
    """PRD 3.4: "It moves instead `DRAFT → CONFLICT_HOLD`, still setting
    `attestation_count` to 1, when all three of these hold: `surrogate_stated` is
    true, `patient_prior_statement` is non-null, and `patient_prior_statement`
    differs from `requested_code_status`."
    PRD 3.4: "An attestation against an order in `CONFLICT_HOLD` must carry a
    non-empty `conflict_resolution_note`; without one it is refused with
    `ERR_GOALS_CONFLICT`. With one, the note is stored, `attestation_count`
    increments by 1, and the order re-enters the main path as `CONFLICT_HOLD →
    ATTESTED`."

    Design: Corner/validations/conflict_hold_attestation_without_a_note_returns_goals_conflict
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Dara Whitfield")

    order = draft_code_status_order(
        patient["id"], "DNR", surrogate_stated=True, patient_prior_statement="FULL_CODE"
    )
    parked = validate_success(
        api.attest_code_status_order(
            order["id"],
            f.code_status_attestation_payload(
                "CLINICIAN", attestation_text="daughter states DNR"
            ),
            PHYSICIAN,
        )
    )
    assert parked["status"] == "CONFLICT_HOLD"
    assert parked["attestation_count"] == 1

    rejected = api.attest_code_status_order(
        order["id"],
        f.code_status_attestation_payload(
            "PATIENT_OR_SURROGATE", attestation_text="daughter re-affirms"
        ),
        SOCIAL_WORKER,
    )
    validate_error(rejected, ApiErrorId.ERR_GOALS_CONFLICT.value, 409)

    resolved = validate_success(
        api.attest_code_status_order(
            order["id"],
            f.code_status_attestation_payload(
                "PATIENT_OR_SURROGATE",
                attestation_text="daughter re-affirms",
                conflict_resolution_note=(
                    "ethics consult reconciled the prior statement with current wishes"
                ),
            ),
            SOCIAL_WORKER,
        )
    )
    assert resolved["status"] == "ATTESTED"
    assert resolved["conflict_resolution_note"], (
        "the supplied conflict_resolution_note must be stored on the order"
    )
    assert read_patient(patient["id"])["code_status"] == "FULL_CODE"
