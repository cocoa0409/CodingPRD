"""Reconciliation claims: filing gates, adjudication, the appeal chain, and
the two resolution branches."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    close_ordering_at_window_end,
    create_and_submit_order,
    create_approved_claim,
    create_claim,
    create_group,
    create_product,
    create_seller,
    create_submitted_paid_order,
    create_campaign,
    drive_campaign_to_distribution_complete,
    drive_campaign_to_sorted,
    get_group_ledger,
    get_order_line_id,
    get_success_data,
    make_admin_headers,
    reset_clock,
    setup_open_campaign_with_seller,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
TREAS = TEST_USERS["treasurer_headers"]


def _open_campaign(api, **product_overrides):
    """Campaign OPEN with one group, one product, one seller."""
    campaign = create_campaign()
    group = create_group(campaign["id"])
    product = create_product(campaign["id"], **product_overrides)
    seller = create_seller(group["id"])
    get_success_data(api.open_campaign(campaign["id"], ADMIN))
    return campaign, group, product, seller


def _sorted_with_paid_order(api, quantity=2, delivered_units=12,
                            **product_overrides):
    """Campaign at SORTED with one fully paid order. Returns the context."""
    reset_clock()
    campaign, group, product, seller = _open_campaign(api,
                                                      **product_overrides)
    order = create_submitted_paid_order(seller["id"], product["id"], quantity)
    close_ordering_at_window_end(campaign["id"])
    drive_campaign_to_sorted(campaign["id"], product["id"], delivered_units)
    line_id = get_order_line_id(order["id"])
    return campaign, group, product, seller, order, line_id


def _distribution_complete_with_paid_order(api, quantity=3,
                                           delivered_units=12,
                                           **product_overrides):
    """Campaign at DISTRIBUTION_COMPLETE with one fully paid order (clock
    inside the return window afterwards)."""
    reset_clock()
    campaign, group, product, seller = _open_campaign(api,
                                                      **product_overrides)
    order = create_submitted_paid_order(seller["id"], product["id"], quantity)
    close_ordering_at_window_end(campaign["id"])
    drive_campaign_to_distribution_complete(
        campaign["id"], product["id"], delivered_units)
    reset_clock("2026-09-08T10:00:00Z")
    line_id = get_order_line_id(order["id"])
    return campaign, group, product, seller, order, line_id


class TestClaimFilingGates:
    def test_claim_qty_exceeds_available_rejected(self, api):
        """PRD §3.6: "the claimed quantity must not exceed the line's
        availability net of returns already received, claims already resolved
        as refunds, and sort shortage allocated to the line — else
        `ERR_CLAIM_QTY_EXCEEDS_AVAILABLE`."

        Design: Corner/validations/claim_qty_exceeds_available_rejected
        """
        _c, _g, _p, _s, order, line_id = _sorted_with_paid_order(
            api, quantity=2)
        resp = api.create_claim({
            "order_id": order["id"], "order_line_id": line_id,
            "claim_type": "MISSING", "quantity": 3,
        }, COORD)
        validate_error(resp, ApiErrorId.ERR_CLAIM_QTY_EXCEEDS_AVAILABLE)

    def test_claim_line_mismatch_referential_beats_quantity_rejected(self, api):
        """PRD §2.10: "Tenth, cross-entity consistency: body entities must
        belong to the same campaign (`ERR_CROSS_CAMPAIGN_REFERENCE`), and a
        supplied `order_line_id` must belong to the supplied `order_id`
        (`ERR_ORDER_LINE_MISMATCH`). Eleventh, business constraints —
        uniqueness, overlaps, capacity, quantity availability, limits, and
        policy gates".

        Design: Difficulty/priority_pair_validation_conflict/claim_line_mismatch_referential_beats_quantity_constraint_rejected
        """
        reset_clock()
        campaign, _group, product, seller = setup_open_campaign_with_seller()
        order1 = create_and_submit_order(seller["id"], product["id"], 2)
        order2 = create_and_submit_order(seller["id"], product["id"], 2,
                                         family_contact_name="Fam2")
        close_ordering_at_window_end(campaign["id"])
        drive_campaign_to_sorted(campaign["id"], product["id"], 12)
        line1 = get_order_line_id(order1["id"])
        line2 = get_order_line_id(order2["id"])
        assert line1 != line2
        # The line belongs to a DIFFERENT order AND the quantity is
        # impossible: referential consistency (tenth) masks the quantity
        # constraint (eleventh).
        resp = api.create_claim({
            "order_id": order1["id"], "order_line_id": line2,
            "claim_type": "MISSING", "quantity": 99,
        }, COORD)
        validate_error(resp, ApiErrorId.ERR_ORDER_LINE_MISMATCH)
        claims, _meta = validate_paginated(
            api.list_claims(COORD, params={"order_id": order1["id"]}))
        assert claims == [], "no claim row may persist after rejection"

    def test_claim_line_mismatch_alone_rejected(self, api):
        """PRD §3.6: "the `order_line_id` (which must belong to that order,
        else `ERR_ORDER_LINE_MISMATCH`, and must resolve, else
        `ERR_ORDER_LINE_NOT_FOUND`)".

        Design: Difficulty/priority_pair_validation_conflict/claim_line_mismatch_referential_beats_quantity_constraint_rejected
        """
        reset_clock()
        campaign, _group, product, seller = setup_open_campaign_with_seller()
        order1 = create_and_submit_order(seller["id"], product["id"], 2)
        order2 = create_and_submit_order(seller["id"], product["id"], 2,
                                         family_contact_name="Fam2")
        close_ordering_at_window_end(campaign["id"])
        drive_campaign_to_sorted(campaign["id"], product["id"], 12)
        line2 = get_order_line_id(order2["id"])
        resp = api.create_claim({
            "order_id": order1["id"], "order_line_id": line2,
            "claim_type": "MISSING", "quantity": 1,
        }, COORD)
        validate_error(resp, ApiErrorId.ERR_ORDER_LINE_MISMATCH)


class TestAppealChain:
    def test_claim_appeal_creates_successor_claim(self, api):
        """PRD §3.6: "A `DENIED` claim may be appealed once by a coordinator:
        the appeal is admitted only when the claim's `supersedes_claim_id` is
        null — only a root claim may be appealed, one appeal per chain, else
        `ERR_APPEAL_LIMIT_EXCEEDED` — and it moves the denied claim to
        `APPEALED` while creating a successor claim in `SUBMITTED` that copies
        the order, line, type, and quantity, sets its `supersedes_claim_id` to
        the denied claim's `id`, and accepts a fresh optional `note`."

        Design: Corner/state_machines/claim_appeal_creates_successor_claim
        """
        _c, _g, _p, _s, order, line_id = _sorted_with_paid_order(api)
        claim = create_claim(order["id"], line_id, 1, "MISSING")
        get_success_data(api.deny_claim(claim["id"], ADMIN,
                                        {"reason": "insufficient evidence"}))
        resp = api.appeal_claim(claim["id"], COORD,
                                {"note": "family provided photo"})
        successor = validate_success(resp, 201)
        assert successor["status"] == "SUBMITTED"
        assert successor["supersedes_claim_id"] == claim["id"], (
            "the successor points back to the denied root claim")
        original = get_success_data(api.get_claim(claim["id"], COORD))
        assert original["status"] == "APPEALED"

    def test_claim_second_appeal_rejected(self, api):
        """PRD §3.6: "the appeal is admitted only when the claim's
        `supersedes_claim_id` is null — only a root claim may be appealed, one
        appeal per chain, else `ERR_APPEAL_LIMIT_EXCEEDED`".

        Design: Corner/state_machines/claim_second_appeal_rejected
        """
        _c, _g, _p, _s, order, line_id = _sorted_with_paid_order(api)
        claim = create_claim(order["id"], line_id, 1, "DAMAGED")
        get_success_data(api.deny_claim(claim["id"], ADMIN))
        resp = api.appeal_claim(claim["id"], COORD)
        successor = validate_success(resp, 201)
        get_success_data(api.deny_claim(successor["id"], ADMIN))
        # The successor carries supersedes_claim_id: it is not a root claim.
        second = api.appeal_claim(successor["id"], COORD)
        validate_error(second, ApiErrorId.ERR_APPEAL_LIMIT_EXCEEDED)


class TestClaimResolution:
    def test_claim_resolve_replacement_consumes_surplus(self, api):
        """PRD §3.6: "It draws the replacement from the unallocated pile: the
        product's `surplus_units` decreases by the quantity, the family keeps
        the same net units so `distributed_units` is unchanged, and when the
        claim type is `DAMAGED` the scrapped unit is added to the product's
        `lost_units`. No money moves and no ledger entry is posted for a
        replacement; the claim's `credit_cents` is zero."

        Design: Corner/state_machines/claim_resolve_replacement_consumes_surplus
        """
        campaign, group, product, _s, order, line_id = (
            _distribution_complete_with_paid_order(api, quantity=3))
        claim = create_approved_claim(order["id"], line_id, 1, "DAMAGED")
        resp = api.resolve_claim(claim["id"], {"resolution": "REPLACEMENT"},
                                 ADMIN)
        resolved = validate_success(resp, 200)
        assert resolved["status"] == "RESOLVED_REPLACEMENT"
        assert resolved["credit_cents"] == 0
        product_view = get_success_data(api.get_product(product["id"], ADMIN))
        assert product_view["surplus_units"] == 8, "9 - 1 replacement"
        assert product_view["lost_units"] == 1, "damaged unit scrapped"
        assert product_view["distributed_units"] == 3, (
            "the family keeps the same net units")
        from test_helpers import assert_product_unit_invariant
        assert_product_unit_invariant(product_view)

    def test_claim_resolve_replacement_insufficient_surplus_rejected(self, api):
        """PRD §3.6: "A **replacement** — moving the claim to
        `RESOLVED_REPLACEMENT` — is admitted only while the order's
        fulfillment is `DISTRIBUTED` or `PARTIALLY_RETURNED` (else
        `ERR_INVALID_STATE`) and only while the product's `surplus_units`
        covers the claimed quantity (else `ERR_INSUFFICIENT_SURPLUS`)."

        Design: Corner/state_machines/claim_resolve_replacement_insufficient_surplus_rejected
        """
        # case_pack_size 3 with 3 sold and 3 delivered leaves zero surplus.
        campaign, group, product, _s, order, line_id = (
            _distribution_complete_with_paid_order(
                api, quantity=3, delivered_units=3, case_pack_size=3))
        claim = create_approved_claim(order["id"], line_id, 1, "DAMAGED")
        resp = api.resolve_claim(claim["id"], {"resolution": "REPLACEMENT"},
                                 ADMIN)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SURPLUS)
        after = get_success_data(api.get_claim(claim["id"], ADMIN))
        assert after["status"] == "APPROVED"

    def test_claim_resolve_refund_posts_credit_and_loss_debit(self, api):
        """PRD §3.6: "A **refund** — moving the claim to `RESOLVED_REFUND` —
        computes the family `credit_cents` as the claim's `quantity` times the
        line's snapshotted `unit_price_cents`, adds the quantity into the
        line's `claim_resolved_refund_qty`, and posts a `CLAIM_LOSS_DEBIT` to
        the order's group equal to the quantity times the difference between
        the line's snapshotted `unit_price_cents` and `unit_cost_cents`,
        multiplied by the product's `profit_share_bps` and divided by 10000,
        rounded half up to whole cents."
        PRD §3.7: "`family_credits_cents` (the sum of `credit_cents` over
        claims in `RESOLVED_REFUND` plus the sum of `refund_cents` over
        returns in `RECEIVED_RESTOCKED` or `RECEIVED_WRITTEN_OFF`)".

        Design: Corner/state_machines/claim_resolve_refund_posts_credit_and_loss_debit
        """
        campaign, group, product, _s, order, line_id = (
            _distribution_complete_with_paid_order(api, quantity=2))
        claim = create_approved_claim(order["id"], line_id, 1, "DAMAGED")
        resp = api.resolve_claim(claim["id"], {"resolution": "REFUND"}, ADMIN)
        resolved = validate_success(resp, 200)
        assert resolved["status"] == "RESOLVED_REFUND"
        assert resolved["credit_cents"] == 1000, "1 * 1000 snapshotted price"

        ledger = get_group_ledger(group["id"])
        loss_entries = [e for e in ledger
                        if e["entry_type"] == "CLAIM_LOSS_DEBIT"]
        assert len(loss_entries) == 1
        # round_half_up(1 * (1000-600) * 5000/10000) == 200, debits negative.
        assert loss_entries[0]["amount_cents"] == -200

        order_view = get_success_data(api.get_order(order["id"], TREAS))
        assert order_view["fulfillment_status"] == "PARTIALLY_RETURNED", (
            "refunded units count toward the returned rollup")
        campaign_view = get_success_data(api.get_campaign(campaign["id"], TREAS))
        assert campaign_view["family_credits_cents"] == 1000


class TestReconcileGate:
    def test_reconcile_with_open_claim_rejected(self, api):
        """PRD §3.7: "requires that no claim of the campaign remain in
        `SUBMITTED` or `APPROVED` and no return request remain in `REQUESTED`,
        `APPROVED`, or `REJECTED` (open items reject the reconcile with
        `ERR_OPEN_CLAIMS_OR_RETURNS`)."

        Design: Corner/state_machines/reconcile_with_open_claim_rejected
        """
        campaign, group, product, seller, order, line_id = (
            _distribution_complete_with_paid_order(api, quantity=2))
        create_claim(order["id"], line_id, 1, "DAMAGED")
        reset_clock("2026-09-14T00:00:00Z")
        resp = api.reconcile_campaign(campaign["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_OPEN_CLAIMS_OR_RETURNS)
        after = get_success_data(api.get_campaign(campaign["id"], ADMIN))
        assert after["status"] == "DISTRIBUTION_COMPLETE"

    def test_reconcile_before_window_elapsed_rejected(self, api):
        """PRD §3.7: "Reconciliation by a `FundraiserAdmin` requires the
        logical clock to be strictly later than `distribution_completed_at`
        plus 7 days — reconciling while the return window is still running,
        including its final instant, is rejected with
        `ERR_RETURN_WINDOW_NOT_ELAPSED`".

        Design: Corner/state_machines/reconcile_before_window_elapsed_rejected
        """
        campaign, _g, _p, _s, _o, _l = _distribution_complete_with_paid_order(
            api, quantity=1)
        reset_clock("2026-09-10T12:00:00Z")
        resp = api.reconcile_campaign(campaign["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_RETURN_WINDOW_NOT_ELAPSED)
        after = get_success_data(api.get_campaign(campaign["id"], ADMIN))
        assert after["status"] == "DISTRIBUTION_COMPLETE"
