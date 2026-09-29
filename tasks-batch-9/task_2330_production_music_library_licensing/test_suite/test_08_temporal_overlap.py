"""Interval occupation on two different resources.

A work's exclusive block is a closed occupation extended by the governing
agreement's holdback, so a term starting on the block day itself is still
refused. A licensee's blanket coverage is a half-open interval with no buffer,
so a coverage starting exactly where the incumbent ends does not collide.
"""

from test_helpers import (
    Deal,
    LICENSING_AGENT,
    accept_sync_request,
    assert_blanket_axes,
    assert_created,
    assert_declared_error,
    assert_final_figures,
    assert_ok,
    assert_page,
    assert_same_instant,
    assert_status,
    composition_version,
    issue_per_use_license,
    new_cataloged_work,
    new_draft_blanket,
    new_licensee,
    new_tier,
    quote_sync_request,
    read_blanket_agreement,
    read_composition,
    review_sync_request,
    submit_sync_request,
)
from test_helpers import factories as build
from test_helpers.api_errors import (
    ERR_BLANKET_COVERAGE_OVERLAP,
    ERR_COVERAGE_DATES_INVALID,
    ERR_EXCLUSIVE_WINDOW_CONFLICT,
)

# The exclusive licence runs 2026-09-01 for 24 calendar months, so its term_end
# is 2028-08-31 and the 90-day holdback carries the work's block to 2028-11-29.
EXCLUSIVE_TERM_START = "2026-09-01T00:00:00Z"
EXCLUSIVE_TERM_END = "2028-08-31T00:00:00Z"
BLOCK_DAY = "2028-11-29T00:00:00Z"
DAY_AFTER_BLOCK = "2028-11-30T00:00:00Z"
FREE_TERM_END = "2029-11-29T00:00:00Z"

INCUMBENT_COVERAGE_START = "2026-08-01T00:00:00Z"
INCUMBENT_COVERAGE_END = "2027-08-01T00:00:00Z"
ADJACENT_COVERAGE_END = "2028-08-01T00:00:00Z"
ONE_DAY_EARLIER_START = "2027-07-31T00:00:00Z"
ONE_DAY_EARLIER_END = "2028-07-31T00:00:00Z"
DEGENERATE_DAY = "2029-01-01T00:00:00Z"


def _accepted_request(api, work, tier, licensee, **overrides) -> Deal:
    """Carry one request SUBMITTED -> UNDER_REVIEW -> QUOTED -> ACCEPTED."""
    deal = Deal(work, tier, licensee)
    submit_sync_request(api, deal, **overrides)
    review_sync_request(api, deal)
    quote_sync_request(api, deal, 14)
    return accept_sync_request(api, deal)


def _work_blocked_by_an_exclusive_licence(api):
    """One work under an EXCLUSIVE agreement with a 90-day holdback.

    An exclusive per-use licence is issued for 2026-09-01 over 24 months, and
    two further non-exclusive requests are then accepted on the same work: one
    asking for a term that starts on the resulting block day and one asking for
    the day after it.
    """
    work = new_cataloged_work(
        api,
        composer_overrides={"display_name": "Lucia Ferrer", "pro_affiliation": "SESAC"},
        agreement_overrides={
            "exclusivity": "EXCLUSIVE",
            "holdback_days": 90,
            "sync_fee_share_pct": 40.00,
        },
        title="Vela",
        duration_sec=195,
        tempo_bpm=132,
        genre="ROCK",
        mood_tags=["EPIC", "TENSE"],
        instrumentation=["GUITAR", "PERCUSSION"],
    )
    tier = new_tier(
        api,
        media_type="BROADCAST_TV",
        base_rate_cents=300000,
        allowed_scales=["LOCAL", "NATIONAL", "WORLDWIDE"],
        min_term_months=1,
        max_term_months=120,
    )
    licensee = new_licensee(
        api, legal_name="Vela Rights Co", licensee_type="AGENCY", credit_limit_cents=5000000
    )

    exclusive = _accepted_request(
        api,
        work,
        tier,
        licensee,
        requested_term_start=EXCLUSIVE_TERM_START,
        requested_term_months=24,
        exclusive_requested=True,
    )
    issue_per_use_license(api, exclusive)

    on_block = _accepted_request(
        api,
        work,
        tier,
        licensee,
        requested_term_start=BLOCK_DAY,
        requested_term_months=12,
        exclusive_requested=False,
    )
    after_block = _accepted_request(
        api,
        work,
        tier,
        licensee,
        requested_term_start=DAY_AFTER_BLOCK,
        requested_term_months=12,
        exclusive_requested=False,
    )
    return {
        "work": work,
        "tier": tier,
        "licensee": licensee,
        "exclusive": exclusive,
        "on_block": on_block,
        "after_block": after_block,
    }


