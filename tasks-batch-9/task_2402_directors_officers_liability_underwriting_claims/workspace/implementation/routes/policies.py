"""Policies, the tower, premium, cancellation and the run-off tail (PRD 3.5, 3.6)."""

from flask import Blueprint, request

import clock
import db
from auth import (
    COMPLIANCE_OFFICER,
    RISK_MANAGER,
    UNDERWRITER,
    authenticate,
    require_owner,
)
from db import store
from errors import ApiError
from money import ZERO, dec, q2
from response import list_response, object_response
from routes.common import get_layer, get_policy, insured_of_policy
from services import derive, pricing
from validation import Field, paginate, parse_body, parse_pagination, validate

bp = Blueprint("policies", __name__)

FORM_TYPES = ("FOLLOWING_FORM", "DIFFERENCE_IN_CONDITIONS")
CANCEL_REASONS = ("INSURED_REQUEST", "NON_PAYMENT", "MATERIAL_MISREPRESENTATION")
PERMITTED_TAIL_YEARS = (1, 2, 3, 6)

LAYER_FIELDS = [
    Field("carrier_name", "string"),
    Field("attachment_point_usd", "money", check=lambda v: v >= 0),
    Field("limit_usd", "money", check=lambda v: v > 0),
    Field("participation_pct", "number", check=lambda v: 0 < v <= 1),
    Field("form_type", "enum", enum=FORM_TYPES),
    Field("underlying_layer_id", "string", required=False, default=None),
    Field("dic_deviation_notes", "string", required=False, default=None),
]

PAYMENT_FIELDS = [Field("amount_usd", "money")]

CANCEL_FIELDS = [
    Field("effective_date", "datetime"),
    Field("cancelled_reason", "enum", enum=CANCEL_REASONS),
]

RUNOFF_FIELDS = [Field("tail_years", "integer")]


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------


@bp.get("/dno/policies/<policy_id>")
def read_policy(policy_id):
    authenticate()
    return object_response(get_policy(policy_id))


@bp.get("/dno/policies")
def list_policies():
    authenticate()
    limit, offset = parse_pagination()
    records = db.ordered(list(store.policies.values()))
    for key in ("submission_id", "insured_id", "quote_id", "coverage_status"):
        value = request.args.get(key)
        if value is not None:
            records = [r for r in records if r[key] == value]
    return list_response(paginate(records, limit, offset), limit, offset, len(records))


@bp.get("/dno/policies/<policy_id>/coverage-parts")
def list_coverage_parts(policy_id):
    authenticate()
    policy = get_policy(policy_id)
    limit, offset = parse_pagination()
    records = derive.parts_of(policy["id"])
    return list_response(paginate(records, limit, offset), limit, offset, len(records))


@bp.get("/dno/layers/<layer_id>")
def read_layer(layer_id):
    authenticate()
    return object_response(get_layer(layer_id))


@bp.get("/dno/layers")
def list_layers():
    authenticate()
    limit, offset = parse_pagination()
    records = db.ordered(list(store.layers.values()))
    for key in ("policy_id", "underlying_layer_id", "status"):
        value = request.args.get(key)
        if value is not None:
            records = [r for r in records if r[key] == value]
    return list_response(paginate(records, limit, offset), limit, offset, len(records))


@bp.get("/dno/policies/<policy_id>/runoff-endorsements")
def list_endorsements(policy_id):
    authenticate()
    policy = get_policy(policy_id)
    limit, offset = parse_pagination()
    records = derive.endorsements_of(policy["id"])
    return list_response(paginate(records, limit, offset), limit, offset, len(records))


# --------------------------------------------------------------------------
# Tower subscription and sealing
# --------------------------------------------------------------------------


