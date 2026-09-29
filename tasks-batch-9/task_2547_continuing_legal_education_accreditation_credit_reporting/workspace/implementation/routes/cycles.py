"""Compliance cycles: reads, the summary, affirmations and certification
(PRD 3.4, 3.5, 3.6, 3.8)."""
from flask import Blueprint

import calc
import constants as C
import db
import listing
import middleware
import response
import util
from errors import fail
from routes.attorneys import CARRYOVER_ELECTIONS, load_cycle
from services import cascades

bp = Blueprint("cycles", __name__)

AFFIRMATION_TYPES = [
    "ATTENDANCE_AFFIRMATION",
    "SELF_STUDY_AFFIRMATION",
    "FINAL_COMPLIANCE_AFFIRMATION",
]


def require_cycle_owner(role, user_id, cycle):
    if role == C.ROLE_ATTORNEY and cycle.get("attorney_id") != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "That compliance cycle belongs to another attorney.")


@bp.route("/cle/compliance-cycles/<cycle_id>", methods=["GET"])
def read_cycle(cycle_id):
    middleware.require_roles([C.ROLE_BOARD_ADMIN, C.ROLE_REVIEWER, C.ROLE_ATTORNEY])
    return response.success(db.serialize(load_cycle(cycle_id)), 200)


@bp.route("/cle/compliance-cycles", methods=["GET"])
def list_cycles():
    middleware.require_roles([C.ROLE_BOARD_ADMIN, C.ROLE_REVIEWER, C.ROLE_ATTORNEY])
    rows = listing.apply_filters(
        db.all_rows("compliance_cycles"),
        ["attorney_id", "previous_cycle_id", "comity_claim_id", "credit_status", "administrative_status"],
    )
    return listing.page(listing.sort_by(rows, "period_start"))


@bp.route("/cle/compliance-cycles/<cycle_id>/summary", methods=["GET"])
def cycle_summary(cycle_id):
    user_id, role = middleware.require_roles([C.ROLE_BOARD_ADMIN, C.ROLE_REVIEWER, C.ROLE_ATTORNEY])
    cycle = load_cycle(cycle_id)
    require_cycle_owner(role, user_id, cycle)

    provisional = calc.credit_application(cycle, "PROVISIONAL")
    final = calc.credit_application(cycle, "FINAL")
    out_general, out_ethics = calc.carryover_determination(cycle, final)

    effective_carry = cycle.get("carryover_in_general_minutes") or 0
    previous = db.get("compliance_cycles", cycle.get("previous_cycle_id"))
    if previous is not None and previous.get("credit_status") == "OPEN":
        effective_carry = 0
    fee_run = calc.credit_application(cycle, "FINAL", carryover_in_general_override=effective_carry)

    payload = {
        "cycle_id": cycle["id"],
        "credit_status": cycle.get("credit_status"),
        "administrative_status": cycle.get("administrative_status"),
        "required_total_minutes": cycle.get("required_total_minutes"),
        "required_ethics_minutes": cycle.get("required_ethics_minutes"),
        "required_technology_minutes": cycle.get("required_technology_minutes"),
        "required_bias_minutes": cycle.get("required_bias_minutes"),
        "provisional_total_minutes": provisional["earned_countable_minutes"],
        "provisional_ethics_minutes": provisional["earned_ethics_minutes"],
        "provisional_technology_minutes": provisional["earned_technology_minutes"],
        "provisional_bias_minutes": provisional["earned_bias_minutes"],
        "provisional_live_minutes": provisional["earned_live_minutes"],
        "provisional_deficiency_total_minutes": provisional["deficiency_total_minutes"],
        "provisional_deficiency_ethics_minutes": provisional["deficiency_ethics_minutes"],
        "projected_final_total_minutes": final["earned_countable_minutes"],
        "projected_final_ethics_minutes": final["earned_ethics_minutes"],
        "projected_final_technology_minutes": final["earned_technology_minutes"],
        "projected_final_bias_minutes": final["earned_bias_minutes"],
        "projected_final_live_minutes": final["earned_live_minutes"],
        "projected_final_deficiency_total_minutes": final["deficiency_total_minutes"],
        "projected_final_deficiency_ethics_minutes": final["deficiency_ethics_minutes"],
        "projected_final_deficiency_technology_minutes": final["deficiency_technology_minutes"],
        "projected_final_deficiency_bias_minutes": final["deficiency_bias_minutes"],
        "self_study_used_minutes": provisional["self_study_used_minutes"],
        "on_demand_used_minutes": provisional["on_demand_used_minutes"],
        "nonlive_used_minutes": provisional["nonlive_used_minutes"],
        "reciprocity_used_minutes": provisional["reciprocity_used_minutes"],
        "carryover_in_general_minutes": cycle.get("carryover_in_general_minutes"),
        "carryover_in_ethics_minutes": cycle.get("carryover_in_ethics_minutes"),
        "projected_carryover_out_general_minutes": out_general,
        "projected_carryover_out_ethics_minutes": out_ethics,
        "projected_late_fee_cents": calc.late_fee_from_result(fee_run),
        "records_counted": provisional["records_counted"],
        "records_excluded": provisional["records_excluded"],
    }
    return response.success(payload, 200)


@bp.route("/cle/compliance-cycles/<cycle_id>/affirmations", methods=["GET"])
def list_affirmations(cycle_id):
    middleware.require_roles([C.ROLE_BOARD_ADMIN, C.ROLE_REVIEWER, C.ROLE_ATTORNEY])
    cycle = load_cycle(cycle_id)
    rows = [a for a in db.all_rows("affirmations") if a.get("cycle_id") == cycle["id"]]
    return listing.page(listing.sort_created_asc(rows))


