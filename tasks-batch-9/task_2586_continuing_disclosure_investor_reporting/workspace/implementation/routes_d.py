"""Failure events, direct placements, official statements, engagements,
the calendar sweep, and the logical-clock test hook."""
from flask import Blueprint, g

import calc
import domain
from core import (ALL_ROLES, CLOCK, DB, Obj, Raw, ROLE_COMPLIANCE_REVIEWER,
                  ROLE_DISCLOSURE_OFFICER, ROLE_DISSEMINATION_AGENT,
                  ROLE_FINANCE_DIRECTOR, body, bump, clock_date, clock_stamp,
                  endpoint, engagements_of, fail, fk, listing, must_get,
                  new_row, parse_date_str, placements_of_issue, touch,
                  undertaking_for_issue, vdate, vdatetime, venum, vid_list,
                  vint, vstr)
from routes_c import _subject_undertaking

bp = Blueprint("routes_d", __name__)

DISCLOSURE_PRACTICES = ("MANDATORY_MATERIAL_EVENT", "VOLUNTARY", "NOT_DISCLOSED")
LOOKBACK_POLICIES = ("STRICT_FIVE_YEAR", "REMEDIATED_EXCLUDED")


# ------------------------------------------------------- failure to file events
@bp.get("/disclosure/failure-to-file-events/<row_id>")
@endpoint(ALL_ROLES)
def get_failure_event(row_id):
    return Obj(must_get("failure_events", row_id))


@bp.get("/disclosure/failure-to-file-events")
@endpoint(ALL_ROLES)
def list_failure_events():
    return listing(DB.failure_events.values(),
                   {"undertaking_id": "undertaking_id",
                    "cycle_id": "cycle_id",
                    "material_event_id": "material_event_id",
                    "remediation_filing_id": "remediation_filing_id",
                    "kind": "kind",
                    "status": "status",
                    "severity": "severity"})


@bp.post("/disclosure/failure-to-file-events/<row_id>/remediate")
@endpoint([ROLE_DISCLOSURE_OFFICER])
def remediate_failure_event(row_id):
    event = must_get("failure_events", row_id)
    data = body()
    filing = fk("filings", data, "remediation_filing_id")
    if filing is None:
        fail("ERR_INVALID_REQUEST", "remediation_filing_id is required")
    note = vstr(data, "remediation_note", max_len=500)
    if event["status"] not in ("OPEN", "REMEDIATION_PENDING"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "only an OPEN or REMEDIATION_PENDING event may be remediated")
    # rule 31 — remediation evidence, two arms keyed on the event's own subject
    undertaking = DB.undertakings.get(event["undertaking_id"])
    if filing["status"] != "CONFIRMED":
        fail("ERR_REMEDIATION_FILING_INVALID",
             "the evidencing filing must be CONFIRMED")
    if event["cycle_id"] is not None:
        if filing["cycle_id"] != event["cycle_id"]:
            fail("ERR_REMEDIATION_FILING_INVALID",
                 "the evidencing filing must carry this event's own cycle")
    else:
        filing_undertaking = _subject_undertaking(filing)
        if undertaking is None or filing_undertaking is None \
                or filing_undertaking["id"] != undertaking["id"]:
            fail("ERR_REMEDIATION_FILING_INVALID",
                 "the evidencing filing must belong to the same undertaking")
    touch(event)
    event["status"] = "REMEDIATED"
    event["remediation_filing_id"] = filing["id"]
    event["remediation_note"] = note
    event["remediated_at"] = clock_stamp()
    domain.rerun_program_lookbacks(domain.program_code_of_undertaking(undertaking))
    return Obj(event)


# ------------------------------------------------------------- direct placements
@bp.post("/disclosure/direct-placements")
@endpoint([ROLE_DISCLOSURE_OFFICER])
def create_placement():
    data = body()
    issue = fk("bond_issues", data, "issue_id")
    if issue is None:
        fail("ERR_INVALID_REQUEST", "issue_id is required")
    lender_name = vstr(data, "lender_name", max_len=120)
    principal = vint(data, "principal_amount_cents", minimum=0)
    execution_date = vdate(data, "execution_date")
    window_start = vdate(data, "review_window_start_date")
    window_end = vdate(data, "review_window_end_date")
    practice = venum(data, "disclosure_practice", DISCLOSURE_PRACTICES)
    # rule 9 — issue gate
    if issue["status"] != "OUTSTANDING":
        fail("ERR_ISSUE_NOT_OUTSTANDING", "the issue is not OUTSTANDING")
    # rule 22 — aggregate review-window capacity, closed interval
    _check_review_capacity(issue, window_start, window_end)
    # rule 23 — window ordering and the principal floor, checked late
    if window_end < window_start:
        fail("ERR_INVALID_REQUEST",
             "review_window_end_date may not precede review_window_start_date")
    if principal < 1:
        fail("ERR_INVALID_REQUEST", "principal_amount_cents must be at least 1")
    row = new_row({
        "issue_id": issue["id"],
        "lender_name": lender_name,
        "principal_amount_cents": principal,
        "execution_date": execution_date.isoformat(),
        "review_window_start_date": window_start.isoformat(),
        "review_window_end_date": window_end.isoformat(),
        "disclosure_practice": practice,
        "materiality_ratio_bp": calc.materiality_ratio_bp(
            principal, issue["outstanding_par_amount_cents"]),
        "status": "RECEIVED",
        "linked_notice_id": None,
        "waiver_reason": None,
    })
    DB.placements[row["id"]] = row
    return Obj(row, 201)


