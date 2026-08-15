"""Warranty claims: dual valuation, the undecided-claim invoice gate, the
appeal cap, and coverage-window eligibility."""
from test_helpers import (
    TEST_USERS,
    appeal_claim,
    assert_warranty_claim,
    create_fleet,
    create_invoice_for_call,
    create_standard_rate_card,
    create_technician,
    create_vehicle,
    decide_claim,
    file_warranty_claim,
    get_call,
    get_success_data,
    run_on_site_repair,
    setup_s1_completed_job,
    submit_claim,
    validate_error,
    validate_paginated,
)
from test_helpers import ApiErrorId

OPS = TEST_USERS["ops_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
WARRANTY_ADMIN = TEST_USERS["warranty_admin_headers"]


def _completed_warranty_job():
    """Canonical S1 job (136698 customer-pay basis: 2.5h STANDARD, 40 actual
    miles, 95 travel minutes, 2x ALT-104 @ 34999) on a warranty-active fleet
    vehicle (OEM coverage to 2027-06-01, 200000-mile limit)."""
    # setup_s1_completed_job publishes the STD-2026 card itself; publishing a
    # second card with the identical closed window would (correctly) be
    # rejected with ERR_RATE_CARD_WINDOW_OVERLAP per PRD section 2.9.
    fleet = create_fleet()
    return setup_s1_completed_job(fleet=fleet, warranty_vehicle=True)


class TestDualValuation:
    def test_warranty_oem_basis_vs_retail_basis_split(self, api):
        """PRD: "The OEM basis, `oem_value_cents`, is computed at filing: the
        product of `oem_labor_hours` and `oem_labor_rate_cents` rounded
        half-up, plus `parts_at_cost_cents`." and "The retail basis,
        `retail_value_cents`, is computed at submission: the call's
        `labor_hours_actual` multiplied by the resolved card's standard labor
        rate — OEMs reimburse the standard class, never the master premium —
        rounded half-up, plus the sum of `line_total_cents` over the call's
        `POSTED` customer-pay usages."

        Design: Difficulty/dual_variant_calc/warranty_oem_basis_vs_retail_basis_split
        """
        ctx = _completed_warranty_job()
        claim = file_warranty_claim(ctx["call"]["id"], ctx["tech_headers"],
                                    oem_labor_hours=1.8,
                                    oem_labor_rate_cents=12000,
                                    parts_at_cost_cents=42000)
        assert_warranty_claim(claim)
        # OEM basis: round_half_up(1.8 x 12000) + 42000 = 21600 + 42000.
        assert claim["oem_value_cents"] == 63600

        submitted = submit_claim(claim["id"])
        # Retail basis: round_half_up(2.5 x 14500) + 2 x 34999
        # = 36250 + 69998 = 106248.
        assert submitted["retail_value_cents"] == 106248

    def test_recovered_is_the_lesser_of_the_two_bases(self, api):
        """PRD: "The recoverable `recovered_cents` is the lesser of the two
        bases and is likewise computed at submission." and "`warranty_offset_cents`
        sums `recovered_cents` over the call's claims in `APPROVED` or
        `SETTLED`".

        Design: Difficulty/dual_variant_calc/warranty_oem_basis_vs_retail_basis_split
        """
        ctx = _completed_warranty_job()
        claim = file_warranty_claim(ctx["call"]["id"], ctx["tech_headers"],
                                    oem_labor_hours=1.8,
                                    oem_labor_rate_cents=12000,
                                    parts_at_cost_cents=42000)
        submitted = submit_claim(claim["id"])
        assert submitted["recovered_cents"] == 63600, (
            "min(oem 63600, retail 106248)")
        decide_claim(claim["id"], "APPROVED")

        invoice = create_invoice_for_call(ctx["call"]["id"])
        assert invoice["warranty_offset_cents"] == 63600
        # 136698 customer-pay total minus the 63600 recovery.
        assert invoice["total_cents"] == 73098


class TestInvoiceGateOnUndecidedClaim:
    def _submitted_claim_ctx(self):
        ctx = _completed_warranty_job()
        claim = file_warranty_claim(ctx["call"]["id"], ctx["tech_headers"])
        submit_claim(claim["id"])
        return ctx, claim

    def test_invoice_create_blocked_by_undecided_warranty_claim(self, api):
        """PRD: "no claim may be filed while a non-`VOID` invoice exists for
        the call, and conversely no invoice may be drafted while a claim of
        the call sits in `DRAFT`, `SUBMITTED`, or `APPEALED`
        (`ERR_WARRANTY_CLAIM_UNDECIDED`)".

        Design: Difficulty/cross_entity_state_dependency/invoice_create_blocked_by_undecided_warranty_claim
        """
        ctx, _claim = self._submitted_claim_ctx()
        resp = api.create_invoice(ctx["call"]["id"], TEST_USERS[
            "billing_clerk_headers"])
        validate_error(resp, ApiErrorId.ERR_WARRANTY_CLAIM_UNDECIDED)

    def test_undecided_claim_gate_leaves_call_repair_completed(self, api):
        """PRD: "no invoice may be drafted while a claim of the call sits in
        `DRAFT`, `SUBMITTED`, or `APPEALED` (`ERR_WARRANTY_CLAIM_UNDECIDED`)"
        — the rejection mutates nothing; the call remains REPAIR_COMPLETED
        and no invoice row appears.

        Design: Difficulty/cross_entity_state_dependency/invoice_create_blocked_by_undecided_warranty_claim
        """
        ctx, _claim = self._submitted_claim_ctx()
        resp = api.create_invoice(ctx["call"]["id"], TEST_USERS[
            "billing_clerk_headers"])
        validate_error(resp, ApiErrorId.ERR_WARRANTY_CLAIM_UNDECIDED)
        assert get_call(ctx["call"]["id"])["status"] == "REPAIR_COMPLETED"
        _data, meta = validate_paginated(api.list_invoices(
            TEST_USERS["billing_clerk_headers"],
            params={"service_call_id": ctx["call"]["id"]}))
        assert meta["total_count"] == 0


class TestClaimEligibilityWindows:
    def test_warranty_window_expired_and_extended_not_applicable(self, api):
        """PRD: "for the two OEM claim types, the call's `received_at` must
        fall before the vehicle's `oem_warranty_expires_at` and the call's
        `completion_odometer_miles` must not exceed `oem_warranty_miles_limit`
        (`ERR_WARRANTY_WINDOW_EXPIRED` otherwise); for an extended-contract
        claim, the vehicle's `extended_warranty` flag must be true
        (`ERR_WARRANTY_NOT_APPLICABLE` otherwise)."

        Design: Corner/errors/warranty_window_expired_and_extended_not_applicable
        """
        # Vehicle whose OEM coverage expired 2026-01-01 with a 250000-mile
        # limit; the call is received 2026-08-05 (past the time prong) and
        # completes at 300050 miles (past the mileage prong).
        create_standard_rate_card()
        expired_veh = create_vehicle(
            odometer_miles=300000, year=2019,
            oem_warranty_expires_at="2026-01-01T00:00:00Z",
            oem_warranty_miles_limit=250000)
        tech, tech_headers = create_technician()
        late = run_on_site_repair(
            expired_veh["id"], tech["id"], tech_headers,
            received_at="2026-08-05T09:00:00Z",
            window=("2026-08-05T09:00:00Z", "2026-08-05T13:00:00Z"),
            depart_at=None, arrive_at="2026-08-05T09:40:00Z",
            actual_travel_miles=20, planned_travel_miles=20,
            labor_hours_actual=1.5, completion_odometer_miles=300050)

        claim_base = {"oem_labor_hours": 1.0, "oem_labor_rate_cents": 12000,
                      "parts_at_cost_cents": 5000}
        resp_oem = api.create_warranty_claim(
            late["call"]["id"], {"claim_type": "OEM_BASE", **claim_base},
            tech_headers)
        validate_error(resp_oem, ApiErrorId.ERR_WARRANTY_WINDOW_EXPIRED)
        resp_extended = api.create_warranty_claim(
            late["call"]["id"],
            {"claim_type": "EXTENDED_SERVICE_CONTRACT", **claim_base},
            tech_headers)
        validate_error(resp_extended, ApiErrorId.ERR_WARRANTY_NOT_APPLICABLE)


class TestAppealCap:
    def test_warranty_appeal_limit_enforced(self, api):
        """PRD: "the appeal cap is two, and an appeal attempted when
        `appeal_count` has already reached two is rejected with
        `ERR_APPEAL_LIMIT_REACHED` — a denial at that point is effectively
        terminal."

        Design: Corner/state_machines/warranty_appeal_limit_enforced
        """
        ctx = _completed_warranty_job()
        claim = file_warranty_claim(ctx["call"]["id"], ctx["tech_headers"],
                                    oem_labor_hours=1.0,
                                    oem_labor_rate_cents=12000,
                                    parts_at_cost_cents=5000)
        submit_claim(claim["id"])
        decide_claim(claim["id"], "DENIED", denial_reason="wear item")
        first = appeal_claim(claim["id"])
        assert first["appeal_count"] == 1
        decide_claim(claim["id"], "DENIED", denial_reason="still wear")
        second = appeal_claim(claim["id"])
        assert second["appeal_count"] == 2
        decide_claim(claim["id"], "DENIED", denial_reason="final")

        resp = api.appeal_warranty_claim(claim["id"], DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_APPEAL_LIMIT_REACHED)
        current = get_success_data(
            api.get_warranty_claim(claim["id"], WARRANTY_ADMIN))
        assert current["status"] == "DENIED"
        assert current["appeal_count"] == 2
