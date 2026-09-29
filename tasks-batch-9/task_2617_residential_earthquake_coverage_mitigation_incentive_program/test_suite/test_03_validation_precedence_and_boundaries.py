"""Ladder precedence and threshold arithmetic for the residual earthquake program.

Two families of contract detail are exercised here. The first is the ordered
validation ladder: when one request offends several rules at once, the offence
with the smallest priority number is the only one reported, so a conflicted
grant reserver hears about segregation of duties rather than about a tier cap, a
loss filed against a still-monitored earthquake hears about the undeclared event
rather than about the policy term, and a booking for a suspended contractor
hears about certification rather than about the contractor's calendar. Each such
case is proved twice over: the low rung answers first, and clearing that rung
alone then exposes the higher rung on a byte-identical request, showing the later
check was skipped rather than merely outvoted.

The second family is threshold arithmetic on the cent and on the year: the
high-limit load that attaches at a Coverage A limit of exactly 75,000,000 cents
and lands on an exact half-cent that must round away from zero, the pre-code age
load that still applies to a 1979 vintage and releases for a 1980 one, the
payment that settles a claim on equality but is refused one cent beyond, and the
take-up rate that sits exactly on the twenty-five percent floor without
triggering a compliance downgrade while one further offer takes it below.
"""
from prd_bench_local_runner.testing import build_user_headers, validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    CLAIM_ADJUSTER_HEADERS,
    FIELD_INSPECTOR_HEADERS,
    GRANT_REVIEWER_HEADERS,
    PROGRAM_ADMIN_ALT_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    UserRole,
    constants,
    factories,
    fixtures,
)
from test_helpers.test_users import (
    GRANT_REVIEWER_USER_ID,
    make_insurer_headers,
    make_policyholder_headers,
)

# ─── Shared building blocks ───────────────────────────────────────────────────

CRIPPLE_WALL_DWELLING = {
    "county_hazard_tier": "TIER_2",
    "soil_class": "SOFT",
    "structure_type": "WOOD_FRAME_CRIPPLE_WALL",
    "year_built": 1955,
    "dwelling_limit_cents": 50000000,
}

WIDE_SUBLIMIT_POLICY = {
    "deductible_pct": 15,
    "contents_sublimit_cents": 10000000,
    "loss_of_use_sublimit_cents": 5000000,
}


def _bound_policy_on_new_dwelling(api, insurer, holder, dwelling_overrides, **policy_overrides):
    """A fresh dwelling for an existing household, quoted and bound with one insurer."""
    dwelling = fixtures.create_dwelling(api, holder["id"], **dwelling_overrides)
    return fixtures.setup_bound_policy(
        api,
        parties={"insurer": insurer, "policyholder": holder, "dwelling": dwelling},
        **policy_overrides,
    )


def _quote_on_new_dwelling(api, insurer, holder, dwelling_overrides, **policy_overrides):
    """A quote produced against a freshly accepted offer on a brand-new dwelling."""
    dwelling = fixtures.create_dwelling(api, holder["id"], **dwelling_overrides)
    ctx = fixtures.setup_accepted_offer(
        api, parties={"insurer": insurer, "policyholder": holder, "dwelling": dwelling}
    )
    return validate_success(
        api.create_policy(
            factories.create_policy_payload(
                dwelling["id"], insurer["id"], ctx["offer"]["id"], **policy_overrides
            ),
            make_insurer_headers(insurer["id"]),
        ),
        201,
    )


def _answer_a_fresh_offer(api, insurer, holder, response, decline_documented=None):
    """Record a mandatory offer on a new dwelling and have the household answer it."""
    dwelling = fixtures.create_dwelling(api, holder["id"])
    ctx = fixtures.setup_pending_offer(
        api, parties={"insurer": insurer, "policyholder": holder, "dwelling": dwelling}
    )
    payload = factories.respond_to_offer_payload(response)
    if decline_documented is not None:
        payload["decline_documented"] = decline_documented
    return validate_success(
        api.respond_to_offer(
            ctx["offer"]["id"], payload, make_policyholder_headers(holder["id"])
        )
    )


