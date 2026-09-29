"""Composite setup helpers.

Every helper builds its preconditions from scratch through the documented
endpoints, because each test starts against an empty database. Ownership-gated
calls always thread the entity-backed identity: a ``Member``'s own id for the
``Member`` role and the ``Park``'s own id for the ``ParkManager`` role.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import DEFAULT_CLOCK_UTC, clock_instant, shift_days
from .factories import (
    make_affiliate_agreement_payload,
    make_agreement_status_change_payload,
    make_amenity_inspection_payload,
    make_annual_dues_run_payload,
    make_capital_decision_payload,
    make_capital_project_payload,
    make_check_out_payload,
    make_classic_tier_payload,
    make_exception_decision_payload,
    make_extension_payload,
    make_maintenance_window_payload,
    make_member_payload,
    make_membership_payload,
    make_membership_tier_payload,
    make_park_payload,
    make_payment_payload,
    make_payment_reversal_payload,
    make_president_tier_payload,
    make_reinstatement_payload,
    make_reinvestment_run_payload,
    make_reservation_payload,
    make_satisfaction_survey_payload,
    make_suspension_payload,
    make_transfer_decision_payload,
    make_transfer_request_payload,
    make_transient_reservation_payload,
)
from .test_users import (
    CLUB_ADMIN_PRIMARY_ID,
    CLUB_ADMIN_SECONDARY_ID,
    TEST_USERS,
    make_compliance_officer_headers,
    make_member_headers,
    make_park_manager_headers,
    make_transient_guest_headers,
)

ADMIN = TEST_USERS["club_admin_headers"]
ADMIN_2 = TEST_USERS["club_admin_secondary_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
GUEST = TEST_USERS["transient_guest_headers"]


# ===========================================================================
# Tier 1 — logical clock and single-row creation
# ===========================================================================


def set_clock(api: ApiClient, instant: str) -> str:
    """Move the logical clock to an instant, or to a bare date at midnight."""
    if len(instant) == 10:
        instant = clock_instant(instant)
    data = get_success_data(api.set_clock(instant))
    return data["current_utc"]


def reset_clock(api: ApiClient) -> str:
    """Return the clock to the value it holds before any client sets it."""
    return set_clock(api, DEFAULT_CLOCK_UTC)


def create_tier(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_membership_tier(make_membership_tier_payload(**overrides), ADMIN)
    )


def create_classic_tier(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Rank 1, 42,000 cents annual dues, no affiliate access, resale refused."""
    return get_success_data(
        api.create_membership_tier(make_classic_tier_payload(**overrides), ADMIN)
    )


