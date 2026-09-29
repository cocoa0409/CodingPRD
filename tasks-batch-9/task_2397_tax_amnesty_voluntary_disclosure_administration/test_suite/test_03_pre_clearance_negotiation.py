"""Anonymous pre-clearance, the mediated negotiation cycle and disclosure.

The bargaining workflow of PRD §3.3 is the one place where the same resource
cycles between two states, so this module walks the offer/counter loop to its
bound, the two automatic rejection branches, and the moment anonymity ends.
"""

from test_helpers import (
    ADMIN_HEADERS,
    OFFICER_ALPHA_HEADERS,
    OFFICER_ALPHA_USER_ID,
    ApiErrorId,
    assert_append_only_fields,
    assert_fields,
    assert_list_total,
    assert_timestamp_with_millis,
    counter_payload,
    disclose_identity_payload,
    is_valid_uuid,
    make_representative_headers,
    offer_terms_payload,
    pre_clearance_payload,
    read_pre_clearance,
    register_representative,
    register_taxpayer,
    reject_pre_clearance_payload,
    setup_open_program,
    validate_error,
    validate_success,
)


def _submit_pre_clearance(api, ctx, **overrides):
    """Register a firm and submit one anonymous request under the open program."""
    representative = ctx.get("representative") or register_representative(api)
    ctx["representative"] = representative
    ctx["representative_headers"] = make_representative_headers(representative["id"])
    pre_clearance = validate_success(
        api.create_pre_clearance(
            pre_clearance_payload(ctx["program"]["id"], **overrides),
            ctx["representative_headers"],
        ),
        201,
    )
    ctx["pre_clearance"] = pre_clearance
    return pre_clearance


def _begin_review(api, ctx):
    pre_clearance = validate_success(
        api.begin_pre_clearance_review(
            ctx["pre_clearance"]["id"], OFFICER_ALPHA_HEADERS
        )
    )
    ctx["pre_clearance"] = pre_clearance
    return pre_clearance


def _offer(api, ctx, lookback_months, penalty_pct, interest_pct, **overrides):
    pre_clearance = validate_success(
        api.offer_terms(
            ctx["pre_clearance"]["id"],
            offer_terms_payload(
                ctx["pre_clearance"]["version"],
                offered_lookback_months=lookback_months,
                offered_penalty_waiver_pct=penalty_pct,
                offered_interest_waiver_pct=interest_pct,
                **overrides,
            ),
            OFFICER_ALPHA_HEADERS,
        )
    )
    ctx["pre_clearance"] = pre_clearance
    return pre_clearance


def _counter(api, ctx, lookback_months, penalty_pct, interest_pct):
    pre_clearance = validate_success(
        api.counter_terms(
            ctx["pre_clearance"]["id"],
            counter_payload(
                counter_lookback_months=lookback_months,
                counter_penalty_waiver_pct=penalty_pct,
                counter_interest_waiver_pct=interest_pct,
            ),
            ctx["representative_headers"],
        )
    )
    ctx["pre_clearance"] = pre_clearance
    return pre_clearance


