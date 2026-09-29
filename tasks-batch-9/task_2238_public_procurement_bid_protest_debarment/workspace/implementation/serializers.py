"""Response payload shapes.

Field lists follow SCAFFOLD.yaml entity definitions. Journal rows
(MandatoryRequirement, Addendum, QuestionSubmission, AgencyRecordItem) expose
only id and created_at from the common set — updated_at and version are absent
entirely, per PRD §2.4.
"""

from util import fmt_dt, num

_COMMON = ("created_at", "updated_at", "version")


def _emit(row, fields, datetimes, numbers=(), common=True):
    out = {}
    for field in fields:
        value = row.get(field)
        if field in datetimes:
            out[field] = fmt_dt(value)
        elif field in numbers:
            out[field] = num(value)
        elif isinstance(value, list):
            out[field] = list(value)
        else:
            out[field] = value
    out["created_at"] = fmt_dt(row["created_at"])
    if common:
        out["updated_at"] = fmt_dt(row.get("updated_at"))
        out["version"] = row.get("version")
    return out


def vendor(row):
    return _emit(
        row,
        ("id", "legal_name", "tax_id", "contact_email", "eligibility_status",
         "protest_fee_balance_cents", "debarment_strike_count", "active_debarment_id",
         "reinstatement_earliest_petition_utc", "suspension_reason_code"),
        {"reinstatement_earliest_petition_utc"},
    )


def solicitation(row):
    return _emit(
        row,
        ("id", "solicitation_number", "title", "issuing_agency_code",
         "estimated_value_cents", "original_bid_due_utc", "effective_bid_due_utc",
         "original_question_deadline_utc", "question_deadline_utc", "status",
         "issued_by_user_id", "bids_opened_at_utc", "cumulative_extension_days",
         "addendum_count", "apparent_low_bid_id", "protest_escrow_cents",
         "predecessor_solicitation_id"),
        {"original_bid_due_utc", "effective_bid_due_utc",
         "original_question_deadline_utc", "question_deadline_utc",
         "bids_opened_at_utc"},
    )


def requirement(row):
    return _emit(
        row,
        ("id", "solicitation_id", "requirement_code", "description", "materiality",
         "is_waivable", "introduced_by_addendum_sequence"),
        set(),
        common=False,
    )


def addendum(row):
    return _emit(
        row,
        ("id", "solicitation_id", "sequence_number", "summary",
         "extends_bid_due_by_days", "acknowledgment_required",
         "adds_material_requirement", "new_requirement_codes", "issued_at_utc"),
        {"issued_at_utc"},
        common=False,
    )


def question(row):
    return _emit(
        row,
        ("id", "solicitation_id", "vendor_id", "question_text", "submitted_at_utc",
         "status", "answer_summary", "answered_via_addendum_sequence"),
        {"submitted_at_utc"},
        common=False,
    )


def bid(row):
    return _emit(
        row,
        ("id", "solicitation_id", "vendor_id", "total_price_cents",
         "acknowledged_addendum_sequences", "submitted_at_utc",
         "responsiveness_status", "responsibility_status", "evaluated_price_cents",
         "corrected_total_price_cents", "informality_loading_cents",
         "nonresponsive_reason_codes", "responsiveness_decided_at_utc",
         "responsiveness_decided_by_user_id", "superseded_by_bid_id"),
        {"submitted_at_utc", "responsiveness_decided_at_utc"},
    )


def review(row):
    return _emit(
        row,
        ("id", "bid_id", "reviewer_user_id", "financial_capacity_score",
         "past_performance_score", "integrity_score", "weight_profile",
         "strike_penalty_points", "composite_score", "determination",
         "decided_at_utc", "notes", "superseded_at_utc"),
        {"decided_at_utc", "superseded_at_utc"},
        {"strike_penalty_points", "composite_score"},
    )


def protest(row):
    return _emit(
        row,
        ("id", "solicitation_id", "protester_vendor_id", "challenged_bid_id",
         "grounds_code", "narrative", "filed_at_utc", "status", "stay_status",
         "filing_fee_cents", "timeliness_deadline_utc", "standing_basis",
         "decision_outcome", "remedy_code", "decided_at_utc", "record_item_count",
         "fee_refunded_cents"),
        {"filed_at_utc", "timeliness_deadline_utc", "decided_at_utc"},
    )


def hearing(row):
    return _emit(
        row,
        ("id", "protest_id", "hearing_officer_user_id", "scheduled_start_utc",
         "scheduled_end_utc", "room_code", "status", "continuance_count",
         "convened_at_utc", "concluded_at_utc", "record_items_reviewed_count"),
        {"scheduled_start_utc", "scheduled_end_utc", "convened_at_utc",
         "concluded_at_utc"},
    )


def record_item(row):
    return _emit(
        row,
        ("id", "protest_id", "sequence_number", "item_type", "document_ref",
         "submitted_by_role", "submitted_at_utc"),
        {"submitted_at_utc"},
        common=False,
    )


def award(row):
    out = _emit(
        row,
        ("id", "solicitation_id", "winning_bid_id", "vendor_id",
         "base_obligation_cents", "administrative_fee_rate",
         "administrative_fee_cents", "protest_risk_reserve_cents",
         "award_total_obligation_cents", "status", "executed_at_utc",
         "void_reason_code"),
        {"executed_at_utc"},
    )
    rate = row.get("administrative_fee_rate")
    out["administrative_fee_rate"] = None if rate is None else float(rate)
    return out


def proceeding(row):
    return _emit(
        row,
        ("id", "vendor_id", "source_protest_id", "cause_code",
         "aggravating_factor_codes", "mitigating_factor_codes",
         "notice_issued_at_utc", "response_deadline_utc", "status",
         "interim_status", "aggravating_total_points", "mitigating_credit_points",
         "severity_score", "debarment_period_months", "debarment_start_utc",
         "debarment_end_utc", "strikes_applied", "response_narrative",
         "decided_at_utc"),
        {"notice_issued_at_utc", "response_deadline_utc", "debarment_start_utc",
         "debarment_end_utc", "decided_at_utc"},
        {"aggravating_total_points", "mitigating_credit_points", "severity_score"},
    )


def petition(row):
    return _emit(
        row,
        ("id", "proceeding_id", "remediation_evidence_codes", "narrative",
         "filed_at_utc", "status", "months_served_at_filing", "decided_at_utc",
         "decision_rationale"),
        {"filed_at_utc", "decided_at_utc"},
    )


def screening(row):
    return _emit(
        row,
        ("id", "solicitation_id", "prime_vendor_id", "sub_vendor_id", "tier",
         "result", "blocked_reason_code", "screened_at_utc", "rescreened_count"),
        {"screened_at_utc"},
    )
