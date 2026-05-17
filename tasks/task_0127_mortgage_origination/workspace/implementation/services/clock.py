"""SystemClock service: read/advance and conversions (PRD §2.9)."""

from datetime import datetime

import db
from utils import parse_iso, to_iso_millis


def get_now_iso() -> str:
    return db.system_clock["now"]


def get_now_dt() -> datetime:
    return parse_iso(db.system_clock["now"])


def advance_to(iso_text: str) -> str:
    """Set the clock to the supplied ISO 8601 instant; return the canonical ISO."""
    dt = parse_iso(iso_text)
    db.system_clock["now"] = to_iso_millis(dt)
    return db.system_clock["now"]
