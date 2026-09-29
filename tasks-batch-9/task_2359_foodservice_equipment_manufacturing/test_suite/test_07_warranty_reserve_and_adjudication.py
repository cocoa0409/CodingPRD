"""Warranty payout arithmetic, the reserve ledger and the approval / reversal compensation."""

import pytest

from test_helpers import (
    ApiErrorId,
    adjudicate_claim,
    coverage_action_payload,
    file_warranty_claim,
    read_connected_unit,
    read_warranty_claim,
    reversal_payload,
    setup_reserve_utilisation,
    setup_warranty_environment,
    validate_error,
    validate_success,
)

BASE_RESERVE_CENTS = 250000


def _file(state, claim_code, parts_cost_cents, labor_hours, certification_index=1):
    """File one further claim on the environment's unit through the authorised partner."""
    return file_warranty_claim(
        state["unit"]["id"],
        state["partner"]["id"],
        state["certifications"][certification_index]["id"],
        claim_code,
        parts_cost_cents,
        labor_hours,
    )


class TestCoinsuranceBandIsReadPreClaim:
    def test_second_claim_is_withheld_at_the_band_the_ledger_held_before_it(self):
        """A first payout of 150000 on a 250000 reserve puts the next claim in the 0.10 band.

        PRD §3.9: "Measure utilisation on the **pre-claim** ledger: the unit's
        `claims_paid_cents` divided by its `reserve_initial_cents`, both as they stand
        immediately before this adjudication. Claims in `SUBMITTED`, `DENIED` or
        `REVERSED` contribute nothing to `claims_paid_cents`."

        Design: Difficulty/combinatorial_formula/warranty_coinsurance_band_read_from_pre_claim_utilization_only
        """
        state = setup_reserve_utilisation()

        first = state["first_claim"]
        assert first["coinsurance_pct"] == pytest.approx(0.00, abs=0.001), (
            "the first claim meets a utilisation of zero, which is below the sixty "
            f"percent band floor, so nothing is withheld, got {first['coinsurance_pct']}"
        )
        assert first["adjudicated_amount_cents"] == 150000, (
            "parts 123000 plus three hours at the BASE rate of 9000 is a gross of "
            f"150000 and nothing is withheld, got {first['adjudicated_amount_cents']}"
        )

        unit_before = read_connected_unit(state["unit"]["id"])
        assert unit_before["reserve_balance_cents"] == 100000, (
            "the first payout leaves 100000 of the 250000 reserve, got "
            f"{unit_before['reserve_balance_cents']}"
        )
        assert unit_before["claims_paid_cents"] == 150000, (
            f"the first payout is the only money paid so far, got "
            f"{unit_before['claims_paid_cents']}"
        )

        second = adjudicate_claim(
            _file(state, "CLM-2", 40000, 3.0)["id"], "APPROVE"
        )

        assert second["coinsurance_pct"] == pytest.approx(0.10, abs=0.001), (
            "the pre-claim utilisation is exactly 150000 over 250000, which is 0.60 and "
            f"lands inclusively in the ten percent band, got {second['coinsurance_pct']}"
        )
        assert second["adjudicated_amount_cents"] == 60300, (
            "the gross is 40000 parts plus 27000 labour, which is 67000, and ten "
            f"percent withheld gives 60300, got {second['adjudicated_amount_cents']}"
        )
        assert second["adjudicated_amount_cents"] != 50250, (
            "50250 is what a post-claim utilisation of 0.868 and its twenty-five "
            "percent band would pay, and the band is not read after the claim"
        )

        unit_after = read_connected_unit(state["unit"]["id"])
        assert unit_after["reserve_balance_cents"] == 39700, (
            "100000 less the 60300 payout leaves 39700, got "
            f"{unit_after['reserve_balance_cents']}"
        )
        assert unit_after["claims_paid_cents"] == 210300, (
            "150000 plus 60300 is 210300 paid, got "
            f"{unit_after['claims_paid_cents']}"
        )
        assert unit_after["service_program_status"] == "ACTIVE", (
            "the reserve is not exhausted, so coverage stays ACTIVE, got "
            f"{unit_after['service_program_status']}"
        )

    def test_a_claim_large_enough_to_move_the_band_itself_is_still_priced_at_zero(self):
        """A single 207000 claim on an untouched reserve is withheld at 0.00, not 0.10.

        PRD §3.9: "Select `coinsurance_pct` from that utilisation, with the band lower
        bounds inclusive: below sixty percent utilisation the partner bears nothing and
        the fraction is `0.00`; from sixty percent up to but not including eighty-five
        percent the fraction is `0.10`; at eighty-five percent utilisation or above it is
        `0.25`. A utilisation of exactly `0.60` therefore lands in the ten-percent band,
        and exactly `0.85` in the twenty-five-percent band."

        Design: Difficulty/combinatorial_formula/warranty_coinsurance_band_read_from_pre_claim_utilization_only
        """
        state = setup_warranty_environment()
        unit_before = read_connected_unit(state["unit"]["id"])
        assert unit_before["claims_paid_cents"] == 0, (
            f"the unit starts with nothing paid, got {unit_before['claims_paid_cents']}"
        )
        assert unit_before["reserve_initial_cents"] == BASE_RESERVE_CENTS, (
            "a BASE unit is activated with a 250000 reserve, got "
            f"{unit_before['reserve_initial_cents']}"
        )

        claim = adjudicate_claim(_file(state, "CLM-BIG", 180000, 3.0)["id"], "APPROVE")

        assert claim["coinsurance_pct"] == pytest.approx(0.00, abs=0.001), (
            "utilisation immediately before this adjudication is zero, so the band is "
            f"the zero one however large the claim is, got {claim['coinsurance_pct']}"
        )
        assert claim["adjudicated_amount_cents"] == 207000, (
            "180000 capped parts plus three hours at 9000 is 207000 and nothing is "
            f"withheld, got {claim['adjudicated_amount_cents']}"
        )
        assert claim["adjudicated_amount_cents"] != 186300, (
            "186300 is the ten percent band applied to the same gross, which is what a "
            "post-claim utilisation of 0.828 would have selected"
        )

        unit_after = read_connected_unit(state["unit"]["id"])
        assert unit_after["reserve_balance_cents"] == 43000, (
            "250000 less 207000 leaves 43000, got "
            f"{unit_after['reserve_balance_cents']}"
        )
        assert unit_after["claims_paid_cents"] == 207000, (
            f"the whole payout is booked as paid, got {unit_after['claims_paid_cents']}"
        )


