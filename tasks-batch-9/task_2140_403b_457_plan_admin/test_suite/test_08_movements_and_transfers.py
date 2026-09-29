"""Contract exchanges and plan-to-plan transfers."""

from test_helpers import (
    ApiErrorId,
    create_active_plan,
    create_batch,
    create_movement_request_payload,
    decide_movement,
    deposit_batch,
    execute_movement,
    first_correction,
    make_line_item,
    make_officer_headers,
    make_sponsor_headers,
    make_vendor_headers,
    move_agreement,
    open_contract,
    register_employer,
    register_participant,
    register_second_vendor,
    register_vendor,
    reverse_movement,
    set_clock,
    settle_correction,
    setup_accepted_exchange,
    setup_active_agreement,
    setup_approved_exchange,
    setup_plan_env,
    setup_two_vendor_403b,
    submit_movement,
    vendor_respond,
    post_data_feed,
    validate_error,
    validate_paginated,
    validate_success,
)


def _divergence_env():
    """Two ACTIVE 403(b) plans under one sponsor. Provider one is inside the first plan's
    perimeter; provider two's agreement with that plan has been TERMINATED and it holds
    no agreement with the second plan."""
    set_clock()
    employer = register_employer()
    vendor_one = register_vendor()
    vendor_two = register_second_vendor()
    plan_one = create_active_plan(employer["id"], plan_name="Riverbend 403(b)")
    plan_two = create_active_plan(employer["id"], plan_name="Riverbend Legacy 403(b)")
    setup_active_agreement(plan_one["id"], vendor_one["id"], employer["id"])
    terminated = setup_active_agreement(
        plan_one["id"], vendor_two["id"], employer["id"], feed_date=None
    )
    move_agreement(terminated["id"], employer["id"], "TERMINATED")
    participant = register_participant(employer["id"])
    account_one = open_contract(
        participant["id"], plan_one["id"], vendor_one["id"], employer["id"],
        contract_number="NLA-0001", accumulated_benefit_cents=5_000_000,
    )
    account_two = open_contract(
        participant["id"], plan_one["id"], vendor_two["id"], employer["id"],
        contract_number="CDR-0001", accumulated_benefit_cents=1_000_000,
    )
    account_other_plan = open_contract(
        participant["id"], plan_two["id"], vendor_two["id"], employer["id"],
        contract_number="CDR-0002", accumulated_benefit_cents=0,
    )
    return {
        "employer_id": employer["id"], "plan_one_id": plan_one["id"],
        "plan_two_id": plan_two["id"], "participant_id": participant["id"],
        "account_one_id": account_one["id"], "account_two_id": account_two["id"],
        "account_other_plan_id": account_other_plan["id"],
    }


def test_contract_exchange_refused_when_receiving_agreement_is_terminated(api):
    """PRD §3.9: "The receiving contract's vendor must additionally hold an information
    sharing agreement with the plan whose `status` is `ACTIVE` and whose `data_stale` is
    false, failing which the answer is `ERR_EXCHANGE_VENDOR_NOT_APPROVED`."
    PRD §3.2: "Terminating an agreement from `ACTIVE` or from `SUSPENDED` additionally
    means the provider ceases to be an approved receiving vendor for contract exchanges
    into that plan; terminating from `PENDING` carries no such cascade because a pending
    agreement never conferred approval in the first place."

    Design: Difficulty/dual_variant_calc/exchange_versus_transfer_admissibility_divergence
    """
    env = _divergence_env()

    response = api.create_movement_request(
        create_movement_request_payload(
            env["participant_id"], "CONTRACT_EXCHANGE", env["plan_one_id"], env["plan_one_id"],
            env["account_one_id"], env["account_two_id"], 5_000_000,
        ),
        make_sponsor_headers(env["employer_id"]),
    )

    validate_error(response, ApiErrorId.ERR_EXCHANGE_VENDOR_NOT_APPROVED.value)
    assert validate_success(
        api.get_vendor_account(env["account_one_id"], make_officer_headers())
    )["accumulated_benefit_cents"] == 5_000_000
    rows, _meta = validate_paginated(
        api.list_movement_requests(
            make_officer_headers(), {"participant_id": env["participant_id"]}
        )
    )
    assert rows == []


