"""Routes: reports (review cycle + PE sealing), observation visits,
changed-condition claims, exploration authorizations, and the logical clock."""

from flask import Blueprint, g, request

import calc
import serialize
from db import fmt_dt, parse_dt, store
from errors import err
from helpers import (
    forbid_role,
    get_body,
    opt_num,
    opt_str,
    paginate,
    req_dt,
    req_enum,
    req_int,
    req_str,
    require_roles,
    sorted_items,
)
from response import success

bp = Blueprint("closeout", __name__)

REPORT_STATES = {"DRAFT", "TECH_REVIEW", "PE_REVIEW", "ISSUED", "SUPERSEDED"}
REPORT_TRANSITIONS = {
    ("DRAFT", "TECH_REVIEW"): "SeniorEngineer",
    ("TECH_REVIEW", "DRAFT"): "ProjectManager",
    ("TECH_REVIEW", "PE_REVIEW"): "ProjectManager",
    ("PE_REVIEW", "DRAFT"): "PrincipalEngineer",
}

VISIT_STATES = {"SCHEDULED", "PERFORMED", "FINDINGS_FILED", "CLOSED"}
VISIT_TRANSITIONS = {
    ("SCHEDULED", "PERFORMED"): "StaffEngineer",
    ("PERFORMED", "FINDINGS_FILED"): "StaffEngineer",
    ("FINDINGS_FILED", "CLOSED"): "ProjectManager",
}
FINDINGS_VALUES = {"CONSISTENT", "MARGINAL", "DIFFERING"}

CLAIM_STATES = {"SUBMITTED", "UNDER_REVIEW", "SUBSTANTIATED", "REBUTTED", "SETTLED"}
CLAIM_TRANSITIONS = {
    ("SUBMITTED", "UNDER_REVIEW"): "SeniorEngineer",
    ("UNDER_REVIEW", "SUBSTANTIATED"): "SeniorEngineer",
    ("UNDER_REVIEW", "REBUTTED"): "SeniorEngineer",
    ("REBUTTED", "UNDER_REVIEW"): "SeniorEngineer",  # single-appeal loop
    ("SUBSTANTIATED", "SETTLED"): "ProjectManager",
}

AUTH_STATES = {"PROPOSED", "APPROVED", "REVOKED", "EXHAUSTED"}
AUTH_TRANSITIONS = {
    ("PROPOSED", "APPROVED"): "ClientRep",
    ("APPROVED", "REVOKED"): "ClientRep",
}

AUTO_CLAIM_BASIS = "Auto-opened from differing-site-condition finding"


def get_project_or_404(pid):
    rec = store.projects.get(pid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "Project %s not found" % pid)
    return rec


def get_report_or_404(rid):
    rec = store.reports.get(rid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "Report %s not found" % rid)
    return rec


def get_visit_or_404(vid):
    rec = store.visits.get(vid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "ObservationVisit %s not found" % vid)
    return rec


def get_claim_or_404(cid):
    rec = store.claims.get(cid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "ChangedConditionClaim %s not found" % cid)
    return rec


def get_auth_or_404(aid):
    rec = store.auths.get(aid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "ExplorationAuthorization %s not found" % aid)
    return rec


def _clientrep_owns(project):
    if g.role == "ClientRep" and project["client_id"] != g.user_id:
        raise forbid_role("ClientRep does not own this project")


def _verified_analysis(project_id):
    cands = [
        a
        for a in store.analyses.values()
        if a["project_id"] == project_id and a["status"] == "VERIFIED"
    ]
    if not cands:
        return None
    return max(cands, key=lambda a: a["_seq"])


def _snapshot_baseline(project_id):
    analysis = _verified_analysis(project_id)
    if analysis is None:
        return None
    return analysis["bearing_capacity_final_psf"]


def _create_claim(project_id, claimed_amount_cents, basis_text, observation_visit_id):
    rec = {
        "id": store.new_id(),
        "project_id": project_id,
        "observation_visit_id": observation_visit_id,
        "claimed_amount_cents": claimed_amount_cents,
        "basis_text": basis_text,
        "baseline_bearing_psf": _snapshot_baseline(project_id),
        "quantum_report_baseline_cents": None,
        "quantum_site_observed_cents": None,
        "awarded_amount_cents": None,
        "appeal_count": 0,
        "status": "SUBMITTED",
    }
    store.stamp(rec)
    store.claims[rec["id"]] = rec
    return rec


