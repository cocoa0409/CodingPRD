"""Conversion-to-employee fees: dual-variant selection, SCHEDULE band edges,
and the one-open-request constraint."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_conversion_request,
    create_active_rate_card,
    create_assignment_payload,
    create_conversion_request_payload,
    create_engagement_in_open,
    create_worker_payload,
    get_success_data,
    make_supplier_coordinator_headers,
    onboard_supplier,
    pick_offer_for_supplier,
    set_logical_clock,
    setup_staffed_assignment,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
HM = TEST_USERS["hiring_manager_headers"]


def _staff_engagement(api, *, rate_card, supplier, title, prorata_conversion,
                      worker_name, worker_email, start_date="2026-03-01",
                      end_date="2026-12-31", tenure_carryover_days=0):
    """Distribute an engagement to the given supplier, accept, register a
    worker, book and activate the assignment. Returns (engagement, worker,
    assignment)."""
    engagement = create_engagement_in_open(
        title=title, duration_months=12, budget_cents=5_000_000,
        prorata_conversion=prorata_conversion,
    )
    offers = get_success_data(api.distribute_engagement(engagement["id"], ADMIN))
    offer = pick_offer_for_supplier(offers, supplier["id"])
    get_success_data(
        api.respond_to_offer(
            offer["id"], {"action": "ACCEPT"},
            make_supplier_coordinator_headers(supplier["id"]),
        )
    )
    worker = get_success_data(
        api.create_worker(
            create_worker_payload(
                supplier["id"], full_name=worker_name, email=worker_email,
                tenure_carryover_days=tenure_carryover_days,
            ),
            make_supplier_coordinator_headers(supplier["id"]),
        )
    )
    assignment = get_success_data(
        api.create_assignment(
            create_assignment_payload(
                worker["id"], engagement["id"], offer["id"], rate_card["id"],
                bill_rate_cents=9500, pay_rate_cents=8000,
                start_date=start_date, end_date=end_date,
            ),
            ADMIN,
        )
    )
    get_success_data(api.activate_assignment(assignment["id"], ADMIN))
    return engagement, worker, assignment


class TestConversionFeeScheduleVsProrata:
    def test_prorata_variant_fee_for_preferred_supplier(self, api):
        """PRD: "The fee variant is pinned: `PRORATA` applies only when the
        engagement's `prorata_conversion` flag is true and the supplier's
        tier is `PREFERRED`; every other case uses `SCHEDULE`."
        PRD: "Under `PRORATA`, the fee decays linearly across a 730-day
        horizon: the base multiplied by one minus the tenure divided by 730,
        floored at zero, rounded half up to whole cents."

        Design: Difficulty/dual_variant_calc/conversion_fee_schedule_vs_prorata
        """
        set_logical_clock("2026-05-01T00:00:00Z")
        rate_card = create_active_rate_card()
        supplier_p = onboard_supplier(tier="PREFERRED", name="Preferred Staffing",
                                      supplier_code="SUP-P")
        _engagement, worker_a, assignment_a = _staff_engagement(
            api, rate_card=rate_card, supplier=supplier_p,
            title="Prorata engagement", prorata_conversion=True,
            worker_name="Worker A", worker_email="wa@example.com",
        )
        # assignment ACTIVE since 2026-03-01; clock 2026-05-01 -> 62 days
        request_a = validate_success(
            api.create_conversion_request(
                create_conversion_request_payload(worker_a["id"], assignment_a["id"]), HM
            ),
            expected_status=201,
        )
        assert_conversion_request(request_a)
        assert request_a["tenure_days_at_request"] == 62
        assert request_a["fee_variant"] == "PRORATA", (
            "prorata flag true AND supplier PREFERRED"
        )
        assert request_a["fee_cents"] == 2_287_671, (
            "round_half_up(2500000 x (1 - 62/730))"
        )
        assert request_a["status"] == "REQUESTED"

    def test_schedule_variant_fee_for_approved_supplier_same_tenure(self, api):
        """PRD: "every other case uses `SCHEDULE`. The base fee is 2,500,000
        cents. Under `SCHEDULE`, the fee is a step function of tenure: below
        180 days the full base applies"
        PRD: "The two variants genuinely differ for identical tenure — at 62
        days, for instance, `SCHEDULE` charges the full 2,500,000 cents while
        `PRORATA` charges 2,287,671 cents."

        Design: Difficulty/dual_variant_calc/conversion_fee_schedule_vs_prorata
        """
        set_logical_clock("2026-05-01T00:00:00Z")
        rate_card = create_active_rate_card()
        supplier_p = onboard_supplier(tier="PREFERRED", name="Preferred Staffing",
                                      supplier_code="SUP-P")
        supplier_b = onboard_supplier(tier="APPROVED", name="Budget Staffing",
                                      supplier_code="SUP-B")
        _ea, worker_a, assignment_a = _staff_engagement(
            api, rate_card=rate_card, supplier=supplier_p,
            title="Prorata engagement", prorata_conversion=True,
            worker_name="Worker A", worker_email="wa@example.com",
        )
        _eb, worker_b, assignment_b = _staff_engagement(
            api, rate_card=rate_card, supplier=supplier_b,
            title="Schedule engagement", prorata_conversion=True,
            worker_name="Worker B", worker_email="wb@example.com",
        )
        request_a = get_success_data(
            api.create_conversion_request(
                create_conversion_request_payload(worker_a["id"], assignment_a["id"]), HM
            )
        )
        request_b = validate_success(
            api.create_conversion_request(
                create_conversion_request_payload(worker_b["id"], assignment_b["id"]), HM
            ),
            expected_status=201,
        )
        assert request_b["tenure_days_at_request"] == 62
        assert request_b["fee_variant"] == "SCHEDULE", (
            "the tier gate fails for an APPROVED supplier despite the prorata flag"
        )
        assert request_b["fee_cents"] == 2_500_000, "band < 180 days -> 100% of base"
        assert request_a["fee_cents"] != request_b["fee_cents"], (
            "dual-variant divergence on identical tenure"
        )


class TestConversionFeeScheduleBandEdges:
    def test_schedule_band_544_days_half_fee(self, api):
        """PRD: "Under `SCHEDULE`, the fee is a step function of tenure:
        below 180 days the full base applies; from 180 through 364 days, 75%
        of the base; from 365 through 544 days, 50%; and at 545 days or more
        the fee is zero."
        PRD: "At filing, the system snapshots `tenure_days_at_request` (the
        tenure accumulation of §3.5 evaluated at the logical clock date)"

        Design: Corner/calculations/conversion_fee_schedule_band_edges
        """
        set_logical_clock("2026-05-01T00:00:00Z")
        rate_card = create_active_rate_card()
        supplier = onboard_supplier(tier="APPROVED", name="Edge Co",
                                    supplier_code="SUP-ED")
        _e, worker_a, assignment_a = _staff_engagement(
            api, rate_card=rate_card, supplier=supplier, title="E1",
            prorata_conversion=False, worker_name="Worker A",
            worker_email="wa@example.com", start_date="2026-04-15",
            end_date="2026-06-30", tenure_carryover_days=527,
        )
        # accrued 2026-04-15..2026-05-01 inclusive = 17 days -> tenure 544
        request_a = validate_success(
            api.create_conversion_request(
                create_conversion_request_payload(worker_a["id"], assignment_a["id"]), HM
            ),
            expected_status=201,
        )
        assert request_a["tenure_days_at_request"] == 544
        assert request_a["fee_variant"] == "SCHEDULE"
        assert request_a["fee_cents"] == 1_250_000, (
            "band 365..544 -> 50% of 2500000"
        )

    def test_schedule_band_545_days_zero_fee(self, api):
        """PRD: "from 365 through 544 days, 50%; and at 545 days or more the
        fee is zero."

        Design: Corner/calculations/conversion_fee_schedule_band_edges
        """
        set_logical_clock("2026-05-01T00:00:00Z")
        rate_card = create_active_rate_card()
        supplier = onboard_supplier(tier="APPROVED", name="Edge Co",
                                    supplier_code="SUP-ED")
        _e, worker_b, assignment_b = _staff_engagement(
            api, rate_card=rate_card, supplier=supplier, title="E2",
            prorata_conversion=False, worker_name="Worker B",
            worker_email="wb@example.com", start_date="2026-04-15",
            end_date="2026-06-30", tenure_carryover_days=528,
        )
        # tenure 528 + 17 = 545 -> free conversion boundary
        request_b = validate_success(
            api.create_conversion_request(
                create_conversion_request_payload(worker_b["id"], assignment_b["id"]), HM
            ),
            expected_status=201,
        )
        assert request_b["tenure_days_at_request"] == 545
        assert request_b["fee_variant"] == "SCHEDULE"
        assert request_b["fee_cents"] == 0, "band >= 545 -> zero fee"


def test_second_conversion_request_returns_409(api):
    """PRD: "A worker may have at most one conversion request in `REQUESTED`
    or `APPROVED` at a time; a second filing is rejected with
    `ERR_CONVERSION_ALREADY_REQUESTED` (409)."

    Design: Corner/errors/second_conversion_request_returns_409
    """
    ctx = setup_staffed_assignment(supplier_name="Conv Co", supplier_code="SUP-CV")
    first = validate_success(
        api.create_conversion_request(
            create_conversion_request_payload(ctx["worker"]["id"],
                                              ctx["assignment"]["id"]),
            HM,
        ),
        expected_status=201,
    )
    assert first["status"] == "REQUESTED"

    resp = api.create_conversion_request(
        create_conversion_request_payload(ctx["worker"]["id"],
                                          ctx["assignment"]["id"]),
        HM,
    )
    validate_error(resp, ApiErrorId.ERR_CONVERSION_ALREADY_REQUESTED)
    after = get_success_data(api.get_conversion_request(first["id"], ADMIN))
    assert after["status"] == "REQUESTED", "R1 is untouched by the rejected filing"
