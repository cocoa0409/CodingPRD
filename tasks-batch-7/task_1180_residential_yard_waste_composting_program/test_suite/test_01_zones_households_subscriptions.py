"""Zones, households, season signup, and subscription fee computation."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_household,
    assert_service_zone,
    assert_subscription,
    create_cart,
    create_household,
    create_household_payload,
    create_service_zone_payload,
    create_subscription,
    create_subscription_payload,
    create_zone,
    get_household,
    get_subscription,
    get_success_data,
    make_resident_headers,
    set_clock,
    setup_active_household,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Queue A: dual_variant_calc / fee_optin_vs_universal_same_cart_config
# ---------------------------------------------------------------------------

def test_fee_variant_diverges_on_lifecycle_at_creation(api, admin_headers):
    """PRD section 3.2: "For a `UNIVERSAL` subscription the base fee is zero —
    base service is covered by utility billing — though cart fees and surcharges
    still apply." and "A subscription in a universal zone activates immediately
    at creation — its `status` starts at `ACTIVE`. An opt-in subscription starts
    at `PENDING_PAYMENT` and must be paid."

    Design: Difficulty/dual_variant_calc/fee_optin_vs_universal_same_cart_config
    """
    set_clock("2026-04-15T00:00:00Z")
    zone_o = create_zone(set_clock_first=False, name="North", service_model="OPT_IN",
                         base_seasonal_fee_cents=12000, universal_flat_credit_cents=500)
    zone_u = create_zone(set_clock_first=False, name="South", service_model="UNIVERSAL",
                         base_seasonal_fee_cents=9000, universal_flat_credit_cents=500)
    hh_a = create_household(zone_o["id"], "1 Oak St")
    hh_b = create_household(zone_u["id"], "2 Elm St")

    sub_a = create_subscription(hh_a, season_year=2026)
    sub_b = create_subscription(hh_b, season_year=2026)

    assert_subscription(sub_a)
    assert sub_a["base_fee_cents"] == 12000
    assert sub_a["total_due_cents"] == 12000
    assert sub_a["status"] == "PENDING_PAYMENT"
    assert_subscription(sub_b)
    assert sub_b["base_fee_cents"] == 0
    assert sub_b["total_due_cents"] == 0
    assert sub_b["status"] == "ACTIVE"


def test_fee_variant_diverges_on_amount_with_identical_carts(api, admin_headers):
    """PRD section 3.2: "For a `UNIVERSAL` subscription the base fee is zero —
    base service is covered by utility billing — though cart fees and surcharges
    still apply." PRD section 3.3: "a 64-gallon cart adds 1500 cents ($15.00)".
    Identical 64-gallon cart configuration yields total_due_cents 13500 in the
    opt-in zone but 1500 in the universal zone.

    Design: Difficulty/dual_variant_calc/fee_optin_vs_universal_same_cart_config
    """
    ctx_o = setup_active_household(service_model="OPT_IN", address_line="1 Oak St",
                                   base_seasonal_fee_cents=12000)
    ctx_u = setup_active_household(service_model="UNIVERSAL", address_line="2 Elm St",
                                   base_seasonal_fee_cents=9000)
    create_cart(ctx_o["household"], ctx_o["subscription"]["id"], 64)
    create_cart(ctx_u["household"], ctx_u["subscription"]["id"], 64)

    sub_a = get_subscription(ctx_o["subscription"]["id"])
    sub_b = get_subscription(ctx_u["subscription"]["id"])

    assert sub_a["base_fee_cents"] == 12000
    assert sub_a["cart_fees_cents"] == 1500
    assert sub_a["total_due_cents"] == 13500
    assert sub_b["base_fee_cents"] == 0
    assert sub_b["cart_fees_cents"] == 1500
    assert sub_b["total_due_cents"] == 1500
    assert sub_a["total_due_cents"] != sub_b["total_due_cents"]


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula / fee_proration_tiered_carts_extra_fee
# ---------------------------------------------------------------------------

def test_mid_season_signup_prorates_base_fee(api, admin_headers):
    """PRD section 3.2: "signing up mid-season prorates: the season length in
    weeks is computed as the number of days in the season window divided by
    seven and rounded up to a whole week, the remaining full weeks are computed
    as the days from the signup date to `season_end_date` divided by seven and
    rounded down, and the billed base fee is the zone's base fee multiplied by
    the remaining full weeks, divided by the season weeks, and floored to whole
    cents." 183-day season -> 27 weeks; signup 2026-07-01 -> 122 days remain ->
    17 full weeks; floor(12000 x 17 / 27) = 7555.

    Design: Difficulty/combinatorial_formula/fee_proration_tiered_carts_extra_fee
    """
    zone = create_zone(clock="2026-04-15T00:00:00Z", service_model="OPT_IN",
                       base_seasonal_fee_cents=12000)
    household = create_household(zone["id"])
    set_clock("2026-07-01T00:00:00Z")
    sub = create_subscription(household, season_year=2026)

    assert_subscription(sub)
    assert sub["base_fee_cents"] == 7555
    assert sub["surcharge_cents"] == 0


def test_prorated_fee_combines_tiered_carts_and_extra_fee(api, admin_headers):
    """PRD section 3.3: "a 35-gallon cart carries no surcharge, a 64-gallon cart
    adds 1500 cents ($15.00), and a 96-gallon cart adds 3000 cents ($30.00)" and
    "then add an extra-cart fee of 2500 cents ($25.00) for every cart beyond the
    first — the first cart is exempt from the extra-cart fee." PRD section 3.2:
    "The `total_due_cents` is the sum of these three components". Prorated base
    7555 + (1500 + 3000 + 2500) = 14555.

    Design: Difficulty/combinatorial_formula/fee_proration_tiered_carts_extra_fee
    """
    zone = create_zone(clock="2026-04-15T00:00:00Z", service_model="OPT_IN",
                       base_seasonal_fee_cents=12000)
    household = create_household(zone["id"])
    set_clock("2026-07-01T00:00:00Z")
    sub = create_subscription(household, season_year=2026)
    sub = get_success_data(api.pay_subscription(
        sub["id"], {"use_credit_balance": False}, make_resident_headers(household["id"])))
    assert sub["status"] == "ACTIVE"

    create_cart(household, sub["id"], 64)
    create_cart(household, sub["id"], 96)

    sub = get_subscription(sub["id"])
    assert sub["base_fee_cents"] == 7555
    assert sub["cart_fees_cents"] == 7000
    assert sub["surcharge_cents"] == 0
    assert sub["total_due_cents"] == 14555


# ---------------------------------------------------------------------------
# Queue B: entities section
# ---------------------------------------------------------------------------

def test_zone_create_applies_defaults_and_default_clock_status(api, admin_headers):
    """PRD section 2.4: "Before any such call, the server's startup default is
    exactly `2026-05-01T00:00:00Z`." PRD section 3.1: "optionally
    `max_strikes_per_season`, which defaults to 3 when omitted." With the clock
    never set (2026-05-01), a zone whose season starts 2026-06-01 reads
    OPEN_ENROLLMENT.

    Design: Corner/entities/zone_create_applies_defaults_and_default_clock_status
    """
    payload = create_service_zone_payload(
        name="East", season_start_date="2026-06-01", season_end_date="2026-10-31",
        base_seasonal_fee_cents=10000, universal_flat_credit_cents=400)
    del payload["max_strikes_per_season"]  # omitted -> default 3
    # NOTE: the logical clock is intentionally never set in this test.
    zone = validate_success(api.create_service_zone(payload, admin_headers), 201)

    assert_service_zone(zone)
    assert zone["status"] == "OPEN_ENROLLMENT"
    assert zone["max_strikes_per_season"] == 3
    assert zone["version"] == 1


def test_household_create_initial_state(api, admin_headers, anonymous_headers):
    """PRD section 3.1: "Each household carries two derived figures that follow
    it through the season: `credit_balance_cents`, the sum of the household's
    granted service credits, and `compost_entitlement_gallons`, the household's
    season compost entitlement at two decimal places." A new household has no
    granted credits and no completed pickups, so both figures are zero.

    Design: Corner/entities/household_create_initial_state
    """
    zone = create_zone()
    household = validate_success(
        api.create_household(create_household_payload(zone["id"], address_line="1 Oak St"),
                             anonymous_headers), 201)

    assert_household(household)
    assert household["credit_balance_cents"] == 0
    assert household["compost_entitlement_gallons"] == 0
    assert household["version"] == 1


def test_subscription_create_computes_fee_and_pending_state(api, admin_headers):
    """PRD section 3.2: "For an `OPT_IN` subscription, signing up on or before
    `season_start_date` bills the zone's full `base_seasonal_fee_cents`" and
    "An opt-in subscription starts at `PENDING_PAYMENT` and must be paid." and
    "At creation the subscription pins a snapshot of the zone's `service_model`".

    Design: Corner/entities/subscription_create_computes_fee_and_pending_state
    """
    zone = create_zone(service_model="OPT_IN", base_seasonal_fee_cents=12000)
    household = create_household(zone["id"])
    sub = create_subscription(household, season_year=2026)

    assert_subscription(sub)
    assert sub["base_fee_cents"] == 12000
    assert sub["total_due_cents"] == 12000
    assert sub["status"] == "PENDING_PAYMENT"
    assert sub["service_model"] == "OPT_IN"


def test_household_create_missing_required_field(api, admin_headers, anonymous_headers):
    """PRD section 2.8: "Required fields are present, types are correct, enum
    members are valid, and ranges hold: `gallons` at least 1,
    `quantity_bundles` between 1 and 10 inclusive, `weight_lbs` greater than 0,
    `window_end` later than `window_start`, `violation_codes` non-empty exactly
    when the inspection result is a tagged outcome, a ticket's `service_date`
    weekday matching the route's weekday, a route's effective window inside its
    zone's season window, and no unknown fields. Any violation yields
    `ERR_INVALID_REQUEST`." PRD section 3.1: "an `Anonymous` caller provides an
    `address_line` and the `zone_id` of the zone the address belongs to".

    Design: Corner/entities/household_create_missing_required_field
    """
    zone = create_zone()
    res = api.create_household({"address_line": "1 Oak St"}, anonymous_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_household_get_not_found_returns_404(api, admin_headers):
    """PRD section 2.8: "A missing household yields `ERR_HOUSEHOLD_NOT_FOUND`".

    Design: Corner/entities/household_get_not_found_returns_404
    """
    res = api.get_household(NON_EXISTENT_UUID, admin_headers)
    validate_error(res, ApiErrorId.ERR_HOUSEHOLD_NOT_FOUND)


def test_household_create_with_extra_field_rejected(api, admin_headers, anonymous_headers):
    """PRD section 2.8: "and no unknown fields. Any violation yields
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/household_create_with_extra_field_rejected
    """
    zone = create_zone()
    payload = create_household_payload(zone["id"], address_line="1 Oak St")
    payload["id"] = NON_EXISTENT_UUID  # server-minted field supplied by client
    res = api.create_household(payload, anonymous_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_zone_status_derived_from_clock(api, admin_headers):
    """PRD section 2.4: "A service zone reads `OPEN_ENROLLMENT` when the clock
    date falls before `season_start_date`, `IN_SEASON` from `season_start_date`
    through `season_end_date` inclusive, and `OFF_SEASON` once the clock date
    passes `season_end_date`."

    Design: Corner/entities/zone_status_derived_from_clock
    """
    zone = create_zone(clock="2026-04-15T00:00:00Z", season_start_date="2026-05-01",
                       season_end_date="2026-10-31")

    z1 = validate_success(api.get_service_zone(zone["id"], admin_headers), 200)
    assert z1["status"] == "OPEN_ENROLLMENT"

    set_clock("2026-05-20T00:00:00Z")
    z2 = validate_success(api.get_service_zone(zone["id"], admin_headers), 200)
    assert z2["status"] == "IN_SEASON"

    set_clock("2026-11-01T00:00:00Z")
    z3 = validate_success(api.get_service_zone(zone["id"], admin_headers), 200)
    assert z3["status"] == "OFF_SEASON"


# ---------------------------------------------------------------------------
# Queue B: state_machines / calculations / validations / cross-cutting
# ---------------------------------------------------------------------------

def test_subscription_terminal_lockdown_cancelled(api, admin_headers):
    """PRD section 3.2: "A resident (or a `ProgramAdmin`) may cancel a
    subscription while it is `PENDING_PAYMENT`, `ACTIVE`, or `SUSPENDED`, moving
    it to `CANCELLED`." and "`CANCELLED` and `EXPIRED` are terminal." and
    "paying a subscription that is not `PENDING_PAYMENT` or `ACTIVE` is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/subscription_terminal_lockdown_cancelled
    """
    zone = create_zone()
    household = create_household(zone["id"])
    sub = create_subscription(household, season_year=2026)

    cancelled = validate_success(
        api.cancel_subscription(sub["id"], make_resident_headers(household["id"])), 200)
    assert cancelled["status"] == "CANCELLED"

    res1 = api.cancel_subscription(sub["id"], make_resident_headers(household["id"]))
    validate_error(res1, ApiErrorId.ERR_INVALID_STATE)

    res2 = api.pay_subscription(sub["id"], {"use_credit_balance": False},
                                make_resident_headers(household["id"]))
    validate_error(res2, ApiErrorId.ERR_INVALID_STATE)


def test_proration_full_fee_at_season_start(api, admin_headers):
    """PRD section 3.2: "For an `OPT_IN` subscription, signing up on or before
    `season_start_date` bills the zone's full `base_seasonal_fee_cents`".
    Signup with the clock exactly on 2026-05-01 (season start) is not prorated.

    Design: Corner/calculations/proration_full_fee_at_season_start
    """
    zone = create_zone(set_clock_first=False, service_model="OPT_IN",
                       base_seasonal_fee_cents=12000)
    household = create_household(zone["id"])
    set_clock("2026-05-01T00:00:00Z")
    sub = create_subscription(household, season_year=2026)

    assert sub["base_fee_cents"] == 12000


def test_duplicate_subscription_same_season(api, admin_headers):
    """PRD section 3.2: "A household may hold at most one non-terminal
    subscription per `season_year` — a second signup while an earlier
    subscription for the same year is still `PENDING_PAYMENT`, `ACTIVE`, or
    `SUSPENDED` fails with `ERR_DUPLICATE_SUBSCRIPTION`."

    Design: Corner/validations/duplicate_subscription_same_season
    """
    zone = create_zone()
    household = create_household(zone["id"])
    create_subscription(household, season_year=2026)

    current = get_household(household["id"])
    res = api.create_subscription(
        create_subscription_payload(household["id"], current["version"], season_year=2026),
        make_resident_headers(household["id"]),
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_SUBSCRIPTION)


def test_enrollment_window_closed_off_season(api, admin_headers):
    """PRD section 3.2: "Signup is only accepted while the household's zone is
    `OPEN_ENROLLMENT` or `IN_SEASON`; once the zone turns `OFF_SEASON`,
    enrollment attempts are rejected with `ERR_ENROLLMENT_WINDOW_CLOSED`."

    Design: Corner/validations/enrollment_window_closed_off_season
    """
    zone = create_zone()
    household = create_household(zone["id"])
    set_clock("2026-11-05T00:00:00Z")

    res = api.create_subscription(
        create_subscription_payload(household["id"], household["version"], season_year=2026),
        make_resident_headers(household["id"]),
    )
    validate_error(res, ApiErrorId.ERR_ENROLLMENT_WINDOW_CLOSED)


def test_zone_window_patch_in_season_rejected(api, admin_headers):
    """PRD section 3.1: "the season window fields `season_start_date` and
    `season_end_date` may only be changed while the zone is `OFF_SEASON`;
    attempting to move the window of an `OPEN_ENROLLMENT` or `IN_SEASON` zone is
    rejected with `ERR_INVALID_STATE`. Setting a new, future season window on an
    `OFF_SEASON` zone is exactly how the zone cycles back to `OPEN_ENROLLMENT`
    for the next year."

    Design: Corner/state_machines/zone_window_patch_in_season_rejected
    """
    zone = create_zone(clock="2026-04-15T00:00:00Z")
    set_clock("2026-05-20T00:00:00Z")  # IN_SEASON

    res = api.update_service_zone(zone["id"], {"season_start_date": "2026-05-15"}, admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    set_clock("2026-11-05T00:00:00Z")  # OFF_SEASON
    updated = validate_success(api.update_service_zone(
        zone["id"], {"season_start_date": "2027-05-01", "season_end_date": "2027-10-31"},
        admin_headers), 200)
    assert updated["season_start_date"] == "2027-05-01"
    assert updated["status"] == "OPEN_ENROLLMENT"


def test_zone_fee_patch_increments_version_and_preserves_snapshots(api, admin_headers):
    """PRD section 3.1: "every zone update increments the zone's `version` by
    one." PRD section 3.2: "At creation the subscription pins a snapshot of the
    zone's `service_model`; later edits to the zone never retroactively change
    existing subscriptions."

    Design: Corner/cross_cutting_layers/zone_fee_patch_increments_version_and_preserves_snapshots
    """
    zone = create_zone(service_model="OPT_IN", base_seasonal_fee_cents=12000)
    assert zone["version"] == 1
    household = create_household(zone["id"])
    sub = create_subscription(household, season_year=2026)
    assert sub["base_fee_cents"] == 12000

    updated = validate_success(
        api.update_service_zone(zone["id"], {"base_seasonal_fee_cents": 13000}, admin_headers), 200)
    assert updated["version"] == zone["version"] + 1
    assert updated["base_seasonal_fee_cents"] == 13000

    sub_after = get_subscription(sub["id"])
    assert sub_after["base_fee_cents"] == 12000


def test_occ_subscription_create_stale_version(api, admin_headers):
    """PRD section 2.6: "Creating a subscription requires the request to carry
    `expected_household_version` holding the client-observed `version` of the
    target household. If the household's current `version` has advanced since
    the client last read it — for example because another subscription for a
    different season year was just created, or a credit approval changed the
    household — the create is rejected with `ERR_STALE_VERSION` (HTTP 412),
    forcing the client to re-read the household before enrolling."

    Design: Corner/cross_cutting_layers/occ_subscription_create_stale_version
    """
    zone = create_zone()
    household = create_household(zone["id"])
    assert household["version"] == 1
    stale_version = household["version"]

    sub_2026 = create_subscription(household, season_year=2026)
    assert sub_2026["status"] == "PENDING_PAYMENT"

    # The first create advanced Household.version to 2; replaying version 1 is stale.
    res = api.create_subscription(
        create_subscription_payload(household["id"], stale_version, season_year=2027),
        make_resident_headers(household["id"]),
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    current = get_household(household["id"])
    assert current["version"] == 2

    sub_2027 = validate_success(api.create_subscription(
        create_subscription_payload(household["id"], current["version"], season_year=2027),
        make_resident_headers(household["id"])), 201)
    assert sub_2027["status"] == "PENDING_PAYMENT"
    assert get_household(household["id"])["version"] == 3
