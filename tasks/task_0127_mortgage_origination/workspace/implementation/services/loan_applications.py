"""LoanApplication service & state machine (PRD §3.1–§3.10, SCAFFOLD state_machines.LoanApplication)."""

import db
from config import (
    APP_CLEAR_TO_CLOSE,
    APP_CLOSED,
    APP_CONDITIONAL_APPROVAL,
    APP_DENIED,
    APP_INTAKE,
    APP_PRE_QUALIFIED,
    APP_TERMINAL,
    APP_UNDERWRITING,
    APP_WITHDRAWN,
    APR_COMPLETED,
    APR_EXPIRED,
    DECISION_APPROVE,
    DECISION_COUNTER,
    DECISION_DENY,
    DISC_ACK,
    DISC_ISSUED,
    DISC_NON_TERMINAL,
    DISC_SUPERSEDED,
    DISC_VOIDED,
    DISCLOSURE_KIND_CD,
    DISCLOSURE_KIND_LE,
    DTI_CEILING,
    LOAN_PURPOSE_ALLOWED,
    LOAN_TERM_MONTHS_ALLOWED,
    LOCK_ACTIVE,
    LOCK_CANCELLED,
    LOCK_CONSUMED,
    LTV_CEILING,
    PMI_THRESHOLD,
    PRE_QUAL_CREDIT_SCORE_MIN,
    PRE_QUAL_LOAN_TO_INCOME_MULTIPLIER,
    ROLE_LOAN_OFFICER,
    TITLE_OK_FOR_UNDERWRITING,
    UNDERWRITE_DECISIONS,
    VER_VERIFIED,
)
from errors import (
    ERR_APPLICATION_NOT_FOUND,
    ERR_APPRAISAL_EXPIRED,
    ERR_COMPLIANCE_REVIEWER_CONFLICT,
    ERR_DTI_EXCEEDED,
    ERR_INVALID_COUNTER_OFFER,
    ERR_INVALID_STATE,
    ERR_LTV_EXCEEDED,
    ERR_MISSING_DEPENDENCIES,
    ERR_RATE_LOCK_EXPIRED,
    ERR_TRID_WAITING_PERIOD,
    ERR_UDAAP_REVIEW_REQUIRED,
    ERR_UDAAP_SOD_VIOLATION,
    ERR_VALIDATION,
    raise_error,
)
from services import calculations, clock, lookups
from services.common import bump, init_common, occ_check, touch
from services.validation import (
    require_enum,
    require_int,
    require_string,
)
from utils import parse_iso, to_iso_millis


# -------------------------------------------------------------------------
# Create + fetch
# -------------------------------------------------------------------------
def create(body: dict) -> dict:
    borrower_id = require_string(body, "borrower_id")
    property_address = require_string(body, "property_address")
    sale_price_cents = require_int(body, "sale_price_cents", min_value=1)
    requested_loan_amount_cents = require_int(
        body, "requested_loan_amount_cents", min_value=1
    )
    loan_term_months = require_int(body, "loan_term_months")
    if loan_term_months not in LOAN_TERM_MONTHS_ALLOWED:
        raise_error(
            ERR_VALIDATION,
            f"loan_term_months must be one of {sorted(LOAN_TERM_MONTHS_ALLOWED)}.",
        )
    loan_purpose = require_enum(body, "loan_purpose", LOAN_PURPOSE_ALLOWED)
    assigned_loan_officer_id = require_string(body, "assigned_loan_officer_id")

    if requested_loan_amount_cents > sale_price_cents:
        raise_error(
            ERR_VALIDATION,
            "requested_loan_amount_cents must not exceed sale_price_cents.",
        )

    if borrower_id not in db.borrowers:
        # Borrower existence is a body-level reference, not a path resource: surface as ERR_VALIDATION.
        raise_error(ERR_VALIDATION, "Referenced borrower_id does not exist.")

    app = init_common(
        {
            "borrower_id": borrower_id,
            "property_address": property_address,
            "sale_price_cents": int(sale_price_cents),
            "requested_loan_amount_cents": int(requested_loan_amount_cents),
            "loan_term_months": int(loan_term_months),
            "loan_purpose": loan_purpose,
            "status": APP_INTAKE,
            "counter_offered_amount_cents": None,
            "dti_ratio": None,
            "ltv_ratio": None,
            "pmi_required": False,
            "assigned_loan_officer_id": assigned_loan_officer_id,
            "compliance_reviewer_id": None,
            "trid_clock_started_at": None,
            "closing_eligible_at": None,
        }
    )
    db.loan_applications[app["id"]] = app
    return app


def get_or_404(application_id: str) -> dict:
    app = db.loan_applications.get(application_id)
    if app is None:
        raise_error(ERR_APPLICATION_NOT_FOUND, "LoanApplication not found.")
    return app


