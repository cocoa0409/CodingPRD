"""Cross-entity state dependency coverage: a write blocked by a *neighbour* entity's state.

Three entity pairs are exercised, and each one is translated in two phases —
the same request body refused while the depended-upon entity sits in the wrong
state, then accepted once that other entity (and nothing about the request)
has moved:

  * RepairOrder <- WarrantyClaim: `POST /gear-service/repair-orders` is refused
    with `ERR_INVALID_CLAIM_STATE` while the claim is still `UNDER_ASSESSMENT`
    and accepted once adjudication moves it to `WARRANTY_APPROVED`
    (PRD §2.11 check 11, §3.6).
  * WorkBlock <- Technician: `POST /gear-service/work-blocks` naming a
    technician who has been patched to `ON_LEAVE` is refused with
    `ERR_TECHNICIAN_NOT_ACTIVE`, while the identical interval is accepted for
    an `ACTIVE` technician (PRD §2.11 check 20, §3.1, §3.8).
  * WarrantyClaim <- ServiceCenter: `POST /gear-service/warranty-claims/{id}/decision`
    resolving to a warranty repair is refused with `ERR_CENTER_LIABILITY_FROZEN`
    while the owning centre's derived posture is `FROZEN`, and accepted once a
    release unwinds the centre's open exposure (PRD §2.11 check 23, §2.9, §3.9).

Every precondition is built inside the test through the PRD §4 endpoints,
because the server is restarted against an empty database before each test.
"""

