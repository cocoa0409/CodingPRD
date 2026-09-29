"""Cascades that travel three or four hops from a single request.

One delivery bumps a counter, re-runs the tier gate and rewrites the roster's
commission rate; one upheld claim adds a strike, collapses a credit posture and
blocks exactly the inquiries the specification says it may block.
"""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    AGENT_HEADERS,
    ApiErrorId,
    add_second_engagement_for_speaker,
    circumvention_claim_payload,
    claim_resolution_payload,
    create_inquiry,
    qualify_inquiry,
    qualify_payload,
    read_claim,
    read_client,
    read_engagement,
    read_inquiry,
    read_speaker,
    round_half_up,
    setup_delivered_engagement_with_feedback,
    setup_two_delivered_engagements,
    setup_upheld_claim,
    validate_error,
    validate_paginated,
    validate_success,
)

TOP_FEEDBACK = {"content_score": 5, "logistics_score": 5}


class TestDeliveryRetiersTheRoster:
    def test_one_delivery_is_not_enough_to_clear_the_silver_gate(self, api):
        """A perfect rolling score still leaves a speaker bronze while only one engagement has been delivered.

        PRD: Both conditions of a tier must hold and the highest satisfied tier wins: `GOLD` requires `engagements_delivered_count` of at least 4 **and** a `rolling_score` of at least 4.50; `SILVER` requires `engagements_delivered_count` of at least 2 **and** a `rolling_score` of at least 4.00; otherwise the speaker is `BRONZE`, and a speaker whose `rolling_score` is still null is always `BRONZE`.
        Design: Difficulty/transitive_cascade/transitive_delivery_promotes_tier_and_rewrites_commission_rate
        """
        bundle = setup_delivered_engagement_with_feedback(
            api, feedback_overrides=TOP_FEEDBACK
        )
        speaker = read_speaker(api, bundle["speaker"]["id"])

        assert speaker["engagements_delivered_count"] == 1
        assert speaker["rolling_score"] == pytest.approx(5.00, abs=0.01)
        assert speaker["roster_tier"] == "BRONZE"
        assert speaker["default_commission_pct"] == pytest.approx(0.25, abs=0.001)
        assert speaker["lifetime_gross_fees_cents"] == 1_275_000

    def test_the_second_delivery_promotes_the_tier_and_rewrites_the_roster_rate(
        self, api
    ):
        """The delivery counter reaching two re-runs the tier gate, which rewrites the roster commission rate to the silver one.

        PRD: Sixth, and this is the four-hop roster cascade: the speaker's `engagements_delivered_count` rises by one and `lifetime_gross_fees_cents` rises by `quoted_fee_cents` plus `recording_fee_cents`; because the delivered count changed, the tiering rule of §3.9 re-runs and may move `roster_tier`; and because `roster_tier` may have moved, the speaker's `default_commission_pct` is rewritten to the rate implied by the new tier.
        Design: Difficulty/transitive_cascade/transitive_delivery_promotes_tier_and_rewrites_commission_rate
        """
        bundle = setup_two_delivered_engagements(api, first_feedback=TOP_FEEDBACK)
        speaker = read_speaker(api, bundle["speaker"]["id"])

        assert speaker["engagements_delivered_count"] == 2
        assert speaker["lifetime_gross_fees_cents"] == 2_550_000
        assert speaker["rolling_score"] == pytest.approx(5.00, abs=0.01)
        assert speaker["roster_tier"] == "SILVER"
        assert speaker["default_commission_pct"] == pytest.approx(0.22, abs=0.001)

    def test_engagements_contracted_before_the_promotion_keep_their_own_rate(
        self, api
    ):
        """Both engagements were executed at the bronze rate, so neither is re-priced by the promotion.

        PRD: Engagements already contracted keep their own `commission_pct_snapshot` untouched — only agreements executed after the change pick up the new rate.
        Design: Difficulty/transitive_cascade/transitive_delivery_promotes_tier_and_rewrites_commission_rate
        """
        bundle = setup_two_delivered_engagements(api, first_feedback=TOP_FEEDBACK)

        first = read_engagement(api, bundle["engagement"]["id"])
        second = read_engagement(api, bundle["engagement_2"]["id"])

        assert first["commission_pct_snapshot"] == pytest.approx(0.25, abs=0.001)
        assert second["commission_pct_snapshot"] == pytest.approx(0.25, abs=0.001)
        assert second["final_commission_cents"] == 318_750
        assert second["final_commission_cents"] == round_half_up(1_275_000 * 0.25)
        assert read_speaker(api, bundle["speaker"]["id"])[
            "default_commission_pct"
        ] == pytest.approx(0.22, abs=0.001)


