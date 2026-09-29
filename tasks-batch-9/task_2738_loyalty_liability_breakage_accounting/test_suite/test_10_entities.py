"""
Entity-level behaviour of the Loyalty Liability & Breakage Accounting API.

These tests exercise what a resource looks like the moment it is created, what a
read gives back, how a collection paginates and filters, which inputs are
required, which optional inputs carry a declared default, which figures the
server measures rather than accepts, and how the cross-programme coherence rules
refuse a pairing whose two parents both exist.
"""

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_allocation_seq_ascending,
    assert_created,
    assert_envelope_object,
    assert_error,
    assert_fields,
    assert_immutable_common_fields,
    assert_lot_split,
    assert_null_fields,
    assert_ok,
    assert_page,
    assert_representation_complete,
    assert_utc_timestamp,
)
from test_helpers.constants import (
    BREAKAGE_METHOD_COHORT_WEIGHTED,
    CLOCK_EPOCH,
    CURRENCY_USD,
    DEFAULT_ESCHEAT_DISCLOSURE_THRESHOLD_CENTS,
    DEFAULT_HISTORICAL_REDEMPTION_RATE_BP,
    DEFAULT_LIMIT,
    DEFAULT_OFFSET,
    DEFAULT_PER_ISSUANCE_POINT_CAP,
    DEFAULT_POINT_EXPIRY_DAYS,
    DEFAULT_PROGRAM_CHANGE_ADJUSTMENT_BP,
    DEFAULT_PROMO_MULTIPLIER_CAP_BP,
    DEFAULT_SEEDED_BREAKAGE_RATE_BP,
    DEFAULT_SSP_MILLICENTS_PER_POINT,
    ENTRY_TYPE_ALLOCATION,
    IDENTITY_MULTIPLIER_BP,
    LOT_FULLY_REDEEMED,
    LOT_OUTSTANDING,
    LOT_PARTIALLY_REDEEMED,
    MEMBER_ACTIVE,
    PERIOD_OPEN,
    PROGRAM_ACTIVE,
    PROGRAM_DRAFT,
    REDEMPTION_ALLOCATED,
    SETTLEMENT_NOT_APPLICABLE,
    TIER_BASE,
    TIER_GOLD,
    TIER_MULTIPLIER_BP,
    UNKNOWN_ID,
)
from test_helpers.test_users import (
    ACCOUNTANT_HEADERS,
    CONTROLLER_HEADERS,
    PROGRAM_ADMIN_HEADERS,
)
from test_helpers.types import expected_fields

# ─── Clock instants this module drives ───────────────────────────────────────
AUG_02 = "2026-08-02T00:00:00Z"
AUG_03 = "2026-08-03T00:00:00Z"

# ─── The programme configuration every measurement below is derived from ─────
# ssp 1200 millicents per point, 730 expiry days, per-issuance cap 5000, GOLD
# multiplier 12500 bp, historical redemption rate 7500 bp.
GOLD_MULTIPLIER_BP = TIER_MULTIPLIER_BP[TIER_GOLD]

# ─── A 1000-point BASE lot at ssp 1200 and breakage rate 2500 bp ─────────────
BASE_LOT_POINTS = 1000
BASE_LOT_GROSS_CENTS = 1200
BASE_LOT_RESERVE_CENTS = 300
BASE_LOT_DEFERRED_CENTS = 900

# ─── A 4000-point GOLD lot: tier uplift to 5000 points, then no promotion ────
GOLD_BASE_POINTS = 4000
GOLD_TIER_POINTS = 5000
GOLD_POINTS_ISSUED = 5000
GOLD_GROSS_CENTS = 6000
GOLD_RESERVE_CENTS = 1500
GOLD_DEFERRED_CENTS = 4500
GOLD_TIER_BENEFIT_EXPENSE_CENTS = 1200
# issued_at 2026-08-01T00:00:00Z advanced by 730 whole days.
GOLD_EXPIRES_AT = "2028-07-31T00:00:00Z"

# ─── The 400-point allocation line drawn from a 1000-point BASE lot ──────────
LINE_POINTS_ALLOCATED = 400
LINE_GROSS_CENTS = 480
LINE_RESERVE_CENTS = 120
LINE_PROVISIONAL_CENTS = 360

# ─── A 1500-point redemption spanning two 1000-point BASE lots ──────────────
SPAN_POINTS_REQUESTED = 1500
SPAN_LINE_1_POINTS = 1000
SPAN_LINE_1_GROSS_CENTS = 1200
SPAN_LINE_1_PROVISIONAL_CENTS = 900
SPAN_LINE_2_POINTS = 500
SPAN_LINE_2_GROSS_CENTS = 600
SPAN_LINE_2_PROVISIONAL_CENTS = 450
SPAN_EVENT_PROVISIONAL_CENTS = 1350
SPAN_BALANCE_AFTER = 500

# ─── Out-of-range and out-of-enumeration probes ──────────────────────────────
UNRECOGNISED_BREAKAGE_METHOD = "MOVING_AVERAGE"
# The declared band for historical_redemption_rate_bp is 200 through 9800.
HISTORICAL_RATE_ABOVE_CEILING_BP = 9801

THREE_KEY_TIER_MULTIPLIER_BP = {"BASE": 10000, "SILVER": 10300, "GOLD": 12500}
FIVE_KEY_TIER_MULTIPLIER_BP = {
    "BASE": 10000,
    "SILVER": 10300,
    "GOLD": 12500,
    "PLATINUM": 15000,
    "DIAMOND": 20000,
}


# ─── Shared setup ────────────────────────────────────────────────────────────
def _configured_program(api, **program_overrides):
    """
    A programme in DRAFT that already carries the one state expiry rule and the
    one enrolment vintage activation insists on. Returns (program, cohort).
    """
    program = fixtures.new_program(api, **program_overrides)
    fixtures.new_state_expiry_rule(
        api, program["id"], escheatment_required=False, escheat_rate_bp=0
    )
    cohort = fixtures.new_cohort(api, program["id"])
    return program, cohort


def _active_program(api, **program_overrides):
    """The same programme driven DRAFT to ACTIVE, so its breakage rate is seeded."""
    program, cohort = _configured_program(api, **program_overrides)
    return fixtures.activate(api, program["id"]), cohort


