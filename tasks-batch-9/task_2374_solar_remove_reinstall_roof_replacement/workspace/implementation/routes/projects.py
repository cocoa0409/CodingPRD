"""Projects, consent (PartyApproval), warranty notice and credit settlement."""

import calc
import errors as E
import services
from errors import ApiError
from flask import Blueprint, g
from db import db, new_row, touch
from middleware import endpoint
from response import ok, ok_row
from routes.helpers import (
    APPROVAL_STATUSES,
    OWNERSHIP_MODELS,
    POSTURES,
    PROJECT_PHASES,
    get_approval,
    get_party,
    get_project,
    invalid_state,
    paged,
    party_type_mismatch,
    resolve_fk,
)
from validation import (
    enum_field,
    enum_query,
    get_body,
    int_field,
    num_field,
    str_field,
    str_query,
)

bp = Blueprint("projects", __name__)

READ_ROLES = (
    "ProjectCoordinator",
    "SolarContractor",
    "RoofingContractor",
    "SolarOwner",
    "SystemOwner",
)
READ_ROLES_WITH_AHJ = READ_ROLES + ("AHJInspector",)
APPROVAL_READ_ROLES = (
    "ProjectCoordinator",
    "RoofingContractor",
    "SolarOwner",
    "SystemOwner",
)
APPROVAL_PARTY_TYPES = ("ROOFER", "SOLAR_OWNER", "SYSTEM_OWNER")
PARTY_SLOT_FOR_TYPE = {
    "ROOFER": "roofer_party_id",
    "SOLAR_OWNER": "solar_owner_party_id",
    "SYSTEM_OWNER": "system_owner_party_id",
}


def check_project_version(body, project):
    """Validation priority 7 (the comparison only; presence is priority 5)."""
    expected = body["expected_project_version"]
    if expected != project["version"]:
        raise ApiError(
            E.ERR_STALE_PROJECT_VERSION,
            "expected_project_version %s does not match current version %s"
            % (expected, project["version"]),
            412,
        )


