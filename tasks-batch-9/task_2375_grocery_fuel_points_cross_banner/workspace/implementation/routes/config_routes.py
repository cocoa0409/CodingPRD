"""Banners, sites, promotional events, point cycles and the logical clock."""
from decimal import Decimal

from flask import Blueprint

import clock
import db
import middleware
import response
import shape
from errors import ApiError, bad_request
from routes._helpers import invalid_state, listing
from services import calc, core, serializers

bp = Blueprint("config", __name__)

SITE_TYPES = ("GROCERY", "OWNED_FUEL_CENTER", "PARTNER_STATION")
BANNER_STATUSES = ("ACTIVE", "SUSPENDED")
SITE_STATUSES = ("ACTIVE", "SUSPENDED")
HOUSEHOLD_STATUSES = ("ACTIVE", "FROZEN")
PROMO_STATUSES = ("SCHEDULED", "ACTIVE", "ENDED")
CYCLE_STATUSES = ("OPEN", "CLOSING", "CLOSED")


# ------------------------------------------------------------------- banners

@bp.route("/banners", methods=["POST"])
def create_banner():
    middleware.require(("ProgramAdmin",))
    payload = shape.body()

    banner_code = shape.req_str(payload, "banner_code", 3, 8, r"^[A-Z0-9]{3,8}$")
    name = shape.req_str(payload, "name", 1, 120)

    base_points_per_dollar = shape.opt_int(payload, "base_points_per_dollar", 1, 1, 10)
    gift_card_multiplier = shape.opt_int(payload, "gift_card_multiplier", 4, 1, 10)
    pharmacy_multiplier = shape.opt_int(payload, "pharmacy_multiplier", 2, 1, 10)
    pharmacy_points_per_script = shape.opt_int(payload, "pharmacy_points_per_script", 50, 0, 500)
    max_stacked_multiplier = shape.opt_int(payload, "max_stacked_multiplier", 8, 1, 50)
    max_stack_count = shape.opt_int(payload, "max_stack_count", 2, 1, 5)
    points_per_discount_block = shape.opt_int(payload, "points_per_discount_block", 100, 1, None)
    cents_off_per_block = shape.opt_int(payload, "cents_off_per_block", 10, 1, None)
    max_cents_off_per_gallon = shape.opt_int(payload, "max_cents_off_per_gallon", 100, 1, None)
    owned_max_gallons = shape.opt_int(payload, "owned_max_gallons_per_redemption", 35, 1, 1000)
    min_points_per_redemption = shape.opt_int(payload, "min_points_per_redemption", 100, 1, None)
    rollover_cap_points = shape.opt_int(payload, "rollover_cap_points", 500, 0, None)
    max_transfers_per_cycle = shape.opt_int(payload, "max_transfers_per_cycle", 3, 0, 50)
    expiry_basis = shape.opt_enum(payload, "expiry_basis",
                                  ("LOT_FIFO", "CYCLE_SCOPED"), "LOT_FIFO")
    fraud_scoring_mode = shape.opt_enum(payload, "fraud_scoring_mode",
                                        ("INSTANTANEOUS", "TRAILING_WEIGHTED"), "INSTANTANEOUS")
    freeze_threshold_score = shape.opt_int(payload, "freeze_threshold_score", 60, 1, 1000)

    # cross-field constraints only bind figures the client actually supplied
    if payload.get("max_cents_off_per_gallon") is not None:
        if max_cents_off_per_gallon < cents_off_per_block:
            raise bad_request("'max_cents_off_per_gallon' must be at least 'cents_off_per_block'")
        if max_cents_off_per_gallon % cents_off_per_block != 0:
            raise bad_request("'max_cents_off_per_gallon' must be a whole multiple of "
                              "'cents_off_per_block'")
    if payload.get("min_points_per_redemption") is not None:
        if min_points_per_redemption < points_per_discount_block:
            raise bad_request("'min_points_per_redemption' may not be below "
                              "'points_per_discount_block'")

    banner = core.new_entity()
    banner.update({
        "banner_code": banner_code,
        "name": name,
        "status": "ACTIVE",
        "base_points_per_dollar": base_points_per_dollar,
        "gift_card_multiplier": gift_card_multiplier,
        "pharmacy_multiplier": pharmacy_multiplier,
        "pharmacy_points_per_script": pharmacy_points_per_script,
        "max_stacked_multiplier": max_stacked_multiplier,
        "max_stack_count": max_stack_count,
        "points_per_discount_block": points_per_discount_block,
        "cents_off_per_block": cents_off_per_block,
        "max_cents_off_per_gallon": max_cents_off_per_gallon,
        "owned_max_gallons_per_redemption": owned_max_gallons,
        "min_points_per_redemption": min_points_per_redemption,
        "rollover_cap_points": rollover_cap_points,
        "max_transfers_per_cycle": max_transfers_per_cycle,
        "expiry_basis": expiry_basis,
        "fraud_scoring_mode": fraud_scoring_mode,
        "freeze_threshold_score": freeze_threshold_score,
    })
    db.banners[banner["id"]] = banner
    return response.object_response(serializers.banner(banner), 201)


