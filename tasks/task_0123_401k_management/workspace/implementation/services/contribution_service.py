"""ContributionRecord posting & listing."""

import db
from config import (
    PARTICIPANT_ACTIVE, PARTICIPANT_SUSPENDED, PLAN_ACTIVE, CONTRIB_POSTED,
    EMPLOYEE_ANNUAL_LIMIT_CENTS, EMPLOYER_ANNUAL_LIMIT_CENTS,
)
from errors import (
    AppError,
    ERR_INVALID_REQUEST,
    ERR_PLAN_NOT_ACTIVE,
    ERR_PARTICIPANT_NOT_IN_VALID_STATE,
    ERR_DUPLICATE_PAY_PERIOD,
    ERR_DEFERRAL_SUSPENDED,
    ERR_ANNUAL_EMPLOYEE_LIMIT_EXCEEDED,
)
from utils import stamp_ledger_create, bump_version, parse_date
from services.calculations import (
    compute_employee_amount_cents, compute_employer_match_cents,
)


def _ensure_plan_active(plan: dict) -> None:
    if plan["status"] != PLAN_ACTIVE:
        raise AppError(ERR_PLAN_NOT_ACTIVE, "Plan must be ACTIVE.", 409)


def post_contribution(plan: dict, participant: dict, payload: dict) -> dict:
    _ensure_plan_active(plan)
    # PRD §2.8 mandates ERR_DEFERRAL_SUSPENDED on contribution attempts during
    # the suspension window. SUSPENDED participants must pass the state gate so
    # the business-rule suspension check (and the higher-priority uniqueness check)
    # can fire per §2.6's intra-bucket order.
    if participant["status"] not in (PARTICIPANT_ACTIVE, PARTICIPANT_SUSPENDED):
        raise AppError(ERR_PARTICIPANT_NOT_IN_VALID_STATE,
                       "Participant must be ACTIVE for contribution posting.", 409)

    if not isinstance(payload, dict):
        raise AppError(ERR_INVALID_REQUEST, "Request body must be a JSON object.", 400)
    pay_period_end = payload.get("pay_period_end")
    gross_pay = payload.get("gross_pay_cents")
    if not isinstance(pay_period_end, str) or parse_date(pay_period_end) is None:
        raise AppError(ERR_INVALID_REQUEST, "pay_period_end must be YYYY-MM-DD.", 400)
    if not isinstance(gross_pay, int) or isinstance(gross_pay, bool) or gross_pay < 0:
        raise AppError(ERR_INVALID_REQUEST, "gross_pay_cents must be a non-negative integer.", 400)

    # Priority 7: pay-period uniqueness
    for c in db.contribution_records.values():
        if c.get("participant_id") == participant["id"] \
                and c.get("pay_period_end") == pay_period_end:
            raise AppError(ERR_DUPLICATE_PAY_PERIOD,
                           "Duplicate contribution for this participant & pay_period_end.", 409)

    # Priority 8: deferral suspension
    clock = db.plan_clocks.get(plan["id"])
    current_date = clock["current_date"] if clock else None
    dsu = participant.get("deferral_suspended_until")
    if dsu and current_date is not None and current_date <= dsu:
        raise AppError(ERR_DEFERRAL_SUSPENDED,
                       "Participant deferral is suspended.", 409)

    # Compute employee_amount_cents
    employee_amount = compute_employee_amount_cents(gross_pay,
                                                    participant.get("elected_deferral_pct", 0))

    # Priority 12: annual employee limit
    year = parse_date(pay_period_end).year
    ytd_employee = 0
    ytd_employer = 0
    for c in db.contribution_records.values():
        if c.get("participant_id") != participant["id"]:
            continue
        cd = parse_date(c.get("pay_period_end", ""))
        if cd is None or cd.year != year:
            continue
        ytd_employee += int(c.get("employee_amount_cents", 0))
        ytd_employer += int(c.get("employer_match_cents", 0))
    if ytd_employee + employee_amount > EMPLOYEE_ANNUAL_LIMIT_CENTS:
        raise AppError(ERR_ANNUAL_EMPLOYEE_LIMIT_EXCEEDED,
                       "Year-to-date + proposed employee contribution would exceed limit.", 422)

    # Compute employer match — silently cap to remaining employer cap
    proposed_employer = compute_employer_match_cents(plan, gross_pay,
                                                     participant.get("elected_deferral_pct", 0))
    remaining_employer_cap = max(0, EMPLOYER_ANNUAL_LIMIT_CENTS - ytd_employer)
    if proposed_employer > remaining_employer_cap:
        proposed_employer = remaining_employer_cap

    record = {
        "plan_id": plan["id"],
        "participant_id": participant["id"],
        "pay_period_end": pay_period_end,
        "gross_pay_cents": int(gross_pay),
        "employee_amount_cents": int(employee_amount),
        "employer_match_cents": int(proposed_employer),
        "status": CONTRIB_POSTED,
    }
    stamp_ledger_create(record)
    db.contribution_records[record["id"]] = record

    # Side effects on participant aggregates
    participant["cumulative_employee_contribution_cents"] = \
        int(participant.get("cumulative_employee_contribution_cents", 0)) + int(employee_amount)
    participant["cumulative_employer_match_cents"] = \
        int(participant.get("cumulative_employer_match_cents", 0)) + int(proposed_employer)
    participant["total_account_balance_cents"] = \
        int(participant.get("total_account_balance_cents", 0)) + int(employee_amount) + int(proposed_employer)
    bump_version(participant)
    return record


def list_contributions(plan: dict, participant: dict, limit: int, offset: int,
                       year: int | None):
    items = [c for c in db.contribution_records.values()
             if c.get("plan_id") == plan["id"] and c.get("participant_id") == participant["id"]]
    if year is not None:
        items = [c for c in items if parse_date(c.get("pay_period_end", "")) and parse_date(c["pay_period_end"]).year == year]
    items.sort(key=lambda c: c.get("created_at", ""))
    total = len(items)
    return items[offset:offset + limit], total