class TestApprovalCascadeIntoGrace:
    def test_a_payout_that_exactly_exhausts_the_reserve_flips_coverage_into_grace(self):
        """CLM-3 pays exactly 100000, zeroing the reserve and stamping a 30 day grace window.

        PRD §3.9: "Hop three, caused by hop two, applies when the reserve has been driven
        exactly to zero: the unit moves `ACTIVE → GRACE` or `EXTENDED → GRACE` and
        `grace_expires_on` is set to the current clock plus a thirty-day grace window,
        during which the unit is still nominally covered but has no money behind it."

        Design: Difficulty/transitive_cascade/claim_approval_cascades_through_reserve_ledger_into_coverage_grace
        """
        state = setup_reserve_utilisation()
        assert state["first_claim"]["adjudicated_amount_cents"] == 150000, (
            "the seeding claim pays 150000, got "
            f"{state['first_claim']['adjudicated_amount_cents']}"
        )

        exhausting = adjudicate_claim(
            _file(state, "CLM-3", 93111, 2.0)["id"], "APPROVE"
        )

        assert exhausting["coinsurance_pct"] == pytest.approx(0.10, abs=0.001), (
            "a pre-claim utilisation of 0.60 selects the ten percent band, got "
            f"{exhausting['coinsurance_pct']}"
        )
        assert exhausting["adjudicated_amount_cents"] == 100000, (
            "93111 parts plus two hours at 9000 is a gross of 111111, and 11111 "
            "withheld half up leaves exactly the 100000 still in the reserve, got "
            f"{exhausting['adjudicated_amount_cents']}"
        )
        assert exhausting["status"] == "APPROVED", (
            "a payout equal to the balance is payable, got "
            f"{exhausting['status']}"
        )

        unit = read_connected_unit(state["unit"]["id"])
        assert unit["reserve_balance_cents"] == 0, (
            f"the second payout empties the reserve, got {unit['reserve_balance_cents']}"
        )
        assert unit["claims_paid_cents"] == 250000, (
            "150000 plus 100000 is the whole initial reserve, got "
            f"{unit['claims_paid_cents']}"
        )
        assert unit["service_program_status"] == "GRACE", (
            "driving the reserve exactly to zero flips coverage into GRACE, got "
            f"{unit['service_program_status']}"
        )
        assert unit["grace_expires_on"] is not None, (
            "the grace transition stamps an expiry, got null"
        )
        assert unit["grace_expires_on"].startswith("2026-08-31T00:00:00"), (
            "the clock stands at 2026-08-01T00:00:00Z, so the thirty day window closes "
            f"on 2026-08-31T00:00:00Z, got {unit['grace_expires_on']}"
        )

    def test_a_payout_one_cent_short_of_the_balance_leaves_coverage_active(self):
        """A 99999 payout against a 100000 balance keeps the unit ACTIVE with no grace stamp.

        PRD §3.9: "Hop two, caused by hop one, subtracts `adjudicated_amount_cents` from
        the unit's `reserve_balance_cents` and adds the same amount to its
        `claims_paid_cents`, preserving the reserve identity."

        Design: Difficulty/transitive_cascade/claim_approval_cascades_through_reserve_ledger_into_coverage_grace
        """
        state = setup_reserve_utilisation()

        nearly = adjudicate_claim(_file(state, "CLM-4", 93110, 2.0)["id"], "APPROVE")

        assert nearly["coinsurance_pct"] == pytest.approx(0.10, abs=0.001), (
            "the pre-claim utilisation is still 0.60, got "
            f"{nearly['coinsurance_pct']}"
        )
        assert nearly["adjudicated_amount_cents"] == 99999, (
            "93110 parts plus 18000 labour is a gross of 111110, and 11111 withheld "
            f"leaves 99999, got {nearly['adjudicated_amount_cents']}"
        )

        unit = read_connected_unit(state["unit"]["id"])
        assert unit["reserve_balance_cents"] == 1, (
            "one cent of the reserve survives the payout, got "
            f"{unit['reserve_balance_cents']}"
        )
        assert unit["claims_paid_cents"] == 249999, (
            f"150000 plus 99999 is 249999 paid, got {unit['claims_paid_cents']}"
        )
        assert unit["service_program_status"] == "ACTIVE", (
            "the grace hop fires only when the reserve is driven exactly to zero, so a "
            f"one cent remainder keeps the unit ACTIVE, got "
            f"{unit['service_program_status']}"
        )
        assert unit["grace_expires_on"] is None, (
            "no grace window is opened while the unit stays ACTIVE, got "
            f"{unit['grace_expires_on']}"
        )
        assert (
            unit["reserve_balance_cents"] + unit["claims_paid_cents"]
            == unit["reserve_initial_cents"]
        ), (
            "balance plus paid must still equal the initial reserve, got "
            f"{unit['reserve_balance_cents']} plus {unit['claims_paid_cents']} against "
            f"{unit['reserve_initial_cents']}"
        )