# --------------------------------------------------------------------------
# ReroofProject
# --------------------------------------------------------------------------
@bp.route("/reroof/projects", methods=["POST"])
@endpoint("ProjectCoordinator")
def create_project():
    body = get_body()

    roofer = resolve_fk(body, "roofer_party_id", get_party)
    solar_owner = resolve_fk(body, "solar_owner_party_id", get_party)
    solar_contractor = resolve_fk(body, "solar_contractor_party_id", get_party)
    system_owner = resolve_fk(body, "system_owner_party_id", get_party)

    site_address = str_field(body, "site_address", required=True)
    ownership_model = enum_field(body, "ownership_model", OWNERSHIP_MODELS, required=True)
    system_dc_kw = num_field(body, "system_dc_kw", required=True, exclusive_min=0)
    roofer_party_id = str_field(body, "roofer_party_id", required=True)
    solar_owner_party_id = str_field(body, "solar_owner_party_id", required=True)
    solar_contractor_party_id = str_field(
        body, "solar_contractor_party_id", required=True
    )
    system_owner_party_id = str_field(
        body, "system_owner_party_id", required=False, default=None
    )
    baseline_daily_kwh = num_field(body, "baseline_daily_kwh", required=True, exclusive_min=0)
    downtime_days_estimated = int_field(
        body, "downtime_days_estimated", required=True, minimum=1
    )
    upgrade_budget_cents = int_field(body, "upgrade_budget_cents", required=True, minimum=0)

    # Priority 17: party-type suitability of every referenced party.
    if roofer["party_type"] != "ROOFER":
        raise party_type_mismatch("roofer_party_id must reference a ROOFER party")
    if solar_owner["party_type"] != "SOLAR_OWNER":
        raise party_type_mismatch("solar_owner_party_id must reference a SOLAR_OWNER party")
    if solar_contractor["party_type"] != "SOLAR_CONTRACTOR":
        raise party_type_mismatch(
            "solar_contractor_party_id must reference a SOLAR_CONTRACTOR party"
        )
    if ownership_model == "HOST_OWNED":
        if system_owner_party_id is not None:
            raise party_type_mismatch(
                "system_owner_party_id must be absent on a HOST_OWNED project"
            )
    else:
        if system_owner_party_id is None:
            raise party_type_mismatch(
                "system_owner_party_id is required on a %s project" % ownership_model
            )
    if system_owner is not None and system_owner["party_type"] != "SYSTEM_OWNER":
        raise party_type_mismatch(
            "system_owner_party_id must reference a SYSTEM_OWNER party"
        )

    project = new_row(
        {
            "site_address": site_address,
            "ownership_model": ownership_model,
            "system_dc_kw": system_dc_kw,
            "roofer_party_id": roofer_party_id,
            "solar_owner_party_id": solar_owner_party_id,
            "solar_contractor_party_id": solar_contractor_party_id,
            "system_owner_party_id": system_owner_party_id,
            "baseline_daily_kwh": baseline_daily_kwh,
            "downtime_days_estimated": downtime_days_estimated,
            "upgrade_budget_cents": upgrade_budget_cents,
            "phase": "INTAKE",
            "posture": "OPEN",
            "negotiation_round": 1,
            "required_approval_party_count": 3 if system_owner_party_id else 2,
            "authorized_at": None,
            "deenergized_at": None,
            "reenergized_at": None,
            "warranty_notice_status": (
                "NOT_REQUIRED" if ownership_model == "HOST_OWNED" else "PENDING"
            ),
            "warranty_notice_filed_at": None,
            "warranty_notice_reference": None,
            "warranty_preserved": True,
            "provisional_credit_cents": 0,
            "final_credit_cents": 0,
            "credit_authorized_cents": 0,
            "credit_reserved_cents": 0,
            "credit_settled_cents": 0,
            "credit_released_cents": 0,
            "weather_abort_count": 0,
            "registered_unit_count": 0,
            "stored_unit_count": 0,
            "reinstalled_unit_count": 0,
            "scrapped_unit_count": 0,
            "damaged_unit_count": 0,
            "open_critical_finding_count": 0,
            "scoped_upgrade_cost_cents": 0,
            "downtime_days_actual": 0,
            "settlement_note": None,
        }
    )
    db.projects[project["id"]] = project
    return ok_row(project, 201)


@bp.route("/reroof/projects", methods=["GET"])
@endpoint(*READ_ROLES)
def list_projects():
    filters = {}
    for key in (
        "roofer_party_id",
        "solar_owner_party_id",
        "solar_contractor_party_id",
        "system_owner_party_id",
    ):
        value = str_query(key)
        if value is not None:
            filters[key] = value
    phase = enum_query("phase", PROJECT_PHASES)
    posture = enum_query("posture", POSTURES)

    rows = []
    for project in db.projects.values():
        if any(project.get(k) != v for k, v in filters.items()):
            continue
        if phase is not None and project["phase"] != phase:
            continue
        if posture is not None and project["posture"] != posture:
            continue
        rows.append(project)
    return paged(rows)


@bp.route("/reroof/projects/<project_id>", methods=["GET"])
@endpoint(*READ_ROLES_WITH_AHJ)
def read_project(project_id):
    return ok_row(get_project(project_id))


@bp.route("/reroof/projects/<project_id>/downtime-summary", methods=["GET"])
@endpoint("ProjectCoordinator", "SolarOwner", "SystemOwner")
def downtime_summary(project_id):
    project = get_project(project_id)
    return ok(
        {
            "project_id": project["id"],
            "downtime_days_actual": project["downtime_days_actual"],
            "provisional_credit_cents": project["provisional_credit_cents"],
            "final_credit_cents": project["final_credit_cents"],
            "credit_authorized_cents": project["credit_authorized_cents"],
            "credit_reserved_cents": project["credit_reserved_cents"],
            "credit_settled_cents": project["credit_settled_cents"],
            "credit_released_cents": project["credit_released_cents"],
            "ledger_balanced": services.ledger_balanced(project),
        }
    )


