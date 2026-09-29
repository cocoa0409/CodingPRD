"""Membership tier (§3.2) and member lifecycle (§3.3) endpoints."""

from flask import Blueprint

import calc
import derive
import guards
from core import (
    DB, ROLE_BOARD_OVERSIGHT, ROLE_DEVELOPMENT_OFFICER, ROLE_FINANCE_CONTROLLER,
    ROLE_MEMBER, apply_changes, authenticate, body, clock_date, fail, iso_date,
    iso_ms, list_response, lookup, lookup_fk, member_scope, new_row, now_clock,
    object_response, pagination, paginate, parse_date, public, q_bool, q_enum,
    q_str, rows, v_enum, v_int, v_str,
)
from routes_fiscal import finalize_create

bp = Blueprint("membership", __name__)


def get_tier(tier_id):
    return lookup("membership_tiers", tier_id, "ERR_MEMBERSHIP_TIER_NOT_FOUND")


def get_member(member_id):
    return lookup("members", member_id, "ERR_MEMBER_NOT_FOUND")


def validate_benefits(raw_benefits):
    if raw_benefits is None:
        return []
    if not isinstance(raw_benefits, list):
        fail("ERR_INVALID_REQUEST", "benefits must be an array")
    if len(raw_benefits) > 8:
        fail("ERR_INVALID_REQUEST", "benefits may hold at most eight items")
    cleaned = []
    for item in raw_benefits:
        if not isinstance(item, dict):
            fail("ERR_INVALID_REQUEST", "each benefit must be an object")
        code = item.get("benefit_code")
        if not isinstance(code, str) or not code:
            fail("ERR_INVALID_REQUEST", "benefit_code is required")
        fulfillment = item.get("fulfillment_type")
        if fulfillment not in calc.FULFILLMENT_TYPES:
            fail("ERR_INVALID_REQUEST", "fulfillment_type is not recognised")
        value = item.get("annual_fair_market_value_cents")
        if isinstance(value, bool) or not isinstance(value, int):
            fail("ERR_INVALID_REQUEST", "annual_fair_market_value_cents must be an integer")
        if value < 0:
            fail("ERR_INVALID_REQUEST", "annual_fair_market_value_cents may not be negative")
        cleaned.append({
            "benefit_code": code,
            "fulfillment_type": fulfillment,
            "annual_fair_market_value_cents": value,
        })
    return cleaned


# ---------------------------------------------------------------------------
# Membership tiers
# ---------------------------------------------------------------------------

@bp.post("/membership-tiers")
def create_membership_tier():
    authenticate(ROLE_DEVELOPMENT_OFFICER)
    data = body()
    tier_code = v_str(data, "tier_code", min_len=2, max_len=32, pattern=r"^[A-Z_]+$")
    guards.require_unique("membership_tiers", "tier_code", tier_code,
                          "tier_code must be unique")
    name = v_str(data, "name", min_len=1)
    renewal_cadence = v_enum(data, "renewal_cadence", calc.RENEWAL_CADENCES)
    contribution_amount_cents = v_int(data, "contribution_amount_cents", minimum=100)
    grace_period_days = v_int(data, "grace_period_days", required=False, minimum=0,
                              maximum=120, default=30)
    benefits = validate_benefits(data.get("benefits"))

    seen = set()
    for benefit in benefits:
        if benefit["benefit_code"] in seen:
            fail("ERR_BENEFIT_CODE_DUPLICATE",
                 "benefit_code %s appears more than once" % benefit["benefit_code"])
        seen.add(benefit["benefit_code"])

    threshold, qpq, insubstantial, benefit_count = calc.tier_quid_pro_quo_value(
        contribution_amount_cents, benefits, renewal_cadence)

    tier = new_row("membership_tiers", {
        "tier_code": tier_code,
        "name": name,
        "renewal_cadence": renewal_cadence,
        "contribution_amount_cents": contribution_amount_cents,
        "grace_period_days": grace_period_days,
        "benefits": benefits,
        "benefit_count": benefit_count,
        "insubstantial_benefit_codes": insubstantial,
        "quid_pro_quo_per_period_cents": qpq,
        "insubstantial_threshold_cents": threshold,
        "status": "DRAFT",
        "published_at": None,
    })
    return object_response(public(tier), 201)