class TestReserveLedgerConservation:
    def test_reversing_the_exhausting_claim_restores_the_ledger_and_the_coverage_state(
        self, api, warranty_adjudicator
    ):
        """Reversal returns 100000 to the reserve, drops paid to 150000 and undoes GRACE.

        PRD §3.9: "Reversal takes the claim `APPROVED → REVERSED`, which is terminal,
        adds `adjudicated_amount_cents` back to the unit's `reserve_balance_cents` and
        subtracts the same amount from `claims_paid_cents`, leaving
        `reserve_balance_cents` plus `claims_paid_cents` equal to `reserve_initial_cents`
        with no drift."

        Design: Difficulty/compensating_invariant/warranty_reserve_ledger_conserves_total_across_claim_approval_and_reversal
        """
        state = setup_reserve_utilisation()
        exhausting = adjudicate_claim(
            _file(state, "CLM-3", 93111, 2.0)["id"], "APPROVE"
        )

        before = read_connected_unit(state["unit"]["id"])
        assert before["reserve_initial_cents"] == BASE_RESERVE_CENTS, (
            "the initial reserve is untouched by payouts, got "
            f"{before['reserve_initial_cents']}"
        )
        assert before["reserve_balance_cents"] == 0, (
            f"the reserve is exhausted before the reversal, got "
            f"{before['reserve_balance_cents']}"
        )
        assert before["claims_paid_cents"] == 250000, (
            f"both payouts are booked, got {before['claims_paid_cents']}"
        )
        assert before["service_program_status"] == "GRACE", (
            f"the exhausting payout put the unit in GRACE, got "
            f"{before['service_program_status']}"
        )
        assert before["grace_expires_on"].startswith("2026-08-31T00:00:00"), (
            f"the grace window closes on 2026-08-31T00:00:00Z, got "
            f"{before['grace_expires_on']}"
        )

        reversed_claim = validate_success(
            api.reverse_warranty_claim(
                exhausting["id"],
                reversal_payload("parts invoice was billed to the wrong serial"),
                warranty_adjudicator,
            )
        )
        assert reversed_claim["status"] == "REVERSED", (
            f"the reversal moves the claim to REVERSED, got {reversed_claim['status']}"
        )

        after = read_connected_unit(state["unit"]["id"])
        assert after["reserve_balance_cents"] == 100000, (
            "the reversed 100000 goes straight back into the reserve, got "
            f"{after['reserve_balance_cents']}"
        )
        assert after["claims_paid_cents"] == 150000, (
            "only the untouched first claim is still paid, got "
            f"{after['claims_paid_cents']}"
        )
        assert (
            after["reserve_balance_cents"] + after["claims_paid_cents"]
            == BASE_RESERVE_CENTS
        ), (
            "balance plus paid must return to the 250000 initial reserve with no drift, "
            f"got {after['reserve_balance_cents']} plus {after['claims_paid_cents']}"
        )
        assert after["service_program_status"] == "ACTIVE", (
            "the reversal undoes the grace transition its own claim caused, got "
            f"{after['service_program_status']}"
        )
        assert after["grace_expires_on"] is None, (
            f"returning to ACTIVE clears the grace expiry, got "
            f"{after['grace_expires_on']}"
        )

        untouched = read_warranty_claim(state["first_claim"]["id"])
        assert untouched["status"] == "APPROVED", (
            f"the earlier claim is not disturbed, got {untouched['status']}"
        )
        assert untouched["adjudicated_amount_cents"] == 150000, (
            f"the earlier claim keeps its own payout, got "
            f"{untouched['adjudicated_amount_cents']}"
        )

    def test_reversing_a_claim_that_did_not_cause_grace_conserves_the_total_but_keeps_grace(
        self, api, warranty_adjudicator
    ):
        """Reversing CLM-1 restores 150000 yet leaves the unit in GRACE, and REVERSED is terminal.

        PRD §3.9: "If the unit had been pushed into `GRACE` by the very claim now being
        reversed, and the restored `reserve_balance_cents` is greater than zero while the
        clock is still strictly before `grace_expires_on`, the unit returns
        `GRACE → ACTIVE` and `grace_expires_on` is cleared to null."

        Design: Difficulty/compensating_invariant/warranty_reserve_ledger_conserves_total_across_claim_approval_and_reversal
        """
        state = setup_reserve_utilisation()
        adjudicate_claim(_file(state, "CLM-3", 93111, 2.0)["id"], "APPROVE")
        first_claim_id = state["first_claim"]["id"]

        reversed_first = validate_success(
            api.reverse_warranty_claim(
                first_claim_id,
                reversal_payload("the first invoice was raised against the wrong unit"),
                warranty_adjudicator,
            )
        )
        assert reversed_first["status"] == "REVERSED", (
            f"the first claim is now REVERSED, got {reversed_first['status']}"
        )

        unit = read_connected_unit(state["unit"]["id"])
        assert unit["reserve_balance_cents"] == 150000, (
            "the reversed 150000 is added back to a zero balance, got "
            f"{unit['reserve_balance_cents']}"
        )
        assert unit["claims_paid_cents"] == 100000, (
            "only the exhausting claim's payout is still booked, got "
            f"{unit['claims_paid_cents']}"
        )
        assert (
            unit["reserve_balance_cents"] + unit["claims_paid_cents"]
            == unit["reserve_initial_cents"]
        ), (
            "the two ledger columns still sum to the initial reserve, got "
            f"{unit['reserve_balance_cents']} plus {unit['claims_paid_cents']} against "
            f"{unit['reserve_initial_cents']}"
        )
        assert unit["service_program_status"] == "GRACE", (
            "the grace state was caused by the other claim, so this reversal does not "
            f"undo it, got {unit['service_program_status']}"
        )
        assert unit["grace_expires_on"].startswith("2026-08-31T00:00:00"), (
            "the grace expiry survives a reversal of a claim that did not cause it, got "
            f"{unit['grace_expires_on']}"
        )

        replay = api.reverse_warranty_claim(
            first_claim_id,
            reversal_payload("a second attempt at the same correction"),
            warranty_adjudicator,
        )
        validate_error(replay, ApiErrorId.ERR_CLAIM_STATE_INVALID.value)

        unchanged = read_connected_unit(state["unit"]["id"])
        assert unchanged["reserve_balance_cents"] == 150000, (
            "the refused second reversal must not credit the reserve twice, got "
            f"{unchanged['reserve_balance_cents']}"
        )
        assert unchanged["claims_paid_cents"] == 100000, (
            f"nor may it debit claims_paid_cents twice, got "
            f"{unchanged['claims_paid_cents']}"
        )


