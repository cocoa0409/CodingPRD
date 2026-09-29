"""Mortgage origination, affordability structuring, closing, and the silent second."""
from flask import Blueprint

import calc
import cascade
import derive
from common import (
    API, created, get_application, get_household, get_site, listing, match, okay,
)
from errors import fail
from payload import body, qenum, qid, vdatetime, venum, vint, vstring
from rbac import auth, own_household, scope_by_household
from store import bump, db, stamp
from util import date_start, days

bp = Blueprint("mortgage", __name__)

STATUSES = ("DRAFT", "UNDERWRITING", "APPROVED", "CLEARED_TO_CLOSE", "CLOSED",
            "DENIED", "SUPERSEDED")
STATUS_TERMINALS = ("CLOSED", "DENIED", "SUPERSEDED")
LIEN_STATUSES = ("NONE", "ACTIVE", "FORBEARANCE", "TRANSFER_PENDING", "SATISFIED",
                 "RECAPTURED")
LIEN_TERMINALS = ("SATISFIED", "RECAPTURED")
PARTNER_STATES = ("SELECTED", "PARTNERSHIP_ACTIVE")
READ_ROLES = ("ProgramAdmin", "MortgageOfficer", "FamilyServicesCoordinator", "Applicant")

LIEN_ACTIONS = ("FORBEARANCE_GRANT", "REINSTATE", "TRANSFER_REQUEST",
                "RECORD_TRANSFER", "SATISFY")
LIEN_ALIASES = {
    "FORBEARANCE": "FORBEARANCE_GRANT",
    "CURE": "REINSTATE",
    "TRANSFER_NOTICE": "TRANSFER_REQUEST",
    "RECAPTURE": "RECORD_TRANSFER",
    "PAYOFF": "SATISFY",
}

STRUCTURE_FIELDS = ("appraised_value_cents", "income_basis_annual_cents",
                    "escrow_monthly_cents", "affordable_pi_payment_cents",
                    "term_months", "first_mortgage_principal_cents",
                    "silent_second_amount_cents")


def _segregation(actor, household):
    for review in db.reviews.values():
        if review.get("household_id") != household["id"]:
            continue
        if review.get("status") != "SUBMITTED":
            continue
        if review.get("reviewer_user_id") == actor.user_id:
            fail("ERR_SEGREGATION_OF_DUTIES")


def _touch_program(program):
    if program is not None:
        derive.refresh_program(program)
        bump(program)


# --------------------------------------------------------------------------- #
# origination
# --------------------------------------------------------------------------- #
@bp.post(API + "/mortgage-applications")
def create_application():
    actor = auth("MortgageOfficer")
    data = body()
    raw_household = data.get("household_id")
    household = get_household(raw_household) if isinstance(raw_household, str) and raw_household else None
    raw_site = data.get("build_site_id")
    site = get_site(raw_site) if isinstance(raw_site, str) and raw_site else None

    household_id = vstring(data, "household_id", 1, None, required=True)
    site_id = vstring(data, "build_site_id", 1, None, required=True)
    expected = vint(data, "expected_household_version", minimum=1, required=True)
    term = vint(data, "term_months", choices=(240, 300, 360), required=True)
    escrow = vint(data, "escrow_monthly_cents", minimum=0, default=None, nullable=True)
    credit = vint(data, "closing_cost_credit_cents", minimum=0, maximum=500000, default=0)
    if household is None:
        household = get_household(household_id)
    if site is None:
        site = get_site(site_id)

    if int(household.get("version") or 0) != int(expected):
        fail("ERR_STALE_HOUSEHOLD_VERSION")

    cascade.guard_not_frozen(derive.program_of_household(household))
    _segregation(actor, household)

    if household.get("selection_status") not in PARTNER_STATES:
        fail("ERR_HOUSEHOLD_NOT_SELECTED")
    assigned = site.get("assigned_household_id")
    if assigned is not None and assigned != household["id"]:
        fail("ERR_SITE_ALREADY_ASSIGNED")

    superseded_id = None
    for existing in derive.applications_of_household(household):
        if existing.get("status") == "DRAFT":
            existing["status"] = "SUPERSEDED"
            bump(existing)
            superseded_id = existing["id"]

    row = {
        "household_id": household["id"],
        "build_site_id": site["id"],
        "superseded_application_id": superseded_id,
        "originating_officer_user_id": actor.user_id,
        "appraised_value_cents": site.get("appraised_value_cents"),
        "income_basis_annual_cents": household.get("verified_annual_income_cents"),
        "escrow_monthly_cents": escrow,
        "affordable_pi_payment_cents": None,
        "term_months": term,
        "first_mortgage_principal_cents": None,
        "silent_second_amount_cents": None,
        "closing_cost_credit_cents": credit,
        "resale_restriction_months": 240,
        "lien_recorded_on": None,
        "forgiven_amount_cents": 0,
        "lien_outstanding_cents": 0,
        "forbearance_counseling_sessions": 0,
        "right_of_first_refusal_expires_on": None,
        "denial_reason_code": None,
        "status": "DRAFT",
        "lien_status": "NONE",
    }
    stamp(row)
    db.applications[row["id"]] = row

    if assigned is None:
        site["assigned_household_id"] = household["id"]
        derive.refresh_site(site)
        bump(site)

    return created(derive.public_application(row))


