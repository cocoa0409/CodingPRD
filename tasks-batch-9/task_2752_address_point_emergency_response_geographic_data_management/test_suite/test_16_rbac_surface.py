"""RBAC surface of the County Address and Emergency Response GIS API.

Corner-design section ``rbac``: the exclusive-operation sweep across all six
roles, the PermitCoordinator's exclusion from the QC scan, the entity-backed
AgencyLiaison ownership rules, the three segregations of duty, and the single
shared write in the model.

Every test builds its own world through documented endpoints; the runner
restarts the server before each test, so the database starts empty.
"""

from test_helpers import (
    ANALYST_HEADERS,
    ANALYST_USER_ID,
    NON_EXISTENT_UUID,
    PERMIT_HEADERS,
    PROV_HEADERS,
    PROV_USER_ID,
    QC_HEADERS,
    QC_USER_ID,
    ROLE_PROVISIONING_OFFICER,
    ROLE_QC_CERTIFIER,
    SYSADMIN_HEADERS,
    ApiErrorId,
    make_agency_liaison_headers,
    make_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


# ===========================================================================
# Local setup helpers, built only from documented endpoints
# ===========================================================================
def _jurisdiction_with_law_agency(api):
    """One jurisdiction plus one ACTIVE LAW agency, so a liaison has an identity."""
    jurisdiction = fx.setup_jurisdiction(api)
    agency = fx.setup_agency(api, jurisdiction["id"], "LAW")
    return jurisdiction, agency


def _denied_exclusive_writes(api, j_id, a1_id):
    """The nine wrong-role writes of the sweep, returned as (label, response)."""
    liaison_1 = make_agency_liaison_headers(a1_id)
    return [
        (
            "POST /gis/jurisdictions as GisAnalyst",
            api.create_jurisdiction(
                f.jurisdiction_payload(
                    name="Weld County", code="WELDCO", postal_city="GREELEY"
                ),
                ANALYST_HEADERS,
            ),
        ),
        (
            "POST /gis/road-centerlines as AgencyLiaison",
            api.create_road_centerline(f.road_centerline_payload(j_id), liaison_1),
        ),
        (
            "POST /gis/qc-validation-reports as QcCertifier",
            api.create_qc_report(f.qc_report_payload_jurisdiction(j_id), QC_HEADERS),
        ),
        (
            "POST /gis/qc-defects/{id}/waive as GisAnalyst",
            api.waive_qc_defect(
                NON_EXISTENT_UUID, {"waiver_reason": "Not my job"}, ANALYST_HEADERS
            ),
        ),
        (
            "POST /gis/provisioning-packages as QcCertifier",
            api.create_package(
                f.package_payload(j_id, NON_EXISTENT_UUID, "MAPPING"), QC_HEADERS
            ),
        ),
        (
            "POST /gis/emergency-service-boundaries as GisAnalyst",
            api.create_boundary(f.boundary_payload(a1_id), ANALYST_HEADERS),
        ),
        (
            "POST /gis/discrepancy-cases/{id}/adopt as AgencyLiaison",
            api.adopt_discrepancy_case(NON_EXISTENT_UUID, {}, liaison_1),
        ),
        (
            "POST /gis/address-points as PermitCoordinator",
            api.create_address_point(
                f.address_point_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID),
                PERMIT_HEADERS,
            ),
        ),
        (
            "POST /gis/_clock/set_current_utc as ProvisioningOfficer",
            api.set_clock("2026-09-01T00:00:00Z", PROV_HEADERS),
        ),
    ]


# ===========================================================================
# rbac / every_roles_exclusive_operations_are_denied_to_the_other_roles_rejected
# ===========================================================================
def test_every_exclusive_write_refuses_the_wrong_role(api):
    """All nine exclusive writes answer 403 ERR_UNAUTHORIZED to the wrong role.

    Write endpoints are narrowly scoped: coverage-cell creation is shared between `SystemAdmin` and `GisAnalyst`, and every other mutating operation belongs to exactly one role, as enumerated in the endpoint table of §4.
    If the role named in `X-User-Role` is not among the roles authorised for the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

    Design: Corner/rbac/every_roles_exclusive_operations_are_denied_to_the_other_roles_rejected
    """
    jurisdiction, agency = _jurisdiction_with_law_agency(api)

    for label, resp in _denied_exclusive_writes(api, jurisdiction["id"], agency["id"]):
        assert resp.status_code == 403, f"{label}: expected 403, got {resp.status_code}"
        validate_error(resp, ApiErrorId.UNAUTHORIZED)


