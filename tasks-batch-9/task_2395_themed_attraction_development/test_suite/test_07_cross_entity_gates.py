"""A write on one row is gated by the state of a different row."""
from test_helpers import (
    TEST_USERS,
    add_package,
    add_prologue_and_chase,
    advance_to,
    approve_package,
    clear_review,
    mark_engineered,
    open_project,
    open_review,
    open_ve_review,
    place_cue,
    propose_ve_item,
    read_ledger,
    read_project,
    register_ride_system,
    select_ride,
    sequence_scene,
    setup_program_at_schematic,
    submit_package,
    validate_error,
    validate_paginated,
    validate_success,
    verify_cue,
    ApiErrorId,
)

OWNER = TEST_USERS["owner_rep_headers"]
DESIGNER = TEST_USERS["creative_director_headers"]
ENGINEER = TEST_USERS["ride_engineer_headers"]
PROGRAMMER = TEST_USERS["show_programmer_headers"]
REVIEWER = TEST_USERS["third_party_reviewer_headers"]

ALTERNATE_RIDE_SYSTEM = {
    "vendor_name": "Intamin Rides", "system_type": "OMNIMOVER",
    "vehicle_count": 4, "riders_per_vehicle": 6, "block_zone_count": 5,
    "cycle_time_seconds": 300, "availability_pct": 95,
    "load_efficiency_pct": 85, "show_stops_per_hour": 1.0,
}
VE_ITEM = {
    "title": "Delete the second projection surface",
    "gross_saving_cents": 70000021,
    "rework_loss_pct": 75,
    "implementation_cost_cents": 1000000,
    "capacity_impact_guests_per_hour": 0,
    "scope_impact_delta_cents": -69000021,
}


