"""The credit and charge ledgers (PRD 3.11)."""

from flask import Blueprint

import auth
import constants as K
import envelope
import ledger
import listing
import lookup
import serialize
import shape
import store
import timeutil
from errors import ApiError

bp = Blueprint("ledgers", __name__)


@bp.get("/kidswear/credit-entries")
def list_credit_entries():
    caller = auth.gate("BillingAgent", "PlatformAdmin", "Member")
    rows = store.all_rows("credit_entries")
    rows = listing.scope_to_member(caller, rows, lambda r: r["member_id"])
    rows = listing.eq(rows, "member_id", shape.query_str("member_id"))
    rows = listing.eq(rows, "source_submission_id", shape.query_str("source_submission_id"))
    rows = listing.eq(rows, "status", shape.query_member("status", K.CREDIT_STATUSES))
    return envelope.listing(rows, serialize.credit_entry)


@bp.get("/kidswear/credit-entries/<credit_entry_id>")
def read_credit_entry(credit_entry_id):
    caller = auth.gate("BillingAgent", "PlatformAdmin", "Member")
    row = lookup.credit_entry(credit_entry_id)
    auth.own(caller, row["member_id"])
    return envelope.ok(serialize.credit_entry(row))


@bp.post("/kidswear/credit-entries/<credit_entry_id>/expire")
def expire_credit(credit_entry_id):
    auth.gate("BillingAgent")
    entry = lookup.credit_entry(credit_entry_id)
    if entry["status"] not in ("AVAILABLE", "PARTIALLY_APPLIED"):
        raise ApiError("ERR_INVALID_STATE")
    if timeutil.now() < entry["expires_at"]:
        raise ApiError("ERR_INVALID_STATE", "The entry's expiry instant has not passed.")
    entry["status"] = "EXPIRED"
    store.touch(entry)
    return envelope.ok(serialize.credit_entry(entry))


@bp.post("/kidswear/credit-entries/<credit_entry_id>/revoke")
def revoke_credit(credit_entry_id):
    auth.gate("BillingAgent")
    body = shape.body_json()
    revoke_reason = shape.string(body, "revoke_reason")
    entry = lookup.credit_entry(credit_entry_id)
    if entry["status"] not in ("AVAILABLE", "PARTIALLY_APPLIED"):
        raise ApiError("ERR_INVALID_STATE")
    entry["status"] = "REVOKED"
    entry["revoke_reason"] = revoke_reason
    store.touch(entry)
    return envelope.ok(serialize.credit_entry(entry))


@bp.get("/kidswear/charge-entries")
def list_charge_entries():
    caller = auth.gate("BillingAgent", "PlatformAdmin", "Member")
    rows = store.all_rows("charge_entries")
    rows = listing.scope_to_member(caller, rows, lambda r: r["member_id"])
    rows = listing.eq(rows, "member_id", shape.query_str("member_id"))
    rows = listing.eq(rows, "cycle_id", shape.query_str("cycle_id"))
    rows = listing.eq(rows, "charge_type", shape.query_member("charge_type", K.CHARGE_TYPES))
    rows = listing.eq(rows, "status", shape.query_member("status", K.CHARGE_STATUSES))
    return envelope.listing(rows, serialize.charge_entry)


@bp.get("/kidswear/charge-entries/<charge_entry_id>")
def read_charge_entry(charge_entry_id):
    caller = auth.gate("BillingAgent", "PlatformAdmin", "Member")
    row = lookup.charge_entry(charge_entry_id)
    auth.own(caller, row["member_id"])
    return envelope.ok(serialize.charge_entry(row))


@bp.post("/kidswear/charge-entries/<charge_entry_id>/waive")
def waive_charge(charge_entry_id):
    auth.gate("BillingAgent")
    body = shape.body_json()
    waive_reason = shape.string(body, "waive_reason")
    charge = lookup.charge_entry(charge_entry_id)
    member = lookup.member(charge["member_id"])
    if charge["status"] not in ("ASSESSED", "PARTIALLY_SETTLED"):
        raise ApiError("ERR_CHARGE_NOT_OPEN")
    ledger.waive_charge(charge, member, waive_reason)
    return envelope.ok(serialize.charge_entry(charge))