@bp.get("/membership-tiers/<tier_id>")
def read_membership_tier(tier_id):
    authenticate(ROLE_DEVELOPMENT_OFFICER, ROLE_FINANCE_CONTROLLER,
                 ROLE_BOARD_OVERSIGHT, ROLE_MEMBER)
    return object_response(public(get_tier(tier_id)))


@bp.get("/membership-tiers")
def list_membership_tiers():
    authenticate(ROLE_DEVELOPMENT_OFFICER, ROLE_FINANCE_CONTROLLER,
                 ROLE_BOARD_OVERSIGHT, ROLE_MEMBER)
    status = q_enum("status", calc.TIER_STATUSES)
    cadence = q_enum("renewal_cadence", calc.RENEWAL_CADENCES)
    limit, offset = pagination()
    items = [t for t in rows("membership_tiers")
             if (status is None or t["status"] == status)
             and (cadence is None or t["renewal_cadence"] == cadence)]
    page, total = paginate(items, limit, offset)
    return list_response([public(t) for t in page], total, limit, offset)


@bp.post("/membership-tiers/<tier_id>/publish")
def publish_membership_tier(tier_id):
    authenticate(ROLE_DEVELOPMENT_OFFICER)
    tier = get_tier(tier_id)
    guards.require_state(tier["status"], ("DRAFT",), "membership tier")
    if int(tier["quid_pro_quo_per_period_cents"]) >= int(tier["contribution_amount_cents"]):
        fail("ERR_BENEFIT_VALUE_EXCEEDS_CONTRIBUTION",
             "the benefit bundle is worth the whole contribution or more")
    apply_changes(tier, {"status": "PUBLISHED", "published_at": iso_ms(now_clock())})
    return object_response(public(tier))


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------

@bp.post("/members")
def create_member():
    authenticate(ROLE_DEVELOPMENT_OFFICER)
    data = body()
    tier = lookup_fk("membership_tiers", data.get("tier_id"),
                     "ERR_MEMBERSHIP_TIER_NOT_FOUND")
    if tier is None:
        fail("ERR_INVALID_REQUEST", "tier_id is required")
    linked_funder = lookup_fk("funders", data.get("linked_funder_id"),
                              "ERR_FUNDER_NOT_FOUND")
    email = v_str(data, "email", min_len=1)
    if "@" not in email:
        fail("ERR_INVALID_REQUEST", "email must contain an @ character")
    guards.require_unique("members", "email", email, "email must be unique")
    full_name = v_str(data, "full_name", min_len=1)
    employer = v_str(data, "employer", required=False, default=None)

    if tier["status"] != "PUBLISHED":
        fail("ERR_TIER_NOT_PUBLISHED", "the tier is still DRAFT")

    member = new_row("members", {
        "tier_id": tier["id"],
        "email": email,
        "full_name": full_name,
        "employer": employer,
        "linked_funder_id": linked_funder["id"] if linked_funder else None,
        "status": "PENDING",
        "cycle_start_date": None,
        "next_renewal_date": None,
        "grace_expires_at": None,
        "lifetime_giving_cents": 0,
        "consecutive_renewals": 0,
        "is_major_donor": False,
        "cultivation_locked": False,
    })
    return object_response(public(member), 201)


@bp.get("/members/<member_id>")
def read_member(member_id):
    authenticate(ROLE_DEVELOPMENT_OFFICER, ROLE_FINANCE_CONTROLLER, ROLE_MEMBER)
    member = get_member(member_id)
    member_scope(member_id)
    return object_response(public(member))


@bp.get("/members")
def list_members():
    authenticate(ROLE_DEVELOPMENT_OFFICER, ROLE_FINANCE_CONTROLLER)
    tier_id = q_str("tier_id")
    linked_funder_id = q_str("linked_funder_id")
    status = q_enum("status", calc.MEMBER_STATUSES)
    is_major_donor = q_bool("is_major_donor")
    limit, offset = pagination()
    items = []
    for member in rows("members"):
        if tier_id is not None and member["tier_id"] != tier_id:
            continue
        if linked_funder_id is not None and member["linked_funder_id"] != linked_funder_id:
            continue
        if status is not None and member["status"] != status:
            continue
        if is_major_donor is not None and bool(member["is_major_donor"]) != is_major_donor:
            continue
        items.append(member)
    page, total = paginate(items, limit, offset)
    return list_response([public(m) for m in page], total, limit, offset)


