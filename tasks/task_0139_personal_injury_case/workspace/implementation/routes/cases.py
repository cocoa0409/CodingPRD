"""Case lifecycle endpoints: create, fetch, list, costs, toll, dismiss,
disbursement-approve. PRD §3.1 (intake), §3.2 (SoL), §3.9 (costs), §3.10
(disbursement)."""
from __future__ import annotations

from datetime import date, datetime, timezone

from flask import Blueprint, request

from config import (
    DISBURSEMENT_STRATEGIES,
    INCIDENT_TYPES,
    LIEN_TYPES_STATUTORY,
    ROLE_ATTORNEY,
    ROLE_MANAGING_PARTNER,
    ROLE_PARALEGAL,
)
from db import store
from errors import raise_error
from middleware import current_user_id, require_auth
from response import list_success, success
from routes._helpers import (
    get_json_body,
    get_pagination_args,
    paginate,
    require_field,
)
from services.calculations import (
    calc_attorney_fee,
    calc_net_disbursement,
    is_sol_expired,
    order_liens_for_disbursement,
    select_contingency_tier_bps,
)
from services.case_engine import (
    assert_case_not_closed,
    check_version_match,
    get_case_or_404,
    new_common_fields,
    now,
    recompute_sol_deadline,
    touch,
)
from services.serializers import case_to_dict, disbursement_to_dict
from utils import is_valid_state_code, new_uuid, parse_iso_date


bp = Blueprint("cases", __name__)

ALL_ROLES = [ROLE_PARALEGAL, ROLE_ATTORNEY, ROLE_MANAGING_PARTNER]


# ── POST /pi-cases ─────────────────────────────────────────────────────────


@bp.post("/pi-cases")
@require_auth(ALL_ROLES)
def open_case():
    body = get_json_body()

    client_id = require_field(body, "client_id")
    client_row = store.clients.get(client_id)
    if not client_row:
        raise_error("ERR_REFERENCE_NOT_FOUND", f"Client {client_id} not found.")

    incident_date_raw = require_field(body, "incident_date")
    incident_date = parse_iso_date(incident_date_raw)
    if incident_date is None:
        raise_error("ERR_VALIDATION", "incident_date must be ISO 8601 date.")
    today_utc = datetime.now(timezone.utc).date()
    if incident_date >= today_utc:
        raise_error("ERR_VALIDATION", "incident_date must be in the past.")
    dob = parse_iso_date(client_row["date_of_birth"])
    if dob is None or incident_date < dob:
        raise_error(
            "ERR_VALIDATION",
            "incident_date must be on or after client's date_of_birth.",
        )

    incident_type = require_field(body, "incident_type")
    if incident_type not in INCIDENT_TYPES:
        raise_error("ERR_VALIDATION", f"Invalid incident_type {incident_type}.")

    jurisdiction_state = require_field(body, "jurisdiction_state")
    if not is_valid_state_code(jurisdiction_state):
        raise_error("ERR_VALIDATION", "jurisdiction_state must be a two-letter uppercase state code.")

    assigned_attorney_id = body.get("assigned_attorney_id")
    assigned_paralegal_id = body.get("assigned_paralegal_id")
    if assigned_attorney_id is not None and not isinstance(assigned_attorney_id, str):
        raise_error("ERR_VALIDATION", "assigned_attorney_id must be a string.")
    if assigned_paralegal_id is not None and not isinstance(assigned_paralegal_id, str):
        raise_error("ERR_VALIDATION", "assigned_paralegal_id must be a string.")

    with store.lock:
        # Compute is_minor_at_incident on the client at the moment of case-open
        # (only set on the FIRST case for the client; subsequent cases leave
        # whatever value is already there unless still null).
        elapsed_years = incident_date.year - dob.year - (
            (incident_date.month, incident_date.day) < (dob.month, dob.day)
        )
        is_minor = elapsed_years < 18
        if client_row.get("is_minor_at_incident") is None:
            client_row["is_minor_at_incident"] = is_minor
            touch(client_row)

        case_row = {
            "id": new_uuid(),
            **new_common_fields(),
            "client_id": client_id,
            "incident_date": incident_date_raw,
            "incident_type": incident_type,
            "jurisdiction_state": jurisdiction_state,
            "status": "INTAKE",
            "sol_deadline": None,
            "sol_tolled_days": 0,
            "assigned_attorney_id": assigned_attorney_id,
            "assigned_paralegal_id": assigned_paralegal_id,
            "gross_settlement_cents": 0,
            "case_costs_cents": 0,
            "filed_in_court": False,
            "disbursement_approved_by": None,
        }
        recompute_sol_deadline(case_row, client_row)
        store.cases[case_row["id"]] = case_row

    return success(case_to_dict(case_row), 201)


# ── GET /pi-cases/{id} ─────────────────────────────────────────────────────


@bp.get("/pi-cases/<cid>")
@require_auth(ALL_ROLES)
def fetch_case(cid):
    row = get_case_or_404(cid)
    return success(case_to_dict(row), 200)


# ── GET /pi-cases ─────────────────────────────────────────────────────────


