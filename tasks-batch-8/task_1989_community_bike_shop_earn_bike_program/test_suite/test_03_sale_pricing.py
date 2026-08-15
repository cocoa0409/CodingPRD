"""Sale pricing: quoted-vs-final snapshot variant (queue A) and tiered-formula
combinatorics (queue A) plus the member-discount corner and surcharge-cap
boundary corner (queue B)."""
from test_helpers import (
    api_client, validate_success, validate_error,
    make_donor, make_bike, triage_bike, make_part, restock_part,
    make_ready_bike, make_membership, make_helmet_part,
    log_usage, set_clock, TEST_USERS, make_member_headers,
    ApiErrorId,
)

COORD = TEST_USERS["coordinator_headers"]
DIRECTOR = TEST_USERS["director_headers"]


def _helmet_stocked(qty: int = 3):
    hp = make_helmet_part(name="Helmet M", helmet_size="M", unit_cost_cents=1500)
    restock_part(hp["id"], qty)
    return hp


def _distribute_sale_helmet(helmet_part_id: str, sale_id: str):
    return validate_success(
        api_client.create_helmet_distribution(
            {
                "helmet_part_id": helmet_part_id,
                "recipient_kind": "SALE_BUYER",
                "sale_id": sale_id,
            },
            COORD,
        ),
        expected_status=201,
    )


class TestSaleQuotedVsFinal:
    def test_quoted_frozen_with_active_member_discount(self):
        """PRD §3.9: "The new sale is `PENDING`, and creation computes
        `quoted_price_cents` under the pricing formula below, evaluated against
        the bike's data and the membership's status at creation; the quote is
        stored and never rewritten." and "Then the member discount: if the
        buyer's membership references an `ACTIVE` membership, ten percent of the
        running total, rounded half up, is subtracted; otherwise the discount is
        zero."

        Design: Difficulty/dual_variant_calc/sale_price_quoted_vs_final_on_membership_suspension
        """
        bike, part, lead, insp = make_ready_bike(
            bike_type="HYBRID", grade="A", part_unit_cost_cents=500, part_quantity=1
        )
        m = make_membership(member_name="M Buyer", member_email="mb2@x.org",
                            tier="BASIC", end_date="2026-12-31")
        sale = validate_success(
            api_client.create_sale(
                {
                    "bike_id": bike["id"],
                    "buyer_name": "B One",
                    "buyer_email": "b1@x.org",
                    "buyer_membership_id": m["id"],
                },
                COORD,
            ),
            expected_status=201,
        )
        # 9000 + min(round(500*0.5), 3000)=250 -> 9250; discount round(925) -> 8325
        assert sale["quoted_price_cents"] == 8325

    def test_final_reevaluated_after_membership_suspension(self):
        """PRD §3.9: "At completion the final price is recomputed against the
        bike's current `parts_cost_cents` and the membership's current status,
        following the same ladder; because membership status is read at
        evaluation time, a membership suspended after creation loses its
        discount and the final price can exceed the quote." and "When
        `round_up` is false, `grand_total_cents` equals the final price and
        `donation_cents` is 0." and "Completion stamps `final_price_cents`,
        `grand_total_cents`, `donation_cents`, `payment_method`, and
        `completed_at`, moves the bike `READY_FOR_DISPOSITION → SOLD`, and bumps
        both records' versions."

        Design: Difficulty/dual_variant_calc/sale_price_quoted_vs_final_on_membership_suspension
        """
        bike, part, lead, insp = make_ready_bike(
            bike_type="HYBRID", grade="A", part_unit_cost_cents=500, part_quantity=1
        )
        m = make_membership(member_name="M Buyer", member_email="mb2@x.org",
                            tier="BASIC", end_date="2026-12-31")
        sale = validate_success(
            api_client.create_sale(
                {
                    "bike_id": bike["id"],
                    "buyer_name": "B One",
                    "buyer_email": "b1@x.org",
                    "buyer_membership_id": m["id"],
                },
                COORD,
            ),
            expected_status=201,
        )
        assert sale["quoted_price_cents"] == 8325
        validate_success(api_client.suspend_membership(m["id"], {"reason": "non-payment"}, COORD))
        hp = _helmet_stocked(3)
        _distribute_sale_helmet(hp["id"], sale["id"])
        completed = validate_success(
            api_client.complete_sale(sale["id"], {"payment_method": "CASH"}, COORD)
        )
        assert completed["final_price_cents"] == 9250
        assert completed["final_price_cents"] != completed["quoted_price_cents"]
        assert completed["grand_total_cents"] == 9250
        assert completed["donation_cents"] == 0
        assert completed["status"] == "COMPLETED"
        bike_after = validate_success(api_client.get_bike(bike["id"], COORD))
        assert bike_after["status"] == "SOLD"