def test_role_denial_precedes_path_entity_existence(api):
    """A wrong-role call on an all-zero path id is ERR_UNAUTHORIZED, not a 404.

    The order is: authentication (`ERR_UNAUTHENTICATED`), then role authorisation (`ERR_UNAUTHORIZED`), then agency identity ownership (`ERR_AGENCY_IDENTITY_MISMATCH`), then path-entity existence, then referenced-entity existence, then request-schema validity (`ERR_INVALID_REQUEST`), then target-state legality, then expected-version staleness, and only then the domain-specific business rules of §2.8 onwards in the order in which they are introduced there.

    Design: Corner/rbac/every_roles_exclusive_operations_are_denied_to_the_other_roles_rejected
    """
    jurisdiction, agency = _jurisdiction_with_law_agency(api)

    # Waiving a defect belongs to the QcCertifier; the analyst is refused before
    # the non-existent defect id in the path is ever resolved.
    waive = api.waive_qc_defect(
        NON_EXISTENT_UUID, {"waiver_reason": "Not my job"}, ANALYST_HEADERS
    )
    assert waive.status_code == 403
    validate_error(waive, ApiErrorId.UNAUTHORIZED)
    assert waive.json()["data"]["error_id"] != ApiErrorId.DEFECT_NOT_FOUND

    # Adoption belongs to the SystemAdmin; the liaison is refused before the
    # non-existent case id in the path is resolved.
    adopt = api.adopt_discrepancy_case(
        NON_EXISTENT_UUID, {}, make_agency_liaison_headers(agency["id"])
    )
    assert adopt.status_code == 403
    validate_error(adopt, ApiErrorId.UNAUTHORIZED)
    assert adopt.json()["data"]["error_id"] != ApiErrorId.CASE_NOT_FOUND
    assert jurisdiction["cell_count"] == 0


def test_role_denial_precedes_referenced_entity_existence(api):
    """A wrong-role call whose body FK does not resolve is still ERR_UNAUTHORIZED.

    The same codes govern references supplied in a request body or a query filter.
    Validation is strictly ordered, and the **first** failing check determines the response; later checks are never reported for the same request.

    Design: Corner/rbac/every_roles_exclusive_operations_are_denied_to_the_other_roles_rejected
    """
    jurisdiction, _agency = _jurisdiction_with_law_agency(api)

    # Opening a package belongs to the ProvisioningOfficer; the certifier is
    # refused before the non-existent qc_report_id is resolved.
    package = api.create_package(
        f.package_payload(jurisdiction["id"], NON_EXISTENT_UUID, "MAPPING"), QC_HEADERS
    )
    assert package.status_code == 403
    validate_error(package, ApiErrorId.UNAUTHORIZED)
    assert package.json()["data"]["error_id"] != ApiErrorId.REPORT_NOT_FOUND

    # Authoring an address point belongs to the GisAnalyst; the permit
    # coordinator is refused before the non-existent road_centerline_id is
    # resolved.
    point = api.create_address_point(
        f.address_point_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID), PERMIT_HEADERS
    )
    assert point.status_code == 403
    validate_error(point, ApiErrorId.UNAUTHORIZED)
    assert point.json()["data"]["error_id"] != ApiErrorId.ROAD_NOT_FOUND


def test_role_denial_precedes_agency_identity_ownership(api):
    """The liaison's wrong-role adopt is ERR_UNAUTHORIZED, not an identity mismatch.

    Any violation of these ownership rules is rejected with `ERR_AGENCY_IDENTITY_MISMATCH` (HTTP 403), which is evaluated immediately after the role check and before any existence, schema or state evaluation.

    Design: Corner/rbac/every_roles_exclusive_operations_are_denied_to_the_other_roles_rejected
    """
    _jurisdiction, agency = _jurisdiction_with_law_agency(api)

    resp = api.adopt_discrepancy_case(
        NON_EXISTENT_UUID, {}, make_agency_liaison_headers(agency["id"])
    )
    assert resp.status_code == 403
    validate_error(resp, ApiErrorId.UNAUTHORIZED)
    assert (
        resp.json()["data"]["error_id"] != ApiErrorId.AGENCY_IDENTITY_MISMATCH
    ), "the role check precedes the agency identity check"


