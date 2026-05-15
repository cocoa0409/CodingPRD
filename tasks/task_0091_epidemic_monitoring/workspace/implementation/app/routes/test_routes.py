"""TestOrder endpoints."""
from __future__ import annotations

from datetime import timedelta

from flask import Flask, request

from ..audit import append_audit
from ..auth import current_actor, require_auth
from ..clock import now_dt, now_iso_ms, parse_iso
from ..constants import ENTITY_BACKED_ROLES, TEST_RESULTS, TEST_TYPES, TEST_VALIDITY_HOURS
from ..errors import ApiError
from ..pagination import parse_limit_offset
from ..services.calculations import compute_case_density_score
from ..store import bump_version, common_fields_create, get_store
from ._helpers import check_version, get_json_body, ok, ok_list, with_lock


def register(app: Flask) -> None:
    app.add_url_rule(
        "/epi/test-orders",
        view_func=require_auth("HospitalReporter", "CDCTracer")(with_lock(create_order)),
        methods=["POST"],
    )
    app.add_url_rule(
        "/epi/test-orders/<oid>/collect",
        view_func=require_auth("HospitalReporter")(with_lock(collect)),
        methods=["POST"],
    )
    app.add_url_rule(
        "/epi/test-orders/<oid>/result",
        view_func=require_auth("LabTechnician")(with_lock(ingest_result)),
        methods=["POST"],
    )
    app.add_url_rule(
        "/epi/test-orders/<oid>/flag-followup",
        view_func=require_auth("LabTechnician")(with_lock(flag_followup)),
        methods=["POST"],
    )
    app.add_url_rule(
        "/epi/test-orders/<oid>/close",
        view_func=require_auth("CDCTracer")(with_lock(close_order)),
        methods=["POST"],
    )
    app.add_url_rule(
        "/epi/test-orders/<oid>",
        view_func=require_auth(
            "CDCSupervisor", "CDCTracer", "HospitalReporter", "LabTechnician"
        )(with_lock(get_order)),
        methods=["GET"],
    )
    app.add_url_rule(
        "/epi/test-orders",
        view_func=require_auth(
            "CDCSupervisor", "CDCTracer", "HospitalReporter", "LabTechnician"
        )(with_lock(list_orders)),
        methods=["GET"],
        endpoint="list_orders",
    )


def create_order():
    body = get_json_body()
    store = get_store()
    user_id, role = current_actor()

    person_id = body.get("person_id")
    inst_id = body.get("ordering_institution_id")
    test_type = body.get("test_type")
    if not person_id or not inst_id or not test_type:
        raise ApiError("ERR_INVALID_INPUT", "Missing required fields.")
    if test_type not in TEST_TYPES:
        raise ApiError("ERR_INVALID_INPUT", f"test_type must be one of {sorted(TEST_TYPES)}.")
    if person_id not in store.persons:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", f"person_id {person_id} not found.")
    inst = store.institutions.get(inst_id)
    if not inst:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", f"ordering_institution_id {inst_id} not found.")
    if inst.get("status") != "ACTIVE":
        raise ApiError("ERR_INSTITUTION_INACTIVE", "Ordering institution is not ACTIVE.")

    order = {
        **common_fields_create(),
        "person_id": person_id,
        "ordering_institution_id": inst_id,
        "test_type": test_type,
        "collected_at": None,
        "result": "PENDING",
        "result_recorded_at": None,
        "status": "ORDERED",
        "chain_of_custody": [],
    }
    store.test_orders[order["id"]] = order
    return ok(order, status=201)


def _append_custody(order: dict, role: str, user_id: str, action: str) -> None:
    order.setdefault("chain_of_custody", []).append(
        {
            "actor_role": role,
            "actor_id": user_id,
            "action": action,
            "at": now_iso_ms(),
        }
    )


def collect(oid: str):
    body = get_json_body()
    store = get_store()
    order = store.test_orders.get(oid)
    if not order:
        raise ApiError("ERR_NOT_FOUND", f"TestOrder {oid} not found.")
    check_version(order, body)
    if order.get("status") != "ORDERED":
        raise ApiError("ERR_INVALID_STATE", "TestOrder must be ORDERED to COLLECT.")

    user_id, role = current_actor()
    order["collected_at"] = now_iso_ms()
    _append_custody(order, role, user_id, "COLLECT")
    order["status"] = "COLLECTED"
    bump_version(order)
    append_audit("TestOrder", order["id"], "ORDERED", "COLLECTED", actor_role=role, actor_id=user_id)
    return ok(order)


