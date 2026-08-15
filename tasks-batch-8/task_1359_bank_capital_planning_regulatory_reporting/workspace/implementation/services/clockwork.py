"""Time-driven transitions fired when the logical clock advances (PRD 2.5)."""

from __future__ import annotations

from datetime import datetime, timezone

import db
from db import (
    banks, reporting_periods, capital_instruments, distribution_requests,
    capital_plans, call_reports, touch,
)
from services.core import (
    recompute_instrument_reg_cap, recompute_mdba, refresh_open_issuance_headrooms,
    supersede_plan, release_distribution_reservation,
    DISTRIBUTION_WINDOW_DAYS,
)


def _jan1(plan_year: int) -> datetime:
    return datetime(plan_year, 1, 1, tzinfo=timezone.utc)


def advance_clock(new_dt: datetime) -> None:
    """Fire every time-triggered transition whose moment has arrived."""
    for bank in list(banks.values()):
        capacity_changed = False

        # --- ReportingPeriod OPEN -> FILING_DUE ---
        for p in list(reporting_periods.values()):
            if p["bank_id"] != bank["id"]:
                continue
            if p["status"] == "OPEN" and new_dt >= p["_period_end_boundary"]:
                p["status"] = "FILING_DUE"
                touch(p)

        # --- supervisory escalation for periods past filing deadline with no
        # submitted/accepted call report ---
        for p in list(reporting_periods.values()):
            if p["bank_id"] != bank["id"]:
                continue
            if p.get("_filing_due_dt") is None or new_dt <= p["_filing_due_dt"]:
                continue
            has_submitted = any(
                r["reporting_period_id"] == p["id"] and r["status"] in ("SUBMITTED", "ACCEPTED")
                for r in call_reports.values()
            )
            if not has_submitted and bank["supervisory_status"] == "NORMAL":
                bank["supervisory_status"] = "UNDER_LETTER"
                touch(bank, bump=False)

        # --- CapitalPlan APPROVED -> EFFECTIVE on plan_year-01-01 ---
        for plan in list(capital_plans.values()):
            if plan["bank_id"] != bank["id"] or plan["status"] != "APPROVED":
                continue
            if new_dt >= _jan1(plan["plan_year"]):
                # supersede any older EFFECTIVE plan first
                for other in list(capital_plans.values()):
                    if (other["bank_id"] == bank["id"] and other["id"] != plan["id"]
                            and other["status"] == "EFFECTIVE"):
                        supersede_plan(other, bank)
                        capacity_changed = True
                plan["status"] = "EFFECTIVE"
                touch(plan)
                recompute_mdba(bank)
                capacity_changed = True

        # --- CapitalDistributionRequest APPROVED_NOT_EXECUTED -> EXPIRED ---
        for d in list(distribution_requests.values()):
            if d["bank_id"] != bank["id"] or d["status"] != "APPROVED_NOT_EXECUTED":
                continue
            pay = d.get("_proposed_payment_date")
            if pay is not None and new_dt.date() > pay.fromordinal(pay.toordinal() + DISTRIBUTION_WINDOW_DAYS):
                release_distribution_reservation(d, bank)
                d["status"] = "EXPIRED"
                touch(d)
                capacity_changed = True

        # --- CapitalInstrument SUBORDINATED_DEBT maturity + haircut decay ---
        for inst in list(capital_instruments.values()):
            if inst["bank_id"] != bank["id"]:
                continue
            if inst["instrument_subtype"] == "SUBORDINATED_DEBT" and inst["status"] == "OUTSTANDING":
                maturity = inst.get("_maturity_date")
                if maturity is not None and new_dt.date() >= maturity:
                    inst["status"] = "MATURED"
                    inst["t2_haircut_pct"] = 100
                    inst["regulatory_capital_cents"] = 0
                    touch(inst)
                    capacity_changed = True
                else:
                    if recompute_instrument_reg_cap(inst, new_dt.date()):
                        touch(inst)

        if capacity_changed:
            recompute_mdba(bank)
            refresh_open_issuance_headrooms(bank)
            touch(bank, bump=True)


def activate_plan_if_due(bank: dict, plan: dict) -> None:
    """Immediately activate an APPROVED plan whose plan year has already begun."""
    if plan["status"] == "APPROVED" and plan_year_start(plan["plan_year"]) <= db.get_current_utc_dt():
        for other in list(capital_plans.values()):
            if (other["bank_id"] == bank["id"] and other["id"] != plan["id"]
                    and other["status"] == "EFFECTIVE"):
                supersede_plan(other, bank)
        plan["status"] = "EFFECTIVE"
        touch(plan)
        recompute_mdba(bank)


def plan_year_start(plan_year: int) -> datetime:
    return datetime(plan_year, 1, 1, tzinfo=timezone.utc)
