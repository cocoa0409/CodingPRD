"""Deterministic time-based transitions run against the logical clock.

Pinned order (PRD §2.4):
  1. offer expirations
  2. stale visit-request expirations
  3. evaluation expirations (unscheduled requests, lapsed appeal windows)
  4. vaccination-record, insurance-policy, orientation-record expirations
  5. certifications marked RENEWAL_DUE, then overdue ones EXPIRED
  6. agreement expiration with facility cascade
  7. visit no-show marking
  8. deemed-verified reconciliation
  9. welfare-hold auto-release
"""
from datetime import timedelta

from db import store
from services import cascades, credits
from services.records import touch
from util import now_dt, today, parse_date, parse_datetime


def run_sweeps():
    now = now_dt()
    today_d = now.date()
    counts = {
        "evaluations_expired": 0,
        "certifications_marked_renewal_due": 0,
        "certifications_expired": 0,
        "vaccinations_expired": 0,
        "policies_expired": 0,
        "orientations_expired": 0,
        "agreements_expired": 0,
        "offers_expired": 0,
        "requests_expired": 0,
        "visits_marked_no_show": 0,
        "visits_deemed_verified": 0,
        "welfare_holds_released": 0,
    }

    # --- 1. Offer expirations: OFFERED and now > offer_expires_at -> OPEN ---
    for req in list(store.visit_requests.values()):
        if req["status"] == "OFFERED" and req.get("offer_expires_at"):
            if now > parse_datetime(req["offer_expires_at"]):
                req["status"] = "OPEN"
                req["offered_team_id"] = None
                req["offered_at"] = None
                req["offer_expires_at"] = None
                # Sweep offer-expiry does NOT increment decline_count.
                touch(req)
                counts["offers_expired"] += 1

    # --- 2. Visit-request expirations: OPEN and requested_end < now -> EXPIRED ---
    for req in list(store.visit_requests.values()):
        if req["status"] == "OPEN" and parse_datetime(req["requested_end"]) < now:
            req["status"] = "EXPIRED"
            req["expired_on"] = today_d.isoformat()
            touch(req)
            counts["requests_expired"] += 1

    # --- 3. Evaluation expirations ---
    for ev in list(store.evaluations.values()):
        if ev["status"] == "REQUESTED":
            if now > parse_datetime(ev["requested_at"]) + timedelta(days=60):
                ev["status"] = "EXPIRED"
                touch(ev)
                counts["evaluations_expired"] += 1
        elif ev["status"] == "FAILED" and ev.get("failed_at"):
            if now > parse_datetime(ev["failed_at"]) + timedelta(days=14):
                ev["status"] = "EXPIRED"
                touch(ev)
                counts["evaluations_expired"] += 1

    # --- 4. Vaccination / policy / orientation expirations ---
    for rec in list(store.vaccinations.values()):
        if rec["status"] == "VALID" and today_d > parse_date(rec["valid_until"]):
            rec["status"] = "EXPIRED"
            touch(rec)
            counts["vaccinations_expired"] += 1
    for pol in list(store.policies.values()):
        if pol["status"] == "ACTIVE" and today_d > parse_date(pol["effective_until"]):
            pol["status"] = "EXPIRED"
            touch(pol)
            counts["policies_expired"] += 1
    for ori in list(store.orientations.values()):
        if ori["status"] == "COMPLETED" and ori.get("expires_on") and today_d > parse_date(ori["expires_on"]):
            ori["status"] = "EXPIRED"
            touch(ori)
            counts["orientations_expired"] += 1

    # --- 5a. Certifications: ACTIVE -> RENEWAL_DUE in the 60-day window ---
    for cert in list(store.certifications.values()):
        if cert["status"] == "ACTIVE" and cert.get("expires_on"):
            exp = parse_date(cert["expires_on"])
            if exp - timedelta(days=60) <= today_d <= exp:
                cert["status"] = "RENEWAL_DUE"
                touch(cert)
                counts["certifications_marked_renewal_due"] += 1
    # --- 5b. Certifications past expiry: ACTIVE / RENEWAL_DUE -> EXPIRED ---
    for cert in list(store.certifications.values()):
        if cert["status"] in ("ACTIVE", "RENEWAL_DUE") and cert.get("expires_on"):
            if today_d > parse_date(cert["expires_on"]):
                cert["status"] = "EXPIRED"
                touch(cert)
                counts["certifications_expired"] += 1

    # --- 6. Agreement expiration with facility cascade ---
    for ag in list(store.agreements.values()):
        if ag["status"] == "ACTIVE" and today_d > parse_date(ag["end_on"]):
            ag["status"] = "EXPIRED"
            touch(ag)
            facility = store.facilities.get(ag["facility_id"])
            if facility is not None:
                cascades.facility_agreement_loss_cascade(facility)
            counts["agreements_expired"] += 1

    # --- 7. Visit no-show: SCHEDULED and now > scheduled_end + 30 minutes ---
    for visit in list(store.visits.values()):
        if visit["lifecycle_status"] != "SCHEDULED":
            continue
        if now > parse_datetime(visit["scheduled_end"]) + timedelta(minutes=30):
            visit["lifecycle_status"] = "NO_SHOW"
            touch(visit)
            team = store.teams.get(visit["team_id"])
            if team is not None:
                team["no_show_count"] = team.get("no_show_count", 0) + 1
                touch(team)
                animal = store.animals.get(team["animal_id"])
                if animal is not None:
                    credits.recompute_animal_workloads(animal)
            cascades._reopen_backed_request(visit)
            counts["visits_marked_no_show"] += 1

    # --- 8. Deemed-verified: COMPLETED + UNVERIFIED and now > actual_end + 14d ---
    for visit in list(store.visits.values()):
        if (visit["lifecycle_status"] == "COMPLETED"
                and visit["verification_status"] == "UNVERIFIED"
                and visit.get("actual_end")):
            if now > parse_datetime(visit["actual_end"]) + timedelta(days=14):
                visit["verification_status"] = "VERIFIED"
                from util import fmt_dt
                visit["verified_at"] = fmt_dt(now)
                touch(visit)
                credits.reconcile_final_credit(visit, visit.get("actual_minutes") or 0)
                counts["visits_deemed_verified"] += 1

    # --- 9. Welfare-hold auto-release ---
    for animal in list(store.animals.values()):
        if animal["status"] != "WELFARE_HOLD" or not animal.get("welfare_hold_until"):
            continue
        if now <= parse_datetime(animal["welfare_hold_until"]):
            continue
        # Release only when no open incident exists on this animal's visits.
        team_ids = {t["id"] for t in store.teams.values() if t["animal_id"] == animal["id"]}
        visit_ids = {v["id"] for v in store.visits.values() if v["team_id"] in team_ids}
        open_incident = any(
            inc["visit_id"] in visit_ids and inc["status"] in ("FILED", "UNDER_REVIEW", "ESCALATED")
            for inc in store.incidents.values()
        )
        if open_incident:
            continue
        animal["status"] = "ACTIVE"
        animal["welfare_hold_until"] = None
        animal["welfare_hold_reason"] = None
        touch(animal)
        counts["welfare_holds_released"] += 1

    return counts
