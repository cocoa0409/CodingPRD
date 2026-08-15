"""Business logic: derived fields, calculations, cascades, serializers (PRD 3.x)."""
from decimal import Decimal

from flask import g

from db import db, next_seq
from response import success_list
from util import CLOCK, fmt_datetime, new_id, round1, round_half_up_int
from validate import get_pagination

# ---------------------------------------------------------------------------
# Constants (scaffold 1.3)
# ---------------------------------------------------------------------------

WORKMANSHIP_CLASSES = ("IPC_CLASS_1", "IPC_CLASS_2", "IPC_CLASS_3")
COMPONENT_TYPES = ("CONNECTOR", "TERMINAL", "WIRE", "SEAL", "SLEEVE")
SUPPLY_TYPES = ("FACTORY_STOCK", "CUSTOMER_CONSIGNED")
TERMINAL_TYPES = ("OPEN_BARREL", "CLOSED_BARREL")
SAMPLE_KINDS = ("FIRST_ARTICLE", "LOT_SAMPLE")
TEST_TYPES = ("CONTINUITY", "HIPOT")
ISSUE_SOURCES = ("FACTORY_STOCK", "CONSIGNED_LOT")
WIP_DISPOSITIONS = ("REWORK", "USE_AS_IS", "SCRAP")
SCRAP_REASONS = ("DAMAGE", "QC_SUSPECT")

BUILT_COUNT_STATUSES = {"BUILT", "TEST_PASS", "REWORK", "SUSPECT", "SHIPPED"}

HIPOT_CLASS_MIN_V = {"IPC_CLASS_1": 500, "IPC_CLASS_2": 1000, "IPC_CLASS_3": 1500}

RECOVERY_RATE = Decimal("0.8")


# ---------------------------------------------------------------------------
# Version / timestamp touch: at most one version bump per resource per request.
# ---------------------------------------------------------------------------

def touch(obj):
    bumped = getattr(g, "_bumped", None)
    if bumped is None:
        bumped = set()
        g._bumped = bumped
    key = id(obj)
    if key in bumped:
        return
    bumped.add(key)
    if "version" in obj:
        obj["version"] += 1
        obj["updated_at"] = CLOCK.now()


def common_fields():
    now = CLOCK.now()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }


def record_fields():
    """Append-only evidence records carry only id + created_at (PRD 2.4)."""
    now = CLOCK.now()
    return {
        "id": new_id(),
        "created_at": now,
        "_seq": next_seq(),
    }


# ---------------------------------------------------------------------------
# Lookups and derived fields
# ---------------------------------------------------------------------------

def bom_lines(drawing_id):
    return [c for c in db["components"].values() if c["drawing_id"] == drawing_id]


def order_units(order_id):
    return [u for u in db["harness_units"].values() if u["build_order_id"] == order_id]


def order_kits(order_id):
    return [k for k in db["kits"].values() if k["build_order_id"] == order_id]


def per_harness_standard_cents(order):
    return sum(c["qty_per_harness"] * c["unit_cost_cents"]
               for c in bom_lines(order["drawing_id"]))


def recompute_order_counters(order):
    """build_order_quantity_reconciliation + STANDARD cost roll-up."""
    units = order_units(order["id"])
    order["qty_built"] = sum(1 for u in units if u["status"] in BUILT_COUNT_STATUSES)
    order["qty_scrapped"] = sum(1 for u in units if u["status"] == "SCRAPPED")
    order["standard_cost_cents"] = order["qty_built"] * per_harness_standard_cents(order)


def recompute_order_spend(order):
    """ACTUAL cost roll-up == material spend (non-voided kit issues only)."""
    total = 0
    for kit in order_kits(order["id"]):
        for iss in kit["issues"]:
            if not iss["voided"]:
                total += iss["qty_issued"] * iss["unit_cost_snapshot_cents"]
    order["material_spent_cents"] = total
    order["actual_cost_cents"] = total


