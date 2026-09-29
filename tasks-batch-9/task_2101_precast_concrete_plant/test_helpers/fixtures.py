"""Composite setup helpers for the precast plant workflow.

Every helper builds its preconditions from scratch through the PRD's own
endpoints, because each test starts against an empty database.  Setup calls go
through the lenient success validator so that a broken precondition surfaces as
"Setup step failed" rather than as a confusing assertion deep inside a test.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import (
    CLOCK_START,
    LBF_3500_PSI,
    RUN_END,
    RUN_START,
)
from .factories import (
    create_bed_run_payload,
    create_casting_bed_payload,
    create_curing_cycle_payload,
    create_cylinder_set_payload,
    create_haul_permit_payload,
    create_mix_design_payload,
    create_piece_payload,
    create_project_payload,
    create_repair_disposition_payload,
    create_shipment_line_payload,
    create_shipment_payload,
    create_steam_zone_payload,
    create_yard_placement_payload,
    create_yard_slot_payload,
    cylinder_break_payload,
    tension_payload,
)
from .test_users import (
    QC_TECHNICIAN_USER,
    QUALITY_ENGINEER_USER,
    TEST_USERS,
    make_production_supervisor_headers,
    make_qc_technician_headers,
    make_quality_engineer_headers,
)

ADMIN = TEST_USERS["plant_admin_headers"]
SUPERVISOR = TEST_USERS["production_supervisor_headers"]
QC = TEST_USERS["qc_technician_headers"]
ENGINEER = TEST_USERS["quality_engineer_headers"]
FOREMAN = TEST_USERS["yard_foreman_headers"]
PERMITS = TEST_USERS["permit_coordinator_headers"]

LIST_ALL = {"limit": 100, "offset": 0}


# ==========================================================================
# Tier 0 -- single-call helpers
# ==========================================================================
def set_clock(to_iso8601: str = CLOCK_START) -> dict:
    return get_success_data(api.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_project(**overrides) -> dict:
    return get_success_data(api.create_project(create_project_payload(**overrides), ADMIN))


def create_draft_mix(**overrides) -> dict:
    return get_success_data(
        api.create_mix_design(create_mix_design_payload(**overrides), ENGINEER)
    )


def create_qualified_mix(**overrides) -> dict:
    mix = create_draft_mix(**overrides)
    return get_success_data(api.qualify_mix_design(mix["id"], ENGINEER))


def create_steam_zone(**overrides) -> dict:
    return get_success_data(
        api.create_steam_zone(create_steam_zone_payload(**overrides), ADMIN)
    )


def create_casting_bed(steam_zone_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_casting_bed(create_casting_bed_payload(steam_zone_id, **overrides), ADMIN)
    )


def create_yard_slot(**overrides) -> dict:
    return get_success_data(api.create_yard_slot(create_yard_slot_payload(**overrides), ADMIN))


def create_bed_run(bed_id: str, mix_design_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_bed_run(create_bed_run_payload(bed_id, mix_design_id, **overrides), SUPERVISOR)
    )


def create_piece(project_id: str, mix_design_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_piece(create_piece_payload(project_id, mix_design_id, **overrides), SUPERVISOR)
    )


def assign_piece(piece_id: str, bed_run_id: str) -> dict:
    return get_success_data(
        api.assign_piece_to_run(piece_id, {"bed_run_id": bed_run_id}, SUPERVISOR)
    )


def tension_run(bed_run_id: str, **overrides) -> dict:
    return get_success_data(
        api.tension_bed_run(bed_run_id, tension_payload(**overrides), SUPERVISOR)
    )


def abort_tensioning(bed_run_id: str, reason: str = "Chuck slip detected on strand 7") -> dict:
    return get_success_data(api.abort_tensioning(bed_run_id, {"reason": reason}, SUPERVISOR))


def create_cylinder_set(bed_run_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_cylinder_set(bed_run_id, create_cylinder_set_payload(**overrides), QC)
    )


def record_break(cylinder_set_id: str, load_lbf: float, diameter_in: float = 4.00,
                 user_id: str = QC_TECHNICIAN_USER) -> dict:
    return get_success_data(
        api.record_cylinder_break(
            cylinder_set_id,
            cylinder_break_payload(load_lbf, diameter_in=diameter_in),
            make_qc_technician_headers(user_id),
        )
    )


def create_curing_cycle(bed_run_id: str, steam_zone_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_curing_cycle(
            bed_run_id, create_curing_cycle_payload(steam_zone_id, **overrides), SUPERVISOR
        )
    )


def cast_run(bed_run_id: str) -> dict:
    return get_success_data(api.cast_bed_run(bed_run_id, SUPERVISOR))


def complete_curing_cycle(curing_cycle_id: str, metered_therms=None) -> dict:
    payload = {} if metered_therms is None else {"metered_therms": metered_therms}
    return get_success_data(api.complete_curing_cycle(curing_cycle_id, SUPERVISOR, payload))


def request_release(bed_run_id: str, user_id: str = QUALITY_ENGINEER_USER) -> dict:
    return get_success_data(
        api.request_release(bed_run_id, make_quality_engineer_headers(user_id))
    )


def strip_run(bed_run_id: str) -> dict:
    return get_success_data(api.strip_bed_run(bed_run_id, SUPERVISOR))


def place_piece(piece_id: str, yard_slot_id: str, stack_level: int = 1) -> dict:
    """Read the slot's live version first, as the placement contract requires."""
    slot = read_yard_slot(yard_slot_id)
    return get_success_data(
        api.create_yard_placement(
            create_yard_placement_payload(
                piece_id, yard_slot_id, slot["version"], stack_level=stack_level
            ),
            FOREMAN,
        )
    )


