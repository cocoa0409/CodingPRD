"""TicketType endpoints per PRD §3.4."""
from __future__ import annotations

import json
from typing import Any, Dict

from flask import Flask, request

from ._common import (
    ANY_ROLE,
    ApiError,
    DB,
    GLOBAL_LOCK,
    append_audit,
    check_if_match,
    get_json_body,
    idempotency_lookup_or_store,
    if_match_header,
    list_by_predicate,
    make_blueprint,
    optional_str,
    paginate_list,
    recompute_outstanding_tickets_total,
    require_enum,
    require_int,
    require_list,
    require_role,
    require_str,
    resolve_festival,
    server_now_iso8601,
    stamp_create,
    stamp_update,
    success_envelope,
    zone_capacity_check,
)


bp = make_blueprint("ticket_types")


_CLASSES = ("SINGLE_DAY", "FULL_FESTIVAL", "VIP")


def _payload(t: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": t["id"],
        "festival_id": t.get("festival_id"),
        "ticket_class": t.get("ticket_class"),
        "tied_program_item_ids": list(t.get("tied_program_item_ids", []) or []),
        "zone_name": t.get("zone_name"),
        "unit_price_cents": t.get("unit_price_cents"),
        "issued_count": int(t.get("issued_count", 0)),
        "refunded_count": int(t.get("refunded_count", 0)),
        "provisional_refund_cents_outstanding": int(
            t.get("provisional_refund_cents_outstanding", 0)
        ),
        "status": t.get("status", "ACTIVE"),
        "created_at": t.get("created_at"),
        "updated_at": t.get("updated_at"),
        "version": t.get("version"),
    }


def _resolve(festival_id: str, type_id: str) -> Dict[str, Any]:
    resolve_festival(festival_id)
    t = DB.ticket_types.get(type_id)
    if t is None:
        raise ApiError(
            "ERR_TICKET_TYPE_NOT_FOUND", f"ticket type {type_id} not found"
        )
    if t.get("festival_id") != festival_id:
        raise ApiError(
            "ERR_RESOURCE_MISMATCHED_PARENT",
            "ticket type belongs to a different festival",
        )
    return t


@bp.route("/festivals/<festival_id>/ticket-types", methods=["POST"])
def create_type(festival_id: str):
    require_role(["TicketingAdmin"])
    body = get_json_body()
    with GLOBAL_LOCK:
        festival = resolve_festival(festival_id)
        ticket_class = require_enum(body, "ticket_class", _CLASSES)
        ties_raw = require_list(body, "tied_program_item_ids", element_type=str)
        zone_name = require_str(body, "zone_name")
        unit_price = require_int(body, "unit_price_cents", non_negative=True)

        # Cross-reference: every tied item must exist under the same festival.
        for pi_id in ties_raw:
            pi = DB.program_items.get(pi_id)
            if pi is None:
                raise ApiError(
                    "ERR_PROGRAM_ITEM_NOT_FOUND",
                    f"tied program item {pi_id} not found",
                )
            if pi.get("festival_id") != festival_id:
                raise ApiError(
                    "ERR_RESOURCE_MISMATCHED_PARENT",
                    f"tied program item {pi_id} belongs to a different festival",
                )

        row = {
            "festival_id": festival_id,
            "ticket_class": ticket_class,
            "tied_program_item_ids": list(ties_raw),
            "zone_name": zone_name,
            "unit_price_cents": unit_price,
            "issued_count": 0,
            "refunded_count": 0,
            "provisional_refund_cents_outstanding": 0,
            "status": "ACTIVE",
        }
        stamp_create(row)
        DB.ticket_types[row["id"]] = row
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="TicketType",
            subject_entity_id=row["id"],
            to_state="ACTIVE",
            payload_summary=(
                f"ticket type ({ticket_class}) zone={zone_name!r} price={unit_price}c created"
            ),
        )
        recompute_outstanding_tickets_total(festival_id)
        out = _payload(row)
    return success_envelope(out, http_status=201)


@bp.route("/festivals/<festival_id>/ticket-types", methods=["GET"])
def list_types(festival_id: str):
    require_role(ANY_ROLE)
    status_f = request.args.get("status")
    class_f = request.args.get("ticket_class")
    zone_f = request.args.get("zone_name")
    with GLOBAL_LOCK:
        resolve_festival(festival_id)

        def _pred(r: dict) -> bool:
            if r.get("festival_id") != festival_id:
                return False
            if status_f is not None and r.get("status") != status_f:
                return False
            if class_f is not None and r.get("ticket_class") != class_f:
                return False
            if zone_f is not None and r.get("zone_name") != zone_f:
                return False
            return True

        rows = list_by_predicate(DB.ticket_types, _pred)
        page, meta = paginate_list(rows, request.args)
        out = [_payload(r) for r in page]
    return success_envelope(out, pagination=meta)