def test_plan_to_plan_transfer_needs_no_information_sharing_agreement(api):
    """PRD §3.9: "For a `PLAN_TO_PLAN_TRANSFER`, the `source_plan_id` and
    `destination_plan_id` must name *different* plans, the source plan's
    `permits_outgoing_transfers` and the destination plan's `permits_incoming_transfers`
    must both be true, and the two plans must share the same `plan_type`; any of those
    three failing is `ERR_TRANSFER_NOT_PERMITTED_BY_PLAN`. No information sharing
    agreement is required at all for a transfer."
    PRD §3.9: "The request is created in state `SUBMITTED`, and requests may be listed
    filtered by `participant_id`, `source_plan_id`, `destination_plan_id`,
    `source_vendor_account_id`, `destination_vendor_account_id`, `request_kind` or
    `state`."

    Design: Difficulty/dual_variant_calc/exchange_versus_transfer_admissibility_divergence
    """
    env = _divergence_env()

    created = validate_success(
        api.create_movement_request(
            create_movement_request_payload(
                env["participant_id"], "PLAN_TO_PLAN_TRANSFER", env["plan_one_id"],
                env["plan_two_id"], env["account_one_id"], env["account_other_plan_id"],
                5_000_000,
            ),
            make_sponsor_headers(env["employer_id"]),
        ),
        expected_status=201,
    )

    assert created["state"] == "SUBMITTED"
    assert created["amount_cents"] == 5_000_000
    rows, _meta = validate_paginated(
        api.list_movement_requests(
            make_officer_headers(), {"participant_id": env["participant_id"]}
        )
    )
    assert len(rows) == 1
    assert validate_success(
        api.get_vendor_account(env["account_one_id"], make_officer_headers())
    )["accumulated_benefit_cents"] == 5_000_000, "filing moves no money"


def _suspended_receiver_env():
    """Provider two's agreement is activated, fed, and then SUSPENDED."""
    env = setup_plan_env(plan_type="PLAN_403B", num_vendors=2)
    setup_active_agreement(env["plan_id"], env["vendor_ids"][0], env["employer_id"])
    suspended = setup_active_agreement(
        env["plan_id"], env["vendor_ids"][1], env["employer_id"], "2026-07-31"
    )
    move_agreement(suspended["id"], env["employer_id"], "SUSPENDED")
    participant = register_participant(env["employer_id"])
    account_one = open_contract(
        participant["id"], env["plan_id"], env["vendor_ids"][0], env["employer_id"],
        contract_number="NLA-0001", accumulated_benefit_cents=5_000_000,
    )
    account_two = open_contract(
        participant["id"], env["plan_id"], env["vendor_ids"][1], env["employer_id"],
        contract_number="CDR-0001", accumulated_benefit_cents=1_000_000,
    )
    env.update(
        suspended_agreement_id=suspended["id"], participant_id=participant["id"],
        account_one_id=account_one["id"], account_two_id=account_two["id"],
    )
    return env


def test_suspended_receiving_agreement_beats_the_over_large_amount(api):
    """PRD §2.6: "When a single request violates more than one rule, the server does not
    report the "most important" violation — it reports the violation that sits highest on
    a fixed ladder, and stops there."
    PRD §3.9: "The receiving contract's vendor must additionally hold an information
    sharing agreement with the plan whose `status` is `ACTIVE` and whose `data_stale` is
    false, failing which the answer is `ERR_EXCHANGE_VENDOR_NOT_APPROVED`."
    PRD §3.9: "Finally, `amount_cents` must be less than or equal to the source contract's
    `accumulated_benefit_cents`, so that the participant's accumulated benefit immediately
    after the exchange is at least what it was immediately before; an over-large amount
    here is reported as `ERR_ACCUMULATED_BENEFIT_REDUCED`."

    Design: Difficulty/priority_pair_validation_conflict/exchange_vendor_not_approved_referential_beats_benefit_reduced_fiscal
    """
    env = _suspended_receiver_env()

    response = api.create_movement_request(
        create_movement_request_payload(
            env["participant_id"], "CONTRACT_EXCHANGE", env["plan_id"], env["plan_id"],
            env["account_one_id"], env["account_two_id"], 9_000_000,
        ),
        make_sponsor_headers(env["employer_id"]),
    )

    validate_error(response, ApiErrorId.ERR_EXCHANGE_VENDOR_NOT_APPROVED.value)
    rows, _meta = validate_paginated(
        api.list_movement_requests(
            make_officer_headers(), {"participant_id": env["participant_id"]}
        )
    )
    assert rows == []


