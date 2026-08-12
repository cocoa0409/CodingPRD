"""Routes: reimbursement districts, advances, levies, payments."""
from flask import Blueprint

from core import (
    DB, actor, require_roles, body, check_no_undeclared, req_string, req_int,
    req_number, req_datetime, opt_string, validation, err, invalid_state,
    new_entity, touch, get_or_404, check_body_fk, ok_object, filter_args,
)
from serializers import (
    district_out, advance_out, levy_out, payment_out,
    district_certified_interest_at, district_advances,
)
from routes_core import paginate_pairs

bp = Blueprint("district", __name__)

CTRL = ["DeclarantController"]
DIRECTOR = ["AssociationDirector"]


# ---------------------------------------------------------------------------
# Districts
# ---------------------------------------------------------------------------
@bp.route("/mpc/districts", methods=["POST"])
def create_district():
    _, role = actor()
    require_roles(role, CTRL)
    data = body()
    community = check_body_fk("community", DB.communities, data.get("community_id"))
    check_no_undeclared(data, {"community_id", "district_name",
                               "interest_rate_annual_pct"})
    req_string(data, "community_id")
    name = req_string(data, "district_name")
    rate = req_number(data, "interest_rate_annual_pct", minimum=0)
    for d in DB.districts.values():
        if d["community_id"] == community["id"]:
            err("ERR_DUPLICATE_DISTRICT", 409,
                "The community already has a reimbursement district")
    d = new_entity()
    d.update({
        "community_id": community["id"],
        "district_name": name,
        "interest_rate_annual_pct": rate,
    })
    DB.districts[d["id"]] = d
    return ok_object(district_out(d), 201)


@bp.route("/mpc/districts", methods=["GET"])
def list_districts():
    actor()
    f = filter_args(["community_id"])
    raw = [d for d in DB.districts.values()
           if f.get("community_id") in (None, d["community_id"])]
    return paginate_pairs(raw, district_out)


@bp.route("/mpc/districts/<did>", methods=["GET"])
def get_district(did):
    actor()
    d = get_or_404("district", DB.districts, did)
    return ok_object(district_out(d))


# ---------------------------------------------------------------------------
# Advances
# ---------------------------------------------------------------------------
@bp.route("/mpc/advances", methods=["POST"])
def create_advance():
    _, role = actor()
    require_roles(role, CTRL)
    data = body()
    district = check_body_fk("district", DB.districts, data.get("district_id"))
    check_no_undeclared(data, {"district_id", "amount_cents", "advance_date",
                               "description"})
    req_string(data, "district_id")
    amount = req_int(data, "amount_cents", gt=0)
    adv_date = req_datetime(data, "advance_date")
    desc = opt_string(data, "description", None)
    a = new_entity()
    a.update({
        "district_id": district["id"],
        "amount_cents": amount,
        "advance_date": adv_date,
        "description": desc,
        "reimbursed_principal_cents": 0,
    })
    DB.advances[a["id"]] = a
    return ok_object(advance_out(a), 201)


@bp.route("/mpc/advances", methods=["GET"])
def list_advances():
    actor()
    f = filter_args(["district_id"])
    raw = [a for a in DB.advances.values()
           if f.get("district_id") in (None, a["district_id"])]
    return paginate_pairs(raw, advance_out)


@bp.route("/mpc/advances/<aid>", methods=["GET"])
def get_advance(aid):
    actor()
    a = get_or_404("advance", DB.advances, aid)
    return ok_object(advance_out(a))


# ---------------------------------------------------------------------------
# Levies
# ---------------------------------------------------------------------------
@bp.route("/mpc/levies", methods=["POST"])
def create_levy():
    _, role = actor()
    require_roles(role, CTRL)
    data = body()
    district = check_body_fk("district", DB.districts, data.get("district_id"))
    check_no_undeclared(data, {"district_id", "levy_year", "amount_cents"})
    req_string(data, "district_id")
    year = req_int(data, "levy_year")
    amount = req_int(data, "amount_cents", gt=0)
    for l in DB.levies.values():
        if l["district_id"] == district["id"] and l["levy_year"] == year:
            validation("levy_year must be unique within the district")
    l = new_entity()
    l.update({
        "district_id": district["id"],
        "levy_year": year,
        "amount_cents": amount,
        "collected_at": None,
        "status": "PLANNED",
    })
    DB.levies[l["id"]] = l
    return ok_object(levy_out(l), 201)


@bp.route("/mpc/levies", methods=["GET"])
def list_levies():
    actor()
    f = filter_args(["district_id"])
    raw = [l for l in DB.levies.values()
           if f.get("district_id") in (None, l["district_id"])]
    return paginate_pairs(raw, levy_out)


@bp.route("/mpc/levies/<lid>", methods=["GET"])
def get_levy(lid):
    actor()
    l = get_or_404("levy", DB.levies, lid)
    return ok_object(levy_out(l))


