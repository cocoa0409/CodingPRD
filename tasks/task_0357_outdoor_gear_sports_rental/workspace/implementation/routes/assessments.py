"""DamageAssessment transitions: dispute (Renter), reassess (ShopAdmin)."""
from flask import Blueprint

import db
import errors
import store
import serializers as S
import middleware as M
from response import ok
import calculations as C

bp = Blueprint("assessments", __name__)


def _checkout_checkin_ratings(reservation_id):
    checkout_rating = None
    checkin_rating = None
    for cr in db.condition_reports.values():
        if cr["reservation_id"] != reservation_id:
            continue
        if cr["phase"] == "CHECKOUT":
            checkout_rating = cr["condition_rating"]
        elif cr["phase"] == "CHECKIN":
            checkin_rating = cr["condition_rating"]
    return checkout_rating, checkin_rating


@bp.post("/rental/damage-assessments/<id>/dispute")
def dispute(id):
    body = M.get_json_body()
    # payload well-formedness: expected_damage_assessment_version required
    expected = M.require_int(body, "expected_damage_assessment_version")
    user_id, role = M.get_auth()
    M.require_role(role, {"Renter"})
    rec = db.damage_assessments.get(id)
    if not rec:
        raise errors.not_found("damage assessment not found")
    reservation = db.reservations.get(rec["reservation_id"])
    if not reservation:
        raise errors.not_found("reservation not found")
    # ownership: Renter may dispute only against own reservation
    if reservation["customer_id"] != user_id:
        raise errors.unauthorized("renter does not own this reservation")
    # state: must be ASSESSED to dispute
    if rec["status"] != "ASSESSED":
        raise errors.invalid_state("assessment is not ASSESSED")
    # OCC
    if expected != rec["version"]:
        raise errors.stale_version("assessment version mismatch")
    rec["status"] = "DISPUTED"
    store.touch(rec)
    return ok(S.damage_assessment(rec))


@bp.post("/rental/damage-assessments/<id>/reassess")
def reassess(id):
    body = M.get_json_body()
    expected = M.require_int(body, "expected_damage_assessment_version")
    override_outcome = body.get("override_outcome")
    if override_outcome is not None and override_outcome not in {"NONE", "DAMAGE", "LOSS"}:
        raise errors.validation("override_outcome must be NONE|DAMAGE|LOSS")
    _, role = M.get_auth()
    M.require_role(role, {"ShopAdmin"})
    rec = db.damage_assessments.get(id)
    if not rec:
        raise errors.not_found("damage assessment not found")
    reservation = db.reservations.get(rec["reservation_id"])
    if not reservation:
        raise errors.not_found("reservation not found")
    # state: must be DISPUTED to reassess
    if rec["status"] != "DISPUTED":
        raise errors.invalid_state("assessment is not DISPUTED")
    # OCC
    if expected != rec["version"]:
        raise errors.stale_version("assessment version mismatch")

    # recompute outcome and charge_cents by the same severity-and-waiver rules
    gear_unit = db.gear_units.get(reservation["gear_unit_id"])
    rate_card = db.rate_cards.get(reservation["rate_card_id"])
    checkout_rating, checkin_rating = _checkout_checkin_ratings(reservation["id"])
    loss_fee = rate_card["loss_fee_cents"] if rate_card else 0
    outcome, charge, waiver_applied = C.damage_charge(
        checkout_rating, checkin_rating, reservation["damage_waiver_opted"], loss_fee
    )
    if override_outcome is not None:
        outcome = override_outcome

    rec["status"] = "ASSESSED"
    rec["outcome"] = outcome
    rec["charge_cents"] = charge
    rec["waiver_applied"] = waiver_applied
    store.touch(rec)
    return ok(S.damage_assessment(rec))
