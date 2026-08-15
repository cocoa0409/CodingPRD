"""Routes: breeding seasons, bulls, bull turnouts, preg checks, calf crops,
sale lots, grazing assignments, supplement programs.
"""
from __future__ import annotations

import math
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from core import (
    CLOCK, db, ApiError,
    success_envelope, paginate, require_ctx,
    get_body, check_allowed_fields, req_int, req_number,
    opt_number, req_str, req_enum, req_date,
    new_record, touch, dec, d1, d2,
    err_not_found, err_invalid_request, err_invalid_state, err_already_terminal,
)
from domain import (
    COWS_PER_BULL, MIN_BULL_TURNAROUND_DAYS, PRECON_MIN_WEAN_DAYS,
    VACCINE_MIN_SPACING_DAYS, DAM_ADJ, DAM_ADJ_11_PLUS, PRECON_RANK,
    DAYS_PER_AUM_MONTH,
    animal_unit_factor, refresh_pasture, refresh_lease, refresh_bull,
    refresh_crop, maybe_close_crop, compute_settlement,
    season_out, bull_out, turnout_out, preg_check_out, calf_crop_out,
    sale_lot_out, assignment_out, program_out,
)

bp = Blueprint("livestock_routes", __name__)

RM = ["RanchManager"]
RG = ["RangeManager"]
HM = ["HerdManager"]
SA = ["SalesAgent"]
ALL = ["RanchManager", "RangeManager", "HerdManager", "SalesAgent"]


# ===========================================================================
# Breeding seasons
# ===========================================================================
@bp.post("/api/breeding-seasons")
def create_season():
    require_ctx(HM)
    body = get_body()
    check_allowed_fields(body, {"ranch_id", "herd_group_id", "season_year",
                                "planned_turnout_date", "planned_removal_date",
                                "exposed_head_count"})
    ranch_id = req_str(body, "ranch_id")
    herd_group_id = req_str(body, "herd_group_id")
    ranch = db.ranches.get(ranch_id)
    if not ranch:
        raise err_not_found("ranch_id does not exist")
    group = db.herd_groups.get(herd_group_id)
    if not group or group["ranch_id"] != ranch_id:
        raise err_not_found("herd_group_id does not exist on this ranch")
    year = req_int(body, "season_year")
    t_date = req_date(body, "planned_turnout_date")
    r_date = req_date(body, "planned_removal_date")
    exposed = req_int(body, "exposed_head_count", positive=True)
    if t_date > r_date:
        raise err_invalid_request("planned_turnout_date must precede or equal planned_removal_date")
    if exposed > group["head_count"]:
        raise ApiError("ERR_EXPOSURE_EXCEEDS_GROUP",
                       "exposed_head_count exceeds herd group head_count", 422)
    s = new_record()
    s.update({
        "ranch_id": ranch_id, "herd_group_id": herd_group_id, "season_year": year,
        "planned_turnout_date": t_date, "planned_removal_date": r_date,
        "exposed_head_count": exposed,
        "required_bull_count": math.ceil(exposed / COWS_PER_BULL),
        "season_status": "PLANNED",
    })
    db.breeding_seasons[s["id"]] = s
    return success_envelope(season_out(s), status=201)


@bp.get("/api/breeding-seasons/<sid>")
def get_season(sid):
    require_ctx(ALL)
    s = db.breeding_seasons.get(sid)
    if not s:
        raise err_not_found()
    return success_envelope(season_out(s))


@bp.get("/api/breeding-seasons")
def list_seasons():
    require_ctx(ALL)
    args = request.args
    items = list(db.breeding_seasons.values())
    if args.get("ranch_id"):
        items = [s for s in items if s["ranch_id"] == args["ranch_id"]]
    if args.get("herd_group_id"):
        items = [s for s in items if s["herd_group_id"] == args["herd_group_id"]]
    if args.get("season_status"):
        items = [s for s in items if s["season_status"] == args["season_status"]]
    window, pg = paginate(items)
    return success_envelope([season_out(s) for s in window], response_type="array", pagination=pg)


@bp.post("/api/breeding-seasons/<sid>/begin-breeding")
def begin_breeding(sid):
    require_ctx(HM)
    s = db.breeding_seasons.get(sid)
    if not s:
        raise err_not_found()
    get_body(required=False)
    if s["season_status"] == "CLOSED":
        raise err_already_terminal("Season is CLOSED")
    if s["season_status"] != "PLANNED":
        raise err_invalid_state("Only a PLANNED season may begin breeding")
    qualified = 0
    for t in db.bull_turnouts.values():
        if t["breeding_season_id"] != sid or t["turnout_status"] != "TURNED_IN":
            continue
        bull = db.bulls.get(t["bull_id"])
        if not bull or bull["life_status"] != "ACTIVE":
            continue
        refresh_bull(bull)
        if bull["bse_status"] == "PASSED":
            qualified += 1
    if qualified < s["required_bull_count"]:
        raise ApiError("ERR_BULL_BATTERY_INSUFFICIENT",
                       "Qualified TURNED_IN bulls below required_bull_count", 422)
    s["season_status"] = "BREEDING"
    touch(s)
    return success_envelope(season_out(s))


@bp.post("/api/breeding-seasons/<sid>/end-breeding")
def end_breeding(sid):
    require_ctx(HM)
    s = db.breeding_seasons.get(sid)
    if not s:
        raise err_not_found()
    get_body(required=False)
    if s["season_status"] == "CLOSED":
        raise err_already_terminal("Season is CLOSED")
    if s["season_status"] != "BREEDING":
        raise err_invalid_state("Only a BREEDING season may end breeding")
    for t in db.bull_turnouts.values():
        if t["breeding_season_id"] == sid and t["turnout_status"] == "TURNED_IN":
            raise err_invalid_state("A turnout remains TURNED_IN for this season")
    s["season_status"] = "GESTATION"
    touch(s)
    return success_envelope(season_out(s))


# ===========================================================================
# Bulls
# ===========================================================================
@bp.post("/api/bulls")
def create_bull():
    require_ctx(HM)
    body = get_body()
    check_allowed_fields(body, {"ranch_id", "tag", "breed", "birth_year"})
    ranch_id = req_str(body, "ranch_id")
    ranch = db.ranches.get(ranch_id)
    if not ranch:
        raise err_not_found("ranch_id does not exist")
    tag = req_str(body, "tag")
    breed = req_str(body, "breed")
    birth_year = req_int(body, "birth_year")
    b = new_record()
    b.update({
        "ranch_id": ranch_id, "tag": tag, "breed": breed, "birth_year": birth_year,
        "last_bse_date": None, "last_bse_result": None, "scrotal_cm": None,
        "bse_status": "UNTESTED", "life_status": "ACTIVE",
    })
    db.bulls[b["id"]] = b
    return success_envelope(bull_out(b), status=201)


@bp.get("/api/bulls/<bid>")
def get_bull(bid):
    require_ctx(ALL)
    b = db.bulls.get(bid)
    if not b:
        raise err_not_found()
    return success_envelope(bull_out(b))


