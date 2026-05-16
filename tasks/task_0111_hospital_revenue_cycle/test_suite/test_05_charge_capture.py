"""Charge capture: create, post, void, CPT validation, and lock rules.

Covers PRD §3.4.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    add_and_post_charge,
    add_charge,
    assert_charge_item,
    create_charge_payload,
    finalize_coding,
    post_charge,
    re_get_encounter,
    setup_charges_captured_encounter,
    setup_coded_encounter,
    setup_eligibility_verified_encounter,
    setup_registered_encounter,
    validate_error,
    validate_success,
    void_charge,
)


# ===========================================================================
# §3.4 ChargeItem creation
# ===========================================================================
class TestChargeCreation:
    """PRD §3.4: A ChargeCaptureClerk records individual services."""

    def test_create_charge_pins_amount_cents(self, api):
        """PRD §3.4: "The server pins the line's `amount_cents` on creation as the product of `quantity` and `unit_price_cents`; this value is immutable thereafter."

        Claim: a created ChargeItem carries amount_cents == quantity *
        unit_price_cents.
        """
        patient, policy, encounter = setup_eligibility_verified_encounter()
        res = api.create_charge(
            encounter["id"],
            create_charge_payload(quantity=3, unit_price_cents=4567),
            TEST_USERS["charge_capture_clerk_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert_charge_item(data)
        assert data["amount_cents"] == 3 * 4567
        assert data["status"] == "PENDING"
        assert data.get("posted_at") is None

    def test_create_charge_with_invalid_cpt_rejected(self, api):
        """PRD §3.4: "A `cpt_code` that is not exactly five digits long is rejected with `ERR_INVALID_CPT`."

        Claim: a 4-digit cpt_code returns ERR_INVALID_CPT.
        """
        patient, policy, encounter = setup_eligibility_verified_encounter()
        res = api.create_charge(
            encounter["id"],
            create_charge_payload(cpt_code="9921"),
            TEST_USERS["charge_capture_clerk_headers"],
        )
        validate_error(res, "ERR_INVALID_CPT")

    def test_create_charge_with_alpha_cpt_rejected(self, api):
        """PRD §3.4: "A `cpt_code` that is not exactly five digits long is rejected with `ERR_INVALID_CPT`."

        Claim: a cpt_code containing non-digit characters returns
        ERR_INVALID_CPT.
        """
        patient, policy, encounter = setup_eligibility_verified_encounter()
        res = api.create_charge(
            encounter["id"],
            create_charge_payload(cpt_code="9921A"),
            TEST_USERS["charge_capture_clerk_headers"],
        )
        validate_error(res, "ERR_INVALID_CPT")

    def test_create_charge_with_6_digit_cpt_rejected(self, api):
        """PRD §3.4: "A `cpt_code` that is not exactly five digits long is rejected with `ERR_INVALID_CPT`."

        Claim: a 6-digit cpt_code returns ERR_INVALID_CPT.
        """
        patient, policy, encounter = setup_eligibility_verified_encounter()
        res = api.create_charge(
            encounter["id"],
            create_charge_payload(cpt_code="992133"),
            TEST_USERS["charge_capture_clerk_headers"],
        )
        validate_error(res, "ERR_INVALID_CPT")


# ===========================================================================
# §3.4 Posting a charge
# ===========================================================================
class TestChargePost:
    """PRD §3.4: posting a PENDING charge advances it to POSTED."""

    def test_post_pending_charge_to_posted(self, api):
        """PRD §3.4: "**Posting** a pending charge — advancing it from `PENDING` to `POSTED` — stamps the line's `posted_at` and is permitted only while the encounter is in `ELIGIBILITY_VERIFIED`"

        Claim: posting a PENDING charge transitions it to POSTED and
        stamps posted_at.
        """
        patient, policy, encounter = setup_eligibility_verified_encounter()
        charge = add_charge(encounter=encounter)
        res = api.post_charge(
            encounter["id"], charge["id"],
            TEST_USERS["charge_capture_clerk_headers"],
        )
        data = validate_success(res)
        assert data["status"] == "POSTED"
        assert data.get("posted_at") is not None

    def test_post_updates_total_charges_cents(self, api):
        """PRD §3.4: "Posting triggers `charge_total_aggregation` to refresh the encounter's `total_charges_cents` (now including this newly posted line)"

        Claim: after posting a charge with amount_cents=N, the
        encounter's total_charges_cents == N.
        """
        patient, policy, encounter = setup_eligibility_verified_encounter()
        charge = add_charge(
            encounter=encounter, quantity=2, unit_price_cents=5000,
        )
        api.post_charge(
            encounter["id"], charge["id"],
            TEST_USERS["charge_capture_clerk_headers"],
        )
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["total_charges_cents"] == 2 * 5000


# ===========================================================================
# §3.4 Voiding charges
# ===========================================================================
class TestChargeVoid:
    """PRD §3.4: voiding a charge sets status to VOIDED."""

    def test_void_pending_charge_does_not_change_total(self, api):
        """PRD §3.4: "When voiding a `POSTED` line, both `charge_total_aggregation` and the estimate refresh run; when voiding a `PENDING` line, neither runs because pending lines were never counted in the aggregate."

        Claim: voiding a PENDING (never-posted) line leaves
        total_charges_cents unchanged at 0.
        """
        patient, policy, encounter = setup_eligibility_verified_encounter()
        charge = add_charge(encounter=encounter)
        api.void_charge(
            encounter["id"], charge["id"],
            TEST_USERS["charge_capture_clerk_headers"],
        )
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["total_charges_cents"] == 0

    def test_void_posted_charge_decrements_total(self, api):
        """PRD §3.4: "When voiding a `POSTED` line, both `charge_total_aggregation` and the estimate refresh run"

        Claim: voiding a previously-POSTED line removes its
        amount_cents from total_charges_cents.
        """
        patient, policy, encounter = setup_eligibility_verified_encounter()
        charge = add_and_post_charge(
            encounter=encounter, unit_price_cents=12_345,
        )
        # Confirm total reflects the post.
        mid = re_get_encounter(encounter["id"])
        assert mid["total_charges_cents"] == 12_345
        # Now void.
        api.void_charge(
            encounter["id"], charge["id"],
            TEST_USERS["charge_capture_clerk_headers"],
        )
        after = re_get_encounter(encounter["id"])
        assert after["total_charges_cents"] == 0

    def test_void_posted_charge_after_finalized_coding_rejected(self, api):
        """PRD §3.4: "Voiding a previously-`POSTED` line additionally requires that no `FINALIZED` coding record exist for the encounter — once coding has been locked, the charge ledger is locked too."

        Claim: voiding a POSTED charge after the encounter's coding is
        FINALIZED returns ERR_INVALID_STATE.
        """
        # Build a CODED encounter (which means coding is FINALIZED).
        patient, policy, encounter, posted = setup_coded_encounter()
        assert encounter["status"] == "CODED"
        charge = posted[0]
        res = api.void_charge(
            encounter["id"], charge["id"],
            TEST_USERS["charge_capture_clerk_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# §3.4 State guards on charge operations
# ===========================================================================
class TestChargeStateGuards:
    """PRD §3.4: charge operations are guarded by encounter status."""

    def test_create_charge_before_eligibility_verified_rejected(self, api):
        """PRD §3.4: "Once the encounter is in `ELIGIBILITY_VERIFIED`, a `ChargeCaptureClerk` begins recording individual services."

        Claim: creating a charge on a REGISTERED encounter returns
        ERR_INVALID_STATE.
        """
        patient, policy, encounter = setup_registered_encounter()
        res = api.create_charge(
            encounter["id"], create_charge_payload(),
            TEST_USERS["charge_capture_clerk_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_post_charge_after_charges_captured_rejected(self, api):
        """PRD §3.4: "**Posting** a pending charge — advancing it from `PENDING` to `POSTED` — stamps the line's `posted_at` and is permitted only while the encounter is in `ELIGIBILITY_VERIFIED`"

        Claim: posting a PENDING charge after discharge (encounter is
        CHARGES_CAPTURED) returns ERR_INVALID_STATE. We arrange this by
        creating a PENDING charge that survives discharge. (PRD §3.6
        actually says discharge requires zero PENDING items, so an
        encounter cannot enter CHARGES_CAPTURED with a leftover
        PENDING. Instead we attempt the post on a CHARGES_CAPTURED
        encounter — its only charge is already POSTED — and observe
        ERR_INVALID_STATE because re-posting a POSTED line is itself a
        state-illegal transition under the PENDING→POSTED rule.)
        """
        patient, policy, encounter, posted = (
            setup_charges_captured_encounter()
        )
        charge = posted[0]  # already POSTED
        res = api.post_charge(
            encounter["id"], charge["id"],
            TEST_USERS["charge_capture_clerk_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")
