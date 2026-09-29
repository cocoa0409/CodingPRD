"""Derived fields and the three cascades of PRD 2.9.

Nothing in here bumps a parent's ``version`` on its own account: the route
handler decides which records a single request touched and flushes them once,
so a record's version advances by exactly 1 per request no matter how many
cascade steps ran over it.
"""

import db
from db import store
from money import ZERO, dec, q2

SIDE_A = "SIDE_A"
SIDE_B = "SIDE_B"
SIDE_C = "SIDE_C"

OPEN_COVERAGE_STATUSES = ("INCEPTED", "ACTIVE", "RUNOFF")
OPEN_CLAIM_STATUSES = (
    "NOTICED",
    "COVERAGE_ACCEPTED",
    "DEFENSE_ADVANCING",
    "SETTLEMENT_PENDING",
)

ELIGIBLE_PARTS = {
    "SECURITIES_CLASS_ACTION": (SIDE_A, SIDE_B, SIDE_C),
    "DERIVATIVE": (SIDE_A, SIDE_B),
    "REGULATORY_ENFORCEMENT": (SIDE_A, SIDE_B),
    "EMPLOYMENT_PRACTICES": (SIDE_A, SIDE_B),
    "FIDUCIARY": (SIDE_A, SIDE_B),
    "INSURED_VS_INSURED": (SIDE_A,),
}

DIC_SHARE_CAP = dec("0.40")


class Touched:
    """Records whose updated_at/version must advance once for this request."""

    def __init__(self):
        self._records = {}

    def add(self, record):
        if record is not None:
            self._records[id(record)] = record

    def add_all(self, records):
        for record in records:
            self.add(record)

    def flush(self):
        for record in self._records.values():
            db.touch(record)


# --------------------------------------------------------------------------
# Collection helpers
# --------------------------------------------------------------------------


def parts_of(policy_id):
    return db.ordered(
        [p for p in store.coverage_parts.values() if p["policy_id"] == policy_id]
    )


def part_of(policy_id, part_name):
    for part in parts_of(policy_id):
        if part["part"] == part_name:
            return part
    return None


def layers_of(policy_id):
    return db.ordered([l for l in store.layers.values() if l["policy_id"] == policy_id])


def claims_of(policy_id):
    return db.ordered([c for c in store.claims.values() if c["policy_id"] == policy_id])


def invoices_of(claim_id):
    return db.ordered(
        [i for i in store.defense_invoices.values() if i["claim_id"] == claim_id]
    )


def proposals_of(claim_id):
    return db.ordered(
        [p for p in store.settlement_proposals.values() if p["claim_id"] == claim_id]
    )


def reports_of(policy_id):
    return db.ordered(
        [r for r in store.circumstance_reports.values() if r["policy_id"] == policy_id]
    )


def endorsements_of(policy_id):
    return db.ordered(
        [e for e in store.runoff_endorsements.values() if e["policy_id"] == policy_id]
    )


def quotes_of(submission_id):
    return db.ordered(
        [q for q in store.quotes.values() if q["submission_id"] == submission_id]
    )


def terms_of(quote_id):
    return db.ordered(
        [t for t in store.exclusion_terms.values() if t["quote_id"] == quote_id]
    )


def policies_of_insured(insured_id):
    return db.ordered(
        [p for p in store.policies.values() if p["insured_id"] == insured_id]
    )


def agreed_term(quote_id, exclusion_type):
    """The AGREED term of a given exclusion type on a quote, if any."""
    for term in terms_of(quote_id):
        if term["exclusion_type"] == exclusion_type and term["status"] == "AGREED":
            return term
    return None


# --------------------------------------------------------------------------
# Insured capacity (PRD 3.4)
# --------------------------------------------------------------------------


def recompute_insured_capacity(insured):
    total = ZERO
    open_policies = 0
    for policy in policies_of_insured(insured["id"]):
        if policy["coverage_status"] not in OPEN_COVERAGE_STATUSES:
            continue
        open_policies += 1
        side_c = part_of(policy["id"], SIDE_C)
        if side_c is not None and side_c["status"] == "ACTIVE":
            total += dec(side_c["limit_usd"])
    cap = dec(insured["entity_capacity_cap_usd"])
    insured["aggregate_bound_side_c_usd"] = q2(total)
    available = cap - total
    insured["available_side_c_capacity_usd"] = q2(available if available > 0 else ZERO)
    if cap == 0:
        utilisation = ZERO
    else:
        utilisation = total / cap
    if utilisation >= 1:
        insured["capacity_posture"] = "EXHAUSTED"
    elif utilisation >= dec("0.80"):
        insured["capacity_posture"] = "RESTRICTED"
    else:
        insured["capacity_posture"] = "OPEN"
    insured["open_policy_count"] = open_policies
    return insured


# --------------------------------------------------------------------------
# Tower placement and posture (PRD 3.5)
# --------------------------------------------------------------------------


def counted_layers(policy_id):
    """Layers that count toward placement: ATTACHED or EXHAUSTED, never RELEASED."""
    return [
        l for l in layers_of(policy_id) if l["status"] in ("ATTACHED", "EXHAUSTED")
    ]


def placed_limit(layers):
    total = ZERO
    for layer in layers:
        total += dec(layer["limit_usd"]) * dec(layer["participation_pct"])
    return q2(total)


