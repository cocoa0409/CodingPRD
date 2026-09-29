"""All read endpoints (PRD 4 GET rows)."""

from flask import Blueprint, request

import calc
from db import db, public
from middleware import (ALL_ROLES, ROLE_AUTHORITY_OFFICER, ROLE_CONCESSIONAIRE,
                        ROLE_INDEPENDENT_CERTIFIER, ROLE_LENDER_AGENT,
                        ROLE_PLATFORM_ADMIN, concession_of, concession_of_period,
                        event_of_dispute, get_action, get_claim, get_concession,
                        get_concessionaire, get_dispute, get_event, get_milestone,
                        get_period, get_refi, get_report, get_txn, owner_guard,
                        period_of_event, period_of_report, require_auth)
from response import listing, ok

bp = Blueprint("reads", __name__)

NON_CERTIFIER = (ROLE_PLATFORM_ADMIN, ROLE_AUTHORITY_OFFICER, ROLE_CONCESSIONAIRE,
                 ROLE_LENDER_AGENT)


def filtered(table, spec):
    rows = db.all(table)
    for param, field in spec.items():
        value = request.args.get(param)
        if value is None or value == "":
            continue
        rows = [r for r in rows if r.get(field) is not None and str(r.get(field)) == value]
    return rows


# ------------------------------------------------------------ concessionaires
@bp.get("/ppp/concessionaires/<row_id>")
def read_concessionaire(row_id):
    require_auth(*ALL_ROLES)
    return ok(public(get_concessionaire(row_id)))


@bp.get("/ppp/concessionaires")
def list_concessionaires():
    require_auth(ROLE_PLATFORM_ADMIN, ROLE_AUTHORITY_OFFICER, ROLE_LENDER_AGENT)
    return listing(filtered("concessionaires", {"status": "status"}))


# ------------------------------------------------------------ concessions
@bp.get("/ppp/concessions/<row_id>")
def read_concession(row_id):
    require_auth(*ALL_ROLES)
    concession = get_concession(row_id)
    owner_guard(concession)
    return ok(public(concession))


@bp.get("/ppp/concessions")
def list_concessions():
    require_auth(*NON_CERTIFIER)
    return listing(filtered("concessions", {
        "concessionaire_id": "concessionaire_id",
        "status": "status",
        "handback_status": "handback_status",
    }))


@bp.get("/ppp/concessions/<row_id>/payment-summary")
def read_payment_summary(row_id):
    require_auth(*NON_CERTIFIER)
    concession = get_concession(row_id)
    owner_guard(concession)
    return ok(calc.payment_summary(concession))


# ------------------------------------------------------------ drawdown milestones
@bp.get("/ppp/drawdown-milestones/<row_id>")
def read_milestone(row_id):
    require_auth(*ALL_ROLES)
    milestone = get_milestone(row_id)
    owner_guard(concession_of(milestone))
    return ok(public(milestone))


@bp.get("/ppp/drawdown-milestones")
def list_milestones():
    require_auth(*ALL_ROLES)
    return listing(filtered("milestones", {
        "concession_id": "concession_id",
        "status": "status",
    }))


# ------------------------------------------------------------ service periods
@bp.get("/ppp/service-periods/<row_id>")
def read_period(row_id):
    require_auth(*ALL_ROLES)
    period = get_period(row_id)
    owner_guard(concession_of_period(period))
    return ok(public(period))


@bp.get("/ppp/service-periods")
def list_periods():
    require_auth(*ALL_ROLES)
    return listing(filtered("periods", {
        "concession_id": "concession_id",
        "reporting_status": "reporting_status",
        "payment_status": "payment_status",
    }))


# ------------------------------------------------------------ performance reports
REPORT_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_AUTHORITY_OFFICER, ROLE_CONCESSIONAIRE,
                ROLE_INDEPENDENT_CERTIFIER)


@bp.get("/ppp/performance-reports/<row_id>")
def read_report(row_id):
    require_auth(*REPORT_ROLES)
    report = get_report(row_id)
    owner_guard(concession_of_period(period_of_report(report)))
    return ok(public(report))


