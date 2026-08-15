"""State-transition side effects and multi-hop cascades.

Conservation (PRD section 2.8): available + reserved + consumed + scrapped
always account for the received volume; release is the exact compensating
action of reserve. Every cascade-touched resource gets its own version bump
and updated_at refresh.
"""

from datetime import timedelta
from decimal import Decimal

import db
from services import derive
from util import dec, round2

# ---------------------------------------------------------------------------
# Calculation constants (SCAFFOLD section 1.3)
# ---------------------------------------------------------------------------
BF_PER_FT = {"L2X4": Decimal("0.6667"), "L2X6": Decimal("1.0"), "L2X8": Decimal("1.3333")}
BASE_WASTE = {"SPF_NO2": Decimal("0.08"), "SPF_MSR2400": Decimal("0.05"), "SYP_NO1": Decimal("0.06")}
LENGTH_SURCHARGE_16FT = Decimal("0.02")
LENGTH_SURCHARGE_20FT = Decimal("0.04")
WASTE_CAP = Decimal("0.11")
PLATES_PER_UNIT = {"FLOOR_TRUSS": 24, "ROOF_TRUSS": 28, "WALL_PANEL": 12}
UNIT_BF_PER_SPAN_FT = {"FLOOR_TRUSS": Decimal("3.5"), "ROOF_TRUSS": Decimal("4.25"), "WALL_PANEL": Decimal("1.8")}

FREIGHT_BASE_CENTS = 50000
PROVISIONAL_CENTS_PER_LB = 12
JOBSITE_CRANE_FLAT_CENTS = 25000
OVERWEIGHT_THRESHOLD_LBS = Decimal("20000")
OVERWEIGHT_CENTS_PER_LB = 18
COMPONENT_VALUE_CENTS_PER_BF = 850
CRANE_BUFFER_MINUTES = 30

OPEN_CLAIM_STATUSES = derive.OPEN_CLAIM_STATUSES


# ---------------------------------------------------------------------------
# Cut-list line math (calculation line_lumber_requirement): per-line values
# rounded half-up to 2dp BEFORE summation (pinned order).
# ---------------------------------------------------------------------------

def compute_line_fields(design, dimension, length_ft, qty):
    line_board_feet = round2(dec(qty) * dec(length_ft) * BF_PER_FT[dimension])
    if dec(length_ft) >= 20:
        surcharge = LENGTH_SURCHARGE_20FT
    elif dec(length_ft) >= 16:
        surcharge = LENGTH_SURCHARGE_16FT
    else:
        surcharge = Decimal("0")
    waste_pct = min(BASE_WASTE[design["lumber_grade"]] + surcharge, WASTE_CAP)
    required_board_feet = round2(line_board_feet * (1 + waste_pct))
    return line_board_feet, waste_pct, required_board_feet


def create_cut_list_lines(cut_list, design, line_specs):
    """Spawn PENDING line children; returns the header totals."""
    total_board_feet = Decimal("0")
    total_pieces = 0
    for spec in line_specs:
        line_bf, waste_pct, required = compute_line_fields(
            design, spec["dimension"], spec["length_ft"], spec["qty"]
        )
        line = db.new_record({
            "cut_list_id": cut_list["id"],
            "member_label": spec["member_label"],
            "dimension": spec["dimension"],
            "length_ft": dec(spec["length_ft"]),
            "qty": spec["qty"],
            "line_board_feet": line_bf,
            "waste_pct": waste_pct,
            "required_board_feet": required,
            "status": "PENDING",
        })
        db.cut_list_lines[line["id"]] = line
        total_board_feet += required  # sum of per-line rounded values
        total_pieces += spec["qty"]
    total_plates = design["quantity_required"] * PLATES_PER_UNIT[design["component_type"]]
    return total_board_feet, total_pieces, total_plates


# ---------------------------------------------------------------------------
# Inventory ledger primitives. Each returns nothing; lots mutate in place.
# ---------------------------------------------------------------------------

