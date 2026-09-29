"""Validation ordering, conditional pairs, aggregates and temporal screens.

The rejection ladder is observable, so these tests arrange two or more failures
at once and pin which one the server is obliged to report.  The remaining cases
cover a rule whose verdict depends on a sibling field, on the collective state
of a package, on a field of a third entity, or on the logical clock.
"""

from test_helpers import (
    ADMIN_HEADERS,
    AGENT_HEADERS,
    AGENT_USER_ID,
    ApiErrorId,
    NON_EXISTENT_UUID,
    UserRole,
    add_option,
    contract_payload,
    create_client,
    create_draft_proposal,
    create_inquiry,
    create_second_speaker,
    create_speaker,
    make_client_headers,
    make_headers_without_user_id,
    proposal_option_payload,
    qualify_inquiry,
    qualify_payload,
    read_engagement,
    read_inquiry,
    read_option,
    read_proposal,
    select_option_payload,
    set_clock,
    setup_confirmed_engagement,
    setup_contracted_engagement,
    setup_draft_proposal,
    setup_presented_proposal,
    validate_error,
    validate_paginated,
    validate_success,
)

SECOND_EVENT_START_UTC = "2026-12-05T16:00:00Z"
SECOND_EVENT_END_UTC = "2026-12-05T18:00:00Z"
SECOND_VALID_UNTIL_UTC = "2026-11-15T00:00:00Z"


class TestLadderPrecedenceOnTheOuterBands:
    def test_a_missing_caller_header_is_reported_before_the_role_is_judged(self, api):
        """A Client aiming at an agent-only action with no X-User-ID is unauthenticated, not unauthorised.

        PRD: **Authentication.** `X-User-ID` and `X-User-Role` both present, and the role one of the four declared names — otherwise `ERR_UNAUTHENTICATED` (401). Applies to every endpoint except the logical-clock capability.
        Design: Corner/validations/validation_missing_x_user_id_header_outranks_the_role_check
        """
        bundle = setup_draft_proposal(api)
        proposal = bundle["proposal"]

        validate_error(
            api.present_proposal(
                proposal["id"], make_headers_without_user_id(UserRole.CLIENT.value)
            ),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            expected_status=401,
        )

        unchanged = read_proposal(api, proposal["id"])
        assert unchanged["status"] == "DRAFT"
        assert unchanged["presented_at_utc"] is None
        assert unchanged["version"] == proposal["version"]

    def test_an_unresolvable_path_id_is_reported_before_the_body_is_parsed(self, api):
        """A commission adjustment against a phantom engagement answers 404 even though the body is also incomplete.

        PRD: A request naming a non-existent engagement and a well-formed but irrelevant body fails on the engagement, not on the body.
        Design: Corner/validations/validation_unknown_path_id_outranks_a_malformed_body
        """
        bundle = setup_contracted_engagement(api)
        engagement = read_engagement(api, bundle["engagement"]["id"])

        validate_error(
            api.create_commission_adjustment(
                NON_EXISTENT_UUID, {"reason": "typo in the id"}, ADMIN_HEADERS
            ),
            ApiErrorId.ERR_ENGAGEMENT_NOT_FOUND.value,
            expected_status=404,
        )

        after = read_engagement(api, engagement["id"])
        assert after["commission_adjustment_count"] == 0
        assert after["version"] == engagement["version"]