@bp.route("/banners/<banner_id>", methods=["GET"])
def get_banner(banner_id):
    middleware.require(("ProgramAdmin", "LoyaltyAnalyst", "LoyaltySupervisor",
                        "StoreOperator", "SettlementClerk"))
    banner = core.fetch("banners", banner_id)
    return response.object_response(serializers.banner(banner))


@bp.route("/banners/<banner_id>/suspend", methods=["POST"])
def suspend_banner(banner_id):
    middleware.require(("ProgramAdmin",))
    banner = core.fetch("banners", banner_id)
    if banner["status"] != "ACTIVE":
        raise invalid_state("banner is already SUSPENDED")
    banner["status"] = "SUSPENDED"
    core.bump(banner)
    return response.object_response(serializers.banner(banner))


@bp.route("/banners/<banner_id>/promo-events", methods=["GET"])
def list_banner_promo_events(banner_id):
    middleware.require(("ProgramAdmin", "LoyaltyAnalyst", "LoyaltySupervisor", "StoreOperator"))
    shape.pagination()
    status = shape.arg_enum("status", PROMO_STATUSES)
    banner = core.fetch("banners", banner_id)
    rows = [e for e in db.promo_events.values() if e["banner_id"] == banner["id"]]
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    return listing(rows, serializers.promo_event,
                   order=lambda e: (-e["stack_priority"], e["created_at"], e["_seq"]))


@bp.route("/banners/<banner_id>/households", methods=["GET"])
def list_banner_households(banner_id):
    middleware.require(("ProgramAdmin", "LoyaltyAnalyst", "LoyaltySupervisor"))
    shape.pagination()
    status = shape.arg_enum("status", HOUSEHOLD_STATUSES)
    banner = core.fetch("banners", banner_id)
    rows = [h for h in db.households.values() if h["banner_id"] == banner["id"]]
    if status is not None:
        rows = [h for h in rows if h["status"] == status]
    return listing(rows, serializers.household, order=core.order_key)


# --------------------------------------------------------------------- sites

@bp.route("/sites", methods=["POST"])
def create_site():
    middleware.require(("ProgramAdmin",))
    payload = shape.body()

    banner_id = shape.req_str(payload, "banner_id")
    site_number = shape.req_str(payload, "site_number", 1, 16)
    site_type = shape.req_enum(payload, "site_type", SITE_TYPES)

    partner_code = shape.opt_str(payload, "partner_code", 3, 16, r"^[A-Z0-9]{3,16}$")
    per_gallon_cap_cents = shape.opt_int(payload, "per_gallon_cap_cents", None, 1, None)
    max_gallons = shape.opt_int(payload, "max_gallons_per_redemption", None, 1, 1000)

    if site_type == "PARTNER_STATION":
        if partner_code is None or per_gallon_cap_cents is None or max_gallons is None:
            raise bad_request("a PARTNER_STATION requires 'partner_code', "
                              "'per_gallon_cap_cents' and 'max_gallons_per_redemption'")
    else:
        if partner_code is not None or per_gallon_cap_cents is not None or max_gallons is not None:
            raise bad_request("'partner_code', 'per_gallon_cap_cents' and "
                              "'max_gallons_per_redemption' must be null for a %s site"
                              % site_type)

    banner = core.fetch("banners", banner_id)

    if site_type == "PARTNER_STATION" \
            and per_gallon_cap_cents % banner["cents_off_per_block"] != 0:
        raise bad_request("'per_gallon_cap_cents' must be a whole multiple of the banner's "
                          "'cents_off_per_block'")

    site = core.new_entity()
    site.update({
        "banner_id": banner["id"],
        "site_number": site_number,
        "site_type": site_type,
        "status": "ACTIVE",
        "partner_code": partner_code,
        "per_gallon_cap_cents": per_gallon_cap_cents,
        "max_gallons_per_redemption": max_gallons,
    })
    db.sites[site["id"]] = site
    return response.object_response(serializers.site(site), 201)


@bp.route("/sites/<site_id>", methods=["GET"])
def get_site(site_id):
    middleware.require(("ProgramAdmin", "LoyaltyAnalyst", "LoyaltySupervisor",
                        "StoreOperator", "PumpTerminal", "SettlementClerk"))
    site = core.fetch("sites", site_id)
    return response.object_response(serializers.site(site))


