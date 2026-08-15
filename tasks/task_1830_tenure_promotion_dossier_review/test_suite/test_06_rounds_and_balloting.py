"""Review rounds and balloting: open/close/certify gates, SoD, quorum and
tally arithmetic, the reopen cycle, sealing, and ballot OCC (PRD §2.9, §3.5,
§3.6)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_member,
    assert_decimal_eq,
    build_committee,
    cast_ballot,
    create_committee,
    certify_round,
    close_voting,
    make_committee_chair_headers,
    make_committee_voter_headers,
    open_round,
    read_case,
    read_round,
    setup_department_stage_case,
    advance_case,
    validate_error,
    validate_paginated,
    validate_success,
)

PO_HEADERS = TEST_USERS["provost_creator_headers"]
READER_HEADERS = TEST_USERS["reader_headers"]


def test_round_certify_gating_matrix(api, reader_headers):
    """PRD §3.6: "The round must be in `TALLYING` (`ERR_INVALID_ROUND_STATE`)".
    PRD §3.6: "Next, quorum must be met per §2.9, otherwise
    `ERR_QUORUM_NOT_MET`."
    PRD §2.9: "Quorum is considered met only when the round's `votes_cast` is at
    least `quorum_required` and at least one eligible voter remains."

    Design: Corner/state_machines/round_certify_gating_matrix
    """
    ctx = setup_department_stage_case("E9104", member_count=4, email_prefix="gm")
    round_id = ctx["round"]["id"]
    chair_id = ctx["committee_ctx"]["chair"]["id"]
    members = ctx["committee_ctx"]["members"]
    open_round(round_id, chair_id)
    cast_ballot(round_id, members[0]["id"], "YES")
    cast_ballot(round_id, members[1]["id"], "NO")

    # Certify while still VOTING_OPEN: the state gate fires.
    err_state = api.certify_round(
        round_id,
        {"recommendation": "SUPPORT", "letter_text": "Too early."},
        make_committee_chair_headers(chair_id),
    )
    validate_error(err_state, ApiErrorId.ERR_INVALID_ROUND_STATE)

    # M = 5 (chair + 4 members) -> quorum_required = ceil(0.5 * 5) = 3, but
    # only 2 ballots are cast.
    close_voting(round_id, chair_id)
    err_quorum = api.certify_round(
        round_id,
        {"recommendation": "SUPPORT", "letter_text": "Still short."},
        make_committee_chair_headers(chair_id),
    )
    validate_error(err_quorum, ApiErrorId.ERR_QUORUM_NOT_MET)

    round_after = validate_success(api.get_round(round_id, reader_headers))
    assert round_after["status"] == "TALLYING"
    assert round_after["quorum_met"] is False


def test_sod_certifier_voted_fires_when_state_ok(api, reader_headers):
    """PRD §2.7: "The certifying chair must not hold any non-retracted ballot in
    the round being certified — not even a `RECUSE` ballot; a violation is
    rejected with `ERR_SOD_CERTIFIER_VOTED`."

    Design: Corner/state_machines/sod_certifier_voted_fires_when_state_ok
    """
    ctx = setup_department_stage_case("E9105", member_count=2, email_prefix="sd")
    round_id = ctx["round"]["id"]
    chair_id = ctx["committee_ctx"]["chair"]["id"]
    member_id = ctx["committee_ctx"]["members"][0]["id"]
    open_round(round_id, chair_id)
    # Chairs may vote; the SoD rule only blocks certifying while holding one.
    cast_ballot(round_id, chair_id, "YES")
    cast_ballot(round_id, member_id, "YES")
    close_voting(round_id, chair_id)

    err = api.certify_round(
        round_id,
        {"recommendation": "SUPPORT", "letter_text": "Conflicted."},
        make_committee_chair_headers(chair_id),
    )
    validate_error(err, ApiErrorId.ERR_SOD_CERTIFIER_VOTED)
    round_after = validate_success(api.get_round(round_id, reader_headers))
    assert round_after["status"] == "TALLYING", (
        "The state gate passed; only the safety gate fired"
    )


class TestCertifyStateBeforeSafetySod:
    def _setup_chair_holding_ballot(self):
        ctx = setup_department_stage_case("E1100", member_count=2, email_prefix="d")
        round_id = ctx["round"]["id"]
        chair_id = ctx["committee_ctx"]["chair"]["id"]
        open_round(round_id, chair_id)
        cast_ballot(round_id, chair_id, "YES")
        cast_ballot(round_id, ctx["committee_ctx"]["members"][0]["id"], "YES")
        return ctx, round_id, chair_id

    def test_certify_in_voting_open_reports_state_not_sod(self, api):
        """PRD §2.12: "When a request would fail several checks, the error
        surfaced is the one from the earliest applicable priority. Priorities
        are evaluated in ascending order:"
        PRD §2.12: "the corresponding member of the invalid-state family —
        `ERR_INVALID_ITEM_STATE`, `ERR_INVALID_INVITATION_STATE`,
        `ERR_INVALID_ROUND_STATE`, `ERR_INVALID_EXTENSION_STATE`,
        `ERR_INVALID_MIDTERM_STATE`, `ERR_INVALID_APPEAL_STATE`, or
        `ERR_INVALID_VOTE_STATE` (all HTTP 409)"
        PRD §2.12: "The four rules of §2.7 are enforced here:
        `ERR_SOD_CERTIFIER_VOTED`, `ERR_SOD_DECISION_BY_CASE_CREATOR`,
        `ERR_RECUSAL_IRREVERSIBLE` (all HTTP 409), and
        `ERR_ARMS_LENGTH_VIOLATION` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/certify_state_before_safety_sod
        """
        _ctx, round_id, chair_id = self._setup_chair_holding_ballot()
        # Both fail: the round is not TALLYING (state) and the certifying chair
        # holds a ballot (safety). The state error must win.
        err = api.certify_round(
            round_id,
            {"recommendation": "SUPPORT", "letter_text": "Premature."},
            make_committee_chair_headers(chair_id),
        )
        validate_error(err, ApiErrorId.ERR_INVALID_ROUND_STATE)

    def test_failed_certify_leaves_round_untouched(self, api, reader_headers):
        """PRD §3.6: "Certification stamps `certified_at`, computes the round's
        `yes_percentage` and `passed` verdict, and moves the round from
        `TALLYING` to `COMPLETED`."

        Design: Difficulty/priority_pair_validation_conflict/certify_state_before_safety_sod
        """
        _ctx, round_id, chair_id = self._setup_chair_holding_ballot()
        api.certify_round(
            round_id,
            {"recommendation": "SUPPORT", "letter_text": "Premature."},
            make_committee_chair_headers(chair_id),
        )
        round_after = validate_success(api.get_round(round_id, reader_headers))
        assert round_after["status"] == "VOTING_OPEN", (
            "A rejected certification must not move the round"
        )
        assert round_after["certified_at"] is None
        assert round_after["passed"] is None


def test_advance_and_close_voting_gates_from_scheduled(api, reader_headers):
    """PRD §3.6: "From `DEPT_COMMITTEE` it requires the case's latest department
    round by `created_at` to be `COMPLETED` (`ERR_ROUND_NOT_CERTIFIED`)".
    PRD §3.6: "the chair closes voting, moving the round from `VOTING_OPEN` to
    `TALLYING`."

    Design: Corner/state_machines/advance_and_close_voting_gates_from_scheduled
    """
    ctx = setup_department_stage_case("E9107", member_count=1, email_prefix="av")
    round_id = ctx["round"]["id"]
    chair_id = ctx["committee_ctx"]["chair"]["id"]
    case_id = ctx["case"]["id"]

    err_close = api.close_voting(round_id, make_committee_chair_headers(chair_id))
    validate_error(err_close, ApiErrorId.ERR_INVALID_ROUND_STATE)

    err_advance = api.advance_stage(case_id, PO_HEADERS)
    validate_error(err_advance, ApiErrorId.ERR_ROUND_NOT_CERTIFIED)

    assert read_round(round_id)["status"] == "SCHEDULED"
    assert read_case(case_id)["stage"] == "DEPT_COMMITTEE"


def test_ballot_lifecycle_negatives(api, reader_headers):
    """PRD §3.5: "no member may hold more than one non-retracted ballot of any
    kind in the same round, otherwise `ERR_DUPLICATE_BALLOT`."
    PRD §3.5: "Patch or retraction attempted on a vote that is not `CAST` is
    rejected with `ERR_INVALID_VOTE_STATE`."
    PRD §2.7: "Recusal is irrevocable through the ballot-change path: neither
    the current nor the new ballot of a change request may be `RECUSE`,
    otherwise the change is rejected with `ERR_RECUSAL_IRREVERSIBLE` — a member
    who wishes to leave a recusal retracts the ballot and casts a fresh one."

    Design: Corner/state_machines/ballot_lifecycle_negatives
    """
    ctx = setup_department_stage_case("E9108", member_count=2, email_prefix="bl")
    round_id = ctx["round"]["id"]
    chair_id = ctx["committee_ctx"]["chair"]["id"]
    m1, m2 = ctx["committee_ctx"]["members"]
    open_round(round_id, chair_id)

    vote1 = cast_ballot(round_id, m1["id"], "YES")
    # One active ballot per (round, member).
    err_dup = api.create_vote(
        {"round_id": round_id, "ballot": "NO"},
        make_committee_voter_headers(m1["id"]),
    )
    validate_error(err_dup, ApiErrorId.ERR_DUPLICATE_BALLOT)

    # A retracted vote can no longer be patched (re-read the current version so
    # only the lifecycle-state check can fail).
    validate_success(
        api.retract_vote(vote1["id"], make_committee_voter_headers(m1["id"]))
    )
    fresh = validate_success(api.get_vote(vote1["id"], reader_headers))
    err_patch = api.patch_vote(
        vote1["id"],
        {"ballot": "NO", "expected_vote_version": fresh["version"]},
        make_committee_voter_headers(m1["id"]),
    )
    validate_error(err_patch, ApiErrorId.ERR_INVALID_VOTE_STATE)

    # RECUSE ballots can only be retracted, never edited.
    vote2 = cast_ballot(round_id, m2["id"], "RECUSE")
    err_recuse = api.patch_vote(
        vote2["id"],
        {"ballot": "YES", "expected_vote_version": vote2["version"]},
        make_committee_voter_headers(m2["id"]),
    )
    validate_error(err_recuse, ApiErrorId.ERR_RECUSAL_IRREVERSIBLE)

    v1_after = validate_success(api.get_vote(vote1["id"], reader_headers))
    v2_after = validate_success(api.get_vote(vote2["id"], reader_headers))
    assert v1_after["status"] == "RETRACTED"
    assert v2_after["status"] == "CAST" and v2_after["ballot"] == "RECUSE"


def test_member_eligibility_negatives(api, reader_headers):
    """PRD §3.5: "Casting requires the voter to be an active member of the
    round's committee whose service window covers `opened_at`, otherwise
    `ERR_VOTER_NOT_ELIGIBLE`, and no member may hold more than one non-retracted
    ballot of any kind in the same round, otherwise `ERR_DUPLICATE_BALLOT`."
    PRD §3.5: "Deactivating a member sets `is_active` to false; inactive members
    are excluded from every eligibility count and cannot vote."

    Design: Corner/state_machines/member_eligibility_negatives
    """
    ctx = setup_department_stage_case("E9109", member_count=1, email_prefix="me")
    round_id = ctx["round"]["id"]
    chair_id = ctx["committee_ctx"]["chair"]["id"]
    member_c = ctx["committee_ctx"]["members"][0]
    open_round(round_id, chair_id)

    # Deactivated after the round opened.
    validate_success(api.deactivate_member(member_c["id"], PO_HEADERS))
    err_c = api.create_vote(
        {"round_id": round_id, "ballot": "YES"},
        make_committee_voter_headers(member_c["id"]),
    )
    validate_error(err_c, ApiErrorId.ERR_VOTER_NOT_ELIGIBLE)

    # Service window starts after opened_at (2026-08-01).
    member_d = add_member(
        ctx["committee_ctx"]["committee"]["id"],
        "ME D",
        "med@u.edu",
        service_start="2026-09-01",
        service_end="2026-12-31",
    )
    err_d = api.create_vote(
        {"round_id": round_id, "ballot": "YES"},
        make_committee_voter_headers(member_d["id"]),
    )
    validate_error(err_d, ApiErrorId.ERR_VOTER_NOT_ELIGIBLE)

    round_after = validate_success(api.get_round(round_id, reader_headers))
    assert round_after["votes_cast"] == 0


def test_abstain_counts_for_quorum_not_percentage(api):
    """PRD §2.9: "Abstentions count toward votes cast but never toward the
    yes-percentage denominator."
    PRD §3.6: "`yes_percentage` is the round's `yes_count` divided by the sum of
    `yes_count` and `no_count`, rounded half-up to four decimal places".

    Design: Corner/calculations/abstain_counts_for_quorum_not_percentage
    """
    ctx = setup_department_stage_case("E9205", member_count=3, email_prefix="ab")
    round_id = ctx["round"]["id"]
    chair_id = ctx["committee_ctx"]["chair"]["id"]
    members = ctx["committee_ctx"]["members"]
    open_round(round_id, chair_id)
    cast_ballot(round_id, members[0]["id"], "YES")
    cast_ballot(round_id, members[1]["id"], "ABSTAIN")
    cast_ballot(round_id, members[2]["id"], "ABSTAIN")
    close_voting(round_id, chair_id)

    certified = certify_round(round_id, chair_id, letter_text="Abstention-heavy.")
    assert certified["votes_cast"] == 3, "ABSTAIN counts toward turnout"
    assert certified["abstain_count"] == 2
    assert_decimal_eq(certified["yes_percentage"], 1.0, "yes_percentage")
    assert certified["passed"] is True


class TestQuorumExactlyMet:
    def _setup_three_ballots(self, employee_id):
        ctx = setup_department_stage_case(employee_id, member_count=4, email_prefix="qm")
        round_id = ctx["round"]["id"]
        chair_id = ctx["committee_ctx"]["chair"]["id"]
        members = ctx["committee_ctx"]["members"]
        open_round(round_id, chair_id)
        cast_ballot(round_id, members[0]["id"], "YES")
        cast_ballot(round_id, members[1]["id"], "YES")
        cast_ballot(round_id, members[2]["id"], "NO")
        close_voting(round_id, chair_id)
        return ctx, round_id, chair_id

    def test_certify_succeeds_when_votes_cast_equals_quorum(self, api):
        """PRD §2.9: "Quorum is considered met only when the round's
        `votes_cast` is at least `quorum_required` and at least one eligible
        voter remains."
        PRD §2.9: "The number of voters required for quorum, `quorum_required`,
        is the committee's `quorum_fraction` multiplied by the round's
        `eligible_voter_count`, rounded up to a whole number."

        Design: Difficulty/boundary_precision_check/quorum_exactly_met_certify_succeeds
        """
        _ctx, round_id, chair_id = self._setup_three_ballots("E1400")
        # M = 5 -> quorum_required = ceil(0.5 * 5) = 3; votes_cast == 3 meets it.
        certified = certify_round(round_id, chair_id, letter_text="Quorum exact.")
        assert certified["status"] == "COMPLETED"

    def test_quorum_boundary_fields(self, api):
        """PRD §2.9: "Quorum is considered met only when the round's
        `votes_cast` is at least `quorum_required` and at least one eligible
        voter remains."

        Design: Difficulty/boundary_precision_check/quorum_exactly_met_certify_succeeds
        """
        _ctx, round_id, chair_id = self._setup_three_ballots("E1401")
        certified = certify_round(round_id, chair_id, letter_text="Quorum exact.")
        assert certified["votes_cast"] == 3
        assert certified["quorum_required"] == 3
        assert certified["quorum_met"] is True
        assert certified["passed"] is True
        assert_decimal_eq(certified["yes_percentage"], 0.6667, "yes_percentage")


class TestVoteTallyDualVariant:
    BALLOTS = ["YES", "YES", "YES", "NO", "ABSTAIN", "ABSTAIN"]

    def _certify_with_rule(self, employee_id, pass_rule):
        ctx = setup_department_stage_case(
            employee_id, member_count=6, pass_rule=pass_rule, email_prefix=employee_id.lower()
        )
        round_id = ctx["round"]["id"]
        chair_id = ctx["committee_ctx"]["chair"]["id"]
        members = ctx["committee_ctx"]["members"]
        open_round(round_id, chair_id)
        for member, ballot in zip(members, self.BALLOTS):
            cast_ballot(round_id, member["id"], ballot)
        close_voting(round_id, chair_id)
        return certify_round(round_id, chair_id)

    def test_strict_majority_of_cast_passes_with_identical_ballots(self, api):
        """PRD §3.6: "Under `STRICT_MAJORITY_OF_CAST`, the round passes when the
        yes-share of cast yes-plus-no ballots is strictly greater than one half —
        an exact tie fails."
        PRD §3.6: "Identical ballots can diverge under the two rules: with six
        eligible voters, three `YES`, one `NO`, and two `ABSTAIN`, the strict
        rule passes at 0.75 while the supermajority rule fails at 0.50 against
        its 0.6667 threshold."

        Design: Difficulty/dual_variant_calc/vote_tally_strict_vs_supermajority_diverge
        """
        certified = self._certify_with_rule("E100", "STRICT_MAJORITY_OF_CAST")
        assert certified["status"] == "COMPLETED"
        assert certified["passed"] is True, "STRICT: 3/4 = 0.75 > 0.5 passes"
        assert_decimal_eq(certified["yes_percentage"], 0.75, "yes_percentage")

    def test_supermajority_of_entitled_fails_with_identical_ballots(self, api):
        """PRD §3.6: "Under `SUPERMAJORITY_OF_ENTITLED`, the round passes when
        `yes_count` divided by `eligible_voter_count` is at least two thirds —
        an exact two-thirds passes — so recusals shrink the denominator while
        abstentions and non-voters count against the motion."
        PRD §3.6: "Identical ballots can diverge under the two rules: with six
        eligible voters, three `YES`, one `NO`, and two `ABSTAIN`, the strict
        rule passes at 0.75 while the supermajority rule fails at 0.50 against
        its 0.6667 threshold."

        Design: Difficulty/dual_variant_calc/vote_tally_strict_vs_supermajority_diverge
        """
        certified = self._certify_with_rule("E200", "SUPERMAJORITY_OF_ENTITLED")
        assert certified["status"] == "COMPLETED"
        assert certified["passed"] is False, (
            "SUPERMAJORITY: 3/6 = 0.50 is below the 2/3 threshold"
        )
        assert_decimal_eq(certified["yes_percentage"], 0.75, "yes_percentage")


class TestRoundReopenRecountCycle:
    def _setup_certified_round(self, employee_id):
        ctx = setup_department_stage_case(employee_id, member_count=3, email_prefix="rv")
        round_id = ctx["round"]["id"]
        chair_id = ctx["committee_ctx"]["chair"]["id"]
        members = ctx["committee_ctx"]["members"]
        open_round(round_id, chair_id)
        vote1 = cast_ballot(round_id, members[0]["id"], "YES")
        cast_ballot(round_id, members[1]["id"], "YES")
        cast_ballot(round_id, members[2]["id"], "NO")
        close_voting(round_id, chair_id)
        certified = certify_round(round_id, chair_id, letter_text="First letter.")
        return ctx, round_id, chair_id, members, vote1, certified

    def test_reopen_and_repatch_flips_certified_verdict(self, api, reader_headers):
        """PRD §3.6: "While the case's stage still matches the round's level and
        the round remains the case's latest round at its level by `created_at`,
        the chair may reopen a `COMPLETED` round, moving it back to
        `VOTING_OPEN`".
        PRD §3.6: "Certification stamps `certified_at`, computes the round's
        `yes_percentage` and `passed` verdict, and moves the round from
        `TALLYING` to `COMPLETED`."

        Design: Difficulty/non_linear_state_machine/round_reopen_recount_cycle
        """
        ctx, round_id, chair_id, members, vote1, certified = (
            self._setup_certified_round("E800")
        )
        assert certified["passed"] is True
        assert_decimal_eq(certified["yes_percentage"], 0.6667, "first yes_percentage")

        reopened = validate_success(
            api.reopen_round(round_id, make_committee_chair_headers(chair_id))
        )
        assert reopened["status"] == "VOTING_OPEN"

        fresh_vote = validate_success(api.get_vote(vote1["id"], reader_headers))
        patched = validate_success(
            api.patch_vote(
                vote1["id"],
                {"ballot": "NO", "expected_vote_version": fresh_vote["version"]},
                make_committee_voter_headers(members[0]["id"]),
            )
        )
        assert patched["ballot"] == "NO"

        close_voting(round_id, chair_id)
        certified2 = certify_round(
            round_id, chair_id, recommendation="OPPOSE", letter_text="Second letter."
        )
        assert certified2["passed"] is False
        assert_decimal_eq(certified2["yes_percentage"], 0.3333, "second yes_percentage")
        assert read_case(ctx["case"]["id"])["stage"] == "DEPT_COMMITTEE", (
            "Certification never auto-advances the case"
        )

    def test_reopen_clears_certification_fields(self, api, reader_headers):
        """PRD §3.6: "Reopening clears `certified_at`, `passed`,
        `yes_percentage`, `recommendation`, and `letter_text` to null, leaves all
        non-retracted votes in `CAST`, and recomputes the tallies."

        Design: Difficulty/non_linear_state_machine/round_reopen_recount_cycle
        """
        _ctx, round_id, chair_id, _members, _vote1, _certified = (
            self._setup_certified_round("E801")
        )
        validate_success(
            api.reopen_round(round_id, make_committee_chair_headers(chair_id))
        )
        round_after = validate_success(api.get_round(round_id, reader_headers))
        assert round_after["status"] == "VOTING_OPEN"
        for field in ("certified_at", "passed", "yes_percentage",
                      "recommendation", "letter_text"):
            assert round_after[field] is None, f"{field} must be cleared on reopen"

        votes, _meta = validate_paginated(
            api.list_votes(reader_headers, {"round_id": round_id})
        )
        assert all(v["status"] == "CAST" for v in votes), (
            "Non-retracted votes stay CAST through the reopen"
        )


def test_reopen_after_advance_returns_sealed(api, reader_headers):
    """PRD §3.6: "a case that has advanced seals the round against both opening
    and reopening with `ERR_ROUND_SEALED`".

    Design: Corner/state_machines/reopen_after_advance_returns_sealed
    """
    ctx = setup_department_stage_case("E9103", member_count=1, email_prefix="sl")
    case_id = ctx["case"]["id"]
    round_id = ctx["round"]["id"]
    chair_id = ctx["committee_ctx"]["chair"]["id"]
    open_round(round_id, chair_id)
    cast_ballot(round_id, ctx["committee_ctx"]["members"][0]["id"], "YES")
    close_voting(round_id, chair_id)
    certify_round(round_id, chair_id)

    # Advancing requires an eligible COLLEGE committee.
    build_committee("COLLEGE", "ENG", 1, email_prefix="csl")
    advance_case(case_id)

    err = api.reopen_round(round_id, make_committee_chair_headers(chair_id))
    validate_error(err, ApiErrorId.ERR_ROUND_SEALED)
    round_after = validate_success(api.get_round(round_id, reader_headers))
    assert round_after["status"] == "COMPLETED"
    assert read_case(case_id)["stage"] == "COLLEGE_COMMITTEE"


def test_occ_vote_patch_stale_version(api, reader_headers):
    """PRD §2.11: "Changing a cast ballot requires the non-optional field
    `expected_vote_version`, carrying the client's last observed `version` of
    that vote; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412),
    forcing the client to re-read the vote and resubmit against the fresh
    version rather than silently re-applying a change."
    PRD §3.5: "a successful change increments the vote's `version` by one".

    Design: Corner/cross_cutting_layers/occ_vote_patch_stale_version
    """
    ctx = setup_department_stage_case("E9602", member_count=1, email_prefix="ov2")
    round_id = ctx["round"]["id"]
    chair_id = ctx["committee_ctx"]["chair"]["id"]
    member_id = ctx["committee_ctx"]["members"][0]["id"]
    open_round(round_id, chair_id)
    vote = cast_ballot(round_id, member_id, "YES")
    snapshot_version = vote["version"]

    patched = validate_success(
        api.patch_vote(
            vote["id"],
            {"ballot": "NO", "expected_vote_version": snapshot_version},
            make_committee_voter_headers(member_id),
        )
    )
    assert patched["ballot"] == "NO"
    assert patched["version"] == snapshot_version + 1, (
        "A successful ballot change increments the vote version by one"
    )

    replayed = api.patch_vote(
        vote["id"],
        {"ballot": "ABSTAIN", "expected_vote_version": snapshot_version},
        make_committee_voter_headers(member_id),
    )
    validate_error(replayed, ApiErrorId.ERR_STALE_VERSION)

    vote_after = validate_success(api.get_vote(vote["id"], reader_headers))
    assert vote_after["ballot"] == "NO", "The stale retry must leave no drift"


class TestRecuseRetractElectorateInvariant:
    def _setup_open_round(self, employee_id):
        ctx = setup_department_stage_case(employee_id, member_count=4, email_prefix="rf")
        round_id = ctx["round"]["id"]
        chair_id = ctx["committee_ctx"]["chair"]["id"]
        open_round(round_id, chair_id)
        return ctx, round_id

    def test_recuse_shrinks_electorate_and_quorum(self, api):
        """PRD §2.9: "Recusals shrink the eligible electorate: each
        non-retracted `RECUSE` ballot reduces `eligible_voter_count` by one, and
        `quorum_required` is recomputed alongside it, while recusal ballots never
        count as votes cast."

        Design: Difficulty/compensating_invariant/recuse_retract_preserves_round_electorate
        """
        ctx, round_id = self._setup_open_round("E2000")
        member_id = ctx["committee_ctx"]["members"][0]["id"]

        baseline = read_round(round_id)
        assert baseline["active_member_count"] == 5  # chair + 4 members
        assert baseline["eligible_voter_count"] == 5
        assert baseline["quorum_required"] == 3
        assert baseline["votes_cast"] == 0

        cast_ballot(round_id, member_id, "RECUSE")
        after = read_round(round_id)
        assert after["eligible_voter_count"] == 4
        assert after["quorum_required"] == 2
        assert after["recusal_count"] == 1
        assert after["votes_cast"] == 0, "RECUSE never counts as a cast ballot"

    def test_retract_recuse_restores_electorate_baseline(self, api, reader_headers):
        """PRD §3.5: "Retracting a `RECUSE` ballot therefore re-includes the
        member in the eligible electorate."
        PRD §3.5: "A member may instead retract, moving the vote from `CAST` to
        its terminal `RETRACTED` status with `retracted_at` stamped."

        Design: Difficulty/compensating_invariant/recuse_retract_preserves_round_electorate
        """
        ctx, round_id = self._setup_open_round("E2001")
        member_id = ctx["committee_ctx"]["members"][0]["id"]
        baseline = read_round(round_id)

        vote = cast_ballot(round_id, member_id, "RECUSE")
        validate_success(
            api.retract_vote(vote["id"], make_committee_voter_headers(member_id))
        )

        restored = read_round(round_id)
        assert restored["eligible_voter_count"] == baseline["eligible_voter_count"]
        assert restored["quorum_required"] == baseline["quorum_required"]
        assert restored["votes_cast"] == baseline["votes_cast"]
        assert restored["recusal_count"] == 0, "No residual drift after retraction"

        vote_after = validate_success(api.get_vote(vote["id"], reader_headers))
        assert vote_after["status"] == "RETRACTED"
        assert vote_after["retracted_at"] is not None


def test_second_active_chair_rejected(api):
    """PRD §2.9: "At most one active member of a committee may hold the chair
    role at any time; an attempt to seat a second active chair is rejected with
    `ERR_CHAIR_CONFLICT`."
    PRD §3.5: "Deactivating a member sets `is_active` to false; inactive members
    are excluded from every eligibility count and cannot vote."

    Design: Corner/validations/second_active_chair_rejected
    """
    committee = create_committee("DEPARTMENT", "CS")
    chair1 = add_member(
        committee["id"], "Chair One", "chair1_hc@u.edu", role_in_committee="CHAIR"
    )

    err = api.create_member(
        {
            "committee_id": committee["id"],
            "full_name": "Chair Two",
            "email": "chair2_hc@u.edu",
            "role_in_committee": "CHAIR",
            "service_start": "2026-01-01",
            "service_end": "2026-12-31",
        },
        PO_HEADERS,
    )
    validate_error(err, ApiErrorId.ERR_CHAIR_CONFLICT)

    # Deactivating the first chair frees the seat.
    validate_success(api.deactivate_member(chair1["id"], PO_HEADERS))
    chair2 = add_member(
        committee["id"], "Chair Two", "chair2_hc@u.edu", role_in_committee="CHAIR"
    )
    assert chair2["role_in_committee"] == "CHAIR"
    assert chair2["is_active"] is True