# --------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------
@bp.route("/geo/projects/<pid>/reports", methods=["POST"])
@require_roles("SeniorEngineer")
def create_report(pid):
    project = get_project_or_404(pid)
    get_body()  # creation takes no body fields
    if project["status"] != "REPORT_REVIEW":
        raise err(
            "ERR_PROJECT_STATE_FORBIDS",
            "Reports may only be created while the project is in REPORT_REVIEW",
        )
    siblings = [r for r in store.reports.values() if r["project_id"] == pid]
    revision_no = max((r["revision_no"] for r in siblings), default=0) + 1
    rec = {
        "id": store.new_id(),
        "project_id": pid,
        "revision_no": revision_no,
        "prepared_by_user_id": g.user_id,
        "sealed_by_pe_user_id": None,
        "sealed_at": None,
        "status": "DRAFT",
    }
    store.stamp(rec)
    store.reports[rec["id"]] = rec
    return success(serialize.report(rec), code=201)


@bp.route("/geo/reports/<rid>", methods=["GET"])
@require_roles("FirmAdmin", "ProjectManager", "SeniorEngineer", "PrincipalEngineer", "ClientRep")
def get_report(rid):
    rec = get_report_or_404(rid)
    if g.role == "ClientRep":
        _clientrep_owns(store.projects[rec["project_id"]])
    return success(serialize.report(rec))


@bp.route("/geo/reports", methods=["GET"])
@require_roles("FirmAdmin", "ProjectManager", "SeniorEngineer", "PrincipalEngineer", "ClientRep")
def list_reports():
    items = list(store.reports.values())
    project_id = request.args.get("project_id")
    if project_id is not None:
        items = [r for r in items if r["project_id"] == project_id]
    if g.role == "ClientRep":
        own = {p["id"] for p in store.projects.values() if p["client_id"] == g.user_id}
        items = [r for r in items if r["project_id"] in own]
    page, meta = paginate(sorted_items(items))
    return success([serialize.report(r) for r in page], "array", 200, meta)


@bp.route("/geo/reports/<rid>/transition", methods=["POST"])
@require_roles("SeniorEngineer", "ProjectManager", "PrincipalEngineer")
def report_transition(rid):
    rec = get_report_or_404(rid)
    body = get_body()
    to = req_enum(body, "to", REPORT_STATES)
    transition = (rec["status"], to)
    actor = REPORT_TRANSITIONS.get(transition)
    if actor is None:
        raise err(
            "ERR_INVALID_STATE",
            "Report in %s cannot transition to %s" % (rec["status"], to),
        )
    if g.role != actor:
        raise forbid_role("Transition to %s requires role %s" % (to, actor))
    rec["status"] = to
    store.bump(rec)
    return success(serialize.report(rec))


@bp.route("/geo/reports/<rid>/issue", methods=["POST"])
@require_roles("PrincipalEngineer")
def issue_report(rid):
    rec = get_report_or_404(rid)
    body = get_body()
    expected_report_version = req_int(body, "expected_report_version")
    if rec["status"] != "PE_REVIEW":
        raise err("ERR_INVALID_STATE", "Only a report in PE_REVIEW may be issued")
    project = store.projects[rec["project_id"]]
    analysis = _verified_analysis(rec["project_id"])
    if analysis is None:
        raise err(
            "ERR_ANALYSIS_NOT_VERIFIED",
            "No VERIFIED FoundationAnalysis exists for the project",
        )
    if analysis["data_status"] != "CURRENT":
        raise err("ERR_ANALYSIS_DATA_STALE", "The VERIFIED analysis has STALE data")
    if any(
        o["project_id"] == rec["project_id"] and o["status"] != "ACCEPTED"
        for o in store.orders.values()
    ):
        raise err(
            "ERR_ORDER_STATE_FORBIDS",
            "Every LabTestOrder of the project must be ACCEPTED",
        )
    # OCC guard (PRD 2.7): the issuer's view of the review state must be current.
    if expected_report_version != rec["version"]:
        raise err(
            "ERR_STALE_REPORT_VERSION",
            "expected_report_version does not match the report's current version",
        )
    # Segregation of duties: the sealing PE must not be the preparer.
    if g.user_id == rec["prepared_by_user_id"]:
        raise err(
            "ERR_SOD_PE_IS_PREPARER",
            "The issuing PrincipalEngineer must differ from the report preparer",
        )

    rec["sealed_by_pe_user_id"] = g.user_id
    rec["sealed_at"] = store.now_iso()
    rec["status"] = "ISSUED"
    for other in store.reports.values():
        if (
            other["project_id"] == rec["project_id"]
            and other["id"] != rec["id"]
            and other["status"] == "ISSUED"
        ):
            other["status"] = "SUPERSEDED"
            store.bump(other)
    store.bump(rec)
    store.touch(project)
    return success(serialize.report(rec))


