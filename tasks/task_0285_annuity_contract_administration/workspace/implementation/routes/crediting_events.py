"""CreditingEvent endpoints (PRD §3.3).

Three crediting engines (FIXED_GUARANTEED, INDEX_SEGMENT, SUBACCOUNT_RETURN),
append-only ledger entries with only id + created_at (no version/updated_at).
"""

from flask import Blueprint, request

import errors
import validation as v
from clock import iso8601, parse_iso8601
from db import store
from middleware import authenticate, authorize
from response import object_response, array_response
from decimal import Decimal

from services import contract as contract_svc
from services import lookups
from services.money import round_half_up, round_half_up_decimal

bp = Blueprint("crediting_events", __name__)

READ_ROLES = {"ContractAdmin", "CreditingOfficer", "ComplianceOfficer"}
CREDITING_KINDS = {"FIXED_GUARANTEED", "INDEX_SEGMENT", "SUBACCOUNT_RETURN"}
KIND_FOR_TYPE = {
    "FIXED": "FIXED_GUARANTEED",
    "INDEXED": "INDEX_SEGMENT",
    "VARIABLE": "SUBACCOUNT_RETURN",
}


def serialize(c):
    # Append-only: id + created_at only, plus the data payload.
    return {
        "id": c["id"],
        "contract_id": c["contract_id"],
        "crediting_kind": c["crediting_kind"],
        "source_segment_id": c["source_segment_id"],
        "source_allocation_id": c["source_allocation_id"],
        "raw_index_return_bps": c["raw_index_return_bps"],
        "credit_period_start": c["credit_period_start"],
        "credit_period_end": c["credit_period_end"],
        "credit_cents": c["credit_cents"],
        "posted_period_index": c["posted_period_index"],
        "created_at": c["created_at"],
    }


def _kind_mismatch(msg):
    return errors.ApiError(errors.ERR_CREDITING_KIND_MISMATCH, 422, msg)


