"""Translator workload + eligibility selection."""
from __future__ import annotations

from db import store

NON_TERMINAL_SEGMENT_STATES = {"NEW", "ASSIGNED", "TRANSLATED", "REVIEWED"}
MAX_WORKLOAD_SEGMENTS = 200


def recompute_workload(translator_id: str) -> None:
    tr = store.translators.get(translator_id)
    if tr is None:
        return
    count = 0
    # Workload = count of segments currently held by this translator in non-terminal states.
    # "Held by" — segment whose assignment_id points to an Assignment that belongs to this
    # translator and whose role is TRANSLATOR, and segment is in a non-terminal state.
    for seg in store.segments.values():
        a_id = seg.get("assignment_id")
        if not a_id:
            continue
        a = store.assignments.get(a_id)
        if a is None:
            continue
        if a["translator_id"] != translator_id:
            continue
        if a["role"] != "TRANSLATOR":
            continue
        if seg["state"] in NON_TERMINAL_SEGMENT_STATES:
            count += 1
    tr["workload_segments_open"] = count


def is_eligible(translator: dict, project: dict, package_size: int) -> bool:
    if not translator.get("test_translation_passed"):
        return False
    if translator.get("availability_status") != "AVAILABLE":
        return False
    pair = {"source_lang": project["source_lang"], "target_lang": project["target_lang"]}
    pairs = translator.get("language_pairs", [])
    if not any(p.get("source_lang") == pair["source_lang"] and p.get("target_lang") == pair["target_lang"] for p in pairs):
        return False
    if project["domain"] not in translator.get("domains", []):
        return False
    if translator.get("workload_segments_open", 0) + package_size > MAX_WORKLOAD_SEGMENTS:
        return False
    return True


def select_successor_translator(project: dict, package_size: int, excluded_ids: set[str]) -> dict | None:
    """Rank eligible translators: rolling_quality_score desc, workload asc, id asc."""
    candidates = []
    for t in store.translators.values():
        if t["id"] in excluded_ids:
            continue
        if not is_eligible(t, project, package_size):
            continue
        candidates.append(t)
    if not candidates:
        return None
    candidates.sort(key=lambda t: (
        -float(t.get("rolling_quality_score", 0)),
        int(t.get("workload_segments_open", 0)),
        t["id"],
    ))
    return candidates[0]
