"""Secret shopper tests, violation cases and corrective action plans."""
from decimal import Decimal

from flask import Blueprint, g

from db import (
    CERT_SUSPENSION_SCORE_THRESHOLD,
    MAX_REVISION_ROUNDS,
    db,
    new_row,
    now,
    now_str,
    sort_key,
    touch,
)
from errors import ApiError
from middleware import (
    COMPLIANCE_OFFICER,
    PARTNER_MANAGER,
    PLATFORM_ADMIN,
    SECRET_SHOPPER_AUDITOR,
    auth,
    fetch,
    scope_check,
    scope_if,
    segregation_of_duties,
)
from response import created, listing, ok, pagination, public
from services.parties import (
    case_rolling_contribution,
    open_case,
    recompute_courier_score,
    refresh_partner,
)
from util import parse_dt
import validate as v

bp = Blueprint("compliance", __name__)

ZERO2 = Decimal("0.00")
SCENARIO_TYPES = ("UNDERAGE_PRESENTER", "NO_ID_PRESENTED", "EXPIRED_DOCUMENT", "INTOXICATION_CUES")
OUTCOMES = ("REFUSAL", "HANDOVER")
VERDICTS = ("PENDING", "PASS", "FAIL")
SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")
CASE_STATES = (
    "OPEN",
    "UNDER_INVESTIGATION",
    "PENDING_PARTNER_RESPONSE",
    "SUBSTANTIATED",
    "DISMISSED",
    "CLOSED_VERIFIED",
)
CASE_ORIGINS = ("AUTO_REFUSAL", "AUTO_SHOPPER_FAIL", "MANUAL")
PLAN_STATES = (
    "SUBMITTED",
    "ACCEPTED",
    "REVISION_REQUESTED",
    "VERIFIED",
    "FAILED_VERIFICATION",
    "SUPERSEDED",
)
NON_TERMINAL_PLAN_STATES = ("SUBMITTED", "ACCEPTED", "REVISION_REQUESTED", "FAILED_VERIFICATION")


def _plans_of(case_id):
    rows = [p for p in db.plans.values() if p["violation_case_id"] == case_id]
    rows.sort(key=sort_key)
    return rows


# ---------------------------------------------------------------------------
# Secret shopper tests
# ---------------------------------------------------------------------------
@bp.post("/secret-shopper-tests")
def schedule_test():
    auth(SECRET_SHOPPER_AUDITOR)
    body = v.body()
    courier_id = body.get("courier_id")
    if not isinstance(courier_id, str) or courier_id.strip() == "":
        raise ApiError("ERR_VALIDATION", "courier_id is required")
    fetch("couriers", courier_id)
    order_id = body.get("order_id")
    if not isinstance(order_id, str) or order_id.strip() == "":
        raise ApiError("ERR_VALIDATION", "order_id is required")
    fetch("orders", order_id)
    scenario_type = v.req_enum(body, "scenario_type", SCENARIO_TYPES)
    _scheduled, scheduled_raw = v.req_dt(body, "scheduled_at")
    expected_outcome = v.req_enum(body, "expected_outcome", OUTCOMES)
    row = new_row(
        courier_id=courier_id,
        order_id=order_id,
        scenario_type=scenario_type,
        scheduled_at=scheduled_raw,
        expected_outcome=expected_outcome,
        observed_outcome=None,
        findings=None,
        verdict="PENDING",
        recorded_at=None,
    )
    db.shopper_tests[row["id"]] = row
    return created(public(row))


@bp.get("/secret-shopper-tests/<test_id>")
def get_test(test_id):
    auth(PLATFORM_ADMIN, COMPLIANCE_OFFICER, SECRET_SHOPPER_AUDITOR)
    return ok(public(fetch("shopper_tests", test_id)))


