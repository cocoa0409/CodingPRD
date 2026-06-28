"""Difficulty queue (A): validation precedence, cross-entity gating, temporal windows,
empty-set boundary.

Covers rules priority_pair_validation_conflict, cross_entity_state_dependency,
resource_temporal_overlap, and the zero-count arm of boundary_precision_check, plus
corner-queue validations / errors / rbac / endpoints / entities breadth probes.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    setup_completed_order,
    setup_draft_clearance,
    setup_passed_clearance,
    setup_verified_project,
    create_project,
    create_worker,
    create_assessment,
    create_active_zone,
    create_zone,
    create_analyzed_air_sample,
    set_clock,
    get_project_version,
    create_project_payload,
    create_worker_payload,
    create_abatement_order_payload,
    create_assignment_payload,
    create_manifest_payload,
    create_sample_payload,
    create_clearance_test_payload,
    create_permit_payload,
    create_pressure_log_payload,
    create_insurance_claim_payload,
    build_user_headers,
    NON_EXISTENT_UUID,
    TEST_USERS,
)

PM = TEST_USERS["project_manager_headers"]
AS = TEST_USERS["abatement_supervisor_headers"]
LT = TEST_USERS["lab_tech_headers"]
HY = TEST_USERS["hygienist_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# ===========================================================================
# Difficulty/priority_pair_validation_conflict
# ===========================================================================
def test_occ_stale_outranks_signoff_independence(api):
    """PRD §2.7: "the optimistic-concurrency check where it applies
    (`ERR_STALE_VERSION`); the state-machine guard that the target is in a state from
    which the transition is defined (`ERR_INVALID_STATE`); and finally the
    operation-specific business and safety rules described throughout Section 3."
    PRD §2.6: "Before any business rule is evaluated, the server compares
    `expected_project_version` against the project's current `version`. If they do not
    match ... the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    The signoff names a non-independent signer (the sampler) AND carries a stale
    version; the OCC check (evaluated before business rules) wins -> ERR_STALE_VERSION.

    Design: Difficulty/priority_pair_validation_conflict/occ_stale_outranks_signoff_independence
    """
    # Sampler is a HYGIENIST so only the OCC and independence checks would fire.
    set_clock()
    lead = create_worker(cert_type="MOLD", full_name="Lead Mold")
    sampler = create_worker(cert_type="HYGIENIST", full_name="Sampler Hyg")
    project = create_project(hazard_class="MOLD", site_name="Pri Site")
    zone = create_active_zone(project["id"])
    order = get_success_data(api.create_abatement_order(
        create_abatement_order_payload(project["id"], zone["id"], lead["id"],
                                       abatement_type="MOLD", planned_weight_kg=50), AS))
    get_success_data(api.create_assignment(create_assignment_payload(order["id"], lead["id"]), AS))
    get_success_data(api.start_abatement_order(order["id"], AS))
    man = get_success_data(api.create_manifest(
        create_manifest_payload(order["id"], project["id"], manifest_weight_kg=50), AS))
    get_success_data(api.submit_manifest(man["id"], AS))
    get_success_data(api.accept_manifest(man["id"], PM))
    get_success_data(api.complete_abatement_order(order["id"], {"removed_weight_kg": 50}, AS))
    clearance = get_success_data(api.create_clearance_test(
        create_clearance_test_payload(project["id"], zone["id"], order["id"], sampler["id"],
                                      clearance_air_count=10, clearance_volume_liters=100), LT))
    get_success_data(api.analyze_clearance_test(clearance["id"], LT))  # -> PASSED
    pv = get_project_version(project["id"])
    # Stale version (pv - 1) AND non-independent signer (the sampler).
    res = api.signoff_clearance_test(
        clearance["id"],
        {"signoff_worker_id": sampler["id"], "expected_project_version": pv - 1}, HY)
    validate_error(res, "ERR_STALE_VERSION")


def test_invalid_state_outranks_zone_not_active_on_complete(api):
    """PRD §2.7: "the state-machine guard that the target is in a state from which the
    transition is defined (`ERR_INVALID_STATE`); and finally the operation-specific
    business and safety rules described throughout Section 3."
    PRD §3.5: "An `AbatementSupervisor` completes an `IN_PROGRESS` order ... Completion
    further requires that the referenced zone still be `ACTIVE` (else
    `ERR_ZONE_NOT_ACTIVE`)".

    Completing a PLANNED order in a SETUP zone fails both the state guard and the
    zone-active rule; the state guard (checked first) wins -> ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_outranks_zone_not_active_on_complete
    """
    set_clock()
    lead = create_worker(cert_type="MOLD", full_name="Lead Mold")
    project = create_project(hazard_class="MOLD", site_name="State Site")
    zone = create_zone(project["id"])  # left SETUP
    order = get_success_data(api.create_abatement_order(
        create_abatement_order_payload(project["id"], zone["id"], lead["id"],
                                       abatement_type="MOLD", planned_weight_kg=50), AS))
    res = api.complete_abatement_order(order["id"], {"removed_weight_kg": 50}, AS)
    validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# Difficulty/cross_entity_state_dependency
# ===========================================================================
def test_abatement_start_requires_zone_active(api):
    """PRD §3.5: "the referenced zone must be `ACTIVE` (else `ERR_ZONE_NOT_ACTIVE`)".

    Starting an order in a SETUP zone (never activated), with a certified lead and an
    assigned certified crew, fails with ERR_ZONE_NOT_ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/abatement_start_requires_zone_active
    """
    set_clock()
    lead = create_worker(cert_type="MOLD", full_name="Lead Mold")
    project = create_project(hazard_class="MOLD", site_name="Zone Site")
    zone = create_zone(project["id"])  # SETUP
    order = get_success_data(api.create_abatement_order(
        create_abatement_order_payload(project["id"], zone["id"], lead["id"],
                                       abatement_type="MOLD", planned_weight_kg=50), AS))
    get_success_data(api.create_assignment(create_assignment_payload(order["id"], lead["id"]), AS))
    res = api.start_abatement_order(order["id"], AS)
    validate_error(res, "ERR_ZONE_NOT_ACTIVE")


def test_insurance_submit_requires_project_posture_ready(api):
    """PRD §3.9: "A `ProjectManager` submits an `OPEN` claim only when the project
    posture is `CLEARANCE_PENDING` or `VERIFIED` (otherwise
    `ERR_PROJECT_NOT_READY_FOR_BILLING`)".

    A fresh project (posture ASSESSMENT) blocks claim submission.

    Design: Difficulty/cross_entity_state_dependency/insurance_submit_requires_project_posture_ready
    """
    set_clock()
    project = create_project(hazard_class="MOLD", site_name="Bill Site")
    claim = get_success_data(api.create_insurance_claim(
        create_insurance_claim_payload(project["id"], policy_number="POL-9",
                                       deductible_cents=0, coverage_limit_cents=100000), PM))
    res = api.submit_insurance_claim(claim["id"], PM)
    validate_error(res, "ERR_PROJECT_NOT_READY_FOR_BILLING")


# ===========================================================================
# Difficulty/resource_temporal_overlap
# ===========================================================================
def test_neshap_notice_lead_window_too_short_blocks_submit(api):
    """PRD §3.7: "Submitting a `DRAFT` permit is unconditional except for a
    `NESHAP_NOTIFICATION`, whose `notice_days` must be at least 10 at submission time,
    otherwise the submission is rejected with `ERR_NESHAP_NOTICE_NOT_MET`."

    A NESHAP permit postmarked 2026-01-01 with work_start 2026-01-08 -> notice_days 7
    (< 10) is rejected at submit.

    Design: Difficulty/resource_temporal_overlap/neshap_notice_lead_window_too_short_blocks_submit
    """
    set_clock()
    project = create_project(hazard_class="ASBESTOS", site_name="Permit Site")
    permit = get_success_data(api.create_permit(
        create_permit_payload(project["id"], permit_type="NESHAP_NOTIFICATION",
                              postmarked_at="2026-01-01T00:00:00Z",
                              work_start_at="2026-01-08T00:00:00Z"), CO))
    assert permit["notice_days"] == 7
    res = api.submit_permit(permit["id"], CO)
    validate_error(res, "ERR_NESHAP_NOTICE_NOT_MET")


def test_latest_pressure_reading_below_required_breaches_active_zone(api):
    """PRD §3.4: "Each new reading recomputes the zone's `latest_pressure_pa`, defined
    as the `reading_pa` of the zone's reading with the greatest `reading_at`, breaking
    ties by the greatest `created_at`".
    PRD §3.4: "If the zone is currently `ACTIVE` and the recomputed reading leaves it
    not compliant, the zone transitions `ACTIVE → BREACHED`, `is_compliant` is set
    false, and the project's posture is recomputed — a breach freezes the project to
    `FROZEN`, which outranks `ABATING`."

    A later reading of 4 (at 10:00) supersedes the earlier compliant 12 (at 08:00) and
    breaches the ACTIVE zone.

    Design: Difficulty/resource_temporal_overlap/latest_pressure_reading_below_required_breaches_active_zone
    """
    set_clock()
    project = create_project(hazard_class="MOLD", site_name="Pressure Site")
    zone = create_active_zone(project["id"], reading_pa=12, reading_at="2026-01-14T08:00:00Z")
    get_success_data(api.create_pressure_log(
        zone["id"], create_pressure_log_payload(zone["id"], reading_pa=4,
                                                reading_at="2026-01-14T10:00:00Z"), AS))
    rezone = validate_success(api.get_zone(zone["id"], PM), 200)
    assert rezone["latest_pressure_pa"] == 4
    assert rezone["is_compliant"] is False
    assert rezone["status"] == "BREACHED"
    reproject = validate_success(api.get_project(project["id"], PM), 200)
    assert reproject["posture"] == "FROZEN"


# ===========================================================================
# Difficulty/boundary_precision_check (zero-count arm)
# ===========================================================================
def test_zero_active_certified_assignments_blocks_start(api):
    """PRD §3.5: "at least one `ACTIVE` worker assignment on the order must belong to
    a worker whose certification is current (else `ERR_NO_CERTIFIED_CREW`)."

    Starting an order with zero worker assignments (empty crew set) is rejected.

    Design: Difficulty/boundary_precision_check/zero_active_certified_assignments_blocks_start
    """
    set_clock()
    lead = create_worker(cert_type="MOLD", full_name="Lead Mold")
    project = create_project(hazard_class="MOLD", site_name="Crew Site")
    zone = create_active_zone(project["id"])
    order = get_success_data(api.create_abatement_order(
        create_abatement_order_payload(project["id"], zone["id"], lead["id"],
                                       abatement_type="MOLD", planned_weight_kg=50), AS))
    # No assignment created.
    res = api.start_abatement_order(order["id"], AS)
    validate_error(res, "ERR_NO_CERTIFIED_CREW")


# ===========================================================================
# Corner/validations
# ===========================================================================
def test_sample_collected_at_in_future_returns_409(api):
    """PRD §3.3: "A `collected_at` after the logical clock's current instant is
    rejected with `ERR_TIMESTAMP_IN_FUTURE`."

    Design: Corner/validations/sample_collected_at_in_future_returns_409
    """
    set_clock()
    assessor = create_worker(cert_type="MOLD", full_name="A")
    project = create_project(hazard_class="MOLD")
    assessment = create_assessment(project["id"], assessor["id"])
    res = api.create_sample(
        create_sample_payload(assessment["id"], project["id"], "AIR",
                              collected_at="2027-01-01T00:00:00Z", volume_liters=100), LT)
    validate_error(res, "ERR_TIMESTAMP_IN_FUTURE")


def test_cross_project_zone_reference_rejected(api):
    """PRD §2.8: "If, for example, a `zone_id` resolves to a zone whose own project is
    different from the supplied `project_id`, or an `abatement_order_id` resolves to an
    order under a different project, the request is rejected with
    `ERR_CROSS_PROJECT_REFERENCE` (HTTP 409)."

    Design: Corner/validations/cross_project_zone_reference_rejected
    """
    set_clock()
    lead = create_worker(cert_type="MOLD", full_name="Lead")
    project1 = create_project(hazard_class="MOLD", site_name="P1")
    project2 = create_project(hazard_class="MOLD", site_name="P2")
    zone2 = create_zone(project2["id"], zone_label="Z2")
    res = api.create_abatement_order(
        create_abatement_order_payload(project1["id"], zone2["id"], lead["id"],
                                       abatement_type="MOLD", planned_weight_kg=50), AS)
    validate_error(res, "ERR_CROSS_PROJECT_REFERENCE")


def test_missing_auth_header_returns_401(api):
    """PRD §2.1: "A request missing either header, or carrying an empty value for
    either, is rejected with `ERR_MISSING_AUTH_HEADER`."

    Design: Corner/validations/missing_auth_header_returns_401
    """
    res = api.get_project(NON_EXISTENT_UUID, {})
    validate_error(res, "ERR_MISSING_AUTH_HEADER")


def test_unrecognized_role_returns_401(api):
    """PRD §2.1: "If `X-User-Role` carries a value that is not one of the recognized
    roles, the request is rejected with `ERR_INVALID_ROLE`."

    Design: Corner/validations/unrecognized_role_returns_401
    """
    res = api.list_projects(build_user_headers("bogus-1", "BogusRole"))
    validate_error(res, "ERR_INVALID_ROLE")


# ===========================================================================
# Corner/errors
# ===========================================================================
def test_manifest_weight_short_blocks_complete(api):
    """PRD §3.5: "an `ACCEPTED` disposal manifest exist for the order whose
    `manifest_weight_kg` is at least the reported `removed_weight_kg` (else
    `ERR_MANIFEST_WEIGHT_SHORT`)."

    ACCEPTED manifest 50 kg, complete attempted with removed 80 (> 50) -> reject.

    Design: Corner/errors/manifest_weight_short_blocks_complete
    """
    set_clock()
    lead = create_worker(cert_type="MOLD", full_name="Lead")
    project = create_project(hazard_class="MOLD")
    zone = create_active_zone(project["id"])
    order = get_success_data(api.create_abatement_order(
        create_abatement_order_payload(project["id"], zone["id"], lead["id"],
                                       abatement_type="MOLD", planned_weight_kg=100), AS))
    get_success_data(api.create_assignment(create_assignment_payload(order["id"], lead["id"]), AS))
    get_success_data(api.start_abatement_order(order["id"], AS))
    man = get_success_data(api.create_manifest(
        create_manifest_payload(order["id"], project["id"], manifest_weight_kg=50), AS))
    get_success_data(api.submit_manifest(man["id"], AS))
    get_success_data(api.accept_manifest(man["id"], PM))
    res = api.complete_abatement_order(order["id"], {"removed_weight_kg": 80}, AS)
    validate_error(res, "ERR_MANIFEST_WEIGHT_SHORT")


def test_transport_permit_missing_blocks_asbestos_manifest_submit(api):
    """PRD §3.6: "when the parent order's `abatement_type` is `ASBESTOS`, an
    `ACKNOWLEDGED` `TRANSPORT` permit must exist for the project, otherwise the
    submission is rejected with `ERR_TRANSPORT_PERMIT_MISSING`."

    Design: Corner/errors/transport_permit_missing_blocks_asbestos_manifest_submit
    """
    set_clock()
    lead = create_worker(cert_type="ASBESTOS", full_name="Lead")
    project = create_project(hazard_class="ASBESTOS", structure_sqft=80, site_name="Asb")
    zone = create_active_zone(project["id"])
    order = get_success_data(api.create_abatement_order(
        create_abatement_order_payload(project["id"], zone["id"], lead["id"],
                                       abatement_type="ASBESTOS", planned_weight_kg=50), AS))
    get_success_data(api.create_assignment(create_assignment_payload(order["id"], lead["id"]), AS))
    get_success_data(api.start_abatement_order(order["id"], AS))
    man = get_success_data(api.create_manifest(
        create_manifest_payload(order["id"], project["id"], manifest_weight_kg=50), AS))
    res = api.submit_manifest(man["id"], AS)
    validate_error(res, "ERR_TRANSPORT_PERMIT_MISSING")


def test_order_not_completed_blocks_clearance_analyze(api):
    """PRD §3.8: "A `LabTech` analyzes a `DRAFT` test, moving it to `ANALYZED`, only
    when the referenced order is `COMPLETED` (otherwise `ERR_ORDER_NOT_COMPLETED`)."

    Design: Corner/errors/order_not_completed_blocks_clearance_analyze
    """
    set_clock()
    lead = create_worker(cert_type="MOLD", full_name="Lead")
    sampler = create_worker(cert_type="MOLD", full_name="Sampler")
    project = create_project(hazard_class="MOLD")
    zone = create_active_zone(project["id"])
    order = get_success_data(api.create_abatement_order(
        create_abatement_order_payload(project["id"], zone["id"], lead["id"],
                                       abatement_type="MOLD", planned_weight_kg=50), AS))
    get_success_data(api.create_assignment(create_assignment_payload(order["id"], lead["id"]), AS))
    get_success_data(api.start_abatement_order(order["id"], AS))  # IN_PROGRESS, not COMPLETED
    clearance = get_success_data(api.create_clearance_test(
        create_clearance_test_payload(project["id"], zone["id"], order["id"], sampler["id"],
                                      clearance_air_count=10, clearance_volume_liters=100), LT))
    res = api.analyze_clearance_test(clearance["id"], LT)
    validate_error(res, "ERR_ORDER_NOT_COMPLETED")


def test_dismantle_without_passing_clearance_blocked(api):
    """PRD §3.4: "A `ProjectManager` dismantles an `ACTIVE` zone ... only when two
    conditions hold: no abatement order in that zone is in `PLANNED`, `IN_PROGRESS`,
    or `REOPENED` status (otherwise `ERR_ABATEMENT_IN_PROGRESS`), and a `SIGNED_OFF`
    clearance test exists for the zone (otherwise `ERR_NO_PASSING_CLEARANCE`)."

    An ACTIVE zone with no orders and no clearance -> ERR_NO_PASSING_CLEARANCE.

    Design: Corner/errors/dismantle_without_passing_clearance_blocked
    """
    set_clock()
    project = create_project(hazard_class="MOLD")
    zone = create_active_zone(project["id"])
    res = api.dismantle_zone(zone["id"], PM)
    validate_error(res, "ERR_NO_PASSING_CLEARANCE")


def test_void_analyzed_sample_under_cleared_assessment_blocked(api):
    """PRD §3.3: "it is permitted only when the parent assessment is not already
    `CLEARED` — voiding an analyzed sample under a `CLEARED` assessment is rejected
    with `ERR_ASSESSMENT_ALREADY_CLEARED`".

    Design: Corner/errors/void_analyzed_sample_under_cleared_assessment_blocked
    """
    set_clock()
    lead = create_worker(cert_type="MOLD", full_name="Lead")
    sampler = create_worker(cert_type="MOLD", full_name="Sampler")
    hyg = create_worker(cert_type="HYGIENIST", full_name="Hyg")
    project = create_project(hazard_class="MOLD", site_name="Clr")
    assessment = create_assessment(project["id"], sampler["id"], area_label="Wall")
    sample = create_analyzed_air_sample(project["id"], assessment["id"],
                                        raw_count=50, volume_liters=100)
    zone = create_active_zone(project["id"])
    order = get_success_data(api.create_abatement_order(
        create_abatement_order_payload(project["id"], zone["id"], lead["id"],
                                       abatement_type="MOLD", planned_weight_kg=50), AS))
    get_success_data(api.create_assignment(create_assignment_payload(order["id"], lead["id"]), AS))
    get_success_data(api.start_abatement_order(order["id"], AS))
    man = get_success_data(api.create_manifest(
        create_manifest_payload(order["id"], project["id"], manifest_weight_kg=50), AS))
    get_success_data(api.submit_manifest(man["id"], AS))
    get_success_data(api.accept_manifest(man["id"], PM))
    get_success_data(api.complete_abatement_order(order["id"], {"removed_weight_kg": 50}, AS))
    clearance = get_success_data(api.create_clearance_test(
        create_clearance_test_payload(project["id"], zone["id"], order["id"], sampler["id"],
                                      clearance_air_count=10, clearance_volume_liters=100), LT))
    get_success_data(api.analyze_clearance_test(clearance["id"], LT))
    pv = get_project_version(project["id"])
    get_success_data(api.signoff_clearance_test(
        clearance["id"], {"signoff_worker_id": hyg["id"], "expected_project_version": pv}, HY))
    # Assessment is now CLEARED; voiding its ANALYZED sample must be rejected.
    res = api.void_sample(sample["id"], PM)
    validate_error(res, "ERR_ASSESSMENT_ALREADY_CLEARED")


# ===========================================================================
# Corner/rbac
# ===========================================================================
def test_labtech_cannot_create_project(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §2.1: "A `ProjectManager` owns the project lifecycle — creating and abandoning
    projects".

    Design: Corner/rbac/labtech_cannot_create_project
    """
    res = api.create_project(create_project_payload(hazard_class="MOLD"), LT)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_abatement_supervisor_cannot_signoff_clearance(api):
    """PRD §2.1: "A `Hygienist` is the independent certified industrial hygienist who
    performs clearance sign-off and final project sign-off and nothing else."
    PRD §2.7: "role permitted for the operation (`ERR_FORBIDDEN_ROLE`)".

    The role check precedes state/OCC, so a DRAFT clearance suffices.

    Design: Corner/rbac/abatement_supervisor_cannot_signoff_clearance
    """
    ctx = setup_draft_clearance(hazard_class="MOLD",
                                clearance_air_count=10, clearance_volume_liters=100)
    pv = get_project_version(ctx["pid"], AS)
    res = api.signoff_clearance_test(
        ctx["cid"], {"signoff_worker_id": ctx["lead_id"], "expected_project_version": pv}, AS)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


