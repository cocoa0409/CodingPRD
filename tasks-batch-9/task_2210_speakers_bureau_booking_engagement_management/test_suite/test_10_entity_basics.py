"""Creation, defaults, reads and body-level integrity on the core entities.

These are the shape guarantees the rest of the suite leans on: what a fresh row
looks like, which inputs are optional, what a list envelope reports, and which
code comes back when an identifier or a required field is missing.
"""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    AGENT_HEADERS,
    AGENT_USER_ID,
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_option,
    assert_append_only_fields,
    client_payload,
    create_client,
    create_draft_proposal,
    create_second_speaker,
    create_speaker,
    feedback_payload,
    inquiry_payload,
    is_valid_uuid,
    make_speaker_headers,
    minimal_speaker_payload,
    proposal_option_payload,
    proposal_payload,
    read_feedback,
    read_inquiry,
    read_proposal,
    read_speaker,
    set_clock,
    setup_delivered_engagement_with_feedback,
    setup_qualified_inquiry,
    speaker_hold_payload,
    speaker_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRosterEntryBasics:
    def test_a_new_roster_entry_arrives_with_every_derived_field_seeded(self, api):
        """Registration seeds the posture, the tier, the bronze rate, five zeroed counters and two null scores.

        PRD: The five running totals `engagements_delivered_count`, `lifetime_gross_fees_cents`, `held_days_count`, `pending_remittance_cents` and `feedback_count` all start at 0, while `rolling_score` and `lifetime_score` start null and stay null until the speaker's first feedback arrives.
        Design: Corner/entities/speaker_creation_returns_roster_defaults_and_derived_counters
        """
        set_clock(api)
        speaker = validate_success(
            api.create_speaker(speaker_payload(), ADMIN_HEADERS), expected_status=201
        )

        assert speaker["roster_status"] == "ACTIVE"
        assert speaker["roster_tier"] == "BRONZE"
        assert speaker["default_commission_pct"] == pytest.approx(0.25, abs=0.001)
        for counter in (
            "engagements_delivered_count",
            "lifetime_gross_fees_cents",
            "held_days_count",
            "pending_remittance_cents",
            "feedback_count",
        ):
            assert speaker[counter] == 0
        assert speaker["rolling_score"] is None
        assert speaker["lifetime_score"] is None
        assert is_valid_uuid(speaker["id"])
        assert speaker["version"] == 1
        assert speaker["created_at"] == speaker["updated_at"]

    def test_the_two_optional_roster_inputs_fall_back_to_their_declared_defaults(
        self, api
    ):
        """Omitting the buffer and the tax form yields a one-day buffer and the blocking tax posture.

        PRD: Two further inputs are optional: `travel_buffer_days`, a whole number of calendar days from 0 to 3 inclusive that defaults to 1 and pads both sides of any engagement this speaker takes, and `tax_form_status`, which is either `MISSING` or `ON_FILE` and defaults to `MISSING`.
        Design: Corner/entities/speaker_optional_inputs_omitted_apply_declared_defaults
        """
        set_clock(api)
        payload = minimal_speaker_payload()
        assert "travel_buffer_days" not in payload
        assert "tax_form_status" not in payload

        speaker = validate_success(
            api.create_speaker(payload, ADMIN_HEADERS), expected_status=201
        )
        assert speaker["travel_buffer_days"] == 1
        assert speaker["tax_form_status"] == "MISSING"

        stored = read_speaker(api, speaker["id"])
        assert stored["travel_buffer_days"] == 1
        assert stored["tax_form_status"] == "MISSING"

    def test_the_roster_listing_reports_totals_for_the_whole_filtered_set(self, api):
        """Paging through three speakers two at a time reports the full count and flips the more-rows marker.

        PRD: Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope.
        Design: Corner/entities/speaker_listing_paginates_with_total_count_and_has_more
        """
        set_clock(api)
        dana = create_speaker(api)
        create_second_speaker(api, topics=["AI_STRATEGY"])
        noor = create_speaker(
            api,
            full_name="Noor Haddad",
            topics=["LEADERSHIP"],
            fee_floor_cents=800_000,
            fee_ceiling_cents=1_500_000,
            travel_class="ECONOMY",
        )

        rows, meta = validate_paginated(
            api.list_speakers(ADMIN_HEADERS, params={"limit": 2, "offset": 0})
        )
        assert len(rows) == 2
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

        rows, meta = validate_paginated(
            api.list_speakers(ADMIN_HEADERS, params={"limit": 2, "offset": 2})
        )
        assert len(rows) == 1
        assert meta["offset"] == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is False

        rows, meta = validate_paginated(
            api.list_speakers(AGENT_HEADERS, params={"topic": "LEADERSHIP"})
        )
        assert {row["id"] for row in rows} == {dana["id"], noor["id"]}
        assert meta["total_count"] == 2
        assert meta["has_more"] is False

    def test_two_consecutive_reads_leave_the_roster_entry_untouched(self, api):
        """Every posted field round-trips and neither read advances the version or the audit stamp.

        PRD: Almost all resources additionally carry `updated_at`, an ISO 8601 UTC instant refreshed on every mutation, and `version`, an integer that starts at 1 and increments by one on every mutation of that resource — including mutations the server performs on its own initiative as a cascade, and including rewrites of purely derived fields.
        Design: Corner/entities/speaker_retrieval_returns_the_stored_record_unchanged
        """
        set_clock(api)
        created = create_speaker(api)

        first = validate_success(
            api.get_speaker(created["id"], make_speaker_headers(created["id"]))
        )
        second = validate_success(api.get_speaker(created["id"], AGENT_HEADERS))

        assert first["full_name"] == "Dana Reyes"
        assert first["topics"] == ["AI_STRATEGY", "LEADERSHIP"]
        assert first["fee_floor_cents"] == 1_000_000
        assert first["fee_ceiling_cents"] == 2_000_000
        assert first["travel_class"] == "PREMIUM"
        assert isinstance(first, dict)

        assert first["version"] == 1
        assert second["version"] == 1
        assert first["updated_at"] == created["updated_at"]
        assert second["updated_at"] == created["updated_at"]

    def test_an_unknown_speaker_id_is_a_not_found_rather_than_an_empty_success(
        self, api
    ):
        """A well-formed but unused identifier answers with the roster's own not-found code.

        PRD: Each resource type has its own not-found code: `ERR_SPEAKER_NOT_FOUND`, `ERR_CLIENT_NOT_FOUND`, `ERR_INQUIRY_NOT_FOUND`, `ERR_PROPOSAL_NOT_FOUND`, `ERR_OPTION_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, `ERR_TRAVEL_EXPENSE_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_REMITTANCE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_GRANT_NOT_FOUND` and `ERR_FEEDBACK_NOT_FOUND`, all HTTP 404.
        Design: Corner/entities/speaker_get_with_unknown_id_returns_not_found
        """
        set_clock(api)
        create_speaker(api)

        validate_error(
            api.get_speaker(NON_EXISTENT_UUID, ADMIN_HEADERS),
            ApiErrorId.ERR_SPEAKER_NOT_FOUND.value,
        )

        _rows, meta = validate_paginated(
            api.list_speakers(ADMIN_HEADERS, params={"limit": 10})
        )
        assert meta["total_count"] == 1


