"""Claim and bench state machines — initial states, guarded edges, cycles.

Covers the WarrantyClaim lifecycle of PRD §3.3 - §3.5, the terminal
disposition lockdown of PRD §2.11 check 17, and the RepairOrder quality-control
cycle of PRD §3.8 together with the condemnation cascade of PRD §3.9.
"""

from test_helpers import (
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_CLAIM_STATE,
    assert_center_posture,
    assert_claim_decision,
    factories,
    get_success_data,
    make_customer_headers,
    make_technician_headers,
    validate_error,
)

CLOCK_INSTANT_PREFIX = "2026-06-15T09:00:00"


def _build_own_msrp_world(scenario, *, stock_panel_lot):
    """Centre, a catalogue model that names no successor, an owner, a unit, two techs.

    The model deliberately carries neither `discontinued_at` nor
    `successor_model_id`, so the unit's successor-MSRP valuation reads the
    model's own `msrp_cents` of 79900 (PRD §2.8).
    """
    scenario.set_clock()
    center = scenario.center()
    model = scenario.model()
    panel_lot = scenario.part_lot(model["id"]) if stock_panel_lot else None
    customer = scenario.customer()
    item = scenario.gear_item(model["id"], customer["id"])
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
    return {
        "center_id": center["id"],
        "model_id": model["id"],
        "panel_lot": panel_lot,
        "customer_id": customer["id"],
        "item_id": item["id"],
        "technician_id": technician["id"],
        "second_technician_id": second_technician["id"],
    }