def _check_review_capacity(issue, window_start, window_end):
    """At most two non-DISCLOSED placements may cover any single calendar date.

    Coverage is piecewise constant, so testing the window's own edges together
    with every existing edge falling inside it is exact.
    """
    existing = []
    for placement in placements_of_issue(issue["id"]):
        if placement["status"] == "DISCLOSED":
            continue
        start = parse_date_str(placement["review_window_start_date"])
        end = parse_date_str(placement["review_window_end_date"])
        if start is None or end is None:
            continue
        existing.append((start, end))
    probes = {window_start, window_end}
    for start, end in existing:
        for edge in (start, end):
            if window_start <= edge <= window_end:
                probes.add(edge)
    for probe in sorted(probes):
        covering = len([1 for start, end in existing if start <= probe <= end])
        if covering >= 2:
            fail("ERR_PLACEMENT_REVIEW_CAPACITY_EXCEEDED",
                 "two placements already cover %s on this issue"
                 % probe.isoformat())


@bp.get("/disclosure/direct-placements/<row_id>")
@endpoint(ALL_ROLES)
def get_placement(row_id):
    return Obj(must_get("placements", row_id))


@bp.get("/disclosure/direct-placements")
@endpoint(ALL_ROLES)
def list_placements():
    return listing(DB.placements.values(),
                   {"issue_id": "issue_id",
                    "linked_notice_id": "linked_notice_id",
                    "status": "status",
                    "disclosure_practice": "disclosure_practice"})


@bp.post("/disclosure/direct-placements/<row_id>/classify")
@endpoint([ROLE_COMPLIANCE_REVIEWER])
def classify_placement(row_id):
    placement = must_get("placements", row_id)
    data = body()
    waiver_reason = vstr(data, "waiver_reason", required=False, max_len=500)
    if placement["status"] != "RECEIVED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "only a RECEIVED placement may be classified")
    required = (placement["materiality_ratio_bp"] >= calc.MATERIAL_OBLIGATION_THRESHOLD_BP
                or placement["disclosure_practice"] == "MANDATORY_MATERIAL_EVENT")
    if not required and (waiver_reason is None or waiver_reason.strip() == ""):
        fail("ERR_WAIVER_REASON_REQUIRED",
             "the waived branch requires a non-empty waiver_reason")
    touch(placement)
    if required:
        placement["status"] = "DISCLOSURE_REQUIRED"
        notice = domain.create_notice(
            placement["issue_id"], "FINANCIAL_OBLIGATION_INCURRENCE",
            parse_date_str(placement["execution_date"]), g.user_id,
            per_se=False, financial_obligation_ref=placement["id"])
        placement["linked_notice_id"] = notice["id"]
        issue = DB.bond_issues.get(placement["issue_id"])
        domain.recompute_open_material_event_count(issue)
        domain.recompute_open_obligation_count(
            undertaking_for_issue(placement["issue_id"]))
    else:
        placement["status"] = "DISCLOSURE_WAIVED"
        placement["waiver_reason"] = waiver_reason
    return Obj(placement)


# ----------------------------------------------------------- official statements
def _resolve_event_ids(data):
    """Rule 4 for the `disclosed_event_ids` array: every id must resolve.

    A malformed value is left to the request-shape rung below.
    """
    if "disclosed_event_ids" not in data or data["disclosed_event_ids"] is None:
        return
    value = data["disclosed_event_ids"]
    if not isinstance(value, list):
        return
    for element in value:
        if isinstance(element, str) and element != "":
            must_get("failure_events", element)