def band_map(layers):
    """attachment_point -> {limit, participation}: one entry per distinct band."""
    bands = {}
    for layer in layers:
        key = dec(layer["attachment_point_usd"])
        entry = bands.setdefault(key, {"limit": dec(layer["limit_usd"]), "participation": ZERO})
        entry["participation"] += dec(layer["participation_pct"])
    return bands


def bands_have_no_gap(bands):
    if not bands:
        return False
    keys = sorted(bands.keys())
    if keys[0] != 0:
        return False
    expected = ZERO
    for key in keys:
        if key != expected:
            return False
        expected = key + bands[key]["limit"]
    return True


def bands_fully_subscribed(bands):
    if not bands:
        return False
    return all(q2(entry["participation"]) == dec("1.00") for entry in bands.values())


def derive_tower(policy):
    layers = layers_of(policy["id"])
    counted = [l for l in layers if l["status"] in ("ATTACHED", "EXHAUSTED")]
    policy["placed_limit_usd"] = placed_limit(counted)
    bands = band_map(counted)
    if policy["coverage_status"] in ("CANCELLED", "EXPIRED"):
        policy["tower_posture"] = "RELEASED"
    elif layers and all(l["status"] == "RELEASED" for l in layers):
        policy["tower_posture"] = "RELEASED"
    elif dec(policy["total_eroded_usd"]) > 0:
        policy["tower_posture"] = "ERODED"
    elif policy["tower_sealed"]:
        policy["tower_posture"] = "SEALED"
    elif bands_have_no_gap(bands) and bands_fully_subscribed(bands):
        policy["tower_posture"] = "CONTIGUOUS"
    else:
        policy["tower_posture"] = "INCOMPLETE"
    return policy


def recompute_open_claim_count(policy):
    policy["open_claim_count"] = len(
        [c for c in claims_of(policy["id"]) if c["status"] in OPEN_CLAIM_STATUSES]
    )
    return policy


def refresh_policy_totals(policy):
    """Re-sum erosion off the coverage parts and re-derive the tower."""
    total = ZERO
    for part in parts_of(policy["id"]):
        total += dec(part["eroded_usd"])
    policy["total_eroded_usd"] = q2(total)
    policy["aggregate_remaining_usd"] = q2(
        dec(policy["shared_aggregate_limit_usd"]) - q2(total)
    )
    derive_tower(policy)
    return policy


def cascade_erosion(policy, touched):
    """Erosion flows upward: exhaust layers the erosion has reached."""
    refresh_policy_totals(policy)
    eroded = dec(policy["total_eroded_usd"])
    for layer in layers_of(policy["id"]):
        if layer["status"] == "ATTACHED" and dec(layer["attachment_point_usd"]) < eroded:
            layer["status"] = "EXHAUSTED"
            touched.add(layer)
    derive_tower(policy)
    touched.add(policy)
    return policy


def cascade_restore(policy, touched):
    """Clawback reversal: re-attach layers the restored erosion no longer reaches."""
    refresh_policy_totals(policy)
    eroded = dec(policy["total_eroded_usd"])
    for layer in layers_of(policy["id"]):
        if (
            layer["status"] == "EXHAUSTED"
            and dec(layer["attachment_point_usd"]) >= eroded
        ):
            layer["status"] = "ATTACHED"
            touched.add(layer)
    derive_tower(policy)
    touched.add(policy)
    return policy


def release_policy(policy, touched):
    """Release flows downward: parts and layers release, insured capacity returns."""
    for part in parts_of(policy["id"]):
        if part["status"] == "ACTIVE":
            part["status"] = "RELEASED"
            touched.add(part)
    for layer in layers_of(policy["id"]):
        if layer["status"] == "ATTACHED":
            layer["status"] = "RELEASED"
            touched.add(layer)
    refresh_policy_totals(policy)
    touched.add(policy)
    insured = store.insureds.get(policy["insured_id"])
    if insured is not None:
        recompute_insured_capacity(insured)
        touched.add(insured)
    return policy


def erode_part(part, amount, touched):
    """Charge an amount to a part, exhausting it when the limit is reached."""
    if amount <= 0:
        return ZERO
    part["eroded_usd"] = q2(dec(part["eroded_usd"]) + amount)
    remaining = dec(part["limit_usd"]) - dec(part["eroded_usd"])
    part["remaining_limit_usd"] = q2(remaining if remaining > 0 else ZERO)
    if dec(part["eroded_usd"]) >= dec(part["limit_usd"]):
        part["status"] = "EXHAUSTED"
        part["remaining_limit_usd"] = q2(ZERO)
    touched.add(part)
    return amount


def restore_part(part, amount, touched):
    """Reverse an amount previously charged to a part."""
    if amount <= 0:
        return
    part["eroded_usd"] = q2(dec(part["eroded_usd"]) - amount)
    if dec(part["eroded_usd"]) < 0:
        part["eroded_usd"] = q2(ZERO)
    remaining = dec(part["limit_usd"]) - dec(part["eroded_usd"])
    part["remaining_limit_usd"] = q2(remaining if remaining > 0 else ZERO)
    if part["status"] == "EXHAUSTED" and dec(part["eroded_usd"]) < dec(part["limit_usd"]):
        part["status"] = "ACTIVE"
    touched.add(part)