@bp.get("/secret-shopper-tests")
def list_tests():
    auth(PLATFORM_ADMIN, COMPLIANCE_OFFICER, SECRET_SHOPPER_AUDITOR)
    courier_filter = v.str_filter("courier_id")
    order_filter = v.str_filter("order_id")
    verdict = v.enum_filter("verdict", VERDICTS)
    scenario_type = v.enum_filter("scenario_type", SCENARIO_TYPES)
    limit, offset = pagination()
    rows = list(db.shopper_tests.values())
    if courier_filter is not None:
        rows = [r for r in rows if r["courier_id"] == courier_filter]
    if order_filter is not None:
        rows = [r for r in rows if r["order_id"] == order_filter]
    if verdict is not None:
        rows = [r for r in rows if r["verdict"] == verdict]
    if scenario_type is not None:
        rows = [r for r in rows if r["scenario_type"] == scenario_type]
    rows.sort(key=sort_key)
    return listing(rows, limit, offset)


@bp.post("/secret-shopper-tests/<test_id>/record-outcome")
def record_outcome(test_id):
    auth(SECRET_SHOPPER_AUDITOR)
    test = fetch("shopper_tests", test_id)
    body = v.body()
    observed_outcome = v.req_enum(body, "observed_outcome", OUTCOMES)
    findings = v.opt_str(body, "findings")

    test["observed_outcome"] = observed_outcome
    test["findings"] = findings
    test["verdict"] = "PASS" if observed_outcome == test["expected_outcome"] else "FAIL"
    test["recorded_at"] = now_str()
    touch(test)

    courier = db.couriers.get(test["courier_id"])
    if test["verdict"] == "FAIL":
        partner_id = courier["delivery_partner_id"] if courier is not None else None
        if partner_id is not None:
            open_case(
                partner_id=partner_id,
                severity="MAJOR",
                summary="Auto-opened from failed secret shopper test (%s)" % test["scenario_type"],
                origin="AUTO_SHOPPER_FAIL",
                secret_shopper_test_id=test["id"],
            )
            partner = db.partners.get(partner_id)
            if partner is not None:
                refresh_partner(partner)
    if courier is not None:
        recompute_courier_score(courier)
    return ok(public(test))


# ---------------------------------------------------------------------------
# Violation cases
# ---------------------------------------------------------------------------
@bp.post("/violation-cases")
def create_case():
    auth(COMPLIANCE_OFFICER)
    body = v.body()
    partner_id = body.get("delivery_partner_id")
    if not isinstance(partner_id, str) or partner_id.strip() == "":
        raise ApiError("ERR_VALIDATION", "delivery_partner_id is required")
    partner = fetch("partners", partner_id)
    attempt_id = body.get("delivery_attempt_id")
    if attempt_id is not None:
        if not isinstance(attempt_id, str) or attempt_id.strip() == "":
            raise ApiError("ERR_VALIDATION", "delivery_attempt_id must be a string")
        fetch("attempts", attempt_id)
    test_id = body.get("secret_shopper_test_id")
    if test_id is not None:
        if not isinstance(test_id, str) or test_id.strip() == "":
            raise ApiError("ERR_VALIDATION", "secret_shopper_test_id must be a string")
        fetch("shopper_tests", test_id)
    severity = v.req_enum(body, "severity", SEVERITIES)
    summary = v.req_str(body, "summary")

    # tier 19 -- exactly one subject
    if (attempt_id is None) == (test_id is None):
        raise ApiError("ERR_CASE_SUBJECT_INVALID")

    case = open_case(
        partner_id=partner_id,
        severity=severity,
        summary=summary,
        origin="MANUAL",
        delivery_attempt_id=attempt_id,
        secret_shopper_test_id=test_id,
    )
    refresh_partner(partner)
    return created(public(case))


@bp.get("/violation-cases/<case_id>")
def get_case(case_id):
    auth(PLATFORM_ADMIN, COMPLIANCE_OFFICER, PARTNER_MANAGER)
    case = fetch("cases", case_id)
    scope_if(PARTNER_MANAGER, case["delivery_partner_id"])
    return ok(public(case))


