"""Bylaws amendment adoption threshold, adoption cascade, defeat loop."""
import test_helpers as th
from test_helpers import fixtures as fx

ADMIN = th.TEST_USERS["governance_admin_headers"]


class TestAmendmentThresholdHealthyBoard:
    """Difficulty: combinatorial_formula / amendment_threshold_nested_branch_max_ceil."""

    def _setup(self, api):
        """6 ACTIVE of board_size 8, threshold 67: healthy branch (6 >= ceil(0.75*8))."""
        return fx.setup_amendment_motion_open(
            num_members=6, board_size=8, amendment_threshold_pct=67,
            proposed_fields={"quorum_pct": 60}, title="Raise quorum to 60%",
            ein="EIN-AMEND-1")

    def test_required_votes_uses_seated_basis_when_healthy(self, api):
        """PRD §3.5: "When a `BYLAWS` motion closes, the generic threshold machinery
        is replaced by the amendment-adoption threshold: the basis is the count of
        `ACTIVE` directors when that count is at least three-quarters of the
        authorized seats — computed as the ceiling of 0.75 times `board_size` — and
        otherwise the full `board_size` itself, so a healthy board needs the bylaws'
        percentage of seated directors while a depleted board needs that percentage
        of authorized seats; the required votes are the greater of 2 and the ceiling
        of `amendment_threshold_pct` percent of that basis."
        PRD §3.5: "The motion passes when the `AYE` count is at least the
        requirement — equality passes — with the additional unanimous-condition
        applied for `UNANIMOUS`, and fails otherwise; the computed requirement is
        persisted as the motion's `required_votes`, which is null until close."

        Design: Difficulty/combinatorial_formula/amendment_threshold_nested_branch_max_ceil
        """
        sc = self._setup(api)
        np_id = sc["nonprofit"]["id"]
        chair = sc["chair"]
        chair_headers = th.make_board_chair_headers(chair["id"])
        members = sc["members"]
        for m, choice in zip(members, ("AYE", "AYE", "AYE", "AYE", "AYE", "NAY")):
            fx.cast_vote(np_id, sc["motion"]["id"], m, choice)
        closed = th.validate_success(api.close_voting(sc["motion"]["id"], chair_headers))
        # 6 ACTIVE >= ceil(0.75*8) == 6 -> basis 6 -> required max(2, ceil(0.67*6)) == 5
        assert closed["required_votes"] == 5, (
            f"healthy board (6 >= 6) uses seated basis 6, got {closed['required_votes']}")
        assert closed["status"] == "PASSED", "5 AYE == required 5 passes on equality"

    def test_adoption_mints_successor_and_supersedes_base(self, api):
        """PRD §3.5: "Passage moves the linked amendment to `ADOPTED` and fires the
        adoption chain: a successor bylaws document is minted with `version_no` one
        greater than the base, the base's field values overlaid with the amendment's
        `proposed_fields`, status `ADOPTED`, and `adopted_at` stamped from the
        clock; the base document becomes `SUPERSEDED`; existing terms remain pinned
        to their original documents, but every future election reads
        `term_length_years`, `max_consecutive_terms`, and `board_size` from the
        newly adopted document; and the nonprofit's `version` increments by 1."

        Design: Difficulty/combinatorial_formula/amendment_threshold_nested_branch_max_ceil
        """
        sc = self._setup(api)
        np_id = sc["nonprofit"]["id"]
        chair = sc["chair"]
        chair_headers = th.make_board_chair_headers(chair["id"])
        for m in sc["members"][:5]:
            fx.cast_vote(np_id, sc["motion"]["id"], m, "AYE")
        closed = th.validate_success(api.close_voting(sc["motion"]["id"], chair_headers))
        assert closed["status"] == "PASSED"

        amendment = th.validate_success(api.get_amendment(sc["amendment"]["id"], ADMIN))
        assert amendment["status"] == "ADOPTED", "link 1: motion PASSED adopts the amendment"

        base = th.validate_success(api.get_bylaws(sc["bylaws"]["id"], ADMIN))
        assert base["status"] == "SUPERSEDED", "link 2: the base document is superseded"

        data, meta = th.validate_paginated(api.list_bylaws(
            ADMIN, params={"nonprofit_id": np_id, "status": "ADOPTED"}))
        assert meta["total_count"] == 1
        successor = data[0]
        assert successor["version_no"] == sc["bylaws"]["version_no"] + 1 == 2
        assert successor["quorum_pct"] == 60, "proposed_fields overlaid onto the successor"


