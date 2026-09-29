"""Multi-hop cascades: an inspection completion reaching the ledger, and a
cancellation reaching the capacity pools."""

from test_helpers import (
    approve_endorsement_ok,
    assert_ledger_sums_to_total,
    assert_pool_capacity_identity,
    bind_policy_ok,
    cancel_policy_ok,
    complete_inspection_ok,
    ledger_by_sequence,
    read_endorsement,
    read_inspection,
    read_ledger,
    read_policy,
    read_pool,
    read_recommendations,
    request_endorsement_ok,
    reservation_by_peril,
    schedule_inspection_ok,
    setup_rated_policy_with_inspector,
)

DEFICIENCY_FINDINGS = [
    {"severity": "MAJOR", "description": "Bund the chemical store", "due_date": "2026-09-30"},
    {"severity": "MINOR", "description": "Post spray-record log", "due_date": "2026-09-30"},
]


def _policy_with_clean_inspection_and_approved_buyback():
    """A RATED policy whose first inspection completed clean — so the compliance
    axis is COMPLIANT — carrying an APPROVED pollution buy-back worth 150000."""
    scenario = setup_rated_policy_with_inspector()
    complete_inspection_ok(
        scenario.inspection["id"],
        scenario.inspector_id,
        findings_summary="No deficiencies observed",
        findings=[],
    )
    requested = request_endorsement_ok(
        scenario.agent_headers,
        scenario.policy_id,
        form_code="POLLUTION_BUYBACK",
        sublimit_cents=10_000_000,
        requested_effective_date="2026-09-01",
    )
    scenario.endorsements.append(
        approve_endorsement_ok(requested["id"], decision_note="Clean initial inspection")
    )
    scenario.inspections.append(
        schedule_inspection_ok(
            scenario.policy_id,
            scenario.inspector_id,
            scheduled_for="2026-08-17T09:00:00Z",
        )
    )
    return scenario


def test_completion_with_findings_suspends_the_buyback_through_four_hops(api):
    """"Hop three follows from the compliance axis leaving the clean states:
    every endorsement of the policy with `requires_inspection` true and `status`
    `APPROVED` is suspended." The second visit scores 10 plus 12 plus 4, raises
    two recommendations, drives the compliance axis from `COMPLIANT` back to
    `RECS_OPEN` and suspends the buy-back, whose `premium_cents` is retained on
    the row for later reinstatement.

    Design: Difficulty/transitive_cascade/inspection_completion_suspends_endorsement_and_ledger
    """
    scenario = _policy_with_clean_inspection_and_approved_buyback()
    second_inspection = scenario.inspections[1]
    assert read_policy(scenario.policy_id)["compliance_status"] == "COMPLIANT"

    completed = complete_inspection_ok(
        second_inspection["id"],
        scenario.inspector_id,
        findings_summary="Chemical storage deficiencies found",
        findings=DEFICIENCY_FINDINGS,
    )

    assert completed["status"] == "COMPLETED"
    assert completed["hazard_score"] == 26
    assert completed["recommendation_count"] == 2

    recommendations = read_recommendations(second_inspection["id"])
    assert [row["sequence_no"] for row in recommendations] == [1, 2]
    assert [row["severity"] for row in recommendations] == ["MAJOR", "MINOR"]

    assert read_policy(scenario.policy_id)["compliance_status"] == "RECS_OPEN"

    endorsement = read_endorsement(scenario.endorsement["id"])
    assert endorsement["status"] == "SUSPENDED"
    assert endorsement["premium_cents"] == 150_000


