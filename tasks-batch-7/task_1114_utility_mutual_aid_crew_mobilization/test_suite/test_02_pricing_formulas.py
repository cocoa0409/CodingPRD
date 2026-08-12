"""Combinatorial pricing formula tests (PRD §2.6, §3.6, §3.8): tiered WORK-day
labor with premium and equipment, per-claim-day rounding order, and the
mobilization fee keyed on the pre-fee subtotal."""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data,
    make_host_coordinator_headers, make_responding_coordinator_headers,
    make_crew_supervisor_headers, make_responding_finance_headers,
    make_program_admin_headers,
    set_clock, create_company, create_event, create_and_publish_schedule,
    create_accepted_request, commit_crew, conduct_and_acknowledge_briefing,
    arrive_crew, create_submitted_timesheet, certify_timesheet,
    create_approved_claim, create_draft_invoice, submit_invoice,
    setup_cleared_arrived_crew, setup_demobilized_with_certified_rows,
    create_per_diem_claim_payload, create_timesheet_payload,
)


class TestWorkDayTieredLaborWithPremiumAndEquipment:
    def test_certified_amount_combines_tiers_premium_equipment(self):
        """PRD §3.6: "A `WORK` day splits `reported_work_minutes` into three
        bands against the schedule's thresholds: straight-time minutes are the
        smaller of the reported minutes and `ot_threshold_minutes`; overtime
        minutes are whatever lies beyond `ot_threshold_minutes`, capped at the
        span between `ot_threshold_minutes` and `dt_threshold_minutes`; and
        double-time minutes are whatever lies beyond `dt_threshold_minutes`."
        PRD §3.6: "The three rounded components sum to the day's labor, and
        when the `work_date` falls inside the event's premium window — on or
        after `premium_window_start`, on or before `premium_window_end` — that
        already-rounded labor is uplifted by `storm_premium_bps` ten-thousandths
        and rounded half-up once more. Equipment is added last: the day's
        amount is the labor figure plus `equipment_daily_total_cents`,
        unrounded."

        Design: Difficulty/combinatorial_formula/work_day_tiered_labor_with_premium_and_equipment
        """
        ctx = setup_cleared_arrived_crew(
            equipment_daily_rate_cents=35000, clock_after_arrival="2026-05-05T09:00:00Z")
        ts = create_submitted_timesheet(ctx["crew"]["id"], work_date="2026-05-04",
                                        day_classification="WORK", reported_work_minutes=600)
        ts = certify_timesheet(ts["id"], ctx["host"]["id"])
        # reg 480 -> 96000; ot 120 -> round(120*12000*15000/(60*10000)) = 36000;
        # labor 132000; premium 10% -> 145200; amount = 145200 + 35000 = 180200.
        assert ts["status"] == "CERTIFIED"
        assert ts["certified_amount_cents"] == 180200

    def test_certification_pins_effective_schedule(self):
        """PRD §3.6: "On success the sheet pins that schedule as its
        `certified_schedule_id`, records the certifier, and prices the day into
        `certified_amount_cents`."

        Design: Difficulty/combinatorial_formula/work_day_tiered_labor_with_premium_and_equipment
        """
        ctx = setup_cleared_arrived_crew(
            equipment_daily_rate_cents=35000, clock_after_arrival="2026-05-05T09:00:00Z")
        ts = create_submitted_timesheet(ctx["crew"]["id"], work_date="2026-05-04",
                                        day_classification="WORK", reported_work_minutes=600)
        ts = certify_timesheet(ts["id"], ctx["host"]["id"])
        assert ts["certified_schedule_id"] == ctx["schedule"]["id"]
        assert ts["certified_by_operator_ref"] == "HC-1"


class TestPerDiemPerDayRoundingBeforeSum:
    def _setup_two_approved_claims(self):
        ctx = setup_cleared_arrived_crew()  # no equipment; crew of roster size 1
        host, rsp, event, crew = ctx["host"], ctx["rsp"], ctx["event"], ctx["crew"]
        amounts = []
        claim_ids = []
        for date in ("2026-05-03", "2026-05-04"):
            resp = api_client.create_per_diem_claim(
                create_per_diem_claim_payload(crew_id=crew["id"], claim_date=date),
                make_responding_coordinator_headers(rsp["id"]))
            claim = validate_success(resp, expected_status=201)
            claim_ids.append(claim["id"])
            amounts.append(claim["amount_cents"])
            resp = api_client.approve_per_diem_claim(
                claim["id"], make_host_coordinator_headers(host["id"]))
            assert resp.status_code == 200, f"Setup failed approving claim: {resp.text}"
        return ctx, claim_ids, amounts

    def test_each_claim_day_rounds_half_up(self):
        """PRD §3.6: "Pricing has two variants selected by `method_applied`, and
        both round half-up to whole cents per claim-day before any summation;
        adding unrounded daily values and rounding once at the end is forbidden."

        Design: Difficulty/combinatorial_formula/per_diem_per_day_rounding_before_sum
        """
        _, _, amounts = self._setup_two_approved_claims()
        # raw per day: 1 * 8950 * 0.75 * (3-0)/3 = 6712.5 -> rounds to 6713
        assert amounts[0] == 6713
        assert amounts[1] == 6713

    def test_request_certified_total_sums_rounded_days(self):
        """PRD §2.6: "Per-diem claims in particular are priced per claim-day and
        rounded before any summation; summing unrounded daily values and rounding
        the total once is forbidden, because the two orders can differ by cents."
        PRD §3.6: "approval moving a claim to `APPROVED` and recomputing the
        request's `certified_direct_cents` and the event's
        `total_certified_direct_cents`"

        Design: Difficulty/combinatorial_formula/per_diem_per_day_rounding_before_sum
        """
        ctx, _, _ = self._setup_two_approved_claims()
        resp = api_client.get_assistance_request(
            ctx["request"]["id"], make_program_admin_headers())
        request = validate_success(resp)
        # 6713 + 6713 = 13426 (sum-then-round of 13425.0 would give 13425)
        assert request["certified_direct_cents"] == 13426


