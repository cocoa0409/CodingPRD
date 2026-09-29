"""One write, several dependent links: findings, adoptions and approvals."""
from test_helpers import (
    TEST_USERS,
    add_package,
    approve_package,
    assert_scene_held_from,
    assert_scene_not_held,
    cast_ballot,
    open_ve_review,
    patch_project,
    propose_ve_item,
    read_ledger,
    read_project,
    setup_program_with_approved_package,
    setup_program_with_open_finding,
    submit_package,
    validate_success,
)

OWNER = TEST_USERS["owner_rep_headers"]
DESIGNER = TEST_USERS["creative_director_headers"]
REVIEWER = TEST_USERS["third_party_reviewer_headers"]

CRITICAL_DESCRIPTION = "Restraint proximity sensor lacks redundant channel on vehicle four"


class TestCriticalFindingCascade:
    """A single non-conformance notice freezes the whole programme."""

    def _programme_with_critical_finding(self):
        return setup_program_with_open_finding(
            severity="CRITICAL",
            remediation_cost_estimate_cents=45000000,
            description=CRITICAL_DESCRIPTION,
        )

    def test_one_critical_finding_walks_review_counter_posture_and_scenes(self, api):
        """The *first* finding raised on a review moves that review from `IN_REVIEW` to `FINDINGS_ISSUED` and increments its `open_finding_count` by one, advancing the review's `version`; each subsequent finding increments `open_finding_count` again.

        The programme's `readiness_posture` is then recomputed from those counters,
        which is how a single critical finding freezes an entire programme and
        cascades its scenes to `HELD`.

        Every scene of the programme whose `status` is `SEQUENCED`, `PROGRAMMED` or
        `VALIDATED` moves to `HELD`; its `held_from_status` is set to whichever of
        those three values it held immediately before the freeze; and its
        `hold_reason` is set to `SAFETY_FREEZE` when `open_critical_finding_count`
        is greater than zero, and to `BUDGET_FREEZE` otherwise.

        Design: Difficulty/transitive_cascade/critical_finding_cascade_freezes_program_and_holds_sequenced_scenes
        """
        ctx = self._programme_with_critical_finding()

        finding = validate_success(api.get_safety_finding(ctx["finding"]["id"], REVIEWER))
        review = validate_success(api.get_safety_review(ctx["review"]["id"], REVIEWER))
        programme = read_project(ctx["project"]["id"])
        sc1 = validate_success(api.get_show_scene(ctx["sc1"]["id"], DESIGNER))
        sc2 = validate_success(api.get_show_scene(ctx["sc2"]["id"], DESIGNER))

        assert finding["status"] == "OPEN"
        assert review["status"] == "FINDINGS_ISSUED"
        assert review["open_finding_count"] == 1
        assert programme["open_critical_finding_count"] == 1
        assert programme["readiness_posture"] == "FROZEN"
        assert_scene_held_from(sc1, held_from_status="SEQUENCED", hold_reason="SAFETY_FREEZE")
        assert_scene_held_from(sc2, held_from_status="SEQUENCED", hold_reason="SAFETY_FREEZE")

    def test_the_critical_finding_lifts_the_forecast_without_moving_committed_cost(self):
        """`open_critical_finding_count` is the number of findings with `severity` `CRITICAL` whose `status` is `OPEN` or `RESOLVED`, counted across every review of every design package of the programme; `open_major_finding_count` is the same count for `severity` `MAJOR`.

        Open safety remediation is the sum of `remediation_cost_estimate_cents` over
        every finding whose review belongs to a design package of this programme and
        whose `status` is `OPEN` or `RESOLVED` — `CLOSED` and `WAIVED` findings are
        excluded — and this sum is *added*.

        The critical notice raises only the critical counter, leaves the committed
        3080000000 exactly where the approval left it, and carries the forecast to
        3125000000 on its 45000000 remediation estimate.

        Design: Difficulty/transitive_cascade/critical_finding_cascade_freezes_program_and_holds_sequenced_scenes
        """
        ctx = self._programme_with_critical_finding()

        programme = read_project(ctx["project"]["id"])

        assert programme["open_critical_finding_count"] == 1
        assert programme["open_major_finding_count"] == 0
        assert programme["committed_cost_cents"] == 3080000000
        assert programme["forecast_cost_cents"] == 3125000000


