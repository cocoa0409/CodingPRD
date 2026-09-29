"""Composite setup builders.

The harness restarts the server with an empty database before every single
test, so nothing here may assume a previously seeded row.  Each builder drives
the real endpoints in the order the PRD requires and returns the created
resource (or a tuple of resources), so a test can start from any depth of the
workflow it needs.  These are plain functions rather than pytest fixtures
precisely because most tests need to call them more than once with different
arguments.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_STARTUP_INSTANT
from .factories import (
    award_booking_payload,
    award_inventory_window_payload,
    co_brand_issuer_payload,
    deferred_revenue_posting_payload,
    fraud_case_payload,
    loyalty_program_payload,
    member_account_payload,
    mile_purchase_order_payload,
    mile_sale_agreement_payload,
    mile_transaction_payload,
    partner_airline_payload,
    program_change_notice_payload,
    promotion_campaign_payload,
)
from .test_users import (
    CONTRACTS_OFFICER,
    FRAUD_ANALYST,
    FRAUD_ANALYST_2,
    PARTNER_MANAGER,
    PROGRAM_ADMIN,
    REVENUE_ACCOUNTANT,
    make_issuer_representative_headers,
    make_member_headers,
)


# --------------------------------------------------------------------------- #
# Clock and epoch runner
# --------------------------------------------------------------------------- #
def set_clock(to_iso8601: str, headers=PROGRAM_ADMIN) -> dict:
    """Reposition the logical clock and return the reported ``current_utc``."""
    return get_success_data(api_client.set_current_utc(to_iso8601, headers))


def reset_clock(headers=PROGRAM_ADMIN) -> dict:
    """Return the clock to the instant it reads at server startup."""
    return set_clock(CLOCK_STARTUP_INSTANT, headers)


def run_epoch(program_id: str, headers=PROGRAM_ADMIN) -> dict:
    """Invoke the epoch sweep for one programme and return its report."""
    return get_success_data(api_client.run_epoch(program_id, headers))


# --------------------------------------------------------------------------- #
# Programme, counterparties and accounting posture
# --------------------------------------------------------------------------- #
def create_program(**overrides) -> dict:
    return get_success_data(
        api_client.create_loyalty_program(
            loyalty_program_payload(**overrides), PROGRAM_ADMIN
        )
    )


def read_program(program_id: str, headers=PROGRAM_ADMIN) -> dict:
    return get_success_data(api_client.get_loyalty_program(program_id, headers))


def transition_recognition(program_id: str, target_state: str) -> dict:
    return get_success_data(
        api_client.create_recognition_transition(
            program_id, {"target_state": target_state}, REVENUE_ACCOUNTANT
        )
    )


def create_issuer(program_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_co_brand_issuer(
            co_brand_issuer_payload(program_id, **overrides), PROGRAM_ADMIN
        )
    )


def create_partner(program_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_partner_airline(
            partner_airline_payload(program_id, **overrides), PROGRAM_ADMIN
        )
    )


def program_with_issuer(program_overrides=None, issuer_overrides=None):
    """A programme plus one co-brand issuer registered beneath it."""
    program = create_program(**(program_overrides or {}))
    issuer = create_issuer(program["id"], **(issuer_overrides or {}))
    return program, issuer


# --------------------------------------------------------------------------- #
# Mile sale agreement negotiation
# --------------------------------------------------------------------------- #
def draft_agreement(issuer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_mile_sale_agreement(
            mile_sale_agreement_payload(issuer_id, **overrides), PARTNER_MANAGER
        )
    )


def read_agreement(agreement_id: str, headers=PARTNER_MANAGER) -> dict:
    return get_success_data(
        api_client.get_mile_sale_agreement(agreement_id, headers)
    )


def submit_agreement(agreement_id: str, headers=PARTNER_MANAGER) -> dict:
    return get_success_data(api_client.submit_agreement(agreement_id, headers))


def counter_agreement(agreement_id: str, issuer_id: str, price: int,
                      volume: int, note=None) -> dict:
    payload = {
        "counter_price_per_mile_centicents": price,
        "counter_committed_volume_miles": volume,
    }
    if note is not None:
        payload["note"] = note
    return get_success_data(
        api_client.counter_agreement(
            agreement_id, payload, make_issuer_representative_headers(issuer_id)
        )
    )


def revise_agreement(agreement_id: str, committed_volume_miles: int,
                     tier_schedule: list, headers=PARTNER_MANAGER) -> dict:
    return get_success_data(
        api_client.revise_agreement(
            agreement_id,
            {
                "committed_volume_miles": committed_volume_miles,
                "tier_schedule": tier_schedule,
            },
            headers,
        )
    )


def ratify_agreement(agreement_id: str, headers=CONTRACTS_OFFICER) -> dict:
    return get_success_data(api_client.ratify_agreement(agreement_id, headers))


def activate_agreement(agreement_id: str, headers=CONTRACTS_OFFICER) -> dict:
    return get_success_data(api_client.activate_agreement(agreement_id, headers))


def active_agreement(issuer_id: str, **overrides) -> dict:
    """Walk DRAFT -> ISSUER_REVIEW -> RATIFIED -> ACTIVE and return the row."""
    agreement = draft_agreement(issuer_id, **overrides)
    submit_agreement(agreement["id"])
    ratify_agreement(agreement["id"])
    return activate_agreement(agreement["id"])


def program_with_active_agreement(program_overrides=None, issuer_overrides=None,
                                  agreement_overrides=None):
    """A programme, its issuer, and one ACTIVE agreement ready to be drawn on."""
    program, issuer = program_with_issuer(program_overrides, issuer_overrides)
    agreement = active_agreement(issuer["id"], **(agreement_overrides or {}))
    return program, issuer, agreement


# --------------------------------------------------------------------------- #
# Mile purchase orders
# --------------------------------------------------------------------------- #
def create_order(agreement_id: str, order_miles: int,
                 expected_agreement_version: int, **overrides) -> dict:
    return get_success_data(
        api_client.create_mile_purchase_order(
            mile_purchase_order_payload(
                agreement_id, order_miles, expected_agreement_version, **overrides
            ),
            PARTNER_MANAGER,
        )
    )


def issue_order(order_id: str) -> dict:
    return get_success_data(api_client.issue_order(order_id, PARTNER_MANAGER))


def invoice_order(order_id: str) -> dict:
    return get_success_data(api_client.invoice_order(order_id, REVENUE_ACCOUNTANT))


def settle_order(order_id: str) -> dict:
    return get_success_data(api_client.settle_order(order_id, REVENUE_ACCOUNTANT))


def issued_order(agreement_id: str, order_miles: int,
                 expected_agreement_version: int, **overrides) -> dict:
    """Create the order and immediately issue the miles."""
    order = create_order(
        agreement_id, order_miles, expected_agreement_version, **overrides
    )
    return issue_order(order["id"])


# --------------------------------------------------------------------------- #
# Member accounts, elite status and the mile ledger
# --------------------------------------------------------------------------- #
def create_member(program_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_member_account(
            member_account_payload(program_id, **overrides), PROGRAM_ADMIN
        )
    )


def read_member(member_id: str, headers=PROGRAM_ADMIN) -> dict:
    return get_success_data(api_client.get_member_account(member_id, headers))


def program_with_member(program_overrides=None, member_overrides=None):
    program = create_program(**(program_overrides or {}))
    member = create_member(program["id"], **(member_overrides or {}))
    return program, member


def grant_status_match(member_id: str, matched_tier: str, trial_days: int) -> dict:
    return get_success_data(
        api_client.grant_status_match(
            member_id,
            {"matched_tier": matched_tier, "trial_days": trial_days},
            PROGRAM_ADMIN,
        )
    )


def resolve_status_match(member_id: str, outcome: str) -> dict:
    return get_success_data(
        api_client.resolve_status_match(
            member_id, {"outcome": outcome}, PROGRAM_ADMIN
        )
    )


def close_qualification_cycle(member_id: str) -> dict:
    return get_success_data(
        api_client.close_qualification_cycle(member_id, PROGRAM_ADMIN)
    )


def restate_qualification_cycle(member_id: str, reason: str) -> dict:
    return get_success_data(
        api_client.restate_qualification_cycle(
            member_id, {"reason": reason}, PROGRAM_ADMIN
        )
    )


def post_transaction(member_id: str, txn_type: str, activity_date: str,
                     headers=PROGRAM_ADMIN, **overrides) -> dict:
    return get_success_data(
        api_client.create_mile_transaction(
            mile_transaction_payload(member_id, txn_type, activity_date, **overrides),
            headers,
        )
    )


def fund_member_balance(member_id: str, miles: int, activity_date: str) -> dict:
    """Credit a member with exactly ``miles`` of spendable balance.

    A ``PARTNER_EARN`` row is used because it takes ``base_miles`` verbatim and
    credits zero qualifying miles, so the balance moves without disturbing any
    elite qualification counter.  The member must still be at ``BASE`` for the
    credited total to equal ``miles``, since a higher tier would add a bonus.
    """
    return post_transaction(
        member_id, "PARTNER_EARN", activity_date, base_miles=miles
    )


# --------------------------------------------------------------------------- #
# Promotion campaigns
# --------------------------------------------------------------------------- #
def create_campaign(program_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_promotion_campaign(
            promotion_campaign_payload(program_id, **overrides), PROGRAM_ADMIN
        )
    )


def live_campaign(program_id: str, **overrides) -> dict:
    """Schedule a campaign and let the epoch sweep move it SCHEDULED -> LIVE.

    The campaign's ``window_start`` must be at or before the clock's now for the
    sweep to launch it, so the default window opens at the startup instant.
    """
    campaign = create_campaign(program_id, **overrides)
    run_epoch(program_id)
    return get_success_data(
        api_client.get_promotion_campaign(campaign["id"], PROGRAM_ADMIN)
    )


def cancel_campaign(campaign_id: str, reason: str) -> dict:
    return get_success_data(
        api_client.cancel_promotion_campaign(
            campaign_id, {"reason": reason}, PROGRAM_ADMIN
        )
    )


# --------------------------------------------------------------------------- #
# Award inventory, holds and the booking lifecycle
# --------------------------------------------------------------------------- #
def create_window(program_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_award_inventory_window(
            award_inventory_window_payload(program_id, **overrides), PROGRAM_ADMIN
        )
    )


def read_window(window_id: str, headers=PROGRAM_ADMIN) -> dict:
    return get_success_data(
        api_client.get_award_inventory_window(window_id, headers)
    )


def pin_capacity_control(window_id: str, capacity_control_state: str) -> dict:
    return get_success_data(
        api_client.patch_capacity_control(
            window_id, {"capacity_control_state": capacity_control_state},
            PROGRAM_ADMIN,
        )
    )


def hold_seats(member_id: str, window_id: str, expected_window_version: int,
               headers=PROGRAM_ADMIN, **overrides) -> dict:
    return get_success_data(
        api_client.create_award_booking(
            award_booking_payload(
                member_id, window_id, expected_window_version, **overrides
            ),
            headers,
        )
    )


def ticket_booking(booking_id: str, headers=PROGRAM_ADMIN) -> dict:
    return get_success_data(api_client.ticket_award_booking(booking_id, headers))


def cancel_booking(booking_id: str, headers=PROGRAM_ADMIN) -> dict:
    return get_success_data(api_client.cancel_award_booking(booking_id, headers))


def refund_booking(booking_id: str) -> dict:
    return get_success_data(api_client.refund_award_booking(booking_id, PROGRAM_ADMIN))


def program_member_and_window(program_overrides=None, member_overrides=None,
                              window_overrides=None):
    """The three rows every award-pricing scenario needs."""
    program = create_program(**(program_overrides or {}))
    member = create_member(program["id"], **(member_overrides or {}))
    window = create_window(program["id"], **(window_overrides or {}))
    return program, member, window


def ticketed_booking(member_id: str, window_id: str, expected_window_version: int,
                     funding_activity_date: str, **overrides):
    """Hold seats, fund the member for exactly the quote, then ticket.

    The funding amount is only knowable after the hold has been priced, which
    is why the credit is posted between the two calls.
    """
    booking = hold_seats(
        member_id, window_id, expected_window_version, **overrides
    )
    fund_member_balance(member_id, booking["quoted_miles"], funding_activity_date)
    return ticket_booking(booking["id"])


def run_settlement(airline_id: str) -> dict:
    return get_success_data(
        api_client.create_settlement_run(airline_id, REVENUE_ACCOUNTANT)
    )


# --------------------------------------------------------------------------- #
# Programme change notices
# --------------------------------------------------------------------------- #
def draft_notice(program_id: str, change_type: str, effective_at: str,
                 expected_program_version: int, **overrides) -> dict:
    return get_success_data(
        api_client.create_program_change_notice(
            program_change_notice_payload(
                program_id, change_type, effective_at,
                expected_program_version, **overrides,
            ),
            PROGRAM_ADMIN,
        )
    )


def announce_notice(notice_id: str) -> dict:
    return get_success_data(api_client.announce_notice(notice_id, PROGRAM_ADMIN))


def rollback_notice(notice_id: str, reason: str) -> dict:
    return get_success_data(
        api_client.rollback_notice(notice_id, {"reason": reason}, PROGRAM_ADMIN)
    )


# --------------------------------------------------------------------------- #
# Fraud cases
# --------------------------------------------------------------------------- #
def open_case(member_id: str, case_type: str, headers=FRAUD_ANALYST,
              **overrides) -> dict:
    return get_success_data(
        api_client.create_fraud_case(
            fraud_case_payload(member_id, case_type, **overrides), headers
        )
    )


def investigate_case(case_id: str, headers=FRAUD_ANALYST) -> dict:
    return get_success_data(api_client.investigate_fraud_case(case_id, headers))


def substantiate_case(case_id: str, headers=FRAUD_ANALYST_2) -> dict:
    """Adjudicated by a second analyst, since the opener may not substantiate."""
    return get_success_data(api_client.substantiate_fraud_case(case_id, headers))


def dismiss_case(case_id: str, headers=FRAUD_ANALYST_2, note=None) -> dict:
    payload = {} if note is None else {"note": note}
    return get_success_data(
        api_client.dismiss_fraud_case(case_id, headers, payload)
    )


def investigating_case(member_id: str, case_type: str, **overrides) -> dict:
    """Open a case as the first analyst and move it into investigation."""
    case = open_case(member_id, case_type, **overrides)
    return investigate_case(case["id"])


# --------------------------------------------------------------------------- #
# Deferred revenue postings
# --------------------------------------------------------------------------- #
def create_posting(program_id: str, period: str, expected_program_version: int,
                   **overrides) -> dict:
    return get_success_data(
        api_client.create_deferred_revenue_posting(
            deferred_revenue_posting_payload(
                program_id, period, expected_program_version, **overrides
            ),
            REVENUE_ACCOUNTANT,
        )
    )


def posted_and_locked(program_id: str, period: str) -> dict:
    """Move OPEN -> CLOSING, post the period, then LOCKED, returning the row.

    A period cannot be locked until it carries a posting, so the posting has to
    sit between the two transitions.
    """
    transition_recognition(program_id, "CLOSING")
    program = read_program(program_id)
    posting = create_posting(program_id, period, program["version"])
    transition_recognition(program_id, "LOCKED")
    return posting


def member_headers_for(member_id: str) -> dict:
    return make_member_headers(member_id)


def issuer_headers_for(issuer_id: str) -> dict:
    return make_issuer_representative_headers(issuer_id)
