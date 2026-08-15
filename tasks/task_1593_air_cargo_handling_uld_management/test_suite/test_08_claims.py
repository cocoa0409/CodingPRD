"""Damage and loss claims: gating, settlement calculation, and lifecycle."""
from test_helpers import (
    ApiErrorId,
    approve_claim,
    create_claim_payload,
    file_claim,
    get_claim,
    make_accepted_booking,
    make_open_flight,
    settle_claim,
    setup_departed_scenario,
    setup_two_loaded_bookings,
    assert_money,
    validate_error,
    validate_success,
)


class TestClaimFilingGate:
    def test_claim_rejected_while_booking_accepted(
        self, api, forwarder_agent_headers
    ):
        """PRD §3.9: "Filing requires the booking to be `LOADED` — cargo still
        in the pipeline draws `ERR_BOOKING_INVALID_STATE`"

        Design: Difficulty/cross_entity_state_dependency/claim_requires_booking_loaded
        """
        flight = make_open_flight(flight_number="CA216")
        booking = make_accepted_booking(
            flight["id"], shipper_ref="SHP-X2", gross_weight_kg=100, volume_m3=1
        )
        res = api.create_claim(
            create_claim_payload(
                booking["id"], claim_type="LOSS", claimed_amount=50,
                items=[{"weight_kg": 1}],
            ),
            forwarder_agent_headers,
        )
        validate_error(res, ApiErrorId.ERR_BOOKING_INVALID_STATE)

    def test_claim_accepted_after_booking_loaded(self, api, forwarder_agent_headers):
        """PRD §3.9: "Filing requires the booking to be `LOADED` — cargo still
        in the pipeline draws `ERR_BOOKING_INVALID_STATE`"
        PRD §3.9: "A new claim starts `SUBMITTED`, with `item_total`, `basis`,
        `approved_amount`, and `settlement_ref` all unset until adjudication."

        Design: Difficulty/cross_entity_state_dependency/claim_requires_booking_loaded
        """
        scenario = setup_departed_scenario(
            flight_overrides={"flight_number": "CA216"},
            booking_overrides={"shipper_ref": "SHP-X2"},
            uld_code="AKE00012CA",
        )
        assert scenario["booking"]["status"] == "LOADED"
        claim = validate_success(
            api.create_claim(
                create_claim_payload(
                    scenario["booking"]["id"], claim_type="LOSS",
                    claimed_amount=50, items=[{"weight_kg": 1}],
                ),
                forwarder_agent_headers,
            ),
            201,
        )
        assert claim["status"] == "SUBMITTED"


class TestSettlementBasisVariants:
    def test_claim_liability_basis_without_declared_value(
        self, api, claims_adjuster_headers
    ):
        """PRD §3.9: "when the booking carries no `declared_value`, the basis
        is `LIABILITY` and the cap is the booking's `chargeable_weight_kg`
        multiplied by the same 19.00 per-kilogram rate, rounded half-up to two
        decimal places"
        PRD §3.9: "The `approved_amount` is the smallest of the three figures —
        `claimed_amount`, `item_total`, and the applicable cap — rounded
        half-up to two decimal places"

        Design: Difficulty/dual_variant_calc/claim_liability_vs_declared_value_basis
        """
        scenario = setup_two_loaded_bookings()
        claim = file_claim(
            scenario["booking_a"]["id"],
            claim_type="DAMAGE", claimed_amount=10000,
            items=[{"weight_kg": 600}],
        )
        approved = approve_claim(claim["id"])
        assert approved["basis"] == "LIABILITY"
        # item_total = 600*19.00 = 11400.00; cap = chargeable 100.00 * 19.00
        # = 1900.00; approved = min(10000, 11400.00, 1900.00)
        assert_money(approved["approved_amount"], 1900.00)

    def test_claim_declared_value_basis(self, api, claims_adjuster_headers):
        """PRD §3.9: "when the booking does carry a `declared_value`, the basis
        is `DECLARED_VALUE` and the cap is that declared value itself, with
        weight playing no role in the cap."
        PRD §3.9: "The `approved_amount` is the smallest of the three figures —
        `claimed_amount`, `item_total`, and the applicable cap — rounded
        half-up to two decimal places"

        Design: Difficulty/dual_variant_calc/claim_liability_vs_declared_value_basis
        """
        scenario = setup_two_loaded_bookings(declared_value_b=8000)
        claim = file_claim(
            scenario["booking_b"]["id"],
            claim_type="DAMAGE", claimed_amount=10000,
            items=[{"weight_kg": 600}],
        )
        approved = approve_claim(claim["id"])
        assert approved["basis"] == "DECLARED_VALUE"
        # item_total = 11400.00; cap = declared_value 8000
        # approved = min(10000, 11400.00, 8000)
        assert_money(approved["approved_amount"], 8000.00)


