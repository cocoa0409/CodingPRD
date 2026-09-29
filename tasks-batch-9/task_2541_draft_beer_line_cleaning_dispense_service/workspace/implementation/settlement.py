"""Visit charge settlement, brewer funding waterfall and dispute reversal (PRD 3.7)."""
import calc
import projections
import store

NON_EXPIRED_CONTRACTS = ("DRAFT", "ACTIVE", "SUSPENDED")


def governing_contract(account_id):
    contract = store.active_contract(account_id)
    if contract is not None:
        return contract
    others = [c for c in store.account_contracts(account_id) if c["status"] != "EXPIRED"]
    if others:
        return store.by_created_desc(others)[0]
    return None


def refresh_program_totals(program):
    remaining = max(0, int(program["funding_cap_cents"]) - int(program["consumed_cents"]))
    if program["remaining_cents"] != remaining:
        program["remaining_cents"] = remaining
        store.touch(program)


def cascade_program(program):
    """Every non-expired contract naming the programme, oldest first, then accounts."""
    affected = store.sort_created(
        [c for c in store.contracts.values()
         if c.get("brewer_program_id") == program["id"]
         and c["status"] in NON_EXPIRED_CONTRACTS])
    accounts = []
    for contract in affected:
        projections.recompute_contract_funding_status(contract)
        account = store.accounts.get(contract["account_id"])
        if account is not None and all(a["id"] != account["id"] for a in accounts):
            accounts.append(account)
    for account in accounts:
        projections.recompute_billing_mode(account)


def set_program_status(program, new_status):
    if program["status"] != new_status:
        program["status"] = new_status
        store.touch(program)
        cascade_program(program)


def run_provisional(visit):
    """The provisional variant: every serviced line is billable, nothing withheld."""
    contract = governing_contract(visit["account_id"])
    serviced = projections.visit_serviced_line_count(visit["id"])
    parts = projections.visit_parts_charge_cents(visit["id"])
    visit["serviced_line_count"] = serviced
    visit["billable_line_count"] = serviced
    visit["parts_charge_cents"] = parts
    if contract is None:
        visit["cleaning_subtotal_cents"] = 0
        visit["provisional_charge_cents"] = parts
        return
    figures = calc.visit_charge(contract["per_line_rate_cents"],
                               contract["frequency_multiplier"],
                               contract["visit_base_fee_cents"], serviced, parts, False)
    visit["cleaning_subtotal_cents"] = figures["cleaning_subtotal_cents"]
    visit["provisional_charge_cents"] = figures["charge_cents"]


def recount_visit(visit):
    """Void replay: the counts follow the provisional definitions."""
    serviced = projections.visit_serviced_line_count(visit["id"])
    changed = False
    if visit["serviced_line_count"] != serviced:
        visit["serviced_line_count"] = serviced
        changed = True
    if visit["billable_line_count"] != serviced:
        visit["billable_line_count"] = serviced
        changed = True
    return changed


def run_settled(visit, apply_withhold):
    """The settled variant: only passing lines are billable; waivers withhold 10%."""
    contract = governing_contract(visit["account_id"])
    serviced = projections.visit_serviced_line_count(visit["id"])
    passed = projections.visit_passed_line_count(visit["id"])
    parts = projections.visit_parts_charge_cents(visit["id"])
    visit["serviced_line_count"] = serviced
    visit["billable_line_count"] = passed
    visit["parts_charge_cents"] = parts
    if contract is None:
        visit["cleaning_subtotal_cents"] = 0
        visit["settled_charge_cents"] = parts
        visit["brewer_funded_cents"] = 0
        visit["account_due_cents"] = parts
        visit["settlement_state"] = "SETTLED"
        return
    figures = calc.visit_charge(contract["per_line_rate_cents"],
                               contract["frequency_multiplier"],
                               contract["visit_base_fee_cents"], passed, parts,
                               apply_withhold)
    visit["cleaning_subtotal_cents"] = figures["cleaning_subtotal_cents"]
    visit["settled_charge_cents"] = figures["charge_cents"]
    apply_funding(visit, contract)
    visit["settlement_state"] = "SETTLED"


def apply_funding(visit, contract):
    """calculations.brewer_funding_waterfall over CLEANING, PARTS then BASE_FEE."""
    program_id = contract.get("brewer_program_id")
    program = store.programs.get(program_id) if program_id else None
    if (program is None or contract["funding_status"] != "BREWER_FUNDED"
            or program["status"] != "ACTIVE"):
        visit["brewer_funded_cents"] = 0
        visit["account_due_cents"] = visit["settled_charge_cents"]
        return
    granted = calc.funding_waterfall(
        program["funded_scope"], program["co_pay_bps"], program["funding_cap_cents"],
        program["consumed_cents"], visit["cleaning_subtotal_cents"],
        projections.visit_eligible_parts_cents(visit["id"]),
        contract["visit_base_fee_cents"])
    visit["brewer_funded_cents"] = granted
    visit["account_due_cents"] = visit["settled_charge_cents"] - granted
    if granted:
        program["consumed_cents"] = int(program["consumed_cents"]) + granted
        store.touch(program)
        refresh_program_totals(program)
    if int(program["consumed_cents"]) >= int(program["funding_cap_cents"]):
        set_program_status(program, "EXHAUSTED")


def reverse_settlement(visit):
    """A dispute credits the brewer programme back and zeroes the settled figures."""
    credited = int(visit["brewer_funded_cents"] or 0)
    contract = governing_contract(visit["account_id"])
    program = None
    if contract is not None and contract.get("brewer_program_id"):
        program = store.programs.get(contract["brewer_program_id"])
    if program is not None and credited:
        program["consumed_cents"] = max(0, int(program["consumed_cents"]) - credited)
        store.touch(program)
        refresh_program_totals(program)
        if (program["status"] == "EXHAUSTED"
                and int(program["consumed_cents"]) < int(program["funding_cap_cents"])):
            set_program_status(program, "ACTIVE")
    visit["settlement_state"] = "REVERSED"
    visit["settled_charge_cents"] = 0
    visit["brewer_funded_cents"] = 0
    visit["account_due_cents"] = 0
    visit["cleaning_subtotal_cents"] = 0
