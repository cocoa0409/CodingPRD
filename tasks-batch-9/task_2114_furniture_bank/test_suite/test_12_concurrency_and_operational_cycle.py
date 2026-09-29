"""Optimistic concurrency on repeatable writes, and the operational cycle."""

from test_helpers import (
    ADMIN,
    DISPATCH,
    WAREHOUSE,
    ApiErrorId,
    allocate_payload,
    book_stop,
    create_run,
    delivery_stop_payload,
    donation_item_payload,
    get_run,
    list_inventory,
    list_waitlist,
    record_outcome,
    run_cycle,
    set_clock,
    setup_allocated_voucher,
    setup_dispatched_run,
    setup_issued_voucher,
    validate_error,
    validate_success,
    voucher_line_payload,
)


# ─── Corner: optimistic concurrency ────────────────────────────────────

def test_replaying_a_spent_voucher_version_on_allocate_is_refused(api):
    """PRD §2.8: "A `POST /vouchers/{id}/allocate` request must carry
    `expected_voucher_version` as a required, non-optional input field, holding
    the `version` of the target `Voucher` as the client last observed it. If
    that value does not equal the voucher's current `version`, the allocation
    round is rejected with `ERR_STALE_VOUCHER_VERSION` (HTTP 412), so a
    warehouse lead cannot reserve stock against a picture of the voucher that
    another writer has already moved past."
    PRD §3.6: "It is deliberately repeatable — a top-up round against a
    half-filled voucher is a normal operation, not an error — which is exactly
    why the round carries `expected_voucher_version` and is rejected with
    `ERR_STALE_VOUCHER_VERSION` when that value does not match the voucher's
    live `version`."

    Design: Corner/cross_cutting_layers/corner_occ_stale_voucher_version_rejected_on_repeat_allocate
    """
    set_clock("2026-08-04T09:00:00Z")
    scenario = setup_issued_voucher(
        lines=[voucher_line_payload("BED", 1, "B")],
        agency_name="Yarrow Field Aid",
    )
    voucher_id = scenario["voucher"]["id"]
    first_version = scenario["voucher"]["version"]
    assert first_version == 1

    after_first = validate_success(
        api.allocate_voucher(voucher_id, allocate_payload(first_version), WAREHOUSE)
    )
    assert after_first["version"] == 2, "a zero-yield round still bumps the version"

    stale = api.allocate_voucher(
        voucher_id, allocate_payload(first_version), WAREHOUSE
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VOUCHER_VERSION.value, 412)

    fresh = validate_success(
        api.allocate_voucher(voucher_id, allocate_payload(2), WAREHOUSE)
    )
    assert fresh["version"] == 3, "the current version is accepted on its own merits"
    assert fresh["status"] == "ISSUED"

    entries = list_waitlist(client_id=scenario["client"]["id"], status="WAITING")
    assert len(entries) == 1, "the repeated rounds keep exactly one waiting entry"


