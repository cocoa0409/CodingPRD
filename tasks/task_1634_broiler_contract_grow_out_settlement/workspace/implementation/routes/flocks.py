"""Flock planning and the grow-out sub-resources: placements, feed, mortality,
weight tickets, catch schedules, condemned loss, and settlement compute."""
from flask import Blueprint, request

import db
import utils
from errors import ApiError
from helpers import check_unique, get_or_404, need_date, need_enum, need_int, need_instant, need_str
from middleware import body, grower_owns_or_403, list_response, require_roles
from response import ok
from services import domain

bp = Blueprint("flocks", __name__)

ADMIN = "IntegratorAdmin"
GROWER = "Grower"
ANALYST = "SettlementAnalyst"
TECH = "ServiceTech"
HAUL = "LivehaulScheduler"


def _body_fk(b, field, table, what):
    """Priority 4: a body FK must be present (422 when absent) and resolve (404)."""
    value = b.get(field)
    if not isinstance(value, str) or not value:
        raise ApiError(
            "ERR_QUANTITY_INVALID", "Field '%s' is required." % field, 422
        )
    if value not in table:
        raise ApiError(
            "ERR_REFERENCE_NOT_FOUND",
            "%s %s does not resolve." % (what, value),
            404,
        )
    return value


def _house_safety_guard(house, scheduled_date):
    """Priority 7 (ERR_HOUSE_IN_DOWNTIME): house not QUARANTINED and the
    scheduled placement date must clear any downtime window."""
    if house["house_status"] == "QUARANTINED":
        raise ApiError(
            "ERR_HOUSE_IN_DOWNTIME",
            "House is QUARANTINED and cannot receive a placement.",
            409,
        )
    if house["downtime_until"] is not None and not (scheduled_date > house["downtime_until"]):
        raise ApiError(
            "ERR_HOUSE_IN_DOWNTIME",
            "House is in downtime until %s; scheduled_date %s does not clear it."
            % (house["downtime_until"], scheduled_date),
            409,
        )


# ------------------------------------------------------------------ flock CRUD
@bp.route("/api/flocks", methods=["POST"])
@require_roles(ADMIN)
def create_flock():
    b = body()
    house_id = _body_fk(b, "house_id", db.houses, "house_id")
    contract_id = _body_fk(b, "contract_id", db.contracts, "contract_id")
    settlement_group_id = _body_fk(
        b, "settlement_group_id", db.settlement_groups, "settlement_group_id"
    )
    flock_no = need_str(b, "flock_no")
    check_unique(db.flocks.values(), "flock_no", flock_no, "flock_no")
    rec = utils.make_record(
        {
            "house_id": house_id,
            "contract_id": contract_id,
            "settlement_group_id": settlement_group_id,
            "flock_no": flock_no,
            "placed_head": 0,
            "placed_date": None,
            "status": "PLANNED",
            "feed_delivered_lbs": 0,
            "mortality_head": 0,
            "condemnation_head": 0,
            "live_weight_lbs": 0,
            "adj_fcr": None,
            "livability_pct": None,
            "condemnation_pct": 0,
            "performance_score": None,
        }
    )
    db.flocks[rec["id"]] = rec
    return ok(utils.pub(rec), 201)


@bp.route("/api/flocks/<fid>", methods=["GET"])
@require_roles(ADMIN, GROWER, TECH, HAUL, ANALYST)
def get_flock(fid):
    rec = get_or_404(db.flocks, fid, "Flock")
    grower_owns_or_403(domain.grower_id_of_flock(rec))
    return ok(utils.pub(rec))


@bp.route("/api/flocks", methods=["GET"])
@require_roles(ADMIN, ANALYST, HAUL)
def list_flocks():
    return list_response(
        db.flocks.values(),
        {
            "settlement_group_id": request.args.get("settlement_group_id"),
            "contract_id": request.args.get("contract_id"),
            "status": request.args.get("status"),
        },
    )


# ------------------------------------------------------------------ placements
@bp.route("/api/flocks/<fid>/placements", methods=["POST"])
@require_roles(ADMIN)
def create_placement(fid):
    flock = get_or_404(db.flocks, fid, "Flock")
    b = body()
    house = domain.house_of_flock(flock)
    scheduled_date = need_date(b, "scheduled_date")
    # Priority 7 before priority 11 (quantity).
    _house_safety_guard(house, scheduled_date)
    head_count = need_int(b, "head_count")
    if head_count <= 0 or head_count > house["capacity_birds"]:
        raise ApiError(
            "ERR_QUANTITY_INVALID",
            "head_count must be > 0 and <= house capacity_birds %d."
            % house["capacity_birds"],
            422,
        )
    rec = utils.make_record(
        {
            "flock_id": fid,
            "scheduled_date": scheduled_date,
            "head_count": head_count,
            "status": "SCHEDULED",
            "confirmed_date": None,
        }
    )
    db.placements[rec["id"]] = rec
    return ok(utils.pub(rec), 201)


