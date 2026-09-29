"""Derived balances, cascades, and the segregation sweep (PRD 2.9, 2.10, 3.7-3.9)."""
import calc
import errors
from store import db, order_by
from timeutil import add_days, fmt_date, parse_date, parse_instant


# --- lookups ----------------------------------------------------------------

def money_sources_of(account_id):
    rows = [r for r in db.money_sources.values() if r["plan_account_id"] == account_id]
    return order_by(rows, "source_code")


def assignable_sources_of(account_id):
    return [r for r in money_sources_of(account_id) if r["is_assignable"]]


def snapshots_of(account_id):
    rows = [r for r in db.valuation_snapshots.values() if r["plan_account_id"] == account_id]
    return order_by(rows, "as_of_date")


def holds_of_account(account_id):
    rows = [r for r in db.segregation_holds.values() if r["plan_account_id"] == account_id]
    return order_by(rows, "placed_at")


def hold_for_case(case_id):
    for hold in order_by(list(db.segregation_holds.values()), "placed_at"):
        if hold["qdro_case_id"] == case_id:
            return hold
    return None


def drafts_of_case(case_id):
    rows = [r for r in db.draft_orders.values() if r["qdro_case_id"] == case_id]
    return order_by(rows, "received_at")


def operative_draft(case_id):
    """The most recent non-SUPERSEDED draft order on the case."""
    for draft in reversed(drafts_of_case(case_id)):
        if draft["status"] != "SUPERSEDED":
            return draft
    return None


def live_draft(case_id):
    """The case's non-terminal draft: UNDER_REVIEW or DEFICIENT."""
    for draft in reversed(drafts_of_case(case_id)):
        if draft["status"] in ("UNDER_REVIEW", "DEFICIENT"):
            return draft
    return None


def notices_of_draft(draft_id):
    rows = [r for r in db.deficiency_notices.values() if r["draft_order_id"] == draft_id]
    return order_by(rows, "notice_sequence")


def latest_notice(draft_id):
    rows = notices_of_draft(draft_id)
    return rows[-1] if rows else None


def plan_account_of_participant(participant_id):
    for account in order_by(list(db.plan_accounts.values()), "created_at"):
        if account["participant_id"] == participant_id:
            return account
    return None


def operative_plan_account(case):
    """The single plan account of the case's participant (PRD 2.6)."""
    account = plan_account_of_participant(case["participant_id"])
    if account is None:
        errors.fail(errors.ERR_PLAN_ACCOUNT_NOT_FOUND,
                    "The case's participant has no plan account.")
    return account


def ap_account_of_case(case_id):
    for account in order_by(list(db.ap_accounts.values()), "created_at"):
        if account["qdro_case_id"] == case_id:
            return account
    return None


def distributions_of(ap_account_id):
    rows = [r for r in db.distributions.values()
            if r["alternate_payee_account_id"] == ap_account_id]
    return order_by(rows, "issued_at")


def authorizations_of_case(case_id):
    rows = [r for r in db.attorney_authorizations.values() if r["qdro_case_id"] == case_id]
    return order_by(rows, "created_at")


def communications_of_case(case_id):
    rows = [r for r in db.communications.values() if r["qdro_case_id"] == case_id]
    return order_by(rows, "sent_at")


# --- derived balances (PRD 2.9) ---------------------------------------------

def recompute_plan_account(account, force=False):
    """Recompute all five derived balances together; bump the row when it moved."""
    sources = money_sources_of(account["id"])
    vested = sum(s["balance_cents"] for s in sources)
    assignable = sum(s["balance_cents"] for s in sources if s["is_assignable"])
    basis = sum(s["basis_cents"] for s in sources if s["is_assignable"])
    held = sum(h["hold_amount_cents"] for h in holds_of_account(account["id"])
               if h["status"] == "HELD")
    figures = {
        "vested_balance_cents": vested,
        "assignable_base_cents": assignable,
        "after_tax_basis_cents": basis,
        "held_amount_cents": held,
        "available_balance_cents": vested - held,
    }
    changed = any(account.get(k) != v for k, v in figures.items())
    account.update(figures)
    if changed or force:
        db.touch(account)
    return account


def recompute_ap_account(account):
    """Reconcile the payee account's totals from the ISSUED set alone."""
    issued = [d for d in distributions_of(account["id"]) if d["status"] == "ISSUED"]
    account["total_distributed_gross_cents"] = sum(d["gross_amount_cents"] for d in issued)
    if account["payment_mode"] == "SEPARATE_INTEREST":
        account["balance_cents"] = (account["_established_balance_cents"]
                                    - sum(d["gross_amount_cents"] for d in issued))
        account["after_tax_basis_cents"] = (account["_established_basis_cents"]
                                           - sum(d["basis_recovery_cents"] for d in issued))
    return account


