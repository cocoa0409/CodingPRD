"""Lifecycle loops and dependent-record cascades of the Municipal Annexation
And Boundary Adjustment API.

Four procedures are exercised here: the petition cure cycle that leaves and
then re-enters `SUFFICIENCY_REVIEW`, the two orthogonal axes of a plan of
services, the effectuation cut-over that propagates from the case down to
utility billing, and the withdrawn signature that unwinds an already-noticed
hearing.
"""
from datetime import datetime

from test_helpers import (
    assertions,
    constants,
    fixtures,
    get_success_data,
    make_property_owner_headers,
    validate_success,
)

TERRITORY_VALUE_CENTS = 100000000
PARCEL_VALUES_CENTS = [40000000, 30000000, 20000000, 10000000]


# ==========================================================================
# Local helpers
# ==========================================================================
def _as_instant(value):
    """Parse an ISO 8601 UTC instant so two readings of the logical clock can
    be compared without depending on how many fractional digits the server
    chose to print."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_instant_equals(actual, expected, field):
    assert _as_instant(actual) == _as_instant(expected), (
        f"{field}: expected {expected}, got {actual}"
    )


def _petition_certified_sufficient(api):
    """A `PETITION_MAJORITY` case whose petition carries 70,000,000 cents of a
    100,000,000-cent territory and has been certified `SUFFICIENT`."""
    ctx = fixtures.setup_certified_case(
        api,
        case={"method": "PETITION_MAJORITY"},
        parcel_values_cents=PARCEL_VALUES_CENTS,
    )
    fixtures.open_petition(api, ctx, petition_type="OWNER_MAJORITY")
    # The 40,000,000-cent and 30,000,000-cent owners sign, so the measured
    # support is 70.00% against the statutory 50.00 threshold.
    ctx["consents"] = [
        fixtures.sign_consent(api, ctx, parcel_index=0),
        fixtures.sign_consent(api, ctx, parcel_index=1),
    ]
    ctx["petition"] = get_success_data(
        api.certify_sufficiency(fixtures.clerk(ctx), ctx["petition"]["id"]), 200
    )
    fixtures.refresh_case(api, ctx)
    return ctx


def _plan_with_police_and_water_fulfilled(api):
    """A plan of services still in `DRAFT` whose POLICE and WATER commitments
    are both `FULFILLED`, so its readiness has already climbed to `READY`."""
    ctx = fixtures.setup_certified_case(
        api,
        statute={"required_service_types": ["POLICE", "WATER"]},
        provider={"service_types": ["POLICE"], "concurrent_project_capacity": 1},
    )
    municipality_id = ctx["municipality"]["id"]
    water_provider = fixtures.create_provider(
        api, municipality_id, service_types=["WATER"], concurrent_project_capacity=1
    )

    plan_at_open = fixtures.open_plan(api, ctx)

    # A 31-day police window stays inside the statutory 60-day police/fire cap,
    # and a zero committed account count fulfils the commitment on activation.
    police = fixtures.add_commitment(
        api,
        ctx,
        "POLICE",
        cost_cents=500000,
        committed_account_count=0,
        window_start_date="2026-08-01",
        window_end_date="2026-08-31",
    )
    police = fixtures.activate_commitment(api, ctx, police["id"])
    plan_after_police = fixtures.read_plan(api, municipality_id, ctx["plan"]["id"])

    water = fixtures.add_commitment(
        api,
        ctx,
        "WATER",
        service_provider_id=water_provider["id"],
        cost_cents=700000,
        committed_account_count=0,
        window_start_date="2026-09-01",
        window_end_date="2026-09-30",
    )
    water = fixtures.activate_commitment(api, ctx, water["id"])

    return {
        "ctx": ctx,
        "police_provider": ctx["provider"],
        "water_provider": water_provider,
        "police": police,
        "water": water,
        "plan_at_open": plan_at_open,
        "plan_after_police": plan_after_police,
    }


def _case_awaiting_effectuation_with_metered_accounts(api):
    """An `ORDINANCE_ADOPTED` case with four `PENDING_ANNEX` parcels, one
    outside-city WATER account and one outside-city SEWER account, and an
    `ADOPTED` plan whose WATER and SEWER commitments each promise to cut one
    account over."""
    ctx = fixtures.setup_certified_case(
        api,
        provider={"service_types": ["POLICE", "FIRE"], "concurrent_project_capacity": 2},
        parcel_values_cents=PARCEL_VALUES_CENTS,
    )
    municipality_id = ctx["municipality"]["id"]
    utilities = fixtures.create_provider(
        api,
        municipality_id,
        service_types=["WATER", "SEWER"],
        concurrent_project_capacity=2,
    )
    water_account = fixtures.add_utility_account(
        api,
        municipality_id,
        ctx["parcels"][0]["id"],
        utilities["id"],
        service_type="WATER",
        monthly_base_cents=5000,
    )
    sewer_account = fixtures.add_utility_account(
        api,
        municipality_id,
        ctx["parcels"][1]["id"],
        utilities["id"],
        service_type="SEWER",
        monthly_base_cents=4000,
    )

    fixtures.open_plan(api, ctx)
    commitments = {}
    # Police and fire are unmetered, so they promise no accounts and fulfil on
    # activation; water and sewer each promise the single account of their
    # service type and therefore stay ACTIVE until the cut-over.
    for service_type, cost_cents, provider_id, account_count in (
        ("POLICE", 500000, ctx["provider"]["id"], 0),
        ("FIRE", 400000, ctx["provider"]["id"], 0),
        ("WATER", 900000, utilities["id"], 1),
        ("SEWER", 700000, utilities["id"], 1),
    ):
        drafted = fixtures.add_commitment(
            api,
            ctx,
            service_type,
            service_provider_id=provider_id,
            cost_cents=cost_cents,
            committed_account_count=account_count,
        )
        commitments[service_type] = fixtures.activate_commitment(api, ctx, drafted["id"])
    ctx["commitments"] = commitments
    ctx["plan"] = get_success_data(
        api.adopt_plan_of_services(fixtures.clerk(ctx), ctx["plan"]["id"]), 200
    )

    fixtures.setup_hearing_noticed(api, ctx)
    fixtures.setup_hearing_held(api, ctx)
    fixtures.close_protest_period(api, ctx)
    fixtures.setup_finalized_analysis(api, ctx)
    fixtures.adopt_ordinance(api, ctx)

    return {
        "ctx": ctx,
        "utilities": utilities,
        "water_account": water_account,
        "sewer_account": sewer_account,
        "plan_before_cutover": fixtures.read_plan(api, municipality_id, ctx["plan"]["id"]),
    }


def _noticed_hearing_over_sufficient_petition(api):
    """A `HEARING_NOTICED` case on the petition path: a petition certified
    `SUFFICIENT` at 70.00%, an `ADOPTED` plan, a `SCHEDULED` hearing and a
    `PUBLISHED` newspaper notice."""
    ctx = fixtures.setup_certified_case(
        api,
        statute={"required_service_types": ["POLICE"]},
        case={"method": "PETITION_MAJORITY"},
        parcel_values_cents=PARCEL_VALUES_CENTS,
    )
    fixtures.open_petition(api, ctx, petition_type="OWNER_MAJORITY")
    ctx["consents"] = [
        fixtures.sign_consent(api, ctx, parcel_index=0),
        fixtures.sign_consent(api, ctx, parcel_index=1),
    ]
    ctx["petition"] = get_success_data(
        api.certify_sufficiency(fixtures.clerk(ctx), ctx["petition"]["id"]), 200
    )
    fixtures.refresh_case(api, ctx)
    fixtures.setup_adopted_plan(api, ctx)
    fixtures.setup_hearing_noticed(api, ctx)
    return ctx


# ==========================================================================
# The petition cure cycle
# ==========================================================================
def test_withdrawn_signature_walks_the_case_back_out_of_sufficiency_review(api):
    """PRD §3.3: "If the petition had been `SUFFICIENT` and no longer meets its
    threshold, the supersession cascade of §2.9 runs in full: the petition drops
    to `INSUFFICIENT`, the case reverts to `PETITION_CIRCULATING` — from
    `SUFFICIENCY_REVIEW` if the hearing had not yet been noticed, and equally
    from `HEARING_NOTICED` if it had — every hearing of that case in
    `SCHEDULED` is `VACATED`, every `PUBLISHED` notice of those hearings becomes
    `SUPERSEDED`, each such hearing's `notice_published_at` reverts to null so
    the chamber slot is freed and the notice clock must restart, and the case's
    `version` increments."

    Design: Difficulty/non_linear_state_machine/petition_cure_cycle_revisits_sufficiency_review_after_insufficient
    """
    ctx = _petition_certified_sufficient(api)
    municipality_id = ctx["municipality"]["id"]

    assert ctx["petition"]["sufficiency_status"] == "SUFFICIENT"
    assertions.assert_numeric_equals(
        ctx["petition"]["signature_value_pct"],
        assertions.expected_weight_pct(70000000, TERRITORY_VALUE_CENTS),
        "signature_value_pct",
    )
    assert ctx["case"]["status"] == "SUFFICIENCY_REVIEW"

    # Pulling the 30,000,000-cent signature leaves 40,000,000 cents of qualified
    # value, which is below the statute's 50.00 signature threshold.
    withdrawn = validate_success(
        api.withdraw_consent(
            make_property_owner_headers(ctx["owners"][1]["id"]),
            ctx["consents"][1]["id"],
        )
    )
    assert withdrawn["consent_status"] == "WITHDRAWN"

    petition = fixtures.read_petition(api, municipality_id, ctx["petition"]["id"])
    assert petition["sufficiency_status"] == "INSUFFICIENT"
    assert petition["qualified_signature_assessed_value_cents"] == 40000000
    assert petition["qualified_signature_owner_count"] == 1
    assertions.assert_numeric_equals(
        petition["signature_value_pct"],
        assertions.expected_weight_pct(40000000, TERRITORY_VALUE_CENTS),
        "signature_value_pct",
    )

    case = fixtures.read_case(api, municipality_id, ctx["case"]["id"])
    assert case["status"] == "PETITION_CIRCULATING"


def test_cured_petition_re_enters_sufficiency_review_at_a_new_percentage(api):
    """PRD §3.3: "When the threshold is met the petition moves to `SUFFICIENT`
    and the case advances to `SUFFICIENCY_REVIEW`; this holds both for the first
    certification out of `CIRCULATING` and for the re-certification limb out of
    `INSUFFICIENT` after new signatures have arrived, and both limbs stamp
    `qualified_signature_assessed_value_cents`,
    `qualified_signature_owner_count`, `signature_value_pct` and
    `signature_owner_pct` identically."

    Design: Difficulty/non_linear_state_machine/petition_cure_cycle_revisits_sufficiency_review_after_insufficient
    """
    ctx = _petition_certified_sufficient(api)
    municipality_id = ctx["municipality"]["id"]

    validate_success(
        api.withdraw_consent(
            make_property_owner_headers(ctx["owners"][1]["id"]),
            ctx["consents"][1]["id"],
        )
    )
    assert (
        fixtures.read_petition(api, municipality_id, ctx["petition"]["id"])[
            "sufficiency_status"
        ]
        == "INSUFFICIENT"
    )

    # The replacement signature on the 20,000,000-cent parcel restores
    # 60,000,000 cents of qualified value across two distinct owners.
    fixtures.sign_consent(api, ctx, parcel_index=2)

    recertified = validate_success(
        api.certify_sufficiency(fixtures.clerk(ctx), ctx["petition"]["id"])
    )
    assert recertified["sufficiency_status"] == "SUFFICIENT"

    petition = fixtures.read_petition(api, municipality_id, ctx["petition"]["id"])
    assert petition["sufficiency_status"] == "SUFFICIENT"
    assert petition["qualified_signature_assessed_value_cents"] == 60000000
    assert petition["qualified_signature_owner_count"] == 2
    assertions.assert_numeric_equals(
        petition["signature_value_pct"],
        assertions.expected_weight_pct(60000000, TERRITORY_VALUE_CENTS),
        "signature_value_pct",
    )

    case = fixtures.read_case(api, municipality_id, ctx["case"]["id"])
    assert case["status"] == "SUFFICIENCY_REVIEW"


# ==========================================================================
# The two axes of a plan of services
# ==========================================================================
def test_plan_readiness_reaches_ready_while_the_plan_is_still_draft(api):
    """PRD §3.5: "Neither axis gates the other: a plan can be `ADOPTED` while
    still `PENDING`, and `READY` while still `DRAFT`."

    Design: Difficulty/non_linear_state_machine/plan_adoption_and_readiness_dimensions_move_independently
    """
    built = _plan_with_police_and_water_fulfilled(api)
    ctx = built["ctx"]
    municipality_id = ctx["municipality"]["id"]

    assert built["plan_at_open"]["adoption_status"] == "DRAFT"
    assert built["plan_at_open"]["service_readiness"] == "PENDING"
    assert built["plan_at_open"]["committed_cost_cents"] == 0
    assert built["plan_at_open"]["covered_service_types"] == []

    # POLICE is fulfilled but WATER is still uncovered, so only one of the two
    # required service types has been promised.
    assert built["plan_after_police"]["adoption_status"] == "DRAFT"
    assert built["plan_after_police"]["service_readiness"] == "PARTIAL"

    plan = fixtures.read_plan(api, municipality_id, ctx["plan"]["id"])
    assert plan["adoption_status"] == "DRAFT"
    assert plan["service_readiness"] == "READY"
    assert plan["covered_service_types"] == assertions.ordered_service_types(
        ["POLICE", "WATER"]
    )
    assert plan["committed_cost_cents"] == 1200000

    adopted = validate_success(
        api.adopt_plan_of_services(fixtures.clerk(ctx), ctx["plan"]["id"])
    )
    assert adopted["adoption_status"] == "ADOPTED"
    _assert_instant_equals(
        adopted["adopted_at"], constants.CLOCK_STARTUP_UTC, "adopted_at"
    )

    # Moving the adoption axis leaves the derived readiness axis untouched.
    plan = fixtures.read_plan(api, municipality_id, ctx["plan"]["id"])
    assert plan["adoption_status"] == "ADOPTED"
    assert plan["service_readiness"] == "READY"


def test_voiding_a_commitment_drops_readiness_while_adoption_stays_adopted(api):
    """PRD §3.5: "A first activation therefore typically drives `PENDING →
    PARTIAL`, a last fulfilment drives `PARTIAL → READY`, and voiding work walks
    the same ladder back down — `READY → PARTIAL` when a fulfilled commitment is
    removed, and `PARTIAL → PENDING` when the void removes the last commitment
    in `ACTIVE` or `FULFILLED`."

    Design: Difficulty/non_linear_state_machine/plan_adoption_and_readiness_dimensions_move_independently
    """
    built = _plan_with_police_and_water_fulfilled(api)
    ctx = built["ctx"]
    municipality_id = ctx["municipality"]["id"]

    adopted = get_success_data(
        api.adopt_plan_of_services(fixtures.clerk(ctx), ctx["plan"]["id"]), 200
    )
    assert adopted["adoption_status"] == "ADOPTED"
    assert adopted["service_readiness"] == "READY"

    voided = validate_success(
        api.void_service_commitment(fixtures.planner(ctx), built["water"]["id"])
    )
    assert voided["commitment_status"] == "VOIDED"

    plan = fixtures.read_plan(api, municipality_id, ctx["plan"]["id"])
    assert plan["adoption_status"] == "ADOPTED"
    _assert_instant_equals(plan["adopted_at"], adopted["adopted_at"], "adopted_at")
    _assert_instant_equals(
        plan["adopted_at"], constants.CLOCK_STARTUP_UTC, "adopted_at"
    )
    assert plan["service_readiness"] == "PARTIAL"
    assert plan["covered_service_types"] == assertions.ordered_service_types(["POLICE"])
    assert plan["committed_cost_cents"] == 500000

    water_commitment = fixtures.read_commitment(
        api, municipality_id, built["water"]["id"]
    )
    assert water_commitment["commitment_status"] == "VOIDED"
    police_commitment = fixtures.read_commitment(
        api, municipality_id, built["police"]["id"]
    )
    assert police_commitment["commitment_status"] == "FULFILLED"

    # The voided water window releases its days; the fulfilled police window,
    # 2026-08-01 through 2026-08-31 inclusive, keeps encumbering 31 days.
    water_provider = fixtures.read_provider(
        api, municipality_id, built["water_provider"]["id"]
    )
    assert water_provider["encumbered_capacity_days"] == 0
    police_provider = fixtures.read_provider(
        api, municipality_id, built["police_provider"]["id"]
    )
    assert police_provider["encumbered_capacity_days"] == assertions.inclusive_day_count(
        "2026-08-01", "2026-08-31"
    )


# ==========================================================================
# The effectuation cut-over
# ==========================================================================
def test_effectuation_incorporates_parcels_and_drops_the_outside_city_surcharge(api):
    """PRD §3.8: "Because the case became `EFFECTIVE`, every parcel of the case
    in `PENDING_ANNEX` moves to `INCORPORATED`; a de-annexation case owns no
    parcels of its own, so this link is a no-op for it and the predecessor
    cascade of §3.9 runs instead. Because those parcels became `INCORPORATED`,
    each of their utility accounts in `OUTSIDE_CITY` moves to
    `INSIDE_CITY_PENDING_TRANSITION`, its `rate_schedule` moves from
    `OUTSIDE_CITY_SURCHARGE` to `INSIDE_CITY`, and its `effective_monthly_cents`
    is recomputed with the surcharge dropped."

    Design: Difficulty/transitive_cascade/effectuate_six_link_cutover_annexes_parcels_accounts_and_plan
    """
    built = _case_awaiting_effectuation_with_metered_accounts(api)
    ctx = built["ctx"]
    municipality_id = ctx["municipality"]["id"]
    surcharge_pct = ctx["municipality"]["utility_outside_surcharge_pct"]

    for account, base_cents in (
        (built["water_account"], 5000),
        (built["sewer_account"], 4000),
    ):
        assert account["account_status"] == "OUTSIDE_CITY"
        assert account["rate_schedule"] == "OUTSIDE_CITY_SURCHARGE"
        assert account["effective_monthly_cents"] == (
            assertions.expected_outside_city_monthly_cents(base_cents, surcharge_pct)
        )
    for parcel in ctx["parcels"]:
        assert (
            fixtures.read_parcel(api, municipality_id, parcel["id"])["parcel_status"]
            == "PENDING_ANNEX"
        )

    effectuated = validate_success(
        api.effectuate(
            fixtures.planner(ctx),
            ctx["case"]["id"],
            constants.EFFECTIVE_DATE_AFTER_PROTEST,
        )
    )
    assert effectuated["status"] == "EFFECTIVE"

    case = fixtures.read_case(api, municipality_id, ctx["case"]["id"])
    assert case["status"] == "EFFECTIVE"
    assert case["effective_date"] == constants.EFFECTIVE_DATE_AFTER_PROTEST

    for parcel in ctx["parcels"]:
        assert (
            fixtures.read_parcel(api, municipality_id, parcel["id"])["parcel_status"]
            == "INCORPORATED"
        )

    # Inside the corporate limits the schedule carries no surcharge at all, so
    # the effective monthly charge falls back to the declared base.
    for account, base_cents in (
        (built["water_account"], 5000),
        (built["sewer_account"], 4000),
    ):
        cut_over = fixtures.read_account(api, municipality_id, account["id"])
        assert cut_over["rate_schedule"] == "INSIDE_CITY"
        assert cut_over["effective_monthly_cents"] == base_cents


def test_effectuation_fulfils_metered_commitments_and_activates_the_accounts(api):
    """PRD §3.8: "Because those accounts entered
    `INSIDE_CITY_PENDING_TRANSITION`, for each of them the commitment on the
    case's `ADOPTED` plan that is in `ACTIVE` and matches both the account's
    `service_type` and its `service_provider_id` has its
    `activated_account_count` incremented by one; once `activated_account_count`
    reaches or exceeds that commitment's `committed_account_count`, the
    commitment advances `ACTIVE → FULFILLED`. Because commitments became
    `FULFILLED`, the plan's `covered_service_types` and `service_readiness` are
    recomputed by the readiness rule of §3.5. And because `service_readiness`
    reached `READY`, every utility account of the case still in
    `INSIDE_CITY_PENDING_TRANSITION` whose service type's commitment is
    `FULFILLED` advances to `INSIDE_CITY_ACTIVE`."

    Design: Difficulty/transitive_cascade/effectuate_six_link_cutover_annexes_parcels_accounts_and_plan
    """
    built = _case_awaiting_effectuation_with_metered_accounts(api)
    ctx = built["ctx"]
    municipality_id = ctx["municipality"]["id"]

    # All four service types are covered, but the two metered commitments still
    # await their accounts, so readiness sits short of READY.
    assert built["plan_before_cutover"]["service_readiness"] == "PARTIAL"
    assert built["plan_before_cutover"]["committed_cost_cents"] == 2500000
    for service_type in ("WATER", "SEWER"):
        pending = fixtures.read_commitment(
            api, municipality_id, ctx["commitments"][service_type]["id"]
        )
        assert pending["commitment_status"] == "ACTIVE"
        assert pending["activated_account_count"] == 0
        assert pending["committed_account_count"] == 1

    validate_success(
        api.effectuate(
            fixtures.planner(ctx),
            ctx["case"]["id"],
            constants.EFFECTIVE_DATE_AFTER_PROTEST,
        )
    )

    for service_type in ("WATER", "SEWER"):
        fulfilled = fixtures.read_commitment(
            api, municipality_id, ctx["commitments"][service_type]["id"]
        )
        assert fulfilled["activated_account_count"] == 1
        assert fulfilled["commitment_status"] == "FULFILLED"

    plan = fixtures.read_plan(api, municipality_id, ctx["plan"]["id"])
    assert plan["service_readiness"] == "READY"
    assert plan["committed_cost_cents"] == 2500000
    assert plan["covered_service_types"] == assertions.ordered_service_types(
        ["POLICE", "FIRE", "WATER", "SEWER"]
    )

    for account in (built["water_account"], built["sewer_account"]):
        assert (
            fixtures.read_account(api, municipality_id, account["id"])["account_status"]
            == "INSIDE_CITY_ACTIVE"
        )


# ==========================================================================
# The consent withdrawal that unwinds a noticed hearing
# ==========================================================================
def test_withdrawal_blanks_the_signature_and_reverts_the_noticed_case(api):
    """PRD §3.3: "If the petition had been `SUFFICIENT` and no longer meets its
    threshold, the supersession cascade of §2.9 runs in full: the petition drops
    to `INSUFFICIENT`, the case reverts to `PETITION_CIRCULATING` — from
    `SUFFICIENCY_REVIEW` if the hearing had not yet been noticed, and equally
    from `HEARING_NOTICED` if it had — every hearing of that case in
    `SCHEDULED` is `VACATED`, every `PUBLISHED` notice of those hearings becomes
    `SUPERSEDED`, each such hearing's `notice_published_at` reverts to null so
    the chamber slot is freed and the notice clock must restart, and the case's
    `version` increments."

    Design: Difficulty/transitive_cascade/consent_withdrawal_five_link_unwind_vacates_noticed_hearing
    """
    ctx = _noticed_hearing_over_sufficient_petition(api)
    municipality_id = ctx["municipality"]["id"]

    assert ctx["case"]["status"] == "HEARING_NOTICED"
    assertions.assert_numeric_equals(
        ctx["petition"]["signature_value_pct"],
        assertions.expected_weight_pct(70000000, TERRITORY_VALUE_CENTS),
        "signature_value_pct",
    )

    validate_success(
        api.withdraw_consent(
            make_property_owner_headers(ctx["owners"][1]["id"]),
            ctx["consents"][1]["id"],
        )
    )

    consent = get_success_data(
        api.get_consent(fixtures.clerk(ctx), ctx["consents"][1]["id"]), 200
    )
    assert consent["consent_status"] == "WITHDRAWN"
    assert consent["qualified_value_cents"] == 0
    _assert_instant_equals(
        consent["withdrawn_at"], constants.CLOCK_STARTUP_UTC, "withdrawn_at"
    )

    petition = fixtures.read_petition(api, municipality_id, ctx["petition"]["id"])
    assert petition["sufficiency_status"] == "INSUFFICIENT"
    assert petition["qualified_signature_assessed_value_cents"] == 40000000
    assert petition["qualified_signature_owner_count"] == 1
    assertions.assert_numeric_equals(
        petition["signature_value_pct"],
        assertions.expected_weight_pct(40000000, TERRITORY_VALUE_CENTS),
        "signature_value_pct",
    )

    case = fixtures.read_case(api, municipality_id, ctx["case"]["id"])
    assert case["status"] == "PETITION_CIRCULATING"


def test_withdrawal_vacates_the_hearing_and_supersedes_its_notice(api):
    """PRD §2.9: "The **supersession cascade** fires when a withdrawn consent
    drops a petition below its threshold: the petition falls from `SUFFICIENT`
    to `INSUFFICIENT`, the case reverts to `PETITION_CIRCULATING`, every hearing
    of that case still in `SCHEDULED` moves to `VACATED`, every notice of those
    hearings still in `PUBLISHED` moves to `SUPERSEDED`, and each affected
    hearing's `notice_published_at` is set back to null so that the council
    chamber slot is released and the notice clock must be restarted."

    Design: Difficulty/transitive_cascade/consent_withdrawal_five_link_unwind_vacates_noticed_hearing
    """
    ctx = _noticed_hearing_over_sufficient_petition(api)
    municipality_id = ctx["municipality"]["id"]
    notice = ctx["notices"][0]

    hearing = fixtures.read_hearing(api, municipality_id, ctx["hearing"]["id"])
    assert hearing["hearing_status"] == "SCHEDULED"
    _assert_instant_equals(
        hearing["notice_published_at"],
        constants.CLOCK_STARTUP_UTC,
        "notice_published_at",
    )
    assert (
        get_success_data(
            api.get_notice_publication(fixtures.clerk(ctx), notice["id"]), 200
        )["notice_status"]
        == "PUBLISHED"
    )

    validate_success(
        api.withdraw_consent(
            make_property_owner_headers(ctx["owners"][1]["id"]),
            ctx["consents"][1]["id"],
        )
    )

    # Losing the 30,000,000-cent signature takes the petition to 40.00%, below
    # the statutory 50.00 threshold, so the hearing track unwinds behind it.
    case = fixtures.read_case(api, municipality_id, ctx["case"]["id"])
    assert case["status"] == "PETITION_CIRCULATING"

    vacated = fixtures.read_hearing(api, municipality_id, ctx["hearing"]["id"])
    assert vacated["hearing_status"] == "VACATED"
    assert vacated["notice_published_at"] is None

    superseded = get_success_data(
        api.get_notice_publication(fixtures.clerk(ctx), notice["id"]), 200
    )
    assert superseded["notice_status"] == "SUPERSEDED"
