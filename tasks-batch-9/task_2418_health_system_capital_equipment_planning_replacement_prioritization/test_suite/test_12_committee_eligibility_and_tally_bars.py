"""The ballot box: who may vote, what each ballot weighs and how the tally is read off."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_committee_member,
    assert_committee_vote,
    assert_cents,
    cast_vote,
    close_intake,
    get_success_data,
    live_allocation,
    make_asset,
    make_committee_member_headers,
    make_cycle,
    make_department,
    make_facility,
    make_member,
    make_request,
    open_intake,
    pin_clock,
    refresh_cycle,
    refresh_request,
    run_allocation,
    run_scoring,
    screen,
    setup_allocated_cycle,
    submit,
    validate_error,
    validate_success,
    vote_rows,
)

CLOCK = "2026-08-01T00:00:00Z"
_PLANNER = TEST_USERS["planner_headers"]
_AUDITOR = TEST_USERS["auditor_headers"]


def _allocated_cycle_with_three_seats():
    """A SCORED request under an ALLOCATED cycle, watched by a three-seat committee."""
    ctx = setup_allocated_cycle(allocation_method="RANK_ORDERED")
    ctx["chair"] = make_member("CHAIR", 3, full_name="Dana Okafor")
    ctx["finance"] = make_member("FINANCE", 2, full_name="Ravi Chandra")
    ctx["safety"] = make_member("SAFETY_OFFICER", 1, full_name="Iris Vance")
    return ctx


def _allocated_cycle_sponsored_by_the_chair():
    """The chair sponsors the request, so the finance seat is the whole electorate."""
    pin_clock(CLOCK)
    chair = make_member("CHAIR", 3, full_name="Dana Okafor")
    finance = make_member("FINANCE", 2, full_name="Ravi Chandra")
    ctx = setup_allocated_cycle(
        allocation_method="RANK_ORDERED", request={"sponsor_member_id": chair["id"]}
    )
    ctx["chair"] = chair
    ctx["finance"] = finance
    return ctx


def _request_whose_only_eligible_voter_is_the_safety_officer():
    """Four seats, three of them conflicted out of one NRH request by a different arm."""
    pin_clock(CLOCK)
    nrh = make_facility(
        name="North Regional Hospital", code="NRH", region="NORTH",
        max_concurrent_construction=1,
    )
    smc = make_facility(
        name="South Metro Center", code="SMC", region="SOUTH", max_concurrent_construction=1
    )
    department = make_department(
        nrh["id"], name="Diagnostic Imaging CT", modality_scope="CT"
    )
    asset = make_asset(
        nrh["id"], department["id"],
        modality="CT", model_name="Aquilon CT-8", install_date="2020-08-02T00:00:00Z",
        expected_life_years=8, acquisition_cost_cents=100000000,
        oem_support_end_date="2029-06-01T00:00:00Z",
    )
    chair = make_member("CHAIR", 3, full_name="Dana Okafor", facility_id=smc["id"])
    safety = make_member("SAFETY_OFFICER", 2, full_name="Iris Vance")
    finance = make_member(
        "FINANCE", 2, full_name="Ravi Chandra", department_id=department["id"]
    )
    sponsor = make_member("CLINICAL", 2, full_name="Tomas Reed")
    cycle = open_intake(make_cycle()["id"])
    request = make_request(
        cycle["id"], department["id"], asset["id"], sponsor_member_id=sponsor["id"]
    )
    submit(request["id"], department["id"])
    screen(request["id"], "ACCEPT")
    close_intake(cycle["id"])
    cycle = run_scoring(cycle["id"])
    cycle = run_allocation(cycle["id"], "RANK_ORDERED", cycle["version"])
    return {
        "facility": nrh, "other_facility": smc, "department": department, "asset": asset,
        "cycle": cycle, "request": refresh_request(request["id"]),
        "chair": chair, "safety": safety, "finance": finance, "sponsor": sponsor,
    }


# ─── Who may cast which ballot ────────────────────────────────────────


def test_a_finance_seat_cannot_veto_but_a_safety_veto_sinks_the_request_before_quorum(api):
    """PRD §3.7: "A `VETO` from any seat other than `SAFETY_OFFICER` is rejected with
    `ERR_VETO_NOT_PERMITTED`."
    PRD §3.7: "A veto is present when at least one counted ballot has `vote` `VETO` and was cast
    by a member whose `seat` is `SAFETY_OFFICER`."
    PRD §3.7: "If a veto is present the request moves `IN_COMMITTEE → REJECTED` and quorum is not
    consulted at all."
    PRD §3.7: "The first counted ballot performs `SCORED → IN_COMMITTEE`."
    PRD §3.7: "Every ballot increments the request's `version`, and every ballot pins
    `counted_weight` from the casting member's `voting_weight` at that instant."
    PRD §2.11: "34. A `VETO` ballot from a seat other than `SAFETY_OFFICER`, on ballot creation —
    `ERR_VETO_NOT_PERMITTED`, 422."

    Design: Corner/validations/only_the_safety_officer_may_veto_and_the_veto_outranks_the_quorum_test
    """
    ctx = _allocated_cycle_with_three_seats()
    scored_version = refresh_request(ctx["request"]["id"])["version"]

    validate_error(
        api.create_vote(
            ctx["request"]["id"],
            {"vote": "VETO", "expected_request_version": scored_version,
             "rationale": "Finance objects to the price."},
            make_committee_member_headers(ctx["finance"]["id"]),
        ),
        ApiErrorId.ERR_VETO_NOT_PERMITTED.value, 422,
    )
    untouched = refresh_request(ctx["request"]["id"])
    assert untouched["status"] == "SCORED"
    assert untouched["version"] == scored_version
    assert vote_rows(ctx["request"]["id"]) == []

    finance_ballot = validate_success(
        api.create_vote(
            ctx["request"]["id"],
            {"vote": "APPROVE", "expected_request_version": scored_version},
            make_committee_member_headers(ctx["finance"]["id"]),
        ),
        201,
    )
    assert_committee_vote(finance_ballot)
    assert finance_ballot["counted_weight"] == 2
    assert refresh_request(ctx["request"]["id"])["status"] == "IN_COMMITTEE"

    safety_ballot = cast_vote(
        ctx["request"]["id"], ctx["safety"]["id"], "VETO",
        rationale="Radiation shielding cannot be certified for this model.",
    )
    assert safety_ballot["counted_weight"] == 1
    assert all(row["superseded"] is False for row in vote_rows(ctx["request"]["id"]))

    decided = validate_success(
        api.committee_decision(
            ctx["request"]["id"],
            make_committee_member_headers(ctx["chair"]["id"]),
            {"decision_note": "Safety veto recorded."},
        )
    )
    assert decided["status"] == "REJECTED"

    allocation = live_allocation(ctx["cycle"]["id"], ctx["facility"]["id"])
    assert_cents(allocation["committed_cents"], 0, "committed_cents")
    assert allocation["posture"] == "ACTIVE"
    assert refresh_cycle(ctx["cycle"]["id"])["status"] == "ALLOCATED"


def test_every_exclusion_arm_speaks_with_one_voice_while_only_the_chair_may_close(api):
    """PRD §3.7: "The acting member must be eligible: `active` true, either a null `facility_id`
    or one equal to the request's facility, an `id` different from the request's
    `sponsor_member_id`, and either a null `department_id` or one different from the request's
    `department_id`."
    PRD §3.7: "An ineligible member is rejected with `ERR_VOTE_CONFLICT_OF_INTEREST`."
    PRD §3.7: "The acting member's `seat` must be `CHAIR`, otherwise the call is rejected with
    `ERR_CHAIR_REQUIRED`; presiding is procedural, so the chair does not itself need to be an
    eligible voter on the request."
    PRD §3.7: "Otherwise the two-thirds approval bar is applied: when approve weight multiplied by
    three is at least cast weight multiplied by two, the request moves `IN_COMMITTEE → APPROVED`."
    PRD §2.11: "33. An ineligible member attempting to vote, on ballot creation —
    `ERR_VOTE_CONFLICT_OF_INTEREST`, 403."
    PRD §2.11: "35. A non-chair attempting to close voting, on committee decision —
    `ERR_CHAIR_REQUIRED`, 403."

    Design: Corner/rbac/the_vote_conflict_predicate_and_the_chair_only_close_are_independent_gates
    """
    ctx = _request_whose_only_eligible_voter_is_the_safety_officer()
    scored_version = ctx["request"]["version"]
    ballot = {"vote": "APPROVE", "expected_request_version": scored_version}

    for member_key in ("sponsor", "finance", "chair"):
        validate_error(
            api.create_vote(
                ctx["request"]["id"], ballot,
                make_committee_member_headers(ctx[member_key]["id"]),
            ),
            ApiErrorId.ERR_VOTE_CONFLICT_OF_INTEREST.value, 403,
        )

    validate_error(
        api.create_vote(
            ctx["request"]["id"],
            {"vote": "VETO", "expected_request_version": scored_version},
            make_committee_member_headers(ctx["finance"]["id"]),
        ),
        ApiErrorId.ERR_VOTE_CONFLICT_OF_INTEREST.value, 403,
    )

    counted = validate_success(
        api.create_vote(
            ctx["request"]["id"], ballot,
            make_committee_member_headers(ctx["safety"]["id"]),
        ),
        201,
    )
    assert counted["counted_weight"] == 2
    assert refresh_request(ctx["request"]["id"])["status"] == "IN_COMMITTEE"

    validate_error(
        api.committee_decision(
            ctx["request"]["id"], make_committee_member_headers(ctx["safety"]["id"])
        ),
        ApiErrorId.ERR_CHAIR_REQUIRED.value, 403,
    )

    decided = validate_success(
        api.committee_decision(
            ctx["request"]["id"], make_committee_member_headers(ctx["chair"]["id"])
        )
    )
    assert decided["status"] == "APPROVED"

    rows = get_success_data(api.list_request_votes(ctx["request"]["id"], _AUDITOR))
    assert len(rows) == 1
    assert rows[0]["id"] == counted["id"]


# ─── What the tally counts ────────────────────────────────────────────


def test_an_abstention_makes_quorum_possible_and_then_raises_the_approval_bar(api):
    """PRD §3.7: "Cast weight is the sum of `counted_weight` over the counted ballots, with
    `APPROVE`, `REJECT`, `ABSTAIN` and `VETO` all contributing; an abstention therefore counts
    toward quorum and raises the approval bar."
    PRD §3.7: "Otherwise the quorum bar, a sixty-percent threshold expressed as an exact
    cross-multiplication, is applied: when cast weight multiplied by five is less than quorum
    weight multiplied by three, the call is rejected with `ERR_QUORUM_NOT_MET`."
    PRD §3.7: "Otherwise the simple-majority defer bar is applied: when approve weight multiplied
    by two is at least cast weight, the request moves `IN_COMMITTEE → DEFERRED`."
    PRD §3.7: "Approve weight is the sum of `counted_weight` over the counted ballots whose
    `vote` is `APPROVE`."
    PRD §2.11: "37. Quorum not met, on committee decision — `ERR_QUORUM_NOT_MET`, 409."

    Design: Corner/validations/an_abstention_counts_toward_cast_weight_at_both_the_quorum_and_approval_bars
    """
    ctx = setup_allocated_cycle(allocation_method="RANK_ORDERED")
    chair = make_member("CHAIR", 3, full_name="Dana Okafor")
    finance = make_member("FINANCE", 2, full_name="Ravi Chandra")
    cast_vote(ctx["request"]["id"], finance["id"], "ABSTAIN")
    before = refresh_request(ctx["request"]["id"])
    assert before["status"] == "IN_COMMITTEE"

    validate_error(
        api.committee_decision(
            ctx["request"]["id"], make_committee_member_headers(chair["id"])
        ),
        ApiErrorId.ERR_QUORUM_NOT_MET.value, 409,
    )
    after_failure = refresh_request(ctx["request"]["id"])
    assert after_failure["status"] == "IN_COMMITTEE"
    assert after_failure["version"] == before["version"]

    cast_vote(ctx["request"]["id"], chair["id"], "APPROVE")
    decided = validate_success(
        api.committee_decision(
            ctx["request"]["id"], make_committee_member_headers(chair["id"])
        )
    )
    assert decided["status"] == "DEFERRED"

    rows = vote_rows(ctx["request"]["id"])
    assert len(rows) == 2
    assert all(row["superseded"] is False for row in rows)
    assert sorted(row["counted_weight"] for row in rows) == [2, 3]

    allocation = live_allocation(ctx["cycle"]["id"], ctx["facility"]["id"])
    assert_cents(allocation["committed_cents"], 0, "committed_cents")
    assert refresh_cycle(ctx["cycle"]["id"])["status"] == "ALLOCATED"


def test_deactivating_the_lone_voter_empties_the_electorate_the_chair_presides_over(api):
    """PRD §3.7: "Editing a member never rewrites ballots already cast — those keep the weight
    pinned on them — but a member who becomes inactive or newly conflicted drops out of both
    quorum and cast weight the next time a tally runs."
    PRD §3.7: "First the **eligible voter set** is derived over every committee member row using
    exactly the eligibility predicate above, and the quorum weight is the sum of `voting_weight`
    over that set."
    PRD §3.7: "Otherwise, if the eligible voter set is empty the call is rejected with
    `ERR_NO_ELIGIBLE_VOTERS`."
    PRD §2.11: "36. An empty eligible voter set, on committee decision —
    `ERR_NO_ELIGIBLE_VOTERS`, 409. Evaluated after the veto branch of the tally."

    Design: Corner/validations/deactivating_the_only_eligible_voter_empties_the_electorate_at_decision_time
    """
    ctx = _allocated_cycle_sponsored_by_the_chair()
    cast_vote(ctx["request"]["id"], ctx["finance"]["id"], "APPROVE")
    assert refresh_request(ctx["request"]["id"])["status"] == "IN_COMMITTEE"

    deactivated = validate_success(
        api.patch_committee_member(ctx["finance"]["id"], {"active": False}, _PLANNER)
    )
    assert_committee_member(deactivated)
    assert deactivated["active"] is False
    assert deactivated["version"] == 2

    pinned = vote_rows(ctx["request"]["id"])
    assert len(pinned) == 1
    assert pinned[0]["counted_weight"] == 2
    assert pinned[0]["superseded"] is False

    validate_error(
        api.committee_decision(
            ctx["request"]["id"], make_committee_member_headers(ctx["chair"]["id"])
        ),
        ApiErrorId.ERR_NO_ELIGIBLE_VOTERS.value, 409,
    )

    current_version = refresh_request(ctx["request"]["id"])["version"]
    validate_error(
        api.create_vote(
            ctx["request"]["id"],
            {"vote": "APPROVE", "expected_request_version": current_version},
            make_committee_member_headers(ctx["chair"]["id"]),
        ),
        ApiErrorId.ERR_VOTE_CONFLICT_OF_INTEREST.value, 403,
    )

    assert refresh_request(ctx["request"]["id"])["status"] == "IN_COMMITTEE"
    assert refresh_cycle(ctx["cycle"]["id"])["status"] == "ALLOCATED"


def test_a_members_own_ballot_log_keeps_both_weights_while_quorum_reads_the_current_one(api):
    """PRD §3.7: "Where the same member had already cast a ballot on this request, that earlier
    ballot's `superseded` becomes true, and superseded ballots are excluded from both quorum and
    tally."
    PRD §3.7: "Members can be listed filtered by `facility_id`, `department_id`, `seat` and
    `active`, and every ballot a single member has cast across all requests can be read in
    `created_at` ascending order filtered by `superseded` and by `vote`."
    PRD §3.7: "In both sums it is the weight pinned on the ballot that counts, never the member's
    current `voting_weight`."
    PRD §3.7: "Otherwise the request moves `IN_COMMITTEE → REJECTED`."
    PRD §3.7: "A request's ballots can be listed filtered by `member_id` and by `superseded`."

    Design: Corner/endpoints/the_member_votes_sub_resource_pins_the_weight_that_each_ballot_carried
    """
    ctx = setup_allocated_cycle(allocation_method="RANK_ORDERED")
    chair = make_member("CHAIR", 3, full_name="Dana Okafor")
    finance = make_member("FINANCE", 2, full_name="Ravi Chandra")
    first_ballot = cast_vote(ctx["request"]["id"], finance["id"], "APPROVE")
    assert first_ballot["counted_weight"] == 2

    validate_success(api.patch_committee_member(finance["id"], {"voting_weight": 5}, _PLANNER))
    recast = cast_vote(
        ctx["request"]["id"], finance["id"], "REJECT",
        rationale="The price is unjustified at the new tier.",
    )
    assert recast["counted_weight"] == 5

    chair_headers = make_committee_member_headers(chair["id"])
    log = get_success_data(api.list_member_votes(finance["id"], chair_headers))
    assert [(row["vote"], row["counted_weight"], row["superseded"]) for row in log] == [
        ("APPROVE", 2, True),
        ("REJECT", 5, False),
    ]

    live_only = get_success_data(
        api.list_member_votes(finance["id"], chair_headers, params={"superseded": False})
    )
    assert len(live_only) == 1
    assert live_only[0]["id"] == recast["id"]

    chair_ballots = get_success_data(
        api.list_request_votes(
            ctx["request"]["id"], chair_headers, params={"member_id": chair["id"]}
        )
    )
    assert chair_ballots == []

    cast_vote(ctx["request"]["id"], chair["id"], "APPROVE")
    decided = validate_success(api.committee_decision(ctx["request"]["id"], chair_headers))
    assert decided["status"] == "REJECTED"

    all_rows = vote_rows(ctx["request"]["id"])
    assert len(all_rows) == 3
    assert len([row for row in all_rows if row["superseded"] is True]) == 1
