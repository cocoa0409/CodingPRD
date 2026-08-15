"""License agreement endpoints."""
from flask import Blueprint

import common
import db
import errors
import middleware
import response
from services import calc

bp = Blueprint("agreements", __name__)

ALL_READERS = ("LicensingAnalyst", "LegalCounsel", "FinanceOfficer", "Licensee", "IPAdmin")

# Fields amendable via PATCH; licensee_id / patent_reference / title /
# effective_date are fixed at creation.
PATCHABLE = [
    ("royalty_base_definition", "enum:NET_SALES,GROSS_SALES"),
    ("base_rate_bp", "int"),
    ("minimum_period_royalty_cents", "int"),
    ("sublicense_allowed", "bool"),
    ("sublicense_passthrough_rate_bp", "int"),
    ("mfl_clause", "bool"),
    ("mfl_mode", "enum:RETROACTIVE,PROSPECTIVE"),
    ("mfl_lookback_quarters", "int"),
    ("audit_window_months", "int"),
    ("underreport_tolerance_bp", "int"),
    ("inventor_shares", "array"),
    ("expiration_date", "datetime"),
]


def _validate_inventor_shares(shares):
    """share_bp sum exactly 10000, inventor_name unique; entries well-formed."""
    if not isinstance(shares, list) or len(shares) == 0:
        raise errors.err_validation("inventor_shares must be a non-empty array")
    seen = set()
    total = 0
    for s in shares:
        if not isinstance(s, dict):
            raise errors.err_validation("inventor_shares entries must be objects")
        for key in s:
            if key not in ("inventor_name", "share_bp"):
                raise errors.err_validation(f"Undeclared field in inventor_shares: {key}")
        if "inventor_name" not in s or "share_bp" not in s:
            raise errors.err_validation(
                "inventor_shares entries require inventor_name and share_bp")
        if not isinstance(s["inventor_name"], str):
            raise errors.err_validation("inventor_name must be a string")
        if not isinstance(s["share_bp"], int) or isinstance(s["share_bp"], bool):
            raise errors.err_validation("share_bp must be an integer")
        if s["inventor_name"] in seen:
            raise errors.err_share_sum_invalid("Duplicate inventor_name")
        seen.add(s["inventor_name"])
        total += s["share_bp"]
    if total != 10000:
        raise errors.err_share_sum_invalid("share_bp values must sum to exactly 10000")


def _validate_numeric_bounds(body, src):
    """Bounds checks for rate/tolerance/window fields. src holds the values."""
    v = src["base_rate_bp"]
    if v <= 0 or v > 10000:
        raise errors.err_validation("base_rate_bp must be > 0 and <= 10000")
    v = src["minimum_period_royalty_cents"]
    if v < 0:
        raise errors.err_validation("minimum_period_royalty_cents must be >= 0")
    v = src["sublicense_passthrough_rate_bp"]
    if v < 0 or v > 10000:
        raise errors.err_validation(
            "sublicense_passthrough_rate_bp must be >= 0 and <= 10000")
    v = src["mfl_lookback_quarters"]
    if v < 1:
        raise errors.err_validation("mfl_lookback_quarters must be >= 1")
    v = src["audit_window_months"]
    if v < 1:
        raise errors.err_validation("audit_window_months must be >= 1")
    v = src["underreport_tolerance_bp"]
    if v < 0 or v >= 10000:
        raise errors.err_validation(
            "underreport_tolerance_bp must be >= 0 and < 10000")


