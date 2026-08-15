"""Grantee due diligence, grant recommendation lifecycle, disbursement ledger."""
import re
from decimal import Decimal

from flask import Blueprint, g, request

from common import (
    STORE, body, err, fund_view, get_path, get_ref, list_response,
    new_resource, now, q2, reactivate_if_inactive, req_decimal, req_enum,
    req_present, require_roles, serialize, success, touch,
)

bp = Blueprint("grants", __name__)

IRS_SUBSECTIONS = ("C3_501", "C3_PRIVATE_FOUNDATION", "GOVERNMENT", "OTHER")
TAX_ID_RE = re.compile(r"^\d{9}$")
GRANT_MINIMUM = Decimal("250.00")


def grantee_view(gr):
    return serialize(gr)


def grant_view(gr):
    return serialize(gr)


def disbursement_view(d):
    return serialize(d)


# ---------------------------------------------------------------------------
# Grantees
# ---------------------------------------------------------------------------
@bp.post("/grantees")
@require_roles("ComplianceOfficer")
def create_grantee():
    data = body()
    legal_name = data.get("legal_name")
    tax_id = data.get("tax_id")
    # Uniqueness (priority 11) precedes field-domain checks (priority 12).
    if legal_name is not None:
        for x in STORE["grantees"].values():
            if x["legal_name"] == legal_name:
                err("ERR_UNIQUENESS_VIOLATION", 409, "legal_name must be unique")
    if tax_id is not None:
        for x in STORE["grantees"].values():
            if x["tax_id"] == tax_id:
                err("ERR_UNIQUENESS_VIOLATION", 409, "tax_id must be unique")
    legal_name = req_present(data, "legal_name")
    tax_id = req_present(data, "tax_id")
    if not TAX_ID_RE.match(tax_id):
        err("ERR_FIELD_CONSTRAINT", 422, "tax_id must be 9 digits (NNNNNNNNN)")
    subsection = req_enum(data, "irs_subsection", IRS_SUBSECTIONS)
    gr = new_resource()
    gr.update({
        "legal_name": legal_name,
        "tax_id": tax_id,
        "irs_subsection": subsection,
        "due_diligence_status": "UNVETTED",
        "cleared_at": None,
        "expenditure_responsibility_required": subsection not in ("C3_501", "GOVERNMENT"),
    })
    STORE["grantees"][gr["id"]] = gr
    return success(grantee_view(gr), code=201)


@bp.get("/grantees")
@require_roles("FoundationAdmin", "ComplianceOfficer", "Advisor")
def list_grantees():
    items = list(STORE["grantees"].values())
    st = request.args.get("due_diligence_status")
    if st is not None:
        items = [g for g in items if g["due_diligence_status"] == st]
    return list_response(items, grantee_view)


@bp.get("/grantees/<granteeId>")
@require_roles("FoundationAdmin", "ComplianceOfficer", "Advisor")
def get_grantee(granteeId):
    return success(grantee_view(get_path("grantees", granteeId)))


@bp.post("/grantees/<granteeId>/begin-review")
@require_roles("ComplianceOfficer")
def begin_review(granteeId):
    gr = get_path("grantees", granteeId)
    if gr["due_diligence_status"] not in ("UNVETTED", "EXPIRED", "REJECTED_DD"):
        err("ERR_INVALID_STATE", 409,
            "Only an UNVETTED, EXPIRED, or REJECTED_DD grantee can enter review")
    gr["due_diligence_status"] = "IN_REVIEW"
    touch(gr)
    return success(grantee_view(gr))


@bp.post("/grantees/<granteeId>/clear")
@require_roles("ComplianceOfficer")
def clear_grantee(granteeId):
    gr = get_path("grantees", granteeId)
    if gr["due_diligence_status"] != "IN_REVIEW":
        err("ERR_INVALID_STATE", 409, "Only an IN_REVIEW grantee can be cleared")
    gr["due_diligence_status"] = "CLEARED"
    gr["cleared_at"] = now()
    touch(gr)
    return success(grantee_view(gr))


