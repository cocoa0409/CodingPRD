"""Membership term lifecycle: renewal cycle, cascades, auto-renew, suspend.

Covers Difficulty queue: non_linear_state_machine (renewal cycle), transitive_cascade
(cancel fans into visit-cancel + offer-expiry); plus corner state_machine transitions.
"""
from test_helpers import (
    validate_success,
    validate_error,
    api_client,
    TEST_USERS,
    make_customer_headers,
    ApiErrorId,
    create_renewal_offer_payload,
    create_and_activate_membership,
    setup_membership_in_renewal_pending,
    setup_active_membership_with_tech,
    book_visit,
    get_membership,
    get_offer,
    get_visit,
    advance_clock,
    set_clock,
)

ADMIN = TEST_USERS["contract_admin_headers"]


# ===========================================================================
# Difficulty / non_linear_state_machine — renewal cycle returns to ACTIVE
# ===========================================================================
def test_accept_renewal_offer_returns_membership_to_active_with_incremented_term_index(api):
    """PRD §3.4: "A manual acceptance sets the offer's `status` to `ACCEPTED` and drives
    the membership's `RENEWAL_PENDING → ACTIVE` renewal: the membership's `plan_id` is set
    to the offer's `offered_plan_id`, the new `term_start` is set to the previous
    `term_end`, the new `term_end` is set to 365 days after the new `term_start`,
    `term_index` is incremented by one, the offer's `offered_annual_fee_cents` is accrued
    onto the customer's `billing_balance_cents`, and the membership's `version` is
    incremented by one."

    Design: Difficulty/non_linear_state_machine/membership_renewal_cycle_returns_to_active
    """
    ctx = setup_membership_in_renewal_pending()
    customer_headers = make_customer_headers(ctx["customer"]["id"])

    accepted = validate_success(api.accept_renewal_offer(ctx["offer"]["id"], customer_headers), 200)
    assert accepted["status"] == "ACCEPTED", f"manual accept sets ACCEPTED, got {accepted['status']}"

    membership = get_membership(ctx["membership"]["id"])
    assert membership["status"] == "ACTIVE", f"renewal cycle returns to ACTIVE, got {membership['status']}"
    assert membership["term_index"] == 2, f"term_index increments 1 -> 2, got {membership['term_index']}"


def test_renewal_offer_creation_flips_membership_to_renewal_pending(api):
    """PRD §3.4: "On success the system creates the offer in `PENDING` status, snapshots
    the offered plan's `annual_fee_cents` into the offer's `offered_annual_fee_cents` (a
    version-pinned price the offer will honor regardless of later plan changes), flips the
    membership from `ACTIVE` to `RENEWAL_PENDING`, and increments the membership's
    `version` by one."

    Design: Difficulty/non_linear_state_machine/membership_renewal_cycle_returns_to_active
    """
    ctx = setup_membership_in_renewal_pending(plan_overrides={"annual_fee_cents": 24000})
    offer = get_offer(ctx["offer"]["id"])
    assert offer["status"] == "PENDING"
    assert offer["offered_annual_fee_cents"] == 24000, (
        f"offer snapshots the plan annual_fee_cents 24000, got {offer['offered_annual_fee_cents']}"
    )
    membership = get_membership(ctx["membership"]["id"])
    assert membership["status"] == "RENEWAL_PENDING", (
        f"offer creation flips membership to RENEWAL_PENDING, got {membership['status']}"
    )


# ===========================================================================
# Difficulty / transitive_cascade — cancel cascades visit cancel + offer expiry
# ===========================================================================
def test_cancel_membership_cascades_visit_cancel_and_offer_expiry(api):
    """PRD §3.3: "Cancellation cascades more broadly than suspension: it cancels every one
    of the membership's service visits in `SCHEDULED`, `DISPATCHED`, or `EN_ROUTE` status
    (each to `CANCELLED`), expires any renewal offer for the membership currently in
    `PENDING` status (setting that offer to `EXPIRED`), and increments the membership's
    `version` by one."

    Design: Difficulty/transitive_cascade/membership_cancel_cascades_visit_cancel_and_offer_expiry
    """
    ctx = create_and_activate_membership()
    visit = book_visit(ctx["membership"], visit_kind="SEASONAL")
    # Creating the offer advances the membership version, so re-read before offering.
    from test_helpers import create_renewal_offer
    membership_now = get_membership(ctx["membership"]["id"])
    offer = create_renewal_offer(membership_now)

    customer_headers = make_customer_headers(ctx["customer"]["id"])
    cancelled = validate_success(api.cancel_membership(ctx["membership"]["id"], customer_headers), 200)
    assert cancelled["status"] == "CANCELLED", f"membership becomes CANCELLED, got {cancelled['status']}"

    assert get_visit(visit["id"])["status"] == "CANCELLED", "SCHEDULED visit cascade-cancels"
    assert get_offer(offer["id"])["status"] == "EXPIRED", "PENDING offer expires on cancel"


def test_cancel_membership_cascades_dispatched_visit_to_cancelled(api):
    """PRD §3.3: "Cancellation cascades more broadly than suspension: it cancels every one
    of the membership's service visits in `SCHEDULED`, `DISPATCHED`, or `EN_ROUTE` status
    (each to `CANCELLED`)."

    Design: Difficulty/transitive_cascade/membership_cancel_cascades_visit_cancel_and_offer_expiry
    """
    ctx = setup_active_membership_with_tech()
    visit = book_visit(ctx["membership"], visit_kind="SEASONAL")
    from test_helpers import dispatch_visit
    dispatch_visit(visit["id"], ctx["technician"]["id"])  # visit now DISPATCHED
    customer_headers = make_customer_headers(ctx["customer"]["id"])
    cancelled = validate_success(api.cancel_membership(ctx["membership"]["id"], customer_headers), 200)
    assert cancelled["status"] == "CANCELLED"
    assert get_visit(visit["id"])["status"] == "CANCELLED", "DISPATCHED visit cascade-cancels on membership cancel"