class TestCommissionNeedsAReviewOnItsOwnRideSystem:
    """A cleared review on the wrong package does not clear this ride."""

    def _installation_with_a_review_on_the_other_system(self):
        project = open_project()
        sc1, sc2 = add_prologue_and_chase(project["id"])
        main = register_ride_system(project["id"])
        alternate = register_ride_system(project["id"], **ALTERNATE_RIDE_SYSTEM)
        advance_to(project["id"], "CONCEPT")
        select_ride(main["id"], project["id"])
        sequence_scene(sc1["id"], 1)
        sequence_scene(sc2["id"], 2, follows_scene_id=sc1["id"])
        advance_to(project["id"], "SCHEMATIC")
        mark_engineered(main["id"])
        alternate_package = add_package(
            project["id"], alternate["id"], package_label="Alternate Vehicle Study",
            discipline_scope="SHOW_SET", base_construction_cost_cents=400000000,
        )
        submit_package(alternate_package["id"])
        advance_to(project["id"], "DESIGN_DEVELOPMENT")
        alternate_package = approve_package(alternate_package["id"])
        alternate_review = clear_review(open_review(alternate_package["id"])["id"])
        advance_to(project["id"], "PRODUCTION")
        advance_to(project["id"], "INSTALLATION")
        return {"project": project, "main": main, "alternate": alternate,
                "alternate_package": alternate_package,
                "alternate_review": alternate_review}

    def _clear_a_review_on_the_selected_system(self, ctx):
        package = add_package(
            ctx["project"]["id"], ctx["main"]["id"],
            package_label="Ride and Controls Release",
            discipline_scope="RIDE_AND_CONTROLS", base_construction_cost_cents=400000000,
        )
        submit_package(package["id"])
        package = approve_package(package["id"])
        review = clear_review(open_review(package["id"])["id"])
        return package, review

    def test_commission_is_refused_while_the_clearance_names_another_system(self, api):
        """It requires the posture not to be `FROZEN`, the programme to be in `INSTALLATION`, the programme's `open_critical_finding_count` to be exactly zero, and at least one `CLEARED` safety review to exist whose design package is `APPROVED` *and* whose `ride_system_id` is this very system; failing either of the last two conditions yields `ERR_SAFETY_REVIEW_NOT_CLEARED`.

        Commissioning advances `ENGINEERED` to `COMMISSIONED`, the terminal state, and
        is the point at which third-party safety work becomes binding on the ride.

        The programme holds a genuinely CLEARED review — it is what let it reach
        INSTALLATION — but that review covers the package citing the alternate
        vehicle study, so the selected system stays ENGINEERED.

        Design: Difficulty/cross_entity_state_dependency/commission_blocked_until_a_cleared_review_covers_the_commissioned_ride_system
        """
        ctx = self._installation_with_a_review_on_the_other_system()

        response = api.commission_ride_system(ctx["main"]["id"], {}, ENGINEER)

        validate_error(response, ApiErrorId.ERR_SAFETY_REVIEW_NOT_CLEARED.value)
        main = validate_success(api.get_ride_system(ctx["main"]["id"], ENGINEER))
        assert main["status"] == "ENGINEERED"
        assert ctx["alternate_review"]["status"] == "CLEARED"
        assert ctx["alternate_package"]["status"] == "APPROVED"
        assert ctx["alternate_package"]["total_cost_of_work_cents"] == 515200000
        assert read_project(ctx["project"]["id"])["design_phase"] == "INSTALLATION"

    def test_a_clearance_naming_the_selected_system_lets_the_same_call_through(self, api):
        """Any *other* design package of the same programme that was `APPROVED` moves to the terminal `SUPERSEDED`, with its own `version` incremented by one — a programme therefore carries at most one approved package at a time.

        `selected_ride_system_id` is a computed mirror, never a client-writable
        reference: it holds the `id` of the programme's ride system whose `status` is
        `SELECTED`, `ENGINEERED` or `COMMISSIONED`, and is null while no system has
        been selected.

        A second package citing the selected system, approved and then cleared,
        satisfies the linkage the first review could not: the ride commissions, the
        alternate package is superseded without losing its commitment, and both
        515200000 commitments stand in the ledger.

        Design: Difficulty/cross_entity_state_dependency/commission_blocked_until_a_cleared_review_covers_the_commissioned_ride_system
        """
        ctx = self._installation_with_a_review_on_the_other_system()
        validate_error(
            api.commission_ride_system(ctx["main"]["id"], {}, ENGINEER),
            ApiErrorId.ERR_SAFETY_REVIEW_NOT_CLEARED.value,
        )

        main_package, main_review = self._clear_a_review_on_the_selected_system(ctx)
        commissioned = validate_success(
            api.commission_ride_system(ctx["main"]["id"], {}, ENGINEER))

        alternate_package = validate_success(
            api.get_design_package(ctx["alternate_package"]["id"], OWNER))
        programme = read_project(ctx["project"]["id"])
        commitments, _meta = read_ledger(ctx["project"]["id"],
                                        params={"entry_kind": "COMMITMENT"})

        assert main_review["status"] == "CLEARED"
        assert main_package["total_cost_of_work_cents"] == 515200000
        assert commissioned["status"] == "COMMISSIONED"
        assert alternate_package["status"] == "SUPERSEDED"
        assert programme["committed_cost_cents"] == 1030400000
        assert programme["readiness_posture"] == "OPEN"
        assert programme["design_phase"] == "INSTALLATION"
        assert len(commitments) == 2