def ingest_result(oid: str):
    body = get_json_body()
    store = get_store()
    order = store.test_orders.get(oid)
    if not order:
        raise ApiError("ERR_NOT_FOUND", f"TestOrder {oid} not found.")
    check_version(order, body)
    if order.get("status") != "COLLECTED":
        raise ApiError("ERR_INVALID_STATE", "TestOrder must be COLLECTED to ingest result.")
    result = body.get("result")
    if result not in TEST_RESULTS:
        raise ApiError("ERR_INVALID_INPUT", f"result must be one of {sorted(TEST_RESULTS)}.")

    # Acting LabTechnician institution must be ACTIVE
    user_id, role = current_actor()
    inst = store.institutions.get(user_id)
    if not inst:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "Acting institution not found.")
    if inst.get("status") != "ACTIVE":
        raise ApiError("ERR_INSTITUTION_INACTIVE", "Acting institution is not ACTIVE.")

    # Validity window
    try:
        collected_dt = parse_iso(order.get("collected_at"))
    except Exception:
        raise ApiError("ERR_INVALID_STATE", "Missing collected_at on order.")
    elapsed_hours = (now_dt() - collected_dt).total_seconds() / 3600.0
    if elapsed_hours > TEST_VALIDITY_HOURS.get(order.get("test_type"), 24):
        raise ApiError(
            "ERR_TEST_RESULT_EXPIRED",
            "Result ingested beyond validity window.",
        )

    order["result"] = result
    order["result_recorded_at"] = now_iso_ms()
    _append_custody(order, role, user_id, "RESULT_INGEST")
    order["status"] = "RESULTED"
    bump_version(order)
    append_audit("TestOrder", order["id"], "COLLECTED", "RESULTED", actor_role=role, actor_id=user_id)

    # If POSITIVE PCR: advance Case for this person
    if result == "POSITIVE" and order.get("test_type") == "PCR":
        person_id = order.get("person_id")
        target_case = None
        for c in store.cases.values():
            if c.get("person_id") != person_id:
                continue
            if c.get("status") in ("REPORTED", "UNDER_TRACING"):
                if target_case is None or c.get("reported_at", "") > target_case.get("reported_at", ""):
                    target_case = c
        if target_case and target_case.get("status") == "UNDER_TRACING":
            # Advance to CONFIRMED. case_type SUSPECTED -> CONFIRMED, ASYMPTOMATIC stays.
            prev_status = target_case["status"]
            if target_case.get("case_type") == "SUSPECTED":
                target_case["case_type"] = "CONFIRMED"
            target_case["status"] = "CONFIRMED"
            bump_version(target_case)
            append_audit(
                "Case",
                target_case["id"],
                prev_status,
                "CONFIRMED",
                actor_role=role,
                actor_id=user_id,
            )
            # Region recompute
            person = store.persons.get(person_id)
            if person:
                district = person.get("district_code")
                for region in store.regions.values():
                    if region.get("district_code") == district:
                        _score, tier = compute_case_density_score(region)
                        region["provisional_risk_tier"] = tier
                        bump_version(region)
                        break

    return ok(order)


def flag_followup(oid: str):
    body = get_json_body()
    store = get_store()
    order = store.test_orders.get(oid)
    if not order:
        raise ApiError("ERR_NOT_FOUND", f"TestOrder {oid} not found.")
    check_version(order, body)
    if order.get("status") != "RESULTED":
        raise ApiError("ERR_INVALID_STATE", "Order must be RESULTED to flag followup.")
    if order.get("result") not in ("POSITIVE", "INVALID"):
        raise ApiError("ERR_INVALID_STATE", "Follow-up flag requires result POSITIVE or INVALID.")
    order["status"] = "FOLLOW_UP"
    bump_version(order)
    user_id, role = current_actor()
    append_audit("TestOrder", order["id"], "RESULTED", "FOLLOW_UP", actor_role=role, actor_id=user_id)
    return ok(order)


def close_order(oid: str):
    body = get_json_body()
    store = get_store()
    order = store.test_orders.get(oid)
    if not order:
        raise ApiError("ERR_NOT_FOUND", f"TestOrder {oid} not found.")
    check_version(order, body)
    prev = order.get("status")
    if prev == "FOLLOW_UP":
        order["status"] = "CLOSED"
    elif prev == "RESULTED" and order.get("result") == "NEGATIVE":
        order["status"] = "CLOSED"
    else:
        raise ApiError(
            "ERR_INVALID_STATE",
            "Order must be FOLLOW_UP, or RESULTED with NEGATIVE result, to close.",
        )
    bump_version(order)
    user_id, role = current_actor()
    append_audit("TestOrder", order["id"], prev, "CLOSED", actor_role=role, actor_id=user_id)
    return ok(order)


def get_order(oid: str):
    store = get_store()
    o = store.test_orders.get(oid)
    if not o:
        raise ApiError("ERR_NOT_FOUND", f"TestOrder {oid} not found.")
    return ok(o)


def list_orders():
    store = get_store()
    person_id = request.args.get("person_id")
    status = request.args.get("status")
    result = request.args.get("result")
    since = request.args.get("since")
    until = request.args.get("until")
    limit, offset = parse_limit_offset()

    items = list(store.test_orders.values())
    if person_id:
        items = [o for o in items if o.get("person_id") == person_id]
    if status:
        items = [o for o in items if o.get("status") == status]
    if result:
        items = [o for o in items if o.get("result") == result]
    if since:
        try:
            s_dt = parse_iso(since)
            items = [o for o in items if parse_iso(o.get("created_at")) >= s_dt]
        except Exception:
            raise ApiError("ERR_INVALID_INPUT", f"Invalid since: {since!r}")
    if until:
        try:
            u_dt = parse_iso(until)
            items = [o for o in items if parse_iso(o.get("created_at")) <= u_dt]
        except Exception:
            raise ApiError("ERR_INVALID_INPUT", f"Invalid until: {until!r}")

    items.sort(key=lambda o: o.get("created_at", ""))
    return ok_list(items, limit, offset)
