"""Domain logic: entity construction/serialization, calculations (invoice amount,
weather envelope, rinsate, calibration, compliance score), interval overlap rules,
and cascade helpers. Implements SCAFFOLD.yaml §1.3 / PRD §2.6, §2.8, §3."""

import uuid
from datetime import timedelta
from decimal import Decimal

from store import store
from util import (now, iso, dec, round_cents, round_1dp, ceil_int, validation_error)

CATEGORIES = {"HERBICIDE", "INSECTICIDE", "FUNGICIDE"}

OBS_MAX_AGE_SECONDS = 60 * 60            # OBS_MAX_AGE_MINUTES = 60
TRAVEL_BUFFER = timedelta(minutes=30)    # TRAVEL_BUFFER_MINUTES = 30
CALIBRATION_VALID_PERIOD = timedelta(days=180)   # CALIBRATION_VALID_DAYS = 180
PASS_ERROR_PCT_MAX = Decimal("5.0")      # PASS_ERROR_PCT_MAX = 5.0
RINSE_FRACTION = Decimal("0.02")         # RINSE_FRACTION_PER_TANK = 0.02
W_MINOR = 2
W_MAJOR = 5
ROLLING_WINDOW = timedelta(days=365)     # ROLLING_DAYS
RECENCY_WINDOW = timedelta(days=90)      # RECENCY_DAYS
RECENCY_MULTIPLIER = 2
REVOKE_THRESHOLD = 10                    # REVOKE_THRESHOLD (exactly 10 revokes)
COMPLAINT_WINDOW = timedelta(days=30)

VERDICTS = {"COMPATIBLE", "CONDITIONAL", "INCOMPATIBLE"}
RINSATE_KINDS = {"FIELD_DISPOSAL", "CONTAINMENT_DISPOSAL"}
SEVERITIES = {"MINOR", "MAJOR"}


# ---------------------------------------------------------------------------
# Entity construction / mutation / serialization
# ---------------------------------------------------------------------------

DT_FIELDS = {
    "field": {"rei_until"},
    "prescription": {"valid_from", "valid_to"},
    "applicator": {"license_expires_on"},
    "equipment": {"calibration_valid_until"},
    "calibration_record": {"performed_at"},
    "weather_observation": {"observed_at"},
    "work_order": {"scheduled_start", "scheduled_end", "started_at", "completed_at"},
    "application_record": {"started_at", "completed_at"},
    "rinsate_record": {"recorded_at"},
}


def _new_base():
    t = now()
    return {"id": str(uuid.uuid4()), "created_at": t, "_seq": store.next_seq()}


def new_mutable(fields):
    """Entities carrying id/created_at/updated_at/version."""
    obj = _new_base()
    obj["updated_at"] = obj["created_at"]
    obj["version"] = 1
    obj.update(fields)
    return obj


def new_evidence(fields):
    """Append-only evidence records: id + created_at only (no updated_at/version)."""
    obj = _new_base()
    obj.update(fields)
    return obj


def touch(obj):
    """Every mutation (direct or cascade) refreshes updated_at and bumps version."""
    obj["updated_at"] = now()
    obj["version"] += 1