def order_status_checks(order):
    """IN_BUILD->TESTING, then TESTING->CANCELLED / TESTING->COMPLETED (PRD 3.5, 3.7)."""
    if (order["status"] == "IN_BUILD"
            and order["qty_built"] + order["qty_scrapped"] == order["qty_ordered"]):
        order["status"] = "TESTING"
    if order["status"] == "TESTING":
        if order["qty_built"] == 0:
            order["status"] = "CANCELLED"
        else:
            units = order_units(order["id"])
            if units and all(u["status"] in ("TEST_PASS", "SHIPPED", "SCRAPPED")
                             for u in units):
                order["status"] = "COMPLETED"


def completion_check(order):
    """TESTING -> COMPLETED bubble-up run on unit TEST_PASS transitions."""
    if order["status"] != "TESTING":
        return
    if order["qty_built"] < 1:
        return
    units = order_units(order["id"])
    if units and all(u["status"] in ("TEST_PASS", "SHIPPED", "SCRAPPED") for u in units):
        order["status"] = "COMPLETED"
        touch(order)


def kit_shortage_count(kit, order):
    """kit_completeness: sum over pinned BOM lines of max(0, needed - issued)."""
    needed = {c["id"]: c["qty_per_harness"] * order["qty_ordered"]
              for c in bom_lines(order["drawing_id"])}
    issued = {}
    for iss in kit["issues"]:
        if not iss["voided"]:
            issued[iss["component_id"]] = issued.get(iss["component_id"], 0) + iss["qty_issued"]
    return sum(max(0, n - issued.get(cid, 0)) for cid, n in needed.items())


def recompute_lot_liabilities(lot):
    """consigned_scrap_liability: BOOK_VALUE and REPLACEMENT_VALUE variants."""
    lot["book_liability_cents"] = lot["qty_scrapped"] * lot["unit_liability_cents"]
    lot["replacement_liability_cents"] = lot["qty_scrapped"] * lot["replacement_cost_cents"]


def lot_reconcile(lot):
    """consigned_lot_quantity_reconciliation: auto-DEPLETED at zero on-hand/open."""
    if (lot["status"] == "ACTIVE"
            and lot["qty_on_hand"] == 0 and lot["qty_issued_open"] == 0):
        lot["status"] = "DEPLETED"
        touch(lot)


def cert_status(cert):
    """operator_certification_status: computed on every read, never stored."""
    if cert["revoked_at"] is not None:
        return "REVOKED"
    if CLOCK.now() >= cert["expires_at"]:
        return "EXPIRED"
    return "ACTIVE"


def has_active_cert(operator_id, workmanship_class):
    for c in db["operator_certifications"].values():
        if (c["operator_id"] == operator_id
                and c["workmanship_class"] == workmanship_class
                and cert_status(c) == "ACTIVE"):
            return True
    return False


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def compute_min_pull_force_n(wire_gauge_awg, terminal_type, workmanship_class):
    """crimp_pull_force_minimum: AWG tier x terminal derating x class multiplier."""
    if wire_gauge_awg >= 24:
        base = Decimal("15.0")
    elif wire_gauge_awg >= 20:
        base = Decimal("30.0")
    elif wire_gauge_awg >= 16:
        base = Decimal("50.0")
    else:
        base = Decimal("80.0")
    derating = Decimal("1.0") if terminal_type == "OPEN_BARREL" else Decimal("0.9")
    multiplier = Decimal("1.1") if workmanship_class == "IPC_CLASS_3" else Decimal("1.0")
    return round1(base * derating * multiplier)


def scrap_credit_cents(order):
    """scrap_recovery_credit: round each BOM line to integer cents FIRST, then sum."""
    total = 0
    for c in bom_lines(order["drawing_id"]):
        line = Decimal(c["qty_per_harness"]) * Decimal(c["unit_cost_cents"]) * RECOVERY_RATE
        total += round_half_up_int(line)
    return total


