"""Composite setup builders.

The harness restarts the server before every test, so each test starts against
an empty database and has to build its own preconditions out of the endpoints
the PRD declares. Every function here does exactly that: it drives real calls,
asserts only that the setup step succeeded, and returns the created row so the
test can assert on the behaviour it actually cares about.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import DEFAULT_CLOCK
from .test_users import (
    CONSERVATOR,
    CURATOR,
    FABRICATION,
    OPERATIONS,
    PM,
)
from .types import (
    CaseDecision,
    DrawingDecision,
    MaterialDecision,
    MountStatus,
    PackageStage,
    Phase,
    PrototypeDecision,
    VoteDecision,
    WindowDecision,
)

#: A clock instant comfortably after every fixture deadline, used by the
#: install and commissioning stages.
LATE_CLOCK = "2026-09-10T08:00:00Z"
#: Default review deadline for setup rounds: far enough ahead that moving the
#: clock for install work never lapses a round a test did not ask about.
FAR_DEADLINE = "2027-01-01T00:00:00Z"


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------
def set_clock(api, instant=DEFAULT_CLOCK, headers=PM):
    response = api.set_clock(instant, headers)
    assert response.status_code == 200, (
        "setting the logical clock failed: %s" % response.text
    )
    return instant


# ---------------------------------------------------------------------------
# single-entity builders
# ---------------------------------------------------------------------------
def create_project(api, headers=PM, **overrides):
    return get_success_data(
        api.create_project(f.project_payload(**overrides), headers), 201
    )


def read_project(api, project_id, headers=PM):
    return get_success_data(api.get_project(project_id, headers), 200)


def project_version(api, project_id, headers=PM):
    return read_project(api, project_id, headers)["version"]


def advance(api, project_id, to_phase, headers=PM):
    return get_success_data(
        api.advance_phase(project_id, f.advance_phase_payload(to_phase), headers), 200
    )


def create_zone(api, project_id, headers=PM, **overrides):
    return get_success_data(
        api.create_gallery_zone(project_id, f.gallery_zone_payload(**overrides), headers),
        201,
    )


def create_artifact(api, project_id, headers=CURATOR, **overrides):
    return get_success_data(
        api.create_artifact(project_id, f.artifact_payload(**overrides), headers), 201
    )


def create_case(api, project_id, zone_id, headers=PM, **overrides):
    return get_success_data(
        api.create_artifact_case(
            project_id, f.artifact_case_payload(zone_id, **overrides), headers
        ),
        201,
    )


def place_artifact(api, case_id, artifact_id, headers=CURATOR, expected_case_version=None):
    if expected_case_version is None:
        expected_case_version = get_success_data(
            api.get_artifact_case(case_id, headers), 200
        )["version"]
    return get_success_data(
        api.create_placement(
            case_id, f.placement_payload(artifact_id, expected_case_version), headers
        ),
        201,
    )


def submit_case(api, case_id, headers=PM):
    return get_success_data(api.submit_case_for_conservation(case_id, headers), 200)


def decide_case(api, case_id, decision=CaseDecision.APPROVE, headers=CONSERVATOR, **payload):
    return get_success_data(
        api.case_conservator_decision(
            case_id, f.case_decision_payload(decision, **payload), headers
        ),
        200,
    )


def approve_case(api, case_id, submit_headers=PM, headers=CONSERVATOR):
    """Send a loaded case to conservation and approve it, reserving a zone slot."""
    submit_case(api, case_id, submit_headers)
    return decide_case(api, case_id, CaseDecision.APPROVE, headers)


def advance_mount(api, case_id, to_mount_status, headers=CONSERVATOR):
    return get_success_data(
        api.mount_advance(case_id, f.mount_advance_payload(to_mount_status), headers), 200
    )


def create_interactive(api, project_id, headers=FABRICATION, **overrides):
    return get_success_data(
        api.create_interactive(project_id, f.interactive_payload(**overrides), headers),
        201,
    )


def create_material(api, project_id, headers=FABRICATION, **overrides):
    return get_success_data(
        api.create_material_spec(project_id, f.material_spec_payload(**overrides), headers),
        201,
    )


def approve_material(
    api,
    material_id,
    decision=MaterialDecision.APPROVE,
    submit_headers=FABRICATION,
    headers=CONSERVATOR,
    **payload
):
    """Push a material through screening to a conservator ruling."""
    get_success_data(api.submit_material_for_conservation(material_id, submit_headers), 200)
    return get_success_data(
        api.material_conservator_decision(
            material_id, f.material_decision_payload(decision, **payload), headers
        ),
        200,
    )


def create_drawing(api, project_id, material_spec_id, headers=FABRICATION, **overrides):
    return get_success_data(
        api.create_shop_drawing(
            f.shop_drawing_payload(project_id, material_spec_id, **overrides), headers
        ),
        201,
    )


def approve_drawing(api, drawing_id, decision=DrawingDecision.APPROVE, headers=PM, **payload):
    """Take a submitted sheet into review and rule on it, committing money."""
    get_success_data(api.start_drawing_review(drawing_id, headers), 200)
    return get_success_data(
        api.drawing_decision(
            drawing_id, f.drawing_decision_payload(decision, **payload), headers
        ),
        200,
    )


def create_package(api, project_id, stage=PackageStage.SCHEMATIC, headers=PM, **overrides):
    """Issue a design package, reading the project version the create demands."""
    version = overrides.pop("expected_project_version", None)
    if version is None:
        version = project_version(api, project_id, headers)
    return get_success_data(
        api.create_design_package(
            project_id, f.design_package_payload(version, stage=stage, **overrides), headers
        ),
        201,
    )


def open_round(api, package_id, headers=PM, panel_roles=None, decision_deadline_at=FAR_DEADLINE, **overrides):
    return get_success_data(
        api.create_review_round(
            package_id,
            f.review_round_payload(
                panel_roles=panel_roles,
                decision_deadline_at=decision_deadline_at,
                **overrides
            ),
            headers,
        ),
        201,
    )


def cast_vote(api, round_id, headers, decision=VoteDecision.APPROVE, **overrides):
    return get_success_data(
        api.cast_vote(round_id, f.vote_payload(decision, **overrides), headers), 201
    )


def approve_package(
    api,
    project_id,
    stage=PackageStage.SCHEMATIC,
    headers=PM,
    panel_roles=None,
    decision_deadline_at=FAR_DEADLINE,
    package_overrides=None,
):
    """Issue a package and carry it to APPROVED on a two-vote quorum.

    The panel seats Curator, Conservator and FabricationLead, so the two
    approving voters are never the ProjectManager who authored the package and
    the segregation-of-duties rule on voting never fires.
    """
    package = create_package(
        api, project_id, stage=stage, headers=headers, **(package_overrides or {})
    )
    review_round = open_round(
        api,
        package["id"],
        headers=PM,
        panel_roles=panel_roles,
        decision_deadline_at=decision_deadline_at,
    )
    cast_vote(api, review_round["id"], CURATOR, VoteDecision.APPROVE)
    resolved = cast_vote(api, review_round["id"], CONSERVATOR, VoteDecision.APPROVE)
    return package, resolved


def create_window(api, project_id, zone_id, headers=FABRICATION, **overrides):
    return get_success_data(
        api.create_install_window(
            f.install_window_payload(project_id, zone_id, **overrides), headers
        ),
        201,
    )


def decide_window(api, window_id, decision=WindowDecision.APPROVE, headers=OPERATIONS, **payload):
    return get_success_data(
        api.window_decision(
            window_id, f.window_decision_payload(decision, **payload), headers
        ),
        200,
    )


def start_window(api, window_id, headers=OPERATIONS):
    return get_success_data(api.start_window(window_id, headers), 200)


def complete_window(api, window_id, headers=OPERATIONS):
    return get_success_data(api.complete_window(window_id, headers), 200)


def cancel_window(api, window_id, headers=OPERATIONS, **payload):
    return get_success_data(api.cancel_window(window_id, headers, payload or None), 200)


def raise_punch_item(api, project_id, headers=OPERATIONS, **overrides):
    return get_success_data(
        api.create_punch_item(project_id, f.punch_item_payload(**overrides), headers), 201
    )


def prepare_interactive(api, interactive_id, submit_headers=FABRICATION, **overrides):
    """Run an interactive from SPECIFIED to FABRICATED.

    The prototype is submitted by the FabricationLead and ruled on by the
    Conservator, so the two identities differ and the prototype ruling is never
    refused for segregation of duties.  Every step here is admitted only while
    the project is still designing or building, so call this before the project
    leaves FABRICATION.
    """
    get_success_data(
        api.submit_prototype(interactive_id, f.prototype_payload(**overrides), submit_headers),
        200,
    )
    get_success_data(
        api.prototype_decision(
            interactive_id,
            f.prototype_decision_payload(PrototypeDecision.APPROVE),
            CONSERVATOR,
        ),
        200,
    )
    return get_success_data(api.mark_fabricated(interactive_id, submit_headers), 200)


def commission_interactive(api, interactive_id, headers=PM, **overrides):
    """Commission a FABRICATED interactive once the project is COMMISSIONING."""
    return get_success_data(
        api.commission_interactive(interactive_id, f.commission_payload(**overrides), headers),
        200,
    )


def settle_project(api, project_id, headers=PM, **overrides):
    return get_success_data(
        api.closeout(project_id, f.closeout_payload(**overrides), headers), 200
    )


def project_in_phase(api, phase=Phase.SCHEMATIC, project_overrides=None, zone_overrides=None):
    """Build a commission standing in the requested phase.

    The walk creates exactly the children each step's admission test demands:
    one gallery zone with two case slots, one collection object, one artifact
    case carrying the first learning objective, one interactive carrying the
    second, an approved package per design stage, an approved material and an
    approved shop drawing. From ``INSTALLATION`` onward the logical clock has
    been moved to a later instant so install work can start.

    The returned mapping holds the rows as they were created together with
    their identifiers; a test that cares about current state re-reads the row.
    """
    ctx = {"packages": {}}
    set_clock(api)
    project = create_project(api, **(project_overrides or {}))
    project_id = project["id"]
    ctx["project"] = project
    ctx["project_id"] = project_id
    if phase == Phase.INTERPRETIVE:
        ctx["project"] = read_project(api, project_id)
        return ctx

    advance(api, project_id, Phase.SCHEMATIC)
    zone = create_zone(api, project_id, **(zone_overrides or {}))
    artifact = create_artifact(api, project_id)
    interactive = create_interactive(api, project_id)
    case = create_case(api, project_id, zone["id"])
    ctx.update(
        zone=zone,
        zone_id=zone["id"],
        artifact=artifact,
        artifact_id=artifact["id"],
        interactive=interactive,
        interactive_id=interactive["id"],
        case=case,
        case_id=case["id"],
    )
    if phase == Phase.SCHEMATIC:
        ctx["project"] = read_project(api, project_id)
        return ctx

    schematic_package, _ = approve_package(api, project_id, PackageStage.SCHEMATIC)
    ctx["packages"][PackageStage.SCHEMATIC] = schematic_package
    advance(api, project_id, Phase.DESIGN_DEV)
    if phase == Phase.DESIGN_DEV:
        ctx["project"] = read_project(api, project_id)
        return ctx

    design_dev_package, _ = approve_package(api, project_id, PackageStage.DESIGN_DEV)
    ctx["packages"][PackageStage.DESIGN_DEV] = design_dev_package
    advance(api, project_id, Phase.FABRICATION)
    material = create_material(api, project_id)
    approve_material(api, material["id"])
    ctx.update(material=material, material_id=material["id"])
    if phase == Phase.FABRICATION:
        ctx["project"] = read_project(api, project_id)
        return ctx

    if phase in (Phase.CLOSEOUT, Phase.WARRANTY_CLOSED):
        # The bench work on an interactive is admitted only while the project is
        # still designing or building, so the station reaches FABRICATED here and
        # is commissioned later, once the project is COMMISSIONING.
        ctx["interactive"] = prepare_interactive(api, interactive["id"])

    place_artifact(api, case["id"], artifact["id"])
    approve_case(api, case["id"])
    drawing = create_drawing(
        api, project_id, material["id"], subject_case_id=case["id"]
    )
    approve_drawing(api, drawing["id"])
    ctx.update(drawing=drawing, drawing_id=drawing["id"])
    if phase == Phase.INSTALLATION:
        advance(api, project_id, Phase.INSTALLATION)
        ctx["project"] = read_project(api, project_id)
        return ctx

    advance_mount(api, case["id"], MountStatus.MOUNT_DESIGN)
    advance_mount(api, case["id"], MountStatus.MOUNT_FABRICATED)
    window = create_window(
        api,
        project_id,
        zone["id"],
        starts_at="2026-09-09T09:00:00Z",
        ends_at="2026-09-09T12:00:00Z",
    )
    decide_window(api, window["id"])
    advance(api, project_id, Phase.INSTALLATION)
    set_clock(api, LATE_CLOCK)
    start_window(api, window["id"])
    advance_mount(api, case["id"], MountStatus.MOUNT_INSTALLED)
    complete_window(api, window["id"])
    ctx.update(window=window, window_id=window["id"])
    advance(api, project_id, Phase.COMMISSIONING)
    if phase == Phase.COMMISSIONING:
        ctx["project"] = read_project(api, project_id)
        return ctx

    commission_interactive(api, interactive["id"])
    advance(api, project_id, Phase.CLOSEOUT)
    if phase == Phase.CLOSEOUT:
        ctx["project"] = read_project(api, project_id)
        return ctx

    settle_project(api, project_id)
    ctx["project"] = read_project(api, project_id)
    return ctx