def test_no_denied_write_left_a_trace(api):
    """Nine refused writes leave the configuration records and counters untouched.

    A new jurisdiction begins with all four of its coverage counters — `cell_count`, `covered_cell_count`, `gap_pair_count` and `forward_gap_pair_count` — initialised to zero.

    Design: Corner/rbac/every_roles_exclusive_operations_are_denied_to_the_other_roles_rejected
    """
    jurisdiction, agency = _jurisdiction_with_law_agency(api)
    j_id = jurisdiction["id"]

    for label, resp in _denied_exclusive_writes(api, j_id, agency["id"]):
        validate_error(resp, ApiErrorId.UNAUTHORIZED)

    _rows, meta = validate_paginated(api.list_jurisdictions({"limit": 100}, ANALYST_HEADERS))
    assert meta["total_count"] == 1, "the denied jurisdiction write created nothing"

    stored = fx.read_jurisdiction(api, j_id)
    assert stored["cell_count"] == 0
    assert stored["covered_cell_count"] == 0
    assert stored["gap_pair_count"] == 0

    _agencies, agency_meta = validate_paginated(
        api.list_agencies({"limit": 100}, ANALYST_HEADERS)
    )
    assert agency_meta["total_count"] == 1

    _roads, road_meta = validate_paginated(
        api.list_road_centerlines({"limit": 100}, ANALYST_HEADERS)
    )
    assert road_meta["total_count"] == 0, "the liaison's centerline write created nothing"

    _boundaries, boundary_meta = validate_paginated(
        api.list_boundaries({"limit": 100}, ANALYST_HEADERS)
    )
    assert boundary_meta["total_count"] == 0

    _reports, report_meta = validate_paginated(
        api.list_qc_reports({"limit": 100}, ANALYST_HEADERS)
    )
    assert report_meta["total_count"] == 0

    _packages, package_meta = validate_paginated(
        api.list_packages({"limit": 100}, ANALYST_HEADERS)
    )
    assert package_meta["total_count"] == 0


# ===========================================================================
# rbac / permit_coordinator_cannot_run_a_qc_scan_rejected
# ===========================================================================
def test_permit_coordinator_cannot_run_a_qc_scan(api):
    """The PermitCoordinator owns intake, not the scan: 403 and no report row.

    If the role named in `X-User-Role` is not among the roles authorised for the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

    Design: Corner/rbac/permit_coordinator_cannot_run_a_qc_scan_rejected
    """
    world = fx.setup_draft_road_world(api)

    resp = api.create_qc_report(
        f.qc_report_payload_road(world["road_id"]), PERMIT_HEADERS
    )
    assert resp.status_code == 403
    validate_error(resp, ApiErrorId.UNAUTHORIZED)

    _rows, meta = validate_paginated(api.list_qc_reports({"limit": 100}, ANALYST_HEADERS))
    assert meta["total_count"] == 0, "the denied scan created nothing"

    # Reads are shared even where writes are not.
    shared_read = api.list_qc_reports({"limit": 100}, PERMIT_HEADERS)
    assert shared_read.status_code == 200


