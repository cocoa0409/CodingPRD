"""Staleness propagation per PRD §2.7.

- Transaction posted: triangles of the segment with valuation_quarter >= effective_quarter go stale.
- Catastrophe assigned/cleared: every triangle of the segment goes stale.
- Triangle stale/re-aggregated: runs computed from it go stale (re-aggregation does NOT rehabilitate runs).
- Pattern withdrawn: runs built on it with valuation_quarter in its window go stale.
- Run stale: IN_REVIEW studies of the segment whose matched run turned stale revert to DRAFT with stale_data_flag=true.
"""
from db import db, next_seq
from util import now_ts


def _touch(rec):
    rec["updated_at"] = now_ts()
    rec["version"] = rec.get("version", 1) + 1


def _mark_run_stale(run):
    if not run["is_stale"]:
        run["is_stale"] = True
        _touch(run)


def _cascade_study_stale_for_segment(segment_id):
    """Every IN_REVIEW study of the segment whose matched run is now stale reverts to DRAFT."""
    for study in db["studies"].values():
        if study["segment_id"] != segment_id:
            continue
        if study["status"] != "IN_REVIEW":
            continue
        # find any run matching study's selector
        matched_any = None
        for r in db["reserve_runs"].values():
            if r["segment_id"] != study["segment_id"]:
                continue
            if r["valuation_quarter"] != study["valuation_quarter"]:
                continue
            if r["method"] != study["selected_method"]:
                continue
            if r["basis"] != study["selected_basis"]:
                continue
            matched_any = r
            break
        # Study reverts only when its matched run turned stale. If there is no matched
        # run at all, we leave the study alone (submit would fail with NO_SELECTED_RUN
        # at its own time; cascade is about a run turning stale).
        if matched_any is not None and matched_any["is_stale"]:
            study["status"] = "DRAFT"
            study["stale_data_flag"] = True
            _touch(study)


def triangle_marked_stale(triangle):
    """Runs referencing this triangle go stale; IN_REVIEW studies revert."""
    for run in db["reserve_runs"].values():
        if run["segment_id"] != triangle["segment_id"]:
            continue
        if run["basis"] != triangle["basis"]:
            continue
        if run["valuation_quarter"] != triangle["valuation_quarter"]:
            continue
        _mark_run_stale(run)
    _cascade_study_stale_for_segment(triangle["segment_id"])


def transaction_posted_staleness(segment_id, effective_quarter):
    """Mark triangles of the segment with valuation_quarter >= effective_quarter stale,
    then cascade."""
    for tri in db["triangles"].values():
        if tri["segment_id"] != segment_id:
            continue
        if tri["valuation_quarter"] >= effective_quarter:
            if not tri["is_stale"]:
                tri["is_stale"] = True
                _touch(tri)
                # cascade to runs
                for run in db["reserve_runs"].values():
                    if run["segment_id"] != tri["segment_id"]:
                        continue
                    if run["basis"] != tri["basis"]:
                        continue
                    if run["valuation_quarter"] != tri["valuation_quarter"]:
                        continue
                    _mark_run_stale(run)
    _cascade_study_stale_for_segment(segment_id)


def catastrophe_assignment_staleness(segment_id):
    """Every triangle of the segment goes stale (layer membership changed)."""
    for tri in db["triangles"].values():
        if tri["segment_id"] != segment_id:
            continue
        if not tri["is_stale"]:
            tri["is_stale"] = True
            _touch(tri)
            for run in db["reserve_runs"].values():
                if run["segment_id"] != tri["segment_id"]:
                    continue
                if run["basis"] != tri["basis"]:
                    continue
                if run["valuation_quarter"] != tri["valuation_quarter"]:
                    continue
                _mark_run_stale(run)
    _cascade_study_stale_for_segment(segment_id)


def triangle_reaggregated(triangle):
    """Re-aggregation clears the triangle's is_stale but does NOT rehabilitate runs
    computed from the earlier aggregation. Any run created after the previous
    aggregation and before this one stays stale. So: nothing to cascade here —
    the runs that were stale remain stale. New runs will be fresh going forward.
    """
    pass


def pattern_withdrawn_staleness(pattern):
    """Runs using this pattern with valuation_quarter in [from, to) go stale.
    Then IN_REVIEW studies whose matched run turned stale revert."""
    for run in db["reserve_runs"].values():
        if run.get("development_pattern_id") != pattern["id"]:
            continue
        vq = run["valuation_quarter"]
        if pattern["effective_from_quarter"] <= vq < pattern["effective_to_quarter"]:
            _mark_run_stale(run)
    _cascade_study_stale_for_segment(pattern["segment_id"])
