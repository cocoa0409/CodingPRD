"""Amended returns: drafting, preparation arithmetic, signature, transmission,
agency disposition and voiding (PRD 3.4, 3.5)."""

from datetime import timedelta

from flask import Blueprint

import calc
from common import (
    F, R_ADMIN, R_OFFICER, R_PREPARER, READ6,
    authenticate, db, fail, get_amended_return, get_case, get_body, matches, new_row,
    now, ok, pagination, paginate, period_ordinal, qs, require_state, sorted_rows,
    touch, validate, whole_days,
)
from serializers import amended_return_json

bp = Blueprint("amendments", __name__)

TERMINAL = ("ACCEPTED", "VOID")

AMENDMENT_CREATE = {
    "correction_case_id": F("string", True),
    "form_code": F("string", True, min_len=1, max_len=16),
    "accrual_through_date": F("datetime", True),
    "expected_correction_case_version": F("integer", True),
    "supersedes_amended_return_id": F("string", False),
}


def _case_of(amendment):
    return db.correction_cases.get(amendment["correction_case_id"])


def _amendment_employer(amendment):
    case = _case_of(amendment)
    return case["employer_id"] if case else None


@bp.post("/amended-returns")
def create_amendment():
    authenticate((R_ADMIN, R_PREPARER))
    body = get_body()
    case = None
    if isinstance(body.get("correction_case_id"), str) and body["correction_case_id"]:
        case = get_case(body["correction_case_id"])
    if isinstance(body.get("supersedes_amended_return_id"), str) and body["supersedes_amended_return_id"]:
        get_amended_return(body["supersedes_amended_return_id"])
    data = validate(body, AMENDMENT_CREATE)

    if data["expected_correction_case_version"] != case["version"]:
        fail("ERR_STALE_CASE_VERSION",
             "expected_correction_case_version does not match the case's current version")

    if not calc.case_discrepancies(case["id"]):
        fail("ERR_CASE_HAS_NO_DISCREPANCIES",
             "the case has no discrepancies to amend")

    for other in calc.case_amendments(case["id"]):
        if other["form_code"] == data["form_code"] and other["status"] in calc.LIVE_AMENDMENT_STATES:
            fail("ERR_AMENDMENT_SLOT_OCCUPIED",
                 "a live amendment already occupies this case and form_code slot")

    row = new_row({
        "correction_case_id": case["id"],
        "supersedes_amended_return_id": data.get("supersedes_amended_return_id"),
        "form_code": data["form_code"],
        "prepared_by_user_id": None,
        "signed_by_user_id": None,
        "accrual_through_date": data["accrual_through_date"],
        "wage_delta_cents": 0,
        "tax_delta_cents": 0,
        "deposit_shortfall_cents": 0,
        "days_late": 0,
        "interest_variant": None,
        "interest_cents": 0,
        "penalty_cents": 0,
        "voluntary_reduction_applied": False,
        "status": "DRAFT",
        "submitted_at": None,
        "accepted_at": None,
        "rejection_reason": None,
        "void_reason": None,
    })
    db.amended_returns[row["id"]] = row
    calc.sync_case(case, forced=True)
    calc.sync_employer(db.employers.get(case["employer_id"]))
    return ok(amended_return_json(row), 201)


@bp.get("/amended-returns/<amended_return_id>")
def read_amendment(amended_return_id):
    actor = authenticate(READ6)
    row = get_amended_return(amended_return_id)
    actor.require_employer(_amendment_employer(row))
    return ok(amended_return_json(row))


@bp.get("/amended-returns")
def list_amendments():
    actor = authenticate(READ6)
    limit, offset = pagination()
    filters = {
        "correction_case_id": qs("correction_case_id"),
        "supersedes_amended_return_id": qs("supersedes_amended_return_id"),
        "form_code": qs("form_code"),
        "status": qs("status"),
        "interest_variant": qs("interest_variant"),
    }
    rows = [r for r in sorted_rows(db.amended_returns.values()) if matches(r, filters)]
    if actor.role == "EmployerRep":
        rows = [r for r in rows if _amendment_employer(r) == actor.user_id]
    return paginate(rows, limit, offset, amended_return_json)


def _registration_covers(case, agency):
    if not agency.get("requires_registration"):
        return True
    ordinal = period_ordinal(case["tax_year"], case["quarter"])
    for acc in db.agency_accounts.values():
        if acc["employer_id"] != case["employer_id"] or acc["agency_id"] != case["agency_id"]:
            continue
        if acc["registration_status"] not in calc.ACTIVE_ACCOUNT_STATES:
            continue
        if acc["from_period_ordinal"] <= ordinal <= acc["to_period_ordinal"]:
            return True
    return False


