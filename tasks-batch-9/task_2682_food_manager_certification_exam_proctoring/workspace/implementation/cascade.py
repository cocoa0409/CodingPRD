"""Multi-entity side effects. Every touched entity is written in the same
request with its own version bump and updated_at refresh (PRD 2.8)."""
from decimal import Decimal

from errors import ApiError
import calc
from store import store

REFUNDABLE_CODE_STATUS = "AVAILABLE"
WITHDRAWABLE_REGISTRATION_STATUSES = ("FILED", "POSTED", "VERIFIED",
                                      "DELINQUENT")


# --- provider ledger -------------------------------------------------------

def recompute_balance(provider):
    provider["credit_balance_cents"] = (provider["lifetime_credited_cents"]
                                        - provider["lifetime_charged_cents"])


def credit_provider(provider, amount_cents):
    provider["lifetime_credited_cents"] += amount_cents
    recompute_balance(provider)
    store.touch(provider)


def check_credit(provider, amount_cents):
    if provider["credit_balance_cents"] < amount_cents:
        raise ApiError("ERR_INSUFFICIENT_CREDIT",
                       "the provider's balance does not cover the debit")


def debit_provider(provider, amount_cents):
    provider["lifetime_charged_cents"] += amount_cents
    recompute_balance(provider)
    store.touch(provider)


def void_credit_buckets(provider, net_credit_cents):
    """Bucket one repairs a negative balance, bucket two is ordinary credit.
    Both post to lifetime_credited_cents (PRD 3.3 step five)."""
    shortfall = 0
    if provider["credit_balance_cents"] < 0:
        shortfall = -provider["credit_balance_cents"]
    repair = min(net_credit_cents, shortfall)
    remainder = net_credit_cents - repair
    credit_provider(provider, repair + remainder)
    return repair, remainder


# --- batch inventory -------------------------------------------------------

def batch_codes(batch_id):
    return [c for c in store.codes.values() if c["batch_id"] == batch_id]


def recount_batch(batch):
    available = assigned = consumed = voided = 0
    for code in batch_codes(batch["id"]):
        status = code["status"]
        if status == "AVAILABLE":
            available += 1
        elif status == "ASSIGNED":
            assigned += 1
        elif status == "CONSUMED":
            consumed += 1
        else:
            voided += 1
    batch["available_count"] = available
    batch["assigned_count"] = assigned
    batch["consumed_count"] = consumed
    batch["voided_count"] = voided


# --- reserved minute bookkeeping ------------------------------------------

def reserve_interval(session, minutes):
    site = store.testing_sites.get(session["testing_site_id"]) \
        if session["testing_site_id"] else None
    if site is not None:
        site["reserved_seat_minutes"] += minutes
        store.touch(site)
    proctor = store.proctors.get(session["proctor_id"]) \
        if session["proctor_id"] else None
    if proctor is not None:
        proctor["reserved_minutes"] += minutes
        store.touch(proctor)


def release_interval(session, minutes):
    reserve_interval(session, -minutes)


# --- candidate posture -----------------------------------------------------

def set_compliance(candidate, status):
    candidate["compliance_status"] = status
    store.touch(candidate)


# --- proctor suspension release cascade -----------------------------------

def release_proctor_sessions(proctor):
    """Every SCHEDULED + ASSIGNED sitting of the proctor drops to
    PENDING_REPROCTOR with proctor_id cleared (PRD 3.2)."""
    for session in store.ordered(list(store.sessions.values())):
        if session["proctor_id"] != proctor["id"]:
            continue
        if session["session_status"] != "SCHEDULED":
            continue
        if session["proctoring_status"] != "ASSIGNED":
            continue
        session["proctoring_status"] = "PENDING_REPROCTOR"
        session["proctor_id"] = None
        proctor["reserved_minutes"] -= session["allowed_minutes"]
        store.touch(session)
    store.touch(proctor)


def suspend_proctor(proctor, reason):
    proctor["registration_status"] = "SUSPENDED"
    proctor["suspended_reason"] = reason
    store.touch(proctor)
    release_proctor_sessions(proctor)