@bp.route("/sites", methods=["GET"])
def list_sites():
    middleware.require(("ProgramAdmin", "LoyaltyAnalyst", "LoyaltySupervisor",
                        "SettlementClerk"))
    shape.pagination()
    banner_id = shape.arg_str("banner_id")
    site_type = shape.arg_enum("site_type", SITE_TYPES)
    status = shape.arg_enum("status", SITE_STATUSES)
    rows = list(db.sites.values())
    if banner_id is not None:
        rows = [s for s in rows if s["banner_id"] == banner_id]
    if site_type is not None:
        rows = [s for s in rows if s["site_type"] == site_type]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    return listing(rows, serializers.site, order=core.order_key)


@bp.route("/sites/<site_id>/suspend", methods=["POST"])
def suspend_site(site_id):
    middleware.require(("ProgramAdmin",))
    site = core.fetch("sites", site_id)
    if site["status"] != "ACTIVE":
        raise invalid_state("site is already SUSPENDED")
    site["status"] = "SUSPENDED"
    core.bump(site)
    return response.object_response(serializers.site(site))


# -------------------------------------------------------------- promo events

@bp.route("/promo-events", methods=["POST"])
def create_promo_event():
    middleware.require(("ProgramAdmin",))
    payload = shape.body()

    banner_id = shape.req_str(payload, "banner_id")
    promo_code = shape.req_str(payload, "promo_code", 3, 24)
    multiplier = shape.req_int(payload, "multiplier", 2, 10)
    categories = shape.req_list(payload, "applies_to_categories", 1, 6)
    for value in categories:
        if not isinstance(value, str) or value not in calc.CATEGORIES:
            raise bad_request("'applies_to_categories' must contain declared purchase categories")
    if len(set(categories)) != len(categories):
        raise bad_request("'applies_to_categories' must not repeat a category")
    starts_at = shape.req_ts(payload, "starts_at")
    ends_at = shape.req_ts(payload, "ends_at")
    if not starts_at < ends_at:
        raise bad_request("'starts_at' must be strictly before 'ends_at'")
    stack_priority = shape.req_int(payload, "stack_priority", 0, 1000)

    banner = core.fetch("banners", banner_id)

    event = core.new_entity()
    event.update({
        "banner_id": banner["id"],
        "promo_code": promo_code,
        "multiplier": multiplier,
        "applies_to_categories": list(categories),
        "starts_at": starts_at,
        "ends_at": ends_at,
        "stack_priority": stack_priority,
        "status": "SCHEDULED",
    })
    conflict = core.promo_conflict(event)
    if conflict is not None:
        raise ApiError("ERR_PROMO_WINDOW_CONFLICT",
                       "promotional event %s already covers an overlapping window at the same "
                       "stack_priority for a shared category" % conflict["id"])
    db.promo_events[event["id"]] = event
    return response.object_response(serializers.promo_event(event), 201)


@bp.route("/promo-events/<event_id>/activate", methods=["POST"])
def activate_promo_event(event_id):
    middleware.require(("ProgramAdmin",))
    event = core.fetch("promo_events", event_id)
    banner = db.banners[event["banner_id"]]
    if banner["status"] != "ACTIVE":
        raise ApiError("ERR_BANNER_SUSPENDED", "banner %s is SUSPENDED" % banner["id"])
    if event["status"] != "SCHEDULED":
        raise invalid_state("only a SCHEDULED promotional event may be activated (current %s)"
                            % event["status"])
    conflict = core.promo_conflict(event)
    if conflict is not None:
        raise ApiError("ERR_PROMO_WINDOW_CONFLICT",
                       "promotional event %s already covers an overlapping window at the same "
                       "stack_priority for a shared category" % conflict["id"])
    event["status"] = "ACTIVE"
    core.bump(event)
    return response.object_response(serializers.promo_event(event))


# -------------------------------------------------------------- point cycles

_MONTH_RE = r"^\d{4}-(0[1-9]|1[0-2])$"


@bp.route("/point-cycles", methods=["POST"])
def create_point_cycle():
    middleware.require(("ProgramAdmin", "LoyaltySupervisor"))
    payload = shape.body()

    banner_id = shape.req_str(payload, "banner_id")
    cycle_month = shape.req_str(payload, "cycle_month", 7, 7, _MONTH_RE)
    opens_at = shape.req_ts(payload, "opens_at")
    closes_at = shape.req_ts(payload, "closes_at")
    if not opens_at < closes_at:
        raise bad_request("'closes_at' must be strictly later than 'opens_at'")

    banner = core.fetch("banners", banner_id)

    if core.cycle_by_month(banner["id"], cycle_month) is not None:
        raise ApiError("ERR_CYCLE_MONTH_DUPLICATE",
                       "banner %s already has a cycle for %s" % (banner["id"], cycle_month))

    cycle = core.new_entity()
    cycle.update({
        "banner_id": banner["id"],
        "cycle_month": cycle_month,
        "opens_at": opens_at,
        "closes_at": closes_at,
        "status": "OPEN",
        "expired_points_total": 0,
        "rolled_over_points_total": 0,
        "swept_member_count": 0,
        "closed_at": None,
    })
    db.point_cycles[cycle["id"]] = cycle
    return response.object_response(serializers.point_cycle(cycle), 201)


