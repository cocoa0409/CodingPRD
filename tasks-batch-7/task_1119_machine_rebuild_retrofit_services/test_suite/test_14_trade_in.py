"""Trade-in valuation and credit: both variants computed and pinned by the
valuation variant, offer supersession, the acceptance cascade through machine,
project, lines and stock, the apply/revoke conservation pair, lazy expiry, and
the apply/revoke referential gates."""

from datetime import datetime, timedelta

import test_helpers as fx
from test_helpers import (
    PM,
    ApiErrorId,
    make_customer_headers,
    validate_error,
    validate_success,
)

ASSESSOR_1 = "assessor-1"


def _assessed_machine(api, year_of_manufacture=2016, machine_type="LATHE"):
    """A machine with an ACCEPTED assessment (wear 57.00 -> MECHANICAL_REBUILD)."""
    customer = fx.create_customer()
    machine = fx.create_machine(
        customer["id"], machine_type=machine_type, year_of_manufacture=year_of_manufacture,
        spindle_hours=50_000,
    )
    assessment = fx.create_assessment(machine["id"], assessor_id=ASSESSOR_1)
    fx.submit_assessment(assessment["id"], assessor_id=ASSESSOR_1)
    fx.accept_assessment(assessment["id"])
    return customer, machine


class TestResidualValueVariants:
    def test_both_variants_stored_and_variant_pins_residual(self, api):
        """PRD §3.9: "Creation always computes and stores both valuations — `market_value_cents` and `cost_value_cents` — regardless of variant, and then pins `residual_value_cents` to the market value when the variant is `MARKET_COMPARABLE` and to the cost value when it is `COST_APPROACH`."

        Design: Difficulty/dual_variant_calc/residual_value_market_vs_cost_diverge
        """
        customer, machine = _assessed_machine(api)

        market_offer = fx.create_offer(machine["id"], valuation_variant="MARKET_COMPARABLE")
        assert isinstance(market_offer["market_value_cents"], int)
        assert isinstance(market_offer["cost_value_cents"], int)
        assert market_offer["residual_value_cents"] == market_offer["market_value_cents"]
        assert market_offer["valuation_variant"] == "MARKET_COMPARABLE"

        cost_offer = fx.create_offer(machine["id"], valuation_variant="COST_APPROACH")
        assert isinstance(cost_offer["market_value_cents"], int)
        assert isinstance(cost_offer["cost_value_cents"], int)
        assert cost_offer["residual_value_cents"] == cost_offer["cost_value_cents"]
        assert cost_offer["valuation_variant"] == "COST_APPROACH"

    def test_new_offer_supersedes_prior_offered_offer(self, api):
        """PRD §3.9: "Creation also supersedes the machine's prior offer: any existing `OFFERED` offer of the same machine moves to the terminal `SUPERSEDED`, and the machine's `version` increments by one."

        Design: Difficulty/dual_variant_calc/residual_value_market_vs_cost_diverge
        """
        customer, machine = _assessed_machine(api)
        version_before = fx.get_machine(machine["id"])["version"]

        first = fx.create_offer(machine["id"], valuation_variant="MARKET_COMPARABLE")
        assert first["status"] == "OFFERED"
        second = fx.create_offer(machine["id"], valuation_variant="COST_APPROACH")
        assert second["status"] == "OFFERED"

        first_after = validate_success(api.get_trade_in_offer(first["id"], PM), 200)
        assert first_after["status"] == "SUPERSEDED"
        machine_after = fx.get_machine(machine["id"])
        assert machine_after["version"] == version_before + 2


