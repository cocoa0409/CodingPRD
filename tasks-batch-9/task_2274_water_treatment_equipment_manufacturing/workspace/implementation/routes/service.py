"""Service agreements, the consumable reserve and draw reversals."""
from datetime import timedelta

from flask import Blueprint

import auth
import calc
import clock
import constants as C
import db
import domain
import response
import serialize
import validate
from errors import fail
from util import format_dt

bp = Blueprint("service", __name__)


# ---------------------------------------------------------------- agreements --

@bp.post("/projects/<project_id>/service-agreements")
def create_agreement(project_id):
    auth.require("ContractsAdministrator")
    project = domain.project(project_id)
    body = validate.body()
    term_months = validate.integer(body, "term_months", minimum=12)
    annual_fee = validate.integer(body, "annual_fee_cents", exclusive_minimum=0)
    reserve_funded = validate.integer(
        body, "reserve_funded_cents", exclusive_minimum=0)
    membrane_installed_at = validate.instant(body, "membrane_installed_at")

    if project["status"] not in ("GUARANTEED", "SERVICE_ACTIVE"):
        fail("ERR_INVALID_PROJECT_STATE",
             "a service agreement requires the project to be GUARANTEED or "
             "SERVICE_ACTIVE")
    for field in ("om_manual_status", "operator_training_status",
                  "spare_parts_list_status"):
        if project[field] != "ACCEPTED":
            fail("ERR_DELIVERABLES_INCOMPLETE",
                 "every closeout deliverable must be ACCEPTED first")

    row = db.new_row("service_agreements")
    row.update({
        "project_id": project["id"],
        "term_months": term_months,
        "annual_fee_cents": annual_fee,
        "reserve_funded_cents": reserve_funded,
        "membrane_installed_at": format_dt(membrane_installed_at),
        "reserve_committed_accrual_cents": 0,
        "reserve_committed_settled_cents": 0,
        "reserve_available_cents": 0,
        "settlement_variance_cents": 0,
        "status": "PENDING_ACTIVATION",
        "activated_at": None,
        "expires_at": None,
    })
    db.insert("service_agreements", row)

    if project["status"] == "GUARANTEED":
        activated_at = clock.now()
        row["status"] = "ACTIVE"
        row["activated_at"] = format_dt(activated_at)
        row["expires_at"] = format_dt(
            activated_at + timedelta(days=30 * term_months))
        row["reserve_available_cents"] = reserve_funded
        project["status"] = "SERVICE_ACTIVE"

    db.touch(project)
    return response.created(serialize.row(row))


@bp.get("/projects/<project_id>/service-agreements")
def list_project_agreements(project_id):
    auth.require(*auth.ROLES)
    project = domain.project(project_id)
    status = validate.enum_filter("status", C.AGREEMENT_STATUSES)
    rows = [r for r in db.all_rows("service_agreements")
            if r["project_id"] == project["id"]]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = db.sorted_rows(rows, [("created_at", "asc")])
    return response.paginate(rows, serialize.row)


