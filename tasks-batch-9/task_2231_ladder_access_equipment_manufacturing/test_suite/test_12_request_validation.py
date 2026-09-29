"""Request-shape, uniqueness, window, artwork and traceability validation."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_joint_samples,
    api_client,
    create_and_approve_document,
    create_approved_revision,
    create_bench_reservation_payload,
    create_campaign,
    create_consumer_registration_payload,
    create_design_revision_payload,
    create_draft_revision,
    create_product,
    create_product_document_payload,
    create_product_payload,
    create_production_lot_payload,
    create_test_bench,
    create_test_campaign_payload,
    freeze_design_payload,
    get_bench_data,
    get_lot_data,
    get_product_data,
    get_revision_data,
    open_lot,
    setup_frozen_product,
    setup_listed_product,
    setup_released_lot,
    start_lot_production,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ENGINEER = TEST_USERS["design_engineer_headers"]
APPROVER = TEST_USERS["design_approver_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
TECHNICIAN = TEST_USERS["test_lab_technician_headers"]
SUPERVISOR = TEST_USERS["production_supervisor_headers"]
CONSUMER = TEST_USERS["consumer_headers"]

FIBERGLASS = {"material": "FIBERGLASS_PULTRUSION"}


def test_a_second_product_reusing_a_model_code_is_rejected():
    """PRD §2.5: "A product's `model_code`, a bench's `bench_code`, a listing
    body's `body_code`, and a production lot's `lot_code` are each globally unique
    across their own collection."
    PRD §2.5: "Any repeat is rejected with `ERR_DUPLICATE_KEY`."

    Design: Corner/validations/duplicate_model_code_rejected
    """
    first = create_product()

    response = api_client.create_product(
        create_product_payload(model_code=first["model_code"]), ENGINEER
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_KEY.value, 409)

    rows, meta = validate_paginated(api_client.list_products(OFFICER))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]


def test_pagination_bounds_are_enforced_on_both_parameters():
    """PRD §2.3: "`limit` sets the maximum number of rows returned; it defaults
    to 10, may be no smaller than 1, and may be no larger than 100. `offset` sets
    the number of rows skipped before the page begins; it defaults to 0 and must be
    a non-negative integer. A `limit` outside the range 1 through 100, or an
    `offset` that is negative or not an integer, is rejected with
    `ERR_INVALID_PAGINATION`."

    Design: Corner/validations/pagination_limit_above_maximum_rejected
    """
    create_product()

    for params in ({"limit": 101}, {"limit": 0}, {"offset": -1}):
        response = api_client.list_products(OFFICER, params)
        validate_error(response, ApiErrorId.ERR_INVALID_PAGINATION.value, 400)

    _, meta = validate_paginated(api_client.list_products(OFFICER, {"limit": 100}))
    assert meta["total_count"] == 1, "the boundary value itself is accepted"


def test_a_reservation_ending_before_it_starts_is_rejected():
    """PRD §3.4: "A reservation whose `start_at` is not strictly earlier than its
    `end_at` is rejected with `ERR_INVALID_WINDOW`."
    PRD §3.4: "The reservation begins at `status` `HELD`, its `duration_minutes`
    is set to the whole number of minutes between `start_at` and `end_at`, and that
    figure is added to the bench's `reserved_minutes_total` per §2.9."

    Design: Corner/validations/reservation_end_before_start_rejected
    """
    product = create_product()
    revision = create_draft_revision(product["id"])
    bench = create_test_bench()
    campaign = create_campaign(product["id"], revision["id"])

    response = api_client.create_bench_reservation(
        create_bench_reservation_payload(
            bench["id"],
            campaign["id"],
            start_at="2026-08-03T12:00:00Z",
            end_at="2026-08-03T08:00:00Z",
        ),
        TECHNICIAN,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_WINDOW.value, 400)

    assert get_bench_data(bench["id"])["reserved_minutes_total"] == 0
    _, meta = validate_paginated(
        api_client.list_bench_reservations(TECHNICIAN, {"test_bench_id": bench["id"]})
    )
    assert meta["total_count"] == 0


def test_a_registration_dated_after_the_clock_is_rejected():
    """PRD §3.8: "A `purchase_date` later than the logical clock is rejected with
    `ERR_DATE_IN_FUTURE`."
    PRD §3.8: "Consumer registration is what makes lot traceability reach a
    doorstep."

    Design: Corner/validations/registration_purchase_date_in_future_rejected
    """
    _, lot = setup_released_lot(produced_units=400)

    response = api_client.create_consumer_registration(
        create_consumer_registration_payload(
            lot["id"],
            purchase_channel="ONLINE",
            purchase_date="2026-09-01T00:00:00Z",
            serial_suffix="0002",
        ),
        CONSUMER,
    )
    validate_error(response, ApiErrorId.ERR_DATE_IN_FUTURE.value, 400)

    _, meta = validate_paginated(
        api_client.list_consumer_registrations(
            OFFICER, {"production_lot_id": lot["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_the_four_audit_fields_must_match_the_campaign_purpose_both_ways():
    """PRD §3.5: "`PERIODIC_AUDIT` requires all four of `listing_record_id`,
    `sampled_lot_id`, `sample_window_start`, and `sample_window_end` to be present,
    while every other purpose requires all four to be null; a mismatch either way is
    rejected with `ERR_AUDIT_FIELDS_MISMATCH`."

    Design: Corner/validations/audit_campaign_missing_window_fields_rejected
    """
    ctx, lot = setup_released_lot(produced_units=400)

    audit_without_windows = api_client.create_test_campaign(
        create_test_campaign_payload(
            ctx["product"]["id"],
            ctx["revision"]["id"],
            "PERIODIC_AUDIT",
            listing_record_id=ctx["listing_record"]["id"],
            sampled_lot_id=lot["id"],
        ),
        TECHNICIAN,
    )
    validate_error(
        audit_without_windows, ApiErrorId.ERR_AUDIT_FIELDS_MISMATCH.value, 422
    )

    qualification_with_windows = api_client.create_test_campaign(
        create_test_campaign_payload(
            ctx["product"]["id"],
            ctx["revision"]["id"],
            "DESIGN_QUALIFICATION",
            sample_window_start="2026-08-05T00:00:00Z",
            sample_window_end="2026-08-09T00:00:00Z",
        ),
        TECHNICIAN,
    )
    validate_error(
        qualification_with_windows, ApiErrorId.ERR_AUDIT_FIELDS_MISMATCH.value, 422
    )

    _, meta = validate_paginated(
        api_client.list_test_campaigns(TECHNICIAN, {"purpose": "PERIODIC_AUDIT"})
    )
    assert meta["total_count"] == 0


def test_an_audit_sampling_another_models_lot_is_rejected():
    """PRD §3.5: "`sampled_lot_id` names the production lot the audit units were
    drawn from and `listing_record_id` names the listing being audited; if either the
    named listing record or the named lot belongs to a different model than the
    campaign's `product_id`, the plan is rejected with `ERR_AUDIT_SCOPE_MISMATCH`."

    Design: Corner/validations/audit_campaign_sampling_a_lot_of_another_product_rejected
    """
    ctx, _ = setup_released_lot(produced_units=400)
    stranger = create_product(product_type="STEP_LADDER", working_length_ft=12.0)
    stranger_revision = create_approved_revision(stranger["id"])
    stranger_lot = open_lot(stranger, stranger_revision["id"])

    response = api_client.create_test_campaign(
        create_test_campaign_payload(
            ctx["product"]["id"],
            ctx["revision"]["id"],
            "PERIODIC_AUDIT",
            listing_record_id=ctx["listing_record"]["id"],
            sampled_lot_id=stranger_lot["id"],
            sample_window_start="2026-08-05T00:00:00Z",
            sample_window_end="2026-08-09T00:00:00Z",
        ),
        TECHNICIAN,
    )
    validate_error(response, ApiErrorId.ERR_AUDIT_SCOPE_MISMATCH.value, 409)

    _, meta = validate_paginated(
        api_client.list_test_campaigns(TECHNICIAN, {"purpose": "PERIODIC_AUDIT"})
    )
    assert meta["total_count"] == 0
    assert get_lot_data(stranger_lot["id"])["status"] == "OPEN"


def test_a_revision_may_not_supersede_another_models_revision():
    """PRD §3.2: "An optional `supersedes_revision_id` names the prior revision
    this one replaces and is null for a model's first revision; if it names a
    revision belonging to a different model, the create is rejected with
    `ERR_SUPERSEDE_TARGET_MISMATCH`."

    Design: Corner/validations/revision_superseding_another_products_revision_rejected
    """
    first_product = create_product()
    foreign_revision = create_draft_revision(first_product["id"])
    second_product = create_product(product_type="STEP_LADDER", working_length_ft=12.0)

    response = api_client.create_design_revision(
        create_design_revision_payload(
            second_product["id"],
            second_product["version"],
            revision_label="A",
            supersedes_revision_id=foreign_revision["id"],
        ),
        ENGINEER,
    )
    validate_error(response, ApiErrorId.ERR_SUPERSEDE_TARGET_MISMATCH.value, 409)

    _, meta = validate_paginated(
        api_client.list_design_revisions(
            ENGINEER, {"product_id": second_product["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert get_revision_data(foreign_revision["id"])["status"] == "DRAFT"


def test_release_is_rejected_while_the_lot_is_short_of_its_required_samples():
    """PRD §3.6: "Its `joint_sample_count` must be at least its
    `required_joint_sample_count`, or the release is rejected with
    `ERR_JOINT_SAMPLE_COUNT_SHORT`."
    PRD §3.6: "`required_joint_sample_count` is derived as the larger of four
    samples and the lot's `produced_units` divided by 250 units per sample rounded
    **up** to a whole number"

    Design: Corner/validations/release_with_joint_sample_count_short_rejected
    """
    ctx = setup_frozen_product(**FIBERGLASS)
    lot = open_lot(ctx["product"], ctx["revision"]["id"])
    lot = start_lot_production(lot["id"], 400)
    assert lot["required_joint_sample_count"] == 4
    add_joint_samples(lot["id"], [470.00, 462.00, 458.00])

    response = api_client.release_production_lot(lot["id"], SUPERVISOR)
    validate_error(response, ApiErrorId.ERR_JOINT_SAMPLE_COUNT_SHORT.value, 422)

    reread = get_lot_data(lot["id"])
    assert reread["status"] == "IN_PROCESS"
    assert reread["joint_sample_count"] == 3
    assert reread["required_joint_sample_count"] == 4
    # The whole percents 4, 3 and 2 average to exactly 3.00.
    assert float(reread["conformance_index"]) == 3.00
    assert reread["units_released"] == 0


def test_release_is_rejected_when_any_joint_sample_failed():
    """PRD §3.6: "Its `joint_fail_count` must be exactly 0, or the release is
    rejected with `ERR_JOINT_INTEGRITY_FAILURE`."
    PRD §3.6: "its `result` is `PASS` when the measured `pull_force_lbf` is
    greater than or equal to that snapshot and `FAIL` otherwise."

    Design: Corner/validations/release_with_failed_joint_sample_rejected
    """
    ctx = setup_frozen_product(**FIBERGLASS)
    assert float(ctx["product"]["required_pull_force_lbf"]) == 450.00
    lot = open_lot(ctx["product"], ctx["revision"]["id"])
    lot = start_lot_production(lot["id"], 400)
    samples = add_joint_samples(lot["id"], [470.00, 462.00, 458.00, 400.00])

    response = api_client.release_production_lot(lot["id"], SUPERVISOR)
    validate_error(response, ApiErrorId.ERR_JOINT_INTEGRITY_FAILURE.value, 422)

    assert samples[3]["result"] == "FAIL"
    # 50.00 lbf short of the 450.00 snapshot is -11.11 percent.
    assert int(samples[3]["margin_pct"]) == -11

    reread = get_lot_data(lot["id"])
    assert reread["joint_sample_count"] == 4
    assert reread["joint_fail_count"] == 1
    assert reread["status"] == "IN_PROCESS"


def test_release_is_rejected_when_the_conformance_index_is_below_the_floor():
    """PRD §3.6: "And its `conformance_index` must be at least 2.00, or the
    release is rejected with `ERR_CONFORMANCE_BELOW_MINIMUM`."

    Design: Corner/validations/release_with_conformance_below_minimum_rejected
    """
    ctx = setup_frozen_product(**FIBERGLASS)
    lot = open_lot(ctx["product"], ctx["revision"]["id"])
    lot = start_lot_production(lot["id"], 400)
    # 1.00 lbf over the 450.00 snapshot rounds to a whole margin of 0 percent.
    add_joint_samples(lot["id"], [451.00, 451.00, 451.00, 451.00])

    response = api_client.release_production_lot(lot["id"], SUPERVISOR)
    validate_error(response, ApiErrorId.ERR_CONFORMANCE_BELOW_MINIMUM.value, 422)

    reread = get_lot_data(lot["id"])
    assert reread["joint_sample_count"] == 4
    assert reread["joint_fail_count"] == 0
    assert float(reread["conformance_index"]) == 0.00
    assert reread["status"] == "IN_PROCESS"


def test_retail_release_is_rejected_while_one_mandated_document_kind_is_missing():
    """PRD §3.7: "Every one of the six mandated document kinds —
    `DUTY_RATING_LABEL`, `WARNING_LABEL`, `INSTRUCTION_LABEL`, `RETAIL_CARTON`,
    `ASSEMBLY_INSTRUCTION_SHEET`, and `CONSUMER_SAFETY_SHEET` — must have at least
    one document for this model in `APPROVED`; a gap is rejected with
    `ERR_LABEL_SET_INCOMPLETE`."

    Design: Corner/validations/retail_release_with_incomplete_label_set_rejected
    """
    ctx = setup_listed_product()
    for kind in (
        "DUTY_RATING_LABEL",
        "WARNING_LABEL",
        "INSTRUCTION_LABEL",
        "RETAIL_CARTON",
        "ASSEMBLY_INSTRUCTION_SHEET",
    ):
        create_and_approve_document(ctx["product"]["id"], kind)

    response = api_client.release_to_retail(ctx["product"]["id"], OFFICER)
    validate_error(response, ApiErrorId.ERR_LABEL_SET_INCOMPLETE.value, 422)

    product = get_product_data(ctx["product"]["id"])
    assert product["market_status"] == "NOT_RELEASED"
    assert product["design_status"] == "DESIGN_FROZEN"
    assert ctx["listing_record"]["status"] == "LISTED"

    _, meta = validate_paginated(
        api_client.list_product_documents(
            ctx["product"]["id"], OFFICER, {"status": "APPROVED"}
        )
    )
    assert meta["total_count"] == 5


def test_each_artwork_rule_is_enforced_at_document_creation():
    """PRD §3.3: "Three artwork rules are enforced identically at document
    creation and again at approval, and any of the three failing yields
    `ERR_LABEL_PLACEMENT_INVALID`: a label kind must have a non-null
    `placement_zone` while a non-label kind must have a null one; a `WARNING_LABEL`
    must carry at least two warning pictograms in its `pictogram_count`; and an
    `ASSEMBLY_INSTRUCTION_SHEET` must have `includes_assembly_instructions` set to
    true."

    Design: Corner/validations/warning_label_with_too_few_pictograms_rejected
    """
    product = create_product()

    too_few_pictograms = api_client.create_product_document(
        create_product_document_payload(
            product["id"],
            "WARNING_LABEL",
            placement_zone="SIDE_RAIL_LOWER",
            pictogram_count=1,
        ),
        OFFICER,
    )
    validate_error(
        too_few_pictograms, ApiErrorId.ERR_LABEL_PLACEMENT_INVALID.value, 422
    )

    packaging_with_zone = api_client.create_product_document(
        create_product_document_payload(
            product["id"], "RETAIL_CARTON", placement_zone="SIDE_RAIL_UPPER"
        ),
        OFFICER,
    )
    validate_error(
        packaging_with_zone, ApiErrorId.ERR_LABEL_PLACEMENT_INVALID.value, 422
    )

    sheet_without_instructions = api_client.create_product_document(
        create_product_document_payload(
            product["id"],
            "ASSEMBLY_INSTRUCTION_SHEET",
            includes_assembly_instructions=False,
        ),
        OFFICER,
    )
    validate_error(
        sheet_without_instructions, ApiErrorId.ERR_LABEL_PLACEMENT_INVALID.value, 422
    )

    _, meta = validate_paginated(
        api_client.list_product_documents(product["id"], OFFICER)
    )
    assert meta["total_count"] == 0


def test_an_unknown_pinned_revision_outranks_the_already_frozen_state():
    """PRD §2.5: "Existence of every foreign-key identifier in the request
    **body**, validated in the order the fields are declared for that operation,
    answering with `ERR_PRODUCT_NOT_FOUND`, `ERR_DESIGN_REVISION_NOT_FOUND`,
    `ERR_LISTING_BODY_NOT_FOUND`, `ERR_LISTING_RECORD_NOT_FOUND`,
    `ERR_PRODUCTION_LOT_NOT_FOUND`"
    PRD §3.7: "The model's `design_status` must be `DRAFT`, or the request is
    rejected with `ERR_PRODUCT_STATE_INVALID`."

    Design: Corner/validations/existence_error_outranks_product_state_error_on_freeze_design
    """
    ctx = setup_frozen_product()

    response = api_client.freeze_design(
        ctx["product"]["id"], freeze_design_payload(NON_EXISTENT_UUID), APPROVER
    )
    validate_error(response, ApiErrorId.ERR_DESIGN_REVISION_NOT_FOUND.value, 404)

    product = get_product_data(ctx["product"]["id"])
    assert product["design_status"] == "DESIGN_FROZEN"
    assert product["frozen_revision_id"] == ctx["revision"]["id"]


def test_a_fiberglass_lot_carrying_its_pultrusion_batch_starts_production():
    """PRD §3.6: "Process traceability must match the construction process: a lot
    of a model whose `material` is `FIBERGLASS_PULTRUSION` must carry a non-null
    `pultrusion_batch_id`, and a lot of a model whose `material` is
    `ALUMINUM_EXTRUSION` must carry a non-null `extrusion_heat_number`; either gap is
    rejected with `ERR_PROCESS_TRACEABILITY_MISSING`."
    PRD §3.6: "On success, both `produced_units` and `units_wip` are set to the
    supplied figure, and `required_joint_sample_count` is derived as the larger of
    four samples and the lot's `produced_units` divided by 250 units per sample
    rounded **up** to a whole number"

    Design: Corner/validations/start_production_with_pultrusion_batch_id_succeeds
    """
    ctx = setup_frozen_product(**FIBERGLASS)
    lot = open_lot(
        ctx["product"], ctx["revision"]["id"], pultrusion_batch_id="PB-77"
    )
    assert lot["status"] == "OPEN"

    started = validate_success(
        api_client.start_production(
            lot["id"], {"produced_units": 400}, SUPERVISOR
        )
    )

    assert started["status"] == "IN_PROCESS"
    assert started["produced_units"] == 400
    assert started["units_wip"] == 400
    assert started["required_joint_sample_count"] == 4
    assert started["conformance_index"] is None


def test_a_fiberglass_lot_without_its_pultrusion_batch_cannot_start_production():
    """PRD §3.6: "a lot of a model whose `material` is `FIBERGLASS_PULTRUSION`
    must carry a non-null `pultrusion_batch_id`, and a lot of a model whose
    `material` is `ALUMINUM_EXTRUSION` must carry a non-null
    `extrusion_heat_number`; either gap is rejected with
    `ERR_PROCESS_TRACEABILITY_MISSING`."
    PRD §3.6: "Two process-traceability fields are optional at creation:
    `extrusion_heat_number` records the aluminium extrusion heat and is null for
    non-extruded materials, and `pultrusion_batch_id` records the fiberglass
    pultrusion batch."

    Design: Corner/validations/fiberglass_lot_without_pultrusion_batch_id_rejected
    """
    ctx = setup_frozen_product(**FIBERGLASS)
    lot = validate_success(
        api_client.create_production_lot(
            create_production_lot_payload(
                ctx["product"]["id"],
                ctx["revision"]["id"],
                extrusion_heat_number="HEAT-42",
            ),
            SUPERVISOR,
        ),
        201,
    )

    response = api_client.start_production(
        lot["id"], {"produced_units": 400}, SUPERVISOR
    )
    validate_error(response, ApiErrorId.ERR_PROCESS_TRACEABILITY_MISSING.value, 422)

    reread = get_lot_data(lot["id"])
    assert reread["status"] == "OPEN"
    assert reread["produced_units"] == 0
    assert reread["units_wip"] == 0
