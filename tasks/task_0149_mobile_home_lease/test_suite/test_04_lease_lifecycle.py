"""Lease state machine: DRAFT, CURRENT, DELINQUENT, GRACE, TERMINATED,
ASSUMED — including sign-time preconditions and the pay action."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_lease,
    create_draft_eviction_case,
    create_lease_payload,
    create_lot,
    create_park,
    create_park_with_lot_and_lease,
    create_resident,
    create_signed_lease,
    get_lease,
    make_park_manager_headers,
    make_resident_headers,
    pay_lease,
    setup_lease_in_delinquent,
    sign_lease,
    sub_meter_billing,
    validate_error,
    validate_success,
)


# ===========================================================================
# Sign — PRD §3.2
# ===========================================================================
class TestLeaseSign:
    def test_sign_transitions_lease_to_current(self, api):
        """PRD §3.2: 'On a successful sign, the system writes the
        lease's id into the lot's current_lease_id, copies the lot's
        base_rent_cents into the lease's monthly_rent_cents, and
        transitions the lease to CURRENT.'

        Claim: after sign, lease.status == CURRENT and
        lease.monthly_rent_cents == lot.base_rent_cents.
        """
        park = create_park()
        lot = create_lot(park["id"], base_rent_cents=123_456)
        r = create_resident()
        lease = create_signed_lease(park["id"], lot["id"], r["id"])
        assert_lease(lease)
        assert lease["status"] == "CURRENT"
        assert lease["monthly_rent_cents"] == 123_456, (
            "PRD §3.2: 'copies the lot's base_rent_cents into the "
            "lease's monthly_rent_cents.'"
        )

    def test_sign_blocked_when_lot_already_has_current_lease(self, api):
        """PRD §3.2: 'the parent lot's current_lease_id must be null
        (otherwise the sign is rejected with ERR_LOT_OCCUPIED); a lot
        can carry exactly one non-terminal lease at a time.'

        Claim: signing a second draft on the same lot while a CURRENT
        lease exists → ERR_LOT_OCCUPIED.
        """
        park = create_park()
        lot = create_lot(park["id"])
        r1 = create_resident()
        r2 = create_resident()
        create_signed_lease(park["id"], lot["id"], r1["id"])
        # Second draft for a different resident on the same lot.
        draft_resp = api.create_lease(
            lot["id"],
            create_lease_payload(resident_id=r2["id"]),
            make_park_manager_headers(park["id"]),
        )
        draft = validate_success(draft_resp, expected_status=201)
        resp = api.sign_lease(
            draft["id"], make_park_manager_headers(park["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LOT_OCCUPIED.value)

    def test_sign_blocked_when_resident_has_recent_finalized_eviction(self, api):
        """PRD §3.2: 'the resident named by resident_id must have a
        violation_count_12mo of zero — a resident with a finalized-for-
        cause eviction within the prior 365 days is barred from signing
        a fresh lease.'

        Claim: a resident with violation_count_12mo > 0 attempting to
        sign a new lease → ERR_INVALID_STATE (the precondition fails).
        """
        park, lot, resident, lease = create_park_with_lot_and_lease()
        # Drive the resident into FINALIZED_FOR_CAUSE via ILLEGAL_USE.
        create_draft_eviction_case(
            park_id=park["id"], lease_id=lease["id"],
            violation_type="ILLEGAL_USE",
        )
        # Lot is now vacant (current_lease_id is null after termination).
        # Try to sign a new lease for the SAME resident.
        draft_resp = api.create_lease(
            lot["id"],
            create_lease_payload(resident_id=resident["id"]),
            make_park_manager_headers(park["id"]),
        )
        draft = validate_success(draft_resp, expected_status=201)
        resp = api.sign_lease(
            draft["id"], make_park_manager_headers(park["id"]),
        )
        # The PRD prose says the resident "is barred from signing a
        # fresh lease" but does not pin an exact error_id; the natural
        # precondition-fail surface is ERR_INVALID_STATE per PRD §2.10
        # priority 6.
        from prd_bench_local_runner.testing import validate_error_is_one_of
        validate_error_is_one_of(
            resp,
            [
                ApiErrorId.ERR_INVALID_STATE.value,
            ],
        )


# ===========================================================================
# DELINQUENT cycle — PRD §3.3, §3.4
# ===========================================================================
class TestDelinquentAndPay:
    def test_billing_sweep_pushes_lease_with_balance_to_delinquent(self, api):
        """PRD §3.3: 'Any lease that was CURRENT and whose recomputed
        balance is strictly greater than zero transitions to
        DELINQUENT.'

        Claim: after /_sweep/billing leaves outstanding_balance_cents
        > 0, the lease's status is DELINQUENT.
        """
        park, lot, resident, lease, bills = setup_lease_in_delinquent(
            master_total_cents=5000,
        )
        assert lease["status"] == "DELINQUENT"
        assert lease["outstanding_balance_cents"] > 0

    def test_pay_clears_balance_and_returns_to_current(self, api):
        """PRD §3.4: 'A Resident clears their delinquency by invoking
        the pay action on their lease. The endpoint takes no body
        parameters: the system marks every previously unpaid
        UtilityBill for the lease with the current logical-clock
        timestamp in paid_at, recomputes the lease's
        outstanding_balance_cents (which drops to zero given that all
        bills are now paid), and cascades the lease's state. A lease
        that was DELINQUENT transitions to CURRENT.'

        Claim: pay on DELINQUENT → outstanding == 0 and status ==
        CURRENT.
        """
        park, lot, resident, lease, bills = setup_lease_in_delinquent(
            master_total_cents=5000,
        )
        paid = pay_lease(resident["id"], lease["id"])
        refreshed = get_lease(lease["id"])
        assert refreshed["outstanding_balance_cents"] == 0
        assert refreshed["status"] == "CURRENT"

    def test_resident_cannot_pay_someone_elses_lease(self, api):
        """PRD §2.1: 'Resident-only mutations (paying a lease, curing
        an eviction, accepting or rejecting a conversion offer)
        additionally require the acting Resident to match the resource
        owner; mismatch is rejected with ERR_FORBIDDEN_NOT_OWNER.'

        Claim: a Resident calling POST /leases/{id}/pay on a lease
        whose resident_id != X-User-ID → ERR_FORBIDDEN_NOT_OWNER.
        """
        park, lot, resident, lease, bills = setup_lease_in_delinquent()
        intruder = create_resident()
        resp = api.pay_lease(lease["id"], make_resident_headers(intruder["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_NOT_OWNER.value)
