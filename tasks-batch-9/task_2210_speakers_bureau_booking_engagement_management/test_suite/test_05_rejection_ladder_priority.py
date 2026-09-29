"""Requests that breach two guards at once, where only one code may come back.

Each scenario is arranged so that a second, independently verifiable breach is
also present: removing the higher-ranked breach must surface the lower-ranked
one, which is what makes the ordering observable rather than incidental.
"""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    AGENT_HEADERS,
    OTHER_AGENT_HEADERS,
    ApiErrorId,
    commission_adjustment_payload,
    create_client,
    create_hold,
    create_inquiry,
    exclusivity_waiver_payload,
    inquiry_payload,
    qualify_payload,
    read_engagement,
    read_inquiry,
    read_speaker,
    round_half_up,
    setup_contracted_engagement,
    setup_exclusivity_grant_scenario,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestLeadTimeOutranksBudgetFloor:
    def test_a_short_notice_inquiry_reports_lead_time_even_when_the_budget_also_fails(
        self, api
    ):
        """An inquiry nine days out with a sub-floor budget is refused on lead time, not on money.

        PRD: **Money**, last within the business band, in this internal order: (a) the budget floor at qualification — `ERR_BUDGET_BELOW_FLOOR` (409); (b) the quoted fee against the speaker's range — `ERR_FEE_OUTSIDE_SPEAKER_RANGE` (409); (c) the quote against the inquiry's budget headroom — `ERR_QUOTE_EXCEEDS_BUDGET` (409); (d) a payment that is not positive or exceeds the invoice's remaining balance — `ERR_OVERPAYMENT` (409); (e) an out-of-range adjustment rate — `ERR_COMMISSION_PCT_OUT_OF_RANGE` (422); (f) a settlement amount outside the claim's assessed commission — `ERR_INVALID_REQUEST` (422).
        Design: Difficulty/priority_pair_validation_conflict/priority_lead_time_outranks_budget_floor_on_qualification
        """
        set_clock(api)
        client_row = create_client(api)
        inquiry = create_inquiry(
            api,
            client_row,
            event_start_utc="2026-08-10T16:00:00Z",
            event_end_utc="2026-08-10T18:00:00Z",
            budget_cents=100_000,
        )

        validate_error(
            api.qualify_inquiry(inquiry["id"], qualify_payload(), AGENT_HEADERS),
            ApiErrorId.ERR_INSUFFICIENT_LEAD_TIME.value,
        )

    def test_removing_the_lead_time_breach_surfaces_the_budget_floor(self, api):
        """The same sub-floor budget is reported once the event is far enough away for the lead-time screen to pass.

        PRD: `QUALIFY` also demands that the inquiry be `RECEIVED`, and adds three commercial screens before moving it `RECEIVED → QUALIFIED`: the client's `credit_status` must not be `HOLD`, or the attempt is refused with `ERR_CLIENT_CREDIT_HOLD`; there must be at least three full weeks of lead time, meaning the whole days from the logical clock to `event_start_utc` must be at least 21, or the attempt is refused with `ERR_INSUFFICIENT_LEAD_TIME`; and `budget_cents` must be at least the engagement floor of 2,500 dollars — that is, 250,000 cents — or the attempt is refused with `ERR_BUDGET_BELOW_FLOOR`.
        Design: Difficulty/priority_pair_validation_conflict/priority_lead_time_outranks_budget_floor_on_qualification
        """
        set_clock(api)
        client_row = create_client(api)
        inquiry = create_inquiry(
            api,
            client_row,
            event_start_utc="2026-10-15T16:00:00Z",
            event_end_utc="2026-10-15T18:00:00Z",
            budget_cents=100_000,
        )

        validate_error(
            api.qualify_inquiry(inquiry["id"], qualify_payload(), AGENT_HEADERS),
            ApiErrorId.ERR_BUDGET_BELOW_FLOOR.value,
        )

    def test_neither_rejected_qualification_takes_ownership_of_the_inquiry(self, api):
        """A refused qualification leaves the inquiry where it started, with no owning agent recorded.

        PRD: A fresh inquiry has `status` `RECEIVED` and a null `owning_agent_user_id`; the full status enumeration is `RECEIVED`, `QUALIFIED`, `BLOCKED`, `PROPOSED`, `WON`, `LOST` and `DISQUALIFIED`, of which `WON`, `LOST` and `DISQUALIFIED` are terminal.
        Design: Difficulty/priority_pair_validation_conflict/priority_lead_time_outranks_budget_floor_on_qualification
        """
        set_clock(api)
        client_row = create_client(api)
        short_notice = create_inquiry(
            api,
            client_row,
            event_start_utc="2026-08-10T16:00:00Z",
            event_end_utc="2026-08-10T18:00:00Z",
            budget_cents=100_000,
        )
        under_floor = validate_success(
            api.create_inquiry(
                inquiry_payload(
                    client_row["id"],
                    event_start_utc="2026-10-15T16:00:00Z",
                    event_end_utc="2026-10-15T18:00:00Z",
                    budget_cents=100_000,
                ),
                AGENT_HEADERS,
            ),
            expected_status=201,
        )

        validate_error(
            api.qualify_inquiry(short_notice["id"], qualify_payload(), AGENT_HEADERS),
            ApiErrorId.ERR_INSUFFICIENT_LEAD_TIME.value,
        )
        validate_error(
            api.qualify_inquiry(under_floor["id"], qualify_payload(), AGENT_HEADERS),
            ApiErrorId.ERR_BUDGET_BELOW_FLOOR.value,
        )

        for inquiry_id in (short_notice["id"], under_floor["id"]):
            row = read_inquiry(api, inquiry_id)
            assert row["status"] == "RECEIVED"
            assert row["owning_agent_user_id"] is None


