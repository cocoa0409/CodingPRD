"""In-memory data store for all entities."""

import threading

# Each map: id -> entity dict.
borrowers: dict = {}
loan_applications: dict = {}
income_verifications: dict = {}
asset_verifications: dict = {}
appraisals: dict = {}
title_searches: dict = {}
rate_locks: dict = {}
rate_lock_extensions: dict = {}
disclosures: dict = {}
udaap_reviews: dict = {}

# Singleton SystemClock (UTC instant ISO 8601 string).
system_clock: dict = {"now": "2026-01-01T00:00:00.000Z"}

# Per-rate-lock extension serialisation: a lock acquired around extend.
_rate_lock_extend_locks: dict = {}
_rate_lock_extend_lock_meta = threading.Lock()


def get_rate_lock_extend_lock(rate_lock_id: str) -> threading.Lock:
    """Return a per-rate-lock Lock used to serialise extension requests."""
    with _rate_lock_extend_lock_meta:
        lk = _rate_lock_extend_locks.get(rate_lock_id)
        if lk is None:
            lk = threading.Lock()
            _rate_lock_extend_locks[rate_lock_id] = lk
        return lk


# Per-(application_id, kind) disclosure-issue serialisation lock.
_disclosure_locks: dict = {}
_disclosure_lock_meta = threading.Lock()


def get_disclosure_lock(application_id: str, kind: str) -> threading.Lock:
    """Return a per-(application,kind) Lock used to serialise disclosure issuance."""
    key = (application_id, kind)
    with _disclosure_lock_meta:
        lk = _disclosure_locks.get(key)
        if lk is None:
            lk = threading.Lock()
            _disclosure_locks[key] = lk
        return lk


# Per-application submit-underwriting lock.
_submit_locks: dict = {}
_submit_lock_meta = threading.Lock()


def get_submit_lock(application_id: str) -> threading.Lock:
    with _submit_lock_meta:
        lk = _submit_locks.get(application_id)
        if lk is None:
            lk = threading.Lock()
            _submit_locks[application_id] = lk
        return lk


def reset_all():
    borrowers.clear()
    loan_applications.clear()
    income_verifications.clear()
    asset_verifications.clear()
    appraisals.clear()
    title_searches.clear()
    rate_locks.clear()
    rate_lock_extensions.clear()
    disclosures.clear()
    udaap_reviews.clear()
    system_clock["now"] = "2026-01-01T00:00:00.000Z"
