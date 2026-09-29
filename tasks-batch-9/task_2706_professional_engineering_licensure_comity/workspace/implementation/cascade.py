"""Derived postures, cascades and the three-stage clock sweep (PRD 2.5, 2.9)."""
import calc
import db
from util import add_days


# ------------------------------------------------------------------- roster
def recompute_active_license_number(engineer_id):
    engineer = db.get("engineers", engineer_id)
    if engineer is None:
        return
    number = None
    for row in db.all_rows("licenses"):
        if row["engineer_id"] == engineer_id and row["status"] == "ACTIVE":
            number = row["license_number"]
            break
    db.write(engineer, active_license_number=number)


OPEN_INVESTIGATION_STATUSES = ("RECEIVED", "INVESTIGATING", "PROBABLE_CAUSE")


def recompute_open_case_count(engineer_id):
    engineer = db.get("engineers", engineer_id)
    if engineer is None:
        return
    count = 0
    for case in db.all_rows("cases"):
        if case["investigation_status"] not in OPEN_INVESTIGATION_STATUSES:
            continue
        license_id = case["respondent_license_id"]
        if not license_id:
            continue
        license_row = db.get("licenses", license_id)
        if license_row is not None and license_row["engineer_id"] == engineer_id:
            count += 1
    db.write(engineer, open_case_count=count)


def engineer_of_license(license_id):
    license_row = db.get("licenses", license_id)
    return license_row["engineer_id"] if license_row else None


# --------------------------------------------------------------- plan sets
def void_draft_plans(firm):
    for plan in db.all_rows("plan_submissions"):
        if plan["firm_registration_id"] == firm["id"] and plan["status"] == "DRAFT":
            db.write(plan, status="VOIDED")


# ------------------------------------------------------------- firm posture
def posture_for(firm):
    """The four-clause pinned posture test of PRD 2.9."""
    license_row = db.get("licenses", firm["responsible_charge_license_id"])
    status = license_row["status"] if license_row else None
    if status == "REVOKED":
        return "REVOKED"
    if status in ("SUSPENDED", "EXPIRED"):
        return "LAPSED_NO_RESPONSIBLE_CHARGE"
    if firm["registration_expires_at"] is not None and db.clock() > firm["registration_expires_at"]:
        return "EXPIRED"
    return "ACTIVE"


def firms_for_license(license_id):
    return [f for f in db.all_rows("firm_registrations")
            if f["responsible_charge_license_id"] == license_id]


def set_firm_status(firm, new_status):
    old = firm["status"]
    if old == new_status:
        return False
    changes = {"status": new_status}
    if new_status == "LAPSED_NO_RESPONSIBLE_CHARGE":
        changes["lapsed_at"] = db.clock()
    elif new_status == "ACTIVE":
        changes["lapsed_at"] = None
    db.write(firm, **changes)
    if new_status in ("LAPSED_NO_RESPONSIBLE_CHARGE", "EXPIRED", "REVOKED"):
        void_draft_plans(firm)
    return True


def apply_firm_posture(firm):
    if firm["status"] == "REVOKED":
        return False
    return set_firm_status(firm, posture_for(firm))


def cascade_license_posture(license_row):
    """Recompute every firm posture that depends on this licence."""
    for firm in firms_for_license(license_row["id"]):
        apply_firm_posture(firm)


# ------------------------------------------------------- exam teardown helpers
def release_appointment(appointment, terminal):
    db.write(appointment, status=terminal)
    center = db.get("test_centers", appointment["test_center_id"])
    if center is not None:
        calc.refresh_seat_ledger(center)


def cancel_scheduled_appointments(authorization, terminal="CANCELLED_BY_BOARD"):
    cancelled = 0
    for appointment in calc.appointments_of_authorization(authorization["id"]):
        if appointment["status"] == "SCHEDULED":
            release_appointment(appointment, terminal)
            cancelled += 1
    return cancelled


def teardown_authorizations(application):
    """Cancel live authorizations on the file and release every held seat."""
    for authorization in calc.authorizations_of(application["id"]):
        if authorization["status"] in ("APPROVED_TO_SIT", "SCHEDULED"):
            db.write(authorization, status="CANCELLED")
            cancel_scheduled_appointments(authorization)


# ------------------------------------------------------------- licence expiry
def expire_license(license_row):
    db.write(license_row, status="EXPIRED",
             reinstatement_eligible_until=add_days(
                 license_row["current_period_end"], calc.REINSTATEMENT_GRACE_DAYS))
    recompute_active_license_number(license_row["engineer_id"])


# ------------------------------------------------------------------ clock sweep
def advance_clock(new_value):
    db.set_clock(new_value)
    summary = {
        "expired_authorization_count": 0,
        "expired_license_count": 0,
        "expired_firm_count": 0,
        "cancelled_appointment_count": 0,
        "lapsed_firm_count": 0,
    }

    # Stage one: examination authorizations whose envelope has lapsed.
    for authorization in db.all_rows("exam_authorizations"):
        if authorization["status"] not in ("APPROVED_TO_SIT", "SCHEDULED", "FAILED"):
            continue
        expires_at = authorization["authorization_expires_at"]
        if expires_at is None or not (expires_at < new_value):
            continue
        db.write(authorization, status="EXPIRED")
        summary["expired_authorization_count"] += 1
        summary["cancelled_appointment_count"] += cancel_scheduled_appointments(
            authorization)

    # Stage two: licences whose current period has run out.
    for license_row in db.all_rows("licenses"):
        if license_row["status"] != "ACTIVE":
            continue
        period_end = license_row["current_period_end"]
        if period_end is None or not (period_end < new_value):
            continue
        expire_license(license_row)
        summary["expired_license_count"] += 1
        for firm in firms_for_license(license_row["id"]):
            if firm["status"] == "ACTIVE":
                set_firm_status(firm, "LAPSED_NO_RESPONSIBLE_CHARGE")
                summary["lapsed_firm_count"] += 1

    # Stage three: firm registrations whose own registration has run out.
    for firm in db.all_rows("firm_registrations"):
        if firm["status"] not in ("ACTIVE", "LAPSED_NO_RESPONSIBLE_CHARGE"):
            continue
        expires_at = firm["registration_expires_at"]
        if expires_at is None or not (expires_at < new_value):
            continue
        set_firm_status(firm, "EXPIRED")
        summary["expired_firm_count"] += 1

    return summary
