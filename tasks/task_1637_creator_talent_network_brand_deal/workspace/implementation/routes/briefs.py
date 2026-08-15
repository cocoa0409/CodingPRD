"""Brief endpoints: create, list, get, publish, close, and nested pitch
listing/creation (OCC on brief version + auto-supersede)."""

from flask import Blueprint, request

import db
import errors as err
import response as resp
from middleware import require_roles
from services import helpers as H, lifecycle

bp = Blueprint("briefs", __name__)


@bp.route("/briefs", methods=["POST"])
@require_roles("BrandManager")
def create_brief(actor):
    payload = H.body()
    H.req_fields(payload, ["brand_id", "title", "niche", "min_followers",
                           "min_engagement_bps", "slots_total", "budget_cents",
                           "deliverables_per_slot", "usage_rights_days",
                           "exclusivity_category", "exclusivity_days",
                           "submission_window_start", "submission_window_end",
                           "content_window_start", "content_window_end"])

    # Existence: brand_id must resolve (ERR_NOT_FOUND) before its standing is
    # evaluated.
    brand = H.get_or_404(db.brands, H.require_str(payload, "brand_id"), "brand")

    title = H.require_str(payload, "title")
    niche = H.require_enum(payload, "niche", H.NICHE_ENUM)
    min_followers = H.require_int(payload, "min_followers", minimum=0)
    min_engagement_bps = H.require_int(payload, "min_engagement_bps", minimum=0)
    slots_total = H.require_int(payload, "slots_total", minimum=1)
    budget_cents = H.require_int(payload, "budget_cents", minimum=1)
    deliverables_per_slot = H.require_int(payload, "deliverables_per_slot",
                                          minimum=1)
    usage_rights_days = H.require_int(payload, "usage_rights_days", minimum=1)
    exclusivity_category = H.require_enum(payload, "exclusivity_category",
                                          H.EXCLUSIVITY_ENUM)
    exclusivity_days = H.require_int(payload, "exclusivity_days", minimum=0)
    whitelisting_required = H.opt_bool(payload, "whitelisting_required",
                                       default=False)
    revision_rounds_included = H.opt_int(payload, "revision_rounds_included",
                                         minimum=0, default=2)

    sub_start = H.require_dt(payload, "submission_window_start")
    sub_end = H.require_dt(payload, "submission_window_end")
    con_start = H.require_dt(payload, "content_window_start")
    con_end = H.require_dt(payload, "content_window_end")
    if sub_start > sub_end or con_start > con_end:
        raise err.validation("window starts must be at or before their ends")

    # Business rule: brand must be ACTIVE.
    if brand["status"] != "ACTIVE":
        raise err.ApiError(err.ERR_BRAND_SUSPENDED,
                           "Brief creation requires brand.status == ACTIVE",
                           422)

    brief = H.new_entity()
    brief.update({
        "brand_id": brand["id"],
        "title": title,
        "niche": niche,
        "min_followers": min_followers,
        "min_engagement_bps": min_engagement_bps,
        "slots_total": slots_total,
        "slots_committed": 0,
        "budget_cents": budget_cents,
        "deliverables_per_slot": deliverables_per_slot,
        "usage_rights_days": usage_rights_days,
        "exclusivity_category": exclusivity_category,
        "exclusivity_days": exclusivity_days,
        "whitelisting_required": whitelisting_required,
        "revision_rounds_included": revision_rounds_included,
        "submission_window_start": db.iso_format(sub_start),
        "submission_window_end": db.iso_format(sub_end),
        "content_window_start": db.iso_format(con_start),
        "content_window_end": db.iso_format(con_end),
        "status": "DRAFT",
    })
    db.briefs[brief["id"]] = brief
    return resp.created(brief)


@bp.route("/briefs", methods=["GET"])
@require_roles("BrandManager", "TalentManager", "Creator", "Brand",
               "FinanceAdmin")
