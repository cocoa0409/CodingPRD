"""Routes: pull-list lines, assessments, fittings, damage claims,
cleaning tickets, invoices."""

from flask import Blueprint, request

from db import (DB, CONDITION_GRADES, DAMAGE_SEVERITIES, ALTERATION_TYPES,
                REVERSIBLE_ALTERATIONS, CLAIM_TYPES, LOST_GRACE_DAYS,
                new_record, touch, now_iso, today, sort_key, parse_date)
from errors import fail
from middleware import (authenticate, require_roles, scope_check, BodyReader,
                        renter_id_of_line, renter_id_of_fitting,
                        renter_id_of_claim, renter_id_of_invoice,
                        renter_id_of_pull_list)
from response import respond_object, respond_list, serialize, serialize_many
from services import (compute_late_fee, compute_damage_valuation,
                      compute_cleaning_fee, recompute_item_serviceable,
                      recompute_renter_credit, evaluate_pull_list_close,
                      evaluate_production_settle, apply_line_loss)

bp = Blueprint("routes_c", __name__)

ALL_ROLES = ["HouseAdmin", "WardrobeStaff", "RenterContact", "Accountant"]


def _line_context(line):
    reservation = DB.reservations.get(line["reservation_id"])
    production = DB.productions.get(reservation["production_id"]) if reservation else None
    item = DB.items.get(reservation["item_id"]) if reservation else None
    unit = DB.units.get(line["item_unit_id"])
    return reservation, production, item, unit


# ---------------------------------------------------------------------------
# Pull-list lines
# ---------------------------------------------------------------------------

@bp.get("/rental-house/pull-list-lines")
def list_lines():
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    recs = list(DB.lines.values())
    if role == "RenterContact":
        recs = [ln for ln in recs
                if renter_id_of_pull_list(ln["pull_list_id"]) == uid]
    for field in ("pull_list_id", "reservation_id", "item_unit_id", "status"):
        v = request.args.get(field)
        if v is not None:
            recs = [ln for ln in recs if ln[field] == v]
    recs.sort(key=sort_key)
    return respond_list(serialize_many(recs))


@bp.get("/rental-house/pull-list-lines/<lid>")
def get_line(lid):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = DB.lines.get(lid)
    if rec is None:
        fail("ERR_NOT_FOUND", "Pull-list line not found")
    scope_check(uid, role, renter_id_of_line(rec["id"]))
    return respond_object(serialize(rec))


@bp.post("/rental-house/pull-list-lines/<lid>/pick")
def pick_line(lid):
    uid, role = authenticate()
    require_roles(role, ["WardrobeStaff"])
    line = DB.lines.get(lid)
    if line is None:
        fail("ERR_NOT_FOUND", "Pull-list line not found")
    pl = DB.pull_lists.get(line["pull_list_id"])
    if line["status"] != "PENDING" or pl is None or pl["status"] != "PICKING":
        fail("ERR_INVALID_STATE", "Line is not PENDING on a PICKING pull list")
    line["status"] = "PICKED"
    touch(line)
    return respond_object(serialize(line))


