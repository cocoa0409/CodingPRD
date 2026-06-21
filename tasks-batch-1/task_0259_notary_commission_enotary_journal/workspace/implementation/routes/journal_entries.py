"""JournalEntry routes (PRD §3.7)."""
from flask import Blueprint, request

from db import store, new_common_fields, touch
from domain import (
    find_entry, find_notary, audit, recompute_lifetime_fees, fee_schedule_for,
    ACT_TYPES, ID_METHODS,
)
from errors import err
from middleware import endpoint
from response import success, list_response
from serialize import view, view_list
from validation import (
    get_body, require_str, require_int, require_enum, non_negative_cents,
    parse_pagination, paginate,
)

bp = Blueprint("journal_entries", __name__)


@bp.post("/journal-entries")
@endpoint(("Notary",))
def create_entry():
    body = get_body()
    notary_id = require_str(body, "notary_id")
    act_type = require_enum(body, "act_type", ACT_TYPES)
    signer_name = require_str(body, "signer_name")
    id_method = require_enum(body, "id_method", ID_METHODS)
    fee = require_int(body, "fee_charged_cents")

    notary = find_notary(notary_id)
    non_negative_cents(fee, "fee_charged_cents")

    # Fee-cap enforcement against the FeeSchedule for (notary jurisdiction, act).
    sched = fee_schedule_for(notary["jurisdiction_id"], act_type)
    if sched is not None and fee > sched["max_act_fee_cents"]:
        raise err("ERR_FEE_EXCEEDS_CAP", "Fee exceeds statutory cap")

    rec = dict(new_common_fields())
    rec.update({
        "notary_id": notary_id,
        "session_id": None,
        "document_id": None,
        "act_type": act_type,
        "signer_name": signer_name,
        "id_method": id_method,
        "fee_charged_cents": fee,
        "status": "POSTED",
        "amends_entry_id": None,
    })
    store.journal_entries[rec["id"]] = rec
    recompute_lifetime_fees(notary)
    touch(notary)
    audit(notary_id, "JOURNAL_ENTRY", rec["id"], "JOURNAL_ENTRY_POSTED", "NOTARY",
          "Journal entry posted")
    return success(view(rec), status=201)


@bp.get("/journal-entries/<entry_id>")
@endpoint(("CommissionAuthority", "Notary"))
def get_entry(entry_id):
    return success(view(find_entry(entry_id)))


@bp.get("/journal-entries")
@endpoint(("CommissionAuthority", "Notary"))
def list_entries():
    limit, offset = parse_pagination()
    recs = list(store.journal_entries.values())
    for key in ("notary_id", "session_id", "document_id", "amends_entry_id", "status"):
        val = request.args.get(key)
        if val is not None:
            recs = [r for r in recs if r.get(key) == val]
    page, total = paginate(recs, limit, offset)
    return list_response(view_list(page), limit, offset, total)


@bp.post("/journal-entries/<entry_id>/amend")
@endpoint(("Notary",))
def amend_entry(entry_id):
    entry = find_entry(entry_id)
    body = get_body()
    signer_name = require_str(body, "signer_name")
    fee = require_int(body, "fee_charged_cents")
    non_negative_cents(fee, "fee_charged_cents")

    if entry["status"] != "POSTED":
        raise err("ERR_ENTRY_NOT_POSTED", "Entry is not POSTED")
    notary = store.notaries.get(entry["notary_id"])
    if notary is None or notary["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", "Performing notary not ACTIVE or SUSPENDED")

    # Original -> AMENDED; new POSTED correction entry pointing back.
    entry["status"] = "AMENDED"
    touch(entry)
    correction = dict(new_common_fields())
    correction.update({
        "notary_id": entry["notary_id"],
        "session_id": entry.get("session_id"),
        "document_id": entry.get("document_id"),
        "act_type": entry["act_type"],
        "signer_name": signer_name,
        "id_method": entry.get("id_method"),
        "fee_charged_cents": fee,
        "status": "POSTED",
        "amends_entry_id": entry["id"],
    })
    store.journal_entries[correction["id"]] = correction
    recompute_lifetime_fees(notary)
    touch(notary)
    audit(entry["notary_id"], "JOURNAL_ENTRY", entry["id"], "JOURNAL_ENTRY_AMENDED",
          "NOTARY", "Journal entry amended")
    # Return the correction (new) entry per amend semantics.
    return success(view(correction))


@bp.post("/journal-entries/<entry_id>/void")
@endpoint(("CommissionAuthority",))
def void_entry(entry_id):
    entry = find_entry(entry_id)
    if entry["status"] != "POSTED":
        raise err("ERR_ENTRY_NOT_POSTED", "Entry is not POSTED")
    entry["status"] = "VOID"
    touch(entry)
    notary = store.notaries.get(entry["notary_id"])
    if notary is not None:
        recompute_lifetime_fees(notary)
        touch(notary)
    audit(entry["notary_id"], "JOURNAL_ENTRY", entry["id"], "JOURNAL_ENTRY_VOIDED",
          "COMMISSION_AUTHORITY", "Journal entry voided")
    return success(view(entry))
