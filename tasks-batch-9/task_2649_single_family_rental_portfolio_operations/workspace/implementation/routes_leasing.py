"""Rental applications, screening, the deposit stack and lease execution."""
from flask import Blueprint

import calc
import cascades
import store
import views
from envelope import created, ok, paginate
from errors import fail
from validation import F, authorize, body_json, must_find, validate

bp = Blueprint("leasing", __name__)

APP_READ = ["LeasingAgent", "PortfolioAdmin", "RegionalDirector", "Prospect"]
LEASE_READ = ["LeasingAgent", "PortfolioAdmin", "RegionalDirector", "Prospect"]

APP_FIELDS = [
    F("prospect_id", "string"),
    F("home_id", "string"),
    F("requested_move_in_date", "date"),
    F("lease_term_months", "count", required=False, default=None, minimum=1),
    F("pet_count", "count", required=False, default=0),
    F("pet_breeds", "array", required=False, default=None, item_kind="string"),
]


@bp.post("/rental-applications")
def create_application():
    data = validate(body_json(), APP_FIELDS)
    authorize(["Prospect", "LeasingAgent"])
    home = must_find("homes", data["home_id"], "ERR_HOME_NOT_FOUND")
    prospect = must_find("prospects", data["prospect_id"], "ERR_PROSPECT_NOT_FOUND")
    for existing in store.all_rows("rental_applications"):
        if (existing["prospect_id"] == prospect["id"] and existing["home_id"] == home["id"]
                and existing["status"] == "SUBMITTED"):
            fail("ERR_DUPLICATE_APPLICATION")
    if prospect["market_id"] != home["market_id"]:
        fail("ERR_MARKET_MISMATCH")
    if prospect["identity_status"] != "VERIFIED":
        fail("ERR_PROSPECT_IDENTITY_UNVERIFIED")
    market = cascades.market_of(home)
    breeds = data["pet_breeds"] if data["pet_breeds"] is not None else []
    restricted = set(market["restricted_breeds"])
    for breed in breeds:
        if breed in restricted:
            fail("ERR_RESTRICTED_BREED")
    pet_count = int(data["pet_count"])
    if pet_count > int(market["max_pets"]) or len(breeds) != pet_count:
        fail("ERR_PET_COUNT_EXCEEDED")

    row = store.base_row()
    row.update({
        "prospect_id": prospect["id"],
        "home_id": home["id"],
        "requested_move_in_date": data["requested_move_in_date"],
        "lease_term_months": (data["lease_term_months"] if data["lease_term_months"] is not None
                              else market["standard_lease_term_months"]),
        "pet_count": pet_count,
        "pet_breeds": breeds,
        "rent_to_income_bps": 0,
        "security_deposit_cents": 0,
        "pet_deposit_cents": 0,
        "total_move_in_deposit_cents": 0,
        "risk_multiplier_bps": 0,
        "adverse_action_reason": "NONE",
        "status": "SUBMITTED",
    })
    store.insert("rental_applications", row)
    return created(views.public(row))


@bp.get("/rental-applications/<application_id>")
def read_application(application_id):
    authorize(APP_READ)
    row = must_find("rental_applications", application_id, "ERR_RENTAL_APPLICATION_NOT_FOUND")
    return ok(views.public(row))


@bp.get("/rental-applications")
def list_applications():
    authorize(APP_READ)
    rows = views.filtered("rental_applications", [
        ("prospect_id", "prospect_id", "string"),
        ("home_id", "home_id", "string"),
        ("status", "status", "string"),
        ("adverse_action_reason", "adverse_action_reason", "string"),
    ])
    return paginate(rows, views.public)


@bp.post("/rental-applications/<application_id>/screen")
def screen_application(application_id):
    authorize(["LeasingAgent"])
    app_row = must_find("rental_applications", application_id,
                        "ERR_RENTAL_APPLICATION_NOT_FOUND")
    if app_row["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE")
    home = store.get("homes", app_row["home_id"])
    prospect = store.get("prospects", app_row["prospect_id"])
    market = cascades.market_of(home)
    if home["occupancy_status"] != "VACANT":
        fail("ERR_HOME_NOT_VACANT")
    if prospect["identity_status"] != "VERIFIED":
        fail("ERR_PROSPECT_IDENTITY_UNVERIFIED")
    if calc.leasing_posture(home) == "FROZEN":
        fail("ERR_HOME_SHOWINGS_BLOCKED")

    outcome = calc.screening_decision(market, prospect, home["asking_rent_cents"])
    app_row["rent_to_income_bps"] = outcome["rent_to_income_bps"]
    app_row["status"] = outcome["status"]
    app_row["adverse_action_reason"] = outcome["adverse_action_reason"]
    if outcome["status"] == "DENIED":
        app_row["risk_multiplier_bps"] = 0
        app_row["security_deposit_cents"] = 0
        app_row["pet_deposit_cents"] = 0
        app_row["total_move_in_deposit_cents"] = 0
        store.touch(app_row)
        return ok(views.public(app_row))

    multiplier = outcome["risk_multiplier_bps"]
    security, pet_deposit, total = calc.deposit_amounts(
        market, app_row, home["asking_rent_cents"], multiplier)
    app_row["risk_multiplier_bps"] = multiplier
    app_row["security_deposit_cents"] = security
    app_row["pet_deposit_cents"] = pet_deposit
    app_row["total_move_in_deposit_cents"] = total
    store.touch(app_row)
    if home["occupancy_status"] == "VACANT":
        home["occupancy_status"] = "RESERVED"
        store.touch(home)
    return ok(views.public(app_row))