@bp.route("/mpc/levies/<lid>/collect", methods=["POST"])
def collect_levy(lid):
    _, role = actor()
    require_roles(role, CTRL)
    l = get_or_404("levy", DB.levies, lid)
    data = body()
    check_no_undeclared(data, set())
    if l["status"] != "PLANNED":
        invalid_state("Levy is not PLANNED")
    l["status"] = "COLLECTED"
    l["collected_at"] = DB.now()
    touch(l)
    return ok_object(levy_out(l))


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
@bp.route("/mpc/payments", methods=["POST"])
def create_payment():
    user_id, role = actor()
    require_roles(role, CTRL)
    data = body()
    district = check_body_fk("district", DB.districts, data.get("district_id"))
    check_no_undeclared(data, {"district_id", "amount_cents"})
    req_string(data, "district_id")
    amount = req_int(data, "amount_cents", gt=0)
    p = new_entity()
    p.update({
        "district_id": district["id"],
        "requested_by_user_id": user_id,
        "amount_cents": amount,
        "certified_interest_cents": 0,
        "certified_principal_cents": 0,
        "certified_at": None,
        "paid_at": None,
        "status": "REQUESTED",
        "_allocations": [],
    })
    DB.payments[p["id"]] = p
    return ok_object(payment_out(p), 201)


@bp.route("/mpc/payments", methods=["GET"])
def list_payments():
    actor()
    f = filter_args(["district_id"])
    raw = [p for p in DB.payments.values()
           if f.get("district_id") in (None, p["district_id"])]
    return paginate_pairs(raw, payment_out)


@bp.route("/mpc/payments/<pid>", methods=["GET"])
def get_payment(pid):
    actor()
    p = get_or_404("payment", DB.payments, pid)
    return ok_object(payment_out(p))


def _outstanding_principal(district_id):
    advance_total = sum(a["amount_cents"] for a in district_advances(district_id))
    certified = sum(
        p["certified_principal_cents"]
        for p in DB.payments.values()
        if p["district_id"] == district_id and p["status"] in ("CERTIFIED", "PAID")
    )
    return advance_total - certified


@bp.route("/mpc/payments/<pid>/certify", methods=["POST"])
def certify_payment(pid):
    _, role = actor()
    require_roles(role, DIRECTOR)
    p = get_or_404("payment", DB.payments, pid)
    data = body()
    check_no_undeclared(data, set())
    if p["status"] != "REQUESTED":
        invalid_state("Payment is not REQUESTED")
    district = DB.districts.get(p["district_id"])
    now = DB.now()
    interest = district_certified_interest_at(district, now)
    outstanding = _outstanding_principal(p["district_id"])
    if p["amount_cents"] > outstanding + interest:
        err("ERR_PAYMENT_EXCEEDS_OBLIGATION", 402,
            "Payment exceeds outstanding principal plus certified interest")
    principal = p["amount_cents"] - interest
    if principal < 0:
        err("ERR_PAYMENT_EXCEEDS_OBLIGATION", 402,
            "Payment does not cover the interest due")
    # Interest-first globally, then principal to advances FIFO.
    advances = sorted(
        district_advances(p["district_id"]),
        key=lambda a: (a["advance_date"], a["created_at"]),
    )
    remaining = principal
    allocations = []
    for adv in advances:
        if remaining <= 0:
            break
        room = adv["amount_cents"] - adv["reimbursed_principal_cents"]
        if room <= 0:
            continue
        take = min(room, remaining)
        adv["reimbursed_principal_cents"] += take
        touch(adv)
        allocations.append((adv["id"], take))
        remaining -= take
    p["certified_interest_cents"] = interest
    p["certified_principal_cents"] = principal
    p["certified_at"] = now
    p["status"] = "CERTIFIED"
    p["_allocations"] = allocations
    touch(p)
    return ok_object(payment_out(p))


@bp.route("/mpc/payments/<pid>/pay", methods=["POST"])
def pay_payment(pid):
    _, role = actor()
    require_roles(role, CTRL)
    p = get_or_404("payment", DB.payments, pid)
    data = body()
    check_no_undeclared(data, set())
    if p["status"] != "CERTIFIED":
        invalid_state("Payment is not CERTIFIED")
    collected = sum(
        l["amount_cents"] for l in DB.levies.values()
        if l["district_id"] == p["district_id"] and l["status"] == "COLLECTED")
    paid = sum(
        q["amount_cents"] for q in DB.payments.values()
        if q["district_id"] == p["district_id"] and q["status"] == "PAID")
    if collected - paid < p["amount_cents"]:
        err("ERR_INSUFFICIENT_DISTRICT_FUNDS", 402,
            "District funds do not cover the payment")
    p["status"] = "PAID"
    p["paid_at"] = DB.now()
    touch(p)
    return ok_object(payment_out(p))


@bp.route("/mpc/payments/<pid>/reject", methods=["POST"])
def reject_payment(pid):
    _, role = actor()
    require_roles(role, DIRECTOR)
    p = get_or_404("payment", DB.payments, pid)
    data = body()
    check_no_undeclared(data, set())
    if p["status"] not in ("REQUESTED", "CERTIFIED"):
        invalid_state("Payment is not REQUESTED or CERTIFIED")
    if p["status"] == "CERTIFIED":
        # Compensating unwind: reverse FIFO (latest allocations first).
        for adv_id, amount in reversed(p.get("_allocations", [])):
            adv = DB.advances.get(adv_id)
            if adv is not None:
                adv["reimbursed_principal_cents"] -= amount
                touch(adv)
        p["_allocations"] = []
    p["status"] = "REJECTED"
    touch(p)
    return ok_object(payment_out(p))