def lot_depleted_recheck(lot):
    """ACTIVE -> DEPLETED when available and reserved are all zero on a lot
    that actually received something (section 2.8)."""
    if lot["status"] != "ACTIVE":
        return
    if (
        lot["available_bf"] == 0
        and lot["reserved_bf"] == 0
        and lot["available_plates"] == 0
        and lot["reserved_plates"] == 0
        and (lot["received_board_feet"] + lot["received_plates"]) > 0
    ):
        lot["status"] = "DEPLETED"
        db.touch(lot)


def reservation_reserve_apply(reservation):
    lot = db.inventory_lots[reservation["lot_id"]]
    if lot["lot_kind"] == "LUMBER":
        lot["available_bf"] -= reservation["reserved_bf"]
        lot["reserved_bf"] += reservation["reserved_bf"]
    else:
        lot["available_plates"] -= reservation["reserved_plates"]
        lot["reserved_plates"] += reservation["reserved_plates"]
    db.touch(lot)


def reservation_consume_apply(reservation):
    """System-side consume (batch CUTTING cascade): reserved -> consumed."""
    lot = db.inventory_lots[reservation["lot_id"]]
    if lot["lot_kind"] == "LUMBER":
        lot["reserved_bf"] -= reservation["reserved_bf"]
        lot["consumed_bf"] += reservation["reserved_bf"]
    else:
        lot["reserved_plates"] -= reservation["reserved_plates"]
        lot["consumed_plates"] += reservation["reserved_plates"]
    reservation["status"] = "CONSUMED"
    db.touch(reservation)
    db.touch(lot)
    lot_depleted_recheck(lot)


def reservation_release_apply(reservation):
    """Release is the exact compensating action of reserve."""
    lot = db.inventory_lots[reservation["lot_id"]]
    if lot["lot_kind"] == "LUMBER":
        lot["reserved_bf"] -= reservation["reserved_bf"]
        lot["available_bf"] += reservation["reserved_bf"]
    else:
        lot["reserved_plates"] -= reservation["reserved_plates"]
        lot["available_plates"] += reservation["reserved_plates"]
    reservation["status"] = "RELEASED"
    db.touch(reservation)
    db.touch(lot)
    lot_depleted_recheck(lot)


def scrap_cut_line_waste(line):
    """CUT -> SCRAPPED waste accrual: walk CONSUMED reservations in created_at
    ASC order, moving consumed -> scrapped until required_board_feet is covered."""
    remaining = line["required_board_feet"]
    reservations = sorted(
        (r for r in db.material_reservations.values()
         if r["cut_list_line_id"] == line["id"] and r["status"] == "CONSUMED"),
        key=lambda r: r["_seq"],
    )
    for r in reservations:
        if remaining <= 0:
            break
        covered = min(remaining, r["reserved_bf"])
        lot = db.inventory_lots[r["lot_id"]]
        lot["consumed_bf"] -= covered
        lot["scrapped_bf"] += covered
        db.touch(lot)
        remaining -= covered


def scrap_line(line):
    """Line -> SCRAPPED with the side effects of its current status."""
    if line["status"] == "PENDING":
        for r in list(db.material_reservations.values()):
            if r["cut_list_line_id"] == line["id"] and r["status"] == "RESERVED":
                reservation_release_apply(r)
    elif line["status"] == "CUT":
        scrap_cut_line_waste(line)
    line["status"] = "SCRAPPED"
    db.touch(line)


# ---------------------------------------------------------------------------
# Load claim-hold release: CLAIM_HOLD -> DELIVERED once no claim of the load
# remains open.
# ---------------------------------------------------------------------------

def claim_hold_release_check(load):
    if load["status"] != "CLAIM_HOLD":
        return
    for c in db.damage_claims.values():
        if c["delivery_load_id"] == load["id"] and c["status"] in OPEN_CLAIM_STATUSES:
            return
    load["status"] = "DELIVERED"
    db.touch(load)


# ---------------------------------------------------------------------------
# Job completion check (section 3.2): runs after a load closes.
# ---------------------------------------------------------------------------

