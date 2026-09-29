"""Three denormalised ledgers driven forward and then compensated back, exactly."""
from test_helpers import (
    add_case,
    add_perfusionist,
    add_slot,
    ADMIN_HEADERS,
    adjudicate_ce_activity,
    api_client,
    assert_case_dimensions,
    assert_ce_hours,
    assert_cents,
    assert_contract_ledger,
    assert_device_state,
    assert_readiness_score,
    assign_perfusionist,
    base_setup,
    cancel_case,
    create_ce_activity,
    create_certification,
    configure_pack,
    INITIAL_CLOCK,
    read_case,
    read_checklist,
    read_contract,
    read_device,
    read_perfusionist,
    setup_verified_setup,
    validate_paginated,
)

CONTROL_WINDOW = ("2026-08-03T06:00:00Z", "2026-08-03T12:00:00Z")
FIRST_WINDOW = ("2026-08-02T06:00:00Z", "2026-08-02T12:00:00Z")
LATE_WINDOW = ("2026-08-02T13:31:00Z", "2026-08-02T19:31:00Z")
BACKUP_WINDOW_END = "2026-08-03T00:00:00Z"


def _ledger_with_a_control_accrual():
    """One accrued case that is never touched again, plus one case still scheduled.

    The control accrual is what makes a naive recomputation of the contract
    total visible: any implementation that zeroes and re-adds loses it.
    """
    env = base_setup(with_devices=False, with_case=False)
    add_perfusionist(env, "p2")
    create_certification(env["p2"]["id"])
    # A single claim may carry at most 20 credit hours, so the 30 pending hours
    # this holder needs are claimed as two in-cycle activities.
    create_ce_activity(env["p2"]["id"], credit_hours=15, activity_date="2026-03-05T00:00:00Z")
    create_ce_activity(env["p2"]["id"], credit_hours=15, activity_date="2026-03-06T00:00:00Z")
    add_slot(
        env,
        env["p2"]["id"],
        key="slot_p2",
        slot_type="BACKUP_CALL",
        window_start=INITIAL_CLOCK,
        window_end=BACKUP_WINDOW_END,
    )
    env["case_1"] = add_case(
        env, "case_1", scheduled_start=FIRST_WINDOW[0], scheduled_end=FIRST_WINDOW[1]
    )
    control = add_case(
        env, "case_2", scheduled_start=CONTROL_WINDOW[0], scheduled_end=CONTROL_WINDOW[1]
    )
    env["case_2"] = assign_perfusionist(
        control["id"], env["p1"]["id"], control["version"], env["chief"]["id"]
    )
    return env


def test_a_supersede_withdraws_and_re_adds_the_accrual_without_moving_the_count():
    """The money leaves before it returns, and the occupied accrual slot never moves.

    PRD 3.4: On success from `SCHEDULED`, the case moves `SCHEDULED → STAFFED`: `assigned_perfusionist_id` is set to the named perfusionist, the provisional fee is computed and written to `provisional_fee_cents`, the fiscal dimension moves `UNBILLED → PROVISIONAL_ACCRUED`, `accrued_fee_cents` is set to the provisional amount, and the contract absorbs it — `accrued_case_fee_cents` rises by that amount, `accrued_case_count` rises by one, and the contract's `updated_at` and `version` advance.
    PRD 3.4: Re-staffing an already `STAFFED` case is a legitimate supersede — `STAFFED → STAFFED` — and it re-prices as it goes, in a strict order that keeps the contract ledger conserved.
    PRD 3.4: The outgoing accrual is withdrawn first: when the case's `billing_status` is `PROVISIONAL_ACCRUED`, the contract's `accrued_case_fee_cents` falls by the case's current `accrued_fee_cents` before anything else happens, and `accrued_case_count` is left alone because the slot is being reused.
    PRD 3.4: Then the new assignment is written, the provisional fee is recomputed for the incoming perfusionist's case context, `billing_status` is set to `PROVISIONAL_ACCRUED`, `accrued_fee_cents` is set to the recomputed amount, and the contract's `accrued_case_fee_cents` rises by that amount.

    Design: Difficulty/compensating_invariant/assign_supersede_then_cancel_restores_contract_accrual_ledger
    """
    env = _ledger_with_a_control_accrual()
    baseline = read_contract(env["contract"]["id"])
    assert_contract_ledger(baseline, 400000, 1)
    assert_case_dimensions(env["case_2"], "STAFFED", "PROVISIONAL_ACCRUED")

    accrued = assign_perfusionist(
        env["case_1"]["id"], env["p1"]["id"], env["case_1"]["version"], env["chief"]["id"]
    )
    assert_case_dimensions(accrued, "STAFFED", "PROVISIONAL_ACCRUED")
    assert_cents(accrued["accrued_fee_cents"], 400000, "accrued_fee_cents")
    assert_cents(accrued["provisional_fee_cents"], 400000, "provisional_fee_cents")
    assert_contract_ledger(read_contract(env["contract"]["id"]), 800000, 2)

    superseded = assign_perfusionist(
        env["case_1"]["id"], env["p2"]["id"], accrued["version"], env["chief"]["id"]
    )
    assert_case_dimensions(superseded, "STAFFED", "PROVISIONAL_ACCRUED")
    assert superseded["assigned_perfusionist_id"] == env["p2"]["id"]
    assert_cents(superseded["accrued_fee_cents"], 400000, "accrued_fee_cents")
    assert_contract_ledger(read_contract(env["contract"]["id"]), 800000, 2)

    control = read_case(env["case_2"]["id"])
    assert_case_dimensions(control, "STAFFED", "PROVISIONAL_ACCRUED")
    assert_cents(control["accrued_fee_cents"], 400000, "accrued_fee_cents")