# ---------------------------------------------------------------------------
# Leases
# ---------------------------------------------------------------------------

APPROVED_APP_STATUSES = {"APPROVED", "CONDITIONAL_APPROVED"}
LIVE_LEASE_STATUSES = {"DRAFT", "EXECUTED"}


@bp.post("/leases")
def create_lease():
    data = validate(body_json(), [
        F("application_id", "string"),
        F("start_date", "date"),
        F("term_months", "count", minimum=1),
        F("monthly_rent_cents", "money", minimum=1),
    ])
    role, user_id = authorize(["LeasingAgent", "RegionalDirector"])
    app_row = must_find("rental_applications", data["application_id"],
                        "ERR_RENTAL_APPLICATION_NOT_FOUND")
    if app_row["status"] not in APPROVED_APP_STATUSES:
        fail("ERR_APPLICATION_NOT_APPROVED")
    home = store.get("homes", app_row["home_id"])
    for existing in store.all_rows("leases"):
        if existing["home_id"] == home["id"] and existing["status"] in LIVE_LEASE_STATUSES:
            fail("ERR_LEASE_ALREADY_EXISTS")
    market = cascades.market_of(home)
    asking = int(home["asking_rent_cents"])
    floor = asking - calc.apply_bps(asking, market["max_rent_concession_bps"])
    if int(data["monthly_rent_cents"]) < floor:
        fail("ERR_RENT_CONCESSION_EXCEEDED")
    if (int(data["term_months"]) != int(market["standard_lease_term_months"])
            and role != "RegionalDirector"):
        fail("ERR_LEASE_TERM_INVALID")

    row = store.base_row()
    row.update({
        "application_id": app_row["id"],
        "home_id": home["id"],
        "start_date": data["start_date"],
        "term_months": data["term_months"],
        "monthly_rent_cents": data["monthly_rent_cents"],
        "required_deposit_cents": int(app_row["total_move_in_deposit_cents"]),
        "deposit_paid_cents": 0,
        "signed_on": "",
        "void_reason": "",
        "status": "DRAFT",
    })
    store.insert("leases", row)
    return created(views.public(row))


@bp.get("/leases/<lease_id>")
def read_lease(lease_id):
    authorize(LEASE_READ)
    row = must_find("leases", lease_id, "ERR_LEASE_NOT_FOUND")
    return ok(views.public(row))


@bp.get("/leases")
def list_leases():
    authorize(LEASE_READ)
    rows = views.filtered("leases", [
        ("application_id", "application_id", "string"),
        ("home_id", "home_id", "string"),
        ("status", "status", "string"),
    ])
    return paginate(rows, views.public)


@bp.post("/leases/<lease_id>/deposit-payments")
def record_deposit_payment(lease_id):
    data = validate(body_json(), [F("amount_cents", "money", minimum=1)])
    authorize(["LeasingAgent"])
    lease = must_find("leases", lease_id, "ERR_LEASE_NOT_FOUND")
    if lease["status"] != "DRAFT":
        fail("ERR_INVALID_STATE")
    if int(lease["deposit_paid_cents"]) + int(data["amount_cents"]) > int(
            lease["required_deposit_cents"]):
        fail("ERR_DEPOSIT_OVERPAYMENT")
    lease["deposit_paid_cents"] = int(lease["deposit_paid_cents"]) + int(data["amount_cents"])
    store.touch(lease)
    return ok(views.public(lease))


@bp.post("/leases/<lease_id>/execute")
def execute_lease(lease_id):
    data = validate(body_json(), [F("signed_on", "date")])
    authorize(["LeasingAgent"])
    lease = must_find("leases", lease_id, "ERR_LEASE_NOT_FOUND")
    if lease["status"] != "DRAFT":
        fail("ERR_INVALID_STATE")
    home = store.get("homes", lease["home_id"])
    if calc.leasing_posture(home) != "OPEN":
        fail("ERR_HOME_LEASING_FROZEN")
    if int(lease["deposit_paid_cents"]) < int(lease["required_deposit_cents"]):
        fail("ERR_DEPOSIT_NOT_FUNDED")

    lease["status"] = "EXECUTED"
    lease["signed_on"] = data["signed_on"]
    store.touch(lease)
    if home["occupancy_status"] == "RESERVED":
        home["occupancy_status"] = "OCCUPIED"
        store.touch(home)
    for slot in cascades.home_slots(home["id"]):
        if slot["status"] == "AVAILABLE":
            slot["status"] = "CANCELLED"
            slot["cancel_reason"] = "HOME_LEASED"
            store.touch(slot)
    cascades.recompute_realized(home)
    return ok(views.public(lease))


@bp.post("/leases/<lease_id>/void")
def void_lease(lease_id):
    data = validate(body_json(), [F("reason", "string")])
    authorize(["LeasingAgent", "RegionalDirector"])
    lease = must_find("leases", lease_id, "ERR_LEASE_NOT_FOUND")
    if lease["status"] != "DRAFT":
        fail("ERR_INVALID_STATE")
    lease["status"] = "VOIDED"
    lease["void_reason"] = data["reason"]
    store.touch(lease)
    home = store.get("homes", lease["home_id"])
    if home is not None and home["occupancy_status"] == "RESERVED":
        home["occupancy_status"] = "VACANT"
        store.touch(home)
    return ok(views.public(lease))
