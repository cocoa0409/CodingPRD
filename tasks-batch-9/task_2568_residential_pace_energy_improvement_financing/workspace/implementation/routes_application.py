"""Applications, project measures, submit / underwrite / cure / approve."""

from flask import Blueprint

import calc
import db
import response
import services
import validation as v
from errors import fail
from middleware import (
    ALL_ROLES,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_PROGRAM_ADMIN,
    ROLE_PROPERTY_OWNER,
    ROLE_UNDERWRITING_ANALYST,
    authorize,
    require_property_owner,
)

bp = Blueprint("application", __name__)

LIVE_APPLICATION_STATUSES = (
    "DRAFT",
    "UNDER_REVIEW",
    "NEEDS_CURE",
    "CONSENT_PENDING",
    "APPROVED",
    "FUNDING_PENDING",
    "FUNDING_HELD",
    "FUNDED",
)


def _list(rows, limit, offset):
    window, total = response.paginate(rows, limit, offset)
    return response.listing([db.public(row) for row in window], limit, offset, total)


def _require_version(expected, application):
    """Ladder stage 7 - optimistic concurrency on the parent application."""
    if expected != int(application["version"]):
        fail(
            "ERR_APPLICATION_VERSION_CONFLICT",
            "expected_application_version does not match the application version",
        )


# ------------------------------------------------------------- applications --
@bp.post("/pace/applications")
def create_application():
    caller = authorize([ROLE_PROPERTY_OWNER])
    payload = v.body()
    property_id = v.req_id(payload, "property_id")
    contractor_id = v.req_id(payload, "contractor_id")
    requested_term_years = v.req_int(
        payload, "requested_term_years", minimum=5, maximum=30
    )
    supersedes_application_id = v.opt_id(payload, "supersedes_application_id")
    prop = services.get_property(property_id)
    contractor = services.get_contractor(contractor_id)
    predecessor = None
    if supersedes_application_id is not None:
        predecessor = services.get_application(supersedes_application_id)
    require_property_owner(caller, prop["id"])
    if contractor["enrollment_status"] != "ENROLLED":
        fail("ERR_CONTRACTOR_NOT_ENROLLED", "Contractor is not ENROLLED")
    if predecessor is not None:
        if predecessor["property_id"] != prop["id"] or predecessor["status"] not in (
            "DECLINED",
            "WITHDRAWN",
        ):
            fail(
                "ERR_INVALID_SUPERSEDE_TARGET",
                "supersedes_application_id must name a dead application on this parcel",
            )
    if prop["in_bankruptcy"]:
        fail("ERR_PROPERTY_IN_BANKRUPTCY", "The parcel owner is in bankruptcy")
    for row in services.applications_of_property(prop["id"]):
        if row["status"] in LIVE_APPLICATION_STATUSES:
            fail(
                "ERR_DUPLICATE_ACTIVE_APPLICATION",
                "Another application on this parcel is still alive",
            )
    oral_required = (
        prop["preferred_language"] == "ES"
        or prop["occupancy_type"] != "OWNER_OCCUPIED"
    )
    application = db.create(
        "applications",
        {
            "property_id": prop["id"],
            "contractor_id": contractor["id"],
            "supersedes_application_id": supersedes_application_id,
            "requested_term_years": requested_term_years,
            "status": "DRAFT",
            "requested_principal_cents": 0,
            "screening_cltv_bps": None,
            "underwriting_cltv_bps": None,
            "valuation_basis": None,
            "portfolio_sir_bps": None,
            "min_measure_sir_bps": None,
            "weighted_useful_life_years": None,
            "cure_round_count": 0,
            "cure_reason_codes": [],
            "decline_reason_code": None,
            "underwriter_user_id": None,
            "approver_user_id": None,
            "notified_lien_count": 0,
            "consent_deadline_at": None,
            "consent_posture": "NOT_STARTED",
            "oral_confirmation_required": oral_required,
            "funding_hold_reason": None,
            "_consent_started": False,
        },
    )
    return response.created(db.public(application))


@bp.get("/pace/applications/<row_id>")
def read_application(row_id):
    authorize(ALL_ROLES)
    return response.ok(db.public(services.get_application(row_id)))


