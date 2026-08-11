"""Membership: registration, dues, tier changes and lapsing (6 endpoints)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from core import clock, serialize
from core.constants import (DUES_GRACE_DAYS, MEMBERSHIP_TERM_DAYS, MEMBER_STATUSES,
                            ROLES, TIERS, TIER_ANNUAL_DUES_CENTS, TIER_DISCOUNT_PCT,
                            TIER_RANK)
from core.envelope import created, ok, page
from core.errors import ApiError
from core.ladder import (body_fk, endpoint, enum_body, enum_filter, free_filter,
                         pagination, path_row, req_id, req_int, req_str, rung_occ)
from core.money import ceil_div, round_half_up
from core.store import DB, touch
from services import credits

bp = Blueprint("members", __name__)
R5 = list(ROLES)


def _tier_fields(tier):
    return TIER_RANK[tier], float(Decimal(TIER_DISCOUNT_PCT[tier]))


@bp.post("/members")
@endpoint(["ClubAdmin"])
def create_member(ctx):
    home = body_fk(ctx, "home_drop_point_id")
    email = req_str(ctx, "email")
    full_name = req_str(ctx, "full_name")
    req_id(ctx, "home_drop_point_id")
    tier = enum_body(ctx, "tier", TIERS, default="BASIC")
    for existing in DB.members.values():
        if existing["email"] == email:
            raise ApiError("ERR_VALIDATION", "email must be unique across members.")
    tier_rank, discount = _tier_fields(tier)
    row = DB.insert("Member", {
        "email": email, "full_name": full_name, "tier": tier,
        "tier_rank": tier_rank, "discount_pct": discount, "status": "PENDING",
        "home_drop_point_id": home["id"], "dues_paid_through": None,
        "dues_grace_until": None, "lifetime_dues_paid_cents": 0,
    })
    return created(serialize.member(row))


@bp.get("/members")
@endpoint(R5)
def list_members(ctx):
    limit, offset = pagination(ctx)
    status = enum_filter(ctx, "status", MEMBER_STATUSES)
    tier = enum_filter(ctx, "tier", TIERS)
    home = free_filter(ctx, "home_drop_point_id")
    rows = []
    for row in DB.all("Member"):
        if home is not None and row["home_drop_point_id"] != home:
            continue
        if status is not None and row["status"] != status:
            continue
        if tier is not None and row["tier"] != tier:
            continue
        rows.append(row)
    return page(serialize.project_all(rows), limit, offset)


@bp.get("/members/<member_id>")
@endpoint(R5)
def read_member(ctx, member_id):
    return ok(serialize.member(path_row("member_id", member_id)))


@bp.post("/members/<member_id>/dues-payments")
@endpoint(["ClubAdmin", "Member"])
def pay_dues(ctx, member_id):
    member = path_row("member_id", member_id)
    amount_cents = req_int(ctx, "amount_cents")
    term_years = req_int(ctx, "term_years", minimum=1)
    req_int(ctx, "expected_member_version")
    rung_occ(ctx, "expected_member_version", member)
    expected = TIER_ANNUAL_DUES_CENTS[member["tier"]] * term_years
    if amount_cents != expected:
        raise ApiError("ERR_VALIDATION",
                       "amount_cents must equal %d for a %d-year %s term."
                       % (expected, term_years, member["tier"]))
    credits.sweep(member["id"])
    paid_through = clock.now() + timedelta(days=MEMBERSHIP_TERM_DAYS * term_years)
    member["dues_paid_through"] = clock.render(paid_through)
    member["dues_grace_until"] = clock.render(paid_through + timedelta(days=DUES_GRACE_DAYS))
    member["lifetime_dues_paid_cents"] += amount_cents
    member["status"] = "ACTIVE"
    touch(member)
    return ok(serialize.member(member))


def tier_change_proration(member, new_tier):
    old_annual = TIER_ANNUAL_DUES_CENTS[member["tier"]]
    new_annual = TIER_ANNUAL_DUES_CENTS[new_tier]
    paid_through = clock.parse(member["dues_paid_through"]) if member["dues_paid_through"] else None
    if paid_through is None or clock.now() >= paid_through:
        remaining_days = 0
    else:
        delta = paid_through - clock.now()
        micros = (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds
        # CEILING: the day on which the change is made counts as remaining.
        remaining_days = ceil_div(micros, 86400 * 1000000)
    if new_annual <= old_annual:
        return 0
    return round_half_up(Decimal(new_annual - old_annual) * Decimal(remaining_days)
                         / Decimal(MEMBERSHIP_TERM_DAYS))


@bp.post("/members/<member_id>/tier-changes")
@endpoint(["ClubAdmin", "Member"])
def change_tier(ctx, member_id):
    member = path_row("member_id", member_id)
    if "new_tier" not in ctx.body or ctx.body["new_tier"] is None:
        raise ApiError("ERR_VALIDATION", "new_tier is required.")
    prorated = req_int(ctx, "prorated_amount_cents")
    req_int(ctx, "expected_member_version")
    new_tier = enum_body(ctx, "new_tier", TIERS, required=True)
    rung_occ(ctx, "expected_member_version", member)
    if new_tier == member["tier"]:
        raise ApiError("ERR_VALIDATION", "new_tier must differ from the current tier.")
    expected = tier_change_proration(member, new_tier)
    if prorated != expected:
        raise ApiError("ERR_VALIDATION",
                       "prorated_amount_cents must equal %d." % expected)
    member["tier"] = new_tier
    member["tier_rank"], member["discount_pct"] = _tier_fields(new_tier)
    member["lifetime_dues_paid_cents"] += prorated
    touch(member)
    return ok(serialize.member(member))


@bp.post("/members/<member_id>/lapse")
@endpoint(["ClubAdmin"])
def lapse_member(ctx, member_id):
    member = path_row("member_id", member_id)
    grace = clock.parse(member["dues_grace_until"]) if member["dues_grace_until"] else None
    if member["status"] != "ACTIVE" or grace is None or clock.now() <= grace:
        raise ApiError("ERR_VALIDATION",
                       "The member is not ACTIVE past the end of the dues grace period.")
    member["status"] = "LAPSED"
    touch(member)
    return ok(serialize.member(member))
