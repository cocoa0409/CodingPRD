"""
Layers that cut across every entity: optimistic concurrency on two different
parents, a threshold measured on a running aggregate, and three derived counters
that must stay reconciled through a sequence of adjudications.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CHARTERING_EXAMINER_HEADERS,
    COUNSEL_HEADERS,
    ESCROW_AGENT_HEADERS,
    fixtures as fx,
)
from test_helpers.assertions import assert_fields_equal, assert_two_decimal_places
from test_helpers.factories import (
    adjudication_payload,
    business_plan_payload,
    conversion_window_payload,
    subscription_payload,
)
from test_helpers.types import (
    BLOCKED_REASON_NONE,
    CATEGORY_MANAGEMENT,
    CATEGORY_VENDOR,
    CLEARANCE_CLEARED,
    COMPOSITION_MET,
    CONDITION_EVIDENCE_SUBMITTED,
    CONDITION_SATISFIED,
    CONDITION_WAIVED,
    DISPOSITION_SATISFIED,
    DISPOSITION_WAIVED,
    FILING_CONDITIONALLY_APPROVED,
    PLAN_DRAFT,
    RAISE_ESCROW_LOCKED,
    RAISE_OPEN,
    WINDOW_RESERVED,
)


# ---------------------------------------------------------------------------
# Corner / cross_cutting_complexity_layers
# ---------------------------------------------------------------------------
def test_a_plan_create_carrying_a_version_read_before_the_fifth_seat_is_refused(api):
    """
    The token is read while the board is four strong; seating and clearing a fifth organizer
    then moves the group on several times over, so the token a client still holds describes a
    file that no longer exists. The create is refused on the concurrency band alone — the
    thirteen projection figures are identical in both attempts, and the only difference between
    the refusal and the acceptance is the version field. The refusal writes nothing at all: no
    plan appears under the group and the group's own version has not moved either. Re-read and
    retried, the very same body is accepted as the first revision of the plan, with the stress
    roll-ups still empty because no overlay has been attached.

    PRD: "Creating a business plan — `POST /de-novo/business-plans` — requires `expected_group_version` in the request body, carrying the `version` the client last observed on the target `OrganizingGroup`."
    PRD: "If that value does not equal the group's current `version`, the create is rejected with `ERR_STALE_GROUP_VERSION` (HTTP 412) and nothing is written."
    PRD: "A new plan begins in `DRAFT` with `stress_scenario_count`, `breach_scenario_count` and `worst_governing_min_leverage_ratio_bps` all 0, and creating it increments the parent group's `version` by one."
    PRD: "`plan_revision_index` is 1 when `supersedes_plan_id` is omitted, and otherwise one more than the superseded plan's own `plan_revision_index`, so a chain of revisions is self-numbering."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_group_version_rejects_business_plan_create
    """
    world = fx.seated_group(api, seats=4, clear=True)
    stale_version = fx.group_version(api, world["group_id"])

    world["o5"] = fx.seat_organizer(api, world["group_id"], fx.CANONICAL_ORGANIZERS[4])
    fx.clear_background(api, world["o5"])
    fresh_version = fx.group_version(api, world["group_id"])
    assert stale_version < fresh_version, (
        f"seating and clearing the fifth organizer must move the group on: "
        f"{stale_version} then {fresh_version}"
    )

    validate_error(
        api.create_business_plan(
            business_plan_payload(world["group_id"], stale_version), COUNSEL_HEADERS
        ),
        "ERR_STALE_GROUP_VERSION",
        expected_status=412,
    )
    _, meta = validate_paginated(
        api.list_business_plans(COUNSEL_HEADERS, params={"group_id": world["group_id"]})
    )
    assert meta["total_count"] == 0, (
        f"a refused create writes no plan, found {meta['total_count']}"
    )
    assert_fields_equal(
        fx.read_group(api, world["group_id"]),
        version=fresh_version,
        composition_status=COMPOSITION_MET,
    )

    plan = get_success_data(
        api.create_business_plan(
            business_plan_payload(world["group_id"], fresh_version), COUNSEL_HEADERS
        ),
        expected_status=201,
    )
    assert_fields_equal(
        plan,
        status=PLAN_DRAFT,
        plan_revision_index=1,
        stress_scenario_count=0,
        worst_governing_min_leverage_ratio_bps=0,
    )
    group = fx.read_group(api, world["group_id"])
    assert_two_decimal_places(
        group["management_composite_score"], 71.80, "management_composite_score"
    )


def test_the_first_reservation_invalidates_the_token_a_second_reservation_replays(api):
    """
    Booking the first outage window bumps the contract, so a client replaying the token it read
    before that booking is describing a calendar one entry out of date. The refusal is the
    concurrency one and emphatically not the capacity one: a single overlapping occupant is
    perfectly acceptable against a ceiling of two, and the second booking would have been the
    legitimate second concurrent migration. Nothing is written — the occupancy count and the
    contract version are exactly where the first booking left them — and the same interval,
    re-requested with the current token, is accepted as a twenty-four hour slot that takes
    occupancy to two while leaving the first booking untouched.

    PRD: "Reserving a core-conversion window — `POST /de-novo/conversion-windows` — requires `expected_vendor_contract_version` in the request body, carrying the `version` the client last observed on the target `VendorContract`."
    PRD: "If that value does not equal the contract's current `version`, the reservation is rejected with `ERR_STALE_VENDOR_CONTRACT_VERSION` (HTTP 412) and nothing is written."
    PRD: "The reservation is refused with `ERR_CONVERSION_CAPACITY_EXCEEDED` when the number of overlapping occupants is 2 or more; one overlapping occupant is therefore accepted and becomes the second concurrent window, and a third simultaneous booking is the one that fails."
    PRD: "On success the window begins in `RESERVED`, the contract's `active_window_count` is recomputed as the number of its `RESERVED` or `CONFIRMED` windows — counting all occupants, not merely the overlapping ones — and the contract's `version` increments by one."
    PRD: "Checks are therefore evaluated in a fixed ladder of bands, and the first failing check in the earliest band wins; later bands are not evaluated at all."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_vendor_contract_version_rejects_window_reserve
    """
    world = fx.open_group(api)
    contract_id = fx.signed_core_vendor(api, world)
    version_before_any_booking = fx.contract_version(api, contract_id)

    first_window = fx.reserve_window(
        api, contract_id, "2026-09-02T00:00:00Z", "2026-09-03T00:00:00Z"
    )
    version_after_first = fx.contract_version(api, contract_id)
    assert_fields_equal(fx.read_contract(api, contract_id), active_window_count=1)
    assert version_after_first > version_before_any_booking, (
        "reserving the first window must bump the contract that carries the calendar"
    )

    error = validate_error(
        api.create_conversion_window(
            conversion_window_payload(
                contract_id,
                version_before_any_booking,
                "2026-09-02T12:00:00Z",
                "2026-09-03T12:00:00Z",
            ),
            COUNSEL_HEADERS,
        ),
        "ERR_STALE_VENDOR_CONTRACT_VERSION",
        expected_status=412,
    )
    assert error["error_id"] != "ERR_CONVERSION_CAPACITY_EXCEEDED", (
        "one overlapping occupant is inside the ceiling of two, so capacity is not the problem"
    )
    assert_fields_equal(
        fx.read_contract(api, contract_id),
        active_window_count=1,
        version=version_after_first,
    )

    second_window = get_success_data(
        api.create_conversion_window(
            conversion_window_payload(
                contract_id,
                version_after_first,
                "2026-09-02T12:00:00Z",
                "2026-09-03T12:00:00Z",
            ),
            COUNSEL_HEADERS,
        ),
        expected_status=201,
    )
    assert_fields_equal(second_window, status=WINDOW_RESERVED)
    assert_two_decimal_places(second_window["duration_hours"], 24.00, "duration_hours")
    assert_fields_equal(fx.read_contract(api, contract_id), active_window_count=2)
    assert_fields_equal(fx.read_window(api, first_window), status=WINDOW_RESERVED)


def test_the_escrow_lock_trips_only_once_the_cleared_basis_reaches_the_minimum(api):
    """
    The threshold is measured on a running total rather than on anything in the request: the
    bodyless lock call is identical both times. With two billion cents cleared against a
    minimum of four point one billion the lock is refused and the offering stays open with its
    cleared basis untouched. One further subscription, funded and cleared, brings the total to
    exactly the minimum — not a cent above it — and the same call now commits the escrow. The
    waterfall is re-derived on the way through: the organizers' claim of a hundred and fifty
    million sits below the five percent ceiling of two hundred and five million, so it is
    reimbursed in full and the remainder is the net. Committing is not paying out, so the
    released figure is still zero.

    PRD: "Three gates apply in this order: the raise must be `OPEN` (`ERR_RAISE_NOT_LOCKABLE`); at least one subscription of the raise must have `counts_toward_escrow` true, so an empty cleared set cannot be locked even in the degenerate case where `minimum_gross_cents` happens to be zero (`ERR_NO_CLEARED_SUBSCRIPTIONS`); and `cleared_escrow_cents` must be at least `minimum_gross_cents`, measured on the cleared basis only — `pledged_gross_cents` is never accepted here (`ERR_ESCROW_BELOW_MINIMUM`)."
    PRD: "Locking re-derives the aggregates and the waterfall so `projected_reimbursement_cents` and `projected_net_release_cents` are current, and increments the raise's `version` by one."
    PRD: "Bucket one is the organizational-expense reimbursement, capped at five percent of that **gross** figure: five percent of gross cleared escrow is rounded half up to whole cents to form the cap, and `projected_reimbursement_cents` is the smaller of `organizational_expense_claim_cents` and that cap."
    PRD: "Bucket two is everything left over: `projected_net_release_cents` is the gross figure minus `projected_reimbursement_cents`, an exact subtraction, so gross always reconciles to reimbursement plus net."
    PRD: "A third field, the capital raise's `released_net_cents`, is a snapshot: it is 0 until escrow is released and thereafter holds the value `projected_net_release_cents` had at the instant of release."

    Design: Corner/cross_cutting_complexity_layers/escrow_lock_trips_only_at_the_exact_minimum_gross
    """
    world = fx.bare_open_raise(api)
    first = fx.add_subscription(api, world["raise_id"], "Harbor Trust LP", 2_000_000)
    fx.fund(api, first)
    fx.screen(api, first, CLEARANCE_CLEARED)
    assert_fields_equal(
        fx.read_raise(api, world["raise_id"]),
        minimum_gross_cents=4_100_000_000,
        cleared_escrow_cents=2_000_000_000,
    )

    validate_error(
        api.lock_escrow(world["raise_id"], ESCROW_AGENT_HEADERS),
        "ERR_ESCROW_BELOW_MINIMUM",
        expected_status=409,
    )
    assert_fields_equal(
        fx.read_raise(api, world["raise_id"]),
        status=RAISE_OPEN,
        cleared_escrow_cents=2_000_000_000,
    )

    second = get_success_data(
        api.create_subscription(
            subscription_payload(
                world["raise_id"],
                subscriber_name="Puget Founders Fund",
                shares=2_100_000,
            ),
            ESCROW_AGENT_HEADERS,
        ),
        expected_status=201,
    )["id"]
    fx.fund(api, second)
    fx.screen(api, second, CLEARANCE_CLEARED)
    assert_fields_equal(
        fx.read_raise(api, world["raise_id"]), cleared_escrow_cents=4_100_000_000
    )

    locked = validate_success(
        api.lock_escrow(world["raise_id"], ESCROW_AGENT_HEADERS), expected_status=200
    )
    assert_fields_equal(
        locked,
        status=RAISE_ESCROW_LOCKED,
        cleared_escrow_cents=4_100_000_000,
        projected_reimbursement_cents=150_000_000,
        projected_net_release_cents=3_950_000_000,
        released_net_cents=0,
    )
    assert_fields_equal(
        fx.read_group(api, world["group_id"]), opening_blocked_reason=BLOCKED_REASON_NONE
    )


def test_three_counters_stay_reconciled_through_a_waiver_and_a_satisfaction(api):
    """
    Two conditions hang off the chartering application: one blocking, one not. Waiving the
    non-blocking one settles it without touching the blocking counter, because a condition that
    was never a blocker cannot stop being one. Filing evidence on the blocker moves it sideways
    within the blocking set rather than out of it, so the blocking counter still stands at one
    while the settled count holds at one. Only the examiner's acceptance clears the blocker, and
    at that moment the settled count reaches both rows and clearance flips true. Throughout all
    three adjudications the total is conserved at two, since nothing but attaching a new
    condition may change it, and the filing itself never moves: no information round is
    consumed.

    PRD: "`condition_total_count` is the number of conditions attached to the filing in any status whatsoever."
    PRD: "`settled_condition_count` is the number whose `status` is `SATISFIED` or `WAIVED`."
    PRD: "`open_blocking_condition_count` is the number whose `is_pre_opening_blocking` is true **and** whose `status` is `OPEN`, `EVIDENCE_SUBMITTED` or `FAILED`; a non-blocking condition is counted in the total and, once settled, in the settled count, but it can never hold `open_blocking_condition_count` above zero no matter how long it stays open."
    PRD: "`pre_opening_clearance` is true exactly when the filing's own `status` is `CONDITIONALLY_APPROVED` or `FINAL_APPROVED` **and** `open_blocking_condition_count` is 0; a filing sitting in `FILED` with no conditions at all has zero open blockers and still has `pre_opening_clearance` false, because clearance is a statement about an approved filing, not about an empty condition list."
    PRD: "No adjudication of any kind ever changes `condition_total_count`; only attaching a new condition changes it."
    PRD: "`SATISFIED` is legal only from `EVIDENCE_SUBMITTED`: the examiner has reviewed the evidence and accepted it."
    PRD: "Note that `EVIDENCE_SUBMITTED` is itself a blocking status: submitting evidence does not reduce `open_blocking_condition_count`, it merely moves the condition sideways within the blocking set."

    Design: Corner/cross_cutting_complexity_layers/filing_counts_reconcile_across_waiver_then_satisfaction
    """
    world = fx.conditionally_approved_group(api)
    blocking = fx.add_condition(api, world["f_ca"], "VEN-01", CATEGORY_VENDOR, True)
    non_blocking = fx.add_condition(
        api, world["f_ca"], "MGMT-01", CATEGORY_MANAGEMENT, False
    )
    assert_fields_equal(
        fx.read_filing(api, world["f_ca"]),
        condition_total_count=2,
        settled_condition_count=0,
        open_blocking_condition_count=1,
        pre_opening_clearance=False,
    )

    waived = validate_success(
        api.adjudicate_condition(
            non_blocking,
            adjudication_payload(DISPOSITION_WAIVED),
            CHARTERING_EXAMINER_HEADERS,
        ),
        expected_status=200,
    )
    assert_fields_equal(waived, status=CONDITION_WAIVED, adjudication_count=1)
    assert_fields_equal(
        fx.read_filing(api, world["f_ca"]),
        condition_total_count=2,
        settled_condition_count=1,
        open_blocking_condition_count=1,
        pre_opening_clearance=False,
    )

    submitted = fx.submit_evidence(
        api, blocking, "DOC-VEN-CORE-CONTRACT-EXECUTED-001"
    )
    assert_fields_equal(submitted, status=CONDITION_EVIDENCE_SUBMITTED)
    assert_fields_equal(
        fx.read_filing(api, world["f_ca"]),
        open_blocking_condition_count=1,
        settled_condition_count=1,
    )

    satisfied = validate_success(
        api.adjudicate_condition(
            blocking,
            adjudication_payload(DISPOSITION_SATISFIED),
            CHARTERING_EXAMINER_HEADERS,
        ),
        expected_status=200,
    )
    assert_fields_equal(satisfied, status=CONDITION_SATISFIED, adjudication_count=1)
    assert_fields_equal(
        fx.read_filing(api, world["f_ca"]),
        condition_total_count=2,
        settled_condition_count=2,
        open_blocking_condition_count=0,
        pre_opening_clearance=True,
        status=FILING_CONDITIONALLY_APPROVED,
        info_request_round=0,
    )
