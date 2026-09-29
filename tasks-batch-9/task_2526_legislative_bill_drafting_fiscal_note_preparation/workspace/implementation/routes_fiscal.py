"""Fiscal note routing, cost estimate lines, submission, return and
certification (PRD S3.7)."""

from flask import Blueprint

from auth import endpoint
import calc
from counters import post_to_ledger, recompute_agency
from envelope import object_response
from errors import fail
from lookups import get_agency, get_bill, get_note, require_active_session
import serializers as S
from store import all_rows, create_row, db, fmt_iso, parse_iso, touch
from validation import body, req_bool, req_enum, req_id, req_int, req_num, req_str

bp = Blueprint("fiscal", __name__)

OPEN_NOTE_STATES = ("ROUTED", "SUBMITTED", "RETURNED_FOR_REVISION")
APPEND_STATES = ("ROUTED", "RETURNED_FOR_REVISION")


def _session_of_note(note):
    bill = db.bills.get(note["bill_id"])
    return db.sessions.get(bill["session_id"]) if bill else None


def _require_owner(note, user_id):
    if note["agency_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER")


def _baseline_years_complete(note, session):
    covered = {
        line["fiscal_year"] for line in calc.current_round_lines(note, "BASELINE")
    }
    for year in session["required_fiscal_years"]:
        if year not in covered:
            return False
    return True


def _recompute_totals(note, session):
    direct, pct, contingency, total = calc.fiscal_note_cost_total(note)
    baseline, high, low = calc.multi_year_revenue_projection(note, session)
    note["direct_cost_cents"] = direct
    note["contingency_pct"] = float(pct)
    note["contingency_cents"] = contingency
    note["certified_total_cents"] = total
    note["projected_revenue_total_cents"] = baseline
    note["high_scenario_total_cents"] = high
    note["low_scenario_total_cents"] = low


# ---------------------------------------------------------------------------
# routing
# ---------------------------------------------------------------------------


@bp.post("/bills/<bid>/fiscal-note-requests")
@endpoint(("Clerk", "FiscalOfficer"))
def route_note(user_id, role, bid):
    bill = get_bill(bid)
    payload = body()
    agency_id = req_id(payload, "agency_id")
    methodology = req_enum(payload, "methodology", ("INCREMENTAL_COST", "FULL_ABSORPTION"))
    agency = get_agency(agency_id)
    session = db.sessions.get(bill["session_id"])
    require_active_session(session)
    if bill["legislative_status"] in ("DEAD", "TRANSMITTED"):
        fail("ERR_INVALID_BILL_STATE")
    if bill["fiscal_status"] not in ("NOTE_PENDING", "NOTE_STALE"):
        fail("ERR_INVALID_BILL_STATE")
    if agency["status"] != "ACTIVE":
        fail("ERR_AGENCY_INACTIVE")
    if agency["open_request_count"] >= agency["max_open_requests"]:
        fail("ERR_AGENCY_CAPACITY_EXCEEDED")
    for other in db.fiscal_note_requests.values():
        if other["bill_id"] == bill["id"] and other["status"] in OPEN_NOTE_STATES:
            fail("ERR_FISCAL_NOTE_ALREADY_OPEN")

    routed = db.now()
    note = create_row(
        "fiscal_note_requests",
        {
            "bill_id": bill["id"],
            "agency_id": agency["id"],
            "reopened_by_amendment_id": None,
            "methodology": methodology,
            "routed_utc": fmt_iso(routed),
            "due_utc": fmt_iso(calc.fiscal_note_due_utc(agency, session, routed)),
            "submitted_utc": None,
            "certified_utc": None,
            "status": "ROUTED",
            "revision_round": 0,
            "late_submission": False,
            "direct_cost_cents": None,
            "contingency_pct": None,
            "contingency_cents": None,
            "certified_total_cents": None,
            "projected_revenue_total_cents": None,
            "high_scenario_total_cents": None,
            "low_scenario_total_cents": None,
        },
    )
    recompute_agency(agency["id"])
    return object_response(S.fiscal_note_request_out(note), 201)


# ---------------------------------------------------------------------------
# cost estimate lines
# ---------------------------------------------------------------------------