def job_completion_check(job):
    if job["status"] != "SHIPPING":
        return
    jid = job["id"]
    loads = [l for l in db.delivery_loads.values() if l["job_id"] == jid]
    if not loads:
        return
    if any(l["status"] not in ("CLOSED", "CANCELLED") for l in loads):
        return
    for b in db.production_batches.values():
        if b["job_id"] == jid and b["status"] not in ("LOADED", "CANCELLED"):
            return
    load_ids = {l["id"] for l in loads}
    for c in db.damage_claims.values():
        if c["delivery_load_id"] in load_ids and c["status"] in OPEN_CLAIM_STATUSES:
            return
    job["status"] = "COMPLETED"
    db.touch(job)


# ---------------------------------------------------------------------------
# Job cancel cascade (section 3.2)
# ---------------------------------------------------------------------------

def job_cancel_cascade(job):
    jid = job["id"]
    # Loads in {PLANNED, STAGED, LOADING} -> CANCELLED; their bundles supersede.
    for load in sorted((l for l in db.delivery_loads.values() if l["job_id"] == jid),
                       key=lambda l: l["_seq"]):
        if load["status"] in ("PLANNED", "STAGED", "LOADING"):
            bundle_statuses = ("PACKED", "LOADED") if load["status"] == "LOADING" else ("PACKED",)
            for bundle in db.bundles.values():
                if bundle["delivery_load_id"] == load["id"] and bundle["status"] in bundle_statuses:
                    bundle["status"] = "SUPERSEDED"
                    db.touch(bundle)
            load["status"] = "CANCELLED"
            db.touch(load)
    # Every batch not LOADED/CANCELLED -> CANCELLED; survivors renumbered.
    cancelled_any = False
    for batch in sorted((b for b in db.production_batches.values() if b["job_id"] == jid),
                        key=lambda b: b["_seq"]):
        if batch["status"] not in ("LOADED", "CANCELLED"):
            batch["status"] = "CANCELLED"
            db.touch(batch)
            cancelled_any = True
    if cancelled_any:
        derive.resequence_job_batches(jid)
    # Every cut list in {EXPLODED, RELEASED, RECONCILING} -> SUPERSEDED.
    job_lists = [cl for cl in db.cut_lists.values() if cl["job_id"] == jid]
    for cl in sorted(job_lists, key=lambda c: c["_seq"]):
        if cl["status"] in ("EXPLODED", "RELEASED", "RECONCILING"):
            cl["status"] = "SUPERSEDED"
            db.touch(cl)
    # Every RESERVED reservation on lines/lists of this job -> RELEASED.
    list_ids = {cl["id"] for cl in job_lists}
    line_ids = {ln["id"] for ln in db.cut_list_lines.values() if ln["cut_list_id"] in list_ids}
    for r in sorted(db.material_reservations.values(), key=lambda r: r["_seq"]):
        if r["status"] != "RESERVED":
            continue
        if r["cut_list_line_id"] in line_ids or r["cut_list_id"] in list_ids:
            reservation_release_apply(r)


# ---------------------------------------------------------------------------
# Design-change-order apply cascade (section 3.9, six hops in order)
# ---------------------------------------------------------------------------

