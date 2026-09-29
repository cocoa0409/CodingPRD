"""Two gates that read another row: the carrier's posture and the policy's claims."""
from test_helpers import (
    ATLAS,
    BEACON,
    accept_assignment,
    api_client,
    assignment_for_application,
    bootstrap_plan,
    bring_application_to_certified,
    ApiErrorId,
    create_claim_closure_payload,
    create_policy_payload,
    create_voluntary_exit_payload,
    drive_carrier_to_suspension,
    issue_policy,
    make_plan_administrator_headers,
    make_servicing_carrier_headers,
    read_applicant,
    read_application,
    read_assignment,
    read_carrier,
    read_claim,
    read_policy,
    report_claim,
    run_cycle,
    schedule_cycle,
    set_clock,
    setup_policy_in_force,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN_HEADERS = make_plan_administrator_headers()

ATLAS_DOMINANT = dict(ATLAS, voluntary_market_share_bps=9000)
BEACON_MINOR = dict(BEACON, voluntary_market_share_bps=1000)


def _suspended_carrier_holding_an_accepted_assignment():
    """Atlas accepts a second risk, then two upheld complaints suspend it."""
    env = bootstrap_plan(carriers=[ATLAS_DOMINANT, BEACON_MINOR])
    atlas = env["carriers"][0]
    first = bring_application_to_certified(
        env,
        applicant_overrides={"full_name": "Owen Pike", "driver_license_number": "D-99011"},
        vehicle_overrides={"vin": "1HGCM82633A004360"},
        document_prefix="DEC-23",
    )
    september = schedule_cycle(env["plan_period"]["id"])
    run_cycle(september["id"])
    first_assignment = assignment_for_application(first["application"]["id"])
    accept_assignment(first_assignment["id"], atlas["id"])
    set_clock("2026-09-15T00:00:00Z")
    policy = issue_policy(first_assignment["id"], atlas["id"], policy_number="AR-100008")

    set_clock("2026-10-05T00:00:00Z")
    second = bring_application_to_certified(
        env,
        applicant_overrides={"full_name": "Nadia Frost", "driver_license_number": "D-99012"},
        vehicle_overrides={"vin": "1HGCM82633A004361"},
        application_overrides={"requested_effective_date": "2026-10-20T00:00:00Z"},
        document_prefix="DEC-24",
    )
    october = schedule_cycle(env["plan_period"]["id"],
                            window_start="2026-10-02T00:00:00Z",
                            window_end="2026-10-31T00:00:00Z")
    run_cycle(october["id"])
    second_assignment = assignment_for_application(second["application"]["id"])
    accept_assignment(second_assignment["id"], atlas["id"])
    assert read_carrier(atlas["id"])["assigned_risk_count"] == 2

    suspended = drive_carrier_to_suspension(policy["id"], atlas["id"])
    assert suspended["posture"] == "SUSPENDED"
    return {"atlas": atlas, "policy": policy, "first_assignment": first_assignment,
            "second_application": second["application"],
            "second_assignment": second_assignment}


def _attempt_issuance_on_the_second_assignment(world):
    return api_client.create_policy(
        create_policy_payload(world["second_assignment"]["id"],
                              policy_number="AR-100009",
                              effective_date="2026-10-20T00:00:00Z",
                              expiration_date="2027-10-20T00:00:00Z"),
        make_servicing_carrier_headers(world["atlas"]["id"]))


def test_a_suspended_carrier_cannot_issue_the_policy_it_already_accepted():
    """Acceptance was lawful, but issuance re-reads the carrier's standing.

    The assignment is in ACCEPTED and no policy references it, so both of the
    issuance preconditions that live on the assignment are met. The gate that
    refuses is the one that reads the other row: the carrier's posture, driven to
    SUSPENDED by two upheld complaints, and its score of 60.

    PRD: "Issuance requires the assignment to be in `ACCEPTED`, requires that no
    policy already references that assignment, and requires the carrier's `posture`
    not to be `SUSPENDED`."
    Design: Difficulty/cross_entity_state_dependency/policy_issuance_depends_on_the_designated_carriers_posture
    """
    world = _suspended_carrier_holding_an_accepted_assignment()

    response = _attempt_issuance_on_the_second_assignment(world)

    validate_error(response, ApiErrorId.ERR_CARRIER_SUSPENDED, 409)
    atlas = read_carrier(world["atlas"]["id"])
    assert atlas["posture"] == "SUSPENDED"
    assert atlas["performance_score"] == 60


def test_the_refused_issuance_leaves_the_assignment_accepted_and_the_deposit_uncredited():
    """No policy row is created, so the accepted designation simply waits.

    The second assignment stays in ACCEPTED with no policy attached, its application
    stays in ASSIGNED, and because issuance is what sweeps the deposit into premium
    the whole 38939 cents remains uncredited. Atlas still counts both risks, and the
    policy it did manage to write is unaffected.

    PRD: "On success the policy's `carrier_id` is copied from the assignment, the
    assignment advances `ACCEPTED → POLICY_ISSUED`, and the application advances
    `ASSIGNED → POLICY_ISSUED`."
    Design: Difficulty/cross_entity_state_dependency/policy_issuance_depends_on_the_designated_carriers_posture
    """
    world = _suspended_carrier_holding_an_accepted_assignment()

    response = _attempt_issuance_on_the_second_assignment(world)

    validate_error(response, ApiErrorId.ERR_CARRIER_SUSPENDED, 409)
    assert read_assignment(world["second_assignment"]["id"])["status"] == "ACCEPTED"
    _, meta = validate_paginated(api_client.list_policies(
        ADMIN_HEADERS, params={"assignment_id": world["second_assignment"]["id"]}))
    assert meta["total_count"] == 0
    application = read_application(world["second_application"]["id"])
    assert application["status"] == "ASSIGNED"
    assert application["deposit_balance_cents"] == 38939
    assert read_carrier(world["atlas"]["id"])["assigned_risk_count"] == 2
    assert read_policy(world["policy"]["id"])["policy_status"] == "IN_FORCE"


def _policy_with_one_live_loss():
    """A rehabilitated risk in force, carrying one open no-fault property claim."""
    env = setup_policy_in_force(policy_number="AR-100010")
    set_clock("2026-09-20T00:00:00Z")
    assert read_applicant(env["applicant"]["id"])["clean_years_credited"] == 5
    claim = report_claim(env["policy"]["id"], env["carrier"]["id"],
                         loss_date="2026-09-20T00:00:00Z", at_fault=False,
                         coverage_line="PD", reserve_cents=50000)
    assert claim["status"] == "OPEN"
    env["claim"] = claim
    return env


def _attempt_voluntary_exit(env):
    return api_client.exit_policy_to_voluntary(
        env["policy"]["id"],
        create_voluntary_exit_payload("Risk has been rehabilitated."),
        ADMIN_HEADERS)


def test_a_live_claim_blocks_the_voluntary_market_exit_in_both_of_its_live_states():
    """Open and acknowledged are both live, so both refuse the exit.

    The applicant has the five clean years the gate wants, so eligibility is not the
    obstacle. The unsettled loss is, and acknowledging it does not settle it: the
    exit is refused while the claim is OPEN and refused again while it is
    ACKNOWLEDGED. The acknowledgement itself is inside the ten-day standard, so it
    is no breach and the carrier's score is untouched.

    PRD: "The policy must be `IN_FORCE`, the applicant's `clean_years_credited` must
    be at least 3 — fewer is refused with `ERR_CLEAN_YEARS_INSUFFICIENT` and HTTP
    422 — and no claim of the policy may be in `OPEN` or `ACKNOWLEDGED`, since an
    unsettled loss is refused with `ERR_OPEN_CLAIM_BLOCKS_EXIT` and HTTP 409."
    Design: Difficulty/cross_entity_state_dependency/voluntary_market_exit_depends_on_the_policys_live_claim_inventory
    """
    env = _policy_with_one_live_loss()

    while_open = _attempt_voluntary_exit(env)
    validate_error(while_open, ApiErrorId.ERR_OPEN_CLAIM_BLOCKS_EXIT, 409)
    assert read_policy(env["policy"]["id"])["policy_status"] == "IN_FORCE"

    validate_success(api_client.acknowledge_claim(
        env["claim"]["id"], make_servicing_carrier_headers(env["carrier"]["id"])))
    acknowledged = read_claim(env["claim"]["id"])
    assert acknowledged["status"] == "ACKNOWLEDGED"
    assert acknowledged["standard_breach"] is False
    assert read_carrier(env["carrier"]["id"])["performance_score"] == 100

    while_acknowledged = _attempt_voluntary_exit(env)
    validate_error(while_acknowledged, ApiErrorId.ERR_OPEN_CLAIM_BLOCKS_EXIT, 409)
    assert read_policy(env["policy"]["id"])["policy_status"] == "IN_FORCE"


def test_closing_the_claim_unblocks_the_exit_and_credits_the_servicing_carrier():
    """A denied closure settles the loss, and the same exit call then succeeds.

    The claim is closed with a denial, which leaves nothing paid, and the previously
    refused exit goes through. The policy leaves the residual market, the applicant
    becomes voluntary-market eligible with its five clean years intact, the
    assignment and application close, and the carrier that was servicing the risk
    earns one unit of voluntary credit because the vehicle's territory is not among
    the period's underserved ones.

    PRD: "`voluntary_credit_units` rises by 1.5 when the vehicle's
    `garaging_territory_code` appears in that period's `underserved_territories`, and
    by 1.0 otherwise."
    Design: Difficulty/cross_entity_state_dependency/voluntary_market_exit_depends_on_the_policys_live_claim_inventory
    """
    env = _policy_with_one_live_loss()
    carrier_headers = make_servicing_carrier_headers(env["carrier"]["id"])
    validate_success(api_client.acknowledge_claim(env["claim"]["id"], carrier_headers))

    validate_success(api_client.close_claim(
        env["claim"]["id"],
        create_claim_closure_payload("DENIED", denial_reason="Loss outside coverage."),
        carrier_headers))
    closed = read_claim(env["claim"]["id"])
    assert closed["status"] == "CLOSED_DENIED"
    assert closed["paid_cents"] == 0

    validate_success(_attempt_voluntary_exit(env))

    assert read_policy(env["policy"]["id"])["policy_status"] == "EXITED_TO_VOLUNTARY"
    applicant = read_applicant(env["applicant"]["id"])
    assert applicant["voluntary_market_eligible"] is True
    assert applicant["clean_years_credited"] == 5
    carrier = read_carrier(env["carrier"]["id"])
    assert carrier["voluntary_credit_units"] == 1.0
    assert carrier["assigned_risk_count"] == 0
    assert read_assignment(env["assignment"]["id"])["status"] == "CLOSED"
    assert read_application(env["application"]["id"])["status"] == "CLOSED_EXITED"
