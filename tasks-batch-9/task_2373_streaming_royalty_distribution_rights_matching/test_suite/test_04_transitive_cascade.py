"""Chained cascades in the royalty distribution API.

Two operations reach far beyond the record they name. Approving one ownership
claim settles the registration, which re-derives the work, which claim-matches a
previously unresolved reported play, which in turn re-counts its batch and
re-attributes its calculated pool. Promulgating a retroactive rate schedule
reaches one level further still: schedule, then finalized pools, then issued
statements and payee balances, then the closed accounting period itself.
"""

from test_helpers import (
    ANALYST_REVIEWER_USER_ID,
    TEST_DEFAULTS,
    TEST_USERS,
    assert_play_count_conservation,
    assert_pool_value_conservation,
    calculate_pool,
    create_calculated_pool,
    create_schedule,
    create_statement,
    file_registration_under_review,
    finalize_pool,
    setup_all_matched_closed_period,
    setup_canonical_matched_batch,
    validate_paginated,
    validate_success,
)

ADMIN_HEADERS = TEST_USERS["royalty_admin_headers"]
ANALYST_HEADERS = TEST_USERS["rights_ops_analyst_headers"]
REGULATOR_HEADERS = TEST_USERS["regulatory_officer_headers"]
REVIEWER_HEADERS = TEST_USERS["reviewer_headers"]


# ─────────────────────────────────────────────────────
# Composite preconditions
# ─────────────────────────────────────────────────────

def _setup_calculated_pool_with_an_unresolved_line(api):
    """The canonical GB/INDIVIDUAL usage with its pool CALCULATED but not frozen.

    Three reported lines land in the 2026-06 batch: 300000 plays resolved by an
    exact ISRC, 150000 plays resolved by normalized title and artist, and 50000
    plays reported as the bare title 'Neon Ledger', which reaches only a
    title-only agreement and is therefore left unattached.
    """
    fixture = setup_canonical_matched_batch(api)
    fixture["pool"] = create_calculated_pool(api, fixture["period"]["id"])
    return fixture


def _setup_claim_under_review_over_the_unresolved_recording(api):
    """The same state, plus a MASTER claim over 'Neon Ledger' in UNDER_REVIEW."""
    fixture = _setup_calculated_pool_with_an_unresolved_line(api)
    fixture["claim"] = file_registration_under_review(
        api,
        fixture["recording_b"]["id"],
        fixture["label"]["id"],
        right_type="MASTER",
        routing="DIRECT",
        share_bps=10000,
        territory_set=["WORLD"],
    )
    return fixture


def _setup_closed_period_with_a_retroactive_proposal(api):
    """The all-matched GB/INDIVIDUAL fixture carried to a CLOSED period, plus a
    PROPOSED retroactive replacement schedule for the same territory and tier.

    The replacement raises the revenue share from 7000 to 8000 basis points and
    keeps the statutory floor at 100 millicents per play, so the ratchet gate
    passes.
    """
    fixture = setup_all_matched_closed_period(api)
    fixture["remand_schedule"] = create_schedule(
        api,
        proceeding_ref=TEST_DEFAULTS["SCHEDULE_REMAND_REF"],
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        revenue_share_bps=8000,
        per_subscriber_minimum_cents=500,
        mechanical_share_bps=4000,
        performance_share_bps=6000,
        statutory_floor_per_play_millicents=100,
        effective_from=TEST_DEFAULTS["SCHEDULE_EFFECTIVE_FROM"],
        effective_to=TEST_DEFAULTS["SCHEDULE_EFFECTIVE_TO"],
        retroactive=True,
    )
    return fixture


def _setup_corrected_statement_after_the_reopen(api, fixture):
    """Recover the reopened pool and build the label's corrected statement."""
    calculate_pool(api, fixture["pool"]["id"])
    finalize_pool(api, fixture["pool"]["id"])
    return create_statement(api, fixture["label"]["id"], fixture["period"]["id"])


# ─────────────────────────────────────────────────────
# registration_approval_depth3_cascade
# ─────────────────────────────────────────────────────

