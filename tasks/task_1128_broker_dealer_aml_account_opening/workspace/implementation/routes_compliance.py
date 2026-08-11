"""Routes: monitoring alerts, AML cases, SAR filings, FinCEN 314(a)."""

from datetime import date, timedelta

from flask import Blueprint, g, request

from db import store, new_record, bump, serialize, now_iso, today
from errors import ApiError
from services import (
    apply_risk, recompute_counts, recompute_posture, restrict_cascade,
    run_314a_scan, matches_of_account, cases_of_account,
)
from util import (
    endpoint, ok_object, list_response, field, MISSING, require_fields,
    get_or_404, parse_date, is_int, ALL_ROLES,
)

bp = Blueprint("compliance", __name__)

ALERT_STATUSES = {"NEW", "UNDER_REVIEW", "ESCALATED_TO_CASE", "CLOSED_NO_ACTION"}
CASE_STATUSES = {"OPEN", "INVESTIGATING", "SAR_RECOMMENDED", "DECIDED_FILED",
                 "DECIDED_NO_FILE", "CLOSED", "REOPENED"}
CASE_PRIORITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
SAR_STATUSES = {"DRAFT", "FILED", "SUPERSEDED"}
REQUEST_STATUSES = {"RECEIVED", "SCAN_COMPLETE", "RESPONSE_SUBMITTED", "OVERDUE"}
MATCH_STATUSES = {"PENDING_REVIEW", "CONFIRMED", "FALSE_POSITIVE", "RESOLVED"}
SUBJECT_TYPES = {"INDIVIDUAL", "ENTITY"}


def _priority_from_severity(severity):
    if severity >= 150:
        return "CRITICAL"
    if severity >= 100:
        return "HIGH"
    if severity >= 50:
        return "MEDIUM"
    return "LOW"


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

@bp.get("/aml/alerts")
@endpoint(ALL_ROLES)
def list_alerts():
    return list_response(
        list(store.alerts.values()),
        {
            "account_id": request.args.get("account_id"),
            "transaction_id": request.args.get("transaction_id"),
            "rule_id": request.args.get("rule_id"),
            "status": request.args.get("status"),
        },
        enum_filters=[("status", ALERT_STATUSES)],
    )


@bp.get("/aml/alerts/<aid>")
@endpoint(ALL_ROLES)
def get_alert(aid):
    return ok_object(serialize(get_or_404("alerts", aid, "ERR_ALERT_NOT_FOUND")))


def _alert_and_account(aid):
    alert = get_or_404("alerts", aid, "ERR_ALERT_NOT_FOUND")
    return alert, store.accounts[alert["account_id"]]


@bp.post("/aml/alerts/<aid>/begin-review")
@endpoint(["AMLAnalyst"])
def begin_review(aid):
    alert, account = _alert_and_account(aid)
    if alert["status"] != "NEW":
        raise ApiError("ERR_ALERT_NOT_ACTIONABLE", 409, "Alert must be NEW to begin review")
    alert["status"] = "UNDER_REVIEW"
    bump(alert)
    recompute_counts(account)
    return ok_object(serialize(alert))


@bp.post("/aml/alerts/<aid>/close-no-action")
@endpoint(["AMLAnalyst"])
def close_no_action(aid):
    alert, account = _alert_and_account(aid)
    if alert["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_ALERT_NOT_ACTIONABLE", 409, "Alert must be UNDER_REVIEW to close")
    require_fields([("rationale", "nstr", True)])
    alert["status"] = "CLOSED_NO_ACTION"
    alert["close_rationale"] = field("rationale")
    bump(alert)
    recompute_counts(account)
    return ok_object(serialize(alert))


@bp.post("/aml/alerts/<aid>/reopen")
@endpoint(["AMLAnalyst"])
def reopen_alert(aid):
    alert, account = _alert_and_account(aid)
    if alert["status"] != "CLOSED_NO_ACTION":
        raise ApiError("ERR_ALERT_NOT_ACTIONABLE", 409, "Alert must be CLOSED_NO_ACTION to reopen")
    alert["status"] = "UNDER_REVIEW"
    bump(alert)
    recompute_counts(account)
    return ok_object(serialize(alert))


