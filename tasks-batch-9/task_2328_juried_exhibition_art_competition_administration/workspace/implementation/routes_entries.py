"""Artists, entries and the fee handshake."""

from flask import Blueprint

from core import *  # noqa: F401,F403
from errors import ApiError

bp = Blueprint("entries", __name__)


# ---------------------------------------------------------------------------
# Artists
# ---------------------------------------------------------------------------


@bp.post("/artists")
def create_artist():
    authenticate()
    require_roles("CallManager")
    payload = body()
    legal_name = v_str(payload, "legal_name")
    email = v_str(payload, "email")
    state = v_str(payload, "residency_state_code")
    if len(state) != 2:
        bad("residency_state_code must be a two-letter code.")
    member_status = v_enum(
        payload, "member_status", ("MEMBER", "NON_MEMBER"), required=False,
        default="NON_MEMBER",
    )
    tax_form = v_bool(payload, "tax_form_on_file", default=False)
    payout_method = v_enum(
        payload, "payout_method", ("CHECK", "ACH"), required=False, default="CHECK"
    )
    for existing in db.artists.values():
        if existing["email"] == email:
            bad("email must be unique across artists.")
    record = new_record(
        {
            "legal_name": legal_name,
            "email": email,
            "residency_state_code": state,
            "member_status": member_status,
            "tax_form_on_file": tax_form,
            "payout_method": payout_method,
            "payout_hold": False,
            "unclaimed_forfeit_count": 0,
        }
    )
    db.artists[record["id"]] = record
    return created(record)


@bp.get("/artists/<artist_id>")
def read_artist(artist_id):
    authenticate()
    require_roles("CallManager", "Artist", "FinanceOfficer")
    artist = find("artists", artist_id)
    if role() == "Artist":
        own(user_id() == artist["id"])
    return ok(artist)


@bp.patch("/artists/<artist_id>")
def patch_artist(artist_id):
    authenticate()
    require_roles("CallManager", "Artist")
    artist = find("artists", artist_id)
    if role() == "Artist":
        own(user_id() == artist["id"])
    payload = body()
    if "payout_hold" in payload and role() != "CallManager":
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED", "Only a CallManager may supply payout_hold."
        )
    member_status = v_enum(
        payload, "member_status", ("MEMBER", "NON_MEMBER"), required=False
    )
    tax_form = v_bool(payload, "tax_form_on_file")
    payout_method = v_enum(payload, "payout_method", ("CHECK", "ACH"), required=False)
    payout_hold = v_bool(payload, "payout_hold")
    if member_status is not None:
        setv(artist, "member_status", member_status)
    if tax_form is not None:
        setv(artist, "tax_form_on_file", tax_form)
    if payout_method is not None:
        setv(artist, "payout_method", payout_method)
    if payout_hold is not None:
        setv(artist, "payout_hold", payout_hold)
    return ok(artist)


@bp.get("/artists/<artist_id>/conflict-declarations")
def artist_conflicts(artist_id):
    authenticate()
    require_roles("CallManager", "JuryChair")
    artist = find("artists", artist_id)
    items = [
        c
        for c in all_of("conflict_declarations")
        if c.get("artist_id") == artist["id"]
    ]
    return listing(items)


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------


def _live_entry_count(exhibition_id, artist_id):
    count = 0
    for entry in all_of("entries"):
        if (
            entry.get("exhibition_id") == exhibition_id
            and entry.get("artist_id") == artist_id
            and entry.get("status") in ("DRAFT", "PENDING_FEE", "SUBMITTED")
        ):
            count += 1
    return count


@bp.post("/entries")
def create_entry():
    authenticate()
    require_roles("Artist")
    payload = body()
    exhibition = fk(payload, "exhibition_id", "exhibitions")
    artist = fk(payload, "artist_id", "artists")
    if artist is not None:
        own(user_id() == artist["id"])
    if exhibition is None:
        req(payload, "exhibition_id")
    if artist is None:
        req(payload, "artist_id")

    if exhibition["status"] != "OPEN_FOR_ENTRIES":
        raise ApiError("ERR_EXHIBITION_PHASE_INVALID")
    if now() >= ts(exhibition, "call_closes_at"):
        raise ApiError("ERR_CALL_WINDOW_CLOSED")
    if artist["residency_state_code"] not in exhibition["eligible_state_codes"]:
        raise ApiError("ERR_ELIGIBILITY_NOT_MET")
    if _live_entry_count(exhibition["id"], artist["id"]) >= int(
        exhibition["max_entries_per_artist"]
    ):
        raise ApiError("ERR_ENTRY_LIMIT_EXCEEDED")

    record = new_record(
        {
            "exhibition_id": exhibition["id"],
            "artist_id": artist["id"],
            "status": "DRAFT",
            "works_count": 0,
            "entry_fee_cents": 0,
            "fee_paid_cents": 0,
            "fee_waived": False,
            "submitted_at": None,
            "shortlisted_count": 0,
        }
    )
    db.entries[record["id"]] = record
    return created(record)


