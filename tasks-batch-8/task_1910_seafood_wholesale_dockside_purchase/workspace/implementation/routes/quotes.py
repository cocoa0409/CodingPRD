"""MarketQuote: daily price board, volatility guard, publication series."""
from decimal import Decimal

from flask import Blueprint

from db import store, new_record, touch
from errors import (
    ApiError,
    ERR_QUOTE_NOT_FOUND,
    ERR_SPECIES_NOT_FOUND,
    ERR_QUOTE_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_SEGREGATION_OF_DUTIES_VIOLATION,
    ERR_INVALID_REQUEST,
)
from middleware import auth, require
from response import ok, ok_list
from services.calc import (
    current_published,
    volatility_pct,
    VOLATILITY_THRESHOLD,
)
from util import body, req_str, req_int, req_enum, req_date, parse_date_str, apply_filters

bp = Blueprint("quotes", __name__)

GRADES = {"GRADE_A", "GRADE_B", "GRADE_C"}


def _get_quote(rid):
    rec = store.quotes.get(rid)
    if rec is None:
        raise ApiError(ERR_QUOTE_NOT_FOUND, 404, "MarketQuote id does not exist")
    return rec


def _supersede_prior(quote):
    """When a quote reaches PUBLISHED, the prior PUBLISHED quote for the same
    (species_id, grade) is superseded."""
    for q in store.quotes.values():
        if (
            q["id"] != quote["id"]
            and q["species_id"] == quote["species_id"]
            and q["grade"] == quote["grade"]
            and q["status"] == "PUBLISHED"
        ):
            q["status"] = "SUPERSEDED"
            touch(q)


@bp.post("/market-quotes")
def create_quote():
    uid, role = auth()
    require(role, {"OperationsManager"})
    b = body()
    species_id = req_str(b, "species_id")
    grade = req_enum(b, "grade", GRADES)
    quote_date = req_date(b, "quote_date")
    price = req_int(b, "price_per_kg_cents")
    if price <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "price_per_kg_cents must be > 0")
    if species_id not in store.species:
        raise ApiError(ERR_SPECIES_NOT_FOUND, 404, "Species id does not exist")
    rec = new_record({
        "species_id": species_id,
        "grade": grade,
        "quote_date": quote_date,
        "price_per_kg_cents": price,
        "status": "DRAFT",
        "volatility_pct": Decimal("0"),
        "created_by_user_id": uid,
        "_quote_date": parse_date_str(quote_date),
    })
    store.quotes[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/market-quotes")
def list_quotes():
    auth()
    page, total, limit, offset = apply_filters(
        list(store.quotes.values()),
        ["species_id", "grade", "quote_date", "status"],
    )
    return ok_list(page, total, limit, offset)


@bp.get("/market-quotes/<rid>")
def get_quote(rid):
    auth()
    return ok(_get_quote(rid))


@bp.post("/market-quotes/<rid>/publish")
def publish_quote(rid):
    _, role = auth()
    require(role, {"OperationsManager"})
    b = body()
    expected_species_version = req_int(b, "expected_species_version")
    quote = _get_quote(rid)
    species = store.species[quote["species_id"]]
    # OCC (priority 5) precedes the state check (priority 6).
    if expected_species_version != species["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_species_version is stale")
    if quote["status"] != "DRAFT":
        raise ApiError(ERR_QUOTE_INVALID_STATE, 409, "Quote is not in DRAFT")
    # Volatility guard against the current PUBLISHED quote for the same key.
    prior = current_published(quote["species_id"], quote["grade"])
    if prior is None:
        quote["status"] = "PUBLISHED"
        touch(quote)
    else:
        vol = volatility_pct(quote["price_per_kg_cents"], prior["price_per_kg_cents"])
        quote["volatility_pct"] = vol
        if vol >= VOLATILITY_THRESHOLD:
            quote["status"] = "PENDING_APPROVAL"
        else:
            quote["status"] = "PUBLISHED"
        touch(quote)
        if quote["status"] == "PUBLISHED":
            _supersede_prior(quote)
    # Publishing advances the species version by one either way.
    touch(species)
    return ok(quote)


@bp.post("/market-quotes/<rid>/approve-volatility")
def approve_volatility(rid):
    uid, role = auth()
    require(role, {"OperationsManager"})
    quote = _get_quote(rid)
    if quote["status"] != "PENDING_APPROVAL":
        raise ApiError(ERR_QUOTE_INVALID_STATE, 409, "Quote is not in PENDING_APPROVAL")
    if uid == quote["created_by_user_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES_VIOLATION,
            403,
            "Volatility approver must differ from the quote creator",
        )
    quote["status"] = "PUBLISHED"
    touch(quote)
    _supersede_prior(quote)
    return ok(quote)


@bp.post("/market-quotes/<rid>/reject-volatility")
def reject_volatility(rid):
    _, role = auth()
    require(role, {"OperationsManager"})
    quote = _get_quote(rid)
    if quote["status"] != "PENDING_APPROVAL":
        raise ApiError(ERR_QUOTE_INVALID_STATE, 409, "Quote is not in PENDING_APPROVAL")
    quote["status"] = "DRAFT"
    touch(quote)
    return ok(quote)
