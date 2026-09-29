"""Sponsors, awards and the sales ledger."""

from flask import Blueprint

from core import *  # noqa: F401,F403
from errors import ApiError

bp = Blueprint("finance", __name__)


# ---------------------------------------------------------------------------
# Sponsors
# ---------------------------------------------------------------------------


@bp.post("/sponsors")
def create_sponsor():
    authenticate()
    require_roles("CallManager")
    payload = body()
    exhibition = fk(payload, "exhibition_id", "exhibitions")
    if exhibition is None:
        req(payload, "exhibition_id")
    name = v_str(payload, "name")
    contribution = v_int(payload, "contribution_cents", minimum=0)
    budget = v_int(payload, "purchase_award_budget_cents", minimum=0)
    record = new_record(
        {
            "exhibition_id": exhibition["id"],
            "name": name,
            "contribution_cents": contribution,
            "purchase_award_budget_cents": budget,
            "recognition_tier": calc_sponsor_tier(contribution),
            "purchase_award_committed_cents": 0,
        }
    )
    db.sponsors[record["id"]] = record
    return created(record)


@bp.get("/sponsors")
def list_sponsors():
    authenticate()
    require_roles("CallManager", "JuryChair", "FinanceOfficer")
    items = all_of("sponsors")
    for field in ("exhibition_id", "recognition_tier"):
        value = qs(field)
        if value is not None:
            items = [s for s in items if s.get(field) == value]
    return listing(items)


@bp.get("/sponsors/<sponsor_id>")
def read_sponsor(sponsor_id):
    authenticate()
    require_roles("CallManager", "JuryChair", "FinanceOfficer")
    return ok(find("sponsors", sponsor_id))


# ---------------------------------------------------------------------------
# Awards
# ---------------------------------------------------------------------------


@bp.post("/awards")
def propose_award():
    authenticate()
    require_roles("JuryChair")
    payload = body()
    exhibition = fk(payload, "exhibition_id", "exhibitions")
    artwork = fk(payload, "artwork_id", "artworks")
    sponsor = fk(payload, "sponsor_id", "sponsors")
    if exhibition is None:
        req(payload, "exhibition_id")
    if artwork is None:
        req(payload, "artwork_id")
    category = v_enum(payload, "category", AWARD_CATEGORIES)
    prize = v_int(payload, "prize_cents", minimum=0)
    if category == "PURCHASE_AWARD" and sponsor is None:
        bad("sponsor_id is required when category is PURCHASE_AWARD.")

    artwork_exhibition = exhibition_of_artwork(artwork)
    if artwork_exhibition is None or artwork_exhibition["id"] != exhibition["id"]:
        raise ApiError("ERR_EXHIBITION_SCOPE_MISMATCH")
    if sponsor is not None and sponsor["exhibition_id"] != exhibition["id"]:
        raise ApiError("ERR_EXHIBITION_SCOPE_MISMATCH")

    record = new_record(
        {
            "exhibition_id": exhibition["id"],
            "artwork_id": artwork["id"],
            "sponsor_id": sponsor["id"] if sponsor is not None else None,
            "category": category,
            "prize_cents": prize,
            "status": "PROPOSED",
            "proposed_by_user_id": user_id(),
            "confirmed_by_user_id": None,
        }
    )
    db.awards[record["id"]] = record
    return created(record)


@bp.get("/awards")
def list_awards():
    authenticate()
    require_roles("CallManager", "JuryChair", "FinanceOfficer")
    items = all_of("awards")
    for field in ("exhibition_id", "artwork_id", "sponsor_id", "status"):
        value = qs(field)
        if value is not None:
            items = [a for a in items if a.get(field) == value]
    return listing(items)


@bp.get("/awards/<award_id>")
def read_award(award_id):
    authenticate()
    require_roles("CallManager", "JuryChair", "FinanceOfficer")
    return ok(find("awards", award_id))


def _create_sale(
    exhibition,
    artwork,
    sale_type,
    sale_price_cents,
    buyer_name,
    buyer_region_code,
    tax_exempt,
    recorded_by,
    source_award_id=None,
):
    split = calc_sale_split(exhibition, sale_type, sale_price_cents, tax_exempt)
    fields = {
        "artwork_id": artwork["id"],
        "source_award_id": source_award_id,
        "sale_type": sale_type,
        "buyer_name": buyer_name,
        "buyer_region_code": buyer_region_code,
        "tax_exempt": tax_exempt,
        "sale_price_cents": int(sale_price_cents),
    }
    fields.update(split)
    fields.update(
        {
            "status": "RECORDED",
            "recorded_by_user_id": recorded_by,
            "payout_released_by_user_id": None,
            "void_reason": None,
        }
    )
    record = new_record(fields)
    db.sales[record["id"]] = record
    set_artwork_status(artwork, "SOLD")
    setv(artwork, "sold_price_cents", int(sale_price_cents))
    recompute_money(exhibition)
    return record