@bp.get("/ppp/performance-reports")
def list_reports():
    require_auth(*REPORT_ROLES)
    return listing(filtered("reports", {
        "service_period_id": "service_period_id",
        "status": "status",
    }))


# ------------------------------------------------------------ deduction events
EVENT_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_AUTHORITY_OFFICER, ROLE_CONCESSIONAIRE,
               ROLE_LENDER_AGENT)


@bp.get("/ppp/deduction-events/<row_id>")
def read_event(row_id):
    require_auth(*EVENT_ROLES)
    event = get_event(row_id)
    owner_guard(concession_of_period(period_of_event(event)))
    return ok(public(event))


@bp.get("/ppp/deduction-events")
def list_events():
    require_auth(*EVENT_ROLES)
    return listing(filtered("events", {
        "service_period_id": "service_period_id",
        "performance_report_id": "performance_report_id",
        "deduction_type": "deduction_type",
        "status": "status",
    }))


# ------------------------------------------------------------ disputes
DISPUTE_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_AUTHORITY_OFFICER, ROLE_CONCESSIONAIRE)


@bp.get("/ppp/deduction-disputes/<row_id>")
def read_dispute(row_id):
    require_auth(*DISPUTE_ROLES)
    dispute = get_dispute(row_id)
    owner_guard(concession_of_period(period_of_event(event_of_dispute(dispute))))
    return ok(public(dispute))


@bp.get("/ppp/deduction-disputes")
def list_disputes():
    require_auth(*DISPUTE_ROLES)
    return listing(filtered("disputes", {
        "deduction_event_id": "deduction_event_id",
        "status": "status",
    }))


# ------------------------------------------------------------ relief claims
CLAIM_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_AUTHORITY_OFFICER, ROLE_CONCESSIONAIRE,
               ROLE_INDEPENDENT_CERTIFIER)


@bp.get("/ppp/relief-claims/<row_id>")
def read_claim(row_id):
    require_auth(*CLAIM_ROLES)
    claim = get_claim(row_id)
    owner_guard(concession_of(claim))
    return ok(public(claim))


@bp.get("/ppp/relief-claims")
def list_claims():
    require_auth(*CLAIM_ROLES)
    return listing(filtered("claims", {
        "concession_id": "concession_id",
        "claim_type": "claim_type",
        "status": "status",
    }))


# ------------------------------------------------------------ reserve ledger
@bp.get("/ppp/reserve-transactions/<row_id>")
def read_txn(row_id):
    require_auth(*ALL_ROLES)
    txn = get_txn(row_id)
    owner_guard(concession_of(txn))
    return ok(public(txn))


@bp.get("/ppp/reserve-transactions")
def list_txns():
    require_auth(*ALL_ROLES)
    return listing(filtered("reserve_txns", {
        "concession_id": "concession_id",
        "reverses_txn_id": "reverses_txn_id",
        "txn_type": "txn_type",
    }))


# ------------------------------------------------------------ refinancing
@bp.get("/ppp/refinancing-events/<row_id>")
def read_refi(row_id):
    require_auth(*NON_CERTIFIER)
    refi = get_refi(row_id)
    owner_guard(concession_of(refi))
    return ok(public(refi))


@bp.get("/ppp/refinancing-events")
def list_refis():
    require_auth(*NON_CERTIFIER)
    return listing(filtered("refis", {
        "concession_id": "concession_id",
        "status": "status",
    }))


# ------------------------------------------------------------ enforcement
@bp.get("/ppp/enforcement-actions/<row_id>")
def read_action(row_id):
    require_auth(*NON_CERTIFIER)
    action = get_action(row_id)
    owner_guard(concession_of(action))
    return ok(public(action))


@bp.get("/ppp/enforcement-actions")
def list_actions():
    require_auth(*NON_CERTIFIER)
    return listing(filtered("enforcements", {
        "concession_id": "concession_id",
        "escalated_to_action_id": "escalated_to_action_id",
        "action_type": "action_type",
        "status": "status",
    }))