def list_paginated(*, status=None, borrower_id=None, limit=10, offset=0):
    items = list(db.loan_applications.values())
    if status is not None:
        items = [a for a in items if a["status"] == status]
    if borrower_id is not None:
        items = [a for a in items if a["borrower_id"] == borrower_id]
    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    return items[offset : offset + limit], total


# -------------------------------------------------------------------------
# Lazy expiry checks (PRD §3.4, §3.5, §3.7)
# -------------------------------------------------------------------------
def _ensure_appraisal_not_expired(application: dict) -> None:
    apr = lookups.completed_appraisal(application["id"])
    if apr is None:
        return
    vu = parse_iso(apr.get("valid_until"))
    now = clock.get_now_dt()
    if vu is not None and now > vu:
        apr["status"] = APR_EXPIRED
        bump(apr)
        raise_error(ERR_APPRAISAL_EXPIRED, "Appraisal has expired.")


def _ensure_rate_lock_not_expired(application: dict) -> None:
    rl = lookups.find_active_rate_lock(application["id"])
    if rl is None:
        raise_error(ERR_RATE_LOCK_EXPIRED, "No active rate lock for this application.")
    expires = parse_iso(rl["lock_expires_at"])
    now = clock.get_now_dt()
    if expires is None or now > expires:
        # Lazy expiry.
        from config import LOCK_EXPIRED
        rl["status"] = LOCK_EXPIRED
        bump(rl)
        raise_error(ERR_RATE_LOCK_EXPIRED, "Rate lock has expired.")


# -------------------------------------------------------------------------
# Cascade helpers
# -------------------------------------------------------------------------
def _cascade_rate_lock_on_terminal(application: dict, *, full_refund: bool) -> None:
    rl = lookups.find_active_rate_lock(application["id"])
    if rl is None:
        return
    rl["status"] = LOCK_CANCELLED
    if full_refund:
        rl["refund_cents"] = int(rl["lock_fee_cents"]) + int(
            rl.get("extension_fee_paid_cents", 0)
        )
    else:
        # 48-hour free-look rule
        locked_at = parse_iso(rl["locked_at"])
        now = clock.get_now_dt()
        if locked_at and (now - locked_at).total_seconds() <= 48 * 3600:
            rl["refund_cents"] = int(rl["lock_fee_cents"]) + int(
                rl.get("extension_fee_paid_cents", 0)
            )
        else:
            rl["refund_cents"] = 0
    bump(rl)


def _cascade_void_disclosures(application: dict) -> None:
    for d in db.disclosures.values():
        if d["application_id"] != application["id"]:
            continue
        if d["status"] in DISC_NON_TERMINAL:
            d["status"] = DISC_VOIDED
            touch(d)


def _supersede_latest_le(application: dict) -> None:
    le = lookups.latest_non_voided_disclosure(application["id"], DISCLOSURE_KIND_LE)
    if le is None:
        return
    if le["status"] in DISC_NON_TERMINAL:
        le["status"] = DISC_SUPERSEDED
        touch(le)


# -------------------------------------------------------------------------
# State transitions
# -------------------------------------------------------------------------
def pre_qualify(application_id: str, body: dict) -> dict:
    app = get_or_404(application_id)
    occ_check(app, body)
    if app["status"] != APP_INTAKE:
        raise_error(ERR_INVALID_STATE, "Application must be in INTAKE.")

    borrower = db.borrowers.get(app["borrower_id"])
    if borrower is None:
        raise_error(ERR_VALIDATION, "Borrower for this application is missing.")
    if borrower["credit_score"] < PRE_QUAL_CREDIT_SCORE_MIN:
        raise_error(ERR_INVALID_STATE, "Borrower credit_score below 620.")
    if borrower["annual_income_cents"] <= 0:
        raise_error(ERR_INVALID_STATE, "Borrower annual_income_cents must be > 0.")
    if app["requested_loan_amount_cents"] > (
        PRE_QUAL_LOAN_TO_INCOME_MULTIPLIER * borrower["annual_income_cents"]
    ):
        raise_error(
            ERR_INVALID_STATE,
            "requested_loan_amount_cents exceeds 4x stated annual income.",
        )

    app["status"] = APP_PRE_QUALIFIED
    app["dti_ratio"] = _decimal_or_none(
        calculations.compute_dti(app, borrower, variant="pre_qualification")
    )
    bump(app)
    return app


