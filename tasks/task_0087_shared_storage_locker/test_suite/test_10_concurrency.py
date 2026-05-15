"""Concurrency / race-condition tests (PRD §2.10).

Only races whose loser error_id PRD §2.10 names explicitly are
asserted with a specific error_id; the rest use the binary
exactly-one-succeeds guarantee.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_exactly_one_succeeds,
    create_active_rental,
    create_insurance_claim_payload,
    create_rental_payload,
    make_renter_headers,
    run_race,
    setup_basic_rental,
    setup_cabinet_with_compartment,
    setup_returned_rental,
    setup_returned_rental_with_insurance_claim,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# Race: two renters on the same IDLE compartment (PRD §2.10)
# ===========================================================================
class TestConcurrentRentalCreation:

    def test_two_renters_serialise_one_wins_one_unavailable(self, api):
        """PRD §2.10: "Two Renter requests starting a rental on the same
        IDLE compartment serialise on the compartment's occupancy_status
        transition from IDLE to RENTED; the loser receives
        ERR_COMPARTMENT_UNAVAILABLE."

        Claim: in a binary race the loser receives
        ERR_COMPARTMENT_UNAVAILABLE.
        """
        cabinet, comps, _ = setup_cabinet_with_compartment(rental_mode="HOURLY")
        cab_id = cabinet["id"]
        comp_id = comps[0]["id"]

        def op_a():
            return api.create_rental(
                cab_id, comp_id, create_rental_payload(),
                make_renter_headers("renter-race-a"),
            )

        def op_b():
            return api.create_rental(
                cab_id, comp_id, create_rental_payload(),
                make_renter_headers("renter-race-b"),
            )

        results = run_race(op_a, op_b)
        outcomes = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcomes["failures"][0]
        validate_error(loser, ApiErrorId.ERR_COMPARTMENT_UNAVAILABLE.value)


# ===========================================================================
# Race: two insurance claims on same rental (PRD §2.10)
# ===========================================================================
class TestConcurrentInsuranceClaimCreation:

    def test_two_claims_one_succeeds_one_already_open(self, api):
        """PRD §2.10: "Two simultaneous InsuranceClaim creations against
        the same rental serialise on uniqueness of an open claim per
        rental; the loser receives ERR_CLAIM_ALREADY_OPEN."

        Claim: binary race ⇒ exactly one 2xx success and one failure
        with ERR_CLAIM_ALREADY_OPEN.
        """
        # A claim can only be filed against a returned BASIC/PREMIUM rental
        # (insurance_tier != NONE). Set one up directly.
        from test_helpers import (
            create_active_rental,
            return_rental_as_owner,
            setup_cabinet_with_compartment,
        )
        cabinet, comps, _ = setup_cabinet_with_compartment(rental_mode="HOURLY")
        rental, renter_id = create_active_rental(
            cabinet["id"], comps[0]["id"],
            renter_id="renter-claim-race-2",
            insurance_tier="BASIC",
            declared_value_cents=500_000,
        )
        return_rental_as_owner(rental, renter_id)

        def op_a():
            return api.create_insurance_claim(
                create_insurance_claim_payload(
                    rental_id=rental["id"],
                    claim_type="DAMAGE",
                    claimed_amount_cents=100_000,
                ),
                make_renter_headers(renter_id),
            )

        def op_b():
            return api.create_insurance_claim(
                create_insurance_claim_payload(
                    rental_id=rental["id"],
                    claim_type="LOSS",
                    claimed_amount_cents=100_000,
                ),
                make_renter_headers(renter_id),
            )

        results = run_race(op_a, op_b)
        outcomes = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcomes["failures"][0]
        validate_error(loser, ApiErrorId.ERR_CLAIM_ALREADY_OPEN.value)


# ===========================================================================
# Race: stale-version OCC (PRD §2.10)
# ===========================================================================
class TestConcurrentStaleVersion:

    def test_two_concurrent_renewals_with_same_version_serialise(self, api):
        """PRD §2.10: "Two concurrent writers with stale version against
        the same Rental, Cabinet, InsuranceClaim, or RepairTicket are
        serialised by the OCC check; the loser receives
        ERR_VERSION_CONFLICT."

        Claim: two renewals with the same starting version yield
        one 2xx success and one ERR_VERSION_CONFLICT.
        """
        ctx = setup_basic_rental(renter_id="renter-occ-race")
        rental = ctx["rental"]
        version = rental["version"]
        rid = rental["id"]
        headers = make_renter_headers(ctx["renter_id"])

        def op_a():
            return api.renew_rental(
                rid, {"renewal_billing_units": 1, "version": version},
                headers,
            )

        def op_b():
            return api.renew_rental(
                rid, {"renewal_billing_units": 1, "version": version},
                headers,
            )

        results = run_race(op_a, op_b)
        outcomes = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcomes["failures"][0]
        validate_error(loser, ApiErrorId.ERR_VERSION_CONFLICT.value)