class TestQualificationPassesEveryScreen:
    def test_lead_time_budget_and_credit_all_clear_so_the_inquiry_qualifies(self, api):
        """Seventy-five days of lead time, a budget well over the floor and untouched credit take the inquiry to QUALIFIED.

        PRD: `QUALIFY` also demands that the inquiry be `RECEIVED`, and adds three commercial screens before moving it `RECEIVED → QUALIFIED`: the client's `credit_status` must not be `HOLD`, or the attempt is refused with `ERR_CLIENT_CREDIT_HOLD`; there must be at least three full weeks of lead time, meaning the whole days from the logical clock to `event_start_utc` must be at least 21, or the attempt is refused with `ERR_INSUFFICIENT_LEAD_TIME`; and `budget_cents` must be at least the engagement floor of 2,500 dollars — that is, 250,000 cents — or the attempt is refused with `ERR_BUDGET_BELOW_FLOOR`.
        Design: Corner/validations/validation_qualification_passes_when_lead_time_budget_and_credit_all_clear
        """
        set_clock(api)
        client_row = create_client(api)
        assert client_row["credit_status"] == "GOOD"

        inquiry = create_inquiry(api, client_row)
        assert inquiry["status"] == "RECEIVED"
        assert inquiry["budget_cents"] == 1_600_000
        assert inquiry["event_start_utc"].startswith("2026-10-15")

        qualified = validate_success(
            api.qualify_inquiry(
                inquiry["id"],
                qualify_payload(
                    qualification_note="budget, lead time and credit all clear"
                ),
                AGENT_HEADERS,
            )
        )
        assert qualified["status"] == "QUALIFIED"

    def test_both_qualification_branches_stamp_the_owner_the_note_and_the_version(
        self, api
    ):
        """The successful screen run also records who took the deal, what they wrote and one version step.

        PRD: A `BookingAgent` supplies an `outcome` of either `QUALIFY` or `DISQUALIFY` together with an optional `qualification_note`, and in **both** branches the server records the caller's `X-User-ID` as `owning_agent_user_id`, stores the `qualification_note`, and increments the inquiry's `version` by one.
        Design: Corner/validations/validation_qualification_passes_when_lead_time_budget_and_credit_all_clear
        """
        set_clock(api)
        client_row = create_client(api)
        inquiry = create_inquiry(api, client_row)
        assert inquiry["owning_agent_user_id"] is None
        assert inquiry["version"] == 1

        qualified = validate_success(
            api.qualify_inquiry(
                inquiry["id"],
                qualify_payload(
                    qualification_note="budget, lead time and credit all clear"
                ),
                AGENT_HEADERS,
            )
        )
        assert qualified["owning_agent_user_id"] == AGENT_USER_ID
        assert qualified["version"] == 2

        stored = read_inquiry(api, inquiry["id"])
        assert stored["status"] == "QUALIFIED"
        assert stored["owning_agent_user_id"] == AGENT_USER_ID
        assert (
            stored["qualification_note"] == "budget, lead time and credit all clear"
        )


