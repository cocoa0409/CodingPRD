"""The inmate trust account: co-pay charges and the append-only ledger."""

from flask import Blueprint, request

import money
import serializers
import store
from constants import CHARGE_ENCOUNTER_TYPES, ENTRY_TYPE
from envelope import created, listing, ok, page_params
from errors import ApiError
from ladder import Ctx

bp = Blueprint("trust", __name__)


@bp.post("/inmates/<inmate_id>/copay-charges")
def post_charge(inmate_id):
    ctx = Ctx(roles=("HealthServicesAdmin",))
    ctx.path_inmate(inmate_id)
    ctx.need_body_ref("sick_call", store.sick_calls, "source_sick_call_id", "ERR_RECORD_NOT_FOUND")
    ctx.freeze_gate()
    ctx.require("encounter_type")
    ctx.check_type("source_sick_call_id", "string")
    ctx.enum("encounter_type", CHARGE_ENCOUNTER_TYPES)
    ctx.run()

    charge, entry = money.post_copay_charge(
        ctx.inmate, ctx.body["encounter_type"],
        source_sick_call_id=ctx.body.get("source_sick_call_id"))
    if entry is not None:
        store.touch(ctx.inmate)
    return created(serializers.copay_charge(charge))


@bp.get("/copay-charges")
def list_charges():
    ctx = Ctx(roles=("HealthServicesAdmin", "GrievanceCoordinator", "Inmate"))
    ctx.run()

    limit, offset = page_params(request.args)
    rows = list(store.copay_charges.values())
    if ctx.is_inmate_actor:
        rows = [c for c in rows if c["inmate_id"] == ctx.user_id]
    for field in ("inmate_id", "source_sick_call_id", "reversal_grievance_id",
                  "status", "charge_variant"):
        wanted = request.args.get(field)
        if wanted:
            rows = [c for c in rows if c.get(field) == wanted]
    rows = store.sort_rows(rows)
    return listing(serializers.many(serializers.copay_charge, rows), limit, offset)


@bp.get("/copay-charges/<charge_id>")
def read_charge(charge_id):
    ctx = Ctx(roles=("HealthServicesAdmin", "GrievanceCoordinator", "Inmate"))
    ctx.own_id(lambda: (store.copay_charges[charge_id]["inmate_id"]
                        if charge_id in store.copay_charges else None))
    ctx.need("charge", store.copay_charges, charge_id, "ERR_RECORD_NOT_FOUND")
    ctx.run()
    return ok(serializers.copay_charge(ctx.row("charge")))


@bp.post("/inmates/<inmate_id>/ledger-entries")
def post_deposit(inmate_id):
    # Deliberately NOT freeze-gated: PRD 2.6 exempts trust-account deposits.
    ctx = Ctx(roles=("HealthServicesAdmin",))
    ctx.path_inmate(inmate_id)
    ctx.require("entry_type", "amount_cents")
    ctx.check_type("amount_cents", "integer")
    ctx.check_type("memo", "string")
    ctx.enum("entry_type", ENTRY_TYPE)

    def deposit_only():
        if ctx.body.get("entry_type") != "DEPOSIT":
            raise ApiError("ERR_VALIDATION",
                           "only DEPOSIT entries may be posted on this path")
    ctx.at(8, deposit_only, sub=3)
    ctx.run()

    entry = money.append_entry(ctx.inmate, "DEPOSIT", ctx.body["amount_cents"],
                               memo=ctx.body.get("memo") or "")
    store.touch(ctx.inmate)
    return created(serializers.ledger_entry(entry))


@bp.get("/ledger-entries")
def list_entries():
    ctx = Ctx(roles=("HealthServicesAdmin", "GrievanceCoordinator", "Inmate"))
    ctx.run()

    limit, offset = page_params(request.args)
    rows = list(store.ledger_entries.values())
    if ctx.is_inmate_actor:
        rows = [e for e in rows if e["inmate_id"] == ctx.user_id]
    for field in ("inmate_id", "source_copay_charge_id", "entry_type"):
        wanted = request.args.get(field)
        if wanted:
            rows = [e for e in rows if e.get(field) == wanted]
    rows = store.sort_rows(rows)
    return listing(serializers.many(serializers.ledger_entry, rows), limit, offset)


@bp.get("/ledger-entries/<entry_id>")
def read_entry(entry_id):
    ctx = Ctx(roles=("HealthServicesAdmin", "GrievanceCoordinator", "Inmate"))
    ctx.own_id(lambda: (store.ledger_entries[entry_id]["inmate_id"]
                        if entry_id in store.ledger_entries else None))
    ctx.need("entry", store.ledger_entries, entry_id, "ERR_RECORD_NOT_FOUND")
    ctx.run()
    return ok(serializers.ledger_entry(ctx.row("entry")))
