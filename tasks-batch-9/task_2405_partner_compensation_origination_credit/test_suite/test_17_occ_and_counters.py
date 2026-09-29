"""The six stale-version guards replayed against a superseded parent version,
and the responsible-matter counter walked across every edge that moves it."""

from test_helpers import (
    ApiErrorId,
    adjudicate_claim,
    adjudicate_claim_payload,
    allocate_origination_credit,
    approx2,
    approx4,
    capital_contribution_payload,
    cast_ballot,
    cast_ballot_payload,
    contribute_capital,
    create_credit_arbiter,
    create_cycle,
    create_matter,
    create_partner,
    cycle_version,
    effectuate_transition,
    effectuate_transition_payload,
    file_claim,
    find_allocation,
    make_committee_member_headers,
    make_credit_arbiter_headers,
    make_cycle_admin_headers,
    matter_allocations,
    matter_financials_payload,
    matter_version,
    notice_of_departure_payload,
    partner_version,
    post_financials,
    read_claim,
    read_cycle,
    read_matter,
    read_partner,
    read_transition,
    set_matter_status,
    setup_deliberation_cycle,
    setup_proposed_transition,
    submit_claim,
    validate_error,
    validate_paginated,
    validate_success,
    void_transition,
    void_transition_payload,
)


def test_occ_matter_financials_replayed_against_a_stale_matter_version(api):
    """PRD 2.8: "Posting billing, collection and cost deltas against a matter
    requires `expected_matter_version` matching the target matter's current
    `version`. Financial deltas are additive, so re-posting the same body is
    legitimate product behaviour on its own terms; the version check is what
    distinguishes an intended second posting from a re-send made against an
    out-of-date view of the matter ledger."

    Design: Corner/cross_cutting_complexity_layers/occ_matter_financials_replayed_against_a_stale_matter_version
    """
    admin = make_cycle_admin_headers()
    create_cycle(api)
    partner = create_partner(api, full_name="Ada Origin")
    matter = create_matter(api, billing_attorney_id=partner["id"])
    stale_version = matter["version"]
    payload = matter_financials_payload(
        stale_version,
        billed_delta_cents=1_000_000,
        collected_delta_cents=900_000,
        direct_cost_delta_cents=200_000,
    )

    posted = validate_success(api.post_matter_financials(matter["id"], payload, admin), 200)
    assert posted["billed_cents"] == 1_000_000
    assert posted["collected_cents"] == 900_000
    assert posted["direct_cost_cents"] == 200_000
    assert posted["realization_pct"] == approx4(0.9000)
    assert posted["profitability_index_contribution"] == approx4(0.7778)
    assert posted["version"] == stale_version + 1

    replay = api.post_matter_financials(matter["id"], payload, admin)
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION.value, 412)

    unchanged = read_matter(api, matter["id"])
    assert unchanged["billed_cents"] == 1_000_000
    assert unchanged["collected_cents"] == 900_000
    assert unchanged["direct_cost_cents"] == 200_000
    assert unchanged["version"] == posted["version"]