@bp.get("/api/bulls")
def list_bulls():
    require_ctx(ALL)
    args = request.args
    items = list(db.bulls.values())
    for b in items:
        refresh_bull(b)
    if args.get("ranch_id"):
        items = [b for b in items if b["ranch_id"] == args["ranch_id"]]
    if args.get("bse_status"):
        items = [b for b in items if b["bse_status"] == args["bse_status"]]
    if args.get("life_status"):
        items = [b for b in items if b["life_status"] == args["life_status"]]
    window, pg = paginate(items)
    return success_envelope([bull_out(b) for b in window], response_type="array", pagination=pg)


@bp.post("/api/bulls/<bid>/record-bse")
def record_bse(bid):
    require_ctx(HM)
    b = db.bulls.get(bid)
    if not b:
        raise err_not_found()
    body = get_body()
    check_allowed_fields(body, {"result", "exam_date", "scrotal_cm"})
    result = req_enum(body, "result", {"PASSED", "FAILED"})
    exam_date = req_date(body, "exam_date")
    scrotal = req_number(body, "scrotal_cm", positive=True)
    if b["life_status"] != "ACTIVE":
        raise err_already_terminal("Bull is no longer ACTIVE")
    b["last_bse_date"] = exam_date
    b["last_bse_result"] = result
    b["scrotal_cm"] = scrotal
    touch(b)
    refresh_bull(b)
    return success_envelope(bull_out(b))


@bp.post("/api/bulls/<bid>/retire")
def retire_bull(bid):
    require_ctx(HM)
    b = db.bulls.get(bid)
    if not b:
        raise err_not_found()
    body = get_body()
    check_allowed_fields(body, {"disposition"})
    disposition = req_enum(body, "disposition", {"SOLD", "CULLED", "DEAD"})
    if b["life_status"] != "ACTIVE":
        raise err_already_terminal("Bull is no longer ACTIVE")
    for t in db.bull_turnouts.values():
        if t["bull_id"] == bid and t["turnout_status"] in ("SCHEDULED", "TURNED_IN"):
            raise err_invalid_state("Bull has a turnout in SCHEDULED or TURNED_IN")
    b["life_status"] = disposition
    touch(b)
    return success_envelope(bull_out(b))


# ===========================================================================
# Bull turnouts
# ===========================================================================
@bp.post("/api/bull-turnouts")
def create_turnout():
    require_ctx(HM)
    body = get_body()
    check_allowed_fields(body, {"bull_id", "breeding_season_id", "ranch_id",
                                "turnout_date", "planned_removal_date"})
    bull_id = req_str(body, "bull_id")
    season_id = req_str(body, "breeding_season_id")
    ranch_id = req_str(body, "ranch_id")
    bull = db.bulls.get(bull_id)
    if not bull:
        raise err_not_found("bull_id does not exist")
    season = db.breeding_seasons.get(season_id)
    if not season:
        raise err_not_found("breeding_season_id does not exist")
    ranch = db.ranches.get(ranch_id)
    if not ranch or bull["ranch_id"] != ranch_id or season["ranch_id"] != ranch_id:
        raise err_not_found("ranch_id must match both the bull's and the season's ranch")
    t_date = req_date(body, "turnout_date")
    r_date = req_date(body, "planned_removal_date")
    if t_date > r_date:
        raise err_invalid_request("turnout_date must precede or equal planned_removal_date")
    if bull["life_status"] != "ACTIVE":
        raise err_already_terminal("Bull is no longer ACTIVE")
    # window nesting (priority 14) — scaffold order: overlap(13) before nesting(14),
    # PRD §3.4 lists nesting first; scaffold §1.4 priority wins per pinned numbers:
    # 13 (bull temporal) then 14 (nesting). Implement pinned priority order.
    # --- closed-interval overlap (priority 13a) ---
    for t in db.bull_turnouts.values():
        if t["bull_id"] != bull_id or t["turnout_status"] not in ("SCHEDULED", "TURNED_IN"):
            continue
        # inclusive intersection
        if t_date <= t["planned_removal_date"] and r_date >= t["turnout_date"]:
            raise ApiError("ERR_BULL_TURNOUT_OVERLAP",
                           "Turnout interval intersects another turnout of the same bull", 409)
    # --- turnaround gap (priority 13b) vs any non-CANCELLED turnout ---
    for t in db.bull_turnouts.values():
        if t["bull_id"] != bull_id or t["turnout_status"] == "CANCELLED":
            continue
        ex_end = t["actual_removal_date"] if t["turnout_status"] == "REMOVED" and t.get("actual_removal_date") else t["planned_removal_date"]
        ex_start = t["turnout_date"]
        gap_after = (t_date - ex_end).days   # new starts after existing ends
        gap_before = (ex_start - r_date).days  # new ends before existing starts
        if gap_after < MIN_BULL_TURNAROUND_DAYS and gap_before < MIN_BULL_TURNAROUND_DAYS:
            raise ApiError("ERR_BULL_TURNAROUND_TOO_SHORT",
                           "Less than 7 days between turnouts of the same bull", 409)
    # --- nesting in season window (priority 14) ---
    if t_date < season["planned_turnout_date"] or r_date > season["planned_removal_date"]:
        raise ApiError("ERR_TURNOUT_OUTSIDE_SEASON_WINDOW",
                       "Turnout window must lie within the season's planned window", 422)
    t = new_record()
    t.update({
        "bull_id": bull_id, "breeding_season_id": season_id, "ranch_id": ranch_id,
        "turnout_date": t_date, "planned_removal_date": r_date,
        "actual_removal_date": None, "turnout_status": "SCHEDULED",
    })
    db.bull_turnouts[t["id"]] = t
    return success_envelope(turnout_out(t), status=201)


@bp.get("/api/bull-turnouts/<tid>")
def get_turnout(tid):
    require_ctx(ALL)
    t = db.bull_turnouts.get(tid)
    if not t:
        raise err_not_found()
    return success_envelope(turnout_out(t))


@bp.get("/api/bull-turnouts")
def list_turnouts():
    require_ctx(ALL)
    args = request.args
    items = list(db.bull_turnouts.values())
    if args.get("bull_id"):
        items = [t for t in items if t["bull_id"] == args["bull_id"]]
    if args.get("breeding_season_id"):
        items = [t for t in items if t["breeding_season_id"] == args["breeding_season_id"]]
    if args.get("ranch_id"):
        items = [t for t in items if t["ranch_id"] == args["ranch_id"]]
    if args.get("turnout_status"):
        items = [t for t in items if t["turnout_status"] == args["turnout_status"]]
    window, pg = paginate(items)
    return success_envelope([turnout_out(t) for t in window], response_type="array", pagination=pg)


