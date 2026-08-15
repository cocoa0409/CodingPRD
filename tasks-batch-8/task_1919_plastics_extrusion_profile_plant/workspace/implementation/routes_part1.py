"""Routes: customers, profiles, dies, lines, resin lots, formulations."""
from state import (
    D, ApiError, err_bad, err_not_found,
    customers, profiles, dies, lines, lots, formulations, batches,
    endpoint, list_result, get_body, Fields, require_exists,
    pagination, paginate, sort_created, mark, stamp_new,
    ser_customer, ser_profile, ser_die, ser_line, ser_lot, ser_formulation,
    COLOR_FAMILIES, ALL_ROLES,
)
from services import (
    pin_amortization_rates, credit_back_lots,
)


# ============================ Customers ====================================
@endpoint("/customers", ["POST"], ["PlantManager"])
def create_customer(user_id):
    body = get_body()
    f = Fields(body)
    f.str_("name")
    f.enum("resin_index_basis", ["MONTHLY_AVG", "SHIPMENT_DATE"])
    f.int_("credit_limit_cents")
    f.fail_if_problems()
    cust = stamp_new({
        "name": f.values["name"],
        "resin_index_basis": f.values["resin_index_basis"],
        "credit_limit_cents": f.values["credit_limit_cents"],
        "status": "ACTIVE",
        "open_exposure_cents": 0,
    })
    customers[cust["id"]] = cust
    return ser_customer(cust), 201


@endpoint("/customers/<customer_id>", ["GET"], ALL_ROLES)
def get_customer(user_id, customer_id):
    return ser_customer(require_exists(customers, customer_id, "Customer")), 200


@endpoint("/customers/<customer_id>/credit-status", ["POST"], ["PlantManager"])
def customer_credit_status(user_id, customer_id):
    cust = require_exists(customers, customer_id, "Customer")
    body = get_body()
    action = body.get("action")
    if not isinstance(action, str) or action not in ("HOLD", "RELEASE"):
        raise err_bad("action must be HOLD or RELEASE")
    if action == "HOLD":
        if cust["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Customer is not ACTIVE")
        cust["status"] = "CREDIT_HOLD"
    else:
        if cust["status"] != "CREDIT_HOLD":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Customer is not CREDIT_HOLD")
        cust["status"] = "ACTIVE"
    mark(cust)
    return ser_customer(cust), 200


# ============================ Profiles =====================================
DIM_KEYS = ("name", "nominal_mm", "tol_plus_mm", "tol_minus_mm",
            "ucl_mm", "lcl_mm")


@endpoint("/profiles", ["POST"], ["ProcessEngineer"])
def create_profile(user_id):
    body = get_body()
    f = Fields(body)
    f.str_("customer_id")
    f.str_("profile_code")
    dims = f.arr("critical_dimensions", min_len=1)
    f.int_("spc_subgroup_size", min_v=1)
    f.int_("sample_every_m", min_v=1)
    f.num("resin_content_kg_per_m", positive=True)
    f.num("min_line_speed_mpm", positive=True)
    f.num("max_line_speed_mpm", positive=True)
    # existence (priority 3)
    cid = f.values.get("customer_id")
    if isinstance(cid, str):
        require_exists(customers, cid, "Customer")
    # structural dimension-shape check (tier 30 detail)
    if isinstance(dims, list) and len(dims) >= 1:
        for d in dims:
            if not isinstance(d, dict):
                f.problems.append("critical_dimensions")
                break
            ok = isinstance(d.get("name"), str)
            for k in ("nominal_mm", "tol_plus_mm", "tol_minus_mm",
                      "ucl_mm", "lcl_mm"):
                v = d.get(k)
                if not (isinstance(v, (int, float)) and not isinstance(v, bool)):
                    ok = False
            if not ok:
                f.problems.append("critical_dimensions")
                break
    f.fail_if_problems()
    if any(p["profile_code"] == f.values["profile_code"]
           for p in profiles.values()):
        raise err_bad("profile_code must be unique")
    prof = stamp_new({
        "customer_id": cid,
        "profile_code": f.values["profile_code"],
        "critical_dimensions": dims,
        "spc_subgroup_size": f.values["spc_subgroup_size"],
        "sample_every_m": f.values["sample_every_m"],
        "resin_content_kg_per_m": f.values["resin_content_kg_per_m"],
        "min_line_speed_mpm": f.values["min_line_speed_mpm"],
        "max_line_speed_mpm": f.values["max_line_speed_mpm"],
    })
    profiles[prof["id"]] = prof
    return ser_profile(prof), 201