@bp.get("/entries")
def list_entries():
    authenticate()
    require_roles("CallManager", "JuryChair", "Artist")
    items = all_of("entries")
    for field in ("exhibition_id", "artist_id", "status"):
        value = qs(field)
        if value is not None:
            items = [e for e in items if e.get(field) == value]
    return listing(items)


@bp.get("/entries/<entry_id>")
def read_entry(entry_id):
    authenticate()
    require_roles("CallManager", "JuryChair", "Artist")
    return ok(find("entries", entry_id))


@bp.post("/entries/<entry_id>/artworks")
def attach_artwork(entry_id):
    authenticate()
    require_roles("Artist")
    entry = find("entries", entry_id)
    own(user_id() == entry["artist_id"])
    exhibition = exhibition_of_entry(entry)
    payload = body()

    title = v_str(payload, "title")
    medium = v_enum(payload, "medium_category", MEDIA_CATEGORIES)
    width = v_num(payload, "width_cm", minimum=0)
    height = v_num(payload, "height_cm", minimum=0)
    depth = v_num(payload, "depth_cm", minimum=0)
    weight = v_num(payload, "weight_kg", minimum=0)
    year_created = v_int(payload, "year_created")
    declared_value = v_int(payload, "declared_value_cents", minimum=0)
    for_sale = v_bool(payload, "for_sale", default=False)
    list_price = v_int(payload, "list_price_cents", required=False, minimum=0)
    if for_sale and list_price is None:
        bad("list_price_cents is required when for_sale is true.")

    if entry["status"] != "DRAFT":
        raise ApiError("ERR_ENTRY_STATE_INVALID")
    if exhibition["status"] != "OPEN_FOR_ENTRIES":
        raise ApiError("ERR_EXHIBITION_PHASE_INVALID")
    if now() >= ts(exhibition, "call_closes_at"):
        raise ApiError("ERR_CALL_WINDOW_CLOSED")
    if medium not in exhibition["allowed_media_categories"]:
        raise ApiError("ERR_MEDIA_CATEGORY_NOT_ALLOWED")
    longest_edge = max(width, height, depth)
    if longest_edge > float(exhibition["max_dimension_cm"]) or weight > float(
        exhibition["max_weight_kg"]
    ):
        raise ApiError("ERR_SIZE_LIMIT_EXCEEDED")
    live_works = sum(
        1 for a in artworks_of_entry(entry["id"]) if a.get("status") != "WITHDRAWN"
    )
    if live_works + 1 > int(exhibition["max_works_per_entry"]):
        raise ApiError("ERR_MAX_WORKS_EXCEEDED")

    ordinal = len(artworks_of_exhibition(exhibition["id"])) + 1
    record = new_record(
        {
            "entry_id": entry["id"],
            "wall_segment_id": None,
            "title": title,
            "medium_category": medium,
            "width_cm": width,
            "height_cm": height,
            "depth_cm": depth,
            "weight_kg": weight,
            "year_created": year_created,
            "declared_value_cents": declared_value,
            "for_sale": for_sale,
            "list_price_cents": list_price,
            "status": "DRAFT",
            "placement_status": "UNPLACED",
            "span_start_cm": None,
            "span_end_cm": None,
            "longest_edge_cm": num(longest_edge),
            "blind_label": "%s-%04d" % (exhibition["season_year"], ordinal),
            "primary_image_count": 0,
            "provisional_mean_score": None,
            "certified_mean_score": None,
            "valid_score_count": 0,
            "intake_condition_grade": None,
            "claim_deadline_at": None,
            "return_method": None,
            "return_carrier": None,
            "return_tracking_number": None,
            "storage_fee_cents": 0,
            "sold_price_cents": None,
        }
    )
    db.artworks[record["id"]] = record
    recompute_entry_counts(entry)
    return created(record)


def _require_primary_images(entry):
    for artwork in artworks_of_entry(entry["id"]):
        if artwork.get("status") == "WITHDRAWN":
            continue
        if int(artwork.get("primary_image_count") or 0) < 1:
            raise ApiError("ERR_PRIMARY_IMAGE_REQUIRED")


def _cascade_draft_works(entry):
    for artwork in artworks_of_entry(entry["id"]):
        if artwork.get("status") == "DRAFT":
            set_artwork_status(artwork, "SUBMITTED")


