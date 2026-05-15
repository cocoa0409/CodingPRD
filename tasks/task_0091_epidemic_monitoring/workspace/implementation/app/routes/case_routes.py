"""Case endpoints + cases recovery."""
from __future__ import annotations

from datetime import timedelta

from flask import Flask, request

from ..audit import append_audit
from ..auth import current_actor, require_auth
from ..clock import add_hours, now_dt, now_iso_ms, parse_iso
from ..constants import CASE_TYPES, ENTITY_BACKED_ROLES, REPORT_LIMIT_HOURS
from ..errors import ApiError
from ..pagination import parse_limit_offset
from ..services.calculations import compute_case_density_score
from ..store import bump_version, common_fields_create, get_store
from ._helpers import check_version, get_json_body, ok, ok_list, with_lock


def register(app: Flask) -> None:
    app.add_url_rule(
        "/epi/cases",
        view_func=require_auth("HospitalReporter", "CDCDispatcher")(with_lock(create_case)),
        methods=["POST"],
    )
    app.add_url_rule(
        "/epi/cases/<case_id>",
        view_func=require_auth(
            "CDCSupervisor", "CDCDispatcher", "CDCTracer", "HospitalReporter"
        )(with_lock(get_case)),
        methods=["GET"],
    )
    app.add_url_rule(
        "/epi/cases",
        view_func=require_auth(
            "CDCSupervisor", "CDCDispatcher", "CDCTracer", "HospitalReporter"
        )(with_lock(list_cases)),
        methods=["GET"],
        endpoint="list_cases",
    )
    app.add_url_rule(
        "/epi/cases/<case_id>/recover",
        view_func=require_auth("CDCDispatcher")(with_lock(recover_case)),
        methods=["POST"],
    )


def _ensure_institution_active(inst_id: str):
    store = get_store()
    inst = store.institutions.get(inst_id)
    if not inst:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", f"reporting_institution_id {inst_id} not found.")
    if inst.get("status") != "ACTIVE":
        raise ApiError("ERR_INSTITUTION_INACTIVE", "Reporting institution is not ACTIVE.")
    return inst


def _recompute_provisional_for_person_region(person_id: str) -> None:
    store = get_store()
    person = store.persons.get(person_id)
    if not person:
        return
    district = person.get("district_code")
    if not district:
        return
    for region in store.regions.values():
        if region.get("district_code") == district:
            _score, tier = compute_case_density_score(region)
            region["provisional_risk_tier"] = tier
            bump_version(region)
            break


def create_case():
    body = get_json_body()
    store = get_store()
    user_id, role = current_actor()

    person_id = body.get("person_id")
    inst_id = body.get("reporting_institution_id")
    case_type = body.get("case_type")
    onset = body.get("onset_date")
    symptoms = body.get("symptoms") or []
    exposure_history = body.get("exposure_history") or []

    if not person_id or not inst_id or not case_type or not onset:
        raise ApiError("ERR_INVALID_INPUT", "Missing required fields.")
    if case_type not in CASE_TYPES:
        raise ApiError(
            "ERR_INVALID_INPUT", f"case_type must be one of {sorted(CASE_TYPES)}."
        )

    # FK existence checks (priority 4)
    if person_id not in store.persons:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", f"person_id {person_id} not found.")
    inst = _ensure_institution_active(inst_id)

    # Entity-backed ownership: role HospitalReporter or CDCDispatcher must own institution
    if role in ENTITY_BACKED_ROLES:
        if user_id != inst_id:
            raise ApiError(
                "ERR_FORBIDDEN",
                "X-User-ID must match reporting_institution_id for this role.",
            )

    try:
        onset_dt = parse_iso(onset)
    except Exception as exc:
        raise ApiError("ERR_INVALID_INPUT", f"Invalid onset_date: {exc}")

    now = now_dt()
    reported_at_dt = now
    report_deadline_dt = add_hours(onset_dt, REPORT_LIMIT_HOURS)
    is_late = reported_at_dt > report_deadline_dt

    # Deduplication priority (PRD §3.2):
    #   - Same reporting_institution_id files a duplicate report → auto-DEDUPLICATED.
    #   - Different reporting_institution_id races the same (person_id, case_type) →
    #     loser receives ERR_DUPLICATE_CASE.
    NON_TERMINAL = {"REPORTED", "UNDER_TRACING", "CONFIRMED"}
    winning_case_id = None
    winning_inst_id = None
    for c in store.cases.values():
        if c.get("person_id") == person_id and c.get("case_type") == case_type and c.get("status") in NON_TERMINAL:
            winning_case_id = c["id"]
            winning_inst_id = c.get("reporting_institution_id")
            break
    if winning_case_id and winning_inst_id != inst_id:
        raise ApiError(
            "ERR_DUPLICATE_CASE",
            "Another institution already filed a non-terminal case for "
            "this (person_id, case_type).",
        )

    case = {
        **common_fields_create(),
        "person_id": person_id,
        "reporting_institution_id": inst_id,
        "case_type": case_type,
        "onset_date": onset,
        "reported_at": now_iso_ms(),
        "report_deadline_at": _iso_from_dt(report_deadline_dt),
        "is_late_report": bool(is_late),
        "symptoms": list(symptoms),
        "exposure_history": list(exposure_history),
        "status": "REPORTED",
        "superseded_by_case_id": None,
    }

    if winning_case_id:
        case["status"] = "DEDUPLICATED"
        case["superseded_by_case_id"] = winning_case_id
        store.cases[case["id"]] = case
        append_audit("Case", case["id"], "REPORTED", "DEDUPLICATED", actor_role=role, actor_id=user_id)
        return ok(case, status=201)

    store.cases[case["id"]] = case
    # update Person.latest_case_id
    person = store.persons[person_id]
    person["latest_case_id"] = case["id"]
    bump_version(person)

    # Provisional region recompute
    _recompute_provisional_for_person_region(person_id)
    return ok(case, status=201)


