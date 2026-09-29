"""When a request breaks two rules at once, exactly one error is reported."""
from test_helpers import (
    OWNER_REP_USER_ID,
    SECOND_OWNER_REP_USER_ID,
    TEST_USERS,
    ApiErrorId,
    add_package,
    api_client,
    open_ve_review,
    patch_project,
    propose_ve_item,
    read_ledger,
    read_project,
    ride_system_version,
    setup_program_at_schematic,
    setup_program_with_approved_package,
    submit_package,
    validate_error,
    validate_paginated,
    validate_success,
)

OWNER = TEST_USERS["owner_rep_headers"]
SECOND_OWNER = TEST_USERS["second_owner_rep_headers"]
DESIGNER = TEST_USERS["creative_director_headers"]
ENGINEER = TEST_USERS["ride_engineer_headers"]
CONTRACTOR = TEST_USERS["contractor_pm_headers"]


def revise_ride_engineering(ride_system_id: str) -> dict:
    """Revise a parameter of the ride system, which advances its own version."""
    return validate_success(
        api_client.patch_ride_system(
            ride_system_id,
            {
                "expected_ride_system_version": ride_system_version(ride_system_id),
                "show_stops_per_hour": 2.0,
            },
            ENGINEER,
        )
    )


class TestFrozenPostureBeatsBudgetCeiling:
    """Tier 8 masks tier 48 on a change order."""

    def _frozen_programme(self):
        ctx = setup_program_with_approved_package()
        ctx["project"] = patch_project(ctx["project"]["id"], budget_ceiling_cents=3000000000)
        assert ctx["project"]["readiness_posture"] == "FROZEN"
        return ctx

    def test_frozen_programme_reports_frozen_rather_than_ceiling_exceeded(self, api):
        """A frozen programme reports `ERR_PROJECT_FROZEN` in preference to any business rule below tier 8, but *after* the target resource's own state check at tier 7 — so a request to program a scene that is already `PROGRAMMED` on a frozen programme reports `ERR_SCENE_STATE_INVALID`, not `ERR_PROJECT_FROZEN`.

        A change order whose `amount_cents` would push `committed_cost_cents` above
        `budget_ceiling_cents` is refused with `ERR_BUDGET_CEILING_EXCEEDED`, and a
        positive change order is refused with `ERR_POSTURE_RESTRICTED` while the
        programme is `RESTRICTED`.

        The 500000000 change order would carry the committed cost to 3580000000,
        far above the 3000000000 ceiling that froze the programme in the first
        place, yet the freeze is what the response reports and the ledger still
        holds only the original commitment.

        Design: Difficulty/priority_pair_validation_conflict/frozen_posture_beats_budget_ceiling_on_ledger_post
        """
        ctx = self._frozen_programme()

        response = api.create_ledger_entry(
            {
                "project_id": ctx["project"]["id"], "entry_kind": "CHANGE_ORDER",
                "amount_cents": 500000000, "memo": "Add third animatronic figure",
                "expected_project_version": ctx["project"]["version"],
            },
            OWNER,
        )

        validate_error(response, ApiErrorId.ERR_PROJECT_FROZEN.value)
        programme = read_project(ctx["project"]["id"])
        assert programme["committed_cost_cents"] == 3080000000
        assert programme["readiness_posture"] == "FROZEN"
        rows, meta = read_ledger(ctx["project"]["id"])
        assert len(rows) == 1
        assert meta["total_count"] == 1

    def test_the_masked_ceiling_check_reports_once_the_freeze_is_lifted(self, api):
        """A change order whose `amount_cents` would push `committed_cost_cents` above `budget_ceiling_cents` is refused with `ERR_BUDGET_CEILING_EXCEEDED`, and a positive change order is refused with `ERR_POSTURE_RESTRICTED` while the programme is `RESTRICTED`.

        Lower-numbered tiers are evaluated first and mask everything below them.

        With the ceiling restored to 3600000000 the programme is OPEN again, so the
        fiscal rule that the freeze had been masking is the one that answers a
        600000000 change order.

        Design: Difficulty/priority_pair_validation_conflict/frozen_posture_beats_budget_ceiling_on_ledger_post
        """
        ctx = self._frozen_programme()
        unfrozen = patch_project(ctx["project"]["id"], budget_ceiling_cents=3600000000)
        assert unfrozen["readiness_posture"] == "OPEN"

        response = api.create_ledger_entry(
            {
                "project_id": ctx["project"]["id"], "entry_kind": "CHANGE_ORDER",
                "amount_cents": 600000000, "memo": "Add third animatronic figure",
                "expected_project_version": unfrozen["version"],
            },
            OWNER,
        )

        validate_error(response, ApiErrorId.ERR_BUDGET_CEILING_EXCEEDED.value)
        assert read_project(ctx["project"]["id"])["committed_cost_cents"] == 3080000000


