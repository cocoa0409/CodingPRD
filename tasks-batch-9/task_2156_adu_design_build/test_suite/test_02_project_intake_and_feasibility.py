"""Opening a project on a parcel and screening it under both feasibility pathways."""
from test_helpers import (
    NON_EXISTENT_UUID, ApiErrorId,
    validate_success, validate_error, validate_paginated,
    assert_adu_project, assert_feasibility_screening,
    adu_project_payload,
    register_jurisdiction, register_property,
    setup_intake_project, setup_intake_project_on_occupied_parcel,
    run_screening, lock_pathway, read_project,
    PLATFORM_ADMIN, DESIGN_LEAD, PLAN_CHECKER,
)


def test_local_ordinance_screening_fails_on_four_checks(api):
    """PRD §3.2: "Under `LOCAL_ORDINANCE`, the requirement set is copied straight off the
    jurisdiction: `max_allowed_sqft` becomes the jurisdiction's `local_max_detached_sqft`,
    `required_rear_setback_ft` becomes its `local_rear_setback_ft`, `required_side_setback_ft`
    becomes its `local_side_setback_ft`, and `required_height_ft` becomes its
    `local_max_height_ft`."
    PRD §3.2: "Whichever checks failed are listed in `deficiency_codes`, drawn from `ZONING`,
    `SETBACK`, `HEIGHT`, and `UTILITY_CAPACITY` and sorted ascending in ASCII order, so
    `HEIGHT` precedes `SETBACK`, which precedes `UTILITY_CAPACITY`, which precedes `ZONING`."
    PRD §3.2: "The `verdict` then follows a strict precedence: if zoning, setback, or height
    failed, the verdict is `FAIL`; otherwise, if only the utility capacity check failed, the
    verdict is `PASS_WITH_CONDITIONS`, because a service upgrade is a solvable problem where
    a zoning violation is not; and if all four checks passed, the verdict is `PASS`."

    Design: Difficulty/dual_variant_calc/feasibility_pathway_verdict_divergence
    """
    ctx = setup_intake_project_on_occupied_parcel(api)

    screening = validate_success(api.create_feasibility_screening(
        ctx["project"]["id"], {"pathway": "LOCAL_ORDINANCE"}, DESIGN_LEAD), 201)

    assert_feasibility_screening(screening)
    assert screening["max_allowed_sqft"] == 750
    assert screening["verdict"] == "FAIL"
    assert screening["deficiency_codes"] == ["HEIGHT", "SETBACK", "UTILITY_CAPACITY", "ZONING"]


def test_statutory_screening_of_the_same_project_passes_with_conditions(api):
    """PRD §3.2: "Under `STATUTORY_MINISTERIAL` the state floor takes over: `max_allowed_sqft`
    becomes whichever is larger of 800 square feet and the jurisdiction's
    `local_max_detached_sqft`, so a restrictive city can never push the ceiling below the
    state's always-allowed area; `required_height_ft` becomes a flat 16.0 feet regardless of
    local rules; and the setbacks become a flat 4.0 feet on both the rear and the side —
    except for a `CONVERSION` or a `JADU`, where converting existing space demands no new
    setback at all and both `required_rear_setback_ft` and `required_side_setback_ft` are 0.0."
    PRD §3.2: "A screening row is immutable: it records the `adu_project_id` it was run
    against and never changes afterwards, which is why the same project can carry a `FAIL`
    under the local ordinance and a `PASS` under the statutory pathway simultaneously."

    Design: Difficulty/dual_variant_calc/feasibility_pathway_verdict_divergence
    """
    ctx = setup_intake_project_on_occupied_parcel(api)
    local = run_screening(api, ctx["project"]["id"], "LOCAL_ORDINANCE")

    statutory = validate_success(api.create_feasibility_screening(
        ctx["project"]["id"], {"pathway": "STATUTORY_MINISTERIAL"}, DESIGN_LEAD), 201)

    assert_feasibility_screening(statutory)
    assert statutory["max_allowed_sqft"] == 800
    assert statutory["required_side_setback_ft"] == 4.0
    assert statutory["required_rear_setback_ft"] == 4.0
    assert statutory["required_height_ft"] == 16.0
    assert statutory["verdict"] == "PASS_WITH_CONDITIONS"
    assert statutory["deficiency_codes"] == ["UTILITY_CAPACITY"]
    assert local["verdict"] == "FAIL", "the earlier local screening is frozen, not rewritten"

    project = read_project(api, ctx["project"]["id"])
    assert project["status"] == "INTAKE"
    assert project["approved_pathway"] is None


