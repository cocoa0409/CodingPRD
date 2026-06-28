"""Cross-entity lookup helpers used by multiple routes."""
from db import db


def patients_of(payer_id):
    return [p for p in db.patients.values() if p["payer_id"] == payer_id]


def consents_of(patient_id):
    return [c for c in db.consents.values() if c["patient_id"] == patient_id]


def active_consent(patient_id):
    """Return the patient's current ACTIVE ConsentRecord, or None."""
    for c in db.consents.values():
        if c["patient_id"] == patient_id and c["status"] == "ACTIVE":
            return c
    return None


def care_plans_of(patient_id):
    return [cp for cp in db.care_plans.values()
            if cp["patient_id"] == patient_id]


def active_care_plan(patient_id):
    """Return the patient's current ACTIVE CarePlan, or None."""
    for cp in db.care_plans.values():
        if cp["patient_id"] == patient_id and cp["status"] == "ACTIVE":
            return cp
    return None


def devices_of(patient_id):
    return [d for d in db.devices.values() if d["patient_id"] == patient_id]


def vitals_of(patient_id):
    return [v for v in db.vitals.values() if v["patient_id"] == patient_id]


def vitals_of_device(device_id):
    return [v for v in db.vitals.values() if v["device_id"] == device_id]


def billing_periods_of(patient_id):
    return [bp for bp in db.billing_periods.values()
            if bp["patient_id"] == patient_id]


def care_activities_of_period(billing_period_id):
    return [a for a in db.care_activities.values()
            if a["billing_period_id"] == billing_period_id]


def care_activities_of_patient(patient_id):
    return [a for a in db.care_activities.values()
            if a["patient_id"] == patient_id]


def line_items_of_period(billing_period_id):
    return [li for li in db.line_items.values()
            if li["billing_period_id"] == billing_period_id]


def claims_of_period(billing_period_id):
    return [c for c in db.claims.values()
            if c["billing_period_id"] == billing_period_id]


def review_tasks_for_alert(alert_id):
    return [t for t in db.review_tasks.values()
            if t["threshold_alert_id"] == alert_id]
