"""Lookup helpers + small entity factories + common mutators.

Centralized so route modules do not duplicate the same dict-bumping logic.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from ..clock import date_iso, iso_format, now, parse_date_str
from ..errors import err_not_found
from ..helpers import new_uuid
from ..store import store


# ---------------------------------------------------------------------------
# Common-field initialisation / bumping
# ---------------------------------------------------------------------------

def _ts() -> str:
    return iso_format(now())  # type: ignore[return-value]


def init_common(d: dict[str, Any]) -> dict[str, Any]:
    """Stamp id, created_at, updated_at, version on a brand-new entity."""
    d.setdefault("id", new_uuid())
    ts = _ts()
    d["created_at"] = ts
    d["updated_at"] = ts
    d["version"] = 1
    return d


def init_event(d: dict[str, Any]) -> dict[str, Any]:
    """Stamp id + created_at on event-style entities (no version/updated_at)."""
    d.setdefault("id", new_uuid())
    d["created_at"] = _ts()
    return d


def bump_version(d: dict[str, Any]) -> dict[str, Any]:
    """Refresh updated_at and increment version (PRD §2.4)."""
    d["updated_at"] = _ts()
    d["version"] = d.get("version", 0) + 1
    return d


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_participant_or_404(pid: str) -> dict[str, Any]:
    p = store().participants.get(pid)
    if not p:
        raise err_not_found(f"Participant {pid} not found")
    return p


def get_account_or_404(aid: str) -> dict[str, Any]:
    a = store().accounts.get(aid)
    if not a:
        raise err_not_found(f"Account {aid} not found")
    return a


def get_account_scoped_or_404(pid: str, aid: str) -> dict[str, Any]:
    """Resolve /participants/{pid}/accounts/{aid} per validation §5."""
    get_participant_or_404(pid)
    a = store().accounts.get(aid)
    if not a or a["participant_id"] != pid:
        raise err_not_found(f"Account {aid} not found for participant {pid}")
    return a


def get_contribution_or_404(cid: str) -> dict[str, Any]:
    c = store().contributions.get(cid)
    if not c:
        raise err_not_found(f"Contribution {cid} not found")
    return c


def get_conversion_or_404(cid: str) -> dict[str, Any]:
    c = store().conversions.get(cid)
    if not c:
        raise err_not_found(f"ConversionRequest {cid} not found")
    return c


def get_claim_or_404(cid: str) -> dict[str, Any]:
    c = store().claims.get(cid)
    if not c:
        raise err_not_found(f"BeneficiaryClaim {cid} not found")
    return c


def get_form_or_404(fid: str) -> dict[str, Any]:
    f = store().forms_1099r.get(fid)
    if not f:
        raise err_not_found(f"Form1099R {fid} not found")
    return f


def get_distribution_or_404(did: str) -> dict[str, Any]:
    d = store().distributions.get(did)
    if not d:
        raise err_not_found(f"DistributionEvent {did} not found")
    return d


# ---------------------------------------------------------------------------
# Computed / derived helpers
# ---------------------------------------------------------------------------

def parse_iso_date_str(s: str | None) -> date | None:
    if s is None:
        return None
    return parse_date_str(s)


def claim_for_account(account_id: str) -> dict[str, Any] | None:
    cid = store().claim_by_account.get(account_id)
    if cid is None:
        return None
    return store().claims.get(cid)


def ts() -> str:
    """Public timestamp accessor (for routes that need to stamp e.g. settled_at)."""
    return _ts()


def date_str_today() -> str:
    from ..clock import current_date
    return date_iso(current_date())  # type: ignore[return-value]