class TestValueEngineeringAdoptionCascade:
    """The contractor's saving is the route out of a budget freeze."""

    def _frozen_programme_with_two_ballots(self):
        ctx = setup_program_with_approved_package()
        item = propose_ve_item(ctx["project"]["id"])
        ctx["ve_item"] = open_ve_review(item["id"])
        ctx["project"] = patch_project(ctx["project"]["id"], budget_ceiling_cents=3000000000)
        assert ctx["project"]["readiness_posture"] == "FROZEN"
        cast_ballot(item["id"], "OwnerRep", "APPROVE", comment="Take the saving")
        cast_ballot(item["id"], "ContractorPM", "APPROVE")
        return ctx

    def test_third_ballot_adopts_the_item_and_mints_the_saving_entry(self, api):
        """The third ballot resolves an unvetoed item: if `ballot_count` reaches 3 with no veto present and at least two of the three ballots carrying `APPROVE`, the item moves to the terminal `ADOPTED`; if the third ballot leaves fewer than two `APPROVE` decisions, the item moves to `REJECTED` instead.

        The programme's `committed_cost_cents` and `forecast_cost_cents` are then
        recomputed and its `readiness_posture` re-derived, which may leave `FROZEN`
        and release every `HELD` scene to its `held_from_status` — value engineering
        is the contractor's route out of a budget freeze.

        The abstention is the third ballot, so the item is adopted on two approvals,
        mints a saving entry of -83500005 as the second ledger ordinal, and carries
        the committed cost to 2996499995 — back under the 3000000000 ceiling but
        still above the 2700000000 restricted-utilisation threshold.

        Design: Difficulty/transitive_cascade/ve_adoption_cascade_lifts_budget_freeze_and_releases_held_scenes
        """
        ctx = self._frozen_programme_with_two_ballots()

        cast_ballot(ctx["ve_item"]["id"], "CreativeDirector", "ABSTAIN")

        item = validate_success(api.get_value_engineering_item(ctx["ve_item"]["id"], OWNER))
        savings, _meta = read_ledger(ctx["project"]["id"], params={"entry_kind": "VE_SAVING"})
        programme = read_project(ctx["project"]["id"])

        assert item["status"] == "ADOPTED"
        assert item["ballot_count"] == 3
        assert item["veto_present"] is False
        assert savings[0]["amount_cents"] == -83500005
        assert savings[0]["sequence_no"] == 2
        assert programme["committed_cost_cents"] == 2996499995
        assert programme["readiness_posture"] == "RESTRICTED"

    def test_leaving_frozen_for_restricted_releases_both_held_scenes(self, api):
        """Leaving `FROZEN` reverses the cascade exactly.

        Whether the posture settles on `RESTRICTED` (because a major finding is
        still open or the committed cost is still above the restricted-utilisation
        threshold, with no critical finding open and the committed cost no longer
        above the ceiling) or on `OPEN` (because no critical and no major finding
        remains open and the committed cost is at or below the
        restricted-utilisation threshold), every `HELD` scene of the programme
        returns to precisely the status recorded in its `held_from_status`, and both
        `held_from_status` and `hold_reason` are cleared to null.

        Both scenes were held out of SEQUENCED by the budget freeze, so the
        adoption that settles the posture on RESTRICTED returns both of them to
        SEQUENCED with their hold fields cleared.

        Design: Difficulty/transitive_cascade/ve_adoption_cascade_lifts_budget_freeze_and_releases_held_scenes
        """
        ctx = self._frozen_programme_with_two_ballots()
        held = validate_success(api.get_show_scene(ctx["sc1"]["id"], DESIGNER))
        assert_scene_held_from(held, held_from_status="SEQUENCED", hold_reason="BUDGET_FREEZE")

        cast_ballot(ctx["ve_item"]["id"], "CreativeDirector", "ABSTAIN")

        sc1 = validate_success(api.get_show_scene(ctx["sc1"]["id"], DESIGNER))
        sc2 = validate_success(api.get_show_scene(ctx["sc2"]["id"], DESIGNER))

        assert sc1["status"] == "SEQUENCED"
        assert_scene_not_held(sc1)
        assert sc2["status"] == "SEQUENCED"
        assert_scene_not_held(sc2)