class TestBodyLevelIntegrity:
    def test_a_client_without_an_industry_code_is_rejected_and_stored_nowhere(
        self, api
    ):
        """The exclusivity dimension cannot be inferred, so its absence fails the body-shape band.

        PRD: The body parses; every required input field is present; every enumerated value is a declared member of its enumeration; every amount field named with a cents suffix is an integer of at least 0; every instant field named with a UTC suffix is an ISO 8601 UTC instant; feedback scores are integers from 1 to 5 inclusive; `rank_no` is from 1 to 4 inclusive; `travel_days` is at least 1; and `new_commission_pct` and `amount_cents` are well-formed numbers. Any breach is `ERR_INVALID_REQUEST` (422).
        Design: Corner/entities/client_creation_missing_required_field_returns_invalid_request
        """
        set_clock(api)
        payload = client_payload()
        del payload["industry_code"]

        validate_error(
            api.create_client(payload, ADMIN_HEADERS),
            ApiErrorId.ERR_INVALID_REQUEST.value,
        )

        _rows, meta = validate_paginated(
            api.list_clients(ADMIN_HEADERS, params={"limit": 10})
        )
        assert meta["total_count"] == 0

    def test_an_off_taxonomy_topic_code_is_a_body_shape_failure(self, api):
        """A topic outside the declared taxonomy is refused before any commercial reasoning happens.

        PRD: An inbound enquiry is recorded by a `BookingAgent` or a `BureauAdmin` as an `Inquiry` naming the `client_id` that raised it, the `required_topic` the audience needs, the event window as `event_start_utc` and `event_end_utc`, the expected headcount as `audience_size` (at least 1), the client's stated speaking-fee budget as `budget_cents` (at least 0), and an `objective_tags` array of between one and four distinct codes drawn from `INSPIRE`, `STRATEGY`, `TRAINING` and `CELEBRATE`.
        Design: Corner/entities/inquiry_invalid_enum_and_bad_event_window_are_rejected
        """
        set_clock(api)
        client_row = create_client(api)

        validate_error(
            api.create_inquiry(
                inquiry_payload(
                    client_row["id"], required_topic="UNDERWATER_BASKETRY"
                ),
                AGENT_HEADERS,
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
        )

        _rows, meta = validate_paginated(
            api.list_inquiries(AGENT_HEADERS, params={"client_id": client_row["id"]})
        )
        assert meta["total_count"] == 0

    def test_a_zero_length_event_window_is_rejected_on_its_own_band(self, api):
        """A body that is otherwise well formed still fails when the event does not actually last any time.

        PRD: `event_end_utc` must be strictly after `event_start_utc`, or the creation fails with `ERR_EVENT_WINDOW_INVALID`.
        Design: Corner/entities/inquiry_invalid_enum_and_bad_event_window_are_rejected
        """
        set_clock(api)
        client_row = create_client(api)

        validate_error(
            api.create_inquiry(
                inquiry_payload(
                    client_row["id"],
                    event_start_utc="2026-10-15T18:00:00Z",
                    event_end_utc="2026-10-15T18:00:00Z",
                ),
                AGENT_HEADERS,
            ),
            ApiErrorId.ERR_EVENT_WINDOW_INVALID.value,
        )

        _rows, meta = validate_paginated(
            api.list_inquiries(AGENT_HEADERS, params={"client_id": client_row["id"]})
        )
        assert meta["total_count"] == 0

    def test_an_unknown_proposal_parent_in_the_body_is_a_not_found(self, api):
        """The option's parent arrives in the body, so an unresolvable package identifier is a 404 on the package.

        PRD: The same codes are reused when a foreign key supplied in a request body fails to resolve.
        Design: Corner/entities/proposal_option_with_unknown_proposal_parent_returns_not_found
        """
        bundle = setup_qualified_inquiry(api)
        proposal = create_draft_proposal(api, bundle["inquiry"])

        validate_error(
            api.create_proposal_option(
                proposal_option_payload(NON_EXISTENT_UUID, bundle["speaker"]["id"]),
                AGENT_HEADERS,
            ),
            ApiErrorId.ERR_PROPOSAL_NOT_FOUND.value,
        )

        unchanged = read_proposal(api, proposal["id"])
        assert unchanged["options_count"] == 0
        assert unchanged["version"] == proposal["version"]

    def test_unresolvable_body_foreign_keys_create_nothing(self, api):
        """An unknown client on an inquiry and an unknown speaker on a blackout each answer with their own 404.

        PRD: **Body foreign keys.** `client_id` on inquiry creation; `speaker_id` on option creation and on manual hold creation; `option_id` on option selection; and `client_id`, `speaker_id` and `source_engagement_id` on claim creation must each resolve to a stored row — otherwise the corresponding 404 code from §2.10.
        Design: Corner/entities/flat_topology_cross_reference_integrity_on_inquiry_and_hold_creation
        """
        set_clock(api)
        speaker = create_speaker(api)
        create_client(api)

        validate_error(
            api.create_inquiry(inquiry_payload(NON_EXISTENT_UUID), AGENT_HEADERS),
            ApiErrorId.ERR_CLIENT_NOT_FOUND.value,
        )
        validate_error(
            api.create_speaker_hold(
                speaker_hold_payload(NON_EXISTENT_UUID), ADMIN_HEADERS
            ),
            ApiErrorId.ERR_SPEAKER_NOT_FOUND.value,
        )

        _inquiries, inquiry_meta = validate_paginated(
            api.list_inquiries(AGENT_HEADERS, params={"limit": 10})
        )
        assert inquiry_meta["total_count"] == 0
        _holds, hold_meta = validate_paginated(
            api.list_speaker_holds(ADMIN_HEADERS, params={"limit": 10})
        )
        assert hold_meta["total_count"] == 0
        assert read_speaker(api, speaker["id"])["held_days_count"] == 0


class TestPackageAndFeedbackShape:
    def test_options_count_tracks_the_children_actually_created(self, api):
        """The package's option counter and version both move only because a child option was created.

        PRD: On a `Proposal`, `options_count` is the number of that proposal's options whose `status` is `OFFERED` or `SELECTED`, and `revision_count` is the number of client revision requests the package has absorbed.
        Design: Corner/entities/proposal_options_count_is_server_computed_from_children
        """
        bundle = setup_qualified_inquiry(api)
        proposal = create_draft_proposal(api, bundle["inquiry"])

        before = read_proposal(api, proposal["id"])
        assert before["options_count"] == 0

        option = add_option(api, before, bundle["speaker"])
        after = read_proposal(api, proposal["id"])

        assert after["options_count"] == 1
        assert after["version"] == before["version"] + 1
        assert option["status"] == "OFFERED"
        assert option["travel_allowance_cents"] == 0

    def test_a_new_package_mints_its_own_system_fields_from_the_header(self, api):
        """Nothing about a fresh package comes from the body: the round, the counters and the author are all server-set.

        PRD: The new package records `inquiry_id`, records the opening agent's `X-User-ID` as `created_by_agent_user_id`, and starts in `DRAFT` with `round_no` 1, `revision_count` 0, `options_count` 0 and a null `presented_at_utc`.
        Design: Corner/entities/proposal_system_fields_are_server_minted_and_input_ignored
        """
        bundle = setup_qualified_inquiry(api)
        inquiry = bundle["inquiry"]

        proposal = validate_success(
            api.create_proposal(
                inquiry["id"], proposal_payload(inquiry["version"]), AGENT_HEADERS
            ),
            expected_status=201,
        )

        assert proposal["inquiry_id"] == inquiry["id"]
        assert proposal["status"] == "DRAFT"
        assert proposal["round_no"] == 1
        assert proposal["revision_count"] == 0
        assert proposal["options_count"] == 0
        assert proposal["presented_at_utc"] is None
        assert proposal["created_by_agent_user_id"] == AGENT_USER_ID
        assert proposal["version"] == 1
        assert is_valid_uuid(proposal["id"])
        assert read_inquiry(api, inquiry["id"])["version"] == inquiry["version"] + 1

    def test_a_second_feedback_filing_is_refused_and_the_first_score_stands(self, api):
        """The bureau records one rating per engagement, and a change of heart cannot overwrite it.

        PRD: Filing feedback requires the engagement's `booking_status` to be `DELIVERED` and the logical clock to be at or after `event_end_utc` — otherwise `ERR_EVENT_NOT_ENDED` — and a second attempt on the same engagement is refused with `ERR_FEEDBACK_ALREADY_SUBMITTED`.
        Design: Corner/entities/feedback_is_immutable_and_carries_no_version_field
        """
        bundle = setup_delivered_engagement_with_feedback(api)

        validate_error(
            api.create_feedback(
                bundle["engagement"]["id"],
                feedback_payload(
                    content_score=1,
                    logistics_score=1,
                    rebook_intent=False,
                    comment="changed my mind",
                ),
                bundle["client_headers"],
            ),
            ApiErrorId.ERR_FEEDBACK_ALREADY_SUBMITTED.value,
        )

        stored = read_feedback(api, bundle["feedback"]["id"])
        assert stored["content_score"] == 5
        assert stored["logistics_score"] == 4
        assert stored["composite_score"] == pytest.approx(4.60, abs=0.01)

        speaker = read_speaker(api, bundle["speaker"]["id"])
        assert speaker["feedback_count"] == 1
        assert speaker["rolling_score"] == pytest.approx(4.60, abs=0.01)

    def test_a_feedback_record_carries_no_version_or_updated_at(self, api):
        """The one append-only entity in the system exposes an identifier and a creation stamp and nothing else.

        PRD: Both `updated_at` and `version` are absent from a `Feedback` resource, and its `composite_score` is written once at creation and never recomputed even when the speaker's aggregate scores are.
        Design: Corner/entities/feedback_is_immutable_and_carries_no_version_field
        """
        bundle = setup_delivered_engagement_with_feedback(api)

        stored = read_feedback(api, bundle["feedback"]["id"])
        assert_append_only_fields(stored, "feedback")
        assert is_valid_uuid(stored["id"])
        assert stored["engagement_id"] == bundle["engagement"]["id"]
