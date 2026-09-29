"""Cross-entity prerequisite gates.

Every test in this module drives one entity's write up to the point where the
only thing left standing in the way is the state of a *different* entity: a
release milestone waiting on a monitoring report, a credit quote waiting on a
released milestone, a prospectus waiting on a work plan, and a milestone
waiting on its predecessor. Each gate is exercised twice — once with the
prerequisite absent, so the specific rejection surfaces, and once with the
prerequisite cured on the other entity, so the identical write lands.
"""

from test_helpers import (
    TEST_DEFAULTS,
    YEAR3_PASSING_MEASUREMENTS,
    ApiErrorId,
    add_milestone,
    api_client,
    approve_release,
    approve_release_payload,
    assert_cents,
    assert_credits,
    assert_score,
    bank_state,
    bank_version,
    claim_milestone,
    create_credit_sale_payload,
    draft_work_plan,
    fund_stewardship,
    get_success_data,
    ledger_rows,
    milestone_state,
    open_monitoring_report,
    release_milestone_fully,
    review_monitoring_report,
    set_clock,
    setup_bank_under_review,
    setup_executed_bank,
    setup_sellable_bank,
    submit_monitoring_report,
    submit_work_plan,
    validate_error,
    validate_paginated,
    validate_success,
)

# The canonical milestone ladder: the first window closes 2026-09-01 and the
# next window opens a full 365 days later.
FIRST_WINDOW_START = "2026-08-01T00:00:00Z"
FIRST_WINDOW_END = "2026-09-01T00:00:00Z"
SECOND_WINDOW_START = "2027-09-01T00:00:00Z"
SECOND_WINDOW_END = "2027-10-01T00:00:00Z"
SECOND_WINDOW_CLOCK = "2027-09-15T00:00:00Z"

# The year-3 field monitoring window, adjacent to the second release window.
REPORT_WINDOW_START = "2027-06-01T00:00:00Z"
REPORT_WINDOW_END = "2027-09-01T00:00:00Z"


def _bank_with_claimed_perf_year_3() -> dict:
    """A sellable bank whose PERF_YEAR_3 milestone is chained behind the
    released INSTRUMENT_EXECUTION milestone and already sits in CLAIMED, with no
    monitoring report on the bank at all."""
    world = setup_sellable_bank()
    predecessor = world["milestones"]["INSTRUMENT_EXECUTION"]
    add_milestone(
        world,
        milestone_code="PERF_YEAR_3",
        release_pct=0.250,
        window_start=SECOND_WINDOW_START,
        window_end=SECOND_WINDOW_END,
        predecessor_milestone_id=predecessor["id"],
    )
    set_clock(SECOND_WINDOW_CLOCK)
    claim_milestone(world, world["milestones"]["PERF_YEAR_3"]["id"])
    world["bank"] = bank_state(world)
    return world


def _attempt_release(world: dict, milestone_id: str):
    """Approve-release under a freshly read concurrency token, so the request
    can only ever fail on the regulatory or referential checks."""
    return api_client.approve_milestone_release(
        milestone_id,
        approve_release_payload(bank_version(world)),
        world["member_headers"][0],
    )


def test_perf_release_refused_while_the_bank_holds_no_accepted_report():
    """A CLAIMED performance milestone cannot be released while the bank owns no
    monitoring report in ACCEPTED, and a DRAFT report does not satisfy the
    dependency either — only the review status ACCEPTED does.

    PRD §3.6: "If no accepted report exists for the bank, the approval is rejected with `ERR_NO_ACCEPTED_MONITORING_REPORT`."
    PRD §3.6: "For the three performance milestones, the server selects the governing monitoring report: among the bank's reports whose review status is `ACCEPTED`, the one with the highest monitoring year, and where two accepted reports share the highest monitoring year, the most recently created of them."
    Design: Difficulty/cross_entity_state_dependency/perf_milestone_release_requires_accepted_monitoring_report
    """
    world = _bank_with_claimed_perf_year_3()
    milestone_id = world["milestones"]["PERF_YEAR_3"]["id"]

    no_report = _attempt_release(world, milestone_id)
    validate_error(no_report, ApiErrorId.ERR_NO_ACCEPTED_MONITORING_REPORT, 422)

    report = open_monitoring_report(
        world,
        monitoring_year=3,
        window_start=REPORT_WINDOW_START,
        window_end=REPORT_WINDOW_END,
        measurements_array=YEAR3_PASSING_MEASUREMENTS,
    )
    assert report["review_status"] == "DRAFT", (
        f"a freshly opened report must sit in DRAFT, got {report['review_status']}"
    )

    draft_report_present = _attempt_release(world, milestone_id)
    validate_error(
        draft_report_present, ApiErrorId.ERR_NO_ACCEPTED_MONITORING_REPORT, 422
    )

    after = milestone_state(milestone_id, world)
    assert after["status"] == "CLAIMED", (
        f"the rejected milestone must stay CLAIMED, got {after['status']}"
    )
    assert after["approved_at"] is None, "a refused release stamps no approved_at"
    assert_credits(
        after["provisional_release_credits"],
        24.69,
        "PERF_YEAR_3 provisional_release_credits",
    )