def pull_placement(yard_placement_id: str, release_reason: str = "RESTACK") -> dict:
    return get_success_data(
        api.pull_yard_placement(yard_placement_id, {"release_reason": release_reason}, FOREMAN)
    )


def apply_permit(project_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_haul_permit(create_haul_permit_payload(project_id, **overrides), PERMITS)
    )


def issue_permit(haul_permit_id: str) -> dict:
    return get_success_data(api.issue_haul_permit(haul_permit_id, PERMITS))


def create_issued_permit(project_id: str, **overrides) -> dict:
    permit = apply_permit(project_id, **overrides)
    return issue_permit(permit["id"])


def create_shipment(project_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_shipment(create_shipment_payload(project_id, **overrides), FOREMAN)
    )


def add_shipment_line(shipment_id: str, piece_id: str, load_position: int) -> dict:
    return get_success_data(
        api.create_shipment_line(
            shipment_id, create_shipment_line_payload(piece_id, load_position), FOREMAN
        )
    )


def dispatch_shipment(shipment_id: str) -> dict:
    return get_success_data(api.dispatch_shipment(shipment_id, FOREMAN))


def deliver_shipment(shipment_id: str) -> dict:
    return get_success_data(api.deliver_shipment(shipment_id, FOREMAN))


def open_ncr(piece_id: str, user_id: str = QC_TECHNICIAN_USER, **overrides) -> dict:
    """Read the piece's live version first, as the report contract requires."""
    piece = read_piece(piece_id)
    return get_success_data(
        api.create_repair_disposition(
            create_repair_disposition_payload(piece_id, piece["version"], **overrides),
            make_qc_technician_headers(user_id),
        )
    )


def decide_disposition(repair_disposition_id: str, disposition: str,
                       user_id: str = QUALITY_ENGINEER_USER) -> dict:
    return get_success_data(
        api.decide_disposition(
            repair_disposition_id,
            {"disposition": disposition},
            make_quality_engineer_headers(user_id),
        )
    )


def start_repair(repair_disposition_id: str, user_id=None) -> dict:
    headers = SUPERVISOR if user_id is None else make_production_supervisor_headers(user_id)
    return get_success_data(api.start_repair(repair_disposition_id, headers))


