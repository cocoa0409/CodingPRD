"""Corner queue: health clearance variants, raiser selector policy, match
selector coverage filter (PRD §3.5, §3.6, §3.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_approved_raiser,
    create_cleared_dog,
    create_dog_in_advanced_training,
    create_dog_payload,
    create_eligible_entry,
    create_screening_payload,
    record_milestone,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
ADMIN = TEST_USERS["program_admin_headers"]
TD = TEST_USERS["training_director_headers"]
VET = TEST_USERS["veterinarian_headers"]


class TestHealthClearanceHardFail:
    """Corner/calculations/health_clearance_hard_fail_zero_component."""

    def test_zero_component_forces_failed(self, api):
        """PRD §3.5: "A hard fail — any single component scoring 0 — fails the
        screening regardless of total."
        PRD §3.5: "hip contributes 30 for `EXCELLENT`, 24 for `GOOD`, 12 for
        `FAIR`, and 0 for `POOR`; elbow contributes 20 for `NORMAL`, 8 for
        `GRADE1`, and 0 for `GRADE2`; eye contributes 15 for `CLEAR` and 0 for
        `ABNORMAL`; cardiac contributes 15 for `NORMAL` and 0 for `ABNORMAL`;
        genetic contributes 20 for `CLEAR`, 10 for `CARRIER`, and 0 for
        `AFFECTED`."
        PRD §3.5: "A failing submission — hard fail or below threshold —
        moves the screening to `FAILED` and mirrors the dog to
        `CAREER_CHANGED` with `career_change_reason` set to `HEALTH`."

        hip POOR (0) + elbow NORMAL (20) + eye CLEAR (15) + cardiac NORMAL
        (15) + genetic CLEAR (20) = 70 with a hard fail.

        Design: Corner/calculations/health_clearance_hard_fail_zero_component
        """
        dog = validate_success(
            api.create_dog(create_dog_payload(), ADMIN), expected_status=201
        )
        validate_success(api.begin_screening(dog["id"], VET))
        screening = validate_success(
            api.create_screening(
                dog["id"],
                create_screening_payload(hip_grade="POOR", genetic_panel="CLEAR"),
                VET,
            ),
            expected_status=201,
        )
        submitted = validate_success(api.submit_screening(screening["id"], VET))
        assert submitted["clearance_score"] == 70
        assert submitted["status"] == "FAILED"
        dog_now = validate_success(api.get_dog(dog["id"], TD))
        assert dog_now["status"] == "CAREER_CHANGED"
        assert dog_now["career_change_reason"] == "HEALTH"


class TestHealthClearanceBredVsDonated:
    """Corner/calculations/health_clearance_bred_vs_donated_thresholds."""

    def test_identical_84_carrier_passes_donated_fails_bred(self, api):
        """PRD §3.5: "A `DONATED` dog passes when its score is at least 84
        with no hard fail; a `CARRIER` genetic panel is tolerated on this
        track at its 10 points. A `BRED` dog passes only when its score is at
        least 92 **and** the genetic panel is `CLEAR`, with no other hard fail
        — so an identical component set can pass a donated dog yet fail a bred
        dog twice over (once on the threshold, once on the genetic
        requirement)."

        GOOD hip (24) + NORMAL elbow (20) + CLEAR eye (15) + NORMAL cardiac
        (15) + CARRIER genetic (10) = 84.

        Design: Corner/calculations/health_clearance_bred_vs_donated_thresholds
        """
        sire = validate_success(
            api.create_dog(
                create_dog_payload(sex="MALE", born_on="2022-01-01"), ADMIN
            ),
            expected_status=201,
        )
        dam = validate_success(
            api.create_dog(
                create_dog_payload(sex="FEMALE", born_on="2022-02-01"), ADMIN
            ),
            expected_status=201,
        )
        donated = validate_success(
            api.create_dog(create_dog_payload(sex="MALE"), ADMIN),
            expected_status=201,
        )
        validate_success(api.begin_screening(donated["id"], VET))
        bred = validate_success(
            api.create_dog(
                create_dog_payload(
                    origin="BRED",
                    sex="FEMALE",
                    sire_id=sire["id"],
                    dam_id=dam["id"],
                    donor_name=None,
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        validate_success(api.begin_screening(bred["id"], VET))
        sc_donated = validate_success(
            api.create_screening(donated["id"], create_screening_payload(), VET),
            expected_status=201,
        )
        sc_bred = validate_success(
            api.create_screening(bred["id"], create_screening_payload(), VET),
            expected_status=201,
        )
        submitted_d = validate_success(api.submit_screening(sc_donated["id"], VET))
        assert submitted_d["clearance_score"] == 84
        assert submitted_d["status"] == "CLEARED"
        dog_d = validate_success(api.get_dog(donated["id"], TD))
        assert dog_d["status"] == "CLEARED"
        submitted_b = validate_success(api.submit_screening(sc_bred["id"], VET))
        assert submitted_b["clearance_score"] == 84
        assert submitted_b["status"] == "FAILED", (
            "84 < 92 and CARRIER != CLEAR fail the BRED track twice over"
        )
        dog_b = validate_success(api.get_dog(bred["id"], TD))
        assert dog_b["status"] == "CAREER_CHANGED"


class TestRaiserSelectorTieBreak:
    """Corner/calculations/raiser_selector_tie_break_created_at."""

    def test_equal_experience_tie_broken_by_created_at(self, api):
        """PRD §3.6: "the pool is ranked by `experience_score` descending,
        ties broken by `last_placement_ended_at` ascending with nulls sorted
        last — a never-placed raiser loses ties to previously active ones —
        then by `created_at` ascending."

        Two APPROVED raisers, same region, experience 50 each, both
        last_placement_ended_at null: the first-created wins.

        Design: Corner/calculations/raiser_selector_tie_break_created_at
        """
        r1 = create_approved_raiser(experience_score=50)
        r2 = create_approved_raiser(experience_score=50)
        dog = create_cleared_dog()
        placement = validate_success(
            api.create_raiser_placement(dog["id"], {}, TD),
            expected_status=201,
        )
        assert placement["puppy_raiser_id"] == r1["id"], (
            f"created_at ascending must pick the first raiser, got "
            f"{placement['puppy_raiser_id']}"
        )
        r1_now = validate_success(api.get_puppy_raiser(r1["id"], ADMIN))
        assert r1_now["status"] == "ACTIVE"
        assert r1_now["current_dog_count"] == 1
        r2_now = validate_success(api.get_puppy_raiser(r2["id"], ADMIN))
        assert r2_now["current_dog_count"] == 0


class TestRaiserSelectorEmptyPool:
    """Corner/calculations/raiser_selector_empty_pool_returns_error."""

    def test_no_regional_raiser_rejected(self, api):
        """PRD §3.6: "the candidate pool is every raiser in `APPROVED` or
        `ACTIVE` whose `current_dog_count` is below `foster_capacity` and
        whose `region` equals the dog's `region` ... an empty pool is rejected
        with `ERR_NO_AVAILABLE_RAISER`."

        The only APPROVED raiser is in NW; the dog is in SW.

        Design: Corner/calculations/raiser_selector_empty_pool_returns_error
        """
        create_approved_raiser(region="NW")
        dog = create_cleared_dog(dog_overrides={"region": "SW"})
        resp = api.create_raiser_placement(dog["id"], {}, TD)
        validate_error(resp, ApiErrorId.ERR_NO_AVAILABLE_RAISER)
        placements = validate_success(api.list_dog_raiser_placements(dog["id"], TD))
        assert len(placements) == 0


class TestMatchSelectorTaskCoverage:
    """Corner/calculations/match_selector_task_coverage_and_explicit_insufficient."""

    def _dog_certified_retrieve_only(self, api):
        """MATCH_READY dog whose certified_tasks is {RETRIEVE_ITEMS}: the six
        advancing milestones use RETRIEVE_ITEMS for every TASK_WORK slot."""
        milestones = [
            {"category": "TASK_WORK", "task_code": "RETRIEVE_ITEMS", "score": 95},
            {"category": "TASK_WORK", "task_code": "RETRIEVE_ITEMS", "score": 90},
            {"category": "PUBLIC_MANNERS", "score": 88},
            {"category": "OBEDIENCE", "score": 85},
            {"category": "SOCIALIZATION", "score": 82},
            {"category": "TASK_WORK", "task_code": "RETRIEVE_ITEMS", "score": 84},
        ]
        dog, _r, _t, _pl = create_dog_in_advanced_training()
        for spec in milestones:
            record_milestone(
                dog["id"], _t["id"], spec["category"], spec["score"],
                spec.get("task_code"),
            )
        dog = validate_success(api.get_dog(dog["id"], TD))
        assert dog["status"] == "MATCH_READY"
        return dog

    def test_selector_mode_excludes_insufficient_coverage(self, api):
        """PRD §3.7: "In selector mode the candidate pool is every `ELIGIBLE`
        entry whose applicant's `required_tasks` form a subset of the dog's
        `certified_tasks` — subset failures are silently excluded here rather
        than rejected — ranked by `rank_score` descending ... an empty pool is
        rejected with `ERR_NO_ELIGIBLE_MATCH`."

        Dog certified only for RETRIEVE_ITEMS; sole ELIGIBLE entry requires
        RETRIEVE_ITEMS + OPEN_DOORS -> empty pool.

        Design: Corner/calculations/match_selector_task_coverage_and_explicit_insufficient
        """
        dog = self._dog_certified_retrieve_only(api)
        _applicant, _entry, _c = create_eligible_entry(
            required_tasks=("RETRIEVE_ITEMS", "OPEN_DOORS")
        )
        dog_now = validate_success(api.get_dog(dog["id"], TD))
        resp = api.create_match_proposal(
            dog["id"], {"expected_dog_version": dog_now["version"]}, COORD
        )
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_MATCH)

    def test_explicit_pick_with_coverage_gap_rejected_422(self, api):
        """PRD §3.7: "An explicit entry must be `ELIGIBLE` (otherwise
        `ERR_INVALID_STATE`), and the dog's `certified_tasks` must cover every
        task in the applicant's `required_tasks` from the latest
        `FINALIZED_ACCEPTED` assessment — a coverage gap on an explicit pick
        is rejected with `ERR_TASK_COVERAGE_INSUFFICIENT` (HTTP 422)."

        Design: Corner/calculations/match_selector_task_coverage_and_explicit_insufficient
        """
        dog = self._dog_certified_retrieve_only(api)
        _applicant, entry, _c = create_eligible_entry(
            required_tasks=("RETRIEVE_ITEMS", "OPEN_DOORS")
        )
        dog_now = validate_success(api.get_dog(dog["id"], TD))
        resp = api.create_match_proposal(
            dog["id"],
            {
                "waitlist_entry_id": entry["id"],
                "expected_dog_version": dog_now["version"],
            },
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_TASK_COVERAGE_INSUFFICIENT)
        matches = validate_success(api.list_dog_matches(dog["id"], TD))
        assert len(matches) == 0
