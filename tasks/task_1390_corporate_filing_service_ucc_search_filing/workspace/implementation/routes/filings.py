"""UCC filing attempt routes: listing, lazy-lapse reads, name-check, submit,
record-acceptance (with all kind-specific root effects and cascades),
record-rejection, withdrawal, and the audit event log."""
from flask import Blueprint, request as flask_request

import errors
from db import store
from middleware import auth, body, opt_str, pagination_params, req_str, require_role
from response import ok, ok_list
from services import (
    CASCADE_OPEN_STATES, CONTINUATION_WINDOW_MONTHS, EFFECTIVENESS_MONTHS,
    REJECTION_REASONS, SUPERGENERIC_COLLATERAL, append_event, cancel_request,
    compute_fee_cents, decrement_root_ucc3_count,
    event_json, filing_json, lapse_if_due, name_of_record, profile_by_code, touch,
)
from util import add_months, fmt_dt, normalize_name, parse_dt

bp = Blueprint("filings", __name__)


def _paginate(records, serializer):
    limit, offset = pagination_params()
    items = [serializer(r) for r in records]
    return ok_list(items[offset:offset + limit], len(items), limit, offset)


def _filing_or_404(filing_id):
    f = store.filings.get(filing_id)
    if f is None:
        raise errors.err_not_found("filing")
    return f


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

@bp.get("/filings")
def list_filings():
    auth()
    records = list(store.filings.values())
    args = flask_request.args
    for param in ("debtor_id", "secured_party_id", "root_filing_id",
                  "supersedes_attempt_id", "effectiveness_status",
                  "reflection_status", "jurisdiction_code"):
        value = args.get(param)
        if value is not None:
            records = [f for f in records if f.get(param) == value]
    return _paginate(records, filing_json)


@bp.get("/filings/<filing_id>")
def get_filing(filing_id):
    auth()
    f = _filing_or_404(filing_id)
    lapse_if_due(f)  # lazy single-filing lapse refresh
    return ok(filing_json(f))


@bp.get("/filings/<filing_id>/name-check")
def name_check(filing_id):
    auth()
    f = _filing_or_404(filing_id)
    lapse_if_due(f)
    debtor = store.debtors.get(f["debtor_id"])
    profile = profile_by_code(f["jurisdiction_code"])
    record, rule_applied = name_of_record(debtor, profile)
    normalized_submitted = normalize_name(f["debtor_name_on_filing"])
    normalized_record = normalize_name(record) if record else None
    match = normalized_record is not None and normalized_submitted == normalized_record
    return ok({
        "match": match,
        "normalized_submitted": normalized_submitted,
        "normalized_of_record": normalized_record,
        "name_rule_applied": rule_applied,
    })


@bp.get("/filings/<filing_id>/events")
def list_events(filing_id):
    auth()
    _filing_or_404(filing_id)
    records = [e for e in store.events.values() if e["ucc_filing_id"] == filing_id]
    return _paginate(records, event_json)


# ---------------------------------------------------------------------------
# Submit (DRAFT -> SUBMITTED): full validation chain per PRD section 2.9
# ---------------------------------------------------------------------------

@bp.post("/filings/<filing_id>/submit")
def submit_filing(filing_id):
    auth()
    body()
    _user_id, role = auth()
    require_role(role, "FilingSpecialist")
    f = _filing_or_404(filing_id)
    req = store.filing_requests[f["filing_request_id"]]
    # Priority 7: request READY, then attempt from-state.
    if req["status"] != "READY":
        raise errors.err_request_not_ready()
    if f["effectiveness_status"] != "DRAFT":
        raise errors.err_filing_invalid_state("Only a DRAFT attempt may be submitted")
    debtor = store.debtors[f["debtor_id"]]
    profile = profile_by_code(f["jurisdiction_code"])
    # Priority 8: debtor-name accuracy.
    if debtor["debtor_type"] == "INDIVIDUAL" and profile["individual_name_rule"] == "DL_SAFE_HARBOR":
        record = debtor["drivers_license_name"]
        if not record:
            raise errors.err_dl_name_missing()
    else:
        record = debtor["legal_name"]
    if normalize_name(f["debtor_name_on_filing"]) != normalize_name(record):
        raise errors.err_name_misleading()
    # Priority 8: collateral sufficiency (INITIAL and COLLATERAL-scope amendments).
    if f["filing_kind"] == "INITIAL" or f["amendment_scope"] == "COLLATERAL":
        text = f["collateral_text"]
        if (
            text is None
            or len(text) < 20
            or normalize_name(text) in SUPERGENERIC_COLLATERAL
        ):
            raise errors.err_collateral_insufficient()
    # Priority 10: expedited daily capacity for the jurisdiction's UTC day.
    if req["service_level"] == "EXPEDITED":
        today = store.clock.date()
        used = 0
        for g in store.filings.values():
            if (
                g["submitted_at"] is not None
                and g["jurisdiction_code"] == f["jurisdiction_code"]
                and g["submitted_at"].date() == today
            ):
                g_req = store.filing_requests[g["filing_request_id"]]
                if g_req["service_level"] == "EXPEDITED":
                    used += 1
        if used >= profile["expedited_daily_capacity"]:
            raise errors.err_expedited_capacity()
    # Priority 11: fiscal gate.
    fee = compute_fee_cents(profile, req)
    if fee > req["fee_authorization_cents"]:
        raise errors.err_fee_exceeded()
    # Side effects.
    f["charged_fee_cents"] = fee
    f["submitted_at"] = store.clock
    f["effectiveness_status"] = "SUBMITTED"
    touch(f)
    client = store.clients[req["client_id"]]
    client["fees_charged_total_cents"] += fee
    touch(client)
    req["status"] = "IN_PROCESS"
    touch(req)
    append_event(f, "SUBMITTED", {
        "charged_fee_cents": fee,
        "submitted_at": fmt_dt(f["submitted_at"]),
    })
    return ok(filing_json(f))


