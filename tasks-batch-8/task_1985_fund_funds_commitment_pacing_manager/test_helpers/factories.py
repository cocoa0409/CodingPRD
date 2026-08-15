"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import itertools

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


DEFAULT_PROGRAM = {
    "base_currency": "USD",
    "total_nav_budget": 100_000_000,
    "strategy_cap_pct": 0.30,
    "manager_cap_pct": 0.25,
    "max_vintage_band_years": 4,
    "liquidity_buffer_min": 1_000_000,
    "overdue_grace_days": 10,
    "secondary_premium_cap_pct": 0.05,
    "secondary_discount_cap_pct": 0.10,
}


def create_program_payload(**overrides) -> dict:
    defaults = dict(DEFAULT_PROGRAM)
    defaults["program_name"] = f"Prog-{ _seq() }"
    defaults.update(overrides)
    return defaults


def create_staff_payload(staff_role="ANALYST", **overrides) -> dict:
    n = _seq()
    defaults = {
        "display_name": f"Staff {n}",
        "staff_role": staff_role,
        "email": f"staff{n}@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_pacing_plan_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "plan_label": f"PLAN-{n}",
        "horizon_years": 4,
        "start_vintage_year": 2026,
        "target_strategy_mix": [
            {"strategy": "BUYOUT", "weight": 0.5},
            {"strategy": "VENTURE", "weight": 0.3},
            {"strategy": "CREDIT", "weight": 0.2},
        ],
    }
    defaults.update(overrides)
    return defaults


def create_manager_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "legal_name": f"ManagerCap-{n}",
        "domicile_country": "US",
        "relationship_since_year": 2015,
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "fund_name": f"Fund-{n}",
        "strategy": "BUYOUT",
        "vintage_year": 2026,
        "fund_size_target": 400_000_000,
        "mgmt_fee_rate_early": 0.02,
        "mgmt_fee_rate_late": 0.01,
        "investment_period_years": 5,
        "carry_rate": 0.20,
        "hurdle_rate": 0.08,
    }
    defaults.update(overrides)
    return defaults


def create_dd_scores_payload(score=80, **overrides) -> dict:
    defaults = {
        "score_strategy_fit": score,
        "score_track_record": score,
        "score_operations": score,
        "score_compliance": score,
    }
    defaults.update(overrides)
    return defaults


def create_proposal_payload(program_id, pacing_plan_id, proposed_amount=10_000_000, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "pacing_plan_id": pacing_plan_id,
        "proposed_amount": proposed_amount,
    }
    defaults.update(overrides)
    return defaults


def create_call_payload(amount=1_000_000, purpose="INVESTMENT", due_date="2026-08-20T00:00:00Z", **overrides) -> dict:
    defaults = {"amount": amount, "purpose": purpose, "due_date": due_date}
    defaults.update(overrides)
    return defaults


def create_distribution_payload(amount=1_000_000, distribution_type="INCOME", received_at="2026-08-25T00:00:00Z", **overrides) -> dict:
    defaults = {
        "amount": amount,
        "distribution_type": distribution_type,
        "received_at": received_at,
    }
    defaults.update(overrides)
    return defaults


def create_secondary_bid_payload(vehicle_id, side="PURCHASE", nav_basis=10_000_000, price=10_000_000, **overrides) -> dict:
    defaults = {
        "vehicle_id": vehicle_id,
        "side": side,
        "nav_basis": nav_basis,
        "price": price,
    }
    if side == "PURCHASE":
        defaults.setdefault("unfunded_assumed", 0)
    defaults.update(overrides)
    return defaults


def create_snapshot_payload(as_of_quarter="2026-Q3", reported_nav=10_500_000, **overrides) -> dict:
    defaults = {"as_of_quarter": as_of_quarter, "reported_nav": reported_nav}
    defaults.update(overrides)
    return defaults


def create_look_through_line_payload(sector="TECH", geography="NA", exposure_amount=1_000_000, **overrides) -> dict:
    defaults = {"sector": sector, "geography": geography, "exposure_amount": exposure_amount}
    defaults.update(overrides)
    return defaults


def create_valuation_report_payload(as_of_quarter="2026-Q3", **overrides) -> dict:
    defaults = {"as_of_quarter": as_of_quarter}
    defaults.update(overrides)
    return defaults


def create_ledger_entry_payload(entry_kind="CONTRIBUTION", amount=1_000_000, **overrides) -> dict:
    defaults = {"entry_kind": entry_kind, "amount": amount}
    defaults.update(overrides)
    return defaults
