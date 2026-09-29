"""Paid-slot capacity, ranking construction and the disclosure gate on publication."""
from __future__ import annotations

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.assertions import assert_instant_equals, assert_score
from test_helpers.fixtures import (
    DEFAULT_INSTANT,
    certified_air,
    certified_hotel,
    hotel_agency_offer,
)
from test_helpers.test_users import (
    COMMERCIAL_MANAGER,
    COMPLIANCE_OFFICER,
    COMPLIANCE_OFFICER_USER_ID,
    PLATFORM_ADMIN,
)


def _capacity_scenario(b):
    """One ACTIVE two-slot deal over [2026-09-01, 2026-09-11) plus three proposals."""
    ctx = certified_hotel(b)
    supplier_id = ctx.supplier["id"]
    market_id = ctx.market["id"]
    ctx["active"] = b.placement(
        supplier_id,
        market_id,
        slots=2,
        window_start="2026-09-01",
        window_end="2026-09-11",
    )
    ctx["overlapping"] = b.placement(
        supplier_id,
        market_id,
        approve=False,
        slots=2,
        window_start="2026-09-10",
        window_end="2026-09-20",
    )
    ctx["adjacent"] = b.placement(
        supplier_id,
        market_id,
        approve=False,
        slots=2,
        window_start="2026-09-11",
        window_end="2026-09-21",
    )
    ctx["single_day"] = b.placement(
        supplier_id,
        market_id,
        approve=False,
        slots=1,
        window_start="2026-09-11",
        window_end="2026-09-12",
    )
    return ctx


def test_placement_approval_is_refused_when_one_shared_day_exceeds_capacity(b, client):
    """A single overlapping date at four slots against a capacity of three is fatal.

    PRD 3.6: "If that sum plus the candidate's own `slots` would exceed the
    market's `paid_slot_capacity` on any single date, approval is rejected with
    `ERR_PLACEMENT_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/placement_half_open_windows_allow_adjacency_but_reject_day_overlap
    """
    ctx = _capacity_scenario(b)

    refused = client.approve_placement_agreement(
        ctx.overlapping["id"], {}, PLATFORM_ADMIN
    )
    validate_error(refused, E.ERR_PLACEMENT_CAPACITY_EXCEEDED, 409)

    still_proposed = validate_success(
        client.get_placement_agreement(ctx.overlapping["id"], PLATFORM_ADMIN)
    )
    assert still_proposed["status"] == "PROPOSED"
    assert still_proposed["approved_by_user_id"] is None
    assert still_proposed["version"] == ctx.overlapping["version"]

    incumbent = validate_success(
        client.get_placement_agreement(ctx.active["id"], PLATFORM_ADMIN)
    )
    assert incumbent["status"] == "ACTIVE"


def test_placement_windows_that_merely_touch_never_compete_for_a_slot(b, client):
    """An exclusive window_end shares no day, and filling capacity exactly is allowed.

    PRD 3.6: "because placement windows are half-open, an agreement whose
    `window_start` equals another's `window_end` shares no date with it and never
    competes for a slot" and "The comparison is strictly greater-than, so filling
    the market's capacity exactly is permitted".

    Design: Difficulty/resource_temporal_overlap/placement_half_open_windows_allow_adjacency_but_reject_day_overlap
    """
    ctx = _capacity_scenario(b)

    adjacent = validate_success(
        client.approve_placement_agreement(ctx.adjacent["id"], {}, PLATFORM_ADMIN)
    )
    assert adjacent["status"] == "ACTIVE"
    assert adjacent["version"] == ctx.adjacent["version"] + 1

    exact_fill = validate_success(
        client.approve_placement_agreement(ctx.single_day["id"], {}, PLATFORM_ADMIN)
    )
    assert exact_fill["status"] == "ACTIVE"

    incumbent = validate_success(
        client.get_placement_agreement(ctx.active["id"], PLATFORM_ADMIN)
    )
    assert incumbent["status"] == "ACTIVE"
    assert incumbent["slots"] == 2