def test_the_cancellation_lands_the_contract_ledger_exactly_on_its_pre_case_baseline():
    """Three ledger movements, one exact return, and a counter that records all three.

    PRD 3.6: On cancellation the case moves to `CANCELLED` and every commitment it holds is released in one pass.
    PRD 3.6: If its `billing_status` reads `PROVISIONAL_ACCRUED`, the contract's `accrued_case_fee_cents` falls by the case's `accrued_fee_cents`, the contract's `accrued_case_count` falls by one, the fiscal dimension moves `PROVISIONAL_ACCRUED → UNBILLED` and the case's `accrued_fee_cents` becomes 0 — the cancellation performs this compensation inline and does not route through any other billing rule.
    PRD 3.6: The case's `readiness_flag` is set to `NONE` and its `setup_verified_at` to null.
    PRD 2.4: Most resources additionally carry `updated_at`, in the same timestamp format, and `version`, an integer that begins at 1 on creation and increases by exactly 1 on every mutation of that resource — including mutations the resource suffers as a consequence of an operation aimed at some other resource.

    Design: Difficulty/compensating_invariant/assign_supersede_then_cancel_restores_contract_accrual_ledger
    """
    env = _ledger_with_a_control_accrual()
    case_1 = env["case_1"]
    baseline = read_contract(env["contract"]["id"])

    accrued = assign_perfusionist(
        case_1["id"], env["p1"]["id"], case_1["version"], env["chief"]["id"]
    )
    assign_perfusionist(case_1["id"], env["p2"]["id"], accrued["version"], env["chief"]["id"])

    cancelled = cancel_case(case_1["id"], env["chief"]["id"])
    assert_case_dimensions(cancelled, "CANCELLED", "UNBILLED")
    assert_cents(cancelled["accrued_fee_cents"], 0, "accrued_fee_cents")
    assert cancelled["readiness_flag"] == "NONE"
    assert cancelled["setup_verified_at"] is None

    restored = read_contract(env["contract"]["id"])
    assert_contract_ledger(restored, 400000, 1)

    control = read_case(env["case_2"]["id"])
    assert_case_dimensions(control, "STAFFED", "PROVISIONAL_ACCRUED")
    assert_cents(control["accrued_fee_cents"], 400000, "accrued_fee_cents")

    assert cancelled["version"] == case_1["version"] + 3, (
        "the assignment, the supersede and the cancellation are three mutations of the case"
    )
    assert restored["version"] == baseline["version"] + 3, (
        "the contract suffered each of the three as a consequence, so nothing was rewound"
    )