@bp.route("/festivals/<festival_id>/ticket-types/<type_id>", methods=["GET"])
def read_type(festival_id: str, type_id: str):
    require_role(ANY_ROLE)
    with GLOBAL_LOCK:
        t = _resolve(festival_id, type_id)
        out = _payload(t)
    return success_envelope(out)


@bp.route(
    "/festivals/<festival_id>/ticket-types/<type_id>/issue", methods=["POST"]
)
def issue_tickets(festival_id: str, type_id: str):
    require_role(["TicketingAdmin"])
    body = get_json_body()
    count = require_int(body, "count", positive=True)
    idempotency_key = body.get("idempotency_key")
    if idempotency_key is not None and not isinstance(idempotency_key, str):
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE", "idempotency_key must be a string when present"
        )
    with GLOBAL_LOCK:
        festival = resolve_festival(festival_id)
        replay, store_cb = idempotency_lookup_or_store(
            endpoint_label="POST /ticket-types/issue",
            idempotency_key=idempotency_key,
            body=body,
            festival_for_clock=festival,
        )
        if replay is not None:
            return replay

        t = _resolve(festival_id, type_id)
        if t.get("status") != "ACTIVE":
            raise ApiError(
                "ERR_TICKET_TYPE_NOT_ACTIVE",
                f"ticket type is in {t.get('status')!r}",
            )
        check_if_match(t, if_match_header())

        # Zone-capacity ceiling per PRD §3.4.  The "zero-capacity edge"
        # — when the zone group's union of tied-program-item stages is
        # empty (which is the case when this ticket type's
        # `tied_program_item_ids` list is empty and no other type in
        # the same zone group covers a stage) — is the dedicated
        # `ERR_TICKET_ZONE_NO_STAGE` 422 error per the §5 catalog.
        # The race-against-cascade variant `ERR_TICKET_TYPE_TIE_INVALID`
        # at 409 — the §2.5 outcome where the cascade trims the array
        # mid-flight — is a strictly different concurrency scenario and
        # is not the empty-from-the-start edge.
        zone_capacity_check(festival_id, type_id, int(count))

        t["issued_count"] = int(t.get("issued_count", 0)) + int(count)
        stamp_update(t)
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="TicketType",
            subject_entity_id=type_id,
            payload_summary=f"issued {count} tickets, new total {t['issued_count']}",
        )
        recompute_outstanding_tickets_total(festival_id)

        resp = success_envelope(_payload(t), http_status=200)
        if store_cb is not None:
            store_cb(resp.status_code, json.loads(resp.get_data(as_text=True)))
    return resp


@bp.route(
    "/festivals/<festival_id>/ticket-types/<type_id>/suspend", methods=["POST"]
)
def suspend_type(festival_id: str, type_id: str):
    require_role(["TicketingAdmin"])
    body = get_json_body()
    reason = optional_str(body, "reason", default="") or ""
    with GLOBAL_LOCK:
        t = _resolve(festival_id, type_id)
        check_if_match(t, if_match_header())
        if t.get("status") != "ACTIVE":
            raise ApiError(
                "ERR_TICKET_TYPE_NOT_ACTIVE",
                f"ticket type is in {t.get('status')!r}, cannot suspend",
            )
        t["status"] = "SUSPENDED"
        stamp_update(t)
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="TicketType",
            subject_entity_id=type_id,
            from_state="ACTIVE",
            to_state="SUSPENDED",
            payload_summary=f"ticket type suspended, reason: {reason!r}",
        )
        out = _payload(t)
    return success_envelope(out)


@bp.route(
    "/festivals/<festival_id>/ticket-types/<type_id>/resume", methods=["POST"]
)
def resume_type(festival_id: str, type_id: str):
    require_role(["TicketingAdmin"])
    with GLOBAL_LOCK:
        festival = resolve_festival(festival_id)
        t = _resolve(festival_id, type_id)
        check_if_match(t, if_match_header())
        if t.get("status") != "SUSPENDED":
            raise ApiError(
                "ERR_TICKET_TYPE_NOT_ACTIVE",
                f"ticket type is in {t.get('status')!r}, cannot resume",
            )
        if festival.get("status") not in ("SCHEDULING", "PUBLISHED", "LIVE"):
            raise ApiError(
                "ERR_FESTIVAL_NOT_SCHEDULING_OR_PUBLISHED",
                f"festival is {festival.get('status')!r}, cannot resume issuance",
            )
        t["status"] = "ACTIVE"
        stamp_update(t)
        append_audit(
            festival_id=festival_id,
            event_category="STATE_TRANSITION",
            subject_entity_type="TicketType",
            subject_entity_id=type_id,
            from_state="SUSPENDED",
            to_state="ACTIVE",
            payload_summary="ticket type resumed",
        )
        out = _payload(t)
    return success_envelope(out)


def register(app: Flask) -> None:
    app.register_blueprint(bp)