# ---------------------------------------------------------------------------
# Kit side effects
# ---------------------------------------------------------------------------

def return_kit(kit):
    """Kit PICKING|STAGED -> RETURNED: void all issues, restore consigned on-hand."""
    order = db["build_orders"][kit["build_order_id"]]
    for iss in kit["issues"]:
        if iss["voided"]:
            continue
        iss["voided"] = True
        if iss["source"] == "CONSIGNED_LOT":
            lot = db["consigned_lots"].get(iss["consigned_lot_id"])
            if lot is not None:
                lot["qty_issued_open"] -= iss["qty_issued"]
                lot["qty_on_hand"] += iss["qty_issued"]
                touch(lot)
    kit["status"] = "RETURNED"
    # kit_completeness also triggers on kit return: with every issue voided the
    # shortage recomputes to the full needed quantity.
    kit["shortage_count"] = kit_shortage_count(kit, order)
    touch(kit)
    recompute_order_spend(order)
    touch(order)


# ---------------------------------------------------------------------------
# Harness unit scrap (manual DAMAGE/QC_SUSPECT and ECN_DISPOSITION)
# ---------------------------------------------------------------------------

def scrap_unit(unit, reason):
    order = db["build_orders"][unit["build_order_id"]]
    unit["status"] = "SCRAPPED"
    unit["scrap_reason"] = reason
    unit["suspect_marked_at"] = None
    touch(unit)

    # 1. Scrap recovery credit accumulates onto the order.
    order["scrap_recovery_credit_cents"] += scrap_credit_cents(order)

    # 2. Consigned content transfers lot qty_consumed -> qty_scrapped, walking the
    #    order's delivered consigned issues FIFO by issued_at ASC, tie-break
    #    kit_seq ASC (scaffold 1.2 HarnessUnit SCRAPPED side effects).
    for line in bom_lines(order["drawing_id"]):
        if line["supply_type"] != "CUSTOMER_CONSIGNED":
            continue
        remaining = line["qty_per_harness"]
        candidates = []
        for kit in order_kits(order["id"]):
            for iss in kit["issues"]:
                if (not iss["voided"] and iss["source"] == "CONSIGNED_LOT"
                        and iss["component_id"] == line["id"]
                        and iss.get("_delivered_qty", 0) > 0):
                    candidates.append((iss["issued_at"], kit["kit_seq"], iss["_seq"], iss))
        candidates.sort(key=lambda t: (t[0], t[1], t[2]))
        for _, _, _, iss in candidates:
            if remaining <= 0:
                break
            take = min(remaining, iss["_delivered_qty"])
            iss["_delivered_qty"] -= take
            remaining -= take
            lot = db["consigned_lots"].get(iss["consigned_lot_id"])
            if lot is not None:
                lot["qty_consumed"] -= take
                lot["qty_scrapped"] += take
                recompute_lot_liabilities(lot)
                lot_reconcile(lot)
                touch(lot)

    # 3. Order counters and order-level checks.
    recompute_order_counters(order)
    order_status_checks(order)
    touch(order)


# ---------------------------------------------------------------------------
# Pull-test cascades (PRD 3.4)
# ---------------------------------------------------------------------------

def apply_first_article_pass(applicator, program):
    """Applicator AVAILABLE -> QUALIFIED; program DRAFT|HELD -> QUALIFIED; the
    HELD -> QUALIFIED requalification releases QC_HOLD orders (created_at ASC)."""
    now = CLOCK.now()
    applicator["status"] = "QUALIFIED"
    applicator["qualified_at"] = now
    touch(applicator)

    if program["status"] == "DRAFT":
        program["status"] = "QUALIFIED"
        touch(program)
    elif program["status"] == "HELD":
        # Requalification requires a CLOSED setup for the pair created after
        # the quarantine. "Created after" is causal creation order, tracked via
        # the insertion sequence so a frozen logical clock cannot tie-break it.
        quarantine_seq = applicator.get("_quarantine_seq")
        ok = False
        for s in db["applicator_setups"].values():
            if (s["applicator_id"] == applicator["id"]
                    and s["program_id"] == program["id"]
                    and s["status"] == "CLOSED"
                    and (quarantine_seq is None or s["_seq"] > quarantine_seq)):
                ok = True
                break
        if ok:
            program["status"] = "QUALIFIED"
            touch(program)
            held = [o for o in db["build_orders"].values()
                    if o["status"] == "QC_HOLD" and o["held_by_program_id"] == program["id"]]
            held.sort(key=lambda o: (o["created_at"], o["_seq"]))
            for o in held:
                o["status"] = o["qc_hold_return_status"]
                o["qc_hold_return_status"] = None
                o["held_by_program_id"] = None
                touch(o)