class TestExclusiveHoldbackBlockDay:
    def test_holdback_carries_the_block_past_the_inclusive_last_day_of_the_term(self, api):
        """PRD §3.5: "`exclusive_block_until` equals `term_end` plus the governing
        agreement's `holdback_days` days when `is_exclusive` is true, and equals
        `term_end` exactly when it is false."

        Design: Difficulty/resource_temporal_overlap/exclusive_holdback_block_day_inclusive_on_composition
        """
        ground = _work_blocked_by_an_exclusive_licence(api)
        license_row = ground["exclusive"].license

        assert license_row["is_exclusive"] is True
        assert_same_instant(license_row["term_start"], EXCLUSIVE_TERM_START)
        assert_same_instant(license_row["term_end"], EXCLUSIVE_TERM_END)
        assert_same_instant(license_row["exclusive_block_until"], BLOCK_DAY)
        assert_final_figures(license_row, 933075, 5.00, 886421)

        composition = read_composition(api, ground["work"].composition_id)
        assert_same_instant(composition["exclusive_block_until"], BLOCK_DAY)
        assert composition["active_license_count"] == 1

    def test_a_term_starting_on_the_block_day_is_refused(self, api):
        """PRD §3.5: "The exclusivity window must be free: when the work's
        `exclusive_block_until` is not null and the new `term_start` falls on or
        before it, issuance is refused with `ERR_EXCLUSIVE_WINDOW_CONFLICT` — the
        block day itself is still blocked."

        Design: Difficulty/resource_temporal_overlap/exclusive_holdback_block_day_inclusive_on_composition
        """
        ground = _work_blocked_by_an_exclusive_licence(api)
        on_block = ground["on_block"]

        assert_declared_error(
            api.create_license(
                build.per_use_license_payload(
                    on_block.sync_request_id,
                    composition_version(api, ground["work"].composition_id),
                ),
                LICENSING_AGENT,
            ),
            ERR_EXCLUSIVE_WINDOW_CONFLICT,
        )

        refused = assert_ok(api.get_sync_request(on_block.sync_request_id, LICENSING_AGENT))
        assert_status(refused, "ACCEPTED")
        assert refused["license_id"] is None
        composition = read_composition(api, ground["work"].composition_id)
        assert composition["active_license_count"] == 1
        assert_same_instant(composition["exclusive_block_until"], BLOCK_DAY)

    def test_a_term_starting_the_day_after_the_block_is_issued(self, api):
        """PRD §3.5: "The exclusivity window must be free: when the work's
        `exclusive_block_until` is not null and the new `term_start` falls on or
        before it, issuance is refused with `ERR_EXCLUSIVE_WINDOW_CONFLICT` — the
        block day itself is still blocked."

        Design: Difficulty/resource_temporal_overlap/exclusive_holdback_block_day_inclusive_on_composition
        """
        ground = _work_blocked_by_an_exclusive_licence(api)

        license_row = assert_created(
            api.create_license(
                build.per_use_license_payload(
                    ground["after_block"].sync_request_id,
                    composition_version(api, ground["work"].composition_id),
                ),
                LICENSING_AGENT,
            )
        )

        assert_same_instant(license_row["term_start"], DAY_AFTER_BLOCK)
        assert_same_instant(license_row["term_end"], FREE_TERM_END)
        assert license_row["is_exclusive"] is False
        assert_same_instant(license_row["exclusive_block_until"], FREE_TERM_END)
        assert_final_figures(license_row, 1276421, 5.00, 370500)

        composition = read_composition(api, ground["work"].composition_id)
        assert composition["active_license_count"] == 2
        # Only exclusive licences feed the work's block, so the non-exclusive
        # issuance leaves it where the holdback put it.
        assert_same_instant(composition["exclusive_block_until"], BLOCK_DAY)

    def test_the_refused_issuance_leaves_the_version_token_spendable(self, api):
        """PRD §2.10: "Every successful issuance increments the composition's
        `version`."

        Design: Difficulty/resource_temporal_overlap/exclusive_holdback_block_day_inclusive_on_composition
        """
        ground = _work_blocked_by_an_exclusive_licence(api)
        composition_id = ground["work"].composition_id
        token = composition_version(api, composition_id)

        assert_declared_error(
            api.create_license(
                build.per_use_license_payload(ground["on_block"].sync_request_id, token),
                LICENSING_AGENT,
            ),
            ERR_EXCLUSIVE_WINDOW_CONFLICT,
        )
        assert composition_version(api, composition_id) == token

        assert_created(
            api.create_license(
                build.per_use_license_payload(ground["after_block"].sync_request_id, token),
                LICENSING_AGENT,
            )
        )
        assert composition_version(api, composition_id) == token + 1


