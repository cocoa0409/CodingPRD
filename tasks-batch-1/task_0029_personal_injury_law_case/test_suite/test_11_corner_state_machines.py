"""Corner-design coverage — state_machines section."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    register_client,
    sign_retainer,
    create_case,
    activate_case,
    register_provider,
    create_records_request,
    walk_records_request_to_reviewed,
    create_proposed_damages,
    include_damages,
    create_included_damages,
    create_demand_letter,
    send_demand_letter,
    create_offer,
    create_court_event,
    accept_offer,
    get_case,
    get_case_version,
    ApiErrorId,
    api_client,
    accept_offer_payload,
    make_attorney_headers,
    make_managing_partner_headers,
    make_paralegal_headers,
    setup_active_case,
    setup_active_case_with_reviewed_records,
    setup_settled_case_with_paid_liens,
)


# ─── case_activate_from_already_active_invalid_state ────────────────


def test_activate_already_active_case_returns_invalid_state(api):
    """PRD §2.9: "After existence comes state: the direct state precondition
    on the target resource (`ERR_INVALID_STATE`) is checked before any
    cross-entity state precondition (`ERR_CROSS_ENTITY_STATE`)."
    PRD §3.1: "The case sits in `INTAKE` until an `Attorney` activates it,
    at which point it moves `INTAKE → ACTIVE`."

    Design: Corner/state_machines/case_activate_from_already_active_invalid_state
    """
    set_clock("2026-01-01T00:00:00Z")
    client, case = setup_active_case()
    # Second activate attempt — case is already ACTIVE.
    res = api_client.activate_case(case["id"], make_attorney_headers())
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    case_after = get_case(case["id"])
    assert case_after["status"] == "ACTIVE"


# ─── case_close_from_settled_requires_disbursement_released ─────────


def test_close_settled_case_with_pending_disbursement_returns_cross_entity(api):
    """PRD §3.9: "After a `Disbursement` has been released and every medical
    lien on the case has reached `PAID`, the `ManagingPartner` may close the
    case by moving it `SETTLED → CLOSED`. Attempting to close before both
    preconditions hold (a released disbursement and uniformly paid liens) is
    rejected with `ERR_CROSS_ENTITY_STATE`."

    Design: Corner/state_machines/case_close_from_settled_requires_disbursement_released
    """
    # Build a settled case with PENDING disbursement (do not release).
    from test_helpers import (
        setup_case_in_negotiation_with_offer,
    )
    set_clock("2026-01-01T00:00:00Z")
    client, case_neg, provider, offer = setup_case_in_negotiation_with_offer(
        offer_amount_cents=4_000_000, by_party="CARRIER",
    )
    case_v = get_case_version(case_neg["id"])
    accept_offer(offer["id"], case_v)
    case_settled = get_case(case_neg["id"])
    assert case_settled["status"] == "SETTLED"
    # Now attempt close — disbursement is still PENDING.
    res = api_client.close_case(case_settled["id"],
                                 make_managing_partner_headers())
    validate_error(res, ApiErrorId.ERR_CROSS_ENTITY_STATE.value)
    case_after = get_case(case_settled["id"])
    assert case_after["status"] == "SETTLED"


# ─── mrr_review_without_prior_receive_invalid_state ─────────────────


def test_review_records_request_in_requested_state_returns_invalid_state(api):
    """PRD §3.2: "When records actually arrive, the paralegal advances the
    request `REQUESTED → RECEIVED`, which stamps `received_at`. The
    `Attorney` then reviews the records, advancing `RECEIVED → REVIEWED`
    and stamping `reviewed_at`."
    PRD §2.9: "After existence comes state: the direct state precondition
    on the target resource (`ERR_INVALID_STATE`) is checked before any
    cross-entity state precondition (`ERR_CROSS_ENTITY_STATE`)."

    Design: Corner/state_machines/mrr_review_without_prior_receive_invalid_state
    """
    set_clock("2026-01-01T00:00:00Z")
    client, case = setup_active_case()
    provider = register_provider()
    mrr = create_records_request(case["id"], provider["id"])
    # Skip receive; attempt to review.
    res = api_client.review_records_request(mrr["id"], make_attorney_headers())
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ─── settlement_accept_from_terminal_rejected_invalid_state ─────────


def test_accept_offer_in_rejected_terminal_state_returns_invalid_state(api):
    """PRD §3.5: "A `ManagingPartner` may reject the current `PENDING`
    offer, moving it `PENDING → REJECTED` and stamping `responded_at`."
    PRD §3.6: "Accepting an offer is the most consequential write in the
    system, and it carries five preconditions in addition to the offer
    being `PENDING`."

    Design: Corner/state_machines/settlement_accept_from_terminal_rejected_invalid_state
    """
    from test_helpers import setup_case_in_negotiation_with_offer
    set_clock("2026-01-01T00:00:00Z")
    client, case_neg, provider, offer = setup_case_in_negotiation_with_offer(
        offer_amount_cents=2_000_000, by_party="CARRIER",
    )
    api_client.reject_offer(offer["id"], make_managing_partner_headers())
    # Now attempt to accept the REJECTED offer.
    case_v = get_case_version(case_neg["id"])
    res = api_client.accept_offer(
        offer["id"], accept_offer_payload(case_v),
        make_managing_partner_headers(),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ─── settlement_offer_thirty_day_expiry_on_clock_advance ────────────


def test_setting_clock_past_thirty_days_expires_pending_offer(api):
    """PRD §3.5: "the offer may simply age out: once thirty days have passed
    since the offer's `created_at`, an offer still in `PENDING` is moved
    `PENDING → EXPIRED` by the system as a side effect of two events — any
    read of the parent case (which sweeps that case's offers against the
    current clock) and any successful clock-set call (which sweeps
    system-wide). On expiry, `responded_at` is stamped to the current clock
    value at the moment of the sweep."

    Design: Corner/state_machines/settlement_offer_thirty_day_expiry_on_clock_advance
    """
    from test_helpers import setup_case_in_negotiation_with_offer, TEST_USERS
    set_clock("2026-01-01T00:00:00Z")
    client, case_neg, provider, offer = setup_case_in_negotiation_with_offer(
        offer_amount_cents=2_000_000, by_party="CARRIER",
    )
    # Advance clock 31 days past offer creation.
    set_clock("2026-02-01T00:00:00Z")
    offer_after = validate_success(
        api.get_offer(offer["id"], TEST_USERS["attorney_headers"]), 200
    )
    assert offer_after["status"] == "EXPIRED"


# ─── damages_item_include_with_excluded_state_invalid ───────────────


def test_include_excluded_damages_item_returns_invalid_state(api):
    """PRD §3.3: "An item can also be moved from `PROPOSED` to `EXCLUDED`
    by the `Attorney` — `EXCLUDED` is terminal."
    PRD §3.3: "A `PROPOSED` item moves into the case's working damages
    model when the `Attorney` promotes it `PROPOSED → INCLUDED`."
    PRD §2.9: "After existence comes state: the direct state precondition
    on the target resource (`ERR_INVALID_STATE`) is checked before any
    cross-entity state precondition (`ERR_CROSS_ENTITY_STATE`)."

    Design: Corner/state_machines/damages_item_include_with_excluded_state_invalid
    """
    set_clock("2026-01-01T00:00:00Z")
    client, case = setup_active_case()
    item = create_proposed_damages(case["id"], "PROPERTY", 100_000)
    api_client.exclude_damages_item(item["id"], make_attorney_headers())
    # EXCLUDED is terminal; attempting include now must fail.
    res = api_client.include_damages_item(item["id"], make_attorney_headers())
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ─── court_event_mark_occurred_before_scheduled_at_invalid_state ────


def test_mark_court_event_occurred_before_clock_returns_invalid_state(api):
    """PRD §3.8: "A scheduled event can be moved `SCHEDULED → OCCURRED` by
    the `Attorney` once the clock has caught up — specifically, the system
    clock at the moment of the mark must be at or later than the event's
    `scheduled_at`; otherwise the transition is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/court_event_mark_occurred_before_scheduled_at_invalid_state
    """
    set_clock("2026-01-01T00:00:00Z")
    client, case = setup_active_case()
    event = create_court_event(case["id"], "HEARING",
                                "2026-08-01T14:00:00Z", duration_minutes=60)
    # Clock still at 2026-01-01 — before scheduled_at.
    res = api_client.mark_court_event_occurred(
        event["id"], make_attorney_headers()
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
