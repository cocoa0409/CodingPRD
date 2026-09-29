"""Purchase agreements: signing, delivery, escrow, the asymmetric rescission
boundary, hardening and closing (PRD 3.8, closing gates from 3.9)."""

from flask import Blueprint

import clock
import envelope
import serializers
import store
import validation as v
from errors import ApiError
from services import cascades, projects as project_service, sales

bp = Blueprint("agreements", __name__)

SIGN_ROLES = ["ConverterSponsor", "Purchaser"]
SPONSOR = ["ConverterSponsor"]
READ_ROLES = ["ConverterSponsor", "EscrowAgent", "StateRegulator",
              "LenderUnderwriter", "Purchaser", "PlatformAdmin"]
HARDEN_ROLES = ["ConverterSponsor", "EscrowAgent"]
RESCIND_ROLES = ["Purchaser", "ConverterSponsor"]

PURCHASER_TYPES = ["OWNER_OCCUPANT", "INVESTOR"]


@bp.post("/units/<unit_id>/purchase-agreements")
def sign_agreement(unit_id):
    v.authorize(SIGN_ROLES)
    unit = v.get_unit(unit_id)
    project = v.get_project(unit["conversion_project_id"])
    body = v.raw_body()
    household = v.body_ref(body, "tenant_household_id", v.get_household)
    v.require_scope(project["id"], household)
    fields = v.parse([
        v.field("purchaser_name", "string", max_len=200),
        v.field("purchaser_tax_id", "string", max_len=100),
        v.field("purchaser_type", "enum", values=PURCHASER_TYPES),
        v.field("price_cents", "integer", minimum=1),
        v.field("deposit_cents", "integer", minimum=0),
        v.field("tenant_household_id", "id", required=False, default=None,
                nullable=True),
        v.field("expected_unit_version", "integer"),
    ])
    if fields["deposit_cents"] > fields["price_cents"]:
        raise ApiError("ERR_INVALID_REQUEST")
    v.require_version(fields["expected_unit_version"], unit,
                      "ERR_STALE_UNIT_VERSION")
    v.gate_not_frozen(project)
    v.require_state(unit, "declaration_status", ("INCLUDED",))
    statement = store.project_statement(project["id"])
    if statement is None or statement["status"] != "EFFECTIVE":
        raise ApiError("ERR_POS_NOT_EFFECTIVE")
    agreement = store.new_record(store.purchase_agreements, {
        "_type": "PurchaseAgreement",
        "unit_id": unit["id"],
        "conversion_project_id": project["id"],
        "public_offering_statement_id": statement["id"],
        "closing_batch_id": None,
        "tenant_household_id": fields["tenant_household_id"],
        "purchaser_name": fields["purchaser_name"],
        "purchaser_tax_id": fields["purchaser_tax_id"],
        "purchaser_type": fields["purchaser_type"],
        "price_cents": fields["price_cents"],
        "deposit_cents": fields["deposit_cents"],
        "signed_at": clock.now(),
        "pos_delivered_at": None,
        "rescission_deadline_at": None,
        "rescission_restart_count": 0,
        "contract_status": "SIGNED",
        "escrow_status": "PENDING",
        "closed_at": None,
        "rescission_reason": None,
    })
    sales.derive_unit_sale_status(unit)
    store.touch(unit)
    sales.recompute_warrantability(project, "contract")
    return envelope.object_response(serializers.dump(agreement), 201)


@bp.get("/units/<unit_id>/purchase-agreements")
def list_unit_agreements(unit_id):
    v.authorize(READ_ROLES)
    unit = v.get_unit(unit_id)
    limit, offset = v.pagination()
    records = [
        a for a in store.unit_agreements(unit["id"])
        if v.matches(a,
                     contract_status=v.filter_value("contract_status"),
                     escrow_status=v.filter_value("escrow_status"))]
    window, page = envelope.paginate(records, limit, offset)
    return envelope.array_response(serializers.dump_all(window), 200, page)