# --------------------------------------------------------------------------
# Observation visits
# --------------------------------------------------------------------------
@bp.route("/geo/projects/<pid>/observation-visits", methods=["POST"])
@require_roles("ProjectManager")
def create_observation_visit(pid):
    project = get_project_or_404(pid)
    body = get_body()
    visit_date_raw, visit_date = req_dt(body, "visit_date")
    if project["status"] != "CONSTRUCTION_SUPPORT":
        raise err(
            "ERR_PROJECT_STATE_FORBIDS",
            "Observation visits require the project in CONSTRUCTION_SUPPORT",
        )
    rec = {
        "id": store.new_id(),
        "project_id": pid,
        "visit_date": visit_date_raw,
        "_visit_date": visit_date,
        "findings": None,
        "observed_bearing_psf": None,
        "status": "SCHEDULED",
    }
    store.stamp(rec)
    store.visits[rec["id"]] = rec
    return success(serialize.observation_visit(rec), code=201)


@bp.route("/geo/observation-visits/<vid>", methods=["GET"])
@require_roles("FirmAdmin", "ProjectManager", "StaffEngineer", "SeniorEngineer")
def get_observation_visit(vid):
    return success(serialize.observation_visit(get_visit_or_404(vid)))


@bp.route("/geo/observation-visits", methods=["GET"])
@require_roles("FirmAdmin", "ProjectManager", "StaffEngineer", "SeniorEngineer")
def list_observation_visits():
    items = list(store.visits.values())
    project_id = request.args.get("project_id")
    if project_id is not None:
        items = [v for v in items if v["project_id"] == project_id]
    page, meta = paginate(sorted_items(items))
    return success([serialize.observation_visit(v) for v in page], "array", 200, meta)


@bp.route("/geo/observation-visits/<vid>/transition", methods=["POST"])
@require_roles("StaffEngineer", "ProjectManager")
def observation_visit_transition(vid):
    rec = get_visit_or_404(vid)
    body = get_body()
    to = req_enum(body, "to", VISIT_STATES)
    transition = (rec["status"], to)
    actor = VISIT_TRANSITIONS.get(transition)
    if actor is None:
        raise err(
            "ERR_INVALID_STATE",
            "ObservationVisit in %s cannot transition to %s" % (rec["status"], to),
        )
    if g.role != actor:
        raise forbid_role("Transition to %s requires role %s" % (to, actor))

    project = store.projects[rec["project_id"]]
    payload = {}
    if to == "FINDINGS_FILED":
        payload["findings"] = req_enum(body, "findings", FINDINGS_VALUES)
        payload["observed_bearing_psf"] = opt_num(body, "observed_bearing_psf", None, min_v=0)

    if to == "PERFORMED":
        if project["status"] != "CONSTRUCTION_SUPPORT":
            raise err(
                "ERR_PROJECT_STATE_FORBIDS",
                "Visits may only be performed under CONSTRUCTION_SUPPORT",
            )
        if not store.clock >= rec["_visit_date"]:
            raise err(
                "ERR_VISIT_DATE_FUTURE",
                "The visit cannot be performed before its visit_date",
            )
    elif to == "FINDINGS_FILED":
        rec["findings"] = payload["findings"]
        rec["observed_bearing_psf"] = payload["observed_bearing_psf"]

    rec["status"] = to
    store.bump(rec)

    # Claim-intake cascade link 1: DIFFERING findings auto-open a claim.
    if to == "FINDINGS_FILED" and rec["findings"] == "DIFFERING":
        _create_claim(rec["project_id"], 0, AUTO_CLAIM_BASIS, rec["id"])
        store.touch(project)
    return success(serialize.observation_visit(rec))


