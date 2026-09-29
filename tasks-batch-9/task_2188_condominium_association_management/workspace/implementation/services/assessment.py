"""SpecialAssessment derived figures, tallies, and Invariant S (PRD 3.4)."""
import clock
import db
import money


def eligible_weight(association_id):
    """Sum of interest_bp over every unit of the association with voting_eligible
    true -- a unit that never cast a ballot still sits in the denominator."""
    return sum(u["interest_bp"] for u in db.store["units"].values()
               if u["association_id"] == association_id and u["voting_eligible"])


def subject_ballots(subject_type, subject_id, opened_at, voter_kind="UNIT_OWNER"):
    """Candidate ballots: matching subject, voter_kind, cast_at in
    [opened_at, clock_now]."""
    now = clock.now()
    rows = []
    for v in db.store["votes"].values():
        if v["subject_type"] != subject_type or v["subject_id"] != subject_id:
            continue
        if v["voter_kind"] != voter_kind:
            continue
        if opened_at is not None and v["cast_at"] < opened_at:
            continue
        if v["cast_at"] > now:
            continue
        rows.append(v)
    rows.sort(key=lambda v: (v["cast_at"], v["created_at"], v["_seq"]))
    return rows


def survivors(ballots):
    """One ballot per unit_id survives: the latest by cast_at, breaking ties by
    the later created_at.  Returns (survivors_in_order, superseded)."""
    best = {}
    for v in ballots:
        uid = v.get("unit_id")
        cur = best.get(uid)
        key = (v["cast_at"], v["created_at"], v["_seq"])
        if cur is None or key > (cur["cast_at"], cur["created_at"], cur["_seq"]):
            best[uid] = v
    winners = set(id(v) for v in best.values())
    surviving = [v for v in ballots if id(v) in winners]
    superseded = [v for v in ballots if id(v) not in winners]
    return surviving, superseded


def rederive_counted(sa):
    """Re-derive `counted` on this assessment's ballots: superseded ballots become
    false, survivors take their unit's voting_eligible at THIS moment."""
    ballots = subject_ballots("SPECIAL_ASSESSMENT", sa["id"], sa.get("ballot_opened_at"))
    surviving, superseded = survivors(ballots)
    for v in superseded:
        v["counted"] = False
    for v in surviving:
        unit = db.get("units", v.get("unit_id"))
        v["counted"] = bool(unit and unit["voting_eligible"])
    return surviving


def charged_cents(sa):
    """Signed sum over this assessment's SPECIAL_ASSESSMENT_INSTALLMENT rows plus
    their REVERSAL rows, so rescinded installments net out to zero."""
    total = 0
    installment_ids = set()
    for e in db.store["ledger_entries"].values():
        if (e["entry_type"] == "SPECIAL_ASSESSMENT_INSTALLMENT"
                and e.get("special_assessment_id") == sa["id"]):
            total += e["amount_cents"]
            installment_ids.add(e["id"])
    for e in db.store["ledger_entries"].values():
        if e["entry_type"] == "REVERSAL" and e.get("reverses_entry_id") in installment_ids:
            total += e["amount_cents"]
    return total


def collected_cents(sa):
    """Sum of applied_cents recorded in payment allocations that targeted
    SPECIAL_ASSESSMENT-bucket rows of this assessment."""
    targets = set(
        e["id"] for e in db.store["ledger_entries"].values()
        if e["bucket"] == "SPECIAL_ASSESSMENT"
        and e.get("special_assessment_id") == sa["id"]
    )
    if not targets:
        return 0
    total = 0
    for e in db.store["ledger_entries"].values():
        if e["entry_type"] != "PAYMENT":
            continue
        for a in e.get("applied_allocations") or []:
            if a["target_entry_id"] in targets:
                total += a["applied_cents"]
    return total


def refunded_cents(sa):
    """Absolute sum of amount_cents over this assessment's POSTED CREDIT_REFUND rows."""
    return sum(abs(e["amount_cents"]) for e in db.store["ledger_entries"].values()
               if e["entry_type"] == "CREDIT_REFUND" and e["status"] == "POSTED"
               and e.get("special_assessment_id") == sa["id"])


def refresh_money(sa):
    sa["charged_cents"] = charged_cents(sa)
    sa["collected_cents"] = collected_cents(sa)
    sa["refunded_cents"] = refunded_cents(sa)
    return sa


def refresh_restricted_cash(association_id):
    """Invariant S: restricted_sa_cash_cents == sum(collected - refunded)."""
    assoc = db.get("associations", association_id)
    if assoc is None:
        return
    total = 0
    for sa in db.store["special_assessments"].values():
        if sa["association_id"] != association_id:
            continue
        total += sa["collected_cents"] - sa["refunded_cents"]
    assoc["restricted_sa_cash_cents"] = total


def on_payment_collection(unit, allocations):
    """Collection moves the funding dimension without any operator action."""
    touched = {}
    for a in allocations:
        if a["bucket"] != "SPECIAL_ASSESSMENT":
            continue
        target = db.get("ledger_entries", a["target_entry_id"])
        if target is None:
            continue
        sa_id = target.get("special_assessment_id")
        if not sa_id:
            continue
        touched[sa_id] = touched.get(sa_id, 0) + a["applied_cents"]
    if not touched:
        return
    assoc = db.get("associations", unit["association_id"])
    assoc_bumped = False
    for sa_id, applied in touched.items():
        sa = db.get("special_assessments", sa_id)
        if sa is None:
            continue
        refresh_money(sa)
        if sa["approval_status"] != "APPROVED":
            continue
        collected = sa["collected_cents"]
        old_status = sa["funding_status"]
        new_status = old_status
        if collected >= sa["total_amount_cents"]:
            if old_status in ("UNFUNDED", "PARTIALLY_COLLECTED"):
                new_status = "FULLY_COLLECTED"
        elif collected > 0:
            if old_status == "UNFUNDED":
                new_status = "PARTIALLY_COLLECTED"
        if new_status != old_status:
            sa["funding_status"] = new_status
            if not assoc_bumped:
                assoc_bumped = True
            db.touch(sa)
    refresh_restricted_cash(unit["association_id"])
    if assoc_bumped:
        db.touch(assoc)