class TestWarrantyClaimStateMachine:
    """Intake, submit and the origin-state guard on the claim dimension."""

    def test_intake_leaves_claim_in_draft_and_moves_nothing(self, catalogue, api):
        """A freshly created claim sits in DRAFT and fires no side effects at all.

        "At creation the claim's `status` is `DRAFT`, its `info_request_count` and `assessment_count` are both 0, its `submitted_at`, `latest_determination`, `latest_repair_cost_cents`, `decision`, `decision_threshold_pct`, `repair_ratio_pct`, `decision_by_role` and `decided_at` are all null, and its `proof_verified` flag is derived from the unit: it is true exactly when the unit's `proof_of_purchase_type` is not `NONE` and its `proof_of_purchase_ref` is not null, and it is recomputed whenever those fields change."
        "Its `disposition_status` starts at `WITH_CUSTOMER`."
        "A new customer starts with `lifetime_claim_count` and `trade_in_credit_cents` at 0."

        Design: Corner/state_machines/warranty_claim_initial_state_is_draft
        """
        scenario = catalogue.scenario
        response = api.create_warranty_claim(
            factories.warranty_claim_payload(catalogue.center_id, catalogue.item_id),
            make_customer_headers(catalogue.customer_id),
        )
        claim = get_success_data(response, 201)

        assert claim["status"] == "DRAFT", claim
        assert claim["version"] == 1, claim
        assert claim["proof_verified"] is True, claim
        assert claim["submitted_at"] is None, claim
        assert claim["decision"] is None, claim
        assert claim["latest_determination"] is None, claim
        assert claim["info_request_count"] == 0, claim
        assert claim["assessment_count"] == 0, claim

        item = scenario.read_item(catalogue.item_id)
        assert item["disposition_status"] == "WITH_CUSTOMER", item
        owner = scenario.read_customer(catalogue.customer_id)
        assert owner["lifetime_claim_count"] == 0, owner

    def test_submit_stamps_claim_and_cascades_to_item_and_owner(
        self, catalogue, api, agent_headers
    ):
        """One submit call moves DRAFT -> SUBMITTED and fires all three side effects.

        "Submitting moves the claim `DRAFT` → `SUBMITTED`."
        "On success the claim's `submitted_at` is stamped with the logical clock instant, the unit moves `WITH_CUSTOMER` → `AT_CENTER` because the centre now has custody, and the owning customer's `lifetime_claim_count` increases by one."

        Design: Corner/state_machines/claim_submit_transition_applies_item_and_customer_side_effects
        """
        scenario = catalogue.scenario
        claim = scenario.claim(catalogue.center_id, catalogue.item_id)

        submitted = get_success_data(api.submit_claim(claim["id"], agent_headers), 200)

        assert submitted["status"] == "SUBMITTED", submitted
        assert submitted["submitted_at"].startswith(CLOCK_INSTANT_PREFIX), submitted
        assert submitted["proof_verified"] is True, submitted
        assert submitted["version"] == 2, submitted
        assert submitted["assessment_count"] == 0, submitted
        assert submitted["info_request_count"] == 0, submitted
        assert submitted["decision"] is None, submitted

        item = scenario.read_item(catalogue.item_id)
        assert item["disposition_status"] == "AT_CENTER", item
        owner = scenario.read_customer(catalogue.customer_id)
        assert owner["lifetime_claim_count"] == 1, owner

    def test_second_submit_is_refused_and_counts_are_not_doubled(
        self, submitted_claim, api, agent_headers
    ):
        """Submit is not idempotent: the second call finds SUBMITTED, an illegal origin.

        "The transition requires that the claim actually be in `DRAFT`; that either the `intake_kind` be `PAID_REPAIR_REQUEST` or `proof_verified` be true; and that either the `intake_kind` be `PAID_REPAIR_REQUEST` or the unit's `warranty_state` be `IN_WARRANTY` or `LIFETIME`."
        "(11) A claim's `status` is a legal origin state for the requested claim transition, else `ERR_INVALID_CLAIM_STATE` (409); this guards claim submit, information request, resubmit, assessment recording, adjudication and repair-order creation."

        Design: Corner/state_machines/claim_second_submit_rejected
        """
        scenario = submitted_claim.scenario
        response = api.submit_claim(submitted_claim.claim_id, agent_headers)
        validate_error(response, ERR_INVALID_CLAIM_STATE)

        claim = scenario.read_claim(submitted_claim.claim_id)
        assert claim["status"] == "SUBMITTED", claim
        assert claim["version"] == 2, claim
        owner = scenario.read_customer(submitted_claim.customer_id)
        assert owner["lifetime_claim_count"] == 1, owner

    def test_assessment_on_draft_claim_reports_state_before_version(
        self, catalogue, api
    ):
        """A bench assessment on a DRAFT claim reports the origin-state failure first.

        "Only a `RepairTechnician` may record a **bench assessment**, and doing so is the transition `SUBMITTED` → `UNDER_ASSESSMENT`, or the self-loop `UNDER_ASSESSMENT` → `UNDER_ASSESSMENT` when the bench re-assesses."
        "Every request runs the same ordered gauntlet, and the **first** check that fails produces the response — no later check is evaluated, so a request that violates several rules always reports the earliest one."
        "(11) A claim's `status` is a legal origin state for the requested claim transition, else `ERR_INVALID_CLAIM_STATE` (409); this guards claim submit, information request, resubmit, assessment recording, adjudication and repair-order creation."

        Design: Corner/state_machines/assessment_on_draft_claim_rejected
        """
        scenario = catalogue.scenario
        claim = scenario.claim(catalogue.center_id, catalogue.item_id)
        assert claim["version"] == 1, claim

        response = api.create_assessment(
            claim["id"],
            factories.assessment_payload(
                claim["version"],
                defect_notes="Bench look before intake completed.",
            ),
            make_technician_headers(catalogue.technician_id),
        )
        validate_error(response, ERR_INVALID_CLAIM_STATE)

        stored = scenario.read_claim(claim["id"])
        assert stored["status"] == "DRAFT", stored
        assert stored["assessment_count"] == 0, stored
        assert stored["version"] == 1, stored

        rows = get_success_data(
            api.list_claim_assessments(
                make_technician_headers(catalogue.technician_id),
                warranty_claim_id=claim["id"],
            )
        )
        assert rows == [], rows


class TestGearItemTerminalDisposition:
    """The terminal-disposition lockdown of PRD §2.11 check 17."""

    def test_trade_in_on_returned_unit_reports_already_terminal(
        self, order_with_sent_estimate, api, agent_headers
    ):
        """A declined quote returns the unit, and RETURNED locks out the trade-in.

        "(17) The addressed resource is not already terminal in the dimension the call would move: a claim in `WEAR_DENIED`, `CLOSED_FULFILLED`, `CLOSED_REPLACED` or `CLOSED_DECLINED`, an order whose `work_status` is `RELEASED`, `IRREPARABLE` or `CLOSED_UNREPAIRED`, or a unit in `RETURNED`, `RESOLD` or `RECYCLED`, all yield `ERR_ALREADY_TERMINAL` (409); this applies to every action endpoint that mutates a claim, a repair order or a gear unit."
        "`RETURNED`, `RESOLD` and `RECYCLED` are all terminal."

        Design: Corner/state_machines/trade_in_on_returned_item_rejected
        """
        scenario = order_with_sent_estimate.scenario
        scenario.decline_estimate(
            order_with_sent_estimate.estimate_id,
            order_with_sent_estimate.customer_id,
            decline_reason="Too expensive.",
        )
        returned = scenario.read_item(order_with_sent_estimate.item_id)
        assert returned["disposition_status"] == "RETURNED", returned

        response = api.trade_in_gear_item(
            order_with_sent_estimate.item_id, {"condition_grade": "B"}, agent_headers
        )
        validate_error(response, ERR_ALREADY_TERMINAL)

        item = scenario.read_item(order_with_sent_estimate.item_id)
        assert item["disposition_status"] == "RETURNED", item
        assert item["trade_in_credit_cents"] == 0, item
        assert item["refurb_list_price_cents"] is None, item
        owner = scenario.read_customer(order_with_sent_estimate.customer_id)
        assert owner["trade_in_credit_cents"] == 0, owner


