"""Operator register and enforcement (PRD 3.1, 3.5)."""
from flask import Blueprint

import calc
import validate as v
from auth import (AWARD_AUTHORITY, DETERMINATION_REVIEWER, FIELD_INSPECTOR,
                  FUNDING_OFFICER, OPERATOR, PROCUREMENT_OFFICER,
                  PROGRAM_ADMIN, endpoint, user_id)
from envelope import filter_value, object_response, paginated
from errors import ApiError, invalid
from lookup import collect, get_operator
from store import clock, db, days, new_row, touch

bp = Blueprint("operators", __name__)

TIERS = ("BLANKET", "INDIVIDUAL")
OPERATOR_STATUSES = ("ACTIVE", "DELINQUENT", "INSOLVENT", "REVOKED")
ENFORCEMENT_ACTIONS = ("DECLARE_INSOLVENT", "REVOKE", "FORFEIT_BOND")

READ_ALL = (PROGRAM_ADMIN, FIELD_INSPECTOR, DETERMINATION_REVIEWER,
            PROCUREMENT_OFFICER, AWARD_AUTHORITY, FUNDING_OFFICER)
READ_ONE = READ_ALL + (OPERATOR,)


def bad_transition(message):
    return ApiError("ERR_INVALID_STATE_TRANSITION", message)


@bp.route("/operators", methods=["POST"])
@endpoint((PROGRAM_ADMIN,))
def create_operator():
    data = v.body()
    name = v.str_field(data, "name")
    region_code = v.region_field(data, "region_code")
    tier = v.enum_field(data, "financial_assurance_tier", TIERS)
    bond = v.int_field(data, "bond_amount_cents", minimum=0)

    row = new_row()
    row.update({
        "name": name,
        "region_code": region_code,
        "financial_assurance_tier": tier,
        "bond_amount_cents": bond,
        "status": "ACTIVE",
        "required_bond_cents": 0,
        "active_well_count": 0,
        "orphan_candidate_count": 0,
        "successor_operator_id": None,
        "insolvency_declared_at": None,
        "bond_forfeited_at": None,
    })
    db.operators[row["id"]] = row
    return object_response(row, 201)


@bp.route("/operators/<operator_id>", methods=["GET"])
@endpoint(READ_ONE)
def fetch_operator(operator_id):
    return object_response(get_operator(operator_id))


@bp.route("/operators", methods=["GET"])
@endpoint(READ_ALL)
def list_operators():
    status = filter_value("status")
    region_code = filter_value("region_code")
    successor = filter_value("successor_operator_id")

    def keep(row):
        if status is not None and row["status"] != status:
            return False
        if region_code is not None and row["region_code"] != region_code:
            return False
        if successor is not None and row["successor_operator_id"] != successor:
            return False
        return True

    return paginated(collect(db.operators, keep))


def _void_transfer(transfer, reason):
    transfer["status"] = "VOIDED"
    transfer["voided_at"] = clock()
    transfer["void_reason"] = reason
    touch(transfer)


@bp.route("/operators/<operator_id>/enforcement", methods=["POST"])
@endpoint((PROGRAM_ADMIN,))
def operator_enforcement(operator_id):
    operator = get_operator(operator_id)
    data = v.body()

    # Step 6: body reference existence precedes schema validation.
    if v.present(data, "successor_operator_id"):
        successor_raw = data["successor_operator_id"]
        if isinstance(successor_raw, str):
            get_operator(successor_raw)

    action = v.enum_field(data, "action", ENFORCEMENT_ACTIONS)
    expected = v.int_field(data, "expected_operator_version")
    v.str_field(data, "memo", required=False, allow_empty=True)
    successor_id = v.str_field(data, "successor_operator_id", required=False)

    # Step 8: optimistic concurrency control.
    if expected != operator["version"]:
        raise ApiError(
            "ERR_STALE_OPERATOR_VERSION",
            "expected_operator_version %s does not match the operator's current "
            "version %s." % (expected, operator["version"]),
        )

    # Step 9: the bond-forfeiture standing carve-out outranks the generic edge.
    if action == "FORFEIT_BOND" and operator["status"] != "INSOLVENT":
        raise ApiError(
            "ERR_OPERATOR_STILL_SOLVENT",
            "Bond forfeiture requires an INSOLVENT operator.",
        )

    if action == "DECLARE_INSOLVENT":
        _declare_insolvent(operator, successor_id)
    elif action == "REVOKE":
        _revoke(operator)
    else:
        _forfeit_bond(operator)

    touch(operator)
    return object_response(operator)


def _declare_insolvent(operator, successor_id):
    if operator["status"] not in ("ACTIVE", "DELINQUENT"):
        raise bad_transition(
            "DECLARE_INSOLVENT is not an edge out of %s." % operator["status"]
        )
    operator["status"] = "INSOLVENT"
    operator["insolvency_declared_at"] = clock()
    if successor_id is not None:
        operator["successor_operator_id"] = successor_id

    cutoff = calc.lookback_start()
    reverted = []
    for transfer in sorted(db.transfers.values(), key=lambda t: t["_seq"]):
        if transfer["to_operator_id"] != operator["id"]:
            continue
        if transfer["status"] != "APPROVED":
            continue
        if transfer["approved_at"] is None or transfer["approved_at"] < cutoff:
            continue
        _void_transfer(transfer, "TRANSFEREE_INSOLVENT")
        well = db.wells.get(transfer["well_id"])
        if well is not None:
            well["operator_id"] = transfer["from_operator_id"]
            touch(well)
            reverted.append(transfer["from_operator_id"])

    seen = []
    for from_operator_id in reverted:
        if from_operator_id in seen:
            continue
        seen.append(from_operator_id)
        calc.recompute_operator(db.operators.get(from_operator_id))
    calc.recompute_operator(operator, bump=False)


def _revoke(operator):
    if operator["status"] != "DELINQUENT":
        raise bad_transition(
            "REVOKE is not an edge out of %s." % operator["status"]
        )
    operator["status"] = "REVOKED"
    calc.promote_wells_to_orphan_candidate(operator["id"])
    calc.recompute_operator(operator, bump=False)


def _forfeit_bond(operator):
    if operator["bond_forfeited_at"] is not None:
        raise bad_transition("This operator's bond has already been forfeited.")
    if operator["bond_amount_cents"] <= 0:
        raise bad_transition("There is no posted bond to forfeit.")

    source = new_row()
    source.update({
        "kind": "FORFEITED_BOND",
        "name": "FORFEITED BOND " + operator["name"],
        "authorized_cents": operator["bond_amount_cents"],
        "committed_cents": 0,
        "disbursed_cents": 0,
        "expires_at": clock() + days(calc.FORFEITED_BOND_TERM_DAYS),
        "federal_match_required_pct": None,
        "allowable_cost_categories": ["PLUGGING", "RECLAMATION"],
        "bond_operator_id": operator["id"],
        "status": "ACTIVE",
        "reporting_required": False,
    })
    db.funding_sources[source["id"]] = source

    operator["bond_amount_cents"] = 0
    operator["bond_forfeited_at"] = clock()
    calc.recompute_operator(operator, bump=False)
    operator["status"] = "REVOKED"
    calc.promote_wells_to_orphan_candidate(operator["id"])
    calc.recompute_operator(operator, bump=False)
