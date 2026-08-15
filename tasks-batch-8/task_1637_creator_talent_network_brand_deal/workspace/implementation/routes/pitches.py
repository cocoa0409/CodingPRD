"""Pitch endpoints: list, get, brand actions, talent actions. ACCEPT creates
the Deal and may auto-award the brief."""

from flask import Blueprint, request

import db
import errors as err
import response as resp
from middleware import require_roles
from services import helpers as H

bp = Blueprint("pitches", __name__)

PITCH_TERMINAL = {"ACCEPTED", "REJECTED", "WITHDRAWN", "SUPERSEDED"}


@bp.route("/pitches", methods=["GET"])
@require_roles("BrandManager", "TalentManager")
def list_pitches(actor):
    items = list(db.pitches.values())
    brief_id = request.args.get("brief_id")
    creator_id = request.args.get("creator_id")
    deal_id = request.args.get("deal_id")
    superseded_by = request.args.get("superseded_by_pitch_id")
    status = request.args.get("status")
    if brief_id is not None:
        items = [p for p in items if p["brief_id"] == brief_id]
    if creator_id is not None:
        items = [p for p in items if p["creator_id"] == creator_id]
    if deal_id is not None:
        items = [p for p in items if p.get("deal_id") == deal_id]
    if superseded_by is not None:
        items = [p for p in items if p.get("superseded_by_pitch_id") == superseded_by]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return resp.paginate(items, request.args)


@bp.route("/pitches/<pid>", methods=["GET"])
@require_roles("BrandManager", "TalentManager")
def get_pitch(actor, pid):
    return resp.ok(H.get_or_404(db.pitches, pid, "pitch"))


def _brief_or_404(pitch):
    return H.get_or_404(db.briefs, pitch["brief_id"], "brief")


