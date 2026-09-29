"""Label registration, the reporting quarter and the commodity batch.

Each of these machines has a terminal state that closes a door for good, and
each records something on the way through — a coverage determination, a pair of
settlement lines, a revenue line — that must survive the lock-down.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    assert_stamped_at,
    make_distributor_headers,
)
from test_helpers import factories as f
from test_helpers import fixtures as h

INSTANT = "2026-08-05T09:00:00Z"


class TestLabelWalkToRegistered:
    """SUBMIT decides coverage; APPROVE stamps the registration."""

    def test_submit_then_approve_walks_draft_to_registered(self, api):
        """Coverage and the deposit land on submission, registered_at on approval.

        PRD: "Submitting a `DRAFT` label advances it `DRAFT → SUBMITTED`."

        PRD: "Approval by a `ProgramAdmin` advances the label `SUBMITTED → REGISTERED`.
        Approval is only available when the coverage determination came out `COVERED`; a
        `NOT_COVERED` label is refused with `ERR_PRODUCT_NOT_COVERED`. On success the server
        stamps `registered_at` with the current logical instant and clears `rejection_reason`
        to null."

        Design: Corner/state_machines/label_submit_then_approve_walks_draft_to_registered
        """
        h.set_clock(api, INSTANT)
        distributor = h.create_distributor(api)
        product = h.create_draft_product(api, distributor["id"])
        distributor_headers = make_distributor_headers(distributor["id"])

        submitted = validate_success(
            api.post_registration_action(
                product["id"],
                f.registration_action_payload("SUBMIT"),
                distributor_headers,
            )
        )
        assert submitted["registration_state"] == "SUBMITTED"
        assert submitted["coverage_status"] == "COVERED"
        assert submitted["coverage_reason"] == "COVERED_STANDARD"
        assert submitted["deposit_cents"] == 10
        assert submitted["registered_at"] is None
        assert submitted["version"] == 2

        registered = validate_success(
            api.post_registration_action(
                product["id"], f.registration_action_payload("APPROVE"), ADMIN_HEADERS
            )
        )
        assert registered["registration_state"] == "REGISTERED"
        assert_stamped_at(registered["registered_at"], INSTANT)
        assert registered["rejection_reason"] is None
        assert registered["version"] == 3


class TestDeclaredInitialStates:
    """Six machines, six different initial states, all at version 1."""

    def test_new_rows_start_in_their_declared_initial_states(self, api):
        """A label, a centre, a machine, an account, a quarter and a store are all fresh.

        PRD: "A newly created label sits in `registration_state` `DRAFT` with
        `deposit_cents` at 0 and no coverage determination yet made; `coverage_status` and
        `coverage_reason` are only written when the label is first submitted."

        PRD: "Installation records the machine's `center_id`, opens it in `status` `IDLE`
        with `bin_filled_count` at 0 and `jam_count_today` at 0, recomputes the hosting
        centre's `machine_count`, and increments the centre's `version`."

        PRD: "A new account opens in `status` `ACTIVE` with `credit_balance_cents` at 0 and
        `fraud_strikes` at 0."

        PRD: "A new store's `obligation_status` is `OBLIGATED`, with `nearest_center_id`,
        `nearest_center_distance_miles` and `exemption_granted_at` all null."

        Design: Corner/state_machines/new_rows_start_in_their_declared_initial_states
        """
        h.set_clock(api, INSTANT)
        distributor = h.create_distributor(api)

        product = h.create_draft_product(api, distributor["id"])
        center = h.create_center(api, site_name="Bend Redemption Center")
        machine = h.install_machine(api, center["id"])
        account = h.create_account(api)
        period = h.create_period(api)
        retailer = h.create_retailer(
            api, store_name="Bend Market", x_miles=1.0, y_miles=1.0, store_area_sqft=6000
        )

        assert product["registration_state"] == "DRAFT"
        assert center["status"] == "PROVISIONAL"
        assert machine["status"] == "IDLE"
        assert account["status"] == "ACTIVE"
        assert period["status"] == "OPEN"
        assert period["funding_status"] == "UNSETTLED"
        assert retailer["obligation_status"] == "OBLIGATED"
        assert retailer["nearest_center_id"] is None

        for row in (product, center, machine, account, period, retailer):
            assert row["version"] == 1


class TestWithdrawnLabelIsLocked:
    """WITHDRAWN accepts no registration action and carries no deposit."""

    @staticmethod
    def _withdrawn_label(api):
        h.set_clock(api, INSTANT)
        period = h.create_period(api, operating_cost_cents=1000)
        distributor = h.create_distributor(api)
        product = h.create_registered_product(api, distributor["id"])
        headers = make_distributor_headers(distributor["id"])
        validate_success(
            api.post_registration_action(
                product["id"], f.registration_action_payload("WITHDRAW"), headers
            )
        )
        return period, distributor, product, headers

    def test_every_further_registration_action_is_refused(self, api):
        """SUBMIT, SUSPEND and a second WITHDRAW all report the same state error.

        PRD: "Requesting an action that is not declared from the label's current state is
        refused with `ERR_INVALID_REGISTRATION_STATE`."

        Design: Corner/state_machines/withdrawn_label_is_locked_and_blocks_deposit_initiation
        """
        _, _, product, headers = self._withdrawn_label(api)

        for action, actor in (
            ("SUBMIT", headers),
            ("SUSPEND", ADMIN_HEADERS),
            ("WITHDRAW", headers),
        ):
            response = api.post_registration_action(
                product["id"], f.registration_action_payload(action), actor
            )
            validate_error(
                response,
                ApiErrorId.ERR_INVALID_REGISTRATION_STATE.value,
                expected_status=409,
            )

        stored = validate_success(api.get_beverage_product(product["id"], headers))
        assert stored["registration_state"] == "WITHDRAWN"
        assert stored["deposit_cents"] == 0
        assert stored["version"] == 4

    def test_deposit_initiation_against_it_is_refused_as_unregistered(self, api):
        """The initiation fails the separate registration check and writes no ledger line.

        PRD: "The label named by `product_id` has `registration_state` `REGISTERED` →
        otherwise `ERR_PRODUCT_NOT_REGISTERED` (HTTP 422)."

        Design: Corner/state_machines/withdrawn_label_is_locked_and_blocks_deposit_initiation
        """
        period, distributor, product, headers = self._withdrawn_label(api)

        response = api.create_deposit_initiation(
            distributor["id"],
            f.deposit_initiation_payload(product["id"], 100, period["id"]),
            headers,
        )
        validate_error(
            response,
            ApiErrorId.ERR_PRODUCT_NOT_REGISTERED.value,
            expected_status=422,
        )

        stored_period = h.read_period(api, period["id"])
        assert stored_period["deposits_initiated_cents"] == 0
        assert stored_period["outstanding_liability_cents"] == 0

        _, meta = validate_paginated(
            api.list_ledger_entries(period["id"], ADMIN_HEADERS)
        )
        assert meta["total_count"] == 0


class TestRejectedLabelResubmission:
    """The rejection reason outlives the resubmission."""

    def test_rejection_reason_survives_until_approval_clears_it(self, api):
        """REJECT records the reason, SUBMIT keeps it, APPROVE clears it.

        PRD: "Rejection by a `ProgramAdmin` moves the label `SUBMITTED → REJECTED` and
        records the supplied `reason` into `rejection_reason`."

        PRD: "Resubmitting a rejected label moves it `REJECTED → SUBMITTED` and re-runs the
        covered-container test, so a corrected volume or material genuinely changes the
        outcome."

        Design: Corner/state_machines/rejected_label_resubmission_keeps_rejection_reason_until_approve
        """
        h.set_clock(api, INSTANT)
        distributor = h.create_distributor(api)
        product = h.create_draft_product(
            api,
            distributor["id"],
            brand_name="Cascade Cola",
            beverage_type="CARBONATED_SOFT_DRINK",
            container_material="ALUMINUM",
            fill_volume_ml=355,
            upc="011110000002",
        )
        headers = make_distributor_headers(distributor["id"])
        h.submit_product(api, product["id"], distributor["id"])

        rejected = validate_success(
            api.post_registration_action(
                product["id"],
                f.registration_action_payload("REJECT", "label artwork illegible"),
                ADMIN_HEADERS,
            )
        )
        assert rejected["registration_state"] == "REJECTED"
        assert rejected["rejection_reason"] == "label artwork illegible"

        resubmitted = validate_success(
            api.post_registration_action(
                product["id"], f.registration_action_payload("SUBMIT"), headers
            )
        )
        assert resubmitted["registration_state"] == "SUBMITTED"
        assert resubmitted["coverage_status"] == "COVERED"
        assert resubmitted["coverage_reason"] == "COVERED_STANDARD"
        assert resubmitted["deposit_cents"] == 10
        assert resubmitted["rejection_reason"] == "label artwork illegible"
        assert resubmitted["registered_at"] is None

        approved = validate_success(
            api.post_registration_action(
                product["id"], f.registration_action_payload("APPROVE"), ADMIN_HEADERS
            )
        )
        assert approved["registration_state"] == "REGISTERED"
        assert approved["rejection_reason"] is None
        assert_stamped_at(approved["registered_at"], INSTANT)
        assert approved["version"] == 5


class TestClosedQuarterIsSettledForGood:
    """CLOSED refuses period actions and every further ledger append."""

    @staticmethod
    def _closed_quarter_with_a_registered_label(api):
        h.set_clock(api, INSTANT)
        period = h.create_period(api, operating_cost_cents=0)
        distributor = h.create_distributor(api)
        product = h.create_registered_product(api, distributor["id"])
        h.period_action(api, period["id"], "RECONCILE")
        h.period_action(api, period["id"], "CLOSE")
        return period, distributor, product

    def test_reopen_reconcile_and_a_ledger_append_all_report_the_period_state(
        self, api
    ):
        """The quarter is terminal in both directions and takes no new line.

        PRD: "Closing — `CLOSE` — moves the quarter `RECONCILING → CLOSED`, which is
        terminal and settles the books for good; it has no effect beyond the transition
        itself and the `version` increment every period action carries."

        PRD: "A period action not declared from the quarter's current `status` is refused
        with `ERR_INVALID_PERIOD_STATE`, as is any attempt to append a deposit ledger line —
        a deposit initiation, a payment, a reversal, a bag-drop credit or a batch sale — to a
        quarter that is not `OPEN`."

        Design: Corner/state_machines/closed_period_rejects_reopen_reconcile_and_ledger_appends
        """
        period, distributor, product = self._closed_quarter_with_a_registered_label(api)

        for action in ("REOPEN", "RECONCILE"):
            response = api.post_period_action(
                period["id"], f.period_action_payload(action), ADMIN_HEADERS
            )
            validate_error(
                response,
                ApiErrorId.ERR_INVALID_PERIOD_STATE.value,
                expected_status=409,
            )

        response = api.create_deposit_initiation(
            distributor["id"],
            f.deposit_initiation_payload(product["id"], 100, period["id"]),
            make_distributor_headers(distributor["id"]),
        )
        validate_error(
            response, ApiErrorId.ERR_INVALID_PERIOD_STATE.value, expected_status=409
        )

        stored = h.read_period(api, period["id"])
        assert stored["status"] == "CLOSED"
        assert stored["version"] == 3
        assert stored["deposits_initiated_cents"] == 0

    def test_the_two_reconciliation_lines_are_all_the_ledger_holds(self, api):
        """Reconciliation of an empty quarter books a zero fee and a zero sweep.

        PRD: "Reconciliation then books two ledger lines, both with `container_count` 0 and
        `source_kind` `PROGRAM_ACTION` because neither represents containers moving: one
        with `entry_type` `HANDLING_FEE` and `amount_cents` equal to `handling_fee_cents`,
        and one with `entry_type` `UNREDEEMED_SWEEP` and `amount_cents` equal to the negative
        of `sweep_to_funding_cents`."

        Design: Corner/state_machines/closed_period_rejects_reopen_reconcile_and_ledger_appends
        """
        period, _, _ = self._closed_quarter_with_a_registered_label(api)

        entries, meta = validate_paginated(
            api.list_ledger_entries(period["id"], ADMIN_HEADERS)
        )
        assert meta["total_count"] == 2
        assert [entry["entry_type"] for entry in entries] == [
            "HANDLING_FEE",
            "UNREDEEMED_SWEEP",
        ]
        for entry in entries:
            assert entry["amount_cents"] == 0
            assert entry["container_count"] == 0
            assert entry["source_kind"] == "PROGRAM_ACTION"


class TestSoldBatchIsFinished:
    """The sale posts revenue once and then locks the batch."""

    @staticmethod
    def _batch_ready_to_sell(api):
        """A world whose centre holds 100 counted PET containers, baled into one 50 kg bale."""
        world = h.build_world(
            api,
            center_overrides={"site_name": "Bend Redemption Center"},
            period_overrides={"operating_cost_cents": 0},
        )
        h.create_counted_center_visit(
            api, world.center_id, world.machine_id, world.product_id, [100]
        )
        batch = h.create_baled_batch(api, world.center_id, 100, 0.0, [50.0])
        return world, batch

    def test_the_sale_prices_the_bale_and_then_refuses_every_repeat(self, api):
        """Sorting, baling and a second sale are all refused once the batch is SOLD.

        PRD: "A `CenterOperator` sells a baled batch, moving it `BALED → SOLD` and stamping
        `sold_at` with the current logical instant."

        PRD: "The commodity batch's `status` matches the requested processing action's or
        sale's originating state → otherwise `ERR_INVALID_BATCH_STATE` (HTTP 409)."

        Design: Corner/state_machines/sold_batch_rejects_further_processing_and_a_second_sale
        """
        world, batch = self._batch_ready_to_sell(api)

        sold = validate_success(
            api.sell_commodity_batch(
                batch["id"],
                f.batch_sale_payload("SPOT", 20000, world.period_id),
                world.center_headers,
            )
        )
        assert sold["status"] == "SOLD"
        assert_stamped_at(sold["sold_at"], INSTANT)
        assert sold["bale_count"] == 1
        assert sold["gross_weight_kg"] == 50.00
        assert sold["effective_price_cents_per_tonne"] == 20000
        assert sold["gross_revenue_cents"] == 1000
        assert sold["freight_cents"] == 225
        assert sold["net_revenue_cents"] == 775

        for payload in (
            f.sort_action_payload(0.0),
            f.bale_action_payload([50.0]),
        ):
            validate_error(
                api.post_batch_processing_action(
                    batch["id"], payload, h.PLANT_COUNTER_HEADERS
                ),
                ApiErrorId.ERR_INVALID_BATCH_STATE.value,
                expected_status=409,
            )

        validate_error(
            api.sell_commodity_batch(
                batch["id"],
                f.batch_sale_payload("SPOT", 20000, world.period_id),
                world.center_headers,
            ),
            ApiErrorId.ERR_INVALID_BATCH_STATE.value,
            expected_status=409,
        )

        assert h.read_batch(api, batch["id"], world.center_headers)["version"] == 4

    def test_the_revenue_line_is_posted_exactly_once(self, api):
        """The three refusals cannot double-count the 775 cents already booked.

        PRD: "The sale then appends a deposit ledger line whose `entry_type` is
        `MATERIAL_REVENUE`, whose `amount_cents` is `net_revenue_cents`, whose
        `container_count` is 0 because this is a pure money line rather than a container
        movement, whose `source_kind` is `COMMODITY_BATCH` and whose `source_ref_id` is this
        batch's `id`, booked into the named quarter."

        Design: Corner/state_machines/sold_batch_rejects_further_processing_and_a_second_sale
        """
        world, batch = self._batch_ready_to_sell(api)
        h.sell_batch(
            api, batch["id"], world.center_id, "SPOT", 20000, world.period_id
        )

        validate_error(
            api.sell_commodity_batch(
                batch["id"],
                f.batch_sale_payload("SPOT", 20000, world.period_id),
                world.center_headers,
            ),
            ApiErrorId.ERR_INVALID_BATCH_STATE.value,
        )

        entries, meta = validate_paginated(
            api.list_ledger_entries(
                world.period_id, ADMIN_HEADERS, params={"entry_type": "MATERIAL_REVENUE"}
            )
        )
        assert meta["total_count"] == 1
        assert entries[0]["amount_cents"] == 775
        assert entries[0]["container_count"] == 0
        assert entries[0]["source_kind"] == "COMMODITY_BATCH"
        assert entries[0]["source_ref_id"] == batch["id"]

        assert h.read_period(api, world.period_id)["material_revenue_cents"] == 775
