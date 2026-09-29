"""Thresholds tested on the instant, not near it.

The cancellation ladder is exercised at exactly thirty whole days and at
twenty-nine; the exclusivity window is exercised one second inside its
exclusive end and exactly on it; and the protection window is exercised at 180,
181 and 366 whole days after the source engagement closed.
"""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    AGENT_HEADERS,
    ApiErrorId,
    add_second_engagement_for_speaker,
    cancellation_payload,
    circumvention_claim_payload,
    claim_resolution_payload,
    find_invoices_for,
    find_remittances_for,
    read_client,
    read_engagement,
    read_grant,
    read_speaker,
    round_half_up,
    set_clock,
    setup_cancelled_engagement,
    setup_contracted_engagement,
    setup_exclusivity_grant_scenario,
    setup_two_delivered_engagements,
    validate_error,
    validate_paginated,
    validate_success,
)

NOVEMBER_EVENT = {
    "event_start_utc": "2026-11-20T16:00:00Z",
    "event_end_utc": "2026-11-20T18:00:00Z",
}


class TestCancellationLadderBoundary:
    def test_exactly_thirty_whole_days_retains_nothing_and_bills_nothing(self, api):
        """A cancellation on the lower bound of the top standard band waives the settlement entirely.

        PRD: Under `STANDARD`: 30 or more days before the event retains nothing, 0.00; from 14 to 29 days inclusive retains 0.50; fewer than 14 days retains the whole fee, 1.00.
        Design: Difficulty/boundary_precision_check/boundary_cancellation_ladder_at_exactly_thirty_days_versus_twenty_nine
        """
        bundle = setup_cancelled_engagement(
            api, cancellation_clock_utc="2026-09-15T16:00:00Z"
        )
        engagement = bundle["engagement"]

        assert engagement["cancellation_days_before"] == 30
        assert engagement["retention_net_cents"] == 0
        assert engagement["retention_commission_cents"] == 0
        assert engagement["booking_status"] == "CANCELLED_BY_CLIENT"
        assert engagement["settlement_status"] == "WAIVED"
        assert find_invoices_for(api, engagement["id"]) == []
        assert find_remittances_for(api, engagement["id"]) == []

    def test_one_day_later_at_twenty_nine_days_retains_half_the_fee(self, api):
        """Slipping one whole day below the boundary moves the retention percentage from nothing to a half.

        PRD: When instead `retention_net_cents` plus `travel_reimbursable_cents` comes out at exactly 0 — a full-waiver band with no approved travel — no invoice and no remittance are created at all and the settlement dimension moves `UNBILLED → WAIVED`.
        Design: Difficulty/boundary_precision_check/boundary_cancellation_ladder_at_exactly_thirty_days_versus_twenty_nine
        """
        bundle = setup_cancelled_engagement(
            api,
            cancellation_clock_utc="2026-10-22T16:00:00Z",
            inquiry_overrides=NOVEMBER_EVENT,
        )
        engagement = bundle["engagement"]

        assert engagement["cancellation_days_before"] == 29
        assert engagement["retention_net_cents"] == 573_750
        assert engagement["retention_net_cents"] == round_half_up(
            1_275_000 * 0.50
        ) - round_half_up(round_half_up(1_275_000 * 0.50) * 0.10)
        assert engagement["retention_commission_cents"] == 143_438
        assert engagement["settlement_status"] == "INVOICED"
        assert bundle["retention_invoice"]["amount_due_cents"] == 583_791

    def test_both_cancellations_return_the_calendar_to_zero_held_days(self, api):
        """Two cancellations on one speaker release both engagement holds, and only the billed one leaves a receivable.

        PRD: In every branch the engagement's calendar hold moves `ACTIVE → RELEASED` and the speaker's `held_days_count` drops by that hold's `day_span`.
        Design: Difficulty/boundary_precision_check/boundary_cancellation_ladder_at_exactly_thirty_days_versus_twenty_nine
        """
        bundle = setup_contracted_engagement(api)
        bundle = add_second_engagement_for_speaker(
            api,
            bundle,
            event_start_utc=NOVEMBER_EVENT["event_start_utc"],
            event_end_utc=NOVEMBER_EVENT["event_end_utc"],
            valid_until_utc="2026-09-20T00:00:00Z",
            deliver=False,
        )
        assert read_speaker(api, bundle["speaker"]["id"])["held_days_count"] == 6

        set_clock(api, "2026-09-15T16:00:00Z")
        validate_success(
            api.cancel_engagement(
                bundle["engagement"]["id"],
                cancellation_payload("the October conference was scrapped"),
                bundle["client_headers"],
            )
        )
        set_clock(api, "2026-10-22T16:00:00Z")
        validate_success(
            api.cancel_engagement(
                bundle["engagement_2"]["id"],
                cancellation_payload("the November conference was scrapped"),
                bundle["client_headers"],
            )
        )

        assert read_speaker(api, bundle["speaker"]["id"])["held_days_count"] == 0
        assert read_engagement(api, bundle["engagement"]["id"])[
            "settlement_status"
        ] == "WAIVED"
        assert read_engagement(api, bundle["engagement_2"]["id"])[
            "settlement_status"
        ] == "INVOICED"
        assert read_client(api, bundle["client"]["id"])[
            "outstanding_balance_cents"
        ] == 583_791


