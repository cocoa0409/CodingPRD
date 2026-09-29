"""Two calls with two live failures each, where the lower rank must be the one reported.

Both pairs are declared inversions in the validation ladder: the posture check outranks the
deposit check on lease execution, and the slot-state check outranks the identity check on
booking, so an implementation that validates in the obvious order reports the wrong error.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers.api_errors import (
    ERR_DEPOSIT_NOT_FUNDED,
    ERR_HOME_LEASING_FROZEN,
    ERR_PROSPECT_IDENTITY_UNVERIFIED,
    ERR_SHOWING_SLOT_NOT_AVAILABLE,
)
from test_helpers.assertions import assert_fields, assert_money_group, failed, ok
from test_helpers.constants import (
    IDENTITY_UNVERIFIED,
    LEASE_DRAFT,
    OBLIGATION_TYPE_HOA,
    OCC_RESERVED,
    POSTURE_FROZEN,
    SEVERITY_CRITICAL,
    SLOT_BOOKED,
)


def test_frozen_posture_is_reported_ahead_of_the_unfunded_deposit(api):
    """A frozen home with a zero deposit ledger reports the posture failure.

    PRD SS2.7: "On lease execution, the posture check at rank 502 sits **below** the
    deposit-funding check at rank 602, so a lease that is both on a home whose posture is not
    `OPEN` and short on deposit reports `ERR_HOME_LEASING_FROZEN`."  PRD SS3.8 says the same
    thing from the endpoint's side: "It also demands full funding: `deposit_paid_cents` must be
    at or above `required_deposit_cents`, otherwise `ERR_DEPOSIT_NOT_FUNDED`. When both
    conditions fail at once, the posture failure is reported".

    Design: Difficulty/priority_pair_validation_conflict/lease_execute_frozen_home_beats_unfunded_deposit
    """
    ctx = x.reserved_home(api, general_template=False)
    assert_money_group(ctx.screened, total_move_in_deposit_cents=352500)
    lease = x.draft_lease(api, ctx.application_id)
    get_success_data(
        api.create_compliance_obligation(
            f.obligation_payload(
                ctx.home_id,
                OBLIGATION_TYPE_HOA,
                SEVERITY_CRITICAL,
                description="unpermitted fence cited by Peachtree HOA",
                due_on="2026-10-15",
            ),
            x.COMPLIANCE,
        )
    )

    response = api.execute_lease(lease["id"], f.execute_lease_payload(), x.AGENT)
    body = failed(response, ERR_HOME_LEASING_FROZEN)
    assert body.get("error_id") != ERR_DEPOSIT_NOT_FUNDED

    stored = ok(api.get_lease(lease["id"], x.AGENT))
    assert_fields(stored, status=LEASE_DRAFT)
    assert_money_group(stored, required_deposit_cents=352500, deposit_paid_cents=0)

    home = ok(api.get_home(ctx.home_id, x.ANALYST))
    assert_fields(home, leasing_posture=POSTURE_FROZEN, occupancy_status=OCC_RESERVED)


def test_taken_slot_is_reported_ahead_of_the_unverified_identity(api):
    """An unverified prospect booking a taken window gets the 409, not the 422.

    PRD SS2.7: "On slot booking, the slot-state check at rank 302 sits **below** the
    unverified-prospect check at rank 420, so a booking that targets an already-taken slot
    *and* comes from an unverified prospect reports `ERR_SHOWING_SLOT_NOT_AVAILABLE`, not
    `ERR_PROSPECT_IDENTITY_UNVERIFIED`."  PRD SS3.7 supplies both checks: "Booking requires the
    window's `status` to be `AVAILABLE`, and a window that is `BOOKED`, `BLOCKED_BY_POSTURE` or
    `CANCELLED` is refused with `ERR_SHOWING_SLOT_NOT_AVAILABLE`. ... It requires the
    prospect's `identity_status` to be exactly `VERIFIED`, otherwise
    `ERR_PROSPECT_IDENTITY_UNVERIFIED`".

    Design: Difficulty/priority_pair_validation_conflict/slot_book_unavailable_state_beats_unverified_identity
    """
    ctx = x.renovated_home(api, general_template=False)
    slot = x.available_slot(
        api,
        ctx.home_id,
        starts_at="2026-09-10T15:00:00Z",
        ends_at="2026-09-10T15:30:00Z",
    )
    holder = x.verified_prospect(api, ctx.market_id)
    booked = get_success_data(
        api.book_showing_slot(slot["id"], f.book_slot_payload(holder.prospect_id), holder.headers)
    )
    assert_fields(booked, status=SLOT_BOOKED)
    intruder = x.create_prospect(
        api,
        ctx.market_id,
        email="p5@example.com",
        full_name="Pedro Five",
        phone="+1-404-555-0105",
        declared_monthly_income_cents=400000,
        credit_tier="C",
    )

    response = api.book_showing_slot(
        slot["id"],
        f.book_slot_payload(intruder["id"]),
        x.make_prospect_headers(intruder["id"]),
    )
    body = failed(response, ERR_SHOWING_SLOT_NOT_AVAILABLE)
    assert body.get("error_id") != ERR_PROSPECT_IDENTITY_UNVERIFIED

    still_booked = ok(api.get_showing_slot(slot["id"], x.AGENT))
    assert_fields(still_booked, status=SLOT_BOOKED, prospect_id=holder.prospect_id)
    assert_fields(
        ok(api.get_prospect(intruder["id"], x.AGENT)), identity_status=IDENTITY_UNVERIFIED
    )
    # The design index asks for the refused booking to have left no trace on the counter.
    # ``booked_showing_count`` lives on the Home, not on the Prospect (PRD SS2.9: "For every
    # home, `booked_showing_count` always equals the number of showing windows on that home
    # whose `status` is `BOOKED`"), so the counter is checked where the PRD defines it: the one
    # window P1 holds, and nothing added by the refused call.
    assert_fields(ok(api.get_home(ctx.home_id, x.ANALYST)), booked_showing_count=1)