@bp.get(API + "/mortgage-applications")
def list_applications():
    actor = auth(*READ_ROLES)
    household_id = qid("household_id")
    site_id = qid("build_site_id")
    superseded = qid("superseded_application_id")
    status = qenum("status", STATUSES)
    lien_status = qenum("lien_status", LIEN_STATUSES)
    rows = [r for r in db.applications.values()
            if match(r, "household_id", household_id)
            and match(r, "build_site_id", site_id)
            and match(r, "superseded_application_id", superseded)
            and match(r, "status", status)
            and match(r, "lien_status", lien_status)]
    return listing(scope_by_household(actor, rows), derive.public_application)


@bp.get(API + "/mortgage-applications/<aid>")
def read_application(aid):
    actor = auth(*READ_ROLES)
    application = get_application(aid)
    own_household(actor, db.households.get(application.get("household_id")))
    return okay(derive.public_application(application))


@bp.get(API + "/mortgage-applications/<aid>/structure-preview")
def preview_structure(aid):
    auth("MortgageOfficer", "ProgramAdmin")
    application = get_application(aid)
    figures = calc.structure(application.get("appraised_value_cents"),
                             application.get("income_basis_annual_cents"))
    return okay(figures)


@bp.post(API + "/mortgage-applications/<aid>/submit-underwriting")
def submit_underwriting(aid):
    actor = auth("MortgageOfficer")
    application = get_application(aid)
    body()

    cascade.state_gate(application, "status", ("DRAFT",), STATUS_TERMINALS)
    household = db.households.get(application.get("household_id"))
    site = db.sites.get(application.get("build_site_id"))
    cascade.guard_not_frozen(derive.program_of_application(application))
    _segregation(actor, household) if household is not None else None

    if household is None or household.get("selection_status") not in PARTNER_STATES:
        fail("ERR_HOUSEHOLD_NOT_SELECTED")
    if household.get("documentation_status") != "VERIFIED":
        fail("ERR_HOUSEHOLD_NOT_SELECTED")
    if household.get("verified_annual_income_cents") is None:
        fail("ERR_HOUSEHOLD_NOT_SELECTED")
    if site is None or site.get("readiness_status") not in (
            "READY_TO_BUILD", "UNDER_CONSTRUCTION", "COMPLETED"):
        fail("ERR_SITE_NOT_READY_TO_BUILD")

    application["appraised_value_cents"] = site.get("appraised_value_cents")
    application["income_basis_annual_cents"] = household.get("verified_annual_income_cents")
    figures = calc.structure(application["appraised_value_cents"],
                             application["income_basis_annual_cents"])
    if figures["affordable_pi_payment_cents"] <= 0:
        fail("ERR_NO_AFFORDABLE_STRUCTURE")

    application["escrow_monthly_cents"] = figures["escrow_monthly_cents"]
    application["affordable_pi_payment_cents"] = figures["affordable_pi_payment_cents"]
    application["term_months"] = figures["term_months"]
    application["first_mortgage_principal_cents"] = figures["first_mortgage_principal_cents"]
    application["silent_second_amount_cents"] = figures["silent_second_amount_cents"]
    application["status"] = "UNDERWRITING"
    bump(application)
    return okay(derive.public_application(application))


