"""Flat filtered-list reads + flat single-resource GETs (PRD 2.5).

Reverse-reachability reads: resolve children from a parent FK without walking
the nested path. Same envelope, pagination, and Investor scoping as nested reads.
"""
from flask import Blueprint

from db import db
from errors import raise_error
from middleware import (
    SPONSOR, COMPLIANCE, AGENT, INVESTOR, ALL_ROLES, endpoint,
)
from response import success_list, success_object
from serializers import (
    ser_offering, ser_subscription, ser_document, ser_capital_call,
    ser_contribution, ser_quarterly_report, ser_distribution,
    ser_distribution_line, ser_capital_event, ser_k1_package,
    ser_transfer_request, ser_portal_session,
)
from services.domain import sorted_items
from validate import pagination, apply_filters

bp = Blueprint("flat", __name__)
RS = {"strict_slashes": False}


def _list(collection, serializer, filters, pre=None):
    limit, offset = pagination()
    items = list(db[collection].values())
    if pre is not None:
        items = [i for i in items if pre(i)]
    items = apply_filters(sorted_items(items), filters)
    page = items[offset:offset + limit]
    return success_list([serializer(o) for o in page], len(items), limit, offset)


def _one(collection, rid, serializer, error_id, pre=None):
    o = db[collection].get(rid)
    if o is None or (pre is not None and not pre(o)):
        raise_error(error_id, f"{collection} id not found: {rid}")
    return success_object(serializer(o))


def _owns(caller, sub):
    return caller.role != INVESTOR or sub["investor_id"] == caller.user_id


# --- Offerings ---

