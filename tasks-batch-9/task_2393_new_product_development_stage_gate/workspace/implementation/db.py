"""In-memory stores.

Everything lives in plain Python dicts keyed by uuid string. Nothing is
persisted, nothing is seeded: a freshly started process holds no entities at
all, exactly as the contract requires.

Row conventions
---------------
* Keys that do NOT start with ``_`` are part of the serialised resource.
* Keys that start with ``_`` are internal bookkeeping:
    ``_seq``        monotonically increasing insertion ordinal (created_at proxy
                    used for deterministic tie-breaks; ``id`` is never an
                    ordering key anywhere in this API)
    ``_dt_<field>`` the parsed ``datetime`` behind a client-supplied ISO-8601
                    string, so the stored string can be echoed verbatim while
                    comparisons still work on real datetimes.
"""

import threading

# --- entity stores ----------------------------------------------------------
projects = {}
stage_gates = {}
retailers = {}
shelf_reset_windows = {}
pilot_lines = {}
concept_tests = {}
business_cases = {}
forecast_lines = {}
deliverables = {}
gate_reviews = {}
gate_votes = {}
formulations = {}
pilot_runs = {}
shelf_life_studies = {}
label_approvals = {}
sell_in_presentations = {}
post_launch_periods = {}

ALL_STORES = {
    "InnovationProject": projects,
    "StageGate": stage_gates,
    "Retailer": retailers,
    "ShelfResetWindow": shelf_reset_windows,
    "PilotLine": pilot_lines,
    "ConceptTest": concept_tests,
    "BusinessCase": business_cases,
    "ForecastLine": forecast_lines,
    "Deliverable": deliverables,
    "GateReview": gate_reviews,
    "GateVote": gate_votes,
    "Formulation": formulations,
    "PilotRun": pilot_runs,
    "ShelfLifeStudy": shelf_life_studies,
    "LabelApproval": label_approvals,
    "SellInPresentation": sell_in_presentations,
    "PostLaunchPeriod": post_launch_periods,
}

# --- insertion ordinal ------------------------------------------------------
_seq_lock = threading.Lock()
_seq = 0


def next_seq():
    global _seq
    with _seq_lock:
        _seq += 1
        return _seq


def rows(store):
    """All rows of a store as a list, in insertion order."""
    return sorted(store.values(), key=lambda r: r["_seq"])


def children(store, field, value):
    """All rows of a store whose ``field`` equals ``value``, insertion ordered."""
    return [r for r in rows(store) if r.get(field) == value]