@bp.post("/disclosure/official-statements")
@endpoint([ROLE_DISCLOSURE_OFFICER])
def create_statement():
    data = body()
    issue = fk("bond_issues", data, "issue_id")
    _resolve_event_ids(data)
    if issue is None:
        fail("ERR_INVALID_REQUEST", "issue_id is required")
    dated_date = vdate(data, "dated_date")
    policy = venum(data, "lookback_policy", LOOKBACK_POLICIES, required=False,
                   default="STRICT_FIVE_YEAR")
    disclosed = vid_list(data, "disclosed_event_ids", default=[])
    row = new_row({
        "issue_id": issue["id"],
        "dated_date": dated_date.isoformat(),
        "lookback_policy": policy,
        "status": "DRAFT",
        "disclosed_event_ids": list(disclosed),
        "required_disclosure_event_ids": [],
        "required_disclosure_event_count": 0,
        "disclosure_adequacy": "UNKNOWN",
        "reviewed_by_user_id": None,
        "reviewed_at": None,
        "posted_by_user_id": None,
        "posted_at": None,
    })
    DB.official_statements[row["id"]] = row
    return Obj(row, 201)


@bp.get("/disclosure/official-statements/<row_id>")
@endpoint(ALL_ROLES)
def get_statement(row_id):
    return Obj(must_get("official_statements", row_id))


@bp.get("/disclosure/official-statements")
@endpoint(ALL_ROLES)
def list_statements():
    return listing(DB.official_statements.values(),
                   {"issue_id": "issue_id",
                    "status": "status",
                    "lookback_policy": "lookback_policy"})


@bp.post("/disclosure/official-statements/<row_id>/compliance-review")
@endpoint([ROLE_COMPLIANCE_REVIEWER])
def review_statement(row_id):
    statement = must_get("official_statements", row_id)
    data = body()
    _resolve_event_ids(data)
    policy = venum(data, "lookback_policy", LOOKBACK_POLICIES, required=False)
    disclosed = vid_list(data, "disclosed_event_ids", default=None)
    if statement["status"] not in ("DRAFT", "COMPLIANCE_REVIEW"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "compliance review is available from DRAFT and COMPLIANCE_REVIEW only")
    issue = DB.bond_issues.get(statement["issue_id"])
    if issue is None or issue["status"] != "OUTSTANDING":
        fail("ERR_ISSUE_NOT_OUTSTANDING", "the issue is not OUTSTANDING")
    touch(statement)
    if policy is not None:
        statement["lookback_policy"] = policy
    if disclosed is not None:
        statement["disclosed_event_ids"] = list(disclosed)
    statement["status"] = "COMPLIANCE_REVIEW"
    statement["reviewed_by_user_id"] = g.user_id
    statement["reviewed_at"] = clock_stamp()
    required, _adequacy = domain.apply_lookback(statement)
    for event_id in required:
        if event_id in statement["disclosed_event_ids"]:
            event = DB.failure_events.get(event_id)
            if event is not None:
                domain.stamp_statement_on_event(event, statement["id"])
    return Obj(statement)


@bp.post("/disclosure/official-statements/<row_id>/post")
@endpoint([ROLE_COMPLIANCE_REVIEWER])
def post_statement(row_id):
    statement = must_get("official_statements", row_id)
    if statement["status"] != "COMPLIANCE_REVIEW":
        fail("ERR_INVALID_STATE_TRANSITION",
             "only a statement in COMPLIANCE_REVIEW may be posted")
    # rule 13 — review is segregated from publication
    if statement["reviewed_by_user_id"] is not None \
            and statement["reviewed_by_user_id"] == g.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the reviewer of record may not also publish the statement")
    # rule 32 — the lookback is re-run at post time
    fresh_required = domain.lookback_required_ids(statement)
    disclosed = set(statement["disclosed_event_ids"])
    if not all(event_id in disclosed for event_id in fresh_required):
        fail("ERR_DISCLOSURE_INADEQUATE",
             "the document does not describe every required failure event")
    required, _adequacy = domain.apply_lookback(statement)
    touch(statement)
    statement["status"] = "POSTED"
    statement["posted_by_user_id"] = g.user_id
    statement["posted_at"] = clock_stamp()
    for event_id in required:
        event = DB.failure_events.get(event_id)
        if event is not None:
            domain.stamp_statement_on_event(event, statement["id"])
    return Obj(statement)


