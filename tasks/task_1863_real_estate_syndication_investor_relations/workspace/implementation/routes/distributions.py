"""Distributions and distribution lines: the four-tier waterfall (PRD 3.5)."""
from flask import Blueprint

import resolve
from db import db
from errors import raise_error
from middleware import SPONSOR, ALL_ROLES, endpoint
from response import success_list, success_object
from serializers import ser_distribution, ser_distribution_line
from services import domain
from services.calculations import waterfall_allocate
from services.domain import stamp_new, stamp_new_light, touch, sorted_items
from util import CLOCK, fmt_dt
from validate import (
    get_body, req_enum, req_int, opt_str, req_version, pagination, apply_filters,
)

bp = Blueprint("distributions", __name__)
RS = {"strict_slashes": False}

DIST_KINDS = ("QUARTERLY_OPERATING", "CAPITAL_EVENT")


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/distributions",
          methods=["POST"], **RS)
@endpoint(SPONSOR)
def create_distribution(caller, syndicationId, offeringId):
    resolve.offering(syndicationId, offeringId)
    body = get_body()
    kind = req_enum(body, "distribution_kind", DIST_KINDS)
    report_id = opt_str(body, "quarterly_report_id")
    event_id = opt_str(body, "capital_event_id")
    total = req_int(body, "total_distributable_cents")
    # Lineage is pinned by kind: exactly one source reference, the other null.
    if kind == "QUARTERLY_OPERATING":
        if report_id is None or body.get("capital_event_id") is not None:
            raise_error("ERR_INVALID_REQUEST",
                        "QUARTERLY_OPERATING requires quarterly_report_id and null capital_event_id")
        rep = db["quarterly_reports"].get(report_id)
        if rep is None or rep["offering_id"] != offeringId:
            raise_error("ERR_QUARTERLY_REPORT_NOT_FOUND",
                        f"quarterly report not found: {report_id}")
    else:
        if event_id is None or body.get("quarterly_report_id") is not None:
            raise_error("ERR_INVALID_REQUEST",
                        "CAPITAL_EVENT requires capital_event_id and null quarterly_report_id")
        if db["capital_events"].get(event_id) is None:
            raise_error("ERR_CAPITAL_EVENT_NOT_FOUND", f"capital event not found: {event_id}")
    d = {
        "offering_id": offeringId,
        "quarterly_report_id": report_id if kind == "QUARTERLY_OPERATING" else None,
        "capital_event_id": event_id if kind == "CAPITAL_EVENT" else None,
        "distribution_kind": kind,
        "total_distributable_cents": total,
        "status": "DRAFT",
        "calculated_at": None,
    }
    stamp_new(d)
    db["distributions"][d["id"]] = d
    return success_object(ser_distribution(d), 201)


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/distributions",
          methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def list_distributions(caller, syndicationId, offeringId):
    resolve.offering(syndicationId, offeringId)
    limit, offset = pagination()
    items = [d for d in db["distributions"].values() if d["offering_id"] == offeringId]
    items = apply_filters(sorted_items(items),
                          {"status": "status", "distribution_kind": "distribution_kind"})
    page = items[offset:offset + limit]
    return success_list([ser_distribution(o) for o in page], len(items), limit, offset)


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/distributions/<distributionId>",
          methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def get_distribution(caller, syndicationId, offeringId, distributionId):
    return success_object(ser_distribution(
        resolve.distribution(syndicationId, offeringId, distributionId)))


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/distributions/<distributionId>/calculate",
          methods=["POST"], **RS)
@endpoint(SPONSOR)
def calculate_distribution(caller, syndicationId, offeringId, distributionId):
    off = resolve.offering(syndicationId, offeringId)
    dist = resolve.distribution(syndicationId, offeringId, distributionId)
    if dist["status"] != "DRAFT":
        raise_error("ERR_INVALID_STATE",
                    f"cannot calculate a distribution in status {dist['status']}")
    if dist["distribution_kind"] == "QUARTERLY_OPERATING":
        rep = db["quarterly_reports"].get(dist["quarterly_report_id"])
        if rep is None or rep["status"] != "PUBLISHED":
            raise_error("ERR_REPORT_NOT_PUBLISHED",
                        "QUARTERLY_OPERATING distribution requires a PUBLISHED report")
    else:
        ev = db["capital_events"].get(dist["capital_event_id"])
        if ev is None or ev["status"] != "EXECUTED":
            raise_error("ERR_CAPITAL_EVENT_NOT_EXECUTED",
                        "CAPITAL_EVENT distribution requires an EXECUTED capital event")
    if dist["total_distributable_cents"] <= 0:
        raise_error("ERR_EMPTY_DISTRIBUTION_POOL", "total_distributable_cents must be > 0")
    lps = domain.funded_subscriptions(offeringId)
    if not lps:
        raise_error("ERR_NO_FUNDED_SUBSCRIPTIONS",
                    "at least one FUNDED subscription is required")
    dist["calculated_at"] = fmt_dt(CLOCK.now())
    snapshots = [{
        "subscription_id": s["id"],
        "unreturned_capital_cents": s["unreturned_capital_cents"],
        "accrued_pref_cents": domain.current_accrued_pref(s, off, CLOCK.now()),
        "funded_cents": s["funded_cents"],
    } for s in lps]
    lines = waterfall_allocate(dist["total_distributable_cents"], snapshots,
                               off["carried_interest_pct"])
    for line in lines:
        rec = {
            "distribution_id": dist["id"],
            "subscription_id": line["subscription_id"],
            "return_of_capital_cents": line["return_of_capital_cents"],
            "preferred_return_cents": line["preferred_return_cents"],
            "profit_split_lp_cents": line["profit_split_lp_cents"],
            "profit_split_gp_cents": line["profit_split_gp_cents"],
            "total_cents": line["total_cents"],
            "paid_at": None,
        }
        stamp_new_light(rec)
        db["distribution_lines"][rec["id"]] = rec
    dist["status"] = "CALCULATED"
    touch(dist)
    return success_object(ser_distribution(dist))


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/distributions/<distributionId>/approve",
          methods=["POST"], **RS)
