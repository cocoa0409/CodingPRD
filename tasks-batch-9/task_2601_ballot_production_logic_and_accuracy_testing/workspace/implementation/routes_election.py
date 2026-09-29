"""Elections, contests and candidates."""

from flask import Blueprint

import auth
import calc
import derive
import envelope
import guards
import serial
import store
import util
import validate
from errors import fail

bp = Blueprint("elections", __name__)


# ---------------------------------------------------------------------------
# Elections
# ---------------------------------------------------------------------------

@bp.post("/elections")
def create_election():
    auth.require(auth.ELECTIONS_DIRECTOR)
    body = validate.body()
    name = validate.req_str(body, "name")
    jurisdiction = validate.req_str(body, "jurisdiction")
    election_date = validate.req_ts(body, "election_date")
    rotation_policy = validate.opt_enum(body, "rotation_policy", calc.ROTATION_POLICIES, "NONE")
    order_method = validate.opt_enum(body, "candidate_order_method",
                                     calc.CANDIDATE_ORDER_METHODS, "ALPHABETICAL_BY_BALLOT_NAME")
    la_notice_hours = validate.opt_int(body, "la_notice_hours", 48, minimum=1)
    row = store.insert("elections", {
        "name": name,
        "jurisdiction": jurisdiction,
        "election_date": util.fmt_ts(election_date),
        "rotation_policy": rotation_policy,
        "candidate_order_method": order_method,
        "la_notice_hours": la_notice_hours,
        "status": "SETUP",
        "certified_contest_count": 0,
        "committed_print_cents": 0,
        "deployment_readiness": "BLOCKED",
        "open_seal_count": 0,
        "total_ballots_received": 0,
        "total_ballots_issued": 0,
        "ballot_accountability_status": "PENDING",
        "net_ballot_variance": 0,
        "reconciliation_basis": None,
        "last_reconciled_at": None,
    })
    return envelope.created(serial.election(row))


@bp.get("/elections/<election_id>")
def read_election(election_id):
    auth.require_any()
    row = guards.find("elections", election_id)
    return envelope.ok(serial.election(row))


@bp.post("/elections/<election_id>/certify-ballot-order")
def certify_ballot_order(election_id):
    auth.require(auth.ELECTIONS_DIRECTOR)
    election = guards.find("elections", election_id)
    guards.require_phase(election, ("SETUP",))
    certified = calc.ordered_certified_contests(election_id)
    if not certified:
        fail("ERR_NO_CERTIFIED_CONTESTS", "Election has no certified contests to order.")
    for index, contest in enumerate(certified, start=1):
        store.setf(contest, ballot_order_index=index)
        derive.assign_base_order(contest, election)
    store.setf(election, status="CONTESTS_CERTIFIED")
    derive.recompute_certified_contest_count(election)
    return envelope.ok(serial.election(election))


@bp.post("/elections/<election_id>/lock-styles")
def lock_styles(election_id):
    auth.require(auth.ELECTIONS_DIRECTOR)
    election = guards.find("elections", election_id)
    guards.require_phase(election, ("CONTESTS_CERTIFIED",))
    precincts = store.precincts_of(election_id)
    for precinct in precincts:
        if not precinct["assigned_style_id"]:
            fail("ERR_ELECTION_PHASE_INVALID",
                 "Every precinct must carry an assigned ballot style before styles are locked.")
    referenced_ids = []
    for precinct in precincts:
        if precinct["assigned_style_id"] not in referenced_ids:
            referenced_ids.append(precinct["assigned_style_id"])
    referenced = [store.get("ballot_styles", sid) for sid in referenced_ids]
    referenced = [s for s in referenced if s is not None]
    for style in referenced:
        if style["status"] != "APPROVED":
            fail("ERR_STYLE_STATE_INVALID",
                 "Ballot style state %s does not permit locking." % style["status"])
    for style in referenced:
        store.setf(style, status="LOCKED")
    store.setf(election, status="STYLES_LOCKED")
    return envelope.ok(serial.election(election))


