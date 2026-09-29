"""EntrySubmission: importer identification transmitted at entry."""
from flask import Blueprint, g

import core
import serialize
from core import write_txn
from db import store
from errors import fail
from middleware import CO, EF, FDA, endpoint
from response import object_response
from routes._common import find, paged
from shapes import body, pagination, query_enum, query_str, req_dt, req_int, req_str

bp = Blueprint("entries", __name__)


@bp.post("/fsvp/entry-submissions")
@endpoint([EF])
def create_entry():
    b = body()
    pair_id = req_str(b, "pair_id")
    entry_number = req_str(b, "entry_number", minlen=6)
    entry_line_number = req_int(b, "entry_line_number", lo=1, hi=999)
    dnb_number_submitted = req_str(b, "dnb_number_submitted", minlen=1)
    ufi_submitted = req_str(b, "ufi_submitted", minlen=1)
    arrival_date = req_dt(b, "arrival_date")

    # rung 8
    pair = find("pair", pair_id, "ERR_PAIR_NOT_FOUND")

    # rung 15
    for row in store.entries.values():
        if row["entry_number"] == entry_number and row["entry_line_number"] == entry_line_number:
            fail("ERR_DUPLICATE_IDENTIFIER", "this entry line has already been filed")

    # rung 20
    if pair["entry_eligibility_status"] != "ELIGIBLE":
        fail("ERR_PAIR_ENTRY_BLOCKED", "the supplier-food combination is not eligible for entry")

    # rung 21
    if not (
        pair["verification_status"] == "VERIFICATION_APPROVED"
        or pair["exemption_status"] == "VERIFIED"
    ):
        fail(
            "ERR_PAIR_VERIFICATION_INCOMPLETE",
            "no compliance basis has been established for this combination",
        )

    supplier = core.supplier_of_pair(pair)

    # rung 27 — a pure (non-modified) verified exemption skips the supplier posture
    # check entirely; everything else rests on an approved supplier.
    pure_exemption = (
        pair["exemption_status"] == "VERIFIED"
        and not core.pair_modified_requirements_only(pair)
    )
    if not pure_exemption:
        if supplier is None or supplier["status"] not in ("APPROVED", "CONDITIONALLY_APPROVED"):
            fail("ERR_SUPPLIER_NOT_APPROVED", "the supplier is not approved")

    # rung 28
    if core.supplier_has_import_suspension(pair["supplier_id"]):
        fail("ERR_IMPORT_SUSPENSION_ACTIVE", "an import suspension is active on this supplier")

    # rung 46
    importer = core.importer_of_pair(pair)
    identifier_match = bool(
        importer is not None
        and dnb_number_submitted == importer["dnb_number"]
        and ufi_submitted == importer["unique_facility_identifier"]
    )
    if not identifier_match:
        fail(
            "ERR_IDENTIFIER_MISMATCH",
            "the transmitted DUNS number and UFI must match the importer of record",
        )

    with write_txn():
        row = store.new_row("entry")
        row.update(
            {
                "pair_id": pair_id,
                "entry_number": entry_number,
                "entry_line_number": entry_line_number,
                "dnb_number_submitted": dnb_number_submitted,
                "ufi_submitted": ufi_submitted,
                "arrival_date": arrival_date,
                "identifier_match": identifier_match,
                "filed_by_user_id": g.user_id,
                # SUBMITTED -> ACCEPTED auto-advance inside the same request
                "status": "ACCEPTED",
                "held_reason": None,
            }
        )
        store.insert(row)
    return object_response(serialize.entry_out(row), 201)


@bp.get("/fsvp/entry-submissions/<entry_id>")
@endpoint([CO, EF, FDA])
def read_entry(entry_id):
    row = find("entry", entry_id, "ERR_ENTRY_SUBMISSION_NOT_FOUND")
    return object_response(serialize.entry_out(row))


@bp.get("/fsvp/entry-submissions")
@endpoint([CO, EF, FDA])
def list_entries():
    pair_id = query_str("pair_id")
    status = query_enum("status", core.ENTRY_STATUSES)
    entry_number = query_str("entry_number")
    held_reason = query_enum("held_reason", core.HELD_REASONS)
    limit, offset = pagination()

    rows = list(store.entries.values())
    if pair_id is not None:
        rows = [r for r in rows if r["pair_id"] == pair_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if entry_number is not None:
        rows = [r for r in rows if r["entry_number"] == entry_number]
    if held_reason is not None:
        rows = [r for r in rows if r["held_reason"] == held_reason]
    return paged(rows, serialize.entry_out, limit, offset)
