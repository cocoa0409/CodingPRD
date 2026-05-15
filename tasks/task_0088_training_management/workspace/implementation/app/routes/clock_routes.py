"""Clock and sweep endpoints (test drivers)."""
from __future__ import annotations

from datetime import timedelta

from flask import Flask

from ..audit import write_audit
from ..auth import require_auth
from ..clock import CLOCK, format_iso, now_dt, parse_iso, add_days
from ..errors import ApiError
from ..store import bump_version, common_fields_append_only, get_store
from ..services.calculations import evaluate_shortfall_warning
from ._helpers import get_json_body, ok, with_lock


def register(app: Flask) -> None:
    @app.post("/training/_clock/advance")
    @require_auth("TrainingAdmin")
    @with_lock
    def advance_clock():
        body = get_json_body()
        now_val = body.get("now")
        if not now_val:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "now is required.", http_status=422)
        try:
            dt = parse_iso(now_val)
        except ValueError as exc:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", f"Invalid now: {exc}", http_status=422)
        CLOCK.set(dt)
        return ok({"now": format_iso(dt)})

    @app.post("/training/_sweep/run")
    @require_auth("TrainingAdmin")
    @with_lock
    def run_sweep():
        store = get_store()
        cur = now_dt()
        results = {
            "enrollment_closed": 0,
            "in_progress": 0,
            "certificates_expiring_soon": 0,
            "certificates_expired": 0,
            "shortfall_warnings_emitted": 0,
        }

        # Sessions: ENROLLMENT_OPEN -> ENROLLMENT_CLOSED (deadline reached)
        for s in store.sessions.values():
            if s["status"] == "ENROLLMENT_OPEN" and cur >= parse_iso(s["enrollment_deadline"]):
                s["status"] = "ENROLLMENT_CLOSED"
                bump_version(s)
                results["enrollment_closed"] += 1
        # Sessions: ENROLLMENT_CLOSED -> IN_PROGRESS (start_at reached)
        for s in store.sessions.values():
            if s["status"] == "ENROLLMENT_CLOSED" and cur >= parse_iso(s["start_at"]):
                s["status"] = "IN_PROGRESS"
                bump_version(s)
                results["in_progress"] += 1

        # Certificates: VALID -> EXPIRING_SOON when within renewal window
        for c in store.certificates.values():
            if c["status"] != "VALID":
                continue
            tpl = store.certificate_templates.get(c["certificate_template_id"])
            if not tpl:
                continue
            expires = parse_iso(c["expires_at"])
            if cur >= expires:
                # already expired
                c["status"] = "EXPIRED"
                bump_version(c)
                results["certificates_expired"] += 1
                continue
            renew_open = add_days(expires, -int(tpl["renewal_window_days"]))
            if cur >= renew_open:
                c["status"] = "EXPIRING_SOON"
                bump_version(c)
                results["certificates_expiring_soon"] += 1
                # emit reminder SyncEvent
                base = common_fields_append_only()
                store.sync_events[base["id"]] = {
                    **base,
                    "source_system": "IM",
                    "event_type": "cert.expiring_soon",
                    "payload": {"certificate_id": c["id"]},
                    "processed_at": base["created_at"],
                    "outcome": "APPLIED",
                }
        # Certificates: EXPIRING_SOON -> EXPIRED if past expires_at
        for c in store.certificates.values():
            if c["status"] == "EXPIRING_SOON":
                if cur >= parse_iso(c["expires_at"]):
                    c["status"] = "EXPIRED"
                    bump_version(c)
                    results["certificates_expired"] += 1

        # Credit pools warning
        for pool in store.credit_pools.values():
            if evaluate_shortfall_warning(pool, cur):
                bump_version(pool)
                results["shortfall_warnings_emitted"] += 1
                base = common_fields_append_only()
                store.sync_events[base["id"]] = {
                    **base,
                    "source_system": "IM",
                    "event_type": "credit.shortfall_warning",
                    "payload": {"credit_pool_id": pool["id"]},
                    "processed_at": base["created_at"],
                    "outcome": "APPLIED",
                }
                write_audit(
                    "CREDIT_POOL",
                    pool["id"],
                    "credit.shortfall_warning",
                    before={"shortfall_warning_emitted": False},
                    after={"shortfall_warning_emitted": True},
                )

        return ok(results)
