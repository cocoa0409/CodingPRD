"""Directors, board terms, term limits, open seats, recruitment matrix."""
import test_helpers as th
from test_helpers import fixtures as fx

ADMIN = th.TEST_USERS["governance_admin_headers"]


class TestMemberRegistration:
    def test_board_member_email_uniqueness_scoped_per_nonprofit(self, api):
        """PRD §3.2: "A director enters the system as a nominee: a
        `GovernanceAdmin` proposes a board member with `full_name`, an `email` that
        must be unique within the nonprofit (`ERR_DUPLICATE_MEMBER_EMAIL`), a
        `skill_tags` list drawn from the recruitment vocabulary of `FINANCE`,
        `LEGAL`, `FUNDRAISING`, `PROGRAM`, `GOVERNANCE`, `MARKETING`, `TECHNOLOGY`,
        and `HR`, an `officer_role` of `NONE`, `CHAIR`, `TREASURER`, or `SECRETARY`
        defaulting to `NONE`, and an `is_independent` flag defaulting to true."

        Design: Corner/entities/board_member_email_uniqueness_scoped_per_nonprofit
        """
        o1 = fx.create_nonprofit(name="O1", ein="EIN-EM-1", receipts=1_000_000)
        o2 = fx.create_nonprofit(name="O2", ein="EIN-EM-2", receipts=1_000_000)
        fx.create_board_member(o1["id"], "A", "a@x.org", skills=["FINANCE"])

        resp_dup = api.create_board_member(
            th.create_member_payload(o1["id"], "A2", "a@x.org",
                                     skill_tags=["LEGAL"]), ADMIN)
        th.validate_error(resp_dup, th.ApiErrorId.ERR_DUPLICATE_MEMBER_EMAIL)

        ok = th.validate_success(api.create_board_member(
            th.create_member_payload(o2["id"], "A", "a@x.org",
                                     skill_tags=["FINANCE"]), ADMIN), 201)
        th.assert_board_member(ok)
        assert ok["nonprofit_id"] == o2["id"]

    def test_board_member_invalid_skill_tag_rejected(self, api):
        """PRD §2.7: "Malformed requests short-circuit immediately after this auth
        block and before any existence or state check: a missing required field, a
        wrong-typed value, an enum value outside its defined set, a negative amount,
        an empty `proposed_fields` or `answers` or `restriction_categories` payload,
        or an end boundary not after its start boundary is rejected with
        `ERR_INVALID_REQUEST` (400)."
        PRD §3.2: "a `skill_tags` list drawn from the recruitment vocabulary of
        `FINANCE`, `LEGAL`, `FUNDRAISING`, `PROGRAM`, `GOVERNANCE`, `MARKETING`,
        `TECHNOLOGY`, and `HR`"

        Design: Corner/entities/board_member_invalid_skill_tag_rejected
        """
        org = fx.create_nonprofit(name="O", ein="EIN-SK-1", receipts=1_000_000)
        resp = api.create_board_member(
            th.create_member_payload(org["id"], "Bad", "bad@x.org",
                                     skill_tags=["UNDERWATER_BASKET_WEAVING"]), ADMIN)
        th.validate_error(resp, th.ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestTermCreation:
    def test_board_term_end_date_and_bylaws_pinning_computed(self, api):
        """PRD §3.2: "Election requires an `ADOPTED` bylaws to exist, else
        `ERR_BYLAWS_NOT_ADOPTED`, and the term is version-pinned to that document
        via its `bylaws_id`: its `end_date` is computed as the `start_date` plus the
        pinned bylaws' `term_length_years` on the same calendar day, and later
        amendments never mutate an existing term's end date."
        PRD §3.2: "A term whose `start_date` lies in the future is `SCHEDULED`; one
        whose start has been reached is `ACTIVE` immediately, and a term whose
        `end_date` has also already passed is swept to `COMPLETED` by the next
        compliance sweep."
        PRD §3.2: "Election moves a `PROPOSED`, `PAST`, or `TERM_LIMITED_OUT` member
        to `ACTIVE` — an `ACTIVE` incumbent simply stays `ACTIVE` — and for a
        `TERM_LIMITED_OUT` member the new term restarts the chain at `chain_index`
        1."

        Design: Corner/entities/board_term_end_date_and_bylaws_pinning_computed
        """
        org = fx.create_nonprofit(name="O", ein="EIN-TD-1", receipts=1_000_000)
        bylaws = fx.create_adopted_bylaws(org["id"], term_length_years=2)
        member = fx.create_board_member(org["id"], "N", "n@x.org", skills=["FINANCE"])

        term = th.validate_success(api.create_board_term(
            th.create_term_payload(org["id"], member["id"],
                                   start_date="2026-01-01T00:00:00Z"), ADMIN), 201)
        th.assert_board_term(term)
        th.assert_instant_eq(term["end_date"], "2028-01-01T00:00:00Z",
            f"end_date must be start + 2 years on the same calendar day, got {term['end_date']}")
        assert term["bylaws_id"] == bylaws["id"], "term must pin the ADOPTED bylaws"
        assert term["chain_index"] == 1
        assert term["status"] == "ACTIVE", (
            f"start 2026-01-01 already reached at the default clock, got {term['status']}")
        member_after = th.validate_success(api.get_board_member(member["id"], ADMIN))
        assert member_after["status"] == "ACTIVE"


class TestResignedMemberLockdown:
    def test_resigned_member_terminal_lockdown(self, api):
        """PRD §3.2: "The member must be `PROPOSED`, `PAST`, `TERM_LIMITED_OUT`, or
        `ACTIVE` — an `ACTIVE` incumbent may be re-elected to a non-overlapping next
        term — while `RESIGNED` or `REMOVED` members are rejected with
        `ERR_MEMBER_NOT_ELIGIBLE`."
        PRD §2.7: "7. **State-machine from-state.** The target resource must be in a
        state from which the requested transition is allowed, else
        `ERR_INVALID_STATE` (409); this also covers transitions attempted on
        terminal resources and non-idempotent re-fires."

        Design: Corner/state_machines/resigned_member_terminal_lockdown
        """
        sc = fx.setup_org_with_board(num_directors=1, officers=("CHAIR",), ein="EIN-RS-1")
        np_id = sc["nonprofit"]["id"]
        member = sc["members"][1]
        resigned = th.validate_success(api.resign_member(member["id"], ADMIN))
        assert resigned["status"] == "RESIGNED"

        th.validate_error(api.resign_member(member["id"], ADMIN),
                          th.ApiErrorId.ERR_INVALID_STATE)

        resp_term = api.create_board_term(
            th.create_term_payload(np_id, member["id"],
                                   start_date="2027-01-01T00:00:00Z"), ADMIN)
        th.validate_error(resp_term, th.ApiErrorId.ERR_MEMBER_NOT_ELIGIBLE)


class TestSweepTermTransitions:
    def test_member_past_vs_term_limited_branch_on_sweep(self, api):
        """PRD §3.2: "Thereafter the sweep advances `SCHEDULED` terms to `ACTIVE`
        once the clock reaches the start date and completes `ACTIVE` terms at their
        end; at completion, the member becomes `PAST` if still eligible for
        re-election (chain length below the cap) or `TERM_LIMITED_OUT` when the
        chain has reached the current bylaws' `max_consecutive_terms`, and either
        way the freed seat re-enters the open-seat pool."
        PRD §3.2: "the chain is the longest trailing run in which each term's
        `start_date` falls exactly on the previous term's `end_date` — strict
        half-open adjacency, where any positive gap breaks the chain."

        Design: Corner/state_machines/member_past_vs_term_limited_branch_on_sweep
        """
        org = fx.create_nonprofit(name="O", ein="EIN-PB-1", receipts=1_000_000)
        fx.create_adopted_bylaws(org["id"], term_length_years=1,
                                 max_consecutive_terms=2, term_cooloff_years=1)
        chair = fx.create_board_member(org["id"], "C", "c@x.org",
                                       skills=["GOVERNANCE"], officer_role="CHAIR")
        p1 = fx.create_board_member(org["id"], "P1", "p1@x.org", skills=["FINANCE"])
        t1 = fx.create_board_member(org["id"], "T1", "t1@x.org", skills=["LEGAL"])
        fx.elect_member(org["id"], chair["id"], start_date="2026-01-01T00:00:00Z")
        fx.elect_member(org["id"], p1["id"], start_date="2025-01-01T00:00:00Z")
        fx.elect_member(org["id"], t1["id"], start_date="2024-01-01T00:00:00Z")
        fx.elect_member(org["id"], t1["id"], start_date="2025-01-01T00:00:00Z")

        fx.sweep(org["id"])

        p1_after = th.validate_success(api.get_board_member(p1["id"], ADMIN))
        assert p1_after["status"] == "PAST", (
            f"chain 1 below cap 2 must complete to PAST, got {p1_after['status']}")
        assert p1_after["consecutive_terms_served"] == 1

        t1_after = th.validate_success(api.get_board_member(t1["id"], ADMIN))
        assert t1_after["status"] == "TERM_LIMITED_OUT", (
            f"adjacency-linked chain 2 == cap 2 must complete to TERM_LIMITED_OUT, got {t1_after['status']}")
        assert t1_after["consecutive_terms_served"] == 2

    def test_future_term_activated_by_sweep(self, api):
        """PRD §3.2: "A term whose `start_date` lies in the future is `SCHEDULED`;
        one whose start has been reached is `ACTIVE` immediately, and a term whose
        `end_date` has also already passed is swept to `COMPLETED` by the next
        compliance sweep."
        PRD §3.2: "Thereafter the sweep advances `SCHEDULED` terms to `ACTIVE` once
        the clock reaches the start date and completes `ACTIVE` terms at their end"

        Design: Corner/state_machines/future_term_activated_by_sweep
        """
        sc = fx.setup_org_with_board(num_directors=0, officers=("CHAIR",), ein="EIN-FT-2")
        np_id = sc["nonprofit"]["id"]
        member = fx.create_board_member(np_id, "M", "m@x.org", skills=["FINANCE"])
        term = fx.elect_member(np_id, member["id"], start_date="2027-01-01T00:00:00Z")
        assert term["status"] == "SCHEDULED", (
            f"future-dated term must be born SCHEDULED, got {term['status']}")

        fx.sweep(np_id)
        mid = th.validate_success(api.get_board_term(term["id"], ADMIN))
        assert mid["status"] == "SCHEDULED", (
            "sweep at the default clock 2026-08-01 must not activate a 2027 term")

        fx.set_clock("2027-01-02T00:00:00Z")
        fx.sweep(np_id)
        after = th.validate_success(api.get_board_term(term["id"], ADMIN))
        assert after["status"] == "ACTIVE", (
            f"term must flip ACTIVE once the clock passes start_date and a sweep runs, got {after['status']}")
        member_after = th.validate_success(api.get_board_member(member["id"], ADMIN))
        assert member_after["status"] == "ACTIVE"


class TestRecruitmentMatrixAndConsistency:
    def test_recruitment_matrix_reports_skill_gaps(self, api):
        """PRD §3.2: "The **recruitment matrix** is a computed read over the roster,
        available to every role: for each of the eight skill tags it reports how
        many `ACTIVE` members hold it (`by_skill`), which skills no `ACTIVE` member
        covers (`uncovered_skills`), the count of `ACTIVE` members
        (`active_members`), the adopted bylaws' `board_size`, and the resulting
        `open_seats` — the skills-based view of the same seat arithmetic the
        election gates enforce."

        Design: Corner/endpoints/recruitment_matrix_reports_skill_gaps
        """
        org = fx.create_nonprofit(name="O", ein="EIN-RM-1", receipts=1_000_000)
        fx.create_adopted_bylaws(org["id"], board_size=5)
        f = fx.create_board_member(org["id"], "F", "f@x.org", skills=["FINANCE"])
        l = fx.create_board_member(org["id"], "L", "l@x.org", skills=["LEGAL"])
        fx.create_board_member(org["id"], "M", "m@x.org",
                               skills=["MARKETING"])  # stays PROPOSED
        fx.elect_member(org["id"], f["id"], start_date="2026-01-01T00:00:00Z")
        fx.elect_member(org["id"], l["id"], start_date="2026-01-01T00:00:00Z")

        matrix = th.validate_success(api.get_recruitment_matrix(org["id"], ADMIN))
        assert matrix["active_members"] == 2
        assert matrix["board_size"] == 5
        assert matrix["open_seats"] == 3
        assert matrix["by_skill"]["FINANCE"] == 1
        assert matrix["by_skill"]["LEGAL"] == 1
        assert matrix["by_skill"]["MARKETING"] == 0, (
            "a PROPOSED nominee must not count toward skill coverage")
        assert sorted(matrix["uncovered_skills"]) == sorted(
            ["FUNDRAISING", "PROGRAM", "GOVERNANCE", "MARKETING", "TECHNOLOGY", "HR"])

    def test_immediate_read_after_write_visibility(self, api):
        """PRD §2.10: "The server maintains consistency across aggregates
        automatically: when one transition's side effects render another entity's
        state untenable, the dependent transition fires as part of the same
        operation, without any client request on the affected resource, and every
        resource mutated along the way has its `updated_at` refreshed and its
        `version` incremented per §2.5."
        PRD §3.2: "Election moves a `PROPOSED`, `PAST`, or `TERM_LIMITED_OUT` member
        to `ACTIVE` — an `ACTIVE` incumbent simply stays `ACTIVE` — and for a
        `TERM_LIMITED_OUT` member the new term restarts the chain at `chain_index`
        1."

        Design: Corner/consistency_model/immediate_read_after_write_visibility
        """
        org = fx.create_nonprofit(name="O", ein="EIN-IM-1", receipts=1_000_000)
        fx.create_adopted_bylaws(org["id"])
        member = fx.create_board_member(org["id"], "M", "m@x.org", skills=["FINANCE"])

        before = th.validate_success(api.get_board_member(member["id"], ADMIN))
        assert before["status"] == "PROPOSED"

        fx.elect_member(org["id"], member["id"], start_date="2026-01-01T00:00:00Z")
        after = th.validate_success(api.get_board_member(member["id"], ADMIN))
        assert after["status"] == "ACTIVE", (
            "the election side effect must be visible on the very next GET")

        data, meta = th.validate_paginated(api.list_board_members(
            ADMIN, params={"nonprofit_id": org["id"], "status": "ACTIVE"}))
        assert meta["total_count"] == 1
        assert data[0]["id"] == member["id"], (
            "the ACTIVE-filtered list must already contain the elected member")


class TestTermLimitReelectionCycle:
    """Difficulty: non_linear_state_machine / board_member_term_limit_reelection_cycle."""

    def _setup_term_limited_out_member(self, api):
        org = fx.create_nonprofit(name="Limit Org", ein="EIN-LIM-1")
        fx.create_adopted_bylaws(org["id"], term_length_years=1,
                                 max_consecutive_terms=1, term_cooloff_years=1,
                                 board_size=5)
        chair = fx.create_board_member(org["id"], "Chair", "c@x.org",
                                       skills=["GOVERNANCE"], officer_role="CHAIR")
        member = fx.create_board_member(org["id"], "M", "m@x.org", skills=["FINANCE"])
        fx.elect_member(org["id"], chair["id"], start_date="2026-01-01T00:00:00Z")
        first_term = fx.elect_member(org["id"], member["id"],
                                     start_date="2024-01-01T00:00:00Z")
        fx.sweep(org["id"])
        return org, member, first_term

    def test_term_completion_sweep_marks_member_term_limited_out(self, api):
        """PRD §3.2: "Thereafter the sweep advances `SCHEDULED` terms to `ACTIVE`
        once the clock reaches the start date and completes `ACTIVE` terms at their
        end; at completion, the member becomes `PAST` if still eligible for
        re-election (chain length below the cap) or `TERM_LIMITED_OUT` when the
        chain has reached the current bylaws' `max_consecutive_terms`, and either
        way the freed seat re-enters the open-seat pool."

        Design: Difficulty/non_linear_state_machine/board_member_term_limit_reelection_cycle
        """
        org, member, first_term = self._setup_term_limited_out_member(api)
        term_after = th.validate_success(api.get_board_term(first_term["id"], ADMIN))
        assert term_after["status"] == "COMPLETED"
        member_after = th.validate_success(api.get_board_member(member["id"], ADMIN))
        assert member_after["status"] == "TERM_LIMITED_OUT", (
            f"chain length 1 == max_consecutive_terms 1 must term-limit the member, got {member_after['status']}")
        assert member_after["consecutive_terms_served"] == 1

    def test_reelection_after_cooloff_restarts_chain(self, api):
        """PRD §3.2: "when the chain has reached `max_consecutive_terms`, the member
        is eligible only once the new term's `start_date` falls at least
        `term_cooloff_years` after the chain's latest `end_date`, with a start
        exactly cool-off-years after the chain end being eligible, and is otherwise
        rejected with `ERR_TERM_LIMIT_EXCEEDED`."
        PRD §3.2: "Election moves a `PROPOSED`, `PAST`, or `TERM_LIMITED_OUT` member
        to `ACTIVE` — an `ACTIVE` incumbent simply stays `ACTIVE` — and for a
        `TERM_LIMITED_OUT` member the new term restarts the chain at `chain_index`
        1."

        Design: Difficulty/non_linear_state_machine/board_member_term_limit_reelection_cycle
        """
        org, member, _ = self._setup_term_limited_out_member(api)
        # chain end 2025-01-01 + 1 year cool-off -> eligible exactly at 2026-01-01
        term2 = th.validate_success(api.create_board_term(
            th.create_term_payload(org["id"], member["id"],
                                   start_date="2026-01-01T00:00:00Z"), ADMIN), 201)
        assert term2["status"] == "ACTIVE"
        th.assert_instant_eq(term2["end_date"], "2027-01-01T00:00:00Z")
        assert term2["chain_index"] == 1, (
            "the 2-year gap broke the consecutive chain; the new term restarts at chain_index 1")
        member_after = th.validate_success(api.get_board_member(member["id"], ADMIN))
        assert member_after["status"] == "ACTIVE"
        assert member_after["consecutive_terms_served"] == 1


class TestCooloffBoundary:
    """Difficulty: boundary_precision_check / term_cooloff_exactly_elapsed_vs_one_day_early."""

    def _setup_cooled_member(self, api):
        org = fx.create_nonprofit(name="Cool Org", ein="EIN-COOL-1")
        fx.create_adopted_bylaws(org["id"], term_length_years=2,
                                 max_consecutive_terms=1, term_cooloff_years=1,
                                 board_size=5)
        chair = fx.create_board_member(org["id"], "Chair", "c@x.org",
                                       skills=["GOVERNANCE"], officer_role="CHAIR")
        member = fx.create_board_member(org["id"], "X", "x@x.org", skills=["FINANCE"])
        fx.elect_member(org["id"], chair["id"], start_date="2026-01-01T00:00:00Z")
        fx.elect_member(org["id"], member["id"], start_date="2024-01-01T00:00:00Z")
        fx.sweep(org["id"])
        member_after = th.validate_success(api.get_board_member(member["id"], ADMIN))
        assert member_after["status"] == "TERM_LIMITED_OUT"
        return org, member

    def test_cooloff_one_day_early_rejected(self, api):
        """PRD §3.2: "when the chain has reached `max_consecutive_terms`, the member
        is eligible only once the new term's `start_date` falls at least
        `term_cooloff_years` after the chain's latest `end_date`, with a start
        exactly cool-off-years after the chain end being eligible, and is otherwise
        rejected with `ERR_TERM_LIMIT_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/term_cooloff_exactly_elapsed_vs_one_day_early
        """
        org, member = self._setup_cooled_member(api)
        # chain end 2026-01-01 + 1 year = 2027-01-01; one day before is not eligible
        resp = api.create_board_term(
            th.create_term_payload(org["id"], member["id"],
                                   start_date="2026-12-31T00:00:00Z"), ADMIN)
        th.validate_error(resp, th.ApiErrorId.ERR_TERM_LIMIT_EXCEEDED)

    def test_cooloff_exactly_elapsed_is_eligible(self, api):
        """PRD §3.2: "when the chain has reached `max_consecutive_terms`, the member
        is eligible only once the new term's `start_date` falls at least
        `term_cooloff_years` after the chain's latest `end_date`, with a start
        exactly cool-off-years after the chain end being eligible, and is otherwise
        rejected with `ERR_TERM_LIMIT_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/term_cooloff_exactly_elapsed_vs_one_day_early
        """
        org, member = self._setup_cooled_member(api)
        term = th.validate_success(api.create_board_term(
            th.create_term_payload(org["id"], member["id"],
                                   start_date="2027-01-01T00:00:00Z"), ADMIN), 201)
        th.assert_board_term(term)
        assert term["status"] == "SCHEDULED", (
            f"start 2027-01-01 is after the default clock, got {term['status']}")
        th.assert_instant_eq(term["start_date"], "2027-01-01T00:00:00Z")
        member_after = th.validate_success(api.get_board_member(member["id"], ADMIN))
        assert member_after["status"] == "ACTIVE"


class TestTermOverlapSemantics:
    """Difficulty: resource_temporal_overlap / board_term_half_open_adjacency_allowed."""

    def _setup_incumbent(self, api):
        org = fx.create_nonprofit(name="Overlap Org", ein="EIN-OVL-1")
        fx.create_adopted_bylaws(org["id"], term_length_years=2,
                                 max_consecutive_terms=3, board_size=5)
        chair = fx.create_board_member(org["id"], "Chair", "c@x.org",
                                       skills=["GOVERNANCE"], officer_role="CHAIR")
        member = fx.create_board_member(org["id"], "A", "a@x.org", skills=["FINANCE"])
        fx.elect_member(org["id"], chair["id"], start_date="2026-01-01T00:00:00Z")
        term1 = fx.elect_member(org["id"], member["id"],
                                start_date="2026-01-01T00:00:00Z")
        th.assert_instant_eq(term1["end_date"], "2028-01-01T00:00:00Z")
        return org, member

    def test_term_interior_start_rejected_as_overlap(self, api):
        """PRD §2.8: "A newly elected term may begin on the exact day the member's
        previous term ends — strict adjacency continues a consecutive-service chain
        and is always allowed — while any true overlap with the member's existing
        non-`VACATED` terms is rejected with `ERR_TERM_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/board_term_half_open_adjacency_allowed
        """
        org, member = self._setup_incumbent(api)
        # current term occupies [2026-01-01, 2028-01-01); 2027-06-01 is inside it
        resp = api.create_board_term(
            th.create_term_payload(org["id"], member["id"],
                                   start_date="2027-06-01T00:00:00Z"), ADMIN)
        th.validate_error(resp, th.ApiErrorId.ERR_TERM_OVERLAP)

    def test_term_adjacent_start_extends_chain(self, api):
        """PRD §2.8: "A newly elected term may begin on the exact day the member's
        previous term ends — strict adjacency continues a consecutive-service chain
        and is always allowed — while any true overlap with the member's existing
        non-`VACATED` terms is rejected with `ERR_TERM_OVERLAP`."
        PRD §3.2: "The chain's length becomes the member's
        `consecutive_terms_served`, and the new term's `chain_index` records its
        1-based position in that chain."

        Design: Difficulty/resource_temporal_overlap/board_term_half_open_adjacency_allowed
        """
        org, member = self._setup_incumbent(api)
        term2 = th.validate_success(api.create_board_term(
            th.create_term_payload(org["id"], member["id"],
                                   start_date="2028-01-01T00:00:00Z"), ADMIN), 201)
        assert term2["status"] == "SCHEDULED"
        assert term2["chain_index"] == 2, "strict adjacency continues the chain"
        th.assert_instant_eq(term2["end_date"], "2030-01-01T00:00:00Z")
        member_after = th.validate_success(api.get_board_member(member["id"], ADMIN))
        assert member_after["consecutive_terms_served"] == 2


class TestOpenSeatsInvariant:
    """Difficulty: compensating_invariant / open_seats_conserved_across_elect_and_resign."""

    def _setup_four_active(self, api):
        org = fx.create_nonprofit(name="Seats Org", ein="EIN-SEAT-1")
        fx.create_adopted_bylaws(org["id"], board_size=5)
        members = []
        specs = [("Chair", "CHAIR", ["GOVERNANCE"]), ("D1", None, ["FINANCE"]),
                 ("D2", None, ["LEGAL"]), ("D3", None, ["PROGRAM"])]
        for i, (name, officer, skills) in enumerate(specs):
            m = fx.create_board_member(org["id"], name, f"m{i}@x.org",
                                       skills=skills, officer_role=officer)
            fx.elect_member(org["id"], m["id"], start_date="2026-01-01T00:00:00Z")
            members.append(m)
        d4 = fx.create_board_member(org["id"], "D4", "d4@x.org", skills=["HR"])
        d5 = fx.create_board_member(org["id"], "D5", "d5@x.org", skills=["MARKETING"])
        return org, members, d4, d5

    def _open_seats(self, api, np_id):
        matrix = th.validate_success(api.get_recruitment_matrix(np_id, ADMIN))
        return matrix["open_seats"]

    def test_election_decrements_open_seats_and_saturates(self, api):
        """PRD §3.2: "Finally, unless the member is currently `ACTIVE` — incumbent
        re-election does not consume a second seat — at least one open seat must
        exist, else `ERR_NO_SEATS_AVAILABLE`."
        PRD §3.2: "The open-seat count is the `board_size` of the adopted bylaws
        minus the count of `ACTIVE` members; electing a member decrements it by
        exactly 1 and that member's later resignation or removal increments it by
        exactly 1, so any elect-then-vacate sequence leaves the count identical to
        its pre-sequence value."

        Design: Difficulty/compensating_invariant/open_seats_conserved_across_elect_and_resign
        """
        org, _members, d4, d5 = self._setup_four_active(api)
        assert self._open_seats(api, org["id"]) == 1, "board_size 5 minus 4 ACTIVE"

        fx.elect_member(org["id"], d4["id"], start_date="2026-01-01T00:00:00Z")
        assert self._open_seats(api, org["id"]) == 0, "the fifth seat is now taken"

        resp = api.create_board_term(
            th.create_term_payload(org["id"], d5["id"],
                                   start_date="2026-01-01T00:00:00Z"), ADMIN)
        th.validate_error(resp, th.ApiErrorId.ERR_NO_SEATS_AVAILABLE)

    def test_resignation_restores_open_seats(self, api):
        """PRD §3.2: "The open-seat count is the `board_size` of the adopted bylaws
        minus the count of `ACTIVE` members; electing a member decrements it by
        exactly 1 and that member's later resignation or removal increments it by
        exactly 1, so any elect-then-vacate sequence leaves the count identical to
        its pre-sequence value."

        Design: Difficulty/compensating_invariant/open_seats_conserved_across_elect_and_resign
        """
        org, _members, d4, _d5 = self._setup_four_active(api)
        seats0 = self._open_seats(api, org["id"])
        elected = fx.elect_member(org["id"], d4["id"], start_date="2026-01-01T00:00:00Z")
        assert elected["status"] == "ACTIVE"
        assert self._open_seats(api, org["id"]) == seats0 - 1

        resigned = th.validate_success(api.resign_member(d4["id"], ADMIN))
        assert resigned["status"] == "RESIGNED"
        assert self._open_seats(api, org["id"]) == seats0, (
            "elect-then-vacate must leave open_seats identical to its pre-sequence value")


class TestElectionPriorityPair:
    """Difficulty: priority_pair_validation_conflict / term_limit_constraint_beats_overlap_temporal."""

    def _setup_term_limited_member(self, api):
        org = fx.create_nonprofit(name="Prio2 Org", ein="EIN-PRIO-2")
        fx.create_adopted_bylaws(org["id"], term_length_years=2,
                                 max_consecutive_terms=1, term_cooloff_years=1,
                                 board_size=5)
        chair = fx.create_board_member(org["id"], "Chair", "c@x.org",
                                       skills=["GOVERNANCE"], officer_role="CHAIR")
        member = fx.create_board_member(org["id"], "X", "x@x.org", skills=["FINANCE"])
        fx.elect_member(org["id"], chair["id"], start_date="2026-01-01T00:00:00Z")
        fx.elect_member(org["id"], member["id"], start_date="2024-01-01T00:00:00Z")
        fx.sweep(org["id"])
        return org, member

    def test_term_limit_error_precedes_overlap_error(self, api):
        """PRD §2.7: "15. **Election eligibility.** Member status, term-limit chain,
        and seat availability, evaluated in that internal order:
        `ERR_MEMBER_NOT_ELIGIBLE`, then `ERR_TERM_LIMIT_EXCEEDED`, then
        `ERR_NO_SEATS_AVAILABLE` (409)."
        PRD §2.7: "18. **Interval rules.** `ERR_TERM_OVERLAP`, `ERR_MEETING_OVERLAP`,
        `ERR_COVERAGE_GAP`, `ERR_POLICY_OVERLAP` (409)."
        PRD §2.7: "When a request fails several rules at once, the error the caller
        receives is determined by a fixed order of precedence, evaluated from first
        to last:"

        Design: Difficulty/priority_pair_validation_conflict/term_limit_constraint_beats_overlap_temporal
        """
        org, member = self._setup_term_limited_member(api)
        # 2025-06-01 fails the cool-off (chain end 2026-01-01 + 1y = 2027-01-01)
        # AND [2025-06-01, 2027-06-01) overlaps the prior [2024-01-01, 2026-01-01) term
        resp = api.create_board_term(
            th.create_term_payload(org["id"], member["id"],
                                   start_date="2025-06-01T00:00:00Z"), ADMIN)
        th.validate_error(resp, th.ApiErrorId.ERR_TERM_LIMIT_EXCEEDED)

    def test_term_limit_rejection_creates_no_term(self, api):
        """PRD §2.7: "15. **Election eligibility.** Member status, term-limit chain,
        and seat availability, evaluated in that internal order:
        `ERR_MEMBER_NOT_ELIGIBLE`, then `ERR_TERM_LIMIT_EXCEEDED`, then
        `ERR_NO_SEATS_AVAILABLE` (409)."

        Design: Difficulty/priority_pair_validation_conflict/term_limit_constraint_beats_overlap_temporal
        """
        org, member = self._setup_term_limited_member(api)
        resp = api.create_board_term(
            th.create_term_payload(org["id"], member["id"],
                                   start_date="2025-06-01T00:00:00Z"), ADMIN)
        th.validate_error(resp, th.ApiErrorId.ERR_TERM_LIMIT_EXCEEDED)

        data, meta = th.validate_paginated(api.list_board_terms(
            ADMIN, params={"board_member_id": member["id"]}))
        assert meta["total_count"] == 1, (
            f"the rejected election must not persist a term, found {meta['total_count']}")
        member_after = th.validate_success(api.get_board_member(member["id"], ADMIN))
        assert member_after["status"] == "TERM_LIMITED_OUT"