def test_screening_listing_can_be_narrowed_by_pathway(api):
    """PRD §3.2: "Screening listings for a project may be narrowed by `pathway`."
    PRD §2.3: "Unless a specific listing states otherwise, collections are returned sorted
    by `created_at` in ascending order, so the oldest row comes first."

    Design: Corner/endpoints/list_feasibility_screenings_filtered_by_pathway
    """
    ctx = setup_intake_project_on_occupied_parcel(api)
    local = run_screening(api, ctx["project"]["id"], "LOCAL_ORDINANCE")
    statutory = run_screening(api, ctx["project"]["id"], "STATUTORY_MINISTERIAL")

    rows, meta = validate_paginated(api.list_feasibility_screenings(
        ctx["project"]["id"], PLAN_CHECKER, {"pathway": "STATUTORY_MINISTERIAL"}))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == statutory["id"]
    assert rows[0]["max_allowed_sqft"] == 800

    everything, all_meta = validate_paginated(
        api.list_feasibility_screenings(ctx["project"]["id"], PLAN_CHECKER))
    assert all_meta["total_count"] == 2
    assert everything[0]["id"] == local["id"], "screenings come back oldest first"
    assert everything[0]["max_allowed_sqft"] == 750


def test_open_project_with_unknown_parcel_reports_property_not_found(api):
    """PRD §2.5: "Foreign keys supplied inside a request body are resolved the same way and
    report the same identifiers. This covers `jurisdiction_id` when registering an inspector
    or a parcel, `property_id` when opening a project, `screening_id` when locking in a
    pathway, `inspector_id` when booking an inspection, `depends_on_phase_id` when adding a
    construction phase behind a predecessor, and `supersedes_change_order_id` when a change
    order replaces an earlier one."
    PRD §2.7: "4. **Body foreign-key existence.** Every foreign key inside the request body,
    per §2.5."

    Design: Corner/entities/create_adu_project_with_unknown_property_returns_property_not_found
    """
    register_jurisdiction(api)

    response = api.create_adu_project(
        adu_project_payload(NON_EXISTENT_UUID, 1), DESIGN_LEAD)

    error = validate_error(response, ApiErrorId.ERR_PROPERTY_NOT_FOUND)
    assert error["error_id"] != ApiErrorId.ERR_STALE_PROPERTY_VERSION.value, (
        "body foreign keys resolve before the optimistic-concurrency guard")


def test_open_project_with_unknown_unit_type_is_rejected(api):
    """PRD §3.2: "The design itself is described at intake: `unit_type` is one of
    `DETACHED_NEW`, `ATTACHED`, `CONVERSION`, or `JADU`; `proposed_sqft` is the conditioned
    floor area; `proposed_height_ft` is the ridge height above grade; `rear_setback_ft` and
    `side_setback_ft` are the proposed setbacks, each zero or more; `bedrooms` counts the
    sleeping rooms; and `contract_base_price_cents` is the signed design-build price before
    any change order, which must be strictly greater than zero."
    PRD §2.7: "**Request shape.** Required fields present and correctly typed; enum-typed fields
    carrying a member of their declared set; numeric, range, and format constraints satisfied;
    pagination bounds satisfied on list endpoints. Every failure here is `ERR_VALIDATION`
    (HTTP 422)."

    Design: Corner/entities/create_adu_project_unit_type_invalid_enum_rejected
    """
    jurisdiction = register_jurisdiction(api)
    parcel = register_property(api, jurisdiction["id"])

    validate_error(
        api.create_adu_project(
            adu_project_payload(parcel["id"], parcel["version"], unit_type="GARAGE_LOFT"),
            DESIGN_LEAD),
        ApiErrorId.ERR_VALIDATION)

    unchanged = validate_success(api.get_property(parcel["id"], DESIGN_LEAD))
    assert unchanged["version"] == 1, "a rejected create must not mutate the parcel"