def test_over_large_exchange_amount_surfaces_after_reinstatement(api):
    """PRD §3.9: "Finally, `amount_cents` must be less than or equal to the source
    contract's `accumulated_benefit_cents`, so that the participant's accumulated benefit
    immediately after the exchange is at least what it was immediately before; an
    over-large amount here is reported as `ERR_ACCUMULATED_BENEFIT_REDUCED`."
    PRD §3.2: "Reinstatement moves the agreement `SUSPENDED → ACTIVE` and may be triggered
    two ways — the sponsor admin naming the destination explicitly, or the provider posting
    a data feed."

    Design: Difficulty/priority_pair_validation_conflict/exchange_vendor_not_approved_referential_beats_benefit_reduced_fiscal
    """
    env = _suspended_receiver_env()
    validate_error(
        api.create_movement_request(
            create_movement_request_payload(
                env["participant_id"], "CONTRACT_EXCHANGE", env["plan_id"], env["plan_id"],
                env["account_one_id"], env["account_two_id"], 9_000_000,
            ),
            make_sponsor_headers(env["employer_id"]),
        ),
        ApiErrorId.ERR_EXCHANGE_VENDOR_NOT_APPROVED.value,
    )

    reinstated = move_agreement(env["suspended_agreement_id"], env["employer_id"], "ACTIVE")
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["data_stale"] is False

    response = api.create_movement_request(
        create_movement_request_payload(
            env["participant_id"], "CONTRACT_EXCHANGE", env["plan_id"], env["plan_id"],
            env["account_one_id"], env["account_two_id"], 9_000_000,
        ),
        make_sponsor_headers(env["employer_id"]),
    )

    validate_error(response, ApiErrorId.ERR_ACCUMULATED_BENEFIT_REDUCED.value)
    rows, _meta = validate_paginated(
        api.list_movement_requests(
            make_officer_headers(), {"participant_id": env["participant_id"]}
        )
    )
    assert rows == []


def _late_deposit_with_accepted_exchange_env():
    """A plan carrying an accepted contract exchange and a batch that is about to be
    deposited six weeks past its deadline."""
    env = setup_two_vendor_403b()
    batch = create_batch(
        env["plan_id"], env["employer_id"], [make_line_item(env["account_one_id"], 100_000)]
    )
    movement = submit_movement(
        env["participant_id"], "CONTRACT_EXCHANGE", env["plan_id"], env["plan_id"],
        env["account_one_id"], env["account_two_id"], 1_000_000, env["employer_id"],
    )
    vendor_respond(movement["id"], env["vendor_ids"][1], True)
    set_clock("2026-09-30T00:00:00Z")
    post_data_feed(env["agreement_one_id"], env["vendor_ids"][0], "2026-09-30")
    post_data_feed(env["agreement_two_id"], env["vendor_ids"][1], "2026-09-30")
    env.update(batch_id=batch["id"], movement_id=movement["id"])
    return env