@bp.post("/amended-returns/<amended_return_id>/prepare")
def prepare_amendment(amended_return_id):
    actor = authenticate((R_ADMIN, R_PREPARER))
    amendment = get_amended_return(amended_return_id)
    body = get_body()
    data = validate(body, {"accrual_through_date": F("datetime", False)})
    case = _case_of(amendment)
    employer = db.employers.get(case["employer_id"]) if case else None
    agency = db.tax_agencies.get(case["agency_id"]) if case else None

    require_state(amendment["status"], ("DRAFT", "SIGNED", "AGENCY_REJECTED"), TERMINAL)

    if amendment["status"] == "SIGNED":
        # Recall the signature: SIGNED -> DRAFT with all figures cleared first.
        amendment["signed_by_user_id"] = None
        amendment["status"] = "DRAFT"
        for field in ("wage_delta_cents", "tax_delta_cents", "deposit_shortfall_cents",
                      "interest_cents", "penalty_cents"):
            amendment[field] = 0
        touch(amendment)
        calc.sync_case(case)
        calc.sync_employer(employer)
        return ok(amended_return_json(amendment))

    if amendment["status"] == "AGENCY_REJECTED":
        amendment["signed_by_user_id"] = None
        amendment["submitted_at"] = None
        amendment["rejection_reason"] = None
        amendment["status"] = "DRAFT"
        touch(amendment)
        return ok(amended_return_json(amendment))

    # DRAFT -> PREPARED: the four gates, then all the arithmetic.
    discrepancies = calc.case_discrepancies(case["id"])
    open_count = sum(1 for d in discrepancies if d["status"] == "OPEN")
    categorized = sum(1 for d in discrepancies if d["status"] == "CATEGORIZED")
    if open_count != 0 or categorized == 0:
        fail("ERR_UNCATEGORIZED_DISCREPANCIES",
             "every discrepancy must be triaged and at least one categorised")

    if not _registration_covers(case, agency):
        fail("ERR_AGENCY_ACCOUNT_NOT_ACTIVE",
             "no active registration covers the case period for this agency")

    accrual_through = data.get("accrual_through_date") or amendment["accrual_through_date"]
    filed = calc.case_filed_return(case)
    original_due_date = filed["original_due_date"] if filed else None
    if original_due_date is None or accrual_through < original_due_date or accrual_through > now():
        fail("ERR_INVALID_ACCRUAL_DATE",
             "accrual_through_date must fall between the original due date and now")

    rollup = calc.delta_rollup(case, accrual_through, original_due_date)
    variant, interest = calc.compute_interest(case, agency, rollup["tax_delta_cents"],
                                              rollup["days_late"], accrual_through)
    penalty, voluntary = calc.compute_penalty(case, agency, rollup["tax_delta_cents"],
                                              rollup["deposit_shortfall_cents"],
                                              rollup["days_late"])

    amendment["accrual_through_date"] = accrual_through
    amendment.update(rollup)
    amendment["interest_variant"] = variant
    amendment["interest_cents"] = interest
    amendment["penalty_cents"] = penalty
    amendment["voluntary_reduction_applied"] = voluntary
    amendment["prepared_by_user_id"] = actor.user_id
    amendment["status"] = "PREPARED"
    touch(amendment)

    filing_moved = False
    if case["filing_status"] == "FILING_PENDING":
        case["filing_status"] = "FILING_IN_PROGRESS"
        filing_moved = True
    calc.sync_case(case, forced=filing_moved)
    calc.sync_employer(employer)
    return ok(amended_return_json(amendment))


@bp.post("/amended-returns/<amended_return_id>/sign")
def sign_amendment(amended_return_id):
    actor = authenticate((R_ADMIN, R_OFFICER))
    amendment = get_amended_return(amended_return_id)
    get_body()
    case = _case_of(amendment)
    employer = db.employers.get(case["employer_id"]) if case else None

    require_state(amendment["status"], ("PREPARED",), TERMINAL)

    if actor.user_id == amendment["prepared_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES_VIOLATION",
             "the signer may not be the preparer")
    if employer is not None and case["total_exposure_cents"] > employer["authorization_limit_cents"]:
        fail("ERR_AUTHORIZATION_LIMIT_EXCEEDED",
             "case exposure exceeds the employer's authorization limit")

    amendment["signed_by_user_id"] = actor.user_id
    amendment["status"] = "SIGNED"
    touch(amendment)
    return ok(amended_return_json(amendment))


