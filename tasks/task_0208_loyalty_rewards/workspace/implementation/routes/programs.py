"""Program lifecycle + config: programs, tiers, promotions, rewards, partners,
refresh-promotions, sweep-expirations, clock (PRD §3.1, §3.9, §3.10)."""
from flask import Blueprint

from db import db
from errors import (err, ERR_INVALID_RATE, ERR_PROGRAM_ALREADY_ACTIVE,
                    ERR_INVALID_STATE, ERR_DUPLICATE_TIER, ERR_INVALID_WINDOW,
                    ERR_PROMOTION_OVERLAP, ERR_INVALID_REQUEST)
from middleware import require_roles
from response import success
from services import serialize, ledger
from services.helpers import (get_json_body, require_str, require_number,
                              require_int, opt_int, opt_number, parse_iso,
                              fmt_iso, add_months, paginate)
from services.lookup import get_program, get_promotion, get_reward, get_partner

bp = Blueprint("programs", __name__)

VALID_TIER_CODES = {"STANDARD", "SILVER", "GOLD", "PLATINUM"}


# ---------------------------------------------------------------------------
# Programs
# ---------------------------------------------------------------------------
@bp.post("/programs")
def create_program():
    require_roles("ProgramAdmin")
    body = get_json_body()
    name = require_str(body, "name")
    base_earn_rate = require_number(body, "base_earn_rate")
    point_value_cents = require_number(body, "point_value_cents")
    lot_expiration_months = require_int(body, "lot_expiration_months")
    qualifying_window_months = opt_int(body, "qualifying_window_months", 12)
    birthday_reward_points = require_int(body, "birthday_reward_points")
    referral_referrer_points = require_int(body, "referral_referrer_points")
    referral_referee_points = require_int(body, "referral_referee_points")
    referral_min_qualifying_cents = require_int(body, "referral_min_qualifying_cents")

    # rate bounds (PRD §3.1) — config-rate check (priority 5)
    if base_earn_rate <= 0 or point_value_cents <= 0:
        raise err(ERR_INVALID_RATE, "base_earn_rate and point_value_cents must be > 0")
    if lot_expiration_months < 1:
        raise err(ERR_INVALID_REQUEST, "lot_expiration_months must be >= 1")
    if qualifying_window_months < 1:
        raise err(ERR_INVALID_REQUEST, "qualifying_window_months must be >= 1")

    p = {
        "name": name,
        "base_earn_rate": base_earn_rate,
        "point_value_cents": point_value_cents,
        "lot_expiration_months": lot_expiration_months,
        "qualifying_window_months": qualifying_window_months,
        "birthday_reward_points": birthday_reward_points,
        "referral_referrer_points": referral_referrer_points,
        "referral_referee_points": referral_referee_points,
        "referral_min_qualifying_cents": referral_min_qualifying_cents,
        "status": "DRAFT",
    }
    db.stamp_create(p)
    db.programs[p["id"]] = p
    return success(serialize.program_out(p), 201)


@bp.post("/programs/<pid>/activate")
def activate_program(pid):
    require_roles("ProgramAdmin")
    p = get_program(pid)
    if p["status"] != "DRAFT":
        raise err(ERR_PROGRAM_ALREADY_ACTIVE, "Program is not DRAFT")
    p["status"] = "ACTIVE"
    db.touch(p)
    return success(serialize.program_out(p), 200)


@bp.post("/programs/<pid>/close")
def close_program(pid):
    require_roles("ProgramAdmin")
    p = get_program(pid)
    if p["status"] not in ("DRAFT", "ACTIVE"):
        raise err(ERR_INVALID_STATE, "Program cannot be closed from its state")
    p["status"] = "CLOSED"
    db.touch(p)
    return success(serialize.program_out(p), 200)


@bp.get("/programs/<pid>")
def get_program_route(pid):
    require_roles("ProgramAdmin", "Member", "PartnerOperator")
    p = get_program(pid)
    return success(serialize.program_out(p), 200)


@bp.get("/programs")
def list_programs():
    require_roles("ProgramAdmin")
    page, pg = paginate(list(db.programs.values()))
    return success([serialize.program_out(x) for x in page], 200, pg)