def _two_tier_mid_awards_against_one_cycle(api):
    """Two 300,000-cent TIER_MID awards on one 1,000,000-cent cycle.

    The first award is already reserved, so the TIER_MID bucket cap of 400,000
    has only 100,000 of headroom left and the shared TIER_ANY fallback cap of
    250,000 cannot hold a 300,000 award either, while the pool as a whole is
    barely touched. The second award is approved by the reviewer identity rev-1
    and left waiting for its money.
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    insurer = fixtures.create_insurer(api)
    holder = fixtures.create_policyholder(api)
    cycle = fixtures.create_grant_cycle(
        api, program_track="BRACE_AND_BOLT", total_pool_cents=1000000
    )
    grant_terms = {
        "income_tier": "TIER_MID",
        "project_cost_estimate_cents": 400000,
        "requested_scope": "CRIPPLE_WALL_BRACING",
    }

    first = _bound_policy_on_new_dwelling(
        api, insurer, holder, CRIPPLE_WALL_DWELLING, **WIDE_SUBLIMIT_POLICY
    )
    first = fixtures.setup_reserved_grant(api, ctx=first, cycle=cycle, **grant_terms)
    assert first["grant"]["approved_amount_cents"] == 300000
    assert first["grant"]["funded_from_bucket"] == "TIER_MID"

    second = _bound_policy_on_new_dwelling(
        api, insurer, holder, CRIPPLE_WALL_DWELLING, **WIDE_SUBLIMIT_POLICY
    )
    second = fixtures.setup_approved_grant(
        api, ctx=second, cycle=cycle, reviewer_headers=GRANT_REVIEWER_HEADERS, **grant_terms
    )
    assert second["grant"]["approved_amount_cents"] == 300000
    assert second["grant"]["approved_by_user_id"] == GRANT_REVIEWER_USER_ID

    ledger = validate_success(api.get_grant_cycle(cycle["id"], PROGRAM_ADMIN_HEADERS))
    assert ledger["reserved_cents"] == 300000
    return {"cycle": ledger, "grant": second["grant"]}


def test_01_approving_reviewer_may_not_reserve_even_when_the_bucket_is_full(api):
    """PRD §5: "Every failure answers with the error envelope of section 2.2 and exactly one `error_id` from the catalogue below, selected by the priority ladder of section 2.8: when a request offends several rules at once, the offence with the smallest priority number is the one reported, and no other error is disclosed in the same response."

    PRD §2.8: "rung 7, the `X-User-ID` reserving cycle funds must differ from the grant's `approved_by_user_id`, otherwise `ERR_SOD_GRANT_REVIEWER_CONFLICT` (403)"

    PRD §2.8: "Rung 72: the grant's own income-tier bucket, or the shared fallback bucket, must have room for the award, otherwise `ERR_GRANT_TIER_CAP_EXHAUSTED` (409) on fund reservation."

    Design: Difficulty/priority_pair_validation_conflict/sod_reviewer_conflict_outranks_tier_cap_exhausted_on_reserve_funds
    """
    ctx = _two_tier_mid_awards_against_one_cycle(api)
    cycle, grant = ctx["cycle"], ctx["grant"]

    conflicted = build_user_headers(GRANT_REVIEWER_USER_ID, UserRole.PROGRAM_ADMIN.value)
    refused = api.reserve_grant_funds(
        grant["id"], factories.reserve_funds_payload(cycle["version"]), conflicted
    )
    validate_error(refused, ApiErrorId.SOD_GRANT_REVIEWER_CONFLICT)

    still_waiting = validate_success(api.get_retrofit_grant(grant["id"], PROGRAM_ADMIN_HEADERS))
    assert still_waiting["status"] == "APPROVED"
    assert still_waiting["funded_from_bucket"] == "NONE"

    untouched = validate_success(api.get_grant_cycle(cycle["id"], PROGRAM_ADMIN_HEADERS))
    assert untouched["reserved_cents"] == 300000
    assert untouched["uncommitted_cents"] == 700000
    assert untouched["version"] == cycle["version"]


def test_02_the_tier_cap_only_answers_once_a_different_hand_reserves(api):
    """PRD §2.10: "These three conflicts sit at rungs 7, 8 and 9 of the ladder respectively, above every state and shape check, so a conflicted operator is told about the conflict rather than about the target's state."

    PRD §2.8: "rung 7, the `X-User-ID` reserving cycle funds must differ from the grant's `approved_by_user_id`, otherwise `ERR_SOD_GRANT_REVIEWER_CONFLICT` (403)"

    PRD §2.8: "Rung 72: the grant's own income-tier bucket, or the shared fallback bucket, must have room for the award, otherwise `ERR_GRANT_TIER_CAP_EXHAUSTED` (409) on fund reservation."

    PRD §3.5: "Step two: otherwise, provided the applicant's tier is not already `TIER_ANY`, if the `TIER_ANY` bucket's usage plus this award is no greater than the `TIER_ANY` cap, the award draws from `TIER_ANY` — that shared bucket is the single fallback, and there is no further cascade."

    Design: Difficulty/priority_pair_validation_conflict/sod_reviewer_conflict_outranks_tier_cap_exhausted_on_reserve_funds
    """
    ctx = _two_tier_mid_awards_against_one_cycle(api)
    cycle, grant = ctx["cycle"], ctx["grant"]
    payload = factories.reserve_funds_payload(cycle["version"])

    conflicted = build_user_headers(GRANT_REVIEWER_USER_ID, UserRole.PROGRAM_ADMIN.value)
    validate_error(
        api.reserve_grant_funds(grant["id"], payload, conflicted),
        ApiErrorId.SOD_GRANT_REVIEWER_CONFLICT,
    )

    unconflicted = api.reserve_grant_funds(grant["id"], payload, PROGRAM_ADMIN_ALT_HEADERS)
    validate_error(unconflicted, ApiErrorId.GRANT_TIER_CAP_EXHAUSTED)

    still_waiting = validate_success(api.get_retrofit_grant(grant["id"], PROGRAM_ADMIN_HEADERS))
    assert still_waiting["status"] == "APPROVED"
    assert still_waiting["funded_from_bucket"] == "NONE"

    untouched = validate_success(api.get_grant_cycle(cycle["id"], PROGRAM_ADMIN_HEADERS))
    assert untouched["reserved_cents"] == 300000
    assert untouched["uncommitted_cents"] == 700000
    assert untouched["version"] == cycle["version"]


def _monitored_quake_that_predates_the_term(api):
    """An in-force term starting 2026-08-01 and a still-monitored quake from 2026-07-15.

    The 2026 treaty year carries an active layer, so the reinsurance gate cannot
    fire, and the tremor is well above the declaration floor, so declaring it is
    a single administrative act away.
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_bound_policy(api)
    assert ctx["policy"]["lifecycle_status"] == "ACTIVE"
    assert ctx["policy"]["effective_at"].startswith("2026-08-01T00:00:00")

    ctx["layer"] = fixtures.create_reinsurance_layer(api)
    ctx["event"] = fixtures.create_catastrophe_event(
        api, magnitude=6.0, occurred_at="2026-07-15T00:00:00Z"
    )
    assert ctx["event"]["status"] == "MONITORING"
    return ctx


