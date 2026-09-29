"""The deterministic nightly sweep run by POST /_clock/set_current_utc.

Fixed order (PRD 2.5):
  step 1  store the new instant
  step 2  expire every CERTIFIED certification whose expires_at is now in the
          past, vacating its unit
  step 3  mark every ASSESSED or PARTIALLY_PAID fee past its due_date DELINQUENT
  step 4  auto-waive every PRICE_APPROVED resale whose ROFR deadline's calendar
          day has fully elapsed
"""

import db
from services import lookup, project_svc


def run(new_now):
    # --- step 1 -----------------------------------------------------------
    db.set_logical_now(new_now)

    certifications_expired = 0
    fees_marked_delinquent = 0
    rofr_windows_auto_waived = 0

    # --- step 2 -----------------------------------------------------------
    for cert in db.all_rows(db.certifications):
        if cert.get("state") != "CERTIFIED":
            continue
        expires_at = cert.get("expires_at")
        if not expires_at:
            continue
        expiry_instant = db.parse_dt(expires_at)
        if expiry_instant is None or not (expiry_instant < new_now):
            continue
        cert["state"] = "EXPIRED"
        db.touch(cert)
        certifications_expired += 1

        unit = lookup.maybe("unit", cert.get("unit_id"))
        if unit is not None and unit.get("occupancy_status") == "OCCUPIED":
            unit["occupancy_status"] = "VACANT"
            unit["current_rent_cents"] = 0
            unit["occupant_household_id"] = None
            db.touch(unit)
            project = lookup.maybe("project", unit.get("project_id"))
            if project is not None:
                project_svc.refresh_posture(project)

    # --- step 3 -----------------------------------------------------------
    today = new_now.date()
    for fee in db.all_rows(db.in_lieu_fees):
        if fee.get("state") not in ("ASSESSED", "PARTIALLY_PAID"):
            continue
        due = db.parse_date_loose(fee.get("due_date"))
        if due is None or not (due < today):
            continue
        fee["state"] = "DELINQUENT"
        db.touch(fee)
        fees_marked_delinquent += 1

    # --- step 4 -----------------------------------------------------------
    for txn in db.all_rows(db.resale_transactions):
        if txn.get("state") != "PRICE_APPROVED":
            continue
        deadline = db.parse_dt(txn.get("rofr_deadline"))
        if deadline is None or not (deadline.date() < today):
            continue
        txn["state"] = "ROFR_WAIVED"
        txn["rofr_auto_waived"] = True
        db.touch(txn)
        rofr_windows_auto_waived += 1

    return {
        "current_utc": db.fmt_dt(new_now),
        "certifications_expired": certifications_expired,
        "fees_marked_delinquent": fees_marked_delinquent,
        "rofr_windows_auto_waived": rofr_windows_auto_waived,
    }
