"""Foreclosure axis, receivership referral gating, and abatement ordering.

Covers difficulty instances 3a (parallel axes), 7a (referral requires stage),
7b (abatement requires escalated violation), 8b (abatement buffer overlap) plus
corner foreclosure terminal transitions.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_registrant_headers, create_registrant, create_property,
    setup_open_violation, setup_escalated_violation, advance_foreclosure,
    assess_fine, set_clock, get_property, transition_violation,
)

ADMIN = TEST_USERS["program_admin_headers"]


# --- Difficulty 3a: independent registration + foreclosure axes ------------
def _parallel_axes_property(api):
    """LIS_PENDENS on the foreclosure axis, SUSPENDED on the registration axis
    (balance 105000). Returns the property id."""
    ctx = setup_open_violation(api, base_fine_cents=95000, cure_period_days=5,
                               category="STRUCTURAL", severity_weight=6)
    reg_id = ctx["registrant"]["id"]
    prop_id = ctx["property"]["id"]
    advance_foreclosure(api, prop_id, reg_id)   # NONE -> NOTICE_OF_DEFAULT
    advance_foreclosure(api, prop_id, reg_id)   # NOTICE_OF_DEFAULT -> LIS_PENDENS
    set_clock(api, "2026-03-06T00:00:00Z")
    transition_violation(api, ctx["violation"]["id"], "ESCALATE")
    assess_fine(api, ctx["violation"]["id"])    # +95000 -> balance 105000 -> SUSPENDED
    return prop_id


def test_registration_axis_suspends_independently(api):
    """PRD §2.9: "The two axes are advanced and redeemed independently: a change to
    one never implicitly changes the other except through the explicit cascades
    described in Section 3."
    PRD §3.1: "a balance of exactly 100000 cents suspends".

    Design: Difficulty/non_linear_state_machine/property_parallel_registration_and_foreclosure_axes
    """
    prop = get_property(api, _parallel_axes_property(api))
    assert prop["registration_status"] == "SUSPENDED"
    assert prop["outstanding_balance_cents"] == 105000


def test_foreclosure_axis_holds_lis_pendens_independently(api):
    """PRD §2.9: "A property advances along two fully independent state axes." The
    `foreclosure_status` axis moves among NONE, NOTICE_OF_DEFAULT, LIS_PENDENS,
    AUCTION_SCHEDULED, and the terminal REO, unaffected by the registration axis.

    Design: Difficulty/non_linear_state_machine/property_parallel_registration_and_foreclosure_axes
    """
    prop = get_property(api, _parallel_axes_property(api))
    assert prop["foreclosure_status"] == "LIS_PENDENS"


# --- Difficulty 7a: receivership referral requires a foreclosure stage -----
def test_referral_blocked_when_foreclosure_none(api):
    """PRD §3.8: "Referral is permitted only when the property's
    `foreclosure_status` is either `NOTICE_OF_DEFAULT` or `LIS_PENDENS`; a referral
    attempted at any other foreclosure stage (including `NONE`, `AUCTION_SCHEDULED`,
    and `REO`) is rejected with `ERR_FORECLOSURE_STAGE_INVALID`."

    Design: Difficulty/cross_entity_state_dependency/referral_requires_foreclosure_stage
    """
    registrant = create_registrant(api, party_type="OWNER")
    prop = create_property(api, registrant, registration_type="OWNER")
    resp = api.create_receivership_referral(
        prop["id"], {"ground": "CHRONIC_NUISANCE", "receiver_name": "Receiver Co"}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_FORECLOSURE_STAGE_INVALID.value)


def test_referral_allowed_at_notice_of_default(api):
    """PRD §3.8: "Referral is permitted only when the property's
    `foreclosure_status` is either `NOTICE_OF_DEFAULT` or `LIS_PENDENS`".
    PRD §3.8: "A new referral begins in status `REFERRED` with `referred_at`
    stamped from the clock".

    Design: Difficulty/cross_entity_state_dependency/referral_requires_foreclosure_stage
    """
    registrant = create_registrant(api, party_type="OWNER")
    prop = create_property(api, registrant, registration_type="OWNER")
    advance_foreclosure(api, prop["id"], registrant["id"])  # -> NOTICE_OF_DEFAULT
    data = validate_success(
        api.create_receivership_referral(
            prop["id"], {"ground": "CHRONIC_NUISANCE", "receiver_name": "Receiver Co"}, ADMIN
        ),
        expected_status=201,
    )
    assert data["status"] == "REFERRED"


# --- Difficulty 7b: abatement requires an ESCALATED/FINED violation --------
_ABATE_WINDOW = {
    "scheduled_start": "2026-03-20T08:00:00Z",
    "scheduled_end": "2026-03-20T16:00:00Z",
    "estimated_cost_cents": 50000,
}


def test_abatement_blocked_while_violation_open(api):
    """PRD §3.7: "abatement presupposes an enforcement predicate: the property must
    have at least one `Violation` whose status is `ESCALATED` or `FINED`, or the
    order is rejected with `ERR_NO_ABATABLE_VIOLATION`."

    Design: Difficulty/cross_entity_state_dependency/abatement_requires_escalated_violation
    """
    ctx = setup_open_violation(api, base_fine_cents=20000, cure_period_days=5,
                               category="STRUCTURAL", severity_weight=7)
    resp = api.create_abatement_order(ctx["property"]["id"], dict(_ABATE_WINDOW), ADMIN)
    validate_error(resp, ApiErrorId.ERR_NO_ABATABLE_VIOLATION.value)


def test_abatement_allowed_once_violation_escalated(api):
    """PRD §3.7: "the property must have at least one `Violation` whose status is
    `ESCALATED` or `FINED`". Once escalated, the order is accepted.
    PRD §3.7: "A new order begins in status `ORDERED` with `ordered_at` stamped
    from the clock".

    Design: Difficulty/cross_entity_state_dependency/abatement_requires_escalated_violation
    """
    ctx = setup_escalated_violation(api, escalate_clock="2026-03-06T00:00:00Z",
                                    base_fine_cents=20000, cure_period_days=5,
                                    category="STRUCTURAL", severity_weight=7)
    data = validate_success(
        api.create_abatement_order(ctx["property"]["id"], dict(_ABATE_WINDOW), ADMIN),
        expected_status=201,
    )
    assert data["status"] == "ORDERED"


# --- Difficulty 8b: abatement property-window 24h buffer -------------------
def _property_with_first_abatement(api):
    ctx = setup_escalated_violation(api, escalate_clock="2026-03-06T00:00:00Z",
                                    base_fine_cents=20000, cure_period_days=5,
                                    category="SANITATION", severity_weight=7)
    validate_success(
        api.create_abatement_order(
            ctx["property"]["id"],
            {"scheduled_start": "2026-03-10T08:00:00Z",
             "scheduled_end": "2026-03-10T16:00:00Z",
             "estimated_cost_cents": 40000},
            ADMIN,
        ),
        expected_status=201,
    )
    return ctx["property"]["id"]


def test_second_abatement_within_buffer_rejected(api):
    """PRD §3.7: "if any other non-terminal abatement order on the same property
    has a window within 24 hours of the new window, the order is rejected with
    `ERR_ABATEMENT_WINDOW_CONFLICT`. This buffer is measured on the closed interval
    from `scheduled_start` through `scheduled_end` inclusive, and adjacency falling
    inside the 24-hour buffer is itself a conflict — two windows must be separated
    by more than 24 hours."

    Design: Difficulty/resource_temporal_overlap/abatement_property_buffer_overlap
    """
    prop_id = _property_with_first_abatement(api)
    resp = api.create_abatement_order(
        prop_id,
        {"scheduled_start": "2026-03-11T10:00:00Z",   # 18h after first ends
         "scheduled_end": "2026-03-11T14:00:00Z",
         "estimated_cost_cents": 30000},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_ABATEMENT_WINDOW_CONFLICT.value)


def test_second_abatement_beyond_buffer_allowed(api):
    """PRD §3.7: "two windows must be separated by more than 24 hours." A second
    window opening more than 24 hours after the first closes is accepted.

    Design: Difficulty/resource_temporal_overlap/abatement_property_buffer_overlap
    """
    prop_id = _property_with_first_abatement(api)
    data = validate_success(
        api.create_abatement_order(
            prop_id,
            {"scheduled_start": "2026-03-12T08:00:00Z",  # 40h after first ends
             "scheduled_end": "2026-03-12T12:00:00Z",
             "estimated_cost_cents": 30000},
            ADMIN,
        ),
        expected_status=201,
    )
    assert data["status"] == "ORDERED"


# --- Corner: foreclosure terminal transitions ------------------------------
def test_advance_past_reo_returns_terminal(api):
    """PRD §3.2: "Attempting to `ADVANCE` a property that is already `REO` has
    nowhere to go and is rejected with `ERR_FORECLOSURE_TERMINAL`."

    Design: Corner/state_machines/foreclosure_advance_past_reo_returns_terminal
    """
    registrant = create_registrant(api, party_type="OWNER")
    prop = create_property(api, registrant, registration_type="OWNER")
    for _ in range(4):
        validate_success(api.foreclosure_property(prop["id"], {"action": "ADVANCE"}, ADMIN))
    reo = get_property(api, prop["id"])
    assert reo["foreclosure_status"] == "REO"
    resp = api.foreclosure_property(prop["id"], {"action": "ADVANCE"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_FORECLOSURE_TERMINAL.value)


def test_redeem_from_none_returns_terminal(api):
    """PRD §3.2: "a property already at `NONE` has nothing to redeem; a `REDEEM` in
    either of those situations is rejected with `ERR_FORECLOSURE_TERMINAL`."

    Design: Corner/state_machines/redeem_from_none_returns_terminal
    """
    registrant = create_registrant(api, party_type="OWNER")
    prop = create_property(api, registrant, registration_type="OWNER")
    resp = api.foreclosure_property(
        prop["id"], {"action": "REDEEM"}, make_registrant_headers(registrant["id"])
    )
    validate_error(resp, ApiErrorId.ERR_FORECLOSURE_TERMINAL.value)
