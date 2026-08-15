from flask import Blueprint

import store as db
import logical_clock as clock
from auth import authorize
from envelope import obj
from logic import expire_proposal, NONTERMINAL_PROPOSAL_STATES
from validate import body, no_unknown, req_dt

bp = Blueprint("ops", __name__)


@bp.post("/advisory/compliance-checkpoints")
def compliance_checkpoint():
    authorize("ComplianceOfficer")
    import flask
    if flask.request.data:
        no_unknown(body(), set())
    now = clock.now()
    expired_ids = []
    for prop in sorted(db.proposals.values(),
                       key=lambda e: (e["created_dt"], e["_seq"])):
        if (prop["status"] in NONTERMINAL_PROPOSAL_STATES
                and prop["expires_at_dt"] <= now):
            expire_proposal(prop)
            expired_ids.append(prop["id"])
    return obj({
        "expired_proposal_count": len(expired_ids),
        "expired_proposal_ids": expired_ids,
    })


@bp.post("/advisory/_clock/set_current_utc")
def set_clock():
    authorize("PlatformAdmin")
    b = body()
    no_unknown(b, {"to_iso8601"})
    to = req_dt(b, "to_iso8601")
    clock.set_current(to)
    return obj({"current_utc": clock.fmt(clock.now())})