@bp.post("/api/bull-turnouts/<tid>/turn-in")
def turn_in(tid):
    require_ctx(HM)
    t = db.bull_turnouts.get(tid)
    if not t:
        raise err_not_found()
    get_body(required=False)
    if t["turnout_status"] in ("REMOVED", "CANCELLED"):
        raise err_already_terminal("Turnout is terminal")
    if t["turnout_status"] != "SCHEDULED":
        raise err_invalid_state("Only a SCHEDULED turnout may be turned in")
    season = db.breeding_seasons.get(t["breeding_season_id"])
    if season["season_status"] not in ("PLANNED", "BREEDING"):
        raise err_invalid_state("Season must be PLANNED or BREEDING to turn a bull in")
    t["turnout_status"] = "TURNED_IN"
    touch(t)
    return success_envelope(turnout_out(t))


@bp.post("/api/bull-turnouts/<tid>/remove")
def remove_turnout(tid):
    require_ctx(HM)
    t = db.bull_turnouts.get(tid)
    if not t:
        raise err_not_found()
    body = get_body()
    check_allowed_fields(body, {"removal_date"})
    removal_date = req_date(body, "removal_date")
    if t["turnout_status"] in ("REMOVED", "CANCELLED"):
        raise err_already_terminal("Turnout is terminal")
    if t["turnout_status"] != "TURNED_IN":
        raise err_invalid_state("Only a TURNED_IN turnout may be removed")
    t["turnout_status"] = "REMOVED"
    t["actual_removal_date"] = removal_date
    touch(t)
    return success_envelope(turnout_out(t))


@bp.post("/api/bull-turnouts/<tid>/cancel")
def cancel_turnout(tid):
    require_ctx(HM)
    t = db.bull_turnouts.get(tid)
    if not t:
        raise err_not_found()
    get_body(required=False)
    if t["turnout_status"] in ("REMOVED", "CANCELLED"):
        raise err_already_terminal("Turnout is terminal")
    if t["turnout_status"] != "SCHEDULED":
        raise err_invalid_state("Only a SCHEDULED turnout may be cancelled")
    t["turnout_status"] = "CANCELLED"
    touch(t)
    return success_envelope(turnout_out(t))


# ===========================================================================
# Preg checks
# ===========================================================================
@bp.post("/api/preg-checks")
def create_preg_check():
    require_ctx(HM)
    body = get_body()
    check_allowed_fields(body, {"breeding_season_id", "ranch_id", "check_date"})
    season_id = req_str(body, "breeding_season_id")
    ranch_id = req_str(body, "ranch_id")
    season = db.breeding_seasons.get(season_id)
    if not season:
        raise err_not_found("breeding_season_id does not exist")
    ranch = db.ranches.get(ranch_id)
    if not ranch or season["ranch_id"] != ranch_id:
        raise err_not_found("ranch_id does not exist or does not match the season")
    check_date = req_date(body, "check_date")
    if season["season_status"] != "GESTATION":
        raise ApiError("ERR_SEASON_NOT_IN_GESTATION",
                       "Preg check requires the season to be in GESTATION", 400)
    for pc in db.preg_checks.values():
        if pc["breeding_season_id"] == season_id:
            raise ApiError("ERR_PREG_CHECK_ALREADY_EXISTS",
                           "Season already has a pregnancy check", 409)
    pc = new_record()
    pc.update({
        "breeding_season_id": season_id, "ranch_id": ranch_id, "check_date": check_date,
        "exposed_head_count": season["exposed_head_count"],
        "pregnant_count": None, "open_count": None, "dead_count": None,
        "pregnancy_rate_pct": None, "check_status": "DRAFT",
    })
    db.preg_checks[pc["id"]] = pc
    season["season_status"] = "PREG_CHECK"
    touch(season)
    return success_envelope(preg_check_out(pc), status=201)


@bp.get("/api/preg-checks/<pid>")
def get_preg_check(pid):
    require_ctx(ALL)
    pc = db.preg_checks.get(pid)
    if not pc:
        raise err_not_found()
    return success_envelope(preg_check_out(pc))


@bp.get("/api/preg-checks")
def list_preg_checks():
    require_ctx(ALL)
    args = request.args
    items = list(db.preg_checks.values())
    if args.get("breeding_season_id"):
        items = [p for p in items if p["breeding_season_id"] == args["breeding_season_id"]]
    if args.get("ranch_id"):
        items = [p for p in items if p["ranch_id"] == args["ranch_id"]]
    window, pg = paginate(items)
    return success_envelope([preg_check_out(p) for p in window], response_type="array", pagination=pg)


@bp.post("/api/preg-checks/<pid>/finalize")
def finalize_preg_check(pid):
    require_ctx(HM)
    pc = db.preg_checks.get(pid)
    if not pc:
        raise err_not_found()
    body = get_body()
    check_allowed_fields(body, {"pregnant_count", "open_count", "dead_count"})
    pregnant = req_int(body, "pregnant_count", nonneg=True)
    open_c = req_int(body, "open_count", nonneg=True)
    dead = req_int(body, "dead_count", nonneg=True)
    if pc["check_status"] == "FINALIZED":
        raise err_already_terminal("Preg check is FINALIZED")
    if pregnant + open_c + dead != pc["exposed_head_count"]:
        raise ApiError("ERR_PREG_COUNT_MISMATCH",
                       "pregnant + open + dead must equal exposed_head_count", 422)
    pc["pregnant_count"] = pregnant
    pc["open_count"] = open_c
    pc["dead_count"] = dead
    pc["pregnancy_rate_pct"] = d1(Decimal(100) * Decimal(pregnant) / Decimal(pc["exposed_head_count"]))
    pc["check_status"] = "FINALIZED"
    touch(pc)
    season = db.breeding_seasons.get(pc["breeding_season_id"])
    group = db.herd_groups.get(season["herd_group_id"])
    if group is not None:
        group["marked_open_head"] += open_c
        touch(group)
    if season["season_status"] == "PREG_CHECK":
        season["season_status"] = "CLOSED"
        touch(season)
    return success_envelope(preg_check_out(pc))


# ===========================================================================
# Calf crops
# ===========================================================================
@bp.post("/api/calf-crops")
def create_calf_crop():
    require_ctx(HM)
    body = get_body()
    check_allowed_fields(body, {"breeding_season_id", "ranch_id", "crop_year",
                                "steer_head", "heifer_head"})
    season_id = req_str(body, "breeding_season_id")
    ranch_id = req_str(body, "ranch_id")
    season = db.breeding_seasons.get(season_id)
    if not season:
        raise err_not_found("breeding_season_id does not exist")
    ranch = db.ranches.get(ranch_id)
    if not ranch or season["ranch_id"] != ranch_id:
        raise err_not_found("ranch_id does not exist or does not match the season")
    year = req_int(body, "crop_year")
    steers = req_int(body, "steer_head", nonneg=True)
    heifers = req_int(body, "heifer_head", nonneg=True)
    if season["season_status"] not in ("GESTATION", "PREG_CHECK", "CLOSED"):
        raise ApiError("ERR_SEASON_NOT_IN_GESTATION",
                       "Crop creation requires the season to be GESTATION, PREG_CHECK or CLOSED", 400)
    c = new_record()
    c.update({
        "breeding_season_id": season_id, "ranch_id": ranch_id, "crop_year": year,
        "steer_head": steers, "heifer_head": heifers,
        "weaning_date": None, "avg_wean_weight_lbs": None, "avg_wean_age_days": None,
        "avg_birth_weight_lbs": None, "avg_dam_age_years": None,
        "adj205_age_only_lbs": None, "adj205_dam_adjusted_lbs": None,
        "vaccine_round_1_date": None, "vaccine_round_2_date": None,
        "retained_heifer_head": 0, "death_loss_steer_head": 0, "death_loss_heifer_head": 0,
        "marketed_steer_head": 0, "marketed_heifer_head": 0,
        "reserved_steer_head": 0, "reserved_heifer_head": 0,
        "available_steer_head": steers, "available_heifer_head": heifers,
        "wean_status": "UNWEANED", "precon_status": "NONE", "lifecycle_status": "ACTIVE",
    })
    db.calf_crops[c["id"]] = c
    return success_envelope(calf_crop_out(c), status=201)


