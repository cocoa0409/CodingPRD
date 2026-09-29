"""Onboarding a charity, its footprint, its statements and its officers (PRD 3.1, 3.2)."""
from flask import Blueprint, request

import clock
import response
import validate
from auth import ALL_ROLES, endpoint
from dates import parse_iso
from db import db, public, sorted_rows, stamp_new, touch_once
from errors import ApiError
from services import calc
from services.cascades import apply_restatement

bp = Blueprint("organizations", __name__)

LIFECYCLE_STATUSES = ("ACTIVE", "DISSOLVED")
OFFICER_TITLES = ("PRESIDENT", "TREASURER", "SECRETARY", "EXECUTIVE_DIRECTOR", "BOARD_CHAIR")
ASSURANCE_LEVELS = ("NONE", "REVIEW", "AUDIT")
STATEMENT_STATUSES = ("CURRENT", "SUPERSEDED")
AMENDABLE = ("legal_name", "fiscal_year_end_month", "has_online_donation_page",
             "lifecycle_status")
IMMUTABLE = ("ein", "domicile_state_code")

DEADLINE_RECOMPUTE_STATUSES = ("DRAFT", "SUBMITTED", "DEFICIENT", "REGISTERED")


def _disclosure_status(criminal_conviction_disclosed, conviction_explanation):
    """INCOMPLETE only when a disclosed conviction carries no narrative (PRD 3.1)."""
    if criminal_conviction_disclosed and (conviction_explanation is None
                                          or conviction_explanation == ""):
        return "INCOMPLETE"
    return "COMPLETE"


@bp.post("/organizations")
@endpoint(["ComplianceOfficer", "SystemAdmin"])
def create_organization():
    body = validate.json_body()
    legal_name = validate.req_string(body, "legal_name", min_len=1, max_len=200)
    ein = validate.req_string(body, "ein")
    if len(ein) != 9 or not ein.isdigit():
        raise ApiError("ERR_INVALID_REQUEST", "ein must be exactly nine digits.")
    domicile_state_code = validate.req_state_code(body, "domicile_state_code")
    fiscal_year_end_month = validate.req_int(body, "fiscal_year_end_month",
                                             minimum=1, maximum=12)
    has_online_donation_page = validate.opt_bool(body, "has_online_donation_page", False)
    lifecycle_status = validate.opt_enum(body, "lifecycle_status", LIFECYCLE_STATUSES,
                                        default="ACTIVE")

    validate.find_state_profile(domicile_state_code)

    # Ladder rung 28 -- ein unused by another organization.
    for other in db.organizations.values():
        if other["ein"] == ein:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER",
                           "An organization with this ein already exists.")

    organization = {
        "legal_name": legal_name,
        "ein": ein,
        "domicile_state_code": domicile_state_code,
        "fiscal_year_end_month": fiscal_year_end_month,
        "has_online_donation_page": has_online_donation_page,
        "lifecycle_status": lifecycle_status,
        # The derived side of the record; clients may not set any of it.
        "solicitation_posture": "CLEAR",
        "filing_posture": "CURRENT",
        "registered_state_count": 0,
        "delinquent_registration_count": 0,
        "ceased_state_codes": [],
        "penalty_outstanding_cents": 0,
    }
    stamp_new(organization)
    db.organizations[organization["id"]] = organization
    return response.created(public(organization))