class TestSalePriceTieredEngine:
    def test_surcharge_cap_binds_on_mtb_c(self):
        """PRD §3.9: "Next comes the parts surcharge: half of the bike's current
        `parts_cost_cents`, rounded half up, capped at 3000 cents." and "The
        condition grade scales that base: grade `A` at full value, `B` at 0.80,
        `C` at 0.40".

        Design: Difficulty/combinatorial_formula/sale_price_tiered_engine_mode_a
        """
        bike, _, _, _ = make_ready_bike(
            bike_type="MTB", grade="C", part_unit_cost_cents=2000, part_quantity=4
        )
        bike_now = validate_success(api_client.get_bike(bike["id"], COORD))
        assert bike_now["parts_cost_cents"] == 8000
        sale = validate_success(
            api_client.create_sale(
                {"bike_id": bike["id"], "buyer_name": "B M", "buyer_email": "bm@x.org"},
                COORD,
            ),
            expected_status=201,
        )
        # round(12000*0.4)=4800 + min(round(8000*0.5)=4000, 3000)=3000 -> 7800
        assert sale["quoted_price_cents"] == 7800

    def test_price_floor_binds_on_kids_c(self):
        """PRD §3.9: "Finally, the price is floored at 2000 cents — if the
        running total falls below the floor, the floor wins."

        Design: Difficulty/combinatorial_formula/sale_price_tiered_engine_mode_a
        """
        bike, _, _, _ = make_ready_bike(
            bike_type="KIDS", grade="C", part_unit_cost_cents=100, part_quantity=1,
            wheel_size_inches=20,
        )
        bike_now = validate_success(api_client.get_bike(bike["id"], COORD))
        assert bike_now["parts_cost_cents"] == 100
        sale = validate_success(
            api_client.create_sale(
                {"bike_id": bike["id"], "buyer_name": "B K", "buyer_email": "bk@x.org"},
                COORD,
            ),
            expected_status=201,
        )
        # round(4000*0.4)=1600 + round(100*0.5)=50 -> 1650 -> max(1650, 2000)
        assert sale["quoted_price_cents"] == 2000


class TestSaleRoundupOrderPinned:
    def _complete_with_roundup(self, bike):
        sale = validate_success(
            api_client.create_sale(
                {"bike_id": bike["id"], "buyer_name": "B", "buyer_email": "b@x.org"},
                COORD,
            ),
            expected_status=201,
        )
        hp = _helmet_stocked(5)
        _distribute_sale_helmet(hp["id"], sale["id"])
        return validate_success(
            api_client.complete_sale(
                sale["id"], {"payment_method": "CARD", "round_up": True}, COORD
            )
        )

    def test_roundup_below_exact_multiple(self):
        """PRD §3.9: "When true, the grand total is the smallest multiple of 500
        cents greater than or equal to the final price — an exact multiple
        yields a zero donation — and `donation_cents` is the difference between
        the grand total and the final price."

        Design: Difficulty/combinatorial_formula/sale_roundup_order_pinned_mode_c
        """
        bike, _, _, _ = make_ready_bike(
            bike_type="MTB", grade="C", part_unit_cost_cents=2000, part_quantity=4
        )
        completed = self._complete_with_roundup(bike)
        assert completed["final_price_cents"] == 7800
        assert completed["grand_total_cents"] == 8000
        assert completed["donation_cents"] == 200

    def test_roundup_exact_multiple_yields_zero_donation(self):
        """PRD §3.9: "When true, the grand total is the smallest multiple of 500
        cents greater than or equal to the final price — an exact multiple
        yields a zero donation — and `donation_cents` is the difference between
        the grand total and the final price."

        Design: Difficulty/combinatorial_formula/sale_roundup_order_pinned_mode_c
        """
        bike, _, _, _ = make_ready_bike(
            bike_type="CARGO", grade="C", part_unit_cost_cents=1300, part_quantity=2,
            wheel_size_inches=26,
        )
        completed = self._complete_with_roundup(bike)
        assert completed["final_price_cents"] == 8500
        assert completed["grand_total_cents"] == 8500
        assert completed["donation_cents"] == 0


class TestSalePricingCorners:
    def test_member_discount_applied_to_quote(self):
        """PRD §3.9: "Then the member discount: if the buyer's membership
        references an `ACTIVE` membership, ten percent of the running total,
        rounded half up, is subtracted; otherwise the discount is zero."

        Design: Corner/calculations/member_discount_applied_to_quote
        """
        bike, _, _, _ = make_ready_bike(
            bike_type="HYBRID", grade="A", part_unit_cost_cents=200, part_quantity=1
        )
        m = make_membership(member_name="M D", member_email="md@x.org",
                            tier="PRO", end_date="2026-12-31")
        sale = validate_success(
            api_client.create_sale(
                {
                    "bike_id": bike["id"],
                    "buyer_name": "B M",
                    "buyer_email": "bm@x.org",
                    "buyer_membership_id": m["id"],
                },
                COORD,
            ),
            expected_status=201,
        )
        # 9000 + round(200*0.5)=100 -> 9100; discount round(910) -> 8190
        assert sale["quoted_price_cents"] == 8190

    def test_surcharge_cap_boundary_trio(self):
        """PRD §3.9: "Next comes the parts surcharge: half of the bike's current
        `parts_cost_cents`, rounded half up, capped at 3000 cents."

        Design: Corner/calculations/surcharge_cap_boundary_trio
        """
        donor = make_donor(display_name="D CB", donor_type="INDIVIDUAL", email="dcb@x.org")
        cases = [
            (2999, 14999),  # 12000 + round(5998*0.5)=2999
            (3000, 15000),  # 12000 + min(3000, 3000)
            (3001, 15000),  # 12000 + min(round(6002*0.5)=3001, 3000)
        ]
        for unit_cost, expected_quote in cases:
            bike, _, _, _ = make_ready_bike(
                donor_id=donor["id"], bike_type="ROAD", grade="A",
                part_unit_cost_cents=unit_cost, part_quantity=2,
            )
            sale = validate_success(
                api_client.create_sale(
                    {"bike_id": bike["id"], "buyer_name": "B", "buyer_email": "b@x.org"},
                    COORD,
                ),
                expected_status=201,
            )
            assert sale["quoted_price_cents"] == expected_quote, (
                f"unit_cost {unit_cost} (x2) should quote {expected_quote}"
            )