@bp.get("/api/calf-crops/<cid>")
def get_calf_crop(cid):
    require_ctx(ALL)
    c = db.calf_crops.get(cid)
    if not c:
        raise err_not_found()
    return success_envelope(calf_crop_out(c))


@bp.get("/api/calf-crops")
def list_calf_crops():
    require_ctx(ALL)
    args = request.args
    items = list(db.calf_crops.values())
    if args.get("ranch_id"):
        items = [c for c in items if c["ranch_id"] == args["ranch_id"]]
    if args.get("breeding_season_id"):
        items = [c for c in items if c["breeding_season_id"] == args["breeding_season_id"]]
    if args.get("precon_status"):
        items = [c for c in items if c["precon_status"] == args["precon_status"]]
    if args.get("lifecycle_status"):
        items = [c for c in items if c["lifecycle_status"] == args["lifecycle_status"]]
    window, pg = paginate(items)
    return success_envelope([calf_crop_out(c) for c in window], response_type="array", pagination=pg)


def _get_crop_or_404(cid):
    c = db.calf_crops.get(cid)
    if not c:
        raise err_not_found()
    return c


@bp.post("/api/calf-crops/<cid>/record-weaning")
def record_weaning(cid):
    require_ctx(HM)
    c = _get_crop_or_404(cid)
    body = get_body()
    check_allowed_fields(body, {"weaning_date", "avg_wean_weight_lbs", "avg_wean_age_days",
                                "avg_birth_weight_lbs", "avg_dam_age_years"})
    weaning_date = req_date(body, "weaning_date")
    wean_wt = req_number(body, "avg_wean_weight_lbs", positive=True)
    wean_age = req_int(body, "avg_wean_age_days", positive=True)
    birth_wt = req_number(body, "avg_birth_weight_lbs", positive=True)
    dam_age = req_int(body, "avg_dam_age_years", positive=True)
    if weaning_date > CLOCK.current_date():
        raise err_invalid_request("weaning_date may not lie in the future")
    if c["wean_status"] == "WEANED":
        raise err_invalid_state("Crop is already WEANED")
    c["weaning_date"] = weaning_date
    c["avg_wean_weight_lbs"] = wean_wt
    c["avg_wean_age_days"] = wean_age
    c["avg_birth_weight_lbs"] = birth_wt
    c["avg_dam_age_years"] = dam_age
    age_only = d1((dec(wean_wt) - dec(birth_wt)) / Decimal(wean_age) * Decimal(205) + dec(birth_wt))
    if dam_age == 2:
        adj = DAM_ADJ[2]
    elif dam_age == 3:
        adj = DAM_ADJ[3]
    elif dam_age >= 11:
        adj = DAM_ADJ_11_PLUS
    else:
        adj = Decimal("0")
    c["adj205_age_only_lbs"] = age_only
    c["adj205_dam_adjusted_lbs"] = d1(age_only + adj)
    c["wean_status"] = "WEANED"
    touch(c)
    return success_envelope(calf_crop_out(c))


@bp.post("/api/calf-crops/<cid>/enroll-preconditioning")
def enroll_precon(cid):
    require_ctx(HM)
    c = _get_crop_or_404(cid)
    get_body(required=False)
    if c["lifecycle_status"] == "CLOSED":
        raise err_already_terminal("Crop lifecycle is CLOSED")
    if c["precon_status"] != "NONE":
        raise err_invalid_state("Crop is already enrolled or certified")
    c["precon_status"] = "ENROLLED"
    touch(c)
    return success_envelope(calf_crop_out(c))


@bp.post("/api/calf-crops/<cid>/record-vaccine")
def record_vaccine(cid):
    require_ctx(HM)
    c = _get_crop_or_404(cid)
    body = get_body()
    check_allowed_fields(body, {"round_number", "vaccine_date"})
    round_number = req_int(body, "round_number")
    if round_number not in (1, 2):
        raise err_invalid_request("round_number must be 1 or 2")
    vdate = req_date(body, "vaccine_date")
    if c["lifecycle_status"] == "CLOSED":
        raise err_already_terminal("Crop lifecycle is CLOSED")
    if round_number == 1:
        if c.get("vaccine_round_1_date") is not None:
            raise err_invalid_state("Vaccine round 1 already recorded")
        c["vaccine_round_1_date"] = vdate
    else:
        if c.get("vaccine_round_2_date") is not None:
            raise err_invalid_state("Vaccine round 2 already recorded")
        r1 = c.get("vaccine_round_1_date")
        if r1 is None or vdate < r1 + timedelta(days=VACCINE_MIN_SPACING_DAYS):
            raise ApiError("ERR_VACCINE_SPACING_VIOLATION",
                           "Round 2 requires round 1 on record and at least 14 days of spacing", 422)
        c["vaccine_round_2_date"] = vdate
    touch(c)
    return success_envelope(calf_crop_out(c))


@bp.post("/api/calf-crops/<cid>/certify-preconditioning")
def certify_precon(cid):
    require_ctx(HM)
    c = _get_crop_or_404(cid)
    get_body(required=False)
    if c["lifecycle_status"] == "CLOSED":
        raise err_already_terminal("Crop lifecycle is CLOSED")
    if c["precon_status"] != "ENROLLED":
        if c["precon_status"] == "CERTIFIED":
            raise err_invalid_state("Crop is already CERTIFIED")
        raise ApiError("ERR_PRECON_NOT_ENROLLED",
                       "Certification requires precon_status ENROLLED", 400)
    if c["wean_status"] != "WEANED":
        raise ApiError("ERR_CROP_NOT_WEANED", "Certification requires the crop to be WEANED", 400)
    if c.get("vaccine_round_1_date") is None or c.get("vaccine_round_2_date") is None:
        raise ApiError("ERR_PRECON_VACCINE_INCOMPLETE",
                       "Both vaccine rounds must be recorded before certification", 422)
    if (CLOCK.current_date() - c["weaning_date"]).days < PRECON_MIN_WEAN_DAYS:
        raise ApiError("ERR_PRECON_DAYS_INSUFFICIENT",
                       "Fewer than 45 days have elapsed since weaning", 422)
    c["precon_status"] = "CERTIFIED"
    touch(c)
    return success_envelope(calf_crop_out(c))