def test_03_loss_on_a_monitored_quake_is_refused_for_the_undeclared_event_first(api):
    """PRD §2.8: "Rung 28: an event must be `DECLARED`, `LOSS_AGGREGATION` or `CAPACITY_EXHAUSTED` for a claim to be filed against it, since an event still `MONITORING` accepts no claims, otherwise `ERR_EVENT_NOT_DECLARED` (409)."

    PRD §2.8: "Rung 69: the event must have struck inside the policy term, meaning its `occurred_at` is at or after the policy's `effective_at` and strictly before the policy's `expires_at`, otherwise `ERR_POLICY_NOT_IN_FORCE_AT_EVENT` (409)."

    PRD §5: "Every failure answers with the error envelope of section 2.2 and exactly one `error_id` from the catalogue below, selected by the priority ladder of section 2.8: when a request offends several rules at once, the offence with the smallest priority number is the one reported, and no other error is disclosed in the same response."

    Design: Difficulty/priority_pair_validation_conflict/event_not_declared_outranks_policy_not_in_force_at_event_on_fnol
    """
    ctx = _monitored_quake_that_predates_the_term(api)

    refused = api.create_claim(
        factories.create_claim_payload(
            ctx["policy"]["id"],
            ctx["event"]["id"],
            ctx["event"]["version"],
            structural_damage_cents=9000000,
        ),
        CLAIM_ADJUSTER_HEADERS,
    )
    validate_error(refused, ApiErrorId.EVENT_NOT_DECLARED)

    quake = validate_success(api.get_catastrophe_event(ctx["event"]["id"], PROGRAM_ADMIN_HEADERS))
    assert quake["status"] == "MONITORING"
    assert quake["claim_count"] == 0
    assert quake["aggregate_incurred_cents"] == 0


def test_04_declaring_the_quake_exposes_the_out_of_term_loss_rather_than_admitting_it(api):
    """PRD §3.7: "Declaring the event moves `MONITORING → DECLARED` and is what opens claim intake."

    PRD §2.8: "Rung 28: an event must be `DECLARED`, `LOSS_AGGREGATION` or `CAPACITY_EXHAUSTED` for a claim to be filed against it, since an event still `MONITORING` accepts no claims, otherwise `ERR_EVENT_NOT_DECLARED` (409)."

    PRD §2.8: "Rung 69: the event must have struck inside the policy term, meaning its `occurred_at` is at or after the policy's `effective_at` and strictly before the policy's `expires_at`, otherwise `ERR_POLICY_NOT_IN_FORCE_AT_EVENT` (409)."

    Design: Difficulty/priority_pair_validation_conflict/event_not_declared_outranks_policy_not_in_force_at_event_on_fnol
    """
    ctx = _monitored_quake_that_predates_the_term(api)
    filing = factories.create_claim_payload(
        ctx["policy"]["id"],
        ctx["event"]["id"],
        ctx["event"]["version"],
        structural_damage_cents=9000000,
    )
    validate_error(
        api.create_claim(filing, CLAIM_ADJUSTER_HEADERS), ApiErrorId.EVENT_NOT_DECLARED
    )

    declared = validate_success(
        api.declare_event(ctx["event"]["id"], None, PROGRAM_ADMIN_HEADERS)
    )
    assert declared["status"] == "DECLARED"

    filing["expected_event_version"] = declared["version"]
    refused = api.create_claim(filing, CLAIM_ADJUSTER_HEADERS)
    validate_error(refused, ApiErrorId.POLICY_NOT_IN_FORCE_AT_EVENT)

    quake = validate_success(api.get_catastrophe_event(ctx["event"]["id"], PROGRAM_ADMIN_HEADERS))
    assert quake["claim_count"] == 0
    assert quake["aggregate_incurred_cents"] == 0


