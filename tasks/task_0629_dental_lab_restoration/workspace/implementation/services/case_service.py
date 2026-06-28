"""Case lifecycle state machine and its cascades (scaffold §1.2, PRD §3.3-§3.8)."""
import clock
import db
import errors
import lookups
from errors import err
from services import calculations as calc


def _billable_units(case_id):
    return [u for u in lookups.case_units(case_id) if u["is_billable"]]


def _build_invoice_amounts(case, is_final):
    """Compute invoice amounts from the case's billable units (PRD §3.3 / §3.6)."""
    units = _billable_units(case["id"])
    subtotal = 0
    for u in units:
        rest = db.restorations[u["restoration_id"]]
        subtotal += rest["unit_price_cents"]
    doctor = db.doctors[case["doctor_id"]]
    return calc.invoice_total(
        subtotal_cents=subtotal,
        is_rush=case["is_rush"],
        completed_case_count=doctor["completed_case_count"],
        is_final=is_final,
        sla_breached=case["sla_breached"],
    )


# =====================================================================
# INTAKE -> DESIGN (submit)
# =====================================================================
def submit(case):
    """POST /cases/{id}/submit — INTAKE -> DESIGN (PRD §3.3)."""
    if case["status"] != "INTAKE":
        raise err(errors.ERR_INVALID_STATE, "Case is not in INTAKE.")

    restorations = lookups.case_restorations(case["id"])

    # ERR_EMPTY_FABRICATION: no restoration carrying at least one unit (priority 10).
    if not any(r["unit_count"] >= 1 for r in restorations):
        raise err(errors.ERR_EMPTY_FABRICATION, "Case has no billable fabrication units.")

    # Precondition: every restoration references a currently active material.
    for r in restorations:
        material = db.materials[r["material_id"]]
        if not material["is_active"]:
            raise err(errors.ERR_MATERIAL_INACTIVE, "Restoration references an inactive material.")

    # --- Side effects, applied together (PRD §3.3) ---
    # 1. price each restoration (per-unit round) BEFORE materializing.
    for r in restorations:
        material = db.materials[r["material_id"]]
        r["unit_price_cents"] = calc.unit_price_cents(
            material["base_unit_price_cents"], r["restoration_type"]
        )
        db.touch(r)

    # 2. create unit_count fabrication units per restoration.
    billable_total = 0
    for r in restorations:
        for _ in range(r["unit_count"]):
            unit = db.stamp_create({
                "id": db.new_id(),
                "restoration_id": r["id"],
                "remade_from_unit_id": None,
                "status": "QUEUED",
                "is_billable": True,
            })
            db.fabrication_units[unit["id"]] = unit
        billable_total += r["unit_count"]

    # 3. billable_unit_count.
    case["billable_unit_count"] = billable_total

    # 4. scheduled_start_at = current logical clock.
    case["scheduled_start_at"] = clock.now()

    # 5. turnaround promise.
    rtypes = [r["restoration_type"] for r in restorations]
    case["promised_ready_at"] = calc.turnaround_promise(
        case["scheduled_start_at"], rtypes, case["is_rush"]
    )

    # 6. one PROVISIONAL invoice; populate amounts (provisional variant).
    amounts = _build_invoice_amounts(case, is_final=False)
    inv = db.stamp_create({
        "id": db.new_id(),
        "case_id": case["id"],
        "kind": "PROVISIONAL",
        "billing_status": "DRAFT",
        "delivery_status": "PENDING",
        **amounts,
    })
    db.invoices[inv["id"]] = inv

    case["status"] = "DESIGN"
    db.touch(case)
    return case