def test_late_deposit_raises_the_correction_and_the_plan_counter(api):
    """PRD §3.7: "Landing on `LATE` immediately triggers a system transition
    `LATE → CORRECTION_PENDING`, and with it a four-hop chain that nothing else in the
    system initiates. A `RemittanceCorrection` is created against the batch in state
    `OPEN`, carrying the `remittance_batch_id` and its computed
    `lost_earnings_total_cents`, `excise_tax_cents` and `line_breakdown`. Creating that
    correction adds each line's lost earnings to the corresponding contract's
    `pending_lost_earnings_cents` and forces the plan's `open_correction_count` to be
    recomputed."

    Design: Difficulty/transitive_cascade/late_deposit_correction_posture_blocks_transfer_chain
    """
    env = _late_deposit_with_accepted_exchange_env()

    deposited = deposit_batch(env["batch_id"], env["employer_id"], "2026-09-30")

    assert deposited["deposit_state"] == "DEPOSITED"
    assert deposited["business_days_late"] == 27
    assert deposited["compliance_state"] == "CORRECTION_PENDING"
    rows, _meta = validate_paginated(
        api.list_corrections(env["batch_id"], make_officer_headers())
    )
    assert len(rows) == 1
    assert rows[0]["state"] == "OPEN"
    assert rows[0]["lost_earnings_total_cents"] == 658
    assert rows[0]["excise_tax_cents"] == 99
    assert validate_success(
        api.get_vendor_account(env["account_one_id"], make_officer_headers())
    )["pending_lost_earnings_cents"] == 658
    assert validate_success(
        api.get_plan(env["plan_id"], make_officer_headers())
    )["open_correction_count"] == 1


def test_under_correction_posture_blocks_the_accepted_exchange(api):
    """PRD §3.7: "The now non-zero count drives the plan's `compliance_posture` from
    `CLEAR` to `UNDER_CORRECTION`, and an under-correction plan cannot have any transfer
    or exchange naming it approved."
    PRD §3.9: "A plan sitting on an unsettled late-deposit correction is
    `UNDER_CORRECTION`, and any movement naming it is refused with
    `ERR_PLAN_UNDER_CORRECTION` — this is the point at which the remittance cascade of
    §3.7 reaches across into the movement pipeline."

    Design: Difficulty/transitive_cascade/late_deposit_correction_posture_blocks_transfer_chain
    """
    env = _late_deposit_with_accepted_exchange_env()
    deposit_batch(env["batch_id"], env["employer_id"], "2026-09-30")

    assert validate_success(
        api.get_plan(env["plan_id"], make_officer_headers())
    )["compliance_posture"] == "UNDER_CORRECTION"

    response = api.decide_movement_request(
        env["movement_id"], {"decision": "APPROVE"}, make_officer_headers("co-1")
    )

    validate_error(response, ApiErrorId.ERR_PLAN_UNDER_CORRECTION.value)
    assert validate_success(
        api.get_movement_request(env["movement_id"], make_officer_headers())
    )["state"] == "ACCEPTED_BY_VENDOR"
    assert validate_success(
        api.get_vendor_account(env["account_one_id"], make_officer_headers())
    )["accumulated_benefit_cents"] == 5_000_000
    assert validate_success(
        api.get_vendor_account(env["account_two_id"], make_officer_headers())
    )["accumulated_benefit_cents"] == 1_000_000


def test_movement_approval_blocked_while_the_plan_is_under_correction(api):
    """PRD §3.9: "`APPROVE` applies only to a request in `ACCEPTED_BY_VENDOR` and moves it
    `ACCEPTED_BY_VENDOR → APPROVED`. Approval re-runs the whole admissibility check for
    the declared `request_kind`, and adds one further condition that filing did not test:
    both the source plan and the destination plan must have `compliance_posture` reading
    `CLEAR`."
    PRD §2.10: "At the plan tier, `open_correction_count` is the number of remittance
    corrections in state `OPEN` across every remittance batch whose `plan_id` is this
    plan, and `compliance_posture` follows it mechanically: `UNDER_CORRECTION` while
    `open_correction_count` is greater than zero, `CLEAR` otherwise."

    Design: Difficulty/cross_entity_state_dependency/transfer_approval_gated_by_plan_compliance_posture
    """
    env = _late_deposit_with_accepted_exchange_env()
    deposit_batch(env["batch_id"], env["employer_id"], "2026-09-30")
    plan = validate_success(api.get_plan(env["plan_id"], make_officer_headers()))
    assert plan["open_correction_count"] == 1
    assert plan["compliance_posture"] == "UNDER_CORRECTION"

    response = api.decide_movement_request(
        env["movement_id"], {"decision": "APPROVE"}, make_officer_headers("co-1")
    )

    validate_error(response, ApiErrorId.ERR_PLAN_UNDER_CORRECTION.value)
    assert validate_success(
        api.get_movement_request(env["movement_id"], make_officer_headers())
    )["state"] == "ACCEPTED_BY_VENDOR"


