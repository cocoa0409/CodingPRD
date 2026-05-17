"""LabResult endpoints: fetch, release, amend, retract."""
from __future__ import annotations

from flask import Blueprint

from ..auth import ROLE_LAB_DIRECTOR, ROLE_LAB_TECH, ROLE_ORDERING_PROVIDER, require_roles
from ..clock import now
from ..errors import (
    err_clia_sod_violation,
    err_clinician_inactive,
    err_invalid_state,
    err_patient_consent_blocked,
    err_validation,
)
from ..helpers import (
    assert_string,
    occ_check,
    require_json_object,
)
from ..responses import ok
from ..services import calculations as calc
from ..services.audit import write_audit_event
from ..services.lookups import (
    get_clinician,
    get_lab_order,
    get_lab_result,
    get_patient,
    get_test_panel,
)
from ..services.serialize import lab_result_view
from ..services.workflows import (
    bump,
    create_critical_notification,
    history_critical_count,
    issue_retest,
)
from ..store import store

bp = Blueprint("results", __name__)


@bp.route("/results/<rid>", methods=["GET"])
@require_roles(ROLE_ORDERING_PROVIDER, ROLE_LAB_TECH, ROLE_LAB_DIRECTOR)
def fetch_result(rid, **_):
    return ok(lab_result_view(get_lab_result(rid)))


# ===========================================================================
# Release a DRAFT result
# ===========================================================================

@bp.route("/results/<rid>/release", methods=["POST"])
@require_roles(ROLE_LAB_DIRECTOR)
def release_result(rid, **_):
    body = require_json_object()
    rel_id = assert_string(body.get("released_by_id"), "released_by_id")

    with store().lock:
        result = get_lab_result(rid)
        rel = get_clinician(rel_id)
        order = get_lab_order(result["lab_order_id"])

        # State (priority 5)
        if result["status"] != "DRAFT":
            raise err_invalid_state(f"LabResult must be DRAFT to release (was {result['status']})")
        if order["status"] != "RESULTED":
            raise err_invalid_state(f"LabOrder must be RESULTED to release (was {order['status']})")

        # SoD (priority 6)
        if rel_id == result["resulted_by_id"]:
            raise err_clia_sod_violation()

        # CLIA: released_by must be LAB_DIRECTOR (per scaffold §1.2 and PRD §2.6)
        # This is part of CLIA SoD/complexity family — use CLIA_SOD_VIOLATION for non-director?
        # Per PRD §2.6, released_by must be LAB_DIRECTOR; we treat this as SoD-family.
        if rel["role_kind"] != "LAB_DIRECTOR":
            raise err_clia_sod_violation("released_by must have role_kind=LAB_DIRECTOR")

        # Patient consent (priority 8)
        patient = get_patient(order["patient_id"])
        if result["critical_flags"] and patient["notification_consent"] == "NONE":
            raise err_patient_consent_blocked("Patient has notification_consent=NONE")

        # Clinician active (priority 14)
        if not rel.get("active", True):
            raise err_clinician_inactive("releasing clinician is inactive")

        # OCC (priority 16)
        occ_check(body.get("version"), result["version"])

        # Perform release
        result["released_by_id"] = rel_id
        result["status"] = "RELEASED"
        result["released_at"] = now()

        # Recompute severity_score_final
        history_count = history_critical_count(
            patient_id=order["patient_id"],
            panel_id=order["panel_id"],
            exclude_result_id=result["id"],
        )
        result["severity_score"] = calc.severity_score_final(result["critical_flags"], history_count)
        bump(result)

        order["status"] = "RELEASED"
        bump(order)

        # Audit + notification
        write_audit_event(
            event_type="RESULT_RELEASED",
            lab_order_id=order["id"],
            actor_id=rel_id,
            payload={"result_id": result["id"], "critical_flags_count": len(result["critical_flags"])},
        )
        if result["critical_flags"]:
            notif = create_critical_notification(result, order)
            write_audit_event(
                event_type="CRITICAL_NOTIFIED",
                lab_order_id=order["id"],
                actor_id="system",
                payload={
                    "notification_id": notif["id"],
                    "critical_analyte_codes": [f["analyte_code"] for f in result["critical_flags"]],
                },
            )

        # If this order has a parent retest, mark that retest FULFILLED
        if order.get("parent_order_id"):
            for r in store().retest_requests.values():
                if r.get("new_lab_order_id") == order["id"] and r["status"] == "ISSUED":
                    r["status"] = "FULFILLED"
                    bump(r)
    return ok(lab_result_view(result))


# ===========================================================================
# Amend a RELEASED result
# ===========================================================================

