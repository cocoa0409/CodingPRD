"""Rate schedules: overlap windows, supersession, provisional recompute
(PRD §3.4)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_invoice_payload,
    create_rate_schedule_payload,
    get_success_data,
    setup_cooperative,
    setup_member,
    setup_published_schedule,
    validate_error,
    validate_success,
)

REP = TEST_USERS["rep"]
ANALYST = TEST_USERS["rate_analyst"]
CLERK = TEST_USERS["billing_clerk"]


class TestRateOverlap:
    def test_overlapping_publish_rejected_adjacent_allowed(self, api):
        """PRD §3.4: "no other `PUBLISHED` schedule for the same `rate_class`
        may have an effectiveness window — the half-open interval from
        `effective_from` to `effective_to` — overlapping this one's, on pain of
        `ERR_RATE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/rate_schedule_effectiveness_overlap
        """
        setup_cooperative()
        rs_a = get_success_data(api.create_rate_schedule(
            create_rate_schedule_payload(
                code="RS-A", effective_from="2026-01-01T00:00:00Z",
                effective_to="2026-07-01T00:00:00Z",
                customer_charge_cents=2000,
                tiers=[{"up_to_kwh": None, "cents_per_kwh": 10}]),
            ANALYST), 201)
        get_success_data(api.publish_rate_schedule(rs_a["id"], ANALYST), 200)
        # RS-B overlaps RS-A's window ([2026-06-01, null) starts inside RS-A).
        rs_b = get_success_data(api.create_rate_schedule(
            create_rate_schedule_payload(
                code="RS-B", effective_from="2026-06-01T00:00:00Z",
                customer_charge_cents=2100,
                tiers=[{"up_to_kwh": None, "cents_per_kwh": 11}]),
            ANALYST), 201)
        resp = api.publish_rate_schedule(rs_b["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_RATE_OVERLAP)
        # RS-C starts exactly at RS-A's effective_to — half-open adjacency, so
        # no overlap.
        rs_c = get_success_data(api.create_rate_schedule(
            create_rate_schedule_payload(
                code="RS-C", effective_from="2026-07-01T00:00:00Z",
                customer_charge_cents=2200,
                tiers=[{"up_to_kwh": None, "cents_per_kwh": 12}]),
            ANALYST), 201)
        published_c = validate_success(api.publish_rate_schedule(rs_c["id"], ANALYST), 200)
        assert published_c["status"] == "PUBLISHED"

    def test_overlap_only_applies_within_same_rate_class(self, api):
        """PRD §3.4: "no other `PUBLISHED` schedule for the same `rate_class`
        may have an effectiveness window — the half-open interval from
        `effective_from` to `effective_to` — overlapping this one's, on pain of
        `ERR_RATE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/rate_schedule_effectiveness_overlap
        """
        setup_cooperative()
        setup_published_schedule(
            rate_class="RESIDENTIAL", code="RS-A",
            effective_from="2026-01-01T00:00:00Z", effective_to="2026-07-01T00:00:00Z")
        # Same window but a different rate class: not the "same rate_class", so
        # no overlap rejection.
        other = get_success_data(api.create_rate_schedule(
            create_rate_schedule_payload(
                code="GS-D", rate_class="COMMERCIAL_GENERAL",
                effective_from="2026-01-01T00:00:00Z",
                effective_to="2026-07-01T00:00:00Z"),
            ANALYST), 201)
        published = validate_success(api.publish_rate_schedule(other["id"], ANALYST), 200)
        assert published["status"] == "PUBLISHED"


class TestSupersede:
    def test_supersede_recomputes_provisional_invoice(self, api):
        """PRD §3.4: "The supersede is atomic — the incumbent moves `PUBLISHED →
        SUPERSEDED` while the replacement moves `DRAFT → PUBLISHED` in the same
        step, with the replacement's overlap check excluding the schedule being
        superseded — and every `PROVISIONAL` invoice for affected locations is
        recomputed against the new schedule."

        Design: Corner/cross_cutting_layers/supersede_recomputes_provisional_invoices
        """
        setup_cooperative()
        member, location = setup_member(status="ACTIVE")
        rs_old = setup_published_schedule(
            code="RS-old", customer_charge_cents=0,
            effective_from="2026-01-01T00:00:00Z",
            tiers=[{"up_to_kwh": None, "cents_per_kwh": 10}])
        inv = validate_success(api.create_invoice(
            create_invoice_payload(
                service_location_id=location["id"],
                billing_period_start="2026-07-01T00:00:00Z",
                billing_period_end="2026-08-01T00:00:00Z"),
            CLERK), expected_status=201)
        total_before = inv["total_due_cents"]
        rs_new = get_success_data(api.create_rate_schedule(
            create_rate_schedule_payload(
                code="RS-new", customer_charge_cents=0,
                effective_from="2026-01-01T00:00:00Z",
                tiers=[{"up_to_kwh": None, "cents_per_kwh": 20}]),
            ANALYST), 201)
        superseded = validate_success(api.supersede_rate_schedule(
            rs_old["id"], {"replacement_id": rs_new["id"]}, ANALYST), 200)
        assert superseded["status"] == "SUPERSEDED"
        rs_new_after = get_success_data(api.get_rate_schedule(rs_new["id"], ANALYST), 200)
        assert rs_new_after["status"] == "PUBLISHED"
        inv_after = get_success_data(api.get_invoice(inv["id"], CLERK), 200)
        assert inv_after["status"] == "PROVISIONAL"
        # Customer charge is zero, so the bill is pure energy: doubling the rate
        # doubles the provisional total.
        assert inv_after["total_due_cents"] == 2 * total_before

    def test_supersede_with_published_replacement_rejected(self, api):
        """PRD §3.4: "the request names a `replacement_id` identifying a `DRAFT`
        schedule for the same `rate_class` (anything else yields
        `ERR_INVALID_STATE`)".

        Design: Corner/cross_cutting_layers/supersede_recomputes_provisional_invoices
        """
        setup_cooperative()
        rs_old = setup_published_schedule(
            code="RS-old", effective_from="2026-01-01T00:00:00Z")
        rs_other = setup_published_schedule(
            code="RS-other", rate_class="COMMERCIAL_GENERAL",
            effective_from="2026-01-01T00:00:00Z")
        # The replacement is PUBLISHED (and a different class) — not a DRAFT.
        resp = api.supersede_rate_schedule(
            rs_old["id"], {"replacement_id": rs_other["id"]}, ANALYST)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
