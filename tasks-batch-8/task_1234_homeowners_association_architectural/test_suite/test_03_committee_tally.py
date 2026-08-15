"""Committee review: quorum, tally variants, abstention handling, recasts, revision loop."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    TEST_USERS, ApiErrorId,
    create_association, register_owner, register_property, register_committee,
    create_complete_draft, create_under_review_application, submit_application,
    start_review, cast_ballots, decide, read_application, get_single_permit,
    set_logical_clock, setup_review_ready,
    make_homeowner_headers, make_committee_member_headers,
)

MANAGER = TEST_USERS["manager_headers"]


def test_quorum_not_met_then_met(api):
    """Decide with fewer ballots than quorum_min fails; the third ballot unblocks it.

    PRD §3.4: "Quorum requires the total ballots cast — A plus D plus X — to be at
    least the association's `quorum_min`; otherwise the decision is rejected with
    `ERR_QUORUM_NOT_MET`."

    Design: Corner/errors/err_quorum_not_met_trigger
    """
    bundle = setup_review_ready(ballots=("APPROVE", "APPROVE"), num_committee=3)
    app_id = bundle["application"]["id"]

    res = api.decide_application(app_id, {"conditions": []}, MANAGER)
    validate_error(res, ApiErrorId.ERR_QUORUM_NOT_MET)
    assert read_application(app_id)["status"] == "UNDER_REVIEW"

    cast_ballots(app_id, [bundle["committee"][2]], ("APPROVE",))
    decided = decide(app_id, conditions=[])
    assert decided["status"] == "APPROVED_WITH_CONDITIONS"


def test_abstain_counts_for_quorum_but_not_ratio(api):
    """Ballots A,A,D,ABSTAIN meet quorum of 3 and approve at exactly two-thirds.

    PRD §3.4: "Quorum requires the total ballots cast — A plus D plus X — to be at
    least the association's `quorum_min`"
    PRD §3.4: "When `supermajority_required` is true, approval requires at least one
    non-abstention ballot and three times A to be at least twice the sum of A plus D
    — abstentions are excluded from the ratio, and the exact two-thirds boundary
    approves, so two approvals against one denial succeed."

    Design: Corner/calculations/tally_abstain_excluded_from_ratio
    """
    bundle = setup_review_ready(ballots=("APPROVE", "APPROVE", "DENY", "ABSTAIN"),
                                num_committee=4)
    decided = decide(bundle["application"]["id"], conditions=["dark shingles only"])
    # 4 ballots >= quorum 3; ratio over non-abstain: 3*A=6 >= 2*(A+D)=6 -> approve.
    assert decided["status"] == "APPROVED_WITH_CONDITIONS"
    assert decided["decision_outcome"] == "APPROVED"


class TestTwoThirdsBoundary:
    """The approve ratio A/(A+D) approves AT exactly 2/3 and denies below it."""

    def test_ratio_exactly_two_thirds_approves(self, api):
        """A=2, D=1 lands exactly on the inclusive two-thirds boundary.

        PRD §3.4: "the exact two-thirds boundary approves, so two approvals against
        one denial succeed."

        Design: Difficulty/boundary_precision_check/quorum_ratio_exactly_two_thirds_approves
        """
        bundle = setup_review_ready(ballots=("APPROVE", "APPROVE", "DENY"))
        decided = decide(bundle["application"]["id"], conditions=["stain natural"])
        assert decided["status"] == "APPROVED_WITH_CONDITIONS"
        assert decided["decision_outcome"] == "APPROVED"

    def test_ratio_one_third_denies(self, api):
        """A=1, D=2 falls below the boundary and denies, recording the reason.

        PRD §3.4: "three times A to be at least twice the sum of A plus D"
        PRD §3.4: "A denying decision moves the application from `UNDER_REVIEW` to
        `DENIED`: `decision_outcome` becomes `DENIED`, `decision_reason` is
        populated from the payload's `denial_reason`, `decided_at` is stamped, and
        `version` increments."

        Design: Difficulty/boundary_precision_check/quorum_ratio_exactly_two_thirds_approves
        """
        bundle = setup_review_ready(
            ballots=("APPROVE", "DENY", "DENY"),
            app_overrides={"project_type": "PAINT", "guideline_section": "SEC-3.1",
                           "description": "door repaint",
                           "requested_window_start": "2026-08-01",
                           "requested_window_end": "2026-08-20"})
        decided = decide(bundle["application"]["id"], denial_reason="color mismatch")
        assert decided["status"] == "DENIED"
        assert decided["decision_outcome"] == "DENIED"
        assert decided["decision_reason"] == "color mismatch"


class TestSupermajorityFlagFlipsOutcome:
    """Identical ballots A=3, D=2 (quorum 3) diverge purely on supermajority_required."""

    def _build_five_ballot_application(self, supermajority_required: bool,
                                       name: str) -> dict:
        assoc = create_association(name=name,
                                   supermajority_required=supermajority_required)
        owner = register_owner(assoc["id"], full_name=f"Ap {name}",
                               email=f"ap.{name}@x.com")
        committee = register_committee(assoc["id"], count=5, prefix=f"Cm{name}")
        prop = register_property(assoc["id"], owner["id"], lot_number=f"{name}-1",
                                 address=f"1 {name} Ct")
        set_logical_clock("2026-05-01T09:00:00Z")
        app = create_under_review_application(
            prop["id"], owner, committee,
            ballots=("APPROVE", "APPROVE", "APPROVE", "DENY", "DENY"),
            project_type="ROOF", guideline_section="SEC-7.1",
            description="roof replacement")
        return {"association": assoc, "applicant": owner, "committee": committee,
                "property": prop, "application": app}

    def test_supermajority_true_denies_three_to_two(self, api):
        """Under the supermajority variant 3/5 falls short of two-thirds and denies.

        PRD §3.4: "When `supermajority_required` is true, approval requires at least
        one non-abstention ballot and three times A to be at least twice the sum of A
        plus D"
        PRD §3.4: "The variants genuinely diverge: three approvals against two
        denials approve under the plurality variant but deny under the supermajority
        variant, because three-fifths falls short of two-thirds."

        Design: Difficulty/combinatorial_formula/quorum_tally_supermajority_flag_flips_outcome
        """
        bundle = self._build_five_ballot_application(True, "Sup")
        decided = decide(bundle["application"]["id"],
                         conditions=["match existing shingle color"],
                         denial_reason="insufficient support")
        # 3*A = 9 < 2*(A+D) = 10 -> denied
        assert decided["status"] == "DENIED"
        assert decided["decision_outcome"] == "DENIED"
        permits = validate_paginated(api.list_application_permits(
            bundle["application"]["id"], MANAGER))[0]
        assert permits == [], "a denied application must not yield a permit"

    def test_supermajority_false_approves_three_to_two(self, api):
        """Under the plurality variant A > D approves and the permit cascade fires.

        PRD §3.4: "When `supermajority_required` is false, approval requires A to
        strictly exceed D, and a tie denies."
        PRD §3.4: "The approval then cascades: a construction permit is created in
        `ACTIVE` status with its `window_start` and `window_end` copied from the
        application's requested window"

        Design: Difficulty/combinatorial_formula/quorum_tally_supermajority_flag_flips_outcome
        """
        bundle = self._build_five_ballot_application(False, "Plu")
        decided = decide(bundle["application"]["id"],
                         conditions=["match existing shingle color"],
                         denial_reason="insufficient support")
        # A=3 > D=2 -> approved
        assert decided["status"] == "APPROVED_WITH_CONDITIONS"
        assert decided["decision_outcome"] == "APPROVED"
        permit = get_single_permit(bundle["application"]["id"])
        assert permit["status"] == "ACTIVE"


class TestVoteRecastConservation:
    """A recast replaces the voter's existing ballot row; it never adds a row."""

    def test_recast_replaces_ballot_and_increments_recast_count(self, api):
        """PRD §3.4: "There is exactly one vote row per distinct voter on an
        application: a member who votes again recasts, replacing the existing ballot
        and incrementing `recast_count` — never adding a second row — so the count
        of `APPROVE` plus `DENY` plus `ABSTAIN` ballots always equals the number of
        distinct voters."

        Design: Difficulty/compensating_invariant/vote_recast_conserves_ballot_count
        """
        bundle = setup_review_ready(ballots=("APPROVE", "APPROVE", "DENY"))
        app_id = bundle["application"]["id"]
        voter_b = bundle["committee"][0]
        first_votes = validate_paginated(api.list_votes(app_id, MANAGER))[0]
        vote_b = next(v for v in first_votes if v["voter_owner_id"] == voter_b["id"])

        recast = validate_success(api.cast_vote(
            app_id, {"ballot": "DENY"},
            make_committee_member_headers(voter_b["id"])), 201)
        assert recast["id"] == vote_b["id"], "recast must replace the same vote row"
        assert recast["ballot"] == "DENY"
        assert recast["recast_count"] == 1

        votes_after, meta = validate_paginated(api.list_votes(app_id, MANAGER))
        assert len(votes_after) == 3, f"recast must not add a row, got {len(votes_after)}"
        total = sum(1 for v in votes_after if v["ballot"] in ("APPROVE", "DENY", "ABSTAIN"))
        assert total == 3, "ballot count must equal the distinct voter count"

    def test_tally_uses_recast_ballot(self, api):
        """After voter b recasts APPROVE->DENY the tally reads A=1, D=2 and denies.

        PRD §3.4: "a member who votes again recasts, replacing the existing ballot"
        PRD §3.4: "When `supermajority_required` is true, approval requires at least
        one non-abstention ballot and three times A to be at least twice the sum of A
        plus D"

        Design: Difficulty/compensating_invariant/vote_recast_conserves_ballot_count
        """
        bundle = setup_review_ready(ballots=("APPROVE", "APPROVE", "DENY"))
        app_id = bundle["application"]["id"]
        voter_b = bundle["committee"][0]
        validate_success(api.cast_vote(app_id, {"ballot": "DENY"},
                                       make_committee_member_headers(voter_b["id"])),
                         201)
        decided = decide(app_id, denial_reason="lost support")
        # A=1 (c), D=2 (b recast, e): 3*1 = 3 < 2*3 = 6 -> denied
        assert decided["status"] == "DENIED"
        assert decided["decision_outcome"] == "DENIED"


