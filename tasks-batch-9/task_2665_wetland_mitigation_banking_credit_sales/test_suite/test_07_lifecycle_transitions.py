"""Lifecycle transitions across the mitigation banking state machines.

Covers the declared initial states of the bank, prospectus, work plan and
release milestone; the coupled prospectus/bank transition performed by one
submit; the rejection of a replayed transition; the terminal lockdown of an
assigned credit sale; the divergent side-effect sets of the work-plan return and
approve branches; the milestone claim window precondition; and the cascade a
bank closure drives into the bank's outstanding quotes.

Each test builds its own world from scratch: the harness restarts the server
with an empty database before every test.
"""

from datetime import datetime, timezone

from test_helpers import (
    TEST_DEFAULTS,
    ApiErrorId,
    add_milestone,
    api_client,
    assert_bank,
    assert_cents,
    assert_credits,
    assert_ledger_sequence,
    assert_ledger_shape,
    assert_milestone,
    assert_performance_standard,
    assert_prospectus,
    assert_score,
    assert_work_plan,
    assign_sale,
    bank_state,
    cancel_sale_payload,
    cast_votes,
    decide_work_plan_payload,
    draft_prospectus,
    draft_work_plan,
    execute_sale,
    file_and_accept_monitoring_report,
    finalize_prospectus,
    fund_stewardship,
    ledger_rows,
    milestone_state,
    permittee_state,
    quote_credits,
    reserve_sale,
    sale_state,
    set_clock,
    setup_bank_under_review,
    setup_draft_bank,
    setup_executed_bank,
    setup_sellable_bank,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_START = "2026-08-01T00:00:00Z"


def _instant(value):
    """Parse an ISO 8601 UTC timestamp into a comparable aware datetime."""
    assert isinstance(value, str) and value, (
        f"expected an ISO 8601 UTC timestamp, got {value!r}"
    )
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def assert_instant(actual, expected_iso, label):
    """Assert a server-stamped timestamp names the expected logical instant."""
    assert _instant(actual) == _instant(expected_iso), (
        f"{label}: expected the instant {expected_iso}, got {actual}"
    )


def _assigned_sale_world():
    """Quote, reserve, settle and assign a 4.00-credit sale on the canonical
    DEPRESSIONAL bank whose endowment sits at the interim gate."""
    set_clock(CLOCK_START)
    world = setup_sellable_bank(
        permittee_required_credits=20.00,
        permittee_deposit_cents=40_000_000,
    )
    sale = quote_credits(world, 4.00)
    reserve_sale(world, sale["id"])
    execute_sale(world, sale["id"])
    return world, sale, assign_sale(world, sale["id"])


def _closable_bank_with_open_quote():
    """A bank in MONITORING whose only milestone is APPROVED, whose endowment is
    funded in full and which carries one outstanding 4.00-credit quote."""
    set_clock(CLOCK_START)
    world = setup_sellable_bank()
    set_clock("2027-08-15T00:00:00Z")
    report = file_and_accept_monitoring_report(
        world,
        monitoring_year=1,
        window_start="2027-08-01T00:00:00Z",
        window_end="2027-09-01T00:00:00Z",
        measurements_array=[
            {"standard_code": "HYDROPERIOD_DAYS", "measured_value": 120},
            {"standard_code": "INVASIVE_COVER_PCT", "measured_value": 8.0},
        ],
    )
    fund_stewardship(world, TEST_DEFAULTS["STEWARDSHIP_REMAINDER_CENTS"])
    sale = quote_credits(world, 4.00)
    return world, report, sale


def test_bank_and_prospectus_open_in_their_declared_initial_states():
    """A newly registered bank site lands on DRAFT with a FROZEN posture and every
    credit aggregate at 0.00, and the prospectus drafted for it lands on DRAFT
    with revision_round 1, all tallies zero and every review stamp still null.

    PRD §3.2: "A newly registered bank opens in `DRAFT` status with a `sales_posture` of `FROZEN`, and every credit aggregate — `total_authorized_credits`, `credits_released`, `credits_sold`, `credits_on_hold` and `credits_available` — initialised to 0.00."
    PRD §3.3: "A prospectus opens in `DRAFT` status with `revision_round` stamped at 1, all three vote tallies at 0, `veto_recorded` false, and `submitted_at`, `review_opened_at`, `decision_recorded_by` and `decided_at` all null."
    Design: Corner/state_machines/bank_and_prospectus_start_in_declared_initial_states
    """
    set_clock(CLOCK_START)
    world = setup_draft_bank()
    bank = world["bank"]

    assert_bank(bank)
    assert bank["status"] == "DRAFT", (
        f"a newly registered bank opens in DRAFT, got {bank['status']}"
    )
    assert bank["sales_posture"] == "FROZEN", (
        f"a DRAFT bank's posture is FROZEN, got {bank['sales_posture']}"
    )
    for field in (
        "total_authorized_credits",
        "credits_released",
        "credits_sold",
        "credits_on_hold",
        "credits_available",
    ):
        assert_credits(bank[field], 0.00, f"newly registered bank {field}")
    assert bank["easement_recorded"] is False, "the easement is unrecorded at registration"
    assert bank["easement_recorded_at"] is None, "easement_recorded_at starts null"
    assert bank["easement_deed_reference"] is None, "easement_deed_reference starts null"
    assert_cents(bank["stewardship_funded_cents"], 0, "stewardship_funded_cents")
    assert bank["deferral_count"] == 0, "deferral_count starts at 0"
    assert bank["open_quote_count"] == 0, "open_quote_count starts at 0"
    assert bank["instrument_executed_at"] is None, "instrument_executed_at starts null"
    assert bank["closed_at"] is None, "closed_at starts null"
    assert bank["version"] == 1, f"version begins at 1, got {bank['version']}"

    prospectus = draft_prospectus(world)
    assert_prospectus(prospectus)
    assert prospectus["status"] == "DRAFT", (
        f"a prospectus opens in DRAFT, got {prospectus['status']}"
    )
    assert prospectus["revision_round"] == 1, "revision_round is stamped at 1"
    assert prospectus["concur_count"] == 0, "concur_count opens at 0"
    assert prospectus["object_count"] == 0, "object_count opens at 0"
    assert prospectus["abstain_count"] == 0, "abstain_count opens at 0"
    assert prospectus["veto_recorded"] is False, "veto_recorded opens false"
    assert prospectus["submitted_at"] is None, "submitted_at opens null"
    assert prospectus["review_opened_at"] is None, "review_opened_at opens null"
    assert prospectus["decision_recorded_by"] is None, "decision_recorded_by opens null"
    assert prospectus["decided_at"] is None, "decided_at opens null"


def test_work_plan_and_milestone_open_in_declared_states_without_moving_the_bank():
    """The work plan drafted for a DRAFT bank opens in DRAFT with no decision
    stamps and the milestone scheduled against it opens in PENDING with a 0.00
    provisional tranche — the bank's authorised total is still 0.00 — while the
    bank itself stays in DRAFT throughout.

    PRD §3.4: "A plan opens in `DRAFT`, with `submitted_at`, `decided_at` and `return_reason` all null."
    PRD §3.6: "A milestone opens in `PENDING` with `claimed_at`, `approved_at` and `deferred_at` null, `attainment_factor_applied` null, and `final_release_credits` at 0.00."
    PRD §3.6: "That provisional figure is the bank's authorised credit total multiplied by the milestone's release percentage, rounded half up to 2 decimal places."
    Design: Corner/state_machines/bank_and_prospectus_start_in_declared_initial_states
    """
    set_clock(CLOCK_START)
    world = setup_draft_bank()
    draft_prospectus(world)

    work_plan = draft_work_plan(world)
    assert_work_plan(work_plan)
    assert work_plan["status"] == "DRAFT", (
        f"a work plan opens in DRAFT, got {work_plan['status']}"
    )
    assert work_plan["submitted_at"] is None, "work plan submitted_at opens null"
    assert work_plan["decided_at"] is None, "work plan decided_at opens null"
    assert work_plan["return_reason"] is None, "work plan return_reason opens null"

    milestone = add_milestone(
        world,
        milestone_code="INSTRUMENT_EXECUTION",
        release_pct=0.150,
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-09-01T00:00:00Z",
    )
    assert_milestone(milestone)
    assert milestone["status"] == "PENDING", (
        f"a milestone opens in PENDING, got {milestone['status']}"
    )
    assert milestone["claimed_at"] is None, "claimed_at opens null"
    assert milestone["approved_at"] is None, "approved_at opens null"
    assert milestone["deferred_at"] is None, "deferred_at opens null"
    assert milestone["attainment_factor_applied"] is None, (
        "attainment_factor_applied opens null"
    )
    assert_credits(milestone["final_release_credits"], 0.00, "final_release_credits")
    assert_credits(
        milestone["provisional_release_credits"],
        0.00,
        "provisional tranche of an unauthorised bank (0.00 x 0.150)",
    )

    after = bank_state(world)
    assert after["status"] == "DRAFT", (
        "attaching a prospectus, a work plan and a milestone does not advance the "
        f"bank out of DRAFT, got {after['status']}"
    )


def test_prospectus_submission_advances_only_to_submitted_and_stamps_the_clock():
    """One submit takes the prospectus DRAFT -> SUBMITTED and no further: it stops
    short of UNDER_REVIEW, which the first vote reaches, and stamps submitted_at
    from the logical clock while leaving revision_round at 1.

    PRD §3.3: "Submission by the owning sponsor advances the prospectus `DRAFT → SUBMITTED`, stamps `submitted_at` with the current logical clock, and — this is the side effect that starts the regulatory machine — drags the bank from `DRAFT` to `PROSPECTUS_REVIEW`, recomputing the bank's posture (which remains `FROZEN`, since `PROSPECTUS_REVIEW` is not a sales-eligible status) and incrementing the bank's `version` by one."
    PRD §3.3: "The first vote of a round auto-advances the prospectus `SUBMITTED → UNDER_REVIEW` and stamps `review_opened_at` with the clock."
    Design: Corner/state_machines/prospectus_submission_transitions_bank_to_prospectus_review
    """
    set_clock(CLOCK_START)
    world = setup_draft_bank()
    prospectus = draft_prospectus(world)

    data = validate_success(
        api_client.submit_prospectus(prospectus["id"], world["sponsor_headers"]), 200
    )
    assert_prospectus(data)
    assert data["status"] == "SUBMITTED", (
        f"submission advances DRAFT -> SUBMITTED, got {data['status']}"
    )
    assert_instant(data["submitted_at"], CLOCK_START, "prospectus submitted_at")
    assert data["revision_round"] == 1, (
        f"submission does not open a new revision round, got {data['revision_round']}"
    )
    assert data["review_opened_at"] is None, (
        "review_opened_at stays null until the first vote of the round arrives"
    )

    reread = validate_success(
        api_client.get_prospectus(prospectus["id"], world["sponsor_headers"]), 200
    )
    assert reread["status"] == "SUBMITTED", (
        f"the persisted prospectus stands in SUBMITTED, got {reread['status']}"
    )


def test_prospectus_submission_drags_the_bank_to_prospectus_review_still_frozen():
    """The very same submit performs the coupled bank transition: the bank goes
    DRAFT -> PROSPECTUS_REVIEW, its version rises 1 -> 2 for the whole request,
    and its recomputed posture stays FROZEN because PROSPECTUS_REVIEW is not a
    sales-eligible status.

    PRD §3.3: "Submission by the owning sponsor advances the prospectus `DRAFT → SUBMITTED`, stamps `submitted_at` with the current logical clock, and — this is the side effect that starts the regulatory machine — drags the bank from `DRAFT` to `PROSPECTUS_REVIEW`, recomputing the bank's posture (which remains `FROZEN`, since `PROSPECTUS_REVIEW` is not a sales-eligible status) and incrementing the bank's `version` by one."
    PRD §2.8: "If the bank's `status` is `DRAFT`, `PROSPECTUS_REVIEW`, `SUSPENDED` or `CLOSED`, the posture is `FROZEN`."
    Design: Corner/state_machines/prospectus_submission_transitions_bank_to_prospectus_review
    """
    set_clock(CLOCK_START)
    world = setup_draft_bank()
    assert world["bank"]["version"] == 1, "the freshly registered bank is at version 1"
    prospectus = draft_prospectus(world)

    validate_success(
        api_client.submit_prospectus(prospectus["id"], world["sponsor_headers"]), 200
    )

    bank = bank_state(world)
    assert_bank(bank)
    assert bank["status"] == "PROSPECTUS_REVIEW", (
        f"submission drags the bank to PROSPECTUS_REVIEW, got {bank['status']}"
    )
    assert bank["version"] == 2, (
        f"the bank's version increments by exactly 1 for the request, got {bank['version']}"
    )
    assert bank["sales_posture"] == "FROZEN", (
        f"a PROSPECTUS_REVIEW bank's posture is FROZEN, got {bank['sales_posture']}"
    )
    assert_credits(bank["credits_available"], 0.00, "credits_available after submission")


def test_second_submit_on_an_under_review_prospectus_is_rejected_not_reapplied():
    """Replaying a completed transition is refused rather than re-applied: a
    second submit on a prospectus that has already reached UNDER_REVIEW returns
    409 ERR_PROSPECTUS_STATE_INVALID and leaves the round's three tallies, the
    revision round and the decision stamps exactly as they were.

    PRD §3.3: "Submission is admissible only while the prospectus is in `DRAFT`, only while the bank is still in `DRAFT`, and only when the bank's service area contains the bank's own site watershed code."
    PRD §3.3: "Each vote raises exactly one of `concur_count`, `object_count` or `abstain_count` by one — the tallies count only votes bearing the prospectus's current revision round — and a veto vote raises the object tally and additionally sets `veto_recorded` to true."
    Design: Corner/state_machines/repeat_submit_and_repeat_finalize_are_rejected_not_reapplied
    """
    set_clock(CLOCK_START)
    world = setup_bank_under_review(
        work_plan_state="SUBMITTED", vote_positions=["CONCUR", "CONCUR", "CONCUR"]
    )
    prospectus_id = world["prospectus"]["id"]

    validate_error(
        api_client.submit_prospectus(prospectus_id, world["sponsor_headers"]),
        ApiErrorId.ERR_PROSPECTUS_STATE_INVALID,
        409,
    )

    reread = validate_success(
        api_client.get_prospectus(prospectus_id, world["sponsor_headers"]), 200
    )
    assert reread["status"] == "UNDER_REVIEW", (
        f"the refused submit leaves the prospectus UNDER_REVIEW, got {reread['status']}"
    )
    assert reread["revision_round"] == 1, (
        f"the refused submit opens no new round, got {reread['revision_round']}"
    )
    assert reread["concur_count"] == 3, (
        f"the three CONCUR votes stand untouched, got {reread['concur_count']}"
    )
    assert reread["object_count"] == 0, "no objection was recorded"
    assert reread["abstain_count"] == 0, "no abstention was recorded"
    assert reread["veto_recorded"] is False, "no veto stands in this round"
    assert reread["decided_at"] is None, "the round has not been closed yet"
    assert reread["decision_recorded_by"] is None, "no chair decision is recorded yet"


def test_second_finalize_review_on_an_approved_prospectus_is_rejected():
    """The chair may close a round only on an UNDER_REVIEW prospectus, so the
    first finalize approves and the replay returns 409
    ERR_PROSPECTUS_STATE_INVALID, leaving revision_round 1, the tallies at 3/0/0
    and decided_at at the instant of the first decision, with the bank still
    sitting in PROSPECTUS_REVIEW because finalising executes no instrument.

    PRD §3.3: "The chair closes a round on a prospectus that is `UNDER_REVIEW`, and the outcome is decided by three tests applied to the votes of the current round."
    PRD §3.3: "When quorum is met, no veto stands, the supermajority is reached, and the bank additionally has a work plan in either `SUBMITTED` or `APPROVED` status, the prospectus goes `UNDER_REVIEW → APPROVED`; if no such work plan exists the finalisation is rejected with `ERR_WORK_PLAN_MISSING`."
    PRD §3.3: "Every one of the three finalisation branches records the chair's opaque caller identity into `decision_recorded_by` and stamps `decided_at` with the clock; those two side effects are common to approval, revision request and rejection alike."
    Design: Corner/state_machines/repeat_submit_and_repeat_finalize_are_rejected_not_reapplied
    """
    set_clock(CLOCK_START)
    world = setup_bank_under_review(
        work_plan_state="SUBMITTED", vote_positions=["CONCUR", "CONCUR", "CONCUR"]
    )
    prospectus_id = world["prospectus"]["id"]

    first = validate_success(
        api_client.finalize_prospectus_review(prospectus_id, world["chair_headers"]), 200
    )
    assert first["status"] == "APPROVED", (
        f"quorum, no veto and a SUBMITTED work plan approve the prospectus, "
        f"got {first['status']}"
    )
    assert_instant(first["decided_at"], CLOCK_START, "prospectus decided_at")

    validate_error(
        api_client.finalize_prospectus_review(prospectus_id, world["chair_headers"]),
        ApiErrorId.ERR_PROSPECTUS_STATE_INVALID,
        409,
    )

    reread = validate_success(
        api_client.get_prospectus(prospectus_id, world["chair_headers"]), 200
    )
    assert reread["status"] == "APPROVED", (
        f"the refused replay leaves the prospectus APPROVED, got {reread['status']}"
    )
    assert reread["revision_round"] == 1, (
        f"the refused replay opens no new round, got {reread['revision_round']}"
    )
    assert reread["concur_count"] == 3, "the concur tally is untouched by the replay"
    assert reread["object_count"] == 0, "the object tally is untouched by the replay"
    assert reread["abstain_count"] == 0, "the abstain tally is untouched by the replay"
    assert_instant(reread["decided_at"], CLOCK_START, "decided_at after the replay")

    votes, meta = validate_paginated(
        api_client.list_prospectus_votes(
            prospectus_id, world["chair_headers"], params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 3, (
        f"no vote was duplicated or rewritten, got total_count {meta['total_count']}"
    )
    assert len(votes) == 3, f"expected the three round-1 votes, got {len(votes)}"

    bank = bank_state(world)
    assert bank["status"] == "PROSPECTUS_REVIEW", (
        "finalising the prospectus does not execute the banking instrument, "
        f"got bank status {bank['status']}"
    )


def test_assigned_sale_rejects_both_reversal_and_withdrawal():
    """ASSIGNED is terminal: the chair's reversal and the buyer's withdrawal both
    return 409 ERR_SALE_STATE_INVALID, and the sale row keeps its ASSIGNED status,
    its null cancellation fields, its retained settled price and the assignment
    reference minted from the permit number, the site watershed and the quantity.

    PRD §3.9: "Reversal is the chair's exclusive compensating transaction and is available only on a sale standing in `EXECUTED`; an assigned sale is terminal and can never be reversed, because its credits have already discharged a permit obligation."
    PRD §3.8: "Any attempt to reserve a sale that is not quoted, settle one that is not reserved, assign one that is not settled, withdraw one that is already settled, assigned, cancelled or expired, or reverse one that is not settled, is rejected with `ERR_SALE_STATE_INVALID`."
    PRD §3.8: "It advances the sale `EXECUTED → ASSIGNED`, requires the requested quantity not to exceed the buyer's remaining unmet obligation, stamps `assigned_at` with the clock, and generates an `assignment_reference` formed as the buyer's permit number, a forward slash, the bank's site watershed code, another forward slash, and the requested credit quantity."
    Design: Corner/state_machines/assigned_sale_cannot_be_reversed_or_cancelled
    """
    world, quoted, assigned = _assigned_sale_world()
    assert assigned["status"] == "ASSIGNED", (
        f"the sale reached ASSIGNED before the lockdown probes, got {assigned['status']}"
    )
    expected_reference = "{}/{}/{}".format(
        world["permittee"]["permit_number"], TEST_DEFAULTS["SITE_HUC8"], "4.00"
    )
    assert assigned["assignment_reference"] == expected_reference, (
        f"expected assignment_reference {expected_reference}, "
        f"got {assigned['assignment_reference']}"
    )
    assert_instant(assigned["assigned_at"], CLOCK_START, "assigned_at")

    validate_error(
        api_client.reverse_credit_sale(quoted["id"], world["chair_headers"]),
        ApiErrorId.ERR_SALE_STATE_INVALID,
        409,
    )
    validate_error(
        api_client.cancel_credit_sale(
            quoted["id"],
            cancel_sale_payload("BUYER_WITHDREW"),
            world["permittee_headers"],
        ),
        ApiErrorId.ERR_SALE_STATE_INVALID,
        409,
    )

    reread = sale_state(quoted["id"], world)
    assert reread["status"] == "ASSIGNED", (
        f"an assigned sale stays ASSIGNED, got {reread['status']}"
    )
    assert reread["cancelled_reason"] is None, (
        f"no cancellation reason is stamped, got {reread['cancelled_reason']!r}"
    )
    assert reread["cancelled_at"] is None, (
        f"no cancellation instant is stamped, got {reread['cancelled_at']!r}"
    )
    assert reread["assignment_reference"] == expected_reference, (
        "the assignment reference survives the refused writes"
    )


def test_refused_writes_on_an_assigned_sale_move_no_ledger_row_and_no_money():
    """The refused reversal and withdrawal leave the six-row append-only ledger,
    the bank's credit aggregates, the buyer's escrow balance and the buyer's
    obligation figures exactly where the assignment left them.

    PRD §3.8: "A ledger entry of type `ASSIGNED` is appended for the audit trail carrying a delta of exactly 0.00, so the running balance is unchanged, and the buyer's assigned credits and unmet obligation are recomputed."
    PRD §3.8: "Pricing starts from the bank's hydrogeomorphic class, which fixes a base price per credit: 4,250,000 cents for `RIVERINE`, 3,800,000 cents for `DEPRESSIONAL`, 3,600,000 cents for `SLOPE`, 3,300,000 cents for `FLATS` and 5,100,000 cents for `ESTUARINE`."
    PRD §3.8: "A bank whose stewardship endowment is funded below its requirement attracts a further 8 percent, and a fully funded bank attracts nothing."
    PRD §3.1: "`escrow_balance_cents` is the deposited total minus the sum of the settled prices of all of this holder's sales standing in `EXECUTED` or `ASSIGNED` status, and likewise starts at 0."
    PRD §3.1: "`unmet_requirement_credits` is the required credits minus the assigned credits, floored at zero so it can never go negative, carried to 2 decimal places, and therefore equal to the required credits at registration."
    Design: Corner/state_machines/assigned_sale_cannot_be_reversed_or_cancelled
    """
    world, quoted, assigned = _assigned_sale_world()
    assert_cents(assigned["quoted_price_cents"], 16416000, "quoted_price_cents")
    assert_cents(assigned["executed_price_cents"], 16416000, "executed_price_cents")

    validate_error(
        api_client.reverse_credit_sale(quoted["id"], world["chair_headers"]),
        ApiErrorId.ERR_SALE_STATE_INVALID,
        409,
    )
    validate_error(
        api_client.cancel_credit_sale(
            quoted["id"],
            cancel_sale_payload("BUYER_WITHDREW"),
            world["permittee_headers"],
        ),
        ApiErrorId.ERR_SALE_STATE_INVALID,
        409,
    )

    entries = ledger_rows(world)
    assert_ledger_sequence(entries)
    assert_ledger_shape(
        entries,
        [
            ("GENERATED", 0.00, 0.00),
            ("RELEASED", 14.82, 14.82),
            ("HOLD_PLACED", -4.00, 10.82),
            ("HOLD_RELEASED", 4.00, 14.82),
            ("SOLD", -4.00, 10.82),
            ("ASSIGNED", 0.00, 10.82),
        ],
    )

    bank = bank_state(world)
    assert_credits(bank["credits_sold"], 4.00, "credits_sold")
    assert_credits(bank["credits_on_hold"], 0.00, "credits_on_hold")
    assert_credits(bank["credits_available"], 10.82, "credits_available")

    buyer = permittee_state(world)
    assert_cents(buyer["escrow_balance_cents"], 23584000, "escrow_balance_cents")
    assert_credits(buyer["assigned_credits"], 4.00, "assigned_credits")
    assert_credits(buyer["unmet_requirement_credits"], 16.00, "unmet_requirement_credits")


def test_work_plan_return_branch_materialises_no_performance_standards():
    """The RETURN branch of the work-plan decision advances SUBMITTED -> RETURNED,
    stamps decided_at and stores the chair's reason, but materialises zero
    performance-standard rows for the bank.

    PRD §3.4: "Returning instead advances `SUBMITTED → RETURNED`, stamps `decided_at`, and stores the chair's `return_reason` — which must be supplied on this branch, its absence being a malformed request."
    PRD §3.4: "The return branch materialises no performance standard rows at all and leaves the bank entirely untouched."
    PRD §2.11: "The performance-standards read is ordered by `effective_from_year` and then by `standard_code`, and is the only way to observe performance standard rows at all — they have no creation endpoint of their own."
    Design: Corner/state_machines/work_plan_return_branch_materialises_no_performance_standards
    """
    set_clock(CLOCK_START)
    world = setup_bank_under_review(work_plan_state="SUBMITTED")
    cast_votes(world)
    finalize_prospectus(world)
    reason = "Hydroperiod target must cite the reference wetland gauge"

    returned = validate_success(
        api_client.decide_work_plan(
            world["work_plan"]["id"],
            decide_work_plan_payload("RETURN", return_reason=reason),
            world["chair_headers"],
        ),
        200,
    )
    assert_work_plan(returned)
    assert returned["status"] == "RETURNED", (
        f"the RETURN branch advances SUBMITTED -> RETURNED, got {returned['status']}"
    )
    assert returned["return_reason"] == reason, (
        f"the chair's reason is stored verbatim, got {returned['return_reason']!r}"
    )
    assert_instant(returned["decided_at"], CLOCK_START, "work plan decided_at on RETURN")

    rows, meta = validate_paginated(
        api_client.list_bank_performance_standards(
            world["bank"]["id"], world["chair_headers"], params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 0, (
        f"the RETURN branch materialises nothing, got total_count {meta['total_count']}"
    )
    assert rows == [], f"expected no performance standard rows, got {rows}"


def test_resubmitted_work_plan_approval_materialises_the_four_declared_standards():
    """Resubmission clears the return reason and the later APPROVE branch shows the
    divergent side-effect set: exactly one performance-standard row per declared
    entry, each stamped with the plan's bank identifier and read back ordered by
    effective year then standard code.

    PRD §3.4: "A returned plan may be resubmitted, advancing `RETURNED → SUBMITTED`, restamping `submitted_at` and clearing `return_reason` back to null."
    PRD §3.4: "Approving advances `SUBMITTED → APPROVED`, stamps `decided_at`, and materialises exactly one performance-standard row per entry of the plan's standards array, each stamped with the plan's bank identifier; the bank's `version` increments by one."
    PRD §3.4: "Each stratum's credit contribution is its acreage multiplied by its lift factor, rounded half up to 2 decimal places, and the plan total is the sum of those already-rounded per-stratum contributions."
    Design: Corner/state_machines/work_plan_return_branch_materialises_no_performance_standards
    """
    set_clock(CLOCK_START)
    world = setup_bank_under_review(work_plan_state="SUBMITTED")
    cast_votes(world)
    finalize_prospectus(world)
    work_plan_id = world["work_plan"]["id"]
    validate_success(
        api_client.decide_work_plan(
            work_plan_id,
            decide_work_plan_payload(
                "RETURN", return_reason="Hydroperiod target must cite the reference gauge"
            ),
            world["chair_headers"],
        ),
        200,
    )

    resubmitted = validate_success(
        api_client.submit_work_plan(work_plan_id, world["sponsor_headers"]), 200
    )
    assert resubmitted["status"] == "SUBMITTED", (
        f"a returned plan is resubmitted into SUBMITTED, got {resubmitted['status']}"
    )
    assert resubmitted["return_reason"] is None, (
        f"resubmission clears return_reason, got {resubmitted['return_reason']!r}"
    )

    approved = validate_success(
        api_client.decide_work_plan(
            work_plan_id, decide_work_plan_payload("APPROVE"), world["chair_headers"]
        ),
        200,
    )
    assert approved["status"] == "APPROVED", (
        f"the APPROVE branch advances SUBMITTED -> APPROVED, got {approved['status']}"
    )
    assert_instant(approved["decided_at"], CLOCK_START, "work plan decided_at on APPROVE")
    assert_credits(approved["total_planned_credits"], 98.77, "total_planned_credits")

    rows, meta = validate_paginated(
        api_client.list_bank_performance_standards(
            world["bank"]["id"], world["chair_headers"], params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 4, (
        f"one row per declared standard, got total_count {meta['total_count']}"
    )
    expected = [
        ("HYDROPERIOD_DAYS", "GTE", 120, 0.300, 1),
        ("INVASIVE_COVER_PCT", "LTE", 10.0, 0.250, 1),
        ("NATIVE_COVER_PCT", "GTE", 80.0, 0.300, 3),
        ("STEM_DENSITY_PER_ACRE", "GTE", 400, 0.150, 3),
    ]
    assert len(rows) == 4, f"expected four materialised standards, got {len(rows)}"
    for row, (code, comparator, threshold, weight, year) in zip(rows, expected):
        assert_performance_standard(row)
        assert row["standard_code"] == code, (
            f"standards are ordered by effective year then code; expected {code}, "
            f"got {row['standard_code']}"
        )
        assert row["comparator"] == comparator, f"{code}: comparator"
        assert float(row["threshold_value"]) == float(threshold), f"{code}: threshold_value"
        assert float(row["weight"]) == float(weight), f"{code}: weight"
        assert row["effective_from_year"] == year, f"{code}: effective_from_year"
        assert row["bank_id"] == world["bank"]["id"], (
            f"{code}: every materialised standard carries the plan's bank identifier"
        )


def test_milestone_claim_before_its_window_opens_is_rejected():
    """A claim lodged while the clock still sits before window_start is refused
    with 409 ERR_MILESTONE_WINDOW_NOT_OPEN and the milestone stays PENDING with
    claimed_at null and nothing released.

    PRD §3.6: "It is admissible only while the bank is in `INSTRUMENT_EXECUTED` or `MONITORING` status, only once the logical clock has reached or passed the window start — an earlier attempt is rejected with `ERR_MILESTONE_WINDOW_NOT_OPEN` — and only when the milestone either has no predecessor or has a predecessor already standing in `APPROVED`; an unreleased predecessor is rejected with `ERR_PREDECESSOR_NOT_RELEASED`."
    Design: Corner/state_machines/milestone_claim_outside_its_window_is_rejected
    """
    set_clock(CLOCK_START)
    world = setup_executed_bank(record_easement=True)
    milestone = add_milestone(
        world,
        milestone_code="INSTRUMENT_EXECUTION",
        release_pct=0.150,
        window_start="2026-09-15T00:00:00Z",
        window_end="2026-10-15T00:00:00Z",
    )

    validate_error(
        api_client.claim_milestone(milestone["id"], world["sponsor_headers"]),
        ApiErrorId.ERR_MILESTONE_WINDOW_NOT_OPEN,
        409,
    )

    reread = milestone_state(milestone["id"], world)
    assert reread["status"] == "PENDING", (
        f"the refused claim leaves the milestone PENDING, got {reread['status']}"
    )
    assert reread["claimed_at"] is None, (
        f"the refused claim stamps no claimed_at, got {reread['claimed_at']!r}"
    )
    assert reread["attainment_factor_applied"] is None, (
        "a refused claim consults no monitoring report and applies no factor"
    )
    assert_credits(reread["final_release_credits"], 0.00, "final_release_credits")

    bank = bank_state(world)
    assert_credits(bank["credits_released"], 0.00, "credits_released after a refused claim")
    assert_credits(bank["credits_available"], 0.00, "credits_available after a refused claim")


def test_milestone_claim_at_exactly_window_start_succeeds_and_releases_nothing():
    """window_start is inclusive, so the identical claim lodged at exactly that
    instant advances PENDING -> CLAIMED, stamps claimed_at from the clock and
    recomputes the provisional tranche to 14.82 — while releasing no credits,
    because a claim is not an approval.

    PRD §3.6: "Claiming is the sponsor's assertion that the milestone has been attained, and it advances the milestone `PENDING → CLAIMED` while stamping `claimed_at` with the logical clock."
    PRD §3.6: "That provisional figure is the bank's authorised credit total multiplied by the milestone's release percentage, rounded half up to 2 decimal places."
    PRD §3.6: "The provisional variant always applies an attainment factor of exactly 1.00 and consults no monitoring report whatsoever, which is why a claim can never fail on ecological grounds."
    Design: Corner/state_machines/milestone_claim_outside_its_window_is_rejected
    """
    set_clock(CLOCK_START)
    world = setup_executed_bank(record_easement=True)
    milestone = add_milestone(
        world,
        milestone_code="INSTRUMENT_EXECUTION",
        release_pct=0.150,
        window_start="2026-09-15T00:00:00Z",
        window_end="2026-10-15T00:00:00Z",
    )
    set_clock("2026-09-15T00:00:00Z")

    claimed = validate_success(
        api_client.claim_milestone(milestone["id"], world["sponsor_headers"]), 200
    )
    assert_milestone(claimed)
    assert claimed["status"] == "CLAIMED", (
        f"a claim at exactly window_start advances to CLAIMED, got {claimed['status']}"
    )
    assert_credits(
        claimed["provisional_release_credits"],
        14.82,
        "provisional_release_credits (98.77 x 0.150)",
    )
    assert_instant(claimed["claimed_at"], "2026-09-15T00:00:00Z", "claimed_at")
    assert_credits(claimed["final_release_credits"], 0.00, "final_release_credits")
    assert claimed["attainment_factor_applied"] is None, (
        "the attainment factor is stamped only when the release is approved"
    )

    bank = bank_state(world)
    assert_credits(bank["credits_released"], 0.00, "a claim releases nothing")
    assert_credits(bank["credits_available"], 0.00, "a claim frees no available credit")


def test_bank_closure_advances_monitoring_to_closed_and_freezes_the_posture():
    """The first accepted report carries the bank into MONITORING, and from there
    the chair's closure advances MONITORING -> CLOSED, stamps closed_at from the
    logical clock and recomputes the posture to FROZEN.

    PRD §3.7: "If the bank has never had an accepted report before, this acceptance additionally carries the bank `INSTRUMENT_EXECUTED → MONITORING`."
    PRD §3.7: "The report's `attainment_score` is the sum of those already-rounded contributions divided by the sum of the effective standards' weights as supplied — the denominator uses the unrounded weights and covers only the standards effective in this year, so a report in an early monitoring year is scored against a denominator smaller than 1.000 — with the quotient rounded half up to 4 decimal places."
    PRD §3.7: "The compliance status then follows from those two outputs in order: it is `PASS` when no standard failed, otherwise `PARTIAL` when the attainment score is at least 0.85 — the boundary is inclusive — and otherwise `FAIL`."
    PRD §3.9: "It advances the bank `MONITORING → CLOSED` and is admissible only from `MONITORING`."
    PRD §3.9: "On success, `closed_at` is stamped with the logical clock, the posture is recomputed to `FROZEN`, every credit sale of the bank still standing in `QUOTED` or `RESERVED` is cancelled with a `cancelled_reason` of `SPONSOR_WITHDREW` and each formerly reserved sale appends a `HOLD_RELEASED` entry restoring its held credits, and the bank's `version` increments by one."
    Design: Corner/state_machines/bank_closure_cascades_cancellation_of_open_quotes
    """
    world, report, _sale = _closable_bank_with_open_quote()
    assert report["compliance_status"] == "PASS", (
        f"no year-1 standard was missed, got {report['compliance_status']}"
    )
    assert_score(report["attainment_score"], 1.0000, "year-1 attainment_score")

    before = bank_state(world)
    assert before["status"] == "MONITORING", (
        f"the first accepted report carries the bank to MONITORING, got {before['status']}"
    )

    closed = validate_success(
        api_client.close_bank(world["bank"]["id"], world["chair_headers"]), 200
    )
    assert_bank(closed)
    assert closed["status"] == "CLOSED", (
        f"closure advances MONITORING -> CLOSED, got {closed['status']}"
    )
    assert closed["sales_posture"] == "FROZEN", (
        f"a CLOSED bank's posture is FROZEN, got {closed['sales_posture']}"
    )
    assert_instant(closed["closed_at"], "2027-08-15T00:00:00Z", "closed_at")
    assert closed["version"] > before["version"], (
        "the closure increments the bank's version"
    )


def test_bank_closure_cancels_the_outstanding_quote_without_touching_the_ledger():
    """Closure cascades one hop down into the bank's sales: the outstanding QUOTED
    sale is cancelled with a reason the client never supplied and cancelled_at
    stamped from the clock, the derived open quote tally falls to zero, and the
    two immutable ledger rows are untouched because a quote never held credits.

    PRD §3.9: "On success, `closed_at` is stamped with the logical clock, the posture is recomputed to `FROZEN`, every credit sale of the bank still standing in `QUOTED` or `RESERVED` is cancelled with a `cancelled_reason` of `SPONSOR_WITHDREW` and each formerly reserved sale appends a `HOLD_RELEASED` entry restoring its held credits, and the bank's `version` increments by one."
    PRD §3.8: "Cancelling a quote advances `QUOTED → CANCELLED`, stamps the reason and `cancelled_at`, and lowers the bank's open quote count; no ledger entry is written because no hold ever existed."
    PRD §3.8: "That counter is a derived tally rather than a hand-maintained number: it is the count of the bank's credit sales standing in either `QUOTED` or `RESERVED`, so a quote that is placed on hold continues to be counted, and a sale leaves the tally only when it settles, is withdrawn or expires."
    Design: Corner/state_machines/bank_closure_cascades_cancellation_of_open_quotes
    """
    world, _report, sale = _closable_bank_with_open_quote()
    assert sale["status"] == "QUOTED", (
        f"the sale stands in QUOTED before the closure, got {sale['status']}"
    )

    validate_success(
        api_client.close_bank(world["bank"]["id"], world["chair_headers"]), 200
    )

    cascaded = sale_state(sale["id"], world)
    assert cascaded["status"] == "CANCELLED", (
        f"closure cancels the outstanding quote, got {cascaded['status']}"
    )
    assert cascaded["cancelled_reason"] == "SPONSOR_WITHDREW", (
        "closure stamps a cancellation reason the client never supplied, "
        f"got {cascaded['cancelled_reason']!r}"
    )
    assert_instant(cascaded["cancelled_at"], "2027-08-15T00:00:00Z", "sale cancelled_at")

    bank = bank_state(world)
    assert bank["open_quote_count"] == 0, (
        f"the derived open quote tally falls to 0, got {bank['open_quote_count']}"
    )
    assert_credits(bank["credits_released"], 14.82, "credits_released after closure")
    assert_credits(bank["credits_available"], 14.82, "credits_available after closure")
    assert_credits(bank["credits_on_hold"], 0.00, "credits_on_hold after closure")

    entries = ledger_rows(world)
    assert_ledger_sequence(entries)
    assert_ledger_shape(
        entries,
        [
            ("GENERATED", 0.00, 0.00),
            ("RELEASED", 14.82, 14.82),
        ],
    )
