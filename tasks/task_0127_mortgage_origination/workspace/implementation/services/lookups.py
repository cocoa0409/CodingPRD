"""Cross-resource lookups: find latest disclosures, active rate locks, completed appraisals, etc."""

from __future__ import annotations

import db
from config import (
    APR_COMPLETED,
    DISC_NON_TERMINAL,
    DISC_VOIDED,
    DISCLOSURE_KIND_CD,
    DISCLOSURE_KIND_LE,
    LOCK_ACTIVE,
    VER_VERIFIED,
)
from services import clock
from utils import parse_iso


def latest_disclosure(application_id: str, kind: str, *, include_voided: bool = False):
    """Return the highest-version Disclosure of the given kind for the application, or None."""
    candidates = [
        d
        for d in db.disclosures.values()
        if d["application_id"] == application_id and d["kind"] == kind
    ]
    if not include_voided:
        candidates = [d for d in candidates if d["status"] != DISC_VOIDED]
    if not candidates:
        return None
    return max(candidates, key=lambda d: d["version"])


def latest_non_voided_disclosure(application_id: str, kind: str):
    return latest_disclosure(application_id, kind, include_voided=False)


def list_disclosures(application_id: str, kind: str | None = None):
    items = [d for d in db.disclosures.values() if d["application_id"] == application_id]
    if kind is not None:
        items = [d for d in items if d["kind"] == kind]
    return items


def next_disclosure_version(application_id: str, kind: str) -> int:
    same = [
        d
        for d in db.disclosures.values()
        if d["application_id"] == application_id and d["kind"] == kind
    ]
    return (max((d["version"] for d in same), default=0)) + 1


def find_active_rate_lock(application_id: str):
    """Return the single active rate lock (status in {LOCKED, EXTENDED}) for the application, or None."""
    for rl in db.rate_locks.values():
        if rl["application_id"] == application_id and rl["status"] in LOCK_ACTIVE:
            return rl
    return None


def latest_rate_lock(application_id: str):
    """Return the most recently created rate lock for the application, or None."""
    candidates = [rl for rl in db.rate_locks.values() if rl["application_id"] == application_id]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r["created_at"])


def completed_appraisal(application_id: str):
    """Return the latest COMPLETED appraisal for the application, or None."""
    candidates = [
        a
        for a in db.appraisals.values()
        if a["application_id"] == application_id and a["status"] == APR_COMPLETED
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda a: a["created_at"])


def any_completed_appraisal_unexpired(application_id: str) -> bool:
    """Per ERR_APPRAISAL_OVERLAP: any COMPLETED appraisal whose valid_until > SystemClock.now."""
    now = clock.get_now_dt()
    for a in db.appraisals.values():
        if a["application_id"] != application_id:
            continue
        if a["status"] != APR_COMPLETED:
            continue
        vu = parse_iso(a.get("valid_until"))
        if vu is not None and vu > now:
            return True
    return False


def title_search_for(application_id: str):
    """Return the most recent title search for the application, or None."""
    candidates = [
        t for t in db.title_searches.values() if t["application_id"] == application_id
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda t: t["created_at"])


def list_income_verifications(application_id: str):
    return [
        iv
        for iv in db.income_verifications.values()
        if iv["application_id"] == application_id
    ]


def list_asset_verifications(application_id: str):
    return [
        av
        for av in db.asset_verifications.values()
        if av["application_id"] == application_id
    ]


def any_verified_income(application_id: str) -> bool:
    return any(
        iv["status"] == VER_VERIFIED for iv in list_income_verifications(application_id)
    )


def any_verified_asset(application_id: str) -> bool:
    return any(
        av["status"] == VER_VERIFIED for av in list_asset_verifications(application_id)
    )


def list_udaap_reviews(application_id: str):
    return [r for r in db.udaap_reviews.values() if r["application_id"] == application_id]


def latest_udaap_review_pass_against_le_version(application_id: str, le_version: int) -> bool:
    """PRD §3.8: APPROVE requires a UDAAPReview with outcome=PASS that
    applies to the *latest* LOAN_ESTIMATE version. Each UDAAP review
    records, at submission time, the latest LE/CD versions on file
    (snapshot fields); the gate matches by exact version, which is
    deterministic regardless of SystemClock vs wall-clock skew.
    """
    for r in list_udaap_reviews(application_id):
        if r["outcome"] != "PASS":
            continue
        if r.get("_snapshot_le_version") == le_version:
            return True
    return False


def latest_udaap_review_pass_against_cd_version(application_id: str, cd_version: int) -> bool:
    """PRD §3.10: clear-to-close requires a UDAAPReview with outcome=
    PASS that applies to the *latest* CLOSING_DISCLOSURE version. Each
    UDAAP review records the latest CD version on file at submission.
    """
    for r in list_udaap_reviews(application_id):
        if r["outcome"] != "PASS":
            continue
        if r.get("_snapshot_cd_version") == cd_version:
            return True
    return False