@bp.post(API + "/mortgage-applications/<aid>/return-to-draft")
def return_to_draft(aid):
    auth("MortgageOfficer")
    application = get_application(aid)
    data = body()
    vstring(data, "return_reason", 1, None, default=None, nullable=True)

    cascade.state_gate(application, "status", ("UNDERWRITING", "CLEARED_TO_CLOSE"),
                       STATUS_TERMINALS)
    cascade.guard_not_frozen(derive.program_of_application(application))

    if application["status"] == "UNDERWRITING":
        for field in STRUCTURE_FIELDS:
            application[field] = None
        application["status"] = "DRAFT"
    else:
        application["status"] = "APPROVED"
    bump(application)
    return okay(derive.public_application(application))


@bp.post(API + "/mortgage-applications/<aid>/approve")
def approve_application(aid):
    actor = auth("MortgageOfficer")
    application = get_application(aid)
    data = body()
    expected = vint(data, "expected_program_version", minimum=1, required=True)
    restriction = vint(data, "resale_restriction_months", choices=(120, 240, 360),
                       required=True)

    program = derive.program_of_application(application)
    if program is None or int(program.get("version") or 0) != int(expected):
        fail("ERR_STALE_PROGRAM_VERSION")

    cascade.state_gate(application, "status", ("UNDERWRITING",), STATUS_TERMINALS)
    cascade.guard_not_frozen(program)

    household = db.households.get(application.get("household_id"))
    if household is not None:
        _segregation(actor, household)

    silent = application.get("silent_second_amount_cents") or 0
    ledger = derive.program_ledger(program)
    if ledger["subsidy_available_cents"] < silent:
        fail("ERR_SUBSIDY_POOL_EXHAUSTED")

    application["resale_restriction_months"] = restriction
    application["status"] = "APPROVED"
    bump(application)
    _touch_program(program)

    if household is not None and household.get("partnership_readiness") == "CLOSING_READY":
        application["status"] = "CLEARED_TO_CLOSE"
        bump(application)

    return okay(derive.public_application(application))


@bp.post(API + "/mortgage-applications/<aid>/deny")
def deny_application(aid):
    auth("MortgageOfficer")
    application = get_application(aid)
    data = body()
    reason = venum(data, "denial_reason_code",
                   ("AFFORDABILITY", "SUBSIDY_CAPACITY", "READINESS", "DOCUMENTATION"),
                   required=True)

    cascade.state_gate(application, "status", ("DRAFT", "UNDERWRITING", "APPROVED"),
                       STATUS_TERMINALS)
    program = derive.program_of_application(application)
    cascade.guard_not_frozen(program)

    was_approved = application["status"] == "APPROVED"
    application["denial_reason_code"] = reason
    application["status"] = "DENIED"
    bump(application)

    site = db.sites.get(application.get("build_site_id"))
    if site is not None and site.get("assigned_household_id") == application.get("household_id"):
        site["assigned_household_id"] = None
        derive.refresh_site(site)
        bump(site)

    if was_approved:
        _touch_program(program)

    return okay(derive.public_application(application))


@bp.post(API + "/mortgage-applications/<aid>/close")
def close_application(aid):
    auth("MortgageOfficer")
    application = get_application(aid)
    data = body()
    vdatetime(data, "closing_date", default=None, nullable=True)

    cascade.state_gate(application, "status", ("CLEARED_TO_CLOSE",), STATUS_TERMINALS)
    program = derive.program_of_application(application)
    cascade.guard_not_frozen(program)

    household = db.households.get(application.get("household_id"))
    site = db.sites.get(application.get("build_site_id"))

    # 34 education gating
    enrollment = derive.core_enrollment(household) if household is not None else None
    if enrollment is None or enrollment.get("status") not in ("COMPLETED", "EXPIRED"):
        fail("ERR_EDUCATION_NOT_COMPLETE")
    if enrollment.get("status") == "EXPIRED":
        fail("ERR_EDUCATION_EXPIRED")
    expires = date_start(enrollment.get("expires_on"))
    if expires is None or expires <= db.now():
        fail("ERR_EDUCATION_EXPIRED")

    # 37 closing prerequisites
    if site is None or site.get("readiness_status") != "COMPLETED":
        fail("ERR_SITE_NOT_COMPLETED")
    derive.refresh_household(household)
    if not household.get("sweat_equity_satisfied"):
        fail("ERR_SWEAT_EQUITY_INCOMPLETE")
    if household.get("partnership_readiness") != "CLOSING_READY":
        fail("ERR_TRANSITION_NOT_ALLOWED", "The household is not closing ready.")

    silent = application.get("silent_second_amount_cents") or 0
    if silent <= 0:
        fail("ERR_TRANSITION_NOT_ALLOWED", "There is no silent second to record.")

    now = db.now()
    application["status"] = "CLOSED"
    application["lien_status"] = "ACTIVE"
    application["lien_recorded_on"] = now
    application["lien_outstanding_cents"] = silent
    application["forgiven_amount_cents"] = 0
    bump(application)

    household["selection_status"] = "CLOSED"
    household["closing_date"] = now
    derive.refresh_household(household)
    bump(household)

    derive.refresh_site(site)
    bump(site)
    _touch_program(program)
    return okay(derive.public_application(application))


