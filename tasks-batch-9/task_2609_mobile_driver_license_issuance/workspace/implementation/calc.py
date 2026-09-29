"""The seven pinned calculations of SCAFFOLD section 1.3."""

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

import derive
from store import now, profile_settings

# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------
POINTS = {
    "DOCUMENT_SCAN": {"STRONG": 250, "FAIR": 150, "WEAK": 60},
    "BIOMETRIC_MATCH": {"STRONG": 200, "FAIR": 120, "WEAK": 40},
    "KNOWLEDGE_CHECK": {"STRONG": 90, "FAIR": 50, "WEAK": 20},
    "ADDRESS_CORROBORATION": {"STRONG": 80, "FAIR": 40, "WEAK": 10},
}
REPEAT_ATTEMPT_PENALTY = 25
IAL2_MIN_SCORE = 420
IAL1_5_MIN_SCORE = 260
IAL_ORDER = {"IAL1": 0, "IAL1_5": 1, "IAL2": 2}

OVER_CEILING_WEIGHT = 12
EXCESS_ELEMENT_WEIGHT = 6
PSEUDONYM_REUSE_WEIGHT = 20
PSEUDONYM_REUSE_MIN = 3
ROLLING_WINDOW_DAYS = 30
INDEX_CEILING = 100
PROBATION_THRESHOLD = 60
SUSPEND_THRESHOLD = 90

TIER_1_MAX_QUERIES = 100
TIER_2_MAX_QUERIES = 500
TIER_2_FACTOR = Decimal("0.80")
TIER_3_FACTOR = Decimal("0.60")
PROBATION_SURCHARGE_PCT = Decimal("0.15")
VOLUME_DISCOUNT_MIN_QUERIES = 250
VOLUME_DISCOUNT_PCT = Decimal("0.10")

BASE_REISSUANCE_FEE_CENTS = 3000
EXPEDITE_FEE_CENTS = 1500
DEVICE_REBINDING_FEE_CENTS = 800
WAIVER_TIER_1_MIN_CENTS = 5300
WAIVER_TIER_2_MIN_CENTS = 3800
LOST_DEVICE_ADDITIONAL_WAIVER_PCT = Decimal("0.05")

MAX_UNBILLED_BALANCE_CENTS = 50000
CERT_RENEWAL_BUFFER_HOURS = 24

CORE_ELEMENTS = (
    "family_name",
    "given_name",
    "birth_date",
    "portrait",
    "document_number",
    "expiry_date",
    "issuing_authority",
    "driving_privileges",
    "address",
    "age_over_18",
    "age_over_21",
)


def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# 1. proofing_assurance_score
# --------------------------------------------------------------------------
def assurance_level_for(score):
    if score >= IAL2_MIN_SCORE:
        return "IAL2"
    if score >= IAL1_5_MIN_SCORE:
        return "IAL1_5"
    return "IAL1"


def _by_type(session_id):
    buckets = {}
    for item in derive.evidence_of_session(session_id):
        buckets.setdefault(item["evidence_type"], []).append(item)
    return buckets


def strict_score(session):
    buckets = _by_type(session["id"])
    raw = 0
    for evidence_type, items in buckets.items():
        # greatest captured_at; on a tie the smallest created_at (== smallest _seq)
        best = None
        for item in items:
            if best is None:
                best = item
                continue
            if item["captured_at"] > best["captured_at"]:
                best = item
            elif item["captured_at"] == best["captured_at"]:
                if (item["created_at"], item["_seq"]) < (best["created_at"], best["_seq"]):
                    best = item
        raw += POINTS[evidence_type][best["quality"]]
    penalty = REPEAT_ATTEMPT_PENALTY * max(0, session.get("submission_count", 0) - 1)
    return max(0, raw - penalty)


def optimistic_score(session):
    buckets = _by_type(session["id"])
    total = 0
    for evidence_type, items in buckets.items():
        total += max(POINTS[evidence_type][item["quality"]] for item in items)
    return total


def evidence_type_count(session):
    return len(_by_type(session["id"]))


def recompute_superseded(session_id):
    """An item is superseded when a same-type sibling was captured strictly later."""
    buckets = _by_type(session_id)
    for items in buckets.values():
        newest = max(item["captured_at"] for item in items)
        for item in items:
            item["superseded"] = item["captured_at"] < newest


