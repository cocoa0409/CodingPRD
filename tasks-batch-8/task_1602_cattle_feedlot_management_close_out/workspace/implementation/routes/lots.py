"""Lot endpoints."""
from flask import Blueprint

import store
from auth import authenticate, authorize, ALL_ROLES
from errors import ERR_LOT_NOT_FOUND, ERR_OWNER_NOT_FOUND, ERR_OWNER_SUSPENDED, \
    ERR_DUPLICATE_LOT_NUMBER, ERR_INVALID_REQUEST, raise_err
from serializers import lot_out, pen_assignment_out, ration_assignment_out, \
    health_event_out, death_loss_out, hedge_position_out, close_out_out, invoice_out
from services import lot_service
from util import body_json, get_or_404, list_response, new_record, bump, \
    req_str, req_int, opt_bool, req_date, success_object

bp = Blueprint("lots", __name__)


@bp.route("/feedlot/lots", methods=["POST"])
def create_lot():
    _, role = authenticate()
    authorize(role, ["FeedyardManager"])
    body = body_json()

    owner_id = req_str(body, "owner_id")
    lot_number = req_str(body, "lot_number")
    sex_class = req_str(body, "sex_class")
    head_count_in = req_int(body, "head_count_in")
    in_weight_total_lbs = req_int(body, "in_weight_total_lbs")
    purchase_cost_cents = req_int(body, "purchase_cost_cents")
    arrival_date = req_date(body, "arrival_date")
    commingle_allowed = opt_bool(body, "commingle_allowed", False)

    # Validate enums
    if sex_class not in ("STEER", "HEIFER"):
        raise_err(ERR_INVALID_REQUEST, "sex_class must be STEER or HEIFER")

    # Validate ranges
    if head_count_in <= 0:
        raise_err(ERR_INVALID_REQUEST, "head_count_in must be > 0")
    if in_weight_total_lbs <= 0:
        raise_err(ERR_INVALID_REQUEST, "in_weight_total_lbs must be > 0")
    if purchase_cost_cents < 0:
        raise_err(ERR_INVALID_REQUEST, "purchase_cost_cents must be >= 0")

    # Check owner exists and is ACTIVE
    owner = store.owners.get(owner_id)
    if owner is None:
        raise_err(ERR_OWNER_NOT_FOUND, "Owner not found: %s" % owner_id)
    if owner["status"] == "SUSPENDED":
        raise_err(ERR_OWNER_SUSPENDED, "Owner %s is SUSPENDED" % owner_id)

    # Check lot_number uniqueness
    for lot in store.lots.values():
        if lot["lot_number"] == lot_number:
            raise_err(ERR_DUPLICATE_LOT_NUMBER, "lot_number %s already in use" % lot_number)

    rec = new_record()
    rec.update({
        "owner_id": owner_id,
        "lot_number": lot_number,
        "sex_class": sex_class,
        "head_count_in": head_count_in,
        "in_weight_total_lbs": in_weight_total_lbs,
        "purchase_cost_cents": purchase_cost_cents,
        "arrival_date": arrival_date,
        "commingle_allowed": commingle_allowed,
        "status": "OPEN",
        "head_count_current": head_count_in,
        "head_shipped": 0,
        "total_deaths": 0,
        "out_weight_total_lbs": None,
        "total_feed_cost_cents": 0,
        "total_health_cost_cents": 0,
        "total_death_loss_cents": 0,
        "total_hedge_pnl_cents": 0,
        "insurance_credit_pending_cents": 0,
        "withdrawal_clear_date": None,
        "provisional_cog_cents_per_cwt": None,
        "_ship_date": None,
    })
    store.lots[rec["id"]] = rec
    return success_object(lot_out(rec), 201)


@bp.route("/feedlot/lots/<lot_id>", methods=["GET"])
def get_lot(lot_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.lots, lot_id, ERR_LOT_NOT_FOUND, "Lot")
    return success_object(lot_out(rec))


