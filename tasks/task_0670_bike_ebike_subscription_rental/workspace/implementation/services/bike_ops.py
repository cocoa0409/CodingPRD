"""Bike state transitions invoked as side-effects of rental/delivery/ticket
transitions. Each mutated bike gets its own version bump + updated_at (PRD §2.5)."""
from services.common import touch
from services.reconcile import recompute_model_counts


def select_available_bike(model_id, bikes):
    """Pick the AVAILABLE bike of a model with the earliest created_at (PRD §3.3).
    Ties broken by insertion sequence. Returns the bike dict or None."""
    candidates = [
        b for b in bikes.values()
        if b["model_id"] == model_id and b["bike_status"] == "AVAILABLE"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda b: b["_seq"])
    return candidates[0]
