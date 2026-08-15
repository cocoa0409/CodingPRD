"""Queue B corner tests: OCC stale-version rules, derived-field reconciliation,
immediate read-after-write consistency."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_participant_headers,
    create_active_recordkeeper,
    create_plan,
    create_participant,
    create_open_batch,
    create_case,
    setup_notified_case,
    submit_election,
)

OPS = TEST_USERS["provider_ops_headers"]
SPONSOR = TEST_USERS["plan_sponsor_headers"]


def test_occ_election_stale_version():
    """PRD §2.7: "Submitting an election against a case requires `expected_case_version`
    equal to the case's current `version`." and "the request is rejected with
    `ERR_STALE_VERSION` and HTTP status 412"
    PRD §3.4: "any earlier `SUBMITTED` election of the same case is simultaneously
    superseded to `SUPERSEDED`, so at most one `SUBMITTED` election exists per case at any
    time. Each election submission increments the case's `version` — which is precisely why
    a client holding an older case version must re-read before its election is accepted."

    Design: Corner/complexity_layers/occ_election_stale_version
    """
    ctx = setup_notified_case(balance=50000)
    case_id = ctx["case"]["id"]
    p_id = ctx["participant"]["id"]
    case = get_success_data(api_client.get_distribution_case(case_id, OPS))
    v1 = case["version"]

    # First election at the observed version succeeds.
    el1 = validate_success(api_client.create_election(
        case_id,
        {"election_type": "LUMP_SUM_CASH", "expected_case_version": v1},
        make_participant_headers(p_id),
    ), 201)
    case = get_success_data(api_client.get_distribution_case(case_id, OPS))
    assert case["version"] > v1

    # Replaying the stale version is rejected 412; no second election is written.
    res = api_client.create_election(
        case_id,
        {"election_type": "SAFE_HARBOR_IRA", "expected_case_version": v1},
        make_participant_headers(p_id),
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, 412)

    # Re-reading and resubmitting succeeds and supersedes the first election.
    v2 = get_success_data(api_client.get_distribution_case(case_id, OPS))["version"]
    el2 = validate_success(api_client.create_election(
        case_id,
        {"election_type": "SAFE_HARBOR_IRA", "expected_case_version": v2},
        make_participant_headers(p_id),
    ), 201)
    el1_after = get_success_data(api_client.get_election(el1["id"], OPS))
    assert el1_after["election_status"] == "SUPERSEDED"
    assert el2["election_status"] == "SUBMITTED"


def test_occ_plan_patch_stale_version():
    """PRD §2.7: "Updating a plan's force-out configuration requires the request to carry
    `expected_plan_version` equal to the plan's current `version`." and "the request is
    rejected with `ERR_STALE_VERSION` and HTTP status 412, and the client must re-read the
    resource and re-apply its intent to the current version."
    PRD §3.1: "A successful update recomputes `network_reachable` and increments the plan's
    `version`."

    Design: Corner/complexity_layers/occ_plan_patch_stale_version
    """
    rk = create_active_recordkeeper()
    plan = create_plan(rk["id"])
    pv = plan["version"]

    updated = validate_success(api_client.patch_plan(
        plan["id"],
        {"expected_plan_version": pv, "state_withholding_rate": 0.05},
        SPONSOR,
    ))
    assert updated["state_withholding_rate"] == 0.05
    assert updated["version"] == pv + 1

    res = api_client.patch_plan(
        plan["id"],
        {"expected_plan_version": pv, "state_withholding_rate": 0.07},
        SPONSOR,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, 412)
    plan_after = get_success_data(api_client.get_plan(plan["id"], OPS))
    assert plan_after["state_withholding_rate"] == 0.05


def test_network_reachable_reconciles_on_suspend_reinstate():
    """PRD §3.1: "Suspension moves an `ACTIVE` recordkeeper to `SUSPENDED`."
    PRD §3.1: "Activation recomputes `network_reachable` to true for every plan of that
    recordkeeper whose `accepts_incoming_transfers` is true — incrementing those plans'
    `version` values in the process — while suspension recomputes `network_reachable` to
    false for every plan of the recordkeeper."
    PRD §2.8: "The flag is recomputed whenever the recordkeeper's status changes and
    whenever the plan itself is updated."

    Design: Corner/complexity_layers/network_reachable_reconciles_on_suspend_reinstate
    """
    rk = create_active_recordkeeper()
    plan = create_plan(rk["id"])
    assert plan["network_reachable"] is True
    assert plan["accepts_incoming_transfers"] is True

    get_success_data(api_client.suspend_recordkeeper(rk["id"], OPS))
    plan = get_success_data(api_client.get_plan(plan["id"], OPS))
    assert plan["network_reachable"] is False
    assert plan["accepts_incoming_transfers"] is True

    get_success_data(api_client.activate_recordkeeper(rk["id"], OPS))
    plan = get_success_data(api_client.get_plan(plan["id"], OPS))
    assert plan["network_reachable"] is True
    assert plan["accepts_incoming_transfers"] is True


def test_immediate_read_after_write_computed_fields():
    """PRD §3.3: "At creation each case computes a provisional `quoted_balance_cents`: the
    separation-date balance times the vesting percent divided by one hundred, rounded
    half-up to integer cents."
    PRD §3.3: "New cases start `IDENTIFIED`"

    Design: Corner/consistency_model/immediate_read_after_write_computed_fields
    """
    rk = create_active_recordkeeper()
    plan = create_plan(rk["id"])
    participant = create_participant()
    batch = create_open_batch(plan["id"])
    case = validate_success(api_client.create_distribution_case({
        "distribution_batch_id": batch["id"],
        "plan_id": plan["id"],
        "participant_id": participant["id"],
        "separation_date": "2026-07-15T00:00:00Z",
        "separation_date_balance_cents": 90000,
        "processing_date_balance_cents": 120000,
    }, SPONSOR), 201)
    # The computed field is visible in the create response itself.
    assert case["quoted_balance_cents"] == 90000
    fetched = get_success_data(api_client.get_distribution_case(case["id"], OPS))
    assert fetched["quoted_balance_cents"] == 90000
    assert fetched["case_status"] == "IDENTIFIED"
