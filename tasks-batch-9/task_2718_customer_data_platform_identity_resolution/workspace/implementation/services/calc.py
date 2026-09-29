"""Core calculations: data-quality scoring, confidence, match rates, rounding."""

import hashlib
import re
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------- constants

COMPONENT_ORDER = ("email_norm", "phone_norm", "loyalty_number", "name_pair", "postal_code")

COMPONENT_WEIGHTS = {
    "email_norm": Decimal("0.30"),
    "phone_norm": Decimal("0.20"),
    "loyalty_number": Decimal("0.20"),
    "name_pair": Decimal("0.15"),
    "postal_code": Decimal("0.15"),
}
WEIGHT_BASE = Decimal("1.00")
MALFORMED_PENALTY = Decimal("0.10")
DQ_RECORD_MIN = Decimal("0.60")
DQ_MIN_SAMPLE = 5
MAX_RETRY_ROUNDS = 2
HOUSEHOLD_MAX_MEMBERS = 6

CONFIDENCE_WEIGHTS = {
    "email_similarity": Decimal("0.40"),
    "phone_similarity": Decimal("0.25"),
    "name_similarity": Decimal("0.20"),
    "address_similarity": Decimal("0.15"),
}

LOYALTY_TIERS = ("NONE", "SILVER", "GOLD", "PLATINUM")
LOYALTY_ORDINAL = {tier: index for index, tier in enumerate(LOYALTY_TIERS)}

CHANNELS = ("EMAIL", "SMS", "PUSH", "DIRECT_MAIL", "ADVERTISING")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
LOYALTY_RE = re.compile(r"^LY[0-9]{8}$")
POSTAL_RE = re.compile(r"^[0-9]{5}$")
PHONE_STRIP = " +-.()"

PASS = "PASS"
FAIL = "FAIL"
ABSENT = "ABSENT"


# ---------------------------------------------------------------- rounding

def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places):
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def num(value, places):
    """Round half-up and hand back a JSON number."""
    return float(round_half_up(value, places))


# ---------------------------------------------------------- normalisation

def _blank(value):
    return value is None or not str(value).strip()


def norm_email(raw):
    if _blank(raw):
        return ABSENT, None
    text = raw.strip()
    if not EMAIL_RE.match(text):
        return FAIL, None
    return PASS, text.lower()


def norm_phone(raw):
    if _blank(raw):
        return ABSENT, None
    text = raw.strip()
    for ch in PHONE_STRIP:
        text = text.replace(ch, "")
    if len(text) == 11 and text.isdigit() and text.startswith("1"):
        return PASS, text
    return FAIL, None


def norm_loyalty(raw):
    if _blank(raw):
        return ABSENT, None
    text = raw.strip()
    if not LOYALTY_RE.match(text):
        return FAIL, None
    return PASS, text


def norm_postal(raw):
    if _blank(raw):
        return ABSENT, None
    text = raw.strip()
    if not POSTAL_RE.match(text):
        return FAIL, None
    return PASS, text


def norm_name_pair(first_raw, last_raw):
    first = None if _blank(first_raw) else first_raw.strip()
    last = None if _blank(last_raw) else last_raw.strip()
    if first is None and last is None:
        return ABSENT, None, None
    if first is not None and last is not None:
        return PASS, first, last
    return FAIL, first, last


def address_hash(raw):
    if _blank(raw):
        return None
    text = " ".join(raw.strip().lower().split())
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def evaluate_record(record):
    """Normalise one raw ingest record and classify each quality component."""
    email_state, email_norm = norm_email(record.get("email_raw"))
    phone_state, phone_norm = norm_phone(record.get("phone_raw"))
    loyalty_state, loyalty = norm_loyalty(record.get("loyalty_number"))
    postal_state, postal = norm_postal(record.get("postal_code"))
    name_state, first, last = norm_name_pair(record.get("first_name"), record.get("last_name"))
    return {
        "components": {
            "email_norm": email_state,
            "phone_norm": phone_state,
            "loyalty_number": loyalty_state,
            "name_pair": name_state,
            "postal_code": postal_state,
        },
        "email_norm": email_norm,
        "phone_norm": phone_norm,
        "loyalty_number": loyalty,
        "postal_code": postal,
        "first_name": first,
        "last_name": last,
        "address_hash": address_hash(record.get("address_line")),
    }


# ------------------------------------------------- batch_data_quality_score