class TestSceneProgrammingNeedsEveryOwnedCueVerified:
    """One unverified cue blocks the scene, and an empty timeline blocks it too."""

    def _scene_pair_with_one_outstanding_cue(self):
        project = open_project()
        sc_a, sc_b = add_prologue_and_chase(project["id"])
        ride = register_ride_system(project["id"])
        advance_to(project["id"], "CONCEPT")
        select_ride(ride["id"], project["id"])
        sequence_scene(sc_a["id"], 1)
        sequence_scene(sc_b["id"], 2, follows_scene_id=sc_a["id"])
        lighting = place_cue(sc_a["id"], cue_label="Prologue Wash",
                             discipline_channel="LIGHTING", offset_ms=0, duration_ms=2000)
        audio = place_cue(sc_a["id"], cue_label="Prologue Stinger",
                          discipline_channel="AUDIO", offset_ms=0, duration_ms=3000)
        verify_cue(lighting["id"])
        return {"project": project, "sc_a": sc_a, "sc_b": sc_b,
                "lighting_cue": lighting, "audio_cue": audio}

    def test_a_scene_holding_one_planned_cue_is_refused(self, api):
        """It requires the posture not to be `FROZEN` and it requires the scene to own at least one cue with *every* cue of the scene already `VERIFIED`; a scene with no cues at all, or with any cue still `PLANNED`, is refused with `ERR_CUES_NOT_VERIFIED`.

        A new scene lands in `DRAFT` with `scene_quality_score`,
        `validating_rehearsal_run_id`, `held_from_status`, `hold_reason` and the four
        discipline scores all null.

        The prologue owns a verified lighting wash and a still-planned audio
        stinger, so its scores are refused and none of them is written.

        Design: Difficulty/cross_entity_state_dependency/scene_program_requires_every_owned_cue_verified_and_at_least_one_cue
        """
        ctx = self._scene_pair_with_one_outstanding_cue()

        response = api.program_show_scene(
            ctx["sc_a"]["id"],
            {"lighting_score": 92, "audio_score": 88,
             "animation_score": 85, "effects_score": 88},
            PROGRAMMER,
        )

        validate_error(response, ApiErrorId.ERR_CUES_NOT_VERIFIED.value)
        scene = validate_success(api.get_show_scene(ctx["sc_a"]["id"], DESIGNER))
        assert scene["status"] == "SEQUENCED"
        assert scene["scene_quality_score"] is None
        assert scene["lighting_score"] is None
        audio = validate_success(api.get_effect_cue(ctx["audio_cue"]["id"], PROGRAMMER))
        assert audio["status"] == "PLANNED"

    def test_an_empty_timeline_is_refused_by_the_same_rule(self, api):
        """It requires the posture not to be `FROZEN` and it requires the scene to own at least one cue with *every* cue of the scene already `VERIFIED`; a scene with no cues at all, or with any cue still `PLANNED`, is refused with `ERR_CUES_NOT_VERIFIED`.

        `show_quality_score` on the programme is the duration-weighted mean of the
        already-rounded `scene_quality_score` values of every scene of that programme
        whose `status` is `PROGRAMMED` or `VALIDATED`: the sum over those scenes of
        each scene's `scene_quality_score` multiplied by its `duration_seconds`,
        divided by the sum of those same `duration_seconds`, rounded half up to two
        decimal places.

        A scene owning no cue at all is not treated as one whose cues are all
        verified, so verifying the outstanding stinger lifts only the prologue to
        PROGRAMMED at 88.10, and the programme roll-up over that single included
        scene is 88.10.

        Design: Difficulty/cross_entity_state_dependency/scene_program_requires_every_owned_cue_verified_and_at_least_one_cue
        """
        ctx = self._scene_pair_with_one_outstanding_cue()

        response = api.program_show_scene(
            ctx["sc_b"]["id"],
            {"lighting_score": 70, "audio_score": 60,
             "animation_score": 65, "effects_score": 70},
            PROGRAMMER,
        )
        validate_error(response, ApiErrorId.ERR_CUES_NOT_VERIFIED.value)

        audio = verify_cue(ctx["audio_cue"]["id"])
        programmed = validate_success(
            api.program_show_scene(
                ctx["sc_a"]["id"],
                {"lighting_score": 92, "audio_score": 88,
                 "animation_score": 85, "effects_score": 88},
                PROGRAMMER,
            )
        )

        chase = validate_success(api.get_show_scene(ctx["sc_b"]["id"], DESIGNER))
        programme = read_project(ctx["project"]["id"])

        assert audio["status"] == "VERIFIED"
        assert programmed["status"] == "PROGRAMMED"
        assert float(programmed["scene_quality_score"]) == 88.10
        assert chase["status"] == "SEQUENCED"
        assert chase["scene_quality_score"] is None
        assert float(programme["show_quality_score"]) == 88.10


