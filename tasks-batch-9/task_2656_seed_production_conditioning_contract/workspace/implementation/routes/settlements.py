"""Grower settlement, the advance-recovery waterfall and contract closure
(PRD 3.9)."""

from flask import Blueprint

import calc
from common import get_contract, get_settlement, paginate, public, public_list, rows_where
from envelope import list_response, object_response
from errors import ApiError
from store import by_created_at, db, new_record, touch
from validation import (Field, authenticate, json_body, parse_fields,
                        parse_pagination, query_enum, query_string)

bp = Blueprint("settlements", __name__)

SETTLEMENT_STATUSES = ("COMPUTED", "APPROVED", "PAID", "DISPUTED", "SUPERSEDED")

COMPUTE_FIELDS = [
    Field("production_contract_id", "string"),
    Field("expected_contract_version", "integer"),
]


def _settleable_lots(contract):
    lots = [lot for lot in db.seed_lots.values()
            if lot["production_contract_id"] == contract["id"]
            and lot["certification_status"] == "TAGGED"
            and lot["final_clean_units"] is not None]
    lots.sort(key=lambda lot: (lot["created_at"], lot["lot_code"]))
    return lots


@bp.post("/seed-ops/settlements")
def compute_settlement():
    user_id, _role = authenticate(("SettlementAccountant",))
    data = parse_fields(json_body(), COMPUTE_FIELDS)
    contract = get_contract(data["production_contract_id"])

    if contract["status"] != "HARVESTED":
        raise ApiError("ERR_INVALID_CONTRACT_STATE")
    if data["expected_contract_version"] != contract["version"]:
        raise ApiError("ERR_STALE_CONTRACT_VERSION")

    lines = _settleable_lots(contract)
    if not lines:
        raise ApiError("ERR_NO_SETTLEABLE_LOTS")

    rollup = calc.settlement_rollup(lines, contract["conditioning_charge_per_unit_cents"])
    provisional_net = rollup["gross_payable_cents"] - rollup["conditioning_charges_cents"]
    if provisional_net < 0:
        raise ApiError("ERR_NET_PAYABLE_NEGATIVE")

    cap, recovery, net = calc.settlement_net_payable(
        provisional_net, contract["advance_outstanding_cents"])

    superseded = [s for s in db.settlements.values()
                  if s["production_contract_id"] == contract["id"]
                  and s["status"] in ("COMPUTED", "DISPUTED")]
    for prior in by_created_at(superseded):
        prior["status"] = "SUPERSEDED"
        touch(prior)

    rec = new_record(True)
    rec["production_contract_id"] = contract["id"]
    rec["computed_by_user_id"] = user_id
    rec["approved_by_user_id"] = None
    rec["line_count"] = rollup["line_count"]
    rec["settled_units_total"] = rollup["settled_units_total"]
    rec["gross_payable_cents"] = rollup["gross_payable_cents"]
    rec["conditioning_charges_cents"] = rollup["conditioning_charges_cents"]
    rec["provisional_net_cents"] = provisional_net
    rec["recovery_cap_pct"] = calc.round_half_up(cap, 1)
    rec["advance_recovery_cents"] = recovery
    rec["net_payable_cents"] = net
    rec["status"] = "COMPUTED"
    rec["dispute_reason"] = None
    rec["payment_reference"] = None
    rec["quality_hold"] = False
    db.settlements[rec["id"]] = rec

    touch(contract)
    return object_response(public(rec), 201)


@bp.post("/seed-ops/settlements/<settlement_id>/approve")
def approve_settlement(settlement_id):
    user_id, _role = authenticate(("SettlementAccountant",))
    settlement = get_settlement(settlement_id)
    if settlement["status"] != "COMPUTED" or settlement["quality_hold"]:
        raise ApiError("ERR_INVALID_SETTLEMENT_STATE")
    if user_id == settlement["computed_by_user_id"]:
        raise ApiError("ERR_SOD_SETTLEMENT_SELF_APPROVAL")

    contract = db.production_contracts[settlement["production_contract_id"]]
    if contract["status"] != "HARVESTED":
        raise ApiError("ERR_INVALID_CONTRACT_STATE")

    settlement["status"] = "APPROVED"
    settlement["approved_by_user_id"] = user_id
    touch(settlement)

    contract["advance_outstanding_cents"] = (
        contract["advance_outstanding_cents"] - settlement["advance_recovery_cents"])
    contract["status"] = "SETTLED"
    touch(contract)
    return object_response(public(settlement))


@bp.post("/seed-ops/settlements/<settlement_id>/pay")
def pay_settlement(settlement_id):
    authenticate(("SettlementAccountant",))
    data = parse_fields(json_body(), [Field("payment_reference", "string")])
    settlement = get_settlement(settlement_id)
    if settlement["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_SETTLEMENT_STATE")

    settlement["status"] = "PAID"
    settlement["payment_reference"] = data["payment_reference"]
    touch(settlement)

    contract = db.production_contracts[settlement["production_contract_id"]]
    if contract["status"] == "SETTLED":
        contract["status"] = "CLOSED"
    touch(contract)
    return object_response(public(settlement))


@bp.post("/seed-ops/settlements/<settlement_id>/dispute")
def dispute_settlement(settlement_id):
    user_id, _role = authenticate(("Grower",))
    data = parse_fields(json_body(), [Field("dispute_reason", "string")])
    settlement = get_settlement(settlement_id)
    contract = db.production_contracts[settlement["production_contract_id"]]

    if user_id != contract["grower_id"]:
        raise ApiError("ERR_GROWER_SCOPE_VIOLATION")
    if settlement["status"] not in ("COMPUTED", "APPROVED"):
        raise ApiError("ERR_INVALID_SETTLEMENT_STATE")

    was_approved = settlement["status"] == "APPROVED"
    settlement["status"] = "DISPUTED"
    settlement["dispute_reason"] = data["dispute_reason"]
    touch(settlement)

    if was_approved:
        contract["advance_outstanding_cents"] = (
            contract["advance_outstanding_cents"] + settlement["advance_recovery_cents"])
        if contract["status"] == "SETTLED":
            contract["status"] = "HARVESTED"
    touch(contract)
    return object_response(public(settlement))


@bp.get("/seed-ops/settlements/<settlement_id>")
def read_settlement(settlement_id):
    authenticate(("ProgramAdmin", "SettlementAccountant", "Grower"))
    return object_response(public(get_settlement(settlement_id)))


@bp.get("/seed-ops/settlements")
def list_settlements():
    authenticate(("ProgramAdmin", "SettlementAccountant", "Grower"))
    limit, offset = parse_pagination()
    rows = rows_where(
        db.settlements,
        production_contract_id=query_string("production_contract_id"),
        status=query_enum("status", SETTLEMENT_STATUSES),
    )
    page, total = paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)
