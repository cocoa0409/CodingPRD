"""Enforcement: surveillance cases, genetic testing, damages and royalty audits."""

from decimal import Decimal

from flask import Blueprint

from calculations import (COMPLIANCE_SUSPEND_THRESHOLD, MATCH_THRESHOLD,
                          damages_waterfall)
from common import filtered, resolve, terminal, transition
from derive import (apply, auto_suspend_below_threshold, children,
                    recompute_compliance, refresh_after_finalize,
                    suspend_agreement)
from errors import ApiError
from middleware import ALL_ROLES, COMPLIANCE_AUDITOR, endpoint
from response import collection, created, ok
from store import new_id, store
from validation import ID, Dec, Enum, Int, Str, UPPER_2_12

bp = Blueprint("enforcement", __name__)

CASE_SCHEMA = [
    ("variety_id", ID, True),
    ("suspected_propagator_id", ID, False),
    ("market_survey_ref", Str(1, 40), True),
]

SAMPLE_SCHEMA = [
    ("sampled_unit_count", Int(1), True),
]

TEST_SCHEMA = [
    ("lab_code", UPPER_2_12, True),
    ("marker_panel", Str(2, 16), True),
    ("match_confidence", Dec(4, 0, 1), True),
]

RESOLVE_SCHEMA = [
    ("recovered_damages_cents", Int(0), True),
    ("enforcement_cost_cents", Int(0), True),
]

ENGAGEMENT_SCHEMA = [
    ("agreement_id", ID, True),
    ("royalty_report_id", ID, True),
]

FINALIZE_SCHEMA = [
    ("finding_severity", Enum(["NONE", "MINOR", "MATERIAL"]), True),
    ("underreported_units", Int(0), False),
]


# ==================================================================
# surveillance cases
# ==================================================================
@endpoint(bp, "POST", "/surveillance-cases", [COMPLIANCE_AUDITOR], CASE_SCHEMA)
def open_case(actor, body):
    variety = resolve("variety_id", body["variety_id"])
    suspect_id = body["suspected_propagator_id"]
    if suspect_id is not None:
        suspect_id = resolve("suspected_propagator_id", suspect_id)["id"]
    record = {
        "id": new_id(),
        "variety_id": variety["id"],
        "suspected_propagator_id": suspect_id,
        "market_survey_ref": body["market_survey_ref"],
        "status": "OPENED",
        "sampled_unit_count": 0,
        "max_match_confidence": Decimal("0.0000"),
        "recovered_damages_cents": 0,
        "enforcement_cost_cents": 0,
        "enforcement_recovery_cents": 0,
        "breeder_pool_cents": 0,
        "propagator_credit_cents": 0,
        "concluded_at": None,
        "_concluded_result": None,
    }
    store.stamp_new(record)
    store.cases[record["id"]] = record
    return created(record)


@endpoint(bp, "GET", "/surveillance-cases", ALL_ROLES)
def list_cases(actor):
    records, limit, offset, total = filtered(
        "cases", "variety_id", "suspected_propagator_id", "status")
    return collection(records, limit, offset, total)


@endpoint(bp, "GET", "/surveillance-cases/<case_id>", ALL_ROLES)
def get_case(actor, case_id):
    return ok(resolve("case_id", case_id))


@endpoint(bp, "POST", "/surveillance-cases/<case_id>/sample", [COMPLIANCE_AUDITOR],
          SAMPLE_SCHEMA)
def sample_case(actor, body, case_id):
    case = resolve("case_id", case_id)
    terminal(case["status"] == "RESOLVED")
    transition(case["status"] == "OPENED")
    apply(case, {
        "status": "SAMPLED",
        "sampled_unit_count": int(body["sampled_unit_count"]),
    }, force=True)
    return ok(case)


@endpoint(bp, "POST", "/surveillance-cases/<case_id>/genetic-tests",
          [COMPLIANCE_AUDITOR], TEST_SCHEMA)
def record_test(actor, body, case_id):
    case = resolve("case_id", case_id)
    terminal(case["status"] == "RESOLVED")
    transition(case["status"] in ("SAMPLED", "TESTING"))
    confidence = body["match_confidence"]
    record = {
        "id": new_id(),
        "case_id": case["id"],
        "lab_code": body["lab_code"],
        "marker_panel": body["marker_panel"],
        "match_confidence": confidence,
        "result": "MATCH" if confidence >= MATCH_THRESHOLD else "NO_MATCH",
    }
    # An immutable laboratory record: id and created_at only (PRD 3.9).
    store.stamp_new(record, versioned=False)
    store.tests[record["id"]] = record
    highest = Decimal("0.0000")
    for test in children("tests", "case_id", case["id"]):
        if Decimal(test["match_confidence"]) > highest:
            highest = Decimal(test["match_confidence"])
    apply(case, {
        "status": "TESTING",
        "max_match_confidence": highest,
    }, force=True)
    return created(record)


@endpoint(bp, "GET", "/genetic-tests", ALL_ROLES)
def list_tests(actor):
    records, limit, offset, total = filtered("tests", "case_id", "result", "lab_code")
    return collection(records, limit, offset, total)


@endpoint(bp, "GET", "/genetic-tests/<test_id>", ALL_ROLES)
def get_test(actor, test_id):
    return ok(resolve("test_id", test_id))


@endpoint(bp, "POST", "/surveillance-cases/<case_id>/conclude-testing",
          [COMPLIANCE_AUDITOR], [])
