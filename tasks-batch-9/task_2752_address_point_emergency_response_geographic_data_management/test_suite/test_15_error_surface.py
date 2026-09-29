"""Corner coverage for the error surface of the County GIS API.

Every test in this module drives a documented endpoint into a documented
refusal and then proves that the refused call changed nothing: the entity-
specific 404 codes for path ids and for body foreign keys, the subject-specific
uniqueness codes, range geometry on create and on a merged patch, the
per-entity invalid-state codes, and the seal/publish/rollback gates of the
provisioning lifecycle.

Design section: Corner/errors.
"""

from test_helpers import (
    ANALYST_HEADERS,
    NON_EXISTENT_UUID,
    PERMIT_HEADERS,
    PROV_HEADERS,
    QC_HEADERS,
    SYSADMIN_HEADERS,
    ApiErrorId,
    make_agency_liaison_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx

# The canonical non-existent identifier used by every not-found probe below.
MISSING = NON_EXISTENT_UUID


# ===========================================================================
# path_id_codes_are_entity_specific_not_found
# ===========================================================================
def test_missing_agency_road_and_address_point_paths_answer_their_own_not_found_codes(api):
    """Three geography reads on the all-zero id answer three different 404 codes.

    Each entity has its own 404 code: `ERR_JURISDICTION_NOT_FOUND`, `ERR_AGENCY_NOT_FOUND`, `ERR_COVERAGE_CELL_NOT_FOUND`, `ERR_ROAD_NOT_FOUND`, `ERR_ADDRESS_POINT_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`, `ERR_BOUNDARY_NOT_FOUND`, `ERR_CELL_ASSIGNMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_DEFECT_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, `ERR_CASE_NOT_FOUND` and `ERR_PROPOSAL_NOT_FOUND`.

    Design: Corner/errors/path_id_codes_are_entity_specific_not_found
    """
    agency_err = validate_error(
        api.get_agency(MISSING, SYSADMIN_HEADERS), ApiErrorId.AGENCY_NOT_FOUND
    )
    road_err = validate_error(
        api.get_road_centerline(MISSING, ANALYST_HEADERS), ApiErrorId.ROAD_NOT_FOUND
    )
    point_err = validate_error(
        api.get_address_point(MISSING, ANALYST_HEADERS),
        ApiErrorId.ADDRESS_POINT_NOT_FOUND,
    )

    assert agency_err["error_id"] == "ERR_AGENCY_NOT_FOUND"
    assert road_err["error_id"] == "ERR_ROAD_NOT_FOUND"
    assert point_err["error_id"] == "ERR_ADDRESS_POINT_NOT_FOUND"
    for err in (agency_err, road_err, point_err):
        assert isinstance(err["message"], str) and err["message"].strip(), (
            "every error response carries a non-empty human-readable message"
        )
    assert len({err["error_id"] for err in (agency_err, road_err, point_err)}) == 3, (
        "a single shared ERR_NOT_FOUND would collapse these three codes into one"
    )


def test_missing_request_boundary_and_cell_assignment_paths_answer_their_own_not_found_codes(api):
    """A boundary cell assignment answers its own code, not the boundary's.

    Path parameters are resolved left to right.
    Each entity has its own 404 code: `ERR_JURISDICTION_NOT_FOUND`, `ERR_AGENCY_NOT_FOUND`, `ERR_COVERAGE_CELL_NOT_FOUND`, `ERR_ROAD_NOT_FOUND`, `ERR_ADDRESS_POINT_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`, `ERR_BOUNDARY_NOT_FOUND`, `ERR_CELL_ASSIGNMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_DEFECT_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, `ERR_CASE_NOT_FOUND` and `ERR_PROPOSAL_NOT_FOUND`.

    Design: Corner/errors/path_id_codes_are_entity_specific_not_found
    """
    request_err = validate_error(
        api.get_assignment_request(MISSING, PERMIT_HEADERS),
        ApiErrorId.REQUEST_NOT_FOUND,
    )
    boundary_err = validate_error(
        api.get_boundary(MISSING, ANALYST_HEADERS), ApiErrorId.BOUNDARY_NOT_FOUND
    )
    assignment_err = validate_error(
        api.get_cell_assignment(MISSING, ANALYST_HEADERS),
        ApiErrorId.CELL_ASSIGNMENT_NOT_FOUND,
    )

    assert request_err["error_id"] == "ERR_REQUEST_NOT_FOUND"
    assert boundary_err["error_id"] == "ERR_BOUNDARY_NOT_FOUND"
    assert assignment_err["error_id"] == "ERR_CELL_ASSIGNMENT_NOT_FOUND", (
        "a cell assignment read is not routed to the boundary's not-found code"
    )
    for err in (request_err, boundary_err, assignment_err):
        assert isinstance(err["message"], str) and err["message"].strip()


def test_missing_report_defect_and_package_paths_answer_their_own_not_found_codes(api):
    """The quality and provisioning reads keep three separate 404 codes.

    Each entity has its own 404 code: `ERR_JURISDICTION_NOT_FOUND`, `ERR_AGENCY_NOT_FOUND`, `ERR_COVERAGE_CELL_NOT_FOUND`, `ERR_ROAD_NOT_FOUND`, `ERR_ADDRESS_POINT_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`, `ERR_BOUNDARY_NOT_FOUND`, `ERR_CELL_ASSIGNMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_DEFECT_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, `ERR_CASE_NOT_FOUND` and `ERR_PROPOSAL_NOT_FOUND`.

    Design: Corner/errors/path_id_codes_are_entity_specific_not_found
    """
    report_err = validate_error(
        api.get_qc_report(MISSING, QC_HEADERS), ApiErrorId.REPORT_NOT_FOUND
    )
    defect_err = validate_error(
        api.get_qc_defect(MISSING, QC_HEADERS), ApiErrorId.DEFECT_NOT_FOUND
    )
    package_err = validate_error(
        api.get_package(MISSING, PROV_HEADERS), ApiErrorId.PACKAGE_NOT_FOUND
    )

    assert report_err["error_id"] == "ERR_REPORT_NOT_FOUND"
    assert defect_err["error_id"] == "ERR_DEFECT_NOT_FOUND"
    assert package_err["error_id"] == "ERR_PACKAGE_NOT_FOUND"
    for err in (report_err, defect_err, package_err):
        assert isinstance(err["message"], str) and err["message"].strip()
    assert len({err["error_id"] for err in (report_err, defect_err, package_err)}) == 3


# ===========================================================================
# body_foreign_key_codes_are_entity_specific_not_found
# ===========================================================================
def test_concur_with_an_unresolvable_proposal_id_answers_proposal_not_found(api):
    """The body foreign key is resolved before the self-concurrence rule runs.

    Validation is strictly ordered, and the **first** failing check determines the response; later checks are never reported for the same request.
    A liaison concurs by supplying the `proposal_id` it is agreeing to, which must equal the case's `current_proposal_id` and must itself project to `PENDING`; a `proposal_id` that resolves to no proposal at all is `ERR_PROPOSAL_NOT_FOUND`.

    Design: Corner/errors/body_foreign_key_codes_are_entity_specific_not_found
    """
    jurisdiction = fx.setup_jurisdiction(api)
    j_id = jurisdiction["id"]
    sheriff = fx.setup_agency(api, j_id, "LAW")
    fire = fx.setup_agency(api, j_id, "FIRE", name="Poudre Fire Authority")
    road = fx.setup_road(api, j_id)
    case = fx.setup_discrepancy_case(
        api,
        road["id"],
        sheriff["id"],
        fire["id"],
        description="Name should read MAPLE STREET",
    )

    # The opener concurs with a proposal that does not exist; priority 5 beats
    # the priority-16 ERR_SELF_CONCURRENCE that would otherwise apply to it.
    err = validate_error(
        api.concur_discrepancy_case(
            case["id"],
            {"proposal_id": MISSING},
            make_agency_liaison_headers(sheriff["id"]),
        ),
        ApiErrorId.PROPOSAL_NOT_FOUND,
    )
    assert err["error_id"] == "ERR_PROPOSAL_NOT_FOUND"

    unchanged = fx.read_case(api, case["id"])
    assert unchanged["status"] == "OPEN"
    assert unchanged["round_count"] == 0
    assert unchanged["version"] == 1
    assert unchanged["current_proposal_id"] is None
    assert unchanged["concurred_by_side"] is None


def test_unresolvable_road_report_and_agency_body_references_answer_the_referenced_entitys_code(api):
    """Body foreign keys answer the referenced entity's code, not the caller's.

    The same codes govern references supplied in a request body or a query filter.
    A `jurisdiction_id`, `agency_id`, `road_centerline_id`, `cell_id`, `parent_address_point_id`, `superseded_by_address_point_id`, `qc_report_id`, `counterparty_agency_id` or `proposal_id` that does not resolve raises the referenced entity's own not-found code.

    Design: Corner/errors/body_foreign_key_codes_are_entity_specific_not_found
    """
    world = fx.setup_base_geography(api)
    j_id = world["j_id"]
    cell_id = world["cell_id"]

    # The cell_id resolves, the road does not.
    road_err = validate_error(
        api.create_address_point(
            {
                "house_number": 100,
                "road_centerline_id": MISSING,
                "side": "LEFT",
                "source": "PARCEL",
                "postal_city": "FORT COLLINS",
                "cell_id": cell_id,
            },
            ANALYST_HEADERS,
        ),
        ApiErrorId.ROAD_NOT_FOUND,
    )
    report_err = validate_error(
        api.create_package(
            {"channel": "MAPPING", "jurisdiction_id": j_id, "qc_report_id": MISSING},
            PROV_HEADERS,
        ),
        ApiErrorId.REPORT_NOT_FOUND,
    )
    # X-User-ID matches the payload agency_id, so the identity check passes and
    # the referenced-entity check is what fires.
    agency_err = validate_error(
        api.create_boundary(
            {"agency_id": MISSING, "effective_start": "2026-08-01T00:00:00Z"},
            make_agency_liaison_headers(MISSING),
        ),
        ApiErrorId.AGENCY_NOT_FOUND,
    )

    assert road_err["error_id"] == "ERR_ROAD_NOT_FOUND"
    assert report_err["error_id"] == "ERR_REPORT_NOT_FOUND"
    assert agency_err["error_id"] == "ERR_AGENCY_NOT_FOUND"

    _, point_meta = validate_paginated(
        api.list_address_points({"limit": 100}, ANALYST_HEADERS)
    )
    assert point_meta["total_count"] == 0, "no address point was created"
    _, package_meta = validate_paginated(
        api.list_packages({"limit": 100}, PROV_HEADERS)
    )
    assert package_meta["total_count"] == 0, "no provisioning package was created"
    _, boundary_meta = validate_paginated(
        api.list_boundaries({"limit": 100}, ANALYST_HEADERS)
    )
    assert boundary_meta["total_count"] == 0, "no boundary was created"


# ===========================================================================
# duplicate_uniqueness_codes_are_subject_specific_rejected
# ===========================================================================
def test_duplicate_jurisdiction_code_and_reused_permit_number_answer_their_own_codes(api):
    """A voided request still reserves its globally unique permit number.

    A jurisdiction's `code` is globally unique, violated with `ERR_DUPLICATE_JURISDICTION_CODE`.
    An assignment request's `permit_number` is globally unique, and the constraint holds against voided and rejected requests as well, violated with `ERR_DUPLICATE_PERMIT_NUMBER`.

    Design: Corner/errors/duplicate_uniqueness_codes_are_subject_specific_rejected
    """
    larimer = fx.setup_jurisdiction(api)
    weld = fx.setup_jurisdiction(
        api, name="Weld County", code="WELDCO", postal_city="GREELEY"
    )
    fx.setup_coverage_cell(api, larimer["id"], "C001")
    road = fx.setup_road(api, larimer["id"])
    request = fx.setup_assignment_request(
        api, road["id"], permit_number="BP-2026-0600", parcel_id="8712300600"
    )
    fx.void_request(api, request["id"], void_reason="Permit withdrawn by applicant")

    jurisdiction_err = validate_error(
        api.create_jurisdiction(
            {
                "name": "Larimer County GIS",
                "code": "LARCO",
                "jurisdiction_type": "MUNICIPAL",
                "postal_city": "FORT COLLINS",
            },
            SYSADMIN_HEADERS,
        ),
        ApiErrorId.DUPLICATE_JURISDICTION_CODE,
    )
    permit_err = validate_error(
        api.create_assignment_request(
            {
                "permit_number": "BP-2026-0600",
                "parcel_id": "8712300601",
                "road_centerline_id": road["id"],
                "side": "RIGHT",
            },
            PERMIT_HEADERS,
        ),
        ApiErrorId.DUPLICATE_PERMIT_NUMBER,
    )

    assert jurisdiction_err["error_id"] == "ERR_DUPLICATE_JURISDICTION_CODE"
    assert permit_err["error_id"] == "ERR_DUPLICATE_PERMIT_NUMBER"

    voided = fx.read_request(api, request["id"])
    assert voided["fulfillment_status"] == "VOIDED", (
        "a voided request still reserves its permit number"
    )
    assert fx.read_jurisdiction(api, larimer["id"])["cell_count"] == 1
    _, jurisdiction_meta = validate_paginated(
        api.list_jurisdictions({"limit": 100}, SYSADMIN_HEADERS)
    )
    assert jurisdiction_meta["total_count"] == 2
    _, request_meta = validate_paginated(
        api.list_assignment_requests({"limit": 100}, PERMIT_HEADERS)
    )
    assert request_meta["total_count"] == 1, "the reused permit number created nothing"
    assert weld["cell_count"] == 0


def test_duplicate_cell_code_is_rejected_inside_a_jurisdiction_and_accepted_across_them(api):
    """C001 collides inside LARCO and is free again under WELDCO.

    A coverage cell's `cell_code` is unique within its `jurisdiction_id`, violated with `ERR_DUPLICATE_CELL_CODE`.

    Design: Corner/errors/duplicate_uniqueness_codes_are_subject_specific_rejected
    """
    larimer = fx.setup_jurisdiction(api)
    weld = fx.setup_jurisdiction(
        api, name="Weld County", code="WELDCO", postal_city="GREELEY"
    )
    fx.setup_coverage_cell(api, larimer["id"], "C001")

    cell_err = validate_error(
        api.create_coverage_cell(
            {"cell_code": "C001", "jurisdiction_id": larimer["id"]}, ANALYST_HEADERS
        ),
        ApiErrorId.DUPLICATE_CELL_CODE,
    )
    assert cell_err["error_id"] == "ERR_DUPLICATE_CELL_CODE"

    accepted = validate_success(
        api.create_coverage_cell(
            {"cell_code": "C001", "jurisdiction_id": weld["id"]}, ANALYST_HEADERS
        ),
        201,
    )
    assert accepted["cell_code"] == "C001"
    assert accepted["jurisdiction_id"] == weld["id"]

    assert fx.read_jurisdiction(api, larimer["id"])["cell_count"] == 1
    assert fx.read_jurisdiction(api, weld["id"])["cell_count"] == 1
    _, cell_meta = validate_paginated(
        api.list_coverage_cells({"limit": 100}, ANALYST_HEADERS)
    )
    assert cell_meta["total_count"] == 2


# ===========================================================================
# bad_range_geometry_on_create_and_patch_rejected
# ===========================================================================
def test_inverted_and_parity_contradicting_ranges_are_rejected_on_create(api):
    """A reversed side and a side whose bounds contradict its parity both fail.

    For either side, the low bound must not exceed the high bound, both bounds must have the parity declared for that side, and a side may not supply only one of its two bounds.
    A failure here is `ERR_RANGE_GEOMETRY_INVALID` (HTTP 422).

    Design: Corner/errors/bad_range_geometry_on_create_and_patch_rejected
    """
    jurisdiction = fx.setup_jurisdiction(api)
    j_id = jurisdiction["id"]
    road = fx.setup_road(api, j_id)
    assert road["version"] == 1

    # from_addr_left 198 > to_addr_left 100.
    inverted = api.create_road_centerline(
        {
            "primary_name": "S ELM DRIVE",
            "jurisdiction_id": j_id,
            "from_addr_left": 198,
            "to_addr_left": 100,
            "parity_left": "EVEN",
            "from_addr_right": 101,
            "to_addr_right": 199,
            "parity_right": "ODD",
        },
        ANALYST_HEADERS,
    )
    assert inverted.status_code == 422
    order_err = validate_error(inverted, ApiErrorId.RANGE_GEOMETRY_INVALID)

    # 101 and 199 are ODD numbers but parity_left declares EVEN.
    contradicting = api.create_road_centerline(
        {
            "primary_name": "W OAK BOULEVARD",
            "jurisdiction_id": j_id,
            "from_addr_left": 101,
            "to_addr_left": 199,
            "parity_left": "EVEN",
            "from_addr_right": 101,
            "to_addr_right": 199,
            "parity_right": "ODD",
        },
        ANALYST_HEADERS,
    )
    assert contradicting.status_code == 422
    parity_err = validate_error(contradicting, ApiErrorId.RANGE_GEOMETRY_INVALID)

    assert order_err["error_id"] == "ERR_RANGE_GEOMETRY_INVALID"
    assert parity_err["error_id"] == "ERR_RANGE_GEOMETRY_INVALID"

    stored = fx.read_road(api, road["id"])
    assert stored["to_addr_left"] == 198
    assert stored["version"] == 1
    assert stored["status"] == "DRAFT"
    assert stored["assignable_slot_count_left"] == 50
    _, road_meta = validate_paginated(
        api.list_road_centerlines({"jurisdiction_id": j_id, "limit": 100}, ANALYST_HEADERS)
    )
    assert road_meta["total_count"] == 1, "neither refused create stored a centerline"


def test_a_patch_whose_merged_result_is_invalid_is_rejected_on_the_geometry_not_the_version(api):
    """The patch body alone looks fine; the merged range [100, 98] does not.

    On an edit the check is evaluated against the **merged** result of the stored record and the supplied changes, not against the changes alone.
    A failure here is `ERR_RANGE_GEOMETRY_INVALID` (HTTP 422).

    Design: Corner/errors/bad_range_geometry_on_create_and_patch_rejected
    """
    jurisdiction = fx.setup_jurisdiction(api)
    road = fx.setup_road(api, jurisdiction["id"])
    assert road["version"] == 1

    # 98 is a legal EVEN number on its own, so only the merge is invalid.
    resp = api.patch_road_centerline(
        road["id"], {"to_addr_left": 98, "expected_road_version": 1}, ANALYST_HEADERS
    )
    assert resp.status_code == 422, "the version supplied was current, so this is not a 412"
    merge_err = validate_error(resp, ApiErrorId.RANGE_GEOMETRY_INVALID)
    assert merge_err["error_id"] == "ERR_RANGE_GEOMETRY_INVALID"

    stored = fx.read_road(api, road["id"])
    assert stored["to_addr_left"] == 198
    assert stored["version"] == 1
    assert stored["status"] == "DRAFT"
    assert stored["assignable_slot_count_left"] == 50
    _, road_meta = validate_paginated(
        api.list_road_centerlines(
            {"jurisdiction_id": jurisdiction["id"], "limit": 100}, ANALYST_HEADERS
        )
    )
    assert road_meta["total_count"] == 1


# ===========================================================================
# activate_an_already_active_address_point_rejected
# ===========================================================================
def test_activating_an_already_active_point_is_rejected_on_the_points_own_state(api):
    """The road is fine, so the refusal names the point rather than the road.

    Activating a point whose centerline is still `DRAFT` or already `RETIRED` is refused with `ERR_ROAD_INVALID_STATE`, because the blocking state belongs to the road rather than to the point; activating a point that is not `PENDING` is refused with `ERR_ADDRESS_POINT_INVALID_STATE`; and activating a point on a contested road is refused with `ERR_ROAD_FROZEN_BY_DISCREPANCY`.

    Design: Corner/errors/activate_an_already_active_address_point_rejected
    """
    world = fx.setup_active_point_on_published_road(api)
    assert world["point"]["status"] == "ACTIVE"

    err = validate_error(
        api.activate_address_point(world["point_id"], {}, ANALYST_HEADERS),
        ApiErrorId.ADDRESS_POINT_INVALID_STATE,
    )
    assert err["error_id"] == "ERR_ADDRESS_POINT_INVALID_STATE"

    point = fx.read_point(api, world["point_id"])
    assert point["status"] == "ACTIVE"
    # v1 on creation, v2 from the publish-triggered confidence refresh (the
    # road-status penalty moved from 5 to 0), v3 from the activation itself.
    assert point["version"] == 3, "the refused activation did not increment the version"
    assert point["confidence_score"] == 96.00, "no second provisional recompute happened"
    assert point["confidence_basis"] == "PROVISIONAL"

    road = fx.read_road(api, world["road_id"])
    assert road["status"] == "PUBLISHED"
    assert road["version"] == 3
    assert road["assignable_slot_count_left"] == 49, "the slot was consumed exactly once"


# ===========================================================================
# gis_review_on_a_voided_request_rejected
# ===========================================================================
def test_gis_review_on_a_voided_request_is_rejected_and_leaves_all_three_dimensions(api):
    """Voiding closes the request; the untouched review dimension stays PENDING_REVIEW.

    Review requires that `review_status` still be `PENDING_REVIEW` and that `fulfillment_status` be `OPEN`; reviewing an already-reviewed request is refused with `ERR_REQUEST_INVALID_STATE`.
    The address assignment request is the one entity that splits this code in two, because it carries three parallel state dimensions: when the fulfillment dimension is wrong for the requested action the code is `ERR_REQUEST_NOT_READY`, and when the review or utility dimension is wrong the code is `ERR_REQUEST_INVALID_STATE`.
    The coordinator supplies `void_reason`; `fulfillment_status` becomes `VOIDED` and the request's `version` increments by 1.

    Design: Corner/errors/gis_review_on_a_voided_request_rejected
    """
    world = fx.setup_draft_road_world(api)
    request = fx.setup_assignment_request(api, world["road_id"])
    voided = fx.void_request(api, request["id"], void_reason="Permit withdrawn by applicant")
    assert voided["fulfillment_status"] == "VOIDED"

    # The review dimension is still PENDING_REVIEW, so the only precondition the
    # void broke is the fulfillment one — and a wrong fulfillment dimension is
    # reported as ERR_REQUEST_NOT_READY.
    err = validate_error(
        api.gis_review_assignment_request(
            request["id"], {"decision": "APPROVE"}, ANALYST_HEADERS
        ),
        ApiErrorId.REQUEST_NOT_READY,
    )
    assert err["error_id"] == "ERR_REQUEST_NOT_READY"

    after = fx.read_request(api, request["id"])
    assert after["fulfillment_status"] == "VOIDED"
    assert after["review_status"] == "PENDING_REVIEW", (
        "the refused review left the review dimension exactly where it was"
    )
    assert after["utility_status"] == "PENDING_UTILITY"
    assert after["version"] == 2, "only the void bumped the version"
    assert after["minted_point_count"] == 0
    assert fx.read_road(api, world["road_id"])["assignable_slot_count_left"] == 50


# ===========================================================================
# assign_before_both_dimensions_clear_rejected
# ===========================================================================
def test_assigning_with_review_approved_but_utilities_pending_is_not_ready(api):
    """One of two dimensions cleared is not READY_TO_ASSIGN, so nothing is minted.

    It requires that `fulfillment_status` be exactly `READY_TO_ASSIGN` — any other value, whether because review is not approved, utility is not cleared, or the request is already fulfilled, is refused with `ERR_REQUEST_NOT_READY` — and that the referenced centerline's `status` be `DRAFT`, `VALIDATED` or `PUBLISHED`, which is to say not `RETIRED`.
    An approval moves `review_status` from `PENDING_REVIEW` to `GIS_APPROVED` and increments the request's `version` by 1; if `utility_status` is already `UTILITY_CLEARED` at that moment, the derived join promotes `fulfillment_status` to `READY_TO_ASSIGN`.

    Design: Corner/errors/assign_before_both_dimensions_clear_rejected
    """
    world = fx.setup_validated_road_world(api)
    request = fx.setup_assignment_request(api, world["road_id"], requested_unit_count=2)
    reviewed = fx.gis_review(api, request["id"], "APPROVE")
    assert reviewed["review_status"] == "GIS_APPROVED"
    assert reviewed["fulfillment_status"] == "OPEN", "utilities are still pending"

    err = validate_error(
        api.assign_assignment_request(request["id"], {}, ANALYST_HEADERS),
        ApiErrorId.REQUEST_NOT_READY,
    )
    assert err["error_id"] == "ERR_REQUEST_NOT_READY"

    after = fx.read_request(api, request["id"])
    assert after["review_status"] == "GIS_APPROVED"
    assert after["utility_status"] == "PENDING_UTILITY"
    assert after["fulfillment_status"] == "OPEN"
    assert after["assigned_house_number"] is None
    assert after["assigned_address_point_id"] is None
    assert after["minted_point_count"] == 0, "not even the base point was minted"
    assert after["version"] == 2, "only the approval bumped the version"

    assert fx.read_road(api, world["road_id"])["assignable_slot_count_left"] == 50
    _, point_meta = validate_paginated(
        api.list_address_points({"limit": 100}, ANALYST_HEADERS)
    )
    assert point_meta["total_count"] == 0


# ===========================================================================
# certify_a_rejected_report_rejected
# ===========================================================================
def test_certifying_a_rejected_report_is_refused_and_the_scores_stand(api):
    """REJECTED is terminal, so certification cannot resurrect the report.

    **Rejection** advances the report `GENERATED → REJECTED`, requires only that the report's `status` be `GENERATED`, records `rejection_reason` from the payload, and increments the report's `version` by 1.
    Certifying or rejecting a report that is not `GENERATED`, including certifying one that is already `CERTIFIED` or `DECERTIFIED`, is refused with `ERR_REPORT_INVALID_STATE` (HTTP 409).

    Design: Corner/errors/certify_a_rejected_report_rejected
    """
    world = fx.setup_base_geography(api)
    road = fx.setup_road(api, world["j_id"], primary_name="N. Maple St")
    report = fx.setup_road_scoped_report(api, road["id"])

    # ROAD_UNVALIDATED, ROAD_NAME_NOT_NORMALIZED, ROAD_QC_DIRTY, ROAD_NO_ADDRESSES.
    assert report["defect_count"] == 4
    assert report["blocking_defect_count"] == 1
    assert report["warning_defect_count"] == 2
    assert report["info_defect_count"] == 1
    assert report["quality_score"] == 93.40
    assert report["advisory_quality_score"] == 96.25
    assert report["quality_tier"] == "B"

    rejected = fx.reject_report(
        api, report["id"], rejection_reason="Scan ran before the nightly parcel load completed"
    )
    assert rejected["status"] == "REJECTED"

    err = validate_error(
        api.certify_qc_report(report["id"], {}, QC_HEADERS),
        ApiErrorId.REPORT_INVALID_STATE,
    )
    assert err["error_id"] == "ERR_REPORT_INVALID_STATE"

    after = fx.read_report(api, report["id"])
    assert after["status"] == "REJECTED"
    assert after["certified_at"] is None
    assert after["certified_by_user_id"] is None
    assert after["rejection_reason"] == "Scan ran before the nightly parcel load completed"
    assert after["defect_count"] == 4
    assert after["open_blocking_defect_count"] == 1
    assert after["waived_blocking_count"] == 0
    assert after["quality_score"] == 93.40
    assert after["advisory_quality_score"] == 96.25
    assert after["quality_tier"] == "B"
    assert after["is_provisioning_eligible"] is False

    stored_road = fx.read_road(api, road["id"])
    assert stored_road["status"] == "DRAFT"
    assert stored_road["qc_dirty"] is True
    assert stored_road["normalized_name"] == "N MAPLE STREET"


# ===========================================================================
# waive_an_already_waived_defect_rejected
# ===========================================================================
def test_waiving_an_already_waived_defect_is_refused_and_keeps_the_first_reason(api):
    """The second waiver is refused and neither the reason nor the scores move again.

    The certifier supplies `waiver_reason`, and the defect advances `OPEN → WAIVED` with `waived_by_user_id` set to the calling `X-User-ID`, `waived_at` stamped at the logical clock instant, and the defect's own `version` incremented by 1.
    Waiving an already-`WAIVED` defect, or waiving any defect on a report that has left `GENERATED`, is refused with `ERR_DEFECT_INVALID_STATE` (HTTP 409).

    Design: Corner/errors/waive_an_already_waived_defect_rejected
    """
    world = fx.setup_base_geography(api)
    road = fx.setup_road(api, world["j_id"], primary_name="N. Maple St")
    report = fx.setup_road_scoped_report(api, road["id"])
    assert report["defect_count"] == 4
    assert report["open_blocking_defect_count"] == 1

    blocking = fx.list_defects(
        api, report["id"], {"defect_code": "ROAD_UNVALIDATED", "limit": 100}
    )
    assert len(blocking) == 1, "the DRAFT centerline raised exactly one ROAD_UNVALIDATED"
    defect_id = blocking[0]["id"]

    waived = fx.waive_defect(
        api, defect_id, waiver_reason="Validation deferred to the next map cycle"
    )
    assert waived["status"] == "WAIVED"
    assert waived["waived_by_user_id"] == "qc-1"
    assert waived["waiver_reason"] == "Validation deferred to the next map cycle"
    assert waived["severity"] == "BLOCKING"
    assert waived["defect_category"] == "ROAD"
    assert waived["version"] == 2

    err = validate_error(
        api.waive_qc_defect(
            defect_id, {"waiver_reason": "Duplicate waiver attempt"}, QC_HEADERS
        ),
        ApiErrorId.DEFECT_INVALID_STATE,
    )
    assert err["error_id"] == "ERR_DEFECT_INVALID_STATE"

    after = fx.read_defect(api, defect_id)
    assert after["status"] == "WAIVED"
    assert after["waiver_reason"] == "Validation deferred to the next map cycle", (
        "the refused second waiver did not overwrite the accepted reason"
    )
    assert after["version"] == 2

    # One waiver raised the strict base to 97.15 and lowered eligibility by the
    # tier-A rate of 1.0 exactly once.
    stored = fx.read_report(api, report["id"])
    assert stored["status"] == "GENERATED"
    assert stored["defect_count"] == 4
    assert stored["open_blocking_defect_count"] == 0
    assert stored["waived_blocking_count"] == 1
    assert stored["quality_score"] == 97.15
    assert stored["advisory_quality_score"] == 96.25
    assert stored["quality_tier"] == "A"
    assert stored["provisioning_eligibility_score"] == 96.15
    assert stored["is_provisioning_eligible"] is True


# ===========================================================================
# publish_a_draft_package_rejected
# ===========================================================================
def test_publishing_a_draft_package_is_refused_on_its_state_not_on_the_report(api):
    """The package never sealed, so the state check answers before any release gate.

    The new package lands in `DRAFT` with `package_version` null, `record_count`, `pinned_record_count`, `fresh_pin_count` and `stale_pin_count` all at zero, `drift_detected` false, and `sealed_at`, `published_at`, `sealed_by_user_id`, `published_by_user_id`, `invalidated_reason` and `rollback_reason` all null.
    Publishing a package that is not `SEALED` is `ERR_PACKAGE_INVALID_STATE`.

    Design: Corner/errors/publish_a_draft_package_rejected
    """
    world = fx.setup_active_point_on_published_road(api)
    report = fx.setup_road_scoped_report(api, world["road_id"])
    assert report["status"] == "GENERATED", "the report was never certified"
    package = fx.setup_package(api, world["j_id"], report["id"], "MAPPING")
    assert package["status"] == "DRAFT"

    err = validate_error(
        api.publish_package(package["id"], {}, PROV_HEADERS),
        ApiErrorId.PACKAGE_INVALID_STATE,
    )
    assert err["error_id"] == "ERR_PACKAGE_INVALID_STATE", (
        "the uncertified report is a seal gate and must not pre-empt the state check"
    )

    after = fx.read_package(api, package["id"])
    assert after["status"] == "DRAFT"
    assert after["package_version"] is None
    assert after["record_count"] == 0
    assert after["pinned_record_count"] == 0
    assert after["fresh_pin_count"] == 0
    assert after["stale_pin_count"] == 0
    assert after["drift_detected"] is False
    assert after["sealed_at"] is None
    assert after["published_at"] is None
    assert after["sealed_by_user_id"] is None
    assert after["published_by_user_id"] is None
    assert after["version"] == 1, "the refused publication did not touch the package"
    assert fx.read_report(api, report["id"])["status"] == "GENERATED"
    _, record_meta = validate_paginated(
        api.list_package_records(package["id"], {"limit": 100}, PROV_HEADERS)
    )
    assert record_meta["total_count"] == 0, "no snapshot rows were ever created"


# ===========================================================================
# seal_a_package_with_an_empty_record_set_rejected
# ===========================================================================
def test_sealing_a_package_whose_record_set_is_empty_is_refused_as_empty(api):
    """A VALIDATED centerline and no active points leave nothing to snapshot.

    Second, the in-scope record set must be non-empty, or the seal is refused with `ERR_PACKAGE_EMPTY` (HTTP 422).
    Every centerline whose `status` is `PUBLISHED` and whose `jurisdiction_id` is that jurisdiction is in scope as a `ROAD_CENTERLINE` record.

    Design: Corner/errors/seal_a_package_with_an_empty_record_set_rejected
    """
    world = fx.setup_validated_road_world(api)
    report = fx.setup_road_scoped_report(api, world["road_id"])
    # Only ROAD_NO_ADDRESSES fires: the road is normalized, VALIDATED and clean.
    assert report["defect_count"] == 1
    assert report["quality_score"] == 99.55
    assert report["quality_tier"] == "A"
    certified = fx.certify_report(api, report["id"])
    assert certified["status"] == "CERTIFIED"
    assert certified["is_provisioning_eligible"] is True

    package = fx.setup_package(api, world["j_id"], report["id"], "MAPPING")
    resp = api.seal_package(package["id"], {}, PROV_HEADERS)
    assert resp.status_code == 422
    err = validate_error(resp, ApiErrorId.PACKAGE_EMPTY)
    assert err["error_id"] == "ERR_PACKAGE_EMPTY", (
        "the certified and eligible report clears gates one and three"
    )

    after = fx.read_package(api, package["id"])
    assert after["status"] == "DRAFT"
    assert after["package_version"] is None, "no release number was consumed"
    assert after["record_count"] == 0
    assert after["sealed_at"] is None
    assert after["version"] == 1
    _, record_meta = validate_paginated(
        api.list_package_records(package["id"], {"limit": 100}, PROV_HEADERS)
    )
    assert record_meta["total_count"] == 0

    road = fx.read_road(api, world["road_id"])
    assert road["status"] == "VALIDATED", "a VALIDATED centerline is not packageable"
    assert road["version"] == 2


# ===========================================================================
# seal_a_package_below_the_provisioning_threshold_rejected
# ===========================================================================
def test_sealing_on_a_certified_but_ineligible_report_is_refused_on_the_score(api):
    """Five low-confidence mismatched points score 87.63, under the inclusive 90.00.

    Third, the referenced report's `is_provisioning_eligible` must be true — equivalently, its `provisioning_eligibility_score` must be at least 90.00 — or the seal is refused with `ERR_QC_SCORE_BELOW_THRESHOLD` (HTTP 422).
    The `is_provisioning_eligible` flag is true when `provisioning_eligibility_score` is greater than or equal to 90.00 — the threshold is inclusive — **and** `open_blocking_defect_count` is zero.

    Design: Corner/errors/seal_a_package_below_the_provisioning_threshold_rejected
    """
    world = fx.setup_published_road_world(api)
    points = [
        fx.setup_address_point(
            api,
            world["road_id"],
            world["cell_id"],
            house_number=number,
            source="POSTAL",
            postal_city="LOVELAND",
            geometry_verified=True,
        )
        for number in (100, 102, 104, 106, 108)
    ]
    # 45 base plus 12 geometry plus 6 for a base address, no postal match and no
    # road penalty on a PUBLISHED centerline.
    assert points[0]["confidence_score"] == 63.00

    report = fx.setup_road_scoped_report(api, world["road_id"])
    assert report["defect_count"] == 10, "one mismatch and one low-confidence per point"
    assert report["blocking_defect_count"] == 0
    assert report["warning_defect_count"] == 5
    assert report["info_defect_count"] == 5
    assert report["quality_score"] == 87.63
    assert report["advisory_quality_score"] == 100.00
    assert report["quality_tier"] == "B"
    assert report["provisioning_eligibility_score"] == 87.63
    assert report["is_provisioning_eligible"] is False

    certified = fx.certify_report(api, report["id"])
    assert certified["status"] == "CERTIFIED"
    assert certified["is_provisioning_eligible"] is False
    stamped = fx.read_point(api, points[0]["id"])
    assert stamped["confidence_basis"] == "CERTIFIED"
    assert stamped["certified_confidence_score"] == 63.00

    package = fx.setup_package(api, world["j_id"], report["id"], "MAPPING")
    resp = api.seal_package(package["id"], {}, PROV_HEADERS)
    assert resp.status_code == 422
    err = validate_error(resp, ApiErrorId.QC_SCORE_BELOW_THRESHOLD)
    assert err["error_id"] == "ERR_QC_SCORE_BELOW_THRESHOLD", (
        "the record set is non-empty, so gate two passes and gate three fires"
    )

    after = fx.read_package(api, package["id"])
    assert after["status"] == "DRAFT"
    assert after["package_version"] is None
    assert after["record_count"] == 0
    assert after["sealed_at"] is None
    assert after["version"] == 1


# ===========================================================================
# publish_a_package_with_stale_pins_rejected
# ===========================================================================
def test_publishing_a_sealed_package_whose_point_pin_went_stale_is_refused(api):
    """A second certification restamps the point, staling its pin without invalidating.

    Non-destructive drift never invalidates anything — it leaves the package `SEALED` with `drift_detected` true, and the refusal only materialises at publication time.
    Third, `stale_pin_count` must be zero, or the request is refused with `ERR_PACKAGE_PINS_STALE` (HTTP 409).

    Design: Corner/errors/publish_a_package_with_stale_pins_rejected
    """
    world = fx.setup_sealed_package(api, "MAPPING")
    sealed = world["package"]
    assert sealed["status"] == "SEALED"
    assert sealed["record_count"] == 2, "one ROAD_CENTERLINE and one ADDRESS_POINT"
    assert sealed["fresh_pin_count"] == 2
    assert sealed["stale_pin_count"] == 0
    assert sealed["drift_detected"] is False

    # A second scan and certification restamps certified confidence on the point,
    # bumping its version past the pinned 4.
    second_report = fx.setup_road_scoped_report(api, world["road_id"])
    assert second_report["defect_count"] == 0
    fx.certify_report(api, second_report["id"])
    point = fx.read_point(api, world["point_id"])
    assert point["status"] == "ACTIVE", "the point is still live, so the drift is benign"
    # v1 create, v2 publish refresh, v3 activate, v4 first certification, v5 second.
    assert point["version"] == 5
    assert point["certified_confidence_score"] == 96.00

    err = validate_error(
        api.publish_package(world["package_id"], {}, PROV_HEADERS),
        ApiErrorId.PACKAGE_PINS_STALE,
    )
    assert err["error_id"] == "ERR_PACKAGE_PINS_STALE"

    after = fx.read_package(api, world["package_id"])
    assert after["status"] == "SEALED", "non-destructive drift never invalidates"
    assert after["drift_detected"] is True
    assert after["stale_pin_count"] == 1
    assert after["fresh_pin_count"] == 1
    assert after["record_count"] == 2
    assert after["published_at"] is None
    assert after["published_by_user_id"] is None
    assert after["package_version"] == 1

    stale_rows = fx.read_package_records(
        api, world["package_id"], {"pin_state": "STALE", "limit": 100}
    )
    assert len(stale_rows) == 1
    assert stale_rows[0]["record_type"] == "ADDRESS_POINT"
    assert stale_rows[0]["record_id"] == world["point_id"]
    assert stale_rows[0]["pinned_version"] == 4
    fresh_rows = fx.read_package_records(
        api, world["package_id"], {"pin_state": "FRESH", "limit": 100}
    )
    assert len(fresh_rows) == 1
    assert fresh_rows[0]["record_type"] == "ROAD_CENTERLINE"
    assert fresh_rows[0]["pinned_version"] == 3


# ===========================================================================
# publish_an_e911_package_with_a_forward_gap_rejected
# ===========================================================================
def test_publishing_a_dispatch_package_over_an_uncovered_cell_is_refused(api):
    """One cell and no boundaries at all leave three uncovered service pairs.

    Second, when the package's `channel` is `DISPATCH_E911`, the jurisdiction's `forward_gap_pair_count` must be zero, or the request is refused with `ERR_COVERAGE_GAP_BLOCKS_E911` (HTTP 409); the `MAPPING` and `PUBLIC` channels are not gated on coverage at all, and note that the gate reads the forward-window counter rather than the instantaneous one, so a gap that opens inside the thirty-day horizon blocks the release even though every cell is covered at this instant.
    A jurisdiction's `gap_pair_count` is the number of gap pairs across all of its cells taken against all three service types; its `covered_cell_count` is the number of its cells that have exactly one covering `ACTIVE` assignment for **all three** service types simultaneously; and a cell's own `active_assignment_count` is the number of `ACTIVE` assignments covering the current instant on that cell, summed across service types.

    Design: Corner/errors/publish_an_e911_package_with_a_forward_gap_rejected
    """
    world = fx.setup_published_road_world(api)
    report = fx.setup_road_scoped_report(api, world["road_id"])
    certified = fx.certify_report(api, report["id"])
    assert certified["is_provisioning_eligible"] is True

    package = fx.setup_package(api, world["j_id"], report["id"], "DISPATCH_E911")
    sealed = fx.seal_package(api, package["id"])
    assert sealed["status"] == "SEALED"
    assert sealed["record_count"] == 1, "only the PUBLISHED centerline is in scope"
    assert sealed["package_version"] == 1

    jurisdiction = fx.read_jurisdiction(api, world["j_id"])
    assert jurisdiction["cell_count"] == 1
    assert jurisdiction["covered_cell_count"] == 0
    assert jurisdiction["gap_pair_count"] == 3
    assert jurisdiction["forward_gap_pair_count"] == 3

    err = validate_error(
        api.publish_package(package["id"], {}, PROV_HEADERS),
        ApiErrorId.COVERAGE_GAP_BLOCKS_E911,
    )
    assert err["error_id"] == "ERR_COVERAGE_GAP_BLOCKS_E911"

    after = fx.read_package(api, package["id"])
    assert after["status"] == "SEALED"
    assert after["published_at"] is None
    assert after["published_by_user_id"] is None
    assert after["package_version"] == 1
    assert after["stale_pin_count"] == 0
    assert after["drift_detected"] is False
    _, record_meta = validate_paginated(
        api.list_package_records(package["id"], {"limit": 100}, PROV_HEADERS)
    )
    assert record_meta["total_count"] == 1
    records = fx.read_package_records(api, package["id"])
    assert records[0]["record_type"] == "ROAD_CENTERLINE"


# ===========================================================================
# rollback_a_package_without_a_predecessor_rejected
# ===========================================================================
def test_rolling_back_the_only_release_on_a_channel_is_refused(api):
    """Nothing was ever superseded, so there is no release to restore.

    The officer supplies `rollback_reason`; the package must currently be `PUBLISHED`, and a `SUPERSEDED` predecessor must exist on the same channel-and-jurisdiction pairing, or the request is refused with `ERR_NO_PUBLISHED_PREDECESSOR` (HTTP 409) — because rolling back the only release would leave the channel unserved.

    Design: Corner/errors/rollback_a_package_without_a_predecessor_rejected
    """
    fx.reset_clock_to_startup(api)
    world = fx.setup_published_package(api, "MAPPING")
    published = world["package"]
    assert published["status"] == "PUBLISHED"
    assert published["package_version"] == 1

    err = validate_error(
        api.rollback_package(
            world["package_id"],
            {"rollback_reason": "Dispatch reported bad geometry on the release"},
            PROV_HEADERS,
        ),
        ApiErrorId.NO_PUBLISHED_PREDECESSOR,
    )
    assert err["error_id"] == "ERR_NO_PUBLISHED_PREDECESSOR"

    after = fx.read_package(api, world["package_id"])
    assert after["status"] == "PUBLISHED", "the only release stays in service"
    assert after["rollback_reason"] is None
    assert after["package_version"] == 1
    assert after["version"] == 3, "create, seal and publish and nothing else"
    assert after["published_at"] == "2026-08-01T00:00:00.000Z"
    assert after["published_by_user_id"] == "prov-1"

    _, superseded_meta = validate_paginated(
        api.list_packages(
            {"channel": "MAPPING", "status": "SUPERSEDED", "limit": 100}, PROV_HEADERS
        )
    )
    assert superseded_meta["total_count"] == 0, "there was never a predecessor"
