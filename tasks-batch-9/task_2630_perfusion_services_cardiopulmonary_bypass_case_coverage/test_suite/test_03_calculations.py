"""Named calculations: coverage posture, the credit ledger, the readiness score and settlement."""
from test_helpers import (
    ADMIN_HEADERS,
    ERR_CE_ACTIVITY_OUTSIDE_CYCLE,
    ERR_CONTRACT_COVERAGE_INSUFFICIENT,
    ERR_READINESS_BELOW_MINIMUM,
    ERR_SETTLEMENT_PERIOD_INVALID,
    add_case,
    add_perfusionist,
    adjudicate_ce_activity,
    api_client,
    assert_case_dimensions,
    assert_ce_hours,
    assert_cents,
    assert_contract_ledger,
    assert_readiness_score,
    assign_perfusionist,
    base_setup,
    build_bypass_case,
    build_assignment,
    build_settlement_run,
    closed_case_setup,
    create_case,
    create_ce_activity,
    create_certification,
    create_perfusionist,
    create_slot,
    read_case,
    read_contract,
    read_perfusionist,
    read_slot,
    settle_month,
    validate_error,
    validate_paginated,
)


def test_coverage_posture_merges_clips_and_gates_case_creation():
    """The posture is an interval merge over the 72-hour horizon, and it gates elective work.

    PRD 3.3: The posture looks forward across a rolling horizon of 72 hours — three days, or 4320 minutes — beginning at the logical clock.
    PRD 3.3: For each of the two staffing roles `PRIMARY_CALL` and `BACKUP_CALL`, the service collects that contract's slots of that role whose `status` is `SCHEDULED` or `ACTIVE`, intersects each slot's window with the horizon and discards any slot whose intersection is empty, then sorts the surviving intersections by start instant ascending with ties broken by end instant ascending, and merges them: an interval whose start lies strictly after the running interval's end begins a new merged interval, while an interval whose start is at or before the running interval's end extends the running interval to the later of the two end instants.
    PRD 3.3: Two windows that merely touch — one ending at exactly the instant the next begins — therefore merge into one continuous stretch rather than counting as two.
    PRD 3.3: Slots in `COMPLETED` or `RELEASED`, and every `ECMO_RELIEF` slot regardless of status, are excluded from the whole computation, and a slot that started before the clock contributes only its remaining minutes.
    PRD 3.3: The contract is `COVERED` when primary-call coverage fills the horizon completely — all 4320 minutes, with no gap anywhere — and backup-call coverage reaches at least half the horizon, meaning at least 2160 minutes.
    PRD 3.3: Failing that, the contract is `THIN` when primary-call coverage reaches at least half the horizon, again 2160 minutes or more.
    PRD 3.3: Failing both, the contract is `UNCOVERED`.
    PRD 3.4: Last, the hospital must actually be covered — the contract's `coverage_posture` must be `COVERED` or `THIN`, else `ERR_CONTRACT_COVERAGE_INSUFFICIENT` — with one deliberate exception: a case whose `acuity` is `EMERGENT` is admitted at any posture, including `UNCOVERED`, because a group that refuses an emergency on paperwork grounds has misunderstood its business.

    Design: Corner/calculations/coverage_posture_merges_clips_and_gates_case_creation
    """
    env = base_setup(with_devices=False, with_slot=False, with_case=False)
    contract_id = env["contract"]["id"]
    add_perfusionist(env, "p2", full_name="Ines Duarte", employee_code="EMP-1003")
    add_perfusionist(env, "p3", full_name="Owen Baptiste", employee_code="EMP-1004")
    add_perfusionist(env, "p4", full_name="Sana Iqbal", employee_code="EMP-1005")

    assert read_contract(contract_id)["coverage_posture"] == "UNCOVERED"

    validate_error(
        api_client.create_bypass_case(
            build_bypass_case(contract_id, env["surgeon"]["id"]), ADMIN_HEADERS
        ),
        ERR_CONTRACT_COVERAGE_INSUFFICIENT,
        409,
    )
    emergent = create_case(
        contract_id,
        env["surgeon"]["id"],
        scheduled_start="2026-08-02T20:00:00Z",
        scheduled_end="2026-08-02T23:00:00Z",
        acuity="EMERGENT",
    )
    assert emergent["acuity"] == "EMERGENT"
    assert_case_dimensions(emergent, "SCHEDULED", "UNBILLED")

    slot1 = create_slot(
        contract_id,
        env["p1"]["id"],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-02T00:00:00Z",
    )
    assert read_contract(contract_id)["coverage_posture"] == "UNCOVERED"

    slot2 = create_slot(
        contract_id,
        env["p2"]["id"],
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-03T12:00:00Z",
    )
    assert read_contract(contract_id)["coverage_posture"] == "THIN"

    elective = create_case(contract_id, env["surgeon"]["id"])
    assert_case_dimensions(elective, "SCHEDULED", "UNBILLED")

    slot3 = create_slot(
        contract_id,
        env["p3"]["id"],
        window_start="2026-08-03T12:00:00Z",
        window_end="2026-08-04T00:00:00Z",
    )
    assert read_contract(contract_id)["coverage_posture"] == "THIN"

    slot4 = create_slot(
        contract_id,
        env["chief"]["id"],
        slot_type="BACKUP_CALL",
        window_start="2026-07-30T00:00:00Z",
        window_end="2026-08-02T00:00:00Z",
    )
    assert read_contract(contract_id)["coverage_posture"] == "THIN"

    slot5 = create_slot(
        contract_id,
        env["p4"]["id"],
        slot_type="BACKUP_CALL",
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-03T00:00:00Z",
    )
    assert read_contract(contract_id)["coverage_posture"] == "COVERED"

    for slot in (slot1, slot2, slot3, slot4, slot5):
        fresh = read_slot(slot["id"])
        assert fresh["status"] == "SCHEDULED"
        assert fresh["consumed"] is False


