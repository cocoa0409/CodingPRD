"""Row -> JSON serializers.  Every datetime field renders as an ISO 8601 UTC
instant with three fractional digits and a trailing Z; CE hour figures render
as plain JSON numbers."""

from decimal import Decimal

from .clock import render_instant


def _hours(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(row):
    return {
        "id": row["id"],
        "created_at": render_instant(row["created_at"]),
        "updated_at": render_instant(row["updated_at"]),
        "version": row["version"],
    }


def agency(row):
    out = _common(row)
    out.update({
        "name": row["name"],
        "resident_state_code": row["resident_state_code"],
    })
    return out


def producer(row):
    from . import calc
    out = _common(row)
    out.update({
        "npn": row["npn"],
        "full_name": row["full_name"],
        "resident_state_code": row["resident_state_code"],
        "agency_id": row["agency_id"],
        "status": row["status"],
        # PRD 3.6 defines this field against the logical clock's *current*
        # calendar year, so it is derived live at read time: when the clock
        # crosses a January 1 boundary the window moves even though no issue
        # or rescind occurred.  The stored counter (recomputed on every issue
        # and rescind) is kept in sync with the same definition here.
        "ytd_issued_premium_cents": calc.producer_ytd_live(row["id"]),
        "commission_held_cents": row["commission_held_cents"],
    })
    return out


def license_(row):
    out = _common(row)
    out.update({
        "producer_id": row["producer_id"],
        "agency_id": row["agency_id"],
        "state_code": row["state_code"],
        "license_class": row["license_class"],
        "lines_of_authority": list(row["lines_of_authority"]),
        "status": row["status"],
        "issue_date": render_instant(row["issue_date"]),
        "expiration_date": render_instant(row["expiration_date"]),
        "ce_period_start": render_instant(row["ce_period_start"]),
        "ce_period_end": render_instant(row["ce_period_end"]),
        "ce_required_hours": _hours(row["ce_required_hours"]),
        "ce_ethics_required_hours": _hours(row["ce_ethics_required_hours"]),
        "ce_completed_hours": _hours(row["ce_completed_hours"]),
        "ce_ethics_completed_hours": _hours(row["ce_ethics_completed_hours"]),
        "renewed_count": row["renewed_count"],
    })
    return out


def ce_credit(row):
    out = _common(row)
    out.update({
        "license_id": row["license_id"],
        "provider_name": row["provider_name"],
        "course_title": row["course_title"],
        "category": row["category"],
        "credit_hours": _hours(row["credit_hours"]),
        "completed_on": render_instant(row["completed_on"]),
        "status": row["status"],
        "reviewed_by_user_id": row["reviewed_by_user_id"],
    })
    return out


def appointment(row):
    out = _common(row)
    out.update({
        "producer_id": row["producer_id"],
        "agency_id": row["agency_id"],
        "state_code": row["state_code"],
        "lines_of_authority": list(row["lines_of_authority"]),
        "origin": row["origin"],
        "status": row["status"],
        "effective_date": render_instant(row["effective_date"]),
        "termination_date": render_instant(row["termination_date"]),
        "termination_reason": row["termination_reason"],
        "termination_initiated_at": render_instant(row["termination_initiated_at"]),
        "jit_filing_deadline": render_instant(row["jit_filing_deadline"]),
    })
    return out


def application(row):
    out = _common(row)
    out.update({
        "producer_id": row["producer_id"],
        "state_code": row["state_code"],
        "line_of_authority": row["line_of_authority"],
        "applicant_name": row["applicant_name"],
        "premium_cents": row["premium_cents"],
        "status": row["status"],
        "submitted_at": render_instant(row["submitted_at"]),
        "decided_at": render_instant(row["decided_at"]),
        "issued_at": render_instant(row["issued_at"]),
        "eligibility_snapshot": row["eligibility_snapshot"],
        "jit_appointment_id": row["jit_appointment_id"],
    })
    return out


def commission_entry(row):
    out = _common(row)
    out.update({
        "application_id": row["application_id"],
        "producer_id": row["producer_id"],
        "amount_cents": row["amount_cents"],
        "amount_variant": row["amount_variant"],
        "status": row["status"],
        "hold_reason": row["hold_reason"],
    })
    return out


def regulatory_action(row):
    out = _common(row)
    out.update({
        "producer_id": row["producer_id"],
        "agency_id": row["agency_id"],
        "state_code": row["state_code"],
        "action_type": row["action_type"],
        "fine_amount_cents": row["fine_amount_cents"],
        "effective_date": render_instant(row["effective_date"]),
        "status": row["status"],
        "created_by_user_id": row["created_by_user_id"],
        "decided_by_user_id": row["decided_by_user_id"],
        "fine_allocations": [dict(a) for a in row["fine_allocations"]],
    })
    return out


def inquiry(row):
    out = _common(row)
    out.update({
        "producer_id": row["producer_id"],
        "agency_id": row["agency_id"],
        "state_code": row["state_code"],
        "reference_number": row["reference_number"],
        "received_at": render_instant(row["received_at"]),
        "response_due_at": render_instant(row["response_due_at"]),
        "status": row["status"],
        "response_text": row["response_text"],
        "responded_at": render_instant(row["responded_at"]),
    })
    return out