@bp.post("/aml/alerts/<aid>/escalate")
@endpoint(["AMLAnalyst"])
def escalate_alert(aid):
    alert, account = _alert_and_account(aid)
    if alert["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_ALERT_NOT_ACTIONABLE", 409, "Alert must be UNDER_REVIEW to escalate")
    # Pinned order: (1) alert -> ESCALATED_TO_CASE + case created OPEN;
    # (2) case priority from the alert's FROZEN severity (pre-recalc);
    # (3) ONGOING risk recalc; (4) open counts recomputed.
    alert["status"] = "ESCALATED_TO_CASE"
    bump(alert)
    case = new_record()
    case.update({
        "account_id": account["id"],
        "origin_alert_id": alert["id"],
        "priority": _priority_from_severity(alert["severity"]),
        "status": "OPEN",
        "recommending_analyst_id": None,
        "initial_detection_date": None,
        "reopen_reason": None,
    })
    store.cases[case["id"]] = case
    txn = store.transactions.get(alert["transaction_id"]) if alert.get("transaction_id") else None
    if txn is not None and txn["status"] == "FLAGGED":
        txn["status"] = "ESCALATED"
        bump(txn)
    apply_risk(account, "ONGOING")
    recompute_counts(account)
    bump(account)
    return ok_object({"alert_id": alert["id"], "case_id": case["id"],
                      "case_priority": case["priority"]}, 201)


# ---------------------------------------------------------------------------
# AML cases
# ---------------------------------------------------------------------------

@bp.post("/aml/aml-cases")
@endpoint(["AMLAnalyst"])
def create_case():
    account_id = field("account_id")
    account = None
    if isinstance(account_id, str):
        account = store.accounts.get(account_id)
        if account is None:
            raise ApiError("ERR_ACCOUNT_NOT_FOUND", 404, "Account %s does not exist" % account_id)
    ev = field("expected_account_version")
    if account is not None and is_int(ev) and ev != account["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_account_version does not match the account's current version")
    origin = field("origin_alert_id")
    if isinstance(origin, str):
        alert = store.alerts.get(origin)
        if alert is None:
            raise ApiError("ERR_ALERT_NOT_FOUND", 404, "Alert %s does not exist" % origin)
        if account is not None and alert["account_id"] != account["id"]:
            raise ApiError("ERR_ALERT_ACCOUNT_MISMATCH", 400,
                           "origin_alert_id belongs to a different account")
    require_fields([("account_id", "nstr", True),
                    ("expected_account_version", "int", True),
                    ("origin_alert_id", "str", False)])
    case = new_record()
    case.update({
        "account_id": account["id"],
        "origin_alert_id": origin if isinstance(origin, str) else None,
        "priority": "MEDIUM",
        "status": "OPEN",
        "recommending_analyst_id": None,
        "initial_detection_date": None,
        "reopen_reason": None,
    })
    store.cases[case["id"]] = case
    apply_risk(account, "ONGOING")
    recompute_counts(account)
    bump(account)
    return ok_object(serialize(case), 201)


@bp.get("/aml/aml-cases")
@endpoint(ALL_ROLES)
def list_cases():
    return list_response(
        list(store.cases.values()),
        {
            "account_id": request.args.get("account_id"),
            "origin_alert_id": request.args.get("origin_alert_id"),
            "status": request.args.get("status"),
            "priority": request.args.get("priority"),
        },
        enum_filters=[("status", CASE_STATUSES), ("priority", CASE_PRIORITIES)],
    )


@bp.get("/aml/aml-cases/<cid>")
@endpoint(ALL_ROLES)
def get_case(cid):
    return ok_object(serialize(get_or_404("cases", cid, "ERR_CASE_NOT_FOUND")))