@bp.route("/offerings", methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def flat_offerings(caller):
    return _list("offerings", ser_offering, {
        "syndication_id": "syndication_id",
        "property_id": "property_id",
        "status": "status",
    })


@bp.route("/offerings/<offeringId>", methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def flat_offering(caller, offeringId):
    return _one("offerings", offeringId, ser_offering, "ERR_OFFERING_NOT_FOUND")


# --- Subscriptions ---

@bp.route("/subscriptions", methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def flat_subscriptions(caller):
    pre = None
    if caller.role == INVESTOR:
        pre = lambda s: s["investor_id"] == caller.user_id
    return _list("subscriptions", ser_subscription, {
        "offering_id": "offering_id",
        "investor_id": "investor_id",
        "status": "status",
    }, pre=pre)


@bp.route("/subscriptions/<subscriptionId>", methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def flat_subscription(caller, subscriptionId):
    pre = None
    if caller.role == INVESTOR:
        pre = lambda s: s["investor_id"] == caller.user_id
    return _one("subscriptions", subscriptionId, ser_subscription,
                "ERR_SUBSCRIPTION_NOT_FOUND", pre=pre)


# --- Documents ---

def _doc_visible(caller, doc):
    if caller.role != INVESTOR:
        return True
    sub = db["subscriptions"].get(doc["subscription_id"])
    return sub is not None and sub["investor_id"] == caller.user_id


@bp.route("/documents", methods=["GET"], **RS)
@endpoint(SPONSOR, COMPLIANCE, INVESTOR)
def flat_documents(caller):
    return _list("documents", ser_document, {
        "subscription_id": "subscription_id",
        "doc_type": "doc_type",
        "review_status": "review_status",
    }, pre=lambda d: _doc_visible(caller, d))


@bp.route("/documents/<documentId>", methods=["GET"], **RS)
@endpoint(SPONSOR, COMPLIANCE, INVESTOR)
def flat_document(caller, documentId):
    return _one("documents", documentId, ser_document, "ERR_DOCUMENT_NOT_FOUND",
                pre=lambda d: _doc_visible(caller, d))


# --- Capital calls ---

@bp.route("/capital-calls", methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def flat_capital_calls(caller):
    return _list("capital_calls", ser_capital_call, {
        "offering_id": "offering_id",
        "status": "status",
    })


@bp.route("/capital-calls/<capitalCallId>", methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def flat_capital_call(caller, capitalCallId):
    return _one("capital_calls", capitalCallId, ser_capital_call,
                "ERR_CAPITAL_CALL_NOT_FOUND")


# --- Contributions ---

@bp.route("/contributions", methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def flat_contributions(caller):
    return _list("contributions", ser_contribution, {
        "capital_call_id": "capital_call_id",
        "subscription_id": "subscription_id",
        "status": "status",
    })


@bp.route("/contributions/<contributionId>", methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def flat_contribution(caller, contributionId):
    return _one("contributions", contributionId, ser_contribution,
                "ERR_CONTRIBUTION_NOT_FOUND")


# --- Quarterly reports ---

@bp.route("/quarterly-reports", methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def flat_reports(caller):
    return _list("quarterly_reports", ser_quarterly_report, {
        "offering_id": "offering_id",
        "report_year": "report_year",
        "report_quarter": "report_quarter",
        "status": "status",
    })


@bp.route("/quarterly-reports/<quarterlyReportId>", methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def flat_report(caller, quarterlyReportId):
    return _one("quarterly_reports", quarterlyReportId, ser_quarterly_report,
                "ERR_QUARTERLY_REPORT_NOT_FOUND")


# --- Distributions ---

@bp.route("/distributions", methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def flat_distributions(caller):
    return _list("distributions", ser_distribution, {
        "offering_id": "offering_id",
        "quarterly_report_id": "quarterly_report_id",
        "capital_event_id": "capital_event_id",
        "status": "status",
        "distribution_kind": "distribution_kind",
    })


@bp.route("/distributions/<distributionId>", methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def flat_distribution(caller, distributionId):
    return _one("distributions", distributionId, ser_distribution,
                "ERR_DISTRIBUTION_NOT_FOUND")


# --- Distribution lines ---

@bp.route("/distribution-lines", methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def flat_lines(caller):
    return _list("distribution_lines", ser_distribution_line, {
        "distribution_id": "distribution_id",
        "subscription_id": "subscription_id",
    })


@bp.route("/distribution-lines/<lineId>", methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def flat_line(caller, lineId):
    return _one("distribution_lines", lineId, ser_distribution_line, "ERR_NOT_FOUND")


# --- Capital events ---

@bp.route("/capital-events", methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def flat_events(caller):
    return _list("capital_events", ser_capital_event, {
        "property_id": "property_id",
        "event_kind": "event_kind",
        "status": "status",
    })


@bp.route("/capital-events/<capitalEventId>", methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def flat_event(caller, capitalEventId):
    return _one("capital_events", capitalEventId, ser_capital_event,
                "ERR_CAPITAL_EVENT_NOT_FOUND")


# --- K-1 packages ---

@bp.route("/k1-packages", methods=["GET"], **RS)
@endpoint(SPONSOR, COMPLIANCE, AGENT)
def flat_k1s(caller):
    return _list("k1_packages", ser_k1_package, {
        "offering_id": "offering_id",
        "tax_year": "tax_year",
        "status": "status",
    })


@bp.route("/k1-packages/<k1PackageId>", methods=["GET"], **RS)
@endpoint(SPONSOR, COMPLIANCE, AGENT)
def flat_k1(caller, k1PackageId):
    return _one("k1_packages", k1PackageId, ser_k1_package, "ERR_K1_PACKAGE_NOT_FOUND")


# --- Transfer requests ---

def _tr_visible(caller, tr):
    if caller.role != INVESTOR:
        return True
    sub = db["subscriptions"].get(tr["from_subscription_id"])
    return sub is not None and sub["investor_id"] == caller.user_id


@bp.route("/transfer-requests", methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def flat_transfers(caller):
    return _list("transfer_requests", ser_transfer_request, {
        "from_subscription_id": "from_subscription_id",
        "to_investor_id": "to_investor_id",
        "status": "status",
    }, pre=lambda t: _tr_visible(caller, t))


@bp.route("/transfer-requests/<transferRequestId>", methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def flat_transfer(caller, transferRequestId):
    return _one("transfer_requests", transferRequestId, ser_transfer_request,
                "ERR_TRANSFER_REQUEST_NOT_FOUND",
                pre=lambda t: _tr_visible(caller, t))


# --- Portal sessions ---

@bp.route("/portal-sessions", methods=["GET"], **RS)
@endpoint(SPONSOR, COMPLIANCE)
def flat_sessions(caller):
    return _list("portal_sessions", ser_portal_session, {"investor_id": "investor_id"})


@bp.route("/portal-sessions/<sessionId>", methods=["GET"], **RS)
@endpoint(SPONSOR, COMPLIANCE, INVESTOR)
def flat_session(caller, sessionId):
    o = db["portal_sessions"].get(sessionId)
    if o is None or (caller.role == INVESTOR and o["investor_id"] != caller.user_id):
        raise_error("ERR_NOT_FOUND", f"portal session not found: {sessionId}")
    return success_object(ser_portal_session(o))
