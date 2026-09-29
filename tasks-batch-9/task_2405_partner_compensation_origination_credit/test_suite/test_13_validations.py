"""Validation corners: cycle-year uniqueness, the two population-driven
completeness gates, path resolution ahead of entity state, an interval sum that
lands exactly on the ceiling, and the state rung outranking the version rung."""

from test_helpers import (
    UNKNOWN_UUID,
    ApiErrorId,
    adjudicate_claim_payload,
    advance_cycle,
    advance_cycle_payload,
    approx2,
    approx4,
    assign_peer_review,
    create_assessment,
    create_committee_member,
    create_credit_arbiter,
    create_cycle,
    create_cycle_payload,
    create_matter,
    create_partner,
    file_claim,
    find_allocation,
    make_credit_arbiter_headers,
    make_cycle_admin_headers,
    make_partner_headers,
    matter_allocations,
    matter_status_payload,
    matter_version,
    peer_review_recuse_payload,
    read_assessment,
    read_claim,
    read_cycle,
    read_matter,
    score_peer_review,
    submit_assessment,
    submit_claim,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = make_cycle_admin_headers()


def test_duplicate_fiscal_year_violates_the_cycle_uniqueness_constraint(api):
    """PRD 3.8: "A `CycleAdmin` opens a compensation cycle for a `fiscal_year`
    between 2000 and 2100, which must be unique across all cycles — a repeat is
    `ERR_DUPLICATE_CYCLE`."

    Design: Corner/validations/duplicate_fiscal_year_violates_the_cycle_uniqueness_constraint
    """
    original = create_cycle(api, fiscal_year=2026)
    advance_cycle(api, original["id"], "SELF_ASSESSMENT")

    # Every other parameter differs; only the fiscal year repeats.
    repeat = api.create_cycle(
        create_cycle_payload(
            fiscal_year=2026,
            distributable_pool_cents=777_000_000,
            lockstep_unit_cents=1_000_000,
            discretionary_pool_pct=0.3500,
            draw_pct=0.5000,
            claim_deadline_on="2026-08-31",
            assessment_deadline_on="2026-09-30",
        ),
        ADMIN,
    )
    validate_error(repeat, ApiErrorId.ERR_DUPLICATE_CYCLE.value, 409)

    rows, meta = validate_paginated(api.list_cycles(ADMIN))
    assert meta["total_count"] == 1
    assert len(rows) == 1

    untouched = read_cycle(api, original["id"])
    assert untouched["state"] == "SELF_ASSESSMENT"
    assert untouched["distributable_pool_cents"] == original["distributable_pool_cents"]
    assert untouched["draw_pct"] == approx4(original["draw_pct"])

    # The constraint is on the year alone, so a different year is admitted.
    next_year = validate_success(
        api.create_cycle(
            create_cycle_payload(
                fiscal_year=2027,
                claim_deadline_on="2027-09-30",
                assessment_deadline_on="2027-10-31",
            ),
            ADMIN,
        ),
        201,
    )
    assert next_year["fiscal_year"] == 2027
    assert next_year["state"] == "OPEN_INTAKE"


def test_evaluation_required_flag_switches_the_assessment_gate_on_and_off(api):
    """PRD 3.8: "`SELF_ASSESSMENT → PEER_REVIEW` is gated on the evaluation
    population having spoken: every partner whose `evaluation_required` is true
    and whose `status` is `ACTIVE` or `NOTICE_GIVEN` must have exactly one
    self-assessment for this cycle whose `state` is `SUBMITTED` or `ACCEPTED`,
    failing which `ERR_ASSESSMENTS_INCOMPLETE`."

    Design: Corner/validations/evaluation_required_flag_switches_the_assessment_gate_on_and_off
    """
    cycle = create_cycle(api)
    exempt = create_partner(api, full_name="Ex Empt", evaluation_required=False)
    required = create_partner(api, full_name="Reba Quired", practice_group="TAX")
    advance_cycle(api, cycle["id"], "SELF_ASSESSMENT")

    with_nothing = api.advance_cycle(cycle["id"], advance_cycle_payload("PEER_REVIEW"), ADMIN)
    validate_error(with_nothing, ApiErrorId.ERR_ASSESSMENTS_INCOMPLETE.value, 409)

    draft = create_assessment(api, cycle_id=cycle["id"], partner_id=required["id"])
    assert draft["state"] == "DRAFT"
    # A DRAFT row does not satisfy the gate; only SUBMITTED or ACCEPTED does.
    with_draft = api.advance_cycle(cycle["id"], advance_cycle_payload("PEER_REVIEW"), ADMIN)
    validate_error(with_draft, ApiErrorId.ERR_ASSESSMENTS_INCOMPLETE.value, 409)

    submit_assessment(api, draft["id"], required["id"])
    opened = validate_success(
        api.advance_cycle(cycle["id"], advance_cycle_payload("PEER_REVIEW"), ADMIN), 200
    )
    assert opened["state"] == "PEER_REVIEW"

    # The exempt partner never had to speak: one assessment covers the cycle.
    rows, meta = validate_paginated(api.list_self_assessments(ADMIN, {"cycle_id": cycle["id"]}))
    assert meta["total_count"] == 1
    assert rows[0]["partner_id"] == required["id"]
    assert rows[0]["state"] == "SUBMITTED"
    assert exempt["evaluation_required"] is False


def test_one_recusal_strands_the_assessment_below_the_scored_review_minimum(api):
    """PRD 3.6: "Recusal leaves `scored_review_count` untouched, which is exactly
    how a late recusal can strand an assessment below the two scored reviews the
    firm requires." PRD 3.8: "and every self-assessment must carry at least two
    reviews in `SCORED`, failing which `ERR_PEER_REVIEWS_INCOMPLETE`."

    Design: Corner/validations/one_recusal_strands_the_assessment_below_the_scored_review_minimum
    """
    cycle = create_cycle(api)
    subject = create_partner(api, full_name="Stan Ded")
    scorer = create_committee_member(api, full_name="Vera Scorer", practice_group="TAX")
    recuser = create_committee_member(api, full_name="Rhea Cuser", practice_group="IP")
    replacement = create_committee_member(api, full_name="Rip Lacement", practice_group="LITIGATION")
    advance_cycle(api, cycle["id"], "SELF_ASSESSMENT")
    assessment = create_assessment(api, cycle_id=cycle["id"], partner_id=subject["id"])
    submit_assessment(api, assessment["id"], subject["id"])

    scored = assign_peer_review(api, assessment["id"], scorer["id"])
    score_peer_review(api, scored["id"], scorer["id"], 4, 4, 4)
    assigned = assign_peer_review(api, assessment["id"], recuser["id"])
    recused = validate_success(
        api.decide_peer_review(
            assigned["id"],
            peer_review_recuse_payload(),
            make_partner_headers(recuser["id"]),
        ),
        200,
    )
    assert recused["state"] == "RECUSED"
    assert recused["composite_score"] is None
    assert recused["technical_score"] is None
    assert recused["recusal_reason"] is not None

    stranded = read_assessment(api, assessment["id"])
    # Two reviews exist but the recusal contributed nothing to the count.
    assert stranded["scored_review_count"] == 1
    assert stranded["mean_peer_score"] == approx4(4.0000)

    advance_cycle(api, cycle["id"], "PEER_REVIEW")
    blocked = api.advance_cycle(cycle["id"], advance_cycle_payload("DELIBERATION"), ADMIN)
    validate_error(blocked, ApiErrorId.ERR_PEER_REVIEWS_INCOMPLETE.value, 409)

    third = assign_peer_review(api, assessment["id"], replacement["id"])
    filled = score_peer_review(api, third["id"], replacement["id"], 3, 3, 3)
    assert filled["composite_score"] == approx4(3.0000)

    healed = read_assessment(api, assessment["id"])
    assert healed["scored_review_count"] == 2
    assert healed["mean_peer_score"] == approx4(3.5000)

    deliberating = validate_success(
        api.advance_cycle(cycle["id"], advance_cycle_payload("DELIBERATION"), ADMIN), 200
    )
    assert deliberating["state"] == "DELIBERATION"


def test_path_existence_is_checked_before_entity_state(api):
    """PRD 2.10: "Identifiers in a path are resolved strictly left to right, and
    the first one that fails to resolve determines the response." PRD 2.11: "The
    ladder is total and it is the same on every endpoint; a check lower down is
    never allowed to mask a check higher up."

    Design: Corner/validations/path_existence_is_checked_before_entity_state
    """
    actor = create_partner(api, full_name="Path Finder")

    # Path resolution sits above every state-of-row check, so an unknown claim
    # reports the missing row rather than ERR_CLAIM_NOT_IN_DRAFT.
    missing_claim = api.submit_credit_claim(
        UNKNOWN_UUID, {}, make_partner_headers(actor["id"])
    )
    validate_error(missing_claim, ApiErrorId.ERR_CLAIM_NOT_FOUND.value, 404)

    # Likewise an unknown matter reports the missing row rather than
    # ERR_MATTER_NOT_OPEN, even though the requested edge would fail anyway.
    missing_matter = api.set_matter_status(
        UNKNOWN_UUID, matter_status_payload("CLOSED"), ADMIN
    )
    validate_error(missing_matter, ApiErrorId.ERR_MATTER_NOT_FOUND.value, 404)

    _claims, claim_meta = validate_paginated(api.list_credit_claims(ADMIN))
    assert claim_meta["total_count"] == 0
    _matters, matter_meta = validate_paginated(api.list_matters(ADMIN))
    assert matter_meta["total_count"] == 0


def test_origination_interval_sum_landing_exactly_on_one_hundred_is_accepted(api):
    """PRD 3.4: "Only allocations whose `credit_role` is `ORIGINATING`
    participate, and their `credit_pct` values are summed across every set of
    half-open validity windows that overlap in time; if any such overlapping set
    would exceed 100.00 on a matter, the write that would create it is refused
    with `ERR_CREDIT_INTERVAL_OVERSUBSCRIBED`."

    Design: Corner/validations/origination_interval_sum_landing_exactly_on_one_hundred_is_accepted
    """
    cycle = create_cycle(api)
    lead = create_partner(api, full_name="Bill Ing")
    major = create_partner(api, full_name="Maj Ority", practice_group="TAX")
    minor = create_partner(api, full_name="Min Ority", practice_group="IP")
    arbiter = create_credit_arbiter(api, full_name="Arya Arbiter", practice_group="REGULATORY")
    matter = create_matter(
        api,
        billing_attorney_id=lead["id"],
        responsible_attorney_id=lead["id"],
        client_key="CLI-IV",
        client_display_name="Interval Industries",
        matter_type="NEW_CLIENT",
        opened_on="2026-01-10",
    )
    arbiter_headers = make_credit_arbiter_headers(arbiter["id"])

    first = file_claim(
        api,
        cycle_id=cycle["id"],
        matter_id=matter["id"],
        claimant_id=major["id"],
        claim_basis="NEW_CLIENT",
        requested_pct=60.00,
    )
    submit_claim(api, first["id"], major["id"])
    second = file_claim(
        api,
        cycle_id=cycle["id"],
        matter_id=matter["id"],
        claimant_id=minor["id"],
        claim_basis="NEW_CLIENT",
        requested_pct=40.00,
    )
    submit_claim(api, second["id"], minor["id"])

    allocated_first = validate_success(
        api.adjudicate_credit_claim(
            first["id"],
            adjudicate_claim_payload("ALLOCATE", matter_version(api, matter["id"]), approved_pct=60.00),
            arbiter_headers,
        ),
        200,
    )
    assert allocated_first["state"] == "ALLOCATED"
    assert allocated_first["approved_pct"] == approx2(60.00)
    assert read_matter(api, matter["id"])["origination_pct_assigned"] == approx2(60.00)

    # 60.00 + 40.00 lands exactly on the ceiling, and the rule refuses only a
    # sum that would exceed it.
    allocated_second = validate_success(
        api.adjudicate_credit_claim(
            second["id"],
            adjudicate_claim_payload("ALLOCATE", matter_version(api, matter["id"]), approved_pct=40.00),
            arbiter_headers,
        ),
        200,
    )
    assert allocated_second["state"] == "ALLOCATED"
    assert read_matter(api, matter["id"])["origination_pct_assigned"] == approx2(100.00)

    rows = matter_allocations(api, matter["id"], credit_role="ORIGINATING", state="ACTIVE")
    assert len(rows) == 2
    assert find_allocation(rows, "ORIGINATING", major["id"])["credit_pct"] == approx2(60.00)
    assert find_allocation(rows, "ORIGINATING", minor["id"])["credit_pct"] == approx2(40.00)
    assert all(row["credit_through"] is None for row in rows)


def test_state_check_outranks_the_occ_check_on_an_already_allocated_claim(api):
    """PRD 3.4: "A claim that is in neither `SUBMITTED` nor `DISPUTED` is not
    adjudicable at all, and a `SPLIT` or `REMAND` aimed at a claim that is not
    `DISPUTED` is likewise not adjudicable; both report
    `ERR_CLAIM_NOT_ADJUDICABLE`." PRD 2.8: "Adjudicating an origination credit
    claim requires `expected_matter_version` matching the claim's matter's
    current `version`."

    Design: Corner/validations/state_check_outranks_the_occ_check_on_an_already_allocated_claim
    """
    cycle = create_cycle(api)
    lead = create_partner(api, full_name="Bill Ing")
    first_claimant = create_partner(api, full_name="Prima Claim", practice_group="TAX")
    second_claimant = create_partner(api, full_name="Secunda Claim", practice_group="IP")
    arbiter = create_credit_arbiter(api, full_name="Arya Arbiter", practice_group="REGULATORY")
    matter = create_matter(
        api,
        billing_attorney_id=lead["id"],
        responsible_attorney_id=lead["id"],
        client_key="CLI-LD",
        client_display_name="Ladder Logistics",
        matter_type="NEW_CLIENT",
        opened_on="2026-01-12",
    )
    arbiter_headers = make_credit_arbiter_headers(arbiter["id"])

    first = file_claim(
        api,
        cycle_id=cycle["id"],
        matter_id=matter["id"],
        claimant_id=first_claimant["id"],
        claim_basis="NEW_CLIENT",
        requested_pct=50.00,
    )
    submit_claim(api, first["id"], first_claimant["id"])
    second = file_claim(
        api,
        cycle_id=cycle["id"],
        matter_id=matter["id"],
        claimant_id=second_claimant["id"],
        claim_basis="NEW_CLIENT",
        requested_pct=50.00,
    )
    submit_claim(api, second["id"], second_claimant["id"])

    pinned = matter_version(api, matter["id"])
    allocated = validate_success(
        api.adjudicate_credit_claim(
            first["id"],
            adjudicate_claim_payload("ALLOCATE", pinned, approved_pct=50.00),
            arbiter_headers,
        ),
        200,
    )
    assert allocated["state"] == "ALLOCATED"
    assert matter_version(api, matter["id"]) > pinned

    # The replay carries both faults: the claim has left SUBMITTED and the
    # matter version is stale. The state rung sits above the version rung.
    replay = api.adjudicate_credit_claim(
        first["id"],
        adjudicate_claim_payload("ALLOCATE", pinned, approved_pct=50.00),
        arbiter_headers,
    )
    validate_error(replay, ApiErrorId.ERR_CLAIM_NOT_ADJUDICABLE.value, 409)

    # With the state fault removed the same stale version surfaces on its own.
    stale = api.adjudicate_credit_claim(
        second["id"],
        adjudicate_claim_payload("ALLOCATE", pinned, approved_pct=50.00),
        arbiter_headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value, 412)

    assert read_claim(api, first["id"])["state"] == "ALLOCATED"
    assert read_claim(api, first["id"])["approved_pct"] == approx2(50.00)
    assert read_claim(api, second["id"])["state"] == "SUBMITTED"
    assert read_matter(api, matter["id"])["origination_pct_assigned"] == approx2(50.00)
