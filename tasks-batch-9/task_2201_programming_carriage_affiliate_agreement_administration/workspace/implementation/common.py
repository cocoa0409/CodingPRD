"""Helpers shared by the route modules: listing, reads, OCC, SoD."""
from flask import request

from auth import enforce_scope, guard, resolve_distributor_of, scope_filter
from envelope import paginate, respond_object
from errors import ApiError
from lookup import all_of, must
from store import creation_order, db, serialize
from validation import peek

ALL_READ_ROLES = [
    "NetworkAdmin",
    "AffiliateSalesExec",
    "RevenueAccountant",
    "AuditManager",
    "RightsAdministrator",
    "DistributorLiaison",
]
BUSINESS_READ_ROLES = [
    "NetworkAdmin",
    "AffiliateSalesExec",
    "RevenueAccountant",
    "AuditManager",
    "DistributorLiaison",
]


def _matches(value, raw):
    if value is None:
        return False
    if isinstance(value, bool):
        return str(value).lower() == raw.lower()
    return str(value) == raw


def list_endpoint(kind, roles, filters):
    """Guard, filter, scope, order by created_at ASC, then page."""
    caller = guard(roles)
    records = all_of(kind)
    for param in filters:
        raw = request.args.get(param)
        if raw is None or raw == "":
            continue
        records = [r for r in records if _matches(r.get(param), raw)]
    records = scope_filter(caller, records, kind)
    return paginate(creation_order(records), serialize)


def read_endpoint(kind, roles, record_id):
    caller = guard(roles)
    record = must(kind, record_id)
    enforce_scope(caller, resolve_distributor_of(record, kind))
    return respond_object(serialize(record))


def ok(record):
    return respond_object(serialize(record))


def created(record):
    return respond_object(serialize(record), 201)


# ---------------------------------------------------------------------------
# optimistic concurrency (PRD 2.7) - evaluated as gauntlet rule 8
# ---------------------------------------------------------------------------
def check_occ(parent, supplied, error_id):
    if parent is None:
        return
    if supplied is None or int(supplied) != parent["version"]:
        raise ApiError(error_id, "stale parent revision")


# ---------------------------------------------------------------------------
# segregation of duties (PRD 2.1) - gauntlet rule 3, before request shape
# ---------------------------------------------------------------------------
def sod_report_review(caller, report_id):
    report = db.subscriber_reports.get(report_id)
    if report is None:
        return
    agreement = db.agreements.get(report["agreement_id"])
    if agreement is None:
        return
    if agreement.get("_executed_by") and agreement["_executed_by"] == caller.user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "the executor of an agreement may not review its subscriber reports",
        )


def sod_invoice_create(caller):
    kind = peek("invoice_kind")
    if kind != "AUDIT_RECOVERY":
        return
    engagement_id = peek("audit_engagement_id")
    engagement = db.audit_engagements.get(engagement_id)
    if engagement is None:
        return
    issuer = engagement.get("_findings_issued_by")
    if issuer and issuer == caller.user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "the issuer of an engagement's findings may not draft its recovery invoice",
        )


# ---------------------------------------------------------------------------
# distributor scope resolved from a request body (gauntlet rule 4)
# ---------------------------------------------------------------------------
def scope_from_body_agreement(caller):
    if not caller.is_liaison:
        return
    agreement = db.agreements.get(peek("agreement_id"))
    if agreement is None:
        return
    enforce_scope(caller, agreement["distributor_id"])


def scope_from_body_distributor(caller):
    if not caller.is_liaison:
        return
    distributor_id = peek("distributor_id")
    if distributor_id is None or distributor_id not in db.distributors:
        return
    enforce_scope(caller, distributor_id)


# ---------------------------------------------------------------------------
# action dispatch
# ---------------------------------------------------------------------------
def unknown_action(action):
    raise ApiError("ERR_INVALID_REQUEST", "unsupported action %s" % action)