def test_ce_ledger_counts_only_in_cycle_activities_in_the_right_status():
    """The credit ledger's input set is filtered by holder, by status and by the cycle window.

    PRD 3.2: The claim is admitted only if its `activity_date` falls inside the half-open window that runs from the current `CCP` certification's `issued_on` inclusive to its `expires_on` exclusive; a claim dated on or after the expiry instant, or before the issue instant, is refused with `ERR_CE_ACTIVITY_OUTSIDE_CYCLE`.
    PRD 3.2: An accepted claim lands in `SUBMITTED` with `counted_toward_remediation` false, and it immediately raises the holder's pending credit total by its own hours.
    PRD 3.2: `ce_credits_verified` is the sum of `credit_hours` across that holder's activities whose `status` is `VERIFIED` and whose `activity_date` lies inside the current certification window, rounded half up to one decimal place.
    PRD 3.2: `ce_credits_pending` is the same sum over activities whose `status` is `SUBMITTED`.
    PRD 3.2: Activities in `REJECTED` or `REVOKED` contribute to neither total, which is what makes the ledger self-compensating.
    PRD 3.2: A `REJECTED` decision moves the claim `SUBMITTED → REJECTED` and lowers only the pending total; the verified total is untouched and no remediation banking occurs.
    PRD 3.2: Where any rule speaks of "the holder's current `CCP` certification", it means the `CCP` row with the greatest `issued_on`, with ties broken in favour of the greater `created_at`.
    PRD 3.2: A new cycle begins `ACTIVE`, with `probation_count` at 0, `remediation_credits_required` at 0 and `probation_credits_banked` at 0, and recording it re-derives the holder's credit ledger against the new window.

    Design: Corner/calculations/ce_ledger_counts_only_in_cycle_activities_in_the_right_status
    """
    holder = create_perfusionist()
    cert1 = create_certification(holder["id"])
    assert_ce_hours(holder["ce_credits_pending"], 0)
    assert_ce_hours(holder["ce_credits_verified"], 0)

    first = create_ce_activity(holder["id"], credit_hours=20, activity_date="2026-03-01T00:00:00Z")
    second = create_ce_activity(
        holder["id"], category="TECHNICAL", credit_hours=12.5, activity_date="2026-06-01T00:00:00Z"
    )
    ledger = read_perfusionist(holder["id"])
    assert_ce_hours(ledger["ce_credits_pending"], 32.5)
    assert_ce_hours(ledger["ce_credits_verified"], 0)

    validate_error(
        api_client.create_ce_activity(
            holder["id"],
            {
                "category": "CLINICAL",
                "credit_hours": 5,
                "activity_date": "2025-12-31T00:00:00Z",
                "accreditation_body": "ABCP",
            },
            ADMIN_HEADERS,
        ),
        ERR_CE_ACTIVITY_OUTSIDE_CYCLE,
        422,
    )
    validate_error(
        api_client.create_ce_activity(
            holder["id"],
            {
                "category": "CLINICAL",
                "credit_hours": 8,
                "activity_date": "2026-12-31T00:00:00Z",
                "accreditation_body": "ABCP",
            },
            ADMIN_HEADERS,
        ),
        ERR_CE_ACTIVITY_OUTSIDE_CYCLE,
        422,
    )
    assert_ce_hours(read_perfusionist(holder["id"])["ce_credits_pending"], 32.5)
    _, meta = validate_paginated(api_client.list_ce_activities(holder["id"], ADMIN_HEADERS))
    assert meta["total_count"] == 2

    create_ce_activity(
        holder["id"], category="SAFETY", credit_hours=3, activity_date="2026-01-01T00:00:00Z"
    )
    assert_ce_hours(read_perfusionist(holder["id"])["ce_credits_pending"], 35.5)

    adjudicate_ce_activity(first["id"], "VERIFIED", note="transcript checked")
    ledger = read_perfusionist(holder["id"])
    assert_ce_hours(ledger["ce_credits_verified"], 20)
    assert_ce_hours(ledger["ce_credits_pending"], 15.5)

    rejected = adjudicate_ce_activity(second["id"], "REJECTED", note="no accreditation record")
    assert rejected["status"] == "REJECTED"
    ledger = read_perfusionist(holder["id"])
    assert_ce_hours(ledger["ce_credits_pending"], 3)
    assert_ce_hours(ledger["ce_credits_verified"], 20)

    certifications, _ = validate_paginated(
        api_client.list_certifications(holder["id"], ADMIN_HEADERS)
    )
    banked = {row["id"]: row for row in certifications}[cert1["id"]]
    assert_ce_hours(banked["probation_credits_banked"], 0)
    assert banked["status"] == "ACTIVE"

    create_certification(
        holder["id"], issued_on="2026-07-01T00:00:00Z", expires_on="2027-06-30T00:00:00Z"
    )
    ledger = read_perfusionist(holder["id"])
    assert_ce_hours(ledger["ce_credits_pending"], 0)
    assert_ce_hours(ledger["ce_credits_verified"], 0)

    create_ce_activity(holder["id"], credit_hours=4, activity_date="2026-08-01T00:00:00Z")
    ledger = read_perfusionist(holder["id"])
    assert_ce_hours(ledger["ce_credits_pending"], 4)
    assert_ce_hours(ledger["ce_credits_verified"], 0)


