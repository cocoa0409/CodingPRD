"""Payroll audit and renewal offer endpoints (nested under policies)."""

from flask import request

from db import db
from errors import err
from middleware import require_roles
from response import success_list, success_object
from routes import bp
from services.posture import recompute_posture
from services.pricing import (
    loss_ratio_calculate,
    premium_calculate,
    renewal_premium_quote,
)
from util import (
    add_days,
    add_months,
    body,
    get_child,
    get_production,
    make_entity,
    now,
    paginate,
    req_dt,
    req_int,
    req_string,
    serialize,
    touch,
)
from routes.policies import get_policy

AUDIT_ROLES = {"BrokerAgent", "ProductionManager", "ExternalAuditor", "PlatformOperator"}
RENEWAL_ROLES = {"BrokerAgent", "ProductionManager", "UnderwriterAgent", "PlatformOperator"}
RENEWAL_TERMS = (6, 12, 18)
OFFER_EXPIRY_DAYS = 14


def get_audit(policy_id, audit_id):
    return get_child(db.payroll_audits, audit_id, "policy_id", policy_id, "PayrollAudit")


def get_offer(policy_id, offer_id):
    return get_child(db.renewal_offers, offer_id, "policy_id", policy_id, "RenewalOffer")


# ---------------------------------------------------------------------------
# Payroll audits
# ---------------------------------------------------------------------------

@bp.route("/productions/<id>/policies/<pid>/payroll-audits", methods=["POST"])
def create_payroll_audit(id, pid):
    require_roles({"ExternalAuditor", "PlatformOperator"})
    with db.lock:
        get_production(id)
        get_policy(id, pid)
        data = body()
        period_start = req_dt(data, "audit_period_start")
        period_end = req_dt(data, "audit_period_end")
        auditor_name = req_string(data, "auditor_name")
        reported_payroll_cents = req_int(data, "reported_payroll_cents")
        if period_end <= period_start:
            raise err("ERR_TEMPORAL_RANGE_INVALID",
                      "audit_period_end must be after audit_period_start")
        if reported_payroll_cents < 0:
            raise err("ERR_FISCAL_CONSTRAINT_VIOLATED",
                      "reported_payroll_cents must be zero or more")

        rec = make_entity({
            "policy_id": pid,
            "audit_period_start": period_start,
            "audit_period_end": period_end,
            "auditor_name": auditor_name,
            "reported_payroll_cents": reported_payroll_cents,
            "premium_delta_cents": None,
            "status": "SCHEDULED",
        })
        db.payroll_audits[rec["id"]] = rec
        return success_object(serialize(rec), status=201)


@bp.route("/productions/<id>/policies/<pid>/payroll-audits", methods=["GET"])
def list_payroll_audits(id, pid):
    require_roles(AUDIT_ROLES)
    get_production(id)
    get_policy(id, pid)
    status = request.args.get("status")
    records = [a for a in db.payroll_audits.values() if a["policy_id"] == pid]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    items, page = paginate(records)
    return success_list(items, page)


@bp.route("/productions/<id>/policies/<pid>/payroll-audits/<childId>", methods=["GET"])
def get_payroll_audit(id, pid, childId):
    require_roles(AUDIT_ROLES)
    get_production(id)
    get_policy(id, pid)
    rec = get_audit(pid, childId)
    return success_object(serialize(rec))


@bp.route("/productions/<id>/policies/<pid>/payroll-audits/<childId>/submit", methods=["POST"])
def submit_payroll_audit(id, pid, childId):
    require_roles({"ExternalAuditor"})
    with db.lock:
        get_production(id)
        get_policy(id, pid)
        audit = get_audit(pid, childId)
        if audit["status"] not in ("SCHEDULED", "DISPUTED"):
            raise err("ERR_INVALID_STATE",
                      "Audit must be SCHEDULED or DISPUTED to submit (current: %s)"
                      % audit["status"])
        audit["status"] = "SUBMITTED"
        touch(audit)
        return success_object(serialize(audit))


@bp.route("/productions/<id>/policies/<pid>/payroll-audits/<childId>/post", methods=["POST"])
def post_payroll_audit(id, pid, childId):
    require_roles({"BrokerAgent"})
    with db.lock:
        prod = get_production(id)
        pol = get_policy(id, pid)
        audit = get_audit(pid, childId)
        if audit["status"] != "SUBMITTED":
            raise err("ERR_INVALID_STATE",
                      "Audit must be SUBMITTED to post (current: %s)" % audit["status"])
        if pol["status"] not in ("ACTIVE", "EXPIRED"):
            raise err("ERR_REFERENCED_STATE_INVALID",
                      "Cannot post an audit against a policy in %s" % pol["status"])

        pol["audited_payroll_cents"] = audit["reported_payroll_cents"]
        pol["final_premium_cents"] = premium_calculate(prod, pol, audit["reported_payroll_cents"])
        touch(pol)
        audit["premium_delta_cents"] = (
            pol["final_premium_cents"] - (pol["provisional_premium_cents"] or 0)
        )
        audit["status"] = "POSTED"
        touch(audit)
        return success_object(serialize(audit))


