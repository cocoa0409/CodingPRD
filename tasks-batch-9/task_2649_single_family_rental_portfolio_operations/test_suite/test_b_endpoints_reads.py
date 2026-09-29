"""The three computed reads: the ranking, the posture decision, and the clock behind both.

None of these endpoints stores anything. Each is checked against the write it predicts -- the
ranking against the dispatch that follows it, the posture against the row it is derived from, and
the clock against a home whose posture flips with nothing else changed.
"""

from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers.api_errors import (
    ERR_VENDOR_INACTIVE,
    ERR_VENDOR_INSURANCE_EXPIRED,
    ERR_VENDOR_NOT_CERTIFIED,
)
from test_helpers.assertions import (
    assert_fields,
    assert_version,
    created,
    ok,
)
from test_helpers.constants import (
    CLOCK_AUG_01,
    CLOCK_SEP_15_NOON,
    POSTURE_FROZEN,
    POSTURE_RESTRICTED,
    WO_DISPATCHED,
)
from test_helpers.test_users import headers_without_user_id


def test_the_ranking_read_names_the_winner_the_dispatch_then_writes(api):
    """Two bids in order, three exclusions each labelled, and the same winner on the row.

    PRD SS3.4: "The same ranking is exposed read-only so an operations manager can inspect a
    dispatch before making it. That computed read returns the `work_order_id`,
    `eligible_vendor_ids` ordered by the ranking above, `bid_cents` positionally aligned with that
    array, `excluded_vendor_ids` listing every same-market vendor that failed the eligibility
    filter, `exclusion_reasons` positionally aligned with the exclusions where each entry is the
    error identifier of the **first** eligibility clause that vendor failed -- one of
    `ERR_VENDOR_INACTIVE`, `ERR_VENDOR_INSURANCE_EXPIRED`, `ERR_VENDOR_NOT_CERTIFIED` or
    `ERR_VENDOR_CAPACITY_EXCEEDED` -- and `winning_vendor_id`, which is the first eligible
    identifier or the empty string when the eligible set is empty."  The bids are the PRD's own:
    "Take a paint work order whose `benchmark_total_cents` is 292176: a vendor with
    `cost_index_bps` 9800 and `quality_score_bps` 8600 bids 286332, while a vendor with
    `cost_index_bps` 10100 and `quality_score_bps` 9400 bids 295098, and the first wins despite
    scoring 800 basis points worse on quality."  The write that follows is PRD SS3.4's: "the work
    order moves `PENDING_DISPATCH -> DISPATCHED`, its `vendor_id` is set to the selected vendor,
    and that vendor's `committed_crew_days` increases by this work order's `crew_days`."

    Design: Corner/endpoints/vendor_ranking_read_matches_the_dispatch_the_engine_would_make
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    paint = x.create_scope_template(api, f.scope_template_general())
    home = x.create_home(api, market["id"])
    vendors = x.two_certified_vendors(api, market["id"])

    uncertified = x.create_vendor(
        api,
        market["id"],
        legal_name="Uncertified Cheap Crews",
        daily_crew_capacity=10,
        cost_index_bps=9000,
        quality_score_bps=9900,
        insurance_expires_on="2027-06-30",
    )
    lapsed = x.create_vendor(
        api,
        market["id"],
        legal_name="Lapsed Binder Brothers",
        daily_crew_capacity=10,
        cost_index_bps=9100,
        quality_score_bps=9000,
        insurance_expires_on="2026-07-31",
    )
    x.certify_vendor(api, lapsed["id"], "GEN", expires_on="2027-01-01")
    suspended = x.create_vendor(
        api,
        market["id"],
        legal_name="Suspended Southside",
        daily_crew_capacity=10,
        cost_index_bps=9200,
        quality_score_bps=8900,
        insurance_expires_on="2027-06-30",
    )
    x.certify_vendor(api, suspended["id"], "GEN", expires_on="2027-01-01")
    ok(
        api.set_vendor_status(
            suspended["id"],
            f.vendor_status_payload("SUSPENDED", suspension_reason="Workmanship complaints"),
            x.VENDOR_MANAGER,
        )
    )

    order = created(
        api.create_work_order(
            f.work_order_payload(
                home["id"], paint["id"], work_type="TURN", fulfillment_channel="VENDOR"
            ),
            x.OPS,
        )
    )

    ranking = ok(api.get_vendor_ranking(order["id"], x.OPS))
    assert ranking["work_order_id"] == order["id"]
    assert ranking["eligible_vendor_ids"] == [
        vendors.cheap.vendor_id,
        vendors.pricey.vendor_id,
    ]
    assert ranking["bid_cents"] == [286332, 295098]
    assert ranking["winning_vendor_id"] == vendors.cheap.vendor_id

    excluded = ranking["excluded_vendor_ids"]
    reasons = ranking["exclusion_reasons"]
    assert len(excluded) == 3
    assert sorted(excluded) == sorted([uncertified["id"], lapsed["id"], suspended["id"]])
    paired = dict(zip(excluded, reasons))
    assert paired[uncertified["id"]] == ERR_VENDOR_NOT_CERTIFIED
    assert paired[lapsed["id"]] == ERR_VENDOR_INSURANCE_EXPIRED
    assert paired[suspended["id"]] == ERR_VENDOR_INACTIVE

    dispatched = ok(api.dispatch_work_order(order["id"], {}, x.OPS))
    assert_fields(
        dispatched,
        status=WO_DISPATCHED,
        vendor_id=vendors.cheap.vendor_id,
        crew_days=9,
    )
    assert_fields(
        ok(api.get_vendor(vendors.cheap.vendor_id, x.VENDOR_MANAGER)), committed_crew_days=9
    )
    assert_fields(
        ok(api.get_vendor(vendors.pricey.vendor_id, x.VENDOR_MANAGER)), committed_crew_days=0
    )


def test_the_posture_read_explains_a_lapsed_binder_then_a_renewal_then_an_obligation(api):
    """Clause 2 with an empty blocking list, clause 5 after the renewal, clause 4 with an id.

    PRD SS2.8: "A dedicated computed read exposes the whole decision for a single home: it returns
    `home_id`, the resulting `leasing_posture`, `deciding_clause` as the integer number (1 through
    6) of the clause that produced it, `blocking_obligation_ids` as the identifiers of the
    obligations that contributed to the decision, and `binder_expired` as a boolean stating whether
    the second clause's condition currently holds."  The clauses are PRD SS2.8's own: "2. Otherwise,
    if `insurance_binder_expires_on` is earlier than the current logical-clock date, the posture is
    `FROZEN`. ... 4. Otherwise, if the home has at least one compliance obligation whose `severity`
    is `MAJOR` and whose `status` is one of `OPEN`, `PLANNED`, `RESOLUTION_SUBMITTED` or
    `RESOLUTION_REJECTED`, the posture is `RESTRICTED`. 5. Otherwise, if `asset_status` is
    `PIPELINE` or `ACQUIRED`, the posture is `RESTRICTED`."  The renewal is an ordinary partial
    update -- PRD SS3.1: "The mutable facts of a home can be revised later by an
    `AcquisitionAnalyst` or `PortfolioAdmin`: ... only the supplied fields are overwritten. ...
    Revising `insurance_binder_expires_on` recomputes `leasing_posture`, which is the quiet path by
    which an administrative correction can freeze a home and push its `AVAILABLE` showing windows to
    `BLOCKED_BY_POSTURE`, or renew a binder and release them back to `AVAILABLE`. Either way the
    home's `version` increments by 1."

    Design: Corner/endpoints/leasing_posture_read_exposes_binder_expiry_and_blocking_ids
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    home = x.create_home(api, market["id"], insurance_binder_expires_on="2026-07-31")

    lapsed = ok(api.get_leasing_posture(home["id"], x.AGENT))
    assert lapsed["home_id"] == home["id"]
    assert_fields(
        lapsed,
        leasing_posture=POSTURE_FROZEN,
        deciding_clause=2,
        binder_expired=True,
        blocking_obligation_ids=[],
    )

    renewed = ok(
        api.patch_home(home["id"], {"insurance_binder_expires_on": "2027-06-30"}, x.ANALYST)
    )
    assert_fields(renewed, leasing_posture=POSTURE_RESTRICTED)
    assert_version(renewed, 2)

    covered = ok(api.get_leasing_posture(home["id"], x.AGENT))
    assert_fields(
        covered,
        leasing_posture=POSTURE_RESTRICTED,
        deciding_clause=5,
        binder_expired=False,
        blocking_obligation_ids=[],
    )

    obligation = x.open_obligation(
        api,
        home["id"],
        obligation_type="INSURANCE_DEFICIENCY",
        severity="MAJOR",
        description="Wind mitigation endorsement missing",
        due_on="2026-10-31",
    )
    blocked = ok(api.get_leasing_posture(home["id"], x.AGENT))
    assert_fields(
        blocked,
        leasing_posture=POSTURE_RESTRICTED,
        deciding_clause=4,
        binder_expired=False,
        blocking_obligation_ids=[obligation["id"]],
    )


