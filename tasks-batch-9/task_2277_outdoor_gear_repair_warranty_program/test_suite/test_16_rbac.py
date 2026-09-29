"""Role-based access: exclusive operations, cross-role refusals and ownership.

PRD §2.1 makes role capability an endpoint-by-endpoint fact and adds one rule on
top of it for customers — a `Customer` may only reach their own gear. The tests
below walk a paid repair through the five roles that each exclusively own a step
of it, then show every cross-role attempt refused with no side effect, then show
two customers treated as peers rather than as a hierarchy.
"""

from test_helpers import (
    ERR_NOT_RESOURCE_OWNER,
    ERR_ROLE_NOT_PERMITTED,
    PARTS_COORDINATOR_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    SERVICE_AGENT_HEADERS,
    assert_center_posture,
    factories,
    make_customer_headers,
    make_technician_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_INSTANT = "2026-06-15T09:00:00Z"

# The zipper lane: one 35-minute line at 9500 cents an hour plus 1800 cents of
# parts, quoted to a PRO owner. Both totals are fixed by PRD §3.4 and §3.7.
ASSESSMENT_COST_CENTS = 7730
QUOTE_TOTAL_CENTS = 7531

ZIPPER_CERTIFICATION = [factories.certification("ZIPPER", 3)]


def _paid_repair_world(api):
    """Build a PAID_REPAIR order carrying one SENT provisional quote.

    Every setup call is made by a role the PRD §4 table authorises for it, so
    the world itself is legitimate and only the triggers are cross-role.
    """
    validate_success(api.set_clock(CLOCK_INSTANT, PROGRAM_ADMIN_HEADERS))
    center = validate_success(
        api.create_service_center(
            factories.service_center_payload(), PROGRAM_ADMIN_HEADERS
        ),
        201,
    )
    model = validate_success(
        api.create_gear_model(factories.gear_model_payload(), PROGRAM_ADMIN_HEADERS),
        201,
    )
    lot = validate_success(
        api.create_part_lot(
            factories.part_lot_payload(
                model["id"],
                part_code=factories.ZIP_PART_CODE,
                part_kind="ZIPPER_SLIDER",
                on_hand_units=4,
                unit_price_cents=1800,
                low_watermark_units=1,
            ),
            PARTS_COORDINATOR_HEADERS,
        ),
        201,
    )
    customer = validate_success(
        api.create_customer(factories.customer_payload(), SERVICE_AGENT_HEADERS), 201
    )
    item = validate_success(
        api.create_gear_item(
            factories.gear_item_payload(model["id"], customer["id"]),
            SERVICE_AGENT_HEADERS,
        ),
        201,
    )
    technician = validate_success(
        api.create_technician(
            factories.technician_payload(
                center["id"], certifications=ZIPPER_CERTIFICATION
            ),
            PROGRAM_ADMIN_HEADERS,
        ),
        201,
    )
    claim = validate_success(
        api.create_warranty_claim(
            factories.warranty_claim_payload(
                center["id"],
                item["id"],
                intake_kind="PAID_REPAIR_REQUEST",
                reported_defect_type="ZIPPER_FAILURE",
                customer_narrative="Slider chewed after a fall.",
            ),
            SERVICE_AGENT_HEADERS,
        ),
        201,
    )
    submitted = validate_success(api.submit_claim(claim["id"], SERVICE_AGENT_HEADERS))
    validate_success(
        api.create_assessment(
            claim["id"],
            factories.assessment_payload(
                submitted["version"],
                determination="USER_DAMAGE",
                required_work_types=["ZIPPER"],
                estimated_labor_lines=[factories.labor_line("ZIPPER", 35)],
                estimated_parts_cents=1800,
                defect_notes="Impact damage.",
            ),
            make_technician_headers(technician["id"]),
        ),
        201,
    )
    validate_success(api.decide_claim(claim["id"], SERVICE_AGENT_HEADERS, {}))
    order = validate_success(
        api.create_repair_order(
            factories.repair_order_payload(claim["id"]), SERVICE_AGENT_HEADERS
        ),
        201,
    )
    estimate = validate_success(
        api.create_estimate(
            order["id"],
            factories.estimate_payload(
                order["version"],
                labor_lines=[factories.labor_line("ZIPPER", 35)],
                parts_lines=[factories.parts_line(factories.ZIP_PART_CODE, 1, 1800)],
            ),
            SERVICE_AGENT_HEADERS,
        ),
        201,
    )
    return {
        "center": center,
        "model": model,
        "lot": lot,
        "customer": customer,
        "item": item,
        "technician": technician,
        "claim": claim,
        "claim_version": submitted["version"],
        "order": order,
        "estimate": estimate,
    }


class TestEachRoleExercisesItsOwnExclusiveOperations:
    """PRD §4 — one paid-repair walk through all five roles' own operations."""

    def test_one_paid_repair_walk_exercises_every_role_s_own_operations(self, api):
        """Each step is taken by the single role the endpoint table authorises.

        "Role capability is per endpoint."
        "Each endpoint in §4 lists the roles permitted to invoke it; a
        syntactically valid role that is not in that list yields
        `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        "Otherwise `on_hand_units` changes by `delta_units`, `available_units`
        is recomputed, the lot's `status` is re-derived — which is how a
        `DEPLETED` lot climbs back to `LOW` or `AVAILABLE` and closes the
        inventory cycle — and the model's `parts_support_status` is re-derived."
        "A `ServiceAgent` may issue an information request with a `reason`,
        moving the claim from either `SUBMITTED` or `UNDER_ASSESSMENT` into
        `INFO_REQUESTED` and increasing `info_request_count` by one."
        "The `assessor_technician_id` is never accepted from the body: the
        server stamps it from `X-User-ID`."
        "From those inputs the server computes `estimated_repair_cost_cents` on
        the assessment row using the labour block of the paid-repair pricing
        rule described in §3.7 — that is, the per-line rounded labour charges
        summed into a labour subtotal, plus `estimated_parts_cents` used
        directly as the parts subtotal, plus the capped shop supply fee."
        "If it is `USER_DAMAGE`, the outcome is `PAID_REPAIR_OFFERED` — the
        customer broke it, and the brand will happily fix it for money."
        "Whatever the outcome, the claim records `decision`,
        `decision_threshold_pct`, `repair_ratio_pct`, `decision_by_role` — set
        to `ServiceAgent` or `ProgramAdmin` according to the acting role — and
        `decided_at` from the logical clock."
        "A `PAID_REPAIR_OFFERED` outcome moves the claim `UNDER_ASSESSMENT` →
        `PAID_REPAIR_OFFERED` and stamps `decision`, `decided_at` and
        `decision_by_role`."
        "No liability entry is created and the centre's `open_liability_cents`
        is unchanged, because the brand carries no exposure on work the
        customer pays for."
        "The order's `order_kind` follows the claim's `decision`:
        `WARRANTY_REPAIR` when the claim decided on warranty repair, and
        `PAID_REPAIR` when it offered paid repair."
        "**Step eight** totals: `total_cents` is `subtotal_cents` minus
        `loyalty_discount_cents` plus `expedite_fee_cents` plus `tax_cents`."
        "The customer answers a quote themselves — approval and decline are the
        two operations reserved exclusively to the `Customer` role, and the
        caller's `X-User-ID` must equal the unit's `owner_customer_id`."
        "On approval the estimate moves `SENT` → `APPROVED`, its `decided_at`
        is stamped, the order's `provisional_estimate_total_cents` is set from
        the estimate's `total_cents`, and the order's `billing_status` moves
        `ESTIMATE_SENT` → `ESTIMATE_APPROVED` — which is the moment the bench
        dimension is unlocked and `QUEUED` → `IN_WORK` becomes reachable."
        "Its `status` begins as `ACTIVE` and becomes `RETIRED` once a
        queue-review observes that its `end_date` has fallen behind the logical
        clock."

        Design: Corner/rbac/each_role_exercises_its_own_exclusive_operations
        """
        # --- ProgramAdmin: the clock, the centre, the catalogue, the bench ---
        validate_success(api.set_clock(CLOCK_INSTANT, PROGRAM_ADMIN_HEADERS))
        center = validate_success(
            api.create_service_center(
                factories.service_center_payload(), PROGRAM_ADMIN_HEADERS
            ),
            201,
        )
        model = validate_success(
            api.create_gear_model(
                factories.gear_model_payload(), PROGRAM_ADMIN_HEADERS
            ),
            201,
        )
        technician = validate_success(
            api.create_technician(
                factories.technician_payload(
                    center["id"], certifications=ZIPPER_CERTIFICATION
                ),
                PROGRAM_ADMIN_HEADERS,
            ),
            201,
        )

        # --- ServiceAgent registers the owner, the owner registers their gear ---
        customer = validate_success(
            api.create_customer(factories.customer_payload(), SERVICE_AGENT_HEADERS),
            201,
        )
        owner = make_customer_headers(customer["id"])
        item = validate_success(
            api.create_gear_item(
                factories.gear_item_payload(model["id"], customer["id"]), owner
            ),
            201,
        )
        claim = validate_success(
            api.create_warranty_claim(
                factories.warranty_claim_payload(
                    center["id"],
                    item["id"],
                    intake_kind="PAID_REPAIR_REQUEST",
                    reported_defect_type="ZIPPER_FAILURE",
                    customer_narrative="Slider chewed after a fall.",
                ),
                owner,
            ),
            201,
        )
        validate_success(api.submit_claim(claim["id"], owner))

        # --- PartsCoordinator stocks and restocks the zipper lot ---
        lot = validate_success(
            api.create_part_lot(
                factories.part_lot_payload(
                    model["id"],
                    part_code=factories.ZIP_PART_CODE,
                    part_kind="ZIPPER_SLIDER",
                    on_hand_units=4,
                    unit_price_cents=1800,
                    low_watermark_units=1,
                ),
                PARTS_COORDINATOR_HEADERS,
            ),
            201,
        )
        adjusted = validate_success(
            api.adjust_part_lot(
                lot["id"],
                {"delta_units": 2, "reason": "Restock from the vendor pallet."},
                PARTS_COORDINATOR_HEADERS,
            )
        )
        assert adjusted["on_hand_units"] == 6, adjusted
        assert adjusted["reserved_units"] == 0, adjusted
        assert adjusted["available_units"] == 6, adjusted

        # --- ServiceAgent asks for documents, the owner answers ---
        info_requested = validate_success(
            api.create_info_request(
                claim["id"],
                {"reason": "Send a photo of the slider."},
                SERVICE_AGENT_HEADERS,
            )
        )
        assert info_requested["status"] == "INFO_REQUESTED", info_requested
        assert info_requested["info_request_count"] == 1, info_requested

        resubmitted = validate_success(
            api.resubmit_claim(
                claim["id"], {"customer_narrative": "Photo attached."}, owner
            )
        )

        # --- RepairTechnician records the bench finding ---
        assessment = validate_success(
            api.create_assessment(
                claim["id"],
                factories.assessment_payload(
                    resubmitted["version"],
                    determination="USER_DAMAGE",
                    required_work_types=["ZIPPER"],
                    estimated_labor_lines=[factories.labor_line("ZIPPER", 35)],
                    estimated_parts_cents=1800,
                    defect_notes="Impact damage.",
                ),
                make_technician_headers(technician["id"]),
            ),
            201,
        )
        assert assessment["assessor_technician_id"] == technician["id"], assessment
        assert assessment["determination"] == "USER_DAMAGE", assessment
        assert assessment["estimated_repair_cost_cents"] == ASSESSMENT_COST_CENTS, (
            assessment
        )

        # --- ServiceAgent adjudicates, opens the order and quotes it ---
        decided = validate_success(api.decide_claim(claim["id"], SERVICE_AGENT_HEADERS))
        assert decided["decision"] == "PAID_REPAIR_OFFERED", decided
        assert decided["decision_by_role"] == "ServiceAgent", decided
        assert decided["status"] == "PAID_REPAIR_OFFERED", decided
        assert_center_posture(
            validate_success(
                api.get_service_center(center["id"], PROGRAM_ADMIN_HEADERS)
            ),
            0,
        )

        order = validate_success(
            api.create_repair_order(
                factories.repair_order_payload(claim["id"]), SERVICE_AGENT_HEADERS
            ),
            201,
        )
        assert order["order_kind"] == "PAID_REPAIR", order

        estimate = validate_success(
            api.create_estimate(
                order["id"],
                factories.estimate_payload(
                    order["version"],
                    labor_lines=[factories.labor_line("ZIPPER", 35)],
                    parts_lines=[
                        factories.parts_line(factories.ZIP_PART_CODE, 1, 1800)
                    ],
                ),
                SERVICE_AGENT_HEADERS,
            ),
            201,
        )
        assert estimate["total_cents"] == QUOTE_TOTAL_CENTS, estimate
        quoted = validate_success(
            api.get_repair_order(order["id"], SERVICE_AGENT_HEADERS)
        )
        assert quoted["billing_status"] == "ESTIMATE_SENT", quoted

        # --- Customer answers the quote: the one operation reserved to them ---
        approved = validate_success(api.approve_estimate(estimate["id"], owner))
        assert approved["status"] == "APPROVED", approved
        assert approved["decided_at"].startswith("2026-06-15T09:00:00"), approved
        settled = validate_success(
            api.get_repair_order(order["id"], SERVICE_AGENT_HEADERS)
        )
        assert settled["billing_status"] == "ESTIMATE_APPROVED", settled
        assert settled["provisional_estimate_total_cents"] == QUOTE_TOTAL_CENTS, settled

        # --- ProgramAdmin declares seasonal capacity ---
        window = validate_success(
            api.create_surge_window(
                center["id"],
                factories.surge_window_payload(
                    label="July peak",
                    start_date="2026-07-01T00:00:00Z",
                    end_date="2026-07-31T23:59:59Z",
                    multiplier=1.25,
                ),
                PROGRAM_ADMIN_HEADERS,
            ),
            201,
        )
        assert window["status"] == "ACTIVE", window


class TestCrossRoleExclusiveOperationsAreForbidden:
    """PRD §2.11 check 4 — the endpoint's role list refuses before any state rule."""

    def test_five_cross_role_attempts_are_refused_with_no_side_effect(self, api):
        """Every borrowed operation is 403 and leaves the world exactly as it was.

        "Role capability is per endpoint."
        "Each endpoint in §4 lists the roles permitted to invoke it; a
        syntactically valid role that is not in that list yields
        `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        "Every request runs the same ordered gauntlet, and the **first** check
        that fails produces the response — no later check is evaluated, so a
        request that violates several rules always reports the earliest one."
        "Only a `RepairTechnician` may record a **bench assessment**, and doing
        so is the transition `SUBMITTED` → `UNDER_ASSESSMENT`, or the self-loop
        `UNDER_ASSESSMENT` → `UNDER_ASSESSMENT` when the bench re-assesses."
        "The customer answers a quote themselves — approval and decline are the
        two operations reserved exclusively to the `Customer` role, and the
        caller's `X-User-ID` must equal the unit's `owner_customer_id`."
        "The new row is created, the claim's `assessment_count` increases by
        one, and the claim's `latest_determination` and
        `latest_repair_cost_cents` are overwritten from the new row's
        `determination` and `estimated_repair_cost_cents`."
        "The new row's `valid_until` is the logical clock instant advanced by
        seven days, and its `decided_at` is null until the customer answers."
        "The unit moves `AT_CENTER` → `IN_REPAIR`, and the order's bench
        dimension begins at `QUEUED` with `commitment_breached` false,
        `qc_fail_count` at 0, `paid_amount_cents` at 0, and `released_at`,
        `provisional_estimate_total_cents` and `final_invoice_total_cents` all
        null."

        Design: Corner/rbac/cross_role_exclusive_operations_are_forbidden
        """
        world = _paid_repair_world(api)
        agent = SERVICE_AGENT_HEADERS
        technician_headers = make_technician_headers(world["technician"]["id"])
        owner = make_customer_headers(world["customer"]["id"])

        # Stocking a lot belongs to PartsCoordinator / ProgramAdmin.
        validate_error(
            api.create_part_lot(factories.part_lot_payload(world["model"]["id"]), agent),
            ERR_ROLE_NOT_PERMITTED,
        )
        # Opening a repair order belongs to ServiceAgent alone.
        validate_error(
            api.create_repair_order(
                factories.repair_order_payload(world["claim"]["id"]),
                PARTS_COORDINATOR_HEADERS,
            ),
            ERR_ROLE_NOT_PERMITTED,
        )
        # Declaring a surge window belongs to ProgramAdmin alone.
        validate_error(
            api.create_surge_window(
                world["center"]["id"],
                factories.surge_window_payload(
                    label="Unauthorised surge",
                    start_date="2026-07-01T00:00:00Z",
                    end_date="2026-07-31T23:59:59Z",
                    multiplier=1.25,
                ),
                technician_headers,
            ),
            ERR_ROLE_NOT_PERMITTED,
        )
        # Recording a bench assessment belongs to RepairTechnician alone — even
        # for the owner of the very unit on the bench.
        validate_error(
            api.create_assessment(
                world["claim"]["id"],
                factories.assessment_payload(
                    world["claim_version"],
                    determination="MANUFACTURING_DEFECT",
                    required_work_types=["ZIPPER"],
                    estimated_labor_lines=[factories.labor_line("ZIPPER", 35)],
                    estimated_parts_cents=1800,
                    defect_notes=factories.OMIT,
                ),
                owner,
            ),
            ERR_ROLE_NOT_PERMITTED,
        )
        # Approving the quote belongs to the Customer alone, even though this
        # quote is otherwise perfectly approvable.
        validate_error(
            api.approve_estimate(world["estimate"]["id"], agent),
            ERR_ROLE_NOT_PERMITTED,
        )

        # --- nothing was written by any of the five refusals ---
        lots, lots_meta = validate_paginated(
            api.list_part_lots(agent, gear_model_id=world["model"]["id"])
        )
        assert lots_meta["total_count"] == 1, lots
        assert lots[0]["part_code"] == factories.ZIP_PART_CODE, lots

        orders, orders_meta = validate_paginated(
            api.list_repair_orders(agent, warranty_claim_id=world["claim"]["id"])
        )
        assert orders_meta["total_count"] == 1, orders
        assert orders[0]["id"] == world["order"]["id"], orders

        _, windows_meta = validate_paginated(
            api.list_surge_windows(world["center"]["id"], PROGRAM_ADMIN_HEADERS)
        )
        assert windows_meta["total_count"] == 0, windows_meta

        _, assessments_meta = validate_paginated(
            api.list_claim_assessments(agent, warranty_claim_id=world["claim"]["id"])
        )
        assert assessments_meta["total_count"] == 1, assessments_meta
        claim = validate_success(api.get_warranty_claim(world["claim"]["id"], agent))
        assert claim["assessment_count"] == 1, claim
        assert claim["latest_determination"] == "USER_DAMAGE", claim

        estimate = validate_success(api.get_estimate(world["estimate"]["id"], agent))
        assert estimate["status"] == "SENT", estimate
        assert estimate["decided_at"] is None, estimate
        order = validate_success(api.get_repair_order(world["order"]["id"], agent))
        assert order["billing_status"] == "ESTIMATE_SENT", order
        assert order["provisional_estimate_total_cents"] is None, order


class TestCustomerCannotReachAnotherOwnersResources:
    """PRD §2.11 check 5 — two customers are peers, not a hierarchy."""

    def test_a_peer_customer_is_refused_on_another_owner_s_rows(self, api):
        """Tam is 403 on Rowan's claim, order and quote, yet reads their own row.

        "Beyond the endpoint list, a `Customer` may only reach their own gear."
        "Whenever a `Customer` addresses an existing resource, the server walks
        from that resource to the gear unit behind it — directly for a unit,
        through the claim's referenced unit for a claim, through the order's
        referenced unit for a repair order, and through the estimate's
        referenced order and then that order's unit for an estimate — and
        compares the unit's `owner_customer_id` to `X-User-ID`."
        "A mismatch is `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
        "Every request runs the same ordered gauntlet, and the **first** check
        that fails produces the response — no later check is evaluated, so a
        request that violates several rules always reports the earliest one."
        "A `loyalty_tier` may be supplied and defaults to `STANDARD`; the only
        other value is `PRO`, and the tier is what earns a discount on paid
        work."
        "A new customer starts with `lifetime_claim_count` and
        `trade_in_credit_cents` at 0."
        "The new row's `valid_until` is the logical clock instant advanced by
        seven days, and its `decided_at` is null until the customer answers."
        "The customer answers a quote themselves — approval and decline are the
        two operations reserved exclusively to the `Customer` role, and the
        caller's `X-User-ID` must equal the unit's `owner_customer_id`."
        "**Step five** applies loyalty: `loyalty_discount_cents` is
        `subtotal_cents` multiplied by the owner's tier rate, rounded half up,
        where a `STANDARD` owner's rate is zero percent and a `PRO` owner's
        rate is ten percent."
        "On approval the estimate moves `SENT` → `APPROVED`, its `decided_at`
        is stamped, the order's `provisional_estimate_total_cents` is set from
        the estimate's `total_cents`, and the order's `billing_status` moves
        `ESTIMATE_SENT` → `ESTIMATE_APPROVED` — which is the moment the bench
        dimension is unlocked and `QUEUED` → `IN_WORK` becomes reachable."

        Design: Corner/rbac/customer_cannot_reach_another_owners_claim_or_estimate
        """
        world = _paid_repair_world(api)
        tam = validate_success(
            api.create_customer(
                factories.customer_payload(
                    full_name="Tam Ito", email="tam@example.com",
                    loyalty_tier="STANDARD",
                ),
                SERVICE_AGENT_HEADERS,
            ),
            201,
        )
        tam_headers = make_customer_headers(tam["id"])
        rowan_headers = make_customer_headers(world["customer"]["id"])

        validate_error(
            api.get_warranty_claim(world["claim"]["id"], tam_headers),
            ERR_NOT_RESOURCE_OWNER,
        )
        validate_error(
            api.get_repair_order(world["order"]["id"], tam_headers),
            ERR_NOT_RESOURCE_OWNER,
        )
        validate_error(
            api.approve_estimate(world["estimate"]["id"], tam_headers),
            ERR_NOT_RESOURCE_OWNER,
        )

        untouched = validate_success(
            api.get_estimate(world["estimate"]["id"], SERVICE_AGENT_HEADERS)
        )
        assert untouched["status"] == "SENT", untouched
        assert untouched["decided_at"] is None, untouched
        order = validate_success(
            api.get_repair_order(world["order"]["id"], SERVICE_AGENT_HEADERS)
        )
        assert order["billing_status"] == "ESTIMATE_SENT", order

        own_record = validate_success(api.get_customer(tam["id"], tam_headers))
        assert own_record["full_name"] == "Tam Ito", own_record
        assert own_record["loyalty_tier"] == "STANDARD", own_record
        assert own_record["lifetime_claim_count"] == 0, own_record

        approved = validate_success(
            api.approve_estimate(world["estimate"]["id"], rowan_headers)
        )
        assert approved["status"] == "APPROVED", approved
        assert approved["decided_at"].startswith("2026-06-15T09:00:00"), approved
        settled = validate_success(
            api.get_repair_order(world["order"]["id"], SERVICE_AGENT_HEADERS)
        )
        assert settled["billing_status"] == "ESTIMATE_APPROVED", settled
        assert settled["provisional_estimate_total_cents"] == QUOTE_TOTAL_CENTS, settled
