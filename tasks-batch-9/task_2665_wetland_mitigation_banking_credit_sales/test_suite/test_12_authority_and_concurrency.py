"""Authority boundaries and optimistic-concurrency layering on the bank ledger.

Every test in this module builds its own world from scratch: the harness
restarts the server with an empty database before each test.
"""

from test_helpers import (
    ApiErrorId,
    add_milestone,
    api_client,
    approve_release_payload,
    assert_credit_conservation,
    assert_credits,
    assert_cents,
    assert_ledger_shape,
    assert_score,
    bank_state,
    bank_version,
    cancel_sale,
    claim_milestone,
    create_bank_payload,
    create_credit_sale_payload,
    create_deposit_payload,
    create_easement_payload,
    create_prospectus_payload,
    create_vote_payload,
    decide_work_plan_payload,
    fund_stewardship,
    get_success_data,
    ledger_rows,
    make_permittee_headers,
    make_sponsor_headers,
    milestone_state,
    open_monitoring_report,
    permittee_state,
    quote_credits,
    register_permittee,
    register_sponsor,
    report_state,
    reserve_sale,
    review_report_payload,
    sale_state,
    set_clock,
    setup_draft_bank,
    setup_bank_under_review,
    setup_executed_bank,
    setup_sellable_bank,
    submit_monitoring_report,
    validate_error,
    validate_paginated,
)

# The four year-3 measurements of the shared world's monitoring report.
YEAR3_MEASUREMENTS = [
    {"standard_code": "HYDROPERIOD_DAYS", "measured_value": 130},
    {"standard_code": "INVASIVE_COVER_PCT", "measured_value": 8.0},
    {"standard_code": "NATIVE_COVER_PCT", "measured_value": 88.0},
    {"standard_code": "STEM_DENSITY_PER_ACRE", "measured_value": 640},
]


def _world_with_claimed_perf_milestone():
    """A sellable bank whose PERF_YEAR_3 milestone is CLAIMED behind the
    released INSTRUMENT_EXECUTION milestone, with a year-3 monitoring report
    sitting in SUBMITTED. Returns (world, perf_milestone, report)."""
    world = setup_sellable_bank(permittee_required_credits=20.00)
    first = world["milestones"]["INSTRUMENT_EXECUTION"]
    set_clock("2029-08-15T00:00:00Z")
    perf = add_milestone(
        world,
        milestone_code="PERF_YEAR_3",
        release_pct=0.200,
        window_start="2029-08-01T00:00:00Z",
        window_end="2029-10-01T00:00:00Z",
        predecessor_milestone_id=first["id"],
    )
    claim_milestone(world, perf["id"])
    report = open_monitoring_report(
        world,
        monitoring_year=3,
        window_start="2029-08-01T00:00:00Z",
        window_end="2029-09-01T00:00:00Z",
        measurements_array=YEAR3_MEASUREMENTS,
    )
    submit_monitoring_report(world, report["id"])
    return world, perf, report


