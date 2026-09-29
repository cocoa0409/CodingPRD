"""Role gates on the warranty ladder and the customer's own scope.

PRD.md section 3.9 splits one claim across three principals: the
``WarrantyAgent`` reviews, prices and decides, the ``PlantAdmin`` holds the two
administrative overrides, and the ``Customer`` may only open and withdraw its
own file. PRD.md section 2.1 adds that the customer's every read and write is
confined to rows carrying its own identifier. Both tests below drive the wrong
principal at each edge, and one drives a second customer at the first one's
rows.
"""

from test_helpers import (
    ApiErrorId,
    acknowledge_storage_guidance_payload,
    advance_unit_to_outfitted,
    approve_claim_payload,
    assert_warranty_reserve_conserved,
    assert_instant_equals,
    build_user_headers,
    customer_payload,
    inspect_payload,
    molding_cycle_payload,
    outfit_payload,
    production_order_version,
    return_to_queue_payload,
    setup_claim_storage_violated,
    setup_sellable_units,
    setup_submitted_claim,
    suspend_payload,
    technician_payload,
    validate_error,
    validate_paginated,
    validate_success,
    void_claim_payload,
    waive_storage_finding_payload,
    warranty_claim_payload,
    withdraw_claim_payload,
)


def test_warranty_adjudication_is_split_across_agent_admin_and_customer(
    api, admin_headers, planner_headers, warranty_agent_headers
):
    """Six wrong-principal calls on one claim all answer 403 and move nothing.

    PRD.md section 2.1: "**WarrantyAgent** ... handles hull-deformation,
    hardware and cosmetic warranty claims: intake, review, the independent
    storage-guidance review, approval against the model's reserve, denial and
    return-to-queue. Identity opaque. Cannot waive its own storage finding and
    cannot void an approval; both of those are reserved to `PlantAdmin`."
    PRD.md section 2.1: "**Customer** ... Acknowledges storage guidance for
    itself, submits claims restricted to its own `customer_id`, and may withdraw
    its own claim, but never prices or decides one."
    PRD.md section 3.9: "**Waiving a storage finding** is reserved to
    `PlantAdmin` and carries a `waiver_note`."
    PRD.md section 3.9: "**Voiding** an approved claim is a `PlantAdmin` action
    carrying a `void_reason`."
    PRD.md section 3.9: "**Withdrawing** is the claimant's own escape hatch."
    PRD.md section 3.1: "Suspending a customer requires a `suspend_reason` and
    `status` `ACTIVE`."
    PRD.md section 2.7: "Authentication and authorization come first ... then a
    role that is not permitted on the endpoint. ... **Resource and lifecycle
    state** — the status of the target row."

    Design: Corner/rbac/rbac_warranty_adjudication_split_across_agent_admin_and_customer
    """
    ctx = setup_claim_storage_violated()
    claim_id = ctx["warranty_claim_id"]
    before = api.read_entity("get_warranty_claim", claim_id, warranty_agent_headers)
    assert before["claim_status"] == "UNDER_REVIEW", "the claim opens this test in review"
    assert before["storage_review_status"] == "GUIDANCE_VIOLATED", (
        "with a storage finding that a PlantAdmin could genuinely waive"
    )
    model_version = api.read_version(
        "get_product_model", ctx["product_model_id"], admin_headers
    )

    validate_error(
        api.approve_warranty_claim(
            claim_id, approve_claim_payload(model_version), planner_headers
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.waive_storage_finding(
            claim_id, waive_storage_finding_payload(), warranty_agent_headers
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.void_warranty_claim(claim_id, void_claim_payload(), warranty_agent_headers),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.withdraw_warranty_claim(
            claim_id, withdraw_claim_payload(), warranty_agent_headers
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.start_claim_review(claim_id, ctx["customer_headers"]),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.suspend_customer(
            ctx["customer_id"], suspend_payload(), warranty_agent_headers
        ),
        ApiErrorId.ROLE_NOT_PERMITTED,
    )

    after = api.read_entity("get_warranty_claim", claim_id, warranty_agent_headers)
    assert after["claim_status"] == "UNDER_REVIEW", (
        "no refusal moved the adjudication axis, and the void refusal in "
        "particular answered on the role gate rather than on the claim not "
        "being APPROVED"
    )
    assert after["storage_review_status"] == "GUIDANCE_VIOLATED", (
        "the agent could not waive the finding it recorded itself"
    )
    assert after["version"] == before["version"], (
        "and no refusal consumed a version, because a rejected request writes "
        "nothing at all"
    )
    model = api.read_entity("get_product_model", ctx["product_model_id"], admin_headers)
    assert model["warranty_reserve_cents"] == 500000, (
        "the planner's approve never reached the pricing step, so the reserve "
        "is untouched"
    )
    assert model["warranty_paid_cents"] == 0, "and nothing was paid"
    assert_warranty_reserve_conserved(model)
    customer = api.read_entity("get_customer", ctx["customer_id"], admin_headers)
    assert customer["status"] == "ACTIVE", (
        "suspension is reserved to PlantAdmin, so the agent's attempt left the "
        "claimant active and its open claim unvoided"
    )
    assert_instant_equals(
        customer["storage_guidance_acknowledged_at"],
        "2026-08-01T00:00:00Z",
        "and the acknowledgement it made before delivery still stands",
    )
    requeued = validate_success(
        api.return_claim_to_queue(
            claim_id, return_to_queue_payload(), warranty_agent_headers
        )
    )
    assert requeued["claim_status"] == "SUBMITTED", (
        "the same agent identity that was refused four times above does carry "
        "the return-to-queue edge, which pins those refusals on the endpoint's "
        "role list rather than on the identity or the row"
    )


def test_customer_scope_confines_reads_and_writes_to_its_own_rows(
    api, admin_headers, warranty_agent_headers
):
    """A second, equally active customer is refused on every one of the first one's rows.

    PRD.md section 2.1: "The `Customer` role is scoped: every read and every
    write it performs must target rows whose `customer_id` equals its own
    identifier, and a claim, hull or shipment belonging to another customer is
    refused with `ERR_CUSTOMER_SCOPE_VIOLATION` (HTTP 403)."
    PRD.md section 3.9: "When the caller's role is `Customer`, the submitted
    `customer_id` must equal the acting `X-User-ID`, otherwise
    `ERR_CUSTOMER_SCOPE_VIOLATION` (HTTP 403)."
    PRD.md section 3.9: "Claims may be listed and filtered by
    `finished_unit_id`, `customer_id`, `claim_type`, `claim_status`,
    `storage_review_status` and `denial_reason`; a `Customer` reading claims
    sees only its own."
    PRD.md section 3.9: "A `Customer` may withdraw a claim from either
    `SUBMITTED` or `UNDER_REVIEW`, giving a `withdraw_reason`; the acting
    `X-User-ID` must equal the claim's `customer_id`, otherwise
    `ERR_CUSTOMER_SCOPE_VIOLATION`."
    PRD.md section 3.1: "Acknowledging the hull storage guidance — permitted to
    `PlantAdmin`, `LogisticsPlanner` or the `Customer` acting on its own record
    — stores an explicit `acknowledged_at` instant into
    `storage_guidance_acknowledged_at`."

    Design: Corner/rbac/rbac_customer_scope_confines_reads_and_writes_to_its_own_rows
    """
    ctx = setup_submitted_claim()
    claim_id = ctx["warranty_claim_id"]
    owner_id = ctx["customer_id"]

    stranger = validate_success(
        api.create_customer(customer_payload(), admin_headers), 201
    )
    assert stranger["status"] == "ACTIVE", (
        "the second customer is itself in good standing, so nothing about its "
        "own state explains the refusals below"
    )
    stranger_headers = build_user_headers(stranger["id"], "Customer")

    owned = validate_success(api.get_warranty_claim(claim_id, ctx["customer_headers"]))
    assert owned["customer_id"] == owner_id, "the owner reads its own claim"

    validate_error(
        api.get_warranty_claim(claim_id, stranger_headers),
        ApiErrorId.CUSTOMER_SCOPE_VIOLATION,
    )
    stranger_claims, stranger_meta = validate_paginated(
        api.list_warranty_claims(None, stranger_headers)
    )
    assert stranger_meta["total_count"] == 0, (
        "the scoped list filters to the acting customer's own rows rather than "
        "refusing, so a customer with no claims sees an empty page"
    )
    assert stranger_claims == [], "and the page carries no rows at all"

    validate_error(
        api.withdraw_warranty_claim(
            claim_id, withdraw_claim_payload(), stranger_headers
        ),
        ApiErrorId.CUSTOMER_SCOPE_VIOLATION,
    )
    validate_error(
        api.acknowledge_storage_guidance(
            owner_id,
            acknowledge_storage_guidance_payload("2026-08-02T09:00:00Z"),
            stranger_headers,
        ),
        ApiErrorId.CUSTOMER_SCOPE_VIOLATION,
    )
    validate_error(
        api.create_warranty_claim(
            warranty_claim_payload(ctx["unit_id"], owner_id), stranger_headers
        ),
        ApiErrorId.CUSTOMER_SCOPE_VIOLATION,
    )

    untouched = api.read_entity("get_warranty_claim", claim_id, warranty_agent_headers)
    assert untouched["claim_status"] == "SUBMITTED", (
        "the stranger's withdraw wrote nothing"
    )
    owner_row = api.read_entity("get_customer", owner_id, admin_headers)
    assert_instant_equals(
        owner_row["storage_guidance_acknowledged_at"],
        "2026-08-01T00:00:00Z",
        "and the stranger's acknowledgement did not restamp the owner's record",
    )
    _, all_claims_meta = validate_paginated(
        api.list_warranty_claims(None, warranty_agent_headers)
    )
    assert all_claims_meta["total_count"] == 1, (
        "the stranger's intake naming the owner as claimant wrote no second claim"
    )

    withdrawn = validate_success(
        api.withdraw_warranty_claim(
            claim_id, withdraw_claim_payload(), ctx["customer_headers"]
        )
    )
    assert withdrawn["claim_status"] == "WITHDRAWN", (
        "the identical withdraw succeeds for the owner, so the refusal above "
        "turned on row ownership alone"
    )


def test_the_role_code_gate_shadows_the_segregation_of_duties_gate(api, admin_headers):
    """An inspector's identity cannot reach the two roles segregation guards.

    PRD.md section 2.1: "Asserting one shop-floor role with the identifier of a
    technician carrying a different `role_code` fails with
    `ERR_ROLE_IDENTITY_MISMATCH` (HTTP 403)."
    PRD.md section 2.1: "Segregation of duties is enforced at inspection and
    outfitting time and is reported as `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
    Concretely: the inspecting technician may not be the producing cycle's
    `operator_technician_id`, may not be the hull's
    `outfitted_by_technician_id`, and an outfitting technician may not be a
    prior inspector of the same hull."
    PRD.md section 3.6: "`inspected_by_technician_id` is stamped with the acting
    identifier."
    PRD.md section 2.7 band 1: "header presence, role validity, endpoint
    permission, identity resolution, role/identity agreement, customer scope."

    Design: Corner/rbac/rbac_role_code_identity_shadows_the_segregation_of_duties_gate
    """
    ctx = setup_sellable_units(unit_count=1)
    second_unit = ctx["finished_units"][1]
    advance_unit_to_outfitted(ctx, second_unit)

    second_inspector = validate_success(
        api.create_technician(technician_payload("QUALITY_INSPECTOR"), admin_headers),
        201,
    )
    assert second_inspector["role_code"] == "QUALITY_INSPECTOR", (
        "the fresh technician is registered as an inspector"
    )
    second_inspector_headers = build_user_headers(
        second_inspector["id"], "QualityInspector"
    )
    inspector_as_operator = build_user_headers(
        ctx["quality_inspector_id"], "MoldingOperator"
    )
    inspector_as_assembly = build_user_headers(
        ctx["quality_inspector_id"], "AssemblyTechnician"
    )

    validate_error(
        api.create_molding_cycle(
            molding_cycle_payload(
                ctx["production_order_id"],
                ctx["oven_station_id"],
                ctx["cooling_bay_id"],
                production_order_version(ctx["production_order_id"]),
                arm_index=2,
                oven_start_at="2026-08-01T13:00:00Z",
            ),
            inspector_as_operator,
        ),
        ApiErrorId.ROLE_IDENTITY_MISMATCH,
    )
    validate_error(
        api.outfit_finished_unit(
            second_unit["id"], outfit_payload(), inspector_as_assembly
        ),
        ApiErrorId.ROLE_IDENTITY_MISMATCH,
    )

    still_outfitted = api.read_entity(
        "get_finished_unit", second_unit["id"], admin_headers
    )
    assert still_outfitted["outfitted_by_technician_id"] == ctx["assembly_technician_id"], (
        "the refused outfit did not restamp the hull, so an inspector identity "
        "can never become outfitted_by_technician_id and can never trip the "
        "outfitter half of the segregation rule"
    )

    inspected = validate_success(
        api.inspect_finished_unit(
            second_unit["id"], inspect_payload(), second_inspector_headers
        )
    )
    assert inspected["inspection_verdict"] == "PASS", (
        "a properly backed inspector who is neither the operator nor the "
        "outfitter passes the hull"
    )
    assert inspected["build_status"] == "SELLABLE", "and the build axis advances"
    assert inspected["inspected_by_technician_id"] == second_inspector["id"], (
        "stamped with the acting identifier"
    )
    assert inspected["inspected_by_technician_id"] != ctx["molding_operator_id"], (
        "who is not the producing cycle's operator"
    )
    assert inspected["inspected_by_technician_id"] != ctx["assembly_technician_id"], (
        "and not the hull's outfitter, so segregation of duties holds"
    )