def _issuance_ready(api, clock=CLOCK_EPOCH, tier=TIER_BASE, **program_overrides):
    """
    The clock placed, an ACTIVE programme with one cohort, one member of the
    requested tier and one OPEN period. Returns a bundle keyed by resource name.
    """
    fixtures.set_clock(api, clock)
    program, cohort = _active_program(api, **program_overrides)
    member = fixtures.new_member(api, program["id"], cohort["id"], tier=tier)
    period = fixtures.new_period(api, program["id"])
    return {
        "program": program,
        "cohort": cohort,
        "member": member,
        "period": period,
    }


def test_program_creation_returns_declared_and_computed_fields(api):
    """
    Creating a programme with every input present returns 201 inside the success
    envelope and echoes each declared value back, while the server itself mints
    the status, the three escheatment and rate figures, the version and both
    derived-on-read totals, which are 0 because the programme owns no lot and no
    closed period yet.

    "Creation endpoints return HTTP 201 with the created resource in `data`."
    "A freshly created programme is born in status `DRAFT`, with `current_breakage_rate_bp` at 0, `total_escheat_accrual_cents` at 0, `escheat_disclosure_required` false, and `version` at 1."
    "`total_deferred_revenue_cents` is the sum, over this programme's lots whose `lifecycle_state` is `OUTSTANDING` or `PARTIALLY_REDEEMED`, of each lot's `remaining_deferred_cents`."
    "`recognized_breakage_ytd_cents` is the sum of `breakage_recognized_cents` over this programme's periods whose `state` is `SOFT_CLOSED` or `HARD_CLOSED`."
    "Every resource carries a server-minted `id` — a UUID string with no type prefix — and a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits."
    "Nothing in this system reads the machine's wall clock."

    Design: Corner/entities/entity_program_creation_returns_declared_and_computed_fields
    """
    fixtures.set_clock(api, CLOCK_EPOCH)

    response = api.create_program(
        factories.program_payload(name="Meridian Rewards Core"), PROGRAM_ADMIN_HEADERS
    )
    program = assert_created(response)
    assert_envelope_object(response, 201)
    assert_representation_complete(program, "LoyaltyProgram")

    assert_fields(
        program,
        name="Meridian Rewards Core",
        currency_code=CURRENCY_USD,
        ssp_millicents_per_point=DEFAULT_SSP_MILLICENTS_PER_POINT,
        point_expiry_days=DEFAULT_POINT_EXPIRY_DAYS,
        per_issuance_point_cap=DEFAULT_PER_ISSUANCE_POINT_CAP,
        tier_multiplier_bp=dict(TIER_MULTIPLIER_BP),
        promo_multiplier_cap_bp=DEFAULT_PROMO_MULTIPLIER_CAP_BP,
        breakage_method=BREAKAGE_METHOD_COHORT_WEIGHTED,
        historical_redemption_rate_bp=DEFAULT_HISTORICAL_REDEMPTION_RATE_BP,
        escheat_disclosure_threshold_cents=DEFAULT_ESCHEAT_DISCLOSURE_THRESHOLD_CENTS,
        status=PROGRAM_DRAFT,
        current_breakage_rate_bp=0,
        total_escheat_accrual_cents=0,
        escheat_disclosure_required=False,
        total_deferred_revenue_cents=0,
        recognized_breakage_ytd_cents=0,
        version=1,
        created_at=CLOCK_EPOCH,
        updated_at=CLOCK_EPOCH,
    )


def test_program_retrieval_returns_stored_values_and_rederives_the_totals(api):
    """
    Reading a programme back gives the same stored configuration the create
    returned, the breakage rate the first activation seeded, and a deferred
    revenue total re-derived from the single outstanding lot rather than stored;
    two consecutive reads leave the version where activation left it.

    "That first activation seeds the programme's live breakage rate: `current_breakage_rate_bp` becomes 10000 basis points less `historical_redemption_rate_bp`."
    "It also increments the programme's `version` by 1."
    "`total_deferred_revenue_cents` is the sum, over this programme's lots whose `lifecycle_state` is `OUTSTANDING` or `PARTIALLY_REDEEMED`, of each lot's `remaining_deferred_cents`."
    "`recognized_breakage_ytd_cents` is the sum of `breakage_recognized_cents` over this programme's periods whose `state` is `SOFT_CLOSED` or `HARD_CLOSED`."
    "Both are recomputed on each read and reading them never bumps the programme's `version`."
    "`deferred_revenue_cents` is `gross_ssp_cents` less `breakage_reserve_cents`, and it is this deferral — not the gross — that is added to the period's `issuance_deferred_cents`."

    Design: Corner/entities/entity_program_retrieval_returns_stored_values
    """
    bundle = _issuance_ready(api)
    program_id = bundle["program"]["id"]

    lot = fixtures.issue_lot(
        api, bundle["member"]["id"], bundle["period"]["id"], GOLD_POINTS_ISSUED
    )
    assert_fields(
        lot,
        gross_ssp_cents=GOLD_GROSS_CENTS,
        breakage_reserve_cents=GOLD_RESERVE_CENTS,
        deferred_revenue_cents=GOLD_DEFERRED_CENTS,
        remaining_deferred_cents=GOLD_DEFERRED_CENTS,
        lifecycle_state=LOT_OUTSTANDING,
    )

    program = assert_envelope_object(api.get_program(program_id, ACCOUNTANT_HEADERS))
    assert_representation_complete(program, "LoyaltyProgram")
    assert_fields(
        program,
        name=bundle["program"]["name"],
        currency_code=CURRENCY_USD,
        ssp_millicents_per_point=DEFAULT_SSP_MILLICENTS_PER_POINT,
        point_expiry_days=DEFAULT_POINT_EXPIRY_DAYS,
        per_issuance_point_cap=DEFAULT_PER_ISSUANCE_POINT_CAP,
        historical_redemption_rate_bp=DEFAULT_HISTORICAL_REDEMPTION_RATE_BP,
        status=PROGRAM_ACTIVE,
        current_breakage_rate_bp=DEFAULT_SEEDED_BREAKAGE_RATE_BP,
        total_deferred_revenue_cents=GOLD_DEFERRED_CENTS,
        recognized_breakage_ytd_cents=0,
        version=2,
    )

    # A second read re-derives both totals and still leaves the version alone.
    again = assert_ok(api.get_program(program_id, CONTROLLER_HEADERS))
    assert_fields(
        again,
        total_deferred_revenue_cents=GOLD_DEFERRED_CENTS,
        recognized_breakage_ytd_cents=0,
        version=2,
        updated_at=program["updated_at"],
    )