def _licensee_with_incumbent_coverage(api):
    """One licensee whose only blanket agreement sits in DRAFT coverage.

    Its interval runs from 2026-08-01 up to but not including 2027-08-01, and a
    DRAFT agreement still occupies the interval it declares.
    """
    licensee = new_licensee(
        api,
        legal_name="Rivergate Networks",
        licensee_type="BROADCASTER",
        credit_limit_cents=20000000,
    )
    blanket = new_draft_blanket(
        api,
        licensee,
        coverage_start=INCUMBENT_COVERAGE_START,
        coverage_end=INCUMBENT_COVERAGE_END,
        annual_fee_cents=4800000,
        reporting_cadence="MONTHLY",
        usage_cap_minutes=120,
        pool_share_pct=25.00,
    )
    return blanket


def _coverage_payload(licensee_id, coverage_start, coverage_end, **overrides):
    return build.blanket_agreement_payload(
        licensee_id,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        annual_fee_cents=5000000,
        usage_cap_minutes=150,
        pool_share_pct=30.00,
        **overrides,
    )


class TestBlanketCoverageHalfOpenAdjacency:
    def test_coverage_starting_where_the_incumbent_ends_is_accepted(self, api):
        """PRD §3.6: "Coverage may not overlap: if another agreement for the same
        licensee whose `coverage_status` is `DRAFT` or `ACTIVE` has a coverage
        interval overlapping the new one, creation is refused with
        `ERR_BLANKET_COVERAGE_OVERLAP`; because the intervals are half-open, an
        agreement ending exactly where the next begins does not overlap it."

        Design: Difficulty/resource_temporal_overlap/blanket_coverage_half_open_adjacency_on_licensee
        """
        blanket = _licensee_with_incumbent_coverage(api)

        adjacent = assert_created(
            api.create_blanket_agreement(
                _coverage_payload(
                    blanket.licensee_id,
                    INCUMBENT_COVERAGE_END,
                    ADJACENT_COVERAGE_END,
                    reporting_cadence="QUARTERLY",
                ),
                LICENSING_AGENT,
            )
        )

        assert_same_instant(adjacent["coverage_start"], INCUMBENT_COVERAGE_END)
        assert_same_instant(adjacent["coverage_end"], ADJACENT_COVERAGE_END)
        assert_blanket_axes(adjacent, "DRAFT", "COMPLIANT")

    def test_coverage_starting_one_day_before_the_incumbent_ends_collides(self, api):
        """PRD §3.6: "Coverage may not overlap: if another agreement for the same
        licensee whose `coverage_status` is `DRAFT` or `ACTIVE` has a coverage
        interval overlapping the new one, creation is refused with
        `ERR_BLANKET_COVERAGE_OVERLAP`; because the intervals are half-open, an
        agreement ending exactly where the next begins does not overlap it."

        Design: Difficulty/resource_temporal_overlap/blanket_coverage_half_open_adjacency_on_licensee
        """
        blanket = _licensee_with_incumbent_coverage(api)

        assert_declared_error(
            api.create_blanket_agreement(
                _coverage_payload(
                    blanket.licensee_id, ONE_DAY_EARLIER_START, ONE_DAY_EARLIER_END
                ),
                LICENSING_AGENT,
            ),
            ERR_BLANKET_COVERAGE_OVERLAP,
        )

        incumbent = read_blanket_agreement(api, blanket.agreement_id)
        assert_blanket_axes(incumbent, "DRAFT", "COMPLIANT")
        assert_same_instant(incumbent["coverage_start"], INCUMBENT_COVERAGE_START)
        assert_same_instant(incumbent["coverage_end"], INCUMBENT_COVERAGE_END)

    def test_a_degenerate_coverage_interval_fails_on_its_ordering(self, api):
        """PRD §3.6: "A `coverage_end` at or before `coverage_start` is refused with
        `ERR_COVERAGE_DATES_INVALID`."

        Design: Difficulty/resource_temporal_overlap/blanket_coverage_half_open_adjacency_on_licensee
        """
        blanket = _licensee_with_incumbent_coverage(api)

        assert_declared_error(
            api.create_blanket_agreement(
                _coverage_payload(blanket.licensee_id, DEGENERATE_DAY, DEGENERATE_DAY),
                LICENSING_AGENT,
            ),
            ERR_COVERAGE_DATES_INVALID,
        )

    def test_only_the_adjacent_coverage_survives_the_three_attempts(self, api):
        """PRD §3.6: "Coverage may not overlap: if another agreement for the same
        licensee whose `coverage_status` is `DRAFT` or `ACTIVE` has a coverage
        interval overlapping the new one, creation is refused with
        `ERR_BLANKET_COVERAGE_OVERLAP`; because the intervals are half-open, an
        agreement ending exactly where the next begins does not overlap it."

        Design: Difficulty/resource_temporal_overlap/blanket_coverage_half_open_adjacency_on_licensee
        """
        blanket = _licensee_with_incumbent_coverage(api)

        adjacent = assert_created(
            api.create_blanket_agreement(
                _coverage_payload(
                    blanket.licensee_id,
                    INCUMBENT_COVERAGE_END,
                    ADJACENT_COVERAGE_END,
                    reporting_cadence="QUARTERLY",
                ),
                LICENSING_AGENT,
            )
        )
        assert_declared_error(
            api.create_blanket_agreement(
                _coverage_payload(
                    blanket.licensee_id, ONE_DAY_EARLIER_START, ONE_DAY_EARLIER_END
                ),
                LICENSING_AGENT,
            ),
            ERR_BLANKET_COVERAGE_OVERLAP,
        )
        assert_declared_error(
            api.create_blanket_agreement(
                _coverage_payload(blanket.licensee_id, DEGENERATE_DAY, DEGENERATE_DAY),
                LICENSING_AGENT,
            ),
            ERR_COVERAGE_DATES_INVALID,
        )

        rows, meta = assert_page(
            api.list_blanket_agreements(
                {"licensee_id": blanket.licensee_id, "limit": 100}, LICENSING_AGENT
            )
        )
        assert meta["total_count"] == 2
        assert [row["id"] for row in rows] == [blanket.agreement_id, adjacent["id"]]