@bp.route("/productions/<id>/policies/<pid>/payroll-audits/<childId>/dispute", methods=["POST"])
def dispute_payroll_audit(id, pid, childId):
    require_roles({"ProductionManager"})
    with db.lock:
        get_production(id)
        get_policy(id, pid)
        audit = get_audit(pid, childId)
        if audit["status"] != "SUBMITTED":
            raise err("ERR_INVALID_STATE",
                      "Audit must be SUBMITTED to dispute (current: %s)" % audit["status"])
        audit["status"] = "DISPUTED"
        touch(audit)
        return success_object(serialize(audit))


# ---------------------------------------------------------------------------
# Renewal offers
# ---------------------------------------------------------------------------

@bp.route("/productions/<id>/policies/<pid>/renewal-offers", methods=["POST"])
def create_renewal_offer(id, pid):
    require_roles({"UnderwriterAgent"})
    with db.lock:
        get_production(id)
        pol = get_policy(id, pid)
        data = body()
        term = data.get("renewal_term_months")
        if isinstance(term, bool) or not isinstance(term, int):
            raise err("ERR_INVALID_REQUEST",
                      "Field 'renewal_term_months' is required and must be an integer")
        if term not in RENEWAL_TERMS:
            raise err("ERR_INVALID_ENUM", "renewal_term_months must be one of [6, 12, 18]")

        ratio = loss_ratio_calculate(pol)
        offered = renewal_premium_quote(pol["provisional_premium_cents"], ratio)
        created = now()

        # A newer offer supersedes any prior OFFERED offer for this policy.
        for ro in db.renewal_offers.values():
            if ro["policy_id"] == pid and ro["status"] == "OFFERED":
                ro["status"] = "SUPERSEDED"
                touch(ro)

        rec = make_entity({
            "policy_id": pid,
            "offered_premium_cents": offered,
            "loss_ratio_pct": ratio,
            "renewal_term_months": term,
            "offer_expires_at": add_days(created, OFFER_EXPIRY_DAYS),
            "status": "OFFERED",
        })
        db.renewal_offers[rec["id"]] = rec
        return success_object(serialize(rec), status=201)


@bp.route("/productions/<id>/policies/<pid>/renewal-offers", methods=["GET"])
def list_renewal_offers(id, pid):
    require_roles(RENEWAL_ROLES)
    get_production(id)
    get_policy(id, pid)
    status = request.args.get("status")
    records = [r for r in db.renewal_offers.values() if r["policy_id"] == pid]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    items, page = paginate(records)
    return success_list(items, page)


@bp.route("/productions/<id>/policies/<pid>/renewal-offers/<childId>", methods=["GET"])
def get_renewal_offer(id, pid, childId):
    require_roles(RENEWAL_ROLES)
    get_production(id)
    get_policy(id, pid)
    rec = get_offer(pid, childId)
    return success_object(serialize(rec))


@bp.route("/productions/<id>/policies/<pid>/renewal-offers/<childId>/accept", methods=["POST"])
def accept_renewal_offer(id, pid, childId):
    require_roles({"ProductionManager"})
    with db.lock:
        get_production(id)
        pol = get_policy(id, pid)
        offer = get_offer(pid, childId)

        # An offer past its expiry refuses with the dedicated error even when
        # the clock sweep has already aged it out to EXPIRED.
        if now() >= offer["offer_expires_at"]:
            raise err("ERR_RENEWAL_OFFER_EXPIRED", "Renewal offer has expired")

        if offer["status"] != "OFFERED":
            raise err("ERR_INVALID_STATE",
                      "Offer must be OFFERED to accept (current: %s)" % offer["status"])

        data = body()
        expected = data.get("expected_policy_version")
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise err("ERR_INVALID_REQUEST",
                      "Field 'expected_policy_version' is required and must be an integer")
        if expected != pol["version"]:
            raise err("ERR_STALE_VERSION",
                      "expected_policy_version %s does not match current version %s"
                      % (expected, pol["version"]))

        if pol["status"] not in ("ACTIVE", "EXPIRED"):
            raise err("ERR_REFERENCED_STATE_INVALID",
                      "Policy must be ACTIVE or EXPIRED to accept a renewal (current: %s)"
                      % pol["status"])

        audit_pending = any(
            a["policy_id"] == pid and a["status"] in ("SCHEDULED", "SUBMITTED")
            for a in db.payroll_audits.values()
        )
        if audit_pending:
            raise err("ERR_AUDIT_PENDING_BLOCKS_RENEWAL",
                      "A payroll audit is still pending for this policy")

        pol["expiry_date"] = add_months(pol["expiry_date"], offer["renewal_term_months"])
        if pol["status"] == "EXPIRED":
            pol["status"] = "ACTIVE"
        pol["provisional_premium_cents"] = offer["offered_premium_cents"]
        pol["audited_payroll_cents"] = None
        pol["final_premium_cents"] = None
        touch(pol)

        offer["status"] = "ACCEPTED"
        touch(offer)
        recompute_posture(db.productions[id])
        return success_object(serialize(offer))


@bp.route("/productions/<id>/policies/<pid>/renewal-offers/<childId>/decline", methods=["POST"])
def decline_renewal_offer(id, pid, childId):
    require_roles({"ProductionManager"})
    with db.lock:
        get_production(id)
        get_policy(id, pid)
        offer = get_offer(pid, childId)
        if offer["status"] != "OFFERED":
            raise err("ERR_INVALID_STATE",
                      "Offer must be OFFERED to decline (current: %s)" % offer["status"])
        offer["status"] = "DECLINED"
        touch(offer)
        return success_object(serialize(offer))