def test_the_clock_is_re_settable_and_the_same_home_freezes_when_it_passes_the_binder(api):
    """Nothing about the home changes between the two reads except what the clock says.

    PRD SS2.4: "Every date and instant comparison in this API reads a **logical clock** rather than
    wall-clock time. The clock boots at `2026-08-01T00:00:00Z`. A `System` caller may set it to any
    instant by supplying `current_utc`; a read of the clock returns the same field name. Setting the
    clock never rewrites values already stored: it only changes what subsequent comparisons see.
    That matters in three places in particular -- the derived leasing posture of every home (because
    an insurance binder is judged expired relative to the clock), vendor dispatch eligibility ...
    and the rejection of showing windows that start in the past."  PRD SS3.1 on the exemption: "a
    `System` caller may advance or rewind the logical clock to a supplied `current_utc` instant, and
    any role may read the clock's present value. This is the only operation in the system exempt
    from the `X-User-ID` requirement."  The flip is clause 2 of PRD SS2.8: "Otherwise, if
    `insurance_binder_expires_on` is earlier than the current logical-clock date, the posture is
    `FROZEN`", against clause 5's "if `asset_status` is `PIPELINE` or `ACQUIRED`, the posture is
    `RESTRICTED`."

    Design: Corner/endpoints/logical_clock_set_and_read_drive_every_date_comparison
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    home = x.create_home(api, market["id"], insurance_binder_expires_on="2026-09-01")

    assert ok(api.get_clock(x.AGENT))["current_utc"] == CLOCK_AUG_01
    before = ok(api.get_leasing_posture(home["id"], x.AGENT))
    assert_fields(
        before,
        leasing_posture=POSTURE_RESTRICTED,
        deciding_clause=5,
        binder_expired=False,
    )

    ok(
        api.set_clock(
            f.clock_payload(CLOCK_SEP_15_NOON), headers_without_user_id("System")
        )
    )
    assert ok(api.get_clock(x.AGENT))["current_utc"] == CLOCK_SEP_15_NOON

    after = ok(api.get_leasing_posture(home["id"], x.AGENT))
    assert_fields(
        after,
        leasing_posture=POSTURE_FROZEN,
        deciding_clause=2,
        binder_expired=True,
    )
    assert_fields(
        ok(api.get_home(home["id"], x.AGENT)), insurance_binder_expires_on="2026-09-01"
    )
