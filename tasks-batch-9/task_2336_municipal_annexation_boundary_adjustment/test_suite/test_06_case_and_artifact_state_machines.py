"""Lifecycle compliance tests for the annexation case and its artifacts.

These tests exercise the procedural ladder a case walks — the states it starts
in, the transitions that advance it, the replays and out-of-order acts the
statute refuses, and the unwinding a denial forces on the parcels, the plan of
services, its commitments and the provider's capacity ledger.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    assertions,
    boundary_commissioner_headers,
    constants,
    county_assessor_headers,
    factories,
    fixtures,
    make_city_clerk_headers,
    make_municipal_planner_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import (  # noqa: E402
    ERR_CASE_STATE_INVALID,
    ERR_CASE_TERMINAL,
    ERR_COMMITMENT_STATE_INVALID,
    ERR_NOTICE_WINDOW_NOT_SATISFIED,
    ERR_PETITION_EXPIRED,
    ERR_PLAN_ALREADY_ADOPTED,
    ERR_PROTEST_PERIOD_CLOSED,
)

# A police commitment window well inside the 60-day police/fire statutory
# ceiling of PRD §2.6, so activation turns on capacity rather than timeline.
_POLICE_WINDOW_START = "2026-08-01"
_POLICE_WINDOW_END = "2026-09-15"
_POLICE_COST_CENTS = 500000
_SECOND_PLAN_COST_CENTS = 700000

# A hearing whose start the clock can reach long before thirty days of notice
# have run, so the notice window is the only unsatisfied precondition.
_EARLY_HEARING_START_AT = "2026-08-20T18:00:00Z"
_EARLY_HEARING_END_AT = "2026-08-20T20:00:00Z"

# A petition circulation window short enough to lapse inside the test timeline.
_SHORT_CIRCULATION_DAYS = 30
_CLOCK_PAST_PETITION_DEADLINE = "2026-09-05T00:00:00Z"


def _same_instant(actual, expected) -> bool:
    """Compare two ISO 8601 instants to the second: PRD §2.5 renders stamped
    timestamps with three fractional digits that a literal does not carry."""
    return actual is not None and actual[:19] == expected[:19]


def _parcel_status_count(api, ctx, parcel_status: str) -> int:
    """How many parcels of the case currently sit in `parcel_status`."""
    _, meta = validate_paginated(
        api.list_parcels(
            fixtures.planner(ctx),
            annexation_case_id=ctx["case"]["id"],
            parcel_status=parcel_status,
        )
    )
    return meta["total_count"]


def _certified_case_with_an_active_police_commitment(api):
    """A `TERRITORY_CERTIFIED` case whose draft plan carries one activated
    police commitment. Its `committed_account_count` is deliberately non-zero so
    the commitment stops at `ACTIVE` instead of fulfilling immediately."""
    ctx = fixtures.setup_certified_case(
        api,
        statute={
            "authorized_methods": ["INVOLUNTARY_ORDINANCE"],
            "required_service_types": ["POLICE"],
        },
        provider={"service_types": ["POLICE"], "concurrent_project_capacity": 1},
    )
    fixtures.open_plan(api, ctx)
    commitment = fixtures.add_commitment(
        api,
        ctx,
        "POLICE",
        cost_cents=_POLICE_COST_CENTS,
        committed_account_count=1,
        window_start_date=_POLICE_WINDOW_START,
        window_end_date=_POLICE_WINDOW_END,
    )
    ctx["commitment"] = fixtures.activate_commitment(api, ctx, commitment["id"])
    return ctx


# ==========================================================================
# Declared initial states
# ==========================================================================
def test_a_new_case_starts_draft_on_the_procedural_and_tax_roll_axes(api):
    """PRD §3.2: "A fresh case starts with `status` `DRAFT`, `tax_roll_status`
    `NOT_TRANSFERRED`, `protest_outcome` `NOT_EVALUATED`, `referendum_result`
    `NOT_HELD` and `commission_review_status` `NOT_REQUIRED`."

    Design: Corner/state_machines/new_case_and_parcel_start_in_their_declared_initial_states
    """
    ctx = fixtures.setup_jurisdiction(api)
    municipality_id = ctx["municipality"]["id"]
    planner = make_municipal_planner_headers(municipality_id)

    response = api.create_annexation_case(
        planner, factories.annexation_case_payload(municipality_id)
    )
    case = validate_success(response, 201)

    assert case["status"] == "DRAFT"
    assert case["tax_roll_status"] == "NOT_TRANSFERRED"
    assert case["protest_outcome"] == "NOT_EVALUATED"
    assert case["referendum_result"] == "NOT_HELD"
    assert case["commission_review_status"] == "NOT_REQUIRED"
    # PRD §3.2 defaults `case_type` to ANNEXATION with a null predecessor.
    assert case["case_type"] == "ANNEXATION"
    assert case["predecessor_case_id"] is None
    # PRD §2.5: `version` starts at 1 on creation.
    assertions.assert_revision_fields(case, expected_version=1)


def test_a_newly_added_parcel_starts_proposed_and_advances_the_case_version(api):
    """PRD §3.2: "A new parcel enters with `parcel_status` `PROPOSED`."

    Design: Corner/state_machines/new_case_and_parcel_start_in_their_declared_initial_states
    """
    ctx = fixtures.setup_jurisdiction(api)
    municipality_id = ctx["municipality"]["id"]
    planner = make_municipal_planner_headers(municipality_id)
    owner = fixtures.create_owner(api)
    case = fixtures.create_case(api, municipality_id)

    response = api.create_parcel(
        planner, case["id"], factories.parcel_payload(owner["id"])
    )
    parcel = validate_success(response, 201)

    assert parcel["parcel_status"] == "PROPOSED"
    assertions.assert_revision_fields(parcel, expected_version=1)

    # PRD §2.9 lists adding a parcel among the acts that advance the case's
    # `version`, so the case stands at 2 after its creation plus one addition.
    reread_case = fixtures.read_case(api, municipality_id, case["id"])
    assert reread_case["status"] == "DRAFT"
    assert reread_case["version"] == 2


# ==========================================================================
# DRAFT → TERRITORY_CERTIFIED
# ==========================================================================
def test_certifying_territory_stamps_every_qualification_field_and_promotes_parcels(api):
    """PRD §3.2: "A successful certification stamps `parcel_count`,
    `territory_acreage`, `territory_assessed_value_cents`, `contiguity_ratio`,
    `urban_development_qualified` and `qualification_index` onto the case,
    promotes every parcel of the case still in `PROPOSED` to `PENDING_ANNEX`,
    and increments the case's `version`."

    Design: Corner/state_machines/certify_territory_advances_the_case_and_stamps_every_qualification_field
    """
    ctx = fixtures.setup_draft_case(
        api, parcel_values_cents=[40000000, 30000000, 20000000, 10000000]
    )
    draft = ctx["case"]
    municipality = ctx["municipality"]
    assert draft["status"] == "DRAFT"
    assert _parcel_status_count(api, ctx, "PROPOSED") == 4
    draft_version = draft["version"]

    response = api.certify_territory(fixtures.planner(ctx), draft["id"])
    case = validate_success(response)

    assert case["status"] == "TERRITORY_CERTIFIED"

    # The territory aggregates of PRD §3.2 cover the four PROPOSED parcels:
    # 5.00 acres each and 100 000 000 cents of assessed value in total.
    assert case["parcel_count"] == 4
    assertions.assert_numeric_equals(
        case["territory_acreage"], assertions.acres("20.00"), "territory_acreage"
    )
    assert case["territory_assessed_value_cents"] == 100000000

    expected_ratio = assertions.expected_contiguity_ratio(
        draft["shared_boundary_feet"], municipality["corporate_boundary_perimeter_feet"]
    )
    assertions.assert_numeric_equals(
        case["contiguity_ratio"], expected_ratio, "contiguity_ratio", places=4
    )

    # Every lot carries a structure, so the subdivision limb of the urban
    # development test passes on its own (PRD §3.2).
    developed_ratio = assertions.expected_developed_lot_ratio(
        draft["developed_lot_count"], draft["total_lot_count"]
    )
    density = assertions.expected_density(draft["dwelling_units"], "20.00")
    assert case["urban_development_qualified"] is True

    # The statute leaves every threshold of PRD §2.6 at its declared default.
    expected_index = assertions.expected_qualification_index(
        expected_ratio,
        constants.DEFAULT_CONTIGUITY_MIN_RATIO,
        True,
        density,
        constants.DEFAULT_URBAN_DENSITY_MIN_UNITS_PER_ACRE,
        developed_ratio,
        constants.DEFAULT_SUBDIVISION_TEST_MIN_DEVELOPED_RATIO,
        constants.DEFAULT_MAX_SERVICE_DISTANCE_MILES,
    )
    assertions.assert_numeric_equals(
        case["qualification_index"], expected_index, "qualification_index"
    )

    # PRD §2.9: certifying territory advances the case's `version` exactly once,
    # and the case has been mutated only by its four parcel additions before.
    assert case["version"] == draft_version + 1
    assert case["version"] == 6

    for parcel in ctx["parcels"]:
        promoted = fixtures.read_parcel(api, municipality["id"], parcel["id"])
        assert promoted["parcel_status"] == "PENDING_ANNEX"
    ctx["case"] = case
    assert _parcel_status_count(api, ctx, "PENDING_ANNEX") == 4
    assert _parcel_status_count(api, ctx, "PROPOSED") == 0


# ==========================================================================
# Replaying a transition from the wrong origin state
# ==========================================================================
def test_certifying_an_already_certified_territory_is_refused(api):
    """PRD §3.2: "It requires the case to be in `DRAFT`, and it requires the
    case's `method` to appear in the statute's `authorized_methods` — otherwise
    `ERR_METHOD_NOT_AUTHORIZED_BY_STATUTE`."

    Design: Corner/state_machines/replaying_certify_and_activate_from_the_wrong_state_is_rejected
    """
    ctx = _certified_case_with_an_active_police_commitment(api)
    municipality_id = ctx["municipality"]["id"]
    case_id = ctx["case"]["id"]
    version_before = fixtures.read_case(api, municipality_id, case_id)["version"]

    # PRD §2.10 heads the state-admissibility checks with the requirement that
    # the case's status be a declared origin state of the requested transition.
    validate_error(
        api.certify_territory(fixtures.planner(ctx), case_id), ERR_CASE_STATE_INVALID
    )

    unchanged = fixtures.read_case(api, municipality_id, case_id)
    assert unchanged["status"] == "TERRITORY_CERTIFIED"
    assert unchanged["version"] == version_before


def test_activating_an_already_active_commitment_is_refused(api):
    """PRD §3.5: "The commitment must be in `DRAFT` (otherwise
    `ERR_COMMITMENT_STATE_INVALID`), its `service_type` must still be one the
    provider offers (`ERR_PROVIDER_SERVICE_TYPE_MISMATCH`), and its
    `timeline_days` must not exceed the statutory ceiling for its service type —
    `police_fire_timeline_max_days` for `POLICE` and `FIRE`,
    `water_sewer_timeline_max_days` for `WATER` and `SEWER` — with a longer
    window refused as `ERR_PLAN_SERVICE_TIMELINE_EXCEEDS_STATUTE`."

    Design: Corner/state_machines/replaying_certify_and_activate_from_the_wrong_state_is_rejected
    """
    ctx = _certified_case_with_an_active_police_commitment(api)
    municipality_id = ctx["municipality"]["id"]
    commitment_id = ctx["commitment"]["id"]

    validate_error(
        api.activate_service_commitment(fixtures.planner(ctx), commitment_id),
        ERR_COMMITMENT_STATE_INVALID,
    )

    commitment = fixtures.read_commitment(api, municipality_id, commitment_id)
    assert commitment["commitment_status"] == "ACTIVE"

    # PRD §3.5 counts both endpoints of the window, and one activation
    # encumbers the provider once — a rejected replay adds nothing.
    expected_days = assertions.inclusive_day_count(
        _POLICE_WINDOW_START, _POLICE_WINDOW_END
    )
    assert commitment["timeline_days"] == expected_days
    provider = fixtures.read_provider(api, municipality_id, ctx["provider"]["id"])
    assert provider["encumbered_capacity_days"] == expected_days

    # The one required service type is covered but not yet fulfilled, so the
    # plan's readiness stays PARTIAL (PRD §3.5).
    plan = fixtures.read_plan(api, municipality_id, ctx["plan"]["id"])
    assert plan["service_readiness"] == "PARTIAL"
    assert plan["committed_cost_cents"] == _POLICE_COST_CENTS
    assert plan["covered_service_types"] == ["POLICE"]


# ==========================================================================
# Closing the protest period twice
# ==========================================================================
def test_closing_an_already_closed_protest_period_is_refused(api):
    """PRD §3.6: "Closing the protest period is the tabulation, and it is
    admissible only when the hearing is `HELD` with `protest_outcome` still
    `OPEN` — otherwise `ERR_PROTEST_PERIOD_CLOSED` — and only once the logical
    clock has moved strictly past `protest_closes_at`, since an equal reading
    still leaves the last day open and draws `ERR_PROTEST_PERIOD_NOT_CLOSED`."

    Design: Corner/state_machines/closing_an_already_closed_protest_period_is_rejected
    """
    ctx = fixtures.setup_certified_case(api)
    fixtures.setup_adopted_plan(api, ctx)
    fixtures.setup_hearing_noticed(api, ctx)
    fixtures.setup_hearing_held(api, ctx)
    municipality_id = ctx["municipality"]["id"]
    clerk = make_city_clerk_headers(municipality_id)
    hearing_id = ctx["hearing"]["id"]
    held_at = ctx["hearing"]["held_at"]

    # PRD §3.6 closes the window `protest_window_days` after the hearing was
    # held; the default window is thirty days (PRD §3.6).
    expected_closes_at = assertions.add_days(
        held_at, constants.DEFAULT_PROTEST_WINDOW_DAYS
    )
    assert _same_instant(ctx["hearing"]["protest_closes_at"], expected_closes_at)

    fixtures.set_clock(api, constants.CLOCK_AFTER_PROTEST_WINDOW)
    tabulated = validate_success(api.close_protest_period(clerk, hearing_id))

    # No owner objected, so the protest fails and the case self-loops at
    # HEARING_HELD (PRD §3.6).
    assert tabulated["protest_outcome"] == "FAILED"
    assertions.assert_numeric_equals(tabulated["protest_pct"], 0, "protest_pct")
    case = fixtures.read_case(api, municipality_id, ctx["case"]["id"])
    assert case["status"] == "HEARING_HELD"
    assert case["protest_outcome"] == "FAILED"

    validate_error(
        api.close_protest_period(clerk, hearing_id), ERR_PROTEST_PERIOD_CLOSED
    )

    # The refused replay re-stamps nothing.
    hearing = fixtures.read_hearing(api, municipality_id, hearing_id)
    assert hearing["hearing_status"] == "HELD"
    assert hearing["protest_outcome"] == "FAILED"
    assertions.assert_numeric_equals(hearing["protest_pct"], 0, "protest_pct")


# ==========================================================================
# Adopting a second plan of services on one case
# ==========================================================================
def test_adopting_a_second_plan_of_services_on_one_case_is_refused(api):
    """PRD §3.5: "It requires the plan to be in `DRAFT`, requires the owning
    case to be in one of `TERRITORY_CERTIFIED`, `PETITION_CIRCULATING`,
    `SUFFICIENCY_REVIEW`, `HEARING_NOTICED` or `HEARING_HELD`, requires that no
    other plan of the case is already `ADOPTED` (otherwise
    `ERR_PLAN_ALREADY_ADOPTED`), requires `covered_service_types` to contain
    every member of the statute's `required_service_types` (otherwise
    `ERR_SERVICE_TYPE_NOT_COVERED`), and re-checks that every commitment of the
    plan in `ACTIVE` or `FULFILLED` respects the statutory ceiling for its
    service type (otherwise `ERR_PLAN_SERVICE_TIMELINE_EXCEEDS_STATUTE`)."

    Design: Corner/state_machines/adopting_a_second_plan_of_services_on_one_case_is_rejected
    """
    # Capacity 2 lets both plans hold a commitment over the identical window,
    # so the second adoption fails on the sibling plan rather than on capacity.
    ctx = fixtures.setup_certified_case(
        api,
        statute={
            "authorized_methods": ["INVOLUNTARY_ORDINANCE"],
            "required_service_types": ["POLICE"],
        },
        provider={"service_types": ["POLICE"], "concurrent_project_capacity": 2},
    )
    municipality_id = ctx["municipality"]["id"]
    clerk = make_city_clerk_headers(municipality_id)

    first_plan = fixtures.open_plan(api, ctx)
    first_commitment = fixtures.add_commitment(
        api,
        ctx,
        "POLICE",
        cost_cents=_POLICE_COST_CENTS,
        committed_account_count=0,
        window_start_date=_POLICE_WINDOW_START,
        window_end_date=_POLICE_WINDOW_END,
    )
    fixtures.activate_commitment(api, ctx, first_commitment["id"])
    adopted = validate_success(api.adopt_plan_of_services(clerk, first_plan["id"]))
    assert adopted["adoption_status"] == "ADOPTED"

    second_plan = fixtures.open_plan(api, ctx)
    second_commitment = fixtures.add_commitment(
        api,
        ctx,
        "POLICE",
        cost_cents=_SECOND_PLAN_COST_CENTS,
        committed_account_count=0,
        window_start_date=_POLICE_WINDOW_START,
        window_end_date=_POLICE_WINDOW_END,
    )
    fixtures.activate_commitment(api, ctx, second_commitment["id"])

    validate_error(
        api.adopt_plan_of_services(clerk, second_plan["id"]), ERR_PLAN_ALREADY_ADOPTED
    )

    # Adoption is single-shot per case, but each plan keeps its own readiness
    # axis: PRD §3.5 makes readiness independent of adoption.
    refused = fixtures.read_plan(api, municipality_id, second_plan["id"])
    assert refused["adoption_status"] == "DRAFT"
    assert refused["adopted_at"] is None
    assert refused["service_readiness"] == "READY"
    assert refused["committed_cost_cents"] == _SECOND_PLAN_COST_CENTS

    survivor = fixtures.read_plan(api, municipality_id, first_plan["id"])
    assert survivor["adoption_status"] == "ADOPTED"
    assert survivor["service_readiness"] == "READY"

    # Both activations encumber the provider's calendar (PRD §3.5).
    expected_days = assertions.inclusive_day_count(
        _POLICE_WINDOW_START, _POLICE_WINDOW_END
    )
    provider = fixtures.read_provider(api, municipality_id, ctx["provider"]["id"])
    assert provider["encumbered_capacity_days"] == 2 * expected_days


# ==========================================================================
# The terminal petition state
# ==========================================================================
def test_certifying_sufficiency_on_an_expired_petition_is_refused(api):
    """PRD §3.3: "If the logical clock is past `circulation_deadline_at`, the
    petition is instead marked `EXPIRED` and the case's `status` is left
    untouched; this applies to a petition in `CIRCULATING` and equally to one in
    `INSUFFICIENT`, and `EXPIRED` is terminal — an expired petition can never be
    certified again, and a later attempt draws `ERR_PETITION_EXPIRED`."

    Design: Corner/state_machines/certify_sufficiency_on_an_expired_petition_is_rejected
    """
    ctx = fixtures.setup_certified_case(api, case={"method": "PETITION_MAJORITY"})
    municipality_id = ctx["municipality"]["id"]
    clerk = make_city_clerk_headers(municipality_id)
    petition = fixtures.open_petition(
        api, ctx, petition_type="OWNER_MAJORITY", circulation_days=_SHORT_CIRCULATION_DAYS
    )

    assert petition["sufficiency_status"] == "CIRCULATING"
    # PRD §3.3 measures the deadline from the clock reading at opening.
    assert _same_instant(petition["circulation_started_at"], constants.CLOCK_STARTUP_UTC)
    assert _same_instant(
        petition["circulation_deadline_at"],
        assertions.add_days(
            petition["circulation_started_at"], _SHORT_CIRCULATION_DAYS
        ),
    )
    case = fixtures.read_case(api, municipality_id, ctx["case"]["id"])
    assert case["status"] == "PETITION_CIRCULATING"

    fixtures.set_clock(api, _CLOCK_PAST_PETITION_DEADLINE)
    lapsed = validate_success(api.certify_sufficiency(clerk, petition["id"]))
    assert lapsed["sufficiency_status"] == "EXPIRED"

    # The lapse leaves the case exactly where it stood.
    case = fixtures.read_case(api, municipality_id, ctx["case"]["id"])
    assert case["status"] == "PETITION_CIRCULATING"

    validate_error(
        api.certify_sufficiency(clerk, petition["id"]), ERR_PETITION_EXPIRED
    )
    still_expired = fixtures.read_petition(api, municipality_id, petition["id"])
    assert still_expired["sufficiency_status"] == "EXPIRED"


# ==========================================================================
# Holding a hearing before the notice window has run
# ==========================================================================
def test_holding_a_hearing_before_the_notice_window_elapses_is_refused(api):
    """PRD §3.6: "Four conditions apply, and their order is the order of §2.10:
    the hearing must still be `SCHEDULED` (`ERR_HEARING_NOT_SCHEDULED`), no
    sibling hearing of the same case may already be `HELD`
    (`ERR_HEARING_ALREADY_HELD`), the hearing must have a `notice_published_at`
    that is not null (`ERR_NOTICE_NOT_PUBLISHED`), the logical clock must have
    reached `notice_published_at` advanced by the statute's `notice_min_days`
    days (`ERR_NOTICE_WINDOW_NOT_SATISFIED`), and the clock must have reached
    the hearing's own `scheduled_start_at` (`ERR_HEARING_NOT_STARTED`)."

    Design: Corner/state_machines/holding_a_hearing_before_the_notice_window_elapses_is_rejected
    """
    ctx = fixtures.setup_certified_case(api)
    fixtures.setup_adopted_plan(api, ctx)
    municipality_id = ctx["municipality"]["id"]
    clerk = make_city_clerk_headers(municipality_id)

    # The hearing sits nineteen days after the notice, so its own
    # `scheduled_start_at` precondition is satisfied while the statute's
    # thirty-day notice window is not.
    fixtures.schedule_hearing(
        api,
        ctx,
        scheduled_start_at=_EARLY_HEARING_START_AT,
        scheduled_end_at=_EARLY_HEARING_END_AT,
    )
    notice = fixtures.publish_notice(api, ctx)
    hearing_id = ctx["hearing"]["id"]

    fixtures.set_clock(api, _EARLY_HEARING_START_AT)
    validate_error(api.hold_hearing(clerk, hearing_id), ERR_NOTICE_WINDOW_NOT_SATISFIED)

    hearing = fixtures.read_hearing(api, municipality_id, hearing_id)
    assert hearing["hearing_status"] == "SCHEDULED"
    assert hearing["held_at"] is None
    assert hearing["protest_opens_at"] is None
    # PRD §3.6 mirrors the notice's `published_at` onto the hearing, and notice
    # was published while the clock still read its startup value (PRD §2.4).
    assert _same_instant(hearing["notice_published_at"], notice["published_at"])
    assert _same_instant(hearing["notice_published_at"], constants.CLOCK_STARTUP_UTC)

    case = fixtures.read_case(api, municipality_id, ctx["case"]["id"])
    assert case["status"] == "HEARING_NOTICED"
    assert case["hearing_held_at"] is None


# ==========================================================================
# Referendum rejection and the rescind cascade
# ==========================================================================
def test_a_rejected_referendum_denies_the_case_and_rescinds_its_plan(api):
    """PRD §3.7: "A `result` of `REJECTED` sets `referendum_result` to
    `REJECTED` and advances the case `REFERENDUM_PENDING → DENIED`, which is
    terminal and triggers the rescind cascade in full: every parcel in
    `PENDING_ANNEX` moves to `EXCLUDED`, the `ADOPTED` plan moves to
    `RESCINDED`, every commitment of that plan in `DRAFT`, `ACTIVE` or
    `FULFILLED` moves to `VOIDED`, each voided commitment's `timeline_days` is
    released from its provider's `encumbered_capacity_days`, and the plan's
    `committed_cost_cents` and `covered_service_types` are recomputed with
    `service_readiness` returning to `PENDING`."

    Design: Corner/state_machines/referendum_rejection_runs_the_full_denial_cascade
    """
    # The statute makes the referendum method require ratification, so ordinance
    # adoption branches to REFERENDUM_PENDING rather than ORDINANCE_ADOPTED.
    ctx = fixtures.setup_case_ready_for_ordinance(
        api,
        method="REFERENDUM",
        statute={
            "authorized_methods": ["REFERENDUM"],
            "referendum_required_methods": ["REFERENDUM"],
            "required_service_types": ["POLICE"],
        },
        provider={"service_types": ["POLICE"], "concurrent_project_capacity": 1},
    )
    municipality_id = ctx["municipality"]["id"]
    clerk = make_city_clerk_headers(municipality_id)
    commitment_id = ctx["commitments"]["POLICE"]["id"]

    pending = fixtures.adopt_ordinance(api, ctx)
    assert pending["status"] == "REFERENDUM_PENDING"
    assert pending["referendum_result"] == "NOT_HELD"
    # PRD §3.7 stamps `ordinance_adopted_at` from the logical clock in both
    # branches of adoption.
    assert _same_instant(
        pending["ordinance_adopted_at"], constants.CLOCK_AFTER_PROTEST_WINDOW
    )
    assert _parcel_status_count(api, ctx, "PENDING_ANNEX") == 4

    denied = validate_success(
        api.record_referendum(clerk, ctx["case"]["id"], "REJECTED")
    )
    assert denied["status"] == "DENIED"
    assert denied["referendum_result"] == "REJECTED"

    ctx["case"] = denied
    assert _parcel_status_count(api, ctx, "EXCLUDED") == 4
    assert _parcel_status_count(api, ctx, "PENDING_ANNEX") == 0
    for parcel in ctx["parcels"]:
        assert (
            fixtures.read_parcel(api, municipality_id, parcel["id"])["parcel_status"]
            == "EXCLUDED"
        )

    plan = fixtures.read_plan(api, municipality_id, ctx["plan"]["id"])
    assert plan["adoption_status"] == "RESCINDED"
    assert plan["service_readiness"] == "PENDING"
    assert plan["committed_cost_cents"] == 0
    assert plan["covered_service_types"] == []

    commitment = fixtures.read_commitment(api, municipality_id, commitment_id)
    assert commitment["commitment_status"] == "VOIDED"

    provider = fixtures.read_provider(api, municipality_id, ctx["provider"]["id"])
    assert provider["encumbered_capacity_days"] == 0


# ==========================================================================
# The terminal case gate
# ==========================================================================
def test_every_write_on_a_commission_denied_case_is_refused(api):
    """PRD §2.10: "Case terminality: the case reached from the target resource
    must not be in `DENIED`, `MSD_ALTERNATIVE_ADOPTED` or `DE_ANNEXED` —
    `ERR_CASE_TERMINAL` (HTTP 409). This applies to every write endpoint that
    touches a case or any of its children."

    Design: Corner/state_machines/every_write_on_a_commission_denied_case_is_rejected
    """
    ctx = fixtures.setup_case_ready_for_ordinance(
        api,
        method="INVOLUNTARY_ORDINANCE",
        statute={
            "authorized_methods": ["INVOLUNTARY_ORDINANCE"],
            "boundary_commission_required": True,
            "required_service_types": ["POLICE"],
        },
        provider={"service_types": ["POLICE"], "concurrent_project_capacity": 1},
    )
    municipality_id = ctx["municipality"]["id"]
    planner = fixtures.planner(ctx)
    clerk = make_city_clerk_headers(municipality_id)
    case_id = ctx["case"]["id"]
    commitment_id = ctx["commitments"]["POLICE"]["id"]

    # PRD §3.7: adoption under a commission statute leaves review PENDING, and
    # the commissioner's DENIED decision drives the case into the terminal state.
    adopted = fixtures.adopt_ordinance(api, ctx)
    assert adopted["status"] == "ORDINANCE_ADOPTED"
    assert adopted["commission_review_status"] == "PENDING"

    submitted = validate_success(api.submit_to_commission(planner, case_id))
    assert submitted["status"] == "COMMISSION_REVIEW"

    denied = validate_success(
        api.commission_decision(boundary_commissioner_headers(), case_id, "DENIED")
    )
    assert denied["status"] == "DENIED"
    assert denied["commission_review_status"] == "DENIED"
    ctx["case"] = denied

    # Case-level writes, including the effectuation whose submitted date would
    # otherwise satisfy the statute's IMMEDIATE rule at the current clock.
    validate_error(api.certify_territory(planner, case_id), ERR_CASE_TERMINAL)
    validate_error(api.adopt_ordinance(clerk, case_id), ERR_CASE_TERMINAL)
    validate_error(
        api.effectuate(planner, case_id, constants.EFFECTIVE_DATE_AFTER_PROTEST),
        ERR_CASE_TERMINAL,
    )
    validate_error(
        api.post_tax_roll(county_assessor_headers(), case_id), ERR_CASE_TERMINAL
    )

    # Writes that create or mutate a child of the case are gated the same way.
    validate_error(
        api.create_plan_of_services(planner, factories.plan_of_services_payload(case_id)),
        ERR_CASE_TERMINAL,
    )
    validate_error(
        api.create_parcel(
            planner, case_id, factories.parcel_payload(ctx["owners"][0]["id"])
        ),
        ERR_CASE_TERMINAL,
    )
    validate_error(
        api.create_public_hearing(
            clerk,
            factories.public_hearing_payload(
                case_id,
                municipality_id,
                scheduled_start_at="2026-11-10T10:00:00Z",
                scheduled_end_at="2026-11-10T12:00:00Z",
            ),
        ),
        ERR_CASE_TERMINAL,
    )
    # The terminal gate of PRD §2.10 outranks the commitment-state check below
    # it, so voiding the already-voided commitment reports terminality.
    validate_error(
        api.void_service_commitment(planner, commitment_id), ERR_CASE_TERMINAL
    )

    # Nothing the refused writes attempted touched the denial cascade's results.
    _, plans_meta = validate_paginated(
        api.list_plans_of_services(planner, annexation_case_id=case_id)
    )
    assert plans_meta["total_count"] == 1

    plan = fixtures.read_plan(api, municipality_id, ctx["plan"]["id"])
    assert plan["adoption_status"] == "RESCINDED"
    assert plan["service_readiness"] == "PENDING"
    assert plan["committed_cost_cents"] == 0

    commitment = fixtures.read_commitment(api, municipality_id, commitment_id)
    assert commitment["commitment_status"] == "VOIDED"

    provider = fixtures.read_provider(api, municipality_id, ctx["provider"]["id"])
    assert provider["encumbered_capacity_days"] == 0

    assert _parcel_status_count(api, ctx, "EXCLUDED") == 4
    final_case = fixtures.read_case(api, municipality_id, case_id)
    assert final_case["status"] == "DENIED"
    assert final_case["tax_roll_status"] == "NOT_TRANSFERRED"