def apply_lot_sample_fail(applicator):
    """Applicator QUALIFIED -> QUARANTINED; programs HELD (depth 2); build orders
    QC_HOLD (depth 3); HarnessUnit SUSPECT sweep (depth 4, suspect_unit_selection)."""
    now = CLOCK.now()
    qualified_at = applicator["qualified_at"]
    applicator["status"] = "QUARANTINED"
    applicator["_quarantine_seq"] = next_seq()
    touch(applicator)

    programs = [p for p in db["machine_programs"].values()
                if p["applicator_id"] == applicator["id"] and p["status"] == "QUALIFIED"]
    programs.sort(key=lambda p: (p["created_at"], p["_seq"]))
    for program in programs:
        program["status"] = "HELD"
        touch(program)

        orders = [o for o in db["build_orders"].values()
                  if o["drawing_id"] == program["drawing_id"]
                  and o["status"] in ("KITTING", "IN_BUILD", "TESTING")]
        orders.sort(key=lambda o: (o["created_at"], o["_seq"]))
        newly_held = []
        for o in orders:
            o["qc_hold_return_status"] = o["status"]
            o["held_by_program_id"] = program["id"]
            o["status"] = "QC_HOLD"
            touch(o)
            newly_held.append(o)

        # Suspect sweep: units of orders that entered QC_HOLD via THIS quarantine,
        # status in {BUILT, REWORK, TEST_PASS}, created_at >= applicator.qualified_at;
        # orders by created_at ASC, then units by created_at ASC.
        for o in newly_held:
            units = [u for u in order_units(o["id"])
                     if u["status"] in ("BUILT", "REWORK", "TEST_PASS")
                     and (qualified_at is None or u["created_at"] >= qualified_at)]
            units.sort(key=lambda u: (u["created_at"], u["_seq"]))
            for u in units:
                u["status"] = "SUSPECT"
                u["suspect_marked_at"] = now
                u["continuity_pass"] = False
                u["hipot_pass"] = False
                u["_continuity_pass_at"] = None
                u["_hipot_pass_at"] = None
                touch(u)


# ---------------------------------------------------------------------------
# ECN apply cascade (PRD 3.8)
# ---------------------------------------------------------------------------