class TestExclusivityOutranksCalendar:
    BLACKOUT = {
        "hold_start_utc": "2026-12-09T00:00:00Z",
        "hold_end_utc": "2026-12-11T23:00:00Z",
        "reason": "family commitment",
    }
    COMPETITOR = {
        "competitor_event_start_utc": "2026-12-10T16:00:00Z",
        "competitor_event_end_utc": "2026-12-10T18:00:00Z",
        "competitor_industry_code": "HEALTHCARE",
        "competitor_valid_until_utc": "2026-11-15T00:00:00Z",
    }

    def test_the_exclusivity_screen_answers_first_when_the_calendar_also_clashes(
        self, api
    ):
        """A competitor confirmation that clashes with both a live grant and a blackout reports the grant.

        PRD: **Exclusivity screen**, on engagement confirmation only — `ERR_EXCLUSIVITY_CONFLICT` (409), as specified in §3.4.
        Design: Difficulty/priority_pair_validation_conflict/priority_exclusivity_conflict_outranks_calendar_conflict_on_confirm
        """
        bundle = setup_exclusivity_grant_scenario(
            api, exclusivity_days=90, **self.COMPETITOR
        )
        create_hold(api, bundle["speaker"], **self.BLACKOUT)

        validate_error(
            api.confirm_engagement(
                bundle["competitor_engagement"]["id"], bundle["speaker_headers"]
            ),
            ApiErrorId.ERR_EXCLUSIVITY_CONFLICT.value,
        )
        assert (
            read_engagement(api, bundle["competitor_engagement"]["id"])[
                "booking_status"
            ]
            == "OFFERED"
        )

    def test_waiving_the_grant_surfaces_the_calendar_conflict_underneath_it(self, api):
        """Releasing the grant lets the identical confirmation through to the calendar screen, which refuses it.

        PRD: Next comes the calendar: no `ACTIVE` hold for this speaker may intersect the buffered **closed** interval running from `event_start_utc` minus `travel_buffer_days` days to `event_end_utc` plus `travel_buffer_days` days, and an intersection is refused with `ERR_SPEAKER_CALENDAR_CONFLICT`.
        Design: Difficulty/priority_pair_validation_conflict/priority_exclusivity_conflict_outranks_calendar_conflict_on_confirm
        """
        bundle = setup_exclusivity_grant_scenario(
            api, exclusivity_days=90, **self.COMPETITOR
        )
        create_hold(api, bundle["speaker"], **self.BLACKOUT)

        waived = validate_success(
            api.waive_exclusivity_grant(
                bundle["grant"]["id"], exclusivity_waiver_payload(), ADMIN_HEADERS
            )
        )
        assert waived["status"] == "WAIVED"

        validate_error(
            api.confirm_engagement(
                bundle["competitor_engagement"]["id"], bundle["speaker_headers"]
            ),
            ApiErrorId.ERR_SPEAKER_CALENDAR_CONFLICT.value,
        )

    def test_neither_refusal_mints_a_hold_or_moves_the_held_days_total(self, api):
        """Both refusals leave the competitor engagement offered, so the calendar still shows only the first booking and the blackout.

        PRD: When all of that passes, the engagement moves `OFFERED → CONFIRMED`, the server mints a hold of `kind` `ENGAGEMENT` and `status` `ACTIVE` spanning exactly that buffered closed interval — so `hold_start_utc` is `event_start_utc` minus the buffer and `hold_end_utc` is `event_end_utc` plus the buffer — and the speaker's `held_days_count` grows by the new hold's `day_span`.
        Design: Difficulty/priority_pair_validation_conflict/priority_exclusivity_conflict_outranks_calendar_conflict_on_confirm
        """
        bundle = setup_exclusivity_grant_scenario(
            api, exclusivity_days=90, **self.COMPETITOR
        )
        create_hold(api, bundle["speaker"], **self.BLACKOUT)
        competitor_engagement_id = bundle["competitor_engagement"]["id"]

        validate_error(
            api.confirm_engagement(competitor_engagement_id, bundle["speaker_headers"]),
            ApiErrorId.ERR_EXCLUSIVITY_CONFLICT.value,
        )
        validate_success(
            api.waive_exclusivity_grant(
                bundle["grant"]["id"], exclusivity_waiver_payload(), ADMIN_HEADERS
            )
        )
        validate_error(
            api.confirm_engagement(competitor_engagement_id, bundle["speaker_headers"]),
            ApiErrorId.ERR_SPEAKER_CALENDAR_CONFLICT.value,
        )

        rows, _meta = validate_paginated(
            api.list_speaker_holds(
                ADMIN_HEADERS, params={"engagement_id": competitor_engagement_id}
            )
        )
        assert rows == []
        assert read_speaker(api, bundle["speaker"]["id"])["held_days_count"] == 6