def test_the_ranking_pool_excludes_an_offer_that_never_went_live(b, client):
    """Only LIVE offers are scored, and the organic score uses the declared weights.

    PRD 3.6: "A candidate offer must have `status` `LIVE` ... Offers that are
    pending, suppressed, closed or superseded never enter the pool", and
    `organic_score` sums "the rounded `price_competitiveness` weighted at forty
    percent, the supplier's `content_score` weighted at twenty-five percent, the
    parity-health figure weighted at twenty percent, and the supplier's
    `conversion_index` weighted at fifteen percent".

    Design: Corner/calculations/ranking_pool_excludes_offers_that_are_not_live
    """
    ctx = hotel_agency_offer(b)
    air = certified_air(b, ctx.market)
    b.agreement(air.supplier["id"], model="MERCHANT")
    air_plan = b.rate_plan(air.supplier["id"], ctx.market["id"], tax_fee_pct=0.05)
    pending = b.offer(air_plan["id"], travel_date=ctx.travel_date, net_rate_cents=119936)
    assert pending["status"] == "PENDING"

    run = b.ranking_run(ctx.market["id"], travel_date=ctx.travel_date)

    assert run["entry_count"] == 1
    assert run["paid_entry_count"] == 0
    assert set(run["weights_snapshot"]) == {"price", "content", "parity", "conversion"}

    entries = b.ranking_entries(run["id"])
    assert [entry["offer_id"] for entry in entries] == [ctx.offer["id"]]
    entry = entries[0]
    assert_score(entry["price_competitiveness"], 100.00)
    assert_score(entry["organic_score"], 89.50)
    assert entry["boost_points_applied"] == 0
    assert_score(entry["final_score"], 89.50)
    assert entry["rank_position"] == 1
    assert entry["is_paid_placement"] is False
    assert entry["disclosure_label"] == "ORGANIC"

    _rows, meta = validate_paginated(
        client.list_ranking_entries(PLATFORM_ADMIN, params={"offer_id": pending["id"]})
    )
    assert meta["total_count"] == 0


def _paid_run(b, *, boost_points: int, disclosure: bool = True):
    """A DRAFT run over one LIVE offer that is boosted by an ACTIVE placement deal."""
    ctx = hotel_agency_offer(b)
    ctx["placement"] = b.placement(
        ctx.supplier["id"],
        ctx.market["id"],
        slots=2,
        boost_points=boost_points,
        disclosure_label="SPONSORED",
        window_start="2026-09-01",
        window_end="2026-09-21",
    )
    overrides = {} if disclosure else {"disclosure_version": f._OMIT}
    ctx["run"] = b.ranking_run(
        ctx.market["id"], travel_date=ctx.travel_date, **overrides
    )
    return ctx