class TestNegotiationCycle:
    """The alternating offer/counter exchange and its bound (PRD §3.3)."""

    def test_three_counters_cycle_then_the_fourth_is_refused(self, api):
        """Four state offers and three counters exhaust the representative's quota.

        PRD §3.3: "Crucially, the loop is bounded: a representative may post at
        most **three** counters on a single request, and the fourth is refused
        with `ERR_NEGOTIATION_ROUND_LIMIT`. Because the state's `current_offer_*`
        mirrors always reflect the newest `STATE` round, a counter does not erase
        the standing offer — it only stops the request from being accepted until
        the officer responds. The cycle `TERMS_OFFERED → COUNTERED →
        TERMS_OFFERED` may therefore turn at most three times."

        PRD §3.3: "Every negotiation round remains readable afterwards by its
        owning `pre_clearance_id`, and a round may be filtered by `proposed_by`."

        Design: Difficulty/non_linear_state_machine/negotiation_cycles_three_counters_then_hits_counter_limit
        """
        ctx = setup_open_program(api)
        _submit_pre_clearance(
            api,
            ctx,
            anonymous_alias="CLIENT-90",
            estimated_liability_cents=4200000,
            earliest_unfiled_period_start="2023-10-01",
        )
        _begin_review(api, ctx)

        _offer(api, ctx, 36, 0.60, 0.20, offer_note="opening position")
        _counter(api, ctx, 24, 1.00, 0.60)
        _offer(api, ctx, 36, 0.80, 0.30)
        _counter(api, ctx, 30, 1.00, 0.55)
        _offer(api, ctx, 36, 0.90, 0.40)
        _counter(api, ctx, 33, 1.00, 0.50)
        _offer(api, ctx, 36, 1.00, 0.45)

        pre_clearance_id = ctx["pre_clearance"]["id"]
        validate_error(
            api.counter_terms(
                pre_clearance_id,
                counter_payload(
                    counter_lookback_months=36,
                    counter_penalty_waiver_pct=1.00,
                    counter_interest_waiver_pct=0.50,
                ),
                ctx["representative_headers"],
            ),
            ApiErrorId.NEGOTIATION_ROUND_LIMIT,
        )

        final = read_pre_clearance(api, pre_clearance_id)
        assert_fields(
            final,
            status="TERMS_OFFERED",
            round_index=7,
            counter_count=3,
            current_offer_penalty_waiver_pct=1.00,
            current_offer_interest_waiver_pct=0.45,
        )
        assert_list_total(
            api.list_negotiation_rounds(pre_clearance_id, ADMIN_HEADERS, {"limit": 100}),
            7,
        )
        assert_list_total(
            api.list_negotiation_rounds(
                pre_clearance_id,
                ADMIN_HEADERS,
                {"proposed_by": "REPRESENTATIVE", "limit": 100},
            ),
            3,
        )

    def test_a_counter_leaves_the_standing_offer_in_place(self, api):
        """Countering advances both counters but never rewrites the state terms.

        PRD §3.3: "the request's `round_index` and `counter_count` each advance
        by one, `status` becomes `COUNTERED`, and `version` advances by one."

        PRD §3.3: "Because the state's `current_offer_*` mirrors always reflect
        the newest `STATE` round, a counter does not erase the standing offer"

        Design: Difficulty/non_linear_state_machine/negotiation_cycles_three_counters_then_hits_counter_limit
        """
        ctx = setup_open_program(api)
        _submit_pre_clearance(
            api,
            ctx,
            anonymous_alias="CLIENT-90",
            estimated_liability_cents=4200000,
            earliest_unfiled_period_start="2023-10-01",
        )
        _begin_review(api, ctx)
        _offer(api, ctx, 36, 0.60, 0.20, offer_note="opening position")
        countered = _counter(api, ctx, 24, 1.00, 0.60)

        assert_fields(
            countered,
            status="COUNTERED",
            round_index=2,
            counter_count=1,
            current_offer_lookback_months=36,
            current_offer_penalty_waiver_pct=0.60,
            current_offer_interest_waiver_pct=0.20,
            last_offer_officer_user_id=OFFICER_ALPHA_USER_ID,
        )

    def test_the_history_records_each_side_of_the_exchange_in_order(self, api):
        """Rounds accumulate one per act, numbered from the request's counter.

        PRD §3.3: "Posting an offer appends a round whose `proposed_by` is
        `STATE`, whose `round_index` is one greater than the request's current
        `round_index`"

        PRD §3.3: "appends a round whose `proposed_by` is `REPRESENTATIVE` with
        `round_index` one greater than the current value"

        Design: Difficulty/non_linear_state_machine/negotiation_cycles_three_counters_then_hits_counter_limit
        """
        ctx = setup_open_program(api)
        _submit_pre_clearance(
            api,
            ctx,
            anonymous_alias="CLIENT-90",
            estimated_liability_cents=4200000,
            earliest_unfiled_period_start="2023-10-01",
        )
        _begin_review(api, ctx)
        _offer(api, ctx, 36, 0.60, 0.20, offer_note="opening position")
        _counter(api, ctx, 24, 1.00, 0.60)
        _offer(api, ctx, 36, 0.80, 0.30)

        pre_clearance_id = ctx["pre_clearance"]["id"]
        rows = assert_list_total(
            api.list_negotiation_rounds(pre_clearance_id, ADMIN_HEADERS, {"limit": 100}),
            3,
        )
        by_index = {row["round_index"]: row for row in rows}
        assert sorted(by_index) == [1, 2, 3]
        assert by_index[1]["proposed_by"] == "STATE"
        assert by_index[2]["proposed_by"] == "REPRESENTATIVE"
        assert by_index[3]["proposed_by"] == "STATE"

        assert_list_total(
            api.list_negotiation_rounds(
                pre_clearance_id, ADMIN_HEADERS, {"proposed_by": "STATE", "limit": 100}
            ),
            2,
        )
        assert_list_total(
            api.list_negotiation_rounds(
                pre_clearance_id,
                ADMIN_HEADERS,
                {"proposed_by": "REPRESENTATIVE", "limit": 100},
            ),
            1,
        )