def submit_reinspection(repair_disposition_id: str, user_id=None) -> dict:
    headers = SUPERVISOR if user_id is None else make_production_supervisor_headers(user_id)
    return get_success_data(api.submit_reinspection(repair_disposition_id, headers))


def reinspect(repair_disposition_id: str, result: str,
              user_id: str = QUALITY_ENGINEER_USER) -> dict:
    return get_success_data(
        api.reinspect(
            repair_disposition_id, {"result": result}, make_quality_engineer_headers(user_id)
        )
    )


# ==========================================================================
# Read helpers.  Rows that have no single-resource read are fetched through
# the collection endpoint the PRD does expose for them.
# ==========================================================================
def read_project(project_id: str) -> dict:
    return get_success_data(api.get_project(project_id, ADMIN))


def read_mix_design(mix_design_id: str) -> dict:
    return get_success_data(api.get_mix_design(mix_design_id, ENGINEER))


def read_steam_zone(steam_zone_id: str) -> dict:
    return get_success_data(api.get_steam_zone(steam_zone_id, ADMIN))


def read_casting_bed(casting_bed_id: str) -> dict:
    return get_success_data(api.get_casting_bed(casting_bed_id, SUPERVISOR))


def read_bed_run(bed_run_id: str) -> dict:
    return get_success_data(api.get_bed_run(bed_run_id, SUPERVISOR))


def read_cylinder_set(cylinder_set_id: str) -> dict:
    return get_success_data(api.get_cylinder_set(cylinder_set_id, QC))


def read_piece(piece_id: str) -> dict:
    return get_success_data(api.get_piece(piece_id, SUPERVISOR))


def read_yard_slot(yard_slot_id: str) -> dict:
    return get_success_data(api.get_yard_slot(yard_slot_id, FOREMAN))


def read_haul_permit(haul_permit_id: str) -> dict:
    return get_success_data(api.get_haul_permit(haul_permit_id, PERMITS))


def read_shipment(shipment_id: str) -> dict:
    return get_success_data(api.get_shipment(shipment_id, FOREMAN))


def _find(rows, row_id, label):
    for row in rows:
        if row.get("id") == row_id:
            return row
    raise AssertionError(f"Setup step failed: no {label} with id {row_id} in {len(rows)} rows")


def read_curing_cycle(bed_run_id: str, curing_cycle_id: str) -> dict:
    rows = get_success_data(api.list_bed_run_curing_cycles(bed_run_id, SUPERVISOR, LIST_ALL))
    return _find(rows, curing_cycle_id, "curing cycle")


def read_cylinder_break(cylinder_set_id: str, break_id: str) -> dict:
    rows = get_success_data(api.list_cylinder_breaks(cylinder_set_id, QC, LIST_ALL))
    return _find(rows, break_id, "cylinder break")


def list_cylinder_breaks(cylinder_set_id: str) -> list:
    return get_success_data(api.list_cylinder_breaks(cylinder_set_id, QC, LIST_ALL))


def read_yard_placement(piece_id: str, placement_id: str) -> dict:
    rows = get_success_data(api.list_piece_yard_placements(piece_id, FOREMAN, LIST_ALL))
    return _find(rows, placement_id, "yard placement")


def list_piece_placements(piece_id: str) -> list:
    return get_success_data(api.list_piece_yard_placements(piece_id, FOREMAN, LIST_ALL))


def read_shipment_line(shipment_id: str, line_id: str) -> dict:
    rows = get_success_data(api.list_shipment_lines(shipment_id, FOREMAN, LIST_ALL))
    return _find(rows, line_id, "shipment line")


def list_shipment_lines(shipment_id: str) -> list:
    return get_success_data(api.list_shipment_lines(shipment_id, FOREMAN, LIST_ALL))


def read_repair_disposition(piece_id: str, ncr_id: str) -> dict:
    rows = get_success_data(api.list_piece_repair_dispositions(piece_id, QC, LIST_ALL))
    return _find(rows, ncr_id, "repair disposition")