def apply_ecn(ecn):
    now = CLOCK.now()
    drawing = db["drawings"][ecn["drawing_id"]]

    # Depth 1: old drawing RELEASED -> SUPERSEDED.
    drawing["status"] = "SUPERSEDED"
    drawing["superseded_at"] = now
    touch(drawing)

    # New DRAFT revision row with copied header fields and copied BOM.
    new_drawing = common_fields()
    new_drawing.update({
        "drawing_number": drawing["drawing_number"],
        "customer_code": drawing["customer_code"],
        "revision": ecn["to_revision"],
        "workmanship_class": drawing["workmanship_class"],
        "status": "DRAFT",
        "released_at": None,
        "superseded_at": None,
    })
    db["drawings"][new_drawing["id"]] = new_drawing
    for comp in bom_lines(drawing["id"]):
        new_comp = common_fields()
        new_comp.update({
            "drawing_id": new_drawing["id"],
            "find_number": comp["find_number"],
            "component_type": comp["component_type"],
            "mpn": comp["mpn"],
            "qty_per_harness": comp["qty_per_harness"],
            "supply_type": comp["supply_type"],
            "unit_cost_cents": comp["unit_cost_cents"],
        })
        db["components"][new_comp["id"]] = new_comp
    ecn["new_drawing_id"] = new_drawing["id"]

    # Depth 2: disposition build orders pinned to the old drawing, created_at ASC.
    targets = [o for o in db["build_orders"].values()
               if o["drawing_id"] == drawing["id"]
               and o["status"] in ("OPEN", "KITTING", "IN_BUILD", "TESTING", "QC_HOLD")]
    targets.sort(key=lambda o: (o["created_at"], o["_seq"]))
    disposition = ecn["wip_disposition"]
    for order in targets:
        if disposition == "USE_AS_IS":
            order["use_as_is_flag"] = True
            touch(order)
        elif disposition == "REWORK":
            units = sorted(order_units(order["id"]),
                           key=lambda u: (u["created_at"], u["_seq"]))
            for u in units:
                if u["status"] in ("BUILT", "TEST_PASS"):
                    u["status"] = "REWORK"
                    u["continuity_pass"] = False
                    u["hipot_pass"] = False
                    u["_continuity_pass_at"] = None
                    u["_hipot_pass_at"] = None
                    touch(u)
        elif disposition == "SCRAP":
            order["status"] = "CANCELLED"
            order["qc_hold_return_status"] = None
            order["held_by_program_id"] = None
            units = sorted(order_units(order["id"]),
                           key=lambda u: (u["created_at"], u["_seq"]))
            for u in units:
                if u["status"] in ("BUILT", "REWORK", "TEST_PASS", "SUSPECT"):
                    scrap_unit(u, "ECN_DISPOSITION")
            kits = sorted(order_kits(order["id"]),
                          key=lambda k: (k["created_at"], k["_seq"]))
            for kit in kits:
                if kit["status"] in ("PICKING", "STAGED"):
                    return_kit(kit)
            recompute_order_counters(order)
            touch(order)

    ecn["applied_at"] = now
    ecn["status"] = "APPLIED"
    touch(ecn)


# ---------------------------------------------------------------------------
# Serializers (declared fields only; internal "_"-prefixed keys never leak)
# ---------------------------------------------------------------------------

def ser_drawing(d):
    return {
        "id": d["id"],
        "drawing_number": d["drawing_number"],
        "customer_code": d["customer_code"],
        "revision": d["revision"],
        "workmanship_class": d["workmanship_class"],
        "status": d["status"],
        "released_at": fmt_datetime(d["released_at"]),
        "superseded_at": fmt_datetime(d["superseded_at"]),
        "created_at": fmt_datetime(d["created_at"]),
        "updated_at": fmt_datetime(d["updated_at"]),
        "version": d["version"],
    }


def ser_component(c):
    return {
        "id": c["id"],
        "drawing_id": c["drawing_id"],
        "find_number": c["find_number"],
        "component_type": c["component_type"],
        "mpn": c["mpn"],
        "qty_per_harness": c["qty_per_harness"],
        "supply_type": c["supply_type"],
        "unit_cost_cents": c["unit_cost_cents"],
        "created_at": fmt_datetime(c["created_at"]),
        "updated_at": fmt_datetime(c["updated_at"]),
        "version": c["version"],
    }


def ser_consigned_lot(lot):
    return {
        "id": lot["id"],
        "lot_code": lot["lot_code"],
        "owner_customer_code": lot["owner_customer_code"],
        "mpn": lot["mpn"],
        "unit_liability_cents": lot["unit_liability_cents"],
        "replacement_cost_cents": lot["replacement_cost_cents"],
        "qty_received": lot["qty_received"],
        "qty_on_hand": lot["qty_on_hand"],
        "qty_issued_open": lot["qty_issued_open"],
        "qty_consumed": lot["qty_consumed"],
        "qty_scrapped": lot["qty_scrapped"],
        "qty_returned": lot["qty_returned"],
        "book_liability_cents": lot["book_liability_cents"],
        "replacement_liability_cents": lot["replacement_liability_cents"],
        "status": lot["status"],
        "created_at": fmt_datetime(lot["created_at"]),
        "updated_at": fmt_datetime(lot["updated_at"]),
        "version": lot["version"],
    }