class TestSuspendedRepresentative:
    """Suspension freezes the firm's side of a live negotiation (PRD §3.2)."""

    def test_a_suspended_firm_cannot_counter_the_standing_offer(self, api):
        """The representative's own status is checked on every counter.

        PRD §3.2: "An administrator may later suspend a representative, moving
        `status` to `SUSPENDED`, which blocks every further negotiation act by
        that firm with `ERR_REPRESENTATIVE_SUSPENDED`."

        PRD §3.3: "requires the acting representative's own `status` to be
        `ACTIVE`, so suspending a firm mid-negotiation freezes it."

        Design: Difficulty/cross_entity_state_dependency/suspended_representative_gates_only_representative_side_negotiation
        """
        ctx = setup_open_program(api)
        _submit_pre_clearance(
            api,
            ctx,
            anonymous_alias="CLIENT-45",
            estimated_liability_cents=600000,
            earliest_unfiled_period_start="2024-10-01",
        )
        _begin_review(api, ctx)
        _offer(api, ctx, 36, 0.70, 0.30)

        suspended = validate_success(
            api.suspend_representative(ctx["representative"]["id"], ADMIN_HEADERS)
        )
        assert_fields(suspended, status="SUSPENDED")

        pre_clearance_id = ctx["pre_clearance"]["id"]
        validate_error(
            api.counter_terms(
                pre_clearance_id,
                counter_payload(
                    counter_lookback_months=24,
                    counter_penalty_waiver_pct=1.00,
                    counter_interest_waiver_pct=0.60,
                ),
                ctx["representative_headers"],
            ),
            ApiErrorId.REPRESENTATIVE_SUSPENDED,
        )

        unchanged = read_pre_clearance(api, pre_clearance_id)
        assert_fields(
            unchanged,
            status="TERMS_OFFERED",
            counter_count=0,
            current_offer_penalty_waiver_pct=0.70,
        )
        assert_list_total(
            api.list_negotiation_rounds(pre_clearance_id, ADMIN_HEADERS, {"limit": 100}),
            1,
        )

    def test_the_officer_may_still_close_the_file_of_a_suspended_firm(self, api):
        """Suspension gates the firm's acts, not the state's.

        PRD §3.3: "An officer may also close the file at any negotiable point,
        moving `UNDER_REVIEW → REJECTED`, `TERMS_OFFERED → REJECTED` or
        `COUNTERED → REJECTED` and recording the supplied `rejection_reason`
        verbatim"

        Design: Difficulty/cross_entity_state_dependency/suspended_representative_gates_only_representative_side_negotiation
        """
        ctx = setup_open_program(api)
        _submit_pre_clearance(
            api,
            ctx,
            anonymous_alias="CLIENT-45",
            estimated_liability_cents=600000,
            earliest_unfiled_period_start="2024-10-01",
        )
        _begin_review(api, ctx)
        _offer(api, ctx, 36, 0.70, 0.30)
        validate_success(
            api.suspend_representative(ctx["representative"]["id"], ADMIN_HEADERS)
        )

        rejected = validate_success(
            api.reject_pre_clearance(
                ctx["pre_clearance"]["id"],
                reject_pre_clearance_payload(
                    rejection_reason="REPRESENTATIVE_SUSPENDED_BY_BOARD"
                ),
                OFFICER_ALPHA_HEADERS,
            )
        )
        assert_fields(
            rejected,
            status="REJECTED",
            rejection_reason="REPRESENTATIVE_SUSPENDED_BY_BOARD",
            round_index=1,
            counter_count=0,
        )


