"""Test-driving system endpoints: /_clock/advance and /_sweep/run-recurring."""

from datetime import datetime, timezone, timedelta
from flask import Blueprint, request
from core.auth import require_roles
from core.envelope import success_object, success_array
from core.errors import raise_error
from core.store import STORE, lock, iso_now_from_dt
from core.clock import CLOCK
from core.validation import require_body, require_field
from core.models import contribution_create, contribution_view, touch


bp = Blueprint("system", __name__)


@bp.post("/__test__/reset")
def test_reset():
    """Test-harness only: wipe in-memory store and reset the logical
    clock to a stable initial instant. Auth is bypassed for this
    endpoint because it is invoked by conftest before any auth setup.

    The clock is reset to a fixed early-real instant so that tests can
    deterministically advance forward through subsequent calendar years
    (PRD §3.8 forbids backward-advance via /_clock/advance, so reset
    must place the clock early enough for every test scenario that
    advances into a specific tax_year). The reset itself is privileged
    — it bypasses the forward-only constraint of /_clock/advance.
    """
    with lock():
        STORE.donors.clear()
        STORE.beneficiaries.clear()
        STORE.accounts.clear()
        STORE.contributions.clear()
        STORE.withdrawals.clear()
        STORE.recurring_plans.clear()
        STORE.beneficiary_change_requests.clear()
        STORE.education_expenses.clear()
        STORE.tax_reports.clear()
        STORE.state_rules.clear()
        STORE.state_rules_by_id.clear()
        STORE._created_seq = 0
        # Stable initial instant — early enough that tests advancing to
        # 2025/2026/2027/2028 always move forward.
        CLOCK._now = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    return success_object({})


def _parse_iso8601(s: str) -> datetime:
    """Parse a strict-ish ISO 8601 UTC instant. Accept trailing 'Z' or +00:00."""
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
    except Exception:
        raise_error("ERR_VALIDATION_FAILED", "to_iso8601 is not a valid ISO 8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@bp.post("/_clock/advance")
@require_roles("PlanAdministrator")
def advance_clock():
    body = require_body(request)
    to_iso = require_field(body, "to_iso8601", kind="string")
    target = _parse_iso8601(to_iso)
    with lock():
        ok = CLOCK.advance_to(target)
        if not ok:
            raise_error("ERR_CLOCK_NOT_MOVING_FORWARD",
                        "to_iso8601 must be strictly greater than current server now()")
    return success_object({})


@bp.post("/_sweep/run-recurring")
@require_roles("PlanAdministrator")
def sweep_recurring():
    now = CLOCK.now()
    created = []
    with lock():
        for plan in list(STORE.recurring_plans.values()):
            if plan["status"] != "ACTIVE":
                continue
            # Parse plan.next_run_at and compare against now.
            try:
                nra_str = plan["next_run_at"]
                if nra_str.endswith("Z"):
                    nra_str = nra_str[:-1] + "+00:00"
                nra = datetime.fromisoformat(nra_str)
                if nra.tzinfo is None:
                    nra = nra.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if nra > now:
                continue
            c = contribution_create(
                plan["account_id"], plan["donor_id"], plan["amount_cents"],
                "RECURRING", plan["id"],
            )
            created.append(contribution_view(c))
            # Advance next_run_at.
            new_dt = nra + timedelta(seconds=plan["cadence_days"] * 86400)
            plan["next_run_at"] = iso_now_from_dt(new_dt)
            touch(plan)
    # Returns array of newly-created contributions.
    return success_array(created, limit=len(created) if created else 10,
                         offset=0, total_count=len(created))
