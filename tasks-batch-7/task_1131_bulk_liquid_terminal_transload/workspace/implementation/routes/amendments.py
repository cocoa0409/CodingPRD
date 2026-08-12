"""LeaseAmendment endpoints: propose (CustomerRep + OCC), list, approve, reject."""
from flask import Blueprint

from clock import CLOCK
from db import STORE, new_id
from errors import err
from middleware import require_roles, current_user
from response import success_object, success_list
from serializers import amendment_view
from services.common import touch, get_lease_or_404
from validation import get_body, req_int, sort_and_page

bp = Blueprint("amendments", __name__)


def _validation(message):
    return err("ERR_VALIDATION", message)


@bp.post("/lease-agreements/<leaseId>/amendments")
def propose_amendment(leaseId):
    user_id, _ = require_roles("CustomerRep")
    body = get_body()

    # Priority 4 (schema): expected_lease_version is non-optional; at least one
    # proposed_* field required; proposed values must respect their bounds.
    expected_lease_version = req_int(body, "expected_lease_version")
    pcc = body.get("proposed_committed_capacity_bbl")
    ptf = body.get("proposed_throughput_fee_per_bbl")
    pmt = body.get("proposed_min_monthly_throughput_bbl")
    for name, v, bound in (
            ("proposed_committed_capacity_bbl", pcc, ("gt", 0)),
            ("proposed_throughput_fee_per_bbl", ptf, ("gt", 0)),
            ("proposed_min_monthly_throughput_bbl", pmt, ("ge", 0))):
        if v is not None:
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                raise _validation("Field '%s' must be a number" % name)
            op, limit = bound
            if op == "gt" and not v > limit:
                raise _validation("Field '%s' must be > 0" % name)
            if op == "ge" and not v >= limit:
                raise _validation("Field '%s' must be >= 0" % name)
    if pcc is None and ptf is None and pmt is None:
        raise _validation("An amendment proposal requires at least one proposed_* field")

    # Priority 3: ownership - the targeted lease's customer must be the caller.
    # (Lease existence itself is priority 5; an unknown lease yields 404.)
    lease_known = STORE.leases.get(leaseId)
    if lease_known is not None and lease_known["customer_id"] != user_id:
        raise err("ERR_FORBIDDEN_OWNERSHIP",
                  "CustomerRep may only amend leases of their own customer")

    lease = get_lease_or_404(leaseId)

    # OCC (1.2.1): stale expected version -> 412, proposal not persisted.
    if expected_lease_version != lease["version"]:
        raise err("ERR_STALE_VERSION",
                  "expected_lease_version %s does not match current version %s"
                  % (expected_lease_version, lease["version"]))

    # Priority 7: lease must be ACTIVE or SUSPENDED.
    if lease["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_LEASE_NOT_ACTIVE",
                  "Amendments may be proposed only while the lease is ACTIVE or SUSPENDED")

    now = CLOCK.now()
    amendment = {
        "id": new_id(),
        "lease_id": lease["id"],
        "proposed_committed_capacity_bbl": pcc,
        "proposed_throughput_fee_per_bbl": ptf,
        "proposed_min_monthly_throughput_bbl": pmt,
        "base_lease_version": expected_lease_version,
        "status": "PROPOSED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE.amendments[amendment["id"]] = amendment
    # The act of proposing increments the lease's version (PRD 3.3).
    touch(lease)
    return success_object(amendment_view(amendment), status=201)


@bp.get("/lease-agreements/<leaseId>/amendments")
def list_amendments(leaseId):
    current_user()
    get_lease_or_404(leaseId)
    rows = [a for a in STORE.amendments.values() if a["lease_id"] == leaseId]
    page, total, limit, offset = sort_and_page(rows)
    return success_list([amendment_view(a) for a in page], total, limit, offset)


def _get_amendment_or_404(amendment_id):
    amendment = STORE.amendments.get(amendment_id)
    if amendment is None:
        raise err("ERR_AMENDMENT_NOT_FOUND", "Amendment %s not found" % amendment_id)
    return amendment


@bp.post("/lease-amendments/<amendmentId>/approve")
def approve_amendment(amendmentId):
    require_roles("TerminalManager")
    amendment = _get_amendment_or_404(amendmentId)
    if amendment["status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE",
                  "Amendment %s is %s; approve requires PROPOSED"
                  % (amendmentId, amendment["status"]))
    lease = get_lease_or_404(amendment["lease_id"])
    if lease["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_LEASE_NOT_ACTIVE",
                  "Amendment approval requires the lease to be ACTIVE or SUSPENDED")
    # base_lease_version pins the lease version the client observed; the
    # proposal itself then incremented the version by 1 (PRD 3.3). Approval
    # therefore rejects when the lease has moved on SINCE the proposal, i.e.
    # any further version-incrementing mutation beyond the proposal's own.
    if lease["version"] != amendment["base_lease_version"] + 1:
        raise err("ERR_AMENDMENT_STALE_BASE",
                  "Amendment base_lease_version %s no longer matches lease version %s"
                  % (amendment["base_lease_version"], lease["version"]))
    # Apply each non-null proposed field onto the lease.
    if amendment["proposed_committed_capacity_bbl"] is not None:
        lease["committed_capacity_bbl"] = amendment["proposed_committed_capacity_bbl"]
    if amendment["proposed_throughput_fee_per_bbl"] is not None:
        lease["throughput_fee_per_bbl"] = amendment["proposed_throughput_fee_per_bbl"]
    if amendment["proposed_min_monthly_throughput_bbl"] is not None:
        lease["min_monthly_throughput_bbl"] = amendment["proposed_min_monthly_throughput_bbl"]
    touch(lease)
    amendment["status"] = "APPROVED"
    touch(amendment)
    return success_object(amendment_view(amendment))


@bp.post("/lease-amendments/<amendmentId>/reject")
def reject_amendment(amendmentId):
    require_roles("TerminalManager")
    amendment = _get_amendment_or_404(amendmentId)
    if amendment["status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE",
                  "Amendment %s is %s; reject requires PROPOSED"
                  % (amendmentId, amendment["status"]))
    amendment["status"] = "REJECTED"
    touch(amendment)
    return success_object(amendment_view(amendment))