# ------------------------------------------------------ dissemination engagements
@bp.post("/disclosure/dissemination-engagements")
@endpoint([ROLE_FINANCE_DIRECTOR])
def create_engagement():
    data = body()
    undertaking = fk("undertakings", data, "undertaking_id")
    if undertaking is None:
        fail("ERR_INVALID_REQUEST", "undertaking_id is required")
    agent_name = vstr(data, "agent_name", max_len=120)
    effective_date = vdate(data, "effective_date")
    expiration_date = vdate(data, "expiration_date")
    retainer_cents = vint(data, "retainer_cents", minimum=0)
    expected_version = vint(data, "expected_undertaking_version", minimum=0)
    ack_date = vdate(data, "last_calendar_ack_date", required=False)
    if expiration_date < effective_date:
        fail("ERR_INVALID_REQUEST",
             "expiration_date may not precede effective_date")
    # rule 7 — optimistic concurrency on the parent undertaking
    if expected_version != undertaking["version"]:
        fail("ERR_UNDERTAKING_VERSION_STALE",
             "expected_undertaking_version %s does not match the undertaking's "
             "current version %s" % (expected_version, undertaking["version"]))
    # rule 10 — undertaking gate
    if undertaking["status"] != "ACTIVE":
        fail("ERR_UNDERTAKING_NOT_ACTIVE", "the undertaking is not ACTIVE")
    row = new_row({
        "undertaking_id": undertaking["id"],
        "agent_name": agent_name,
        "effective_date": effective_date.isoformat(),
        "expiration_date": expiration_date.isoformat(),
        "retainer_cents": retainer_cents,
        "status": "ACTIVE",
        "last_calendar_ack_date": ack_date.isoformat() if ack_date else None,
        "monitoring_lapse_days": 0,
        "billable_filing_count": 0,
        "invoice_total_cents": 0,
        "superseded_by_engagement_id": None,
        "termination_reason": None,
    })
    # the incumbent is superseded rather than collided with
    for incumbent in engagements_of(undertaking["id"]):
        if incumbent["status"] == "TERMINATED":
            continue
        touch(incumbent)
        incumbent["status"] = "TERMINATED"
        incumbent["termination_reason"] = "SUPERSEDED"
        incumbent["superseded_by_engagement_id"] = row["id"]
    DB.engagements[row["id"]] = row
    row["monitoring_lapse_days"] = calc.monitoring_lapse_days(row)
    row["billable_filing_count"] = calc.confirmed_filing_count(row["id"])
    row["invoice_total_cents"] = calc.invoice_total(
        row["billable_filing_count"], retainer_cents,
        undertaking["compliance_posture"])
    bump(undertaking)
    return Obj(row, 201)


@bp.get("/disclosure/dissemination-engagements/<row_id>")
@endpoint(ALL_ROLES)
def get_engagement(row_id):
    return Obj(must_get("engagements", row_id))


@bp.get("/disclosure/dissemination-engagements")
@endpoint(ALL_ROLES)
def list_engagements():
    return listing(DB.engagements.values(),
                   {"undertaking_id": "undertaking_id",
                    "superseded_by_engagement_id": "superseded_by_engagement_id",
                    "status": "status"})


@bp.post("/disclosure/dissemination-engagements/<row_id>/acknowledge-calendar")
@endpoint([ROLE_DISSEMINATION_AGENT])
def acknowledge_calendar(row_id):
    engagement = must_get("engagements", row_id)
    data = body()
    ack_date = vdate(data, "last_calendar_ack_date")
    # rule 6 — the agent may only acknowledge its own engagement
    if g.user_id != engagement["id"]:
        fail("ERR_AGENT_NOT_ENGAGED",
             "an agent may only acknowledge its own engagement")
    if engagement["status"] not in ("ACTIVE", "SUSPENDED"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "a TERMINATED engagement may not acknowledge the calendar")
    effective_date = parse_date_str(engagement["effective_date"])
    if (effective_date is not None and ack_date < effective_date) \
            or ack_date > clock_date():
        fail("ERR_ACK_DATE_OUT_OF_RANGE",
             "last_calendar_ack_date must fall between effective_date and today")
    touch(engagement)
    engagement["last_calendar_ack_date"] = ack_date.isoformat()
    engagement["status"] = "ACTIVE"
    domain.refresh_monitoring_lapse(engagement)
    return Obj(engagement)


@bp.post("/disclosure/dissemination-engagements/<row_id>/terminate")
@endpoint([ROLE_FINANCE_DIRECTOR])
def terminate_engagement(row_id):
    engagement = must_get("engagements", row_id)
    if engagement["status"] not in ("ACTIVE", "SUSPENDED"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "only an ACTIVE or SUSPENDED engagement may be terminated")
    for filing in DB.filings.values():
        if filing["submitting_engagement_id"] == engagement["id"] \
                and filing["status"] == "SUBMITTED":
            fail("ERR_ENGAGEMENT_HAS_LIVE_FILING",
                 "a filing this agent submitted is still with the repository")
    touch(engagement)
    engagement["status"] = "TERMINATED"
    engagement["termination_reason"] = "ISSUER_TERMINATED"
    return Obj(engagement)


# --------------------------------------------------------------- calendar sweep
@bp.post("/disclosure/calendar-sweeps")
@endpoint([ROLE_FINANCE_DIRECTOR])
def run_calendar_sweep():
    return Raw(domain.run_sweep())


# ----------------------------------------------------------------- logical clock
@bp.post("/_clock/set_current_utc")
@endpoint([ROLE_FINANCE_DIRECTOR])
def set_clock():
    data = body()
    parsed = vdatetime(data, "current_utc")
    CLOCK.current = parsed
    return Raw({"current_utc": data["current_utc"]})
