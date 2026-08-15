"""Guest musician contracts: quote rounding, negotiation cycles, terminal lockdown."""
from test_helpers import (
    ApiErrorId,
    activate_member,
    contract_in_state,
    counter_contract_payload,
    create_contract,
    create_contract_payload,
    create_open_season_with_section,
    make_president_headers,
    make_treasurer_headers,
    offer_contract,
    validate_error,
    validate_success,
)


class TestGuestFeeQuote:
    def test_guest_fee_per_line_rounding_order(self, api, director_headers):
        """PRD §3.7: "The quote's rounding order is pinned: each service line
        is rounded first — the line's `rate_cents` multiplied by its `units`,
        rounded half up to integer cents — and only then are the rounded line
        totals summed, with `travel_stipend_cents` added last. Summing the raw
        products and rounding once at the end is a different, non-conforming
        result."

        Design: Difficulty/combinatorial_formula/guest_fee_per_line_rounding_order
        """
        season, _section = create_open_season_with_section()
        contract = validate_success(api.create_contract(
            create_contract_payload(
                season["id"],
                musician_name="Fiddler",
                service_lines=[
                    {"kind": "REHEARSAL", "units": 1.5, "rate_cents": 10001},
                    {"kind": "MASTERCLASS", "units": 2.5, "rate_cents": 10001},
                ],
                travel_stipend_cents=0),
            director_headers), 201)
        # Per line: round_half_up(15001.5)=15002, round_half_up(25002.5)=25003
        # -> 40005. Sum-then-round would give 40004 and is non-conforming.
        assert contract["quoted_fee_cents"] == 40005
        assert contract["status"] == "DRAFT"

    def test_guest_fee_adds_travel_stipend_after_line_rounding(
            self, api, director_headers):
        """PRD §3.7: "each service line is rounded first — the line's
        `rate_cents` multiplied by its `units`, rounded half up to integer
        cents — and only then are the rounded line totals summed, with
        `travel_stipend_cents` added last."

        Design: Difficulty/combinatorial_formula/guest_fee_per_line_rounding_order
        """
        season, _section = create_open_season_with_section()
        contract = validate_success(api.create_contract(
            create_contract_payload(
                season["id"],
                service_lines=[
                    {"kind": "REHEARSAL", "units": 1.5, "rate_cents": 10001},
                ],
                travel_stipend_cents=777),
            director_headers), 201)
        # round_half_up(1.5 * 10001) = 15002; stipend added last: 15779.
        assert contract["quoted_fee_cents"] == 15779


class TestOfferCounterCycle:
    def test_guest_contract_offer_counter_cycle(self, api, director_headers):
        """PRD §3.7: "Offering moves `DRAFT` to `OFFERED`, and later also
        `COUNTERED` back to `OFFERED` with revised terms; either way the caller
        may supply fresh `service_lines` or `travel_stipend_cents`, the quote
        is recomputed, and the contract's `version` increments. Recording the
        musician's counter-offer moves `OFFERED` to `COUNTERED` and is the
        OCC-guarded step from §2.7: it requires
        `expected_guest_contract_version`, increments `counter_count` by one,
        replaces the `service_lines` and travel stipend with the countered
        terms, recomputes `quoted_fee_cents`, and increments `version`."

        Design: Difficulty/non_linear_state_machine/guest_contract_offer_counter_cycle
        """
        season, _section = create_open_season_with_section()
        contract = create_contract(
            season["id"],
            service_lines=[{"kind": "CONCERT", "units": 1,
                            "rate_cents": 30000}])
        offered = offer_contract(contract["id"])

        countered = validate_success(api.counter_contract(
            contract["id"],
            counter_contract_payload(
                offered["version"],
                service_lines=[{"kind": "CONCERT", "units": 1,
                                "rate_cents": 28000}]),
            director_headers))
        assert countered["status"] == "COUNTERED"
        assert countered["counter_count"] == 1
        assert countered["quoted_fee_cents"] == 28000

        # COUNTERED -> OFFERED keeps the countered terms when none supplied.
        reoffered = offer_contract(contract["id"])
        assert reoffered["status"] == "OFFERED"
        assert reoffered["quoted_fee_cents"] == 28000

        accepted = validate_success(api.accept_contract(contract["id"],
                                                        director_headers))
        assert accepted["status"] == "ACCEPTED"
        final = validate_success(api.get_contract(contract["id"],
                                                  director_headers))
        assert final["counter_count"] == 1
        assert final["quoted_fee_cents"] == 28000

    def test_guest_contract_multiple_counter_cycles(self, api,
                                                    director_headers):
        """PRD §3.7: "Recording the musician's counter-offer moves `OFFERED` to
        `COUNTERED` ... increments `counter_count` by one, replaces the
        `service_lines` and travel stipend with the countered terms, recomputes
        `quoted_fee_cents`, and increments `version`."
        PRD §3.7: "and later also `COUNTERED` back to `OFFERED` with revised
        terms"

        Design: Difficulty/non_linear_state_machine/guest_contract_offer_counter_cycle
        """
        season, _section = create_open_season_with_section()
        contract = create_contract(
            season["id"],
            service_lines=[{"kind": "CONCERT", "units": 1,
                            "rate_cents": 30000}])
        v = offer_contract(contract["id"])["version"]

        # Cycle 1: counter down to 28000.
        countered = validate_success(api.counter_contract(
            contract["id"],
            counter_contract_payload(
                v, service_lines=[{"kind": "CONCERT", "units": 1,
                                   "rate_cents": 28000}]),
            director_headers))
        assert countered["counter_count"] == 1

        # Back to OFFERED with fresh terms at 26000.
        reoffered = validate_success(api.offer_contract(
            contract["id"],
            {"service_lines": [{"kind": "CONCERT", "units": 1,
                                "rate_cents": 26000}]},
            director_headers))
        assert reoffered["status"] == "OFFERED"
        assert reoffered["quoted_fee_cents"] == 26000

        # Cycle 2: counter down to 24000.
        countered2 = validate_success(api.counter_contract(
            contract["id"],
            counter_contract_payload(
                reoffered["version"],
                service_lines=[{"kind": "CONCERT", "units": 1,
                                "rate_cents": 24000}]),
            director_headers))
        assert countered2["status"] == "COUNTERED"
        assert countered2["counter_count"] == 2, \
            "each counter-offer increments counter_count"
        assert countered2["quoted_fee_cents"] == 24000


class TestContractTerminalLockdown:
    def test_contract_decline_after_paid_rejected(self, api, director_headers):
        """PRD §3.7: "The musician's answer is recorded as acceptance —
        `OFFERED` to `ACCEPTED` — or as a decline, which moves `OFFERED` or
        `COUNTERED` to the terminal `DECLINED`." — `PAID` is not a from-state
        for decline.
        PRD §3.7: "`CANCELLED` is terminal alongside `DECLINED` and `PAID`."

        Design: Corner/state_machines/contract_decline_after_paid_rejected
        """
        season, section = create_open_season_with_section()
        activate_member(season["id"], section["id"])  # fund treasury: 18000
        contract = contract_in_state(
            season["id"], "PAID", rate_cents=10000,
            approver_headers=make_president_headers("pres-1"),
            payer_headers=make_treasurer_headers("treas-1"))
        assert contract["status"] == "PAID"

        resp = api.decline_contract(contract["id"], director_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        current = validate_success(api.get_contract(contract["id"],
                                                    director_headers))
        assert current["status"] == "PAID", "terminal PAID unchanged"