@endpoint("/profiles/<profile_id>", ["GET"], ALL_ROLES)
def get_profile(user_id, profile_id):
    return ser_profile(require_exists(profiles, profile_id, "Profile")), 200


@endpoint("/profiles", ["GET"], ALL_ROLES)
def list_profiles(user_id):
    limit, offset = pagination()
    items = sort_created(list(profiles.values()))
    cf = request_arg("customer_id")
    if cf is not None:
        items = [p for p in items if p["customer_id"] == cf]
    page, total = paginate(items, limit, offset)
    return list_result([ser_profile(p) for p in page], limit, offset, total)


def request_arg(name):
    from flask import request
    v = request.args.get(name)
    return v if v not in (None, "") else None


# ============================ Dies =========================================
DIE_STATES = {"DRAFT", "TRIAL", "QUALIFIED", "IN_SERVICE", "MAINTENANCE",
              "RETIRED"}


@endpoint("/dies", ["POST"], ["ProcessEngineer"])
def create_die(user_id):
    body = get_body()
    f = Fields(body)
    f.str_("profile_id")
    f.str_("die_code")
    f.int_("tooling_cost_cents", min_v=0)
    f.num("committed_length_m", positive=True)
    f.num("committed_weight_kg", positive=True)
    f.enum("amortization_mode", ["PER_METER", "PER_KG"])
    f.int_("buffer_hours", min_v=0)
    f.num("min_screw_mm", positive=True)
    f.num("max_screw_mm", positive=True)
    pid = f.values.get("profile_id")
    if isinstance(pid, str):
        require_exists(profiles, pid, "Profile")
    f.fail_if_problems()
    if any(d["die_code"] == f.values["die_code"] for d in dies.values()):
        raise err_bad("die_code must be unique")
    die = stamp_new({
        "profile_id": pid,
        "die_code": f.values["die_code"],
        "tooling_cost_cents": f.values["tooling_cost_cents"],
        "committed_length_m": f.values["committed_length_m"],
        "committed_weight_kg": f.values["committed_weight_kg"],
        "amortization_mode": f.values["amortization_mode"],
        "buffer_hours": f.values["buffer_hours"],
        "min_screw_mm": f.values["min_screw_mm"],
        "max_screw_mm": f.values["max_screw_mm"],
        "amort_rate_cents_per_m": None,
        "amort_rate_cents_per_kg": None,
        "amortized_cents": 0,
        "remaining_balance_cents": f.values["tooling_cost_cents"],
        "status": "DRAFT",
    })
    dies[die["id"]] = die
    return ser_die(die), 201


@endpoint("/dies/<die_id>", ["GET"], ALL_ROLES)
def get_die(user_id, die_id):
    return ser_die(require_exists(dies, die_id, "Die")), 200


@endpoint("/dies", ["GET"], ALL_ROLES)
def list_dies(user_id):
    limit, offset = pagination()
    items = sort_created(list(dies.values()))
    pf = request_arg("profile_id")
    if pf is not None:
        items = [d for d in items if d["profile_id"] == pf]
    page, total = paginate(items, limit, offset)
    return list_result([ser_die(d) for d in page], limit, offset, total)


def _die_has_assignment(die_id, statuses):
    return any(a["die_id"] == die_id and a["status"] in statuses
               for a in assignments_values())


def assignments_values():
    from state import assignments
    return assignments.values()