def submit_underwriting(application_id: str, actor_user_id: str, body: dict) -> dict:
    lock = db.get_submit_lock(application_id)
    if not lock.acquire(blocking=False):
        raise_error(
            ERR_COMPLIANCE_REVIEWER_CONFLICT,
            "Another submit-underwriting is in flight.",
        )
    try:
        app = get_or_404(application_id)
        occ_check(app, body)

        if app["status"] != APP_PRE_QUALIFIED:
            raise_error(ERR_INVALID_STATE, "Application must be in PRE_QUALIFIED.")

        # Priority 9: appraisal-validity is time-gated and must be evaluated.
        _ensure_appraisal_not_expired(app)

        # Priority 11: required dependencies (post-state, post-temporal).
        if not lookups.any_verified_income(application_id):
            raise_error(ERR_MISSING_DEPENDENCIES, "No VERIFIED IncomeVerification.")
        if not lookups.any_verified_asset(application_id):
            raise_error(ERR_MISSING_DEPENDENCIES, "No VERIFIED AssetVerification.")
        apr = lookups.completed_appraisal(application_id)
        if apr is None:
            raise_error(ERR_MISSING_DEPENDENCIES, "No COMPLETED Appraisal.")
        ts = lookups.title_search_for(application_id)
        if ts is None or ts["status"] not in TITLE_OK_FOR_UNDERWRITING:
            raise_error(
                ERR_MISSING_DEPENDENCIES, "TitleSearch must be CLEAR or RESOLVED."
            )
        le = lookups.latest_non_voided_disclosure(application_id, DISCLOSURE_KIND_LE)
        if le is None or le["status"] not in DISC_NON_TERMINAL:
            raise_error(
                ERR_MISSING_DEPENDENCIES,
                "An ISSUED or ACKNOWLEDGED LOAN_ESTIMATE must exist.",
            )

        # Required body field: compliance_reviewer_id (and segregation-of-duties).
        compliance_reviewer_id = require_string(body, "compliance_reviewer_id")
        if compliance_reviewer_id == app.get("assigned_loan_officer_id"):
            raise_error(
                ERR_UDAAP_SOD_VIOLATION,
                "compliance_reviewer_id must not equal assigned_loan_officer_id.",
            )

        # First-writer-wins on compliance_reviewer_id.
        if app.get("compliance_reviewer_id") is not None:
            raise_error(
                ERR_COMPLIANCE_REVIEWER_CONFLICT,
                "compliance_reviewer_id already assigned.",
            )

        borrower = db.borrowers.get(app["borrower_id"])
        dti = calculations.compute_dti(app, borrower, variant="underwriting")
        if dti is None:
            raise_error(ERR_MISSING_DEPENDENCIES, "Cannot compute underwriting DTI.")

        ltv = calculations.compute_ltv(app, apr)

        app["compliance_reviewer_id"] = compliance_reviewer_id
        app["status"] = APP_UNDERWRITING
        app["dti_ratio"] = _decimal_or_none(dti)
        app["ltv_ratio"] = _decimal_or_none(ltv)
        bump(app)
        return app
    finally:
        lock.release()


def underwrite_decision(application_id: str, actor_user_id: str, body: dict) -> dict:
    app = get_or_404(application_id)
    occ_check(app, body)

    # Priority 5: state.
    if app["status"] != APP_UNDERWRITING:
        raise_error(ERR_INVALID_STATE, "Application must be in UNDERWRITING.")

    # Priority 6: segregation of duties.
    if (
        app.get("compliance_reviewer_id")
        and actor_user_id == app["compliance_reviewer_id"]
    ):
        raise_error(
            ERR_UDAAP_SOD_VIOLATION,
            "Acting user must not be the compliance reviewer.",
        )

    decision = require_enum(body, "decision", UNDERWRITE_DECISIONS)

    if decision == DECISION_APPROVE:
        # Priority 7: UDAAP review against latest LOAN_ESTIMATE version.
        le = lookups.latest_non_voided_disclosure(application_id, DISCLOSURE_KIND_LE)
        if le is None:
            raise_error(
                ERR_UDAAP_REVIEW_REQUIRED, "No LOAN_ESTIMATE to review against."
            )
        if not lookups.latest_udaap_review_pass_against_le_version(
            application_id, le["version"]
        ):
            raise_error(
                ERR_UDAAP_REVIEW_REQUIRED,
                "UDAAPReview with outcome=PASS required for the latest LOAN_ESTIMATE.",
            )

        # Priorities 16, 17: DTI/LTV ceilings.
        from decimal import Decimal as _D
        dti = app.get("dti_ratio")
        if dti is None or _D(str(dti)) > DTI_CEILING:
            raise_error(ERR_DTI_EXCEEDED, "DTI ratio exceeds 0.43.")
        ltv = app.get("ltv_ratio")
        if ltv is None or _D(str(ltv)) > LTV_CEILING:
            raise_error(ERR_LTV_EXCEEDED, "LTV ratio exceeds 0.97.")

        app["status"] = APP_CONDITIONAL_APPROVAL
        app["pmi_required"] = bool(_D(str(ltv)) > PMI_THRESHOLD)
        bump(app)
        return app

    if decision == DECISION_COUNTER:
        counter_amt = require_int(body, "counter_offered_amount_cents")
        if counter_amt <= 0 or counter_amt >= app["requested_loan_amount_cents"]:
            raise_error(
                ERR_INVALID_COUNTER_OFFER,
                "counter_offered_amount_cents must be > 0 and < requested_loan_amount_cents.",
            )
        app["counter_offered_amount_cents"] = int(counter_amt)
        app["status"] = APP_PRE_QUALIFIED
        bump(app)
        _supersede_latest_le(app)
        return app

    # decision == DECISION_DENY
    app["status"] = APP_DENIED
    bump(app)
    _cascade_void_disclosures(app)
    _cascade_rate_lock_on_terminal(app, full_refund=True)
    return app


