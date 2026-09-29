"""
The endpoints themselves: what an edit rewrites, what a read exposes, what a filter narrows.

An edit to a draft remedy re-derives the whole cost chain rather than storing the new input
beside stale figures, and the same edit against an approved remedy is refused outright. The
funding assembly is a pure read over the waterfall. A control links two aggregates and both
must agree. Closure runs as two separate acts, one by the agency and one by the lender. And
the ops-run checkpoint honours the parcel it was pointed at.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    ERR_PLAN_NOT_EDITABLE,
    ERR_PLAN_SITE_MISMATCH,
    LENDER,
    REVIEWER_ALPHA,
    accept_letter,
    add_award,
    add_control,
    add_plan,
    add_site,
    add_tax_credit_award,
    assert_estimate_figures,
    assert_fields,
    assert_funding_conservation,
    assert_instant,
    assert_pagination_meta,
    assert_sweep_counters,
    continuing_obligation_payload,
    decide_award,
    ids_of,
    impose_obligation,
    issue_letter,
    liability_protection_payload,
    run_sweep,
    set_clock,
    site_control_payload,
    stage_approved,
    stage_completion_review,
    stage_enrolled,
    stage_implementation,
    stage_plan,
    stage_protection,
    stage_registry,
    stage_site,
)

# ─── patch_draft_plan_recomputes_every_design_cost_figure ────────────────────────

# The filed remedy, mobilising three years out.
AS_FILED = {
    "direct_cost_cents": 89787402,
    "escalation_cents": 11313213,
    "contingency_pct": "0.10",
    "contingency_cents": 10110062,
    "oversight_cents": 4000000,
    "total_cents": 115210677,
}

# The same six lines and the same basis phase, mobilising five years out instead.
AS_EDITED = {
    "direct_cost_cents": 89787402,
    "escalation_cents": 18855354,
    "contingency_pct": "0.10",
    "contingency_cents": 10864276,
    "oversight_cents": 4000000,
    "total_cents": 123507032,
}

EDITED_TOTAL_CENTS = 123507032
LATER_CONSTRUCTION_START = {"years_to_construction_start": 5}


def test_editing_the_construction_date_reruns_the_whole_design_chain(api):
    """
    The new input is not merely stored: escalation, contingency and the total all move.

    "An accepted edit immediately re-runs the design-basis estimate over the new inputs,
    rewriting all seven cost figures including `total_funding_need_cents`, and increments the
    plan's `version` by 1."

    Design: Corner/endpoints/patch_draft_plan_recomputes_every_design_cost_figure
    """
    world = stage_enrolled(api)
    stage_plan(world)
    assert_estimate_figures(world.plan, AS_FILED)
    assert_fields(world.plan, total_funding_need_cents=AS_FILED["total_cents"])

    patched = get_success_data(
        api.patch_plan(world.plan["id"], LATER_CONSTRUCTION_START, world.consult_headers)
    )
    assert_fields(
        patched,
        years_to_construction_start=5,
        total_funding_need_cents=EDITED_TOTAL_CENTS,
        version=world.plan["version"] + 1,
    )
    assert_estimate_figures(patched, AS_EDITED)


def test_the_edited_remedy_reads_back_with_the_recomputed_figures_and_no_pins(api):
    """
    The plan is still a draft afterwards, so it still carries no goal pins.

    "Plans can be listed with filters on `vcp_enrollment_id`, `site_id` and `status`, and read
    individually with every cost figure, both branch dimensions and the goal pins exposed."

    Design: Corner/endpoints/patch_draft_plan_recomputes_every_design_cost_figure
    """
    world = stage_enrolled(api)
    stage_plan(world)
    api.patch_plan(world.plan["id"], LATER_CONSTRUCTION_START, world.consult_headers)

    read_back = world.read_plan()
    assert_fields(
        read_back,
        status="DRAFT",
        years_to_construction_start=5,
        total_funding_need_cents=EDITED_TOTAL_CENTS,
        pinned_cleanup_goal_versions=[],
        technical_review_state="NOT_STARTED",
        public_comment_state="NOT_STARTED",
    )
    assert_estimate_figures(read_back, AS_EDITED)


# ─── patch_approved_plan_returns_plan_not_editable ───────────────────────────────


def test_the_approved_remedy_refuses_the_same_edit_and_keeps_its_figures(api):
    """
    Editability is a status gate, and approval closes it.

    "It is permitted only while the plan's `status` is `DRAFT` or `REVISION_REQUESTED`; an edit
    against any other status is refused with `ERR_PLAN_NOT_EDITABLE` (HTTP 409)."

    Design: Corner/endpoints/patch_approved_plan_returns_plan_not_editable
    """
    world = stage_approved(api)
    approved = world.read_plan()

    refused = api.patch_plan(
        world.plan["id"], LATER_CONSTRUCTION_START, world.consult_headers
    )
    validate_error(refused, ERR_PLAN_NOT_EDITABLE, 409)

    unchanged = world.read_plan()
    assert_fields(
        unchanged,
        status="APPROVED",
        years_to_construction_start=3,
        total_funding_need_cents=AS_FILED["total_cents"],
        version=approved["version"],
    )
    assert_estimate_figures(unchanged, AS_FILED)


# ─── funding_assembly_computed_read_matches_the_waterfall ────────────────────────

FUNDING_NEED_CENTS = 115210677

# Priority 1 takes 40 percent of the excavation and monitoring lines.
GRANT_ALLOCATION_CENTS = 23842210

# Priority 2 then takes the whole groundwater-treatment line out of what is left.
CREDIT_ALLOCATION_CENTS = 18610003

UNFUNDED_GAP_CENTS = 72758464

# 20 percent of the grant plus 5 percent of the credit, each rounded before summing.
LOCAL_MATCH_CENTS = 5698942

WIDE_TAX_CREDIT = {
    "max_share_pct": 1.00,
    "max_award_cents": 80000000,
    "match_requirement_pct": 0.05,
    "eligible_cost_categories": ["GW_TREATMENT"],
}


def _two_awarded_programmes(api):
    """An approved remedy funded by a priority-1 grant and a priority-2 tax credit."""
    world = stage_approved(api)
    grant = add_award(world)
    credit = add_tax_credit_award(world, **WIDE_TAX_CREDIT)
    decide_award(world, grant)
    decide_award(world, credit)
    return world, grant, credit


def test_the_assembly_read_pairs_each_programme_with_what_the_waterfall_left_it(api):
    """
    Two programmes stacked in priority order, with the residual gap and the local match.

    "The computed read exposes `site_id`, the `remedial_action_plan_id` of the approved plan,
    `total_funding_need_cents`, an `allocations` array whose entries each pair a
    `funding_award_id` with its `allocated_cents`, `unfunded_gap_cents` and
    `local_match_required_cents`."

    Design: Corner/endpoints/funding_assembly_computed_read_matches_the_waterfall
    """
    world, grant, credit = _two_awarded_programmes(api)

    assembly = get_success_data(api.get_funding_assembly(world.site["id"], LENDER))
    assert_fields(
        assembly,
        site_id=world.site["id"],
        remedial_action_plan_id=world.plan["id"],
        total_funding_need_cents=FUNDING_NEED_CENTS,
        unfunded_gap_cents=UNFUNDED_GAP_CENTS,
        local_match_required_cents=LOCAL_MATCH_CENTS,
    )
    awarded_order = [entry["funding_award_id"] for entry in assembly["allocations"]]
    assert awarded_order == [grant["id"], credit["id"]], (
        f"the allocations must run in priority order: {assembly['allocations']}"
    )
    assert_fields(assembly["allocations"][0], allocated_cents=GRANT_ALLOCATION_CENTS)
    assert_fields(assembly["allocations"][1], allocated_cents=CREDIT_ALLOCATION_CENTS)
    assert_funding_conservation(assembly)


def test_the_assembly_is_a_read_and_repeating_it_changes_nothing(api):
    """
    Nothing is stored on the way out: two reads agree and the plan is untouched.

    "The allocation is a strict priority waterfall against a single need figure, and it is
    also exposed as a computed read on the parcel."

    Design: Corner/endpoints/funding_assembly_computed_read_matches_the_waterfall
    """
    world, _grant, _credit = _two_awarded_programmes(api)
    plan_before = world.read_plan()

    first = get_success_data(api.get_funding_assembly(world.site["id"], LENDER))
    second = get_success_data(api.get_funding_assembly(world.site["id"], LENDER))
    assert first == second, (
        f"the computed read must be free of side effects: {first} then {second}"
    )

    assert_fields(
        world.read_plan(),
        version=plan_before["version"],
        total_funding_need_cents=FUNDING_NEED_CENTS,
    )


# ─── site_control_must_link_a_plan_on_the_same_site ──────────────────────────────

SECOND_PARCEL = {
    "site_name": "Cuyahoga Tannery Parcel",
    "county_code": "OH-035",
    "acreage": 3.75,
    "intended_reuse": "RESIDENTIAL",
    "planned_acquisition_date": "2026-11-01",
}


def test_a_control_naming_one_parcel_and_another_parcels_plan_is_refused(api):
    """
    The two references must agree before any control is written.

    "An `EnvironmentalConsultant` proposes one against a plan, supplying `site_id`,
    `remedial_action_plan_id` (which must name a plan on the same parcel, else
    `ERR_PLAN_SITE_MISMATCH`)"

    Design: Corner/endpoints/site_control_must_link_a_plan_on_the_same_site
    """
    world = stage_enrolled(api)
    plan = add_plan(world)
    other_parcel = add_site(world, **SECOND_PARCEL)

    refused = api.create_site_control(
        site_control_payload(other_parcel["id"], plan["id"]), world.consult_headers
    )
    validate_error(refused, ERR_PLAN_SITE_MISMATCH, 422)

    _rows, meta = validate_paginated(
        api.list_site_controls(world.consult_headers, site_id=other_parcel["id"])
    )
    assert meta["total_count"] == 0, (
        f"the refused control must not have been written: {meta}"
    )


def test_the_coherent_pairing_is_accepted_and_derives_its_control_class(api):
    """
    Named against its own parcel's plan, the same control is admitted.

    "`control_type` is one of `VAPOR_MITIGATION`, `ENGINEERED_CAP`, `GW_USE_RESTRICTION` or
    `DEED_RESTRICTION`, and from it the server derives `control_class`: `ENGINEERING` for
    `VAPOR_MITIGATION` and `ENGINEERED_CAP`, `INSTITUTIONAL` for `GW_USE_RESTRICTION` and
    `DEED_RESTRICTION`."

    Design: Corner/endpoints/site_control_must_link_a_plan_on_the_same_site
    """
    world = stage_enrolled(api)
    plan = add_plan(world)
    add_site(world, **SECOND_PARCEL)

    control = add_control(world, plan)
    assert_fields(
        control,
        site_id=world.site["id"],
        remedial_action_plan_id=plan["id"],
        control_type="VAPOR_MITIGATION",
        control_class="ENGINEERING",
        status="PROPOSED",
    )


# ─── letter_issue_and_lender_acceptance_close_the_enrollment ─────────────────────

ISSUANCE_DATE = "2027-06-01"
COMPLETION_REQUEST_INSTANT = "2027-06-01T00:00:00Z"
LOAN_FILE_REFERENCE = "LOAN-2743-CRE-118"


def _a_letter_awaiting_issuance(api):
    """A parcel in completion review with one operating control and a drafted letter."""
    world = stage_implementation(api)
    stage_completion_review(world)
    return world


def test_issuing_the_letter_counts_the_operating_controls_and_closes_the_enrollment(api):
    """
    The agency's act dates itself from the clock and shuts the enrollment behind it.

    "Issuance moves the letter `DRAFT → ISSUED`, sets `issued_on` from the logical clock's
    date, records `issued_by_user_id`, and stores `controls_certified_count` as the number of
    site controls on the parcel whose `status` is `OPERATING` at that instant."

    Design: Corner/endpoints/letter_issue_and_lender_acceptance_close_the_enrollment
    """
    world = _a_letter_awaiting_issuance(api)

    issued = issue_letter(world)
    assert_fields(
        issued,
        status="ISSUED",
        issued_on=ISSUANCE_DATE,
        issued_by_user_id="reviewer-beta",
        controls_certified_count=1,
        reissue_count=0,
        revocation_reason=None,
        accepted_by_lender_user_id=None,
    )

    enrollment = world.read_enrollment()
    assert_fields(enrollment, status="CLOSED")
    assert_instant(
        enrollment["completion_requested_at"],
        COMPLETION_REQUEST_INSTANT,
        "completion_requested_at",
    )


def test_the_lenders_reliance_is_recorded_without_moving_the_enrollment_again(api):
    """
    A second, separate act by a different party: the enrollment is already closed.

    "Acceptance stores `accepted_by_lender_user_id` from the acting `X-User-ID` along with
    `lender_reference`, moves the letter `ISSUED → ACCEPTED_BY_LENDER`, and increments its
    `version` by 1."

    Design: Corner/endpoints/letter_issue_and_lender_acceptance_close_the_enrollment
    """
    world = _a_letter_awaiting_issuance(api)
    world.letter = issue_letter(world)
    closed = world.read_enrollment()

    accepted = accept_letter(world, lender_reference=LOAN_FILE_REFERENCE)
    assert_fields(
        accepted,
        status="ACCEPTED_BY_LENDER",
        accepted_by_lender_user_id="lender-1",
        lender_reference=LOAN_FILE_REFERENCE,
        issued_by_user_id="reviewer-beta",
        controls_certified_count=1,
        version=world.letter["version"] + 1,
    )

    assert_fields(world.read_enrollment(), status="CLOSED", version=closed["version"])


# ─── compliance_sweep_scopes_its_ops_run_to_the_named_site ───────────────────────

SHARED_DUE_DATE = "2027-03-01"
ONE_DAY_LATE = "2027-03-02"
ONE_DAY_LATE_CLOCK = "2027-03-02T00:00:00Z"
FIRST_DUTY_DESCRIPTION = "Maintain fencing, signage and stormwater controls."
SECOND_DUTY_DESCRIPTION = "Honour the residential-use covenant."


def _two_parcels_each_one_day_overdue(api):
    """Two parcels, each with a single defence-critical duty that fell due yesterday."""
    world = stage_registry(api)
    stage_site(world)
    stage_protection(world)
    first_duty = impose_obligation(
        world,
        obligation_category="REASONABLE_STEPS",
        description=FIRST_DUTY_DESCRIPTION,
        due_date=SHARED_DUE_DATE,
        recurrence_days=90,
    )

    other_parcel = add_site(
        world, institutional_control_committed=False, **SECOND_PARCEL
    )
    other_protection = get_success_data(
        api.create_liability_protection(
            liability_protection_payload(other_parcel["id"]), world.redev_headers
        ),
        201,
    )
    second_duty = get_success_data(
        api.impose_continuing_obligation(
            other_protection["id"],
            continuing_obligation_payload(
                obligation_category="LAND_USE_RESTRICTION_COMPLIANCE",
                description=SECOND_DUTY_DESCRIPTION,
                due_date=SHARED_DUE_DATE,
                recurrence_days=180,
            ),
            REVIEWER_ALPHA,
        ),
        201,
    )

    set_clock(api, ONE_DAY_LATE_CLOCK)
    return world, first_duty, other_parcel, other_protection, second_duty


def test_the_scoped_run_lapses_one_parcels_duty_and_leaves_the_other_alone(api):
    """
    Both duties are equally overdue; only the named parcel's is examined.

    "The sweep takes an `as_of_date` and an optional `site_id` to narrow it to one parcel, and
    it is one of the three operations that runs even on a `FROZEN` parcel — indeed running it
    on frozen parcels is the point, since forfeiture is exactly what it detects."

    Design: Corner/endpoints/compliance_sweep_scopes_its_ops_run_to_the_named_site
    """
    world, first_duty, other_parcel, _other_protection, second_duty = (
        _two_parcels_each_one_day_overdue(api)
    )

    result = run_sweep(world, ONE_DAY_LATE, site_id=world.site["id"])
    assert_sweep_counters(result, lapsed_count=1, frozen_site_count=1)

    assert_fields(world.read_obligation(first_duty), status="LAPSED")
    assert_fields(world.read_site(), cleanup_posture="FROZEN")

    untouched = get_success_data(
        api.get_continuing_obligation(second_duty["id"], REVIEWER_ALPHA)
    )
    assert_fields(untouched, status="CURRENT")
    assert_fields(
        get_success_data(api.get_site(other_parcel["id"], world.redev_headers)),
        cleanup_posture="OPEN",
    )


def test_the_unscoped_run_afterwards_reaches_only_what_is_left_to_reach(api):
    """
    The second parcel forfeits on its own lapse; the first is already terminal.

    "Two of them — `REASONABLE_STEPS` and `LAND_USE_RESTRICTION_COMPLIANCE` — are
    **defence-critical**: if either lapses, the defence is forfeited outright."

    Design: Corner/endpoints/compliance_sweep_scopes_its_ops_run_to_the_named_site
    """
    world, _first_duty, other_parcel, other_protection, second_duty = (
        _two_parcels_each_one_day_overdue(api)
    )
    run_sweep(world, ONE_DAY_LATE, site_id=world.site["id"])

    result = run_sweep(world, ONE_DAY_LATE)
    assert_sweep_counters(result, lapsed_count=1, frozen_site_count=1)

    assert_fields(
        get_success_data(api.get_continuing_obligation(second_duty["id"], REVIEWER_ALPHA)),
        status="LAPSED",
    )
    assert_fields(
        get_success_data(
            api.get_liability_protection(other_protection["id"], world.redev_headers)
        ),
        bfpp_status="FORFEITED",
    )
    assert_fields(
        get_success_data(api.get_site(other_parcel["id"], world.redev_headers)),
        cleanup_posture="FROZEN",
    )


# ─── list_site_controls_filters_by_class_status_and_pagination ───────────────────

DEED_CONTROL = {
    "control_type": "DEED_RESTRICTION",
    "sub_area_code": "PARCEL-WIDE",
    "inspection_interval_days": 365,
}
DEED_NEXT_CERTIFICATION_DUE_ON = "2028-01-01"


def _one_engineering_and_one_institutional_control(api):
    """A draft remedy carrying a vapour barrier and a parcel-wide deed restriction."""
    world = stage_enrolled(api)
    plan = add_plan(world)
    barrier = add_control(world, plan)
    deed = add_control(world, plan, **DEED_CONTROL)
    return world, barrier, deed


def test_the_deed_restriction_derives_its_class_and_its_first_inspection_date(api):
    """
    A yearly inspection interval pushes the first due date a year past the coverage start.

    "A newly proposed control sits in `PROPOSED` with `impairment_count` zero,
    `last_certified_on` null, `impaired_since` null, and `next_certification_due_on` derived as
    `coverage_from` advanced by `inspection_interval_days`."

    Design: Corner/endpoints/list_site_controls_filters_by_class_status_and_pagination
    """
    _world, _barrier, deed = _one_engineering_and_one_institutional_control(api)

    assert_fields(
        deed,
        control_class="INSTITUTIONAL",
        status="PROPOSED",
        next_certification_due_on=DEED_NEXT_CERTIFICATION_DUE_ON,
        impairment_count=0,
        last_certified_on=None,
        impaired_since=None,
    )


def test_the_control_listing_separates_the_two_classes_and_pages_through_them(api):
    """
    Each declared filter narrows the parcel's two controls, and a page of one splits them.

    "Controls can be listed with filters on `site_id`, `remedial_action_plan_id`,
    `sub_area_code`, `status` and `control_class`, and read individually with their coverage
    interval and impairment counters."

    Design: Corner/endpoints/list_site_controls_filters_by_class_status_and_pagination
    """
    world, barrier, deed = _one_engineering_and_one_institutional_control(api)
    parcel = world.site["id"]

    rows, meta = validate_paginated(
        api.list_site_controls(REVIEWER_ALPHA, site_id=parcel)
    )
    assert sorted(ids_of(rows)) == sorted([barrier["id"], deed["id"]]), (
        f"the parcel's own controls must both be listed: {ids_of(rows)}"
    )
    assert_pagination_meta(
        meta,
        expected_total=2,
        expected_limit=10,
        expected_offset=0,
        expected_has_more=False,
    )

    institutional, _meta = validate_paginated(
        api.list_site_controls(
            REVIEWER_ALPHA, site_id=parcel, control_class="INSTITUTIONAL"
        )
    )
    assert ids_of(institutional) == [deed["id"]], (
        f"only the deed restriction is institutional: {ids_of(institutional)}"
    )

    engineering, _meta = validate_paginated(
        api.list_site_controls(
            REVIEWER_ALPHA, site_id=parcel, control_class="ENGINEERING"
        )
    )
    assert ids_of(engineering) == [barrier["id"]], (
        f"only the vapour barrier is engineering: {ids_of(engineering)}"
    )

    first_page, first_meta = validate_paginated(
        api.list_site_controls(
            REVIEWER_ALPHA, site_id=parcel, status="PROPOSED", limit=1, offset=0
        )
    )
    assert_pagination_meta(
        first_meta,
        expected_total=2,
        expected_limit=1,
        expected_offset=0,
        expected_has_more=True,
    )

    second_page, second_meta = validate_paginated(
        api.list_site_controls(
            REVIEWER_ALPHA, site_id=parcel, status="PROPOSED", limit=1, offset=1
        )
    )
    assert_pagination_meta(
        second_meta,
        expected_total=2,
        expected_limit=1,
        expected_offset=1,
        expected_has_more=False,
    )
    assert not set(ids_of(first_page)) & set(ids_of(second_page)), (
        f"the two pages must be disjoint: {ids_of(first_page)} and {ids_of(second_page)}"
    )
    assert sorted(ids_of(first_page) + ids_of(second_page)) == sorted(
        [barrier["id"], deed["id"]]
    ), "the two pages together must be the whole result set"