@bp.get("/pi-cases")
@require_auth(ALL_ROLES)
def list_cases():
    limit, offset = get_pagination_args()

    status_filter = request.args.get("status")
    jurisdiction = request.args.get("jurisdiction_state")
    client_id = request.args.get("client_id")

    rows = list(store.cases.values())
    if status_filter:
        rows = [r for r in rows if r["status"] == status_filter]
    if jurisdiction:
        rows = [r for r in rows if r["jurisdiction_state"] == jurisdiction]
    if client_id:
        rows = [r for r in rows if r["client_id"] == client_id]

    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return list_success([case_to_dict(r) for r in page], limit, offset, total)


# ── PATCH /pi-cases/{id}/costs ────────────────────────────────────────────


@bp.patch("/pi-cases/<cid>/costs")
@require_auth([ROLE_ATTORNEY, ROLE_MANAGING_PARTNER])
def patch_case_costs(cid):
    body = get_json_body()
    row = get_case_or_404(cid)
    assert_case_not_closed(row)

    if "case_costs_cents" not in body:
        raise_error("ERR_VALIDATION", "case_costs_cents is required.")
    new_value = body["case_costs_cents"]
    if not isinstance(new_value, int) or isinstance(new_value, bool) or new_value < 0:
        raise_error("ERR_VALIDATION", "case_costs_cents must be a non-negative integer.")

    check_version_match(row, body.get("version"))

    if new_value < int(row["case_costs_cents"]):
        raise_error(
            "ERR_COSTS_DECREASE_NOT_ALLOWED",
            "case_costs_cents cannot decrease.",
        )

    with store.lock:
        row["case_costs_cents"] = int(new_value)
        touch(row)

    return success(case_to_dict(row), 200)


# ── POST /pi-cases/{id}/toll ──────────────────────────────────────────────


@bp.post("/pi-cases/<cid>/toll")
@require_auth([ROLE_ATTORNEY, ROLE_MANAGING_PARTNER])
def toll_case(cid):
    body = get_json_body()
    row = get_case_or_404(cid)
    assert_case_not_closed(row)

    if "additional_days" not in body:
        raise_error("ERR_VALIDATION", "additional_days is required.")
    additional = body["additional_days"]
    if not isinstance(additional, int) or isinstance(additional, bool) or additional <= 0:
        raise_error("ERR_VALIDATION", "additional_days must be a positive integer.")

    reason = body.get("reason")
    if not isinstance(reason, str) or reason.strip() == "":
        raise_error("ERR_VALIDATION", "reason is required.")

    client_row = store.clients.get(row["client_id"])
    if not client_row:
        raise_error("ERR_NOT_FOUND", "Client not found for this case.")

    with store.lock:
        row["sol_tolled_days"] = int(row.get("sol_tolled_days", 0)) + int(additional)
        recompute_sol_deadline(row, client_row)
        touch(row)

    return success(case_to_dict(row), 200)


# ── POST /pi-cases/{id}/dismiss ───────────────────────────────────────────


@bp.post("/pi-cases/<cid>/dismiss")
@require_auth([ROLE_MANAGING_PARTNER])
def dismiss_case(cid):
    body = get_json_body()
    row = get_case_or_404(cid)

    reason = body.get("reason")
    if not isinstance(reason, str) or reason.strip() == "":
        raise_error("ERR_VALIDATION", "reason is required.")

    if row["status"] in ("DISMISSED", "CLOSED"):
        raise_error("ERR_CASE_CLOSED", "Case is already terminal.")

    # PRD §3.3: dismissal only valid in INTAKE / RECORDS_PENDING / READY_FOR_DEMAND
    # for pre-settlement dismissal cascade. Other non-terminal states are
    # allowed by the API (ManagingPartner remains able to terminate), but they
    # are not pre-settlement cases; per the scaffold transitions table, only
    # the three pre-demand-sent statuses cascade. We still accept the call.
    allowed_pre_demand = {"INTAKE", "RECORDS_PENDING", "READY_FOR_DEMAND"}
    if row["status"] not in allowed_pre_demand:
        raise_error(
            "ERR_INVALID_STATE",
            f"Case cannot be dismissed from {row['status']}.",
        )

    with store.lock:
        # Cascade: cancel all open medical-record requests.
        for r in store.medical_requests.values():
            if r["case_id"] == cid and r["status"] in ("DRAFT", "SENT"):
                r["status"] = "CANCELED"
                touch(r)

        row["status"] = "DISMISSED"
        touch(row)

    return success(case_to_dict(row), 200)


# ── POST /pi-cases/{id}/disbursement/approve ──────────────────────────────