def _validate_measurements_for_amend(measurements_raw, panel: dict) -> list[dict]:
    # Same shape as create_result's check, inlined.
    if not isinstance(measurements_raw, list):
        from ..errors import err_measurements_incomplete
        raise err_measurements_incomplete("measurements must be an array")
    panel_codes = [a["analyte_code"] for a in panel["analytes"]]
    panel_unit = {a["analyte_code"]: a["unit"] for a in panel["analytes"]}
    seen: dict[str, dict] = {}
    out: list[dict] = []
    from ..errors import err_measurements_incomplete
    for i, m in enumerate(measurements_raw):
        if not isinstance(m, dict):
            raise err_measurements_incomplete(f"measurements[{i}] must be an object")
        code = m.get("analyte_code")
        unit = m.get("unit")
        value = m.get("value")
        if not isinstance(code, str) or code not in panel_codes:
            raise err_measurements_incomplete(f"measurements[{i}]: analyte_code '{code}' not on panel")
        if code in seen:
            raise err_measurements_incomplete(f"measurements[{i}]: analyte_code '{code}' duplicated")
        if not isinstance(unit, str) or unit != panel_unit[code]:
            raise err_measurements_incomplete(f"measurements[{i}]: unit mismatch")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise err_measurements_incomplete(f"measurements[{i}]: value must be a number")
        seen[code] = m
        out.append({"analyte_code": code, "value": value, "unit": unit})
    missing = [c for c in panel_codes if c not in seen]
    if missing:
        raise err_measurements_incomplete(f"missing analytes: {missing}")
    return out


@bp.route("/results/<rid>/amend", methods=["POST"])
@require_roles(ROLE_LAB_DIRECTOR)
def amend_result(rid, **_):
    body = require_json_object()
    measurements_raw = body.get("measurements")
    if measurements_raw is None:
        raise err_validation("measurements is required")

    with store().lock:
        result = get_lab_result(rid)
        if result["status"] != "RELEASED":
            raise err_invalid_state(f"LabResult must be RELEASED to amend (was {result['status']})")
        occ_check(body.get("version"), result["version"])

        order = get_lab_order(result["lab_order_id"])
        panel = get_test_panel(order["panel_id"])
        measurements = _validate_measurements_for_amend(measurements_raw, panel)

        prior_flags = list(result["critical_flags"])
        prior_flag_keys = {(f["analyte_code"], f["side"]) for f in prior_flags}

        new_flags = calc.compute_critical_flags(measurements, panel)
        new_flag_keys = {(f["analyte_code"], f["side"]) for f in new_flags}
        flags_changed = prior_flag_keys != new_flag_keys

        # Newly-critical: flags in new but not in prior
        newly_critical = [f for f in new_flags if (f["analyte_code"], f["side"]) not in prior_flag_keys]

        result["measurements"] = measurements
        result["critical_flags"] = new_flags
        history_count = history_critical_count(
            patient_id=order["patient_id"],
            panel_id=order["panel_id"],
            exclude_result_id=result["id"],
        )
        result["severity_score"] = calc.severity_score_final(new_flags, history_count)
        result["status"] = "AMENDED"
        bump(result)

        write_audit_event(
            event_type="AMENDMENT_RECORDED",
            lab_order_id=order["id"],
            actor_id=result.get("released_by_id") or "system",
            payload={
                "result_id": result["id"],
                "flags_changed": flags_changed,
                "retract": False,
            },
        )

        if flags_changed:
            issue_retest(order, reason="RESULT_AMENDED")
            if newly_critical:
                # Open a notification scoped to the newly-critical analytes
                # Patient consent applies here too — if NONE, skip silently? PRD says consent blocks release.
                patient = get_patient(order["patient_id"])
                if patient["notification_consent"] != "NONE":
                    notif = create_critical_notification(result, order, flags_subset=newly_critical)
                    write_audit_event(
                        event_type="CRITICAL_NOTIFIED",
                        lab_order_id=order["id"],
                        actor_id="system",
                        payload={
                            "notification_id": notif["id"],
                            "critical_analyte_codes": [f["analyte_code"] for f in newly_critical],
                            "scope": "amendment",
                        },
                    )
    return ok(lab_result_view(result))


# ===========================================================================
# Retract an AMENDED result
# ===========================================================================

@bp.route("/results/<rid>/retract", methods=["POST"])
@require_roles(ROLE_LAB_DIRECTOR)
def retract_result(rid, **_):
    body = require_json_object()
    with store().lock:
        result = get_lab_result(rid)
        if result["status"] != "AMENDED":
            raise err_invalid_state(f"LabResult must be AMENDED to retract (was {result['status']})")
        occ_check(body.get("version"), result["version"])

        order = get_lab_order(result["lab_order_id"])
        result["status"] = "RETRACTED"
        bump(result)
        # Order remains RELEASED — but audit-logged.
        write_audit_event(
            event_type="AMENDMENT_RECORDED",
            lab_order_id=order["id"],
            actor_id=result.get("released_by_id") or "system",
            payload={"result_id": result["id"], "retract": True},
        )
    return ok(lab_result_view(result))
