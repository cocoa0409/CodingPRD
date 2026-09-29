"""Going-out-of-business licences and the markdown cadence."""

from flask import Blueprint

import auth
import calc
import clock
import db
import helpers
import response
import serializers
import shape
from errors import ApiError
from money import ZERO, dec, round4

bp = Blueprint("license", __name__)


# ----------------------------------------------------------------- licences

@bp.post("/stores/<store_id>/gob-licenses")
def create_license(store_id):
    user_id, _role = auth.begin(("ComplianceOfficer",))
    body = shape.json_body()
    license_number = shape.field_str(body, "license_number")
    period_start = shape.field_date(body, "period_start_date")
    period_end = shape.field_date(body, "period_end_date")
    claim_codes = shape.field_code_list(body, "advertising_claim_codes", calc.CLAIM_CODES)
    if period_end < period_start:
        raise ApiError("ERR_INVALID_DATE_RANGE")

    store = helpers.require("stores", store_id)
    helpers.store_open_for_children(store)
    jurisdiction = helpers.jurisdiction_of_store(store)

    prohibited = list(jurisdiction["prohibited_claim_codes"]) if jurisdiction else []
    for code in claim_codes:
        if code in prohibited:
            raise ApiError("ERR_PROHIBITED_ADVERTISING_CLAIM")

    if jurisdiction is not None and jurisdiction["advertising_disclosure_required"]:
        declares_comparison = any(
            code in calc.PRICE_COMPARISON_CLAIMS for code in claim_codes
        )
        if declares_comparison and calc.DISCLOSURE_CLAIM not in claim_codes:
            raise ApiError("ERR_ADVERTISING_DISCLOSURE_REQUIRED")

    prior = calc.most_recent_non_denied_license(store["id"])
    if prior is not None and jurisdiction is not None:
        gap = (period_start - calc.as_date(prior["period_end_date"])).days
        if gap < jurisdiction["license_cooling_off_days"]:
            raise ApiError("ERR_LICENSE_COOLING_OFF")

    requested_days = (period_end - period_start).days + 1
    if jurisdiction is not None and requested_days > jurisdiction["max_sale_days"]:
        raise ApiError("ERR_LICENSE_PERIOD_TOO_LONG")

    if not claim_codes or len(set(claim_codes)) != len(claim_codes):
        raise ApiError("ERR_DUPLICATE_CLAIM_CODE")

    row = db.insert(
        "licenses",
        {
            "store_id": store["id"],
            "license_number": license_number,
            "period_start_date": period_start.isoformat(),
            "period_end_date": period_end.isoformat(),
            "requested_days": requested_days,
            "advertising_claim_codes": claim_codes,
            "license_status": "APPLIED",
            "applied_by_user_id": user_id,
            "decided_by_user_id": None,
            "decision_reason": None,
            "revoked_reason": None,
        },
    )
    return response.ok(serializers.license(row), 201)


@bp.get("/stores/<store_id>/gob-licenses")
def list_licenses(store_id):
    auth.begin(("ComplianceOfficer", "LiquidationConsultant", "RetailerController"))
    limit, offset = shape.pagination()
    license_status = shape.query_enum("license_status", calc.LICENSE_STATUSES)
    store = helpers.require("stores", store_id)
    rows = db.licenses_of_store(store["id"])
    if license_status is not None:
        rows = [r for r in rows if r["license_status"] == license_status]
    return helpers.paginate(rows, serializers.license, limit, offset)


@bp.get("/gob-licenses/<row_id>")
def read_license(row_id):
    auth.begin(("ComplianceOfficer", "LiquidationConsultant", "RetailerController"))
    row = helpers.require("licenses", row_id)
    return response.ok(serializers.license(row))


@bp.post("/gob-licenses/<row_id>/decision")
def decide_license(row_id):
    user_id, _role = auth.begin(("ComplianceOfficer",))
    lic = db.get("licenses", row_id)
    auth.deny_self_decision(user_id, lic, "applied_by_user_id")
    body = shape.json_body()
    decision = shape.field_enum(body, "decision", ("APPROVE", "DENY"))
    decision_reason = shape.field_str(body, "decision_reason", required=False, default=None)
    if lic is None:
        raise ApiError("ERR_LICENSE_NOT_FOUND")
    if lic["license_status"] != "APPLIED":
        raise ApiError("ERR_LICENSE_STATE_INVALID")

    lic["decided_by_user_id"] = user_id
    lic["decision_reason"] = decision_reason
    store = db.get("stores", lic["store_id"])
    if decision == "DENY":
        lic["license_status"] = "DENIED"
        db.touch(lic)
        return response.ok(serializers.license(lic))

    lic["license_status"] = "APPROVED"
    db.touch(lic)
    if store is not None and store["store_status"] == "LICENSE_PENDING":
        store["store_status"] = "SELLING"
        store["selling_start_date"] = lic["period_start_date"]
        db.touch(store)
    return response.ok(serializers.license(lic))