from test_helpers import (
    ERR_CENTER_LIABILITY_FROZEN,
    ERR_INVALID_CLAIM_STATE,
    ERR_TECHNICIAN_NOT_ACTIVE,
    SCENARIO_CLOCK_UTC,
    SERVICE_AGENT_HEADERS,
    World,
    assert_center_posture,
    assert_claim_decision,
    assert_no_row_created,
    factories,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

BLOCK_START_AT = "2026-06-16T09:00:00Z"
BLOCK_END_AT = "2026-06-16T11:00:00Z"
SERIAL_C = "AS2-00419"


def _build_frozen_center_world(scenario) -> World:
    """A centre whose cap is 22000 cents, frozen by one warranty-repair approval.

    Both units are serial AS2-00417 / AS2-00418 on the Ascent 2P tent, bought
    2023-05-10 for 74900 cents with the logical clock pinned to
    2026-06-15T09:00:00Z. Claim A is already approved as a warranty repair, so
    its OPEN `REPAIR` entry reserves 22390 cents against a 22000-cent ceiling;
    claim B carries the identical `MANUFACTURING_DEFECT` finding over a single
    120-minute `FABRIC` lane and is still awaiting adjudication.
    """
    scenario.set_clock(SCENARIO_CLOCK_UTC)
    center = scenario.center(liability_cap_cents=22000)
    model = scenario.model()
    panel_lot = scenario.part_lot(model["id"], on_hand_units=5, low_watermark_units=2)
    customer = scenario.customer()
    item_a = scenario.gear_item(
        model["id"], customer["id"], serial_number=factories.SERIAL_A
    )
    item_b = scenario.gear_item(
        model["id"],
        customer["id"],
        serial_number=factories.SERIAL_B,
        proof_of_purchase_ref="POS-88214",
    )
    technician = scenario.technician(
        center["id"],
        employee_code="T-101",
        full_name="Ines Park",
        certifications=[factories.certification("FABRIC", 3)],
    )
    second_technician = scenario.technician(
        center["id"],
        employee_code="T-102",
        full_name="Dev Osei",
        certifications=[factories.certification("FABRIC", 2)],
    )

    claim_a = scenario.claim(
        center["id"], item_a["id"], customer_narrative="Floor seam split on 417."
    )
    submitted_a = scenario.submit(claim_a["id"])
    scenario.assess(
        claim_a["id"], technician["id"], expected_claim_version=submitted_a["version"]
    )
    decided_a = scenario.decide(claim_a["id"])

    claim_b = scenario.claim(
        center["id"], item_b["id"], customer_narrative="Floor seam split on 418."
    )
    submitted_b = scenario.submit(claim_b["id"])
    scenario.assess(
        claim_b["id"],
        technician["id"],
        expected_claim_version=submitted_b["version"],
        defect_notes="Same factory bond line failure.",
    )

    return World(
        scenario=scenario,
        center_id=center["id"],
        model_id=model["id"],
        panel_lot_id=panel_lot["id"],
        customer_id=customer["id"],
        item_a_id=item_a["id"],
        item_b_id=item_b["id"],
        technician_id=technician["id"],
        second_technician_id=second_technician["id"],
        claim_a=decided_a,
        claim_a_id=claim_a["id"],
        claim_b_id=claim_b["id"],
    )


class TestRepairOrderCreationRequiresDecidedClaim:
    """RepairOrder <- WarrantyClaim: only an adjudicated claim may carry an order."""

    def test_order_refused_while_its_claim_is_still_under_assessment(
        self, api, agent_headers, assessed_claim
    ):
        """An order on an UNDER_ASSESSMENT claim is refused and mints nothing at all.

        "(11) A claim's `status` is a legal origin state for the requested claim transition, else `ERR_INVALID_CLAIM_STATE` (409); this guards claim submit, information request, resubmit, assessment recording, adjudication and repair-order creation."
        "The unit moves `AT_CENTER` → `IN_REPAIR`, and the order's bench dimension begins at `QUEUED` with `commitment_breached` false, `qc_fail_count` at 0, `paid_amount_cents` at 0, and `released_at`, `provisional_estimate_total_cents` and `final_invoice_total_cents` all null."

        Design: Difficulty/cross_entity_state_dependency/repair_order_creation_requires_decided_claim
        """
        scenario = assessed_claim.scenario
        claim = scenario.read_claim(assessed_claim.claim_id)
        assert claim["status"] == "UNDER_ASSESSMENT", claim
        assert claim["decision"] is None, claim

        response = api.create_repair_order(
            factories.repair_order_payload(assessed_claim.claim_id), agent_headers
        )
        validate_error(response, ERR_INVALID_CLAIM_STATE)

        rows, meta = validate_paginated(
            api.list_repair_orders(
                agent_headers, warranty_claim_id=assessed_claim.claim_id
            )
        )
        assert_no_row_created(rows)
        assert meta["total_count"] == 0, meta

        item = scenario.read_item(assessed_claim.item_id)
        assert item["disposition_status"] == "AT_CENTER", item

        unchanged = scenario.read_claim(assessed_claim.claim_id)
        assert unchanged["status"] == "UNDER_ASSESSMENT", unchanged
        assert unchanged["version"] == claim["version"], unchanged

    def test_identical_order_body_accepted_once_the_claim_is_decided(
        self, api, agent_headers, assessed_claim
    ):
        """The same POST body succeeds after the decision moves the claim to WARRANTY_APPROVED.

        "(11) A claim's `status` is a legal origin state for the requested claim transition, else `ERR_INVALID_CLAIM_STATE` (409); this guards claim submit, information request, resubmit, assessment recording, adjudication and repair-order creation."
        "A `WARRANTY_REPAIR` outcome moves the claim `UNDER_ASSESSMENT` → `WARRANTY_APPROVED` and opens the brand's exposure in a three-hop cascade."
        "The order copies `service_center_id` and `gear_item_id` from the claim rather than accepting them from the body, and copies `required_work_types` from the claim's newest non-superseded assessment."
        "The unit moves `AT_CENTER` → `IN_REPAIR`, and the order's bench dimension begins at `QUEUED` with `commitment_breached` false, `qc_fail_count` at 0, `paid_amount_cents` at 0, and `released_at`, `provisional_estimate_total_cents` and `final_invoice_total_cents` all null."
        "A warranty order is minted with `billing_status` `NOT_BILLABLE`, which is already terminal in the money dimension — a warranty order is never quoted, never invoiced and never paid, and any attempt to issue an estimate on it is refused with `ERR_INVALID_BILLING_STATE`."

        Design: Difficulty/cross_entity_state_dependency/repair_order_creation_requires_decided_claim
        """
        scenario = assessed_claim.scenario
        payload = factories.repair_order_payload(assessed_claim.claim_id)

        blocked = api.create_repair_order(payload, agent_headers)
        validate_error(blocked, ERR_INVALID_CLAIM_STATE)

        decided = scenario.decide(
            assessed_claim.claim_id, decision_note="Defect confirmed."
        )
        assert_claim_decision(decided, "WARRANTY_REPAIR", "WARRANTY_APPROVED")

        order = validate_success(api.create_repair_order(payload, agent_headers), 201)
        assert order["warranty_claim_id"] == assessed_claim.claim_id, order
        assert order["work_status"] == "QUEUED", order
        assert order["billing_status"] == "NOT_BILLABLE", order
        assert order["required_work_types"] == ["FABRIC"], order
        assert order["service_center_id"] == assessed_claim.center_id, order
        assert order["gear_item_id"] == assessed_claim.item_id, order
        assert order["commitment_breached"] is False, order
        assert order["qc_fail_count"] == 0, order

        item = scenario.read_item(assessed_claim.item_id)
        assert item["disposition_status"] == "IN_REPAIR", item

        rows, meta = validate_paginated(
            api.list_repair_orders(
                agent_headers, warranty_claim_id=assessed_claim.claim_id
            )
        )
        assert meta["total_count"] == 1, meta
        assert [row["id"] for row in rows] == [order["id"]], rows


class TestWorkBlockRequiresActiveTechnician:
    """WorkBlock <- Technician: bench time may only be booked on an ACTIVE roster row."""

    def test_block_refused_for_a_technician_patched_to_on_leave(
        self, api, agent_headers, admin_headers, open_order
    ):
        """Naming an ON_LEAVE technician is refused and books no minutes and no block.

        "(20) The acting technician, or the `technician_id` named in the body, has a roster `status` of `ACTIVE`, else `ERR_TECHNICIAN_NOT_ACTIVE` (422); this guards assessment recording, work-block scheduling, bench-complete and quality-control inspection."
        "When `technician_id` is supplied explicitly, that technician must have roster `status` `ACTIVE`, must belong to the order's centre, must hold a certification for the block's `work_type` at or above that lane's minimum level, and must have no block already in `status` `SCHEDULED` overlapping the requested half-open interval — a conflict is refused with `ERR_TECHNICIAN_WINDOW_CONFLICT`."
        "Patching a technician may change the roster `status` or replace the `certifications` matrix; a technician moved to `ON_LEAVE` or `INACTIVE` drops out of the routing candidate pool immediately, while blocks already scheduled for them are left untouched."

        Design: Difficulty/cross_entity_state_dependency/work_block_requires_active_technician
        """
        scenario = open_order.scenario
        assert scenario.read_order(open_order.order_id)["work_status"] == "QUEUED"

        patched = get_success_data(
            api.patch_technician(
                open_order.technician_id, {"status": "ON_LEAVE"}, admin_headers
            )
        )
        assert patched["status"] == "ON_LEAVE", patched

        payload = factories.work_block_payload(
            open_order.order_id,
            work_type="FABRIC",
            start_at=BLOCK_START_AT,
            end_at=BLOCK_END_AT,
            technician_id=open_order.technician_id,
        )
        response = api.create_work_block(payload, agent_headers)
        validate_error(response, ERR_TECHNICIAN_NOT_ACTIVE)

        technician = scenario.read_technician(open_order.technician_id)
        assert technician["status"] == "ON_LEAVE", technician
        assert technician["scheduled_minutes_open"] == 0, technician

        rows, meta = validate_paginated(
            api.list_work_blocks(agent_headers, repair_order_id=open_order.order_id)
        )
        assert_no_row_created(rows)
        assert meta["total_count"] == 0, meta

        order = scenario.read_order(open_order.order_id)
        assert order["work_status"] == "QUEUED", order

    def test_identical_interval_accepted_for_the_still_active_technician(
        self, api, agent_headers, admin_headers, open_order
    ):
        """The refused interval books cleanly against the ACTIVE T-102 in the same sequence.

        "(20) The acting technician, or the `technician_id` named in the body, has a roster `status` of `ACTIVE`, else `ERR_TECHNICIAN_NOT_ACTIVE` (422); this guards assessment recording, work-block scheduling, bench-complete and quality-control inspection."
        "On success the block's `duration_minutes` is the whole number of minutes between `start_at` and `end_at`, its `status` is `SCHEDULED`, its `actual_minutes` is null, the assigned technician's `scheduled_minutes_open` increases by `duration_minutes`, and — if this is the first block on the order — the order's `work_status` moves `QUEUED` → `IN_WORK`."
        "The winner is stamped onto the block's `technician_id` and the block's `routed_by_selector` flag is set to true; a block whose technician was supplied by the caller keeps `routed_by_selector` false."

        Design: Difficulty/cross_entity_state_dependency/work_block_requires_active_technician
        """
        scenario = open_order.scenario
        get_success_data(
            api.patch_technician(
                open_order.technician_id, {"status": "ON_LEAVE"}, admin_headers
            )
        )

        blocked = api.create_work_block(
            factories.work_block_payload(
                open_order.order_id,
                work_type="FABRIC",
                start_at=BLOCK_START_AT,
                end_at=BLOCK_END_AT,
                technician_id=open_order.technician_id,
            ),
            agent_headers,
        )
        validate_error(blocked, ERR_TECHNICIAN_NOT_ACTIVE)

        accepted = validate_success(
            api.create_work_block(
                factories.work_block_payload(
                    open_order.order_id,
                    work_type="FABRIC",
                    start_at=BLOCK_START_AT,
                    end_at=BLOCK_END_AT,
                    technician_id=open_order.second_technician_id,
                ),
                agent_headers,
            ),
            201,
        )
        assert accepted["status"] == "SCHEDULED", accepted
        assert accepted["technician_id"] == open_order.second_technician_id, accepted
        assert accepted["duration_minutes"] == 120, accepted
        assert accepted["routed_by_selector"] is False, accepted
        assert accepted["actual_minutes"] is None, accepted

        active = scenario.read_technician(open_order.second_technician_id)
        assert active["scheduled_minutes_open"] == 120, active
        on_leave = scenario.read_technician(open_order.technician_id)
        assert on_leave["scheduled_minutes_open"] == 0, on_leave

        order = scenario.read_order(open_order.order_id)
        assert order["work_status"] == "IN_WORK", order

    def test_same_request_accepted_once_the_technician_returns_to_active(
        self, api, agent_headers, admin_headers, open_order
    ):
        """Patching the roster row back to ACTIVE makes the byte-identical block succeed.

        "(20) The acting technician, or the `technician_id` named in the body, has a roster `status` of `ACTIVE`, else `ERR_TECHNICIAN_NOT_ACTIVE` (422); this guards assessment recording, work-block scheduling, bench-complete and quality-control inspection."
        "Patching a technician may change the roster `status` or replace the `certifications` matrix; a technician moved to `ON_LEAVE` or `INACTIVE` drops out of the routing candidate pool immediately, while blocks already scheduled for them are left untouched."
        "On success the block's `duration_minutes` is the whole number of minutes between `start_at` and `end_at`, its `status` is `SCHEDULED`, its `actual_minutes` is null, the assigned technician's `scheduled_minutes_open` increases by `duration_minutes`, and — if this is the first block on the order — the order's `work_status` moves `QUEUED` → `IN_WORK`."

        Design: Difficulty/cross_entity_state_dependency/work_block_requires_active_technician
        """
        scenario = open_order.scenario
        payload = factories.work_block_payload(
            open_order.order_id,
            work_type="FABRIC",
            start_at=BLOCK_START_AT,
            end_at=BLOCK_END_AT,
            technician_id=open_order.technician_id,
        )

        get_success_data(
            api.patch_technician(
                open_order.technician_id, {"status": "ON_LEAVE"}, admin_headers
            )
        )
        validate_error(
            api.create_work_block(payload, agent_headers), ERR_TECHNICIAN_NOT_ACTIVE
        )

        restored = get_success_data(
            api.patch_technician(
                open_order.technician_id, {"status": "ACTIVE"}, admin_headers
            )
        )
        assert restored["status"] == "ACTIVE", restored

        block = validate_success(api.create_work_block(payload, agent_headers), 201)
        assert block["technician_id"] == open_order.technician_id, block
        assert block["status"] == "SCHEDULED", block
        assert block["duration_minutes"] == 120, block
        assert block["routed_by_selector"] is False, block

        technician = scenario.read_technician(open_order.technician_id)
        assert technician["scheduled_minutes_open"] == 120, technician

        order = scenario.read_order(open_order.order_id)
        assert order["work_status"] == "IN_WORK", order


class TestWarrantyDecisionBlockedByFrozenCenterPosture:
    """WarrantyClaim <- ServiceCenter: a FROZEN posture refuses warranty generosity."""

    def test_frozen_posture_refuses_the_warranty_adjudication_of_a_second_claim(
        self, api, scenario
    ):
        """With 22390 open against a 22000 cap the centre is FROZEN and claim B is refused.

        "If `open_liability_cents` is strictly greater than `liability_cap_cents`, the posture is `FROZEN`."
        "`liability_utilization_pct` is one hundred multiplied by `open_liability_cents` divided by `liability_cap_cents`, rounded half up to two decimal places, and is display-only."
        "(23) The centre's `liability_posture` is not `FROZEN` when the adjudication resolves to a warranty repair or a warranty replacement, else `ERR_CENTER_LIABILITY_FROZEN` (409); paid-repair and wear-denial outcomes are always permitted."
        "Separately, the model's `defect_claim_count` increases by one and its `repairability_flag` is then re-derived from the updated counters."

        Design: Difficulty/cross_entity_state_dependency/warranty_decision_blocked_by_frozen_center_posture
        """
        world = _build_frozen_center_world(scenario)

        before = scenario.read_center(world.center_id)
        assert_center_posture(before, 22390, 101.77, "FROZEN")

        response = api.decide_claim(
            world.claim_b_id,
            SERVICE_AGENT_HEADERS,
            {"decision_note": "Second defect on the same model."},
        )
        validate_error(response, ERR_CENTER_LIABILITY_FROZEN)

        claim_b = scenario.read_claim(world.claim_b_id)
        assert claim_b["status"] == "UNDER_ASSESSMENT", claim_b
        assert claim_b["decision"] is None, claim_b
        assert claim_b["decided_at"] is None, claim_b

        assert_no_row_created(scenario.liability_entries(world.claim_b_id))

        after = scenario.read_center(world.center_id)
        assert_center_posture(after, 22390, 101.77, "FROZEN")

        model = scenario.read_model(world.model_id)
        assert model["defect_claim_count"] == 1, model

    def test_same_decision_accepted_once_a_release_unwinds_the_frozen_posture(
        self, api, scenario
    ):
        """Releasing claim A's repaired unit clears the exposure, and claim B then adjudicates.

        "(23) The centre's `liability_posture` is not `FROZEN` when the adjudication resolves to a warranty repair or a warranty replacement, else `ERR_CENTER_LIABILITY_FROZEN` (409); paid-repair and wear-denial outcomes are always permitted."
        "For a warranty order the claim's open liability entry with `basis` `REPAIR` moves `OPEN` → `RELEASED` with `release_reason` `ORDER_RELEASED` and `released_at` stamped, the centre's `open_liability_cents` decreases by the released amount, and `liability_posture` is re-derived — which is how a centre unwinds from `FROZEN` back toward `OPEN`."
        "A `WARRANTY_REPAIR` outcome moves the claim `UNDER_ASSESSMENT` → `WARRANTY_APPROVED` and opens the brand's exposure in a three-hop cascade."

        Design: Difficulty/cross_entity_state_dependency/warranty_decision_blocked_by_frozen_center_posture
        """
        world = _build_frozen_center_world(scenario)
        decision_body = {"decision_note": "Second defect on the same model."}

        blocked = api.decide_claim(
            world.claim_b_id, SERVICE_AGENT_HEADERS, decision_body
        )
        validate_error(blocked, ERR_CENTER_LIABILITY_FROZEN)

        # Work claim A's warranty order through to release: the only movement is on
        # the centre, whose open exposure is given back when the unit goes home.
        order = scenario.repair_order(world.claim_a_id)
        block = scenario.work_block(
            order["id"],
            world.technician_id,
            work_type="FABRIC",
            start_at=BLOCK_START_AT,
            end_at=BLOCK_END_AT,
        )
        scenario.bench_complete(
            order["id"],
            world.technician_id,
            [factories.work_log_entry(block["id"], 120)],
        )
        scenario.qc(order["id"], world.second_technician_id)
        scenario.release_to_customer(order["id"])

        unfrozen = scenario.read_center(world.center_id)
        assert_center_posture(unfrozen, 0, 0.0, "OPEN")

        accepted = validate_success(
            api.decide_claim(world.claim_b_id, SERVICE_AGENT_HEADERS, decision_body)
        )
        assert_claim_decision(accepted, "WARRANTY_REPAIR", "WARRANTY_APPROVED")

        entries = scenario.liability_entries(world.claim_b_id)
        assert len(entries) == 1, entries
        assert entries[0]["status"] == "OPEN", entries[0]
        assert entries[0]["basis"] == "REPAIR", entries[0]
        assert entries[0]["reserved_amount_cents"] == 22390, entries[0]

        refrozen = scenario.read_center(world.center_id)
        assert_center_posture(refrozen, 22390, 101.77, "FROZEN")

        model = scenario.read_model(world.model_id)
        assert model["defect_claim_count"] == 2, model

    def test_frozen_posture_still_permits_the_wear_driven_paid_repair_outcome(
        self, api, scenario
    ):
        """The same FROZEN centre adjudicates a NORMAL_WEAR claim into PAID_REPAIR_OFFERED.

        "(23) The centre's `liability_posture` is not `FROZEN` when the adjudication resolves to a warranty repair or a warranty replacement, else `ERR_CENTER_LIABILITY_FROZEN` (409); paid-repair and wear-denial outcomes are always permitted."
        "Under `FROZEN`, both warranty outcomes — repair and replacement — are refused with `ERR_CENTER_LIABILITY_FROZEN`, while the two outcomes that cost the brand nothing, a paid-repair offer and a wear denial, remain available."
        "If it is `NORMAL_WEAR`, the outcome depends on the stockroom: `WEAR_DENIED` when the model's `parts_support_status` is `NO_SUPPORT`, and `PAID_REPAIR_OFFERED` otherwise."
        "A `PAID_REPAIR_OFFERED` outcome moves the claim `UNDER_ASSESSMENT` → `PAID_REPAIR_OFFERED` and stamps `decision`, `decided_at` and `decision_by_role`."
        "No liability entry is created and the centre's `open_liability_cents` is unchanged, because the brand carries no exposure on work the customer pays for."
        "This outcome is available under every posture, `FROZEN` included."

        Design: Difficulty/cross_entity_state_dependency/warranty_decision_blocked_by_frozen_center_posture
        """
        world = _build_frozen_center_world(scenario)
        assert scenario.read_center(world.center_id)["liability_posture"] == "FROZEN"
        assert scenario.read_model(world.model_id)["parts_support_status"] == "SUPPORTED"

        validate_error(
            api.decide_claim(
                world.claim_b_id, SERVICE_AGENT_HEADERS, {"decision_note": "Defect."}
            ),
            ERR_CENTER_LIABILITY_FROZEN,
        )

        wear_item = scenario.gear_item(
            world.model_id,
            world.customer_id,
            serial_number=SERIAL_C,
            proof_of_purchase_ref="POS-88215",
        )
        wear_claim = scenario.claim(
            world.center_id,
            wear_item["id"],
            reported_defect_type="ABRASION_WEAR",
            customer_narrative="Floor abraded through after four seasons of gravel pads.",
        )
        submitted = scenario.submit(wear_claim["id"])
        scenario.assess(
            wear_claim["id"],
            world.technician_id,
            expected_claim_version=submitted["version"],
            determination="NORMAL_WEAR",
            defect_notes="Abrasion consistent with ordinary use, not a defect.",
        )

        decided = validate_success(
            api.decide_claim(
                wear_claim["id"],
                SERVICE_AGENT_HEADERS,
                {"decision_note": "Wear, but parts are on the shelf: quote paid work."},
            )
        )
        assert decided["status"] == "PAID_REPAIR_OFFERED", decided
        assert decided["decided_at"] is not None, decided
        assert decided["decision_by_role"] == "ServiceAgent", decided

        assert_no_row_created(scenario.liability_entries(wear_claim["id"]))

        center = scenario.read_center(world.center_id)
        assert_center_posture(center, 22390, 101.77, "FROZEN")