# --------------------------------------------------------------------------
# Changed-condition claims
# --------------------------------------------------------------------------
@bp.route("/geo/projects/<pid>/claims", methods=["POST"])
@require_roles("ProjectManager", "ClientRep")
def create_claim(pid):
    project = get_project_or_404(pid)
    _clientrep_owns(project)
    body = get_body()
    claimed_amount_cents = req_int(body, "claimed_amount_cents")
    basis_text = req_str(body, "basis_text")
    observation_visit_id = opt_str(body, "observation_visit_id")
    if claimed_amount_cents < 0:
        raise err("ERR_VALIDATION", "claimed_amount_cents must be non-negative")
    if project["status"] != "CONSTRUCTION_SUPPORT":
        raise err(
            "ERR_PROJECT_STATE_FORBIDS",
            "Claims may only be filed under CONSTRUCTION_SUPPORT",
        )
    # Category 9: the linked visit must resolve to a visit of this project.
    if observation_visit_id is not None:
        visit = store.visits.get(observation_visit_id)
        if visit is None or visit["project_id"] != pid:
            raise err(
                "ERR_VISIT_PROJECT_MISMATCH",
                "observation_visit_id does not resolve to a visit of this project",
            )
    # Category 10: manual filings must carry at least 1 cent.
    if claimed_amount_cents < 1:
        raise err(
            "ERR_CLAIM_AMOUNT_INVALID",
            "Manually filed claims must carry claimed_amount_cents >= 1",
        )
    rec = _create_claim(pid, claimed_amount_cents, basis_text, observation_visit_id)
    return success(serialize.claim(rec), code=201)


@bp.route("/geo/claims/<cid>", methods=["GET"])
@require_roles("FirmAdmin", "ProjectManager", "SeniorEngineer", "ClientRep")
def get_claim(cid):
    rec = get_claim_or_404(cid)
    if g.role == "ClientRep":
        _clientrep_owns(store.projects[rec["project_id"]])
    return success(serialize.claim(rec))


@bp.route("/geo/claims", methods=["GET"])
@require_roles("FirmAdmin", "ProjectManager", "SeniorEngineer", "ClientRep")
def list_claims():
    items = list(store.claims.values())
    project_id = request.args.get("project_id")
    if project_id is not None:
        items = [c for c in items if c["project_id"] == project_id]
    observation_visit_id = request.args.get("observation_visit_id")
    if observation_visit_id is not None:
        items = [c for c in items if c["observation_visit_id"] == observation_visit_id]
    if g.role == "ClientRep":
        own = {p["id"] for p in store.projects.values() if p["client_id"] == g.user_id}
        items = [c for c in items if c["project_id"] in own]
    page, meta = paginate(sorted_items(items))
    return success([serialize.claim(c) for c in page], "array", 200, meta)


@bp.route("/geo/claims/<cid>/transition", methods=["POST"])
@require_roles("SeniorEngineer", "ProjectManager")
def claim_transition(cid):
    rec = get_claim_or_404(cid)
    body = get_body()
    to = req_enum(body, "to", CLAIM_STATES)
    transition = (rec["status"], to)
    actor = CLAIM_TRANSITIONS.get(transition)
    if actor is None:
        raise err(
            "ERR_INVALID_STATE",
            "ChangedConditionClaim in %s cannot transition to %s" % (rec["status"], to),
        )
    if g.role != actor:
        raise forbid_role("Transition to %s requires role %s" % (to, actor))

    awarded = None
    if to == "SETTLED":
        awarded = req_int(body, "awarded_amount_cents")
        if awarded < 0:
            raise err("ERR_VALIDATION", "awarded_amount_cents must be non-negative")

    if transition == ("UNDER_REVIEW", "SUBSTANTIATED"):
        if rec["baseline_bearing_psf"] is None:
            raise err(
                "ERR_ANALYSIS_NOT_VERIFIED",
                "No VERIFIED-analysis baseline bearing snapshot exists",
            )
    elif transition == ("REBUTTED", "UNDER_REVIEW"):
        if rec["appeal_count"] >= calc.APPEAL_MAX:
            raise err("ERR_APPEAL_LIMIT", "appeal_count is at the cap of 1")

    if to == "UNDER_REVIEW":
        rb, so = calc.claim_quanta(rec)
        rec["quantum_report_baseline_cents"] = rb
        rec["quantum_site_observed_cents"] = so
        if rec["status"] == "REBUTTED":
            rec["appeal_count"] += 1
    elif to == "SETTLED":
        rec["awarded_amount_cents"] = awarded

    rec["status"] = to
    store.bump(rec)
    # Exposure and posture rollups recompute; refresh the parent's updated_at.
    store.touch(store.projects[rec["project_id"]])
    return success(serialize.claim(rec))