@bp.post("/gob-licenses/<row_id>/revoke")
def revoke_license(row_id):
    auth.begin(("ComplianceOfficer",))
    body = shape.json_body()
    revoked_reason = shape.field_str(body, "revoked_reason")
    lic = helpers.require("licenses", row_id)
    if lic["license_status"] != "APPROVED":
        raise ApiError("ERR_LICENSE_STATE_INVALID")

    store = db.get("stores", lic["store_id"])
    engagement = helpers.engagement_of_store(store) if store is not None else None

    # hop 1
    lic["license_status"] = "REVOKED"
    lic["revoked_reason"] = revoked_reason
    db.touch(lic)

    was_selling = store is not None and store["store_status"] == "SELLING"
    if was_selling:
        # hop 2
        store["store_status"] = "SUSPENDED"
        store["suspension_reason"] = "LICENSE_REVOKED"
        # hop 3
        for stage in db.stages_of_store(store["id"]):
            if stage["stage_status"] == "ACTIVE":
                stage["stage_status"] = "CLOSED"
                stage["closed_reason"] = "LICENSE_LOST"
                stage["escalation_applied_pct"] = round4(ZERO)
                db.touch(stage)
        # hop 4
        calc.recompute_store(store)
        db.touch(store)

    if engagement is not None:
        if was_selling:
            engagement["compliance_strike_count"] += 1
        # hop 5 plus the posture fan-out
        calc.recompute_engagement(engagement)
        db.touch(engagement)
    return response.ok(serializers.license(lic))


# ----------------------------------------------------------- markdown stages

@bp.post("/stores/<store_id>/markdown-stages")
def create_stage(store_id):
    auth.begin(("LiquidationConsultant",))
    body = shape.json_body()
    stage_index = shape.field_int(body, "stage_index", minimum=1)
    discount_pct = shape.field_pct(body, "discount_pct")
    target_pct = shape.field_pct(body, "sell_through_target_pct")
    if dec(target_pct) <= 0:
        shape.bad("Field 'sell_through_target_pct' must be greater than 0")
    window_start = shape.field_date(body, "window_start_date")
    window_end = shape.field_date(body, "window_end_date")
    expected_store_version = shape.field_int(body, "expected_store_version", minimum=0)
    supersede = shape.field_bool(
        body, "supersede_overlapping", required=False, default=False
    )
    if window_end <= window_start:
        raise ApiError("ERR_INVALID_DATE_RANGE")

    store = helpers.require("stores", store_id)
    if expected_store_version != store["version"]:
        raise ApiError("ERR_STALE_STORE_VERSION")
    helpers.store_open_for_children(store)

    engagement = helpers.engagement_of_store(store)
    if engagement is not None:
        helpers.deny_frozen(engagement)
        helpers.deny_restricted(engagement)

    overlapping = calc.stages_overlapping(store["id"], window_start, window_end)
    to_void = []
    if overlapping:
        if not supersede:
            raise ApiError("ERR_STAGE_WINDOW_OVERLAP")
        to_void = [s for s in overlapping if s["stage_status"] == "ARMED"]
        if len(to_void) != len(overlapping):
            raise ApiError("ERR_STAGE_WINDOW_OVERLAP")

    # PRD 2.11 puts the sequence check at priority 25, after the overlap check at
    # 18 but still before any write, so the predecessor is read from the stages
    # "not been voided" as the request found them -- the supersede void is a side
    # effect of the successful create and has not happened yet.
    surviving = [
        s
        for s in db.stages_of_store(store["id"])
        if s["stage_status"] != "VOIDED"
    ]
    predecessor = None
    highest = 0
    for candidate in surviving:
        if candidate["stage_index"] >= highest:
            highest = candidate["stage_index"]
            predecessor = candidate
    if stage_index != highest + 1:
        raise ApiError("ERR_STAGE_SEQUENCE_INVALID")
    if dec(discount_pct) > calc.MAX_DISCOUNT_PCT:
        raise ApiError("ERR_STAGE_SEQUENCE_INVALID")
    if predecessor is not None and dec(discount_pct) <= dec(predecessor["discount_pct"]):
        raise ApiError("ERR_STAGE_SEQUENCE_INVALID")

    for stage in to_void:
        stage["stage_status"] = "VOIDED"
        stage["closed_reason"] = "SUPERSEDED"
        db.touch(stage)

    row = db.insert(
        "stages",
        {
            "store_id": store["id"],
            "stage_index": stage_index,
            "discount_pct": discount_pct,
            "sell_through_target_pct": target_pct,
            "window_start_date": window_start.isoformat(),
            "window_end_date": window_end.isoformat(),
            "stage_status": "ARMED",
            "closed_reason": None,
            "checkpoint_sell_through_pct": None,
            "escalation_applied_pct": round4(ZERO),
            "activated_at": None,
        },
    )
    calc.recompute_store(store)
    db.touch(store)
    if engagement is not None:
        calc.recompute_engagement(engagement)
    return response.ok(serializers.stage(row), 201)