@bp.route("/reroof/projects/<project_id>/warranty-notice", methods=["POST"])
@endpoint("ProjectCoordinator")
def file_warranty_notice(project_id):
    project = get_project(project_id)
    body = get_body()
    manufacturer = str_field(body, "manufacturer", required=True)
    notice_reference = str_field(body, "notice_reference", required=True)
    int_field(body, "expected_project_version", required=True)
    check_project_version(body, project)

    snapshot = services.project_snapshot(project)
    project["warranty_notice_status"] = "FILED"
    project["warranty_notice_filed_at"] = db.now()
    project["warranty_notice_reference"] = notice_reference
    services.rollup_project(project)
    services.commit_project(project, snapshot, force=True)
    return ok_row(project)


@bp.route("/reroof/projects/<project_id>/credit-settlement", methods=["POST"])
@endpoint("ProjectCoordinator")
def settle_credit(project_id):
    project = get_project(project_id)
    body = get_body()
    settlement_note = str_field(body, "settlement_note", required=False, default=None)

    if project["phase"] != "COMMISSIONED":
        raise ApiError(
            E.ERR_SETTLEMENT_NOT_READY,
            "project phase must be COMMISSIONED to settle, not %s" % project["phase"],
            409,
        )
    if not services.ledger_balanced(project):
        raise ApiError(
            E.ERR_CREDIT_LEDGER_UNBALANCED,
            "credit ledger identity does not hold for this project",
            409,
        )

    snapshot = services.project_snapshot(project)
    aborted = [
        w
        for w in services.project_windows(project["id"])
        if w["status"] == "WEATHER_ABORTED"
    ]
    final = calc.final_credit_cents(project, aborted)
    project["final_credit_cents"] = final
    difference = final - project["credit_reserved_cents"]
    if difference > 0:
        project["credit_authorized_cents"] += difference
    project["credit_settled_cents"] = final
    project["credit_reserved_cents"] = 0
    project["credit_released_cents"] = (
        project["credit_authorized_cents"] - project["credit_settled_cents"]
    )
    project["phase"] = "CLOSED"
    if settlement_note is not None:
        project["settlement_note"] = settlement_note
    services.rollup_project(project)
    services.commit_project(project, snapshot, force=True)
    return ok_row(project)


# --------------------------------------------------------------------------
# PartyApproval
# --------------------------------------------------------------------------
@bp.route("/reroof/projects/<project_id>/party-approvals", methods=["POST"])
@endpoint("ProjectCoordinator")
def create_approval(project_id):
    project = get_project(project_id)
    body = get_body()
    party = resolve_fk(body, "party_id", get_party)
    party_id = str_field(body, "party_id", required=True)

    # Priority 17
    if party["party_type"] not in APPROVAL_PARTY_TYPES:
        raise party_type_mismatch(
            "party_id must reference a ROOFER, SOLAR_OWNER or SYSTEM_OWNER party"
        )
    slot = PARTY_SLOT_FOR_TYPE[party["party_type"]]
    if project.get(slot) != party_id:
        raise party_type_mismatch(
            "party_id must equal the project's %s" % slot
        )

    # Priority 28
    for existing in services.project_approvals(project["id"]):
        if existing["party_id"] == party_id:
            raise ApiError(
                E.ERR_DUPLICATE_APPROVAL_PARTY,
                "a consent record already exists for this project and party",
                409,
            )

    snapshot = services.project_snapshot(project)
    first = len(services.project_approvals(project["id"])) == 0
    approval = new_row(
        {
            "project_id": project["id"],
            "party_id": party_id,
            "approval_role": party["party_type"],
            "status": "PENDING",
            "round_recorded": project["negotiation_round"],
            "change_request_count": 0,
            "veto_flag": False,
            "decided_at": None,
            "decision_note": None,
        }
    )
    db.approvals[approval["id"]] = approval

    if first and project["phase"] == "INTAKE":
        project["phase"] = "APPROVALS_OPEN"
    services.rollup_project(project)
    services.commit_project(project, snapshot)
    return ok_row(approval, 201)


