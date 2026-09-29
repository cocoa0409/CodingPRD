"""The five ordered steps of the feed service fee, and the two independent tier
selections that compose inside them."""
import pytest

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers.api_client import api_client
from test_helpers.assertions import assert_retailer, assert_slot_ledger, assert_syndication_job
from test_helpers.fixtures import queue_job
from test_helpers.test_users import make_shelf_admin_headers, make_syndication_operator_headers


def test_rush_surcharge_tier_is_keyed_on_the_discounted_amount(bigbox_world):
    """Ten slots subtotal 25000 cents and take the 15 percent volume tier down to
    21250, which is at or above 20000 and therefore carries the 12 percent rush
    surcharge: 21250 + 2550 == 23800.  A rush tier keyed on the post-surcharge
    total would have taken 20 percent and produced 25500.

    PRD 3.6: "The surcharge tier is keyed on the **discounted amount before any surcharge**, never on the final total — keying it on the total would be circular, because the surcharge itself can push the total across the 20000-cent boundary."
    Design: Difficulty/combinatorial_formula/service_fee_rush_tier_keyed_on_discounted_not_on_total
    """
    job = queue_job(
        bigbox_world["listing"]["id"],
        bigbox_world["revision"]["id"],
        10,
        "2026-08-10T12:00:00Z",
        "2026-08-11T00:00:00Z",
        bigbox_world["retailer"]["id"],
    )
    assert_syndication_job(job)
    assert job["service_fee_cents"] == 23800
    assert job["service_fee_cents"] != 25500


def test_queueing_grows_the_slot_ledger_and_bumps_the_retailer_version(bigbox_world):
    """The ten reserved slots take the BigBox ledger from 0 to 10 against a capacity
    of 10, and the retailer row advances from version 1 to version 2.

    PRD 3.6: "On success, the retailer's `feed_slots_reserved` grows by the job's `slot_count` and the retailer's `version` increments by 1."
    Design: Difficulty/combinatorial_formula/service_fee_rush_tier_keyed_on_discounted_not_on_total
    """
    assert bigbox_world["retailer"]["feed_slots_reserved"] == 0
    assert bigbox_world["retailer"]["version"] == 1

    queue_job(
        bigbox_world["listing"]["id"],
        bigbox_world["revision"]["id"],
        10,
        "2026-08-10T12:00:00Z",
        "2026-08-11T00:00:00Z",
        bigbox_world["retailer"]["id"],
    )

    retailer = validate_success(
        api_client.get_retailer(bigbox_world["retailer"]["id"], make_shelf_admin_headers())
    )
    assert_retailer(retailer)
    assert_slot_ledger(retailer, 10)
    assert retailer["version"] == 2


def test_a_fresh_job_freezes_its_readiness_and_drives_the_listing_pending(bigbox_world):
    """The job opens QUEUED at attempt_no 1 with both timestamps still null, freezes
    the listing's 51.00 readiness onto itself, and moves the listing off
    NOT_SYNDICATED.

    PRD 3.6: "The new job begins in `state` `QUEUED` with `attempt_no` 1, `transmitted_at` and `responded_at` both null, and it drives the target listing's `syndication_state` from `NOT_SYNDICATED` to `PENDING`."
    Design: Difficulty/combinatorial_formula/service_fee_rush_tier_keyed_on_discounted_not_on_total
    """
    job = queue_job(
        bigbox_world["listing"]["id"],
        bigbox_world["revision"]["id"],
        10,
        "2026-08-10T12:00:00Z",
        "2026-08-11T00:00:00Z",
        bigbox_world["retailer"]["id"],
    )
    assert job["state"] == "QUEUED"
    assert job["attempt_no"] == 1
    assert job["transmitted_at"] is None
    assert job["responded_at"] is None
    assert float(job["readiness_at_queue"]) == pytest.approx(51.00, abs=0.01)

    listing = validate_success(
        api_client.get_retailer_listing(bigbox_world["listing"]["id"], make_shelf_admin_headers())
    )
    assert listing["syndication_state"] == "PENDING"


def test_volume_discount_applies_at_the_inclusive_lower_edge_of_its_tier(bigbox_world):
    """Two slots subtotal exactly 5000 cents, which is the inclusive lower edge of
    the 5 percent tier, so the fee is 4750 rather than the undiscounted 5000.

    PRD 3.6: "Second, a volume discount percentage is selected **from that subtotal**: no discount when the subtotal is below 5000 cents, 5 percent when the subtotal is at least 5000 and below 15000 cents, 10 percent when it is at least 15000 and below 25000 cents, and 15 percent when it is 25000 cents or more."
    Design: Difficulty/combinatorial_formula/service_fee_no_rush_at_inclusive_lower_discount_boundary
    """
    job = queue_job(
        bigbox_world["listing"]["id"],
        bigbox_world["revision"]["id"],
        2,
        "2026-08-15T00:00:00Z",
        "2026-08-16T00:00:00Z",
        bigbox_world["retailer"]["id"],
    )
    assert job["service_fee_cents"] == 4750
    assert job["service_fee_cents"] != 5000


def test_a_window_five_days_out_collapses_the_rush_dimension(bigbox_world):
    """With window_start five days after the clock the gap is far beyond 24 hours,
    so no surcharge is added on top of the 4750 discounted amount and the ledger
    still records the two slots against version 2.

    PRD 3.6: "Fourth, a rush surcharge percentage is selected: the transmission counts as **rush** when the gap between `window_start` and the logical clock's current instant is strictly less than 24 hours; a non-rush transmission carries no surcharge, a rush transmission carries 20 percent when the discounted amount is below 20000 cents, and a rush transmission carries 12 percent when the discounted amount is 20000 cents or more."
    Design: Difficulty/combinatorial_formula/service_fee_no_rush_at_inclusive_lower_discount_boundary
    """
    job = queue_job(
        bigbox_world["listing"]["id"],
        bigbox_world["revision"]["id"],
        2,
        "2026-08-15T00:00:00Z",
        "2026-08-16T00:00:00Z",
        bigbox_world["retailer"]["id"],
    )
    assert job["service_fee_cents"] == 4750
    assert float(job["readiness_at_queue"]) == pytest.approx(51.00, abs=0.01)

    retailer = get_success_data(
        api_client.get_retailer(
            bigbox_world["retailer"]["id"], make_syndication_operator_headers()
        )
    )
    assert_slot_ledger(retailer, 2)
    assert retailer["version"] == 2
