from flask import Blueprint

from common import (
    API_PREFIX, db, new_entity, touch, serialize, object_response, paginate,
    sorted_rows, filter_equals, authenticate, json_body, get_contract,
    get_resource, check_contract_party, fail, req_id, req_string, req_int,
    req_date, require_contract_operational, windows_of_project,
    ALL_ROLES, ROLE_ADMIN, ROLE_MANAGER,
)

bp = Blueprint("projects", __name__)


@bp.route(API_PREFIX + "/projects", methods=["POST"])
def create_project():
    user_id, role = authenticate([ROLE_ADMIN])
    body = json_body()
    contract_id = req_id(body, "contract_id")
    contract = get_contract(contract_id)
    check_contract_party(contract, user_id, role)

    title = req_string(body, "title")
    budget_cents = req_int(body, "budget_cents", 1)
    req_date(body, "target_completion_date")

    require_contract_operational(contract)

    project = new_entity({
        "contract_id": contract_id,
        "title": title,
        "budget_cents": budget_cents,
        "target_completion_date": body["target_completion_date"],
        "status": "PLANNED",
        "approved_by_user_id": None,
        "window_count": 0,
    })
    db.projects[project["id"]] = project
    return object_response(serialize(project), 201)


@bp.route(API_PREFIX + "/projects/<project_id>", methods=["GET"])
def read_project(project_id):
    authenticate(ALL_ROLES)
    project = get_resource(db.projects, project_id)
    return object_response(serialize(project))


@bp.route(API_PREFIX + "/projects", methods=["GET"])
def list_projects():
    authenticate(ALL_ROLES)
    rows = sorted_rows(db.projects)
    rows = filter_equals(rows, "contract_id")
    rows = filter_equals(rows, "status")
    return paginate(rows)


@bp.route(API_PREFIX + "/projects/<project_id>/approve", methods=["POST"])
def approve_project(project_id):
    user_id, role = authenticate([ROLE_MANAGER])
    project = get_resource(db.projects, project_id)
    contract = db.contracts.get(project["contract_id"])
    if contract is not None:
        check_contract_party(contract, user_id, role)

    if project["status"] != "PLANNED":
        fail("ERR_INVALID_STATE_TRANSITION")
    require_contract_operational(contract)

    project["status"] = "APPROVED"
    project["approved_by_user_id"] = user_id
    touch(project)
    return object_response(serialize(project))


@bp.route(API_PREFIX + "/projects/<project_id>/complete", methods=["POST"])
def complete_project(project_id):
    user_id, role = authenticate([ROLE_ADMIN])
    project = get_resource(db.projects, project_id)
    contract = db.contracts.get(project["contract_id"])
    if contract is not None:
        check_contract_party(contract, user_id, role)

    if project["status"] not in ("APPROVED", "IN_PROGRESS", "AT_RISK"):
        fail("ERR_INVALID_STATE_TRANSITION")
    for window in windows_of_project(project["id"]):
        if window["status"] == "SCHEDULED":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "A scheduled downtime window still belongs to this project.")

    project["status"] = "COMPLETE"
    touch(project)
    return object_response(serialize(project))
