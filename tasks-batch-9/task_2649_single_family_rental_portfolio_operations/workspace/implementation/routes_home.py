"""The home register, its posture read and the disposition decision."""
from flask import Blueprint

import calc
import cascades
import store
import views
from envelope import created, ok, paginate
from errors import fail
from validation import F, authorize, body_json, must_find, validate

bp = Blueprint("homes", __name__)

HOME_READ = ["PortfolioAdmin", "OperationsManager", "LeasingAgent", "ComplianceOfficer",
             "AcquisitionAnalyst", "InvestmentCommittee", "RegionalDirector", "VendorManager"]
POSTURE_READ = ["PortfolioAdmin", "OperationsManager", "LeasingAgent", "ComplianceOfficer",
                "RegionalDirector"]

HOME_FIELDS = [
    F("market_id", "string"),
    F("address_line1", "string"),
    F("city", "string"),
    F("state_code", "string"),
    F("postal_code", "string"),
    F("bedrooms", "count"),
    F("bathrooms", "number"),
    F("square_feet", "count"),
    F("year_built", "count"),
    F("assessed_value_cents", "money"),
    F("asking_rent_cents", "money", required=False, default=None),
    F("insurance_carrier_name", "string"),
    F("insurance_annual_premium_cents", "money"),
    F("insurance_binder_expires_on", "date"),
    F("hoa_name", "string", required=False, default=""),
    F("hoa_annual_cents", "money", required=False, default=0),
]

PATCH_FIELDS = [
    F("asking_rent_cents", "money", required=False, default=None),
    F("assessed_value_cents", "money", required=False, default=None),
    F("insurance_carrier_name", "string", required=False, default=None),
    F("insurance_annual_premium_cents", "money", required=False, default=None),
    F("insurance_binder_expires_on", "date", required=False, default=None),
    F("hoa_name", "string", required=False, default=None),
    F("hoa_annual_cents", "money", required=False, default=None),
]


@bp.post("/homes")
def create_home():
    data = validate(body_json(), HOME_FIELDS)
    authorize(["AcquisitionAnalyst", "PortfolioAdmin"])
    market = must_find("markets", data["market_id"], "ERR_MARKET_NOT_FOUND")
    row = store.base_row()
    row.update({
        "market_id": market["id"],
        "address_line1": data["address_line1"],
        "city": data["city"],
        "state_code": data["state_code"],
        "postal_code": data["postal_code"],
        "bedrooms": data["bedrooms"],
        "bathrooms": data["bathrooms"],
        "square_feet": data["square_feet"],
        "year_built": data["year_built"],
        "assessed_value_cents": data["assessed_value_cents"],
        "asking_rent_cents": (data["asking_rent_cents"] if data["asking_rent_cents"] is not None
                              else market["rent_index_cents"]),
        "insurance_carrier_name": data["insurance_carrier_name"],
        "insurance_annual_premium_cents": data["insurance_annual_premium_cents"],
        "insurance_binder_expires_on": data["insurance_binder_expires_on"],
        "hoa_name": data["hoa_name"],
        "hoa_annual_cents": data["hoa_annual_cents"],
        "property_tax_annual_cents": calc.property_tax_annual(
            data["assessed_value_cents"], market["millage_bps"]),
        "asset_status": "PIPELINE",
        "occupancy_status": "VACANT",
        "booked_showing_count": 0,
        "disposition_mode": "NONE",
        "lot_code": "",
        "bpo_value_cents": 0,
        "net_sale_proceeds_cents": 0,
        "realized_gain_cents": 0,
        "hold_sell_score_bps": 0,
        "disposition_flagged": False,
    })
    store.insert("homes", row)
    return created(views.home_view(row))


@bp.get("/homes/<home_id>")
def read_home(home_id):
    authorize(HOME_READ)
    row = must_find("homes", home_id, "ERR_HOME_NOT_FOUND")
    return ok(views.home_view(row))


@bp.get("/homes")
def list_homes():
    authorize(HOME_READ)
    rows = views.filtered("homes", [
        ("market_id", "market_id", "string"),
        ("asset_status", "asset_status", "string"),
        ("occupancy_status", "occupancy_status", "string"),
        ("leasing_posture", "leasing_posture", "posture"),
        ("disposition_flagged", "disposition_flagged", "bool"),
        ("lot_code", "lot_code", "string"),
    ])
    return paginate(rows, views.home_view)