class TestBandUpperBoundary:
    def test_utilization_of_exactly_eighty_five_percent_selects_the_quarter_band(self):
        """A 212500 first payout leaves utilisation at 0.85, so the next claim pays 21750.

        PRD §3.9: "Select `coinsurance_pct` from that utilisation, with the band lower
        bounds inclusive: below sixty percent utilisation the partner bears nothing and
        the fraction is `0.00`; from sixty percent up to but not including eighty-five
        percent the fraction is `0.10`; at eighty-five percent utilisation or above it is
        `0.25`. A utilisation of exactly `0.60` therefore lands in the ten-percent band,
        and exactly `0.85` in the twenty-five-percent band."

        Design: Corner/calculations/coinsurance_band_upper_boundary_at_exactly_eighty_five_percent_utilization
        """
        state = setup_reserve_utilisation(parts_cost_cents=176500, labor_hours=4.0)

        first = state["first_claim"]
        assert first["coinsurance_pct"] == pytest.approx(0.00, abs=0.001), (
            f"the opening claim meets a zero utilisation, got {first['coinsurance_pct']}"
        )
        assert first["adjudicated_amount_cents"] == 212500, (
            "176500 parts plus four hours at 9000 is 212500 and nothing is withheld, "
            f"got {first['adjudicated_amount_cents']}"
        )

        seeded = read_connected_unit(state["unit"]["id"])
        assert seeded["reserve_initial_cents"] == BASE_RESERVE_CENTS, (
            f"a BASE unit reserves 250000, got {seeded['reserve_initial_cents']}"
        )
        assert seeded["reserve_balance_cents"] == 37500, (
            f"250000 less 212500 leaves 37500, got {seeded['reserve_balance_cents']}"
        )
        assert seeded["claims_paid_cents"] == 212500, (
            "212500 over a 250000 initial reserve is a utilisation of exactly 0.85, got "
            f"{seeded['claims_paid_cents']} paid"
        )

        second = adjudicate_claim(_file(state, "CLM-2", 20000, 1.0)["id"], "APPROVE")

        assert second["coinsurance_pct"] == pytest.approx(0.25, abs=0.001), (
            "the 0.25 band's lower bound is inclusive, so a utilisation of exactly 0.85 "
            f"selects it, got {second['coinsurance_pct']}"
        )
        assert second["adjudicated_amount_cents"] == 21750, (
            "20000 parts plus one hour at 9000 is a gross of 29000, and a quarter "
            f"withheld leaves 21750, got {second['adjudicated_amount_cents']}"
        )
        assert second["adjudicated_amount_cents"] != 26100, (
            "26100 is what the ten percent band would have paid, and 0.85 is not in "
            "that band"
        )
        assert second["status"] == "APPROVED", (
            "21750 fits inside the 37500 balance, so the claim is payable, got "
            f"{second['status']}"
        )

        unit = read_connected_unit(state["unit"]["id"])
        assert unit["reserve_balance_cents"] == 15750, (
            f"37500 less 21750 leaves 15750, got {unit['reserve_balance_cents']}"
        )
        assert unit["claims_paid_cents"] == 234250, (
            f"212500 plus 21750 is 234250, got {unit['claims_paid_cents']}"
        )
        assert unit["service_program_status"] == "ACTIVE", (
            "money is still left in the reserve, so coverage stays ACTIVE, got "
            f"{unit['service_program_status']}"
        )