def _suspended_contractor_with_a_booked_morning(api):
    """One contractor, two projects awaiting inspection, one booked visit, then suspension.

    The booked visit runs 09:00 to 11:00 on 2026-10-05 and is still PENDING, so it
    holds the contractor's calendar. Both projects were opened and driven to
    AWAITING_INSPECTION while the certification was good; the suspension lands
    afterwards, which is why it blocks a new booking without disturbing the work
    already in hand.
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    insurer = fixtures.create_insurer(api)
    holder = fixtures.create_policyholder(api)
    cycle = fixtures.create_grant_cycle(
        api, program_track="BRACE_AND_BOLT", total_pool_cents=1000000
    )
    contractor = fixtures.create_contractor(api, certified_scopes=["CRIPPLE_WALL_BRACING"])
    grant_terms = {
        "income_tier": "TIER_LOW",
        "project_cost_estimate_cents": 250000,
        "requested_scope": "CRIPPLE_WALL_BRACING",
    }

    first = _bound_policy_on_new_dwelling(
        api, insurer, holder, CRIPPLE_WALL_DWELLING, **WIDE_SUBLIMIT_POLICY
    )
    first = fixtures.setup_project_awaiting_inspection(
        api, ctx=first, cycle=cycle, contractor=contractor, **grant_terms
    )
    second = _bound_policy_on_new_dwelling(
        api, insurer, holder, CRIPPLE_WALL_DWELLING, **WIDE_SUBLIMIT_POLICY
    )
    second = fixtures.setup_project_awaiting_inspection(
        api, ctx=second, cycle=cycle, contractor=contractor, **grant_terms
    )
    assert second["project"]["status"] == "AWAITING_INSPECTION"

    booked = validate_success(
        api.create_inspection(
            factories.create_inspection_payload(
                first["project"]["id"], "2026-10-05T09:00:00Z", "2026-10-05T11:00:00Z"
            ),
            FIELD_INSPECTOR_HEADERS,
        ),
        201,
    )
    assert booked["result"] == "PENDING"

    suspended = validate_success(
        api.set_contractor_certification(
            contractor["id"],
            factories.certification_payload("SUSPENDED", reason="license audit"),
            PROGRAM_ADMIN_HEADERS,
        )
    )
    assert suspended["certification_status"] == "SUSPENDED"
    return {"contractor": contractor, "booked": booked, "project": second["project"]}


def _restore_certification(api, contractor_id):
    """Put a suspended contractor back on the certified register."""
    restored = validate_success(
        api.set_contractor_certification(
            contractor_id,
            factories.certification_payload("CERTIFIED", reason="audit cleared"),
            PROGRAM_ADMIN_HEADERS,
        )
    )
    assert restored["certification_status"] == "CERTIFIED"
    return restored


def test_05_booking_for_a_suspended_contractor_answers_on_certification_not_the_calendar(api):
    """PRD §2.8: "Rung 39: the contractor's `certification_status` must be `CERTIFIED` both when a project is created for it and again when an inspection is booked for that project, since a contractor on `PROBATION` or `SUSPENDED` can neither take on new retrofit work nor be inspected for it, otherwise `ERR_CONTRACTOR_NOT_CERTIFIED` (409)."

    PRD §2.8: "Rung 60: the contractor calendar must be free, otherwise `ERR_INSPECTION_SLOT_OVERLAP` (409)."

    PRD §5: "Every failure answers with the error envelope of section 2.2 and exactly one `error_id` from the catalogue below, selected by the priority ladder of section 2.8: when a request offends several rules at once, the offence with the smallest priority number is the one reported, and no other error is disclosed in the same response."

    Design: Difficulty/priority_pair_validation_conflict/contractor_not_certified_outranks_inspection_slot_overlap
    """
    ctx = _suspended_contractor_with_a_booked_morning(api)

    refused = api.create_inspection(
        factories.create_inspection_payload(
            ctx["project"]["id"], "2026-10-05T11:30:00Z", "2026-10-05T12:30:00Z"
        ),
        FIELD_INSPECTOR_HEADERS,
    )
    validate_error(refused, ApiErrorId.CONTRACTOR_NOT_CERTIFIED)

    calendar = validate_success(
        api.list_inspections({"project_id": ctx["project"]["id"]}, PROGRAM_ADMIN_HEADERS)
    )
    assert calendar == []


def test_06_reinstating_the_contractor_exposes_the_buffered_calendar_clash(api):
    """PRD §3.6: "if the widened interval intersects the half-open window of any existing inspection that is still `PENDING`, belongs to the same `contractor_id`, and sits on a project that is not `ABANDONED`, the booking is refused with `ERR_INSPECTION_SLOT_OVERLAP`."

    PRD §2.8: "Rung 39: the contractor's `certification_status` must be `CERTIFIED` both when a project is created for it and again when an inspection is booked for that project, since a contractor on `PROBATION` or `SUSPENDED` can neither take on new retrofit work nor be inspected for it, otherwise `ERR_CONTRACTOR_NOT_CERTIFIED` (409)."

    PRD §2.8: "Rung 60: the contractor calendar must be free, otherwise `ERR_INSPECTION_SLOT_OVERLAP` (409)."

    Design: Difficulty/priority_pair_validation_conflict/contractor_not_certified_outranks_inspection_slot_overlap
    """
    ctx = _suspended_contractor_with_a_booked_morning(api)
    request = factories.create_inspection_payload(
        ctx["project"]["id"], "2026-10-05T11:30:00Z", "2026-10-05T12:30:00Z"
    )
    validate_error(
        api.create_inspection(request, FIELD_INSPECTOR_HEADERS),
        ApiErrorId.CONTRACTOR_NOT_CERTIFIED,
    )

    _restore_certification(api, ctx["contractor"]["id"])

    refused = api.create_inspection(request, FIELD_INSPECTOR_HEADERS)
    validate_error(refused, ApiErrorId.INSPECTION_SLOT_OVERLAP)

    calendar = validate_success(
        api.list_inspections({"project_id": ctx["project"]["id"]}, PROGRAM_ADMIN_HEADERS)
    )
    assert calendar == []


def test_07_a_visit_starting_where_the_buffer_ends_is_accepted(api):
    """PRD §3.6: "if the widened interval intersects the half-open window of any existing inspection that is still `PENDING`, belongs to the same `contractor_id`, and sits on a project that is not `ABANDONED`, the booking is refused with `ERR_INSPECTION_SLOT_OVERLAP`."

    PRD §3.6: "The window is half-open — it includes `window_start` and excludes `window_end` — must be at least thirty and at most two hundred and forty minutes long, both bounds inclusive, and must begin at or after the current logical clock; a visit booked into the past is refused with `ERR_INSPECTION_IN_PAST`."

    PRD §3.6: "The project must be in `AWAITING_INSPECTION`, and the inspection's `contractor_id` is copied from the project rather than taken from the caller; a caller-supplied `contractor_id` that disagrees with the project's is refused with `ERR_INSPECTION_PROJECT_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/contractor_not_certified_outranks_inspection_slot_overlap
    """
    ctx = _suspended_contractor_with_a_booked_morning(api)
    _restore_certification(api, ctx["contractor"]["id"])

    accepted = validate_success(
        api.create_inspection(
            factories.create_inspection_payload(
                ctx["project"]["id"], "2026-10-05T12:00:00Z", "2026-10-05T13:00:00Z"
            ),
            FIELD_INSPECTOR_HEADERS,
        ),
        201,
    )
    assert accepted["result"] == "PENDING"
    assert accepted["contractor_id"] == ctx["contractor"]["id"]
    assert accepted["project_id"] == ctx["project"]["id"]


ROCK_TIER_1_DWELLING = {
    "county_hazard_tier": "TIER_1",
    "soil_class": "ROCK",
    "structure_type": "WOOD_FRAME_SLAB",
    "year_built": 1990,
}
LARGE_LIMIT_QUOTE_TERMS = {
    "deductible_pct": 10,
    "contents_sublimit_cents": 10000000,
    "loss_of_use_sublimit_cents": 5000000,
}


def _quote_at_limit(api, insurer, holder, dwelling_limit_cents):
    """Quote one otherwise identical rock-soil dwelling at the given Coverage A limit."""
    return _quote_on_new_dwelling(
        api,
        insurer,
        holder,
        dict(ROCK_TIER_1_DWELLING, dwelling_limit_cents=dwelling_limit_cents),
        **LARGE_LIMIT_QUOTE_TERMS,
    )


def test_08_a_limit_one_hundred_cents_short_of_the_load_prices_without_it(api):
    """PRD §3.3: "1.15 when `dwelling_limit_cents` is at least 75,000,000 cents, which is a Coverage A limit of seven hundred and fifty thousand dollars or more, and 1.00 below that."

    PRD §3.3: "First, the exposure is expressed in units of one thousand dollars of Coverage A limit: divide `dwelling_limit_cents` by one hundred thousand, which is the number of cents in one thousand dollars."

    PRD §3.3: "Second, take the county's base rate per thousand dollars of limit, which is 180 cents for `TIER_1`, 320 cents for `TIER_2` and 520 cents for `TIER_3`."

    PRD §3.3: "Multiply the base rate per thousand by the exposure units and then by all six factors, in that order, keeping exact decimal arithmetic throughout."

    PRD §3.3: "Only after the clamp is the value rounded, half up, exactly once, to whole cents, and that integer becomes `base_premium_cents`."

    PRD §3.2: "it pins `rated_dwelling_limit_cents` from the dwelling's live `dwelling_limit_cents`"

    Design: Difficulty/boundary_precision_check/high_limit_load_attaches_exactly_at_75000000_and_rounds_half_up
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    insurer = fixtures.create_insurer(api)
    holder = fixtures.create_policyholder(api)

    # 180 cents per thousand x 749.999 exposure units x 0.85 rock soil = 114,749.847 unclamped.
    below = _quote_at_limit(api, insurer, holder, 74999900)
    assert below["base_premium_cents"] == 114750
    assert below["rated_dwelling_limit_cents"] == 74999900
    assert below["annual_premium_cents"] == 114750
    assert below["rating_variant"] == "QUOTE_TIME"


