"""Exercise routes + Form 3921 generation. PRD §3.8, §3.9."""
from __future__ import annotations

from flask import Blueprint, g, request

import db
from common import (
    get_body, pagination_params, paginate_and_sort, require_int,
    require_string, stamp_common_fields, stamp_immutable, touch,
)
from errors import (
    APIError, ERR_NOT_FOUND, ERR_FORBIDDEN, ERR_INVALID_STATE,
    ERR_EXCEEDS_EXERCISABLE, ERR_ELECTION_BLOCKS_REVERSE, ERR_VALIDATION,
)
from middleware import require_roles
from response import created, success, list_response
from services import core
from services.calc import exercise_spread_cents

bp = Blueprint("exercises", __name__)


@bp.post("/exercises")
@require_roles("Stakeholder", "Administrator")
def create_exercise():
    body = get_body()
    cap_table_id = require_string(body, "cap_table_id")
    core.get_cap_table(cap_table_id)
    option_grant_id = require_string(body, "option_grant_id")
    grant = core.get_option_grant(option_grant_id)
    if grant["cap_table_id"] != cap_table_id:
        raise APIError(ERR_NOT_FOUND, "OptionGrant not found.", 404)
    share_count = require_int(body, "share_count", strict_positive=True)

    # Stakeholder may only exercise its own grants (PRD §2.1)
    if g.user_role == "Stakeholder" and grant["shareholder_id"] != g.user_id:
        raise APIError(ERR_FORBIDDEN, "Stakeholder may only exercise its own grants.", 403)

    now = db.now_utc()
    vested = core.compute_vested_shares(grant, now)
    already = grant["exercised_shares"]
    if grant["early_exercise_allowed"]:
        exercisable = grant["share_count"] - already
    else:
        exercisable = vested - already
    if exercisable < 0:
        exercisable = 0
    if share_count > exercisable:
        raise APIError(ERR_EXCEEDS_EXERCISABLE, "Exercise exceeds exercisable shares.", 422)

    # is_early_exercise true when this exercise reaches beyond the vested portion
    is_early = grant["early_exercise_allowed"] and (already + share_count) > vested

    ex = {
        "cap_table_id": cap_table_id,
        "option_grant_id": option_grant_id,
        "share_count": share_count,
        "is_early_exercise": is_early,
        "spread_cents": 0,
        "filing_3921_id": None,
        "status": "PENDING",
    }
    stamp_common_fields(ex, now)
    db.exercises[ex["id"]] = ex
    return created(core.serialize(ex))


@bp.get("/exercises/<cid>")
@require_roles("Administrator", "BoardApprover", "Auditor", "Stakeholder")
def get_exercise(cid):
    ex = core.get_exercise(cid)
    return success(core.serialize(ex))


@bp.get("/exercises")
@require_roles("Administrator", "BoardApprover", "Auditor", "Stakeholder")
def list_exercises():
    limit, offset = pagination_params()
    items = list(db.exercises.values())
    for key in ("cap_table_id", "option_grant_id", "filing_3921_id"):
        val = request.args.get(key)
        if val is not None:
            items = [i for i in items if i.get(key) == val]
    if g.user_role == "Stakeholder":
        own = {gr["id"] for gr in db.option_grants.values() if gr["shareholder_id"] == g.user_id}
        items = [i for i in items if i["option_grant_id"] in own]
    page, total = paginate_and_sort(items, limit, offset)
    return list_response(
        [core.serialize(i) for i in page],
        limit=limit, offset=offset, total_count=total,
    )