def test_occ_two_adjudications_on_one_matter_from_the_same_read(api):
    """PRD 2.8: "Adjudicating an origination credit claim requires
    `expected_matter_version` matching the claim's matter's current `version`.
    Adjudication writes originating credit rows against the matter and consumes
    part of its 100.00 percent capacity, so an arbiter whose view of the matter
    has been superseded is working from a stale picture of the remaining capacity
    and is rejected rather than allowed to oversubscribe it."

    Design: Corner/cross_cutting_complexity_layers/occ_two_adjudications_on_one_matter_from_the_same_read
    """
    cycle = create_cycle(api)
    first_claimant = create_partner(api, full_name="Ada Origin")
    second_claimant = create_partner(api, full_name="Otto Other", practice_group="TAX")
    arbiter = create_credit_arbiter(api, full_name="Arya Arbiter", practice_group="REGULATORY")
    matter = create_matter(
        api,
        billing_attorney_id=second_claimant["id"],
        responsible_attorney_id=second_claimant["id"],
        client_key="CLI-OA",
        client_display_name="Omega Analytics",
    )

    first_claim = file_claim(
        api,
        cycle_id=cycle["id"],
        matter_id=matter["id"],
        claimant_id=first_claimant["id"],
        requested_pct=60.00,
    )
    submit_claim(api, first_claim["id"], first_claimant["id"])
    second_claim = file_claim(
        api,
        cycle_id=cycle["id"],
        matter_id=matter["id"],
        claimant_id=second_claimant["id"],
        requested_pct=40.00,
        narrative="I brought this client into the firm alongside my colleague.",
    )
    submit_claim(api, second_claim["id"], second_claimant["id"])

    shared_read = matter_version(api, matter["id"])
    decided = adjudicate_claim(
        api,
        claim_id=first_claim["id"],
        arbiter_id=arbiter["id"],
        decision="ALLOCATE",
        expected_matter_version=shared_read,
        approved_pct=60.00,
    )
    assert decided["state"] == "ALLOCATED"
    assert decided["approved_pct"] == approx2(60.00)

    replay = api.adjudicate_credit_claim(
        second_claim["id"],
        adjudicate_claim_payload("ALLOCATE", shared_read, approved_pct=40.00),
        make_credit_arbiter_headers(arbiter["id"]),
    )
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION.value, 412)

    fresh_read = matter_version(api, matter["id"])
    assert fresh_read == shared_read + 1
    assert read_matter(api, matter["id"])["origination_pct_assigned"] == approx2(60.00)
    assert read_claim(api, second_claim["id"])["state"] == "SUBMITTED"

    retried = adjudicate_claim(
        api,
        claim_id=second_claim["id"],
        arbiter_id=arbiter["id"],
        decision="ALLOCATE",
        expected_matter_version=fresh_read,
        approved_pct=40.00,
    )
    assert retried["state"] == "ALLOCATED"
    assert read_matter(api, matter["id"])["origination_pct_assigned"] == approx2(100.00)


def test_occ_second_ballot_cast_from_the_same_cycle_read(api):
    """PRD 2.8: "Casting, abstaining or recusing on a committee ballot requires
    `expected_cycle_version` matching the ballot's cycle's current `version`.
    Every accepted ballot decision advances the cycle's `version`, so a committee
    member holding a superseded view of the deliberation point pool fails
    deterministically."

    Design: Corner/cross_cutting_complexity_layers/occ_second_ballot_cast_from_the_same_cycle_read
    """
    scenario = setup_deliberation_cycle(api)
    cycle_id = scenario["cycle"]["id"]
    first_member, second_member = scenario["committee"]
    first_ballot, second_ballot = scenario["ballots"]
    shared_read = cycle_version(api, cycle_id)
    assert read_cycle(api, cycle_id)["total_committee_points"] == approx2(0.00)

    cast = cast_ballot(
        api,
        ballot_id=first_ballot["id"],
        committee_member_id=first_member["id"],
        points_proposed=800.00,
        expected_cycle_version=shared_read,
    )
    assert cast["state"] == "CAST"
    assert cast["points_proposed"] == approx2(800.00)

    replay = api.cast_ballot(
        second_ballot["id"],
        cast_ballot_payload(600.00, shared_read),
        make_committee_member_headers(second_member["id"]),
    )
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION.value, 412)

    fresh_read = cycle_version(api, cycle_id)
    assert fresh_read == shared_read + 1
    assert read_cycle(api, cycle_id)["total_committee_points"] == approx2(800.00)

    retried = cast_ballot(
        api,
        ballot_id=second_ballot["id"],
        committee_member_id=second_member["id"],
        points_proposed=600.00,
        expected_cycle_version=fresh_read,
    )
    assert retried["state"] == "CAST"
    assert read_partner(api, scenario["subject"]["id"])["committee_points"] == approx2(700.00)


def test_occ_capital_contribution_replayed_against_a_stale_partner_version(api):
    """PRD 2.8: "Contributing capital to a partner requires
    `expected_partner_version` matching that partner's current `version`.
    Contributions are additive, so a second contribution of the same amount
    legitimately succeeds under the product semantics; the version check is the
    only thing separating an intended second contribution from a re-send against
    an out-of-date capital account balance."

    Design: Corner/cross_cutting_complexity_layers/occ_capital_contribution_replayed_against_a_stale_partner_version
    """
    admin = make_cycle_admin_headers()
    create_cycle(api)
    partner = create_partner(
        api, full_name="Ada Origin", opening_capital_cents=0, target_capital_cents=20_000_000
    )
    assert partner["capital_account_balance_cents"] == 0
    stale_version = partner["version"]
    payload = capital_contribution_payload(5_000_000, stale_version)

    funded = validate_success(api.capital_contribution(partner["id"], payload, admin), 200)
    assert funded["capital_account_balance_cents"] == 5_000_000
    assert funded["version"] == stale_version + 1

    replay = api.capital_contribution(partner["id"], payload, admin)
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION.value, 412)

    unchanged = read_partner(api, partner["id"])
    assert unchanged["capital_account_balance_cents"] == 5_000_000
    assert unchanged["version"] == funded["version"]

    retried = contribute_capital(
        api,
        partner_id=partner["id"],
        amount_cents=5_000_000,
        expected_partner_version=partner_version(api, partner["id"]),
    )
    assert retried["capital_account_balance_cents"] == 10_000_000