@bp.post("/api/calf-crops/<cid>/retain-heifers")
def retain_heifers(cid):
    require_ctx(HM)
    c = _get_crop_or_404(cid)
    body = get_body()
    check_allowed_fields(body, {"head_count", "target_herd_group_id"})
    head = req_int(body, "head_count", positive=True)
    target_id = req_str(body, "target_herd_group_id")
    target = db.herd_groups.get(target_id)
    if not target:
        raise err_not_found("target_herd_group_id does not exist")
    if c["lifecycle_status"] == "CLOSED":
        raise err_already_terminal("Crop lifecycle is CLOSED")
    if (target["ranch_id"] != c["ranch_id"]
            or target["animal_class"] != "REPLACEMENT_HEIFER"
            or target["group_status"] == "LIQUIDATED"):
        raise ApiError("ERR_RETENTION_CLASS_MISMATCH",
                       "Retention target must be a non-LIQUIDATED REPLACEMENT_HEIFER group on the same ranch", 422)
    refresh_crop(c)
    if head > c["available_heifer_head"]:
        raise ApiError("ERR_RETENTION_EXCEEDS_AVAILABLE",
                       "retain head exceeds available_heifer_head", 422)
    c["retained_heifer_head"] += head
    target["head_count"] += head
    if target.get("retained_from_crop_id") is None:
        target["retained_from_crop_id"] = c["id"]
    touch(target)
    touch(c)
    maybe_close_crop(c)
    return success_envelope(calf_crop_out(c))


@bp.post("/api/calf-crops/<cid>/unretain-heifers")
def unretain_heifers(cid):
    require_ctx(HM)
    c = _get_crop_or_404(cid)
    body = get_body()
    check_allowed_fields(body, {"head_count", "source_herd_group_id"})
    head = req_int(body, "head_count", positive=True)
    source_id = req_str(body, "source_herd_group_id")
    source = db.herd_groups.get(source_id)
    if not source:
        raise err_not_found("source_herd_group_id does not exist")
    if source.get("retained_from_crop_id") != c["id"]:
        raise ApiError("ERR_RETENTION_CLASS_MISMATCH",
                       "Source group was not retained from this crop", 422)
    if head > c["retained_heifer_head"]:
        raise ApiError("ERR_RETENTION_EXCEEDS_AVAILABLE",
                       "unretain head exceeds retained_heifer_head", 422)
    c["retained_heifer_head"] -= head
    source["head_count"] -= head
    touch(source)
    touch(c)
    maybe_close_crop(c)
    return success_envelope(calf_crop_out(c))


@bp.post("/api/calf-crops/<cid>/record-death-loss")
def record_death_loss(cid):
    require_ctx(HM)
    c = _get_crop_or_404(cid)
    body = get_body()
    check_allowed_fields(body, {"calf_class", "head_count", "loss_date"})
    cls = req_enum(body, "calf_class", {"STEER", "HEIFER"})
    head = req_int(body, "head_count", positive=True)
    req_date(body, "loss_date")
    if c["lifecycle_status"] == "CLOSED":
        raise err_already_terminal("Crop lifecycle is CLOSED")
    refresh_crop(c)
    avail = c["available_steer_head"] if cls == "STEER" else c["available_heifer_head"]
    if head > avail:
        raise ApiError("ERR_INSUFFICIENT_CROP_HEAD",
                       "Death loss exceeds available head of that class", 422)
    if cls == "STEER":
        c["death_loss_steer_head"] += head
    else:
        c["death_loss_heifer_head"] += head
    touch(c)
    maybe_close_crop(c)
    return success_envelope(calf_crop_out(c))


# ===========================================================================
# Sale lots
# ===========================================================================
@bp.post("/api/sale-lots")
def create_sale_lot():
    ctx = require_ctx(SA)
    body = get_body()
    check_allowed_fields(body, {"calf_crop_id", "ranch_id", "lot_class", "head_count",
                                "base_price_cents_per_cwt", "slide_cents_per_lb",
                                "base_weight_lbs", "shrink_pct", "precon_claim",
                                "freight_cents_per_head", "commission_pct"})
    crop_id = req_str(body, "calf_crop_id")
    ranch_id = req_str(body, "ranch_id")
    crop = db.calf_crops.get(crop_id)
    if not crop:
        raise err_not_found("calf_crop_id does not exist")
    ranch = db.ranches.get(ranch_id)
    if not ranch or crop["ranch_id"] != ranch_id:
        raise err_not_found("ranch_id does not exist or does not match the crop")
    cls = req_enum(body, "lot_class", {"STEER", "HEIFER"})
    head = req_int(body, "head_count", positive=True)
    base_price = req_number(body, "base_price_cents_per_cwt", positive=True)
    slide = req_number(body, "slide_cents_per_lb")
    base_weight = req_number(body, "base_weight_lbs", positive=True)
    shrink = req_number(body, "shrink_pct", nonneg=True)
    claim = req_enum(body, "precon_claim", {"NONE", "ENROLLED", "CERTIFIED"})
    freight = req_int(body, "freight_cents_per_head", nonneg=True)
    commission = req_number(body, "commission_pct", nonneg=True)
    # state gates (priorities 7-8): closed crop -> ALREADY_TERMINAL; unweaned -> CROP_NOT_WEANED
    if crop["lifecycle_status"] == "CLOSED":
        raise err_already_terminal("Calf crop lifecycle is CLOSED")
    if crop["wean_status"] != "WEANED":
        raise ApiError("ERR_CROP_NOT_WEANED", "Sale-lot creation requires a WEANED crop", 400)
    # marketing gates (priority 20)
    refresh_crop(crop)
    avail = crop["available_steer_head"] if cls == "STEER" else crop["available_heifer_head"]
    if head > avail:
        raise ApiError("ERR_INSUFFICIENT_CROP_HEAD",
                       "head_count exceeds available head of lot_class", 422)
    if PRECON_RANK[claim] > PRECON_RANK[crop["precon_status"]]:
        raise ApiError("ERR_PRECON_CLAIM_EXCEEDS_CROP",
                       "precon_claim ranks above the crop's precon_status", 422)
    l = new_record()
    l.update({
        "calf_crop_id": crop_id, "ranch_id": ranch_id, "lot_class": cls,
        "head_count": head, "base_price_cents_per_cwt": base_price,
        "slide_cents_per_lb": slide, "base_weight_lbs": base_weight,
        "shrink_pct": shrink, "precon_claim": claim,
        "freight_cents_per_head": freight, "commission_pct": commission,
        "buyer_name": None, "delivered_avg_weight_lbs": None,
        "pay_weight_lbs": None, "final_price_cents_per_cwt": None,
        "per_head_gross_cents": None, "gross_cents": None,
        "commission_cents": None, "freight_cents": None, "net_settlement_cents": None,
        "relist_count": 0, "sold_by_user_id": ctx.user_id, "settled_by_user_id": None,
        "lot_status": "DRAFT",
    })
    db.sale_lots[l["id"]] = l
    return success_envelope(sale_lot_out(l), status=201)