def revoke_proctor(proctor):
    proctor["registration_status"] = "REVOKED"
    store.touch(proctor)
    release_proctor_sessions(proctor)


# --- certificate teardown -------------------------------------------------

def withdraw_registrations(certificate):
    for registration in store.ordered(list(store.registrations.values())):
        if registration["certificate_id"] != certificate["id"]:
            continue
        if registration["status"] not in WITHDRAWABLE_REGISTRATION_STATUSES:
            continue
        registration["status"] = "WITHDRAWN"
        store.touch(registration)


def revoke_certificate(certificate, reason):
    certificate["status"] = "REVOKED"
    certificate["revocation_reason"] = reason
    store.touch(certificate)
    candidate = store.candidates.get(certificate["candidate_id"])
    if candidate is not None:
        provider = store.providers.get(candidate["training_provider_id"])
        if provider is not None:
            credit_provider(provider, certificate["issuance_fee_cents"])
    withdraw_registrations(certificate)


def certificates_of_report(report_id):
    return [c for c in store.certificates.values()
            if c["score_report_id"] == report_id]


# --- the substantiation cascade (PRD 3.9) ---------------------------------

def substantiate(incident, session, user_id, resolution_note):
    incident["status"] = "SUBSTANTIATED"
    incident["resolved_by_user_id"] = user_id
    incident["resolution_note"] = resolution_note
    store.touch(incident)

    session["session_status"] = "INVALIDATED"
    session["proctoring_status"] = "COMPROMISED"
    store.touch(session)

    report = None
    for candidate_report in store.score_reports.values():
        if candidate_report["exam_session_id"] == session["id"]:
            report = candidate_report
            break
    if report is not None:
        report["status"] = "VOIDED"
        report["pass_flag"] = False
        store.touch(report)
        for certificate in store.ordered(certificates_of_report(report["id"])):
            if certificate["status"] == "ISSUED":
                revoke_certificate(certificate, "SCORE_VOIDED")

    candidate = store.candidates.get(session["candidate_id"])
    if candidate is not None:
        candidate["compliance_status"] = "NON_COMPLIANT"
        candidate["substantiated_incident_count"] += 1
        if incident["severity"] == "CRITICAL":
            candidate["security_hold"] = True
        store.touch(candidate)

    proctor = store.proctors.get(session["proctor_id"]) \
        if session["proctor_id"] else None
    if proctor is not None:
        proctor["substantiated_incident_weight_total"] += \
            incident["severity_weight"]
        proctor["risk_score"] = calc.lifetime_cumulative_risk(proctor)
        proctor["risk_variant_applied"] = "LIFETIME_CUMULATIVE"
        store.touch(proctor)
        if proctor["risk_score"] >= calc.RISK_SUSPENSION_THRESHOLD \
                and proctor["registration_status"] == "REGISTERED":
            suspend_proctor(proctor, "RISK_THRESHOLD_BREACH")


def dismiss(incident, session, user_id, resolution_note):
    incident["status"] = "DISMISSED"
    incident["resolved_by_user_id"] = user_id
    incident["resolution_note"] = resolution_note
    store.touch(incident)
    session["proctoring_status"] = "CLEARED"
    store.touch(session)


def new_interval(session, form, accommodation, start_at=None, delivery_mode=None):
    """(allowed_minutes, scheduled_end_at) for a proposed sitting shape."""
    from datetime import timedelta
    mode = delivery_mode or session["delivery_mode"]
    start = start_at or session["scheduled_start_at"]
    minutes = calc.compute_allowed_minutes(form, accommodation, mode)
    return minutes, start + timedelta(minutes=minutes)


def apply_retime(session, minutes, end_at):
    """Adjust reserved minute counters by the delta and write the interval."""
    delta = minutes - session["allowed_minutes"]
    if delta:
        reserve_interval(session, delta)
    session["allowed_minutes"] = minutes
    session["scheduled_end_at"] = end_at
    store.touch(session)
