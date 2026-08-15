"""Home registration (auto-creates the 1:1 warranty reserve) and reads (PRD 3.1)."""
from flask import Blueprint, request

from db import db, new_entity, sorted_items
from errors import raise_error, ERR_HOME_NOT_FOUND, ERR_HOMEOWNER_NOT_FOUND
from middleware import get_caller, require_role
from response import success_list, success_object
from services.calc import alert_status_for, expected_accrual_cents
from util import add_months, serialize
from validate import get_body, pagination_params, apply_page, req_enum, req_int, req_str, req_date

bp = Blueprint("homes", __name__)

WARRANTY_PROGRAMS = {"STANDARD", "THIRD_PARTY_ADMINISTERED"}


@bp.post("/homes")
def create_home():
    _uid, role = get_caller()
    require_role(role, {"WarrantyManager"})
    body = get_body()
    # Identifier resolution (precedence 4) precedes remaining shape checks:
    # a present-but-unknown homeowner reference 404s even if other fields are missing.
    homeowner_ref = body.get("homeowner_id")
    if isinstance(homeowner_ref, str) and homeowner_ref.strip() != "":
        if homeowner_ref not in db["homeowners"]:
            raise_error(ERR_HOMEOWNER_NOT_FOUND,
                        f"homeowner id does not resolve: {homeowner_ref}")
    homeowner_id = req_str(body, "homeowner_id")
    lot_number = req_str(body, "lot_number")
    community_name = req_str(body, "community_name")
    sale_price_cents = req_int(body, "sale_price_cents", positive=True)
    closing_date = req_date(body, "closing_date")
    warranty_program = req_enum(body, "warranty_program", WARRANTY_PROGRAMS)

    home = new_entity()
    home.update({
        "homeowner_id": homeowner_id,
        "lot_number": lot_number,
        "community_name": community_name,
        "sale_price_cents": sale_price_cents,
        "closing_date": closing_date,
        "warranty_program": warranty_program,
        # Tier end dates anchored at closing; coverage end is EXCLUSIVE.
        "workmanship_end_date": add_months(closing_date, 12),
        "systems_end_date": add_months(closing_date, 24),
        "structural_end_date": add_months(closing_date, 120),
    })
    db["homes"][home["id"]] = home

    # Exactly one reserve per home, created with the home (version 1, zero balance).
    expected = expected_accrual_cents(sale_price_cents)
    reserve = new_entity()
    reserve.update({
        "home_id": home["id"],
        "expected_lifetime_accrual_cents": expected,
        "accrued_to_date_cents": 0,
        "drawn_to_date_cents": 0,
        "recovered_to_date_cents": 0,
        "balance_cents": 0,
        "last_accrual_month_index": 0,
        # A zero balance sits below the alert threshold whenever expected > 0.
        "alert_status": alert_status_for(0, expected),
    })
    db["warranty_reserves"][reserve["id"]] = reserve
    return success_object(serialize(home), 201)


@bp.get("/homes/<rid>")
def fetch_home(rid):
    _uid, role = get_caller()
    require_role(role, {"WarrantyManager", "WarrantyRep", "FinanceAdmin", "Homeowner"})
    home = db["homes"].get(rid)
    if home is None:
        raise_error(ERR_HOME_NOT_FOUND, f"home id does not resolve: {rid}")
    return success_object(serialize(home))


@bp.get("/homes")
def list_homes():
    _uid, role = get_caller()
    require_role(role, {"WarrantyManager", "WarrantyRep", "FinanceAdmin"})
    limit, offset = pagination_params()
    homeowner_id = request.args.get("homeowner_id")
    community_name = request.args.get("community_name")
    items = sorted_items("homes")
    if homeowner_id is not None:
        items = [h for h in items if h["homeowner_id"] == homeowner_id]
    if community_name is not None:
        items = [h for h in items if h["community_name"] == community_name]
    page, total = apply_page(items, limit, offset)
    return success_list([serialize(h) for h in page], total, limit, offset)