class TestSegregationOfDutiesBeatsPinnedReference:
    """Tier 12 masks tier 16 on package approval."""

    def _self_submitted_package_with_moved_ride_system(self):
        ctx = setup_program_at_schematic()
        package = add_package(ctx["project"]["id"], ctx["ride_system"]["id"])
        ctx["package"] = submit_package(package["id"], headers=OWNER)
        revise_ride_engineering(ctx["ride_system"]["id"])
        return ctx

    def test_self_approval_reports_segregation_of_duties_not_a_stale_pin(self, api):
        """And segregation of duties (tier 12) outranks pinned-reference staleness (tier 16) and the budget ceiling (tier 48), so a self-approval attempt on a package whose ride system has moved on and whose cost would breach the ceiling reports `ERR_SEGREGATION_OF_DUTIES`.

        Five conditions must hold, and per §2.10 they are evaluated in this order
        after the posture and state checks: the posture must not be `FROZEN`; the
        approving caller's `X-User-ID` must differ from the recorded
        `submitted_by_user_id`, since a party may not approve its own submission even
        when that party legitimately holds `OwnerRep` — a self-approval is refused
        with `ERR_SEGREGATION_OF_DUTIES`; the `pinned_ride_system_version` must still
        equal the current `version` of the ride system named by `ride_system_id`, so
        that any engineering revision made after submission invalidates the approval
        and yields `ERR_PINNED_REFERENCE_STALE`; and the programme's
        `committed_cost_cents` plus this package's `total_cost_of_work_cents` must not
        exceed `budget_ceiling_cents`, or the approval is refused with
        `ERR_BUDGET_CEILING_EXCEEDED`.

        The owner's rep submitted the package himself and the ride system has since
        been re-engineered, so both the identity rule and the pinned-revision rule
        are broken; nothing is committed and the package stays SUBMITTED.

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_pinned_reference_stale_on_approve
        """
        ctx = self._self_submitted_package_with_moved_ride_system()

        response = api.approve_design_package(
            ctx["package"]["id"],
            {"expected_package_version": ctx["package"]["version"]},
            OWNER,
        )

        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
        package = validate_success(api.get_design_package(ctx["package"]["id"], OWNER))
        assert package["status"] == "SUBMITTED"
        assert package["submitted_by_user_id"] == OWNER_REP_USER_ID
        assert package["approved_by_user_id"] is None
        assert read_project(ctx["project"]["id"])["committed_cost_cents"] == 0

    def test_the_masked_pinned_reference_check_reports_for_a_second_owner(self, api):
        """Five conditions must hold, and per §2.10 they are evaluated in this order after the posture and state checks: the posture must not be `FROZEN`; the approving caller's `X-User-ID` must differ from the recorded `submitted_by_user_id`, since a party may not approve its own submission even when that party legitimately holds `OwnerRep` — a self-approval is refused with `ERR_SEGREGATION_OF_DUTIES`; the `pinned_ride_system_version` must still equal the current `version` of the ride system named by `ride_system_id`, so that any engineering revision made after submission invalidates the approval and yields `ERR_PINNED_REFERENCE_STALE`; and the programme's `committed_cost_cents` plus this package's `total_cost_of_work_cents` must not exceed `budget_ceiling_cents`, or the approval is refused with `ERR_BUDGET_CEILING_EXCEEDED`.

        It records `submitted_by_user_id` as the submitting caller's `X-User-ID`, and
        it captures `pinned_ride_system_version` as the current `version` of the ride
        system named by `ride_system_id` — the revision the drawing set was
        coordinated against.

        A second owner identity satisfies the identity rule, which unmasks the
        stale pin left by the engineering revision.

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_pinned_reference_stale_on_approve
        """
        ctx = self._self_submitted_package_with_moved_ride_system()

        response = api.approve_design_package(
            ctx["package"]["id"],
            {"expected_package_version": ctx["package"]["version"]},
            SECOND_OWNER,
        )

        validate_error(response, ApiErrorId.ERR_PINNED_REFERENCE_STALE.value)
        package = validate_success(api.get_design_package(ctx["package"]["id"], SECOND_OWNER))
        assert package["status"] == "SUBMITTED"
        assert package["submitted_by_user_id"] == OWNER_REP_USER_ID
        assert SECOND_OWNER_REP_USER_ID != OWNER_REP_USER_ID


