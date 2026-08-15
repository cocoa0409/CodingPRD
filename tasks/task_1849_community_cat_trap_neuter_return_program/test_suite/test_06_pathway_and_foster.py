"""Pathway decisions, foster loop, release-readiness, and cat-level OCC."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_coordinator_headers,
    setup_cat_at_post_surgery, setup_kitten_in_foster, setup_cat_returned,
    setup_caretaker_with_colony, create_cat, create_partner_clinic,
    create_clinic_day, list_slots, get_cat, get_foster_home, get_colony,
    create_foster_home, create_foster_placement_payload, create_survey,
    drive_cat_to_post_surgery,
)


class TestFosterLoopCycle:
    """Difficulty/non_linear_state_machine/cat_foster_loop_cycle"""

    def test_return_to_program_reopens_decision(self, api):
        """PRD §3.6: "Returning to program is the foster loop: the placement ends
        as `ENDED_RETURNED`, the cat drops back from `IN_FOSTER` to
        `POST_SURGERY` with its `pathway` reset to null — the decision re-opened,
        so the kitten can be re-placed later — and the home's count decrements by
        one."

        Design: Difficulty/non_linear_state_machine/cat_foster_loop_cycle
        """
        sc = setup_kitten_in_foster(home_capacity=2)
        cat = sc["cat"]
        assert cat["status"] == "IN_FOSTER"
        assert cat["pathway"] == "ADOPTION"

        resp = api.return_placement_to_program(sc["placement"]["id"],
                                               sc["volunteer_headers"])
        validate_success(resp, expected_status=200)

        cat_after = get_cat(cat["id"])
        assert cat_after["status"] == "POST_SURGERY", \
            "cycle completes back at the decision point"
        assert cat_after.get("pathway") is None, "decision re-opened"
        home = get_foster_home(sc["foster_home"]["id"])
        assert home["current_kittens"] == 0

    def test_replacement_after_foster_return(self, api):
        """PRD §3.6: "Returning to program is the foster loop: the placement ends
        as `ENDED_RETURNED`, the cat drops back from `IN_FOSTER` to
        `POST_SURGERY` with its `pathway` reset to null — the decision re-opened,
        so the kitten can be re-placed later — and the home's count decrements by
        one."

        Design: Difficulty/non_linear_state_machine/cat_foster_loop_cycle
        """
        sc = setup_kitten_in_foster(home_capacity=2)
        get_success_data(api.return_placement_to_program(
            sc["placement"]["id"], sc["volunteer_headers"]))

        home2, vh2 = create_foster_home(volunteer_name="Second Home")
        ch = make_coordinator_headers()
        resp = api.create_foster_placement(
            create_foster_placement_payload(sc["cat"]["id"], home2["id"]), ch)
        placement = validate_success(resp, expected_status=201)
        assert placement["status"] == "ACTIVE"
        cat_after = get_cat(sc["cat"]["id"])
        assert cat_after["status"] == "IN_FOSTER"
        assert cat_after["pathway"] == "ADOPTION"


class TestPathwayPriority:
    """Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_pathway"""

    def test_state_error_wins_over_release_readiness(self, api):
        """PRD §3.5: "the request names the `pathway` and the
        `expected_cat_version`, and its checks run existence, then state, then the
        stale-version rejection (`ERR_STALE_VERSION`), then release-readiness."
        An AT_LARGE cat is both in the wrong state and unmarked/unvaccinated;
        state is checked first, so the rejection is ERR_INVALID_STATE.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_pathway
        """
        ct, cth, col = setup_caretaker_with_colony()
        cat = create_cat(col, intake_tag="P1", approximate_age_months=24)
        resp = api.decide_pathway(
            cat["id"],
            {"pathway": "RETURN_TO_FIELD", "expected_cat_version": cat["version"]},
            make_coordinator_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_release_readiness_fires_when_state_is_valid(self, api):
        """PRD §3.5: "Any pathway decision requires `ear_tipped` and
        `vaccinated_rabies` both true on the cat; a decision attempted on an
        unmarked or unvaccinated cat is rejected with `ERR_NOT_RELEASE_READY`
        (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_pathway
        """
        sc = setup_cat_at_post_surgery(surgery_overrides={
            "ear_tipped": False, "rabies_vaccinated": True,
            "outcome": "ALREADY_STERILE"})
        cat = sc["cat"]
        resp = api.decide_pathway(
            cat["id"],
            {"pathway": "RETURN_TO_FIELD", "expected_cat_version": cat["version"]},
            make_coordinator_headers())
        validate_error(resp, ApiErrorId.ERR_NOT_RELEASE_READY, expected_status=422)


class TestPathwayReleaseReadiness:
    def test_pathway_requires_ear_tip_and_rabies(self, api):
        """PRD §3.5: "Any pathway decision requires `ear_tipped` and
        `vaccinated_rabies` both true on the cat; a decision attempted on an
        unmarked or unvaccinated cat is rejected with `ERR_NOT_RELEASE_READY`
        (HTTP 422)."

        Design: Corner/validations/pathway_requires_ear_tip_and_rabies
        """
        sc = setup_cat_at_post_surgery(surgery_overrides={
            "ear_tipped": False, "rabies_vaccinated": True,
            "outcome": "ALREADY_STERILE"})
        cat = sc["cat"]
        resp = api.decide_pathway(
            cat["id"],
            {"pathway": "RETURN_TO_FIELD", "expected_cat_version": cat["version"]},
            make_coordinator_headers())
        validate_error(resp, ApiErrorId.ERR_NOT_RELEASE_READY, expected_status=422)


class TestFosterPlacementGuards:
    """Difficulty/cross_entity_state_dependency/foster_placement_depends_on_foster_home_state"""

    def test_placement_into_full_home_rejected(self, api):
        """PRD §3.6: "and home availability — a home that does not stand `ACTIVE`,
        or whose `current_kittens` has already reached its `capacity_kittens`,
        rejects the placement with `ERR_FOSTER_HOME_FULL` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/foster_placement_depends_on_foster_home_state
        """
        sc = setup_kitten_in_foster(home_capacity=1, kitten_age_months=2)
        col = sc["colony"]
        cth = sc["caretaker_headers"]
        day = sc["day"]
        slots = sc["slots"]
        k2 = create_cat(col, intake_tag="FK2", approximate_age_months=3)
        drive_cat_to_post_surgery(k2, cth, day["id"], slots[1])

        ch = make_coordinator_headers()
        resp = api.create_foster_placement(
            create_foster_placement_payload(k2["id"], sc["foster_home"]["id"]), ch)
        validate_error(resp, ApiErrorId.ERR_FOSTER_HOME_FULL, expected_status=409)

    def test_placement_into_home_with_room_accepted(self, api):
        """PRD §3.6: "A successful placement moves the kitten from `POST_SURGERY`
        to `IN_FOSTER`, records its `pathway` as `ADOPTION`, increments the home's
        `current_kittens` by one, and stamps `placed_at` from the logical clock"

        Design: Difficulty/cross_entity_state_dependency/foster_placement_depends_on_foster_home_state
        """
        sc = setup_cat_at_post_surgery(approximate_age_months=2)
        home, vh = create_foster_home(capacity_kittens=1)
        ch = make_coordinator_headers()
        resp = api.create_foster_placement(
            create_foster_placement_payload(sc["cat"]["id"], home["id"]), ch)
        placement = validate_success(resp, expected_status=201)
        assert placement["status"] == "ACTIVE"
        cat_after = get_cat(sc["cat"]["id"])
        assert cat_after["status"] == "IN_FOSTER"
        assert cat_after["pathway"] == "ADOPTION"
        assert get_foster_home(home["id"])["current_kittens"] == 1

    def test_foster_rejects_adult(self, api):
        """PRD §3.6: "the kitten rule — placement of a cat six months of age or
        older is rejected with `ERR_NOT_A_KITTEN` (HTTP 422)"

        Design: Corner/validations/foster_rejects_adult
        """
        sc = setup_cat_at_post_surgery(approximate_age_months=12)
        home, vh = create_foster_home(volunteer_name="Roomy Home", capacity_kittens=5)
        ch = make_coordinator_headers()
        resp = api.create_foster_placement(
            create_foster_placement_payload(sc["cat"]["id"], home["id"]), ch)
        validate_error(resp, ApiErrorId.ERR_NOT_A_KITTEN, expected_status=422)


class TestFosterCountConservation:
    """Difficulty/compensating_invariant/foster_placement_count_conservation"""

    def test_place_then_return_restores_count(self, api):
        """PRD §3.6: "A successful placement moves the kitten from `POST_SURGERY`
        to `IN_FOSTER`, records its `pathway` as `ADOPTION`, increments the home's
        `current_kittens` by one"
        PRD §3.6: "Returning to program is the foster loop: the placement ends as
        `ENDED_RETURNED`, the cat drops back from `IN_FOSTER` to `POST_SURGERY`
        with its `pathway` reset to null — the decision re-opened, so the kitten
        can be re-placed later — and the home's count decrements by one."

        Design: Difficulty/compensating_invariant/foster_placement_count_conservation
        """
        sc = setup_kitten_in_foster(home_capacity=2)
        assert get_foster_home(sc["foster_home"]["id"])["current_kittens"] == 1

        get_success_data(api.return_placement_to_program(
            sc["placement"]["id"], sc["volunteer_headers"]))
        home = get_foster_home(sc["foster_home"]["id"])
        assert home["current_kittens"] == 0, \
            "placement's +1 must be exactly compensated by return's -1"

    def test_place_then_graduate_restores_count(self, api):
        """PRD §3.6: "Graduation sends a ready kitten onward: the placement ends
        as `ENDED_ADOPTION`, the cat moves from `IN_FOSTER` to `ADOPTION_PIPELINE`,
        and the home's `current_kittens` decrements by one."

        Design: Difficulty/compensating_invariant/foster_placement_count_conservation
        """
        sc = setup_kitten_in_foster(home_capacity=2)
        assert get_foster_home(sc["foster_home"]["id"])["current_kittens"] == 1

        get_success_data(api.graduate_placement(
            sc["placement"]["id"], sc["volunteer_headers"]))
        home = get_foster_home(sc["foster_home"]["id"])
        assert home["current_kittens"] == 0
        assert get_cat(sc["cat"]["id"])["status"] == "ADOPTION_PIPELINE"


class TestAdoptionFallthrough:
    def test_adoption_fallthrough_returns_to_decision_point(self, api):
        """PRD §3.5: "Adoption is not always permanent. A cat that fails to place
        can fall through: the same pathway decision capability, applied to a cat
        standing `ADOPTION_PIPELINE` with `pathway` set to `RETURN_TO_FIELD`,
        sends the cat back to `POST_SURGERY` and resets its `pathway` to null,
        re-opening the decision; a subsequent `RETURN_TO_FIELD` decision then
        applies from `POST_SURGERY` in the ordinary way."

        Design: Corner/state_machines/adoption_fallthrough_returns_to_decision_point
        """
        sc = setup_cat_at_post_surgery(approximate_age_months=30)
        ch = make_coordinator_headers()
        cat = sc["cat"]

        first = validate_success(api.decide_pathway(
            cat["id"], {"pathway": "ADOPTION", "expected_cat_version": cat["version"]},
            ch))
        assert first["status"] == "ADOPTION_PIPELINE"

        second = validate_success(api.decide_pathway(
            cat["id"],
            {"pathway": "RETURN_TO_FIELD", "expected_cat_version": first["version"]},
            ch))
        assert second["status"] == "POST_SURGERY", "fall-through re-opens the decision"
        assert second.get("pathway") is None

        third = validate_success(api.decide_pathway(
            cat["id"],
            {"pathway": "RETURN_TO_FIELD", "expected_cat_version": second["version"]},
            ch))
        assert third["status"] == "RETURNED"
        assert third["pathway"] == "RETURN_TO_FIELD"


class TestConfirmLongTerm:
    def test_confirm_long_term_requires_qualifying_survey(self, api):
        """PRD §3.5: "Once a field survey of the cat's colony — covered in §3.9 —
        exists whose `surveyed_on` falls on or after the moment the cat entered
        `RETURNED` and whose `eartipped_count` is at least 1, the
        `ProgramCoordinator` may confirm the cat long-term, moving it from
        `RETURNED` to `COLONY_STERILIZED`; without a qualifying survey the
        confirmation is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/confirm_long_term_requires_qualifying_survey
        """
        sc = setup_cat_returned()
        ch = make_coordinator_headers()
        cat = sc["cat"]

        rejected = api.confirm_long_term(cat["id"], ch)
        validate_error(rejected, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        create_survey(sc["colony"], headers=ch, surveyed_on="2026-08-01T00:00:00Z",
                      observed_count=3, eartipped_count=1)
        ok = api.confirm_long_term(cat["id"], ch)
        data = validate_success(ok)
        assert data["status"] == "COLONY_STERILIZED"


class TestDecidePathwayStaleVersion:
    def test_decide_pathway_stale_cat_version(self, api):
        """PRD §2.9: "Deciding a cat's pathway requires `expected_cat_version`,
        compared against the cat's current `version`; if a foster return or
        another pathway decision has advanced the cat since the client's last
        read — re-opening the decision by resetting `pathway` — the request is
        likewise rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.5: "its checks run existence, then state, then the stale-version
        rejection (`ERR_STALE_VERSION`), then release-readiness."

        The advancing event is the adoption fall-through (PRD §3.5): two pathway
        decisions return the cat to POST_SURGERY with `pathway` reset to null —
        the decision re-opened — so the stale read faces a cat standing at a
        legal decision point and the stale-version rejection fires.

        Design: Corner/cross_cutting_layers/decide_pathway_stale_cat_version
        """
        sc = setup_cat_at_post_surgery(approximate_age_months=24)
        ch = make_coordinator_headers()
        cat = sc["cat"]
        observed_version = cat["version"]

        first = validate_success(api.decide_pathway(
            cat["id"], {"pathway": "ADOPTION",
                        "expected_cat_version": observed_version}, ch))
        assert first["status"] == "ADOPTION_PIPELINE"

        second = validate_success(api.decide_pathway(
            cat["id"], {"pathway": "RETURN_TO_FIELD",
                        "expected_cat_version": first["version"]}, ch))
        assert second["status"] == "POST_SURGERY", \
            "fall-through re-opens the decision"
        assert second.get("pathway") is None

        stale = api.decide_pathway(
            cat["id"], {"pathway": "RETURN_TO_FIELD",
                        "expected_cat_version": observed_version}, ch)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


class TestVersionIncrements:
    def test_version_increments_on_every_mutation(self, api):
        """PRD §2.5: "`version` — an integer that increments by one on every
        mutation, including mutations caused by side effects and by recomputation
        of derived fields; it backs the optimistic concurrency checks of §2.9."
        A rejected request is no mutation, so the cat's version is unchanged by a
        failed confirm-long-term attempt.

        Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
        """
        ct, cth, col = setup_caretaker_with_colony()
        cat = create_cat(col, intake_tag="VE1", approximate_age_months=24)
        before = get_cat(cat["id"])
        assert isinstance(before["version"], int)

        # Failed mutation: AT_LARGE cat cannot be confirmed long-term.
        validate_error(api.confirm_long_term(cat["id"], make_coordinator_headers()),
                       ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        after = get_cat(cat["id"])
        assert after["version"] == before["version"], \
            (f"failed mutations must not bump version: "
             f"before={before['version']} after={after['version']}")