@bp.get("/purchase-agreements")
def list_agreements():
    v.authorize(READ_ROLES)
    limit, offset = v.pagination()
    records = [
        a for a in store.ordered(store.purchase_agreements.values())
        if v.matches(
            a,
            conversion_project_id=v.filter_value("conversion_project_id"),
            unit_id=v.filter_value("unit_id"),
            public_offering_statement_id=v.filter_value(
                "public_offering_statement_id"),
            closing_batch_id=v.filter_value("closing_batch_id"),
            tenant_household_id=v.filter_value("tenant_household_id"),
            purchaser_type=v.filter_value("purchaser_type"),
            contract_status=v.filter_value("contract_status"),
            escrow_status=v.filter_value("escrow_status"))]
    window, page = envelope.paginate(records, limit, offset)
    return envelope.array_response(serializers.dump_all(window), 200, page)


@bp.get("/purchase-agreements/<agreement_id>")
def get_agreement(agreement_id):
    user_id, role = v.authorize(READ_ROLES)
    # A purchaser is bound to its own agreement, never another purchaser's.
    v.require_identity(user_id, role, "Purchaser", agreement_id)
    agreement = v.get_agreement(agreement_id)
    return envelope.object_response(serializers.dump(agreement), 200)


@bp.patch("/purchase-agreements/<agreement_id>")
def patch_agreement(agreement_id):
    v.authorize(SPONSOR)
    agreement = v.get_agreement(agreement_id)
    project = v.get_project(agreement["conversion_project_id"])
    body = v.parse([
        v.field("purchaser_name", "string", required=False, max_len=200),
        v.field("purchaser_tax_id", "string", required=False, max_len=100),
        v.field("purchaser_type", "enum", required=False,
                values=PURCHASER_TYPES),
        v.field("price_cents", "integer", required=False, minimum=1),
        v.field("deposit_cents", "integer", required=False, minimum=0),
    ])
    v.gate_not_frozen(project)
    v.require_state(agreement, "contract_status", ("SIGNED",))
    v.require_state(agreement, "escrow_status", ("PENDING",))
    price = body.get("price_cents", agreement["price_cents"])
    deposit = body.get("deposit_cents", agreement["deposit_cents"])
    if deposit > price:
        raise ApiError("ERR_INVALID_REQUEST")
    for name, value in body.items():
        agreement[name] = value
    store.touch(agreement)
    # Changing purchaser_type never restarts an already-computed deadline.
    sales.recompute_warrantability(project, "contract")
    return envelope.object_response(serializers.dump(agreement), 200)


@bp.post("/purchase-agreements/<agreement_id>/pos-deliveries")
def deliver_statement(agreement_id):
    v.authorize(SPONSOR)
    agreement = v.get_agreement(agreement_id)
    project = v.get_project(agreement["conversion_project_id"])
    v.gate_not_frozen(project)
    v.require_state(agreement, "contract_status", ("SIGNED",))
    statement = store.project_statement(project["id"])
    if statement is None or statement["status"] != "EFFECTIVE":
        raise ApiError("ERR_POS_NOT_EFFECTIVE")
    delivered_at = clock.now()
    agreement["pos_delivered_at"] = delivered_at
    agreement["rescission_deadline_at"] = clock.plus_seconds(
        delivered_at,
        sales.rescission_window_seconds(agreement["purchaser_type"]))
    store.touch(agreement)
    return envelope.object_response(serializers.dump(agreement), 201)


@bp.post("/purchase-agreements/<agreement_id>/escrow-deposits")
def fund_escrow(agreement_id):
    v.authorize(["EscrowAgent"])
    agreement = v.get_agreement(agreement_id)
    project = v.get_project(agreement["conversion_project_id"])
    body = v.parse([v.field("amount_cents", "integer", minimum=0)])
    v.gate_not_frozen(project)
    v.require_state(agreement, "contract_status", ("SIGNED",))
    v.require_state(agreement, "escrow_status", ("PENDING",))
    if body["amount_cents"] != agreement["deposit_cents"]:
        raise ApiError("ERR_ESCROW_AMOUNT_MISMATCH")
    agreement["escrow_status"] = "FUNDED"
    store.touch(agreement)
    # The received total is the monotonic bucket; `sync` derives the rest.
    project["escrow_deposits_received_cents"] += agreement["deposit_cents"]
    store.touch(project)
    project_service.sync(project)
    batch = store.closing_batches.get(agreement["closing_batch_id"])
    if batch is not None:
        sales.write_batch_counters(batch, project)
    project_service.recompute_posture(project)
    return envelope.object_response(serializers.dump(agreement), 201)