def _iso_from_dt(dt) -> str:
    from ..clock import format_iso
    return format_iso(dt)  # type: ignore[return-value]


def get_case(case_id: str):
    store = get_store()
    c = store.cases.get(case_id)
    if not c:
        raise ApiError("ERR_NOT_FOUND", f"Case {case_id} not found.")
    return ok(c)


def list_cases():
    store = get_store()
    district = request.args.get("district_code")
    status = request.args.get("status")
    case_type = request.args.get("case_type")
    since = request.args.get("since")
    until = request.args.get("until")
    limit, offset = parse_limit_offset()

    items = list(store.cases.values())
    if status:
        items = [c for c in items if c.get("status") == status]
    if case_type:
        items = [c for c in items if c.get("case_type") == case_type]
    if district:
        items = [
            c
            for c in items
            if (store.persons.get(c.get("person_id"), {}).get("district_code") == district)
        ]
    if since:
        try:
            s_dt = parse_iso(since)
            items = [c for c in items if parse_iso(c.get("reported_at")) >= s_dt]
        except Exception:
            raise ApiError("ERR_INVALID_INPUT", f"Invalid since: {since!r}")
    if until:
        try:
            u_dt = parse_iso(until)
            items = [c for c in items if parse_iso(c.get("reported_at")) <= u_dt]
        except Exception:
            raise ApiError("ERR_INVALID_INPUT", f"Invalid until: {until!r}")

    items.sort(key=lambda c: c.get("created_at", ""))
    return ok_list(items, limit, offset)


def recover_case(case_id: str):
    body = get_json_body()
    store = get_store()
    case = store.cases.get(case_id)
    if not case:
        raise ApiError("ERR_NOT_FOUND", f"Case {case_id} not found.")
    check_version(case, body)
    if case.get("status") != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", "Case must be CONFIRMED to recover.")

    # Linked Isolation for person must be RELEASED
    person_id = case.get("person_id")
    linked_iso = None
    for iso in store.isolations.values():
        if iso.get("person_id") == person_id:
            # Pick the most recent isolation by created_at
            if linked_iso is None or iso.get("created_at", "") > linked_iso.get("created_at", ""):
                linked_iso = iso
    if linked_iso is None or linked_iso.get("status") != "RELEASED":
        raise ApiError("ERR_INVALID_STATE", "Linked isolation must be RELEASED.")

    # >=2 prior NEGATIVE PCR TestOrders with chronologically distinct collection dates
    neg_dates: set[tuple[int, int, int]] = set()
    neg_count = 0
    for t in store.test_orders.values():
        if t.get("person_id") != person_id:
            continue
        if t.get("status") != "RESULTED":
            continue
        if t.get("result") != "NEGATIVE":
            continue
        if t.get("test_type") != "PCR":
            continue
        collected = t.get("collected_at")
        if not collected:
            continue
        try:
            cdt = parse_iso(collected)
        except Exception:
            continue
        neg_count += 1
        neg_dates.add((cdt.year, cdt.month, cdt.day))
    if neg_count < 2 or len(neg_dates) < 2:
        raise ApiError(
            "ERR_INVALID_STATE",
            "Need at least 2 prior NEGATIVE PCR tests with distinct collection dates.",
        )

    prev = case["status"]
    case["status"] = "RECOVERED"
    bump_version(case)
    user_id, role = current_actor()
    append_audit("Case", case["id"], prev, "RECOVERED", actor_role=role, actor_id=user_id)
    return ok(case)
