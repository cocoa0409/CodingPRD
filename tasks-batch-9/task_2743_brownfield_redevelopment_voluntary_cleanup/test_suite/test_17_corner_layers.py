"""
The three cross-cutting layers: two optimistic-concurrency guards and the ops-run checkpoint.

Both guarded creates are legitimate business supersessions, so no state precondition can tell
an intentional replacement from a client working off a stale view — only the expected parent
version can. The third layer is temporal rather than concurrent: an inquiry's expiry date
passing does nothing at all on its own; the compliance sweep is the only channel that converts
an expiry into a state change, and it does so exactly once.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    ERR_STALE_ENROLLMENT_VERSION,
    ERR_STALE_PLAN_VERSION,
    add_enrollment,
    assert_fields,
    assert_pagination_meta,
    assert_sweep_counters,
    decide_eligibility,
    plan_payload,
    policy_payload,
    run_sweep,
    set_clock,
    stage_approved,
    stage_assessed,
    stage_goals,
    stage_inquiry,
    stage_phase_i,
    stage_protection,
    stage_registry,
    stage_site,
)

# ─── occ_stale_enrollment_version_blocks_the_plan_create ───────────────────────────

DESIGN_TOTAL_CENTS = 115210677
STALE_VIEW_NARRATIVE = (
    "Excavation, groundwater treatment and vapour mitigation filed against a stale "
    "enrollment view."
)


def _an_enrollment_accepted_after_its_version_was_read(api):
    """Return a world plus the enrollment version as it stood before the decision."""
    world = stage_assessed(api)
    stage_goals(world)
    world.enrollment = add_enrollment(world)
    assert_fields(world.enrollment, status="ELIGIBILITY_REVIEW")
    version_before_the_decision = world.enrollment["version"]

    world.enrollment = decide_eligibility(world, world.enrollment, "ENROLL")
    assert_fields(
        world.enrollment, status="ENROLLED", version=version_before_the_decision + 1
    )
    world.enrollment_version = world.enrollment["version"]
    return world, version_before_the_decision


def _plan_body(world, expected_version):
    """The same remedy body, differing only in the enrollment version it claims to hold."""
    return plan_payload(
        world.enrollment["id"],
        world.site["id"],
        world.phase_ii["id"],
        expected_version,
        remedy_narrative=STALE_VIEW_NARRATIVE,
    )


def test_a_plan_filed_against_the_pre_decision_version_is_refused(api):
    """
    The eligibility decision moved the enrollment on, and the filing client had not noticed.

    "If that value does not equal the enrollment's current `version`, the create is rejected with
    `ERR_STALE_ENROLLMENT_VERSION` (HTTP 412)."

    Design: Corner/cross-cutting complexity layers/occ_stale_enrollment_version_blocks_the_plan_create
    """
    world, version_before_the_decision = _an_enrollment_accepted_after_its_version_was_read(
        api
    )

    refused = api.create_plan(
        _plan_body(world, version_before_the_decision), world.consult_headers
    )
    validate_error(refused, ERR_STALE_ENROLLMENT_VERSION, 412)

    plans, meta = validate_paginated(
        api.list_plans(world.consult_headers, vcp_enrollment_id=world.enrollment["id"])
    )
    assert plans == [], f"the refused create persisted a plan: {plans}"
    assert_pagination_meta(meta, expected_total=0)

    assert_fields(
        world.read_enrollment(),
        status="ENROLLED",
        version=version_before_the_decision + 1,
    )


def test_the_identical_body_carrying_the_current_version_is_accepted(api):
    """
    Nothing about the remedy changed; only the version the client claims to have seen.

    "Filing immediately runs the design-basis estimate of §3.6, writing `direct_cost_cents`,
    `escalation_cents`, `contingency_pct`, `contingency_cents`, `oversight_cents` and
    `total_estimate_cents`, and setting `total_funding_need_cents` equal to `total_estimate_cents`
    — no insurance premium has been placed yet."

    Design: Corner/cross-cutting complexity layers/occ_stale_enrollment_version_blocks_the_plan_create
    """
    world, version_before_the_decision = _an_enrollment_accepted_after_its_version_was_read(
        api
    )
    validate_error(
        api.create_plan(
            _plan_body(world, version_before_the_decision), world.consult_headers
        ),
        ERR_STALE_ENROLLMENT_VERSION,
        412,
    )

    filed = get_success_data(
        api.create_plan(
            _plan_body(world, world.enrollment["version"]), world.consult_headers
        ),
        201,
    )
    assert_fields(
        filed,
        status="DRAFT",
        total_estimate_cents=DESIGN_TOTAL_CENTS,
        total_funding_need_cents=DESIGN_TOTAL_CENTS,
    )


# ─── occ_stale_plan_version_blocks_the_cost_cap_quote ──────────────────────────────

UNDERWRITING_ESTIMATE_CENTS = 139803445
FIRST_QUOTE_REFERENCE = "CCP-2743-FIRST"
STALE_QUOTE_REFERENCE = "CCP-2743-STALE"
FRESH_QUOTE_REFERENCE = "CCP-2743-FRESH"


def _quote_body(world, policy_reference, expected_version):
    """The same placement request, differing only in the plan version it claims to hold."""
    return policy_payload(
        world.plan["id"],
        world.insurer["id"],
        expected_version,
        policy_reference=policy_reference,
    )


def _a_plan_whose_version_moved_under_the_carrier(api):
    """Quote once against the approved remedy; the accepted quote itself moves the plan on."""
    world = stage_approved(api)
    version_the_carrier_priced_against = world.plan["version"]
    world.policy = get_success_data(
        api.quote_policy(
            _quote_body(
                world, FIRST_QUOTE_REFERENCE, version_the_carrier_priced_against
            ),
            world.insurer_headers,
        ),
        201,
    )
    return world, version_the_carrier_priced_against


def test_a_re_quote_carrying_the_version_the_first_quote_consumed_is_refused(api):
    """
    The carrier's own accepted quote is what invalidated the version it was holding.

    "The plan's `version` increments by 1 as well, which is precisely why the next quote needs a
    refreshed `expected_remedial_action_plan_version`."

    Design: Corner/cross-cutting complexity layers/occ_stale_plan_version_blocks_the_cost_cap_quote
    """
    world, priced_against = _a_plan_whose_version_moved_under_the_carrier(api)
    assert_fields(world.read_plan(), version=priced_against + 1)

    refused = api.quote_policy(
        _quote_body(world, STALE_QUOTE_REFERENCE, priced_against), world.insurer_headers
    )
    validate_error(refused, ERR_STALE_PLAN_VERSION, 412)

    policies, meta = validate_paginated(
        api.list_policies(
            world.insurer_headers, remedial_action_plan_id=world.plan["id"]
        )
    )
    assert len(policies) == 1, f"the refused quote persisted a policy: {policies}"
    assert_pagination_meta(meta, expected_total=1)
    assert_fields(world.read_policy(), status="QUOTED", bound_at=None)


def test_the_refreshed_version_prices_the_underwriting_basis(api):
    """
    Re-reading the plan is all the carrier needed; the placement itself is unchanged.

    "Quoting runs the underwriting-basis estimate over the plan's `cost_lines` and its basis
    assessment phase, then derives the placement in a strictly pinned order."

    Design: Corner/cross-cutting complexity layers/occ_stale_plan_version_blocks_the_cost_cap_quote
    """
    world, priced_against = _a_plan_whose_version_moved_under_the_carrier(api)
    validate_error(
        api.quote_policy(
            _quote_body(world, STALE_QUOTE_REFERENCE, priced_against),
            world.insurer_headers,
        ),
        ERR_STALE_PLAN_VERSION,
        412,
    )

    fresh = get_success_data(
        api.quote_policy(
            _quote_body(
                world, FRESH_QUOTE_REFERENCE, world.read_plan()["version"]
            ),
            world.insurer_headers,
        ),
        201,
    )
    assert_fields(
        fresh,
        status="QUOTED",
        bound_at=None,
        policy_reference=FRESH_QUOTE_REFERENCE,
        underwriting_estimate_cents=UNDERWRITING_ESTIMATE_CENTS,
    )


def test_the_accepted_re_quote_supersedes_the_first_and_leaves_the_need_alone(api):
    """
    Two quotes, one live: and neither premium has reached the funding need.

    "Any prior policy on the same plan whose `status` is `QUOTED` becomes `SUPERSEDED` with its
    `version` incremented by 1 — a superseded quote's premium never enters the plan's funding
    need, since only bound premiums do."

    Design: Corner/cross-cutting complexity layers/occ_stale_plan_version_blocks_the_cost_cap_quote
    """
    world, _priced_against = _a_plan_whose_version_moved_under_the_carrier(api)
    first_policy = world.policy

    get_success_data(
        api.quote_policy(
            _quote_body(
                world, FRESH_QUOTE_REFERENCE, world.read_plan()["version"]
            ),
            world.insurer_headers,
        ),
        201,
    )

    superseded = get_success_data(
        api.get_policy(first_policy["id"], world.insurer_headers)
    )
    assert_fields(
        superseded, status="SUPERSEDED", version=first_policy["version"] + 1
    )
    assert_fields(world.read_plan(), total_funding_need_cents=DESIGN_TOTAL_CENTS)


# ─── ops_run_checkpoint_is_the_only_channel_that_stales_an_inquiry ─────────────────

TANNERY_PARCEL = {
    "site_name": "Cuyahoga Tannery Parcel",
    "county_code": "OH-035",
    "acreage": 3.75,
    "intended_reuse": "RESIDENTIAL",
    "planned_acquisition_date": "2026-11-01",
    "institutional_control_committed": False,
}
RECORDS_REVIEW_DATES = {
    "field_start_date": "2026-06-05",
    "field_end_date": "2026-07-12",
    "aai_report_date": "2026-07-20",
}
AAI_EXPIRES_ON = "2027-07-20"
DAY_AFTER_EXPIRY = "2027-07-21"
DAY_AFTER_EXPIRY_CLOCK = "2027-07-21T00:00:00Z"
TWO_DAYS_AFTER_EXPIRY = "2027-07-22"


def _an_expired_inquiry_on_a_deal_that_never_closed(api):
    """A parcel still under contract whose accepted inquiry aged past its year."""
    world = stage_registry(api)
    stage_site(world, **TANNERY_PARCEL)
    stage_protection(world)
    stage_phase_i(world, **RECORDS_REVIEW_DATES)
    stage_inquiry(world)
    set_clock(api, DAY_AFTER_EXPIRY_CLOCK)
    return world


def test_the_expiry_date_alone_stales_nothing_until_the_sweep_runs(api):
    """
    The clock is already past the expiry, and the dimension has not moved.

    "A protection whose `inquiry_state` is `AAI_COMPLETE` moves to `AAI_STALE` when the sweep's
    `as_of_date` is strictly later than `aai_expires_on` **and** the parcel is still
    `UNDER_CONTRACT` — an inquiry that has aged past a year while the deal has not closed no
    longer supports the defence."

    Design: Corner/cross-cutting complexity layers/ops_run_checkpoint_is_the_only_channel_that_stales_an_inquiry
    """
    world = _an_expired_inquiry_on_a_deal_that_never_closed(api)
    before = world.read_protection()
    assert_fields(
        before,
        inquiry_state="AAI_COMPLETE",
        aai_report_date="2026-07-20",
        aai_expires_on=AAI_EXPIRES_ON,
    )
    assert_fields(world.read_site(), acquisition_status="UNDER_CONTRACT")

    result = run_sweep(world, DAY_AFTER_EXPIRY, site_id=world.site["id"])
    assert_sweep_counters(
        result,
        stale_inquiry_count=1,
        lapsed_count=0,
        forfeited_protection_count=0,
        frozen_site_count=0,
    )

    assert_fields(
        world.read_protection(),
        inquiry_state="AAI_STALE",
        bfpp_status="NOT_ESTABLISHED",
        version=before["version"] + 1,
    )
    assert_fields(world.read_site(), acquisition_status="UNDER_CONTRACT")


def test_a_second_ops_run_finds_nothing_left_to_stale(api):
    """
    The counter reports work done, not work outstanding, so the second run is silent.

    "A protection whose `inquiry_state` is `AAI_COMPLETE` moves to `AAI_STALE` when the sweep's
    `as_of_date` is strictly later than `aai_expires_on` **and** the parcel is still
    `UNDER_CONTRACT` — an inquiry that has aged past a year while the deal has not closed no
    longer supports the defence."

    Design: Corner/cross-cutting complexity layers/ops_run_checkpoint_is_the_only_channel_that_stales_an_inquiry
    """
    world = _an_expired_inquiry_on_a_deal_that_never_closed(api)
    run_sweep(world, DAY_AFTER_EXPIRY, site_id=world.site["id"])
    once_staled = world.read_protection()

    again = run_sweep(world, TWO_DAYS_AFTER_EXPIRY, site_id=world.site["id"])
    assert_sweep_counters(again, stale_inquiry_count=0, forfeited_protection_count=0)

    assert_fields(
        world.read_protection(),
        inquiry_state="AAI_STALE",
        version=once_staled["version"],
    )
