"""Case and Contact state machines: cyclic loops, transitions, preconditions,
initial/terminal states, and side-effect transitions.

Queue A (Difficulty): non_linear_state_machine (case reopen loop, contact retry loop).
Queue B (Corner): state_machines section instances.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    make_investigator_headers,
    make_tracer_headers,
    make_intake_headers,
    make_epi_headers,
    ApiErrorId,
    create_case_payload,
)
from test_helpers import fixtures as fx


# ===========================================================================
# Queue A — non_linear_state_machine
# ===========================================================================
class TestCaseCyclicReopenLoop:
    """CLASSIFIED -> CLOSED -> REOPENED -> (re-interview) UNDER_INVESTIGATION, with
    classification reset to SUSPECT and interview_completed cleared then re-set."""

    def _closed_case(self):
        program, jurisdiction, _ = fx.setup_program_jurisdiction_condition(
            condition_overrides={"requires_lab_confirmation": False}
        )
        j = jurisdiction["id"]
        case = fx.open_interview_classify_case(
            program["id"], j, "PROBABLE", case_overrides={"patient_reference": "PT-C"}
        )
        validate_success(api_client.close_case(case["id"], make_investigator_headers(j)))
        return j, case["id"]

    def test_reopen_resets_classification_to_suspect(self, api):
        """PRD §3.4: "Reopening advances the case `CLOSED → REOPENED`, resets `classification`
        to `SUSPECT`, sets `interview_completed` back to false, clears `infectious_start_date`,
        `infectious_end_date`, and `isolation_end_date`, and recomputes the completeness score."

        Design: Difficulty/non_linear_state_machine/case_cyclic_reopen_loop
        """
        j, cid = self._closed_case()
        data = validate_success(api.reopen_case(cid, make_investigator_headers(j)))
        assert data["status"] == "REOPENED"
        assert data["classification"] == "SUSPECT"
        assert data["interview_completed"] is False

    def test_reinterview_from_reopened_returns_to_under_investigation(self, api):
        """PRD §3.3: "the case interview, which advances the case from `OPEN` to
        `UNDER_INVESTIGATION` (and likewise re-enters `UNDER_INVESTIGATION` from `REOPENED`
        on the revert loop described later)."
        PRD §3.4: "From `REOPENED` the case re-enters investigation through a fresh interview,
        recomputing the infectious window and completeness score exactly as the first interview did."

        Design: Difficulty/non_linear_state_machine/case_cyclic_reopen_loop
        """
        j, cid = self._closed_case()
        validate_success(api.reopen_case(cid, make_investigator_headers(j)))
        data = validate_success(api.interview_case(cid, {}, make_investigator_headers(j)))
        assert data["status"] == "UNDER_INVESTIGATION"
        assert data["classification"] == "SUSPECT"
        assert data["interview_completed"] is True


class TestContactNotificationFailedRetryLoop:
    """NOTIFICATION_PENDING -> (FAILED) NOTIFICATION_FAILED -> (queue) NOTIFICATION_PENDING
    -> (SUCCESS) NOTIFIED, with notification_attempts incrementing each record step."""

    def _pending_then_failed(self):
        program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
        j = jurisdiction["id"]
        ci = fx.open_and_interview_case(program["id"], j, case_overrides={"patient_reference": "PT-I"})
        kn = fx.elicit_contact(
            program["id"], ci["id"], j, contact_reference="K-N",
            exposure_setting="WORKPLACE", proximity_meters=1.5, cumulative_exposure_minutes=10,
        )
        validate_success(api_client.queue_notification(kn["id"], make_tracer_headers(j)))
        validate_success(
            api_client.record_notification(kn["id"], {"outcome": "FAILED"}, make_tracer_headers(j))
        )
        return j, kn["id"]

    def test_requeue_after_failed_returns_to_pending(self, api):
        """PRD §3.8: "a `FAILED` outcome advances `NOTIFICATION_PENDING → NOTIFICATION_FAILED`
        and likewise increments `notification_attempts` by one, after which the contact can be
        re-queued, looping back to `NOTIFICATION_PENDING`."

        Design: Difficulty/non_linear_state_machine/contact_notification_failed_retry_loop
        """
        j, kid = self._pending_then_failed()
        data = validate_success(api.queue_notification(kid, make_tracer_headers(j)))
        assert data["status"] == "NOTIFICATION_PENDING"

    def test_retry_success_reaches_notified_with_two_attempts(self, api):
        """PRD §3.8: "A `SUCCESS` outcome advances the contact `NOTIFICATION_PENDING → NOTIFIED`
        and increments `notification_attempts` by one; a `FAILED` outcome advances
        `NOTIFICATION_PENDING → NOTIFICATION_FAILED` and likewise increments
        `notification_attempts` by one, after which the contact can be re-queued, looping back
        to `NOTIFICATION_PENDING`."

        Design: Difficulty/non_linear_state_machine/contact_notification_failed_retry_loop
        """
        j, kid = self._pending_then_failed()
        validate_success(api.queue_notification(kid, make_tracer_headers(j)))
        data = validate_success(
            api.record_notification(kid, {"outcome": "SUCCESS"}, make_tracer_headers(j))
        )
        assert data["status"] == "NOTIFIED"
        assert data["notification_attempts"] == 2, data["notification_attempts"]


# ===========================================================================
# Queue B — state_machines section
# ===========================================================================
def test_interview_valid_transition_open_to_under_investigation(api):
    """PRD §3.3: "A successful interview sets `interview_completed` to true, computes the
    infectious window, and recomputes the completeness score."

    Design: Corner/state_machines/interview_valid_transition_open_to_under_investigation
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
    j = jurisdiction["id"]
    co = fx.open_case(program["id"], j, patient_reference="PT-O")
    data = validate_success(api.interview_case(co["id"], {}, make_investigator_headers(j)))
    assert data["status"] == "UNDER_INVESTIGATION"
    assert data["interview_completed"] is True