def list_briefs(actor):
    items = list(db.briefs.values())
    brand_id = request.args.get("brand_id")
    status = request.args.get("status")
    niche = request.args.get("niche")
    if brand_id is not None:
        items = [b for b in items if b["brand_id"] == brand_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    if niche is not None:
        items = [b for b in items if b["niche"] == niche]
    return resp.paginate(items, request.args)


@bp.route("/briefs/<bid>", methods=["GET"])
@require_roles("BrandManager", "TalentManager", "Creator", "Brand",
               "FinanceAdmin")
def get_brief(actor, bid):
    brief = H.get_or_404(db.briefs, bid, "brief")
    return resp.ok(brief)


@bp.route("/briefs/<bid>/publish", methods=["POST"])
@require_roles("BrandManager")
def publish_brief(actor, bid):
    brief = H.get_or_404(db.briefs, bid, "brief")
    if brief["status"] in ("EXPIRED", "CLOSED"):
        raise err.already_terminal(f"Brief is {brief['status']}")
    if brief["status"] != "DRAFT":
        raise err.invalid_state("Only a DRAFT brief can be published")

    brand = db.brands.get(brief["brand_id"])
    if brand is None or brand["status"] != "ACTIVE":
        raise err.ApiError(err.ERR_BRAND_SUSPENDED,
                           "Brief publish requires brand.status == ACTIVE",
                           422)
    if brand["credit_hold"]:
        raise err.ApiError(err.ERR_BRAND_CREDIT_HOLD,
                           "Brand is on credit hold", 402)

    sub_start = db.parse_iso(brief["submission_window_start"])
    sub_end = db.parse_iso(brief["submission_window_end"])
    con_start = db.parse_iso(brief["content_window_start"])
    con_end = db.parse_iso(brief["content_window_end"])
    if sub_start > sub_end or con_start > con_end:
        raise err.validation("window starts must be at or before their ends")

    brief["status"] = "OPEN"
    H.touch(brief)
    return resp.ok(brief)


@bp.route("/briefs/<bid>/close", methods=["POST"])
@require_roles("BrandManager")
def close_brief(actor, bid):
    brief = H.get_or_404(db.briefs, bid, "brief")
    if brief["status"] in ("EXPIRED", "CLOSED"):
        raise err.already_terminal(f"Brief is {brief['status']}")
    if brief["status"] == "OPEN":
        if brief["slots_committed"] != 0:
            raise err.invalid_state(
                "An OPEN brief closes only while slots_committed is zero")
        brief["status"] = "CLOSED"
        H.touch(brief)
        lifecycle.withdraw_open_pitches_of_brief(brief["id"])
        return resp.ok(brief)
    if brief["status"] == "AWARDED":
        for deal in db.deals.values():
            if deal["brief_id"] == brief["id"] and deal["status"] not in (
                    "COMPLETED", "TERMINATED"):
                raise err.invalid_state(
                    "An AWARDED brief closes only once every deal is "
                    "COMPLETED or TERMINATED")
        brief["status"] = "CLOSED"
        H.touch(brief)
        return resp.ok(brief)
    raise err.invalid_state(f"Brief in {brief['status']} cannot be closed")


@bp.route("/briefs/<bid>/pitches", methods=["GET"])
@require_roles("BrandManager", "TalentManager")
def list_brief_pitches(actor, bid):
    H.get_or_404(db.briefs, bid, "brief")
    items = [p for p in db.pitches.values() if p["brief_id"] == bid]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return resp.paginate(items, request.args)


@bp.route("/briefs/<bid>/pitches", methods=["POST"])
@require_roles("TalentManager")
def create_pitch(actor, bid):
    brief = H.get_or_404(db.briefs, bid, "brief")

    # Priority 5: payload well-formedness.
    payload = H.body()
    H.req_fields(payload, ["creator_id", "proposed_fee_cents", "concept_note",
                           "expected_brief_version"])
    creator_id = H.require_str(payload, "creator_id")
    proposed_fee = H.require_int(payload, "proposed_fee_cents", minimum=1)
    concept_note = H.require_str(payload, "concept_note")

    # Priority 6: optimistic concurrency on the brief version.
    expected = payload.get("expected_brief_version")
    if not H.is_int(expected):
        raise err.validation("expected_brief_version must be an integer")
    if expected != brief["version"]:
        raise err.stale_version(
            "expected_brief_version does not match the brief's current version")

    # Priority 7: terminal lockdown on the brief.
    if brief["status"] in ("EXPIRED", "CLOSED"):
        raise err.already_terminal(f"Brief is {brief['status']}")
    # Priority 8: state precondition.
    if brief["status"] != "OPEN":
        raise err.invalid_state("Pitches are accepted only on an OPEN brief")

    # Payload FK must resolve before its standing can be evaluated.
    creator = H.get_or_404(db.creators, creator_id, "creator")

    # Priority 19: pitch eligibility (boundary inclusive).
    if (creator["followers"] < brief["min_followers"]
            or creator["engagement_rate_bps"] < brief["min_engagement_bps"]):
        raise err.ApiError(err.ERR_PITCH_REQUIREMENTS_NOT_MET,
                           "Creator below brief min_followers or "
                           "min_engagement_bps", 422)

    # Priority 23: submission window, both bounds inclusive.
    now = db.get_clock()
    if not (db.parse_iso(brief["submission_window_start"]) <= now
            <= db.parse_iso(brief["submission_window_end"])):
        raise err.ApiError(err.ERR_SUBMISSION_WINDOW_CLOSED,
                           "Pitch created outside the brief submission window",
                           422)

    # Priority 26: creator must be ACTIVE.
    if creator["status"] != "ACTIVE":
        raise err.ApiError(err.ERR_CREATOR_NOT_ACTIVE,
                           "Pitch requires creator.status == ACTIVE", 422)

    pitch = H.new_entity()
    pitch.update({
        "brief_id": brief["id"],
        "creator_id": creator["id"],
        "proposed_fee_cents": proposed_fee,
        "concept_note": concept_note,
        "status": "SUBMITTED",
        "negotiation_rounds": 0,
        "superseded_by_pitch_id": None,
        "deal_id": None,
    })
    db.pitches[pitch["id"]] = pitch

    # Side effects: supersede the same creator's prior SUBMITTED pitch on this
    # brief; advance the brief's version by one.
    for p in db.pitches.values():
        if (p["id"] != pitch["id"] and p["brief_id"] == brief["id"]
                and p["creator_id"] == creator["id"]
                and p["status"] == "SUBMITTED"):
            p["status"] = "SUPERSEDED"
            p["superseded_by_pitch_id"] = pitch["id"]
            H.touch(p)
    H.touch(brief)

    return resp.created(pitch)
