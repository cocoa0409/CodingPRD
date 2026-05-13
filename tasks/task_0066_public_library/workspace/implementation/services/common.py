"""Common helpers: lookups, OCC, presentation."""
from flask import g

import db
from errors import err


# ---------- Lookups (raise ERR_NOT_FOUND on miss) ----------

def get_book_title(tid: str):
    obj = db.book_titles.get(tid)
    if not obj:
        raise err("ERR_NOT_FOUND", f"BookTitle {tid} not found")
    return obj


def get_copy(cid: str):
    obj = db.copies.get(cid)
    if not obj:
        raise err("ERR_NOT_FOUND", f"Copy {cid} not found")
    return obj


def get_reader(rid: str):
    obj = db.readers.get(rid)
    if not obj:
        raise err("ERR_NOT_FOUND", f"Reader {rid} not found")
    return obj


def get_card(cid: str):
    obj = db.cards.get(cid)
    if not obj:
        raise err("ERR_NOT_FOUND", f"Card {cid} not found")
    return obj


def get_loan(lid: str):
    obj = db.loans.get(lid)
    if not obj:
        raise err("ERR_NOT_FOUND", f"Loan {lid} not found")
    return obj


def get_reservation(rid: str):
    obj = db.reservations.get(rid)
    if not obj:
        raise err("ERR_NOT_FOUND", f"Reservation {rid} not found")
    return obj


def get_fine(fid: str):
    obj = db.fines.get(fid)
    if not obj:
        raise err("ERR_NOT_FOUND", f"Fine {fid} not found")
    return obj


def get_ill_request(iid: str):
    obj = db.ill_requests.get(iid)
    if not obj:
        raise err("ERR_NOT_FOUND", f"ILLRequest {iid} not found")
    return obj


def get_suggestion(sid: str):
    obj = db.acquisition_suggestions.get(sid)
    if not obj:
        raise err("ERR_NOT_FOUND", f"AcquisitionSuggestion {sid} not found")
    return obj


# ---------- OCC check ----------

def check_version(resource: dict, body: dict):
    """Per PRD §2.5: omit version => skip; provided => must match current."""
    if not isinstance(body, dict):
        return
    if "version" not in body:
        return
    requested = body.get("version")
    if requested is None:
        return
    current = resource.get("version")
    if requested != current:
        raise err("ERR_VERSION_CONFLICT",
                  f"version mismatch: provided {requested}, current {current}")


# ---------- Reader ownership (Reader role) ----------

def assert_reader_ownership(resource_reader_id: str):
    """If role is Reader, X-User-ID must equal the resource's owning reader id."""
    if g.user_role == "Reader":
        if g.user_id != resource_reader_id:
            raise err("ERR_FORBIDDEN", "Reader can act only on their own resources")