# ===========================================================================
# Corner/endpoints
# ===========================================================================
def test_filtered_list_samples_by_assessment_id(api):
    """PRD §4: "GET `/api/samples` List samples (filters: `assessment_id`,
    `project_id`)" and PRD §2.3: "Every list response carries `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/filtered_list_samples_by_assessment_id
    """
    set_clock()
    assessor = create_worker(cert_type="MOLD", full_name="A")
    project = create_project(hazard_class="MOLD")
    assessment = create_assessment(project["id"], assessor["id"])
    get_success_data(api.create_sample(
        create_sample_payload(assessment["id"], project["id"], "SURFACE"), LT))
    get_success_data(api.create_sample(
        create_sample_payload(assessment["id"], project["id"], "SURFACE",
                              collected_at="2026-01-14T01:00:00Z"), LT))
    data, meta = validate_paginated(api.list_samples(LT, params={"assessment_id": assessment["id"]}))
    assert meta["total_count"] == 2
    assert all(s["assessment_id"] == assessment["id"] for s in data)


def test_list_pressure_logs_for_zone(api):
    """PRD §4: "GET `/api/pressure-logs` List pressure logs (filter: `zone_id`)" and
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/list_pressure_logs_for_zone
    """
    set_clock()
    project = create_project(hazard_class="MOLD")
    zone = create_zone(project["id"])
    get_success_data(api.create_pressure_log(
        zone["id"], create_pressure_log_payload(zone["id"]), AS))
    data, meta = validate_paginated(api.list_pressure_logs(AS, params={"zone_id": zone["id"]}))
    assert meta["total_count"] == 1
    assert all(pl["zone_id"] == zone["id"] for pl in data)


