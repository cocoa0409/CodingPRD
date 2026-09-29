"""The vendor network and its dated trade certifications."""
from flask import Blueprint

import store
import views
from envelope import created, ok, paginate
from errors import fail
from validation import F, authorize, body_json, must_find, parse_date_value, validate

bp = Blueprint("vendors", __name__)

VENDOR_READ = ["VendorManager", "OperationsManager", "PortfolioAdmin", "RegionalDirector", "Vendor"]
VENDOR_LIST = ["VendorManager", "OperationsManager", "PortfolioAdmin", "RegionalDirector"]
CERT_READ = ["VendorManager", "OperationsManager", "PortfolioAdmin", "RegionalDirector", "Vendor"]

VENDOR_FIELDS = [
    F("legal_name", "string"),
    F("market_id", "string"),
    F("daily_crew_capacity", "count", minimum=1),
    F("cost_index_bps", "bps", minimum=5000, maximum=20000),
    F("quality_score_bps", "bps", minimum=0, maximum=10000),
    F("insurance_expires_on", "date"),
]

VENDOR_PATCH_FIELDS = [
    F("daily_crew_capacity", "count", required=False, default=None, minimum=1),
    F("cost_index_bps", "bps", required=False, default=None, minimum=5000, maximum=20000),
    F("quality_score_bps", "bps", required=False, default=None, minimum=0, maximum=10000),
    F("insurance_expires_on", "date", required=False, default=None),
]


@bp.post("/vendors")
def create_vendor():
    data = validate(body_json(), VENDOR_FIELDS)
    authorize(["VendorManager"])
    market = must_find("markets", data["market_id"], "ERR_MARKET_NOT_FOUND")
    row = store.base_row()
    row.update({
        "legal_name": data["legal_name"],
        "market_id": market["id"],
        "daily_crew_capacity": data["daily_crew_capacity"],
        "cost_index_bps": data["cost_index_bps"],
        "quality_score_bps": data["quality_score_bps"],
        "insurance_expires_on": data["insurance_expires_on"],
        "status": "ACTIVE",
        "committed_crew_days": 0,
        "suspension_reason": "",
    })
    store.insert("vendors", row)
    return created(views.public(row))


@bp.get("/vendors/<vendor_id>")
def read_vendor(vendor_id):
    authorize(VENDOR_READ)
    row = must_find("vendors", vendor_id, "ERR_VENDOR_NOT_FOUND")
    return ok(views.public(row))


@bp.get("/vendors")
def list_vendors():
    authorize(VENDOR_LIST)
    rows = views.filtered("vendors", [
        ("market_id", "market_id", "string"),
        ("status", "status", "string"),
    ])
    return paginate(rows, views.public)


@bp.patch("/vendors/<vendor_id>")
def update_vendor(vendor_id):
    data = validate(body_json(), VENDOR_PATCH_FIELDS)
    authorize(["VendorManager"])
    vendor = must_find("vendors", vendor_id, "ERR_VENDOR_NOT_FOUND")
    for name in ("daily_crew_capacity", "cost_index_bps", "quality_score_bps",
                 "insurance_expires_on"):
        if data[name] is not None:
            vendor[name] = data[name]
    store.touch(vendor)
    return ok(views.public(vendor))


@bp.post("/vendors/<vendor_id>/status")
def set_vendor_status(vendor_id):
    data = validate(body_json(), [
        F("status", "string", enum=["ACTIVE", "SUSPENDED"]),
        F("suspension_reason", "string", required=False, default=None),
    ])
    authorize(["VendorManager"])
    vendor = must_find("vendors", vendor_id, "ERR_VENDOR_NOT_FOUND")
    vendor["status"] = data["status"]
    if data["suspension_reason"] is not None:
        vendor["suspension_reason"] = data["suspension_reason"]
    elif data["status"] == "ACTIVE":
        vendor["suspension_reason"] = ""
    store.touch(vendor)
    return ok(views.public(vendor))


# ---------------------------------------------------------------------------
# Vendor certifications
# ---------------------------------------------------------------------------

CERT_FIELDS = [
    F("vendor_id", "string"),
    F("certification_code", "string"),
    F("effective_on", "date"),
    F("expires_on", "date"),
]


@bp.post("/vendor-certifications")
def create_certification():
    data = validate(body_json(), CERT_FIELDS)
    if parse_date_value(data["effective_on"]) > parse_date_value(data["expires_on"]):
        fail("ERR_INVALID_REQUEST", "Field 'expires_on' may not precede 'effective_on'.")
    authorize(["VendorManager"])
    vendor = must_find("vendors", data["vendor_id"], "ERR_VENDOR_NOT_FOUND")
    for existing in store.all_rows("vendor_certifications"):
        if (existing["vendor_id"] == vendor["id"]
                and existing["certification_code"] == data["certification_code"]
                and existing["status"] == "ACTIVE"):
            fail("ERR_DUPLICATE_CERTIFICATION")
    row = store.base_row()
    row.update({
        "vendor_id": vendor["id"],
        "certification_code": data["certification_code"],
        "effective_on": data["effective_on"],
        "expires_on": data["expires_on"],
        "status": "ACTIVE",
    })
    store.insert("vendor_certifications", row)
    return created(views.public(row))


@bp.get("/vendor-certifications/<certification_id>")
def read_certification(certification_id):
    authorize(CERT_READ)
    row = must_find("vendor_certifications", certification_id,
                    "ERR_VENDOR_CERTIFICATION_NOT_FOUND")
    return ok(views.public(row))


@bp.get("/vendor-certifications")
def list_certifications():
    authorize(CERT_READ)
    rows = views.filtered("vendor_certifications", [
        ("vendor_id", "vendor_id", "string"),
        ("certification_code", "certification_code", "string"),
        ("status", "status", "string"),
    ])
    return paginate(rows, views.public)


@bp.post("/vendor-certifications/<certification_id>/revoke")
def revoke_certification(certification_id):
    data = validate(body_json(), [F("reason", "string")])
    authorize(["VendorManager"])
    cert = must_find("vendor_certifications", certification_id,
                     "ERR_VENDOR_CERTIFICATION_NOT_FOUND")
    if cert["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE")
    cert["status"] = "REVOKED"
    store.touch(cert)
    return ok(views.public(cert))