@bp.post("/pi-cases/<cid>/disbursement/approve")
@require_auth([ROLE_MANAGING_PARTNER])
def approve_disbursement(cid):
    body = get_json_body()
    row = get_case_or_404(cid)

    if row["status"] in ("DISMISSED", "CLOSED") and row["status"] != "CLOSED":
        # CLOSED handled by ERR_DISBURSEMENT_ALREADY_APPROVED below; DISMISSED
        # blocks at ERR_CASE_CLOSED.
        raise_error("ERR_CASE_CLOSED", "Case is dismissed.")

    if row["status"] not in ("SETTLED", "TRIAL_AWARDED", "CLOSED"):
        raise_error(
            "ERR_CASE_INVALID_STATE",
            f"Disbursement only permitted on SETTLED or TRIAL_AWARDED; case is {row['status']}.",
        )

    strategy = body.get("strategy")
    if strategy not in DISBURSEMENT_STRATEGIES:
        raise_error(
            "ERR_VALIDATION",
            f"strategy must be one of {sorted(DISBURSEMENT_STRATEGIES)}.",
        )

    # Idempotency guard: case may not have been already approved.
    if row.get("disbursement_approved_by") is not None or row["status"] == "CLOSED":
        raise_error(
            "ERR_DISBURSEMENT_ALREADY_APPROVED",
            "Disbursement has already been approved on this case.",
        )

    # Segregation of duties: acting user != assigned_attorney_id.
    user_id = current_user_id()
    if row.get("assigned_attorney_id") and user_id == row["assigned_attorney_id"]:
        raise_error(
            "ERR_SEGREGATION_OF_DUTIES",
            "Approver cannot also be the assigned attorney on this case.",
        )

    # Pre-condition: lien states are acceptable.
    case_liens = [l for l in store.liens.values() if l["case_id"] == cid]
    for lien in case_liens:
        if lien["status"] == "NEGOTIATING":
            raise_error(
                "ERR_INVALID_STATE",
                "All liens must complete negotiation before disbursement.",
            )
        if lien["lien_type"] not in LIEN_TYPES_STATUTORY:
            # Non-statutory: must be REDUCED, RESOLVED, or DISPUTED.
            if lien["status"] not in ("REDUCED", "RESOLVED", "DISPUTED"):
                raise_error(
                    "ERR_INVALID_STATE",
                    f"Lien {lien['id']} ({lien['lien_type']}) must be REDUCED/RESOLVED/DISPUTED.",
                )

    # Fetch fee agreement.
    fee_id = store.fee_agreement_by_case.get(cid)
    if not fee_id:
        raise_error("ERR_INVALID_STATE", "Case has no contingency-fee agreement.")
    fee_row = store.fee_agreements[fee_id]

    rate_bps = select_contingency_tier_bps(row, fee_row)
    attorney_fee = calc_attorney_fee(row["gross_settlement_cents"], rate_bps)

    # Net-below-zero precheck.
    after_fee = int(row["gross_settlement_cents"]) - int(attorney_fee)
    after_costs = after_fee - int(row["case_costs_cents"])
    if after_costs < 0:
        raise_error(
            "ERR_NET_BELOW_ZERO",
            "Net after attorney_fee and case_costs is negative.",
        )

    with store.lock:
        # Re-check approval idempotency under the lock for concurrency.
        if row.get("disbursement_approved_by") is not None or row["status"] == "CLOSED":
            raise_error(
                "ERR_DISBURSEMENT_ALREADY_APPROVED",
                "Disbursement has already been approved on this case.",
            )

        ordered = order_liens_for_disbursement(cid, store.liens)
        result = calc_net_disbursement(
            row, ordered, strategy, attorney_fee,
        )

        # Touch every lien row that the waterfall mutated.
        for lien in ordered:
            if lien["status"] == "DISPUTED":
                touch(lien)
                continue
            # All non-disputed liens become RESOLVED at the end of the
            # cascade. Statutory ASSERTED liens were already flipped to
            # REDUCED during the waterfall; here we advance every paid lien
            # to RESOLVED (terminal).
            lien["status"] = "RESOLVED"
            touch(lien)

        if result["client_net_cents"] < 0:
            raise_error("ERR_NET_BELOW_ZERO", "client_net_cents is negative.")

        # Atomicity check: gross - fee - costs - liens == net.
        checksum = (
            int(row["gross_settlement_cents"])
            - int(result["attorney_fee_cents"])
            - int(result["case_costs_cents"])
            - int(result["total_lien_payment_cents"])
        )
        if checksum != int(result["client_net_cents"]):
            raise_error(
                "ERR_NET_BELOW_ZERO",
                "Disbursement checksum does not match (cents drift).",
            )

        disbursement = {
            "id": new_uuid(),
            "created_at": now(),
            "case_id": cid,
            "gross_amount_cents": int(row["gross_settlement_cents"]),
            "attorney_fee_cents": int(result["attorney_fee_cents"]),
            "case_costs_cents": int(result["case_costs_cents"]),
            "total_lien_payment_cents": int(result["total_lien_payment_cents"]),
            "client_net_cents": int(result["client_net_cents"]),
            "strategy": strategy,
            "approved_by": user_id,
        }
        store.disbursements[disbursement["id"]] = disbursement
        store.disbursement_by_case[cid] = disbursement["id"]

        row["disbursement_approved_by"] = user_id
        row["status"] = "CLOSED"
        touch(row)

    return success(disbursement_to_dict(disbursement), 201)
