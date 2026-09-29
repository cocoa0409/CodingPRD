"""Job description inventory (PRD 3.2)."""
from flask import Blueprint

import db
from constants import ALL_ROLES, CLAIMED_EXEMPTION_TESTS, FLS_STATUSES, SALARY_BASES
from errors import fail
from middleware import body, endpoint, pagination
from response import success, success_list
from services import derive, lookup, serialize
from validation import opt_bool, req_enum, req_int, req_num, req_state_code, req_str

bp = Blueprint("positions", __name__)

RESTRICTED_TIERS = ("HIGH", "CRITICAL")


@bp.post("/positions")
@endpoint(["ProgramAdmin"])
def create_position():
    payload = body()
    family_id = req_str(payload, "job_family_id")
    title = req_str(payload, "title")
    job_code = req_str(payload, "job_code")
    current_fls_status = req_enum(payload, "current_fls_status", FLS_STATUSES)
    claimed_test = req_enum(payload, "claimed_exemption_test", CLAIMED_EXEMPTION_TESTS)
    annual_salary_cents = req_int(payload, "annual_salary_cents", minimum=1)
    salary_basis = req_enum(payload, "salary_basis", SALARY_BASES)
    work_state_code = req_state_code(payload, "work_state_code")
    incumbent_count = req_int(payload, "incumbent_count", minimum=1)
    avg_weekly_hours = req_num(payload, "avg_weekly_hours", minimum=0, maximum=168)
    requires_advanced_degree = opt_bool(payload, "requires_advanced_degree", default=False)
    works_primarily_offsite = opt_bool(payload, "works_primarily_offsite", default=False)

    # rank 5: foreign keys
    family = lookup.family(family_id)
    project = derive.project_of_family(family)

    # rank 6: engagement posture (PRD 2.12)
    posture = derive.remediation_posture(project) if project else "OPEN"
    if posture == "FROZEN":
        fail("ERR_PROJECT_POSTURE_FROZEN")
    if posture == "RESTRICTED":
        if derive.family_view(family)["risk_tier"] in RESTRICTED_TIERS:
            fail("ERR_POSTURE_RESTRICTED_FAMILY")

    # rank 13: job_code unique within the family
    for existing in derive.positions_of_family(family["id"]):
        if existing["job_code"] == job_code:
            fail("ERR_DUPLICATE_CODE")

    row = db.make_row(
        job_family_id=family["id"],
        title=title,
        job_code=job_code,
        current_fls_status=current_fls_status,
        claimed_exemption_test=claimed_test,
        annual_salary_cents=annual_salary_cents,
        salary_basis=salary_basis,
        work_state_code=work_state_code,
        incumbent_count=incumbent_count,
        avg_weekly_hours=avg_weekly_hours,
        requires_advanced_degree=requires_advanced_degree,
        works_primarily_offsite=works_primarily_offsite,
        self_reported_exempt_pct_override=None,
        classification_status="UNREVIEWED",
    )
    db.positions[row["id"]] = row

    # the family risk figures and the engagement posture move with the new row
    db.touch(family)
    if project is not None:
        db.touch(project)
    return success(serialize.position(row), 201)


@bp.get("/positions/<position_id>")
@endpoint(ALL_ROLES)
def get_position(position_id):
    position = lookup.position(position_id)
    return success(serialize.position(position), 200)


def _sub_list(position_id, rows_fn, serializer):
    position = lookup.position(position_id)
    limit, offset = pagination()
    rows = rows_fn(position["id"])
    items, total = serialize.paginate(rows, limit, offset, serializer)
    return success_list(items, limit, offset, total)


@bp.get("/positions/<position_id>/duty-statements")
@endpoint(ALL_ROLES)
def list_duty_statements(position_id):
    return _sub_list(position_id, derive.duty_statements_of, serialize.duty_statement)


@bp.get("/positions/<position_id>/interviews")
@endpoint(ALL_ROLES)
def list_interviews(position_id):
    return _sub_list(position_id, derive.interviews_of, serialize.interview)


@bp.get("/positions/<position_id>/exemption-analyses")
@endpoint(ALL_ROLES)
def list_analyses(position_id):
    def rows_fn(pid):
        return db.ordered(
            [a for a in db.exemption_analyses.values() if a["position_id"] == pid]
        )

    return _sub_list(position_id, rows_fn, serialize.exemption_analysis)


@bp.get("/positions/<position_id>/reclassification-cases")
@endpoint(ALL_ROLES)
def list_cases(position_id):
    def rows_fn(pid):
        return db.ordered(
            [c for c in db.reclassification_cases.values() if c["position_id"] == pid]
        )

    return _sub_list(position_id, rows_fn, serialize.reclassification_case)


@bp.get("/positions/<position_id>/job-change-triggers")
@endpoint(ALL_ROLES)
def list_triggers(position_id):
    def rows_fn(pid):
        return db.ordered(
            [t for t in db.job_change_triggers.values() if t["position_id"] == pid]
        )

    return _sub_list(position_id, rows_fn, serialize.job_change_trigger)