# ---------------------------------------------------------------------------
# Tiers
# ---------------------------------------------------------------------------
@bp.post("/programs/<pid>/tiers")
def create_tier(pid):
    require_roles("ProgramAdmin")
    p = get_program(pid)
    body = get_json_body()
    code = require_str(body, "code")
    qualify_threshold = require_int(body, "qualify_threshold")
    earn_multiplier = require_number(body, "earn_multiplier")
    transfer_ratio = require_number(body, "transfer_ratio")
    rank = require_int(body, "rank")

    if code not in VALID_TIER_CODES:
        raise err(ERR_INVALID_REQUEST, "Invalid tier code")
    # rate bounds (priority 5)
    if transfer_ratio <= 0 or earn_multiplier < 1.0:
        raise err(ERR_INVALID_RATE, "transfer_ratio > 0 and earn_multiplier >= 1.0 required")
    if qualify_threshold < 0 or rank < 0:
        raise err(ERR_INVALID_REQUEST, "qualify_threshold and rank must be >= 0")

    # duplicate / STANDARD-special checks (priority 7)
    existing = ledger.program_tiers(pid)
    for t in existing:
        if t["code"] == code or t["rank"] == rank:
            raise err(ERR_DUPLICATE_TIER, "Tier code or rank already defined")
    if code == "STANDARD":
        if qualify_threshold != 0 or rank != 0 or earn_multiplier != 1.0:
            raise err(ERR_DUPLICATE_TIER,
                      "STANDARD must have qualify_threshold 0, rank 0, earn_multiplier 1.0")

    t = {
        "program_id": pid,
        "code": code,
        "qualify_threshold": qualify_threshold,
        "earn_multiplier": earn_multiplier,
        "transfer_ratio": transfer_ratio,
        "rank": rank,
    }
    db.stamp_create(t)
    db.tiers[t["id"]] = t
    return success(serialize.tier_out(t), 201)


@bp.get("/programs/<pid>/tiers")
def list_tiers(pid):
    require_roles("ProgramAdmin", "Member")
    get_program(pid)
    items = [t for t in db.tiers.values() if t["program_id"] == pid]
    page, pg = paginate(items)
    return success([serialize.tier_out(x) for x in page], 200, pg)


# ---------------------------------------------------------------------------
# Promotions (PRD §3.10)
# ---------------------------------------------------------------------------
def _promo_overlaps(program_id, new_start, new_end, exclude_id=None):
    for promo in db.promotions.values():
        if promo["program_id"] != program_id:
            continue
        if promo["status"] == "CANCELLED":
            continue
        if exclude_id is not None and promo["id"] == exclude_id:
            continue
        es = parse_iso(promo["starts_at"])
        ee = parse_iso(promo["ends_at"])
        # half-open overlap: new.start < existing.end AND existing.start < new.end
        if new_start < ee and es < new_end:
            return True
    return False


@bp.post("/programs/<pid>/promotions")
def create_promotion(pid):
    require_roles("ProgramAdmin")
    p = get_program(pid)
    body = get_json_body()
    name = require_str(body, "name")
    bonus_multiplier = require_number(body, "bonus_multiplier")
    starts_at_raw = require_str(body, "starts_at")
    ends_at_raw = require_str(body, "ends_at")
    min_eligible_cents = opt_int(body, "min_eligible_cents", 0)

    if bonus_multiplier < 1.0:
        raise err(ERR_INVALID_REQUEST, "bonus_multiplier must be >= 1.0")
    starts_at = parse_iso(starts_at_raw)
    ends_at = parse_iso(ends_at_raw)
    if min_eligible_cents < 0:
        raise err(ERR_INVALID_REQUEST, "min_eligible_cents must be >= 0")

    # window validity (priority 8): ends_at strictly after starts_at
    if not (ends_at > starts_at):
        raise err(ERR_INVALID_WINDOW, "Promotion ends_at must be after starts_at")

    # overlap (priority 9)
    if _promo_overlaps(pid, starts_at, ends_at):
        raise err(ERR_PROMOTION_OVERLAP, "Promotion window overlaps an existing promotion")

    promo = {
        "program_id": pid,
        "name": name,
        "bonus_multiplier": bonus_multiplier,
        "starts_at": fmt_iso(starts_at),
        "ends_at": fmt_iso(ends_at),
        "min_eligible_cents": min_eligible_cents,
        "status": "SCHEDULED",
    }
    db.stamp_create(promo)
    db.promotions[promo["id"]] = promo
    return success(serialize.promotion_out(promo), 201)


