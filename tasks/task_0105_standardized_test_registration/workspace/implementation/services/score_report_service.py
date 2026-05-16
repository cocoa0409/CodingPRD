"""ScoreReport posting and Super Score computation."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

import db
from clock import now
from config import (
    REPORT_TYPES,
    REPORTING_MODES,
    SCORE_RANGES,
    SECTION_KEYS,
    SUPER_SCORE_LOOKBACK_DAYS,
)
from errors import (
    err_insufficient_permissions,
    err_invalid_registration_state,
    err_invalid_request,
    err_score_report_not_found,
)
from response import parse_iso_utc
from services.registration_service import get_scoped_registration_or_404
from services.test_event_service import get_test_event_or_404


def get_score_report_or_404(score_report_id: str) -> dict:
    s = db.score_reports.get(score_report_id)
    if s is None:
        raise err_score_report_not_found()
    return s


def post_score_report(test_event_id: str, registration_id: str, body: dict) -> dict:
    e = get_test_event_or_404(test_event_id)
    r = get_scoped_registration_or_404(test_event_id, registration_id)
    if r["status"] != "COMPLETED":
        raise err_invalid_registration_state("Registration must be COMPLETED to post a ScoreReport")

    section_scores = body.get("section_scores")
    total_score = body.get("total_score")
    report_type = body.get("report_type", "OFFICIAL")

    if report_type not in REPORT_TYPES:
        raise err_invalid_request("report_type must be OFFICIAL or RESCORED")
    if not isinstance(section_scores, dict) or not section_scores:
        raise err_invalid_request("section_scores must be a non-empty object")
    expected_sections = SECTION_KEYS[e["test_type"]]
    if set(section_scores.keys()) != expected_sections:
        raise err_invalid_request(
            f"section_scores keys must match {sorted(expected_sections)} for test_type {e['test_type']}"
        )
    for k, v in section_scores.items():
        if not isinstance(v, int):
            raise err_invalid_request(f"section_scores[{k}] must be an integer")
    if not isinstance(total_score, int):
        raise err_invalid_request("total_score must be an integer")
    low, high = SCORE_RANGES[e["test_type"]]
    if total_score < low or total_score > high:
        raise err_invalid_request(f"total_score must be in [{low}, {high}] for {e['test_type']}")

    s = db.append_create()
    s.update(
        {
            "registration_id": registration_id,
            "section_scores": dict(section_scores),
            "total_score": total_score,
            "report_type": report_type,
        }
    )
    db.score_reports.insert(s)
    return s


def list_score_reports(test_event_id: str, registration_id: str, caller_role: str, caller_user_id: str):
    r = get_scoped_registration_or_404(test_event_id, registration_id)
    if caller_role == "Candidate" and caller_user_id != r["candidate_id"]:
        raise err_insufficient_permissions()
    items = [s for s in db.score_reports.all() if s["registration_id"] == registration_id]
    items.sort(key=lambda s: s["created_at"])
    return items


def compute_super_score(candidate_id: str, test_type: str, reporting_mode: str, as_of_date: Optional[str]) -> dict:
    """Build the pool: every Registration owned by the candidate where
    TestEvent.test_type matches; for each registration, keep the latest
    ScoreReport (RESCORED > OFFICIAL by created_at); filter by 24-month lookback.
    """
    if test_type not in SCORE_RANGES:
        raise err_invalid_request("test_type must be one of SAT, ACT, AP, CLEP")
    if reporting_mode not in REPORTING_MODES:
        raise err_invalid_request("reporting_mode must be COLLEGE_BOARD_OFFICIAL or INSTITUTIONAL_SUBMISSION")

    if as_of_date:
        try:
            as_of_dt = parse_iso_utc(as_of_date)
        except Exception:
            raise err_invalid_request("as_of_date must be ISO 8601 UTC")
    else:
        as_of_dt = now()

    lookback_threshold = as_of_dt - timedelta(days=SUPER_SCORE_LOOKBACK_DAYS)

    # Gather candidate registrations.
    pool = []
    for r in db.registrations.all():
        if r["candidate_id"] != candidate_id:
            continue
        e = db.test_events.get(r["test_event_id"])
        if not e or e["test_type"] != test_type:
            continue
        event_test_date = parse_iso_utc(e["test_date"])
        if event_test_date < lookback_threshold:
            continue
        # Pick the contributing ScoreReport: the one with the most recent created_at
        # whose report_type is OFFICIAL or RESCORED. If both kinds exist, the latest
        # by created_at wins (RESCORED supersedes OFFICIAL only if it is newer).
        reports = [s for s in db.score_reports.all() if s["registration_id"] == r["id"]]
        if not reports:
            continue
        latest = max(reports, key=lambda s: s["created_at"])
        pool.append((r, latest, e))

    if not pool:
        return {
            "test_type": test_type,
            "reporting_mode": reporting_mode,
            "composite": None,
            "sections": {},
            "sittings_used": 0,
            "source_score_report_ids": [],
        }

    section_keys = SECTION_KEYS[test_type]

    if test_type in ("AP", "CLEP"):
        # No super score; return the latest sitting's composite verbatim.
        latest_pair = max(pool, key=lambda triple: parse_iso_utc(triple[2]["test_date"]))
        _r, latest_sr, _e = latest_pair
        return {
            "test_type": test_type,
            "reporting_mode": reporting_mode,
            "composite": latest_sr["total_score"],
            "sections": dict(latest_sr["section_scores"]),
            "sittings_used": 1,
            "source_score_report_ids": [latest_sr["id"]],
        }

    if reporting_mode == "COLLEGE_BOARD_OFFICIAL":
        # Per section, take MAX across all sittings.
        sections = {}
        source_ids = set()
        for sk in section_keys:
            best_val = None
            best_id = None
            for _r, sr, _e in pool:
                v = sr["section_scores"].get(sk)
                if v is None:
                    continue
                if best_val is None or v > best_val:
                    best_val = v
                    best_id = sr["id"]
            sections[sk] = best_val
            if best_id:
                source_ids.add(best_id)
        if test_type == "SAT":
            rw = sections.get("reading_writing") or 0
            mt = sections.get("math") or 0
            composite = rw + mt
        else:  # ACT
            values = [sections[k] for k in section_keys if sections.get(k) is not None]
            if not values:
                composite = None
            else:
                mean = Decimal(sum(values)) / Decimal(len(values))
                composite = int(mean.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return {
            "test_type": test_type,
            "reporting_mode": reporting_mode,
            "composite": composite,
            "sections": sections,
            "sittings_used": len(pool),
            "source_score_report_ids": sorted(source_ids),
        }

    # INSTITUTIONAL_SUBMISSION: pick the sitting with the highest total_score.
    best_triple = max(pool, key=lambda triple: (triple[1]["total_score"], triple[1]["created_at"]))
    _r, best_sr, _e = best_triple
    sections = {sk: best_sr["section_scores"].get(sk) for sk in section_keys}
    if test_type == "SAT":
        composite = (sections.get("reading_writing") or 0) + (sections.get("math") or 0)
    else:
        values = [sections[k] for k in section_keys if sections.get(k) is not None]
        if not values:
            composite = None
        else:
            mean = Decimal(sum(values)) / Decimal(len(values))
            composite = int(mean.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    # PRD §3.9: INSTITUTIONAL_SUBMISSION uses a *single* sitting verbatim,
    # so sittings_used is 1 whenever the pool is non-empty.
    return {
        "test_type": test_type,
        "reporting_mode": reporting_mode,
        "composite": composite,
        "sections": sections,
        "sittings_used": 1,
        "source_score_report_ids": [best_sr["id"]],
    }
