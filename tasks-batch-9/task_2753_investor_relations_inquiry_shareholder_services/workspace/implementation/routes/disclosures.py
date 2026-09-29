"""The disclosure record: draft, publish, supersede, withdraw (PRD §3.4)."""
from flask import Blueprint

import calc
import validation as V
from envelope import created, ok, ok_list, paginate
from errors import ApiError
from serializers import disclosure_out
from store import (DISCLOSURE_STATUSES, DISCLOSURE_TYPES, METRICS_WITH_NONE,
                   new_row, sorted_rows, store, touch)

bp = Blueprint("disclosures", __name__)


@bp.post("/disclosures")
def create_disclosure():
    V.authorize("DisclosureOfficer")
    b = V.body()
    company_id = V.f_str(b, "company_id", required=True)
    disclosure_type = V.f_enum(b, "disclosure_type", DISCLOSURE_TYPES, required=True)
    fact_key = V.f_str(b, "fact_key", required=True, max_len=80)
    metric = V.f_enum(b, "metric", METRICS_WITH_NONE, default="NONE")
    period_label = V.f_str(b, "period_label", default=None)
    is_guidance_row = disclosure_type == "GUIDANCE_UPDATE"
    guidance_low = V.f_num(b, "guidance_low", required=is_guidance_row, minimum=0)
    guidance_high = V.f_num(b, "guidance_high", required=is_guidance_row, minimum=0)
    V.f_bool(b, "is_guidance", default=None)  # accepted but derived, never trusted
    if guidance_low is not None and guidance_high is not None and guidance_low > guidance_high:
        V.bad("guidance_low must be <= guidance_high")

    company = V.get_company(company_id)

    for existing in store.disclosures.values():
        if (existing["company_id"] == company["id"] and existing["fact_key"] == fact_key
                and existing["status"] in ("DRAFT", "PUBLISHED")):
            raise ApiError("ERR_DUPLICATE_FACT_KEY",
                           "fact_key %s is already live for this issuer" % fact_key)

    disclosure = new_row({
        "company_id": company["id"],
        "disclosure_type": disclosure_type,
        "fact_key": fact_key,
        "metric": metric,
        "period_label": period_label,
        "guidance_low": guidance_low,
        "guidance_high": guidance_high,
        "status": "DRAFT",
        "published_at": None,
        "is_guidance": disclosure_type == "GUIDANCE_UPDATE" and metric != "NONE",
        "withdrawal_reason": None,
    })
    store.disclosures[disclosure["id"]] = disclosure
    return created(disclosure_out(disclosure))


@bp.get("/disclosures")
def list_disclosures():
    V.authorize("IRAdmin", "IRAnalyst", "DisclosureOfficer")
    limit, offset = V.q_pagination()
    company_id = V.q_str("company_id")
    status = V.q_enum("status", DISCLOSURE_STATUSES)
    disclosure_type = V.q_enum("disclosure_type", DISCLOSURE_TYPES)
    metric = V.q_enum("metric", METRICS_WITH_NONE)
    period_label = V.q_str("period_label")
    is_guidance = V.q_bool("is_guidance")
    rows = sorted_rows(store.disclosures)
    if company_id is not None:
        rows = [r for r in rows if r["company_id"] == company_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if disclosure_type is not None:
        rows = [r for r in rows if r["disclosure_type"] == disclosure_type]
    if metric is not None:
        rows = [r for r in rows if r["metric"] == metric]
    if period_label is not None:
        rows = [r for r in rows if r["period_label"] == period_label]
    if is_guidance is not None:
        rows = [r for r in rows if r["is_guidance"] == is_guidance]
    page, total = paginate(rows, limit, offset)
    return ok_list([disclosure_out(r) for r in page], limit, offset, total)


@bp.get("/disclosures/<disclosure_id>")
def read_disclosure(disclosure_id):
    V.authorize("IRAdmin", "IRAnalyst", "DisclosureOfficer", "Investor")
    return ok(disclosure_out(V.get_disclosure(disclosure_id)))


@bp.post("/disclosures/<disclosure_id>/publish")
def publish_disclosure(disclosure_id):
    V.authorize("DisclosureOfficer")
    disclosure = V.get_disclosure(disclosure_id)
    if disclosure["status"] != "DRAFT":
        raise ApiError("ERR_DISCLOSURE_INVALID_STATE", "only a DRAFT disclosure may be published")
    if disclosure["disclosure_type"] == "GUIDANCE_UPDATE":
        if (disclosure["metric"] == "NONE" or disclosure["period_label"] is None
                or disclosure["guidance_low"] is None or disclosure["guidance_high"] is None
                or disclosure["guidance_low"] > disclosure["guidance_high"]):
            V.bad("a GUIDANCE_UPDATE disclosure needs a metric, period_label and a valid band")

    disclosure["status"] = "PUBLISHED"
    disclosure["published_at"] = store.now()
    touch(disclosure)

    if disclosure["is_guidance"]:
        for other in sorted_rows(store.disclosures):
            if other["id"] == disclosure["id"]:
                continue
            if (other["company_id"] == disclosure["company_id"]
                    and other["status"] == "PUBLISHED" and other["is_guidance"]
                    and other["metric"] == disclosure["metric"]
                    and other["period_label"] == disclosure["period_label"]):
                other["status"] = "SUPERSEDED"
                touch(other)
    return ok(disclosure_out(disclosure))


@bp.post("/disclosures/<disclosure_id>/withdraw")
def withdraw_disclosure(disclosure_id):
    V.authorize("DisclosureOfficer")
    b = V.body()
    reason = V.f_str(b, "reason", required=True)

    disclosure = V.get_disclosure(disclosure_id)
    if disclosure["status"] not in ("DRAFT", "PUBLISHED"):
        raise ApiError("ERR_DISCLOSURE_INVALID_STATE",
                       "only a DRAFT or PUBLISHED disclosure may be withdrawn")

    was_published = disclosure["status"] == "PUBLISHED"
    disclosure["status"] = "WITHDRAWN"
    disclosure["withdrawal_reason"] = reason
    touch(disclosure)
    if was_published:
        calc.withdrawal_cascade(disclosure)
    return ok(disclosure_out(disclosure))
