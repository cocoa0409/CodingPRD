"""Entity assertions and domain invariant checkers.

Shape assertions use the framework's generic validators and the status sets
named in the PRD. Monetary quantities are integer cents (PRD §2.5).
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_cents(data: dict, field: str):
    assert isinstance(data.get(field), int), f"{field} must be integer cents"


def assert_aid_year(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "OPEN", "PACKAGING_LOCKED", "RECONCILING", "CLOSED"]
    _assert_cents(data, "coa_in_state_cents")
    _assert_cents(data, "coa_out_of_state_cents")
    _assert_cents(data, "total_packaged_cents")
    _assert_cents(data, "total_disbursed_cents")


def assert_fund_type(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "ACTIVE", "EXHAUSTED", "CLOSED"]
    assert data["category"] in ["FEDERAL_TITLE_IV", "INSTITUTIONAL", "STATE", "EXTERNAL"]
    _assert_cents(data, "annual_cap_cents")
    _assert_cents(data, "pool_budget_cents")
    _assert_cents(data, "pool_reserved_cents")
    _assert_cents(data, "pool_disbursed_cents")


def assert_student(data: dict):
    _assert_common(data)
    assert data["residency"] in ["IN_STATE", "OUT_OF_STATE"]
    assert data["dependency_status"] in ["DEPENDENT", "INDEPENDENT"]
    assert data["enrollment_status"] in [
        "FULL_TIME", "THREE_QUARTER", "HALF_TIME", "LESS_THAN_HALF"]
    assert data["sap_status"] in [
        "NOT_EVALUATED", "GOOD_STANDING", "WARNING", "SUSPENDED", "APPEAL_APPROVED"]
    assert 1 <= data["grade_level"] <= 5


def assert_isir_record(data: dict):
    _assert_common(data)
    assert data["cohort"] in ["PRIORITY", "STANDARD"]
    assert data["verification_selection"] in ["SELECTED", "NOT_SELECTED"]
    assert isinstance(data["is_current"], bool)
    _assert_cents(data, "efc_provisional_cents")
    _assert_cents(data, "efc_official_cents")
    assert data["efc_verified_cents"] is None or isinstance(data["efc_verified_cents"], int)


def assert_verification_case(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "DOCUMENTS_REQUESTED", "DOCUMENTS_RECEIVED", "UNDER_REVIEW",
        "COMPLETED_SATISFIED", "COMPLETED_CORRECTION_SENT", "WAIVED"]
    assert data["tracking_group"] == "V1"


def assert_verification_document(data: dict):
    _assert_common(data)
    assert data["status"] in ["REQUESTED", "RECEIVED", "ACCEPTED", "REJECTED"]
    assert data["doc_type"] in [
        "TAX_RETURN_TRANSCRIPT", "W2", "HOUSEHOLD_FORM", "IDENTITY_STATEMENT", "OTHER"]


def assert_conflicting_info_case(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "OPEN", "SUBSTANTIATED", "UNSUBSTANTIATED",
        "RESOLVED_REQUIRES_CORRECTION", "RESOLVED"]
    assert isinstance(data.get("opened_by_user_id"), str)


def assert_pj_case(data: dict):
    _assert_common(data)
    assert data["status"] in ["SUBMITTED", "UNDER_REVIEW", "APPROVED", "DENIED"]
    assert data["adjustment_type"] in [
        "EFC_ADJUSTMENT", "COA_ADJUSTMENT", "DEPENDENCY_OVERRIDE"]
    _assert_cents(data, "requested_delta_cents")


def assert_award_package(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "DRAFT", "PACKAGED", "NOTIFIED", "PARTIALLY_ACCEPTED", "ACCEPTED",
        "DECLINED", "REVISION_REQUESTED", "LOCKED"]
    for field in ("coa_used_cents", "efc_used_cents", "need_cents",
                  "total_offered_cents", "total_accepted_cents", "gift_aid_cents"):
        _assert_cents(data, field)


def assert_award_line(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "OFFERED", "ACCEPTED", "PARTIALLY_ACCEPTED", "DECLINED", "CANCELLED",
        "DISBURSING", "DISBURSED", "RETURN_REQUESTED", "RETURNED"]
    _assert_cents(data, "offered_cents")
    _assert_cents(data, "accepted_cents")
    _assert_cents(data, "disbursed_cents")
    assert isinstance(data["sequence_number"], int) and data["sequence_number"] >= 1


def assert_award_notification(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "SENT", "ACKNOWLEDGED"]
    assert isinstance(data["notification_seq"], int) and data["notification_seq"] >= 1
    _assert_cents(data, "snapshot_total_offered_cents")


def assert_revision_request(data: dict):
    _assert_common(data)
    assert data["status"] in ["SUBMITTED", "UNDER_REVIEW", "APPROVED", "DENIED"]
    assert data["reason"] in [
        "CHANGE_ENROLLMENT", "CHANGE_CIRCUMSTANCE", "APPEAL_AMOUNT", "DECLINE_LOAN_ONLY"]
    assert data["requested_by_role"] in ["Student", "AidOfficer"]


def assert_disbursement(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "SCHEDULED", "ELIGIBILITY_PASSED", "ELIGIBILITY_FAILED",
        "POSTED", "RETURN_REQUESTED", "RETURNED"]
    _assert_cents(data, "scheduled_cents")
    _assert_cents(data, "disbursed_cents")
    assert isinstance(data["failure_reasons"], list)


def assert_overaward_case(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "RESOLVING", "RESOLVED", "VERIFIED"]
    _assert_cents(data, "detected_total_aid_cents")
    _assert_cents(data, "overage_cents")


def assert_external_aid(data: dict):
    _assert_common(data)
    _assert_cents(data, "amount_cents")
    assert isinstance(data["counts_against_coa"], bool)


def assert_reconciliation_run(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "DRAFT", "IMPORTED", "COMPARED", "BALANCED", "VARIANCE_FOUND", "ADJUSTED"]
    assert isinstance(data["run_seq"], int) and data["run_seq"] >= 1
    _assert_cents(data, "federal_reported_cents")
    _assert_cents(data, "internal_posted_cents")
    _assert_cents(data, "variance_cents")


def assert_reconciliation_adjustment(data: dict):
    _assert_common(data)
    _assert_cents(data, "adjust_cents")
    assert data["reason_code"] in [
        "FEDERAL_UNDERREPORT", "FEDERAL_OVERREPORT", "TIMING_DIFFERENCE",
        "DATA_ENTRY_ERROR"]