@bp.post("/licensing/license-agreements")
def create_agreement():
    middleware.require_role("LicensingAnalyst")
    body = common.get_body()
    common.validate_body(body, [
        ("licensee_id", "string", True),
        ("patent_reference", "string", True),
        ("title", "string", True),
        ("royalty_base_definition", "enum:NET_SALES,GROSS_SALES", True),
        ("base_rate_bp", "int", True),
        ("minimum_period_royalty_cents", "int", False),
        ("sublicense_allowed", "bool", False),
        ("sublicense_passthrough_rate_bp", "int", False),
        ("mfl_clause", "bool", False),
        ("mfl_mode", "enum:RETROACTIVE,PROSPECTIVE", False),
        ("mfl_lookback_quarters", "int", False),
        ("audit_window_months", "int", False),
        ("underreport_tolerance_bp", "int", False),
        ("inventor_shares", "array", True),
        ("effective_date", "datetime", True),
        ("expiration_date", "datetime", True),
    ])
    # Tier 3: body FK existence
    licensee = db.licensees.get(body["licensee_id"])
    if licensee is None:
        raise errors.err_licensee_not_found()

    merged = {
        "base_rate_bp": body["base_rate_bp"],
        "minimum_period_royalty_cents": body.get("minimum_period_royalty_cents", 0),
        "sublicense_passthrough_rate_bp": body.get("sublicense_passthrough_rate_bp", 0),
        "mfl_lookback_quarters": body.get("mfl_lookback_quarters", 4),
        "audit_window_months": body.get("audit_window_months", 24),
        "underreport_tolerance_bp": body.get("underreport_tolerance_bp", 500),
    }
    _validate_numeric_bounds(body, merged)

    if common.parse_dt(body["expiration_date"]) <= common.parse_dt(body["effective_date"]):
        raise errors.err_validation("expiration_date must be after effective_date")

    _validate_inventor_shares(body["inventor_shares"])

    agr = common.new_resource({
        "licensee_id": body["licensee_id"],
        "patent_reference": body["patent_reference"],
        "title": body["title"],
        "royalty_base_definition": body["royalty_base_definition"],
        "base_rate_bp": body["base_rate_bp"],
        "minimum_period_royalty_cents": merged["minimum_period_royalty_cents"],
        "sublicense_allowed": body.get("sublicense_allowed", False),
        "sublicense_passthrough_rate_bp": merged["sublicense_passthrough_rate_bp"],
        "mfl_clause": body.get("mfl_clause", False),
        "mfl_mode": body.get("mfl_mode", "RETROACTIVE"),
        "mfl_lookback_quarters": merged["mfl_lookback_quarters"],
        "audit_window_months": merged["audit_window_months"],
        "underreport_tolerance_bp": merged["underreport_tolerance_bp"],
        "inventor_shares": [
            {"inventor_name": s["inventor_name"], "share_bp": s["share_bp"]}
            for s in body["inventor_shares"]
        ],
        "effective_date": body["effective_date"],
        "expiration_date": body["expiration_date"],
        "status": "DRAFT",
        "cumulative_accepted_base_cents": 0,
        "cumulative_recognized_revenue_cents": 0,
        "undistributed_pool_cents": 0,
        "mfl_adjusted_rate_bp": None,
        "last_mfl_credit_cents": 0,
    })
    db.agreements[agr["id"]] = agr
    return response.success_object(agr, 201)