@bp.post("/rental-house/pull-list-lines/<lid>/check-in")
def check_in_line(lid):
    uid, role = authenticate()
    require_roles(role, ["WardrobeStaff"])
    line = DB.lines.get(lid)
    if line is None:
        fail("ERR_NOT_FOUND", "Pull-list line not found")
    br = BodyReader()
    grade_after = br.get_enum("condition_grade_after", CONDITION_GRADES)
    severity = br.get_enum("damage_severity", DAMAGE_SEVERITIES)
    restoration_complete = br.get_bool("restoration_complete")
    # Priority 5: state
    if line["status"] != "OUT":
        fail("ERR_INVALID_STATE", "Line is not OUT")
    # Priority 10: restoration gate
    approved_fittings = [f for f in DB.fittings.values()
                         if f["pull_list_line_id"] == lid and f["status"] == "APPROVED"]
    if approved_fittings and restoration_complete is not True:
        fail("ERR_RESTORATION_INCOMPLETE",
             "Line has APPROVED fittings; restoration_complete must be true")
    br.raise_if_errors()

    reservation, production, item, unit = _line_context(line)
    cur_date = today()
    late_days = 0
    if line.get("_due_back_date") is not None:
        late_days = max(0, (cur_date - line["_due_back_date"]).days)

    # ReturnAssessment (1:1 with the checked-in line)
    assessment = new_record()
    assessment.update({
        "pull_list_line_id": lid,
        "condition_grade_before": unit["condition_grade"] if unit else None,
        "condition_grade_after": grade_after,
        "damage_severity": severity,
        "restoration_complete": restoration_complete,
        "late_days": late_days,
        "assessed_by_user_id": uid,
    })
    DB.assessments[assessment["id"]] = assessment

    # Late fee uses the unit's current grade (post-update: condition_grade_after)
    line["late_fee_cents"] = compute_late_fee(late_days, item, grade_after, production)
    line["status"] = "RETURNED" if severity == "NONE" else "DAMAGED"
    line["returned_at"] = now_iso()
    touch(line)

    # Unit transition
    if unit is not None:
        unit["condition_grade"] = grade_after
        unit["last_returned_date"] = cur_date.isoformat()
        if severity in ("NONE", "MINOR"):
            unit["status"] = "CLEANING"
        elif severity == "REPAIRABLE":
            unit["status"] = "REPAIR"
        else:  # DESTROYED
            unit["status"] = "DISPOSED"
        touch(unit)
        if severity == "DESTROYED":
            recompute_item_serviceable(item)

    # Cleaning ticket unless DESTROYED
    if severity != "DESTROYED":
        queue_depth = sum(1 for t in DB.tickets.values()
                          if t["status"] in ("QUEUED", "IN_CLEANING"))
        ticket = new_record()
        ticket.update({
            "item_unit_id": unit["id"] if unit else None,
            "status": "QUEUED",
            "requires_repair": severity == "REPAIRABLE",
            "repair_done": False,
            "queue_depth_at_creation": queue_depth,
            "cleaning_fee_cents": compute_cleaning_fee(item, queue_depth),
            "invoiced": False,
            "queued_at": now_iso(),
            "ready_at": None,
            "_production_id": production["id"] if production else None,
        })
        DB.tickets[ticket["id"]] = ticket

    # Approved fittings become RESTORED when restoration is complete
    if restoration_complete is True:
        for f in approved_fittings:
            f["status"] = "RESTORED"
            touch(f)

    # Pull-list auto-close evaluation (bubble-up to settle runs inside)
    pl = DB.pull_lists.get(line["pull_list_id"])
    if pl is not None:
        evaluate_pull_list_close(pl)
    return respond_object(serialize(line))


@bp.post("/rental-house/pull-list-lines/<lid>/report-lost")
def report_lost_line(lid):
    uid, role = authenticate()
    require_roles(role, ["WardrobeStaff"])
    line = DB.lines.get(lid)
    if line is None:
        fail("ERR_NOT_FOUND", "Pull-list line not found")
    if line["status"] != "OUT":
        fail("ERR_INVALID_STATE", "Line is not OUT")
    apply_line_loss(line)
    return respond_object(serialize(line))


@bp.get("/rental-house/pull-list-lines/<lid>/assessment")
def get_line_assessment(lid):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    line = DB.lines.get(lid)
    if line is None:
        fail("ERR_NOT_FOUND", "Pull-list line not found")
    scope_check(uid, role, renter_id_of_line(lid))
    recs = [a for a in DB.assessments.values() if a["pull_list_line_id"] == lid]
    recs.sort(key=sort_key)
    return respond_list(serialize_many(recs))


# ---------------------------------------------------------------------------
# Fitting authorizations
# ---------------------------------------------------------------------------

