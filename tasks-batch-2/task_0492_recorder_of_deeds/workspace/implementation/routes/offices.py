"""RecordingOffice routes (PRD §2.5, §3.1, §4)."""
from flask import Blueprint

from auth import require_auth, CLERK, ALL_READERS
from clock import clock
from db import db, new_id, common_fields, touch
from escrow import recompute
from helpers import body, require_fields, as_int, as_str, get_or_404, out
from response import ok, created

bp = Blueprint("offices", __name__)

DEFAULT_INSTRUMENT_SEQ_START = 1000000


@bp.route("/offices", methods=["POST"])
def create_office():
    require_auth([CLERK])
    data = body()
    require_fields(data, ["county_name", "book_capacity"])
    county_name = as_str(data, "county_name")
    book_capacity = as_int(data, "book_capacity", minimum=1)
    if "instrument_seq_start" in data and data["instrument_seq_start"] is not None:
        seq_start = as_int(data, "instrument_seq_start", minimum=0)
    else:
        seq_start = DEFAULT_INSTRUMENT_SEQ_START

    oid = new_id()
    office = {
        "id": oid,
        "county_name": county_name,
        "book_capacity": book_capacity,
        "instrument_seq_start": seq_start,
        "next_instrument_number": seq_start,
        "current_book": 1,
        "current_page": 1,
        "documents_in_current_book": 0,
        "recording_date": clock.now(),
        "daily_collected_cents": 0,
        "total_indexed_entries": 0,
    }
    office.update(common_fields())
    db.offices[oid] = office
    return created(out(office))


@bp.route("/offices/<oid>", methods=["GET"])
def get_office(oid):
    require_auth(ALL_READERS)
    office = get_or_404(db.offices, oid)
    return ok(out(office))


@bp.route("/offices/<oid>/deposit-escrow", methods=["POST"])
def deposit_escrow(oid):
    require_auth([CLERK])
    office = get_or_404(db.offices, oid)
    data = body()
    require_fields(data, ["submitter_id", "amount_cents"])
    submitter_id = as_str(data, "submitter_id")
    amount = as_int(data, "amount_cents", minimum=0)
    submitter = get_or_404(db.submitters, submitter_id)

    # Deposit raises deposited total and settled balance; recompute available.
    submitter["escrow_deposited_total_cents"] += amount
    recompute(submitter)
    touch(submitter)
    return created(out(submitter))
