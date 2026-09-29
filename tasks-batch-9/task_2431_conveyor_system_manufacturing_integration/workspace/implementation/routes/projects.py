"""Project surface: opening, freezing, simulating, provisioning and reads."""

from flask import Blueprint

from auth import ALL_ROLES, authenticate
from errors import ApiError
from lookups import get_project
from response import list_response, object_response
from serializers import (
    acceptance_certificate_out,
    change_order_out,
    commissioning_ramp_out,
    project_out,
    segment_out,
    simulation_run_out,
    site_zone_out,
    spare_part_line_out,
)
from services import calculations as calc
from services.cascade import release_design_block
from store import (
    certificates_of,
    change_orders_of,
    iso,
    new_record,
    now,
    ramps_of,
    runs_of,
    segments_of,
    spare_lines_of,
    store,
    touch,
    zones_of,
)
from validate import (
    body,
    pagination,
    paginate,
    query_filter,
    query_int_filter,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("projects", __name__)

SERVICE_TIERS = ("BASIC", "PREMIUM", "CRITICAL")
SIMULATION_METHODS = ("DETERMINISTIC_STEADY_STATE", "DEGRADED_AVAILABILITY")


@bp.post("/projects")
def create_project():
    authenticate(("ProjectDirector",))
    data = body()

    customer_name = req_str(data, "customer_name")
    facility_code = req_str(data, "facility_code")
    customer_rep_user_id = req_str(data, "customer_rep_user_id")
    required_throughput_cph = req_int(data, "required_throughput_cph", minimum=1)
    contract_base_cents = req_int(data, "contract_base_cents", minimum=1)
    authorized_ceiling_cents = req_int(
        data, "authorized_ceiling_cents", minimum=contract_base_cents
    )
    spares_budget_cents = req_int(data, "spares_budget_cents", minimum=0)
    service_tier = req_enum(data, "service_tier", SERVICE_TIERS)

    project = new_record()
    project.update(
        {
            "customer_name": customer_name,
            "facility_code": facility_code,
            "customer_rep_user_id": customer_rep_user_id,
            "required_throughput_cph": required_throughput_cph,
            "contract_base_cents": contract_base_cents,
            "authorized_ceiling_cents": authorized_ceiling_cents,
            "spares_budget_cents": spares_budget_cents,
            "spares_allocated_cents": 0,
            "spares_unallocated_cents": spares_budget_cents,
            "service_tier": service_tier,
            "response_sla_minutes": calc.SLA_MINUTES_BY_TIER[service_tier],
            "design_version": 1,
            "delivery_status": "DESIGN",
            "commercial_status": "CLEAN",
            "legacy_share_bps": 10000,
            "in_transition_share_bps": 0,
            "cutover_share_bps": 0,
            "design_frozen_at": None,
            "acceptance_ready": False,
        }
    )
    subtotal, fee, value = calc.contract_value_recompute(project)
    project["escalation_fee_cents"] = fee
    project["contract_value_cents"] = value

    store.projects[project["id"]] = project
    return object_response(project_out(project), 201)


@bp.get("/projects/<project_id>")
def read_project(project_id):
    authenticate(ALL_ROLES)
    project = get_project(project_id)
    return object_response(project_out(project))


@bp.post("/projects/<project_id>/design-freeze")
def design_freeze(project_id):
    authenticate(("ProjectDirector",))
    project = get_project(project_id)

    # Band 8 - state admissibility.
    if project["delivery_status"] != "DESIGN":
        raise ApiError(
            "ERR_PROJECT_NOT_IN_DESIGN",
            "Design freeze is only legal while delivery_status is DESIGN.",
        )
    gating_run = calc.current_degraded_run(project)
    if gating_run is None:
        raise ApiError(
            "ERR_SIMULATION_STALE_OR_MISSING",
            "No COMPLETE DEGRADED_AVAILABILITY simulation exists for the current design_version.",
        )

    # Band 14 - graph and share integrity, then the shortfall gate.
    calc.check_share_integrity(project)
    if gating_run["effective_throughput_cph"] < project["required_throughput_cph"]:
        raise ApiError(
            "ERR_THROUGHPUT_SHORTFALL",
            "Simulated effective throughput %d is below the required %d cartons per hour."
            % (gating_run["effective_throughput_cph"], project["required_throughput_cph"]),
        )

    project["delivery_status"] = "DESIGN_FROZEN"
    project["design_frozen_at"] = iso(now())
    touch(project)
    return object_response(project_out(project))


@bp.post("/projects/<project_id>/simulations")
def run_simulation(project_id):
    authenticate(("DesignEngineer",))
    project = get_project(project_id)
    data = body()
    method = req_enum(data, "method", SIMULATION_METHODS)

    # Band 14 - share integrity gates the run itself.
    calc.check_share_integrity(project)

    figures = calc.compute_simulation(project, method)

    run = new_record()
    run.update(
        {
            "project_id": project["id"],
            "method": method,
            "design_version_at_run": project["design_version"],
            "status": "COMPLETE",
        }
    )
    run.update(figures)

    # A completed run supersedes its predecessor of the same method.
    for existing in runs_of(project["id"]):
        if (
            existing["id"] != run["id"]
            and existing["method"] == method
            and existing["status"] == "COMPLETE"
        ):
            existing["status"] = "SUPERSEDED"
            touch(existing)

    store.simulation_runs[run["id"]] = run

    if (
        method == "DEGRADED_AVAILABILITY"
        and run["design_version_at_run"] == project["design_version"]
        and run["effective_throughput_cph"] >= project["required_throughput_cph"]
    ):
        release_design_block(project)

    return object_response(simulation_run_out(run), 201)


@bp.get("/projects/<project_id>/simulation-runs")
def list_simulation_runs(project_id):
    authenticate(ALL_ROLES)
    project = get_project(project_id)
    limit, offset = pagination()
    method = query_filter("method")
    status = query_filter("status")

    records = runs_of(project["id"])
    if method is not None:
        records = [r for r in records if r["method"] == method]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    records = list(reversed(records))  # newest first by created_at DESC
    page, total = paginate(records, limit, offset)
    return list_response([simulation_run_out(r) for r in page], limit, offset, total)


@bp.post("/projects/<project_id>/spares-provisioning")
def spares_provisioning(project_id):
    authenticate(("ProjectDirector",))
    project = get_project(project_id)
    data = body()
    expected = req_int(data, "expected_project_version")

    # Band 7 - optimistic concurrency on the project.
    if expected != project["version"]:
        raise ApiError(
            "ERR_STALE_PROJECT_VERSION",
            "expected_project_version %d does not match the project's version %d."
            % (expected, project["version"]),
        )

    # Band 15 - money gate, evaluated last; nothing is persisted on rejection.
    if not calc.fundable_spare_lines(project):
        raise ApiError(
            "ERR_NO_FUNDABLE_SPARE_LINES",
            "No spare part line with criticality CRITICAL or MAJOR is available to fund.",
        )

    calc.run_spares_waterfall(project)
    touch(project)
    return object_response(project_out(project))


@bp.get("/projects/<project_id>/spare-part-lines")
def list_spare_part_lines(project_id):
    authenticate(ALL_ROLES)
    project = get_project(project_id)
    limit, offset = pagination()
    criticality = query_filter("criticality")
    status = query_filter("status")

    records = spare_lines_of(project["id"])
    if criticality is not None:
        records = [r for r in records if r["criticality"] == criticality]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = paginate(records, limit, offset)
    return list_response([spare_part_line_out(r) for r in page], limit, offset, total)


@bp.get("/projects/<project_id>/segments")
def list_project_segments(project_id):
    authenticate(ALL_ROLES)
    project = get_project(project_id)
    limit, offset = pagination()
    equipment_class = query_filter("equipment_class")

    records = segments_of(project["id"])
    if equipment_class is not None:
        records = [r for r in records if r["equipment_class"] == equipment_class]
    page, total = paginate(records, limit, offset)
    return list_response([segment_out(r) for r in page], limit, offset, total)


@bp.get("/projects/<project_id>/site-zones")
def list_project_zones(project_id):
    authenticate(ALL_ROLES)
    project = get_project(project_id)
    limit, offset = pagination()
    records = zones_of(project["id"])
    page, total = paginate(records, limit, offset)
    return list_response([site_zone_out(r) for r in page], limit, offset, total)


@bp.get("/projects/<project_id>/commissioning-ramps")
def list_project_ramps(project_id):
    authenticate(ALL_ROLES)
    project = get_project(project_id)
    limit, offset = pagination()
    step_pct = query_int_filter("step_pct")

    records = ramps_of(project["id"])
    if step_pct is not None:
        records = [r for r in records if r["step_pct"] == step_pct]
    page, total = paginate(records, limit, offset)
    return list_response([commissioning_ramp_out(r) for r in page], limit, offset, total)


@bp.get("/projects/<project_id>/change-orders")
def list_project_change_orders(project_id):
    authenticate(ALL_ROLES)
    project = get_project(project_id)
    limit, offset = pagination()
    status = query_filter("status")

    records = change_orders_of(project["id"])
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = paginate(records, limit, offset)
    return list_response([change_order_out(r) for r in page], limit, offset, total)


@bp.get("/projects/<project_id>/acceptance-certificates")
def list_project_certificates(project_id):
    authenticate(ALL_ROLES)
    project = get_project(project_id)
    limit, offset = pagination()
    records = certificates_of(project["id"])
    page, total = paginate(records, limit, offset)
    return list_response([acceptance_certificate_out(r) for r in page], limit, offset, total)


@bp.post("/_clock/set_current_utc")
def set_clock_endpoint():
    from store import parse_iso, set_clock

    authenticate(("ProjectDirector",))
    data = body()
    raw = data.get("to_iso8601")
    if not isinstance(raw, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'to_iso8601' is required.")
    parsed = parse_iso(raw)
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'to_iso8601' must be a valid ISO 8601 instant.")
    set_clock(parsed)
    return object_response({})