@bp.post("/aml/aml-cases/<cid>/begin-investigation")
@endpoint(["AMLAnalyst"])
def begin_investigation(cid):
    case = get_or_404("cases", cid, "ERR_CASE_NOT_FOUND")
    if case["status"] not in ("OPEN", "REOPENED"):
        raise ApiError("ERR_CASE_NOT_ACTIONABLE", 409,
                       "Case must be OPEN or REOPENED to begin investigation")
    case["status"] = "INVESTIGATING"
    bump(case)
    return ok_object(serialize(case))


@bp.post("/aml/aml-cases/<cid>/recommend-sar")
@endpoint(["AMLAnalyst"])
def recommend_sar(cid):
    case = get_or_404("cases", cid, "ERR_CASE_NOT_FOUND")
    if case["status"] != "INVESTIGATING":
        raise ApiError("ERR_CASE_NOT_ACTIONABLE", 409,
                       "Case must be INVESTIGATING to recommend a SAR")
    det = field("initial_detection_date")
    if det is not MISSING and parse_date(det) is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "initial_detection_date must be a well-formed YYYY-MM-DD date")
    require_fields([("recommendation_note", "nstr", True),
                    ("initial_detection_date", "date", True)])
    case["status"] = "SAR_RECOMMENDED"
    case["recommending_analyst_id"] = g.user_id
    case["initial_detection_date"] = det
    bump(case)
    return ok_object(serialize(case))


@bp.post("/aml/aml-cases/<cid>/decide-no-file")
@endpoint(["SAROfficer"])
def decide_no_file(cid):
    case = get_or_404("cases", cid, "ERR_CASE_NOT_FOUND")
    if case["status"] not in ("INVESTIGATING", "SAR_RECOMMENDED"):
        raise ApiError("ERR_CASE_NOT_ACTIONABLE", 409,
                       "Case must be INVESTIGATING or SAR_RECOMMENDED to decide no-file")
    require_fields([("rationale", "nstr", True)])
    account = store.accounts[case["account_id"]]
    case["status"] = "DECIDED_NO_FILE"
    bump(case)
    # Compensating: origin alert returns to UNDER_REVIEW; its ESCALATED
    # transaction clears. Open workload restored to pre-escalation state.
    if case.get("origin_alert_id"):
        alert = store.alerts.get(case["origin_alert_id"])
        if alert is not None and alert["status"] == "ESCALATED_TO_CASE":
            alert["status"] = "UNDER_REVIEW"
            bump(alert)
            txn = store.transactions.get(alert["transaction_id"]) if alert.get("transaction_id") else None
            if txn is not None and txn["status"] == "ESCALATED":
                txn["status"] = "CLEARED"
                bump(txn)
    recompute_counts(account)
    recompute_posture(account)
    bump(account)
    return ok_object(serialize(case))


@bp.post("/aml/aml-cases/<cid>/close")
@endpoint(["SAROfficer"])
def close_case(cid):
    case = get_or_404("cases", cid, "ERR_CASE_NOT_FOUND")
    if case["status"] not in ("DECIDED_NO_FILE", "DECIDED_FILED"):
        raise ApiError("ERR_CASE_NOT_ACTIONABLE", 409,
                       "Case must be DECIDED_NO_FILE or DECIDED_FILED to close")
    if any(f["case_id"] == cid and f["status"] == "DRAFT"
           for f in store.sar_filings.values()):
        raise ApiError("ERR_CASE_HAS_OPEN_FILING", 409,
                       "Case close blocked by a DRAFT SAR filing")
    account = store.accounts[case["account_id"]]
    case["status"] = "CLOSED"
    bump(case)
    recompute_counts(account)
    recompute_posture(account)
    return ok_object(serialize(case))


