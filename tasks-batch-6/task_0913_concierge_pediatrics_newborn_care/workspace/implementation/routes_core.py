"""Clock, membership plans, physicians, families, insurance policies, children.

Every handler walks the 17-rung ladder of PRD 2.7 in source-line order; the
`RUNG n` comments name the rung each call implements.
"""
from flask import Blueprint, g

import calc
import constants as C
import serialize
import validate as V
from auth import begin, parent_family_scope, require_child_owner, require_family_owner
from envelope import object_response
from errors import ApiError
from listing import paginated
from store import db, new_row, touch
from timeutil import add_days, fmt_datetime

bp = Blueprint("core", __name__)


# ============================================================== logical clock
@bp.post("/peds/_clock/set_current_utc")
def set_clock():
    begin([C.ROLE_PRACTICE_ADMIN])                                   # RUNG 1, 2
    body = V.json_body()
    V.req_string(body, "to_iso8601")                                 # RUNG 4 p9
    target = V.req_datetime(body, "to_iso8601")                      # RUNG 5 p12
    V.date_range(                                                    # RUNG 5 p13
        target >= db.clock, "The logical clock may only move forward or stand still."
    )

    db.clock = target
    new_date = db.today()

    for visit in db.well_visits.values():
        if visit["status"] not in ("DUE", "SCHEDULED"):
            continue
        if add_days(visit["window_close_date"], C.WELL_VISIT_MISS_GRACE_DAYS) < new_date:
            visit["status"] = "MISSED"
            touch(visit, g.touched)

    for entry in db.waitlist_entries.values():
        if entry["status"] != "WAITING":
            continue
        if add_days(entry["created_at"].date(), C.WAITLIST_ENTRY_TTL_DAYS) < new_date:
            entry["status"] = "EXPIRED"
            touch(entry, g.touched)

    return object_response({"current_utc": fmt_datetime(db.clock)}, 200)


# ============================================================ MembershipPlan
@bp.post("/peds/membership-plans")
def create_plan():
    begin([C.ROLE_PRACTICE_ADMIN])                                   # RUNG 1, 2
    body = V.json_body()
    tier = V.req_string(body, "tier")                                # RUNG 4 p9
    monthly_rate_cents = V.req_int(body, "monthly_rate_cents")
    included_lactation = V.req_int(body, "included_lactation_consults")
    included_sleep = V.req_int(body, "included_sleep_consults")
    form_sla_hours = V.req_int(body, "form_sla_hours")
    waived = V.req_bool(body, "after_hours_surcharge_waived")
    overage = V.req_int(body, "overage_consult_fee_cents")

    V.enum_member(tier, C.PLAN_TIERS, "tier")                        # RUNG 4 p10

    V.check_range(monthly_rate_cents >= 0, "monthly_rate_cents must be at least 0.")
    V.check_range(included_lactation >= 0, "included_lactation_consults must be at least 0.")
    V.check_range(included_sleep >= 0, "included_sleep_consults must be at least 0.")
    V.check_range(form_sla_hours > 0, "form_sla_hours must be greater than 0.")
    V.check_range(overage >= 0, "overage_consult_fee_cents must be at least 0.")  # p11

    for plan in db.plans.values():                                   # RUNG 15 p33
        if plan["tier"] == tier:
            raise ApiError("ERR_DUPLICATE_WAITLIST_ENTRY", "That plan tier already exists.")

    plan = new_row(
        db.plans,
        {
            "tier": tier,
            "monthly_rate_cents": monthly_rate_cents,
            "included_lactation_consults": included_lactation,
            "included_sleep_consults": included_sleep,
            "form_sla_hours": form_sla_hours,
            "after_hours_surcharge_waived": waived,
            "overage_consult_fee_cents": overage,
        },
    )
    return object_response(serialize.plan_json(plan), 201)


@bp.get("/peds/membership-plans/<plan_id>")
def read_plan(plan_id):
    begin(
        [
            C.ROLE_PRACTICE_ADMIN,
            C.ROLE_CARE_COORDINATOR,
            C.ROLE_BILLING_SPECIALIST,
            C.ROLE_PHYSICIAN,
            C.ROLE_PARENT,
        ]
    )
    plan = db.plans.get(plan_id)                                     # RUNG 3 p7
    if plan is None:
        raise ApiError("ERR_PLAN_NOT_FOUND")
    return object_response(serialize.plan_json(plan), 200)