def test_second_project_create_with_a_stale_parcel_version_is_rejected(api):
    """PRD §2.6: "Opening an ADU project on a parcel — `POST /adu-projects` — requires
    `expected_property_version`, carrying the client's last observed `version` of that
    `Property`."
    PRD §2.6: "If the supplied value differs from the parcel's current `version`, the request
    is rejected with `ERR_STALE_PROPERTY_VERSION` and HTTP 412, and nothing is created."
    PRD §3.2: "Opening the project also counts as a mutation of the parcel, so the parcel's
    `version` rises by 1."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_property_version_on_project_create
    """
    jurisdiction = register_jurisdiction(api)
    parcel = register_property(api, jurisdiction["id"])
    stale_version = parcel["version"]

    first = validate_success(
        api.create_adu_project(adu_project_payload(parcel["id"], stale_version), DESIGN_LEAD), 201)
    assert_adu_project(first)
    assert validate_success(api.get_property(parcel["id"], DESIGN_LEAD))["version"] == 2

    validate_error(
        api.create_adu_project(
            adu_project_payload(parcel["id"], stale_version, unit_type="CONVERSION",
                                proposed_sqft=500, proposed_height_ft=12.0,
                                rear_setback_ft=4.0, side_setback_ft=4.0, bedrooms=1,
                                contract_base_price_cents=15_000_000),
            DESIGN_LEAD),
        ApiErrorId.ERR_STALE_PROPERTY_VERSION)

    rows, meta = validate_paginated(
        api.list_adu_projects(PLATFORM_ADMIN, {"property_id": parcel["id"]}))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]
    assert validate_success(api.get_property(parcel["id"], DESIGN_LEAD))["version"] == 2


def test_selecting_a_pathway_twice_is_rejected(api):
    """PRD §3.2: "Locking the project onto a pathway is what clears it out of intake,
    advancing `status` from `INTAKE` to `FEASIBILITY_CLEARED`."
    PRD §3.2: "The project must still be in `INTAKE`; a second attempt to select a pathway
    on a project that has already left intake is rejected with `ERR_PROJECT_PHASE_INVALID`
    (HTTP 409)."

    Design: Corner/state_machines/select_pathway_twice_returns_project_phase_invalid
    """
    ctx = setup_intake_project(api)
    first_screening = run_screening(api, ctx["project"]["id"], "LOCAL_ORDINANCE")
    lock_pathway(api, ctx["project"]["id"], first_screening["id"])
    second_screening = run_screening(api, ctx["project"]["id"], "STATUTORY_MINISTERIAL")

    validate_error(
        api.select_pathway(ctx["project"]["id"], {"screening_id": second_screening["id"]},
                           DESIGN_LEAD),
        ApiErrorId.ERR_PROJECT_PHASE_INVALID)

    project = read_project(api, ctx["project"]["id"])
    assert project["approved_pathway"] == "LOCAL_ORDINANCE"
    assert project["status"] == "FEASIBILITY_CLEARED"


def test_adopting_a_failed_screening_is_rejected(api):
    """PRD §3.2: "And the screening's `verdict` must be either `PASS` or
    `PASS_WITH_CONDITIONS` — adopting a `FAIL` screening is rejected with
    `ERR_FEASIBILITY_FAILED` (HTTP 409)."
    PRD §3.2: "The new project opens with `status` `INTAKE`, `financing_state` `UNFUNDED`,
    and `approved_pathway` null, with `max_allowed_sqft`, `approved_change_days`,
    `approved_change_order_count`, and `total_permit_fee_cents` all at 0, and with
    `contract_price_current_cents` seeded equal to `contract_base_price_cents`."

    Design: Corner/validations/select_pathway_with_failed_screening_returns_feasibility_failed
    """
    ctx = setup_intake_project_on_occupied_parcel(api)
    screening = run_screening(api, ctx["project"]["id"], "LOCAL_ORDINANCE")
    assert screening["verdict"] == "FAIL"

    validate_error(
        api.select_pathway(ctx["project"]["id"], {"screening_id": screening["id"]}, DESIGN_LEAD),
        ApiErrorId.ERR_FEASIBILITY_FAILED)

    project = read_project(api, ctx["project"]["id"])
    assert project["approved_pathway"] is None
    assert project["status"] == "INTAKE"
    assert project["max_allowed_sqft"] == 0
