"""AccessGrant + DisclosureRequest routes (PRD §3.4, §3.5)."""

import re

from flask import Blueprint, request

from db import (
    add_days,
    all_rows,
    by_id,
    created_asc,
    db,
    fmt_ts,
    new_record,
    now,
    parse_dt,
    serialize,
    stamp,
    touch,
)
from errors import (
    err_ceiling,
    err_counterparty_not_active,
    err_endorsement,
    err_expiry_in_past,
    err_invalid_request,
    err_invalid_state,
    err_marking_evidence,
    err_nda_not_active,
    err_need_to_know,
    err_not_found,
    err_ownership,
    err_posture,
    err_risk_too_high,
    err_sod,
    err_stale_reference,
    err_training_not_current,
    err_unauthorized_role,
)
from middleware import actor, body, require_enum, require_field, require_roles, require_str
from response import ok_list, ok_object, paginate
from services import (
    CLASS_ORDER,
    CLASSIFICATION_CLEARANCE,
    CLEARANCE_ORDER,
    EXECUTE_STALE_DAYS,
    GRANT_MAX_DAYS,
    REJECT_MIN,
    ENDORSEMENT_MIN,
    recompute_counterparty_exposure,
    recompute_grant_count,
    recompute_training_current,
    risk_score_final,
    risk_score_provisional,
)
from decimal import Decimal

bp = Blueprint("access", __name__)

GRANT_STATUSES = ("REQUESTED", "APPROVED", "DENIED", "PROVISIONED", "SUSPENDED", "REVOKED", "EXPIRED")
MARKING_PROTOCOLS = ("STAMPED_CONFIDENTIAL", "ORAL_WITH_FOLLOWUP", "ENCRYPTED_DELIVERY")
DISCLOSURE_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "UNDER_REVIEW",
    "APPROVED",
    "REJECTED",
    "RETURNED",
    "WITHDRAWN",
    "EXECUTED",
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _paginate_list(store_name, filters):
    rows = []
    for r in created_asc(all_rows(store_name)):
        if all(r.get(k) == v for k, v in filters):
            rows.append(serialize(r))
    page, limit, offset, total = paginate(rows, request.args)
    return ok_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# AccessGrant
# ---------------------------------------------------------------------------
@bp.post("/api/grants")
def create_grant():
    user_id, role = actor()
    require_roles(role, "Employee")
    data = body()
    employee_id = require_str(data, "employee_id")
    # Ownership (priority 3) before referenced-entity existence (priority 4).
    if user_id != employee_id:
        raise err_ownership("An employee may request a grant only for themself")
    emp = by_id("employees", employee_id)
    if emp is None:
        raise err_not_found("employee not found")
    asset_id = require_str(data, "asset_id")
    asset = by_id("assets", asset_id)
    if asset is None:
        raise err_not_found("asset not found")
    # Entity-level state gates (priority 6).
    if asset["status"] != "REGISTERED":
        raise err_invalid_state("Asset must be REGISTERED")
    if emp["status"] != "ACTIVE":
        raise err_invalid_state("Employee must be ACTIVE")
    # Need-to-know clearance gate (priority 7).
    required = CLASSIFICATION_CLEARANCE[asset["classification"]]
    if CLEARANCE_ORDER[emp["access_clearance"]] < CLEARANCE_ORDER[required]:
        raise err_need_to_know()
    # Temporal window (priority 8).
    expires_raw = require_field(data, "expires_at")
    expires_dt = parse_dt(expires_raw)
    if expires_dt is None:
        raise err_invalid_request("expires_at must be an ISO 8601 timestamp")
    n = now()
    if not (expires_dt > n and expires_dt <= add_days(n, GRANT_MAX_DAYS)):
        raise err_expiry_in_past()
    justification = require_str(data, "justification")
    rec = new_record(
        "grants",
        {
            "employee_id": employee_id,
            "asset_id": asset_id,
            "justification": justification,
            "expires_at": expires_raw if isinstance(expires_raw, str) else fmt_ts(expires_dt),
            "_expires_at_dt": expires_dt,
            "status": "REQUESTED",
            "requester_user_id": user_id,
            "approved_by_user_id": None,
        },
    )
    return ok_object(serialize(rec), code=201)


@bp.get("/api/grants")
def list_grants():
    _uid, role = actor()
    require_roles(role, "SecurityOfficer", "IPCounsel", "Employee")
    filters = [(f, request.args[f]) for f in ("employee_id", "asset_id", "status") if f in request.args]
    return _paginate_list("grants", filters)


