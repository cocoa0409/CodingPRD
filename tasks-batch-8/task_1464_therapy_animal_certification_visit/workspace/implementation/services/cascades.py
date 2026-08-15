"""Cascade-down and bubble-up state propagation (PRD §2.8)."""
from datetime import timedelta

from db import store
from services import credits
from services.records import touch
from util import now_iso, today, parse_date


# ---------------------------------------------------------------------------
# Visit cancellation primitive
# ---------------------------------------------------------------------------

def cancel_visit_record(visit, reason):
    """Cancel a SCHEDULED visit: stamps, workload recompute, request compensation.
    Does not apply the handler late-cancel penalty (that lives in the route)."""
    if visit["lifecycle_status"] != "SCHEDULED":
        return
    visit["lifecycle_status"] = "CANCELLED"
    visit["cancel_reason"] = reason
    visit["cancelled_at"] = now_iso()
    touch(visit)
    team = store.teams.get(visit["team_id"])
    if team is not None:
        animal = store.animals.get(team["animal_id"])
        if animal is not None:
            credits.recompute_animal_workloads(animal)
    _reopen_backed_request(visit)


def _reopen_backed_request(visit):
    """Request-backed cancelled/no-show visit: ACCEPTED -> OPEN, offer fields cleared."""
    req_id = visit.get("request_id")
    if not req_id:
        return
    req = store.visit_requests.get(req_id)
    if req is not None and req["status"] == "ACCEPTED":
        req["status"] = "OPEN"
        req["offered_team_id"] = None
        req["offered_at"] = None
        req["offer_expires_at"] = None
        touch(req)


def cancel_scheduled_visits_of_team(team_id, reason):
    for v in list(store.visits.values()):
        if v["team_id"] == team_id and v["lifecycle_status"] == "SCHEDULED":
            cancel_visit_record(v, reason)


def cancel_scheduled_visits_of_facility(facility_id, reason):
    for v in list(store.visits.values()):
        if v["facility_id"] == facility_id and v["lifecycle_status"] == "SCHEDULED":
            cancel_visit_record(v, reason)


# ---------------------------------------------------------------------------
# Certification transitions with cascades
# ---------------------------------------------------------------------------

def suspend_certification(cert, reason, suspension_until=None,
                          visit_cancel_reason="CERT_SUSPENDED"):
    """Certification ACTIVE|RENEWAL_DUE -> SUSPENDED with full cascade.

    `visit_cancel_reason` is the cancel_reason stamped on the team's cancelled
    SCHEDULED visits: CERT_SUSPENDED for ordinary/insurance-lapse/late-cancel
    suspensions (PRD §3.3, §3.5), INCIDENT_PRECAUTION for the incident
    escalation cascade (PRD §3.9)."""
    if cert["status"] not in ("ACTIVE", "RENEWAL_DUE"):
        return False
    cert["status"] = "SUSPENDED"
    cert["suspension_reason"] = reason
    cert["suspension_until"] = suspension_until
    touch(cert)
    team = store.teams.get(cert["team_id"])
    if team is not None:
        if team["status"] == "ACTIVE":
            team["status"] = "SUSPENDED"
            touch(team)
        cancel_scheduled_visits_of_team(team["id"], visit_cancel_reason)
    return True


def revoke_certification(cert):
    """Certification -> REVOKED; team DISSOLVED; SCHEDULED visits cancelled."""
    if cert["status"] not in ("ACTIVE", "RENEWAL_DUE", "SUSPENDED"):
        return False
    cert["status"] = "REVOKED"
    touch(cert)
    team = store.teams.get(cert["team_id"])
    if team is not None:
        cancel_scheduled_visits_of_team(team["id"], "CERT_REVOKED")
        if team["status"] != "DISSOLVED":
            team["status"] = "DISSOLVED"
            touch(team)
    return True


def activate_certification_bubble(cert):
    """Bubble-up on activation: Team FORMING->ACTIVE, Animal REGISTERED->ACTIVE."""
    team = store.teams.get(cert["team_id"])
    if team is not None:
        if team["status"] == "FORMING":
            team["status"] = "ACTIVE"
            touch(team)
        animal = store.animals.get(team["animal_id"])
        if animal is not None and animal["status"] == "REGISTERED":
            animal["status"] = "ACTIVE"
            touch(animal)


def reinstate_certification_bubble(cert):
    team = store.teams.get(cert["team_id"])
    if team is not None and team["status"] == "SUSPENDED":
        team["status"] = "ACTIVE"
        touch(team)


# ---------------------------------------------------------------------------
# Handler retirement cascade
# ---------------------------------------------------------------------------

def retire_handler_cascade(handler):
    for team in list(store.teams.values()):
        if team["handler_id"] == handler["id"] and team["status"] in ("FORMING", "ACTIVE", "SUSPENDED"):
            cancel_scheduled_visits_of_team(team["id"], "TEAM_DISSOLVED")
            team["status"] = "DISSOLVED"
            touch(team)


# ---------------------------------------------------------------------------
# Facility / agreement loss cascade
# ---------------------------------------------------------------------------

def facility_agreement_loss_cascade(facility):
    """Facility ACTIVE -> SUSPENDED; SCHEDULED visits cancelled (AGREEMENT_ENDED);
    OPEN/OFFERED requests of the facility -> WITHDRAWN."""
    if facility["status"] == "ACTIVE":
        facility["status"] = "SUSPENDED"
        touch(facility)
    cancel_scheduled_visits_of_facility(facility["id"], "AGREEMENT_ENDED")
    for req in list(store.visit_requests.values()):
        if req["facility_id"] == facility["id"] and req["status"] in ("OPEN", "OFFERED"):
            req["status"] = "WITHDRAWN"
            touch(req)


