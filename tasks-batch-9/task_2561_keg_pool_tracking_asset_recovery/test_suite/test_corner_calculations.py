"""Derived quantities read at the corners of their own arithmetic.

Each scenario builds the exact history a formula reads — a dwell spell, a
billed running total, an index series, a fill count, a census — and then reads
the single figure the contract derives from it, together with the neighbouring
figure that proves the boundary was taken the declared way rather than the
plausible one.
"""

from test_helpers import (
    api_client,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_census
from test_helpers.test_users import (
    ANALYST_USER_ID,
    SECOND_TECHNICIAN_USER_ID,
    TECHNICIAN_USER_ID,
    TEST_USERS,
    make_analyst_headers,
    make_brewer_headers,
    make_technician_headers,
)

OPERATOR = TEST_USERS["pool_operator_headers"]
TECHNICIAN = make_technician_headers(TECHNICIAN_USER_ID)
SECOND_TECHNICIAN = make_technician_headers(SECOND_TECHNICIAN_USER_ID)
ANALYST = make_analyst_headers(ANALYST_USER_ID)

POOL = {
    "pool_code": "HB-50L",
    "size_liters": 50,
    "stainless_weight_kg": 12.5,
    "replacement_cost_cents": 23500,
    "region_code": "CO",
}

RATE = 2200


def _a_fill_recorded_thirty_days_and_twenty_three_hours_late():
    """One keg dispatched at the very start of August and filled at eleven at
    night on the thirty-first: a spell of thirty days and twenty-three hours.
    """
    fixtures.pin_clock("2026-08-31T23:00:00Z")
    index = fixtures.post_index("2026-07-01", 480)
    brewer = fixtures.create_brewer()
    pool = fixtures.create_pool(**POOL)
    kegs = fixtures.import_kegs(pool["id"], ["K-0001", "K-0002"])
    agreement = fixtures.create_and_activate_agreement(
        brewer["id"], pool["id"], 2, effective_date="2026-08-01", per_fill_rate_cents=RATE
    )
    order = fixtures.order_allocated_and_dispatched(
        agreement["id"], 1, "2026-08-01T00:00:00Z"
    )
    keg_id = order["allocated_keg_ids"][0]
    scan = validate_success(
        api_client.scan_keg(
            keg_id,
            factories.fill_scan_payload(brewer["id"], "2026-08-31T23:00:00Z", "RDG"),
            make_brewer_headers(brewer["id"]),
        ),
        201,
    )
    return {
        "index": index,
        "brewer": brewer,
        "pool": pool,
        "kegs": kegs,
        "agreement": agreement,
        "order": order,
        "keg_id": keg_id,
        "scan": scan,
    }


def test_a_thirty_day_twenty_three_hour_spell_floors_to_thirty_whole_days():
    """The remainder is discarded rather than rounded, so the spell reads thirty
    days: the surcharge excess is zero and the fill costs the bare base rate,
    where a thirty-first day would have added thirty cents.

    PRD: "Elapsed time in days is always computed by taking the difference
    between two instants in seconds, dividing by 86400 and discarding the
    remainder — that is, flooring to whole days."

    PRD: "A spell of twenty-nine days and twenty-three hours is twenty-nine days,
    never thirty."

    PRD: "Next, the raw dwell surcharge: the number of whole days the brewer has
    held the keg at the moment of the scan, less the thirty-day brewer dwell
    allowance, floored at zero, multiplied by 30 cents per excess day."

    Design: Corner/calculations/dwell_days_floors_a_thirty_day_twenty_three_hour_spell_to_thirty
    """
    ctx = _a_fill_recorded_thirty_days_and_twenty_three_hours_late()
    scan = ctx["scan"]

    assert scan["dwell_days_closed"] == 30
    assert scan["dwell_days_closed"] != 31
    assert scan["fill_charge_net_cents"] == 2200
    assert scan["is_late_arrival"] is False
    assert scan["recorded_at"] == "2026-08-31T23:00:00Z"

    keg = fixtures.read_keg(ctx["keg_id"])
    assert keg["cumulative_dwell_days"] == 30
    assert keg["custody_state"] == "FILLED"
    assert keg["fill_count"] == 1


def test_the_scan_never_promotes_the_dwell_flag_and_restarts_the_brewer_clock():
    """Thirty days is exactly the brewer limit and the scan still leaves the flag
    `WITHIN_LIMIT` — only the sweep reclassifies — while the fill resets the
    brewer clock, so the on-demand read of the newly opened spell is zero days
    against the same thirty-day limit.

    PRD: "The keg's `dwell_flag` classifies the *open* spell, and — this is
    important — no scan ever sets it to `APPROACHING` or `OVERDUE`."

    PRD: "Given the applicable limit, the open spell reads `OVERDUE` when its
    whole-day length is **strictly greater** than the limit, `APPROACHING` when it
    is at or beyond the approaching point but not over the limit, and
    `WITHIN_LIMIT` otherwise."

    PRD: "a keg in `ISSUED_TO_BREWER` or `FILLED` is measured on the brewer clock
    against a limit of 30 days with an approaching point at 24 days"

    PRD: "An accepted fill appends the scan, raises the keg's `fill_count` by one,
    records `filled_brand_code` from `brand_code_scanned` and `filling_brewer_id`
    from `brewer_id`, closes the open custody spell in the manner described above,
    resets `dwell_started_at` to `scanned_at`, and clears `misdelivery_open` —
    refilling a keg is what settles any unreconciled cross-brand history on it."

    Design: Corner/calculations/dwell_days_floors_a_thirty_day_twenty_three_hour_spell_to_thirty
    """
    ctx = _a_fill_recorded_thirty_days_and_twenty_three_hours_late()

    keg = fixtures.read_keg(ctx["keg_id"])
    assert keg["dwell_flag"] == "WITHIN_LIMIT"
    assert keg["dwell_started_at"] == "2026-08-31T23:00:00Z"

    dwell = validate_success(api_client.get_keg_dwell(ctx["keg_id"], OPERATOR))
    assert dwell["brewer_spell_days"] == 0
    assert dwell["limit_days"] == 30
    assert dwell["approaching_days"] == 24
    assert dwell["cumulative_dwell_days"] == 30

    agreement = fixtures.read_agreement(ctx["agreement"]["id"])
    assert agreement["billed_amount_cents"] == 2200
    assert agreement["billed_fills_count"] == 1
    assert fixtures.read_brewer(ctx["brewer"]["id"])["lifetime_fill_count"] == 1


def _a_second_dispatch_backdated_behind_the_last_scan():
    """One keg run through a whole cycle — dispatch, fill, distribution, return,
    wash line, release — and then issued again on an order whose `dispatched_at`
    is backdated to a day *before* the return scan that closed the first cycle.

    That is the only way to reach a fill which is admissible against the custody
    interval and yet strictly earlier than the keg's high-water mark.
    """
    fixtures.pin_clock("2026-08-20T23:00:00Z")
    index = fixtures.post_index("2026-07-01", 480)
    brewer = fixtures.create_brewer()
    distributor = fixtures.create_distributor(name="High Plains Distributing")
    pool = fixtures.create_pool(**POOL)
    first_keg = fixtures.import_keg(pool["id"], "K-0001")
    fixtures.import_keg(
        pool["id"], "K-0002", fill_count=5, fills_at_last_pressure_test=5
    )
    center = fixtures.create_service_center(2, name="Denver Wash Bay")
    agreement = fixtures.create_and_activate_agreement(
        brewer["id"], pool["id"], 2, effective_date="2026-08-01", per_fill_rate_cents=RATE
    )

    first_order = fixtures.order_allocated_and_dispatched(
        agreement["id"], 1, "2026-08-02T00:00:00Z"
    )
    keg_id = first_order["allocated_keg_ids"][0]
    fixtures.fill_scan(keg_id, brewer["id"], "2026-08-05T00:00:00Z", "RDG")
    fixtures.distribution_scan(
        keg_id, distributor["id"], "2026-08-08T00:00:00Z", "RDG"
    )
    fixtures.return_scan(keg_id, distributor["id"], "2026-08-10T00:00:00Z", "RDG")

    cycle = fixtures.create_service_cycle(
        keg_id, center["id"], "2026-08-10T01:00:00Z", headers=TECHNICIAN
    )
    fixtures.record_clean(cycle["id"], "2026-08-10T02:00:00Z", caustic_cycle_minutes=15)
    fixtures.record_inspect(cycle["id"], "2026-08-10T03:00:00Z", inspection_result="PASS")
    fixtures.record_pressure_test(
        cycle["id"],
        "2026-08-10T04:00:00Z",
        pressure_test_psi=45,
        pressure_test_result="PASS",
    )
    fixtures.release_cycle(
        cycle["id"], "2026-08-10T05:00:00Z", headers=SECOND_TECHNICIAN
    )

    second_order = fixtures.create_order(agreement["id"], 1)
    second_order = fixtures.allocate_order(second_order["id"], agreement["id"])
    second_order = fixtures.dispatch_order(second_order["id"], "2026-08-09T00:00:00Z")

    late = validate_success(
        api_client.scan_keg(
            keg_id,
            factories.fill_scan_payload(brewer["id"], "2026-08-09T12:00:00Z", "RDG"),
            make_brewer_headers(brewer["id"]),
        ),
        201,
    )
    accruals, _meta = validate_paginated(
        api_client.list_return_incentives(
            OPERATOR, params={"distributor_id": distributor["id"]}
        )
    )
    return {
        "index": index,
        "brewer": brewer,
        "distributor": distributor,
        "pool": pool,
        "first_keg": first_keg,
        "center": center,
        "agreement": agreement,
        "first_order": first_order,
        "second_order": second_order,
        "keg_id": keg_id,
        "late_scan": late,
        "accruals": accruals,
    }


def test_a_backdated_dispatch_admits_a_fill_that_is_still_a_late_arrival():
    """The fill sits after the re-based custody start, so the interval guard lets
    it through, yet it is strictly earlier than the keg's last scan, so it is
    flagged late; a late arrival contributes zero dwell days rather than a
    negative number, and it is recorded at the clock, not at its own instant.

    PRD: "A scan is flagged `is_late_arrival` when the keg's `last_scanned_at` is
    already set and this scan's `scanned_at` is strictly earlier than it."

    PRD: "The spell clock is likewise clamped: `dwell_days_closed` is the
    difference between this scan's `scanned_at` and the keg's `dwell_started_at`,
    floored to whole days and floored at 0, so a late arrival contributes zero
    dwell days rather than a negative number, and `dwell_started_at` becomes
    whichever is later of its existing value and the new `scanned_at`."

    PRD: "Critically, every allocated keg's `dwell_started_at` is re-based to that
    same supplied `dispatched_at`, so the brewer's dwell clock starts when the
    truck left rather than when the operator got round to typing it in."

    Design: Corner/calculations/late_arrival_fill_after_a_backdated_dispatch_keeps_the_high_water_mark
    """
    ctx = _a_second_dispatch_backdated_behind_the_last_scan()
    late = ctx["late_scan"]

    assert late["scanned_at"] == "2026-08-09T12:00:00Z"
    assert late["is_late_arrival"] is True
    assert late["recorded_at"] == "2026-08-20T23:00:00Z"
    assert late["dwell_days_closed"] == 0
    assert late["custody_state_after"] == "FILLED"
    assert late["fill_charge_net_cents"] == 2200


def test_the_last_scanned_high_water_mark_never_rewinds_to_the_late_scan():
    """The keg's high-water mark stays on the return scan of the first cycle, so a
    later genuine scan cannot be made to look late; the counters, meanwhile, take
    the late row in full — four scans, two fills and eight accumulated dwell days.

    PRD: "The high-water mark never rewinds — `last_scanned_at` becomes whichever
    is later of its existing value and the new `scanned_at` — so a late arrival
    cannot make a subsequent genuine scan look late."

    PRD: "Every accepted scan raises the keg's `scan_count` by one, adds the newly
    closed `dwell_days_closed` into the keg's `cumulative_dwell_days`, and advances
    the keg's `version`."

    PRD: "The volume tier is then chosen using the agreement's already-billed
    `billed_amount_cents` **plus this fill's pre-discount amount**, so the current
    fill counts toward its own tier: a basis of at least 9000 cents earns a
    300-basis-point discount, a basis of at least 4500 cents earns 150 basis
    points, and anything less earns none, with both comparisons inclusive so a
    basis of exactly 9000 earns the higher rate."

    Design: Corner/calculations/late_arrival_fill_after_a_backdated_dispatch_keeps_the_high_water_mark
    """
    ctx = _a_second_dispatch_backdated_behind_the_last_scan()

    keg = fixtures.read_keg(ctx["keg_id"])
    assert keg["last_scanned_at"] == "2026-08-10T00:00:00Z"
    assert keg["last_scanned_at"] != "2026-08-09T12:00:00Z"
    assert keg["scan_count"] == 4
    assert keg["fill_count"] == 2
    assert keg["cumulative_dwell_days"] == 8
    assert keg["custody_state"] == "FILLED"

    assert ctx["first_order"]["allocated_keg_ids"] == [ctx["keg_id"]]
    assert ctx["second_order"]["allocated_keg_ids"] == [ctx["keg_id"]]

    agreement = fixtures.read_agreement(ctx["agreement"]["id"])
    assert agreement["billed_amount_cents"] == 4400
    assert agreement["billed_fills_count"] == 2


def test_the_none_tier_return_minted_a_zero_row_that_still_counts_as_a_return():
    """The first cycle's return was earned by a distributor that never signed a
    cooperation agreement, so the accrual is worth nothing at all and yet is still
    a row: the ledger stays at zero while the return statistics move.

    PRD: "A `NONE`-tier distributor still accrues rows, each with `incentive_cents`
    of 0, rather than accruing nothing at all — which matters, because those rows
    still advance the service history that drives promotion."

    PRD: "The cooperation factor is 0 basis points for a `NONE`-tier distributor,
    10000 for `BRONZE`, 11500 for `SILVER` and 13000 for `GOLD`, taken from the
    tier as it stands *at the moment of this scan*."

    PRD: "A `NONE`-tier distributor never auto-promotes; it must be moved to
    `BRONZE` by an explicit cooperation agreement first."

    Design: Corner/calculations/late_arrival_fill_after_a_backdated_dispatch_keeps_the_high_water_mark
    """
    ctx = _a_second_dispatch_backdated_behind_the_last_scan()

    assert len(ctx["accruals"]) == 1
    accrual = ctx["accruals"][0]
    assert accrual["accrual_type"] == "RETURN_DWELL"
    assert accrual["dwell_days"] == 2
    assert accrual["tier_pct_bp"] == 10000
    assert accrual["cooperation_multiplier_bp"] == 0
    assert accrual["incentive_cents"] == 0
    assert accrual["status"] == "ACCRUED"

    distributor = fixtures.read_distributor(ctx["distributor"]["id"])
    assert distributor["cooperation_tier"] == "NONE"
    assert distributor["total_returns_count"] == 1
    assert distributor["on_time_returns_count"] == 1
    assert distributor["incentive_accrual_cents"] == 0


def _two_fills_at_a_base_that_tips_the_tier_exactly():
    """Two kegs filled an hour apart on a float whose base rate is 2250 cents, so
    the second fill's tier basis lands on exactly 4500 — the inclusive edge of the
    first volume band.  Neither keg has dwelled a day, so no surcharge muddies the
    arithmetic.
    """
    fixtures.pin_clock("2026-08-01T23:00:00Z")
    index = fixtures.post_index("2026-07-01", 480)
    brewer = fixtures.create_brewer()
    pool = fixtures.create_pool(**POOL)
    kegs = fixtures.import_kegs(
        pool["id"], ["K-0001", "K-0002", "K-0003", "K-0004"]
    )
    agreement = fixtures.create_and_activate_agreement(
        brewer["id"], pool["id"], 4, effective_date="2026-08-01", per_fill_rate_cents=2250
    )
    order = fixtures.order_allocated_and_dispatched(
        agreement["id"], 2, "2026-08-01T01:00:00Z"
    )
    first_keg_id, second_keg_id = order["allocated_keg_ids"]
    first_scan = fixtures.fill_scan(
        first_keg_id, brewer["id"], "2026-08-01T02:00:00Z", "RDG"
    )
    billed_after_first = fixtures.read_agreement(agreement["id"])
    second_scan = fixtures.fill_scan(
        second_keg_id, brewer["id"], "2026-08-01T03:00:00Z", "RDG"
    )
    return {
        "index": index,
        "brewer": brewer,
        "pool": pool,
        "kegs": kegs,
        "agreement": agreement,
        "order": order,
        "first_keg_id": first_keg_id,
        "second_keg_id": second_keg_id,
        "first_scan": first_scan,
        "second_scan": second_scan,
        "agreement_after_first_fill": billed_after_first,
    }


def test_the_opening_fill_is_below_the_first_volume_band_and_pays_in_full():
    """With nothing billed yet the tier basis is the fill's own 2250, which is
    short of the 4500 band, so the charge is the base rate untouched and the
    ledger reads it back exactly.

    PRD: "The base is the agreement's current `per_fill_rate_cents` — taken from
    the agreement, not from the order's `per_fill_price_cents_pinned`."

    PRD: "Only after the charge has been computed is the ledger updated:
    `billed_amount_cents` grows by the net charge, `billed_fills_count` and the
    keg's `fill_count` each rise by one, and the brewer's `lifetime_fill_count`
    rises by one."

    Design: Corner/calculations/fill_charge_tier_basis_of_exactly_4500_earns_150_bp
    """
    ctx = _two_fills_at_a_base_that_tips_the_tier_exactly()

    assert ctx["first_scan"]["fill_charge_net_cents"] == 2250
    assert ctx["agreement_after_first_fill"]["billed_amount_cents"] == 2250
    assert ctx["agreement_after_first_fill"]["billed_fills_count"] == 1
    assert ctx["order"]["per_fill_price_cents_pinned"] == 2250


def test_a_tier_basis_of_exactly_4500_earns_the_150_basis_point_discount():
    """2250 already billed plus this fill's 2250 is exactly 4500, which is the
    inclusive edge of the 150-basis-point band: the discount is 34 cents on a
    round-half-up of 33.75, so the fill nets 2216 rather than the 2250 a strict
    comparison would have billed.

    PRD: "The discount is that rate applied to the pre-discount charge — so the
    surcharge is itself discountable and is not added back afterwards — rounded
    half up to whole cents, and the scan's `fill_charge_net_cents` is the
    pre-discount charge less that discount."

    PRD: "The volume tier is then chosen using the agreement's already-billed
    `billed_amount_cents` **plus this fill's pre-discount amount**, so the current
    fill counts toward its own tier: a basis of at least 9000 cents earns a
    300-basis-point discount, a basis of at least 4500 cents earns 150 basis
    points, and anything less earns none, with both comparisons inclusive so a
    basis of exactly 9000 earns the higher rate."

    Design: Corner/calculations/fill_charge_tier_basis_of_exactly_4500_earns_150_bp
    """
    ctx = _two_fills_at_a_base_that_tips_the_tier_exactly()

    assert ctx["second_scan"]["fill_charge_net_cents"] == 2216
    assert ctx["second_scan"]["fill_charge_net_cents"] != 2250

    agreement = fixtures.read_agreement(ctx["agreement"]["id"])
    assert agreement["billed_amount_cents"] == 4466
    assert agreement["billed_fills_count"] == 2

    assert fixtures.read_keg(ctx["first_keg_id"])["fill_count"] == 1
    assert fixtures.read_keg(ctx["second_keg_id"])["fill_count"] == 1
    assert fixtures.read_brewer(ctx["brewer"]["id"])["lifetime_fill_count"] == 2

    pool = fixtures.read_pool(ctx["pool"]["id"])
    assert_census(
        pool,
        {
            "kegs_total": 4,
            "kegs_available": 2,
            "kegs_circulating": 2,
            "kegs_servicing": 0,
            "kegs_held": 0,
            "kegs_written_off": 0,
        },
    )
    assert pool["available_pct"] == 50.00
    assert pool["posture"] == "OPEN"


def _one_keg_against_a_three_row_price_series():
    """A single keg in a 12.5-kilogram pool, with three index rows on file: one
    stale, one effective, and one dated a month into the future.
    """
    fixtures.pin_clock("2026-08-01T23:00:00Z")
    stale = fixtures.post_index("2026-06-01", 400)
    effective = fixtures.post_index("2026-07-01", 480)
    future = fixtures.post_index("2026-09-01", 600)
    pool = fixtures.create_pool(**POOL)
    keg = fixtures.import_keg(pool["id"], "K-0001")
    return {
        "stale_index": stale,
        "effective_index": effective,
        "future_index": future,
        "pool": pool,
        "keg": keg,
        "read_today": validate_success(api_client.get_keg(keg["id"], ANALYST)),
    }


def test_the_scrap_value_picks_the_latest_row_on_or_before_the_clock():
    """Of the three postings only the July row is in force: the June row is
    superseded and the September row is future-dated and never selected, so the
    shell values at 3900 rather than 3250 or 4875.

    PRD: "It is the pool's `stainless_weight_kg` multiplied by the stainless price
    in force, multiplied by a recovery factor of 65 percent, rounded half up to
    whole cents."

    PRD: "The price in force is taken from the commodity index row with the
    greatest `effective_date` that is on or before the valuation date, where the
    valuation date is the date part of the logical clock at the moment of
    computation; a future-dated index row is never selected, and because
    `effective_date` is unique the selection is never ambiguous."

    Design: Corner/calculations/stainless_scrap_value_selects_the_latest_index_at_or_before_today
    """
    ctx = _one_keg_against_a_three_row_price_series()
    keg = ctx["read_today"]

    assert keg["stainless_scrap_value_cents"] == 3900
    assert keg["stainless_scrap_value_cents"] != 3250
    assert keg["stainless_scrap_value_cents"] != 4875


def test_moving_the_clock_past_the_future_row_reprices_the_read_without_a_write():
    """Repositioning the clock into September brings the 600-cent row into force
    and the very same keg reads 4875 — recomputed on read, since the keg's version
    is untouched by either read and the clock move rewrote nothing.

    PRD: "This value is recomputed afresh every time a keg is read, so a keg read
    reflects the currently effective index."

    PRD: "A `PoolOperator` may reposition the clock by supplying a target instant
    as `to_iso8601`; the response reports `current_utc` and `previous_utc`."

    PRD: "Repositioning the clock mutates no entity and re-runs no calculation."

    PRD: "Neither has `updated_at` and neither has `version`; a client must not
    expect either field on them."

    Design: Corner/calculations/stainless_scrap_value_selects_the_latest_index_at_or_before_today
    """
    ctx = _one_keg_against_a_three_row_price_series()

    moved = fixtures.pin_clock("2026-09-02T00:00:00Z")
    assert moved["current_utc"] == "2026-09-02T00:00:00Z"
    assert moved["previous_utc"] == "2026-08-01T23:00:00Z"

    reread = validate_success(api_client.get_keg(ctx["keg"]["id"], ANALYST))
    assert reread["stainless_scrap_value_cents"] == 4875
    assert reread["version"] == ctx["read_today"]["version"]

    rows, meta = validate_paginated(api_client.list_commodity_index(OPERATOR))
    assert meta["total_count"] == 3
    for row in rows:
        assert "version" not in row
        assert "updated_at" not in row


def _two_assessments_whose_requested_basis_cannot_stand():
    """One never-filled keg out with the brewer and one never-issued keg still on
    the floor, both assessed with an explicit `DEPRECIATED_BOOK` that the contract
    coerces away: the first because there is nothing to depreciate, the second
    because a thief takes a keg at market value.
    """
    fixtures.pin_clock("2026-08-01T23:00:00Z")
    index = fixtures.post_index("2026-07-01", 480)
    brewer = fixtures.create_brewer()
    pool = fixtures.create_pool(**POOL)
    issued_keg, floor_keg = fixtures.import_kegs(pool["id"], ["K-0001", "K-0002"])
    agreement = fixtures.create_and_activate_agreement(
        brewer["id"], pool["id"], 2, effective_date="2026-08-01", per_fill_rate_cents=RATE
    )
    order = fixtures.order_allocated_and_dispatched(
        agreement["id"], 1, "2026-08-01T01:00:00Z"
    )
    issued_keg_id = order["allocated_keg_ids"][0]

    lost = validate_success(
        api_client.create_loss_assessment(
            factories.create_loss_assessment_payload(
                issued_keg_id,
                "LOST_IN_TRADE",
                fixtures.keg_version(issued_keg_id),
                assessment_basis="DEPRECIATED_BOOK",
            ),
            ANALYST,
        ),
        201,
    )
    stolen = validate_success(
        api_client.create_loss_assessment(
            factories.create_loss_assessment_payload(
                floor_keg["id"],
                "STOLEN_SUSPECTED",
                fixtures.keg_version(floor_keg["id"]),
                assessment_basis="DEPRECIATED_BOOK",
            ),
            ANALYST,
        ),
        201,
    )
    return {
        "index": index,
        "brewer": brewer,
        "pool": pool,
        "agreement": agreement,
        "order": order,
        "issued_keg_id": issued_keg_id,
        "floor_keg": floor_keg,
        "lost": lost,
        "stolen": stolen,
    }


def test_depreciated_book_on_a_never_filled_keg_is_coerced_to_replacement_cost():
    """The requested basis is neither honoured nor refused: it is silently stored
    as `REPLACEMENT_COST`, which values the shell at the pool's full 23500 rather
    than at the 7050 floor a literal book reading would have produced, and the
    six-tenths liability of a trade loss nets 14100.

    PRD: "When `assessment_basis` is omitted, or is supplied as `DEPRECIATED_BOOK`
    on a keg whose `fill_count` is 0, or is supplied as `DEPRECIATED_BOOK` together
    with a `cause` of `STOLEN_SUSPECTED`, the stored `assessment_basis` becomes
    `REPLACEMENT_COST` and the gross value follows that variant."

    PRD: "`brewer_liability_pct_bp` is keyed off the cause alone: 6000 basis points
    for `LOST_IN_TRADE`, 10000 for `DAMAGED_BEYOND_REPAIR`, 10000 for
    `NOT_RETURNED_DWELL` and 0 for `STOLEN_SUSPECTED`."

    PRD: "The `brewer_id` is not supplied: it is resolved as the keg's
    `filling_brewer_id` when that is set, and otherwise as its `current_brewer_id`."

    Design: Corner/calculations/zero_fill_and_stolen_kegs_force_the_replacement_cost_variant
    """
    ctx = _two_assessments_whose_requested_basis_cannot_stand()
    assessment = ctx["lost"]

    assert fixtures.read_keg(ctx["issued_keg_id"])["fill_count"] == 0
    assert assessment["assessment_basis"] == "REPLACEMENT_COST"
    assert assessment["gross_value_cents"] == 23500
    assert assessment["scrap_credit_cents"] == 0
    assert assessment["assessed_value_cents"] == 23500
    assert assessment["brewer_liability_pct_bp"] == 6000
    assert assessment["net_chargeback_cents"] == 14100
    assert assessment["brewer_id"] == ctx["brewer"]["id"]
    assert assessment["commodity_index_id"] == ctx["index"]["id"]
    assert assessment["assessment_status"] == "PROPOSED"
    assert assessment["chargeback_status"] == "NONE"
    assert assessment["created_by_user_id"] == ANALYST_USER_ID


def test_a_stolen_suspected_assessment_is_admitted_with_no_chargeable_party():
    """The keg on the floor has neither a filling brewer nor a current one, which
    would normally be refused outright, but `STOLEN_SUSPECTED` charges nobody and
    is therefore exempt: the row is created at the full market gross and nets zero
    against a null brewer.

    PRD: "At least one of the two must be set unless the `cause` is
    `STOLEN_SUSPECTED`, which charges nobody; a keg with neither is refused with
    `ERR_NO_CHARGEABLE_PARTY`."

    PRD: "And `net_chargeback_cents` is the assessed value multiplied by that
    liability share as a proportion of 10000, rounded half up."

    PRD: "The `created_by_user_id` is stamped with the acting `X-User-ID`, the
    assessment opens in `assessment_status` `PROPOSED` with `chargeback_status`
    `NONE`, the keg's `assessment_open` flag is raised, and
    `dwell_days_at_assessment` records the keg's dwell at creation, taken from
    whichever clock is open — the brewer clock when both are."

    Design: Corner/calculations/zero_fill_and_stolen_kegs_force_the_replacement_cost_variant
    """
    ctx = _two_assessments_whose_requested_basis_cannot_stand()
    assessment = ctx["stolen"]

    assert assessment["assessment_basis"] == "REPLACEMENT_COST"
    assert assessment["gross_value_cents"] == 23500
    assert assessment["brewer_liability_pct_bp"] == 0
    assert assessment["net_chargeback_cents"] == 0
    assert assessment["chargeback_status"] == "NONE"
    assert assessment["brewer_id"] is None

    keg = fixtures.read_keg(ctx["floor_keg"]["id"])
    assert keg["custody_state"] == "IN_FLOAT"
    assert keg["assessment_open"] is True

    assert fixtures.read_brewer(ctx["brewer"]["id"])["chargeback_balance_cents"] == 0


def _two_well_worn_kegs_assessed_on_the_book_basis():
    """Two kegs either side of the depreciation cap — 155 lifetime fills, one step
    below it, and 160, past it — both freshly certified so both are allocatable and
    both have a chargeable party.
    """
    fixtures.pin_clock("2026-08-01T23:00:00Z")
    index = fixtures.post_index("2026-07-01", 480)
    brewer = fixtures.create_brewer()
    pool = fixtures.create_pool(**POOL)
    fixtures.import_keg(
        pool["id"], "K-0001", fill_count=155, fills_at_last_pressure_test=155
    )
    fixtures.import_keg(
        pool["id"], "K-0002", fill_count=160, fills_at_last_pressure_test=160
    )
    agreement = fixtures.create_and_activate_agreement(
        brewer["id"], pool["id"], 2, effective_date="2026-08-01", per_fill_rate_cents=RATE
    )
    order = fixtures.order_allocated_and_dispatched(
        agreement["id"], 2, "2026-08-01T01:00:00Z"
    )
    under_cap_id, over_cap_id = order["allocated_keg_ids"]
    under_cap = fixtures.open_loss_assessment(
        under_cap_id, "NOT_RETURNED_DWELL", assessment_basis="DEPRECIATED_BOOK"
    )
    over_cap = fixtures.open_loss_assessment(
        over_cap_id, "NOT_RETURNED_DWELL", assessment_basis="DEPRECIATED_BOOK"
    )
    return {
        "index": index,
        "brewer": brewer,
        "pool": pool,
        "agreement": agreement,
        "order": order,
        "under_cap_keg_id": under_cap_id,
        "over_cap_keg_id": over_cap_id,
        "under_cap": under_cap,
        "over_cap": over_cap,
    }


def test_one_hundred_fifty_five_fills_depreciate_just_short_of_the_cap():
    """155 fills at 45 basis points each is 6975, one step below the 7000 ceiling,
    so the book value is computed from the uncapped figure and rounds half up to
    7109 — above the 30 percent floor, which is therefore not the binding value.

    PRD: "Under **`DEPRECIATED_BOOK`**, the replacement cost is written down 45
    basis points for every lifetime fill, with total depreciation capped at 7000
    basis points."

    PRD: "A candidate book value is the `replacement_cost_cents` multiplied by
    10000 less that depreciation, divided by 10000, rounded half up; a floor value
    is 30 percent of `replacement_cost_cents`, rounded half up; and
    `gross_value_cents` is the greater of the two."

    PRD: "Rounding is applied separately to the candidate book value, to the floor
    value and to the net chargeback; basis points are always integers."

    Design: Corner/calculations/depreciation_cap_binds_and_a_non_recovered_keg_credits_no_scrap
    """
    ctx = _two_well_worn_kegs_assessed_on_the_book_basis()
    assessment = ctx["under_cap"]

    assert assessment["assessment_basis"] == "DEPRECIATED_BOOK"
    assert assessment["gross_value_cents"] == 7109
    assert assessment["gross_value_cents"] > 7050
    assert assessment["scrap_credit_cents"] == 0
    assert assessment["assessed_value_cents"] == 7109
    assert assessment["brewer_liability_pct_bp"] == 10000
    assert assessment["net_chargeback_cents"] == 7109


def test_the_cap_lands_the_heavier_keg_exactly_on_the_thirty_percent_floor():
    """160 fills would depreciate 7200 basis points if nothing stopped it; the cap
    pins the write-down at 7000, which computes a book value of exactly the 7050
    floor, and the keg's 3900 of stainless is deliberately not credited because a
    keg that never came back cannot be weighed in.

    PRD: "`scrap_credit_cents` takes the keg's `stainless_scrap_value_cents` only
    when the `cause` is `DAMAGED_BEYOND_REPAIR`, because only then is the shell
    physically in hand; `LOST_IN_TRADE`, `NOT_RETURNED_DWELL` and
    `STOLEN_SUSPECTED` all credit 0 even though the keg has a scrap value on paper,
    since nobody can weigh in a keg they cannot find."

    PRD: "`assessed_value_cents` is the gross value less the scrap credit, floored
    at 0."

    PRD: "Candidates are ranked deterministically, ascending, on three keys in this
    order: first `fill_count`, so the least-filled keg leaves first and wear is
    spread across the fleet; then `last_pressure_test_at`, so the oldest
    certification leaves first; then `created_at` as the mandatory final
    tie-break."

    Design: Corner/calculations/depreciation_cap_binds_and_a_non_recovered_keg_credits_no_scrap
    """
    ctx = _two_well_worn_kegs_assessed_on_the_book_basis()
    assessment = ctx["over_cap"]

    assert assessment["assessment_basis"] == "DEPRECIATED_BOOK"
    assert assessment["gross_value_cents"] == 7050
    assert assessment["scrap_credit_cents"] == 0
    assert assessment["assessed_value_cents"] == 7050
    assert assessment["net_chargeback_cents"] == 7050

    heavier = fixtures.read_keg(ctx["over_cap_keg_id"])
    assert heavier["fill_count"] == 160
    assert heavier["stainless_scrap_value_cents"] == 3900

    assert ctx["order"]["allocated_keg_ids"] == [
        ctx["under_cap_keg_id"],
        ctx["over_cap_keg_id"],
    ]
    assert ctx["order"]["allocation_shortfall"] == 0
    assert fixtures.read_brewer(ctx["brewer"]["id"])["chargeback_balance_cents"] == 0


def _a_three_keg_pool_emptied_one_order_at_a_time():
    """Three kegs, three single-keg orders all raised while the pool still reads
    100.00 so that no order creation is ever gated, then allocated one at a time so
    the availability percentage can be read at each step of the walk.
    """
    fixtures.pin_clock("2026-08-01T23:00:00Z")
    fixtures.post_index("2026-07-01", 480)
    brewer = fixtures.create_brewer()
    pool = fixtures.create_pool(**POOL)
    fixtures.import_kegs(pool["id"], ["K-0001", "K-0002", "K-0003"])
    agreement = fixtures.create_and_activate_agreement(
        brewer["id"], pool["id"], 3, effective_date="2026-08-01", per_fill_rate_cents=RATE
    )
    orders = [fixtures.create_order(agreement["id"], 1) for _ in range(3)]
    return {
        "brewer": brewer,
        "pool": pool,
        "agreement": agreement,
        "orders": orders,
        "at_import": fixtures.read_pool(pool["id"]),
    }


def test_a_full_pool_reads_one_hundred_then_sixty_six_point_six_seven():
    """The percentage is carried to exactly two decimals with round half up, so two
    kegs of three is 66.67 rather than 66.66 or 67, and 66.67 is still comfortably
    above the 25 percent restrict threshold, so the posture does not budge.

    PRD: "`available_pct` is 0.00 when `kegs_total` is zero, and otherwise
    `kegs_available` divided by `kegs_total`, multiplied by 100, rounded half up to
    exactly two decimal places."

    PRD: "When `kegs_total` is greater than zero and `available_pct` is greater than
    or equal to `restrict_threshold_pct`, the posture is `OPEN`."

    PRD: "While the posture is `HEALTHY` or `SUSPENDED` it is 0."

    Design: Corner/calculations/pool_available_pct_carries_two_decimals_round_half_up
    """
    ctx = _a_three_keg_pool_emptied_one_order_at_a_time()
    at_import = ctx["at_import"]
    assert at_import["kegs_total"] == 3
    assert at_import["kegs_available"] == 3
    assert at_import["available_pct"] == 100.00
    assert at_import["posture"] == "OPEN"

    fixtures.allocate_order(ctx["orders"][0]["id"], ctx["agreement"]["id"])

    pool = fixtures.read_pool(ctx["pool"]["id"])
    assert pool["available_pct"] == 66.67
    assert pool["kegs_available"] == 2
    assert pool["kegs_circulating"] == 1
    assert pool["posture"] == "OPEN"

    agreement = fixtures.read_agreement(ctx["agreement"]["id"])
    assert agreement["kegs_at_brewer_count"] == 1
    assert agreement["float_posture"] == "HEALTHY"
    assert agreement["pending_replenishment_kegs"] == 0


def test_the_third_allocation_empties_the_pool_and_suspends_the_float():
    """One keg of three is 33.333..., which truncates in the third decimal to 33.33
    and is still at or above 25, so the pool holds `OPEN` right up to the last
    allocation; emptying it lands 0.00 exactly, which is below the freeze threshold
    and suspends the float in the very same request.

    PRD: "Otherwise — including whenever `kegs_total` is zero — the posture is
    `FROZEN`."

    PRD: "The agreement is `SUSPENDED` whenever the pool's `posture` is `FROZEN`
    **or** the brewer's `status` is `PROBATION` or `SUSPENDED`."

    PRD: "Whenever the posture changes, the pool's `version` advances and every
    `ACTIVE` float agreement on that pool recomputes its own `float_posture`; a pool
    falling to `FROZEN` therefore suspends the drawing rights of every brewer
    leasing from it, which in turn blocks their allocations and their fill scans."

    Design: Corner/calculations/pool_available_pct_carries_two_decimals_round_half_up
    """
    ctx = _a_three_keg_pool_emptied_one_order_at_a_time()
    fixtures.allocate_order(ctx["orders"][0]["id"], ctx["agreement"]["id"])
    fixtures.allocate_order(ctx["orders"][1]["id"], ctx["agreement"]["id"])

    midway = fixtures.read_pool(ctx["pool"]["id"])
    assert midway["available_pct"] == 33.33
    assert midway["kegs_available"] == 1
    assert midway["kegs_circulating"] == 2
    assert midway["posture"] == "OPEN"

    fixtures.allocate_order(ctx["orders"][2]["id"], ctx["agreement"]["id"])

    emptied = fixtures.read_pool(ctx["pool"]["id"])
    assert emptied["available_pct"] == 0.00
    assert emptied["kegs_available"] == 0
    assert emptied["kegs_circulating"] == 3
    assert emptied["posture"] == "FROZEN"
    assert emptied["kegs_written_off"] == 0
    assert emptied["kegs_held"] == 0
    assert emptied["kegs_servicing"] == 0

    assert fixtures.read_agreement(ctx["agreement"]["id"])["float_posture"] == "SUSPENDED"

    for order in ctx["orders"]:
        allocated = fixtures.read_order(order["id"])
        assert allocated["status"] == "ALLOCATED"
        assert allocated["allocation_shortfall"] == 0
        assert allocated["allocated_keg_count"] == 1


def _four_kegs_of_unequal_wear_and_certification_age():
    """K-A at 12 fills, two kegs at 5 fills certified a month apart, and K-D at 30
    fills, imported in that order so that import order and rank order disagree.
    Every keg's `fills_at_last_pressure_test` equals its `fill_count`, so all four
    are `SERVICE_OK` and all four are candidates.
    """
    fixtures.pin_clock("2026-08-01T23:00:00Z")
    fixtures.post_index("2026-07-01", 480)
    brewer = fixtures.create_brewer()
    pool = fixtures.create_pool(**POOL)
    keg_a = fixtures.import_keg(pool["id"], "K-A", fill_count=12, fills_at_last_pressure_test=12)
    keg_b = fixtures.import_keg(
        pool["id"],
        "K-B",
        fill_count=5,
        fills_at_last_pressure_test=5,
        last_pressure_test_at="2026-05-01T00:00:00Z",
    )
    keg_c = fixtures.import_keg(
        pool["id"],
        "K-C",
        fill_count=5,
        fills_at_last_pressure_test=5,
        last_pressure_test_at="2026-06-01T00:00:00Z",
    )
    keg_d = fixtures.import_keg(pool["id"], "K-D", fill_count=30, fills_at_last_pressure_test=30)
    agreement = fixtures.create_and_activate_agreement(
        brewer["id"], pool["id"], 4, effective_date="2026-08-01", per_fill_rate_cents=RATE
    )
    first_order = fixtures.create_order(agreement["id"], 2)
    fixtures.allocate_order(first_order["id"], agreement["id"])
    second_order = fixtures.create_order(agreement["id"], 1)
    fixtures.allocate_order(second_order["id"], agreement["id"])
    return {
        "brewer": brewer,
        "pool": pool,
        "agreement": agreement,
        "keg_a": keg_a,
        "keg_b": keg_b,
        "keg_c": keg_c,
        "keg_d": keg_d,
        "first_order": fixtures.read_order(first_order["id"]),
        "second_order": fixtures.read_order(second_order["id"]),
    }


def test_the_two_least_worn_kegs_leave_first_oldest_certification_ahead():
    """Both 5-fill kegs outrank the 12-fill and the 30-fill shells on the first key,
    and between the two of them the May certification leaves before the June one —
    so the reported order is K-B then K-C, which is neither the import order of the
    pool nor any ordering by id.

    PRD: "Candidates are ranked deterministically, ascending, on three keys in this
    order: first `fill_count`, so the least-filled keg leaves first and wear is
    spread across the fleet; then `last_pressure_test_at`, so the oldest
    certification leaves first; then `created_at` as the mandatory final tie-break."

    PRD: "A keg's `id` is never an input to the ranking."

    PRD: "Otherwise the leading kegs in rank order are taken: `allocated_keg_ids`
    records their ids in rank order as a reporting convenience that is never an
    input to any later decision, `allocated_keg_count` records how many were taken,
    `allocation_shortfall` records `requested_keg_count` minus that number, and
    `per_fill_price_cents_pinned` copies the agreement's `per_fill_rate_cents` at
    this moment, so later edits to the agreement do not retro-price this order's
    fills."

    Design: Corner/calculations/allocation_selector_ranks_by_fill_count_then_certification_age
    """
    ctx = _four_kegs_of_unequal_wear_and_certification_age()
    order = ctx["first_order"]

    assert order["allocated_keg_ids"] == [ctx["keg_b"]["id"], ctx["keg_c"]["id"]]
    assert order["status"] == "ALLOCATED"
    assert order["allocated_keg_count"] == 2
    assert order["allocation_shortfall"] == 0
    assert order["per_fill_price_cents_pinned"] == RATE


def test_the_follow_up_order_resumes_the_ranking_at_the_remaining_candidates():
    """The second order takes K-A at 12 fills — the next-least-worn keg still in
    float — and not K-D, and not the keg with the oldest certification overall,
    because the wear key is consulted before the certification key on the reduced
    candidate set rather than the original one.

    PRD: "The candidate set is built from the kegs of the agreement's pool whose
    `custody_state` is `IN_FLOAT`, whose `service_state` is `SERVICE_OK` or
    `SERVICE_DUE`, whose `theft_investigation_id` is unset, and whose
    `assessment_open` flag is false."

    PRD: "Each allocated keg moves `IN_FLOAT → ISSUED_TO_BREWER`, records
    `current_brewer_id` from the agreement and `issuance_order_id` from the order,
    sets `dwell_started_at` to the logical clock, sets `dwell_flag` to
    `WITHIN_LIMIT`, and advances its own `version`."

    PRD: "Both comparisons are inclusive, so an `available_pct` exactly equal to
    `restrict_threshold_pct` reads `OPEN` and one exactly equal to
    `freeze_threshold_pct` reads `RESTRICTED`."

    Design: Corner/calculations/allocation_selector_ranks_by_fill_count_then_certification_age
    """
    ctx = _four_kegs_of_unequal_wear_and_certification_age()
    assert ctx["second_order"]["allocated_keg_ids"] == [ctx["keg_a"]["id"]]

    issued = fixtures.read_keg(ctx["keg_b"]["id"])
    assert issued["custody_state"] == "ISSUED_TO_BREWER"
    assert issued["issuance_order_id"] == ctx["first_order"]["id"]
    assert fixtures.read_keg(ctx["keg_d"]["id"])["custody_state"] == "IN_FLOAT"

    pool = fixtures.read_pool(ctx["pool"]["id"])
    assert pool["kegs_available"] == 1
    assert pool["kegs_circulating"] == 3
    assert pool["available_pct"] == 25.00
    assert pool["posture"] == "OPEN"

    agreement = fixtures.read_agreement(ctx["agreement"]["id"])
    assert agreement["kegs_at_brewer_count"] == 3
    assert agreement["float_posture"] == "HEALTHY"


def _a_pool_whose_only_keg_is_out_of_certification():
    """A single keg certified in January 2024 — 943 days before the clock, well past
    the two-year interval — so the pool is full on paper and empty of candidates.
    """
    fixtures.pin_clock("2026-08-01T23:00:00Z")
    fixtures.post_index("2026-07-01", 480)
    brewer = fixtures.create_brewer()
    pool = fixtures.create_pool(**POOL)
    overdue_keg = fixtures.import_keg(
        pool["id"], "K-OLD", last_pressure_test_at="2024-01-01T00:00:00Z"
    )
    agreement = fixtures.create_and_activate_agreement(
        brewer["id"], pool["id"], 2, effective_date="2026-08-01", per_fill_rate_cents=RATE
    )
    order = fixtures.create_order(agreement["id"], 1)
    return {
        "brewer": brewer,
        "pool": pool,
        "overdue_keg": overdue_keg,
        "agreement": agreement,
        "order": order,
        "before_allocate": fixtures.read_pool(pool["id"]),
        "refusal": api_client.allocate_issuance_order(
            order["id"],
            {"expected_agreement_version": fixtures.agreement_version(agreement["id"])},
            OPERATOR,
        ),
    }


def test_a_pool_reading_open_at_one_hundred_percent_still_has_no_eligible_kegs():
    """Census membership and allocation candidacy are different sets: the overdue
    keg is `IN_FLOAT` and is counted in `kegs_available`, so the pool reads 100.00
    and `OPEN`, and the allocation is nevertheless refused outright with nothing
    left behind on the order or the keg.

    PRD: "If instead its certification is older than two years — that is, more than
    730 days have elapsed between `last_pressure_test_at` and the logical clock — it
    opens `SERVICE_OVERDUE`."

    PRD: "Two of those filters have consequences the operator can see in the census:
    a keg that is `SERVICE_OVERDUE`, or attached to a theft investigation, or
    carrying an open assessment, is still `IN_FLOAT` and still counted in
    `kegs_available`, yet is not a candidate — so a pool can read `posture` `OPEN`
    and still fail allocation with `ERR_NO_ELIGIBLE_KEGS`."

    PRD: "The selector then takes the smaller of `requested_keg_count` and the
    number of candidates. If that number is zero, the request is refused with
    `ERR_NO_ELIGIBLE_KEGS`."

    Design: Corner/calculations/service_overdue_keg_is_counted_available_yet_yields_no_eligible_kegs
    """
    ctx = _a_pool_whose_only_keg_is_out_of_certification()
    assert ctx["overdue_keg"]["service_state"] == "SERVICE_OVERDUE"
    assert ctx["overdue_keg"]["custody_state"] == "IN_FLOAT"

    before = ctx["before_allocate"]
    assert before["kegs_available"] == 1
    assert before["available_pct"] == 100.00
    assert before["posture"] == "OPEN"

    validate_error(ctx["refusal"], ApiErrorId.ERR_NO_ELIGIBLE_KEGS, 409)

    order = fixtures.read_order(ctx["order"]["id"])
    assert order["status"] == "REQUESTED"
    assert order["allocated_keg_ids"] == []
    assert order["allocated_keg_count"] == 0
    assert fixtures.read_keg(ctx["overdue_keg"]["id"])["custody_state"] == "IN_FLOAT"
    assert fixtures.read_agreement(ctx["agreement"]["id"])["kegs_at_brewer_count"] == 0


def test_importing_a_service_due_keg_makes_the_very_same_order_allocate():
    """A keg 25 fills past its last test is `SERVICE_DUE`, and `SERVICE_DUE` is a
    legitimate candidate — only `SERVICE_OVERDUE` is excluded — so the order that
    was just refused now allocates the new keg while the overdue shell stays on the
    floor and keeps being counted as available.

    PRD: "If `fill_count` minus `fills_at_last_pressure_test` is at least 25 fills,
    the keg opens `SERVICE_DUE`."

    PRD: "Kegs that are merely `SERVICE_DUE` *are* candidates, because they remain
    certified and are only due for a test; they will, however, be refused later at
    the fill scan."

    PRD: "`kegs_available` counts the kegs whose `custody_state` is `IN_FLOAT`."

    Design: Corner/calculations/service_overdue_keg_is_counted_available_yet_yields_no_eligible_kegs
    """
    ctx = _a_pool_whose_only_keg_is_out_of_certification()
    due_keg = fixtures.import_keg(
        ctx["pool"]["id"], "K-DUE", fill_count=25, fills_at_last_pressure_test=0
    )
    assert due_keg["service_state"] == "SERVICE_DUE"

    allocated = validate_success(
        api_client.allocate_issuance_order(
            ctx["order"]["id"],
            {
                "expected_agreement_version": fixtures.agreement_version(
                    ctx["agreement"]["id"]
                )
            },
            OPERATOR,
        )
    )
    assert allocated["allocated_keg_ids"] == [due_keg["id"]]

    pool = fixtures.read_pool(ctx["pool"]["id"])
    assert pool["kegs_total"] == 2
    assert pool["kegs_available"] == 1
    assert pool["kegs_circulating"] == 1
    assert pool["available_pct"] == 50.00
    assert pool["posture"] == "OPEN"


def _a_paid_return_on_a_keg_that_turns_out_to_be_stolen():
    """One full outbound-and-back cycle earns a BRONZE distributor a 250 cent
    accrual, which is then remitted; an investigation naming that same distributor
    as the suspect impounds the keg it came back on.
    """
    fixtures.pin_clock("2026-08-15T23:00:00Z")
    fixtures.post_index("2026-07-01", 480)
    brewer = fixtures.create_brewer()
    distributor = fixtures.create_distributor()
    fixtures.sign_cooperation_agreement(distributor["id"], "BRONZE", "2026-08-01")
    pool = fixtures.create_pool(**POOL)
    keg = fixtures.import_keg(pool["id"], "K-0001")
    fixtures.import_keg(pool["id"], "K-0002", fill_count=5, fills_at_last_pressure_test=5)
    agreement = fixtures.create_and_activate_agreement(
        brewer["id"], pool["id"], 2, effective_date="2026-08-01", per_fill_rate_cents=RATE
    )
    fixtures.order_allocated_and_dispatched(agreement["id"], 1, "2026-08-02T00:00:00Z")
    fixtures.fill_scan(keg["id"], brewer["id"], "2026-08-03T00:00:00Z", "RDG")
    fixtures.distribution_scan(
        keg["id"], distributor["id"], "2026-08-04T00:00:00Z", "RDG"
    )
    fixtures.return_scan(keg["id"], distributor["id"], "2026-08-06T00:00:00Z", "RDG")

    rows, _ = validate_paginated(
        api_client.list_return_incentives(
            OPERATOR,
            {"distributor_id": distributor["id"], "accrual_type": "RETURN_DWELL"},
        )
    )
    accrual_id = rows[0]["id"]
    fixtures.pay_accrual(accrual_id, "2026-08-07T00:00:00Z")

    investigation = fixtures.open_investigation(
        pool["id"],
        [keg["id"]],
        opened_reason="Scrap yard tip from a Pueblo dealer.",
        suspect_distributor_id=distributor["id"],
    )
    held = fixtures.set_investigation_status(
        investigation["id"],
        "EVIDENCE_HOLD",
        keg_ids=[keg["id"]],
        hold_started_at="2026-08-08T00:00:00Z",
    )
    return {
        "brewer": brewer,
        "distributor": distributor,
        "pool": pool,
        "keg": keg,
        "agreement": agreement,
        "investigation": investigation,
        "held": held,
        "accrual_id": accrual_id,
    }


def test_paying_the_accrual_does_not_drain_the_incentive_ledger():
    """Remittance moves the row to `PAID` and stamps `paid_at`, and the two-day
    accountability spell priced it at the full band and the BRONZE multiplier — but
    the distributor's ledger still reads 250, because paid rows stay inside the sum.

    PRD: "The accrual moves to `PAID` and records `paid_at`, while the distributor's
    `incentive_accrual_cents` is deliberately **unchanged**, because paid rows stay
    inside the ledger sum."

    PRD: "The dwell band factor is 10000 basis points when the accountability spell
    closed in 14 days or fewer, 6000 basis points from 15 through 29 days, 2500
    basis points from 30 through 44 days, and 0 basis points at 45 days or more — so
    a keg returned outside the 45-day distributor allowance earns nothing."

    PRD: "The cooperation factor is 0 basis points for a `NONE`-tier distributor,
    10000 for `BRONZE`, 11500 for `SILVER` and 13000 for `GOLD`, taken from the tier
    as it stands *at the moment of this scan*."

    Design: Corner/calculations/incentive_clawback_restores_the_money_but_not_the_service_history
    """
    ctx = _a_paid_return_on_a_keg_that_turns_out_to_be_stolen()
    accrual = fixtures.read_accrual(ctx["accrual_id"])

    assert accrual["status"] == "PAID"
    assert accrual["incentive_cents"] == 250
    assert accrual["dwell_days"] == 2
    assert accrual["tier_pct_bp"] == 10000
    assert accrual["cooperation_multiplier_bp"] == 10000
    assert accrual["paid_at"] == "2026-08-07T00:00:00Z"
    assert fixtures.read_distributor(ctx["distributor"]["id"])["incentive_accrual_cents"] == 250

    investigation = ctx["held"]
    assert investigation["attached_keg_count"] == 1
    assert investigation["held_keg_count"] == 1
    assert investigation["stainless_value_at_risk_cents"] == 3900
    assert investigation["status"] == "EVIDENCE_HOLD"

    keg = fixtures.read_keg(ctx["keg"]["id"])
    assert keg["custody_state"] == "EVIDENCE_HOLD"
    assert keg["pre_hold_custody_state"] == "IN_SERVICE"


def test_the_write_off_claws_the_paid_row_back_to_the_pre_accrual_balance():
    """Closing the investigation as written off flips the suspect distributor's paid
    row to `CLAWED_BACK` without zeroing it — the row leaves the sum rather than
    being rewritten — and the ledger returns to exactly 0, the same delta a clawback
    of an `ACCRUED` row would have produced.

    PRD: "When `suspect_distributor_id` is set, that distributor's accruals in
    `ACCRUED` **or** `PAID` for the attached kegs all flip to `CLAWED_BACK` with a
    `clawback_reason` recorded, and `incentive_accrual_cents` is recomputed, which
    restores it to its exact pre-accrual value: since a `PAID` row never left the
    ledger sum, clawing back a paid accrual moves the balance by precisely the same
    amount as clawing back an accrued one."

    PRD: "The distributor's `incentive_accrual_cents` is then the sum of the
    already-rounded `incentive_cents` across its accruals in `ACCRUED` or `PAID`."

    Design: Corner/calculations/incentive_clawback_restores_the_money_but_not_the_service_history
    """
    ctx = _a_paid_return_on_a_keg_that_turns_out_to_be_stolen()
    fixtures.set_investigation_status(
        ctx["investigation"]["id"],
        "CLOSE",
        outcome="WRITTEN_OFF",
        outcome_notes="Recovered as scrap at a Pueblo yard; keg destroyed.",
    )

    accrual = fixtures.read_accrual(ctx["accrual_id"])
    assert accrual["status"] == "CLAWED_BACK"
    assert accrual["incentive_cents"] == 250
    assert accrual["clawback_reason"] is not None

    assert fixtures.read_distributor(ctx["distributor"]["id"])["incentive_accrual_cents"] == 0


def test_the_clawback_leaves_the_service_history_and_the_tier_standing():
    """Service history is not money and is not conserved: the clawed-back return
    still counts as a return, on time, at a two-day average, and the tier the
    returns earned stands — while the keg itself is now `STOLEN`, still carrying its
    investigation reference for audit.

    PRD: "What is *not* restored is the service history — `total_returns_count`,
    `on_time_returns_count`, `on_time_return_pct` and `avg_dwell_days` all keep the
    returns, and any `cooperation_tier` promotion those returns earned stands."

    PRD: "With an `outcome` of `WRITTEN_OFF`, every attached keg that is on
    `EVIDENCE_HOLD` moves to `STOLEN` — and an evidence hold is the *only* route
    into `STOLEN`, so a keg can never be written off as stolen without having been
    formally impounded first — while an attached keg that was never held only
    detaches."

    PRD: "`kegs_written_off` counts the kegs in `LOST`, `STOLEN` or `SCRAPPED`."

    PRD: "While the posture is `TIGHT` it is the float size minus
    `kegs_at_brewer_count`, or 0 if that difference would be negative."

    Design: Corner/calculations/incentive_clawback_restores_the_money_but_not_the_service_history
    """
    ctx = _a_paid_return_on_a_keg_that_turns_out_to_be_stolen()
    closed = fixtures.set_investigation_status(
        ctx["investigation"]["id"],
        "CLOSE",
        outcome="WRITTEN_OFF",
        outcome_notes="Recovered as scrap at a Pueblo yard; keg destroyed.",
    )

    distributor = fixtures.read_distributor(ctx["distributor"]["id"])
    assert distributor["total_returns_count"] == 1
    assert distributor["on_time_returns_count"] == 1
    assert distributor["on_time_return_pct"] == 100.00
    assert distributor["avg_dwell_days"] == 2.00
    assert distributor["cooperation_tier"] == "BRONZE"

    keg = fixtures.read_keg(ctx["keg"]["id"])
    assert keg["custody_state"] == "STOLEN"
    assert keg["theft_investigation_id"] == ctx["investigation"]["id"]
    assert closed["status"] == "CLOSED_WRITTEN_OFF"
    assert closed["closed_at"] == "2026-08-15T23:00:00Z"

    pool = fixtures.read_pool(ctx["pool"]["id"])
    assert_census(
        pool,
        {
            "kegs_total": 2,
            "kegs_available": 1,
            "kegs_circulating": 0,
            "kegs_servicing": 0,
            "kegs_held": 0,
            "kegs_written_off": 1,
        },
    )
    assert pool["available_pct"] == 50.00
    assert pool["posture"] == "OPEN"

    agreement = fixtures.read_agreement(ctx["agreement"]["id"])
    assert agreement["float_posture"] == "TIGHT"
    assert agreement["pending_replenishment_kegs"] == 2
    assert agreement["billed_amount_cents"] == 2200
