"""Public serialization of entities — strips internal-only fields.

Internal fields (prefixed with "_", e.g. _seq) are never exposed.
Each serializer projects exactly the scaffold-declared fields plus the
applicable common system fields.
"""


def _base(record, keys, common=True, light=False):
    out = {"id": record["id"], "created_at": record["created_at"]}
    if common:
        out["updated_at"] = record["updated_at"]
        out["version"] = record["version"]
    for k in keys:
        out[k] = record.get(k)
    return out


def payer(r):
    return _base(r, [
        "name", "payer_type", "rate_99453_cents", "rate_99454_cents",
        "rate_99457_cents", "requires_active_consent", "timely_filing_days",
    ])


def patient(r):
    return _base(r, [
        "payer_id", "mrn", "full_name", "enrollment_status",
        "monitoring_status", "care_plan_id",
    ])


def consent(r):
    # Lighter record: only id + created_at (no updated_at, no version).
    return _base(r, [
        "patient_id", "consent_type", "effective_at", "revoked_at", "status",
    ], common=False)


def care_plan(r):
    return _base(r, [
        "patient_id", "diagnosis_code", "goal_text", "required_care_minutes",
        "status", "superseded_by_plan_id",
    ])


def device(r):
    return _base(r, [
        "patient_id", "device_type", "serial_number", "status",
        "activated_at", "setup_billed",
    ])


def vitals(r):
    # Lighter record: only id + created_at.
    return _base(r, [
        "patient_id", "device_id", "reading_value", "secondary_value",
        "measured_at", "service_date", "breach_flag",
    ], common=False)


def alert(r):
    return _base(r, [
        "patient_id", "vitals_reading_id", "severity", "status",
        "acknowledged_by_user_id",
    ])


def review_task(r):
    return _base(r, [
        "patient_id", "threshold_alert_id", "escalated_from_task_id",
        "priority", "status", "reviewer_user_id",
    ])


def care_activity(r):
    return _base(r, [
        "patient_id", "billing_period_id", "clinician_user_id",
        "activity_type", "minutes", "performed_at", "counted_minutes",
    ])


def billing_period(r):
    return _base(r, [
        "patient_id", "period_year", "period_month", "status",
        "provisional_total_minutes", "distinct_device_days",
        "finalized_total_minutes", "finalized_total_cents",
    ])


def line_item(r):
    return _base(r, [
        "billing_period_id", "cpt_code", "units", "amount_cents", "status",
    ])


def claim(r):
    return _base(r, [
        "billing_period_id", "payer_id", "claimed_cents", "reimbursed_cents",
        "status", "expected_billing_period_version",
    ])