# ---------------------------------------------------------------------------
# Record acceptance (SUBMITTED -> ACTIVE) with kind-specific root effects
# ---------------------------------------------------------------------------

@bp.post("/filings/<filing_id>/record-acceptance")
def record_acceptance(filing_id):
    auth()
    data = body()
    # Priority 2: structural.
    filing_number = req_str(data, "filing_number")
    if "filed_at" not in data or data["filed_at"] is None:
        raise errors.err_invalid_request("Missing required field: filed_at")
    filed_at = parse_dt(data["filed_at"])
    if filed_at is None:
        raise errors.err_invalid_request("filed_at must be an ISO 8601 datetime")
    # Priority 3: role.
    _user_id, role = auth()
    require_role(role, "FilingOfficer")
    # Priority 5: existence.
    f = _filing_or_404(filing_id)
    req = store.filing_requests[f["filing_request_id"]]
    kind = f["filing_kind"]
    root = store.filings.get(f["root_filing_id"]) if f["root_filing_id"] else None
    # Priority 7: attempt from-state, then target-state guards.
    if f["effectiveness_status"] != "SUBMITTED":
        raise errors.err_filing_invalid_state("record-acceptance requires SUBMITTED")
    if kind in ("AMENDMENT", "TERMINATION"):
        if root is None or root["effectiveness_status"] != "ACTIVE":
            raise errors.err_target_not_active()
    elif kind == "CONTINUATION":
        if root is None or root["effectiveness_status"] not in ("ACTIVE", "LAPSED"):
            raise errors.err_target_not_active()
    # Priority 8: safety guards.
    if kind == "INITIAL":
        for g in store.filings.values():
            if (
                g["id"] != f["id"]
                and g["filing_kind"] == "INITIAL"
                and g["debtor_id"] == f["debtor_id"]
                and g["jurisdiction_code"] == f["jurisdiction_code"]
                and g["filing_office"] == f["filing_office"]
                and g["effectiveness_status"] == "ACTIVE"
            ):
                raise errors.err_overlapping()
    if kind == "AMENDMENT" and f["amendment_scope"] == "COLLATERAL" \
            and f["collateral_change_op"] == "DELETE":
        if root["collateral_text"] is None or f["collateral_text"] not in root["collateral_text"]:
            raise errors.err_collateral_not_present()
    # Priority 9: temporal guards (filed_at bracket, then continuation window).
    if filed_at < f["submitted_at"] or filed_at > store.clock:
        raise errors.err_invalid_filed_at()
    if kind == "CONTINUATION":
        window_open = add_months(root["expiration_at"], -CONTINUATION_WINDOW_MONTHS)
        if not (window_open <= filed_at < root["expiration_at"]):
            raise errors.err_continuation_outside_window()
    # --- Side effects ------------------------------------------------------
    f["filing_number"] = filing_number
    f["filed_at"] = filed_at
    f["effectiveness_status"] = "ACTIVE"
    if kind == "INITIAL":
        f["expiration_at"] = add_months(filed_at, EFFECTIVENESS_MONTHS)
    touch(f)
    append_event(f, "ACCEPTED", {
        "filing_number": filing_number,
        "filed_at": fmt_dt(filed_at),
    })

    if kind == "CONTINUATION":
        # Extend from the root's stored expiration, never from filed_at.
        prior_expiration = root["expiration_at"]
        new_expiration = add_months(prior_expiration, EFFECTIVENESS_MONTHS)
        root["expiration_at"] = new_expiration
        if root["effectiveness_status"] == "LAPSED":
            root["effectiveness_status"] = "ACTIVE"
            append_event(root, "REVIVED", {"revived_by_filing_id": f["id"]})
        append_event(root, "CONTINUED", {
            "prior_expiration_at": fmt_dt(prior_expiration),
            "new_expiration_at": fmt_dt(new_expiration),
            "continuation_filing_id": f["id"],
        })
        touch(root)
    elif kind == "AMENDMENT":
        scope = f["amendment_scope"]
        detail = {"amendment_scope": scope, "amendment_filing_id": f["id"]}
        if scope == "DEBTOR_NAME":
            root["debtor_name_on_filing"] = f["debtor_name_on_filing"]
        elif scope == "COLLATERAL":
            op = f["collateral_change_op"]
            detail["collateral_change_op"] = op
            if op == "ADD":
                base = root["collateral_text"] or ""
                root["collateral_text"] = (base + ";" + f["collateral_text"]) if base else f["collateral_text"]
            elif op == "DELETE":
                root["collateral_text"] = root["collateral_text"].replace(f["collateral_text"], "", 1)
            elif op == "RESTATE":
                root["collateral_text"] = f["collateral_text"]
        elif scope == "SECURED_PARTY":
            root["secured_party_id"] = req["secured_party_id"]
        append_event(root, "AMENDED", detail)
        touch(root)
    elif kind == "TERMINATION":
        root["effectiveness_status"] = "TERMINATED"
        append_event(root, "TERMINATED", {"termination_filing_id": f["id"]})
        touch(root)
        # Cascade: cancel other open AMENDMENT/CONTINUATION requests on the root.
        for r in list(store.filing_requests.values()):
            if (
                r["id"] != req["id"]
                and r["target_filing_id"] == root["id"]
                and r["kind"] in ("AMENDMENT", "CONTINUATION")
                and r["status"] in CASCADE_OPEN_STATES
            ):
                cancel_request(r, "TARGET_TERMINATED")

    # Parent request: IN_PROCESS -> FULFILLED (with UCC-3 count compensation).
    req["status"] = "FULFILLED"
    touch(req)
    if req["kind"] != "NEW_UCC1" and root is not None:
        decrement_root_ucc3_count(root)
    return ok(filing_json(f))


