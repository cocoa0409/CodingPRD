"""Endorsement routes (PRD §3.5, §3.7 removal)."""
from decimal import Decimal

from flask import Blueprint, request

from db import db
from errors import err
from middleware import require_roles
from response import success
from services.calc import endorsement_premium_delta, to_money
from services.common import (
    get_json_body, require_field, as_enum, as_number,
    get_or_404, parse_pagination, paginate,
)
from services.ledger import post
from services.models import base_record, serialize, touch

bp = Blueprint("endorsements", __name__)

KINDS = {"PERIL_ADD", "EXCLUSION"}
PERIL_CODES = {"WATER_BACKUP", "SCREENED_ENCLOSURE", "ORDINANCE_LAW", "EARTH_MOVEMENT", "MOLD"}


@bp.post("/endorsements")
@require_roles("Agent")
def create_endorsement():
    body = get_json_body()
    application_id = require_field(body, "application_id")
    kind = as_enum(require_field(body, "kind"), "kind", KINDS)
    peril_code = as_enum(require_field(body, "peril_code"), "peril_code", PERIL_CODES)
    if "coverage_limit" in body and body["coverage_limit"] is not None:
        coverage_limit = as_number(body["coverage_limit"], "coverage_limit")
        if coverage_limit < 0:
            raise err("ERR_INVALID_REQUEST", "coverage_limit must be >= 0.")
    else:
        coverage_limit = Decimal("0")

    with db.lock:
        get_or_404("application", application_id)
        rec = base_record()
        rec.update({
            "application_id": application_id,
            "kind": kind,
            "peril_code": peril_code,
            "coverage_limit": coverage_limit,
            "premium_delta": Decimal("0"),
            "status": "DRAFT",
        })
        db.endorsements[rec["id"]] = rec
    return success(serialize(rec), status=201)


@bp.get("/endorsements")
@require_roles("Admin", "Agent", "Underwriter")
def list_endorsements():
    limit, offset = parse_pagination()
    application_id = request.args.get("application_id")
    with db.lock:
        items = list(db.endorsements.values())
        if application_id is not None:
            items = [e for e in items if e["application_id"] == application_id]
        window, meta = paginate(items, limit, offset)
        data = [serialize(e) for e in window]
    return success(data, status=200, list_meta=meta)


@bp.get("/endorsements/<rid>")
@require_roles("Admin", "Agent", "Underwriter")
def get_endorsement(rid):
    with db.lock:
        rec = get_or_404("endorsement", rid)
        return success(serialize(rec), status=200)


@bp.post("/endorsements/<rid>/attach")
@require_roles("Agent")
def attach_endorsement(rid):
    with db.lock:
        end = get_or_404("endorsement", rid)
        if end["status"] != "DRAFT":
            raise err("ERR_ENDORSEMENT_NOT_DRAFT", "attach requires Endorsement in DRAFT.")
        app = db.applications[end["application_id"]]
        if app["status"] not in ("DRAFT", "SUBMITTED", "UNDER_REVIEW"):
            raise err("ERR_APPLICATION_NOT_OPEN_FOR_ENDORSEMENT",
                      "attach requires parent Application in DRAFT/SUBMITTED/UNDER_REVIEW.")
        end["premium_delta"] = endorsement_premium_delta(
            end["kind"], end["peril_code"], end["coverage_limit"]
        )
        end["status"] = "PENDING"
        touch(end)
        return success(serialize(end), status=200)


@bp.post("/endorsements/<rid>/remove")
@require_roles("Underwriter")
def remove_endorsement(rid):
    with db.lock:
        end = get_or_404("endorsement", rid)
        if end["status"] != "APPLIED":
            raise err("ERR_ENDORSEMENT_NOT_APPLIED", "remove requires Endorsement in APPLIED.")
        # find the application's policy (cross-entity Endorsement<->Policy)
        app_id = end["application_id"]
        policy = _policy_for_application(app_id)
        if policy is None or policy["status"] not in ("PENDING_PAYMENT", "ACTIVE", "REINSTATED"):
            raise err("ERR_POLICY_NOT_AMENDABLE",
                      "remove requires the policy in PENDING_PAYMENT/ACTIVE/REINSTATED.")
        delta = to_money(end["premium_delta"])
        if end["kind"] == "PERIL_ADD":
            # forward was a DEBIT(premium_delta); reversal is a CREDIT(premium_delta)
            post(policy, "CREDIT", delta, "ENDORSEMENT_REMOVE_REVERSAL")
            # lower total_insured_value by coverage_limit
            prop = db.properties[policy["property_id"]]
            prop["total_insured_value"] = to_money(
                to_money(prop["total_insured_value"]) - to_money(end["coverage_limit"])
            )
            touch(prop)
        else:  # EXCLUSION: forward was CREDIT(|delta|); reversal is DEBIT(|delta|)
            post(policy, "DEBIT", abs(delta), "ENDORSEMENT_REMOVE_REVERSAL")
        end["status"] = "REMOVED"
        touch(end)
        return success(serialize(end), status=200)


def _policy_for_application(application_id):
    for pol in db.policies.values():
        if pol["application_id"] == application_id:
            return pol
    return None