class TestAmendmentAdoptionCascade:
    """Difficulty: transitive_cascade / amendment_adoption_cascade_changes_future_term_length."""

    def _adopt_term_length_amendment(self, api):
        sc = fx.setup_amendment_motion_open(
            num_members=6, board_size=8, amendment_threshold_pct=67,
            proposed_fields={"term_length_years": 3}, title="Lengthen terms",
            ein="EIN-CASC-1")
        np_id = sc["nonprofit"]["id"]
        chair = sc["chair"]
        chair_headers = th.make_board_chair_headers(chair["id"])
        np_before = th.validate_success(api.get_nonprofit(np_id, ADMIN))
        for m in sc["members"]:
            fx.cast_vote(np_id, sc["motion"]["id"], m, "AYE")
        closed = th.validate_success(api.close_voting(sc["motion"]["id"], chair_headers))
        assert closed["status"] == "PASSED"
        return sc, np_before

    def test_adoption_cascade_bumps_nonprofit_version(self, api):
        """PRD §3.5: "Passage moves the linked amendment to `ADOPTED` and fires the
        adoption chain: a successor bylaws document is minted with `version_no` one
        greater than the base, the base's field values overlaid with the amendment's
        `proposed_fields`, status `ADOPTED`, and `adopted_at` stamped from the
        clock; the base document becomes `SUPERSEDED`; existing terms remain pinned
        to their original documents, but every future election reads
        `term_length_years`, `max_consecutive_terms`, and `board_size` from the
        newly adopted document; and the nonprofit's `version` increments by 1."

        Design: Difficulty/transitive_cascade/amendment_adoption_cascade_changes_future_term_length
        """
        sc, np_before = self._adopt_term_length_amendment(api)
        amendment = th.validate_success(api.get_amendment(sc["amendment"]["id"], ADMIN))
        assert amendment["status"] == "ADOPTED"
        base = th.validate_success(api.get_bylaws(sc["bylaws"]["id"], ADMIN))
        assert base["status"] == "SUPERSEDED"
        data, _meta = th.validate_paginated(api.list_bylaws(
            ADMIN, params={"nonprofit_id": sc["nonprofit"]["id"], "status": "ADOPTED"}))
        assert len(data) == 1 and data[0]["term_length_years"] == 3
        np_after = th.validate_success(api.get_nonprofit(sc["nonprofit"]["id"], ADMIN))
        assert np_after["version"] == np_before["version"] + 1, (
            "the adoption cascade bumps the nonprofit version by exactly 1")

    def test_future_term_reads_amended_term_length(self, api):
        """PRD §3.5: "existing terms remain pinned to their original documents, but
        every future election reads `term_length_years`, `max_consecutive_terms`,
        and `board_size` from the newly adopted document"
        PRD §3.2: "the term is version-pinned to that document via its `bylaws_id`:
        its `end_date` is computed as the `start_date` plus the pinned bylaws'
        `term_length_years` on the same calendar day, and later amendments never
        mutate an existing term's end date."

        Design: Difficulty/transitive_cascade/amendment_adoption_cascade_changes_future_term_length
        """
        sc, _np_before = self._adopt_term_length_amendment(api)
        np_id = sc["nonprofit"]["id"]
        data, _meta = th.validate_paginated(api.list_bylaws(
            ADMIN, params={"nonprofit_id": np_id, "status": "ADOPTED"}))
        new_bylaws = data[0]

        new_member = fx.create_board_member(np_id, "NewDir", "nd@x.org",
                                            skills=["TECHNOLOGY"])
        term = th.validate_success(api.create_board_term(
            th.create_term_payload(np_id, new_member["id"],
                                   start_date="2026-08-01T00:00:00Z"), ADMIN), 201)
        assert term["bylaws_id"] == new_bylaws["id"], (
            "the new term pins the newly adopted bylaws document")
        th.assert_instant_eq(term["end_date"], "2029-08-01T00:00:00Z",
            f"start + amended 3-year length, got {term['end_date']}")