@bp.post("/exercises/<cid>/settle")
@require_roles("Administrator")
def settle_exercise(cid):
    ex = core.get_exercise(cid)
    grant = core.get_option_grant(ex["option_grant_id"])
    if ex["status"] != "PENDING":
        raise APIError(ERR_INVALID_STATE, "Exercise must be PENDING to settle.", 409)
    if grant["status"] != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, "Grant must be ACTIVE to settle exercise.", 409)

    ct = core.get_cap_table(ex["cap_table_id"])
    val = core.get_valuation(grant["valuation_id"])
    sc = core.get_security_class(grant["security_class_id"])
    now = db.now_utc()

    ex["status"] = "SETTLED"
    ex["spread_cents"] = exercise_spread_cents(grant, val, ex["share_count"])
    touch(ex, now)

    # depth-3 cascade
    grant["exercised_shares"] += ex["share_count"]
    sc["shares_outstanding"] += ex["share_count"]
    touch(sc, now)

    # grant ACTIVE -> EXERCISED if fully exercised
    if grant["exercised_shares"] >= grant["share_count"]:
        grant["status"] = "EXERCISED"
    touch(grant, now)

    core.recompute_ledger(ct, now, bump=True)
    return success(core.serialize(ex))


@bp.post("/exercises/<cid>/reverse")
@require_roles("Administrator")
def reverse_exercise(cid):
    ex = core.get_exercise(cid)
    now = db.now_utc()

    if ex["status"] == "PENDING":
        ex["status"] = "REVERSED"
        touch(ex, now)
        return success(core.serialize(ex))

    if ex["status"] == "SETTLED":
        # blocked if an ACCEPTED 83(b) election references this exercise
        for el in db.section_83b_elections.values():
            if el["exercise_id"] == ex["id"] and el["status"] == "ACCEPTED":
                raise APIError(
                    ERR_ELECTION_BLOCKS_REVERSE,
                    "An ACCEPTED 83(b) election references this exercise.",
                    409,
                )
        grant = core.get_option_grant(ex["option_grant_id"])
        ct = core.get_cap_table(ex["cap_table_id"])
        sc = core.get_security_class(grant["security_class_id"])

        ex["status"] = "REVERSED"
        touch(ex, now)
        # compensation depth-3
        grant["exercised_shares"] -= ex["share_count"]
        sc["shares_outstanding"] -= ex["share_count"]
        touch(sc, now)
        if grant["status"] == "EXERCISED":
            grant["status"] = "ACTIVE"
        touch(grant, now)
        # void any linked Form 3921
        form_id = ex.get("filing_3921_id")
        if form_id is not None:
            db.forms_3921.pop(form_id, None)
            ex["filing_3921_id"] = None
        core.recompute_ledger(ct, now, bump=True)
        return success(core.serialize(ex))

    raise APIError(ERR_INVALID_STATE, "Exercise cannot be reversed from its current state.", 409)


@bp.post("/exercises/<cid>/form-3921")
@require_roles("Administrator")
def generate_form_3921(cid):
    ex = core.get_exercise(cid)
    grant = core.get_option_grant(ex["option_grant_id"])
    sh = core.get_shareholder(grant["shareholder_id"])
    val = core.get_valuation(grant["valuation_id"])

    if ex["status"] != "SETTLED":
        raise APIError(ERR_INVALID_STATE, "Exercise must be SETTLED to generate Form 3921.", 409)
    if not sh["is_us_taxpayer"]:
        raise APIError(ERR_VALIDATION, "Shareholder is not a U.S. taxpayer.", 400)

    now = db.now_utc()
    # tax_year = calendar year of the exercise's settlement (updated_at at settle ~ now)
    settle_dt = ex.get("updated_at") or now
    form = {
        "cap_table_id": ex["cap_table_id"],
        "exercise_id": ex["id"],
        "shareholder_id": grant["shareholder_id"],
        "tax_year": settle_dt.year,
        "exercise_fmv_cents": val["fmv_per_share_cents"],
        "strike_price_cents": grant["strike_price_cents"],
        "shares_transferred": ex["share_count"],
    }
    stamp_immutable(form, now)
    db.forms_3921[form["id"]] = form
    ex["filing_3921_id"] = form["id"]
    touch(ex, now)
    return created(core.serialize(form))