def record_score(components, mode):
    passes = [name for name in COMPONENT_ORDER if components[name] == PASS]
    fails = [name for name in COMPONENT_ORDER if components[name] == FAIL]
    if mode == "UNWEIGHTED_MEAN":
        raw = Decimal(len(passes)) / Decimal(len(COMPONENT_ORDER))
    else:
        earned = sum((COMPONENT_WEIGHTS[name] for name in passes), Decimal("0"))
        raw = earned / WEIGHT_BASE
        if mode == "PENALIZED_WEIGHTED":
            raw = raw - MALFORMED_PENALTY * Decimal(len(fails))
            if raw < Decimal("0"):
                raw = Decimal("0.00")
    return round_half_up(raw, 2)


def batch_quality(evaluations, mode):
    """Score every record, then the batch. Returns a dict of batch-level figures."""
    scores = []
    valid_flags = []
    breakdown = {}
    for evaluation in evaluations:
        components = evaluation["components"]
        score = record_score(components, mode)
        scores.append(score)
        valid_flags.append(score >= DQ_RECORD_MIN)
        for name in COMPONENT_ORDER:
            if components[name] == FAIL:
                breakdown[name] = breakdown.get(name, 0) + 1
    count = len(scores)
    if count == 0:
        dq_score = Decimal("0.00")
    else:
        dq_score = round_half_up(sum(scores, Decimal("0")) / Decimal(count), 2)
    ordered = {name: breakdown[name] for name in COMPONENT_ORDER if name in breakdown}
    return {
        "record_scores": scores,
        "valid_flags": valid_flags,
        "valid_record_count": sum(1 for flag in valid_flags if flag),
        "invalid_record_count": sum(1 for flag in valid_flags if not flag),
        "dq_score": dq_score,
        "dq_failure_breakdown": ordered,
    }


# --------------------------------------------------- identity_match_confidence

def match_confidence(evidence, policy):
    raw = Decimal("0")
    base = Decimal("0")
    for name, weight in CONFIDENCE_WEIGHTS.items():
        value = evidence.get(name)
        if value is None:
            continue
        raw += weight * dec(value)
        base += weight
    if policy == "RENORMALIZE":
        if base == 0:
            return Decimal("0.0000")
        return round_half_up(raw / base, 4)
    return round_half_up(raw, 4)


def pair_evidence(left, right):
    """Derive the four similarity components for a candidate profile pair."""
    evidence = {}
    for key, field in (("email_similarity", "email_norm"), ("phone_similarity", "phone_norm")):
        a, b = left.get(field), right.get(field)
        if a is None or b is None:
            evidence[key] = None
        else:
            evidence[key] = 1.0 if a == b else 0.0
    a_named = left.get("first_name") is not None or left.get("last_name") is not None
    b_named = right.get("first_name") is not None or right.get("last_name") is not None
    if not (a_named and b_named):
        evidence["name_similarity"] = None
    else:
        comparable = [
            field for field in ("first_name", "last_name")
            if left.get(field) is not None and right.get(field) is not None
        ]
        equal = [field for field in comparable if left[field] == right[field]]
        if len(comparable) == 2 and len(equal) == 2:
            evidence["name_similarity"] = 1.0
        elif equal:
            evidence["name_similarity"] = 0.5
        else:
            evidence["name_similarity"] = 0.0
    a_addr, b_addr = left.get("address_hash"), right.get("address_hash")
    if a_addr is None or b_addr is None:
        evidence["address_similarity"] = None
    else:
        evidence["address_similarity"] = 1.0 if a_addr == b_addr else 0.0
    return evidence


# ------------------------------------------------------ activation_match_rate

def match_rates(dispatched, matched, unusable):
    if dispatched == 0:
        gross = Decimal("0.0000")
    else:
        gross = round_half_up(Decimal(matched) / Decimal(dispatched), 4)
    usable = dispatched - unusable
    if usable <= 0:
        net = Decimal("0.0000")
    else:
        net = round_half_up(Decimal(matched) / Decimal(usable), 4)
    return gross, net


def precision_estimate(confirmed, rejected):
    denominator = confirmed + rejected
    if denominator == 0:
        return Decimal("1.0000")
    return round_half_up(Decimal(confirmed) / Decimal(denominator), 4)


def pass_rate(valid_total, submitted_total):
    if submitted_total == 0:
        return Decimal("1.0000")
    return round_half_up(Decimal(valid_total) / Decimal(submitted_total), 4)