def test_movement_approval_succeeds_once_the_correction_is_settled(api):
    """PRD §3.7: "When the last correction of a batch leaves `OPEN`, the batch itself moves
    `CORRECTION_PENDING → CORRECTED` as a system transition, recomputing the plan's
    `open_correction_count` and `compliance_posture` once more and incrementing the
    batch's `version` by one."
    PRD §3.9: "`APPROVE` applies only to a request in `ACCEPTED_BY_VENDOR` and moves it
    `ACCEPTED_BY_VENDOR → APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/transfer_approval_gated_by_plan_compliance_posture
    """
    env = _late_deposit_with_accepted_exchange_env()
    deposit_batch(env["batch_id"], env["employer_id"], "2026-09-30")
    correction = first_correction(env["batch_id"])
    validate_error(
        api.decide_movement_request(
            env["movement_id"], {"decision": "APPROVE"}, make_officer_headers("co-1")
        ),
        ApiErrorId.ERR_PLAN_UNDER_CORRECTION.value,
    )

    settled = settle_correction(env["batch_id"], correction["id"], "VFCP-2026-0001", "co-2")
    assert settled["state"] == "SETTLED"
    assert settled["settled_by_user_id"] == "co-2"

    plan = validate_success(api.get_plan(env["plan_id"], make_officer_headers()))
    assert plan["open_correction_count"] == 0
    assert plan["compliance_posture"] == "CLEAR"
    assert validate_success(
        api.get_remittance_batch(env["batch_id"], make_officer_headers())
    )["compliance_state"] == "CORRECTED"

    approved = validate_success(
        api.decide_movement_request(
            env["movement_id"], {"decision": "APPROVE"}, make_officer_headers("co-1")
        )
    )
    assert approved["state"] == "APPROVED"


def test_execution_moves_money_and_snapshots_both_sides(api):
    """PRD §3.9: "Execution first snapshots both sides: `pre_move_source_benefit_cents`
    records the source contract's `accumulated_benefit_cents` and
    `pre_move_destination_benefit_cents` the destination contract's, as they stood
    immediately before the move. Then the source contract's `accumulated_benefit_cents` is
    reduced by `amount_cents` and the destination contract's is increased by the same
    figure; both contracts' `vested_balance_cents` are recomputed from their new benefits;
    the participant's `total_accumulated_benefit_cents` and `total_vested_balance_cents`
    are recomputed; `executed_at` is stamped from the logical clock; and the request moves
    `APPROVED → EXECUTED` with its `version` incremented by one."

    Design: Difficulty/compensating_invariant/transfer_execute_reverse_preserves_participant_benefit_total
    """
    env = setup_approved_exchange(amount_cents=1_500_000)
    before = validate_success(
        api.get_participant(env["participant_id"], make_officer_headers())
    )
    assert before["total_accumulated_benefit_cents"] == 6_000_000

    executed = execute_movement(env["movement_id"], env["employer_id"], "2026-08-01")

    assert executed["state"] == "EXECUTED"
    assert executed["pre_move_source_benefit_cents"] == 5_000_000
    assert executed["pre_move_destination_benefit_cents"] == 1_000_000
    source = validate_success(
        api.get_vendor_account(env["account_one_id"], make_officer_headers())
    )
    destination = validate_success(
        api.get_vendor_account(env["account_two_id"], make_officer_headers())
    )
    assert source["accumulated_benefit_cents"] == 3_500_000
    assert destination["accumulated_benefit_cents"] == 2_500_000
    after = validate_success(
        api.get_participant(env["participant_id"], make_officer_headers())
    )
    assert after["total_accumulated_benefit_cents"] == 6_000_000, "the move itself is neutral"