def terminate_active_agreement(agreement, reason):
    """Agreement ACTIVE -> TERMINATED plus the agreement-loss cascade."""
    agreement["status"] = "TERMINATED"
    agreement["terminated_reason"] = reason
    touch(agreement)
    facility = store.facilities.get(agreement["facility_id"])
    if facility is not None:
        facility_agreement_loss_cascade(facility)


# ---------------------------------------------------------------------------
# Insurance-policy cancellation cascade
# ---------------------------------------------------------------------------

def policy_cancellation_cascade(handler):
    """After a policy is cancelled: for each certification of the handler's teams
    in ACTIVE/RENEWAL_DUE with no remaining adequate ACTIVE policy, suspend with
    INSURANCE_LAPSE (which cascades to team + visits + requests)."""
    from services.gates import active_policies
    today_d = today()
    remaining = [p for p in active_policies(handler["id"], today_d)
                 if p["coverage_cents"] >= 100000000]
    if remaining:
        return
    for team in list(store.teams.values()):
        if team["handler_id"] != handler["id"]:
            continue
        for cert in list(store.certifications.values()):
            if cert["team_id"] == team["id"] and cert["status"] in ("ACTIVE", "RENEWAL_DUE"):
                suspend_certification(cert, "INSURANCE_LAPSE")


# ---------------------------------------------------------------------------
# Incident escalation precaution cascade
# ---------------------------------------------------------------------------

def incident_escalation_cascade(visit):
    """Animal WELFARE_HOLD (14d precaution), certification INCIDENT_PRECAUTION
    suspension, team suspension, SCHEDULED visits cancelled (INCIDENT_PRECAUTION),
    request-backed visits' requests reopened."""
    from util import now_dt, fmt_dt
    team = store.teams.get(visit["team_id"])
    if team is None:
        return
    animal = store.animals.get(team["animal_id"])
    if animal is not None and animal["status"] == "ACTIVE":
        animal["status"] = "WELFARE_HOLD"
        animal["welfare_hold_until"] = fmt_dt(now_dt() + timedelta(days=14))
        animal["welfare_hold_reason"] = "INCIDENT_PRECAUTION"
        touch(animal)
    cert = None
    for c in store.certifications.values():
        if c["team_id"] == team["id"] and c["status"] in ("ACTIVE", "RENEWAL_DUE"):
            cert = c
            break
    if cert is not None:
        suspend_certification(cert, "INCIDENT_PRECAUTION",
                              visit_cancel_reason="INCIDENT_PRECAUTION")
    elif team["status"] == "ACTIVE":
        # No cert to suspend (defensive); still drop the team and cancel visits.
        team["status"] = "SUSPENDED"
        touch(team)
        cancel_scheduled_visits_of_team(team["id"], "INCIDENT_PRECAUTION")


def incident_resolution_effects(incident, resolution_code, suspension_days):
    """Apply resolution-code side effects (PRD §3.9)."""
    visit = store.visits.get(incident["visit_id"])
    if visit is None:
        return
    team = store.teams.get(visit["team_id"])
    animal = store.animals.get(team["animal_id"]) if team else None
    cert = None
    if team is not None:
        for c in store.certifications.values():
            if c["team_id"] == team["id"]:
                cert = c
                break

    if resolution_code in ("NO_ACTION", "WARNING"):
        # Release precaution holds with no gate re-check; cancelled visits stay cancelled.
        if (animal is not None and animal["status"] == "WELFARE_HOLD"
                and animal.get("welfare_hold_reason") == "INCIDENT_PRECAUTION"):
            animal["status"] = "ACTIVE"
            animal["welfare_hold_until"] = None
            animal["welfare_hold_reason"] = None
            touch(animal)
        if (cert is not None and cert["status"] == "SUSPENDED"
                and cert.get("suspension_reason") == "INCIDENT_PRECAUTION"):
            cert["status"] = "ACTIVE"
            cert["suspension_reason"] = None
            cert["suspension_until"] = None
            touch(cert)
            if team is not None and team["status"] == "SUSPENDED":
                team["status"] = "ACTIVE"
                touch(team)
        if resolution_code == "WARNING" and team is not None:
            team["warning_count"] = team.get("warning_count", 0) + 1
            touch(team)

    elif resolution_code == "SUSPENSION":
        until = today() + timedelta(days=suspension_days)
        if cert is not None:
            if cert["status"] in ("ACTIVE", "RENEWAL_DUE", "SUSPENDED"):
                already_suspended = cert["status"] == "SUSPENDED"
                cert["status"] = "SUSPENDED"
                cert["suspension_reason"] = "INCIDENT_SUSPENSION"
                cert["suspension_until"] = until.isoformat()
                touch(cert)
                if team is not None and team["status"] == "ACTIVE" and not already_suspended:
                    team["status"] = "SUSPENDED"
                    touch(team)
                if not already_suspended:
                    cancel_scheduled_visits_of_team(team["id"], "CERT_SUSPENDED")
        if animal is not None and animal["status"] == "WELFARE_HOLD":
            from util import fmt_dt, now_dt
            animal["welfare_hold_until"] = fmt_dt(now_dt() + timedelta(days=suspension_days))
            touch(animal)

    elif resolution_code == "REVOCATION":
        if cert is not None and cert["status"] in ("ACTIVE", "RENEWAL_DUE", "SUSPENDED"):
            revoke_certification(cert)
        elif team is not None and team["status"] != "DISSOLVED":
            cancel_scheduled_visits_of_team(team["id"], "CERT_REVOKED")
            team["status"] = "DISSOLVED"
            touch(team)
        if animal is not None and animal["status"] == "WELFARE_HOLD":
            animal["status"] = "ACTIVE"
            animal["welfare_hold_until"] = None
            animal["welfare_hold_reason"] = None
            touch(animal)
