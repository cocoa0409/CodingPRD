"""Gates a policy cannot satisfy on its own: the producer's appointment standing
and the hazard score of the latest completed inspection."""

from test_helpers import (
    ApiErrorId,
    bind_policy,
    bind_policy_ok,
    complete_inspection_ok,
    decide_endorsement,
    get_success_data,
    patch_agent_ok,
    read_endorsement,
    read_ledger,
    read_policy,
    read_pool,
    read_recommendations,
    reinspect,
    request_endorsement_ok,
    reservation_by_peril,
    setup_rated_dwelling_policy,
    setup_rated_policy_with_inspector,
    validate_error,
)

CRITICAL_FINDING = {
    "severity": "CRITICAL",
    "description": "Contain the fuel island spill risk",
    "due_date": "2026-09-30",
}

MINOR_FINDING = {
    "severity": "MINOR",
    "description": "Label the waste-oil drums",
    "due_date": "2026-09-30",
}


def _rated_policy_with_requested_buyback():
    """A RATED single-dwelling package with an ACTIVE inspector, one SCHEDULED
    INITIAL inspection and a REQUESTED pollution buy-back of 10000000 cents."""
    scenario = setup_rated_policy_with_inspector()
    scenario.endorsements.append(
        request_endorsement_ok(
            scenario.agent_headers,
            scenario.policy_id,
            form_code="POLLUTION_BUYBACK",
            sublimit_cents=10_000_000,
            requested_effective_date="2026-09-01",
        )
    )
    return scenario


def test_a_suspended_producer_appointment_blocks_the_bind(api):
    """"The producer on the account must have `appointment_status` `ACTIVE`, or
    `ERR_AGENT_NOT_ACTIVE`." The standing lives on the producer registry rather
    than on the policy, so suspending the agency after the quote was struck makes
    an otherwise perfect `RATED` package unbindable, and the refused call leaves
    the reservations merely `RESERVED`.

    Design: Difficulty/cross_entity_state_dependency/bind_blocked_by_suspended_producer_appointment
    """
    scenario = setup_rated_dwelling_policy()
    rated = read_policy(scenario.policy_id)
    suspended = patch_agent_ok(scenario.agent_id, appointment_status="SUSPENDED")
    assert suspended["appointment_status"] == "SUSPENDED"

    response = bind_policy(scenario.policy_id)

    validate_error(response, ApiErrorId.ERR_AGENT_NOT_ACTIVE.value, 422)

    after = read_policy(scenario.policy_id)
    assert after["uw_status"] == "RATED"
    assert after["version"] == rated["version"]
    assert after["bound_at"] is None
    assert {row["status"] for row in reservation_by_peril(scenario.policy_id).values()} == {
        "RESERVED"
    }
    hail = read_pool(scenario.hail_pool["id"])
    assert hail["committed_cents"] == 0
    assert hail["reserved_cents"] == 20_000_000


def test_reinstating_the_producer_makes_the_same_quote_bindable_again(api):
    """"A producer record may later be suspended, reinstated or re-authorised by
    supplying either or both of `appointment_status` and `authority_limit_cents`;
    the row's `version` climbs by 1 and nothing else in the system is revisited,
    because appointment standing and authority are read only at bind time."
    Nothing about the policy changed while the agency was suspended, so the
    reinstated producer binds the untouched quote and the HAIL reservation moves
    straight from reserved to committed.

    Design: Difficulty/cross_entity_state_dependency/bind_blocked_by_suspended_producer_appointment
    """
    scenario = setup_rated_dwelling_policy()
    patch_agent_ok(scenario.agent_id, appointment_status="SUSPENDED")
    bind_policy(scenario.policy_id)

    reinstated = patch_agent_ok(scenario.agent_id, appointment_status="ACTIVE")
    assert reinstated["appointment_status"] == "ACTIVE"
    assert reinstated["version"] == 3

    bound = bind_policy_ok(scenario.policy_id)

    assert bound["uw_status"] == "BOUND"
    assert bound["bound_at"].startswith("2026-08-15T00:00:00")
    assert bound["total_premium_cents"] == 269_200

    reservations = reservation_by_peril(scenario.policy_id)
    assert {row["status"] for row in reservations.values()} == {"COMMITTED"}
    hail = read_pool(scenario.hail_pool["id"])
    assert hail["committed_cents"] == 20_000_000
    assert hail["reserved_cents"] == 0