class TestPartsCapAndTierRate:
    def test_an_extended_plus_claim_caps_the_parts_and_bills_labour_at_its_own_rate(self):
        """250000 of parts is capped at 180000 and two hours bill at 11000, paying 202000.

        PRD §3.9: "Cap the parts: the covered parts amount is the lesser of the claim's
        `parts_cost_cents` and one hundred eighty thousand cents."

        Design: Corner/calculations/parts_cap_and_extended_plus_labor_rate_are_both_applied
        """
        state = setup_warranty_environment(
            serial_number="SN-9", service_tier="EXTENDED_PLUS"
        )

        unit_before = read_connected_unit(state["unit"]["id"])
        assert unit_before["reserve_initial_cents"] == 600000, (
            "an EXTENDED_PLUS unit is activated with a 600000 reserve, got "
            f"{unit_before['reserve_initial_cents']}"
        )
        assert unit_before["coverage_end_date"].startswith("2028-07-31T00:00:00"), (
            "the EXTENDED_PLUS term is 730 days from the 2026-08-01 activation, got "
            f"{unit_before['coverage_end_date']}"
        )

        claim = adjudicate_claim(_file(state, "CLM-9", 250000, 2.0)["id"], "APPROVE")

        assert claim["coinsurance_pct"] == pytest.approx(0.00, abs=0.001), (
            "nothing has been paid on this unit, so no coinsurance applies, got "
            f"{claim['coinsurance_pct']}"
        )
        assert claim["adjudicated_amount_cents"] == 202000, (
            "the parts line is capped at 180000 and two hours at the EXTENDED_PLUS rate "
            f"of 11000 adds 22000, got {claim['adjudicated_amount_cents']}"
        )
        assert claim["adjudicated_amount_cents"] != 272000, (
            "272000 is what an uncapped 250000 parts line would have paid"
        )
        assert claim["adjudicated_amount_cents"] != 198000, (
            "198000 is what the BASE labour rate of 9000 per hour would have paid"
        )

        unit_after = read_connected_unit(state["unit"]["id"])
        assert unit_after["reserve_balance_cents"] == 398000, (
            f"600000 less 202000 leaves 398000, got "
            f"{unit_after['reserve_balance_cents']}"
        )
        assert unit_after["claims_paid_cents"] == 202000, (
            f"the payout is booked in full, got {unit_after['claims_paid_cents']}"
        )


