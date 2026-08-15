"""Biosimilar substitution policy endpoints (PRD 3.7)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_BIOSIMILAR_POLICY_NOT_DRAFT,
    ERR_REFERENCE_SELF_BIOSIMILAR, ERR_BIOSIMILAR_ALREADY_MAPPED,
    ERR_INVALID_WINDOW, ERR_POLICY_WINDOW_OVERLAP,
)
from middleware import authorized
from response import success_object
from routes.helpers import (
    apply_filters, get_body, get_or_404, list_response, public, read_all,
    req_date, req_num, req_str, stamp_new,
)
from services.pricing import reprice_for_biosimilar, touch
from util import new_id, pdate

bp = Blueprint("biosimilar_policies", __name__)


@bp.post("/api/biosimilar-policies")
def create_biosimilar_policy():
    authorized(["PlanAdmin"])
    body = get_body()
    # ---- shape (stage 4) ----
    reference_drug_id = req_str(body, "reference_drug_id")
    biosimilar_drug_id = req_str(body, "biosimilar_drug_id")
    provider_incentive_addon_pct = req_num(body, "provider_incentive_addon_pct", gt=0, le=0.10)
    member_copay_waiver_pct = req_num(body, "member_copay_waiver_pct", ge=0, le=1)
    effective_start = req_date(body, "effective_start")
    effective_end = req_date(body, "effective_end")
    # ---- existence (stage 5): body FKs in declared order ----
    if reference_drug_id not in db["drugs"]:
        raise_error(ERR_NOT_FOUND, f"reference drug {reference_drug_id} does not exist")
    if biosimilar_drug_id not in db["drugs"]:
        raise_error(ERR_NOT_FOUND, f"biosimilar drug {biosimilar_drug_id} does not exist")
    # ---- referential coherence (stage 10) ----
    if biosimilar_drug_id == reference_drug_id:
        raise_error(ERR_REFERENCE_SELF_BIOSIMILAR, "biosimilar_drug_id equals reference_drug_id")
    # ---- temporal (stage 11): half-open window must be non-empty ----
    if effective_start >= effective_end:
        raise_error(ERR_INVALID_WINDOW, "effective_start must be before effective_end")
    rec = {
        "id": new_id(),
        "reference_drug_id": reference_drug_id,
        "biosimilar_drug_id": biosimilar_drug_id,
        "provider_incentive_addon_pct": provider_incentive_addon_pct,
        "member_copay_waiver_pct": member_copay_waiver_pct,
        "effective_start": effective_start.isoformat(),
        "effective_end": effective_end.isoformat(),
        "status": "DRAFT",
    }
    stamp_new(rec)
    db["biosimilar_policies"][rec["id"]] = rec
    return success_object(public(rec), 201)


@bp.get("/api/biosimilar-policies")
def list_biosimilar_policies():
    read_all()
    items = list(db["biosimilar_policies"].values())
    items = apply_filters(items, ["reference_drug_id", "biosimilar_drug_id", "status"])
    return list_response(items)


@bp.get("/api/biosimilar-policies/<policyId>")
def get_biosimilar_policy(policyId):
    read_all()
    return success_object(public(get_or_404("biosimilar_policies", policyId)))


@bp.post("/api/biosimilar-policies/<policyId>/activate")
def activate_biosimilar_policy(policyId):
    authorized(["PlanAdmin"])
    get_body()
    policy = get_or_404("biosimilar_policies", policyId)
    # ---- target state (stage 7) ----
    if policy["status"] != "DRAFT":
        raise_error(ERR_BIOSIMILAR_POLICY_NOT_DRAFT, "activate requires a DRAFT biosimilar policy")
    start = pdate(policy["effective_start"])
    end = pdate(policy["effective_end"])
    # ---- temporal hygiene: half-open window overlap (stage 11) ----
    for other in db["biosimilar_policies"].values():
        if (
            other["id"] != policy["id"]
            and other["status"] == "ACTIVE"
            and other["reference_drug_id"] == policy["reference_drug_id"]
            and start < pdate(other["effective_end"])
            and pdate(other["effective_start"]) < end
        ):
            # touching boundaries (end == start) do NOT overlap
            raise_error(ERR_POLICY_WINDOW_OVERLAP, "overlapping ACTIVE policy window for the reference drug")
    # ---- uniqueness of the biosimilar mapping among ACTIVE policies ----
    for other in db["biosimilar_policies"].values():
        if (
            other["id"] != policy["id"]
            and other["status"] == "ACTIVE"
            and other["biosimilar_drug_id"] == policy["biosimilar_drug_id"]
        ):
            raise_error(ERR_BIOSIMILAR_ALREADY_MAPPED, "biosimilar drug already mapped by an ACTIVE policy")
    policy["status"] = "ACTIVE"
    touch(policy)
    # cascade: in-flight repricing of unpaid biosimilar claims inside the window
    reprice_for_biosimilar(policy)
    return success_object(public(policy))