class TestWearDenialTerminalBranch:
    """The stockroom-guarded UNDER_ASSESSMENT -> WEAR_DENIED edge of PRD §3.5."""

    def test_normal_wear_without_parts_support_denies_and_locks_the_claim(
        self, scenario, api, agent_headers
    ):
        """NORMAL_WEAR on an unstocked model denies terminally and opens no exposure.

        "A new model begins with `parts_support_status` at `NO_SUPPORT`, because no lot has been stocked for it yet, with `repairability_flag` at `NONE`, and with its three feedback counters — `defect_claim_count`, `wear_denial_count` and `irreparable_count` — all at 0."
        "If it is `NORMAL_WEAR`, the outcome depends on the stockroom: `WEAR_DENIED` when the model's `parts_support_status` is `NO_SUPPORT`, and `PAID_REPAIR_OFFERED` otherwise."
        "Whatever the outcome, the claim records `decision`, `decision_threshold_pct`, `repair_ratio_pct`, `decision_by_role` — set to `ServiceAgent` or `ProgramAdmin` according to the acting role — and `decided_at` from the logical clock."
        "A `WEAR_DENIED` outcome moves the claim `UNDER_ASSESSMENT` → `WEAR_DENIED`, which is terminal, and stamps `decision`, `decided_at` and `decision_by_role`."
        "No liability entry is created and no repair order follows; the unit's `disposition_status` stays at `AT_CENTER`."
        "The feedback signal is different from the warranty branches: the model's `wear_denial_count` increases by one and `defect_claim_count` is left untouched."
        "(11) A claim's `status` is a legal origin state for the requested claim transition, else `ERR_INVALID_CLAIM_STATE` (409); this guards claim submit, information request, resubmit, assessment recording, adjudication and repair-order creation."

        Design: Corner/state_machines/normal_wear_on_unsupported_model_denies_claim_terminally
        """
        world = _build_own_msrp_world(scenario, stock_panel_lot=False)
        model = scenario.read_model(world["model_id"])
        assert model["parts_support_status"] == "NO_SUPPORT", model

        claim = scenario.claim(
            world["center_id"],
            world["item_id"],
            reported_defect_type="ABRASION_WEAR",
            customer_narrative="Floor is worn thin.",
        )
        submitted = scenario.submit(claim["id"])
        scenario.assess(
            claim["id"],
            world["technician_id"],
            expected_claim_version=submitted["version"],
            determination="NORMAL_WEAR",
            defect_notes="Uniform abrasion, no defect.",
        )

        decided = get_success_data(
            api.decide_claim(
                claim["id"], agent_headers, {"decision_note": "Wear, and no parts remain."}
            ),
            200,
        )
        assert_claim_decision(decided, "WEAR_DENIED", "WEAR_DENIED", 55, 31.14)
        assert decided["decision_by_role"] == "ServiceAgent", decided
        assert decided["decided_at"].startswith(CLOCK_INSTANT_PREFIX), decided

        model = scenario.read_model(world["model_id"])
        assert model["wear_denial_count"] == 1, model
        assert model["defect_claim_count"] == 0, model
        assert model["repairability_flag"] == "NONE", model

        assert scenario.liability_entries(claim["id"]) == []
        assert_center_posture(
            scenario.read_center(world["center_id"]), 0, posture="OPEN"
        )
        item = scenario.read_item(world["item_id"])
        assert item["disposition_status"] == "AT_CENTER", item

        refused = api.create_info_request(
            claim["id"], {"reason": "Trying to reopen after denial."}, agent_headers
        )
        validate_error(refused, ERR_INVALID_CLAIM_STATE)
        assert scenario.read_claim(claim["id"])["info_request_count"] == 0


