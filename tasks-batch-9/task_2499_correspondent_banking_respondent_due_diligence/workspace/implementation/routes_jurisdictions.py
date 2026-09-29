"""Jurisdiction reference data (PRD 3.1)."""

from flask import Blueprint

import calc
import cascade
import store
from common import ALL, OPS, arg, eq, eq_bool, need, paged, start, PREFIX
from errors import fail
from response import ok, ok_list
from validate import body, fbool, fenum, fnum, fstr, q2, validate

bp = Blueprint("jurisdictions", __name__)

SANCTIONS = ("PERMITTED", "RESTRICTED", "COMPREHENSIVELY_SANCTIONED")
FATF = ("NONE", "INCREASED_MONITORING", "CALL_FOR_ACTION")
RATINGS = ("LOW", "MEDIUM", "HIGH", "PROHIBITED")

WRITERS = ("PlatformAdmin", "SanctionsOfficer")

CREATE_SPEC = [
    fstr("jurisdiction_code", True, 2, 2),
    fstr("name", True, 1, 120),
    fenum("sanctions_status", SANCTIONS, False),
    fenum("fatf_listing", FATF, False),
    fnum("basel_aml_index", True, 0, 10),
    fbool("secrecy_flag", False),
    fnum("corridor_risk_weight", True, "0.50", "2.50"),
    fbool("nested_correspondent_prohibited", False),
    fenum("max_permitted_risk_rating", RATINGS, False),
]

PATCH_SPEC = [
    fstr("name", False, 1, 120),
    fenum("sanctions_status", SANCTIONS, False),
    fenum("fatf_listing", FATF, False),
    fnum("basel_aml_index", False, 0, 10),
    fbool("secrecy_flag", False),
    fnum("corridor_risk_weight", False, "0.50", "2.50"),
    fbool("nested_correspondent_prohibited", False),
    fenum("max_permitted_risk_rating", RATINGS, False),
]


@bp.post(PREFIX + "/jurisdiction-profiles")
def create_profile():
    start(WRITERS)
    data = body()
    validate(data, CREATE_SPEC)
    code = data["jurisdiction_code"]
    if not (code.isupper() and code.isalpha()):
        fail("ERR_INVALID_REQUEST_BODY",
             "jurisdiction_code must be two uppercase ASCII letters.")
    if store.jurisdiction_by_code(code) is not None:
        fail("ERR_DUPLICATE_RESOURCE",
             "A jurisdiction profile for %s already exists." % code)
    row = store.insert("jurisdictions", {
        "jurisdiction_code": code,
        "name": data["name"],
        "sanctions_status": data.get("sanctions_status") or "PERMITTED",
        "fatf_listing": data.get("fatf_listing") or "NONE",
        "basel_aml_index": q2(data["basel_aml_index"]),
        "secrecy_flag": bool(data.get("secrecy_flag", False)),
        "corridor_risk_weight": q2(data["corridor_risk_weight"]),
        "nested_correspondent_prohibited": bool(
            data.get("nested_correspondent_prohibited", False)),
        "max_permitted_risk_rating": data.get("max_permitted_risk_rating") or "HIGH",
        "jurisdiction_risk_points": None,
    })
    row["jurisdiction_risk_points"] = calc.jurisdiction_risk_points(row)
    return ok(row, 201)


@bp.get(PREFIX + "/jurisdiction-profiles")
def list_profiles():
    start(OPS)
    rows = store.by_seq(store.all_rows("jurisdictions"))
    rows = eq(rows, "sanctions_status", arg("sanctions_status"))
    rows = eq(rows, "fatf_listing", arg("fatf_listing"))
    rows = eq_bool(rows, "nested_correspondent_prohibited",
                   arg("nested_correspondent_prohibited"))
    page, limit, offset, total = paged(rows)
    return ok_list(page, limit, offset, total)


@bp.get(PREFIX + "/jurisdiction-profiles/<profile_id>")
def read_profile(profile_id):
    start(OPS)
    return ok(need("jurisdictions", profile_id))


@bp.patch(PREFIX + "/jurisdiction-profiles/<profile_id>")
def amend_profile(profile_id):
    start(WRITERS)
    row = need("jurisdictions", profile_id)
    data = body()
    validate(data, PATCH_SPEC)
    was_sanctioned = row["sanctions_status"] == "COMPREHENSIVELY_SANCTIONED"
    for field in ("name", "sanctions_status", "fatf_listing",
                  "max_permitted_risk_rating"):
        if data.get(field) is not None:
            row[field] = data[field]
    for field in ("basel_aml_index", "corridor_risk_weight"):
        if data.get(field) is not None:
            row[field] = q2(data[field])
    for field in ("secrecy_flag", "nested_correspondent_prohibited"):
        if field in data and data[field] is not None:
            row[field] = bool(data[field])
    row["jurisdiction_risk_points"] = calc.jurisdiction_risk_points(row)
    store.touch(row)
    if not was_sanctioned and row["sanctions_status"] == "COMPREHENSIVELY_SANCTIONED":
        _sanctions_cascade(row)
    return ok(row)


def _sanctions_cascade(profile):
    code = profile["jurisdiction_code"]
    touched = []
    for resp in store.by_seq(store.all_rows("respondents")):
        if resp["home_jurisdiction_code"] != code or resp["dd_state"] == "TERMINATED":
            continue
        resp["dd_state"] = "RESTRICTED"
        resp["restriction_reason"] = "SANCTIONS_EXPOSURE"
        resp["payment_posture"] = "BLOCKED"
        store.touch(resp)
        touched.append(resp)
    affected = {r["id"] for r in touched}
    for row in store.by_seq(store.all_rows("nested")):
        if row["downstream_jurisdiction_code"] != code:
            continue
        if row["state"] not in calc.NESTED_LIVE:
            continue
        row["state"] = "PROHIBITED"
        row["prohibition_reason"] = "SANCTIONED_JURISDICTION"
        store.touch(row)
        affected.add(row["respondent_bank_id"])
    for respondent_id in sorted(affected):
        resp = store.get("respondents", respondent_id)
        if resp is not None:
            cascade.nested_rollup(resp)
    for resp in touched:
        cascade.block_payments_for_sanctions(store.payments_of(resp["id"]))
