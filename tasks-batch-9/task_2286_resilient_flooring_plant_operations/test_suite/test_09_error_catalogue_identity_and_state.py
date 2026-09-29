"""Identity, existence and own-entity-state error paths of the plant API.

These tests exercise the first, third, fourth, fifth and seventh validation
bands of PRD §2.5: the two identity headers of §2.1, the dedicated claim-date
refusal of §3.9, the per-collection not-found codes reached through a path
segment and through a body foreign key, and the lifecycle refusals each entity
raises on its own state — recipes (§3.1), design grants and print films (§3.2),
laboratory panels (§3.4), QC dispositions and stock holds (§3.7) and warranty
claims (§3.9). One cross-entity refusal is covered too: a hold release blocked
by the producing run's QC disposition (§3.7).
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    PLANT_ADMIN,
    PRODUCTION_PLANNER,
    QA_TECHNICIAN,
    QA_TECHNICIAN_B,
    TECHNICAL_DIRECTOR,
    USER_IDS,
    WARRANTY_ADJUSTER,
    WARRANTY_ADJUSTER_B,
    ApiErrorId,
    FORMULATOR,
    adjudication_payload,
    allocation_payload,
    assert_version_unchanged,
    batch_of_run,
    begin_testing,
    build_draft_formulation,
    build_provisional_sku,
    build_released_sku,
    build_sku,
    build_stock_batch,
    component_payload,
    create_distributor,
    create_license,
    create_panel,
    create_press_line,
    create_print_film,
    create_raw_material,
    create_run,
    formulation_payload,
    hold_status_payload,
    license_amendment_payload,
    press_line_payload,
    print_film_payload,
    print_film_status_payload,
    production_run_payload,
    qc_disposition_payload,
    record_result,
    run_to_completion,
    set_clock,
    set_film_status,
    set_license_status,
    set_qc_disposition,
    setup_run,
    start_panel,
    start_run,
    submit_formulation,
    test_result_payload as measurement_payload,
    validate_error,
    validate_paginated,
    validate_success,
    void_panel_payload,
    warranty_claim_payload,
)


def test_absent_or_undeclared_identity_headers_are_unauthenticated(api):
    """Missing headers and a role outside the declared seven all return ERR_UNAUTHENTICATED, never a 403 or a 404.

    "Every request — without exception, including reads — must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user is acting."
    "If either header is absent or empty, or if `X-User-Role` is not one of the seven role names defined below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    "The seven roles are `PlantAdmin`, `Formulator`, `TechnicalDirector`, `QaTechnician`, `ProductionPlanner`, `WarrantyAdjuster` and `Distributor`."
    "Because a single request often breaks several rules at once, the server evaluates validations in a strict ascending order of fifteen bands and **stops at the first violation**; no later band is evaluated, and the response carries only that first rule's error."

    Design: Corner/errors/unauthenticated_requests_missing_headers_or_bad_role_are_rejected
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    unauthenticated_headers = [
        {},
        {"X-User-ID": USER_IDS["plant_admin"]},
        {"X-User-ID": USER_IDS["plant_admin"], "X-User-Role": "Machinist"},
    ]
    for headers in unauthenticated_headers:
        validate_error(
            api.list_press_lines(headers), ApiErrorId.UNAUTHENTICATED.value
        )

    # The same undeclared role on a write is authentication, not authorization,
    # and the write must leave nothing behind.
    validate_error(
        api.create_press_line(
            press_line_payload(line_code="PL-Z"),
            {"X-User-ID": USER_IDS["plant_admin"], "X-User-Role": "Machinist"},
        ),
        ApiErrorId.UNAUTHENTICATED.value,
    )

    _, meta = validate_paginated(api.list_press_lines(PLANT_ADMIN))
    assert meta["total_count"] == 0, "the rejected POST must not have created a line"


