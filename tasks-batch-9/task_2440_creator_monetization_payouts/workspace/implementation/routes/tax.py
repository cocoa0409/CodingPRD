"""Tax documentation lifecycle (PRD 3.2)."""
from flask import Blueprint, request

import calc
import serialize
from apierrors import fail
from envelope import created, ok
from fields import F
from gate import endpoint
from listutil import filter_rows, respond
from store import db, days, sort_rows

bp = Blueprint("tax", __name__)

COUNTRIES = ("US", "GB", "DE", "IN", "BR", "JP")
FORMS = ("W9", "W8BEN")
READ_ROLES = ("Creator", "FinanceOperator", "PlatformAdmin", "Auditor")

CREATE = (
    F("creator_id", "str", required=True),
    F("form_type", "enum", required=True, enum=FORMS),
    F("country_code", "enum", required=True, enum=COUNTRIES),
    F("tin_provided", "bool", default=False),
    F("treaty_claimed", "bool", default=False),
    F("treaty_rate_bps", "int", default=None, minv=0, maxv=3000),
    F("expected_creator_version", "int", required=True),
)
VERIFY = (
    F("decision", "enum", required=True, enum=("VERIFY", "REJECT")),
    F("rejection_reason", "str"),
)
REVISE = (
    F("form_type", "enum", enum=FORMS),
    F("tin_provided", "bool"),
    F("treaty_claimed", "bool"),
    F("treaty_rate_bps", "int", minv=0, maxv=3000),
)

PATH = (("tax_profile_id", "tax_profiles"),)
OWN = lambda ctx: ctx.path["tax_profile_id"]["creator_id"]


def _form_country_ok(form_type, country_code):
    if form_type == "W9":
        return country_code == "US"
    return country_code != "US"


@bp.route("/monetization/tax-profiles", methods=["POST"])
@endpoint(roles=("Creator", "FinanceOperator"), fields=CREATE,
          refs=(("creator_id", "creators"),),
          owner=lambda ctx: ctx.data.get("creator_id"))
def create_tax_profile(ctx):
    creator = ctx.refs["creator_id"]
    data = ctx.data
    if data["expected_creator_version"] != creator["version"]:          # 43
        fail("ERR_STALE_CREATOR_VERSION",
             "expected_creator_version does not match the creator's version.")
    if data["country_code"] != creator["country_code"]:                 # 52
        fail("ERR_TAX_COUNTRY_MISMATCH",
             "country_code must equal the creator's country_code.")
    if not _form_country_ok(data["form_type"], data["country_code"]):    # 53
        fail("ERR_TAX_FORM_COUNTRY_INVALID",
             "form_type is not valid for country_code.")
    if data["treaty_claimed"] and data["treaty_rate_bps"] is None:      # 54
        fail("ERR_TREATY_RATE_REQUIRED",
             "treaty_rate_bps is required when treaty_claimed is true.")
    if not data["treaty_claimed"] and data["treaty_rate_bps"] is not None:  # 55
        fail("ERR_TREATY_RATE_FORBIDDEN",
             "treaty_rate_bps must be null when treaty_claimed is false.")

    for prior in sort_rows([p for p in db.rows("tax_profiles")
                            if p["creator_id"] == creator["id"]
                            and p["status"] != "SUPERSEDED"],
                           lambda r: (r["created_at"],)):
        prior["status"] = "SUPERSEDED"      # withholding_rate_bps stays frozen
        db.touch(prior)

    row = db.insert("tax_profiles", {
        "creator_id": creator["id"],
        "form_type": data["form_type"],
        "country_code": data["country_code"],
        "tin_provided": data["tin_provided"],
        "treaty_claimed": data["treaty_claimed"],
        "treaty_rate_bps": data["treaty_rate_bps"],
        "status": "DRAFT",
        "withholding_rate_bps": 0,
        "submitted_at": None,
        "verified_at": None,
        "expires_at": None,
        "rejection_reason": None,
    })
    row["withholding_rate_bps"] = calc.resolve_profile_rate(row)
    db.touch(creator)
    return created(serialize.tax_profile(row))


@bp.route("/monetization/tax-profiles", methods=["GET"])
@endpoint(roles=READ_ROLES, listing=True)
def list_tax_profiles(ctx):
    rows = db.rows("tax_profiles")
    if ctx.is_creator:
        rows = [r for r in rows if r["creator_id"] == ctx.user_id]
    rows = filter_rows(rows, request.args, {
        "creator_id": "creator_id", "status": "status", "form_type": "form_type"})
    rows = sort_rows(rows, lambda r: (r["created_at"],))
    return respond(ctx, rows, serialize.tax_profile)