class TestMobilizationFeeKeyedOnPrefeeSubtotal:
    def _setup_invoice_straddling_tier_boundary(self):
        ctx = setup_demobilized_with_certified_rows()
        # Rebuild the schedule with a second tier at 200000 so the boundary sits
        # between the pre-fee subtotal (186913) and the post-fee total (201866).
        # The canonical fixture publishes a single-tier schedule; here we need
        # the two-tier variant, so we re-run the scenario pieces manually.
        return ctx

    def _setup_two_tier_scenario(self):
        set_clock("2026-05-01T08:00:00Z")
        host = create_company(name="Host Power", company_code="HST",
                              role_capability="BOTH", home_region="Coastal")
        rsp = create_company(name="Responder Electric", company_code="RSP",
                             role_capability="RESPONDING", home_region="Inland")
        event = create_event(host["id"], activate=True)
        schedule = create_and_publish_schedule(event["id"], rsp["id"], mobilization_fee_tiers=[
            {"min_subtotal_cents": 0, "fee_bps": 800},
            {"min_subtotal_cents": 200000, "fee_bps": 500},
        ])
        request = create_accepted_request(event["id"], host["id"], rsp["id"])
        crew = commit_crew(request["id"], rsp["id"], equipment_units=[
            {"unit_type": "bucket_truck", "unit_ref": "BT-1", "daily_rate_cents": 35000},
        ])
        conduct_and_acknowledge_briefing(crew["id"], event["id"], host["id"])
        arrive_crew(crew["id"], host["id"])
        set_clock("2026-05-05T09:00:00Z")
        ts = create_submitted_timesheet(crew["id"], work_date="2026-05-04",
                                        day_classification="WORK", reported_work_minutes=600)
        certify_timesheet(ts["id"], host["id"])
        create_approved_claim(crew["id"], rsp["id"], host["id"], claim_date="2026-05-03")
        resp = api_client.begin_demobilization(event["id"], make_host_coordinator_headers(host["id"]))
        assert resp.status_code == 200, f"Setup failed demobilizing: {resp.text}"
        invoice = create_draft_invoice(request["id"], schedule["id"], rsp["id"])
        return {"host": host, "rsp": rsp, "event": event, "schedule": schedule,
                "request": request, "crew": crew, "invoice": invoice}

    def test_fee_uses_tier_selected_by_prefee_subtotal(self):
        """PRD §3.8: "The mobilization fee is then selected from the schedule's
        `mobilization_fee_tiers`: sorted ascending by `min_subtotal_cents`, the
        applicable tier is the last tier whose threshold is at most the pre-fee
        direct subtotal — keyed always on the pre-fee subtotal, never on the
        post-fee total — and `mobilization_fee_cents` is the subtotal times that
        tier's `fee_bps`, divided by ten thousand, rounded half-up."

        Design: Difficulty/combinatorial_formula/mobilization_fee_tier_keyed_on_prefee_subtotal
        """
        ctx = self._setup_two_tier_scenario()
        resp = api_client.submit_invoice(
            ctx["invoice"]["id"], make_responding_finance_headers(ctx["rsp"]["id"]))
        invoice = validate_success(resp)
        assert invoice["labor_subtotal_cents"] + invoice["per_diem_subtotal_cents"] == 186913
        # pre-fee 186913 < 200000 => 800bps tier: round(186913*800/10000) = 14953
        assert invoice["mobilization_fee_cents"] == 14953

    def test_post_fee_total_may_cross_the_tier_boundary(self):
        """PRD §3.8: "keyed always on the pre-fee subtotal, never on the post-fee
        total" PRD §3.8: "`final_total_cents` is labor plus per-diem plus fee."

        Design: Difficulty/combinatorial_formula/mobilization_fee_tier_keyed_on_prefee_subtotal
        """
        ctx = self._setup_two_tier_scenario()
        resp = api_client.submit_invoice(
            ctx["invoice"]["id"], make_responding_finance_headers(ctx["rsp"]["id"]))
        invoice = validate_success(resp)
        # post-fee total 201866 exceeds the 200000 tier threshold, proving the
        # 800bps tier was keyed on the pre-fee subtotal.
        assert invoice["final_total_cents"] == 201866
        assert invoice["final_total_cents"] > 200000