def test_claim_reported_before_installed_returns_claim_dates_invalid(api):
    """A reported_on strictly earlier than installed_on is its own 400, and equality is accepted.

    "It carries a `claim_code` unique across claims, the `batch_id` the flooring came from, the `distributor_id` filing it, a `claim_type` naming the failure mode, a `claimed_area_sqm` greater than zero at two decimal places, an `installed_on` date, a `reported_on` date that may not precede it, and an optional `installed_by_certified_installer` flag defaulting to false."
    "A `reported_on` earlier than `installed_on` is refused with `ERR_CLAIM_DATES_INVALID` (HTTP 400)."

    Design: Corner/errors/claim_reported_before_installed_returns_claim_dates_invalid
    """
    built = build_stock_batch(api)
    distributor = create_distributor(api)
    batch_id = built["batch"]["id"]

    inverted = warranty_claim_payload(
        batch_id,
        distributor["id"],
        claim_code="WC-BAD-DATES",
        claim_type="DELAMINATION",
        claimed_area_sqm=10.00,
        installed_on="2026-08-05T00:00:00Z",
        reported_on="2026-08-04T00:00:00Z",
    )
    validate_error(
        api.create_warranty_claim(inverted, WARRANTY_ADJUSTER),
        ApiErrorId.CLAIM_DATES_INVALID.value,
    )

    _, meta = validate_paginated(
        api.list_warranty_claims(WARRANTY_ADJUSTER, params={"batch_id": batch_id})
    )
    assert meta["total_count"] == 0, "the refused claim must not have been stored"

    same_day = dict(inverted, reported_on="2026-08-05T00:00:00Z")
    accepted = validate_success(
        api.create_warranty_claim(same_day, WARRANTY_ADJUSTER), 201
    )
    assert accepted["status"] == "SUBMITTED"


def test_unknown_path_id_returns_that_collections_own_not_found_code(api):
    """One unused UUID addressed at every collection produces that collection's own 404 code.

    "Path resource existence — the `{id}` (or `{component_id}`) segment must address an existing row of the collection named by its own segment; otherwise the not-found code for that entity is returned with HTTP 404. The twelve codes are `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_RAW_MATERIAL_NOT_FOUND`, `ERR_FORMULATION_NOT_FOUND`, `ERR_FORMULATION_COMPONENT_NOT_FOUND`, `ERR_DESIGN_LICENSE_NOT_FOUND`, `ERR_PRINT_FILM_NOT_FOUND`, `ERR_PRODUCT_SKU_NOT_FOUND`, `ERR_PRESS_LINE_NOT_FOUND`, `ERR_TEST_PANEL_NOT_FOUND`, `ERR_PRODUCTION_RUN_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND` and `ERR_WARRANTY_CLAIM_NOT_FOUND`."
    "Only then is a second path segment — the `component_id` of a recipe component, written `{component_id}` in a path — resolved, and a component identifier that exists but belongs to a different recipe is treated exactly like one that does not exist at all: `ERR_FORMULATION_COMPONENT_NOT_FOUND` with HTTP 404."

    Design: Corner/errors/every_path_id_not_found_code_is_reachable_from_one_unknown_uuid
    """
    built = build_draft_formulation(api)
    formulation_id = built["formulation"]["id"]

    cases = [
        (
            lambda: api.get_distributor(NON_EXISTENT_UUID, PLANT_ADMIN),
            ApiErrorId.DISTRIBUTOR_NOT_FOUND.value,
        ),
        (
            lambda: api.get_raw_material(NON_EXISTENT_UUID, PLANT_ADMIN),
            ApiErrorId.RAW_MATERIAL_NOT_FOUND.value,
        ),
        (
            lambda: api.get_formulation(NON_EXISTENT_UUID, PLANT_ADMIN),
            ApiErrorId.FORMULATION_NOT_FOUND.value,
        ),
        (
            lambda: api.delete_formulation_component(
                formulation_id, NON_EXISTENT_UUID, FORMULATOR
            ),
            ApiErrorId.FORMULATION_COMPONENT_NOT_FOUND.value,
        ),
        (
            lambda: api.get_design_license(NON_EXISTENT_UUID, PLANT_ADMIN),
            ApiErrorId.DESIGN_LICENSE_NOT_FOUND.value,
        ),
        (
            lambda: api.get_print_film(NON_EXISTENT_UUID, PLANT_ADMIN),
            ApiErrorId.PRINT_FILM_NOT_FOUND.value,
        ),
        (
            lambda: api.get_product_sku(NON_EXISTENT_UUID, PLANT_ADMIN),
            ApiErrorId.PRODUCT_SKU_NOT_FOUND.value,
        ),
        (
            lambda: api.get_press_line(NON_EXISTENT_UUID, PLANT_ADMIN),
            ApiErrorId.PRESS_LINE_NOT_FOUND.value,
        ),
        (
            lambda: api.get_test_panel(NON_EXISTENT_UUID, PLANT_ADMIN),
            ApiErrorId.TEST_PANEL_NOT_FOUND.value,
        ),
        (
            lambda: api.get_production_run(NON_EXISTENT_UUID, PLANT_ADMIN),
            ApiErrorId.PRODUCTION_RUN_NOT_FOUND.value,
        ),
        (
            lambda: api.get_batch(NON_EXISTENT_UUID, PLANT_ADMIN),
            ApiErrorId.BATCH_NOT_FOUND.value,
        ),
        (
            lambda: api.get_allocation(NON_EXISTENT_UUID, PLANT_ADMIN),
            ApiErrorId.ALLOCATION_NOT_FOUND.value,
        ),
        (
            lambda: api.get_warranty_claim(NON_EXISTENT_UUID, PLANT_ADMIN),
            ApiErrorId.WARRANTY_CLAIM_NOT_FOUND.value,
        ),
    ]
    for make_request, expected_error_id in cases:
        validate_error(make_request(), expected_error_id)

    _, meta = validate_paginated(
        api.list_formulation_components(formulation_id, FORMULATOR)
    )
    assert meta["total_count"] == 2, (
        "the unknown component_id must have left the recipe's real components alone"
    )