def _two_cases_holding_one_pump():
    """One verified case and one later case, both reserving the same machine pair.

    The later window clears the 90-minute turnaround by a single minute, which
    is what lets one pump legitimately carry two reservations at once.
    """
    env = setup_verified_setup()
    later = add_case(
        env, "case_c", scheduled_start=LATE_WINDOW[0], scheduled_end=LATE_WINDOW[1]
    )
    env["case_c"] = assign_perfusionist(
        later["id"], env["p1"]["id"], later["version"], env["chief"]["id"]
    )
    env["pack_c"] = configure_pack(later["id"], env["d1"]["id"], env["p1"]["id"])
    return env


def test_cancelling_one_of_two_holders_decrements_the_reservation_instead_of_freeing_it():
    """The machine follows the recomputed count, not the identity of the cancelling case.

    PRD 3.6: On cancellation the case moves to `CANCELLED` and every commitment it holds is released in one pass.
    PRD 3.6: If its `billing_status` reads `PROVISIONAL_ACCRUED`, the contract's `accrued_case_fee_cents` falls by the case's `accrued_fee_cents`, the contract's `accrued_case_count` falls by one, the fiscal dimension moves `PROVISIONAL_ACCRUED → UNBILLED` and the case's `accrued_fee_cents` becomes 0 — the cancellation performs this compensation inline and does not route through any other billing rule.
    PRD 3.6: Each machine the case holds has its `open_reservation_count` recomputed and returns `RESERVED → AVAILABLE` when that count falls to 0, staying `RESERVED` when another case still holds it.
    PRD 3.6: Every checklist of the case in `DRAFT` or `VERIFIED` moves to `INVALIDATED` with `blood_mgmt_signoff` false.
    PRD 3.6: The case's `readiness_flag` is set to `NONE` and its `setup_verified_at` to null.
    PRD 3.6: A checklist in `DRAFT` or `VERIFIED` is driven to `INVALIDATED` either by the critical-alarm cascade of §3.7 or by the cancellation of its case, and in both instances `blood_mgmt_signoff` returns to false and `verified_at` returns to null.

    Design: Difficulty/compensating_invariant/pack_reserve_and_verify_then_cancel_restores_device_reservation_ledger
    """
    env = _two_cases_holding_one_pump()
    assert_device_state(read_device(env["d1"]["id"]), "RESERVED", open_reservation_count=2)
    assert_device_state(read_device(env["d2"]["id"]), "RESERVED", open_reservation_count=2)
    assert env["case"]["bypass_status"] == "SETUP_VERIFIED"
    assert env["checklist"]["status"] == "VERIFIED"
    assert env["checklist"]["blood_mgmt_signoff"] is True
    assert_contract_ledger(read_contract(env["contract"]["id"]), 800000, 2)

    cancelled = cancel_case(env["case"]["id"], env["chief"]["id"])
    assert_case_dimensions(cancelled, "CANCELLED", "UNBILLED")
    assert_cents(cancelled["accrued_fee_cents"], 0, "accrued_fee_cents")
    assert cancelled["setup_verified_at"] is None
    assert cancelled["readiness_flag"] == "NONE"

    withdrawn = read_checklist(env["checklist"]["id"])
    assert withdrawn["status"] == "INVALIDATED"
    assert withdrawn["blood_mgmt_signoff"] is False
    assert withdrawn["verified_at"] is None

    assert_device_state(read_device(env["d1"]["id"]), "RESERVED", open_reservation_count=1)
    assert_device_state(read_device(env["d2"]["id"]), "RESERVED", open_reservation_count=1)
    assert_contract_ledger(read_contract(env["contract"]["id"]), 400000, 1)