# =====================================================================
# DESIGN/REVISION -> FABRICATION (start-fabrication)
# =====================================================================
def start_fabrication(case):
    """POST /cases/{id}/start-fabrication — DESIGN/REVISION -> FABRICATION (PRD §3.5).

    From REVISION the case lands back in DESIGN (re-entry leg of the cycle).
    """
    status = case["status"]
    if status not in ("DESIGN", "REVISION"):
        raise err(errors.ERR_INVALID_STATE, "Case is not in DESIGN or REVISION.")

    # Precondition: every QUEUED unit has a SCHEDULED or DONE MillJob.
    for u in lookups.case_units(case["id"]):
        if u["status"] != "QUEUED":
            continue
        jobs = lookups.unit_mill_jobs(u["id"])
        if not any(j["status"] in ("SCHEDULED", "DONE") for j in jobs):
            raise err(errors.ERR_INVALID_STATE,
                      "A queued unit lacks a SCHEDULED or DONE mill job.")

    if status == "REVISION":
        case["status"] = "DESIGN"
    else:
        case["status"] = "FABRICATION"
    db.touch(case)
    return case


# =====================================================================
# FABRICATION -> TRY_IN (ready-tryin)
# =====================================================================
def ready_tryin(case):
    """POST /cases/{id}/ready-tryin — FABRICATION -> TRY_IN (PRD §3.5)."""
    if case["status"] != "FABRICATION":
        raise err(errors.ERR_INVALID_STATE, "Case is not in FABRICATION.")

    # Precondition: every billable unit is MILLED.
    for u in _billable_units(case["id"]):
        if u["status"] != "MILLED":
            raise err(errors.ERR_INVALID_STATE, "Not every billable unit is MILLED.")

    case["status"] = "TRY_IN"
    db.touch(case)
    return case


# =====================================================================
# TRY_IN -> SHIPPED / REVISION (tryin-verdict)
# =====================================================================
def tryin_verdict(case, verdict, expected_case_version, revise_restoration_ids):
    """POST /cases/{id}/tryin-verdict (PRD §3.5, §3.6). OCC on Case.version.

    Validation order (PRD §2.9): state (must be in TRY_IN) precedes OCC precedes
    business checks.
    """
    # state precondition first.
    if case["status"] != "TRY_IN":
        raise err(errors.ERR_INVALID_STATE, "Case is not in TRY_IN.")

    # OCC check (priority 6) before business checks.
    if expected_case_version != case["version"]:
        raise err(errors.ERR_STALE_CASE_VERSION, "expected_case_version is stale.")

    if verdict == "REVISE":
        return _verdict_revise(case, revise_restoration_ids)
    return _verdict_accept(case)


def _verdict_revise(case, revise_restoration_ids):
    # ERR_MAX_REVISIONS_EXCEEDED (priority 11): revision_count < MAX_REVISIONS.
    if case["revision_count"] >= calc.MAX_REVISIONS:
        raise err(errors.ERR_MAX_REVISIONS_EXCEEDED, "Maximum revisions reached.")

    # On first verdict each MILLED unit -> TRIED_IN, then revise sends them QUEUED.
    # Net: each milled billable unit goes back to QUEUED for re-milling.
    for u in _billable_units(case["id"]):
        if u["status"] == "MILLED":
            u["status"] = "QUEUED"
            db.touch(u)

    # Create a ShadeRecord (matched=false) for each flagged restoration.
    flagged = revise_restoration_ids or []
    for rid in flagged:
        rest = db.restorations[rid]
        sr = db.stamp_create({
            "id": db.new_id(),
            "restoration_id": rest["id"],
            "shade_code": rest["requested_shade"],
            "matched": False,
        })
        db.shade_records[sr["id"]] = sr

    case["revision_count"] += 1
    case["status"] = "REVISION"
    db.touch(case)
    return case


