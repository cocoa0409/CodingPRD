"""Cascade discipline: contract -> participant -> plan (PRD 2.10)."""
import store
import calc


def recompute_vendor_account(va):
    va["vested_balance_cents"] = calc.vested_balance(va["accumulated_benefit_cents"],
                                                     va["vested_percentage_bps"])


def recompute_participant(participant, bump=False):
    """Refresh every stored participant-level aggregate.

    `bump` follows PRD 2.10: a contract-level figure that moves through a provider
    balance report, a loan disbursement, a distribution payment, a remittance deposit
    or its reversal, or a movement execution refreshes the participant row itself.
    """
    pid = participant["id"]
    open_accounts = store.accounts_of(pid, status="OPEN")
    participant["total_accumulated_benefit_cents"] = sum(
        va["accumulated_benefit_cents"] for va in open_accounts)
    participant["total_vested_balance_cents"] = sum(
        va["vested_balance_cents"] for va in open_accounts)
    participant["total_outstanding_loan_balance_cents"] = sum(
        va["outstanding_loan_balance_cents"] for va in open_accounts)
    participant["highest_outstanding_loan_12mo_cents"] = sum(
        va["highest_outstanding_loan_12mo_cents"] for va in open_accounts)
    participant["ytd_elective_deferrals_all_vendors_cents"] = sum(
        va["ytd_elective_deferrals_cents"] for va in open_accounts)
    participant["lifetime_elective_deferrals_cents"] = calc.lifetime_elective_deferrals(
        participant)
    participant["projected_annual_deferral_cents"] = sum(
        e["annual_deferral_amount_cents"] for e in store.elections_of(pid)
        if e["state"] == "EFFECTIVE")
    participant["loan_eligibility_flag"] = calc.loan_eligibility_flag(participant)
    if bump:
        store.touch(participant)


def recompute_plan_corrections(plan):
    count = 0
    for batch in store.rows(store.remittance_batches):
        if batch["plan_id"] != plan["id"]:
            continue
        for corr in store.corrections_of(batch["id"]):
            if corr["state"] == "OPEN":
                count += 1
    plan["open_correction_count"] = count
    plan["compliance_posture"] = "UNDER_CORRECTION" if count > 0 else "CLEAR"


def recompute_plan_excess(plan):
    employer = store.employers.get(plan["employer_id"])
    seen = set()
    count = 0
    for election in store.rows(store.contribution_elections):
        if election["plan_id"] != plan["id"] or election["state"] != "EFFECTIVE":
            continue
        pid = election["participant_id"]
        if pid in seen:
            continue
        seen.add(pid)
        participant = store.participants.get(pid)
        if not participant or not employer:
            continue
        agg = calc.deferral_limit_aggregate_402g(plan, participant, employer)
        if participant["projected_annual_deferral_cents"] > agg["total_limit"]:
            count += 1
    plan["projected_excess_participant_count"] = count


def recompute_plan(plan):
    recompute_plan_corrections(plan)
    recompute_plan_excess(plan)


def recompute_all_plans_for_participant(participant):
    touched = set()
    for election in store.elections_of(participant["id"]):
        touched.add(election["plan_id"])
    for plan_id in touched:
        plan = store.plans.get(plan_id)
        if plan:
            recompute_plan_excess(plan)