@bp.get("/api/grants/<rid>")
def get_grant(rid):
    _uid, role = actor()
    require_roles(role, "SecurityOfficer", "IPCounsel", "Employee")
    g = by_id("grants", rid)
    if g is None:
        raise err_not_found("grant not found")
    return ok_object(serialize(g))


@bp.post("/api/grants/<rid>/state")
def grant_state(rid):
    user_id, role = actor()
    require_roles(role, "SecurityOfficer", "IPCounsel")
    g = by_id("grants", rid)
    if g is None:
        raise err_not_found("grant not found")
    data = body()
    to_status = require_str(data, "to_status")
    if to_status not in GRANT_STATUSES:
        raise err_invalid_request(f"to_status must be one of {list(GRANT_STATUSES)}")
    cur = g["status"]
    asset = by_id("assets", g["asset_id"])
    emp = by_id("employees", g["employee_id"])

    if to_status == "APPROVED":
        # Per-transition role gate (priority 2): CROWN_JEWEL needs IPCounsel.
        if asset is not None and asset["classification"] == "CROWN_JEWEL" and role != "IPCounsel":
            raise err_unauthorized_role("CROWN_JEWEL approval requires IPCounsel")
        # Segregation of duties (priority 3).
        if user_id == g["requester_user_id"]:
            raise err_sod("The grant requester may not approve it")
        if cur != "REQUESTED":
            raise err_invalid_state(f"Cannot move grant from {cur} to APPROVED")
        if asset is None or asset["status"] != "REGISTERED":
            raise err_invalid_state("Asset must be REGISTERED")
        if emp is None or emp["status"] != "ACTIVE":
            raise err_invalid_state("Employee must be ACTIVE")
        if emp is not None:
            recompute_training_current(emp)
            if not emp["training_current"]:
                raise err_training_not_current()
        g["status"] = "APPROVED"
        g["approved_by_user_id"] = user_id
        touch(g)
        if asset is not None:
            recompute_grant_count(asset)
    elif to_status == "DENIED":
        if cur != "REQUESTED":
            raise err_invalid_state(f"Cannot move grant from {cur} to DENIED")
        g["status"] = "DENIED"
        touch(g)
    elif to_status == "PROVISIONED":
        if role != "SecurityOfficer":
            raise err_unauthorized_role("PROVISIONED requires SecurityOfficer")
        if cur not in ("APPROVED", "SUSPENDED"):
            raise err_invalid_state(f"Cannot move grant from {cur} to PROVISIONED")
        if now() > g["_expires_at_dt"]:
            raise err_invalid_state("Grant has expired")
        g["status"] = "PROVISIONED"
        touch(g)
    elif to_status == "SUSPENDED":
        if role != "SecurityOfficer":
            raise err_unauthorized_role("SUSPENDED requires SecurityOfficer")
        if cur != "PROVISIONED":
            raise err_invalid_state(f"Cannot move grant from {cur} to SUSPENDED")
        g["status"] = "SUSPENDED"
        touch(g)
    elif to_status == "REVOKED":
        if cur not in ("APPROVED", "PROVISIONED", "SUSPENDED"):
            raise err_invalid_state(f"Cannot move grant from {cur} to REVOKED")
        g["status"] = "REVOKED"
        touch(g)
        if asset is not None:
            recompute_grant_count(asset)
    else:  # REQUESTED / EXPIRED are not manual targets
        raise err_invalid_state(f"Cannot move grant from {cur} to {to_status}")
    return ok_object(serialize(g))


# ---------------------------------------------------------------------------
# DisclosureRequest
# ---------------------------------------------------------------------------
@bp.post("/api/disclosures")
def create_disclosure():
    user_id, role = actor()
    require_roles(role, "Employee")
    data = body()
    # The requester is stamped from the caller and must be an Employee id.
    emp = by_id("employees", user_id)
    if emp is None:
        raise err_not_found("requester employee not found")
    asset_id = require_str(data, "asset_id")
    asset = by_id("assets", asset_id)
    if asset is None:
        raise err_not_found("asset not found")
    nda_id = require_str(data, "nda_id")
    nda = by_id("ndas", nda_id)
    if nda is None:
        raise err_not_found("NDA not found")
    if asset["status"] != "REGISTERED":
        raise err_invalid_state("Asset must be REGISTERED")
    cp = by_id("counterparties", nda["counterparty_id"])
    if cp is not None and cp["status"] != "ACTIVE":
        # A suspended/barred counterparty blocks new disclosure drafts (§3.2).
        raise err_counterparty_not_active()
    purpose = require_str(data, "purpose")
    marking = require_enum(data, "marking_protocol", MARKING_PROTOCOLS)
    planned_raw = require_field(data, "planned_disclosure_date")
    planned_dt = parse_dt(planned_raw)
    if planned_dt is None:
        raise err_invalid_request("planned_disclosure_date must be an ISO 8601 timestamp")
    rec = new_record(
        "disclosures",
        {
            "requester_employee_id": user_id,
            "asset_id": asset_id,
            "nda_id": nda_id,
            "purpose": purpose,
            "marking_protocol": marking,
            "planned_disclosure_date": planned_raw if isinstance(planned_raw, str) else fmt_ts(planned_dt),
            "_planned_dt": planned_dt,
            "pinned_asset_version": None,
            "pinned_nda_version": None,
            "risk_score_provisional": None,
            "risk_score_final": None,
            "senior_endorsed": False,
            "marking_evidence_uri": None,
            "marking_sha256": None,
            "status": "DRAFT",
        },
    )
    return ok_object(serialize(rec), code=201)