@bp.get("/licensing/license-agreements")
def list_agreements():
    user_id, role = middleware.require_role(*ALL_READERS)
    args = common.request.args
    licensee_id = args.get("licensee_id")
    status = args.get("status")
    patent_reference = args.get("patent_reference")
    items = list(db.agreements.values())
    if role == "Licensee":
        items = [a for a in items if a["licensee_id"] == user_id]
    if licensee_id is not None:
        items = [a for a in items if a["licensee_id"] == licensee_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    if patent_reference is not None:
        items = [a for a in items if a["patent_reference"] == patent_reference]
    limit, offset = common.get_pagination()
    page, total = common.paginate(items, limit, offset)
    return response.success_list(page, limit, offset, total)


@bp.get("/licensing/license-agreements/<aid>")
def get_agreement(aid):
    user_id, role = middleware.require_role(
        "LicensingAnalyst", "LegalCounsel", "FinanceOfficer", "Licensee")
    agr = db.agreements.get(aid)
    if agr is None:
        raise errors.err_agreement_not_found()
    if role == "Licensee" and agr["licensee_id"] != user_id:
        raise errors.err_not_resource_owner()
    return response.success_object(agr)


@bp.patch("/licensing/license-agreements/<aid>")
def patch_agreement(aid):
    middleware.require_role("LicensingAnalyst")
    agr = db.agreements.get(aid)
    if agr is None:
        raise errors.err_agreement_not_found()
    body = common.get_body()
    spec = [("expected_agreement_version", "int", True)]
    spec += [(name, kind, False) for name, kind in PATCHABLE]
    common.validate_body(body, spec)
    # OCC check
    if body["expected_agreement_version"] != agr["version"]:
        raise errors.err_stale_version()
    # Only while DRAFT or ACTIVE
    if agr["status"] not in ("DRAFT", "ACTIVE"):
        raise errors.err_agreement_not_active(
            "Agreement terms may only be amended while DRAFT or ACTIVE")

    merged = {k: agr[k] for k in (
        "base_rate_bp", "minimum_period_royalty_cents",
        "sublicense_passthrough_rate_bp", "mfl_lookback_quarters",
        "audit_window_months", "underreport_tolerance_bp")}
    for k in merged:
        if k in body:
            merged[k] = body[k]
    _validate_numeric_bounds(body, merged)

    if "expiration_date" in body and \
            common.parse_dt(body["expiration_date"]) <= common.parse_dt(agr["effective_date"]):
        raise errors.err_validation("expiration_date must be after effective_date")

    if "inventor_shares" in body:
        _validate_inventor_shares(body["inventor_shares"])

    for name, _kind in PATCHABLE:
        if name in body:
            if name == "inventor_shares":
                agr[name] = [
                    {"inventor_name": s["inventor_name"], "share_bp": s["share_bp"]}
                    for s in body[name]
                ]
            else:
                agr[name] = body[name]
    common.touch(agr)
    return response.success_object(agr)


@bp.post("/licensing/license-agreements/<aid>/lifecycle")
def agreement_lifecycle(aid):
    middleware.require_role("LicensingAnalyst")
    agr = db.agreements.get(aid)
    if agr is None:
        raise errors.err_agreement_not_found()
    body = common.get_body()
    common.validate_body(body, [
        ("action", "enum:ACTIVATE,SUSPEND,REINSTATE,TERMINATE", True),
    ])
    action = body["action"]
    cur = agr["status"]

    if action == "ACTIVATE":
        if cur != "DRAFT":
            raise errors.err_agreement_not_active(
                "Only a DRAFT agreement can be activated")
        licensee = db.licensees[agr["licensee_id"]]
        if licensee["status"] != "ACTIVE":
            raise errors.err_licensee_not_active(
                "Licensee must be ACTIVE to activate the agreement")
        if common.parse_dt(agr["expiration_date"]) <= common.logical_now():
            raise errors.err_validation(
                "expiration_date must be in the future to activate")
        agr["status"] = "ACTIVE"
        common.touch(agr)
        # MFL sweep side effect (hop 1 / hop 2 onto other agreements)
        calc.mfl_sweep(agr)
    elif action == "SUSPEND":
        if cur != "ACTIVE":
            raise errors.err_agreement_not_active(
                "Only an ACTIVE agreement can be suspended")
        agr["status"] = "SUSPENDED"
        common.touch(agr)
    elif action == "REINSTATE":
        if cur != "SUSPENDED":
            raise errors.err_agreement_not_active(
                "Only a SUSPENDED agreement can be reinstated")
        agr["status"] = "ACTIVE"
        common.touch(agr)
    elif action == "TERMINATE":
        if cur not in ("ACTIVE", "SUSPENDED"):
            raise errors.err_agreement_not_active(
                "Only an ACTIVE or SUSPENDED agreement can be terminated")
        agr["status"] = "TERMINATED"
        common.touch(agr)
    return response.success_object(agr)
