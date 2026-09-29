from flask import Blueprint

import calc
import find
import serialize
import validators as v
from auth import acting_user_id, endpoint
from envelope import object_response, paginate
from errors import ApiError
from store import db, new_record, parse_instant, sorted_records, touch

bp = Blueprint("settlements", __name__)

LINE_KINDS = ("PRIZE_ADJUSTMENT", "SANCTION_FEE", "FEE_REBATE")
ROLES = ["CorpsDirector", "BusinessManager", "TourManager"]


@bp.route("/show-settlements", methods=["POST"])
@endpoint(["BusinessManager"])
def create_settlement():
    body = v.get_body()
    stop_id = v.req_str(body, "tour_stop_id")
    appearance_fee = v.req_int(body, "appearance_fee_cents")
    prize_pool = v.req_int(body, "prize_pool_cents")
    projected_placement = v.req_int(body, "projected_placement")
    v.check(projected_placement <= 12, "projected_placement", "must be at most 12")
    # Rung 6 -- positivity floors.
    v.positive(appearance_fee >= 0, "appearance_fee_cents must be at least 0.")
    v.positive(prize_pool >= 0, "prize_pool_cents must be at least 0.")
    v.positive(projected_placement >= 1, "projected_placement must be at least 1.")
    stop = find.stop(stop_id)
    # Rung 25 -- the parent stop must be a COMPLETED SHOW.
    if stop["status"] != "COMPLETED" or stop["stop_type"] != "SHOW":
        raise ApiError("ERR_STOP_NOT_COMPLETED",
                       "The parent stop must be a COMPLETED SHOW stop.")
    # Rung 49 -- a stop may carry at most one settlement.
    for other in db.settlements.values():
        if other["tour_stop_id"] == stop_id:
            raise ApiError("ERR_SETTLEMENT_ALREADY_EXISTS",
                           "This stop already carries a settlement.")

    provisional = calc.show_settlement_provisional(appearance_fee, prize_pool,
                                                   projected_placement)
    record = new_record()
    record.update({
        "tour_stop_id": stop_id,
        "appearance_fee_cents": appearance_fee,
        "prize_pool_cents": prize_pool,
        "projected_placement": projected_placement,
        "final_placement": None,
        "final_prize_cents": None,
        "final_gross_cents": None,
        "final_circuit_fee_cents": None,
        "sanctions_charged_cents": None,
        "rebate_applied_cents": None,
        "final_net_cents": None,
        "variance_cents": None,
        "remittance_line_count": 0,
        "prepared_by_user_id": acting_user_id(),
        "finalized_by_user_id": None,
        "status": "DRAFT",
    })
    record.update(provisional)
    db.settlements[record["id"]] = record
    return object_response(serialize.settlement(record), 201)


@bp.route("/show-settlements/<show_settlement_id>", methods=["GET"])
@endpoint(ROLES)
def get_settlement(show_settlement_id):
    return object_response(serialize.settlement(find.settlement(show_settlement_id)))


@bp.route("/show-settlements", methods=["GET"])
@endpoint(ROLES)
def list_settlements():
    stop_id = v.arg_str("tour_stop_id")
    status = v.arg_str("status")
    records = []
    for record in sorted_records(db.settlements):
        if stop_id is not None and record["tour_stop_id"] != stop_id:
            continue
        if status is not None and record["status"] != status:
            continue
        records.append(record)
    return paginate(records, serialize.settlement)


def _read_remittance_lines(body):
    if not v.present(body, "remittance_lines"):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'remittance_lines' is required.")
    raw_lines = body["remittance_lines"]
    if not isinstance(raw_lines, list):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'remittance_lines' must be an array.")
    lines = []
    for index, raw in enumerate(raw_lines):
        if not isinstance(raw, dict):
            raise ApiError("ERR_INVALID_REQUEST",
                           "Each remittance line must be a JSON object.")
        kind = v.req_enum(raw, "kind", LINE_KINDS)
        amount = v.req_int(raw, "amount_cents")
        recorded_raw = v.req_str(raw, "recorded_at")
        recorded_at = parse_instant(recorded_raw)
        if recorded_at is None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field 'recorded_at' must be an ISO 8601 UTC instant.")
        lines.append({
            "kind": kind,
            "amount_cents": amount,
            "recorded_at": recorded_raw,
            "_recorded_at": recorded_at,
            "_index": index,
        })
    return lines


@bp.route("/show-settlements/<show_settlement_id>/finalize", methods=["POST"])
@endpoint(["BusinessManager"])
def finalize_settlement(show_settlement_id):
    body = v.get_body()
    final_placement = v.req_int(body, "final_placement")
    v.check(final_placement <= 12, "final_placement", "must be at most 12")
    lines = _read_remittance_lines(body)
    # Rung 6 -- positivity floor on the certified placement.
    v.positive(final_placement >= 1, "final_placement must be at least 1.")
    settlement = find.settlement(show_settlement_id)
    # Rung 24 -- the settlement must be DRAFT.
    if settlement["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_SETTLEMENT_STATE",
                       "Only a DRAFT settlement may be finalized.")
    stop = db.stops.get(settlement["tour_stop_id"])
    # Rung 25 -- the parent stop must still be a COMPLETED SHOW.
    if stop is None or stop["status"] != "COMPLETED" or stop["stop_type"] != "SHOW":
        raise ApiError("ERR_STOP_NOT_COMPLETED",
                       "The parent stop must still be a COMPLETED SHOW stop.")
    # Rung 37 -- the preparer may never finalize their own draft.
    if acting_user_id() == settlement["prepared_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The finalizing user may not be the preparing user.")

    result = calc.show_settlement_final(
        settlement["appearance_fee_cents"], settlement["prize_pool_cents"],
        final_placement, lines, settlement["provisional_net_cents"])
    settlement["final_placement"] = final_placement
    settlement.update(result)
    settlement["status"] = "FINALIZED"
    settlement["finalized_by_user_id"] = acting_user_id()
    touch(settlement)
    if stop["settlement_state"] == "PENDING":
        stop["settlement_state"] = "SETTLED"
        touch(stop)
    return object_response(serialize.settlement(settlement))
