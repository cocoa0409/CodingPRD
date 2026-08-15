"""assessed_dues calculation (scaffold calculations[0]).

Rate resolution fallback chain:
  bp   = classification.dues_percent_bp ?? local.default_dues_percent_bp
  flat = classification.flat_dues_cents ?? local.default_flat_dues_cents
  lo   = classification.min_monthly_dues_cents
  hi   = classification.max_monthly_dues_cents (null = uncapped)
Branch on local.dues_method:
  FLAT_RATE:           base = flat
  PERCENTAGE_OF_GROSS: base = round_half_up(gross * bp / 10000)
Clamp: assessed = max(base, lo); if hi is not null: assessed = min(assessed, hi)

Precision: integer cents; round_half_up applied exactly once, at the percent
multiplication. gross and bp are non-negative integers, so
(gross * bp + 5000) // 10000 is exact round-half-up.
"""
import db


def resolve_rates(local, classification):
    bp = classification.get("dues_percent_bp")
    if bp is None:
        bp = local["default_dues_percent_bp"]
    flat = classification.get("flat_dues_cents")
    if flat is None:
        flat = local["default_flat_dues_cents"]
    lo = classification["min_monthly_dues_cents"]
    hi = classification.get("max_monthly_dues_cents")
    return bp, flat, lo, hi


def compute_assessed(local, classification, gross_wages_cents):
    """Returns (assessed_cents, rate_bp_applied, flat_applied_cents,
    min_applied_cents, max_applied_cents)."""
    bp, flat, lo, hi = resolve_rates(local, classification)
    if local["dues_method"] == "FLAT_RATE":
        base = flat
        rate_bp_applied = None
        flat_applied = flat
    else:
        base = (gross_wages_cents * bp + 5000) // 10000  # round half up
        rate_bp_applied = bp
        flat_applied = None
    assessed = max(base, lo)
    if hi is not None:
        assessed = min(assessed, hi)
    return assessed, rate_bp_applied, flat_applied, lo, hi


def floor_dues(local, classification):
    """Dues at a zero wage base per objector_rebate's projected variant:
    FLAT_RATE -> resolved flat dues; PERCENTAGE_OF_GROSS -> the floor
    min_monthly_dues_cents (PRD states these literally)."""
    _, flat, lo, _ = resolve_rates(local, classification)
    if local["dues_method"] == "FLAT_RATE":
        return flat
    return lo


def member_config(member):
    """Return (local, classification) for a member."""
    local = db.store.locals[member["local_id"]]
    classification = db.store.classifications[member["classification_id"]]
    return local, classification


def provisional_wage_base(member_id, run_period):
    """Provisional variant: gross of the member's most recent FINAL assessment
    from an earlier period, else 0."""
    best = None
    for a in db.store.assessments.values():
        if a["member_id"] != member_id or a["status"] != "FINAL":
            continue
        if a["period"] >= run_period:
            continue
        if best is None or a["period"] > best["period"]:
            best = a
    return best["gross_wages_cents"] if best else 0


def create_assessment(member, period, gross, status):
    """Create a DuesAssessment pinned at computation time. Caller posts the
    ASSESSMENT_CHARGE entry."""
    local, classification = member_config(member)
    assessed, rate_bp, flat_applied, lo, hi = compute_assessed(
        local, classification, gross)
    ts = db.fmt_ts(db.now())
    assessment = {
        "id": __import__("utils").new_id(),
        "member_id": member["id"],
        "period": period,
        "status": status,
        "gross_wages_cents": gross,
        "assessed_cents": assessed,
        "rate_bp_applied": rate_bp,
        "flat_applied_cents": flat_applied,
        "min_applied_cents": lo,
        "max_applied_cents": hi,
        "finalized_at": ts if status == "FINAL" else None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.store.next_seq(),
    }
    db.store.assessments[assessment["id"]] = assessment
    return assessment


def finalize_assessment(assessment, gross):
    """PROVISIONAL -> FINAL with the final variant wage base. Posts the
    compensating delta entry when the amount moves. Returns the delta entry
    (or None when delta == 0)."""
    from services import ledger as ledger_svc
    member = db.store.members[assessment["member_id"]]
    local, classification = member_config(member)
    assessed, rate_bp, flat_applied, lo, hi = compute_assessed(
        local, classification, gross)
    old = assessment["assessed_cents"]
    assessment["assessed_cents"] = assessed
    assessment["gross_wages_cents"] = gross
    assessment["rate_bp_applied"] = rate_bp
    assessment["flat_applied_cents"] = flat_applied
    assessment["min_applied_cents"] = lo
    assessment["max_applied_cents"] = hi
    assessment["status"] = "FINAL"
    assessment["finalized_at"] = db.fmt_ts(db.now())
    db.touch(assessment)
    delta = assessed - old
    entry = None
    if delta > 0:
        entry = ledger_svc.post_entry(
            member["id"], "SUPPLEMENTAL_CHARGE", delta, assessment["period"],
            memo="finalization delta for assessment %s" % assessment["id"],
            assessment_id=assessment["id"])
    elif delta < 0:
        entry = ledger_svc.post_entry(
            member["id"], "ADJUSTMENT_CREDIT", delta, assessment["period"],
            memo="finalization delta for assessment %s" % assessment["id"],
            assessment_id=assessment["id"])
    return entry