def test_point_lot_listing_paginates_and_filters_together(api):
    """
    The point lot collection windows its rows with limit and offset, reports the
    size of the whole ordered result in total_count, and applies the
    lifecycle_state filter before counting, so the lot a redemption drove to
    FULLY_REDEEMED leaves the filtered page and the filtered total alike.

    "`limit` caps the number of rows returned; it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100."
    "`offset` skips rows from the front of the ordered result and defaults to 0; negative values are not accepted."
    "List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope."
    "Unless a specific read says otherwise, list results are ordered by `created_at` ascending."
    "Point lots may be filtered by `member_id`, `period_id`, `partner_agreement_id` and by either state dimension independently — `lifecycle_state` and `settlement_state`."
    "A lot that was `OUTSTANDING` and gives up exactly its `points_remaining` moves `OUTSTANDING → FULLY_REDEEMED`, with `points_remaining` set to 0, one `ALLOCATION` row appended, and its `version` incremented by 1."

    Design: Corner/entities/entity_point_lot_listing_paginates_and_filters_together
    """
    bundle = _issuance_ready(api)
    member_id = bundle["member"]["id"]
    period_id = bundle["period"]["id"]

    lot_a = fixtures.issue_lot(api, member_id, period_id, BASE_LOT_POINTS)
    fixtures.set_clock(api, AUG_02)
    lot_b = fixtures.issue_lot(api, member_id, period_id, BASE_LOT_POINTS)
    fixtures.set_clock(api, AUG_03)
    lot_c = fixtures.issue_lot(api, member_id, period_id, BASE_LOT_POINTS)

    # The oldest lot is consumed whole, so it drops out of the OUTSTANDING set.
    fixtures.allocated_redemption(api, member_id, period_id, BASE_LOT_POINTS)

    first_page = api.list_point_lots(
        ACCOUNTANT_HEADERS, period_id=period_id, limit=2, offset=0
    )
    assert_page(
        first_page,
        expected_ids=[lot_a["id"], lot_b["id"]],
        total_count=3,
        has_more=True,
        limit=2,
        offset=0,
    )

    second_page = api.list_point_lots(
        ACCOUNTANT_HEADERS, period_id=period_id, limit=2, offset=2
    )
    assert_page(
        second_page,
        expected_ids=[lot_c["id"]],
        total_count=3,
        has_more=False,
        limit=2,
        offset=2,
    )

    filtered = api.list_point_lots(
        ACCOUNTANT_HEADERS,
        period_id=period_id,
        lifecycle_state=LOT_OUTSTANDING,
        limit=10,
        offset=0,
    )
    assert_page(
        filtered,
        expected_ids=[lot_b["id"], lot_c["id"]],
        total_count=2,
        has_more=False,
    )

    defaults = api.list_point_lots(ACCOUNTANT_HEADERS, period_id=period_id)
    assert_page(
        defaults,
        expected_ids=[lot_a["id"], lot_b["id"], lot_c["id"]],
        total_count=3,
        has_more=False,
        limit=DEFAULT_LIMIT,
        offset=DEFAULT_OFFSET,
    )

    consumed = assert_ok(api.get_point_lot(lot_a["id"], ACCOUNTANT_HEADERS))
    assert_fields(consumed, lifecycle_state=LOT_FULLY_REDEEMED, points_remaining=0)
    for survivor in (lot_b, lot_c):
        still_open = assert_ok(api.get_point_lot(survivor["id"], ACCOUNTANT_HEADERS))
        assert_fields(
            still_open,
            lifecycle_state=LOT_OUTSTANDING,
            points_remaining=BASE_LOT_POINTS,
        )


def test_get_member_with_unknown_id_returns_member_not_found(api):
    """
    Addressing a member identifier the server never minted is a 404 carrying the
    member's own not-found code inside the error envelope, not a 200 with an
    empty payload, and the refused read leaves the collection empty.

    "Each entity has its own not-found code — `ERR_PROGRAM_NOT_FOUND`, `ERR_STATE_EXPIRY_RULE_NOT_FOUND`, `ERR_COHORT_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`, `ERR_PARTNER_AGREEMENT_NOT_FOUND`, `ERR_POINT_LOT_NOT_FOUND`, `ERR_REDEMPTION_EVENT_NOT_FOUND`, `ERR_BREAKAGE_ESTIMATE_NOT_FOUND`, `ERR_SETTLEMENT_STATEMENT_NOT_FOUND` and `ERR_CHANGE_ORDER_NOT_FOUND` — and each carries HTTP 404."
    "The `error_id` is a unique, machine-readable string that identifies the specific error."
    "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/entities/entity_get_member_with_unknown_id_returns_member_not_found
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    _configured_program(api)

    response = api.get_member(UNKNOWN_ID, ACCOUNTANT_HEADERS)
    error = assert_error(response, ApiErrorId.MEMBER_NOT_FOUND.value)
    assert response.json()["response_type"] == "error"
    assert isinstance(error["message"], str) and error["message"], (
        "The error envelope must carry a human-readable message"
    )

    assert_page(api.list_members(ACCOUNTANT_HEADERS), expected_ids=[], total_count=0)


def test_cohort_create_missing_required_field_rejected(api):
    """
    observed_redemption_rate_bp is an input the cohort endpoint declares without
    a default, so omitting it is a malformed request rather than a silent zero;
    nothing is written, and supplying the one missing value makes the very same
    body succeed.

    "**Request shape** — the body parses, every required input the endpoint declares is present, every value satisfies its declared type, enumeration and range constraint, and pagination parameters are in range. Otherwise `ERR_INVALID_REQUEST` (400), on every endpoint."
    "Behaviourally, a cohort carries `observed_redemption_rate_bp` — the redemption rate historically observed for that vintage before any programme-change effect, from 0 through 10000 inclusive — and `sample_size`, the number of members underlying that observation, at least 1."
    "A cohort also carries `program_change_adjustment_bp`, a signed behavioural adjustment from -5000 through 5000 inclusive that defaults to 0 and is moved only by an applied programme change order."

    Design: Corner/entities/entity_cohort_create_missing_required_field_rejected
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    program = fixtures.new_program(api)

    incomplete = factories.cohort_payload(
        program["id"], observed_redemption_rate_bp=None
    )
    assert "observed_redemption_rate_bp" not in incomplete
    assert_error(
        api.create_cohort(incomplete, PROGRAM_ADMIN_HEADERS),
        ApiErrorId.INVALID_REQUEST.value,
    )

    assert_page(
        api.list_cohorts(ACCOUNTANT_HEADERS, program_id=program["id"]),
        expected_ids=[],
        total_count=0,
    )

    complete = dict(incomplete, observed_redemption_rate_bp=8200)
    cohort = assert_created(api.create_cohort(complete, PROGRAM_ADMIN_HEADERS))
    assert_fields(
        cohort,
        program_id=program["id"],
        observed_redemption_rate_bp=8200,
        program_change_adjustment_bp=DEFAULT_PROGRAM_CHANGE_ADJUSTMENT_BP,
    )


