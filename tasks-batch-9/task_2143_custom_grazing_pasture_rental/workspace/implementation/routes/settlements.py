"""Weight-out settlements: drafting, issue, dispute, adjudication, closeout."""
from datetime import timedelta

from flask import Blueprint, request

from common import (authenticate, body_of, opt_str, parse_dt, req_enum,
                    req_int, req_num, req_str)
from derive import (DISPUTE_WINDOW_DAYS, MAX_DISPUTE_ROUNDS,
                    pasture_of_contract, recompute_owner_credit,
                    recompute_pasture, select_effective_assessment,
                    sorted_records, tickets_of_contract, treatments_of_lot,
                    weight_events_of_lot)
from envelope import created, listing, ok, pagination, public, public_list
from errors import ApiError
from money import compute_settlement
from store import db, format_clock, new_record, touch

bp = Blueprint("settlements", __name__)

ALL_ROLES = ("Grazier", "CattleOwner", "RangeConsultant", "PlatformAdmin")
DISPUTED_FIELDS = ("SHRUNK_GAIN_LBS", "TREATMENT_CHARGE", "DEATH_LOSS_CREDIT")
RESOLUTIONS = ("UPHELD_GRAZIER", "UPHELD_OWNER", "SPLIT_MIDPOINT")
RESOLUTION_TO_METHOD = {
    "UPHELD_GRAZIER": "PROVISIONAL_PRORATED",
    "UPHELD_OWNER": "FINAL_ADJUDICATED",
    "SPLIT_MIDPOINT": "SPLIT_MIDPOINT",
}


def get_settlement(settlement_id):
    settlement = db.settlements.get(settlement_id)
    if settlement is None:
        raise ApiError("ERR_SETTLEMENT_NOT_FOUND", "Settlement does not exist.")
    return settlement


def _owner_of(settlement):
    contract = db.contracts[settlement["contract_id"]]
    return db.cattle_owners.get(contract["cattle_owner_id"])


@bp.post("/grazing/settlements")
def draft_settlement():
    actor = authenticate(("Grazier",))
    body = body_of()

    # priority 5 — body identifiers resolve
    contract_id = body.get("contract_id")
    if contract_id is not None and (not isinstance(contract_id, str) or contract_id not in db.contracts):
        raise ApiError("ERR_CONTRACT_NOT_FOUND", "contract_id does not resolve.")
    lot_id = body.get("lot_id")
    if lot_id is not None and (not isinstance(lot_id, str) or lot_id not in db.lots):
        raise ApiError("ERR_LOT_NOT_FOUND", "lot_id does not resolve.")

    contract_id = req_str(body, "contract_id")
    lot_id = req_str(body, "lot_id")
    expected_version = req_int(body, "expected_contract_version")

    contract = db.contracts[contract_id]
    lot = db.lots[lot_id]

    if contract["grazier_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Only the contract's grazier may draft a settlement.")

    if expected_version != contract["version"]:
        raise ApiError("ERR_STALE_CONTRACT_VERSION",
                       "expected_contract_version does not match the contract's current version.")

    for treatment in treatments_of_lot(lot["id"]):
        if treatment["status"] in ("RECORDED", "DISPUTED"):
            raise ApiError("ERR_OPEN_TREATMENT_REVIEW",
                           "The lot still carries an unreviewed health treatment.")

    out_events = [w for w in weight_events_of_lot(lot["id"]) if w["event_type"] == "OUT"]
    if len(out_events) != 1:
        raise ApiError("ERR_NO_OUT_WEIGHT", "The lot has no OUT scale ticket.")

    rec = new_record()
    rec.update({
        "contract_id": contract_id,
        "lot_id": lot_id,
        "adjudicator_id": None,
        "gain_method": "PROVISIONAL_PRORATED",
        "days_on_feed": lot["days_on_feed"],
        "billable_head_days": 0,
        "adjusted_in_weight_lbs": 0,
        "shrunk_gain_lbs": 0,
        "average_daily_gain": 0,
        "base_charge_cents": 0,
        "treatment_charge_cents": 0,
        "infrastructure_charge_cents": 0,
        "death_loss_credit_cents": 0,
        "subtotal_cents": 0,
        "early_removal_adjustment_cents": 0,
        "volume_rebate_cents": 0,
        "total_due_cents": 0,
        "dispute_round": 0,
        "disputed_field": None,
        "claimed_shrunk_gain_lbs": None,
        "resolution": None,
        "dispute_note": None,
        "adjudication_note": None,
        "void_reason": None,
        "issued_at": None,
        "dispute_opened_at": None,
        "status": "DRAFT",
    })
    db.settlements[rec["id"]] = rec
    compute_settlement(rec, recompute_aggregates=True)
    touch(contract)
    return created(public(rec))