class TestRepairOrderQualityControlCycle:
    """The BENCH_DONE fork of PRD §3.8: rework loop versus forced condemnation."""

    def test_first_qc_failure_reopens_the_bench_and_keeps_liability_open(
        self, bench_completed_order, api, agent_headers
    ):
        """The first FAIL closes a loop: back to IN_WORK with the REPAIR reservation open.

        "While `qc_fail_count` is below two before the increment, the count increases by one and the order moves `BENCH_DONE` → `IN_WORK`, reopening a rework loop that requires fresh work blocks; that is the bench cycle `IN_WORK` → `BENCH_DONE` → `IN_WORK`."
        "First, a liability entry is created on the claim with `basis` `REPAIR`, `valuation_variant` `DEPRECIATED_PURCHASE`, `status` `OPEN`, and a `reserved_amount_cents` equal to the lesser of the claim's `latest_repair_cost_cents` and the unit's `replacement_value_depreciated_cents` — the brand never reserves more for a repair than the depreciated worth of the thing being repaired."
        "`liability_utilization_pct` is one hundred multiplied by `open_liability_cents` divided by `liability_cap_cents`, rounded half up to two decimal places, and is display-only."
        "On success the block's `duration_minutes` is the whole number of minutes between `start_at` and `end_at`, its `status` is `SCHEDULED`, its `actual_minutes` is null, the assigned technician's `scheduled_minutes_open` increases by `duration_minutes`, and — if this is the first block on the order — the order's `work_status` moves `QUEUED` → `IN_WORK`."

        Design: Corner/state_machines/qc_failure_returns_order_to_in_work_and_rework_is_accepted
        """
        scenario = bench_completed_order.scenario
        failed = get_success_data(
            api.create_qc_inspection(
                bench_completed_order.order_id,
                {"outcome": "FAIL", "notes": "Bond line still lifting."},
                make_technician_headers(bench_completed_order.second_technician_id),
            ),
            200,
        )
        assert failed["qc_fail_count"] == 1, failed
        assert failed["work_status"] == "IN_WORK", failed

        item = scenario.read_item(bench_completed_order.item_id)
        assert item["disposition_status"] == "IN_REPAIR", item
        model = scenario.read_model(bench_completed_order.model_id)
        assert model["irreparable_count"] == 0, model

        entries = scenario.liability_entries(bench_completed_order.claim_id)
        assert len(entries) == 1, entries
        entry = entries[0]
        assert entry["status"] == "OPEN", entry
        assert entry["basis"] == "REPAIR", entry
        assert entry["valuation_variant"] == "DEPRECIATED_PURCHASE", entry
        assert entry["reserved_amount_cents"] == 22390, entry
        assert_center_posture(
            scenario.read_center(bench_completed_order.center_id), 22390, 0.45
        )

        rework_payload = factories.work_block_payload(
            bench_completed_order.order_id,
            work_type="FABRIC",
            start_at="2026-06-17T09:00:00Z",
            end_at="2026-06-17T10:00:00Z",
            technician_id=bench_completed_order.technician_id,
        )
        rework = get_success_data(
            api.create_work_block(rework_payload, agent_headers), 201
        )
        assert rework["status"] == "SCHEDULED", rework
        assert rework["duration_minutes"] == 60, rework
        assert scenario.read_order(bench_completed_order.order_id)["work_status"] == "IN_WORK"

        technician = scenario.read_technician(bench_completed_order.technician_id)
        assert technician["completed_minutes"] == 120, technician
        assert technician["scheduled_minutes_open"] == 60, technician

    def test_third_qc_failure_condemns_and_revalues_the_reservation(
        self, scenario, api, agent_headers
    ):
        """The third FAIL takes the other branch: IRREPARABLE with liability revalued.

        "When `qc_fail_count` is exactly two before the increment — that is, on the third failure — the count is set to three and the order moves `BENCH_DONE` → `IRREPARABLE` automatically, with no operator choice, and the full condemnation cascade of §3.9 runs identically to an explicit condemnation."
        "For a warranty order the liability is revalued rather than merely released: the claim's open entry with `basis` `REPAIR` moves `OPEN` → `RELEASED` with `release_reason` `REVALUED_TO_REPLACEMENT`, and a new entry is created with `basis` `REPLACEMENT`, `valuation_variant` `SUCCESSOR_MSRP` and `status` `OPEN`, so the centre's `open_liability_cents` is adjusted by subtracting the released repair amount and adding the new replacement amount before `liability_posture` is re-derived."
        "The unit moves `IN_REPAIR` → `IRREPARABLE_HOLD`, which makes trade-in reachable."
        "And the model's `irreparable_count` increases by one, after which its `repairability_flag` is re-derived."
        "A model's `repairability_flag` becomes `REDESIGN_REQUESTED` when its `defect_claim_count` is at least five **and** its `irreparable_count` is at least two; failing that, it becomes `WATCH` when its `defect_claim_count` is at least three; and otherwise it is `NONE`."
        "The base list price is the successor model's `msrp_cents` when the unit's model has both a non-null `discontinued_at` and a non-null `successor_model_id`; in every other case it is the unit's own model's `msrp_cents`."
        "The successor valuation is that base list price multiplied by ninety percent, rounded half up to whole cents."

        Design: Corner/state_machines/third_qc_failure_forces_irreparable_and_revalues_liability
        """
        world = _build_own_msrp_world(scenario, stock_panel_lot=True)
        claim = scenario.claim(world["center_id"], world["item_id"])
        submitted = scenario.submit(claim["id"])
        scenario.assess(
            claim["id"],
            world["technician_id"],
            expected_claim_version=submitted["version"],
        )
        scenario.decide(claim["id"])
        order = scenario.repair_order(claim["id"])

        rounds = (
            ("2026-06-16T09:00:00Z", "2026-06-16T11:00:00Z", 120, "First failure."),
            ("2026-06-17T09:00:00Z", "2026-06-17T10:00:00Z", 60, "Second failure."),
            ("2026-06-18T09:00:00Z", "2026-06-18T10:00:00Z", 60, None),
        )
        for start_at, end_at, minutes, fail_note in rounds:
            block = scenario.work_block(
                order["id"],
                world["technician_id"],
                work_type="FABRIC",
                start_at=start_at,
                end_at=end_at,
            )
            scenario.bench_complete(
                order["id"],
                world["technician_id"],
                [factories.work_log_entry(block["id"], minutes)],
            )
            if fail_note is not None:
                scenario.qc(
                    order["id"],
                    world["second_technician_id"],
                    outcome="FAIL",
                    notes=fail_note,
                )

        condemned = get_success_data(
            api.create_qc_inspection(
                order["id"],
                {"outcome": "FAIL", "notes": "Third failure — panel cannot be saved."},
                make_technician_headers(world["second_technician_id"]),
            ),
            200,
        )
        assert condemned["qc_fail_count"] == 3, condemned
        assert condemned["work_status"] == "IRREPARABLE", condemned

        item = scenario.read_item(world["item_id"])
        assert item["disposition_status"] == "IRREPARABLE_HOLD", item

        entries = scenario.liability_entries(claim["id"])
        assert len(entries) == 2, entries
        repair_entry = next(e for e in entries if e["basis"] == "REPAIR")
        assert repair_entry["valuation_variant"] == "DEPRECIATED_PURCHASE", repair_entry
        assert repair_entry["reserved_amount_cents"] == 22390, repair_entry
        assert repair_entry["status"] == "RELEASED", repair_entry
        assert repair_entry["release_reason"] == "REVALUED_TO_REPLACEMENT", repair_entry
        replacement_entry = next(e for e in entries if e["basis"] == "REPLACEMENT")
        assert replacement_entry["valuation_variant"] == "SUCCESSOR_MSRP", replacement_entry
        assert replacement_entry["status"] == "OPEN", replacement_entry
        assert replacement_entry["reserved_amount_cents"] == 71910, replacement_entry

        assert_center_posture(
            scenario.read_center(world["center_id"]), 71910, 1.44, "OPEN"
        )

        model = scenario.read_model(world["model_id"])
        assert model["irreparable_count"] == 1, model
        assert model["defect_claim_count"] == 1, model
        assert model["repairability_flag"] == "NONE", model

        technician = scenario.read_technician(world["technician_id"])
        assert technician["scheduled_minutes_open"] == 0, technician
        assert technician["completed_minutes"] == 240, technician
        blocks = get_success_data(
            api.list_work_blocks(agent_headers, repair_order_id=order["id"], limit=100)
        )
        assert [b for b in blocks if b["status"] == "SCHEDULED"] == []

        assert scenario.read_claim(claim["id"])["status"] == "WARRANTY_APPROVED"
