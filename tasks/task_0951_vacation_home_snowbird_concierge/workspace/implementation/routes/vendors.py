from flask import Blueprint

import calc
import core
import gates
import serialize
from core import D, fail, new_row, now, parse_iso, rhu, touch
from gates import check_state

bp = Blueprint("vendors", __name__)

CREATE_SPEC = [
    ("legal_name", "string", True),
    ("trade", "string", True),
    ("coi_expires_at", "datetime", True),
    ("license_expires_at", "datetime", True),
    ("hourly_rate_cents", "integer", True),
    ("rating", "number", True),
    ("billing_mode", "string", False),
    ("emergency_capable", "boolean", False),
]

CRED_SPEC = [
    ("coi_expires_at", "datetime", False),
    ("license_expires_at", "datetime", False),
    ("rating", "number", False),
    ("hourly_rate_cents", "integer", False),
]


@bp.post("/property-care/vendors")
def create_vendor():
    gates.begin(["Dispatcher", "PlatformAdmin"])
    body = gates.body_json()
    gates.validate_payload(body, CREATE_SPEC)
    vendor = new_row(
        "vendors",
        legal_name=body["legal_name"],
        trade=body["trade"],
        coi_expires_at=parse_iso(body["coi_expires_at"]),
        license_expires_at=parse_iso(body["license_expires_at"]),
        hourly_rate_cents=body["hourly_rate_cents"],
        rating=body["rating"],
        billing_mode=body.get("billing_mode", "MANAGED"),
        status="ONBOARDING",
        emergency_capable=body.get("emergency_capable", False),
        outstanding_key_count=0,
        last_eligibility_evaluated_at=None,
    )
    return core.ok(serialize.vendor(vendor), 201)


@bp.get("/property-care/vendors")
def list_vendors():
    gates.begin(["Dispatcher", "PlatformAdmin", "AccountManager", "StormCoordinator", "Auditor"])
    return gates.list_response("vendors", ["trade", "status", "emergency_capable"], serialize.vendor)


@bp.get("/property-care/vendors/<vid>")
def read_vendor(vid):
    gates.begin(["Dispatcher", "PlatformAdmin", "AccountManager", "StormCoordinator", "Auditor",
                 "Vendor"])
    vendor = gates.fetch_path("vendors", vid)
    return core.ok(serialize.vendor(vendor))


@bp.patch("/property-care/vendors/<vid>/credentials")
def update_credentials(vid):
    gates.begin(["Dispatcher", "PlatformAdmin"])
    vendor = gates.fetch_path("vendors", vid)
    body = gates.body_json()
    gates.validate_payload(body, CRED_SPEC)
    if "coi_expires_at" in body and body["coi_expires_at"] is not None:
        vendor["coi_expires_at"] = parse_iso(body["coi_expires_at"])
    if "license_expires_at" in body and body["license_expires_at"] is not None:
        vendor["license_expires_at"] = parse_iso(body["license_expires_at"])
    if "rating" in body and body["rating"] is not None:
        vendor["rating"] = body["rating"]
    if "hourly_rate_cents" in body and body["hourly_rate_cents"] is not None:
        vendor["hourly_rate_cents"] = body["hourly_rate_cents"]
    vendor["last_eligibility_evaluated_at"] = now()
    if vendor["status"] == "LAPSED" and vendor["coi_expires_at"] > now() and \
            vendor["license_expires_at"] > now():
        vendor["status"] = "ELIGIBLE"
    touch(vendor)
    return core.ok(serialize.vendor(vendor))


@bp.post("/property-care/vendors/<vid>/suspend")
def suspend(vid):
    gates.begin(["Dispatcher", "PlatformAdmin"])
    vendor = gates.fetch_path("vendors", vid)
    check_state("vendor", vendor, ["ELIGIBLE"])
    vendor["status"] = "SUSPENDED"
    touch(vendor)
    return core.ok(serialize.vendor(vendor))


@bp.post("/property-care/vendors/<vid>/reinstate")
def reinstate(vid):
    gates.begin(["Dispatcher", "PlatformAdmin"])
    vendor = gates.fetch_path("vendors", vid)
    check_state("vendor", vendor, ["ONBOARDING", "SUSPENDED"])
    # G8a, in rung order 44, 45, then the un-numbered rating floor (F7)
    if not vendor["coi_expires_at"] > now():
        fail("ERR_VENDOR_COI_EXPIRED", "The certificate of insurance has expired.")
    if not vendor["license_expires_at"] > now():
        fail("ERR_VENDOR_LICENSE_EXPIRED", "The trade licence has expired.")
    if rhu(D(vendor["rating"]), 1) < core.VENDOR_MIN_RATING:
        fail("ERR_VENDOR_RATING_BELOW_FLOOR", "The vendor rating is below the floor.")
    vendor["status"] = "ELIGIBLE"
    vendor["last_eligibility_evaluated_at"] = now()
    touch(vendor)
    return core.ok(serialize.vendor(vendor))


@bp.post("/property-care/vendors/<vid>/refresh-eligibility")
def refresh_eligibility(vid):
    gates.begin(["Dispatcher", "PlatformAdmin"])
    vendor = gates.fetch_path("vendors", vid)
    check_state("vendor", vendor, ["ELIGIBLE"])
    if vendor["coi_expires_at"] <= now() or vendor["license_expires_at"] <= now():
        vendor["status"] = "LAPSED"
    vendor["last_eligibility_evaluated_at"] = now()
    touch(vendor)
    return core.ok(serialize.vendor(vendor))