def test_only_the_second_cancellation_returns_the_machines_to_available():
    """The count reaches 0 before the pump is free, and no maintenance figure moves.

    PRD 3.6: Each machine the case holds has its `open_reservation_count` recomputed and returns `RESERVED → AVAILABLE` when that count falls to 0, staying `RESERVED` when another case still holds it.
    PRD 3.5: That count, `open_reservation_count`, is recomputed from scratch for each touched machine as the number of bypass cases naming that machine as either their primary or their standby whose `bypass_status` is `PACK_CONFIGURED`, `SETUP_VERIFIED` or `ON_BYPASS` — which is why it is a count rather than a flag, and why cases in `SCHEDULED`, `STAFFED`, `OFF_BYPASS`, `CLOSED` or `CANCELLED` never contribute to it.
    PRD 3.1: A commissioned device begins `AVAILABLE`, with `runtime_hours_since_service` and `alarm_count_since_service` at 0, `open_reservation_count` at 0, and `last_service_completed_at` null until its first service is recorded.

    Design: Difficulty/compensating_invariant/pack_reserve_and_verify_then_cancel_restores_device_reservation_ledger
    """
    env = _two_cases_holding_one_pump()
    cancel_case(env["case"]["id"], env["chief"]["id"])
    assert_device_state(read_device(env["d1"]["id"]), "RESERVED", open_reservation_count=1)

    cancel_case(env["case_c"]["id"], env["chief"]["id"])
    freed_primary = read_device(env["d1"]["id"])
    assert_device_state(freed_primary, "AVAILABLE", open_reservation_count=0)
    assert_device_state(read_device(env["d2"]["id"]), "AVAILABLE", open_reservation_count=0)

    assert_device_state(
        freed_primary, alarm_count_since_service=0, runtime_hours_since_service=0
    )
    assert freed_primary["last_service_completed_at"] is None, (
        "no bypass was ever run, so no maintenance figure moved through either compensation"
    )
    assert_contract_ledger(read_contract(env["contract"]["id"]), 0, 0)

    _, meta = validate_paginated(
        api_client.list_disposable_packs(ADMIN_HEADERS, params={"case_id": env["case"]["id"]})
    )
    assert meta["total_count"] == 1, "the pack survives the cancellation as the historical record"


def _split_credit_claims():
    """One holder with two fractional claims inside the cycle, both still SUBMITTED."""
    env = base_setup(with_devices=False, ce_overrides={"credit_hours": 12.5})
    env["ce2"] = create_ce_activity(
        env["p1"]["id"], credit_hours=7.5, activity_date="2026-03-05T00:00:00Z"
    )
    return env


def test_a_revoked_claim_returns_its_hours_to_neither_bucket_and_stays_on_file():
    """Two ledgers of one decimal place each, moved forward twice and back once.

    PRD 3.2: An accepted claim lands in `SUBMITTED` with `counted_toward_remediation` false, and it immediately raises the holder's pending credit total by its own hours.
    PRD 3.2: `ce_credits_verified` is the sum of `credit_hours` across that holder's activities whose `status` is `VERIFIED` and whose `activity_date` lies inside the current certification window, rounded half up to one decimal place.
    PRD 3.2: `ce_credits_pending` is the same sum over activities whose `status` is `SUBMITTED`.
    PRD 3.2: Activities in `REJECTED` or `REVOKED` contribute to neither total, which is what makes the ledger self-compensating.
    PRD 3.2: A `VERIFIED` decision moves the claim `SUBMITTED → VERIFIED`, lowers the holder's pending total by the claim's hours and raises the verified total by the same hours.
    PRD 3.2: If — and only if — the holder's `CCP` certification is in `PROBATION` at that moment, the claim is additionally marked `counted_toward_remediation` true and its hours are banked into the certification's `probation_credits_banked`; should the banked total then reach or exceed `remediation_credits_required`, the certification returns `PROBATION → ACTIVE`, its `remediation_credits_required` is zeroed and its `probation_credits_banked` is reset to 0.
    PRD 3.2: A `REVOKED` decision applies to a claim already in `VERIFIED`, moves it `VERIFIED → REVOKED`, lowers the verified total by exactly the claim's hours, and — when that claim had been marked `counted_toward_remediation` — withdraws the same hours from the certification's `probation_credits_banked` before clearing `counted_toward_remediation` back to false.

    Design: Difficulty/compensating_invariant/ce_verify_then_revoke_restores_credit_ledger_and_readiness_gate
    """
    env = _split_credit_claims()
    holder = read_perfusionist(env["p1"]["id"])
    assert_ce_hours(holder["ce_credits_verified"], 0.0)
    assert_ce_hours(holder["ce_credits_pending"], 20.0)
    assert env["ce"]["status"] == "SUBMITTED"
    assert env["ce2"]["status"] == "SUBMITTED"

    first = adjudicate_ce_activity(env["ce"]["id"], "VERIFIED")
    assert first["status"] == "VERIFIED"
    moved = read_perfusionist(env["p1"]["id"])
    assert_ce_hours(moved["ce_credits_verified"], 12.5)
    assert_ce_hours(moved["ce_credits_pending"], 7.5)

    second = adjudicate_ce_activity(env["ce2"]["id"], "VERIFIED")
    assert second["status"] == "VERIFIED"
    full = read_perfusionist(env["p1"]["id"])
    assert_ce_hours(full["ce_credits_verified"], 20.0)
    assert_ce_hours(full["ce_credits_pending"], 0.0)

    revoked = adjudicate_ce_activity(env["ce2"]["id"], "REVOKED")
    assert revoked["status"] == "REVOKED"
    assert revoked["counted_toward_remediation"] is False
    assert revoked["version"] == env["ce2"]["version"] + 2, (
        "the verification and the revocation are two mutations of a row that is retained"
    )

    compensated = read_perfusionist(env["p1"]["id"])
    assert_ce_hours(compensated["ce_credits_verified"], 12.5)
    assert_ce_hours(compensated["ce_credits_pending"], 0.0)

    cycle = validate_paginated(
        api_client.list_certifications(env["p1"]["id"], ADMIN_HEADERS, params={"cert_code": "CCP"})
    )[0][0]
    assert cycle["status"] == "ACTIVE"
    assert_ce_hours(cycle["probation_credits_banked"], 0.0)
    assert cycle["probation_count"] == 0