@bp.post("/dno/policies/<policy_id>/layers")
def subscribe_layer(policy_id):
    authenticate(UNDERWRITER)
    policy = get_policy(policy_id)
    values, _ = validate(parse_body(), LAYER_FIELDS)

    underlying_id = values["underlying_layer_id"]
    if underlying_id is not None:
        underlying = store.layers.get(underlying_id)
        if underlying is None or underlying["policy_id"] != policy["id"]:
            raise ApiError("ERR_LAYER_NOT_FOUND")

    if values["form_type"] == "DIFFERENCE_IN_CONDITIONS" and not values["dic_deviation_notes"]:
        raise ApiError("ERR_CONDITIONAL_FIELD_REQUIRED")

    if policy["coverage_status"] not in ("INCEPTED", "ACTIVE"):
        raise ApiError("ERR_INVALID_POLICY_STATE")
    if policy["tower_sealed"]:
        raise ApiError("ERR_TOWER_ALREADY_SEALED")

    attachment = values["attachment_point_usd"]
    layer_limit = values["limit_usd"]
    participation = values["participation_pct"]
    counted = derive.counted_layers(policy["id"])

    new_start = attachment
    new_end = attachment + layer_limit
    for band_start, band in derive.band_map(counted).items():
        band_end = band_start + band["limit"]
        if band_start == new_start and band["limit"] == layer_limit:
            continue
        if new_start < band_end and band_start < new_end:
            raise ApiError("ERR_LAYER_OVERLAP")

    band_participation = participation
    for layer in counted:
        if (
            layer["status"] == "ATTACHED"
            and dec(layer["attachment_point_usd"]) == new_start
            and dec(layer["limit_usd"]) == layer_limit
        ):
            band_participation += dec(layer["participation_pct"])
    if q2(band_participation) > dec("1.00"):
        raise ApiError("ERR_PARTICIPATION_OVERSUBSCRIBED")

    dic_share = ZERO
    for layer in counted:
        if layer["form_type"] == "DIFFERENCE_IN_CONDITIONS":
            dic_share += dec(layer["limit_usd"]) * dec(layer["participation_pct"])
    if values["form_type"] == "DIFFERENCE_IN_CONDITIONS":
        dic_share += layer_limit * participation
    if q2(dic_share) > derive.DIC_SHARE_CAP * dec(policy["program_target_limit_usd"]):
        raise ApiError("ERR_DIC_SHARE_EXCEEDED")

    if attachment == 0:
        already_primary = any(dec(l["attachment_point_usd"]) == 0 for l in counted)
        if already_primary or layer_limit != dec(policy["shared_aggregate_limit_usd"]):
            raise ApiError("ERR_PRIMARY_LAYER_IMMUTABLE")

    prospective = q2(derive.placed_limit(counted) + layer_limit * participation)
    if prospective > dec(policy["program_target_limit_usd"]):
        raise ApiError("ERR_TOWER_LIMIT_EXCEEDED")

    layer = db.insert(
        "layers",
        {
            "policy_id": policy["id"],
            "underlying_layer_id": underlying_id,
            "carrier_name": values["carrier_name"],
            "attachment_point_usd": attachment,
            "limit_usd": layer_limit,
            "participation_pct": participation,
            "form_type": values["form_type"],
            "dic_deviation_notes": values["dic_deviation_notes"],
            "status": "ATTACHED",
            "is_primary": attachment == 0,
        },
    )
    touched = derive.Touched()
    derive.derive_tower(policy)
    touched.add(policy)
    touched.flush()
    return object_response(layer, 201)


@bp.post("/dno/policies/<policy_id>/seal-tower")
def seal_tower(policy_id):
    authenticate(UNDERWRITER)
    policy = get_policy(policy_id)
    parse_body()
    if policy["coverage_status"] not in ("INCEPTED", "ACTIVE"):
        raise ApiError("ERR_INVALID_POLICY_STATE")
    if policy["tower_sealed"]:
        raise ApiError("ERR_TOWER_ALREADY_SEALED")

    counted = derive.counted_layers(policy["id"])
    bands = derive.band_map(counted)
    if not derive.bands_have_no_gap(bands):
        raise ApiError("ERR_TOWER_GAP")
    if not derive.bands_fully_subscribed(bands) or derive.placed_limit(counted) != dec(
        policy["program_target_limit_usd"]
    ):
        raise ApiError("ERR_PARTICIPATION_INCOMPLETE")

    policy["tower_sealed"] = True
    touched = derive.Touched()
    derive.derive_tower(policy)
    touched.add(policy)
    touched.flush()
    return object_response(policy)


# --------------------------------------------------------------------------
# Premium, cancellation and run-off
# --------------------------------------------------------------------------