def test_owning_sponsor_refused_on_member_only_release_approval():
    """The bank's own sponsor cannot approve its own credit release: role
    authorisation is decided before ownership, so the refusal is
    ERR_ROLE_NOT_PERMITTED and the claimed milestone releases nothing.

    PRD §2.1: "Once authenticated, the caller's role must appear in the authorised-role list of the endpoint being invoked, as tabulated in §4; a role acting outside its list is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §2.1: "An `IRTMember` votes on prospectus revision rounds, reviews and scores monitoring reports, inspects corrective work, and approves credit releases."
    PRD §3.6: "A milestone opens in `PENDING` with `claimed_at`, `approved_at` and `deferred_at` null, `attainment_factor_applied` null, and `final_release_credits` at 0.00."

    Design: Corner/rbac/sponsor_and_permittee_cannot_perform_irt_exclusive_operations
    """
    world, perf, _report = _world_with_claimed_perf_milestone()
    version_before = bank_version(world)

    refused = api_client.approve_milestone_release(
        perf["id"],
        approve_release_payload(version_before),
        world["sponsor_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

    after = milestone_state(perf["id"], world)
    assert after["status"] == "CLAIMED", (
        f"the refused approval must leave the milestone CLAIMED, got {after['status']}"
    )
    assert_credits(
        after["final_release_credits"], 0.00, "final_release_credits after refusal"
    )
    assert after["approved_at"] is None, "approved_at must stay null after a refusal"
    assert bank_version(world) == version_before, (
        "a refused approval must not bump the bank version"
    )


def test_chair_only_and_member_only_writes_refused_to_sponsor_and_permittee():
    """The sponsor may not decide its own work plan and the buying permittee may
    not review a monitoring report; both are refused 403 and neither target row
    moves.

    PRD §2.1: "Once authenticated, the caller's role must appear in the authorised-role list of the endpoint being invoked, as tabulated in §4; a role acting outside its list is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §2.10: "Authentication comes first (`ERR_UNAUTHENTICATED`), then role authorisation against the endpoint's role list (`ERR_ROLE_NOT_PERMITTED`)."
    PRD §3.4: "Returning instead advances `SUBMITTED → RETURNED`, stamps `decided_at`, and stores the chair's `return_reason` — which must be supplied on this branch, its absence being a malformed request."
    PRD §3.7: "A new report opens with its review status at `DRAFT`, its compliance status at `UNEVALUATED`, `return_count` at 0, `attainment_score` null, `failed_standard_codes` empty, and `reviewed_by_member_id`, `submitted_at` and `reviewed_at` all null."

    Design: Corner/rbac/sponsor_and_permittee_cannot_perform_irt_exclusive_operations
    """
    world, _perf, report = _world_with_claimed_perf_milestone()
    version_before = bank_version(world)

    refused_decide = api_client.decide_work_plan(
        world["work_plan"]["id"],
        decide_work_plan_payload(
            "RETURN", return_reason="sponsor attempting to decide its own plan"
        ),
        world["sponsor_headers"],
    )
    validate_error(refused_decide, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

    refused_review = api_client.review_monitoring_report(
        report["id"], review_report_payload("ACCEPT"), world["permittee_headers"]
    )
    validate_error(refused_review, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

    plans, _meta = validate_paginated(
        api_client.list_bank_work_plans(
            world["bank"]["id"], world["sponsor_headers"], params={"limit": 10}
        )
    )
    plan = next(p for p in plans if p["id"] == world["work_plan"]["id"])
    assert plan["status"] == "APPROVED", (
        f"the refused RETURN must leave the plan APPROVED, got {plan['status']}"
    )
    assert plan["return_reason"] is None, (
        "the refused RETURN must not store a return_reason"
    )

    after = report_state(report["id"], world)
    assert after["review_status"] == "SUBMITTED", (
        f"the refused review must leave the report SUBMITTED, got {after['review_status']}"
    )
    assert after["compliance_status"] == "UNEVALUATED", (
        "a refused review scores nothing, so compliance_status stays UNEVALUATED"
    )
    assert after["reviewed_by_member_id"] is None, (
        "a refused review must not record a reviewing member"
    )
    assert bank_version(world) == version_before, (
        "neither refused call may bump the bank version"
    )


def test_chair_prospectus_vote_refused_and_tallies_stay_at_three():
    """The chair may not cast a prospectus vote, so the three seated members'
    CONCUR tallies are the only votes the round ever holds.

    PRD §2.1: "the chair never casts a prospectus vote, which keeps the quorum and supermajority tallies free of the deciding official's own opinion, and an attempt by the chair to vote is rejected with `ERR_ROLE_NOT_PERMITTED`."
    PRD §3.3: "Each vote raises exactly one of `concur_count`, `object_count` or `abstain_count` by one — the tallies count only votes bearing the prospectus's current revision round — and a veto vote raises the object tally and additionally sets `veto_recorded` to true."

    Design: Corner/rbac/chair_cannot_vote_and_member_cannot_finalize
    """
    world = setup_bank_under_review(
        work_plan_state="SUBMITTED", vote_positions=["CONCUR", "CONCUR", "CONCUR"]
    )
    prospectus_id = world["prospectus"]["id"]

    refused = api_client.create_prospectus_vote(
        prospectus_id, create_vote_payload("CONCUR"), world["chair_headers"]
    )
    validate_error(refused, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

    votes, meta = validate_paginated(
        api_client.list_prospectus_votes(
            prospectus_id, world["chair_headers"], params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 3, (
        f"the chair's refused vote must not be recorded, got {meta['total_count']} votes"
    )
    seated_ids = {m["id"] for m in world["members"]}
    for vote in votes:
        assert vote["irt_member_id"] in seated_ids, (
            f"vote {vote['id']} was cast by a non-seated identity {vote['irt_member_id']}"
        )

    current = get_success_data(
        api_client.get_prospectus(prospectus_id, world["chair_headers"])
    )
    assert current["concur_count"] == 3, (
        f"concur_count must stay at 3, got {current['concur_count']}"
    )
    assert current["object_count"] == 0, "the refused vote must not raise object_count"
    assert current["abstain_count"] == 0, "the refused vote must not raise abstain_count"
    assert current["veto_recorded"] is False, "no veto was cast in this round"


def test_member_finalize_refused_while_chair_finalize_approves():
    """Closing the review round belongs to the chair alone: a member's finalize
    attempt is refused 403, and the chair's own finalize then carries the
    prospectus to APPROVED on the same three concurrences.

    PRD §2.1: "Once authenticated, the caller's role must appear in the authorised-role list of the endpoint being invoked, as tabulated in §4; a role acting outside its list is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §3.3: "When quorum is met, no veto stands, the supermajority is reached, and the bank additionally has a work plan in either `SUBMITTED` or `APPROVED` status, the prospectus goes `UNDER_REVIEW → APPROVED`; if no such work plan exists the finalisation is rejected with `ERR_WORK_PLAN_MISSING`."
    PRD §3.3: "Every one of the three finalisation branches records the chair's opaque caller identity into `decision_recorded_by` and stamps `decided_at` with the clock; those two side effects are common to approval, revision request and rejection alike."

    Design: Corner/rbac/chair_cannot_vote_and_member_cannot_finalize
    """
    world = setup_bank_under_review(
        work_plan_state="SUBMITTED", vote_positions=["CONCUR", "CONCUR", "CONCUR"]
    )
    prospectus_id = world["prospectus"]["id"]

    refused = api_client.finalize_prospectus_review(
        prospectus_id, world["member_headers"][0]
    )
    validate_error(refused, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

    still_under_review = get_success_data(
        api_client.get_prospectus(prospectus_id, world["chair_headers"])
    )
    assert still_under_review["status"] == "UNDER_REVIEW", (
        "a refused finalize must leave the prospectus UNDER_REVIEW, got "
        f"{still_under_review['status']}"
    )

    finalized = get_success_data(
        api_client.finalize_prospectus_review(prospectus_id, world["chair_headers"])
    )
    assert finalized["status"] == "APPROVED", (
        f"the chair's finalize must approve the prospectus, got {finalized['status']}"
    )
    assert finalized["concur_count"] == 3, (
        f"the approval rests on exactly 3 concurrences, got {finalized['concur_count']}"
    )
    assert finalized["revision_round"] == 1, (
        "an approval on the first round leaves revision_round at 1"
    )
    assert finalized["veto_recorded"] is False, "no veto stood in this round"
    assert finalized["decision_recorded_by"] == world["chair_headers"]["X-User-ID"], (
        "decision_recorded_by must hold the chair's opaque caller identity"
    )
    assert str(finalized["decided_at"]).startswith("2026-08-01T00:00:00"), (
        f"decided_at must be stamped from the clock, got {finalized['decided_at']}"
    )


def test_program_admin_refused_on_bank_creation_and_instrument_execution():
    """ProgramAdmin is a registration-and-clock role, not a super-user: opening
    a bank site and executing the banking instrument are both refused 403 and
    the existing bank stays untouched in DRAFT.

    PRD §2.1: "A `ProgramAdmin` registers sponsors, permittees and review-team members, may top up permittee escrow, and drives the logical clock; it holds no bank, review, release or sales authority whatsoever."
    PRD §2.10: "Authentication comes first (`ERR_UNAUTHENTICATED`), then role authorisation against the endpoint's role list (`ERR_ROLE_NOT_PERMITTED`)."
    PRD §3.2: "Its `easement_recorded` flag is false with `easement_recorded_at` and `easement_deed_reference` both null; its `stewardship_funded_cents`, `deferral_count` and `open_quote_count` are 0; and `instrument_executed_at` and `closed_at` are null."

    Design: Corner/rbac/program_admin_holds_no_bank_or_sale_authority
    """
    world = setup_draft_bank()

    refused_create = api_client.create_bank(
        create_bank_payload(
            world["sponsor"]["id"],
            site_name="Admin Bank",
            service_area_huc8_codes=["03130002"],
            hgm_class="SLOPE",
            annual_stewardship_cost_cents=3000000,
        ),
        world["admin_headers"],
    )
    validate_error(refused_create, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

    refused_execute = api_client.execute_instrument(
        world["bank"]["id"], world["admin_headers"]
    )
    validate_error(refused_execute, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

    _banks, meta = validate_paginated(
        api_client.list_banks(
            world["admin_headers"],
            params={"sponsor_id": world["sponsor"]["id"], "limit": 10},
        )
    )
    assert meta["total_count"] == 1, (
        f"the refused creation must not persist a bank, got {meta['total_count']}"
    )

    sponsor = get_success_data(
        api_client.get_sponsor(world["sponsor"]["id"], world["admin_headers"])
    )
    assert sponsor["banks_count"] == 1, (
        f"banks_count must stay at 1, got {sponsor['banks_count']}"
    )

    bank = bank_state(world)
    assert bank["status"] == "DRAFT", (
        f"the refused execution must leave the bank in DRAFT, got {bank['status']}"
    )
    assert bank["instrument_executed_at"] is None, (
        "instrument_executed_at must stay null after a refused execution"
    )


def test_program_admin_may_top_up_permittee_escrow():
    """The refusals above are not a blanket denial: the deposit endpoint the
    ProgramAdmin does share raises the permit holder's escrow in the same world.

    PRD §3.1: "Escrow is funded by a deposit carrying a single `amount_cents` figure, and either a `ProgramAdmin` or the permit holder itself may lodge one; a permit holder may only fund its own account."
    PRD §3.1: "A deposit is the system's sole money-conservation source event: the deposited total and the escrow balance both rise by the deposited amount, and the permit holder's `version` increments by one."

    Design: Corner/rbac/program_admin_holds_no_bank_or_sale_authority
    """
    world = setup_draft_bank()

    deposited = get_success_data(
        api_client.create_deposit(
            world["permittee"]["id"],
            create_deposit_payload(5000000),
            world["admin_headers"],
        )
    )
    assert_cents(deposited["escrow_balance_cents"], 5000000, "escrow_balance_cents")
    assert_cents(deposited["deposited_cents"], 5000000, "deposited_cents")

    reread = permittee_state(world)
    assert_cents(
        reread["escrow_balance_cents"], 5000000, "escrow_balance_cents on re-read"
    )


def test_foreign_sponsor_refused_on_path_named_bank_easement():
    """Ownership is scoped per bank, not per role: sponsor B holds the Sponsor
    role yet recording an easement on sponsor A's bank is refused
    ERR_NOT_BANK_SPONSOR and the flag stays false.

    PRD §2.1: "Concretely, a Sponsor write is admissible only when the targeted bank's `sponsor_id` equals `X-User-ID` — whether the bank is named directly in the path, reached through the target row's `bank_id`, or reached through the monitoring report that a remedial action was opened against — and a mismatch is rejected with `ERR_NOT_BANK_SPONSOR` (HTTP 403)."
    PRD §3.2: "Its `easement_recorded` flag is false with `easement_recorded_at` and `easement_deed_reference` both null; its `stewardship_funded_cents`, `deferral_count` and `open_quote_count` are 0; and `instrument_executed_at` and `closed_at` are null."

    Design: Corner/rbac/a_sponsor_cannot_operate_another_sponsors_bank
    """
    world = setup_draft_bank()
    sponsor_b = register_sponsor(
        legal_name="Tallow Creek Restoration Trust",
        legal_entity_type="NGO",
        performance_bond_cents=26000000,
    )
    headers_b = make_sponsor_headers(sponsor_b["id"])

    refused = api_client.record_conservation_easement(
        world["bank"]["id"], create_easement_payload("BK9999-PG001"), headers_b
    )
    validate_error(refused, ApiErrorId.ERR_NOT_BANK_SPONSOR, 403)

    bank = bank_state(world)
    assert bank["easement_recorded"] is False, (
        "the refused write must leave easement_recorded false"
    )
    assert bank["easement_deed_reference"] is None, (
        "the refused write must not store a deed reference"
    )
    assert bank["easement_recorded_at"] is None, (
        "the refused write must not stamp easement_recorded_at"
    )
    assert bank["version"] == 1, (
        f"the refused write must not bump the bank version, got {bank['version']}"
    )


def test_foreign_sponsor_refused_on_body_fk_prospectus_but_may_read():
    """The same ownership check reaches through a body foreign key: sponsor B's
    prospectus for sponsor A's bank is refused ERR_NOT_BANK_SPONSOR rather than
    a not-found, while the read both sponsors share still succeeds.

    PRD §2.1: "Concretely, a Sponsor write is admissible only when the targeted bank's `sponsor_id` equals `X-User-ID` — whether the bank is named directly in the path, reached through the target row's `bank_id`, or reached through the monitoring report that a remedial action was opened against — and a mismatch is rejected with `ERR_NOT_BANK_SPONSOR` (HTTP 403)."
    PRD §3.1: "Two sponsor properties are derived rather than supplied: `banks_count`, the number of bank rows naming this sponsor, counted across every bank status without exception and initialised to 0; and `good_standing`, a boolean that is true precisely when the sponsor owns no bank in `SUSPENDED` status, and therefore initialised to true."

    Design: Corner/rbac/a_sponsor_cannot_operate_another_sponsors_bank
    """
    world = setup_draft_bank()
    sponsor_b = register_sponsor(
        legal_name="Tallow Creek Restoration Trust",
        legal_entity_type="NGO",
        performance_bond_cents=26000000,
    )
    headers_b = make_sponsor_headers(sponsor_b["id"])

    refused = api_client.create_prospectus(
        create_prospectus_payload(
            world["bank"]["id"],
            objective_summary="Foreign sponsor prospectus",
            proposed_credits=40.00,
        ),
        headers_b,
    )
    validate_error(refused, ApiErrorId.ERR_NOT_BANK_SPONSOR, 403)

    shared_read = get_success_data(
        api_client.get_bank(world["bank"]["id"], headers_b)
    )
    assert shared_read["easement_recorded"] is False, (
        "the non-owning sponsor's shared read must report the untouched bank"
    )

    _rows, prospectus_meta = validate_paginated(
        api_client.list_bank_prospectuses(
            world["bank"]["id"], world["sponsor_headers"], params={"limit": 10}
        )
    )
    assert prospectus_meta["total_count"] == 0, (
        f"the refused draft must create no prospectus, got {prospectus_meta['total_count']}"
    )

    reread_b = get_success_data(api_client.get_sponsor(sponsor_b["id"], headers_b))
    assert reread_b["banks_count"] == 0, (
        f"sponsor B owns no bank, got banks_count {reread_b['banks_count']}"
    )

    _banks, bank_meta = validate_paginated(
        api_client.list_banks(
            headers_b, params={"sponsor_id": sponsor_b["id"], "limit": 10}
        )
    )
    assert bank_meta["total_count"] == 0, (
        f"no bank names sponsor B, got total_count {bank_meta['total_count']}"
    )


def _sellable_bank_with_two_permittees():
    """A sellable bank, a second unrelated permit holder, and a 3.00-credit
    quote belonging to the first. Returns (world, other_permittee, sale)."""
    world = setup_sellable_bank(permittee_required_credits=20.00)
    other = register_permittee(
        organization_name="Bayou Ridge Terminals",
        impact_huc8_code="03130003",
        required_credits=12.00,
    )
    sale = quote_credits(world, 3.00)
    return world, other, sale


def test_foreign_permittee_refused_on_reserve_and_cancel():
    """A permit holder may only act on its own sale: the second permittee is
    refused ERR_NOT_SALE_PERMITTEE on both reserve and cancel, and the quote is
    left exactly as it stood with no hold placed.

    PRD §2.1: "When `X-User-Role` is `Permittee`, `X-User-ID` is the `id` of the acting Permittee row; ownership checks compare `X-User-ID` to the sale's `permittee_id`, to the `permittee_id` supplied in the body when a quote is created, or to the permittee identifier in the path when escrow is topped up, and a mismatch is rejected with `ERR_NOT_SALE_PERMITTEE` (HTTP 403)."
    PRD §3.8: "A quote opens in `QUOTED` status with `hold_start_at`, `hold_expires_at`, `executed_price_cents`, `executed_at`, `assigned_at`, `assignment_reference`, `cancelled_reason` and `cancelled_at` all null, raises the bank's `open_quote_count` by one and increments the bank's `version` by one."

    Design: Corner/rbac/a_permittee_cannot_reserve_or_cancel_another_permittees_sale
    """
    world, other, sale = _sellable_bank_with_two_permittees()
    foreign_headers = make_permittee_headers(other["id"])

    refused_reserve = api_client.reserve_credit_sale(sale["id"], foreign_headers)
    validate_error(refused_reserve, ApiErrorId.ERR_NOT_SALE_PERMITTEE, 403)

    refused_cancel = api_client.cancel_credit_sale(
        sale["id"], {"cancelled_reason": "BUYER_WITHDREW"}, foreign_headers
    )
    validate_error(refused_cancel, ApiErrorId.ERR_NOT_SALE_PERMITTEE, 403)

    current = sale_state(sale["id"], world)
    assert current["status"] == "QUOTED", (
        f"the refused writes must leave the sale QUOTED, got {current['status']}"
    )
    assert current["cancelled_reason"] is None, (
        "the refused cancel must not stamp a cancelled_reason"
    )
    assert current["cancelled_at"] is None, (
        "the refused cancel must not stamp cancelled_at"
    )
    assert current["hold_start_at"] is None, (
        "the refused reserve must not open a hold"
    )

    bank = bank_state(world)
    assert_credits(bank["credits_on_hold"], 0.00, "credits_on_hold after refusals")
    assert_credits(bank["credits_available"], 14.82, "credits_available after refusals")
    assert len(ledger_rows(world)) == 2, (
        "neither refusal may append a ledger row: only GENERATED and RELEASED exist"
    )


def test_owning_permittee_reserve_places_the_hold():
    """The refusal is identity-scoped, not posture-scoped: the sale's own permit
    holder reserves the same quote, which places the 3.00-credit hold and drops
    available credits to 11.82.

    PRD §3.8: "Reservation belongs exclusively to the buying permit holder acting on its own sale."
    PRD §3.8: "Reservation stamps `hold_start_at` with the current clock and `hold_expires_at` 30 days later, appends a `HOLD_PLACED` entry carrying the requested credits as a negative delta and attributed through a source entity type of `CREDIT_SALE` and the sale's own identifier, recomputes the bank's credits on hold and available credits and its posture, recomputes the bank's `open_quote_count`, and increments the bank's `version` by one."

    Design: Corner/rbac/a_permittee_cannot_reserve_or_cancel_another_permittees_sale
    """
    world, other, sale = _sellable_bank_with_two_permittees()
    foreign_headers = make_permittee_headers(other["id"])
    validate_error(
        api_client.reserve_credit_sale(sale["id"], foreign_headers),
        ApiErrorId.ERR_NOT_SALE_PERMITTEE,
        403,
    )

    reserved = reserve_sale(world, sale["id"])
    assert reserved["status"] == "RESERVED", (
        f"the owning permittee's reserve must succeed, got {reserved['status']}"
    )
    assert str(reserved["hold_start_at"]).startswith("2026-08-01T00:00:00"), (
        f"hold_start_at must be stamped from the clock, got {reserved['hold_start_at']}"
    )

    bank = bank_state(world)
    assert_credits(bank["credits_on_hold"], 3.00, "credits_on_hold after reservation")
    assert_credits(bank["credits_available"], 11.82, "credits_available after reservation")
    assert_ledger_shape(
        ledger_rows(world),
        [
            ("GENERATED", 0.00, 0.00),
            ("RELEASED", 14.82, 14.82),
            ("HOLD_PLACED", -3.00, 11.82),
        ],
    )
    assert_credit_conservation(bank)


def test_stale_bank_version_rejects_quote_creation():
    """The quote's concurrency guard is the bank's version: after an unrelated
    stewardship contribution moves the bank from 7 to 8, a quote carrying 7 is
    turned away 412 and no sale row is created.

    PRD §2.7: "Both require a non-optional integer input field named `expected_bank_version`, carrying the `version` of the bank as the client last read it from the bank's single-resource read. If the value supplied does not equal the bank's current `version` at request time, the request is rejected with `ERR_STALE_BANK_VERSION` (HTTP 412)."
    PRD §3.5: "Each contribution raises `stewardship_funded_cents` by the amount contributed and increments the bank's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_bank_version_rejects_quote_creation
    """
    world = setup_sellable_bank(permittee_required_credits=20.00)
    stale_version = bank_version(world)
    assert stale_version == 7, (
        f"the shared world reaches bank version 7, got {stale_version}"
    )

    bumped = fund_stewardship(world, 1000000)
    assert bumped["version"] == 8, (
        f"the contribution must take the bank to version 8, got {bumped['version']}"
    )
    assert_cents(bumped["stewardship_funded_cents"], 29420000, "stewardship_funded_cents")

    refused = api_client.create_credit_sale(
        create_credit_sale_payload(
            world["bank"]["id"],
            world["permittee"]["id"],
            4.00,
            stale_version,
            impact_huc8_code="03130002",
        ),
        world["permittee_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_STALE_BANK_VERSION, 412)

    _sales, meta = validate_paginated(
        api_client.list_credit_sales(
            world["sponsor_headers"],
            params={"bank_id": world["bank"]["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 0, (
        f"the rejected attempt must create nothing, got {meta['total_count']} sales"
    )
    after = bank_state(world)
    assert after["version"] == 8, (
        f"a rejected quote must not bump the bank version, got {after['version']}"
    )
    assert after["open_quote_count"] == 0, (
        f"a rejected quote must not raise open_quote_count, got {after['open_quote_count']}"
    )


def test_fresh_bank_version_quote_prices_four_credits():
    """The retry carrying the fresh bank version succeeds and prices 4.00
    DEPRESSIONAL credits at 16416000 cents on a PRIMARY tier with the demand
    index at 0.0000.

    PRD §2.7: "Both require a non-optional integer input field named `expected_bank_version`, carrying the `version` of the bank as the client last read it from the bank's single-resource read. If the value supplied does not equal the bank's current `version` at request time, the request is rejected with `ERR_STALE_BANK_VERSION` (HTTP 412)."
    PRD §3.8: "Pricing starts from the bank's hydrogeomorphic class, which fixes a base price per credit: 4,250,000 cents for `RIVERINE`, 3,800,000 cents for `DEPRESSIONAL`, 3,600,000 cents for `SLOPE`, 3,300,000 cents for `FLATS` and 5,100,000 cents for `ESTUARINE`."
    PRD §3.8: "The first tier takes the requested quantity up to a ceiling of 5.00 credits at a multiplier of 1.000."
    PRD §3.8: "A bank whose stewardship endowment is funded below its requirement attracts a further 8 percent, and a fully funded bank attracts nothing."
    PRD §3.8: "The impact watershed must fall inside the bank's service area, or the quote is rejected with `ERR_OUTSIDE_SERVICE_AREA`: this is the service-area limitation that gives mitigation banking its geographic integrity, and it is also what fixes the sale's `service_area_tier`, which is `PRIMARY` when the impact watershed is the bank's own site watershed and `SECONDARY` when it is any other member of the bank's service-area list."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_bank_version_rejects_quote_creation
    """
    world = setup_sellable_bank(permittee_required_credits=20.00)
    stale_version = bank_version(world)
    fresh_version = fund_stewardship(world, 1000000)["version"]

    validate_error(
        api_client.create_credit_sale(
            create_credit_sale_payload(
                world["bank"]["id"],
                world["permittee"]["id"],
                4.00,
                stale_version,
                impact_huc8_code="03130002",
            ),
            world["permittee_headers"],
        ),
        ApiErrorId.ERR_STALE_BANK_VERSION,
        412,
    )

    sale = get_success_data(
        api_client.create_credit_sale(
            create_credit_sale_payload(
                world["bank"]["id"],
                world["permittee"]["id"],
                4.00,
                fresh_version,
                impact_huc8_code="03130002",
            ),
            world["permittee_headers"],
        ),
        201,
    )
    assert_cents(sale["quoted_price_cents"], 16416000, "quoted_price_cents")
    assert_score(sale["quoted_demand_index"], 0.0000, "quoted_demand_index")
    assert sale["service_area_tier"] == "PRIMARY", (
        f"the site watershed quotes at PRIMARY, got {sale['service_area_tier']}"
    )
    assert sale["status"] == "QUOTED", f"a new quote opens QUOTED, got {sale['status']}"

    _sales, meta = validate_paginated(
        api_client.list_credit_sales(
            world["sponsor_headers"],
            params={"bank_id": world["bank"]["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 1, (
        f"only the accepted quote may exist, got {meta['total_count']} sales"
    )
    after = bank_state(world)
    assert after["version"] == 9, (
        f"only the accepted quote bumped the bank, got version {after['version']}"
    )
    assert after["open_quote_count"] == 1, (
        f"open_quote_count must read 1, got {after['open_quote_count']}"
    )


def _executed_bank_with_claimed_first_milestone():
    """A bank in INSTRUMENT_EXECUTED with its easement recorded and endowment at
    the interim gate, whose INSTRUMENT_EXECUTION milestone is CLAIMED but not
    yet approved. Returns (world, milestone)."""
    world = setup_sellable_bank(release_first_milestone=False)
    milestone = add_milestone(world)
    claim_milestone(world, milestone["id"])
    return world, milestone


def test_stale_bank_version_rejects_release_approval():
    """The second concurrency-guarded write uses the same field: the approving
    member's read of bank version 6 is superseded by a stewardship top-up, and
    the approval carrying 6 is refused 412 with nothing released.

    PRD §3.6: "The request carries `expected_bank_version` and is turned away with `ERR_STALE_BANK_VERSION` if that value does not match the bank's current version."
    PRD §3.5: "Each contribution raises `stewardship_funded_cents` by the amount contributed and increments the bank's `version` by one."
    PRD §3.6: "A milestone opens in `PENDING` with `claimed_at`, `approved_at` and `deferred_at` null, `attainment_factor_applied` null, and `final_release_credits` at 0.00."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_bank_version_rejects_release_approval
    """
    world, milestone = _executed_bank_with_claimed_first_milestone()
    read_version = bank_version(world)
    assert read_version == 6, (
        f"the member reads bank version 6 before the top-up, got {read_version}"
    )

    bumped_version = fund_stewardship(world, 500000)["version"]
    assert bumped_version == 7, (
        f"the top-up must take the bank to version 7, got {bumped_version}"
    )

    refused = api_client.approve_milestone_release(
        milestone["id"],
        approve_release_payload(read_version),
        world["member_headers"][0],
    )
    validate_error(refused, ApiErrorId.ERR_STALE_BANK_VERSION, 412)

    after = milestone_state(milestone["id"], world)
    assert after["status"] == "CLAIMED", (
        f"the refused approval must leave the milestone CLAIMED, got {after['status']}"
    )
    assert_credits(after["final_release_credits"], 0.00, "final_release_credits")
    assert after["attainment_factor_applied"] is None, (
        "a refused approval must not stamp an attainment factor"
    )

    bank = bank_state(world)
    assert_credits(bank["credits_released"], 0.00, "credits_released after refusal")
    assert len(ledger_rows(world)) == 1, (
        "only the GENERATED entry may exist: the refused approval released nothing"
    )


def test_fresh_bank_version_release_approval_releases_full_tranche():
    """The retry carrying the bumped version releases exactly 14.82 credits at an
    attainment factor of 1.00 and leaves the bank at version 8 with one RELEASED
    ledger row.

    PRD §3.6: "The request carries `expected_bank_version` and is turned away with `ERR_STALE_BANK_VERSION` if that value does not match the bank's current version."
    PRD §3.6: "For the two construction milestones, `INSTRUMENT_EXECUTION` and `CONSTRUCTION_COMPLETE`, no monitoring is consulted at all and the attainment factor is exactly 1.00 — earthwork needs no growing season."
    PRD §3.6: "A ledger entry of type `RELEASED` is appended carrying the final release quantity as a positive delta, attributed through a source entity type of `RELEASE_MILESTONE` and the milestone's own identifier, with a memo naming the release, its milestone code and the attainment factor applied."
    PRD §3.6: "The milestone's `approved_at` is stamped with the clock and the bank's `version` increments by one."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_bank_version_rejects_release_approval
    """
    world, milestone = _executed_bank_with_claimed_first_milestone()
    read_version = bank_version(world)
    bumped_version = fund_stewardship(world, 500000)["version"]

    validate_error(
        api_client.approve_milestone_release(
            milestone["id"],
            approve_release_payload(read_version),
            world["member_headers"][0],
        ),
        ApiErrorId.ERR_STALE_BANK_VERSION,
        412,
    )

    approved = get_success_data(
        api_client.approve_milestone_release(
            milestone["id"],
            approve_release_payload(bumped_version),
            world["member_headers"][0],
        )
    )
    assert approved["status"] == "APPROVED", (
        f"the fresh-token approval must succeed, got {approved['status']}"
    )
    assert_credits(approved["final_release_credits"], 14.82, "final_release_credits")
    assert_credits(approved["attainment_factor_applied"], 1.00, "attainment_factor_applied")
    assert str(approved["approved_at"]).startswith("2026-08-01T00:00:00"), (
        f"approved_at must be stamped from the clock, got {approved['approved_at']}"
    )

    bank = bank_state(world)
    assert bank["version"] == 8, (
        f"the release takes the bank from 7 to 8, got {bank['version']}"
    )
    assert_credits(bank["credits_released"], 14.82, "credits_released")
    assert_ledger_shape(
        ledger_rows(world),
        [("GENERATED", 0.00, 0.00), ("RELEASED", 14.82, 14.82)],
    )


def test_bank_version_bumps_only_on_bank_touching_writes():
    """Only writes that touch the bank row bump its version: the endowment
    contribution takes it 5 to 6, creating and claiming a milestone leave it at
    6, and the release approval takes it 6 to 7.

    PRD §2.4: "`version` is an integer that begins at 1 and increments by exactly 1 on every mutation of the row; it is the token the optimistic-concurrency machinery of §2.7 is built on."
    PRD §2.9: "Whenever a cascade repositions a bank, the bank's `version` increments by exactly 1 for the whole request — not once per touched field — and its `updated_at` is refreshed."
    PRD §3.5: "Each contribution raises `stewardship_funded_cents` by the amount contributed and increments the bank's `version` by one."
    PRD §3.6: "Claiming is the sponsor's assertion that the milestone has been attained, and it advances the milestone `PENDING → CLAIMED` while stamping `claimed_at` with the logical clock."
    PRD §3.6: "The milestone's `approved_at` is stamped with the clock and the bank's `version` increments by one."

    Design: Corner/cross_cutting_complexity_layers/bank_version_increments_once_per_bank_touching_write
    """
    world = setup_executed_bank(record_easement=True)

    version_after_core = bank_version(world)
    assert version_after_core == 5, (
        "bank create, prospectus submit, work-plan approval, instrument execution "
        f"and easement recording give version 5, got {version_after_core}"
    )

    version_after_contribution = fund_stewardship(world, 28420000)["version"]
    assert version_after_contribution == 6, (
        f"the contribution must take the bank to 6, got {version_after_contribution}"
    )

    milestone = add_milestone(world)
    claim_milestone(world, milestone["id"])
    version_after_claim = bank_version(world)
    assert version_after_claim == 6, (
        "neither the milestone create nor the claim touches the bank row, so the "
        f"version must stay at 6, got {version_after_claim}"
    )

    get_success_data(
        api_client.approve_milestone_release(
            milestone["id"],
            approve_release_payload(version_after_claim),
            world["member_headers"][0],
        )
    )
    bank = bank_state(world)
    assert bank["version"] == 7, (
        f"the release approval must take the bank to 7, got {bank['version']}"
    )
    assert_credits(bank["credits_released"], 14.82, "credits_released")
    assert_cents(bank["stewardship_funded_cents"], 28420000, "stewardship_funded_cents")


def test_milestone_row_keeps_its_own_version_counter():
    """The milestone row counts its own mutations independently of the bank: it
    opens at version 1, the claim takes it to 2 and the release approval to 3.

    PRD §2.4: "`version` is an integer that begins at 1 and increments by exactly 1 on every mutation of the row; it is the token the optimistic-concurrency machinery of §2.7 is built on."
    PRD §2.9: "Child rows mutated inside the same cascade increment their own `version` and refresh their own `updated_at` in the same way."
    PRD §3.6: "Its `provisional_release_credits` is computed straight away, and is recomputed each time the milestone is claimed so that it always reflects the bank's current authorised total."

    Design: Corner/cross_cutting_complexity_layers/bank_version_increments_once_per_bank_touching_write
    """
    world = setup_executed_bank(record_easement=True)
    fund_stewardship(world, 28420000)

    milestone = add_milestone(world)
    assert milestone["version"] == 1, (
        f"a freshly created milestone opens at version 1, got {milestone['version']}"
    )

    claimed = claim_milestone(world, milestone["id"])
    assert claimed["version"] == 2, (
        f"the claim is one mutation of the milestone row, got {claimed['version']}"
    )
    assert_credits(
        claimed["provisional_release_credits"], 14.82, "provisional_release_credits"
    )

    released = get_success_data(
        api_client.approve_milestone_release(
            milestone["id"],
            approve_release_payload(bank_version(world)),
            world["member_headers"][0],
        )
    )
    assert released["version"] == 3, (
        f"the release approval is the third mutation, got {released['version']}"
    )
    assert_credits(released["final_release_credits"], 14.82, "final_release_credits")


def _two_quotes_then_cancel_then_reserve():
    """Open two quotes on the sellable bank, withdraw the second, then reserve
    the survivor. Returns the four bank snapshots taken along the way plus the
    two sale ids."""
    world = setup_sellable_bank(permittee_required_credits=20.00)
    sale_a = quote_credits(world, 3.00)
    after_first = bank_state(world)
    sale_b = quote_credits(world, 2.00)
    after_second = bank_state(world)
    cancel_sale(world, sale_b["id"], "BUYER_WITHDREW")
    after_cancel = bank_state(world)
    reserve_sale(world, sale_a["id"])
    after_reserve = bank_state(world)
    return world, sale_a, sale_b, after_first, after_second, after_cancel, after_reserve


def test_open_quote_count_tracks_quoted_and_reserved_sales():
    """The derived tally counts sales standing in QUOTED or RESERVED: it rises
    1 then 2 as quotes accumulate, falls back to 1 when one quote is withdrawn,
    and the reserved survivor is still counted.

    PRD §3.8: "That counter is a derived tally rather than a hand-maintained number: it is the count of the bank's credit sales standing in either `QUOTED` or `RESERVED`, so a quote that is placed on hold continues to be counted, and a sale leaves the tally only when it settles, is withdrawn or expires."
    PRD §3.8: "Cancelling a quote advances `QUOTED → CANCELLED`, stamps the reason and `cancelled_at`, and lowers the bank's open quote count; no ledger entry is written because no hold ever existed."

    Design: Corner/cross_cutting_complexity_layers/open_quote_count_reconciles_after_cancel_and_reserve
    """
    (
        world,
        _sale_a,
        sale_b,
        after_first,
        after_second,
        after_cancel,
        after_reserve,
    ) = _two_quotes_then_cancel_then_reserve()

    assert after_first["open_quote_count"] == 1, (
        f"the first quote raises the tally to 1, got {after_first['open_quote_count']}"
    )
    assert after_second["open_quote_count"] == 2, (
        f"the second quote raises the tally to 2, got {after_second['open_quote_count']}"
    )
    assert after_cancel["open_quote_count"] == 1, (
        f"the withdrawn quote leaves the tally, got {after_cancel['open_quote_count']}"
    )
    assert after_reserve["open_quote_count"] == 1, (
        "a quote placed on hold continues to be counted, got "
        f"{after_reserve['open_quote_count']}"
    )
    assert_credits(
        after_second["credits_on_hold"], 0.00, "credits_on_hold while both are quoted"
    )

    withdrawn = sale_state(sale_b["id"], world)
    assert withdrawn["status"] == "CANCELLED", (
        f"the withdrawn quote must be CANCELLED, got {withdrawn['status']}"
    )
    assert withdrawn["cancelled_reason"] == "BUYER_WITHDREW", (
        f"cancelled_reason must be BUYER_WITHDREW, got {withdrawn['cancelled_reason']}"
    )
    assert str(withdrawn["cancelled_at"]).startswith("2026-08-01T00:00:00"), (
        f"cancelled_at must be stamped from the clock, got {withdrawn['cancelled_at']}"
    )


def test_reservation_moves_credits_from_available_to_on_hold():
    """The two derived counters move independently: reserving the surviving quote
    is the moment credits_on_hold first becomes 3.00 and available credits drop
    to 11.82, while the withdrawn quote appended no ledger row at all.

    PRD §2.11: "`credits_on_hold` is the negation of the total of the deltas of its `HOLD_PLACED` and `HOLD_RELEASED` entries taken together."
    PRD §2.11: "`credits_available` is the released quantity minus the sold quantity minus the on-hold quantity."
    PRD §2.11: "The invariant no endpoint may ever break is that released credits equal the sum of sold, on-hold and available credits, and that available credits equal the `balance_after` of the bank's highest-numbered ledger entry."
    PRD §3.8: "Cancelling a quote advances `QUOTED → CANCELLED`, stamps the reason and `cancelled_at`, and lowers the bank's open quote count; no ledger entry is written because no hold ever existed."

    Design: Corner/cross_cutting_complexity_layers/open_quote_count_reconciles_after_cancel_and_reserve
    """
    (
        world,
        _sale_a,
        _sale_b,
        _after_first,
        _after_second,
        _after_cancel,
        after_reserve,
    ) = _two_quotes_then_cancel_then_reserve()

    assert_credits(after_reserve["credits_on_hold"], 3.00, "credits_on_hold")
    assert_credits(after_reserve["credits_available"], 11.82, "credits_available")
    assert_credits(after_reserve["credits_released"], 14.82, "credits_released")
    assert_credits(after_reserve["credits_sold"], 0.00, "credits_sold")
    assert_credit_conservation(after_reserve)

    assert_ledger_shape(
        ledger_rows(world),
        [
            ("GENERATED", 0.00, 0.00),
            ("RELEASED", 14.82, 14.82),
            ("HOLD_PLACED", -3.00, 11.82),
        ],
    )
