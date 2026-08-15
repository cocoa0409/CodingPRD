"""Advance payments: the recoup-policy dual variant under settlement, the
advance money-partition invariant under recoupment and write-off, the
inclusive cap boundary, and grower self-service scoping."""
from test_helpers import (
    ApiErrorId,
    assert_advance,
    create_advance_payload,
    create_and_approve_advance,
    dom_fresh_spec,
    get_advance,
    get_grower,
    get_statements,
    juice_spec,
    set_clock,
    settle_pool,
    setup_posted_scenario,
    statement_amounts,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    close_intake_and_set_price,
    create_grower,
    create_pool,
)
from test_helpers.test_users import TEST_USERS, make_grower_headers

ACCOUNTANT = TEST_USERS["accountant_headers"]


def _setup_settled_with_two_advances(tag):
    """Posted DOM100@500/JUICE scenario + two 9000-cent ISSUED advances of
    different recoup policies + pool PRICED. Settlement then recoups them."""
    scenario = setup_posted_scenario(
        tag, channel_specs=[
            dom_fresh_spec(f"DOM-{tag}", "HAMLIN", boxes=100, price=500, rank=2),
            juice_spec(f"JU-{tag}", "HAMLIN"),
        ])
    grower_id = scenario["grower"]["id"]
    pool_id = scenario["pool"]["id"]
    advance_full = create_and_approve_advance(
        grower_id, pool_id, 9000, recoup_policy="NEXT_SETTLEMENT_FULL")
    advance_thirds = create_and_approve_advance(
        grower_id, pool_id, 9000, recoup_policy="PRO_RATA_THIRDS")
    close_intake_and_set_price(pool_id)
    scenario["advance_full"] = advance_full
    scenario["advance_thirds"] = advance_thirds
    return scenario


class TestRecoupPolicyDualVariant:
    def test_recoup_policy_full_vs_thirds_advance_outcomes(self, api):
        """PRD §3.6: "for each advance, a `NEXT_SETTLEMENT_FULL` policy caps
        recoupment at the advance's entire `outstanding_cents`, while a
        `PRO_RATA_THIRDS` policy caps it at one third of the advance's
        `amount_cents` rounded half-up to whole cents, and the amount actually
        recouped is the smallest of the advance's outstanding balance, its
        policy cap, and the remaining residual — with identical inputs, a
        pro-rata advance therefore yields a smaller recoupment and a larger
        grower payment than a full-recoupment advance; the residual falls by
        the recouped amount and the advance's `recouped_cents` rises by it, an
        advance recouped in full becomes `RECOUPED`, and one recouped in part
        becomes `PARTIALLY_RECOUPED`."

        Design: Difficulty/dual_variant_calc/advance_recoup_policy_thirds_vs_full
        """
        scenario = _setup_settled_with_two_advances("AR1")
        settle_pool(scenario["pool"]["id"])
        full = get_advance(scenario["advance_full"]["id"])
        thirds = get_advance(scenario["advance_thirds"]["id"])
        # Identical 9000 amounts and identical residual: only policy differs.
        assert full["status"] == "RECOUPED"
        assert full["recouped_cents"] == 9000
        assert full["outstanding_cents"] == 0
        assert thirds["status"] == "PARTIALLY_RECOUPED"
        assert thirds["recouped_cents"] == 3000, "round_half_up(9000/3) cap"
        assert thirds["outstanding_cents"] == 6000
        assert get_grower(scenario["grower"]["id"])[
            "advance_outstanding_cents"] == 6000

    def test_recoup_policy_full_vs_thirds_statement(self, api):
        """PRD §3.6: "Step four: whatever residual remains is the grower's
        payment." — with the final price at 328 the grower's share is
        round_half_up(96.8 * 328) = 31750, no caretaking offset applies, the
        two advances recoup 9000 + 3000, and the payment is 19750. PRD §3.6:
        "The per-grower settlement statements of a pool — share, offset,
        recoupment, and amount paid — are readable by a `PackinghouseAdmin`, a
        `PoolAccountant`, and the `Grower` for its own statement."

        Design: Difficulty/dual_variant_calc/advance_recoup_policy_thirds_vs_full
        """
        scenario = _setup_settled_with_two_advances("AR1B")
        settled = settle_pool(scenario["pool"]["id"])
        # proceeds 46760, ge 96.8, charge 100 * 150 -> final 328.
        assert settled["final_price_cents_per_ge_box"] == 328
        payload = get_statements(scenario["pool"]["id"])
        assert len(payload["statements"]) == 1
        share, offset, recouped, paid = statement_amounts(payload["statements"][0])
        assert share == 31750
        assert offset == 0
        assert recouped == 12000
        assert paid == 19750


