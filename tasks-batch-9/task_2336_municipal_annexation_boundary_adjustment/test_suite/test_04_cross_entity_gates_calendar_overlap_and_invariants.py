"""Procedural gates that read another record's state, calendar contention for
the council chamber and for a provider's crew, and the ledgers an unwinding act
must restore exactly.

Three themes run through this file. First, several statutory acts on an
annexation case are admissible only while a *different* record sits in the right
state: notice publication needs an `ADOPTED` plan of services, ordinance
adoption needs a `FINALIZED` fiscal impact analysis, and plan adoption needs its
service commitments out of `DRAFT`. Second, the council chamber and a service
provider's calendar use opposite interval conventions — the chamber compares
buffered instants strictly, while a commitment occupies both endpoint days of
its window. Third, withdrawing a signature, voiding a commitment and unwinding
an annexation are compensating acts, and each must return the running total it
touched to exactly the value it had before.
"""
from datetime import datetime

from test_helpers import (
    FISCAL_ANALYST_USER_ID,
    assertions,
    constants,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers.api_errors import (
    ERR_FISCAL_ANALYSIS_NOT_FINALIZED,
    ERR_HEARING_SLOT_CONFLICT,
    ERR_PLAN_NOT_ADOPTED,
    ERR_PROVIDER_CAPACITY_EXCEEDED,
    ERR_SERVICE_TYPE_NOT_COVERED,
)

# The territory every case in this file assembles: four fully developed lots of
# five acres each, sharing 20000 of the city's 80000 feet of corporate
# boundary, which saturates the contiguity ramp and certifies at index 100.00.
_PARCEL_COUNT = 4

# A police commitment window well inside the statutory 60-day ceiling.
_AUGUST_WINDOW = ("2026-08-01", "2026-08-31")
# A window that begins on the day the August window ends, so the two share that
# single calendar day.
_TOUCHING_WINDOW = ("2026-08-31", "2026-09-30")
# A window that begins the day after, so the two share no day at all.
_SEPTEMBER_WINDOW = ("2026-09-01", "2026-09-30")


def _instant(value):
    """ISO 8601 UTC readings may or may not carry fractional digits, so compare
    parsed instants rather than strings."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _certified_case_with_draft_plan(api, service_types, **overrides):
    """A certified case whose plan of services is still `DRAFT`, carrying one
    commitment per named service type in whatever state the caller leaves it."""
    ctx = fixtures.setup_certified_case(
        api,
        statute={"required_service_types": list(service_types)},
        **overrides,
    )
    fixtures.open_plan(api, ctx)
    return ctx


def _second_certified_case(api, ctx):
    """A second certified case in the same city, so that its hearing competes
    for the one council chamber that city has."""
    municipality_id = ctx["municipality"]["id"]
    case = fixtures.create_case(api, municipality_id)
    for _ in range(_PARCEL_COUNT):
        owner = fixtures.create_owner(api)
        fixtures.add_parcel(api, municipality_id, case["id"], owner["id"])
    return get_success_data(api.certify_territory(fixtures.planner(ctx), case["id"]))


# ==========================================================================
# Publishing statutory notice reads the plan of services' adoption state
# ==========================================================================
def test_notice_publication_refused_while_the_plan_of_services_is_still_draft(api):
    """PRD §3.6: "The hearing must still be `SCHEDULED`, or
    `ERR_HEARING_NOT_SCHEDULED` is returned, and the case must have an
    `ADOPTED` plan of services, or `ERR_PLAN_NOT_ADOPTED`."

    Design: Difficulty/cross_entity_state_dependency/notice_publication_gated_on_plan_of_services_adoption_state
    """
    ctx = _certified_case_with_draft_plan(api, ["POLICE"])
    commitment = fixtures.add_commitment(
        api, ctx, "POLICE", cost_cents=500000, committed_account_count=0
    )
    fixtures.activate_commitment(api, ctx, commitment["id"])
    fixtures.schedule_hearing(api, ctx)

    # The hearing is SCHEDULED and the case is in a valid origin state, so the
    # only thing standing in the way is the plan's own adoption_status.
    validate_error(
        api.publish_notice(fixtures.clerk(ctx), ctx["hearing"]["id"], "NEWSPAPER"),
        ERR_PLAN_NOT_ADOPTED,
    )

    plan = fixtures.read_plan(api, ctx["municipality"]["id"], ctx["plan"]["id"])
    assert plan["adoption_status"] == "DRAFT"
    hearing = fixtures.read_hearing(api, ctx["municipality"]["id"], ctx["hearing"]["id"])
    assert hearing["notice_published_at"] is None
    assert fixtures.read_case(api, ctx["municipality"]["id"], ctx["case"]["id"])[
        "status"
    ] == "TERRITORY_CERTIFIED"


def test_adopting_the_plan_lets_the_identical_notice_publication_advance_the_case(api):
    """PRD §3.6: "The notice is created with `notice_status` `PUBLISHED` and
    `published_at` set to the logical clock, and the hearing's
    `notice_published_at` is set to that instant." "The case advances to
    `HEARING_NOTICED` and its `version` increments — from `SUFFICIENCY_REVIEW`
    on the petition path, and directly from `TERRITORY_CERTIFIED` when the
    case's `method` is `REFERENDUM` or `INVOLUNTARY_ORDINANCE`, since those two
    methods skip the petition limb entirely and never pass through
    `SUFFICIENCY_REVIEW` at all."

    Design: Difficulty/cross_entity_state_dependency/notice_publication_gated_on_plan_of_services_adoption_state
    """
    ctx = _certified_case_with_draft_plan(api, ["POLICE"])
    commitment = fixtures.add_commitment(
        api, ctx, "POLICE", cost_cents=500000, committed_account_count=0
    )
    fixtures.activate_commitment(api, ctx, commitment["id"])
    fixtures.schedule_hearing(api, ctx)

    # Nothing about the case or the hearing changes here — only the plan moves.
    plan = get_success_data(
        api.adopt_plan_of_services(fixtures.clerk(ctx), ctx["plan"]["id"])
    )
    assert plan["adoption_status"] == "ADOPTED"

    notice = get_success_data(
        api.publish_notice(fixtures.clerk(ctx), ctx["hearing"]["id"], "NEWSPAPER"), 201
    )
    assert notice["notice_status"] == "PUBLISHED"
    assert _instant(notice["published_at"]) == _instant(constants.CLOCK_STARTUP_UTC)

    hearing = fixtures.read_hearing(api, ctx["municipality"]["id"], ctx["hearing"]["id"])
    assert _instant(hearing["notice_published_at"]) == _instant(notice["published_at"])
    assert hearing["hearing_status"] == "SCHEDULED"

    case = fixtures.read_case(api, ctx["municipality"]["id"], ctx["case"]["id"])
    assert case["status"] == "HEARING_NOTICED"

    notices, meta = validate_paginated(
        api.list_hearing_notices(fixtures.clerk(ctx), ctx["hearing"]["id"])
    )
    assert meta["total_count"] == 1
    assert notices[0]["id"] == notice["id"]


# ==========================================================================
# Ordinance adoption reads the fiscal impact analysis' status
# ==========================================================================
def _case_ready_but_analysis_still_draft(api):
    """The full ladder to an adoptable case — protest closed `FAILED`, plan
    `ADOPTED`, cooling-off period elapsed — with the analysis left in `DRAFT`."""
    ctx = fixtures.setup_certified_case(api)
    fixtures.setup_adopted_plan(api, ctx)
    fixtures.setup_hearing_noticed(api, ctx)
    fixtures.setup_hearing_held(api, ctx)
    fixtures.close_protest_period(api, ctx)
    fixtures.author_analysis(api, ctx)
    return ctx


def test_ordinance_adoption_refused_while_the_analysis_of_record_is_still_draft(api):
    """PRD §3.7: "The case must have an `ADOPTED` plan of services
    (`ERR_PLAN_NOT_ADOPTED`) and a `FINALIZED` fiscal impact analysis
    (`ERR_FISCAL_ANALYSIS_NOT_FINALIZED`), that analysis's `deficit_ratio_pct`
    must be no greater than the municipality's `fiscal_deficit_tolerance_pct` —
    equality is tolerated, anything above it is refused with
    `ERR_FISCAL_DEFICIT_EXCEEDS_TOLERANCE` — and the case's `method` must still
    appear in the statute's `authorized_methods`
    (`ERR_METHOD_NOT_AUTHORIZED_BY_STATUTE`)."

    Design: Difficulty/cross_entity_state_dependency/ordinance_adoption_gated_on_fiscal_analysis_finalized_state
    """
    ctx = _case_ready_but_analysis_still_draft(api)
    assert ctx["case"]["protest_outcome"] == "FAILED"
    assert ctx["analysis"]["status"] == "DRAFT"
    # A surplus analysis, so the deficit tolerance is not what refuses this.
    assert assertions.approx_equal(ctx["analysis"]["deficit_ratio_pct"], 0)

    validate_error(
        api.adopt_ordinance(fixtures.clerk(ctx), ctx["case"]["id"]),
        ERR_FISCAL_ANALYSIS_NOT_FINALIZED,
    )

    case = fixtures.read_case(api, ctx["municipality"]["id"], ctx["case"]["id"])
    assert case["status"] == "HEARING_HELD"
    assert case["ordinance_adopted_at"] is None
    assert case["fiscal_finalized_by_user_id"] is None


def test_finalizing_the_analysis_lets_the_identical_adoption_call_succeed(api):
    """PRD §3.4: "Finalization moves `status` to `FINALIZED`, writes the acting
    analyst's `X-User-ID` into `finalized_by_user_id` on the analysis and
    mirrors it into `fiscal_finalized_by_user_id` on the case, and increments
    the case's `version`." PRD §3.7: "When the case's `method` is **not** among
    the methods requiring ratification, the case advances `HEARING_HELD →
    ORDINANCE_ADOPTED`, and its `commission_review_status` becomes `PENDING` if
    the statute's `boundary_commission_required` is true and stays
    `NOT_REQUIRED` otherwise."

    Design: Difficulty/cross_entity_state_dependency/ordinance_adoption_gated_on_fiscal_analysis_finalized_state
    """
    ctx = _case_ready_but_analysis_still_draft(api)

    analysis = fixtures.finalize_analysis(api, ctx)
    assert analysis["status"] == "FINALIZED"
    assert analysis["finalized_by_user_id"] == FISCAL_ANALYST_USER_ID

    case = get_success_data(api.adopt_ordinance(fixtures.clerk(ctx), ctx["case"]["id"]))
    assert case["status"] == "ORDINANCE_ADOPTED"
    # The clock last moved strictly past the protest close instant, and the
    # ordinance is stamped from that same reading.
    assert _instant(case["ordinance_adopted_at"]) == _instant(
        constants.CLOCK_AFTER_PROTEST_WINDOW
    )
    # The statute leaves boundary_commission_required at its false default.
    assert case["commission_review_status"] == "NOT_REQUIRED"
    assert case["fiscal_finalized_by_user_id"] == FISCAL_ANALYST_USER_ID


# ==========================================================================
# Plan adoption reads its commitments' activation state
# ==========================================================================
def test_plan_adoption_refused_while_its_only_commitment_is_still_draft(api):
    """PRD §3.5: "Consider only the plan's commitments in `ACTIVE` or
    `FULFILLED`; those in `DRAFT` or `VOIDED` contribute neither cost nor
    coverage." "It requires the plan to be in `DRAFT`, requires the owning case
    to be in one of `TERRITORY_CERTIFIED`, `PETITION_CIRCULATING`,
    `SUFFICIENCY_REVIEW`, `HEARING_NOTICED` or `HEARING_HELD`, requires that no
    other plan of the case is already `ADOPTED` (otherwise
    `ERR_PLAN_ALREADY_ADOPTED`), requires `covered_service_types` to contain
    every member of the statute's `required_service_types` (otherwise
    `ERR_SERVICE_TYPE_NOT_COVERED`), and re-checks that every commitment of the
    plan in `ACTIVE` or `FULFILLED` respects the statutory ceiling for its
    service type (otherwise `ERR_PLAN_SERVICE_TIMELINE_EXCEEDS_STATUTE`)."

    Design: Difficulty/cross_entity_state_dependency/plan_adoption_gated_on_commitment_activation_state
    """
    ctx = _certified_case_with_draft_plan(api, ["POLICE"])
    assert ctx["plan"]["service_readiness"] == "PENDING"

    commitment = fixtures.add_commitment(
        api, ctx, "POLICE", cost_cents=500000, committed_account_count=0
    )
    assert commitment["commitment_status"] == "DRAFT"

    plan = fixtures.read_plan(api, ctx["municipality"]["id"], ctx["plan"]["id"])
    assert plan["covered_service_types"] == []
    assert plan["committed_cost_cents"] == 0

    validate_error(
        api.adopt_plan_of_services(fixtures.clerk(ctx), ctx["plan"]["id"]),
        ERR_SERVICE_TYPE_NOT_COVERED,
    )

    plan = fixtures.read_plan(api, ctx["municipality"]["id"], ctx["plan"]["id"])
    assert plan["adoption_status"] == "DRAFT"
    assert plan["adopted_at"] is None


def test_activating_the_commitment_lets_the_identical_plan_adoption_succeed(api):
    """PRD §3.5: "Adoption is the clerk's act and moves `adoption_status` from
    `DRAFT` to `ADOPTED`, stamping `adopted_at` from the logical clock and
    incrementing the plan's `version`." "`service_readiness` is `PENDING` when
    that set of commitments is empty; it is `READY` when every member of the
    statute's `required_service_types` appears in `covered_service_types`
    **and** every one of those commitments is in `FULFILLED`; and it is
    `PARTIAL` in every other case."

    Design: Difficulty/cross_entity_state_dependency/plan_adoption_gated_on_commitment_activation_state
    """
    ctx = _certified_case_with_draft_plan(api, ["POLICE"])
    commitment = fixtures.add_commitment(
        api, ctx, "POLICE", cost_cents=500000, committed_account_count=0
    )

    # A write to the commitment, not to the plan: an unmetered commitment is
    # fulfilled in the same request that activates it.
    activated = fixtures.activate_commitment(api, ctx, commitment["id"])
    assert activated["commitment_status"] == "FULFILLED"

    plan = get_success_data(
        api.adopt_plan_of_services(fixtures.clerk(ctx), ctx["plan"]["id"])
    )
    assert plan["adoption_status"] == "ADOPTED"
    assert _instant(plan["adopted_at"]) == _instant(constants.CLOCK_STARTUP_UTC)
    assert plan["service_readiness"] == "READY"
    assert plan["committed_cost_cents"] == 500000
    assert plan["covered_service_types"] == assertions.ordered_service_types(["POLICE"])


# ==========================================================================
# The council chamber: buffered instants compared strictly
# ==========================================================================
def _chamber_contention_setup(api):
    """One city whose chamber already holds an 18:00–20:00 hearing, plus a
    second certified case wanting the same evening."""
    ctx = fixtures.setup_certified_case(
        api, municipality={"hearing_changeover_buffer_minutes": 30}
    )
    fixtures.schedule_hearing(
        api,
        ctx,
        scheduled_start_at="2026-09-10T18:00:00Z",
        scheduled_end_at="2026-09-10T20:00:00Z",
    )
    return ctx, _second_certified_case(api, ctx)


def test_hearing_starting_exactly_at_the_peers_end_plus_buffer_is_admitted(api):
    """PRD §3.6: "Each occupation is extended by a trailing changeover buffer
    equal to the municipality's `hearing_changeover_buffer_minutes`." "Because
    both comparisons are strict, a candidate starting exactly at a peer's end
    plus the buffer is admitted."

    Design: Difficulty/resource_temporal_overlap/chamber_buffered_half_open_interval_admits_exact_touch_only
    """
    ctx, second_case = _chamber_contention_setup(api)

    # 20:00 end plus the 30-minute changeover buffer lands exactly on 20:30.
    payload = factories.public_hearing_payload(
        second_case["id"],
        ctx["municipality"]["id"],
        scheduled_start_at="2026-09-10T20:30:00Z",
        scheduled_end_at="2026-09-10T21:15:00Z",
    )
    admitted = get_success_data(
        api.create_public_hearing(fixtures.clerk(ctx), payload), 201
    )
    assert admitted["hearing_status"] == "SCHEDULED"
    assert _instant(admitted["scheduled_start_at"]) == _instant("2026-09-10T20:30:00Z")

    peer = fixtures.read_hearing(api, ctx["municipality"]["id"], ctx["hearing"]["id"])
    assert peer["hearing_status"] == "SCHEDULED"
    assert _instant(peer["scheduled_end_at"]) == _instant("2026-09-10T20:00:00Z")

    hearings, meta = validate_paginated(
        api.list_public_hearings(
            fixtures.clerk(ctx), municipality_id=ctx["municipality"]["id"]
        )
    )
    assert meta["total_count"] == 2
    assertions.assert_id_set(hearings, [ctx["hearing"]["id"], admitted["id"]])


def test_hearing_starting_inside_the_peers_changeover_buffer_conflicts(api):
    """PRD §3.6: "Two hearings conflict when the candidate's start is strictly
    earlier than the peer's end plus the buffer **and** the peer's start is
    strictly earlier than the candidate's end plus the buffer; any conflict is
    refused with `ERR_HEARING_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/chamber_buffered_half_open_interval_admits_exact_touch_only
    """
    ctx, second_case = _chamber_contention_setup(api)

    # 20:15 is fifteen minutes short of the peer's buffered 20:30 release.
    payload = factories.public_hearing_payload(
        second_case["id"],
        ctx["municipality"]["id"],
        scheduled_start_at="2026-09-10T20:15:00Z",
        scheduled_end_at="2026-09-10T21:00:00Z",
    )
    validate_error(
        api.create_public_hearing(fixtures.clerk(ctx), payload),
        ERR_HEARING_SLOT_CONFLICT,
    )

    hearings, meta = validate_paginated(
        api.list_public_hearings(
            fixtures.clerk(ctx), municipality_id=ctx["municipality"]["id"]
        )
    )
    assert meta["total_count"] == 1
    assertions.assert_id_set(hearings, [ctx["hearing"]["id"]])


# ==========================================================================
# A provider's calendar: closed date windows that include both endpoints
# ==========================================================================
def _single_crew_plan(api):
    """A plan of services on a provider whose crew can run one project at a
    time, so any shared calendar day is a conflict."""
    ctx = _certified_case_with_draft_plan(
        api,
        ["POLICE"],
        provider={
            "service_types": ["POLICE", "FIRE", "WATER", "SEWER"],
            "concurrent_project_capacity": 1,
        },
    )
    police = fixtures.add_commitment(
        api,
        ctx,
        "POLICE",
        cost_cents=500000,
        committed_account_count=0,
        window_start_date=_AUGUST_WINDOW[0],
        window_end_date=_AUGUST_WINDOW[1],
    )
    assert police["timeline_days"] == assertions.inclusive_day_count(*_AUGUST_WINDOW)
    activated = fixtures.activate_commitment(api, ctx, police["id"])
    assert activated["commitment_status"] == "FULFILLED"
    return ctx


def test_commitment_window_touching_an_active_window_on_one_day_is_refused(api):
    """PRD §3.5: "A commitment occupies every calendar day from its
    `window_start_date` through its `window_end_date` inclusive, so two
    commitments that merely touch — one ending on the day the other begins — do
    overlap on that shared day." "For each calendar day the candidate occupies,
    the number of peers occupying that same day plus the candidate itself must
    not exceed the provider's `concurrent_project_capacity`; if any single day
    would exceed it, activation is refused with
    `ERR_PROVIDER_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/provider_closed_date_intervals_collide_on_the_shared_touching_day
    """
    ctx = _single_crew_plan(api)
    touching = fixtures.add_commitment(
        api,
        ctx,
        "FIRE",
        cost_cents=400000,
        committed_account_count=0,
        window_start_date=_TOUCHING_WINDOW[0],
        window_end_date=_TOUCHING_WINDOW[1],
    )
    # 31 days, comfortably inside the 60-day police/fire ceiling, so the
    # statutory timeline is not what refuses this activation.
    assert touching["timeline_days"] == assertions.inclusive_day_count(*_TOUCHING_WINDOW)

    validate_error(
        api.activate_service_commitment(fixtures.planner(ctx), touching["id"]),
        ERR_PROVIDER_CAPACITY_EXCEEDED,
    )

    assert (
        fixtures.read_commitment(api, ctx["municipality"]["id"], touching["id"])[
            "commitment_status"
        ]
        == "DRAFT"
    )
    provider = fixtures.read_provider(
        api, ctx["municipality"]["id"], ctx["provider"]["id"]
    )
    # A refused activation encumbers nothing.
    assert provider["encumbered_capacity_days"] == assertions.inclusive_day_count(
        *_AUGUST_WINDOW
    )


def test_commitment_window_starting_the_day_after_is_admitted_and_encumbers_both(api):
    """PRD §3.5: "Admitted, the commitment moves `DRAFT → ACTIVE`, its
    `timeline_days` is added to the provider's `encumbered_capacity_days`, and
    the plan's derived figures are recomputed." "When a commitment's
    `committed_account_count` is 0 there are no accounts to cut over, so it
    advances `ACTIVE → FULFILLED` immediately in the same request."

    Design: Difficulty/resource_temporal_overlap/provider_closed_date_intervals_collide_on_the_shared_touching_day
    """
    ctx = _single_crew_plan(api)
    disjoint = fixtures.add_commitment(
        api,
        ctx,
        "WATER",
        cost_cents=700000,
        committed_account_count=0,
        window_start_date=_SEPTEMBER_WINDOW[0],
        window_end_date=_SEPTEMBER_WINDOW[1],
    )
    assert disjoint["timeline_days"] == assertions.inclusive_day_count(*_SEPTEMBER_WINDOW)

    activated = fixtures.activate_commitment(api, ctx, disjoint["id"])
    assert activated["commitment_status"] == "FULFILLED"

    provider = fixtures.read_provider(
        api, ctx["municipality"]["id"], ctx["provider"]["id"]
    )
    expected_days = assertions.inclusive_day_count(
        *_AUGUST_WINDOW
    ) + assertions.inclusive_day_count(*_SEPTEMBER_WINDOW)
    assert provider["encumbered_capacity_days"] == expected_days

    plan = fixtures.read_plan(api, ctx["municipality"]["id"], ctx["plan"]["id"])
    assert plan["committed_cost_cents"] == 500000 + 700000
    assert plan["covered_service_types"] == assertions.ordered_service_types(
        ["WATER", "POLICE"]
    )


# ==========================================================================
# Withdrawing a signature restores the petition's signature value exactly
# ==========================================================================
_CONSENT_PARCEL_VALUES = [40000000, 30000000, 20000000, 10000000]


def _sufficient_petition_on_two_parcels(api):
    """A `SUFFICIENT` petition carrying the whole interest in the two most
    valuable parcels, so the case waits in `SUFFICIENCY_REVIEW`."""
    ctx = fixtures.setup_certified_case(
        api,
        case={"method": "PETITION_MAJORITY"},
        parcel_values_cents=list(_CONSENT_PARCEL_VALUES),
    )
    fixtures.open_petition(api, ctx, petition_type="OWNER_MAJORITY")
    fixtures.sign_consent(api, ctx, parcel_index=0)
    fixtures.sign_consent(api, ctx, parcel_index=1)
    ctx["petition"] = get_success_data(
        api.certify_sufficiency(fixtures.clerk(ctx), ctx["petition"]["id"])
    )
    fixtures.refresh_case(api, ctx)
    return ctx


def test_third_consent_lifts_the_petition_value_to_the_derived_sum(api):
    """PRD §3.3: "The consent is stored with `consent_status` `SIGNED` and
    `signed_at` set to the clock, and its `qualified_value_cents` is computed
    immediately as the parcel's `assessed_value_cents` multiplied by
    `ownership_share_pct`, divided by one hundred, and rounded half up to a
    whole cent; the owning petition's signature aggregates are then recomputed
    by the rule stated below." "`qualified_signature_assessed_value_cents` is
    the exact integer sum of the qualifying consents' already-rounded
    `qualified_value_cents`, and `qualified_signature_owner_count` is the number
    of distinct `property_owner_id` values among them."

    Design: Difficulty/compensating_invariant/consent_withdrawal_restores_petition_signature_value_without_drift
    """
    ctx = _sufficient_petition_on_two_parcels(api)
    territory_value = sum(_CONSENT_PARCEL_VALUES)

    two_signature_value = (
        _CONSENT_PARCEL_VALUES[0] + _CONSENT_PARCEL_VALUES[1]
    )
    assert ctx["petition"]["qualified_signature_assessed_value_cents"] == two_signature_value
    assert ctx["petition"]["qualified_signature_owner_count"] == 2
    assert ctx["petition"]["sufficiency_status"] == "SUFFICIENT"

    third = fixtures.sign_consent(api, ctx, parcel_index=2)
    # The whole interest in a 20,000,000-cent parcel qualifies at its full value.
    assert third["qualified_value_cents"] == assertions.expected_share_value_cents(
        _CONSENT_PARCEL_VALUES[2], 100.00
    )

    petition = fixtures.read_petition(
        api, ctx["municipality"]["id"], ctx["petition"]["id"]
    )
    forward_value = two_signature_value + _CONSENT_PARCEL_VALUES[2]
    assert petition["qualified_signature_assessed_value_cents"] == forward_value
    assert petition["qualified_signature_owner_count"] == 3
    assert assertions.approx_equal(
        petition["signature_value_pct"],
        assertions.expected_weight_pct(forward_value, territory_value),
    )


def test_withdrawing_that_consent_returns_the_petition_value_without_drift(api):
    """PRD §3.3: "Withdrawal sets `consent_status` to `WITHDRAWN`, stamps
    `withdrawn_at` from the clock, and resets that consent's
    `qualified_value_cents` to 0 so it stops contributing." "The petition's
    aggregates are then recomputed." "`signature_value_pct` is that value sum
    divided by the case's `territory_assessed_value_cents`, multiplied by one
    hundred and rounded half up to two decimal places — or exactly 0.00 when the
    territory's assessed value is zero."

    Design: Difficulty/compensating_invariant/consent_withdrawal_restores_petition_signature_value_without_drift
    """
    ctx = _sufficient_petition_on_two_parcels(api)
    territory_value = sum(_CONSENT_PARCEL_VALUES)

    before = fixtures.read_petition(
        api, ctx["municipality"]["id"], ctx["petition"]["id"]
    )
    value_before = before["qualified_signature_assessed_value_cents"]
    owners_before = before["qualified_signature_owner_count"]
    assert value_before == _CONSENT_PARCEL_VALUES[0] + _CONSENT_PARCEL_VALUES[1]

    third = fixtures.sign_consent(api, ctx, parcel_index=2)
    withdrawn = get_success_data(
        api.withdraw_consent(fixtures.owner_headers(ctx, 2), third["id"])
    )
    assert withdrawn["consent_status"] == "WITHDRAWN"
    assert withdrawn["qualified_value_cents"] == 0

    after = fixtures.read_petition(api, ctx["municipality"]["id"], ctx["petition"]["id"])
    assert after["qualified_signature_assessed_value_cents"] == value_before
    assert after["qualified_signature_owner_count"] == owners_before
    assert assertions.approx_equal(
        after["signature_value_pct"],
        assertions.expected_weight_pct(value_before, territory_value),
    )
    # 70.00% still clears the statute's 50.00 threshold, so nothing downstream
    # of the petition is disturbed either.
    assert after["sufficiency_status"] == "SUFFICIENT"
    assert (
        fixtures.read_case(api, ctx["municipality"]["id"], ctx["case"]["id"])["status"]
        == "SUFFICIENCY_REVIEW"
    )


# ==========================================================================
# Voiding a commitment releases exactly what it encumbered
# ==========================================================================
_POLICE_COST_CENTS = 500000
_WATER_COST_CENTS = 700000


def _two_fulfilled_commitments(api):
    """A plan whose police and water commitments are both `FULFILLED` on the
    same single-crew provider, over windows that share no calendar day."""
    ctx = _certified_case_with_draft_plan(
        api,
        ["POLICE", "WATER"],
        provider={
            "service_types": ["POLICE", "WATER"],
            "concurrent_project_capacity": 1,
        },
    )
    police = fixtures.add_commitment(
        api,
        ctx,
        "POLICE",
        cost_cents=_POLICE_COST_CENTS,
        committed_account_count=0,
        window_start_date=_AUGUST_WINDOW[0],
        window_end_date=_AUGUST_WINDOW[1],
    )
    fixtures.activate_commitment(api, ctx, police["id"])
    water = fixtures.add_commitment(
        api,
        ctx,
        "WATER",
        cost_cents=_WATER_COST_CENTS,
        committed_account_count=0,
        window_start_date=_SEPTEMBER_WINDOW[0],
        window_end_date=_SEPTEMBER_WINDOW[1],
    )
    fixtures.activate_commitment(api, ctx, water["id"])
    return ctx, police, water


def test_activating_both_commitments_accumulates_the_derived_days_and_cost(api):
    """PRD §3.5: "`committed_cost_cents` is the sum of those commitments'
    `cost_cents`." "`service_readiness` is `PENDING` when that set of
    commitments is empty; it is `READY` when every member of the statute's
    `required_service_types` appears in `covered_service_types` **and** every
    one of those commitments is in `FULFILLED`; and it is `PARTIAL` in every
    other case."

    Design: Difficulty/compensating_invariant/commitment_void_releases_exactly_the_encumbrance_and_cost_it_added
    """
    ctx = _certified_case_with_draft_plan(
        api,
        ["POLICE", "WATER"],
        provider={
            "service_types": ["POLICE", "WATER"],
            "concurrent_project_capacity": 1,
        },
    )
    police_days = assertions.inclusive_day_count(*_AUGUST_WINDOW)
    water_days = assertions.inclusive_day_count(*_SEPTEMBER_WINDOW)

    police = fixtures.add_commitment(
        api,
        ctx,
        "POLICE",
        cost_cents=_POLICE_COST_CENTS,
        committed_account_count=0,
        window_start_date=_AUGUST_WINDOW[0],
        window_end_date=_AUGUST_WINDOW[1],
    )
    fixtures.activate_commitment(api, ctx, police["id"])
    provider = fixtures.read_provider(
        api, ctx["municipality"]["id"], ctx["provider"]["id"]
    )
    assert provider["encumbered_capacity_days"] == police_days
    plan = fixtures.read_plan(api, ctx["municipality"]["id"], ctx["plan"]["id"])
    assert plan["committed_cost_cents"] == _POLICE_COST_CENTS
    # Water is still missing from the statute's required set.
    assert plan["service_readiness"] == "PARTIAL"

    water = fixtures.add_commitment(
        api,
        ctx,
        "WATER",
        cost_cents=_WATER_COST_CENTS,
        committed_account_count=0,
        window_start_date=_SEPTEMBER_WINDOW[0],
        window_end_date=_SEPTEMBER_WINDOW[1],
    )
    fixtures.activate_commitment(api, ctx, water["id"])
    provider = fixtures.read_provider(
        api, ctx["municipality"]["id"], ctx["provider"]["id"]
    )
    assert provider["encumbered_capacity_days"] == police_days + water_days
    plan = fixtures.read_plan(api, ctx["municipality"]["id"], ctx["plan"]["id"])
    assert plan["committed_cost_cents"] == _POLICE_COST_CENTS + _WATER_COST_CENTS
    assert plan["service_readiness"] == "READY"


def test_voiding_the_water_commitment_releases_exactly_its_own_days_and_cost(api):
    """PRD §3.5: "The void moves `commitment_status` to `VOIDED`, and when the
    commitment had been `ACTIVE` or `FULFILLED` its `timeline_days` is
    subtracted from the provider's `encumbered_capacity_days` — a `DRAFT`
    commitment releases nothing because it encumbered nothing."
    "`committed_cost_cents`, `covered_service_types` and `service_readiness` are
    then recomputed by the rule above, and the plan's `version` increments."

    Design: Difficulty/compensating_invariant/commitment_void_releases_exactly_the_encumbrance_and_cost_it_added
    """
    ctx, police, water = _two_fulfilled_commitments(api)
    police_days = assertions.inclusive_day_count(*_AUGUST_WINDOW)
    water_days = assertions.inclusive_day_count(*_SEPTEMBER_WINDOW)

    provider = fixtures.read_provider(
        api, ctx["municipality"]["id"], ctx["provider"]["id"]
    )
    assert provider["encumbered_capacity_days"] == police_days + water_days

    voided = get_success_data(
        api.void_service_commitment(fixtures.planner(ctx), water["id"])
    )
    assert voided["commitment_status"] == "VOIDED"
    # Exactly the water window's own days come back, not the whole ledger.
    assert voided["timeline_days"] == water_days

    provider = fixtures.read_provider(
        api, ctx["municipality"]["id"], ctx["provider"]["id"]
    )
    assert provider["encumbered_capacity_days"] == police_days

    plan = fixtures.read_plan(api, ctx["municipality"]["id"], ctx["plan"]["id"])
    assert plan["committed_cost_cents"] == _POLICE_COST_CENTS
    assert plan["covered_service_types"] == assertions.ordered_service_types(["POLICE"])
    assert plan["service_readiness"] == "PARTIAL"
    assert (
        fixtures.read_commitment(api, ctx["municipality"]["id"], police["id"])[
            "commitment_status"
        ]
        == "FULFILLED"
    )


# ==========================================================================
# De-annexation reverses the municipal tax base and refunds the remainder
# ==========================================================================
_DE_ANNEX_PARCEL_VALUE_CENTS = 3657300
_MONTHLY_BASE_CENTS = 5000


def _posted_annexation_with_one_water_account(api):
    """An annexation carried all the way to a posted tax roll, with one water
    account that made the whole outside-city to inside-city journey."""
    ctx = fixtures.setup_certified_case(
        api,
        parcel_values_cents=[_DE_ANNEX_PARCEL_VALUE_CENTS] * _PARCEL_COUNT,
    )
    ctx["account"] = fixtures.add_utility_account(
        api,
        ctx["municipality"]["id"],
        ctx["parcels"][0]["id"],
        ctx["provider"]["id"],
        service_type="WATER",
        monthly_base_cents=_MONTHLY_BASE_CENTS,
    )
    fixtures.setup_adopted_plan(api, ctx)
    fixtures.setup_hearing_noticed(api, ctx)
    fixtures.setup_hearing_held(api, ctx)
    fixtures.close_protest_period(api, ctx)
    fixtures.setup_finalized_analysis(api, ctx)
    fixtures.adopt_ordinance(api, ctx)
    fixtures.effectuate(api, ctx, constants.EFFECTIVE_DATE_AFTER_PROTEST)
    fixtures.post_tax_roll(api, ctx)
    return ctx


def _expected_posted_tax_cents(effective_date):
    """The per-parcel annual levy prorated over the remainder of the fiscal
    year, rounded per parcel and only then summed."""
    annual = assertions.expected_property_tax_cents(_DE_ANNEX_PARCEL_VALUE_CENTS, 10.0)
    remaining_days = assertions.remaining_fiscal_days(
        effective_date, constants.DEFAULT_FISCAL_YEAR_END_MONTH_DAY
    )
    per_parcel = assertions.expected_prorated_tax_cents(annual, remaining_days)
    return per_parcel * _PARCEL_COUNT


def test_posting_the_tax_roll_adds_the_derived_prorated_levy_to_the_municipal_base(api):
    """PRD §3.8: "Then walk the case's parcels in `INCORPORATED`, ordered by
    `created_at` ascending and never by identifier, and for each one stamp
    `annual_tax_cents` as the parcel's `assessed_value_cents` multiplied by the
    municipality's `general_fund_millage_rate`, divided by one thousand, rounded
    half up to a whole cent; then stamp `prorated_tax_cents` as that
    `annual_tax_cents` multiplied by the remaining days, divided by the three
    hundred and sixty-five days of the fiscal year, rounded half up to a whole
    cent." "The municipality's `taxable_assessed_value_cents` is increased by
    that transferred assessed value, `tax_roll_status` advances
    `NOT_TRANSFERRED → POSTED`, and the case's `version` increments."

    Design: Difficulty/compensating_invariant/de_annexation_reverses_the_municipal_tax_base_and_refunds_the_remainder
    """
    ctx = fixtures.setup_certified_case(
        api,
        parcel_values_cents=[_DE_ANNEX_PARCEL_VALUE_CENTS] * _PARCEL_COUNT,
    )
    base_before = fixtures.read_municipality(api, ctx["municipality"]["id"])[
        "taxable_assessed_value_cents"
    ]
    assert base_before == 0

    ctx["account"] = fixtures.add_utility_account(
        api,
        ctx["municipality"]["id"],
        ctx["parcels"][0]["id"],
        ctx["provider"]["id"],
        service_type="WATER",
        monthly_base_cents=_MONTHLY_BASE_CENTS,
    )
    # Registered outside the corporate limits, the account carries the city's
    # 0.50 surcharge.
    assert ctx["account"][
        "effective_monthly_cents"
    ] == assertions.expected_outside_city_monthly_cents(
        _MONTHLY_BASE_CENTS, constants.DEFAULT_UTILITY_OUTSIDE_SURCHARGE_PCT
    )

    fixtures.setup_adopted_plan(api, ctx)
    fixtures.setup_hearing_noticed(api, ctx)
    fixtures.setup_hearing_held(api, ctx)
    fixtures.close_protest_period(api, ctx)
    fixtures.setup_finalized_analysis(api, ctx)
    fixtures.adopt_ordinance(api, ctx)
    fixtures.effectuate(api, ctx, constants.EFFECTIVE_DATE_AFTER_PROTEST)

    case = fixtures.post_tax_roll(api, ctx)
    territory_value = _DE_ANNEX_PARCEL_VALUE_CENTS * _PARCEL_COUNT
    assert case["tax_roll_status"] == "POSTED"
    assert case["tax_roll_transferred_assessed_value_cents"] == territory_value
    assert case["tax_roll_transferred_tax_cents"] == _expected_posted_tax_cents(
        constants.EFFECTIVE_DATE_AFTER_PROTEST
    )

    municipality = fixtures.read_municipality(api, ctx["municipality"]["id"])
    assert municipality["taxable_assessed_value_cents"] == base_before + territory_value


def test_de_annexation_returns_the_municipal_base_and_refunds_only_the_remainder(api):
    """PRD §3.9: "And because the predecessor was de-annexed while its
    `tax_roll_status` was `POSTED`, that status advances `POSTED → REVERSED`,
    the municipality's `taxable_assessed_value_cents` is decreased by the
    predecessor's `tax_roll_transferred_assessed_value_cents`, and the
    successor's `de_annexation_refund_cents` is computed." "Because the
    predecessor became `DE_ANNEXED`, every parcel of the predecessor in
    `INCORPORATED` moves to `DE_ANNEXED`." "Because those parcels were
    de-annexed, each of their utility accounts in
    `INSIDE_CITY_PENDING_TRANSITION` or `INSIDE_CITY_ACTIVE` returns to
    `OUTSIDE_CITY`, its `rate_schedule` returns to `OUTSIDE_CITY_SURCHARGE`, and
    its `effective_monthly_cents` is recomputed with the surcharge restored —
    closing the account cycle `OUTSIDE_CITY → INSIDE_CITY_PENDING_TRANSITION →
    INSIDE_CITY_ACTIVE → OUTSIDE_CITY`." "Under
    `DAILY_PRORATION`, locate the fiscal year end relative to the de-annexation
    case's own `effective_date` — the statute's `fiscal_year_end_month_day` in
    the effective date's year if the effective date is on or before it,
    otherwise the same month and day the following year — count the days from
    the effective date through that fiscal year end inclusive of both endpoints,
    and set the refund to the predecessor's posted tax multiplied by those
    remaining days, divided by the three hundred and sixty-five days of the
    fiscal year, rounded half up to a whole cent."

    Design: Difficulty/compensating_invariant/de_annexation_reverses_the_municipal_tax_base_and_refunds_the_remainder
    """
    ctx = _posted_annexation_with_one_water_account(api)
    posted_tax = ctx["case"]["tax_roll_transferred_tax_cents"]
    posted_value = ctx["case"]["tax_roll_transferred_assessed_value_cents"]
    base_after_posting = fixtures.read_municipality(api, ctx["municipality"]["id"])[
        "taxable_assessed_value_cents"
    ]
    assert base_after_posting == posted_value

    successor = fixtures.setup_de_annexation_case(api, ctx)
    case = fixtures.effectuate(
        api, successor, constants.DE_ANNEXATION_EFFECTIVE_DATE
    )
    assert case["status"] == "EFFECTIVE"

    # Only the unused remainder of the fiscal year comes back, not the whole
    # posted levy.
    expected_refund = assertions.expected_daily_proration_refund_cents(
        posted_tax,
        constants.DE_ANNEXATION_EFFECTIVE_DATE,
        constants.DEFAULT_FISCAL_YEAR_END_MONTH_DAY,
    )
    assert case["de_annexation_refund_cents"] == expected_refund
    assert expected_refund < posted_tax

    predecessor = fixtures.read_case(
        api, ctx["municipality"]["id"], ctx["case"]["id"]
    )
    assert predecessor["status"] == "DE_ANNEXED"
    assert predecessor["tax_roll_status"] == "REVERSED"

    # The municipal ledger is back to exactly the value it carried before the
    # roll was ever posted.
    municipality = fixtures.read_municipality(api, ctx["municipality"]["id"])
    assert municipality["taxable_assessed_value_cents"] == base_after_posting - posted_value
    assert municipality["taxable_assessed_value_cents"] == 0

    for parcel in ctx["parcels"]:
        assert (
            fixtures.read_parcel(api, ctx["municipality"]["id"], parcel["id"])[
                "parcel_status"
            ]
            == "DE_ANNEXED"
        )

    account = fixtures.read_account(
        api, ctx["municipality"]["id"], ctx["account"]["id"]
    )
    assert account["account_status"] == "OUTSIDE_CITY"
    assert account["rate_schedule"] == "OUTSIDE_CITY_SURCHARGE"
    assert account["effective_monthly_cents"] == assertions.expected_outside_city_monthly_cents(
        _MONTHLY_BASE_CENTS, constants.DEFAULT_UTILITY_OUTSIDE_SURCHARGE_PCT
    )