@bp.post("/members/<member_id>/lifecycle-actions")
def member_lifecycle_actions(member_id):
    authenticate(ROLE_DEVELOPMENT_OFFICER, ROLE_MEMBER)
    member = get_member(member_id)
    member_scope(member_id)
    data = body()
    action = v_enum(data, "action", ("RENEW", "REINSTATE", "CANCEL"))
    tier = DB["membership_tiers"].get(member["tier_id"])

    guards.require_not_terminal(member["status"], ("CANCELLED",), "member")
    if action == "RENEW":
        guards.require_state(member["status"], ("ACTIVE", "GRACE"), "member")
    elif action == "REINSTATE":
        guards.require_state(member["status"], ("LAPSED",), "member")
    else:
        guards.require_state(member["status"], ("ACTIVE", "GRACE", "LAPSED"), "member")

    if action in ("RENEW", "REINSTATE"):
        if tier is None or tier["status"] != "PUBLISHED":
            fail("ERR_TIER_NOT_PUBLISHED", "the tier is no longer PUBLISHED")

    if action == "RENEW":
        consumed = parse_date(member.get("next_renewal_date"))
        changes = derive.member_schedule_changes(member, tier, consumed, status="ACTIVE")
        changes["status"] = "ACTIVE"
        changes["grace_expires_at"] = None
        changes["consecutive_renewals"] = int(member["consecutive_renewals"]) + 1
        apply_changes(member, changes)
    elif action == "REINSTATE":
        if member.get("cultivation_locked"):
            fail("ERR_INVALID_STATE", "the member's cultivation is locked")
        changes = derive.member_schedule_changes(member, tier, clock_date(), status="ACTIVE")
        changes["status"] = "ACTIVE"
        changes["grace_expires_at"] = None
        changes["consecutive_renewals"] = 0
        apply_changes(member, changes)
    else:
        apply_changes(member, {
            "status": "CANCELLED",
            "next_renewal_date": None,
            "grace_expires_at": None,
        })
    return object_response(public(member))


@bp.post("/members/<member_id>/tier-change")
def member_tier_change(member_id):
    authenticate(ROLE_DEVELOPMENT_OFFICER, ROLE_MEMBER)
    member = get_member(member_id)
    data = body()
    new_tier = lookup_fk("membership_tiers", data.get("new_tier_id"),
                         "ERR_MEMBERSHIP_TIER_NOT_FOUND")
    if new_tier is None:
        fail("ERR_INVALID_REQUEST", "new_tier_id is required")
    member_scope(member_id)
    expected_member_version = v_int(data, "expected_member_version")

    if new_tier["status"] != "PUBLISHED":
        fail("ERR_TIER_NOT_PUBLISHED", "the target tier is still DRAFT")
    if member["status"] not in ("ACTIVE", "GRACE"):
        fail("ERR_MEMBER_NOT_ACTIVE", "the member is %s" % member["status"])
    if new_tier["id"] == member["tier_id"]:
        fail("ERR_INVALID_STATE", "new_tier_id must differ from the current tier")
    if member.get("cultivation_locked"):
        fail("ERR_INVALID_STATE", "the member's cultivation is locked")
    if expected_member_version != int(member["version"]):
        fail("ERR_STALE_MEMBER_VERSION",
             "expected_member_version %s does not match %s"
             % (expected_member_version, member["version"]))

    changes = derive.member_schedule_changes(
        member, new_tier, parse_date(member.get("cycle_start_date")))
    changes["tier_id"] = new_tier["id"]
    apply_changes(member, changes)

    for contribution in rows("contributions"):
        if contribution.get("member_id") != member["id"]:
            continue
        if contribution.get("acknowledgment_status") != "UNACKNOWLEDGED":
            continue
        qpq, deductible = calc.contribution_deductible_split(
            contribution["revenue_stream"], contribution["amount_cents"], new_tier)
        apply_changes(contribution, {
            "quid_pro_quo_cents": qpq,
            "deductible_cents": deductible,
        })
    return object_response(public(member))
