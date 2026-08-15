"""Amendment quorum, fiduciary minutes, OCC finalize, and cascades (PRD §3.8)."""
from test_helpers import (
    ADVISOR,
    BOGUS_UUID,
    ApiErrorId,
    assert_iso_instant_equal,
    create_active_client,
    create_active_ips,
    create_benchmark,
    create_committee_minute_payload,
    create_draft_amendment,
    create_ips_payload,
    create_ratified_minute,
    finalize_amendment,
    generate_proposal,
    get_success_data,
    ips_version,
    make_advisor_headers,
    make_committee_chair_headers,
    make_committee_member_headers,
    proposal_trades,
    setup_breached_60_40,
    setup_quorum_amendment,
    submit_amendment,
    validate_error,
    validate_success,
    vote_to_quorum,
)

T_CASH = [
    {"asset_class": "CASH_EQUIVALENT", "target_pct": 100.00, "band_pct": 50.00},
]
T_60_40 = [
    {"asset_class": "US_EQUITY", "target_pct": 60.00, "band_pct": 5.00},
    {"asset_class": "CASH_EQUIVALENT", "target_pct": 40.00, "band_pct": 5.00},
]


class TestAmendmentDraftAndVote:
    def test_amendment_requires_at_least_one_change_lever(self, api):
        """PRD §3.8: "An `Advisor` drafts an amendment against an existing IPS
        by naming `ips_id` and at least one change lever among
        `proposed_objective_text`, `proposed_review_cadence_months` (1 to 24
        inclusive), `proposed_risk_tolerance_score` (1 to 100 inclusive), and
        `proposed_benchmark_id`; a draft carrying no lever at all is rejected
        with `ERR_AMENDMENT_EMPTY_CHANGES`."

        Design: Corner/validations/amendment_requires_at_least_one_change_lever
        """
        client = create_active_client(full_name="AE", risk_tolerance_score=50)
        bench = create_benchmark(name="Bench")
        ips = create_active_ips(client, bench, targets=T_CASH)
        validate_error(api.create_ips_amendment({"ips_id": ips["id"]}, ADVISOR),
                       ApiErrorId.ERR_AMENDMENT_EMPTY_CHANGES)

    def test_duplicate_vote_rejected_and_count_stable(self, api):
        """PRD §3.8: "Each member votes at most once; a second vote from the
        same member is rejected with `ERR_DUPLICATE_VOTE`."

        Design: Corner/validations/duplicate_vote_rejected_and_count_stable
        """
        client = create_active_client(full_name="DV", risk_tolerance_score=50)
        bench = create_benchmark(name="Bench")
        ips = create_active_ips(client, bench, targets=T_CASH)
        amendment = create_draft_amendment(ips["id"], proposer="adv-1",
                                           proposed_objective_text="New")
        submit_amendment(amendment["id"], proposer="adv-1")
        get_success_data(api.vote_ips_amendment(
            amendment["id"], "APPROVE", make_committee_member_headers("cm-1")))
        # A second vote by the same identity — even with a different decision.
        validate_error(api.vote_ips_amendment(
            amendment["id"], "REJECT", make_committee_member_headers("cm-1")),
            ApiErrorId.ERR_DUPLICATE_VOTE)
        current = validate_success(api.get_ips_amendment(amendment["id"], ADVISOR))
        assert current["approve_votes"] == 1
        assert current["reject_votes"] == 0
        assert current["status"] == "SUBMITTED"

    def test_proposer_cannot_vote_on_own_amendment(self, api):
        """PRD §3.8: "Segregation of duties bars the proposer: a voter whose
        identity equals `proposed_by_user_id` is rejected with
        `ERR_SOD_SELF_VOTE`."

        Design: Corner/validations/proposer_cannot_vote_on_own_amendment
        """
        client = create_active_client(full_name="SoD", risk_tolerance_score=50)
        bench = create_benchmark(name="Bench")
        ips = create_active_ips(client, bench, targets=T_CASH)
        amendment = create_draft_amendment(ips["id"], proposer="adv-1",
                                           proposed_objective_text="New")
        submit_amendment(amendment["id"], proposer="adv-1")
        # The proposer votes — even while wearing the CommitteeMember role.
        validate_error(api.vote_ips_amendment(
            amendment["id"], "APPROVE", make_committee_member_headers("adv-1")),
            ApiErrorId.ERR_SOD_SELF_VOTE)
        current = validate_success(api.get_ips_amendment(amendment["id"], ADVISOR))
        assert current["approve_votes"] == 0
        assert current["status"] == "SUBMITTED"

    def test_amendment_guards_state_ownership_and_prequorum_finalize(self, api):
        """PRD §3.8: "A `CommitteeMember` casts a `decision` of `APPROVE` or
        `REJECT` on a `SUBMITTED` amendment — voting at any other time is
        `ERR_AMENDMENT_INVALID_STATE`."
        PRD §3.8: "Submission — an `Advisor` action — moves `DRAFT → SUBMITTED`
        and requires the referenced IPS to be `ACTIVE` at that moment, else
        `ERR_IPS_INVALID_STATE`"
        PRD §2.1: "withdrawing a policy amendment requires the caller's
        `X-User-ID` to equal the amendment's `proposed_by_user_id`."
        PRD §3.8: "The amendment must stand in `QUORUM_REACHED`, else
        `ERR_AMENDMENT_INVALID_STATE`."

        Design: Corner/state_machines/amendment_guards_state_ownership_and_prequorum_finalize
        """
        client = create_active_client(full_name="AmG", risk_tolerance_score=50)
        bench = create_benchmark(name="Bench")
        # A DRAFT IPS that is never submitted.
        ips_draft = get_success_data(api.create_ips(
            create_ips_payload(client["id"], bench["id"], objective_text="DraftIPS",
                               risk_tolerance_score=50), ADVISOR))
        ips_active = create_active_ips(client, bench, targets=T_CASH,
                                       objective_text="ActiveIPS")
        amendment = create_draft_amendment(ips_active["id"], proposer="adv-1",
                                           proposed_objective_text="New")
        minute = create_ratified_minute(amendment_refs=[], recorder="cm-1",
                                        chair="chair-1", decisions_text="None")
        # Vote on a DRAFT amendment.
        validate_error(api.vote_ips_amendment(
            amendment["id"], "APPROVE", make_committee_member_headers("cm-1")),
            ApiErrorId.ERR_AMENDMENT_INVALID_STATE)
        # Withdraw by a non-proposer.
        validate_error(api.withdraw_ips_amendment(
            amendment["id"], make_advisor_headers("adv-2")),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        # Submit against a DRAFT IPS.
        draft_am = create_draft_amendment(ips_draft["id"], proposer="adv-1",
                                          proposed_objective_text="Y")
        validate_error(api.submit_ips_amendment(
            draft_am["id"], make_advisor_headers("adv-1")),
            ApiErrorId.ERR_IPS_INVALID_STATE)
        # Finalize before quorum, even with a valid ratified minute and a fresh
        # OCC version.
        submit_amendment(amendment["id"], proposer="adv-1")
        validate_error(api.finalize_ips_amendment(
            amendment["id"], minute["id"], ips_version(ips_active["id"]),
            make_committee_chair_headers("chair-1")),
            ApiErrorId.ERR_AMENDMENT_INVALID_STATE)


class TestQuorumBoundary:
    def test_third_approve_vote_reaches_quorum(self, api):
        """PRD §3.8: "Quorum is three: the vote that records the third distinct
        `APPROVE` moves the amendment `SUBMITTED → QUORUM_REACHED`"

        Design: Difficulty/boundary_precision_check/quorum_exactly_third_vote_flips_status
        """
        client = create_active_client(full_name="Quorum Client",
                                      risk_tolerance_score=50)
        bench = create_benchmark(name="Bench")
        ips = create_active_ips(client, bench, targets=T_60_40)
        amendment = create_draft_amendment(ips["id"], proposer="adv-1",
                                           proposed_review_cadence_months=6)
        submit_amendment(amendment["id"], proposer="adv-1")
        after1 = validate_success(api.vote_ips_amendment(
            amendment["id"], "APPROVE", make_committee_member_headers("cm-1")))
        assert after1["approve_votes"] == 1
        assert after1["status"] == "SUBMITTED"
        after2 = validate_success(api.vote_ips_amendment(
            amendment["id"], "APPROVE", make_committee_member_headers("cm-2")))
        assert after2["approve_votes"] == 2
        assert after2["status"] == "SUBMITTED"
        after3 = validate_success(api.vote_ips_amendment(
            amendment["id"], "APPROVE", make_committee_member_headers("cm-3")))
        assert after3["approve_votes"] == 3
        assert after3["status"] == "QUORUM_REACHED", (
            "the threshold is cumulative and inclusive at 3")

    def test_third_reject_vote_rejects_and_post_quorum_votes_closed(self, api):
        """PRD §3.8: "the vote that records the third distinct `REJECT` moves
        it `SUBMITTED → REJECTED`, terminal."
        PRD §3.8: "voting at any other time is `ERR_AMENDMENT_INVALID_STATE`."

        Design: Difficulty/boundary_precision_check/quorum_exactly_third_vote_flips_status
        """
        client = create_active_client(full_name="Quorum Client",
                                      risk_tolerance_score=50)
        bench = create_benchmark(name="Bench")
        ips = create_active_ips(client, bench, targets=T_60_40)
        am_ok = create_draft_amendment(ips["id"], proposer="adv-1",
                                       proposed_review_cadence_months=6)
        submit_amendment(am_ok["id"], proposer="adv-1")
        am_no = create_draft_amendment(ips["id"], proposer="adv-1",
                                       proposed_risk_tolerance_score=45)
        submit_amendment(am_no["id"], proposer="adv-1")
        rejected = vote_to_quorum(am_no["id"], "REJECT")
        assert rejected["status"] == "REJECTED", "reject quorum mirrors approve"
        assert rejected["reject_votes"] == 3
        vote_to_quorum(am_ok["id"], "APPROVE")
        # QUORUM_REACHED no longer accepts votes.
        validate_error(api.vote_ips_amendment(
            am_ok["id"], "APPROVE", make_committee_member_headers("cm-4")),
            ApiErrorId.ERR_AMENDMENT_INVALID_STATE)


class TestMinuteLifecycle:
    def test_minute_lifecycle_sod_and_reference_guards(self, api):
        """PRD §3.8: "A `CommitteeMember` records a minute with a
        `meeting_date` — which may not be later than the current logical clock
        date, else `ERR_MEETING_DATE_IN_FUTURE`"
        PRD §3.8: "the minute must be `DRAFT`, else `ERR_MINUTE_INVALID_STATE`;
        the chair's identity must differ from `recorded_by_user_id`, else
        `ERR_SOD_MINUTE_SELF_RATIFY`; and every id in `amendment_refs` must
        resolve to an existing amendment, else `ERR_INVALID_REFERENCE`."

        Design: Corner/state_machines/minute_lifecycle_sod_and_reference_guards
        """
        # Bogus amendment_refs element at creation.
        validate_error(api.create_committee_minute(
            create_committee_minute_payload(amendment_refs=[BOGUS_UUID],
                                            decisions_text="X"),
            make_committee_member_headers("cm-1")),
            ApiErrorId.ERR_INVALID_REFERENCE)
        # Future meeting_date (clock is the 2026-08-01 default).
        validate_error(api.create_committee_minute(
            create_committee_minute_payload(meeting_date="2026-08-02",
                                            decisions_text="X"),
            make_committee_member_headers("cm-1")),
            ApiErrorId.ERR_MEETING_DATE_IN_FUTURE)
        minute = validate_success(api.create_committee_minute(
            create_committee_minute_payload(decisions_text="Q3 review"),
            make_committee_member_headers("cm-1")), 201)
        assert minute["status"] == "DRAFT"
        assert minute["recorded_by_user_id"] == "cm-1"
        # The recorder may not ratify, even wearing the chair role.
        validate_error(api.ratify_committee_minute(
            minute["id"], make_committee_chair_headers("cm-1")),
            ApiErrorId.ERR_SOD_MINUTE_SELF_RATIFY)
        ratified = validate_success(api.ratify_committee_minute(
            minute["id"], make_committee_chair_headers("chair-1")))
        assert ratified["status"] == "RATIFIED"
        assert ratified["ratified_by_user_id"] == "chair-1"
        assert ratified["ratified_at"] is not None
        # RATIFIED is terminal.
        validate_error(api.ratify_committee_minute(
            minute["id"], make_committee_chair_headers("chair-2")),
            ApiErrorId.ERR_MINUTE_INVALID_STATE)


class TestFinalizeGates:
    def test_finalize_gated_until_minute_ratified(self, api):
        """PRD §3.8: "the referenced minute must stand in `RATIFIED`, else
        `ERR_AMENDMENT_MINUTE_NOT_RATIFIED`"

        Design: Difficulty/cross_entity_state_dependency/amendment_finalize_gated_by_ratified_minute
        """
        client = create_active_client(full_name="Fiduciary Client",
                                      risk_tolerance_score=50)
        bench = create_benchmark(name="Bench")
        ips = create_active_ips(client, bench, targets=T_60_40)
        amendment = setup_quorum_amendment(ips["id"], proposer="adv-1",
                                           proposed_objective_text="Income oriented")
        minute = get_success_data(api.create_committee_minute(
            create_committee_minute_payload(amendment_refs=[amendment["id"]],
                                            decisions_text="Approved objective change"),
            make_committee_member_headers("cm-1")))
        # The DRAFT minute blocks finalization.
        validate_error(api.finalize_ips_amendment(
            amendment["id"], minute["id"], ips_version(ips["id"]),
            make_committee_chair_headers("chair-1")),
            ApiErrorId.ERR_AMENDMENT_MINUTE_NOT_RATIFIED)
        # After ratification by a different user, the gate opens.
        ratified = validate_success(api.ratify_committee_minute(
            minute["id"], make_committee_chair_headers("chair-1")))
        assert ratified["status"] == "RATIFIED"

    def test_finalize_after_ratification_applies_levers(self, api):
        """PRD §3.8: "A successful finalization applies every non-null proposed
        lever to the IPS, stamps the amendment with `ratified_minute_id`,
        `finalized_by_user_id`, and `finalized_at`"

        Design: Difficulty/cross_entity_state_dependency/amendment_finalize_gated_by_ratified_minute
        """
        client = create_active_client(full_name="Fiduciary Client",
                                      risk_tolerance_score=50)
        bench = create_benchmark(name="Bench")
        ips = create_active_ips(client, bench, targets=T_60_40)
        amendment = setup_quorum_amendment(ips["id"], proposer="adv-1",
                                           proposed_objective_text="Income oriented")
        minute = create_ratified_minute(amendment_refs=[amendment["id"]],
                                        recorder="cm-1", chair="chair-1",
                                        decisions_text="Approved objective change")
        finalized = finalize_amendment(amendment["id"], minute["id"], chair="chair-1")
        assert finalized["status"] == "APPROVED"
        assert finalized["ratified_minute_id"] == minute["id"]
        assert finalized["finalized_by_user_id"] == "chair-1"
        assert finalized["finalized_at"] is not None
        updated = validate_success(api.get_ips(ips["id"], ADVISOR))
        assert updated["objective_text"] == "Income oriented"

    def test_finalize_draft_minute_missing_ref_safety_beats_referential(self, api):
        """PRD §2.7: "Checks run in a fixed priority order, and when several
        checks would fail, the request is rejected with the error from the
        earliest category" — the fiduciary gate `ERR_AMENDMENT_MINUTE_NOT_RATIFIED`
        (category 9) precedes the referential `ERR_AMENDMENT_NOT_IN_MINUTE`
        (category 10).

        Design: Difficulty/priority_pair_validation_conflict/finalize_draft_minute_missing_ref_safety_beats_referential
        """
        client = create_active_client(full_name="Gate Client",
                                      risk_tolerance_score=50)
        bench = create_benchmark(name="Bench")
        ips = create_active_ips(client, bench, targets=T_60_40)
        amendment = setup_quorum_amendment(
            ips["id"], proposer="adv-1",
            proposed_objective_text="Capital preservation first")
        # A DRAFT minute that also does NOT reference the amendment.
        minute = get_success_data(api.create_committee_minute(
            create_committee_minute_payload(amendment_refs=[],
                                            decisions_text="No decisions"),
            make_committee_member_headers("cm-1")))
        validate_error(api.finalize_ips_amendment(
            amendment["id"], minute["id"], ips_version(ips["id"]),
            make_committee_chair_headers("chair-1")),
            ApiErrorId.ERR_AMENDMENT_MINUTE_NOT_RATIFIED)

    def test_finalize_priority_failure_leaves_state_unchanged(self, api):
        """PRD §3.8: "The amendment must stand in `QUORUM_REACHED`, else
        `ERR_AMENDMENT_INVALID_STATE`." — a rejected finalize applies no levers
        and leaves the amendment QUORUM_REACHED.

        Design: Difficulty/priority_pair_validation_conflict/finalize_draft_minute_missing_ref_safety_beats_referential
        """
        client = create_active_client(full_name="Gate Client",
                                      risk_tolerance_score=50)
        bench = create_benchmark(name="Bench")
        ips = create_active_ips(client, bench, targets=T_60_40)
        amendment = setup_quorum_amendment(
            ips["id"], proposer="adv-1",
            proposed_objective_text="Capital preservation first")
        minute = get_success_data(api.create_committee_minute(
            create_committee_minute_payload(amendment_refs=[],
                                            decisions_text="No decisions"),
            make_committee_member_headers("cm-1")))
        validate_error(api.finalize_ips_amendment(
            amendment["id"], minute["id"], ips_version(ips["id"]),
            make_committee_chair_headers("chair-1")),
            ApiErrorId.ERR_AMENDMENT_MINUTE_NOT_RATIFIED)
        current = validate_success(api.get_ips_amendment(amendment["id"], ADVISOR))
        assert current["status"] == "QUORUM_REACHED"
        unchanged = validate_success(api.get_ips(ips["id"], ADVISOR))
        assert unchanged["review_cadence_months"] == 12
        assert unchanged["objective_text"] == "Growth"

    def test_finalize_with_ratified_minute_lacking_amendment_ref(self, api):
        """PRD §3.8: "the amendment's own id must appear in that minute's
        `amendment_refs`, else `ERR_AMENDMENT_NOT_IN_MINUTE`."

        Design: Corner/validations/finalize_with_ratified_minute_lacking_amendment_ref
        """
        client = create_active_client(full_name="NIM", risk_tolerance_score=50)
        bench = create_benchmark(name="Bench")
        ips = create_active_ips(client, bench, targets=T_CASH)
        amendment = setup_quorum_amendment(ips["id"], proposer="adv-1",
                                           proposed_objective_text="New")
        # A RATIFIED minute whose amendment_refs do not include the amendment.
        minute = create_ratified_minute(amendment_refs=[], recorder="cm-1",
                                        chair="chair-1",
                                        decisions_text="Unrelated business")
        validate_error(api.finalize_ips_amendment(
            amendment["id"], minute["id"], ips_version(ips["id"]),
            make_committee_chair_headers("chair-1")),
            ApiErrorId.ERR_AMENDMENT_NOT_IN_MINUTE)
        assert validate_success(api.get_ips_amendment(amendment["id"], ADVISOR))[
            "status"] == "QUORUM_REACHED"


class TestFinalizeCascadeAndOcc:
    def test_finalize_cascade_applies_levers_and_expires_proposals(self, api):
        """PRD §3.8: "The version bump detonates the pin cascade: every
        rebalance proposal pinned to the amended IPS whose `pinned_ips_version`
        no longer matches transitions to `EXPIRED`, and its `PENDING` or
        `BLOCKED` trades transition to `CANCELLED`."

        Design: Difficulty/transitive_cascade/amendment_finalize_cascade_expires_pinned_proposals
        """
        fx = setup_breached_60_40(reprice_to=1500, client_name="Finalize Client")
        proposal = generate_proposal(fx["portfolio"]["id"], "DRIFT_BREACH")
        assert proposal["status"] == "PROPOSED"
        amendment = setup_quorum_amendment(fx["ips"]["id"], proposer="adv-1",
                                           proposed_review_cadence_months=6)
        minute = create_ratified_minute(amendment_refs=[amendment["id"]],
                                        recorder="cm-1", chair="chair-1",
                                        decisions_text="Approved cadence change")
        finalized = finalize_amendment(amendment["id"], minute["id"], chair="chair-1")
        assert finalized["status"] == "APPROVED"
        assert finalized["finalized_by_user_id"] == "chair-1"
        # Hop 2: the proposal's pin went stale with the version bump.
        expired = validate_success(
            api.get_rebalance_proposal(proposal["id"], ADVISOR))
        assert expired["status"] == "EXPIRED"
        # Hop 3: its PENDING trade is CANCELLED.
        cancelled = proposal_trades(proposal["id"], status="CANCELLED")
        assert len(cancelled) == 1

    def test_finalize_cascade_applies_cadence_and_recomputes_due(self, api):
        """PRD §3.8: "A successful finalization applies every non-null proposed
        lever to the IPS, stamps the amendment with `ratified_minute_id`,
        `finalized_by_user_id`, and `finalized_at` — the latter two remaining
        null until the amendment reaches `APPROVED` — and increments the IPS's
        `version` by exactly one."
        PRD §3.8: "When the cadence lever changed, `next_review_due` is
        recomputed by adding the new cadence in calendar months to
        `finalized_at`, with the same end-of-month clamp as activation."

        Design: Difficulty/transitive_cascade/amendment_finalize_cascade_expires_pinned_proposals
        """
        fx = setup_breached_60_40(reprice_to=1500, client_name="Finalize Client")
        ips = fx["ips"]
        version_before = ips["version"]
        amendment = setup_quorum_amendment(ips["id"], proposer="adv-1",
                                           proposed_review_cadence_months=6)
        minute = create_ratified_minute(amendment_refs=[amendment["id"]],
                                        recorder="cm-1", chair="chair-1",
                                        decisions_text="Approved cadence change")
        finalize_amendment(amendment["id"], minute["id"], chair="chair-1")
        updated = validate_success(api.get_ips(ips["id"], ADVISOR))
        assert updated["review_cadence_months"] == 6
        # finalized_at is the default clock 2026-08-01; +6 months.
        assert_iso_instant_equal(updated["next_review_due"], "2027-02-01T00:00:00Z")
        assert updated["version"] == version_before + 1

    def test_occ_stale_ips_version_on_amendment_finalize(self, api):
        """PRD §2.8: "If the IPS's current `version` differs — for instance
        because another amendment was finalized against it first under the
        quorum process — the finalization is rejected with
        `ERR_STALE_IPS_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_stale_ips_version_on_amendment_finalize
        """
        client = create_active_client(full_name="OCC2", risk_tolerance_score=50)
        bench = create_benchmark(name="Bench")
        ips = create_active_ips(client, bench, targets=T_CASH, cadence=12)
        a1 = setup_quorum_amendment(ips["id"], proposer="adv-1",
                                    proposed_objective_text="A1 text")
        a2 = setup_quorum_amendment(ips["id"], proposer="adv-1",
                                    proposed_review_cadence_months=6)
        minute = create_ratified_minute(amendment_refs=[a1["id"], a2["id"]],
                                        recorder="cm-1", chair="chair-1",
                                        decisions_text="Both approved")
        observed = ips_version(ips["id"])
        # Finalize A2 with the fresh version: succeeds.
        ok = validate_success(api.finalize_ips_amendment(
            a2["id"], minute["id"], observed, make_committee_chair_headers("chair-1")))
        assert ok["status"] == "APPROVED"
        assert validate_success(api.get_ips(ips["id"], ADVISOR))[
            "review_cadence_months"] == 6
        # A2's finalize bumped the IPS version; A1's observed version is stale.
        validate_error(api.finalize_ips_amendment(
            a1["id"], minute["id"], observed, make_committee_chair_headers("chair-1")),
            ApiErrorId.ERR_STALE_IPS_VERSION)
        # Re-observing and retrying finalizes A1.
        recovered = validate_success(api.finalize_ips_amendment(
            a1["id"], minute["id"], ips_version(ips["id"]),
            make_committee_chair_headers("chair-1")))
        assert recovered["status"] == "APPROVED"
        assert validate_success(api.get_ips(ips["id"], ADVISOR))[
            "objective_text"] == "A1 text"