@bp.post("/rental-house/fitting-authorizations")
def create_fitting():
    uid, role = authenticate()
    require_roles(role, ["RenterContact"])
    br = BodyReader()
    line_id = br.get_str("pull_list_line_id")
    alteration_type = br.get_str("alteration_type")
    notes = br.get_str("notes", required=False)
    line = DB.lines.get(line_id) if line_id else None
    if line is not None:
        scope_check(uid, role, renter_id_of_line(line["id"]))
    if line_id is not None and line is None:
        fail("ERR_NOT_FOUND", "Pull-list line not found")
    # Priority 5: line state
    if line is not None and line["status"] not in ("PENDING", "PICKED", "OUT"):
        fail("ERR_INVALID_STATE",
             "Fitting authorizations require a PENDING, PICKED, or OUT line")
    # Priority 7: alteration policy gate
    if line is not None and alteration_type is not None:
        reservation, production, item, unit = _line_context(line)
        policy = item["alteration_policy"] if item else "PROHIBITED"
        if policy == "PROHIBITED":
            fail("ERR_ALTERATION_PROHIBITED",
                 "Item alteration_policy PROHIBITED blocks all alterations")
        if policy == "REVERSIBLE_ONLY" and alteration_type not in REVERSIBLE_ALTERATIONS:
            fail("ERR_ALTERATION_PROHIBITED",
                 "REVERSIBLE_ONLY allows only HEM, TAKE_IN, LET_OUT")
    br.raise_if_errors()
    if alteration_type not in ALTERATION_TYPES:
        fail("ERR_VALIDATION", "alteration_type must be one of %s"
             % ", ".join(ALTERATION_TYPES))
    rec = new_record()
    rec.update({
        "pull_list_line_id": line_id,
        "alteration_type": alteration_type,
        "notes": notes if notes is not None else "",
        "status": "REQUESTED",
        "decided_by_user_id": None,
    })
    DB.fittings[rec["id"]] = rec
    return respond_object(serialize(rec), 201)


@bp.get("/rental-house/fitting-authorizations")
def list_fittings():
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    recs = list(DB.fittings.values())
    if role == "RenterContact":
        recs = [f for f in recs
                if renter_id_of_line(f["pull_list_line_id"]) == uid]
    for field in ("pull_list_line_id", "status"):
        v = request.args.get(field)
        if v is not None:
            recs = [f for f in recs if f[field] == v]
    recs.sort(key=sort_key)
    return respond_list(serialize_many(recs))


@bp.get("/rental-house/fitting-authorizations/<fid>")
def get_fitting(fid):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = DB.fittings.get(fid)
    if rec is None:
        fail("ERR_NOT_FOUND", "Fitting authorization not found")
    scope_check(uid, role, renter_id_of_line(rec["pull_list_line_id"]))
    return respond_object(serialize(rec))


@bp.post("/rental-house/fitting-authorizations/<fid>/decide")
def decide_fitting(fid):
    uid, role = authenticate()
    require_roles(role, ["HouseAdmin"])
    rec = DB.fittings.get(fid)
    if rec is None:
        fail("ERR_NOT_FOUND", "Fitting authorization not found")
    br = BodyReader()
    decision = br.get_enum("decision", ["APPROVED", "REJECTED"])
    if rec["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE", "Fitting authorization is not REQUESTED")
    if decision == "APPROVED":
        line = DB.lines.get(rec["pull_list_line_id"])
        if line is None or line["status"] not in ("PENDING", "PICKED", "OUT"):
            fail("ERR_INVALID_STATE",
                 "Approval requires the line to be PENDING, PICKED, or OUT")
    br.raise_if_errors()
    rec["status"] = decision
    rec["decided_by_user_id"] = uid
    touch(rec)
    return respond_object(serialize(rec))


# ---------------------------------------------------------------------------
# Damage claims
# ---------------------------------------------------------------------------