class TestEligibilityScreen:
    """Beginning review forks on the representative's own declaration."""

    def test_a_self_reported_audit_is_rejected_without_officer_discretion(self, api):
        """The screen takes the automatic branch straight to `REJECTED`.

        PRD §3.3: "When `self_reported_under_audit` is true the same operation
        instead takes the automatic branch `SUBMITTED → REJECTED`, setting
        `screening_result` to `INELIGIBLE_SELF_REPORTED_AUDIT` and copying that
        same enum name into `rejection_reason` as a string — no officer
        discretion is involved, a self-declared audit subject is simply
        excluded."

        Design: Corner/Table 2 State Machines/begin_review_branches_straight_to_rejected_on_a_self_reported_audit
        """
        ctx = setup_open_program(api)
        ctx["representative"] = register_representative(
            api, firm_name="Ferro Tax Group", bar_number="BAR-71230"
        )
        _submit_pre_clearance(
            api,
            ctx,
            anonymous_alias="CLIENT-19",
            estimated_liability_cents=1200000,
            self_reported_under_audit=True,
            earliest_unfiled_period_start="2023-11-01",
        )

        screened = _begin_review(api, ctx)
        assert_fields(
            screened,
            status="REJECTED",
            screening_result="INELIGIBLE_SELF_REPORTED_AUDIT",
            rejection_reason="INELIGIBLE_SELF_REPORTED_AUDIT",
            round_index=0,
        )
        assert_list_total(
            api.list_negotiation_rounds(screened["id"], ADMIN_HEADERS, {"limit": 100}),
            0,
        )
        assert_list_total(
            api.list_pre_clearances(ADMIN_HEADERS, {"status": "REJECTED"}), 1
        )


class TestNegotiationRoundRecord:
    """A round is written once and never revised (PRD §2.4)."""

    def test_a_round_carries_no_version_and_no_updated_at(self, api):
        """The append-only exception to the common audit fields.

        PRD §2.4: "The one exception is the `NegotiationRound`: a negotiation
        round is an append-only record of what was proposed and by whom, is
        never modified after creation, and therefore carries only `id` and
        `created_at` — it has neither `updated_at` nor `version`."

        PRD §3.3: "whose `lookback_months`, `penalty_waiver_pct` and
        `interest_waiver_pct` are the offered figures, whose `note` holds the
        supplied note, and whose `actor_user_id` is the officer's `X-User-ID`."

        Design: Corner/Table 1 Entities/negotiation_round_is_immutable_and_carries_no_version
        """
        ctx = setup_open_program(api)
        ctx["representative"] = register_representative(
            api, firm_name="Marlowe & Pike LLP", bar_number="BAR-33417"
        )
        _submit_pre_clearance(
            api,
            ctx,
            anonymous_alias="CLIENT-07",
            estimated_liability_cents=900000,
            earliest_unfiled_period_start="2024-04-01",
        )
        _begin_review(api, ctx)
        _offer(api, ctx, 30, 0.60, 0.30, offer_note="opening position")

        rows = assert_list_total(
            api.list_negotiation_rounds(
                ctx["pre_clearance"]["id"], ADMIN_HEADERS, {"limit": 100}
            ),
            1,
        )
        round_row = validate_success(
            api.get_negotiation_round(rows[0]["id"], ADMIN_HEADERS)
        )

        assert is_valid_uuid(round_row["id"])
        assert_timestamp_with_millis(round_row["created_at"])
        assert_append_only_fields(round_row)
        assert_fields(
            round_row,
            round_index=1,
            proposed_by="STATE",
            lookback_months=30,
            penalty_waiver_pct=0.60,
            interest_waiver_pct=0.30,
            note="opening position",
            actor_user_id=OFFICER_ALPHA_USER_ID,
        )