def test_replaying_a_spent_run_version_on_stop_booking_is_refused(api):
    """PRD §2.8: "A `POST /delivery-runs/{id}/stops` request must carry
    `expected_run_version` as a required, non-optional input field, holding the
    `version` of the target `DeliveryRun` as the planner last observed it. If
    that value does not equal the run's current `version`, the booking is
    rejected with `ERR_STALE_RUN_VERSION` (HTTP 412), pinning the planner's view
    of the run's load and stop list to the one they actually read."
    PRD §2.9: "10. The supplied expected-version field equals the parent
    entity's current `version` — otherwise `ERR_STALE_VOUCHER_VERSION` or
    `ERR_STALE_RUN_VERSION` (412), on the allocation round and stop booking
    respectively."
    PRD §2.9: "11. The target resource is in a state that has an outgoing
    transition for this trigger — otherwise one of `ERR_REFERRAL_NOT_SUBMITTED`,
    `ERR_REFERRAL_NOT_APPROVED`, `ERR_VOUCHER_INVALID_STATE`,
    `ERR_FEE_STATE_INVALID`, `ERR_OFFER_INVALID_STATE`, `ERR_RUN_INVALID_STATE`,
    `ERR_STOP_INVALID_STATE` or `ERR_CREW_ASSIGNMENT_INVALID_STATE` (409).
    Applies to every action endpoint."

    Design: Corner/cross_cutting_layers/corner_occ_stale_run_version_rejected_on_second_stop_booking
    """
    set_clock("2026-08-04T09:00:00Z")
    scenario = setup_allocated_voucher(
        lines=[voucher_line_payload("BED", 1, "B")],
        offer_items=[donation_item_payload("BED", "B", False, 30.0)],
        truck_label="BOX-63", agency_name="Zephyr Court Services",
    )
    run = create_run(scenario["truck"]["id"], service_date="2026-08-05",
                     window_start="2026-08-05T09:00:00Z",
                     window_end="2026-08-05T17:00:00Z", county="CENTRAL")
    stale_version = run["version"]
    assert stale_version == 1

    book_stop(run["id"], scenario["voucher"]["id"], 1, stale_version)
    current_version = get_run(run["id"])["version"]
    assert current_version == 2, "booking a stop bumps the run's version"

    stale_booking = api.create_delivery_stop(
        run["id"],
        delivery_stop_payload(scenario["voucher"]["id"], 2, stale_version),
        DISPATCH,
    )
    validate_error(stale_booking, ApiErrorId.ERR_STALE_RUN_VERSION.value, 412)

    fresh_booking = api.create_delivery_stop(
        run["id"],
        delivery_stop_payload(scenario["voucher"]["id"], 2, current_version),
        DISPATCH,
    )
    validate_error(fresh_booking, ApiErrorId.ERR_VOUCHER_INVALID_STATE.value, 409)

    run_now = validate_success(api.get_delivery_run(run["id"], DISPATCH))
    assert run_now["stop_count"] == 1
    assert run_now["version"] == current_version, "neither refusal bumps the run"

    voucher_now = validate_success(api.get_voucher(scenario["voucher"]["id"], ADMIN))
    assert voucher_now["status"] == "SCHEDULED"


# ─── Corner: the operational cycle ─────────────────────────────────────

def test_operational_cycle_advances_the_quota_epoch_and_zeroes_usage(api):
    """PRD §2.6: "6. **Quota epoch advance.** Only when `advance_quota_epoch` is
    true, every agency's `quota_epoch` is incremented and its `quota_used` is
    reset to 0."
    PRD §2.6: "1. **Referral expiry.** Every `Referral` in status `APPROVED`
    whose `expires_at` is strictly earlier than now moves to `EXPIRED`."
    PRD §3.1: "The quota epoch counter is advanced only by the operational
    cycle, and only when that cycle is asked to do so; nothing else moves it."

    Design: Corner/cross_cutting_layers/corner_ops_run_cycle_advances_quota_epoch_and_zeroes_usage
    """
    set_clock("2026-08-04T09:00:00Z")
    scenario = setup_issued_voucher(
        lines=[voucher_line_payload("BED", 1, "B")], quota=3,
        agency_name="Ashgrove Mutual",
    )
    assert scenario["referral"]["approved_epoch"] == 1

    summary = run_cycle(advance_quota_epoch=True)

    assert summary["quota_epoch_advanced"] is True
    assert summary["expired_referral_count"] == 0, "the clock never moved past expiry"

    agency_now = validate_success(api.get_agency(scenario["agency"]["id"], ADMIN))
    assert agency_now["quota_epoch"] == 2
    assert agency_now["quota_used"] == 0
    assert agency_now["standing"] == "GOOD"

    referral_now = validate_success(api.get_referral(scenario["referral"]["id"], ADMIN))
    assert referral_now["status"] == "APPROVED", "a live referral is not expired"
    assert referral_now["approved_epoch"] == 1, (
        "the stamp on the referral records the epoch it was approved in"
    )


