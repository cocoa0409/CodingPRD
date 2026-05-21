"""VerificationItem service — vendor return path."""
from __future__ import annotations

from core.errors import err_invalid_state, err_validation_failed
from core.store import store
from services.audit_service import append_event
from services.calculations import compute_severity_score
from services.timestamps import stamp_update
from services.order_service import maybe_advance_to_adjudication


def _validate_raw_finding(kind: str, payload) -> dict:
    if not isinstance(payload, dict):
        raise err_validation_failed("raw_finding must be a JSON object.")
    if kind == "CRIMINAL":
        if "conviction_date" not in payload or "severity" not in payload:
            raise err_validation_failed(
                "CRIMINAL raw_finding requires conviction_date and severity."
            )
        if payload.get("severity") not in {"INFRACTION", "MISDEMEANOR", "FELONY"}:
            raise err_validation_failed(
                "CRIMINAL severity must be INFRACTION|MISDEMEANOR|FELONY."
            )
    elif kind == "MVR":
        if "violations_3yr" not in payload or "license_status" not in payload:
            raise err_validation_failed(
                "MVR raw_finding requires violations_3yr and license_status."
            )
        v = payload.get("violations_3yr")
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise err_validation_failed("violations_3yr must be a non-negative integer.")
    elif kind == "EDUCATION":
        if "institution" not in payload or "claim_verified" not in payload:
            raise err_validation_failed(
                "EDUCATION raw_finding requires institution and claim_verified."
            )
        if not isinstance(payload.get("claim_verified"), bool):
            raise err_validation_failed("claim_verified must be a boolean.")
    else:
        raise err_validation_failed(f"Unknown VerificationItem kind: {kind}")
    return payload


def return_item(item: dict, body: dict, *, actor_role: str, actor_user_id: str) -> dict:
    if item["status"] != "IN_PROGRESS":
        raise err_invalid_state(
            f"Item is in {item['status']}, expected IN_PROGRESS."
        )
    payload = body.get("raw_finding")
    raw = _validate_raw_finding(item["kind"], payload)
    item["raw_finding"] = raw

    candidate = store.candidates.get(
        store.orders.get(item["order_id"], {}).get("candidate_id")
    )
    item["severity_score"] = compute_severity_score(item, candidate or {})
    item["status"] = "RETURNED"
    stamp_update(item)

    append_event(
        event_type="ITEM_RETURNED",
        subject_entity="VerificationItem",
        subject_id=item["id"],
        actor_role=actor_role,
        actor_user_id=actor_user_id,
    )

    # Cascade: maybe push the order forward.
    order = store.orders.get(item["order_id"])
    if order is not None:
        maybe_advance_to_adjudication(order)
    return item
