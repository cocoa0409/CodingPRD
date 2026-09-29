"""The compliance sweep: steps S1 -> S2 -> S3 -> S4 (PRD 3.9)."""

import db
from services import cascade
from services import health_center as hc_svc


def _has_accepted_plan(finding_id):
    for plan in db.db.corrective_action_plans.values():
        if plan["site_visit_finding_id"] == finding_id and plan["status"] == "ACCEPTED":
            return True
    return False


def _health_centers_of_patient(patient_id):
    out = set()
    for enc in db.db.encounters.values():
        if enc["patient_id"] != patient_id:
            continue
        site = db.db.service_sites.get(enc["service_site_id"])
        if site is not None:
            out.add(site["health_center_id"])
    return out


def run():
    clock = db.now()
    touched = set()
    before = {hc["id"]: hc_svc.derived(hc) for hc in db.db.health_centers.values()}

    expired_verification_count = 0
    escalated_finding_count = 0
    expired_fee_schedule_count = 0

    # S1 — expire documentation.
    for verification in db.all_rows("income_verifications"):
        if verification["status"] == "VERIFIED" and verification["expires_at"] <= clock:
            verification["status"] = "EXPIRED"
            db.touch(verification)
            expired_verification_count += 1
            patient = db.db.patients.get(verification["patient_id"])
            if patient is not None:
                db.touch(patient)
                touched |= _health_centers_of_patient(patient["id"])

    # S2 — escalate findings, firing the depth-5 escalation cascade.
    for finding in db.all_rows("site_visit_findings"):
        if finding["severity"] != "CONDITION":
            continue
        if finding["status"] not in ("OPEN", "CAP_SUBMITTED"):
            continue
        if finding["cap_due_at"] > clock:
            continue
        if _has_accepted_plan(finding["id"]):
            continue
        cascade.escalate_finding(finding)
        escalated_finding_count += 1
        touched.add(finding["health_center_id"])

    # S3 — retire schedules (review_status is derived on every read).
    for schedule in db.all_rows("fee_schedules"):
        if schedule["status"] == "ADOPTED" and schedule["effective_end"] <= clock:
            schedule["status"] = "EXPIRED"
            db.touch(schedule)
            expired_fee_schedule_count += 1
            touched.add(schedule["health_center_id"])

    # S4 — recompute every grantee touched by the first three steps, plus every
    # grantee whose derived values moved.
    recomputed = 0
    for hc in db.all_rows("health_centers"):
        changed = hc_svc.derived(hc) != before.get(hc["id"])
        if changed or hc["id"] in touched:
            hc_svc.bump(hc)
            recomputed += 1

    return {
        "expired_verification_count": expired_verification_count,
        "escalated_finding_count": escalated_finding_count,
        "expired_fee_schedule_count": expired_fee_schedule_count,
        "recomputed_health_center_count": recomputed,
    }
