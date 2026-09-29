"""Difficulty rule 7 — cross_entity_state_dependency.

Three distinct entity pairs in which the transition is defined for the target
record and refused because a *different* record two hops away is in the wrong
state, and in which the identical call succeeds once that other record moves:

  * AddressPoint -> RoadCenterline      (ERR_ROAD_INVALID_STATE)
  * ProvisioningPackage -> QcValidationReport (ERR_QC_REPORT_NOT_CERTIFIED)
  * EmergencyServiceBoundary -> Agency  (ERR_AGENCY_NOT_ACTIVE)

Every test builds its whole world through documented endpoints, because the
harness restarts the server with an empty database before each test.
"""

from test_helpers import (
    ANALYST_HEADERS,
    PROV_HEADERS,
    QC_HEADERS,
    ApiErrorId,
    assert_address_point,
    assert_boundary,
    assert_package,
    assert_road_centerline,
    assert_score_equals,
    assert_exact_millisecond_timestamp,
    make_agency_liaison_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx


# ===========================================================================
# Instance 1 — address_point_activate_requires_validated_road
# ===========================================================================
def test_activating_a_pending_point_on_a_draft_centerline_is_refused_naming_the_road(api):
    """A perfectly PENDING point cannot activate while its owning centerline is still DRAFT, and the refusal names the ROAD.

    Activating a point whose centerline is still `DRAFT` or already `RETIRED` is refused with `ERR_ROAD_INVALID_STATE`, because the blocking state belongs to the road rather than to the point; activating a point that is not `PENDING` is refused with `ERR_ADDRESS_POINT_INVALID_STATE`; and activating a point on a contested road is refused with `ERR_ROAD_FROZEN_BY_DISCREPANCY`.

    Design: Difficulty/cross_entity_state_dependency/address_point_activate_requires_validated_road
    """
    fx.reset_clock_to_startup(api)
    world = fx.setup_pending_point_on_draft_road(api)
    point_id = world["point_id"]

    # 70 (PARCEL) + 12 (geometry_verified) + 8 (postal city match) + 6 (base) - 15 (DRAFT road)
    assert_address_point(world["point"], status="PENDING", confidence_basis="PROVISIONAL")
    assert_score_equals(world["point"]["confidence_score"], 81.00, "confidence_score")

    road = fx.read_road(api, world["road_id"])
    assert_road_centerline(road, status="DRAFT", open_discrepancy_case_count=0)

    resp = api.activate_address_point(point_id, {}, ANALYST_HEADERS)
    validate_error(resp, ApiErrorId.ROAD_INVALID_STATE, 409)

    after = fx.read_point(api, point_id)
    assert_address_point(after, status="PENDING")
    assert_score_equals(after["confidence_score"], 81.00, "confidence_score")
    assert after["certified_confidence_score"] is None


def test_validating_the_owning_centerline_lets_the_identical_activation_succeed(api):
    """Nothing about the point changes: validating the road alone turns the refused activation into a 200 and lifts confidence from 81.00 to 91.00.

    Three preconditions apply: the referenced centerline's `status` must be `VALIDATED` or `PUBLISHED`; that centerline's `open_discrepancy_case_count` must be zero; and when the point carries a non-null `unit_id`, its parent point's `status` must be `ACTIVE`.

    Design: Difficulty/cross_entity_state_dependency/address_point_activate_requires_validated_road
    """
    fx.reset_clock_to_startup(api)
    world = fx.setup_pending_point_on_draft_road(api)
    point_id = world["point_id"]
    road_id = world["road_id"]

    first = api.activate_address_point(point_id, {}, ANALYST_HEADERS)
    validate_error(first, ApiErrorId.ROAD_INVALID_STATE, 409)

    validated = fx.validate_road(api, road_id)
    assert_road_centerline(validated, status="VALIDATED", qc_dirty=False)

    second = api.activate_address_point(point_id, {}, ANALYST_HEADERS)
    activated = validate_success(second, 200)
    assert_address_point(activated, status="ACTIVE", confidence_basis="PROVISIONAL")
    # ROAD_STATUS_PENALTY drops from 15 to 5, so 81.00 becomes 91.00.
    assert_score_equals(activated["confidence_score"], 91.00, "confidence_score")

    road = fx.read_road(api, road_id)
    assert_road_centerline(road, status="VALIDATED")
    assert road["assignable_slot_count_left"] == 49, (
        "one PENDING-or-ACTIVE base point consumes exactly one of the fifty left slots"
    )


# ===========================================================================
# Instance 2 — package_seal_requires_certified_report
# ===========================================================================
def test_sealing_a_package_whose_qc_report_is_only_generated_is_refused(api):
    """A DRAFT package over a perfectly valid in-scope record set cannot seal while its authorising report is merely GENERATED, and no partial snapshot is left behind.

    First, the referenced report's `status` must be `CERTIFIED`, or the seal is refused with `ERR_QC_REPORT_NOT_CERTIFIED` (HTTP 409).

    Design: Difficulty/cross_entity_state_dependency/package_seal_requires_certified_report
    """
    fx.reset_clock_to_startup(api)
    world = fx.setup_active_point_on_published_road(api)
    report = fx.setup_road_scoped_report(api, world["road_id"])
    assert report["status"] == "GENERATED", "a fresh scan lands in GENERATED"
    assert report["is_provisioning_eligible"] is True

    package = fx.setup_package(api, world["j_id"], report["id"], "MAPPING")
    assert_package(package, status="DRAFT", pinned_record_count=0)
    assert package["package_version"] is None

    resp = api.seal_package(package["id"], {}, PROV_HEADERS)
    validate_error(resp, ApiErrorId.QC_REPORT_NOT_CERTIFIED, 409)

    after = fx.read_package(api, package["id"])
    assert_package(after, status="DRAFT", pinned_record_count=0, record_count=0)
    assert after["package_version"] is None, "a refused seal assigns no release number"
    assert after["sealed_at"] is None
    assert after["sealed_by_user_id"] is None
    assert fx.read_package_records(api, package["id"]) == [], "no partial snapshot"


def test_certifying_the_report_lets_the_unchanged_package_seal(api):
    """The SAME seal call succeeds the moment the report is CERTIFIED, pinning both in-scope records at version 1 of the snapshot.

    The package then records `record_count`, `pinned_record_count` and `fresh_pin_count` all equal to the number of pins created, `stale_pin_count` at zero, `sealed_at` at the logical clock instant, and `sealed_by_user_id` from the calling `X-User-ID`, and increments its own `version` by 1.

    Design: Difficulty/cross_entity_state_dependency/package_seal_requires_certified_report
    """
    fx.reset_clock_to_startup(api)
    world = fx.setup_active_point_on_published_road(api)
    report = fx.setup_road_scoped_report(api, world["road_id"])
    package = fx.setup_package(api, world["j_id"], report["id"], "MAPPING")

    first = api.seal_package(package["id"], {}, PROV_HEADERS)
    validate_error(first, ApiErrorId.QC_REPORT_NOT_CERTIFIED, 409)

    certified = validate_success(api.certify_qc_report(report["id"], {}, QC_HEADERS), 200)
    assert certified["status"] == "CERTIFIED"

    second = api.seal_package(package["id"], {}, PROV_HEADERS)
    sealed = validate_success(second, 200)
    assert_package(
        sealed,
        status="SEALED",
        package_version=1,
        pinned_record_count=2,
        fresh_pin_count=2,
        stale_pin_count=0,
        drift_detected=False,
        sealed_by_user_id="prov-1",
    )
    assert_exact_millisecond_timestamp(sealed["sealed_at"], "sealed_at")
    assert sealed["sealed_at"] == "2026-08-01T00:00:00.000Z"

    # One ROAD_CENTERLINE record plus one ADDRESS_POINT record.
    records = fx.read_package_records(api, package["id"])
    assert sorted(row["record_type"] for row in records) == [
        "ADDRESS_POINT",
        "ROAD_CENTERLINE",
    ]
    assert all(row["pin_state"] == "FRESH" for row in records)

    report_after = fx.read_report(api, report["id"])
    assert report_after["status"] == "CERTIFIED"


# ===========================================================================
# Instance 3 — boundary_activate_requires_active_agency
# ===========================================================================
def test_activating_a_proposed_boundary_owned_by_a_suspended_agency_is_refused(api):
    """The boundary is correctly PROPOSED with a valid cell claim; the blocking state lives on its owning Agency, two hops away.

    A `SUSPENDED` agency retains its existing active boundaries but may not activate new ones and may not be named as a party to a new discrepancy case — either attempt is refused with `ERR_AGENCY_NOT_ACTIVE`.

    Design: Difficulty/cross_entity_state_dependency/boundary_activate_requires_active_agency
    """
    fx.reset_clock_to_startup(api)
    world = fx.setup_base_geography(api)
    law = fx.setup_agency(api, world["j_id"], "LAW")

    built = fx.setup_proposed_boundary_on_cell(api, law["id"], world["cell_id"])
    assert_boundary(built["boundary"], status="PROPOSED", service_type="LAW")

    suspended = fx.suspend_agency(api, law["id"])
    assert suspended["status"] == "SUSPENDED"

    resp = api.activate_boundary(
        built["boundary_id"], {}, make_agency_liaison_headers(law["id"])
    )
    validate_error(resp, ApiErrorId.AGENCY_NOT_ACTIVE, 409)

    boundary = fx.read_boundary(api, built["boundary_id"])
    assert_boundary(boundary, status="PROPOSED")
    assignment = fx.read_cell_assignment(api, built["assignment_id"])
    assert assignment["status"] == "PENDING", "suspension never touches the claim's status"
    assert fx.read_agency(api, law["id"])["status"] == "SUSPENDED"
    assert fx.read_cell(api, world["cell_id"])["active_assignment_count"] == 0


def test_the_sibling_boundary_of_an_active_agency_activates_on_the_same_cell(api):
    """In the same fixture the FIRE boundary of an ACTIVE agency activates on the very cell the suspended LAW agency was refused on.

    Activation transitions every cell assignment on the boundary from `PENDING` to `ACTIVE`, each incrementing its own `version` by 1 and refreshing its owning cell's `active_assignment_count`, then refreshes the jurisdiction's coverage counters, then increments the boundary's `version` by 1.

    Design: Difficulty/cross_entity_state_dependency/boundary_activate_requires_active_agency
    """
    fx.reset_clock_to_startup(api)
    world = fx.setup_base_geography(api)
    law = fx.setup_agency(api, world["j_id"], "LAW")
    fire = fx.setup_agency(api, world["j_id"], "FIRE")

    law_built = fx.setup_proposed_boundary_on_cell(api, law["id"], world["cell_id"])
    fire_built = fx.setup_proposed_boundary_on_cell(api, fire["id"], world["cell_id"])
    fx.suspend_agency(api, law["id"])

    refused = api.activate_boundary(
        law_built["boundary_id"], {}, make_agency_liaison_headers(law["id"])
    )
    validate_error(refused, ApiErrorId.AGENCY_NOT_ACTIVE, 409)

    resp = api.activate_boundary(
        fire_built["boundary_id"], {}, make_agency_liaison_headers(fire["id"])
    )
    activated = validate_success(resp, 200)
    assert_boundary(activated, status="ACTIVE", service_type="FIRE")

    assert fx.read_cell_assignment(api, fire_built["assignment_id"])["status"] == "ACTIVE"
    assert fx.read_cell_assignment(api, law_built["assignment_id"])["status"] == "PENDING"
    assert fx.read_boundary(api, law_built["boundary_id"])["status"] == "PROPOSED"

    cell = fx.read_cell(api, world["cell_id"])
    assert cell["active_assignment_count"] == 1, "only the FIRE assignment activated"

    jurisdiction = fx.read_jurisdiction(api, world["j_id"])
    assert jurisdiction["gap_pair_count"] == 2, "LAW and EMS remain uncovered"
    assert jurisdiction["covered_cell_count"] == 0, "a cell needs all three service types"