def create_president_tier(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Rank 3, 58,000 cents annual dues, affiliate access and resale allowed."""
    return get_success_data(
        api.create_membership_tier(make_president_tier_payload(**overrides), ADMIN)
    )


def create_member(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_member(make_member_payload(**overrides), ADMIN))


def sell_membership(
    api: ApiClient, member_id: str, tier_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_membership(make_membership_payload(member_id, tier_id, **overrides), ADMIN)
    )


def create_park(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_park(make_park_payload(**overrides), ADMIN))


def create_affiliate_agreement(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_affiliate_agreement(make_affiliate_agreement_payload(**overrides), ADMIN)
    )


# ===========================================================================
# Tier 2 — entity hierarchies
# ===========================================================================


def sell_membership_to_new_member(
    api: ApiClient, tier_id: str, member_overrides: Optional[Dict[str, Any]] = None, **overrides: Any
) -> Dict[str, Any]:
    """Register a person, sell them a contract, and return the whole bundle.

    The bundle carries ``headers`` built from the ``Member`` row's own id, which
    is what every ownership-gated member call must present.
    """
    member = create_member(api, **(member_overrides or {}))
    membership = sell_membership(api, member["id"], tier_id, **overrides)
    invoices = list_invoices(api, membership["id"])
    return {
        "member": member,
        "member_id": member["id"],
        "membership": membership,
        "membership_id": membership["id"],
        "headers": make_member_headers(member["id"]),
        "invoice": invoices[0] if invoices else None,
        "invoice_id": invoices[0]["id"] if invoices else None,
    }


def list_invoices(
    api: ApiClient, membership_id: str, params: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    return get_success_data(api.list_membership_dues_invoices(membership_id, ADMIN, params))


def read_membership(api: ApiClient, membership_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_membership(membership_id, ADMIN))


def read_park(api: ApiClient, park_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_park(park_id, ADMIN))


def read_reservation(api: ApiClient, reservation_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_reservation(reservation_id, ADMIN))


def read_invoice(api: ApiClient, invoice_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_dues_invoice(invoice_id, ADMIN))


def read_project(api: ApiClient, project_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_capital_project(project_id, ADMIN))


def read_agreement(api: ApiClient, agreement_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_affiliate_agreement(agreement_id, ADMIN))


def open_park(api: ApiClient, park_id: str) -> Dict[str, Any]:
    """Advance a park from SEASONAL_CLOSED to OPEN as its own park manager."""
    return get_success_data(api.open_park_season(park_id, make_park_manager_headers(park_id)))


def create_open_park(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """A park is not open for business when created, so open it immediately."""
    park = create_park(api, **overrides)
    return open_park(api, park["id"])


def activate_agreement(api: ApiClient, agreement_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.change_affiliate_agreement_status(
            agreement_id, make_agreement_status_change_payload("ACTIVE"), ADMIN
        )
    )


def create_active_agreement(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """A newly registered agreement opens in DRAFT; move it to ACTIVE."""
    agreement = create_affiliate_agreement(api, **overrides)
    return activate_agreement(api, agreement["id"])


def create_affiliate_open_park(
    api: ApiClient, agreement_id: str, **overrides: Any
) -> Dict[str, Any]:
    overrides.setdefault("affiliate_agreement_id", agreement_id)
    return create_open_park(api, **overrides)


# ===========================================================================
# Tier 3 — reservation lifecycle shortcuts
# ===========================================================================


def book_member_stay(
    api: ApiClient,
    member_headers: Dict[str, str],
    park_id: str,
    membership_id: str,
    arrival_date: str,
    scheduled_departure_date: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a member booking; the CONFIRMED / WAITLISTED fork is resolved here."""
    return get_success_data(
        api.create_reservation(
            make_reservation_payload(
                park_id, membership_id, arrival_date, scheduled_departure_date, **overrides
            ),
            member_headers,
        )
    )


def book_transient_stay(
    api: ApiClient,
    park_id: str,
    arrival_date: str,
    scheduled_departure_date: str,
    guest_headers: Optional[Dict[str, str]] = None,
    guest_name: str = "Walk-in Guest",
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_transient_reservation(
            make_transient_reservation_payload(
                park_id, arrival_date, scheduled_departure_date, guest_name, **overrides
            ),
            guest_headers or GUEST,
        )
    )


def check_in(
    api: ApiClient, reservation_id: str, headers: Dict[str, str], at_instant: Optional[str] = None
) -> Dict[str, Any]:
    """Move a CONFIRMED stay to CHECKED_IN, optionally at a given clock instant."""
    if at_instant is not None:
        set_clock(api, at_instant)
    return get_success_data(api.check_in_reservation(reservation_id, headers))


def check_out(
    api: ApiClient,
    reservation_id: str,
    headers: Dict[str, str],
    actual_departure_date: str,
    at_instant: Optional[str] = None,
) -> Dict[str, Any]:
    if at_instant is not None:
        set_clock(api, at_instant)
    return get_success_data(
        api.check_out_reservation(
            reservation_id, make_check_out_payload(actual_departure_date), headers
        )
    )


def extend(
    api: ApiClient,
    reservation_id: str,
    headers: Dict[str, str],
    new_departure_date: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.extend_reservation(
            reservation_id, make_extension_payload(new_departure_date, **overrides), headers
        )
    )


def cancel(api: ApiClient, reservation_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(api.cancel_reservation(reservation_id, headers))


def completed_stay(
    api: ApiClient,
    member_headers: Dict[str, str],
    park_id: str,
    membership_id: str,
    arrival_date: str,
    departure_date: str,
    check_in_instant: Optional[str] = None,
    check_out_instant: Optional[str] = None,
) -> Dict[str, Any]:
    """Book, arrive and depart on time so the stay lands in COMPLETED."""
    reservation = book_member_stay(
        api, member_headers, park_id, membership_id, arrival_date, departure_date
    )
    check_in(api, reservation["id"], member_headers, check_in_instant or arrival_date)
    return check_out(
        api,
        reservation["id"],
        member_headers,
        departure_date,
        check_out_instant or departure_date,
    )


def submit_survey(
    api: ApiClient,
    reservation_id: str,
    member_headers: Dict[str, str],
    **ratings: Any,
) -> Dict[str, Any]:
    """File the one satisfaction survey a COMPLETED stay permits."""
    return get_success_data(
        api.submit_satisfaction_survey(
            reservation_id, make_satisfaction_survey_payload(**ratings), member_headers
        )
    )


def list_reservation_exceptions(
    api: ApiClient, reservation_id: str, params: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    return get_success_data(api.list_reservation_occupancy_exceptions(reservation_id, ADMIN, params))


def decide_exception(
    api: ApiClient,
    exception_id: str,
    decision: str,
    officer_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.decide_occupancy_exception(
            exception_id,
            make_exception_decision_payload(decision, **overrides),
            officer_headers or OFFICER,
        )
    )


# ===========================================================================
# Tier 4 — accumulation and threshold targeting
# ===========================================================================


def pay_invoice_in_full(
    api: ApiClient, invoice_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Tender exactly the outstanding balance: amount plus late fee less paid."""
    invoice = read_invoice(api, invoice_id)
    outstanding = (
        invoice["amount_cents"] + invoice["late_fee_cents"] - invoice["paid_amount_cents"]
    )
    return get_success_data(
        api.pay_dues_invoice(invoice_id, make_payment_payload(outstanding), headers or ADMIN)
    )


def reverse_payment(api: ApiClient, invoice_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.reverse_dues_payment(invoice_id, make_payment_reversal_payload(**overrides), ADMIN)
    )


def run_delinquency_sweep(api: ApiClient, at_instant: Optional[str] = None) -> Dict[str, Any]:
    """Age every OPEN or PAST_DUE invoice against the current logical date."""
    if at_instant is not None:
        set_clock(api, at_instant)
    return get_success_data(api.run_dues_delinquency(ADMIN))


def run_annual_dues(
    api: ApiClient, cycle_year: int, at_instant: Optional[str] = None
) -> Dict[str, Any]:
    if at_instant is not None:
        set_clock(api, at_instant)
    return get_success_data(api.run_annual_dues(make_annual_dues_run_payload(cycle_year), ADMIN))


def suspend_membership(
    api: ApiClient, membership_id: str, suspension_reason: str = "ADMIN_ACTION"
) -> Dict[str, Any]:
    return get_success_data(
        api.suspend_membership(
            membership_id, make_suspension_payload(suspension_reason=suspension_reason), ADMIN
        )
    )


def reinstate_membership(
    api: ApiClient, membership_id: str, reinstatement_fee_paid_cents: int = 15000
) -> Dict[str, Any]:
    return get_success_data(
        api.reinstate_membership(
            membership_id,
            make_reinstatement_payload(reinstatement_fee_paid_cents=reinstatement_fee_paid_cents),
            ADMIN,
        )
    )


def age_membership_into_grace(
    api: ApiClient, sweep_instant: str, membership_id: str
) -> Dict[str, Any]:
    """Sweep at an instant past the due date so the billing axis reaches GRACE."""
    run_delinquency_sweep(api, sweep_instant)
    return read_membership(api, membership_id)


def schedule_window(
    api: ApiClient, park_id: str, start_date: str, end_date: str, **overrides: Any
) -> Dict[str, Any]:
    """Schedule maintenance as the park's own manager."""
    return get_success_data(
        api.create_maintenance_window(
            make_maintenance_window_payload(park_id, start_date, end_date, **overrides),
            make_park_manager_headers(park_id),
        )
    )


def activate_window(api: ApiClient, park_id: str, window_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.activate_maintenance_window(window_id, make_park_manager_headers(park_id))
    )


def complete_window(api: ApiClient, park_id: str, window_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.complete_maintenance_window(window_id, make_park_manager_headers(park_id))
    )


def file_inspection(
    api: ApiClient,
    park_id: str,
    headers: Optional[Dict[str, str]] = None,
    **scores: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.file_amenity_inspection(
            park_id,
            make_amenity_inspection_payload(**scores),
            headers or make_park_manager_headers(park_id),
        )
    )


def propose_project(
    api: ApiClient,
    park_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Propose capital work; requested_by_user_id is taken from the proposer."""
    return get_success_data(
        api.create_capital_project(
            make_capital_project_payload(park_id, **overrides), headers or ADMIN
        )
    )


def decide_project(
    api: ApiClient,
    project_id: str,
    park_id: str,
    decision: str = "APPROVE",
    decider_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Decide a project against the park's current version, as a second operator."""
    park = read_park(api, park_id)
    return get_success_data(
        api.decide_capital_project(
            project_id,
            make_capital_decision_payload(decision, park["version"], **overrides),
            decider_headers or ADMIN_2,
        )
    )


def approved_project(
    api: ApiClient,
    park_id: str,
    proposer_headers: Optional[Dict[str, str]] = None,
    decider_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Propose then approve, so the project sits in the funding queue."""
    project = propose_project(api, park_id, proposer_headers or ADMIN, **overrides)
    return decide_project(
        api, project["id"], park_id, "APPROVE", decider_headers or ADMIN_2
    )


def run_reinvestment(
    api: ApiClient, fiscal_year: int, budget_cents: int
) -> Dict[str, Any]:
    return get_success_data(
        api.run_reinvestment(make_reinvestment_run_payload(fiscal_year, budget_cents), ADMIN)
    )


# ===========================================================================
# Tier 5 — transfers, succession and terminal states
# ===========================================================================


def submit_transfer(
    api: ApiClient,
    submitter_headers: Dict[str, str],
    membership_id: str,
    to_member_id: str,
    transfer_type: str = "GIFT",
    expected_membership_version: Optional[int] = None,
    api_for_read: Optional[ApiClient] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Submit a transfer pinned to the membership version the client just read."""
    if expected_membership_version is None:
        expected_membership_version = read_membership(api_for_read or api, membership_id)["version"]
    return get_success_data(
        api.create_transfer_request(
            make_transfer_request_payload(
                membership_id,
                to_member_id,
                transfer_type,
                expected_membership_version,
                **overrides,
            ),
            submitter_headers,
        )
    )


def decide_transfer(
    api: ApiClient,
    request_id: str,
    decision: str = "APPROVE",
    decider_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Decide a transfer as an operator other than the one who submitted it."""
    return get_success_data(
        api.decide_transfer_request(
            request_id,
            make_transfer_decision_payload(decision, **overrides),
            decider_headers or ADMIN,
        )
    )


def transfer_membership(
    api: ApiClient,
    membership_id: str,
    submitter_headers: Dict[str, str],
    to_member_id: str,
    transfer_type: str = "GIFT",
    **overrides: Any,
) -> Dict[str, Any]:
    """Submit and approve a transfer, returning the request and the successor."""
    request = submit_transfer(
        api, submitter_headers, membership_id, to_member_id, transfer_type, **overrides
    )
    decided = decide_transfer(api, request["id"], "APPROVE", ADMIN)
    successor_id = decided.get("successor_membership_id")
    return {
        "request": decided,
        "successor_membership_id": successor_id,
        "successor": read_membership(api, successor_id) if successor_id else None,
        "source": read_membership(api, membership_id),
    }


def terminated_membership_via_transfer(
    api: ApiClient, tier_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Drive a contract to the terminal TERMINATED state through an approval."""
    holder = sell_membership_to_new_member(api, tier_id, **overrides)
    recipient = create_member(api)
    outcome = transfer_membership(
        api, holder["membership_id"], holder["headers"], recipient["id"], "GIFT"
    )
    return {
        "holder": holder,
        "recipient": recipient,
        "outcome": outcome,
        "source": outcome["source"],
        "successor": outcome["successor"],
    }


# ===========================================================================
# Convenience bundles that several recipes reuse verbatim
# ===========================================================================


def classic_holder_at_open_park(
    api: ApiClient,
    park_overrides: Optional[Dict[str, Any]] = None,
    tier_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A CLASSIC contract plus one OPEN park, the commonest starting point."""
    tier = create_classic_tier(api, **(tier_overrides or {}))
    park = create_open_park(api, **(park_overrides or {}))
    holder = sell_membership_to_new_member(api, tier["id"])
    return {"tier": tier, "park": park, "park_id": park["id"], **holder}


def president_holder_at_open_park(
    api: ApiClient,
    park_overrides: Optional[Dict[str, Any]] = None,
    tier_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A PRESIDENT contract plus one OPEN park, for affiliate and CLASS_A work."""
    tier = create_president_tier(api, **(tier_overrides or {}))
    park = create_open_park(api, **(park_overrides or {}))
    holder = sell_membership_to_new_member(api, tier["id"])
    return {"tier": tier, "park": park, "park_id": park["id"], **holder}


def find_by_id(rows: List[Dict[str, Any]], row_id: str) -> Dict[str, Any]:
    """Pick one row out of a list response by id, failing loudly when absent."""
    for row in rows:
        if row.get("id") == row_id:
            return row
    raise AssertionError(f"row {row_id} not present in the returned collection")


def shift(day: str, days: int) -> str:
    """Small re-export so recipes can express dates relative to the clock."""
    return shift_days(day, days)