def test_perf_release_succeeds_once_the_monitoring_report_is_accepted():
    """Accepting the year-3 report on the other entity cures the dependency: the
    accepted report scores a full 1.0000 and PASSes, so the governing factor is
    1.00 and the whole provisional tranche is released.

    PRD §3.7: "The compliance status then follows from those two outputs in order: it is `PASS` when no standard failed, otherwise `PARTIAL` when the attainment score is at least 0.85 — the boundary is inclusive — and otherwise `FAIL`."
    PRD §3.6: "Otherwise the factor is selected from the report's attainment score by two thresholds, both of which are inclusive at their boundary: a score of at least 0.95 earns a factor of 1.00, a score of at least 0.85 but below 0.95 earns a factor of 0.90, and a score below 0.85 is rejected with `ERR_COMPLIANCE_FAILED`."
    PRD §3.6: "The final release quantity is then the *already-rounded* provisional quantity multiplied by the selected factor, rounded half up to 2 decimal places again."
    Design: Difficulty/cross_entity_state_dependency/perf_milestone_release_requires_accepted_monitoring_report
    """
    world = _bank_with_claimed_perf_year_3()
    milestone_id = world["milestones"]["PERF_YEAR_3"]["id"]

    report = open_monitoring_report(
        world,
        monitoring_year=3,
        window_start=REPORT_WINDOW_START,
        window_end=REPORT_WINDOW_END,
        measurements_array=YEAR3_PASSING_MEASUREMENTS,
    )
    submit_monitoring_report(world, report["id"])
    accepted = review_monitoring_report(world, report["id"], "ACCEPT", member_index=1)

    assert accepted["review_status"] == "ACCEPTED", (
        f"the report must reach ACCEPTED, got {accepted['review_status']}"
    )
    assert_score(accepted["attainment_score"], 1.0000, "attainment_score")
    assert accepted["compliance_status"] == "PASS", (
        f"every effective standard was met, so compliance must be PASS, got "
        f"{accepted['compliance_status']}"
    )

    released = validate_success(_attempt_release(world, milestone_id), 200)
    assert released["status"] == "APPROVED", (
        f"the cured release must advance the milestone to APPROVED, got "
        f"{released['status']}"
    )
    assert_credits(
        released["attainment_factor_applied"], 1.00, "attainment_factor_applied"
    )
    assert_credits(
        released["final_release_credits"], 24.69, "PERF_YEAR_3 final_release_credits"
    )


def test_perf_release_after_report_acceptance_extends_the_credit_ledger():
    """The cured release is the only thing that moves the bank's projections: two
    RELEASED entries now stand on the ledger and the bank's released and
    available credits both read 39.51.

    PRD §3.6: "A ledger entry of type `RELEASED` is appended carrying the final release quantity as a positive delta, attributed through a source entity type of `RELEASE_MILESTONE` and the milestone's own identifier, with a memo naming the release, its milestone code and the attainment factor applied."
    PRD §2.11: "`credits_released` is the total of the deltas of the bank's `RELEASED` entries."
    Design: Difficulty/cross_entity_state_dependency/perf_milestone_release_requires_accepted_monitoring_report
    """
    world = _bank_with_claimed_perf_year_3()
    milestone_id = world["milestones"]["PERF_YEAR_3"]["id"]

    report = open_monitoring_report(
        world,
        monitoring_year=3,
        window_start=REPORT_WINDOW_START,
        window_end=REPORT_WINDOW_END,
        measurements_array=YEAR3_PASSING_MEASUREMENTS,
    )
    submit_monitoring_report(world, report["id"])
    review_monitoring_report(world, report["id"], "ACCEPT", member_index=1)
    validate_success(_attempt_release(world, milestone_id), 200)

    releases = ledger_rows(world, entry_type="RELEASED")
    assert len(releases) == 2, (
        f"expected one RELEASED entry per approved milestone, got {len(releases)}"
    )
    assert_credits(releases[0]["delta_credits"], 14.82, "first RELEASED delta_credits")
    assert_credits(releases[1]["delta_credits"], 24.69, "second RELEASED delta_credits")
    assert releases[1]["source_entity_type"] == "RELEASE_MILESTONE", (
        "a release is attributed to the milestone that caused it"
    )
    assert releases[1]["source_id"] == milestone_id, (
        "the RELEASED entry names the approved milestone as its source"
    )

    bank = bank_state(world)
    assert_credits(bank["credits_released"], 39.51, "credits_released")
    assert_credits(bank["credits_available"], 39.51, "credits_available")


