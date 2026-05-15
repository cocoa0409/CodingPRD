"""SponsorEntitlement workflow (§3.8)."""

from flask import g

import db
import clock
from errors import (
    AppError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_INVALID_INPUT,
    ERR_FORBIDDEN,
)
from services.common import (
    stamp_create,
    bump,
    check_occ,
    must_dict,
    write_audit,
)
from services import calculations


VALID_CODES = {"SIGNAGE", "PROGRAM_AD", "LOUNGE", "SPEAKING_SLOT", "BRANDED_GIFT"}
VALID_TIERS = {"BRONZE", "SILVER", "GOLD", "PLATINUM"}


def _get_ent(eid):
    e = db.entitlements.get(eid)
    if e is None:
        raise AppError(ERR_NOT_FOUND, "Entitlement not found.", 404)
    return e


def create_entitlement(exhibition_id: str, body: dict) -> dict:
    ex = db.exhibitions.get(exhibition_id)
    if ex is None:
        raise AppError(ERR_NOT_FOUND, "Exhibition not found.", 404)
    body = must_dict(body)
    exhibitor_id = body.get("exhibitor_id")
    code = body.get("entitlement_code")
    tier = body.get("sponsor_tier")
    deadline = body.get("deadline")
    if not exhibitor_id:
        raise AppError(ERR_INVALID_INPUT, "exhibitor_id is required.", 422)
    if code not in VALID_CODES:
        raise AppError(ERR_INVALID_INPUT, "Invalid entitlement_code.", 422)
    if tier not in VALID_TIERS:
        raise AppError(ERR_INVALID_INPUT, "Invalid sponsor_tier.", 422)
    if not deadline or clock.parse_iso(deadline) is None:
        raise AppError(ERR_INVALID_INPUT, "Invalid deadline.", 422)
    row = {
        "exhibition_id": exhibition_id,
        "exhibitor_id": exhibitor_id,
        "entitlement_code": code,
        "sponsor_tier": tier,
        "deadline": deadline,
        "evidence_url": None,
        "status": "PLANNED",
        "make_good_credit_cents": 0,
        "fulfillment_score": 0.0,
    }
    stamp_create(row)
    db.entitlements[row["id"]] = row
    return row


def start_entitlement(eid, body):
    e = _get_ent(eid)
    if e["status"] != "PLANNED":
        raise AppError(ERR_INVALID_STATE, "Entitlement not in PLANNED.", 409)
    check_occ(e, body)
    e["status"] = "IN_PROGRESS"
    bump(e)
    return e


def fulfill_entitlement(eid, body):
    e = _get_ent(eid)
    if e["status"] != "IN_PROGRESS":
        raise AppError(ERR_INVALID_STATE, "Entitlement not in IN_PROGRESS.", 409)
    body = must_dict(body)
    evidence_url = body.get("evidence_url")
    if not evidence_url or not isinstance(evidence_url, str) or not evidence_url.strip():
        raise AppError(ERR_INVALID_INPUT, "evidence_url required.", 422)
    deadline_dt = clock.parse_iso(e.get("deadline"))
    if deadline_dt is None or clock.now() > deadline_dt:
        raise AppError(ERR_INVALID_STATE, "Past deadline.", 409)
    check_occ(e, body)
    e["status"] = "FULFILLED"
    e["evidence_url"] = evidence_url
    e["fulfillment_score"] = calculations.fulfillment_score_final(
        "FULFILLED", deadline_dt, clock.now()
    )
    bump(e)
    write_audit("ENTITLEMENT", e["id"], "FULFILL", {"evidence_url": evidence_url})
    return e


def mark_missed(eid, body):
    e = _get_ent(eid)
    if e["status"] != "IN_PROGRESS":
        raise AppError(ERR_INVALID_STATE, "Entitlement not in IN_PROGRESS.", 409)
    ex = db.exhibitions.get(e["exhibition_id"])
    if ex is None:
        raise AppError(ERR_NOT_FOUND, "Exhibition not found.", 404)
    deadline_dt = clock.parse_iso(e.get("deadline"))
    now_dt = clock.now()
    # Precondition: now > deadline OR Exhibition.status == TEARDOWN
    if not ((deadline_dt is not None and now_dt > deadline_dt) or ex["status"] == "TEARDOWN"):
        raise AppError(ERR_INVALID_STATE, "Cannot mark missed yet.", 409)
    check_occ(e, body)
    e["status"] = "MISSED"
    e["make_good_credit_cents"] = calculations.entitlement_make_good(
        e["sponsor_tier"], e["entitlement_code"]
    )
    e["fulfillment_score"] = calculations.fulfillment_score_final(
        "MISSED", deadline_dt, now_dt
    )
    bump(e)
    return e


def offer_make_good(eid, body):
    e = _get_ent(eid)
    if e["status"] != "MISSED":
        raise AppError(ERR_INVALID_STATE, "Entitlement not in MISSED.", 409)
    if int(e.get("make_good_credit_cents") or 0) <= 0:
        raise AppError(ERR_INVALID_STATE, "make_good_credit_cents must be > 0.", 409)
    check_occ(e, body)
    e["status"] = "MAKE_GOOD_OFFERED"
    bump(e)
    write_audit("ENTITLEMENT", e["id"], "MAKE_GOOD_OFFERED", {
        "make_good_credit_cents": int(e["make_good_credit_cents"])
    })
    return e


def accept_make_good(eid, body):
    e = _get_ent(eid)
    if g.role == "Exhibitor" and e["exhibitor_id"] != g.user_id:
        raise AppError(ERR_FORBIDDEN, "Entitlement not owned by exhibitor.", 403)
    if e["status"] != "MAKE_GOOD_OFFERED":
        raise AppError(ERR_INVALID_STATE, "Entitlement not in MAKE_GOOD_OFFERED.", 409)
    check_occ(e, body)
    e["status"] = "MAKE_GOOD_ACCEPTED"
    e["fulfillment_score"] = calculations.fulfillment_score_final(
        "MAKE_GOOD_ACCEPTED", clock.parse_iso(e.get("deadline")), clock.now()
    )
    bump(e)
    return e


def waive_entitlement(eid, body):
    e = _get_ent(eid)
    if g.role == "Exhibitor" and e["exhibitor_id"] != g.user_id:
        raise AppError(ERR_FORBIDDEN, "Entitlement not owned by exhibitor.", 403)
    if e["status"] != "PLANNED":
        raise AppError(ERR_INVALID_STATE, "Entitlement not in PLANNED.", 409)
    check_occ(e, body)
    e["status"] = "WAIVED"
    e["fulfillment_score"] = calculations.fulfillment_score_final(
        "WAIVED", clock.parse_iso(e.get("deadline")), clock.now()
    )
    bump(e)
    return e


# ---- Clock-advance cascade: auto-MISS entitlements whose deadline has passed
# while still IN_PROGRESS.
def clock_cascade(now_dt):
    for e in list(db.entitlements.values()):
        if e["status"] != "IN_PROGRESS":
            continue
        deadline_dt = clock.parse_iso(e.get("deadline"))
        if deadline_dt is None:
            continue
        if now_dt > deadline_dt:
            e["status"] = "MISSED"
            e["make_good_credit_cents"] = calculations.entitlement_make_good(
                e["sponsor_tier"], e["entitlement_code"]
            )
            e["fulfillment_score"] = calculations.fulfillment_score_final(
                "MISSED", deadline_dt, now_dt
            )
            bump(e)