class TestRecordingFeeConsistency:
    def test_both_directions_of_the_recording_pair_are_refused_and_paper_nothing(
        self, api
    ):
        """Rights of NONE with a fee and AUDIO_ONLY without one fail on opposite halves of the same rule.

        PRD: Recording rights and recording fee must agree with each other: if `recording_rights` is `NONE` then `recording_fee_cents` must be absent or 0, and a positive fee is refused with `ERR_RECORDING_FEE_NOT_ALLOWED`; conversely if `recording_rights` is `AUDIO_ONLY` or `FULL_BUY_OUT` then `recording_fee_cents` must be strictly greater than 0, and an absent or zero fee is refused with `ERR_RECORDING_FEE_REQUIRED`.
        Design: Corner/validations/validation_recording_fee_consistency_in_both_directions
        """
        bundle = setup_confirmed_engagement(api)
        engagement_id = bundle["engagement"]["id"]

        validate_error(
            api.create_contract(
                engagement_id,
                contract_payload(
                    travel_policy_code="POLICY_A",
                    recording_rights="NONE",
                    recording_fee_cents=100_000,
                ),
                AGENT_HEADERS,
            ),
            ApiErrorId.ERR_RECORDING_FEE_NOT_ALLOWED.value,
            expected_status=422,
        )

        omitted = contract_payload(
            travel_policy_code="POLICY_A", recording_rights="AUDIO_ONLY"
        )
        assert "recording_fee_cents" not in omitted
        validate_error(
            api.create_contract(engagement_id, omitted, AGENT_HEADERS),
            ApiErrorId.ERR_RECORDING_FEE_REQUIRED.value,
            expected_status=422,
        )

        _rows, meta = validate_paginated(
            api.list_contracts(AGENT_HEADERS, params={"engagement_id": engagement_id})
        )
        assert meta["total_count"] == 0

    def test_only_the_consistent_pair_drafts_an_agreement(self, api):
        """After two refusals the matching rights-and-fee pair papers exactly one DRAFT agreement.

        PRD: A drafted agreement starts in `DRAFT` with `speaker_signed_at_utc`, `client_signed_at_utc` and `executed_at_utc` all null; the status enumeration continues `SENT`, `PARTIALLY_SIGNED` and the two terminal values `EXECUTED` and `VOID`.
        Design: Corner/validations/validation_recording_fee_consistency_in_both_directions
        """
        bundle = setup_confirmed_engagement(api)
        engagement_id = bundle["engagement"]["id"]

        validate_error(
            api.create_contract(
                engagement_id,
                contract_payload(
                    travel_policy_code="POLICY_A",
                    recording_rights="NONE",
                    recording_fee_cents=100_000,
                ),
                AGENT_HEADERS,
            ),
            ApiErrorId.ERR_RECORDING_FEE_NOT_ALLOWED.value,
        )
        validate_error(
            api.create_contract(
                engagement_id,
                contract_payload(
                    travel_policy_code="POLICY_A", recording_rights="AUDIO_ONLY"
                ),
                AGENT_HEADERS,
            ),
            ApiErrorId.ERR_RECORDING_FEE_REQUIRED.value,
        )

        contract = validate_success(
            api.create_contract(
                engagement_id,
                contract_payload(
                    travel_policy_code="POLICY_A",
                    recording_rights="AUDIO_ONLY",
                    recording_fee_cents=350_000,
                ),
                AGENT_HEADERS,
            ),
            expected_status=201,
        )
        assert contract["status"] == "DRAFT"
        assert contract["recording_rights"] == "AUDIO_ONLY"
        assert contract["recording_fee_cents"] == 350_000
        assert contract["speaker_signed_at_utc"] is None
        assert contract["client_signed_at_utc"] is None
        assert contract["executed_at_utc"] is None

        _rows, meta = validate_paginated(
            api.list_contracts(AGENT_HEADERS, params={"engagement_id": engagement_id})
        )
        assert meta["total_count"] == 1


