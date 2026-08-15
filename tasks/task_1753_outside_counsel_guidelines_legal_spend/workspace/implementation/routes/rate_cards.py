"""RateCard + TimekeeperRate endpoints, including the annual-increase cap clamp."""

import math
from decimal import Decimal

from flask import Blueprint, request

import db
import errors
import helpers
import response as resp
from middleware import require_auth, ROLE_LEGAL_OPS, ROLE_FIRM_USER

bp = Blueprint("rate_cards", __name__)


@bp.route("/legal-departments/<deptId>/panel-firms/<firmId>/rate-cards", methods=["POST"])
def create_rate_card(deptId, firmId):
    user_id, _ = require_auth([ROLE_FIRM_USER])
    _, firm = helpers.resolve_firm(deptId, firmId)
    if user_id != firmId:
        raise errors.firm_mismatch()
    body = helpers.get_body()
    helpers.require_fields(body, ["effective_year", "expected_panel_firm_version"])
    # OCC: expected_panel_firm_version vs current firm version (evaluated late).
    try:
        expected = int(body["expected_panel_firm_version"])
    except (TypeError, ValueError):
        raise errors.stale_version()
    if expected != int(firm.get("version", 1)):
        raise errors.stale_version()
    rec = db.base_resource({
        "panel_firm_id": firmId,
        "effective_year": int(body["effective_year"]),
        "status": "DRAFT",
        "submitted_at": None,
    })
    db.rate_cards[rec["id"]] = rec
    # Rate-card creation advances the firm's version.
    db.touch(firm)
    return resp.success_object(resp.public(rec), 201)


@bp.route("/legal-departments/<deptId>/panel-firms/<firmId>/rate-cards/<cardId>", methods=["GET"])
def get_rate_card(deptId, firmId, cardId):
    require_auth([ROLE_LEGAL_OPS, ROLE_FIRM_USER])
    _, _, card = helpers.resolve_rate_card(deptId, firmId, cardId)
    return resp.success_object(resp.public(card))


@bp.route("/legal-departments/<deptId>/panel-firms/<firmId>/rate-cards", methods=["GET"])
def list_rate_cards(deptId, firmId):
    require_auth([ROLE_LEGAL_OPS, ROLE_FIRM_USER])
    helpers.resolve_firm(deptId, firmId)
    limit, offset = resp.parse_pagination(request.args)
    records = [c for c in db.rate_cards.values() if c.get("panel_firm_id") == firmId]
    records = helpers.apply_filters(records, request.args, ["status", "effective_year"])
    items, total = resp.paginate(records, limit, offset)
    return resp.success_list(items, limit, offset, total)


@bp.route("/legal-departments/<deptId>/panel-firms/<firmId>/rate-cards/<cardId>/submit", methods=["POST"])
def submit_rate_card(deptId, firmId, cardId):
    user_id, _ = require_auth([ROLE_FIRM_USER])
    _, firm, card = helpers.resolve_rate_card(deptId, firmId, cardId)
    if card.get("status") != "DRAFT":
        raise errors.invalid_state()
    if user_id != card.get("panel_firm_id"):
        raise errors.firm_mismatch()
    if firm.get("status") != "ACTIVE":
        raise errors.firm_not_active()
    # Every referenced timekeeper must be QUALIFIED.
    for rate in db.timekeeper_rates.values():
        if rate.get("rate_card_id") != cardId:
            continue
        tk = db.timekeepers.get(rate.get("timekeeper_id"))
        if tk is None or tk.get("qualification_status") != "QUALIFIED":
            raise errors.timekeeper_not_qualified()
    # No other card of this firm with the same effective_year in SUBMITTED/APPROVED.
    for other in db.rate_cards.values():
        if other.get("panel_firm_id") == firmId and other.get("id") != cardId:
            if other.get("effective_year") == card.get("effective_year") and other.get("status") in ("SUBMITTED", "APPROVED"):
                raise errors.rate_card_year_conflict()
    card["status"] = "SUBMITTED"
    card["submitted_at"] = db.now_iso()
    db.touch(card)
    return resp.success_object(resp.public(card))


def _sub_cap_pct(dept, tk_class):
    cap = Decimal(str(dept.get("annual_rate_increase_cap_pct", 0)))
    if tk_class == "PARTNER":
        return cap
    if tk_class == "ASSOCIATE":
        return cap * Decimal("0.80")
    if tk_class == "PARALEGAL":
        return cap * Decimal("0.60")
    return cap


def _prior_approved_card(firm_id, effective_year):
    """Most recent APPROVED card of the firm with strictly earlier
    effective_year. Order: effective_year DESC, tie-break created_at ASC."""
    candidates = [
        c for c in db.rate_cards.values()
        if c.get("panel_firm_id") == firm_id
        and c.get("status") == "APPROVED"
        and int(c.get("effective_year", 0)) < int(effective_year)
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda c: (-int(c.get("effective_year", 0)), c.get("created_at", ""), c.get("_seq", 0)))
    return candidates[0]


