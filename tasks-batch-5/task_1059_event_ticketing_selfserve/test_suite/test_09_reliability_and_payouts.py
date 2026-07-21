"""Organiser reliability, the payout chain and the rolling reserve."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, TEST_USERS, FINANCE_USER_ID, FINANCE_USER_ID_2,
    assert_payout,
    setup_onsale_event, setup_marketplace, setup_paid_order,
    setup_completed_event_with_payout, setup_eligible_payout,
    setup_approved_payout, setup_released_payout, setup_payout, open_payout,
    create_organizer, create_venue, create_event, create_ticket_type, create_buyer,
    create_held_order, publish_event, close_sales, complete_event, set_clock,
    read_payout, read_organizer, organizer_version, make_organizer_headers,
    make_buyer_headers, make_finance_officer_headers,
)

FINANCE = TEST_USERS["finance_officer_headers"]
FINANCE_2 = TEST_USERS["finance_officer_headers_2"]


# ---------------------------------------------------------------------------
# Reliability: the same formula over two input sets
# ---------------------------------------------------------------------------

def _organizer_with_three_qualifying_events():
    """Two completed shows scoring 65 each and one cancelled show scoring 45."""
    organizer = create_organizer(display_name="Cascade Presents",
                                 contact_email="ops@cascade.example")
    halls = [create_venue(name=f"Hall {n}", city="Portland", seated_capacity=200)
             for n in ("One", "Two", "Three")]
    headers = make_organizer_headers(organizer["id"])

    august = create_event(organizer, halls[0], title="August Night",
                          starts_at="2026-08-01T18:00:00Z", ends_at="2026-08-01T22:00:00Z")
    september = create_event(organizer, halls[1], title="September Night",
                             starts_at="2026-09-01T18:00:00Z",
                             ends_at="2026-09-01T22:00:00Z")
    october = create_event(organizer, halls[2], title="October Night",
                           starts_at="2026-10-01T18:00:00Z",
                           ends_at="2026-10-01T22:00:00Z")

    for event in (august, september):
        create_ticket_type(organizer, event)
        publish_event(organizer, event)
        validate_success(api_client.close_event_sales(event["id"], headers), 200)

    validate_success(api_client.cancel_event(october["id"], headers,
                                             {"reason": "venue withdrew"}), 200)

    set_clock("2026-11-01T00:00:00Z")
    for event in (august, september):
        validate_success(api_client.complete_event(event["id"], headers), 200)

    return organizer, headers


def test_lifetime_reliability_averages_every_qualifying_event():
    """PRD §3.9: "`LIFETIME` — the default when the parameter is omitted — averages
    over every qualifying event."
    PRD §3.9: "The event's score is 100 multiplied by the sum of three weighted terms:
    0.45 times one minus the refund rate, plus 0.35 times the check-in rate, plus 0.20
    times one minus the cancellation flag. The organiser's score is the arithmetic
    mean of the event scores across the variant's input set, rounded half up exactly
    once to a whole integer between 0 and 100."

    Design: Difficulty/dual_variant_calc/reliability_lifetime_vs_trailing_divergence_on_organizer
    """
    organizer, headers = _organizer_with_three_qualifying_events()

    data = validate_success(api_client.get_organizer_reliability(
        organizer["id"], headers, params={"variant": "LIFETIME"}), 200)

    assert data["organizer_id"] == organizer["id"]
    assert data["variant"] == "LIFETIME"
    assert data["events_counted"] == 3, \
        f"Every qualifying event feeds the lifetime mean, got {data['events_counted']}"
    assert data["score"] == 58, (
        "Two completed shows score 65 and the cancelled show scores 45, so the mean "
        f"175/3 rounds half up to 58. Got {data['score']}")


def test_trailing_reliability_averages_only_the_two_most_recent_events():
    """PRD §3.9: "`TRAILING` averages over only the two most recently ended
    qualifying events, ordered by `ends_at` descending and tie-broken by `created_at`
    descending, which is why an organiser with one bad recent event scores strictly
    lower on `TRAILING` than on `LIFETIME`."
    PRD §3.9: "The read reports `organizer_id`, the `variant` applied, the resulting
    `score`, and the `events_counted` that fed the mean."

    Design: Difficulty/dual_variant_calc/reliability_lifetime_vs_trailing_divergence_on_organizer
    """
    organizer, headers = _organizer_with_three_qualifying_events()

    lifetime = validate_success(api_client.get_organizer_reliability(
        organizer["id"], headers, params={"variant": "LIFETIME"}), 200)
    trailing = validate_success(api_client.get_organizer_reliability(
        organizer["id"], headers, params={"variant": "TRAILING"}), 200)

    assert trailing["variant"] == "TRAILING"
    assert trailing["events_counted"] == 2, \
        f"Only the two most recently ended events feed it, got {trailing['events_counted']}"
    assert trailing["score"] == 55, (
        "The October cancellation (45) and the September show (65) average to 55. "
        f"Got {trailing['score']}")
    assert trailing["score"] != lifetime["score"], \
        "One bad recent event must pull the trailing score below the lifetime score"


def test_reliability_defaults_to_seventy_five_without_qualifying_events():
    """PRD §3.9: "When the organiser has no qualifying events at all, the score is 75
    by default rather than computed."
    PRD §3.9: "The reliability score is a weighted blend over the organiser's
    *qualifying* events — those the organiser owns whose status is `COMPLETED` or
    `CANCELLED`."

    Design: Corner/calculations/corner_reliability_defaults_to_seventy_five_without_qualifying_events
    """
    ctx = setup_marketplace(organizer_overrides={"display_name": "Fresh Co",
                                                 "contact_email": "ops@fresh.example"},
                            venue_overrides={"name": "Fresh Hall", "city": "Waco",
                                             "seated_capacity": 60})
    create_event(ctx["organizer"], ctx["venue"], title="Fresh Night",
                 starts_at="2026-10-06T18:00:00Z", ends_at="2026-10-06T22:00:00Z")

    data = validate_success(api_client.get_organizer_reliability(
        ctx["org_id"], ctx["org_headers"], params={"variant": "TRAILING"}), 200)

    assert data["score"] == 75, f"Expected the default score 75, got {data['score']}"
    assert data["events_counted"] == 0, \
        f"A draft event does not qualify, got {data['events_counted']}"
    assert data["variant"] == "TRAILING"
    assert data["organizer_id"] == ctx["org_id"]


# ---------------------------------------------------------------------------
# Opening a payout and the seven-step chain
# ---------------------------------------------------------------------------

def test_payout_cannot_be_marked_eligible_before_the_event_completes():
    """PRD §3.9: "Three preconditions apply beyond the source status: the event must
    be `COMPLETED` and the recomputed `net_amount_cents` must be at least zero, a
    failure of either being `ERR_PAYOUT_NOT_ELIGIBLE`; and no refund request on any
    order of the event may still be sitting in `REQUESTED` or `APPROVED`, a failure
    being `ERR_PAYOUT_PENDING_REFUNDS`."
    PRD §3.9: "Step five selects `reserve_rate` from the frozen
    `reliability_score_snapshot` on a four-rung ladder: a snapshot of at least 90
    withholds nothing at all, a rate of 0.00; at least 70 but below 90 withholds 0.05;
    at least 50 but below 70 withholds 0.10; and anything below 50 withholds 0.20."

    Design: Difficulty/cross_entity_state_dependency/payout_eligibility_gated_by_event_completion
    """
    ctx = setup_onsale_event(
        clock="2026-07-05T10:00:00Z",
        event_overrides={"title": "Settlement Night", "starts_at": "2026-08-01T18:00:00Z",
                         "ends_at": "2026-08-01T22:00:00Z"})
    setup_paid_order(ctx, buyer=create_buyer(email="quin@example.com",
                                             display_name="Quin"), quantity=2)
    close_sales(ctx)
    payout = setup_payout(ctx)

    resp = api_client.mark_payout_eligible(payout["id"], FINANCE)
    validate_error(resp, ApiErrorId.ERR_PAYOUT_NOT_ELIGIBLE.value, 409)

    # The payout itself is internally sound; only the sibling event blocks it.
    assert_payout(payout)
    assert payout["reliability_score_snapshot"] == 75, (
        "The organiser has no qualifying event yet, so the default score is frozen. "
        f"Got {payout['reliability_score_snapshot']}")
    assert payout["reserve_rate"] == pytest.approx(0.05), \
        f"A snapshot of 75 sits on the 0.05 rung, got {payout['reserve_rate']}"
    assert payout["reserve_cents"] == 500
    assert payout["net_amount_cents"] == 9500


def test_payout_becomes_eligible_once_the_event_is_completed():
    """PRD §3.9: "Marking a payout eligible moves it `ACCRUING → ELIGIBLE` and
    recomputes the whole seven-step chain."
    PRD §3.2: "Completion requires the event to be in `SALES_CLOSED` — otherwise
    `ERR_INVALID_EVENT_TRANSITION` — and requires that `ends_at` is at or before the
    current time, so an attempt to complete a show that has not yet finished is
    rejected with `ERR_EVENT_NOT_ENDED`."

    Design: Difficulty/cross_entity_state_dependency/payout_eligibility_gated_by_event_completion
    """
    ctx = setup_onsale_event(
        clock="2026-07-05T10:00:00Z",
        event_overrides={"title": "Settlement Night", "starts_at": "2026-08-01T18:00:00Z",
                         "ends_at": "2026-08-01T22:00:00Z"})
    setup_paid_order(ctx, buyer=create_buyer(email="quin2@example.com",
                                             display_name="Quin Two"), quantity=2)
    close_sales(ctx)
    payout = setup_payout(ctx)
    validate_error(api_client.mark_payout_eligible(payout["id"], FINANCE),
                   ApiErrorId.ERR_PAYOUT_NOT_ELIGIBLE.value, 409)

    set_clock("2026-08-02T00:00:00Z")
    complete_event(ctx)

    eligible = validate_success(api_client.mark_payout_eligible(payout["id"], FINANCE), 200)
    assert eligible["status"] == "ELIGIBLE", \
        f"Completion unblocks the transition, got {eligible['status']}"
    assert eligible["net_amount_cents"] == 9500


def test_perfect_reliability_withholds_no_reserve_at_all():
    """PRD §3.9: "Step five selects `reserve_rate` from the frozen
    `reliability_score_snapshot` on a four-rung ladder: a snapshot of at least 90
    withholds nothing at all, a rate of 0.00; at least 70 but below 90 withholds 0.05;
    at least 50 but below 70 withholds 0.10; and anything below 50 withholds 0.20."
    PRD §3.9: "The payout opens in `ACCRUING` status, freezes
    `reliability_score_snapshot` from the organiser's `TRAILING` reliability score at
    that instant, sets `reserve_release_at` to ninety days after the event's
    `ends_at`, opens `reserve_released_cents` at zero with `approved_by_user_id` and
    `released_by_user_id` both null, increments the organiser's `version` by 1, and
    computes the settlement chain."

    Design: Corner/calculations/corner_reserve_tier_a_zero_rate_for_perfect_score
    """
    ctx = setup_completed_event_with_payout(quantity=1, scan_all=True)
    payout = ctx["payout"]

    assert_payout(payout)
    assert payout["reliability_score_snapshot"] == 100, (
        "No refunds, a full check-in rate and no cancellation score exactly 100. "
        f"Got {payout['reliability_score_snapshot']}")
    assert payout["reserve_rate"] == pytest.approx(0.0), \
        f"A snapshot of at least 90 withholds nothing, got {payout['reserve_rate']}"
    assert payout["gross_cents"] == 5000
    assert payout["reserve_basis_cents"] == 5000
    assert payout["reserve_cents"] == 0
    assert payout["net_amount_cents"] == 5000
    assert payout["reserve_release_at"].startswith("2026-10-30T22:00:00"), (
        "The reserve matures ninety days after the event's end, got "
        f"{payout['reserve_release_at']}")
    assert payout["status"] == "ACCRUING"


def test_payout_can_be_held_then_resumed_back_to_eligible():
    """PRD §3.9: "A payout in `ACCRUING` or `ELIGIBLE` may be frozen to `ON_HOLD` with
    an optional `reason`, which freezes both approval and release; the settlement
    cascade of §3.8 drives the same transition automatically when a recompute pushes
    `net_amount_cents` below zero. Resuming returns a payout from `ON_HOLD` to
    `ELIGIBLE`, requires `net_amount_cents` to be at least zero — else
    `ERR_PAYOUT_NOT_ELIGIBLE` — and recomputes the full chain."

    Design: Corner/state_machines/corner_payout_hold_then_resume_returns_to_eligible
    """
    ctx = setup_eligible_payout(quantity=1)
    payout_id = ctx["payout_id"]

    held = validate_success(api_client.hold_payout(
        payout_id, FINANCE, {"reason": "manual review"}), 200)
    assert held["status"] == "ON_HOLD"

    resumed = validate_success(api_client.resume_payout(payout_id, FINANCE), 200)
    assert resumed["status"] == "ELIGIBLE", \
        f"Resuming returns the payout to ELIGIBLE, got {resumed['status']}"
    assert resumed["reliability_score_snapshot"] == 65, (
        "The single completed show with no scans scores 65. Got "
        f"{resumed['reliability_score_snapshot']}")
    assert resumed["gross_cents"] == 5000
    assert resumed["reserve_cents"] == 500
    assert resumed["net_amount_cents"] == 4500


def test_the_approving_officer_may_not_also_release_the_payout():
    """PRD §3.9: "Release moves an `APPROVED` payout to `RELEASED` and records the
    acting operator as `released_by_user_id` — but only if that operator differs from
    the one recorded in `approved_by_user_id`. One person may not both approve and
    release the same payout; an attempt is rejected with `ERR_SOD_SAME_ACTOR`
    (HTTP 403)."

    Design: Corner/rbac/corner_payout_release_by_the_approver_violates_segregation_of_duties
    """
    ctx = setup_approved_payout(quantity=1)
    payout_id = ctx["payout_id"]

    same_actor = api_client.release_payout(payout_id, FINANCE)
    validate_error(same_actor, ApiErrorId.ERR_SOD_SAME_ACTOR.value, 403)

    released = validate_success(api_client.release_payout(payout_id, FINANCE_2), 200)
    assert released["status"] == "RELEASED"
    assert released["approved_by_user_id"] == FINANCE_USER_ID
    assert released["released_by_user_id"] == FINANCE_USER_ID_2


def test_reserve_is_paid_only_once_it_has_matured():
    """PRD §3.9: "Releasing the reserve requires the current time to be at or after
    `reserve_release_at` — the ninety-day mark past the event's end — and an earlier
    attempt is rejected with `ERR_RESERVE_NOT_MATURED`. The release sets
    `reserve_released_cents` equal to `reserve_cents`."

    Design: Corner/endpoints/corner_release_reserve_before_maturity_then_after
    """
    ctx = setup_released_payout(quantity=1)
    payout_id = ctx["payout_id"]

    # The clock stands at 2026-08-02, well before the ninety-day mark.
    early = api_client.release_payout_reserve(payout_id, FINANCE_2)
    validate_error(early, ApiErrorId.ERR_RESERVE_NOT_MATURED.value, 409)

    matured = read_payout(payout_id)
    assert matured["reserve_release_at"].startswith("2026-10-30T22:00:00"), \
        f"Expected maturity ninety days past the end, got {matured['reserve_release_at']}"
    assert matured["reserve_cents"] == 500

    set_clock("2026-10-31T00:00:00Z")
    paid_out = validate_success(api_client.release_payout_reserve(payout_id, FINANCE_2), 200)

    assert paid_out["reserve_released_cents"] == 500, \
        f"The release pays the whole withheld reserve, got {paid_out['reserve_released_cents']}"
    assert paid_out["status"] == "RELEASED"
    assert paid_out["approved_by_user_id"] == FINANCE_USER_ID
    assert paid_out["released_by_user_id"] == FINANCE_USER_ID_2


def test_stale_expected_organizer_version_on_payout_create_is_rejected():
    """PRD §2.7: "A `POST /api/payouts` request must carry
    `expected_organizer_version` as a required input field, holding the `version` of
    the target `Organizer` as the client last observed it. If that value does not
    equal the organiser's current `version`, the create is rejected with
    `ERR_STALE_ORGANIZER_VERSION` (HTTP 412)."
    PRD §2.7: "An organiser's `version` advances on every paid order and every settled
    refund, each of which changes the amounts a newly created payout would compute;
    the check exists so that a finance operator cannot open a settlement against
    figures that have already moved beneath them."

    Design: Corner/cross_cutting_layers/corner_stale_expected_organizer_version_on_payout_create_returns_412
    """
    ctx = setup_onsale_event(
        clock="2026-07-05T10:00:00Z",
        event_overrides={"title": "Stale Night", "starts_at": "2026-08-01T18:00:00Z",
                         "ends_at": "2026-08-01T22:00:00Z"})
    buyer = create_buyer(email="nyx@example.com", display_name="Nyx")
    order = create_held_order(ctx, buyer, quantity=1)

    observed_version = organizer_version(ctx["org_id"])
    validate_success(api_client.pay_order(order["id"], make_buyer_headers(buyer["id"])), 200)
    close_sales(ctx)

    stale = open_payout(ctx, expected_organizer_version=observed_version)
    validate_error(stale, ApiErrorId.ERR_STALE_ORGANIZER_VERSION.value, 412)

    assert read_organizer(ctx["org_id"])["lifetime_gross_cents"] == 5000
    payout = validate_success(open_payout(ctx), 201)
    assert payout["gross_cents"] == 5000
    assert payout["reliability_score_snapshot"] == 75
    assert payout["status"] == "ACCRUING"