def test_classify_before_interview_returns_not_classifiable(api):
    """PRD §3.4: "Classification is legal only from `UNDER_INVESTIGATION`; attempting it from
    any other state is rejected with `ERR_CASE_NOT_CLASSIFIABLE`, and attempting it before the
    interview has run (that is, while `interview_completed` is false) is rejected with
    `ERR_INTERVIEW_NOT_COMPLETE`."

    Design: Corner/state_machines/classify_before_interview_returns_interview_not_complete
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition(
        condition_overrides={"requires_lab_confirmation": False}
    )
    j = jurisdiction["id"]
    co = fx.open_case(program["id"], j, patient_reference="PT-O")
    res = api.classify_case(co["id"], {"classification": "PROBABLE"}, make_investigator_headers(j))
    validate_error(res, ApiErrorId.ERR_CASE_NOT_CLASSIFIABLE.value)


def test_interview_no_onset_returns_onset_or_specimen_required(api):
    """PRD §3.3: "If the resulting `is_symptomatic` is true, a `symptom_onset_date` must be
    present; otherwise a `specimen_collection_date` must be present. Failing this requirement
    raises `ERR_ONSET_OR_SPECIMEN_REQUIRED`."

    Design: Corner/state_machines/interview_clears_no_onset_returns_onset_or_specimen_required
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
    j = jurisdiction["id"]
    res = api.create_case(
        create_case_payload(program["id"], j, patient_reference="PT-NO", symptom_onset_date=None,
                            is_symptomatic=True),
        make_investigator_headers(j),
    )
    cno = get_success_data(res)
    res2 = api.interview_case(cno["id"], {}, make_investigator_headers(j))
    validate_error(res2, ApiErrorId.ERR_ONSET_OR_SPECIMEN_REQUIRED.value)


def test_case_starts_in_open_initial_state(api):
    """PRD §3.3: "A new case begins in `OPEN` with `classification` `SUSPECT`,
    `completeness_score` 0, `contact_count` 0, and `linked_positive_count` 0."

    Design: Corner/state_machines/case_starts_in_open_initial_state
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
    j = jurisdiction["id"]
    res = api.create_case(
        create_case_payload(program["id"], j, patient_reference="PT-INIT"),
        make_investigator_headers(j),
    )
    data = validate_success(res, expected_status=201)
    assert data["status"] == "OPEN"
    assert data["classification"] == "SUSPECT"
    assert data["interview_completed"] is False


def test_contact_starts_in_elicited_initial_state(api):
    """PRD §3.6: "A newly elicited contact begins in `ELICITED`."
    PRD §3.7: "this STANDARD computation sets `quarantine_release_basis` to `STANDARD` and
    writes `quarantine_end_date`."

    Design: Corner/state_machines/contact_starts_in_elicited_initial_state
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
    j = jurisdiction["id"]
    ci = fx.open_and_interview_case(program["id"], j, case_overrides={"patient_reference": "PT-I"})
    res = api.create_contact(
        fx.create_contact_payload(program["id"], ci["id"], j, contact_reference="K-INIT"),
        make_tracer_headers(j),
    )
    data = validate_success(res, expected_status=201)
    assert data["status"] == "ELICITED"
    assert data["quarantine_release_basis"] == "STANDARD"
    assert data["notification_attempts"] == 0