@bp.post("/amended-returns/<amended_return_id>/submit")
def submit_amendment(amended_return_id):
    authenticate((R_ADMIN, R_OFFICER))
    amendment = get_amended_return(amended_return_id)
    get_body()
    case = _case_of(amendment)
    agency = db.tax_agencies.get(case["agency_id"]) if case else None

    if amendment["status"] in TERMINAL:
        fail("ERR_ALREADY_TERMINAL", "amendment is already in a terminal state")
    if amendment["status"] != "SIGNED":
        fail("ERR_AMENDED_RETURN_NOT_SIGNED", "transmission requires a SIGNED amendment")

    filed = calc.case_filed_return(case)
    if filed is not None and agency is not None:
        boundary = filed["original_due_date"] + timedelta(days=agency["amendment_window_days"])
        if now() > boundary:
            fail("ERR_AMENDMENT_WINDOW_CLOSED", "the amendment window has closed")

    previous = []
    for other in db.amended_returns.values():
        if other["id"] == amendment["id"]:
            continue
        if other["status"] not in ("SUBMITTED", "ACCEPTED", "AGENCY_REJECTED"):
            continue
        if other["submitted_at"] is None:
            continue
        other_case = _case_of(other)
        if other_case is None:
            continue
        if (other_case["employer_id"] == case["employer_id"]
                and other_case["agency_id"] == case["agency_id"]
                and other_case["tax_year"] == case["tax_year"]
                and other_case["quarter"] == case["quarter"]):
            previous.append(other)
    if previous and agency is not None:
        latest = max(previous, key=lambda a: (a["submitted_at"], a["_seq"]))
        if whole_days(latest["submitted_at"], now()) < agency["min_days_between_amendments"]:
            fail("ERR_AMENDMENT_COOLING_OFF_ACTIVE",
                 "the cooling-off buffer since the previous transmission has not elapsed")

    amendment["status"] = "SUBMITTED"
    amendment["submitted_at"] = now()
    touch(amendment)
    return ok(amended_return_json(amendment))


@bp.post("/amended-returns/<amended_return_id>/agency-outcome")
def amendment_outcome(amended_return_id):
    authenticate((R_ADMIN, R_OFFICER))
    amendment = get_amended_return(amended_return_id)
    body = get_body()
    data = validate(body, {
        "outcome": F("string", True, enum=("ACCEPTED", "REJECTED")),
        "rejection_reason": F("string", False, min_len=1, max_len=2000),
    })
    if data["outcome"] == "REJECTED" and "rejection_reason" not in data:
        fail("ERR_INVALID_REQUEST", "rejection_reason is required when rejecting")

    case = _case_of(amendment)
    employer = db.employers.get(case["employer_id"]) if case else None
    require_state(amendment["status"], ("SUBMITTED",), TERMINAL)

    if data["outcome"] == "REJECTED":
        amendment["status"] = "AGENCY_REJECTED"
        amendment["rejection_reason"] = data["rejection_reason"]
        touch(amendment)
        return ok(amended_return_json(amendment))

    # Link one
    amendment["status"] = "ACCEPTED"
    amendment["accepted_at"] = now()
    touch(amendment)
    for ret in calc.case_filed_returns(case):
        if ret["status"] == "FILED":
            ret["status"] = "AMENDED"
            touch(ret)
    # Link two
    for row in calc.case_discrepancies(case["id"]):
        if row["status"] == "CATEGORIZED":
            row["status"] = "RESOLVED"
            row["resolved_amended_return_id"] = amendment["id"]
            row["resolved_amount_cents"] = row["amount_cents"]
            touch(row)
    # Links three and four
    filing_moved = calc.advance_filing_after_discrepancy_change(case)
    calc.sync_case(case, forced=filing_moved)
    # Link five
    calc.sync_employer(employer)
    return ok(amended_return_json(amendment))


@bp.post("/amended-returns/<amended_return_id>/void")
def void_amendment(amended_return_id):
    authenticate((R_ADMIN, R_OFFICER))
    amendment = get_amended_return(amended_return_id)
    body = get_body()
    data = validate(body, {"void_reason": F("string", True, min_len=1, max_len=2000)})
    case = _case_of(amendment)
    employer = db.employers.get(case["employer_id"]) if case else None

    require_state(amendment["status"], ("DRAFT", "PREPARED", "AGENCY_REJECTED"), TERMINAL)
    origin = amendment["status"]

    amendment["status"] = "VOID"
    amendment["void_reason"] = data["void_reason"]
    touch(amendment)

    if origin == "DRAFT":
        return ok(amended_return_json(amendment))

    if origin == "PREPARED":
        for row in calc.case_discrepancies(case["id"]):
            if row["resolved_amended_return_id"] == amendment["id"] and row["status"] == "RESOLVED":
                row["status"] = "CATEGORIZED"
                row["resolved_amended_return_id"] = None
                row["resolved_amount_cents"] = None
                touch(row)
        filing_reverted = False
        if case["filing_status"] == "FILING_IN_PROGRESS":
            blocking = [a for a in calc.case_amendments(case["id"])
                        if a["id"] != amendment["id"]
                        and a["status"] in ("PREPARED", "SIGNED", "SUBMITTED", "ACCEPTED")]
            if not blocking:
                case["filing_status"] = "FILING_PENDING"
                filing_reverted = True
        calc.sync_case(case, forced=filing_reverted)
        calc.sync_employer(employer)
        return ok(amended_return_json(amendment))

    # AGENCY_REJECTED -> VOID
    calc.sync_case(case)
    calc.sync_employer(employer)
    return ok(amended_return_json(amendment))