class TestAmendmentGatedByMotionOutcome:
    """Difficulty: cross_entity_state_dependency / amendment_adoption_gated_by_motion_outcome."""

    def _setup_depleted_board(self, api):
        """3 ACTIVE of board_size 5: 3 < ceil(0.75*5)=4 -> depleted branch, basis 5."""
        return fx.setup_amendment_motion_open(
            num_members=3, board_size=5, amendment_threshold_pct=67,
            proposed_fields={"board_size": 7}, title="Enlarge board",
            ein="EIN-GATE-3")

    def test_failed_motion_defeats_amendment(self, api):
        """PRD §3.5: "Failure moves the amendment to `DEFEATED` and clears its
        `motion_id`, leaving it free to be revised and re-voted."
        PRD §3.5: "When a `BYLAWS` motion closes, the generic threshold machinery is
        replaced by the amendment-adoption threshold: the basis is the count of
        `ACTIVE` directors when that count is at least three-quarters of the
        authorized seats — computed as the ceiling of 0.75 times `board_size` — and
        otherwise the full `board_size` itself, so a healthy board needs the bylaws'
        percentage of seated directors while a depleted board needs that percentage
        of authorized seats; the required votes are the greater of 2 and the ceiling
        of `amendment_threshold_pct` percent of that basis."

        Design: Difficulty/cross_entity_state_dependency/amendment_adoption_gated_by_motion_outcome
        """
        sc = self._setup_depleted_board(api)
        np_id = sc["nonprofit"]["id"]
        chair = sc["chair"]
        chair_headers = th.make_board_chair_headers(chair["id"])
        members = sc["members"]
        for m, choice in zip(members, ("AYE", "NAY", "NAY")):
            fx.cast_vote(np_id, sc["motion"]["id"], m, choice)
        closed = th.validate_success(api.close_voting(sc["motion"]["id"], chair_headers))
        # depleted: 3 < ceil(0.75*5)=4 -> basis 5 -> required max(2, ceil(0.67*5)) == 4
        assert closed["required_votes"] == 4, (
            f"depleted board (3 < 4) uses authorized basis 5, got {closed['required_votes']}")
        assert closed["status"] == "FAILED", "1 AYE < 4"

        amendment = th.validate_success(api.get_amendment(sc["amendment"]["id"], ADMIN))
        assert amendment["status"] == "DEFEATED", (
            "motion FAILED pushes the linked amendment to DEFEATED")
        assert amendment.get("motion_id") is None, "defeat clears the motion link"
        base = th.validate_success(api.get_bylaws(sc["bylaws"]["id"], ADMIN))
        assert base["status"] == "ADOPTED", "defeat never supersedes the base document"

    def test_defeated_amendment_revise_reopens_draft(self, api):
        """PRD §3.1: "A defeated amendment's `motion_id` is cleared so the board may
        rework the text, and the `BoardChair` may return a `DEFEATED` amendment to
        `DRAFT` for revision, which is the cycle that lets a single amendment be
        voted more than once."

        Design: Difficulty/cross_entity_state_dependency/amendment_adoption_gated_by_motion_outcome
        """
        sc = self._setup_depleted_board(api)
        np_id = sc["nonprofit"]["id"]
        chair = sc["chair"]
        chair_headers = th.make_board_chair_headers(chair["id"])
        members = sc["members"]
        for m, choice in zip(members, ("AYE", "NAY", "NAY")):
            fx.cast_vote(np_id, sc["motion"]["id"], m, choice)
        th.validate_success(api.close_voting(sc["motion"]["id"], chair_headers))

        revised = th.validate_success(api.revise_amendment(
            sc["amendment"]["id"], chair_headers))
        assert revised["status"] == "DRAFT", (
            "the DEFEATED -> DRAFT revision loop reopens the amendment")
