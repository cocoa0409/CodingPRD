"""Business logic: calculations (SCAFFOLD §1.3), derived-field reconciliation
(§2.10), and cascades (state machines §1.2).

Derived fields are recomputed eagerly as part of the same operation that
changes their inputs (immediate consistency). Recomputing a parent's derived
fields never bumps the parent's `version`: only direct mutations of a resource
(PATCH, state transitions, explicit system stamps, and the two OCC-guarded
writes) do (PRD §2.4, §3.5 serialization-point semantics).
"""

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from db import (
    add_days,
    add_months,
    all_rows,
    created_asc,
    db,
    fmt_ts,
    new_record,
    now,
    stamp,
    touch,
)

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
MEASURE_WEIGHT = {"POLICY": 10, "TRAINING": 10, "PHYSICAL": 15, "CONTRACTUAL": 20, "TECHNICAL": 25}
MULT_VERIFIED = Decimal("1.0")
MULT_IMPLEMENTED = Decimal("0.6")
THRESHOLD_STRONG = Decimal("70")
THRESHOLD_ADEQUATE = Decimal("40")

PTS_ESCALATED = 25
PTS_OVERDUE_NOW = 10
PTS_DISCLOSURE_EXECUTED = 5
EXPOSURE_CAP = 100
TIER_MEDIUM_MIN = 30
TIER_HIGH_MIN = 60
WINDOW_DAYS = 365

CLASS_BASE = {"INTERNAL": 10, "CONFIDENTIAL": 30, "RESTRICTED": 60, "CROWN_JEWEL": 90}
TIER_MULT = {"LOW": Decimal("1.0"), "MEDIUM": Decimal("1.25"), "HIGH": Decimal("1.5")}
MARKING_CREDIT = {"STAMPED_CONFIDENTIAL": 10, "ORAL_WITH_FOLLOWUP": 0, "ENCRYPTED_DELIVERY": 20}
ENDORSEMENT_MIN = Decimal("80")
REJECT_MIN = Decimal("95")

CLAIM_FACTOR = {
    "CEASE_AND_DESIST": Decimal("0.30"),
    "RETURN_OF_PROPERTY": Decimal("0.20"),
    "PRESERVATION": Decimal("0.15"),
}

RETURN_WINDOW_DAYS = 30
ACK_WINDOW_DAYS = 10
TRAINING_VALIDITY_DAYS = 365
REVIEW_WINDOW_DAYS = 90
EXECUTE_STALE_DAYS = 30
AUDIT_BUFFER_DAYS = 7
GRANT_MAX_DAYS = 365

CLASS_ORDER = {"INTERNAL": 0, "CONFIDENTIAL": 1, "RESTRICTED": 2, "CROWN_JEWEL": 3}
CLEARANCE_ORDER = {"STANDARD": 0, "ELEVATED": 1, "PRIVILEGED": 2}
# Clearance required per asset classification (PRD §3.4).
CLASSIFICATION_CLEARANCE = {
    "INTERNAL": "STANDARD",
    "CONFIDENTIAL": "STANDARD",
    "RESTRICTED": "ELEVATED",
    "CROWN_JEWEL": "PRIVILEGED",
}


# ---------------------------------------------------------------------------
# reasonable_measures_score + protection_posture (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
def measure_points_effective(measure):
    w = MEASURE_WEIGHT[measure["measure_type"]]
    if measure["status"] == "VERIFIED":
        return float(Decimal(w) * MULT_VERIFIED)
    if measure["status"] == "IMPLEMENTED":
        return float(Decimal(w) * MULT_IMPLEMENTED)
    return 0


def refresh_measure_derived(measure):
    measure["weight_points"] = MEASURE_WEIGHT[measure["measure_type"]]
    measure["points_effective"] = measure_points_effective(measure)


