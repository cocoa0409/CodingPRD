"""Private charters: cyclic negotiation, deterministic quotes, capacity tiers,
round caps, and the conversion cascade (PRD §3.9)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_inquiry,
    counter_inquiry,
    create_cruise,
    create_customer,
    create_inquiry,
    create_paid_booking,
    create_vessel,
    get_booking,
    get_cruise,
    get_inquiry,
    make_customer_headers,
    quote_inquiry,
    setup_accepted_inquiry,
    setup_inventory,
    validate_error,
    validate_success,
)

OM = TEST_USERS["ops_manager_headers"]
AGENT = TEST_USERS["charter_agent_headers"]


class TestCyclicNegotiation:
    def test_quote_counter_requote_cycle_returns_to_quoted(self, api):
        """PRD §3.9: "The customer counters a standing quote, moving the inquiry
        from `QUOTED` to `COUNTERED` and incrementing `quote_round`; the agent
        re-quotes a countered inquiry, moving it from `COUNTERED` back to
        `QUOTED`, recomputing `quoted_total_cents`, and incrementing
        `quote_round`."
        PRD §3.9: "The quoted amount is deterministic."

        Design: Difficulty/non_linear_state_machine/charter_inquiry_cyclic_negotiation_rounds
        """
        inv = setup_inventory(vessel_capacity=60)  # MEDIUM charter tier
        customer = create_customer("corp@example.com", "Corp")
        inquiry = create_inquiry(inv["cruise"]["id"], customer["id"])
        assert inquiry["status"] == "DRAFT"
        assert inquiry["quote_round"] == 0

        q1 = quote_inquiry(inquiry["id"], inquiry["version"])
        assert q1["status"] == "QUOTED"
        # MEDIUM base 620000 * 1.25 PEAK = 775000.
        assert q1["quoted_total_cents"] == 775000
        countered = counter_inquiry(inquiry["id"], customer["id"])
        assert countered["status"] == "COUNTERED"
        q2 = quote_inquiry(inquiry["id"], countered["version"])

        assert q2["status"] == "QUOTED", (
            f"After QUOTED->COUNTERED->QUOTED the inquiry must be QUOTED, got "
            f"{q2['status']}"
        )
        assert q2["quote_round"] == 3, (
            f"Three transitions must leave quote_round == 3, got "
            f"{q2['quote_round']}"
        )
        assert q2["quoted_total_cents"] == 775000, (
            f"Re-quote is deterministic at 775000, got {q2['quoted_total_cents']}"
        )

    def test_quote_and_counter_each_increment_round(self, api):
        """PRD §3.9: "it moves the inquiry to `QUOTED`, computing
        `quoted_total_cents` and incrementing `quote_round`"
        PRD §3.9: "The customer counters a standing quote, moving the inquiry
        from `QUOTED` to `COUNTERED` and incrementing `quote_round`"

        Design: Difficulty/non_linear_state_machine/charter_inquiry_cyclic_negotiation_rounds
        """
        inv = setup_inventory(vessel_capacity=60)
        customer = create_customer("corp@example.com", "Corp")
        inquiry = create_inquiry(inv["cruise"]["id"], customer["id"])
        q1 = quote_inquiry(inquiry["id"], inquiry["version"])
        assert q1["quote_round"] == 1
        c1 = counter_inquiry(inquiry["id"], customer["id"])
        assert c1["quote_round"] == 2
        q2 = quote_inquiry(inquiry["id"], c1["version"])
        assert q2["quote_round"] == 3


class TestCharterQuoteCapacityTiers:
    def test_tier_boundaries_forty_nine_fifty_one_hundred(self, api):
        """PRD §3.9: "The operating vessel's `coast_guard_capacity` selects a
        tier: forty-nine or fewer passengers is the small tier, fifty through
        ninety-nine is the medium tier, and one hundred or more is the large
        tier."
        PRD §3.9: "The tier's base price — 350,000 cents for small, 620,000
        cents for medium, 980,000 cents for large — is multiplied by the
        cruise's seasonal multiplier, the same 1.25-for-`PEAK`, 1.10-for-
        `SHOULDER`, 1.00-for-`OFF` ladder used in ticket pricing, and the
        product is rounded half-up to whole cents exactly once."

        Design: Corner/calculations/charter_quote_capacity_tier_boundaries
        """
        inv = setup_inventory()  # dock + tier; vessel 100 replaced below
        dock = inv["dock"]
        tier = inv["tier"]
        # OFF-season cruises isolate the tier base (multiplier 1.00).
        dates = {"49": "2026-01-15", "50": "2026-01-16", "100": "2026-01-17"}
        capacities = {"49": 49, "50": 50, "100": 100}
        expected = {"49": 350000, "50": 620000, "100": 980000}
        customer = create_customer("corp@example.com", "Corp")
        for label, capacity in capacities.items():
            vessel = create_vessel(dock["id"], capacity=capacity,
                                   name=f"V{label}")
            cruise = create_cruise(vessel["id"], tier["id"],
                                   depart_at=f"{dates[label]}T19:00:00Z",
                                   return_at=f"{dates[label]}T22:00:00Z")
            inquiry = create_inquiry(cruise["id"], customer["id"])
            quoted = quote_inquiry(inquiry["id"], inquiry["version"])
            assert quoted["quoted_total_cents"] == expected[label], (
                f"Capacity {capacity} must quote {expected[label]}, got "
                f"{quoted['quoted_total_cents']}"
            )


class TestQuoteRoundsExhausted:
    def test_seventh_round_rejected(self, api):
        """PRD §3.9: "Both the counter and the re-quote are capped: they require
        `quote_round` to still be below six rounds, failing with
        `ERR_QUOTE_ROUNDS_EXHAUSTED` once the negotiation has used them up; the
        opening quote from `DRAFT` does not consult the cap."

        Design: Corner/validations/quote_rounds_exhausted_rejected
        """
        inv = setup_inventory(vessel_capacity=60)
        customer = create_customer("corp@example.com", "Corp")
        inquiry = create_inquiry(inv["cruise"]["id"], customer["id"])
        current = quote_inquiry(inquiry["id"], inquiry["version"])  # round 1
        for _ in range(2):  # rounds 2-3 and 4-5
            current = counter_inquiry(inquiry["id"], customer["id"])
            current = quote_inquiry(inquiry["id"], current["version"])
        current = counter_inquiry(inquiry["id"], customer["id"])  # round 6
        assert current["quote_round"] == 6
        assert current["status"] == "COUNTERED"

        resp = api.quote_charter_inquiry(
            inquiry["id"], {"expected_inquiry_version": current["version"]},
            AGENT)
        validate_error(resp, ApiErrorId.ERR_QUOTE_ROUNDS_EXHAUSTED)


class TestCharterConversionCascade:
    def _setup_accepted_with_booking(self, api):
        """Vessel cap 60 (MEDIUM); cruise PEAK; booking A party4 PAID (total
        42275); inquiry QUOTED -> ACCEPTED. Returns context."""
        inv = setup_inventory(vessel_capacity=60)
        cruise = inv["cruise"]
        cust_a = create_customer("a@example.com", "A")
        booking = create_paid_booking(cruise["id"], cust_a["id"], 4,
                                      cruise["version"])
        cust_c = create_customer("corp@example.com", "Corp")
        inquiry = setup_accepted_inquiry(cruise["id"], cust_c["id"])
        return {**inv, "cust_a": cust_a, "booking": booking,
                "cust_c": cust_c, "inquiry": inquiry}

    def test_conversion_cascade_depth2(self, api):
        """PRD §3.9: "A successful conversion executes as one cascade: the
        server creates a new booking for the charter client with `booking_status`
        `CONFIRMED`, `payment_status` `PAID`, and `party_size` equal to the
        vessel's full `coast_guard_capacity`, and points the cruise's
        `charter_booking_id` at it; every pre-existing booking of the cruise
        standing at `RESERVED` or `CONFIRMED` moves to `CONVERTED_TO_CHARTER`,
        and when such a booking had been `PAID` its `payment_status` moves to
        `CREDITED` with a conversion CruiseCredit issued in `ISSUED` status for
        the booking's frozen `booking_total_cents` less a twelve-percent
        conversion fee — that is, eighty-eight percent of the frozen total, in
        integer cents under the system-wide rounding rule; and the cruise's
        `reserved_covers` is recomputed, reading exactly the certified capacity."

        Design: Difficulty/transitive_cascade/charter_conversion_cascade_depth2
        """
        ctx = self._setup_accepted_with_booking(api)
        converted = validate_success(
            api.convert_charter_inquiry(ctx["inquiry"]["id"], OM))
        assert converted["status"] == "CONVERTED"

        # Hop 1: the pre-existing booking flips on both axes.
        booking = get_booking(ctx["booking"]["id"])
        assert booking["booking_status"] == "CONVERTED_TO_CHARTER"
        assert booking["payment_status"] == "CREDITED"
        # Hop 2: the booking's own transition issues the conversion credit.
        credits = validate_success(
            api.list_booking_credits(ctx["booking"]["id"], OM))
        assert len(credits) == 1
        # round_half_up(42275 * 0.88) = 37202.
        assert credits[0]["credit_status"] == "ISSUED"
        assert credits[0]["amount_cents"] == 37202, (
            f"Conversion credit must be 37202 (88% of 42275), got "
            f"{credits[0]['amount_cents']}"
        )
        # The cruise points at the system-created charter booking and reads
        # exactly the certified capacity.
        cruise = get_cruise(ctx["cruise"]["id"])
        assert cruise["charter_booking_id"] is not None
        assert cruise["reserved_covers"] == 60, (
            f"reserved_covers must read exactly the capacity 60, got "
            f"{cruise['reserved_covers']}"
        )
        charter_booking = get_booking(cruise["charter_booking_id"])
        assert charter_booking["booking_status"] == "CONFIRMED"
        assert charter_booking["payment_status"] == "PAID"
        assert charter_booking["party_size"] == 60

    def test_conversion_credit_flows_into_customer_balance(self, api):
        """PRD §3.8: "A customer's `credit_balance_cents` is the sum over their
        credits of the `amount_cents` while a credit stands at `ISSUED`, the
        `final_amount_cents` while it stands at `SETTLED`, and zero once it
        stands at `REDEEMED` or `EXPIRED`."

        Design: Difficulty/transitive_cascade/charter_conversion_cascade_depth2
        """
        ctx = self._setup_accepted_with_booking(api)
        validate_success(api.convert_charter_inquiry(ctx["inquiry"]["id"], OM))
        customer = validate_success(api.get_customer(ctx["cust_a"]["id"], OM))
        assert customer["credit_balance_cents"] == 37202, (
            f"ISSUED conversion credit must count at amount_cents, got "
            f"{customer['credit_balance_cents']}"
        )


class TestInquiryTerminalStates:
    def test_declined_inquiry_rejects_further_quote(self, api):
        """PRD §3.9: "The customer may instead decline from either `QUOTED` or
        `COUNTERED`, moving the inquiry to `DECLINED`. Left unanswered, a quote
        standing at `QUOTED` lapses automatically to `EXPIRED` once the logical
        clock passes forty-eight hours after the quote was posted; `DECLINED`,
        `EXPIRED`, and `CONVERTED` are all terminal."

        Design: Corner/state_machines/inquiry_declined_terminal_lockdown
        """
        inv = setup_inventory(vessel_capacity=60)
        customer = create_customer("corp@example.com", "Corp")
        inquiry = create_inquiry(inv["cruise"]["id"], customer["id"])
        quote_inquiry(inquiry["id"], inquiry["version"])
        declined = validate_success(api.decline_charter_inquiry(
            inquiry["id"], make_customer_headers(customer["id"])))
        assert declined["status"] == "DECLINED"

        current = get_inquiry(inquiry["id"])
        resp = api.quote_charter_inquiry(
            inquiry["id"], {"expected_inquiry_version": current["version"]},
            AGENT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestCharterRbacSegregation:
    def test_charter_sales_agent_cannot_convert(self, api):
        """PRD §2.1: "`CharterSalesAgent` owns the charter pipeline — opening
        inquiries and posting quotes — and never converts a charter, by
        segregation of duties."
        PRD §2.1: "An attempt to perform an operation outside the roles
        authorized for it in §4 is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."

        Design: Corner/rbac/charter_sales_agent_cannot_convert
        """
        inv = setup_inventory(vessel_capacity=60)
        customer = create_customer("corp@example.com", "Corp")
        inquiry = setup_accepted_inquiry(inv["cruise"]["id"], customer["id"])
        assert inquiry["status"] == "ACCEPTED"
        resp = api.convert_charter_inquiry(inquiry["id"], AGENT)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