@bp.post("/elections/<election_id>/deploy")
def deploy_election(election_id):
    auth.require(auth.ELECTIONS_DIRECTOR)
    election = guards.find("elections", election_id)
    guards.require_phase(election, ("STYLES_LOCKED",))
    derive.recompute_readiness(election)
    if election["deployment_readiness"] != "READY":
        fail("ERR_DEPLOYMENT_NOT_READY", "Election is not deployment-ready.")
    store.setf(election, status="DEPLOYED")
    return envelope.ok(serial.election(election))


@bp.post("/elections/<election_id>/close-polls")
def close_polls(election_id):
    role, user = auth.require(auth.ELECTIONS_DIRECTOR)
    election = guards.find("elections", election_id)
    guards.require_phase(election, ("DEPLOYED",))
    for unit in store.units_of_election(election_id):
        if unit["custody_status"] == "DEPLOYED":
            derive.append_custody(election_id, "TABULATOR_UNIT", unit["id"], "RETURN",
                                  "DEPLOYED", "RETURNED", unit.get("seal_number"),
                                  role, "system")
            store.setf(unit, custody_status="RETURNED")
    store.setf(election, status="POLLS_CLOSED")
    derive.recompute_readiness(election)
    derive.recompute_open_seals(election)
    return envelope.ok(serial.election(election))


@bp.post("/elections/<election_id>/reconcile")
def reconcile(election_id):
    auth.require(auth.ELECTIONS_DIRECTOR)
    body = validate.body()
    basis = validate.req_enum(body, "basis", calc.RECONCILIATION_BASES)
    expected_version = validate.req_int(body, "expected_election_version")
    election = guards.find("elections", election_id)
    if expected_version != election["version"]:
        fail("ERR_STALE_ELECTION_VERSION",
             "Election version %d no longer current." % expected_version)
    guards.require_phase(election, ("POLLS_CLOSED", "RECONCILED"))
    if basis == "FINAL_CANVASS":
        still_issued = [l for l in store.lots_of_election(election_id)
                        if l["custody_state"] == "ISSUED"]
        if still_issued:
            fail("ERR_LOTS_NOT_RETURNED",
                 "%d lots are still issued; a final canvass requires every lot returned."
                 % len(still_issued))
    sheet = calc.accountability(election_id, basis)
    # Reconciliation is repeatable and always bumps the version, even when a
    # repeat pass writes byte-identical figures, so a client re-reconciling must
    # read the election again for a fresh expected_election_version.
    election.update({
        "total_ballots_issued": sheet["gross_issued"],
        "net_ballot_variance": sheet["net_variance"],
        "ballot_accountability_status": sheet["ballot_accountability_status"],
        "reconciliation_basis": basis,
        "last_reconciled_at": util.now_str(),
        "status": "RECONCILED",
    })
    store.touch(election)
    return envelope.ok(serial.election(election))


@bp.get("/elections/<election_id>/accountability")
def read_accountability(election_id):
    auth.require_any()
    basis = validate.query_enum("basis", calc.RECONCILIATION_BASES, "PRELIMINARY")
    guards.find("elections", election_id)
    return envelope.ok(calc.accountability(election_id, basis))


