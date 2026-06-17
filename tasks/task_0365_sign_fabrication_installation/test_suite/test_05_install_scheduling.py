"""Install-job scheduling: equipment-class derivation, equipment/crew booking
conflicts, dispatch certification gates, and install input validation.

Covers equipment_requirement boundaries, resource_temporal_overlap, the
referential-vs-temporal priority pair, the dual-variant warranty/equipment
instance, and install-related corner validations.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_ready_for_install_project, create_installed_project,
    create_fabrication_project, register_crew, register_equipment,
    schedule_install_job, create_install_job_payload, create_passed_survey,
    set_clock,
    TEST_USERS,
)

SM = TEST_USERS["shop_manager_headers"]


# ═══ Queue A: boundary_precision_check / equipment_requirement_ladder_max ══════

def test_equipment_requirement_ladder_at_exactly_20ft(api):
    """PRD §3.5: "a placement height above 8 feet but at most 20 feet needs a
    LADDER, and the lower edge of each tier is inclusive so that exactly 20 feet
    with no obstruction still resolves to LADDER."

    Design: Difficulty/boundary_precision_check/equipment_requirement_ladder_max_inclusive_boundary
    """
    project, estimate, survey, wo = create_ready_for_install_project(
        placement_height_ft=20, survey_overhead_obstruction=False,
        customer_name="Ladder Co", site_address="20 Reach Rd")
    crew = register_crew(name="Crew M", certified_aerial=False)
    equip = register_equipment(asset_tag="LAD-2", equipment_class="LADDER", max_reach_ft=24)
    job = validate_success(api.create_install_job(
        project["id"], create_install_job_payload(
            wo["id"], crew["id"], "2026-06-05T09:00:00Z", "2026-06-05T10:00:00Z",
            equipment_id=equip["id"]), SM), 201)
    assert job["required_equipment_class"] == "LADDER"


def test_equipment_requirement_bucket_truck_above_20ft(api):
    """PRD §3.5: "Anything requiring more than ladder height, or any obstruction
    case, lands on BUCKET_TRUCK."

    Design: Difficulty/boundary_precision_check/equipment_requirement_ladder_max_inclusive_boundary
    """
    project, estimate, survey, wo = create_ready_for_install_project(
        placement_height_ft=21, survey_overhead_obstruction=False,
        customer_name="Bucket Co", site_address="21 Reach Rd")
    crew = register_crew(name="Crew B", certified_aerial=True)
    equip = register_equipment(asset_tag="BT-21", equipment_class="BUCKET_TRUCK", max_reach_ft=40)
    job = validate_success(api.create_install_job(
        project["id"], create_install_job_payload(
            wo["id"], crew["id"], "2026-06-05T09:00:00Z", "2026-06-05T10:00:00Z",
            equipment_id=equip["id"]), SM), 201)
    assert job["required_equipment_class"] == "BUCKET_TRUCK"


# ═══ Queue A: dual_variant_calc / warranty_coverage_vs_equipment_requirement ══

def test_dual_threshold_equipment_class_bucket_truck(api):
    """PRD §3.5: "When the survey reports an overhead obstruction, the class is
    forced to BUCKET_TRUCK regardless of height" — here a 25-foot placement also
    resolves to BUCKET_TRUCK by height. PRD §3.5: "a placement height above 8 feet
    but at most 20 feet needs a LADDER" and anything above lands on BUCKET_TRUCK.

    Design: Difficulty/dual_variant_calc/warranty_coverage_vs_equipment_requirement_dual_threshold_domains
    """
    set_clock("2026-06-01T10:00:00Z")
    project, wo, crew, equip, job = create_installed_project(
        placement_height_ft=25, equipment_class="BUCKET_TRUCK", equipment_reach=40,
        certified_aerial=True, window_start_iso="2026-06-01T09:00:00Z",
        window_end_iso="2026-06-01T10:00:00Z",
        customer_name="Tall Co", site_address="9 High Rd")
    assert job["required_equipment_class"] == "BUCKET_TRUCK"


def test_dual_threshold_warranty_covered_true_within_window(api):
    """PRD §3.7: "The claim is covered when reported_iso falls strictly before the
    install date plus the coverage-window days." PRD §3.7: "COSMETIC for 90 days."

    Design: Difficulty/dual_variant_calc/warranty_coverage_vs_equipment_requirement_dual_threshold_domains
    """
    set_clock("2026-06-01T10:00:00Z")
    project, wo, crew, equip, job = create_installed_project(
        placement_height_ft=25, equipment_class="BUCKET_TRUCK", equipment_reach=40,
        certified_aerial=True, window_start_iso="2026-06-01T09:00:00Z",
        window_end_iso="2026-06-01T10:00:00Z",
        customer_name="Tall2 Co", site_address="9 High Rd")
    claim = validate_success(api.create_warranty_claim(
        project["id"],
        {"install_job_id": job["id"], "defect_kind": "COSMETIC",
         "reported_iso": "2026-07-01T10:00:00Z"}, SM), 201)
    assert claim["covered"] is True


# ═══ Queue A: cross_entity_state_dependency / install_dispatch_requires_cert ══

def test_dispatch_bucket_truck_uncertified_crew_rejected(api):
    """PRD §3.5: "a job whose required_equipment_class is BUCKET_TRUCK demands a
    crew whose certified_aerial flag is true, failing which dispatch is rejected
    with ERR_CREW_NOT_CERTIFIED."

    Design: Difficulty/cross_entity_state_dependency/install_dispatch_requires_crew_certified_for_bucket_truck
    """
    project, estimate, survey, wo = create_ready_for_install_project(
        placement_height_ft=25, customer_name="Cert Co", site_address="25 Lift Rd")
    crew = register_crew(name="Ground Crew", certified_aerial=False)
    equip = register_equipment(asset_tag="BT-3", equipment_class="BUCKET_TRUCK", max_reach_ft=40)
    job = get_success_data(api.create_install_job(
        project["id"], create_install_job_payload(
            wo["id"], crew["id"], "2026-06-06T09:00:00Z", "2026-06-06T10:00:00Z",
            equipment_id=equip["id"]), SM))
    res = api.dispatch_install_job(project["id"], job["id"], SM)
    validate_error(res, "ERR_CREW_NOT_CERTIFIED")


def test_dispatch_bucket_truck_certified_crew_succeeds(api):
    """PRD §3.5: "A ShopManager dispatches a SCHEDULED job, moving it
    SCHEDULED → DISPATCHED, but only if the crew is available and certified for
    the work."

    Design: Difficulty/cross_entity_state_dependency/install_dispatch_requires_crew_certified_for_bucket_truck
    """
    project, estimate, survey, wo = create_ready_for_install_project(
        placement_height_ft=25, customer_name="Cert2 Co", site_address="25 Lift Rd")
    crew = register_crew(name="Aerial Crew", certified_aerial=True)
    equip = register_equipment(asset_tag="BT-4", equipment_class="BUCKET_TRUCK", max_reach_ft=40)
    job = get_success_data(api.create_install_job(
        project["id"], create_install_job_payload(
            wo["id"], crew["id"], "2026-06-06T09:00:00Z", "2026-06-06T10:00:00Z",
            equipment_id=equip["id"]), SM))
    dispatched = validate_success(api.dispatch_install_job(project["id"], job["id"], SM), 200)
    assert dispatched["status"] == "DISPATCHED"


# ═══ Queue A: resource_temporal_overlap / equipment_half_open_interval ════════

def _ready_bucket_project(name, addr):
    project, estimate, survey, wo = create_ready_for_install_project(
        placement_height_ft=25, customer_name=name, site_address=addr)
    return project, wo


def test_equipment_double_booked_overlapping_window_rejected(api):
    """PRD §3.5: "The chosen equipment may not collide with another active install
    job: if its window overlaps an existing booking on the half-open interval from
    start (inclusive) to end (exclusive), the schedule is rejected with
    ERR_EQUIPMENT_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/equipment_half_open_interval_overlap
    """
    equip = register_equipment(asset_tag="BT-SHARED", equipment_class="BUCKET_TRUCK", max_reach_ft=40)
    p1, wo1 = _ready_bucket_project("Eq P1", "30 Truck Rd")
    crew1 = register_crew(name="Crew E1", certified_aerial=True)
    schedule_install_job(p1["id"], wo1["id"], crew1["id"],
                         "2026-06-07T09:00:00Z", "2026-06-07T10:00:00Z", equipment_id=equip["id"])

    p2, wo2 = _ready_bucket_project("Eq P2", "31 Truck Rd")
    crew2 = register_crew(name="Crew E2", certified_aerial=True)
    res = api.create_install_job(p2["id"], create_install_job_payload(
        wo2["id"], crew2["id"], "2026-06-07T09:30:00Z", "2026-06-07T10:30:00Z",
        equipment_id=equip["id"]), SM)
    validate_error(res, "ERR_EQUIPMENT_DOUBLE_BOOKED")


def test_equipment_abutting_window_does_not_collide(api):
    """PRD §3.5: overlap is "on the half-open interval from start (inclusive) to
    end (exclusive)" — an abutting job whose start equals the prior job's end does
    not overlap and is accepted.

    Design: Difficulty/resource_temporal_overlap/equipment_half_open_interval_overlap
    """
    equip = register_equipment(asset_tag="BT-ABUT", equipment_class="BUCKET_TRUCK", max_reach_ft=40)
    p1, wo1 = _ready_bucket_project("Eq A1", "32 Truck Rd")
    crew1 = register_crew(name="Crew A1", certified_aerial=True)
    schedule_install_job(p1["id"], wo1["id"], crew1["id"],
                         "2026-06-07T09:00:00Z", "2026-06-07T10:00:00Z", equipment_id=equip["id"])

    p2, wo2 = _ready_bucket_project("Eq A2", "33 Truck Rd")
    crew2 = register_crew(name="Crew A2", certified_aerial=True)
    job2 = validate_success(api.create_install_job(p2["id"], create_install_job_payload(
        wo2["id"], crew2["id"], "2026-06-07T10:00:00Z", "2026-06-07T11:00:00Z",
        equipment_id=equip["id"]), SM), 201)
    assert job2["status"] == "SCHEDULED"


# ═══ Queue A: resource_temporal_overlap / crew_buffered_interval_overlap ══════

def test_crew_double_booked_insufficient_buffer_rejected(api):
    """PRD §3.5: "The chosen crew is held to a same-day rule: if it already has an
    overlapping window on the same day, or one that sits too close without the
    required buffer between adjacent jobs, the schedule is rejected with
    ERR_CREW_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/crew_buffered_interval_overlap
    """
    crew = register_crew(name="Shared Crew", certified_aerial=True)
    p1, wo1 = _ready_bucket_project("Cr P1", "40 Crew Rd")
    eq1 = register_equipment(asset_tag="BT-8", equipment_class="BUCKET_TRUCK", max_reach_ft=40)
    schedule_install_job(p1["id"], wo1["id"], crew["id"],
                         "2026-06-08T08:00:00Z", "2026-06-08T09:30:00Z", equipment_id=eq1["id"])

    p2, wo2 = _ready_bucket_project("Cr P2", "41 Crew Rd")
    eq2 = register_equipment(asset_tag="BT-9", equipment_class="BUCKET_TRUCK", max_reach_ft=40)
    res = api.create_install_job(p2["id"], create_install_job_payload(
        wo2["id"], crew["id"], "2026-06-08T10:00:00Z", "2026-06-08T11:00:00Z",
        equipment_id=eq2["id"]), SM)
    validate_error(res, "ERR_CREW_DOUBLE_BOOKED")


def test_crew_overlapping_same_day_window_rejected(api):
    """PRD §3.5: "if it already has an overlapping window on the same day... the
    schedule is rejected with ERR_CREW_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/crew_buffered_interval_overlap
    """
    crew = register_crew(name="Shared Crew 2", certified_aerial=True)
    p1, wo1 = _ready_bucket_project("Cr O1", "42 Crew Rd")
    eq1 = register_equipment(asset_tag="BT-10", equipment_class="BUCKET_TRUCK", max_reach_ft=40)
    schedule_install_job(p1["id"], wo1["id"], crew["id"],
                         "2026-06-08T08:00:00Z", "2026-06-08T09:30:00Z", equipment_id=eq1["id"])

    p2, wo2 = _ready_bucket_project("Cr O2", "43 Crew Rd")
    eq2 = register_equipment(asset_tag="BT-11", equipment_class="BUCKET_TRUCK", max_reach_ft=40)
    res = api.create_install_job(p2["id"], create_install_job_payload(
        wo2["id"], crew["id"], "2026-06-08T09:00:00Z", "2026-06-08T10:00:00Z",
        equipment_id=eq2["id"]), SM)
    validate_error(res, "ERR_CREW_DOUBLE_BOOKED")


# ═══ Queue A: priority_pair_validation_conflict / referential_before_temporal ══

def test_install_create_reference_not_eligible_beats_double_book(api):
    """PRD §3.9: "Only after these structural checks do the business rules run:
    referential eligibility (ERR_REFERENCE_NOT_ELIGIBLE)... the equipment and crew
    booking conflicts." PRD §3.5: "The referenced work order must be in
    READY_FOR_INSTALL; otherwise the schedule is rejected with
    ERR_REFERENCE_NOT_ELIGIBLE."

    Design: Difficulty/priority_pair_validation_conflict/referential_before_temporal_on_install_create
    """
    equip = register_equipment(asset_tag="BT-CLASH", equipment_class="BUCKET_TRUCK", max_reach_ft=40)
    # P1 holds the equipment 09:00-10:00 with a real READY_FOR_INSTALL WO.
    p1, wo1 = _ready_bucket_project("Dbl P1", "10 Clash Rd")
    crew1 = register_crew(name="Aerial A", certified_aerial=True)
    schedule_install_job(p1["id"], wo1["id"], crew1["id"],
                         "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z", equipment_id=equip["id"])

    # P2 is only at FABRICATION with a RELEASED (not READY_FOR_INSTALL) WO.
    p2, estimate2, survey2, wo2 = create_fabrication_project(
        placement_height_ft=25, customer_name="Dbl P2", site_address="11 Clash Rd")
    crew2 = register_crew(name="Aerial B", certified_aerial=True)
    res = api.create_install_job(p2["id"], create_install_job_payload(
        wo2["id"], crew2["id"], "2026-06-02T09:30:00Z", "2026-06-02T10:30:00Z",
        equipment_id=equip["id"]), SM)
    validate_error(res, "ERR_REFERENCE_NOT_ELIGIBLE")


def test_install_create_against_released_work_order_rejected(api):
    """PRD §3.5: "The referenced work order must be in READY_FOR_INSTALL;
    otherwise the schedule is rejected with ERR_REFERENCE_NOT_ELIGIBLE."

    Design: Difficulty/priority_pair_validation_conflict/referential_before_temporal_on_install_create
    """
    project, estimate, survey, wo = create_fabrication_project(
        placement_height_ft=25, customer_name="Rel Ref Co", site_address="12 Clash Rd")
    crew = register_crew(name="Aerial C", certified_aerial=True)
    equip = register_equipment(asset_tag="BT-REL", equipment_class="BUCKET_TRUCK", max_reach_ft=40)
    res = api.create_install_job(project["id"], create_install_job_payload(
        wo["id"], crew["id"], "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z",
        equipment_id=equip["id"]), SM)
    validate_error(res, "ERR_REFERENCE_NOT_ELIGIBLE")


# ═══ Queue B: corner calculations / validations (install) ════════════════════

def test_obstruction_forces_bucket_truck_at_low_placement(api):
    """PRD §3.5: "When the survey reports an overhead obstruction, the class is
    forced to BUCKET_TRUCK regardless of height — even when the placement height
    would otherwise sit in the ladder range."

    Design: Corner/calculations/equipment_requirement_obstruction_forces_bucket_truck
    """
    project, estimate, survey, wo = create_ready_for_install_project(
        placement_height_ft=6, survey_overhead_obstruction=True,
        customer_name="Obs Co", site_address="18 Wire St")
    crew = register_crew(name="Crew Obs", certified_aerial=True)
    equip = register_equipment(asset_tag="BT-Obs", equipment_class="BUCKET_TRUCK", max_reach_ft=40)
    job = validate_success(api.create_install_job(
        project["id"], create_install_job_payload(
            wo["id"], crew["id"], "2026-06-12T09:00:00Z", "2026-06-12T10:00:00Z",
            equipment_id=equip["id"]), SM), 201)
    assert job["required_equipment_class"] == "BUCKET_TRUCK"


def test_dispatch_inactive_crew_rejected(api):
    """PRD §3.5: "a crew whose active flag is false is rejected with
    ERR_CREW_UNAVAILABLE."

    Design: Corner/validations/dispatch_inactive_crew_rejected
    """
    project, estimate, survey, wo = create_ready_for_install_project(
        placement_height_ft=12, customer_name="Inact Co", site_address="22 Off St")
    crew = register_crew(name="Crew Off", certified_aerial=False, active=True)
    equip = register_equipment(asset_tag="LAD-Off", equipment_class="LADDER", max_reach_ft=16)
    job = get_success_data(api.create_install_job(
        project["id"], create_install_job_payload(
            wo["id"], crew["id"], "2026-06-13T09:00:00Z", "2026-06-13T10:00:00Z",
            equipment_id=equip["id"]), SM))
    api.update_crew(crew["id"], {"active": False}, SM)
    res = api.dispatch_install_job(project["id"], job["id"], SM)
    validate_error(res, "ERR_CREW_UNAVAILABLE")


def test_install_bucket_truck_without_equipment_rejected(api):
    """PRD §3.5: "When the derived class is not NONE, equipment_id is required...
    A missing or mismatched equipment selection is rejected with
    ERR_EQUIPMENT_REQUIRED."

    Design: Corner/validations/install_create_bucket_truck_without_equipment_rejected
    """
    project, estimate, survey, wo = create_ready_for_install_project(
        placement_height_ft=25, customer_name="NoEq Co", site_address="23 Bare St")
    crew = register_crew(name="Crew NoEq", certified_aerial=True)
    res = api.create_install_job(project["id"], create_install_job_payload(
        wo["id"], crew["id"], "2026-06-14T09:00:00Z", "2026-06-14T10:00:00Z"), SM)
    validate_error(res, "ERR_EQUIPMENT_REQUIRED")


def test_install_window_end_before_start_rejected(api):
    """PRD §3.5: "The window must be coherent: window_end_iso must be strictly
    later than window_start_iso, or the request is rejected with
    ERR_INVALID_REQUEST."

    Design: Corner/validations/install_create_window_end_before_start_rejected
    """
    project, estimate, survey, wo = create_ready_for_install_project(
        placement_height_ft=12, customer_name="Win Co", site_address="24 Time St")
    crew = register_crew(name="Crew Win", certified_aerial=False)
    equip = register_equipment(asset_tag="LAD-Win", equipment_class="LADDER", max_reach_ft=16)
    res = api.create_install_job(project["id"], create_install_job_payload(
        wo["id"], crew["id"], "2026-06-15T10:00:00Z", "2026-06-15T09:00:00Z",
        equipment_id=equip["id"]), SM)
    validate_error(res, "ERR_INVALID_REQUEST")
