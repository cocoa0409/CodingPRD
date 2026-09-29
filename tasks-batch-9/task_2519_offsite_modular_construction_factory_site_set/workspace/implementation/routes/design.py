"""DesignPackage endpoints — the cyclic freeze review and the supersession cascade."""

from flask import Blueprint

import auth
import calc
import serialize
import services
import validate
from envelope import created, ok, ok_list, paginate
from errors import ApiError
from store import base_row, db, sorted_rows, touch

bp = Blueprint("design", __name__)

FREEZE_STATES = ("DRAFT", "IN_REVIEW", "REVISION_REQUIRED", "FROZEN", "SUPERSEDED")
DETAIL_STATES = ("NOT_STARTED", "FACTORY_DETAILED", "FIELD_COORDINATED", "COMPLETE")
DECISIONS = ("FREEZE", "RETURN_FOR_REVISION")


def _score(package):
    project = db.projects.get(package["project_id"])
    planned = project["planned_module_count"] if project else 0
    package["factory_compatibility_score"] = calc.compatibility_score(package, planned)
    return package["factory_compatibility_score"]


@bp.post("/modular/design-packages")
@auth.endpoint("DesignEngineer")
def create_package():
    data = validate.body(optional=False)
    project_id = validate.field_id(data, "project_id")
    revision_index = validate.field_int(data, "revision_index", minimum=1)
    module_split_count = validate.field_int(data, "module_split_count", minimum=1)
    expected_project_version = validate.field_int(
        data, "expected_project_version", minimum=0
    )
    connection_detail_state = validate.field_enum(
        data,
        "connection_detail_state",
        DETAIL_STATES,
        required=False,
        default="NOT_STARTED",
    )
    open_connection_conflicts = validate.field_int(
        data, "open_connection_conflicts", required=False, default=0, minimum=0
    )
    field_scope_items_open = validate.field_int(
        data, "field_scope_items_open", required=False, default=0, minimum=0
    )
    supersedes_package_id = validate.field_id(
        data, "supersedes_package_id", required=False
    )

    # rank 5 — body foreign keys, in the declared resolution order
    project = services.get_project(project_id)
    predecessor = None
    if supersedes_package_id is not None:
        predecessor = services.get_package(supersedes_package_id)

    # rank 9 — optimistic concurrency on the parent Project
    if expected_project_version != project["version"]:
        raise ApiError(
            "ERR_STALE_PROJECT_VERSION",
            "expected project version %s but current is %s"
            % (expected_project_version, project["version"]),
        )

    # rank 86 — a supersession must climb a legitimate revision chain
    if predecessor is not None:
        if (
            predecessor["project_id"] != project_id
            or predecessor["freeze_state"] != "FROZEN"
            or predecessor["revision_index"] >= revision_index
        ):
            raise ApiError(
                "ERR_INVALID_SUPERSESSION",
                "supersedes_package_id must be a FROZEN package of the same project "
                "with a strictly lower revision_index",
            )

    row = base_row()
    row.update(
        {
            "project_id": project_id,
            "revision_index": revision_index,
            "supersedes_package_id": supersedes_package_id,
            "freeze_state": "DRAFT",
            "revision_round": 0,
            "module_split_count": module_split_count,
            "connection_detail_state": connection_detail_state,
            "open_connection_conflicts": open_connection_conflicts,
            "field_scope_items_open": field_scope_items_open,
            "factory_compatibility_score": 0,
            "submitted_by_user_id": None,
            "reviewed_by_user_id": None,
            "review_note": None,
        }
    )
    _score(row)
    db.design_packages[row["id"]] = row

    services.refresh_project(project)
    touch(project)
    return created(serialize.design_package(row))


@bp.get("/modular/design-packages/<package_id>")
@auth.endpoint(
    "ProgramAdmin",
    "DesignEngineer",
    "FactoryProductionManager",
    "StateProgramOfficer",
    "AuthorityHavingJurisdiction",
)
def read_package(package_id):
    return ok(serialize.design_package(services.get_package(package_id)))


