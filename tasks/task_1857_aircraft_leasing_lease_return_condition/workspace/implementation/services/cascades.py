"""Cross-entity cascade helpers shared by several routes."""
from db import CLOCK, STORE, touch


def items_of_case(case_id):
    return [
        i for i in STORE["checklist_items"].values() if i["return_case_id"] == case_id
    ]


def reports_of_lease(lease_id):
    return [
        r for r in STORE["utilization_reports"].values() if r["lease_id"] == lease_id
    ]


def claims_of_lease(lease_id):
    return [c for c in STORE["reserve_claims"].values() if c["lease_id"] == lease_id]


def cases_of_lease(lease_id):
    return [c for c in STORE["return_cases"].values() if c["lease_id"] == lease_id]


def open_return_case(lease_id):
    """The (at most one) non-terminal ReturnCase of a lease, if any."""
    for c in STORE["return_cases"].values():
        if c["lease_id"] == lease_id and c["status"] not in ("SETTLED", "CANCELLED"):
            return c
    return None


def open_default_case(lease_id):
    for d in STORE["default_cases"].values():
        if d["lease_id"] == lease_id and d["status"] in (
            "DECLARED",
            "REPOSSESSION_AUTHORIZED",
        ):
            return d
    return None


def auto_confirm_covering_slot(aircraft_id, date_str):
    """Settle cascade link 3: among the aircraft's TENTATIVE slots whose
    closed window covers the settle date, confirm the one with the earliest
    window_start (tie-break created_at ASC). None qualify -> no-op."""
    candidates = [
        s
        for s in STORE["transition_slots"].values()
        if s["aircraft_id"] == aircraft_id
        and s["status"] == "TENTATIVE"
        and s["window_start"] <= date_str <= s["window_end"]
    ]
    if not candidates:
        return
    candidates.sort(key=lambda s: (s["window_start"], s["created_at"]))
    slot = candidates[0]
    slot["status"] = "CONFIRMED"
    touch(slot)


def release_aircraft_slots(aircraft_id):
    """Repossession cascade: TENTATIVE/CONFIRMED slots -> RELEASED;
    COMPLETED/RELEASED untouched."""
    for s in STORE["transition_slots"].values():
        if s["aircraft_id"] == aircraft_id and s["status"] in ("TENTATIVE", "CONFIRMED"):
            s["status"] = "RELEASED"
            touch(s)


def current_date_str():
    return CLOCK.date_str()