class TestExclusivityWindowIsExclusiveAtItsEnd:
    def test_one_second_before_the_end_instant_still_conflicts(self, api):
        """An event starting a second inside the ninety-day window is refused for the competing client.

        PRD: Only then does the exclusivity screen run over the surviving `ACTIVE` grants: if any grant for this same `speaker_id`, carrying the same `industry_code` as this engagement's client, and whose `beneficiary_client_id` is a *different* client, covers this engagement's `event_start_utc` within the half-open window running from `effective_from_utc` inclusive to `effective_to_utc` exclusive, the confirmation is refused with `ERR_EXCLUSIVITY_CONFLICT`.
        Design: Difficulty/boundary_precision_check/boundary_exclusivity_effective_to_is_exclusive_at_the_instant
        """
        bundle = setup_exclusivity_grant_scenario(
            api,
            exclusivity_days=90,
            competitor_event_start_utc="2027-01-13T17:59:59Z",
            competitor_event_end_utc="2027-01-13T19:59:59Z",
            competitor_valid_until_utc="2026-11-15T00:00:00Z",
        )
        assert bundle["grant"]["effective_to_utc"].startswith("2027-01-13T18:00:00")

        validate_error(
            api.confirm_engagement(
                bundle["competitor_engagement"]["id"], bundle["speaker_headers"]
            ),
            ApiErrorId.ERR_EXCLUSIVITY_CONFLICT.value,
        )

        engagement = read_engagement(api, bundle["competitor_engagement"]["id"])
        assert engagement["booking_status"] == "OFFERED"
        rows, _meta = validate_paginated(
            api.list_speaker_holds(
                ADMIN_HEADERS, params={"engagement_id": engagement["id"]}
            )
        )
        assert rows == []

    def test_exactly_the_end_instant_is_outside_the_window(self, api):
        """An event starting exactly on the exclusive end instant is not covered, so the confirmation succeeds and mints its hold.

        PRD: A grant restricts confirmations only while it is `ACTIVE`.
        Design: Difficulty/boundary_precision_check/boundary_exclusivity_effective_to_is_exclusive_at_the_instant
        """
        bundle = setup_exclusivity_grant_scenario(
            api,
            exclusivity_days=90,
            competitor_event_start_utc="2027-01-13T18:00:00Z",
            competitor_event_end_utc="2027-01-13T20:00:00Z",
            competitor_valid_until_utc="2026-11-15T00:00:00Z",
        )

        confirmed = validate_success(
            api.confirm_engagement(
                bundle["competitor_engagement"]["id"], bundle["speaker_headers"]
            )
        )
        assert confirmed["booking_status"] == "CONFIRMED"

        rows, _meta = validate_paginated(
            api.list_speaker_holds(
                ADMIN_HEADERS,
                params={
                    "engagement_id": bundle["competitor_engagement"]["id"],
                    "status": "ACTIVE",
                },
            )
        )
        assert len(rows) == 1
        assert rows[0]["kind"] == "ENGAGEMENT"
        assert read_grant(api, bundle["grant"]["id"])["status"] == "ACTIVE"


