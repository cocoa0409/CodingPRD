"""CustomerBrief endpoints (PRD §3.1, §3.9)."""

from flask import Blueprint, request

import constants as K
import serializers as S
from db import base_entity, db, now_logical, touch
from errors import fail
from middleware import ALL_ROLES, auth
from response import created, ok
from routes.common import list_response, need
from services import cascade, ledger
from validate import (as_code_subset, as_datetime, as_enum, as_int, as_decimal,
                      as_pattern, as_str, body_json, optional, present, require)

bp = Blueprint("briefs", __name__)


def _brief(brief_id):
    return need(db.briefs, brief_id, "ERR_BRIEF_NOT_FOUND", "customer brief")


@bp.post("/customer-briefs")
def create_brief():
    auth(["AccountManager"])
    body = body_json()
    brief_code = as_pattern(require(body, "brief_code"), "brief_code",
                            r"^BRF-[0-9]{4}$")
    customer_name = as_str(require(body, "customer_name"), "customer_name", 1, 120)
    matrix_type = as_enum(require(body, "matrix_type"), "matrix_type",
                          K.MATRIX_TYPES)
    target_profile = as_enum(require(body, "target_profile"), "target_profile",
                             K.TARGET_PROFILES)
    dosage_pct = as_decimal(require(body, "dosage_pct"), "dosage_pct", 4,
                            gt=0, le=100)
    annual_volume_kg = as_int(require(body, "annual_volume_kg"),
                              "annual_volume_kg", minimum=1)
    cap = as_int(require(body, "cost_in_use_cap_cents_per_tonne"),
                 "cost_in_use_cap_cents_per_tonne", minimum=0)
    tier = as_enum(require(body, "confidentiality_tier"), "confidentiality_tier",
                   K.TIERS)
    natural = optional(body, "natural_claim_required", False)
    kosher = optional(body, "kosher_required", False)
    halal = optional(body, "halal_required", False)
    if not isinstance(natural, bool) or not isinstance(kosher, bool) \
            or not isinstance(halal, bool):
        fail("ERR_INVALID_REQUEST", "claim requirement flags must be booleans")
    exclusions = optional(body, "allergen_exclusions", [])
    exclusions = as_code_subset(exclusions, "allergen_exclusions",
                               K.ALLERGEN_CODES)

    for existing in db.briefs.values():
        if existing["brief_code"] == brief_code:
            fail("ERR_DUPLICATE_CODE", "brief_code %s already exists" % brief_code)

    brief = base_entity()
    brief.update({
        "brief_code": brief_code,
        "customer_name": customer_name,
        "matrix_type": matrix_type,
        "target_profile": target_profile,
        "dosage_pct": dosage_pct,
        "annual_volume_kg": annual_volume_kg,
        "cost_in_use_cap_cents_per_tonne": cap,
        "natural_claim_required": natural,
        "kosher_required": kosher,
        "halal_required": halal,
        "allergen_exclusions": exclusions,
        "confidentiality_tier": tier,
        "status": "DRAFT",
        "clarification_round_count": 0,
        "clarification_note": None,
        "decision_note": None,
        "outcome": None,
        "loss_reason": None,
        "closed_at": None,
    })
    db.briefs[brief["id"]] = brief
    return created(S.brief_out(brief))


@bp.get("/customer-briefs")
def list_briefs():
    auth(ALL_ROLES)
    status = request.args.get("status")
    customer_name = request.args.get("customer_name")
    outcome = request.args.get("outcome")
    rows = []
    for brief in db.briefs.values():
        if status is not None and brief["status"] != status:
            continue
        if customer_name is not None and brief["customer_name"] != customer_name:
            continue
        if outcome is not None and brief["outcome"] != outcome:
            continue
        rows.append(brief)
    return list_response(rows, S.brief_out)


@bp.get("/customer-briefs/<brief_id>")
def get_brief(brief_id):
    auth(ALL_ROLES)
    return ok(S.brief_out(_brief(brief_id)))