@bp.post("/fiscal-note-requests/<nid>/cost-estimates")
@endpoint(("AgencyAnalyst",))
def create_cost_estimate(user_id, role, nid):
    note = get_note(nid)
    _require_owner(note, user_id)
    payload = body()
    expected = req_int(payload, "expected_fiscal_note_request_version")
    fiscal_year = req_int(payload, "fiscal_year", minimum=2000)
    scenario = req_enum(payload, "scenario", ("BASELINE", "HIGH", "LOW"))
    personnel = req_int(payload, "personnel_cost_cents", minimum=0)
    operating = req_int(payload, "operating_cost_cents", minimum=0)
    one_time = req_int(payload, "one_time_cost_cents", minimum=0)
    fte_count = req_num(payload, "fte_count", minimum=0)
    revenue = req_int(payload, "revenue_impact_cents")
    assumption_note = req_str(payload, "assumption_note")
    if expected != note["version"]:
        fail("ERR_STALE_FISCAL_NOTE_VERSION")
    require_active_session(_session_of_note(note))
    if note["status"] not in APPEND_STATES:
        fail("ERR_INVALID_FISCAL_NOTE_STATE")
    for line in db.cost_estimates.values():
        if (
            line["fiscal_note_request_id"] == note["id"]
            and line["fiscal_year"] == fiscal_year
            and line["scenario"] == scenario
            and line["revision_round"] == note["revision_round"]
        ):
            fail("ERR_DUPLICATE_COST_ESTIMATE")

    line = create_row(
        "cost_estimates",
        {
            "fiscal_note_request_id": note["id"],
            "fiscal_year": fiscal_year,
            "scenario": scenario,
            "revision_round": note["revision_round"],
            "personnel_cost_cents": personnel,
            "operating_cost_cents": operating,
            "one_time_cost_cents": one_time,
            "fte_count": fte_count,
            "revenue_impact_cents": revenue,
            "assumption_note": assumption_note,
            "included_in_certification": True,
        },
        versioned=False,
    )
    touch(note)
    return object_response(S.cost_estimate_out(line), 201)


# ---------------------------------------------------------------------------
# submission
# ---------------------------------------------------------------------------


@bp.post("/fiscal-note-requests/<nid>/submit")
@endpoint(("AgencyAnalyst",))
def submit_note(user_id, role, nid):
    note = get_note(nid)
    _require_owner(note, user_id)
    payload = body()
    req_str(payload, "submission_note", required=False)
    session = _session_of_note(note)
    require_active_session(session)
    if note["status"] not in APPEND_STATES:
        fail("ERR_INVALID_FISCAL_NOTE_STATE")
    if not calc.current_round_lines(note):
        fail("ERR_NO_COST_ESTIMATES")
    if not _baseline_years_complete(note, session):
        fail("ERR_ESTIMATE_YEARS_INCOMPLETE")

    submitted = db.now()
    note["status"] = "SUBMITTED"
    note["submitted_utc"] = fmt_iso(submitted)
    late = submitted > parse_iso(note["due_utc"])
    note["late_submission"] = late
    _recompute_totals(note, session)
    touch(note)
    if late:
        agency = db.agencies.get(note["agency_id"])
        if agency is not None:
            agency["late_submission_count"] = agency["late_submission_count"] + 1
            touch(agency)
            recompute_agency(agency["id"])
    return object_response(S.fiscal_note_request_out(note))


# ---------------------------------------------------------------------------
# return for revision
# ---------------------------------------------------------------------------


@bp.post("/fiscal-note-requests/<nid>/return")
@endpoint(("FiscalOfficer",))
def return_note(user_id, role, nid):
    note = get_note(nid)
    payload = body()
    req_str(payload, "return_reason")
    require_active_session(_session_of_note(note))
    if note["status"] != "SUBMITTED":
        fail("ERR_INVALID_FISCAL_NOTE_STATE")

    prior_round = note["revision_round"]
    note["status"] = "RETURNED_FOR_REVISION"
    note["revision_round"] = prior_round + 1
    touch(note)
    for line in all_rows("cost_estimates"):
        if (
            line["fiscal_note_request_id"] == note["id"]
            and line["revision_round"] <= prior_round
        ):
            line["included_in_certification"] = False
    agency = db.agencies.get(note["agency_id"])
    if agency is not None:
        agency["revision_count"] = agency["revision_count"] + 1
        touch(agency)
        recompute_agency(agency["id"])
    return object_response(S.fiscal_note_request_out(note))


# ---------------------------------------------------------------------------
# certification
# ---------------------------------------------------------------------------


@bp.post("/fiscal-note-requests/<nid>/certify")
@endpoint(("FiscalOfficer",))
def certify_note(user_id, role, nid):
    note = get_note(nid)
    payload = body()
    req_str(payload, "certification_note", required=False)
    session = _session_of_note(note)
    require_active_session(session)
    if note["status"] != "SUBMITTED":
        fail("ERR_INVALID_FISCAL_NOTE_STATE")
    if not _baseline_years_complete(note, session):
        fail("ERR_ESTIMATE_YEARS_INCOMPLETE")
    total = note["certified_total_cents"] or 0
    if session["certified_fiscal_total_cents"] + total > session["fiscal_cap_cents"]:
        fail("ERR_SESSION_FISCAL_CAP_EXCEEDED")

    note["status"] = "CERTIFIED"
    note["certified_utc"] = db.now_iso()
    note["reopened_by_amendment_id"] = None
    touch(note)
    post_to_ledger(session, total)
    recompute_agency(note["agency_id"])
    bill = db.bills.get(note["bill_id"])
    if bill is not None and bill["fiscal_status"] in ("NOTE_PENDING", "NOTE_STALE"):
        bill["fiscal_status"] = "NOTE_COMPLETE"
        touch(bill)
    return object_response(S.fiscal_note_request_out(note))
