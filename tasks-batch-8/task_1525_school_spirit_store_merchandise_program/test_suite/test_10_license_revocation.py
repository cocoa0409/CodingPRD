"""Licensing gate: revocation cascade depth-3, safety-over-temporal priority."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_active_program,
    create_approved_design,
    create_approved_vendor_with_quote,
    create_design,
    create_drop,
    create_open_campaign,
    create_order_line,
    create_order_payload,
    create_variant,
    design_transition,
    drop_transition,
    get_campaign,
    get_variant,
    make_customer_headers,
    place_paid_preorder,
    place_preorder,
    set_clock,
    stock_variant,
    TEST_USERS,
    validate_error,
    validate_success,
)

DIRECTOR = TEST_USERS["director_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
TREASURER = TEST_USERS["treasurer_headers"]


class TestDesignRevokeCascade:
    def _setup_revokable(self, api):
        """APPROVED design, variants M and S, OPEN campaign (goal 100) with
        P1 M qty 2 PAID (deposit 2000) and P2 S qty 1 PLACED."""
        program = create_active_program()
        design = create_approved_design(program["id"])
        variant_m = create_variant(program["id"], design["id"], size="M")
        variant_s = create_variant(program["id"], design["id"], size="S")
        campaign = create_open_campaign(
            program["id"], design["id"], goal_units=100
        )
        p1 = place_paid_preorder(
            program["id"], campaign["id"], variant_m["id"], "cust-01", 2
        )
        p2 = place_preorder(
            program["id"], campaign["id"], variant_s["id"], "cust-02", 1
        )
        assert p1["status"] == "PAID" and p1["deposit_paid_cents"] == 2000
        assert p2["status"] == "PLACED"
        return program, design, variant_m, campaign, p1, p2

    def test_revoke_unsellables_variants_and_cancels_campaign(self, api):
        """PRD §3.2: "First, every variant of the design recomputes
        `sellable` to false. Second, every preorder campaign of the design
        still in `OPEN` or `IN_PRODUCTION` auto-transitions to `CANCELLED`,
        because its merchandise is no longer sellable."

        Design: Difficulty/transitive_cascade/design_revoke_cascade_depth3
        """
        program, design, variant_m, campaign, p1, p2 = self._setup_revokable(api)
        revoked = design_transition(
            design["id"], "REVOKED", design["version"], note="trademark dispute"
        )
        assert revoked["status"] == "REVOKED"

        variant_after = get_variant(variant_m["id"])
        assert variant_after["sellable"] is False, (
            "link 1: variant recomputed unsellable"
        )
        campaign_after = get_campaign(campaign["id"])
        assert campaign_after["status"] == "CANCELLED", (
            "link 2: OPEN campaign auto-cancelled because its design became "
            "unsellable"
        )

    def test_revoke_cascade_refunds_paid_and_cancels_placed_preorders(self, api):
        """PRD §3.2: "Third, within each cancelled campaign, every preorder in
        `PAID` moves to `REFUNDED` with `refunded_cents` set to the sum of its
        `deposit_paid_cents` and `balance_paid_cents`, while every preorder
        still in `PLACED` moves to `CANCELLED`."

        Design: Difficulty/transitive_cascade/design_revoke_cascade_depth3
        """
        program, design, variant_m, campaign, p1, p2 = self._setup_revokable(api)
        design_transition(
            design["id"], "REVOKED", design["version"], note="trademark dispute"
        )
        p1_after = validate_success(api.get_preorder(p1["id"], TREASURER), 200)
        assert p1_after["status"] == "REFUNDED"
        assert p1_after["refunded_cents"] == 2000, (
            "deposit_paid 2000 + balance_paid 0"
        )
        p2_after = validate_success(api.get_preorder(p2["id"], TREASURER), 200)
        assert p2_after["status"] == "CANCELLED", (
            "PLACED preorder cancelled, no money moved"
        )


class TestSafetyBeatsTemporalOnOrderCreate:
    def _setup_revoked_closed_drop(self, api, revoke=True):
        """Drop [09-01, 10-01) opened then CLOSED; variant M attached to it
        and stocked 25; optionally the design is then REVOKED."""
        program = create_active_program()
        design = create_approved_design(program["id"], name="DropArt")
        drop = create_drop(
            program["id"],
            program["version"],
            name="Fall Drop",
            opens_at="2026-09-01T00:00:00Z",
            closes_at="2026-10-01T00:00:00Z",
        )
        variant = create_variant(
            program["id"], design["id"], size="M", unit_price_cents=3000,
            drop_id=drop["id"],
        )
        vendor = create_approved_vendor_with_quote(program["id"], design["id"])
        stock_variant(program["id"], variant["id"], vendor["id"], 25)
        set_clock("2026-09-05T12:00:00Z")
        drop_transition(drop["id"], "OPEN")
        drop_transition(drop["id"], "CLOSED")
        if revoke:
            design_transition(
                design["id"], "REVOKED", design["version"],
                note="licensor pulled rights",
            )
        return program, variant

    def test_revoked_design_and_closed_drop_yields_license_revoked(self, api):
        """PRD §2.8: "Selling, preordering, submitting a purchase order, or
        opening a campaign all require the underlying design to be `APPROVED`:
        a `REVOKED` design yields `ERR_LICENSE_REVOKED`, and any other
        non-approved status yields `ERR_DESIGN_NOT_LICENSED`."
        PRD §2.8: "The ordering is normative: when a request would fail two
        checks, the earlier check's error is the one returned."

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_on_order_create
        """
        program, variant = self._setup_revoked_closed_drop(api, revoke=True)
        res = api.create_order(
            create_order_payload(
                program["id"], "ONLINE", "cust-20", "CARD",
                [create_order_line(variant["id"], 1)],
            ),
            make_customer_headers("cust-20"),
        )
        validate_error(res, ApiErrorId.ERR_LICENSE_REVOKED, 409)

    def test_closed_drop_alone_yields_drop_not_open(self, api):
        """PRD §3.6: "A line whose variant is pinned to a seasonal drop can be
        sold only while that drop is `OPEN`; otherwise the sale fails with
        `ERR_DROP_NOT_OPEN`."

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_on_order_create
        """
        program, variant = self._setup_revoked_closed_drop(api, revoke=False)
        res = api.create_order(
            create_order_payload(
                program["id"], "ONLINE", "cust-20", "CARD",
                [create_order_line(variant["id"], 1)],
            ),
            make_customer_headers("cust-20"),
        )
        validate_error(res, ApiErrorId.ERR_DROP_NOT_OPEN, 409)


class TestLicensingGateOnSale:
    def test_order_with_unlicensed_design_rejected(self, api):
        """PRD §2.8: "Selling, preordering, submitting a purchase order, or
        opening a campaign all require the underlying design to be `APPROVED`:
        a `REVOKED` design yields `ERR_LICENSE_REVOKED`, and any other
        non-approved status yields `ERR_DESIGN_NOT_LICENSED`."

        Design: Corner/errors/order_with_unlicensed_design_rejected
        """
        program = create_active_program()
        design = create_design(program["id"])  # stays DRAFT
        variant = create_variant(program["id"], design["id"], size="M")
        res = api.create_order(
            create_order_payload(
                program["id"], "ONLINE", "cust-87", "CARD",
                [create_order_line(variant["id"], 1)],
            ),
            make_customer_headers("cust-87"),
        )
        validate_error(res, ApiErrorId.ERR_DESIGN_NOT_LICENSED, 409)