def list_piece_repair_dispositions(piece_id: str) -> list:
    return get_success_data(api.list_piece_repair_dispositions(piece_id, QC, LIST_ALL))


# ==========================================================================
# Tier 1 -- the static plant: project(s), mix book, boiler zone, bed, slot
# ==========================================================================
DEFAULT_PIECE_MARKS = ["DT-101", "DT-102", "DT-103", "DT-104", "DT-105", "DT-106"]


def setup_plant(
    clock=CLOCK_START,
    project_count=1,
    mix_overrides=None,
    zone_overrides=None,
    bed_overrides=None,
    slot_overrides=None,
    with_slot=False,
):
    """Clock + N erection packages + one QUALIFIED mix + boiler zone + bed
    (+ optional yard slot).  Returns a context dict every later tier extends."""
    set_clock(clock)
    projects = [
        create_project(
            **(
                {}
                if i == 0
                else {
                    "name": ["Riverfront Garage", "Southside Deck", "Northgate Ramp"][i],
                    "jobsite_city": ["Nashville", "Memphis", "Knoxville"][i],
                    "erection_start_date": ["2026-09-15", "2026-10-01", "2026-10-20"][i],
                }
            )
        )
        for i in range(project_count)
    ]
    mix = create_qualified_mix(**(mix_overrides or {}))
    zone = create_steam_zone(**(zone_overrides or {}))
    bed = create_casting_bed(zone["id"], **(bed_overrides or {}))
    slot = create_yard_slot(**(slot_overrides or {})) if with_slot else None
    return {
        "clock": clock,
        "projects": projects,
        "project": projects[0] if projects else None,
        "mix": mix,
        "zone": zone,
        "bed": bed,
        "slot": slot,
        "pieces": [],
        "placements": [],
        "run": None,
        "cylinder_set": None,
        "curing_cycle": None,
    }


# ==========================================================================
# Tier 2-4 -- walk the casting cycle to a requested stage
# ==========================================================================
STAGES = [
    "plant",
    "scheduled",
    "tensioned",
    "curing",
    "release_ready",
    "released",
    "stripped",
    "yarded",
]


def _stage_at_least(stage, target):
    return STAGES.index(stage) >= STAGES.index(target)