def test_program_omitted_optional_inputs_apply_declared_defaults(api):
    """
    A programme create that supplies only the inputs the contract requires takes
    the reporting currency, the promotional cap, the breakage methodology and the
    escheatment disclosure threshold from their declared defaults instead of
    leaving them null.

    "The programme is created with a display `name` of at most 120 characters that may not be empty, and with a `currency_code` naming the reporting currency of the deferred-revenue ledger as exactly three uppercase letters; when the caller omits it, the currency is `USD`."
    "Promotional generosity is capped separately by `promo_multiplier_cap_bp`, which defaults to 30000 and is accepted from 10000 through 100000 inclusive."
    "`breakage_method` is either `COHORT_WEIGHTED` or `PROGRAM_HISTORICAL` and defaults to `COHORT_WEIGHTED`."
    "Escheatment disclosure is governed by `escheat_disclosure_threshold_cents`, a non-negative amount defaulting to 100000 cents, which is one thousand currency units."

    Design: Corner/entities/entity_program_omitted_optional_inputs_apply_declared_defaults
    """
    fixtures.set_clock(api, CLOCK_EPOCH)

    payload = factories.minimal_program_payload()
    for omitted in (
        "currency_code",
        "promo_multiplier_cap_bp",
        "breakage_method",
        "escheat_disclosure_threshold_cents",
    ):
        assert omitted not in payload, f"{omitted} must be omitted for this probe"

    program = assert_created(api.create_program(payload, PROGRAM_ADMIN_HEADERS))
    assert_fields(
        program,
        currency_code=CURRENCY_USD,
        promo_multiplier_cap_bp=DEFAULT_PROMO_MULTIPLIER_CAP_BP,
        breakage_method=BREAKAGE_METHOD_COHORT_WEIGHTED,
        escheat_disclosure_threshold_cents=DEFAULT_ESCHEAT_DISCLOSURE_THRESHOLD_CENTS,
    )


def test_point_lot_omitted_promo_multiplier_defaults_to_the_identity(api):
    """
    An issuance that omits promo_multiplier_bp takes the identity multiplier of
    10000 basis points, so the promotional uplift step leaves the already-rounded
    tier point count alone and the promotional expense leg measures nothing.

    "The request names the holder through `member_id` and the period the issuance books to through `period_id`, optionally names a partner through `partner_agreement_id` (absent or null for programme-issued points), supplies `base_points` of at least 1, and may supply `promo_multiplier_bp`, a promotional multiplier of at least 10000 basis points that defaults to 10000 — meaning no promotion."
    "When `promo_multiplier_bp` is the default 10000, this step is an identity on `tier_points`."
    "`promo_expense_cents` is the difference between `points_issued` and `tier_points`, multiplied by `ssp_millicents_per_point_at_issue`, divided by 1000, rounded half up."
    "`breakage_reserve_cents` is `gross_ssp_cents` multiplied by `breakage_rate_bp_at_issue`, divided by 10000, rounded half up."

    Design: Corner/entities/entity_program_omitted_optional_inputs_apply_declared_defaults
    """
    bundle = _issuance_ready(api)

    payload = factories.point_lot_payload(
        bundle["member"]["id"], bundle["period"]["id"], BASE_LOT_POINTS
    )
    assert "promo_multiplier_bp" not in payload

    lot = assert_created(api.create_point_lot(payload, ACCOUNTANT_HEADERS))
    assert_fields(
        lot,
        base_points=BASE_LOT_POINTS,
        promo_multiplier_bp=IDENTITY_MULTIPLIER_BP,
        tier_points=BASE_LOT_POINTS,
        points_issued=BASE_LOT_POINTS,
        promo_expense_cents=0,
        gross_ssp_cents=BASE_LOT_GROSS_CENTS,
        breakage_reserve_cents=BASE_LOT_RESERVE_CENTS,
        deferred_revenue_cents=BASE_LOT_DEFERRED_CENTS,
    )
    assert_lot_split(lot)


