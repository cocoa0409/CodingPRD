"""Routes: appraisals and insurance policies (OCC on artwork.version)."""
from flask import Blueprint, request

from store import db, new_record, touch, serialize
from common import (auth, get_body, require_fields, check_enum, require_int,
                    get_or_404, fk_or_404, paginate)
from envelope import object_response, list_response
from errors import err
from timeutil import parse_dt
import calc
import domain

bp = Blueprint("valuation", __name__)

METHODS = {"FAIR_MARKET", "REPLACEMENT"}
COVERAGE_TYPES = {"STORAGE_ONLY", "TRANSIT", "ALL_RISK"}


def _check_occ(artwork, body):
    expected = body.get("expected_artwork_version")
    if expected != artwork["version"]:
        raise err("ERR_STALE_VERSION", "expected_artwork_version does not match")


# ---------------------------------------------------------------------------
# Appraisals
# ---------------------------------------------------------------------------
@bp.route("/appraisals", methods=["POST"])
def create_appraisal():
    auth(["Registrar"])
    body = get_body()
    artwork = fk_or_404("artworks", body.get("artwork_id"))
    require_fields(body, ["artwork_id", "method", "comparable_base_cents",
                          "appraiser_name", "expected_artwork_version"])
    check_enum(body["method"], METHODS, "method")
    require_int(body, "comparable_base_cents")
    require_int(body, "expected_artwork_version")
    _check_occ(artwork, body)

    mult = body.get("replacement_multiplier", 1.0)
    if mult is None:
        mult = 1.0
    reserve = body.get("restoration_reserve_cents", 0)
    if reserve is None:
        reserve = 0
    value = calc.appraisal_value(body["method"], body["comparable_base_cents"], mult, reserve)

    # supersede prior FINALIZED appraisal
    for a in domain.finalized_appraisals_for(artwork["id"]):
        a["status"] = "SUPERSEDED"
        touch(a)

    rec = new_record({
        "artwork_id": artwork["id"],
        "method": body["method"],
        "comparable_base_cents": body["comparable_base_cents"],
        "replacement_multiplier": mult,
        "restoration_reserve_cents": reserve,
        "appraiser_name": body["appraiser_name"],
        "appraised_value_cents": value,
        "status": "FINALIZED",
    })
    db["appraisals"][rec["id"]] = rec
    artwork["appraised_value_cents"] = value
    touch(artwork)
    return object_response(serialize(rec), 201)


@bp.route("/appraisals/<rid>", methods=["GET"])
def get_appraisal(rid):
    auth(["Registrar", "Approver"])
    rec = get_or_404("appraisals", rid)
    return object_response(serialize(rec))


@bp.route("/appraisals", methods=["GET"])
def list_appraisals():
    auth(["Registrar", "Approver"])
    aid = request.args.get("artwork_id")
    st = request.args.get("status")
    recs = [r for r in db["appraisals"].values()
            if (aid is None or r["artwork_id"] == aid) and (st is None or r["status"] == st)]
    items, limit, offset, total = paginate(recs)
    return list_response(items, limit, offset, total)


# ---------------------------------------------------------------------------
# Insurance policies
# ---------------------------------------------------------------------------
@bp.route("/policies", methods=["POST"])
def create_policy():
    auth(["Registrar"])
    body = get_body()
    artwork = fk_or_404("artworks", body.get("artwork_id"))
    require_fields(body, ["artwork_id", "coverage_type", "insured_value_cents",
                          "effective_start", "effective_end", "expected_artwork_version"])
    check_enum(body["coverage_type"], COVERAGE_TYPES, "coverage_type")
    require_int(body, "insured_value_cents")
    require_int(body, "expected_artwork_version")
    start = parse_dt(body["effective_start"])
    end = parse_dt(body["effective_end"])
    if not end > start:
        raise err("ERR_TIME_WINDOW_INVALID", "effective_end must be after effective_start")
    _check_occ(artwork, body)

    premium = calc.insurance_premium(body["insured_value_cents"], body["coverage_type"],
                                     artwork["fragility_class"], body["effective_start"],
                                     body["effective_end"])
    # supersede prior ACTIVE policy for the artwork
    prior = domain.active_policy_for(artwork["id"])
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)

    rec = new_record({
        "artwork_id": artwork["id"],
        "coverage_type": body["coverage_type"],
        "insured_value_cents": body["insured_value_cents"],
        "effective_start": body["effective_start"],
        "effective_end": body["effective_end"],
        "premium_cents": premium,
        "status": "ACTIVE",
    })
    db["policies"][rec["id"]] = rec
    artwork["active_policy_id"] = rec["id"]
    touch(artwork)
    return object_response(serialize(rec), 201)


@bp.route("/policies/<rid>/state", methods=["POST"])
def policy_state(rid):
    auth(["Approver"])
    rec = get_or_404("policies", rid)
    body = get_body()
    require_fields(body, ["to_status"])
    to_status = body["to_status"]
    if to_status not in {"ACTIVE", "CANCELLED", "SUPERSEDED", "LAPSED"}:
        raise err("ERR_VALIDATION", "invalid to_status")
    if to_status != "CANCELLED" or rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "cannot move policy from %s to %s"
                  % (rec["status"], to_status))
    rec["status"] = "CANCELLED"
    touch(rec)
    artwork = db["artworks"].get(rec["artwork_id"])
    if artwork is not None and artwork.get("active_policy_id") == rec["id"]:
        artwork["active_policy_id"] = None
        touch(artwork)
    return object_response(serialize(rec))


@bp.route("/policies/<rid>", methods=["GET"])
def get_policy(rid):
    auth(["Registrar", "Approver"])
    rec = get_or_404("policies", rid)
    return object_response(serialize(rec))


@bp.route("/policies", methods=["GET"])
def list_policies():
    auth(["Registrar", "Approver"])
    aid = request.args.get("artwork_id")
    st = request.args.get("status")
    recs = [r for r in db["policies"].values()
            if (aid is None or r["artwork_id"] == aid) and (st is None or r["status"] == st)]
    items, limit, offset, total = paginate(recs)
    return list_response(items, limit, offset, total)