@bp.post("/purchase-agreements/<agreement_id>/hardening")
def harden_agreement(agreement_id):
    v.authorize(HARDEN_ROLES)
    agreement = v.get_agreement(agreement_id)
    project = v.get_project(agreement["conversion_project_id"])
    v.gate_not_frozen(project)
    v.require_state(agreement, "contract_status", ("SIGNED",))
    if agreement["pos_delivered_at"] is None:
        raise ApiError("ERR_POS_NOT_DELIVERED")
    # Hardening is admissible at or after the deadline instant, inclusively.
    if clock.now() < agreement["rescission_deadline_at"]:
        raise ApiError("ERR_RESCISSION_PERIOD_OPEN")
    if agreement["escrow_status"] != "FUNDED":
        raise ApiError("ERR_ESCROW_NOT_FUNDED")
    agreement["contract_status"] = "HARD"
    store.touch(agreement)
    unit = store.units.get(agreement["unit_id"])
    if unit is not None:
        sales.derive_unit_sale_status(unit)
    batch = store.closing_batches.get(agreement["closing_batch_id"])
    if batch is not None:
        sales.write_batch_counters(batch, project)
        cascades.promote_batch(batch, project)
    sales.recompute_warrantability(project, "contract")
    project_service.sync(project)
    project_service.recompute_posture(project)
    return envelope.object_response(serializers.dump(agreement), 200)


@bp.post("/purchase-agreements/<agreement_id>/rescission")
def rescind(agreement_id):
    user_id, role = v.authorize(RESCIND_ROLES)
    v.require_identity(user_id, role, "Purchaser", agreement_id)
    agreement = v.get_agreement(agreement_id)
    project = v.get_project(agreement["conversion_project_id"])
    body = v.parse([v.field("rescission_reason", "string", required=False,
                            default=None, max_len=500)])
    v.gate_not_frozen(project)
    v.require_state(agreement, "contract_status", ("SIGNED",))
    if agreement["pos_delivered_at"] is None:
        raise ApiError("ERR_POS_NOT_DELIVERED")
    # Rescission is admissible strictly before the deadline instant.
    if clock.now() >= agreement["rescission_deadline_at"]:
        raise ApiError("ERR_RESCISSION_PERIOD_CLOSED")
    cascades.rescind_agreement(agreement, project, body["rescission_reason"])
    return envelope.object_response(serializers.dump(agreement), 200)


@bp.post("/purchase-agreements/<agreement_id>/closing")
def close_agreement(agreement_id):
    v.authorize(["EscrowAgent"])
    agreement = v.get_agreement(agreement_id)
    project = v.get_project(agreement["conversion_project_id"])
    v.gate_not_frozen(project)
    v.require_state(agreement, "contract_status", ("HARD",))
    batch = store.closing_batches.get(agreement["closing_batch_id"])
    if batch is None or batch["status"] != "RELEASED":
        raise ApiError("ERR_BATCH_NOT_RELEASED")
    now = clock.now()
    # The settlement window is half-open: the end instant is outside it.
    if now < batch["window_start_at"] or now >= batch["window_end_at"]:
        raise ApiError("ERR_BATCH_NOT_RELEASED")
    if agreement["escrow_status"] != "FUNDED":
        raise ApiError("ERR_ESCROW_NOT_FUNDED")
    package = store.project_package(project["id"])
    if package is None or package["status"] != "RECORDED":
        raise ApiError("ERR_DECLARATION_NOT_RECORDED")
    agreement["contract_status"] = "CLOSED"
    agreement["escrow_status"] = "DISBURSED"
    agreement["closed_at"] = now
    store.touch(agreement)
    unit = store.units.get(agreement["unit_id"])
    if unit is not None:
        sales.derive_unit_sale_status(unit)
    project_service.sync(project)
    sales.recompute_warrantability(project, "closed")
    cascades.complete_project_if_all_sold(project)
    project_service.recompute_posture(project)
    return envelope.object_response(serializers.dump(agreement), 200)
