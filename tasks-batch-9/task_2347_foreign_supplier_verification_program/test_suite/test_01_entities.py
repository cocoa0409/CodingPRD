"""Entity contracts: creation defaults, computed fields, identity and uniqueness."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as err
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_immutable_row,
    assert_importer_rollup,
    assert_money,
    assert_pair_dimensions,
    assert_versioned_row,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER_HEADERS,
    FDA_INSPECTOR_HEADERS,
    make_qualified_individual_headers,
)


def test_importer_creation_returns_program_rollup_fields_at_version_one(
    api: ApiClient, clock_at_base: str
):
    """PRD 3.1: "A freshly registered importer is not compliant. Its
    `blocked_pair_count` and `open_corrective_action_count` are both 0, its
    `qualified_individual_designated` is false, and its `program_status` is
    therefore `NON_COMPLIANT` — no qualified individual exists yet, and under the
    programme-status rule of §2.7 the absence of an active designation is by itself
    disqualifying. Reading the importer back returns those four roll-up fields
    live."
    PRD 2.5: "Most resources additionally carry `updated_at` — an ISO 8601 UTC
    timestamp refreshed on every mutation — and `version`, a monotonically
    increasing integer that starts at 1 and increments by exactly one on every
    mutation of that row, including mutations the row's owner never requested (a
    recomputed roll-up counts as a mutation)."
    Registering an importer returns 201 Created per the endpoint definitions.

    Design: Corner/entities/importer_creation_returns_program_rollup_fields_at_version_one
    """
    response = api.create_importer(f.importer_payload(), COMPLIANCE_OFFICER_HEADERS)
    importer = validate_success(response, 201)

    assert response.json()["response_type"] == "object", (
        "a single created resource must be enveloped as response_type object"
    )
    assert importer["legal_name"] == f.IMPORTER_LEGAL_NAME
    assert importer["dnb_number"] == f.IMPORTER_DNB
    assert importer["unique_facility_identifier"] == f.IMPORTER_UFI

    assert_importer_rollup(
        importer,
        blocked_pair_count=0,
        open_corrective_action_count=0,
        qualified_individual_designated=False,
        program_status="NON_COMPLIANT",
    )
    assert_versioned_row(importer, "importer")
    assert importer["version"] == 1, (
        f"a freshly registered importer must be at version 1, got {importer['version']}"
    )


def test_supplier_food_pair_retrieval_returns_three_status_dimensions_and_risk_fields(
    api: ApiClient,
):
    """PRD 2.6: "A `SupplierFoodPair` — the food × foreign-supplier combination
    that FSVP treats as the unit of compliance — carries three independent status
    dimensions on the same row, and none of them is derivable from the others."
    PRD 3.3: "**Step two** fixes `risk_tier` from the gross risk and from nothing
    else: `HIGH` when gross risk is at or above 40.00, otherwise `MODERATE` when
    it is at or above 18.00, otherwise `LOW`."
    PRD 3.3: "`required_annual_frequency` is 1 for a `LOW` tier, 2 for
    `MODERATE`, and 4 for `HIGH`; and `required_coverage` is
    `composite_hazard_risk` multiplied by 1.5, rounded half up to two decimal
    places."
    PRD 3.3: "The combination's `verification_status` advances `DRAFT →
    HAZARD_ANALYZED`, or self-loops `HAZARD_ANALYZED → HAZARD_ANALYZED` when a
    newer analysis replaces an earlier approved one."
    PRD 3.4: "The **PLANNED** variant, surfaced as `adequacy_score_planned`,
    takes as its input set every activity on the combination whose `status` is
    `APPROVED`; it is recomputed whenever an activity's status or fields change,
    when a hazard analysis is approved, and when the supplier's compliance status
    or final performance score moves, and it is the variant that gates
    verification approval."

    Design: Corner/entities/supplier_food_pair_retrieval_returns_three_status_dimensions_and_risk_fields
    """
    # One control-bearing hazard: Listeria, severity 4 x probability 3, ready-to-eat
    # biological penalty 1.15, foreign-supplier control factor 1.00 -> risk_score 13.80.
    world = fx.analyzed_program(api, hazards=[fx.HAZARD_LISTERIA])

    pair = validate_success(
        api.get_supplier_food_pair(world.pair_id, COMPLIANCE_OFFICER_HEADERS)
    )

    assert_pair_dimensions(
        pair,
        verification_status="HAZARD_ANALYZED",
        entry_eligibility_status="PENDING",
        exemption_status="NONE",
    )
    assert pair["active_hazard_analysis_id"] == world.analysis_id
    assert pair["hazard_analysis_count"] == 1

    assert_money(pair["composite_hazard_risk"], 13.80, "composite_hazard_risk")
    assert pair["risk_tier"] == "LOW", f"expected LOW tier, got {pair['risk_tier']}"
    assert pair["required_annual_frequency"] == 1
    assert_money(pair["required_coverage"], 20.70, "required_coverage")
    assert pair["uncontrolled_significant_hazard_count"] == 1

    assert_money(pair["adequacy_score_planned"], 0.00, "adequacy_score_planned")
    assert_money(pair["adequacy_score_realized"], 0.00, "adequacy_score_realized")
    assert pair["last_reassessed_at"] is None
    assert pair["reassessment_due_at"] is None


def test_importer_foods_listing_paginates_with_total_count_and_has_more(
    api: ApiClient, clock_at_base: str
):
    """PRD 2.3: "List responses carry `limit`, `offset`, `total_count` and
    `has_more` inside the envelope's `meta` object, where `total_count` is the
    number of rows matching the filter before pagination is applied and
    `has_more` indicates whether rows remain beyond the current page."

    Design: Corner/entities/importer_foods_listing_paginates_with_total_count_and_has_more
    """
    importer = fx.create_importer(api)
    fx.create_food(api, importer["id"])
    fx.create_juice_food(api, importer["id"])
    fx.create_plain_food(api, importer["id"])

    response = api.list_importer_foods(
        importer["id"], FDA_INSPECTOR_HEADERS, {"limit": 2, "offset": 0}
    )
    rows, meta = validate_paginated(response)

    assert response.json()["response_type"] == "array"
    assert meta["total_count"] == 3, (
        f"total_count must count the whole filtered set, got {meta['total_count']}"
    )
    assert meta["has_more"] is True, "rows remain beyond a two-row page over three foods"
    assert len(rows) == 2, f"limit=2 must return exactly two rows, got {len(rows)}"


def test_get_supplier_food_pair_with_unknown_id_returns_pair_not_found(
    api: ApiClient, clock_at_base: str
):
    """PRD 2.11: "The `{id}` path segment or `pair_id` resolves to a
    `SupplierFoodPair` — `ERR_PAIR_NOT_FOUND` (404), on the combination read,
    verification approval, reassessment, exemption, hazard-analysis create,
    activity create and entry-line create."

    Design: Corner/entities/get_supplier_food_pair_with_unknown_id_returns_pair_not_found
    """
    fx.create_importer(api)

    response = api.get_supplier_food_pair(NON_EXISTENT_UUID, COMPLIANCE_OFFICER_HEADERS)
    validate_error(response, err.ERR_PAIR_NOT_FOUND)


def test_importer_create_without_dnb_number_returns_invalid_request(
    api: ApiClient, clock_at_base: str
):
    """PRD 3.1: "A `ComplianceOfficer` opens the programme by registering the
    importer of record, supplying its `legal_name`, the `dnb_number` that will be
    transmitted as the importer identifier at entry, and the
    `unique_facility_identifier` (the UFI) that accompanies it."
    PRD 2.11: "Request shape: required fields present, types correct, enum values
    in range, integers inside their declared bounds, datetimes valid ISO 8601
    UTC, string lengths inside their declared constraints, `limit` between 1 and
    100, `offset` at least 0 — `ERR_INVALID_REQUEST` (400), on every endpoint."

    Design: Corner/entities/importer_create_without_dnb_number_returns_invalid_request
    """
    response = api.create_importer(
        f.importer_payload(dnb_number=f.OMIT), COMPLIANCE_OFFICER_HEADERS
    )
    validate_error(response, err.ERR_INVALID_REQUEST)


def test_omitted_optional_inputs_take_their_declared_defaults(
    api: ApiClient, clock_at_base: str
):
    """PRD 3.1: "Two optional fields shape the importer's regime:
    `small_importer_flag`, which defaults to false and marks an importer that
    qualifies as a very small importer eligible for modified requirements, and
    `record_retention_months`, which defaults to 24 and must be between 24 and
    120 inclusive — it is the retention period applied to every verification
    record the importer ever files."
    PRD 3.2: "Two optional fields describe the regulatory and culinary context:
    `process_control_category`, defaulting to `NONE` and drawn from `NONE`,
    `JUICE_HACCP`, `SEAFOOD_HACCP`, `LOW_ACID_CANNED`, `DIETARY_SUPPLEMENT` and
    `ALCOHOL_BEVERAGE`, which records the process-control regime already covering
    the food; and `ready_to_eat`, defaulting to false and true when the food is
    consumed without a kill step."
    PRD 3.1: "An optional `concurrent_activity_capacity`, defaulting to 2 and
    constrained to between 1 and 6 inclusive, caps how many already-assigned
    execution windows may overlap a new assignment for this individual."
    PRD 3.1: "The row is created in `status` `PROPOSED`, and `training_valid_until`
    is derived immediately as `training_completed_at` advanced by 36 calendar
    months."

    Design: Corner/entities/omitted_optional_inputs_take_their_declared_defaults
    """
    importer = validate_success(
        api.create_importer(f.importer_payload(), COMPLIANCE_OFFICER_HEADERS), 201
    )
    assert importer["small_importer_flag"] is False
    assert importer["record_retention_months"] == 24

    food = validate_success(
        api.create_food(
            f.food_payload(importer["id"], ready_to_eat=f.OMIT),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        201,
    )
    assert food["process_control_category"] == "NONE"
    assert food["ready_to_eat"] is False

    individual = validate_success(
        api.create_qualified_individual(
            f.qualified_individual_payload(importer["id"]), COMPLIANCE_OFFICER_HEADERS
        ),
        201,
    )
    assert individual["concurrent_activity_capacity"] == 2
    assert individual["status"] == "PROPOSED"


def test_qi_training_valid_until_computed_thirty_six_months_after_training(
    api: ApiClient, clock_at_base: str
):
    """PRD 2.4: "Two derived date fields are computed with calendar-month
    arithmetic rather than fixed day counts: a qualified individual's
    `training_valid_until` is the individual's `training_completed_at` advanced by
    36 calendar months, and a supplier-food combination's `reassessment_due_at` is
    its `last_reassessed_at` advanced by 36 calendar months."
    PRD 3.1: "The row is created in `status` `PROPOSED`, and `training_valid_until`
    is derived immediately as `training_completed_at` advanced by 36 calendar
    months. A computed `active_assignment_count` — the number of verification
    activities assigned to this individual whose `status` is `PROPOSED`,
    `CHANGES_REQUESTED` or `APPROVED` — starts at 0."
    PRD 2.7: "`qualified_individual_designated` is true exactly when the importer
    has at least one qualified individual whose `status` is `ACTIVE` and whose
    `training_valid_until` is at or after the logical clock."

    Design: Corner/entities/qi_training_valid_until_computed_thirty_six_months_after_training
    """
    importer = fx.create_importer(api)

    # training_completed_at 2025-06-01 advanced by 36 calendar months -> 2028-06-01.
    individual = validate_success(
        api.create_qualified_individual(
            f.qualified_individual_payload(
                importer["id"], training_completed_at="2025-06-01T00:00:00Z"
            ),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        201,
    )
    assert individual["training_valid_until"].startswith("2028-06-01T00:00:00"), (
        "training_valid_until must be the training instant plus 36 calendar months, "
        f"got {individual['training_valid_until']}"
    )
    assert individual["status"] == "PROPOSED"
    assert individual["active_assignment_count"] == 0

    # A merely PROPOSED individual is not an ACTIVE designation.
    rolled_up = validate_success(
        api.get_importer(importer["id"], COMPLIANCE_OFFICER_HEADERS)
    )
    assert_importer_rollup(
        rolled_up,
        qualified_individual_designated=False,
        program_status="NON_COMPLIANT",
    )


def test_pair_system_fields_minted_by_server_on_create(api: ApiClient, clock_at_base: str):
    """PRD 3.2: "Creation initialises all three dimensions —
    `verification_status` `DRAFT`, `entry_eligibility_status` `PENDING`,
    `exemption_status` `NONE` — and leaves `exemption_type`,
    `active_hazard_analysis_id`, `last_reassessed_at` and `reassessment_due_at`
    null, `modified_requirements_only` false, and `hazard_analysis_count`,
    `uncontrolled_significant_hazard_count`, `adequacy_score_planned` and
    `adequacy_score_realized` at their zero values."
    PRD 2.5: "Every persisted resource carries an `id`, which is a server-minted
    UUID with no type prefix, and a `created_at`, which is an ISO 8601 UTC
    timestamp with three fractional digits recording when the row was first
    written."
    PRD 2.5: "Most resources additionally carry `updated_at` — an ISO 8601 UTC
    timestamp refreshed on every mutation — and `version`, a monotonically
    increasing integer that starts at 1 and increments by exactly one on every
    mutation of that row, including mutations the row's owner never requested (a
    recomputed roll-up counts as a mutation)."

    Design: Corner/entities/pair_system_fields_minted_by_server_on_create
    """
    importer = fx.create_importer(api)
    individual = fx.create_qualified_individual(api, importer["id"])
    supplier = fx.create_supplier(api, importer["id"], approve_by_qi_id=individual["id"])
    food = fx.create_food(api, importer["id"])

    # The create body carries only the four foreign keys; everything else is minted.
    pair = validate_success(
        api.create_supplier_food_pair(
            f.pair_payload(importer["id"], supplier["id"], food["id"], individual["id"]),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        201,
    )

    assert_versioned_row(pair, "supplier-food pair")
    assert pair["version"] == 1, f"a new combination starts at version 1, got {pair['version']}"
    assert_pair_dimensions(
        pair,
        verification_status="DRAFT",
        entry_eligibility_status="PENDING",
        exemption_status="NONE",
    )
    assert pair["exemption_type"] is None
    assert pair["modified_requirements_only"] is False


def test_hazard_create_with_severity_above_five_returns_invalid_request(api: ApiClient):
    """PRD 3.3: "Each hazard names a `hazard_type` — `BIOLOGICAL`,
    `CHEMICAL_INCL_RADIOLOGICAL` or `PHYSICAL` — a `hazard_name` such as
    'Salmonella spp.', a `severity` and a `probability` each between 1 and 5
    inclusive, and a `control_owner` drawn from `FOREIGN_SUPPLIER`,
    `SUPPLIER_OF_SUPPLIER`, `IMPORTER` and `CUSTOMER_DOWNSTREAM`."
    PRD 2.11: "Request shape: required fields present, types correct, enum values
    in range, integers inside their declared bounds, datetimes valid ISO 8601
    UTC, string lengths inside their declared constraints, `limit` between 1 and
    100, `offset` at least 0 — `ERR_INVALID_REQUEST` (400), on every endpoint."
    PRD 3.3: "The new row starts in `status` `DRAFT` with `risk_total` 0.00,
    `hazard_count` 0 and `significant_hazard_count` 0; its `authored_by_qi_id` is
    copied from `X-User-ID`, and the accepted `expected_pair_version` is retained
    as `pair_version_at_create`."

    Design: Corner/entities/hazard_create_with_severity_above_five_returns_invalid_request
    """
    world = fx.base_program(api)
    analysis = fx.create_hazard_analysis(api, world.pair_id, world.qi_a_id)

    response = api.create_hazard(
        analysis["id"],
        f.hazard_payload(severity=6),
        make_qualified_individual_headers(world.qi_a_id),
    )
    validate_error(response, err.ERR_INVALID_REQUEST)

    # The out-of-range severity never reaches the scoring formula, so no row exists.
    reread = fx.get_analysis(api, analysis["id"])
    assert reread["hazard_count"] == 0, "the rejected hazard must not have been persisted"
    assert_money(reread["risk_total"], 0.00, "risk_total")


def test_food_row_is_immutable_with_no_version_field(api: ApiClient, clock_at_base: str):
    """PRD 2.5: "Two resource types are immutable after creation and therefore
    carry only `id` and `created_at`: a `Food` row and a `Hazard` row. For those
    two, both `updated_at` and `version` are absent from the response entirely —
    there is no update endpoint for either, and neither participates in version
    pinning."

    Design: Corner/entities/food_row_is_immutable_with_no_version_field
    """
    importer = fx.create_importer(api)
    food = fx.create_food(api, importer["id"])
    assert_immutable_row(food, "food (create response)")

    rows, meta = validate_paginated(
        api.list_importer_foods(importer["id"], COMPLIANCE_OFFICER_HEADERS)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == food["id"]
    assert_immutable_row(rows[0], "food (listing row)")


def test_pair_create_with_food_of_another_importer_rejected(
    api: ApiClient, clock_at_base: str
):
    """PRD 3.2: "The supplier, the food, the named individual and the body's
    importer must all belong to the same importer, or the create is refused with
    `ERR_IMPORTER_SCOPE_MISMATCH`."
    PRD 2.11: "Single-importer scope — `ERR_IMPORTER_SCOPE_MISMATCH` (409), on
    combination create, activity create, activity revision and hazard-analysis
    create."

    Design: Corner/entities/pair_create_with_food_of_another_importer_rejected
    """
    importer = fx.create_importer(api)
    other_importer = fx.create_second_importer(api)
    individual = fx.create_qualified_individual(api, importer["id"])
    supplier = fx.create_supplier(api, importer["id"])
    # The food exists and resolves, but it is owned by the second importer.
    foreign_food = fx.create_food(api, other_importer["id"])

    response = api.create_supplier_food_pair(
        f.pair_payload(
            importer["id"], supplier["id"], foreign_food["id"], individual["id"]
        ),
        COMPLIANCE_OFFICER_HEADERS,
    )
    validate_error(response, err.ERR_IMPORTER_SCOPE_MISMATCH)

    _rows, meta = validate_paginated(
        api.list_supplier_food_pairs(
            COMPLIANCE_OFFICER_HEADERS, {"importer_id": importer["id"]}
        )
    )
    assert meta["total_count"] == 0, "the rejected combination must not have been persisted"


def test_many_to_many_second_pair_same_supplier_different_food_allowed(
    api: ApiClient, clock_at_base: str
):
    """PRD 3.2: "A combination whose `supplier_id` and `food_id` duplicate an
    existing combination is refused with `ERR_DUPLICATE_SUPPLIER_FOOD_PAIR`
    unless every such existing combination has `verification_status` equal to
    `RETIRED` — retirement frees the pairing for a fresh start."
    PRD 2.11: "No existing combination with the same `supplier_id` and `food_id`
    whose `verification_status` is anything other than `RETIRED` —
    `ERR_DUPLICATE_SUPPLIER_FOOD_PAIR` (409), on combination create."
    PRD 3.2: "Creation initialises all three dimensions — `verification_status`
    `DRAFT`, `entry_eligibility_status` `PENDING`, `exemption_status` `NONE`".

    Design: Corner/entities/many_to_many_second_pair_same_supplier_different_food_allowed
    """
    importer = fx.create_importer(api)
    individual = fx.create_qualified_individual(api, importer["id"])
    supplier = fx.create_supplier(api, importer["id"], approve_by_qi_id=individual["id"])
    first_food = fx.create_food(api, importer["id"])
    second_food = fx.create_juice_food(api, importer["id"])
    first_pair = fx.create_pair(
        api, importer["id"], supplier["id"], first_food["id"], individual["id"]
    )

    # Same supplier, different food: the uniqueness scope is the tuple, not the supplier.
    second_pair = validate_success(
        api.create_supplier_food_pair(
            f.pair_payload(
                importer["id"], supplier["id"], second_food["id"], individual["id"]
            ),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        201,
    )
    assert second_pair["id"] != first_pair["id"]
    assert second_pair["supplier_id"] == supplier["id"]
    assert second_pair["food_id"] == second_food["id"]
    assert_pair_dimensions(second_pair, verification_status="DRAFT")

    _rows, meta = validate_paginated(
        api.list_supplier_food_pairs(
            COMPLIANCE_OFFICER_HEADERS, {"supplier_id": supplier["id"]}
        )
    )
    assert meta["total_count"] == 2, (
        f"one supplier may carry two combinations, got total_count {meta['total_count']}"
    )


def test_duplicate_supplier_food_pair_rejected_while_not_retired(
    api: ApiClient, clock_at_base: str
):
    """PRD 3.2: "A combination whose `supplier_id` and `food_id` duplicate an
    existing combination is refused with `ERR_DUPLICATE_SUPPLIER_FOOD_PAIR`
    unless every such existing combination has `verification_status` equal to
    `RETIRED` — retirement frees the pairing for a fresh start."
    PRD 2.11: "No existing combination with the same `supplier_id` and `food_id`
    whose `verification_status` is anything other than `RETIRED` —
    `ERR_DUPLICATE_SUPPLIER_FOOD_PAIR` (409), on combination create."

    Design: Corner/entities/duplicate_supplier_food_pair_rejected_while_not_retired
    """
    importer = fx.create_importer(api)
    individual = fx.create_qualified_individual(api, importer["id"])
    supplier = fx.create_supplier(api, importer["id"])
    food = fx.create_food(api, importer["id"])
    existing = fx.create_pair(
        api, importer["id"], supplier["id"], food["id"], individual["id"]
    )
    assert existing["verification_status"] == "DRAFT", (
        "the incumbent combination must be in a non-RETIRED state for this check"
    )

    response = api.create_supplier_food_pair(
        f.pair_payload(importer["id"], supplier["id"], food["id"], individual["id"]),
        COMPLIANCE_OFFICER_HEADERS,
    )
    validate_error(response, err.ERR_DUPLICATE_SUPPLIER_FOOD_PAIR)

    _rows, meta = validate_paginated(
        api.list_supplier_food_pairs(
            COMPLIANCE_OFFICER_HEADERS, {"supplier_id": supplier["id"]}
        )
    )
    assert meta["total_count"] == 1, "the duplicate combination must not have been persisted"