def recompute_asset_scores(asset):
    op = Decimal("0")
    doc = Decimal("0")
    for m in all_rows("measures"):
        if m["asset_id"] != asset["id"]:
            continue
        w = Decimal(m["weight_points"])
        if m["status"] == "VERIFIED":
            op += w * MULT_VERIFIED
            doc += w
        elif m["status"] == "IMPLEMENTED":
            op += w * MULT_IMPLEMENTED
    asset["score_operational"] = float(op.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    asset["score_documentary"] = float(doc.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    if op >= THRESHOLD_STRONG:
        asset["protection_posture"] = "STRONG"
    elif op >= THRESHOLD_ADEQUATE:
        asset["protection_posture"] = "ADEQUATE"
    else:
        asset["protection_posture"] = "DEFICIENT"


# ---------------------------------------------------------------------------
# counterparty_exposure_index + risk_tier (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
def recompute_counterparty_exposure(cp):
    n = now()
    window_start = n - timedelta(days=WINDOW_DAYS)
    nda_ids = {x["id"] for x in all_rows("ndas") if x["counterparty_id"] == cp["id"]}
    trailing = 0
    lifetime = 0
    for ob in all_rows("obligations"):
        if ob["nda_id"] not in nda_ids:
            continue
        if ob["status"] == "ESCALATED":
            lifetime += PTS_ESCALATED
            esc_dt = ob.get("_escalated_at_dt")
            if esc_dt is not None and window_start <= esc_dt <= n:
                trailing += PTS_ESCALATED
        elif ob["status"] == "OVERDUE":
            # Counted at 'now', no window applied.
            trailing += PTS_OVERDUE_NOW
            lifetime += PTS_OVERDUE_NOW
    for d in all_rows("disclosures"):
        if d["nda_id"] in nda_ids and d["status"] == "EXECUTED":
            lifetime += PTS_DISCLOSURE_EXECUTED
            exec_dt = d.get("_updated_dt")  # execution time == last mutation (EXECUTED is terminal)
            if exec_dt is not None and window_start <= exec_dt <= n:
                trailing += PTS_DISCLOSURE_EXECUTED
    cp["exposure_index_trailing"] = min(EXPOSURE_CAP, trailing)
    cp["exposure_index_lifetime"] = min(EXPOSURE_CAP, lifetime)
    t = cp["exposure_index_trailing"]
    if t >= TIER_HIGH_MIN:
        cp["risk_tier"] = "HIGH"
    elif t >= TIER_MEDIUM_MIN:
        cp["risk_tier"] = "MEDIUM"
    else:
        cp["risk_tier"] = "LOW"


# ---------------------------------------------------------------------------
# disclosure_risk_score (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
def risk_score_provisional(asset_classification, marking_protocol):
    val = Decimal(CLASS_BASE[asset_classification]) - Decimal(MARKING_CREDIT[marking_protocol])
    return float(val.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def risk_score_final(asset_classification, risk_tier, marking_protocol):
    val = Decimal(CLASS_BASE[asset_classification]) * TIER_MULT[risk_tier] - Decimal(
        MARKING_CREDIT[marking_protocol]
    )
    if val < 0:
        val = Decimal("0")
    if val > 100:
        val = Decimal("100")
    return float(val.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# demand_letter_damages (SCAFFOLD §1.3) — per-line round_half_up, then sum.
# ---------------------------------------------------------------------------
def demand_letter_damages(claim_lines):
    total = 0
    for line in claim_lines:
        asset = db["assets"][line["asset_id"]]
        product = Decimal(asset["exposure_estimate_cents"]) * CLAIM_FACTOR[line["claim_type"]]
        total += int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return total


# ---------------------------------------------------------------------------
# training_current (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
def recompute_training_current(emp):
    n = now()
    window_start = n - timedelta(days=TRAINING_VALIDITY_DAYS)
    has_bad = False
    has_valid_basic = False
    for t in all_rows("training_assignments"):
        if t["employee_id"] != emp["id"]:
            continue
        if t["status"] in ("OVERDUE", "ESCALATED"):
            has_bad = True
        if (
            t["module"] == "BASIC_TS"
            and t["status"] == "COMPLETED"
            and t.get("_completed_at_dt") is not None
            and window_start <= t["_completed_at_dt"] <= n
        ):
            has_valid_basic = True
    emp["training_current"] = (not has_bad) and has_valid_basic


# ---------------------------------------------------------------------------
# active_grant_count (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
def recompute_grant_count(asset):
    asset["active_grant_count"] = sum(
        1
        for g in all_rows("grants")
        if g["asset_id"] == asset["id"] and g["status"] in ("APPROVED", "PROVISIONED", "SUSPENDED")
    )


# ---------------------------------------------------------------------------
# nda_obligation_counts (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
def recompute_nda_counts(nda):
    obs = [o for o in all_rows("obligations") if o["nda_id"] == nda["id"]]
    nda["obligations_total_count"] = len(obs)
    nda["obligations_open_count"] = sum(
        1 for o in obs if o["status"] in ("PENDING", "OVERDUE", "ESCALATED")
    )
    nda["obligations_fulfilled_count"] = sum(1 for o in obs if o["status"] == "FULFILLED")
    nda["obligations_waived_count"] = sum(1 for o in obs if o["status"] == "WAIVED")


# ---------------------------------------------------------------------------
# return_obligation_anchor (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
def anchor_return_obligations(nda, anchor_dt):
    for ob in created_asc([o for o in all_rows("obligations") if o["nda_id"] == nda["id"]]):
        if (
            ob["obligation_type"] == "RETURN_OR_DESTROY"
            and ob["status"] == "PENDING"
            and ob["due_at"] is None
        ):
            due = add_days(anchor_dt, RETURN_WINDOW_DAYS)
            ob["due_at"] = fmt_ts(due)
            ob["_due_at_dt"] = due
            touch(ob)


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------
def terminate_nda(nda, terminated_dt):
    """NDA -> TERMINATED: stamp terminated_at, anchor open return obligations,
    recompute counterparty exposure. Used by the manual transition and by the
    counterparty-bar cascade."""
    nda["status"] = "TERMINATED"
    stamp(nda, "terminated_at", terminated_dt)
    touch(nda)
    anchor_return_obligations(nda, terminated_dt)
    cp = db["counterparties"].get(nda["counterparty_id"])
    if cp is not None:
        recompute_counterparty_exposure(cp)


def bar_counterparty_cascade(cp):
    """Counterparty -> BARRED: terminate every non-terminal NDA (created_at ASC),
    anchoring return obligations; reject in-flight disclosures; recompute
    exposure indexes and risk_tier (PRD §3.2)."""
    ndas = created_asc(
        [
            x
            for x in all_rows("ndas")
            if x["counterparty_id"] == cp["id"]
            and x["status"] in ("DRAFT", "SENT", "EXECUTED", "ACTIVE", "BREACH_ALLEGED")
        ]
    )
    for nda in ndas:
        terminate_nda(nda, now())
    nda_ids = {x["id"] for x in all_rows("ndas") if x["counterparty_id"] == cp["id"]}
    for d in created_asc(
        [
            x
            for x in all_rows("disclosures")
            if x["nda_id"] in nda_ids and x["status"] in ("DRAFT", "SUBMITTED", "UNDER_REVIEW")
        ]
    ):
        d["status"] = "REJECTED"
        touch(d)
    recompute_counterparty_exposure(cp)


def lapse_measure(measure):
    """Measure -> LAPSED (manual or audit cascade): zero effective points,
    recompute parent scores/posture, and if the asset's posture drops to
    DEFICIENT, return its UNDER_REVIEW disclosures (created_at ASC)."""
    measure["status"] = "LAPSED"
    touch(measure)
    refresh_measure_derived(measure)
    asset = db["assets"].get(measure["asset_id"])
    if asset is None:
        return
    posture_before = asset["protection_posture"]
    recompute_asset_scores(asset)
    if posture_before != "DEFICIENT" and asset["protection_posture"] == "DEFICIENT":
        for d in created_asc(
            [
                x
                for x in all_rows("disclosures")
                if x["asset_id"] == asset["id"] and x["status"] == "UNDER_REVIEW"
            ]
        ):
            d["status"] = "RETURNED"
            touch(d)


def retire_asset_cascade(asset):
    """Asset -> RETIRED: abandon every live measure (created_at ASC), then
    recompute both score variants (to zero) and the posture (PRD §3.1)."""
    for m in created_asc(
        [
            x
            for x in all_rows("measures")
            if x["asset_id"] == asset["id"]
            and x["status"] in ("PLANNED", "IMPLEMENTED", "VERIFIED", "LAPSED")
        ]
    ):
        m["status"] = "ABANDONED"
        touch(m)
        refresh_measure_derived(m)
    recompute_asset_scores(asset)


def compute_confidentiality_end(expiry_dt, survival_months):
    return add_months(expiry_dt, survival_months)