def ser_operator(o):
    return {
        "id": o["id"],
        "operator_name": o["operator_name"],
        "badge_no": o["badge_no"],
        "created_at": fmt_datetime(o["created_at"]),
        "updated_at": fmt_datetime(o["updated_at"]),
        "version": o["version"],
    }


def ser_certification(c):
    return {
        "id": c["id"],
        "operator_id": c["operator_id"],
        "workmanship_class": c["workmanship_class"],
        "issued_at": fmt_datetime(c["issued_at"]),
        "expires_at": fmt_datetime(c["expires_at"]),
        "revoked_at": fmt_datetime(c["revoked_at"]),
        "status": cert_status(c),
        "created_at": fmt_datetime(c["created_at"]),
        "updated_at": fmt_datetime(c["updated_at"]),
        "version": c["version"],
    }


def ser_applicator(a):
    return {
        "id": a["id"],
        "applicator_code": a["applicator_code"],
        "compatible_terminal_mpn": a["compatible_terminal_mpn"],
        "status": a["status"],
        "current_program_id": a["current_program_id"],
        "qualified_at": fmt_datetime(a["qualified_at"]),
        "created_at": fmt_datetime(a["created_at"]),
        "updated_at": fmt_datetime(a["updated_at"]),
        "version": a["version"],
    }


def ser_setup(s):
    return {
        "id": s["id"],
        "applicator_id": s["applicator_id"],
        "program_id": s["program_id"],
        "setup_operator_id": s["setup_operator_id"],
        "planned_start_at": fmt_datetime(s["planned_start_at"]),
        "planned_end_at": fmt_datetime(s["planned_end_at"]),
        "status": s["status"],
        "closed_at": fmt_datetime(s["closed_at"]),
        "created_at": fmt_datetime(s["created_at"]),
        "updated_at": fmt_datetime(s["updated_at"]),
        "version": s["version"],
    }


def ser_program(p):
    return {
        "id": p["id"],
        "program_code": p["program_code"],
        "drawing_id": p["drawing_id"],
        "applicator_id": p["applicator_id"],
        "wire_gauge_awg": p["wire_gauge_awg"],
        "wire_type": p["wire_type"],
        "cut_length_mm": p["cut_length_mm"],
        "strip_length_mm": p["strip_length_mm"],
        "terminal_mpn": p["terminal_mpn"],
        "terminal_type": p["terminal_type"],
        "min_pull_force_n": p["min_pull_force_n"],
        "status": p["status"],
        "created_at": fmt_datetime(p["created_at"]),
        "updated_at": fmt_datetime(p["updated_at"]),
        "version": p["version"],
    }


def ser_build_order(o):
    return {
        "id": o["id"],
        "order_code": o["order_code"],
        "drawing_id": o["drawing_id"],
        "drawing_revision_pinned": o["drawing_revision_pinned"],
        "workmanship_class": o["workmanship_class"],
        "qty_ordered": o["qty_ordered"],
        "material_budget_cents": o["material_budget_cents"],
        "material_spent_cents": o["material_spent_cents"],
        "qty_built": o["qty_built"],
        "qty_scrapped": o["qty_scrapped"],
        "standard_cost_cents": o["standard_cost_cents"],
        "actual_cost_cents": o["actual_cost_cents"],
        "scrap_recovery_credit_cents": o["scrap_recovery_credit_cents"],
        "status": o["status"],
        "qc_hold_return_status": o["qc_hold_return_status"],
        "held_by_program_id": o["held_by_program_id"],
        "use_as_is_flag": o["use_as_is_flag"],
        "next_unit_seq": o["next_unit_seq"],
        "created_at": fmt_datetime(o["created_at"]),
        "updated_at": fmt_datetime(o["updated_at"]),
        "version": o["version"],
    }


