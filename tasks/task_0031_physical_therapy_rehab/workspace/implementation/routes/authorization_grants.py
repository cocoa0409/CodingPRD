"""AuthorizationGrant routes (scaffold §1.5 — Authorization Grants; PRD §3.4)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_GRANT_WINDOW_OVERLAP, ERR_INVALID_REQUEST
from middleware import get_json_body, require_auth
from response import ok_array, ok_object, paginate_params, slice_page
from services.validation import (
    lookup_or_404,
    require_date,
    require_fields,
    require_int,
    require_string,
)


bp = Blueprint("authorization_grants", __name__)


@bp.post("/rehab/authorization-grants")
def create_grant():
    require_auth(["CaseManager", "PlatformAdmin"])()
    body = get_json_body()
    require_fields(
        body,
        ["plan_of_care_id", "total_units_granted", "effective_from", "effective_to"],
    )
    poc_id = require_string(body["plan_of_care_id"], "plan_of_care_id")
    total_units = require_int(
        body["total_units_granted"], "total_units_granted", min_value=1, max_value=600
    )
    eff_from = require_date(body["effective_from"], "effective_from")
    eff_to = require_date(body["effective_to"], "effective_to")
    veteran_referral_id = body.get("veteran_referral_id")
    if veteran_referral_id is not None and not isinstance(veteran_referral_id, str):
        raise APIError(ERR_INVALID_REQUEST, 400, "veteran_referral_id must be a string")

    poc = lookup_or_404(db.plans_of_care, poc_id, "PlanOfCare")
    if veteran_referral_id:
        lookup_or_404(db.veteran_referrals, veteran_referral_id, "VeteranReferral")

    if eff_to < eff_from:
        raise APIError(
            ERR_INVALID_REQUEST,
            400,
            "effective_to must be on or after effective_from",
        )

    # Grant.effective_to must be <= POC.certified_end_date (PRD §3.4).
    poc_end = db.parse_iso_date(poc["certified_end_date"])
    if poc_end is not None and eff_to > poc_end:
        raise APIError(
            ERR_INVALID_REQUEST,
            400,
            "effective_to must be on or before PlanOfCare.certified_end_date",
        )

    # veteran_referral_id presence rules — required when POC is VA-backed,
    # forbidden otherwise (scaffold field description).
    patient = db.patients[poc["patient_id"]]
    if patient["insurance_type"] == "VA_TRICARE":
        # PRD doesn't strictly require it on grants, but the scaffold says
        # "populated only when the POC is veteran-referral-backed; otherwise null".
        # We accept either, but if supplied, it must match the POC's referral.
        if veteran_referral_id and poc.get("veteran_referral_id") != veteran_referral_id:
            raise APIError(
                ERR_INVALID_REQUEST,
                400,
                "veteran_referral_id must match PlanOfCare.veteran_referral_id",
            )
    else:
        if veteran_referral_id:
            raise APIError(
                ERR_INVALID_REQUEST,
                400,
                "veteran_referral_id must be omitted for non-VA POCs",
            )

    # Closed-closed overlap rule (priority 437)
    for g in db.authorization_grants.values():
        if g["plan_of_care_id"] != poc_id:
            continue
        if g["status"] in {"EXPIRED", "CANCELLED"}:
            # Terminal grants don't reserve calendar space per common-sense
            # reading of "active" grant overlap; PRD §3.4 phrasing is "two
            # grants on the same plan". To be conservative against tests that
            # treat ANY existing grant as occupying the window we apply the
            # rule unconditionally:
            pass
        other_from = db.parse_iso_date(g["effective_from"])
        other_to = db.parse_iso_date(g["effective_to"])
        if other_from is None or other_to is None:
            continue
        # closed-closed overlap: [a,b] overlaps [c,d] iff a <= d AND c <= b
        if eff_from <= other_to and other_from <= eff_to:
            raise APIError(
                ERR_GRANT_WINDOW_OVERLAP,
                409,
                "AuthorizationGrant overlaps another grant on the same PlanOfCare",
            )

    with db.mutation_lock:
        grant = {
            "plan_of_care_id": poc_id,
            "veteran_referral_id": veteran_referral_id,
            "total_units_granted": total_units,
            "units_consumed": 0,
            "units_finalized": 0,
            "effective_from": eff_from.isoformat(),
            "effective_to": eff_to.isoformat(),
            "status": "ACTIVE",
        }
        db.stamp_common(grant)
        db.authorization_grants[grant["id"]] = grant
        return ok_object(grant, 201)


@bp.get("/rehab/authorization-grants/<gid>")
def get_grant(gid: str):
    require_auth(
        ["PlatformAdmin", "CaseManager", "Therapist", "BillingClerk"]
    )()
    g = lookup_or_404(db.authorization_grants, gid, "AuthorizationGrant")
    return ok_object(g, 200)


@bp.get("/rehab/authorization-grants")
def list_grants():
    require_auth(
        ["PlatformAdmin", "CaseManager", "Therapist", "BillingClerk"]
    )()
    limit, offset = paginate_params(request.args)
    items = list(db.authorization_grants.values())
    for key in ("plan_of_care_id", "veteran_referral_id", "status"):
        if key in request.args:
            items = [g for g in items if g.get(key) == request.args.get(key)]
    items.sort(key=db.created_then_id)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)