class TestPackageApprovalSupersession:
    """A programme carries at most one approved package, but every commitment stays."""

    def _programme_with_two_packages(self):
        ctx = setup_program_with_approved_package(
            package_overrides={
                "package_label": "Show Set Package A",
                "discipline_scope": "SHOW_SET",
                "base_construction_cost_cents": 400000000,
            }
        )
        package_b = add_package(
            ctx["project"]["id"], ctx["ride_system"]["id"],
            package_label="Show Set Package B", discipline_scope="SHOW_SET",
            base_construction_cost_cents=500000000,
        )
        ctx["package_b"] = submit_package(package_b["id"])
        return ctx

    def test_approving_the_second_package_supersedes_the_first(self, api):
        """Any *other* design package of the same programme that was `APPROVED` moves to the terminal `SUPERSEDED`, with its own `version` incremented by one — a programme therefore carries at most one approved package at a time.

        Package A prices a base of 400000000 for a total of 515200000 and package B
        prices a base of 500000000 for a total of 644000000; approving B moves A to
        SUPERSEDED without touching either total.

        Design: Difficulty/transitive_cascade/package_approval_supersedes_prior_package_and_stacks_commitment
        """
        ctx = self._programme_with_two_packages()

        approved_b = approve_package(ctx["package_b"]["id"])
        package_a = validate_success(api.get_design_package(ctx["package"]["id"], OWNER))

        assert approved_b["status"] == "APPROVED"
        assert approved_b["total_cost_of_work_cents"] == 644000000
        assert package_a["status"] == "SUPERSEDED"
        assert package_a["total_cost_of_work_cents"] == 515200000

    def test_the_superseded_commitment_still_stacks_in_the_committed_cost(self):
        """No status filter is applied — an entry whose `reversed` flag is true still contributes its original amount, and its `REVERSAL` twin contributes the negation — and no rounding occurs, because every input is already a whole number of cents.

        A ledger entry is minted with `entry_kind` `COMMITMENT`, an `amount_cents`
        equal to this package's `total_cost_of_work_cents`, a `sequence_no` one
        greater than the programme's `ledger_sequence_high_water` (which then
        advances), and a `memo` of the form `COMMITMENT for design package `
        followed by the package's `package_label`.

        Supersession is not a reversal: both commitments remain in the replay, so
        the committed cost is 515200000 plus 644000000, and 1159200000 still sits
        below the restricted-utilisation threshold of a 3600000000 ceiling.

        Design: Difficulty/transitive_cascade/package_approval_supersedes_prior_package_and_stacks_commitment
        """
        ctx = self._programme_with_two_packages()

        approve_package(ctx["package_b"]["id"])

        commitments, _meta = read_ledger(ctx["project"]["id"], params={"entry_kind": "COMMITMENT"})
        programme = read_project(ctx["project"]["id"])

        assert commitments[0]["amount_cents"] == 515200000
        assert commitments[1]["amount_cents"] == 644000000
        assert commitments[1]["sequence_no"] == 2
        assert programme["committed_cost_cents"] == 1159200000
        assert programme["readiness_posture"] == "OPEN"