@bp.post("/dno/policies/<policy_id>/premium-payments")
def record_payment(policy_id):
    user_id, role = authenticate(RISK_MANAGER)
    policy = get_policy(policy_id)
    require_owner(role, user_id, policy["insured_id"])
    values, _ = validate(parse_body(), PAYMENT_FIELDS)
    if policy["coverage_status"] == "CANCELLED":
        raise ApiError("ERR_INVALID_POLICY_STATE")
    if policy["premium_status"] not in ("INVOICED", "DELINQUENT"):
        raise ApiError("ERR_INVALID_POLICY_STATE")
    if values["amount_usd"] != dec(policy["gross_premium_usd"]):
        raise ApiError("ERR_PREMIUM_AMOUNT_MISMATCH")
    policy["premium_status"] = "PAID"
    db.touch(policy)
    return object_response(policy)


@bp.post("/dno/policies/<policy_id>/cancel")
def cancel_policy(policy_id):
    authenticate(COMPLIANCE_OFFICER)
    policy = get_policy(policy_id)
    values, _ = validate(parse_body(), CANCEL_FIELDS)
    if policy["coverage_status"] not in ("INCEPTED", "ACTIVE"):
        raise ApiError("ERR_INVALID_POLICY_STATE")
    derive.recompute_open_claim_count(policy)
    if policy["open_claim_count"] > 0:
        raise ApiError("ERR_OPEN_CLAIMS_BLOCK_CANCEL")

    policy["coverage_status"] = "CANCELLED"
    policy["cancelled_reason"] = values["cancelled_reason"]
    policy["return_premium_usd"] = pricing.unexpired_credit(
        policy["gross_premium_usd"], values["effective_date"], policy["period_end"]
    )
    touched = derive.Touched()
    derive.release_policy(policy, touched)
    touched.flush()
    return object_response(policy)


@bp.post("/dno/policies/<policy_id>/runoff-endorsements")
def endorse_runoff(policy_id):
    authenticate(COMPLIANCE_OFFICER)
    policy = get_policy(policy_id)
    values, _ = validate(parse_body(), RUNOFF_FIELDS)
    if policy["coverage_status"] not in ("INCEPTED", "ACTIVE", "RUNOFF"):
        raise ApiError("ERR_INVALID_POLICY_STATE")
    if derive.endorsements_of(policy["id"]):
        raise ApiError("ERR_RUNOFF_ALREADY_ENDORSED")

    insured = insured_of_policy(policy)
    if (
        insured is None
        or insured["control_status"] not in ("CHANGE_OF_CONTROL_ANNOUNCED", "ACQUIRED")
        or insured["change_of_control_date"] is None
    ):
        raise ApiError("ERR_NO_CHANGE_OF_CONTROL")

    tail_years = values["tail_years"]
    if tail_years not in PERMITTED_TAIL_YEARS:
        raise ApiError("ERR_INVALID_TAIL_YEARS")

    runoff_start = insured["change_of_control_date"]
    runoff_end = clock.plus_days(runoff_start, tail_years * 365)
    has_live_claim = any(
        c["status"] != "DENIED" for c in derive.claims_of(policy["id"])
    )
    priced = pricing.runoff_premium(
        policy["gross_premium_usd"],
        tail_years,
        has_live_claim,
        runoff_start,
        policy["period_end"],
    )
    endorsement = db.insert(
        "runoff_endorsements",
        {
            "policy_id": policy["id"],
            "change_of_control_date": runoff_start,
            "tail_years": tail_years,
            "runoff_start_date": runoff_start,
            "runoff_end_date": runoff_end,
            "tail_factor_applied": priced["tail_factor_applied"],
            "severity_load_applied": priced["severity_load_applied"],
            "unexpired_premium_credit_usd": priced["unexpired_premium_credit_usd"],
            "runoff_premium_usd": priced["runoff_premium_usd"],
            "status": "ENDORSED",
        },
    )

    touched = derive.Touched()
    policy["coverage_status"] = "RUNOFF"
    policy["runoff_start_date"] = runoff_start
    policy["runoff_end_date"] = runoff_end
    policy["runoff_premium_usd"] = priced["runoff_premium_usd"]
    derive.derive_tower(policy)
    touched.add(policy)
    for report in derive.reports_of(policy["id"]):
        if report["status"] == "REPORTED":
            report["reporting_deadline"] = reporting_deadline(policy)
            touched.add(report)
    touched.flush()
    return object_response(endorsement, 201)


def reporting_deadline(policy):
    """window_end + erp_days, keeping the window end's time of day; exclusive."""
    if policy["coverage_status"] == "RUNOFF" and policy["runoff_end_date"] is not None:
        window_end = policy["runoff_end_date"]
    else:
        window_end = policy["period_end"]
    return clock.plus_days(window_end, policy["erp_days"])
