"""Dispatch instructions, telemetry and performance scoring
(PRD 3.5 and 3.6)."""

from decimal import Decimal

from flask import Blueprint

import db
import errors
import middleware
import response
import validators as v
from errors import ApiError
from numeric import D, rnd, f, r3
from services import calc, core

bp = Blueprint("dispatches", __name__)

EXECUTION_STATUSES = ("PENDING", "ACCEPTED", "EXECUTING", "COMPLETED", "FAILED")
SCORING_STATUSES = ("NOT_SCORED", "PROVISIONAL", "SETTLED")
LIVE_RESERVATION_CLAIMS = ("PENDING", "ACCEPTED", "EXECUTING", "COMPLETED")


@bp.post("/dispatch-instructions")
def create_dispatch():
    middleware.authorize("MarketOperator")
    body = v.json_body()

    asset_id = v.ident(body, "asset_id")
    bid_id = v.ident(body, "bid_id")
    instructed_mw = v.num(body, "instructed_mw", gt=0)
    start_raw, start = v.timestamp(body, "setpoint_start")
    end_raw, end = v.timestamp(body, "setpoint_end")
    if not end > start:
        raise errors.bad_request(
            "Field 'setpoint_end' must be strictly later than 'setpoint_start'.")

    asset = core.get_asset(asset_id)
    bid = core.get_bid(bid_id)
    if bid["asset_id"] != asset_id:
        raise ApiError(errors.ERR_ASSET_SCOPE_MISMATCH, 409,
                       "The offer belongs to a different asset.")

    if bid["status"] != "CLEARED":
        raise ApiError(errors.ERR_BID_NOT_CLEARED, 409,
                       "The offer is not CLEARED.")
    core.gate_lockout(asset)
    core.gate_market_available(asset)

    reservation = core.reservation_of_bid(bid)
    delivery_start = db.parse_dt(bid["delivery_start"])
    delivery_end = db.parse_dt(bid["delivery_end"])
    inside_delivery = delivery_start <= start and end <= delivery_end
    inside_reservation = True
    if reservation is not None:
        window_start = db.parse_dt(reservation["window_start"])
        window_end = db.parse_dt(reservation["window_end"])
        inside_reservation = window_start <= start and end <= window_end
    if not (inside_delivery and inside_reservation):
        raise ApiError(errors.ERR_RESERVATION_WINDOW_MISMATCH, 422,
                       "The setpoint window escapes the cleared delivery window "
                       "or the backing reservation's window.")

    if D(instructed_mw) > D(bid["cleared_mw"]):
        raise ApiError(errors.ERR_INSTRUCTION_EXCEEDS_CLEARED, 422,
                       "instructed_mw exceeds the cleared power.")

    expected_energy = calc.expected_energy(instructed_mw, start, end)
    if reservation is not None:
        siblings = [d for d in core.dispatches_of_reservation(reservation["id"])
                    if d["execution_status"] in LIVE_RESERVATION_CLAIMS]
        total = rnd(D(expected_energy)
                    + sum((D(d["expected_energy_mwh"]) for d in siblings),
                          Decimal("0")), 3)
        if total > D(reservation["reserved_mwh"]):
            raise ApiError(errors.ERR_DISPATCH_EXCEEDS_RESERVATION, 422,
                           "The instruction draws more energy than its "
                           "reservation still holds.")

    instruction = db.new_row()
    instruction.update({
        "bid_id": bid_id,
        "asset_id": asset_id,
        "instructed_mw": instructed_mw,
        "setpoint_start": start_raw,
        "setpoint_end": end_raw,
        "direction": bid["direction"],
        "expected_energy_mwh": expected_energy,
        "execution_status": "PENDING",
        "scoring_status": "NOT_SCORED",
        "delivered_mwh": 0.0,
        "soc_delta_mwh": 0.0,
        "telemetry_sample_count": 0,
        "accuracy_score": None,
        "deadband_pct": None,
        "composite_score": None,
        "non_performance_charge_usd": 0.0,
        "failure_reason": None,
        "accepted_by_user_id": None,
    })
    db.dispatches[instruction["id"]] = instruction
    return response.created(db.serialize(instruction))


@bp.get("/dispatch-instructions/<dispatch_id>")
def read_dispatch(dispatch_id):
    middleware.any_role()
    return response.ok(db.serialize(core.get_dispatch(dispatch_id)))