@bp.post("/aml/aml-cases/<cid>/reopen")
@endpoint(["AMLAnalyst"])
def reopen_case(cid):
    case = get_or_404("cases", cid, "ERR_CASE_NOT_FOUND")
    if case["status"] != "CLOSED":
        raise ApiError("ERR_CASE_NOT_ACTIONABLE", 409, "Case must be CLOSED to reopen")
    require_fields([("reason", "nstr", True)])
    account = store.accounts[case["account_id"]]
    case["status"] = "REOPENED"
    case["reopen_reason"] = field("reason")
    bump(case)
    recompute_counts(account)
    recompute_posture(account)
    return ok_object(serialize(case))


# ---------------------------------------------------------------------------
# SAR filings
# ---------------------------------------------------------------------------

@bp.post("/aml/sar-filings")
@endpoint(["SAROfficer"])
def create_sar_filing():
    case_id = field("case_id")
    case = None
    if isinstance(case_id, str):
        case = store.cases.get(case_id)
        if case is None:
            raise ApiError("ERR_CASE_NOT_FOUND", 404, "Case %s does not exist" % case_id)
    a_start_raw, a_end_raw = field("activity_start"), field("activity_end")
    a_start, a_end = parse_date(a_start_raw), parse_date(a_end_raw)
    if (a_start_raw is not MISSING and a_start is None) \
            or (a_end_raw is not MISSING and a_end is None):
        raise ApiError("ERR_INVALID_DATE_RANGE", 400, "Dates must be well-formed YYYY-MM-DD")
    if a_start is not None and a_end is not None and a_start > a_end:
        raise ApiError("ERR_INVALID_DATE_RANGE", 400,
                       "activity_start must not be later than activity_end")
    prior_id = field("prior_filing_id")
    prior = None
    if isinstance(prior_id, str):
        prior = store.sar_filings.get(prior_id)
        if prior is None:
            raise ApiError("ERR_SAR_FILING_NOT_FOUND", 404,
                           "SAR filing %s does not exist" % prior_id)
        if case is not None and (prior["case_id"] != case["id"] or prior["status"] != "FILED"):
            raise ApiError("ERR_PRIOR_FILING_CASE_MISMATCH", 400,
                           "prior_filing_id must reference a FILED filing of the same case")
    if case is not None:
        if prior is None:
            if case["status"] != "SAR_RECOMMENDED":
                raise ApiError("ERR_CASE_NOT_SAR_RECOMMENDED", 409,
                               "Initial SAR draft requires the case to be SAR_RECOMMENDED")
        else:
            if case["status"] != "DECIDED_FILED":
                raise ApiError("ERR_PRIOR_FILING_CASE_MISMATCH", 400,
                               "Continuing SAR draft requires the case to be DECIDED_FILED")
    require_fields([("case_id", "nstr", True), ("narrative", "nstr", True),
                    ("activity_start", "date", True), ("activity_end", "date", True),
                    ("prior_filing_id", "str", False)])
    rec = new_record()
    if prior is None:
        deadline = date.fromisoformat(case["initial_detection_date"]) + timedelta(days=30)
    else:
        deadline = date.fromisoformat(prior["filed_at"][:10]) + timedelta(days=120)
    rec.update({
        "case_id": case["id"],
        "prior_filing_id": prior["id"] if prior else None,
        "narrative": field("narrative"),
        "activity_start": a_start_raw,
        "activity_end": a_end_raw,
        "status": "DRAFT",
        "filing_deadline": deadline.isoformat(),
        "filed_at": None,
        "filed_late": False,
        "continuing_review_due_date": None,
        "continuing_review_count": 0,
        "last_continuing_review_at": None,
        "review_overdue": False,
    })
    store.sar_filings[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/aml/sar-filings")
@endpoint(ALL_ROLES)
def list_sar_filings():
    return list_response(
        list(store.sar_filings.values()),
        {
            "case_id": request.args.get("case_id"),
            "prior_filing_id": request.args.get("prior_filing_id"),
            "status": request.args.get("status"),
        },
        enum_filters=[("status", SAR_STATUSES)],
    )


@bp.get("/aml/sar-filings/<fid>")
@endpoint(ALL_ROLES)
def get_sar_filing(fid):
    return ok_object(serialize(get_or_404("sar_filings", fid, "ERR_SAR_FILING_NOT_FOUND")))


@bp.post("/aml/sar-filings/<fid>/file")
@endpoint(["SAROfficer"])
def file_sar(fid):
    filing = get_or_404("sar_filings", fid, "ERR_SAR_FILING_NOT_FOUND")
    case = store.cases[filing["case_id"]]
    # Segregation of duties (priority 3): filer != recommending analyst
    if case.get("recommending_analyst_id") is not None \
            and g.user_id == case["recommending_analyst_id"]:
        raise ApiError("ERR_SOD_VIOLATION", 403,
                       "The SAR filer must differ from the recommending analyst")
    if filing["status"] != "DRAFT":
        raise ApiError("ERR_SAR_NOT_FILABLE", 409, "SAR filing must be DRAFT to file")
    if filing.get("prior_filing_id") is None:
        if case["status"] != "SAR_RECOMMENDED":
            raise ApiError("ERR_CASE_NOT_SAR_RECOMMENDED", 409,
                           "Initial filing requires the case to be SAR_RECOMMENDED")
    else:
        prior = store.sar_filings[filing["prior_filing_id"]]
        if prior["case_id"] != case["id"] or prior["status"] != "FILED" \
                or case["status"] != "DECIDED_FILED":
            raise ApiError("ERR_PRIOR_FILING_CASE_MISMATCH", 400,
                           "Continuing filing requires a FILED prior filing of the same case and a DECIDED_FILED case")
    filed_date = today()
    filing["status"] = "FILED"
    filing["filed_at"] = now_iso()
    filing["filed_late"] = filed_date > date.fromisoformat(filing["filing_deadline"])
    filing["continuing_review_due_date"] = (filed_date + timedelta(days=90)).isoformat()
    bump(filing)
    if filing.get("prior_filing_id") is None:
        case["status"] = "DECIDED_FILED"
        bump(case)
    else:
        prior = store.sar_filings[filing["prior_filing_id"]]
        prior["status"] = "SUPERSEDED"
        bump(prior)
    return ok_object(serialize(filing))


@bp.post("/aml/sar-filings/<fid>/continuing-reviews")
@endpoint(["SAROfficer"])
def continuing_review(fid):
    filing = get_or_404("sar_filings", fid, "ERR_SAR_FILING_NOT_FOUND")
    if filing["status"] != "FILED":
        raise ApiError("ERR_SAR_NOT_FILABLE", 409,
                       "Continuing reviews are recorded against a FILED filing")
    a_start_raw, a_end_raw = field("activity_start"), field("activity_end")
    a_start = parse_date(a_start_raw) if a_start_raw is not MISSING else None
    a_end = parse_date(a_end_raw) if a_end_raw is not MISSING else None
    if (a_start_raw is not MISSING and a_start is None) \
            or (a_end_raw is not MISSING and a_end is None):
        raise ApiError("ERR_INVALID_DATE_RANGE", 400, "Dates must be well-formed YYYY-MM-DD")
    eff_start = a_start if a_start is not None else date.fromisoformat(filing["activity_start"])
    eff_end = a_end if a_end is not None else date.fromisoformat(filing["activity_end"])
    if eff_start > eff_end:
        raise ApiError("ERR_INVALID_DATE_RANGE", 400,
                       "activity_start must not be later than activity_end")
    require_fields([("outcome", "nstr", True), ("note", "nstr", True),
                    ("narrative", "str", False)])
    filing["continuing_review_count"] += 1
    filing["last_continuing_review_at"] = now_iso()
    filing["review_overdue"] = False
    if field("narrative") is not MISSING:
        filing["narrative"] = field("narrative")
    if a_start_raw is not MISSING:
        filing["activity_start"] = a_start_raw
    if a_end_raw is not MISSING:
        filing["activity_end"] = a_end_raw
    next_due = today() + timedelta(days=90)
    filing["continuing_review_due_date"] = next_due.isoformat()
    bump(filing)
    new_draft_id = None
    if field("outcome") == "CONTINUING_ACTIVITY":
        draft = new_record()
        draft.update({
            "case_id": filing["case_id"],
            "prior_filing_id": filing["id"],
            "narrative": filing["narrative"],
            "activity_start": filing["activity_start"],
            "activity_end": filing["activity_end"],
            "status": "DRAFT",
            "filing_deadline": (date.fromisoformat(filing["filed_at"][:10])
                                + timedelta(days=120)).isoformat(),
            "filed_at": None,
            "filed_late": False,
            "continuing_review_due_date": None,
            "continuing_review_count": 0,
            "last_continuing_review_at": None,
            "review_overdue": False,
        })
        store.sar_filings[draft["id"]] = draft
        new_draft_id = draft["id"]
    return ok_object({"new_draft_filing_id": new_draft_id,
                      "next_review_due": next_due.isoformat()})


# ---------------------------------------------------------------------------
# FinCEN 314(a)
# ---------------------------------------------------------------------------

@bp.post("/aml/fincen-314a-requests")
@endpoint(["ComplianceOfficer"])
def create_314a_request():
    ref = field("request_reference")
    if isinstance(ref, str) and any(r["request_reference"] == ref
                                    for r in store.fincen_requests.values()):
        raise ApiError("ERR_DUPLICATE_314A_REQUEST", 409,
                       "request_reference already registered")
    subjects = field("subjects")
    if isinstance(subjects, list):
        for s in subjects:
            if not isinstance(s, dict):
                raise ApiError("ERR_INVALID_REQUEST", 400, "subjects entries must be objects")
            st = s.get("subject_type")
            if st is not None and st not in SUBJECT_TYPES:
                raise ApiError("ERR_INVALID_ENUM", 400,
                               "subject_type must be INDIVIDUAL or ENTITY")
            if not isinstance(s.get("name"), str) or not s.get("name", "").strip():
                raise ApiError("ERR_INVALID_REQUEST", 400, "Each subject requires a name")
            if "date_of_birth" in s and s["date_of_birth"] is not None \
                    and parse_date(s["date_of_birth"]) is None:
                raise ApiError("ERR_INVALID_REQUEST", 400,
                               "subject date_of_birth must be YYYY-MM-DD")
    require_fields([("request_reference", "nstr", True), ("subjects", "list", True)])
    rec = new_record()
    rec.update({
        "request_reference": ref,
        "subjects": subjects,
        "received_at": now_iso(),
        "response_deadline": (today() + timedelta(days=14)).isoformat(),
        "status": "RECEIVED",
        "match_count": 0,
        "responded_at": None,
        "responded_late": False,
    })
    store.fincen_requests[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/aml/fincen-314a-requests")
@endpoint(ALL_ROLES)
def list_314a_requests():
    return list_response(
        list(store.fincen_requests.values()),
        {"status": request.args.get("status")},
        enum_filters=[("status", REQUEST_STATUSES)],
    )


@bp.get("/aml/fincen-314a-requests/<rid>")
@endpoint(ALL_ROLES)
def get_314a_request(rid):
    return ok_object(serialize(get_or_404("fincen_requests", rid, "ERR_FINCEN_REQUEST_NOT_FOUND")))


@bp.post("/aml/fincen-314a-requests/<rid>/scan")
@endpoint(["ComplianceOfficer"])
def scan_314a_request(rid):
    req = get_or_404("fincen_requests", rid, "ERR_FINCEN_REQUEST_NOT_FOUND")
    if req["status"] != "RECEIVED":
        raise ApiError("ERR_FINCEN_REQUEST_NOT_SCANNABLE", 409,
                       "Request must be RECEIVED to scan")
    run_314a_scan(req)
    req["status"] = "SCAN_COMPLETE"
    bump(req)
    return ok_object(serialize(req))


@bp.post("/aml/fincen-314a-requests/<rid>/submit-response")
@endpoint(["ComplianceOfficer"])
def submit_314a_response(rid):
    req = get_or_404("fincen_requests", rid, "ERR_FINCEN_REQUEST_NOT_FOUND")
    if req["status"] not in ("SCAN_COMPLETE", "OVERDUE"):
        raise ApiError("ERR_FINCEN_REQUEST_NOT_SCANNABLE", 409,
                       "Request must be SCAN_COMPLETE or OVERDUE to submit a response")
    if any(m["request_id"] == rid and m["status"] not in ("FALSE_POSITIVE", "RESOLVED")
           for m in store.matches.values()):
        raise ApiError("ERR_FINCEN_RESPONSE_INCOMPLETE", 409,
                       "All matches must be FALSE_POSITIVE or RESOLVED before responding")
    req["status"] = "RESPONSE_SUBMITTED"
    req["responded_at"] = now_iso()
    req["responded_late"] = today() > date.fromisoformat(req["response_deadline"])
    bump(req)
    return ok_object(serialize(req))


@bp.get("/aml/fincen-314a-matches")
@endpoint(ALL_ROLES)
def list_314a_matches():
    return list_response(
        list(store.matches.values()),
        {
            "request_id": request.args.get("request_id"),
            "account_id": request.args.get("account_id"),
            "status": request.args.get("status"),
        },
        enum_filters=[("status", MATCH_STATUSES)],
    )


@bp.get("/aml/fincen-314a-matches/<mid>")
@endpoint(ALL_ROLES)
def get_314a_match(mid):
    return ok_object(serialize(get_or_404("matches", mid, "ERR_MATCH_NOT_FOUND")))


@bp.post("/aml/fincen-314a-matches/<mid>/confirm")
@endpoint(["ComplianceOfficer"])
def confirm_match(mid):
    match = get_or_404("matches", mid, "ERR_MATCH_NOT_FOUND")
    if match["status"] != "PENDING_REVIEW":
        raise ApiError("ERR_MATCH_NOT_REVIEWABLE", 409, "Match must be PENDING_REVIEW to confirm")
    account = store.accounts[match["account_id"]]
    match["status"] = "CONFIRMED"
    match["reviewed_by"] = g.user_id
    bump(match)
    # Four-hop cascade: restrict (if OPEN) + posture SEVERE; flag POSTED txns;
    # one NEW alert per newly flagged txn lacking an open alert; ONGOING recalc.
    if account["lifecycle_status"] == "OPEN":
        account["lifecycle_status"] = "RESTRICTED"
    restrict_cascade(account, "FINCEN_314A_MATCH")
    recompute_posture(account)
    bump(account)
    return ok_object(serialize(match))


@bp.post("/aml/fincen-314a-matches/<mid>/mark-false-positive")
@endpoint(["ComplianceOfficer"])
def mark_false_positive(mid):
    match = get_or_404("matches", mid, "ERR_MATCH_NOT_FOUND")
    if match["status"] != "PENDING_REVIEW":
        raise ApiError("ERR_MATCH_NOT_REVIEWABLE", 409,
                       "Match must be PENDING_REVIEW to mark false positive")
    require_fields([("rationale", "nstr", True)])
    match["status"] = "FALSE_POSITIVE"
    match["reviewed_by"] = g.user_id
    bump(match)
    return ok_object(serialize(match))


@bp.post("/aml/fincen-314a-matches/<mid>/resolve")
@endpoint(["ComplianceOfficer"])
def resolve_match(mid):
    match = get_or_404("matches", mid, "ERR_MATCH_NOT_FOUND")
    if match["status"] != "CONFIRMED":
        raise ApiError("ERR_MATCH_NOT_REVIEWABLE", 409, "Match must be CONFIRMED to resolve")
    account = store.accounts[match["account_id"]]
    match["status"] = "RESOLVED"
    bump(match)
    recompute_posture(account)
    bump(account)
    return ok_object(serialize(match))