# ===========================================================================
# Corner/entities
# ===========================================================================
def test_create_project_returns_201_with_computed_fields(api):
    """PRD §3.2: "A new project starts with `status` `OPEN`, `posture` `ASSESSMENT`,
    `open_finding_count` zero, and a computed `neshap_required` flag."
    PRD §2.4: "The `version` field is an integer that starts at 1".

    Design: Corner/entities/create_project_returns_201_with_computed_fields
    """
    set_clock()
    project = validate_success(
        api.create_project(create_project_payload(hazard_class="MOLD", site_name="S",
                                                  structure_sqft=80), PM), 201)
    assert project["posture"] == "ASSESSMENT"
    assert project["status"] == "OPEN"
    assert project["neshap_required"] is False
    assert project["open_finding_count"] == 0
    assert project["version"] == 1


def test_get_project_not_found_returns_404(api):
    """PRD §2.7: "existence of every resource identifier in the URL path, validated
    left to right (a `404` naming the first missing resource)" and PRD §5 lists
    `ERR_PROJECT_NOT_FOUND` as 404.

    Design: Corner/entities/get_project_not_found_returns_404
    """
    res = api.get_project("00000000-0000-0000-0000-000000000000", PM)
    validate_error(res, "ERR_PROJECT_NOT_FOUND")


