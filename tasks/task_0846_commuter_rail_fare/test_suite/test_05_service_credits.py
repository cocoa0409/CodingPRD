"""Service disruptions, tiered compensation credits, void reversal, and window buffer."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
)
from test_helpers import fixtures as fx


# ==========================================================================
# transitive_cascade / service_credit_create_to_wallet_credit_depth2
# ==========================================================================

def test_service_credit_issue_credits_passenger_wallet(api):
    """PRD 3.8: "for a delay of at least 30 but under 60 minutes, twenty-five percent of the
    purchase price floored to whole cents"
    PRD 3.8: "Issuing the credit adds its amount to the passenger's wallet balance and
    advances the passenger's `version`; the credit is recorded in `ISSUED`."

    Design: Difficulty/transitive_cascade/service_credit_create_to_wallet_credit_depth2
    """
    pax, tkt, dis = fx.setup_service_credit_scenario(api, "2026-03-01T08:45:00Z")  # 45 min
    sc = fx.issue_service_credit(api, dis["id"], tkt["id"])
    assert sc["credit_amount_cents"] == 325  # floor(1300 * 0.25)
    assert sc["status"] == "ISSUED"
    assert fx.get_passenger(api, pax["id"])["wallet_credit_cents"] == 325


def test_severe_delay_credits_full_purchase_price_to_wallet(api):
    """PRD 3.8: "and for a delay of 120 minutes or more, the full purchase price."
    PRD 3.8: "Issuing the credit adds its amount to the passenger's wallet balance and
    advances the passenger's `version`"

    Design: Difficulty/transitive_cascade/service_credit_create_to_wallet_credit_depth2
    """
    pax, tkt, dis = fx.setup_service_credit_scenario(api, "2026-03-01T10:00:00Z")  # 120 min
    sc = fx.issue_service_credit(api, dis["id"], tkt["id"])
    assert sc["credit_amount_cents"] == 1300
    assert fx.get_passenger(api, pax["id"])["wallet_credit_cents"] == 1300


# ==========================================================================
# compensating_invariant / void_conserves_wallet_balance
# ==========================================================================

def test_void_credit_returns_wallet_to_pre_issue_balance(api):
    """PRD 3.8: "The void records the `void_reason`, moves the credit to the terminal
    `VOIDED` state, and subtracts the credit amount back out of the passenger's wallet
    balance as a compensating reversal, advancing the passenger's `version`."

    Design: Difficulty/compensating_invariant/void_conserves_wallet_balance
    """
    pax, tkt, dis = fx.setup_service_credit_scenario(api, "2026-03-01T08:45:00Z")  # 325
    sc = fx.issue_service_credit(api, dis["id"], tkt["id"])
    assert fx.get_passenger(api, pax["id"])["wallet_credit_cents"] == 325
    voided = validate_success(
        api.void_service_credit(sc["id"], {"reason": "recorded in error"}, fx.ADMIN), 200
    )
    assert voided["status"] == "VOIDED"
    assert fx.get_passenger(api, pax["id"])["wallet_credit_cents"] == 0


def test_void_full_credit_returns_wallet_to_zero(api):
    """PRD 3.8: "subtracts the credit amount back out of the passenger's wallet balance as
    a compensating reversal, advancing the passenger's `version`."

    Design: Difficulty/compensating_invariant/void_conserves_wallet_balance
    """
    pax, tkt, dis = fx.setup_service_credit_scenario(api, "2026-03-01T10:00:00Z")  # full 1300
    sc = fx.issue_service_credit(api, dis["id"], tkt["id"])
    assert fx.get_passenger(api, pax["id"])["wallet_credit_cents"] == 1300
    validate_success(api.void_service_credit(sc["id"], {"reason": "err"}, fx.ADMIN), 200)
    assert fx.get_passenger(api, pax["id"])["wallet_credit_cents"] == 0


# ==========================================================================
# boundary_precision_check / service_credit_delay_at_30_minutes_issues
# ==========================================================================

def test_service_credit_at_30_minute_delay_issues(api):
    """PRD 3.8: "The disruption's delay must be at least 30 minutes, or issuance fails with
    `ERR_DELAY_BELOW_THRESHOLD`"
    PRD 3.8: "for a delay of at least 30 but under 60 minutes, twenty-five percent of the
    purchase price floored to whole cents"

    Design: Difficulty/boundary_precision_check/service_credit_delay_at_30_minutes_issues
    """
    pax, tkt, dis = fx.setup_service_credit_scenario(api, "2026-03-01T08:30:00Z", line_code="L2")
    assert dis["delay_minutes"] == 30
    sc = fx.issue_service_credit(api, dis["id"], tkt["id"])
    assert sc["credit_amount_cents"] == 325
    assert sc["status"] == "ISSUED"


def test_service_credit_at_29_minute_delay_rejected(api):
    """PRD 3.8: "The disruption's delay must be at least 30 minutes, or issuance fails with
    `ERR_DELAY_BELOW_THRESHOLD`"

    Design: Difficulty/boundary_precision_check/service_credit_delay_at_30_minutes_issues
    """
    pax, tkt, dis = fx.setup_service_credit_scenario(api, "2026-03-01T08:29:00Z", line_code="L2b")
    assert dis["delay_minutes"] == 29
    resp = api.create_service_credit({"disruption_id": dis["id"], "ticket_id": tkt["id"]}, fx.ADMIN)
    validate_error(resp, ApiErrorId.ERR_DELAY_BELOW_THRESHOLD.value)


# ==========================================================================
# resource_temporal_overlap / disruption_window_within_buffer_rejected
# ==========================================================================

def test_disruption_window_within_buffer_rejected(api):
    """PRD 3.8: "A new disruption's window on a given line must be separated by at least the
    15-minute buffer from any existing disruption window on that same line; a window that
    falls within that buffer of an existing one is rejected with
    `ERR_DISRUPTION_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/disruption_window_within_buffer_rejected
    """
    fx.set_clock(api)
    fx.create_disruption(api, "L3", "2026-03-05T10:00:00Z", "2026-03-05T10:40:00Z",
                         "2026-03-05T10:00:00Z", "2026-03-05T10:30:00Z")
    resp = api.create_disruption(
        {"line_code": "L3", "scheduled_departure": "2026-03-05T10:40:00Z",
         "actual_departure": "2026-03-05T11:20:00Z",
         "window_start": "2026-03-05T10:40:00Z", "window_end": "2026-03-05T11:00:00Z"},
        fx.ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DISRUPTION_WINDOW_CONFLICT.value)


def test_disruption_window_at_buffer_boundary_allowed(api):
    """PRD 3.8: "A new disruption's window on a given line must be separated by at least the
    15-minute buffer from any existing disruption window on that same line"

    Design: Difficulty/resource_temporal_overlap/disruption_window_within_buffer_rejected
    """
    fx.set_clock(api)
    fx.create_disruption(api, "L3b", "2026-03-05T10:00:00Z", "2026-03-05T10:40:00Z",
                         "2026-03-05T10:00:00Z", "2026-03-05T10:30:00Z")
    # Second window starts 10:45 — exactly 15 minutes after the first window ends (10:30).
    data = validate_success(
        api.create_disruption(
            {"line_code": "L3b", "scheduled_departure": "2026-03-05T10:45:00Z",
             "actual_departure": "2026-03-05T11:25:00Z",
             "window_start": "2026-03-05T10:45:00Z", "window_end": "2026-03-05T11:05:00Z"},
            fx.ADMIN,
        ),
        201,
    )
    assert data["line_code"] == "L3b"


# ==========================================================================
# Corner: service credit threshold
# ==========================================================================

def test_service_credit_below_threshold_returns_delay_below(api):
    """PRD 3.8: "The disruption's delay must be at least 30 minutes, or issuance fails with
    `ERR_DELAY_BELOW_THRESHOLD`"

    Design: Corner/validations/service_credit_below_threshold_returns_delay_below
    """
    pax, tkt, dis = fx.setup_service_credit_scenario(api, "2026-03-01T08:29:00Z", line_code="S9")
    assert dis["delay_minutes"] == 29
    resp = api.create_service_credit({"disruption_id": dis["id"], "ticket_id": tkt["id"]}, fx.ADMIN)
    validate_error(resp, ApiErrorId.ERR_DELAY_BELOW_THRESHOLD.value)
