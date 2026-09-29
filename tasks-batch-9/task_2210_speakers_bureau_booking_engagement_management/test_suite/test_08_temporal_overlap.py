"""Overlap screens that reach beyond the literal event window.

The calendar screen widens each booking by the speaker's travel buffer, so two
events that do not overlap at all can still collide; the exclusivity screen is
scoped by industry and by beneficiary, so it blocks a competitor while leaving
the beneficiary and an unrelated industry free.
"""

from test_helpers import (
    ADMIN_HEADERS,
    AGENT_HEADERS,
    ApiErrorId,
    add_option,
    create_client,
    create_draft_proposal,
    create_inquiry,
    find_holds_for_speaker,
    get_success_data,
    make_client_headers,
    qualify_inquiry,
    read_engagement,
    read_grant,
    read_speaker,
    select_option_payload,
    setup_confirmed_engagement,
    setup_exclusivity_grant_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


def _offer_engagement(
    api,
    speaker,
    client_row,
    client_headers,
    event_start_utc,
    event_end_utc,
    valid_until_utc,
):
    """Run inquiry -> proposal -> selection for one speaker, stopping at OFFERED."""
    inquiry = create_inquiry(
        api,
        client_row,
        event_start_utc=event_start_utc,
        event_end_utc=event_end_utc,
    )
    inquiry = qualify_inquiry(api, inquiry["id"])
    proposal = create_draft_proposal(api, inquiry, valid_until_utc=valid_until_utc)
    option = add_option(api, proposal, speaker)
    get_success_data(api.present_proposal(proposal["id"], AGENT_HEADERS))
    engagement = get_success_data(
        api.select_proposal_option(
            proposal["id"], select_option_payload(option["id"]), client_headers
        )
    )
    return read_engagement(api, engagement["id"])


def _active_engagement_holds(api, speaker_id):
    return [
        hold
        for hold in find_holds_for_speaker(api, speaker_id)
        if hold["kind"] == "ENGAGEMENT" and hold["status"] == "ACTIVE"
    ]


class TestTravelBufferWidensTheCalendar:
    def test_a_confirmed_booking_holds_a_day_on_either_side_of_the_event(self, api):
        """The minted hold spans the event widened by one buffer day at each end and counts three calendar dates.

        PRD: When all of that passes, the engagement moves `OFFERED → CONFIRMED`, the server mints a hold of `kind` `ENGAGEMENT` and `status` `ACTIVE` spanning exactly that buffered closed interval — so `hold_start_utc` is `event_start_utc` minus the buffer and `hold_end_utc` is `event_end_utc` plus the buffer — and the speaker's `held_days_count` grows by the new hold's `day_span`.
        Design: Difficulty/resource_temporal_overlap/temporal_travel_buffer_blocks_a_non_overlapping_adjacent_event
        """
        bundle = setup_confirmed_engagement(api)
        holds = _active_engagement_holds(api, bundle["speaker"]["id"])

        assert len(holds) == 1
        hold = holds[0]
        assert hold["hold_start_utc"].startswith("2026-10-14T16:00:00")
        assert hold["hold_end_utc"].startswith("2026-10-16T18:00:00")
        assert hold["day_span"] == 3
        assert hold["engagement_id"] == bundle["engagement"]["id"]
        assert read_speaker(api, bundle["speaker"]["id"])["held_days_count"] == 3

    def test_an_event_the_day_after_the_hold_ends_still_collides(self, api):
        """A second event that never overlaps the first is refused because its own buffer reaches back into the live hold.

        PRD: Next comes the calendar: no `ACTIVE` hold for this speaker may intersect the buffered **closed** interval running from `event_start_utc` minus `travel_buffer_days` days to `event_end_utc` plus `travel_buffer_days` days, and an intersection is refused with `ERR_SPEAKER_CALENDAR_CONFLICT`.
        Design: Difficulty/resource_temporal_overlap/temporal_travel_buffer_blocks_a_non_overlapping_adjacent_event
        """
        bundle = setup_confirmed_engagement(api)
        adjacent = _offer_engagement(
            api,
            bundle["speaker"],
            bundle["client"],
            bundle["client_headers"],
            "2026-10-17T16:00:00Z",
            "2026-10-17T18:00:00Z",
            "2026-09-20T00:00:00Z",
        )

        validate_error(
            api.confirm_engagement(adjacent["id"], bundle["speaker_headers"]),
            ApiErrorId.ERR_SPEAKER_CALENDAR_CONFLICT.value,
        )

        assert read_engagement(api, adjacent["id"])["booking_status"] == "OFFERED"
        rows, _meta = validate_paginated(
            api.list_speaker_holds(
                ADMIN_HEADERS, params={"engagement_id": adjacent["id"]}
            )
        )
        assert rows == []

    def test_one_day_further_out_clears_both_buffers_and_confirms(self, api):
        """Moving the second event a day further out separates the two buffered intervals, so the calendar accepts it.

        PRD: On a `Speaker`: `held_days_count` equals the sum of `day_span` over that speaker's calendar holds whose `status` is `ACTIVE`; `engagements_delivered_count` equals the number of that speaker's engagements whose `booking_status` is `DELIVERED`; `lifetime_gross_fees_cents` equals the running sum of `quoted_fee_cents` plus `recording_fee_cents` over those delivered engagements; `pending_remittance_cents` equals the sum of `net_payable_cents` over that speaker's remittances whose `status` is `PENDING` or `APPROVED`; and `feedback_count` is the number of feedback rows filed across that speaker's engagements.
        Design: Difficulty/resource_temporal_overlap/temporal_travel_buffer_blocks_a_non_overlapping_adjacent_event
        """
        bundle = setup_confirmed_engagement(api)
        adjacent = _offer_engagement(
            api,
            bundle["speaker"],
            bundle["client"],
            bundle["client_headers"],
            "2026-10-17T16:00:00Z",
            "2026-10-17T18:00:00Z",
            "2026-09-20T00:00:00Z",
        )
        validate_error(
            api.confirm_engagement(adjacent["id"], bundle["speaker_headers"]),
            ApiErrorId.ERR_SPEAKER_CALENDAR_CONFLICT.value,
        )

        clear = _offer_engagement(
            api,
            bundle["speaker"],
            bundle["client"],
            bundle["client_headers"],
            "2026-10-18T16:00:00Z",
            "2026-10-18T18:00:00Z",
            "2026-09-20T00:00:00Z",
        )
        confirmed = validate_success(
            api.confirm_engagement(clear["id"], bundle["speaker_headers"])
        )
        assert confirmed["booking_status"] == "CONFIRMED"

        rows, _meta = validate_paginated(
            api.list_speaker_holds(
                ADMIN_HEADERS, params={"engagement_id": clear["id"], "status": "ACTIVE"}
            )
        )
        assert len(rows) == 1
        assert rows[0]["hold_start_utc"].startswith("2026-10-17T16:00:00")
        assert rows[0]["hold_end_utc"].startswith("2026-10-19T18:00:00")
        assert rows[0]["day_span"] == 3
        assert read_speaker(api, bundle["speaker"]["id"])["held_days_count"] == 6

    def test_the_span_counts_distinct_calendar_dates_not_elapsed_hours(self, api):
        """A hold running from one afternoon to the afternoon two days later touches three dates.

        PRD: Either way the server computes `day_span` as the number of distinct UTC calendar dates the closed interval from `hold_start_utc` to `hold_end_utc` touches, and adds that `day_span` to the speaker's `held_days_count`.
        Design: Difficulty/resource_temporal_overlap/temporal_travel_buffer_blocks_a_non_overlapping_adjacent_event
        """
        bundle = setup_confirmed_engagement(api)
        hold = _active_engagement_holds(api, bundle["speaker"]["id"])[0]

        assert hold["hold_start_utc"][:10] == "2026-10-14"
        assert hold["hold_end_utc"][:10] == "2026-10-16"
        assert hold["day_span"] == 3


class TestExclusivityIsScopedByIndustryAndBeneficiary:
    def test_a_same_industry_competitor_is_refused_inside_the_window(self, api):
        """A rival healthcare client cannot confirm the same speaker while the grant is live.

        PRD: Only then does the exclusivity screen run over the surviving `ACTIVE` grants: if any grant for this same `speaker_id`, carrying the same `industry_code` as this engagement's client, and whose `beneficiary_client_id` is a *different* client, covers this engagement's `event_start_utc` within the half-open window running from `effective_from_utc` inclusive to `effective_to_utc` exclusive, the confirmation is refused with `ERR_EXCLUSIVITY_CONFLICT`.
        Design: Difficulty/resource_temporal_overlap/temporal_exclusivity_window_blocks_competitor_but_not_beneficiary_or_other_industry
        """
        bundle = setup_exclusivity_grant_scenario(api, exclusivity_days=90)
        assert bundle["grant"]["industry_code"] == "HEALTHCARE"
        assert bundle["grant"]["beneficiary_client_id"] == bundle["client"]["id"]

        validate_error(
            api.confirm_engagement(
                bundle["competitor_engagement"]["id"], bundle["speaker_headers"]
            ),
            ApiErrorId.ERR_EXCLUSIVITY_CONFLICT.value,
        )

        assert read_engagement(api, bundle["competitor_engagement"]["id"])[
            "booking_status"
        ] == "OFFERED"
        rows, _meta = validate_paginated(
            api.list_speaker_holds(
                ADMIN_HEADERS,
                params={"engagement_id": bundle["competitor_engagement"]["id"]},
            )
        )
        assert rows == []

    def test_the_beneficiary_itself_may_book_the_same_date_it_locked_up(self, api):
        """The client the grant protects is exempt from it, so its own second booking on the blocked date confirms.

        PRD: And when `exclusivity_days` is greater than 0, an `ExclusivityGrant` is created in `status` `ACTIVE`, recording `source_engagement_id` as this engagement, `speaker_id` as this speaker, `beneficiary_client_id` as this engagement's client, `industry_code` copied from that beneficiary client, `effective_from_utc` equal to the engagement's `event_end_utc`, and `effective_to_utc` equal to `effective_from_utc` plus `exclusivity_days` days — the window being inclusive at its start and **exclusive** at its end.
        Design: Difficulty/resource_temporal_overlap/temporal_exclusivity_window_blocks_competitor_but_not_beneficiary_or_other_industry
        """
        bundle = setup_exclusivity_grant_scenario(api, exclusivity_days=90)
        validate_error(
            api.confirm_engagement(
                bundle["competitor_engagement"]["id"], bundle["speaker_headers"]
            ),
            ApiErrorId.ERR_EXCLUSIVITY_CONFLICT.value,
        )

        own_second = _offer_engagement(
            api,
            bundle["speaker"],
            bundle["client"],
            bundle["client_headers"],
            "2026-12-05T16:00:00Z",
            "2026-12-05T18:00:00Z",
            "2026-11-15T00:00:00Z",
        )
        confirmed = validate_success(
            api.confirm_engagement(own_second["id"], bundle["speaker_headers"])
        )
        assert confirmed["booking_status"] == "CONFIRMED"
        assert read_speaker(api, bundle["speaker"]["id"])["held_days_count"] == 6

    def test_an_unrelated_industry_is_outside_the_grant_altogether(self, api):
        """A finance client is never in scope of a healthcare grant, so it confirms and the grant stays live.

        PRD: A grant restricts confirmations only while it is `ACTIVE`.
        Design: Difficulty/resource_temporal_overlap/temporal_exclusivity_window_blocks_competitor_but_not_beneficiary_or_other_industry
        """
        bundle = setup_exclusivity_grant_scenario(api, exclusivity_days=90)
        validate_error(
            api.confirm_engagement(
                bundle["competitor_engagement"]["id"], bundle["speaker_headers"]
            ),
            ApiErrorId.ERR_EXCLUSIVITY_CONFLICT.value,
        )
        validate_success(
            api.confirm_engagement(
                _offer_engagement(
                    api,
                    bundle["speaker"],
                    bundle["client"],
                    bundle["client_headers"],
                    "2026-12-05T16:00:00Z",
                    "2026-12-05T18:00:00Z",
                    "2026-11-15T00:00:00Z",
                )["id"],
                bundle["speaker_headers"],
            )
        )

        other_industry = create_client(
            api,
            org_name="Lakeside Capital",
            industry_code="FINANCE",
            primary_contact_email="events@lakeside.example",
        )
        finance_engagement = _offer_engagement(
            api,
            bundle["speaker"],
            other_industry,
            make_client_headers(other_industry["id"]),
            "2026-12-20T16:00:00Z",
            "2026-12-20T18:00:00Z",
            "2026-12-01T00:00:00Z",
        )
        confirmed = validate_success(
            api.confirm_engagement(finance_engagement["id"], bundle["speaker_headers"])
        )
        assert confirmed["booking_status"] == "CONFIRMED"

        assert read_speaker(api, bundle["speaker"]["id"])["held_days_count"] == 9
        grant = read_grant(api, bundle["grant"]["id"])
        assert grant["status"] == "ACTIVE"
        assert grant["effective_from_utc"] == bundle["grant"]["effective_from_utc"]
        assert grant["effective_to_utc"] == bundle["grant"]["effective_to_utc"]