@bp.get("/pace/applications")
def list_applications():
    authorize(ALL_ROLES)
    limit, offset = v.pagination()
    property_id = v.filter_value("property_id")
    contractor_id = v.filter_value("contractor_id")
    supersedes_application_id = v.filter_value("supersedes_application_id")
    status = v.filter_value("status")
    rows = db.by_created_at(db.rows("applications"))
    if property_id:
        rows = [row for row in rows if row["property_id"] == property_id]
    if contractor_id:
        rows = [row for row in rows if row["contractor_id"] == contractor_id]
    if supersedes_application_id:
        rows = [
            row
            for row in rows
            if row.get("supersedes_application_id") == supersedes_application_id
        ]
    if status:
        rows = [row for row in rows if row["status"] == status]
    return _list(rows, limit, offset)


# ---------------------------------------------------------- project measures --
@bp.post("/pace/applications/<row_id>/measures")
def add_measure(row_id):
    caller = authorize([ROLE_PROPERTY_OWNER])
    payload = v.body()
    product_id = v.req_id(payload, "product_id")
    installed_cost_cents = v.req_int(payload, "installed_cost_cents", minimum=100000)
    estimated_annual_savings_cents = v.req_int(
        payload, "estimated_annual_savings_cents", minimum=1
    )
    expected_version = v.req_int(payload, "expected_application_version", minimum=0)
    application = services.get_application(row_id)
    product = services.get_product(product_id)
    require_property_owner(caller, application["property_id"])
    _require_version(expected_version, application)
    if product["status"] != "ACTIVE":
        fail("ERR_PRODUCT_RETIRED", "The catalog product is RETIRED")
    if application["status"] not in ("DRAFT", "NEEDS_CURE"):
        fail("ERR_APPLICATION_STATE_INVALID", "Application is not DRAFT or NEEDS_CURE")
    siblings = services.measures_of(application["id"])
    for sibling in siblings:
        if sibling["product_id"] == product["id"]:
            fail(
                "ERR_DUPLICATE_MEASURE_PRODUCT",
                "Another measure of this application already names that product",
            )
    if len(siblings) >= 5:
        fail("ERR_MEASURE_LIMIT_EXCEEDED", "An application may hold at most 5 measures")
    if estimated_annual_savings_cents > int(product["max_annual_savings_cents"]):
        fail(
            "ERR_SAVINGS_EXCEEDS_PRODUCT_CAP",
            "estimated_annual_savings_cents exceeds the product's savings cap",
        )
    measure = db.create(
        "measures",
        {
            "application_id": application["id"],
            "product_id": product["id"],
            "installed_cost_cents": installed_cost_cents,
            "estimated_annual_savings_cents": estimated_annual_savings_cents,
            "pv_savings_cents": 0,
            "sir_bps": 0,
            "status": "PROPOSED",
        },
    )
    db.touch(application)
    return response.created(db.public(measure))


@bp.get("/pace/measures/<row_id>")
def read_measure(row_id):
    authorize(ALL_ROLES)
    return response.ok(db.public(services.get_measure(row_id)))


@bp.get("/pace/measures")
def list_measures():
    authorize(ALL_ROLES)
    limit, offset = v.pagination()
    application_id = v.filter_value("application_id")
    product_id = v.filter_value("product_id")
    status = v.filter_value("status")
    rows = db.by_created_at(db.rows("measures"))
    if application_id:
        rows = [row for row in rows if row["application_id"] == application_id]
    if product_id:
        rows = [row for row in rows if row["product_id"] == product_id]
    if status:
        rows = [row for row in rows if row["status"] == status]
    return _list(rows, limit, offset)


# -------------------------------------------------------------- submit / cure --
@bp.post("/pace/applications/<row_id>/submit")
def submit_application(row_id):
    caller = authorize([ROLE_PROPERTY_OWNER])
    v.body()
    application = services.get_application(row_id)
    require_property_owner(caller, application["property_id"])
    if application["status"] != "DRAFT":
        fail("ERR_APPLICATION_STATE_INVALID", "Application is not DRAFT")
    prop = services.get_property(application["property_id"])
    if prop["in_bankruptcy"]:
        fail("ERR_PROPERTY_IN_BANKRUPTCY", "The parcel owner is in bankruptcy")
    if int(prop["tax_delinquency_count_36m"]) > 1:
        fail("ERR_TAX_DELINQUENCY_HISTORY", "The parcel has too many tax delinquencies")
    plan = services.compute_pricing(application)
    if not plan["measures"]:
        fail("ERR_NO_ELIGIBLE_MEASURES", "The application holds no PROPOSED measure")
    term = int(application["requested_term_years"])
    if term not in v.ALLOWED_TERMS or term > int(plan["weighted_useful_life_years"]):
        fail(
            "ERR_TERM_EXCEEDS_USEFUL_LIFE",
            "requested_term_years is not an allowed term within the useful life",
        )
    services.apply_pricing(application, plan)
    application["status"] = "UNDER_REVIEW"
    db.touch(application)
    return response.ok(db.public(application))


