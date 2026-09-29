"""Product-to-competitor match endpoints (PRD 3.2)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import (ALL_ROLES, PRICING_ANALYST, PRICING_MANAGER, body,
                        endpoint)
from response import object_response
from routes.common import (FK_COMPETITOR, FK_PRODUCT, filtered, list_page,
                           path_lookup, resolve_fks)
from services import calc, cascades, serialize
from util import as_enum, as_int, as_str, get_required

bp = Blueprint("matches", __name__)

MATCH_METHODS = ("IDENTIFIER", "ATTRIBUTE", "IMAGE")
REVIEW_DECISIONS = ("OPEN_REVIEW", "CONFIRM", "REJECT")
NON_REJECTED = ("PROPOSED", "UNDER_REVIEW", "CONFIRMED")


def _score(payload, name):
    return as_int(get_required(payload, name), name, minimum=0, maximum=100)


@bp.post("/matches")
@endpoint([PRICING_ANALYST])
def create_match(user_id, role):
    payload = body()
    fks = resolve_fks(payload, [FK_PRODUCT, FK_COMPETITOR])

    product = fks["product_id"]
    if product is None:
        get_required(payload, "product_id")
    competitor = fks["competitor_id"]
    if competitor is None:
        get_required(payload, "competitor_id")
    method_raw = as_str(get_required(payload, "match_method"), "match_method",
                        min_len=1)
    identifier_score = _score(payload, "identifier_score")
    attribute_score = _score(payload, "attribute_score")
    image_score = _score(payload, "image_score")
    competitor_identifier = None
    if payload.get("competitor_identifier") is not None:
        competitor_identifier = as_str(payload["competitor_identifier"],
                                       "competitor_identifier", min_len=1)

    match_method = as_enum(method_raw, "match_method", MATCH_METHODS)

    if product["market_id"] != competitor["market_id"]:
        raise err("ERR_MARKET_MISMATCH",
                  "The product and the competitor belong to different markets.")

    for existing in db.links.values():
        if (existing["product_id"] == product["id"]
                and existing["competitor_id"] == competitor["id"]
                and existing["status"] in NON_REJECTED):
            raise err("ERR_DUPLICATE_RESOURCE",
                      "A non-rejected match already exists for this pair.")

    confidence_bp, variant, grade = calc.match_confidence(
        match_method, identifier_score, attribute_score, image_score)

    record = db.new_record()
    record.update({
        "product_id": product["id"],
        "competitor_id": competitor["id"],
        "match_method": match_method,
        "competitor_identifier": competitor_identifier,
        "identifier_score": identifier_score,
        "attribute_score": attribute_score,
        "image_score": image_score,
        "confidence_bp": confidence_bp,
        "confidence_variant": variant,
        "match_grade": grade,
        "review_round": 0,
        "status": "PROPOSED",
        "latest_effective_price_cents": None,
        "selected_observation_id": None,
        "data_status": "INSUFFICIENT",
        "gap_bp": None,
        "gap_stale": False,
    })
    db.links[record["id"]] = record
    return object_response(serialize.link(record), 201)


@bp.post("/matches/<match_id>/review")
@endpoint([PRICING_MANAGER])
def review_match(user_id, role, match_id):
    link = path_lookup("links", match_id, "ERR_MATCH_NOT_FOUND")
    payload = body()
    decision_raw = as_str(get_required(payload, "decision"), "decision", min_len=1)
    if payload.get("note") is not None:
        as_str(payload["note"], "note", min_len=1)
    decision = as_enum(decision_raw, "decision", REVIEW_DECISIONS)

    current = link["status"]
    if decision == "OPEN_REVIEW":
        if current != "PROPOSED":
            raise err("ERR_INVALID_STATE",
                      "Only a PROPOSED match may be opened for review.")
        if link["review_round"] >= calc.MAX_MATCH_REVIEW_ROUNDS:
            raise err("ERR_MAX_REVIEW_ROUNDS",
                      "The match has exhausted its review rounds.")
        link["status"] = "UNDER_REVIEW"
        db.touch(link)
    elif decision == "CONFIRM":
        if current not in ("PROPOSED", "UNDER_REVIEW"):
            raise err("ERR_INVALID_STATE",
                      "Only a PROPOSED or UNDER_REVIEW match may be confirmed.")
        product = db.products.get(link["product_id"])
        competitor = db.competitors.get(link["competitor_id"])
        if product is None or product["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE",
                      "The product must be ACTIVE to confirm a match.")
        if competitor is None or competitor["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE",
                      "The competitor must be ACTIVE to confirm a match.")
        threshold = (calc.GRADE_EXACT_MIN_BP if current == "PROPOSED"
                     else calc.GRADE_CLOSE_MIN_BP)
        if link["confidence_bp"] < threshold:
            raise err("ERR_CONFIDENCE_BELOW_CONFIRM_THRESHOLD",
                      "confidence_bp %d is below the %d confirmation bar."
                      % (link["confidence_bp"], threshold))
        link["status"] = "CONFIRMED"
        calc.elect_effective_price(link)
        db.touch(link)
    else:
        if current not in ("PROPOSED", "UNDER_REVIEW"):
            raise err("ERR_INVALID_STATE",
                      "Only a PROPOSED or UNDER_REVIEW match may be rejected.")
        link["status"] = "REJECTED"
        db.touch(link)
        cascades.void_active_observations(link, "LINK_REJECTED")
        # PRD 3.3: the election is re-run every time the observation pool
        # changes, including on a void.
        calc.elect_effective_price(link)

    return object_response(serialize.link(link))


@bp.post("/matches/<match_id>/revise")
@endpoint([PRICING_ANALYST])
def revise_match(user_id, role, match_id):
    link = path_lookup("links", match_id, "ERR_MATCH_NOT_FOUND")
    payload = body()

    updates = {}
    for name in ("identifier_score", "attribute_score", "image_score"):
        if payload.get(name) is not None:
            updates[name] = as_int(payload[name], name, minimum=0, maximum=100)
    method_raw = None
    if payload.get("match_method") is not None:
        method_raw = as_str(payload["match_method"], "match_method", min_len=1)
    if "competitor_identifier" in payload and payload["competitor_identifier"] is not None:
        updates["competitor_identifier"] = as_str(payload["competitor_identifier"],
                                                  "competitor_identifier", min_len=1)
    if method_raw is not None:
        updates["match_method"] = as_enum(method_raw, "match_method", MATCH_METHODS)

    if link["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE",
                  "Only an UNDER_REVIEW match may be revised.")
    if link["review_round"] >= calc.MAX_MATCH_REVIEW_ROUNDS:
        raise err("ERR_MAX_REVIEW_ROUNDS",
                  "The match has exhausted its review rounds.")

    link.update(updates)
    link["status"] = "PROPOSED"
    link["review_round"] = link["review_round"] + 1
    confidence_bp, variant, grade = calc.match_confidence(
        link["match_method"], link["identifier_score"], link["attribute_score"],
        link["image_score"])
    link["confidence_bp"] = confidence_bp
    link["confidence_variant"] = variant
    link["match_grade"] = grade
    db.touch(link)
    return object_response(serialize.link(link))


@bp.get("/matches/<match_id>")
@endpoint(ALL_ROLES)
def read_match(user_id, role, match_id):
    link = path_lookup("links", match_id, "ERR_MATCH_NOT_FOUND")
    return object_response(serialize.link(link))


@bp.get("/matches")
@endpoint(ALL_ROLES)
def list_matches(user_id, role):
    rows = filtered(db.ordered(db.links), request.args,
                    [("product_id", "product_id"),
                     ("competitor_id", "competitor_id"),
                     ("status", "status"), ("match_grade", "match_grade")])
    raw_min = request.args.get("min_confidence_bp")
    if raw_min is not None:
        try:
            minimum = int(raw_min, 10)
        except ValueError:
            minimum = None
        if minimum is not None:
            rows = [r for r in rows if r["confidence_bp"] >= minimum]
    return list_page(rows, serialize.link)
