"""FraudFlag lifecycle and listing freeze/unfreeze (PRD §3.8)."""
import db
import errors
from errors import err
from services import calc, recompute, seat_ops


def _subject_listing(flag):
    """Resolve the listing that the flag's subject pertains to (for freeze logic).
    LISTING -> the listing; SEAT -> the seat's listing; ORDER -> the order's listing."""
    if flag["subject_type"] == "LISTING":
        return db.listings.get(flag.get("listing_id"))
    if flag["subject_type"] == "SEAT":
        seat = db.seats.get(flag.get("seat_id"))
        return db.listings.get(seat["listing_id"]) if seat else None
    if flag["subject_type"] == "ORDER":
        order = db.orders.get(flag.get("order_id"))
        return db.listings.get(order["listing_id"]) if order else None
    return None


def _seller_for_flag(flag):
    listing = _subject_listing(flag)
    if listing is not None:
        return db.sellers.get(listing["seller_id"])
    return None


def compute_severity(flag):
    listing = _subject_listing(flag)
    eff = listing["effective_price_cents"] if listing else None
    face = None
    if listing is not None:
        section = db.sections.get(listing["section_id"])
        face = section["face_value_cents"] if section else None
    return calc.fraud_severity(flag["signal"], eff, face if face is not None else 0)


def freeze_listing_if_needed(flag):
    """On a HIGH flag landing on a listing, freeze DRAFT/ACTIVE listing -> FROZEN."""
    if flag["severity"] != "HIGH":
        return
    listing = _subject_listing(flag)
    if listing is None:
        return
    if listing["status"] in ("DRAFT", "ACTIVE"):
        listing["status"] = "FROZEN"
        db.touch(listing)
        event = db.events.get(listing["event_id"])
        if event is not None:
            recompute.recompute_event(event)


def _other_high_open(listing_id, exclude_flag_id):
    """True if some other flag on the listing has severity HIGH and status in
    {OPEN, UNDER_REVIEW, CONFIRMED}."""
    listing_seat_ids = {s["id"] for s in db.seats.values() if s["listing_id"] == listing_id}
    for f in db.fraud_flags.values():
        if f["id"] == exclude_flag_id:
            continue
        if f["severity"] != "HIGH":
            continue
        if f["status"] not in ("OPEN", "UNDER_REVIEW", "CONFIRMED"):
            continue
        if f["subject_type"] == "LISTING" and f.get("listing_id") == listing_id:
            return True
        if f["subject_type"] == "SEAT" and f.get("seat_id") in listing_seat_ids:
            return True
        if f["subject_type"] == "ORDER":
            order = db.orders.get(f.get("order_id"))
            if order and order["listing_id"] == listing_id:
                return True
    return False


def review(flag):
    if flag["status"] != "OPEN":
        raise err(errors.ERR_INVALID_STATE, "Flag is not OPEN")
    flag["status"] = "UNDER_REVIEW"
    db.touch(flag)


def confirm(flag):
    if flag["status"] not in ("OPEN", "UNDER_REVIEW"):
        raise err(errors.ERR_INVALID_STATE, "Flag is not OPEN/UNDER_REVIEW")
    flag["status"] = "CONFIRMED"
    db.touch(flag)

    listing = _subject_listing(flag)
    # DUPLICATE_BARCODE: void the flagged seat
    if flag["signal"] == "DUPLICATE_BARCODE" and flag["subject_type"] == "SEAT":
        seat = db.seats.get(flag.get("seat_id"))
        if seat is not None and seat["status"] != "VOID":
            seat_ops.set_status(seat, "VOID")
        if listing is not None:
            recompute.recompute_listing(listing)

    # freeze if HIGH and not already frozen
    if flag["severity"] == "HIGH" and listing is not None and listing["status"] in ("DRAFT", "ACTIVE"):
        listing["status"] = "FROZEN"
        db.touch(listing)
        event = db.events.get(listing["event_id"])
        if event is not None:
            recompute.recompute_event(event)

    seller = _seller_for_flag(flag)
    if seller is not None:
        recompute.recompute_seller(seller)


def dismiss(flag):
    if flag["status"] not in ("OPEN", "UNDER_REVIEW"):
        raise err(errors.ERR_INVALID_STATE, "Flag is not OPEN/UNDER_REVIEW")
    flag["status"] = "DISMISSED"
    db.touch(flag)

    listing = _subject_listing(flag)
    # if this was the last HIGH open flag and listing FROZEN -> ACTIVE
    if listing is not None and listing["status"] == "FROZEN":
        if not _other_high_open(listing["id"], flag["id"]):
            listing["status"] = "ACTIVE"
            db.touch(listing)
            recompute.recompute_listing(listing)
            event = db.events.get(listing["event_id"])
            if event is not None:
                recompute.recompute_event(event)

    seller = _seller_for_flag(flag)
    if seller is not None:
        recompute.recompute_seller(seller)