@bp.post("/rental-house/damage-claims")
def create_claim():
    uid, role = authenticate()
    require_roles(role, ["WardrobeStaff"])
    br = BodyReader()
    line_id = br.get_str("pull_list_line_id")
    claim_type = br.get_enum("claim_type", CLAIM_TYPES)
    assessment_id = br.get_str("return_assessment_id", required=False)
    line = DB.lines.get(line_id) if line_id else None
    if line_id is not None and line is None:
        fail("ERR_NOT_FOUND", "Pull-list line not found")
    assessment = DB.assessments.get(assessment_id) if assessment_id else None
    if assessment_id is not None and assessment is None:
        fail("ERR_NOT_FOUND", "Return assessment not found")
    # Priority 8: one claim per line, then type/status match
    if line is not None:
        for c in DB.claims.values():
            if c["pull_list_line_id"] == line["id"]:
                fail("ERR_CLAIM_ALREADY_EXISTS",
                     "A damage claim already exists for this line")
    if line is not None and claim_type is not None:
        if claim_type == "DAMAGE":
            if line["status"] != "DAMAGED" or assessment is None \
                    or assessment["pull_list_line_id"] != line["id"]:
                fail("ERR_CLAIM_TYPE_MISMATCH",
                     "DAMAGE claims require a DAMAGED line and its return assessment")
        else:  # LOSS
            if line["status"] != "LOST" or assessment is not None:
                fail("ERR_CLAIM_TYPE_MISMATCH",
                     "LOSS claims require a LOST line and no assessment")
    br.raise_if_errors()

    reservation, production, item, unit = _line_context(line)
    renter = DB.renters.get(production["renter_id"]) if production else None
    if claim_type == "DAMAGE":
        # assessment date = the logical date the check-in assessment was created
        assessment_date = parse_date(assessment["created_at"][:10])
    else:
        assessment_date = today()
    method, value = compute_damage_valuation(claim_type, unit, item, renter,
                                             assessment_date)
    rec = new_record()
    rec.update({
        "pull_list_line_id": line_id,
        "return_assessment_id": assessment_id if claim_type == "DAMAGE" else None,
        "claim_type": claim_type,
        "valuation_method": method,
        "assessed_value_cents": value,
        "status": "DRAFT",
        "created_by_user_id": uid,
        "posted_by_user_id": None,
        "invoice_id": None,
    })
    DB.claims[rec["id"]] = rec
    return respond_object(serialize(rec), 201)


@bp.get("/rental-house/damage-claims")
def list_claims():
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    recs = list(DB.claims.values())
    if role == "RenterContact":
        recs = [c for c in recs
                if renter_id_of_line(c["pull_list_line_id"]) == uid]
    for field in ("return_assessment_id", "pull_list_line_id", "invoice_id",
                  "status"):
        v = request.args.get(field)
        if v is not None:
            recs = [c for c in recs if c[field] == v]
    recs.sort(key=sort_key)
    return respond_list(serialize_many(recs))


@bp.get("/rental-house/damage-claims/<cid>")
def get_claim(cid):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = DB.claims.get(cid)
    if rec is None:
        fail("ERR_NOT_FOUND", "Damage claim not found")
    scope_check(uid, role, renter_id_of_line(rec["pull_list_line_id"]))
    return respond_object(serialize(rec))


@bp.post("/rental-house/damage-claims/<cid>/post")
def post_claim(cid):
    uid, role = authenticate()
    require_roles(role, ["Accountant"])
    rec = DB.claims.get(cid)
    if rec is None:
        fail("ERR_NOT_FOUND", "Damage claim not found")
    if rec["status"] not in ("DRAFT", "DISPUTED"):
        fail("ERR_INVALID_STATE", "Claim is not DRAFT or DISPUTED")
    if uid == rec["created_by_user_id"]:
        fail("ERR_SOD_VIOLATION",
             "The claim creator may not post it (segregation of duties)")
    rec["status"] = "POSTED"
    rec["posted_by_user_id"] = uid
    touch(rec)
    line = DB.lines.get(rec["pull_list_line_id"])
    if line is not None:
        pl = DB.pull_lists.get(line["pull_list_id"])
        if pl is not None:
            evaluate_pull_list_close(pl)
    return respond_object(serialize(rec))