def test_the_buyback_pair_judges_existence_before_it_judges_the_hazard(api):
    """"When `requires_inspection` is true, the policy must have at least one
    inspection in `COMPLETED`, or the approval draws
    `ERR_BUYBACK_INSPECTION_REQUIRED`, and the `hazard_score` of the latest
    `COMPLETED` inspection — greatest `completed_at`, ties broken by `created_at`
    ascending — must be no greater than 35, or it draws
    `ERR_BUYBACK_HAZARD_TOO_HIGH`." With only a `SCHEDULED` visit on file the
    first error fires; once that visit completes on a `CRITICAL` finding at
    hazard 40 the second one does.

    Design: Difficulty/cross_entity_state_dependency/buyback_approval_gated_by_latest_inspection_hazard
    """
    scenario = _rated_policy_with_requested_buyback()
    endorsement_id = scenario.endorsement["id"]
    assert scenario.endorsement["requires_inspection"] is True
    assert scenario.endorsement["status"] == "REQUESTED"

    validate_error(
        decide_endorsement(endorsement_id, "APPROVE", "First attempt"),
        ApiErrorId.ERR_BUYBACK_INSPECTION_REQUIRED.value,
        422,
    )
    assert read_endorsement(endorsement_id)["status"] == "REQUESTED"

    completed = complete_inspection_ok(
        scenario.inspection["id"],
        scenario.inspector_id,
        findings_summary="Fuel island uncontained",
        findings=[CRITICAL_FINDING],
    )
    assert completed["hazard_score"] == 40

    validate_error(
        decide_endorsement(endorsement_id, "APPROVE", "Second attempt"),
        ApiErrorId.ERR_BUYBACK_HAZARD_TOO_HIGH.value,
        422,
    )

    still_requested = read_endorsement(endorsement_id)
    assert still_requested["status"] == "REQUESTED"
    assert still_requested["premium_cents"] == 0
    assert read_policy(scenario.policy_id)["total_premium_cents"] == 269_200


def test_a_cleaner_reinspection_becomes_the_latest_and_unblocks_the_buyback(api):
    """"`hazard_score` and `recommendation_count` are retained until the
    re-inspection completes, existing recommendation rows are untouched, the
    policy's `compliance_status` does not move, and the inspection's `version`
    climbs by 1." Sent back out and completed on a single `MINOR` finding, the
    visit rescores from 40 to 9 as a `RE_INSPECTION`, and because approval reads
    the latest completed visit the buy-back now prices at 150000 cents.

    Design: Difficulty/cross_entity_state_dependency/buyback_approval_gated_by_latest_inspection_hazard
    """
    scenario = _rated_policy_with_requested_buyback()
    endorsement_id = scenario.endorsement["id"]
    inspection_id = scenario.inspection["id"]
    complete_inspection_ok(
        inspection_id,
        scenario.inspector_id,
        findings_summary="Fuel island uncontained",
        findings=[CRITICAL_FINDING],
    )

    rescheduled = get_success_data(reinspect(inspection_id, scheduled_for="2026-08-18T09:00:00Z"))
    assert rescheduled["status"] == "SCHEDULED"
    assert rescheduled["inspection_type"] == "RE_INSPECTION"
    assert rescheduled["hazard_score"] == 40
    assert rescheduled["completed_at"] is None

    recompleted = complete_inspection_ok(
        inspection_id,
        scenario.inspector_id,
        findings_summary="Containment installed, drums unlabelled",
        findings=[MINOR_FINDING],
    )
    assert recompleted["hazard_score"] == 9
    assert recompleted["recommendation_count"] == 1
    assert [row["sequence_no"] for row in read_recommendations(inspection_id)] == [1, 2]

    approved = get_success_data(decide_endorsement(endorsement_id, "APPROVE", "Hazard now 9"))

    assert approved["status"] == "APPROVED"
    assert approved["premium_cents"] == 150_000

    policy = read_policy(scenario.policy_id)
    assert policy["endorsement_premium_cents"] == 150_000
    assert policy["base_premium_cents"] == 294_000
    assert policy["cat_load_cents"] == 125_200
    assert policy["total_premium_cents"] == 419_200

    ledger = read_ledger(scenario.policy_id)
    assert ledger[-1]["txn_type"] == "ENDORSEMENT_ADD"
    assert ledger[-1]["amount_cents"] == 150_000
    assert ledger[-1]["reason_code"] == "ENDORSEMENT_APPROVAL"