@bp.get("/programs/<pid>/promotions")
def list_promotions(pid):
    require_roles("ProgramAdmin", "Member")
    get_program(pid)
    items = [x for x in db.promotions.values() if x["program_id"] == pid]
    page, pg = paginate(items)
    return success([serialize.promotion_out(x) for x in page], 200, pg)


@bp.post("/promotions/<pid>/cancel")
def cancel_promotion(pid):
    require_roles("ProgramAdmin")
    promo = get_promotion(pid)
    if promo["status"] not in ("SCHEDULED", "ACTIVE"):
        raise err(ERR_INVALID_STATE, "Promotion cannot be cancelled from its state")
    promo["status"] = "CANCELLED"
    db.touch(promo)
    return success(serialize.promotion_out(promo), 200)


@bp.post("/programs/<pid>/refresh-promotions")
def refresh_promotions(pid):
    require_roles("ProgramAdmin")
    get_program(pid)
    now = db.current_clock
    changed = []
    promos = sorted(
        [x for x in db.promotions.values() if x["program_id"] == pid],
        key=lambda r: r["_seq"],
    )
    for promo in promos:
        starts = parse_iso(promo["starts_at"])
        ends = parse_iso(promo["ends_at"])
        if promo["status"] == "SCHEDULED" and starts <= now < ends:
            promo["status"] = "ACTIVE"
            db.touch(promo)
        elif promo["status"] == "ACTIVE" and now >= ends:
            promo["status"] = "ENDED"
            db.touch(promo)
        changed.append(promo)
    page, pg = paginate(changed)
    return success([serialize.promotion_out(x) for x in page], 200, pg)


# ---------------------------------------------------------------------------
# Catalog rewards (PRD §3.1)
# ---------------------------------------------------------------------------
@bp.post("/programs/<pid>/rewards")
def create_reward(pid):
    require_roles("ProgramAdmin")
    get_program(pid)
    body = get_json_body()
    name = require_str(body, "name")
    point_cost = require_int(body, "point_cost")
    tier_discount_pct = opt_number(body, "tier_discount_pct", 0.0)
    stock = require_int(body, "stock")

    if point_cost <= 0:
        raise err(ERR_INVALID_REQUEST, "point_cost must be > 0")
    if not (0 <= tier_discount_pct < 1):
        raise err(ERR_INVALID_REQUEST, "tier_discount_pct must be >= 0 and < 1")
    if stock < 0:
        raise err(ERR_INVALID_REQUEST, "stock must be >= 0")

    r = {
        "program_id": pid,
        "name": name,
        "point_cost": point_cost,
        "tier_discount_pct": tier_discount_pct,
        "stock": stock,
        "status": "ACTIVE",
    }
    db.stamp_create(r)
    db.rewards[r["id"]] = r
    return success(serialize.reward_out(r), 201)


@bp.get("/programs/<pid>/rewards")
def list_rewards(pid):
    require_roles("ProgramAdmin", "Member")
    get_program(pid)
    items = [x for x in db.rewards.values() if x["program_id"] == pid]
    page, pg = paginate(items)
    return success([serialize.reward_out(x) for x in page], 200, pg)


@bp.post("/rewards/<rid>/discontinue")
def discontinue_reward(rid):
    require_roles("ProgramAdmin")
    r = get_reward(rid)
    if r["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Reward cannot be discontinued from its state")
    r["status"] = "DISCONTINUED"
    db.touch(r)
    return success(serialize.reward_out(r), 200)


# ---------------------------------------------------------------------------
# Partner accounts (PRD §3.1, §3.8)
# ---------------------------------------------------------------------------
@bp.post("/programs/<pid>/partners")
def create_partner(pid):
    require_roles("ProgramAdmin")
    get_program(pid)
    body = get_json_body()
    name = require_str(body, "name")
    transfer_block_size = require_int(body, "transfer_block_size")
    min_transfer_points = require_int(body, "min_transfer_points")

    if transfer_block_size < 1:
        raise err(ERR_INVALID_REQUEST, "transfer_block_size must be >= 1")
    if min_transfer_points < 0:
        raise err(ERR_INVALID_REQUEST, "min_transfer_points must be >= 0")

    pa = {
        "program_id": pid,
        "name": name,
        "transfer_block_size": transfer_block_size,
        "min_transfer_points": min_transfer_points,
        "status": "ACTIVE",
    }
    db.stamp_create(pa)
    db.partners[pa["id"]] = pa
    return success(serialize.partner_out(pa), 201)