@bp.post("/pace/applications/<row_id>/cure")
def cure_application(row_id):
    caller = authorize([ROLE_PROPERTY_OWNER])
    payload = v.body()
    v.opt_str(payload, "note")
    application = services.get_application(row_id)
    require_property_owner(caller, application["property_id"])
    if application["status"] != "NEEDS_CURE":
        fail("ERR_APPLICATION_STATE_INVALID", "Application is not NEEDS_CURE")
    plan = services.compute_pricing(application)
    if not plan["measures"]:
        fail("ERR_NO_ELIGIBLE_MEASURES", "The application holds no PROPOSED measure")
    services.apply_pricing(application, plan)
    application["cure_reason_codes"] = []
    application["status"] = "UNDER_REVIEW"
    db.touch(application)
    return response.ok(db.public(application))


# ----------------------------------------------------------------- underwrite --
@bp.post("/pace/applications/<row_id>/underwrite")
def underwrite_application(row_id):
    caller = authorize([ROLE_UNDERWRITING_ANALYST])
    payload = v.body()
    decision = v.req_enum(payload, "decision", ("PROCEED", "CURE", "DECLINE"))
    elected_basis = v.opt_enum(payload, "valuation_basis", ("ASSESSED", "MARKET"))
    cure_reason_codes = None
    decline_reason_code = None
    if decision == "CURE":
        cure_reason_codes = v.req_str_array(
            payload, "cure_reason_codes", allowed=v.CURE_REASON_CODES
        )
    elif decision == "DECLINE":
        decline_reason_code = v.req_enum(
            payload, "decline_reason_code", v.ANALYST_DECLINE_REASONS
        )
    application = services.get_application(row_id)
    if application["status"] != "UNDER_REVIEW":
        fail("ERR_APPLICATION_STATE_INVALID", "Application is not UNDER_REVIEW")
    prop = services.get_property(application["property_id"])
    if prop["in_bankruptcy"]:
        fail("ERR_PROPERTY_IN_BANKRUPTCY", "The parcel owner is in bankruptcy")
    if int(prop["tax_delinquency_count_36m"]) > 1:
        fail("ERR_TAX_DELINQUENCY_HISTORY", "The parcel has too many tax delinquencies")
    proposed = [
        row for row in services.measures_of(application["id"]) if row["status"] == "PROPOSED"
    ]
    if not proposed:
        fail("ERR_NO_ELIGIBLE_MEASURES", "The application holds no PROPOSED measure")

    applied_basis, basis_value = services.valuation_basis_value(
        prop, elected_basis if elected_basis else "ASSESSED"
    )

    if decision == "PROCEED":
        approved = []
        for measure in proposed:
            product = db.get("products", measure["product_id"])
            if int(measure["sir_bps"]) >= calc.SIR_FLOOR_BPS and product["status"] == "ACTIVE":
                approved.append(measure)
        if not approved:
            fail("ERR_NO_ELIGIBLE_MEASURES", "No measure survives the per-measure gate")
        approved_principal = sum(int(row["installed_cost_cents"]) for row in approved)
        approved_pv = sum(int(row["pv_savings_cents"]) for row in approved)
        portfolio = calc.portfolio_sir_bps(approved_pv, approved_principal)
        if portfolio is None or portfolio < calc.SIR_FLOOR_BPS:
            fail("ERR_SIR_FLOOR_NOT_MET", "The blended savings ratio is below the floor")
        cltv = calc.cltv_bps(
            prop["senior_lien_balance_cents"],
            prop["committed_pace_principal_cents"],
            approved_principal,
            basis_value,
        )
        if cltv is None or cltv > calc.CLTV_CAP_BPS:
            fail("ERR_CLTV_LIMIT_EXCEEDED", "The combined lien-to-value ratio is too high")
        ptv = calc.ptv_bps(approved_principal, prop["assessed_value_cents"])
        if ptv is None or ptv > calc.PTV_CAP_BPS:
            fail("ERR_PTV_LIMIT_EXCEEDED", "The principal-to-value ratio is too high")
        equity = calc.equity_ratio_bps(
            prop["senior_lien_balance_cents"], prop["assessed_value_cents"]
        )
        if equity < calc.EQUITY_FLOOR_BPS:
            fail("ERR_EQUITY_FLOOR_NOT_MET", "The parcel equity ratio is below the floor")
        approved_ids = set(row["id"] for row in approved)
        for measure in proposed:
            measure["status"] = "APPROVED" if measure["id"] in approved_ids else "INELIGIBLE"
            db.touch(measure)
        application["requested_principal_cents"] = approved_principal
        application["portfolio_sir_bps"] = portfolio
        application["underwriting_cltv_bps"] = cltv
        application["valuation_basis"] = applied_basis
        application["underwriter_user_id"] = caller.user_id
        application["status"] = "CONSENT_PENDING"
        services.notify_liens(application)
        db.touch(application)
        return response.ok(db.public(application))

    cltv = calc.cltv_bps(
        prop["senior_lien_balance_cents"],
        prop["committed_pace_principal_cents"],
        application["requested_principal_cents"],
        basis_value,
    )
    application["underwriting_cltv_bps"] = cltv
    application["valuation_basis"] = applied_basis
    application["underwriter_user_id"] = caller.user_id

    if decision == "CURE":
        if int(application["cure_round_count"]) >= 2:
            application["status"] = "DECLINED"
            application["decline_reason_code"] = "CURE_ROUNDS_EXHAUSTED"
            for measure in proposed:
                measure["status"] = "INELIGIBLE"
                db.touch(measure)
        else:
            application["cure_reason_codes"] = cure_reason_codes
            application["cure_round_count"] = int(application["cure_round_count"]) + 1
            application["status"] = "NEEDS_CURE"
    else:
        application["status"] = "DECLINED"
        application["decline_reason_code"] = decline_reason_code
        for measure in proposed:
            measure["status"] = "INELIGIBLE"
            db.touch(measure)
    db.touch(application)
    return response.ok(db.public(application))