@bp.route("/pitches/<pid>/brand-action", methods=["POST"])
@require_roles("BrandManager")
def brand_action(actor, pid):
    pitch = H.get_or_404(db.pitches, pid, "pitch")
    payload = H.body()
    H.req_fields(payload, ["action"])
    action = H.require_enum(payload, "action",
                            {"SHORTLIST", "COUNTER", "REJECT", "ACCEPT"})

    if pitch["status"] in PITCH_TERMINAL:
        raise err.already_terminal(f"Pitch is {pitch['status']}")

    brief = _brief_or_404(pitch)

    if action == "SHORTLIST":
        if pitch["status"] != "SUBMITTED":
            raise err.invalid_state("Only a SUBMITTED pitch can be shortlisted")
        if brief["status"] != "OPEN":
            raise err.invalid_state("Shortlisting requires brief OPEN")
        pitch["status"] = "SHORTLISTED"
        H.touch(pitch)
        return resp.ok(pitch)

    if action == "COUNTER":
        if pitch["status"] != "SHORTLISTED":
            raise err.invalid_state("Only a SHORTLISTED pitch can be countered")
        if brief["status"] != "OPEN":
            raise err.invalid_state("Countering requires brief OPEN")
        counter_fee = H.require_int(payload, "counter_fee_cents", minimum=1)
        if pitch["negotiation_rounds"] >= H.MAX_PITCH_NEGOTIATION_ROUNDS:
            raise err.ApiError(err.ERR_NEGOTIATION_LIMIT_EXCEEDED,
                               "Pitch negotiation round cap reached", 422)
        pitch["proposed_fee_cents"] = counter_fee
        pitch["negotiation_rounds"] += 1
        pitch["status"] = "COUNTERED"
        H.touch(pitch)
        return resp.ok(pitch)

    if action == "REJECT":
        if pitch["status"] not in ("SUBMITTED", "SHORTLISTED", "COUNTERED"):
            raise err.invalid_state("Pitch cannot be rejected from "
                                    f"{pitch['status']}")
        pitch["status"] = "REJECTED"
        H.touch(pitch)
        return resp.ok(pitch)

    # action == "ACCEPT"
    if pitch["status"] != "SHORTLISTED":
        raise err.invalid_state("Only a SHORTLISTED pitch can be accepted")
    if brief["status"] not in ("OPEN", "AWARDED"):
        raise err.invalid_state(
            "Pitch acceptance requires brief OPEN or AWARDED")
    if brief["slots_committed"] >= brief["slots_total"]:
        raise err.ApiError(err.ERR_BRIEF_SLOTS_FULL,
                           "Brief slots are fully committed", 422)
    committed_fees = 0
    for p in db.pitches.values():
        if p["brief_id"] == brief["id"] and p["status"] == "ACCEPTED":
            d = db.deals.get(p.get("deal_id") or "")
            if d is not None and d["status"] != "TERMINATED":
                committed_fees += int(p["proposed_fee_cents"])
    if committed_fees + pitch["proposed_fee_cents"] > brief["budget_cents"]:
        raise err.ApiError(err.ERR_BRIEF_BUDGET_EXCEEDED,
                           "Pitch acceptance would exceed brief budget", 422)

    # Create the deal in DRAFT, copying brief terms.
    deal = H.new_entity()
    deal.update({
        "pitch_id": pitch["id"],
        "brief_id": brief["id"],
        "creator_id": pitch["creator_id"],
        "brand_id": brief["brand_id"],
        "status": "DRAFT",
        "negotiation_rounds": 0,
        "fee_base_cents": pitch["proposed_fee_cents"],
        "fee_total_cents": None,
        "usage_rights_days": brief["usage_rights_days"],
        "exclusivity_category": brief["exclusivity_category"],
        "exclusivity_days": brief["exclusivity_days"],
        "whitelisting": brief["whitelisting_required"],
        "revision_rounds_included": brief["revision_rounds_included"],
        "terms_version": 0,
        "exclusive_window_start": None,
        "exclusive_window_end": None,
        "activated_at": None,
        "reduction_pct": 0,
        "bonus_accrued_cents": 0,
    })
    db.deals[deal["id"]] = deal

    pitch["status"] = "ACCEPTED"
    pitch["deal_id"] = deal["id"]
    H.touch(pitch)

    H.recompute_slots_committed(brief["id"])
    if brief["slots_committed"] == brief["slots_total"] and brief["status"] == "OPEN":
        brief["status"] = "AWARDED"
        H.touch(brief)

    return resp.ok(pitch)


@bp.route("/pitches/<pid>/talent-action", methods=["POST"])
@require_roles("TalentManager")
def talent_action(actor, pid):
    pitch = H.get_or_404(db.pitches, pid, "pitch")
    payload = H.body()
    H.req_fields(payload, ["action"])
    action = H.require_enum(payload, "action", {"RESUBMIT", "WITHDRAW"})

    if pitch["status"] in PITCH_TERMINAL:
        raise err.already_terminal(f"Pitch is {pitch['status']}")

    brief = _brief_or_404(pitch)

    if action == "RESUBMIT":
        if pitch["status"] != "COUNTERED":
            raise err.invalid_state("Only a COUNTERED pitch can be resubmitted")
        if brief["status"] != "OPEN":
            raise err.invalid_state("Resubmission requires brief OPEN")
        new_fee = H.require_int(payload, "proposed_fee_cents", minimum=1)
        if pitch["negotiation_rounds"] >= H.MAX_PITCH_NEGOTIATION_ROUNDS:
            raise err.ApiError(err.ERR_NEGOTIATION_LIMIT_EXCEEDED,
                               "Pitch negotiation round cap reached", 422)
        pitch["proposed_fee_cents"] = new_fee
        pitch["negotiation_rounds"] += 1
        pitch["status"] = "SHORTLISTED"
        H.touch(pitch)
        return resp.ok(pitch)

    # WITHDRAW
    if pitch["status"] not in ("SUBMITTED", "SHORTLISTED", "COUNTERED"):
        raise err.invalid_state("Pitch cannot be withdrawn from "
                                f"{pitch['status']}")
    pitch["status"] = "WITHDRAWN"
    H.touch(pitch)
    return resp.ok(pitch)