@bp.get("/elections/<election_id>/custody-events")
def list_custody_events(election_id):
    auth.require_any()
    limit, offset = validate.pagination()
    subject_type = validate.query_enum("subject_type", ("TABULATOR_UNIT", "BALLOT_LOT"))
    subject_id = validate.query_str("subject_id")
    event_type = validate.query_enum("event_type", (
        "TRANSFER_OUT", "RECEIPT", "ISSUE", "RECALL", "RETURN",
        "SEAL_APPLIED", "SEAL_BROKEN", "RETENTION_SEAL", "VOID"))
    guards.find("elections", election_id)
    rows = store.events_of_election(election_id)
    if subject_type:
        rows = [r for r in rows if r["subject_type"] == subject_type]
    if subject_id:
        rows = [r for r in rows if r["subject_id"] == subject_id]
    if event_type:
        rows = [r for r in rows if r["event_type"] == event_type]
    rows.sort(key=lambda r: (r["sequence_index"], r["_seq"]))
    page, total = validate.paginate(rows, limit, offset)
    return envelope.ok_list([serial.event(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Contests
# ---------------------------------------------------------------------------

@bp.post("/elections/<election_id>/contests")
def create_contest(election_id):
    auth.require(auth.ELECTIONS_DIRECTOR, auth.BALLOT_COORDINATOR)
    body = validate.body()
    title = validate.req_str(body, "title")
    contest_type = validate.req_enum(body, "contest_type", calc.CONTEST_TYPES)
    district_code = validate.req_str(body, "district_code")
    seats_open = validate.req_int(body, "seats_open", minimum=1)
    rotation_required = validate.opt_bool(body, "rotation_required", False)
    election = guards.find("elections", election_id)
    guards.require_phase(election, ("SETUP",))
    row = store.insert("contests", {
        "election_id": election_id,
        "title": title,
        "contest_type": contest_type,
        "district_code": district_code,
        "seats_open": seats_open,
        "rotation_required": rotation_required,
        "ballot_order_index": None,
        "status": "DRAFT",
        "certified_candidate_count": 0,
        "certified_at": None,
        "withdrawn_reason": None,
    })
    return envelope.created(serial.contest(row))


@bp.get("/elections/<election_id>/contests")
def list_contests(election_id):
    auth.require_any()
    limit, offset = validate.pagination()
    status = validate.query_enum("status", ("DRAFT", "CERTIFIED", "WITHDRAWN"))
    guards.find("elections", election_id)
    rows = store.contests_of(election_id)
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=store.order_key)
    page, total = validate.paginate(rows, limit, offset)
    return envelope.ok_list([serial.contest(r) for r in page], limit, offset, total)


@bp.get("/contests/<contest_id>")
def read_contest(contest_id):
    auth.require_any()
    row = guards.find("contests", contest_id)
    return envelope.ok(serial.contest(row))


@bp.post("/contests/<contest_id>/certify")
def certify_contest(contest_id):
    auth.require(auth.ELECTIONS_DIRECTOR)
    contest = guards.find("contests", contest_id)
    election = guards.election_of_contest(contest)
    guards.require_phase(election, ("SETUP",))
    if contest["status"] != "DRAFT":
        fail("ERR_CONTEST_STATE_INVALID",
             "Contest state %s does not permit certification." % contest["status"])
    filed = [c for c in store.candidates_of(contest_id) if c["status"] == "FILED"]
    if contest["contest_type"] == "CANDIDATE" and len(filed) < contest["seats_open"]:
        fail("ERR_CANDIDATE_STATE_INVALID",
             "Contest has %d filed candidates for %d seats open."
             % (len(filed), contest["seats_open"]))
    for other in store.contests_of(election["id"]):
        if other["id"] == contest_id:
            continue
        if other["status"] not in ("DRAFT", "CERTIFIED"):
            continue
        if (other["contest_type"] == contest["contest_type"]
                and other["district_code"] == contest["district_code"]
                and other["title"] == contest["title"]):
            fail("ERR_BALLOT_ORDER_COLLISION",
                 "Contests %s and %s cannot be ordered deterministically."
                 % (contest_id, other["id"]))
    filed.sort(key=store.order_key)
    for candidate in filed:
        store.setf(candidate, status="CERTIFIED")
    store.setf(contest, status="CERTIFIED", certified_candidate_count=len(filed),
               certified_at=util.now_str())
    derive.assign_base_order(contest, election)
    derive.recompute_certified_contest_count(election)
    for style in derive.styles_covering(election["id"], contest["district_code"]):
        derive.recompute_style_contest_count(style)
    return envelope.ok(serial.contest(contest))


@bp.post("/contests/<contest_id>/withdraw")
def withdraw_contest(contest_id):
    role, user = auth.require(auth.ELECTIONS_DIRECTOR)
    body = validate.body()
    withdrawn_reason = validate.req_str(body, "withdrawn_reason")
    contest = guards.find("contests", contest_id)
    election = guards.election_of_contest(contest)
    guards.require_phase(election, ("SETUP", "CONTESTS_CERTIFIED", "STYLES_LOCKED"))
    if contest["status"] != "CERTIFIED":
        fail("ERR_CONTEST_STATE_INVALID",
             "Contest state %s does not permit withdrawal." % contest["status"])
    store.setf(contest, status="WITHDRAWN", ballot_order_index=None,
               withdrawn_reason=withdrawn_reason)
    derive.recompute_certified_contest_count(election)
    derive.cascade_contest_withdrawn(contest, election, role, user)
    return envelope.ok(serial.contest(contest))


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------

@bp.post("/contests/<contest_id>/candidates")
def create_candidate(contest_id):
    auth.require(auth.ELECTIONS_DIRECTOR, auth.BALLOT_COORDINATOR)
    body = validate.body()
    full_name = validate.req_str(body, "full_name")
    ballot_name = validate.req_str(body, "ballot_name")
    filing_received_at = validate.req_ts(body, "filing_received_at")
    party_code = validate.opt_str(body, "party_code")
    contest = guards.find("contests", contest_id)
    election = guards.election_of_contest(contest)
    guards.require_phase(election, ("SETUP",))
    if contest["status"] != "DRAFT":
        fail("ERR_CONTEST_STATE_INVALID",
             "Contest state %s does not permit candidate filing." % contest["status"])
    row = store.insert("candidates", {
        "contest_id": contest_id,
        "full_name": full_name,
        "ballot_name": ballot_name,
        "party_code": party_code,
        "filing_received_at": util.fmt_ts(filing_received_at),
        "status": "FILED",
        "base_order_index": None,
        "disqualified_reason": None,
    })
    return envelope.created(serial.candidate(row))


@bp.get("/contests/<contest_id>/candidates")
def list_candidates(contest_id):
    auth.require_any()
    limit, offset = validate.pagination()
    status = validate.query_enum("status", ("FILED", "CERTIFIED", "DISQUALIFIED"))
    guards.find("contests", contest_id)
    rows = store.candidates_of(contest_id)
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["base_order_index"] is None,
                             r["base_order_index"] if r["base_order_index"] is not None else 0,
                             r["created_at"], r["_seq"]))
    page, total = validate.paginate(rows, limit, offset)
    return envelope.ok_list([serial.candidate(r) for r in page], limit, offset, total)


