"""Isolation endpoints."""
from __future__ import annotations

from datetime import timedelta

from flask import Flask

from ..audit import append_audit
from ..auth import current_actor, require_auth
from ..clock import format_iso, now_dt, now_iso_ms, parse_iso
from ..constants import EXTENSION_DAYS, FEVER_THRESHOLD, ISOLATION_MIN_DAYS, ISOLATION_MODES
from ..errors import ApiError
from ..services.calculations import evaluate_release
from ..store import bump_version, common_fields_append_only, common_fields_create, get_store
from ._helpers import check_version, get_json_body, ok, with_lock


def register(app: Flask) -> None:
    app.add_url_rule(
        "/epi/isolations",
        view_func=require_auth("CDCTracer")(with_lock(create_isolation)),
        methods=["POST"],
    )
    app.add_url_rule(
        "/epi/isolations/<iso_id>",
        view_func=require_auth("CDCSupervisor", "CDCTracer")(with_lock(get_isolation)),
        methods=["GET"],
    )
    app.add_url_rule(
        "/epi/isolations/<iso_id>/daily-report",
        view_func=require_auth("CDCTracer", "HospitalReporter")(
            with_lock(submit_daily_report)
        ),
        methods=["POST"],
    )
    app.add_url_rule(
        "/epi/isolations/<iso_id>/violation",
        view_func=require_auth("CDCTracer")(with_lock(record_violation)),
        methods=["POST"],
    )
    app.add_url_rule(
        "/epi/isolations/<iso_id>/check-release",
        view_func=require_auth("CDCTracer")(with_lock(check_release)),
        methods=["POST"],
    )


def _latest_case_for_person(person_id: str):
    store = get_store()
    best = None
    for c in store.cases.values():
        if c.get("person_id") != person_id:
            continue
        if c.get("status") == "DEDUPLICATED":
            continue
        if best is None or c.get("reported_at", "") > best.get("reported_at", ""):
            best = c
    return best


def create_isolation():
    body = get_json_body()
    store = get_store()

    person_id = body.get("person_id")
    mode = body.get("mode")
    facility_id = body.get("facility_id")
    start_date = body.get("start_date")

    if not person_id or not mode or not start_date:
        raise ApiError("ERR_INVALID_INPUT", "Missing required fields.")
    if mode not in ISOLATION_MODES:
        raise ApiError(
            "ERR_INVALID_INPUT", f"mode must be one of {sorted(ISOLATION_MODES)}."
        )

    if person_id not in store.persons:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", f"person_id {person_id} not found.")
    if facility_id is not None and facility_id not in store.facilities:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", f"facility_id {facility_id} not found.")

    # Validate start_date (priority 11): not future; not before existing index Case.onset_date
    try:
        start_dt = parse_iso(start_date)
    except Exception as exc:
        raise ApiError("ERR_INVALID_INPUT", f"Invalid start_date: {exc}")
    if start_dt > now_dt():
        raise ApiError("ERR_ISOLATION_DATE_INVALID", "start_date cannot be in the future.")
    latest_case = _latest_case_for_person(person_id)
    if latest_case and latest_case.get("onset_date"):
        try:
            onset_dt = parse_iso(latest_case["onset_date"])
            if start_dt < onset_dt:
                raise ApiError(
                    "ERR_ISOLATION_DATE_INVALID",
                    "start_date cannot be earlier than the indexing Case.onset_date.",
                )
        except ApiError:
            raise
        except Exception:
            pass

    facility = None
    if mode == "CENTRALIZED":
        if not facility_id:
            raise ApiError("ERR_INVALID_INPUT", "facility_id required for CENTRALIZED mode.")
        facility = store.facilities.get(facility_id)
        if not facility:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", f"facility_id {facility_id} not found.")
        if facility.get("status") != "OPEN" or int(facility.get("occupied", 0)) >= int(
            facility.get("capacity", 0)
        ):
            raise ApiError("ERR_FACILITY_AT_CAPACITY", "Facility is full or not OPEN.")

    min_days = ISOLATION_MIN_DAYS[mode]
    planned_end_dt = start_dt + timedelta(days=min_days)

    iso = {
        **common_fields_create(),
        "person_id": person_id,
        "mode": mode,
        "facility_id": facility_id if mode == "CENTRALIZED" else None,
        "start_date": start_date,
        "planned_end_date": format_iso(planned_end_dt),
        "actual_end_date": None,
        "status": "ACTIVE",
        "extension_count": 0,
        "daily_reports_received": 0,
        "violations_count": 0,
    }
    store.isolations[iso["id"]] = iso

    person = store.persons[person_id]
    person["isolation_status"] = "ACTIVE"
    bump_version(person)

    if facility:
        facility["occupied"] = int(facility.get("occupied", 0)) + 1
        if int(facility["occupied"]) >= int(facility.get("capacity", 0)):
            facility["status"] = "FULL"
        bump_version(facility)

    return ok(iso, status=201)


def get_isolation(iso_id: str):
    store = get_store()
    iso = store.isolations.get(iso_id)
    if not iso:
        raise ApiError("ERR_NOT_FOUND", f"Isolation {iso_id} not found.")
    return ok(iso)


