"""Routes: CollateralItem and CollateralReleaseRequest (PRD 3.7)."""
from flask import Blueprint, request

from auth import require_roles, ALL_ROLES, uid, check_issuer_owns
from envelope import ok, list_response, get_body, public
from errors import (raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE,
                    ERR_ALREADY_TERMINAL, ERR_SEGREGATION_OF_DUTIES,
                    ERR_DEFAULT_LOCK, ERR_COVERAGE_BELOW_MINIMUM,
                    ERR_VALUATION_STALE, ERR_SUBSTITUTE_REQUIRED,
                    ERR_STALE_VERSION, ERR_INVALID_REQUEST)
from store import DB, LOCK, new_entity, now, mutate, touch
from validate import (req_str, req_int, opt_int, req_enum, opt_enum,
                      req_date, opt_str, parse_date_strict, is_int)
from calc import collateral_coverage_bps, MIN_COVERAGE_BPS

bp = Blueprint("collateral", __name__)

COLLATERAL_TYPES = ["REAL_ESTATE", "EQUIPMENT", "SECURITIES", "GUARANTEE"]
ITEM_TERMINAL = ("RELEASED", "SUBSTITUTED")
REQUEST_TERMINAL = ("EFFECTED", "REJECTED", "SUPERSEDED")


def _check_fresh(valuation_iso, what):
    """Rule 18: valuation within 180 days of the logical clock date."""
    vd = parse_date_strict(valuation_iso)
    if vd is not None and (now().date() - vd).days > 180:
        raise_err(ERR_VALUATION_STALE, "%s valuation is stale" % what)


# ---------------------------------------------------------------------------
# CollateralItem
# ---------------------------------------------------------------------------

@bp.route("/collateral-items", methods=["POST"])
@require_roles("TrustOfficer")
def create_item():
    body = get_body()
    with LOCK:
        indenture_id = body.get("indenture_id")
        ind = DB["indentures"].get(indenture_id) if isinstance(indenture_id, str) else None
        if ind is None:
            raise_err(ERR_NOT_FOUND, "Indenture not found")
        req_str(body, "indenture_id")
        desc = req_str(body, "description")
        ctype = req_enum(body, "collateral_type", COLLATERAL_TYPES)
        value = req_int(body, "appraised_value_cents")
        vdate = req_date(body, "valuation_date")
        e = new_entity("collateral_items")
        e.update({
            "indenture_id": indenture_id,
            "description": desc,
            "collateral_type": ctype,
            "appraised_value_cents": value,
            "valuation_date": vdate,
            "substituted_from_item_id": None,
            "status": "PLEDGED",
        })
    return ok(public(e), 201)