class TestBallotPartyRoleMismatchBeatsVetoBan:
    """Tier 18 masks tier 41 on a ballot."""

    def _item_under_review(self):
        ctx = setup_program_at_schematic()
        item = propose_ve_item(
            ctx["project"]["id"],
            title="Delete the second projection surface",
            gross_saving_cents=70000021,
            rework_loss_pct=75,
            implementation_cost_cents=1000000,
            capacity_impact_guests_per_hour=0,
            scope_impact_delta_cents=-69000021,
        )
        ctx["ve_item"] = open_ve_review(item["id"])
        return ctx

    def test_declaring_another_party_reports_the_role_mismatch(self, api):
        """The declared `party_role` must equal the caller's `X-User-Role`; a mismatch is refused with `ERR_BALLOT_PARTY_ROLE_MISMATCH`.

        The veto is asymmetric by design: only `OwnerRep` and `ContractorPM` may
        cast `VETO`, while the designer party — `CreativeDirector` — may `APPROVE` or
        `ABSTAIN` but never veto, and an attempt is refused with
        `ERR_VETO_NOT_PERMITTED`.

        The contractor casting a designer's veto breaks both rules at once, and the
        role mismatch is the one reported: no ballot is recorded, the tally stays at
        zero and no veto is flagged.

        Design: Difficulty/priority_pair_validation_conflict/ballot_party_role_mismatch_beats_veto_not_permitted
        """
        ctx = self._item_under_review()

        response = api.create_ve_ballot(
            {
                "value_engineering_item_id": ctx["ve_item"]["id"],
                "party_role": "CreativeDirector", "decision": "VETO",
                "comment": "Contractor casting on the designer's behalf",
            },
            CONTRACTOR,
        )

        validate_error(response, ApiErrorId.ERR_BALLOT_PARTY_ROLE_MISMATCH.value)
        item = validate_success(api.get_value_engineering_item(ctx["ve_item"]["id"], OWNER))
        assert item["status"] == "UNDER_REVIEW"
        assert item["ballot_count"] == 0
        assert item["veto_present"] is False
        ballots, meta = validate_paginated(
            api.list_value_engineering_ballots(ctx["ve_item"]["id"], OWNER)
        )
        assert ballots == []
        assert meta["total_count"] == 0

    def test_the_masked_veto_ban_reports_once_the_declared_party_matches(self, api):
        """The veto is asymmetric by design: only `OwnerRep` and `ContractorPM` may cast `VETO`, while the designer party — `CreativeDirector` — may `APPROVE` or `ABSTAIN` but never veto, and an attempt is refused with `ERR_VETO_NOT_PERMITTED`.

        When a request violates more than one rule, exactly one error is reported,
        and which one is fully determined by the following priority order.

        With the designer casting a designer's ballot the role check passes, so the
        veto ban below it is what answers.

        Design: Difficulty/priority_pair_validation_conflict/ballot_party_role_mismatch_beats_veto_not_permitted
        """
        ctx = self._item_under_review()

        response = api.create_ve_ballot(
            {
                "value_engineering_item_id": ctx["ve_item"]["id"],
                "party_role": "CreativeDirector", "decision": "VETO",
            },
            DESIGNER,
        )

        validate_error(response, ApiErrorId.ERR_VETO_NOT_PERMITTED.value)
        item = validate_success(api.get_value_engineering_item(ctx["ve_item"]["id"], OWNER))
        assert item["status"] == "UNDER_REVIEW"
        assert item["ballot_count"] == 0
        assert item["veto_present"] is False