class TestRegistrationApprovalDepth3Cascade:
    def test_pre_state_parks_the_unresolved_line_value_in_the_holding_account(self, api):
        """Before the approval the title-only line is unattached, the batch is
        PARTIALLY_MATCHED and its 99999 cents of value sits in holding.

        PRD: "When `unmatched_play_count` is 1 or more, the batch moves `SEALED → PARTIALLY_MATCHED` instead; the divergence is not cosmetic, because those still-`UNMATCHED` lines are precisely what will fund pool holding accounts at calculation time."

        Design: Difficulty/transitive_cascade/registration_approval_depth3_cascade
        """
        fixture = _setup_calculated_pool_with_an_unresolved_line(api)

        batch = validate_success(
            api.get_usage_batch(fixture["batch"]["id"], ANALYST_HEADERS), 200
        )
        assert batch["status"] == "PARTIALLY_MATCHED"
        assert batch["total_play_count"] == 500000
        assert batch["matched_play_count"] == 450000
        assert batch["unmatched_play_count"] == 50000
        assert batch["disputed_play_count"] == 0
        assert_play_count_conservation(batch)

        unresolved_line = validate_success(
            api.get_usage_line(fixture["usage_lines"][2]["id"], ANALYST_HEADERS), 200
        )
        assert unresolved_line["match_status"] == "UNMATCHED"
        assert unresolved_line["work_id"] is None
        assert unresolved_line["match_confidence_bps"] == 5000
        assert unresolved_line["attributed_revenue_cents"] == 99999

        pool = validate_success(api.get_pool(fixture["pool"]["id"], ADMIN_HEADERS), 200)
        assert pool["status"] == "CALCULATED"
        assert pool["distributable_cents"] == 999999
        assert pool["matched_attributed_cents"] == 899998
        assert pool["holding_cents"] == 99999
        assert pool["rounding_residual_cents"] == 2
        assert_pool_value_conservation(pool)

        recording = validate_success(
            api.get_work(fixture["recording_b"]["id"], ANALYST_HEADERS), 200
        )
        assert recording["rights_state"] == "UNMATCHED"
        assert recording["approved_master_share_bps"] == 0

    def test_link_one_settles_the_registration_and_stamps_the_approving_operator(self, api):
        """Approving the claim moves it to APPROVED and records the approving
        analyst on the registration.

        PRD: "Its `status` becomes `APPROVED` and `reviewed_by_user_id` records the approving `X-User-ID`."

        Design: Difficulty/transitive_cascade/registration_approval_depth3_cascade
        """
        fixture = _setup_claim_under_review_over_the_unresolved_recording(api)

        approved = validate_success(
            api.approve_rights_registration(fixture["claim"]["id"], REVIEWER_HEADERS), 200
        )
        assert approved["status"] == "APPROVED"
        assert approved["reviewed_by_user_id"] == ANALYST_REVIEWER_USER_ID

    def test_link_two_re_derives_the_work_to_registered(self, api):
        """The settled registration re-derives the claimed recording's rights
        state to REGISTERED and recomputes its approved master share.

        PRD: "The work's `rights_state` is re-derived, moving from `UNMATCHED` or `PROVISIONAL` to `REGISTERED`, and `approved_master_share_bps` is recomputed."

        Design: Difficulty/transitive_cascade/registration_approval_depth3_cascade
        """
        fixture = _setup_claim_under_review_over_the_unresolved_recording(api)
        validate_success(
            api.approve_rights_registration(fixture["claim"]["id"], REVIEWER_HEADERS), 200
        )

        recording = validate_success(
            api.get_work(fixture["recording_b"]["id"], ANALYST_HEADERS), 200
        )
        assert recording["rights_state"] == "REGISTERED"
        assert recording["approved_master_share_bps"] == 10000

    def test_link_two_claim_matches_the_title_only_line_at_5000(self, api):
        """The re-derived work drags the previously refused title-only line into
        CLAIM_MATCHED at the score it had already recorded.

        PRD: "Then the service re-runs the matcher in claim mode over unattached usage: every usage line whose `work_id` is still null, whose batch belongs to a period where the current instant is at or before `claim_window_closes_at`, and whose best score against **this newly approved work alone** is at least 5,000, takes `work_id` from that work, records that score in `match_confidence_bps`, and moves to `match_status` `CLAIM_MATCHED`."

        Design: Difficulty/transitive_cascade/registration_approval_depth3_cascade
        """
        fixture = _setup_claim_under_review_over_the_unresolved_recording(api)
        validate_success(
            api.approve_rights_registration(fixture["claim"]["id"], REVIEWER_HEADERS), 200
        )

        line = validate_success(
            api.get_usage_line(fixture["usage_lines"][2]["id"], ANALYST_HEADERS), 200
        )
        assert line["match_status"] == "CLAIM_MATCHED"
        assert line["work_id"] == fixture["recording_b"]["id"]
        assert line["match_confidence_bps"] == 5000
        assert line["attributed_revenue_cents"] == 99999

    def test_link_three_promotes_the_batch_to_matched(self, api):
        """The re-attached line empties the batch's unmatched plays and promotes
        it from PARTIALLY_MATCHED to MATCHED.

        PRD: "Every affected usage batch recomputes `matched_play_count` and `unmatched_play_count`, and any batch whose `unmatched_play_count` has reached 0 moves `PARTIALLY_MATCHED → MATCHED`, which in turn lets the parent period re-evaluate its `OPEN → USAGE_SEALED` bubble-up."

        Design: Difficulty/transitive_cascade/registration_approval_depth3_cascade
        """
        fixture = _setup_claim_under_review_over_the_unresolved_recording(api)
        validate_success(
            api.approve_rights_registration(fixture["claim"]["id"], REVIEWER_HEADERS), 200
        )

        batch = validate_success(
            api.get_usage_batch(fixture["batch"]["id"], ANALYST_HEADERS), 200
        )
        assert batch["status"] == "MATCHED"
        assert batch["matched_play_count"] == 500000
        assert batch["unmatched_play_count"] == 0
        assert batch["disputed_play_count"] == 0
        assert batch["total_play_count"] == 500000
        assert_play_count_conservation(batch)

    def test_link_three_empties_the_pool_holding_account_without_touching_the_pool(self, api):
        """The re-attached line makes the calculated pool re-run attribution, so
        its holding account empties into the matched total while the frozen
        distributable amount and residual stay exactly where they were.

        PRD: "A pool whose `status` is `CALCULATED` re-runs attribution in full, so `holding_cents` falls and `matched_attributed_cents` rises by exactly the same number of cents."

        Design: Difficulty/transitive_cascade/registration_approval_depth3_cascade
        """
        fixture = _setup_claim_under_review_over_the_unresolved_recording(api)
        before = validate_success(api.get_pool(fixture["pool"]["id"], ADMIN_HEADERS), 200)
        assert before["holding_cents"] == 99999
        assert before["matched_attributed_cents"] == 899998

        validate_success(
            api.approve_rights_registration(fixture["claim"]["id"], REVIEWER_HEADERS), 200
        )

        after = validate_success(api.get_pool(fixture["pool"]["id"], ADMIN_HEADERS), 200)
        assert after["holding_cents"] == 0
        assert after["matched_attributed_cents"] == 999997
        assert after["rounding_residual_cents"] == 2
        assert after["distributable_cents"] == 999999
        assert_pool_value_conservation(after)