class TestPerItemRoundingOrder:
    def test_claim_item_total_per_item_rounding(self, api, claims_adjuster_headers):
        """PRD §3.9: "The claim's `item_total` is computed by multiplying each
        item's `weight_kg` by the liability rate of 19.00 per kilogram,
        rounding each per-item product half-up to two decimal places first, and
        only then summing the rounded per-item amounts — this pinned order,
        per-item rounding strictly before summation, is part of the contract."

        Design: Difficulty/combinatorial_formula/claim_per_item_rounding_order
        """
        scenario = setup_departed_scenario(
            flight_overrides={"flight_number": "CA204"},
            booking_overrides={
                "shipper_ref": "SHP-R1", "pieces": 3,
                "gross_weight_kg": 100, "volume_m3": 0.1,
            },
            uld_code="AKE00004CA",
        )
        claim = file_claim(
            scenario["booking"]["id"],
            claim_type="DAMAGE", claimed_amount=1000,
            items=[{"weight_kg": 0.335}, {"weight_kg": 0.335}, {"weight_kg": 0.335}],
        )
        approved = approve_claim(claim["id"])
        assert approved["basis"] == "LIABILITY"
        # 3 x round_half_up(0.335 * 19.00, 2) = 3 x 6.37 = 19.11; a
        # sum-then-round implementation would produce 19.10 and fail.
        assert_money(approved["item_total"], 19.11)

    def test_claim_approved_amount_uses_rounded_item_total(
        self, api, claims_adjuster_headers
    ):
        """PRD §3.9: "rounding each per-item product half-up to two decimal
        places first, and only then summing the rounded per-item amounts"
        PRD §3.9: "The `approved_amount` is the smallest of the three figures —
        `claimed_amount`, `item_total`, and the applicable cap — rounded
        half-up to two decimal places"

        Design: Difficulty/combinatorial_formula/claim_per_item_rounding_order
        """
        scenario = setup_departed_scenario(
            flight_overrides={"flight_number": "CA204"},
            booking_overrides={
                "shipper_ref": "SHP-R1", "pieces": 3,
                "gross_weight_kg": 100, "volume_m3": 0.1,
            },
            uld_code="AKE00004CA",
        )
        claim = file_claim(
            scenario["booking"]["id"],
            claim_type="DAMAGE", claimed_amount=1000,
            items=[{"weight_kg": 0.335}, {"weight_kg": 0.335}, {"weight_kg": 0.335}],
        )
        approved = approve_claim(claim["id"])
        # min(1000, 19.11, 1900.00) — item_total is the binding term
        assert_money(approved["approved_amount"], 19.11)


class TestClaimAmountCapping:
    def test_claim_approved_amount_capped_by_claimed(
        self, api, claims_adjuster_headers
    ):
        """PRD §3.9: "The `approved_amount` is the smallest of the three
        figures — `claimed_amount`, `item_total`, and the applicable cap —
        rounded half-up to two decimal places, and approval moves the claim to
        `APPROVED` with all three computed fields stored."

        Design: Corner/calculations/claim_approved_amount_capped_by_claimed
        """
        scenario = setup_departed_scenario(
            flight_overrides={"flight_number": "CA317", "max_payload_kg": 5000},
            booking_overrides={"shipper_ref": "SHP-CC"},
            uld_code="AKE00108CA",
        )
        claim = file_claim(
            scenario["booking"]["id"],
            claim_type="DAMAGE", claimed_amount=10, items=[{"weight_kg": 1}],
        )
        approved = approve_claim(claim["id"])
        # item_total = 1*19.00 = 19.00; liability cap = 100*19.00 = 1900.00;
        # approved = min(10, 19.00, 1900.00)
        assert_money(approved["item_total"], 19.00)
        assert_money(approved["approved_amount"], 10.00)
        assert approved["status"] == "APPROVED"


class TestClaimLifecycleGuards:
    def test_settle_submitted_claim_rejected(self, api, claims_adjuster_headers):
        """PRD §3.9: "An approved claim is closed out by settlement, which
        requires the claim to be `APPROVED` (`ERR_CLAIM_NOT_APPROVED`
        otherwise) and records the payment's `settlement_ref` on the claim as
        it moves to `SETTLED`."

        Design: Corner/errors/settle_submitted_claim_rejected
        """
        scenario = setup_departed_scenario(
            flight_overrides={"flight_number": "CA338", "max_payload_kg": 5000},
            booking_overrides={"shipper_ref": "SHP-ST"},
            uld_code="AKE00121CA",
        )
        claim = file_claim(
            scenario["booking"]["id"],
            claim_type="LOSS", claimed_amount=500, items=[{"weight_kg": 5}],
        )
        res = api.settle_claim(
            claim["id"], {"settlement_ref": "PAY-2002"}, claims_adjuster_headers
        )
        validate_error(res, ApiErrorId.ERR_CLAIM_NOT_APPROVED)

    def test_settled_claim_terminal_lockdown(self, api, claims_adjuster_headers):
        """PRD §3.9: "Approval requires the claim to be `SUBMITTED`
        (`ERR_CLAIM_NOT_SUBMITTED`) and runs the settlement calculation in
        full."
        PRD §3.9: "An approved claim is closed out by settlement, which
        requires the claim to be `APPROVED` (`ERR_CLAIM_NOT_APPROVED`
        otherwise) and records the payment's `settlement_ref` on the claim as
        it moves to `SETTLED`."

        Design: Corner/state_machines/settled_claim_terminal_lockdown
        """
        scenario = setup_departed_scenario(
            flight_overrides={"flight_number": "CA312", "max_payload_kg": 5000},
            booking_overrides={"shipper_ref": "SHP-T1"},
            uld_code="AKE00106CA",
        )
        claim = file_claim(
            scenario["booking"]["id"],
            claim_type="DAMAGE", claimed_amount=100, items=[{"weight_kg": 2}],
        )
        approve_claim(claim["id"])
        settled = settle_claim(claim["id"], settlement_ref="PAY-1001")
        assert settled["status"] == "SETTLED"
        res = api.approve_claim(claim["id"], claims_adjuster_headers)
        validate_error(res, ApiErrorId.ERR_CLAIM_NOT_SUBMITTED)
        assert get_claim(claim["id"])["status"] == "SETTLED", (
            "SETTLED is terminal: a late approval must not mutate the claim"
        )