def setup_production_line(
    stage="stripped",
    piece_specs=None,
    project_count=1,
    clock=CLOCK_START,
    mix_overrides=None,
    zone_overrides=None,
    bed_overrides=None,
    slot_overrides=None,
    with_slot=None,
    run_overrides=None,
    tension_overrides=None,
    cylinder_set_overrides=None,
    with_cylinder_set=None,
    curing_overrides=None,
    with_curing_cycle=None,
    release_break_loads=None,
    metered_therms=None,
    break_user_id=QC_TECHNICIAN_USER,
    release_user_id=QUALITY_ENGINEER_USER,
):
    """Drive one bed run from scheduling through to the requested `stage`.

    Stages, in order: plant, scheduled, tensioned, curing, release_ready,
    released, stripped, yarded.  `piece_specs` is a list of override dicts for
    `create_piece_payload`; each may carry `project_index` to pick which
    erection package owns the piece.  Defaults produce one 48200 lb oversize
    double tee (DT-101, erection_sequence_no 10) on a C40 mix.
    """
    if stage not in STAGES:
        raise ValueError(f"unknown stage {stage}")
    if with_slot is None:
        with_slot = _stage_at_least(stage, "yarded")
    if with_cylinder_set is None:
        with_cylinder_set = _stage_at_least(stage, "release_ready")
    if with_curing_cycle is None:
        with_curing_cycle = _stage_at_least(stage, "curing")
    if piece_specs is None:
        piece_specs = [{}]
    if release_break_loads is None:
        release_break_loads = (LBF_3500_PSI, LBF_3500_PSI)

    ctx = setup_plant(
        clock=clock,
        project_count=project_count,
        mix_overrides=mix_overrides,
        zone_overrides=zone_overrides,
        bed_overrides=bed_overrides,
        slot_overrides=slot_overrides,
        with_slot=with_slot,
    )
    if stage == "plant":
        return ctx

    ctx["run"] = create_bed_run(ctx["bed"]["id"], ctx["mix"]["id"], **(run_overrides or {}))

    for index, spec in enumerate(piece_specs):
        spec = dict(spec)
        project_index = spec.pop("project_index", 0)
        spec.setdefault("piece_mark", DEFAULT_PIECE_MARKS[index])
        spec.setdefault("erection_sequence_no", (index + 1) * 10)
        piece = create_piece(
            ctx["projects"][project_index]["id"], ctx["mix"]["id"], **spec
        )
        assign_piece(piece["id"], ctx["run"]["id"])
        ctx["pieces"].append(read_piece(piece["id"]))

    if not _stage_at_least(stage, "tensioned"):
        ctx["run"] = read_bed_run(ctx["run"]["id"])
        return ctx

    tension_run(ctx["run"]["id"], **(tension_overrides or {}))

    if with_cylinder_set:
        ctx["cylinder_set"] = create_cylinder_set(
            ctx["run"]["id"], **(cylinder_set_overrides or {})
        )
    if with_curing_cycle:
        ctx["curing_cycle"] = create_curing_cycle(
            ctx["run"]["id"], ctx["zone"]["id"], **(curing_overrides or {})
        )

    if not _stage_at_least(stage, "curing"):
        ctx["run"] = read_bed_run(ctx["run"]["id"])
        return ctx

    cast_run(ctx["run"]["id"])

    if not _stage_at_least(stage, "release_ready"):
        ctx["run"] = read_bed_run(ctx["run"]["id"])
        ctx["pieces"] = [read_piece(p["id"]) for p in ctx["pieces"]]
        return ctx

    if ctx["curing_cycle"] is not None:
        complete_curing_cycle(ctx["curing_cycle"]["id"], metered_therms)
        ctx["curing_cycle"] = read_curing_cycle(
            ctx["run"]["id"], ctx["curing_cycle"]["id"]
        )
    if ctx["cylinder_set"] is not None:
        for load in release_break_loads:
            record_break(ctx["cylinder_set"]["id"], load, user_id=break_user_id)
        ctx["cylinder_set"] = read_cylinder_set(ctx["cylinder_set"]["id"])

    if not _stage_at_least(stage, "released"):
        ctx["run"] = read_bed_run(ctx["run"]["id"])
        ctx["pieces"] = [read_piece(p["id"]) for p in ctx["pieces"]]
        return ctx

    request_release(ctx["run"]["id"], user_id=release_user_id)

    if not _stage_at_least(stage, "stripped"):
        ctx["run"] = read_bed_run(ctx["run"]["id"])
        ctx["pieces"] = [read_piece(p["id"]) for p in ctx["pieces"]]
        return ctx

    strip_run(ctx["run"]["id"])
    ctx["run"] = read_bed_run(ctx["run"]["id"])
    ctx["pieces"] = [read_piece(p["id"]) for p in ctx["pieces"]]

    if not _stage_at_least(stage, "yarded"):
        return ctx

    for level, piece in enumerate(ctx["pieces"], start=1):
        ctx["placements"].append(place_piece(piece["id"], ctx["slot"]["id"], stack_level=level))
    ctx["pieces"] = [read_piece(p["id"]) for p in ctx["pieces"]]
    ctx["slot"] = read_yard_slot(ctx["slot"]["id"])
    return ctx


