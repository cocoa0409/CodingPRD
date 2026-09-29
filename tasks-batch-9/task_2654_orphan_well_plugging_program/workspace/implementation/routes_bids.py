"""Bidding, responsiveness, award and the unit-cost contract (PRD 3.6)."""
from flask import Blueprint

import calc
import validate as v
from auth import (AWARD_AUTHORITY, CONTRACTOR, FIELD_INSPECTOR,
                  FUNDING_OFFICER, PROCUREMENT_OFFICER, PROGRAM_ADMIN,
                  endpoint, not_owner, role, sod, user_id)
from envelope import filter_value, object_response, paginated
from errors import ApiError
from lookup import (collect, get_bid, get_contract, get_contractor,
                    get_solicitation)
from store import db, new_row, touch
from store import clock

bp = Blueprint("bids", __name__)

EVALUATION_OUTCOMES = ("RESPONSIVE", "NONRESPONSIVE")
LIVE_BID_STATUSES = ("SUBMITTED", "RESPONSIVE", "NONRESPONSIVE", "AWARDED")

BID_READERS = (PROGRAM_ADMIN, PROCUREMENT_OFFICER, AWARD_AUTHORITY,
               FUNDING_OFFICER, CONTRACTOR)
CONTRACT_READ_ONE = (PROGRAM_ADMIN, PROCUREMENT_OFFICER, AWARD_AUTHORITY,
                     FUNDING_OFFICER, FIELD_INSPECTOR, CONTRACTOR)
CONTRACT_READ_MANY = (PROGRAM_ADMIN, PROCUREMENT_OFFICER, AWARD_AUTHORITY,
                      FUNDING_OFFICER, FIELD_INSPECTOR)


def bad_transition(message):
    return ApiError("ERR_INVALID_STATE_TRANSITION", message)


def _solicitation_bids(solicitation_id):
    return sorted(
        [b for b in db.bids.values() if b["solicitation_id"] == solicitation_id],
        key=lambda b: b["_seq"],
    )


@bp.route("/solicitations/<solicitation_id>/bids", methods=["POST"])
@endpoint((PROCUREMENT_OFFICER, CONTRACTOR))
def create_bid(solicitation_id):
    solicitation = get_solicitation(solicitation_id)
    data = v.body()

    # Step 3: a Contractor may only bid under its own identity.
    raw_contractor = data.get("contractor_id")
    if role() == CONTRACTOR and isinstance(raw_contractor, str):
        if raw_contractor != user_id():
            raise not_owner("A contractor may only submit bids for itself.")

    # Step 6: body reference existence.
    if isinstance(raw_contractor, str) and raw_contractor != "":
        get_contractor(raw_contractor)

    contractor_id = v.str_field(data, "contractor_id")
    cement = v.int_field(data, "cement_per_sack_cents", exclusive_minimum=0)
    rig_day = v.int_field(data, "rig_day_rate_cents", exclusive_minimum=0)
    casing = v.int_field(data, "casing_per_ft_cents", exclusive_minimum=0)
    mobilization = v.int_field(data, "mobilization_fee_cents", exclusive_minimum=0)
    technical_score = v.num_field(data, "technical_score", minimum=0, maximum=100)

    contractor = get_contractor(contractor_id)

    # Step 11: the referenced solicitation must be OPEN.
    if solicitation["status"] != "OPEN":
        raise ApiError(
            "ERR_SOLICITATION_NOT_OPEN",
            "Bids are only accepted while the solicitation is OPEN.",
        )

    # Step 15: licensing standing.
    if contractor["license_status"] != "GOOD_STANDING":
        raise ApiError(
            "ERR_CONTRACTOR_NOT_ELIGIBLE",
            "A contractor whose licence is %s may not bid."
            % contractor["license_status"],
        )

    # Step 16: uniqueness, then the deadline, then the ceiling.
    for existing in _solicitation_bids(solicitation_id):
        if existing["contractor_id"] == contractor_id:
            if existing["status"] in LIVE_BID_STATUSES:
                raise ApiError(
                    "ERR_DUPLICATE_BID",
                    "This contractor already holds a live bid on the "
                    "solicitation.",
                )
    if clock() >= solicitation["bid_due_at"]:
        raise ApiError(
            "ERR_BID_DEADLINE_PASSED",
            "The bid submission deadline has passed.",
        )

    evaluated = calc.basket_cost_cents(cement, rig_day, casing, mobilization)
    if evaluated > solicitation["ceiling_cents"]:
        raise ApiError(
            "ERR_BID_EXCEEDS_CEILING",
            "The evaluated basket cost exceeds the solicitation ceiling.",
        )

    row = new_row()
    row.update({
        "solicitation_id": solicitation_id,
        "contractor_id": contractor_id,
        "cement_per_sack_cents": cement,
        "rig_day_rate_cents": rig_day,
        "casing_per_ft_cents": casing,
        "mobilization_fee_cents": mobilization,
        "technical_score": technical_score,
        "evaluated_unit_cost_cents": evaluated,
        "price_score": None,
        "composite_score": None,
        "status": "SUBMITTED",
        "evaluated_by_user_id": None,
        "nonresponsive_reason": None,
    })
    db.bids[row["id"]] = row
    return object_response(row, 201)


