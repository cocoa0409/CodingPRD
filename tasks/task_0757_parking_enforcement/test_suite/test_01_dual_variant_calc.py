"""Difficulty rule: dual_variant_calc.

Two derived figures computed from the same underlying state diverge:
  (A) a Vehicle's settled outstanding_balance_cents vs its forward-looking
      projected_balance_cents when a PENDING payment exists;
  (B) a Shift's gross_citation_count vs net_citation_count when a citation
      is voided.
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
    setup_issuing_context,
    issue_in_context,
    create_payment,
    void_citation,
    close_shift,
)

ADMIN = TEST_USERS["admin_headers"]


class TestVehicleOutstandingVsProjected:
    def test_outstanding_balance_ignores_pending_payment(self, api):
        """PRD §3.4: "The `outstanding_balance_cents` is the settled-basis balance
        and is authoritative for enforcement: for each unpaid citation it takes the
        fine less only that citation's `SETTLED` payments and applied waivers
        (floored at 0), and sums those across the set — `PENDING` payments do not
        reduce it."
        PRD §3.5: "A newly recorded payment opens in `status` `PENDING`, which
        reduces the vehicle's `projected_balance_cents` but not its authoritative
        `outstanding_balance_cents`."

        Design: Difficulty/dual_variant_calc/vehicle_outstanding_vs_projected_balance
        """
        ctx = setup_issuing_context(base_fine_cents=15000, code="HYDRANT")
        cit = issue_in_context(ctx)
        assert cit["fine_amount_cents"] == 15000
        pay = create_payment(cit["id"], 5000, method="CARD")
        assert pay["status"] == "PENDING"

        veh = validate_success(api.get_vehicle(ctx["vehicle"]["id"], ADMIN))
        assert veh["outstanding_balance_cents"] == 15000, \
            f"settled basis must ignore PENDING, got {veh['outstanding_balance_cents']}"

    def test_projected_balance_credits_pending_payment(self, api):
        """PRD §3.4: "The `projected_balance_cents` is the forward-looking preview:
        it computes the same per-citation shortfall but additionally credits
        `PENDING` payments as though they will settle, and therefore diverges from
        the settled balance exactly whenever a `PENDING` payment exists."

        Design: Difficulty/dual_variant_calc/vehicle_outstanding_vs_projected_balance
        """
        ctx = setup_issuing_context(base_fine_cents=15000, code="HYDRANT")
        cit = issue_in_context(ctx)
        create_payment(cit["id"], 5000, method="CARD")

        veh = validate_success(api.get_vehicle(ctx["vehicle"]["id"], ADMIN))
        assert veh["projected_balance_cents"] == 10000, \
            f"projected must credit the 5000 PENDING payment, got {veh['projected_balance_cents']}"


class TestShiftGrossVsNet:
    def _setup_three_citations_one_voided(self):
        # 2-hour RESIDENTIAL shift, three STREET_CLEAN citations, one voided.
        ctx = setup_issuing_context(
            base_fine_cents=6000, code="STREET_CLEAN", is_booting_eligible=False,
            scheduled_start="2026-03-02T08:00:00Z",
            scheduled_end="2026-03-02T10:00:00Z")
        c1 = issue_in_context(ctx, evidence_photo_url="https://ev/a.jpg")
        issue_in_context(ctx, evidence_photo_url="https://ev/b.jpg")
        issue_in_context(ctx, evidence_photo_url="https://ev/c.jpg")
        void_citation(c1["id"])
        return ctx

    def test_gross_count_includes_voided_citation(self, api):
        """PRD §3.2: "The `gross_citation_count` is the raw count of every citation
        issued during the shift, including any later voided or dismissed."

        Design: Difficulty/dual_variant_calc/shift_productivity_gross_vs_net
        """
        ctx = self._setup_three_citations_one_voided()
        shift = close_shift(ctx["shift"]["id"], ctx["officer"]["id"])
        assert shift["gross_citation_count"] == 3, \
            f"gross must count the voided citation too, got {shift['gross_citation_count']}"
        assert shift["status"] == "CLOSED"

    def test_net_count_and_per_hour_exclude_voided(self, api):
        """PRD §3.2: "The `net_citation_count` is the quality-adjusted count: every
        citation of the shift whose `status` is not `VOID` and not `DISMISSED`. The
        `citations_per_hour` divides the net count by the shift's scheduled duration
        in hours — the elapsed time from `scheduled_start` to `scheduled_end`, which
        validation guarantees is positive — and is rounded half-up to two decimal
        places; when the net count is zero, `citations_per_hour` is exactly 0.00."

        Design: Difficulty/dual_variant_calc/shift_productivity_gross_vs_net
        """
        ctx = self._setup_three_citations_one_voided()
        shift = close_shift(ctx["shift"]["id"], ctx["officer"]["id"])
        assert shift["net_citation_count"] == 2, \
            f"net must exclude the voided citation, got {shift['net_citation_count']}"
        # net 2 over a 2-hour shift -> 1.00
        assert shift["citations_per_hour"] == 1.00, \
            f"expected 1.00 citations/hour, got {shift['citations_per_hour']}"