def test_unknown_body_foreign_key_returns_not_found_not_invalid_request(api):
    """A dangling foreign key in the body is the referenced collection's 404, ahead of any state or producibility rule.

    "Body reference existence — every foreign key in the body must address an existing row, or that entity's not-found code from the list above is returned with HTTP 404: `formulation_id` and `supersedes_formulation_id` against recipes, `raw_material_id` against materials, `license_id` and `supersedes_license_id` against design grants, `print_film_id` against films, `sku_id` against SKUs, `press_line_id` against lines, `distributor_id` against distributors, `batch_id` against batches, and `production_run_id` against runs."
    "Because a single request often breaks several rules at once, the server evaluates validations in a strict ascending order of fifteen bands and **stops at the first violation**; no later band is evaluated, and the response carries only that first rule's error."

    Design: Corner/errors/unknown_body_foreign_keys_return_not_found_not_invalid_request
    """
    built = build_sku(api)
    press_line = create_press_line(api)
    distributor = create_distributor(api)
    formulation_id = built["formulation"]["id"]
    sku_id = built["sku"]["id"]

    cases = [
        (
            lambda: api.add_formulation_component(
                formulation_id,
                component_payload(NON_EXISTENT_UUID, 10.00),
                FORMULATOR,
            ),
            ApiErrorId.RAW_MATERIAL_NOT_FOUND.value,
        ),
        (
            lambda: api.create_formulation(
                formulation_payload(
                    "F-ORPHAN", supersedes_formulation_id=NON_EXISTENT_UUID
                ),
                FORMULATOR,
            ),
            ApiErrorId.FORMULATION_NOT_FOUND.value,
        ),
        (
            lambda: api.create_print_film(
                print_film_payload(NON_EXISTENT_UUID, design_code="PF-ORPHAN"),
                PLANT_ADMIN,
            ),
            ApiErrorId.DESIGN_LICENSE_NOT_FOUND.value,
        ),
        (
            lambda: api.create_production_run(
                production_run_payload(
                    NON_EXISTENT_UUID,
                    press_line["id"],
                    run_code="RUN-ORPHAN-1",
                    planned_end_utc="2026-08-01T02:00:00Z",
                    planned_quantity_sqm=10.00,
                ),
                PRODUCTION_PLANNER,
            ),
            ApiErrorId.PRODUCT_SKU_NOT_FOUND.value,
        ),
        (
            lambda: api.create_production_run(
                production_run_payload(
                    sku_id,
                    NON_EXISTENT_UUID,
                    run_code="RUN-ORPHAN-2",
                    planned_end_utc="2026-08-01T02:00:00Z",
                    planned_quantity_sqm=10.00,
                ),
                PRODUCTION_PLANNER,
            ),
            ApiErrorId.PRESS_LINE_NOT_FOUND.value,
        ),
        (
            lambda: api.create_allocation(
                allocation_payload(
                    NON_EXISTENT_UUID,
                    sku_id,
                    allocation_code="ALLOC-ORPHAN",
                    requested_quantity_sqm=10.00,
                ),
                PLANT_ADMIN,
            ),
            ApiErrorId.DISTRIBUTOR_NOT_FOUND.value,
        ),
        (
            lambda: api.create_warranty_claim(
                warranty_claim_payload(
                    NON_EXISTENT_UUID,
                    distributor["id"],
                    claim_code="WC-ORPHAN",
                    claim_type="DELAMINATION",
                    claimed_area_sqm=10.00,
                    installed_on="2026-08-05T00:00:00Z",
                    reported_on="2027-08-05T00:00:00Z",
                ),
                WARRANTY_ADJUSTER,
            ),
            ApiErrorId.BATCH_NOT_FOUND.value,
        ),
    ]
    for make_request, expected_error_id in cases:
        validate_error(make_request(), expected_error_id)

    # None of the seven rejected calls may have written a row.
    _, formulations_meta = validate_paginated(api.list_formulations(PLANT_ADMIN))
    assert formulations_meta["total_count"] == 1
    _, films_meta = validate_paginated(api.list_print_films(PLANT_ADMIN))
    assert films_meta["total_count"] == 1
    _, runs_meta = validate_paginated(api.list_production_runs(PLANT_ADMIN))
    assert runs_meta["total_count"] == 0
    _, allocations_meta = validate_paginated(api.list_allocations(PLANT_ADMIN))
    assert allocations_meta["total_count"] == 0
    _, claims_meta = validate_paginated(api.list_warranty_claims(PLANT_ADMIN))
    assert claims_meta["total_count"] == 0


