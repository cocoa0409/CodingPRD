"""Well transfers between operators (PRD 3.5)."""
from flask import Blueprint

import calc
import validate as v
from auth import (DETERMINATION_REVIEWER, FIELD_INSPECTOR, FUNDING_OFFICER,
                  OPERATOR, PROGRAM_ADMIN, endpoint, user_id)
from envelope import filter_value, object_response, paginated
from errors import ApiError
from lookup import collect, get_operator, get_transfer, get_well
from store import clock, db, new_row, touch

bp = Blueprint("transfers", __name__)

DECISION_ACTIONS = ("APPROVE", "DENY", "VOID")
CLOSURE_COMMITTED = ("PLUGGING_SCHEDULED", "PLUGGED", "RECLAIMED")

READ_ONE = (PROGRAM_ADMIN, FIELD_INSPECTOR, DETERMINATION_REVIEWER,
            FUNDING_OFFICER, OPERATOR)
READ_MANY = (PROGRAM_ADMIN, FIELD_INSPECTOR, DETERMINATION_REVIEWER,
             FUNDING_OFFICER)


def bad_transition(message):
    return ApiError("ERR_INVALID_STATE_TRANSITION", message)


def _failing_transferee(operator):
    if operator["status"] in ("INSOLVENT", "REVOKED"):
        return True
    if operator["status"] == "DELINQUENT" and operator["orphan_candidate_count"] > 0:
        return True
    return False


def _transfer_refused():
    return ApiError(
        "ERR_TRANSFER_TO_INSOLVENT_OPERATOR",
        "The receiving operator cannot take on additional wells.",
    )


@bp.route("/wells/<well_id>/transfers", methods=["POST"])
@endpoint((PROGRAM_ADMIN, OPERATOR))
def create_transfer(well_id):
    well = get_well(well_id)
    data = v.body()

    if v.present(data, "to_operator_id") and isinstance(data["to_operator_id"], str):
        get_operator(data["to_operator_id"])

    to_operator_id = v.str_field(data, "to_operator_id")
    to_operator = get_operator(to_operator_id)

    if _failing_transferee(to_operator):
        raise _transfer_refused()

    row = new_row()
    row.update({
        "well_id": well_id,
        "from_operator_id": well["operator_id"],
        "to_operator_id": to_operator_id,
        "status": "PENDING",
        "transferee_required_bond_cents": calc.transferee_required_bond(
            to_operator, well
        ),
        "decided_by_user_id": None,
        "approved_at": None,
        "voided_at": None,
        "void_reason": None,
    })
    db.transfers[row["id"]] = row
    return object_response(row, 201)


@bp.route("/well-transfers/<transfer_id>", methods=["GET"])
@endpoint(READ_ONE)
def fetch_transfer(transfer_id):
    return object_response(get_transfer(transfer_id))


@bp.route("/well-transfers", methods=["GET"])
@endpoint(READ_MANY)
def list_transfers():
    well_id = filter_value("well_id")
    from_operator_id = filter_value("from_operator_id")
    to_operator_id = filter_value("to_operator_id")
    status = filter_value("status")

    def keep(row):
        if well_id is not None and row["well_id"] != well_id:
            return False
        if from_operator_id is not None and row["from_operator_id"] != from_operator_id:
            return False
        if to_operator_id is not None and row["to_operator_id"] != to_operator_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return paginated(collect(db.transfers, keep))


@bp.route("/well-transfers/<transfer_id>/decision", methods=["POST"])
@endpoint((PROGRAM_ADMIN,), needs_user_id=True)
def decide_transfer(transfer_id):
    transfer = get_transfer(transfer_id)
    data = v.body()
    action = v.enum_field(data, "action", DECISION_ACTIONS)
    rationale = v.str_field(data, "rationale", required=False, allow_empty=True)

    well = get_well(transfer["well_id"])
    from_operator = db.operators.get(transfer["from_operator_id"])
    to_operator = db.operators.get(transfer["to_operator_id"])

    if action == "APPROVE":
        if transfer["status"] != "PENDING":
            raise bad_transition(
                "A transfer in %s cannot be approved." % transfer["status"]
            )
        if well["status"] in CLOSURE_COMMITTED:
            raise bad_transition(
                "The well is already committed to closure and cannot change hands."
            )
        if to_operator is None or _failing_transferee(to_operator):
            raise _transfer_refused()
        if to_operator["bond_amount_cents"] < transfer["transferee_required_bond_cents"]:
            raise ApiError(
                "ERR_TRANSFEREE_ASSURANCE_INSUFFICIENT",
                "The receiving operator's posted bond is below its post-transfer "
                "requirement.",
            )
        transfer["status"] = "APPROVED"
        transfer["approved_at"] = clock()
        transfer["decided_by_user_id"] = user_id()
        touch(transfer)

        well["operator_id"] = transfer["to_operator_id"]
        touch(well)
        calc.recompute_operator(from_operator)
        calc.recompute_operator(to_operator)

    elif action == "DENY":
        if transfer["status"] != "PENDING":
            raise bad_transition(
                "A transfer in %s cannot be denied." % transfer["status"]
            )
        transfer["status"] = "DENIED"
        transfer["decided_by_user_id"] = user_id()
        touch(transfer)

    else:
        if transfer["status"] != "APPROVED":
            raise bad_transition(
                "A transfer in %s cannot be voided." % transfer["status"]
            )
        if well["status"] in CLOSURE_COMMITTED:
            raise bad_transition(
                "The chain of custody is frozen once closure work has started."
            )
        transfer["status"] = "VOIDED"
        transfer["voided_at"] = clock()
        transfer["void_reason"] = "MANUAL_VOID"
        transfer["decided_by_user_id"] = user_id()
        touch(transfer)

        well["operator_id"] = transfer["from_operator_id"]
        touch(well)
        calc.recompute_operator(from_operator)
        calc.recompute_operator(to_operator)

    return object_response(transfer)
