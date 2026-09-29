"""Inclusive-boundary arithmetic on two unrelated thresholds.

The outreach-tier boundary is inclusive on the *rounded* ownership percentage, so
9,999 of 1,000,000 shares stays in the third tier while exactly 10,000 crosses
into the second; and the consensus staleness cutoff is inclusive on its lower
bound, so an estimate stamped exactly 90 days before the logical clock is still
eligible while one day more collapses the eligible set to empty.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    IR_ADMIN,
    IR_ANALYST,
    assertions,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_START = "2026-08-01T00:00:00Z"


def _build_boundary_register(api: ApiClient):
    """An issuer of exactly 1,000,000 shares and one holder sitting at 5,000."""
    fixtures.set_clock(api, CLOCK_START)
    company = fixtures.create_company(
        api,
        ticker="BND",
        legal_name="Boundary Numerics Inc",
        shares_outstanding=1000000,
    )
    holder = fixtures.create_holder(
        api,
        company["id"],
        5000,
        display_name="Boundary Holder",
        email="bnd@funds.test",
    )
    return company, holder


class TestOwnershipPctTierBoundary:
    """PATCH /contacts/{id}/position across the one-percent tier boundary."""

    def test_position_of_9999_shares_rounds_to_0_9999_and_stays_in_tier_three(
        self, api: ApiClient
    ):
        """One share short of the boundary rounds to 0.9999 and is still TIER_3.

        PRD §3.2: "On creation, and again on every position update, the system divides
        the contact's `shares_held` by the issuer's `shares_outstanding` as stored at
        that moment, multiplies the quotient by 100, and rounds the result half up to 4
        decimal places to obtain `ownership_pct`."
        PRD §3.2: "From that rounded figure — never from the raw quotient — it derives
        the outreach tier stored in `target_tier`, evaluated top to bottom with the first
        matching clause winning: a percentage of at least 5.0 is `TIER_1`; otherwise a
        percentage of at least 1.0 is `TIER_2`; otherwise any percentage strictly greater
        than zero is `TIER_3`; and a percentage of exactly zero is `UNTIERED`."

        Design: Difficulty/boundary_precision_check/ownership_pct_exactly_one_percent_lands_in_tier_two
        """
        company, holder = _build_boundary_register(api)
        first_version = fixtures.company_version(api, company["id"])
        assert first_version == 1, "registration begins the issuer's version at 1"

        patched = validate_success(
            api.update_position(
                holder["id"],
                factories.position_payload(9999, first_version),
                IR_ADMIN,
            )
        )
        assertions.assert_contact(
            patched, shares_held=9999, target_tier="TIER_3", threat_level="NONE"
        )
        assert patched["ownership_pct"] == assertions.approx_4dp(0.9999)
        assertions.assert_version(patched, 2, "Contact")

        stored = fixtures.read_contact(api, holder["id"])
        assertions.assert_contact(stored, shares_held=9999, target_tier="TIER_3")
        assert stored["ownership_pct"] == assertions.approx_4dp(0.9999)
        assertions.assert_version(
            fixtures.read_company(api, company["id"]), 2, "Company"
        )

    def test_position_of_exactly_ten_thousand_shares_lands_in_tier_two(
        self, api: ApiClient
    ):
        """Exactly 1.0000 percent crosses into TIER_2 because the low side is inclusive.

        PRD §3.2: "Both tier boundaries are inclusive on their low side, so exactly
        1.0000 is `TIER_2` and exactly 5.0000 is `TIER_1`, while a holder of no shares is
        `UNTIERED` and never `TIER_3`."
        PRD §3.2: "A position write that survives every check re-derives `ownership_pct`
        and `target_tier`, then re-derives the issuer's `disclosure_posture` and stamps
        `posture_recomputed_at`, incrementing both the contact's `version` and the
        issuer's `version` by 1."

        Design: Difficulty/boundary_precision_check/ownership_pct_exactly_one_percent_lands_in_tier_two
        """
        company, holder = _build_boundary_register(api)

        validate_success(
            api.update_position(
                holder["id"],
                factories.position_payload(9999, fixtures.company_version(api, company["id"])),
                IR_ADMIN,
            )
        )
        patched = validate_success(
            api.update_position(
                holder["id"],
                factories.position_payload(10000, fixtures.company_version(api, company["id"])),
                IR_ADMIN,
            )
        )
        assertions.assert_contact(
            patched, shares_held=10000, target_tier="TIER_2", threat_level="NONE"
        )
        assert patched["ownership_pct"] == assertions.approx_4dp(1.0000)
        assertions.assert_version(patched, 3, "Contact")

        stored = fixtures.read_contact(api, holder["id"])
        assertions.assert_contact(stored, target_tier="TIER_2", threat_level="NONE")
        assert stored["ownership_pct"] == assertions.approx_4dp(1.0000)
        assertions.assert_version(
            fixtures.read_company(api, company["id"]), 3, "Company"
        )


def _build_single_estimate_world(api: ApiClient):
    """One granted, covering analyst with a single EPS/FY2026 filing at the epoch clock."""
    fixtures.set_clock(api, CLOCK_START)
    company = fixtures.create_company(
        api,
        ticker="STL",
        legal_name="Staleness Boundary Corp",
        shares_outstanding=1000000,
    )
    analyst = fixtures.create_granted_analyst(
        api,
        company["id"],
        display_name="Stale Analyst",
        email="stl@banks.test",
    )
    estimate = fixtures.file_estimate(
        api, analyst["id"], 2.00, metric="EPS", period_label="FY2026"
    )
    assertions.assert_estimate(estimate, status="ACCEPTED")
    assertions.assert_ts_equals(estimate["submitted_at"], CLOCK_START, "submitted_at")
    return company, analyst, estimate


class TestConsensusNinetyDayWindowBoundary:
    """GET /companies/{id}/consensus across the inclusive staleness cutoff."""

    def test_estimate_exactly_ninety_days_old_is_still_eligible(self, api: ApiClient):
        """The lower bound is inclusive, so the 90-day-old filing still counts.

        PRD §3.7: "A submission is eligible when all of the following hold together: its
        own `status` is `ACCEPTED`; the contact that filed it belongs to the issuer being
        read; that contact's `contact_type` is `SELL_SIDE_ANALYST`; that contact's
        `coverage_status` is `INITIATED`; that contact's `model_access_status` is anything
        other than `REVOKED`; its `metric` equals the requested metric; its
        `period_label` equals the requested period; and its `submitted_at` is at or after
        the logical clock's current instant minus 90 days, the lower bound being
        inclusive."
        PRD §3.7: "If no such row exists, `guidance_anchored` is false and the same
        fifteen-percent margins are applied to `simple_mean` instead: `band_low` is
        `simple_mean` multiplied by 0.85 and `band_high` is `simple_mean` multiplied by
        1.15, each rounded half up to 4 decimal places."
        PRD §3.7: "Finally, `dispersion_pct` is the spread of the kept values relative to
        the reported consensus: the largest kept value minus the smallest kept value,
        divided by `consensus_mean`, multiplied by 100 and rounded half up to 2 decimal
        places."

        Design: Difficulty/boundary_precision_check/consensus_ninety_day_window_boundary_and_empty_eligible_set
        """
        company, analyst, estimate = _build_single_estimate_world(api)
        fixtures.set_clock(api, "2026-10-30T00:00:00Z")

        payload = validate_success(
            api.get_consensus(company["id"], "EPS", "FY2026", None, IR_ANALYST)
        )
        assertions.assert_consensus(
            payload,
            company_id=company["id"],
            metric="EPS",
            period_label="FY2026",
            variant="ANCHORED",
            eligible_count=1,
            guidance_anchored=False,
            outlier_excluded_count=0,
            trimmed_applied=True,
        )
        assert payload["simple_mean"] == assertions.approx_4dp(2.0000)
        assert payload["consensus_mean"] == assertions.approx_4dp(2.0000)
        assert payload["band_low"] == assertions.approx_4dp(1.7000)
        assert payload["band_high"] == assertions.approx_4dp(2.3000)
        assert payload["dispersion_pct"] == assertions.approx_2dp(0.00)

    def test_one_day_past_the_window_empties_the_eligible_set(self, api: ApiClient):
        """One day beyond the cutoff the read fails outright with no partial payload.

        PRD §3.7: "If the set is empty the whole read fails with
        `ERR_NO_ELIGIBLE_ESTIMATES` and no partial payload is returned."
        PRD §3.3: "Revocation is deliberately non-destructive to history: estimate
        submissions that analyst has already filed keep their `ACCEPTED` status untouched,
        but for as long as `model_access_status` remains `REVOKED` those rows fall out of
        the consensus eligible set described in §3.7 — so revoking access silently changes
        what the consensus read reports without deleting a single row."

        Design: Difficulty/boundary_precision_check/consensus_ninety_day_window_boundary_and_empty_eligible_set
        """
        company, analyst, estimate = _build_single_estimate_world(api)
        fixtures.set_clock(api, "2026-10-31T00:00:00Z")

        error = validate_error(
            api.get_consensus(company["id"], "EPS", "FY2026", None, IR_ANALYST),
            ApiErrorId.NO_ELIGIBLE_ESTIMATES.value,
        )
        assert set(error.keys()) == {"error_id", "message"}, (
            "an error body carries only error_id and message, never a partial consensus"
        )

        rows, meta = validate_paginated(
            api.list_contact_estimates(analyst["id"], IR_ANALYST)
        )
        assert meta["total_count"] == 1
        assertions.assert_estimate(rows[0], id=estimate["id"], status="ACCEPTED")