def test_occ_transition_effectuate_after_an_intervening_matter_write(api):
    """PRD 2.8: "Effectuating a credit transition requires
    `expected_matter_version` matching the transition's matter's current
    `version`. Effectuation rewrites the matter's originating allocations and
    possibly its responsible attorney, and several transitions can legitimately
    land on the same matter, so an administrator acting on a superseded matter
    version is rejected rather than allowed to overwrite an allocation layout it
    never observed."

    Design: Corner/cross_cutting_complexity_layers/occ_transition_effectuate_after_an_intervening_matter_write
    """
    admin = make_cycle_admin_headers()
    scenario = setup_proposed_transition(api)
    matter_id = scenario["matter"]["id"]
    transition_id = scenario["transition"]["id"]
    stale_version = matter_version(api, matter_id)

    posted = post_financials(
        api,
        matter_id,
        billed_delta_cents=500_000,
        collected_delta_cents=400_000,
        direct_cost_delta_cents=0,
        expected_matter_version=stale_version,
    )
    assert posted["version"] == stale_version + 1

    replay = api.effectuate_credit_transition(
        transition_id,
        effectuate_transition_payload(
            scenario["successor"]["id"], "2026-12-31", stale_version
        ),
        admin,
    )
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION.value, 412)

    untouched = read_transition(api, transition_id)
    assert untouched["state"] == "PROPOSED"
    assert untouched["successor_partner_id"] is None
    assert untouched["effective_on"] is None

    effective = effectuate_transition(
        api,
        transition_id=transition_id,
        successor_partner_id=scenario["successor"]["id"],
        effective_on="2026-12-31",
        expected_matter_version=posted["version"],
    )
    assert effective["state"] == "EFFECTIVE"
    assert effective["successor_partner_id"] == scenario["successor"]["id"]

    rows = matter_allocations(api, matter_id)
    transferred = find_allocation(
        rows, "ORIGINATING", scenario["departing"]["id"], "TRANSFERRED"
    )
    assert transferred["credit_through"] == "2026-12-31"
    opened = find_allocation(rows, "ORIGINATING", scenario["successor"]["id"], "ACTIVE")
    assert opened["credit_pct"] == approx2(100.00)
    assert opened["source"] == "TRANSITION"
    assert opened["credit_from"] == "2026-12-31"


