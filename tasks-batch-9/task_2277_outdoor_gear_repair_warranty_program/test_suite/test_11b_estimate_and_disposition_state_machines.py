"""Corner cases on the money dimension and the resale channel.

Two state machines are exercised here. The first is the estimate's own
lifecycle and the `billing_status` cycle it drives on the repair order — the
decline unwind, the queue-review expiry sweep, the re-quote self-loop and the
two single-shot guards on approval (PRD §3.7, §3.9). The second is the gear
unit's afterlife: trade-in, refurbished listing, resale and recycling, plus the
surge-window retirement and reservation-settlement guards that share the same
checkpoint machinery (PRD §3.8, §3.9).
"""

from test_helpers import (
    ERR_ESTIMATE_ALREADY_APPROVED,
    ERR_ESTIMATE_EXPIRED,
    ERR_INVALID_DISPOSITION_STATE,
    ERR_INVALID_ESTIMATE_STATE,
    ERR_RESERVATION_NOT_RESERVED,
    PARTS_COORDINATOR_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    SERVICE_AGENT_HEADERS,
    assert_center_posture,
    assert_estimate_breakdown,
    assert_multiplier,
    assert_part_lot_counts,
    assert_pct,
    assert_timestamp_millis,
    factories,
    make_customer_headers,
    make_technician_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_QUOTE_UTC = "2026-06-15T09:00:00Z"
CLOCK_AFTER_VALIDITY_UTC = "2026-06-23T09:00:00Z"
CLOCK_AFTER_WINDOW_UTC = "2026-07-05T09:00:00Z"


def _assert_stamped_at(value, instant_prefix):
    """Assert a stamped timestamp carries millis and sits on the logical clock."""
    assert value is not None, "expected a stamped timestamp, got null"
    assert_timestamp_millis(value)
    assert value.startswith(instant_prefix), f"expected {instant_prefix}*, got {value}"


def _zipper_paid_order(catalogue):
    """A PAID_REPAIR order on the registered unit quoted for ZIPPER work alone.

    Built entirely through the PRD-declared endpoints: a zipper lot of four
    units at 1800 cents, a `PAID_REPAIR_REQUEST` intake, a `USER_DAMAGE` bench
    finding on the single `ZIPPER` lane, the derived paid-repair adjudication
    and the repair order that follows it.
    """
    scenario = catalogue.scenario
    zip_lot = scenario.part_lot(
        catalogue.model_id,
        part_code=factories.ZIP_PART_CODE,
        part_kind="ZIPPER_SLIDER",
        on_hand_units=4,
        unit_price_cents=1800,
        low_watermark_units=1,
    )
    claim = scenario.claim(
        catalogue.center_id,
        catalogue.item_id,
        intake_kind="PAID_REPAIR_REQUEST",
        reported_defect_type="ZIPPER_FAILURE",
        customer_narrative="Slider chewed after a fall.",
    )
    submitted = scenario.submit(claim["id"])
    scenario.assess(
        claim["id"],
        catalogue.technician_id,
        expected_claim_version=submitted["version"],
        determination="USER_DAMAGE",
        required_work_types=["ZIPPER"],
        estimated_labor_lines=[factories.labor_line("ZIPPER", 35)],
        estimated_parts_cents=1800,
        defect_notes="Impact damage, not a defect.",
    )
    scenario.decide(claim["id"], decision_note="User damage: quote as paid repair.")
    order = scenario.repair_order(claim["id"])
    catalogue.update(
        zip_lot=zip_lot,
        zip_lot_id=zip_lot["id"],
        claim_id=claim["id"],
        order=order,
        order_id=order["id"],
    )
    return catalogue


def _zipper_paid_order_with_quote(catalogue):
    """The zipper paid order quoted once: 35 zipper minutes plus one 1800c line."""
    world = _zipper_paid_order(catalogue)
    estimate = world.scenario.estimate(
        world.order_id,
        expected_repair_order_version=world.order["version"],
        labor_lines=[factories.labor_line("ZIPPER", 35)],
        parts_lines=[factories.parts_line(factories.ZIP_PART_CODE, 1, 1800)],
    )
    world.update(estimate=estimate, estimate_id=estimate["id"])
    return world


def _replacement_authorized_world(scenario):
    """A discontinued model with no part lots anywhere, adjudicated to replace.

    `parts_support_status` is therefore `NO_SUPPORT`, so the `MANUFACTURING_DEFECT`
    finding resolves `WARRANTY_REPLACE` and parks the unit in `IRREPARABLE_HOLD`
    with an open successor-MSRP reservation against the centre (PRD §3.5).
    """
    scenario.set_clock(CLOCK_QUOTE_UTC)
    center = scenario.center()
    successor = scenario.successor_model()
    model = scenario.model(
        discontinued_at="2024-03-01T00:00:00Z", successor_model_id=successor["id"]
    )
    customer = scenario.customer()
    item = scenario.gear_item(model["id"], customer["id"])
    technician = scenario.technician(
        center["id"], certifications=[factories.certification("FABRIC", 3)]
    )
    claim = scenario.claim(center["id"], item["id"])
    submitted = scenario.submit(claim["id"])
    scenario.assess(
        claim["id"],
        technician["id"],
        expected_claim_version=submitted["version"],
    )
    decided = scenario.decide(
        claim["id"], decision_note="No parts remain for this generation."
    )
    return {
        "center_id": center["id"],
        "model_id": model["id"],
        "customer_id": customer["id"],
        "item_id": item["id"],
        "technician_id": technician["id"],
        "claim_id": claim["id"],
        "claim": decided,
    }


class TestEstimateLifecycleMachine:
    """PRD §3.7, §3.9 — the quote's own states and the billing cycle they drive."""

    def test_decline_unwinds_order_item_claim_and_reserved_parts(self, catalogue):
        """One customer decline moves the estimate, order, reservation, lot, unit and claim.

        "Declining takes an optional `decline_reason` and moves the estimate `SENT` → `DECLINED`."
        "Because a re-quote supersedes its predecessor, the estimate being declined is by construction the order's only `PROVISIONAL` row still in `SENT`, and declining it therefore unwinds the whole order: the order's `billing_status` becomes `ESTIMATE_DECLINED` and its `work_status` moves from `QUEUED` or `IN_WORK` to `CLOSED_UNREPAIRED`, every reservation on the order still in `RESERVED` is released with the full lot-and-model give-back chain described in §3.8, every work block on the order still in `SCHEDULED` is cancelled with its minutes given back to its technician, the unit moves `IN_REPAIR` → `RETURNED` and is shipped back unrepaired, and the claim closes `PAID_REPAIR_OFFERED` → `CLOSED_DECLINED`."
        "Alternatively a `PartsCoordinator` **releases** it with an optional `reason`, moving it `RESERVED` → `RELEASED`, stamping `settled_at`, and decreasing only the lot's `reserved_units` by `units`, so `available_units` rises by that many units while `on_hand_units` is untouched; again the lot's `status` and then the model's `parts_support_status` are re-derived."
        "`active_queue_depth` itself is defined as the count of the centre's repair orders whose `work_status` is `QUEUED`, `IN_WORK` or `BENCH_DONE`."

        Design: Corner/state_machines/estimate_decline_cascades_across_order_item_claim_and_parts
        """
        world = _zipper_paid_order(catalogue)
        scenario = world.scenario
        reservation = scenario.reserve_parts(
            world.order_id, world.zip_lot_id, factories.ZIP_PART_CODE, 1
        )
        estimate = scenario.estimate(
            world.order_id,
            labor_lines=[factories.labor_line("ZIPPER", 35)],
            parts_lines=[factories.parts_line(factories.ZIP_PART_CODE, 1, 1800)],
        )

        declined = validate_success(
            scenario.api.decline_estimate(
                estimate["id"],
                make_customer_headers(world.customer_id),
                {"decline_reason": "Not worth it."},
            )
        )
        assert declined["status"] == "DECLINED", declined
        _assert_stamped_at(declined["decided_at"], "2026-06-15T09:00:00")

        order = scenario.read_order(world.order_id)
        assert order["work_status"] == "CLOSED_UNREPAIRED", order
        assert order["billing_status"] == "ESTIMATE_DECLINED", order
        assert order["final_invoice_total_cents"] is None, order

        settled = scenario.read_reservation(reservation["id"])
        assert settled["status"] == "RELEASED", settled
        _assert_stamped_at(settled["settled_at"], "2026-06-15T09:00:00")

        assert_part_lot_counts(
            scenario.read_lot(world.zip_lot_id),
            on_hand_units=4,
            reserved_units=0,
            available_units=4,
            status="AVAILABLE",
        )

        assert scenario.read_item(world.item_id)["disposition_status"] == "RETURNED"
        assert scenario.read_claim(world.claim_id)["status"] == "CLOSED_DECLINED"
        assert scenario.read_center(world.center_id)["active_queue_depth"] == 0

    def test_queue_review_expires_the_quote_and_reopens_estimate_pending(
        self, catalogue
    ):
        """The sweep flips the stale quote to EXPIRED and rewinds billing to ESTIMATE_PENDING.

        "The new row's `valid_until` is the logical clock instant advanced by seven days, and its `decided_at` is null until the customer answers."
        "The checkpoint described in §3.9 expires any `PROVISIONAL` estimate whose `status` is `SENT` and whose `valid_until` has fallen behind the logical clock, moving it `SENT` → `EXPIRED` and returning the order's `billing_status` `ESTIMATE_SENT` → `ESTIMATE_PENDING` so that a fresh quote can be issued."
        "It flags every repair order at the centre whose `work_status` is non-terminal and whose `promised_return_at` has fallen behind the logical clock by setting that order's `commitment_breached` to true."
        "`last_queue_review_at` is set to the logical clock instant."

        Design: Corner/state_machines/queue_review_expiry_sweep_reverts_billing_to_estimate_pending
        """
        world = _zipper_paid_order_with_quote(catalogue)
        scenario = world.scenario
        assert world.estimate["valid_until"].startswith("2026-06-22T09:00:00")
        assert world.estimate["total_cents"] == 7531, world.estimate

        scenario.set_clock(CLOCK_AFTER_VALIDITY_UTC)
        scenario.queue_review(world.center_id)

        estimate = scenario.read_estimate(world.estimate_id)
        assert estimate["status"] == "EXPIRED", estimate
        assert estimate["total_cents"] == 7531, estimate

        order = scenario.read_order(world.order_id)
        assert order["billing_status"] == "ESTIMATE_PENDING", order
        assert order["work_status"] == "QUEUED", order
        assert order["provisional_estimate_total_cents"] is None, order
        assert order["commitment_breached"] is False, order
        assert order["promised_return_at"] == "2026-06-30T23:59:59.999Z", order

        center = scenario.read_center(world.center_id)
        _assert_stamped_at(center["last_queue_review_at"], "2026-06-23T09:00:00")
        assert center["active_queue_depth"] == 1, center
        assert_multiplier(center["current_surge_multiplier"], 1.00)
        assert center["breached_commitment_count"] == 0, center

    def test_approve_past_validity_without_a_sweep_is_expired(self, catalogue):
        """Validity is enforced on the approve path itself, with the row still SENT.

        "Approval requires the estimate's `status` to be `SENT` and the logical clock instant to be at or before its `valid_until`, refusing a late approval with `ERR_ESTIMATE_EXPIRED`."
        "(35) The logical clock instant is at or before an estimate's `valid_until` when approving, else `ERR_ESTIMATE_EXPIRED` (409)."

        Design: Corner/state_machines/estimate_approve_after_validity_without_sweep_rejected
        """
        world = _zipper_paid_order_with_quote(catalogue)
        scenario = world.scenario
        scenario.set_clock(CLOCK_AFTER_VALIDITY_UTC)

        response = scenario.api.approve_estimate(
            world.estimate_id, make_customer_headers(world.customer_id)
        )
        validate_error(response, ERR_ESTIMATE_EXPIRED)

        estimate = scenario.read_estimate(world.estimate_id)
        assert estimate["status"] == "SENT", estimate
        assert estimate["decided_at"] is None, estimate

        order = scenario.read_order(world.order_id)
        assert order["billing_status"] == "ESTIMATE_SENT", order
        assert order["provisional_estimate_total_cents"] is None, order

    def test_requote_supersedes_the_prior_sent_row_and_reprices(self, catalogue):
        """The billing dimension self-loops: the first quote is superseded, the second is SENT.

        "Issuing a customer-facing quote is a `ServiceAgent` operation on a paid order, permitted while `billing_status` is `ESTIMATE_PENDING` (the first quote, `ESTIMATE_PENDING` → `ESTIMATE_SENT`) or `ESTIMATE_SENT` (a re-quote, the self-loop `ESTIMATE_SENT` → `ESTIMATE_SENT`)."
        "On success any prior estimate on the order whose `status` was `SENT` becomes `SUPERSEDED`, a new estimate row is created with `variant` `PROVISIONAL` and `status` `SENT` and a `repair_order_id` pointing at the order, the order's `billing_status` becomes `ESTIMATE_SENT`, and the order's `version` increases by one."
        "The hourly rates are 8500 cents for `FABRIC`, 9500 cents for `ZIPPER`, 11000 cents for `FRAME` and 9000 cents for `INSULATION`."
        "The new row's `valid_until` is the logical clock instant advanced by seven days, and its `decided_at` is null until the customer answers."

        Design: Corner/state_machines/requote_supersedes_prior_sent_estimate
        """
        world = _zipper_paid_order_with_quote(catalogue)
        scenario = world.scenario
        version_before_requote = scenario.order_version(world.order_id)

        second = validate_success(
            scenario.api.create_estimate(
                world.order_id,
                factories.estimate_payload(
                    version_before_requote,
                    labor_lines=[factories.labor_line("ZIPPER", 50)],
                    parts_lines=[
                        factories.parts_line(factories.ZIP_PART_CODE, 1, 1800)
                    ],
                ),
                SERVICE_AGENT_HEADERS,
            ),
            expected_status=201,
        )

        assert scenario.read_estimate(world.estimate_id)["status"] == "SUPERSEDED"
        assert second["status"] == "SENT", second
        assert second["variant"] == "PROVISIONAL", second
        assert second["valid_until"].startswith("2026-06-22T09:00:00")
        assert_estimate_breakdown(
            second,
            labor_subtotal_cents=7917,
            parts_subtotal_cents=1800,
            shop_supply_fee_cents=554,
            subtotal_cents=10271,
            loyalty_discount_cents=1027,
            expedite_fee_cents=0,
            tax_cents=763,
            total_cents=10007,
        )

        order = scenario.read_order(world.order_id)
        assert order["billing_status"] == "ESTIMATE_SENT", order
        assert order["version"] == version_before_requote + 1, order

        rows, _meta = validate_paginated(
            scenario.api.list_order_estimates(world.order_id, SERVICE_AGENT_HEADERS)
        )
        sent = [row for row in rows if row["status"] == "SENT"]
        assert len(sent) == 1, rows
        assert sent[0]["id"] == second["id"], rows

    def test_second_approve_is_refused_and_leaves_the_first_decision_intact(
        self, catalogue
    ):
        """Approve is single-shot: the second call finds APPROVED, not SENT.

        "(14) An estimate's `status` is `SENT` for approve or decline, else `ERR_INVALID_ESTIMATE_STATE` (409)."
        "On approval the estimate moves `SENT` → `APPROVED`, its `decided_at` is stamped, the order's `provisional_estimate_total_cents` is set from the estimate's `total_cents`, and the order's `billing_status` moves `ESTIMATE_SENT` → `ESTIMATE_APPROVED` — which is the moment the bench dimension is unlocked and `QUEUED` → `IN_WORK` becomes reachable."

        Design: Corner/state_machines/estimate_second_approve_rejected
        """
        world = _zipper_paid_order_with_quote(catalogue)
        scenario = world.scenario
        scenario.approve_estimate(world.estimate_id, world.customer_id)

        response = scenario.api.approve_estimate(
            world.estimate_id, make_customer_headers(world.customer_id)
        )
        validate_error(response, ERR_INVALID_ESTIMATE_STATE)

        estimate = scenario.read_estimate(world.estimate_id)
        assert estimate["status"] == "APPROVED", estimate
        _assert_stamped_at(estimate["decided_at"], "2026-06-15T09:00:00")

        order = scenario.read_order(world.order_id)
        assert order["billing_status"] == "ESTIMATE_APPROVED", order
        assert order["provisional_estimate_total_cents"] == 7531, order

    def test_requote_after_approval_reports_its_own_cause(self, catalogue):
        """A re-quote on an approved order is refused for approval, not for billing state.

        "It also requires that no estimate on the order has `status` `APPROVED`: once a customer has said yes, re-quoting is refused with `ERR_ESTIMATE_ALREADY_APPROVED`."
        "The `ESTIMATE_APPROVED` case for estimate issuance is deliberately carved out of this check and answered later by check 40, so that a re-quote after approval reports its own cause; and this check does not apply to invoicing at all, whose billing gate is check 50."

        Design: Corner/state_machines/requote_after_approval_rejected
        """
        world = _zipper_paid_order_with_quote(catalogue)
        scenario = world.scenario
        scenario.approve_estimate(world.estimate_id, world.customer_id)
        version_after_approval = scenario.order_version(world.order_id)

        response = scenario.api.create_estimate(
            world.order_id,
            factories.estimate_payload(
                version_after_approval,
                labor_lines=[factories.labor_line("ZIPPER", 50)],
            ),
            SERVICE_AGENT_HEADERS,
        )
        validate_error(response, ERR_ESTIMATE_ALREADY_APPROVED)

        assert scenario.read_estimate(world.estimate_id)["status"] == "APPROVED"

        order = scenario.read_order(world.order_id)
        assert order["billing_status"] == "ESTIMATE_APPROVED", order
        assert order["provisional_estimate_total_cents"] == 7531, order
        assert order["version"] == version_after_approval, order

        rows, meta = validate_paginated(
            scenario.api.list_order_estimates(world.order_id, SERVICE_AGENT_HEADERS)
        )
        assert meta["total_count"] == 1, meta
        assert len(rows) == 1, rows


class TestDispositionMachine:
    """PRD §3.9 — the afterlife of a condemned unit through the resale channel."""

    def test_trade_in_then_refurb_listing_then_resale(self, scenario):
        """Three hops across two endpoints price the credit, list the unit and sell it.

        "The credit is a decay function on the depreciated basis: the base credit is the unit's `replacement_value_depreciated_cents` multiplied by the grade's rate — thirty-five percent for grade `A`, twenty-two percent for grade `B` and twelve percent for grade `C` — rounded half up."
        "The unit's `trade_in_credit_cents` is the lesser of 40000 cents and the base credit plus the goodwill bonus — the cap is applied **after** the bonus is added, never before."
        "At the same moment the unit's `refurb_list_price_cents` is set to its `replacement_value_successor_cents` multiplied by fifty-five percent, rounded half up."
        "The unit moves `IRREPARABLE_HOLD` → `TRADED_IN`, the owner's `trade_in_credit_cents` increases by the credit just granted, and the driving claim closes — `WARRANTY_APPROVED` → `CLOSED_REPLACED` or `REPLACEMENT_AUTHORIZED` → `CLOSED_REPLACED` — with every open liability entry on that claim moving to `RELEASED` with `release_reason` `CLAIM_CLOSED` and `released_at` stamped, after which the centre's `open_liability_cents` decreases by the released amounts and `liability_posture` is re-derived."
        "From `REFURB_LISTED` it may go to `RESOLD`, which requires a `sale_price_cents` in the body and stamps it onto the unit's `resale_price_cents`, or to `RECYCLED`, which strips it for parts and removes it from the resale channel."

        Design: Corner/state_machines/irreparable_item_trade_in_refurb_listing_and_resale_walk
        """
        world = _replacement_authorized_world(scenario)

        claim = world["claim"]
        assert claim["status"] == "REPLACEMENT_AUTHORIZED", claim
        assert claim["decision"] == "WARRANTY_REPLACE", claim
        assert_pct(claim["repair_ratio_pct"], 24.90)
        assert claim["decision_threshold_pct"] == 55, claim
        assert (
            scenario.read_item(world["item_id"])["disposition_status"]
            == "IRREPARABLE_HOLD"
        )
        entries = scenario.liability_entries(world["claim_id"])
        assert len(entries) == 1, entries
        assert entries[0]["basis"] == "REPLACEMENT", entries[0]
        assert entries[0]["valuation_variant"] == "SUCCESSOR_MSRP", entries[0]
        assert entries[0]["status"] == "OPEN", entries[0]
        assert entries[0]["reserved_amount_cents"] == 89910, entries[0]

        traded = validate_success(
            scenario.api.trade_in_gear_item(
                world["item_id"], {"condition_grade": "B"}, SERVICE_AGENT_HEADERS
            )
        )
        assert traded["disposition_status"] == "TRADED_IN", traded
        assert traded["trade_in_credit_cents"] == 16535, traded
        assert traded["refurb_list_price_cents"] == 49451, traded
        assert traded["resale_price_cents"] is None, traded

        owner = scenario.read_customer(world["customer_id"])
        assert owner["trade_in_credit_cents"] == 16535, owner
        assert scenario.read_claim(world["claim_id"])["status"] == "CLOSED_REPLACED"

        released = scenario.liability_entries(world["claim_id"])
        assert len(released) == 1, released
        assert released[0]["status"] == "RELEASED", released[0]
        assert released[0]["release_reason"] == "CLAIM_CLOSED", released[0]
        assert_center_posture(
            scenario.read_center(world["center_id"]),
            open_liability_cents=0,
            utilization_pct=0.00,
            posture="OPEN",
        )

        listed = scenario.disposition(world["item_id"], "REFURB_LISTED")
        assert listed["disposition_status"] == "REFURB_LISTED", listed
        assert listed["resale_price_cents"] is None, listed

        sold = scenario.disposition(world["item_id"], "RESOLD", sale_price_cents=45000)
        assert sold["disposition_status"] == "RESOLD", sold
        assert sold["resale_price_cents"] == 45000, sold
        assert sold["refurb_list_price_cents"] == 49451, sold

    def test_traded_in_unit_cannot_skip_to_resold_but_may_be_recycled(self, scenario):
        """From TRADED_IN only REFURB_LISTED and RECYCLED are legal hops.

        "(16) A unit's `disposition_status` permits the requested resale-channel hop — `TRADED_IN` to `REFURB_LISTED` or `RECYCLED`, and `REFURB_LISTED` to `RESOLD` or `RECYCLED` — else `ERR_INVALID_DISPOSITION_STATE` (409)."
        "From `TRADED_IN` the unit may go to `REFURB_LISTED`, which lists it on the refurbished channel at its `refurb_list_price_cents`, or straight to `RECYCLED`."
        "Any other hop is refused with `ERR_INVALID_DISPOSITION_STATE`."

        Design: Corner/state_machines/traded_in_item_cannot_skip_to_resold_but_may_recycle
        """
        world = _replacement_authorized_world(scenario)
        validate_success(
            scenario.api.trade_in_gear_item(
                world["item_id"], {"condition_grade": "B"}, SERVICE_AGENT_HEADERS
            )
        )

        response = scenario.api.set_gear_item_disposition(
            world["item_id"],
            {"to": "RESOLD", "sale_price_cents": 45000},
            PARTS_COORDINATOR_HEADERS,
        )
        validate_error(response, ERR_INVALID_DISPOSITION_STATE)

        unchanged = scenario.read_item(world["item_id"])
        assert unchanged["disposition_status"] == "TRADED_IN", unchanged
        assert unchanged["resale_price_cents"] is None, unchanged

        recycled = scenario.disposition(world["item_id"], "RECYCLED")
        assert recycled["disposition_status"] == "RECYCLED", recycled
        assert recycled["resale_price_cents"] is None, recycled
        assert recycled["refurb_list_price_cents"] == 49451, recycled
        assert recycled["trade_in_credit_cents"] == 16535, recycled
        assert scenario.read_claim(world["claim_id"])["status"] == "CLOSED_REPLACED"


class TestCheckpointAndSettlementGuards:
    """PRD §3.1, §3.8, §3.9 — surge retirement and single-shot part settlement."""

    def test_surge_window_stays_active_until_a_queue_review_observes_it(self, scenario):
        """The window's status is not time-derived on read: only the checkpoint retires it.

        "Its `status` begins as `ACTIVE` and becomes `RETIRED` once a queue-review observes that its `end_date` has fallen behind the logical clock."
        "It retires every surge window whose `end_date` has fallen behind the logical clock, moving its `status` `ACTIVE` → `RETIRED`."
        "`last_queue_review_at` is set to the logical clock instant."

        Design: Corner/state_machines/surge_window_retired_by_queue_review_after_end_date
        """
        scenario.set_clock(CLOCK_QUOTE_UTC)
        center = scenario.center()
        window = scenario.surge_window(
            center["id"],
            label="Summer peak",
            start_date="2026-06-20T00:00:00Z",
            end_date="2026-06-30T23:59:59Z",
            multiplier=1.50,
        )
        assert window["status"] == "ACTIVE", window

        scenario.set_clock(CLOCK_AFTER_WINDOW_UTC)

        before, before_meta = validate_paginated(
            scenario.api.list_surge_windows(center["id"], PROGRAM_ADMIN_HEADERS)
        )
        assert before_meta["total_count"] == 1, before_meta
        assert before[0]["id"] == window["id"], before
        assert before[0]["status"] == "ACTIVE", before[0]

        scenario.queue_review(center["id"])

        after, after_meta = validate_paginated(
            scenario.api.list_surge_windows(center["id"], PROGRAM_ADMIN_HEADERS)
        )
        assert after_meta["total_count"] == 1, after_meta
        assert after[0]["id"] == window["id"], after
        assert after[0]["status"] == "RETIRED", after[0]

        reviewed = scenario.read_center(center["id"])
        assert_multiplier(reviewed["current_surge_multiplier"], 1.00)
        assert reviewed["active_queue_depth"] == 0, reviewed
        _assert_stamped_at(reviewed["last_queue_review_at"], "2026-07-05T09:00:00")

    def test_second_consume_is_refused_and_draws_no_second_time(self, open_order):
        """Consume is single-shot: CONSUMED is settled, so on_hand_units stays at 3.

        "A `RepairTechnician` **consumes** it — permitted while its `status` is `RESERVED` and the order's `work_status` is `QUEUED`, `IN_WORK` or `BENCH_DONE` — moving it `RESERVED` → `CONSUMED`, stamping `settled_at`, and decreasing **both** the lot's `on_hand_units` and its `reserved_units` by `units`, so `available_units` does not change; the lot's `status` is re-derived and then the model's `parts_support_status`."
        "Release or consume attempted on a reservation that has already settled is refused with `ERR_RESERVATION_NOT_RESERVED`."
        "(15) A reservation's `status` is `RESERVED` for release or consume, else `ERR_RESERVATION_NOT_RESERVED` (409)."

        Design: Corner/state_machines/reservation_second_consume_rejected
        """
        scenario = open_order.scenario
        reservation = scenario.reserve_parts(
            open_order.order_id, open_order.panel_lot_id, factories.PANEL_PART_CODE, 2
        )
        scenario.consume_parts(reservation["id"], open_order.technician_id)

        response = scenario.api.consume_parts_reservation(
            reservation["id"], make_technician_headers(open_order.technician_id)
        )
        validate_error(response, ERR_RESERVATION_NOT_RESERVED)

        settled = scenario.read_reservation(reservation["id"])
        assert settled["status"] == "CONSUMED", settled
        assert settled["units"] == 2, settled
        _assert_stamped_at(settled["settled_at"], "2026-06-15T09:00:00")

        assert_part_lot_counts(
            scenario.read_lot(open_order.panel_lot_id),
            on_hand_units=3,
            reserved_units=0,
            available_units=3,
            status="AVAILABLE",
        )
        assert (
            scenario.read_model(open_order.model_id)["parts_support_status"]
            == "SUPPORTED"
        )