@bp.get("/violation-cases")
def list_cases():
    user_id, role = auth(PLATFORM_ADMIN, COMPLIANCE_OFFICER, PARTNER_MANAGER)
    partner_filter = v.str_filter("delivery_partner_id")
    attempt_filter = v.str_filter("delivery_attempt_id")
    test_filter = v.str_filter("secret_shopper_test_id")
    state = v.enum_filter("state", CASE_STATES)
    severity = v.enum_filter("severity", SEVERITIES)
    origin = v.enum_filter("origin", CASE_ORIGINS)
    limit, offset = pagination()
    if role == PARTNER_MANAGER:
        if partner_filter is not None and partner_filter != user_id:
            raise ApiError("ERR_FORBIDDEN_RESOURCE_SCOPE")
        partner_filter = user_id
    rows = list(db.cases.values())
    if partner_filter is not None:
        rows = [r for r in rows if r["delivery_partner_id"] == partner_filter]
    if attempt_filter is not None:
        rows = [r for r in rows if r.get("delivery_attempt_id") == attempt_filter]
    if test_filter is not None:
        rows = [r for r in rows if r.get("secret_shopper_test_id") == test_filter]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    if severity is not None:
        rows = [r for r in rows if r["severity"] == severity]
    if origin is not None:
        rows = [r for r in rows if r["origin"] == origin]
    rows.sort(key=sort_key)
    return listing(rows, limit, offset)


@bp.post("/violation-cases/<case_id>/investigate")
def investigate_case(case_id):
    auth(COMPLIANCE_OFFICER)
    case = fetch("cases", case_id)
    if case["state"] != "OPEN":
        raise ApiError("ERR_INVALID_CASE_STATE")
    case["state"] = "UNDER_INVESTIGATION"
    case["investigation_rounds"] += 1
    touch(case)
    return ok(public(case))


@bp.post("/violation-cases/<case_id>/request-partner-response")
def request_partner_response(case_id):
    auth(COMPLIANCE_OFFICER)
    case = fetch("cases", case_id)
    body = v.body()
    response_due_at, response_due_raw = v.req_dt(body, "response_due_at")
    notes = v.opt_str(body, "notes")
    if case["state"] != "UNDER_INVESTIGATION":
        raise ApiError("ERR_INVALID_CASE_STATE")
    if response_due_at <= now():
        raise ApiError("ERR_RESPONSE_DUE_NOT_FUTURE")
    case["state"] = "PENDING_PARTNER_RESPONSE"
    case["response_due_at"] = response_due_raw
    if notes is not None:
        case["notes"] = notes
    touch(case)
    return ok(public(case))


@bp.post("/violation-cases/<case_id>/partner-response")
def partner_response(case_id):
    auth(PARTNER_MANAGER)
    case = fetch("cases", case_id)
    scope_check(case["delivery_partner_id"])
    body = v.body()
    text = v.req_str(body, "partner_response_text")
    if case["state"] != "PENDING_PARTNER_RESPONSE":
        raise ApiError("ERR_INVALID_CASE_STATE")
    case["state"] = "UNDER_INVESTIGATION"
    case["partner_response_text"] = text
    case["investigation_rounds"] += 1
    touch(case)
    return ok(public(case))


def _courier_of_case(case):
    attempt_id = case.get("delivery_attempt_id")
    if not attempt_id:
        return None
    attempt = db.attempts.get(attempt_id)
    if attempt is None:
        return None
    return db.couriers.get(attempt["courier_id"])