@bp.patch("/homes/<home_id>")
def update_home(home_id):
    data = validate(body_json(), PATCH_FIELDS)
    authorize(["PortfolioAdmin", "AcquisitionAnalyst"])
    home = must_find("homes", home_id, "ERR_HOME_NOT_FOUND")
    for name in ("asking_rent_cents", "insurance_carrier_name",
                 "insurance_annual_premium_cents", "hoa_name", "hoa_annual_cents"):
        if data[name] is not None:
            home[name] = data[name]
    if data["assessed_value_cents"] is not None:
        home["assessed_value_cents"] = data["assessed_value_cents"]
        cascades.recompute_property_tax(home)
    binder_changed = data["insurance_binder_expires_on"] is not None
    if binder_changed:
        home["insurance_binder_expires_on"] = data["insurance_binder_expires_on"]
    store.touch(home)
    if binder_changed:
        cascades.recompute_posture(home)
    return ok(views.home_view(home))


@bp.get("/homes/<home_id>/leasing-posture")
def read_posture(home_id):
    authorize(POSTURE_READ)
    home = must_find("homes", home_id, "ERR_HOME_NOT_FOUND")
    posture, clause, blocking, expired = calc.leasing_posture_detail(home)
    return ok({
        "home_id": home["id"],
        "leasing_posture": posture,
        "deciding_clause": clause,
        "blocking_obligation_ids": blocking,
        "binder_expired": expired,
    })


DISPOSITION_FIELDS = [
    F("decision", "string", enum=["APPROVE_SALE", "CLOSE_SALE"]),
    F("disposition_mode", "string", required=False, default=None,
      enum=["NONE", "INDIVIDUAL", "PORTFOLIO_LOT"]),
    F("bpo_value_cents", "money", required=False, default=None),
    F("lot_code", "string", required=False, default=None),
    F("net_sale_proceeds_cents", "money", required=False, default=None),
]


@bp.post("/homes/<home_id>/disposition-decision")
def disposition_decision(home_id):
    data = validate(body_json(), DISPOSITION_FIELDS)
    if data["decision"] == "CLOSE_SALE" and data["net_sale_proceeds_cents"] is None:
        fail("ERR_INVALID_REQUEST", "Field 'net_sale_proceeds_cents' is required.")
    authorize(["InvestmentCommittee"])
    home = must_find("homes", home_id, "ERR_HOME_NOT_FOUND")

    if data["decision"] == "APPROVE_SALE":
        if home["asset_status"] != "STABILIZED":
            fail("ERR_INVALID_STATE")
        if calc.leasing_posture(home) == "FROZEN":
            fail("ERR_DISPOSITION_NOT_ELIGIBLE")
        mode = data["disposition_mode"] if data["disposition_mode"] is not None else "NONE"
        if mode == "INDIVIDUAL" and home["occupancy_status"] != "VACANT":
            fail("ERR_DISPOSITION_NOT_ELIGIBLE")
        home["asset_status"] = "DISPOSITION_APPROVED"
        home["disposition_mode"] = mode
        if data["bpo_value_cents"] is not None:
            home["bpo_value_cents"] = data["bpo_value_cents"]
        if data["lot_code"] is not None:
            home["lot_code"] = data["lot_code"]
        elif mode == "INDIVIDUAL":
            home["lot_code"] = ""
        store.touch(home)
        cascades.recompute_posture(home)
        return ok(views.home_view(home))

    if home["asset_status"] != "DISPOSITION_APPROVED":
        fail("ERR_INVALID_STATE")
    case = cascades.approved_case(home["id"])
    basis = 0
    if case is not None:
        basis = case.get("realized_all_in_basis_cents")
        if basis is None:
            basis = case.get("underwritten_all_in_basis_cents") or 0
    home["net_sale_proceeds_cents"] = data["net_sale_proceeds_cents"]
    home["realized_gain_cents"] = int(data["net_sale_proceeds_cents"]) - int(basis)
    home["asset_status"] = "DISPOSED"
    store.touch(home)
    cascades.recompute_posture(home)
    return ok(views.home_view(home))