def _void_sale(sale, exhibition, reason):
    setv(sale, "status", "VOIDED")
    setv(sale, "void_reason", reason)
    artwork = db.artworks.get(sale["artwork_id"])
    if artwork is not None:
        others = [
            s
            for s in sales_of_artwork(artwork["id"])
            if s["id"] != sale["id"] and s.get("status") != "VOIDED"
        ]
        if not others and artwork.get("status") == "SOLD":
            if exhibition["status"] == "CLOSED":
                set_artwork_status(artwork, "RETURN_PENDING")
            else:
                set_artwork_status(artwork, "ON_VIEW")
            setv(artwork, "sold_price_cents", None)
    recompute_money(exhibition)
    recompute_insurance(exhibition)


@bp.post("/awards/<award_id>/confirm")
def confirm_award(award_id):
    authenticate()
    require_roles("JuryChair")
    award = find("awards", award_id)
    exhibition = db.exhibitions.get(award["exhibition_id"])
    artwork = db.artworks.get(award["artwork_id"])
    sponsor = db.sponsors.get(award.get("sponsor_id")) if award.get("sponsor_id") else None
    payload = body()
    expected = v_int(payload, "expected_exhibition_version")

    if award["status"] != "PROPOSED":
        raise ApiError("ERR_AWARD_STATE_INVALID")
    if exhibition["status"] not in ("RESULTS_PUBLISHED", "INSTALLATION", "ON_VIEW"):
        raise ApiError("ERR_EXHIBITION_PHASE_INVALID")

    artwork_exhibition = exhibition_of_artwork(artwork) if artwork else None
    if artwork_exhibition is None or artwork_exhibition["id"] != exhibition["id"]:
        raise ApiError("ERR_EXHIBITION_SCOPE_MISMATCH")
    if sponsor is not None and sponsor["exhibition_id"] != exhibition["id"]:
        raise ApiError("ERR_EXHIBITION_SCOPE_MISMATCH")

    if user_id() == award.get("proposed_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    prize = int(award["prize_cents"])
    if sponsor is None:
        if int(exhibition["award_committed_cents"]) + prize > int(
            exhibition["award_budget_cents"]
        ):
            raise ApiError("ERR_AWARD_BUDGET_EXCEEDED")
    if award["category"] == "PURCHASE_AWARD":
        if int(sponsor["purchase_award_committed_cents"]) + prize > int(
            sponsor["purchase_award_budget_cents"]
        ):
            raise ApiError("ERR_SPONSOR_BUDGET_EXCEEDED")
        if artwork["status"] != "ON_VIEW":
            raise ApiError("ERR_ARTWORK_STATE_INVALID")

    if expected != exhibition["version"]:
        raise ApiError("ERR_STALE_VERSION")

    setv(award, "status", "CONFIRMED")
    setv(award, "confirmed_by_user_id", user_id())
    if sponsor is None:
        recompute_awards(exhibition)
    else:
        recompute_sponsor(sponsor)

    if award["category"] == "PURCHASE_AWARD":
        _create_sale(
            exhibition,
            artwork,
            "PURCHASE_AWARD",
            prize,
            sponsor["name"],
            None,
            False,
            None,
            source_award_id=award["id"],
        )

    touch(exhibition)
    touch(award)
    return ok(award)


@bp.post("/awards/<award_id>/rescind")
def rescind_award(award_id):
    authenticate()
    require_roles("JuryChair")
    award = find("awards", award_id)
    exhibition = db.exhibitions.get(award["exhibition_id"])
    sponsor = db.sponsors.get(award.get("sponsor_id")) if award.get("sponsor_id") else None
    payload = body()
    reason = v_str(payload, "reason")

    if award["status"] != "CONFIRMED":
        raise ApiError("ERR_AWARD_STATE_INVALID")
    if exhibition["settlement_status"] != "NOT_STARTED":
        raise ApiError("ERR_SETTLEMENT_PHASE_INVALID")

    setv(award, "status", "RESCINDED")
    if sponsor is None:
        recompute_awards(exhibition)
    else:
        recompute_sponsor(sponsor)

    if award["category"] == "PURCHASE_AWARD":
        for sale in sales_of_artwork(award["artwork_id"]):
            if sale.get("source_award_id") == award["id"] and sale.get(
                "status"
            ) != "VOIDED":
                _void_sale(sale, exhibition, reason)

    touch(award)
    return ok(award)


# ---------------------------------------------------------------------------
# Sales
# ---------------------------------------------------------------------------


@bp.post("/sales")
def record_sale():
    authenticate()
    require_roles("FinanceOfficer")
    payload = body()
    artwork = fk(payload, "artwork_id", "artworks")
    if artwork is None:
        req(payload, "artwork_id")
    buyer_name = v_str(payload, "buyer_name")
    buyer_region = v_str(payload, "buyer_region_code")
    sale_price = v_int(payload, "sale_price_cents", minimum=0)
    tax_exempt = v_bool(payload, "tax_exempt", default=False)

    exhibition = exhibition_of_artwork(artwork)
    if artwork["status"] != "ON_VIEW":
        raise ApiError("ERR_ARTWORK_STATE_INVALID")
    if exhibition is None or exhibition["status"] != "ON_VIEW":
        raise ApiError("ERR_EXHIBITION_PHASE_INVALID")
    if not artwork.get("for_sale") or artwork.get("list_price_cents") is None:
        raise ApiError("ERR_ARTWORK_NOT_FOR_SALE")
    for existing in sales_of_artwork(artwork["id"]):
        if existing.get("status") != "VOIDED":
            raise ApiError("ERR_SALE_STATE_INVALID", "This artwork already has a sale.")

    record = _create_sale(
        exhibition,
        artwork,
        "GALLERY_SALE",
        sale_price,
        buyer_name,
        buyer_region,
        tax_exempt,
        user_id(),
    )
    return created(record)


@bp.get("/sales")
def list_sales():
    authenticate()
    require_roles("CallManager", "FinanceOfficer", "Artist")
    items = all_of("sales")
    for field in ("artwork_id", "source_award_id", "status"):
        value = qs(field)
        if value is not None:
            items = [s for s in items if s.get(field) == value]
    return listing(items)


@bp.get("/sales/<sale_id>")
def read_sale(sale_id):
    authenticate()
    require_roles("CallManager", "FinanceOfficer", "Artist")
    return ok(find("sales", sale_id))


@bp.post("/sales/<sale_id>/invoice")
def invoice_sale(sale_id):
    authenticate()
    require_roles("FinanceOfficer")
    sale = find("sales", sale_id)
    if sale["status"] != "RECORDED":
        raise ApiError("ERR_SALE_STATE_INVALID")
    setv(sale, "status", "INVOICED")
    return ok(sale)


@bp.post("/sales/<sale_id>/payment")
def pay_sale(sale_id):
    authenticate()
    require_roles("FinanceOfficer")
    sale = find("sales", sale_id)
    payload = body()
    amount = v_int(payload, "amount_cents", minimum=0)
    if sale["status"] != "INVOICED":
        raise ApiError("ERR_SALE_STATE_INVALID")
    if amount != int(sale["buyer_total_cents"]):
        raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH")
    setv(sale, "status", "PAID")
    return ok(sale)


@bp.post("/sales/<sale_id>/payout")
def payout_sale(sale_id):
    authenticate()
    require_roles("FinanceOfficer")
    sale = find("sales", sale_id)
    artwork = db.artworks.get(sale["artwork_id"])
    exhibition = exhibition_of_artwork(artwork) if artwork else None
    artist = artist_of_artwork(artwork) if artwork else None
    payload = body()
    expected = v_int(payload, "expected_exhibition_version")

    if sale["status"] != "PAID":
        raise ApiError("ERR_SALE_STATE_INVALID")
    if exhibition is None or exhibition["settlement_status"] != "RECONCILING":
        raise ApiError("ERR_SETTLEMENT_PHASE_INVALID")
    if user_id() == sale.get("recorded_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if artist is None or not artist.get("tax_form_on_file"):
        raise ApiError("ERR_TAX_FORM_MISSING")
    if artist.get("payout_hold"):
        raise ApiError("ERR_ARTIST_PAYOUT_HOLD")
    if expected != exhibition["version"]:
        raise ApiError("ERR_STALE_VERSION")

    setv(sale, "status", "PAYOUT_RELEASED")
    setv(sale, "payout_released_by_user_id", user_id())
    recompute_money(exhibition)
    touch(exhibition)
    touch(sale)
    return ok(sale)


@bp.post("/sales/<sale_id>/void")
def void_sale(sale_id):
    authenticate()
    require_roles("FinanceOfficer")
    sale = find("sales", sale_id)
    artwork = db.artworks.get(sale["artwork_id"])
    exhibition = exhibition_of_artwork(artwork) if artwork else None
    payload = body()
    reason = v_str(payload, "reason")

    if sale["status"] not in ("RECORDED", "INVOICED", "PAID"):
        raise ApiError("ERR_SALE_STATE_INVALID")
    if exhibition is None or exhibition["settlement_status"] not in (
        "NOT_STARTED",
        "RECONCILING",
    ):
        raise ApiError("ERR_SETTLEMENT_PHASE_INVALID")

    _void_sale(sale, exhibition, reason)
    return ok(sale)