class TestAdvanceLedgerConservation:
    def _setup_thirds_advance_and_settle(self, tag):
        scenario = setup_posted_scenario(
            tag, channel_specs=[
                dom_fresh_spec(f"DOM-{tag}", "HAMLIN", boxes=100, price=500, rank=2),
                juice_spec(f"JU-{tag}", "HAMLIN"),
            ])
        advance = create_and_approve_advance(
            scenario["grower"]["id"], scenario["pool"]["id"], 9000,
            recoup_policy="PRO_RATA_THIRDS")
        close_intake_and_set_price(scenario["pool"]["id"])
        scenario["advance"] = advance
        return scenario

    def test_advance_partition_holds_after_partial_recoup(self, api):
        """PRD §3.6: "the invariant that the amount always equals the sum of
        recouped, written-off, and outstanding portions holds for the
        advance's entire life." PRD §3.6: "`ISSUED` → `PARTIALLY_RECOUPED`
        when a settlement recoups less than the outstanding balance".

        Design: Difficulty/compensating_invariant/advance_amount_conserved_under_recoup_and_writeoff
        """
        scenario = self._setup_thirds_advance_and_settle("CI2")
        settle_pool(scenario["pool"]["id"])
        advance = get_advance(scenario["advance"]["id"])
        assert advance["status"] == "PARTIALLY_RECOUPED"
        assert advance["recouped_cents"] == 3000
        assert advance["written_off_cents"] == 0
        assert advance["outstanding_cents"] == 6000
        assert_advance(advance)  # 9000 == 3000 + 0 + 6000
        assert get_grower(scenario["grower"]["id"])[
            "advance_outstanding_cents"] == 6000

    def test_advance_partition_holds_after_writeoff(self, api):
        """PRD §3.6: "Once the advance's pool is `SETTLED`, a `PoolAccountant`
        may write off the remaining balance, moving `ISSUED` or
        `PARTIALLY_RECOUPED` → the terminal `WRITTEN_OFF`" and "Writing off
        sets `written_off_cents` to the prior `outstanding_cents`, drops
        `outstanding_cents` to zero, and reduces the grower's
        `advance_outstanding_cents` by the written-off amount with a grower
        version bump."

        Design: Difficulty/compensating_invariant/advance_amount_conserved_under_recoup_and_writeoff
        """
        scenario = self._setup_thirds_advance_and_settle("CI2B")
        settle_pool(scenario["pool"]["id"])
        written = validate_success(api_client.write_off_advance(
            scenario["advance"]["id"], ACCOUNTANT))
        assert written["status"] == "WRITTEN_OFF"
        assert written["recouped_cents"] == 3000
        assert written["written_off_cents"] == 6000
        assert written["outstanding_cents"] == 0
        assert_advance(written)  # 9000 == 3000 + 6000 + 0
        assert get_grower(scenario["grower"]["id"])[
            "advance_outstanding_cents"] == 0


class TestAdvanceCapBoundary:
    def test_advance_cap_inclusive_boundary(self, api):
        """PRD §3.6: "The cap is computed from the grower's posted position in
        that pool: take the `ge_boxes` of `POSTED` sort runs whose deliveries
        came from the grower's groves and were assigned to the advance's pool,
        multiply by the pool's current `provisional_price_cents_per_ge_box` to
        get the projected value, and take sixty percent of that value, rounded
        half-up to whole cents. Approval is allowed exactly when the grower's
        `advance_outstanding_cents` plus the new `amount_cents` is at most the
        cap — the boundary is inclusive — and otherwise fails with
        `ERR_ADVANCE_CAP_EXCEEDED`."

        Design: Corner/calculations/advance_cap_inclusive_boundary
        """
        scenario = setup_posted_scenario("CA3")
        pool = scenario["pool"]
        assert pool["provisional_price_cents_per_ge_box"] == 514
        grower_id = scenario["grower"]["id"]
        # cap = round_half_up(0.60 * 96.8 * 514) = 29853.
        at_cap = validate_success(api_client.create_advance(
            create_advance_payload(grower_id, pool["id"], 29853), ACCOUNTANT),
            expected_status=201)
        issued = validate_success(api_client.approve_advance(
            at_cap["id"], ACCOUNTANT))
        assert issued["status"] == "ISSUED"
        assert get_grower(grower_id)["advance_outstanding_cents"] == 29853
        # One cent over the cap is refused.
        over = validate_success(api_client.create_advance(
            create_advance_payload(grower_id, pool["id"], 1), ACCOUNTANT),
            expected_status=201)
        resp = api_client.approve_advance(over["id"], ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_ADVANCE_CAP_EXCEEDED)
        assert get_advance(over["id"])["status"] == "REQUESTED"


class TestGrowerSelfService:
    def test_grower_self_service_advance_request(self, api):
        """PRD §3.6: "A `Grower` — for its own `grower_id` only — or a
        `PoolAccountant` requests one with `grower_id`, `pool_id`, an
        `amount_cents` greater than zero, and an optional `recoup_policy` of
        `NEXT_SETTLEMENT_FULL` or `PRO_RATA_THIRDS` that defaults to
        `NEXT_SETTLEMENT_FULL`. The advance is born `REQUESTED` with
        `issued_at` null and `recouped_cents` and `written_off_cents` zero".
        PRD §2.1: "A mismatch is rejected with
        `ERR_GROWER_OWNERSHIP_MISMATCH` (HTTP 403)."

        Design: Corner/rbac/grower_self_service_advance_request
        """
        set_clock("2026-08-01T00:00:00Z")
        grower_a = create_grower("GR-RB3A", "Adv A")
        grower_b = create_grower("GR-RB3B", "Adv B")
        pool = create_pool("HAMLIN", "2026-07-27")
        own = validate_success(api_client.create_advance(
            create_advance_payload(grower_a["id"], pool["id"], 5000),
            make_grower_headers(grower_a["id"])), expected_status=201)
        assert own["status"] == "REQUESTED"
        assert own["recoup_policy"] == "NEXT_SETTLEMENT_FULL", "default applied"
        assert own["issued_at"] is None
        assert own["outstanding_cents"] == 5000
        # An advance naming another grower is an ownership violation.
        resp = api_client.create_advance(
            create_advance_payload(grower_b["id"], pool["id"], 5000),
            make_grower_headers(grower_a["id"]))
        validate_error(resp, ApiErrorId.ERR_GROWER_OWNERSHIP_MISMATCH)