# ================================================================= Physician
@bp.post("/peds/physicians")
def create_physician():
    begin([C.ROLE_PRACTICE_ADMIN])
    body = V.json_body()
    full_name = V.req_string(body, "full_name")                      # RUNG 4 p9
    panel_slot_cap = V.req_number(body, "panel_slot_cap")
    state_codes = V.req_string_array(body, "licensed_state_codes")
    for code in state_codes:
        V.check_range(
            len(code) == 2 and code.isupper(),
            "licensed_state_codes must hold two-character upper-case state codes.",
        )
    V.check_range(panel_slot_cap > 0, "panel_slot_cap must be greater than 0.")  # p11

    physician = new_row(
        db.physicians,
        {
            "full_name": full_name,
            "panel_slot_cap": panel_slot_cap,
            "licensed_state_codes": list(state_codes),
        },
    )
    return object_response(serialize.physician_json(physician), 201)


@bp.get("/peds/physicians/<physician_id>")
def read_physician(physician_id):
    begin(
        [
            C.ROLE_PRACTICE_ADMIN,
            C.ROLE_CARE_COORDINATOR,
            C.ROLE_BILLING_SPECIALIST,
            C.ROLE_PHYSICIAN,
            C.ROLE_PARENT,
        ]
    )
    physician = db.physicians.get(physician_id)                      # RUNG 3 p5
    if physician is None:
        raise ApiError("ERR_PHYSICIAN_NOT_FOUND")
    return object_response(serialize.physician_json(physician), 200)


@bp.get("/peds/physicians/<physician_id>/panel")
def read_panel(physician_id):
    begin([C.ROLE_PRACTICE_ADMIN, C.ROLE_CARE_COORDINATOR, C.ROLE_PHYSICIAN])
    physician = db.physicians.get(physician_id)                      # RUNG 3 p5
    if physician is None:
        raise ApiError("ERR_PHYSICIAN_NOT_FOUND")

    occupancy, available = calc.physician_occupancy(physician)
    occupying = 0
    for membership in db.memberships.values():
        if (
            membership["physician_id"] == physician_id
            and membership["status"] in C.MEMBERSHIP_OCCUPYING_STATUSES
        ):
            occupying += 1
    waiting = 0
    for entry in db.waitlist_entries.values():
        if entry["physician_id"] == physician_id and entry["status"] == "WAITING":
            waiting += 1

    return object_response(
        {
            "physician_id": physician["id"],
            "panel_slot_cap": physician["panel_slot_cap"],
            "weighted_occupancy": occupancy,
            "available_panel_weight": available,
            "occupying_membership_count": occupying,
            "waiting_entry_count": waiting,
        },
        200,
    )


# ==================================================================== Family
@bp.post("/peds/families")
def create_family():
    begin([C.ROLE_PRACTICE_ADMIN])
    body = V.json_body()
    household_name = V.req_string(body, "household_name")            # RUNG 4 p9
    cap = V.req_int(body, "family_monthly_cap_cents")
    V.check_range(cap >= 0, "family_monthly_cap_cents must be at least 0.")  # p11

    family = new_row(
        db.families, {"household_name": household_name, "family_monthly_cap_cents": cap}
    )
    return object_response(serialize.family_json(family), 201)


@bp.get("/peds/families/<family_id>")
def read_family(family_id):
    begin(
        [
            C.ROLE_PRACTICE_ADMIN,
            C.ROLE_BILLING_SPECIALIST,
            C.ROLE_CARE_COORDINATOR,
            C.ROLE_PARENT,
        ]
    )
    family = db.families.get(family_id)                              # RUNG 3 p3
    if family is None:
        raise ApiError("ERR_FAMILY_NOT_FOUND")
    require_family_owner(family["id"])                               # RUNG 7 p19
    return object_response(serialize.family_json(family), 200)


# =========================================================== InsurancePolicy
@bp.post("/peds/insurance-policies")
def create_policy():
    begin([C.ROLE_PRACTICE_ADMIN, C.ROLE_BILLING_SPECIALIST])
    body = V.json_body()
    family_id = V.req_string(body, "family_id")                      # RUNG 4 p9
    carrier_name = V.req_string(body, "carrier_name")
    deductible_cents = V.req_int(body, "deductible_cents")
    coinsurance_rate = V.req_number(body, "coinsurance_rate")
    status = V.opt_enum(body, "status", C.POLICY_STATUSES, "ACTIVE")  # p9 then p10

    V.check_range(deductible_cents >= 0, "deductible_cents must be at least 0.")
    V.check_range(
        0 <= coinsurance_rate <= 1, "coinsurance_rate must be between 0 and 1 inclusive."
    )                                                                # RUNG 4 p11

    family = db.families.get(family_id)                              # RUNG 6 p14
    if family is None:
        raise ApiError("ERR_FAMILY_NOT_FOUND")

    policy = new_row(
        db.policies,
        {
            "family_id": family_id,
            "carrier_name": carrier_name,
            "deductible_cents": deductible_cents,
            "deductible_met_cents": 0,
            "coinsurance_rate": coinsurance_rate,
            "status": status,
        },
    )
    return object_response(serialize.policy_json(policy), 201)