# --- correspondence ---------------------------------------------------------

def append_communication(case, recipient_type, template_code, disclosure_level, origin,
                         attorney_email=None):
    row = db.new_row("Communication", {
        "qdro_case_id": case["id"],
        "recipient_type": recipient_type,
        "template_code": template_code,
        "disclosure_level": disclosure_level,
        "attorney_email": attorney_email,
        "origin": origin,
        "sent_at": db.now_iso(),
    })
    db.communications[row["id"]] = row
    return row


def append_party_pair(case, template_code, payee_level):
    """The participant entry first, then the alternate payee's (the pinned order)."""
    append_communication(case, "PARTICIPANT", template_code, "FULL", "SYSTEM")
    append_communication(case, "ALTERNATE_PAYEE", template_code, payee_level, "SYSTEM")


# --- operative case terms ---------------------------------------------------

def copy_operative_terms(case, draft):
    """The case's five operative terms are copied from the draft; clients never send them."""
    case["approach"] = draft["proposed_approach"]
    case["formula_code"] = draft["proposed_formula_code"]
    case["assigned_percentage_bps"] = draft["proposed_percentage_bps"]
    case["assigned_flat_amount_cents"] = draft["proposed_flat_amount_cents"]
    case["shared_payment_end_date"] = draft["proposed_shared_payment_end_date"]


def sized_assignment(case):
    """(plan, participant, account, assignable sources, base, gross assigned amount)."""
    participant = db.participants[case["participant_id"]]
    plan = db.plans[participant["plan_id"]]
    account = operative_plan_account(case)
    sources = assignable_sources_of(account["id"])
    base = sum(s["balance_cents"] for s in sources)
    capped = calc.gross_assigned_amount(plan, case, participant, base)
    return plan, participant, account, sources, base, capped


# --- earnings window (PRD 3.5) ----------------------------------------------

def baseline_snapshot(account_id, valuation_date):
    """The snapshot whose as_of_date equals the case's valuation_date, exactly."""
    for snapshot in snapshots_of(account_id):
        if snapshot["as_of_date"] == valuation_date:
            return snapshot
    return None


def endpoint_snapshot(account_id, segregation_date, baseline):
    """The earliest snapshot on or after the segregation date; else the baseline itself."""
    candidates = [s for s in snapshots_of(account_id)
                  if parse_date(s["as_of_date"]) >= segregation_date]
    if not candidates:
        return baseline
    return candidates[0]


def earnings_figures(plan, case, account, allocations, segregation_date):
    """(credited growth bps, per-source earnings, total earnings) for the interval."""
    baseline = baseline_snapshot(account["id"], case["valuation_date"])
    if baseline is None:
        return 0, [0 for _ in allocations], 0
    endpoint = endpoint_snapshot(account["id"], segregation_date, baseline)
    growth = calc.credited_growth_bps(plan, baseline, endpoint, segregation_date)
    per_source = calc.per_source_earnings(allocations, growth)
    return growth, per_source, sum(per_source)


# --- the projection read (PRD 3.5) ------------------------------------------

def benefit_projection(case, approach_override):
    plan, participant, account, sources, base, capped = sized_assignment(case)
    effective = approach_override if approach_override is not None else case["approach"]
    projected = {
        "assignable_base_cents": base,
        "gross_assigned_amount_cents": capped,
        "effective_approach": effective,
        "earnings_growth_bps": 0,
        "earnings_adjustment_cents": 0,
        "separate_interest_balance_cents": 0,
        "shared_payment_per_period_cents": 0,
        "after_tax_basis_carryover_cents": 0,
        "valuation_snapshot_count": len(snapshots_of(account["id"])),
    }
    if effective == "SEPARATE_INTEREST":
        allocations = calc.per_source_allocation(capped, sources, base)
        growth, _per_source, earnings = earnings_figures(
            plan, case, account, allocations, db.today())
        projected["earnings_growth_bps"] = growth
        projected["earnings_adjustment_cents"] = earnings
        projected["separate_interest_balance_cents"] = capped + earnings
        projected["after_tax_basis_carryover_cents"] = calc.basis_carryover(sources, allocations)
    elif effective == "SHARED_PAYMENT":
        projected["shared_payment_per_period_cents"] = calc.shared_payment_per_period(account, case)
    return projected


# --- tax ledger (PRD 3.9) ---------------------------------------------------