@bp.route("/collateral-items", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_items():
    return list_response(DB["collateral_items"].values(), {
        "indenture_id": request.args.get("indenture_id"),
        "status": request.args.get("status"),
    })


@bp.route("/collateral-items/<cid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_item(cid):
    e = DB["collateral_items"].get(cid)
    if e is None:
        raise_err(ERR_NOT_FOUND, "CollateralItem not found")
    return ok(public(e))


# ---------------------------------------------------------------------------
# CollateralReleaseRequest
# ---------------------------------------------------------------------------

@bp.route("/collateral-release-requests", methods=["POST"])
@require_roles("Issuer")
def create_release_request():
    body = get_body()
    with LOCK:
        item_id = body.get("collateral_item_id")
        item = DB["collateral_items"].get(item_id) if isinstance(item_id, str) else None
        if item is None:
            raise_err(ERR_NOT_FOUND, "CollateralItem not found")
        # Rule 3: issuer owns the item's indenture.
        ind = DB["indentures"].get(item["indenture_id"])
        check_issuer_owns(ind)
        # OCC: expected_collateral_item_version must match the item version.
        expected = body.get("expected_collateral_item_version")
        if is_int(expected) and expected != item["version"]:
            raise_err(ERR_STALE_VERSION,
                      "expected_collateral_item_version is stale")
        rtype = body.get("request_type")
        # Rule 18: valuation freshness at creation (item and substitute).
        _check_fresh(item["valuation_date"], "Collateral")
        if rtype == "SUBSTITUTION":
            sub_vdate = body.get("substitute_valuation_date")
            if sub_vdate is not None:
                _check_fresh(sub_vdate, "Substitute collateral")
        # Rule 24: SUBSTITUTION requires all substitute_* fields.
        if rtype == "SUBSTITUTION":
            missing = [k for k in ("substitute_description",
                                   "substitute_collateral_type",
                                   "substitute_appraised_value_cents",
                                   "substitute_valuation_date")
                       if body.get(k) is None]
            if missing:
                raise_err(ERR_SUBSTITUTE_REQUIRED,
                          "SUBSTITUTION request is missing: %s" % ", ".join(missing))
        # Rule 26: shape.
        req_str(body, "collateral_item_id")
        rtype = req_enum(body, "request_type", ["RELEASE", "SUBSTITUTION"])
        if not is_int(body.get("expected_collateral_item_version")):
            raise_err(ERR_INVALID_REQUEST,
                      "expected_collateral_item_version is required")
        sub_desc = sub_type = sub_vdate = None
        sub_value = None
        if rtype == "SUBSTITUTION":
            sub_desc = req_str(body, "substitute_description")
            sub_type = req_enum(body, "substitute_collateral_type", COLLATERAL_TYPES)
            sub_value = req_int(body, "substitute_appraised_value_cents")
            sub_vdate = req_date(body, "substitute_valuation_date")
        # Supersede SUBMITTED siblings on the same item.
        for r in DB["collateral_release_requests"].values():
            if r["collateral_item_id"] == item["id"] and r["status"] == "SUBMITTED":
                mutate(r, status="SUPERSEDED")
        touch(item)  # creation advances the parent item version
        e = new_entity("collateral_release_requests")
        e.update({
            "collateral_item_id": item_id,
            "request_type": rtype,
            "substitute_description": sub_desc,
            "substitute_collateral_type": sub_type,
            "substitute_appraised_value_cents": sub_value,
            "substitute_valuation_date": sub_vdate,
            "post_release_coverage_bps": None,
            "status": "SUBMITTED",
            "verified_by_user_id": None,
            "decided_by_user_id": None,
        })
    return ok(public(e), 201)


@bp.route("/collateral-release-requests", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_release_requests():
    return list_response(DB["collateral_release_requests"].values(), {
        "collateral_item_id": request.args.get("collateral_item_id"),
        "status": request.args.get("status"),
    })


@bp.route("/collateral-release-requests/<rid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_release_request(rid):
    e = DB["collateral_release_requests"].get(rid)
    if e is None:
        raise_err(ERR_NOT_FOUND, "CollateralReleaseRequest not found")
    return ok(public(e))


@bp.route("/collateral-release-requests/<rid>/verify", methods=["POST"])
@require_roles("TrustOfficer")
def verify_release_request(rid):
    with LOCK:
        req = DB["collateral_release_requests"].get(rid)
        if req is None:
            raise_err(ERR_NOT_FOUND, "CollateralReleaseRequest not found")
        if req["status"] in REQUEST_TERMINAL:
            raise_err(ERR_ALREADY_TERMINAL,
                      "Request is terminal (%s)" % req["status"])
        if req["status"] != "SUBMITTED":
            raise_err(ERR_INVALID_STATE, "Only a SUBMITTED request can be verified")
        item = DB["collateral_items"].get(req["collateral_item_id"])
        ind = DB["indentures"].get(item["indenture_id"]) if item else None
        # Rule 18: re-check freshness at verification.
        if item is not None:
            _check_fresh(item["valuation_date"], "Collateral")
        if req["request_type"] == "SUBSTITUTION":
            _check_fresh(req.get("substitute_valuation_date"), "Substitute collateral")
        others = [it for it in DB["collateral_items"].values()
                  if it["indenture_id"] == item["indenture_id"]
                  and it["status"] == "PLEDGED"
                  and it["id"] != item["id"]]
        coverage = collateral_coverage_bps(ind, others, req)
        mutate(req, status="VERIFIED", post_release_coverage_bps=coverage,
               verified_by_user_id=uid())
    return ok(public(req))


@bp.route("/collateral-release-requests/<rid>/decide", methods=["POST"])
@require_roles("TrustManager")
def decide_release_request(rid):
    body = get_body()
    with LOCK:
        req = DB["collateral_release_requests"].get(rid)
        if req is None:
            raise_err(ERR_NOT_FOUND, "CollateralReleaseRequest not found")
        if req["status"] in REQUEST_TERMINAL:
            raise_err(ERR_ALREADY_TERMINAL,
                      "Request is terminal (%s)" % req["status"])
        if req["status"] != "VERIFIED":
            raise_err(ERR_INVALID_STATE, "Only a VERIFIED request can be decided")
        # Rule 6: segregation of duties (decider != verifier).
        if uid() == req["verified_by_user_id"]:
            raise_err(ERR_SEGREGATION_OF_DUTIES,
                      "Decider must differ from the verifying officer")
        # Rule 7: default lock.
        item = DB["collateral_items"].get(req["collateral_item_id"])
        indenture_id = item["indenture_id"] if item else None
        for c in DB["default_cases"].values():
            if (c["indenture_id"] == indenture_id
                    and c["status"] in ("CONFIRMED", "ACCELERATED")):
                raise_err(ERR_DEFAULT_LOCK,
                          "A default case of the indenture is active")
        decision = body.get("decision")
        # Rule 13: coverage floor on approval (equality approves).
        if decision == "APPROVE":
            if (req.get("post_release_coverage_bps") is None
                    or req["post_release_coverage_bps"] < MIN_COVERAGE_BPS):
                raise_err(ERR_COVERAGE_BELOW_MINIMUM,
                          "post_release_coverage_bps is below 12500")
        # Rule 26: shape.
        decision = req_enum(body, "decision", ["APPROVE", "REJECT"])
        mutate(req, status="APPROVED" if decision == "APPROVE" else "REJECTED",
               decided_by_user_id=uid())
    return ok(public(req))


@bp.route("/collateral-release-requests/<rid>/effect", methods=["POST"])
@require_roles("TrustOfficer")
def effect_release_request(rid):
    with LOCK:
        req = DB["collateral_release_requests"].get(rid)
        if req is None:
            raise_err(ERR_NOT_FOUND, "CollateralReleaseRequest not found")
        if req["status"] in REQUEST_TERMINAL:
            raise_err(ERR_ALREADY_TERMINAL,
                      "Request is terminal (%s)" % req["status"])
        if req["status"] != "APPROVED":
            raise_err(ERR_INVALID_STATE, "Only an APPROVED request can be effected")
        item = DB["collateral_items"].get(req["collateral_item_id"])
        if item is None:
            raise_err(ERR_NOT_FOUND, "CollateralItem not found")
        if item["status"] != "PLEDGED":
            raise_err(ERR_INVALID_STATE, "Collateral item is no longer PLEDGED")
        if req["request_type"] == "RELEASE":
            mutate(item, status="RELEASED")
        else:
            mutate(item, status="SUBSTITUTED")
            sub = new_entity("collateral_items")
            sub.update({
                "indenture_id": item["indenture_id"],
                "description": req["substitute_description"],
                "collateral_type": req["substitute_collateral_type"],
                "appraised_value_cents": req["substitute_appraised_value_cents"],
                "valuation_date": req["substitute_valuation_date"],
                "substituted_from_item_id": item["id"],
                "status": "PLEDGED",
            })
        mutate(req, status="EFFECTED")
    return ok(public(req))