@bp.post("/partners/<pid>/pause")
def pause_partner(pid):
    require_roles("ProgramAdmin")
    pa = get_partner(pid)
    if pa["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Partner cannot be paused from its state")
    pa["status"] = "PAUSED"
    db.touch(pa)
    return success(serialize.partner_out(pa), 200)


@bp.post("/partners/<pid>/resume")
def resume_partner(pid):
    require_roles("ProgramAdmin")
    pa = get_partner(pid)
    if pa["status"] != "PAUSED":
        raise err(ERR_INVALID_STATE, "Partner cannot be resumed from its state")
    pa["status"] = "ACTIVE"
    db.touch(pa)
    return success(serialize.partner_out(pa), 200)


@bp.get("/partners/<pid>")
def get_partner_route(pid):
    require_roles("ProgramAdmin", "Member", "PartnerOperator")
    pa = get_partner(pid)
    return success(serialize.partner_out(pa), 200)


@bp.get("/programs/<pid>/partners")
def list_partners(pid):
    require_roles("ProgramAdmin", "Member", "PartnerOperator")
    get_program(pid)
    items = [x for x in db.partners.values() if x["program_id"] == pid]
    page, pg = paginate(items)
    return success([serialize.partner_out(x) for x in page], 200, pg)


# ---------------------------------------------------------------------------
# Sweep expirations (PRD §3.9)
# ---------------------------------------------------------------------------
@bp.post("/programs/<pid>/sweep-expirations")
def sweep_expirations(pid):
    require_roles("ProgramAdmin")
    program = get_program(pid)
    now = db.current_clock

    member_ids = {m["id"] for m in db.members.values()
                  if m["program_id"] == pid}

    # Expire due lots (ACTIVE, expires_at <= now, remaining > 0), oldest first.
    candidates = [l for l in db.lots.values()
                  if l["status"] == "ACTIVE"
                  and l["remaining_points"] > 0
                  and l["member_id"] in member_ids
                  and parse_iso(l["expires_at"]) <= now]
    candidates.sort(key=lambda l: (l["created_at"], l["id"]))

    swept = []
    affected_members = set()
    for lot in candidates:
        member = db.members[lot["member_id"]]
        ledger.append_tx(member, lot_id=lot["id"], tx_type="EXPIRE",
                         points_delta=-lot["remaining_points"])
        lot["remaining_points"] = 0
        lot["status"] = "EXPIRED"
        db.touch(lot)
        swept.append(lot)
        affected_members.add(member["id"])

    # Age out stale PENDING referrals (older than lot_expiration_months).
    for ref in db.referrals.values():
        if ref["program_id"] != pid:
            continue
        if ref["status"] != "PENDING":
            continue
        cutoff = add_months(parse_iso(ref["created_at"]),
                            program["lot_expiration_months"])
        if now >= cutoff:
            ref["status"] = "EXPIRED"
            db.touch(ref)

    # Recompute balances + tier for affected members.
    for mid in affected_members:
        ledger.recompute_member(db.members[mid])
        db.touch(db.members[mid])

    page, pg = paginate(swept)
    return success([serialize.lot_out(x) for x in page], 200, pg)


# ---------------------------------------------------------------------------
# Clock (test-driving) (PRD §3.9)
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def clock_set():
    require_roles("ProgramAdmin")
    body = get_json_body()
    to_iso = require_str(body, "to_iso8601")
    db.current_clock = parse_iso(to_iso)
    return success({"now": fmt_iso(db.current_clock)}, 200)


@bp.post("/_clock/advance")
def clock_advance():
    require_roles("ProgramAdmin")
    body = get_json_body()
    months = require_int(body, "months")
    db.current_clock = add_months(db.current_clock, months)
    return success({"now": fmt_iso(db.current_clock)}, 200)
