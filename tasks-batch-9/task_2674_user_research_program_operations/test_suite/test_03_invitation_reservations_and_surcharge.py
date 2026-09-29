"""What an invitation costs: pre-call utilization, the surcharge tiers and the
precedence of the recruitment-closed guard over the fiscal guard.
"""

from test_helpers import (
    RESEARCHER_HEADERS,
    ApiErrorId,
    assert_ledger_partition,
    assert_pool_posture_matches_ledger,
    complete_session,
    create_recruitment_payload,
    grant_consent,
    invite,
    read_pool,
    read_recruitment,
    read_study,
    schedule,
    screen,
    setup_fielding_study,
    setup_invited_recruitments,
    setup_pool_with_reservations,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestReservationReadsPreCallUtilization:
    """A reservation is priced from the ledger as it stood before the reservation."""

    def test_second_invitation_is_priced_from_the_pre_call_utilization(self, api):
        """The second invite on a quarter-committed pool pays the free tier, not the tier its own reservation creates.

        PRD 3.4: "First, read the pool's utilization from the state before this
        reservation is applied: committed money, meaning `incentive_reserved_cents`
        plus `incentive_paid_cents`, divided by `incentive_budget_cents`."

        PRD 3.4: "From that pre-call utilization read a scarcity surcharge
        percentage: below 0.50 the surcharge is zero; from 0.50 up to but not
        including 0.80 it is five percent; at 0.80 or above it is ten percent."

        Design: Difficulty/combinatorial_formula/reservation_surcharge_reads_pre_state_utilization
        """
        ctx = setup_invited_recruitments(
            api,
            invite_count=1,
            participant_count=2,
            incentive_amount_cents=5000,
            target_participant_count=3,
            pool_overrides={"incentive_budget_cents": 20000},
        )
        first = ctx["recruitments"][0]
        assert first["reserved_cents"] == 5000, (
            f"Expected 5000, got {first['reserved_cents']} for the first invitation "
            "priced at a pre-call utilization of 0.00"
        )

        before = read_pool(ctx["pool"]["id"], api)
        assert_ledger_partition(before)
        assert before["incentive_reserved_cents"] == 5000, (
            f"Expected 5000 reserved, got {before['incentive_reserved_cents']} "
            "before the second invitation"
        )
        assert before["incentive_available_cents"] == 15000, (
            f"Expected 15000 available, got {before['incentive_available_cents']} "
            "before the second invitation"
        )

        second = validate_success(
            api.create_recruitment(
                ctx["study"]["id"],
                create_recruitment_payload(ctx["participants"][1]["id"]),
                RESEARCHER_HEADERS,
            ),
            expected_status=201,
        )
        assert second["reserved_cents"] == 5000, (
            f"Expected 5000, got {second['reserved_cents']} for a reservation taken "
            "at a pre-call utilization of 0.25"
        )
        assert second["reserved_cents"] != 5250, (
            "The reservation was priced from the post-call utilization of 0.50, "
            f"charging {second['reserved_cents']} instead of the free-tier 5000"
        )

    def test_pool_ledger_after_two_free_tier_invitations_is_exactly_half_committed(self, api):
        """Two free-tier reservations move 10000 cents from available into reserved and leave the pool OPEN.

        PRD 3.4: "Otherwise the pool's `incentive_reserved_cents` rises by exactly
        `reserved_cents` and `incentive_available_cents` is re-derived as budget minus
        reserved minus paid, keeping the ledger partition of §2.10 intact."

        PRD 2.10: "At every observable instant, and for every pool, the following must
        hold: `incentive_available_cents` plus `incentive_reserved_cents` plus
        `incentive_paid_cents` equals `incentive_budget_cents`."

        Design: Difficulty/combinatorial_formula/reservation_surcharge_reads_pre_state_utilization
        """
        ctx = setup_invited_recruitments(
            api,
            invite_count=2,
            participant_count=2,
            incentive_amount_cents=5000,
            target_participant_count=3,
            pool_overrides={"incentive_budget_cents": 20000},
        )
        pool = read_pool(ctx["pool"]["id"], api)
        assert_ledger_partition(pool)
        assert pool["incentive_reserved_cents"] == 10000, (
            f"Expected 10000 reserved, got {pool['incentive_reserved_cents']} after "
            "two 5000-cent reservations"
        )
        assert pool["incentive_available_cents"] == 10000, (
            f"Expected 10000 available, got {pool['incentive_available_cents']} after "
            "two 5000-cent reservations"
        )
        assert pool["incentive_paid_cents"] == 0, (
            f"Expected 0 paid, got {pool['incentive_paid_cents']} before any settlement"
        )
        assert pool["status"] == "OPEN", (
            f"Expected OPEN, got {pool['status']} at a utilization of 0.50"
        )
        assert_pool_posture_matches_ledger(pool)

    def test_free_tier_holds_even_when_the_reservation_pushes_utilization_past_eighty_percent(
        self, api
    ):
        """A pre-call utilization below 0.50 charges nothing even though the post-call ratio sits in the ten-percent band.

        PRD 3.4: "Each reservation is computed as follows, and the order is pinned
        because the answer depends on state this very reservation is about to change."

        PRD 3.4: "From that pre-call utilization read a scarcity surcharge
        percentage: below 0.50 the surcharge is zero; from 0.50 up to but not
        including 0.80 it is five percent; at 0.80 or above it is ten percent."

        Design: Difficulty/combinatorial_formula/reservation_surcharge_reads_pre_state_utilization
        """
        ctx = setup_invited_recruitments(
            api,
            invite_count=1,
            participant_count=2,
            incentive_amount_cents=5000,
            target_participant_count=3,
            pool_overrides={"incentive_budget_cents": 12000},
        )
        before = read_pool(ctx["pool"]["id"], api)
        assert_ledger_partition(before)
        assert before["incentive_reserved_cents"] == 5000, (
            f"Expected 5000 reserved, got {before['incentive_reserved_cents']} at a "
            "pre-call utilization of 5000/12000"
        )

        second = validate_success(
            api.create_recruitment(
                ctx["study"]["id"],
                create_recruitment_payload(ctx["participants"][1]["id"]),
                RESEARCHER_HEADERS,
            ),
            expected_status=201,
        )
        assert second["reserved_cents"] == 5000, (
            f"Expected 5000, got {second['reserved_cents']} for a reservation whose "
            "pre-call utilization of 5000/12000 is below 0.50"
        )
        assert second["reserved_cents"] != 5500, (
            "The reservation was priced from the post-call utilization of 10000/12000, "
            f"charging the ten-percent tier amount {second['reserved_cents']}"
        )

        after = read_pool(ctx["pool"]["id"], api)
        assert_ledger_partition(after)
        assert after["incentive_reserved_cents"] == 10000, (
            f"Expected 10000 reserved, got {after['incentive_reserved_cents']} after "
            "two free-tier reservations of 5000"
        )
        assert after["incentive_available_cents"] == 2000, (
            f"Expected 2000 available, got {after['incentive_available_cents']} after "
            "two free-tier reservations of 5000"
        )
        assert after["status"] == "RESTRICTED", (
            f"Expected RESTRICTED, got {after['status']} at a utilization of 10000/12000"
        )
        assert_pool_posture_matches_ledger(after)


class TestSurchargeTierAtExactlyHalfUtilization:
    """The 0.50 utilization edge belongs to the five-percent tier, not to the free tier."""

    def test_reservation_at_exactly_half_utilization_pays_the_five_percent_tier(self, api):
        """A pre-call utilization of exactly 0.50 reserves 5250, because the free tier stops strictly below 0.50.

        PRD 3.4: "From that pre-call utilization read a scarcity surcharge
        percentage: below 0.50 the surcharge is zero; from 0.50 up to but not
        including 0.80 it is five percent; at 0.80 or above it is ten percent."

        PRD 3.4: "Then take the study's `incentive_amount_cents`, multiply it by the
        surcharge percentage, round that surcharge term up to the next whole cent, and
        add it to the base — the sum is the recruitment's `reserved_cents`."

        Design: Difficulty/boundary_precision_check/reservation_surcharge_at_exactly_half_utilization
        """
        ctx = setup_pool_with_reservations(
            api,
            reservation_count=2,
            participant_count=3,
            incentive_amount_cents=5000,
            pool_overrides={"incentive_budget_cents": 20000},
        )
        before = read_pool(ctx["pool"]["id"], api)
        assert_ledger_partition(before)
        assert before["incentive_reserved_cents"] == 10000, (
            f"Expected 10000 reserved, got {before['incentive_reserved_cents']} for an "
            "exact 0.50 utilization"
        )
        assert before["incentive_available_cents"] == 10000, (
            f"Expected 10000 available, got {before['incentive_available_cents']} for "
            "an exact 0.50 utilization"
        )
        for recruitment in ctx["recruitments"]:
            assert recruitment["reserved_cents"] == 5000, (
                f"Expected 5000, got {recruitment['reserved_cents']} for a reservation "
                "taken below the 0.50 boundary"
            )

        third = validate_success(
            api.create_recruitment(
                ctx["study"]["id"],
                create_recruitment_payload(ctx["participants"][2]["id"]),
                RESEARCHER_HEADERS,
            ),
            expected_status=201,
        )
        assert third["reserved_cents"] == 5250, (
            f"Expected 5250, got {third['reserved_cents']} for a reservation taken at "
            "an exact 0.50 utilization"
        )

        after = read_pool(ctx["pool"]["id"], api)
        assert_ledger_partition(after)
        assert after["incentive_reserved_cents"] == 15250, (
            f"Expected 15250 reserved, got {after['incentive_reserved_cents']} after "
            "the surcharged reservation"
        )
        assert after["incentive_available_cents"] == 4750, (
            f"Expected 4750 available, got {after['incentive_available_cents']} after "
            "the surcharged reservation"
        )
        assert after["status"] == "OPEN", (
            f"Expected OPEN, got {after['status']} at a utilization of 15250/20000"
        )
        assert_pool_posture_matches_ledger(after)

    def test_reservation_a_single_cent_below_half_utilization_pays_nothing_extra(self, api):
        """A utilization of 10000/20001 is strictly below 0.50, so the third invite still reserves the bare base.

        PRD 2.8: "Pool utilization is never rounded at all. It is compared as an exact
        ratio of integer cents, so a pool holding 800 reserved cents against an
        1,000-cent budget sits exactly at the 0.80 boundary rather than near it."

        PRD 3.4: "From that pre-call utilization read a scarcity surcharge
        percentage: below 0.50 the surcharge is zero; from 0.50 up to but not
        including 0.80 it is five percent; at 0.80 or above it is ten percent."

        Design: Difficulty/boundary_precision_check/reservation_surcharge_at_exactly_half_utilization
        """
        ctx = setup_pool_with_reservations(
            api,
            reservation_count=2,
            participant_count=3,
            incentive_amount_cents=5000,
            pool_overrides={"incentive_budget_cents": 20001},
        )
        before = read_pool(ctx["pool"]["id"], api)
        assert_ledger_partition(before)
        assert before["incentive_reserved_cents"] == 10000, (
            f"Expected 10000 reserved, got {before['incentive_reserved_cents']} just "
            "below the 0.50 boundary"
        )
        assert before["incentive_available_cents"] == 10001, (
            f"Expected 10001 available, got {before['incentive_available_cents']} just "
            "below the 0.50 boundary"
        )

        third = validate_success(
            api.create_recruitment(
                ctx["study"]["id"],
                create_recruitment_payload(ctx["participants"][2]["id"]),
                RESEARCHER_HEADERS,
            ),
            expected_status=201,
        )
        assert third["reserved_cents"] == 5000, (
            f"Expected 5000, got {third['reserved_cents']} for a reservation taken at "
            "a utilization of 10000/20001, which is strictly below 0.50"
        )

        after = read_pool(ctx["pool"]["id"], api)
        assert_ledger_partition(after)
        assert after["incentive_reserved_cents"] == 15000, (
            f"Expected 15000 reserved, got {after['incentive_reserved_cents']} after "
            "three free-tier reservations"
        )
        assert after["incentive_available_cents"] == 5001, (
            f"Expected 5001 available, got {after['incentive_available_cents']} after "
            "three free-tier reservations"
        )
        assert_pool_posture_matches_ledger(after)

    def test_five_percent_surcharge_on_a_base_of_333_cents_rounds_up_to_a_whole_cent(self, api):
        """At the five-percent tier a 333-cent base reserves 350, because 16.65 cents rounds up to 17.

        PRD 3.4: "A study offering 1,000 cents therefore reserves 1,000 cents in an
        unstressed pool, 1,050 cents once the pool crosses the halfway mark, and 1,100
        cents from 0.80 utilization upward; a base of 333 cents at the five-percent tier
        reserves 333 plus 17, because 16.65 cents rounds up to a whole 17."

        PRD 2.8: "First, all money in this platform is integer cents —
        `incentive_budget_cents`, `incentive_reserved_cents`, `incentive_paid_cents`,
        `incentive_available_cents`, `last_estimate_cents`, `incentive_amount_cents`,
        `reserved_cents` and `paid_cents` are integers throughout, and the only rounding
        that touches money is the surcharge term of a reservation, which is rounded up to
        the next whole cent."

        Design: Difficulty/boundary_precision_check/reservation_surcharge_at_exactly_half_utilization
        """
        ctx = setup_pool_with_reservations(
            api,
            reservation_count=2,
            participant_count=3,
            incentive_amount_cents=333,
            pool_overrides={"incentive_budget_cents": 1332},
        )
        before = read_pool(ctx["pool"]["id"], api)
        assert_ledger_partition(before)
        assert before["incentive_reserved_cents"] == 666, (
            f"Expected 666 reserved, got {before['incentive_reserved_cents']} for an "
            "exact 0.50 utilization of a 1332-cent budget"
        )

        third = validate_success(
            api.create_recruitment(
                ctx["study"]["id"],
                create_recruitment_payload(ctx["participants"][2]["id"]),
                RESEARCHER_HEADERS,
            ),
            expected_status=201,
        )
        assert third["reserved_cents"] == 350, (
            f"Expected 350, got {third['reserved_cents']} for a 333-cent base at the "
            "five-percent tier, where the 16.65-cent surcharge rounds up to 17"
        )

        after = read_pool(ctx["pool"]["id"], api)
        assert_ledger_partition(after)
        assert after["incentive_reserved_cents"] == 1016, (
            f"Expected 1016 reserved, got {after['incentive_reserved_cents']} after the "
            "rounded-up surcharge landed"
        )
        assert after["incentive_available_cents"] == 316, (
            f"Expected 316 available, got {after['incentive_available_cents']} after the "
            "rounded-up surcharge landed"
        )
        assert_pool_posture_matches_ledger(after)


def _study_at_quota_with_a_thin_budget(api):
    """One completed session against a 6000-cent budget and a target of 1, so the
    study is at quota *and* the next reservation would be unaffordable."""
    ctx = setup_fielding_study(
        api,
        participant_count=2,
        target_participant_count=1,
        incentive_amount_cents=5000,
        pool_overrides={"incentive_budget_cents": 6000, "contact_cap_per_window": 2},
    )
    first_participant = ctx["participants"][0]["id"]
    grant_consent(first_participant, ctx["study"]["id"], api, scopes=["RECORDING"], retention_days=60)
    recruitment = invite(ctx["study"]["id"], first_participant, api)
    screen(recruitment["id"], api)
    schedule(recruitment["id"], "2026-08-05T14:00:00Z", "2026-08-05T15:00:00Z", api)
    ctx["recruitments"] = [complete_session(recruitment["id"], api)]
    ctx["study"] = read_study(ctx["study"]["id"], api)
    ctx["pool"] = read_pool(ctx["pool"]["id"], api)
    return ctx


class TestRecruitmentClosedOutranksTheBudgetGuard:
    """One invitation breaks the quota guard and the budget guard at once; the
    state guard is the one the caller is told about."""

    def test_invitation_into_a_quota_met_study_is_refused_as_recruitment_closed(self, api):
        """The 409 state guard answers first even though the reservation would also have overrun the budget.

        PRD 3.4: "Either way, invitation is gated first on the study and then on the
        pool: the study's `execution_status` must be `FIELDING` and its
        `recruitment_status` must not already be `QUOTA_MET`, else
        `ERR_RECRUITMENT_CLOSED`; and the pool's derived posture must not be `CLOSED`,
        else `ERR_POOL_CLOSED`."

        PRD 2.6: "`ERR_RECRUITMENT_CLOSED` (409) on both invitation endpoints;
        `ERR_POOL_CLOSED` (409) on both invitation endpoints; `ERR_POOL_RESTRICTED` (409)
        on batch invitation only"

        PRD 2.6: "**Business rules** — evaluated last, in this order:
        `ERR_CONSENT_MISSING`, `ERR_CONSENT_SCOPE_MISSING`, `ERR_ARTIFACT_PURGED`,"
        and, at the tail of that same last step,
        "`ERR_INCENTIVE_BUDGET_EXCEEDED`, `ERR_DUPLICATE_EXTERNAL_REF`,
        `ERR_DUPLICATE_LABEL`."

        Design: Difficulty/priority_pair_validation_conflict/invite_state_closed_outranks_fiscal_budget_breach
        """
        ctx = _study_at_quota_with_a_thin_budget(api)
        assert ctx["study"]["recruitment_status"] == "QUOTA_MET", (
            f"Expected QUOTA_MET, got {ctx['study']['recruitment_status']} once the "
            "single target session completed"
        )
        assert ctx["pool"]["incentive_available_cents"] == 1000, (
            f"Expected 1000 available, got {ctx['pool']['incentive_available_cents']} — "
            "the second reservation of 5500 must be unaffordable"
        )

        validate_error(
            api.create_recruitment(
                ctx["study"]["id"],
                create_recruitment_payload(ctx["participants"][1]["id"]),
                RESEARCHER_HEADERS,
            ),
            ApiErrorId.RECRUITMENT_CLOSED.value,
        )

    def test_the_refused_invitation_creates_no_row_and_moves_no_cents(self, api):
        """The rejected call leaves the recruitment set, the study counters and the ledger exactly as they were.

        PRD 2.6: "Because a single request can violate several rules at once, the
        platform evaluates checks in a fixed precedence and returns the first failure it
        finds."

        PRD 3.4: "That amount is then checked against the same pre-call state: if
        `reserved_cents` exceeds the pool's `incentive_available_cents`, the invitation is
        refused with `ERR_INCENTIVE_BUDGET_EXCEEDED` and nothing is created."

        Design: Difficulty/priority_pair_validation_conflict/invite_state_closed_outranks_fiscal_budget_breach
        """
        ctx = _study_at_quota_with_a_thin_budget(api)
        second_participant = ctx["participants"][1]["id"]

        validate_error(
            api.create_recruitment(
                ctx["study"]["id"],
                create_recruitment_payload(second_participant),
                RESEARCHER_HEADERS,
            ),
            ApiErrorId.RECRUITMENT_CLOSED.value,
        )

        rows, _meta = validate_paginated(
            api.list_recruitments(
                RESEARCHER_HEADERS, {"participant_id": second_participant}
            )
        )
        assert rows == [], (
            f"Expected no recruitment for the uninvited participant, got {len(rows)} rows"
        )

        study = read_study(ctx["study"]["id"], api)
        assert study["invited_count"] == 1, (
            f"Expected invited_count 1, got {study['invited_count']} after the refused "
            "invitation"
        )
        assert study["recruitment_status"] == "QUOTA_MET", (
            f"Expected QUOTA_MET, got {study['recruitment_status']} after the refused "
            "invitation"
        )

        pool = read_pool(ctx["pool"]["id"], api)
        assert_ledger_partition(pool)
        assert pool["incentive_reserved_cents"] == 5000, (
            f"Expected 5000 reserved, got {pool['incentive_reserved_cents']} — the "
            "refused invitation must not have reserved anything"
        )
        assert pool["incentive_available_cents"] == 1000, (
            f"Expected 1000 available, got {pool['incentive_available_cents']} — the "
            "refused invitation must not have moved cents"
        )
        assert pool["incentive_paid_cents"] == 0, (
            f"Expected 0 paid, got {pool['incentive_paid_cents']} before any settlement"
        )

    def test_the_completed_session_keeps_its_reservation_until_settlement(self, api):
        """Reaching quota neither pays nor releases the completed row's reserved cents.

        PRD 3.5: "The study's `completed_count` is recomputed as the number of its
        recruitments standing in `COMPLETED`, and its `recruitment_status` re-derived:
        once the number of the study's recruitments sitting in `SCHEDULED` or `COMPLETED`
        reaches `target_participant_count`, the study moves `RECRUITING → QUOTA_MET` and
        further invitations are refused with `ERR_RECRUITMENT_CLOSED`."

        PRD 2.10: "`incentive_available_cents` is always derived as the budget minus
        reserved minus paid, never accumulated independently."

        Design: Difficulty/priority_pair_validation_conflict/invite_state_closed_outranks_fiscal_budget_breach
        """
        ctx = _study_at_quota_with_a_thin_budget(api)
        recruitment = read_recruitment(ctx["recruitments"][0]["id"], api)
        assert recruitment["status"] == "COMPLETED", (
            f"Expected COMPLETED, got {recruitment['status']} for the session that met "
            "the target"
        )
        assert recruitment["incentive_state"] == "RESERVED", (
            f"Expected RESERVED, got {recruitment['incentive_state']} before any "
            "settlement ran"
        )
        assert recruitment["reserved_cents"] == 5000, (
            f"Expected 5000, got {recruitment['reserved_cents']} for the first "
            "reservation of an unstressed pool"
        )
        assert recruitment["paid_cents"] == 0, (
            f"Expected 0 paid, got {recruitment['paid_cents']} before any settlement ran"
        )
        assert_ledger_partition(read_pool(ctx["pool"]["id"], api))