@bp.route("/cle/compliance-cycles/<cycle_id>/affirmations", methods=["POST"])
def file_affirmation(cycle_id):
    user_id, role = middleware.require_roles([C.ROLE_ATTORNEY])
    cycle = load_cycle(cycle_id)
    require_cycle_owner(role, user_id, cycle)

    body = middleware.body_json()
    affirmation_type = middleware.req_enum(body, "affirmation_type", AFFIRMATION_TYPES)
    statement = middleware.req_str(body, "statement", 1, 500)
    target_supplied = middleware.present(body, "target_credit_record_id")
    if affirmation_type == "ATTENDANCE_AFFIRMATION" and not target_supplied:
        fail("ERR_INVALID_REQUEST", "target_credit_record_id is required for an attendance affirmation.")
    if affirmation_type != "ATTENDANCE_AFFIRMATION" and target_supplied:
        fail("ERR_INVALID_REQUEST", "target_credit_record_id is only permitted on an attendance affirmation.")

    target = None
    if target_supplied:
        target = db.get("credit_records", body.get("target_credit_record_id"))
        if target is None:
            fail("ERR_CREDIT_RECORD_NOT_FOUND", "No credit record matches target_credit_record_id.")
        if (
            target.get("status") != "PENDING_VERIFICATION"
            or target.get("verification_method") != "AFFIRMATION"
        ):
            fail(
                "ERR_INVALID_STATE_TRANSITION",
                "The targeted record must be PENDING_VERIFICATION under the AFFIRMATION method.",
            )

    if cycle.get("administrative_status") == "ADMIN_SUSPENDED":
        fail("ERR_CYCLE_ADMIN_SUSPENDED", "That cycle accepts no credit-bearing write.")

    if target is not None and target.get("cycle_id") != cycle["id"]:
        fail("ERR_CYCLE_ATTORNEY_MISMATCH", "The targeted record belongs to another cycle.")

    affirmation = db.insert(
        "affirmations",
        {
            "cycle_id": cycle["id"],
            "affirmation_type": affirmation_type,
            "statement": statement,
            "target_credit_record_id": target["id"] if target is not None else None,
            "affirmed_by_user_id": user_id,
        },
    )
    if target is not None:
        cascades.set_fields(target, {"affirmation_id": affirmation["id"]})
        cascades.mark_verified(target)
    return response.success(db.serialize(affirmation), 201)


@bp.route("/cle/compliance-cycles/<cycle_id>/certification", methods=["POST"])
def certify(cycle_id):
    user_id, role = middleware.require_roles([C.ROLE_ATTORNEY])
    cycle = load_cycle(cycle_id)
    require_cycle_owner(role, user_id, cycle)
    body = middleware.body_json()
    election = middleware.opt_enum(body, "carryover_election", CARRYOVER_ELECTIONS, None)

    if cycle.get("credit_status") != "OPEN":
        fail("ERR_INVALID_STATE_TRANSITION", "Only an OPEN period may be certified.")
    if cycle.get("administrative_status") == "ADMIN_SUSPENDED":
        fail("ERR_CYCLE_ADMIN_SUSPENDED", "That cycle accepts no credit-bearing write.")

    attorney = db.get("attorneys", cycle.get("attorney_id"))
    if attorney is not None and attorney.get("status") not in ("ACTIVE", "EXEMPT"):
        fail("ERR_ATTORNEY_NOT_IN_GOOD_STANDING", "The attorney is not in good standing.")

    has_final = any(
        a.get("cycle_id") == cycle["id"] and a.get("affirmation_type") == "FINAL_COMPLIANCE_AFFIRMATION"
        for a in db.all_rows("affirmations")
    )
    if not has_final:
        fail("ERR_AFFIRMATION_REQUIRED", "A FINAL_COMPLIANCE_AFFIRMATION must exist for this cycle.")

    if election is not None:
        cascades.set_fields(cycle, {"carryover_election": election})

    arrival_admin_status = cycle.get("administrative_status")
    delinquent_since = util.parse_dt(cycle.get("delinquent_since"))

    res = cascades.persist_application(cycle, "FINAL")
    cascades.set_fields(cycle, {"certified_at": util.now_iso()})
    deficient = calc.has_any_deficiency(res)
    if deficient:
        cascades.set_fields(cycle, {"credit_status": "DEFICIENT"})
        if attorney is not None:
            cascades.bump_deficiency_count(attorney, 1)
        out_general, out_ethics = 0, 0
    else:
        cascades.set_fields(cycle, {"credit_status": "SATISFIED"})
        out_general, out_ethics = calc.carryover_determination(cycle, res)
    cascades.write_carryover_out(cycle, out_general, out_ethics)

    if arrival_admin_status == "DELINQUENT" and not deficient:
        cascades.set_fields(
            cycle,
            {
                "administrative_status": "GOOD_STANDING",
                "delinquent_since": None,
                "credit_status": "SATISFIED",
            },
        )
        if delinquent_since is not None:
            grace_end = util.add_days(delinquent_since, C.LATE_FEE_VOID_GRACE_DAYS)
            if util.now_dt() <= grace_end:
                for fee in db.all_rows("fee_assessments"):
                    if fee.get("cycle_id") != cycle["id"]:
                        continue
                    if fee.get("fee_type") != "LATE_COMPLIANCE" or fee.get("status") != "ASSESSED":
                        continue
                    cascades.release_fee(fee, "VOIDED")

    db.touch(cycle)
    return response.success(db.serialize(cycle), 200)
