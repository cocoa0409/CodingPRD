"""Off-hire finalization, cascades, and invoice composition (PRD §3.9)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assess_incident,
    close_contract,
    get_contract,
    get_incident,
    get_line,
    get_unit,
    off_hire_contract,
    off_hire_line,
    report_incident,
    setup_off_hire_contract,
    setup_on_rent_contract,
    validate_error,
    validate_success,
)

TEST_SALES = TEST_USERS["sales_engineer_headers"]

LOYAL_TWO_UNIT = {
    "customer_overrides": {
        "name": "Loyal Rentals Co",
        "billing_email": "ap@loyal.example",
        "loyalty_discount_pct": 0.07,
    },
    "unit_overrides": {
        "capacity_kw": 100, "nox_g_per_kwh": 2.0,
        "day_rate_cents": 10001, "week_rate_cents": 50005,
        "month_rate_cents": 200011, "demob_fee_cents": 50000,
    },
    "extra_unit_overrides": [{
        "capacity_kw": 100, "nox_g_per_kwh": 2.0,
        "day_rate_cents": 10001, "week_rate_cents": 50005,
        "month_rate_cents": 200011, "demob_fee_cents": 50000,
    }],
    "contract_overrides": {
        "load_profile": [{"load_type": "CONTINUOUS", "nameplate_kw": 80}],
        "start_date": "2026-09-01T00:00:00Z",
        "expected_offhire_date": "2026-09-06T00:00:00Z",
    },
}


class TestContractOffHireCascade:
    def test_offhire_finalizes_each_on_rent_line(self, api):
        """PRD §3.9: "Contract-level off-hire, performed by the same two roles on an
        `ON_RENT` contract, applies the identical finalization to every line still
        `ON_RENT`: each such line moves to `OFF_HIRED` with its final charge and
        `offhired_at` set, each deployed unit moves to `OFF_RENT`, the contract stamps
        `actual_offhire_at`, and the contract lands in `OFF_HIRE` with its version
        incremented."
        PRD §3.9: "the window runs from the contract's `start_date` inclusive to the
        off-hire moment exclusive, so the chargeable days are the elapsed seconds
        divided by 86,400 and rounded up".

        Design: Difficulty/transitive_cascade/offhire_cascades_line_finalize_unit_release
        """
        bundle = setup_off_hire_contract(
            off_hire_clock="2026-09-04T00:00:00Z", with_kit=True
        )
        contract = bundle["contract"]
        assert contract["status"] == "OFF_HIRE"
        assert contract["actual_offhire_at"].startswith("2026-09-04T00:00:00")

        equipment_line = get_line(bundle["line"]["id"])
        # 3 elapsed days x 12000 = 36000 time charge + 35000 demob = 71000.
        assert equipment_line["status"] == "OFF_HIRED"
        assert equipment_line["final_charge_cents"] == 71000
        assert equipment_line["offhired_at"].startswith("2026-09-04T00:00:00")

        kit_line = get_line(bundle["kit_line"]["id"])
        # 3 days x 3000 = 9000, under the 15000 week cap; kits carry no demob fee.
        assert kit_line["status"] == "OFF_HIRED"
        assert kit_line["final_charge_cents"] == 9000

    def test_offhire_releases_unit_to_off_rent(self, api):
        """PRD §3.9: "each deployed unit moves to `OFF_RENT`" (contract off-hire).
        PRD §3.9: "its unit — if the line is an equipment line — flips `DEPLOYED →
        OFF_RENT` with `current_site_id` cleared."

        Design: Difficulty/transitive_cascade/offhire_cascades_line_finalize_unit_release
        """
        bundle = setup_on_rent_contract(clock_after_start="2026-09-04T00:00:00Z")
        unit = bundle["unit"]
        assert get_unit(unit["id"])["status"] == "DEPLOYED"

        off_hire_contract(bundle["contract"]["id"])
        released = get_unit(unit["id"])
        assert released["status"] == "OFF_RENT"
        assert released["current_site_id"] is None


class TestPartialLineOffHire:
    def test_partial_line_offhire_keeps_contract_on_rent(self, api):
        """PRD §3.9: "A partial off-hire — performed by a `SalesEngineer` or the
        owning `Customer` on a line standing in `ON_RENT` — is allowed while the
        parent contract is `ON_RENT` or `SUSPENDED`, and it finalizes that line alone:
        the line moves to `OFF_HIRED`, its `final_charge_cents` is computed by the
        final accrual below, its `offhired_at` is stamped from the logical clock, and
        its unit — if the line is an equipment line — flips `DEPLOYED → OFF_RENT` with
        `current_site_id` cleared."

        Design: Corner/state_machines/partial_line_offhire_keeps_contract_on_rent
        """
        bundle = setup_on_rent_contract(
            with_kit=True, clock_after_start="2026-09-04T00:00:00Z"
        )
        finalized = off_hire_line(bundle["line"]["id"])
        assert finalized["status"] == "OFF_HIRED"
        assert finalized["final_charge_cents"] == 71000  # 3 days x 12000 + 35000

        assert get_contract(bundle["contract"]["id"])["status"] == "ON_RENT"
        kit_line = get_line(bundle["kit_line"]["id"])
        assert kit_line["status"] == "ON_RENT"
        assert kit_line["final_charge_cents"] is None

        unit = get_unit(bundle["unit"]["id"])
        assert unit["status"] == "OFF_RENT"
        assert unit["current_site_id"] is None


class TestInvoiceRoundingOrder:
    def test_invoice_per_line_discount_rounding_total(self, api):
        """PRD §3.9: "First, each line's discounted charge is its
        `final_charge_cents` multiplied by one minus the customer's
        `loyalty_discount_pct`, rounded half-up to whole cents — the rounding happens
        per line before any summation, because summing first and rounding once would
        yield different cents."
        PRD §3.9: "The invoice total is the lines subtotal plus the damage component,
        minus the fuel credit, minus the service-level credit, all in exact integer
        cents with rounding only at the per-line discount and the fuel credit, in that
        order."

        Design: Difficulty/combinatorial_formula/invoice_discount_rounds_per_line_then_sums
        """
        bundle = setup_off_hire_contract(
            off_hire_clock="2026-09-06T00:00:00Z", **LOYAL_TWO_UNIT
        )
        closed = close_contract(bundle["contract"]["id"])
        # Per line: round_half_up(100005 * 0.93) = 93005; two lines -> 186010.
        # Sum-then-round would give round_half_up(200010 * 0.93) = 186009.
        assert closed["status"] == "CLOSED"
        assert closed["invoice_total_cents"] == 186010

    def test_invoice_line_final_charges_feed_the_per_line_rounding(self, api):
        """PRD §3.9: "Second, those discounted lines are summed into a lines
        subtotal."
        PRD §3.9: "the line's `demob_fee_cents` is added once for each equipment
        line."

        Design: Difficulty/combinatorial_formula/invoice_discount_rounds_per_line_then_sums
        """
        bundle = setup_off_hire_contract(
            off_hire_clock="2026-09-06T00:00:00Z", **LOYAL_TWO_UNIT
        )
        for line in [bundle["line"], *bundle["extra_lines"]]:
            finalized = get_line(line["id"])
            # 5 days: min(5 x 10001, 50005) = 50005 time charge + 50000 demob.
            assert finalized["final_charge_cents"] == 100005

        closed = close_contract(bundle["contract"]["id"])
        assert closed["invoice_total_cents"] == 186010


class TestCloseBlockedByOpenIncident:
    def _setup_off_hire_with_reported_incident(self, api):
        """ON_RENT contract with a DAMAGE incident still REPORTED, taken OFF_HIRE at
        day 3 (line finalizes at 71000)."""
        bundle = setup_on_rent_contract(clock_after_start="2026-09-04T00:00:00Z")
        incident = report_incident(
            bundle["contract"]["id"], bundle["unit"]["id"], "DAMAGE",
            as_customer_id=bundle["customer"]["id"], notes="cracked alternator bracket",
        )
        bundle["contract"] = off_hire_contract(bundle["contract"]["id"])
        bundle["incident"] = incident
        return bundle

    def test_close_blocked_while_incident_reported(self, api):
        """PRD §3.9: "A contract in `OFF_HIRE` may close only when no incident on it
        remains `REPORTED` — an open incident blocks the close with
        `ERR_OPEN_INCIDENTS` (HTTP 422) — and when every line stands in `OFF_HIRED` or
        `RETURNED`."

        Design: Difficulty/cross_entity_state_dependency/close_blocked_by_reported_incident
        """
        bundle = self._setup_off_hire_with_reported_incident(api)
        res = api.close_contract(bundle["contract"]["id"], TEST_SALES)
        validate_error(res, ApiErrorId.ERR_OPEN_INCIDENTS, expected_status=422)
        assert get_contract(bundle["contract"]["id"])["status"] == "OFF_HIRE"

    def test_close_after_assessment_invoices_damage_and_charges_incident(self, api):
        """PRD §3.9: "Third, the damage component is the sum of
        `assessed_charge_cents` over the incidents transitioning `ASSESSED → CHARGED`
        on this close."
        PRD §3.9: "The close stamps the total onto `invoice_total_cents`, cascades the
        assessed incidents to `CHARGED`, increments the contract version, and lands
        the contract in the terminal `CLOSED` state."

        Design: Difficulty/cross_entity_state_dependency/close_blocked_by_reported_incident
        """
        bundle = self._setup_off_hire_with_reported_incident(api)
        cid = bundle["contract"]["id"]

        res = api.close_contract(cid, TEST_SALES)
        validate_error(res, ApiErrorId.ERR_OPEN_INCIDENTS, expected_status=422)

        assess_incident(bundle["incident"]["id"], 15000)

        closed = close_contract(cid)
        assert closed["status"] == "CLOSED"
        # line final 71000 (no loyalty discount) + damage 15000 = 86000
        assert closed["invoice_total_cents"] == 86000
        assert get_incident(bundle["incident"]["id"])["status"] == "CHARGED"