def test_readiness_weights_clamp_and_gate_the_admission_of_a_perfusionist():
    """The admission score is weighted, clamped, rounded to three places and enforced at 0.600.

    PRD 3.2: The **admission** variant counts the holder's verified credits plus their pending credits — the group is willing to admit a perfusionist on the strength of education they have claimed but the back office has not yet adjudicated.
    PRD 3.2: Everything else is identical: a credit ratio, being the smaller of 1.0 and the counted credits divided by the certification's `cycle_credit_requirement`; an experience ratio, being the smaller of 1.0 and the holder's `career_case_count` divided by a career target of 150 completed cases; and a fatigue penalty, being eight hundredths for each case counted in `consecutive_case_count_24h` plus two hundredths for each hour counted in `ecmo_hours_rolling_7d`.
    PRD 3.2: The raw score is fifty-five hundredths of the credit ratio plus forty-five hundredths of the experience ratio, minus the fatigue penalty.
    PRD 3.2: That raw value is then clamped into the closed interval from 0 to 1 — negative results become 0 and results above 1 become 1 — and only then rounded half up to three decimal places.
    PRD 3.2: The score must clear a floor of 0.600 — that is, be at or above it — for an assignment to be admitted, and a score strictly below 0.550 at audit time is one of the two independent grounds on which a quality review may reach a systemic finding.
    PRD 3.2: The perfusionist's `readiness_score` always holds the most recently computed value, and `readiness_variant_last` records which of the two variants produced it: it is set to `ADMISSION` when the value came from an assignment-time admission computation and to `AUDIT` when the value came from a quality-review audit computation.
    PRD 3.1: A newly onboarded perfusionist has `ce_credits_verified`, `ce_credits_pending`, `readiness_score`, `consecutive_case_count_24h` and `ecmo_hours_rolling_7d` all at 0, and `readiness_variant_last` null.
    PRD 3.4: Then, in the order fixed by §2.8: the incoming perfusionist's employment must be `ACTIVE`; their `CCP` certification must exist and be in `ACTIVE` or `PROBATION`, so that a `LAPSED` or `REVOKED` credential blocks the assignment with `ERR_CERTIFICATION_NOT_CURRENT` while probation — a person under remediation but still credentialed — does not; their admission readiness score must be at or above 0.600, else `ERR_READINESS_BELOW_MINIMUM`; a covering call slot must exist; their concurrent workload must be within limits; and the contract must have accrual capacity left.
    PRD 3.4: The outgoing accrual is withdrawn first: when the case's `billing_status` is `PROVISIONAL_ACCRUED`, the contract's `accrued_case_fee_cents` falls by the case's current `accrued_fee_cents` before anything else happens, and `accrued_case_count` is left alone because the slot is being reused.

    Design: Corner/calculations/readiness_weights_clamp_and_gate_the_admission_of_a_perfusionist
    """
    env = base_setup()
    case_id = env["case"]["id"]
    contract_id = env["contract"]["id"]

    novice = create_perfusionist(
        full_name="Bea Halvorsen", employee_code="EMP-1004", career_case_count=60
    )
    create_certification(novice["id"])
    assert_readiness_score(novice["readiness_score"], 0.0)
    assert novice["readiness_variant_last"] is None

    validate_error(
        api_client.assign_perfusionist(
            case_id,
            build_assignment(novice["id"], env["case"]["version"]),
            env["chief_headers"],
        ),
        ERR_READINESS_BELOW_MINIMUM,
        422,
    )
    refused = read_perfusionist(novice["id"])
    assert_readiness_score(refused["readiness_score"], 0.0)
    assert refused["readiness_variant_last"] is None
    assert_case_dimensions(read_case(case_id), "SCHEDULED", "UNBILLED")
    assert_contract_ledger(read_contract(contract_id), 0, 0)

    staffed = assign_perfusionist(
        case_id, env["p1"]["id"], env["case"]["version"], env["chief"]["id"]
    )
    assert_case_dimensions(staffed, "STAFFED", "PROVISIONAL_ACCRUED")
    assert_cents(staffed["provisional_fee_cents"], 400000, "provisional_fee_cents")
    admitted = read_perfusionist(env["p1"]["id"])
    assert_readiness_score(admitted["readiness_score"], 0.694)
    assert admitted["readiness_variant_last"] == "ADMISSION"
    assert_ce_hours(admitted["ce_credits_pending"], 20)
    assert_ce_hours(admitted["ce_credits_verified"], 0)
    assert admitted["consecutive_case_count_24h"] == 0
    assert_contract_ledger(read_contract(contract_id), 400000, 1)

    create_certification(env["chief"]["id"])
    for hours, day in ((20, "2026-02-01T00:00:00Z"), (20, "2026-03-01T00:00:00Z"), (10, "2026-04-01T00:00:00Z")):
        create_ce_activity(env["chief"]["id"], credit_hours=hours, activity_date=day)
    assert_ce_hours(read_perfusionist(env["chief"]["id"])["ce_credits_pending"], 50)
    create_slot(contract_id, env["chief"]["id"], slot_type="BACKUP_CALL")

    superseded = assign_perfusionist(
        case_id, env["chief"]["id"], staffed["version"], env["chief"]["id"]
    )
    assert_case_dimensions(superseded, "STAFFED", "PROVISIONAL_ACCRUED")
    assert superseded["assigned_perfusionist_id"] == env["chief"]["id"]
    capped = read_perfusionist(env["chief"]["id"])
    assert_readiness_score(capped["readiness_score"], 1.0)
    assert capped["readiness_variant_last"] == "ADMISSION"
    assert_readiness_score(read_perfusionist(env["p1"]["id"])["readiness_score"], 0.694)
    assert_contract_ledger(read_contract(contract_id), 400000, 1)