@bp.get("/dispatch-instructions")
def list_dispatches():
    middleware.any_role()
    limit, offset = v.pagination()
    asset_id = v.query_str("asset_id")
    bid_id = v.query_str("bid_id")
    execution_status = v.query_enum("execution_status", EXECUTION_STATUSES)
    scoring_status = v.query_enum("scoring_status", SCORING_STATUSES)

    rows = list(db.dispatches.values())
    if asset_id is not None:
        rows = [r for r in rows if r["asset_id"] == asset_id]
    if bid_id is not None:
        rows = [r for r in rows if r["bid_id"] == bid_id]
    if execution_status is not None:
        rows = [r for r in rows if r["execution_status"] == execution_status]
    if scoring_status is not None:
        rows = [r for r in rows if r["scoring_status"] == scoring_status]
    rows = core.newest_first(rows)
    page, total = core.paginate(rows, limit, offset)
    return response.ok_list([db.serialize(r) for r in page], limit, offset, total)


@bp.post("/dispatch-instructions/<dispatch_id>/accept")
def accept_dispatch(dispatch_id):
    user_id, _role = middleware.authorize("ControlRoomOperator")
    instruction = core.get_dispatch(dispatch_id)
    asset = core.get_asset(instruction["asset_id"])
    bid = db.bids.get(instruction["bid_id"])

    if instruction["execution_status"] != "PENDING":
        raise ApiError(errors.ERR_DISPATCH_NOT_PENDING, 409,
                       "The instruction is not PENDING.")
    if bid is None or bid["status"] != "CLEARED":
        raise ApiError(errors.ERR_BID_NOT_CLEARED, 409,
                       "The parent offer is no longer CLEARED.")
    core.gate_lockout(asset)
    core.gate_market_available(asset)
    core.gate_derate(asset, instruction["instructed_mw"])

    instruction["execution_status"] = "ACCEPTED"
    instruction["accepted_by_user_id"] = user_id
    db.touch(instruction)
    return response.ok(db.serialize(instruction))


@bp.post("/dispatch-instructions/<dispatch_id>/execute")
def execute_dispatch(dispatch_id):
    user_id, role = middleware.authorize("SiteController")
    instruction = core.get_dispatch(dispatch_id)
    middleware.check_asset_ownership(user_id, role, instruction["asset_id"])
    asset = core.get_asset(instruction["asset_id"])
    bid = db.bids.get(instruction["bid_id"])
    reservation = core.reservation_of_bid(bid) if bid is not None else None

    if instruction["execution_status"] != "ACCEPTED":
        raise ApiError(errors.ERR_DISPATCH_NOT_ACCEPTED, 409,
                       "The instruction is not ACCEPTED.")
    if reservation is None or reservation["status"] != "HELD":
        raise ApiError(errors.ERR_RESERVATION_NOT_HELD, 409,
                       "The backing reservation is not HELD.")
    if asset["safety_state"] not in ("NORMAL", "ELEVATED"):
        raise ApiError(errors.ERR_ASSET_SAFETY_LOCKOUT, 409,
                       "The asset's safety posture forbids execution.")

    start = db.parse_dt(instruction["setpoint_start"])
    end = db.parse_dt(instruction["setpoint_end"])
    energy = calc.expected_energy(instruction["instructed_mw"], start, end)
    if D(energy) > D(reservation["reserved_mwh"]):
        raise ApiError(errors.ERR_DISPATCH_EXCEEDS_RESERVATION, 422,
                       "The instruction draws more energy than its reservation "
                       "holds.")

    instruction["execution_status"] = "EXECUTING"
    db.touch(instruction)
    return response.ok(db.serialize(instruction))


def _score(instruction, samples):
    accuracy, deadband, composite = calc.performance_score(samples)
    instruction["accuracy_score"] = accuracy
    instruction["deadband_pct"] = deadband
    instruction["composite_score"] = composite
    return composite


def _on_time_samples(instruction):
    end = db.parse_dt(instruction["setpoint_end"])
    rows = [s for s in core.samples_of(instruction["id"])
            if db.parse_dt(s["sampled_at"]) <= end]
    return core.by_sample_index(rows)


@bp.post("/dispatch-instructions/<dispatch_id>/complete")
def complete_dispatch(dispatch_id):
    user_id, role = middleware.authorize("SiteController")
    instruction = core.get_dispatch(dispatch_id)
    middleware.check_asset_ownership(user_id, role, instruction["asset_id"])
    asset = core.get_asset(instruction["asset_id"])

    if instruction["execution_status"] != "EXECUTING":
        raise ApiError(errors.ERR_DISPATCH_NOT_EXECUTING, 409,
                       "The instruction is not EXECUTING.")
    core.gate_lockout(asset)

    on_time = _on_time_samples(instruction)
    delivered = calc.delivered_energy(on_time)
    soc_delta = calc.soc_delta(instruction["direction"], delivered,
                               asset["round_trip_efficiency_pct"])

    instruction["execution_status"] = "COMPLETED"
    instruction["delivered_mwh"] = delivered
    instruction["soc_delta_mwh"] = soc_delta

    # the ledgers move in this order
    asset["soc_mwh"] = r3(D(asset["soc_mwh"]) + D(soc_delta))
    asset["cumulative_throughput_mwh"] = r3(
        D(asset["cumulative_throughput_mwh"]) + D(delivered))
    core.recompute_efc(asset)

    bid = db.bids.get(instruction["bid_id"])
    reservation = core.reservation_of_bid(bid) if bid is not None else None
    if reservation is not None and reservation["status"] == "HELD":
        reservation["status"] = "CONSUMED"
        reservation["consumed_mwh"] = delivered
        db.touch(reservation)
    core.recompute_pool(asset)

    # the provisional scoring pass — on-time telemetry only, never charged
    instruction["scoring_status"] = "PROVISIONAL"
    _score(instruction, on_time)
    instruction["non_performance_charge_usd"] = 0.0
    db.touch(instruction)

    core.reprice_draft_bids(asset)
    db.touch(asset)
    return response.ok(db.serialize(instruction))