def test_create_project_missing_required_field_returns_invalid_request(api):
    """PRD §3.2: "A `ProjectManager` opens a remediation **Project** by supplying a
    `site_name`, a primary `hazard_class` (one of `ASBESTOS`, `LEAD`, or `MOLD`)".
    PRD §2.7: "request well-formedness — required fields present, enums valid, numeric
    ranges satisfied (`ERR_INVALID_REQUEST`)".

    Omitting hazard_class -> 400 ERR_INVALID_REQUEST.

    Design: Corner/entities/create_project_missing_required_field_returns_invalid_request
    """
    payload = {"site_name": "S", "structure_sqft": 80, "jurisdiction_code": "US-EPA"}
    res = api.create_project(payload, PM)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_neshap_required_true_for_large_asbestos_project(api):
    """PRD §3.2: "The NESHAP applicability flag is true exactly when the hazard class
    is `ASBESTOS` and the affected area is at least 160 square feet".

    structure_sqft == 160 (== threshold, inclusive) -> neshap_required true.

    Design: Corner/entities/neshap_required_true_for_large_asbestos_project
    """
    set_clock()
    project = validate_success(api.create_project(
        create_project_payload(hazard_class="ASBESTOS", structure_sqft=160,
                               site_name="Big Asb"), PM), 201)
    assert project["neshap_required"] is True


