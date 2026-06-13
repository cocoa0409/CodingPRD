"""Corner: business-rule validations — duplicate case number, bond-type not
allowed, credit-limit, insufficient collateral, GPS-not-required, invalid
remission, notify-timing, grace-expired open-recovery.
"""
from test_helpers import (
    validate_error, get_success_data, api_client,
    setup_draft_surety_bond, setup_forfeited_bond, setup_judgment_ready, enter_judgment_on,
    pin_clock,
    TEST_USERS,
)

AGENT = TEST_USERS["bonds_agent_headers"]
COURT = TEST_USERS["court_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
RECOVERY = TEST_USERS["recovery_agent_headers"]


# Corner/validations/duplicate_case_number_rejected
def test_duplicate_case_number_rejected(api):
    """PRD 3.1: "The order references its defendant through `defendant_id` and
    carries a `case_number` that must be unique among that defendant's orders — a
    collision is rejected with `ERR_DUPLICATE_CASE_NUMBER` (HTTP 409)."

    Design: Corner/validations/duplicate_case_number_rejected
    """
    defendant = get_success_data(api_client.create_defendant(
        {"full_name": "Tu Gf", "date_of_birth": "1989-03-15", "phone_e164": "+15551110019"}, AGENT))
    get_success_data(api_client.create_bail_order(
        defendant["id"], {"case_number": "CR-DUP", "bail_amount_cents": 500000, "bond_type_allowed": "SURETY"}, COURT))
    resp = api.create_bail_order(
        defendant["id"], {"case_number": "CR-DUP", "bail_amount_cents": 700000, "bond_type_allowed": "SURETY"}, COURT)
    validate_error(resp, "ERR_DUPLICATE_CASE_NUMBER")


# Corner/validations/bond_type_not_allowed_by_order
def test_bond_type_not_allowed_by_order(api):
    """PRD 3.2: "the chosen `bond_type` is allowed only when the order's
    `bond_type_allowed` is `ANY` or exactly equals the chosen type, and a mismatch
    is rejected with `ERR_BOND_TYPE_NOT_ALLOWED` (HTTP 409)."

    Posting SURETY against a CASH-only order -> ERR_BOND_TYPE_NOT_ALLOWED.

    Design: Corner/validations/bond_type_not_allowed_by_order
    """
    defendant = get_success_data(api_client.create_defendant(
        {"full_name": "Uv Fe", "date_of_birth": "1990-04-16", "phone_e164": "+15551110020"}, AGENT))
    order = get_success_data(api_client.create_bail_order(
        defendant["id"], {"case_number": "CR-X13", "bail_amount_cents": 500000, "bond_type_allowed": "CASH"}, COURT))
    resp = api.create_bond(defendant["id"], order["id"], {"bond_type": "SURETY", "premium_rate_bps": 1000}, AGENT)
    validate_error(resp, "ERR_BOND_TYPE_NOT_ALLOWED")


# Corner/validations/credit_limit_exceeded_on_agreement
def test_credit_limit_exceeded_on_agreement(api):
    """PRD 3.3: "if the new share, added to the indemnitor's existing
    binding-and-pending exposure, would exceed `credit_limit_cents`, the attachment
    is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 409)."

    Indemnitor credit_limit 300,000 cannot take a 400,000c share.

    Design: Corner/validations/credit_limit_exceeded_on_agreement
    """
    scen = setup_draft_surety_bond(bail_amount_cents=1_000_000, with_indemnity=False,
                                   with_collateral=False)
    ind = get_success_data(api_client.create_indemnitor(
        {"full_name": "Yz Dc", "phone_e164": "+15551110022", "credit_limit_cents": 300000}, AGENT))
    resp = api.create_indemnity_agreement(
        scen["def_id"], scen["bond_id"], {"indemnitor_id": ind["id"], "liability_share_cents": 400000}, AGENT)
    validate_error(resp, "ERR_CREDIT_LIMIT_EXCEEDED")


# Corner/validations/insufficient_collateral_on_activate
def test_insufficient_collateral_on_activate(api):
    """PRD 3.2: "For surety and cash bonds alike, `collateral_held_cents` must be at
    least `required_collateral_cents`, and a shortfall is rejected with
    `ERR_INSUFFICIENT_COLLATERAL` (HTTP 409)."

    SURETY 2,000,000c MEDIUM (required 500,000) with only 400,000c collateral and
    full indemnity -> ERR_INSUFFICIENT_COLLATERAL.

    Design: Corner/validations/insufficient_collateral_on_activate
    """
    scen = setup_draft_surety_bond(bail_amount_cents=2_000_000, liability_share_cents=2_000_000,
                                   collateral_value_cents=400_000, risk_tier="MEDIUM")
    resp = api.activate_bond(scen["def_id"], scen["bond_id"], scen["agent"])
    validate_error(resp, "ERR_INSUFFICIENT_COLLATERAL")


# Corner/validations/gps_not_required_rejected
def test_gps_assign_when_not_required_rejected(api):
    """PRD 3.8: "the bond's bail order must actually mandate monitoring — its
    `gps_required` must be true — or the assignment is rejected with
    `ERR_GPS_NOT_REQUIRED` (HTTP 409)."

    Design: Corner/validations/gps_not_required_rejected
    """
    scen = setup_draft_surety_bond(bail_amount_cents=1_000_000, gps_required=False,
                                   with_indemnity=False, with_collateral=False)
    device = get_success_data(api_client.create_gps_device({"serial_number": "GPS-DDD-5"}, scen["agent"]))
    resp = api.assign_gps(scen["def_id"], scen["bond_id"], {"device_id": device["id"]}, scen["agent"])
    validate_error(resp, "ERR_GPS_NOT_REQUIRED")


# Corner/validations/invalid_remission_pct_rejected
def test_invalid_remission_pct_rejected(api):
    """PRD 3.6: "Remission is defined only from `JUDGMENT` and requires a
    `remission_pct` strictly greater than 0 and at most 100; a percentage outside
    that half-open range is rejected with `ERR_INVALID_REMISSION` (HTTP 400)."

    remission_pct == 0 is outside (0, 100] -> ERR_INVALID_REMISSION.

    Design: Corner/validations/invalid_remission_pct_rejected
    """
    scen = setup_judgment_ready(open_recovery=False, bail_amount_cents=1_000_000,
                                liability_share_cents=1_000_000, collateral_value_cents=250_000)
    enter_judgment_on(scen)
    resp = api.remit(scen["def_id"], scen["proc_id"], {"remission_pct": 0}, OFFICER)
    validate_error(resp, "ERR_INVALID_REMISSION")


# Corner/validations/notify_after_scheduled_timing_violation
def test_notify_at_or_after_scheduled_timing_violation(api):
    """PRD 3.5: "It is permitted only while the court date is `SCHEDULED` and the
    system clock is strictly before the hearing's `scheduled_utc`; an attempt at or
    after the scheduled instant is a timing violation, rejected with
    `ERR_TIMING_VIOLATION` (HTTP 409)."

    Design: Corner/validations/notify_after_scheduled_timing_violation
    """
    pin_clock("2026-07-01T00:00:00Z")
    scen = setup_draft_surety_bond(bail_amount_cents=1_000_000, with_indemnity=False,
                                   with_collateral=False)
    cd = get_success_data(api_client.create_court_date(
        scen["def_id"], scen["bond_id"], {"scheduled_utc": "2026-07-05T09:00:00Z", "duration_minutes": 60}, COURT))
    pin_clock("2026-07-06T00:00:00Z")
    resp = api.notify_court_date(scen["def_id"], cd["id"], {"channel": "SMS"}, COURT)
    validate_error(resp, "ERR_TIMING_VIOLATION")


# Corner/validations/grace_expired_open_recovery_rejected
def test_open_recovery_after_grace_expired_rejected(api):
    """PRD 3.6: "This is allowed only while the proceeding is `FORFEITED` and the
    system clock is at or before `grace_deadline_utc`; an attempt past the deadline
    is rejected with `ERR_GRACE_EXPIRED` (HTTP 409)."

    Design: Corner/validations/grace_expired_open_recovery_rejected
    """
    scen = setup_forfeited_bond(bail_amount_cents=1_000_000, liability_share_cents=1_000_000)
    pin_clock("2026-08-15T00:00:00Z")  # well past the 30-day grace deadline
    resp = api.open_recovery(scen["def_id"], scen["proc_id"], RECOVERY)
    validate_error(resp, "ERR_GRACE_EXPIRED")