@bp.post("/candidates/<candidate_id>/disqualify")
def disqualify_candidate(candidate_id):
    auth.require(auth.ELECTIONS_DIRECTOR)
    body = validate.body()
    disqualified_reason = validate.req_str(body, "disqualified_reason")
    candidate = guards.find("candidates", candidate_id)
    contest = guards.contest_of_candidate(candidate)
    election = guards.election_of_contest(contest)
    guards.require_phase(election, ("SETUP", "CONTESTS_CERTIFIED", "STYLES_LOCKED"))
    if candidate["status"] == "DISQUALIFIED":
        fail("ERR_CANDIDATE_STATE_INVALID", "Candidate is already disqualified.")
    if candidate["status"] == "FILED":
        if election["status"] != "SETUP":
            fail("ERR_ELECTION_PHASE_INVALID",
                 "Election phase %s does not permit disqualifying a filed candidate."
                 % election["status"])
        if contest["status"] != "DRAFT":
            fail("ERR_CONTEST_STATE_INVALID",
                 "Contest state %s does not permit this operation." % contest["status"])
        store.setf(candidate, status="DISQUALIFIED", disqualified_reason=disqualified_reason)
        return envelope.ok(serial.candidate(candidate))
    if contest["status"] != "CERTIFIED":
        fail("ERR_CONTEST_STATE_INVALID",
             "Contest state %s does not permit this operation." % contest["status"])
    store.setf(candidate, status="DISQUALIFIED", disqualified_reason=disqualified_reason,
               base_order_index=None)
    derive.recompute_certified_candidate_count(contest)
    derive.cascade_candidate_disqualified(candidate, contest, election)
    return envelope.ok(serial.candidate(candidate))
