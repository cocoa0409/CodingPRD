"""Filing-request routes: intake, review/approval, correction (OCC PATCH),
cancellation, and attempt creation/listing under a request."""
from datetime import timedelta

from flask import Blueprint, request as flask_request

import errors
from db import store
from middleware import (
    as_int, as_str, auth, body, opt_enum, opt_int, opt_str, pagination_params,
    req_enum, req_int, req_str, require_role,
)
from response import ok, ok_list
from services import (
    AMENDMENT_SCOPES, COLLATERAL_CLASSES, COLLATERAL_OPS, OPEN_REQUEST_STATES,
    REFILE_WINDOW_DAYS, REQUEST_KIND_TO_FILING_KIND, REQUEST_KINDS,
    SEARCH_FRESHNESS_DAYS, SERVICE_LEVELS, append_event, cancel_request,
    compute_fee_cents, determine_filing_office, filing_json, profile_by_code,
    request_json, stamp_new, touch,
)
from util import new_id

bp = Blueprint("requests", __name__)


def _paginate(records, serializer):
    limit, offset = pagination_params()
    items = [serializer(r) for r in records]
    return ok_list(items[offset:offset + limit], len(items), limit, offset)


def _request_or_404(request_id):
    req = store.filing_requests.get(request_id)
    if req is None:
        raise errors.err_not_found("request")
    return req


# ---------------------------------------------------------------------------
# Filing request intake
# ---------------------------------------------------------------------------

@bp.post("/filing-requests")
def create_filing_request():
    auth()
    data = body()
    # --- Priority 2: structural validation -------------------------------
    client_id = req_str(data, "client_id")
    kind = req_enum(data, "kind", REQUEST_KINDS)
    debtor_id = req_str(data, "debtor_id")
    secured_party_id = req_str(data, "secured_party_id")
    jurisdiction_code = req_str(data, "jurisdiction_code")
    collateral_class = req_enum(data, "collateral_class", COLLATERAL_CLASSES)
    fee_authorization_cents = req_int(data, "fee_authorization_cents")
    county_name = opt_str(data, "county_name")
    service_level = opt_enum(data, "service_level", SERVICE_LEVELS, default="STANDARD")
    additional_debtor_count = opt_int(data, "additional_debtor_count", default=0)
    if additional_debtor_count < 0:
        raise errors.err_invalid_request("additional_debtor_count must be >= 0")
    supporting_search_id = opt_str(data, "supporting_search_id")
    target_filing_id = opt_str(data, "target_filing_id")
    expected_target_version = None
    if kind != "NEW_UCC1":
        if not target_filing_id:
            raise errors.err_target_filing_required()
        if "expected_target_filing_version" not in data or data["expected_target_filing_version"] is None:
            raise errors.err_invalid_request(
                "expected_target_filing_version is required when kind is not NEW_UCC1")
        expected_target_version = as_int(
            data["expected_target_filing_version"], "expected_target_filing_version")
    # --- Priority 3: role -------------------------------------------------
    _user_id, role = auth()
    require_role(role, "FilingSpecialist")
    # --- Priority 6: body references --------------------------------------
    client = store.clients.get(client_id)
    if client is None:
        raise errors.err_not_found("client")
    if profile_by_code(jurisdiction_code) is None:
        raise errors.err_not_found("jurisdiction")
    debtor = store.debtors.get(debtor_id)
    if debtor is None or debtor["client_id"] != client_id:
        raise errors.err_not_found("debtor")
    sp = store.secured_parties.get(secured_party_id)
    if sp is None or sp["client_id"] != client_id:
        raise errors.err_not_found("secured_party")
    target = None
    if kind != "NEW_UCC1":
        target = store.filings.get(target_filing_id)
        if target is None:
            raise errors.err_not_found("filing")
        if target["filing_kind"] != "INITIAL":
            raise errors.err_invalid_request(
                "target_filing_id must reference an INITIAL filing")
    if supporting_search_id is not None and supporting_search_id not in store.lien_searches:
        raise errors.err_not_found("search")
    # --- Priority 7: OCC on the target root -------------------------------
    if target is not None and expected_target_version != target["version"]:
        raise errors.err_stale_version()
    # --- Priority 10: at most one open AMENDMENT/CONTINUATION per root -----
    if kind in ("AMENDMENT", "CONTINUATION"):
        for r in store.filing_requests.values():
            if (
                r["target_filing_id"] == target_filing_id
                and r["kind"] in ("AMENDMENT", "CONTINUATION")
                and r["status"] in OPEN_REQUEST_STATES
            ):
                raise errors.err_ucc3_in_flight()
    req = stamp_new({
        "id": new_id(),
        "client_id": client_id,
        "kind": kind,
        "debtor_id": debtor_id,
        "secured_party_id": secured_party_id,
        "jurisdiction_code": jurisdiction_code,
        "collateral_class": collateral_class,
        "county_name": county_name,
        "service_level": service_level,
        "additional_debtor_count": additional_debtor_count,
        "fee_authorization_cents": fee_authorization_cents,
        "target_filing_id": target_filing_id if kind != "NEW_UCC1" else None,
        "supporting_search_id": supporting_search_id,
        "filing_office": None,
        "quoted_fee_cents": None,
        "intake_submitted_by_user_id": None,
        "status": "DRAFT_INTAKE",
        "cancel_reason": None,
    })
    store.filing_requests[req["id"]] = req
    if target is not None:
        target["open_ucc3_request_count"] += 1
        touch(target)
    return ok(request_json(req), 201)


