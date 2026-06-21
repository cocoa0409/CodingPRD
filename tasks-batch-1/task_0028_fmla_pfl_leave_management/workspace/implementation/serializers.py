"""Convert internal entity dicts into JSON-safe response payloads."""
from decimal import Decimal

import clock


def _common(entity):
    return {
        "id": entity["id"],
        "created_at": clock.iso8601_ms(entity["created_at"]),
        "updated_at": clock.iso8601_ms(entity["updated_at"]),
        "version": entity["version"],
    }


def _maybe_iso(dt):
    return clock.iso8601_ms(dt) if dt is not None else None


def _num(value):
    if isinstance(value, Decimal):
        # Drop trailing zeros while keeping precision sensible.
        f = float(value)
        if f == int(f):
            return int(f) if isinstance(value, Decimal) and value == value.to_integral_value() else f
        return f
    return value


def serialize_employer(e):
    out = _common(e)
    out.update({
        "legal_name": e["legal_name"],
        "state_code": e["state_code"],
        "fmla_method": e["fmla_method"],
        "pfl_enabled": e["pfl_enabled"],
        "employer_premium_share_pct": float(e["employer_premium_share_pct"]),
        "monthly_premium_total_cents": e["monthly_premium_total_cents"],
    })
    return out


def serialize_employee(e):
    out = _common(e)
    out.update({
        "employer_id": e["employer_id"],
        "email": e["email"],
        "full_name": e["full_name"],
        "hire_date": clock.iso8601_ms(e["hire_date"]),
        "hours_worked_trailing_12mo": e["hours_worked_trailing_12mo"],
        "home_state_code": e["home_state_code"],
        "health_plan_enrolled": e["health_plan_enrolled"],
        "employment_status": e["employment_status"],
        "job_restoration_deadline": _maybe_iso(e.get("job_restoration_deadline")),
    })
    return out


def serialize_provider(p):
    out = _common(p)
    out.update({
        "license_id": p["license_id"],
        "full_name": p["full_name"],
        "specialty": p["specialty"],
    })
    return out


def serialize_leave_case(c):
    out = _common(c)
    out.update({
        "employee_id": c["employee_id"],
        "qualifying_reason": c["qualifying_reason"],
        "leave_type": c["leave_type"],
        "requested_start_at": clock.iso8601_ms(c["requested_start_at"]),
        "requested_end_at": clock.iso8601_ms(c["requested_end_at"]),
        "status": c["status"],
        "eligibility_evaluated": c["eligibility_evaluated"],
        "tenure_months_at_request": c.get("tenure_months_at_request"),
        "hours_at_request": c.get("hours_at_request"),
        "pfl_concurrent": c["pfl_concurrent"],
        "fmla_hours_charged": _num(c["fmla_hours_charged"]),
        "pfl_hours_charged": _num(c["pfl_hours_charged"]),
        "job_restoration_protected": c["job_restoration_protected"],
    })
    return out


def serialize_certification(c):
    out = _common(c)
    out.update({
        "leave_case_id": c["leave_case_id"],
        "provider_id": c["provider_id"],
        "certification_status": c["certification_status"],
        "expected_duration_weeks": _num(c["expected_duration_weeks"]) if c["expected_duration_weeks"] is not None else None,
        "intermittent_frequency_per_month": c.get("intermittent_frequency_per_month"),
        "intermittent_hours_per_episode": _num(c["intermittent_hours_per_episode"]) if c.get("intermittent_hours_per_episode") is not None else None,
        "provider_attestation_signed_at": _maybe_iso(c.get("provider_attestation_signed_at")),
        "received_at": _maybe_iso(c.get("received_at")),
        "insufficient_reason": c.get("insufficient_reason"),
    })
    return out


def serialize_interval(i):
    out = _common(i)
    out.update({
        "leave_case_id": i["leave_case_id"],
        "start_datetime": clock.iso8601_ms(i["start_datetime"]),
        "end_datetime": clock.iso8601_ms(i["end_datetime"]),
        "hours_taken": _num(i["hours_taken"]),
        "fmla_hours_charged": _num(i["fmla_hours_charged"]),
        "pfl_hours_charged": _num(i["pfl_hours_charged"]),
        "status": i["status"],
    })
    return out


def serialize_ledger(l):
    out = _common(l)
    out.update({
        "employee_id": l["employee_id"],
        "leave_case_id": l["leave_case_id"],
        "period_start": clock.iso8601_ms(l["period_start"]),
        "period_end": clock.iso8601_ms(l["period_end"]),
        "employer_premium_share_cents": l["employer_premium_share_cents"],
        "employee_premium_share_cents": l["employee_premium_share_cents"],
        "employee_owes_cents": l["employee_owes_cents"],
        "payments_received_cents": l["payments_received_cents"],
        "payment_status": l["payment_status"],
    })
    return out


def serialize_notice(n):
    out = _common(n)
    out.update({
        "leave_case_id": n["leave_case_id"],
        "notice_type": n["notice_type"],
        "sent_at": _maybe_iso(n.get("sent_at")),
        "response_due_at": _maybe_iso(n.get("response_due_at")),
        "response_received": n["response_received"],
    })
    return out