@bp.get("/stores/<store_id>/markdown-stages")
def list_stages(store_id):
    user_id, role = auth.begin(
        ("LiquidationConsultant", "RetailerController", "StoreManager")
    )
    auth.scope_store(user_id, role, store_id)
    limit, offset = shape.pagination()
    stage_status = shape.query_enum("stage_status", calc.STAGE_STATUSES)
    store = helpers.require("stores", store_id)
    rows = db.stages_of_store(store["id"])
    if stage_status is not None:
        rows = [r for r in rows if r["stage_status"] == stage_status]
    return helpers.paginate(rows, serializers.stage, limit, offset)


@bp.get("/markdown-stages/<row_id>")
def read_stage(row_id):
    user_id, role = auth.begin(
        ("LiquidationConsultant", "RetailerController", "StoreManager")
    )
    row = db.get("stages", row_id)
    auth.scope_child(user_id, role, row)
    if row is None:
        raise ApiError("ERR_MARKDOWN_STAGE_NOT_FOUND")
    return response.ok(serializers.stage(row))


@bp.post("/markdown-stages/<row_id>/activate")
def activate_stage(row_id):
    auth.begin(("LiquidationConsultant",))
    stage = helpers.require("stages", row_id)
    if stage["stage_status"] != "ARMED":
        raise ApiError("ERR_STAGE_STATE_INVALID")
    store = db.get("stores", stage["store_id"])
    if store is None or store["store_status"] != "SELLING":
        raise ApiError("ERR_STORE_NOT_SELLING")
    engagement = helpers.engagement_of_store(store)
    if engagement is not None:
        helpers.deny_frozen(engagement)
    jurisdiction = helpers.jurisdiction_of_store(store)
    if jurisdiction is not None and jurisdiction["gob_license_required"]:
        covering = calc.license_covers_window(
            store,
            calc.as_date(stage["window_start_date"]),
            calc.as_date(stage["window_end_date"]),
        )
        if covering is None:
            raise ApiError("ERR_LICENSE_NOT_ACTIVE")
    for other in db.stages_of_store(store["id"]):
        if other["id"] != stage["id"] and other["stage_status"] == "ACTIVE":
            raise ApiError("ERR_STAGE_ALREADY_ACTIVE")

    stage["stage_status"] = "ACTIVE"
    stage["activated_at"] = clock.iso_now()
    db.touch(stage)
    return response.ok(serializers.stage(stage))


@bp.post("/markdown-stages/<row_id>/checkpoint")
def checkpoint_stage(row_id):
    auth.begin(("LiquidationConsultant",))
    stage = helpers.require("stages", row_id)
    if stage["stage_status"] != "ACTIVE":
        raise ApiError("ERR_STAGE_STATE_INVALID")
    store = db.get("stores", stage["store_id"])
    if store is None or store["store_status"] != "SELLING":
        raise ApiError("ERR_STORE_NOT_SELLING")

    calc.recompute_store(store)
    observed = round4(store["realized_sell_through_pct"])
    stage["checkpoint_sell_through_pct"] = observed
    shortfall = round4(dec(stage["sell_through_target_pct"]) - dec(observed))
    stage["stage_status"] = "CLOSED"
    if shortfall <= 0:
        stage["escalation_applied_pct"] = round4(ZERO)
        stage["closed_reason"] = "ON_SCHEDULE"
    else:
        raise_pct = calc.escalation_for_shortfall(shortfall)
        stage["escalation_applied_pct"] = raise_pct
        stage["closed_reason"] = "ESCALATED"
        for successor in db.stages_of_store(store["id"]):
            if (
                successor["stage_status"] == "ARMED"
                and successor["stage_index"] == stage["stage_index"] + 1
            ):
                raised = round4(dec(successor["discount_pct"]) + dec(raise_pct))
                if raised > calc.MAX_DISCOUNT_PCT:
                    raised = round4(calc.MAX_DISCOUNT_PCT)
                successor["discount_pct"] = raised
                db.touch(successor)
                break
    db.touch(stage)

    calc.recompute_store(store)
    db.touch(store)
    engagement = helpers.engagement_of_store(store)
    if engagement is not None:
        calc.recompute_engagement(engagement)
    return response.ok(serializers.stage(stage))