@bp.route("/legal-departments/<deptId>/panel-firms/<firmId>/rate-cards/<cardId>/approve", methods=["POST"])
def approve_rate_card(deptId, firmId, cardId):
    require_auth([ROLE_LEGAL_OPS])
    dept, firm, card = helpers.resolve_rate_card(deptId, firmId, cardId)
    if card.get("status") != "SUBMITTED":
        raise errors.invalid_state()

    prior = _prior_approved_card(firmId, card.get("effective_year"))
    prior_rates = {}
    if prior is not None:
        for r in db.timekeeper_rates.values():
            if r.get("rate_card_id") == prior["id"]:
                prior_rates[r.get("timekeeper_id")] = r

    for rate in db.timekeeper_rates.values():
        if rate.get("rate_card_id") != cardId:
            continue
        proposed = int(rate.get("hourly_rate_cents", 0))
        prior_row = prior_rates.get(rate.get("timekeeper_id"))
        if prior is None or prior_row is None:
            # No baseline -> proposed rates stand, no clamping.
            rate["approved_rate_cents"] = proposed
        else:
            tk = db.timekeepers.get(rate.get("timekeeper_id"))
            sub_cap = _sub_cap_pct(dept, tk.get("tk_class") if tk else None)
            prior_approved = int(prior_row.get("approved_rate_cents") or prior_row.get("hourly_rate_cents") or 0)
            ceiling = math.floor(float(Decimal(prior_approved) * (Decimal("1") + sub_cap / Decimal("100"))))
            rate["approved_rate_cents"] = min(proposed, ceiling)
        db.touch(rate)

    # Supersede any other APPROVED card of this firm.
    for other in db.rate_cards.values():
        if other.get("panel_firm_id") == firmId and other.get("id") != cardId and other.get("status") == "APPROVED":
            other["status"] = "SUPERSEDED"
            db.touch(other)

    card["status"] = "APPROVED"
    db.touch(card)
    return resp.success_object(resp.public(card))


@bp.route("/legal-departments/<deptId>/panel-firms/<firmId>/rate-cards/<cardId>/reject", methods=["POST"])
def reject_rate_card(deptId, firmId, cardId):
    require_auth([ROLE_LEGAL_OPS])
    _, _, card = helpers.resolve_rate_card(deptId, firmId, cardId)
    if card.get("status") != "SUBMITTED":
        raise errors.invalid_state()
    card["status"] = "REJECTED"
    db.touch(card)
    return resp.success_object(resp.public(card))


@bp.route("/legal-departments/<deptId>/panel-firms/<firmId>/rate-cards/<cardId>/revise", methods=["POST"])
def revise_rate_card(deptId, firmId, cardId):
    user_id, _ = require_auth([ROLE_FIRM_USER])
    _, _, card = helpers.resolve_rate_card(deptId, firmId, cardId)
    if card.get("status") != "REJECTED":
        raise errors.invalid_state()
    if user_id != card.get("panel_firm_id"):
        raise errors.firm_mismatch()
    card["status"] = "DRAFT"
    db.touch(card)
    return resp.success_object(resp.public(card))


# ---------------------------------------------------------------------------
# TimekeeperRate rows
# ---------------------------------------------------------------------------

@bp.route("/legal-departments/<deptId>/panel-firms/<firmId>/rate-cards/<cardId>/rates", methods=["POST"])
def add_rate(deptId, firmId, cardId):
    user_id, _ = require_auth([ROLE_FIRM_USER])
    _, _, card = helpers.resolve_rate_card(deptId, firmId, cardId)
    if user_id != card.get("panel_firm_id"):
        raise errors.firm_mismatch()
    if card.get("status") != "DRAFT":
        raise errors.invalid_state()
    body = helpers.get_body()
    helpers.require_fields(body, ["timekeeper_id", "hourly_rate_cents"])
    tk = db.timekeepers.get(body["timekeeper_id"])
    if tk is None or tk.get("panel_firm_id") != firmId:
        raise errors.referential_integrity("timekeeper_id does not resolve within this firm")
    rec = db.base_resource({
        "rate_card_id": cardId,
        "timekeeper_id": body["timekeeper_id"],
        "hourly_rate_cents": int(body["hourly_rate_cents"]),
        "approved_rate_cents": None,
    })
    db.timekeeper_rates[rec["id"]] = rec
    return resp.success_object(resp.public(rec), 201)


@bp.route("/legal-departments/<deptId>/panel-firms/<firmId>/rate-cards/<cardId>/rates", methods=["GET"])
def list_rates(deptId, firmId, cardId):
    require_auth([ROLE_LEGAL_OPS, ROLE_FIRM_USER])
    helpers.resolve_rate_card(deptId, firmId, cardId)
    limit, offset = resp.parse_pagination(request.args)
    records = [r for r in db.timekeeper_rates.values() if r.get("rate_card_id") == cardId]
    items, total = resp.paginate(records, limit, offset)
    return resp.success_list(items, limit, offset, total)


@bp.route("/legal-departments/<deptId>/panel-firms/<firmId>/rate-cards/<cardId>/rates/<rateId>", methods=["GET"])
def get_rate(deptId, firmId, cardId, rateId):
    require_auth([ROLE_LEGAL_OPS, ROLE_FIRM_USER])
    _, _, _, rate = helpers.resolve_rate(deptId, firmId, cardId, rateId)
    return resp.success_object(resp.public(rate))