# ---------------------------------------------------------------------------
# Record rejection (SUBMITTED -> REJECTED): correction loop opens
# ---------------------------------------------------------------------------

@bp.post("/filings/<filing_id>/record-rejection")
def record_rejection(filing_id):
    auth()
    data = body()
    if "rejection_reason_code" not in data or data["rejection_reason_code"] is None:
        raise errors.err_invalid_request("Missing required field: rejection_reason_code")
    code = data["rejection_reason_code"]
    if code not in REJECTION_REASONS:
        raise errors.err_invalid_request(
            f"rejection_reason_code must be one of {sorted(REJECTION_REASONS)}")
    note = opt_str(data, "rejection_note")
    _user_id, role = auth()
    require_role(role, "FilingOfficer")
    f = _filing_or_404(filing_id)
    if f["effectiveness_status"] != "SUBMITTED":
        raise errors.err_filing_invalid_state("record-rejection requires SUBMITTED")
    req = store.filing_requests[f["filing_request_id"]]
    f["rejection_reason_code"] = code
    f["rejection_note"] = note
    f["rejected_at"] = store.clock
    f["effectiveness_status"] = "REJECTED"
    touch(f)
    client = store.clients[req["client_id"]]
    client["fees_refunded_total_cents"] += f["charged_fee_cents"] or 0
    touch(client)
    req["status"] = "CORRECTION_REQUIRED"
    touch(req)
    append_event(f, "REJECTED", {
        "rejection_reason_code": code,
        "rejection_note": note,
    })
    return ok(filing_json(f))


# ---------------------------------------------------------------------------
# Withdraw (DRAFT -> WITHDRAWN)
# ---------------------------------------------------------------------------

@bp.post("/filings/<filing_id>/withdraw")
def withdraw_filing(filing_id):
    auth()
    body()
    _user_id, role = auth()
    require_role(role, "FilingSpecialist")
    f = _filing_or_404(filing_id)
    if f["effectiveness_status"] != "DRAFT":
        raise errors.err_filing_invalid_state("Only a DRAFT attempt may be withdrawn")
    f["effectiveness_status"] = "WITHDRAWN"
    touch(f)
    append_event(f, "WITHDRAWN", {})
    return ok(filing_json(f))