class TestUpheldClaimsCollapseCreditPosture:
    def _third_qualified_inquiry(self, api, bundle):
        inquiry = create_inquiry(
            api,
            bundle["client"],
            event_start_utc="2027-03-10T16:00:00Z",
            event_end_utc="2027-03-10T18:00:00Z",
        )
        return qualify_inquiry(api, inquiry["id"])

    def _second_upheld_claim(self, api, bundle):
        bundle = add_second_engagement_for_speaker(
            api,
            bundle,
            event_start_utc="2026-11-20T16:00:00Z",
            event_end_utc="2026-11-20T18:00:00Z",
            valid_until_utc="2026-10-30T00:00:00Z",
            setup_clock_utc="2026-10-16T00:00:00Z",
        )
        blocked_candidate = self._third_qualified_inquiry(api, bundle)
        claim = validate_success(
            api.create_circumvention_claim(
                circumvention_claim_payload(
                    bundle["client"]["id"],
                    bundle["speaker"]["id"],
                    bundle["engagement_2"]["id"],
                    "2026-12-20T18:00:00Z",
                    1_000_000,
                ),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        validate_success(
            api.resolve_circumvention_claim(
                claim["id"], claim_resolution_payload("UPHOLD"), ADMIN_HEADERS
            )
        )
        bundle["claim_2"] = read_claim(api, claim["id"])
        bundle["blocked_candidate"] = blocked_candidate
        return bundle

    def test_the_first_uphold_counts_a_strike_without_touching_the_credit_posture(
        self, api
    ):
        """One upheld claim is priced at the source engagement's pinned rate and leaves the client's credit good.

        PRD: `commission_due_cents` is `direct_fee_cents` multiplied by the source engagement's `commission_pct_snapshot` multiplied by `protection_factor`, that single triple product rounded half up to a whole number of cents.
        Design: Difficulty/transitive_cascade/transitive_upheld_claim_holds_credit_and_blocks_qualified_inquiry
        """
        bundle = setup_upheld_claim(
            api,
            direct_event_date_utc="2026-12-14T18:00:00Z",
            direct_fee_cents=1_000_000,
        )
        claim = bundle["claim"]

        assert claim["status"] == "UPHELD"
        assert claim["protection_factor"] == pytest.approx(1.00, abs=0.001)
        assert claim["commission_due_cents"] == 250_000
        assert claim["commission_due_cents"] == round_half_up(
            1_000_000 * 0.25 * 1.00
        )

        client_row = read_client(api, bundle["client"]["id"])
        assert client_row["circumvention_strikes"] == 1
        assert client_row["credit_status"] == "GOOD"

        rows, _meta = validate_paginated(
            api.list_inquiries(
                AGENT_HEADERS,
                params={"client_id": client_row["id"], "status": "BLOCKED"},
            )
        )
        assert rows == []

    def test_the_second_uphold_holds_the_credit_and_blocks_only_qualified_inquiries(
        self, api
    ):
        """Two strikes collapse the posture to hold, and exactly the one qualified inquiry is blocked while the won ones are untouched.

        PRD: `UPHOLD` also requires the claim to be `OPEN`, drives `OPEN → UPHELD`, and sets off a four-hop cascade: the client's `circumvention_strikes` rises by one; upon reaching the threshold of 2 strikes the client's `credit_status` becomes `HOLD`; and because the posture became `HOLD`, every inquiry of that client whose `status` is `QUALIFIED` moves to `BLOCKED` — leaving inquiries in `RECEIVED` or `PROPOSED` alone, as noted in §3.2.
        Design: Difficulty/transitive_cascade/transitive_upheld_claim_holds_credit_and_blocks_qualified_inquiry
        """
        bundle = setup_upheld_claim(
            api,
            direct_event_date_utc="2026-12-14T18:00:00Z",
            direct_fee_cents=1_000_000,
        )
        bundle = self._second_upheld_claim(api, bundle)

        assert bundle["claim_2"]["status"] == "UPHELD"
        assert bundle["claim_2"]["protection_factor"] == pytest.approx(1.00, abs=0.001)
        assert bundle["claim_2"]["commission_due_cents"] == 250_000

        client_row = read_client(api, bundle["client"]["id"])
        assert client_row["circumvention_strikes"] == 2
        assert client_row["credit_status"] == "HOLD"

        rows, _meta = validate_paginated(
            api.list_inquiries(
                AGENT_HEADERS,
                params={"client_id": client_row["id"], "status": "BLOCKED"},
            )
        )
        assert len(rows) == 1
        assert rows[0]["id"] == bundle["blocked_candidate"]["id"]

        assert read_inquiry(api, bundle["inquiry"]["id"])["status"] == "WON"
        assert read_inquiry(api, bundle["inquiry_2"]["id"])["status"] == "WON"

    def test_a_blocked_inquiry_can_no_longer_be_qualified(self, api):
        """Qualification is refused on the blocked inquiry because BLOCKED is not a declared source state for it.

        PRD: The target resource sits in a status from which the requested transition is declared: `status` on an inquiry for qualification and for opening a proposal round; `status` on a proposal for presentation, revision request, decline and selection; `booking_status` on an engagement for confirmation, speaker decline, contract drafting, delivery, cancellation, travel-expense submission and commission adjustment; `status` on a contract for sending and signing; `status` on a travel expense for approval and rejection; `status` on an invoice for payment and void; `status` on a remittance for payout; `status` on a claim for resolution; and `status` on an exclusivity grant for waiver.
        Design: Difficulty/transitive_cascade/transitive_upheld_claim_holds_credit_and_blocks_qualified_inquiry
        """
        bundle = setup_upheld_claim(
            api,
            direct_event_date_utc="2026-12-14T18:00:00Z",
            direct_fee_cents=1_000_000,
        )
        bundle = self._second_upheld_claim(api, bundle)
        blocked_id = bundle["blocked_candidate"]["id"]
        assert read_inquiry(api, blocked_id)["status"] == "BLOCKED"

        validate_error(
            api.qualify_inquiry(blocked_id, qualify_payload(), AGENT_HEADERS),
            ApiErrorId.ERR_INQUIRY_STATE_INVALID.value,
        )
        assert read_inquiry(api, blocked_id)["status"] == "BLOCKED"
