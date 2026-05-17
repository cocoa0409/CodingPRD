"""Ledger / cascade helpers shared by routes.

These keep money mutations, form issuance, and excess assessments in one
place so route handlers stay thin.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from ..clock import current_date, current_year, date_iso
from ..store import store
from .calculations import (
    applicable_contribution_cap_cents,
    assess_excess_contribution,
    compute_federal_withholding,
    compute_rmd_amount_cents,
    percent_of,
)
from .constants import (
    FORFEIT_PENALTY_RATE,
    MISSED_RMD_PENALTY_RATE,
    RMD_AGE,
)
from .lookups import (
    bump_version,
    claim_for_account,
    init_common,
    init_event,
    parse_iso_date_str,
    ts,
)


# ---------------------------------------------------------------------------
# Form 1099-R issuance
# ---------------------------------------------------------------------------

def issue_form_for_distribution(distribution: dict[str, Any], account: dict[str, Any]) -> dict[str, Any]:
    reason = distribution["distribution_reason"]
    if reason == "EARLY":
        box7 = "1"
    elif reason in ("NORMAL", "RMD"):
        box7 = "7"
    elif reason == "DEATH":
        box7 = "4"
    elif reason == "CONVERSION":
        box7 = "G"
    elif reason == "EXCESS_REMOVAL":
        # Treat reversal-emitted distribution like a normal box7
        box7 = "7"
    else:
        box7 = "7"

    box1 = distribution["gross_amount_cents"]
    if account["account_type"] == "TRADITIONAL":
        box2a = box1
    else:
        box2a = 0
    box4 = distribution["federal_withholding_cents"]

    form = init_event(
        {
            "tax_year": distribution["tax_year"],
            "recipient_participant_id": account["participant_id"],
            "source_event_type": "DISTRIBUTION",
            "source_event_id": distribution["id"],
            "box1_gross_distribution_cents": box1,
            "box2a_taxable_amount_cents": box2a,
            "box4_federal_withholding_cents": box4,
            "box7_distribution_code": box7,
            "status": "ISSUED",
        }
    )
    store().forms_1099r[form["id"]] = form
    return form


def issue_form_for_conversion(conversion: dict[str, Any]) -> dict[str, Any]:
    box1 = conversion["amount_cents"]
    box2a = 0 if conversion["backdoor_flag"] else box1
    form = init_event(
        {
            "tax_year": current_year(),
            "recipient_participant_id": conversion["participant_id"],
            "source_event_type": "CONVERSION",
            "source_event_id": conversion["id"],
            "box1_gross_distribution_cents": box1,
            "box2a_taxable_amount_cents": box2a,
            "box4_federal_withholding_cents": 0,
            "box7_distribution_code": "G",
            "status": "ISSUED",
        }
    )
    store().forms_1099r[form["id"]] = form
    return form


def issue_form_for_excess_penalty(
    penalty: dict[str, Any], recipient_participant_id: str, box7: str = "8"
) -> dict[str, Any]:
    excess = penalty["excess_amount_cents"]
    form = init_event(
        {
            "tax_year": penalty["tax_year"],
            "recipient_participant_id": recipient_participant_id,
            "source_event_type": "EXCESS_PENALTY",
            "source_event_id": penalty["id"],
            "box1_gross_distribution_cents": excess,
            "box2a_taxable_amount_cents": excess,
            "box4_federal_withholding_cents": 0,
            "box7_distribution_code": box7,
            "status": "ISSUED",
        }
    )
    store().forms_1099r[form["id"]] = form
    return form


# ---------------------------------------------------------------------------
# Excess contribution sweep (manual + year-end)
# ---------------------------------------------------------------------------

def run_excess_sweep_for_account(account: dict[str, Any], tax_year: int) -> dict[str, Any] | None:
    """Assess excess contributions for `account` for `tax_year`.

    Returns the created ExcessPenalty (or None if no penalty).
    Performs cascading side effects: debits balance, issues 1099-R.
    """
    participant = store().participants.get(account["participant_id"])
    if participant is None:
        return None

    ytd_for_year = sum(
        c["amount_cents"]
        for c in store().contributions.values()
        if c["account_id"] == account["id"]
        and c["status"] == "POSTED"
        and c["tax_year"] == tax_year
    )
    dob = parse_iso_date_str(participant["date_of_birth"])
    cap = applicable_contribution_cap_cents(dob, tax_year)  # type: ignore[arg-type]
    result = assess_excess_contribution(
        ytd_contribution_cents=ytd_for_year,
        applicable_cap_cents=cap,
    )
    if result is None:
        return None
    excess, penalty_amt = result

    penalty = init_event(
        {
            "account_id": account["id"],
            "tax_year": tax_year,
            "excess_amount_cents": excess,
            "penalty_amount_cents": penalty_amt,
            "assessed_at": ts(),
        }
    )
    store().excess_penalties[penalty["id"]] = penalty

    # Debit account
    account["balance_cents"] = account["balance_cents"] - penalty_amt
    bump_version(account)

    issue_form_for_excess_penalty(penalty, recipient_participant_id=account["participant_id"], box7="8")
    return penalty


def run_missed_rmd_sweep_for_account(account: dict[str, Any], tax_year: int) -> dict[str, Any] | None:
    """Assess missed-RMD penalty (SECURE 2.0 25%) on `account` for `tax_year`.

    Returns the created ExcessPenalty or None when no missed RMD applies.
    """
    participant = store().participants.get(account["participant_id"])
    if participant is None:
        return None
    dob = parse_iso_date_str(participant["date_of_birth"])
    age_dec31 = tax_year - dob.year  # type: ignore[union-attr]

    is_inherited = account.get("inherited_from_participant_id") is not None

    # Sweep applies to: every Traditional account with age >= 73, plus every
    # Inherited IRA regardless of underlying type.
    if not is_inherited:
        if account["account_type"] != "TRADITIONAL":
            return None
        if age_dec31 < RMD_AGE:
            return None

    # Compute required RMD for the just-closed tax year
    inheritance_start_year = None
    if is_inherited and account.get("inheritance_start_date"):
        inheritance_start_year = int(account["inheritance_start_date"][:4])

    required = compute_rmd_amount_cents(
        account_type=account["account_type"],
        inherited_from_participant_id=account.get("inherited_from_participant_id"),
        prior_year_end_balance_cents=account["prior_year_end_balance_cents"],
        date_of_birth=dob,  # type: ignore[arg-type]
        tax_year=tax_year,
        inheritance_start_year=inheritance_start_year,
    )
    if required <= 0:
        return None

    # Has an RMD-coded distribution been recorded for this account in this tax_year?
    rmd_taken = any(
        d["account_id"] == account["id"]
        and d["distribution_reason"] == "RMD"
        and d["tax_year"] == tax_year
        for d in store().distributions.values()
    )
    if rmd_taken:
        return None

    penalty_amount = percent_of(required, MISSED_RMD_PENALTY_RATE)
    penalty = init_event(
        {
            "account_id": account["id"],
            "tax_year": tax_year,
            "excess_amount_cents": required,
            "penalty_amount_cents": penalty_amount,
            "assessed_at": ts(),
        }
    )
    store().excess_penalties[penalty["id"]] = penalty

    account["balance_cents"] = account["balance_cents"] - penalty_amount
    bump_version(account)

    issue_form_for_excess_penalty(penalty, recipient_participant_id=account["participant_id"], box7="8")
    return penalty


# ---------------------------------------------------------------------------
# Forfeit sweep (inherited claim past deadline)
# ---------------------------------------------------------------------------

def run_forfeit_sweep() -> list[str]:
    """Forfeit any claim whose deadline has passed while balance > 0.

    Applies to CLAIMED or SUSPENDED claims (per scaffold state machine).
    Returns the list of claim ids that were forfeited.
    """
    forfeited: list[str] = []
    cur = current_date()
    for claim in list(store().claims.values()):
        if claim["status"] not in ("CLAIMED", "SUSPENDED"):
            continue
        deadline = parse_iso_date_str(claim["deadline_date"])
        if deadline is None or cur <= deadline:
            continue
        account = store().accounts.get(claim["account_id"])
        if account is None:
            continue
        residual = account["balance_cents"]
        if residual <= 0:
            continue

        # Issue penalty
        penalty_amount = percent_of(residual, FORFEIT_PENALTY_RATE)
        penalty = init_event(
            {
                "account_id": account["id"],
                "tax_year": current_year(),
                "excess_amount_cents": residual,
                "penalty_amount_cents": penalty_amount,
                "assessed_at": ts(),
            }
        )
        store().excess_penalties[penalty["id"]] = penalty

        # Update claim
        claim["status"] = "FORFEITED"
        bump_version(claim)

        # Account flips to FROZEN
        account["status"] = "FROZEN"
        bump_version(account)

        # Issue 1099-R
        issue_form_for_excess_penalty(
            penalty,
            recipient_participant_id=account["participant_id"],
            box7="8",
        )
        forfeited.append(claim["id"])
    return forfeited


# ---------------------------------------------------------------------------
# Year-end roll-forward
# ---------------------------------------------------------------------------

def run_year_roll() -> dict[str, Any]:
    """Atomic year-boundary: snapshot, advance, reset, sweep excess, sweep missed-RMD.

    Returns a summary suitable for inclusion in the clock state response.
    """
    from ..clock import clock as _clock

    closing_year = current_year()

    # 1) snapshot
    for account in store().accounts.values():
        account["prior_year_end_balance_cents"] = account["balance_cents"]
        bump_version(account)

    # 2) increment clock year (advance to Jan 1)
    cur = current_date()
    from datetime import date as _date
    new_date = _date(closing_year + 1, 1, 1)
    _clock.set_date(new_date)

    # 3) reset ytd contribution
    for account in store().accounts.values():
        account["ytd_contribution_cents"] = 0
        bump_version(account)

    # 4) Excess sweep for closing year
    for account in list(store().accounts.values()):
        run_excess_sweep_for_account(account, closing_year)

    # 5) Missed-RMD sweep for closing year
    for account in list(store().accounts.values()):
        run_missed_rmd_sweep_for_account(account, closing_year)

    return {
        "closed_tax_year": closing_year,
        "current_date": new_date.isoformat(),
        "clock_year": new_date.year,
    }