@bp.get("/organizations")
@endpoint(["ComplianceOfficer", "CertifyingOfficer", "StateRegulator", "SystemAdmin"])
def list_organizations():
    rows = list(db.organizations.values())
    for field in ("solicitation_posture", "filing_posture", "domicile_state_code"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    page, limit, offset, total = response.paginate(sorted_rows(rows))
    return response.listing([public(r) for r in page], limit, offset, total)


@bp.get("/organizations/<organization_id>")
@endpoint(ALL_ROLES)
def read_organization(organization_id):
    return response.ok(public(validate.find_organization(organization_id)))


@bp.patch("/organizations/<organization_id>")
@endpoint(["ComplianceOfficer"])
def update_organization(organization_id):
    """Only four profile fields are amendable; ein and domicile are identity."""
    organization = validate.find_organization(organization_id)
    body = validate.json_body()
    for field in IMMUTABLE:
        if field in body:
            raise ApiError("ERR_INVALID_REQUEST", "%s may not be amended." % field)

    updates = {}
    if "legal_name" in body and body["legal_name"] is not None:
        updates["legal_name"] = validate.req_string(body, "legal_name", min_len=1, max_len=200)
    if "fiscal_year_end_month" in body and body["fiscal_year_end_month"] is not None:
        updates["fiscal_year_end_month"] = validate.req_int(
            body, "fiscal_year_end_month", minimum=1, maximum=12)
    if "has_online_donation_page" in body and body["has_online_donation_page"] is not None:
        updates["has_online_donation_page"] = validate.req_bool(body, "has_online_donation_page")
    if "lifecycle_status" in body and body["lifecycle_status"] is not None:
        updates["lifecycle_status"] = validate.req_enum(body, "lifecycle_status",
                                                        LIFECYCLE_STATUSES)

    fye_moved = ("fiscal_year_end_month" in updates
                 and updates["fiscal_year_end_month"] != organization["fiscal_year_end_month"])
    organization.update(updates)
    touch_once(organization, "organization")

    if fye_moved:
        # Every renewal deadline in the system is derived from the fiscal year end.
        affected = [r for r in db.state_registrations.values()
                    if r["organization_id"] == organization_id
                    and r["status"] in DEADLINE_RECOMPUTE_STATUSES]
        for registration in sorted_rows(affected):
            calc.recompute_deadlines(registration)
            touch_once(registration, "state_registration")

    return response.ok(public(organization))


@bp.get("/organizations/<organization_id>/compliance-calendar")
@endpoint(["ComplianceOfficer", "CertifyingOfficer", "StateRegulator", "SystemAdmin"])
def compliance_calendar(organization_id):
    """Computed read: ordered by effective_due_date ASC, state_code ASC.

    This is the one list in the system that documents a different ordering, and
    it accepts no limit or offset at all (PRD 2.3).
    """
    validate.find_organization(organization_id)
    rows = [r for r in db.state_registrations.values()
            if r["organization_id"] == organization_id]
    fiscal_year = response.query_int("fiscal_year")
    if fiscal_year is not None:
        rows = [r for r in rows if r["fiscal_year"] == fiscal_year]

    rows.sort(key=lambda r: (r["effective_due_date"] or "", r["state_code"]))
    entries = [{
        "state_code": r["state_code"],
        "fiscal_year": r["fiscal_year"],
        "renewal_due_date": r["renewal_due_date"],
        "effective_due_date": r["effective_due_date"],
        "status": r["status"],
        "required_financial_attestation": r["required_financial_attestation"],
    } for r in rows]

    now = clock.now()
    ahead = sorted({r["effective_due_date"] for r in rows
                    if r["effective_due_date"]
                    and parse_iso(r["effective_due_date"]) > now})
    delinquent_state_codes = sorted({r["state_code"] for r in rows
                                     if r["status"] == "DELINQUENT"})

    return response.ok({
        "organization_id": organization_id,
        "entry_count": len(entries),
        "entries": entries,
        "next_effective_due_date": ahead[0] if ahead else None,
        "delinquent_state_codes": delinquent_state_codes,
    })


@bp.get("/organizations/<organization_id>/solicitation-activities")
@endpoint(["ComplianceOfficer", "StateRegulator", "SystemAdmin"])
def list_organization_activities(organization_id):
    validate.find_organization(organization_id)
    rows = [r for r in db.solicitation_activities.values()
            if r["organization_id"] == organization_id]
    state_code = request.args.get("state_code")
    if state_code is not None:
        rows = [r for r in rows if r["state_code"] == state_code]
    fiscal_year = response.query_int("fiscal_year")
    if fiscal_year is not None:
        rows = [r for r in rows if r["fiscal_year"] == fiscal_year]
    page, limit, offset, total = response.paginate(sorted_rows(rows))
    return response.listing([public(r) for r in page], limit, offset, total)


@bp.get("/organizations/<organization_id>/financial-statements")
@endpoint(["ComplianceOfficer", "CertifyingOfficer", "StateRegulator", "SystemAdmin"])
def list_organization_statements(organization_id):
    validate.find_organization(organization_id)
    rows = [r for r in db.financial_statements.values()
            if r["organization_id"] == organization_id]
    fiscal_year = response.query_int("fiscal_year")
    if fiscal_year is not None:
        rows = [r for r in rows if r["fiscal_year"] == fiscal_year]
    statement_status = request.args.get("statement_status")
    if statement_status is not None:
        rows = [r for r in rows if r["statement_status"] == statement_status]
    page, limit, offset, total = response.paginate(sorted_rows(rows))
    return response.listing([public(r) for r in page], limit, offset, total)


@bp.get("/organizations/<organization_id>/officer-disclosures")
@endpoint(["ComplianceOfficer", "CertifyingOfficer", "StateRegulator", "SystemAdmin"])
def list_organization_officers(organization_id):
    validate.find_organization(organization_id)
    rows = [r for r in db.officer_disclosures.values()
            if r["organization_id"] == organization_id]
    raw = request.args.get("is_certifying_officer")
    if raw is not None:
        wanted = str(raw).strip().lower() in ("true", "1", "yes")
        rows = [r for r in rows if r["is_certifying_officer"] == wanted]
    page, limit, offset, total = response.paginate(sorted_rows(rows))
    return response.listing([public(r) for r in page], limit, offset, total)


@bp.get("/organizations/<organization_id>/disclosure-statements")
@endpoint(["ComplianceOfficer", "StateRegulator", "SystemAdmin"])
def list_organization_disclosures(organization_id):
    validate.find_organization(organization_id)
    rows = [r for r in db.disclosure_statements.values()
            if r["organization_id"] == organization_id]
    state_code = request.args.get("state_code")
    if state_code is not None:
        rows = [r for r in rows if r["state_code"] == state_code]
    compliance_status = request.args.get("compliance_status")
    if compliance_status is not None:
        rows = [r for r in rows if r["compliance_status"] == compliance_status]
    page, limit, offset, total = response.paginate(sorted_rows(rows))
    return response.listing([public(r) for r in page], limit, offset, total)


@bp.post("/solicitation-activities")
@endpoint(["ComplianceOfficer"])
def create_solicitation_activity():
    """An immutable event record carrying id and created_at only (PRD 2.5)."""
    body = validate.json_body()
    organization_id = validate.req_string(body, "organization_id")
    state_code = validate.req_state_code(body, "state_code")
    fiscal_year = validate.req_int(body, "fiscal_year", minimum=2000, maximum=2100)
    donor_count = validate.req_int(body, "donor_count", minimum=0)
    contributions_cents = validate.req_int(body, "contributions_cents", minimum=0)
    channels = validate.req_array(body, "channels", allowed=validate.SOLICITATION_CHANNELS)

    validate.find_organization(organization_id)
    profile = validate.find_state_profile(state_code)

    triggers, reasons = calc.registration_trigger_evaluation(
        donor_count, contributions_cents, channels, profile)

    activity = {
        "organization_id": organization_id,
        "state_code": state_code,
        "fiscal_year": fiscal_year,
        "donor_count": donor_count,
        "contributions_cents": contributions_cents,
        "channels": channels,
        "triggers_registration": triggers,
        "trigger_reasons": reasons,
    }
    stamp_new(activity, common_fields=False)
    db.solicitation_activities[activity["id"]] = activity
    return response.created(public(activity))


@bp.post("/financial-statements")
@endpoint(["ComplianceOfficer"])
def create_financial_statement():
    """File or restate a statement; guarded by the organization-version OCC rule."""
    body = validate.json_body()
    organization_id = validate.req_string(body, "organization_id")
    fiscal_year = validate.req_int(body, "fiscal_year", minimum=2000, maximum=2100)
    total_revenue_cents = validate.req_int(body, "total_revenue_cents", minimum=0)
    contributions_cents = validate.req_int(body, "contributions_cents", minimum=0)
    program_expense_cents = validate.req_int(body, "program_expense_cents", minimum=0)
    fundraising_expense_cents = validate.req_int(body, "fundraising_expense_cents", minimum=0)
    management_expense_cents = validate.req_int(body, "management_expense_cents", minimum=0)
    government_grant_cents = validate.opt_int(body, "government_grant_cents", 0, minimum=0)
    assurance_level = validate.opt_enum(body, "assurance_level", ASSURANCE_LEVELS,
                                        default="NONE")
    expected_organization_version = validate.req_int(body, "expected_organization_version")
    if total_revenue_cents < contributions_cents:
        raise ApiError("ERR_INVALID_REQUEST",
                       "total_revenue_cents must be at least contributions_cents.")

    organization = validate.find_organization(organization_id)

    # Ladder rung 8 -- the restatement OCC guard.
    if expected_organization_version != organization["version"]:
        raise ApiError("ERR_STALE_ORGANIZATION_VERSION")

    functional_total = calc.functional_expense_total(
        program_expense_cents, fundraising_expense_cents, management_expense_cents)

    statement = {
        "organization_id": organization_id,
        "fiscal_year": fiscal_year,
        "total_revenue_cents": total_revenue_cents,
        "contributions_cents": contributions_cents,
        "government_grant_cents": government_grant_cents,
        "program_expense_cents": program_expense_cents,
        "fundraising_expense_cents": fundraising_expense_cents,
        "management_expense_cents": management_expense_cents,
        "assurance_level": assurance_level,
        "statement_status": "CURRENT",
        "functional_expense_total_cents": functional_total,
        "program_ratio": calc.program_ratio(program_expense_cents, functional_total),
    }
    stamp_new(statement)
    db.financial_statements[statement["id"]] = statement

    # R1 / R2 / R3 -- the restatement cascade, when a current statement existed.
    if apply_restatement(statement):
        touch_once(organization, "organization")

    return response.created(public(statement))


@bp.post("/officer-disclosures")
@endpoint(["ComplianceOfficer"])
def create_officer_disclosure():
    body = validate.json_body()
    organization_id = validate.req_string(body, "organization_id")
    officer_name = validate.req_string(body, "officer_name", max_len=200)
    title = validate.req_enum(body, "title", OFFICER_TITLES)
    is_certifying_officer = validate.opt_bool(body, "is_certifying_officer", False)
    annual_compensation_cents = validate.opt_int(body, "annual_compensation_cents", 0, minimum=0)
    criminal_conviction_disclosed = validate.opt_bool(body, "criminal_conviction_disclosed", False)
    conviction_explanation = validate.opt_string(body, "conviction_explanation", default=None)

    validate.find_organization(organization_id)

    disclosure = {
        "organization_id": organization_id,
        "officer_name": officer_name,
        "title": title,
        "is_certifying_officer": is_certifying_officer,
        "annual_compensation_cents": annual_compensation_cents,
        "criminal_conviction_disclosed": criminal_conviction_disclosed,
        "conviction_explanation": conviction_explanation,
        "disclosure_status": _disclosure_status(criminal_conviction_disclosed,
                                                conviction_explanation),
    }
    stamp_new(disclosure)
    db.officer_disclosures[disclosure["id"]] = disclosure
    return response.created(public(disclosure))
