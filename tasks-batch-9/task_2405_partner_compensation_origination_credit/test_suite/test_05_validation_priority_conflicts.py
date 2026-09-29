"""Priority pairs: a request that breaks two rules at once reports the higher
rung, and the lower rung is independently reachable once the higher is cleared."""

from test_helpers import (
    ApiErrorId,
    accept_assessment,
    advance_cycle,
    advance_cycle_payload,
    approx2,
    assign_peer_review,
    cast_ballot_payload,
    create_assessment,
    create_committee_member,
    create_cycle,
    create_matter,
    create_partner,
    cycle_version,
    file_claim,
    find_ballot,
    get_success_data,
    make_committee_member_headers,
    make_cycle_admin_headers,
    make_partner_headers,
    matter_allocations,
    read_claim,
    read_cycle,
    read_matter,
    read_partner,
    score_peer_review,
    set_clock,
    setup_published_discretionary_award,
    submit_assessment,
    validate_error,
    validate_success,
)


def _deliberation_with_a_self_ballot(api):
    """A DISCRETIONARY committee member is their own ballot's subject, and one
    further committee member holds a second ballot on them."""
    cycle = create_cycle(api)
    subject = create_partner(
        api,
        full_name="Vera Chair",
        practice_group="LITIGATION",
        compensation_model="DISCRETIONARY",
        admission_year=2008,
        is_committee_member=True,
    )
    reviewer = create_committee_member(
        api, full_name="Rita Reviewer", practice_group="TAX", admission_year=2009
    )
    second = create_partner(
        api,
        full_name="Sam Second",
        practice_group="IP",
        compensation_model="FORMULA",
        admission_year=2013,
        evaluation_required=False,
    )
    advance_cycle(api, cycle["id"], "SELF_ASSESSMENT")
    assessment = create_assessment(
        api,
        cycle_id=cycle["id"],
        partner_id=subject["id"],
        claimed_origination_pct_total=0.00,
        claimed_non_billable_hours=0.00,
    )
    submit_assessment(api, assessment["id"], subject["id"])
    for member, scores in ((reviewer, (4, 4, 4)), (second, (5, 4, 3))):
        review = assign_peer_review(api, assessment["id"], member["id"])
        score_peer_review(api, review["id"], member["id"], *scores)
    accept_assessment(api, assessment["id"], reviewer["id"])
    advance_cycle(api, cycle["id"], "PEER_REVIEW")
    cycle = advance_cycle(api, cycle["id"], "DELIBERATION")
    return {
        "cycle": cycle,
        "subject": subject,
        "reviewer": reviewer,
        "self_ballot": find_ballot(api, cycle["id"], subject["id"], subject["id"]),
        "reviewer_ballot": find_ballot(api, cycle["id"], subject["id"], reviewer["id"]),
    }


def test_self_vote_refusal_outranks_the_points_cap_breach(api):
    """PRD 2.11: "A committee member who casts their own ballot with proposed
    points above the per-ballot cap violates both segregation of duties (rung 13)
    and the cap constraint (rung 15); the response is `ERR_SELF_VOTE_FORBIDDEN`."

    Design: Difficulty/priority_pair_validation_conflict/self_vote_safety_beats_points_cap_constraint
    """
    scenario = _deliberation_with_a_self_ballot(api)
    ballot_id = scenario["self_ballot"]["id"]
    subject_id = scenario["subject"]["id"]
    pinned_version = cycle_version(api, scenario["cycle"]["id"])
    admin = make_cycle_admin_headers()

    both_broken = api.cast_ballot(
        ballot_id,
        cast_ballot_payload(2000.00, pinned_version, rationale="Self-assessed top of band."),
        make_committee_member_headers(subject_id),
    )
    validate_error(both_broken, ApiErrorId.ERR_SELF_VOTE_FORBIDDEN.value, 403)

    safety_only = api.cast_ballot(
        ballot_id,
        cast_ballot_payload(500.00, pinned_version, rationale="Within the cap."),
        make_committee_member_headers(subject_id),
    )
    validate_error(safety_only, ApiErrorId.ERR_SELF_VOTE_FORBIDDEN.value, 403)

    ballot = get_success_data(api.get_ballot(ballot_id, admin))
    assert ballot["state"] == "PENDING"
    assert ballot["points_proposed"] is None
    assert read_partner(api, subject_id)["committee_points"] == approx2(0.00)
    assert cycle_version(api, scenario["cycle"]["id"]) == pinned_version