def append_tax_report(distribution, sign=1, correction_of=None):
    row = db.new_row("TaxReport", {
        "distribution_id": distribution["id"],
        "alternate_payee_account_id": distribution["alternate_payee_account_id"],
        "correction_of_tax_report_id": correction_of,
        "form_code": "FORM_1099R",
        "reportable_gross_cents": sign * distribution["gross_amount_cents"],
        "reportable_taxable_cents": sign * distribution["taxable_amount_cents"],
        "federal_withheld_cents": sign * distribution["federal_withheld_cents"],
        "distribution_code": distribution["distribution_code"],
        "tax_year": distribution["tax_year"],
        "written_at": db.now_iso(),
    })
    db.tax_reports[row["id"]] = row
    return row


def original_tax_report(distribution_id):
    rows = [r for r in db.tax_reports.values()
            if r["distribution_id"] == distribution_id
            and r["correction_of_tax_report_id"] is None]
    rows = order_by(rows, "written_at")
    return rows[0] if rows else None


# --- hold sizing / capacity (PRD 3.4) ---------------------------------------

def hold_capacity_check(case, account, candidate):
    """The candidate plus every OTHER HELD hold on the account must fit the vested balance."""
    other_held = sum(h["hold_amount_cents"] for h in holds_of_account(account["id"])
                     if h["status"] == "HELD" and h["qdro_case_id"] != case["id"])
    if candidate + other_held > account["vested_balance_cents"]:
        errors.fail(errors.ERR_HOLD_CAPACITY_EXCEEDED,
                    "Aggregate segregation exposure exceeds the account's vested balance.")


def expire_issued_notices(draft_id):
    """Move every still-ISSUED notice on the draft to EXPIRED; return the ids."""
    expired = []
    for notice in notices_of_draft(draft_id):
        if notice["status"] == "ISSUED":
            notice["status"] = "EXPIRED"
            db.touch(notice)
            expired.append(notice["id"])
    return expired


# --- the three-phase sweep (PRD 3.8) ----------------------------------------

def run_segregation_sweep():
    now = db.now()
    today = db.today()
    expired_hold_ids = []
    lapsed_case_ids = []
    denied_draft_order_ids = []
    expired_notice_ids = []
    closed_ap_account_ids = []

    # Phase 1 - lapsed segregation, in placed_at ascending order.
    holds = order_by(list(db.segregation_holds.values()), "placed_at")
    for hold in holds:
        if hold["status"] != "HELD":
            continue
        if not now > parse_instant(hold["expires_at"]):
            continue
        hold["status"] = "EXPIRED"
        db.touch(hold)
        expired_hold_ids.append(hold["id"])
        account = db.plan_accounts.get(hold["plan_account_id"])
        if account is not None:
            recompute_plan_account(account)
        case = db.qdro_cases.get(hold["qdro_case_id"])
        if case is None:
            continue
        case["segregation_status"] = "LAPSED"
        lapsed_case_ids.append(case["id"])
        draft = live_draft(case["id"])
        if draft is not None:
            draft["status"] = "DENIED"
            draft["denial_reason"] = "SEGREGATION_LAPSED"
            db.touch(draft)
            denied_draft_order_ids.append(draft["id"])
            expired_notice_ids.extend(expire_issued_notices(draft["id"]))
            case["review_status"] = "DENIED"
        append_party_pair(case, "SEGREGATION_LAPSE_NOTICE", "LIMITED")
        db.touch(case)

    # Phase 2 - expired resubmission windows, in issued_at ascending order.
    notices = order_by(list(db.deficiency_notices.values()), "issued_at")
    for notice in notices:
        if notice["status"] != "ISSUED":
            continue
        if not now > parse_instant(notice["resubmission_deadline_at"]):
            continue
        notice["status"] = "EXPIRED"
        db.touch(notice)
        expired_notice_ids.append(notice["id"])

    # Phase 3 - exhausted shared-payment streams.
    accounts = order_by(list(db.ap_accounts.values()), "established_at")
    for account in accounts:
        if account["status"] != "ESTABLISHED" or account["payment_mode"] != "SHARED_PAYMENT":
            continue
        end_date = account["shared_payment_end_date"]
        if not end_date or not today > parse_date(end_date):
            continue
        account["status"] = "CLOSED"
        db.touch(account)
        closed_ap_account_ids.append(account["id"])

    return {
        "evaluated_count": (len(expired_hold_ids) + len(expired_notice_ids)
                            + len(closed_ap_account_ids)),
        "expired_hold_ids": expired_hold_ids,
        "lapsed_case_ids": lapsed_case_ids,
        "denied_draft_order_ids": denied_draft_order_ids,
        "expired_notice_ids": expired_notice_ids,
        "closed_ap_account_ids": closed_ap_account_ids,
    }