@bp.post("/grantees/<granteeId>/reject")
@require_roles("ComplianceOfficer")
def reject_grantee(granteeId):
    gr = get_path("grantees", granteeId)
    if gr["due_diligence_status"] != "IN_REVIEW":
        err("ERR_INVALID_STATE", 409, "Only an IN_REVIEW grantee can be rejected")
    gr["due_diligence_status"] = "REJECTED_DD"
    touch(gr)
    return success(grantee_view(gr))


# ---------------------------------------------------------------------------
# Grant recommendations
# ---------------------------------------------------------------------------
@bp.post("/grants")
@require_roles("Advisor", "FoundationAdmin")
def create_grant():
    data = body()
    fund_id = data.get("fund_id")
    grantee_id = data.get("grantee_id")
    advisor_id = data.get("recommended_by_advisor_id")
    # Body reference existence (priority 4).
    if fund_id is not None:
        get_ref("funds", fund_id, "fund")
    if grantee_id is not None:
        get_ref("grantees", grantee_id, "grantee")
    if advisor_id is not None:
        get_ref("advisors", advisor_id, "advisor")
    fund_id = req_present(data, "fund_id")
    grantee_id = req_present(data, "grantee_id")
    f = get_ref("funds", fund_id, "fund")
    get_ref("grantees", grantee_id, "grantee")
    # OCC (priority 6): grant creation always carries expected_fund_version.
    if data.get("expected_fund_version") != f["version"]:
        err("ERR_STALE_FUND_VERSION", 412,
            "expected_fund_version does not match the fund's current version")
    # Field domain (priority 12).
    amount = req_decimal(data, "amount")
    amount = q2(amount)
    if amount < GRANT_MINIMUM:
        err("ERR_FIELD_CONSTRAINT", 422, "amount must be at least 250.00")
    purpose = req_present(data, "purpose")
    if f["fund_type"] == "DONOR_ADVISED":
        if advisor_id is None:
            err("ERR_FIELD_CONSTRAINT", 422,
                "recommended_by_advisor_id is required for DONOR_ADVISED funds")
    else:
        if advisor_id is not None:
            err("ERR_FIELD_CONSTRAINT", 422,
                "recommended_by_advisor_id is forbidden for non-DONOR_ADVISED funds")
    gr = new_resource()
    gr.update({
        "fund_id": fund_id,
        "grantee_id": grantee_id,
        "amount": amount,
        "purpose": purpose,
        "recommended_by_advisor_id": advisor_id,
        "status": "DRAFT",
        "revision_count": 0,
        "submitted_at": None,
        "decided_at": None,
        "_claimed_by": None,
        "_approved_by": None,
    })
    STORE["grants"][gr["id"]] = gr
    # Creating a grant touches the fund's pipeline and advances its version.
    touch(f)
    return success(grant_view(gr), code=201)


@bp.get("/grants")
@require_roles("FoundationAdmin", "ComplianceOfficer", "FinanceOfficer", "Advisor")
def list_grants():
    items = list(STORE["grants"].values())
    fid = request.args.get("fund_id")
    gid = request.args.get("grantee_id")
    aid = request.args.get("recommended_by_advisor_id")
    st = request.args.get("status")
    if fid is not None:
        items = [x for x in items if x["fund_id"] == fid]
    if gid is not None:
        items = [x for x in items if x["grantee_id"] == gid]
    if aid is not None:
        items = [x for x in items if x["recommended_by_advisor_id"] == aid]
    if st is not None:
        items = [x for x in items if x["status"] == st]
    return list_response(items, grant_view)


@bp.get("/grants/<grantId>")
@require_roles("FoundationAdmin", "ComplianceOfficer", "FinanceOfficer", "Advisor")
def get_grant(grantId):
    return success(grant_view(get_path("grants", grantId)))


