"""Claims reported under an assigned-risk policy and the plan handling standard."""

from flask import Blueprint, request

import calc
import domain
import guards
from envelope import created, ok, ok_list
from errors import fail
from store import db, days, new_row, touch

bp = Blueprint("claims", __name__)

READ_ROLES = (
    "PlanAdministrator",
    "ComplianceExaminer",
    "ServicingCarrier",
    "ProducerAgent",
)


@bp.post("/plan/claims")
def report_claim():
    user_id, role = guards.authenticate(("ServicingCarrier",))
    data = guards.body()
    policy_id = guards.req_str(data, "policy_id")
    loss_date = guards.req_dt(data, "loss_date")
    at_fault = guards.req_bool(data, "at_fault")
    coverage_line = guards.req_enum(data, "coverage_line", ("BI", "PD", "UM"))
    reserve_cents = guards.req_int(data, "reserve_cents", minimum=0)

    policy = guards.need_policy(policy_id)
    guards.carrier_scope(role, user_id, policy["carrier_id"])

    if loss_date < policy["effective_date"] or loss_date > db.clock:
        fail("ERR_LOSS_DATE_OUTSIDE_TERM")

    row = new_row()
    row.update(
        {
            "policy_id": policy["id"],
            "loss_date": loss_date,
            "at_fault": at_fault,
            "coverage_line": coverage_line,
            "reserve_cents": reserve_cents,
            "reported_at": db.clock,
            "acknowledgement_deadline": db.clock + days(calc.CLAIM_ACK_WINDOW_DAYS),
            "acknowledged_at": None,
            "status": "OPEN",
            "standard_breach": False,
            "paid_cents": 0,
        }
    )
    db.claims[row["id"]] = row
    return created(domain.claim_out(row))


@bp.get("/plan/policies/<policy_id>/claims")
def list_policy_claims(policy_id):
    guards.authenticate(READ_ROLES)
    limit, offset = guards.pagination()
    policy = guards.need_policy(policy_id)
    status = request.args.get("status")

    rows = [c for c in db.claims.values() if c["policy_id"] == policy["id"]]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    rows = domain.sort_default(rows)
    page, total = domain.paginate(rows, limit, offset)
    return ok_list([domain.claim_out(r) for r in page], limit, offset, total)


@bp.get("/plan/claims/<claim_id>")
def read_claim(claim_id):
    guards.authenticate(READ_ROLES)
    claim = guards.need_claim(claim_id)
    return ok(domain.claim_out(claim))


@bp.post("/plan/claims/<claim_id>/acknowledgement")
def acknowledge_claim(claim_id):
    user_id, role = guards.authenticate(("ServicingCarrier",))
    guards.body()
    claim = guards.need_claim(claim_id)
    policy = db.policies[claim["policy_id"]]
    guards.carrier_scope(role, user_id, policy["carrier_id"])

    if claim["status"] != "OPEN":
        fail("ERR_INVALID_CLAIM_STATE")

    claim["status"] = "ACKNOWLEDGED"
    claim["acknowledged_at"] = db.clock
    late = db.clock > claim["acknowledgement_deadline"]
    if late:
        claim["standard_breach"] = True
    touch(claim)

    if late:
        carrier = db.carriers[policy["carrier_id"]]
        carrier["breach_count_current_period"] += 1
        domain.adjust_score(carrier, -calc.ACK_BREACH_DEDUCTION)
        domain.apply_suspension_cascade(carrier)
    return ok(domain.claim_out(claim))


@bp.post("/plan/claims/<claim_id>/closure")
def close_claim(claim_id):
    user_id, role = guards.authenticate(("ServicingCarrier",))
    data = guards.body()
    disposition = guards.req_enum(data, "disposition", ("PAID", "DENIED"))
    paid_cents = guards.opt_int(data, "paid_cents", default=0, minimum=0)
    denial_reason = guards.opt_str(data, "denial_reason", max_len=500)
    if disposition == "DENIED" and denial_reason is None:
        guards.invalid("Field denial_reason is required on a DENIED closure.")

    claim = guards.need_claim(claim_id)
    policy = db.policies[claim["policy_id"]]
    guards.carrier_scope(role, user_id, policy["carrier_id"])

    if claim["status"] != "ACKNOWLEDGED":
        fail("ERR_INVALID_CLAIM_STATE")

    if disposition == "PAID":
        if paid_cents > claim["reserve_cents"]:
            fail("ERR_PAYMENT_EXCEEDS_RESERVE")
        claim["status"] = "CLOSED_PAID"
        claim["paid_cents"] = paid_cents
    else:
        claim["status"] = "CLOSED_DENIED"
        claim["paid_cents"] = 0
    touch(claim)

    if claim["at_fault"]:
        # The applicant's clean-years clock restarts at this loss.
        application = domain.policy_application(policy)
        touch(db.applicants[application["applicant_id"]])
    return ok(domain.claim_out(claim))
