"""Sample custody: pre-advice, receipt, style matching, custody moves, return
and loss write-off."""
from datetime import timedelta

from flask import Blueprint

from core import (
    CUSTODY_STATES, MATCH_STATES, authorize, by_created, created, db, fail,
    get_body, new_row, now, ok, ok_list, page_params, paginate, qenum, qstr,
    touch, venum, vstr,
)
from cascade import cascade_sample_lost
from logic import find, return_days_late, vendor_strike
from serialize import sample_out

bp = Blueprint("samples", __name__)

UPPER_NUM = r"^[A-Z0-9]+\Z"
UPPER_NUM_DASH = r"^[A-Z0-9\-]+\Z"

TERMINAL_CUSTODY = ("RETURNED", "LOST")
LOSSABLE = ("RECEIVED", "IN_STUDIO", "ON_SET", "RETURN_PENDING")

# Declared custody transitions of the custody-move action.
CUSTODY_MOVES = {
    ("RECEIVED", "IN_STUDIO"),
    ("IN_STUDIO", "ON_SET"),
    ("ON_SET", "IN_STUDIO"),
    ("RECEIVED", "RETURN_PENDING"),
    ("IN_STUDIO", "RETURN_PENDING"),
    ("ON_SET", "RETURN_PENDING"),
}
# Moves into production require an identified box.
MOVES_REQUIRING_MATCH = {("RECEIVED", "IN_STUDIO"), ("IN_STUDIO", "ON_SET")}


@bp.post("/samples")
def create_sample():
    authorize("SampleCoordinator")
    body = get_body()
    barcode = vstr(body, "barcode", minlen=4, maxlen=24, pattern=UPPER_NUM_DASH)
    vendor_id = vstr(body, "vendor_id", minlen=1)
    declared_style_number = vstr(body, "declared_style_number", minlen=4, maxlen=16,
                                 pattern=UPPER_NUM)

    vendor = find(db.vendors, vendor_id, "ERR_REFERENCE_NOT_FOUND")

    if any(s["barcode"] == barcode for s in db.samples.values()):
        fail("ERR_DUPLICATE_CODE", "barcode '%s' already exists." % barcode)

    row = new_row({
        "barcode": barcode,
        "vendor_id": vendor["id"],
        "declared_style_number": declared_style_number,
        "matched_style_id": None,
        "custody_state": "EXPECTED",
        "match_state": "UNMATCHED",
        "received_at": None,
        "due_return_at": None,
        "returned_at": None,
        "return_days_late": 0,
        "condition_note": None,
    })
    db.samples[row["id"]] = row
    return created(sample_out(row))


@bp.post("/samples/<sample_id>/receive")
def receive_sample(sample_id):
    authorize("SampleCoordinator")
    sample = find(db.samples, sample_id, "ERR_SAMPLE_NOT_FOUND")
    if sample["custody_state"] != "EXPECTED":
        fail("ERR_SAMPLE_INVALID_CUSTODY",
             "A sample may only be received while EXPECTED.")
    vendor = db.vendors.get(sample["vendor_id"])
    if vendor is not None and vendor.get("coordination_hold"):
        fail("ERR_VENDOR_COORDINATION_HOLD")

    sample["custody_state"] = "RECEIVED"
    sample["received_at"] = now()
    sla_days = vendor["sample_sla_days"] if vendor else 14
    sample["due_return_at"] = sample["received_at"] + timedelta(days=sla_days)
    touch(sample)
    if vendor is not None:
        vendor["outstanding_sample_count"] = vendor.get("outstanding_sample_count", 0) + 1
        touch(vendor)
    return ok(sample_out(sample))


@bp.post("/samples/<sample_id>/match")
def match_sample(sample_id):
    authorize("SampleCoordinator")
    body = get_body()
    style_id = vstr(body, "style_id", minlen=1)
    resolution = venum(body, "mismatch_resolution", ["HOLD", "ACCEPT_SUBSTITUTE"],
                       required=False, default=None)

    sample = find(db.samples, sample_id, "ERR_SAMPLE_NOT_FOUND")
    style = find(db.styles, style_id, "ERR_STYLE_NOT_FOUND")

    if sample["custody_state"] in TERMINAL_CUSTODY:
        fail("ERR_SAMPLE_INVALID_CUSTODY",
             "A returned or lost sample can no longer be reconciled.")

    numbers_agree = style["style_number"] == sample["declared_style_number"]
    if numbers_agree or resolution == "ACCEPT_SUBSTITUTE":
        sample["match_state"] = "MATCHED"
        sample["matched_style_id"] = style["id"]
    elif resolution == "HOLD":
        sample["match_state"] = "MISMATCH_HOLD"
        sample["matched_style_id"] = None
    else:
        fail("ERR_STYLE_NUMBER_MISMATCH",
             "declared_style_number '%s' does not match style_number '%s'."
             % (sample["declared_style_number"], style["style_number"]))
    touch(sample)
    return ok(sample_out(sample))