def test_point_lot_computed_measurement_fields_derived_from_config(api):
    """
    A lot's whole measurement falls out of the base point count plus the
    programme configuration: the GOLD multiplier lifts 4000 base points to 5000,
    the snapshotted price turns those into a 6000 cent gross, the snapshotted
    breakage rate splits that into a 1500 cent reserve and 4500 cents of
    deferral, the tier uplift is expensed at 1200 cents, and the expiry horizon
    lands 730 whole days after issuance — none of which the request body carried.

    "`tier_multiplier_bp_at_issue` takes the programme's `tier_multiplier_bp` entry for the member's current `tier`."
    "`ssp_millicents_per_point_at_issue` takes the programme's `ssp_millicents_per_point`; it is immutable thereafter, so a later change of the programme's standalone selling price leaves this lot priced as it was issued."
    "`breakage_rate_bp_at_issue` takes the programme's `current_breakage_rate_bp` as it stands at this instant."
    "`issued_at` takes the current logical clock reading, and `expires_at` is set to `issued_at` advanced by the programme's `point_expiry_days` whole days."
    "`tier_points` is `base_points` multiplied by `tier_multiplier_bp_at_issue`, divided by 10000, and rounded half up to a whole number of points."
    "`points_remaining` starts equal to `points_issued`."
    "`gross_ssp_cents` is `points_issued` multiplied by `ssp_millicents_per_point_at_issue`, divided by 1000, rounded half up."
    "`breakage_reserve_cents` is `gross_ssp_cents` multiplied by `breakage_rate_bp_at_issue`, divided by 10000, rounded half up."
    "`deferred_revenue_cents` is `gross_ssp_cents` less `breakage_reserve_cents`, and it is this deferral — not the gross — that is added to the period's `issuance_deferred_cents`."
    "`tier_benefit_expense_cents` is the difference between `tier_points` and `base_points`, multiplied by `ssp_millicents_per_point_at_issue`, divided by 1000, rounded half up — and is therefore 0 for a `BASE` member."
    "`remaining_gross_ssp_cents` is `points_remaining` multiplied by `ssp_millicents_per_point_at_issue`, divided by 1000, rounded half up."
    "`remaining_deferred_cents` is that remaining gross less the reserve on the remaining gross — that is, less `remaining_gross_ssp_cents` multiplied by `breakage_rate_bp_at_issue`, divided by 10000, rounded half up."
    "The redemption-and-expiry dimension, `lifecycle_state`, is born `OUTSTANDING` and may reach `PARTIALLY_REDEEMED`, `FULLY_REDEEMED`, `EXPIRED` or `ESCHEATED`."
    "The partner-billing dimension, `settlement_state`, is born `NOT_APPLICABLE` when no partner was named, and is born `PENDING_SETTLEMENT` when one was — the dimension-two assignment `NOT_APPLICABLE → PENDING_SETTLEMENT` happens at creation, so a partner lot is born `PENDING_SETTLEMENT` on one dimension while being born `OUTSTANDING` on the other."

    Design: Corner/entities/entity_point_lot_computed_measurement_fields_derived_from_config
    """
    bundle = _issuance_ready(api, tier=TIER_GOLD)

    lot = assert_created(
        api.create_point_lot(
            factories.point_lot_payload(
                bundle["member"]["id"],
                bundle["period"]["id"],
                GOLD_BASE_POINTS,
                promo_multiplier_bp=IDENTITY_MULTIPLIER_BP,
            ),
            ACCOUNTANT_HEADERS,
        )
    )
    assert_representation_complete(lot, "PointLot")

    assert_fields(
        lot,
        base_points=GOLD_BASE_POINTS,
        tier_multiplier_bp_at_issue=GOLD_MULTIPLIER_BP,
        ssp_millicents_per_point_at_issue=DEFAULT_SSP_MILLICENTS_PER_POINT,
        breakage_rate_bp_at_issue=DEFAULT_SEEDED_BREAKAGE_RATE_BP,
        tier_points=GOLD_TIER_POINTS,
        points_issued=GOLD_POINTS_ISSUED,
        points_remaining=GOLD_POINTS_ISSUED,
        gross_ssp_cents=GOLD_GROSS_CENTS,
        breakage_reserve_cents=GOLD_RESERVE_CENTS,
        deferred_revenue_cents=GOLD_DEFERRED_CENTS,
        tier_benefit_expense_cents=GOLD_TIER_BENEFIT_EXPENSE_CENTS,
        promo_expense_cents=0,
        remaining_gross_ssp_cents=GOLD_GROSS_CENTS,
        remaining_deferred_cents=GOLD_DEFERRED_CENTS,
        issued_at=CLOCK_EPOCH,
        expires_at=GOLD_EXPIRES_AT,
        lifecycle_state=LOT_OUTSTANDING,
        settlement_state=SETTLEMENT_NOT_APPLICABLE,
    )
    assert_lot_split(lot)
    assert_utc_timestamp(lot, "issued_at", "expires_at")