@bp.get("/api/sale-lots/<lid>")
def get_sale_lot(lid):
    require_ctx(ALL)
    l = db.sale_lots.get(lid)
    if not l:
        raise err_not_found()
    return success_envelope(sale_lot_out(l))


@bp.get("/api/sale-lots")
def list_sale_lots():
    require_ctx(ALL)
    args = request.args
    items = list(db.sale_lots.values())
    if args.get("calf_crop_id"):
        items = [l for l in items if l["calf_crop_id"] == args["calf_crop_id"]]
    if args.get("ranch_id"):
        items = [l for l in items if l["ranch_id"] == args["ranch_id"]]
    if args.get("lot_status"):
        items = [l for l in items if l["lot_status"] == args["lot_status"]]
    if args.get("lot_class"):
        items = [l for l in items if l["lot_class"] == args["lot_class"]]
    window, pg = paginate(items)
    return success_envelope([sale_lot_out(l) for l in window], response_type="array", pagination=pg)


def _get_lot_or_404(lid):
    l = db.sale_lots.get(lid)
    if not l:
        raise err_not_found()
    return l


@bp.post("/api/sale-lots/<lid>/offer")
def offer_lot(lid):
    require_ctx(SA)
    l = _get_lot_or_404(lid)
    get_body(required=False)
    if l["lot_status"] in ("SETTLED", "CANCELLED"):
        raise err_already_terminal("Lot is terminal")
    if l["lot_status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT lot may be offered")
    crop = db.calf_crops.get(l["calf_crop_id"])
    if crop["lifecycle_status"] != "ACTIVE":
        raise err_already_terminal("Calf crop lifecycle is CLOSED")
    refresh_crop(crop)
    avail = crop["available_steer_head"] if l["lot_class"] == "STEER" else crop["available_heifer_head"]
    if l["head_count"] > avail:
        raise ApiError("ERR_INSUFFICIENT_CROP_HEAD",
                       "Available head no longer covers the lot", 422)
    l["lot_status"] = "OFFERED"
    touch(l)
    touch(crop, bump_version=False)
    return success_envelope(sale_lot_out(l))


@bp.post("/api/sale-lots/<lid>/contract")
def contract_lot(lid):
    require_ctx(SA)
    l = _get_lot_or_404(lid)
    body = get_body()
    check_allowed_fields(body, {"buyer_name"})
    buyer = req_str(body, "buyer_name")
    if l["lot_status"] in ("SETTLED", "CANCELLED"):
        raise err_already_terminal("Lot is terminal")
    if l["lot_status"] != "OFFERED":
        raise err_invalid_state("Only an OFFERED lot may be contracted")
    l["lot_status"] = "CONTRACTED"
    l["buyer_name"] = buyer
    touch(l)
    return success_envelope(sale_lot_out(l))


@bp.post("/api/sale-lots/<lid>/relist")
def relist_lot(lid):
    require_ctx(SA)
    l = _get_lot_or_404(lid)
    get_body(required=False)
    if l["lot_status"] in ("SETTLED", "CANCELLED"):
        raise err_already_terminal("Lot is terminal")
    if l["lot_status"] != "CONTRACTED":
        raise err_invalid_state("Only a CONTRACTED lot may be relisted")
    l["lot_status"] = "OFFERED"
    l["relist_count"] += 1
    l["buyer_name"] = None
    touch(l)
    return success_envelope(sale_lot_out(l))


@bp.post("/api/sale-lots/<lid>/deliver")
def deliver_lot(lid):
    require_ctx(SA)
    l = _get_lot_or_404(lid)
    body = get_body()
    check_allowed_fields(body, {"delivered_avg_weight_lbs"})
    weight = req_number(body, "delivered_avg_weight_lbs", positive=True)
    if l["lot_status"] in ("SETTLED", "CANCELLED"):
        raise err_already_terminal("Lot is terminal")
    if l["lot_status"] != "CONTRACTED":
        raise err_invalid_state("Only a CONTRACTED lot may be delivered")
    l["delivered_avg_weight_lbs"] = weight
    l["lot_status"] = "DELIVERED"
    compute_settlement(l)
    touch(l)
    return success_envelope(sale_lot_out(l))


@bp.post("/api/sale-lots/<lid>/dispute")
def dispute_lot(lid):
    require_ctx(SA)
    l = _get_lot_or_404(lid)
    body = get_body()
    check_allowed_fields(body, {"reason"})
    req_str(body, "reason")
    if l["lot_status"] in ("SETTLED", "CANCELLED"):
        raise err_already_terminal("Lot is terminal")
    if l["lot_status"] != "DELIVERED":
        raise err_invalid_state("Only a DELIVERED lot may be disputed")
    l["lot_status"] = "DISPUTED"
    touch(l)
    return success_envelope(sale_lot_out(l))


@bp.post("/api/sale-lots/<lid>/resolve-dispute")
def resolve_dispute(lid):
    require_ctx(SA)
    l = _get_lot_or_404(lid)
    body = get_body()
    check_allowed_fields(body, {"adjusted_delivered_weight_lbs"})
    adjusted = opt_number(body, "adjusted_delivered_weight_lbs")
    if l["lot_status"] in ("SETTLED", "CANCELLED"):
        raise err_already_terminal("Lot is terminal")
    if l["lot_status"] != "DISPUTED":
        raise err_invalid_state("Only a DISPUTED lot may be resolved")
    if adjusted is not None:
        if adjusted <= 0:
            raise err_invalid_request("adjusted_delivered_weight_lbs must be positive")
        l["delivered_avg_weight_lbs"] = adjusted
        compute_settlement(l)
    l["lot_status"] = "DELIVERED"
    touch(l)
    return success_envelope(sale_lot_out(l))