@bp.get("/modular/design-packages")
@auth.endpoint(
    "ProgramAdmin", "DesignEngineer", "FactoryProductionManager", "StateProgramOfficer"
)
def list_packages():
    project_id = validate.field_str_query("project_id")
    supersedes_package_id = validate.field_str_query("supersedes_package_id")
    freeze_state = validate.enum_query("freeze_state", FREEZE_STATES)
    connection_detail_state = validate.enum_query(
        "connection_detail_state", DETAIL_STATES
    )
    rows = sorted_rows(list(db.design_packages.values()))
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if supersedes_package_id is not None:
        rows = [r for r in rows if r["supersedes_package_id"] == supersedes_package_id]
    if freeze_state is not None:
        rows = [r for r in rows if r["freeze_state"] == freeze_state]
    if connection_detail_state is not None:
        rows = [
            r for r in rows if r["connection_detail_state"] == connection_detail_state
        ]
    page, meta = paginate(rows)
    return ok_list([serialize.design_package(r) for r in page], meta)


@bp.post("/modular/design-packages/<package_id>/submit")
@auth.endpoint("DesignEngineer")
def submit_package(package_id):
    data = validate.body()
    module_split_count = validate.field_int(
        data, "module_split_count", required=False, minimum=1
    )
    open_connection_conflicts = validate.field_int(
        data, "open_connection_conflicts", required=False, minimum=0
    )
    field_scope_items_open = validate.field_int(
        data, "field_scope_items_open", required=False, minimum=0
    )
    connection_detail_state = validate.field_enum(
        data, "connection_detail_state", DETAIL_STATES, required=False
    )
    review_note = validate.field_str(data, "review_note", required=False, allow_blank=True)

    row = services.get_package(package_id)

    # rank 39 — only one revision of a project may be in review at a time
    for sibling in services.packages_of_project(row["project_id"]):
        if sibling["id"] != row["id"] and sibling["freeze_state"] == "IN_REVIEW":
            raise ApiError(
                "ERR_DESIGN_REVIEW_IN_FLIGHT",
                "another design package of this project is already IN_REVIEW",
            )

    # rank 40
    if row["freeze_state"] not in ("DRAFT", "REVISION_REQUIRED"):
        raise ApiError(
            "ERR_DESIGN_NOT_SUBMITTABLE",
            "freeze_state %s cannot be submitted" % row["freeze_state"],
        )

    if module_split_count is not None:
        row["module_split_count"] = module_split_count
    if open_connection_conflicts is not None:
        row["open_connection_conflicts"] = open_connection_conflicts
    if field_scope_items_open is not None:
        row["field_scope_items_open"] = field_scope_items_open
    if connection_detail_state is not None:
        row["connection_detail_state"] = connection_detail_state
    if review_note is not None:
        row["review_note"] = review_note

    _score(row)
    row["freeze_state"] = "IN_REVIEW"
    row["revision_round"] += 1
    row["submitted_by_user_id"] = auth.user_id()
    touch(row)
    return ok(serialize.design_package(row))


@bp.post("/modular/design-packages/<package_id>/review-decision")
@auth.endpoint("DesignEngineer")
def review_decision(package_id):
    data = validate.body(optional=False)
    decision = validate.field_enum(data, "decision", DECISIONS)
    review_note = validate.field_str(data, "review_note", required=False, allow_blank=True)

    row = services.get_package(package_id)

    # rank 8 — segregation of duties
    if row["submitted_by_user_id"] is not None and row["submitted_by_user_id"] == auth.user_id():
        raise ApiError(
            "ERR_SAME_ACTOR_REVIEW",
            "the engineer who submitted this package may not review it",
        )

    # rank 41
    if row["freeze_state"] != "IN_REVIEW":
        raise ApiError(
            "ERR_DESIGN_NOT_IN_REVIEW",
            "freeze_state %s is not under review" % row["freeze_state"],
        )

    project = db.projects.get(row["project_id"])
    score = _score(row)

    if decision == "FREEZE":
        # rank 87 — the three-part freeze gate
        if (
            score < calc.FREEZE_MIN_SCORE
            or row["connection_detail_state"] == "NOT_STARTED"
            or (project is not None
                and row["module_split_count"] != project["planned_module_count"])
        ):
            raise ApiError(
                "ERR_FACTORY_COMPATIBILITY_TOO_LOW",
                "the revision is not detailed enough to freeze",
            )
        row["freeze_state"] = "FROZEN"
        row["reviewed_by_user_id"] = auth.user_id()
        if review_note is not None:
            row["review_note"] = review_note
        touch(row)
        if project is not None:
            services.supersession_cascade(row, project)
            services.refresh_project(project)
            touch(project)
        return ok(serialize.design_package(row))

    row["freeze_state"] = "REVISION_REQUIRED"
    row["reviewed_by_user_id"] = auth.user_id()
    if review_note is not None:
        row["review_note"] = review_note
    row["submitted_by_user_id"] = None
    touch(row)
    return ok(serialize.design_package(row))
