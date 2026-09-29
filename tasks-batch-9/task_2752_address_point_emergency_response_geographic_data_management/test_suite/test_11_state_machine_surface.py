"""State-machine surface of the County Address and Emergency Response GIS API.

Queue B of the scaffold corner design: the `state_machines` section — declared
initial states, valid transitions, invalid transitions, terminal-state lockdown,
the refusal of idempotency, side effects that ride along with a transition, the
cross-entity reach of a suspension, the parallel dimensions of an assignment
request, and the cyclic negotiation that escalates on its fourth filing.

Every test builds its own world through documented endpoints; the runner
restarts the server before each test, so each one starts from an empty database
with the logical clock at its startup value of 2026-08-01T00:00:00Z.
"""

from test_helpers import (
    ANALYST_HEADERS,
    PERMIT_HEADERS,
    QC_HEADERS,
    SYSADMIN_HEADERS,
    ApiErrorId,
    assert_address_point,
    assert_agency,
    assert_assignment_request,
    assert_boundary,
    assert_cell_assignment,
    assert_coverage_cell,
    assert_discrepancy_case,
    assert_discrepancy_proposal,
    assert_package,
    assert_qc_report,
    assert_road_centerline,
    assert_score_equals,
    assert_slot_counters,
    make_agency_liaison_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


# ===========================================================================
# valid_transition — DRAFT -> VALIDATED drags the confidence refresh with it
# ===========================================================================
def test_validating_a_draft_centerline_rescores_its_points_at_the_lower_road_penalty(api):
    """
    Validating a `DRAFT` centerline advances it `DRAFT → VALIDATED`.
    Validation sets `qc_dirty` to false, increments the centerline's `version` by 1, triggers a confidence refresh in which the road-status penalty moves from 15 down to 5, and then evaluates pin staleness for the centerline and each recomputed address point.

    Design: Corner/state_machines/validate_draft_road_promotes_and_refreshes_point_confidence
    """
    world = fx.setup_base_geography(api)
    road = fx.setup_road(api, world["j_id"])
    assert_road_centerline(road, status="DRAFT", qc_dirty=True, version=1)

    point = fx.setup_address_point(
        api, road["id"], world["cell_id"], geometry_verified=True
    )
    # 70 (PARCEL) + 12 (geometry) + 8 (postal city) + 6 (base address) - 15 (DRAFT)
    assert_address_point(
        point,
        status="PENDING",
        confidence_basis="PROVISIONAL",
        version=1,
    )
    assert_score_equals(point["confidence_score"], 81.00, "confidence_score")

    validated = validate_success(
        api.validate_road_centerline(road["id"], {}, ANALYST_HEADERS), 200
    )
    assert_road_centerline(
        validated,
        status="VALIDATED",
        qc_dirty=False,
        version=2,
    )

    refreshed = fx.read_point(api, point["id"])
    # 70 + 12 + 8 + 6 - 5 (VALIDATED), and CONFIDENCE_REFRESH bumped the point.
    assert_score_equals(refreshed["confidence_score"], 91.00, "confidence_score")
    assert_address_point(
        refreshed,
        status="PENDING",
        confidence_basis="PROVISIONAL",
        version=2,
    )
    assert refreshed["certified_confidence_score"] is None, (
        "the provisional variant leaves certified_confidence_score null"
    )


# ===========================================================================
# precondition_enforcement — GENERATED -> CERTIFIED needs zero open blockers
# ===========================================================================
def test_certifying_a_report_with_an_open_blocking_defect_is_refused(api):
    """
    Two preconditions apply, evaluated in this order: the report's `open_blocking_defect_count` must be zero, or the request is refused with `ERR_QC_BLOCKING_DEFECTS_OPEN` (HTTP 409); and the calling `X-User-ID` must differ from the report's `generated_by_user_id`, or the request is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
    A `ROAD`-scoped report therefore never emits a boundary-category finding or an uncovered-cell finding, and its boundary category consequently always scores a perfect 100.

    Design: Corner/state_machines/certify_report_with_open_blocking_defect_rejected
    """
    world = fx.setup_geography_without_cells(api)
    road = fx.setup_road(api, world["j_id"])

    report = fx.setup_road_scoped_report(api, road["id"])
    assert_qc_report(
        report,
        scope="ROAD",
        status="GENERATED",
        defect_count=3,
        blocking_defect_count=1,
        warning_defect_count=1,
        info_defect_count=1,
        open_blocking_defect_count=1,
        waived_blocking_count=0,
        quality_tier="B",
        is_provisioning_eligible=False,
        version=1,
    )
    # ADDRESS 45.00 + ROAD 0.30*(100-18.0)=24.60 + BOUNDARY 25.00
    assert_score_equals(report["quality_score"], 94.60, "quality_score")
    # advisory counts BLOCKING only: 45.00 + 0.30*87.5=26.25 + 25.00
    assert_score_equals(
        report["advisory_quality_score"], 96.25, "advisory_quality_score"
    )
    assert_score_equals(
        report["provisioning_eligibility_score"],
        94.60,
        "provisioning_eligibility_score",
    )

    defects = fx.list_defects(api, report["id"])
    assert len(defects) == 3, f"expected exactly three defects, got {defects}"
    assert fx.defect_by_code(defects, "ROAD_UNVALIDATED")["severity"] == "BLOCKING"
    assert fx.defect_by_code(defects, "ROAD_QC_DIRTY")["severity"] == "WARNING"
    assert fx.defect_by_code(defects, "ROAD_NO_ADDRESSES")["severity"] == "INFO"

    refused = api.certify_qc_report(report["id"], {}, QC_HEADERS)
    validate_error(refused, ApiErrorId.QC_BLOCKING_DEFECTS_OPEN, 409)

    after = fx.read_report(api, report["id"])
    assert_qc_report(after, status="GENERATED", version=1)
    assert after["certified_at"] is None, "the refused certify stamped nothing"
    assert after["certified_by_user_id"] is None, "the refused certify named nobody"


# ===========================================================================
# idempotency — a second activate is refused, not silently re-applied
# ===========================================================================
def test_activating_an_already_active_boundary_is_refused_and_coverage_does_not_double(api):
    """
    Acting on an already-`RETIRED` boundary, proposing a boundary that is not `DRAFT`, or activating a boundary that is not `PROPOSED` are all `ERR_BOUNDARY_INVALID_STATE`.
    A jurisdiction's `gap_pair_count` is the number of gap pairs across all of its cells taken against all three service types; its `covered_cell_count` is the number of its cells that have exactly one covering `ACTIVE` assignment for **all three** service types simultaneously; and a cell's own `active_assignment_count` is the number of `ACTIVE` assignments covering the current instant on that cell, summed across service types.

    Design: Corner/state_machines/activate_boundary_twice_rejected
    """
    world = fx.setup_base_geography(api)
    law = fx.setup_agency(api, world["j_id"], "LAW")
    built = fx.setup_active_boundary_on_cell(api, law["id"], world["cell_id"])

    boundary_id = built["boundary_id"]
    assignment_id = built["assignment_id"]
    assert_boundary(built["boundary"], status="ACTIVE", assigned_cell_count=1)

    refused = api.activate_boundary(
        boundary_id, {}, make_agency_liaison_headers(law["id"])
    )
    validate_error(refused, ApiErrorId.BOUNDARY_INVALID_STATE, 409)

    after = fx.read_boundary(api, boundary_id)
    assert_boundary(after, status="ACTIVE", assigned_cell_count=1)

    assignment = fx.read_cell_assignment(api, assignment_id)
    assert_cell_assignment(assignment, status="ACTIVE", service_type="LAW")

    cell = fx.read_cell(api, world["cell_id"])
    assert_coverage_cell(cell, active_assignment_count=1)

    jurisdiction = fx.read_jurisdiction(api, world["j_id"])
    assert jurisdiction["gap_pair_count"] == 2, (
        "FIRE and EMS remain uncovered on the single cell"
    )
    assert jurisdiction["covered_cell_count"] == 0, (
        "a covered cell needs all three service types"
    )


# ===========================================================================
# initial_state — every machine honours its declared starting status
# ===========================================================================
def test_every_new_record_lands_in_its_declared_initial_state(api):
    """
    The new centerline lands in `DRAFT` status with `qc_dirty` true, `open_discrepancy_case_count` at zero, and both slot counters set to the side's full capacity.
    The new boundary lands in `DRAFT` status with `assigned_cell_count` at zero and `retired_at` and `retire_reason` both null.
    Every emitted defect starts with `status` `OPEN`, and defects are created in a deterministic order: by `defect_code` ascending, then by `entity_type` ascending, then by the subject record's `created_at` ascending.
    The new package lands in `DRAFT` with `package_version` null, `record_count`, `pinned_record_count`, `fresh_pin_count` and `stale_pin_count` all at zero, `drift_detected` false, and `sealed_at`, `published_at`, `sealed_by_user_id`, `published_by_user_id`, `invalidated_reason` and `rollback_reason` all null.
    The new case lands in `OPEN` status with `round_count` at zero, `current_proposal_id` null, and `concurred_by_side`, `resolved_value`, `escalated_at` and `adopted_at` all null.

    Design: Corner/state_machines/new_entities_start_in_declared_initial_states
    """
    world = fx.setup_base_geography(api)
    law = fx.setup_agency(api, world["j_id"], "LAW")
    fire = fx.setup_agency(api, world["j_id"], "FIRE")
    assert_agency(law, status="ACTIVE", agency_type="LAW")
    assert law["suspended_reason"] is None, "a new agency's suspended_reason is null"

    road = fx.setup_road(api, world["j_id"])
    assert_road_centerline(road, status="DRAFT", qc_dirty=True, version=1)

    point = fx.setup_address_point(
        api, road["id"], world["cell_id"], geometry_verified=True
    )
    assert_address_point(point, status="PENDING", confidence_basis="PROVISIONAL")

    boundary = fx.setup_boundary(api, law["id"])
    assert_boundary(boundary, status="DRAFT", assigned_cell_count=0, service_type="LAW")
    assert boundary["retired_at"] is None and boundary["retire_reason"] is None

    assignment = fx.claim_cell(api, boundary["id"], law["id"], world["cell_id"])
    assert_cell_assignment(assignment, status="PENDING", service_type="LAW")

    report = fx.setup_road_scoped_report(api, road["id"])
    assert_qc_report(report, scope="ROAD", status="GENERATED")

    package = fx.setup_package(api, world["j_id"], report["id"], "MAPPING")
    assert_package(
        package,
        status="DRAFT",
        pinned_record_count=0,
        fresh_pin_count=0,
        stale_pin_count=0,
        drift_detected=False,
    )
    assert package["package_version"] is None, "a DRAFT package has a null package_version"

    case = fx.setup_discrepancy_case(api, road["id"], law["id"], fire["id"])
    assert_discrepancy_case(
        case,
        status="OPEN",
        round_count=0,
        subject_type="ROAD_NAME",
        jurisdiction_id=world["j_id"],
        opened_by_agency_id=law["id"],
    )
    assert case["current_proposal_id"] is None
    assert case["concurred_by_side"] is None
    assert case["resolved_value"] is None
    assert case["escalated_at"] is None
    assert case["adopted_at"] is None

    defects = fx.list_defects(api, report["id"])
    assert defects, "the scan of a DRAFT road emits at least one finding"
    for defect in defects:
        assert defect["status"] == "OPEN", (
            f"every emitted defect starts OPEN, got {defect['status']!r} "
            f"on {defect['defect_code']}"
        )


# ===========================================================================
# terminal_state_lockdown — RETIRED refuses both validate and a second retire
# ===========================================================================
def test_a_retired_centerline_refuses_both_validation_and_a_second_retirement(api):
    """
    The centerline moves to `RETIRED`, which is terminal, with `retired_at` stamped at the logical clock instant and `retire_reason` recorded from the payload, and its `version` increments by 1.
    Attempting a transition that the target record's current state does not define — including repeating a transition already performed, since idempotency is *not* granted anywhere in this system, and including any action on a terminal state — yields that entity's invalid-state code with HTTP 409: `ERR_ROAD_INVALID_STATE`, `ERR_ADDRESS_POINT_INVALID_STATE`, `ERR_BOUNDARY_INVALID_STATE`, `ERR_REPORT_INVALID_STATE`, `ERR_DEFECT_INVALID_STATE`, `ERR_PACKAGE_INVALID_STATE` or `ERR_CASE_INVALID_STATE`.

    Design: Corner/state_machines/validate_or_retire_a_retired_road_rejected
    """
    world = fx.setup_geography_without_cells(api)
    road = fx.setup_road(api, world["j_id"])

    retired = validate_success(
        api.retire_road_centerline(
            road["id"],
            {"retire_reason": "Vacated by ordinance 2026-14"},
            ANALYST_HEADERS,
        ),
        200,
    )
    assert_road_centerline(
        retired,
        status="RETIRED",
        retire_reason="Vacated by ordinance 2026-14",
        retired_at="2026-08-01T00:00:00.000Z",
        version=2,
    )

    refused_validate = api.validate_road_centerline(road["id"], {}, ANALYST_HEADERS)
    validate_error(refused_validate, ApiErrorId.ROAD_INVALID_STATE, 409)

    refused_retire = api.retire_road_centerline(
        road["id"], {"retire_reason": "Retiring again"}, ANALYST_HEADERS
    )
    validate_error(refused_retire, ApiErrorId.ROAD_INVALID_STATE, 409)

    after = fx.read_road(api, road["id"])
    assert_road_centerline(
        after,
        status="RETIRED",
        retire_reason="Vacated by ordinance 2026-14",
        retired_at="2026-08-01T00:00:00.000Z",
        version=2,
    )


# ===========================================================================
# invalid_transitions — PATCH is undefined from PUBLISHED
# ===========================================================================
def test_editing_a_published_centerline_is_refused_even_with_the_current_version(api):
    """
    An edit of a `DRAFT` centerline leaves it in `DRAFT` — `DRAFT → DRAFT` is a real transition, not a no-op — while an edit of a `VALIDATED` centerline **demotes** it, `VALIDATED → DRAFT`, because a validated road whose name or ranges have moved must be re-validated before it may be published again.
    Validation is strictly ordered, and the **first** failing check determines the response; later checks are never reported for the same request.

    Design: Corner/state_machines/patch_published_road_rejected
    """
    world = fx.setup_geography_without_cells(api)
    road = fx.setup_road(api, world["j_id"])
    fx.validate_road(api, road["id"])
    published = fx.publish_road(api, road["id"])
    assert_road_centerline(published, status="PUBLISHED", qc_dirty=False, version=3)

    refused = api.patch_road_centerline(
        road["id"],
        {"expected_road_version": published["version"], "primary_name": "N MAPLE AVE"},
        ANALYST_HEADERS,
    )
    # Not 412: the version supplied was the current one, so state legality fires.
    validate_error(refused, ApiErrorId.ROAD_INVALID_STATE, 409)

    after = fx.read_road(api, road["id"])
    assert_road_centerline(
        after,
        status="PUBLISHED",
        primary_name="N MAPLE STREET",
        normalized_name="N MAPLE STREET",
        qc_dirty=False,
        version=3,
    )


# ===========================================================================
# side_effect_execution — retiring a base point sweeps units, frees one slot
# ===========================================================================
def test_retiring_a_base_address_sweeps_its_units_and_frees_exactly_one_slot(api):
    """
    The point moves to `RETIRED` with `retired_at` stamped at the logical clock instant, and `retire_reason` is recorded as `REPLACED` when a successor was supplied and as `ANALYST_RETIRED` when it was not.
    Every point whose `parent_address_point_id` equals the retired point and whose `status` is `PENDING` or `ACTIVE` then transitions to `RETIRED` with `retire_reason` set to `PARENT_RETIRED`.
    The road's slot counters are refreshed — retiring a base address frees exactly one slot, while retiring a unit frees none — and pin staleness is evaluated for every mutated record.

    Design: Corner/state_machines/retire_base_point_cascades_units_and_frees_one_slot
    """
    world = fx.setup_base_geography(api)
    road = fx.setup_road(api, world["j_id"])

    base = fx.setup_address_point(
        api, road["id"], world["cell_id"], geometry_verified=True
    )
    unit_b = fx.setup_unit_point(
        api, road["id"], world["cell_id"], base["id"], unit_id="3B",
        geometry_verified=True,
    )
    unit_c = fx.setup_unit_point(
        api, road["id"], world["cell_id"], base["id"], unit_id="3C",
        geometry_verified=True,
    )

    before = fx.read_road(api, road["id"])
    # Capacity 50 on the left; the base point consumes one, the units none.
    assert_slot_counters(before, 49, 50)

    retired = validate_success(
        api.retire_address_point(
            base["id"], {"retire_reason": "Structure demolished"}, ANALYST_HEADERS
        ),
        200,
    )
    assert_address_point(
        retired,
        status="RETIRED",
        retire_reason="ANALYST_RETIRED",
        unit_child_count=0,
        version=2,
    )
    assert retired["superseded_by_address_point_id"] is None, (
        "no successor was supplied, so the supersession link stays null"
    )

    for unit in (unit_b, unit_c):
        swept = fx.read_point(api, unit["id"])
        assert_address_point(
            swept, status="RETIRED", retire_reason="PARENT_RETIRED", version=2
        )

    after = fx.read_road(api, road["id"])
    assert_slot_counters(after, 50, 50)


# ===========================================================================
# cross_entity — suspension is forward-looking only
# ===========================================================================
def test_suspending_an_agency_leaves_its_active_boundary_serving(api):
    """
    An administrator may suspend an agency, supplying `suspended_reason`; the agency's `status` becomes `SUSPENDED` and its `version` increments by 1.
    A `SUSPENDED` agency retains its existing active boundaries but may not activate new ones and may not be named as a party to a new discrepancy case — either attempt is refused with `ERR_AGENCY_NOT_ACTIVE`.

    Design: Corner/state_machines/agency_suspend_leaves_its_active_boundary_serving
    """
    world = fx.setup_base_geography(api)
    law = fx.setup_agency(api, world["j_id"], "LAW")
    built = fx.setup_active_boundary_on_cell(api, law["id"], world["cell_id"])

    suspended = validate_success(
        api.suspend_agency(
            law["id"], {"suspended_reason": "IGA lapsed pending renewal"}, SYSADMIN_HEADERS
        ),
        200,
    )
    assert_agency(
        suspended,
        status="SUSPENDED",
        suspended_reason="IGA lapsed pending renewal",
    )

    boundary = fx.read_boundary(api, built["boundary_id"])
    assert_boundary(boundary, status="ACTIVE", assigned_cell_count=1)
    assert boundary["retired_at"] is None, (
        "suspension does not retire live coverage"
    )

    assignment = fx.read_cell_assignment(api, built["assignment_id"])
    assert_cell_assignment(assignment, status="ACTIVE")

    cell = fx.read_cell(api, world["cell_id"])
    assert_coverage_cell(cell, active_assignment_count=1)

    jurisdiction = fx.read_jurisdiction(api, world["j_id"])
    assert jurisdiction["gap_pair_count"] == 2, (
        "FIRE and EMS are still the only gaps; LAW keeps answering"
    )
    assert jurisdiction["forward_gap_pair_count"] == 2, (
        "the open-ended LAW claim covers the whole thirty-day horizon"
    )


# ===========================================================================
# valid_transition — the review and utility dimensions are independent
# ===========================================================================
def test_a_gis_rejection_closes_the_request_while_the_utility_hold_stands(api):
    """
    Holding from `PENDING_UTILITY` to `UTILITY_HELD` increments the `version` by 1 and leaves `fulfillment_status` at `OPEN`.
    A rejection moves `review_status` from `PENDING_REVIEW` to `GIS_REJECTED`, increments the `version` by 1, and drives `fulfillment_status` to `CLOSED_REJECTED` **regardless of what `utility_status` holds** — a rejected review closes the request outright, and no later utility action can reopen it.

    Design: Corner/state_machines/gis_reject_closes_request_while_utility_dimension_stays_held
    """
    world = fx.setup_geography_without_cells(api)
    road = fx.setup_road(api, world["j_id"])
    fx.validate_road(api, road["id"])

    request = fx.setup_assignment_request(
        api,
        road["id"],
        permit_number="BP-2026-0200",
        parcel_id="8712300200",
    )
    assert_assignment_request(
        request,
        review_status="PENDING_REVIEW",
        utility_status="PENDING_UTILITY",
        fulfillment_status="OPEN",
        version=1,
    )

    held = validate_success(
        api.utility_clearance_assignment_request(
            request["id"],
            {"decision": "HOLD", "utility_note": "Water tap not yet paid"},
            PERMIT_HEADERS,
        ),
        200,
    )
    assert_assignment_request(
        held,
        review_status="PENDING_REVIEW",
        utility_status="UTILITY_HELD",
        fulfillment_status="OPEN",
        version=2,
    )

    rejected = validate_success(
        api.gis_review_assignment_request(
            request["id"],
            {
                "decision": "REJECT",
                "review_note": "Parcel fronts a private drive, not this centerline",
            },
            ANALYST_HEADERS,
        ),
        200,
    )
    assert_assignment_request(
        rejected,
        review_status="GIS_REJECTED",
        utility_status="UTILITY_HELD",
        fulfillment_status="CLOSED_REJECTED",
        review_note="Parcel fronts a private drive, not this centerline",
        utility_note="Water tap not yet paid",
        minted_point_count=0,
        version=3,
    )
    assert rejected["assigned_address_point_id"] is None, (
        "a rejected request never minted an address"
    )

    after = fx.read_road(api, road["id"])
    assert_slot_counters(after, 50, 50)


# ===========================================================================
# cyclic — three alternating rounds, then the fourth filing escalates
# ===========================================================================
def test_the_fourth_filing_escalates_the_case_and_only_arbitration_resolves_it(api):
    """
    The filing that arrives while `round_count` already **equals** three is still accepted — it is recorded as `round_number` 4 and `round_count` is set accordingly — but instead of continuing the cycle it drives the case to `ESCALATED`, from either `PROPOSAL_PENDING` or `COUNTERED`, stamping `escalated_at` at the logical clock instant and incrementing the case's `version` by 1.
    The case sets `resolved_value` to that `arbitration_value`, stamps `adopted_at` at the logical clock instant, moves `ESCALATED → ARBITRATED`, and increments its `version` by 1; every filed proposal on the case projects to `VOIDED`; and levels 2 through 5 of the adoption cascade then run identically, using the arbitrated value in place of a proposed one.

    Design: Corner/state_machines/escalation_past_round_limit_voids_every_proposal_then_arbitration_resolves
    """
    world = fx.setup_geography_without_cells(api)
    road = fx.setup_road(api, world["j_id"], primary_name="W OAK ST")
    parties = fx.setup_two_agencies(api, world["j_id"])
    opener = parties["opener_id"]
    counterparty = parties["counterparty_id"]

    case = fx.setup_discrepancy_case(
        api,
        road["id"],
        opener,
        counterparty,
        description="Sheriff CAD carries W OAK AVE; fire carries W OAK ST",
    )
    case_id = case["id"]

    p1 = fx.file_proposal(api, case_id, opener, "W OAK AVE", rationale="Round 1, opener")
    assert_discrepancy_proposal(p1, round_number=1, proposed_by_side="OPENER")

    p2 = fx.file_proposal(
        api, case_id, counterparty, "W OAK ST", rationale="Round 2, counterparty"
    )
    assert_discrepancy_proposal(p2, round_number=2, proposed_by_side="COUNTERPARTY")

    p3 = fx.file_proposal(
        api, case_id, opener, "W OAK AVENUE", rationale="Round 3, opener"
    )
    assert_discrepancy_proposal(p3, round_number=3, proposed_by_side="OPENER")

    # The fourth filing is accepted (201), not refused, and it escalates the case.
    fourth_version = fx.read_case(api, case_id)["version"]
    fourth = validate_success(
        api.create_proposal(
            case_id,
            {
                "proposed_value": "W OAK STREET",
                "expected_case_version": fourth_version,
                "rationale": "Round 4, counterparty — breaches the limit",
            },
            make_agency_liaison_headers(counterparty),
        ),
        201,
    )
    assert_discrepancy_proposal(fourth, round_number=4, proposed_by_side="COUNTERPARTY")

    escalated = fx.read_case(api, case_id)
    assert_discrepancy_case(
        escalated,
        status="ESCALATED",
        round_count=4,
        escalated_at="2026-08-01T00:00:00.000Z",
        current_proposal_id=fourth["id"],
    )

    arbitrated = fx.arbitrate(
        api,
        case_id,
        "W OAK BLVD",
        rationale="County adopts the 1998 plat spelling",
    )
    assert_discrepancy_case(
        arbitrated,
        status="ARBITRATED",
        resolved_value="W OAK BLVD",
        version=6,
    )

    rows, meta = validate_paginated(
        api.list_proposals(case_id, {"limit": 100}, ANALYST_HEADERS)
    )
    assert meta["total_count"] == 4, "four filings sit in the append-only log"
    for row in rows:
        assert row["status"] == "VOIDED", (
            f"every filed proposal projects to VOIDED once the case is arbitrated, "
            f"got {row['status']!r} on round {row['round_number']}"
        )

    after = fx.read_road(api, road["id"])
    assert_road_centerline(
        after,
        primary_name="W OAK BLVD",
        normalized_name="W OAK BOULEVARD",
        qc_dirty=True,
        status="DRAFT",
        open_discrepancy_case_count=0,
        version=2,
    )


# ===========================================================================
# invalid_transitions — arbitration is defined only from ESCALATED
# ===========================================================================
def test_arbitrating_a_concurred_case_is_refused(api):
    """
    Adopting a case that is not `CONCURRED`, arbitrating a case that is not `ESCALATED`, and filing a proposal on an already-resolved case are all refused with `ERR_CASE_INVALID_STATE` (HTTP 409).
    Concurrence is available from `PROPOSAL_PENDING` and from `COUNTERED`, and both branches behave identically: the case advances to `CONCURRED`, `concurred_by_side` is set to the acting side (`OPENER` or `COUNTERPARTY`), and the case's `version` increments by 1.

    Design: Corner/state_machines/arbitrate_a_concurred_case_rejected
    """
    world = fx.setup_geography_without_cells(api)
    road = fx.setup_road(api, world["j_id"], primary_name="W OAK ST")
    parties = fx.setup_two_agencies(api, world["j_id"])
    opener = parties["opener_id"]
    counterparty = parties["counterparty_id"]

    case = fx.setup_discrepancy_case(
        api, road["id"], opener, counterparty, description="Name dispute"
    )
    case_id = case["id"]

    proposal = fx.file_proposal(api, case_id, opener, "W OAK AVE")
    concurred = fx.concur(api, case_id, counterparty, proposal["id"])
    assert_discrepancy_case(
        concurred,
        status="CONCURRED",
        concurred_by_side="COUNTERPARTY",
        version=3,
    )

    refused = api.arbitrate_discrepancy_case(
        case_id, {"arbitration_value": "W OAK PL"}, SYSADMIN_HEADERS
    )
    validate_error(refused, ApiErrorId.CASE_INVALID_STATE, 409)

    after = fx.read_case(api, case_id)
    assert_discrepancy_case(
        after,
        status="CONCURRED",
        concurred_by_side="COUNTERPARTY",
        version=3,
    )
    assert after["resolved_value"] is None, "the refused arbitration wrote no value"
    assert after["adopted_at"] is None, "the refused arbitration stamped nothing"

    rows, meta = validate_paginated(
        api.list_proposals(case_id, {"limit": 100}, ANALYST_HEADERS)
    )
    assert meta["total_count"] == 1
    # Not VOIDED: the case never escalated and was never arbitrated.
    assert_discrepancy_proposal(rows[0], round_number=1, status="PENDING")

    unchanged = fx.read_road(api, road["id"])
    assert_road_centerline(
        unchanged,
        primary_name="W OAK ST",
        status="DRAFT",
        version=1,
    )
