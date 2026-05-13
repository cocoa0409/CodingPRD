"""Server timestamp helpers (PRD §2.4 created_at / updated_at)."""
from __future__ import annotations

from datetime import datetime, timezone


def now_iso() -> str:
    """ISO 8601 UTC timestamp with three fractional digits."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