@bp.post("/rental-house/damage-claims/<cid>/dispute")
def dispute_claim(cid):
    uid, role = authenticate()
    require_roles(role, ["RenterContact"])
    rec = DB.claims.get(cid)
    if rec is None:
        fail("ERR_NOT_FOUND", "Damage claim not found")
    scope_check(uid, role, renter_id_of_line(rec["pull_list_line_id"]))
    if rec["status"] != "POSTED":
        fail("ERR_INVALID_STATE", "Claim is not POSTED")
    if rec["invoice_id"] is not None:
        fail("ERR_CLAIM_ALREADY_BILLED",
             "A claim already swept into an invoice cannot be disputed")
    rec["status"] = "DISPUTED"
    touch(rec)
    return respond_object(serialize(rec))


@bp.post("/rental-house/damage-claims/<cid>/waive")
def waive_claim(cid):
    uid, role = authenticate()
    require_roles(role, ["Accountant"])
    rec = DB.claims.get(cid)
    if rec is None:
        fail("ERR_NOT_FOUND", "Damage claim not found")
    if rec["status"] not in ("DRAFT", "DISPUTED"):
        fail("ERR_INVALID_STATE", "Claim is not DRAFT or DISPUTED")
    rec["status"] = "WAIVED"
    touch(rec)
    line = DB.lines.get(rec["pull_list_line_id"])
    if line is not None:
        pl = DB.pull_lists.get(line["pull_list_id"])
        if pl is not None:
            evaluate_pull_list_close(pl)
    return respond_object(serialize(rec))


# ---------------------------------------------------------------------------
# Cleaning tickets
# ---------------------------------------------------------------------------

@bp.get("/rental-house/units/<uid_>/cleaning-tickets")
def list_unit_tickets(uid_):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    unit = DB.units.get(uid_)
    if unit is None:
        fail("ERR_NOT_FOUND", "Unit not found")
    recs = [t for t in DB.tickets.values() if t["item_unit_id"] == uid_]
    status = request.args.get("status")
    if status is not None:
        recs = [t for t in recs if t["status"] == status]
    recs.sort(key=sort_key)
    return respond_list(serialize_many(recs))


@bp.post("/rental-house/cleaning-tickets/<tid>/advance")
def advance_ticket(tid):
    uid, role = authenticate()
    require_roles(role, ["WardrobeStaff"])
    rec = DB.tickets.get(tid)
    if rec is None:
        fail("ERR_NOT_FOUND", "Cleaning ticket not found")
    cur = rec["status"]
    if cur == "QUEUED":
        rec["status"] = "IN_CLEANING"
    elif cur == "IN_CLEANING":
        rec["status"] = "INSPECTION"
    elif cur == "INSPECTION":
        if rec["requires_repair"] and not rec["repair_done"]:
            rec["status"] = "REPAIR"
        else:
            rec["status"] = "READY"
    elif cur == "REPAIR":
        rec["status"] = "INSPECTION"
        rec["repair_done"] = True
    else:  # READY
        fail("ERR_INVALID_STATE", "Ticket is already READY")
    if rec["status"] == "READY":
        rec["ready_at"] = now_iso()
        unit = DB.units.get(rec["item_unit_id"])
        if unit is not None and unit["status"] in ("CLEANING", "REPAIR"):
            unit["status"] = "AVAILABLE"
            touch(unit)
    touch(rec)
    return respond_object(serialize(rec))


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