def test_occ_transition_void_after_an_intervening_matter_write(api):
    """PRD 2.8: "Voiding a credit transition requires `expected_matter_version`
    matching the transition's matter's current `version`. A void restores the
    departing partner's allocation and the matter's prior responsible attorney;
    restoring that snapshot onto a matter it no longer describes is refused."

    Design: Corner/cross_cutting_complexity_layers/occ_transition_void_after_an_intervening_matter_write
    """
    admin = make_cycle_admin_headers()
    cycle = create_cycle(api)
    departing = create_partner(
        api, full_name="Dev Departing", compensation_model="FORMULA", evaluation_required=False
    )
    successor = create_partner(
        api,
        full_name="Sam Successor",
        compensation_model="FORMULA",
        practice_group="TAX",
        evaluation_required=False,
    )
    arbiter = create_credit_arbiter(api, full_name="Arya Arbiter", practice_group="REGULATORY")
    matters = []
    for client_key, opened_on in (("CLI-V1", "2026-01-15"), ("CLI-V2", "2026-02-15")):
        matter = create_matter(
            api,
            billing_attorney_id=departing["id"],
            responsible_attorney_id=departing["id"],
            client_key=client_key,
            client_display_name=f"Client {client_key}",
            opened_on=opened_on,
        )
        allocate_origination_credit(
            api,
            cycle_id=cycle["id"],
            matter_id=matter["id"],
            claimant_id=departing["id"],
            arbiter_id=arbiter["id"],
            approved_pct=100.00,
        )
        matters.append(matter)
    validate_success(
        api.notice_of_departure(
            departing["id"], notice_of_departure_payload("2026-12-31"), admin
        ),
        200,
    )
    staged, meta = validate_paginated(
        api.list_credit_transitions(admin, {"departing_partner_id": departing["id"]})
    )
    assert meta["total_count"] == 2
    matter_id = matters[0]["id"]
    transition_id = staged[0]["id"]
    assert staged[0]["matter_id"] == matter_id

    effectuate_transition(
        api,
        transition_id=transition_id,
        successor_partner_id=successor["id"],
        effective_on="2026-12-31",
        matter_id=matter_id,
    )
    assert read_matter(api, matter_id)["responsible_attorney_id"] == successor["id"]
    assert read_partner(api, departing["id"])["status"] == "NOTICE_GIVEN"
    stale_version = matter_version(api, matter_id)

    posted = post_financials(
        api,
        matter_id,
        billed_delta_cents=250_000,
        collected_delta_cents=200_000,
        direct_cost_delta_cents=0,
        expected_matter_version=stale_version,
    )
    assert posted["version"] == stale_version + 1

    replay = api.void_credit_transition(
        transition_id,
        void_transition_payload("The successor declined the relationship.", stale_version),
        admin,
    )
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION.value, 412)

    untouched = read_transition(api, transition_id)
    assert untouched["state"] == "EFFECTIVE"
    assert untouched["void_reason"] is None
    assert read_matter(api, matter_id)["responsible_attorney_id"] == successor["id"]

    voided = void_transition(
        api,
        transition_id=transition_id,
        void_reason="The successor declined the relationship.",
        expected_matter_version=posted["version"],
    )
    assert voided["state"] == "VOIDED"

    restored = read_matter(api, matter_id)
    assert restored["responsible_attorney_id"] == departing["id"]
    assert restored["origination_pct_assigned"] == approx2(100.00)
    rows = matter_allocations(api, matter_id)
    assert find_allocation(rows, "ORIGINATING", departing["id"], "ACTIVE")[
        "credit_pct"
    ] == approx2(100.00)
    assert find_allocation(rows, "ORIGINATING", successor["id"], "SUPERSEDED") is not None


def test_responsible_matter_count_reconciles_across_create_close_and_write_off(api):
    """PRD 3.1: "`responsible_matter_count` is the number of matters currently in
    `OPEN` whose `responsible_attorney_id` is this partner — it rises when a
    matter opens under them, falls when that matter closes or is written off, and
    moves in both directions when a departure reassigns responsibility."

    Design: Corner/cross_cutting_complexity_layers/responsible_matter_count_reconciles_across_create_close_and_write_off
    """
    create_cycle(api)
    partner = create_partner(api, full_name="Ada Origin")
    assert read_partner(api, partner["id"])["responsible_matter_count"] == 0

    first = create_matter(
        api,
        billing_attorney_id=partner["id"],
        client_key="CLI-M1",
        client_display_name="Matter One Holdings",
        opened_on="2026-01-10",
    )
    assert read_partner(api, partner["id"])["responsible_matter_count"] == 1

    second = create_matter(
        api,
        billing_attorney_id=partner["id"],
        client_key="CLI-M2",
        client_display_name="Matter Two Holdings",
        opened_on="2026-02-10",
    )
    assert read_partner(api, partner["id"])["responsible_matter_count"] == 2

    closed = set_matter_status(api, first["id"], "CLOSED")
    assert closed["state"] == "CLOSED"
    assert read_partner(api, partner["id"])["responsible_matter_count"] == 1

    written_off = set_matter_status(
        api,
        second["id"],
        "WRITTEN_OFF",
        written_off_reason="The client entered insolvency proceedings.",
    )
    assert written_off["state"] == "WRITTEN_OFF"
    assert read_partner(api, partner["id"])["responsible_matter_count"] == 0

    rows, meta = validate_paginated(api.list_matters(make_cycle_admin_headers()))
    assert meta["total_count"] == 2
    assert [row["id"] for row in rows] == [first["id"], second["id"]]
    assert matter_allocations(api, second["id"], state="ACTIVE") == []