def test_quote_refused_while_no_milestone_has_released_any_credit():
    """An executed bank with a recorded easement and an authorised total of 98.77
    credits still cannot be quoted against: no milestone has been approved, so
    available credits are exactly 0.00, the posture ladder lands on SOLD_OUT and
    the quote is refused on the posture rather than on the credit ceiling.

    PRD §2.8: "Otherwise, if the bank's available credits are exactly zero, the posture is `SOLD_OUT`."
    PRD §2.8: "Quoting and reserving both require a posture of exactly `OPEN`."
    PRD §2.8: "The rejection code is keyed to the offending posture value rather than to the operation: a `FROZEN` bank yields `ERR_BANK_SALES_FROZEN`, a `RESTRICTED` bank yields `ERR_BANK_SALES_RESTRICTED`, and a `SOLD_OUT` bank blocking a quote or a reservation yields `ERR_BANK_SOLD_OUT`."
    Design: Difficulty/cross_entity_state_dependency/quote_creation_requires_a_released_milestone_on_the_bank
    """
    world = setup_executed_bank(record_easement=True)
    bank = bank_state(world)

    assert bank["status"] == "INSTRUMENT_EXECUTED", (
        f"the bank must be executed before quoting is attempted, got {bank['status']}"
    )
    assert bank["easement_recorded"] is True, "the easement is recorded in this world"
    assert_credits(bank["total_authorized_credits"], 98.77, "total_authorized_credits")
    assert_credits(bank["credits_available"], 0.00, "credits_available")
    assert bank["sales_posture"] == "SOLD_OUT", (
        f"zero available credits must read SOLD_OUT, got {bank['sales_posture']}"
    )

    rejected = api_client.create_credit_sale(
        create_credit_sale_payload(
            bank["id"],
            world["permittee"]["id"],
            4.00,
            bank["version"],
            impact_huc8_code=bank["site_huc8_code"],
        ),
        world["permittee_headers"],
    )
    validate_error(rejected, ApiErrorId.ERR_BANK_SOLD_OUT, 409)

    sales, meta = validate_paginated(
        api_client.list_credit_sales(
            world["sponsor_headers"], params={"bank_id": bank["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"a refused quote creates no credit sale row, got {meta['total_count']}"
    )
    assert sales == [], "no credit sale may be listed for the bank"
    assert bank_state(world)["open_quote_count"] == 0, (
        "the refused quote may not raise the bank's open quote count"
    )


def test_quote_succeeds_once_a_milestone_release_supplies_available_credits():
    """Releasing the INSTRUMENT_EXECUTION milestone on a different entity flips
    the posture to OPEN, and the identical quote request then succeeds and is
    priced from the DEPRESSIONAL base price with the 8 percent underfunded
    stewardship surcharge.

    PRD §3.6: "The bank's `credits_released` and `credits_available` are recomputed from the ledger, and the posture is recomputed — which is typically the moment a bank moves from `RESTRICTED` to `OPEN`, once credits exist and no remedial action is standing."
    PRD §3.8: "Pricing starts from the bank's hydrogeomorphic class, which fixes a base price per credit: 4,250,000 cents for `RIVERINE`, 3,800,000 cents for `DEPRESSIONAL`, 3,600,000 cents for `SLOPE`, 3,300,000 cents for `FLATS` and 5,100,000 cents for `ESTUARINE`."
    PRD §3.8: "A bank whose stewardship endowment is funded below its requirement attracts a further 8 percent, and a fully funded bank attracts nothing."
    Design: Difficulty/cross_entity_state_dependency/quote_creation_requires_a_released_milestone_on_the_bank
    """
    world = setup_executed_bank(record_easement=True)
    fund_stewardship(world, TEST_DEFAULTS["STEWARDSHIP_INTERIM_GATE_CENTS"])

    milestone = release_milestone_fully(
        world,
        milestone_code="INSTRUMENT_EXECUTION",
        release_pct=0.150,
        window_start=FIRST_WINDOW_START,
        window_end=FIRST_WINDOW_END,
    )
    assert_credits(
        milestone["final_release_credits"], 14.82, "final_release_credits"
    )

    bank = bank_state(world)
    assert_credits(bank["credits_available"], 14.82, "credits_available")
    assert bank["sales_posture"] == "OPEN", (
        f"released credits with no remedial action must read OPEN, got "
        f"{bank['sales_posture']}"
    )

    quoted = validate_success(
        api_client.create_credit_sale(
            create_credit_sale_payload(
                bank["id"],
                world["permittee"]["id"],
                4.00,
                bank["version"],
                impact_huc8_code=bank["site_huc8_code"],
            ),
            world["permittee_headers"],
        ),
        201,
    )
    assert quoted["status"] == "QUOTED", (
        f"a fresh quote opens in QUOTED, got {quoted['status']}"
    )
    assert quoted["service_area_tier"] == "PRIMARY", (
        "the impact watershed is the bank's own site watershed, so the tier is PRIMARY"
    )
    assert_score(quoted["quoted_demand_index"], 0.0000, "quoted_demand_index")
    assert_cents(quoted["quoted_price_cents"], 16416000, "quoted_price_cents")
    assert bank_state(world)["open_quote_count"] == 1, (
        "the successful quote raises the bank's open quote count to 1"
    )


def _prospectus_under_review_without_work_plan() -> dict:
    """A prospectus UNDER_REVIEW with three CONCUR votes cast, on a bank that
    owns no work plan at all."""
    return setup_bank_under_review(
        work_plan_state="NONE", vote_positions=["CONCUR", "CONCUR", "CONCUR"]
    )


def test_prospectus_approval_refused_without_a_work_plan_out_of_draft():
    """Quorum, veto and supermajority are all satisfied, so the prospectus side of
    the decision is complete, yet approval is refused while the bank owns no work
    plan — and a work plan merely created in DRAFT is still not in SUBMITTED or
    APPROVED, so the same rejection stands.

    PRD §3.3: "When quorum is met, no veto stands, the supermajority is reached, and the bank additionally has a work plan in either `SUBMITTED` or `APPROVED` status, the prospectus goes `UNDER_REVIEW → APPROVED`; if no such work plan exists the finalisation is rejected with `ERR_WORK_PLAN_MISSING`."
    Design: Difficulty/cross_entity_state_dependency/prospectus_approval_requires_a_submitted_work_plan
    """
    world = _prospectus_under_review_without_work_plan()
    prospectus_id = world["prospectus"]["id"]

    no_plan = api_client.finalize_prospectus_review(prospectus_id, world["chair_headers"])
    validate_error(no_plan, ApiErrorId.ERR_WORK_PLAN_MISSING, 422)

    plan = draft_work_plan(world)
    assert plan["status"] == "DRAFT", (
        f"a freshly drafted plan opens in DRAFT, got {plan['status']}"
    )

    draft_plan_present = api_client.finalize_prospectus_review(
        prospectus_id, world["chair_headers"]
    )
    validate_error(draft_plan_present, ApiErrorId.ERR_WORK_PLAN_MISSING, 422)

    after = get_success_data(
        api_client.get_prospectus(prospectus_id, world["chair_headers"])
    )
    assert after["status"] == "UNDER_REVIEW", (
        f"both rejections leave the prospectus UNDER_REVIEW, got {after['status']}"
    )
    assert after["decided_at"] is None, "a refused finalisation stamps no decided_at"
    assert after["decision_recorded_by"] is None, (
        "a refused finalisation records no deciding chair"
    )
    assert after["concur_count"] == 3, (
        f"the three CONCUR votes stand untouched, got {after['concur_count']}"
    )
    assert after["revision_round"] == 1, (
        f"a refused finalisation opens no new round, got {after['revision_round']}"
    )


def test_prospectus_approval_succeeds_once_the_work_plan_is_submitted():
    """Submitting the work plan on the other entity cures the dependency and the
    identical finalisation now approves the prospectus, while the bank's
    authorised credit total is still untouched because that copy waits for
    instrument execution.

    PRD §3.3: "When quorum is met, no veto stands, the supermajority is reached, and the bank additionally has a work plan in either `SUBMITTED` or `APPROVED` status, the prospectus goes `UNDER_REVIEW → APPROVED`; if no such work plan exists the finalisation is rejected with `ERR_WORK_PLAN_MISSING`."
    PRD §3.4: "Note what approval does *not* do: it does not write the bank's authorised credit total."
    PRD §3.4: "Each stratum's credit contribution is its acreage multiplied by its lift factor, rounded half up to 2 decimal places, and the plan total is the sum of those already-rounded per-stratum contributions."
    Design: Difficulty/cross_entity_state_dependency/prospectus_approval_requires_a_submitted_work_plan
    """
    world = _prospectus_under_review_without_work_plan()
    prospectus_id = world["prospectus"]["id"]

    draft_work_plan(world)
    submit_work_plan(world)

    approved = validate_success(
        api_client.finalize_prospectus_review(prospectus_id, world["chair_headers"]), 200
    )
    assert approved["status"] == "APPROVED", (
        f"the cured finalisation must approve the prospectus, got {approved['status']}"
    )
    assert approved["decided_at"] is not None, (
        "the approval branch stamps decided_at with the clock"
    )

    plans, _ = validate_paginated(
        api_client.list_bank_work_plans(world["bank"]["id"], world["sponsor_headers"])
    )
    assert len(plans) == 1, f"exactly one work plan exists, got {len(plans)}"
    assert plans[0]["status"] == "SUBMITTED", (
        f"the satisfying plan is still SUBMITTED at approval time, got "
        f"{plans[0]['status']}"
    )
    assert_credits(plans[0]["total_planned_credits"], 98.77, "total_planned_credits")

    bank = bank_state(world)
    assert_credits(bank["total_authorized_credits"], 0.00, "total_authorized_credits")


def _bank_with_chained_milestones() -> dict:
    """An executed bank with the easement recorded and the endowment at the
    interim gate, carrying two PENDING milestones where the second names the
    first as its predecessor, and a clock past both window starts."""
    world = setup_executed_bank(
        record_easement=True,
        stewardship_funded_cents=TEST_DEFAULTS["STEWARDSHIP_INTERIM_GATE_CENTS"],
    )
    first = add_milestone(
        world,
        milestone_code="INSTRUMENT_EXECUTION",
        release_pct=0.150,
        window_start=FIRST_WINDOW_START,
        window_end=FIRST_WINDOW_END,
    )
    add_milestone(
        world,
        milestone_code="CONSTRUCTION_COMPLETE",
        release_pct=0.200,
        window_start=SECOND_WINDOW_START,
        window_end=SECOND_WINDOW_END,
        predecessor_milestone_id=first["id"],
    )
    set_clock(SECOND_WINDOW_CLOCK)
    return world


def test_successor_claim_refused_while_the_predecessor_is_not_yet_approved():
    """The successor's own window is open and its own state is PENDING, so nothing
    about the row itself blocks the claim: the predecessor milestone is the
    blocking entity, and driving it as far as CLAIMED is still not enough.

    PRD §3.6: "It is admissible only while the bank is in `INSTRUMENT_EXECUTED` or `MONITORING` status, only once the logical clock has reached or passed the window start — an earlier attempt is rejected with `ERR_MILESTONE_WINDOW_NOT_OPEN` — and only when the milestone either has no predecessor or has a predecessor already standing in `APPROVED`; an unreleased predecessor is rejected with `ERR_PREDECESSOR_NOT_RELEASED`."
    Design: Difficulty/cross_entity_state_dependency/milestone_claim_requires_predecessor_milestone_released
    """
    world = _bank_with_chained_milestones()
    predecessor_id = world["milestones"]["INSTRUMENT_EXECUTION"]["id"]
    successor_id = world["milestones"]["CONSTRUCTION_COMPLETE"]["id"]

    pending_predecessor = api_client.claim_milestone(
        successor_id, world["sponsor_headers"]
    )
    validate_error(pending_predecessor, ApiErrorId.ERR_PREDECESSOR_NOT_RELEASED, 409)

    claimed = claim_milestone(world, predecessor_id)
    assert claimed["status"] == "CLAIMED", (
        f"the predecessor's own claim must succeed, got {claimed['status']}"
    )
    assert_credits(
        claimed["provisional_release_credits"],
        14.82,
        "INSTRUMENT_EXECUTION provisional_release_credits",
    )

    claimed_predecessor = api_client.claim_milestone(
        successor_id, world["sponsor_headers"]
    )
    validate_error(claimed_predecessor, ApiErrorId.ERR_PREDECESSOR_NOT_RELEASED, 409)

    successor = milestone_state(successor_id, world)
    assert successor["status"] == "PENDING", (
        f"both rejections leave the successor PENDING, got {successor['status']}"
    )
    assert successor["claimed_at"] is None, "a refused claim stamps no claimed_at"


def test_successor_claim_succeeds_once_the_predecessor_release_is_approved():
    """Only an APPROVED predecessor satisfies the edge: once the predecessor's
    release is approved the successor's identical claim lands, recomputing its
    provisional tranche against the bank's authorised total.

    PRD §3.6: "Claiming is the sponsor's assertion that the milestone has been attained, and it advances the milestone `PENDING → CLAIMED` while stamping `claimed_at` with the logical clock."
    PRD §3.6: "That provisional figure is the bank's authorised credit total multiplied by the milestone's release percentage, rounded half up to 2 decimal places."
    Design: Difficulty/cross_entity_state_dependency/milestone_claim_requires_predecessor_milestone_released
    """
    world = _bank_with_chained_milestones()
    predecessor_id = world["milestones"]["INSTRUMENT_EXECUTION"]["id"]
    successor_id = world["milestones"]["CONSTRUCTION_COMPLETE"]["id"]

    claim_milestone(world, predecessor_id)
    released = approve_release(world, predecessor_id)
    assert released["status"] == "APPROVED", (
        f"the predecessor must reach APPROVED, got {released['status']}"
    )
    assert_credits(
        released["final_release_credits"],
        14.82,
        "INSTRUMENT_EXECUTION final_release_credits",
    )

    successor = claim_milestone(world, successor_id)
    assert successor["status"] == "CLAIMED", (
        f"the cured claim must advance the successor to CLAIMED, got "
        f"{successor['status']}"
    )
    assert_credits(
        successor["provisional_release_credits"],
        19.75,
        "CONSTRUCTION_COMPLETE provisional_release_credits",
    )
    assert successor["claimed_at"].startswith("2027-09-15T00:00:00"), (
        f"claimed_at is stamped from the logical clock, got {successor['claimed_at']}"
    )
    assert successor["attainment_factor_applied"] is None, (
        "the attainment factor is stamped by approval, not by the claim"
    )
    assert successor["approved_at"] is None, "a claim is not an approval"


def test_successor_claim_releases_nothing_from_the_credit_ledger():
    """A claim is an assertion, not a release: after the successor's cured claim
    the bank's ledger still carries the single RELEASED entry written by the
    predecessor's approval.

    PRD §3.6: "A ledger entry of type `RELEASED` is appended carrying the final release quantity as a positive delta, attributed through a source entity type of `RELEASE_MILESTONE` and the milestone's own identifier, with a memo naming the release, its milestone code and the attainment factor applied."
    PRD §2.11: "`credits_released` is the total of the deltas of the bank's `RELEASED` entries."
    Design: Difficulty/cross_entity_state_dependency/milestone_claim_requires_predecessor_milestone_released
    """
    world = _bank_with_chained_milestones()
    predecessor_id = world["milestones"]["INSTRUMENT_EXECUTION"]["id"]
    successor_id = world["milestones"]["CONSTRUCTION_COMPLETE"]["id"]

    claim_milestone(world, predecessor_id)
    approve_release(world, predecessor_id)
    claim_milestone(world, successor_id)

    releases = ledger_rows(world, entry_type="RELEASED")
    assert len(releases) == 1, (
        f"only the approved predecessor writes a RELEASED entry, got {len(releases)}"
    )
    assert_credits(releases[0]["delta_credits"], 14.82, "RELEASED delta_credits")
    assert releases[0]["source_id"] == predecessor_id, (
        "the single RELEASED entry belongs to the approved predecessor"
    )

    bank = bank_state(world)
    assert_credits(bank["credits_released"], 14.82, "credits_released")
    assert_credits(bank["credits_available"], 14.82, "credits_available")