class TestOptionLimitIsAnAggregate:
    def _four_option_package(self, api) -> dict:
        set_clock(api)
        first = create_speaker(api)
        client_row = create_client(api)
        inquiry = qualify_inquiry(api, create_inquiry(api, client_row)["id"])
        proposal = create_draft_proposal(api, inquiry)

        second = create_second_speaker(api, topics=["AI_STRATEGY"])
        third = create_speaker(
            api,
            full_name="Noor Haddad",
            topics=["AI_STRATEGY"],
            fee_floor_cents=800_000,
            fee_ceiling_cents=1_500_000,
            travel_class="ECONOMY",
        )
        fourth = create_speaker(
            api,
            full_name="Ines Duarte",
            topics=["AI_STRATEGY"],
            fee_floor_cents=700_000,
            fee_ceiling_cents=1_400_000,
            travel_class="ECONOMY",
        )
        fifth = create_speaker(
            api,
            full_name="Tomas Berg",
            topics=["AI_STRATEGY"],
            fee_floor_cents=600_000,
            fee_ceiling_cents=1_300_000,
            travel_class="ECONOMY",
        )

        add_option(api, proposal, first, quoted_fee_cents=1_275_000, rank_no=1)
        add_option(api, proposal, second, quoted_fee_cents=1_150_000, rank_no=2)
        add_option(api, proposal, third, quoted_fee_cents=1_050_000, rank_no=3)
        add_option(api, proposal, fourth, quoted_fee_cents=950_000, rank_no=4)
        return {"proposal": proposal, "fifth_speaker": fifth}

    def test_four_individually_valid_options_all_land_on_one_package(self, api):
        """Each of the four quotes clears its own speaker's range and the budget cap, so the counter reaches four.

        PRD: Adding an option increments the parent package's `options_count` by one and its `version` by one.
        Design: Corner/validations/validation_option_limit_is_an_aggregate_over_siblings
        """
        scenario = self._four_option_package(api)
        proposal = read_proposal(api, scenario["proposal"]["id"])

        assert proposal["options_count"] == 4
        assert proposal["status"] == "DRAFT"
        assert proposal["version"] == scenario["proposal"]["version"] + 4

        rows, meta = validate_paginated(
            api.list_proposal_options(
                AGENT_HEADERS, params={"proposal_id": proposal["id"]}
            )
        )
        assert meta["total_count"] == 4
        assert sorted(row["rank_no"] for row in rows) == [1, 2, 3, 4]
        assert all(row["status"] == "OFFERED" for row in rows)

    def test_the_fifth_option_reports_the_limit_rather_than_the_reused_rank(self, api):
        """A fifth quote that also reuses rank 4 fails on the aggregate count, because 16(b) precedes 16(d).

        PRD: **Structural constraints** (409 throughout), in this internal order: (a) presenting a package with no live options — `ERR_PROPOSAL_NO_OPTIONS`; (b) adding an option beyond the fourth — `ERR_OPTION_LIMIT_REACHED`; (c) quoting a speaker already quoted on a sibling option of the same proposal — `ERR_DUPLICATE_SPEAKER_OPTION`; (d) reusing a `rank_no` already taken on the same proposal — `ERR_DUPLICATE_RANK`; (e) requesting a revision beyond the second — `ERR_REVISION_LIMIT_REACHED`; (f) opening a duplicate claim — `ERR_DUPLICATE_CLAIM`.
        Design: Corner/validations/validation_option_limit_is_an_aggregate_over_siblings
        """
        scenario = self._four_option_package(api)
        proposal = read_proposal(api, scenario["proposal"]["id"])

        validate_error(
            api.create_proposal_option(
                proposal_option_payload(
                    proposal["id"],
                    scenario["fifth_speaker"]["id"],
                    quoted_fee_cents=900_000,
                    rank_no=4,
                ),
                AGENT_HEADERS,
            ),
            ApiErrorId.ERR_OPTION_LIMIT_REACHED.value,
            expected_status=409,
        )

        after = read_proposal(api, proposal["id"])
        assert after["options_count"] == 4
        assert after["version"] == proposal["version"]

        _rows, meta = validate_paginated(
            api.list_proposal_options(
                AGENT_HEADERS, params={"proposal_id": proposal["id"]}
            )
        )
        assert meta["total_count"] == 4


class TestTopicIsCheckedAgainstTheRoster:
    def test_a_speaker_without_the_required_topic_cannot_be_quoted(self, api):
        """The quote clears the fee range and the budget cap and still fails, because the roster entry lacks the topic.

        PRD: The inquiry's `required_topic` must appear in that speaker's `topics`, or the request is refused with `ERR_TOPIC_NOT_IN_ROSTER`.
        Design: Corner/validations/validation_topic_not_in_roster_is_a_cross_entity_check
        """
        set_clock(api)
        create_speaker(api)
        client_row = create_client(api)
        inquiry = qualify_inquiry(api, create_inquiry(api, client_row)["id"])
        assert inquiry["required_topic"] == "AI_STRATEGY"
        proposal = create_draft_proposal(api, inquiry)

        off_topic = create_second_speaker(api, topics=["LEADERSHIP"])
        assert off_topic["roster_status"] == "ACTIVE"
        assert off_topic["fee_floor_cents"] <= 1_150_000 <= off_topic["fee_ceiling_cents"]

        validate_error(
            api.create_proposal_option(
                proposal_option_payload(
                    proposal["id"],
                    off_topic["id"],
                    quoted_fee_cents=1_150_000,
                    rank_no=1,
                ),
                AGENT_HEADERS,
            ),
            ApiErrorId.ERR_TOPIC_NOT_IN_ROSTER.value,
            expected_status=409,
        )

        after = read_proposal(api, proposal["id"])
        assert after["options_count"] == 0
        assert after["version"] == proposal["version"]