def test_reopen_from_open_case_cannot_be_reopened(api):
    """PRD §3.4: "Reopen is legal only from `CLOSED`, rejected otherwise with
    `ERR_CASE_NOT_REOPENABLE`."

    Design: Corner/state_machines/reopen_from_open_case_cannot_be_reopened
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
    j = jurisdiction["id"]
    co = fx.open_case(program["id"], j, patient_reference="PT-O")
    res = api.reopen_case(co["id"], make_investigator_headers(j))
    validate_error(res, ApiErrorId.ERR_CASE_NOT_REOPENABLE.value)


def test_start_monitoring_from_elicited_cannot_start_not_notified(api):
    """PRD §3.8: "Starting monitoring activates the contact and consumes the scheduled period.
    It is legal only from `NOTIFIED`, rejected otherwise with `ERR_CONTACT_NOT_NOTIFIED`."

    Design: Corner/state_machines/start_monitoring_from_elicited_cannot_start_not_notified
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
    j = jurisdiction["id"]
    ci = fx.open_and_interview_case(program["id"], j, case_overrides={"patient_reference": "PT-I"})
    ks = fx.elicit_contact(program["id"], ci["id"], j, contact_reference="K-S")
    res = api.start_monitoring(ks["id"], make_tracer_headers(j))
    validate_error(res, ApiErrorId.ERR_CONTACT_NOT_NOTIFIED.value)


def test_closed_case_terminal_classify_rejected(api):
    """PRD §3.4: "Classification is legal only from `UNDER_INVESTIGATION`; attempting it from
    any other state is rejected with `ERR_CASE_NOT_CLASSIFIABLE`".
    PRD §3.4: "`CLOSED` is the terminal resting state of the case lifecycle."

    Design: Corner/state_machines/closed_case_terminal_classify_rejected
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition(
        condition_overrides={"requires_lab_confirmation": False}
    )
    j = jurisdiction["id"]
    case = fx.open_interview_classify_case(program["id"], j, "PROBABLE", case_overrides={"patient_reference": "PT-T"})
    validate_success(api.close_case(case["id"], make_investigator_headers(j)))
    res = api.classify_case(case["id"], {"classification": "CONFIRMED"}, make_investigator_headers(j))
    validate_error(res, ApiErrorId.ERR_CASE_NOT_CLASSIFIABLE.value)
    data = validate_success(api.get_case(case["id"], make_investigator_headers(j)))
    assert data["status"] == "CLOSED"


def test_interview_twice_idempotency_rejected_not_interviewable(api):
    """PRD §3.3: "The interview is legal only when the case is in `OPEN` or `REOPENED`; from any
    other state it is rejected with `ERR_CASE_NOT_INTERVIEWABLE`."

    Design: Corner/state_machines/interview_twice_idempotency_rejected_not_interviewable
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
    j = jurisdiction["id"]
    ci = fx.open_and_interview_case(program["id"], j, case_overrides={"patient_reference": "PT-I"})
    res = api.interview_case(ci["id"], {}, make_investigator_headers(j))
    validate_error(res, ApiErrorId.ERR_CASE_NOT_INTERVIEWABLE.value)


def test_transfer_reject_restores_prior_status_no_rehome(api):
    """PRD §3.12: "Rejecting advances the transfer `REQUESTED → REJECTED` and performs no rehome.
    In both cases the case's status is restored to whichever prior state was remembered when the
    transfer was requested — `UNDER_INVESTIGATION → TRANSFER_PENDING` is restored to
    `UNDER_INVESTIGATION`, and `CLASSIFIED → TRANSFER_PENDING` is restored to `CLASSIFIED`."

    Design: Corner/state_machines/transfer_reject_restores_case_prior_status_no_rehome
    """
    program, j1, j2, case, transfer = fx.setup_transfer_requested()
    data = validate_success(
        api.resolve_transfer(transfer["id"], {"status": "REJECTED"}, make_epi_headers())
    )
    assert data["status"] == "REJECTED"
    case_data = validate_success(api.get_case(case["id"], make_epi_headers()))
    assert case_data["status"] == "UNDER_INVESTIGATION"
    assert case_data["jurisdiction_id"] == j1["id"]