def test_reversal_restores_both_contracts_exactly(api):
    """PRD §3.9: "Reversal moves the request `EXECUTED → REVERSED` on a supplied `reason`,
    adds `amount_cents` back to the source contract's `accumulated_benefit_cents`,
    subtracts it from the destination contract's, recomputes both `vested_balance_cents`
    figures, and recomputes the participant's `total_accumulated_benefit_cents` and
    `total_vested_balance_cents`. The compensation is exact: after reversal, the sum of
    `accumulated_benefit_cents` over the participant's open contracts is precisely what it
    was before execution, with zero drift."

    Design: Difficulty/compensating_invariant/transfer_execute_reverse_preserves_participant_benefit_total
    """
    env = setup_approved_exchange(amount_cents=1_500_000)
    execute_movement(env["movement_id"], env["employer_id"], "2026-08-01")

    reversed_request = reverse_movement(
        env["movement_id"], "wrong destination contract identified by the sponsor", "co-1"
    )

    assert reversed_request["state"] == "REVERSED"
    source = validate_success(
        api.get_vendor_account(env["account_one_id"], make_officer_headers())
    )
    destination = validate_success(
        api.get_vendor_account(env["account_two_id"], make_officer_headers())
    )
    assert source["accumulated_benefit_cents"] == 5_000_000
    assert destination["accumulated_benefit_cents"] == 1_000_000
    participant = validate_success(
        api.get_participant(env["participant_id"], make_officer_headers())
    )
    assert participant["total_accumulated_benefit_cents"] == 6_000_000
    assert participant["total_vested_balance_cents"] == 6_000_000


def test_vendor_rejection_then_resubmit_cycle(api):
    """PRD §3.9: "Refusal moves it `SUBMITTED → REJECTED_BY_VENDOR` and stores the reason
    as `vendor_rejection_reason`."
    PRD §3.9: "`RESUBMIT` applies to a request in `REJECTED_BY_VENDOR` and returns it
    `REJECTED_BY_VENDOR → SUBMITTED`, clearing `vendor_rejection_reason` and increasing
    `resubmit_count` by one; the `SUBMITTED → REJECTED_BY_VENDOR → SUBMITTED` cycle may
    repeat any number of times."
    PRD §3.9: "Acceptance moves the request `SUBMITTED → ACCEPTED_BY_VENDOR`."

    Design: Corner/state_machines/transfer_request_vendor_rejection_then_resubmit_cycle
    """
    env = setup_two_vendor_403b()
    movement = submit_movement(
        env["participant_id"], "CONTRACT_EXCHANGE", env["plan_id"], env["plan_id"],
        env["account_one_id"], env["account_two_id"], 1_000_000, env["employer_id"],
    )

    rejected = validate_success(
        api.respond_to_movement_request(
            movement["id"],
            {"accepted": False, "rejection_reason": "receiving contract not yet in force"},
            make_vendor_headers(env["vendor_ids"][1]),
        )
    )
    assert rejected["state"] == "REJECTED_BY_VENDOR"
    assert rejected["vendor_rejection_reason"] == "receiving contract not yet in force"

    resubmitted = decide_movement(movement["id"], "RESUBMIT", "co-1")
    assert resubmitted["state"] == "SUBMITTED"
    assert resubmitted["resubmit_count"] == 1
    assert resubmitted["vendor_rejection_reason"] is None

    accepted = vendor_respond(movement["id"], env["vendor_ids"][1], True)
    assert accepted["state"] == "ACCEPTED_BY_VENDOR"
    assert validate_success(
        api.get_vendor_account(env["account_one_id"], make_officer_headers())
    )["accumulated_benefit_cents"] == 5_000_000, "no money moves before execution"