def test_the_restored_credit_ledger_is_the_one_the_admission_gate_reads():
    """The compensation is observable downstream: it decides the score the assignment stores.

    PRD 3.2: A `REVOKED` decision applies to a claim already in `VERIFIED`, moves it `VERIFIED → REVOKED`, lowers the verified total by exactly the claim's hours, and — when that claim had been marked `counted_toward_remediation` — withdraws the same hours from the certification's `probation_credits_banked` before clearing `counted_toward_remediation` back to false.
    PRD 3.2: The **admission** variant counts the holder's verified credits plus their pending credits — the group is willing to admit a perfusionist on the strength of education they have claimed but the back office has not yet adjudicated.
    PRD 3.2: Everything else is identical: a credit ratio, being the smaller of 1.0 and the counted credits divided by the certification's `cycle_credit_requirement`; an experience ratio, being the smaller of 1.0 and the holder's `career_case_count` divided by a career target of 150 completed cases; and a fatigue penalty, being eight hundredths for each case counted in `consecutive_case_count_24h` plus two hundredths for each hour counted in `ecmo_hours_rolling_7d`.
    PRD 3.2: The raw score is fifty-five hundredths of the credit ratio plus forty-five hundredths of the experience ratio, minus the fatigue penalty.
    PRD 3.2: That raw value is then clamped into the closed interval from 0 to 1 — negative results become 0 and results above 1 become 1 — and only then rounded half up to three decimal places.
    PRD 3.2: The perfusionist's `readiness_score` always holds the most recently computed value, and `readiness_variant_last` records which of the two variants produced it: it is set to `ADMISSION` when the value came from an assignment-time admission computation and to `AUDIT` when the value came from a quality-review audit computation.
    PRD 3.2: The score must clear a floor of 0.600 — that is, be at or above it — for an assignment to be admitted, and a score strictly below 0.550 at audit time is one of the two independent grounds on which a quality review may reach a systemic finding.

    Design: Difficulty/compensating_invariant/ce_verify_then_revoke_restores_credit_ledger_and_readiness_gate
    """
    env = _split_credit_claims()
    adjudicate_ce_activity(env["ce"]["id"], "VERIFIED")
    adjudicate_ce_activity(env["ce2"]["id"], "VERIFIED")
    adjudicate_ce_activity(env["ce2"]["id"], "REVOKED")
    restored = read_perfusionist(env["p1"]["id"])
    assert_ce_hours(restored["ce_credits_verified"], 12.5)
    assert_ce_hours(restored["ce_credits_pending"], 0.0)

    staffed = assign_perfusionist(
        env["case"]["id"], env["p1"]["id"], env["case"]["version"], env["chief"]["id"]
    )
    assert_case_dimensions(staffed, "STAFFED", "PROVISIONAL_ACCRUED")

    admitted = read_perfusionist(env["p1"]["id"])
    assert_readiness_score(admitted["readiness_score"], 0.603)
    assert admitted["readiness_variant_last"] == "ADMISSION", (
        "0.55 * 12.5 / 45 plus 0.45 * 150 / 150 is 0.602777..., which rounds to 0.603"
    )