class TestSegregationOfDutiesOutranksStaleVersion:
    def test_the_owning_agent_is_barred_before_the_version_token_is_even_checked(
        self, api
    ):
        """The engagement's own agent is refused on four-eyes grounds even though the version token it sent is stale.

        PRD: The engagement's own `owning_agent_user_id` may not post that engagement's commission adjustment — otherwise `ERR_SEGREGATION_OF_DUTIES` (403).
        Design: Difficulty/priority_pair_validation_conflict/priority_segregation_of_duties_outranks_stale_engagement_version
        """
        bundle = setup_contracted_engagement(api)
        engagement = bundle["engagement"]
        stale_version = engagement["version"] - 1

        validate_error(
            api.create_commission_adjustment(
                engagement["id"],
                commission_adjustment_payload(0.30, stale_version),
                AGENT_HEADERS,
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        )
        assert (
            read_engagement(api, engagement["id"])["commission_adjustment_count"] == 0
        )

    def test_a_stranger_sending_the_same_stale_token_is_refused_on_concurrency(
        self, api
    ):
        """Once the four-eyes bar is cleared by a different agent, the stale token becomes the reported failure.

        PRD: If that value does not equal the engagement's current `version`, the request is rejected with `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412).
        Design: Difficulty/priority_pair_validation_conflict/priority_segregation_of_duties_outranks_stale_engagement_version
        """
        bundle = setup_contracted_engagement(api)
        engagement = bundle["engagement"]
        stale_version = engagement["version"] - 1

        validate_error(
            api.create_commission_adjustment(
                engagement["id"],
                commission_adjustment_payload(0.30, stale_version),
                OTHER_AGENT_HEADERS,
            ),
            ApiErrorId.ERR_STALE_ENGAGEMENT_VERSION.value,
        )
        assert (
            read_engagement(api, engagement["id"])["commission_adjustment_count"] == 0
        )

    def test_a_stranger_with_a_current_token_re_prices_the_engagement(self, api):
        """With both guards satisfied the adjustment overwrites the snapshot and rewrites the provisional figure.

        PRD: An accepted adjustment overwrites `commission_pct_snapshot` with `new_commission_pct`, rewrites `provisional_commission_cents` using the provisional formula at the new rate — `quoted_fee_cents` multiplied by the new snapshot, rounded half up — and increments `commission_adjustment_count` by one.
        Design: Difficulty/priority_pair_validation_conflict/priority_segregation_of_duties_outranks_stale_engagement_version
        """
        bundle = setup_contracted_engagement(api)
        engagement = read_engagement(api, bundle["engagement"]["id"])

        validate_success(
            api.create_commission_adjustment(
                engagement["id"],
                commission_adjustment_payload(0.30, engagement["version"]),
                OTHER_AGENT_HEADERS,
            )
        )

        adjusted = read_engagement(api, engagement["id"])
        assert adjusted["commission_pct_snapshot"] == pytest.approx(0.30, abs=0.001)
        assert adjusted["provisional_commission_cents"] == 382_500
        assert adjusted["provisional_commission_cents"] == round_half_up(
            1_275_000 * 0.30
        )
        assert adjusted["commission_adjustment_count"] == 1