@bp.post("/crediting-events")
def create_crediting_event():
    _, role = authenticate()
    authorize(role, {"CreditingOfficer"})
    body = v.get_json_body()

    contract_id = v.require_string(body, "contract_id")
    crediting_kind = v.require_enum(body, "crediting_kind", CREDITING_KINDS)
    source_segment_id = v.optional_string(body, "source_segment_id")
    source_allocation_id = v.optional_string(body, "source_allocation_id")

    contract = lookups.ref_contract(contract_id)
    # FK existence for provided source references.
    if source_segment_id is not None:
        lookups.ref_segment(source_segment_id)
    if source_allocation_id is not None:
        lookups.ref_allocation(source_allocation_id)

    product = store.products[contract["product_id"]]
    expected_kind = KIND_FOR_TYPE[product["contract_type"]]

    # Crediting kind must match the contract's product type, and carry its
    # required source reference.
    if crediting_kind != expected_kind:
        raise _kind_mismatch("crediting_kind does not match the contract type.")
    if crediting_kind == "INDEX_SEGMENT" and source_segment_id is None:
        raise _kind_mismatch("INDEX_SEGMENT crediting requires source_segment_id.")
    if crediting_kind == "SUBACCOUNT_RETURN" and source_allocation_id is None:
        raise _kind_mismatch("SUBACCOUNT_RETURN crediting requires source_allocation_id.")

    acc = contract_svc.accumulation_value_cents(contract)

    raw_return = None
    period_start_raw = None
    period_end_raw = None

    if crediting_kind == "FIXED_GUARANTEED":
        rate = product["fixed_annual_rate_bps"] or 0
        credit = round_half_up(acc * rate, 10000)

    elif crediting_kind == "INDEX_SEGMENT":
        segment = store.index_segments[source_segment_id]
        if segment["contract_id"] != contract_id:
            raise _kind_mismatch("Segment does not belong to the contract.")
        raw_return = v.require_int(body, "raw_index_return_bps")
        period_start_raw = v.require_string(body, "credit_period_start")
        period_end_raw = v.require_string(body, "credit_period_end")
        ps = parse_iso8601(period_start_raw)
        pe = parse_iso8601(period_end_raw)
        if ps is None or pe is None:
            raise errors.invalid_request("credit_period_* must be ISO 8601 timestamps.")
        if ps >= pe:
            raise errors.invalid_request(
                "credit_period_start must precede credit_period_end."
            )

        # Credit-period window + overlap/touch checks are evaluated BEFORE the
        # segment-OPEN state check: the period-overlap test fixture posts a
        # second, touching period against the (now CREDITED) segment and
        # expects ERR_CREDIT_PERIOD_OVERLAP rather than ERR_INVALID_STATE
        # (PRD §3.3, §1.8 crediting_period_touch_rejected_closed_buffer).
        term_start = parse_iso8601(segment["term_start_date"])
        term_end = parse_iso8601(segment["term_end_date"])
        if ps < term_start or pe > term_end:
            raise errors.ApiError(
                errors.ERR_CREDIT_PERIOD_OVERLAP,
                409,
                "Credit period falls outside the segment term window.",
            )

        # No overlap OR touch with prior crediting periods for the same segment.
        for prior in store.crediting_events.values():
            if prior.get("source_segment_id") == source_segment_id:
                pp_s = parse_iso8601(prior["credit_period_start"])
                pp_e = parse_iso8601(prior["credit_period_end"])
                overlap = ps < pp_e and pp_s < pe
                touch = ps == pp_e or pe == pp_s
                if overlap or touch:
                    raise errors.ApiError(
                        errors.ERR_CREDIT_PERIOD_OVERLAP,
                        409,
                        "Credit period overlaps or touches a prior crediting period.",
                    )

        # Segment must be OPEN (a CREDITED segment rejects further crediting)
        # once the period passes the overlap gate.
        if segment["status"] != "OPEN":
            raise errors.invalid_state("Index segment is not OPEN.")

        # participated = raw * participation / 10000 ; then cap (min) ; then floor (max).
        participated = Decimal(raw_return) * Decimal(segment["participation_bps"]) / Decimal(10000)
        capped = min(participated, Decimal(segment["cap_bps"]))
        bounded = max(capped, Decimal(segment["floor_bps"]))
        credit = round_half_up_decimal(
            Decimal(segment["segment_premium_cents"]) * bounded / Decimal(10000)
        )
        credit = max(credit, 0)

    else:  # SUBACCOUNT_RETURN
        alloc = store.sub_account_allocations[source_allocation_id]
        if alloc["contract_id"] != contract_id:
            raise _kind_mismatch("Allocation does not belong to the contract.")
        raw_return = v.require_int(body, "raw_index_return_bps")
        share = Decimal(acc) * Decimal(alloc["allocation_bps"]) / Decimal(10000)
        credit = round_half_up_decimal(share * Decimal(raw_return) / Decimal(10000))
        credit = max(credit, 0)

    now = store.clock.now()
    cid = store.new_id()
    event = {
        "id": cid,
        "contract_id": contract_id,
        "crediting_kind": crediting_kind,
        "source_segment_id": source_segment_id,
        "source_allocation_id": source_allocation_id,
        "raw_index_return_bps": raw_return,
        "credit_period_start": period_start_raw,
        "credit_period_end": period_end_raw,
        "credit_cents": credit,
        "posted_period_index": store.next_crediting_period(),
        "created_at": iso8601(now),
        "_seq": store.next_seq(),
    }
    store.crediting_events[cid] = event

    # INDEX_SEGMENT crediting closes the segment.
    if crediting_kind == "INDEX_SEGMENT":
        segment = store.index_segments[source_segment_id]
        segment["status"] = "CREDITED"
        segment["version"] += 1
        segment["updated_at"] = iso8601(now)

    # Crediting bumps the contract version (accumulation changed).
    contract_svc.bump(contract)

    return object_response(serialize(event), 201, now)


@bp.get("/crediting-events")
def list_crediting_events():
    _, role = authenticate()
    authorize(role, READ_ROLES)
    limit, offset = v.parse_pagination()
    contract_filter = request.args.get("contract_id")
    segment_filter = request.args.get("source_segment_id")
    allocation_filter = request.args.get("source_allocation_id")

    rows = lookups.sorted_by_creation(list(store.crediting_events.values()))
    if contract_filter is not None:
        rows = [c for c in rows if c["contract_id"] == contract_filter]
    if segment_filter is not None:
        rows = [c for c in rows if c["source_segment_id"] == segment_filter]
    if allocation_filter is not None:
        rows = [c for c in rows if c["source_allocation_id"] == allocation_filter]
    page, total = lookups.paginate(rows, limit, offset)
    return array_response(
        [serialize(c) for c in page], total, limit, offset, store.clock.now()
    )


@bp.get("/crediting-events/<rid>")
def get_crediting_event(rid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    event = lookups.path_crediting_event(rid)
    return object_response(serialize(event), 200, store.clock.now())
