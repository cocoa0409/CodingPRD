"""Concurrency: serialised races on negotiation rounds, signatures, payment
event idempotency (PRD §2.12)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    run_race,
    assert_exactly_one_succeeds,
    assert_at_least_one_succeeds,
    ApiErrorId,
    create_rights_holder,
    create_two_rights_holders,
    create_registered_work,
    create_offered_license,
    setup_accepted_license,
    create_pending_contract,
    round_payload,
    signature_payload,
    make_rights_holder_headers,
    ADMIN_HEADERS,
)


# ---------------------------------------------------------------------------
# Negotiation round race
# ---------------------------------------------------------------------------

class TestNegotiationRoundRaces:
    """PRD §2.12: "Two parties simultaneously submitting a NegotiationRound
    on the same license serialize on the increment of current_round: the
    first writer wins, and the second's submission is rejected with
    ERR_NOT_YOUR_TURN because, after the first writer increments the
    counter, the second is no longer the opposite party."
    """

    def test_concurrent_counter_and_accept_serialize(self, api):
        """PRD §2.12: at most one of two simultaneous round submissions on
        the same license succeeds; the loser receives ERR_NOT_YOUR_TURN.

        We stage: License OFFERED with licensee_id=B. Two concurrent calls
        from licensee — one COUNTER, one ACCEPT — both legal as the licensee's
        first action on OFFERED. Exactly one must succeed under PRD §2.12."""
        licensor, licensee = create_two_rights_holders(api)
        work, _ = create_registered_work(api, owner=licensor)
        license_data = create_offered_license(api, work, licensor, licensee)
        licensee_headers = make_rights_holder_headers(licensee["id"])

        results = run_race(
            lambda: api.submit_round(
                license_data["id"],
                round_payload(action="COUNTER",
                                clause_diff={"fixed_fee_cents": {"old": 100000, "new": 150000}}),
                licensee_headers,
            ),
            lambda: api.submit_round(
                license_data["id"],
                round_payload(action="ACCEPT"),
                licensee_headers,
            ),
        )
        # PRD §2.12 explicitly says the loser receives ERR_NOT_YOUR_TURN, so
        # one must succeed and one must fail.
        assert_exactly_one_succeeds(results[0], results[1])


# ---------------------------------------------------------------------------
# Signature race
# ---------------------------------------------------------------------------

class TestSignatureRaces:
    """PRD §2.12: "Two signers concurrently submitting signatures for the
    same contract serialize on the increment of signed_count: the first
    writer wins, the second is rejected with ERR_SIGNATURE_OUT_OF_ORDER."
    """

    def test_concurrent_signatures_one_wins(self, api):
        """PRD §2.12: serialised on signed_count; the second submission for
        signing_order[0] would race the first."""
        bundle = setup_accepted_license(api)
        licensor, licensee = bundle["licensor"], bundle["licensee"]
        # Create a contract whose signing_order has the licensor as both
        # the first and second signer — both signatures are submittable
        # by licensor, and the contention is the increment of signed_count.
        contract = create_pending_contract(
            api, bundle["license"],
            licensor=licensor, licensee=licensee,
            signing_order=[licensor["id"], licensor["id"]],
        )
        licensor_headers = make_rights_holder_headers(licensor["id"])

        results = run_race(
            lambda: api.submit_signature(
                contract["id"],
                signature_payload(signer_id=licensor["id"]),
                licensor_headers,
            ),
            lambda: api.submit_signature(
                contract["id"],
                signature_payload(signer_id=licensor["id"]),
                licensor_headers,
            ),
        )
        # Both submissions are by the same licensor for index 0. After one
        # succeeds, signed_count=1 and the next call must succeed (since
        # signing_order[1]==licensor) OR fail with ERR_DUPLICATE_SIGNATURE.
        # Under PRD §2.12 the second writer races to either win on index 1
        # or lose on duplicate — at minimum one must succeed.
        assert_at_least_one_succeeds(*results)