def test_second_submit_or_edit_on_a_recipe_under_review_is_refused(api):
    """A recipe already UNDER_REVIEW refuses both a repeated submit and a component edit on its own state.

    "Submission is the `Formulator`'s hand-off. It is permitted only from `DRAFT`, taking the recipe `DRAFT → UNDER_REVIEW`, and it stamps `submitted_by_user_id` with the acting user."
    "Adding a component is permitted while the recipe is `DRAFT` or `REJECTED`; from any other state the attempt is `ERR_INVALID_FORMULATION_STATE` (HTTP 409)."
    "Own-entity state — the addressed row's own lifecycle state must admit the requested transition."

    Design: Corner/errors/second_submit_on_a_recipe_under_review_returns_invalid_formulation_state
    """
    built = build_draft_formulation(api)
    formulation_id = built["formulation"]["id"]
    filler = create_raw_material(api, "RM-FILLER")
    submit_formulation(api, formulation_id)

    validate_error(
        api.submit_formulation(formulation_id, FORMULATOR),
        ApiErrorId.INVALID_FORMULATION_STATE.value,
    )
    validate_error(
        api.add_formulation_component(
            formulation_id, component_payload(filler["id"], 10.00), FORMULATOR
        ),
        ApiErrorId.INVALID_FORMULATION_STATE.value,
    )

    recipe = validate_success(api.get_formulation(formulation_id, FORMULATOR))
    assert recipe["status"] == "UNDER_REVIEW"
    _, meta = validate_paginated(
        api.list_formulation_components(formulation_id, FORMULATOR)
    )
    assert meta["total_count"] == 2, "the refused edit must not have been applied"


