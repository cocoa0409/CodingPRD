"""Cross-entity side-effect helpers (cascades, draw creation, ledger sync)."""
from db import store
from models import (_base_record, touch, project_billed_to_date)
from calculations import draw_amount, contract_total
from helpers import round_half_up_div


def recompute_estimate(project):
    """estimate variant of contract_total -> estimate_total_cents."""
    project["estimate_total_cents"] = contract_total(project, "estimate")


def create_draw(project, draw_type, requested_pct_bps=None, due_utc=None):
    """Create a Draw in PENDING with waterfall-capped amount (PRD §3.8)."""
    billed = project_billed_to_date(project["id"])
    amount = draw_amount(project, draw_type, requested_pct_bps, billed)
    rec = _base_record()
    rec.update({
        "project_id": project["id"],
        "draw_type": draw_type,
        "requested_pct_bps": requested_pct_bps,
        "amount_cents": amount,
        "due_utc": due_utc,
        "late_fee_cents": 0,
        "status": "PENDING",
    })
    store.draws[rec["id"]] = rec
    return rec


def create_progress_adjustment_draw(project, delta_cents):
    """Change-order approve creates a PROGRESS draw for max(0, delta_cents),
    still waterfall-capped so cumulative billing never exceeds the (new) contract
    total (PRD §3.7 + §3.8 no-over-bill invariant)."""
    raw = max(0, delta_cents)
    billed = project_billed_to_date(project["id"])
    remaining = project["contract_total_cents"] - billed
    amount = min(raw, remaining)
    if amount < 0:
        amount = 0
    rec = _base_record()
    rec.update({
        "project_id": project["id"],
        "draw_type": "PROGRESS",
        "requested_pct_bps": None,
        "amount_cents": amount,
        "due_utc": None,
        "late_fee_cents": 0,
        "status": "PENDING",
    })
    store.draws[rec["id"]] = rec
    return rec


def recompute_deposit_required(project):
    shop = store.shops[project["shop_id"]]
    project["deposit_required_cents"] = round_half_up_div(
        project["contract_total_cents"] * shop["deposit_pct_bps"], 10000)


def release_reservations(project, statuses):
    """Move project's reservations in given statuses to RELEASED, bumping each."""
    for r in store.reservations.values():
        if r["project_id"] == project["id"] and r["status"] in statuses:
            r["status"] = "RELEASED"
            touch(r)


def bubble_installation_complete(project):
    """Installation reached COMPLETE: project READY_FOR_DELIVERY -> INSTALLED,
    create one RETAINAGE Draw PENDING (PRD §3.9)."""
    project["status"] = "INSTALLED"
    touch(project)
    create_draw(project, "RETAINAGE")
