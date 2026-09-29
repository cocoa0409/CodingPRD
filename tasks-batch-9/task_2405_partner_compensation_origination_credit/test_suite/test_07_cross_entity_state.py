"""Cross-entity state dependencies: a write that is legal for its own row and
refused because of the state of a neighbouring one."""

from test_helpers import (
    ApiErrorId,
    accept_assessment,
    advance_cycle,
    advance_cycle_payload,
    allocate_origination_credit,
    approx2,
    assign_peer_review,
    cast_ballot,
    cast_ballot_payload,
    create_assessment,
    create_billable_record,
    create_committee_member,
    create_contribution_record_payload,
    create_cycle,
    create_matter,
    create_non_billable_record,
    create_partner,
    cycle_version,
    effectuate_transition,
    effectuate_transition_payload,
    find_allocation,
    find_ballot,
    get_success_data,
    make_committee_member_headers,
    make_cycle_admin_headers,
    matter_allocations,
    matter_version,
    notice_of_departure_payload,
    post_financials,
    read_assessment,
    read_cycle,
    read_matter,
    read_partner,
    read_transition,
    score_peer_review,
    set_matter_status,
    setup_proposed_transition,
    submit_assessment,
    validate_error,
)


def _deliberation_with_one_unaccepted_subject(api):
    """Two DISCRETIONARY subjects, identical but for their assessment state: one
    ACCEPTED, one still SUBMITTED, each holding a PENDING ballot."""
    cycle = create_cycle(api)
    first = create_partner(
        api,
        full_name="Sara One",
        practice_group="LITIGATION",
        compensation_model="DISCRETIONARY",
        admission_year=2011,
    )
    second = create_partner(
        api,
        full_name="Sven Two",
        practice_group="CORPORATE",
        compensation_model="DISCRETIONARY",
        admission_year=2012,
    )
    chair = create_committee_member(
        api, full_name="Cora Chair", practice_group="TAX", admission_year=2005
    )
    reviewer = create_partner(
        api,
        full_name="Sam Second",
        practice_group="IP",
        compensation_model="FORMULA",
        admission_year=2013,
        evaluation_required=False,
    )
    advance_cycle(api, cycle["id"], "SELF_ASSESSMENT")
    assessments = {}
    for key, subject in (("accepted", first), ("submitted", second)):
        assessment = create_assessment(
            api,
            cycle_id=cycle["id"],
            partner_id=subject["id"],
            claimed_origination_pct_total=0.00,
            claimed_non_billable_hours=0.00,
        )
        submit_assessment(api, assessment["id"], subject["id"])
        for member in (chair, reviewer):
            review = assign_peer_review(api, assessment["id"], member["id"])
            score_peer_review(api, review["id"], member["id"], 4, 4, 4)
        assessments[key] = assessment
    accept_assessment(api, assessments["accepted"]["id"], chair["id"])
    advance_cycle(api, cycle["id"], "PEER_REVIEW")
    cycle = advance_cycle(api, cycle["id"], "DELIBERATION")
    return {
        "cycle": cycle,
        "accepted_subject": first,
        "submitted_subject": second,
        "chair": chair,
        "assessments": assessments,
        "accepted_ballot": find_ballot(api, cycle["id"], first["id"], chair["id"]),
        "submitted_ballot": find_ballot(api, cycle["id"], second["id"], chair["id"]),
    }


