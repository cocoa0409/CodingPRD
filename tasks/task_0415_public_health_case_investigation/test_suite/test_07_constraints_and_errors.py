"""Business constraints (lab linkage, monitoring elapse, reportability, uniqueness,
same-jurisdiction transfer, invalid classification, close-with-pending-transfer) and
isolated error triggers.

Queue B (Corner): validations section + errors section instances.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_error_is_one_of,
    get_success_data,
    make_investigator_headers,
    make_tracer_headers,
    make_intake_headers,
    make_epi_headers,
    ApiErrorId,
    create_jurisdiction_payload,
    create_case_payload,
)
from test_helpers import fixtures as fx


# ===========================================================================
# Queue B — validations section
# ===========================================================================
def test_lab_patient_mismatch_after_condition_match_on_link(api):
    """PRD §3.2: "and the lab result's `patient_reference` must equal the case's
    `patient_reference`, checked second and rejected with `ERR_LAB_PATIENT_MISMATCH`."

    Design: Corner/validations/lab_patient_mismatch_after_condition_match_on_link
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
    j = jurisdiction["id"]
    cl = fx.open_and_interview_case(program["id"], j, case_overrides={"patient_reference": "PT-L"})
    # Same condition COVID19 but different patient PT-OTHER.
    lab = fx.intake_lab(program["id"], j, patient_reference="PT-OTHER", result_value="POSITIVE")
    res = api.link_lab_result(cl["id"], {"lab_result_id": lab["id"]}, make_investigator_headers(j))
    validate_error(res, ApiErrorId.ERR_LAB_PATIENT_MISMATCH.value)