@bp.get("/filing-requests")
def list_filing_requests():
    auth()
    records = list(store.filing_requests.values())
    args = flask_request.args
    for param in ("client_id", "debtor_id", "secured_party_id",
                  "target_filing_id", "supporting_search_id", "status", "kind"):
        value = args.get(param)
        if value is not None:
            records = [r for r in records if r.get(param) == value]
    return _paginate(records, request_json)


@bp.get("/filing-requests/<request_id>")
def get_filing_request(request_id):
    auth()
    return ok(request_json(_request_or_404(request_id)))


@bp.patch("/filing-requests/<request_id>")
def patch_filing_request(request_id):
    auth()
    data = body()
    # --- Priority 2: structural -------------------------------------------
    if "expected_request_version" not in data or data["expected_request_version"] is None:
        raise errors.err_invalid_request("expected_request_version is required")
    expected_version = as_int(data["expected_request_version"], "expected_request_version")
    updates = {}
    if "collateral_class" in data and data["collateral_class"] is not None:
        updates["collateral_class"] = req_enum(data, "collateral_class", COLLATERAL_CLASSES)
    if "county_name" in data:
        v = data["county_name"]
        updates["county_name"] = None if v is None else as_str(v, "county_name")
    if "service_level" in data and data["service_level"] is not None:
        updates["service_level"] = req_enum(data, "service_level", SERVICE_LEVELS)
    if "additional_debtor_count" in data and data["additional_debtor_count"] is not None:
        v = as_int(data["additional_debtor_count"], "additional_debtor_count")
        if v < 0:
            raise errors.err_invalid_request("additional_debtor_count must be >= 0")
        updates["additional_debtor_count"] = v
    if "fee_authorization_cents" in data and data["fee_authorization_cents"] is not None:
        updates["fee_authorization_cents"] = as_int(
            data["fee_authorization_cents"], "fee_authorization_cents")
    if "supporting_search_id" in data:
        v = data["supporting_search_id"]
        updates["supporting_search_id"] = None if v is None else as_str(v, "supporting_search_id")
    # --- Priority 3: role ---------------------------------------------------
    _user_id, role = auth()
    require_role(role, "FilingSpecialist")
    # --- Priority 5: path existence -----------------------------------------
    req = _request_or_404(request_id)
    # --- Priority 6: body references ----------------------------------------
    new_search = updates.get("supporting_search_id")
    if "supporting_search_id" in updates and new_search is not None \
            and new_search not in store.lien_searches:
        raise errors.err_not_found("search")
    # --- Priority 7: state + OCC --------------------------------------------
    if req["status"] not in ("DRAFT_INTAKE", "IN_REVIEW", "CORRECTION_REQUIRED"):
        raise errors.err_request_invalid_state(
            "Preparation fields may only be corrected from DRAFT_INTAKE, IN_REVIEW or CORRECTION_REQUIRED")
    if expected_version != req["version"]:
        raise errors.err_stale_version()
    # --- Priority 8: county consistency on office recompute -----------------
    changed_class = "collateral_class" in updates and updates["collateral_class"] != req["collateral_class"]
    changed_county = "county_name" in updates and updates["county_name"] != req["county_name"]
    if req["status"] == "IN_REVIEW" and (changed_class or changed_county):
        profile = profile_by_code(req["jurisdiction_code"])
        effective_class = updates.get("collateral_class", req["collateral_class"])
        effective_county = updates.get("county_name", req["county_name"])
        updates["filing_office"] = determine_filing_office(profile, effective_class, effective_county)
    for k, v in updates.items():
        req[k] = v
    touch(req)
    return ok(request_json(req))


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------