@bp.post("/customer-briefs/<brief_id>/submit")
def submit_brief(brief_id):
    auth(["AccountManager"])
    body_json()
    brief = _brief(brief_id)
    if brief["status"] not in ("DRAFT", "CLARIFICATION_REQUESTED"):
        fail("ERR_BRIEF_STATE_INVALID",
             "cannot submit a brief in status %s" % brief["status"])
    brief["status"] = "SUBMITTED"
    touch(brief)
    return ok(S.brief_out(brief))


@bp.post("/customer-briefs/<brief_id>/clarification-request")
def clarification_request(brief_id):
    auth(["TechnicalDirector"])
    body = body_json()
    note = as_str(require(body, "clarification_note"), "clarification_note")
    brief = _brief(brief_id)
    if brief["status"] != "SUBMITTED":
        fail("ERR_BRIEF_STATE_INVALID",
             "cannot request clarification on a brief in status %s"
             % brief["status"])
    brief["clarification_note"] = note
    if brief["clarification_round_count"] <= 2:
        brief["clarification_round_count"] += 1
        brief["status"] = "CLARIFICATION_REQUESTED"
        touch(brief)
    else:
        brief["status"] = "REJECTED"
        brief["decision_note"] = "CLARIFICATION_EXHAUSTED"
        touch(brief)
        cascade.reject_brief_cascade(brief)
    return ok(S.brief_out(brief))


@bp.post("/customer-briefs/<brief_id>/decision")
def decide_brief(brief_id):
    auth(["TechnicalDirector"])
    body = body_json()
    decision = as_enum(require(body, "decision"), "decision",
                       ("ACCEPTED", "REJECTED"))
    note = optional(body, "decision_note")
    if note is not None:
        note = as_str(note, "decision_note")
    brief = _brief(brief_id)
    if brief["status"] != "SUBMITTED":
        fail("ERR_BRIEF_STATE_INVALID",
             "cannot decide a brief in status %s" % brief["status"])
    brief["status"] = "ACCEPTED" if decision == "ACCEPTED" else "REJECTED"
    if note is not None:
        brief["decision_note"] = note
    touch(brief)
    if decision == "REJECTED":
        cascade.reject_brief_cascade(brief)
    return ok(S.brief_out(brief))


@bp.post("/customer-briefs/<brief_id>/close")
def close_brief(brief_id):
    auth(["AccountManager"])
    body = body_json()
    outcome = as_enum(require(body, "outcome"), "outcome", K.OUTCOMES)
    loss_reason = optional(body, "loss_reason")
    if loss_reason is not None:
        loss_reason = as_enum(loss_reason, "loss_reason", K.LOSS_REASONS)
    if outcome == "LOST" and loss_reason is None:
        fail("ERR_INVALID_REQUEST", "loss_reason is required when closing as LOST")

    brief = _brief(brief_id)
    if brief["status"] != "ACCEPTED":
        fail("ERR_BRIEF_STATE_INVALID",
             "cannot close a brief in status %s" % brief["status"])

    if outcome == "WON":
        has_approved = any(f["status"] == "APPROVED"
                           for f in ledger.formulas_of_brief(brief["id"]))
        if not has_approved:
            fail("ERR_FORMULA_NOT_APPROVED",
                 "closing WON requires an APPROVED formula on the brief")
        brief["status"] = "CLOSED_WON"
        brief["outcome"] = "WON"
        brief["closed_at"] = now_logical()
        touch(brief)
        cascade.realize_brief_forecasts(brief)
        cascade.archive_brief_formulas(brief)
    else:
        brief["status"] = "CLOSED_LOST"
        brief["outcome"] = "LOST"
        brief["loss_reason"] = loss_reason
        brief["closed_at"] = now_logical()
        touch(brief)
        cascade.lapse_brief_forecasts(brief)
        cascade.archive_brief_formulas(brief)
        cascade.cancel_live_brief_shipments(brief, "BRIEF_CLOSED_LOST")
    return ok(S.brief_out(brief))