# --------------------------------------------------------------------------
# Exploration authorizations
# --------------------------------------------------------------------------
@bp.route("/geo/projects/<pid>/exploration-authorizations", methods=["POST"])
@require_roles("ProjectManager")
def create_exploration_authorization(pid):
    project = get_project_or_404(pid)
    body = get_body()
    authorized_amount_cents = req_int(body, "authorized_amount_cents", min_v=0)
    extra_boring_count = req_int(body, "extra_boring_count", min_v=0)
    if project["status"] != "FIELDWORK":
        raise err(
            "ERR_PROJECT_STATE_FORBIDS",
            "Exploration authorizations may only be proposed under FIELDWORK",
        )
    rec = {
        "id": store.new_id(),
        "project_id": pid,
        "authorized_amount_cents": authorized_amount_cents,
        "extra_boring_count": extra_boring_count,
        "consumed_boring_count": 0,
        "status": "PROPOSED",
    }
    store.stamp(rec)
    store.auths[rec["id"]] = rec
    return success(serialize.exploration_authorization(rec), code=201)


@bp.route("/geo/exploration-authorizations/<aid>", methods=["GET"])
@require_roles("FirmAdmin", "ProjectManager", "ClientRep")
def get_exploration_authorization(aid):
    rec = get_auth_or_404(aid)
    if g.role == "ClientRep":
        _clientrep_owns(store.projects[rec["project_id"]])
    return success(serialize.exploration_authorization(rec))


@bp.route("/geo/exploration-authorizations", methods=["GET"])
@require_roles("FirmAdmin", "ProjectManager", "ClientRep")
def list_exploration_authorizations():
    items = list(store.auths.values())
    project_id = request.args.get("project_id")
    if project_id is not None:
        items = [a for a in items if a["project_id"] == project_id]
    if g.role == "ClientRep":
        own = {p["id"] for p in store.projects.values() if p["client_id"] == g.user_id}
        items = [a for a in items if a["project_id"] in own]
    page, meta = paginate(sorted_items(items))
    return success([serialize.exploration_authorization(a) for a in page], "array", 200, meta)


@bp.route("/geo/exploration-authorizations/<aid>/transition", methods=["POST"])
@require_roles("ClientRep")
def exploration_authorization_transition(aid):
    rec = get_auth_or_404(aid)
    body = get_body()
    to = req_enum(body, "to", AUTH_STATES)
    expected_project_version = req_int(body, "expected_project_version")
    transition = (rec["status"], to)
    actor = AUTH_TRANSITIONS.get(transition)
    if actor is None:
        # EXHAUSTED is system-only; the rest are wrong-from transitions.
        raise err(
            "ERR_INVALID_STATE",
            "ExplorationAuthorization in %s cannot transition to %s"
            % (rec["status"], to),
        )
    if g.role != actor:
        raise forbid_role("Transition to %s requires role %s" % (to, actor))
    project = store.projects[rec["project_id"]]
    _clientrep_owns(project)

    if to == "REVOKED" and rec["consumed_boring_count"] != 0:
        raise err(
            "ERR_INVALID_STATE",
            "An authorization with consumed borings cannot be revoked",
        )
    # OCC (category 5): the committed-total check must use a current view.
    if expected_project_version != project["version"]:
        raise err(
            "ERR_STALE_PROJECT_VERSION",
            "expected_project_version does not match the project's current version",
        )
    if to == "APPROVED":
        # Inclusive boundary: a total exactly equal to the cap passes.
        committed = calc.compute_additional_committed(rec["project_id"])
        if committed + rec["authorized_amount_cents"] > project["additional_auth_cap_cents"]:
            raise err(
                "ERR_AUTH_CAP_EXCEEDED",
                "Approval would exceed the project's additional_auth_cap_cents",
            )

    rec["status"] = to
    store.bump(rec)
    # Approval/revocation mutates the committed rollup: bump the Project.
    store.bump(project)
    return success(serialize.exploration_authorization(rec))


# --------------------------------------------------------------------------
# Logical clock (test-driving capability)
# --------------------------------------------------------------------------
@bp.route("/geo/_clock/set_current_utc", methods=["POST"])
@require_roles("FirmAdmin")
def set_current_utc():
    body = get_body()
    _, new_now = req_dt(body, "to_iso8601")
    store.clock = new_now
    # Expiry sweep: tickets in FILED/CLEARED strictly past expires_on -> EXPIRED.
    for c in store.clearances.values():
        if c["status"] in ("FILED", "CLEARED") and store.clock > c["_expires_on"]:
            c["status"] = "EXPIRED"
            store.bump(c)
    return success({}, "object", 200)