@bp.post("/grants/<grantId>/submit")
@require_roles("Advisor", "FoundationAdmin")
def submit_grant(grantId):
    gr = get_path("grants", grantId)
    if gr["status"] not in ("DRAFT", "RETURNED"):
        err("ERR_INVALID_STATE", 409,
            "Only a DRAFT or RETURNED grant can be submitted")
    f = STORE["funds"][gr["fund_id"]]
    # Checks in PRD order: fund active, advisor authorization, amount floor, revision limit.
    if f["status"] != "ACTIVE":
        err("ERR_FUND_NOT_ACTIVE_FOR_GRANTS", 409,
            "Fund must be ACTIVE for grant submission")
    if f["fund_type"] == "DONOR_ADVISED":
        adv = STORE["advisors"].get(gr["recommended_by_advisor_id"])
        if (adv is None or adv["fund_id"] != f["id"] or adv["status"] != "ACTIVE"
                or g.role != "Advisor" or g.uid != adv["id"]):
            err("ERR_ADVISOR_NOT_AUTHORIZED", 403,
                "DONOR_ADVISED grants must be submitted by the ACTIVE recommending advisor of the fund")
    else:
        if g.role != "FoundationAdmin" or gr["recommended_by_advisor_id"] is not None:
            err("ERR_ADVISOR_NOT_AUTHORIZED", 403,
                "Grants on DESIGNATED/SCHOLARSHIP funds are submitted by a FoundationAdmin")
    if gr["amount"] < GRANT_MINIMUM:
        err("ERR_GRANT_BELOW_MINIMUM", 422, "Grant amount must be at least 250.00")
    if gr["revision_count"] >= 3:
        err("ERR_REVISION_LIMIT_REACHED", 422, "Grant has reached the revision limit")
    gr["status"] = "SUBMITTED"
    gr["submitted_at"] = now()
    touch(gr)
    return success(grant_view(gr))


@bp.post("/grants/<grantId>/claim-review")
@require_roles("ComplianceOfficer")
def claim_review(grantId):
    gr = get_path("grants", grantId)
    if gr["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", 409, "Only a SUBMITTED grant can be claimed for review")
    gr["status"] = "COMPLIANCE_REVIEW"
    gr["_claimed_by"] = g.uid
    touch(gr)
    return success(grant_view(gr))


@bp.post("/grants/<grantId>/approve")
@require_roles("ComplianceOfficer")
def approve_grant(grantId):
    gr = get_path("grants", grantId)
    if gr["status"] != "COMPLIANCE_REVIEW":
        err("ERR_INVALID_STATE", 409, "Only a grant in COMPLIANCE_REVIEW can be approved")
    data = body()
    # 1. Segregation of duties: approver != claimer.
    if gr["_claimed_by"] is not None and g.uid == gr["_claimed_by"]:
        err("ERR_SOD_SELF_APPROVAL", 403,
            "The approving officer must differ from the officer who claimed the review")
    # 2. Grantee must be CLEARED at the decision instant.
    grantee = STORE["grantees"].get(gr["grantee_id"])
    if grantee is None or grantee["due_diligence_status"] != "CLEARED":
        err("ERR_GRANTEE_NOT_CLEARED", 422, "Grantee is not CLEARED")
    # 3. Expenditure-responsibility acknowledgement where required.
    if grantee["expenditure_responsibility_required"]:
        if data.get("include_er_acknowledgement") is not True:
            err("ERR_ER_ACK_REQUIRED", 422,
                "Expenditure-responsibility acknowledgement is required for this grantee")
    # 4. Amount within spendable balance at the decision instant.
    f = STORE["funds"][gr["fund_id"]]
    spendable = Decimal(str(fund_view(f)["spendable_balance"]))
    if gr["amount"] > spendable:
        err("ERR_EXCEEDS_SPENDABLE", 422, "Grant amount exceeds the fund's spendable balance")
    gr["status"] = "APPROVED"
    gr["decided_at"] = now()
    gr["_approved_by"] = g.uid
    touch(gr)
    return success(grant_view(gr))


@bp.post("/grants/<grantId>/return")
@require_roles("ComplianceOfficer")
def return_grant(grantId):
    gr = get_path("grants", grantId)
    if gr["status"] != "COMPLIANCE_REVIEW":
        err("ERR_INVALID_STATE", 409, "Only a grant in COMPLIANCE_REVIEW can be returned")
    gr["status"] = "RETURNED"
    gr["revision_count"] += 1
    if gr["revision_count"] >= 3:
        # Third return auto-denies.
        gr["status"] = "DENIED"
        gr["decided_at"] = now()
    touch(gr)
    return success(grant_view(gr))