@bp.route("/monetization/tax-profiles/<tax_profile_id>", methods=["GET"])
@endpoint(roles=READ_ROLES, path=PATH, owner=OWN)
def read_tax_profile(ctx, tax_profile_id):
    return ok(serialize.tax_profile(ctx.path["tax_profile_id"]))


@bp.route("/monetization/tax-profiles/<tax_profile_id>/submit", methods=["POST"])
@endpoint(roles=("Creator",), path=PATH, owner=OWN)
def submit_tax_profile(ctx, tax_profile_id):
    row = ctx.path["tax_profile_id"]
    if row["status"] != "DRAFT":                                        # 13
        fail("ERR_TAX_PROFILE_NOT_DRAFT", "The profile is not DRAFT.")
    if row["treaty_claimed"] and row["treaty_rate_bps"] is None:        # 54
        fail("ERR_TREATY_RATE_REQUIRED",
             "treaty_rate_bps is required when treaty_claimed is true.")
    row["status"] = "SUBMITTED"
    row["submitted_at"] = db.now
    row["withholding_rate_bps"] = calc.resolve_profile_rate(row)
    db.touch(row)
    return ok(serialize.tax_profile(row))


@bp.route("/monetization/tax-profiles/<tax_profile_id>/verify", methods=["POST"])
@endpoint(roles=("FinanceOperator",), path=PATH, fields=VERIFY)
def verify_tax_profile(ctx, tax_profile_id):
    row = ctx.path["tax_profile_id"]
    if row["status"] != "SUBMITTED":                                    # 14
        fail("ERR_TAX_PROFILE_NOT_SUBMITTED", "The profile is not SUBMITTED.")
    decision = ctx.data["decision"]
    reason = ctx.data.get("rejection_reason")
    if decision == "REJECT" and (reason is None or not reason.strip()):  # 57
        fail("ERR_REJECTION_REASON_REQUIRED",
             "rejection_reason is required on a REJECT decision.")
    if decision == "VERIFY" and reason is not None:                     # 58
        fail("ERR_REJECTION_REASON_FORBIDDEN",
             "rejection_reason must be absent on a VERIFY decision.")
    if decision == "VERIFY":
        row["status"] = "VERIFIED"
        row["verified_at"] = db.now
        row["expires_at"] = db.now + days(calc.TAX_FORM_VALIDITY_DAYS)
    else:
        row["status"] = "REJECTED"
        row["rejection_reason"] = reason
    row["withholding_rate_bps"] = calc.resolve_profile_rate(row)
    db.touch(row)
    return ok(serialize.tax_profile(row))


@bp.route("/monetization/tax-profiles/<tax_profile_id>/revise", methods=["POST"])
@endpoint(roles=("Creator",), path=PATH, fields=REVISE, owner=OWN)
def revise_tax_profile(ctx, tax_profile_id):
    row = ctx.path["tax_profile_id"]
    if row["status"] != "REJECTED":                                     # 15
        fail("ERR_TAX_PROFILE_NOT_REJECTED", "The profile is not REJECTED.")
    merged = dict(row)
    for name in ("form_type", "tin_provided", "treaty_claimed", "treaty_rate_bps"):
        if name in ctx.data and ctx.data[name] is not None:
            merged[name] = ctx.data[name]
        elif name in ctx.data and ctx.data[name] is None and ctx.supplied(name):
            merged[name] = None
    if not _form_country_ok(merged["form_type"], row["country_code"]):   # 53
        fail("ERR_TAX_FORM_COUNTRY_INVALID",
             "form_type is not valid for the profile's country_code.")
    if merged["treaty_claimed"] and merged["treaty_rate_bps"] is None:   # 54
        fail("ERR_TREATY_RATE_REQUIRED",
             "treaty_rate_bps is required when treaty_claimed is true.")
    if not merged["treaty_claimed"] and merged["treaty_rate_bps"] is not None:  # 55
        fail("ERR_TREATY_RATE_FORBIDDEN",
             "treaty_rate_bps must be null when treaty_claimed is false.")
    for name in ("form_type", "tin_provided", "treaty_claimed", "treaty_rate_bps"):
        row[name] = merged[name]
    row["rejection_reason"] = None
    row["status"] = "DRAFT"
    row["withholding_rate_bps"] = calc.resolve_profile_rate(row)
    db.touch(row)
    return ok(serialize.tax_profile(row))