@bp.route("/api/flocks/<fid>/placements", methods=["GET"])
@require_roles(ADMIN, GROWER, TECH)
def list_placements(fid):
    flock = get_or_404(db.flocks, fid, "Flock")
    grower_owns_or_403(domain.grower_id_of_flock(flock))
    rows = [p for p in db.placements.values() if p["flock_id"] == fid]
    return list_response(rows)


# ------------------------------------------------------------------ feed
@bp.route("/api/flocks/<fid>/feed-deliveries", methods=["POST"])
@require_roles(ADMIN)
def create_feed_delivery(fid):
    flock = get_or_404(db.flocks, fid, "Flock")
    b = body()
    delivered_date = need_date(b, "delivered_date")
    feed_lbs = need_int(b, "feed_lbs")
    if feed_lbs <= 0:
        raise ApiError("ERR_QUANTITY_INVALID", "feed_lbs must be > 0.", 422)
    feed_type = need_enum(b, "feed_type", domain.FEED_TYPES)
    ticket_no = need_str(b, "ticket_no")
    check_unique(db.feed_deliveries.values(), "ticket_no", ticket_no, "ticket_no")
    rec = utils.make_record(
        {
            "flock_id": fid,
            "delivered_date": delivered_date,
            "feed_lbs": feed_lbs,
            "feed_type": feed_type,
            "ticket_no": ticket_no,
        }
    )
    db.feed_deliveries[rec["id"]] = rec
    domain.apply_feed_delivery(flock, feed_lbs)
    return ok(utils.pub(rec), 201)


@bp.route("/api/flocks/<fid>/feed-deliveries", methods=["GET"])
@require_roles(ADMIN, GROWER, ANALYST)
def list_feed_deliveries(fid):
    flock = get_or_404(db.flocks, fid, "Flock")
    grower_owns_or_403(domain.grower_id_of_flock(flock))
    rows = [r for r in db.feed_deliveries.values() if r["flock_id"] == fid]
    return list_response(rows)


# ------------------------------------------------------------------ mortality
@bp.route("/api/flocks/<fid>/mortality-reports", methods=["POST"])
@require_roles(GROWER)
def create_mortality_report(fid):
    flock = get_or_404(db.flocks, fid, "Flock")
    grower_owns_or_403(domain.grower_id_of_flock(flock))
    b = body()
    report_date = need_date(b, "report_date")
    dead_head = need_int(b, "dead_head")
    condemned_head = need_int(b, "condemned_head")
    if dead_head < 0 or condemned_head < 0:
        raise ApiError(
            "ERR_QUANTITY_INVALID",
            "dead_head and condemned_head must be >= 0.",
            422,
        )
    cumulative = (
        flock["mortality_head"] + flock["condemnation_head"] + dead_head + condemned_head
    )
    if cumulative > flock["placed_head"]:
        raise ApiError(
            "ERR_QUANTITY_INVALID",
            "Cumulative mortality + condemnation (%d) exceeds placed_head (%d)."
            % (cumulative, flock["placed_head"]),
            422,
        )
    rec = utils.make_record(
        {
            "flock_id": fid,
            "report_date": report_date,
            "dead_head": dead_head,
            "condemned_head": condemned_head,
        }
    )
    db.mortality_reports[rec["id"]] = rec
    domain.apply_mortality_report(flock, dead_head, condemned_head)
    return ok(utils.pub(rec), 201)


@bp.route("/api/flocks/<fid>/mortality-reports", methods=["GET"])
@require_roles(ADMIN, GROWER, ANALYST)
def list_mortality_reports(fid):
    flock = get_or_404(db.flocks, fid, "Flock")
    grower_owns_or_403(domain.grower_id_of_flock(flock))
    rows = [r for r in db.mortality_reports.values() if r["flock_id"] == fid]
    return list_response(rows)


# ------------------------------------------------------------------ weight tickets
@bp.route("/api/flocks/<fid>/weight-tickets", methods=["POST"])
@require_roles(HAUL)
def create_weight_ticket(fid):
    flock = get_or_404(db.flocks, fid, "Flock")
    b = body()
    ticket_no = need_str(b, "ticket_no")
    weighed_at = need_instant(b, "weighed_at")
    live_weight_lbs = need_int(b, "live_weight_lbs")
    if live_weight_lbs <= 0:
        raise ApiError(
            "ERR_QUANTITY_INVALID", "live_weight_lbs must be > 0.", 422
        )
    check_unique(db.weight_tickets.values(), "ticket_no", ticket_no, "ticket_no")
    rec = utils.make_record(
        {
            "flock_id": fid,
            "ticket_no": ticket_no,
            "weighed_at": weighed_at,
            "live_weight_lbs": live_weight_lbs,
        }
    )
    db.weight_tickets[rec["id"]] = rec
    domain.apply_weight_ticket(flock, live_weight_lbs)
    return ok(utils.pub(rec), 201)


