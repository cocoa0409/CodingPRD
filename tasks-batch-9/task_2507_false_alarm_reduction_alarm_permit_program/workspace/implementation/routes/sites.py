"""Premises records — the address is the counting key for the whole program."""

from flask import Blueprint

import engine
import rt
from core import F, authenticate, check_owner, created, listing, ok, q, validate
from errors import ApiError
from store import base_row, store

bp = Blueprint("sites", __name__)

READ_ONE_ROLES = ["ProgramAdministrator", "PermitClerk", "BillingClerk",
                  "FalseAlarmReviewOfficer", "HearingOfficer",
                  "PoliceDispatchSupervisor", "AlarmUser"]
READ_MANY_ROLES = ["ProgramAdministrator", "PermitClerk", "BillingClerk",
                   "FalseAlarmReviewOfficer", "PoliceDispatchSupervisor"]
SUMMARY_ROLES = ["ProgramAdministrator", "PermitClerk", "BillingClerk",
                 "FalseAlarmReviewOfficer", "HearingOfficer", "AlarmUser"]

OCCUPANCY = ("RESIDENTIAL", "COMMERCIAL", "SCHOOL", "FINANCIAL", "GOVERNMENT")

CREATE_FIELDS = [
    F("address_key", "string", nonempty=True),
    F("street_address", "string"),
    F("city", "string"),
    F("zip_code", "string"),
    F("occupancy_class", "enum", values=OCCUPANCY),
    F("police_beat", "string"),
]


def normalize_address(value):
    """Upper-case and collapse whitespace; the comparison key, not the echo."""
    return " ".join(str(value).upper().split())


@bp.post("/alarm-sites")
def create_site():
    ctx = authenticate(["ProgramAdministrator", "PermitClerk"])
    data = validate(ctx.body, CREATE_FIELDS)
    key = normalize_address(data["address_key"])
    for existing in store.alarm_sites.values():
        if existing.get("status") != "ACTIVE":
            continue
        if existing.get("_address_norm") == key:
            raise ApiError("ERR_DUPLICATE_ADDRESS_KEY",
                           "A live premises already holds this address key.")
    row = base_row()
    row["address_key"] = data["address_key"]
    row["street_address"] = data["street_address"]
    row["city"] = data["city"]
    row["zip_code"] = data["zip_code"]
    row["occupancy_class"] = data["occupancy_class"]
    row["police_beat"] = data["police_beat"]
    row["status"] = "ACTIVE"
    row["governing_fee_schedule_id"] = None
    row["response_status"] = "RESPONSE_ACTIVE"
    row["chargeable_count_window"] = 0
    row["chargeable_count_rolling_365"] = 0
    row["chargeable_count_permit_year"] = 0
    row["lifetime_assessed_cents"] = 0
    row["outstanding_balance_cents"] = 0
    row["credit_balance_cents"] = 0
    row["unpermitted_system_count"] = 0
    row["lifted_suspension_count"] = 0
    row["ecv_callable_contact_count"] = 0
    row["renewal_block_active"] = False
    row["_address_norm"] = key
    store.alarm_sites[row["id"]] = row
    return created(row)


@bp.get("/alarm-sites/<site_id>")
def get_site(site_id):
    ctx = authenticate(READ_ONE_ROLES)
    site = rt.resolve("AlarmSite", site_id)
    check_owner(ctx, site_id=site["id"])
    engine.rollup_site(site, bump=False)
    return ok(site)


@bp.get("/alarm-sites")
def list_sites():
    authenticate(READ_MANY_ROLES)
    rows = rt.all_rows("AlarmSite")
    for row in rows:
        engine.rollup_site(row, bump=False)
    filters = (("governing_fee_schedule_id", q("governing_fee_schedule_id")),
               ("response_status", q("response_status")),
               ("occupancy_class", q("occupancy_class")),
               ("status", q("status")))
    for field, value in filters:
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    address_key = q("address_key")
    if address_key is not None:
        key = normalize_address(address_key)
        rows = [r for r in rows if r.get("_address_norm") == key]
    return listing(rows, rt.fields("AlarmSite"))


@bp.get("/alarm-sites/<site_id>/false-alarm-summary")
def site_summary(site_id):
    ctx = authenticate(SUMMARY_ROLES)
    site = rt.resolve("AlarmSite", site_id)
    check_owner(ctx, site_id=site["id"])
    engine.rollup_site(site, bump=False)
    return ok(site)