def test_the_suspension_hop_appends_a_negative_ledger_entry(api):
    """"Hop four follows from those suspensions: one `ENDORSEMENT_REMOVE` entry
    per suspended endorsement, with `amount_cents` the negation of that
    endorsement's `premium_cents` and `reason_code` `COMPLIANCE_SUSPENSION`."
    The policy falls from 419200 back to 269200, the catastrophe load is never
    recomputed, and the four-row ledger still sums to the total premium.

    Design: Difficulty/transitive_cascade/inspection_completion_suspends_endorsement_and_ledger
    """
    scenario = _policy_with_clean_inspection_and_approved_buyback()
    assert read_policy(scenario.policy_id)["total_premium_cents"] == 419_200

    complete_inspection_ok(
        scenario.inspections[1]["id"],
        scenario.inspector_id,
        findings_summary="Chemical storage deficiencies found",
        findings=DEFICIENCY_FINDINGS,
    )

    policy = read_policy(scenario.policy_id)
    assert policy["endorsement_premium_cents"] == 0
    assert policy["base_premium_cents"] == 144_000
    assert policy["cat_load_cents"] == 125_200
    assert policy["total_premium_cents"] == 269_200
    assert policy["uw_status"] == "RATED"

    ledger = read_ledger(scenario.policy_id)
    assert len(ledger) == 4
    removal = ledger_by_sequence(ledger)[4]
    assert removal["txn_type"] == "ENDORSEMENT_REMOVE"
    assert removal["reason_code"] == "COMPLIANCE_SUSPENSION"
    assert removal["amount_cents"] == -150_000
    assert_ledger_sums_to_total(ledger, policy["total_premium_cents"])


def test_cancelling_a_bound_policy_returns_committed_capacity_to_every_pool(api):
    """"The third hop follows from those rows having changed status: each
    referenced pool re-derives `committed_cents` and `available_cents` and lifts
    its `version` by 1, returning the amount to availability." All three pools
    end whole again at version 4 — one bump for creation, one for the
    reservation, one for the commitment and one for the release.

    Design: Difficulty/transitive_cascade/policy_cancel_releases_committed_capacity_to_pool
    """
    scenario = setup_rated_policy_with_inspector()
    bind_policy_ok(scenario.policy_id)

    cancelled = cancel_policy_ok(scenario.policy_id, "Insured sold the operation")

    assert cancelled["uw_status"] == "CANCELLED"
    assert cancelled["closure_reason"] == "Insured sold the operation"

    reservations = reservation_by_peril(scenario.policy_id)
    assert {row["status"] for row in reservations.values()} == {"RELEASED"}
    assert reservations["HAIL"]["amount_cents"] == 20_000_000
    assert reservations["WIND"]["amount_cents"] == 12_000_000
    assert reservations["WILDFIRE"]["amount_cents"] == 8_000_000

    for peril in ("HAIL", "WIND", "WILDFIRE"):
        pool = read_pool(scenario.pools[peril]["id"])
        assert pool["reserved_cents"] == 0
        assert pool["committed_cents"] == 0
        assert pool["available_cents"] == 200_000_000
        assert pool["version"] == 4
        assert_pool_capacity_identity(pool)

    assert read_inspection(scenario.inspection["id"])["status"] == "CANCELLED"


def test_cancellation_reverses_the_ledger_flat_in_sequence_order(api):
    """"Alongside those hops the ledger is reversed flat — one `REVERSAL` entry
    per prior non-reversed entry in `sequence_no` ascending order with
    `reason_code` `POLICY_CANCELLATION` — and every premium field is zeroed."
    The two rating entries are mirrored at sequence 3 and 4 by -144000 and
    -125200, so the ledger sums to zero.

    Design: Difficulty/transitive_cascade/policy_cancel_releases_committed_capacity_to_pool
    """
    scenario = setup_rated_policy_with_inspector()
    bind_policy_ok(scenario.policy_id)

    cancelled = cancel_policy_ok(scenario.policy_id, "Insured sold the operation")

    ledger = read_ledger(scenario.policy_id)
    assert len(ledger) == 4
    by_sequence = ledger_by_sequence(ledger)
    assert by_sequence[3]["txn_type"] == "REVERSAL"
    assert by_sequence[3]["amount_cents"] == -144_000
    assert by_sequence[3]["reverses_sequence_no"] == 1
    assert by_sequence[3]["reason_code"] == "POLICY_CANCELLATION"
    assert by_sequence[4]["txn_type"] == "REVERSAL"
    assert by_sequence[4]["amount_cents"] == -125_200
    assert by_sequence[4]["reverses_sequence_no"] == 2
    assert by_sequence[4]["reason_code"] == "POLICY_CANCELLATION"

    assert by_sequence[1]["amount_cents"] == 144_000
    assert by_sequence[2]["amount_cents"] == 125_200

    assert cancelled["total_premium_cents"] == 0
    assert_ledger_sums_to_total(ledger, 0)