class TestIdentityDisclosure:
    """Anonymity ends exactly once, and acceptance waits for it."""

    def test_acceptance_waits_for_disclosure_and_disclosure_never_repeats(self, api):
        """The self-loop is idempotent in name only — the second call is refused.

        PRD §3.3: "Disclosing carries a `taxpayer_id` and requires the request to
        be in `TERMS_OFFERED`, requires the referenced taxpayer to exist, and
        requires that `disclosed_taxpayer_id` is still null — a second
        disclosure is refused with `ERR_IDENTITY_ALREADY_DISCLOSED`."

        PRD §3.3: "When the named taxpayer carries no blocking record, the
        request stays in `TERMS_OFFERED` — the transition is a self-loop — with
        `disclosed_taxpayer_id` set from the payload and `screening_result` set
        to `ELIGIBLE`."

        PRD §3.3: "Accepting moves the request `TERMS_OFFERED → ACCEPTED` and
        requires four things: a standing offer, a non-null
        `disclosed_taxpayer_id` — accepting while still anonymous is refused
        with `ERR_IDENTITY_NOT_DISCLOSED` — an `ACTIVE` representative, and an
        `OPEN` program."

        Design: Corner/Table 6 Errors/identity_disclosure_gates_acceptance_and_cannot_be_repeated
        """
        ctx = setup_open_program(api)
        ctx["representative"] = register_representative(
            api, firm_name="Quill & Rowe Tax Counsel", bar_number="BAR-55120"
        )
        taxpayer = register_taxpayer(
            api, legal_name="Greyloch Distribution Inc", tin_last4="4408"
        )
        _submit_pre_clearance(
            api,
            ctx,
            anonymous_alias="CLIENT-ORCHID",
            estimated_liability_cents=900000,
            earliest_unfiled_period_start="2024-01-01",
        )
        _begin_review(api, ctx)
        _offer(api, ctx, 30, 0.80, 0.40)

        pre_clearance_id = ctx["pre_clearance"]["id"]
        rep_headers = ctx["representative_headers"]

        validate_error(
            api.accept_pre_clearance(pre_clearance_id, rep_headers),
            ApiErrorId.IDENTITY_NOT_DISCLOSED,
        )

        disclosed = validate_success(
            api.disclose_identity(
                pre_clearance_id,
                disclose_identity_payload(taxpayer["id"]),
                rep_headers,
            )
        )
        assert_fields(
            disclosed,
            status="TERMS_OFFERED",
            disclosed_taxpayer_id=taxpayer["id"],
            screening_result="ELIGIBLE",
        )

        validate_error(
            api.disclose_identity(
                pre_clearance_id,
                disclose_identity_payload(taxpayer["id"]),
                rep_headers,
            ),
            ApiErrorId.IDENTITY_ALREADY_DISCLOSED,
        )
        assert_fields(
            read_pre_clearance(api, pre_clearance_id),
            disclosed_taxpayer_id=taxpayer["id"],
        )

        accepted = validate_success(
            api.accept_pre_clearance(pre_clearance_id, rep_headers)
        )
        assert_fields(
            accepted,
            status="ACCEPTED",
            disclosed_taxpayer_id=taxpayer["id"],
            screening_result="ELIGIBLE",
            current_offer_lookback_months=30,
            current_offer_penalty_waiver_pct=0.80,
            counter_count=0,
        )
        assert_list_total(
            api.list_pre_clearances(
                ADMIN_HEADERS, {"disclosed_taxpayer_id": taxpayer["id"]}
            ),
            1,
        )


