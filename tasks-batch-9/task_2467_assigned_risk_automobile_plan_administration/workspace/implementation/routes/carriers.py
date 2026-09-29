"""Carrier enrolment, listing, exit notice and licensing amendment."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import domain
import guards
from envelope import created, ok, ok_list
from errors import fail
from store import db, days, new_row, touch

bp = Blueprint("carriers", __name__)

ALL_ROLES = (
    "PlanAdministrator",
    "ComplianceExaminer",
    "ServicingCarrier",
    "ProducerAgent",
)


@bp.post("/plan/carriers")
def create_carrier():
    guards.authenticate(("PlanAdministrator",))
    data = guards.body()
    name = guards.req_str(data, "name", min_len=1, max_len=120)
    naic_code = guards.req_str(data, "naic_code", exact_len=5, pattern=r"^\d{5}$")
    bps = guards.req_int(data, "voluntary_market_share_bps", minimum=1, maximum=10000)
    territories = guards.req_territories(data, "licensed_territories")

    for existing in db.carriers.values():
        if existing["naic_code"] == naic_code:
            fail("ERR_DUPLICATE_IDENTIFIER", "naic_code is already enrolled.")

    row = new_row()
    row.update(
        {
            "name": name,
            "naic_code": naic_code,
            "voluntary_market_share_bps": bps,
            "licensed_territories": territories,
            "enrollment_sequence": db.next_enrollment_sequence(),
            "status": "ACTIVE",
            "exit_effective_date": None,
            "performance_score": calc.SCORE_START,
            "breach_count_current_period": 0,
            "non_renewal_count_current_period": 0,
            "voluntary_credit_units": Decimal("0.0"),
        }
    )
    db.carriers[row["id"]] = row
    # The apportionment denominator just grew: every ACTIVE carrier's
    # quota_target_units is re-derived on read.
    return created(domain.carrier_out(row))


@bp.get("/plan/carriers")
def list_carriers():
    guards.authenticate(ALL_ROLES)
    limit, offset = guards.pagination()
    status = request.args.get("status")
    posture = request.args.get("posture")
    territory_code = request.args.get("territory_code")

    rows = list(db.carriers.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if territory_code is not None:
        rows = [r for r in rows if territory_code in r["licensed_territories"]]
    targets = domain.quota_targets()
    if posture is not None:
        rows = [r for r in rows if domain.carrier_posture(r, targets) == posture]

    rows = domain.sort_carriers(rows)
    page, total = domain.paginate(rows, limit, offset)
    return ok_list([domain.carrier_out(r) for r in page], limit, offset, total)


@bp.get("/plan/carriers/<carrier_id>")
def read_carrier(carrier_id):
    guards.authenticate(ALL_ROLES)
    carrier = guards.need_carrier(carrier_id)
    return ok(domain.carrier_out(carrier))


@bp.post("/plan/carriers/<carrier_id>/exit-notice")
def exit_notice(carrier_id):
    guards.authenticate(("PlanAdministrator",))
    data = guards.body()
    exit_effective_date = guards.req_dt(data, "exit_effective_date")
    carrier = guards.need_carrier(carrier_id)

    if carrier["status"] != "ACTIVE":
        fail("ERR_CARRIER_NOT_ACTIVE")
    if exit_effective_date < db.clock + days(calc.EXIT_NOTICE_LEAD_DAYS):
        fail("ERR_EXIT_NOTICE_TOO_SHORT")

    carrier["status"] = "EXIT_NOTICED"
    carrier["exit_effective_date"] = exit_effective_date
    touch(carrier)

    # Reassign the live book, oldest policy first, batch_sequence 1..n.
    policies = [
        p
        for p in db.policies.values()
        if p["carrier_id"] == carrier["id"] and p["policy_status"] == "IN_FORCE"
    ]
    policies.sort(key=lambda p: (p["created_at"], p["_seq"]))
    batch_sequence = 0
    for policy in policies:
        policy["policy_status"] = "REASSIGNMENT_PENDING"
        policy["reassignment_required"] = True
        touch(policy)
        application = domain.policy_application(policy)
        vehicle = db.vehicles[application["vehicle_id"]]
        receiver, deficit = domain.select_carrier(
            vehicle["garaging_territory_code"], excluded_carrier_id=carrier["id"]
        )
        if receiver is None:
            # An empty market is a fact to be recorded, not a request failure.
            continue
        batch_sequence += 1
        domain.create_assignment(
            application,
            receiver,
            deficit,
            batch_sequence,
            "REASSIGNMENT",
            assignment_cycle_id=None,
            predecessor_assignment_id=policy["_current_assignment_id"],
        )

    domain.rescind_pending_assignments(carrier, "CARRIER_INELIGIBLE")
    return ok(domain.carrier_out(carrier))


@bp.post("/plan/carriers/<carrier_id>/licensing-amendment")
def licensing_amendment(carrier_id):
    guards.authenticate(("PlanAdministrator",))
    data = guards.body()
    territories = guards.req_territories(data, "licensed_territories")
    carrier = guards.need_carrier(carrier_id)

    if carrier["status"] != "ACTIVE":
        fail("ERR_CARRIER_NOT_ACTIVE")

    # The book already placed with the carrier is deliberately left alone.
    carrier["licensed_territories"] = territories
    touch(carrier)
    return ok(domain.carrier_out(carrier))