@bp.post("/rental-house/invoices/generate")
def generate_invoice():
    uid, role = authenticate()
    require_roles(role, ["Accountant"])
    br = BodyReader()
    production_id = br.get_str("production_id")
    production = DB.productions.get(production_id) if production_id else None
    if production_id is not None and production is None:
        fail("ERR_NOT_FOUND", "Production not found")
    br.raise_if_errors()

    swept_rental_lines, swept_late_lines = [], []
    swept_tickets, swept_claims = [], []
    rental_sum = late_sum = cleaning_sum = damage_sum = 0

    for ln in DB.lines.values():
        pl = DB.pull_lists.get(ln["pull_list_id"])
        if pl is None or pl["production_id"] != production_id:
            continue
        if ln["status"] in ("OUT", "RETURNED", "DAMAGED", "LOST") \
                and not ln["rental_invoiced"]:
            swept_rental_lines.append(ln)
            rental_sum += ln["rental_charge_cents"]
        if ln["status"] in ("RETURNED", "DAMAGED", "LOST") \
                and not ln["late_fee_invoiced"]:
            swept_late_lines.append(ln)
            late_sum += ln["late_fee_cents"]
    for t in DB.tickets.values():
        if t["_production_id"] == production_id and not t["invoiced"]:
            swept_tickets.append(t)
            cleaning_sum += t["cleaning_fee_cents"]
    for c in DB.claims.values():
        ln = DB.lines.get(c["pull_list_line_id"])
        pl = DB.pull_lists.get(ln["pull_list_id"]) if ln else None
        if pl is None or pl["production_id"] != production_id:
            continue
        if c["status"] == "POSTED" and c["invoice_id"] is None:
            swept_claims.append(c)
            damage_sum += c["assessed_value_cents"]

    if not (swept_rental_lines or swept_late_lines or swept_tickets or swept_claims):
        fail("ERR_INVOICE_EMPTY", "No unbilled charges for this production")

    rec = new_record()
    total = rental_sum + late_sum + cleaning_sum + damage_sum
    rec.update({
        "production_id": production_id,
        "status": "OPEN",
        "rental_charges_cents": rental_sum,
        "late_fee_cents": late_sum,
        "cleaning_charges_cents": cleaning_sum,
        "damage_charges_cents": damage_sum,
        "total_cents": total,
        "credited_cents": 0,
        "amount_paid_cents": 0,
        "balance_cents": total,
        "_renter_id": production["renter_id"],
        "_swept_rental_line_ids": [ln["id"] for ln in swept_rental_lines],
        "_swept_late_line_ids": [ln["id"] for ln in swept_late_lines],
        "_swept_ticket_ids": [t["id"] for t in swept_tickets],
        "_swept_claim_ids": [c["id"] for c in swept_claims],
    })
    DB.invoices[rec["id"]] = rec
    for ln in swept_rental_lines:
        ln["rental_invoiced"] = True
        touch(ln)
    for ln in swept_late_lines:
        ln["late_fee_invoiced"] = True
        touch(ln)
    for t in swept_tickets:
        t["invoiced"] = True
        touch(t)
    for c in swept_claims:
        c["invoice_id"] = rec["id"]
        touch(c)
    return respond_object(serialize(rec), 201)


@bp.get("/rental-house/invoices")
def list_invoices():
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    recs = list(DB.invoices.values())
    if role == "RenterContact":
        recs = [i for i in recs if i["_renter_id"] == uid]
    for field in ("production_id", "status"):
        v = request.args.get(field)
        if v is not None:
            recs = [i for i in recs if i[field] == v]
    recs.sort(key=sort_key)
    return respond_list(serialize_many(recs))


@bp.get("/rental-house/invoices/<iid>")
def get_invoice(iid):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = DB.invoices.get(iid)
    if rec is None:
        fail("ERR_NOT_FOUND", "Invoice not found")
    scope_check(uid, role, rec["_renter_id"])
    return respond_object(serialize(rec))


def _after_invoice_mutation(invoice):
    renter = DB.renters.get(invoice["_renter_id"])
    if renter is not None:
        recompute_renter_credit(renter)
    evaluate_production_settle(DB.productions.get(invoice["production_id"]))


