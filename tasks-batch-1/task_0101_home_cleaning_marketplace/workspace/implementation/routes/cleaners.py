"""Cleaner registration, listing, and onboarding state machine routes."""
from flask import Blueprint, request

import db
import serializers as S
from auth import authenticate, authorize
from errors import err
from helpers import (get_json_body, require_resource, require_fields,
                     parse_pagination, paginate)
from response import success, list_success
from clock import clock

bp = Blueprint("cleaners", __name__)


@bp.route("/cleaning/cleaners", methods=["POST"])
def create_cleaner():
    principal = authenticate()
    authorize(principal, {"Anonymous"})
    body = get_json_body()
    require_fields(body, ["email", "full_name", "service_postal_codes"])
    email = body["email"]
    if not isinstance(email, str) or email.strip() == "":
        raise err("ERR_INVALID_REQUEST", "email must be a non-empty string")
    if not isinstance(body["full_name"], str) or body["full_name"].strip() == "":
        raise err("ERR_INVALID_REQUEST", "full_name must be a non-empty string")
    codes = body["service_postal_codes"]
    if not isinstance(codes, list) or not all(isinstance(c, str) for c in codes):
        raise err("ERR_INVALID_REQUEST", "service_postal_codes must be a list of strings")
    rec = {
        "email": email.strip().lower(),
        "full_name": body["full_name"],
        "service_postal_codes": codes,
        "status": "APPLIED",
        "rating_sum": 0,
        "rating_count": 0,
        "completed_job_count": 0,
    }
    db.insert(db.cleaners, rec)
    return success(S.cleaner(rec), status=201)


@bp.route("/cleaning/cleaners/<cid>", methods=["GET"])
def get_cleaner(cid):
    principal = authenticate()
    authorize(principal, {"Cleaner", "PlatformAdmin", "Customer"})
    rec = require_resource(db.cleaners, cid, "cleaner")
    return success(S.cleaner(rec), status=200)


@bp.route("/cleaning/cleaners", methods=["GET"])
def list_cleaners():
    principal = authenticate()
    authorize(principal, {"PlatformAdmin", "Customer"})
    limit, offset = parse_pagination()
    status = request.args.get("status")
    postal_code = request.args.get("postal_code")
    records = list(db.cleaners.values())
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if postal_code is not None:
        records = [r for r in records if postal_code in (r.get("service_postal_codes") or [])]
    page, total = paginate(records, limit, offset)
    return list_success([S.cleaner(r) for r in page], limit, offset, total)


@bp.route("/cleaning/cleaners/<cid>/background-checks", methods=["POST"])
def open_background_check(cid):
    principal = authenticate()
    authorize(principal, {"PlatformAdmin"})
    cleaner = require_resource(db.cleaners, cid, "cleaner")
    if cleaner["status"] != "APPLIED":
        raise err("ERR_INVALID_STATE", "cleaner is not APPLIED")
    body = get_json_body()
    require_fields(body, ["provider_ref"])
    if not isinstance(body["provider_ref"], str) or body["provider_ref"] == "":
        raise err("ERR_INVALID_REQUEST", "provider_ref must be a non-empty string")
    check = {
        "cleaner_id": cleaner["id"],
        "provider_ref": body["provider_ref"],
        "result": "PENDING",
        "adjudicated_at": None,
    }
    db.insert(db.background_checks, check)
    cleaner["status"] = "CHECK_PENDING"
    db.touch(cleaner)
    return success(S.background_check(check), status=201)


@bp.route("/cleaning/cleaners/<cid>/background-checks", methods=["GET"])
def list_cleaner_checks(cid):
    principal = authenticate()
    authorize(principal, {"PlatformAdmin"})
    require_resource(db.cleaners, cid, "cleaner")
    limit, offset = parse_pagination()
    records = [r for r in db.background_checks.values() if r["cleaner_id"] == cid]
    page, total = paginate(records, limit, offset)
    return list_success([S.background_check(r) for r in page], limit, offset, total)


@bp.route("/cleaning/background-checks/<bid>", methods=["GET"])
def get_background_check(bid):
    principal = authenticate()
    authorize(principal, {"PlatformAdmin"})
    rec = require_resource(db.background_checks, bid, "background_check")
    return success(S.background_check(rec), status=200)


@bp.route("/cleaning/background-checks/<bid>/adjudicate", methods=["POST"])
def adjudicate(bid):
    principal = authenticate()
    authorize(principal, {"PlatformAdmin"})
    check = require_resource(db.background_checks, bid, "background_check")
    cleaner = db.cleaners.get(check["cleaner_id"])
    # State gate: cleaner must be CHECK_PENDING and the check still PENDING.
    if cleaner is None or cleaner["status"] != "CHECK_PENDING" or check["result"] != "PENDING":
        raise err("ERR_INVALID_STATE", "cleaner not in CHECK_PENDING or check already adjudicated")
    body = get_json_body()
    require_fields(body, ["result"])
    result = body["result"]
    if result not in ("CLEAR", "ADVERSE"):
        raise err("ERR_INVALID_REQUEST", "result must be CLEAR or ADVERSE")
    check["result"] = result
    check["adjudicated_at"] = clock.now()
    db.touch(check)
    cleaner["status"] = "CHECK_PASSED" if result == "CLEAR" else "CHECK_FAILED"
    db.touch(cleaner)
    return success(S.background_check(check), status=200)


@bp.route("/cleaning/cleaners/<cid>/activate", methods=["POST"])
def activate_cleaner(cid):
    principal = authenticate()
    authorize(principal, {"PlatformAdmin"})
    cleaner = require_resource(db.cleaners, cid, "cleaner")
    if cleaner["status"] not in ("CHECK_PASSED", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", "cleaner cannot be activated from current state")
    cleaner["status"] = "ACTIVE"
    db.touch(cleaner)
    return success(S.cleaner(cleaner), status=200)


@bp.route("/cleaning/cleaners/<cid>/suspend", methods=["POST"])
def suspend_cleaner(cid):
    principal = authenticate()
    authorize(principal, {"PlatformAdmin"})
    cleaner = require_resource(db.cleaners, cid, "cleaner")
    if cleaner["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "only ACTIVE cleaners can be suspended")
    cleaner["status"] = "SUSPENDED"
    db.touch(cleaner)
    return success(S.cleaner(cleaner), status=200)