def conclude_testing(actor, body, case_id):
    case = resolve("case_id", case_id)
    terminal(case["status"] == "RESOLVED")
    transition(case["status"] == "TESTING")
    confirmed = Decimal(case["max_match_confidence"]) >= MATCH_THRESHOLD
    result = "MATCH_CONFIRMED" if confirmed else "NO_MATCH"
    apply(case, {
        "status": result,
        "concluded_at": store.now_iso(),
        "_concluded_result": result,
    }, force=True)
    # The compliance cascade lives on the MATCH_CONFIRMED side only, and only
    # when the case actually names a suspect (PRD 3.9).
    if confirmed and case["suspected_propagator_id"]:
        propagator = store.propagators.get(case["suspected_propagator_id"])
        if propagator is not None:
            recompute_compliance(propagator)
    return ok(case)


@endpoint(bp, "POST", "/surveillance-cases/<case_id>/resolve", [COMPLIANCE_AUDITOR],
          RESOLVE_SCHEMA)
def resolve_case(actor, body, case_id):
    case = resolve("case_id", case_id)
    terminal(case["status"] == "RESOLVED")
    transition(case["status"] in ("MATCH_CONFIRMED", "NO_MATCH"))
    recovery, breeder_pool, credit = damages_waterfall(
        body["recovered_damages_cents"], body["enforcement_cost_cents"])
    apply(case, {
        "status": "RESOLVED",
        "recovered_damages_cents": int(body["recovered_damages_cents"]),
        "enforcement_cost_cents": int(body["enforcement_cost_cents"]),
        "enforcement_recovery_cents": recovery,
        "breeder_pool_cents": breeder_pool,
        "propagator_credit_cents": credit,
    }, force=True)
    if case["suspected_propagator_id"]:
        propagator = store.propagators.get(case["suspected_propagator_id"])
        if propagator is not None:
            apply(propagator, {
                "damages_credit_cents": int(propagator["damages_credit_cents"]) + credit,
            }, force=True)
    return ok(case)


# ==================================================================
# audit engagements
# ==================================================================
@endpoint(bp, "POST", "/audit-engagements", [COMPLIANCE_AUDITOR], ENGAGEMENT_SCHEMA)
def open_engagement(actor, body):
    agreement = resolve("agreement_id", body["agreement_id"])
    report = resolve("royalty_report_id", body["royalty_report_id"])
    if report["agreement_id"] != agreement["id"]:
        raise ApiError("ERR_REPORT_ENGAGEMENT_MISMATCH")
    record = {
        "id": new_id(),
        "agreement_id": agreement["id"],
        "royalty_report_id": report["id"],
        "status": "OPENED",
        "underreported_units": 0,
        "finding_severity": None,
        "finalized_at": None,
        "finalized_by_user_id": None,
    }
    store.stamp_new(record)
    store.engagements[record["id"]] = record
    return created(record)


@endpoint(bp, "GET", "/audit-engagements", ALL_ROLES)
def list_engagements(actor):
    records, limit, offset, total = filtered(
        "engagements", "agreement_id", "royalty_report_id", "status",
        "finding_severity")
    return collection(records, limit, offset, total)


@endpoint(bp, "GET", "/audit-engagements/<engagement_id>", ALL_ROLES)
def get_engagement(actor, engagement_id):
    return ok(resolve("engagement_id", engagement_id))


@endpoint(bp, "POST", "/audit-engagements/<engagement_id>/finalize",
          [COMPLIANCE_AUDITOR], FINALIZE_SCHEMA)
def finalize_engagement(actor, body, engagement_id):
    severity = body["finding_severity"]
    units = body["underreported_units"]
    # A finding with no underreported units is not a finding: a payload-only
    # constraint, so it is judged in the body tier of PRD 2.8.
    if severity in ("MINOR", "MATERIAL") and (units is None or int(units) < 1):
        raise ApiError("ERR_INVALID_REQUEST",
                       "underreported_units must be at least 1 for a finding.")
    engagement = resolve("engagement_id", engagement_id)
    terminal(engagement["status"] in ("FINDINGS_ISSUED", "CLOSED_NO_FINDING"))
    transition(engagement["status"] == "OPENED")

    if severity == "NONE":
        apply(engagement, {
            "status": "CLOSED_NO_FINDING",
            "finding_severity": "NONE",
            "underreported_units": 0,
            "finalized_at": store.now_iso(),
            "finalized_by_user_id": actor.user_id,
        }, force=True)
        return ok(engagement)

    apply(engagement, {
        "status": "FINDINGS_ISSUED",
        "finding_severity": severity,
        "underreported_units": int(units),
        "finalized_at": store.now_iso(),
        "finalized_by_user_id": actor.user_id,
    }, force=True)

    agreement = store.agreements[engagement["agreement_id"]]
    propagator = store.propagators[agreement["propagator_id"]]
    # Dispute limb: only an ACCEPTED and UNSETTLED report is un-booked.
    report = store.reports.get(engagement["royalty_report_id"])
    if (report is not None and report["review_status"] == "ACCEPTED"
            and report["settlement_status"] == "UNSETTLED"):
        apply(report, {"review_status": "DISPUTED", "booked_amount_cents": 0},
              force=True)
    rolling = refresh_after_finalize(propagator, severity == "MATERIAL")
    # MATERIAL suspends outright; MINOR only through the score threshold.
    if severity == "MATERIAL" and agreement["status"] == "ACTIVE":
        suspend_agreement(agreement, "AUDIT_FINDING")
    if rolling < COMPLIANCE_SUSPEND_THRESHOLD:
        auto_suspend_below_threshold(propagator, rolling)
    return ok(engagement)
