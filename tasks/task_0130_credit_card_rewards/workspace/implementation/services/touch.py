"""Helpers to refresh common system fields (updated_at, version).

Per PRD §2.4, four resources (Activation, Transfer, Credit, Ledger) are
append-only and do NOT carry updated_at/version. We only touch versioned
resources here.

Per PRD §2.4 last paragraph: when the system mutates a derived field on an
Account (points_balance, ytd_qualifying_spend_cents, spending_tier,
lifecycle_state, signup_bonus_state, signup_bonus_qualifying_spend_cents,
last_qualifying_activity_at), the mutation refreshes updated_at and version.

Per PRD §2.11: cascades increment version once per overall transition (not
once per cascade hop). The transition wrapper is responsible for that.
"""
from __future__ import annotations

from store import store


def touch_versioned(resource: dict) -> None:
    """Refresh `updated_at` to now and increment `version` by 1.

    Safe to call on any resource that exposes updated_at/version.
    """
    resource["updated_at"] = store.now_iso()
    resource["version"] = int(resource.get("version", 0)) + 1