@bp.post("/samples/<sample_id>/custody-move")
def move_sample(sample_id):
    authorize("SampleCoordinator")
    body = get_body()
    to_state = venum(body, "to_state", CUSTODY_STATES)

    sample = find(db.samples, sample_id, "ERR_SAMPLE_NOT_FOUND")
    pair = (sample["custody_state"], to_state)
    if pair not in CUSTODY_MOVES:
        fail("ERR_SAMPLE_INVALID_CUSTODY",
             "%s -> %s is not a declared custody move." % pair)
    if pair in MOVES_REQUIRING_MATCH and sample["match_state"] != "MATCHED":
        fail("ERR_SAMPLE_NOT_MATCHED")

    sample["custody_state"] = to_state
    touch(sample)

    if pair == ("RECEIVED", "IN_STUDIO"):
        style = db.styles.get(sample.get("matched_style_id"))
        if style is not None and style["content_state"] in ("NOT_STARTED", "BLOCKED"):
            style["content_state"] = "SAMPLE_READY"
            touch(style)
    return ok(sample_out(sample))


@bp.post("/samples/<sample_id>/return")
def return_sample(sample_id):
    authorize("SampleCoordinator")
    body = get_body()
    condition_note = vstr(body, "condition_note", required=False, default=None,
                          maxlen=2000)

    sample = find(db.samples, sample_id, "ERR_SAMPLE_NOT_FOUND")
    if sample["custody_state"] != "RETURN_PENDING":
        fail("ERR_SAMPLE_INVALID_CUSTODY",
             "A sample may only be returned from RETURN_PENDING.")

    sample["custody_state"] = "RETURNED"
    sample["returned_at"] = now()
    if condition_note is not None:
        sample["condition_note"] = condition_note
    sample["return_days_late"] = return_days_late(sample["due_return_at"],
                                                  sample["returned_at"])
    touch(sample)

    vendor = db.vendors.get(sample["vendor_id"])
    if vendor is not None:
        vendor["outstanding_sample_count"] = max(
            0, vendor.get("outstanding_sample_count", 0) - 1)
        if sample["return_days_late"] > 0:
            vendor_strike(vendor)
        touch(vendor)
    return ok(sample_out(sample))


@bp.post("/samples/<sample_id>/report-lost")
def report_sample_lost(sample_id):
    authorize("SampleCoordinator")
    body = get_body()
    vstr(body, "reason", required=False, default=None, maxlen=2000)

    sample = find(db.samples, sample_id, "ERR_SAMPLE_NOT_FOUND")
    if sample["custody_state"] not in LOSSABLE:
        fail("ERR_SAMPLE_INVALID_CUSTODY",
             "Only a sample in studio custody can be written off as lost.")

    # match_state is deliberately left exactly as it was.
    sample["custody_state"] = "LOST"
    touch(sample)
    cascade_sample_lost(sample)
    return ok(sample_out(sample))


@bp.get("/samples/<sample_id>")
def read_sample(sample_id):
    authorize("StudioAdmin", "SampleCoordinator", "Producer")
    row = find(db.samples, sample_id, "ERR_SAMPLE_NOT_FOUND")
    return ok(sample_out(row))


@bp.get("/samples")
def list_samples():
    authorize("StudioAdmin", "SampleCoordinator", "Producer")
    limit, offset = page_params()
    vendor_id = qstr("vendor_id")
    matched_style_id = qstr("matched_style_id")
    custody_state = qenum("custody_state", CUSTODY_STATES)
    match_state = qenum("match_state", MATCH_STATES)

    rows = list(db.samples.values())
    if vendor_id is not None:
        rows = [r for r in rows if r["vendor_id"] == vendor_id]
    if matched_style_id is not None:
        rows = [r for r in rows if r.get("matched_style_id") == matched_style_id]
    if custody_state is not None:
        rows = [r for r in rows if r["custody_state"] == custody_state]
    if match_state is not None:
        rows = [r for r in rows if r["match_state"] == match_state]

    page, total = paginate(by_created(rows), limit, offset)
    return ok_list([sample_out(r) for r in page], limit, offset, total)