@bp.route("/feedlot/lots/<lot_id>/market", methods=["POST"])
def market_lot(lot_id):
    _, role = authenticate()
    authorize(role, ["FeedyardManager"])
    rec = get_or_404(store.lots, lot_id, ERR_LOT_NOT_FOUND, "Lot")
    lot_service.market_lot(rec)
    return success_object(lot_out(rec))


@bp.route("/feedlot/lots/<lot_id>/fail-sale", methods=["POST"])
def fail_sale_lot(lot_id):
    _, role = authenticate()
    authorize(role, ["FeedyardManager"])
    rec = get_or_404(store.lots, lot_id, ERR_LOT_NOT_FOUND, "Lot")
    lot_service.fail_sale(rec)
    return success_object(lot_out(rec))


@bp.route("/feedlot/lots/<lot_id>/ship", methods=["POST"])
def ship_lot(lot_id):
    _, role = authenticate()
    authorize(role, ["FeedyardManager"])
    rec = get_or_404(store.lots, lot_id, ERR_LOT_NOT_FOUND, "Lot")
    body = body_json()
    ship_date = req_date(body, "ship_date")
    out_weight_total_lbs = req_int(body, "out_weight_total_lbs")

    if out_weight_total_lbs <= 0:
        raise_err(ERR_INVALID_REQUEST, "out_weight_total_lbs must be > 0")

    lot_service.ship_lot(rec, ship_date, out_weight_total_lbs)
    return success_object(lot_out(rec))


@bp.route("/feedlot/lots/<lot_id>/assignments", methods=["GET"])
def list_lot_assignments(lot_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    get_or_404(store.lots, lot_id, ERR_LOT_NOT_FOUND, "Lot")
    assignments = [pa for pa in store.pen_assignments.values() if pa["lot_id"] == lot_id]
    return list_response(assignments, pen_assignment_out)


@bp.route("/feedlot/lots/<lot_id>/ration-assignments", methods=["GET"])
def list_lot_ration_assignments(lot_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    get_or_404(store.lots, lot_id, ERR_LOT_NOT_FOUND, "Lot")
    ras = [ra for ra in store.ration_assignments.values() if ra["lot_id"] == lot_id]
    return list_response(ras, ration_assignment_out)


@bp.route("/feedlot/lots/<lot_id>/health-events", methods=["GET"])
def list_lot_health_events(lot_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    get_or_404(store.lots, lot_id, ERR_LOT_NOT_FOUND, "Lot")
    events = [he for he in store.health_events.values() if he["lot_id"] == lot_id]
    return list_response(events, health_event_out)


@bp.route("/feedlot/lots/<lot_id>/death-losses", methods=["GET"])
def list_lot_death_losses(lot_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    get_or_404(store.lots, lot_id, ERR_LOT_NOT_FOUND, "Lot")
    losses = [dl for dl in store.death_losses.values() if dl["lot_id"] == lot_id]
    return list_response(losses, death_loss_out)


@bp.route("/feedlot/lots/<lot_id>/hedges", methods=["GET"])
def list_lot_hedges(lot_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    get_or_404(store.lots, lot_id, ERR_LOT_NOT_FOUND, "Lot")
    hedges = [h for h in store.hedge_positions.values() if h["lot_id"] == lot_id]
    return list_response(hedges, hedge_position_out)


@bp.route("/feedlot/lots/<lot_id>/close-outs", methods=["GET"])
def list_lot_close_outs(lot_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    get_or_404(store.lots, lot_id, ERR_LOT_NOT_FOUND, "Lot")
    close_outs = [co for co in store.close_outs.values() if co["lot_id"] == lot_id]
    return list_response(close_outs, close_out_out)


@bp.route("/feedlot/lots/<lot_id>/invoices", methods=["GET"])
def list_lot_invoices(lot_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    get_or_404(store.lots, lot_id, ERR_LOT_NOT_FOUND, "Lot")
    invoices = [inv for inv in store.invoices.values() if inv["lot_id"] == lot_id]
    return list_response(invoices, invoice_out)