def test_neshap_not_required_for_asbestos_below_threshold(api):
    """PRD §3.2: "for any other hazard class, or for an asbestos project under 160
    square feet, it is false."

    structure_sqft == 159 (just below 160) -> neshap_required false.

    Design: Corner/entities/neshap_not_required_for_asbestos_below_threshold
    """
    set_clock()
    project = validate_success(api.create_project(
        create_project_payload(hazard_class="ASBESTOS", structure_sqft=159,
                               site_name="Small Asb"), PM), 201)
    assert project["neshap_required"] is False


def test_list_projects_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter caps the number of records returned; it
    defaults to 10, may not be less than 1, and may not exceed 100." and PRD §2.3:
    "Every list response carries `limit`, `offset`, `total_count`, and `has_more`
    inside the `meta` object of the envelope."

    Design: Corner/entities/list_projects_pagination_envelope
    """
    set_clock()
    create_project(hazard_class="MOLD", site_name="P1")
    create_project(hazard_class="MOLD", site_name="P2")
    data, meta = validate_paginated(api.list_projects(PM, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] >= 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_system_fields_ignored_on_create(api):
    """PRD §3.1: "A worker is current when two independent conditions both hold: the
    certification has not expired — `cert_expires_at` is strictly after the logical
    clock's current instant — and the respirator fit test is still inside its validity
    window — `ppe_fit_test_at` is strictly after the logical clock's current instant
    minus 365 days."

    is_cert_current is computed by the server from cert_expires_at / ppe_fit_test_at.

    Design: Corner/entities/system_fields_ignored_on_create
    """
    set_clock()
    worker = validate_success(api.create_worker(
        create_worker_payload(full_name="W", cert_type="MOLD",
                              cert_expires_at="2027-01-01T00:00:00Z",
                              ppe_fit_test_at="2025-12-15T00:00:00Z"), PM), 201)
    assert worker["is_cert_current"] is True


def test_worker_cert_expired_makes_is_cert_current_false(api):
    """PRD §3.1: "The certification comparison is strict: a certification whose expiry
    equals the current instant is not current."

    cert_expires_at == clock now (2026-01-15T00:00:00Z) -> is_cert_current false.

    Design: Corner/entities/worker_cert_expired_makes_is_cert_current_false
    """
    set_clock()
    worker = validate_success(api.create_worker(
        create_worker_payload(full_name="Expired", cert_type="MOLD",
                              cert_expires_at="2026-01-15T00:00:00Z",
                              ppe_fit_test_at="2025-12-15T00:00:00Z"), PM), 201)
    assert worker["is_cert_current"] is False


def test_assessment_creation_with_bad_project_fk_returns_404(api):
    """PRD §2.7: "existence of every foreign-key reference carried in the request body
    (a `404` naming the missing resource)" and PRD §2.7 names `ERR_PROJECT_NOT_FOUND`
    among the body-FK not-found errors.

    Design: Corner/entities/assessment_creation_with_bad_project_fk_returns_404
    """
    set_clock()
    worker = create_worker(cert_type="MOLD", full_name="A")
    res = api.create_assessment(
        {"project_id": "00000000-0000-0000-0000-000000000000",
         "assessor_worker_id": worker["id"], "area_label": "X"}, LT)
    validate_error(res, "ERR_PROJECT_NOT_FOUND")


def test_air_sample_missing_volume_returns_invalid_request(api):
    """PRD §3.3: "For an `AIR` sample the air volume `volume_liters` is required and
    must be greater than zero ... omitting it (or supplying a non-positive value) for
    an air sample, is an `ERR_INVALID_REQUEST`."

    Design: Corner/entities/air_sample_missing_volume_returns_invalid_request
    """
    set_clock()
    assessor = create_worker(cert_type="MOLD", full_name="A")
    project = create_project(hazard_class="MOLD")
    assessment = create_assessment(project["id"], assessor["id"])
    res = api.create_sample(
        {"assessment_id": assessment["id"], "project_id": project["id"],
         "sample_type": "AIR", "collected_at": "2026-01-14T00:00:00Z"}, LT)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_surface_sample_supplying_volume_returns_invalid_request(api):
    """PRD §3.3: "for a `SURFACE` sample `volume_liters` must be omitted entirely.
    Supplying volume for a surface sample ... is an `ERR_INVALID_REQUEST`."

    Design: Corner/entities/surface_sample_supplying_volume_returns_invalid_request
    """
    set_clock()
    assessor = create_worker(cert_type="MOLD", full_name="A")
    project = create_project(hazard_class="MOLD")
    assessment = create_assessment(project["id"], assessor["id"])
    res = api.create_sample(
        {"assessment_id": assessment["id"], "project_id": project["id"],
         "sample_type": "SURFACE", "collected_at": "2026-01-14T00:00:00Z",
         "volume_liters": 100}, LT)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_surface_sample_concentration_equals_raw_count(api):
    """PRD §3.3: "for a `SURFACE` sample the concentration is simply the raw count
    itself." and PRD §3.3: "For a surface sample, a raw count below 50 grades `CLEAN`;
    a count at or above 50 but below 500 grades `ELEVATED`".

    raw_count=60 -> concentration 60, grade ELEVATED.

    Design: Corner/entities/surface_sample_concentration_equals_raw_count
    """
    set_clock()
    assessor = create_worker(cert_type="MOLD", full_name="A")
    project = create_project(hazard_class="MOLD")
    assessment = create_assessment(project["id"], assessor["id"])
    sample = get_success_data(api.create_sample(
        create_sample_payload(assessment["id"], project["id"], "SURFACE"), LT))
    analyzed = validate_success(api.upload_sample_result(sample["id"], {"raw_count": 60}, LT), 200)
    assert analyzed["concentration"] == 60
    assert analyzed["result_grade"] == "ELEVATED"


def test_pressure_log_is_immutable_event_no_version(api):
    """PRD §2.4: "A **PressureLog** is an append-only event record: it carries only an
    `id` (a server-minted UUID) and a `created_at` timestamp. A PressureLog has no
    `updated_at` and no `version`".

    Design: Corner/entities/pressure_log_is_immutable_event_no_version
    """
    set_clock()
    project = create_project(hazard_class="MOLD")
    zone = create_zone(project["id"])
    log = validate_success(api.create_pressure_log(
        zone["id"], create_pressure_log_payload(zone["id"]), AS), 201)
    assert "created_at" in log
    assert "version" not in log
    assert "updated_at" not in log
