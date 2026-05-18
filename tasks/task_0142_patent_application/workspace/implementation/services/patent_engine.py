"""Patent-application domain service.

Implements every state transition from SCAFFOLD §1.2 and the supporting
business logic (entity creation, fee recording, clock-driven sweep). Each
public function MUST be invoked while holding `store.lock` so concurrency
contracts (SCAFFOLD §1.2.1) hold.
"""

from datetime import datetime, timezone
from flask import g

from config import (
    APPLICANT_STATUS_ACTIVE,
    APPLICANT_STATUS_SUSPENDED,
    APP_STATUS_ABANDONED,
    APP_STATUS_ALLOWED,
    APP_STATUS_DRAFT,
    APP_STATUS_EXPIRED,
    APP_STATUS_FILED,
    APP_STATUS_GRANTED,
    APP_STATUS_OFFICE_ACTION_PENDING,
    APP_STATUS_UNDER_EXAMINATION,
    APP_TYPE_DESIGN,
    APP_TYPE_PROVISIONAL,
    APP_TYPE_UTILITY,
    APPLICANT_STATUSES,
    APPLICATION_TYPES,
    CONT_CIP,
    CONT_CONTINUATION,
    CONT_NONE,
    CONTINUATION_PARENT_OK_STATUSES,
    CONTINUATION_TYPES,
    ENTITY_SIZES,
    ENTITY_SIZE_MICRO,
    FEE_CATEGORIES,
    FEE_CATEGORY_EXAMINATION,
    FEE_CATEGORY_EXCESS_CLAIM,
    FEE_CATEGORY_EXTENSION,
    FEE_CATEGORY_FILING,
    FEE_CATEGORY_ISSUE,
    FEE_CATEGORY_MAINTENANCE,
    FEE_CATEGORY_PCT_NATIONAL,
    FEE_CATEGORY_PCT_TRANSMITTAL,
    MAINTENANCE_GRACE_PERIOD_DAYS,
    MAINT_STAGE_11_5,
    MAINT_STAGE_3_5,
    MAINT_STAGE_7_5,
    MAINT_STATUS_LAPSED,
    MAINT_STATUS_PAID,
    MAINT_STATUS_SCHEDULED,
    MICRO_INCOME_CAP_CENTS,
    MICRO_PRIOR_FILINGS_MAX,
    OA_EXTENDED_DEADLINE_DAYS,
    OA_RESPONSE_DEADLINE_DAYS,
    OA_STATUS_ABANDONED_BY_DEFAULT,
    OA_STATUS_PENDING,
    OA_STATUS_RESPONDED,
    OA_TYPES,
    PCT_INIT_OK_STATUSES,
    PCT_NATIONAL_DEADLINE_MONTHS,
    PCT_STATUS_INTERNATIONAL,
    PCT_STATUS_LAPSED,
    PCT_STATUS_NATIONAL_ENTERED,
    RISK_SUSPEND_THRESHOLD,
    ROLE_APPLICANT,
    STAGE_ANCHOR_YEARS,
    VOLUNTARY_ABANDON_OK_STATUSES,
)
from db import store
from errors import make_error
from services.calculations import (
    compute_applicant_risk_score,
    compute_forward_expires_at,
    examination_fee as calc_examination_fee,
    excess_claim_fee as calc_excess_claim_fee,
    extension_fee as calc_extension_fee,
    extension_months,
    filing_fee as calc_filing_fee,
    issue_fee as calc_issue_fee,
    maintenance_fee_amount as calc_maintenance_fee,
    pct_national_fee as calc_pct_national_fee,
)
from utils import (
    add_days,
    add_months_30d,
    add_years_as_days,
    iso_now,
    new_uuid,
    parse_iso8601,
)


# ---------------------------------------------------------------------------
# Common-fields helpers
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return iso_now(store.now())


