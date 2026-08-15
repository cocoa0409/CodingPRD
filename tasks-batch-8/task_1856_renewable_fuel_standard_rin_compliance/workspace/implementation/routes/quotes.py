"""PriceQuote endpoints: create, get, list."""
from flask import Blueprint, request

import db
from errors import invalid_request, not_found, reference_not_found, price_window_overlap
from middleware import require_roles, json_body
from response import ok_object, ok_list, parse_pagination, paginate
from serializers import quote_view

bp = Blueprint("quotes", __name__)

_D_CODES = ("D3", "D4", "D5", "D6")


@bp.route("/rfs/price-quotes", methods=["POST"])
def create_quote():
    require_roles("OpsAdmin")
    body = json_body()

    account_id = body.get("account_id")
    d_code = body.get("d_code")
    vintage_year = body.get("vintage_year")
    price_cents = body.get("price_cents")
    effective_start_raw = body.get("effective_start")
    effective_end_raw = body.get("effective_end")

    # --- Request shape (priority 5) ---
    for field, value in (("account_id", account_id), ("d_code", d_code),
                         ("vintage_year", vintage_year), ("price_cents", price_cents),
                         ("effective_start", effective_start_raw), ("effective_end", effective_end_raw)):
        if value is None:
            raise invalid_request(f"{field} is required")
    if d_code not in _D_CODES:
        raise invalid_request("d_code must be one of D3, D4, D5, D6")
    if not isinstance(vintage_year, int) or isinstance(vintage_year, bool):
        raise invalid_request("vintage_year must be an integer")
    if not isinstance(price_cents, int) or isinstance(price_cents, bool) or price_cents <= 0:
        raise invalid_request("price_cents must be a positive integer")
    try:
        effective_start = db.parse_iso(effective_start_raw)
        effective_end = db.parse_iso(effective_end_raw)
    except (ValueError, TypeError):
        raise invalid_request("effective_start and effective_end must be valid ISO 8601 datetimes")
    # CLOSED window: end may equal start but never precede it
    if effective_end < effective_start:
        raise invalid_request("effective_end must be >= effective_start")

    # --- Referential integrity (priority 6) ---
    if db.compliance_accounts.get(account_id) is None:
        raise reference_not_found("Referenced account does not exist")

    # --- Overlap (priority 10): CLOSED [start, end] for same (account, d_code, vintage);
    #     sharing an endpoint IS a conflict ---
    for q in db.price_quotes.values():
        if q["account_id"] != account_id or q["d_code"] != d_code or q["vintage_year"] != vintage_year:
            continue
        # Closed-interval overlap: new_start <= existing_end AND existing_start <= new_end
        if effective_start <= q["effective_end"] and q["effective_start"] <= effective_end:
            raise price_window_overlap("Effective window overlaps an existing quote for the same account, D-code, and vintage")

    now = db.now_utc()
    quote = {
        "id": db.new_id(),
        "account_id": account_id,
        "d_code": d_code,
        "vintage_year": vintage_year,
        "price_cents": price_cents,
        "effective_start": effective_start,
        "effective_end": effective_end,
        "retention_until": db.retention_until_from(now),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.price_quotes[quote["id"]] = quote
    return ok_object(quote_view(quote), status=201)


@bp.route("/rfs/price-quotes/<quote_id>", methods=["GET"])
def get_quote(quote_id):
    require_roles("OpsAdmin", "ComplianceManager", "Trader")
    quote = db.price_quotes.get(quote_id)
    if quote is None:
        raise not_found("Price quote not found")
    return ok_object(quote_view(quote))


@bp.route("/rfs/price-quotes", methods=["GET"])
def list_quotes():
    require_roles("OpsAdmin", "ComplianceManager", "Trader")
    limit, offset = parse_pagination(request.args)
    account_id = request.args.get("account_id")
    rows = list(db.price_quotes.values())
    if account_id is not None:
        rows = [r for r in rows if r["account_id"] == account_id]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return ok_list([quote_view(r) for r in page], limit, offset, total)
