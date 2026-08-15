"""Customers, sites, the deterministic site clock, freeze/close, education."""

import db
import errors
import helpers as H
import middleware as mw
import response as R
import services as svc

S = db.STORE
PM = ("ProjectManager",)
SITES_BASE = "/septic-ops/installer-companies/<cid>/customers/<cuid>/sites"


# ------------------------------------------------------------- customers

def create_customer(cid):
    H.resolve_company(cid)
    b = mw.body()
    full_name = mw.req_str(b, "full_name")
    email = mw.req_str(b, "email")
    phone = mw.req_str(b, "phone")
    if any(c["email"] == email for c in H.children("customers", "installer_company_id", cid)):
        errors.invalid_request("email must be unique within the installer company")
    rec = db.create_record("customers", {
        "installer_company_id": cid,
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "education_completed_at": None,
    })
    return R.respond_object(rec, 201)


def list_customers(cid):
    H.resolve_company(cid)
    return R.respond_list(H.children("customers", "installer_company_id", cid))


def get_customer(cid, cuid):
    return R.respond_object(H.resolve_customer(cid, cuid))


# ----------------------------------------------------------------- sites

def create_site(cid, cuid):
    company = H.resolve_company(cid)
    H.resolve_customer(cid, cuid)
    b = mw.body()
    parcel_id = mw.req_str(b, "parcel_id")
    address_line = mw.req_str(b, "address_line")
    county_code = mw.req_str(b, "county_code")
    high_water_table = mw.req_bool(b, "high_water_table")
    if any(s["parcel_id"] == parcel_id
           for s in H.children("sites", "installer_company_id", cid)):
        errors.invalid_request("parcel_id must be unique within the installer company")
    if county_code not in company["county_codes"]:
        errors.invalid_request("county_code is not covered by the installer company")
    rec = db.create_record("sites", {
        "customer_id": cuid,
        "installer_company_id": cid,
        "parcel_id": parcel_id,
        "address_line": address_line,
        "county_code": county_code,
        "current_period_index": 0,
        "seasonal_freeze_until": -1,
        "status": "OPEN",
        "high_water_table": high_water_table,
    })
    return R.respond_object(rec, 201)


def list_sites(cid, cuid):
    H.resolve_customer(cid, cuid)
    rows = H.children("sites", "customer_id", cuid)
    rows = H.apply_filters(rows, {"status": "status"})
    return R.respond_list(rows)


def get_site(cid, cuid, sid):
    return R.respond_object(H.resolve_site(cid, cuid, sid))


def clock_advance(cid, cuid, sid):
    site = H.resolve_site(cid, cuid, sid)
    b = mw.body()
    by_periods = mw.req_int(b, "by_periods")
    if by_periods < 1:
        errors.invalid_request("by_periods must be a positive integer")
    svc.advance_clock(site, by_periods)
    return R.respond_object(site)


def freeze_site(cid, cuid, sid):
    site = H.resolve_site(cid, cuid, sid)
    b = mw.body()
    freeze_until = mw.req_int(b, "freeze_until_period")
    # (5) state, then (21) freeze window not in the past
    if site["status"] != "OPEN":
        errors.invalid_state("Only an OPEN site may be frozen")
    if freeze_until < site["current_period_index"]:
        raise errors.ApiError(errors.ERR_FREEZE_IN_PAST, 409,
                              "freeze_until_period lies in the past")
    db.set_fields(site, status="FROZEN", seasonal_freeze_until=freeze_until)
    return R.respond_object(site)


def close_site(cid, cuid, sid):
    site = H.resolve_site(cid, cuid, sid)
    # (5) state
    if site["status"] != "OPEN":
        errors.invalid_state("Only an OPEN site may be closed")
    # (23) no open work remains
    open_designs = [d for d in svc.designs_of_site(sid)
                    if d["status"] in ("DRAFT", "SUBMITTED")]
    open_installations = [i for i in svc.installations_of_site(sid)
                          if i["status"] in
                          ("NOT_STARTED", "ROUGH_IN_PROGRESS", "TANK_SET",
                           "FIELD_INSTALLED", "READY_FOR_FINAL", "FAILED_HOLD")]
    open_cases = [r for r in H.children("repair_cases", "site_id", sid)
                  if r["status"] in ("OPEN", "TRIAGED", "IN_REMEDIATION")]
    if open_designs or open_installations or open_cases:
        raise errors.ApiError(errors.ERR_OPEN_WORK_REMAINS, 409,
                              "Site has open designs, installations, or repair cases")
    db.set_fields(site, status="CLOSED")
    return R.respond_object(site)


# ------------------------------------------------------- homeowner education

def deliver_education(cid, cuid):
    customer = H.resolve_customer(cid, cuid)
    b = mw.body()
    site_id = b.get("site_id")
    if not isinstance(site_id, str) or not site_id:
        errors.invalid_request("site_id is required")
    # body FK: the site must exist and belong to this customer/company (422)
    site = S["sites"].get(site_id)
    if (site is None or site["customer_id"] != cuid
            or site["installer_company_id"] != cid):
        errors.fk_not_found("site_id does not reference a site of this customer")
    delivery_period = mw.req_int(b, "delivery_period")
    # (29) at least one COMPLETED installation on the referenced site
    if not any(i["site_id"] == site["id"] and i["status"] == "COMPLETED"
               for i in svc.installations_of_site(site["id"])):
        errors.invalid_state(
            "Homeowner education requires a COMPLETED installation on the site")
    db.set_fields(customer, education_completed_at=db.now_iso())
    return R.respond_object(customer, 201)


def register(app):
    cust = "/septic-ops/installer-companies/<cid>/customers"
    app.add_url_rule(cust, "customer_create", mw.auth(*PM)(create_customer),
                     methods=["POST"], strict_slashes=False)
    app.add_url_rule(cust, "customer_list", mw.auth()(list_customers),
                     methods=["GET"], strict_slashes=False)
    app.add_url_rule(cust + "/<cuid>", "customer_get", mw.auth()(get_customer),
                     methods=["GET"], strict_slashes=False)
    app.add_url_rule(cust + "/<cuid>/education-records", "education_deliver",
                     mw.auth(*PM)(deliver_education),
                     methods=["POST"], strict_slashes=False)

    app.add_url_rule(SITES_BASE, "site_create", mw.auth(*PM)(create_site),
                     methods=["POST"], strict_slashes=False)
    app.add_url_rule(SITES_BASE, "site_list", mw.auth()(list_sites),
                     methods=["GET"], strict_slashes=False)
    app.add_url_rule(SITES_BASE + "/<sid>", "site_get", mw.auth()(get_site),
                     methods=["GET"], strict_slashes=False)
    app.add_url_rule(SITES_BASE + "/<sid>/clock/advance", "site_clock",
                     mw.auth(*PM)(clock_advance),
                     methods=["POST"], strict_slashes=False)
    app.add_url_rule(SITES_BASE + "/<sid>/freeze", "site_freeze",
                     mw.auth(*PM)(freeze_site),
                     methods=["POST"], strict_slashes=False)
    app.add_url_rule(SITES_BASE + "/<sid>/close", "site_close",
                     mw.auth(*PM)(close_site),
                     methods=["POST"], strict_slashes=False)