@bp.post("/grants/<grantId>/deny")
@require_roles("ComplianceOfficer")
def deny_grant(grantId):
    gr = get_path("grants", grantId)
    if gr["status"] != "COMPLIANCE_REVIEW":
        err("ERR_INVALID_STATE", 409, "Only a grant in COMPLIANCE_REVIEW can be denied")
    gr["status"] = "DENIED"
    gr["decided_at"] = now()
    touch(gr)
    return success(grant_view(gr))


@bp.post("/grants/<grantId>/cancel")
@require_roles("ComplianceOfficer")
def cancel_grant(grantId):
    gr = get_path("grants", grantId)
    if gr["status"] != "APPROVED":
        err("ERR_INVALID_STATE", 409, "Only an APPROVED grant can be cancelled")
    gr["status"] = "CANCELLED"
    touch(gr)
    return success(grant_view(gr))


@bp.post("/grants/<grantId>/disburse")
@require_roles("FinanceOfficer")
def disburse_grant(grantId):
    gr = get_path("grants", grantId)
    if gr["status"] != "APPROVED":
        err("ERR_INVALID_STATE", 409, "Only an APPROVED grant can be disbursed")
    # Segregation of duties: disburser != approver.
    if gr["_approved_by"] is not None and g.uid == gr["_approved_by"]:
        err("ERR_SOD_SELF_DISBURSE", 403,
            "The disbursing officer must differ from the approving officer")
    f = STORE["funds"][gr["fund_id"]]
    if gr["amount"] > f["cash_balance"]:
        err("ERR_INSUFFICIENT_CASH", 422, "Grant amount exceeds the fund's cash balance")
    f["cash_balance"] = q2(f["cash_balance"] - gr["amount"])
    if f["endowed"]:
        f["allowance_used"] = q2(f["allowance_used"] + gr["amount"])
    f["last_activity_at"] = now()
    reactivate_if_inactive(f)
    touch(f)
    d = new_resource(common_fields=False)
    d.update({
        "source_kind": "GRANT",
        "grant_id": gr["id"],
        "award_id": None,
        "fund_id": f["id"],
        "amount": q2(gr["amount"]),
    })
    STORE["disbursements"][d["id"]] = d
    gr["status"] = "DISBURSED"
    touch(gr)
    return success(grant_view(gr))


# ---------------------------------------------------------------------------
# Disbursement ledger reads
# ---------------------------------------------------------------------------
@bp.get("/funds/<fundId>/disbursements")
@require_roles("FoundationAdmin", "FinanceOfficer")
def list_fund_disbursements(fundId):
    f = get_path("funds", fundId)
    items = [d for d in STORE["disbursements"].values() if d["fund_id"] == f["id"]]
    sk = request.args.get("source_kind")
    if sk is not None:
        items = [d for d in items if d["source_kind"] == sk]
    return list_response(items, disbursement_view)


@bp.get("/disbursements/<disbursementId>")
@require_roles("FoundationAdmin", "FinanceOfficer")
def get_disbursement(disbursementId):
    return success(disbursement_view(get_path("disbursements", disbursementId)))


@bp.get("/disbursements")
@require_roles("FoundationAdmin", "FinanceOfficer")
def list_disbursements():
    items = list(STORE["disbursements"].values())
    gid = request.args.get("grant_id")
    aid = request.args.get("award_id")
    fid = request.args.get("fund_id")
    if gid is not None:
        items = [d for d in items if d["grant_id"] == gid]
    if aid is not None:
        items = [d for d in items if d["award_id"] == aid]
    if fid is not None:
        items = [d for d in items if d["fund_id"] == fid]
    return list_response(items, disbursement_view)


@bp.get("/grants/<grantId>/disbursements")
@require_roles("FoundationAdmin", "FinanceOfficer", "ComplianceOfficer")
def list_grant_disbursements(grantId):
    gr = get_path("grants", grantId)
    items = [d for d in STORE["disbursements"].values() if d["grant_id"] == gr["id"]]
    return list_response(items, disbursement_view)
