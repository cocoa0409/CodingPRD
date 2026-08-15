"""Payload factories — one per entity, input fields only (PRD §3 workflows)."""
from .constants import TEST_DEFAULTS


def create_payer_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["PAYER_NAME"],
        "plan_type": TEST_DEFAULTS["PLAN_TYPE"],
        "default_timely_filing_days": TEST_DEFAULTS["DEFAULT_TIMELY_FILING_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(payer_id, level_number=1, **overrides) -> dict:
    days = (
        TEST_DEFAULTS["POLICY_LEVEL_1_DAYS"]
        if level_number == 1
        else TEST_DEFAULTS["POLICY_LEVEL_2_DAYS"]
    )
    defaults = {
        "payer_id": payer_id,
        "level_number": level_number,
        "timely_filing_days": days,
        "response_window_days": TEST_DEFAULTS["RESPONSE_WINDOW_DAYS"],
        "required_attachment_types": ["CLINICAL_NOTES"],
        "effective_from": TEST_DEFAULTS["POLICY_EFFECTIVE_FROM"],
    }
    defaults.update(overrides)
    return defaults


def create_remittance_code_payload(**overrides) -> dict:
    defaults = {
        "code": TEST_DEFAULTS["CODE"],
        "category": TEST_DEFAULTS["CATEGORY"],
        "default_department": TEST_DEFAULTS["DEPARTMENT"],
        "appealable": True,
    }
    defaults.update(overrides)
    return defaults


def create_denial_payload(payer_id, remittance_code_id, **overrides) -> dict:
    defaults = {
        "claim_number": "CLM-1",
        "patient_account_number": "PA-1",
        "payer_id": payer_id,
        "remittance_code_id": remittance_code_id,
        "billed_amount_cents": 300000,
        "denied_amount_cents": 250000,
        "service_date": TEST_DEFAULTS["SERVICE_DATE"],
        "remittance_received_date": TEST_DEFAULTS["REMITTANCE_RECEIVED_DATE"],
    }
    defaults.update(overrides)
    return defaults


def triage_payload(preventable_flag=False, **overrides) -> dict:
    defaults = {"preventable_flag": preventable_flag}
    defaults.update(overrides)
    return defaults


def assign_payload(specialist_id, expected_denial_case_version) -> dict:
    return {
        "specialist_id": specialist_id,
        "expected_denial_case_version": expected_denial_case_version,
    }


def correction_payload(expected_denial_case_version, **overrides) -> dict:
    defaults = {"expected_denial_case_version": expected_denial_case_version}
    defaults.update(overrides)
    return defaults


def create_appeal_payload(denial_case_id) -> dict:
    return {"denial_case_id": denial_case_id}


def create_attachment_payload(appeal_id, document_type="CLINICAL_NOTES", **overrides) -> dict:
    defaults = {
        "appeal_id": appeal_id,
        "document_type": document_type,
        "file_reference": f"doc-{document_type.lower()}",
    }
    defaults.update(overrides)
    return defaults


def outcome_payload(outcome, recovered_amount_cents, **overrides) -> dict:
    defaults = {"outcome": outcome, "recovered_amount_cents": recovered_amount_cents}
    defaults.update(overrides)
    return defaults


def reversal_payload(reason="Payer reissued the remittance") -> dict:
    return {"reason": reason}


def void_attachment_payload(reason="Superseded document") -> dict:
    return {"reason": reason}


def create_task_payload(denial_case_id, **overrides) -> dict:
    defaults = {
        "denial_case_id": denial_case_id,
        "task_type": "PROCESS_FIX",
        "description": "Fix the upstream process",
        "due_date": "2026-08-20",
    }
    defaults.update(overrides)
    return defaults


def implement_fix_payload(fix_summary="Encoder mapping corrected") -> dict:
    return {"fix_summary": fix_summary}


def create_write_off_payload(denial_case_id, requested_amount_cents, **overrides) -> dict:
    defaults = {
        "denial_case_id": denial_case_id,
        "requested_amount_cents": requested_amount_cents,
        "reason_code": "SMALL_BALANCE",
    }
    defaults.update(overrides)
    return defaults


def reject_write_off_payload(reason="Insufficient documentation") -> dict:
    return {"reason": reason}


def revise_write_off_payload(requested_amount_cents) -> dict:
    return {"requested_amount_cents": requested_amount_cents}


def rescind_write_off_payload(reason="Payer agreed to reprocess after all") -> dict:
    return {"reason": reason}


def create_scorecard_payload(department="CODING", **overrides) -> dict:
    defaults = {
        "department": department,
        "period_start_date": "2026-08-01",
        "period_end_date": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_program_payload(**overrides) -> dict:
    defaults = {
        "department": "CODING",
        "name": "Coder Roundtables",
        "start_date": "2026-08-01",
        "end_date": "2026-10-31",
        "target_reduction_pct": 15,
    }
    defaults.update(overrides)
    return defaults


def clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