def test_09_the_load_attaches_at_the_threshold_itself_and_the_exact_half_rounds_up(api):
    """PRD §3.3: "1.15 when `dwelling_limit_cents` is at least 75,000,000 cents, which is a Coverage A limit of seven hundred and fifty thousand dollars or more, and 1.00 below that."

    PRD §3.3: "Only after the clamp is the value rounded, half up, exactly once, to whole cents, and that integer becomes `base_premium_cents`."

    PRD §2.6: "Rounding half up means that a fractional remainder of exactly one half rounds away from zero, to the next whole cent."

    PRD §3.3: "Finally, `annual_premium_cents` — the amount actually billed — is `base_premium_cents` less whatever `mitigation_discount_cents` currently stands at, which at quote time is zero."

    Design: Difficulty/boundary_precision_check/high_limit_load_attaches_exactly_at_75000000_and_rounds_half_up
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    insurer = fixtures.create_insurer(api)
    holder = fixtures.create_policyholder(api)

    below = _quote_at_limit(api, insurer, holder, 74999900)
    assert below["base_premium_cents"] == 114750

    # 180 x 750 x 0.85 x 1.15 is exactly 131,962.5, which must round away from zero.
    at_threshold = _quote_at_limit(api, insurer, holder, 75000000)
    assert at_threshold["base_premium_cents"] == 131963
    assert at_threshold["rated_dwelling_limit_cents"] == 75000000
    assert at_threshold["annual_premium_cents"] == 131963
    assert at_threshold["mitigation_discount_cents"] == 0

    # One hundred cents of extra limit buys 17,213 cents of extra premium.
    assert at_threshold["base_premium_cents"] - below["base_premium_cents"] == 17213


def test_10_one_cent_above_the_threshold_stays_on_the_loaded_side(api):
    """PRD §3.3: "1.15 when `dwelling_limit_cents` is at least 75,000,000 cents, which is a Coverage A limit of seven hundred and fifty thousand dollars or more, and 1.00 below that."

    PRD §3.3: "Multiply the base rate per thousand by the exposure units and then by all six factors, in that order, keeping exact decimal arithmetic throughout."

    PRD §3.3: "Only after the clamp is the value rounded, half up, exactly once, to whole cents, and that integer becomes `base_premium_cents`."

    PRD §3.2: "it pins `rated_dwelling_limit_cents` from the dwelling's live `dwelling_limit_cents`"

    Design: Difficulty/boundary_precision_check/high_limit_load_attaches_exactly_at_75000000_and_rounds_half_up
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    insurer = fixtures.create_insurer(api)
    holder = fixtures.create_policyholder(api)

    # 180 x 750.00001 x 0.85 x 1.15 = 131,962.5017595, still 131963 once rounded.
    above = _quote_at_limit(api, insurer, holder, 75000001)
    assert above["base_premium_cents"] == 131963
    assert above["rated_dwelling_limit_cents"] == 75000001
    assert above["annual_premium_cents"] == 131963
    assert above["rating_variant"] == "QUOTE_TIME"