def test_the_same_qc_scan_body_succeeds_for_the_gis_analyst(api):
    """The identical POST body that the coordinator was refused is a 201 for the analyst.

    The new report lands in `GENERATED` status with `generated_by_user_id` set to the calling `X-User-ID`, `waived_blocking_count` at zero, and `certified_by_user_id`, `certified_at`, `rejection_reason` and `decertified_reason` all null.

    Design: Corner/rbac/permit_coordinator_cannot_run_a_qc_scan_rejected
    """
    world = fx.setup_draft_road_world(api)
    payload = f.qc_report_payload_road(world["road_id"])

    validate_error(api.create_qc_report(payload, PERMIT_HEADERS), ApiErrorId.UNAUTHORIZED)

    report = validate_success(api.create_qc_report(payload, ANALYST_HEADERS), 201)
    assert report["generated_by_user_id"] == ANALYST_USER_ID
    assert report["scope"] == "ROAD"
    assert report["status"] == "GENERATED"
    assert report["certified_by_user_id"] is None

    _rows, meta = validate_paginated(api.list_qc_reports({"limit": 100}, ANALYST_HEADERS))
    assert meta["total_count"] == 1, "exactly one report exists — the analyst's"


# ===========================================================================
# rbac / agency_liaison_cannot_touch_another_agencys_boundary_rejected
# ===========================================================================
def _two_agencies_and_a_draft_boundary(api):
    """Jurisdiction + C001 + a1 (LAW) and a2 (FIRE) + one DRAFT boundary owned by a1."""
    world = fx.setup_base_geography(api)
    a1 = fx.setup_agency(api, world["j_id"], "LAW")
    a2 = fx.setup_agency(api, world["j_id"], "FIRE")
    boundary = fx.setup_boundary(api, a1["id"])
    world["a1_id"] = a1["id"]
    world["a2_id"] = a2["id"]
    world["boundary"] = boundary
    world["boundary_id"] = boundary["id"]
    return world


def test_liaison_cannot_create_a_boundary_naming_a_peer_agency(api):
    """Naming another agency on create is 403 ERR_AGENCY_IDENTITY_MISMATCH.

    A liaison creating a boundary or a case may not name an agency other than itself.

    Design: Corner/rbac/agency_liaison_cannot_touch_another_agencys_boundary_rejected
    """
    world = _two_agencies_and_a_draft_boundary(api)

    resp = api.create_boundary(
        f.boundary_payload(world["a2_id"]),
        make_agency_liaison_headers(world["a1_id"]),
    )
    assert resp.status_code == 403
    validate_error(resp, ApiErrorId.AGENCY_IDENTITY_MISMATCH)

    _rows, meta = validate_paginated(api.list_boundaries({"limit": 100}, ANALYST_HEADERS))
    assert meta["total_count"] == 1, "a2 never created a boundary"


def test_liaison_cannot_propose_claim_or_retire_a_peer_agencys_boundary(api):
    """Propose, claim and retire on a peer's boundary are all identity mismatches.

    Concretely, a liaison may only propose, claim cells for, activate or retire an `EmergencyServiceBoundary` whose `agency_id` equals `X-User-ID`, and may only file proposals on or concur with a `DiscrepancyCase` in which `X-User-ID` appears as either `opened_by_agency_id` or `counterparty_agency_id`.

    Design: Corner/rbac/agency_liaison_cannot_touch_another_agencys_boundary_rejected
    """
    world = _two_agencies_and_a_draft_boundary(api)
    b_id = world["boundary_id"]
    b_version = world["boundary"]["version"]
    intruder = make_agency_liaison_headers(world["a2_id"])

    propose = api.propose_boundary(b_id, {}, intruder)
    assert propose.status_code == 403
    validate_error(propose, ApiErrorId.AGENCY_IDENTITY_MISMATCH)
    assert (
        propose.json()["data"]["error_id"] != ApiErrorId.BOUNDARY_INVALID_STATE
    ), "the identity check precedes the transition preconditions"

    claim = api.create_cell_assignment(
        b_id, f.cell_assignment_payload(world["cell_id"], b_version), intruder
    )
    assert claim.status_code == 403
    validate_error(claim, ApiErrorId.AGENCY_IDENTITY_MISMATCH)

    retire = api.retire_boundary(
        b_id, f.retire_boundary_payload(retire_reason="Not my boundary"), intruder
    )
    assert retire.status_code == 403
    validate_error(retire, ApiErrorId.AGENCY_IDENTITY_MISMATCH)

    stored = fx.read_boundary(api, b_id)
    assert stored["status"] == "DRAFT"
    assert stored["version"] == 1
    assert stored["assigned_cell_count"] == 0

    _rows, meta = validate_paginated(
        api.list_boundary_cell_assignments_of(b_id, {"limit": 100}, ANALYST_HEADERS)
    )
    assert meta["total_count"] == 0, "the refused claim appended nothing"