def change_order_apply_cascade(co):
    job = db.jobs[co["job_id"]]
    old_design = db.designs[co["supersedes_design_id"]]

    # Hop 1: superseded design SEALED -> SUPERSEDED.
    old_design["status"] = "SUPERSEDED"
    db.touch(old_design)

    # Hop 2: cut lists of that design move — keyed on whether any line is CUT.
    affected_lists = [
        cl for cl in sorted(db.cut_lists.values(), key=lambda c: c["_seq"])
        if cl["design_id"] == old_design["id"] and cl["status"] in ("EXPLODED", "RELEASED")
    ]
    reconciling_lists = []
    for cl in affected_lists:
        has_cut = any(
            ln["cut_list_id"] == cl["id"] and ln["status"] == "CUT"
            for ln in db.cut_list_lines.values()
        )
        if cl["status"] == "RELEASED" and has_cut:
            cl["status"] = "RECONCILING"
            reconciling_lists.append(cl)
        else:
            cl["status"] = "SUPERSEDED"
        db.touch(cl)

    # Hop 3: RESERVED reservations on PENDING lines of those lists, or
    # plate-level on the lists themselves, -> RELEASED (lots restored).
    for cl in affected_lists:
        pending_line_ids = {
            ln["id"] for ln in db.cut_list_lines.values()
            if ln["cut_list_id"] == cl["id"] and ln["status"] == "PENDING"
        }
        for r in sorted(db.material_reservations.values(), key=lambda r: r["_seq"]):
            if r["status"] != "RESERVED":
                continue
            if r["cut_list_id"] == cl["id"] or r["cut_list_line_id"] in pending_line_ids:
                reservation_release_apply(r)

    # Hop 4: batches referencing those lists (non-LOADED, non-CANCELLED) ->
    # CANCELLED; surviving batches renumbered.
    list_ids = {cl["id"] for cl in affected_lists}
    cancelled_batch_ids = set()
    for batch in sorted((b for b in db.production_batches.values() if b["cut_list_id"] in list_ids),
                        key=lambda b: b["_seq"]):
        if batch["status"] in ("SCHEDULED", "CUTTING", "ASSEMBLY", "BUILT", "QC_PASSED",
                               "QC_FAILED", "REWORK", "STAGED"):
            batch["status"] = "CANCELLED"
            db.touch(batch)
            cancelled_batch_ids.add(batch["id"])
    if cancelled_batch_ids:
        derive.resequence_job_batches(job["id"])

    # Hop 5: PACKED bundles referencing a cancelled batch -> SUPERSEDED; the
    # owning load in {PLANNED, STAGED, LOADING} reopens to PLANNED.
    for bundle in sorted(db.bundles.values(), key=lambda b: b["_seq"]):
        if bundle["status"] == "PACKED" and bundle["production_batch_id"] in cancelled_batch_ids:
            bundle["status"] = "SUPERSEDED"
            db.touch(bundle)
            load = db.delivery_loads[bundle["delivery_load_id"]]
            if load["status"] in ("PLANNED", "STAGED", "LOADING"):
                load["status"] = "PLANNED"
                db.touch(load)
    # Hop 6: job posture is derived; reads recompute it.


# ---------------------------------------------------------------------------
# Claim rebuild cascade (section 3.8): clone the damaged bundle's batch's cut
# list with fresh PENDING lines, then create the rebuild batch.
# ---------------------------------------------------------------------------

def claim_rebuild_cascade(claim):
    bundle = db.bundles[claim["bundle_id"]]
    source_batch = db.production_batches[bundle["production_batch_id"]]
    source_list = db.cut_lists[source_batch["cut_list_id"]]
    design = db.designs[source_list["design_id"]]

    clone = db.new_record({
        "design_id": source_list["design_id"],
        "job_id": source_list["job_id"],
        "jig_setup_id": source_list["jig_setup_id"],
        "rebuild_for_claim_id": claim["id"],
        "status": "EXPLODED",
    })
    db.cut_lists[clone["id"]] = clone
    source_lines = sorted(
        (ln for ln in db.cut_list_lines.values() if ln["cut_list_id"] == source_list["id"]),
        key=lambda ln: ln["_seq"],
    )
    line_specs = [
        {"member_label": ln["member_label"], "dimension": ln["dimension"],
         "length_ft": ln["length_ft"], "qty": ln["qty"]}
        for ln in source_lines
    ]
    total_bf, total_pieces, total_plates = create_cut_list_lines(clone, design, line_specs)
    clone["total_board_feet"] = total_bf
    clone["total_pieces"] = total_pieces
    clone["total_plates"] = total_plates

    rebuild_batch = db.new_record({
        "job_id": source_list["job_id"],
        "cut_list_id": clone["id"],
        "jig_setup_id": source_batch["jig_setup_id"],
        "requested_completion_at": db.get_clock() + timedelta(days=7),
        "build_sequence_no": None,
        "is_rebuild": True,
        "source_claim_id": claim["id"],
        "status": "SCHEDULED",
    })
    db.production_batches[rebuild_batch["id"]] = rebuild_batch
    derive.resequence_job_batches(source_list["job_id"])
    return clone, rebuild_batch