def serialize(kind, obj):
    dts = DT_FIELDS.get(kind, set()) | {"created_at", "updated_at"}
    out = {}
    for k, v in obj.items():
        if k.startswith("_"):
            continue
        if k in dts:
            out[k] = iso(v) if v is not None else None
        elif isinstance(v, Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Payload line validators
# ---------------------------------------------------------------------------

def validate_prescription_lines(raw):
    if not isinstance(raw, list) or len(raw) == 0:
        raise validation_error("lines must be a non-empty array")
    seen = set()
    out = []
    for item in raw:
        if not isinstance(item, dict):
            raise validation_error("each line must be an object")
        pid = item.get("product_id")
        if not isinstance(pid, str) or not pid:
            raise validation_error("line product_id must be a non-empty string")
        rate = item.get("rate_per_acre")
        if isinstance(rate, bool) or not isinstance(rate, (int, float)) or rate <= 0:
            raise validation_error("line rate_per_acre must be a positive number")
        if pid in seen:
            raise validation_error("each product appears at most once in lines")
        seen.add(pid)
        out.append({"product_id": pid, "rate_per_acre": rate})
    return out


def validate_actual_lines(raw, prescription):
    """lines must cover exactly the prescription's product set, each once, rates > 0."""
    if not isinstance(raw, list) or len(raw) == 0:
        raise validation_error("lines must be a non-empty array")
    seen = set()
    out = []
    for item in raw:
        if not isinstance(item, dict):
            raise validation_error("each line must be an object")
        pid = item.get("product_id")
        if not isinstance(pid, str) or not pid:
            raise validation_error("line product_id must be a non-empty string")
        rate = item.get("actual_rate_per_acre")
        if isinstance(rate, bool) or not isinstance(rate, (int, float)) or rate <= 0:
            raise validation_error("line actual_rate_per_acre must be a positive number")
        if pid in seen:
            raise validation_error("each product appears at most once in lines")
        seen.add(pid)
        out.append({"product_id": pid, "actual_rate_per_acre": rate})
    expected = {l["product_id"] for l in prescription["lines"]}
    if seen != expected:
        raise validation_error("lines must cover exactly the prescription's product set")
    return out


# ---------------------------------------------------------------------------
# Tank-mix compatibility
# ---------------------------------------------------------------------------

def pair_verdict(a, b):
    """Unordered pair lookup; a pair with no rule is treated as COMPATIBLE."""
    for r in store.compatibility_rules.values():
        if {r["product_a_id"], r["product_b_id"]} == {a, b}:
            return r["verdict"]
    return "COMPATIBLE"


def tank_mix_verdicts(product_ids):
    ids = list(dict.fromkeys(product_ids))
    has_incompatible = False
    has_conditional = False
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            v = pair_verdict(ids[i], ids[j])
            if v == "INCOMPATIBLE":
                has_incompatible = True
            elif v == "CONDITIONAL":
                has_conditional = True
    return has_incompatible, has_conditional


# ---------------------------------------------------------------------------
# invoice_amount (tiered_pricing): per-line half-up rounding first, then summed;
# the service fee is rounded independently.
# ---------------------------------------------------------------------------

def invoice_amount_cents(wo, customer, line_specs):
    fee = round_cents(dec(wo["acres_to_treat"]) * dec(customer["rate_per_acre_cents"]))
    total = fee
    for product, rate in line_specs:
        raw = (dec(wo["acres_to_treat"]) * dec(rate) * dec(product["unit_cost_cents"])
               * (Decimal(1) + dec(product["markup_pct"]) / Decimal(100)))
        total += round_cents(raw)
    return total


def provisional_amount_cents(wo, customer, prescription):
    specs = [(store.products[l["product_id"]], l["rate_per_acre"]) for l in prescription["lines"]]
    return invoice_amount_cents(wo, customer, specs)


def final_amount_cents(wo, customer, record):
    specs = [(store.products[l["product_id"]], l["actual_rate_per_acre"]) for l in record["lines"]]
    return invoice_amount_cents(wo, customer, specs)


# ---------------------------------------------------------------------------
# mix_weather_envelope
# ---------------------------------------------------------------------------

def latest_observation():
    obs = list(store.weather_observations.values())
    if not obs:
        return None
    return max(obs, key=lambda o: (o["observed_at"], o["created_at"], o["_seq"]))


def envelope_limits(prescription):
    prods = [store.products[l["product_id"]] for l in prescription["lines"]]
    eff_max_wind = min(p["max_wind_mph"] for p in prods)
    eff_temp_low = max(p["min_temp_f"] for p in prods)
    eff_temp_high = min(p["max_temp_f"] for p in prods)
    return eff_max_wind, eff_temp_low, eff_temp_high


def observation_fresh(obs, at=None):
    at = at or now()
    return (at - obs["observed_at"]).total_seconds() <= OBS_MAX_AGE_SECONDS


def envelope_passes(prescription, obs):
    """wind/temp/inversion only; freshness is checked separately for error mapping."""
    eff_max_wind, eff_temp_low, eff_temp_high = envelope_limits(prescription)
    if obs["wind_mph"] > eff_max_wind:            # boundary: equal passes
        return False
    if not (eff_temp_low <= obs["temp_f"] <= eff_temp_high):
        return False
    if obs["inversion_present"]:
        return False
    return True


# ---------------------------------------------------------------------------
# schedule_overlap_rules: field uses half-open [start, end); the applicator test
# pads the existing interval by the 30-minute travel buffer (padding either side
# is algebraically equivalent), so back-to-back jobs conflict.
# ---------------------------------------------------------------------------

def field_time_conflict(field_id, ns, ne, exclude_id=None):
    for w in store.work_orders.values():
        if w["id"] == exclude_id or w["field_id"] != field_id:
            continue
        if w["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        es, ee = w["scheduled_start"], w["scheduled_end"]
        if es < ne and ns < ee:
            return True
    return False


def applicator_time_conflict(applicator_id, ns, ne, exclude_id=None):
    for w in store.work_orders.values():
        if w["id"] == exclude_id or w["applicator_id"] != applicator_id:
            continue
        if w["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        es, ee = w["scheduled_start"], w["scheduled_end"]
        if (es - TRAVEL_BUFFER) < ne and ns < (ee + TRAVEL_BUFFER):
            return True
    return False


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def find_application_record(work_order_id):
    for r in store.application_records.values():
        if r["work_order_id"] == work_order_id:
            return r
    return None


def find_invoice(work_order_id):
    for inv in store.invoices.values():
        if inv["work_order_id"] == work_order_id:
            return inv
    return None


def find_open_complaint(work_order_id):
    for c in store.drift_complaints.values():
        if c["work_order_id"] == work_order_id and c["status"] in ("FILED", "INVESTIGATING"):
            return c
    return None


# ---------------------------------------------------------------------------
# Cascades (§2.8): each touched resource gets its own updated_at + version bump
# ---------------------------------------------------------------------------

def revert_scheduled_work_orders(applicator_id=None, equipment_id=None):
    """SCHEDULED -> DRAFT with assignment/window cleared (applicator suspension/
    revocation or equipment CALIBRATION_DUE)."""
    for w in store.work_orders.values():
        if w["status"] != "SCHEDULED":
            continue
        if applicator_id is not None and w["applicator_id"] != applicator_id:
            continue
        if equipment_id is not None and w["equipment_id"] != equipment_id:
            continue
        w["status"] = "DRAFT"
        w["applicator_id"] = None
        w["equipment_id"] = None
        w["scheduled_start"] = None
        w["scheduled_end"] = None
        w["uses_adjuvant"] = False
        w["estimated_total_cents"] = None
        touch(w)


def severity_weight(severity):
    return W_MAJOR if severity == "MAJOR" else W_MINOR