def _finalized_claim_payable_18200000(api):
    """A finalized loss whose payable settles at exactly 18,200,000 cents.

    Coverage A limit 50,000,000 at a fifteen percent deductible of 7,500,000;
    structural 20,000,000 with 5,000,000 cosmetic reported, of which only
    2,000,000 is allowed; contents and loss of use reported exactly at their
    sublimits of 2,500,000 and 1,200,000.
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    ctx = fixtures.setup_event_with_policy(
        api,
        dwelling_overrides=CRIPPLE_WALL_DWELLING,
        policy_overrides={
            "deductible_pct": 15,
            "contents_sublimit_cents": 2500000,
            "loss_of_use_sublimit_cents": 1200000,
        },
    )
    ctx = fixtures.setup_finally_adjusted_claim(
        api,
        ctx=ctx,
        structural_damage_cents=20000000,
        cosmetic_damage_cents=5000000,
        contents_damage_cents=2500000,
        loss_of_use_cents=1200000,
    )
    claim = ctx["claim"]
    assert claim["deductible_applied_cents"] == 7500000
    assert claim["contents_part_cents"] == 1734694
    assert claim["dwelling_part_cents"] == 15265306
    assert claim["loss_of_use_part_cents"] == 1200000
    assert claim["final_payable_cents"] == 18200000
    assert claim["payable_cents"] == 18200000
    assert claim["paid_cents"] == 0
    assert claim["payment_status"] == "UNPAID"
    return ctx


def test_11_a_payment_one_cent_short_of_the_payable_leaves_the_claim_partly_paid(api):
    """PRD §3.8: "The amount must be strictly greater than zero, and `paid_cents` plus the amount must not exceed `payable_cents`; one cent beyond is refused with `ERR_PAYMENT_EXCEEDS_PAYABLE`."

    PRD §3.8: "On success `paid_cents` rises by the amount, and the payment dimension moves according to the arithmetic: `UNPAID → PARTIALLY_PAID` when the running total is still short of `payable_cents`, `UNPAID → PAID` when a single payment settles the whole payable exactly, and `PARTIALLY_PAID → PAID` when a later payment brings the total to exactly `payable_cents`."

    PRD §3.8: "`adjustment_status` is never changed by a payment."

    Design: Difficulty/boundary_precision_check/payment_settles_exactly_at_payable_and_one_cent_more_is_refused
    """
    ctx = _finalized_claim_payable_18200000(api)

    partial = validate_success(
        api.record_claim_payment(
            ctx["claim"]["id"],
            factories.record_payment_payload(18199999),
            PROGRAM_ADMIN_HEADERS,
        )
    )
    assert partial["paid_cents"] == 18199999
    assert partial["payment_status"] == "PARTIALLY_PAID"
    assert partial["payable_cents"] == 18200000
    assert partial["adjustment_status"] == "FINAL_ADJUSTED"


def test_12_the_final_cent_settles_the_payable_exactly(api):
    """PRD §3.8: "On success `paid_cents` rises by the amount, and the payment dimension moves according to the arithmetic: `UNPAID → PARTIALLY_PAID` when the running total is still short of `payable_cents`, `UNPAID → PAID` when a single payment settles the whole payable exactly, and `PARTIALLY_PAID → PAID` when a later payment brings the total to exactly `payable_cents`."

    PRD §3.8: "Equality settles; anything beyond is refused."

    PRD §3.8: "`adjustment_status` is never changed by a payment."

    Design: Difficulty/boundary_precision_check/payment_settles_exactly_at_payable_and_one_cent_more_is_refused
    """
    ctx = _finalized_claim_payable_18200000(api)
    claim_id = ctx["claim"]["id"]

    validate_success(
        api.record_claim_payment(
            claim_id, factories.record_payment_payload(18199999), PROGRAM_ADMIN_HEADERS
        )
    )
    settled = validate_success(
        api.record_claim_payment(
            claim_id, factories.record_payment_payload(1), PROGRAM_ADMIN_HEADERS
        )
    )
    assert settled["paid_cents"] == 18200000
    assert settled["payment_status"] == "PAID"
    assert settled["adjustment_status"] == "FINAL_ADJUSTED"

    reread = validate_success(api.get_claim(claim_id, PROGRAM_ADMIN_HEADERS))
    assert reread["paid_cents"] == 18200000
    assert reread["payment_status"] == "PAID"


def test_13_a_payment_one_cent_beyond_the_remaining_balance_is_refused(api):
    """PRD §3.8: "The amount must be strictly greater than zero, and `paid_cents` plus the amount must not exceed `payable_cents`; one cent beyond is refused with `ERR_PAYMENT_EXCEEDS_PAYABLE`."

    PRD §2.8: "Rung 75: a payment's `amount_cents` must be strictly greater than zero and no greater than the claim's `payable_cents` less its `paid_cents`, otherwise `ERR_PAYMENT_EXCEEDS_PAYABLE` (422)."

    PRD §3.8: "Equality settles; anything beyond is refused."

    Design: Difficulty/boundary_precision_check/payment_settles_exactly_at_payable_and_one_cent_more_is_refused
    """
    ctx = _finalized_claim_payable_18200000(api)
    claim_id = ctx["claim"]["id"]

    validate_success(
        api.record_claim_payment(
            claim_id, factories.record_payment_payload(18199999), PROGRAM_ADMIN_HEADERS
        )
    )

    # Exactly one cent of the payable is still outstanding, so two cents overflows it.
    refused = api.record_claim_payment(
        claim_id, factories.record_payment_payload(2), PROGRAM_ADMIN_HEADERS
    )
    validate_error(refused, ApiErrorId.PAYMENT_EXCEEDS_PAYABLE, 422)

    reread = validate_success(api.get_claim(claim_id, PROGRAM_ADMIN_HEADERS))
    assert reread["paid_cents"] == 18199999
    assert reread["payment_status"] == "PARTIALLY_PAID"
    assert reread["adjustment_status"] == "FINAL_ADJUSTED"


TAKE_UP_WINDOW = ("2026-07-01T00:00:00Z", "2026-09-01T00:00:00Z")


def _evaluate_take_up(api, insurer_id):
    """Measure take-up over the half-open window that spans the whole test calendar."""
    return validate_success(
        api.insurer_take_up_evaluation(
            insurer_id,
            factories.take_up_evaluation_payload(*TAKE_UP_WINDOW),
            PROGRAM_ADMIN_HEADERS,
        )
    )


def _one_acceptance_and_three_documented_declines(api):
    """A carrier whose duty book holds one acceptance against three documented refusals."""
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    insurer = fixtures.create_insurer(api)
    holder = fixtures.create_policyholder(api)

    accepted = _answer_a_fresh_offer(api, insurer, holder, "ACCEPT")
    assert accepted["status"] == "ACCEPTED"
    for _ in range(3):
        declined = _answer_a_fresh_offer(api, insurer, holder, "DECLINE", decline_documented=True)
        assert declined["status"] == "DECLINED"
    return insurer, holder


def test_14_a_take_up_rate_sitting_exactly_on_the_floor_leaves_the_carrier_compliant(api):
    """PRD §3.1: "Within that set, the numerator is the count in `ACCEPTED` and the denominator is the count of all considered offers; the take-up rate in basis points is ten thousand multiplied by the accepted count divided by the considered count, rounded half up to a whole basis point, and is reported as zero when nothing was considered at all."

    PRD §3.1: "Otherwise, if at least four offers were considered *and* the computed rate is strictly below 2500 basis points — that is, below a twenty-five percent take-up — *and* the insurer is currently `COMPLIANT`, then `compliance_status` moves `COMPLIANT → UNDER_REVIEW`."

    PRD §3.1: "The evaluation writes the result to `last_take_up_rate_bp`, writes the considered count to `offers_recorded_count`, and rewrites `undocumented_decline_count` as the count of considered offers that are `DECLINED` with `decline_documented` false."

    Design: Difficulty/boundary_precision_check/take_up_rate_exactly_at_floor_does_not_downgrade_but_one_offer_later_does
    """
    insurer, _holder = _one_acceptance_and_three_documented_declines(api)

    # One acceptance out of four considered offers is exactly 2500 basis points.
    measured = _evaluate_take_up(api, insurer["id"])
    assert measured["offers_recorded_count"] == 4
    assert measured["last_take_up_rate_bp"] == 2500
    assert measured["undocumented_decline_count"] == 0
    assert measured["compliance_status"] == "COMPLIANT"


def test_15_one_further_documented_decline_drops_the_rate_below_the_floor(api):
    """PRD §3.1: "Otherwise, if at least four offers were considered *and* the computed rate is strictly below 2500 basis points — that is, below a twenty-five percent take-up — *and* the insurer is currently `COMPLIANT`, then `compliance_status` moves `COMPLIANT → UNDER_REVIEW`."

    PRD §3.1: "If the recomputed `undocumented_decline_count` is at least three, the insurer's `compliance_status` becomes `SANCTIONED`; this path may jump straight from `COMPLIANT` without passing through `UNDER_REVIEW`."

    PRD §3.1: "Within that set, the numerator is the count in `ACCEPTED` and the denominator is the count of all considered offers; the take-up rate in basis points is ten thousand multiplied by the accepted count divided by the considered count, rounded half up to a whole basis point, and is reported as zero when nothing was considered at all."

    Design: Difficulty/boundary_precision_check/take_up_rate_exactly_at_floor_does_not_downgrade_but_one_offer_later_does
    """
    insurer, holder = _one_acceptance_and_three_documented_declines(api)

    at_floor = _evaluate_take_up(api, insurer["id"])
    assert at_floor["last_take_up_rate_bp"] == 2500
    assert at_floor["compliance_status"] == "COMPLIANT"

    _answer_a_fresh_offer(api, insurer, holder, "DECLINE", decline_documented=True)

    # One acceptance out of five considered offers is 2000 basis points.
    below_floor = _evaluate_take_up(api, insurer["id"])
    assert below_floor["offers_recorded_count"] == 5
    assert below_floor["last_take_up_rate_bp"] == 2000
    assert below_floor["undocumented_decline_count"] == 0
    assert below_floor["compliance_status"] == "UNDER_REVIEW"


def test_16_a_sample_short_of_four_offers_never_downgrades_however_low_the_rate(api):
    """PRD §3.1: "Fewer than four considered offers is treated as statistically meaningless: no downgrade occurs at any measured rate, including the case where nothing was considered and the rate is reported as zero."

    PRD §3.1: "Otherwise, if at least four offers were considered *and* the computed rate is strictly below 2500 basis points — that is, below a twenty-five percent take-up — *and* the insurer is currently `COMPLIANT`, then `compliance_status` moves `COMPLIANT → UNDER_REVIEW`."

    PRD §3.1: "The evaluation considers exactly those of the insurer's offers whose `offered_at` is at or after `window_start` and strictly before `window_end`, and whose status is one of `ACCEPTED`, `DECLINED` or `EXPIRED` — offers still `PENDING` count in neither the numerator nor the denominator."

    Design: Difficulty/boundary_precision_check/take_up_rate_exactly_at_floor_does_not_downgrade_but_one_offer_later_does
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    insurer = fixtures.create_insurer(api)
    holder = fixtures.create_policyholder(api)
    for _ in range(3):
        _answer_a_fresh_offer(api, insurer, holder, "DECLINE", decline_documented=True)

    # Nothing accepted out of three considered offers: the worst possible rate on too small a sample.
    measured = _evaluate_take_up(api, insurer["id"])
    assert measured["offers_recorded_count"] == 3
    assert measured["last_take_up_rate_bp"] == 0
    assert measured["undocumented_decline_count"] == 0
    assert measured["compliance_status"] == "COMPLIANT"


