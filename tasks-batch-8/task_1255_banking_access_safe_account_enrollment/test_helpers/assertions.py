"""Entity assertions and domain invariant checkers (PRD §2.4, §2.8, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_account_standard(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["monthly_fee_cap_cents"], int)
    assert isinstance(data["overdraft_fee_allowed"], bool)
    assert isinstance(data["min_opening_deposit_cap_cents"], int)
    assert isinstance(data["accepted_alt_id_types"], list)
    assert isinstance(data["chex_second_look_required"], bool)
    assert isinstance(data["requires_financial_education"], bool)
    assert data["rubric_mode"] in ("STANDARD_RUBRIC", "REMEDIATION_RUBRIC")
    assert data["status"] in ("DRAFT", "EFFECTIVE", "SUPERSEDED")


def assert_partner_institution(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["charter_type"] in ("BANK", "CREDIT_UNION")
    assert data["certification_status"] in (
        "APPLIED", "UNDER_REVIEW", "CERTIFIED", "SUSPENDED", "LAPSED", "DECERTIFIED",
    )
    assert isinstance(data["accounts_opened_total"], int)


def assert_certification_review(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("institution_id", ""))
    assert is_valid_uuid(data.get("standard_id", ""))
    assert data["status"] in (
        "DRAFT", "SCORED", "FINALIZED_PASS", "FINALIZED_CONDITIONAL",
        "FINALIZED_FAIL", "SUPERSEDED",
    )


def assert_participant(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["prior_banking_record"] in ("NONE", "CLEAN", "FLAGGED")
    assert isinstance(data["docs_complete"], bool)
    assert data["pipeline_stage"] in (
        "REGISTERED", "REFERRED", "DOCS_READY", "EVENT_BOOKED", "APPLIED", "ACCOUNT_OPENED",
    )


def assert_referral(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("participant_id", ""))
    assert data["created_via"] in ("NAVIGATOR", "CAMPAIGN")
    assert data["status"] in (
        "DOCS_PENDING", "DOCS_COMPLETE", "BOOKED", "APPLIED",
        "CLOSED_CONVERTED", "CLOSED_LOST",
    )


def assert_account_opening_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("institution_id", ""))
    assert isinstance(data["venue_code"], str) and data["venue_code"]
    assert isinstance(data["capacity"], int)
    assert isinstance(data["booked_count"], int)
    assert isinstance(data["alt_id_accepted"], bool)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")


def assert_account_application(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("participant_id", ""))
    assert is_valid_uuid(data.get("institution_id", ""))
    assert data["id_type_presented"] in (
        "STATE_ID", "MATRICULA_CONSULAR", "MUNICIPAL_ID", "FOREIGN_PASSPORT",
    )
    assert data["status"] in (
        "SUBMITTED", "OPENED", "DECLINED_CHEX", "DECLINED_ID",
        "DECLINED_FINAL", "REINSTATED", "CLOSED_EARLY",
    )


def assert_barrier_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert is_valid_uuid(data.get("participant_id", ""))
    assert is_valid_uuid(data.get("institution_id", ""))
    assert data["status"] in ("OPEN", "PLAN_PROPOSED", "COUNTERED", "RESOLVED", "DENIED_FINAL")
    assert isinstance(data["negotiation_rounds"], int)


def assert_education_pairing(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("participant_id", ""))
    assert isinstance(data["coach_id"], str) and data["coach_id"]
    assert data["course_code"] in ("FOUNDATIONS", "CREDIT_BASICS", "SAVINGS")
    assert data["status"] in ("ACTIVE", "COMPLETED", "FOLLOW_UP_DUE", "FOLLOW_UP_DONE")


def assert_retention_checkpoint(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert data["kind"] in ("M6", "M12")
    assert isinstance(data["due_date"], str) and data["due_date"]
    assert isinstance(data["window_end"], str) and data["window_end"]
    assert data["status"] in (
        "PENDING", "EVALUATED_RETAINED", "EVALUATED_NOT_RETAINED", "EXPIRED_UNCONFIRMED",
    )


def assert_funding_grant(data: dict):
    _assert_common(data)
    assert isinstance(data["funder_name"], str) and data["funder_name"]
    assert isinstance(data["program_year"], int)
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["per_report_cap_cents"], int)
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data["reserved_cents"], int)
    assert isinstance(data["disbursed_cents"], int)
    assert isinstance(data["available_cents"], int)


def assert_partner_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("institution_id", ""))
    assert is_valid_uuid(data.get("grant_id", ""))
    assert data["evaluation_mode"] in ("PROVISIONAL", "FINAL")
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED")
    assert isinstance(data["opened_count"], int)
    assert isinstance(data["opening_claim_cents"], int)
    assert isinstance(data["retention_bonus_cents"], int)
    assert isinstance(data["education_stipend_cents"], int)
    assert isinstance(data["claim_total_cents"], int)


def assert_outreach_campaign(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["zip_cluster"], str) and data["zip_cluster"]
    assert isinstance(data["budget_cents"], int)
    assert isinstance(data["per_conversion_cents"], int)
    assert isinstance(data["spent_cents"], int)
    assert data["status"] in ("ACTIVE", "CLOSED")


def assert_grant_ledger_invariant(grant: dict):
    """PRD §2.8: available_cents + reserved_cents + disbursed_cents == total_cents
    at every observable instant."""
    total = grant["available_cents"] + grant["reserved_cents"] + grant["disbursed_cents"]
    assert total == grant["total_cents"], (
        f"grant ledger drift: {grant['available_cents']} + {grant['reserved_cents']} "
        f"+ {grant['disbursed_cents']} != total {grant['total_cents']}"
    )
