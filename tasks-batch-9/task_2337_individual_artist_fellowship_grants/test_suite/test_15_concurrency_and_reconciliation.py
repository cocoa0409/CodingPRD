"""
The two optimistic-concurrency guards, one derived counter tracked through every
source change, and the immediacy of the widest cascade's own response.
"""

from test_helpers import (
    APPEALS_OFFICER,
    BOARD_MEMBER,
    BOARD_MEMBER_ID,
    PROGRAM_OFFICER,
    api_client,
    assert_cents,
    assert_cycle_ledger,
    cornermain_slate_submitted,
    cycle_version,
    panel_version,
    read_application,
    read_artist,
    read_cycle,
    read_discipline,
    read_panel,
    set_clock,
    twoslot_applications_submitted,
    twoslot_board_review,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestStaleCycleVersionOnBoardAction:
    """The version check runs ahead of the slot's own state check."""

    def test_a_version_one_behind_is_refused_and_the_replay_is_refused_again(self):
        """
        A board action carrying the version one behind is refused with the stale-version error
        and leaves the slot, the cycle version and the budget untouched; the correct action then
        advances the version by exactly one, so replaying the identical body is refused as stale
        rather than for the slot's state.

        PRD: "The server compares that value against the cycle's current `version` before any
        state, posture or fiscal evaluation."

        PRD: "Every accepted board action increments the cycle's `version` by one, so a re-read
        is mandatory before the next action."

        Design: Corner/complexity_layers/stale_expected_cycle_version_on_board_action_returns_412
        """
        ctx = cornermain_slate_submitted()
        expected = cycle_version(ctx.cyc)

        validate_error(
            api_client.board_action(
                ctx.slot,
                {"action": "APPROVE", "expected_cycle_version": expected - 1},
                BOARD_MEMBER,
            ),
            "ERR_STALE_CYCLE_VERSION",
        )
        untouched = read_cycle(ctx.cyc)
        assert untouched["version"] == expected, (
            f"the refusal spends no version, got {untouched['version']}"
        )
        assert_cents(untouched["funded_total_cents"], 0, "cycle.funded_total_cents")
        assert_cents(untouched["committed_cents"], 0, "cycle.committed_cents")
        assert (
            validate_success(api_client.get_slot(ctx.slot, PROGRAM_OFFICER))["status"]
            == "PROPOSED"
        ), "the slot is still awaiting the board"

        approved = validate_success(
            api_client.board_action(
                ctx.slot,
                {"action": "APPROVE", "expected_cycle_version": expected},
                BOARD_MEMBER,
            )
        )
        assert approved["status"] == "BOARD_APPROVED", (
            f"the matching version is accepted, got {approved['status']}"
        )
        assert_cents(
            approved["awarded_amount_cents"], 1_500_000, "slot.awarded_amount_cents"
        )

        after = read_cycle(ctx.cyc)
        assert after["version"] == expected + 1, (
            "the accepted action advances the version by exactly one, got "
            f"{after['version']} against {expected}"
        )
        assert_cents(after["committed_cents"], 1_627_500, "cycle.committed_cents")

        validate_error(
            api_client.board_action(
                ctx.slot,
                {"action": "APPROVE", "expected_cycle_version": expected},
                BOARD_MEMBER,
            ),
            "ERR_STALE_CYCLE_VERSION",
        )


class TestStalePanelVersionOnSlate:
    """The version check runs ahead of the ranked list's validation."""

    def test_a_stale_slate_creates_no_slot_even_though_its_list_is_valid(self):
        """
        A slate whose ranked list is entirely correct is still refused when its expected panel
        version is one behind, and no recommendation slot is created; the accepted slate advances
        the panel version by exactly one, so the replay is refused as stale.

        PRD: "The server compares that value against the panel's current `version` before it
        validates the ranked application list."

        PRD: "An accepted slate submission increments the panel's `version` by one."

        Design: Corner/complexity_layers/stale_expected_panel_version_on_slate_returns_412
        """
        ctx = twoslot_board_review()
        expected = panel_version(ctx.tpan)
        body = {"ranked_application_ids": [ctx.appA, ctx.appB]}

        validate_error(
            api_client.submit_slate(
                ctx.tpan,
                {**body, "expected_panel_version": expected - 1},
                ctx.tpl1_headers,
            ),
            "ERR_STALE_PANEL_VERSION",
        )
        assert read_panel(ctx.tpan)["status"] == "DELIBERATING", (
            "the refused slate leaves the panel deliberating"
        )
        _, meta = validate_paginated(
            api_client.list_slots(PROGRAM_OFFICER, {"panel_id": ctx.tpan, "limit": 100})
        )
        assert meta["total_count"] == 0, (
            f"no slot is created by a stale slate, got {meta['total_count']}"
        )

        submitted = validate_success(
            api_client.submit_slate(
                ctx.tpan, {**body, "expected_panel_version": expected}, ctx.tpl1_headers
            )
        )
        assert submitted["status"] == "SLATE_SUBMITTED", (
            f"the matching version is accepted, got {submitted['status']}"
        )
        rows, meta = validate_paginated(
            api_client.list_slots(PROGRAM_OFFICER, {"panel_id": ctx.tpan, "limit": 100})
        )
        assert meta["total_count"] == 2, (
            f"one slot per listed application, got {meta['total_count']}"
        )
        for row in rows:
            assert row["status"] == "PROPOSED", (
                f"each new slot is proposed, got {row['status']}"
            )

        validate_error(
            api_client.submit_slate(
                ctx.tpan, {**body, "expected_panel_version": expected}, ctx.tpl1_headers
            ),
            "ERR_STALE_PANEL_VERSION",
        )
        assert panel_version(ctx.tpan) == expected + 1, (
            "the accepted slate advances the panel version by exactly one, got "
            f"{panel_version(ctx.tpan)} against {expected}"
        )


class TestEligibleCountTracksEverySource:
    """Up twice, unchanged once, and up again through a remedy."""

    def test_the_counter_follows_two_determinations_a_refusal_and_a_reinstatement(self):
        """
        The discipline's eligible count reads zero before any determination, one and then two as
        eligible determinations land, stays at two when a third application is determined
        ineligible, and reaches three only when an upheld appeal reinstates that application.

        PRD: "On success the application moves `SUBMITTED → ELIGIBLE` and the discipline's
        `eligible_application_count` is incremented by one."

        PRD: "On success the application moves `SUBMITTED → INELIGIBLE`, the
        `ineligibility_reason_code` is recorded, and `notified_at` is stamped from the logical
        clock — which opens the appeal window described in §3.11."

        PRD: "Upholding an appeal requires a `remedy_code` that is permitted for the cited
        `grounds_code`, and the mapping is exact: `ELIGIBILITY_DETERMINATION_ERROR` permits only
        `REINSTATE_ELIGIBILITY`; `CONFLICT_NOT_MANAGED`, `ANONYMITY_BREACH` and
        `SCORING_PROCEDURE_DEFECT` each permit only `RESCORE_BY_NEW_PANEL`; and
        `PANEL_COMPOSITION_DEFECT` permits either `RESCORE_BY_NEW_PANEL` or `REISSUE_SLATE`."

        PRD: "`REINSTATE_ELIGIBILITY` moves the `INELIGIBLE` application to `ELIGIBLE`, clears
        its `ineligibility_reason_code`, clears its `assigned_panel_id` so a later charter can
        pick it up, and increments the discipline's `eligible_application_count` by one."

        Design: Corner/complexity_layers/eligible_application_count_reconciles_across_every_source_change
        """
        ctx = twoslot_applications_submitted()
        set_clock("2026-10-16T00:00:00Z")
        validate_success(
            api_client.set_cycle_status(ctx.tcyc, "CLOSED", PROGRAM_OFFICER)
        )
        assert read_discipline(ctx.tdisc)["eligible_application_count"] == 0, (
            "no determination has been recorded yet"
        )

        validate_success(
            api_client.determine_eligibility(
                ctx.appA, {"determination": "ELIGIBLE"}, PROGRAM_OFFICER
            )
        )
        assert read_discipline(ctx.tdisc)["eligible_application_count"] == 1, (
            "the first eligible determination is counted"
        )
        validate_success(
            api_client.determine_eligibility(
                ctx.appB, {"determination": "ELIGIBLE"}, PROGRAM_OFFICER
            )
        )
        assert read_discipline(ctx.tdisc)["eligible_application_count"] == 2, (
            "the second eligible determination is counted"
        )

        ineligible = validate_success(
            api_client.determine_eligibility(
                ctx.appD,
                {
                    "determination": "INELIGIBLE",
                    "ineligibility_reason_code": "RESIDENCY_DURATION",
                },
                PROGRAM_OFFICER,
            )
        )
        assert ineligible["status"] == "INELIGIBLE", (
            f"the third application is refused, got {ineligible['status']}"
        )
        assert ineligible["ineligibility_reason_code"] == "RESIDENCY_DURATION", (
            f"the cited criterion is recorded, got {ineligible['ineligibility_reason_code']}"
        )
        assert ineligible["residency_months_at_deadline"] == 23, (
            "the frozen residency is one month short, got "
            f"{ineligible['residency_months_at_deadline']}"
        )
        assert str(ineligible["notified_at"]).startswith("2026-10-16"), (
            f"the appeal window opens from the clock, got {ineligible['notified_at']}"
        )
        assert read_discipline(ctx.tdisc)["eligible_application_count"] == 2, (
            "an ineligible determination leaves the counter alone"
        )

        validate_success(
            api_client.set_cycle_status(ctx.tcyc, "PANEL_REVIEW", PROGRAM_OFFICER)
        )
        appeal = validate_success(
            api_client.create_appeal(
                {
                    "application_id": ctx.appD,
                    "grounds_code": "ELIGIBILITY_DETERMINATION_ERROR",
                    "statement": "My residency began before the stated date.",
                },
                ctx.artD_headers,
            ),
            expected_status=201,
        )
        validate_success(api_client.screen_appeal(appeal["id"], APPEALS_OFFICER))

        validate_error(
            api_client.decide_appeal(
                appeal["id"],
                {"decision": "UPHOLD", "remedy_code": "RESCORE_BY_NEW_PANEL"},
                APPEALS_OFFICER,
            ),
            "ERR_REMEDY_NOT_PERMITTED_FOR_GROUNDS",
        )
        assert read_discipline(ctx.tdisc)["eligible_application_count"] == 2, (
            "the refused remedy changes no counter"
        )

        upheld = validate_success(
            api_client.decide_appeal(
                appeal["id"],
                {"decision": "UPHOLD", "remedy_code": "REINSTATE_ELIGIBILITY"},
                APPEALS_OFFICER,
            )
        )
        assert upheld["status"] == "UPHELD", (
            f"the permitted remedy is accepted, got {upheld['status']}"
        )
        assert read_discipline(ctx.tdisc)["eligible_application_count"] == 3, (
            "the reinstatement raises the counter to three"
        )

        reinstated = read_application(ctx.appD)
        assert reinstated["status"] == "ELIGIBLE", (
            f"the application rejoins the pool, got {reinstated['status']}"
        )
        assert reinstated["ineligibility_reason_code"] is None, (
            f"the reason is cleared, got {reinstated['ineligibility_reason_code']}"
        )
        assert reinstated["assigned_panel_id"] is None, (
            f"a later charter can pick it up, got {reinstated['assigned_panel_id']}"
        )


class TestApprovalResponseIsAlreadyReconciled:
    """No second call is needed to see the cascade."""

    def test_the_board_approval_response_and_the_reads_after_it_agree_at_once(self):
        """
        The approval's own response body already carries the approved disposition and the awarded
        amount, and the reads that follow it show the cycle ledger, the discipline commitment, the
        artist's active count and the new award fully reconciled without any further action.

        PRD: "Every such cascade is synchronous and complete before the response is returned;
        there is no deferred reconciliation and no eventual consistency."

        PRD: "The slot moves `PROPOSED → BOARD_APPROVED` with `awarded_amount_cents` recorded."

        PRD: "And the cycle's `funded_total_cents`, `admin_assessment_rate`,
        `admin_assessment_cents`, `committed_cents`, `available_cents` and `posture` are all
        recomputed by the rules of §2.7."

        Design: Corner/consistency_model/board_approval_response_already_carries_every_derived_change
        """
        ctx = cornermain_slate_submitted()

        approved = validate_success(
            api_client.board_action(
                ctx.slot,
                {"action": "APPROVE", "expected_cycle_version": cycle_version(ctx.cyc)},
                BOARD_MEMBER,
            )
        )
        assert approved["status"] == "BOARD_APPROVED", (
            f"the response already shows the disposition, got {approved['status']}"
        )
        assert_cents(
            approved["awarded_amount_cents"], 1_500_000, "slot.awarded_amount_cents"
        )
        assert approved["board_action_by"] == BOARD_MEMBER_ID, (
            f"the acting board member is stamped, got {approved['board_action_by']}"
        )

        assert_cycle_ledger(
            read_cycle(ctx.cyc),
            1_500_000,
            0.085,
            127_500,
            300_000,
            1_627_500,
            4_072_500,
            "OPEN",
        )
        discipline = read_discipline(ctx.disc)
        assert_cents(discipline["committed_cents"], 1_500_000, "discipline.committed_cents")
        assert discipline["funded_application_count"] == 1, (
            f"the funded application is counted, got {discipline['funded_application_count']}"
        )
        assert read_artist(ctx.art)["active_award_count"] == 1, (
            "the artist now holds one active award"
        )

        rows, meta = validate_paginated(
            api_client.list_awards(PROGRAM_OFFICER, {"application_id": ctx.app})
        )
        assert meta["total_count"] == 1, (
            f"the award is discoverable at once, got {meta['total_count']}"
        )
        award = rows[0]
        assert award["status"] == "OFFERED", (
            f"a new award begins offered, got {award['status']}"
        )
        assert award["payment_status"] == "UNPAID", (
            f"nothing is paid yet, got {award['payment_status']}"
        )
        assert award["reporting_status"] == "NOT_DUE", (
            f"no report is due yet, got {award['reporting_status']}"
        )
        assert_cents(award["gross_amount_cents"], 1_500_000, "award.gross_amount_cents")
        assert str(award["acceptance_deadline_at"]).startswith("2026-10-30"), (
            "the acceptance window runs fourteen days from the clock, got "
            f"{award['acceptance_deadline_at']}"
        )