def test_operational_cycle_expires_the_voucher_and_releases_its_stock(api):
    """PRD §2.6: "2. **Voucher expiry.** The vouchers of those referrals expire
    and their reserved stock is released (detailed in §3.3 and §3.6)."
    PRD §3.3: "From `PARTIALLY_ALLOCATED → EXPIRED` and from `ALLOCATED →
    EXPIRED` the same line and waitlist effects apply, and in addition every
    reserved unit moves `RESERVED → AVAILABLE` with
    `reserved_for_voucher_line_id` cleared and `available_since` restamped to
    now."
    PRD §3.6: "They move `WAITING → EXPIRED` when the owning voucher expires in
    step 2 of the operational cycle's expiry pass."

    Design: Corner/cross_cutting_layers/corner_ops_run_cycle_expires_voucher_and_releases_reserved_stock
    """
    set_clock("2026-08-04T09:00:00Z")
    scenario = setup_allocated_voucher(
        lines=[voucher_line_payload("BED", 2, "B")],
        offer_items=[donation_item_payload("BED", "B", False, 30.0)],
        truck_label="BOX-64", quota=3,
        agency_name="Brackenridge Household Aid",
    )
    assert scenario["allocated"]["status"] == "PARTIALLY_ALLOCATED"
    entry = list_waitlist(client_id=scenario["client"]["id"], status="WAITING")[0]
    unit = list_inventory(donation_item_id=scenario["donation_items"][0]["id"])[0]

    set_clock("2026-09-19T09:00:00Z")
    summary = run_cycle(advance_quota_epoch=False)

    assert summary["expired_referral_count"] == 1
    assert summary["expired_voucher_count"] == 1
    assert summary["released_inventory_count"] == 1

    referral_now = validate_success(api.get_referral(scenario["referral"]["id"], ADMIN))
    assert referral_now["status"] == "EXPIRED"
    voucher_now = validate_success(api.get_voucher(scenario["voucher"]["id"], ADMIN))
    assert voucher_now["status"] == "EXPIRED"

    unit_now = validate_success(api.get_inventory_item(unit["id"], WAREHOUSE))
    assert unit_now["status"] == "AVAILABLE"
    assert unit_now["reserved_for_voucher_line_id"] is None
    assert unit_now["available_since"] == "2026-09-19T09:00:00.000Z"

    entry_now = validate_success(api.get_waitlist_entry(entry["id"], ADMIN))
    assert entry_now["status"] == "EXPIRED"

    agency_now = validate_success(api.get_agency(scenario["agency"]["id"], ADMIN))
    assert agency_now["quota_used"] == 0, "expiry returns the approval slot"


def test_operational_cycle_remediates_the_residence_then_reinstates_it(api):
    """PRD §2.6: "- **3a. Bed-bug remediation.** Every `Client` whose
    `bed_bug_status` is `CONFIRMED` and whose `bed_bug_confirmed_at` is at least
    60 days old moves to `bed_bug_status` `REMEDIATED`."
    PRD §2.6: "- **3b. Household reinstatement.** Every `Client` in status
    `ON_HOLD` whose `delivery_ban_until` is null or has already passed, and
    whose `bed_bug_status` is no longer `CONFIRMED`, returns to status `ACTIVE`
    with `no_show_strikes` reset to 0. Because 3a runs before 3b, a household
    remediated in this very cycle is reinstated in the same call."

    Design: Corner/cross_cutting_layers/corner_ops_run_cycle_remediates_bed_bug_then_reinstates_household
    """
    set_clock("2026-08-04T09:00:00Z")
    scenario = setup_allocated_voucher(
        lines=[voucher_line_payload("BED", 1, "B")],
        offer_items=[donation_item_payload("BED", "B", False, 30.0)],
        truck_label="BOX-65", agency_name="Coldharbour Family Aid",
    )
    booked = setup_dispatched_run(scenario["truck"]["id"], scenario["voucher"]["id"],
                                  county="CENTRAL", volunteer_name="Rune Halvorsen")
    outcome = record_outcome(booked["stop"]["id"], "REFUSED",
                             pest_observed_at_residence=True)
    assert outcome["chargeback_cents"] == 625

    before = validate_success(api.get_client(scenario["client"]["id"], ADMIN))
    assert before["bed_bug_confirmed_at"] == "2026-08-04T09:00:00.000Z"
    assert before["status"] == "ON_HOLD"

    set_clock("2026-10-03T09:00:00Z")
    summary = run_cycle(advance_quota_epoch=False)

    assert summary["reinstated_client_count"] == 1

    household = validate_success(api.get_client(scenario["client"]["id"], ADMIN))
    assert household["bed_bug_status"] == "REMEDIATED", (
        "exactly 60 days after confirmation the residence is remediated"
    )
    assert household["status"] == "ACTIVE", (
        "remediation runs before reinstatement inside the same call"
    )
    assert household["no_show_strikes"] == 0
    assert household["delivery_ban_until"] is None

    referral_now = validate_success(api.get_referral(scenario["referral"]["id"], ADMIN))
    assert referral_now["status"] == "EXPIRED"
    voucher_now = validate_success(api.get_voucher(scenario["voucher"]["id"], ADMIN))
    assert voucher_now["status"] == "EXPIRED"