def test_boundary_reads_are_not_agency_scoped_while_writes_are(api):
    """The peer liaison reads the boundary at 200 though every write is refused.

    Read endpoints are open to all six roles.
    The boundary's `service_type` is not supplied by the caller: it is copied from the owning agency's `agency_type` at creation, so a boundary can never disagree with its agency about which emergency service it provides.

    Design: Corner/rbac/agency_liaison_cannot_touch_another_agencys_boundary_rejected
    """
    world = _two_agencies_and_a_draft_boundary(api)
    intruder = make_agency_liaison_headers(world["a2_id"])

    read = api.get_boundary(world["boundary_id"], intruder)
    assert read.status_code == 200
    data = validate_success(read, 200)
    assert data["agency_id"] == world["a1_id"]
    assert data["service_type"] == "LAW", "service_type is copied from the agency"

    listed = api.list_boundaries({"limit": 100}, intruder)
    assert listed.status_code == 200

    validate_error(
        api.retire_boundary(
            world["boundary_id"], f.retire_boundary_payload(), intruder
        ),
        ApiErrorId.AGENCY_IDENTITY_MISMATCH,
    )


# ===========================================================================
# rbac / qc_report_generator_cannot_certify_its_own_report_rejected
# ===========================================================================
def _published_road_with_generated_report(api):
    """Jurisdiction + C001 + PUBLISHED road holding no address points, plus one
    ROAD-scoped report generated by analyst-1 (only the ROAD_NO_ADDRESSES INFO)."""
    world = fx.setup_published_road_world(api)
    report = fx.setup_road_scoped_report(api, world["road_id"])
    world["report"] = report
    world["report_id"] = report["id"]
    return world


def test_report_generator_cannot_certify_its_own_report(api):
    """analyst-1 wearing the QcCertifier role is refused on the report it generated.

    That same identifier may not certify the report: if `X-User-ID` on the certify request equals the report's `generated_by_user_id`, the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

    Design: Corner/rbac/qc_report_generator_cannot_certify_its_own_report_rejected
    """
    world = _published_road_with_generated_report(api)
    assert world["report"]["generated_by_user_id"] == ANALYST_USER_ID
    assert world["report"]["open_blocking_defect_count"] == 0

    resp = api.certify_qc_report(
        world["report_id"], {}, make_headers(ANALYST_USER_ID, ROLE_QC_CERTIFIER)
    )
    assert resp.status_code == 403
    validate_error(resp, ApiErrorId.SEGREGATION_OF_DUTIES)

    stored = fx.read_report(api, world["report_id"])
    assert stored["status"] == "GENERATED"
    assert stored["certified_by_user_id"] is None
    assert stored["version"] == 1