def test_system_fields_minted_by_server_on_create(api):
    """
    An accounting period create supplies only the programme, the label and the
    window; the server mints the identifier, both audit timestamps and the
    opening version, opens the period, zeroes the reopen counter and starts every
    one of its rollforward and rate figures at 0.

    "Every resource carries a server-minted `id` — a UUID string with no type prefix — and a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits."
    "Programmes, state expiry rules, cohorts, members, accounting periods, partner agreements, point lots, redemption events, breakage estimates, settlement statements and programme change orders additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on each mutation of that resource."
    "A new period is born in `state` `OPEN`, with `reopen_count` at 0, with `soft_closed_at` null, and with all eleven of its currency and rate rollforward figures at 0: `opening_liability_cents`, `issuance_deferred_cents`, `redemption_recognized_cents`, `remeasurement_delta_cents`, `expiry_released_cents`, `escheat_accrual_cents`, `pre_catchup_liability_cents`, `required_liability_cents`, `catch_up_adjustment_cents`, `breakage_recognized_cents`, `closing_liability_cents` and `approved_estimate_rate_bp`."
    "Nothing in this system reads the machine's wall clock."

    Design: Corner/entities/entity_system_fields_minted_by_server_on_create
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    program, _cohort = _active_program(api)

    payload = factories.period_payload(program["id"])
    for minted in ("id", "created_at", "updated_at", "version", "state", "reopen_count"):
        assert minted not in payload, f"{minted} must not be a client input"

    period = assert_created(api.create_period(payload, CONTROLLER_HEADERS))
    assert_representation_complete(period, "AccountingPeriod")
    assert_utc_timestamp(period, "created_at", "updated_at")
    assert_null_fields(period, "soft_closed_at")

    assert_fields(
        period,
        program_id=program["id"],
        state=PERIOD_OPEN,
        reopen_count=0,
        version=1,
        created_at=CLOCK_EPOCH,
        updated_at=CLOCK_EPOCH,
        opening_liability_cents=0,
        issuance_deferred_cents=0,
        redemption_recognized_cents=0,
        remeasurement_delta_cents=0,
        expiry_released_cents=0,
        escheat_accrual_cents=0,
        pre_catchup_liability_cents=0,
        required_liability_cents=0,
        catch_up_adjustment_cents=0,
        breakage_recognized_cents=0,
        closing_liability_cents=0,
        approved_estimate_rate_bp=0,
    )


def test_program_invalid_breakage_method_enum_rejected(api):
    """
    breakage_method is an enumeration of exactly two methodologies, so a third
    name is a malformed request rejected before any programme row is written.

    "`breakage_method` is either `COHORT_WEIGHTED` or `PROGRAM_HISTORICAL` and defaults to `COHORT_WEIGHTED`."
    "**Request shape** — the body parses, every required input the endpoint declares is present, every value satisfies its declared type, enumeration and range constraint, and pagination parameters are in range. Otherwise `ERR_INVALID_REQUEST` (400), on every endpoint."

    Design: Corner/entities/entity_program_invalid_breakage_method_enum_rejected
    """
    fixtures.set_clock(api, CLOCK_EPOCH)

    assert_error(
        api.create_program(
            factories.program_payload(
                name="Bad Enum Core", breakage_method=UNRECOGNISED_BREAKAGE_METHOD
            ),
            PROGRAM_ADMIN_HEADERS,
        ),
        ApiErrorId.INVALID_REQUEST.value,
    )

    assert_page(api.list_programs(PROGRAM_ADMIN_HEADERS), expected_ids=[], total_count=0)


def test_program_historical_redemption_rate_above_its_range_rejected(api):
    """
    historical_redemption_rate_bp carries a declared band as well as a declared
    type, and a value one basis point above the ceiling fails the same
    request-shape rung the unrecognised enumeration fails, writing nothing.

    "Alongside it, `historical_redemption_rate_bp` — from 200 through 9800 inclusive — records the programme-level redemption rate observed to date; it is consumed directly by the programme-historical measurement and it is also what seeds the programme's live breakage rate at first activation."
    "**Request shape** — the body parses, every required input the endpoint declares is present, every value satisfies its declared type, enumeration and range constraint, and pagination parameters are in range. Otherwise `ERR_INVALID_REQUEST` (400), on every endpoint."

    Design: Corner/entities/entity_program_invalid_breakage_method_enum_rejected
    """
    fixtures.set_clock(api, CLOCK_EPOCH)

    assert_error(
        api.create_program(
            factories.program_payload(
                name="Out Of Band Core",
                historical_redemption_rate_bp=HISTORICAL_RATE_ABOVE_CEILING_BP,
            ),
            PROGRAM_ADMIN_HEADERS,
        ),
        ApiErrorId.INVALID_REQUEST.value,
    )

    assert_page(api.list_programs(PROGRAM_ADMIN_HEADERS), expected_ids=[], total_count=0)


def test_program_tier_multiplier_missing_platinum_key_rejected(api):
    """
    tier_multiplier_bp must declare exactly the four member tiers, so a map that
    leaves PLATINUM out is refused with the dedicated tier-key conflict rather
    than the generic malformed-request code, and no programme is written.

    "`tier_multiplier_bp` is an object of earn multipliers in basis points keyed by member tier, and it must declare exactly the four keys `BASE`, `SILVER`, `GOLD` and `PLATINUM` — no more, no fewer — each value an integer from 10000 through 50000 inclusive."
    "A key set that is not exactly those four is rejected with `ERR_TIER_MULTIPLIER_KEYS_INVALID`."
    "**Tier multiplier keys are exactly the four tiers** — `ERR_TIER_MULTIPLIER_KEYS_INVALID` (409), on programme create and change-order create."

    Design: Corner/entities/entity_program_tier_multiplier_missing_platinum_key_rejected
    """
    fixtures.set_clock(api, CLOCK_EPOCH)

    assert_error(
        api.create_program(
            factories.program_payload(
                name="Bad Tiers Core",
                tier_multiplier_bp=dict(THREE_KEY_TIER_MULTIPLIER_BP),
            ),
            PROGRAM_ADMIN_HEADERS,
        ),
        ApiErrorId.TIER_MULTIPLIER_KEYS_INVALID.value,
    )

    assert_page(api.list_programs(PROGRAM_ADMIN_HEADERS), expected_ids=[], total_count=0)


def test_program_tier_multiplier_extra_key_rejected(api):
    """
    The key set must match the four tiers exactly rather than merely contain
    them, so a fifth tier is refused with the same tier-key conflict as a missing
    tier and still writes nothing.

    "`tier_multiplier_bp` is an object of earn multipliers in basis points keyed by member tier, and it must declare exactly the four keys `BASE`, `SILVER`, `GOLD` and `PLATINUM` — no more, no fewer — each value an integer from 10000 through 50000 inclusive."
    "A key set that is not exactly those four is rejected with `ERR_TIER_MULTIPLIER_KEYS_INVALID`."

    Design: Corner/entities/entity_program_tier_multiplier_missing_platinum_key_rejected
    """
    fixtures.set_clock(api, CLOCK_EPOCH)

    assert_error(
        api.create_program(
            factories.program_payload(
                name="Bad Tiers Core 2",
                tier_multiplier_bp=dict(FIVE_KEY_TIER_MULTIPLIER_BP),
            ),
            PROGRAM_ADMIN_HEADERS,
        ),
        ApiErrorId.TIER_MULTIPLIER_KEYS_INVALID.value,
    )

    assert_page(api.list_programs(PROGRAM_ADMIN_HEADERS), expected_ids=[], total_count=0)


def test_redemption_allocation_immutable_has_no_version_field(api):
    """
    The allocation ledger row an allocation appends carries its own identifier
    and creation stamp, the junction's two foreign keys, its entry type, its
    sequence number and its three measured figures — but neither of the two
    system fields a mutable entity carries, because the journal is never
    rewritten. The same row is reachable from the lot side and from the event
    side, and its final release stays null until the event is fulfilled.

    "`RedemptionAllocation` rows are the exception."
    "They are append-only journal entries that are never modified after they are written, so they carry only `id` and `created_at`: both `updated_at` and `version` are absent from a `RedemptionAllocation` altogether."
    "Each consumed lot produces exactly one **RedemptionAllocation** row, an append-only journal entry that names its `redemption_event_id` and its `point_lot_id`, carries `entry_type` `ALLOCATION`, and is numbered by `allocation_seq` starting at 1 and increasing by 1 in consumption order."
    "The row records `points_allocated`, the positive count drawn from that lot, and `line_gross_ssp_cents`, being `points_allocated` multiplied by that lot's `ssp_millicents_per_point_at_issue`, divided by 1000, rounded half up."
    "It also records `provisional_release_cents` for the line: the line's gross less the reserve on that line, where the reserve is the line gross multiplied by **that lot's own** `breakage_rate_bp_at_issue`, divided by 10000, rounded half up."
    "The row's `final_release_cents` stays null until the event is fulfilled."
    "The journal is readable from either side."
    "`RedemptionAllocation` is immutable and has no collection of its own — it is reached only through the two sub-resource reads."

    Design: Corner/entities/entity_redemption_allocation_immutable_has_no_version_field
    """
    bundle = _issuance_ready(api)
    member_id = bundle["member"]["id"]
    period_id = bundle["period"]["id"]

    lot = fixtures.issue_lot(api, member_id, period_id, BASE_LOT_POINTS)
    event = fixtures.allocated_redemption(
        api, member_id, period_id, LINE_POINTS_ALLOCATED
    )

    from_lot = assert_page(
        api.list_lot_allocations(lot["id"], ACCOUNTANT_HEADERS, limit=10, offset=0),
        total_count=1,
    )
    row = from_lot[0]

    missing = [f for f in expected_fields("RedemptionAllocation") if f not in row]
    assert not missing, f"The allocation ledger row is missing {missing}"
    assert_immutable_common_fields(row)

    assert_fields(
        row,
        redemption_event_id=event["id"],
        point_lot_id=lot["id"],
        entry_type=ENTRY_TYPE_ALLOCATION,
        allocation_seq=1,
        points_allocated=LINE_POINTS_ALLOCATED,
        line_gross_ssp_cents=LINE_GROSS_CENTS,
        provisional_release_cents=LINE_GROSS_CENTS - LINE_RESERVE_CENTS,
    )
    assert row["provisional_release_cents"] == LINE_PROVISIONAL_CENTS
    assert_null_fields(row, "final_release_cents")

    # The junction reads identically from the event side.
    from_event = assert_page(
        api.list_redemption_allocations(event["id"], ACCOUNTANT_HEADERS),
        expected_ids=[row["id"]],
        total_count=1,
    )
    assert from_event[0] == row

    # entry_type isolates the original consumption row; no compensating row exists.
    assert_page(
        api.list_lot_allocations(
            lot["id"], ACCOUNTANT_HEADERS, entry_type=ENTRY_TYPE_ALLOCATION
        ),
        expected_ids=[row["id"]],
        total_count=1,
    )
    assert_page(
        api.list_lot_allocations(lot["id"], ACCOUNTANT_HEADERS, entry_type="REVERSAL"),
        expected_ids=[],
        total_count=0,
    )


def test_point_lot_period_from_other_program_rejected(api):
    """
    Both parents of the pairing exist, so pairing one programme's member with
    another programme's accounting period is a coherence conflict rather than a
    missing resource: the issuance is refused, nothing is booked into either
    programme, and repeating the very same body against the member's own period
    succeeds.

    "When a partner is named, that agreement must belong to the same programme as the member, else `ERR_AGREEMENT_PROGRAM_MISMATCH`; the named period must likewise belong to that programme, else `ERR_PERIOD_PROGRAM_MISMATCH`."
    "Whenever a period named in a request body must pair with a member, a partner agreement or a programme, it must belong to the same programme as its counterparty, and a cross-programme pairing is rejected with `ERR_PERIOD_PROGRAM_MISMATCH`."
    "**Period belongs to the same programme as its counterparty** — `ERR_PERIOD_PROGRAM_MISMATCH` (409), on point-lot issuance, redemption request, breakage-estimate create and statement create."
    "`issuance_deferred_cents` grows by each issued lot's `deferred_revenue_cents`."

    Design: Corner/entities/entity_point_lot_period_from_other_program_rejected
    """
    fixtures.set_clock(api, CLOCK_EPOCH)

    program_a, cohort_a = _active_program(api)
    member_a = fixtures.new_member(api, program_a["id"], cohort_a["id"])
    period_a = fixtures.new_period(api, program_a["id"])

    program_b, _cohort_b = _active_program(
        api, ssp_millicents_per_point=1500, point_expiry_days=365, per_issuance_point_cap=9000
    )
    period_b = fixtures.new_period(api, program_b["id"])

    crossed = factories.point_lot_payload(
        member_a["id"],
        period_b["id"],
        BASE_LOT_POINTS,
        promo_multiplier_bp=IDENTITY_MULTIPLIER_BP,
    )
    assert_error(
        api.create_point_lot(crossed, ACCOUNTANT_HEADERS),
        ApiErrorId.PERIOD_PROGRAM_MISMATCH.value,
    )

    assert_page(
        api.list_point_lots(ACCOUNTANT_HEADERS, period_id=period_b["id"]),
        expected_ids=[],
        total_count=0,
    )
    assert_page(
        api.list_point_lots(ACCOUNTANT_HEADERS, member_id=member_a["id"]),
        expected_ids=[],
        total_count=0,
    )

    untouched = assert_ok(api.get_period(period_b["id"], CONTROLLER_HEADERS))
    assert_fields(untouched, issuance_deferred_cents=0, version=1)
    holder = assert_ok(api.get_member(member_a["id"], ACCOUNTANT_HEADERS))
    assert_fields(holder, point_balance=0)

    # Only the cross-programme pairing was wrong.
    lot = assert_created(
        api.create_point_lot(
            dict(crossed, period_id=period_a["id"]), ACCOUNTANT_HEADERS
        )
    )
    assert_fields(
        lot,
        period_id=period_a["id"],
        points_issued=BASE_LOT_POINTS,
        deferred_revenue_cents=BASE_LOT_DEFERRED_CENTS,
    )


def test_member_cohort_from_other_program_rejected(api):
    """
    Enrolling a member of one programme into a cohort owned by another is refused
    with the cohort coherence conflict even though both the programme and the
    cohort resolve, no member row is written, and the same body naming the
    programme's own cohort enrols an ACTIVE member with an empty balance.

    "The `external_member_ref` must be unique within the programme (`ERR_DUPLICATE_CODE` otherwise), and the named cohort must belong to the same programme as the one named in the body, else `ERR_COHORT_PROGRAM_MISMATCH`."
    "**Cohort belongs to the same programme** — `ERR_COHORT_PROGRAM_MISMATCH` (409), on member enrolment and breakage-estimate create."
    "A new member is born with `status` `ACTIVE`, with `enrolled_at` set to the current logical clock reading, and with `last_activity_at` initialised to that same instant."
    "Three member figures are derived on read: `dormancy_days` is the whole number of days between `last_activity_at` and the current clock reading, computed by dividing the elapsed seconds by 86400 and discarding the fraction, and floored at 0; `point_balance` is the sum of `points_remaining` over the member's lots whose `lifecycle_state` is `OUTSTANDING` or `PARTIALLY_REDEEMED`; and `outstanding_gross_ssp_cents` is the sum, over that same set of lots, of each lot's `remaining_gross_ssp_cents`, with each lot rounded first and the rounded amounts then added."

    Design: Corner/entities/entity_member_cohort_from_other_program_rejected
    """
    fixtures.set_clock(api, CLOCK_EPOCH)

    program_a, cohort_a = _configured_program(api)
    _program_b, cohort_b = _configured_program(api)

    crossed = factories.member_payload(program_a["id"], cohort_b["id"])
    assert_error(
        api.create_member(crossed, ACCOUNTANT_HEADERS),
        ApiErrorId.COHORT_PROGRAM_MISMATCH.value,
    )

    assert_page(
        api.list_members(ACCOUNTANT_HEADERS, program_id=program_a["id"]),
        expected_ids=[],
        total_count=0,
    )

    member = assert_created(
        api.create_member(dict(crossed, cohort_id=cohort_a["id"]), ACCOUNTANT_HEADERS)
    )
    assert_representation_complete(member, "Member")
    assert_fields(
        member,
        program_id=program_a["id"],
        cohort_id=cohort_a["id"],
        status=MEMBER_ACTIVE,
        tier=TIER_BASE,
        enrolled_at=CLOCK_EPOCH,
        last_activity_at=CLOCK_EPOCH,
        dormancy_days=0,
        point_balance=0,
        outstanding_gross_ssp_cents=0,
    )


def test_graph_topology_one_redemption_spans_two_lots_via_junction(api):
    """
    A point lot and a redemption event meet many-to-many through the allocation
    journal: one 1500-point redemption over two 1000-point lots writes two rows,
    numbered 1 and 2 in first-in-first-out issuance order, the older lot drained
    whole and the newer one drawn down by the remainder. The event's provisional
    release is the sum of the two per-line releases, and the identical two rows
    are reachable one at a time from each lot.

    "Consumption is first-in-first-out."
    "The candidates are walked in order of `issued_at` ascending and then `created_at` ascending — never by identifier — so a lot recorded later but carrying an earlier issuance instant is still consumed first."
    "From each lot in turn the allocation draws the lesser of the points still needed and that lot's `points_remaining`, until `points_requested` is exhausted."
    "Each consumed lot produces exactly one **RedemptionAllocation** row, an append-only journal entry that names its `redemption_event_id` and its `point_lot_id`, carries `entry_type` `ALLOCATION`, and is numbered by `allocation_seq` starting at 1 and increasing by 1 in consumption order."
    "The event's own `provisional_release_cents` is the sum of the per-line provisional releases — each line rounded first, then the rounded amounts added."
    "A lot that was `OUTSTANDING` and gives up exactly its `points_remaining` moves `OUTSTANDING → FULLY_REDEEMED`, with `points_remaining` set to 0, one `ALLOCATION` row appended, and its `version` incremented by 1."
    "A lot that was `OUTSTANDING` and gives up a positive count strictly fewer than its `points_remaining` moves `OUTSTANDING → PARTIALLY_REDEEMED`, with `points_remaining` decremented by the amount drawn, one `ALLOCATION` row appended, and the lot's `version` incremented by 1."
    "The allocation also sets `allocated_at` to the clock reading and measures the partner cost leg, which is independent of the revenue legs: when the event names a `partner_agreement_id`, `partner_cost_cents` is `points_requested` multiplied by that agreement's `redemption_rate_millicents_per_point`, divided by 1000, rounded half up; when no partner is named it is 0."
    "The rows that consumed or restored one lot can be read as a sub-resource of that lot, and the rows belonging to one event can be read as a sub-resource of that event; both reads accept `entry_type` as a filter so an auditor can look at the original consumption alone or the compensating entries alone, and both return rows ordered by `allocation_seq` ascending then `created_at` ascending."

    Design: Corner/entities/entity_graph_topology_one_redemption_spans_two_lots_via_junction
    """
    bundle = _issuance_ready(api)
    member_id = bundle["member"]["id"]
    period_id = bundle["period"]["id"]

    lot_a = fixtures.issue_lot(api, member_id, period_id, BASE_LOT_POINTS)
    fixtures.set_clock(api, AUG_02)
    lot_b = fixtures.issue_lot(api, member_id, period_id, BASE_LOT_POINTS)

    event = fixtures.allocated_redemption(
        api, member_id, period_id, SPAN_POINTS_REQUESTED
    )
    assert_fields(
        event,
        state=REDEMPTION_ALLOCATED,
        points_requested=SPAN_POINTS_REQUESTED,
        provisional_release_cents=SPAN_EVENT_PROVISIONAL_CENTS,
        partner_cost_cents=0,
        allocated_at=AUG_02,
    )

    rows = assert_page(
        api.list_redemption_allocations(event["id"], ACCOUNTANT_HEADERS),
        total_count=2,
    )
    assert_allocation_seq_ascending(rows)

    assert_fields(
        rows[0],
        redemption_event_id=event["id"],
        point_lot_id=lot_a["id"],
        entry_type=ENTRY_TYPE_ALLOCATION,
        allocation_seq=1,
        points_allocated=SPAN_LINE_1_POINTS,
        line_gross_ssp_cents=SPAN_LINE_1_GROSS_CENTS,
        provisional_release_cents=SPAN_LINE_1_PROVISIONAL_CENTS,
    )
    assert_fields(
        rows[1],
        redemption_event_id=event["id"],
        point_lot_id=lot_b["id"],
        entry_type=ENTRY_TYPE_ALLOCATION,
        allocation_seq=2,
        points_allocated=SPAN_LINE_2_POINTS,
        line_gross_ssp_cents=SPAN_LINE_2_GROSS_CENTS,
        provisional_release_cents=SPAN_LINE_2_PROVISIONAL_CENTS,
    )
    assert (
        rows[0]["provisional_release_cents"] + rows[1]["provisional_release_cents"]
        == event["provisional_release_cents"]
    ), "The event's provisional release must be the sum of its per-line releases"

    drained = assert_ok(api.get_point_lot(lot_a["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        drained,
        lifecycle_state=LOT_FULLY_REDEEMED,
        points_issued=BASE_LOT_POINTS,
        points_remaining=0,
    )
    partial = assert_ok(api.get_point_lot(lot_b["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        partial,
        lifecycle_state=LOT_PARTIALLY_REDEEMED,
        points_issued=BASE_LOT_POINTS,
        points_remaining=SPAN_LINE_2_POINTS,
    )

    # The same two rows, one apiece, traversed from the lot side of the junction.
    assert_page(
        api.list_lot_allocations(lot_a["id"], ACCOUNTANT_HEADERS),
        expected_ids=[rows[0]["id"]],
        total_count=1,
    )
    assert_page(
        api.list_lot_allocations(lot_b["id"], ACCOUNTANT_HEADERS),
        expected_ids=[rows[1]["id"]],
        total_count=1,
    )

    holder = assert_ok(api.get_member(member_id, ACCOUNTANT_HEADERS))
    assert_fields(
        holder,
        point_balance=SPAN_BALANCE_AFTER,
        outstanding_gross_ssp_cents=SPAN_LINE_2_GROSS_CENTS,
    )
