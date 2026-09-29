"""Payer contracts and their fee schedules (PRD 3.6)."""

from flask import Blueprint

import config
import db
import middleware
import payload
import support
from errors import ApiError
from services import calc, derive, uow

bp = Blueprint("payer_contracts", __name__)

READ_ROLES = (
    config.ROLE_FINANCE_CONTROLLER,
    config.ROLE_INTEGRATION_LEAD,
    config.ROLE_DEAL_COUNSEL,
)


@bp.post("/payer-contracts")
@support.transactional
def create_contract():
    middleware.authorize([config.ROLE_FINANCE_CONTROLLER])
    data = payload.body()
    practice = support.load_fk(data, "practice_id", "practices")
    payload.string(data, "practice_id")
    payer_name = payload.string(data, "payer_name")
    row = db.insert(
        "payer_contracts",
        {
            "practice_id": practice["id"],
            "payer_name": payer_name,
            "transition_state": "LEGACY",
            "dso_schedule_effective_date": None,
            "erosion_override_ack": False,
        },
    )
    return "payer_contracts", row, 201


@bp.get("/payer-contracts/<payer_contract_id>")
def get_contract(payer_contract_id):
    middleware.authorize(READ_ROLES)
    row = support.load("payer_contracts", payer_contract_id)
    return support.read_one("payer_contracts", row)


@bp.get("/payer-contracts")
def list_contracts():
    middleware.authorize(READ_ROLES)
    rows = db.all_rows("payer_contracts")
    rows = support.filter_rows(rows, "practice_id", payload.filter_value("practice_id"))
    rows = support.filter_rows(
        rows, "transition_state", payload.filter_value("transition_state")
    )
    return support.read_many("payer_contracts", rows)


@bp.post("/payer-contracts/<id>/fee-schedule-items")
@support.transactional
def create_fee_schedule_item(id):
    middleware.authorize([config.ROLE_FINANCE_CONTROLLER])
    contract = support.load("payer_contracts", id)
    data = payload.body()
    procedure_code = payload.string(data, "procedure_code")
    legacy_allowed_cents = payload.integer(data, "legacy_allowed_cents", minimum=0)
    dso_allowed_cents = payload.integer(data, "dso_allowed_cents", minimum=0)
    annual_volume = payload.integer(data, "annual_volume", minimum=0)
    if contract["transition_state"] not in ("LEGACY", "PENDING_CREDENTIALING"):
        raise ApiError(
            "ERR_INVALID_CONTRACT_STATE",
            "A contract already on the DSO schedule cannot be extended.",
        )
    for existing in derive.fee_items_of_contract(contract["id"]):
        if existing["procedure_code"] == procedure_code:
            raise ApiError(
                "ERR_DUPLICATE_PROCEDURE_CODE",
                "That procedure code already appears on this contract.",
            )
    row = db.insert(
        "fee_schedule_items",
        {
            "payer_contract_id": contract["id"],
            "procedure_code": procedure_code,
            "legacy_allowed_cents": legacy_allowed_cents,
            "dso_allowed_cents": dso_allowed_cents,
            "annual_volume": annual_volume,
            "line_impact_cents": calc.fee_line_impact(
                legacy_allowed_cents, dso_allowed_cents, annual_volume
            ),
        },
        versioned=False,
    )
    # The contract's blended impact and item count are recomputed; its version bumps.
    uow.touch(contract)
    return "fee_schedule_items", row, 201


@bp.get("/payer-contracts/<id>/fee-schedule-items")
def list_fee_schedule_items(id):
    middleware.authorize(READ_ROLES)
    contract = support.load("payer_contracts", id)
    rows = derive.fee_items_of_contract(contract["id"])
    return support.read_many("fee_schedule_items", rows)


@bp.post("/payer-contracts/<payer_contract_id>/activate-fee-schedule")
@support.transactional
def activate_fee_schedule(payer_contract_id):
    middleware.authorize([config.ROLE_FINANCE_CONTROLLER])
    contract = support.load("payer_contracts", payer_contract_id)
    data = payload.body()
    effective_date = payload.timestamp(data, "dso_schedule_effective_date")
    override_ack = payload.boolean(data, "erosion_override_ack", default=False)

    if contract["transition_state"] != "PENDING_CREDENTIALING":
        raise ApiError(
            "ERR_INVALID_CONTRACT_STATE",
            "The contract must be in PENDING_CREDENTIALING to activate.",
        )
    practice = db.get("practices", contract["practice_id"])
    support.require_affiliated(practice)
    support.require_posture(practice, ("STABILIZING", "INTEGRATED"))
    if derive.fee_schedule_item_count(contract) < 1:
        raise ApiError(
            "ERR_FEE_SCHEDULE_EMPTY", "The contract carries no fee schedule items."
        )
    enrollments = derive.enrollments_of_contract(contract["id"])
    if not enrollments or any(row["status"] != "APPROVED" for row in enrollments):
        raise ApiError(
            "ERR_ENROLLMENTS_NOT_APPROVED",
            "Every enrollment of the contract must be approved first.",
        )
    for row in enrollments:
        lead = derive.lead_days(row)
        if lead is None or lead < config.CREDENTIALING_LEAD_DAYS:
            raise ApiError(
                "ERR_CREDENTIALING_LEAD_TIME_SHORT",
                "An enrollment has fewer than %d whole days of credentialing lead time."
                % config.CREDENTIALING_LEAD_DAYS,
            )
    blended = derive.blended_impact_cents(contract)
    if calc.erosion_is_material(blended) and not override_ack:
        raise ApiError(
            "ERR_FEE_EROSION_MATERIAL",
            "Material reimbursement erosion requires an explicit acknowledgement.",
        )

    contract["transition_state"] = "DSO_SCHEDULE_ACTIVE"
    contract["dso_schedule_effective_date"] = effective_date
    contract["erosion_override_ack"] = override_ack
    uow.touch(contract)
    return "payer_contracts", contract, 200