@bp.post("/entries/<entry_id>/submit")
def submit_entry(entry_id):
    authenticate()
    require_roles("Artist")
    entry = find("entries", entry_id)
    own(user_id() == entry["artist_id"])
    exhibition = exhibition_of_entry(entry)
    artist = db.artists.get(entry["artist_id"])

    if entry["status"] != "DRAFT":
        raise ApiError("ERR_ENTRY_STATE_INVALID")
    if exhibition["status"] != "OPEN_FOR_ENTRIES":
        raise ApiError("ERR_EXHIBITION_PHASE_INVALID")
    if now() >= ts(exhibition, "call_closes_at"):
        raise ApiError("ERR_CALL_WINDOW_CLOSED")
    if artist["residency_state_code"] not in exhibition["eligible_state_codes"]:
        raise ApiError("ERR_ELIGIBILITY_NOT_MET")
    recompute_entry_counts(entry)
    if int(entry["works_count"]) < 1:
        raise ApiError(
            "ERR_ENTRY_STATE_INVALID", "An entry needs at least one artwork to submit."
        )
    _require_primary_images(entry)

    setv(entry, "entry_fee_cents", calc_entry_fee(entry, exhibition, artist))
    setv(entry, "status", "PENDING_FEE")
    setv(entry, "submitted_at", iso(now()))
    return ok(entry)


@bp.post("/entries/<entry_id>/fee-payment")
def pay_fee(entry_id):
    authenticate()
    require_roles("Artist")
    entry = find("entries", entry_id)
    own(user_id() == entry["artist_id"])
    exhibition = exhibition_of_entry(entry)
    payload = body()
    amount = v_int(payload, "amount_cents", minimum=0)

    if entry["status"] != "PENDING_FEE":
        raise ApiError("ERR_ENTRY_STATE_INVALID")
    if exhibition["status"] != "OPEN_FOR_ENTRIES":
        raise ApiError("ERR_EXHIBITION_PHASE_INVALID")
    if now() >= ts(exhibition, "call_closes_at"):
        raise ApiError("ERR_CALL_WINDOW_CLOSED")
    if amount != int(entry["entry_fee_cents"]):
        raise ApiError("ERR_FEE_AMOUNT_MISMATCH")

    setv(entry, "fee_paid_cents", amount)
    setv(entry, "status", "SUBMITTED")
    _cascade_draft_works(entry)
    recompute_entry_counts(entry)
    return ok(entry)


@bp.post("/entries/<entry_id>/fee-waiver")
def waive_fee(entry_id):
    authenticate()
    require_roles("CallManager")
    entry = find("entries", entry_id)
    exhibition = exhibition_of_entry(entry)

    if entry["status"] not in ("DRAFT", "PENDING_FEE"):
        raise ApiError("ERR_ENTRY_STATE_INVALID")
    if exhibition["status"] != "OPEN_FOR_ENTRIES":
        raise ApiError("ERR_EXHIBITION_PHASE_INVALID")
    recompute_entry_counts(entry)
    if int(entry["works_count"]) < 1:
        raise ApiError(
            "ERR_ENTRY_STATE_INVALID", "An entry needs at least one artwork to submit."
        )
    _require_primary_images(entry)

    setv(entry, "fee_waived", True)
    setv(entry, "entry_fee_cents", 0)
    setv(entry, "fee_paid_cents", 0)
    setv(entry, "status", "SUBMITTED")
    setv(entry, "submitted_at", iso(now()))
    _cascade_draft_works(entry)
    recompute_entry_counts(entry)
    return ok(entry)


@bp.post("/entries/<entry_id>/withdraw")
def withdraw_entry(entry_id):
    authenticate()
    require_roles("Artist", "CallManager")
    entry = find("entries", entry_id)
    if role() == "Artist":
        own(user_id() == entry["artist_id"])
    exhibition = exhibition_of_entry(entry)

    if entry["status"] not in ("DRAFT", "PENDING_FEE", "SUBMITTED"):
        raise ApiError("ERR_ENTRY_STATE_INVALID")
    if exhibition["status"] not in ("OPEN_FOR_ENTRIES", "JURYING"):
        raise ApiError("ERR_EXHIBITION_PHASE_INVALID")
    blocking = ("ACCEPTED", "WAITLISTED", "DELIVERED", "ON_VIEW", "SOLD")
    for artwork in artworks_of_entry(entry["id"]):
        if artwork.get("status") in blocking:
            raise ApiError(
                "ERR_ARTWORK_STATE_INVALID",
                "An entry with accepted or delivered work may not be withdrawn.",
            )

    setv(entry, "status", "WITHDRAWN")
    for artwork in artworks_of_entry(entry["id"]):
        if artwork.get("status") in ("DRAFT", "SUBMITTED", "SHORTLISTED"):
            set_artwork_status(artwork, "WITHDRAWN")
    recompute_entry_counts(entry)
    recompute_exhibition_counts(exhibition)
    recompute_rounds_of(exhibition)
    return ok(entry)