@bp.post("/dispatch-instructions/<dispatch_id>/fail")
def fail_dispatch(dispatch_id):
    user_id, role = middleware.authorize("ControlRoomOperator", "SiteController")
    body = v.json_body(required=False)
    supplied_reason = v.text(body, "failure_reason", required=False, default=None,
                             min_len=1, max_len=120)
    instruction = core.get_dispatch(dispatch_id)
    middleware.check_asset_ownership(user_id, role, instruction["asset_id"])
    asset = core.get_asset(instruction["asset_id"])

    status = instruction["execution_status"]
    if status not in ("EXECUTING", "COMPLETED"):
        raise ApiError(errors.ERR_DISPATCH_NOT_EXECUTING, 409,
                       "The instruction is neither EXECUTING nor COMPLETED.")

    bid = db.bids.get(instruction["bid_id"])
    reservation = core.reservation_of_bid(bid) if bid is not None else None

    if status == "EXECUTING":
        # the no-delivery branch — nothing had been credited
        instruction["execution_status"] = "FAILED"
        instruction["failure_reason"] = supplied_reason or "OPERATOR_FAILURE"
        db.touch(instruction)
        if reservation is not None and reservation["status"] == "HELD":
            reservation["status"] = "RELEASED"
            reservation["released_reason"] = "DISPATCH_COMPENSATION"
            db.touch(reservation)
        core.recompute_pool(asset)
        db.touch(asset)
        return response.ok(db.serialize(instruction))

    # the compensation branch
    if instruction["scoring_status"] != "PROVISIONAL":
        raise ApiError(errors.ERR_SCORE_NOT_PROVISIONAL, 409,
                       "A settled instruction can no longer be compensated.")

    asset["cumulative_throughput_mwh"] = r3(
        D(asset["cumulative_throughput_mwh"]) - D(instruction["delivered_mwh"]))
    asset["soc_mwh"] = r3(D(asset["soc_mwh"]) - D(instruction["soc_delta_mwh"]))
    core.recompute_efc(asset)

    if reservation is not None and reservation["status"] == "CONSUMED":
        reservation["status"] = "RELEASED"
        reservation["consumed_mwh"] = 0.0
        reservation["released_reason"] = "DISPATCH_COMPENSATION"
        db.touch(reservation)
    core.recompute_pool(asset)

    instruction["execution_status"] = "FAILED"
    instruction["delivered_mwh"] = 0.0
    instruction["soc_delta_mwh"] = 0.0
    instruction["failure_reason"] = "DELIVERY_VOIDED"
    instruction["scoring_status"] = "NOT_SCORED"
    instruction["accuracy_score"] = None
    instruction["deadband_pct"] = None
    instruction["composite_score"] = None
    instruction["non_performance_charge_usd"] = 0.0
    db.touch(instruction)

    core.reprice_draft_bids(asset)
    db.touch(asset)
    return response.ok(db.serialize(instruction))


@bp.post("/dispatch-instructions/<dispatch_id>/settle-score")
def settle_score(dispatch_id):
    middleware.authorize("MarketOperator")
    instruction = core.get_dispatch(dispatch_id)

    if instruction["execution_status"] != "COMPLETED":
        raise ApiError(errors.ERR_DISPATCH_NOT_COMPLETED, 409,
                       "The instruction is not COMPLETED.")
    if instruction["scoring_status"] != "PROVISIONAL":
        raise ApiError(errors.ERR_SCORE_NOT_PROVISIONAL, 409,
                       "The scoring axis is not PROVISIONAL.")

    every_sample = core.by_sample_index(core.samples_of(instruction["id"]))
    composite = _score(instruction, every_sample)
    instruction["non_performance_charge_usd"] = calc.non_performance_charge(
        composite, instruction["instructed_mw"])
    instruction["scoring_status"] = "SETTLED"
    db.touch(instruction)
    return response.ok(db.serialize(instruction))