def test_transfer_to_another_employers_plan_is_rejected(api):
    """PRD §3.9: "What *is* required is that the participant's `employer_id` equals the
    destination plan's `employer_id` — the participant must be an employee or former
    employee of the receiving sponsor — failing which the answer is
    `ERR_TRANSFER_PARTICIPANT_NOT_ELIGIBLE`."

    Design: Corner/validations/plan_to_plan_transfer_to_another_employers_plan_is_rejected
    """
    set_clock()
    employer_one = register_employer()
    employer_two = register_employer(
        legal_name="Cedarbrook Charter School", ein="22-2222222", total_employee_count=60
    )
    vendor = register_vendor()
    plan_one = create_active_plan(employer_one["id"], plan_name="Riverbend 403(b)")
    plan_two = create_active_plan(
        employer_two["id"], plan_name="Cedarbrook 403(b)", reported_participant_count=50
    )
    participant = register_participant(employer_one["id"])
    account_one = open_contract(
        participant["id"], plan_one["id"], vendor["id"], employer_one["id"],
        contract_number="NLA-0001", accumulated_benefit_cents=5_000_000,
    )
    account_two = open_contract(
        participant["id"], plan_two["id"], vendor["id"], employer_two["id"],
        contract_number="NLA-0002", accumulated_benefit_cents=0,
    )

    response = api.create_movement_request(
        create_movement_request_payload(
            participant["id"], "PLAN_TO_PLAN_TRANSFER", plan_one["id"], plan_two["id"],
            account_one["id"], account_two["id"], 1_000_000,
        ),
        make_sponsor_headers(employer_one["id"]),
    )

    validate_error(response, ApiErrorId.ERR_TRANSFER_PARTICIPANT_NOT_ELIGIBLE.value)
    assert validate_success(
        api.get_vendor_account(account_one["id"], make_officer_headers())
    )["accumulated_benefit_cents"] == 5_000_000
    assert validate_success(
        api.get_vendor_account(account_two["id"], make_officer_headers())
    )["accumulated_benefit_cents"] == 0


def test_exchange_refused_when_the_plan_forbids_exchanges(api):
    """PRD §3.9: "For a `CONTRACT_EXCHANGE`, the `source_plan_id` and `destination_plan_id`
    must name the same plan and that plan's `permits_contract_exchanges` must be true; a
    mismatch on either point is `ERR_TRANSFER_NOT_PERMITTED_BY_PLAN`."
    PRD §3.1: "Six plan-document permissions may be supplied and each defaults to true
    when omitted: `permits_loans`, `permits_hardship`, `permits_unforeseeable_emergency`,
    `permits_contract_exchanges`, `permits_incoming_transfers` and
    `permits_outgoing_transfers`."

    Design: Corner/errors/error_transfer_not_permitted_when_plan_forbids_exchanges
    """
    env = setup_plan_env(
        plan_type="PLAN_403B", num_vendors=2,
        plan_overrides={"permits_contract_exchanges": False},
    )
    setup_active_agreement(env["plan_id"], env["vendor_ids"][1], env["employer_id"])
    participant = register_participant(env["employer_id"])
    account_one = open_contract(
        participant["id"], env["plan_id"], env["vendor_ids"][0], env["employer_id"],
        contract_number="NLA-0001", accumulated_benefit_cents=5_000_000,
    )
    account_two = open_contract(
        participant["id"], env["plan_id"], env["vendor_ids"][1], env["employer_id"],
        contract_number="CDR-0001", accumulated_benefit_cents=1_000_000,
    )
    assert validate_success(
        api.get_plan(env["plan_id"], make_officer_headers())
    )["permits_contract_exchanges"] is False

    response = api.create_movement_request(
        create_movement_request_payload(
            participant["id"], "CONTRACT_EXCHANGE", env["plan_id"], env["plan_id"],
            account_one["id"], account_two["id"], 1_000_000,
        ),
        make_sponsor_headers(env["employer_id"]),
    )

    validate_error(response, ApiErrorId.ERR_TRANSFER_NOT_PERMITTED_BY_PLAN.value)
    rows, _meta = validate_paginated(
        api.list_movement_requests(make_officer_headers(), {"participant_id": participant["id"]})
    )
    assert rows == []