def test_points_cap_breach_is_reachable_on_somebody_elses_ballot(api):
    """PRD 3.7: "Separately from the schema range, a `points_proposed` above the
    per-ballot ceiling of 1000.00 points is a business-constraint breach reported
    as `ERR_POINTS_CAP_EXCEEDED` rather than as a malformed payload — and when a
    committee member casts their own ballot with points above that ceiling, the
    self-vote refusal wins, as section 2.11 sets out."

    Design: Difficulty/priority_pair_validation_conflict/self_vote_safety_beats_points_cap_constraint
    """
    scenario = _deliberation_with_a_self_ballot(api)
    ballot_id = scenario["reviewer_ballot"]["id"]
    pinned_version = cycle_version(api, scenario["cycle"]["id"])

    response = api.cast_ballot(
        ballot_id,
        cast_ballot_payload(
            2000.00, pinned_version, rationale="Above the cap on somebody else."
        ),
        make_committee_member_headers(scenario["reviewer"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_POINTS_CAP_EXCEEDED.value, 409)

    ballot = get_success_data(api.get_ballot(ballot_id, make_cycle_admin_headers()))
    assert ballot["state"] == "PENDING"
    assert ballot["points_proposed"] is None
    assert read_partner(api, scenario["subject"]["id"])["committee_points"] == approx2(0.00)
    assert cycle_version(api, scenario["cycle"]["id"]) == pinned_version


def _late_new_client_claim(api):
    """A NEW_CLIENT claim on the second matter of a client that already has a
    sibling matter, with the clock pushed past the claim deadline."""
    cycle = create_cycle(api)
    partner = create_partner(api, full_name="Ada Origin", compensation_model="FORMULA")
    first = create_matter(
        api,
        billing_attorney_id=partner["id"],
        responsible_attorney_id=partner["id"],
        client_key="CLI-DUP",
        client_display_name="Duplicate Dynamics",
        matter_type="NEW_CLIENT",
        opened_on="2026-01-10",
    )
    second = create_matter(
        api,
        billing_attorney_id=partner["id"],
        responsible_attorney_id=partner["id"],
        client_key="CLI-DUP",
        client_display_name="Duplicate Dynamics",
        matter_type="EXPANDED_MATTER",
        opened_on="2026-03-10",
    )
    claim = file_claim(
        api,
        cycle_id=cycle["id"],
        matter_id=second["id"],
        claimant_id=partner["id"],
        claim_basis="NEW_CLIENT",
        requested_pct=100.00,
        narrative="Treating this as a brand-new client.",
    )
    return {
        "cycle": cycle,
        "partner": partner,
        "first": first,
        "second": second,
        "claim": claim,
    }


def test_closed_claim_window_outranks_the_client_history_rule(api):
    """PRD 2.11: "A claim asserting a brand-new client for a client that already
    has a sibling matter, submitted after the cycle's claim deadline has passed,
    violates both the window (rung 12) and the client-history rule (rung 14); the
    response is `ERR_CLAIM_WINDOW_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/claim_window_temporal_beats_client_history_referential
    """
    scenario = _late_new_client_claim(api)
    set_clock(api, "2026-12-01T00:00:00Z")

    response = api.submit_credit_claim(
        scenario["claim"]["id"], {}, make_partner_headers(scenario["partner"]["id"])
    )
    validate_error(response, ApiErrorId.ERR_CLAIM_WINDOW_CLOSED.value, 409)

    claim = read_claim(api, scenario["claim"]["id"])
    assert claim["state"] == "DRAFT"
    assert claim["revision_count"] == 0
    rows = matter_allocations(api, scenario["second"]["id"])
    assert [row for row in rows if row["credit_role"] == "ORIGINATING"] == []


def test_client_history_rule_surfaces_once_the_window_is_open(api):
    """PRD 3.4: "Only once the window has been cleared is the asserted basis
    tested against the client's actual matter history, and that test has three
    arms, all of which report `ERR_CLIENT_NOT_NEW`: a basis of `NEW_CLIENT`
    requires that no *other* matter with the same `client_key` and a state other
    than `WRITTEN_OFF` exists; a basis of `EXPANDED_MATTER` or `CROSS_SELL`
    requires that at least one such sibling matter *does* exist; and a
    `CROSS_SELL` basis additionally requires the claimed matter's
    `practice_group` to differ from the `practice_group` of the client's earliest
    sibling matter, since selling more of the same practice into an existing
    client is an expansion rather than a cross-sell."

    Design: Difficulty/priority_pair_validation_conflict/claim_window_temporal_beats_client_history_referential
    """
    scenario = _late_new_client_claim(api)
    set_clock(api, "2026-12-01T00:00:00Z")
    set_clock(api, "2026-09-01T00:00:00Z")

    response = api.submit_credit_claim(
        scenario["claim"]["id"], {}, make_partner_headers(scenario["partner"]["id"])
    )
    validate_error(response, ApiErrorId.ERR_CLIENT_NOT_NEW.value, 409)

    claim = read_claim(api, scenario["claim"]["id"])
    assert claim["state"] == "DRAFT"
    assert claim["revision_count"] == 0
    assert read_matter(api, scenario["first"]["id"])["is_first_matter_for_client"] is True
    assert read_matter(api, scenario["second"]["id"])["is_first_matter_for_client"] is False


def test_missing_transition_edge_outranks_the_settlement_gate(api):
    """PRD 2.11: "A cycle sitting in `AWARDS_PUBLISHED` with unsettled awards
    that is asked to advance straight to `CLOSED` violates both the missing
    transition edge (rung 9) and the settlement gate (rung 17); the response is
    `ERR_INVALID_CYCLE_TRANSITION`."

    Design: Difficulty/priority_pair_validation_conflict/cycle_transition_state_beats_awards_not_settled_fiscal
    """
    bundle = setup_published_discretionary_award(
        api, subject_overrides={"target_capital_cents": 30_000_000}
    )
    cycle_id = bundle["cycle"]["id"]
    assert read_cycle(api, cycle_id)["unsettled_award_count"] == 1

    response = api.advance_cycle(
        cycle_id, advance_cycle_payload("CLOSED"), make_cycle_admin_headers()
    )
    validate_error(response, ApiErrorId.ERR_INVALID_CYCLE_TRANSITION.value, 409)

    cycle = read_cycle(api, cycle_id)
    assert cycle["state"] == "AWARDS_PUBLISHED"
    assert cycle["unsettled_award_count"] == 1
    assert cycle["confidentiality_locked"] is False


def test_settlement_gate_surfaces_from_the_state_that_owns_the_edge(api):
    """PRD 3.8: "`TRUE_UP_OPEN → CLOSED` requires the cycle's
    `unsettled_award_count` — the number of its awards whose payment state is
    anything other than `SETTLED` — to be exactly 0, failing which
    `ERR_AWARDS_NOT_SETTLED`."

    Design: Difficulty/priority_pair_validation_conflict/cycle_transition_state_beats_awards_not_settled_fiscal
    """
    bundle = setup_published_discretionary_award(
        api, subject_overrides={"target_capital_cents": 30_000_000}
    )
    cycle_id = bundle["cycle"]["id"]

    opened = validate_success(
        api.advance_cycle(
            cycle_id, advance_cycle_payload("TRUE_UP_OPEN"), make_cycle_admin_headers()
        ),
        200,
    )
    assert opened["state"] == "TRUE_UP_OPEN"

    response = api.advance_cycle(
        cycle_id, advance_cycle_payload("CLOSED"), make_cycle_admin_headers()
    )
    validate_error(response, ApiErrorId.ERR_AWARDS_NOT_SETTLED.value, 409)

    cycle = read_cycle(api, cycle_id)
    assert cycle["state"] == "TRUE_UP_OPEN"
    assert cycle["unsettled_award_count"] == 1
    assert cycle["confidentiality_locked"] is False