CODE_YEAR_QUOTE_TERMS = {
    "deductible_pct": 10,
    "contents_sublimit_cents": 4000000,
    "loss_of_use_sublimit_cents": 2000000,
}


def _quote_on_vintage(api, insurer, holder, year_built):
    """Quote one otherwise identical tier-two slab dwelling of the given vintage."""
    return _quote_on_new_dwelling(
        api,
        insurer,
        holder,
        {
            "county_hazard_tier": "TIER_2",
            "soil_class": "STIFF",
            "structure_type": "WOOD_FRAME_SLAB",
            "year_built": year_built,
            "dwelling_limit_cents": 20000000,
        },
        **CODE_YEAR_QUOTE_TERMS,
    )


def test_17_a_dwelling_built_before_the_code_year_carries_the_vintage_load(api):
    """PRD §3.3: "1.20 when `year_built` is 1979 or earlier, and 1.00 for anything built in 1980 or later"

    PRD §3.2: "The vintage matters because construction from 1979 or earlier is pre-code and rates accordingly."

    PRD §3.3: "Second, take the county's base rate per thousand dollars of limit, which is 180 cents for `TIER_1`, 320 cents for `TIER_2` and 520 cents for `TIER_3`."

    PRD §3.3: "Multiply the base rate per thousand by the exposure units and then by all six factors, in that order, keeping exact decimal arithmetic throughout."

    Design: Difficulty/boundary_precision_check/pre_code_age_factor_attaches_at_1979_and_releases_at_1980
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    insurer = fixtures.create_insurer(api)
    holder = fixtures.create_policyholder(api)

    # 320 cents per thousand x 200 exposure units x 1.20 vintage load = 76,800.
    pre_code = _quote_on_vintage(api, insurer, holder, 1978)
    assert pre_code["base_premium_cents"] == 76800
    assert pre_code["annual_premium_cents"] == 76800
    assert pre_code["rating_variant"] == "QUOTE_TIME"


def test_18_the_code_year_itself_is_still_inside_the_loaded_band(api):
    """PRD §3.3: "1.20 when `year_built` is 1979 or earlier, and 1.00 for anything built in 1980 or later"

    PRD §3.2: "The vintage matters because construction from 1979 or earlier is pre-code and rates accordingly."

    PRD §3.3: "Only after the clamp is the value rounded, half up, exactly once, to whole cents, and that integer becomes `base_premium_cents`."

    Design: Difficulty/boundary_precision_check/pre_code_age_factor_attaches_at_1979_and_releases_at_1980
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    insurer = fixtures.create_insurer(api)
    holder = fixtures.create_policyholder(api)

    on_the_boundary = _quote_on_vintage(api, insurer, holder, 1979)
    assert on_the_boundary["base_premium_cents"] == 76800
    assert on_the_boundary["annual_premium_cents"] == 76800
    assert on_the_boundary["rated_dwelling_limit_cents"] == 20000000