# --------------------------------------------------------------------------
# 2. revocation_status_projection
# --------------------------------------------------------------------------
def revocation_status(credential):
    entries = sorted(
        derive.entries_of_credential(credential["id"]), key=lambda r: r["sequence"]
    )
    effective = "VALID"
    for entry in entries:
        status = entry["status"]
        if effective in ("REVOKED", "EXPIRED"):
            continue
        if status == "SUSPENDED":
            effective = "SUSPENDED"
        elif status == "REVOKED":
            effective = "REVOKED"
        elif status == "EXPIRED":
            effective = "EXPIRED"
        elif status == "REINSTATED":
            if effective == "SUSPENDED":
                effective = "VALID"
    if entries:
        newest = entries[-1]
        entry_sequence = newest["sequence"]
        effective_at = newest["effective_at"]
        delta = now() - effective_at
        staleness = int(delta.total_seconds() // 1)
    else:
        entry_sequence = 0
        effective_at = None
        staleness = 0
    freshness = profile_settings()["revocation_freshness_seconds"]
    return {
        "credential_id": credential["id"],
        "status": effective,
        "entry_sequence": entry_sequence,
        "effective_at": effective_at,
        "staleness_seconds": staleness,
        "is_fresh": staleness <= freshness,
    }


# --------------------------------------------------------------------------
# 3. presentation_minimization_projection
# --------------------------------------------------------------------------
def minimization(context, requested_elements, reader_app, verifier):
    if context == "AGE_ONLY":
        allow = list(profile_settings()["age_only_allowed_elements"])
    elif context == "LAW_ENFORCEMENT":
        allow = list(CORE_ELEMENTS)
    else:
        scope = list(verifier.get("purpose_scope") or [])
        allow = [e for e in (reader_app.get("requested_elements") or []) if e in scope]

    requested = list(requested_elements)
    minimized = [e for e in CORE_ELEMENTS if e in requested and e in allow]
    withheld_core = [e for e in CORE_ELEMENTS if e in requested and e not in allow]
    withheld_extra = [
        e for e in requested if e not in CORE_ELEMENTS and e not in allow
    ]
    seen = []
    for element in withheld_extra:
        if element not in seen:
            seen.append(element)
    withheld = withheld_core + seen
    age_only = context == "AGE_ONLY" and all(
        e in ("age_over_18", "age_over_21") for e in minimized
    )
    return {
        "minimized_elements": minimized,
        "withheld_elements": withheld,
        "excess_element_count": len(withheld),
        "age_attestation_only": bool(age_only),
    }


# --------------------------------------------------------------------------
# 4. credential_reissuance_settlement_cents
# --------------------------------------------------------------------------
def reissuance_settlement(prior, device_id, expedite):
    rebind_applies = device_id != prior["device_id"]
    pre_waiver_total = BASE_REISSUANCE_FEE_CENTS
    if expedite:
        pre_waiver_total += EXPEDITE_FEE_CENTS
    if rebind_applies:
        pre_waiver_total += DEVICE_REBINDING_FEE_CENTS

    if pre_waiver_total >= WAIVER_TIER_1_MIN_CENTS:
        tier_pct = Decimal("0.20")
    elif pre_waiver_total >= WAIVER_TIER_2_MIN_CENTS:
        tier_pct = Decimal("0.10")
    else:
        tier_pct = Decimal("0.00")

    if (prior["lifecycle_state"] == "SUSPENDED"
            and prior.get("suspend_reason") == "DEVICE_LOST"):
        extra_pct = LOST_DEVICE_ADDITIONAL_WAIVER_PCT
    else:
        extra_pct = Decimal("0.00")

    waiver_credit = round_half_up(Decimal(pre_waiver_total) * (tier_pct + extra_pct))
    return pre_waiver_total - waiver_credit


# --------------------------------------------------------------------------
# 5. verifier_exposure_index
# --------------------------------------------------------------------------
def _index_over(entries, ceiling):
    over_ceiling = len([e for e in entries if e["retention_days_declared"] > ceiling])
    excess = sum(e["excess_element_count"] for e in entries)
    reuse = len([e for e in entries
                 if e["pseudonym_reuse_index"] >= PSEUDONYM_REUSE_MIN])
    raw = (OVER_CEILING_WEIGHT * over_ceiling
           + EXCESS_ELEMENT_WEIGHT * excess
           + PSEUDONYM_REUSE_WEIGHT * reuse)
    return min(INDEX_CEILING, raw)


def rolling_window_entries(verifier_id):
    lower = now() - timedelta(days=ROLLING_WINDOW_DAYS)
    upper = now()
    return [e for e in derive.log_entries_of_verifier(verifier_id)
            if lower <= e["recorded_at"] <= upper]


def since_attestation_entries(verifier_id, last_attestation_at):
    entries = derive.log_entries_of_verifier(verifier_id)
    if last_attestation_at is None:
        return list(entries)
    return [e for e in entries if e["recorded_at"] >= last_attestation_at]


def effective_ceiling(verifier):
    if verifier.get("attested_max_retention_days") is not None:
        return verifier["attested_max_retention_days"]
    return verifier["retention_ceiling_days"]


def rolling_window_index(verifier):
    entries = rolling_window_entries(verifier["id"])
    return _index_over(entries, effective_ceiling(verifier)), len(entries)


def since_attestation_index(verifier, ceiling=None):
    entries = since_attestation_entries(
        verifier["id"], verifier.get("last_attestation_at")
    )
    if ceiling is None:
        ceiling = effective_ceiling(verifier)
    return _index_over(entries, ceiling), len(entries)


# --------------------------------------------------------------------------
# 6. verifier_invoice_amount_cents
# --------------------------------------------------------------------------
def invoice(verifier):
    surcharge = (PROBATION_SURCHARGE_PCT
                 if verifier["trust_status"] == "PROBATION" else Decimal("0.00"))
    apps = [a for a in derive.reader_apps_of_verifier(verifier["id"])
            if a["trust_state"] in ("LISTED", "DELISTED")]
    apps = sorted(apps, key=lambda a: (a["created_at"], a["_seq"]))
    total = 0
    line_count = 0
    for app in apps:
        queries = derive.query_count(app["id"])
        base = app["base_rate_cents"]
        if queries <= TIER_1_MAX_QUERIES:
            rate = base
        elif queries <= TIER_2_MAX_QUERIES:
            rate = round_half_up(Decimal(base) * TIER_2_FACTOR)
        else:
            rate = round_half_up(Decimal(base) * TIER_3_FACTOR)
        gross = queries * rate
        discount = (VOLUME_DISCOUNT_PCT
                    if queries >= VOLUME_DISCOUNT_MIN_QUERIES else Decimal("0.00"))
        line = round_half_up(
            Decimal(gross) * (Decimal("1") - discount) * (Decimal("1") + surcharge)
        )
        total += line
        line_count += 1
    return {
        "invoice_amount_cents": total,
        "line_count": line_count,
        "surcharge_pct": float(surcharge),
        "billable_query_balance_cents":
            derive.billable_query_balance_cents(verifier["id"]),
    }


# --------------------------------------------------------------------------
# 7. update_order_status_rollup
# --------------------------------------------------------------------------
def rollup(order):
    from store import touch

    delivery_count, delivered_count, failed_count = derive.order_counts(order["id"])
    if delivery_count == 0:
        status = "COMPLETED"
    elif delivered_count == delivery_count:
        status = "COMPLETED"
    elif delivered_count + failed_count == delivery_count:
        status = "FAILED_CLOSED"
    elif delivered_count + failed_count > 0:
        status = "PARTIALLY_DELIVERED"
    else:
        status = "OPEN"
    changed = order["status"] != status
    order["status"] = status
    if status in ("COMPLETED", "FAILED_CLOSED") and order.get("closed_at") is None:
        order["closed_at"] = now()
        changed = True
    if changed:
        touch(order)
    return order


def assurance_at_least(achieved, required):
    if achieved is None:
        return False
    return IAL_ORDER.get(achieved, -1) >= IAL_ORDER.get(required, 99)


def apply_exposure_thresholds(verifier, index):
    """Threshold triggers of SCAFFOLD 1.3 verifier_exposure_index."""
    from store import touch

    status = verifier["trust_status"]
    if index >= SUSPEND_THRESHOLD and status in ("APPROVED", "PROBATION"):
        verifier["trust_status"] = "SUSPENDED"
        verifier["probation_strike_count"] += 1
        touch(verifier)
    elif index >= PROBATION_THRESHOLD and status == "APPROVED":
        verifier["trust_status"] = "PROBATION"
        verifier["probation_strike_count"] += 1
        touch(verifier)