def test_complete_monitoring_before_quarantine_elapsed_returns_not_elapsed(api):
    """PRD §3.8: "It additionally requires that the program's `current_date` has reached or
    passed the contact's `quarantine_end_date`; if the window has not yet elapsed, the request
    is rejected with `ERR_MONITORING_NOT_ELAPSED`."

    Design: Corner/validations/complete_monitoring_before_quarantine_elapsed_returns_not_elapsed
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
    j = jurisdiction["id"]
    fx.set_clock(program["id"], "2026-03-20T00:00:00.000Z")  # before quarantine_end 2026-03-29
    ci = fx.open_and_interview_case(program["id"], j, case_overrides={"patient_reference": "PT-I"})
    contact_after, _ = fx.setup_monitoring_active_contact(
        program["id"], ci["id"], j, contact_overrides={"contact_reference": "K-M"}
    )
    res = api.complete_monitoring(contact_after["id"], make_tracer_headers(j))
    validate_error(res, ApiErrorId.ERR_MONITORING_NOT_ELAPSED.value)


def test_nedss_export_suspect_case_not_reportable(api):
    """PRD §3.13: "The case's `classification` must be `CONFIRMED` or `PROBABLE` to be
    reportable; any other classification is rejected with `ERR_EXPORT_CASE_NOT_REPORTABLE`."

    Design: Corner/validations/nedss_export_suspect_case_not_reportable
    """
    program, jurisdiction, _, case = fx.setup_interviewed_case(case_overrides={"patient_reference": "PT-U"})
    res = api.create_export({"program_id": program["id"], "case_id": case["id"]}, make_epi_headers())
    validate_error(res, ApiErrorId.ERR_EXPORT_CASE_NOT_REPORTABLE.value)


def test_duplicate_fips_code_within_program_returns_duplicate_key(api):
    """PRD §3.1: "the `fips_code` must be unique across the jurisdictions of the same program,
    and a duplicate is rejected with `ERR_DUPLICATE_KEY`."

    Design: Corner/validations/duplicate_fips_code_within_program_returns_duplicate_key
    """
    program = fx.create_program()
    fx.create_jurisdiction(program["id"], name="County 1", fips_code="06001")
    res = api.create_jurisdiction(
        create_jurisdiction_payload(program["id"], name="County 1 Dup", fips_code="06001"), fx.ADMIN
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_KEY.value)


def test_same_jurisdiction_transfer_rejected(api):
    """PRD §3.12: "The `to_jurisdiction_id` must differ from the case's current `jurisdiction_id`,
    or the request is rejected with `ERR_SAME_JURISDICTION_TRANSFER`."

    Design: Corner/validations/same_jurisdiction_transfer_rejected
    """
    program, jurisdiction, _, case = fx.setup_interviewed_case(case_overrides={"patient_reference": "PT-S"})
    j = jurisdiction["id"]
    version = fx.observe_case_version(case["id"])
    res = api.create_transfer(
        {"program_id": program["id"], "case_id": case["id"], "to_jurisdiction_id": j,
         "expected_case_version": version},
        make_epi_headers(),
    )
    validate_error(res, ApiErrorId.ERR_SAME_JURISDICTION_TRANSFER.value)


def test_classify_invalid_classification_value_rejected(api):
    """PRD §3.4: "The submitted `classification` must be one of `CONFIRMED`, `PROBABLE`, or
    `NOT_A_CASE`; any other value is rejected with `ERR_INVALID_CLASSIFICATION`."

    Design: Corner/validations/classify_invalid_classification_value_rejected
    """
    program, jurisdiction, _, case = fx.setup_interviewed_case(case_overrides={"patient_reference": "PT-V"})
    j = jurisdiction["id"]
    res = api.classify_case(case["id"], {"classification": "SUSPECT"}, make_investigator_headers(j))
    validate_error(res, ApiErrorId.ERR_INVALID_CLASSIFICATION.value)


def test_close_blocked_by_pending_transfer(api):
    """PRD §3.4: "no jurisdiction transfer for this case may be in `REQUESTED`, or the close is
    rejected with `ERR_TRANSFER_PENDING_EXISTS`."
    PRD §3.12: "A successful request creates a `JurisdictionTransfer` in `REQUESTED` ... drives
    the case from its current state (`UNDER_INVESTIGATION` or `CLASSIFIED`) into `TRANSFER_PENDING`".
    PRD §3.4: "Closing is legal only from `CLASSIFIED`, rejected otherwise with
    `ERR_CASE_NOT_CLOSEABLE`."

    Design: Corner/validations/close_blocked_by_pending_transfer_returns_transfer_pending_exists
    """
    program, j1, j2, case, transfer = fx.setup_transfer_requested(
        condition_overrides={"requires_lab_confirmation": False}, prior_classification="PROBABLE"
    )
    res = api.close_case(case["id"], make_investigator_headers(j1["id"]))
    validate_error_is_one_of(
        res, [ApiErrorId.ERR_CASE_NOT_CLOSEABLE.value, ApiErrorId.ERR_TRANSFER_PENDING_EXISTS.value]
    )


# ===========================================================================
# Queue B — errors section
# ===========================================================================
def test_missing_user_context_header_returns_400(api):
    """PRD §2.1: "Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying
    the acting user, and `X-User-Role`, declaring the operational capacity under which the
    request is made. If either header is absent, or if `X-User-Role` is not one of the recognized
    role names, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/errors/missing_user_context_header_returns_400
    """
    program = fx.create_program()
    # 'as: NONE' -> omit the auth header entirely (Content-Type only).
    res = api.get_program(program["id"], {"Content-Type": "application/json"})
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


def test_unknown_role_header_returns_400(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the recognized
    role names, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/errors/unknown_role_header_returns_400
    """
    program = fx.create_program()
    # 'as: SUPERHERO' -> a bogus/unknown role token.
    res = api.get_program(
        program["id"],
        {"X-User-ID": "test-bogus-1", "X-User-Role": "SUPERHERO", "Content-Type": "application/json"},
    )
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


