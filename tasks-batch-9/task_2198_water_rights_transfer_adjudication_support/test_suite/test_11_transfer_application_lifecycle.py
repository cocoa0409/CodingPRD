"""The transfer application's declared edges, and the analyses they freeze.

PRD §3.4: "An application is drafted against a certified quantification by the
claimant, an analyst or the adjudicator."
"""
import pytest
from test_helpers import (
    assert_same_instant,
    ApiErrorId,
    api_client,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers.factories import create_transfer_application_payload
from test_helpers.fixtures import (
    ANALYST,
    DECIDER,
    HEARING_OFFICER,
    add_injury_analysis,
    add_point_of_diversion,
    conditions_of,
    create_claimant,
    decide,
    file_protest,
    publish_application,
    read_application,
    read_claimant,
    read_right,
    resubmit_application,
    right_version,
    set_clock,
    setup_certified_right,
    setup_draft_application,
    setup_protested_application,
)
from test_helpers.test_users import DECIDER_USER_ID

CLOCK = "2026-03-01T00:00:00Z"
FIRST_DEADLINE = "2026-03-31T00:00:00Z"


class TestTheUnprotestedSpine:
    """PRD §3.4 / §3.7 — the whole undisputed path in one run.

    A certified right carrying 195.00 AF of transferable water backs a 100.00 AF
    `CHANGE_OF_USE` application. The analysis is a `SEASONAL_AVERAGE` one whose
    return-flow credit of 78.00 AF exactly cancels its own gross depletion, so
    unconditional approval is admissible at the end of the run.
    """

    def test_the_unprotested_spine_converts_escrow_into_a_permanent_transfer(self):
        """PRD §3.4: "A successful submission moves the application `DRAFT →
        SUBMITTED` and sets `escrowed_af` to `requested_af`." And: "On the right,
        `encumbered_af` increases by that same amount and `transferable_af` decreases by
        it, conserving the ledger identity; the right's status is re-derived, which is
        what carries an otherwise idle right `ACTIVE → ENCUMBERED`; the claimant's
        `open_application_count` is recomputed; and both the application's and the
        right's `version` are bumped."

        PRD §3.5 stamps the first window at "thirty days out on a first
        publication, when `revision_round` is 0". PRD §3.5 then closes it: "the
        logical clock must have reached `protest_deadline`", and "On success the
        application's `DRAFT` injury analysis moves to the terminal `FINALIZED`,
        freezing `gross_depletion_af`, `offset_af` and `net_injury_af` at their
        current values". PRD §3.7 finishes the move: "the application moves
        `READY_FOR_DECISION → APPROVED`, `escrowed_af` is set to 0.00, and on the
        right the escrowed volume moves out of `encumbered_af` and into
        `transferred_away_af` so that the conserved identity holds across the
        move."

        Design: Corner/state_machines/sm_transfer_application_unprotested_path_reaches_approved
        """
        bundle = setup_draft_application(requested_af=100.00, clock=CLOCK)
        right_id = bundle["right"]["id"]
        application_id = bundle["application"]["id"]
        assert bundle["right"]["transferable_af"] == pytest.approx(195.00, abs=0.01)

        submitted = get_success_data(
            api_client.submit_transfer_application(
                application_id, right_version(right_id), ANALYST
            )
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["escrowed_af"] == pytest.approx(100.00, abs=0.01)
        escrowed = read_right(right_id)
        assert escrowed["encumbered_af"] == pytest.approx(100.00, abs=0.01)
        assert escrowed["transferable_af"] == pytest.approx(95.00, abs=0.01)
        assert escrowed["transferred_away_af"] == pytest.approx(0.00, abs=0.01)
        assert escrowed["status"] == "ENCUMBERED"

        analysis = add_injury_analysis(
            application_id, "SEASONAL_AVERAGE", 0.00, return_flow_credit_af=78.00
        )
        published = publish_application(application_id)
        assert published["status"] == "PROTEST_PERIOD"
        assert_same_instant(published["protest_deadline"], FIRST_DEADLINE, "protest_deadline")

        set_clock(FIRST_DEADLINE)
        closed = get_success_data(
            api_client.close_protest_period(application_id, HEARING_OFFICER)
        )
        assert closed["status"] == "READY_FOR_DECISION"
        frozen = get_success_data(
            api_client.get_injury_analysis(analysis["id"], ANALYST)
        )
        assert frozen["status"] == "FINALIZED"
        assert frozen["gross_depletion_af"] == pytest.approx(78.00, abs=0.01)
        assert frozen["offset_af"] == pytest.approx(0.00, abs=0.01)
        assert frozen["net_injury_af"] == pytest.approx(0.00, abs=0.01)

        approved = decide(application_id, "APPROVE")

        assert approved["status"] == "APPROVED"
        assert approved["escrowed_af"] == pytest.approx(0.00, abs=0.01)
        assert approved["decided_by_user_id"] == DECIDER_USER_ID
        assert approved["mitigation_fee_total_usd"] == pytest.approx(0.00, abs=0.01)
        assert conditions_of(application_id) == [], (
            "PRD §3.7 — unconditional approval creates no approval condition"
        )
        final = read_right(right_id)
        assert final["encumbered_af"] == pytest.approx(0.00, abs=0.01)
        assert final["transferred_away_af"] == pytest.approx(100.00, abs=0.01)
        assert final["transferable_af"] == pytest.approx(95.00, abs=0.01)
        assert final["status"] == "PARTIALLY_TRANSFERRED"
        assert final["pending_review_count"] == 0
        assert read_claimant(bundle["claimant"]["id"])["open_application_count"] == 0


class TestWithdrawalIsACompensatingCascade:
    """PRD §3.4 — one call unwinds the escrow and closes both child families.

    A 100.00 AF application on a 195.00 AF right is published and then protested
    by a second claimant, so it sits in `UNDER_PROTEST` with one `FILED` protest
    and one `DRAFT` `INSTANTANEOUS_DEPLETION` analysis measured over 4.00 river
    miles.
    """

    def test_withdrawal_dismisses_the_protest_and_voids_the_draft_analysis(self):
        """PRD §3.4: "The application reaches the terminal `WITHDRAWN`;
        `escrowed_af` is released to 0.00 and the released volume moves from the
        right's `encumbered_af` back into its `transferable_af`, conserving the
        ledger, with the right's status re-derived and its `version` bumped."

        PRD §3.4: "Every protest on the application still in `FILED`,
        `IN_NEGOTIATION` or `IN_HEARING` moves to the terminal `DISMISSED` with
        its `version` bumped and `unresolved_protest_count` recomputed to 0; any
        `DRAFT` injury analysis moves to the terminal `VOIDED` with its `version`
        bumped and `pending_review_count` recomputed; and the claimant's
        `open_application_count` is recomputed."

        The voided analysis keeps the figures it carried: PRD §3.5 computes a
        distance factor of "one minus fifteen thousandths for each river mile of
        the move", which is 0.9400 over 4.00 miles, and a gross depletion of
        100.00 * 0.92 * 0.9400 = 86.48 that no credit offsets.

        Design: Corner/state_machines/sm_transfer_application_withdraw_dismisses_protest_and_voids_analysis
        """
        bundle = setup_protested_application(
            requested_af=100.00,
            claimed_injury_af=12.00,
            clock=CLOCK,
            injury_method="INSTANTANEOUS_DEPLETION",
            pod_move_miles=4.00,
        )
        right_id = bundle["right"]["id"]
        assert bundle["application"]["status"] == "UNDER_PROTEST"
        protest_version_before = bundle["protest"]["version"]

        application = get_success_data(
            api_client.withdraw_transfer_application(
                bundle["application"]["id"],
                "Applicant is re-scoping the project outside this docket.",
                ANALYST,
            )
        )

        assert application["status"] == "WITHDRAWN"
        assert application["escrowed_af"] == pytest.approx(0.00, abs=0.01)
        assert application["unresolved_protest_count"] == 0
        protest = get_success_data(
            api_client.get_protest(bundle["protest"]["id"], ANALYST)
        )
        assert protest["status"] == "DISMISSED"
        assert protest["stipulated_offset_af"] == pytest.approx(0.00, abs=0.01)
        assert protest["version"] > protest_version_before
        analysis = get_success_data(
            api_client.get_injury_analysis(bundle["analysis"]["id"], ANALYST)
        )
        assert analysis["status"] == "VOIDED"
        assert analysis["gross_depletion_af"] == pytest.approx(86.48, abs=0.01)
        assert analysis["offset_af"] == pytest.approx(0.00, abs=0.01)
        assert analysis["net_injury_af"] == pytest.approx(86.48, abs=0.01)
        right = read_right(right_id)
        assert right["certified_hcu_af"] == pytest.approx(195.00, abs=0.01)
        assert right["encumbered_af"] == pytest.approx(0.00, abs=0.01)
        assert right["transferred_away_af"] == pytest.approx(0.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(195.00, abs=0.01)
        assert right["status"] == "ACTIVE"
        assert right["pending_review_count"] == 0
        assert read_claimant(bundle["claimant"]["id"])["open_application_count"] == 0


class TestWithdrawnIsTerminal:
    """PRD §3.4 — a `DRAFT` application withdrawn before submission.

    Nothing was ever escrowed and no injury analysis was ever prepared, which is
    what makes the ordering visible: each refusal below has a second, independent
    defect available to it and still reports the state failure.
    """

    def _withdrawn_from_draft(self):
        bundle = setup_draft_application(requested_af=100.00, clock=CLOCK)
        bundle["application"] = get_success_data(
            api_client.withdraw_transfer_application(
                bundle["application"]["id"], "Filed in the wrong basin.", ANALYST
            )
        )
        return bundle

    def test_a_withdrawn_application_refuses_every_further_edge(self):
        """PRD §3.4: "Withdrawal from `DRAFT` is the one case where there is no
        escrow to release and no ledger movement occurs at all."

        PRD §2.11 orders the ladder so that "the domain-specific referential,
        uniqueness, concurrency, state, safety, temporal, constraint and fiscal
        families" run in that sequence — but publication's own missing-analysis
        rule is a safety rule that sits *after* the state check, so a terminal
        application that never had an analysis still reports `ERR_INVALID_STATE`
        rather than `ERR_INJURY_ANALYSIS_MISSING`.

        Design: Corner/state_machines/sm_transfer_application_withdrawn_is_terminal_and_locked
        """
        bundle = self._withdrawn_from_draft()
        application_id = bundle["application"]["id"]
        right_id = bundle["right"]["id"]
        assert bundle["application"]["status"] == "WITHDRAWN"
        version_before = bundle["application"]["version"]

        refusals = {
            "submit": api_client.submit_transfer_application(
                application_id, right_version(right_id), ANALYST
            ),
            "withdraw": api_client.withdraw_transfer_application(
                application_id, "Second attempt at the same escape hatch.", ANALYST
            ),
            "publish": api_client.publish_transfer_application(
                application_id, ANALYST
            ),
            "decide": api_client.decide_transfer_application(
                application_id,
                {"disposition": "DENY", "decision_note": "Findings of record."},
                DECIDER,
            ),
        }

        for edge, response in refusals.items():
            assert response.status_code == 409, f"{edge} must be refused on state"
            validate_error(
                response, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409
            )
        application = read_application(application_id)
        assert application["status"] == "WITHDRAWN"
        assert application["escrowed_af"] == pytest.approx(0.00, abs=0.01)
        assert application["version"] == version_before
        right = read_right(right_id)
        assert right["transferable_af"] == pytest.approx(195.00, abs=0.01)
        assert right["encumbered_af"] == pytest.approx(0.00, abs=0.01)


class TestTheRevisionCapClosesTheCycle:
    """PRD §3.6 — "This closes the cycle `SUBMITTED → PROTEST_PERIOD →
    UNDER_PROTEST → REVISION_REQUESTED → SUBMITTED`, which may run at most
    twice."

    Three separate protestants are needed, because a revision request holds the
    existing protests exactly where they are and PRD §3.6 forbids one protestant
    from holding two protests on the same application. The application is taken
    twice around the loop, from 100.00 AF down to 90.00 and then to 80.00, with
    the logical clock never moving off 2026-03-01.
    """

    PROTESTANTS = (
        ("Cottonwood Cattle Co", "b@cotton.example", "INDIVIDUAL", 12.00),
        ("City of Rill", "c@rill.example", "MUNICIPALITY", 5.00),
        ("Shoshone-Paiute Tribes", "d@tribe.example", "TRIBE", 3.00),
    )
    SHORT_DEADLINE = "2026-03-16T00:00:00Z"

    def _twice_around_the_loop(self):
        bundle = setup_draft_application(requested_af=100.00, clock=CLOCK)
        application_id = bundle["application"]["id"]
        right_id = bundle["right"]["id"]
        add_injury_analysis(application_id, "SEASONAL_AVERAGE", 0.00)
        get_success_data(
            api_client.submit_transfer_application(
                application_id, right_version(right_id), ANALYST
            )
        )
        publish_application(application_id)
        bundle["protestants"] = [
            create_claimant(legal_name=name, contact_email=email, entity_type=kind)
            for name, email, kind, _injury in self.PROTESTANTS
        ]
        bundle["deadlines"] = []
        for round_index, requested_af in ((0, 90.00), (1, 80.00)):
            file_protest(
                application_id,
                bundle["protestants"][round_index]["id"],
                self.PROTESTANTS[round_index][3],
            )
            get_success_data(
                api_client.request_revision(
                    application_id, "Re-scope the requested volume.", HEARING_OFFICER
                )
            )
            resubmit_application(application_id, right_id, requested_af)
            bundle["deadlines"].append(
                publish_application(application_id)["protest_deadline"]
            )
        file_protest(
            application_id, bundle["protestants"][2]["id"], self.PROTESTANTS[2][3]
        )
        bundle["application"] = read_application(application_id)
        return bundle

    def test_the_third_revision_request_is_refused_at_the_cap(self):
        """PRD §3.6: "The alternative to clearing protests is sending the
        application back to be re-scoped, which only a `HearingOfficer` may do and
        which requires `revision_round` to be strictly below the cap of 2 and at
        least one unresolved protest to exist."

        Both preconditions of that sentence are examined at once: the application
        is a perfectly valid `UNDER_PROTEST` row carrying three unresolved
        protests, so the only defect available is the cap, and PRD §3.6 —
        "Exceeding the cap is `ERR_REVISION_LIMIT_REACHED`" — is what comes back.
        PRD §3.4 also shows the escrow was swapped rather than stacked: "the
        right's `encumbered_af` first decreases by the old escrow and then
        increases by the new requested volume", leaving 80.00 encumbered against a
        195.00 AF certified volume rather than 270.00.

        Design: Corner/state_machines/sm_transfer_application_third_revision_request_rejected_at_cap
        """
        bundle = self._twice_around_the_loop()
        application_id = bundle["application"]["id"]
        assert bundle["application"]["status"] == "UNDER_PROTEST"
        assert bundle["application"]["revision_round"] == 2
        version_before = bundle["application"]["version"]

        response = api_client.request_revision(
            application_id, "Third re-scope attempt.", HEARING_OFFICER
        )

        validate_error(
            response, ApiErrorId.ERR_REVISION_LIMIT_REACHED.value, expected_status=409
        )
        application = read_application(application_id)
        assert application["status"] == "UNDER_PROTEST"
        assert application["revision_round"] == 2
        assert application["requested_af"] == pytest.approx(80.00, abs=0.01)
        assert application["escrowed_af"] == pytest.approx(80.00, abs=0.01)
        assert application["unresolved_protest_count"] == 3
        assert application["version"] == version_before
        right = read_right(bundle["right"]["id"])
        assert right["encumbered_af"] == pytest.approx(80.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(115.00, abs=0.01)

    def test_every_republication_after_a_revision_uses_the_shorter_window(self):
        """PRD §3.5: "`protest_deadline` is stamped from the logical clock at
        thirty days out on a first publication, when `revision_round` is 0, and at
        fifteen days out on every republication after a revision, when
        `revision_round` is 1 or more — a revised application gets a materially
        shorter window because the basin has already had its first look."

        The clock never leaves 2026-03-01, so both republications land on
        2026-03-16 and neither one lands on the 2026-03-31 that a first
        publication would have produced. The rule keys off `revision_round`, not
        off how many times publication has been called.

        Design: Corner/state_machines/sm_transfer_application_third_revision_request_rejected_at_cap
        """
        bundle = self._twice_around_the_loop()

        for _d in bundle["deadlines"]:
            assert_same_instant(_d, self.SHORT_DEADLINE, "protest_deadline")
        assert_same_instant(bundle["application"]["protest_deadline"], self.SHORT_DEADLINE, "protest_deadline")


class TestRepostingAnAnalysisVoidsThePriorDraft:
    """PRD §3.5 — "At most one analysis may be pending per application."

    One 100.00 AF `DRAFT` application carries an `INSTANTANEOUS_DEPLETION`
    analysis measured over 4.00 river miles, which is then replaced by a
    `SEASONAL_AVERAGE` analysis quoting the same 4.00 miles and claiming a 10.00
    AF return-flow credit.
    """

    def test_reposting_voids_the_prior_draft_and_nets_the_pending_count_to_zero(self):
        """PRD §3.5: "Preparing a new one moves any existing `DRAFT` analysis on the
        same application to the terminal `VOIDED` with its `version` bumped, and seeds
        the new analysis's `offset_af` from the offsets already stipulated, so re-running
        an analysis in the middle of a negotiation does not silently discard concessions
        the protestants already obtained."

        PRD §3.5: "`pending_review_count` on the right is the number of `DRAFT`
        injury analyses whose application sits on that right; it therefore rises
        by one for a first analysis and nets to zero when one draft replaces
        another, and the right's `version` is bumped either way."

        The two rows keep their own arithmetic. PRD §3.5: "Under `SEASONAL_AVERAGE`
        there is no distance attenuation whatsoever — `pod_move_miles` is read from
        the payload, stored, and then ignored by the arithmetic — and gross
        depletion is simply `requested_af` multiplied by a flat seasonal factor of
        0.78, rounded to 2 decimal places." So the survivor reads 78.00 gross
        against 68.00 net, while the voided row keeps the 0.9400 factor and the
        86.48 gross depletion it was computed with.

        Design: Corner/state_machines/sm_injury_analysis_reposting_voids_the_prior_draft
        """
        bundle = setup_draft_application(requested_af=100.00, clock=CLOCK)
        application_id = bundle["application"]["id"]
        right_id = bundle["right"]["id"]
        first = add_injury_analysis(application_id, "INSTANTANEOUS_DEPLETION", 4.00)
        before = read_right(right_id)
        assert before["pending_review_count"] == 1

        second = add_injury_analysis(
            application_id, "SEASONAL_AVERAGE", 4.00, return_flow_credit_af=10.00
        )

        assert second["status"] == "DRAFT"
        assert second["pod_move_miles"] == pytest.approx(4.00, abs=0.01)
        assert second["gross_depletion_af"] == pytest.approx(78.00, abs=0.01)
        assert second["offset_af"] == pytest.approx(0.00, abs=0.01)
        assert second["net_injury_af"] == pytest.approx(68.00, abs=0.01)
        voided = get_success_data(
            api_client.get_injury_analysis(first["id"], ANALYST)
        )
        assert voided["status"] == "VOIDED"
        assert voided["gross_depletion_af"] == pytest.approx(86.48, abs=0.01)
        assert voided["net_injury_af"] == pytest.approx(86.48, abs=0.01)
        assert voided["version"] > first["version"]
        drafts, draft_meta = validate_paginated(
            api_client.list_injury_analyses(
                application_id, ANALYST, params={"status": "DRAFT"}
            )
        )
        assert draft_meta["total_count"] == 1
        assert [row["id"] for row in drafts] == [second["id"]]
        every, every_meta = validate_paginated(
            api_client.list_injury_analyses(application_id, ANALYST)
        )
        assert every_meta["total_count"] == 2
        assert {row["id"] for row in every} == {first["id"], second["id"]}
        after = read_right(right_id)
        assert after["pending_review_count"] == before["pending_review_count"]
        assert after["version"] > before["version"]


class TestApprovingAHeadgateMoveSwapsTheAuthorizedHeadgate:
    """PRD §3.7 — the only route to the terminal `RETIRED` headgate state.

    One right owns two headgates. The upper one at river mile 41.20 was
    registered before activation, so it is `AUTHORIZED`; the lower one at river
    mile 46.80 was registered afterwards, so it is still `PROPOSED`. A 100.00 AF
    `POINT_OF_DIVERSION_CHANGE` application names the lower headgate, and its
    `INSTANTANEOUS_DEPLETION` analysis over the 5.60-mile separation is fully
    offset by return flow, which makes unconditional approval admissible.
    """

    UPPER = {
        "max_rate_cfs": 5.000,
        "legal_description": "NE1/4 SEC 12 T3N R4E headgate",
        "stream_reach_code": "SNK-14-A",
        "stream_miles_from_headwater": 41.20,
    }
    LOWER = {
        "max_rate_cfs": 4.000,
        "legal_description": "SW1/4 SEC 18 T3N R4E headgate",
        "stream_reach_code": "SNK-14-B",
        "stream_miles_from_headwater": 46.80,
    }

    def _ready_for_decision(self):
        bundle = setup_certified_right(clock=CLOCK, pod_specs=[self.UPPER])
        right_id = bundle["right"]["id"]
        bundle["upper"] = bundle["pods"][0]
        bundle["lower"] = add_point_of_diversion(right_id, **self.LOWER)
        payload = create_transfer_application_payload(
            right_id,
            bundle["study"]["id"],
            100.00,
            application_type="POINT_OF_DIVERSION_CHANGE",
            proposed_point_of_diversion_id=bundle["lower"]["id"],
        )
        del payload["proposed_purpose_of_use"]
        application = get_success_data(
            api_client.create_transfer_application(payload, ANALYST),
            expected_status=201,
        )
        bundle["analysis"] = add_injury_analysis(
            application["id"],
            "INSTANTANEOUS_DEPLETION",
            5.60,
            return_flow_credit_af=84.27,
        )
        get_success_data(
            api_client.submit_transfer_application(
                application["id"], right_version(right_id), ANALYST
            )
        )
        publish_application(application["id"])
        set_clock(FIRST_DEADLINE)
        bundle["application"] = get_success_data(
            api_client.close_protest_period(application["id"], HEARING_OFFICER)
        )
        return bundle

    def test_approval_authorizes_the_proposed_headgate_and_retires_the_other(self):
        """PRD §3.7: "When the `application_type` is `POINT_OF_DIVERSION_CHANGE`
        or `COMBINED`, the application's `proposed_point_of_diversion_id` names a
        headgate that moves `PROPOSED → AUTHORIZED`, and every *other* headgate on
        the same right currently in `AUTHORIZED` moves to the terminal `RETIRED`."

        It is a swap rather than an addition, so PRD §3.1's terminal state — a
        headgate "reaches the terminal `RETIRED` only when a newly authorized
        headgate supersedes it" — is reached in the very same call that promotes
        its replacement, and the `AUTHORIZED` listing still holds exactly one row.

        Design: Corner/state_machines/sm_pod_change_approval_authorizes_proposed_and_retires_superseded_headgate
        """
        bundle = self._ready_for_decision()
        assert bundle["upper"]["status"] == "AUTHORIZED"
        assert bundle["lower"]["status"] == "PROPOSED"
        frozen = get_success_data(
            api_client.get_injury_analysis(bundle["analysis"]["id"], ANALYST)
        )
        assert frozen["status"] == "FINALIZED"
        assert frozen["gross_depletion_af"] == pytest.approx(84.27, abs=0.01)
        assert frozen["net_injury_af"] == pytest.approx(0.00, abs=0.01)

        application = decide(bundle["application"]["id"], "APPROVE")

        assert application["status"] == "APPROVED"
        upper = get_success_data(
            api_client.get_point_of_diversion(bundle["upper"]["id"], ANALYST)
        )
        lower = get_success_data(
            api_client.get_point_of_diversion(bundle["lower"]["id"], ANALYST)
        )
        assert lower["status"] == "AUTHORIZED"
        assert upper["status"] == "RETIRED"
        authorized, meta = validate_paginated(
            api_client.list_points_of_diversion(
                bundle["right"]["id"], ANALYST, params={"status": "AUTHORIZED"}
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in authorized] == [bundle["lower"]["id"]]
        right = read_right(bundle["right"]["id"])
        assert right["encumbered_af"] == pytest.approx(0.00, abs=0.01)
        assert right["transferred_away_af"] == pytest.approx(100.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(95.00, abs=0.01)
        assert right["status"] == "PARTIALLY_TRANSFERRED"