@bp.get("/service-agreements")
def list_agreements():
    auth.require(*auth.ROLES)
    project_id = validate.string_filter("project_id")
    status = validate.enum_filter("status", C.AGREEMENT_STATUSES)
    rows = db.all_rows("service_agreements")
    if project_id:
        rows = [r for r in rows if r["project_id"] == project_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = db.sorted_rows(rows, [("created_at", "asc")])
    return response.paginate(rows, serialize.row)


@bp.get("/service-agreements/<agreement_id>")
def get_agreement(agreement_id):
    auth.require(*auth.ROLES)
    return response.ok(serialize.row(domain.agreement(agreement_id)))


# --------------------------------------------------------------------- draws --

@bp.post("/service-agreements/<agreement_id>/consumable-draws")
def post_draw(agreement_id):
    actor = auth.require("ContractsAdministrator")
    agreement = domain.agreement(agreement_id)
    body = validate.body()
    draw_type = validate.enum(body, "draw_type", C.DRAW_TYPE_INPUTS)
    item_code = validate.string(body, "item_code", max_length=80)
    quantity = validate.integer(body, "quantity")
    catalog_unit_cost = validate.integer(
        body, "catalog_unit_cost_cents", exclusive_minimum=0)
    invoiced_unit_cost = validate.integer(
        body, "invoiced_unit_cost_cents", exclusive_minimum=0)
    expected_version = validate.integer(
        body, "expected_service_agreement_version", minimum=0)

    domain.check_version(agreement, expected_version, "ERR_STALE_AGREEMENT_VERSION")

    if domain.sweep_agreement_expiry(agreement) or agreement["status"] == "EXPIRED":
        fail("ERR_AGREEMENT_EXPIRED", "the service agreement has expired")
    if agreement["status"] != "ACTIVE":
        fail("ERR_AGREEMENT_NOT_ACTIVE", "the service agreement accepts no draw")

    if quantity < 1:
        fail("ERR_INVALID_DRAW_QUANTITY", "quantity must be an integer of at least 1")

    accrual, settled, warranty_credit = calc.draw_amounts(
        agreement, draw_type, quantity, catalog_unit_cost, invoiced_unit_cost)

    if accrual > int(agreement["reserve_available_cents"]):
        fail("ERR_RESERVE_INSUFFICIENT",
             "the accrual line exceeds the available reserve")

    row = db.new_row("consumable_draws", common_fields=False)
    row.update({
        "service_agreement_id": agreement["id"],
        "reverses_draw_id": None,
        "draw_type": draw_type,
        "item_code": item_code,
        "quantity": quantity,
        "catalog_unit_cost_cents": catalog_unit_cost,
        "invoiced_unit_cost_cents": invoiced_unit_cost,
        "accrual_amount_cents": accrual,
        "settled_amount_cents": settled,
        "warranty_credit_cents": warranty_credit,
        "posted_by_user_id": actor,
    })
    db.insert("consumable_draws", row)

    calc.recompute_reserve(agreement)
    if (agreement["status"] == "ACTIVE"
            and int(agreement["reserve_available_cents"]) == 0):
        agreement["status"] = "SUSPENDED"
    db.touch(agreement)

    return response.created(serialize.row(row))


@bp.get("/consumable-draws")
def list_draws():
    auth.require(*auth.ROLES)
    agreement_id = validate.string_filter("service_agreement_id")
    reverses_draw_id = validate.string_filter("reverses_draw_id")
    draw_type = validate.enum_filter("draw_type", C.DRAW_TYPES)
    rows = db.all_rows("consumable_draws")
    if agreement_id:
        rows = [r for r in rows if r["service_agreement_id"] == agreement_id]
    if reverses_draw_id:
        rows = [r for r in rows if r["reverses_draw_id"] == reverses_draw_id]
    if draw_type:
        rows = [r for r in rows if r["draw_type"] == draw_type]
    rows = db.sorted_rows(rows, [("created_at", "asc")])
    return response.paginate(rows, serialize.row)


@bp.get("/consumable-draws/<draw_id>")
def get_draw(draw_id):
    auth.require(*auth.ROLES)
    return response.ok(serialize.row(domain.draw(draw_id)))


@bp.post("/consumable-draws/<draw_id>/reversal")
def reverse_draw(draw_id):
    actor = auth.require("ContractsAdministrator")
    target = domain.draw(draw_id)
    body = validate.body()
    validate.string(body, "reversal_reason", required=False, default=None,
                    max_length=2000, allow_blank=True)

    agreement = db.get("service_agreements", target["service_agreement_id"])
    if agreement is not None:
        if domain.sweep_agreement_expiry(agreement) or agreement["status"] == "EXPIRED":
            fail("ERR_AGREEMENT_EXPIRED", "the service agreement has expired")

    if target["draw_type"] == "REVERSAL":
        fail("ERR_DRAW_ALREADY_REVERSED", "a reversal cannot itself be reversed")
    for existing in db.all_rows("consumable_draws"):
        if existing["reverses_draw_id"] == target["id"]:
            fail("ERR_DRAW_ALREADY_REVERSED", "the draw has already been reversed")

    row = db.new_row("consumable_draws", common_fields=False)
    row.update({
        "service_agreement_id": target["service_agreement_id"],
        "reverses_draw_id": target["id"],
        "draw_type": "REVERSAL",
        "item_code": target["item_code"],
        "quantity": target["quantity"],
        "catalog_unit_cost_cents": target["catalog_unit_cost_cents"],
        "invoiced_unit_cost_cents": target["invoiced_unit_cost_cents"],
        "accrual_amount_cents": -int(target["accrual_amount_cents"]),
        "settled_amount_cents": -int(target["settled_amount_cents"]),
        "warranty_credit_cents": 0,
        "posted_by_user_id": actor,
    })
    db.insert("consumable_draws", row)

    if agreement is not None:
        calc.recompute_reserve(agreement)
        if (agreement["status"] == "SUSPENDED"
                and int(agreement["reserve_available_cents"]) > 0):
            agreement["status"] = "ACTIVE"
        db.touch(agreement)

    return response.created(serialize.row(row))