class TestTradeInAcceptCascade:
    PARTS_SPEC = [
        {"oem_status": "ACTIVE", "unit_cost_cents": 1_250_000, "stock_quantity": 10,
         "quantity": 2},
    ]

    def _project_in_sourcing_with_offer(self, api):
        """Project machine in PARTS_SOURCING (line RESERVED) + an OFFERED offer
        on the project machine itself."""
        ctx = fx.setup_project_approved(parts_spec=self.PARTS_SPEC)
        validate_success(api.begin_sourcing(ctx.project["id"], PM), 200)
        offer = fx.create_offer(ctx.machine["id"], valuation_variant="COST_APPROACH")
        return ctx, offer

    def test_accept_trades_in_machine_and_cancels_project(self, api):
        """PRD §3.9: "A successful acceptance moves the offer to the terminal `ACCEPTED` and fires the trade-in cascade."
        PRD §3.9: "First, the machine moves from `REGISTERED` to the terminal `TRADED_IN`. Second, every RebuildProject of that machine whose `work_status` is `SCOPED`, `DECIDED`, or `PARTS_SOURCING` is moved to `CANCELLED`."

        Design: Difficulty/transitive_cascade/trade_in_accept_cascade_depth3
        """
        ctx, offer = self._project_in_sourcing_with_offer(api)
        assert fx.get_project(ctx.project["id"])["work_status"] == "PARTS_SOURCING"

        accepted = fx.accept_offer(offer["id"], ctx.customer["id"])
        assert accepted["status"] == "ACCEPTED"

        # The machine's own transition is pinned by the PRD only from
        # `REGISTERED` (§3.1: "accepting a trade-in offer for a `REGISTERED`
        # machine moves it to the terminal `TRADED_IN`"); this machine is
        # `IN_PROJECT`, a case the PRD leaves unpinned, so no machine-status
        # assertion is made here.
        project = fx.get_project(ctx.project["id"])
        assert project["work_status"] == "CANCELLED"

    def test_accept_cancels_lines_and_releases_reserved_stock(self, api):
        """PRD §3.9: "Third, on each such cancelled project, every part line in `PENDING`, `RESERVED`, or `RE_PENDING` moves to `CANCELLED`; the reservation of each `RESERVED` line is released, decreasing the part's `reserved_quantity` by the line's `quantity`; and the reverse-engineering jobs of `RE_PENDING` lines move to `CANCELLED`."
        PRD §2.9: "The part ledger obeys a strict conservation law: for every Part, `available_quantity` plus `reserved_quantity` always equals `stock_quantity`."

        Design: Difficulty/transitive_cascade/trade_in_accept_cascade_depth3
        """
        ctx, offer = self._project_in_sourcing_with_offer(api)
        part = ctx.parts[0]
        line = ctx.lines[0]

        part_before = fx.get_part(part["id"])
        assert part_before["reserved_quantity"] == 2
        assert part_before["available_quantity"] == 8
        assert part_before["stock_quantity"] == 10

        fx.accept_offer(offer["id"], ctx.customer["id"])

        line_after = validate_success(api.get_part_line(line["id"], PM), 200)
        assert line_after["status"] == "CANCELLED"

        part_after = fx.get_part(part["id"])
        assert part_after["reserved_quantity"] == 0
        assert part_after["available_quantity"] == 10
        assert part_after["stock_quantity"] == 10
        fx.assert_part_stock_conservation(part_after)


class TestTradeInCreditConservation:
    def _quoted_project_with_accepted_offer(self, api):
        """DECIDED project with a computed quote + a second machine of the same
        customer carrying an ACCEPTED COST_APPROACH offer."""
        ctx = fx.setup_project_quoted()
        quote_price_before = ctx.project["quote_price_cents"]
        offer_ctx = fx.setup_accepted_offer(
            machine_overrides={"machine_type": "LATHE", "year_of_manufacture": 2016,
                               "control_generation": "MODERN", "spindle_hours": 30_000},
            valuation_variant="COST_APPROACH",
            customer=ctx.customer,
        )
        return ctx, offer_ctx, quote_price_before

    def test_apply_moves_credit_into_quote(self, api):
        """PRD §3.9: "Applying sets the project's `applied_trade_in_credit_cents` to the offer's `residual_value_cents`, reduces `quote_price_cents` by that same amount, and stamps the offer's `applied_project_id` with the project."
        PRD §2.10: "A conservation law ties the snapshot together: `quote_price_cents` plus `applied_trade_in_credit_cents` always equals `base_price_cents` plus `parts_total_cents` plus `labor_cents` minus `discount_cents`."

        Design: Difficulty/compensating_invariant/trade_in_credit_conservation_across_apply_and_revoke
        """
        ctx, offer_ctx, quote_before = self._quoted_project_with_accepted_offer(api)
        residual = offer_ctx.offer["residual_value_cents"]

        applied = validate_success(
            api.apply_trade_in(ctx.project["id"], {"offer_id": offer_ctx.offer["id"]}, PM), 200
        )
        assert applied["applied_trade_in_credit_cents"] == residual
        assert applied["quote_price_cents"] == quote_before - residual
        fx.assert_quote_conservation(applied)

        offer_after = validate_success(api.get_trade_in_offer(offer_ctx.offer["id"], PM), 200)
        assert offer_after["applied_project_id"] == ctx.project["id"]

    def test_revoke_restores_gross_quote_exactly(self, api):
        """PRD §3.9: "Revoking — the mechanism for backing a credit out before the customer approves the quote — requires a credit to be present, failing which `ERR_TRADE_IN_ALREADY_APPLIED` is returned; it restores `quote_price_cents` by adding the applied amount back, zeroes `applied_trade_in_credit_cents`, and clears the offer's `applied_project_id`."
        PRD §2.10: "Applying or revoking a trade-in credit moves value between `quote_price_cents` and `applied_trade_in_credit_cents` only; the gross quote on the right-hand side is left unchanged by that pair of operations."

        Design: Difficulty/compensating_invariant/trade_in_credit_conservation_across_apply_and_revoke
        """
        ctx, offer_ctx, quote_before = self._quoted_project_with_accepted_offer(api)
        validate_success(
            api.apply_trade_in(ctx.project["id"], {"offer_id": offer_ctx.offer["id"]}, PM), 200
        )

        revoked = validate_success(api.revoke_trade_in(ctx.project["id"], PM), 200)
        assert revoked["applied_trade_in_credit_cents"] == 0
        assert revoked["quote_price_cents"] == quote_before
        fx.assert_quote_conservation(revoked)

        offer_after = validate_success(api.get_trade_in_offer(offer_ctx.offer["id"], PM), 200)
        assert offer_after["applied_project_id"] is None


