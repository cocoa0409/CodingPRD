"""Composite setup helpers for the BIM coordination workflow.

Every test starts against an empty database (the harness restarts the server
before each test and the logical clock reads exactly 2026-08-01T00:00:00Z, per
PRD §2.5), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: `TradeModelAuthor` and `FabricationLead` are entity-backed
roles (PRD §2.1) — every ownership-gated call is made with
`make_trade_model_author_headers(partner_id)` /
`make_fabrication_lead_headers(partner_id)` built from the real partner id,
never the shared constants.

Segregation of duties: clash assignment defaults to operator "coord-1" and
verification to "coord-2", because the verifier must differ from the assigner
(PRD §3.4). Sign-off signing defaults to "eng-1", which never equals a model's
submitter id (PRD §3.6).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import PHASE_ORDER
from .factories import (
    create_as_built_payload,
    create_clash_run_payload,
    create_commitment_payload,
    create_fabrication_package_payload,
    create_federated_model_payload,
    create_freeze_window_payload,
    create_handover_package_payload,
    create_lod_requirement_payload,
    create_meeting_payload,
    create_project_payload,
    create_quantity_takeoff_payload,
    create_trade_model_payload,
    create_trade_partner_payload,
    import_clash_payload,
    make_takeoff_element,
)
from .test_users import (
    TEST_USERS,
    make_bim_coordinator_headers,
    make_fabrication_lead_headers,
    make_lead_engineer_headers,
    make_trade_model_author_headers,
)

# Shared opaque-role headers (safe: these roles never pass ownership checks).
VDC = TEST_USERS["vdc_manager_headers"]
COORD = TEST_USERS["bim_coordinator_headers"]          # operator "coord-1"
ENG = TEST_USERS["lead_engineer_headers"]              # operator "eng-1"

# A meeting window that contains the default logical clock 2026-08-01T00:00:00Z.
DEFAULT_MEETING_STARTS = "2026-08-01T00:00:00Z"
DEFAULT_MEETING_ENDS = "2026-08-01T01:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and simple state progression
# ---------------------------------------------------------------------------

def create_project(name="P"):
    """Create a project. Returns it (SCHEMATIC_DESIGN / NORMAL / CRI 100)."""
    return get_success_data(api_client.create_project(create_project_payload(name), VDC))


def get_project(project_id):
    return get_success_data(api_client.get_project(project_id, VDC))


def project_version(project_id):
    return get_project(project_id)["version"]


def set_clock(to_iso8601):
    """Advance the logical clock (VDCManager-only, forward-only)."""
    return get_success_data(api_client.set_clock(to_iso8601, VDC))


def advance_phase(project_id):
    """Advance current_phase exactly one step. Returns the updated project."""
    return get_success_data(api_client.advance_phase(project_id, VDC))


def advance_phase_to(project_id, target_phase):
    """Advance one step at a time until current_phase == target_phase."""
    project = get_project(project_id)
    while project["current_phase"] != target_phase:
        project = advance_phase(project_id)
    return project


def run_coordination_sweep(project_id):
    return get_success_data(api_client.run_coordination_sweep(project_id, VDC))


def create_lod_requirement(project_id, discipline="STRUCTURAL",
                           phase="SCHEMATIC_DESIGN", min_lod=300,
                           clearance_requirement_mm=25.0):
    payload = create_lod_requirement_payload(
        discipline=discipline, phase=phase, min_lod=min_lod,
        clearance_requirement_mm=clearance_requirement_mm)
    return get_success_data(api_client.create_lod_requirement(project_id, payload, VDC))


def create_partner(project_id, company_name="StructCo", discipline="STRUCTURAL",
                   hourly_rate_cents=12000, coordination_budget_hours=100.0,
                   software_platform="REVIT"):
    """Onboard a trade partner. Returns it (ACTIVE, reliability 100)."""
    payload = create_trade_partner_payload(
        company_name=company_name, discipline=discipline,
        hourly_rate_cents=hourly_rate_cents,
        coordination_budget_hours=coordination_budget_hours,
        software_platform=software_platform)
    return get_success_data(api_client.create_trade_partner(project_id, payload, VDC))


def get_partner(project_id, partner_id):
    """Fetch one partner via the project roster list endpoint."""
    partners = get_success_data(api_client.list_trade_partners(project_id, VDC))
    for partner in partners:
        if partner["id"] == partner_id:
            return partner
    raise AssertionError(f"Partner {partner_id} not found in project {project_id}")


def create_model(project_id, partner_id, file_format="RVT", declared_lod=300,
                 **element_counters):
    """Create a DRAFT trade model, authored with entity-backed headers."""
    payload = create_trade_model_payload(
        partner_id, file_format=file_format, declared_lod=declared_lod,
        **element_counters)
    headers = make_trade_model_author_headers(partner_id)
    return get_success_data(api_client.create_trade_model(project_id, payload, headers))


def submit_model(model_id, partner_id):
    """Submit (ownership-gated: the author's X-User-ID is the partner id)."""
    headers = make_trade_model_author_headers(partner_id)
    return get_success_data(api_client.submit_trade_model(model_id, headers))


def accept_model(model_id, coordinator_id="coord-1"):
    return get_success_data(
        api_client.accept_trade_model(
            model_id, make_bim_coordinator_headers(coordinator_id)))


def reject_model(model_id, coordinator_id="coord-1"):
    return get_success_data(
        api_client.reject_trade_model(
            model_id, make_bim_coordinator_headers(coordinator_id)))


def get_model(model_id):
    return get_success_data(api_client.get_trade_model(model_id, VDC))


def create_and_accept_model(project_id, partner_id, **model_kwargs):
    """Create -> submit -> accept. Returns the ACCEPTED model."""
    model = create_model(project_id, partner_id, **model_kwargs)
    submit_model(model["id"], partner_id)
    return accept_model(model["id"])


# ---------------------------------------------------------------------------
# Tier 2: federated assembly chain
# ---------------------------------------------------------------------------

def create_federated_model(project_id, member_trade_model_ids, label="F1",
                           target_format="IFC", expected_project_version=None):
    """Assemble a federated model (OCC-guarded; re-reads the project version
    when expected_project_version is not supplied)."""
    if expected_project_version is None:
        expected_project_version = project_version(project_id)
    payload = create_federated_model_payload(
        member_trade_model_ids, expected_project_version,
        label=label, target_format=target_format)
    return get_success_data(api_client.create_federated_model(project_id, payload, VDC))


def get_fed(fed_id):
    return get_success_data(api_client.get_federated_model(fed_id, VDC))


def list_members(fed_id):
    return get_success_data(api_client.list_federated_model_members(fed_id, VDC))


def freeze_fed(fed_id):
    return get_success_data(api_client.freeze_federated_model(fed_id, VDC))


def unfreeze_fed(fed_id):
    return get_success_data(api_client.unfreeze_federated_model(fed_id, VDC))


def release_fed(fed_id):
    return get_success_data(api_client.release_federated_model(fed_id, VDC))


def create_freeze_window(fed_id, starts_at, ends_at, purpose="COORDINATION_FREEZE"):
    payload = create_freeze_window_payload(starts_at, ends_at, purpose=purpose)
    return get_success_data(api_client.create_freeze_window(fed_id, payload, VDC))


# ---------------------------------------------------------------------------
# Tier 2: clash runs and the resolution cycle
# ---------------------------------------------------------------------------

def create_clash_run(fed_id, tolerance_mm=5.0):
    payload = create_clash_run_payload(tolerance_mm=tolerance_mm)
    return get_success_data(api_client.create_clash_run(fed_id, payload, COORD))


def get_run(run_id):
    return get_success_data(api_client.get_clash_run(run_id, COORD))


def start_run(run_id, coordinator_id="coord-1"):
    return get_success_data(
        api_client.start_clash_run(run_id, make_bim_coordinator_headers(coordinator_id)))


def import_clash(run_id, element_pair, overlap_mm, spans_disciplines=False,
                 coordinator_id="coord-1"):
    payload = import_clash_payload(element_pair, overlap_mm, spans_disciplines)
    return get_success_data(
        api_client.import_clash(run_id, payload,
                                make_bim_coordinator_headers(coordinator_id)))


def get_clash(clash_id):
    return get_success_data(api_client.get_clash_issue(clash_id, COORD))


def assign_clash(clash_id, partner_id, coordinator_id="coord-1"):
    """Assign (or re-assign) a NEW/REOPENED clash; computes provisional cost."""
    return get_success_data(
        api_client.assign_clash(clash_id, {"trade_partner_id": partner_id},
                                make_bim_coordinator_headers(coordinator_id)))


def resolve_clash(clash_id, partner_id, actual_labor_hours):
    """Resolve (ownership-gated: caller must be the assigned partner)."""
    return get_success_data(
        api_client.resolve_clash(clash_id, {"actual_labor_hours": actual_labor_hours},
                                 make_trade_model_author_headers(partner_id)))


def verify_clash(clash_id, re_inspection_overlap_mm, coordinator_id="coord-2"):
    """Verify with a DIFFERENT coordinator than the assigner (SoD, PRD §3.4)."""
    return get_success_data(
        api_client.verify_clash(
            clash_id, {"re_inspection_overlap_mm": re_inspection_overlap_mm},
            make_bim_coordinator_headers(coordinator_id)))


def reopen_clash(clash_id, coordinator_id="coord-2"):
    return get_success_data(
        api_client.reopen_clash(clash_id, make_bim_coordinator_headers(coordinator_id)))


# ---------------------------------------------------------------------------
# Tier 2: meetings and commitments
# ---------------------------------------------------------------------------

def create_meeting(project_id, room_id="RM-1", starts_at=DEFAULT_MEETING_STARTS,
                   ends_at=DEFAULT_MEETING_ENDS):
    payload = create_meeting_payload(room_id=room_id, starts_at=starts_at,
                                     ends_at=ends_at)
    return get_success_data(api_client.create_coordination_meeting(project_id, payload,
                                                                   COORD))


def get_meeting(meeting_id):
    return get_success_data(api_client.get_coordination_meeting(meeting_id, COORD))


def start_meeting(meeting_id, coordinator_id="coord-1"):
    return get_success_data(
        api_client.start_meeting(meeting_id,
                                 make_bim_coordinator_headers(coordinator_id)))


def adjourn_meeting(meeting_id, coordinator_id="coord-1"):
    return get_success_data(
        api_client.adjourn_meeting(meeting_id,
                                   make_bim_coordinator_headers(coordinator_id)))


def create_in_session_meeting(project_id, room_id="RM-1",
                              starts_at=DEFAULT_MEETING_STARTS,
                              ends_at=DEFAULT_MEETING_ENDS, advance_clock_to=None):
    """Create a meeting and start it. If the window is in the future, pass
    advance_clock_to an instant inside [starts_at, ends_at) to move the
    logical clock there first."""
    meeting = create_meeting(project_id, room_id=room_id, starts_at=starts_at,
                             ends_at=ends_at)
    if advance_clock_to is not None:
        set_clock(advance_clock_to)
    return start_meeting(meeting["id"])


def create_commitment(meeting_id, clash_id, partner_id, due_at):
    payload = create_commitment_payload(clash_id, partner_id, due_at=due_at)
    return get_success_data(api_client.create_commitment(meeting_id, payload, COORD))


def get_commitment(commitment_id):
    return get_success_data(api_client.get_commitment(commitment_id, COORD))


def waive_commitment(commitment_id, coordinator_id="coord-1"):
    return get_success_data(
        api_client.waive_commitment(commitment_id,
                                    make_bim_coordinator_headers(coordinator_id)))


# ---------------------------------------------------------------------------
# Tier 2: fabrication packages and sign-offs
# ---------------------------------------------------------------------------

def create_package(project_id, fed_id, scope_disciplines, fabricator_id):
    """Create a DRAFT package; the FabricationLead's X-User-ID is the
    requesting partner id (recorded as requesting_partner_id)."""
    payload = create_fabrication_package_payload(fed_id, scope_disciplines)
    return get_success_data(
        api_client.create_fabrication_package(
            project_id, payload, make_fabrication_lead_headers(fabricator_id)))


def get_package(package_id):
    return get_success_data(api_client.get_fabrication_package(package_id, VDC))


def submit_package_for_signoff(package_id, fabricator_id):
    return get_success_data(
        api_client.submit_package_for_signoff(
            package_id, make_fabrication_lead_headers(fabricator_id)))


def release_package(package_id, fabricator_id):
    return get_success_data(
        api_client.release_fabrication_package(
            package_id, make_fabrication_lead_headers(fabricator_id)))


def void_package(package_id, fabricator_id):
    return get_success_data(
        api_client.void_fabrication_package(
            package_id, make_fabrication_lead_headers(fabricator_id)))


def list_package_signoffs(package_id):
    return get_success_data(api_client.list_package_signoffs(package_id, VDC))


def get_signoff(signoff_id):
    return get_success_data(api_client.get_signoff(signoff_id, VDC))


def sign_signoff(signoff_id, engineer_id="eng-1"):
    return get_success_data(
        api_client.sign_signoff(signoff_id, make_lead_engineer_headers(engineer_id)))


def decline_signoff(signoff_id, engineer_id="eng-1"):
    return get_success_data(
        api_client.decline_signoff(signoff_id, make_lead_engineer_headers(engineer_id)))


# ---------------------------------------------------------------------------
# Tier 2: as-built models
# ---------------------------------------------------------------------------

def create_as_built(project_id, model_id, partner_id, notes="field survey"):
    """Create a DRAFT as-built (ownership: caller is the basis partner)."""
    payload = create_as_built_payload(model_id, field_verification_notes=notes)
    return get_success_data(
        api_client.create_as_built_model(
            project_id, payload, make_trade_model_author_headers(partner_id)))


def submit_as_built(as_built_id, partner_id):
    return get_success_data(
        api_client.submit_as_built_model(
            as_built_id, make_trade_model_author_headers(partner_id)))


def verify_as_built(as_built_id, verification_deviation_mm):
    return get_success_data(
        api_client.verify_as_built_model(
            as_built_id, {"verification_deviation_mm": verification_deviation_mm}, VDC))


def get_as_built(as_built_id):
    return get_success_data(api_client.get_as_built_model(as_built_id, VDC))


# ---------------------------------------------------------------------------
# Tier 2: quantity takeoffs
# ---------------------------------------------------------------------------

def create_takeoff(project_id, fed_id, extraction_mode="GROSS", elements=None,
                   discipline_filter=None, expected_project_version=None):
    """Extract quantities (OCC-guarded; re-reads the project version when not
    supplied)."""
    if expected_project_version is None:
        expected_project_version = project_version(project_id)
    if elements is None:
        elements = [make_takeoff_element("E1", 1.0, 0.0)]
    payload = create_quantity_takeoff_payload(
        fed_id, extraction_mode, elements, expected_project_version,
        discipline_filter=discipline_filter)
    return get_success_data(api_client.create_quantity_takeoff(project_id, payload,
                                                               COORD))


def get_takeoff(takeoff_id):
    return get_success_data(api_client.get_quantity_takeoff(takeoff_id, VDC))


def approve_takeoff(takeoff_id):
    return get_success_data(api_client.approve_quantity_takeoff(takeoff_id, VDC))


# ---------------------------------------------------------------------------
# Tier 2: handover packages
# ---------------------------------------------------------------------------

def create_handover(project_id, takeoff_id, label="H1"):
    payload = create_handover_package_payload(takeoff_id, label=label)
    return get_success_data(api_client.create_handover_package(project_id, payload,
                                                               COORD))


def get_handover(handover_id):
    return get_success_data(api_client.get_handover_package(handover_id, COORD))


def mark_handover_ready(handover_id, coordinator_id="coord-1"):
    return get_success_data(
        api_client.mark_handover_ready(handover_id,
                                       make_bim_coordinator_headers(coordinator_id)))


def transmit_handover(handover_id, coordinator_id="coord-1"):
    return get_success_data(
        api_client.transmit_handover_package(
            handover_id, make_bim_coordinator_headers(coordinator_id)))


def respond_handover(handover_id, decision, fm_user_id="fm-1"):
    from .test_users import make_facilities_manager_headers
    return get_success_data(
        api_client.respond_handover_package(
            handover_id, {"decision": decision},
            make_facilities_manager_headers(fm_user_id)))


# ---------------------------------------------------------------------------
# Tier 3: full-lifecycle composite chains
# ---------------------------------------------------------------------------

def setup_accepted_model_scenario(project_name="BASE", partner_kwargs=None,
                                  model_kwargs=None):
    """Project + one ACTIVE partner + one ACCEPTED model revision.

    Returns {"project", "partner", "model"}.
    """
    project = create_project(project_name)
    partner = create_partner(project["id"], **(partner_kwargs or {}))
    model = create_and_accept_model(project["id"], partner["id"],
                                    **(model_kwargs or {}))
    return {"project": project, "partner": partner, "model": model}


def setup_frozen_assembly(project_name="BASE", partner_kwargs=None,
                          model_kwargs=None, fed_label="F1"):
    """setup_accepted_model_scenario + federated model over the accepted model,
    frozen. Returns the workspace dict with an added "fed" entry.

    The assembly is born ASSEMBLED (every member already ACCEPTED at creation)
    and then frozen.
    """
    ws = setup_accepted_model_scenario(project_name, partner_kwargs, model_kwargs)
    fed = create_federated_model(ws["project"]["id"], [ws["model"]["id"]],
                                 label=fed_label)
    ws["fed"] = freeze_fed(fed["id"])
    return ws


def setup_running_run(project_name="BASE", partner_kwargs=None, model_kwargs=None,
                      tolerance_mm=5.0):
    """setup_frozen_assembly + a clash run started (RUNNING).

    Returns the workspace dict with "fed" and "run" entries.
    """
    ws = setup_frozen_assembly(project_name, partner_kwargs, model_kwargs)
    run = create_clash_run(ws["fed"]["id"], tolerance_mm=tolerance_mm)
    ws["run"] = start_run(run["id"])
    return ws


def setup_assigned_clash(project_name="BASE", overlap_mm=30.0,
                         spans_disciplines=False, **kwargs):
    """setup_running_run + one imported clash assigned to the partner.

    Returns the workspace dict with an added "clash" entry (ASSIGNED).
    """
    ws = setup_running_run(project_name, **kwargs)
    clash = import_clash(ws["run"]["id"], "E/1", overlap_mm, spans_disciplines)
    ws["clash"] = assign_clash(clash["id"], ws["partner"]["id"])
    return ws


def setup_verified_clash(project_name="BASE", overlap_mm=30.0,
                         spans_disciplines=False, actual_labor_hours=1.0,
                         **kwargs):
    """setup_assigned_clash + resolve + passing verify. The clash is VERIFIED."""
    ws = setup_assigned_clash(project_name, overlap_mm=overlap_mm,
                              spans_disciplines=spans_disciplines, **kwargs)
    resolve_clash(ws["clash"]["id"], ws["partner"]["id"], actual_labor_hours)
    ws["clash"] = verify_clash(ws["clash"]["id"], 0.0)
    return ws


def setup_in_session_meeting_with_assigned_clash(project_name="BASE",
                                                 due_at="2026-08-11T00:00:00Z",
                                                 overlap_mm=10.0):
    """Running run + one ASSIGNED clash + an IN_SESSION meeting (window
    covering the default clock). Returns ws with "clash" and "meeting"."""
    ws = setup_assigned_clash(project_name, overlap_mm=overlap_mm)
    ws["meeting"] = create_in_session_meeting(ws["project"]["id"])
    ws["due_at"] = due_at
    return ws


# ---------------------------------------------------------------------------
# Tier 3: fabrication sign-off chain
# ---------------------------------------------------------------------------

def setup_package_in_signoff(project_name="PKG", scope=("STRUCTURAL",)):
    """Frozen assembly + DRAFT package submitted for sign-off.

    Returns {"project", "author" (model author partner), "fabricator",
             "model", "fed", "package", "signoffs"}.
    The fabricator is a second, MECHANICAL partner; its id is the package's
    requesting_partner_id.
    """
    ws = setup_frozen_assembly(project_name)
    ws["author"] = ws["partner"]
    ws["fabricator"] = create_partner(
        ws["project"]["id"], company_name="FabCo", discipline="MECHANICAL",
        hourly_rate_cents=10000, coordination_budget_hours=50.0,
        software_platform="TEKLA")
    package = create_package(ws["project"]["id"], ws["fed"]["id"],
                             list(scope), ws["fabricator"]["id"])
    ws["package"] = submit_package_for_signoff(package["id"],
                                               ws["fabricator"]["id"])
    ws["signoffs"] = list_package_signoffs(ws["package"]["id"])
    return ws


def setup_ready_package(project_name="PKG", scope=("STRUCTURAL",)):
    """setup_package_in_signoff with every sign-off SIGNED — the package sits
    at READY_FOR_RELEASE (signed_count == required_signoff_count)."""
    ws = setup_package_in_signoff(project_name, scope=scope)
    for signoff in ws["signoffs"]:
        sign_signoff(signoff["id"])
    ws["package"] = get_package(ws["package"]["id"])
    ws["signoffs"] = list_package_signoffs(ws["package"]["id"])
    return ws


def setup_two_member_ready_package(project_name="PKG2"):
    """Two disciplines (STRUCTURAL author + MECHANICAL fabricator-author),
    both models ACCEPTED, one frozen assembly over both, package with scope
    [STRUCTURAL, MECHANICAL] and both sign-offs SIGNED (READY_FOR_RELEASE).
    """
    project = create_project(project_name)
    p1 = create_partner(project["id"], company_name="StructCo",
                        discipline="STRUCTURAL", hourly_rate_cents=12000,
                        coordination_budget_hours=100.0, software_platform="REVIT")
    p2 = create_partner(project["id"], company_name="FabCo",
                        discipline="MECHANICAL", hourly_rate_cents=10000,
                        coordination_budget_hours=50.0, software_platform="TEKLA")
    m1 = create_and_accept_model(project["id"], p1["id"])
    m3 = create_and_accept_model(project["id"], p2["id"], file_format="IFC")
    fed = create_federated_model(project["id"], [m1["id"], m3["id"]])
    fed = freeze_fed(fed["id"])
    package = create_package(project["id"], fed["id"],
                             ["STRUCTURAL", "MECHANICAL"], p2["id"])
    package = submit_package_for_signoff(package["id"], p2["id"])
    signoffs = list_package_signoffs(package["id"])
    for signoff in signoffs:
        sign_signoff(signoff["id"], engineer_id="eng-2")
    package = get_package(package["id"])
    return {"project": project, "author": p1, "fabricator": p2,
            "model": m1, "model2": m3, "fed": fed, "package": package,
            "signoffs": list_package_signoffs(package["id"])}


# ---------------------------------------------------------------------------
# Tier 4: threshold / accumulation targeting
# ---------------------------------------------------------------------------

def breach_partner_by_sweep(project_id, meeting_id, clash_id, partner_id,
                            breach_count, due_at="2026-08-11T00:00:00Z",
                            sweep_clock="2026-08-12T00:00:00Z"):
    """Create `breach_count` COMMITTED commitments (all on the given ASSIGNED
    clash, all due at `due_at`), advance the clock past the deadline, and run
    the coordination sweep once. Returns the partner after the sweep.

    Reliability walk (tier read from the pre-event score, PRD §3.5):
    breaches 1-5 cost 5 each (score >= 80), 6-8 cost 10 (50 <= score < 80),
    breach 9+ costs 20 (score < 50).
    """
    for _ in range(breach_count):
        create_commitment(meeting_id, clash_id, partner_id, due_at)
    set_clock(sweep_clock)
    run_coordination_sweep(project_id)
    return get_partner(project_id, partner_id)


def setup_partner_with_reliability(project_name="REL", breach_count=0):
    """Project + partner + accepted model + frozen fed + running run with one
    MINOR clash assigned to the partner + an IN_SESSION meeting, followed by
    `breach_count` swept breaches on that clash's commitments.

    breach_count=8 leaves the partner at reliability 45 (still ACTIVE);
    breach_count=9 leaves it at 25 (PROBATION). The meeting window is
    2026-08-10T09:00-10:00 and the clock is advanced to 09:30 before the
    meeting starts, so commitments can be recorded while IN_SESSION.
    Returns ws with "project", "partner", "model", "fed", "run", "clash",
    "meeting".
    """
    ws = setup_assigned_clash(project_name, overlap_mm=0.0)
    meeting = create_meeting(ws["project"]["id"], room_id="RM-A",
                             starts_at="2026-08-10T09:00:00Z",
                             ends_at="2026-08-10T10:00:00Z")
    set_clock("2026-08-10T09:30:00Z")
    ws["meeting"] = start_meeting(meeting["id"])
    if breach_count:
        breach_partner_by_sweep(
            ws["project"]["id"], ws["meeting"]["id"], ws["clash"]["id"],
            ws["partner"]["id"], breach_count)
        ws["partner"] = get_partner(ws["project"]["id"], ws["partner"]["id"])
    return ws


def setup_probation_partner_via_reopen(project_name="PROB"):
    """Drive the partner to PROBATION through the reopen cascade (PRD §3.4
    reopen -> FULFILLED commitment BREACHED -> reliability decay, PRD §3.5).

    Chain: 8 swept breaches leave the partner at 45 (ACTIVE); a MINOR clash
    is resolved, verified (fulfilling its commitment), then reopened — the
    reopen breaches the fulfilled commitment, a 45-point pre-event score is
    tier C (-20), and 25 < 40 flips the partner to PROBATION.

    Returns ws with "project", "partner" (PROBATION), "model", "fed", "run"
    (still RUNNING), "meeting", "clash" (the breached one), "commitment",
    plus "reopened_clash".
    """
    ws = setup_partner_with_reliability(project_name, breach_count=8)
    clash = import_clash(ws["run"]["id"], "E/9", 0.0)
    assign_clash(clash["id"], ws["partner"]["id"])
    # The commitment must be recorded while the clash is ASSIGNED (PRD §3.5) —
    # before the resolve moves it to RESOLVED.
    commitment = create_commitment(ws["meeting"]["id"], clash["id"],
                                   ws["partner"]["id"], "2026-09-01T00:00:00Z")
    resolve_clash(clash["id"], ws["partner"]["id"], 1.0)
    verify_clash(clash["id"], 0.0)
    ws["commitment"] = commitment
    ws["reopened_clash"] = reopen_clash(clash["id"])
    ws["partner"] = get_partner(ws["project"]["id"], ws["partner"]["id"])
    return ws


# ---------------------------------------------------------------------------
# Tier 5: closeout / terminal-state chains
# ---------------------------------------------------------------------------

def setup_released_fed_with_approved_takeoff(project_name="CLOSE"):
    """Frozen assembly -> released -> GROSS takeoff -> approved.
    Returns ws with "project", "partner", "model", "fed", "takeoff"."""
    ws = setup_frozen_assembly(project_name)
    ws["fed"] = release_fed(ws["fed"]["id"])
    takeoff = create_takeoff(ws["project"]["id"], ws["fed"]["id"], "GROSS",
                             [make_takeoff_element("E1", 2.0, 0.0)])
    ws["takeoff"] = approve_takeoff(takeoff["id"])
    return ws


def setup_closeout_project_with_verified_asbuilt(project_name="CLOSE"):
    """Full closeout precondition chain: APPROVED takeoff, phase CLOSEOUT,
    one FIELD_VERIFIED as-built. Returns ws with an added "asbuilt"."""
    ws = setup_released_fed_with_approved_takeoff(project_name)
    advance_phase_to(ws["project"]["id"], PHASE_ORDER[-1])
    as_built = create_as_built(ws["project"]["id"], ws["model"]["id"],
                               ws["partner"]["id"])
    submit_as_built(as_built["id"], ws["partner"]["id"])
    ws["asbuilt"] = verify_as_built(as_built["id"], 10.0)
    ws["project"] = get_project(ws["project"]["id"])
    return ws


def setup_ready_handover(project_name="CLOSE"):
    """setup_closeout_project_with_verified_asbuilt + a handover package
    marked READY. Returns ws with "handover"."""
    ws = setup_closeout_project_with_verified_asbuilt(project_name)
    handover = create_handover(ws["project"]["id"], ws["takeoff"]["id"])
    ws["handover"] = mark_handover_ready(handover["id"])
    return ws