def test_amendment_on_a_suspended_grant_returns_invalid_license_state(api):
    """Amending a SUSPENDED grant fails on the grant's own lifecycle, not on the referential fitness code.

    "A `TechnicalDirector` supplies the successor's `license_code` and `term_volume_cap_sqm`, optionally a new `valid_until`, a new `royalty_rate_bps` and an `amendment_note` recording the rationale. The grant being amended must be `ACTIVE`."
    "Amending a design grant, in particular, is deliberately not version-guarded, because the amended grant leaves `ACTIVE` as part of the amendment, so a second amendment is already refused on state grounds."
    "Own-entity state — the addressed row's own lifecycle state must admit the requested transition."
    "Business referential — rules about the fitness of a referenced row rather than merely its existence."
    "On success a successor grant is created `ACTIVE` with `supersedes_license_id` pointing at the amended one, carrying `reserved_volume_sqm`, `consumed_volume_sqm` and `accrued_royalty_cents` across unchanged; every film of the amended grant is repointed at the successor and has its `version` advanced; and the amended grant moves `ACTIVE → SUPERSEDED`."

    Design: Corner/errors/amendment_on_a_suspended_grant_returns_invalid_license_state
    """
    grant = create_license(api)
    suspended = set_license_status(api, grant["id"], "SUSPENDED")
    assert suspended["status"] == "SUSPENDED"

    validate_error(
        api.create_license_amendment(
            grant["id"],
            license_amendment_payload(
                "LIC-OAK-A1", 3000.00, amendment_note="Cap uplift"
            ),
            TECHNICAL_DIRECTOR,
        ),
        ApiErrorId.INVALID_LICENSE_STATE.value,
    )

    _, meta = validate_paginated(
        api.list_design_licenses(
            PLANT_ADMIN, params={"supersedes_license_id": grant["id"]}
        )
    )
    assert meta["total_count"] == 0, "no successor grant may have been created"
    unchanged = validate_success(api.get_design_license(grant["id"], PLANT_ADMIN))
    assert unchanged["status"] == "SUSPENDED", (
        "the refused amendment must not have superseded the grant"
    )


def test_results_and_restart_on_a_voided_panel_return_invalid_panel_state(api):
    """A VOIDED panel accepts neither a further measurement nor a restart, and the void leaves the SKU in TESTING.

    "Recording a measurement is permitted only while the panel is `IN_TEST`, and the operation names a `test_type` and a `measured_value` of at least zero with at most four decimal places."
    "Starting a panel takes it `SCHEDULED → IN_TEST` or `RETEST_REQUIRED → IN_TEST`; the states `PASSED`, `FAILED` and `VOIDED` accept nothing, and a start from any of them is `ERR_INVALID_PANEL_STATE` (HTTP 409)."
    "Voiding a panel is available from `SCHEDULED`, `IN_TEST` or `RETEST_REQUIRED` and requires a `void_reason`."
    "Two of those resolutions reach the SKU."
    "Own-entity state — the addressed row's own lifecycle state must admit the requested transition."

    Design: Corner/errors/results_posted_to_a_voided_panel_return_invalid_panel_state
    """
    built = build_sku(api)
    sku_id = built["sku"]["id"]
    begin_testing(api, sku_id)
    panel = create_panel(api, sku_id)
    start_panel(api, panel["id"])
    record_result(api, panel["id"], "RESIDUAL_INDENTATION", 0.0800)

    voided = validate_success(
        api.void_test_panel(panel["id"], void_panel_payload(), QA_TECHNICIAN)
    )
    assert voided["status"] == "VOIDED"

    validate_error(
        api.record_test_result(
            panel["id"],
            measurement_payload("DIMENSIONAL_STABILITY_HEAT", 0.2000),
            QA_TECHNICIAN,
        ),
        ApiErrorId.INVALID_PANEL_STATE.value,
    )
    validate_error(
        api.start_test_panel(panel["id"], QA_TECHNICIAN),
        ApiErrorId.INVALID_PANEL_STATE.value,
    )

    sku = validate_success(api.get_product_sku(sku_id, PLANT_ADMIN))
    assert sku["certification_status"] == "TESTING", (
        "voiding a panel neither passes nor fails the SKU"
    )


