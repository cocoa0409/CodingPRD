"""Order-lifecycle and fiscal validations of the PRD §2.11 ordered gauntlet.

The checks exercised here sit at the far end of the gauntlet: the duplicate-order
rule (check 39), the pagination bounds (check 10), the posture override on a
warranty replacement (check 24), the two state-dimension gates (checks 12 and
13), the trade-in disposition rule (check 49) and the three fiscal rules
evaluated last (checks 50, 51 and 52). Each test builds its own preconditions,
because the server is restarted with an empty database before every test.
"""

from test_helpers import (
    ERR_BALANCE_OUTSTANDING,
    ERR_ESTIMATE_NOT_APPROVED,
    ERR_INVALID_BILLING_STATE,
    ERR_INVALID_PAGINATION,
    ERR_INVALID_WORK_STATE,
    ERR_ITEM_NOT_IRREPARABLE,
    ERR_ORDER_ALREADY_OPEN,
    ERR_PAYMENT_AMOUNT_MISMATCH,
    ERR_REPLACEMENT_REQUIRES_OVERRIDE,
    World,
    assert_center_posture,
    assert_claim_decision,
    assert_no_row_created,
    factories,
    make_customer_headers,
    make_technician_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# The clock every world below pins before building state (PRD §2.4).
CLOCK_UTC = "2026-06-15T09:00:00Z"

ZIP_BLOCK_START = "2026-06-16T09:00:00Z"
ZIP_BLOCK_END = "2026-06-16T10:00:00Z"
OTHER_BLOCK_START = "2026-06-17T09:00:00Z"
OTHER_BLOCK_END = "2026-06-17T10:00:00Z"

# Second unit of the same model, so a second claim can be filed independently.
SECOND_PROOF_REF = "POS-88214"


def _no_parts_support_world(scenario) -> World:
    """A centre capped at 100000 cents and a model with no part lots at all.

    With `parts_support_status` at `NO_SUPPORT`, every MANUFACTURING_DEFECT
    finding on this model resolves to `WARRANTY_REPLACE`, and one replacement
    reservation of 71910 cents already carries the centre past sixty percent of
    its ceiling.
    """
    scenario.set_clock(CLOCK_UTC)
    center = scenario.center(liability_cap_cents=100000)
    model = scenario.model()
    customer = scenario.customer()
    item_a = scenario.gear_item(model["id"], customer["id"])
    item_b = scenario.gear_item(
        model["id"],
        customer["id"],
        serial_number=factories.SERIAL_B,
        proof_of_purchase_ref=SECOND_PROOF_REF,
    )
    technician = scenario.technician(
        center["id"], certifications=[factories.certification("FABRIC", 3)]
    )

    claim_a = scenario.claim(
        center["id"], item_a["id"], customer_narrative="Unit A seam split."
    )
    submitted_a = scenario.submit(claim_a["id"])
    scenario.assess(
        claim_a["id"],
        technician["id"],
        expected_claim_version=submitted_a["version"],
        defect_notes="Bond line A.",
    )
    decided_a = scenario.decide(claim_a["id"])

    claim_b = scenario.claim(
        center["id"], item_b["id"], customer_narrative="Unit B seam split."
    )
    submitted_b = scenario.submit(claim_b["id"])
    scenario.assess(
        claim_b["id"],
        technician["id"],
        expected_claim_version=submitted_b["version"],
        defect_notes="Bond line B.",
    )

    return World(
        scenario=scenario,
        center_id=center["id"],
        model_id=model["id"],
        customer_id=customer["id"],
        item_a_id=item_a["id"],
        item_b_id=item_b["id"],
        technician_id=technician["id"],
        claim_a=decided_a,
        claim_a_id=claim_a["id"],
        claim_b_id=claim_b["id"],
    )


def _paid_zipper_order(scenario) -> World:
    """A PAID_REPAIR order on a zipper job, quoted nowhere yet.

    USER_DAMAGE on a paid-repair intake, one ZIPPER lane of 35 bench-standard
    minutes and 1800 cents of parts, for a PRO-tier owner.
    """
    scenario.set_clock(CLOCK_UTC)
    center = scenario.center()
    model = scenario.model()
    zip_lot = scenario.part_lot(
        model["id"],
        part_code=factories.ZIP_PART_CODE,
        part_kind="ZIPPER_SLIDER",
        on_hand_units=4,
        unit_price_cents=1800,
        low_watermark_units=1,
    )
    customer = scenario.customer()
    item = scenario.gear_item(model["id"], customer["id"])
    bench_technician = scenario.technician(
        center["id"],
        employee_code="T-101",
        full_name="Ines Park",
        certifications=[factories.certification("ZIPPER", 3)],
    )
    qc_technician = scenario.technician(
        center["id"],
        employee_code="T-102",
        full_name="Dev Osei",
        certifications=[factories.certification("ZIPPER", 2)],
    )

    claim = scenario.claim(
        center["id"],
        item["id"],
        intake_kind="PAID_REPAIR_REQUEST",
        reported_defect_type="ZIPPER_FAILURE",
        customer_narrative="Slider chewed after a fall.",
    )
    submitted = scenario.submit(claim["id"])
    scenario.assess(
        claim["id"],
        bench_technician["id"],
        expected_claim_version=submitted["version"],
        determination="USER_DAMAGE",
        required_work_types=["ZIPPER"],
        estimated_labor_lines=[factories.labor_line("ZIPPER", 35)],
        estimated_parts_cents=1800,
        defect_notes="Impact damage.",
    )
    scenario.decide(claim["id"])
    order = scenario.repair_order(claim["id"])

    return World(
        scenario=scenario,
        center_id=center["id"],
        model_id=model["id"],
        zip_lot_id=zip_lot["id"],
        customer_id=customer["id"],
        item_id=item["id"],
        bench_technician_id=bench_technician["id"],
        qc_technician_id=qc_technician["id"],
        claim_id=claim["id"],
        order=order,
        order_id=order["id"],
    )


def _sent_quote(world) -> dict:
    """Issue the provisional quote: ZIPPER 35 minutes plus one 1800-cent slider."""
    return world.scenario.estimate(
        world.order_id,
        labor_lines=[factories.labor_line("ZIPPER", 35)],
        parts_lines=[factories.parts_line(factories.ZIP_PART_CODE, 1, 1800)],
    )


def _order_invoiced(world) -> World:
    """Carry the paid order to QC_PASSED / INVOICED with 40 minutes logged."""
    scenario = world.scenario
    estimate = _sent_quote(world)
    scenario.approve_estimate(estimate["id"], world.customer_id)
    reservation = scenario.reserve_parts(
        world.order_id, world.zip_lot_id, factories.ZIP_PART_CODE, 1
    )
    block = scenario.work_block(
        world.order_id,
        world.bench_technician_id,
        work_type="ZIPPER",
        start_at=ZIP_BLOCK_START,
        end_at=ZIP_BLOCK_END,
    )
    scenario.consume_parts(reservation["id"], world.bench_technician_id)
    scenario.bench_complete(
        world.order_id,
        world.bench_technician_id,
        [factories.work_log_entry(block["id"], 40)],
    )
    scenario.qc(
        world.order_id, world.qc_technician_id, notes="New slider runs clean."
    )
    invoice = scenario.invoice(world.order_id)
    world.update(
        estimate=estimate,
        estimate_id=estimate["id"],
        reservation_id=reservation["id"],
        block_id=block["id"],
        invoice=invoice,
        invoice_id=invoice["id"],
    )
    return world


def _scheduled_block_on_another_order(world):
    """Open a second warranty order on a second unit and book one block on it."""
    scenario = world.scenario
    other_item = scenario.gear_item(
        world.model_id,
        world.customer_id,
        serial_number=factories.SERIAL_B,
        proof_of_purchase_ref=SECOND_PROOF_REF,
    )
    other_claim = scenario.claim(
        world.center_id, other_item["id"], customer_narrative="Second unit seam split."
    )
    submitted = scenario.submit(other_claim["id"])
    scenario.assess(
        other_claim["id"],
        world.technician_id,
        expected_claim_version=submitted["version"],
        defect_notes="Bond line on the second unit.",
    )
    scenario.decide(other_claim["id"])
    other_order = scenario.repair_order(other_claim["id"])
    block = scenario.work_block(
        other_order["id"],
        world.second_technician_id,
        work_type="FABRIC",
        start_at=OTHER_BLOCK_START,
        end_at=OTHER_BLOCK_END,
    )
    return other_order, block


class TestSecondRepairOrderOnTheSameClaim:
    """PRD §2.11 check 39: one non-terminal order per claim."""

    def test_duplicate_order_on_an_offered_claim_is_refused(self, api, agent_headers, paid_repair_order):
        """A second order on a claim that already carries an open one is refused.

        "(39) The claim has no repair order in a non-terminal `work_status` and its `decision` is one that authorises an order, else `ERR_ORDER_ALREADY_OPEN` (409)."
        "The claim must be in a state that authorises an order and its `decision` must be `WARRANTY_REPAIR` or `PAID_REPAIR_OFFERED`; a claim whose `decision` is `WARRANTY_REPLACE` never gets an order, and neither does a claim that already has an order in a non-terminal `work_status` — both are refused with `ERR_ORDER_ALREADY_OPEN`."
        "A `PAID_REPAIR_OFFERED` outcome moves the claim `UNDER_ASSESSMENT` → `PAID_REPAIR_OFFERED` and stamps `decision`, `decided_at` and `decision_by_role`."

        Design: Corner/validations/second_repair_order_on_the_same_claim_rejected
        """
        scenario = paid_repair_order.scenario
        claim = scenario.read_claim(paid_repair_order.claim_id)
        assert claim["status"] == "PAID_REPAIR_OFFERED", claim
        assert scenario.read_order(paid_repair_order.order_id)["work_status"] == "QUEUED"

        response = api.create_repair_order(
            factories.repair_order_payload(paid_repair_order.claim_id), agent_headers
        )
        validate_error(response, ERR_ORDER_ALREADY_OPEN)

        unchanged = scenario.read_claim(paid_repair_order.claim_id)
        assert unchanged["status"] == "PAID_REPAIR_OFFERED", unchanged

    def test_refused_duplicate_mints_no_second_order_and_moves_no_queue(
        self, api, agent_headers, paid_repair_order
    ):
        """The claim keeps exactly one order, and queue depth and custody are untouched.

        "(39) The claim has no repair order in a non-terminal `work_status` and its `decision` is one that authorises an order, else `ERR_ORDER_ALREADY_OPEN` (409)."
        "The unit moves `AT_CENTER` → `IN_REPAIR`, and the order's bench dimension begins at `QUEUED` with `commitment_breached` false, `qc_fail_count` at 0, `paid_amount_cents` at 0, and `released_at`, `provisional_estimate_total_cents` and `final_invoice_total_cents` all null."
        "`active_queue_depth` itself is defined as the count of the centre's repair orders whose `work_status` is `QUEUED`, `IN_WORK` or `BENCH_DONE`."

        Design: Corner/validations/second_repair_order_on_the_same_claim_rejected
        """
        scenario = paid_repair_order.scenario

        validate_error(
            api.create_repair_order(
                factories.repair_order_payload(paid_repair_order.claim_id),
                agent_headers,
            ),
            ERR_ORDER_ALREADY_OPEN,
        )

        rows, meta = validate_paginated(
            api.list_repair_orders(
                agent_headers, warranty_claim_id=paid_repair_order.claim_id
            )
        )
        assert meta["total_count"] == 1, meta
        assert [row["id"] for row in rows] == [paid_repair_order.order_id], rows

        center = scenario.read_center(paid_repair_order.center_id)
        assert center["active_queue_depth"] == 1, center

        item = scenario.read_item(paid_repair_order.item_id)
        assert item["disposition_status"] == "IN_REPAIR", item


class TestPaginationBoundsOnListEndpoints:
    """PRD §2.11 check 10: limit is a closed 1..100 range and offset is non-negative."""

    def test_limit_zero_limit_over_hundred_and_negative_offset_are_refused(
        self, api, agent_headers, scenario
    ):
        """Each of limit 0, limit 101 and offset -1 is refused before any filtering.

        "The `limit` parameter caps the number of rows returned; when omitted it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100."
        "The `offset` parameter is the number of rows to skip, defaults to 0, and must not be negative."
        "A `limit` below 1 or above 100, or a negative `offset`, is rejected with `ERR_INVALID_PAGINATION` (HTTP 422)."
        "(10) On every list endpoint, `limit` within 1 to 100 and `offset` at least zero, else `ERR_INVALID_PAGINATION`."

        Design: Corner/validations/pagination_bounds_enforced_on_list_endpoints
        """
        scenario.set_clock(CLOCK_UTC)
        model = scenario.model()
        customer = scenario.customer()
        item_a = scenario.gear_item(model["id"], customer["id"])
        item_b = scenario.gear_item(
            model["id"],
            customer["id"],
            serial_number=factories.SERIAL_B,
            proof_of_purchase_ref=SECOND_PROOF_REF,
        )

        validate_error(
            api.list_gear_items(agent_headers, limit=0), ERR_INVALID_PAGINATION
        )
        validate_error(
            api.list_gear_items(agent_headers, limit=101), ERR_INVALID_PAGINATION
        )
        validate_error(
            api.list_gear_items(agent_headers, offset=-1), ERR_INVALID_PAGINATION
        )

        for item_id in (item_a["id"], item_b["id"]):
            assert scenario.read_item(item_id)["version"] == 1

    def test_limit_hundred_at_offset_zero_is_the_accepted_upper_edge(
        self, api, agent_headers, scenario
    ):
        """limit 100 with offset 0 is inside the closed range and lists both rows.

        "The `limit` parameter caps the number of rows returned; when omitted it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100."
        "A `limit` below 1 or above 100, or a negative `offset`, is rejected with `ERR_INVALID_PAGINATION` (HTTP 422)."
        "List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope."

        Design: Corner/validations/pagination_bounds_enforced_on_list_endpoints
        """
        scenario.set_clock(CLOCK_UTC)
        model = scenario.model()
        customer = scenario.customer()
        item_a = scenario.gear_item(model["id"], customer["id"])
        item_b = scenario.gear_item(
            model["id"],
            customer["id"],
            serial_number=factories.SERIAL_B,
            proof_of_purchase_ref=SECOND_PROOF_REF,
        )

        rows, meta = validate_paginated(
            api.list_gear_items(agent_headers, limit=100, offset=0)
        )
        assert meta["limit"] == 100, meta
        assert meta["offset"] == 0, meta
        assert meta["total_count"] == 2, meta
        assert meta["has_more"] is False, meta
        listed = {row["id"] for row in rows}
        assert listed == {item_a["id"], item_b["id"]}, rows


class TestConstrainedPostureReplacementOverride:
    """PRD §2.11 check 24: under CONSTRAINED only a ProgramAdmin may replace."""

    def test_service_agent_replacement_refused_once_the_centre_is_constrained(
        self, api, agent_headers, scenario
    ):
        """The same ServiceAgent call that decided claim A is refused for claim B.

        "Otherwise, if `open_liability_cents` multiplied by one hundred is strictly greater than sixty multiplied by `liability_cap_cents`, the posture is `CONSTRAINED`."
        "Under `CONSTRAINED`, a warranty replacement outcome requires a `ProgramAdmin` actor and anyone else is refused with `ERR_REPLACEMENT_REQUIRES_OVERRIDE`; warranty repair outcomes remain available to a `ServiceAgent`."
        "(24) When the posture is `CONSTRAINED` and the adjudication resolves to a warranty replacement, `X-User-Role` must be `ProgramAdmin`, else `ERR_REPLACEMENT_REQUIRES_OVERRIDE` (403)."
        "If the model's `parts_support_status` is `NO_SUPPORT`, the outcome is `WARRANTY_REPLACE`, because there is nothing to repair the unit with."
        "On success a liability entry is created with `basis` `REPLACEMENT`, `valuation_variant` `SUCCESSOR_MSRP`, `status` `OPEN` and a `reserved_amount_cents` equal to the unit's full `replacement_value_successor_cents`; the centre's `open_liability_cents` rises by that amount and `liability_posture` is re-derived."

        Design: Corner/validations/constrained_posture_replacement_requires_program_admin
        """
        world = _no_parts_support_world(scenario)
        assert_claim_decision(
            world.claim_a, "WARRANTY_REPLACE", "REPLACEMENT_AUTHORIZED", 55, 31.14
        )
        entries = scenario.liability_entries(world.claim_a_id)
        assert len(entries) == 1, entries
        assert entries[0]["basis"] == "REPLACEMENT", entries[0]
        assert entries[0]["valuation_variant"] == "SUCCESSOR_MSRP", entries[0]
        assert entries[0]["reserved_amount_cents"] == 71910, entries[0]
        assert_center_posture(
            scenario.read_center(world.center_id), 71910, 71.91, "CONSTRAINED"
        )

        response = api.decide_claim(
            world.claim_b_id,
            agent_headers,
            {"decision_note": "Second replacement of the batch."},
        )
        validate_error(response, ERR_REPLACEMENT_REQUIRES_OVERRIDE)

        claim_b = scenario.read_claim(world.claim_b_id)
        assert claim_b["status"] == "UNDER_ASSESSMENT", claim_b
        assert claim_b["decision"] is None, claim_b
        assert_no_row_created(scenario.liability_entries(world.claim_b_id))
        assert_center_posture(
            scenario.read_center(world.center_id), 71910, 71.91, "CONSTRAINED"
        )

    def test_program_admin_override_authorises_the_replacement_and_freezes_the_centre(
        self, api, admin_headers, agent_headers, scenario
    ):
        """The ProgramAdmin override goes through and drives the centre to FROZEN.

        "Under `CONSTRAINED`, a warranty replacement outcome requires a `ProgramAdmin` actor and anyone else is refused with `ERR_REPLACEMENT_REQUIRES_OVERRIDE`; warranty repair outcomes remain available to a `ServiceAgent`."
        "A `WARRANTY_REPLACE` outcome moves the claim `UNDER_ASSESSMENT` → `REPLACEMENT_AUTHORIZED` and is where posture bites hardest: while the centre is `CONSTRAINED`, only a `ProgramAdmin` may reach this outcome and any other role is refused with `ERR_REPLACEMENT_REQUIRES_OVERRIDE`."
        "The unit moves `AT_CENTER` → `IRREPARABLE_HOLD` and thereby skips the bench entirely: **no repair order may ever be opened on a replacement-authorised claim**, and the unit goes straight into the trade-in lane."
        "If `open_liability_cents` is strictly greater than `liability_cap_cents`, the posture is `FROZEN`."
        "As with a repair approval, the model's `defect_claim_count` increases by one and its `repairability_flag` is re-derived."

        Design: Corner/validations/constrained_posture_replacement_requires_program_admin
        """
        world = _no_parts_support_world(scenario)

        validate_error(
            api.decide_claim(
                world.claim_b_id,
                agent_headers,
                {"decision_note": "Second replacement of the batch."},
            ),
            ERR_REPLACEMENT_REQUIRES_OVERRIDE,
        )

        claim_b = validate_success(
            api.decide_claim(
                world.claim_b_id,
                admin_headers,
                {"decision_note": "Override authorised by the program owner."},
            )
        )
        assert_claim_decision(
            claim_b, "WARRANTY_REPLACE", "REPLACEMENT_AUTHORIZED", 55, 31.14
        )
        assert claim_b["decision_by_role"] == "ProgramAdmin", claim_b

        assert_center_posture(
            scenario.read_center(world.center_id), 143820, 143.82, "FROZEN"
        )
        item_b = scenario.read_item(world.item_b_id)
        assert item_b["disposition_status"] == "IRREPARABLE_HOLD", item_b
        assert scenario.read_model(world.model_id)["defect_claim_count"] == 2


class TestWarrantyOrderInvoicingAndRelease:
    """PRD §2.11 checks 50 and 52 on a NOT_BILLABLE warranty order."""

    def test_invoicing_a_not_billable_warranty_order_is_refused(
        self, api, agent_headers, qc_passed_order
    ):
        """A QC-passed warranty order is past every work gate yet still not invoiceable.

        "(50) At invoicing, `billing_status` equals `ESTIMATE_APPROVED` — a paid order must carry an approved provisional quote, and a `NOT_BILLABLE` warranty order is never invoiceable — else `ERR_ESTIMATE_NOT_APPROVED` (HTTP 402)."
        "A paid order with no approved quote, and any `NOT_BILLABLE` warranty order, are refused with `ERR_ESTIMATE_NOT_APPROVED`."
        "A warranty order is minted with `billing_status` `NOT_BILLABLE`, which is already terminal in the money dimension — a warranty order is never quoted, never invoiced and never paid, and any attempt to issue an estimate on it is refused with `ERR_INVALID_BILLING_STATE`."

        Design: Corner/validations/warranty_order_cannot_be_invoiced_but_releases_without_payment
        """
        scenario = qc_passed_order.scenario
        order = scenario.read_order(qc_passed_order.order_id)
        assert order["work_status"] == "QC_PASSED", order
        assert order["billing_status"] == "NOT_BILLABLE", order

        response = api.invoice_order(qc_passed_order.order_id, agent_headers)
        validate_error(response, ERR_ESTIMATE_NOT_APPROVED)

        after = scenario.read_order(qc_passed_order.order_id)
        assert after["billing_status"] == "NOT_BILLABLE", after
        assert after["final_invoice_total_cents"] is None, after

        rows, meta = validate_paginated(
            api.list_order_estimates(qc_passed_order.order_id, agent_headers)
        )
        assert meta["total_count"] == 0, meta
        assert_no_row_created(rows)

    def test_warranty_order_releases_with_no_payment_at_all(
        self, api, agent_headers, qc_passed_order
    ):
        """Release succeeds on the unpaid warranty order and unwinds the exposure.

        "**Release to customer** is a `ServiceAgent` operation on an order in `work_status` `QC_PASSED` whose `billing_status` is either `NOT_BILLABLE` or `PAID`; a paid order still carrying a balance is refused with `ERR_BALANCE_OUTSTANDING`."
        "On success the order moves `QC_PASSED` → `RELEASED` with `released_at` stamped from the logical clock, the unit moves `IN_REPAIR` → `RETURNED`, and the claim closes — `WARRANTY_APPROVED` → `CLOSED_FULFILLED` for a warranty order and `PAID_REPAIR_OFFERED` → `CLOSED_FULFILLED` for a paid one."
        "For a warranty order the claim's open liability entry with `basis` `REPAIR` moves `OPEN` → `RELEASED` with `release_reason` `ORDER_RELEASED` and `released_at` stamped, the centre's `open_liability_cents` decreases by the released amount, and `liability_posture` is re-derived — which is how a centre unwinds from `FROZEN` back toward `OPEN`."

        Design: Corner/validations/warranty_order_cannot_be_invoiced_but_releases_without_payment
        """
        scenario = qc_passed_order.scenario
        validate_error(
            api.invoice_order(qc_passed_order.order_id, agent_headers),
            ERR_ESTIMATE_NOT_APPROVED,
        )

        validate_success(api.release_to_customer(qc_passed_order.order_id, agent_headers))
        released = scenario.read_order(qc_passed_order.order_id)
        assert released["work_status"] == "RELEASED", released
        assert released["paid_amount_cents"] == 0, released
        assert released["released_at"].startswith("2026-06-15T09:00:00"), released

        item = scenario.read_item(qc_passed_order.item_id)
        assert item["disposition_status"] == "RETURNED", item
        claim = scenario.read_claim(qc_passed_order.claim_id)
        assert claim["status"] == "CLOSED_FULFILLED", claim

        entries = scenario.liability_entries(qc_passed_order.claim_id)
        assert len(entries) == 1, entries
        assert entries[0]["basis"] == "REPAIR", entries[0]
        assert entries[0]["valuation_variant"] == "DEPRECIATED_PURCHASE", entries[0]
        assert entries[0]["reserved_amount_cents"] == 22390, entries[0]
        assert entries[0]["status"] == "RELEASED", entries[0]
        assert entries[0]["release_reason"] == "ORDER_RELEASED", entries[0]

        center = scenario.read_center(qc_passed_order.center_id)
        assert_center_posture(center, 0, 0, "OPEN")
        assert center["active_queue_depth"] == 0, center


class TestPaymentSettlesTheExactBalance:
    """PRD §2.11 check 51: neither partial payment nor overpayment is accepted."""

    def test_underpayment_and_overpayment_are_both_refused(self, api, scenario):
        """8000 and 9000 are each refused against the 8355-cent invoice.

        "(51) A payment's `amount_cents` equals `final_invoice_total_cents` minus `paid_amount_cents` exactly, with neither partial payment nor overpayment accepted, else `ERR_PAYMENT_AMOUNT_MISMATCH` (402)."
        "A payment, available to the owner or to a `ServiceAgent`, carries an `amount_cents` that must equal `final_invoice_total_cents` minus `paid_amount_cents` precisely; anything less or more is refused with `ERR_PAYMENT_AMOUNT_MISMATCH`, and a payment attempted before invoicing is refused with `ERR_INVALID_BILLING_STATE`."
        "A `FINAL` row is derived by the server and accepts no lines from the caller at all: its labour lines come from the order's work blocks whose `status` is `COMPLETED`, grouped by `work_type` with the group's minutes being the sum of `actual_minutes` for that work type and the groups taken in ascending `work_type` order; its parts lines come from the order's reservations whose `status` is `CONSUMED`, each priced at its lot's `unit_price_cents`, with `RESERVED` and `RELEASED` reservations excluded entirely."
        "**Step eight** totals: `total_cents` is `subtotal_cents` minus `loyalty_discount_cents` plus `expedite_fee_cents` plus `tax_cents`."

        Design: Corner/validations/payment_must_settle_the_exact_outstanding_balance
        """
        world = _order_invoiced(_paid_zipper_order(scenario))
        customer_headers = make_customer_headers(world.customer_id)

        order = scenario.read_order(world.order_id)
        assert order["billing_status"] == "INVOICED", order
        assert order["provisional_estimate_total_cents"] == 7531, order
        assert order["final_invoice_total_cents"] == 8355, order
        assert order["paid_amount_cents"] == 0, order

        validate_error(
            api.pay_order(world.order_id, {"amount_cents": 8000}, customer_headers),
            ERR_PAYMENT_AMOUNT_MISMATCH,
        )
        validate_error(
            api.pay_order(world.order_id, {"amount_cents": 9000}, customer_headers),
            ERR_PAYMENT_AMOUNT_MISMATCH,
        )

        after = scenario.read_order(world.order_id)
        assert after["paid_amount_cents"] == 0, after
        assert after["billing_status"] == "INVOICED", after
        assert scenario.read_estimate(world.invoice_id)["status"] == "INVOICED"

    def test_the_exact_outstanding_balance_settles_the_invoice(self, api, scenario):
        """Paying exactly 8355 moves both the order and the FINAL row to PAID.

        "(51) A payment's `amount_cents` equals `final_invoice_total_cents` minus `paid_amount_cents` exactly, with neither partial payment nor overpayment accepted, else `ERR_PAYMENT_AMOUNT_MISMATCH` (402)."
        "On success the amount is added to the order's `paid_amount_cents`, the order's `billing_status` moves `INVOICED` → `PAID`, and the `FINAL` estimate row moves `INVOICED` → `PAID`."
        "On success a new estimate row is minted with `variant` `FINAL` directly in `status` `INVOICED` — a final row never passes through `SENT` or `APPROVED` — priced by the `FINAL` variant above, and the order's `final_invoice_total_cents` is set from that row's `total_cents` while its `billing_status` moves `ESTIMATE_APPROVED` → `INVOICED`."

        Design: Corner/validations/payment_must_settle_the_exact_outstanding_balance
        """
        world = _order_invoiced(_paid_zipper_order(scenario))
        customer_headers = make_customer_headers(world.customer_id)
        assert world.invoice["variant"] == "FINAL", world.invoice
        assert world.invoice["total_cents"] == 8355, world.invoice

        validate_success(
            api.pay_order(world.order_id, {"amount_cents": 8355}, customer_headers)
        )
        paid = scenario.read_order(world.order_id)
        assert paid["paid_amount_cents"] == 8355, paid
        assert paid["billing_status"] == "PAID", paid

        assert scenario.read_estimate(world.invoice_id)["status"] == "PAID"


class TestReleaseBlockedUntilTheBalanceIsSettled:
    """PRD §2.11 check 52: a paid-repair order must be PAID before release."""

    def test_release_refused_while_the_invoice_is_unpaid(self, api, agent_headers, scenario):
        """QC_PASSED satisfies the bench gate, but the billing dimension refuses release.

        "(52) A paid-repair order's `billing_status` is `PAID` before release, else `ERR_BALANCE_OUTSTANDING` (402)."
        "**Release to customer** is a `ServiceAgent` operation on an order in `work_status` `QC_PASSED` whose `billing_status` is either `NOT_BILLABLE` or `PAID`; a paid order still carrying a balance is refused with `ERR_BALANCE_OUTSTANDING`."
        "Only then does release-to-customer become reachable in the bench dimension."

        Design: Corner/validations/release_blocked_until_the_paid_balance_is_settled
        """
        world = _order_invoiced(_paid_zipper_order(scenario))
        order = scenario.read_order(world.order_id)
        assert order["work_status"] == "QC_PASSED", order
        assert order["billing_status"] == "INVOICED", order

        response = api.release_to_customer(world.order_id, agent_headers)
        validate_error(response, ERR_BALANCE_OUTSTANDING)

        after = scenario.read_order(world.order_id)
        assert after["work_status"] == "QC_PASSED", after
        assert after["released_at"] is None, after
        assert scenario.read_item(world.item_id)["disposition_status"] == "IN_REPAIR"
        assert scenario.read_claim(world.claim_id)["status"] == "PAID_REPAIR_OFFERED"

    def test_the_same_release_succeeds_once_the_invoice_is_paid(
        self, api, agent_headers, scenario
    ):
        """The identical release call goes through after settlement, and reserves nothing.

        "(52) A paid-repair order's `billing_status` is `PAID` before release, else `ERR_BALANCE_OUTSTANDING` (402)."
        "On success the order moves `QC_PASSED` → `RELEASED` with `released_at` stamped from the logical clock, the unit moves `IN_REPAIR` → `RETURNED`, and the claim closes — `WARRANTY_APPROVED` → `CLOSED_FULFILLED` for a warranty order and `PAID_REPAIR_OFFERED` → `CLOSED_FULFILLED` for a paid one."
        "For a paid order there is no liability movement at all, because a paid order never opened an entry."
        "Finally the centre's `active_queue_depth` is recomputed, since this order has left the queue."

        Design: Corner/validations/release_blocked_until_the_paid_balance_is_settled
        """
        world = _order_invoiced(_paid_zipper_order(scenario))

        validate_error(
            api.release_to_customer(world.order_id, agent_headers),
            ERR_BALANCE_OUTSTANDING,
        )

        scenario.pay(world.order_id, 8355)
        settled = scenario.read_order(world.order_id)
        assert settled["billing_status"] == "PAID", settled
        assert settled["paid_amount_cents"] == 8355, settled

        validate_success(api.release_to_customer(world.order_id, agent_headers))
        released = scenario.read_order(world.order_id)
        assert released["work_status"] == "RELEASED", released
        assert released["released_at"].startswith("2026-06-15T09:00:00"), released

        assert scenario.read_item(world.item_id)["disposition_status"] == "RETURNED"
        assert scenario.read_claim(world.claim_id)["status"] == "CLOSED_FULFILLED"
        assert_no_row_created(scenario.liability_entries(world.claim_id))
        center = scenario.read_center(world.center_id)
        assert_center_posture(center, 0, 0, "OPEN")
        assert center["active_queue_depth"] == 0, center


class TestBillingStateGatesBenchWorkAndPayments:
    """PRD §2.11 check 13: the money dimension gates both ends of the paid flow."""

    def test_bench_work_refused_while_the_quote_is_only_sent(self, api, agent_headers, scenario):
        """Scheduling a block on an ESTIMATE_SENT order is refused and books no minutes.

        "(13) An order's `billing_status` is a legal origin state, else `ERR_INVALID_BILLING_STATE` (409): issuing an estimate requires `ESTIMATE_PENDING` or `ESTIMATE_SENT` and never `NOT_BILLABLE`; scheduling a work block requires `NOT_BILLABLE` or `ESTIMATE_APPROVED`; recording a payment requires `INVOICED`."
        "The order's `work_status` must be `QUEUED` or `IN_WORK`, and its `billing_status` must be `NOT_BILLABLE` or `ESTIMATE_APPROVED`; scheduling bench time on a paid order whose quote is still `ESTIMATE_PENDING` or `ESTIMATE_SENT` is refused with `ERR_INVALID_BILLING_STATE`, which is exactly how the money dimension gates the bench dimension."
        "On success the block's `duration_minutes` is the whole number of minutes between `start_at` and `end_at`, its `status` is `SCHEDULED`, its `actual_minutes` is null, the assigned technician's `scheduled_minutes_open` increases by `duration_minutes`, and — if this is the first block on the order — the order's `work_status` moves `QUEUED` → `IN_WORK`."

        Design: Corner/validations/billing_state_gates_bench_work_and_payments
        """
        world = _paid_zipper_order(scenario)
        _sent_quote(world)
        order = scenario.read_order(world.order_id)
        assert order["billing_status"] == "ESTIMATE_SENT", order
        assert order["work_status"] == "QUEUED", order

        payload = factories.work_block_payload(
            world.order_id,
            work_type="ZIPPER",
            start_at=ZIP_BLOCK_START,
            end_at=ZIP_BLOCK_END,
        )
        payload["technician_id"] = world.bench_technician_id
        validate_error(
            api.create_work_block(payload, agent_headers), ERR_INVALID_BILLING_STATE
        )

        after = scenario.read_order(world.order_id)
        assert after["billing_status"] == "ESTIMATE_SENT", after
        assert after["work_status"] == "QUEUED", after
        technician = scenario.read_technician(world.bench_technician_id)
        assert technician["scheduled_minutes_open"] == 0, technician

    def test_payment_refused_while_billing_is_only_estimate_approved(self, api, scenario):
        """Approval unlocks the bench but a payment still needs the INVOICED state.

        "(13) An order's `billing_status` is a legal origin state, else `ERR_INVALID_BILLING_STATE` (409): issuing an estimate requires `ESTIMATE_PENDING` or `ESTIMATE_SENT` and never `NOT_BILLABLE`; scheduling a work block requires `NOT_BILLABLE` or `ESTIMATE_APPROVED`; recording a payment requires `INVOICED`."
        "On approval the estimate moves `SENT` → `APPROVED`, its `decided_at` is stamped, the order's `provisional_estimate_total_cents` is set from the estimate's `total_cents`, and the order's `billing_status` moves `ESTIMATE_SENT` → `ESTIMATE_APPROVED` — which is the moment the bench dimension is unlocked and `QUEUED` → `IN_WORK` becomes reachable."
        "A payment, available to the owner or to a `ServiceAgent`, carries an `amount_cents` that must equal `final_invoice_total_cents` minus `paid_amount_cents` precisely; anything less or more is refused with `ERR_PAYMENT_AMOUNT_MISMATCH`, and a payment attempted before invoicing is refused with `ERR_INVALID_BILLING_STATE`."
        "**Step eight** totals: `total_cents` is `subtotal_cents` minus `loyalty_discount_cents` plus `expedite_fee_cents` plus `tax_cents`."

        Design: Corner/validations/billing_state_gates_bench_work_and_payments
        """
        world = _paid_zipper_order(scenario)
        estimate = _sent_quote(world)

        scenario.approve_estimate(estimate["id"], world.customer_id)
        approved = scenario.read_estimate(estimate["id"])
        assert approved["status"] == "APPROVED", approved
        order = scenario.read_order(world.order_id)
        assert order["billing_status"] == "ESTIMATE_APPROVED", order
        assert order["provisional_estimate_total_cents"] == 7531, order

        validate_error(
            api.pay_order(
                world.order_id,
                {"amount_cents": 7531},
                make_customer_headers(world.customer_id),
            ),
            ERR_INVALID_BILLING_STATE,
        )

        after = scenario.read_order(world.order_id)
        assert after["paid_amount_cents"] == 0, after
        assert after["billing_status"] == "ESTIMATE_APPROVED", after
        assert after["final_invoice_total_cents"] is None, after
        assert scenario.read_estimate(estimate["id"])["status"] == "APPROVED"


class TestBenchCompleteOnAQueuedOrder:
    """PRD §2.11 check 12: bench-complete is only legal from IN_WORK."""

    def test_bench_complete_refused_on_an_order_with_no_blocks_of_its_own(
        self, api, open_order
    ):
        """A QUEUED order refuses the close-out even though the logged block exists.

        "Every request runs the same ordered gauntlet, and the **first** check that fails produces the response — no later check is evaluated, so a request that violates several rules always reports the earliest one."
        "(12) An order's `work_status` is a legal origin state, else `ERR_INVALID_WORK_STATE` (409); this guards work-block scheduling, bench-complete, quality-control inspection, condemnation, invoicing, release-to-customer and parts reservation."
        "(28) Every `work_block_id` in a bench-complete `work_log` belongs to the addressed order and has `status` `SCHEDULED`, else `ERR_WORK_BLOCK_NOT_ON_ORDER` (422)."
        "**Bench completion** is a `RepairTechnician` operation on an order in `work_status` `IN_WORK`, moving it `IN_WORK` → `BENCH_DONE`."
        "On success each listed block moves `SCHEDULED` → `COMPLETED` with its `actual_minutes` stamped, and for each block the technician's `scheduled_minutes_open` decreases by that block's `duration_minutes` while their `completed_minutes` increases by that block's `actual_minutes`."

        Design: Corner/validations/bench_complete_on_a_queued_order_rejected
        """
        scenario = open_order.scenario
        other_order, block = _scheduled_block_on_another_order(open_order)
        assert block["status"] == "SCHEDULED", block
        assert block["repair_order_id"] == other_order["id"], block
        assert scenario.read_order(open_order.order_id)["work_status"] == "QUEUED"

        response = api.bench_complete(
            open_order.order_id,
            {"work_log": [factories.work_log_entry(block["id"], 60)]},
            make_technician_headers(open_order.technician_id),
        )
        validate_error(response, ERR_INVALID_WORK_STATE)

        after = scenario.read_order(open_order.order_id)
        assert after["work_status"] == "QUEUED", after
        assert after["billing_status"] == "NOT_BILLABLE", after
        technician = scenario.read_technician(open_order.technician_id)
        assert technician["completed_minutes"] == 0, technician
        assert technician["scheduled_minutes_open"] == 0, technician
        assert scenario.read_work_block(block["id"])["status"] == "SCHEDULED"


class TestTradeInOnAnInRepairItem:
    """PRD §2.11 check 49: only an IRREPARABLE_HOLD unit may be traded in."""

    def test_trade_in_refused_while_the_unit_is_in_repair(self, api, open_order):
        """An IN_REPAIR unit is refused a trade-in and no credit is minted anywhere.

        "(49) A unit's `disposition_status` is `IRREPARABLE_HOLD` for a trade-in, else `ERR_ITEM_NOT_IRREPARABLE` (409)."
        "A trade-in attempted on a unit whose `disposition_status` is anything other than `IRREPARABLE_HOLD` is refused with `ERR_ITEM_NOT_IRREPARABLE`."
        "`trade_in_credit_cents` is 0 until the unit is accepted as a trade-in, `refurb_list_price_cents` is null until the same moment, and `resale_price_cents` is null until the unit is actually sold on the refurbished channel."
        "A new customer starts with `lifetime_claim_count` and `trade_in_credit_cents` at 0."

        Design: Corner/validations/trade_in_on_an_in_repair_item_rejected
        """
        scenario = open_order.scenario
        item = scenario.read_item(open_order.item_id)
        assert item["disposition_status"] == "IN_REPAIR", item

        response = api.trade_in_gear_item(
            open_order.item_id,
            {"condition_grade": "B"},
            make_customer_headers(open_order.customer_id),
        )
        validate_error(response, ERR_ITEM_NOT_IRREPARABLE)

        after = scenario.read_item(open_order.item_id)
        assert after["disposition_status"] == "IN_REPAIR", after
        assert after["trade_in_credit_cents"] == 0, after
        assert after["refurb_list_price_cents"] is None, after
        assert after["condition_grade"] == "B", after

        owner = scenario.read_customer(open_order.customer_id)
        assert owner["trade_in_credit_cents"] == 0, owner
        assert scenario.read_claim(open_order.claim_id)["status"] == "WARRANTY_APPROVED"

        entries = scenario.liability_entries(open_order.claim_id)
        assert len(entries) == 1, entries
        assert entries[0]["status"] == "OPEN", entries[0]
        assert entries[0]["reserved_amount_cents"] == 22390, entries[0]
        assert_center_posture(scenario.read_center(open_order.center_id), 22390)