# --------------------------------------------------------------------------- #
# the silent second
# --------------------------------------------------------------------------- #
@bp.post(API + "/mortgage-applications/<aid>/lien-actions")
def lien_action(aid):
    auth("MortgageOfficer", "ProgramAdmin")
    application = get_application(aid)
    data = body()
    action = venum(data, "action", LIEN_ACTIONS, required=True, alias_map=LIEN_ALIASES)
    effective = vdatetime(data, "effective_date", required=True)
    sale_price = vint(data, "sale_price_cents", minimum=0, default=None, nullable=True)
    reference = vstring(data, "counseling_session_reference", 1, None,
                        default=None, nullable=True)

    origins = {
        "FORBEARANCE_GRANT": ("ACTIVE",),
        "REINSTATE": ("FORBEARANCE",),
        "TRANSFER_REQUEST": ("ACTIVE",),
        "RECORD_TRANSFER": ("TRANSFER_PENDING",),
        "SATISFY": ("ACTIVE",),
    }[action]

    program = derive.program_of_application(application)
    cascade.guard_not_frozen(program)

    if application.get("status") != "CLOSED":
        fail("ERR_TRANSITION_NOT_ALLOWED", "The application has not closed.")
    cascade.state_gate(application, "lien_status", origins, LIEN_TERMINALS)

    calc.refresh_lien(application)

    if action == "FORBEARANCE_GRANT":
        if not reference:
            fail("ERR_DOCUMENTATION_INCOMPLETE")
        if (application.get("forbearance_counseling_sessions") or 0) > 1:
            fail("ERR_FORBEARANCE_LIMIT_REACHED")
        application["forbearance_counseling_sessions"] = \
            (application.get("forbearance_counseling_sessions") or 0) + 1
        application["lien_status"] = "FORBEARANCE"
        calc.refresh_lien(application)
        bump(application)
    elif action == "REINSTATE":
        application["lien_status"] = "ACTIVE"
        calc.refresh_lien(application)
        bump(application)
    elif action == "TRANSFER_REQUEST":
        if sale_price is None or sale_price <= 0:
            fail("ERR_VALIDATION", "sale_price_cents must be greater than zero.")
        application["_sale_price_cents"] = sale_price
        application["lien_status"] = "TRANSFER_PENDING"
        application["right_of_first_refusal_expires_on"] = effective + days(30)
        calc.refresh_lien(application)
        bump(application)
    elif action == "RECORD_TRANSFER":
        window = date_start(application.get("right_of_first_refusal_expires_on"))
        if window is not None and db.now() < window:
            fail("ERR_ROFR_WINDOW_OPEN")
        price = sale_price if sale_price is not None else application.get("_sale_price_cents")
        total, share = calc.recapture_total(application, price)
        application["_recapture_total_cents"] = total
        application["_shared_appreciation_cents"] = share
        application["lien_status"] = "RECAPTURED"
        bump(application)
        if program is not None:
            program["subsidy_pool_cents"] = (program.get("subsidy_pool_cents") or 0) + share
            _touch_program(program)
    else:
        if (application.get("lien_outstanding_cents") or 0) != 0:
            fail("ERR_LIEN_BALANCE_OUTSTANDING")
        application["lien_status"] = "SATISFIED"
        bump(application)
        _touch_program(program)

    return okay(derive.public_application(application))