def test_monthly_settlement_counts_only_final_accrued_in_period_cases():
    """Settlement gathers its four components, tiers on the pre-credit gross and invoices.

    PRD 3.10: Settlement is a monthly, contract-level act reserved to a `ContractAdmin`.
    PRD 3.10: The period must be well formed, its first instant must be at or before the logical clock — a future month cannot be settled — and it must be strictly later than the contract's `last_settlement_period` when one is set, so a month is never settled twice and months are never settled out of order; any violation is `ERR_SETTLEMENT_PERIOD_INVALID`.
    PRD 3.10: `case_fee_gross_cents` is the sum of `final_fee_cents` over the contract's cases whose `billing_status` is `FINAL_ACCRUED` and whose `bypass_ended_at` falls inside the period — cases still `PROVISIONAL_ACCRUED`, cases already `INVOICED` and cases `CREDITED` are all excluded, so a case is billed exactly once in its life.
    PRD 3.10: `ecmo_gross_cents` is the sum of `ecmo_fee_cents` over extracorporeal runs belonging to this contract's cases whose `status` is `DECANNULATED` and whose `decannulated_at` falls inside the period; note that runs are gathered by their own closure instant, not by their case's, so a run decannulated in one month against a case that came off pump in the previous one lands in the later settlement.
    PRD 3.10: `coverage_fee_cents` is the contract's `monthly_coverage_fee_cents` when its `staffing_model` is `COVERAGE_PLUS_PER_CASE` or `FULL_COVERAGE`, and 0 for a `PER_CASE` contract.
    PRD 3.10: `volume_credit_pct` is 0.00 below 5000000 cents, 0.03 from 5000000 cents inclusive, and 0.06 from 10000000 cents inclusive — the boundaries are inclusive, so a pre-credit gross of exactly 5000000 earns 0.03.
    PRD 3.10: `quality_credit_cents` is 150000 cents multiplied by the number of incident reports of this contract's cases whose `finding` is `SYSTEMIC` and whose `updated_at` falls inside the period — the reports are counted by when they were last written, which for a closed report is its closure.
    PRD 3.10: `net_settlement_cents` is the pre-credit gross minus both credits, an exact integer subtraction with no further rounding, floored at 0 so a month whose credits exceed its gross settles at zero rather than negative.
    PRD 3.10: As a side effect every settled case moves `FINAL_ACCRUED → INVOICED` with its `accrued_fee_cents` left **unchanged**, which is why invoicing does not disturb the contract's `accrued_case_fee_cents` at all: the ledger tracks what has been earned, and settlement only records that it has been billed.
    PRD 3.4: Otherwise the number of units is the whole-number result, rounded down, of the excess minutes over that threshold divided by 30 — one unit per half hour of prolonged perfusion — plus one.

    Design: Corner/calculations/monthly_settlement_counts_only_final_accrued_in_period_cases
    """
    env = closed_case_setup(
        end_bypass_overrides={
            "pump_time_minutes": 210,
            "cross_clamp_minutes": 90,
            "lowest_hematocrit_pct": 23,
            "adverse_event_count": 0,
        }
    )
    contract_id = env["contract"]["id"]
    closed = env["case"]
    assert_case_dimensions(closed, "CLOSED", "FINAL_ACCRUED")
    assert_cents(closed["final_fee_cents"], 520000, "final_fee_cents")
    assert_cents(closed["accrued_fee_cents"], 520000, "accrued_fee_cents")

    other = add_case(
        env,
        "case_b",
        scheduled_start="2026-08-03T06:00:00Z",
        scheduled_end="2026-08-03T12:00:00Z",
    )
    # Coming off pump moved the first case's covering slot ACTIVE -> COMPLETED, and
    # only a SCHEDULED or ACTIVE slot can cover an assignment, so the second case
    # needs a live call window of its own.
    create_slot(
        contract_id,
        env["p1"]["id"],
        chief_id=env["chief"]["id"],
        window_start="2026-08-03T00:00:00Z",
        window_end="2026-08-04T00:00:00Z",
    )
    other = assign_perfusionist(
        other["id"], env["p1"]["id"], other["version"], env["chief"]["id"]
    )
    assert_case_dimensions(other, "STAFFED", "PROVISIONAL_ACCRUED")
    assert_contract_ledger(read_contract(contract_id), 920000, 2)

    run = settle_month(contract_id, "2026-08")
    assert run["period"] == "2026-08"
    assert run["case_count"] == 1
    assert_cents(run["case_fee_gross_cents"], 520000, "case_fee_gross_cents")
    assert_cents(run["ecmo_gross_cents"], 0, "ecmo_gross_cents")
    assert_cents(run["coverage_fee_cents"], 1200000, "coverage_fee_cents")
    assert_cents(run["pre_credit_gross_cents"], 1720000, "pre_credit_gross_cents")
    assert abs(float(run["volume_credit_pct"]) - 0.0) < 1e-9
    assert_cents(run["volume_credit_cents"], 0, "volume_credit_cents")
    assert_cents(run["quality_credit_cents"], 0, "quality_credit_cents")
    assert_cents(run["net_settlement_cents"], 1720000, "net_settlement_cents")

    invoiced = read_case(closed["id"])
    assert_case_dimensions(invoiced, "CLOSED", "INVOICED")
    assert_cents(invoiced["accrued_fee_cents"], 520000, "accrued_fee_cents")
    assert_cents(invoiced["final_fee_cents"], 520000, "final_fee_cents")
    assert_case_dimensions(read_case(other["id"]), "STAFFED", "PROVISIONAL_ACCRUED")

    contract = read_contract(contract_id)
    assert contract["last_settlement_period"] == "2026-08"
    assert contract["version"] == run["contract_version"]
    assert_contract_ledger(contract, 920000, 2)

    for period in ("2026-08", "2026-7", "2026-09"):
        validate_error(
            api_client.create_settlement_run(
                contract_id, build_settlement_run(period), ADMIN_HEADERS
            ),
            ERR_SETTLEMENT_PERIOD_INVALID,
            422,
        )
    assert read_contract(contract_id)["last_settlement_period"] == "2026-08"