def test_a_different_certifier_certifies_the_identical_report(api):
    """qc-1 is accepted on the identical payload analyst-1 was refused on.

    Certification sets `certified_by_user_id` to the calling `X-User-ID` and `certified_at` to the logical clock instant, increments the report's `version` by 1, and then stamps certified confidence onto the data: for every address point in the report's scope whose `status` is `PENDING` or `ACTIVE`, processed in order of `house_number` ascending and then `created_at` ascending, the certified variant of the confidence calculation is computed into `certified_confidence_score`, `confidence_basis` is set to `CERTIFIED`, and that point's `version` is incremented by 1.

    Design: Corner/rbac/qc_report_generator_cannot_certify_its_own_report_rejected
    """
    world = _published_road_with_generated_report(api)
    report_id = world["report_id"]

    validate_error(
        api.certify_qc_report(
            report_id, {}, make_headers(ANALYST_USER_ID, ROLE_QC_CERTIFIER)
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES,
    )

    certified = validate_success(api.certify_qc_report(report_id, {}, QC_HEADERS), 200)
    assert certified["status"] == "CERTIFIED"
    assert certified["certified_by_user_id"] == QC_USER_ID
    assert certified["generated_by_user_id"] == ANALYST_USER_ID
    assert certified["certified_at"] == "2026-08-01T00:00:00.000Z"
    assert certified["version"] == 2
    assert certified["quality_score"] == 99.55
    assert certified["quality_tier"] == "A"
    assert certified["is_provisioning_eligible"] is True


# ===========================================================================
# rbac / report_certifier_cannot_publish_the_package_built_on_it_rejected
# ===========================================================================
def _sealed_package_on_a_report_certified_by_qc_1(api):
    """The world of the previous instance, certified by qc-1, with one MAPPING
    package created and sealed by prov-1 over a single road pin."""
    world = _published_road_with_generated_report(api)
    world["report"] = fx.certify_report(api, world["report_id"])
    package = fx.setup_package(api, world["j_id"], world["report_id"], "MAPPING")
    world["package"] = fx.seal_package(api, package["id"])
    world["package_id"] = package["id"]
    return world


def test_report_certifier_cannot_publish_the_package_built_on_it(api):
    """qc-1 wearing the ProvisioningOfficer role cannot publish its own report's package.

    Certification records the certifier in `certified_by_user_id`, and that identifier in turn may not publish a provisioning package built on the report: if `X-User-ID` on the publish request equals the referenced report's `certified_by_user_id`, the same `ERR_SEGREGATION_OF_DUTIES` is returned.
    First, the calling `X-User-ID` must differ from the referenced report's `certified_by_user_id`, or the request is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

    Design: Corner/rbac/report_certifier_cannot_publish_the_package_built_on_it_rejected
    """
    world = _sealed_package_on_a_report_certified_by_qc_1(api)

    resp = api.publish_package(
        world["package_id"], {}, make_headers(QC_USER_ID, ROLE_PROVISIONING_OFFICER)
    )
    assert resp.status_code == 403
    validate_error(resp, ApiErrorId.SEGREGATION_OF_DUTIES)

    stored = fx.read_package(api, world["package_id"])
    assert stored["status"] == "SEALED"
    assert stored["published_at"] is None
    assert stored["published_by_user_id"] is None


def test_the_provisioning_officer_publishes_the_same_sealed_package(api):
    """prov-1 publishes what qc-1 was refused; sealing by prov-1 was never segregated.

    A successful publication stamps `published_at` at the logical clock instant and `published_by_user_id` from the calling `X-User-ID`, increments the package's `version` by 1, and then supersedes the incumbent: any other package on the same channel-and-jurisdiction pairing whose `status` is `PUBLISHED` transitions `PUBLISHED → SUPERSEDED`, incrementing its own `version` by 1.

    Design: Corner/rbac/report_certifier_cannot_publish_the_package_built_on_it_rejected
    """
    world = _sealed_package_on_a_report_certified_by_qc_1(api)
    package_id = world["package_id"]

    validate_error(
        api.publish_package(
            package_id, {}, make_headers(QC_USER_ID, ROLE_PROVISIONING_OFFICER)
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES,
    )

    published = validate_success(api.publish_package(package_id, {}, PROV_HEADERS), 200)
    assert published["status"] == "PUBLISHED"
    assert published["package_version"] == 1
    assert published["published_by_user_id"] == PROV_USER_ID
    assert published["version"] == 3
    assert published["record_count"] == 1
    assert published["fresh_pin_count"] == 1
    assert published["stale_pin_count"] == 0
    assert published["sealed_by_user_id"] == PROV_USER_ID


# ===========================================================================
# rbac / an_agency_cannot_concur_with_or_counter_its_own_proposal_rejected
# ===========================================================================
def _case_with_one_opener_proposal(api):
    """A ROAD_NAME case opened by a1 against a2 with one proposal filed by a1."""
    world = fx.setup_draft_road_world(api)
    parties = fx.setup_two_agencies(api, world["j_id"])
    case = fx.setup_discrepancy_case(
        api,
        world["road_id"],
        parties["opener_id"],
        parties["counterparty_id"],
        description="Sheriff CAD shows N MAPLE ST; fire shows MAPLE ST N",
    )
    proposal = fx.file_proposal(
        api,
        case["id"],
        parties["opener_id"],
        "N MAPLE STREET",
        expected_case_version=case["version"],
        rationale="Matches the recorded plat",
    )
    world.update(parties)
    world["case_id"] = case["id"]
    world["proposal_id"] = proposal["id"]
    world["case"] = fx.read_case(api, case["id"])
    return world


def test_the_opener_cannot_concur_with_its_own_proposal(api):
    """The side that filed the pending proposal is refused ERR_SELF_CONCURRENCE.

    The acting side must differ from that proposal's `proposed_by_side`, since an agency may not concur with its own proposal, and a violation is `ERR_SELF_CONCURRENCE` (HTTP 403).

    Design: Corner/rbac/an_agency_cannot_concur_with_or_counter_its_own_proposal_rejected
    """
    world = _case_with_one_opener_proposal(api)

    resp = api.concur_discrepancy_case(
        world["case_id"],
        f.concur_payload(world["proposal_id"]),
        make_agency_liaison_headers(world["opener_id"]),
    )
    assert resp.status_code == 403
    validate_error(resp, ApiErrorId.SELF_CONCURRENCE)

    stored = fx.read_case(api, world["case_id"])
    assert stored["status"] == "PROPOSAL_PENDING"
    assert stored["version"] == 2
    assert stored["round_count"] == 1
    assert stored["concurred_by_side"] is None


def test_the_opener_cannot_counter_its_own_proposal(api):
    """A self-counter carrying the current case version is ERR_SELF_CONCURRENCE.

    The third separation lives in the discrepancy workflow: the agency side that authored the currently pending proposal may neither concur with it nor counter it, and either attempt is rejected with `ERR_SELF_CONCURRENCE` (HTTP 403).
    And once a first proposal exists, the acting side must **differ** from the current proposal's `proposed_by_side` — an agency may not counter itself — or the filing is refused with `ERR_SELF_CONCURRENCE` (HTTP 403).

    Design: Corner/rbac/an_agency_cannot_concur_with_or_counter_its_own_proposal_rejected
    """
    world = _case_with_one_opener_proposal(api)
    case_version = world["case"]["version"]
    assert case_version == 2

    resp = api.create_proposal(
        world["case_id"],
        f.proposal_payload("NORTH MAPLE STREET", case_version, rationale="Self counter"),
        make_agency_liaison_headers(world["opener_id"]),
    )
    assert resp.status_code == 403
    validate_error(resp, ApiErrorId.SELF_CONCURRENCE)

    _rows, meta = validate_paginated(
        api.list_proposals(world["case_id"], {"limit": 100}, ANALYST_HEADERS)
    )
    assert meta["total_count"] == 1, "the refused counter appended nothing"

    stored = fx.read_case(api, world["case_id"])
    assert stored["round_count"] == 1
    assert stored["version"] == 2

    proposals = fx.read_proposals(api, world["case_id"])
    assert proposals[0]["proposed_by_side"] == "OPENER"
    assert proposals[0]["round_number"] == 1
    assert proposals[0]["status"] == "PENDING"


def test_the_counterparty_concurrence_carries_the_case_to_concurred(api):
    """After both self-dealing refusals the other side concurs and the case moves.

    Concurrence is available from `PROPOSAL_PENDING` and from `COUNTERED`, and both branches behave identically: the case advances to `CONCURRED`, `concurred_by_side` is set to the acting side (`OPENER` or `COUNTERPARTY`), and the case's `version` increments by 1.

    Design: Corner/rbac/an_agency_cannot_concur_with_or_counter_its_own_proposal_rejected
    """
    world = _case_with_one_opener_proposal(api)
    case_id = world["case_id"]
    proposal_id = world["proposal_id"]
    opener = make_agency_liaison_headers(world["opener_id"])

    validate_error(
        api.concur_discrepancy_case(case_id, f.concur_payload(proposal_id), opener),
        ApiErrorId.SELF_CONCURRENCE,
    )
    validate_error(
        api.create_proposal(
            case_id, f.proposal_payload("NORTH MAPLE STREET", 2), opener
        ),
        ApiErrorId.SELF_CONCURRENCE,
    )

    concurred = validate_success(
        api.concur_discrepancy_case(
            case_id,
            f.concur_payload(proposal_id),
            make_agency_liaison_headers(world["counterparty_id"]),
        ),
        200,
    )
    assert concurred["status"] == "CONCURRED"
    assert concurred["concurred_by_side"] == "COUNTERPARTY"
    assert concurred["current_proposal_id"] == proposal_id
    assert concurred["version"] == 3
    assert concurred["opened_by_agency_id"] == world["opener_id"]
    assert concurred["resolved_value"] is None, "adoption, not concurrence, writes the value"


# ===========================================================================
# rbac / coverage_cell_creation_is_shared_by_the_admin_and_the_analyst
# ===========================================================================
def test_coverage_cell_creation_succeeds_for_both_the_admin_and_the_analyst(api):
    """The one shared write in the model: both roles create a cell at 201.

    Creating one — the single write operation shared between `SystemAdmin` and `GisAnalyst` — captures a `cell_code` (one to 12 characters of uppercase letters and digits, unique inside its `jurisdiction_id`), the `jurisdiction_id` it belongs to, and optional informational `centroid_lat` and `centroid_lon` values that default to null and are never consulted in any business decision.

    Design: Corner/rbac/coverage_cell_creation_is_shared_by_the_admin_and_the_analyst
    """
    jurisdiction = fx.setup_jurisdiction(api)
    j_id = jurisdiction["id"]

    admin_resp = api.create_coverage_cell(
        f.coverage_cell_payload(j_id, cell_code="C001"), SYSADMIN_HEADERS
    )
    assert admin_resp.status_code == 201
    c1 = validate_success(admin_resp, 201)

    analyst_resp = api.create_coverage_cell(
        f.coverage_cell_payload(
            j_id, cell_code="C002", centroid_lat=40.585, centroid_lon=-105.084
        ),
        ANALYST_HEADERS,
    )
    assert analyst_resp.status_code == 201
    c2 = validate_success(analyst_resp, 201)

    assert c1["cell_code"] == "C001"
    assert c1["centroid_lat"] is None
    assert c1["active_assignment_count"] == 0
    assert c1["jurisdiction_id"] == j_id

    assert c2["cell_code"] == "C002"
    assert c2["centroid_lat"] == 40.585
    assert c2["centroid_lon"] == -105.084
    assert c2["jurisdiction_id"] == j_id


def test_shared_cell_writes_accumulate_into_one_counter_set(api):
    """Cells created by different roles land in the same jurisdiction counters.

    A jurisdiction's `gap_pair_count` is the number of gap pairs across all of its cells taken against all three service types; its `covered_cell_count` is the number of its cells that have exactly one covering `ACTIVE` assignment for **all three** service types simultaneously; and a cell's own `active_assignment_count` is the number of `ACTIVE` assignments covering the current instant on that cell, summed across service types.
    The new cell's `active_assignment_count` starts at zero, and creating it refreshes the owning jurisdiction's counters — which means `cell_count` rises and, since a brand-new cell is claimed by nobody, the gap counters rise with it.

    Design: Corner/rbac/coverage_cell_creation_is_shared_by_the_admin_and_the_analyst
    """
    jurisdiction = fx.setup_jurisdiction(api)
    j_id = jurisdiction["id"]

    validate_success(
        api.create_coverage_cell(
            f.coverage_cell_payload(j_id, cell_code="C001"), SYSADMIN_HEADERS
        ),
        201,
    )
    validate_success(
        api.create_coverage_cell(
            f.coverage_cell_payload(
                j_id, cell_code="C002", centroid_lat=40.585, centroid_lon=-105.084
            ),
            ANALYST_HEADERS,
        ),
        201,
    )

    stored = fx.read_jurisdiction(api, j_id)
    assert stored["cell_count"] == 2, "the shared writes are not partitioned by role"
    assert stored["covered_cell_count"] == 0
    assert stored["gap_pair_count"] == 6, "2 cells times 3 service types"
    assert stored["forward_gap_pair_count"] == 6

    # Every role reads the shared collection.
    rows, meta = validate_paginated(api.list_coverage_cells({"limit": 100}, PERMIT_HEADERS))
    assert meta["total_count"] == 2
    assert [row["cell_code"] for row in rows] == ["C001", "C002"]