# ===========================================================================
# Corner / state_machines
# ===========================================================================
def test_activate_already_active_membership_rejected(api):
    """PRD §3.3: "Activation is permitted only when the membership is in
    `PENDING_ACTIVATION` and its referenced plan is currently active; an attempt against
    a non-pending membership is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/activate_already_active_membership_returns_invalid_state
    """
    ctx = create_and_activate_membership()
    validate_error(api.activate_membership(ctx["membership"]["id"], ADMIN), ApiErrorId.ERR_INVALID_STATE.value)


def test_suspend_active_membership_cascades_scheduled_visit_cancel(api):
    """PRD §3.3: "The `ACTIVE → SUSPENDED` transition cascades down into the membership's
    visits, cancelling every one of its service visits currently in `SCHEDULED` or
    `DISPATCHED` status (each such visit transitions to `CANCELLED`), and increments the
    membership's `version` by one."

    Design: Corner/state_machines/suspend_active_membership_cascades_scheduled_visit_cancel
    """
    ctx = create_and_activate_membership()
    visit = book_visit(ctx["membership"], visit_kind="SEASONAL")
    suspended = validate_success(api.suspend_membership(ctx["membership"]["id"], ADMIN), 200)
    assert suspended["status"] == "SUSPENDED", f"membership becomes SUSPENDED, got {suspended['status']}"
    assert get_visit(visit["id"])["status"] == "CANCELLED", "SCHEDULED visit cascade-cancels on suspend"


def test_auto_renew_clock_advance_auto_accepts_offer(api):
    """PRD §3.4: "For an offer whose membership has `auto_renew` set to true, crossing
    `expires_at` auto-accepts the offer: its `status` becomes `AUTO_ACCEPTED` and it
    drives the same `RENEWAL_PENDING → ACTIVE` renewal (new term window, incremented
    `term_index`, accrued fee, version bump) as a manual acceptance."

    Design: Corner/state_machines/auto_renew_clock_advance_auto_accepts_offer
    """
    ctx = setup_membership_in_renewal_pending(
        plan_overrides={"auto_renew_default": True},
        membership_overrides={"auto_renew": True},
        offer_overrides={"expires_at": "2026-07-15T00:00:00Z"},
    )
    advance_clock("2026-07-16T00:00:00Z")
    assert get_offer(ctx["offer"]["id"])["status"] == "AUTO_ACCEPTED", "auto_renew true -> AUTO_ACCEPTED"
    membership = get_membership(ctx["membership"]["id"])
    assert membership["status"] == "ACTIVE", f"renewal returns to ACTIVE, got {membership['status']}"
    assert membership["term_index"] == 2, f"term_index increments to 2, got {membership['term_index']}"


def test_no_auto_renew_clock_advance_expires_offer_and_lapses_membership(api):
    """PRD §3.4: "For an offer whose membership has `auto_renew` set to false, crossing
    `expires_at` expires the offer: its `status` becomes `EXPIRED` and it drives the
    membership's `RENEWAL_PENDING → LAPSED` transition."

    Design: Corner/state_machines/no_auto_renew_clock_advance_expires_offer_membership_lapses
    """
    ctx = setup_membership_in_renewal_pending(
        plan_overrides={"auto_renew_default": False},
        membership_overrides={"auto_renew": False},
        offer_overrides={"expires_at": "2026-07-15T00:00:00Z"},
    )
    advance_clock("2026-07-16T00:00:00Z")
    assert get_offer(ctx["offer"]["id"])["status"] == "EXPIRED", "auto_renew false -> EXPIRED"
    membership = get_membership(ctx["membership"]["id"])
    assert membership["status"] == "LAPSED", f"membership lapses, got {membership['status']}"


def test_second_open_renewal_offer_rejected(api):
    """PRD §3.4: "Creating the offer requires the membership to be `ACTIVE` and requires
    that no renewal offer for that membership already sits in `PENDING`, `ACCEPTED`, or
    `AUTO_ACCEPTED` status; a second open offer is rejected with `ERR_OFFER_ALREADY_OPEN`."

    Design: Corner/validations/second_open_renewal_offer_rejected
    """
    ctx = setup_membership_in_renewal_pending()
    # A PENDING offer already exists; re-read the membership for its current version.
    membership_now = get_membership(ctx["membership"]["id"])
    payload = create_renewal_offer_payload(ctx["plan"]["id"], membership_now["version"])
    validate_error(api.create_renewal_offer(ctx["membership"]["id"], payload, ADMIN),
                   ApiErrorId.ERR_OFFER_ALREADY_OPEN.value)


def test_accept_renewal_offer_after_expiry_rejected(api):
    """PRD §3.4: "Accepting an offer is permitted only when the offer is `PENDING`, the
    owning membership is in `RENEWAL_PENDING`, and the current clock is strictly before
    the offer's `expires_at`; an accept or decline at or after `expires_at` is rejected
    with `ERR_OFFER_EXPIRED`."

    Design: Corner/validations/accept_offer_after_expiry_rejected
    """
    ctx = setup_membership_in_renewal_pending(offer_overrides={"expires_at": "2026-07-15T00:00:00Z"})
    # set_current_utc (not advance) does NOT auto-fire, leaving the offer PENDING past expiry.
    set_clock("2026-07-16T00:00:00Z")
    validate_error(
        api.accept_renewal_offer(ctx["offer"]["id"], make_customer_headers(ctx["customer"]["id"])),
        ApiErrorId.ERR_OFFER_EXPIRED.value,
    )