class TestReserveExhaustionIsNotTruncated:
    def test_a_gross_over_the_balance_is_refused_while_an_exact_match_is_paid(
        self, api, warranty_adjudicator
    ):
        """252000 against a 250000 reserve is refused outright, then 250000 exactly is paid.

        PRD §3.9: "Only now compare the result against the unit's
        `reserve_balance_cents`. A payout larger than the remaining reserve is rejected
        outright with `ERR_WARRANTY_RESERVE_EXHAUSTED` — it is never truncated to fit."

        Design: Corner/validations/payout_equal_to_the_reserve_balance_is_paid_but_one_cent_more_is_refused
        """
        state = setup_warranty_environment()
        unit_before = read_connected_unit(state["unit"]["id"])
        assert unit_before["reserve_balance_cents"] == BASE_RESERVE_CENTS, (
            "the unit opens with the whole 250000 reserve available, got "
            f"{unit_before['reserve_balance_cents']}"
        )

        too_big = _file(state, "CLM-BIG", 180000, 8.0)
        exact = _file(state, "CLM-EXACT", 178000, 8.0, certification_index=0)

        refused = api.adjudicate_warranty_claim(
            too_big["id"], {"decision": "APPROVE"}, warranty_adjudicator
        )
        validate_error(refused, ApiErrorId.ERR_WARRANTY_RESERVE_EXHAUSTED.value)

        still_open = read_warranty_claim(too_big["id"])
        assert still_open["status"] == "SUBMITTED", (
            "180000 parts plus eight hours at 9000 is a gross of 252000, which exceeds "
            f"the balance, so the claim stays SUBMITTED, got {still_open['status']}"
        )
        assert still_open["adjudicated_amount_cents"] is None, (
            "a refused approval stamps no payout, got "
            f"{still_open['adjudicated_amount_cents']}"
        )
        untouched = read_connected_unit(state["unit"]["id"])
        assert untouched["reserve_balance_cents"] == BASE_RESERVE_CENTS, (
            "the refusal leaves the ledger alone, got "
            f"{untouched['reserve_balance_cents']}"
        )
        assert untouched["claims_paid_cents"] == 0, (
            f"nothing has been paid, got {untouched['claims_paid_cents']}"
        )

        paid = validate_success(
            api.adjudicate_warranty_claim(
                exact["id"], {"decision": "APPROVE"}, warranty_adjudicator
            )
        )
        assert paid["adjudicated_amount_cents"] == 250000, (
            "178000 parts plus 72000 labour is exactly the remaining reserve, got "
            f"{paid['adjudicated_amount_cents']}"
        )
        assert paid["status"] == "APPROVED", (
            f"a payout equal to the balance is payable, got {paid['status']}"
        )

        drained = read_connected_unit(state["unit"]["id"])
        assert drained["reserve_balance_cents"] == 0, (
            f"the exact payout empties the reserve, got "
            f"{drained['reserve_balance_cents']}"
        )
        assert drained["claims_paid_cents"] == 250000, (
            f"the whole reserve has now been paid out, got "
            f"{drained['claims_paid_cents']}"
        )
        assert drained["service_program_status"] == "GRACE", (
            "a reserve driven exactly to zero moves coverage into GRACE, got "
            f"{drained['service_program_status']}"
        )

        replay = api.adjudicate_warranty_claim(
            exact["id"],
            {"decision": "DENY", "denial_reason": "Filed twice"},
            warranty_adjudicator,
        )
        validate_error(replay, ApiErrorId.ERR_CLAIM_STATE_INVALID.value)

        final = read_warranty_claim(exact["id"])
        assert final["adjudicated_amount_cents"] == 250000, (
            "adjudication is permitted only while the claim is SUBMITTED, so the replay "
            f"cannot rewrite the payout, got {final['adjudicated_amount_cents']}"
        )
        assert final["status"] == "APPROVED", (
            f"the approved claim stays APPROVED, got {final['status']}"
        )