@bp.route("/reroof/party-approvals", methods=["GET"])
@endpoint(*APPROVAL_READ_ROLES)
def list_approvals():
    project_id = str_query("project_id")
    party_id = str_query("party_id")
    status = enum_query("status", APPROVAL_STATUSES)
    rows = []
    for approval in db.approvals.values():
        if project_id is not None and approval["project_id"] != project_id:
            continue
        if party_id is not None and approval["party_id"] != party_id:
            continue
        if status is not None and approval["status"] != status:
            continue
        rows.append(approval)
    return paged(rows)


@bp.route("/reroof/party-approvals/<approval_id>", methods=["GET"])
@endpoint(*APPROVAL_READ_ROLES)
def read_approval(approval_id):
    return ok_row(get_approval(approval_id))


@bp.route("/reroof/party-approvals/<approval_id>/decision", methods=["POST"])
@endpoint("RoofingContractor", "SolarOwner", "SystemOwner")
def decide_approval(approval_id):
    approval = get_approval(approval_id)
    project = db.projects.get(approval["project_id"])
    body = get_body()
    decision = enum_field(body, "decision", ("APPROVE", "REQUEST_CHANGES"), required=True)
    decision_note = str_field(body, "decision_note", required=False, default=None)

    # Priority 6: only the party the record belongs to may decide it.
    if g.get("actor_id") != approval["party_id"]:
        raise ApiError(
            E.ERR_PARTY_NOT_ON_PROJECT,
            "only the consent record's own party may record its decision",
            403,
        )

    # Priority 8: transition legality then round freshness.
    if decision == "APPROVE":
        legal_from = ("PENDING", "CHANGES_REQUESTED")
    else:
        legal_from = ("PENDING", "APPROVED")
    if approval["status"] not in legal_from:
        raise invalid_state(
            "cannot record %s on a consent record in %s" % (decision, approval["status"])
        )
    if approval["round_recorded"] != project["negotiation_round"]:
        raise ApiError(
            E.ERR_APPROVAL_ROUND_STALE,
            "consent record was recorded against negotiation round %s but the project is on round %s"
            % (approval["round_recorded"], project["negotiation_round"]),
            409,
        )

    snapshot = services.project_snapshot(project)
    now = db.now()
    if decision_note is not None:
        approval["decision_note"] = decision_note

    if decision == "APPROVE":
        approval["status"] = "APPROVED"
        approval["decided_at"] = now
        approval["veto_flag"] = False
        touch(approval)
        services.rollup_project(project)
        services.evaluate_authorized(project)
    else:
        approval["status"] = "CHANGES_REQUESTED"
        approval["change_request_count"] += 1
        approval["decided_at"] = now
        is_veto = approval["approval_role"] == "SYSTEM_OWNER"
        if is_veto:
            approval["veto_flag"] = True

        project["negotiation_round"] += 1
        new_r = project["negotiation_round"]
        for sibling in services.project_approvals(project["id"]):
            if sibling["id"] == approval["id"]:
                continue
            if sibling["status"] == "APPROVED":
                sibling["status"] = "PENDING"
                sibling["round_recorded"] = new_r
                sibling["decided_at"] = None
                touch(sibling)
            elif sibling["status"] == "CHANGES_REQUESTED":
                sibling["status"] = "PENDING"
                sibling["round_recorded"] = new_r
                sibling["veto_flag"] = False
                touch(sibling)
        approval["round_recorded"] = new_r
        touch(approval)

        if is_veto and project["phase"] in ("AUTHORIZED", "DEENERGIZED"):
            was_deenergized = project["phase"] == "DEENERGIZED"
            project["phase"] = "APPROVALS_OPEN"
            services.revoke_scheduled_windows(project)
            if was_deenergized:
                services.release_reserved_credit(project)
        services.rollup_project(project)

    services.commit_project(project, snapshot)
    return ok_row(approval)
