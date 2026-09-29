"""Endpoint-shape corners: computed reads, bulk actions and composed filters.

The scenarios here separate what an endpoint *reports* from what it *persists*
(the dwell read against the sweep), prove that list-valued bulk actions are
all-or-nothing, and drive every declared filter of two listings at once so a
filter that silently widens or shadows another becomes visible.
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
    TEST_USERS,
    make_analyst_headers,
    make_distributor_headers,
)

OPERATOR = TEST_USERS["pool_operator_headers"]
ANALYST = make_analyst_headers(ANALYST_USER_ID)

CLOCK = "2026-08-01T23:00:00Z"
POOL = {
    "pool_code": "HB-50L",
    "size_liters": 50,
    "stainless_weight_kg": 12.5,
    "replacement_cost_cents": 23500,
    "region_code": "CO",
}
SECOND_POOL = {
    "pool_code": "SK-20L",
    "size_liters": 20,
    "stainless_weight_kg": 7.5,
    "replacement_cost_cents": 16000,
    "region_code": "CO",
}
RATE = 2200
KEG_SPECS = [
    {"asset_tag": "K-0001"},
    {"asset_tag": "K-0002", "fill_count": 5, "fills_at_last_pressure_test": 5},
]


def _a_keg_thirty_seven_days_into_its_distributor_spell(clock="2026-09-11T00:00:00Z"):
    """One keg dispatched 2026-08-01, filled 2026-08-03 and handed to a
    distributor on 2026-08-05, read against a clock parked well after it."""
    ctx = fixtures.setup_active_float(
        float_size_kegs=2,
        keg_count=2,
        brewer_overrides={"credit_limit_cents": 400000},
        pool_overrides=dict(POOL),
        agreement_overrides={"per_fill_rate_cents": RATE},
        keg_specs=[dict(spec) for spec in KEG_SPECS],
        effective_date="2026-08-01",
        clock=clock,
    )
    ctx["distributor"] = fixtures.create_distributor()
    order = fixtures.order_allocated_and_dispatched(
        ctx["agreement"]["id"], 1, "2026-08-01T00:00:00Z"
    )
    ctx["order"] = order
    ctx["keg_id"] = order["allocated_keg_ids"][0]
    ctx["idle_keg_id"] = next(
        keg["id"] for keg in ctx["kegs"] if keg["id"] != ctx["keg_id"]
    )
    fixtures.fill_scan(
        ctx["keg_id"], ctx["brewer"]["id"], "2026-08-03T00:00:00Z", "RDG"
    )
    fixtures.distribution_scan(
        ctx["keg_id"], ctx["distributor"]["id"], "2026-08-05T00:00:00Z", "RDG"
    )
    return ctx


def test_the_dwell_read_reports_both_clocks_and_the_distributor_constants():
    """A keg `IN_TRADE` is measured on the distributor clock, so the read hands back
    limit 45 and approaching 36 rather than the brewer pair 30 and 24, and both
    spells count from the 2026-08-05 distribution scan that re-based them.

    PRD: "The computed read reports `keg_id`, the keg's `custody_state`, both clocks
    as `brewer_spell_days` and `distributor_spell_days`, the `limit_days` and
    `approaching_days` that apply to that custody state, the `dwell_flag` as it
    *would* be classified right now, the accumulated `cumulative_dwell_days`, and the
    two start instants `dwell_started_at` and `distributor_custody_started_at`."

    PRD: "a keg in `IN_TRADE` or `AT_RETAIL` is measured on the distributor clock
    against a limit of 45 days with an approaching point at 36 days"

    Design: Corner/endpoints/dwell_read_classifies_without_persisting_the_flag
    """
    ctx = _a_keg_thirty_seven_days_into_its_distributor_spell()

    dwell = validate_success(api_client.get_keg_dwell(ctx["keg_id"], OPERATOR))

    assert dwell["keg_id"] == ctx["keg_id"]
    assert dwell["custody_state"] == "IN_TRADE"
    assert dwell["brewer_spell_days"] == 37
    assert dwell["distributor_spell_days"] == 37
    assert dwell["limit_days"] == 45
    assert dwell["approaching_days"] == 36
    assert dwell["dwell_started_at"] == "2026-08-05T00:00:00Z"
    assert dwell["distributor_custody_started_at"] == "2026-08-05T00:00:00Z"
    assert dwell["cumulative_dwell_days"] == 4


def test_the_classification_the_read_returns_is_never_written_to_the_keg():
    """Thirty-seven open distributor-days classify as `APPROACHING` in the read while
    the stored column is still `WITHIN_LIMIT`, and the keg's `version` is the same
    integer before and after the read.

    PRD: "The read is strictly read-only: the classification it returns is not
    persisted."

    PRD: "The keg's `dwell_flag` classifies the *open* spell, and — this is important
    — no scan ever sets it to `APPROACHING` or `OVERDUE`."

    Design: Corner/endpoints/dwell_read_classifies_without_persisting_the_flag
    """
    ctx = _a_keg_thirty_seven_days_into_its_distributor_spell()
    before = fixtures.read_keg(ctx["keg_id"])

    dwell = validate_success(api_client.get_keg_dwell(ctx["keg_id"], OPERATOR))
    assert dwell["dwell_flag"] == "APPROACHING"

    after = fixtures.read_keg(ctx["keg_id"])
    assert after["dwell_flag"] == "WITHIN_LIMIT"
    assert after["version"] == before["version"]
    assert after["custody_state"] == "IN_TRADE"


def _the_same_float_fifty_one_days_after_the_distribution_scan():
    """The dwell-read scenario with the clock parked at 2026-09-25, which is 51
    whole days after the 2026-08-05 distribution scan."""
    return _a_keg_thirty_seven_days_into_its_distributor_spell(
        clock="2026-09-25T00:00:00Z"
    )


def test_the_sweep_counts_only_the_kegs_that_had_an_open_spell_to_advance():
    """Two kegs sit in the pool but only the one `IN_TRADE` has a spell, so
    `swept_keg_count` is 1; at 51 days against a limit of 45 the strict comparison
    makes it `OVERDUE` rather than `APPROACHING`, and the sweep is the writer that
    finally persists the flag.

    PRD: "`swept_keg_count` counts only the kegs that actually had an open dwell
    spell to advance — that is, those in `ISSUED_TO_BREWER`, `FILLED`, `IN_TRADE` or
    `AT_RETAIL`; kegs in `IN_FLOAT`, `IN_SERVICE`, `QUARANTINED`, `EVIDENCE_HOLD` or a
    written-off state are forced to `WITHIN_LIMIT` and are not counted."

    PRD: "Given the applicable limit, the open spell reads `OVERDUE` when its
    whole-day length is **strictly greater** than the limit, `APPROACHING` when it is
    at or beyond the approaching point but not over the limit, and `WITHIN_LIMIT`
    otherwise."

    Design: Corner/endpoints/replenishment_sweep_is_the_only_writer_of_the_dwell_flag
    """
    ctx = _the_same_float_fifty_one_days_after_the_distribution_scan()

    sweep = fixtures.sweep_pool(ctx["pool"]["id"])

    assert sweep["pool_id"] == ctx["pool"]["id"]
    assert sweep["swept_keg_count"] == 1
    assert sweep["approaching_keg_count"] == 0
    assert sweep["overdue_keg_count"] == 1

    assert fixtures.read_keg(ctx["keg_id"])["dwell_flag"] == "OVERDUE"
    assert fixtures.read_keg(ctx["idle_keg_id"])["dwell_flag"] == "WITHIN_LIMIT"


def test_the_sweep_reports_the_recomputed_postures_without_moving_anything():
    """One keg of two is out, so availability reads 50.00 at posture `OPEN`; the lone
    agreement holds no keg at the brewer at all, so it lands on the thin side of a
    ceiling of `floor(2 x 20 / 100) = 0` and the sweep lists it as tight with a
    pending signal of the whole float, while neither custody nor money moves.

    PRD: "It reports `pool_id`, `swept_keg_count`, `approaching_keg_count`,
    `overdue_keg_count`, `available_pct`, `posture`, `tight_agreement_ids`,
    `suspended_agreement_ids` and `pending_replenishment_kegs_total`."

    PRD: "Otherwise, letting the thin-float ceiling be `float_size_kegs` multiplied
    by `replenishment_threshold_pct`, divided by 100 and floored to a whole number
    of kegs, the agreement is `TIGHT` when `kegs_at_brewer_count` is less than or
    equal to that ceiling, and `HEALTHY` otherwise."

    PRD: "While the posture is `TIGHT` it is the float size minus
    `kegs_at_brewer_count`, or 0 if that difference would be negative."

    PRD: "No keg's `custody_state` changes and no money moves: the sweep detects, it
    does not remediate."

    Design: Corner/endpoints/replenishment_sweep_is_the_only_writer_of_the_dwell_flag
    """
    ctx = _the_same_float_fifty_one_days_after_the_distribution_scan()

    sweep = fixtures.sweep_pool(ctx["pool"]["id"])

    assert sweep["available_pct"] == 50.00
    assert sweep["posture"] == "OPEN"
    assert sweep["tight_agreement_ids"] == [ctx["agreement"]["id"]]
    assert sweep["suspended_agreement_ids"] == []
    assert sweep["pending_replenishment_kegs_total"] == 2

    assert fixtures.read_keg(ctx["keg_id"])["custody_state"] == "IN_TRADE"
    agreement = fixtures.read_agreement(ctx["agreement"]["id"])
    assert agreement["float_posture"] == "TIGHT"
    assert agreement["billed_amount_cents"] == RATE
    assert (
        fixtures.read_distributor(ctx["distributor"]["id"])["incentive_accrual_cents"]
        == 0
    )
    _rows, meta = validate_paginated(
        api_client.list_return_incentives(
            OPERATOR, params={"distributor_id": ctx["distributor"]["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_a_second_sweep_at_the_same_clock_returns_the_same_counts():
    """The sweep is a detector, so running it again at a fixed clock re-derives
    exactly the same three counts instead of double-counting the keg it already
    flagged.

    PRD: "Every keg in the pool has its `dwell_flag` reclassified by the rules above,
    with kegs that have no dwell limit forced to `WITHIN_LIMIT`; this is the only
    operation in the entire system that writes `dwell_flag`."

    Design: Corner/endpoints/replenishment_sweep_is_the_only_writer_of_the_dwell_flag
    """
    ctx = _the_same_float_fifty_one_days_after_the_distribution_scan()

    first = fixtures.sweep_pool(ctx["pool"]["id"])
    second = fixtures.sweep_pool(ctx["pool"]["id"])

    for field in (
        "swept_keg_count",
        "approaching_keg_count",
        "overdue_keg_count",
        "available_pct",
        "posture",
        "pending_replenishment_kegs_total",
    ):
        assert second[field] == first[field]

    assert fixtures.read_keg(ctx["keg_id"])["dwell_flag"] == "OVERDUE"
    assert fixtures.read_keg(ctx["keg_id"])["custody_state"] == "IN_TRADE"


def _two_pools_and_a_two_keg_order_waiting_for_allocation():
    """Three kegs in HB-50L, one keg in a second pool SK-20L, and one order for two
    kegs left in `REQUESTED` so allocation can be provoked later."""
    ctx = fixtures.setup_active_float(
        float_size_kegs=3,
        keg_count=3,
        brewer_overrides={"credit_limit_cents": 400000},
        pool_overrides=dict(POOL),
        agreement_overrides={"per_fill_rate_cents": RATE},
        effective_date="2026-08-01",
        clock=CLOCK,
    )
    ctx["other_pool"] = fixtures.create_pool(**SECOND_POOL)
    ctx["foreign_keg"] = fixtures.import_keg(ctx["other_pool"]["id"], "K-9001")
    ctx["keg_ids"] = [keg["id"] for keg in ctx["kegs"]]
    ctx["order"] = fixtures.create_order(ctx["agreement"]["id"], 2)
    return ctx


def test_a_keg_of_another_pool_refuses_the_whole_investigation():
    """`keg_ids` is resolved inside the `pool_id` named in the same body, so the keg
    that belongs to SK-20L reads as not found and the request attaches nothing at
    all — there is no partial investigation to clean up.

    PRD: "List-valued foreign keys are resolved element by element in the order
    supplied, and are resolved *within* the scope named earlier in the same body: when
    a theft investigation is opened, each element of `keg_ids` must be a keg of the
    named `pool_id`, so a keg that exists but belongs to a different pool is reported
    as `ERR_KEG_NOT_FOUND` and the whole request is refused with nothing attached."

    Design: Corner/endpoints/theft_investigation_attach_is_all_or_nothing_across_pools
    """
    ctx = _two_pools_and_a_two_keg_order_waiting_for_allocation()
    first_before = fixtures.read_keg(ctx["keg_ids"][0])

    response = api_client.create_theft_investigation(
        factories.create_theft_investigation_payload(
            ctx["pool"]["id"],
            [ctx["keg_ids"][0], ctx["keg_ids"][1], ctx["foreign_keg"]["id"]],
        ),
        ANALYST,
    )
    validate_error(response, ApiErrorId.ERR_KEG_NOT_FOUND, 404)

    _rows, meta = validate_paginated(api_client.list_theft_investigations(OPERATOR))
    assert meta["total_count"] == 0

    first_after = fixtures.read_keg(ctx["keg_ids"][0])
    assert first_after["theft_investigation_id"] is None
    assert first_after["version"] == first_before["version"]
    assert fixtures.read_keg(ctx["foreign_keg"]["id"])["theft_investigation_id"] is None


def test_the_accepted_attachment_prices_the_exposure_without_moving_custody():
    """Two kegs of one pool attach for a per-keg exposure of 3900 cents each, and the
    census is untouched: the pool still reads three available kegs at 100.00 percent
    because attachment is a candidacy rule, not a custody move.

    PRD: "That attachment alone removes the keg from allocation candidacy **without
    changing its `custody_state`** — a keg under investigation stays where it is in the
    census and simply stops being issuable."

    PRD: "for each attached keg, its pool's `stainless_weight_kg` multiplied by the
    stainless price in force multiplied by the 65 percent recovery factor, rounded half
    up **per keg**, and only then summed"

    Design: Corner/endpoints/theft_investigation_attach_is_all_or_nothing_across_pools
    """
    ctx = _two_pools_and_a_two_keg_order_waiting_for_allocation()

    investigation = fixtures.open_investigation(
        ctx["pool"]["id"], [ctx["keg_ids"][0], ctx["keg_ids"][1]]
    )

    assert investigation["status"] == "OPEN"
    assert investigation["attached_keg_count"] == 2
    assert investigation["held_keg_count"] == 0
    assert investigation["opened_by_user_id"] == ANALYST_USER_ID
    assert investigation["stainless_value_at_risk_cents"] == 7800

    assert fixtures.read_keg(ctx["keg_ids"][0])["custody_state"] == "IN_FLOAT"
    assert (
        fixtures.read_keg(ctx["keg_ids"][0])["theft_investigation_id"]
        == investigation["id"]
    )
    pool = fixtures.read_pool(ctx["pool"]["id"])
    assert_census(
        pool,
        {
            "kegs_total": 3,
            "kegs_available": 3,
            "kegs_circulating": 0,
            "kegs_servicing": 0,
            "kegs_held": 0,
            "kegs_written_off": 0,
        },
    )
    assert pool["available_pct"] == 100.00
    assert pool["posture"] == "OPEN"


def test_the_two_keg_order_fails_short_of_float_while_the_pool_reads_full():
    """With two of three kegs under investigation the candidate set holds exactly one
    keg, so a two-keg order without `allow_partial` is refused for insufficiency and
    not for emptiness, and the order stays exactly where it was.

    PRD: "When the candidate set is non-empty but smaller than requested,
    `allow_partial` is true — `ERR_INSUFFICIENT_FLOAT` (409), on allocation."

    PRD: "If it is greater than zero but less than requested and `allow_partial` is
    false, the request is refused with `ERR_INSUFFICIENT_FLOAT` and nothing changes at
    all."

    Design: Corner/endpoints/theft_investigation_attach_is_all_or_nothing_across_pools
    """
    ctx = _two_pools_and_a_two_keg_order_waiting_for_allocation()
    fixtures.open_investigation(ctx["pool"]["id"], [ctx["keg_ids"][0], ctx["keg_ids"][1]])

    response = api_client.allocate_issuance_order(
        ctx["order"]["id"],
        {
            "expected_agreement_version": fixtures.agreement_version(
                ctx["agreement"]["id"]
            )
        },
        OPERATOR,
    )
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_FLOAT, 409)

    order = fixtures.read_order(ctx["order"]["id"])
    assert order["status"] == "REQUESTED"
    assert order["allocation_shortfall"] == 0
    assert order["allocated_keg_ids"] == []


def _an_investigation_attached_to_one_of_two_kegs():
    """Two kegs sit `IN_FLOAT` in one pool and the investigation names only the
    first, so the second is a real keg of the right pool that is simply not
    attached."""
    ctx = fixtures.setup_pool_with_kegs(
        keg_count=2, pool_overrides=dict(POOL), clock=CLOCK
    )
    ctx["keg_ids"] = [keg["id"] for keg in ctx["kegs"]]
    ctx["investigation"] = fixtures.open_investigation(
        ctx["pool"]["id"], [ctx["keg_ids"][0]]
    )
    return ctx


def test_holding_an_unattached_keg_is_a_membership_failure_not_a_lookup_failure():
    """The second keg exists in the same pool, so the refusal is the 409 membership
    error rather than a 404, and neither keg leaves `IN_FLOAT`.

    PRD: "Every keg named in `keg_ids` must already be attached to *this*
    investigation and must not be in `LOST`, `STOLEN` or `SCRAPPED`; a keg that is
    unattached or already written off is refused with `ERR_KEG_NOT_ATTACHED`."

    Design: Corner/endpoints/evidence_hold_refuses_a_list_holding_an_unattached_keg
    """
    ctx = _an_investigation_attached_to_one_of_two_kegs()
    before = fixtures.read_investigation(ctx["investigation"]["id"])

    response = api_client.set_investigation_status(
        ctx["investigation"]["id"],
        factories.investigation_status_payload(
            "EVIDENCE_HOLD", keg_ids=ctx["keg_ids"], hold_started_at=CLOCK
        ),
        ANALYST,
    )
    validate_error(response, ApiErrorId.ERR_KEG_NOT_ATTACHED, 409)

    after = fixtures.read_investigation(ctx["investigation"]["id"])
    assert after["status"] == "OPEN"
    assert after["held_keg_count"] == 0
    assert after["hold_started_at"] is None
    assert after["version"] == before["version"]

    assert fixtures.read_keg(ctx["keg_ids"][0])["custody_state"] == "IN_FLOAT"
    assert fixtures.read_keg(ctx["keg_ids"][1])["custody_state"] == "IN_FLOAT"
    pool = fixtures.read_pool(ctx["pool"]["id"])
    assert_census(
        pool,
        {
            "kegs_total": 2,
            "kegs_available": 2,
            "kegs_circulating": 0,
            "kegs_servicing": 0,
            "kegs_held": 0,
            "kegs_written_off": 0,
        },
    )
    assert pool["available_pct"] == 100.00


def test_the_retry_holds_exactly_the_named_subset_and_records_its_bucket():
    """Naming only the attached keg is accepted: that keg records `IN_FLOAT` as the
    bucket it must be returned to and moves into `kegs_held`, while the pool's other
    keg is untouched and availability halves.

    PRD: "Each named keg records its current custody state into
    `pre_hold_custody_state` and then moves to `EVIDENCE_HOLD`, which pulls it out of
    whichever census bucket it occupied and into `kegs_held`."

    PRD: "The investigation moves to `EVIDENCE_HOLD` and recomputes `hold_started_at`,
    `held_keg_count` and `stainless_value_at_risk_cents`."

    Design: Corner/endpoints/evidence_hold_refuses_a_list_holding_an_unattached_keg
    """
    ctx = _an_investigation_attached_to_one_of_two_kegs()

    held = fixtures.set_investigation_status(
        ctx["investigation"]["id"],
        "EVIDENCE_HOLD",
        keg_ids=[ctx["keg_ids"][0]],
        hold_started_at=CLOCK,
    )

    assert held["status"] == "EVIDENCE_HOLD"
    assert held["held_keg_count"] == 1
    assert held["hold_started_at"] == CLOCK

    first = fixtures.read_keg(ctx["keg_ids"][0])
    assert first["custody_state"] == "EVIDENCE_HOLD"
    assert first["pre_hold_custody_state"] == "IN_FLOAT"
    assert fixtures.read_keg(ctx["keg_ids"][1])["custody_state"] == "IN_FLOAT"

    pool = fixtures.read_pool(ctx["pool"]["id"])
    assert_census(
        pool,
        {
            "kegs_total": 2,
            "kegs_available": 1,
            "kegs_circulating": 0,
            "kegs_servicing": 0,
            "kegs_held": 1,
            "kegs_written_off": 0,
        },
    )
    assert pool["available_pct"] == 50.00
    assert pool["posture"] == "OPEN"


def _one_keg_carrying_a_fill_a_distribution_and_a_retail_scan():
    """Three scans on one keg, all under the float owner's own brand so none of them
    is a misdelivery."""
    ctx = fixtures.setup_active_float(
        float_size_kegs=2,
        keg_count=2,
        brewer_overrides={"credit_limit_cents": 400000},
        pool_overrides=dict(POOL),
        agreement_overrides={"per_fill_rate_cents": RATE},
        keg_specs=[dict(spec) for spec in KEG_SPECS],
        effective_date="2026-08-01",
        clock="2026-08-10T23:00:00Z",
    )
    ctx["distributor"] = fixtures.create_distributor()
    order = fixtures.order_allocated_and_dispatched(
        ctx["agreement"]["id"], 1, "2026-08-01T00:00:00Z"
    )
    ctx["keg_id"] = order["allocated_keg_ids"][0]
    fixtures.fill_scan(
        ctx["keg_id"], ctx["brewer"]["id"], "2026-08-03T00:00:00Z", "RDG"
    )
    fixtures.distribution_scan(
        ctx["keg_id"], ctx["distributor"]["id"], "2026-08-05T00:00:00Z", "RDG"
    )
    fixtures.retail_scan(
        ctx["keg_id"],
        ctx["distributor"]["id"],
        "TAP-114",
        "2026-08-07T00:00:00Z",
        "RDG",
    )
    return ctx


def test_the_scan_point_filter_narrows_the_stream_to_the_one_matching_row():
    """Unfiltered the keg's stream is three rows on the default page of ten; adding
    `scan_point` leaves exactly the fill, which still carries its own priced charge and
    the two dwell days it closed.

    PRD: "Scan events are readable individually and listable with filters on `keg_id`,
    `brewer_id`, `distributor_id`, `scan_point`, `misdelivery_detected` and
    `is_late_arrival`."

    PRD: "`limit` controls page size: it defaults to 10, may be no smaller than 1 and
    no larger than 100."

    Design: Corner/endpoints/scan_event_listing_filters_compose_and_never_leak_other_scan_points
    """
    ctx = _one_keg_carrying_a_fill_a_distribution_and_a_retail_scan()

    rows, meta = validate_paginated(
        api_client.list_scan_events(OPERATOR, params={"keg_id": ctx["keg_id"]})
    )
    assert len(rows) == 3
    assert meta["total_count"] == 3
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["has_more"] is False
    assert all(row["keg_id"] == ctx["keg_id"] for row in rows)
    assert all(row["misdelivery_detected"] is False for row in rows)

    fills, fill_meta = validate_paginated(
        api_client.list_scan_events(
            OPERATOR, params={"keg_id": ctx["keg_id"], "scan_point": "FILL"}
        )
    )
    assert fill_meta["total_count"] == 1
    assert len(fills) == 1
    assert fills[0]["scan_point"] == "FILL"
    assert fills[0]["fill_charge_net_cents"] == RATE
    assert fills[0]["dwell_days_closed"] == 2


def test_the_page_window_and_the_boolean_filter_both_read_the_filtered_set():
    """A limit of two splits the same three-row stream into pages of two and one while
    `total_count` stays 3, and asking for the misdelivered rows returns an empty page
    with `total_count` 0 rather than falling back to the unfiltered stream.

    PRD: "For list responses, the `meta` object carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` is the number of rows matching the
    filters before pagination is applied and `has_more` is true when rows remain beyond
    the current page."

    Design: Corner/endpoints/scan_event_listing_filters_compose_and_never_leak_other_scan_points
    """
    ctx = _one_keg_carrying_a_fill_a_distribution_and_a_retail_scan()

    first_page, first_meta = validate_paginated(
        api_client.list_scan_events(
            OPERATOR, params={"keg_id": ctx["keg_id"], "limit": 2, "offset": 0}
        )
    )
    assert len(first_page) == 2
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True

    second_page, second_meta = validate_paginated(
        api_client.list_scan_events(
            OPERATOR, params={"keg_id": ctx["keg_id"], "limit": 2, "offset": 2}
        )
    )
    assert len(second_page) == 1
    assert second_meta["offset"] == 2
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    misdelivered, misdelivered_meta = validate_paginated(
        api_client.list_scan_events(
            OPERATOR,
            params={"keg_id": ctx["keg_id"], "misdelivery_detected": "true"},
        )
    )
    assert misdelivered == []
    assert misdelivered_meta["total_count"] == 0
    assert misdelivered_meta["has_more"] is False


def _an_issued_chargeback_on_one_lost_keg():
    """One keg of three filled once and then written off under `LOST_IN_TRADE` on the
    depreciated-book basis, upheld by a second analyst so the money is live."""
    ctx = fixtures.setup_active_float(
        float_size_kegs=3,
        keg_count=3,
        brewer_overrides={"credit_limit_cents": 400000},
        pool_overrides=dict(POOL),
        agreement_overrides={"per_fill_rate_cents": RATE},
        keg_specs=[
            {"asset_tag": "K-0001"},
            {"asset_tag": "K-0002", "fill_count": 5, "fills_at_last_pressure_test": 5},
            {"asset_tag": "K-0003", "fill_count": 6, "fills_at_last_pressure_test": 6},
        ],
        effective_date="2026-08-01",
        clock=CLOCK,
    )
    order = fixtures.order_allocated_and_dispatched(
        ctx["agreement"]["id"], 1, "2026-08-01T00:00:00Z"
    )
    ctx["keg_id"] = order["allocated_keg_ids"][0]
    fixtures.fill_scan(
        ctx["keg_id"], ctx["brewer"]["id"], "2026-08-01T12:00:00Z", "RDG"
    )
    ctx["assessment"] = fixtures.open_loss_assessment(
        ctx["keg_id"], "LOST_IN_TRADE", assessment_basis="DEPRECIATED_BOOK"
    )
    ctx["upheld"] = fixtures.resolve_assessment(ctx["assessment"]["id"], "UPHELD")
    return ctx


def test_the_book_basis_pins_the_net_chargeback_the_settlement_must_match():
    """One fill writes 45 basis points off a 23500-cent shell, so the book value is
    23394 — well above the 7050 floor — and with no scrap credit and a 6000-basis-point
    share the ledger row is 14036 cents.

    PRD: "Under **`DEPRECIATED_BOOK`**, the replacement cost is written down 45 basis
    points for every lifetime fill, with total depreciation capped at 7000 basis points.
    A candidate book value is the `replacement_cost_cents` multiplied by 10000 less that
    depreciation, divided by 10000, rounded half up; a floor value is 30 percent of
    `replacement_cost_cents`, rounded half up; and `gross_value_cents` is the greater of
    the two."

    PRD: "And `net_chargeback_cents` is the assessed value multiplied by that liability
    share as a proportion of 10000, rounded half up."

    Design: Corner/endpoints/chargeback_settlement_demands_the_exact_net_amount
    """
    ctx = _an_issued_chargeback_on_one_lost_keg()
    assessment = fixtures.read_assessment(ctx["assessment"]["id"])

    assert assessment["assessment_basis"] == "DEPRECIATED_BOOK"
    assert assessment["gross_value_cents"] == 23394
    assert assessment["scrap_credit_cents"] == 0
    assert assessment["assessed_value_cents"] == 23394
    assert assessment["brewer_liability_pct_bp"] == 6000
    assert assessment["net_chargeback_cents"] == 14036
    assert assessment["assessment_status"] == "UPHELD"
    assert assessment["chargeback_status"] == "ISSUED"

    keg = fixtures.read_keg(ctx["keg_id"])
    assert keg["custody_state"] == "LOST"
    assert keg["assessment_open"] is False


def test_a_balance_under_the_gate_leaves_the_reason_to_the_loss_rate():
    """A single loss over a single fill is a trailing rate of 10000 basis points while
    the balance of 14036 stays under 25000, so the balance gate never fires and the
    probation reason must read `LOSS_RATE_THRESHOLD`.

    PRD: "`LOSS_RATE_THRESHOLD` therefore appears only when the recomputed balance is
    strictly below 25000 cents while the trailing rate is at or above 1500 basis
    points."

    PRD: "Because the brewer entered probation, every `ACTIVE` float agreement of that
    brewer recomputes `float_posture` to `SUSPENDED`, which blocks that brewer's later
    allocations and fill scans."

    Design: Corner/endpoints/chargeback_settlement_demands_the_exact_net_amount
    """
    ctx = _an_issued_chargeback_on_one_lost_keg()

    brewer = fixtures.read_brewer(ctx["brewer"]["id"])
    assert brewer["chargeback_balance_cents"] == 14036
    assert brewer["upheld_loss_count"] == 1
    assert brewer["loss_rate_bp_trailing_90d"] == 10000
    assert brewer["loss_rate_bp_lifetime"] == 10000
    assert brewer["status"] == "PROBATION"
    assert brewer["status_reason"] == "LOSS_RATE_THRESHOLD"

    assert (
        fixtures.read_agreement(ctx["agreement"]["id"])["float_posture"] == "SUSPENDED"
    )
    pool = fixtures.read_pool(ctx["pool"]["id"])
    assert_census(
        pool,
        {
            "kegs_total": 3,
            "kegs_available": 2,
            "kegs_circulating": 0,
            "kegs_servicing": 0,
            "kegs_held": 0,
            "kegs_written_off": 1,
        },
    )
    assert pool["available_pct"] == 66.67
    assert pool["posture"] == "OPEN"


def test_a_settlement_thirty_six_cents_short_is_refused_and_the_exact_one_settles():
    """The same operator and the same endpoint differ only in `amount_cents`: 14000 is
    refused with the row untouched, 14036 settles it, and settling moves no money
    because `SETTLED` stays inside the ledger sum.

    PRD: "A `SETTLE` requires `chargeback_status` `ISSUED` and an `amount_cents` exactly
    equal to `net_chargeback_cents`; partial settlement is not supported and any other
    figure is `ERR_SETTLEMENT_AMOUNT_MISMATCH`."

    PRD: "It moves the status to `SETTLED`, records `settled_amount_cents`, and leaves
    `chargeback_balance_cents` unchanged."

    Design: Corner/endpoints/chargeback_settlement_demands_the_exact_net_amount
    """
    ctx = _an_issued_chargeback_on_one_lost_keg()
    before = fixtures.read_assessment(ctx["assessment"]["id"])

    response = api_client.chargeback_resolution(
        ctx["assessment"]["id"],
        factories.chargeback_resolution_payload(
            "SETTLE",
            amount_cents=14000,
            resolution_notes="Brewer remitted a round number.",
        ),
        OPERATOR,
    )
    validate_error(response, ApiErrorId.ERR_SETTLEMENT_AMOUNT_MISMATCH, 422)

    refused = fixtures.read_assessment(ctx["assessment"]["id"])
    assert refused["chargeback_status"] == "ISSUED"
    assert refused["settled_amount_cents"] is None
    assert refused["version"] == before["version"]

    settled = fixtures.settle_chargeback(
        ctx["assessment"]["id"], 14036, resolution_notes="Exact remittance."
    )
    assert settled["chargeback_status"] == "SETTLED"
    assert settled["settled_amount_cents"] == 14036

    brewer = fixtures.read_brewer(ctx["brewer"]["id"])
    assert brewer["chargeback_balance_cents"] == 14036
    assert brewer["status"] == "PROBATION"


def _a_keg_distributed_under_a_second_brewers_collar():
    """K-0001 is filled under RDG on 2026-08-03 and then read as OAK at distribution on
    2026-08-05, which is the misdelivery the claim must cite."""
    ctx = fixtures.setup_misdelivery_evidence(
        owning_fill_at="2026-08-03T00:00:00Z",
        distribution_at="2026-08-05T00:00:00Z",
        other_brand_code="OAK",
        other_brewer_name="Oakline Ales",
        float_size_kegs=2,
        keg_count=2,
        brewer_overrides={"credit_limit_cents": 400000},
        pool_overrides=dict(POOL),
        agreement_overrides={"per_fill_rate_cents": RATE},
        keg_specs=[dict(spec) for spec in KEG_SPECS],
        effective_date="2026-08-01",
        clock="2026-08-10T23:00:00Z",
    )
    ctx["claimant_headers"] = make_distributor_headers(ctx["distributor"]["id"])
    return ctx


def test_both_halves_of_the_evidence_link_are_checked_independently():
    """Citing the fill instant names a real scan that detected nothing, and citing the
    misdelivery instant against the keg's own owning brewer names the wrong brand
    holder; each is refused on its own and neither writes a claim.

    PRD: "Evidence is mandatory and is checked strictly: the keg must carry a scan
    event whose `misdelivery_detected` is true and whose `scanned_at` equals the supplied
    `evidence_scanned_at` exactly, and the named `misdelivered_to_brewer_id` must be the
    brewer whose `brand_code` equals *that scan's* `brand_code_scanned`."

    PRD: "Naming any other brewer — including the keg's own owning brewer — fails with
    `ERR_NO_MISDELIVERY_EVIDENCE`, as does citing an instant on which no misdelivery was
    detected."

    Design: Corner/endpoints/misdelivery_claim_must_name_the_evidence_scan_and_the_wrong_brand_owner
    """
    ctx = _a_keg_distributed_under_a_second_brewers_collar()

    wrong_instant = api_client.create_reconciliation_claim(
        factories.create_reconciliation_claim_payload(
            ctx["keg_id"], ctx["other_brewer"]["id"], 1200, "2026-08-03T00:00:00Z"
        ),
        ctx["claimant_headers"],
    )
    validate_error(wrong_instant, ApiErrorId.ERR_NO_MISDELIVERY_EVIDENCE, 422)

    wrong_brewer = api_client.create_reconciliation_claim(
        factories.create_reconciliation_claim_payload(
            ctx["keg_id"], ctx["brewer"]["id"], 1200, "2026-08-05T00:00:00Z"
        ),
        ctx["claimant_headers"],
    )
    validate_error(wrong_brewer, ApiErrorId.ERR_NO_MISDELIVERY_EVIDENCE, 422)

    _rows, meta = validate_paginated(
        api_client.list_reconciliation_claims(
            OPERATOR, params={"keg_id": ctx["keg_id"]}
        )
    )
    assert meta["total_count"] == 0


def test_the_accepted_claim_derives_its_two_other_parties():
    """The pair (misdelivery instant, brewer owning the scanned brand) is accepted, and
    the claim reads its claimant off the acting distributor and its owning brewer off the
    keg rather than off the payload.

    PRD: "The claim's own `claimant_distributor_id` is resolved from the acting
    `X-User-ID` rather than supplied, and `owning_brewer_id` is copied from the keg's
    `filling_brewer_id`."

    PRD: "A new claim opens in `SUBMITTED` with `round_count` at 0,
    `counter_offset_cents` and `agreed_offset_cents` unset, and `last_responder_role`
    already recorded as `Distributor`, because filing the claim *is* the distributor's
    first move."

    Design: Corner/endpoints/misdelivery_claim_must_name_the_evidence_scan_and_the_wrong_brand_owner
    """
    ctx = _a_keg_distributed_under_a_second_brewers_collar()

    claim = fixtures.file_claim(
        ctx["keg_id"],
        ctx["distributor"]["id"],
        ctx["other_brewer"]["id"],
        1200,
        "2026-08-05T00:00:00Z",
    )

    assert claim["status"] == "SUBMITTED"
    assert claim["round_count"] == 0
    assert claim["counter_offset_cents"] is None
    assert claim["agreed_offset_cents"] is None
    assert claim["last_responder_role"] == "Distributor"
    assert claim["claimed_offset_cents"] == 1200
    assert claim["claimant_distributor_id"] == ctx["distributor"]["id"]
    assert claim["owning_brewer_id"] == ctx["brewer"]["id"]
    assert claim["misdelivered_to_brewer_id"] == ctx["other_brewer"]["id"]
    assert claim["evidence_scanned_at"] == "2026-08-05T00:00:00Z"


def _four_seeded_kegs_and_one_keg_in_a_second_pool():
    """K-0001 plain, K-0002 seeded `IN_SERVICE`, K-0003 seeded `QUARANTINED`, K-0004
    seeded 25 fills past its last pressure test, plus one keg in another pool."""
    ctx = fixtures.setup_pool_with_kegs(
        pool_overrides=dict(POOL),
        keg_specs=[
            {"asset_tag": "K-0001"},
            {"asset_tag": "K-0002", "initial_custody_state": "IN_SERVICE"},
            {"asset_tag": "K-0003", "initial_custody_state": "QUARANTINED"},
            {"asset_tag": "K-0004", "fill_count": 25, "fills_at_last_pressure_test": 0},
        ],
        clock=CLOCK,
    )
    ctx["keg_ids"] = [keg["id"] for keg in ctx["kegs"]]
    ctx["other_pool"] = fixtures.create_pool(**SECOND_POOL)
    ctx["foreign_keg"] = fixtures.import_keg(ctx["other_pool"]["id"], "K-9001")
    return ctx


def _listed_keg_ids(params):
    rows, meta = validate_paginated(api_client.list_kegs(OPERATOR, params=params))
    return [row["id"] for row in rows], meta


def test_the_custody_and_service_filters_intersect_rather_than_shadow():
    """Two kegs are `IN_FLOAT` and one is `SERVICE_DUE`; asking for both dimensions at
    once returns the single row that satisfies each, so neither filter can be the one
    that decided the page.

    PRD: "The whole fleet can also be listed and filtered by `pool_id`,
    `current_brewer_id`, `current_distributor_id`, `filling_brewer_id`,
    `issuance_order_id`, `theft_investigation_id`, `custody_state`, `service_state` and
    `dwell_flag`; this second listing is the reverse-lookup channel for every custody
    foreign key a keg carries."

    PRD: "If `fill_count` minus `fills_at_last_pressure_test` is at least 25 fills, the
    keg opens `SERVICE_DUE`."

    Design: Corner/endpoints/keg_listing_filters_the_custody_and_service_dimensions_independently
    """
    ctx = _four_seeded_kegs_and_one_keg_in_a_second_pool()
    pool_id = ctx["pool"]["id"]
    plain, due_keg = ctx["keg_ids"][0], ctx["keg_ids"][3]

    in_float, in_float_meta = _listed_keg_ids(
        {"pool_id": pool_id, "custody_state": "IN_FLOAT"}
    )
    assert in_float_meta["total_count"] == 2
    assert set(in_float) == {plain, due_keg}

    service_due, service_due_meta = _listed_keg_ids(
        {"pool_id": pool_id, "service_state": "SERVICE_DUE"}
    )
    assert service_due_meta["total_count"] == 1
    assert service_due == [due_keg]

    both, both_meta = _listed_keg_ids(
        {
            "pool_id": pool_id,
            "custody_state": "IN_FLOAT",
            "service_state": "SERVICE_OK",
        }
    )
    assert both_meta["total_count"] == 1
    assert both == [plain]


def test_the_seeded_fleet_is_all_within_limit_and_none_of_it_is_overdue():
    """No certification is older than 730 days and no sweep has run, so nothing reads
    `SERVICE_OVERDUE` while every keg — including the two out of circulation — still
    carries the `WITHIN_LIMIT` flag it was imported with, and the other pool's keg never
    appears.

    PRD: "Newly imported kegs open with `dwell_flag` `WITHIN_LIMIT`, with
    `current_brewer_id`, `current_distributor_id`, `filling_brewer_id`,
    `issuance_order_id`, `theft_investigation_id`, `filled_brand_code`,
    `dwell_started_at`, `distributor_custody_started_at`, `last_scanned_at` and
    `pre_hold_custody_state` all unset, with `cumulative_dwell_days` and `scan_count` at
    0, and with `misdelivery_open` and `assessment_open` both false."

    PRD: "`last_pressure_test_at` records the instant of that last passing test; when
    the caller omits it the server records the new keg's own `created_at`, treating the
    factory acceptance test as the certification event, so this field is never null and
    every certification comparison is well defined."

    Design: Corner/endpoints/keg_listing_filters_the_custody_and_service_dimensions_independently
    """
    ctx = _four_seeded_kegs_and_one_keg_in_a_second_pool()
    pool_id = ctx["pool"]["id"]

    overdue, overdue_meta = _listed_keg_ids(
        {"pool_id": pool_id, "service_state": "SERVICE_OVERDUE"}
    )
    assert overdue_meta["total_count"] == 0
    assert overdue == []

    within, within_meta = _listed_keg_ids(
        {"pool_id": pool_id, "dwell_flag": "WITHIN_LIMIT"}
    )
    assert within_meta["total_count"] == 4
    assert set(within) == set(ctx["keg_ids"])
    assert ctx["foreign_keg"]["id"] not in within

    rows, _meta = validate_paginated(
        api_client.list_kegs(OPERATOR, params={"pool_id": pool_id})
    )
    assert all(row["pool_id"] == pool_id for row in rows)