@bp.route("/bids/<bid_id>", methods=["GET"])
@endpoint(BID_READERS)
def fetch_bid(bid_id):
    bid = get_bid(bid_id)
    if role() == CONTRACTOR and bid["contractor_id"] != user_id():
        raise not_owner("This bid belongs to another contractor.")
    return object_response(bid)


@bp.route("/bids", methods=["GET"])
@endpoint(BID_READERS)
def list_bids():
    solicitation_id = filter_value("solicitation_id")
    contractor_id = filter_value("contractor_id")
    status = filter_value("status")

    if role() == CONTRACTOR:
        if contractor_id is not None and contractor_id != user_id():
            raise not_owner("A contractor may only list its own bids.")
        contractor_id = user_id()

    def keep(row):
        if solicitation_id is not None and row["solicitation_id"] != solicitation_id:
            return False
        if contractor_id is not None and row["contractor_id"] != contractor_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return paginated(collect(db.bids, keep))


@bp.route("/bids/<bid_id>/evaluation", methods=["POST"])
@endpoint((PROCUREMENT_OFFICER,), needs_user_id=True)
def evaluate_bid(bid_id):
    bid = get_bid(bid_id)
    data = v.body()
    outcome = v.enum_field(data, "outcome", EVALUATION_OUTCOMES)
    reason = v.str_field(data, "reason", required=False, allow_empty=True)

    solicitation = get_solicitation(bid["solicitation_id"])
    contractor = get_contractor(bid["contractor_id"])

    if outcome == "RESPONSIVE":
        if bid["status"] not in ("SUBMITTED", "NONRESPONSIVE"):
            raise bad_transition(
                "A bid in %s cannot be marked RESPONSIVE." % bid["status"]
            )
        if solicitation["status"] not in ("OPEN", "EVALUATING"):
            raise bad_transition(
                "Responsiveness may only be recorded while the solicitation is "
                "OPEN or EVALUATING."
            )
        if calc.dec(bid["technical_score"]) < calc.dec(
                solicitation["min_technical_score"]):
            raise ApiError(
                "ERR_TECHNICAL_SCORE_BELOW_MINIMUM",
                "The bid's technical score is below the solicitation minimum.",
            )
        if bid["evaluated_unit_cost_cents"] > solicitation["ceiling_cents"]:
            raise ApiError(
                "ERR_BID_EXCEEDS_CEILING",
                "The evaluated basket cost exceeds the solicitation ceiling.",
            )
        if contractor["license_status"] != "GOOD_STANDING":
            raise ApiError(
                "ERR_CONTRACTOR_NOT_ELIGIBLE",
                "A contractor whose licence is %s cannot hold a responsive bid."
                % contractor["license_status"],
            )
        bid["status"] = "RESPONSIVE"
        bid["nonresponsive_reason"] = None
    else:
        if bid["status"] not in ("SUBMITTED", "RESPONSIVE"):
            raise bad_transition(
                "A bid in %s cannot be marked NONRESPONSIVE." % bid["status"]
            )
        if solicitation["status"] not in ("OPEN", "EVALUATING"):
            raise bad_transition(
                "Responsiveness may only be recorded while the solicitation is "
                "OPEN or EVALUATING."
            )
        bid["status"] = "NONRESPONSIVE"
        bid["nonresponsive_reason"] = reason

    bid["evaluated_by_user_id"] = user_id()
    touch(bid)
    return object_response(bid)


