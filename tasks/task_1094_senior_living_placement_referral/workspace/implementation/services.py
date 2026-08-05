"""Row lifecycle, roll-up recomputation, and cascade helpers."""
import store
import calc


# ---------------------------------------------------------------------------
# Row creation / mutation
# ---------------------------------------------------------------------------
def new_row(collection, fields, versioned=True):
    now = store.now_iso()
    row = {"id": store.new_id(), "created_at": now, "_seq": store.next_seq()}
    if versioned:
        row["updated_at"] = now
        row["version"] = 1
    row.update(fields)
    store.DB[collection][row["id"]] = row
    return row


def touch(row):
    row["updated_at"] = store.now_iso()
    if "version" in row:
        row["version"] = row["version"] + 1


# ---------------------------------------------------------------------------
# Cross-entity lookups
# ---------------------------------------------------------------------------
def assessment_for_inquiry(inquiry_id):
    for a in store.DB["assessments"].values():
        if a["inquiry_id"] == inquiry_id:
            return a
    return None


def issued_guidance_for_assessment(assessment_id):
    for g in store.DB["guidances"].values():
        if g["assessment_id"] == assessment_id and g["status"] == "ISSUED":
            return g
    return None


def active_assignment_for_inquiry(inquiry_id):
    for a in store.DB["assignments"].values():
        if a["inquiry_id"] == inquiry_id and a["status"] == "ACTIVE":
            return a
    return None


def matches_of_inquiry(inquiry_id):
    return [m for m in store.DB["matches"].values() if m["inquiry_id"] == inquiry_id]


def scheduled_tours_of_match(match_id):
    return [t for t in store.DB["tours"].values()
            if t["match_id"] == match_id and t["status"] == "SCHEDULED"]


# ---------------------------------------------------------------------------
# Roll-up recomputation (sets computed fields only; callers bump version)
# ---------------------------------------------------------------------------
def recompute_advisor_fields(advisor):
    active = [a for a in store.DB["assignments"].values()
              if a["advisor_id"] == advisor["id"] and a["status"] == "ACTIVE"]
    cap = advisor["caseload_capacity"]
    advisor["active_caseload_count"] = len(active)
    sum_priority = sum((store.DB["inquiries"][a["inquiry_id"]]["priority_score"]
                        for a in active), calc.Decimal(0))
    advisor["headcount_load_index"] = calc.headcount_index(len(active), cap)
    advisor["weighted_load_index"] = calc.weighted_index(sum_priority, cap)


def recompute_inventory_fields(inv):
    placements = [p for p in store.DB["placements"].values()
                  if p["inventory_id"] == inv["id"]]
    reserved = sum(1 for p in placements if p["residency_status"] == "PENDING_MOVE_IN")
    occupied = sum(1 for p in placements
                   if p["residency_status"] in ("MOVED_IN", "RESIDENT_CONFIRMED"))
    inv["reserved_units"] = reserved
    inv["occupied_units"] = occupied
    inv["available_units"] = max(0, inv["total_units"] - reserved - occupied)


def recompute_community_rollup(community):
    entries = [e for e in store.DB["ledger_entries"].values()
               if e["community_id"] == community["id"]]
    community["fee_balance_cents"] = sum(e["amount_cents"] for e in entries)
    surveys = [s for s in store.DB["surveys"].values()
               if s["community_id"] == community["id"]]
    community["satisfaction_survey_count"] = len(surveys)
    if surveys:
        total = sum((s["composite_score"] for s in surveys), calc.Decimal(0))
        community["avg_satisfaction_score"] = calc.rhu(total / calc.Decimal(len(surveys)), 2)
    else:
        community["avg_satisfaction_score"] = calc.Decimal("0")


def recompute_invoice_net(invoice):
    entries = [e for e in store.DB["ledger_entries"].values()
               if e["invoice_id"] == invoice["id"]
               and e["entry_type"] in ("ACCRUAL", "ADJUSTMENT", "CLAWBACK", "WRITE_OFF")]
    invoice["net_recognized_fee_cents"] = sum(e["amount_cents"] for e in entries)


def recompute_match_fit(match):
    inquiry = store.DB["inquiries"][match["inquiry_id"]]
    assessment = assessment_for_inquiry(inquiry["id"])
    community = store.DB["communities"][match["community_id"]]
    inv = _inventory_for(match["community_id"], match["care_level"])
    available = inv["available_units"] if inv else 0
    match["fit_score"] = calc.match_fit_score(
        match["care_level"], assessment["recommended_care_level"],
        assessment["affordability_ceiling_cents"], match["quoted_monthly_rate_cents"],
        community["quality_rating"], available)


def _inventory_for(community_id, care_level):
    for inv in store.DB["inventories"].values():
        if inv["community_id"] == community_id and inv["care_level"] == care_level:
            return inv
    return None


def open_inventory_for(community_id, care_level):
    for inv in store.DB["inventories"].values():
        if (inv["community_id"] == community_id and inv["care_level"] == care_level
                and inv["status"] == "OPEN"):
            return inv
    return None


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------
def append_ledger_entry(invoice, placement, community, entry_type, amount, reason):
    entry = new_row("ledger_entries", {
        "invoice_id": invoice["id"],
        "placement_id": placement["id"],
        "community_id": community["id"],
        "entry_type": entry_type,
        "amount_cents": amount,
        "balance_after_cents": 0,
        "reason": reason,
    }, versioned=False)
    # Recompute community running balance in (created_at, _seq) order.
    entries = sorted(
        (e for e in store.DB["ledger_entries"].values()
         if e["community_id"] == community["id"]),
        key=lambda e: (e["created_at"], e["_seq"]))
    running = 0
    for e in entries:
        running += e["amount_cents"]
        e["balance_after_cents"] = running
    community["fee_balance_cents"] = running
    recompute_invoice_net(invoice)
    return entry


# ---------------------------------------------------------------------------
# Cascade helpers
# ---------------------------------------------------------------------------
def withdraw_match(match, inquiry):
    match["status"] = "WITHDRAWN"
    touch(match)
    inquiry["match_count"] = inquiry["match_count"] - 1
    for tour in scheduled_tours_of_match(match["id"]):
        tour["status"] = "CANCELLED"
        tour["cancel_reason_code"] = "MATCH_WITHDRAWN"
        touch(tour)


def release_active_caseload(inquiry, reason):
    assignment = active_assignment_for_inquiry(inquiry["id"])
    if assignment is None:
        return
    assignment["status"] = "RELEASED"
    assignment["released_at"] = store.now_iso()
    assignment["release_reason"] = reason
    touch(assignment)
    advisor = store.DB["advisors"].get(assignment["advisor_id"])
    if advisor is not None:
        recompute_advisor_fields(advisor)
        touch(advisor)
