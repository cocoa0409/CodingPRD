"""Record -> API dict serializers (exact scaffold field names; internals stripped)."""
import db
from services.calc import storage_charge
from utils import ts


def _base(r):
    return {
        "id": r["id"],
        "created_at": ts(r["created_at"]),
        "updated_at": ts(r["updated_at"]),
        "version": r["version"],
    }


def landlord(r):
    return {**_base(r), "legal_name": r["legal_name"], "contact_email": r["contact_email"]}


def unit(r):
    return {
        **_base(r),
        "landlord_id": r["landlord_id"],
        "jurisdiction_code": r["jurisdiction_code"],
        "street_address": r["street_address"],
        "unit_label": r["unit_label"],
        "status": r["status"],
    }


def tenancy(r):
    return {
        **_base(r),
        "unit_id": r["unit_id"],
        "tenant_full_name": r["tenant_full_name"],
        "monthly_rent_cents": r["monthly_rent_cents"],
        "lease_start_date": r["lease_start_date"],
        "lease_end_date": r["lease_end_date"],
        "status": r["status"],
        "ended_at": ts(r["ended_at"]) if r["ended_at"] else None,
    }


def case(r):
    return {
        **_base(r),
        "tenancy_id": r["tenancy_id"],
        "landlord_id": r["landlord_id"],
        "case_reason": r["case_reason"],
        "status": r["status"],
        "case_number": r["case_number"],
        "served_defendant_names": list(r["served_defendant_names"]),
        "service_completed_at": ts(r["service_completed_at"]) if r["service_completed_at"] else None,
        "dismiss_reason": r["dismiss_reason"],
    }


def notice(r):
    return {
        **_base(r),
        "case_id": r["case_id"],
        "notice_type": r["notice_type"],
        "served_on": r["served_on"],
        "claimed_rent_owed_cents": r["claimed_rent_owed_cents"],
        "violation_description": r["violation_description"],
        "statutory_cure_days": r["statutory_cure_days"],
        "cure_deadline": ts(r["cure_deadline"]),
        "status": r["status"],
        "cured_at": ts(r["cured_at"]) if r["cured_at"] else None,
    }


def package(r):
    return {
        **_base(r),
        "case_id": r["case_id"],
        "claimed_amount_cents": r["claimed_amount_cents"],
        "defendant_names": list(r["defendant_names"]),
        "jury_demanded": r["jury_demanded"],
        "efiled": r["efiled"],
        "filing_fee_cents": r["filing_fee_cents"],
        "fee_paid_cents": r["fee_paid_cents"],
        "fee_status": r["fee_status"],
        "status": r["status"],
        "accepted_by_clerk_id": r["accepted_by_clerk_id"],
        "accepted_at": ts(r["accepted_at"]) if r["accepted_at"] else None,
        "rejection_reason": r["rejection_reason"],
    }


def service_attempt(r):
    # Ledger record: id + created_at only among common fields.
    return {
        "id": r["id"],
        "created_at": ts(r["created_at"]),
        "case_id": r["case_id"],
        "defendant_name": r["defendant_name"],
        "method": r["method"],
        "result": r["result"],
        "served_at": ts(r["served_at"]),
        "server_user_id": r["server_user_id"],
        "server_role": r["server_role"],
    }


def hearing(r):
    return {
        **_base(r),
        "case_id": r["case_id"],
        "courtroom": r["courtroom"],
        "start_at": ts(r["start_at"]),
        "end_at": ts(r["end_at"]),
        "status": r["status"],
        "clerk_user_id": r["clerk_user_id"],
    }


def answer(r):
    return {
        **_base(r),
        "case_id": r["case_id"],
        "defense_codes": list(r["defense_codes"]),
        "mediation_requested": r["mediation_requested"],
        "status": r["status"],
        "filed_by_clerk_id": r["filed_by_clerk_id"],
    }


def referral(r):
    return {
        **_base(r),
        "answer_id": r["answer_id"],
        "mediator_id": r["mediator_id"],
        "session_date": r["session_date"],
        "status": r["status"],
        "outcome_notes": r["outcome_notes"],
        "outcome_recorded_at": ts(r["outcome_recorded_at"]) if r["outcome_recorded_at"] else None,
    }


def judgment(r):
    return {
        **_base(r),
        "case_id": r["case_id"],
        "possession_granted": r["possession_granted"],
        "rent_awarded_cents": r["rent_awarded_cents"],
        "damages_cents": r["damages_cents"],
        "late_fee_cents": r["late_fee_cents"],
        "court_costs_cents": r["court_costs_cents"],
        "oldest_unpaid_due_date": r["oldest_unpaid_due_date"],
        "interest_cents": r["interest_cents"],
        "total_awarded_cents": r["total_awarded_cents"],
        "outstanding_balance_cents": r["outstanding_balance_cents"],
        "status": r["status"],
        "entered_by_clerk_id": r["entered_by_clerk_id"],
        "entered_at": ts(r["entered_at"]),
        "appeal_deadline": ts(r["appeal_deadline"]),
        "satisfied_at": ts(r["satisfied_at"]) if r["satisfied_at"] else None,
    }


def writ(r):
    return {
        **_base(r),
        "judgment_id": r["judgment_id"],
        "case_id": r["case_id"],
        "unit_id": r["unit_id"],
        "status": r["status"],
        "writ_fee_paid_cents": r["writ_fee_paid_cents"],
        "issued_at": ts(r["issued_at"]) if r["issued_at"] else None,
        "expires_on": ts(r["expires_on"]) if r["expires_on"] else None,
        "deputy_id": r["deputy_id"],
        "window_start": ts(r["window_start"]) if r["window_start"] else None,
        "window_end": ts(r["window_end"]) if r["window_end"] else None,
        "executed_at": ts(r["executed_at"]) if r["executed_at"] else None,
    }


def storage_record(r):
    if r["status"] in ("RECLAIMED", "DISPOSED"):
        accrued = 0
    else:
        accrued = storage_charge(r["billing_mode"], r["daily_fee_cents"], r["stored_at"], db.now())
    return {
        **_base(r),
        "writ_id": r["writ_id"],
        "case_id": r["case_id"],
        "items_summary": r["items_summary"],
        "status": r["status"],
        "stored_at": ts(r["stored_at"]),
        "daily_fee_cents": r["daily_fee_cents"],
        "billing_mode": r["billing_mode"],
        "disposal_eligible_on": ts(r["disposal_eligible_on"]),
        "accrued_charge_cents": accrued,
        "final_charge_cents": r["final_charge_cents"],
    }


def collection_entry(r):
    # Ledger record: id + created_at only among common fields.
    return {
        "id": r["id"],
        "created_at": ts(r["created_at"]),
        "judgment_id": r["judgment_id"],
        "entry_type": r["entry_type"],
        "amount_cents": r["amount_cents"],
        "reversal_of_id": r["reversal_of_id"],
        "allocation": dict(r["allocation"]),
        "resulting_outstanding_cents": r["resulting_outstanding_cents"],
        "reversed_by_id": r["reversed_by_id"],
        "recorded_by": r["recorded_by"],
    }


def report(r):
    return {
        **_base(r),
        "tenancy_id": r["tenancy_id"],
        "landlord_id": r["landlord_id"],
        "report_type": r["report_type"],
        "reference_report_id": r["reference_report_id"],
        "event_at": ts(r["event_at"]),
        "superseded": r["superseded"],
        "bureau_reference": r["bureau_reference"],
    }
