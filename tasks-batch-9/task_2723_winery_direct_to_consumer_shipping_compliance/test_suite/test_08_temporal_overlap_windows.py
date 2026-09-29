"""Temporal exclusivity windows of the Winery DTC Shipping Compliance API.

Three temporal resources with three different exclusivity conventions:

* a `StatePermit` period is a **closed** interval, so a shared endpoint date is an
  overlap and the filing is refused;
* a `TaxRemittance` period is **half-open**, so the very adjacency that collides
  for a permit is legal, and exclusivity is scoped by winery, state, period type
  and basis; and
* a weather hold is guarded by a minimum *gap* rather than a non-overlap: the new
  `hold_start_date` must fall on or after `last_hold_release_date` plus 3 days.

Every expectation below is quoted from PRD.md and nothing else.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.api_client import DtcApiClient  # noqa: F401  (client under test)
from test_helpers.assertions import (
    assert_cents,
    assert_liters,
)
from test_helpers.fixtures import (
    build_club_landscape,
    build_landscape,
    build_landscape_without_permit,
    create_permit,
)
from test_helpers.test_users import OFFICER_A


# ---------------------------------------------------------------------------
# Instance 1: the permit's closed interval treats a shared endpoint as overlap
# ---------------------------------------------------------------------------
def _winery_holding_a_pending_first_half_permit(api):
    """Winery Estate 1 with one `PENDING` TX permit covering 2026-01-01..2026-06-30.

    Exclusivity applies to every non-revoked status, so a `PENDING` incumbent is
    enough to block a colliding filing.  The clock sits at its 2026-08-01 default.
    """
    scape = build_landscape_without_permit(api)
    p1 = create_permit(
        api,
        scape.winery_id,
        permit_number="TX-DTC-A",
        effective_date="2026-01-01",
        expiration_date="2026-06-30",
    )
    assert p1["status"] == "PENDING"
    return scape, p1


def test_permit_sharing_an_endpoint_date_is_refused_as_an_overlap(api):
    """2026-06-30 belongs to the incumbent's closed interval, so it collides.

    "Those two dates form a **closed interval** — both endpoints are inside the
    permit's authority." (PRD 3.2)

    "Sharing a single endpoint date already counts as an overlap: a new permit whose
    `effective_date` falls exactly on an existing permit's `expiration_date`
    collides, and the filing is refused with `ERR_PERMIT_PERIOD_OVERLAP` (HTTP
    409)." (PRD 3.2)

    Design: Difficulty/resource_temporal_overlap/permit_closed_interval_treats_a_shared_endpoint_as_overlap
    """
    scape, p1 = _winery_holding_a_pending_first_half_permit(api)

    validate_error(
        api.create_state_permit(
            f.state_permit_payload(
                scape.winery_id,
                permit_number="TX-DTC-B",
                effective_date="2026-06-30",
                expiration_date="2026-12-31",
            ),
            OFFICER_A,
        ),
        "ERR_PERMIT_PERIOD_OVERLAP",
        409,
    )

    _rows, meta = validate_paginated(
        api.list_state_permits(OFFICER_A, {"limit": 100})
    )
    assert meta["total_count"] == 1, (
        f"The refused filing must persist nothing, got {meta['total_count']} permits"
    )
    assert scape.read_permit(p1["id"])["status"] == "PENDING"


def test_permit_starting_one_day_after_the_incumbent_expiry_is_accepted(api):
    """One day of separation leaves the closed intervals disjoint.

    "Because two overlapping licences for the same state would make it ambiguous
    which one authorized a shipment, a new permit's closed interval must not overlap
    the closed interval of any non-revoked permit the same winery already holds for
    the same state." (PRD 3.2)

    "A filed permit opens in `PENDING`, and a `PENDING` permit authorizes nothing."
    (PRD 3.2)

    Design: Difficulty/resource_temporal_overlap/permit_closed_interval_treats_a_shared_endpoint_as_overlap
    """
    scape, _p1 = _winery_holding_a_pending_first_half_permit(api)

    p3 = create_permit(
        api,
        scape.winery_id,
        permit_number="TX-DTC-C",
        effective_date="2026-07-01",
        expiration_date="2026-12-31",
    )

    assert p3["effective_date"] == "2026-07-01"
    assert p3["expiration_date"] == "2026-12-31"
    assert p3["status"] == "PENDING"
    assert p3["state_code"] == "TX"

    _rows, meta = validate_paginated(
        api.list_state_permits(OFFICER_A, {"limit": 100})
    )
    assert meta["total_count"] == 2, (
        f"Expected exactly two stored permits, got {meta['total_count']}"
    )


def test_revoking_the_incumbent_frees_its_exact_interval_for_re_issue(api):
    """A revoked licence is dropped from the comparison, so the interval reopens.

    "Revoked permits are excluded from this comparison, so a revoked licence never
    blocks a replacement." (PRD 3.2)

    "The request supplies a `revocation_reason`, which is recorded on the row
    alongside the new `REVOKED` status." (PRD 3.2)

    Design: Difficulty/resource_temporal_overlap/permit_closed_interval_treats_a_shared_endpoint_as_overlap
    """
    scape, p1 = _winery_holding_a_pending_first_half_permit(api)
    create_permit(
        api,
        scape.winery_id,
        permit_number="TX-DTC-C",
        effective_date="2026-07-01",
        expiration_date="2026-12-31",
    )

    revoked = scape.revoke_permit(p1["id"])
    assert revoked["status"] == "REVOKED"

    p4 = create_permit(
        api,
        scape.winery_id,
        permit_number="TX-DTC-D",
        effective_date="2026-01-01",
        expiration_date="2026-06-30",
    )

    assert p4["effective_date"] == "2026-01-01"
    assert p4["expiration_date"] == "2026-06-30"
    assert p4["id"] != p1["id"], (
        "The re-issue must be a new row, not a resurrection of the revoked one"
    )
    assert p4["status"] == "PENDING"


def test_revoking_a_permit_with_no_dependants_moves_no_counter(api):
    """The three-tier cascade recomputes a count that is still zero here.

    "**Third**, because those subscriptions changed status, the winery's
    `suspended_subscription_count` is recomputed as the number of that winery's
    subscriptions now sitting in `SUSPENDED_COMPLIANCE`, and `Winery.version`
    increments by 1." (PRD 3.2)

    Design: Difficulty/resource_temporal_overlap/permit_closed_interval_treats_a_shared_endpoint_as_overlap
    """
    scape, p1 = _winery_holding_a_pending_first_half_permit(api)

    scape.revoke_permit(p1["id"])

    winery = scape.read_winery()
    assert winery["suspended_subscription_count"] == 0
    assert_cents(winery["excise_accrued_cents"], 0, "excise_accrued_cents")


# ---------------------------------------------------------------------------
# Instance 2: the remittance's half-open period allows adjacency
# ---------------------------------------------------------------------------
# Every period below must already have closed, because PRD 3.9 requires
# `period_end` to fall on or before the logical clock date.  The clock is
# therefore parked in January 2027 so that the July and August 2026 monthly
# windows and the 2026 annual window are all reportable.
REMITTANCE_CLOCK = "2027-01-15T00:00:00Z"


def _winery_holding_the_july_accrual_remittance(api):
    """Winery Estate 1 with one closed `MONTHLY` `ACCRUAL_BASIS` July 2026 period.

    No orders exist at all, so every period this winery can open is empty.
    """
    scape = build_landscape(
        api,
        clock=REMITTANCE_CLOCK,
        permit_overrides={"expiration_date": "2027-12-31"},
    )
    july = scape.open_remittance("TX", "2026-07-01", "2026-08-01")
    assert july["period_start"] == "2026-07-01"
    assert july["period_end"] == "2026-08-01"
    assert july["status"] == "OPEN"
    return scape, july


def test_remittance_beginning_exactly_on_the_previous_period_end_is_accepted(api):
    """Adjacency is legal because the interval is half-open at the top.

    "The interval is always **half-open**: `period_start` is inclusive and
    `period_end` is exclusive, so an order whose key date falls exactly on
    `period_end` belongs to the *next* period, not this one." (PRD 3.9)

    "Exact adjacency is explicitly allowed — a period beginning precisely on an
    existing period's `period_end` is accepted, which is the whole point of the
    half-open convention." (PRD 3.9)

    Design: Difficulty/resource_temporal_overlap/remittance_half_open_period_allows_adjacency_and_is_family_scoped
    """
    scape, july = _winery_holding_the_july_accrual_remittance(api)

    august = scape.open_remittance("TX", "2026-08-01", "2026-09-01")

    assert august["period_start"] == july["period_end"]
    assert august["period_start"] == "2026-08-01"
    assert august["period_end"] == "2026-09-01"
    assert august["period_type"] == "MONTHLY"
    assert august["basis"] == "ACCRUAL_BASIS"
    assert august["status"] == "OPEN"
    assert august["id"] != july["id"]


def test_identical_period_in_the_same_filing_family_is_refused(api):
    """A true overlap inside one (winery, state, period_type, basis) family.

    "A new remittance's half-open interval must not overlap the interval of any
    existing remittance for the same combination of `winery_id`, `state_code`,
    `period_type` **and** `basis` whose `status` is anything other than `AMENDED`; a
    collision is refused with `ERR_REMITTANCE_PERIOD_OVERLAP` (HTTP 409)." (PRD 3.9)

    Design: Difficulty/resource_temporal_overlap/remittance_half_open_period_allows_adjacency_and_is_family_scoped
    """
    scape, july = _winery_holding_the_july_accrual_remittance(api)
    scape.open_remittance("TX", "2026-08-01", "2026-09-01")

    validate_error(
        api.create_remittance(
            f.remittance_payload(
                scape.winery_id,
                "TX",
                "2026-07-01",
                "2026-08-01",
                period_type="MONTHLY",
                basis="ACCRUAL_BASIS",
            ),
            OFFICER_A,
        ),
        "ERR_REMITTANCE_PERIOD_OVERLAP",
        409,
    )

    _rows, meta = validate_paginated(
        api.list_remittances(
            OFFICER_A, {"winery_id": scape.winery_id, "state_code": "TX", "limit": 100}
        )
    )
    assert meta["total_count"] == 2, (
        f"The refused filing must persist nothing, got {meta['total_count']} rows"
    )
    assert scape.read_remittance(july["id"])["status"] == "OPEN"


def test_the_other_basis_is_a_separate_filing_family_over_the_same_window(api):
    """The same calendar window may be opened once on each basis.

    "Because the check is also scoped by `basis`, the two bases are separate filing
    families and the very same calendar period may legitimately be opened once on
    each." (PRD 3.9)

    Design: Difficulty/resource_temporal_overlap/remittance_half_open_period_allows_adjacency_and_is_family_scoped
    """
    scape, july = _winery_holding_the_july_accrual_remittance(api)

    july_delivery = scape.open_remittance(
        "TX", "2026-07-01", "2026-08-01", basis="DELIVERY_BASIS"
    )

    assert july_delivery["basis"] == "DELIVERY_BASIS"
    assert july_delivery["period_start"] == july["period_start"]
    assert july_delivery["period_end"] == july["period_end"]
    assert july_delivery["period_type"] == "MONTHLY"
    assert july_delivery["id"] != july["id"]


def test_an_annual_period_enclosing_the_monthly_ones_does_not_collide(api):
    """Exclusivity is scoped by `period_type`, so nesting is legal.

    "Because the check is scoped by `period_type`, a `MONTHLY` period nested inside
    an `ANNUAL` period never collides with it." (PRD 3.9)

    Design: Difficulty/resource_temporal_overlap/remittance_half_open_period_allows_adjacency_and_is_family_scoped
    """
    scape, _july = _winery_holding_the_july_accrual_remittance(api)
    scape.open_remittance("TX", "2026-08-01", "2026-09-01")
    scape.open_remittance("TX", "2026-07-01", "2026-08-01", basis="DELIVERY_BASIS")

    annual = scape.open_remittance(
        "TX", "2026-01-01", "2027-01-01", period_type="ANNUAL"
    )

    assert annual["period_type"] == "ANNUAL"
    assert annual["period_start"] == "2026-01-01"
    assert annual["period_end"] == "2027-01-01"
    assert annual["basis"] == "ACCRUAL_BASIS"
    assert annual["status"] == "OPEN"

    _rows, meta = validate_paginated(
        api.list_remittances(
            OFFICER_A, {"winery_id": scape.winery_id, "state_code": "TX", "limit": 100}
        )
    )
    assert meta["total_count"] == 4, (
        f"Expected four coexisting periods, got {meta['total_count']}"
    )


def test_every_coexisting_period_is_an_empty_period_computed_from_no_orders(api):
    """With no orders in the landscape every period's figures are zero.

    "From the selected set the remittance records: `excise_accrued_cents`, the sum of
    `excise_tax_cents` across the selected orders; `sales_tax_accrued_cents`, the sum
    of their `sales_tax_cents`; `excise_reversed_cents` and
    `sales_tax_reversed_cents`, the same two sums restricted to those selected orders
    whose `returned_at` is non-null and falls **strictly before** `period_end`;
    `excise_due_cents`, the accrued excise less the reversed excise;
    `sales_tax_due_cents`, the accrued sales tax less the reversed sales tax;
    `liters_total`, the sum of the selected orders' `total_liters` rounded half up to
    three decimal places; `shipment_count`, the count of selected orders; and
    `included_order_ids`, the identifiers of the selected orders ordered by
    `cleared_at` ascending and then by `created_at` ascending." (PRD 3.9)

    Design: Difficulty/resource_temporal_overlap/remittance_half_open_period_allows_adjacency_and_is_family_scoped
    """
    scape, july = _winery_holding_the_july_accrual_remittance(api)
    august = scape.open_remittance("TX", "2026-08-01", "2026-09-01")
    july_delivery = scape.open_remittance(
        "TX", "2026-07-01", "2026-08-01", basis="DELIVERY_BASIS"
    )
    annual = scape.open_remittance(
        "TX", "2026-01-01", "2027-01-01", period_type="ANNUAL"
    )

    for remittance in (july, august, july_delivery, annual):
        row = scape.read_remittance(remittance["id"])
        assert row["status"] == "OPEN"
        assert row["shipment_count"] == 0
        assert_cents(row["excise_accrued_cents"], 0, "excise_accrued_cents")
        assert_cents(row["sales_tax_accrued_cents"], 0, "sales_tax_accrued_cents")
        assert_cents(row["excise_reversed_cents"], 0, "excise_reversed_cents")
        assert_cents(row["sales_tax_reversed_cents"], 0, "sales_tax_reversed_cents")
        assert_cents(row["excise_due_cents"], 0, "excise_due_cents")
        assert_cents(row["sales_tax_due_cents"], 0, "sales_tax_due_cents")
        assert_liters(row["liters_total"], 0.000, "liters_total")
        assert row["included_order_ids"] == []


# ---------------------------------------------------------------------------
# Instance 3: the weather hold's three-day buffer from the last release
# ---------------------------------------------------------------------------
def _subscription_released_from_a_first_hold(api):
    """An `ACTIVE` subscription whose `last_hold_release_date` is 2026-08-05.

    A first hold ran 2026-08-02 to 2026-08-05 and was released by hand, so the
    release copied 2026-08-05 into `last_hold_release_date` and the earliest legal
    next `hold_start_date` is 2026-08-08.  The clock sits at 2026-08-01 and the
    subscription's `next_run_date` is 2026-08-20.
    """
    scape, subscription = build_club_landscape(api)
    held = get_success_data(
        api.place_weather_hold(
            subscription["id"],
            f.weather_hold_payload("2026-08-02", "2026-08-05", "WEATHER_HEAT"),
            scape.operator,
        )
    )
    assert held["status"] == "WEATHER_HELD"
    released = get_success_data(
        api.release_hold(subscription["id"], f.release_hold_payload(), scape.operator)
    )
    return scape, released


def test_the_release_seeds_the_buffer_and_clears_the_hold_fields(api):
    """The buffer is measured from the release, which is where it is recorded.

    "Releasing a `WEATHER_HELD` subscription early — a `WEATHER_HELD` → `ACTIVE`
    move available to a `WineryOperator` or a `ComplianceOfficer` — copies the
    current `hold_release_date` into `last_hold_release_date` and then clears
    `hold_start_date`, `hold_release_date` and `hold_reason` back to null; the
    optional `reset_missed_runs` flag, when true, additionally puts
    `missed_run_count` back to 0." (PRD 3.8)

    Design: Difficulty/resource_temporal_overlap/weather_hold_three_day_buffer_measured_from_the_last_release
    """
    scape, released = _subscription_released_from_a_first_hold(api)

    assert released["status"] == "ACTIVE"
    assert released["last_hold_release_date"] == "2026-08-05"
    assert released["hold_start_date"] is None
    assert released["hold_release_date"] is None
    assert released["hold_reason"] is None
    assert released["next_run_date"] == "2026-08-20"
    assert scape.read_subscription(released["id"])["status"] == "ACTIVE"


def test_hold_one_day_short_of_the_three_day_buffer_is_refused(api):
    """2026-08-07 falls before 2026-08-05 plus three days, so the gap is too small.

    "And when the subscription already carries a `last_hold_release_date` from a
    previous hold, the new `hold_start_date` must fall on or after that date plus 3
    days, so a club cannot chain back-to-back holds to stall a member's allotment
    indefinitely; when `last_hold_release_date` is null no spacing constraint
    applies." (PRD 3.8)

    "Either violation is refused with `ERR_HOLD_WINDOW_CONFLICT` (HTTP 409)."
    (PRD 3.8)

    Design: Difficulty/resource_temporal_overlap/weather_hold_three_day_buffer_measured_from_the_last_release
    """
    scape, released = _subscription_released_from_a_first_hold(api)

    validate_error(
        api.place_weather_hold(
            released["id"],
            f.weather_hold_payload("2026-08-07", "2026-08-11", "WEATHER_FREEZE"),
            scape.operator,
        ),
        "ERR_HOLD_WINDOW_CONFLICT",
        409,
    )

    unchanged = scape.read_subscription(released["id"])
    assert unchanged["status"] == "ACTIVE"
    assert unchanged["hold_start_date"] is None
    assert unchanged["hold_release_date"] is None
    assert unchanged["hold_reason"] is None
    assert unchanged["last_hold_release_date"] == "2026-08-05"


def test_a_zero_length_hold_window_is_refused(api):
    """`hold_release_date` equal to `hold_start_date` is meaningless.

    "The `hold_release_date` must be strictly after the `hold_start_date` — a
    zero-length or inverted hold is meaningless." (PRD 3.8)

    "Either violation is refused with `ERR_HOLD_WINDOW_CONFLICT` (HTTP 409)."
    (PRD 3.8)

    Design: Difficulty/resource_temporal_overlap/weather_hold_three_day_buffer_measured_from_the_last_release
    """
    scape, released = _subscription_released_from_a_first_hold(api)

    validate_error(
        api.place_weather_hold(
            released["id"],
            f.weather_hold_payload("2026-08-08", "2026-08-08", "WEATHER_FREEZE"),
            scape.operator,
        ),
        "ERR_HOLD_WINDOW_CONFLICT",
        409,
    )

    assert scape.read_subscription(released["id"])["status"] == "ACTIVE"


def test_hold_starting_exactly_on_the_buffer_boundary_is_accepted(api):
    """2026-08-08 is exactly 2026-08-05 plus three days, and on-or-after clears.

    "Placing a **weather hold** moves an `ACTIVE` subscription to `WEATHER_HELD` and
    records three fields from the request: `hold_start_date`, `hold_release_date` and
    a `hold_reason` of `WEATHER_HEAT`, `WEATHER_FREEZE` or `CONSUMER_REQUEST`."
    (PRD 3.8)

    "Placing a hold deliberately leaves `next_run_date` untouched — it is the run
    itself, not the hold, that defers the schedule." (PRD 3.8)

    Design: Difficulty/resource_temporal_overlap/weather_hold_three_day_buffer_measured_from_the_last_release
    """
    scape, released = _subscription_released_from_a_first_hold(api)

    held = get_success_data(
        api.place_weather_hold(
            released["id"],
            f.weather_hold_payload("2026-08-08", "2026-08-12", "WEATHER_FREEZE"),
            scape.operator,
        ),
        200,
    )

    assert held["status"] == "WEATHER_HELD"
    assert held["hold_start_date"] == "2026-08-08"
    assert held["hold_release_date"] == "2026-08-12"
    assert held["hold_reason"] == "WEATHER_FREEZE"
    # The buffer field only advances on release, never on a hold.
    assert held["last_hold_release_date"] == "2026-08-05"
    assert held["next_run_date"] == "2026-08-20"
    assert held["missed_run_count"] == 0
    assert held["consumed_shipments"] == 0
