"""Premium committees, premium funds and the append-only premium ledger."""
from decimal import Decimal

from flask import Blueprint

import common as C
import store as S
import validators as V
from common import new_id, pct
from errors import ApiError
from response import created, listing, ok
from store import ordered

bp = Blueprint("committees", __name__)


@bp.post("/premium-committees")
def constitute_committee():
    from auth import authorize
    authorize("CertificationOfficer")
    data = V.body()
    holder_id = V.req_id(data, "holder_id")
    chair_user_id = V.req_str(data, "chair_user_id", 200)
    member_count = V.req_int(data, "member_count", minimum=3)
    approved_use_categories = V.req_enum_array(data, "approved_use_categories",
                                               C.USE_CATEGORIES)
    quorum_pct = V.opt_number(data, "quorum_pct", 2, default=pct("60.00"),
                              exclusive_min="0.00", maximum="100.00")

    holder = S.holder_or_404(holder_id)
    if holder["holder_type"] != "PRODUCER_ORG":
        raise ApiError("ERR_COMMITTEE_ALREADY_EXISTS",
                       "only a PRODUCER_ORG holder may hold a premium committee")
    if S.live_committee_of(holder_id) is not None:
        raise ApiError("ERR_COMMITTEE_ALREADY_EXISTS",
                       "this holder already holds an undissolved committee")

    committee = {
        "id": new_id(),
        "holder_id": holder_id,
        "chair_user_id": chair_user_id,
        "member_count": member_count,
        "quorum_pct": quorum_pct,
        "approved_use_categories": approved_use_categories,
        "status": "FORMING",
        "open_proposal_count": 0,
    }
    S.stamp_new(committee)
    S.committees[committee["id"]] = committee
    return created(committee)


@bp.get("/premium-committees/<committee_id>")
def read_committee(committee_id):
    from auth import authorize
    authorize("CertificationOfficer", "Auditor", "CommitteeChair",
              "CommitteeMember", "ProducerRepresentative")
    return ok(S.committee_or_404(committee_id))


@bp.get("/certificate-holders/<holder_id>/premium-committees")
def list_holder_committees(holder_id):
    from auth import authorize
    authorize("CertificationOfficer", "Auditor", "CommitteeChair",
              "CommitteeMember", "ProducerRepresentative")
    status = V.enum_filter("status", C.COMMITTEE_STATUSES)
    S.holder_or_404(holder_id)
    rows = ordered([c for c in S.committees.values() if c["holder_id"] == holder_id])
    if status:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = V.paginate(rows)
    return listing(page, limit, offset, total)


@bp.get("/certificate-holders/<holder_id>/premium-funds")
def list_holder_funds(holder_id):
    from auth import authorize
    authorize("CertificationOfficer", "Auditor", "CommitteeChair",
              "CommitteeMember", "ProducerRepresentative")
    fiscal_year = V.int_filter("fiscal_year")
    S.holder_or_404(holder_id)
    rows = ordered([f for f in S.funds.values() if f["holder_id"] == holder_id])
    if fiscal_year is not None:
        rows = [r for r in rows if r["fiscal_year"] == fiscal_year]
    page, limit, offset, total = V.paginate(rows)
    return listing(page, limit, offset, total)


@bp.get("/premium-ledger-entries/<entry_id>")
def read_entry(entry_id):
    from auth import authorize
    authorize("CertificationOfficer", "Auditor", "CommitteeChair",
              "CommitteeMember", "ProducerRepresentative")
    return ok(S.entry_or_404(entry_id))


@bp.get("/premium-ledger-entries")
def list_entries():
    from auth import authorize
    authorize("CertificationOfficer", "Auditor", "CommitteeChair",
              "CommitteeMember", "ProducerRepresentative")
    fund_id = V.str_filter("fund_id")
    trade_transaction_id = V.str_filter("trade_transaction_id")
    proposal_id = V.str_filter("proposal_id")
    entry_type = V.enum_filter("entry_type", C.ENTRY_TYPES)

    rows = ordered(list(S.entries.values()))
    if fund_id:
        rows = [r for r in rows if r["fund_id"] == fund_id]
    if trade_transaction_id:
        rows = [r for r in rows if r["trade_transaction_id"] == trade_transaction_id]
    if proposal_id:
        rows = [r for r in rows if r["proposal_id"] == proposal_id]
    if entry_type:
        rows = [r for r in rows if r["entry_type"] == entry_type]
    page, limit, offset, total = V.paginate(rows)
    return listing(page, limit, offset, total)