# ─────────────────────────────────────────────────────
# retroactive_promulgation_depth4_cascade
# ─────────────────────────────────────────────────────

class TestRetroactivePromulgationDepth4Cascade:
    def test_pre_state_carries_the_issued_net_on_the_label_balance(self, api):
        """Before the promulgation the label holds an issued single-line
        statement of 750000 gross, 60000 fee and 690000 net on its balance.

        PRD: "Issuing moves the statement `DRAFT → ISSUED`, stamps `issued_at` from the logical clock, raises the payee's `receivable_balance_cents` by exactly `net_payable_cents`, increments the payee's `issued_statement_count` by 1, and increments the statement's `version`."

        Design: Difficulty/transitive_cascade/retroactive_promulgation_depth4_cascade
        """
        fixture = _setup_closed_period_with_a_retroactive_proposal(api)

        statement = validate_success(
            api.get_statement(fixture["statement"]["id"], ADMIN_HEADERS), 200
        )
        assert statement["status"] == "ISSUED"
        assert statement["gross_cents"] == 750000
        assert statement["admin_fee_cents"] == 60000
        assert statement["net_payable_cents"] == 690000
        assert statement["line_count"] == 1

        holder = validate_success(
            api.get_rights_holder(fixture["label"]["id"], ADMIN_HEADERS), 200
        )
        assert holder["receivable_balance_cents"] == 690000
        assert holder["issued_statement_count"] == 1

    def test_link_one_brings_the_remand_schedule_into_force_and_displaces_the_incumbent(self, api):
        """Promulgating with supersede_incumbent moves the remand schedule to
        EFFECTIVE and the incumbent 7000-bps schedule to SUPERSEDED.

        PRD: "**Link one** moves the schedule `PROPOSED → EFFECTIVE` and stamps `promulgated_at` from the logical clock; when `supersede_incumbent` is true, every intersecting `EFFECTIVE` schedule sharing the `territory_code` and `subscription_tier` moves `EFFECTIVE → SUPERSEDED`."

        Design: Difficulty/transitive_cascade/retroactive_promulgation_depth4_cascade
        """
        fixture = _setup_closed_period_with_a_retroactive_proposal(api)

        promulgated = validate_success(
            api.promulgate_rate_schedule(
                fixture["remand_schedule"]["id"],
                REGULATOR_HEADERS,
                {"supersede_incumbent": True},
            ),
            200,
        )
        assert promulgated["status"] == "EFFECTIVE"
        assert promulgated["promulgated_at"] is not None

        incumbent = validate_success(
            api.get_rate_schedule(fixture["schedule"]["id"], REGULATOR_HEADERS), 200
        )
        assert incumbent["status"] == "SUPERSEDED"

    def test_link_two_reopens_the_finalized_pool(self, api):
        """The newly effective retroactive schedule reopens the finalized pool
        of the period it now governs.

        PRD: "**Link two** fires only when the newly effective schedule has `retroactive` set to true: every royalty pool whose `status` is `FINALIZED`, whose `subscription_tier` equals the schedule's, whose `territory_code` equals the schedule's or whose schedule is the literal `WORLD`, and whose parent period's `usage_end` falls inside the schedule's inclusive window, moves `FINALIZED → REOPENED_FOR_ADJUSTMENT`."

        Design: Difficulty/transitive_cascade/retroactive_promulgation_depth4_cascade
        """
        fixture = _setup_closed_period_with_a_retroactive_proposal(api)
        assert fixture["pool"]["status"] == "FINALIZED"

        validate_success(
            api.promulgate_rate_schedule(
                fixture["remand_schedule"]["id"],
                REGULATOR_HEADERS,
                {"supersede_incumbent": True},
            ),
            200,
        )

        pool = validate_success(api.get_pool(fixture["pool"]["id"], ADMIN_HEADERS), 200)
        assert pool["status"] == "REOPENED_FOR_ADJUSTMENT"

    def test_link_three_supersedes_the_issued_statement_and_reverses_the_balance(self, api):
        """The reopened pool voids the issued statement that drew on it and takes
        exactly its net payable back off the label's balance.

        PRD: "**Link three** follows because those pools reopened: every statement whose `status` is `ISSUED` and which owns at least one line pointing at a reopened pool moves `ISSUED → SUPERSEDED`, and each such statement's payee has its `receivable_balance_cents` reduced by exactly that statement's `net_payable_cents` and its `issued_statement_count` reduced by one."

        Design: Difficulty/transitive_cascade/retroactive_promulgation_depth4_cascade
        """
        fixture = _setup_closed_period_with_a_retroactive_proposal(api)

        validate_success(
            api.promulgate_rate_schedule(
                fixture["remand_schedule"]["id"],
                REGULATOR_HEADERS,
                {"supersede_incumbent": True},
            ),
            200,
        )

        statement = validate_success(
            api.get_statement(fixture["statement"]["id"], ADMIN_HEADERS), 200
        )
        assert statement["status"] == "SUPERSEDED"
        assert statement["net_payable_cents"] == 690000

        holder = validate_success(
            api.get_rights_holder(fixture["label"]["id"], ADMIN_HEADERS), 200
        )
        assert holder["receivable_balance_cents"] == 0
        assert holder["issued_statement_count"] == 0

    def test_link_four_reopens_the_closed_accounting_period(self, api):
        """The voided statement and reopened pool drag the accounting period back
        out of CLOSED into REOPENED.

        PRD: "**Link four** follows because those pools reopened and those statements were voided: every accounting period that owns a reopened pool moves to `REOPENED` — the `CLOSED → REOPENED` transition for a period that had already been closed, and the same move for a period still sitting in `DISTRIBUTED` when the cascade lands."

        Design: Difficulty/transitive_cascade/retroactive_promulgation_depth4_cascade
        """
        fixture = _setup_closed_period_with_a_retroactive_proposal(api)
        assert fixture["period_after_close"]["status"] == "CLOSED"

        validate_success(
            api.promulgate_rate_schedule(
                fixture["remand_schedule"]["id"],
                REGULATOR_HEADERS,
                {"supersede_incumbent": True},
            ),
            200,
        )

        period = validate_success(
            api.get_period(fixture["period"]["id"], ADMIN_HEADERS), 200
        )
        assert period["status"] == "REOPENED"

    def test_recalculating_the_reopened_pool_applies_the_new_rate(self, api):
        """Recalculating the reopened pool selects the 8000-bps schedule, so the
        distributable amount rises to 1142856 and is spread over the matched
        plays alone.

        PRD: "Each `REOPENED_FOR_ADJUSTMENT` pool is recalculated, which now selects the newly `EFFECTIVE` schedule and moves the pool `REOPENED_FOR_ADJUSTMENT → CALCULATED`, and is then finalized again, which bubbles the period `REOPENED → DISTRIBUTED`."

        Design: Difficulty/transitive_cascade/retroactive_promulgation_depth4_cascade
        """
        fixture = _setup_closed_period_with_a_retroactive_proposal(api)
        validate_success(
            api.promulgate_rate_schedule(
                fixture["remand_schedule"]["id"],
                REGULATOR_HEADERS,
                {"supersede_incumbent": True},
            ),
            200,
        )

        recalculated = validate_success(
            api.calculate_pool(fixture["pool"]["id"], ADMIN_HEADERS), 200
        )
        assert recalculated["status"] == "CALCULATED"
        assert recalculated["applied_rate_schedule_id"] == fixture["remand_schedule"]["id"]
        assert recalculated["distributable_cents"] == 1142856
        assert recalculated["denominator_basis"] == "MATCHED_ONLY"
        assert recalculated["denominator_play_count"] == 450000
        assert recalculated["matched_attributed_cents"] == 1142856
        assert recalculated["holding_cents"] == 0
        assert recalculated["rounding_residual_cents"] == 0
        assert_pool_value_conservation(recalculated)

        first_line = validate_success(
            api.get_usage_line(fixture["usage_lines"][0]["id"], ANALYST_HEADERS), 200
        )
        second_line = validate_success(
            api.get_usage_line(fixture["usage_lines"][1]["id"], ANALYST_HEADERS), 200
        )
        assert first_line["attributed_revenue_cents"] == 761904
        assert second_line["attributed_revenue_cents"] == 380952

        finalized = validate_success(
            api.finalize_pool(fixture["pool"]["id"], ADMIN_HEADERS), 200
        )
        assert finalized["status"] == "FINALIZED"
        period = validate_success(
            api.get_period(fixture["period"]["id"], ADMIN_HEADERS), 200
        )
        assert period["status"] == "DISTRIBUTED"

    def test_corrected_statement_carries_only_adjustment_lines(self, api):
        """The statement built after the reopen is a delta: its single line is an
        ADJUSTMENT and it never restates the original line.

        PRD: "The corrected statement carries **only** adjustment lines; it never restates the original lines."

        Design: Difficulty/transitive_cascade/retroactive_promulgation_depth4_cascade
        """
        fixture = _setup_closed_period_with_a_retroactive_proposal(api)
        validate_success(
            api.promulgate_rate_schedule(
                fixture["remand_schedule"]["id"],
                REGULATOR_HEADERS,
                {"supersede_incumbent": True},
            ),
            200,
        )

        corrected = _setup_corrected_statement_after_the_reopen(api, fixture)
        assert corrected["status"] == "DRAFT"
        assert corrected["line_count"] == 1

        lines, meta = validate_paginated(
            api.list_statement_lines(
                ADMIN_HEADERS, params={"statement_id": corrected["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert [line["line_type"] for line in lines] == ["ADJUSTMENT"]

    def test_adjustment_line_carries_the_gross_and_fee_deltas(self, api):
        """The adjustment line points at the superseded original and carries the
        gross delta of 107142, the fee delta of 8571 and their difference.

        PRD: "When either delta is non-zero, one line of `line_type` `ADJUSTMENT` is emitted: its `adjustment_of_line_id` points at the old line, its `pool_id`, `work_id`, `right_type`, `routing`, `territory_code`, `subscription_tier` and `share_bps` are copied from the old line, its `play_count` is 0, its `gross_cents` is the gross delta, its `admin_fee_cents` is the fee delta, and its `net_cents` is the gross delta minus the fee delta."

        Design: Difficulty/transitive_cascade/retroactive_promulgation_depth4_cascade
        """
        fixture = _setup_closed_period_with_a_retroactive_proposal(api)
        original_line = fixture["statement_lines"][0]
        validate_success(
            api.promulgate_rate_schedule(
                fixture["remand_schedule"]["id"],
                REGULATOR_HEADERS,
                {"supersede_incumbent": True},
            ),
            200,
        )

        corrected = _setup_corrected_statement_after_the_reopen(api, fixture)
        lines, _ = validate_paginated(
            api.list_statement_lines(
                ADMIN_HEADERS,
                params={"statement_id": corrected["id"], "line_type": "ADJUSTMENT"},
            )
        )
        assert len(lines) == 1
        adjustment = lines[0]
        assert adjustment["adjustment_of_line_id"] == original_line["id"]
        assert adjustment["play_count"] == 0
        assert adjustment["gross_cents"] == 107142
        assert adjustment["admin_fee_cents"] == 8571
        assert adjustment["net_cents"] == 98571

        assert corrected["gross_cents"] == 107142
        assert corrected["admin_fee_cents"] == 8571
        assert corrected["net_payable_cents"] == 98571