def test_lab_not_supersedable_when_not_linked(api):
    """PRD §3.2: "Only a result in `LINKED` may be superseded; otherwise the request is rejected
    with `ERR_LAB_NOT_SUPERSEDABLE`."

    Design: Corner/errors/lab_not_supersedable_when_not_linked
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
    j = jurisdiction["id"]
    lab = fx.intake_lab(program["id"], j, patient_reference="PT-NOBODY", result_value="POSITIVE")
    res = api.supersede_lab_result(lab["id"], make_intake_headers(j))
    validate_error(res, ApiErrorId.ERR_LAB_NOT_SUPERSEDABLE.value)


def test_contact_not_voidable_when_already_voided(api):
    """PRD §3.9: "Voiding is legal only when the contact is in `ELICITED`, `NOTIFICATION_PENDING`,
    `NOTIFIED`, `NOTIFICATION_FAILED`, or `MONITORING_ACTIVE`; from any terminal state it is
    rejected with `ERR_CONTACT_NOT_VOIDABLE`."

    Design: Corner/errors/contact_not_voidable_when_already_voided
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
    j = jurisdiction["id"]
    ci = fx.open_and_interview_case(program["id"], j, case_overrides={"patient_reference": "PT-I"})
    kv = fx.elicit_contact(
        program["id"], ci["id"], j, contact_reference="K-V",
        exposure_setting="SOCIAL", proximity_meters=1.5, cumulative_exposure_minutes=10,
    )
    validate_success(api.void_contact(kv["id"], make_tracer_headers(j)))
    res = api.void_contact(kv["id"], make_tracer_headers(j))
    validate_error(res, ApiErrorId.ERR_CONTACT_NOT_VOIDABLE.value)


def test_start_monitoring_without_scheduled_period_returns_no_scheduled_monitoring(api):
    """PRD §3.8: "a `SCHEDULED` monitoring period for the contact must exist, or the request is
    rejected with `ERR_NO_SCHEDULED_MONITORING`."

    Design: Corner/errors/start_monitoring_without_scheduled_period_returns_no_scheduled_monitoring
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
    j = jurisdiction["id"]
    ci = fx.open_and_interview_case(program["id"], j, case_overrides={"patient_reference": "PT-I"})
    kn = fx.setup_notified_contact(program["id"], ci["id"], j, contact_overrides={"contact_reference": "K-N"})
    res = api.start_monitoring(kn["id"], make_tracer_headers(j))
    validate_error(res, ApiErrorId.ERR_NO_SCHEDULED_MONITORING.value)


def test_transfer_not_resolvable_when_already_accepted(api):
    """PRD §3.12: "Resolution is legal only while the transfer is in `REQUESTED`, rejected
    otherwise with `ERR_TRANSFER_NOT_RESOLVABLE`."

    Design: Corner/errors/transfer_not_resolvable_when_already_accepted
    """
    program, j1, j2, case, transfer = fx.setup_transfer_requested()
    validate_success(api.resolve_transfer(transfer["id"], {"status": "ACCEPTED"}, make_epi_headers()))
    res = api.resolve_transfer(transfer["id"], {"status": "REJECTED"}, make_epi_headers())
    validate_error(res, ApiErrorId.ERR_TRANSFER_NOT_RESOLVABLE.value)


def test_condition_code_unknown_in_program_on_case_open(api):
    """PRD §2.5: "the foreign keys it accepts — `program_id`, `jurisdiction_id`, `condition_code`,
    ... must each reference an existing row within the same program; an unresolved reference
    yields the corresponding not-found error."

    Design: Corner/errors/condition_code_unknown_in_program_on_case_open
    """
    program, jurisdiction, _ = fx.setup_program_jurisdiction_condition()
    j = jurisdiction["id"]
    res = api.create_case(
        create_case_payload(program["id"], j, condition_code="EBOLA", patient_reference="PT-E"),
        make_investigator_headers(j),
    )
    validate_error(res, ApiErrorId.ERR_CONDITION_NOT_FOUND.value)
