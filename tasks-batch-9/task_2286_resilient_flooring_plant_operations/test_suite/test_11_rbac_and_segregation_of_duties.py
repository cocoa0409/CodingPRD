"""Role authorisation, Distributor ownership narrowing and segregation of duties.

These tests cover the three distinct refusals of PRD §2.1, §2.5 and §2.8: a role
that is absent from an endpoint's authorised set (`ERR_UNAUTHORIZED`), a
`Distributor` acting on a row belonging to another account
(`ERR_NOT_RESOURCE_OWNER`), and an authorised caller who is personally
disqualified because they performed the conflicting earlier step of the same
workflow (`ERR_SEGREGATION_OF_DUTIES`). The payload-dependent authorisation
split on design-grant status changes is covered here too, together with the
positive controls in PRD §3.1, §3.5, §3.7 and §3.9 that show each refusal turns
on identity rather than on role.
"""

from test_helpers import (
    ApiErrorId,
    FORMULATOR,
    PLANT_ADMIN,
    PRODUCTION_PLANNER,
    QA_TECHNICIAN,
    QA_TECHNICIAN_B,
    TECHNICAL_DIRECTOR,
    TECHNICAL_DIRECTOR_B,
    USER_IDS,
    UserRole,
    WARRANTY_ADJUSTER,
    WARRANTY_ADJUSTER_B,
    adjudication_payload,
    allocation_payload,
    begin_testing,
    build_certified_sku,
    build_draft_formulation,
    build_open_allocation,
    build_passed_panel,
    build_sku,
    build_stock_batch,
    build_user_headers,
    create_claim,
    create_distributor,
    create_license,
    distributor_headers,
    fill_payload,
    formulation_payload,
    hold_status_payload,
    license_status_payload,
    raw_material_payload,
    record_review,
    review_decision_payload,
    set_batch_hold,
    set_clock,
    submit_formulation,
    triage_claim,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_plant_admin_and_formulator_writes_are_mutually_exclusive(api):
    """Neither master-data role nor recipe-author role can perform the other's write.

    "Once the caller is identified, the declared role must appear in the set of
    roles authorised for the addressed operation; otherwise the request fails
    with `ERR_UNAUTHORIZED` (HTTP 403)."
    "The plant's material library is administered by a `PlantAdmin`."
    "Recipes are authored by a `Formulator`, who supplies a `formulation_code`
    unique across recipes and, when the new recipe is intended to replace an
    existing approved one, the `supersedes_formulation_id` of that predecessor;
    for an original recipe the field is null."
    "A newly created recipe is `DRAFT` with `revision` 1, `cost_basis` `LIVE`,
    `rejection_count` and `open_revision_count` both 0, and
    `authored_by_user_id` set to the acting `X-User-ID`."
    "`total_count` (the number of rows matching the filters before the window is
    applied)"

    Design: Corner/rbac/plant_admin_and_formulator_writes_are_mutually_exclusive
    """
    material_body = raw_material_payload("RM-X", name="Unauthorised material")
    recipe_body = formulation_payload("F-X")

    # A Formulator may not register master data.
    validate_error(
        api.create_raw_material(material_body, FORMULATOR),
        ApiErrorId.UNAUTHORIZED.value,
    )
    # A PlantAdmin may not author a recipe.
    validate_error(
        api.create_formulation(recipe_body, PLANT_ADMIN),
        ApiErrorId.UNAUTHORIZED.value,
    )

    # Neither refusal wrote anything.
    materials, materials_meta = validate_paginated(api.list_raw_materials(PLANT_ADMIN))
    assert materials == [], "the refused raw-material create must not have persisted"
    assert materials_meta["total_count"] == 0
    recipes, recipes_meta = validate_paginated(api.list_formulations(PLANT_ADMIN))
    assert recipes == [], "the refused recipe create must not have persisted"
    assert recipes_meta["total_count"] == 0

    # The identical payloads succeed for the permitted roles.
    material = validate_success(
        api.create_raw_material(material_body, PLANT_ADMIN), 201
    )
    assert material["material_code"] == "RM-X"
    recipe = validate_success(api.create_formulation(recipe_body, FORMULATOR), 201)
    assert recipe["formulation_code"] == "F-X"
    assert recipe["status"] == "DRAFT"
    assert recipe["authored_by_user_id"] == USER_IDS["formulator"]


def test_sku_catalog_read_is_shared_by_six_roles_and_closed_to_the_seventh(api):
    """Six roles read the same SKU row; the WarrantyAdjuster is refused outright.

    "| `GET` | `/product-skus/{id}` | Read one SKU | `PlantAdmin`, `Formulator`,
    `TechnicalDirector`, `QaTechnician`, `ProductionPlanner`, `Distributor` |"
    "Once the caller is identified, the declared role must appear in the set of
    roles authorised for the addressed operation; otherwise the request fails
    with `ERR_UNAUTHORIZED` (HTTP 403)."
    "When `X-User-Role` is `Distributor`, `X-User-ID` is the `id` of the acting
    distributor row."
    "A `Distributor` reading or acting on an allocation whose `distributor_id`
    differs from `X-User-ID` — filling it, releasing it, reading the allocation
    itself, reading its lines, or reading an individual warranty claim — is
    refused with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    "The residential term is 25 years when `wear_layer_mil` is at least 20, 20
    years when it is at least 12 but below 20, 15 years when it is at least 6 but
    below 12, and 10 years otherwise."

    Design: Corner/rbac/sku_catalog_read_is_shared_by_six_roles_and_closed_to_the_seventh
    """
    built = build_sku(api)
    sku_id = built["sku"]["id"]
    distributor = create_distributor(api)

    permitted = {
        "PlantAdmin": PLANT_ADMIN,
        "Formulator": FORMULATOR,
        "TechnicalDirector": TECHNICAL_DIRECTOR,
        "QaTechnician": QA_TECHNICIAN,
        "ProductionPlanner": PRODUCTION_PLANNER,
        "Distributor": distributor_headers(distributor["id"]),
    }
    representations = {}
    for role_name, headers in permitted.items():
        row = validate_success(api.get_product_sku(sku_id, headers))
        assert row["id"] == sku_id
        assert row["sku_code"] == "SKU-A"
        # wear_layer_mil is 12, which is the "at least 12 but below 20" tier.
        assert row["warranty_years"] == 20
        representations[role_name] = row

    reference = representations["PlantAdmin"]
    for role_name, row in representations.items():
        assert row == reference, (
            f"{role_name} received a different representation of the SKU catalogue row"
        )

    # The one internal role outside this endpoint's authorised set. The SKU
    # catalogue is not ownership-narrowed, so the Distributor read above is not
    # an ERR_NOT_RESOURCE_OWNER case either.
    validate_error(
        api.get_product_sku(sku_id, WARRANTY_ADJUSTER),
        ApiErrorId.UNAUTHORIZED.value,
    )


def test_license_status_authority_splits_on_the_requested_to_status(api):
    """Suspension is PlantAdmin-only and termination TechnicalDirector-only.

    "One endpoint splits its authorisation by payload rather than by path:
    changing a design grant's status to `TERMINATED` is reserved to
    `TechnicalDirector`, while moving a grant to `ACTIVE` or `SUSPENDED` is
    reserved to `PlantAdmin`."
    "Both roles are nominally authorised for the endpoint, so the mismatch
    surfaces as `ERR_UNAUTHORIZED` (HTTP 403) after the general role check rather
    than before it."
    "`ACTIVE → SUSPENDED` is a `PlantAdmin` action and cascades three hops: every
    `AVAILABLE` film on the grant moves to `RESTRICTED`; because those films were
    restricted, every SKU on one of them whose `commercial_status` is `RELEASED`
    moves to `HOLD`; and because those SKUs went on hold, each of their
    `IN_STOCK` batches moves to `HELD` with `hold_reason` `SKU_ON_HOLD`."
    "Termination is a `TechnicalDirector` action reachable from either `ACTIVE`
    or `SUSPENDED`, and it runs four hops."

    Design: Corner/rbac/license_status_authority_splits_on_the_requested_to_status
    """
    license_row = create_license(api)
    license_id = license_row["id"]
    assert license_row["status"] == "ACTIVE"

    # TechnicalDirector is in the endpoint's allowed roles but may not suspend.
    validate_error(
        api.set_license_status(
            license_id, license_status_payload("SUSPENDED"), TECHNICAL_DIRECTOR
        ),
        ApiErrorId.UNAUTHORIZED.value,
    )
    suspended = validate_success(
        api.set_license_status(
            license_id, license_status_payload("SUSPENDED"), PLANT_ADMIN
        )
    )
    assert suspended["status"] == "SUSPENDED"

    # PlantAdmin just transitioned this very grant, yet may not terminate it.
    validate_error(
        api.set_license_status(
            license_id, license_status_payload("TERMINATED"), PLANT_ADMIN
        ),
        ApiErrorId.UNAUTHORIZED.value,
    )
    terminated = validate_success(
        api.set_license_status(
            license_id, license_status_payload("TERMINATED"), TECHNICAL_DIRECTOR
        )
    )
    assert terminated["status"] == "TERMINATED"


def test_distributor_cannot_fill_another_accounts_allocation(api):
    """A non-owning Distributor is refused on both the fill and the read.

    "A `Distributor` reading or acting on an allocation whose `distributor_id`
    differs from `X-User-ID` — filling it, releasing it, reading the allocation
    itself, reading its lines, or reading an individual warranty claim — is
    refused with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    "When `X-User-Role` is `Distributor`, `X-User-ID` is the `id` of the acting
    distributor row."
    "Filling is the `Distributor`'s draw against finished stock, and it carries
    `expected_allocation_version` as described in §2.7."
    "Filling an allocation requires `expected_allocation_version` in the request
    body as a non-optional field, carrying the client's last observed `version`
    of the allocation."
    "A mismatch with the allocation's current `version` is rejected with
    `ERR_STALE_ALLOCATION_VERSION` (HTTP 412)."
    "The allocation's resulting `status` follows from the arithmetic: `FILLED`
    when `allocated_quantity_sqm` has reached `requested_quantity_sqm`,
    `PARTIALLY_FILLED` when it is above zero but short of the request, and `OPEN`
    when it is zero."

    Design: Corner/rbac/distributor_cannot_fill_another_accounts_allocation
    """
    built = build_open_allocation(api)
    allocation = built["allocation"]
    owner_headers = distributor_headers(built["distributor"]["id"])
    intruder = create_distributor(
        api, account_code="D-200", name="Southline Floors LLC"
    )
    intruder_headers = distributor_headers(intruder["id"])
    observed_version = allocation["version"]

    validate_error(
        api.fill_allocation(
            allocation["id"], fill_payload(observed_version), intruder_headers
        ),
        ApiErrorId.NOT_RESOURCE_OWNER.value,
    )
    validate_error(
        api.get_allocation(allocation["id"], intruder_headers),
        ApiErrorId.NOT_RESOURCE_OWNER.value,
    )

    # The owning distributor fills with the SAME observed version, so the two
    # refusals neither mutated the row nor consumed the version.
    filled = validate_success(
        api.fill_allocation(
            allocation["id"], fill_payload(observed_version), owner_headers
        )
    )
    assert filled["status"] == "FILLED"
    assert filled["allocated_quantity_sqm"] == 100.00


def test_distributor_cannot_create_an_allocation_for_another_account(api):
    """The body's distributor_id is ownership-checked on a Distributor create only.

    "The same code and status apply when a `Distributor` creates an allocation or
    files a warranty claim whose body carries a `distributor_id` other than its
    own."
    "`PlantAdmin` and the other operator roles are not subject to this ownership
    narrowing."
    "An allocation is a request for stock, created by a `Distributor` for its own
    account or by a `PlantAdmin` on a distributor's behalf."
    "The SKU must be `CERTIFIED` at creation time — an allocation may not be
    raised against a SKU that has never been certified or has lost
    certification, and the attempt is `ERR_SKU_NOT_PRODUCIBLE` (HTTP 409)."
    "A new allocation is `OPEN` with `allocated_quantity_sqm` and
    `upgrade_cost_total_cents` both 0."

    Design: Corner/rbac/distributor_cannot_create_an_allocation_for_another_account
    """
    built = build_certified_sku(api)
    sku_id = built["sku"]["id"]
    assert built["sku"]["certification_status"] == "CERTIFIED"
    owner = create_distributor(api)
    intruder = create_distributor(
        api, account_code="D-200", name="Southline Floors LLC"
    )
    intruder_headers = distributor_headers(intruder["id"])

    validate_error(
        api.create_allocation(
            allocation_payload(owner["id"], sku_id, allocation_code="ALLOC-X1"),
            intruder_headers,
        ),
        ApiErrorId.NOT_RESOURCE_OWNER.value,
    )
    rows, meta = validate_paginated(api.list_allocations(PLANT_ADMIN))
    assert rows == [], "the refused create must not have written ALLOC-X1"
    assert meta["total_count"] == 0

    # PlantAdmin may allocate on behalf of any account with the same body.
    on_behalf = validate_success(
        api.create_allocation(
            allocation_payload(owner["id"], sku_id, allocation_code="ALLOC-X2"),
            PLANT_ADMIN,
        ),
        201,
    )
    assert on_behalf["distributor_id"] == owner["id"]
    assert on_behalf["status"] == "OPEN"

    # The same Distributor may allocate for itself.
    own_account = validate_success(
        api.create_allocation(
            allocation_payload(intruder["id"], sku_id, allocation_code="ALLOC-X3"),
            intruder_headers,
        ),
        201,
    )
    assert own_account["distributor_id"] == intruder["id"]


def test_formulation_author_cannot_approve_their_own_recipe(api):
    """The recipe's author is refused on review; a second director approves it.

    "A recipe review decision is refused when `X-User-ID` equals the recipe's
    `authored_by_user_id`."
    "Authoring and approving are separated; submitting is not, so the same
    `Formulator` may author and submit."
    "All four return `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and all four are
    evaluated in band 9 — after concurrency and before any cross-entity state
    check."
    "For six of the seven roles — `PlantAdmin`, `Formulator`,
    `TechnicalDirector`, `QaTechnician`, `ProductionPlanner` and
    `WarrantyAdjuster` — `X-User-ID` is an opaque operator identifier that is not
    tied to any persisted entity."
    "A newly created recipe is `DRAFT` with `revision` 1, `cost_basis` `LIVE`,
    `rejection_count` and `open_revision_count` both 0, and
    `authored_by_user_id` set to the acting `X-User-ID`."
    "It is permitted only from `DRAFT`, taking the recipe `DRAFT → UNDER_REVIEW`,
    and it stamps `submitted_by_user_id` with the acting user."
    "Review is the `TechnicalDirector`'s decision, expressed as a `decision` of
    either approve or reject, with an optional `review_note` recorded alongside a
    rejection."
    "Rejection takes the recipe `UNDER_REVIEW → REJECTED` and increments
    `rejection_count` by one; nothing else moves, and the recipe remains
    editable, which is how the revision loop closes."
    "On approval the recipe moves `UNDER_REVIEW → APPROVED` and four things are
    written."
    "Third, `approved_by_user_id` is set to the acting user and `approved_at` to
    the logical clock."

    Design: Corner/rbac/formulation_author_cannot_approve_their_own_recipe
    """
    # The same opaque operator id acts as Formulator here and as
    # TechnicalDirector below, which the header contract permits.
    author_headers = build_user_headers(
        USER_IDS["technical_director"], UserRole.FORMULATOR.value
    )
    built = build_draft_formulation(api, "F-DUAL", headers=author_headers)
    recipe_id = built["formulation"]["id"]
    assert built["formulation"]["authored_by_user_id"] == USER_IDS["technical_director"]

    submitted = submit_formulation(api, recipe_id, author_headers)
    assert submitted["status"] == "UNDER_REVIEW"
    assert submitted["submitted_by_user_id"] == USER_IDS["technical_director"]

    # The author holds the TechnicalDirector role, so this is a duty-separation
    # failure and not an authorization failure.
    validate_error(
        api.review_formulation(
            recipe_id,
            review_decision_payload("APPROVE", review_note="Self approval attempt"),
            TECHNICAL_DIRECTOR,
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES.value,
    )
    # The rule keys on the endpoint, not on the decision.
    validate_error(
        api.review_formulation(
            recipe_id,
            review_decision_payload("REJECT", review_note="Self rejection attempt"),
            TECHNICAL_DIRECTOR,
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES.value,
    )
    untouched = validate_success(api.get_formulation(recipe_id, TECHNICAL_DIRECTOR))
    assert untouched["status"] == "UNDER_REVIEW"
    assert untouched["rejection_count"] == 0

    approved = validate_success(
        api.review_formulation(
            recipe_id,
            review_decision_payload("APPROVE", review_note="Independent review"),
            TECHNICAL_DIRECTOR_B,
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == USER_IDS["technical_director_b"]


def test_technical_director_who_recorded_a_result_cannot_certify_the_sku(api):
    """The director who took a qualifying reading is refused; another certifies.

    "SKU certification is refused when `X-User-ID` equals the
    `recorded_by_user_id` of any test measurement that is being counted toward
    that SKU's required-type coverage."
    "All four return `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and all four are
    evaluated in band 9 — after concurrency and before any cross-entity state
    check."
    "A measurement is created carrying the panel's `test_panel_id`, the
    `attempt_no` in force when it was taken, the `recorded_by_user_id` of the
    acting technician, and three server-computed fields: `unit`, `spec_limit` and
    `outcome`."
    "Otherwise, if coverage is complete and every outcome at that attempt is
    `PASS`, the panel moves `IN_TEST → PASSED`."
    "A panel that reaches `PASSED` whose coverage includes both
    `RESIDUAL_INDENTATION` and `DIMENSIONAL_STABILITY_HEAT` moves the SKU's
    certification `TESTING → PROVISIONAL`."
    "Certification is a `TechnicalDirector` action reachable from `TESTING` or
    `PROVISIONAL` — `certification_status` `TESTING → CERTIFIED` and
    `PROVISIONAL → CERTIFIED` are treated identically."
    "Any required type without such a qualifying measurement is
    `ERR_TEST_COVERAGE_INCOMPLETE` (HTTP 422), and as noted in §2.5 that error is
    returned even when the SKU's recipe has meanwhile been superseded."
    "The acting director must not have recorded any of the qualifying
    measurements (§2.8)."
    "`standard_cost_cents_per_sqm` is computed on the pinned basis described in
    §3.3 and stored, and `list_price_cents_per_sqm` is derived from it by the
    `target_margin_bps` gross-up."
    "`pin_stale` is set to false, `certified_at` to the logical clock and
    `certified_by_user_id` to the acting user."
    "The cost of a square metre is assembled from seven named components, each
    rounded half up to a whole cent on its own before any addition happens."
    "The core-compound component is the compound's blended cost per kilogram
    multiplied by 1.90 — the specific gravity in kilograms per square metre per
    millimetre — multiplied by the SKU's `overall_thickness_mm`."
    "The wear-layer component is `wear_layer_mil` multiplied by 3.5 cents per mil
    per square metre."
    "The print-film component is a base of 18 cents plus a repeat surcharge
    determined by the larger of the design's two pattern repeats: 6 cents when
    that larger repeat is at least 1800 millimetres, 2 cents when it is at least
    1200 but below 1800, and nothing below 1200."
    "The underlayment component is 0 cents for `NONE`, 22 for `IXPE_1MM`, 17 for
    `EVA_1_5MM` and 41 for `CORK_2MM`."
    "The waterproofing component is 9 cents when the SKU is `waterproof_rated`
    and zero otherwise."
    "The conversion component is a base of 35 cents plus 12 cents of click-lock
    milling when `construction_type` is `CLICK_LOCK_SPC` or `CLICK_LOCK_WPC`."
    "The seventh component is the royalty: the SKU's
    `royalty_basis_price_cents_per_sqm` multiplied by the governing grant's
    `royalty_rate_bps` divided by 10000, rounded half up to a whole cent."
    "`standard_cost_cents_per_sqm` is the exact integer sum of those seven
    rounded integers, and `list_price_cents_per_sqm` is that standard cost
    multiplied by the quantity 10000 plus `target_margin_bps`, divided by 10000,
    rounded half up to a whole cent."
    "Add those products together, divide the total by `total_phr`, and round half
    up to a whole cent."
    "Second, the recipe's `cost_basis` flips to `PINNED` and
    `blended_cost_per_kg_cents` is re-derived from those snapshots rather than
    from live material costs."

    Design: Corner/rbac/technical_director_who_recorded_a_result_cannot_certify_the_sku
    """
    # One opaque operator id records the laboratory readings as a QaTechnician
    # and then tries to certify as a TechnicalDirector.
    recorder_headers = build_user_headers(
        USER_IDS["technical_director_b"], UserRole.QA_TECHNICIAN.value
    )
    built = build_sku(api)
    sku_id = built["sku"]["id"]
    begin_testing(api, sku_id)
    panel_built = build_passed_panel(api, sku_id, headers=recorder_headers)

    assert panel_built["panel"]["status"] == "PASSED"
    for result in panel_built["results"]:
        assert result["recorded_by_user_id"] == USER_IDS["technical_director_b"]
        assert result["outcome"] == "PASS"
    provisional = validate_success(api.get_product_sku(sku_id, PLANT_ADMIN))
    assert provisional["certification_status"] == "PROVISIONAL"

    # Coverage is complete — which is precisely why the conflict is detectable.
    validate_error(
        api.certify_sku(sku_id, TECHNICAL_DIRECTOR_B),
        ApiErrorId.SEGREGATION_OF_DUTIES.value,
    )

    certified = validate_success(api.certify_sku(sku_id, TECHNICAL_DIRECTOR))
    assert certified["certification_status"] == "CERTIFIED"
    assert certified["certified_by_user_id"] == USER_IDS["technical_director"]
    # 955 core (201 * 1.90 * 2.50) + 42 wear layer + 20 print film + 0
    # underlayment + 0 waterproofing + 35 conversion + 105 royalty.
    assert certified["standard_cost_cents_per_sqm"] == 1157


def test_qa_technician_cannot_release_a_hold_they_placed_themselves(api):
    """The technician who quarantined stock cannot return it to sale.

    "Releasing a batch hold is refused when `X-User-ID` equals the batch's
    `held_by_user_id`."
    "All four return `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and all four are
    evaluated in band 9 — after concurrency and before any cross-entity state
    check."
    "Stock holds are the `QaTechnician`'s direct control over finished
    inventory, driven by an `action` of `HOLD`, `RELEASE_HOLD` or `SCRAP` with an
    optional `hold_reason`."
    "Holding requires the batch to be `IN_STOCK`, releasing requires it to be
    `HELD`, and scrapping requires any non-`SCRAPPED` batch; a mismatch is
    `ERR_INVALID_BATCH_STATE` (HTTP 409)."
    "`IN_STOCK → HELD` records `held_by_user_id` as the acting user — or the
    string `system` when the transition arrived through a SKU-hold cascade rather
    than an operator action — and voids every `ACTIVE` allocation line on the
    batch with `void_reason` `BATCH_HELD`, adding each line's `quantity_sqm` back
    to `available_quantity_sqm` and stepping the owning allocations back as
    above."
    "The acting user may not be the batch's `held_by_user_id` (§2.8)."
    "The producing run's `qc_disposition` must be `RELEASED`, or the release is
    `ERR_RUN_NOT_RELEASED` (HTTP 409)."
    "Releasing moves the run's batch `IN_PRODUCTION → IN_STOCK` (or `HELD →
    IN_STOCK` when the batch was quarantined earlier) and sets
    `available_quantity_sqm` to the full `quantity_sqm`."
    "Releasing clears `hold_reason` and `held_by_user_id` and recomputes
    `available_quantity_sqm` as `quantity_sqm` less the sum of the `ACTIVE`
    allocation-line quantities still drawn on the batch — not as the full
    quantity, because lines placed before the hold may still stand."

    Design: Corner/rbac/qa_technician_cannot_release_a_hold_they_placed_themselves
    """
    built = build_stock_batch(api)
    batch_id = built["batch"]["id"]
    in_stock = validate_success(api.get_batch(batch_id, QA_TECHNICIAN))
    assert in_stock["status"] == "IN_STOCK"
    assert in_stock["available_quantity_sqm"] == 1200.00
    assert built["run"]["qc_disposition"] == "RELEASED"

    held = set_batch_hold(
        api,
        batch_id,
        "HOLD",
        QA_TECHNICIAN,
        hold_reason="Customer complaint sample pulled",
    )
    assert held["status"] == "HELD"
    assert held["held_by_user_id"] == USER_IDS["qa_technician"]

    # The batch is in the correct HELD state and its run is RELEASED, so only the
    # holder's identity blocks the release.
    validate_error(
        api.set_batch_hold_status(
            batch_id, hold_status_payload("RELEASE_HOLD"), QA_TECHNICIAN
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES.value,
    )
    still_held = validate_success(api.get_batch(batch_id, QA_TECHNICIAN))
    assert still_held["status"] == "HELD"
    assert still_held["held_by_user_id"] == USER_IDS["qa_technician"]

    released = validate_success(
        api.set_batch_hold_status(
            batch_id, hold_status_payload("RELEASE_HOLD"), QA_TECHNICIAN_B
        )
    )
    assert released["status"] == "IN_STOCK"
    # No allocation line was ever drawn on this batch.
    assert released["available_quantity_sqm"] == 1200.00
    assert released["held_by_user_id"] is None
    assert released["hold_reason"] is None


def test_triaging_adjuster_cannot_adjudicate_the_claim_they_own(api):
    """The adjuster stamped at triage may record reviews but not decide the claim.

    "Warranty adjudication is refused when `X-User-ID` equals the claim's
    `assigned_adjuster_user_id` — that is, the adjuster who triaged the claim may
    record its branch reviews but may not decide it."
    "All four return `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and all four are
    evaluated in band 9 — after concurrency and before any cross-entity state
    check."
    "Triage is a `WarrantyAdjuster` action taking the claim `SUBMITTED →
    TRIAGE`."
    "Triage stamps `assigned_adjuster_user_id` with the acting adjuster and
    **forks** the investigation by setting `required_reviews`: a `DELAMINATION`
    or `LOCK_FAILURE` claim requires both a materials review and a field review,
    while a `WEAR_LAYER_WEARTHROUGH` or `DIMENSIONAL_MOVEMENT` claim requires the
    field review only."
    "The claim stays in `TRIAGE` while any required arm is unanswered; the
    instant every required arm carries a non-null outcome, the claim joins
    `TRIAGE → ADJUDICATION_READY`."
    "The claim must be `ADJUDICATION_READY`, and the acting adjuster may not be
    the one who triaged it (§2.8)."
    "An approval takes it `ADJUDICATION_READY → APPROVED` and requires two
    further things: every required review outcome must be `DEFECT_CONFIRMED`, and
    any arm answered `NO_DEFECT` or `INCONCLUSIVE` makes the approval
    `ERR_REVIEW_OUTCOME_CONFLICT` (HTTP 409); and the warranty coverage must not
    be exhausted."
    "`elapsed_months` is the number of whole calendar months from `installed_on`
    to `reported_on`, floored, so a partial month does not count."
    "The coverage term is the SKU's `warranty_years` multiplied by 12, and an
    approval whose `elapsed_months` has reached or passed that figure is refused
    with `ERR_WARRANTY_EXPIRED` (HTTP 409) before any settlement is computed — a
    claim at exactly the coverage boundary has no remaining months and is
    expired."
    "The residential term is 25 years when `wear_layer_mil` is at least 20, 20
    years when it is at least 12 but below 20, 15 years when it is at least 6 but
    below 12, and 10 years otherwise."
    "The `replacement_value_cents` is the `claimed_area_sqm` multiplied by the
    SKU's `royalty_basis_price_cents_per_sqm`, rounded half up to a whole cent."
    "The `labor_allowance_cents` is the `claimed_area_sqm` multiplied by 350
    cents per square metre, rounded half up to a whole cent, when
    `installed_by_certified_installer` is true, and 0 otherwise."
    "The decay of the replacement value depends on the `claim_type`, and the
    chosen variant is recorded in `settlement_variant`."
    "A `DELAMINATION` or `LOCK_FAILURE` claim uses `STEPPED_SCHEDULE`: take the
    elapsed whole years as `elapsed_months` divided by twelve rounded down, then
    apply 100 percent when that figure is 1 or less, 80 percent when it is 2 or
    3, 60 percent when it is 4 through 7, 40 percent when it is 8 through 12, and
    20 percent beyond that, rounding the result half up to a whole cent."
    "A **manufacturing defect** is confirmed when the batch's
    `wear_layer_measured_mil` is strictly less than the SKU's specified
    `wear_layer_mil` minus 0.5 mil — the tolerance the plant accepts on
    wear-layer thickness."
    "The `settlement_amount_cents` is the covered value plus the
    `labor_allowance_cents`, added as two already-rounded integers."

    Design: Corner/rbac/triaging_adjuster_cannot_adjudicate_the_claim_they_own
    """
    built = build_stock_batch(api)
    distributor = create_distributor(api)
    set_clock(api, "2029-08-05T00:00:00Z")
    claim = create_claim(
        api,
        built["batch"]["id"],
        distributor["id"],
        WARRANTY_ADJUSTER,
        claim_code="WC-SOD",
        claim_type="DELAMINATION",
    )
    assert claim["status"] == "SUBMITTED"

    triaged = triage_claim(api, claim["id"], WARRANTY_ADJUSTER)
    assert triaged["status"] == "TRIAGE"
    # Stamped by the triage call, not supplied in any payload.
    assert triaged["assigned_adjuster_user_id"] == USER_IDS["warranty_adjuster"]
    assert set(triaged["required_reviews"]) == {"MATERIALS", "FIELD"}

    # Recording both branch reviews is permitted to the triaging adjuster.
    record_review(api, claim["id"], "MATERIALS", "DEFECT_CONFIRMED", WARRANTY_ADJUSTER)
    answered = record_review(
        api, claim["id"], "FIELD", "DEFECT_CONFIRMED", WARRANTY_ADJUSTER
    )
    assert answered["status"] == "ADJUDICATION_READY"
    assert answered["materials_review_outcome"] == "DEFECT_CONFIRMED"
    assert answered["field_review_outcome"] == "DEFECT_CONFIRMED"

    # The claim is fully adjudicable, so only the adjuster's identity refuses it.
    validate_error(
        api.adjudicate_warranty_claim(
            claim["id"], adjudication_payload("APPROVE"), WARRANTY_ADJUSTER
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES.value,
    )

    # SKU-A specifies wear_layer_mil 12 and the batch measured 12.0, which is not
    # strictly less than 11.5, so no manufacturing-defect override applies.
    assert built["sku"]["wear_layer_mil"] == 12
    assert built["batch"]["wear_layer_measured_mil"] == 12.0

    approved = validate_success(
        api.adjudicate_warranty_claim(
            claim["id"], adjudication_payload("APPROVE"), WARRANTY_ADJUSTER_B
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["elapsed_months"] == 36
    assert approved["settlement_variant"] == "STEPPED_SCHEDULE"
    # 25.50 sqm * 2100 cents.
    assert approved["replacement_value_cents"] == 53550
    assert approved["labor_allowance_cents"] == 0
    # 3 elapsed whole years takes the 80 percent step: 80% of 53550, plus 0.
    assert approved["settlement_amount_cents"] == 42840