class TestRevisionLoop:
    """The UNDER_REVIEW <-> REVISION_REQUESTED cycle repeats and hold days accumulate."""

    def _setup_loop(self, api):
        assoc = create_association(name="Loop HOA")
        owner = register_owner(assoc["id"], full_name="Ann A", email="ann.a@x.com")
        member = register_owner(assoc["id"], full_name="Cid B", email="cid.b@x.com")
        prop = register_property(assoc["id"], owner["id"], lot_number="L-1",
                                 address="1 Loop Ln")
        set_logical_clock("2026-05-01T09:00:00Z")
        app = create_complete_draft(prop["id"], owner, project_type="PAINT",
                                    guideline_section="SEC-3.1",
                                    description="repaint trim")
        submit_application(app["id"], owner["id"])
        start_review(app["id"])
        return assoc, owner, member, app

    def test_first_cycle_accumulates_three_hold_days(self, api):
        """Hold grows by the whole days between revision request and resubmission.

        PRD §3.4: "On resubmission, `applicant_hold_days` grows by the whole days
        after the revision request's date up to and including the resubmission date"
        PRD §3.4: "The applicant — and only the applicant, with `owner_id` equal to
        `X-User-ID` — resubmits, cycling the application back from
        `REVISION_REQUESTED` to `UNDER_REVIEW`."

        Design: Difficulty/non_linear_state_machine/application_revision_loop_cycles
        """
        _assoc, owner, member, app = self._setup_loop(api)
        res = api.request_revision(app["id"], {"revision_notes": "provide color board"},
                                   make_committee_member_headers(member["id"]))
        validate_success(res, 200)
        set_logical_clock("2026-05-04T09:00:00Z")
        resub = validate_success(api.resubmit_application(
            app["id"], make_homeowner_headers(owner["id"])), 200)
        assert resub["status"] == "UNDER_REVIEW"
        # whole days in (2026-05-01, 2026-05-04] == 3
        assert resub["applicant_hold_days"] == 3

    def test_second_cycle_accumulates_five_hold_days_and_versions(self, api):
        """The loop may repeat; hold time accumulates and version increments per step.

        PRD §3.4: "This revision loop may repeat without bound for as long as the
        statutory clock allows, with hold time accumulating on every pass."
        PRD §3.4: "the application moves from `UNDER_REVIEW` to `REVISION_REQUESTED`,
        the applicant-hold window opens, and `version` increments"
        PRD §3.4: "On resubmission, `applicant_hold_days` grows by the whole days
        after the revision request's date up to and including the resubmission date,
        and `version` increments again."

        Design: Difficulty/non_linear_state_machine/application_revision_loop_cycles
        """
        _assoc, owner, member, app = self._setup_loop(api)
        member_headers = make_committee_member_headers(member["id"])
        owner_headers = make_homeowner_headers(owner["id"])
        v_create = app["version"]

        validate_success(api.request_revision(
            app["id"], {"revision_notes": "provide color board"}, member_headers), 200)
        set_logical_clock("2026-05-04T09:00:00Z")
        resub1 = validate_success(api.resubmit_application(app["id"], owner_headers), 200)
        assert resub1["applicant_hold_days"] == 3

        validate_success(api.request_revision(
            app["id"], {"revision_notes": "revise setback detail"}, member_headers), 200)
        set_logical_clock("2026-05-06T09:00:00Z")
        resub2 = validate_success(api.resubmit_application(app["id"], owner_headers), 200)
        assert resub2["status"] == "UNDER_REVIEW"
        # 3 + whole days in (2026-05-04, 2026-05-06] == 3 + 2 == 5
        assert resub2["applicant_hold_days"] == 5
        # create + 6 mutations (submit, start-review, req-rev, resubmit, req-rev, resubmit)
        assert resub2["version"] == v_create + 6, (
            f"each mutation increments version by one: {v_create} + 6 != "
            f"{resub2['version']}")
