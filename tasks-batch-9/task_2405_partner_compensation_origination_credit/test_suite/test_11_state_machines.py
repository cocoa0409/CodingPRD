"""State machines: declared initial states, the claim happy path, the side
effects of matter creation and of deliberation entry, the completeness gate out
of OPEN_INTAKE, non-adjacent and terminal stage refusals, transition replay and
the write-off supersession cascade."""

from test_helpers import (
    ApiErrorId,
    adjudicate_claim_payload,
    advance_cycle,
    advance_cycle_payload,
    advance_cycle_to,
    approx2,
    approx4,
    assign_peer_review,
    create_assessment,
    create_committee_member,
    create_credit_arbiter,
    create_credit_claim_payload,
    create_cycle,
    create_cycle_payload,
    create_matter,
    create_matter_payload,
    create_partner,
    create_self_assessment_payload,
    cycle_version,
    file_claim,
    find_allocation,
    make_credit_arbiter_headers,
    make_cycle_admin_headers,
    make_partner_headers,
    matter_allocations,
    matter_status_payload,
    matter_version,
    post_financials,
    read_claim,
    read_cycle,
    read_matter,
    read_partner,
    score_peer_review,
    submit_assessment,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_new_rows_start_in_their_declared_initial_states(api):
    """PRD 3.2: "The matter begins in state `OPEN`, its
    `prior_responsible_attorney_id` and `written_off_reason` both null, and
    creation returns 201 Created." PRD 3.8: "Claims left sitting in `DRAFT` are
    allowed to lapse — only in-flight claims block the stage change."

    Design: Corner/state_machines/new_rows_start_in_their_declared_initial_states
    """
    admin = make_cycle_admin_headers()

    cycle = validate_success(api.create_cycle(create_cycle_payload(), admin), 201)
    assert cycle["state"] == "OPEN_INTAKE"

    partner = validate_success(
        api.create_partner(
            {
                "full_name": "Ini Tial",
                "practice_group": "CORPORATE",
                "compensation_model": "FORMULA",
                "admission_year": 2014,
            },
            admin,
        ),
        201,
    )
    assert partner["status"] == "ACTIVE"

    matter = validate_success(
        api.create_matter(
            create_matter_payload(
                client_key="CLI-IN",
                client_display_name="Initial State Co",
                matter_type="NEW_CLIENT",
                practice_group="CORPORATE",
                opened_on="2026-02-01",
                billing_attorney_id=partner["id"],
                responsible_attorney_id=partner["id"],
            ),
            admin,
        ),
        201,
    )
    assert matter["state"] == "OPEN"
    assert matter["prior_responsible_attorney_id"] is None
    assert matter["written_off_reason"] is None

    allocations = matter_allocations(api, matter["id"])
    assert len(allocations) == 2
    assert all(row["state"] == "ACTIVE" for row in allocations)

    claim = validate_success(
        api.create_credit_claim(
            create_credit_claim_payload(
                cycle_id=cycle["id"],
                matter_id=matter["id"],
                claim_basis="NEW_CLIENT",
                requested_pct=100.00,
                narrative="I originated this client.",
            ),
            make_partner_headers(partner["id"]),
        ),
        201,
    )
    assert claim["state"] == "DRAFT"
    assert claim["revision_count"] == 0
    assert claim["remand_count"] == 0

    advanced = validate_success(
        api.advance_cycle(cycle["id"], advance_cycle_payload("SELF_ASSESSMENT"), admin), 200
    )
    assert advanced["state"] == "SELF_ASSESSMENT"

    assessment = validate_success(
        api.create_self_assessment(
            create_self_assessment_payload(
                cycle_id=cycle["id"],
                narrative="My year in review.",
                claimed_origination_pct_total=100.00,
                claimed_non_billable_hours=0.00,
            ),
            make_partner_headers(partner["id"]),
        ),
        201,
    )
    assert assessment["state"] == "DRAFT"
    assert assessment["revision_count"] == 0
    assert assessment["scored_review_count"] == 0


def test_claim_allocate_moves_draft_to_allocated_and_writes_the_allocation(api):
    """PRD 3.4: "The claimant's share of the arbiter's `approved_pct` depends on
    the asserted basis — a genuinely new client is not shared at all and the
    claimant keeps 100.00 percent of it, an expanded matter for an existing client
    is shared 60/40 in the claimant's favour, and a cross-sell into a different
    practice group is shared 50/50." "The claim's `counterparty_pct` is *not*
    written on this branch; it remains null, and the complement is expressed only
    as the prior originator's allocation percentage."

    Design: Corner/state_machines/claim_allocate_moves_draft_to_allocated_and_writes_the_allocation
    """
    cycle = create_cycle(api)
    claimant = create_partner(
        api, full_name="Pat Path", practice_group="CORPORATE", admission_year=2014
    )
    arbiter = create_credit_arbiter(
        api, full_name="Abe Arbiter", practice_group="REGULATORY", admission_year=2004
    )
    matter = create_matter(
        api,
        billing_attorney_id=claimant["id"],
        responsible_attorney_id=claimant["id"],
        client_key="CLI-NW",
        client_display_name="Brand New Client LLC",
        matter_type="NEW_CLIENT",
        practice_group="CORPORATE",
        opened_on="2026-02-01",
    )
    opening_version = matter["version"]
    claim = file_claim(
        api,
        cycle_id=cycle["id"],
        matter_id=matter["id"],
        claimant_id=claimant["id"],
        claim_basis="NEW_CLIENT",
        requested_pct=80.00,
        narrative="First engagement with this client, sourced by me.",
    )

    submitted = validate_success(
        api.submit_credit_claim(claim["id"], {}, make_partner_headers(claimant["id"])), 200
    )
    assert submitted["state"] == "SUBMITTED"

    allocated = validate_success(
        api.adjudicate_credit_claim(
            claim["id"],
            adjudicate_claim_payload("ALLOCATE", opening_version, approved_pct=80.00),
            make_credit_arbiter_headers(arbiter["id"]),
        ),
        200,
    )
    assert allocated["state"] == "ALLOCATED"
    assert allocated["approved_pct"] == approx2(80.00)
    assert allocated["counterparty_pct"] is None
    assert allocated["resolved_prior_originator_id"] is None

    originating = matter_allocations(api, matter["id"], credit_role="ORIGINATING")
    assert len(originating) == 1
    assert originating[0]["partner_id"] == claimant["id"]
    assert originating[0]["credit_pct"] == approx2(80.00)
    assert originating[0]["source"] == "CLAIM_ALLOCATED"
    assert originating[0]["state"] == "ACTIVE"

    reread = read_matter(api, matter["id"])
    assert reread["origination_pct_assigned"] == approx2(80.00)
    assert reread["version"] > opening_version


def test_matter_creation_seeds_the_billing_and_responsible_allocations(api):
    """PRD 3.2: "A `BILLING` allocation is created for the billing attorney and a
    `RESPONSIBLE` allocation for the responsible attorney, each at `credit_pct` of
    100.00, each with `source` of `DEFAULT_BILLING`, `credit_from` equal to the
    matter's `opened_on`, `credit_through` null and `state` of `ACTIVE`." "No
    `ORIGINATING` allocation and no `WORKING` allocation is created here:
    origination credit arrives only through claim adjudication, and working credit
    only through hour verification."

    Design: Corner/state_machines/matter_creation_seeds_the_billing_and_responsible_allocations
    """
    admin = make_cycle_admin_headers()
    billing = create_partner(
        api, full_name="Bill Ing", practice_group="CORPORATE", admission_year=2013
    )
    responsible = create_partner(
        api, full_name="Resp Onsible", practice_group="CORPORATE", admission_year=2015
    )

    matter = validate_success(
        api.create_matter(
            create_matter_payload(
                client_key="CLI-SE",
                client_display_name="Side Effect Holdings",
                matter_type="EXISTING",
                practice_group="CORPORATE",
                opened_on="2026-03-01",
                billing_attorney_id=billing["id"],
                responsible_attorney_id=responsible["id"],
            ),
            admin,
        ),
        201,
    )

    billing_rows, _ = validate_paginated(
        api.list_matter_credit_allocations(matter["id"], admin, {"credit_role": "BILLING"})
    )
    responsible_rows, _ = validate_paginated(
        api.list_matter_credit_allocations(matter["id"], admin, {"credit_role": "RESPONSIBLE"})
    )
    assert len(billing_rows) == 1
    assert len(responsible_rows) == 1
    assert billing_rows[0]["partner_id"] == billing["id"]
    assert billing_rows[0]["credit_pct"] == approx2(100.00)
    assert billing_rows[0]["source"] == "DEFAULT_BILLING"
    assert responsible_rows[0]["partner_id"] == responsible["id"]
    assert responsible_rows[0]["credit_pct"] == approx2(100.00)
    assert responsible_rows[0]["source"] == "DEFAULT_BILLING"

    assert read_partner(api, responsible["id"])["responsible_matter_count"] == 1
    assert read_partner(api, billing["id"])["responsible_matter_count"] == 0
    assert matter_allocations(api, matter["id"], credit_role="ORIGINATING") == []
    assert matter_allocations(api, matter["id"], credit_role="WORKING") == []
    assert read_matter(api, matter["id"])["origination_pct_assigned"] == approx2(0.00)


def test_deliberation_entry_fans_out_ballots_and_awards_by_partner_config(api):
    """PRD 3.7: "One ballot is created in `PENDING` for every pairing of a subject
    partner — one whose `compensation_model` is `DISCRETIONARY`, whose
    `evaluation_required` is true and whose `status` is `ACTIVE` or `NOTICE_GIVEN`
    — with a committee member, being any partner whose `is_committee_member` is
    true and whose `status` is `ACTIVE`." PRD 3.8: "On success the edge recomputes
    `realization_pct`, `profitability_index_contribution` and
    `profitability_index_fully_loaded` on every matter; recomputes
    `credited_collection_provisional_cents` and `credited_collection_final_cents`
    on every `ACTIVE` allocation; recomputes every partner's
    `non_billable_points`; recomputes every partner's `formula_score_provisional`
    and `formula_score_final` along with the cycle's `total_formula_score`;
    creates the `PENDING` ballots described in section 3.7; and creates one
    compensation award for every partner whose `evaluation_required` is true and
    whose `status` is `ACTIVE` or `NOTICE_GIVEN`, in award state `PROPOSED` and
    payment state `PENDING`, with `target_award_cents` of 0 and `basis_model`
    snapshotted from that partner's `compensation_model` at that moment."

    Design: Corner/state_machines/deliberation_entry_fans_out_ballots_and_awards_by_partner_config
    """
    admin = make_cycle_admin_headers()
    cycle = create_cycle(api)
    subject = create_partner(
        api,
        full_name="Sub Ject",
        practice_group="CORPORATE",
        compensation_model="DISCRETIONARY",
        admission_year=2012,
    )
    formula = create_partner(
        api, full_name="For Mula", practice_group="IP", admission_year=2013
    )
    first_member = create_committee_member(
        api, full_name="Cee One", practice_group="TAX", admission_year=2004
    )
    second_member = create_committee_member(
        api, full_name="Cee Two", practice_group="REGULATORY", admission_year=2006
    )
    advance_cycle(api, cycle["id"], "SELF_ASSESSMENT")

    for partner, scores in ((subject, (4, 4, 4)), (formula, (3, 3, 3))):
        assessment = create_assessment(
            api, cycle_id=cycle["id"], partner_id=partner["id"], claimed_non_billable_hours=0.00
        )
        submit_assessment(api, assessment["id"], partner["id"])
        for reviewer in (first_member, second_member):
            review = assign_peer_review(api, assessment["id"], reviewer["id"])
            score_peer_review(api, review["id"], reviewer["id"], *scores)
    advance_cycle(api, cycle["id"], "PEER_REVIEW")

    advanced = validate_success(
        api.advance_cycle(cycle["id"], advance_cycle_payload("DELIBERATION"), admin), 200
    )
    assert advanced["state"] == "DELIBERATION"

    ballots, ballot_meta = validate_paginated(api.list_ballots(admin, {"cycle_id": cycle["id"]}))
    assert ballot_meta["total_count"] == 2
    assert {row["subject_partner_id"] for row in ballots} == {subject["id"]}
    assert {row["committee_member_id"] for row in ballots} == {
        first_member["id"],
        second_member["id"],
    }
    assert all(row["state"] == "PENDING" for row in ballots)

    formula_ballots, _ = validate_paginated(
        api.list_ballots(admin, {"cycle_id": cycle["id"], "subject_partner_id": formula["id"]})
    )
    assert formula_ballots == []

    awards, award_meta = validate_paginated(api.list_awards(admin, {"cycle_id": cycle["id"]}))
    assert award_meta["total_count"] == 2
    assert {row["partner_id"] for row in awards} == {subject["id"], formula["id"]}

    member_awards, _ = validate_paginated(
        api.list_awards(admin, {"cycle_id": cycle["id"], "partner_id": first_member["id"]})
    )
    assert member_awards == []

    formula_award = [row for row in awards if row["partner_id"] == formula["id"]][0]
    assert formula_award["award_state"] == "PROPOSED"
    assert formula_award["payment_state"] == "PENDING"
    assert formula_award["basis_model"] == "FORMULA"
    assert formula_award["target_award_cents"] == 0

    subject_award = [row for row in awards if row["partner_id"] == subject["id"]][0]
    assert subject_award["basis_model"] == "DISCRETIONARY"
    assert subject_award["award_state"] == "PROPOSED"
    assert subject_award["payment_state"] == "PENDING"


def test_advance_out_of_open_intake_is_blocked_by_an_in_flight_claim(api):
    """PRD 3.8: "`OPEN_INTAKE → SELF_ASSESSMENT` is gated on origination disputes
    being finished: no credit claim of the cycle may still be in `SUBMITTED` or
    `DISPUTED`, and one that is reports `ERR_UNRESOLVED_CLAIMS`." PRD 3.4: "It
    does, however, install a fallback so that no matter is left with unassigned
    origination credit: when the matter holds no credit allocation whose
    `credit_role` is `ORIGINATING` and whose `state` is `ACTIVE`, one is created
    for the matter's `billing_attorney_id` at `credit_pct` of 100.00 with `source`
    of `DEFAULT_BILLING`."

    Design: Corner/state_machines/advance_out_of_open_intake_is_blocked_by_an_in_flight_claim
    """
    admin = make_cycle_admin_headers()
    cycle = create_cycle(api)
    claimant = create_partner(
        api, full_name="Gate Keeper", practice_group="CORPORATE", admission_year=2014
    )
    arbiter = create_credit_arbiter(
        api, full_name="Arb Two", practice_group="REGULATORY", admission_year=2004
    )
    matter = create_matter(
        api,
        billing_attorney_id=claimant["id"],
        responsible_attorney_id=claimant["id"],
        client_key="CLI-GT",
        client_display_name="Gated Client Co",
        matter_type="NEW_CLIENT",
        practice_group="CORPORATE",
        opened_on="2026-02-10",
    )
    claim = file_claim(
        api,
        cycle_id=cycle["id"],
        matter_id=matter["id"],
        claimant_id=claimant["id"],
        claim_basis="NEW_CLIENT",
        requested_pct=100.00,
        narrative="Sourced through my network.",
    )
    validate_success(
        api.submit_credit_claim(claim["id"], {}, make_partner_headers(claimant["id"])), 200
    )
    version_before = cycle_version(api, cycle["id"])

    blocked = api.advance_cycle(cycle["id"], advance_cycle_payload("SELF_ASSESSMENT"), admin)
    validate_error(blocked, ApiErrorId.ERR_UNRESOLVED_CLAIMS.value, 409)

    held = read_cycle(api, cycle["id"])
    assert held["state"] == "OPEN_INTAKE"
    assert held["version"] == version_before

    rejected = validate_success(
        api.adjudicate_credit_claim(
            claim["id"],
            adjudicate_claim_payload("REJECT", matter_version(api, matter["id"])),
            make_credit_arbiter_headers(arbiter["id"]),
        ),
        200,
    )
    assert rejected["state"] == "REJECTED"
    assert rejected["approved_pct"] == approx2(0.00)

    cleared = validate_success(
        api.advance_cycle(cycle["id"], advance_cycle_payload("SELF_ASSESSMENT"), admin), 200
    )
    assert cleared["state"] == "SELF_ASSESSMENT"

    fallback = find_allocation(
        matter_allocations(api, matter["id"]), "ORIGINATING", claimant["id"], "ACTIVE"
    )
    assert fallback["credit_pct"] == approx2(100.00)
    assert fallback["source"] == "DEFAULT_BILLING"


def test_open_intake_refuses_a_non_adjacent_target_state(api):
    """PRD 3.8: "Every stage change is requested by naming a `target_state`, and a
    `target_state` not reachable from the cycle's current stage is refused with
    `ERR_INVALID_CYCLE_TRANSITION`."

    Design: Corner/state_machines/open_intake_refuses_a_non_adjacent_target_state
    """
    admin = make_cycle_admin_headers()
    cycle = create_cycle(api)
    opening_version = cycle["version"]

    for target in (
        "DELIBERATION",
        "AWARDS_PUBLISHED",
        "TRUE_UP_OPEN",
        "CLOSED",
        "OPEN_INTAKE",
    ):
        response = api.advance_cycle(cycle["id"], advance_cycle_payload(target), admin)
        validate_error(response, ApiErrorId.ERR_INVALID_CYCLE_TRANSITION.value, 409)

    held = read_cycle(api, cycle["id"])
    assert held["state"] == "OPEN_INTAKE"
    assert held["version"] == opening_version

    ballots, ballot_meta = validate_paginated(api.list_ballots(admin, {"cycle_id": cycle["id"]}))
    assert ballots == []
    assert ballot_meta["total_count"] == 0
    awards, award_meta = validate_paginated(api.list_awards(admin, {"cycle_id": cycle["id"]}))
    assert awards == []
    assert award_meta["total_count"] == 0


def test_closed_cycle_refuses_every_further_advance_and_stays_locked(api):
    """PRD 3.8: "Closing moves every award of the cycle from award state
    `PUBLISHED` to the terminal `FINALIZED`, sets `confidentiality_locked` to
    true, and puts the cycle in its terminal `CLOSED` stage — at which point it is
    no longer eligible to be the anchor cycle, and only a `CycleAdmin` may read
    its ballots." "`AWARDS_PUBLISHED → DELIBERATION` is the reconsideration
    reopen, and it is bounded twice over: the cycle's `reopen_count` must still be
    below 1, and no award of the cycle may have reached payment state `TRUED_UP`
    or `SETTLED`; either failure is `ERR_CYCLE_NOT_REOPENABLE`."

    Design: Corner/state_machines/closed_cycle_refuses_every_further_advance_and_stays_locked
    """
    admin = make_cycle_admin_headers()
    cycle = create_cycle(api)
    create_committee_member(api, full_name="Lock One", practice_group="TAX", admission_year=2004)
    create_committee_member(api, full_name="Lock Two", practice_group="IP", admission_year=2006)

    closed = advance_cycle_to(api, cycle["id"], "CLOSED")
    assert closed["state"] == "CLOSED"
    assert closed["confidentiality_locked"] is True
    closed_version = closed["version"]

    for target in ("TRUE_UP_OPEN", "DELIBERATION", "CLOSED"):
        response = api.advance_cycle(cycle["id"], advance_cycle_payload(target), admin)
        validate_error(response, ApiErrorId.ERR_INVALID_CYCLE_TRANSITION.value, 409)

    locked = read_cycle(api, cycle["id"])
    assert locked["state"] == "CLOSED"
    assert locked["confidentiality_locked"] is True
    assert locked["version"] == closed_version
    assert locked["unsettled_award_count"] == 0
    assert locked["reopen_count"] == 0


def test_second_submit_of_the_same_claim_is_refused_not_replayed(api):
    """PRD 3.4: "Submitting a claim advances it `DRAFT → SUBMITTED` and closes the
    door on quiet editing. A claim that is not in `DRAFT` yields
    `ERR_CLAIM_NOT_IN_DRAFT`."

    Design: Corner/state_machines/second_submit_of_the_same_claim_is_refused_not_replayed
    """
    admin = make_cycle_admin_headers()
    cycle = create_cycle(api)
    claimant = create_partner(
        api, full_name="Ida Idem", practice_group="CORPORATE", admission_year=2014
    )
    matter = create_matter(
        api,
        billing_attorney_id=claimant["id"],
        responsible_attorney_id=claimant["id"],
        client_key="CLI-ID",
        client_display_name="Idempotent Industries",
        matter_type="NEW_CLIENT",
        practice_group="CORPORATE",
        opened_on="2026-02-15",
    )
    claim = file_claim(
        api,
        cycle_id=cycle["id"],
        matter_id=matter["id"],
        claimant_id=claimant["id"],
        claim_basis="NEW_CLIENT",
        requested_pct=100.00,
        narrative="Introduced by me at a conference.",
    )

    submitted = validate_success(
        api.submit_credit_claim(claim["id"], {}, make_partner_headers(claimant["id"])), 200
    )
    assert submitted["state"] == "SUBMITTED"
    assert submitted["version"] == 2

    replay = api.submit_credit_claim(claim["id"], {}, make_partner_headers(claimant["id"]))
    validate_error(replay, ApiErrorId.ERR_CLAIM_NOT_IN_DRAFT.value, 409)

    reread = read_claim(api, claim["id"])
    assert reread["state"] == "SUBMITTED"
    assert reread["version"] == submitted["version"]
    assert reread["revision_count"] == 0
    assert reread["remand_count"] == 0

    rows, meta = validate_paginated(api.list_credit_claims(admin, {"cycle_id": cycle["id"]}))
    assert len(rows) == 1
    assert meta["total_count"] == 1


def test_write_off_cascades_supersession_to_every_allocation_on_the_matter(api):
    """PRD 3.2: "Writing a matter off moves it `OPEN → WRITTEN_OFF`, requires a
    `written_off_reason` — absent, the request is malformed — and is the harshest
    of the three: `collected_cents` is left as it stands but the matter is
    excluded from both the provisional accrual basis and the final collected
    basis, every credit allocation on the matter is superseded with `state` set to
    `SUPERSEDED` and `credit_through` set to the logical clock's current date,
    that supersession recomputes `credited_collection_provisional_cents` and
    `credited_collection_final_cents` for every affected partner,
    `responsible_matter_count` on the responsible attorney decrements because the
    counter admits only `OPEN` matters, and the matter's `version` increments."

    Design: Corner/state_machines/write_off_cascades_supersession_to_every_allocation_on_the_matter
    """
    admin = make_cycle_admin_headers()
    cycle = create_cycle(api)
    partner = create_partner(
        api, full_name="Cass Cade", practice_group="CORPORATE", admission_year=2014
    )
    arbiter = create_credit_arbiter(
        api, full_name="Arb Three", practice_group="REGULATORY", admission_year=2004
    )
    matter = create_matter(
        api,
        billing_attorney_id=partner["id"],
        responsible_attorney_id=partner["id"],
        client_key="CLI-WO",
        client_display_name="Written Off Ventures",
        matter_type="NEW_CLIENT",
        practice_group="CORPORATE",
        opened_on="2026-02-20",
    )
    post_financials(
        api,
        matter["id"],
        billed_delta_cents=5_000_000,
        collected_delta_cents=4_000_000,
        direct_cost_delta_cents=1_000_000,
    )
    claim = file_claim(
        api,
        cycle_id=cycle["id"],
        matter_id=matter["id"],
        claimant_id=partner["id"],
        claim_basis="NEW_CLIENT",
        requested_pct=100.00,
        narrative="New client sourced by me.",
    )
    validate_success(
        api.submit_credit_claim(claim["id"], {}, make_partner_headers(partner["id"])), 200
    )
    validate_success(
        api.adjudicate_credit_claim(
            claim["id"],
            adjudicate_claim_payload(
                "ALLOCATE", matter_version(api, matter["id"]), approved_pct=100.00
            ),
            make_credit_arbiter_headers(arbiter["id"]),
        ),
        200,
    )
    assert len(matter_allocations(api, matter["id"], state="ACTIVE")) == 3
    version_before = matter_version(api, matter["id"])

    written_off = validate_success(
        api.set_matter_status(
            matter["id"],
            matter_status_payload(
                "WRITTEN_OFF", written_off_reason="Client insolvent; receivable uncollectible."
            ),
            admin,
        ),
        200,
    )
    assert written_off["state"] == "WRITTEN_OFF"
    assert written_off["written_off_reason"] == "Client insolvent; receivable uncollectible."
    assert written_off["version"] > version_before

    superseded = matter_allocations(api, matter["id"], state="SUPERSEDED")
    assert len(superseded) == 3
    assert {row["credit_role"] for row in superseded} == {
        "ORIGINATING",
        "BILLING",
        "RESPONSIBLE",
    }
    assert all(row["state"] == "SUPERSEDED" for row in superseded)
    assert all(row["credit_through"] == "2026-08-01" for row in superseded)
    assert matter_allocations(api, matter["id"], state="ACTIVE") == []

    assert read_claim(api, claim["id"])["state"] == "ALLOCATED"

    reread = read_partner(api, partner["id"])
    assert reread["credited_collection_provisional_cents"] == 0
    assert reread["credited_collection_final_cents"] == 0
    assert reread["responsible_matter_count"] == 0
    assert reread["formula_score_provisional"] == approx4(0.0000)