def test_offer_decline_then_accept_rejected(api):
    """PRD §3.9: "Acceptance is the customer's act: the caller's `X-User-ID` must equal the offer's `customer_id`, and the offer must still be `OFFERED`."
    PRD §3.9: "A customer may instead decline an `OFFERED` offer — again with `X-User-ID` matching the offer's `customer_id` — moving it to the terminal `DECLINED`."

    Design: Corner/state_machines/offer_decline_then_accept_rejected
    """
    customer = fx.create_customer()
    machine = fx.create_machine(customer["id"], machine_type="GRINDER",
                                year_of_manufacture=2012, spindle_hours=80_000)
    offer = fx.create_offer(machine["id"], valuation_variant="MARKET_COMPARABLE")

    declined = validate_success(
        api.decline_trade_in_offer(offer["id"], make_customer_headers(customer["id"])), 200
    )
    assert declined["status"] == "DECLINED"

    res = api.accept_trade_in_offer(offer["id"], make_customer_headers(customer["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_offer_expiry_lazy_on_accept(api):
    """PRD §3.9: "The offer's `expires_at` is set to its `created_at` plus thirty days on the logical clock."
    PRD §3.9: "If the logical clock has passed `expires_at`, the offer flips to the terminal `EXPIRED` and the attempt fails with `ERR_TRADE_IN_OFFER_EXPIRED`; acceptance at exactly the `expires_at` instant still succeeds."
    PRD §2.7: "Trade-in offers are never swept: offer expiry is evaluated lazily at acceptance time, as described in §3.9."

    Design: Corner/validations/offer_expiry_lazy_on_accept
    """
    customer = fx.create_customer()
    machine = fx.create_machine(customer["id"], machine_type="GRINDER",
                                year_of_manufacture=2010, spindle_hours=90_000)
    offer = fx.create_offer(machine["id"], valuation_variant="MARKET_COMPARABLE")

    created_at = datetime.fromisoformat(offer["created_at"].replace("Z", "+00:00"))
    expires_at = datetime.fromisoformat(offer["expires_at"].replace("Z", "+00:00"))
    assert expires_at - created_at == timedelta(days=30)

    # The default clock is 2026-05-01; advancing 35 days passes expires_at.
    fx.set_clock("2026-06-05T00:00:00Z")
    res = api.accept_trade_in_offer(offer["id"], make_customer_headers(customer["id"]))
    validate_error(res, ApiErrorId.ERR_TRADE_IN_OFFER_EXPIRED.value)

    offer_after = validate_success(api.get_trade_in_offer(offer["id"], PM), 200)
    assert offer_after["status"] == "EXPIRED"


def test_trade_in_apply_wrong_customer_rejected(api):
    """PRD §3.9: "A `ProjectManager` applies it to a project's quote by passing the `offer_id`: the offer must be `ACCEPTED`, must belong to the same customer as the project, and must not already be applied to another project — any breach is rejected with `ERR_TRADE_IN_NOT_APPLICABLE` — and the project must not already carry an applied credit, otherwise `ERR_TRADE_IN_ALREADY_APPLIED`."

    Design: Corner/validations/trade_in_apply_wrong_customer_rejected
    """
    # Customer A's quoted project; customer B holds the accepted offer.
    ctx = fx.setup_project_quoted(customer_overrides={"name": "Customer A"})
    project_id = ctx.project["id"]
    customer_b = fx.create_customer(name="Customer B")

    # Customer B's accepted offer on B's own machine.
    offer_ctx = fx.setup_accepted_offer(
        machine_overrides={"machine_type": "MILL", "year_of_manufacture": 2014,
                           "spindle_hours": 70_000},
        valuation_variant="COST_APPROACH",
        customer=customer_b,
    )

    res = api.apply_trade_in(project_id, {"offer_id": offer_ctx.offer["id"]}, PM)
    validate_error(res, ApiErrorId.ERR_TRADE_IN_NOT_APPLICABLE.value)


def test_trade_in_revoke_without_credit_rejected(api):
    """PRD §3.9: "Revoking — the mechanism for backing a credit out before the customer approves the quote — requires a credit to be present, failing which `ERR_TRADE_IN_ALREADY_APPLIED` is returned; it restores `quote_price_cents` by adding the applied amount back, zeroes `applied_trade_in_credit_cents`, and clears the offer's `applied_project_id`."

    Design: Corner/validations/trade_in_revoke_without_credit_rejected
    """
    ctx = fx.setup_project_quoted()
    assert ctx.project["applied_trade_in_credit_cents"] == 0

    res = api.revoke_trade_in(ctx.project["id"], PM)
    validate_error(res, ApiErrorId.ERR_TRADE_IN_ALREADY_APPLIED.value)