def test_qc_disposition_on_a_running_run_returns_invalid_qc_transition(api):
    """A run still RUNNING refuses every QC disposition on the run's execution state, not on the gates.

    "Quality disposition is a `QaTechnician` decision expressed as a `to_disposition`, with an optional `hold_reason`. It requires the run's `run_status` to be `COMPLETED`; a disposition against a run in any other execution state, or a `to_disposition` not reachable from the run's current `qc_disposition`, is `ERR_INVALID_QC_TRANSITION` (HTTP 409)."
    "Fourth, provided `actual_quantity_sqm` is strictly greater than zero, exactly one batch is minted."

    Design: Corner/errors/qc_disposition_on_a_running_job_returns_invalid_qc_transition
    """
    built = build_provisional_sku(api)
    press_line = create_press_line(api)
    run = create_run(api, built["sku"]["id"], press_line["id"])
    setup_run(api, run["id"])
    running = start_run(api, run["id"])
    assert running["run_status"] == "RUNNING"

    for to_disposition in ("RELEASED", "QUARANTINED"):
        validate_error(
            api.set_run_qc_disposition(
                run["id"], qc_disposition_payload(to_disposition), QA_TECHNICIAN_B
            ),
            ApiErrorId.INVALID_QC_TRANSITION.value,
        )

    unchanged = validate_success(api.get_production_run(run["id"], PLANT_ADMIN))
    assert unchanged["run_status"] == "RUNNING"
    assert unchanged["qc_disposition"] == "PENDING"
    _, meta = validate_paginated(
        api.list_batches(QA_TECHNICIAN, params={"production_run_id": run["id"]})
    )
    assert meta["total_count"] == 0, "an incomplete run has minted no batch"


def test_release_hold_on_an_in_stock_batch_returns_invalid_batch_state(api):
    """RELEASE_HOLD against stock that was never held is the batch's own-state 409, not an idempotent success.

    "Stock holds are the `QaTechnician`'s direct control over finished inventory, driven by an `action` of `HOLD`, `RELEASE_HOLD` or `SCRAP` with an optional `hold_reason`. Holding requires the batch to be `IN_STOCK`, releasing requires it to be `HELD`, and scrapping requires any non-`SCRAPPED` batch; a mismatch is `ERR_INVALID_BATCH_STATE` (HTTP 409)."
    "Releasing moves the run's batch `IN_PRODUCTION → IN_STOCK` (or `HELD → IN_STOCK` when the batch was quarantined earlier) and sets `available_quantity_sqm` to the full `quantity_sqm`."
    "Most resources additionally carry `updated_at`, in the same format, refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row — including mutations the caller did not directly request, such as a cascade reaching the row from a neighbouring entity."

    Design: Corner/errors/release_hold_on_an_in_stock_batch_returns_invalid_batch_state
    """
    built = build_stock_batch(api)
    before = validate_success(api.get_batch(built["batch"]["id"], QA_TECHNICIAN))
    assert before["status"] == "IN_STOCK"
    assert before["available_quantity_sqm"] == 1200.00

    validate_error(
        api.set_batch_hold_status(
            before["id"], hold_status_payload("RELEASE_HOLD"), QA_TECHNICIAN
        ),
        ApiErrorId.INVALID_BATCH_STATE.value,
    )

    after = validate_success(api.get_batch(before["id"], QA_TECHNICIAN))
    assert after["status"] == "IN_STOCK"
    assert after["available_quantity_sqm"] == 1200.00
    assert_version_unchanged(before, after)