@bp.post("/filing-requests/<request_id>/submit-intake")
def submit_intake(request_id):
    auth()
    body()
    _user_id, role = auth()
    require_role(role, "FilingSpecialist", "FilingReviewer")
    req = _request_or_404(request_id)
    # Priority 7: client ACTIVE, then request from-state, then target ACTIVE.
    client = store.clients.get(req["client_id"])
    if client is not None and client["status"] != "ACTIVE":
        raise errors.err_client_suspended()
    if req["status"] != "DRAFT_INTAKE":
        raise errors.err_request_invalid_state("submit-intake requires DRAFT_INTAKE")
    if req["kind"] != "NEW_UCC1":
        target = store.filings.get(req["target_filing_id"])
        if target is None or target["effectiveness_status"] != "ACTIVE":
            raise errors.err_target_not_active()
    # Priority 8: filing-office determination with county consistency.
    profile = profile_by_code(req["jurisdiction_code"])
    office = determine_filing_office(profile, req["collateral_class"], req["county_name"])
    req["filing_office"] = office
    req["intake_submitted_by_user_id"] = flask_request.headers.get("X-User-ID")
    req["status"] = "IN_REVIEW"
    touch(req)
    return ok(request_json(req))


@bp.post("/filing-requests/<request_id>/approve-preparation")
def approve_preparation(request_id):
    user_id, role = auth()
    body()
    require_role(role, "FilingReviewer")
    req = _request_or_404(request_id)
    # Priority 7: from-state.
    if req["status"] not in ("IN_REVIEW", "CORRECTION_REQUIRED"):
        raise errors.err_request_invalid_state(
            "approve-preparation requires IN_REVIEW or CORRECTION_REQUIRED")
    # Priority 8: segregation of duties.
    if user_id == req["intake_submitted_by_user_id"]:
        raise errors.err_segregation()
    # Priority 9: supporting-search freshness.
    if req["supporting_search_id"]:
        search = store.lien_searches.get(req["supporting_search_id"])
        if (
            search is None
            or search["status"] != "COMPLETED"
            or search["through_date"] is None
            or search["through_date"] + timedelta(days=SEARCH_FRESHNESS_DAYS) < store.clock
        ):
            raise errors.err_search_stale()
    profile = profile_by_code(req["jurisdiction_code"])
    req["quoted_fee_cents"] = compute_fee_cents(profile, req)
    req["status"] = "READY"
    touch(req)
    return ok(request_json(req))


@bp.post("/filing-requests/<request_id>/cancel")
def cancel_filing_request(request_id):
    auth()
    body()
    _user_id, role = auth()
    require_role(role, "FilingSpecialist")
    req = _request_or_404(request_id)
    if req["status"] == "IN_PROCESS":
        raise errors.err_request_in_process()
    if req["status"] not in ("DRAFT_INTAKE", "IN_REVIEW", "READY", "CORRECTION_REQUIRED"):
        raise errors.err_request_invalid_state(
            "Only pre-processing requests may be cancelled")
    cancel_request(req, "CLIENT_REQUEST")
    return ok(request_json(req))


# ---------------------------------------------------------------------------
# Attempts under a request
# ---------------------------------------------------------------------------