@bp.get("/grazing/settlements/<settlement_id>")
def read_settlement(settlement_id):
    authenticate(ALL_ROLES)
    return ok(public(get_settlement(settlement_id)))


@bp.get("/grazing/settlements")
def list_settlements():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = sorted_records(db.settlements.values())
    for field in ("contract_id", "lot_id", "adjudicator_id", "status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    return listing(public_list(rows), limit, offset)


@bp.post("/grazing/settlements/<settlement_id>/issue")
def issue_settlement(settlement_id):
    actor = authenticate(("Grazier",))
    settlement = get_settlement(settlement_id)
    contract = db.contracts[settlement["contract_id"]]

    if contract["grazier_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Only the contract's grazier may issue this settlement.")

    if settlement["status"] != "DRAFT":
        raise ApiError("ERR_SETTLEMENT_INVALID_STATE", "Only a DRAFT settlement may be issued.")

    settlement["status"] = "ISSUED"
    settlement["issued_at"] = format_clock(db.clock)
    touch(settlement)

    if contract["billing_status"] == "UNBILLED":
        contract["billing_status"] = "SETTLEMENT_ISSUED"
        touch(contract)

    for ticket in tickets_of_contract(contract["id"]):
        if ticket["status"] == "REPAIRED":
            ticket["status"] = "BILLED"
            touch(ticket)

    recompute_owner_credit(_owner_of(settlement))
    return ok(public(settlement))


@bp.post("/grazing/settlements/<settlement_id>/dispute")
def dispute_settlement(settlement_id):
    actor = authenticate(("CattleOwner",))
    settlement = get_settlement(settlement_id)
    contract = db.contracts[settlement["contract_id"]]
    body = body_of()
    disputed_field = req_enum(body, "disputed_field", DISPUTED_FIELDS)
    claimed = req_num(body, "claimed_shrunk_gain_lbs")
    note = opt_str(body, "note")

    if contract["cattle_owner_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Only the contract's cattle owner may dispute.")

    if settlement["status"] != "ISSUED":
        raise ApiError("ERR_SETTLEMENT_INVALID_STATE", "Only an ISSUED settlement may be disputed.")

    deadline = parse_dt(settlement["issued_at"]) + timedelta(days=DISPUTE_WINDOW_DAYS)
    if db.clock > deadline:
        raise ApiError("ERR_DISPUTE_WINDOW_CLOSED", "The dispute window has elapsed.")

    if settlement["dispute_round"] >= MAX_DISPUTE_ROUNDS:
        raise ApiError("ERR_DISPUTE_ROUNDS_EXHAUSTED", "The settlement has used its dispute rounds.")

    settlement["status"] = "DISPUTED"
    settlement["dispute_round"] += 1
    settlement["disputed_field"] = disputed_field
    settlement["claimed_shrunk_gain_lbs"] = claimed
    if note is not None:
        settlement["dispute_note"] = note
    settlement["dispute_opened_at"] = format_clock(db.clock)
    touch(settlement)
    recompute_owner_credit(_owner_of(settlement))
    return ok(public(settlement))


@bp.post("/grazing/settlements/<settlement_id>/adjudicate")
def adjudicate_settlement(settlement_id):
    actor = authenticate(("RangeConsultant",))
    settlement = get_settlement(settlement_id)
    contract = db.contracts[settlement["contract_id"]]
    body = body_of()
    resolution = req_enum(body, "resolution", RESOLUTIONS)
    note = opt_str(body, "note")

    if settlement["status"] != "DISPUTED":
        raise ApiError("ERR_SETTLEMENT_INVALID_STATE", "Only a DISPUTED settlement may be adjudicated.")

    pasture = pasture_of_contract(contract)
    effective = select_effective_assessment(pasture) if pasture else None
    if effective is not None and effective["assessor_id"] == actor.user_id:
        raise ApiError("ERR_ADJUDICATOR_CONFLICT",
                       "The consultant authored the pasture's effective capacity assessment.")

    settlement["status"] = "ADJUDICATED"
    settlement["adjudicator_id"] = actor.user_id
    settlement["resolution"] = resolution
    if note is not None:
        settlement["adjudication_note"] = note
    settlement["gain_method"] = RESOLUTION_TO_METHOD[resolution]
    compute_settlement(settlement, recompute_aggregates=False)
    touch(settlement)
    recompute_owner_credit(_owner_of(settlement))
    return ok(public(settlement))


@bp.post("/grazing/settlements/<settlement_id>/reissue")
def reissue_settlement(settlement_id):
    actor = authenticate(("Grazier",))
    settlement = get_settlement(settlement_id)
    contract = db.contracts[settlement["contract_id"]]

    if contract["grazier_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Only the contract's grazier may reissue.")

    if settlement["status"] != "ADJUDICATED":
        raise ApiError("ERR_SETTLEMENT_INVALID_STATE", "Only an ADJUDICATED settlement may be reissued.")

    settlement["status"] = "ISSUED"
    settlement["issued_at"] = format_clock(db.clock)
    touch(settlement)
    recompute_owner_credit(_owner_of(settlement))
    return ok(public(settlement))


@bp.post("/grazing/settlements/<settlement_id>/finalize")
def finalize_settlement(settlement_id):
    actor = authenticate(("Grazier", "CattleOwner"))
    settlement = get_settlement(settlement_id)
    contract = db.contracts[settlement["contract_id"]]

    if actor.is_grazier and contract["grazier_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Only the contract's grazier may act here.")
    if actor.is_owner and contract["cattle_owner_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Only the contract's cattle owner may act here.")

    if settlement["status"] not in ("ISSUED", "ADJUDICATED"):
        raise ApiError("ERR_SETTLEMENT_INVALID_STATE",
                       "Finalization is only declared from ISSUED or ADJUDICATED.")

    if actor.is_grazier and settlement["status"] == "ISSUED":
        ready_at = parse_dt(settlement["issued_at"]) + timedelta(days=DISPUTE_WINDOW_DAYS)
        if db.clock < ready_at:
            raise ApiError("ERR_DISPUTE_WINDOW_OPEN",
                           "The grazier must wait out the dispute window.")

    settlement["status"] = "FINAL"
    touch(settlement)

    if contract["billing_status"] == "SETTLEMENT_ISSUED":
        contract["billing_status"] = "SETTLED"
        touch(contract)
    if contract["lifecycle_status"] in ("ACTIVE", "EARLY_REMOVAL_PENDING"):
        contract["lifecycle_status"] = "COMPLETED"
        touch(contract)

    lot = db.lots[settlement["lot_id"]]
    if lot["status"] == "WEIGHED_OUT":
        lot["status"] = "CLOSED"
        touch(lot)

    recompute_pasture(pasture_of_contract(contract))
    recompute_owner_credit(_owner_of(settlement))
    return ok(public(settlement))


@bp.post("/grazing/settlements/<settlement_id>/void")
def void_settlement(settlement_id):
    actor = authenticate(("Grazier",))
    settlement = get_settlement(settlement_id)
    contract = db.contracts[settlement["contract_id"]]
    body = body_of()
    reason = req_str(body, "reason")

    if contract["grazier_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Only the contract's grazier may void this settlement.")

    if settlement["status"] not in ("DRAFT", "ISSUED"):
        raise ApiError("ERR_SETTLEMENT_INVALID_STATE",
                       "Only a DRAFT or ISSUED settlement may be voided.")

    settlement["status"] = "VOID"
    settlement["void_reason"] = reason
    touch(settlement)

    if contract["billing_status"] == "SETTLEMENT_ISSUED":
        contract["billing_status"] = "UNBILLED"
        touch(contract)

    recompute_owner_credit(_owner_of(settlement))
    return ok(public(settlement))