def test_withdrawn_film_and_repeated_available_return_invalid_print_film_state(api):
    """A WITHDRAWN film and an AVAILABLE → AVAILABLE self-loop are both refused with the film's own state code.

    "`AVAILABLE → RESTRICTED` and `RESTRICTED → AVAILABLE` are both declared, `WITHDRAWN` is terminal and reachable from either `AVAILABLE` or `RESTRICTED`, and no self-transition is declared — asking for the state the film is already in is `ERR_INVALID_PRINT_FILM_STATE` (HTTP 409), as is any request against a `WITHDRAWN` film."
    "Returning a film to `AVAILABLE` additionally requires its grant to be `ACTIVE`, and a request to do so while the grant is not `ACTIVE` also returns `ERR_INVALID_PRINT_FILM_STATE`."
    "A new grant is `ACTIVE` with `reserved_volume_sqm`, `consumed_volume_sqm` and `accrued_royalty_cents` all zero, and with `supersedes_license_id` and `amendment_note` null."

    Design: Corner/errors/withdrawn_film_and_repeated_available_return_invalid_print_film_state
    """
    grant = create_license(api)
    withdrawn_film = create_print_film(api, grant["id"])
    available_film = create_print_film(
        api,
        grant["id"],
        design_code="PF-SLATE-900B",
        pattern_repeat_mm_length=900,
        pattern_repeat_mm_width=150,
        registration_tolerance_mm=0.30,
        emboss_plate_code="EP-SLATE-B",
        emboss_alignment_offset_mm=0.05,
    )
    withdrawn = set_film_status(api, withdrawn_film["id"], "WITHDRAWN")
    assert withdrawn["status"] == "WITHDRAWN"

    validate_error(
        api.set_print_film_status(
            withdrawn_film["id"], print_film_status_payload("AVAILABLE"), PLANT_ADMIN
        ),
        ApiErrorId.INVALID_PRINT_FILM_STATE.value,
    )
    validate_error(
        api.set_print_film_status(
            available_film["id"], print_film_status_payload("AVAILABLE"), PLANT_ADMIN
        ),
        ApiErrorId.INVALID_PRINT_FILM_STATE.value,
    )

    governing = validate_success(api.get_design_license(grant["id"], PLANT_ADMIN))
    assert governing["status"] == "ACTIVE", (
        "neither refusal may be blamed on the governing grant"
    )
    still_available = validate_success(
        api.get_print_film(available_film["id"], PLANT_ADMIN)
    )
    assert still_available["status"] == "AVAILABLE"


