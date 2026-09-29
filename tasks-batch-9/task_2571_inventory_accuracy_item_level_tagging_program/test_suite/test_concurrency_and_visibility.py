"""
Stale-read protection on the three versioned write paths, the vendor sampling
band as a cumulative rate threshold, and the immediate visibility of everything
a posting derives.

Each of the three version checks guards a write whose legitimate behaviour is to
overwrite or supersede earlier work, which is exactly why a stale reading has to
be refused rather than merged.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_pct
from test_helpers.constants import (
    APPAREL_MIN_ACCURACY_PCT,
    DEFAULT_CLOCK_UTC,
    TEE1_UNIT_COST_CENTS,
)
from test_helpers.api_errors import (
    ERR_STALE_INVESTIGATION_VERSION,
    ERR_STALE_PHYSICAL_INVENTORY_VERSION,
    ERR_STALE_STOCK_POSITION_VERSION,
)
from test_helpers.test_users import (
    ADMIN,
    ANALYST,
    CONTROLLER,
    SUPERVISOR,
    make_counter_headers,
    make_store_ops_headers,
    make_vendor_rep_headers,
)


class TestAdjustmentsQuoteThePositionTheyRead:
    def test_a_verification_cascade_invalidates_an_earlier_position_read(self, api):
        """
        The position moves for a reason that has nothing to do with adjustments.

        "Requesting an on-hand adjustment against a stock position requires
        `expected_stock_position_version` in the request body as a non-optional field,
        carrying the client's last observed `version` of the target `StockPosition`. If
        that value does not equal the position's current `version`, the request is
        rejected with `ERR_STALE_STOCK_POSITION_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/adjustment_create_with_stale_position_version_rejected
        """
        world = fx.encoded_tag_batch_world(api)
        stale_version = fx.position_version(api, world["position_id"])

        failed = validate_success(
            api.verify_tag_batch(
                world["batch_id"],
                f.verify_payload(sampled_units=50, readable_units=48),
                world["store_headers"],
            )
        )
        assert failed["read_rate_bps"] == 9600
        assert failed["verification_outcome"] == "FAIL"

        validate_error(
            api.create_adjustment(
                world["position_id"],
                f.adjustment_payload(-20, stale_version, reason_code="COUNT_VARIANCE"),
                ANALYST,
            ),
            ERR_STALE_STOCK_POSITION_VERSION,
            412,
        )
        rows, meta = validate_paginated(
            api.list_adjustments(ANALYST, {"stock_position_id": world["position_id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0

        fresh = fx.read_position(api, world["position_id"])
        assert fresh["version"] > stale_version
        assert fresh["tag_integrity_hold"] is True
        assert fresh["on_hand_units"] == 100

        accepted = validate_success(
            api.create_adjustment(
                world["position_id"],
                f.adjustment_payload(-20, fresh["version"], reason_code="COUNT_VARIANCE"),
                ANALYST,
            ),
            201,
        )
        assert accepted["approval_state"] == "PENDING"
        assert accepted["posting_state"] == "UNPOSTED"

    def test_a_refused_write_does_not_itself_move_the_version(self, api):
        """
        The 412 leaves the counter exactly where it was.

        "Requesting an on-hand adjustment against a stock position requires
        `expected_stock_position_version` in the request body as a non-optional field,
        carrying the client's last observed `version` of the target `StockPosition`. If
        that value does not equal the position's current `version`, the request is
        rejected with `ERR_STALE_STOCK_POSITION_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/adjustment_create_with_stale_position_version_rejected
        """
        world = fx.apparel_reference_world(api)
        current = fx.position_version(api, world["position_id"])

        for _ in range(2):
            validate_error(
                api.create_adjustment(
                    world["position_id"],
                    f.adjustment_payload(-5, current + 1, reason_code="COUNT_VARIANCE"),
                    ANALYST,
                ),
                ERR_STALE_STOCK_POSITION_VERSION,
                412,
            )
            assert fx.position_version(api, world["position_id"]) == current

        accepted = validate_success(
            api.create_adjustment(
                world["position_id"],
                f.adjustment_payload(-5, current, reason_code="COUNT_VARIANCE"),
                ANALYST,
            ),
            201,
        )
        assert accepted["delta_units"] == -5


class TestPhysicalLinesQuoteTheInventoryTheyRead:
    @staticmethod
    def _counting_world(api):
        """A two-item store with a COUNTING physical inventory assigned to CF1."""
        world = fx.apparel_two_item_world(api, baseline_a=100, baseline_b=40)
        firm = fx.create_counter_firm(api)
        inventory = validate_success(
            api.create_physical_inventory(
                f.physical_inventory_payload(world["store_id"], firm["id"]), CONTROLLER
            ),
            201,
        )
        world["counter_headers"] = make_counter_headers(firm["id"])
        world["physical_inventory_id"] = inventory["id"]
        started = validate_success(
            api.start_physical_inventory(inventory["id"], world["counter_headers"])
        )
        assert started["status"] == "COUNTING"
        world["version_at_start"] = started["version"]
        return world

    def test_the_second_line_of_a_pass_may_not_reuse_the_first_lines_version(self, api):
        """
        One accepted line is enough to invalidate the reading it was written from.

        "Submitting a counted line for a physical inventory requires
        `expected_physical_inventory_version` in the request body as a non-optional
        field, carrying the client's last observed `version` of the target
        `PhysicalInventory`. A mismatch with the inventory's current `version` is
        rejected with `ERR_STALE_PHYSICAL_INVENTORY_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/physical_inventory_line_with_stale_inventory_version_rejected
        """
        world = self._counting_world(api)
        inventory_id = world["physical_inventory_id"]

        first = validate_success(
            api.create_physical_inventory_line(
                inventory_id,
                f.physical_line_payload(
                    world["item_id"], 100, world["version_at_start"]
                ),
                world["counter_headers"],
            ),
            201,
        )
        assert first["superseded"] is False

        validate_error(
            api.create_physical_inventory_line(
                inventory_id,
                f.physical_line_payload(
                    world["item_b_id"], 40, world["version_at_start"]
                ),
                world["counter_headers"],
            ),
            ERR_STALE_PHYSICAL_INVENTORY_VERSION,
            412,
        )
        rows, meta = validate_paginated(
            api.list_physical_inventory_lines(
                ANALYST, {"physical_inventory_id": inventory_id}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first["id"]

        current = fx.read_physical_inventory(api, inventory_id)
        assert current["version"] > world["version_at_start"]
        second = validate_success(
            api.create_physical_inventory_line(
                inventory_id,
                f.physical_line_payload(world["item_b_id"], 40, current["version"]),
                world["counter_headers"],
            ),
            201,
        )
        assert second["counted_units"] == 40

    def test_the_supersede_edge_must_still_be_walked_from_a_fresh_read(self, api):
        """
        Re-counting an item replaces the earlier line rather than adding to it.

        "Submitting a counted line for a physical inventory requires
        `expected_physical_inventory_version` in the request body as a non-optional
        field, carrying the client's last observed `version` of the target
        `PhysicalInventory`. A mismatch with the inventory's current `version` is
        rejected with `ERR_STALE_PHYSICAL_INVENTORY_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/physical_inventory_line_with_stale_inventory_version_rejected
        """
        world = self._counting_world(api)
        inventory_id = world["physical_inventory_id"]

        first = validate_success(
            api.create_physical_inventory_line(
                inventory_id,
                f.physical_line_payload(
                    world["item_id"], 100, world["version_at_start"]
                ),
                world["counter_headers"],
            ),
            201,
        )
        after_first = fx.read_physical_inventory(api, inventory_id)
        validate_success(
            api.create_physical_inventory_line(
                inventory_id,
                f.physical_line_payload(
                    world["item_b_id"], 40, after_first["version"]
                ),
                world["counter_headers"],
            ),
            201,
        )

        validate_error(
            api.create_physical_inventory_line(
                inventory_id,
                f.physical_line_payload(world["item_id"], 95, after_first["version"]),
                world["counter_headers"],
            ),
            ERR_STALE_PHYSICAL_INVENTORY_VERSION,
            412,
        )

        current = fx.read_physical_inventory(api, inventory_id)
        recount = validate_success(
            api.create_physical_inventory_line(
                inventory_id,
                f.physical_line_payload(world["item_id"], 95, current["version"]),
                world["counter_headers"],
            ),
            201,
        )
        assert recount["counted_units"] == 95
        assert recount["superseded"] is False
        assert (
            validate_success(
                api.get_physical_inventory_line(first["id"], ANALYST)
            )["superseded"]
            is True
        )

        _, meta = validate_paginated(
            api.list_physical_inventory_lines(
                ANALYST,
                {"physical_inventory_id": inventory_id, "superseded": False},
            )
        )
        assert meta["total_count"] == 2
        assert fx.read_physical_inventory(api, inventory_id)["line_count"] == 2


class TestCauseProposalsQuoteTheInvestigationTheyRead:
    def test_the_assignment_alone_invalidates_a_pre_assignment_read(self, api):
        """
        A proposal written from the opening read is refused.

        "Proposing a root cause on a variance investigation requires
        `expected_investigation_version` in the request body as a non-optional field,
        carrying the client's last observed `version` of the target
        `VarianceInvestigation`. A mismatch with the investigation's current `version` is
        rejected with `ERR_STALE_INVESTIGATION_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/cause_proposal_with_stale_investigation_version_rejected
        """
        world = fx.counted_variance_world(api, counted_units=90, baseline=100)
        investigation_id = world["investigation_id"]
        stale_version = world["investigation"]["version"]

        assigned = fx.drive_to_in_review(api, investigation_id)
        assert assigned["status"] == "IN_REVIEW"
        assert assigned["version"] > stale_version

        validate_error(
            api.propose_cause(
                investigation_id,
                f.propose_cause_payload("PROCESS_ERROR", stale_version),
                ANALYST,
            ),
            ERR_STALE_INVESTIGATION_VERSION,
            412,
        )
        stalled = fx.read_investigation(api, investigation_id)
        assert stalled["status"] == "IN_REVIEW"
        assert stalled["proposed_root_cause"] is None
        assert stalled["proposal_round"] == 0

        proposed = validate_success(
            api.propose_cause(
                investigation_id,
                f.propose_cause_payload("PROCESS_ERROR", stalled["version"]),
                ANALYST,
            )
        )
        assert proposed["status"] == "CAUSE_PROPOSED"
        assert proposed["proposal_round"] == 1

    def test_the_legal_supersede_edge_cannot_be_walked_from_a_stale_read(self, api):
        """
        Every accepted step moves the version the next step must quote.

        "Proposing a root cause on a variance investigation requires
        `expected_investigation_version` in the request body as a non-optional field,
        carrying the client's last observed `version` of the target
        `VarianceInvestigation`. A mismatch with the investigation's current `version` is
        rejected with `ERR_STALE_INVESTIGATION_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/cause_proposal_with_stale_investigation_version_rejected
        """
        world = fx.counted_variance_world(api, counted_units=90, baseline=100)
        investigation_id = world["investigation_id"]
        in_review = fx.drive_to_in_review(api, investigation_id)

        first = validate_success(
            api.propose_cause(
                investigation_id,
                f.propose_cause_payload("THEFT", in_review["version"]),
                ANALYST,
            )
        )
        assert first["status"] == "CAUSE_PROPOSED"

        validate_error(
            api.propose_cause(
                investigation_id,
                f.propose_cause_payload("DAMAGE", in_review["version"]),
                ANALYST,
            ),
            ERR_STALE_INVESTIGATION_VERSION,
            412,
        )
        assert fx.read_investigation(api, investigation_id)["proposed_root_cause"] == (
            "THEFT"
        )

        superseded = validate_success(
            api.propose_cause(
                investigation_id,
                f.propose_cause_payload("DAMAGE", first["version"]),
                ANALYST,
            )
        )
        assert superseded["proposed_root_cause"] == "DAMAGE"
        assert superseded["proposal_round"] == 2

        returned = validate_success(
            api.return_investigation(investigation_id, SUPERVISOR)
        )
        assert returned["status"] == "IN_REVIEW"
        assert returned["version"] > superseded["version"]

        validate_error(
            api.propose_cause(
                investigation_id,
                f.propose_cause_payload("THEFT", superseded["version"]),
                ANALYST,
            ),
            ERR_STALE_INVESTIGATION_VERSION,
            412,
        )
        final = validate_success(
            api.propose_cause(
                investigation_id,
                f.propose_cause_payload("THEFT", returned["version"]),
                ANALYST,
            )
        )
        assert final["status"] == "CAUSE_PROPOSED"
        assert final["proposal_round"] == 3


def _tagging_world(api):
    """An APPAREL SKU at S100 with the vendor and store identities to hand."""
    world = fx.apparel_reference_world(api)
    world["vendor_headers"] = make_vendor_rep_headers(world["vendor_id"])
    world["store_headers"] = make_store_ops_headers(world["store_id"])
    return world


def _verified_batch(api, world, outcome, quantity=1000):
    """Draft, encode, receive and verify one batch at the vendor's current band."""
    batch = validate_success(
        api.create_tag_batch(
            f.tag_batch_payload(
                world["vendor_id"],
                world["item_id"],
                world["store_id"],
                quantity_encoded=quantity,
            ),
            world["vendor_headers"],
        ),
        201,
    )
    encoded = validate_success(
        api.encode_tag_batch(batch["id"], f.encode_payload(), world["vendor_headers"])
    )
    required = encoded["required_sample_units"]
    validate_success(api.receive_tag_batch(batch["id"], world["store_headers"]))
    readable = required if outcome == "PASS" else required - max(1, required // 10)
    verified = validate_success(
        api.verify_tag_batch(
            batch["id"],
            f.verify_payload(sampled_units=required, readable_units=readable),
            world["store_headers"],
        )
    )
    assert verified["verification_outcome"] == outcome
    assert verified["required_sample_units"] == required
    return verified


class TestTheVendorSampleBandIsACumulativeThreshold:
    def test_the_band_flips_back_exactly_when_the_score_reaches_nine_thousand(self, api):
        """
        One failure costs 1500 and each pass earns 200, so recovery takes four.

        "The sample band is a three-step ladder read off the vendor's score:
        `required_verification_sample_pct` is 5 when `tag_compliance_score_bps` is 9000 or
        more, 10 when the score is 7500 or more but below 9000, and 20 when the score is
        below 7500. A vendor starting at a perfect 10000 who fails one verification drops
        to 8500 and therefore into the 10 percent band, so the next thousand-unit batch
        that vendor encodes will demand 100 sampled units rather than 50."

        Design: Corner/cross_cutting_complexity_layers/vendor_sample_band_crosses_at_nine_thousand_bps
        """
        world = _tagging_world(api)
        opening = fx.read_vendor(api, world["vendor_id"])
        assert opening["tag_compliance_score_bps"] == 10000
        assert opening["required_verification_sample_pct"] == 5

        failed = _verified_batch(api, world, "FAIL")
        assert failed["required_sample_units"] == 50
        penalised = fx.read_vendor(api, world["vendor_id"])
        assert penalised["tag_compliance_score_bps"] == 8500
        assert penalised["required_verification_sample_pct"] == 10

        for expected_score in (8700, 8900):
            passed = _verified_batch(api, world, "PASS")
            assert passed["required_sample_units"] == 100
            recovering = fx.read_vendor(api, world["vendor_id"])
            assert recovering["tag_compliance_score_bps"] == expected_score
            assert recovering["required_verification_sample_pct"] == 10

        fourth = _verified_batch(api, world, "PASS")
        assert fourth["read_rate_bps"] == 10000
        assert fourth["required_sample_units"] == 100
        restored = fx.read_vendor(api, world["vendor_id"])
        assert restored["tag_compliance_score_bps"] == 9100
        assert restored["required_verification_sample_pct"] == 5

        later_batch = validate_success(
            api.create_tag_batch(
                f.tag_batch_payload(
                    world["vendor_id"], world["item_id"], world["store_id"]
                ),
                world["vendor_headers"],
            ),
            201,
        )
        later = validate_success(
            api.encode_tag_batch(
                later_batch["id"], f.encode_payload(), world["vendor_headers"]
            )
        )
        assert later["required_sample_units"] == 50

    def test_the_reward_is_capped_at_a_perfect_score(self, api):
        """
        A pass by an unblemished vendor earns nothing further.

        "The vendor's `tag_compliance_score_bps` rises by 200 basis points but never past
        10000, and `required_verification_sample_pct` is re-derived from the new score."

        Design: Corner/cross_cutting_complexity_layers/vendor_sample_band_crosses_at_nine_thousand_bps
        """
        world = _tagging_world(api)

        passed = _verified_batch(api, world, "PASS")
        assert passed["required_sample_units"] == 50
        assert passed["read_rate_bps"] == 10000
        assert passed["status"] == "VERIFIED_PASS"

        vendor = fx.read_vendor(api, world["vendor_id"])
        assert vendor["tag_compliance_score_bps"] == 10000
        assert vendor["required_verification_sample_pct"] == 5

    def test_the_penalty_floors_at_zero_and_the_band_widens_to_twenty(self, api):
        """
        Seven consecutive failures land on the floor rather than below it.

        "First, the sample is stored, `read_rate_bps` is computed,
        `verification_outcome` becomes `FAIL`, and the batch moves from `RECEIVED` to
        `VERIFICATION_FAILED`; at the same time the vendor's `tag_compliance_score_bps`
        falls by 1500 basis points but never below 0, and
        `required_verification_sample_pct` is re-derived from the reduced score."

        Design: Corner/cross_cutting_complexity_layers/vendor_sample_band_crosses_at_nine_thousand_bps
        """
        world = _tagging_world(api)
        ladder = (
            (8500, 10),
            (7000, 20),
            (5500, 20),
            (4000, 20),
            (2500, 20),
            (1000, 20),
            (0, 20),
        )

        for expected_score, expected_pct in ladder:
            failed = _verified_batch(api, world, "FAIL")
            assert failed["status"] == "VERIFICATION_FAILED"
            vendor = fx.read_vendor(api, world["vendor_id"])
            assert vendor["tag_compliance_score_bps"] == expected_score
            assert vendor["required_verification_sample_pct"] == expected_pct

        exhausted = validate_success(
            api.create_tag_batch(
                f.tag_batch_payload(
                    world["vendor_id"], world["item_id"], world["store_id"]
                ),
                world["vendor_headers"],
            ),
            201,
        )
        encoded = validate_success(
            api.encode_tag_batch(
                exhausted["id"], f.encode_payload(), world["vendor_headers"]
            )
        )
        assert encoded["required_sample_units"] == 200


class TestEveryDerivedFieldIsVisibleImmediately:
    @staticmethod
    def _approved_adjustment(api):
        """A clean position carrying one APPROVED adjustment of -20 units."""
        world = fx.apparel_reference_world(api)
        world["version_before"] = fx.position_version(api, world["position_id"])
        adjustment = fx.create_adjustment(
            api, world["position_id"], -20, reason_code="COUNT_VARIANCE"
        )
        assert adjustment["approval_state"] == "PENDING"
        approved = validate_success(
            api.approve_adjustment(adjustment["id"], SUPERVISOR)
        )
        assert approved["approval_state"] == "APPROVED"
        assert approved["posting_state"] == "UNPOSTED"
        world["adjustment_id"] = adjustment["id"]
        return world

    def test_the_posting_response_already_carries_the_settled_figures(self, api):
        """
        Nothing is left for a later refresh to fill in.

        "On success the cascade runs in a fixed order, each hop caused by the one before
        it. Hop one sets `posting_state` to `POSTED` and stamps `posted_at` with the
        current logical-clock instant. Hop two re-derives the position: `on_hand_units`
        becomes `baseline_on_hand_units` plus the sum of `delta_units` over every
        adjustment on that position whose `posting_state` is `POSTED`, and
        `book_value_cents`, `unit_accuracy_pct` and `value_accuracy_pct` follow."

        Design: Corner/consistency_model/posting_response_already_carries_every_derived_field
        """
        world = self._approved_adjustment(api)

        posted = validate_success(
            api.post_adjustment(world["adjustment_id"], SUPERVISOR)
        )
        assert posted["posting_state"] == "POSTED"
        assert posted["approval_state"] == "APPROVED"
        assert posted["posted_at"] == DEFAULT_CLOCK_UTC

        position = fx.read_position(api, world["position_id"])
        assert position["on_hand_units"] == 80
        assert position["book_value_cents"] == 80 * TEE1_UNIT_COST_CENTS
        assert position["version"] > world["version_before"]

        rows, meta = validate_paginated(
            api.list_adjustments(ADMIN, {"posting_state": "POSTED"})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == world["adjustment_id"]

    def test_the_computed_read_agrees_with_the_entity_read(self, api):
        """
        Two views of one position, and no second read ever changes an answer.

        "A dedicated computed read exposes both accuracy variants of a position side by
        side together with the reason its gate holds, returning `unit_accuracy_pct`,
        `value_accuracy_pct`, `last_count_system_units`, `last_count_book_value_cents`,
        `last_variance_units`, `last_variance_value_cents`, `promising_state`, a
        human-readable `promising_reason` naming the clause that decided the state, and
        the `min_accuracy_pct` the position is measured against."

        Design: Corner/consistency_model/posting_response_already_carries_every_derived_field
        """
        world = self._approved_adjustment(api)
        validate_success(api.post_adjustment(world["adjustment_id"], SUPERVISOR))

        position = fx.read_position(api, world["position_id"])
        accuracy = validate_success(
            api.get_stock_position_accuracy(world["position_id"], ANALYST)
        )
        for field in (
            "unit_accuracy_pct",
            "value_accuracy_pct",
            "promising_state",
            "last_count_system_units",
            "last_count_book_value_cents",
            "last_variance_units",
            "last_variance_value_cents",
        ):
            assert accuracy[field] == position[field]
        assert isinstance(accuracy["promising_reason"], str)
        assert_pct(accuracy["min_accuracy_pct"], APPAREL_MIN_ACCURACY_PCT)

        assert fx.read_position(api, world["position_id"]) == position
        assert (
            validate_success(
                api.get_stock_position_accuracy(world["position_id"], ANALYST)
            )
            == accuracy
        )