@endpoint("/dies/<die_id>/transition", ["POST"], ["ProcessEngineer"])
def die_transition(user_id, die_id):
    die = require_exists(dies, die_id, "Die")
    body = get_body()
    to = body.get("to")
    if not isinstance(to, str) or to not in DIE_STATES:
        raise err_bad("to must be one of %s" % ", ".join(sorted(DIE_STATES)))
    cur = die["status"]
    edges = {
        ("DRAFT", "TRIAL"),
        ("TRIAL", "QUALIFIED"),
        ("TRIAL", "DRAFT"),
        ("IN_SERVICE", "MAINTENANCE"),
        ("MAINTENANCE", "IN_SERVICE"),
        ("IN_SERVICE", "RETIRED"),
        ("MAINTENANCE", "RETIRED"),
    }
    if (cur, to) not in edges:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Die cannot transition %s -> %s" % (cur, to))
    if to == "MAINTENANCE":
        if _die_has_assignment(die["id"], {"ACTIVE"}):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Die has an ACTIVE assignment")
    if to == "RETIRED":
        if _die_has_assignment(die["id"], {"SCHEDULED", "ACTIVE"}):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Die has SCHEDULED or ACTIVE assignments")
    if to == "QUALIFIED":
        pin_amortization_rates(die)
    die["status"] = to
    mark(die)
    return ser_die(die), 200


@endpoint("/dies/<die_id>/amortization-adjustments", ["POST"],
          ["PlantManager"])
def die_amortization_adjustment(user_id, die_id):
    die = require_exists(dies, die_id, "Die")
    body = get_body()
    f = Fields(body)
    f.int_("adjustment_cents")
    f.str_("reason")
    # OCC field is non-optional (PRD 2.7); a missing/ill-typed one is a
    # deferred structural problem evaluated after domain tiers.
    occ_missing = False
    ev = body.get("expected_die_version")
    if ev is None or not (isinstance(ev, int) and not isinstance(ev, bool)):
        occ_missing = True
    elif ev != die["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_die_version does not match current version")
    if die["status"] not in ("QUALIFIED", "IN_SERVICE", "MAINTENANCE"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Adjustments require QUALIFIED, IN_SERVICE or "
                       "MAINTENANCE die")
    if f.ok("adjustment_cents"):
        adj = f.values["adjustment_cents"]
        new_amort = die["amortized_cents"] + adj
        new_rem = die["remaining_balance_cents"] - adj
        cost = die["tooling_cost_cents"]
        if not (0 <= new_amort <= cost) or not (0 <= new_rem <= cost):
            raise err_bad("Adjustment would drive balances outside "
                          "[0, tooling_cost_cents]")
    f.fail_if_problems()
    if occ_missing:
        raise err_bad("expected_die_version is required")
    adj = f.values["adjustment_cents"]
    die["amortized_cents"] += adj
    die["remaining_balance_cents"] -= adj
    mark(die)
    return ser_die(die), 200


# ============================ Extrusion lines ==============================
@endpoint("/lines", ["POST"], ["ProcessEngineer"])
def create_line(user_id):
    body = get_body()
    f = Fields(body)
    f.str_("line_code")
    f.num("screw_diameter_mm", positive=True)
    f.fail_if_problems()
    if any(l["line_code"] == f.values["line_code"] for l in lines.values()):
        raise err_bad("line_code must be unique")
    line = stamp_new({
        "line_code": f.values["line_code"],
        "screw_diameter_mm": f.values["screw_diameter_mm"],
        "status": "IDLE",
    })
    lines[line["id"]] = line
    return ser_line(line), 201


@endpoint("/lines/<line_id>", ["GET"], ALL_ROLES)
def get_line(user_id, line_id):
    return ser_line(require_exists(lines, line_id, "ExtrusionLine")), 200


# ============================ Resin lots ===================================
LOT_KINDS = ["VIRGIN", "REGRIND", "COLORANT"]


@endpoint("/resin-lots", ["POST"], ["LineOperator"])
def create_lot(user_id):
    body = get_body()
    f = Fields(body)
    f.enum("lot_kind", LOT_KINDS)
    f.str_("resin_type")
    f.enum("color_family", sorted(COLOR_FAMILIES))
    f.num("received_kg", positive=True)
    f.str_("supplier_lot_ref", required=False)
    # priority 15: VIRGIN lots must be NATURAL
    if f.ok("lot_kind", "color_family"):
        if f.values["lot_kind"] == "VIRGIN" and \
                f.values["color_family"] != "NATURAL":
            raise err_bad("VIRGIN lots must have color_family NATURAL")
    f.fail_if_problems()
    lot = stamp_new({
        "lot_kind": f.values["lot_kind"],
        "resin_type": f.values["resin_type"],
        "color_family": f.values["color_family"],
        "received_kg": f.values["received_kg"],
        "supplier_lot_ref": f.values.get("supplier_lot_ref"),
        "consumed_kg": D(0),
        "available_kg": f.values["received_kg"],
        "status": "RECEIVED",
    })
    lots[lot["id"]] = lot
    return ser_lot(lot), 201


