"""Rate-increase filing endpoints (PRD §3.11)."""
from flask import Blueprint, request

import errors
from db import STORE, new_id, common_fields, touch
from middleware import authenticate, authorize
from response import object_response, array_response
from services import common, serialize, lookup, core

bp = Blueprint("rate_filings", __name__)


@bp.route("/rate-filings", methods=["POST"])
def file_rate_increase():
    caller = authenticate()
    authorize(caller, ["Underwriter"])
    body = common.get_json_body()
    policy_id = common.require_str(body, "policy_id")
    requested = common.require_int(body, "requested_increase_pct")
    effective = common.require_int(body, "effective_period_index")
    lookup.policy_or_404(policy_id)

    # No new filing while another FILED filing exists for the policy.
    for f in STORE.rate_filings.values():
        if f["policy_id"] == policy_id and f["status"] == "FILED":
            raise errors.err(errors.ERR_RATE_FILING_PENDING, "A filing is already pending")

    fid = new_id()
    rec = {
        "id": fid,
        "policy_id": policy_id,
        "requested_increase_pct": requested,
        "approved_increase_pct": 0,
        "effective_period_index": effective,
        "status": "FILED",
    }
    rec.update(common_fields(STORE.next_seq()))
    STORE.rate_filings[fid] = rec
    return object_response(serialize.rate_filing(rec), 201)


@bp.route("/rate-filings", methods=["GET"])
def list_rate_filings():
    caller = authenticate()
    authorize(caller, ["Underwriter", "Regulator"])
    records = list(STORE.rate_filings.values())
    policy_id = request.args.get("policy_id")
    if policy_id is not None:
        records = [r for r in records if r["policy_id"] == policy_id]
    records = lookup.sorted_by_created(records)
    page, limit, offset, total = common.paginate(records)
    return array_response([serialize.rate_filing(r) for r in page], limit, offset, total)


@bp.route("/rate-filings/<rid>", methods=["GET"])
def get_rate_filing(rid):
    caller = authenticate()
    authorize(caller, ["Underwriter", "Regulator"])
    rec = lookup.rate_filing_or_404(rid)
    return object_response(serialize.rate_filing(rec), 200)


@bp.route("/rate-filings/<rid>/adjudicate", methods=["POST"])
def adjudicate(rid):
    caller = authenticate()
    authorize(caller, ["Regulator"])
    filing = lookup.rate_filing_or_404(rid)
    body = common.get_json_body()
    granted = common.require_int(body, "granted_pct")
    expected_version = common.require_int(body, "expected_policy_version")

    # State precedes business rules.
    if filing["status"] != "FILED":
        raise errors.err(errors.ERR_INVALID_STATE, "Filing not in FILED state")

    requested = filing["requested_increase_pct"]
    if granted < 0 or granted > requested:
        raise errors.err(errors.ERR_INVALID_REQUEST, "granted_pct out of range")

    pol = STORE.policies[filing["policy_id"]]

    if granted == 0:
        # REJECTED: no OCC check, no version bump, no recompute.
        filing["status"] = "REJECTED"
        filing["approved_increase_pct"] = 0
        touch(filing)
        return object_response(serialize.rate_filing(filing), 200)

    # APPROVED or PARTIALLY_APPROVED both require OCC and bump version.
    if expected_version != pol["version"]:
        raise errors.err(errors.ERR_STALE_VERSION, "Stale policy version")

    if granted == requested:
        filing["status"] = "APPROVED"
    else:
        filing["status"] = "PARTIALLY_APPROVED"
    filing["approved_increase_pct"] = granted
    touch(filing)

    core.reprice_open_invoices(filing["policy_id"], filing["effective_period_index"])
    touch(pol)
    return object_response(serialize.rate_filing(filing), 200)


@bp.route("/rate-filings/<rid>/withdraw", methods=["POST"])
def withdraw(rid):
    caller = authenticate()
    authorize(caller, ["Underwriter"])
    filing = lookup.rate_filing_or_404(rid)
    if filing["status"] != "FILED":
        raise errors.err(errors.ERR_INVALID_STATE, "Filing not in FILED state")
    filing["status"] = "WITHDRAWN"
    touch(filing)
    return object_response(serialize.rate_filing(filing), 200)