# ==========================================================================
# Tier 5 -- shipping shortcuts
# ==========================================================================
def setup_yarded_load(
    piece_specs=None,
    project_count=1,
    slot_overrides=None,
    permit_overrides=None,
    with_permit=True,
    issue=True,
    shipment_overrides=None,
    clock=CLOCK_START,
):
    """Pieces cleared, stripped and yarded, plus an open BUILDING shipment for
    the first erection package (optionally linked to a haul permit)."""
    ctx = setup_production_line(
        stage="yarded",
        piece_specs=piece_specs,
        project_count=project_count,
        slot_overrides=slot_overrides or {"capacity_weight_lb": 200000, "max_stack_count": 5},
        clock=clock,
    )
    ctx["permit"] = None
    if with_permit:
        permit = apply_permit(ctx["project"]["id"], **(permit_overrides or {}))
        if issue:
            permit = issue_permit(permit["id"])
        ctx["permit"] = permit
    ship_overrides = dict(shipment_overrides or {})
    if ctx["permit"] is not None:
        ship_overrides.setdefault("haul_permit_id", ctx["permit"]["id"])
    ctx["shipment"] = create_shipment(ctx["project"]["id"], **ship_overrides)
    ctx["lines"] = []
    return ctx


def load_pieces(ctx, order):
    """Add one line per (piece_index, load_position) pair, in the given order."""
    for piece_index, load_position in order:
        line = add_shipment_line(
            ctx["shipment"]["id"], ctx["pieces"][piece_index]["id"], load_position
        )
        ctx["lines"].append(line)
    ctx["shipment"] = read_shipment(ctx["shipment"]["id"])
    return ctx


# ==========================================================================
# Tier 5 -- nonconformance shortcuts
# ==========================================================================
def setup_piece_with_open_ncr(stage="plant", piece_specs=None, ncr_overrides=None,
                              qc_user=QC_TECHNICIAN_USER, **kwargs):
    """A piece carrying one OPEN nonconformance report.  With the default
    `plant` stage the piece is never assigned to a run, so nothing but the
    report itself touches its quality dimension."""
    if stage == "plant":
        set_clock(kwargs.get("clock", CLOCK_START))
        project = create_project()
        mix = create_qualified_mix()
        spec = dict((piece_specs or [{}])[0])
        piece = create_piece(project["id"], mix["id"], **spec)
        ctx = {
            "projects": [project],
            "project": project,
            "mix": mix,
            "pieces": [read_piece(piece["id"])],
            "run": None,
            "slot": None,
            "placements": [],
        }
    else:
        ctx = setup_production_line(stage=stage, piece_specs=piece_specs, **kwargs)
    ctx["ncr"] = open_ncr(ctx["pieces"][0]["id"], user_id=qc_user, **(ncr_overrides or {}))
    ctx["pieces"] = [read_piece(p["id"]) for p in ctx["pieces"]]
    return ctx


def setup_dispositioned_ncr(disposition="STRUCTURAL_REPAIR",
                            engineer_user=QUALITY_ENGINEER_USER, **kwargs):
    """A report the engineer has already decided, ready for the repair loop."""
    ctx = setup_piece_with_open_ncr(**kwargs)
    ctx["ncr"] = decide_disposition(ctx["ncr"]["id"], disposition, user_id=engineer_user)
    ctx["pieces"] = [read_piece(p["id"]) for p in ctx["pieces"]]
    return ctx


def setup_ncr_in_reinspection(repairer_user="ps-carl", **kwargs):
    """A report that has been dispositioned, repaired and submitted, so the
    next reinspect call decides the repair loop."""
    ctx = setup_dispositioned_ncr(**kwargs)
    start_repair(ctx["ncr"]["id"], user_id=repairer_user)
    ctx["ncr"] = submit_reinspection(ctx["ncr"]["id"], user_id=repairer_user)
    return ctx


# ==========================================================================
# Tier 5 -- second-bed helpers for cross-resource scenarios
# ==========================================================================
def add_bed_and_run(ctx, bed_code="B2", mix_design_id=None, bed_overrides=None,
                    run_overrides=None):
    """Register another casting bed in the same boiler zone and schedule a run
    on it, so bed occupancy never confounds a boiler or strength scenario."""
    bed = create_casting_bed(
        ctx["zone"]["id"], **{**{"bed_code": bed_code}, **(bed_overrides or {})}
    )
    run = create_bed_run(
        bed["id"], mix_design_id or ctx["mix"]["id"], **(run_overrides or {})
    )
    return bed, run
