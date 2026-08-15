"""Installer companies and the five staff registries."""

import db
import errors
import helpers as H
import middleware as mw
import response as R

S = db.STORE
ADMIN = ("PlatformAdmin",)

# (collection, id_param, unique_field) for each staff registry
STAFF = {
    "soil-scientists": ("soil_scientists", "ssid", "license_number"),
    "system-designers": ("system_designers", "dsid", "license_number"),
    "inspectors": ("inspectors", "iid", "license_number"),
    "health-officers": ("health_officers", "hid", "badge_number"),
    "project-managers": ("project_managers", "pmid", "employee_number"),
}

PREFIX = "/septic-ops"


def _create_company():
    b = mw.body()
    legal_name = mw.req_str(b, "legal_name")
    license_number = mw.req_str(b, "license_number")
    county_codes = b.get("county_codes")
    if (not isinstance(county_codes, list)
            or any(not isinstance(x, str) or not x for x in county_codes)):
        errors.invalid_request("county_codes must be a list of non-empty strings")
    if any(c["license_number"] == license_number
           for c in S["installer_companies"].values()):
        errors.invalid_request("license_number must be unique across companies")
    rec = db.create_record("installer_companies", {
        "legal_name": legal_name,
        "license_number": license_number,
        "county_codes": list(county_codes),
    })
    return R.respond_object(rec, 201)


def _list_companies():
    return R.respond_list(H.rows_of("installer_companies"))


def _get_company(cid):
    return R.respond_object(H.resolve_company(cid))


def _staff_create(collection, unique_field, cid):
    company = H.resolve_company(cid)
    b = mw.body()
    full_name = mw.req_str(b, "full_name")
    unique_val = mw.req_str(b, unique_field)
    if any(r[unique_field] == unique_val
           for r in H.children(collection, "installer_company_id", cid)):
        errors.invalid_request(
            "{} must be unique within the company registry".format(unique_field))
    rec = db.create_record(collection, {
        "installer_company_id": company["id"],
        "full_name": full_name,
        unique_field: unique_val,
    })
    return R.respond_object(rec, 201)


def _staff_list(collection, cid):
    H.resolve_company(cid)
    return R.respond_list(H.children(collection, "installer_company_id", cid))


def _staff_get(collection, cid, row_id):
    return R.respond_object(H.resolve_staff(collection, cid, row_id))


def register(app):
    app.add_url_rule(PREFIX + "/installer-companies", "company_create",
                     mw.auth(*ADMIN)(_create_company),
                     methods=["POST"], strict_slashes=False)
    app.add_url_rule(PREFIX + "/installer-companies", "company_list",
                     mw.auth()(_list_companies),
                     methods=["GET"], strict_slashes=False)
    app.add_url_rule(PREFIX + "/installer-companies/<cid>", "company_get",
                     mw.auth()(_get_company),
                     methods=["GET"], strict_slashes=False)

    for path_name, (collection, id_param, unique_field) in STAFF.items():
        base = PREFIX + "/installer-companies/<cid>/" + path_name

        def create(cid, collection=collection, unique_field=unique_field):
            return _staff_create(collection, unique_field, cid)

        def listing(cid, collection=collection):
            return _staff_list(collection, cid)

        def get_one(cid, _id=None, collection=collection, id_param=id_param, **kw):
            return _staff_get(collection, cid, kw[id_param])

        app.add_url_rule(base, path_name + "_create", mw.auth(*ADMIN)(create),
                         methods=["POST"], strict_slashes=False)
        app.add_url_rule(base, path_name + "_list", mw.auth()(listing),
                         methods=["GET"], strict_slashes=False)
        app.add_url_rule(base + "/<" + id_param + ">", path_name + "_get",
                         mw.auth()(get_one), methods=["GET"], strict_slashes=False)