@bp.route("/point-cycles/<cycle_id>", methods=["GET"])
def get_point_cycle(cycle_id):
    middleware.require(("ProgramAdmin", "LoyaltyAnalyst", "LoyaltySupervisor", "StoreOperator"))
    cycle = core.fetch("point_cycles", cycle_id)
    return response.object_response(serializers.point_cycle(cycle))


@bp.route("/point-cycles", methods=["GET"])
def list_point_cycles():
    middleware.require(("ProgramAdmin", "LoyaltyAnalyst", "LoyaltySupervisor", "StoreOperator"))
    shape.pagination()
    banner_id = shape.arg_str("banner_id")
    status = shape.arg_enum("status", CYCLE_STATUSES)
    rows = list(db.point_cycles.values())
    if banner_id is not None:
        rows = [c for c in rows if c["banner_id"] == banner_id]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    return listing(rows, serializers.point_cycle,
                   order=lambda c: (c["cycle_month"], c["created_at"], c["_seq"]))


@bp.route("/point-cycles/<cycle_id>/begin-close", methods=["POST"])
def begin_close_point_cycle(cycle_id):
    middleware.require(("LoyaltySupervisor", "ProgramAdmin"))
    cycle = core.fetch("point_cycles", cycle_id)
    if cycle["status"] != "OPEN":
        raise invalid_state("only an OPEN cycle may begin closing (current %s)" % cycle["status"])
    if not clock.now() > cycle["closes_at"]:
        raise ApiError("ERR_CYCLE_NOT_ENDED",
                       "the logical clock has not passed the cycle's closes_at")
    for other in core.cycles_of(cycle["banner_id"]):
        if other["cycle_month"] < cycle["cycle_month"] and other["status"] != "CLOSED":
            raise ApiError("ERR_PRIOR_CYCLE_NOT_CLOSED",
                           "cycle %s (%s) is not CLOSED" % (other["id"], other["cycle_month"]))
    cycle["status"] = "CLOSING"
    core.bump(cycle)
    return response.object_response(serializers.point_cycle(cycle))


@bp.route("/point-cycles/<cycle_id>/close", methods=["POST"])
def close_point_cycle(cycle_id):
    middleware.require(("LoyaltySupervisor", "ProgramAdmin"))
    cycle = core.fetch("point_cycles", cycle_id)
    if cycle["status"] != "CLOSING":
        raise invalid_state("only a CLOSING cycle may be closed (current %s)" % cycle["status"])
    next_cycle = core.require_next_cycle(cycle)
    banner = db.banners[cycle["banner_id"]]

    members = core.by_created([m for m in db.members.values()
                               if m["banner_id"] == banner["id"]])
    expired_total = 0
    rolled_total = 0
    swept = 0
    touched_members = []
    for member in members:
        expiring, rolled, expired = core.sweep_amounts(member, banner, cycle)
        if expiring <= 0:
            continue
        wrote = False
        if expired > 0:
            core.add_entry(member["id"], cycle["id"], "EXPIRY", -expiring,
                           "POINT_CYCLE", cycle["id"],
                           memo="cycle %s expiry sweep" % cycle["cycle_month"])
            wrote = True
        if rolled > 0:
            core.add_entry(member["id"], cycle["id"], "ROLLOVER", rolled,
                           "POINT_CYCLE", cycle["id"],
                           lot_expires_at=next_cycle["closes_at"],
                           memo="cycle %s rollover" % cycle["cycle_month"])
            wrote = True
        if wrote:
            core.bump(member)
            touched_members.append(member)
            swept += 1
            expired_total += expired
            rolled_total += rolled

    cycle["expired_points_total"] = expired_total
    cycle["rolled_over_points_total"] = rolled_total
    cycle["swept_member_count"] = swept
    cycle["status"] = "CLOSED"
    cycle["closed_at"] = clock.now()
    core.bump(cycle)

    for event in core.by_created(list(db.promo_events.values())):
        if event["banner_id"] != banner["id"]:
            continue
        if event["status"] in ("SCHEDULED", "ACTIVE") and event["ends_at"] <= cycle["closes_at"]:
            event["status"] = "ENDED"
            core.bump(event)

    return response.object_response(serializers.point_cycle(cycle))


# --------------------------------------------------------------------- clock

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    middleware.require(("ProgramAdmin",))
    payload = shape.body()
    to_iso8601 = shape.req_ts(payload, "to_iso8601")
    current = clock.set_now(to_iso8601)
    return response.object_response({"current_utc": clock.fmt(current)})