class TestVoidingCoverage:
    def test_void_zeroes_the_reserve_keeps_claims_paid_and_is_terminal(
        self, api, warranty_adjudicator
    ):
        """VOID drops the balance to zero, leaves the 150000 already paid, and refuses a replay.

        PRD §3.9: "`VOID` requires a non-empty `void_reason` and takes the unit
        `ACTIVE → VOIDED`, `EXTENDED → VOIDED` or `GRACE → VOIDED`. It sets
        `reserve_balance_cents` to zero and leaves `claims_paid_cents` at whatever has
        already been paid. `VOIDED` is terminal, and so is `EXPIRED`."

        Design: Corner/state_machines/voiding_coverage_zeroes_the_reserve_but_preserves_claims_paid
        """
        state = setup_reserve_utilisation()
        assert state["unit"]["reserve_balance_cents"] == 100000, (
            "the seeding payout leaves 100000 in the reserve, got "
            f"{state['unit']['reserve_balance_cents']}"
        )

        voided = validate_success(
            api.coverage_action(
                state["unit"]["id"],
                coverage_action_payload(
                    "VOID", void_reason="Unit destroyed in a kitchen fire"
                ),
                warranty_adjudicator,
            )
        )

        assert voided["service_program_status"] == "VOIDED", (
            f"the unit moves ACTIVE to VOIDED, got {voided['service_program_status']}"
        )
        assert voided["reserve_balance_cents"] == 0, (
            "voiding writes the remaining 100000 off to zero, got "
            f"{voided['reserve_balance_cents']}"
        )
        assert voided["reserve_initial_cents"] == BASE_RESERVE_CENTS, (
            "the initial reserve is left as it was, got "
            f"{voided['reserve_initial_cents']}"
        )
        assert voided["claims_paid_cents"] == 150000, (
            "money already paid out stays paid, got "
            f"{voided['claims_paid_cents']}"
        )

        replay = api.coverage_action(
            state["unit"]["id"],
            coverage_action_payload("VOID", void_reason="Duplicate write-off request"),
            warranty_adjudicator,
        )
        validate_error(replay, ApiErrorId.ERR_CONNECTED_STATE_INVALID.value)

        final = read_connected_unit(state["unit"]["id"])
        assert final["service_program_status"] == "VOIDED", (
            f"VOIDED is terminal, got {final['service_program_status']}"
        )
        assert final["reserve_balance_cents"] == 0, (
            f"the refused replay changes nothing, got {final['reserve_balance_cents']}"
        )
        assert final["claims_paid_cents"] == 150000, (
            f"nor does it disturb claims_paid_cents, got {final['claims_paid_cents']}"
        )
