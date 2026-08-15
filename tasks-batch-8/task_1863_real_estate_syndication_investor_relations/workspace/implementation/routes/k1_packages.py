"""K-1 packages: provisional vs final (largest-remainder) allocation (PRD 3.7)."""
from datetime import date

from flask import Blueprint

import resolve
from db import db
from errors import raise_error
from middleware import SPONSOR, COMPLIANCE, AGENT, endpoint
from response import success_list, success_object
from serializers import ser_k1_package
from services import domain
from services.calculations import k1_allocation
from services.domain import stamp_new, touch, sorted_items
from util import parse_dt
from validate import get_body, req_int, req_str, pagination, apply_filters

bp = Blueprint("k1_packages", __name__)
RS = {"strict_slashes": False}


def _year_end(tax_year):
    return date(tax_year, 12, 31)


def _k1_base_subscriptions(offering_id, tax_year):
    """FUNDED subscriptions whose funding landed on or before the tax year's last day."""
    end = _year_end(tax_year)
    out = []
    for s in domain.offering_subscriptions(offering_id):
        if s["status"] != "FUNDED" or not s.get("funded_at"):
            continue
        if parse_dt(s["funded_at"]).date() <= end:
            out.append(s)
    return sorted(out, key=lambda s: (s["funded_at"], s["created_at"], s["_seq"]))


def _offering_noi_for_year(offering_id, tax_year):
    return sum(
        r["noi_cents"] for r in db["quarterly_reports"].values()
        if r["offering_id"] == offering_id
        and r["report_year"] == tax_year
        and r["status"] in ("PUBLISHED", "AMENDED")
    )


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/k1-packages",
          methods=["POST"], **RS)
@endpoint(SPONSOR)
def create_k1(caller, syndicationId, offeringId):
    resolve.offering(syndicationId, offeringId)
    body = get_body()
    k = {
        "offering_id": offeringId,
        "tax_year": req_int(body, "tax_year"),
        "preparer_firm": req_str(body, "preparer_firm"),
        "draft_k1_cents_by_subscription": None,
        "final_k1_cents_by_subscription": None,
        "status": "PREPARATION",
    }
    stamp_new(k)
    db["k1_packages"][k["id"]] = k
    return success_object(ser_k1_package(k), 201)


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/k1-packages",
          methods=["GET"], **RS)
@endpoint(SPONSOR, COMPLIANCE, AGENT)
def list_k1(caller, syndicationId, offeringId):
    resolve.offering(syndicationId, offeringId)
    limit, offset = pagination()
    items = [k for k in db["k1_packages"].values() if k["offering_id"] == offeringId]
    items = apply_filters(sorted_items(items),
                          {"status": "status", "tax_year": "tax_year"})
    page = items[offset:offset + limit]
    return success_list([ser_k1_package(o) for o in page], len(items), limit, offset)


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/k1-packages/<k1PackageId>",
          methods=["GET"], **RS)
@endpoint(SPONSOR, COMPLIANCE, AGENT)
def get_k1(caller, syndicationId, offeringId, k1PackageId):
    return success_object(ser_k1_package(
        resolve.k1_package(syndicationId, offeringId, k1PackageId)))


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/k1-packages/<k1PackageId>/submit-for-review",
          methods=["POST"], **RS)
@endpoint(SPONSOR)
def submit_k1_for_review(caller, syndicationId, offeringId, k1PackageId):
    k = resolve.k1_package(syndicationId, offeringId, k1PackageId)
    if k["status"] != "PREPARATION":
        raise_error("ERR_INVALID_STATE",
                    f"cannot submit-for-review a K-1 package in status {k['status']}")
    lps = _k1_base_subscriptions(offeringId, k["tax_year"])
    if not lps:
        raise_error("ERR_NO_K1_BASE",
                    "no FUNDED subscription on this offering as of the tax year's last day")
    noi = _offering_noi_for_year(offeringId, k["tax_year"])
    # Provisional variant: per-line rounding, NO reconciliation pass.
    k["draft_k1_cents_by_subscription"] = k1_allocation(noi, [
        {"subscription_id": s["id"], "funded_cents": s["funded_cents"], "seq": s["_seq"]}
        for s in lps
    ], reconcile=False)
    k["status"] = "PARTNER_REVIEW"
    touch(k)
    return success_object(ser_k1_package(k))


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/k1-packages/<k1PackageId>/finalize",
          methods=["POST"], **RS)
@endpoint(SPONSOR)
def finalize_k1(caller, syndicationId, offeringId, k1PackageId):
    k = resolve.k1_package(syndicationId, offeringId, k1PackageId)
    if k["status"] != "PARTNER_REVIEW":
        raise_error("ERR_INVALID_STATE",
                    f"cannot finalize a K-1 package in status {k['status']}")
    noi = _offering_noi_for_year(offeringId, k["tax_year"])
    lps = _k1_base_subscriptions(offeringId, k["tax_year"])
    # Final variant: same inputs, then largest-remainder reconciliation to the NOI.
    k["final_k1_cents_by_subscription"] = k1_allocation(noi, [
        {"subscription_id": s["id"], "funded_cents": s["funded_cents"], "seq": s["_seq"]}
        for s in lps
    ], reconcile=True)
    # draft map stays frozen for the delta audit.
    k["status"] = "FINALIZED"
    touch(k)
    return success_object(ser_k1_package(k))


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/k1-packages/<k1PackageId>/deliver",
          methods=["POST"], **RS)
@endpoint(SPONSOR)
def deliver_k1(caller, syndicationId, offeringId, k1PackageId):
    k = resolve.k1_package(syndicationId, offeringId, k1PackageId)
    if k["status"] != "FINALIZED":
        raise_error("ERR_INVALID_STATE",
                    f"cannot deliver a K-1 package in status {k['status']}")
    # Passive delivery: portal-visible K-1 records; no session timestamps touched.
    k["status"] = "DELIVERED"
    touch(k)
    return success_object(ser_k1_package(k))