def _common_create_fields() -> dict:
    now = _now_iso()
    return {
        "id": new_uuid(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }


def _bump(entity: dict) -> None:
    """Refresh updated_at and increment version. Used on every mutation."""
    entity["updated_at"] = _now_iso()
    entity["version"] = entity["version"] + 1


def _audit(application_id: str | None, action: str, details: dict | None = None) -> None:
    """Append an AuditEvent. actor_role and actor_id come from flask.g."""
    store.audit_events.append({
        "id": new_uuid(),
        "application_id": application_id,
        "actor_role": getattr(g, "user_role", None),
        "actor_id": getattr(g, "user_id", None),
        "action": action,
        "details": details or {},
        "created_at": _now_iso(),
    })


# ---------------------------------------------------------------------------
# Applicant CRUD
# ---------------------------------------------------------------------------
def create_applicant(*, name: str, entity_size: str,
                     gross_income_cents: int | None,
                     prior_filings_count: int | None) -> dict:
    _validate_applicant_input(
        entity_size=entity_size,
        gross_income_cents=gross_income_cents,
        prior_filings_count=prior_filings_count,
    )
    applicant = {
        **_common_create_fields(),
        "name": name,
        "entity_size": entity_size,
        "gross_income_cents": gross_income_cents,
        "prior_filings_count": prior_filings_count,
        "status": APPLICANT_STATUS_ACTIVE,
        "applicant_risk_score": 0,
    }
    store.applicants[applicant["id"]] = applicant
    return applicant


def update_applicant(applicant_id: str, *, name=None, entity_size=None,
                     gross_income_cents=None, prior_filings_count=None,
                     version: int | None = None) -> dict:
    applicant = store.applicants.get(applicant_id)
    if applicant is None:
        raise make_error("ERR_NOT_FOUND", f"Applicant {applicant_id} not found.")
    # OCC: only check when version is provided
    if version is not None and version != applicant["version"]:
        raise make_error("ERR_VERSION_CONFLICT")
    # Compute the prospective entity_size and the prospective MICRO inputs
    new_entity_size = entity_size if entity_size is not None else applicant["entity_size"]
    new_income = gross_income_cents if gross_income_cents is not None else applicant.get("gross_income_cents")
    new_priors = prior_filings_count if prior_filings_count is not None else applicant.get("prior_filings_count")
    _validate_applicant_input(
        entity_size=new_entity_size,
        gross_income_cents=new_income,
        prior_filings_count=new_priors,
    )
    if name is not None:
        applicant["name"] = name
    if entity_size is not None:
        applicant["entity_size"] = entity_size
    if gross_income_cents is not None:
        applicant["gross_income_cents"] = gross_income_cents
    if prior_filings_count is not None:
        applicant["prior_filings_count"] = prior_filings_count
    _bump(applicant)
    return applicant


def get_applicant_with_risk_eval(applicant_id: str) -> dict:
    """Read an applicant and re-evaluate the risk score / auto-suspension."""
    applicant = store.applicants.get(applicant_id)
    if applicant is None:
        raise make_error("ERR_NOT_FOUND", f"Applicant {applicant_id} not found.")
    score = compute_applicant_risk_score(
        applicant_id, store.applications, store.office_actions, store.maintenance_fees
    )
    if score >= RISK_SUSPEND_THRESHOLD and applicant["status"] == APPLICANT_STATUS_ACTIVE:
        applicant["status"] = APPLICANT_STATUS_SUSPENDED
        _bump(applicant)
        _audit(None, "APPLICANT_SUSPENDED", {"applicant_id": applicant_id, "score": score})
    applicant["applicant_risk_score"] = score
    return applicant


def _validate_applicant_input(*, entity_size: str,
                              gross_income_cents: int | None,
                              prior_filings_count: int | None) -> None:
    """Validates applicant create/update payload.

    Generic shape errors -> ERR_VALIDATION.
    MICRO eligibility failure -> ERR_MICRO_INELIGIBLE.
    """
    if entity_size not in ENTITY_SIZES:
        raise make_error("ERR_VALIDATION", "entity_size must be one of LARGE, SMALL, MICRO.")
    if gross_income_cents is not None and (
        not isinstance(gross_income_cents, int) or gross_income_cents < 0 or isinstance(gross_income_cents, bool)
    ):
        raise make_error("ERR_VALIDATION", "gross_income_cents must be a non-negative integer.")
    if prior_filings_count is not None and (
        not isinstance(prior_filings_count, int) or prior_filings_count < 0 or isinstance(prior_filings_count, bool)
    ):
        raise make_error("ERR_VALIDATION", "prior_filings_count must be a non-negative integer.")
    if entity_size == ENTITY_SIZE_MICRO:
        if gross_income_cents is None or prior_filings_count is None:
            raise make_error(
                "ERR_MICRO_INELIGIBLE",
                "MICRO applicants must declare gross_income_cents and prior_filings_count.",
            )
        if gross_income_cents > MICRO_INCOME_CAP_CENTS:
            raise make_error("ERR_MICRO_INELIGIBLE", "gross_income_cents exceeds the MICRO cap.")
        if prior_filings_count > MICRO_PRIOR_FILINGS_MAX:
            raise make_error("ERR_MICRO_INELIGIBLE", "prior_filings_count exceeds the MICRO cap.")


# ---------------------------------------------------------------------------
# Suspension check — every write operation by an Applicant must check this.
# ---------------------------------------------------------------------------
def _check_active_applicant(applicant: dict) -> None:
    if applicant["status"] != APPLICANT_STATUS_ACTIVE:
        raise make_error("ERR_APPLICANT_SUSPENDED")


# ---------------------------------------------------------------------------
# Application CRUD + transitions
# ---------------------------------------------------------------------------
def create_application(*, applicant_id: str, application_type: str, title: str,
                       claim_count: int, independent_claim_count: int,
                       parent_application_id: str | None,
                       continuation_type: str | None) -> dict:
    # Ownership: acting Applicant.id must equal applicant_id (priority 5)
    acting_role = getattr(g, "user_role", None)
    acting_id = getattr(g, "user_id", None)
    if acting_role == ROLE_APPLICANT and acting_id != applicant_id:
        raise make_error("ERR_FORBIDDEN", "Applicants may only create their own applications.")
    # Existence of applicant
    applicant = store.applicants.get(applicant_id)
    if applicant is None:
        raise make_error("ERR_NOT_FOUND", f"Applicant {applicant_id} not found.")

    # State/role business validations follow the priority chain:
    # priority 6 (state) — N/A here; the new row begins in DRAFT.
    # priority 7 (parent pending) — checked next.
    _validate_continuation_parent(parent_application_id, continuation_type)
    # priority 9 (claim shape)
    _validate_claim_shape(application_type, claim_count, independent_claim_count)
    # priority 15 (applicant active)
    _check_active_applicant(applicant)

    application = {
        **_common_create_fields(),
        "applicant_id": applicant_id,
        "application_type": application_type,
        "title": title,
        "claim_count": claim_count,
        "independent_claim_count": independent_claim_count,
        "status": APP_STATUS_DRAFT,
        "filed_at": None,
        "granted_at": None,
        "expires_at": None,
        "parent_application_id": parent_application_id,
        "continuation_type": continuation_type if continuation_type is not None else CONT_NONE,
        "total_fees_paid_cents": 0,
    }
    store.applications[application["id"]] = application
    _audit(application["id"], "APPLICATION_DRAFTED", {
        "application_type": application_type,
        "applicant_id": applicant_id,
    })
    return application


def update_application(application_id: str, *, title=None, claim_count=None,
                       independent_claim_count=None, version: int | None = None) -> dict:
    application = store.applications.get(application_id)
    if application is None:
        raise make_error("ERR_NOT_FOUND", f"Application {application_id} not found.")
    _check_ownership_application(application)
    # State precondition: only DRAFT is mutable
    if application["status"] != APP_STATUS_DRAFT:
        raise make_error("ERR_INVALID_STATE", "Application can only be edited while DRAFT.")
    # OCC
    if version is not None and version != application["version"]:
        raise make_error("ERR_VERSION_CONFLICT")
    # Claim shape on the prospective values
    new_claim = claim_count if claim_count is not None else application["claim_count"]
    new_indep = independent_claim_count if independent_claim_count is not None else application["independent_claim_count"]
    _validate_claim_shape(application["application_type"], new_claim, new_indep)
    # Applicant must be ACTIVE
    applicant = store.applicants.get(application["applicant_id"])
    if applicant is not None:
        _check_active_applicant(applicant)
    if title is not None:
        application["title"] = title
    if claim_count is not None:
        application["claim_count"] = claim_count
    if independent_claim_count is not None:
        application["independent_claim_count"] = independent_claim_count
    _bump(application)
    return application


# -------- Helpers used by Application validators --------
def _validate_claim_shape(application_type: str, claim_count: int, independent_claim_count: int) -> None:
    if application_type == APP_TYPE_PROVISIONAL:
        if claim_count != 0 or independent_claim_count != 0:
            raise make_error("ERR_CLAIM_SHAPE_INVALID",
                             "PROVISIONAL must have claim_count == 0 and independent_claim_count == 0.")
        return
    if application_type in (APP_TYPE_UTILITY, APP_TYPE_DESIGN):
        if claim_count is None or independent_claim_count is None:
            raise make_error("ERR_CLAIM_SHAPE_INVALID",
                             "claim_count and independent_claim_count are required.")
        if claim_count < 1 or independent_claim_count < 1:
            raise make_error("ERR_CLAIM_SHAPE_INVALID",
                             "UTILITY/DESIGN require claim_count >= 1 and independent_claim_count >= 1.")
        if independent_claim_count > claim_count:
            raise make_error("ERR_CLAIM_SHAPE_INVALID",
                             "independent_claim_count must not exceed claim_count.")


def _validate_continuation_parent(parent_application_id, continuation_type):
    """Validate the parent/continuation relationship at create time.

    Rules (SCAFFOLD §1.4 priority 7, PRD §3.2):
      - parent_application_id null => continuation_type must be None/NONE.
      - parent_application_id provided => parent exists, is not PROVISIONAL,
        status in {FILED, UNDER_EXAMINATION, OFFICE_ACTION_PENDING, ALLOWED,
        GRANTED}, and continuation_type in {CONTINUATION, CIP}.
    """
    if parent_application_id is None:
        if continuation_type is not None and continuation_type != CONT_NONE:
            raise make_error("ERR_PARENT_NOT_PENDING",
                             "continuation_type must be NONE when parent_application_id is null.")
        return
    parent = store.applications.get(parent_application_id)
    if parent is None:
        raise make_error("ERR_PARENT_NOT_PENDING", "Parent application not found.")
    if parent["application_type"] == APP_TYPE_PROVISIONAL:
        raise make_error("ERR_PARENT_NOT_PENDING", "Parent must not be PROVISIONAL.")
    if parent["status"] not in CONTINUATION_PARENT_OK_STATUSES:
        raise make_error("ERR_PARENT_NOT_PENDING",
                         f"Parent status {parent['status']} is not a continuation-eligible status.")
    if continuation_type not in (CONT_CONTINUATION, CONT_CIP):
        raise make_error("ERR_PARENT_NOT_PENDING",
                         "continuation_type must be CONTINUATION or CIP when parent is set.")


def _check_ownership_application(application: dict) -> None:
    """For Applicant role, verify ownership; other roles see across applicants."""
    role = getattr(g, "user_role", None)
    user_id = getattr(g, "user_id", None)
    if role == ROLE_APPLICANT and application["applicant_id"] != user_id:
        raise make_error("ERR_FORBIDDEN", "Application does not belong to acting applicant.")


def _check_ownership_via_application(application_id: str) -> None:
    application = store.applications.get(application_id)
    if application is None:
        raise make_error("ERR_NOT_FOUND", f"Application {application_id} not found.")
    _check_ownership_application(application)


# ---------------------------------------------------------------------------
# Fee transactions
# ---------------------------------------------------------------------------
def record_fee_transaction(*, application_id: str, fee_category: str,
                           amount_cents: int, maintenance_fee_id: str | None,
                           office_action_id: str | None) -> dict:
    application = store.applications.get(application_id)
    if application is None:
        raise make_error("ERR_NOT_FOUND", f"Application {application_id} not found.")
    _check_ownership_application(application)
    applicant = store.applicants[application["applicant_id"]]
    _check_active_applicant(applicant)

    # Validate enum + shape
    if fee_category not in FEE_CATEGORIES:
        raise make_error("ERR_VALIDATION", "Unknown fee_category.")
    if not isinstance(amount_cents, int) or isinstance(amount_cents, bool) or amount_cents < 0:
        raise make_error("ERR_VALIDATION", "amount_cents must be a non-negative integer.")

    # Fee-category appropriateness (priority 14):
    # MAINTENANCE may only be recorded by /maintenance-fees/{id}/pay (its
    # dedicated payment route still calls this function via FK linkage),
    # but on this endpoint we accept MAINTENANCE only with a maintenance_fee_id.
    # EXTENSION must be paired with an office_action_id pointing at this
    # application's OfficeAction. Other categories are accepted without FK.
    _validate_fee_category_and_fk(application_id, fee_category, maintenance_fee_id, office_action_id)

    # Fee amount must match the scaffold-computed amount per category & entity_size
    expected = _expected_fee_amount(
        application=application, applicant=applicant, fee_category=fee_category,
        maintenance_fee_id=maintenance_fee_id, office_action_id=office_action_id,
    )
    if amount_cents != expected:
        raise make_error(
            "ERR_FEE_AMOUNT_MISMATCH",
            f"Expected {expected} cents for {fee_category}; got {amount_cents}.",
        )

    ft = {
        "id": new_uuid(),
        "application_id": application_id,
        "fee_category": fee_category,
        "amount_cents": amount_cents,
        "paid_at": _now_iso(),
        "maintenance_fee_id": maintenance_fee_id,
        "office_action_id": office_action_id,
        "created_at": _now_iso(),
    }
    store.fee_transactions[ft["id"]] = ft
    # Recompute total
    _recompute_total_fees(application)
    return ft


def _validate_fee_category_and_fk(application_id, fee_category, maintenance_fee_id, office_action_id):
    if fee_category == FEE_CATEGORY_MAINTENANCE:
        if not maintenance_fee_id:
            raise make_error("ERR_FEE_CATEGORY_INVALID",
                             "MAINTENANCE fees require maintenance_fee_id.")
        mf = store.maintenance_fees.get(maintenance_fee_id)
        if mf is None or mf["application_id"] != application_id:
            raise make_error("ERR_FEE_CATEGORY_INVALID",
                             "maintenance_fee_id does not belong to this application.")
        return
    if fee_category == FEE_CATEGORY_EXTENSION:
        if not office_action_id:
            raise make_error("ERR_FEE_CATEGORY_INVALID",
                             "EXTENSION fees require office_action_id.")
        oa = store.office_actions.get(office_action_id)
        if oa is None or oa["application_id"] != application_id:
            raise make_error("ERR_FEE_CATEGORY_INVALID",
                             "office_action_id does not belong to this application.")
        return
    # For any other category, fk fields must be null
    if maintenance_fee_id is not None or office_action_id is not None:
        raise make_error("ERR_FEE_CATEGORY_INVALID",
                         "maintenance_fee_id/office_action_id only allowed for MAINTENANCE/EXTENSION fees.")


def _expected_fee_amount(*, application, applicant, fee_category, maintenance_fee_id, office_action_id):
    entity_size = applicant["entity_size"]
    if fee_category == FEE_CATEGORY_FILING:
        return calc_filing_fee(application["application_type"], entity_size)
    if fee_category == FEE_CATEGORY_EXCESS_CLAIM:
        return calc_excess_claim_fee(
            application["claim_count"], application["independent_claim_count"], entity_size,
        )
    if fee_category == FEE_CATEGORY_EXAMINATION:
        return calc_examination_fee(entity_size)
    if fee_category == FEE_CATEGORY_ISSUE:
        return calc_issue_fee(entity_size)
    if fee_category == FEE_CATEGORY_PCT_NATIONAL:
        return calc_pct_national_fee(entity_size)
    if fee_category == FEE_CATEGORY_PCT_TRANSMITTAL:
        # Not pinned by a calculation rule; treat as zero so any non-zero
        # amount fails the mismatch check. Tests are not expected to record
        # PCT_TRANSMITTAL.
        return 0
    if fee_category == FEE_CATEGORY_EXTENSION:
        oa = store.office_actions[office_action_id]
        deadline = parse_iso8601(oa["response_deadline_at"])
        months = extension_months(store.now(), deadline)
        if months == 0:
            return 0
        if months > 3:
            raise make_error("ERR_OFFICE_ACTION_DEADLINE_PASSED")
        return calc_extension_fee(months, entity_size)
    if fee_category == FEE_CATEGORY_MAINTENANCE:
        mf = store.maintenance_fees[maintenance_fee_id]
        due_at = parse_iso8601(mf["due_at"])
        grace_end = parse_iso8601(mf["grace_period_end_at"])
        return calc_maintenance_fee(
            mf["stage"], store.now(), due_at, grace_end, entity_size,
        )
    return 0


def _recompute_total_fees(application: dict) -> None:
    total = 0
    for t in store.fee_transactions.values():
        if t["application_id"] == application["id"]:
            total += t["amount_cents"]
    application["total_fees_paid_cents"] = total
    _bump(application)


# ---------------------------------------------------------------------------
# Application state transitions
# ---------------------------------------------------------------------------
def file_application(application_id: str) -> dict:
    application = store.applications.get(application_id)
    if application is None:
        raise make_error("ERR_NOT_FOUND", f"Application {application_id} not found.")
    _check_ownership_application(application)
    if application["status"] != APP_STATUS_DRAFT:
        raise make_error("ERR_INVALID_STATE", "Application must be in DRAFT to file.")

    # Continuation parent must still be pending at commit (priority 7)
    _validate_continuation_parent(
        application.get("parent_application_id"),
        application.get("continuation_type") if application.get("continuation_type") != CONT_NONE else None,
    )
    # Claim shape revalidate
    _validate_claim_shape(
        application["application_type"], application["claim_count"], application["independent_claim_count"],
    )
    # Applicant active
    applicant = store.applicants[application["applicant_id"]]
    _check_active_applicant(applicant)

    # Fee-amount precondition (priority 13): FILING transaction at expected amount;
    # plus EXCESS_CLAIM when threshold exceeded for UTILITY/DESIGN.
    expected_filing = calc_filing_fee(application["application_type"], applicant["entity_size"])
    has_filing = False
    has_excess = False
    expected_excess = 0
    if application["application_type"] in (APP_TYPE_UTILITY, APP_TYPE_DESIGN):
        if application["claim_count"] > 20 or application["independent_claim_count"] > 3:
            expected_excess = calc_excess_claim_fee(
                application["claim_count"], application["independent_claim_count"], applicant["entity_size"],
            )
    for t in store.fee_transactions.values():
        if t["application_id"] != application_id:
            continue
        if t["fee_category"] == FEE_CATEGORY_FILING and t["amount_cents"] == expected_filing:
            has_filing = True
        if t["fee_category"] == FEE_CATEGORY_EXCESS_CLAIM and t["amount_cents"] == expected_excess:
            has_excess = True
    if not has_filing:
        raise make_error(
            "ERR_FEE_AMOUNT_MISMATCH",
            f"FILING fee at {expected_filing} cents required to file.",
        )
    if expected_excess > 0 and not has_excess:
        raise make_error(
            "ERR_FEE_AMOUNT_MISMATCH",
            f"EXCESS_CLAIM fee at {expected_excess} cents required for claim counts above threshold.",
        )

    # Commit transition
    application["status"] = APP_STATUS_FILED
    application["filed_at"] = _now_iso()
    if application["application_type"] == APP_TYPE_PROVISIONAL:
        # PROVISIONAL expires at filed_at + 365 days
        forward = add_days(parse_iso8601(application["filed_at"]), 365)
        application["expires_at"] = iso_now(forward)
    _bump(application)
    _recompute_total_fees(application)  # also bumps version (cumulative)
    _audit(application_id, "APPLICATION_FILED", {
        "application_type": application["application_type"],
    })
    return application


def begin_examination(application_id: str) -> dict:
    application = store.applications.get(application_id)
    if application is None:
        raise make_error("ERR_NOT_FOUND", f"Application {application_id} not found.")
    if application["status"] != APP_STATUS_FILED:
        raise make_error("ERR_INVALID_STATE",
                         "Application must be FILED before examination can begin.")
    if application["application_type"] not in (APP_TYPE_UTILITY, APP_TYPE_DESIGN):
        raise make_error("ERR_INVALID_STATE",
                         "Only UTILITY/DESIGN applications can enter examination.")
    applicant = store.applicants[application["applicant_id"]]
    # Fee precondition: EXAMINATION fee at expected amount
    expected = calc_examination_fee(applicant["entity_size"])
    if not _has_fee(application_id, FEE_CATEGORY_EXAMINATION, expected):
        raise make_error(
            "ERR_FEE_AMOUNT_MISMATCH",
            f"EXAMINATION fee at {expected} cents required.",
        )
    application["status"] = APP_STATUS_UNDER_EXAMINATION
    _bump(application)
    _audit(application_id, "EXAMINATION_BEGUN", {})
    return application


def issue_office_action(application_id: str, *, action_type: str) -> dict:
    application = store.applications.get(application_id)
    if application is None:
        raise make_error("ERR_NOT_FOUND", f"Application {application_id} not found.")
    if application["status"] != APP_STATUS_UNDER_EXAMINATION:
        raise make_error("ERR_INVALID_STATE",
                         "Office Action requires UNDER_EXAMINATION.")
    if action_type not in OA_TYPES:
        raise make_error("ERR_VALIDATION", "action_type must be NON_FINAL or FINAL.")

    # Assign action_number = max existing + 1
    existing = [oa for oa in store.office_actions.values() if oa["application_id"] == application_id]
    action_number = max((oa["action_number"] for oa in existing), default=0) + 1

    issued_at_dt = store.now()
    oa = {
        **_common_create_fields(),
        "application_id": application_id,
        "action_number": action_number,
        "action_type": action_type,
        "issued_at": iso_now(issued_at_dt),
        "response_deadline_at": iso_now(add_days(issued_at_dt, OA_RESPONSE_DEADLINE_DAYS)),
        "extended_deadline_at": iso_now(add_days(issued_at_dt, OA_EXTENDED_DEADLINE_DAYS)),
        "status": OA_STATUS_PENDING,
    }
    store.office_actions[oa["id"]] = oa
    application["status"] = APP_STATUS_OFFICE_ACTION_PENDING
    _bump(application)
    _audit(application_id, "OFFICE_ACTION_ISSUED", {
        "office_action_id": oa["id"], "action_number": action_number, "action_type": action_type,
    })
    return oa


def file_response(office_action_id: str) -> dict:
    oa = store.office_actions.get(office_action_id)
    if oa is None:
        raise make_error("ERR_NOT_FOUND", f"OfficeAction {office_action_id} not found.")
    application = store.applications.get(oa["application_id"])
    if application is None:
        raise make_error("ERR_NOT_FOUND", "Owning application not found.")
    _check_ownership_application(application)
    # State precondition: OA must be PENDING and the application must be OFFICE_ACTION_PENDING
    if oa["status"] != OA_STATUS_PENDING:
        raise make_error("ERR_INVALID_STATE", "OfficeAction is not PENDING.")
    if application["status"] != APP_STATUS_OFFICE_ACTION_PENDING:
        raise make_error("ERR_INVALID_STATE", "Application is not OFFICE_ACTION_PENDING.")
    applicant = store.applicants[application["applicant_id"]]
    _check_active_applicant(applicant)
    # Temporal precondition: now <= extended_deadline_at
    extended_dt = parse_iso8601(oa["extended_deadline_at"])
    if store.now() > extended_dt:
        raise make_error("ERR_OFFICE_ACTION_DEADLINE_PASSED")
    # Fee precondition: if now > response_deadline_at, EXTENSION fee tied to this OA
    deadline_dt = parse_iso8601(oa["response_deadline_at"])
    months = extension_months(store.now(), deadline_dt)
    if months > 3:
        # Would be ineligible — but extended-deadline check above already
        # catches it. Defensive guard:
        raise make_error("ERR_OFFICE_ACTION_DEADLINE_PASSED")
    extension_amount = calc_extension_fee(months, applicant["entity_size"]) if months > 0 else 0
    if months > 0:
        if not _has_fee_with_oa(application["id"], FEE_CATEGORY_EXTENSION, extension_amount, office_action_id):
            raise make_error(
                "ERR_FEE_AMOUNT_MISMATCH",
                f"EXTENSION fee at {extension_amount} cents required for this OfficeAction.",
            )
    # Commit
    resp = {
        **_common_create_fields(),
        "office_action_id": office_action_id,
        "application_id": oa["application_id"],
        "filed_at": _now_iso(),
        "months_extension": months,
        "extension_fee_cents": extension_amount,
    }
    store.responses[resp["id"]] = resp
    oa["status"] = OA_STATUS_RESPONDED
    _bump(oa)
    application["status"] = APP_STATUS_UNDER_EXAMINATION
    _bump(application)
    _recompute_total_fees(application)
    _audit(application["id"], "OFFICE_ACTION_RESPONDED", {
        "office_action_id": office_action_id,
        "response_id": resp["id"],
        "months_extension": months,
    })
    return resp


def allow_application(application_id: str) -> dict:
    application = store.applications.get(application_id)
    if application is None:
        raise make_error("ERR_NOT_FOUND", f"Application {application_id} not found.")
    if application["status"] != APP_STATUS_UNDER_EXAMINATION:
        raise make_error("ERR_INVALID_STATE",
                         "Allowance requires UNDER_EXAMINATION.")
    # No OfficeAction in PENDING for this application
    for oa in store.office_actions.values():
        if oa["application_id"] == application_id and oa["status"] == OA_STATUS_PENDING:
            raise make_error("ERR_INVALID_STATE",
                             "Cannot allow while an OfficeAction is PENDING.")
    application["status"] = APP_STATUS_ALLOWED
    _bump(application)
    _audit(application_id, "APPLICATION_ALLOWED", {})
    return application


def grant_application(application_id: str) -> dict:
    application = store.applications.get(application_id)
    if application is None:
        raise make_error("ERR_NOT_FOUND", f"Application {application_id} not found.")
    if application["status"] != APP_STATUS_ALLOWED:
        raise make_error("ERR_INVALID_STATE", "Grant requires ALLOWED.")
    if application["application_type"] not in (APP_TYPE_UTILITY, APP_TYPE_DESIGN):
        raise make_error("ERR_INVALID_STATE", "Only UTILITY/DESIGN can be granted.")
    applicant = store.applicants[application["applicant_id"]]
    expected = calc_issue_fee(applicant["entity_size"])
    if not _has_fee(application_id, FEE_CATEGORY_ISSUE, expected):
        raise make_error(
            "ERR_FEE_AMOUNT_MISMATCH",
            f"ISSUE fee at {expected} cents required.",
        )

    granted_at_dt = store.now()
    application["status"] = APP_STATUS_GRANTED
    application["granted_at"] = iso_now(granted_at_dt)
    forward = compute_forward_expires_at(application)
    application["expires_at"] = iso_now(forward) if forward is not None else None
    _bump(application)

    if application["application_type"] == APP_TYPE_UTILITY:
        for stage in (MAINT_STAGE_3_5, MAINT_STAGE_7_5, MAINT_STAGE_11_5):
            anchor_years = STAGE_ANCHOR_YEARS[stage]
            window_open = add_years_as_days(granted_at_dt, anchor_years - 0.5)
            due = add_years_as_days(granted_at_dt, anchor_years)
            grace_end = add_days(due, MAINTENANCE_GRACE_PERIOD_DAYS)
            mf = {
                **_common_create_fields(),
                "application_id": application_id,
                "stage": stage,
                "window_open_at": iso_now(window_open),
                "due_at": iso_now(due),
                "grace_period_end_at": iso_now(grace_end),
                "status": MAINT_STATUS_SCHEDULED,
                "required_fee_cents": None,
            }
            store.maintenance_fees[mf["id"]] = mf
    _audit(application_id, "APPLICATION_GRANTED", {})
    return application


def abandon_application(application_id: str) -> dict:
    application = store.applications.get(application_id)
    if application is None:
        raise make_error("ERR_NOT_FOUND", f"Application {application_id} not found.")
    _check_ownership_application(application)
    if application["status"] not in VOLUNTARY_ABANDON_OK_STATUSES:
        raise make_error("ERR_INVALID_STATE",
                         "Application cannot be abandoned from its current status.")
    applicant = store.applicants[application["applicant_id"]]
    _check_active_applicant(applicant)

    application["status"] = APP_STATUS_ABANDONED
    _bump(application)
    # Cascade: PENDING OfficeActions -> ABANDONED_BY_DEFAULT
    for oa in store.office_actions.values():
        if oa["application_id"] == application_id and oa["status"] == OA_STATUS_PENDING:
            oa["status"] = OA_STATUS_ABANDONED_BY_DEFAULT
            _bump(oa)
    # Cascade: delete every SCHEDULED MaintenanceFee
    to_delete = [mf_id for mf_id, mf in store.maintenance_fees.items()
                 if mf["application_id"] == application_id and mf["status"] == MAINT_STATUS_SCHEDULED]
    for mf_id in to_delete:
        del store.maintenance_fees[mf_id]
    _audit(application_id, "APPLICATION_ABANDONED_VOLUNTARY", {})
    return application


# ---------------------------------------------------------------------------
# Maintenance fee payment
# ---------------------------------------------------------------------------
def pay_maintenance_fee(maintenance_fee_id: str) -> dict:
    mf = store.maintenance_fees.get(maintenance_fee_id)
    if mf is None:
        raise make_error("ERR_NOT_FOUND", f"MaintenanceFee {maintenance_fee_id} not found.")
    application = store.applications.get(mf["application_id"])
    if application is None:
        raise make_error("ERR_NOT_FOUND", "Owning application not found.")
    _check_ownership_application(application)
    if mf["status"] != MAINT_STATUS_SCHEDULED:
        raise make_error("ERR_INVALID_STATE", "MaintenanceFee is not SCHEDULED.")
    if application["status"] != APP_STATUS_GRANTED or application["application_type"] != APP_TYPE_UTILITY:
        raise make_error("ERR_MAINTENANCE_NOT_APPLICABLE",
                         "Maintenance fee applies only to GRANTED UTILITY applications.")
    applicant = store.applicants[application["applicant_id"]]
    _check_active_applicant(applicant)
    # Temporal check
    window_open_dt = parse_iso8601(mf["window_open_at"])
    grace_end_dt = parse_iso8601(mf["grace_period_end_at"])
    due_dt = parse_iso8601(mf["due_at"])
    now = store.now()
    if now < window_open_dt or now > grace_end_dt:
        raise make_error("ERR_MAINTENANCE_WINDOW_CLOSED")
    # Compute required amount
    expected = calc_maintenance_fee(mf["stage"], now, due_dt, grace_end_dt, applicant["entity_size"])
    # Need a MAINTENANCE FeeTransaction tied to this maintenance_fee_id at the expected amount
    matched = False
    for t in store.fee_transactions.values():
        if (t["application_id"] == application["id"]
                and t["fee_category"] == FEE_CATEGORY_MAINTENANCE
                and t.get("maintenance_fee_id") == maintenance_fee_id
                and t["amount_cents"] == expected):
            matched = True
            break
    if not matched:
        raise make_error(
            "ERR_FEE_AMOUNT_MISMATCH",
            f"MAINTENANCE fee at {expected} cents tied to this maintenance window required.",
        )
    # Commit
    mf["status"] = MAINT_STATUS_PAID
    mf["required_fee_cents"] = expected
    _bump(mf)
    _recompute_total_fees(application)
    _audit(application["id"], "MAINTENANCE_FEE_PAID", {
        "maintenance_fee_id": maintenance_fee_id, "stage": mf["stage"], "amount_cents": expected,
    })
    return mf


# ---------------------------------------------------------------------------
# PCT
# ---------------------------------------------------------------------------
def create_pct_phase(application_id: str) -> dict:
    application = store.applications.get(application_id)
    if application is None:
        raise make_error("ERR_NOT_FOUND", f"Application {application_id} not found.")
    _check_ownership_application(application)
    applicant = store.applicants[application["applicant_id"]]
    _check_active_applicant(applicant)
    # Eligibility: UTILITY and status in {FILED, UNDER_EXAMINATION, OFFICE_ACTION_PENDING}
    if (application["application_type"] != APP_TYPE_UTILITY
            or application["status"] not in PCT_INIT_OK_STATUSES):
        raise make_error("ERR_PCT_INELIGIBLE")
    pct_filed_dt = store.now()
    if not application.get("filed_at"):
        raise make_error("ERR_PCT_INELIGIBLE", "Owning application has no filed_at.")
    priority_dt = parse_iso8601(application["filed_at"])
    national_deadline = add_months_30d(priority_dt, PCT_NATIONAL_DEADLINE_MONTHS)
    pct = {
        **_common_create_fields(),
        "application_id": application_id,
        "pct_filed_at": iso_now(pct_filed_dt),
        "priority_date": iso_now(priority_dt),
        "national_phase_deadline_at": iso_now(national_deadline),
        "status": PCT_STATUS_INTERNATIONAL,
        "national_entered_at": None,
    }
    store.pct_phases[pct["id"]] = pct
    _audit(application_id, "PCT_INITIATED", {"pct_id": pct["id"]})
    return pct


def enter_national_phase(pct_id: str) -> dict:
    pct = store.pct_phases.get(pct_id)
    if pct is None:
        raise make_error("ERR_NOT_FOUND", f"PCTPhase {pct_id} not found.")
    application = store.applications.get(pct["application_id"])
    if application is None:
        raise make_error("ERR_NOT_FOUND", "Owning application not found.")
    _check_ownership_application(application)
    if pct["status"] != PCT_STATUS_INTERNATIONAL:
        raise make_error("ERR_INVALID_STATE", "PCTPhase is not INTERNATIONAL.")
    applicant = store.applicants[application["applicant_id"]]
    _check_active_applicant(applicant)
    deadline_dt = parse_iso8601(pct["national_phase_deadline_at"])
    if store.now() > deadline_dt:
        raise make_error("ERR_PCT_DEADLINE_PASSED")
    expected = calc_pct_national_fee(applicant["entity_size"])
    if not _has_fee(application["id"], FEE_CATEGORY_PCT_NATIONAL, expected):
        raise make_error(
            "ERR_FEE_AMOUNT_MISMATCH",
            f"PCT_NATIONAL fee at {expected} cents required.",
        )
    pct["status"] = PCT_STATUS_NATIONAL_ENTERED
    pct["national_entered_at"] = _now_iso()
    _bump(pct)
    _audit(application["id"], "PCT_NATIONAL_ENTERED", {"pct_id": pct_id})
    return pct


# ---------------------------------------------------------------------------
# Clock advance + sweep
# ---------------------------------------------------------------------------
def advance_clock(to_iso: str) -> dict:
    new_now = parse_iso8601(to_iso)
    # Clock may only move forward (PRD §2.8). Allow equal as a no-op.
    if new_now < store.now():
        raise make_error("ERR_VALIDATION", "SystemClock may only move forward.")
    store.set_clock(new_now)
    _run_sweep()
    return {"now": iso_now(store.now())}


def _run_sweep() -> None:
    """Deterministic deadline sweep (PRD §2.8).

    Order:
      1. Office Actions past extended_deadline_at -> ABANDONED_BY_DEFAULT; cascade Application -> ABANDONED.
      2. Maintenance Fees past grace_period_end_at -> LAPSED; cascade Application -> EXPIRED.
      3. PCT Phases past national_phase_deadline_at -> LAPSED.
      4. Granted Applications whose forward_expires_at <= now -> EXPIRED.
    """
    now = store.now()
    # 1. Office Actions
    for oa in list(store.office_actions.values()):
        if oa["status"] != OA_STATUS_PENDING:
            continue
        extended_dt = parse_iso8601(oa["extended_deadline_at"])
        if now > extended_dt:
            oa["status"] = OA_STATUS_ABANDONED_BY_DEFAULT
            _bump(oa)
            application = store.applications.get(oa["application_id"])
            if application is not None and application["status"] == APP_STATUS_OFFICE_ACTION_PENDING:
                application["status"] = APP_STATUS_ABANDONED
                _bump(application)
                _audit(application["id"], "APPLICATION_ABANDONED_DEADLINE",
                       {"office_action_id": oa["id"]})
    # 2. Maintenance Fees
    lapsed_apps: set[str] = set()
    for mf in list(store.maintenance_fees.values()):
        if mf["status"] != MAINT_STATUS_SCHEDULED:
            continue
        # If a qualifying payment already exists with the matching FK we skip lapse.
        already_paid_match = False
        for t in store.fee_transactions.values():
            if t["fee_category"] == FEE_CATEGORY_MAINTENANCE and t.get("maintenance_fee_id") == mf["id"]:
                already_paid_match = True
                break
        if already_paid_match:
            continue
        grace_end_dt = parse_iso8601(mf["grace_period_end_at"])
        if now > grace_end_dt:
            mf["status"] = MAINT_STATUS_LAPSED
            _bump(mf)
            _audit(mf["application_id"], "MAINTENANCE_FEE_LAPSED",
                   {"maintenance_fee_id": mf["id"], "stage": mf["stage"]})
            application = store.applications.get(mf["application_id"])
            if application is not None and application["status"] == APP_STATUS_GRANTED:
                application["status"] = APP_STATUS_EXPIRED
                _bump(application)
                _audit(application["id"], "APPLICATION_EXPIRED",
                       {"reason": "maintenance_lapsed", "maintenance_fee_id": mf["id"]})
            lapsed_apps.add(mf["application_id"])
    # PRD §3.4: when at least one MaintenanceFee for the application has
    # LAPSED, the effective expires_at is the earliest grace_period_end_at
    # among the lapsed rows (necessarily earlier than the forward term).
    for application_id in lapsed_apps:
        application = store.applications.get(application_id)
        if application is None:
            continue
        earliest_lapsed_iso = None
        earliest_lapsed_dt = None
        for mf2 in store.maintenance_fees.values():
            if mf2["application_id"] != application_id:
                continue
            if mf2["status"] != MAINT_STATUS_LAPSED:
                continue
            mf2_dt = parse_iso8601(mf2["grace_period_end_at"])
            if earliest_lapsed_dt is None or mf2_dt < earliest_lapsed_dt:
                earliest_lapsed_dt = mf2_dt
                earliest_lapsed_iso = mf2["grace_period_end_at"]
        if earliest_lapsed_iso is not None:
            application["expires_at"] = earliest_lapsed_iso
    # 3. PCT Phases
    for pct in list(store.pct_phases.values()):
        if pct["status"] != PCT_STATUS_INTERNATIONAL:
            continue
        deadline_dt = parse_iso8601(pct["national_phase_deadline_at"])
        if now > deadline_dt:
            pct["status"] = PCT_STATUS_LAPSED
            _bump(pct)
            _audit(pct["application_id"], "PCT_LAPSED", {"pct_id": pct["id"]})
    # 4. Statutory expiration for GRANTED applications
    for application in list(store.applications.values()):
        if application["status"] != APP_STATUS_GRANTED:
            continue
        forward = compute_forward_expires_at(application)
        if forward is not None and now >= forward:
            application["status"] = APP_STATUS_EXPIRED
            _bump(application)
            _audit(application["id"], "APPLICATION_EXPIRED", {"reason": "term_reached"})
    # PROVISIONAL applications also expire at filed_at + 365 days while still FILED.
    for application in list(store.applications.values()):
        if (application["status"] == APP_STATUS_FILED
                and application["application_type"] == APP_TYPE_PROVISIONAL
                and application.get("expires_at")):
            forward = parse_iso8601(application["expires_at"])
            if now >= forward:
                application["status"] = APP_STATUS_EXPIRED
                _bump(application)
                _audit(application["id"], "APPLICATION_EXPIRED", {"reason": "provisional_term"})


# ---------------------------------------------------------------------------
# Fee lookup helpers
# ---------------------------------------------------------------------------
def _has_fee(application_id: str, category: str, expected_amount: int) -> bool:
    for t in store.fee_transactions.values():
        if (t["application_id"] == application_id
                and t["fee_category"] == category
                and t["amount_cents"] == expected_amount):
            return True
    return False


def _has_fee_with_oa(application_id: str, category: str, expected_amount: int, oa_id: str) -> bool:
    for t in store.fee_transactions.values():
        if (t["application_id"] == application_id
                and t["fee_category"] == category
                and t["amount_cents"] == expected_amount
                and t.get("office_action_id") == oa_id):
            return True
    return False