class TestOfferStaleness:
    """The offer's optimistic concurrency check runs before its payload rules."""

    def test_a_stale_expected_version_is_refused_before_the_lookback_rule(self, api):
        """A too-deep lookback on a stale view reports staleness, not the depth.

        PRD §2.8: "A mismatch with the current `version` is rejected with
        `ERR_STALE_PRE_CLEARANCE_VERSION` (HTTP 412). A new offer supersedes the
        standing one, so an officer writing from a stale view of the negotiation
        — an unseen counter, an unseen identity disclosure — must be refused."

        PRD §3.3: "The first offer additionally requires
        `offered_lookback_months` to be no greater than the program's
        `lookback_months`; a deeper offer is refused with
        `ERR_LOOKBACK_EXCEEDS_PROGRAM_LIMIT`."

        Design: Corner/Cross-Cutting Complexity Layers/stale_expected_pre_clearance_version_is_refused_before_the_payload_rule
        """
        ctx = setup_open_program(api)
        ctx["representative"] = register_representative(
            api, firm_name="Vane & Ash LLP", bar_number="BAR-77341"
        )
        submitted = _submit_pre_clearance(
            api,
            ctx,
            anonymous_alias="CLIENT-JUNIPER",
            estimated_liability_cents=1400000,
            earliest_unfiled_period_start="2024-04-01",
        )
        stale_version = submitted["version"]
        _begin_review(api, ctx)

        pre_clearance_id = submitted["id"]
        validate_error(
            api.offer_terms(
                pre_clearance_id,
                offer_terms_payload(
                    stale_version,
                    offered_lookback_months=48,
                    offered_penalty_waiver_pct=0.90,
                    offered_interest_waiver_pct=0.45,
                ),
                OFFICER_ALPHA_HEADERS,
            ),
            ApiErrorId.STALE_PRE_CLEARANCE_VERSION,
        )

        fresh_version = read_pre_clearance(api, pre_clearance_id)["version"]
        assert fresh_version == stale_version + 1

        validate_error(
            api.offer_terms(
                pre_clearance_id,
                offer_terms_payload(
                    fresh_version,
                    offered_lookback_months=48,
                    offered_penalty_waiver_pct=0.90,
                    offered_interest_waiver_pct=0.45,
                ),
                OFFICER_ALPHA_HEADERS,
            ),
            ApiErrorId.LOOKBACK_EXCEEDS_PROGRAM_LIMIT,
        )
        assert_fields(
            read_pre_clearance(api, pre_clearance_id),
            status="UNDER_REVIEW",
            round_index=0,
        )

        offered = validate_success(
            api.offer_terms(
                pre_clearance_id,
                offer_terms_payload(
                    fresh_version,
                    offered_lookback_months=36,
                    offered_penalty_waiver_pct=0.90,
                    offered_interest_waiver_pct=0.45,
                ),
                OFFICER_ALPHA_HEADERS,
            )
        )
        assert_fields(
            offered,
            status="TERMS_OFFERED",
            round_index=1,
            counter_count=0,
            current_offer_lookback_months=36,
            last_offer_officer_user_id=OFFICER_ALPHA_USER_ID,
        )
        assert_list_total(
            api.list_negotiation_rounds(
                pre_clearance_id, ADMIN_HEADERS, {"proposed_by": "STATE", "limit": 100}
            ),
            1,
        )