class TestBallotNeedsTheItemUnderReview:
    """The gate is the parent item's state, not the ballot's payload."""

    def _proposed_item(self):
        ctx = setup_program_at_schematic()
        ctx["ve_item"] = propose_ve_item(ctx["project"]["id"], **VE_ITEM)
        return ctx

    def test_no_party_may_cast_while_the_item_is_still_proposed(self, api):
        """Ballots may only be cast while the item is `UNDER_REVIEW`; an item that is still `PROPOSED` or already resolved is refused with `ERR_VE_ITEM_STATE_INVALID`, as is opening the ballot on an item that is not `PROPOSED`.

        The item is created `PROPOSED` with `net_saving_cents` null, `ballot_count` 0
        and `veto_present` false.

        The owner's own approval, cast with a matching declared party, is still
        refused while the item sits in PROPOSED, and no ballot row survives the
        attempt.

        Design: Difficulty/cross_entity_state_dependency/ve_ballot_requires_the_item_under_review_before_any_party_may_cast
        """
        ctx = self._proposed_item()

        response = api.create_ve_ballot(
            {
                "value_engineering_item_id": ctx["ve_item"]["id"],
                "party_role": "OwnerRep", "decision": "APPROVE",
                "comment": "Cast before review was opened",
            },
            OWNER,
        )

        validate_error(response, ApiErrorId.ERR_VE_ITEM_STATE_INVALID.value)
        item = validate_success(api.get_value_engineering_item(ctx["ve_item"]["id"], OWNER))
        assert item["status"] == "PROPOSED"
        assert item["net_saving_cents"] is None
        assert item["ballot_count"] == 0
        ballots, meta = validate_paginated(
            api.list_value_engineering_ballots(ctx["ve_item"]["id"], OWNER))
        assert ballots == []
        assert meta["total_count"] == 0

    def test_the_identical_ballot_is_accepted_once_review_is_opened(self, api):
        """An `OwnerRep` opens the ballot, moving the item from `PROPOSED` to `UNDER_REVIEW`.

        Opening the ballot fixes the item's net saving: the retained saving is
        `gross_saving_cents` multiplied by one minus `rework_loss_pct` divided by one
        hundred, and `net_saving_cents` is that retained saving rounded half up to
        whole cents *first* and then reduced by `implementation_cost_cents`.

        Each ballot records `cast_by_user_id` as the casting caller's `X-User-ID`,
        increments the item's `ballot_count`, and sets the item's `veto_present` flag
        true when its `decision` was `VETO`.

        Opening review both materialises the 16500005 net saving and unlocks the
        vote, so the request that was refused a moment ago now records the owner's
        approval as the item's first ballot.

        Design: Difficulty/cross_entity_state_dependency/ve_ballot_requires_the_item_under_review_before_any_party_may_cast
        """
        ctx = self._proposed_item()
        validate_error(
            api.create_ve_ballot(
                {
                    "value_engineering_item_id": ctx["ve_item"]["id"],
                    "party_role": "OwnerRep", "decision": "APPROVE",
                    "comment": "Cast before review was opened",
                },
                OWNER,
            ),
            ApiErrorId.ERR_VE_ITEM_STATE_INVALID.value,
        )

        under_review = open_ve_review(ctx["ve_item"]["id"])
        ballot = validate_success(
            api.create_ve_ballot(
                {
                    "value_engineering_item_id": ctx["ve_item"]["id"],
                    "party_role": "OwnerRep", "decision": "APPROVE",
                    "comment": "Cast after review was opened",
                },
                OWNER,
            ),
            201,
        )

        item = validate_success(api.get_value_engineering_item(ctx["ve_item"]["id"], OWNER))
        ballots, meta = validate_paginated(
            api.list_value_engineering_ballots(ctx["ve_item"]["id"], OWNER))

        assert under_review["net_saving_cents"] == 16500005
        assert ballot["party_role"] == "OwnerRep"
        assert item["status"] == "UNDER_REVIEW"
        assert item["net_saving_cents"] == 16500005
        assert item["ballot_count"] == 1
        assert item["veto_present"] is False
        assert len(ballots) == 1
        assert meta["total_count"] == 1