@bp.get("/peds/insurance-policies")
def list_policies():
    begin([C.ROLE_PRACTICE_ADMIN, C.ROLE_BILLING_SPECIALIST])
    status = V.enum_filter("status", C.POLICY_STATUSES)              # RUNG 4 p10
    limit, offset = V.pagination()                                   # RUNG 4 p11
    family_id = V.filter_value("family_id")

    rows = []
    for policy in db.policies.values():
        if family_id is not None and policy["family_id"] != family_id:
            continue
        if status is not None and policy["status"] != status:
            continue
        rows.append(policy)
    return paginated(rows, serialize.policy_json, limit, offset)


@bp.get("/peds/insurance-policies/<policy_id>")
def read_policy(policy_id):
    begin([C.ROLE_PRACTICE_ADMIN, C.ROLE_BILLING_SPECIALIST])
    policy = db.policies.get(policy_id)                              # RUNG 3 p8
    if policy is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    return object_response(serialize.policy_json(policy), 200)


@bp.post("/peds/insurance-policies/<policy_id>/terminate")
def terminate_policy(policy_id):
    begin([C.ROLE_PRACTICE_ADMIN, C.ROLE_BILLING_SPECIALIST])
    policy = db.policies.get(policy_id)                              # RUNG 3 p8
    if policy is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    if policy["status"] != "ACTIVE":                                 # RUNG 10 p22
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE policy can be terminated.")

    policy["status"] = "TERMINATED"
    touch(policy, g.touched)  # deductible_met_cents is deliberately preserved
    return object_response(serialize.policy_json(policy), 200)


# ===================================================================== Child
@bp.post("/peds/children")
def create_child():
    begin([C.ROLE_PRACTICE_ADMIN, C.ROLE_CARE_COORDINATOR])
    body = V.json_body()
    family_id = V.req_string(body, "family_id")                      # RUNG 4 p9
    first_name = V.req_string(body, "first_name")
    date_of_birth = V.req_date(body, "date_of_birth")                # RUNG 5 p12

    family = db.families.get(family_id)                              # RUNG 6 p14
    if family is None:
        raise ApiError("ERR_FAMILY_NOT_FOUND")

    if date_of_birth > db.today():                                   # RUNG 13 p29
        raise ApiError("ERR_FUTURE_DATED", "date_of_birth may not be after today.")

    child = new_row(
        db.children,
        {"family_id": family_id, "first_name": first_name, "date_of_birth": date_of_birth},
    )
    return object_response(serialize.child_json(child), 201)


@bp.get("/peds/children")
def list_children():
    begin(
        [
            C.ROLE_PRACTICE_ADMIN,
            C.ROLE_CARE_COORDINATOR,
            C.ROLE_PHYSICIAN,
            C.ROLE_BILLING_SPECIALIST,
            C.ROLE_PARENT,
        ]
    )
    limit, offset = V.pagination()                                   # RUNG 4 p11
    family_id = V.filter_value("family_id")
    scope = parent_family_scope()

    rows = []
    for child in db.children.values():
        if family_id is not None and child["family_id"] != family_id:
            continue
        if scope is not None and child["family_id"] != scope:
            continue
        rows.append(child)
    return paginated(rows, serialize.child_json, limit, offset)


@bp.get("/peds/children/<child_id>")
def read_child(child_id):
    begin(
        [
            C.ROLE_PRACTICE_ADMIN,
            C.ROLE_CARE_COORDINATOR,
            C.ROLE_PHYSICIAN,
            C.ROLE_BILLING_SPECIALIST,
            C.ROLE_PARENT,
        ]
    )
    child = db.children.get(child_id)                                # RUNG 3 p4
    if child is None:
        raise ApiError("ERR_CHILD_NOT_FOUND")
    require_child_owner(child)                                       # RUNG 7 p19
    return object_response(serialize.child_json(child), 200)