@bp.post("/rental-house/invoices/<iid>/issue")
def issue_invoice(iid):
    uid, role = authenticate()
    require_roles(role, ["Accountant"])
    rec = DB.invoices.get(iid)
    if rec is None:
        fail("ERR_NOT_FOUND", "Invoice not found")
    if rec["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "Invoice is not OPEN")
    if rec["total_cents"] <= 0:
        fail("ERR_INVOICE_EMPTY", "Cannot issue a zero-total invoice")
    rec["status"] = "ISSUED"
    touch(rec)
    _after_invoice_mutation(rec)
    return respond_object(serialize(rec))


@bp.post("/rental-house/invoices/<iid>/record-payment")
def record_payment(iid):
    uid, role = authenticate()
    require_roles(role, ["Accountant"])
    rec = DB.invoices.get(iid)
    if rec is None:
        fail("ERR_NOT_FOUND", "Invoice not found")
    br = BodyReader()
    amount = br.get_int("amount_cents")
    if rec["status"] not in ("ISSUED", "PARTIALLY_PAID"):
        fail("ERR_INVALID_STATE", "Invoice is not ISSUED or PARTIALLY_PAID")
    if amount is not None:
        if amount < 1:
            fail("ERR_PAYMENT_INVALID", "amount_cents must be at least 1")
        if amount > rec["balance_cents"]:
            fail("ERR_PAYMENT_EXCEEDS_BALANCE",
                 "amount_cents exceeds the invoice balance")
    br.raise_if_errors()
    rec["amount_paid_cents"] += amount
    rec["balance_cents"] = rec["total_cents"] - rec["amount_paid_cents"]
    rec["status"] = "PAID" if rec["amount_paid_cents"] == rec["total_cents"] \
        else "PARTIALLY_PAID"
    touch(rec)
    _after_invoice_mutation(rec)
    return respond_object(serialize(rec))


@bp.post("/rental-house/invoices/<iid>/credit-note")
def credit_note(iid):
    uid, role = authenticate()
    require_roles(role, ["Accountant"])
    rec = DB.invoices.get(iid)
    if rec is None:
        fail("ERR_NOT_FOUND", "Invoice not found")
    br = BodyReader()
    amount = br.get_int("amount_cents")
    reason = br.get_str("reason", required=False)
    if rec["status"] not in ("OPEN", "ISSUED", "PARTIALLY_PAID"):
        fail("ERR_INVALID_STATE", "Invoice cannot be credited from %s" % rec["status"])
    if amount is not None:
        if amount < 1:
            fail("ERR_CREDIT_INVALID", "amount_cents must be at least 1")
        if amount > rec["balance_cents"]:
            fail("ERR_CREDIT_EXCEEDS_BALANCE",
                 "amount_cents exceeds the invoice balance")
    br.raise_if_errors()
    rec["credited_cents"] += amount
    rec["total_cents"] = rec["rental_charges_cents"] + rec["late_fee_cents"] \
        + rec["cleaning_charges_cents"] + rec["damage_charges_cents"] \
        - rec["credited_cents"]
    rec["balance_cents"] = rec["total_cents"] - rec["amount_paid_cents"]
    # A credit equal to the pre-credit balance settles the invoice
    full = (rec["balance_cents"] == 0)
    if full and rec["status"] == "OPEN":
        rec["status"] = "VOID"
        # Administrative void: swept records become unbilled again
        for lid_ in rec["_swept_rental_line_ids"]:
            ln = DB.lines.get(lid_)
            if ln is not None:
                ln["rental_invoiced"] = False
                touch(ln)
        for lid_ in rec["_swept_late_line_ids"]:
            ln = DB.lines.get(lid_)
            if ln is not None:
                ln["late_fee_invoiced"] = False
                touch(ln)
        for tid_ in rec["_swept_ticket_ids"]:
            t = DB.tickets.get(tid_)
            if t is not None:
                t["invoiced"] = False
                touch(t)
        for cid_ in rec["_swept_claim_ids"]:
            c = DB.claims.get(cid_)
            if c is not None:
                c["invoice_id"] = None
                touch(c)
    elif full:
        rec["status"] = "CREDITED"
    touch(rec)
    _after_invoice_mutation(rec)
    return respond_object(serialize(rec))