# -------------------------------------------------------------------- approve --
@bp.post("/pace/applications/<row_id>/approve")
def approve_application(row_id):
    caller = authorize([ROLE_COMPLIANCE_OFFICER])
    payload = v.body()
    v.opt_str(payload, "note")
    application = services.get_application(row_id)
    if application["status"] != "CONSENT_PENDING":
        fail("ERR_APPLICATION_STATE_INVALID", "Application is not CONSENT_PENDING")
    if (
        application.get("underwriter_user_id") is not None
        and caller.user_id == application["underwriter_user_id"]
    ):
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The approver may not be the analyst that underwrote the application",
        )
    prop = services.get_property(application["property_id"])
    services.deemed_consent_sweep(application, prop)
    posture = services.derive_consent_posture(application)
    if posture == "VETOED":
        fail("ERR_LENDER_CONSENT_DECLINED", "A mortgage holder declined the assessment")
    if posture != "CLEARED":
        fail("ERR_LENDER_CONSENT_PENDING", "Lender consent is still outstanding")
    application["consent_posture"] = "CLEARED"
    application["approver_user_id"] = caller.user_id
    application["status"] = "APPROVED"
    db.touch(application)
    return response.ok(db.public(application))


# --------------------------------------------------------- eligibility report --
@bp.get("/pace/applications/<row_id>/eligibility-report")
def eligibility_report(row_id):
    authorize(
        [
            ROLE_PROPERTY_OWNER,
            ROLE_UNDERWRITING_ANALYST,
            ROLE_COMPLIANCE_OFFICER,
            ROLE_PROGRAM_ADMIN,
        ]
    )
    application = services.get_application(row_id)
    prop = services.get_property(application["property_id"])
    measures = services.measures_of(application["id"])
    live = [row for row in measures if row["status"] in ("PROPOSED", "APPROVED")]
    proposed = [row for row in measures if row["status"] == "PROPOSED"]
    preview = []
    for measure in measures:
        if measure["status"] == "APPROVED":
            preview.append(measure)
        elif measure["status"] == "PROPOSED":
            product = db.get("products", measure["product_id"])
            if (
                int(measure["sir_bps"]) >= calc.SIR_FLOOR_BPS
                and product is not None
                and product["status"] == "ACTIVE"
            ):
                preview.append(measure)
    approved_principal = sum(int(row["installed_cost_cents"]) for row in preview)
    proposed_principal = sum(int(row["installed_cost_cents"]) for row in proposed)
    approved_pv = sum(int(row["pv_savings_cents"]) for row in preview)
    portfolio = calc.portfolio_sir_bps(approved_pv, approved_principal)
    min_measure = min([int(row["sir_bps"]) for row in live]) if live else None
    pairs = []
    for measure in live:
        product = db.get("products", measure["product_id"])
        if product is not None:
            pairs.append((measure["installed_cost_cents"], product["useful_life_years"]))
    weighted_life = calc.weighted_useful_life_years(pairs) if pairs else None
    senior = prop["senior_lien_balance_cents"]
    committed = prop["committed_pace_principal_cents"]
    cltv_assessed = calc.cltv_bps(
        senior, committed, approved_principal, prop["assessed_value_cents"]
    )
    market_denominator = prop.get("market_value_cents")
    if market_denominator is None:
        market_denominator = prop["assessed_value_cents"]
    cltv_market = calc.cltv_bps(senior, committed, approved_principal, market_denominator)
    ptv = calc.ptv_bps(approved_principal, prop["assessed_value_cents"])
    equity = calc.equity_ratio_bps(senior, prop["assessed_value_cents"])
    stored_basis = application.get("valuation_basis")
    basis_applied = stored_basis if stored_basis else "ASSESSED"
    effective_basis, _basis_value = services.valuation_basis_value(prop, basis_applied)
    cltv_applied = cltv_market if effective_basis == "MARKET" else cltv_assessed
    blocking = None
    if not preview:
        blocking = "ERR_NO_ELIGIBLE_MEASURES"
    elif portfolio is None or portfolio < calc.SIR_FLOOR_BPS:
        blocking = "ERR_SIR_FLOOR_NOT_MET"
    elif cltv_applied is None or cltv_applied > calc.CLTV_CAP_BPS:
        blocking = "ERR_CLTV_LIMIT_EXCEEDED"
    elif ptv is None or ptv > calc.PTV_CAP_BPS:
        blocking = "ERR_PTV_LIMIT_EXCEEDED"
    elif equity < calc.EQUITY_FLOOR_BPS:
        blocking = "ERR_EQUITY_FLOOR_NOT_MET"
    report = {
        "application_id": application["id"],
        "valuation_basis_applied": basis_applied,
        "appraisal_stale": services.appraisal_stale(prop),
        "cltv_bps_assessed": cltv_assessed,
        "cltv_bps_market": cltv_market,
        "ptv_bps": ptv,
        "equity_bps": equity,
        "portfolio_sir_bps": portfolio,
        "min_measure_sir_bps": min_measure,
        "weighted_useful_life_years": weighted_life,
        "approved_principal_cents": approved_principal,
        "proposed_principal_cents": proposed_principal,
        "consent_posture": application["consent_posture"],
        "blocking_error_id": blocking,
        "measure_sir_report": ",".join(
            "%s:%d" % (row["id"], int(row["sir_bps"])) for row in live
        ),
    }
    return response.ok(report)


# ------------------------------------------- per-application child collections --
@bp.get("/pace/applications/<row_id>/financing-agreements")
def list_application_agreements(row_id):
    authorize(ALL_ROLES)
    limit, offset = v.pagination()
    status = v.filter_value("status")
    application = services.get_application(row_id)
    rows = services.agreements_of(application["id"])
    rows = sorted(rows, key=lambda row: row["created_at"], reverse=True)
    if status:
        rows = [row for row in rows if row["status"] == status]
    return _list(rows, limit, offset)


@bp.get("/pace/applications/<row_id>/completion-certificates")
def list_application_certificates(row_id):
    authorize(ALL_ROLES)
    limit, offset = v.pagination()
    status = v.filter_value("status")
    application = services.get_application(row_id)
    rows = services.certificates_of(application["id"])
    if status:
        rows = [row for row in rows if row["status"] == status]
    return _list(rows, limit, offset)