@bp.route("/api/flocks/<fid>/weight-tickets", methods=["GET"])
@require_roles(ADMIN, GROWER, HAUL, ANALYST)
def list_weight_tickets(fid):
    flock = get_or_404(db.flocks, fid, "Flock")
    grower_owns_or_403(domain.grower_id_of_flock(flock))
    rows = [r for r in db.weight_tickets.values() if r["flock_id"] == fid]
    return list_response(rows)


# ------------------------------------------------------------------ catch schedules
@bp.route("/api/flocks/<fid>/catch-schedules", methods=["POST"])
@require_roles(HAUL)
def create_catch_schedule(fid):
    flock = get_or_404(db.flocks, fid, "Flock")
    b = body()
    crew_id = _body_fk(b, "crew_id", db.catch_crews, "crew_id")
    crew = db.catch_crews[crew_id]
    if flock["status"] != "GROWING":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Catch can only be scheduled for a GROWING flock (current: %s)."
            % flock["status"],
            409,
        )
    catch_date = need_date(b, "catch_date")
    # Priority 9: crew capacity before priority 10: flock age.
    committed = sum(
        1
        for s in db.catch_schedules.values()
        if s["crew_id"] == crew_id
        and s["catch_date"] == catch_date
        and s["status"] in ("SCHEDULED", "COMPLETED")
    )
    if committed >= crew["max_catches_per_day"]:
        raise ApiError(
            "ERR_CREW_OVERBOOKED",
            "Crew %s already has %d catch(es) on %s (max %d)."
            % (crew_id, committed, catch_date, crew["max_catches_per_day"]),
            409,
        )
    if utils.age_days(flock["placed_date"]) < domain.MIN_GROW_DAYS:
        raise ApiError(
            "ERR_FLOCK_TOO_YOUNG",
            "Flock is %d days old; catch requires at least %d days."
            % (utils.age_days(flock["placed_date"]), domain.MIN_GROW_DAYS),
            422,
        )
    rec = utils.make_record(
        {
            "flock_id": fid,
            "crew_id": crew_id,
            "catch_date": catch_date,
            "status": "SCHEDULED",
        }
    )
    db.catch_schedules[rec["id"]] = rec
    flock["status"] = "CATCH_SCHEDULED"
    domain.bump(flock)
    return ok(utils.pub(rec), 201)


@bp.route("/api/flocks/<fid>/catch-schedules", methods=["GET"])
@require_roles(ADMIN, GROWER, HAUL)
def list_catch_schedules(fid):
    flock = get_or_404(db.flocks, fid, "Flock")
    grower_owns_or_403(domain.grower_id_of_flock(flock))
    rows = [s for s in db.catch_schedules.values() if s["flock_id"] == fid]
    return list_response(rows)


# ------------------------------------------------------------------ condemned loss
@bp.route("/api/flocks/<fid>/declare-condemned-loss", methods=["POST"])
@require_roles(ADMIN)
def declare_condemned_loss(fid):
    flock = get_or_404(db.flocks, fid, "Flock")
    if flock["status"] != "GROWING":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Condemned loss can only be declared on a GROWING flock (current: %s)."
            % flock["status"],
            409,
        )
    condemnation_pct = utils.d4(flock["condemnation_pct"]) or utils.Decimal(0)
    if not condemnation_pct > domain.CONDEMNATION_LOSS_THRESHOLD:
        raise ApiError(
            "ERR_CONDEMNATION_BELOW_THRESHOLD",
            "condemnation_pct %s does not exceed the 0.30 whole-flock loss threshold."
            % flock["condemnation_pct"],
            422,
        )
    domain.declare_condemned_loss(flock)
    return ok(utils.pub(flock))


# ------------------------------------------------------------------ settlement compute
@bp.route("/api/flocks/<fid>/recompute-settlement", methods=["POST"])
@require_roles(ANALYST)
def recompute_settlement(fid):
    flock = get_or_404(db.flocks, fid, "Flock")
    if flock["status"] != "HARVESTED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Settlement can only be computed for a HARVESTED flock (current: %s)."
            % flock["status"],
            409,
        )
    b = body()
    # Priority 6: OCC on Flock.version (skipped when the field is omitted).
    if "expected_flock_version" in b and b.get("expected_flock_version") is not None:
        if b.get("expected_flock_version") != flock["version"]:
            raise ApiError(
                "ERR_STALE_FLOCK_VERSION",
                "expected_flock_version %r does not match current Flock.version %d; re-read and retry."
                % (b.get("expected_flock_version"), flock["version"]),
                412,
            )
    settlement = domain.compute_settlement_for_flock(flock)
    domain.bump(flock)
    return ok(utils.pub(settlement))


@bp.route("/api/flocks/<fid>/settlement", methods=["GET"])
@require_roles(ADMIN, GROWER, ANALYST)
def get_flock_settlement(fid):
    flock = get_or_404(db.flocks, fid, "Flock")
    grower_owns_or_403(domain.grower_id_of_flock(flock))
    settlement = domain.settlement_for_flock(fid)
    rows = [settlement] if settlement is not None else []
    return list_response(rows)