def test_19_the_first_post_code_vintage_releases_the_load_entirely(api):
    """PRD §3.3: "1.20 when `year_built` is 1979 or earlier, and 1.00 for anything built in 1980 or later"

    PRD §3.3: "Finally, `annual_premium_cents` — the amount actually billed — is `base_premium_cents` less whatever `mitigation_discount_cents` currently stands at, which at quote time is zero."

    PRD §3.3: "The result is written to `base_premium_cents`, and `rating_variant` records which of the two variants produced it, taking the value `QUOTE_TIME` or `RENEWAL_TIME`."

    Design: Difficulty/boundary_precision_check/pre_code_age_factor_attaches_at_1979_and_releases_at_1980
    """
    fixtures.set_clock(api, constants.CLOCK_EPOCH)
    insurer = fixtures.create_insurer(api)
    holder = fixtures.create_policyholder(api)

    on_the_boundary = _quote_on_vintage(api, insurer, holder, 1979)
    assert on_the_boundary["base_premium_cents"] == 76800

    post_code = _quote_on_vintage(api, insurer, holder, 1980)
    assert post_code["base_premium_cents"] == 64000
    assert post_code["annual_premium_cents"] == 64000
    assert post_code["mitigation_discount_cents"] == 0
    assert post_code["rating_variant"] == "QUOTE_TIME"

    # One year of vintage is worth 12,800 cents on byte-identical hazard data.
    assert on_the_boundary["base_premium_cents"] - post_code["base_premium_cents"] == 12800