@bp.get("/api/disclosures")
def list_disclosures():
    _uid, role = actor()
    require_roles(role, "IPCounsel", "SeniorCounsel", "Employee")
    filters = [
        (f, request.args[f])
        for f in ("asset_id", "nda_id", "requester_employee_id", "status")
        if f in request.args
    ]
    return _paginate_list("disclosures", filters)


@bp.get("/api/disclosures/<rid>")
def get_disclosure(rid):
    _uid, role = actor()
    require_roles(role, "IPCounsel", "SeniorCounsel", "Employee")
    d = by_id("disclosures", rid)
    if d is None:
        raise err_not_found("disclosure not found")
    return ok_object(serialize(d))


@bp.post("/api/disclosures/<rid>/endorse")
def endorse_disclosure(rid):
    _uid, role = actor()
    require_roles(role, "SeniorCounsel")
    d = by_id("disclosures", rid)
    if d is None:
        raise err_not_found("disclosure not found")
    if d["status"] != "UNDER_REVIEW":
        raise err_invalid_state("Endorsement is possible only from UNDER_REVIEW")
    d["senior_endorsed"] = True
    touch(d)
    return ok_object(serialize(d))


@bp.post("/api/disclosures/<rid>/state")
def disclosure_state(rid):
    user_id, role = actor()
    require_roles(role, "Employee", "IPCounsel")
    d = by_id("disclosures", rid)
    if d is None:
        raise err_not_found("disclosure not found")
    data = body()
    to_status = require_str(data, "to_status")
    if to_status not in DISCLOSURE_STATUSES:
        raise err_invalid_request(f"to_status must be one of {list(DISCLOSURE_STATUSES)}")
    cur = d["status"]
    asset = by_id("assets", d["asset_id"])
    nda = by_id("ndas", d["nda_id"])
    cp = by_id("counterparties", nda["counterparty_id"]) if nda is not None else None

    if to_status == "SUBMITTED":
        if role != "Employee":
            raise err_unauthorized_role("SUBMITTED requires the Employee role")
        if user_id != d["requester_employee_id"]:
            raise err_ownership("Only the requester may submit the disclosure")
        if cur != "DRAFT":
            raise err_invalid_state(f"Cannot move disclosure from {cur} to SUBMITTED")
        requester = by_id("employees", d["requester_employee_id"])
        if requester is None or requester["status"] not in ("PREBOARDING", "ACTIVE", "NOTICE"):
            raise err_invalid_state("Requester employee must be PREBOARDING, ACTIVE, or NOTICE")
        if asset is None or asset["status"] != "REGISTERED":
            raise err_invalid_state("Asset must be REGISTERED")
        # Pin the world and score provisionally.
        d["pinned_asset_version"] = asset["version"]
        d["pinned_nda_version"] = nda["version"] if nda is not None else None
        d["risk_score_provisional"] = risk_score_provisional(
            asset["classification"], d["marking_protocol"]
        )
        d["status"] = "SUBMITTED"
        touch(d)
    elif to_status == "UNDER_REVIEW":
        if role != "IPCounsel":
            raise err_unauthorized_role("UNDER_REVIEW requires IPCounsel")
        if cur != "SUBMITTED":
            raise err_invalid_state(f"Cannot move disclosure from {cur} to UNDER_REVIEW")
        # Classification ceiling (priority 7) before referenced-state (9).
        if nda is not None and asset is not None:
            if CLASS_ORDER[nda["classification_ceiling"]] < CLASS_ORDER[asset["classification"]]:
                raise err_ceiling()
        if nda is None or nda["status"] != "ACTIVE":
            raise err_nda_not_active()
        if cp is None or cp["status"] != "ACTIVE":
            raise err_counterparty_not_active()
        d["status"] = "UNDER_REVIEW"
        touch(d)
    elif to_status == "APPROVED":
        if role != "IPCounsel":
            raise err_unauthorized_role("APPROVED requires IPCounsel")
        # Segregation of duties (priority 3).
        if user_id == d["requester_employee_id"]:
            raise err_sod("The disclosure requester may not approve it")
        if cur != "UNDER_REVIEW":
            raise err_invalid_state(f"Cannot move disclosure from {cur} to APPROVED")
        # Safety gates (priority 7): posture, then risk routing.
        from services import recompute_asset_scores

        if asset is not None:
            recompute_asset_scores(asset)
        if asset is None or asset["protection_posture"] not in ("ADEQUATE", "STRONG"):
            raise err_posture()
        final = risk_score_final(
            asset["classification"],
            cp["risk_tier"] if cp is not None else "LOW",
            d["marking_protocol"],
        )
        if Decimal(str(final)) >= REJECT_MIN:
            raise err_risk_too_high()
        if Decimal(str(final)) >= ENDORSEMENT_MIN and not d["senior_endorsed"]:
            raise err_endorsement()
        # Referenced-entity gates (priority 9).
        if nda is None or nda["status"] != "ACTIVE":
            raise err_nda_not_active()
        if cp is None or cp["status"] != "ACTIVE":
            raise err_counterparty_not_active()
        if (
            asset["version"] != d["pinned_asset_version"]
            or nda["version"] != d["pinned_nda_version"]
        ):
            raise err_stale_reference()
        d["risk_score_final"] = final
        d["status"] = "APPROVED"
        touch(d)
    elif to_status == "REJECTED":
        if role != "IPCounsel":
            raise err_unauthorized_role("REJECTED requires IPCounsel")
        if cur != "UNDER_REVIEW":
            raise err_invalid_state(f"Cannot move disclosure from {cur} to REJECTED")
        d["status"] = "REJECTED"
        touch(d)
    elif to_status == "RETURNED":
        if role != "IPCounsel":
            raise err_unauthorized_role("RETURNED requires IPCounsel")
        if cur != "UNDER_REVIEW":
            raise err_invalid_state(f"Cannot move disclosure from {cur} to RETURNED")
        d["status"] = "RETURNED"
        touch(d)
    elif to_status == "DRAFT":
        if role != "Employee":
            raise err_unauthorized_role("DRAFT requires the Employee role")
        if user_id != d["requester_employee_id"]:
            raise err_ownership("Only the requester may reopen the disclosure")
        if cur != "RETURNED":
            raise err_invalid_state(f"Cannot move disclosure from {cur} to DRAFT")
        d["pinned_asset_version"] = None
        d["pinned_nda_version"] = None
        d["senior_endorsed"] = False
        d["status"] = "DRAFT"
        touch(d)
    elif to_status == "WITHDRAWN":
        if role != "Employee":
            raise err_unauthorized_role("WITHDRAWN requires the Employee role")
        if user_id != d["requester_employee_id"]:
            raise err_ownership("Only the requester may withdraw the disclosure")
        if cur not in ("DRAFT", "SUBMITTED", "RETURNED"):
            raise err_invalid_state(f"Cannot move disclosure from {cur} to WITHDRAWN")
        d["status"] = "WITHDRAWN"
        touch(d)
    elif to_status == "EXECUTED":
        if role != "IPCounsel":
            raise err_unauthorized_role("EXECUTED requires IPCounsel")
        if cur != "APPROVED":
            raise err_invalid_state(f"Cannot move disclosure from {cur} to EXECUTED")
        # Stale approval: no later than planned_disclosure_date + 30 days.
        if now() > add_days(d["_planned_dt"], EXECUTE_STALE_DAYS):
            raise err_invalid_state("Approval is stale: past planned_disclosure_date + 30 days")
        marking_uri = data.get("marking_evidence_uri")
        marking_hash = data.get("marking_sha256")
        if (
            not marking_uri
            or not isinstance(marking_uri, str)
            or not isinstance(marking_hash, str)
            or not SHA256_RE.match(marking_hash)
        ):
            raise err_marking_evidence()
        d["marking_evidence_uri"] = marking_uri
        d["marking_sha256"] = marking_hash
        d["status"] = "EXECUTED"
        touch(d)
        # Seal the marked copy as evidence; then recompute exposure (§3.5).
        ev = new_record(
            "evidence_items",
            {
                "review_id": None,
                "disclosure_id": d["id"],
                "source": "MARKED_COPY",
                "sha256": marking_hash,
                "byte_size": 0,
                "sealed_at": None,
                "status": "SEALED",
            },
        )
        stamp(ev, "sealed_at")
        if cp is not None:
            recompute_counterparty_exposure(cp)
    return ok_object(serialize(d))