@endpoint("/resin-lots/<lot_id>", ["GET"], ALL_ROLES)
def get_lot(user_id, lot_id):
    return ser_lot(require_exists(lots, lot_id, "ResinLot")), 200


@endpoint("/resin-lots/<lot_id>/qc", ["POST"], ["QualityInspector"])
def lot_qc(user_id, lot_id):
    lot = require_exists(lots, lot_id, "ResinLot")
    body = get_body()
    outcome = body.get("outcome")
    if not isinstance(outcome, str) or outcome not in ("PASS", "FAIL",
                                                       "REVERSE"):
        raise err_bad("outcome must be PASS, FAIL or REVERSE")
    if outcome in ("PASS", "FAIL"):
        if lot["status"] != "RECEIVED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Lot is not RECEIVED")
        lot["status"] = "QC_PASSED" if outcome == "PASS" else "QC_REJECTED"
        mark(lot)
        return ser_lot(lot), 200
    # REVERSE: QC_PASSED -> QC_REJECTED with batch quarantine cascade
    if lot["status"] != "QC_PASSED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "REVERSE requires a QC_PASSED lot")
    lot["status"] = "QC_REJECTED"
    mark(lot)
    for b in sort_created(list(batches.values())):
        if b["status"] not in ("BLENDED", "QC_RELEASED"):
            continue
        if lot_id not in (b["virgin_lot_id"], b.get("regrind_lot_id"),
                          b["colorant_lot_id"]):
            continue
        b["pre_quarantine_status"] = b["status"]
        b["status"] = "QUARANTINED"
        credit_back_lots(b)
        mark(b)
    return ser_lot(lot), 200


# ============================ Formulations =================================
@endpoint("/formulations", ["POST"], ["ProcessEngineer"])
def create_formulation(user_id):
    body = get_body()
    f = Fields(body)
    f.str_("profile_id")
    f.str_("formula_code")
    f.str_("base_resin_type")
    f.enum("color_family", sorted(COLOR_FAMILIES))
    f.num("let_down_ratio")
    f.num("max_regrind_pct")
    pid = f.values.get("profile_id")
    if isinstance(pid, str):
        require_exists(profiles, pid, "Profile")
    # priority 14: bounded formulation numbers
    if f.ok("let_down_ratio"):
        ldr = f.values["let_down_ratio"]
        if ldr < D("10.0") or ldr > D("50.0"):
            raise ApiError("ERR_LET_DOWN_RANGE", 400,
                           "let_down_ratio must be within [10.0, 50.0]")
    if f.ok("max_regrind_pct"):
        mrp = f.values["max_regrind_pct"]
        if mrp < D(0) or mrp > D(40):
            raise ApiError("ERR_LET_DOWN_RANGE", 400,
                           "max_regrind_pct must be within [0, 40]")
    f.fail_if_problems()
    if any(x["formula_code"] == f.values["formula_code"]
           for x in formulations.values()):
        raise err_bad("formula_code must be unique")
    form = stamp_new({
        "profile_id": pid,
        "formula_code": f.values["formula_code"],
        "base_resin_type": f.values["base_resin_type"],
        "color_family": f.values["color_family"],
        "let_down_ratio": f.values["let_down_ratio"],
        "max_regrind_pct": f.values["max_regrind_pct"],
    })
    formulations[form["id"]] = form
    return ser_formulation(form), 201


@endpoint("/formulations/<formulation_id>", ["GET"], ALL_ROLES)
def get_formulation(user_id, formulation_id):
    return ser_formulation(
        require_exists(formulations, formulation_id, "Formulation")), 200


@endpoint("/formulations", ["GET"], ALL_ROLES)
def list_formulations(user_id):
    limit, offset = pagination()
    items = sort_created(list(formulations.values()))
    pf = request_arg("profile_id")
    if pf is not None:
        items = [x for x in items if x["profile_id"] == pf]
    page, total = paginate(items, limit, offset)
    return list_result([ser_formulation(x) for x in page], limit, offset,
                       total)