def test_adjudicating_an_untriaged_claim_returns_invalid_claim_state(api):
    """A claim still SUBMITTED refuses adjudication on its own lifecycle, never on the empty review set.

    "New claims are `SUBMITTED` with `required_reviews`, both review outcomes, `assigned_adjuster_user_id`, `elapsed_months`, `settlement_variant`, `replacement_value_cents`, `labor_allowance_cents`, `settlement_amount_cents` and `denial_reason` all unset."
    "Adjudication is the final decision, expressed as a `decision` of approve or deny with an optional `denial_reason` recorded on a denial. The claim must be `ADJUDICATION_READY`, and the acting adjuster may not be the one who triaged it (§2.8)."
    "An approval takes it `ADJUDICATION_READY → APPROVED` and requires two further things: every required review outcome must be `DEFECT_CONFIRMED`, and any arm answered `NO_DEFECT` or `INCONCLUSIVE` makes the approval `ERR_REVIEW_OUTCOME_CONFLICT` (HTTP 409); and the warranty coverage must not be exhausted."
    "Own-entity state — the addressed row's own lifecycle state must admit the requested transition."

    Design: Corner/errors/adjudicating_an_untriaged_claim_returns_invalid_claim_state
    """
    built = build_stock_batch(api)
    distributor = create_distributor(api)
    set_clock(api, "2029-08-05T00:00:00Z")
    claim = validate_success(
        api.create_warranty_claim(
            warranty_claim_payload(
                built["batch"]["id"],
                distributor["id"],
                claim_code="WC-RAW",
                claim_type="DELAMINATION",
            ),
            WARRANTY_ADJUSTER,
        ),
        201,
    )
    assert claim["status"] == "SUBMITTED"
    assert claim["required_reviews"] is None, "required_reviews is only set at triage"

    validate_error(
        api.adjudicate_warranty_claim(
            claim["id"], adjudication_payload("APPROVE"), WARRANTY_ADJUSTER_B
        ),
        ApiErrorId.INVALID_CLAIM_STATE.value,
    )

    after = validate_success(api.get_warranty_claim(claim["id"], WARRANTY_ADJUSTER))
    assert after["status"] == "SUBMITTED"
    assert after["settlement_amount_cents"] is None


def test_release_hold_while_the_run_is_quarantined_returns_run_not_released(api):
    """A genuinely HELD batch asked to be released by a different technician still fails on the producing run's QC disposition.

    "`PENDING → QUARANTINED` moves the batch `IN_PRODUCTION → HELD` with `hold_reason` `QC_QUARANTINE` and `held_by_user_id` set to the acting technician — which, by §2.8, means someone else must later release it."
    "`HELD → IN_STOCK` closes the `IN_STOCK → HELD → IN_STOCK` cycle and carries three preconditions beyond the state check."
    "The producing run's `qc_disposition` must be `RELEASED`, or the release is `ERR_RUN_NOT_RELEASED` (HTTP 409)."
    "Releasing a batch hold is refused when `X-User-ID` equals the batch's `held_by_user_id`."
    "When a run completes with positive output, the batch is minted with a `batch_code` formed as the producing run's `run_code` followed by the suffix `-B1`, a `production_run_id` pointing at that run, a `sku_id` denormalised from it for stock selection, a `quantity_sqm` equal to the run's `actual_quantity_sqm` that never changes thereafter, an `available_quantity_sqm` of 0, and a `wear_layer_measured_mil` copied from the run's measurement — the reading that will later serve as warranty defect evidence."

    Design: Corner/errors/release_hold_while_the_run_is_quarantined_returns_run_not_released
    """
    built = build_released_sku(api)
    press_line = create_press_line(api)
    run = run_to_completion(api, built["sku"]["id"], press_line["id"])
    quarantined = set_qc_disposition(
        api,
        run["id"],
        "QUARANTINED",
        QA_TECHNICIAN_B,
        hold_reason="Awaiting second curl reading",
    )
    assert quarantined["qc_disposition"] == "QUARANTINED"

    batch = batch_of_run(api, run["id"])
    assert batch["status"] == "HELD"
    assert batch["hold_reason"] == "QC_QUARANTINE"
    assert batch["held_by_user_id"] == USER_IDS["qa_technician_b"]

    # QA_TECHNICIAN is not the holder, so the segregation-of-duties band passes
    # and the cross-entity QC check is the only obstacle left.
    validate_error(
        api.set_batch_hold_status(
            batch["id"], hold_status_payload("RELEASE_HOLD"), QA_TECHNICIAN
        ),
        ApiErrorId.RUN_NOT_RELEASED.value,
    )

    after = validate_success(api.get_batch(batch["id"], QA_TECHNICIAN))
    assert after["status"] == "HELD"
    assert after["available_quantity_sqm"] == 0.00