def test_a_ranking_entry_read_exposes_the_paid_boost_and_its_disclosure_label(b, client):
    """The boosted row carries the winning deal, its points and its label.

    PRD 3.6: "when `boost_points_applied` is greater than zero the entry's
    `placement_agreement_id` is set to that winning agreement's `id`,
    `is_paid_placement` is true, and `disclosure_label` is copied from the winning
    agreement" and "`final_score` is `organic_score` plus `boost_points_applied`".

    Design: Corner/endpoints/ranking_entry_read_exposes_the_paid_placement_boost_and_disclosure
    """
    ctx = _paid_run(b, boost_points=6)

    rows, meta = validate_paginated(
        client.list_ranking_entries(
            COMPLIANCE_OFFICER,
            params={"ranking_run_id": ctx.run["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 1
    entry = rows[0]
    assert entry["offer_id"] == ctx.offer["id"]
    assert entry["placement_agreement_id"] == ctx.placement["id"]
    assert_score(entry["price_competitiveness"], 100.00)
    assert_score(entry["organic_score"], 89.50)
    assert entry["boost_points_applied"] == 6
    assert_score(entry["final_score"], 95.50)
    assert entry["rank_position"] == 1
    assert entry["is_paid_placement"] is True
    assert entry["disclosure_label"] == "SPONSORED"

    run = b.read_ranking_run(ctx.run["id"])
    assert run["entry_count"] == 1
    assert run["paid_entry_count"] == 1
    assert run["status"] == "DRAFT"


def test_publishing_a_ranking_run_stamps_its_publication_metadata(b, client):
    """Publication records when and by whom, and leaves the frozen counts alone.

    PRD 3.6: publication moves the run "`DRAFT → PUBLISHED` and stamping
    `published_at` from the logical clock and `published_by_user_id` from
    `X-User-ID`".

    Design: Corner/endpoints/ranking_run_publish_stamps_publication_metadata
    """
    ctx = _paid_run(b, boost_points=6)

    published = validate_success(
        client.publish_ranking_run(
            ctx.run["id"], {"note": "criteria disclosure v1 attached"}, COMPLIANCE_OFFICER
        )
    )

    assert published["status"] == "PUBLISHED"
    assert_instant_equals(published["published_at"], DEFAULT_INSTANT)
    assert published["published_by_user_id"] == COMPLIANCE_OFFICER_USER_ID
    assert published["entry_count"] == 1
    assert published["paid_entry_count"] == 1


def test_a_ranking_run_with_no_live_offer_is_rejected(b, client):
    """An empty candidate pool kills the whole run, entries and all.

    PRD 3.6: "If the resulting pool is empty, the whole run is rejected with
    `ERR_NO_ELIGIBLE_OFFERS`."

    Design: Corner/errors/ranking_run_with_no_live_offer_is_rejected
    """
    ctx = hotel_agency_offer(b, publish=False)
    assert ctx.offer["status"] == "PENDING"

    refused = client.create_ranking_run(
        f.ranking_run_payload(ctx.market["id"], ctx.travel_date), COMMERCIAL_MANAGER
    )
    validate_error(refused, E.ERR_NO_ELIGIBLE_OFFERS, 422)

    _runs, run_meta = validate_paginated(client.list_ranking_runs(PLATFORM_ADMIN))
    assert run_meta["total_count"] == 0
    _entries, entry_meta = validate_paginated(
        client.list_ranking_entries(PLATFORM_ADMIN)
    )
    assert entry_meta["total_count"] == 0
    assert b.read_offer(ctx.offer["id"])["status"] == "PENDING"


def test_publishing_a_run_without_a_disclosure_version_is_rejected(b, client):
    """A market that demands disclosure blocks publication of an undocumented run.

    PRD 3.6: "when the market's `ranking_disclosure_required` is true the run's
    `disclosure_version` must be non-null, otherwise `ERR_DISCLOSURE_MISSING`".

    Design: Corner/errors/publishing_a_ranking_run_without_a_disclosure_version_is_rejected
    """
    ctx = hotel_agency_offer(b)
    assert ctx.market["ranking_disclosure_required"] is True
    run = b.ranking_run(
        ctx.market["id"], travel_date=ctx.travel_date, disclosure_version=f._OMIT
    )
    assert run["status"] == "DRAFT"
    assert run["entry_count"] == 1
    assert run["disclosure_version"] is None

    refused = client.publish_ranking_run(
        run["id"], {"note": "no criteria document attached"}, COMPLIANCE_OFFICER
    )
    validate_error(refused, E.ERR_DISCLOSURE_MISSING, 422)

    after = b.read_ranking_run(run["id"])
    assert after["status"] == "DRAFT"
    assert after["published_at"] is None
    assert after["published_by_user_id"] is None


def test_the_missing_disclosure_is_reported_before_the_cancelled_placement(b, client):
    """With both faults present the disclosure gate is the one that reports.

    PRD 3.6: "Two further conditions apply, in this order: when the market's
    `ranking_disclosure_required` is true the run's `disclosure_version` must be
    non-null, otherwise `ERR_DISCLOSURE_MISSING`; and every entry with
    `is_paid_placement` true must reference a placement agreement whose `status` is
    still `ACTIVE`, otherwise `ERR_PLACEMENT_NOT_ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_ranking_publish_missing_disclosure_with_cancelled_placement
    """
    ctx = _paid_run(b, boost_points=8, disclosure=False)
    assert ctx.run["paid_entry_count"] == 1
    assert ctx.run["disclosure_version"] is None

    cancelled = validate_success(
        client.cancel_placement_agreement(
            ctx.placement["id"],
            {"cancellation_reason": "Supplier withdrew from the programme."},
            COMMERCIAL_MANAGER,
        )
    )
    assert cancelled["status"] == "CANCELLED"

    refused = client.publish_ranking_run(ctx.run["id"], {}, COMPLIANCE_OFFICER)
    body = validate_error(refused, E.ERR_DISCLOSURE_MISSING, 422)
    assert body["error_id"] != E.ERR_PLACEMENT_NOT_ACTIVE

    after = b.read_ranking_run(ctx.run["id"])
    assert after["status"] == "DRAFT"
    assert after["published_at"] is None


def test_a_cancelled_placement_still_blocks_a_fully_disclosed_run(b, client):
    """Once the disclosure is present the stale paid entry becomes the reported fault.

    PRD 3.6: "every entry with `is_paid_placement` true must reference a placement
    agreement whose `status` is still `ACTIVE`, otherwise
    `ERR_PLACEMENT_NOT_ACTIVE`. That second condition is the reason a cancelled
    placement deal is fatal to an unpublished run even though it never rewrites the
    frozen entry."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_ranking_publish_missing_disclosure_with_cancelled_placement
    """
    ctx = _paid_run(b, boost_points=8, disclosure=True)
    assert ctx.run["disclosure_version"] is not None
    assert ctx.run["paid_entry_count"] == 1

    validate_success(
        client.cancel_placement_agreement(
            ctx.placement["id"],
            {"cancellation_reason": "Supplier withdrew from the programme."},
            COMMERCIAL_MANAGER,
        )
    )

    refused = client.publish_ranking_run(ctx.run["id"], {}, COMPLIANCE_OFFICER)
    validate_error(refused, E.ERR_PLACEMENT_NOT_ACTIVE, 422)

    entry = b.ranking_entries(ctx.run["id"])[0]
    assert entry["boost_points_applied"] == 8
    assert entry["disclosure_label"] == "SPONSORED"
    assert b.read_ranking_run(ctx.run["id"])["status"] == "DRAFT"