def test_cast_is_refused_while_the_subjects_assessment_is_only_submitted(api):
    """PRD 3.7: "Two further conditions apply to a cast and to no other action:
    the committee member may not be the subject, and casting on one's own ballot
    is refused with `ERR_SELF_VOTE_FORBIDDEN`; and the subject partner's
    self-assessment for that cycle must have reached `ACCEPTED`, failing which
    `ERR_ASSESSMENT_NOT_ACCEPTED`."

    Design: Difficulty/cross_entity_state_dependency/ballot_cast_requires_subject_assessment_accepted
    """
    scenario = _deliberation_with_one_unaccepted_subject(api)
    ballot_id = scenario["submitted_ballot"]["id"]
    assert scenario["submitted_ballot"]["state"] == "PENDING"

    response = api.cast_ballot(
        ballot_id,
        cast_ballot_payload(
            500.00,
            cycle_version(api, scenario["cycle"]["id"]),
            rationale="Deserves a mid-band award.",
        ),
        make_committee_member_headers(scenario["chair"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_ASSESSMENT_NOT_ACCEPTED.value, 409)

    pending = get_success_data(api.get_ballot(ballot_id, make_cycle_admin_headers()))
    assert pending["state"] == "PENDING"
    submitted = read_assessment(api, scenario["assessments"]["submitted"]["id"])
    assert submitted["state"] == "SUBMITTED"
    assert submitted["scored_review_count"] == 2
    assert read_assessment(api, scenario["assessments"]["accepted"]["id"])["state"] == "ACCEPTED"
    assert read_cycle(api, scenario["cycle"]["id"])["state"] == "DELIBERATION"


def test_the_accepted_subjects_ballot_casts_but_one_vote_misses_quorum(api):
    """PRD 3.8: "Every subject partner that has ballots in this cycle must have at
    least two of them in `CAST`, failing which `ERR_QUORUM_NOT_MET`; and the pool
    waterfall must close without residual deficit, failing which
    `ERR_POOL_INSUFFICIENT` and the entire advance is rejected with all four pool
    fields left at their pre-call values."

    Design: Difficulty/cross_entity_state_dependency/ballot_cast_requires_subject_assessment_accepted
    """
    scenario = _deliberation_with_one_unaccepted_subject(api)
    cycle_id = scenario["cycle"]["id"]
    pools_before = {
        field: read_cycle(api, cycle_id)[field]
        for field in (
            "lockstep_reserved_cents",
            "discretionary_pool_cents",
            "formula_pool_cents",
            "haircut_applied_pct",
        )
    }

    cast = cast_ballot(
        api,
        ballot_id=scenario["accepted_ballot"]["id"],
        committee_member_id=scenario["chair"]["id"],
        points_proposed=500.00,
        cycle_id=cycle_id,
        rationale="Deserves a mid-band award.",
    )
    assert cast["state"] == "CAST"
    assert cast["points_proposed"] == approx2(500.00)

    response = api.advance_cycle(
        cycle_id, advance_cycle_payload("AWARDS_PUBLISHED"), make_cycle_admin_headers()
    )
    validate_error(response, ApiErrorId.ERR_QUORUM_NOT_MET.value, 409)

    cycle = read_cycle(api, cycle_id)
    assert cycle["state"] == "DELIBERATION"
    assert {field: cycle[field] for field in pools_before} == pools_before


def _one_closed_and_one_open_matter(api):
    """One FORMULA partner responsible for a CLOSED matter and an OPEN one, both
    fully collected."""
    cycle = create_cycle(api)
    partner = create_partner(
        api,
        full_name="Pia Poster",
        practice_group="LITIGATION",
        compensation_model="FORMULA",
        admission_year=2015,
    )
    closed = create_matter(
        api,
        billing_attorney_id=partner["id"],
        responsible_attorney_id=partner["id"],
        client_key="CLI-C1",
        client_display_name="Closed Co",
        matter_type="EXISTING",
        practice_group="LITIGATION",
        opened_on="2026-01-05",
    )
    post_financials(
        api,
        closed["id"],
        billed_delta_cents=500_000,
        collected_delta_cents=500_000,
        direct_cost_delta_cents=0,
    )
    still_open = create_matter(
        api,
        billing_attorney_id=partner["id"],
        responsible_attorney_id=partner["id"],
        client_key="CLI-O1",
        client_display_name="Open Co",
        matter_type="EXISTING",
        practice_group="LITIGATION",
        opened_on="2026-02-05",
    )
    post_financials(
        api,
        still_open["id"],
        billed_delta_cents=500_000,
        collected_delta_cents=500_000,
        direct_cost_delta_cents=0,
    )
    set_matter_status(api, closed["id"], "CLOSED")
    return {"cycle": cycle, "partner": partner, "closed": closed, "open": still_open}


def test_billable_hours_cannot_be_booked_against_a_closed_matter(api):
    """PRD 3.3: "A billable record additionally requires the referenced matter to
    be in state `OPEN`, and a record pointing at a closed or written-off matter is
    refused with `ERR_MATTER_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/billable_record_requires_matter_open
    """
    scenario = _one_closed_and_one_open_matter(api)
    admin = make_cycle_admin_headers()
    assert read_matter(api, scenario["closed"]["id"])["state"] == "CLOSED"
    assert read_matter(api, scenario["open"]["id"])["state"] == "OPEN"

    response = api.create_contribution_record(
        create_contribution_record_payload(
            partner_id=scenario["partner"]["id"],
            cycle_id=scenario["cycle"]["id"],
            matter_id=scenario["closed"]["id"],
            hours=10.00,
            standard_rate_cents=50_000,
            service_period_start="2026-03-01",
            service_period_end="2026-03-31",
        ),
        admin,
    )
    validate_error(response, ApiErrorId.ERR_MATTER_NOT_OPEN.value, 409)

    assert get_success_data(api.list_contribution_records(admin)) == []
    assert read_matter(api, scenario["closed"]["id"])["verified_billable_hours"] == approx2(0.00)


def test_the_same_hours_book_freely_against_the_open_matter(api):
    """PRD 3.3: "Creation returns 201 Created, sets `standard_value_cents` to
    `hours` multiplied by `standard_rate_cents` rounded half up for billable rows
    and to 0 for non-billable rows, and leaves `verified` false with `verified_at`
    null."

    Design: Difficulty/cross_entity_state_dependency/billable_record_requires_matter_open
    """
    scenario = _one_closed_and_one_open_matter(api)

    billable = create_billable_record(
        api,
        partner_id=scenario["partner"]["id"],
        cycle_id=scenario["cycle"]["id"],
        matter_id=scenario["open"]["id"],
        hours=10.00,
        standard_rate_cents=50_000,
        service_period_start="2026-03-01",
        service_period_end="2026-03-31",
    )
    assert billable["standard_value_cents"] == 500_000
    assert billable["verified"] is False
    assert billable["verified_at"] is None

    non_billable = create_non_billable_record(
        api,
        partner_id=scenario["partner"]["id"],
        cycle_id=scenario["cycle"]["id"],
        category="FIRM_MANAGEMENT",
        hours=10.00,
        service_period_start="2026-05-01",
        service_period_end="2026-05-31",
    )
    assert non_billable["standard_value_cents"] == 0
    assert non_billable["matter_id"] is None

    assert read_matter(api, scenario["open"]["id"])["verified_billable_hours"] == approx2(0.00)
    assert read_matter(api, scenario["closed"]["id"])["verified_billable_hours"] == approx2(0.00)


def _transition_with_an_ineligible_and_an_eligible_successor(api):
    """A PROPOSED transition whose departing partner is NOTICE_GIVEN, alongside a
    second partner who has also given notice and one untouched ACTIVE partner."""
    base = setup_proposed_transition(api, departure_effective_on="2026-12-31")
    leaving = create_partner(
        api,
        full_name="Sela Leaving",
        compensation_model="FORMULA",
        admission_year=2013,
        evaluation_required=False,
    )
    arbiter = base["arbiter"]
    second_matter = create_matter(
        api,
        billing_attorney_id=leaving["id"],
        responsible_attorney_id=leaving["id"],
        client_key="CLI-X2",
        client_display_name="Second Sunset LLC",
        opened_on="2026-02-01",
    )
    allocate_origination_credit(
        api,
        cycle_id=base["cycle"]["id"],
        matter_id=second_matter["id"],
        claimant_id=leaving["id"],
        arbiter_id=arbiter["id"],
        approved_pct=100.00,
    )
    get_success_data(
        api.notice_of_departure(
            leaving["id"],
            notice_of_departure_payload("2026-11-30"),
            make_cycle_admin_headers(),
        )
    )
    base["ineligible_successor"] = leaving
    return base


def test_effectuation_is_refused_when_the_nominated_successor_is_departing(api):
    """PRD 3.1: "A transition that is not currently `PROPOSED` is refused with
    `ERR_TRANSITION_NOT_PENDING`; a departing partner whose `status` is not
    `NOTICE_GIVEN` yields `ERR_PARTNER_NOT_DEPARTING`; a successor whose `status`
    is not `ACTIVE`, or who is the departing partner themselves, yields
    `ERR_SUCCESSOR_NOT_ELIGIBLE`; and an `effective_on` that is not strictly later
    than the departing originating allocation's `credit_from` is rejected as a
    malformed request, since a transfer cannot take effect before the credit it
    transfers began."

    Design: Difficulty/cross_entity_state_dependency/transition_effectuate_requires_successor_active
    """
    scenario = _transition_with_an_ineligible_and_an_eligible_successor(api)
    transition_id = scenario["transition"]["id"]
    matter_id = scenario["matter"]["id"]
    pinned_version = matter_version(api, matter_id)
    assert scenario["transition"]["state"] == "PROPOSED"
    assert scenario["transition"]["transferred_pct"] == approx2(100.00)
    assert read_partner(api, scenario["departing"]["id"])["status"] == "NOTICE_GIVEN"
    assert read_partner(api, scenario["ineligible_successor"]["id"])["status"] == "NOTICE_GIVEN"
    assert read_partner(api, scenario["successor"]["id"])["status"] == "ACTIVE"

    response = api.effectuate_credit_transition(
        transition_id,
        effectuate_transition_payload(
            scenario["ineligible_successor"]["id"], "2026-09-01", pinned_version
        ),
        make_cycle_admin_headers(),
    )
    validate_error(response, ApiErrorId.ERR_SUCCESSOR_NOT_ELIGIBLE.value, 409)

    transition = read_transition(api, transition_id)
    assert transition["state"] == "PROPOSED"
    assert transition["successor_partner_id"] is None
    assert matter_version(api, matter_id) == pinned_version


def test_nominating_the_active_partner_moves_the_credit_and_departs_the_leaver(api):
    """PRD 3.1: "A partner completes the edge `NOTICE_GIVEN → DEPARTED` and
    reaches that terminal status not by an explicit call but as a consequence:
    once no credit transition naming them as departing partner remains in
    `PROPOSED` — that is, once every one has reached `EFFECTIVE` or `VOIDED` —
    their `status` becomes `DEPARTED` and their `version` increments."

    Design: Difficulty/cross_entity_state_dependency/transition_effectuate_requires_successor_active
    """
    scenario = _transition_with_an_ineligible_and_an_eligible_successor(api)
    matter_id = scenario["matter"]["id"]
    departing_id = scenario["departing"]["id"]
    successor_id = scenario["successor"]["id"]

    effective = effectuate_transition(
        api,
        transition_id=scenario["transition"]["id"],
        successor_partner_id=successor_id,
        effective_on="2026-09-01",
        matter_id=matter_id,
    )
    assert effective["state"] == "EFFECTIVE"
    assert effective["successor_partner_id"] == successor_id
    assert effective["effective_on"] == "2026-09-01"

    rows = matter_allocations(api, matter_id)
    old_row = find_allocation(rows, "ORIGINATING", departing_id)
    new_row = find_allocation(rows, "ORIGINATING", successor_id)
    assert old_row["state"] == "TRANSFERRED"
    assert old_row["credit_through"] == "2026-09-01"
    assert new_row["state"] == "ACTIVE"
    assert new_row["credit_pct"] == approx2(100.00)
    assert new_row["credit_from"] == "2026-09-01"
    assert new_row["credit_through"] is None
    assert new_row["source"] == "TRANSITION"
    assert read_matter(api, matter_id)["origination_pct_assigned"] == approx2(100.00)
    assert read_partner(api, departing_id)["status"] == "DEPARTED"
    assert read_partner(api, scenario["ineligible_successor"]["id"])["status"] == "NOTICE_GIVEN"