class TestExpiryIsMeasuredAgainstTheClock:
    def test_a_selectable_package_becomes_unselectable_once_the_clock_passes_it(
        self, api
    ):
        """Nothing changes but the clock, and the same selection that would have booked the event is refused.

        PRD: **Calendar and clock** (409 throughout), in this internal order: (a) calendar conflict on confirmation or on a manual hold — `ERR_SPEAKER_CALENDAR_CONFLICT`; (b) insufficient lead time at qualification — `ERR_INSUFFICIENT_LEAD_TIME`; (c) an expired quotation when presenting, selecting or requesting a revision — `ERR_PROPOSAL_EXPIRED`; (d) the event window has not closed when delivering or filing feedback — `ERR_EVENT_NOT_ENDED`; (e) a directly booked event outside the protection window on claim creation — `ERR_OUTSIDE_PROTECTION_WINDOW`.
        Design: Corner/validations/validation_proposal_expiry_is_measured_against_the_logical_clock
        """
        bundle = setup_presented_proposal(api)
        proposal = bundle["proposal"]
        assert proposal["status"] == "PRESENTED"
        assert proposal["valid_until_utc"].startswith("2026-09-20T00:00:00")

        set_clock(api, "2026-09-21T00:00:00Z")

        validate_error(
            api.select_proposal_option(
                proposal["id"],
                select_option_payload(bundle["option"]["id"]),
                bundle["client_headers"],
            ),
            ApiErrorId.ERR_PROPOSAL_EXPIRED.value,
            expected_status=409,
        )

        assert read_proposal(api, proposal["id"])["status"] == "PRESENTED"
        assert read_option(api, bundle["option"]["id"])["status"] == "OFFERED"
        assert read_inquiry(api, bundle["inquiry"]["id"])["status"] == "PROPOSED"

        _rows, meta = validate_paginated(
            api.list_engagements(ADMIN_HEADERS, params={"limit": 10})
        )
        assert meta["total_count"] == 0


class TestOptionMembership:
    def test_an_option_from_a_sibling_package_cannot_be_selected(self, api):
        """Two live packages for one client, and naming the other one's quote is refused on membership alone.

        PRD: A `Client` names a single `option_id`, and the server checks that the package is `PRESENTED`, that the logical clock is strictly before `valid_until_utc`, that the named option belongs to the package in the path — a mismatch being `ERR_OPTION_NOT_IN_PROPOSAL` — that the option's own `status` is `OFFERED`, and that the client's `credit_status` is not `HOLD`.
        Design: Corner/validations/validation_selected_option_must_belong_to_the_path_proposal
        """
        bundle = setup_presented_proposal(api)
        client_headers = make_client_headers(bundle["client"]["id"])

        second_inquiry = qualify_inquiry(
            api,
            create_inquiry(
                api,
                bundle["client"],
                event_start_utc=SECOND_EVENT_START_UTC,
                event_end_utc=SECOND_EVENT_END_UTC,
                audience_size=400,
                objective_tags=["TRAINING"],
            )["id"],
        )
        second_proposal = create_draft_proposal(
            api, second_inquiry, valid_until_utc=SECOND_VALID_UNTIL_UTC
        )
        second_option = add_option(api, second_proposal, bundle["speaker"])
        validate_success(api.present_proposal(second_proposal["id"], AGENT_HEADERS))

        validate_error(
            api.select_proposal_option(
                bundle["proposal"]["id"],
                select_option_payload(second_option["id"]),
                client_headers,
            ),
            ApiErrorId.ERR_OPTION_NOT_IN_PROPOSAL.value,
            expected_status=409,
        )

        assert read_proposal(api, bundle["proposal"]["id"])["status"] == "PRESENTED"
        assert read_proposal(api, second_proposal["id"])["status"] == "PRESENTED"
        assert read_option(api, bundle["option"]["id"])["status"] == "OFFERED"
        assert read_option(api, second_option["id"])["status"] == "OFFERED"
        assert read_inquiry(api, bundle["inquiry"]["id"])["status"] == "PROPOSED"
        assert read_inquiry(api, second_inquiry["id"])["status"] == "PROPOSED"

        _rows, meta = validate_paginated(
            api.list_engagements(ADMIN_HEADERS, params={"limit": 10})
        )
        assert meta["total_count"] == 0