@bp.post("/filing-requests/<request_id>/attempts")
def create_attempt(request_id):
    auth()
    data = body()
    # --- Priority 2: unconditional structural ------------------------------
    debtor_name_on_filing = req_str(data, "debtor_name_on_filing")
    collateral_text = opt_str(data, "collateral_text")
    amendment_scope = opt_enum(data, "amendment_scope", AMENDMENT_SCOPES)
    collateral_change_op = opt_enum(data, "collateral_change_op", COLLATERAL_OPS)
    secured_amount_cents = opt_int(data, "secured_amount_cents", default=0)
    # --- Priority 2 (conditional): needs the parent request -----------------
    req = store.filing_requests.get(request_id)
    if req is not None:
        if req["kind"] == "NEW_UCC1" and collateral_text is None:
            raise errors.err_invalid_request(
                "collateral_text is required for an INITIAL filing attempt")
        if req["kind"] == "AMENDMENT":
            if amendment_scope is None:
                raise errors.err_invalid_request(
                    "amendment_scope is required for an AMENDMENT attempt")
            if amendment_scope == "COLLATERAL":
                if collateral_change_op is None:
                    raise errors.err_invalid_request(
                        "collateral_change_op is required for a COLLATERAL amendment")
                if collateral_text is None:
                    raise errors.err_invalid_request(
                        "collateral_text is required for a COLLATERAL amendment")
    # --- Priority 3: role ----------------------------------------------------
    _user_id, role = auth()
    require_role(role, "FilingSpecialist")
    # --- Priority 5: path existence ------------------------------------------
    if req is None:
        raise errors.err_not_found("request")
    # --- Priority 7: request must be READY -----------------------------------
    if req["status"] != "READY":
        raise errors.err_request_not_ready()
    # --- Priority 9: refile window -------------------------------------------
    latest_rejected = None
    for f in store.filings.values():
        if f["filing_request_id"] == request_id and f["effectiveness_status"] == "REJECTED":
            if latest_rejected is None or f["rejected_at"] >= latest_rejected["rejected_at"]:
                latest_rejected = f
    supersedes_attempt_id = None
    if latest_rejected is not None:
        if store.clock > latest_rejected["rejected_at"] + timedelta(days=REFILE_WINDOW_DAYS):
            raise errors.err_refile_window_expired()
        supersedes_attempt_id = latest_rejected["id"]
    # --- Priority 10: at most one non-terminal attempt per request -----------
    for f in store.filings.values():
        if f["filing_request_id"] == request_id and f["effectiveness_status"] in ("DRAFT", "SUBMITTED"):
            raise errors.err_attempt_in_flight()
    filing = stamp_new({
        "id": new_id(),
        "filing_request_id": request_id,
        "filing_kind": REQUEST_KIND_TO_FILING_KIND[req["kind"]],
        "root_filing_id": None if req["kind"] == "NEW_UCC1" else req["target_filing_id"],
        "supersedes_attempt_id": supersedes_attempt_id,
        "debtor_id": req["debtor_id"],
        "secured_party_id": req["secured_party_id"],
        "jurisdiction_code": req["jurisdiction_code"],
        "filing_office": req["filing_office"],
        "county_name": req["county_name"] if req["filing_office"] == "COUNTY" else None,
        "debtor_name_on_filing": debtor_name_on_filing,
        "collateral_text": collateral_text,
        "amendment_scope": amendment_scope if req["kind"] == "AMENDMENT" else None,
        "collateral_change_op": (
            collateral_change_op
            if req["kind"] == "AMENDMENT" and amendment_scope == "COLLATERAL"
            else None
        ),
        "secured_amount_cents": secured_amount_cents,
        "charged_fee_cents": None,
        "filing_number": None,
        "submitted_at": None,
        "filed_at": None,
        "rejected_at": None,
        "rejection_reason_code": None,
        "rejection_note": None,
        "expiration_at": None,
        "effectiveness_status": "DRAFT",
        "reflection_status": "UNVERIFIED",
        "open_ucc3_request_count": 0,
    })
    store.filings[filing["id"]] = filing
    append_event(filing, "CREATED", {"filing_request_id": request_id})
    return ok(filing_json(filing), 201)


@bp.get("/filing-requests/<request_id>/attempts")
def list_attempts(request_id):
    auth()
    _request_or_404(request_id)
    records = [f for f in store.filings.values() if f["filing_request_id"] == request_id]
    return _paginate(records, filing_json)