@bp.post("/violation-cases/<case_id>/decide")
def decide_case(case_id):
    user_id, _role = auth(COMPLIANCE_OFFICER)
    case = fetch("cases", case_id)
    body = v.body()
    decision = v.req_enum(body, "decision", ("SUBSTANTIATED", "DISMISSED"))
    assessed_severity = v.opt_enum(body, "assessed_severity", SEVERITIES)
    notes = v.opt_str(body, "notes")
    if decision == "SUBSTANTIATED" and assessed_severity is None:
        raise ApiError("ERR_VALIDATION", "assessed_severity is required when substantiating")
    if case["state"] != "UNDER_INVESTIGATION":
        raise ApiError("ERR_INVALID_CASE_STATE")

    case["decided_at"] = now_str()
    if notes is not None:
        case["notes"] = notes
    if decision == "SUBSTANTIATED":
        case["state"] = "SUBSTANTIATED"
        case["assessed_severity"] = assessed_severity
        case["substantiated_by_user_id"] = user_id
        case["risk_contribution"] = case_rolling_contribution(case)
    else:
        case["state"] = "DISMISSED"
        case["assessed_severity"] = None
        case["substantiated_by_user_id"] = None
        case["risk_contribution"] = ZERO2
    touch(case)

    partner = db.partners.get(case["delivery_partner_id"])
    if partner is not None:
        refresh_partner(partner)
    courier = _courier_of_case(case)
    if courier is not None:
        recompute_courier_score(courier)
    return ok(public(case))


@bp.post("/violation-cases/<case_id>/reopen")
def reopen_case(case_id):
    auth(COMPLIANCE_OFFICER)
    case = fetch("cases", case_id)
    body = v.body()
    notes = v.req_str(body, "notes")
    if case["state"] not in ("SUBSTANTIATED", "DISMISSED"):
        raise ApiError("ERR_INVALID_CASE_STATE")
    case["state"] = "UNDER_INVESTIGATION"
    case["decided_at"] = None
    case["assessed_severity"] = None
    case["substantiated_by_user_id"] = None
    case["risk_contribution"] = ZERO2
    case["investigation_rounds"] += 1
    case["notes"] = notes
    touch(case)

    for plan in _plans_of(case_id):
        if plan["state"] in NON_TERMINAL_PLAN_STATES:
            plan["state"] = "SUPERSEDED"
            touch(plan)

    partner = db.partners.get(case["delivery_partner_id"])
    if partner is not None:
        refresh_partner(partner)
    courier = _courier_of_case(case)
    if courier is not None:
        recompute_courier_score(courier)
    return ok(public(case))


# ---------------------------------------------------------------------------
# Corrective action plans
# ---------------------------------------------------------------------------
@bp.post("/violation-cases/<case_id>/corrective-action-plans")
def file_plan(case_id):
    auth(PARTNER_MANAGER)
    case = fetch("cases", case_id)
    scope_check(case["delivery_partner_id"])
    body = v.body()
    expected_version = v.opt_int(body, "expected_violation_case_version")
    remediation_items = v.req_str_list(body, "remediation_items", min_len=1, max_len=12)
    due_at, due_raw = v.req_dt(body, "due_at")

    # tier 8 -- cross-field semantics
    if due_at <= now():
        raise ApiError("ERR_INCONSISTENT_FIELDS", "due_at must lie later than now")
    # tier 9 -- optimistic concurrency on the parent case
    if expected_version is not None and expected_version != case["version"]:
        raise ApiError("ERR_STALE_CASE_VERSION")
    # tier 10 -- the case must be substantiated
    if case["state"] != "SUBSTANTIATED":
        raise ApiError("ERR_INVALID_CASE_STATE")

    for existing in _plans_of(case_id):
        if existing["state"] in NON_TERMINAL_PLAN_STATES:
            existing["state"] = "SUPERSEDED"
            touch(existing)

    plan = new_row(
        violation_case_id=case_id,
        remediation_items=list(remediation_items),
        due_at=due_raw,
        state="SUBMITTED",
        revision_round=0,
        reviewed_by_user_id=None,
        verified_by_user_id=None,
        verification_outcome=None,
        notes=None,
    )
    db.plans[plan["id"]] = plan
    touch(case)
    return created(public(plan))