class TestProtectionWindowBoundaries:
    def test_exactly_one_hundred_and_eighty_days_keeps_full_protection(self, api):
        """A direct booking exactly 180 whole days after the source event closed is assessed at the full factor.

        PRD: `days_after_source` is the whole days from the source engagement's `event_end_utc` to `direct_event_date_utc`, computed as the difference in seconds divided by 86400 and floored; a direct event on or before the source engagement's end therefore gives a count of zero or less, which sits comfortably inside the full-protection band.
        Design: Difficulty/boundary_precision_check/boundary_protection_window_at_180_versus_181_versus_366_days
        """
        bundle = setup_two_delivered_engagements(api)

        claim = validate_success(
            api.create_circumvention_claim(
                circumvention_claim_payload(
                    bundle["client"]["id"],
                    bundle["speaker"]["id"],
                    bundle["engagement"]["id"],
                    "2027-04-13T18:00:00Z",
                    1_000_000,
                ),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )

        assert claim["days_after_source"] == 180
        assert claim["protection_factor"] == pytest.approx(1.00, abs=0.001)
        assert claim["commission_due_cents"] == 250_000
        assert claim["status"] == "OPEN"

    def test_one_hundred_and_eighty_one_days_halves_the_protection_factor(self, api):
        """Crossing the six-month bound by a single whole day halves the assessed commission.

        PRD: `protection_factor` is 1.00 when `days_after_source` is at most 180 — the first six months — and 0.50 when `days_after_source` is greater than 180 but at most 365; a `days_after_source` greater than 365 means the protection has lapsed entirely and the claim is refused with `ERR_OUTSIDE_PROTECTION_WINDOW`.
        Design: Difficulty/boundary_precision_check/boundary_protection_window_at_180_versus_181_versus_366_days
        """
        bundle = setup_two_delivered_engagements(api)

        claim = validate_success(
            api.create_circumvention_claim(
                circumvention_claim_payload(
                    bundle["client"]["id"],
                    bundle["speaker"]["id"],
                    bundle["engagement_2"]["id"],
                    "2027-05-20T18:00:00Z",
                    1_000_000,
                ),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )

        assert claim["days_after_source"] == 181
        assert claim["protection_factor"] == pytest.approx(0.50, abs=0.001)
        assert claim["commission_due_cents"] == 125_000
        assert claim["commission_due_cents"] == round_half_up(
            1_000_000 * 0.25 * 0.50
        )

    def test_three_hundred_and_sixty_six_days_has_lapsed_and_creates_no_row(self, api):
        """Beyond the year the claim is refused outright, leaving only the earlier dismissed row on that engagement.

        PRD: `DISMISS` requires the claim to be `OPEN`, drives `OPEN → DISMISSED`, and leaves the client's `circumvention_strikes` unchanged.
        Design: Difficulty/boundary_precision_check/boundary_protection_window_at_180_versus_181_versus_366_days
        """
        bundle = setup_two_delivered_engagements(api)
        source_id = bundle["engagement_2"]["id"]

        claim = validate_success(
            api.create_circumvention_claim(
                circumvention_claim_payload(
                    bundle["client"]["id"],
                    bundle["speaker"]["id"],
                    source_id,
                    "2027-05-20T18:00:00Z",
                    1_000_000,
                ),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        dismissed = validate_success(
            api.resolve_circumvention_claim(
                claim["id"], claim_resolution_payload("DISMISS"), ADMIN_HEADERS
            )
        )
        assert dismissed["status"] == "DISMISSED"

        validate_error(
            api.create_circumvention_claim(
                circumvention_claim_payload(
                    bundle["client"]["id"],
                    bundle["speaker"]["id"],
                    source_id,
                    "2027-11-21T18:00:00Z",
                    1_000_000,
                ),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_OUTSIDE_PROTECTION_WINDOW.value,
        )

        rows, _meta = validate_paginated(
            api.list_circumvention_claims(
                AGENT_HEADERS, params={"source_engagement_id": source_id}
            )
        )
        assert len(rows) == 1
        assert rows[0]["status"] == "DISMISSED"
        assert read_client(api, bundle["client"]["id"])["circumvention_strikes"] == 0