def submit_daily_report(iso_id: str):
    body = get_json_body()
    store = get_store()
    iso = store.isolations.get(iso_id)
    if not iso:
        raise ApiError("ERR_NOT_FOUND", f"Isolation {iso_id} not found.")

    report_date = body.get("report_date")
    temp = body.get("temperature_c")
    symptoms = body.get("symptoms") or []
    if not report_date or temp is None:
        raise ApiError("ERR_INVALID_INPUT", "Missing required fields.")
    try:
        temp_f = float(temp)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_INPUT", "temperature_c must be a number.")

    is_abnormal = (temp_f >= FEVER_THRESHOLD) or (isinstance(symptoms, list) and len(symptoms) > 0)
    base = common_fields_append_only()
    row = {
        **base,
        "isolation_id": iso_id,
        "report_date": report_date,
        "temperature_c": temp_f,
        "symptoms": list(symptoms) if isinstance(symptoms, list) else [],
        "is_abnormal": bool(is_abnormal),
    }
    store.daily_reports[row["id"]] = row

    iso["daily_reports_received"] = int(iso.get("daily_reports_received", 0)) + 1
    bump_version(iso)

    return ok(row, status=201)


def record_violation(iso_id: str):
    body = get_json_body()
    store = get_store()
    iso = store.isolations.get(iso_id)
    if not iso:
        raise ApiError("ERR_NOT_FOUND", f"Isolation {iso_id} not found.")
    if iso.get("status") not in ("ACTIVE", "EXTENDED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Violations can only be recorded against non-terminal isolations.",
        )
    check_version(iso, body)

    user_id, role = current_actor()
    prev_status = iso["status"]
    iso["violations_count"] = int(iso.get("violations_count", 0)) + 1
    iso["actual_end_date"] = now_iso_ms()
    iso["status"] = "VIOLATED_TERMINATED"
    bump_version(iso)

    person = store.persons.get(iso.get("person_id"))
    if person:
        person["isolation_status"] = "VIOLATED_TERMINATED"
        bump_version(person)

    if iso.get("mode") == "CENTRALIZED" and iso.get("facility_id"):
        facility = store.facilities.get(iso["facility_id"])
        if facility:
            facility["occupied"] = max(0, int(facility.get("occupied", 0)) - 1)
            if facility.get("status") == "FULL" and int(facility["occupied"]) < int(
                facility.get("capacity", 0)
            ):
                facility["status"] = "OPEN"
            bump_version(facility)

    append_audit(
        "Isolation",
        iso["id"],
        prev_status,
        "VIOLATED_TERMINATED",
        actor_role=role,
        actor_id=user_id,
    )
    return ok(iso)


def check_release(iso_id: str):
    body = get_json_body()
    store = get_store()
    iso = store.isolations.get(iso_id)
    if not iso:
        raise ApiError("ERR_NOT_FOUND", f"Isolation {iso_id} not found.")
    if iso.get("status") not in ("ACTIVE", "EXTENDED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Isolation must be ACTIVE or EXTENDED to evaluate release.",
        )
    check_version(iso, body)

    mode_hint = body.get("mode_hint")  # 'RELEASE_ONLY' optional gate
    outcome = evaluate_release(iso)

    user_id, role = current_actor()
    if outcome == "RELEASE":
        prev = iso["status"]
        iso["status"] = "RELEASED"
        iso["actual_end_date"] = now_iso_ms()
        bump_version(iso)
        person = store.persons.get(iso.get("person_id"))
        if person:
            person["isolation_status"] = "RELEASED"
            bump_version(person)
        if iso.get("mode") == "CENTRALIZED" and iso.get("facility_id"):
            facility = store.facilities.get(iso["facility_id"])
            if facility:
                facility["occupied"] = max(0, int(facility.get("occupied", 0)) - 1)
                if facility.get("status") == "FULL" and int(facility["occupied"]) < int(
                    facility.get("capacity", 0)
                ):
                    facility["status"] = "OPEN"
                bump_version(facility)
        append_audit("Isolation", iso["id"], prev, "RELEASED", actor_role=role, actor_id=user_id)
        return ok(iso)

    if outcome == "EXTEND":
        prev = iso["status"]
        iso["extension_count"] = int(iso.get("extension_count", 0)) + 1
        iso["planned_end_date"] = format_iso(now_dt() + timedelta(days=EXTENSION_DAYS))
        if iso["status"] != "EXTENDED":
            iso["status"] = "EXTENDED"
            bump_version(iso)
            append_audit("Isolation", iso["id"], prev, "EXTENDED", actor_role=role, actor_id=user_id)
        else:
            bump_version(iso)
        if mode_hint == "RELEASE_ONLY":
            raise ApiError("ERR_RELEASE_NOT_ELIGIBLE", "Not eligible for release.")
        return ok(iso)

    # NOT_ELIGIBLE
    if mode_hint == "RELEASE_ONLY":
        raise ApiError("ERR_RELEASE_NOT_ELIGIBLE", "Not eligible for release.")
    return ok(iso)
