"""Claims: liability variants, filing windows, review cycle, close gating (PRD §3.4, §3.8)."""
from datetime import datetime

import pytest

from test_helpers import (
    ApiErrorId,
    assert_claim,
    assert_money_equal,
    file_claim,
    get_hwb,
    get_mawb,
    record_milestone,
    resolve_review_payload,
    setup_delivered,
    setup_delivered_claim,
    setup_tendered,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

CLAIM_CLOCK = "2026-08-11T12:00:00Z"
DELIVERED_UTC = "2026-08-11T09:00:00Z"


def _parse_utc(ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp for instant comparison."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestLiabilityVariants:
    def _setup_two_delivered(self):
        ctx = setup_delivered(
            hwb_specs=[
                (
                    "HWB-STD",
                    {
                        "pieces": 4,
                        "gross_weight_kg": 100.0,
                        "declared_volume_m3": 0.50,
                        "declared_value_amount": 0,
                        "declared_value_surcharge_paid": False,
                    },
                ),
                (
                    "HWB-DCL",
                    {
                        "pieces": 4,
                        "gross_weight_kg": 100.0,
                        "declared_volume_m3": 0.50,
                        "declared_value_amount": 5000.00,
                        "declared_value_surcharge_paid": True,
                    },
                ),
            ]
        )
        set_clock(CLAIM_CLOCK)
        return ctx

    def test_standard_liability_limit(self, api):
        """PRD §3.8: "Under the `STANDARD` variant, `liability_limit_amount` is the
        lesser of the `claimed_amount` and the Montreal Convention cap — 22 Special
        Drawing Rights per kilogram of the waybill's actual `gross_weight_kg`,
        converted at the fixed rate of 1.35 USD per SDR and rounded half-up to two
        decimals; the cap is independent of any declared value."

        Design: Difficulty/dual_variant_calc/standard_vs_declared_value_liability
        """
        ctx = self._setup_two_delivered()
        claim = file_claim(ctx["hwbs"][0]["id"], claim_type="DAMAGE", claimed_amount=3000.00)
        assert_claim(claim)
        assert claim["liability_basis"] == "STANDARD"
        # min(3000.00, 22 x 1.35 x 100.0 kg) = min(3000.00, 2970.00)
        assert_money_equal(claim["liability_limit_amount"], 2970.00, "liability_limit_amount")
        assert claim["status"] == "FILED"
        assert claim["review_round_count"] == 0

    def test_declared_value_liability_limit(self, api):
        """PRD §3.8: "Under the `DECLARED_VALUE` variant, the limit is simply the
        lesser of the `claimed_amount` and the waybill's `declared_value_amount` — so
        an identical claim on a surcharge-paid waybill yields a different, usually
        higher, limit."

        Design: Difficulty/dual_variant_calc/standard_vs_declared_value_liability
        """
        ctx = self._setup_two_delivered()
        claim_std = file_claim(ctx["hwbs"][0]["id"], claim_type="DAMAGE", claimed_amount=3000.00)
        claim_dcl = file_claim(ctx["hwbs"][1]["id"], claim_type="DAMAGE", claimed_amount=3000.00)
        assert claim_dcl["liability_basis"] == "DECLARED_VALUE"
        # min(3000.00, 5000.00) = 3000.00
        assert_money_equal(claim_dcl["liability_limit_amount"], 3000.00, "liability_limit_amount")
        assert claim_dcl["liability_limit_amount"] != claim_std["liability_limit_amount"], (
            "the two variants diverge on identical claim input"
        )


class TestClaimRequiresDelivered:
    def test_claim_rejected_while_in_transit(self, api, forwarder_ops_headers):
        """PRD §3.8: "Filing against a waybill that is not `DELIVERED` fails with
        `ERR_HWB_NOT_DELIVERED`."

        Design: Difficulty/cross_entity_state_dependency/claim_requires_hwb_delivered
        """
        ctx = setup_tendered()
        record_milestone(ctx["mawb"]["id"], "DEPARTED", "2026-08-10T10:00:00Z")
        assert get_hwb(ctx["hwb"]["id"])["status"] == "IN_TRANSIT"

        resp = api.create_claim(
            {"hwb_id": ctx["hwb"]["id"], "claim_type": "DAMAGE", "claimed_amount": 500.00},
            forwarder_ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_HWB_NOT_DELIVERED)

    def test_claim_succeeds_after_delivery(self, api):
        """PRD §3.6: "A `DELIVERED` event moves it `ARRIVED → DELIVERED` and delivers
        the cargo: every attached `IN_TRANSIT` waybill becomes `DELIVERED` with its
        `delivered_at_utc` stamped from the milestone's `event_time_utc`."
        PRD §3.8: "The new claim starts `FILED` with `review_round_count` at zero."

        Design: Difficulty/cross_entity_state_dependency/claim_requires_hwb_delivered
        """
        ctx = setup_delivered()
        hwb = ctx["hwb"]
        assert hwb["status"] == "DELIVERED"
        # PRD §3.6 pins the stamp's provenance ("stamped from the milestone's
        # event_time_utc"), i.e. the instant, not its lexical form — §2.4's
        # three-fractional-digit format rule covers only the system-managed
        # created_at/updated_at. Compare parsed instants.
        assert _parse_utc(hwb["delivered_at_utc"]) == _parse_utc(DELIVERED_UTC)

        set_clock(CLAIM_CLOCK)
        claim = file_claim(hwb["id"], claim_type="DAMAGE", claimed_amount=500.00)
        assert claim["status"] == "FILED"
        # STANDARD limit on 80.0 kg gross: 22 x 1.35 x 80.0 = 2376.00; 500.00 claimed
        assert_money_equal(claim["liability_limit_amount"], 500.00, "liability_limit_amount")


class TestClaimFilingDeadline:
    def _setup_two_delivered(self):
        return setup_delivered(
            hwb_specs=[
                ("HWB-A", {}),
                ("HWB-B", {"pieces": 1, "gross_weight_kg": 10.0, "declared_volume_m3": 0.05}),
            ]
        )

    def test_claim_filing_at_exact_deadline_allowed(self, api):
        """PRD §3.8: "The filing window runs from the waybill's `delivered_at_utc`:
        `DAMAGE` and `SHORTAGE` claims must be filed within 14 days of delivery,
        `DELAY` and `LOSS` claims within 21 days, and filing exactly at the deadline
        is allowed; a late filing is rejected with `ERR_CLAIM_FILING_DEADLINE_PASSED`."

        Design: Difficulty/boundary_precision_check/claim_deadline_exact_boundary
        """
        ctx = self._setup_two_delivered()
        # Delivered 2026-08-11T09:00:00Z; DAMAGE deadline is exactly +14 days
        set_clock("2026-08-25T09:00:00Z")
        claim = file_claim(ctx["hwbs"][0]["id"], claim_type="DAMAGE", claimed_amount=500.00)
        assert claim["status"] == "FILED"

    def test_claim_filing_one_second_late_rejected(self, api, forwarder_ops_headers):
        """PRD §3.8: "The filing window runs from the waybill's `delivered_at_utc`:
        `DAMAGE` and `SHORTAGE` claims must be filed within 14 days of delivery,
        `DELAY` and `LOSS` claims within 21 days, and filing exactly at the deadline
        is allowed; a late filing is rejected with `ERR_CLAIM_FILING_DEADLINE_PASSED`."

        Design: Difficulty/boundary_precision_check/claim_deadline_exact_boundary
        """
        ctx = self._setup_two_delivered()
        set_clock("2026-08-25T09:00:01Z")  # one second past the DAMAGE deadline
        resp = api.create_claim(
            {"hwb_id": ctx["hwbs"][1]["id"], "claim_type": "DAMAGE", "claimed_amount": 100.00},
            forwarder_ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_FILING_DEADLINE_PASSED)
        _rows, meta = validate_paginated(
            api.list_house_waybill_claims(ctx["hwbs"][1]["id"], forwarder_ops_headers)
        )
        assert meta["total_count"] == 0


class TestCounterofferCycle:
    def test_counteroffer_and_rebuttal_round(self, api, claims_adjuster_headers, forwarder_ops_headers):
        """PRD §3.8: "`COUNTERED` requires a `counter_amount` greater than zero and at
        most the `liability_limit_amount` — note the counteroffer is capped by the
        liability limit alone, not by the claimed amount — with the same error split
        for missing/non-positive versus over-cap values; the counter amount is stamped
        and the claim becomes `COUNTERED`."
        PRD §3.8: "Rebutting a `COUNTERED` claim sends it back to `UNDER_REVIEW` and
        increments `review_round_count` by one"

        Design: Difficulty/non_linear_state_machine/claim_counteroffer_rebuttal_cycle
        """
        ctx = setup_delivered_claim()  # DAMAGE 3000.00 on 80 kg -> limit 2376.00
        claim = ctx["claim"]

        validate_success(api.start_claim_review(claim["id"], claims_adjuster_headers))
        countered = validate_success(
            api.resolve_claim_review(
                claim["id"],
                resolve_review_payload("COUNTERED", counter_amount=1500.00),
                claims_adjuster_headers,
            )
        )
        assert countered["status"] == "COUNTERED"
        assert_money_equal(countered["counter_amount"], 1500.00, "counter_amount")

        rebuffed = validate_success(api.rebut_claim(claim["id"], forwarder_ops_headers))
        assert rebuffed["status"] == "UNDER_REVIEW"
        assert rebuffed["review_round_count"] == 1

    def test_approve_at_cap_and_settle_after_rebuttal(
        self, api, claims_adjuster_headers, forwarder_ops_headers
    ):
        """PRD §3.8: "`APPROVED` requires an `approved_amount` greater than zero and
        at most the lesser of the `claimed_amount` and the `liability_limit_amount`;
        the amount is stamped and the claim becomes `APPROVED`."
        PRD §3.8: "Independently, an `APPROVED` claim is settled by the
        `ClaimsAdjuster`, landing in `SETTLED` at its already-stamped
        `approved_amount`."

        Design: Difficulty/non_linear_state_machine/claim_counteroffer_rebuttal_cycle
        """
        ctx = setup_delivered_claim()  # DAMAGE 3000.00 on 80 kg -> limit 2376.00
        claim = ctx["claim"]

        validate_success(api.start_claim_review(claim["id"], claims_adjuster_headers))
        validate_success(
            api.resolve_claim_review(
                claim["id"],
                resolve_review_payload("COUNTERED", counter_amount=1500.00),
                claims_adjuster_headers,
            )
        )
        validate_success(api.rebut_claim(claim["id"], forwarder_ops_headers))

        approved = validate_success(
            api.resolve_claim_review(
                claim["id"],
                resolve_review_payload("APPROVED", approved_amount=2376.00),
                claims_adjuster_headers,
            )
        )
        assert approved["status"] == "APPROVED"
        assert_money_equal(approved["approved_amount"], 2376.00, "approved_amount")

        settled = validate_success(api.settle_claim(claim["id"], claims_adjuster_headers))
        assert settled["status"] == "SETTLED"
        assert_money_equal(settled["approved_amount"], 2376.00, "approved_amount")


class TestAmountCap:
    def test_approved_amount_above_liability_returns_exceeds(
        self, api, claims_adjuster_headers
    ):
        """PRD §3.8: "`APPROVED` requires an `approved_amount` greater than zero and
        at most the lesser of the `claimed_amount` and the `liability_limit_amount`;
        the amount is stamped and the claim becomes `APPROVED`. A missing or
        non-positive amount is `ERR_INVALID_REQUEST`; an amount above the cap is
        `ERR_AMOUNT_EXCEEDS_LIABILITY`."

        Design: Corner/validations/approved_amount_above_liability_returns_exceeds
        """
        ctx = setup_delivered_claim()  # limit 2376.00, claimed 3000.00
        claim = ctx["claim"]
        validate_success(api.start_claim_review(claim["id"], claims_adjuster_headers))

        over = api.resolve_claim_review(
            claim["id"],
            resolve_review_payload("APPROVED", approved_amount=2400.00),
            claims_adjuster_headers,
        )
        validate_error(over, ApiErrorId.ERR_AMOUNT_EXCEEDS_LIABILITY)
        staying = validate_success(api.get_claim(claim["id"], claims_adjuster_headers))
        assert staying["status"] == "UNDER_REVIEW", (
            "a rejected decision must leave the claim in review"
        )

        at_cap = validate_success(
            api.resolve_claim_review(
                claim["id"],
                resolve_review_payload("APPROVED", approved_amount=2376.00),
                claims_adjuster_headers,
            )
        )
        assert at_cap["status"] == "APPROVED"
        assert_money_equal(at_cap["approved_amount"], 2376.00, "approved_amount")


class TestOpenClaimGuards:
    def test_duplicate_open_claim_rejected(self, api, forwarder_ops_headers):
        """PRD §3.8: "And only one open claim may exist per waybill: if another claim
        on the same waybill sits in `FILED`, `UNDER_REVIEW`, `COUNTERED`, or
        `APPROVED`, the filing fails with `ERR_DUPLICATE_OPEN_CLAIM`."

        Design: Corner/validations/duplicate_open_claim_rejected
        """
        ctx = setup_delivered_claim(claim_overrides={"claimed_amount": 500.00})
        resp = api.create_claim(
            {"hwb_id": ctx["hwb"]["id"], "claim_type": "DELAY", "claimed_amount": 100.00},
            forwarder_ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_OPEN_CLAIM)
        _rows, meta = validate_paginated(
            api.list_house_waybill_claims(ctx["hwb"]["id"], forwarder_ops_headers)
        )
        assert meta["total_count"] == 1

    def test_open_claim_blocks_mawb_close(
        self, api, capacity_planner_headers, claims_adjuster_headers
    ):
        """PRD §3.4: "Closing is the happy ending: a `CapacityPlanner` closes a
        `DELIVERED` master waybill to terminal `CLOSED`, but only when no claim on any
        attached waybill sits in `FILED`, `UNDER_REVIEW`, `COUNTERED`, or `APPROVED`;
        open claims block the close with `ERR_OPEN_CLAIMS_EXIST`."

        Design: Corner/validations/open_claim_blocks_mawb_close
        """
        ctx = setup_delivered_claim(claim_overrides={"claimed_amount": 500.00})
        claim = ctx["claim"]

        blocked = api.close_master_waybill(ctx["mawb"]["id"], capacity_planner_headers)
        validate_error(blocked, ApiErrorId.ERR_OPEN_CLAIMS_EXIST)
        assert get_mawb(ctx["mawb"]["id"])["status"] == "DELIVERED"

        validate_success(api.start_claim_review(claim["id"], claims_adjuster_headers))
        validate_success(
            api.resolve_claim_review(
                claim["id"],
                resolve_review_payload("DENIED", reason="no exterior damage noted at delivery"),
                claims_adjuster_headers,
            )
        )
        closed = validate_success(
            api.close_master_waybill(ctx["mawb"]["id"], capacity_planner_headers)
        )
        assert closed["status"] == "CLOSED", "a terminal (DENIED) claim no longer blocks close"