@bp.get("/violation-cases/<case_id>/corrective-action-plans")
def list_case_plans(case_id):
    auth(PLATFORM_ADMIN, COMPLIANCE_OFFICER, PARTNER_MANAGER)
    case = fetch("cases", case_id)
    scope_if(PARTNER_MANAGER, case["delivery_partner_id"])
    state = v.enum_filter("state", PLAN_STATES)
    limit, offset = pagination()
    rows = _plans_of(case_id)
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    return listing(rows, limit, offset)


@bp.get("/corrective-action-plans/<plan_id>")
def get_plan(plan_id):
    auth(PLATFORM_ADMIN, COMPLIANCE_OFFICER, PARTNER_MANAGER)
    plan = fetch("plans", plan_id)
    case = db.cases.get(plan["violation_case_id"])
    if case is not None:
        scope_if(PARTNER_MANAGER, case["delivery_partner_id"])
    return ok(public(plan))


@bp.post("/corrective-action-plans/<plan_id>/review")
def review_plan(plan_id):
    user_id, _role = auth(COMPLIANCE_OFFICER)
    plan = fetch("plans", plan_id)
    case = db.cases.get(plan["violation_case_id"])
    if case is not None:
        segregation_of_duties(case)
    body = v.body()
    decision = v.req_enum(body, "decision", ("ACCEPT", "REQUEST_REVISION"))
    notes = v.opt_str(body, "notes")
    if plan["state"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_PLAN_STATE")
    if case is None or case["state"] != "SUBSTANTIATED":
        raise ApiError("ERR_INVALID_CASE_STATE")
    plan["state"] = "ACCEPTED" if decision == "ACCEPT" else "REVISION_REQUESTED"
    plan["reviewed_by_user_id"] = user_id
    if notes is not None:
        plan["notes"] = notes
    touch(plan)
    return ok(public(plan))


@bp.post("/corrective-action-plans/<plan_id>/resubmit")
def resubmit_plan(plan_id):
    auth(PARTNER_MANAGER)
    plan = fetch("plans", plan_id)
    case = db.cases.get(plan["violation_case_id"])
    if case is not None:
        scope_check(case["delivery_partner_id"])
    body = v.body()
    remediation_items = v.req_str_list(body, "remediation_items", min_len=1, max_len=12)
    due_at, due_raw = v.req_dt(body, "due_at")
    if plan["state"] not in ("REVISION_REQUESTED", "FAILED_VERIFICATION"):
        raise ApiError("ERR_INVALID_PLAN_STATE")
    if plan["revision_round"] >= MAX_REVISION_ROUNDS:
        raise ApiError("ERR_REVISION_LIMIT_REACHED")
    plan["remediation_items"] = list(remediation_items)
    plan["due_at"] = due_raw
    plan["revision_round"] += 1
    plan["state"] = "SUBMITTED"
    touch(plan)
    return ok(public(plan))


@bp.post("/corrective-action-plans/<plan_id>/verify")
def verify_plan(plan_id):
    user_id, _role = auth(COMPLIANCE_OFFICER)
    plan = fetch("plans", plan_id)
    case = db.cases.get(plan["violation_case_id"])
    if case is not None:
        segregation_of_duties(case)
    body = v.body()
    outcome = v.req_enum(body, "verification_outcome", ("PASSED", "FAILED"))
    notes = v.opt_str(body, "notes")
    if plan["state"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_PLAN_STATE")

    plan["verification_outcome"] = outcome
    plan["verified_by_user_id"] = user_id
    if notes is not None:
        plan["notes"] = notes
    if outcome == "PASSED":
        plan["state"] = "VERIFIED"
        touch(plan)
        if case is not None and case["state"] == "SUBSTANTIATED":
            case["state"] = "CLOSED_VERIFIED"
            case["risk_contribution"] = ZERO2
            touch(case)
            partner = db.partners.get(case["delivery_partner_id"])
            if partner is not None:
                refresh_partner(partner)
    else:
        plan["state"] = "FAILED_VERIFICATION"
        touch(plan)
    return ok(public(plan))