def _verdict_accept(case):
    # Precondition: every billable unit is in PASSED or MILLED.
    units = _billable_units(case["id"])
    for u in units:
        if u["status"] not in ("PASSED", "MILLED"):
            raise err(errors.ERR_INVALID_STATE,
                      "Not every billable unit is PASSED or MILLED.")

    # Precondition: case has a RouteStop in PLANNED.
    stops = lookups.case_route_stops(case["id"])
    if not any(s["status"] == "PLANNED" for s in stops):
        raise err(errors.ERR_INVALID_STATE, "Case has no PLANNED route stop.")

    # Promote every billable MILLED unit to PASSED.
    for u in units:
        if u["status"] == "MILLED":
            u["status"] = "PASSED"
            db.touch(u)

    # shipped_at = current logical clock.
    case["shipped_at"] = clock.now()
    # sla_breached = shipped_at > promised_ready_at (strict >).
    case["sla_breached"] = case["shipped_at"] > case["promised_ready_at"]

    # Flip invoice to FINAL and recompute (final variant).
    inv = lookups.case_invoice(case["id"])
    inv["kind"] = "FINAL"
    amounts = _build_invoice_amounts(case, is_final=True)
    inv.update(amounts)

    # If breached: issue CreditMemo and bump doctor ledger.
    if case["sla_breached"] and inv["sla_credit_cents"] > 0:
        memo = db.stamp_create({
            "id": db.new_id(),
            "case_id": case["id"],
            "invoice_id": inv["id"],
            "amount_cents": inv["sla_credit_cents"],
            "status": "ISSUED",
        })
        db.credit_memos[memo["id"]] = memo
        doctor = db.doctors[case["doctor_id"]]
        doctor["account_credit_cents"] += memo["amount_cents"]
        db.touch(doctor)

    # billing_status=ISSUED, delivery_status=IN_TRANSIT.
    inv["billing_status"] = "ISSUED"
    inv["delivery_status"] = "IN_TRANSIT"
    db.touch(inv)

    case["status"] = "SHIPPED"
    db.touch(case)
    return case


# =====================================================================
# SHIPPED -> DELIVERED (confirm-delivery)
# =====================================================================
def confirm_delivery(case):
    """POST /cases/{id}/confirm-delivery — SHIPPED -> DELIVERED (PRD §3.7)."""
    if case["status"] != "SHIPPED":
        raise err(errors.ERR_INVALID_STATE, "Case is not in SHIPPED.")

    # Precondition: case has a RouteStop in COMPLETED.
    stops = lookups.case_route_stops(case["id"])
    if not any(s["status"] == "COMPLETED" for s in stops):
        raise err(errors.ERR_INVALID_STATE, "Case has no COMPLETED route stop.")

    inv = lookups.case_invoice(case["id"])
    # delivery_status -> DELIVERED, allowed only while billing_status in {ISSUED, PAID}.
    if inv["billing_status"] not in ("ISSUED", "PAID"):
        raise err(errors.ERR_INVALID_STATE,
                  "Invoice billing_status must be ISSUED or PAID to deliver.")
    inv["delivery_status"] = "DELIVERED"
    db.touch(inv)

    case["status"] = "DELIVERED"
    db.touch(case)

    # Recompute doctor.completed_case_count (+1 for this DELIVERED case).
    doctor = db.doctors[case["doctor_id"]]
    doctor["completed_case_count"] = sum(
        1 for c in db.cases.values()
        if c["doctor_id"] == doctor["id"] and c["status"] == "DELIVERED"
    )
    db.touch(doctor)
    return case


# =====================================================================
# INTAKE/DESIGN -> CANCELLED (cancel)
# =====================================================================
def cancel(case):
    """POST /cases/{id}/cancel — INTAKE or DESIGN -> CANCELLED (PRD §3.8)."""
    status = case["status"]
    if status not in ("INTAKE", "DESIGN"):
        raise err(errors.ERR_INVALID_STATE, "Case cannot be cancelled from its current state.")

    if status == "DESIGN":
        # Cascade: cancel every SCHEDULED mill job of the case's units (frees interval).
        for u in lookups.case_units(case["id"]):
            for j in lookups.unit_mill_jobs(u["id"]):
                if j["status"] == "SCHEDULED":
                    j["status"] = "CANCELLED"
                    db.touch(j)

    # Void the DRAFT invoice (requires it to currently be DRAFT).
    inv = lookups.case_invoice(case["id"])
    if inv is not None and inv["billing_status"] == "DRAFT":
        inv["billing_status"] = "VOID"
        db.touch(inv)

    case["status"] = "CANCELLED"
    db.touch(case)
    return case