def clear_to_close(application_id: str, actor_user_id: str, body: dict) -> dict:
    app = get_or_404(application_id)
    occ_check(app, body)

    if app["status"] != APP_CONDITIONAL_APPROVAL:
        raise_error(ERR_INVALID_STATE, "Application must be in CONDITIONAL_APPROVAL.")

    # Priority 6: SoD.
    if (
        app.get("compliance_reviewer_id")
        and actor_user_id == app["compliance_reviewer_id"]
    ):
        raise_error(
            ERR_UDAAP_SOD_VIOLATION,
            "Acting user must not be the compliance reviewer.",
        )

    # Priority 7: UDAAP review against latest CLOSING_DISCLOSURE.
    cd = lookups.latest_non_voided_disclosure(application_id, DISCLOSURE_KIND_CD)
    if cd is None or cd["status"] not in DISC_NON_TERMINAL:
        raise_error(
            ERR_UDAAP_REVIEW_REQUIRED,
            "An ISSUED or ACKNOWLEDGED CLOSING_DISCLOSURE is required.",
        )
    if not lookups.latest_udaap_review_pass_against_cd_version(
        application_id, cd["version"]
    ):
        raise_error(
            ERR_UDAAP_REVIEW_REQUIRED,
            "UDAAPReview with outcome=PASS required for the latest CLOSING_DISCLOSURE.",
        )

    # Priority 8: TRID waiting period.
    eligible = parse_iso(cd.get("eligible_to_consummate_at"))
    now = clock.get_now_dt()
    if eligible is None or now < eligible:
        raise_error(
            ERR_TRID_WAITING_PERIOD,
            "TRID 3-business-day waiting period has not elapsed.",
        )

    # Priority 9: appraisal-expired.
    _ensure_appraisal_not_expired(app)

    # Priority 10: rate-lock-expired.
    _ensure_rate_lock_not_expired(app)

    # Title check is also required.
    ts = lookups.title_search_for(application_id)
    if ts is None or ts["status"] not in TITLE_OK_FOR_UNDERWRITING:
        raise_error(ERR_INVALID_STATE, "TitleSearch must be CLEAR or RESOLVED.")

    app["status"] = APP_CLEAR_TO_CLOSE
    app["closing_eligible_at"] = clock.get_now_iso()
    bump(app)
    return app


def close(application_id: str, body: dict) -> dict:
    app = get_or_404(application_id)
    occ_check(app, body)

    if app["status"] != APP_CLEAR_TO_CLOSE:
        raise_error(ERR_INVALID_STATE, "Application must be in CLEAR_TO_CLOSE.")

    # Priority 10: rate-lock-expired.
    _ensure_rate_lock_not_expired(app)

    rl = lookups.find_active_rate_lock(app["id"])
    app["status"] = APP_CLOSED
    bump(app)

    if rl is not None:
        rl["status"] = LOCK_CONSUMED
        bump(rl)

    cd = lookups.latest_non_voided_disclosure(app["id"], DISCLOSURE_KIND_CD)
    if cd is not None and cd["status"] == DISC_ISSUED:
        cd["status"] = DISC_ACK
        cd["acknowledged_at"] = clock.get_now_iso()
        touch(cd)
    return app


def withdraw(application_id: str, body: dict) -> dict:
    app = get_or_404(application_id)
    occ_check(app, body)
    if app["status"] not in {APP_INTAKE, APP_PRE_QUALIFIED, APP_UNDERWRITING}:
        raise_error(
            ERR_INVALID_STATE,
            "Withdrawal is only allowed from INTAKE, PRE_QUALIFIED, or UNDERWRITING.",
        )

    prior_status = app["status"]
    app["status"] = APP_WITHDRAWN
    bump(app)
    # No cascade from INTAKE — no rate lock can exist.
    if prior_status != APP_INTAKE:
        _cascade_rate_lock_on_terminal(app, full_refund=False)
    return app


def _decimal_or_none(value):
    """Render Decimals as float on entity dicts so JSON serialisation is straightforward."""
    if value is None:
        return None
    return float(value)