def test_supersede_linked_lab_detaches_and_recomputes_count(api):
    """PRD §3.2: "Superseding moves the result `LINKED → SUPERSEDED`, clears its `linked_case_id`,
    and recomputes the previously linked case's `linked_positive_count` and `completeness_score`
    so the case no longer counts the detached result."

    Design: Corner/state_machines/supersede_linked_lab_detaches_and_recomputes_count
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
    j = jurisdiction["id"]
    cs = fx.open_and_interview_case(program["id"], j, case_overrides={"patient_reference": "PT-S"})
    lab = fx.intake_lab(program["id"], j, patient_reference="PT-S", result_value="POSITIVE")
    if lab.get("status") != "LINKED":
        fx.link_lab_to_case(cs["id"], j, lab["id"])
    sup = validate_success(api.supersede_lab_result(lab["id"], make_intake_headers(j)))
    assert sup["status"] == "SUPERSEDED"
    assert sup["linked_case_id"] is None
    case_data = validate_success(api.get_case(cs["id"], make_investigator_headers(j)))
    assert case_data["linked_positive_count"] == 0


def test_elr_intake_no_matching_case_lands_unlinked(api):
    """PRD §3.2: "If no such single matching case exists, the result instead becomes `UNLINKED`
    and carries no `linked_case_id`."

    Design: Corner/state_machines/elr_intake_no_matching_case_lands_unlinked
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
    j = jurisdiction["id"]
    res = api.create_lab_result(
        fx.create_lab_result_payload(program["id"], j, patient_reference="PT-NOBODY",
                                     result_value="POSITIVE"),
        make_intake_headers(j),
    )
    data = validate_success(res, expected_status=201)
    assert data["status"] == "UNLINKED"
    assert data["linked_case_id"] is None


def test_outbreak_cluster_close_valid_transition_and_idempotency(api):
    """PRD §3.11: "An `EpiAnalyst` may close an active cluster. Closing is legal only from
    `ACTIVE`, rejected otherwise with `ERR_CLUSTER_NOT_CLOSEABLE`, and advances the cluster
    `ACTIVE → CLOSED`."

    Design: Corner/state_machines/outbreak_cluster_close_valid_transition
    """
    program, jurisdiction, _, case_ids = fx.setup_three_colocated_confirmed_cases(
        location_id="VENUE-9"
    )
    j = jurisdiction["id"]
    # classify the third to form the cluster
    third = validate_success(
        api.classify_case(case_ids[-1], {"classification": "CONFIRMED"}, make_investigator_headers(j))
    )
    cluster_id = third["cluster_id"]
    assert cluster_id is not None
    closed = validate_success(api.close_cluster(cluster_id, make_epi_headers()))
    assert closed["status"] == "CLOSED"
    res = api.close_cluster(cluster_id, make_epi_headers())
    validate_error(res, ApiErrorId.ERR_CLUSTER_NOT_CLOSEABLE.value)


def test_nedss_void_generated_export_valid_transition_and_idempotency(api):
    """PRD §3.13: "a generated export may be voided; voiding is legal only from `GENERATED`,
    rejected otherwise with `ERR_EXPORT_NOT_VOIDABLE`, and advances the export
    `GENERATED → VOIDED`."

    Design: Corner/state_machines/nedss_void_generated_export_valid_transition
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition(
        condition_overrides={"requires_lab_confirmation": False}
    )
    j = jurisdiction["id"]
    case = fx.open_interview_classify_case(program["id"], j, "CONFIRMED", case_overrides={"patient_reference": "PT-N"})
    export = fx.generate_export(program["id"], case["id"])
    voided = validate_success(api.void_export(export["id"], make_epi_headers()))
    assert voided["status"] == "VOIDED"
    res = api.void_export(export["id"], make_epi_headers())
    validate_error(res, ApiErrorId.ERR_EXPORT_NOT_VOIDABLE.value)


def test_contact_promote_creates_self_referential_lineage_case(api):
    """PRD §3.9: "Promotion creates a new `Case` in `OPEN` with `classification` `SUSPECT`, whose
    `source_contact_id` points back to this contact, whose `jurisdiction_id` is the contact's
    `monitoring_jurisdiction_id`, and whose `condition_code` is copied from the contact's source
    case; the contact's `promoted_case_id` is set to the new case's id and the contact advances
    to `PROMOTED_TO_CASE`."

    Design: Corner/state_machines/contact_promote_creates_self_referential_lineage_case
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
    j = jurisdiction["id"]
    ci = fx.open_and_interview_case(program["id"], j, case_overrides={"patient_reference": "PT-I"})
    kp = fx.setup_notified_contact(program["id"], ci["id"], j, contact_overrides={"contact_reference": "K-P"})
    res = api.promote_contact(
        kp["id"], {"symptom_onset_date": "2026-03-18T00:00:00.000Z"}, make_tracer_headers(j)
    )
    newcase = validate_success(res, expected_status=201)
    contact_after = validate_success(api.get_contact(kp["id"], make_tracer_headers(j)))
    assert contact_after["status"] == "PROMOTED_TO_CASE"
    assert contact_after["promoted_case_id"] == newcase["id"]
    assert newcase["source_contact_id"] == kp["id"]
    assert newcase["status"] == "OPEN"
    assert newcase["jurisdiction_id"] == j
