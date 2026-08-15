"""Order pricing: budget variant literals, budget/contract divergence, invoice summary."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS,
    validate_success, get_success_data,
    setup_approved_order, get_order, configure_order, make_drawing,
    submit_drawing, approve_drawing, make_project, make_order, make_opening,
)

ANY_H = TEST_USERS["any_headers"]
EST_H = TEST_USERS["estimator_headers"]

# MAPLE TEMPLATE_PREP MIN_20 order shared by the pinned pricing scenario:
# opening 101 (2 leaves, MIN_20) + opening 102 (1 leaf, NONE).
_PRICING_OPENINGS = (
    {"opening_no": "101", "leaf_count": 2, "fire_rating": "MIN_20",
     "required_on_site_date": "2026-10-01"},
    {"opening_no": "102", "leaf_count": 1, "fire_rating": "NONE",
     "required_on_site_date": "2026-10-01"},
)

# PRD §3.2 budget variant, worked by hand from the stated constants:
#   line(101) = round_half_up(2*38000*1.12*1.08) + 5500 = 91930 + 5500 = 97430
#   line(102) = round_half_up(1*38000*1.12*1.08) + 5500 = 45965 + 5500 = 51465
#   budget_quote_cents = 97430 + 51465 + 25000 = 173895
EXPECTED_BUDGET_CENTS = 173895


def _approved_pricing_order(contract_code, order_code):
    return setup_approved_order(
        contract_code=contract_code, name="Hillcrest Tower", site_address="1200 Grand Ave",
        species="MAPLE", finish_system="STAIN", sheen_target="SATIN",
        hardware_prep_mode="TEMPLATE_PREP", fire_rating_required="MIN_20",
        order_code=order_code, profile_code="PR-7",
        template_code="T-FR-1", template_fire_rated=True,
        openings=_PRICING_OPENINGS,
    )


class TestBudgetVsContractDivergence:
    def test_budget_quote_literal_at_configure(self, api):
        """PRD §3.2: "Each line is the opening's `leaf_count` multiplied by the
        species base price, then uplifted by a flat 12% waste allowance and a
        further flat 8% finish upcharge, with the result rounded half-up to
        whole cents; a flat hardware allowance of 5500 cents per opening is
        then added to the line. The budget quote is the sum of those lines plus
        a single flat freight allowance of 25000 cents."

        Design: Difficulty/dual_variant_calc/order_pricing_budget_vs_contract_divergence
        """
        project = make_project(name="Hillcrest Tower", site_address="1200 Grand Ave",
                               contract_code="C-1001")
        template = get_success_data(api.create_hardware_template(
            {"template_code": "T-FR-1", "manufacturer": "ACME", "fire_rated_compatible": True},
            TEST_USERS["plant_manager_headers"],
        ))
        order = make_order(project["id"], order_code="O-1001", species="MAPLE",
                           profile_code="PR-7", hardware_prep_mode="TEMPLATE_PREP",
                           fire_rating_required="MIN_20", hardware_template_id=template["id"])
        make_opening(order["id"], opening_no="101", leaf_count=2, fire_rating="MIN_20")
        make_opening(order["id"], opening_no="102", width_in=30, height_in=80,
                     leaf_count=1, fire_rating="NONE")

        configured = validate_success(
            api.set_order_status(order["id"], {"target_status": "CONFIGURED"}, EST_H), 200,
        )
        assert configured["budget_quote_cents"] == EXPECTED_BUDGET_CENTS, (
            f"budget variant: expected {EXPECTED_BUDGET_CENTS}, "
            f"got {configured['budget_quote_cents']}"
        )
        # The read path must agree with the mutation response (immediate consistency).
        fetched = get_order(order["id"])
        assert fetched["budget_quote_cents"] == EXPECTED_BUDGET_CENTS

    def test_contract_variant_diverges_from_budget(self, api):
        """PRD §3.3: "The contract variant reprices the same non-cancelled
        openings the budget variant saw — by construction the two variants
        yield different totals for identical input." and "The freight lands in
        `freight_fee_cents`, and `contract_price_cents` is the merchandise
        total plus the freight fee."

        Design: Difficulty/dual_variant_calc/order_pricing_budget_vs_contract_divergence
        """
        ctx = _approved_pricing_order("C-1001B", "O-1001")
        order = get_order(ctx["order"]["id"])

        assert order["budget_quote_cents"] == EXPECTED_BUDGET_CENTS, (
            "the provisional budget quote is retained after approval"
        )
        merch = order["merchandise_total_cents"]
        freight = order["freight_fee_cents"]
        contract = order["contract_price_cents"]
        for field_name, value in (("merchandise_total_cents", merch),
                                  ("freight_fee_cents", freight),
                                  ("contract_price_cents", contract)):
            assert isinstance(value, int) and value > 0, (
                f"{field_name} must be computed at approval, got {value!r}"
            )
        assert contract == merch + freight, (
            "contract_price_cents is the merchandise total plus the freight fee"
        )
        assert contract != order["budget_quote_cents"], (
            "the two variants yield different totals for identical input"
        )


class TestInvoiceSummary:
    def test_invoice_summary_computed_read_matches_order(self, api):
        """PRD §3.3: "A computed read, the order's invoice summary, reports the
        rolled-up figures — `merchandise_total_cents`, `freight_fee_cents`,
        `contract_price_cents`, the provisional `budget_quote_cents`, and the
        priced `line_count` — recomputed under the same pinned rounding order."

        Design: Corner/endpoints/invoice_summary_computed_read_matches_order
        """
        ctx = _approved_pricing_order("CE-1", "O-E1")
        order = get_order(ctx["order"]["id"])
        summary = validate_success(api.get_invoice_summary(ctx["order"]["id"], ANY_H), 200)

        assert summary["merchandise_total_cents"] == order["merchandise_total_cents"]
        assert summary["freight_fee_cents"] == order["freight_fee_cents"]
        assert summary["contract_price_cents"] == order["contract_price_cents"]
        assert summary["budget_quote_cents"] == EXPECTED_BUDGET_CENTS
        assert summary["budget_quote_cents"] == order["budget_quote_cents"]
        assert summary["line_count"] == 2, "two non-cancelled openings price two lines"


class TestImmediateConsistency:
    def test_immediate_consistency_read_after_write(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field." PRD §3.2: "On a successful configure, the system computes
        and stores the provisional price in `budget_quote_cents`".

        Design: Corner/consistency_model/immediate_consistency_read_after_write
        """
        project = make_project(name="P", contract_code="CCY-1")
        order = make_order(project["id"], order_code="O-CY1", species="OAK",
                           profile_code="PR-1", hardware_prep_mode="INSTALLER_PREP",
                           fire_rating_required="NONE")
        make_opening(order["id"], opening_no="1", leaf_count=2, fire_rating="NONE")

        # OAK 2-leaf budget line: round_half_up(2*42000*1.12*1.08) = 101606,
        # + 5500 hardware, + 25000 flat freight -> 132106.
        expected_budget = 132106
        resp_order = validate_success(
            api.set_order_status(order["id"], {"target_status": "CONFIGURED"}, EST_H), 200,
        )
        assert resp_order["status"] == "CONFIGURED"
        assert resp_order["budget_quote_cents"] == expected_budget, (
            f"mutation response must carry the computed budget, got "
            f"{resp_order['budget_quote_cents']}"
        )
        fetched = get_order(order["id"])
        assert fetched["status"] == "CONFIGURED"
        assert fetched["budget_quote_cents"] == resp_order["budget_quote_cents"], (
            "an immediate read returns identical values — no lag"
        )