def ser_kit(k):
    return {
        "id": k["id"],
        "build_order_id": k["build_order_id"],
        "kit_seq": k["kit_seq"],
        "status": k["status"],
        "issues": [{
            "component_id": iss["component_id"],
            "qty_issued": iss["qty_issued"],
            "source": iss["source"],
            "consigned_lot_id": iss["consigned_lot_id"],
            "unit_cost_snapshot_cents": iss["unit_cost_snapshot_cents"],
            "issued_at": fmt_datetime(iss["issued_at"]),
            "voided": iss["voided"],
        } for iss in k["issues"]],
        "shortage_count": k["shortage_count"],
        "delivered_at": fmt_datetime(k["delivered_at"]),
        "created_at": fmt_datetime(k["created_at"]),
        "updated_at": fmt_datetime(k["updated_at"]),
        "version": k["version"],
    }


def ser_harness_unit(u):
    return {
        "id": u["id"],
        "build_order_id": u["build_order_id"],
        "serial_number": u["serial_number"],
        "drawing_revision_built": u["drawing_revision_built"],
        "built_by_operator_id": u["built_by_operator_id"],
        "status": u["status"],
        "rework_count": u["rework_count"],
        "continuity_pass": u["continuity_pass"],
        "hipot_pass": u["hipot_pass"],
        "suspect_marked_at": fmt_datetime(u["suspect_marked_at"]),
        "scrap_reason": u["scrap_reason"],
        "created_at": fmt_datetime(u["created_at"]),
        "updated_at": fmt_datetime(u["updated_at"]),
        "version": u["version"],
    }


def ser_pull_test(t):
    return {
        "id": t["id"],
        "applicator_id": t["applicator_id"],
        "program_id": t["program_id"],
        "operator_id": t["operator_id"],
        "sample_kind": t["sample_kind"],
        "measured_force_n": t["measured_force_n"],
        "min_pull_force_n_snapshot": t["min_pull_force_n_snapshot"],
        "result": t["result"],
        "tested_at": fmt_datetime(t["tested_at"]),
        "created_at": fmt_datetime(t["created_at"]),
    }


def ser_electrical_test(t):
    return {
        "id": t["id"],
        "harness_unit_id": t["harness_unit_id"],
        "test_operator_id": t["test_operator_id"],
        "test_type": t["test_type"],
        "opens_count": t["opens_count"],
        "hipot_voltage_v": t["hipot_voltage_v"],
        "dwell_seconds": t["dwell_seconds"],
        "measured_leakage_ua": t["measured_leakage_ua"],
        "leakage_limit_ua": t["leakage_limit_ua"],
        "result": t["result"],
        "tested_at": fmt_datetime(t["tested_at"]),
        "created_at": fmt_datetime(t["created_at"]),
    }


def ser_ecn(e):
    return {
        "id": e["id"],
        "ecn_code": e["ecn_code"],
        "drawing_id": e["drawing_id"],
        "from_revision": e["from_revision"],
        "to_revision": e["to_revision"],
        "wip_disposition": e["wip_disposition"],
        "status": e["status"],
        "applied_at": fmt_datetime(e["applied_at"]),
        "new_drawing_id": e["new_drawing_id"],
        "created_at": fmt_datetime(e["created_at"]),
        "updated_at": fmt_datetime(e["updated_at"]),
        "version": e["version"],
    }


def paginated(items, serializer):
    """PRD 2.3: created_at ASC default sort, limit/offset pagination."""
    ordered = sorted(items, key=lambda o: (o["created_at"], o["_seq"]))
    limit, offset = get_pagination()
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return success_list([serializer(o) for o in page], total, limit, offset)
