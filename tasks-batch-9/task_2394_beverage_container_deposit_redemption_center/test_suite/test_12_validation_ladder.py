"""The 39-rung ladder: one clean pass, and seven rungs that fire in order.

The ladder is ordered authenticate, authorise, resolve, shape, version, state,
screening, windows, uniqueness, capacity, money — so each test below arranges a
request that could plausibly be answered by a later rung and pins the earlier
one.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    ROLE_CENTER_OPERATOR,
    ApiErrorId,
    assert_center_pool,
    assert_lot_settlement,
    assert_visit_valuation,
    headers_without_user_id,
    make_distributor_headers,
    make_headers,
)
from test_helpers import factories as f
from test_helpers import fixtures as h

INSTANT = "2026-08-05T09:00:00Z"


class TestFullRedemptionHappyPath:
    """Nothing on the ladder fires on a well-formed centre redemption."""

    def test_visit_lot_close_approve_and_pay_all_succeed(self, api):
        """Five calls in a row return 2xx and the money moves exactly once.

        PRD: "The normal path advances the visit `COUNTING → COUNTED`; a `CENTER` visit
        additionally requires its centre to still be `OPERATIONAL`, refusing otherwise with
        `ERR_CENTER_NOT_OPERATIONAL`."

        PRD: "On success the server stamps `paid_at` with the current logical instant,
        decreases the centre's `cash_drawer_balance_cents` by `payout_cents`, and appends a
        deposit ledger line into that quarter whose `entry_type` is `REDEMPTION_PAID`, whose
        `amount_cents` is the negative of `payout_cents` — paying a redemption discharges
        liability — whose `container_count` is `payable_count`, whose `source_kind` is
        `REDEMPTION_VISIT` and whose `source_ref_id` is this visit's `id`."

        Design: Corner/validations/full_redemption_happy_path_satisfies_every_check
        """
        world = h.build_world(
            api,
            center_overrides={"site_name": "Bend Redemption Center"},
            period_overrides={"operating_cost_cents": 0},
        )
        headers = world.center_headers
        h.initiate_deposits(
            api, world.distributor_id, world.product_id, 300, world.period_id
        )

        visit = validate_success(
            api.create_redemption_visit(
                f.center_machine_visit_payload(
                    world.center_id, world.machine_id, world.account_id
                ),
                headers,
            ),
            expected_status=201,
        )
        lot = validate_success(
            api.create_container_lot(
                visit["id"],
                f.create_lot_payload(world.product_id, 200, visit["version"]),
                headers,
            ),
            expected_status=201,
        )
        closed = validate_success(api.close_count(visit["id"], headers))
        validate_success(
            api.post_payout_action(
                visit["id"], f.payout_action_payload("APPROVE"), headers
            )
        )
        paid = validate_success(
            api.post_payout_action(visit["id"], f.payout_action_payload("PAY"), headers)
        )

        assert closed["count_status"] == "COUNTED"
        assert paid["payout_status"] == "PAID"
        assert_visit_valuation(
            paid,
            visit_limit_applied=240,
            capped_count=200,
            shrink_adjustment_count=0,
            payable_count=200,
            refused_over_limit_count=0,
            payout_cents=2000,
        )

        stored_lot = h.list_lots(api, visit["id"], headers)[0]
        assert stored_lot["id"] == lot["id"]
        assert stored_lot["accepted_quantity"] == 200
        assert stored_lot["reject_reason"] is None
        assert_lot_settlement(
            stored_lot, paid_quantity=200, reconciliation_flag="PAID_FULL"
        )

        center = h.read_center(api, world.center_id, headers)
        assert center["cash_drawer_balance_cents"] == 48000
        assert_center_pool(
            center,
            accepted_container_count=200,
            unbatched_container_count=200,
            withheld_visit_count=0,
        )

        holder = h.read_account(api, world.account_id, ADMIN_HEADERS)
        assert holder["containers_redeemed_today"] == 200
        assert holder["cap_reached_today"] is False
        assert holder["fraud_strikes"] == 0

        period = h.read_period(api, world.period_id)
        assert period["outstanding_liability_cents"] == 1000
        assert period["redemptions_paid_cents"] == 2000
        assert period["containers_redeemed_count"] == 200

        entries, meta = validate_paginated(
            api.list_ledger_entries(world.period_id, ADMIN_HEADERS)
        )
        assert meta["total_count"] == 2
        assert [entry["entry_type"] for entry in entries] == [
            "DEPOSIT_INITIATED",
            "REDEMPTION_PAID",
        ]
        assert [entry["amount_cents"] for entry in entries] == [3000, -2000]


class TestClosedAccountAnswersTwoDifferentRungs:
    """The from-state rung and the standing rung sit next to each other."""

    @staticmethod
    def _closed_account(api):
        h.set_clock(api, INSTANT)
        account = h.create_account(api)
        return h.account_status_change(api, account["id"], "CLOSE")

    def test_a_status_change_reports_the_state_and_a_credit_action_the_standing(
        self, api
    ):
        """CLOSE and UNFLAG stop at rung 20; WITHDRAW falls through to rung 21.

        PRD: "The centre's `status`, the account's `status` and the store's
        `obligation_status` each match the originating state of the requested status change,
        account action or exemption action → otherwise `ERR_INVALID_CENTER_STATE`,
        `ERR_INVALID_ACCOUNT_STATE` or `ERR_INVALID_OBLIGATION_STATE` (all HTTP 409)."

        PRD: "Account standing permits the operation: a `CLOSED` account accepts no operation
        at all (`ERR_ACCOUNT_CLOSED`, HTTP 409), and a `FLAGGED` account accepts no new visit,
        no new bag drop and no credit action (`ERR_ACCOUNT_FLAGGED`, HTTP 409)."

        Design: Corner/validations/closed_account_close_hits_priority_20_while_withdraw_hits_priority_21
        """
        closed = self._closed_account(api)
        assert closed["status"] == "CLOSED"
        version_after_close = closed["version"]

        validate_error(
            api.post_account_status_change(
                closed["id"], f.account_status_change_payload("CLOSE"), ADMIN_HEADERS
            ),
            ApiErrorId.ERR_INVALID_ACCOUNT_STATE.value,
            expected_status=409,
        )

        validate_error(
            api.post_credit_action(
                closed["id"],
                f.credit_action_payload("WITHDRAW", 100, version_after_close),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_ACCOUNT_CLOSED.value,
            expected_status=409,
        )

        validate_error(
            api.post_account_status_change(
                closed["id"], f.account_status_change_payload("UNFLAG"), ADMIN_HEADERS
            ),
            ApiErrorId.ERR_INVALID_ACCOUNT_STATE.value,
            expected_status=409,
        )

        stored = h.read_account(api, closed["id"], ADMIN_HEADERS)
        assert stored["status"] == "CLOSED"
        assert stored["credit_balance_cents"] == 0
        assert stored["version"] == version_after_close

        _, meta = validate_paginated(
            api.list_credit_entries(closed["id"], ADMIN_HEADERS)
        )
        assert meta["total_count"] == 0


class TestAuthPrecedesLookup:
    """A missing row is never reported while the headers are still unusable."""

    def test_a_bad_role_and_a_missing_principal_both_beat_the_404(self, api):
        """Three probes at one unstored identifier report 401, 403 and 401.

        PRD: "`X-User-Role` and `X-User-ID` are both present and non-empty → otherwise
        `ERR_UNAUTHENTICATED`. Applies to every endpoint except the logical-clock endpoint."

        PRD: "`X-User-Role` names one of the six roles in §2.1 → otherwise
        `ERR_UNAUTHENTICATED`. Applies to every endpoint."

        PRD: "The acting role appears in the requested operation's authorised-role list →
        otherwise `ERR_UNAUTHORIZED`. Applies to every endpoint."

        Design: Corner/validations/authentication_and_authorization_run_before_the_lookup
        """
        h.set_clock(api, INSTANT)

        unknown_role = validate_error(
            api.get_retailer(
                NON_EXISTENT_UUID, make_headers("someone-1", "UnknownRole")
            ),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            expected_status=401,
        )
        assert unknown_role["error_id"] != ApiErrorId.ERR_RETAILER_NOT_FOUND.value

        wrong_role = validate_error(
            api.get_retailer(
                NON_EXISTENT_UUID, make_headers(NON_EXISTENT_UUID, ROLE_CENTER_OPERATOR)
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            expected_status=403,
        )
        assert wrong_role["error_id"] != ApiErrorId.ERR_RETAILER_NOT_FOUND.value

        no_principal = validate_error(
            api.get_retailer(
                NON_EXISTENT_UUID, headers_without_user_id("ProgramAdmin")
            ),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            expected_status=401,
        )
        assert no_principal["error_id"] != ApiErrorId.ERR_RETAILER_NOT_FOUND.value


class TestRequestShapePrecedesVersion:
    """A malformed body is rejected before its stale version is compared."""

    def test_a_zero_quantity_lot_with_a_stale_version_reports_the_shape(self, api):
        """Rung 7 answers 400 rather than rung 10 answering 412.

        PRD: "Request shape: every required body field is present, every enum value is a
        declared member, every integer lies inside its declared range, every state code is
        exactly two uppercase letters, dates are well formed, and the site/channel pairing
        rules hold"

        PRD: "The supplied expected-version field equals the parent's current `version`, per
        §2.6 → otherwise `ERR_STALE_VISIT_VERSION`, `ERR_STALE_BAG_DROP_VERSION` or
        `ERR_STALE_ACCOUNT_VERSION` (HTTP 412). Applies to lot addition, bag-drop count
        submission and account credit actions."

        Design: Corner/validations/malformed_lot_payload_is_rejected_before_the_stale_version_check
        """
        h.set_clock(api, INSTANT)
        distributor = h.create_distributor(api)
        product = h.create_registered_product(api, distributor["id"])
        fleet = h.create_operational_center(
            api,
            {"site_name": "Bend Redemption Center", "opening_cash_cents": 50000},
        )
        center, machine = fleet["center"], fleet["machine"]
        headers = h.make_center_headers(center["id"])

        visit = h.open_center_machine_visit(api, center["id"], machine["id"])
        original_version = visit["version"]
        h.add_lot(
            api,
            visit["id"],
            product["id"],
            10,
            headers,
            expected_visit_version=original_version,
        )

        body = validate_error(
            api.create_container_lot(
                visit["id"],
                f.create_lot_payload(product["id"], 0, original_version),
                headers,
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            expected_status=400,
        )
        assert body["error_id"] != ApiErrorId.ERR_STALE_VISIT_VERSION.value

        stored = h.read_visit(api, visit["id"], headers)
        assert stored["presented_total"] == 10
        assert stored["count_status"] == "COUNTING"

        _, meta = validate_paginated(api.list_visit_lots(visit["id"], headers))
        assert meta["total_count"] == 1


class TestMaterialAcceptance:
    """The same material passes or fails according to two different configs."""

    def test_a_glass_lot_and_an_aluminium_lot_probe_both_halves_of_the_rung(self, api):
        """The centre list refuses glass at one site; the machine refuses aluminium at another.

        PRD: "Material acceptance: on a `CENTER` visit the label's `container_material`
        appears in the centre's `accepted_materials`, and on a `MACHINE_COUNT` visit it
        additionally equals the machine's `accepted_material` → otherwise
        `ERR_MATERIAL_NOT_ACCEPTED` (HTTP 422). Applies to lot addition."

        Design: Corner/validations/material_acceptance_depends_on_centre_config_and_machine_assignment
        """
        h.set_clock(api, INSTANT)
        distributor = h.create_distributor(api)
        glass = h.create_registered_product(
            api,
            distributor["id"],
            brand_name="Cascade Cider",
            beverage_type="HARD_CIDER",
            container_material="GLASS",
            fill_volume_ml=500,
            upc="011110000003",
        )
        aluminium = h.create_registered_product(
            api,
            distributor["id"],
            brand_name="Cascade Cola",
            beverage_type="CARBONATED_SOFT_DRINK",
            container_material="ALUMINUM",
            fill_volume_ml=355,
            upc="011110000002",
        )

        pet_only = h.create_operational_center(
            api,
            {
                "site_name": "PET Only Center",
                "x_miles": 10.0,
                "y_miles": 10.0,
                "accepted_materials": ["PET_PLASTIC"],
                "accepts_all_materials": False,
                "opening_cash_cents": 50000,
            },
            {"asset_tag": "RVM-3001", "accepted_material": "PET_PLASTIC"},
        )["center"]
        all_materials = h.create_operational_center(
            api,
            {"site_name": "All Materials Center", "opening_cash_cents": 50000},
            {"asset_tag": "RVM-4001", "accepted_material": "PET_PLASTIC"},
        )
        wide_center, pet_machine = all_materials["center"], all_materials["machine"]

        pet_only_headers = h.make_center_headers(pet_only["id"])
        wide_headers = h.make_center_headers(wide_center["id"])

        refused_by_center = h.open_center_hand_visit(api, pet_only["id"])
        validate_error(
            api.create_container_lot(
                refused_by_center["id"],
                f.create_lot_payload(
                    glass["id"], 10, refused_by_center["version"]
                ),
                pet_only_headers,
            ),
            ApiErrorId.ERR_MATERIAL_NOT_ACCEPTED.value,
            expected_status=422,
        )
        stored = h.read_visit(api, refused_by_center["id"], pet_only_headers)
        assert stored["count_status"] == "OPEN"
        assert stored["presented_total"] == 0

        accepted_by_center = h.open_center_hand_visit(api, wide_center["id"])
        glass_lot = validate_success(
            api.create_container_lot(
                accepted_by_center["id"],
                f.create_lot_payload(
                    glass["id"], 10, accepted_by_center["version"]
                ),
                wide_headers,
            ),
            expected_status=201,
        )
        assert glass_lot["accepted_quantity"] == 10
        assert glass_lot["deposit_cents_per_container"] == 10

        machine_visit = h.open_center_machine_visit(
            api, wide_center["id"], pet_machine["id"]
        )
        validate_error(
            api.create_container_lot(
                machine_visit["id"],
                f.create_lot_payload(
                    aluminium["id"], 10, machine_visit["version"]
                ),
                wide_headers,
            ),
            ApiErrorId.ERR_MATERIAL_NOT_ACCEPTED.value,
            expected_status=422,
        )
        stored_machine_visit = h.read_visit(api, machine_visit["id"], wide_headers)
        assert stored_machine_visit["count_status"] == "OPEN"
        assert stored_machine_visit["version"] == machine_visit["version"]


class TestUnbatchedPoolIsAnAggregate:
    """Successive draws share one pool, so the second one runs it dry."""

    def test_a_second_draw_of_sixty_is_refused_but_fifty_fits(self, api):
        """150 plus 60 exceeds the 200-container pool; 150 plus 50 empties it.

        PRD: "The draw cannot exceed what the centre actually holds: `container_count` must
        be at most the centre's `unbatched_container_count`, and an over-draw is refused with
        `ERR_INSUFFICIENT_UNBATCHED_CONTAINERS`."

        PRD: "On success the batch opens in `status` `ACCUMULATING`, the centre's
        `batched_container_count` grows by the drawn count and its `unbatched_container_count`
        falls by the same amount."

        Design: Corner/validations/unbatched_pool_is_an_aggregate_check_across_successive_batches
        """
        h.set_clock(api, INSTANT)
        distributor = h.create_distributor(api)
        product = h.create_registered_product(api, distributor["id"])
        fleet = h.create_operational_center(
            api,
            {"site_name": "Bend Redemption Center", "opening_cash_cents": 50000},
        )
        center, machine = fleet["center"], fleet["machine"]
        headers = h.make_center_headers(center["id"])

        for _ in range(2):
            h.create_counted_center_visit(
                api, center["id"], machine["id"], product["id"], [100]
            )
        assert_center_pool(
            h.read_center(api, center["id"], headers),
            accepted_container_count=200,
            unbatched_container_count=200,
        )

        first = validate_success(
            api.create_commodity_batch(
                f.create_commodity_batch_payload(
                    center["id"], 150, batch_code="BATCH-1001"
                ),
                headers,
            ),
            expected_status=201,
        )
        assert_center_pool(
            h.read_center(api, center["id"], headers),
            batched_container_count=150,
            unbatched_container_count=50,
        )

        validate_error(
            api.create_commodity_batch(
                f.create_commodity_batch_payload(
                    center["id"], 60, batch_code="BATCH-1002"
                ),
                headers,
            ),
            ApiErrorId.ERR_INSUFFICIENT_UNBATCHED_CONTAINERS.value,
            expected_status=422,
        )
        assert_center_pool(
            h.read_center(api, center["id"], headers),
            batched_container_count=150,
            unbatched_container_count=50,
        )

        second = validate_success(
            api.create_commodity_batch(
                f.create_commodity_batch_payload(
                    center["id"], 50, batch_code="BATCH-1003"
                ),
                headers,
            ),
            expected_status=201,
        )
        assert_center_pool(
            h.read_center(api, center["id"], headers),
            batched_container_count=200,
            unbatched_container_count=0,
        )

        rows, meta = validate_paginated(
            api.list_commodity_batches(headers, params={"center_id": center["id"]})
        )
        assert meta["total_count"] == 2
        assert sorted(row["batch_code"] for row in rows) == [
            "BATCH-1001",
            "BATCH-1003",
        ]
        assert h.read_batch(api, first["id"], headers)["status"] == "ACCUMULATING"
        assert h.read_batch(api, second["id"], headers)["status"] == "ACCUMULATING"


class TestSuspendedDistributorCannotSubmit:
    """A suspended bottler owns labels it can never move out of DRAFT."""

    def test_the_submission_is_refused_and_the_label_stays_in_draft(self, api):
        """Creating the label succeeds; only the SUBMIT action is refused.

        PRD: "An optional `status` may be supplied and defaults to `ACTIVE`; the only other
        accepted value is `SUSPENDED`, and a suspended distributor may neither submit labels
        nor initiate deposits."

        PRD: "The owning distributor's `status` is `ACTIVE` → otherwise
        `ERR_DISTRIBUTOR_SUSPENDED` (HTTP 422). Applies to deposit initiation and to the
        `SUBMIT` registration action."

        Design: Corner/validations/suspended_distributor_cannot_submit_its_own_label
        """
        h.set_clock(api, INSTANT)
        distributor = h.create_distributor(
            api,
            legal_name="Suspended Bottling LLC",
            permit_number="PERMIT-2001",
            status="SUSPENDED",
        )
        headers = make_distributor_headers(distributor["id"])
        product = h.create_draft_product(
            api,
            distributor["id"],
            brand_name="Suspended Spring",
            upc="011110000021",
        )

        validate_error(
            api.post_registration_action(
                product["id"], f.registration_action_payload("SUBMIT"), headers
            ),
            ApiErrorId.ERR_DISTRIBUTOR_SUSPENDED.value,
            expected_status=422,
        )

        stored = validate_success(api.get_beverage_product(product["id"], headers))
        assert stored["registration_state"] == "DRAFT"
        assert stored["coverage_status"] is None
        assert stored["deposit_cents"] == 0
        assert stored["version"] == 1

        owner = validate_success(api.get_distributor(distributor["id"], headers))
        assert owner["status"] == "SUSPENDED"
        assert owner["containers_initiated_count"] == 0


class TestPaymentNeedsTheContainingQuarter:
    """An open quarter elsewhere in the calendar does not authorise payment."""

    def test_pay_is_refused_until_a_quarter_contains_the_visit_date(self, api):
        """Q2 cannot pay an August visit; creating Q3 makes the same call succeed.

        PRD: "A reporting quarter with `status` `OPEN` exists whose closed interval from
        `start_date` to `end_date` contains the relevant date — the `visit_date` for a payment
        or reversal, the calendar date of `settled_at` for a bag-drop credit → otherwise
        `ERR_NO_OPEN_PERIOD` (HTTP 422). Applies to the `PAY` and `REVERSE` payout actions and
        to the `CREDIT` settlement action."

        Design: Corner/validations/payout_needs_an_open_period_containing_the_visit_date
        """
        h.set_clock(api, INSTANT)
        second_quarter = h.create_period(
            api,
            quarter_code="2026Q2",
            start_date="2026-04-01",
            end_date="2026-06-30",
            operating_cost_cents=0,
        )
        distributor = h.create_distributor(api)
        product = h.create_registered_product(api, distributor["id"])
        fleet = h.create_operational_center(
            api,
            {"site_name": "Bend Redemption Center", "opening_cash_cents": 50000},
        )
        center, machine = fleet["center"], fleet["machine"]
        headers = h.make_center_headers(center["id"])

        visit = h.create_counted_center_visit(
            api, center["id"], machine["id"], product["id"], [100]
        )
        h.payout_action(api, visit["id"], "APPROVE", headers)

        validate_error(
            api.post_payout_action(
                visit["id"], f.payout_action_payload("PAY"), headers
            ),
            ApiErrorId.ERR_NO_OPEN_PERIOD.value,
            expected_status=422,
        )
        blocked = h.read_visit(api, visit["id"], headers)
        assert blocked["payout_status"] == "APPROVED"
        assert blocked["paid_at"] is None
        assert (
            h.read_center(api, center["id"], headers)["cash_drawer_balance_cents"]
            == 50000
        )

        third_quarter = h.create_period(api, operating_cost_cents=0)

        paid = validate_success(
            api.post_payout_action(
                visit["id"], f.payout_action_payload("PAY"), headers
            )
        )
        assert paid["payout_status"] == "PAID"
        assert (
            h.read_center(api, center["id"], headers)["cash_drawer_balance_cents"]
            == 49000
        )

        rows, meta = validate_paginated(
            api.list_ledger_entries(third_quarter["id"], ADMIN_HEADERS)
        )
        assert meta["total_count"] == 1
        assert rows[0]["entry_type"] == "REDEMPTION_PAID"
        assert rows[0]["amount_cents"] == -1000
        assert rows[0]["liability_after_cents"] == -1000

        _, empty_meta = validate_paginated(
            api.list_ledger_entries(second_quarter["id"], ADMIN_HEADERS)
        )
        assert empty_meta["total_count"] == 0