@endpoint(SPONSOR)
def approve_distribution(caller, syndicationId, offeringId, distributionId):
    dist = resolve.distribution(syndicationId, offeringId, distributionId)
    body = get_body()
    # OCC-guarded approval (PRD 2.7): expected_distribution_version is required.
    req_version(body, "expected_distribution_version", dist["version"],
                "ERR_STALE_DISTRIBUTION_VERSION")
    if dist["status"] != "CALCULATED":
        raise_error("ERR_INVALID_STATE",
                    f"cannot approve a distribution in status {dist['status']}")
    dist["status"] = "APPROVED"
    touch(dist)
    return success_object(ser_distribution(dist))


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/distributions/<distributionId>/pay",
          methods=["POST"], **RS)
@endpoint(SPONSOR)
def pay_distribution(caller, syndicationId, offeringId, distributionId):
    off = resolve.offering(syndicationId, offeringId)
    dist = resolve.distribution(syndicationId, offeringId, distributionId)
    if dist["status"] != "APPROVED":
        raise_error("ERR_INVALID_STATE",
                    f"cannot pay a distribution in status {dist['status']}")
    now = fmt_dt(CLOCK.now())
    lines = [l for l in db["distribution_lines"].values()
             if l["distribution_id"] == dist["id"]]
    for line in lines:
        line["paid_at"] = now
        sub = db["subscriptions"].get(line["subscription_id"])
        if sub is not None:
            sub["_pref_ledger"] = sub.get("_pref_ledger", 0) + line["preferred_return_cents"]
            sub["unreturned_capital_cents"] -= line["return_of_capital_cents"]
            touch(sub)
    off["total_distributed_cents"] += dist["total_distributable_cents"]
    if dist["distribution_kind"] == "CAPITAL_EVENT" and dist["capital_event_id"]:
        ev = db["capital_events"].get(dist["capital_event_id"])
        if ev is not None and ev["status"] == "EXECUTED":
            ev["status"] = "DISTRIBUTED"
            touch(ev)
    dist["status"] = "PAID"
    touch(dist)
    return success_object(ser_distribution(dist))


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/distributions/<distributionId>/cancel",
          methods=["POST"], **RS)
@endpoint(SPONSOR)
def cancel_distribution(caller, syndicationId, offeringId, distributionId):
    dist = resolve.distribution(syndicationId, offeringId, distributionId)
    if dist["status"] not in ("DRAFT", "CALCULATED"):
        raise_error("ERR_INVALID_STATE",
                    f"cannot cancel a distribution in status {dist['status']}")
    for lid in [l["id"] for l in db["distribution_lines"].values()
                if l["distribution_id"] == dist["id"]]:
        del db["distribution_lines"][lid]
    dist["status"] = "CANCELLED"
    touch(dist)
    return success_object(ser_distribution(dist))


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/distributions/<distributionId>/lines",
          methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def list_lines(caller, syndicationId, offeringId, distributionId):
    resolve.distribution(syndicationId, offeringId, distributionId)
    limit, offset = pagination()
    items = [l for l in db["distribution_lines"].values()
             if l["distribution_id"] == distributionId]
    items = apply_filters(sorted_items(items), {"subscription_id": "subscription_id"})
    page = items[offset:offset + limit]
    return success_list([ser_distribution_line(o) for o in page], len(items), limit, offset)


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/distributions/<distributionId>/lines/<lineId>",
          methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def get_line(caller, syndicationId, offeringId, distributionId, lineId):
    return success_object(ser_distribution_line(
        resolve.distribution_line(syndicationId, offeringId, distributionId, lineId)))