@bp.post("/api/sale-lots/<lid>/settle")
def settle_lot(lid):
    ctx = require_ctx(RM)
    l = _get_lot_or_404(lid)
    get_body(required=False)
    # segregation of duties (priority 3)
    if ctx.user_id == l["sold_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "Settler must differ from sold_by_user_id", 403)
    if l["lot_status"] in ("SETTLED", "CANCELLED"):
        raise err_already_terminal("Lot is terminal")
    if l["lot_status"] != "DELIVERED":
        raise err_invalid_state("Only a DELIVERED lot may be settled")
    l["lot_status"] = "SETTLED"
    l["settled_by_user_id"] = ctx.user_id
    touch(l)
    crop = db.calf_crops.get(l["calf_crop_id"])
    if l["lot_class"] == "STEER":
        crop["marketed_steer_head"] += l["head_count"]
    else:
        crop["marketed_heifer_head"] += l["head_count"]
    touch(crop)
    maybe_close_crop(crop)
    return success_envelope(sale_lot_out(l))


@bp.post("/api/sale-lots/<lid>/cancel")
def cancel_lot(lid):
    require_ctx(SA)
    l = _get_lot_or_404(lid)
    get_body(required=False)
    if l["lot_status"] in ("SETTLED", "CANCELLED"):
        raise err_already_terminal("Lot is terminal")
    if l["lot_status"] not in ("DRAFT", "OFFERED"):
        raise err_invalid_state("Only a DRAFT or OFFERED lot may be cancelled")
    was_offered = l["lot_status"] == "OFFERED"
    l["lot_status"] = "CANCELLED"
    touch(l)
    if was_offered:
        crop = db.calf_crops.get(l["calf_crop_id"])
        touch(crop, bump_version=False)
        maybe_close_crop(crop)
    return success_envelope(sale_lot_out(l))


# ===========================================================================
# Grazing assignments
# ===========================================================================
@bp.post("/api/grazing-assignments")
def create_assignment():
    require_ctx(RG)
    body = get_body()
    check_allowed_fields(body, {"pasture_id", "herd_group_id", "ranch_id",
                                "start_date", "planned_end_date"})
    pasture_id = req_str(body, "pasture_id")
    herd_group_id = req_str(body, "herd_group_id")
    ranch_id = req_str(body, "ranch_id")
    pasture = db.pastures.get(pasture_id)
    if not pasture:
        raise err_not_found("pasture_id does not exist")
    group = db.herd_groups.get(herd_group_id)
    if not group:
        raise err_not_found("herd_group_id does not exist")
    ranch = db.ranches.get(ranch_id)
    if not ranch or pasture["ranch_id"] != ranch_id or group["ranch_id"] != ranch_id:
        raise err_not_found("ranch_id must match both the pasture's and the herd group's ranch")
    start = req_date(body, "start_date")
    planned_end = req_date(body, "planned_end_date")
    if start >= planned_end:
        raise err_invalid_request("start_date must precede planned_end_date (half-open window)")
    # priority 8: pasture not CLOSED
    refresh_pasture(pasture)
    if pasture["condition_status"] == "CLOSED":
        raise ApiError("ERR_PASTURE_NOT_GRAZEABLE", "Pasture is CLOSED", 400)
    # priority 8: LEASED pasture requires a covering ACTIVE lease
    covering_lease = None
    if pasture["tenure"] == "LEASED":
        for l in db.grazing_leases.values():
            if l["pasture_id"] != pasture_id or l["ranch_id"] != ranch_id:
                continue
            refresh_lease(l)
            if l["lease_status"] == "ACTIVE":
                covering_lease = l
                break
        if covering_lease is None:
            raise ApiError("ERR_LEASE_NOT_ACTIVE",
                           "Leased pasture has no ACTIVE covering lease", 400)
    # priority 10a: blocking destock order
    for o in db.destock_orders.values():
        if o["ranch_id"] == ranch_id and o["order_status"] in ("OPEN", "EXPIRED"):
            raise ApiError("ERR_DESTOCK_ORDER_BLOCKING",
                           "An OPEN or EXPIRED destock order blocks new grazing commitments", 422)
    # priority 10b: posture gate
    if ranch["drought_posture"] in ("ALERT", "CRITICAL"):
        raise ApiError("ERR_DROUGHT_POSTURE_BLOCKS_COMMITMENT",
                       "Ranch drought posture blocks new grazing commitments", 422)
    # priority 12a: half-open overlap vs ACTIVE assignments on this pasture
    for a in db.grazing_assignments.values():
        if a["pasture_id"] != pasture_id or a["assignment_status"] != "ACTIVE":
            continue
        if start < a["planned_end_date"] and planned_end > a["start_date"]:
            raise ApiError("ERR_PASTURE_WINDOW_OVERLAP",
                           "Grazing window intersects an ACTIVE assignment on the pasture", 409)
    # priority 12b: rest buffer vs ALL non-CANCELLED assignments, both directions
    for a in db.grazing_assignments.values():
        if a["pasture_id"] != pasture_id or a["assignment_status"] == "CANCELLED":
            continue
        if a["assignment_status"] in ("COMPLETED", "SHORTENED"):
            ex_end = a["actual_end_date"]
        else:
            ex_end = a["planned_end_date"]
        ex_start = a["start_date"]
        gap_after = (start - ex_end).days
        gap_before = (ex_start - planned_end).days
        if gap_after < pasture["min_rest_days"] and gap_before < pasture["min_rest_days"]:
            raise ApiError("ERR_PASTURE_REST_VIOLATION",
                           "Gap between grazing windows is below the pasture's min_rest_days", 409)
    # priority 14: nesting inside covering lease window
    if covering_lease is not None:
        if start < covering_lease["start_date"] or planned_end > covering_lease["end_date"]:
            raise ApiError("ERR_ASSIGNMENT_OUTSIDE_LEASE_WINDOW",
                           "Assignment window must lie within the covering lease window", 422)
    # compute snapshots + budget (priority 19)
    grazing_days = (planned_end - start).days
    au = animal_unit_factor(group["animal_class"], group["avg_weight_lbs"])
    daily_demand = dec(group["head_count"]) * au / DAYS_PER_AUM_MONTH  # unrounded
    reserved = d2(daily_demand * Decimal(grazing_days))
    if reserved > dec(pasture["available_aum"]):
        raise ApiError("ERR_AUM_BUDGET_EXCEEDED",
                       "reserved_aum exceeds pasture available_aum", 422)
    a = new_record()
    a.update({
        "pasture_id": pasture_id, "herd_group_id": herd_group_id, "ranch_id": ranch_id,
        "start_date": start, "planned_end_date": planned_end,
        "grazing_days": grazing_days, "au_factor": au,
        "daily_demand_aum": daily_demand, "reserved_aum": reserved,
        "consumed_aum": None, "actual_end_date": None,
        "assignment_status": "ACTIVE",
    })
    db.grazing_assignments[a["id"]] = a
    refresh_pasture(pasture)
    touch(pasture, bump_version=False)
    return success_envelope(assignment_out(a), status=201)


@bp.get("/api/grazing-assignments/<aid>")
def get_assignment(aid):
    require_ctx(ALL)
    a = db.grazing_assignments.get(aid)
    if not a:
        raise err_not_found()
    return success_envelope(assignment_out(a))


@bp.get("/api/grazing-assignments")
def list_assignments():
    require_ctx(ALL)
    args = request.args
    items = list(db.grazing_assignments.values())
    if args.get("pasture_id"):
        items = [a for a in items if a["pasture_id"] == args["pasture_id"]]
    if args.get("herd_group_id"):
        items = [a for a in items if a["herd_group_id"] == args["herd_group_id"]]
    if args.get("ranch_id"):
        items = [a for a in items if a["ranch_id"] == args["ranch_id"]]
    if args.get("assignment_status"):
        items = [a for a in items if a["assignment_status"] == args["assignment_status"]]
    window, pg = paginate(items)
    return success_envelope([assignment_out(a) for a in window], response_type="array", pagination=pg)


@bp.post("/api/grazing-assignments/<aid>/complete")
def complete_assignment(aid):
    require_ctx(RG)
    a = db.grazing_assignments.get(aid)
    if not a:
        raise err_not_found()
    body = get_body()
    check_allowed_fields(body, {"actual_end_date"})
    actual_end = req_date(body, "actual_end_date")
    if a["assignment_status"] in ("COMPLETED", "SHORTENED", "CANCELLED"):
        raise err_already_terminal("Assignment is terminal")
    if actual_end < a["start_date"]:
        raise err_invalid_request("actual_end_date may not precede start_date")
    if actual_end > CLOCK.current_date():
        raise err_invalid_request("actual_end_date may not lie in the future")
    if actual_end > a["planned_end_date"]:
        raise err_invalid_request("actual_end_date may not exceed planned_end_date")
    actual_days = (actual_end - a["start_date"]).days
    a["consumed_aum"] = d2(dec(a["daily_demand_aum"]) * Decimal(actual_days))
    a["actual_end_date"] = actual_end
    a["assignment_status"] = "COMPLETED" if actual_end == a["planned_end_date"] else "SHORTENED"
    touch(a)
    pasture = db.pastures.get(a["pasture_id"])
    pasture["resting_until"] = actual_end + timedelta(days=pasture["min_rest_days"])
    refresh_pasture(pasture)
    touch(pasture)
    return success_envelope(assignment_out(a))


@bp.post("/api/grazing-assignments/<aid>/cancel")
def cancel_assignment(aid):
    require_ctx(RG)
    a = db.grazing_assignments.get(aid)
    if not a:
        raise err_not_found()
    get_body(required=False)
    if a["assignment_status"] in ("COMPLETED", "SHORTENED", "CANCELLED"):
        raise err_already_terminal("Assignment is terminal")
    if not (CLOCK.current_date() < a["start_date"]):
        raise err_invalid_state("Only an assignment that has not begun may be cancelled")
    a["assignment_status"] = "CANCELLED"
    a["consumed_aum"] = Decimal("0")
    touch(a)
    pasture = db.pastures.get(a["pasture_id"])
    refresh_pasture(pasture)
    touch(pasture, bump_version=False)
    return success_envelope(assignment_out(a))


# ===========================================================================
# Supplement programs
# ===========================================================================
@bp.post("/api/supplement-programs")
def create_program():
    require_ctx(HM)
    body = get_body()
    check_allowed_fields(body, {"herd_group_id", "ranch_id", "program_type",
                                "start_date", "end_date", "feed_rate_oz_per_head_day",
                                "cost_cents_per_ton"})
    herd_group_id = req_str(body, "herd_group_id")
    ranch_id = req_str(body, "ranch_id")
    group = db.herd_groups.get(herd_group_id)
    if not group:
        raise err_not_found("herd_group_id does not exist")
    ranch = db.ranches.get(ranch_id)
    if not ranch or group["ranch_id"] != ranch_id:
        raise err_not_found("ranch_id does not exist or does not match the herd group")
    ptype = req_enum(body, "program_type", {"MINERAL", "PROTEIN", "ENERGY"})
    start = req_date(body, "start_date")
    end = req_date(body, "end_date")
    rate = req_number(body, "feed_rate_oz_per_head_day", positive=True)
    cost = req_int(body, "cost_cents_per_ton", nonneg=True)
    if start > end:
        raise err_invalid_request("start_date must precede or equal end_date")
    window_days = (end - start).days + 1  # inclusive both ends
    projected = d2(dec(group["head_count"]) * Decimal(window_days) * dec(rate) / Decimal(16))
    p = new_record()
    p.update({
        "herd_group_id": herd_group_id, "ranch_id": ranch_id, "program_type": ptype,
        "start_date": start, "end_date": end,
        "feed_rate_oz_per_head_day": rate, "cost_cents_per_ton": cost,
        "delivered_lbs_total": Decimal("0"), "cost_to_date_cents": Decimal("0"),
        "projected_consumption_lbs": projected,
        "program_status": "ACTIVE",
    })
    db.supplement_programs[p["id"]] = p
    return success_envelope(program_out(p), status=201)


@bp.get("/api/supplement-programs/<pid>")
def get_program(pid):
    require_ctx(ALL)
    p = db.supplement_programs.get(pid)
    if not p:
        raise err_not_found()
    return success_envelope(program_out(p))


@bp.get("/api/supplement-programs")
def list_programs():
    require_ctx(ALL)
    args = request.args
    items = list(db.supplement_programs.values())
    if args.get("herd_group_id"):
        items = [p for p in items if p["herd_group_id"] == args["herd_group_id"]]
    if args.get("ranch_id"):
        items = [p for p in items if p["ranch_id"] == args["ranch_id"]]
    if args.get("program_status"):
        items = [p for p in items if p["program_status"] == args["program_status"]]
    if args.get("program_type"):
        items = [p for p in items if p["program_type"] == args["program_type"]]
    window, pg = paginate(items)
    return success_envelope([program_out(p) for p in window], response_type="array", pagination=pg)


@bp.post("/api/supplement-programs/<pid>/deliveries")
def record_delivery(pid):
    require_ctx(HM)
    p = db.supplement_programs.get(pid)
    if not p:
        raise err_not_found()
    body = get_body()
    check_allowed_fields(body, {"delivered_lbs", "delivery_date"})
    lbs = req_number(body, "delivered_lbs", positive=True)
    req_date(body, "delivery_date")
    if p["program_status"] in ("COMPLETED", "CANCELLED"):
        raise err_already_terminal("Program is terminal")
    p["delivered_lbs_total"] = dec(p["delivered_lbs_total"]) + dec(lbs)
    p["cost_to_date_cents"] = d2(dec(p["delivered_lbs_total"]) / Decimal(2000) * dec(p["cost_cents_per_ton"]))
    touch(p)
    return success_envelope(program_out(p))


@bp.post("/api/supplement-programs/<pid>/complete")
def complete_program(pid):
    require_ctx(HM)
    p = db.supplement_programs.get(pid)
    if not p:
        raise err_not_found()
    get_body(required=False)
    if p["program_status"] in ("COMPLETED", "CANCELLED"):
        raise err_already_terminal("Program is terminal")
    p["program_status"] = "COMPLETED"
    touch(p)
    return success_envelope(program_out(p))


@bp.post("/api/supplement-programs/<pid>/cancel")
def cancel_program(pid):
    require_ctx(HM)
    p = db.supplement_programs.get(pid)
    if not p:
        raise err_not_found()
    get_body(required=False)
    if p["program_status"] in ("COMPLETED", "CANCELLED"):
        raise err_already_terminal("Program is terminal")
    p["program_status"] = "CANCELLED"
    touch(p)
    return success_envelope(program_out(p))