@bp.route("/solicitations/<solicitation_id>/award", methods=["POST"])
@endpoint((AWARD_AUTHORITY,), needs_user_id=True)
def award_solicitation(solicitation_id):
    solicitation = get_solicitation(solicitation_id)

    # Step 4: the officer who drafted the solicitation may not award it.
    if solicitation["created_by_user_id"] == user_id():
        raise sod("The drafting officer may not award this solicitation.")

    if solicitation["status"] != "EVALUATING":
        raise bad_transition(
            "A solicitation in %s cannot be awarded." % solicitation["status"]
        )

    all_bids = _solicitation_bids(solicitation_id)
    # The candidate pool is fixed before any score is computed.
    candidates = [b for b in all_bids if b["status"] == "RESPONSIVE"]
    if len(candidates) == 0:
        raise ApiError(
            "ERR_NO_RESPONSIVE_BIDS",
            "The solicitation has no responsive bids to award.",
        )

    lowest = min(b["evaluated_unit_cost_cents"] for b in candidates)
    scored = []
    for bid in candidates:
        price = calc.price_score(lowest, bid["evaluated_unit_cost_cents"])
        composite = calc.composite_score(price, bid["technical_score"])
        scored.append((bid, price, composite))

    ranked = sorted(
        scored,
        key=lambda item: (
            -calc.dec(item[2]),
            item[0]["evaluated_unit_cost_cents"],
            item[0]["created_at"],
            item[0]["_seq"],
        ),
    )
    winner = ranked[0][0]
    winning_contractor = get_contractor(winner["contractor_id"])
    if winning_contractor["license_status"] != "GOOD_STANDING":
        raise ApiError(
            "ERR_CONTRACTOR_NOT_ELIGIBLE",
            "The winning contractor's licence is %s."
            % winning_contractor["license_status"],
        )

    for bid, price, composite in scored:
        bid["price_score"] = price
        bid["composite_score"] = composite
        bid["status"] = "AWARDED" if bid["id"] == winner["id"] else "NOT_AWARDED"
        touch(bid)

    for bid in all_bids:
        if bid["status"] in ("SUBMITTED", "NONRESPONSIVE"):
            bid["status"] = "NOT_AWARDED"
            touch(bid)

    solicitation["status"] = "AWARDED"
    touch(solicitation)

    contract = new_row()
    contract.update({
        "solicitation_id": solicitation_id,
        "contractor_id": winner["contractor_id"],
        "winning_bid_id": winner["id"],
        "cement_per_sack_cents": winner["cement_per_sack_cents"],
        "rig_day_rate_cents": winner["rig_day_rate_cents"],
        "casing_per_ft_cents": winner["casing_per_ft_cents"],
        "mobilization_fee_cents": winner["mobilization_fee_cents"],
        "ceiling_cents": solicitation["ceiling_cents"],
        "obligated_cents": 0,
        "status": "ACTIVE",
        "awarded_by_user_id": user_id(),
    })
    db.contracts[contract["id"]] = contract

    return object_response(contract, 201)


@bp.route("/unit-cost-contracts/<contract_id>", methods=["GET"])
@endpoint(CONTRACT_READ_ONE)
def fetch_contract(contract_id):
    return object_response(get_contract(contract_id))


@bp.route("/unit-cost-contracts", methods=["GET"])
@endpoint(CONTRACT_READ_MANY)
def list_contracts():
    solicitation_id = filter_value("solicitation_id")
    contractor_id = filter_value("contractor_id")
    winning_bid_id = filter_value("winning_bid_id")
    status = filter_value("status")

    def keep(row):
        if solicitation_id is not None and row["solicitation_id"] != solicitation_id:
            return False
        if contractor_id is not None and row["contractor_id"] != contractor_id:
            return False
        if winning_bid_id is not None and row["winning_bid_id"] != winning_bid_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return paginated(collect(db.contracts, keep))
