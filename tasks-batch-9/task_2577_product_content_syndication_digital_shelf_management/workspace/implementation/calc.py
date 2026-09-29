"""Calculation rules (PRD 2.7, 3.4, 3.6, 3.7, 3.9)."""
import re
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, localcontext
from fractions import Fraction

from store import db, in_order

# ---------------------------------------------------------------- constants
IMAGE_WEIGHT = Fraction(20)
CERTIFIED_WEIGHT = Decimal("0.60")
ACCURACY_WEIGHT = Decimal("0.40")
ACCURACY_CAP_WHEN_NOT_OK = Decimal("60.00")
PENALTY_TIER_1_2 = Decimal("5")
PENALTY_TIER_3_5 = Decimal("12")
PENALTY_TIER_6_PLUS = Decimal("25")
LIVE_ENHANCED_BONUS = Decimal("5")

HEALTH_ACCURACY_WEIGHT = Decimal("0.45")
HEALTH_RANK_WEIGHT = Decimal("0.25")
HEALTH_AVAILABILITY_WEIGHT = Decimal("0.20")
HEALTH_RATING_WEIGHT = Decimal("0.10")
RANK_DECAY_PER_POSITION = Decimal("5")
HEALTH_ALERT_THRESHOLD = Decimal("60.00")

COMPLETENESS_GATE = Decimal("85.00")
CONTENT_DRIFT_THRESHOLD = Decimal("85.00")
QUALITY_SPLIT_ACCURACY_THRESHOLD = Decimal("90.00")

PER_SKU_RATE_CENTS = 2500
RUSH_WINDOW_HOURS = 24
RUSH_TIER_BOUNDARY_CENTS = 20000

PROHIBITED_CLAIM_TOKENS = ("cures", "fda approved", "100% guaranteed")

SCORING_LEVELS = ("REQUIRED", "RECOMMENDED")
IMAGE_ROLES = ("HERO_IMAGE", "SECONDARY_IMAGE")
HOLDING_JOB_STATES = ("QUEUED", "TRANSMITTED")
HEALTH_SYNDICATION_STATES = ("LIVE", "ERROR_HOLD")
ACTIVE_DEPLOYMENT_STATES = ("PENDING_RETAILER_APPROVAL", "LIVE")
OPEN_ALERT_STATES = ("OPEN", "ACKNOWLEDGED")

ZERO2 = Decimal("0.00")


# ---------------------------------------------------------------- rounding
def _to_decimal(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, Fraction):
        with localcontext() as ctx:
            ctx.prec = 60
            return Decimal(value.numerator) / Decimal(value.denominator)
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round2(value):
    """round_half_up to 2 decimal places."""
    return _to_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round0(value):
    """round_half_up to whole units (cents)."""
    return _to_decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def dec(value):
    return _to_decimal(value)


# ---------------------------------------------------------------- lookups
def requirement_rows(retailer_id):
    rows = [r for r in db.retailer_requirements.values() if r["retailer_id"] == retailer_id]
    return in_order(rows)


def scoring_rows(retailer_id):
    """REQUIRED and RECOMMENDED rows only; OPTIONAL is excluded entirely."""
    return [r for r in requirement_rows(retailer_id) if r["requirement_level"] in SCORING_LEVELS]


def weight_of(req):
    if req.get("weight_override") is not None:
        return Fraction(dec(req["weight_override"]))
    definition = attribute_definition(req["attribute_key"])
    if definition is None:
        return Fraction(0)
    return Fraction(dec(definition["base_weight"]))


def effective_ceiling(req):
    if req.get("max_chars_override") is not None:
        return int(req["max_chars_override"])
    definition = attribute_definition(req["attribute_key"])
    if definition is None:
        return 0
    return int(definition["max_chars"])


def attribute_definition(attribute_key):
    for row in db.attribute_definitions.values():
        if row["attribute_key"] == attribute_key:
            return row
    return None


def attribute_values_of(content_version_id):
    out = {}
    for row in db.attribute_values.values():
        if row["content_version_id"] == content_version_id:
            out[row["attribute_key"]] = row
    return out


def versions_of_product(product_id):
    return [v for v in db.content_versions.values() if v["product_id"] == product_id]


def declared_source(listing):
    """Highest revision_no revision of the listing's product, any state."""
    candidates = versions_of_product(listing["product_id"])
    if not candidates:
        return None
    return max(candidates, key=lambda v: v["revision_no"])


def certified_source(listing):
    pinned = listing.get("pinned_content_version_id")
    if not pinned:
        return None
    return db.content_versions.get(pinned)


def listings_of_product(product_id):
    return in_order([l for l in db.listings.values() if l["product_id"] == product_id])


def listings_of_retailer(retailer_id):
    return in_order([l for l in db.listings.values() if l["retailer_id"] == retailer_id])


def find_listing(product_id, retailer_id):
    for row in db.listings.values():
        if row["product_id"] == product_id and row["retailer_id"] == retailer_id:
            return row
    return None


def jobs_of_listing(listing_id):
    return in_order([j for j in db.jobs.values() if j["retailer_listing_id"] == listing_id])


def jobs_of_retailer(retailer_id):
    out = []
    for job in db.jobs.values():
        listing = db.listings.get(job["retailer_listing_id"])
        if listing is not None and listing["retailer_id"] == retailer_id:
            out.append(job)
    return in_order(out)


def rejection_errors_of_job(job_id):
    return in_order([e for e in db.rejection_errors.values() if e["syndication_job_id"] == job_id])


def observations_of_listing(listing_id):
    return in_order([o for o in db.observations.values() if o["retailer_listing_id"] == listing_id])


def alerts_of_listing(listing_id):
    return in_order([a for a in db.alerts.values() if a["retailer_listing_id"] == listing_id])


def deployments_of_listing(listing_id):
    return in_order([d for d in db.deployments.values() if d["retailer_listing_id"] == listing_id])


def approved_image_count(product_id):
    return len([
        a for a in db.media_assets.values()
        if a["product_id"] == product_id
        and a["asset_role"] in IMAGE_ROLES
        and a["approval_state"] == "APPROVED"
    ])


# ---------------------------------------------------------------- type check
_INT_RE = re.compile(r"^[+-]?\d+$")
_DEC_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")


def type_valid(stripped, data_type):
    if stripped == "":
        return False
    if data_type == "INTEGER":
        return bool(_INT_RE.match(stripped))
    if data_type == "DECIMAL":
        return bool(_DEC_RE.match(stripped))
    return True


# ---------------------------------------------------- listing completeness
def image_component(count, min_image_count):
    """Partial-credit image component; the ratio is capped at 1."""
    if min_image_count == 0:
        return IMAGE_WEIGHT
    ratio = Fraction(int(count), int(min_image_count))
    if ratio > 1:
        ratio = Fraction(1)
    return IMAGE_WEIGHT * ratio


def completeness_detail(listing):
    """Both variants side by side, plus the diagnostic arrays."""
    retailer = db.retailers.get(listing["retailer_id"])
    reqs = scoring_rows(listing["retailer_id"])
    weight_total = sum((weight_of(r) for r in reqs), Fraction(0))
    denominator = weight_total + IMAGE_WEIGHT
    min_images = int(retailer["min_image_count"]) if retailer else 0

    declared_version = declared_source(listing)
    certified_version = certified_source(listing)

    detail = {
        "declared_score": ZERO2,
        "certified_score": ZERO2,
        "declared_source_content_version_id": declared_version["id"] if declared_version else None,
        "certified_source_content_version_id": certified_version["id"] if certified_version else None,
        "requirement_weight_total": round2(denominator),
        "declared_image_component": ZERO2,
        "certified_image_component": ZERO2,
        "missing_required_keys": [],
        "over_limit_keys": [],
    }

    certified_values = attribute_values_of(certified_version["id"]) if certified_version else {}
    missing = []
    over_limit = []
    for req in reqs:
        row = certified_values.get(req["attribute_key"])
        has_value = row is not None and int(row["char_count"]) >= 1
        if req["requirement_level"] == "REQUIRED" and not has_value:
            missing.append(req["attribute_key"])
        if has_value and int(row["char_count"]) > effective_ceiling(req):
            over_limit.append(req["attribute_key"])
    detail["missing_required_keys"] = sorted(missing)
    detail["over_limit_keys"] = sorted(over_limit)

    # Empty-requirement-set fallback: nothing to score against.
    if not reqs:
        return detail

    if declared_version is not None:
        values = attribute_values_of(declared_version["id"])
        numerator = Fraction(0)
        for req in reqs:
            row = values.get(req["attribute_key"])
            if row is not None and int(row["char_count"]) >= 1:
                numerator += weight_of(req)
        component = image_component(int(declared_version.get("image_count") or 0), min_images)
        numerator += component
        detail["declared_image_component"] = round2(component)
        detail["declared_score"] = round2(Fraction(100) * numerator / denominator)

    if certified_version is not None:
        numerator = Fraction(0)
        for req in reqs:
            row = certified_values.get(req["attribute_key"])
            if row is None:
                continue
            if int(row["char_count"]) < 1:
                continue
            if not row["type_valid"]:
                continue
            if int(row["char_count"]) > effective_ceiling(req):
                continue
            numerator += weight_of(req)
        component = image_component(approved_image_count(listing["product_id"]), min_images)
        numerator += component
        detail["certified_image_component"] = round2(component)
        detail["certified_score"] = round2(Fraction(100) * numerator / denominator)

    return detail


# ---------------------------------------------------------------- readiness
def open_blocking_error_count(listing_id):
    total = 0
    for job in jobs_of_listing(listing_id):
        for row in rejection_errors_of_job(job["id"]):
            if row["severity"] == "BLOCKING" and row["state"] == "OPEN":
                total += 1
    return total


def penalty_for(blocking):
    if blocking == 0:
        return Decimal("0")
    if blocking <= 2:
        return PENALTY_TIER_1_2
    if blocking <= 5:
        return PENALTY_TIER_3_5
    return PENALTY_TIER_6_PLUS


def readiness_score(listing):
    certified = dec(listing.get("completeness_score_certified") or 0)
    accuracy_raw = listing.get("content_accuracy_pct")
    accuracy = dec(accuracy_raw) if accuracy_raw is not None else ZERO2
    if listing.get("shelf_state") != "OK":
        accuracy = min(accuracy, ACCURACY_CAP_WHEN_NOT_OK)
    penalty = penalty_for(int(listing.get("open_blocking_error_count") or 0))
    bonus = Decimal("0")
    for deployment in deployments_of_listing(listing["id"]):
        if deployment["state"] == "LIVE":
            bonus = LIVE_ENHANCED_BONUS
            break
    raw = (CERTIFIED_WEIGHT * certified + ACCURACY_WEIGHT * accuracy) - penalty + bonus
    if raw < 0:
        raw = Decimal("0")
    if raw > 100:
        raw = Decimal("100")
    return round2(raw)


# ------------------------------------------------------------ shelf health
def listing_subscore(listing):
    accuracy = listing.get("content_accuracy_pct")
    accuracy = dec(accuracy) if accuracy is not None else Decimal("0")
    rank = listing.get("search_rank_latest")
    if rank is None:
        rank_score = Decimal("0")
    else:
        rank_score = Decimal("100") - RANK_DECAY_PER_POSITION * (Decimal(int(rank)) - 1)
        if rank_score < 0:
            rank_score = Decimal("0")
        if rank_score > 100:
            rank_score = Decimal("100")
    avail_score = Decimal("100") if listing.get("in_stock") else Decimal("0")
    rating = listing.get("rating_avg")
    rating_score = Decimal("20") * (dec(rating) if rating is not None else Decimal("0"))
    raw = (HEALTH_ACCURACY_WEIGHT * accuracy
           + HEALTH_RANK_WEIGHT * rank_score
           + HEALTH_AVAILABILITY_WEIGHT * avail_score
           + HEALTH_RATING_WEIGHT * rating_score)
    return round2(raw), accuracy, rank_score, avail_score, rating_score


def qualifying_listings(product_id):
    return [l for l in listings_of_product(product_id)
            if l.get("syndication_state") in HEALTH_SYNDICATION_STATES]


def shelf_health(product_id):
    """Two-stage rounding: subscores first, then the average."""
    rows = qualifying_listings(product_id)
    subscores = []
    for listing in rows:
        sub, accuracy, rank_score, avail_score, rating_score = listing_subscore(listing)
        subscores.append({
            "retailer_listing_id": listing["id"],
            "retailer_id": listing["retailer_id"],
            "subscore": sub,
            "accuracy_component": round2(accuracy),
            "rank_component": round2(rank_score),
            "availability_component": round2(avail_score),
            "rating_component": round2(rating_score),
        })
    if not subscores:
        return ZERO2, []
    total = sum((row["subscore"] for row in subscores), Decimal("0"))
    index = round2(Fraction(dec(total)) / Fraction(len(subscores)))
    return index, subscores


# --------------------------------------------------------- conversion lift
def product_observations(product_id):
    ids = set(l["id"] for l in listings_of_product(product_id))
    rows = [o for o in db.observations.values() if o["retailer_listing_id"] in ids]
    return sorted(rows, key=lambda o: (o["observed_at"], o["created_at"], o["_seq"]))


def conversion_lift(product, variant="post_pin_window"):
    rows = product_observations(product["id"])
    high = []
    base = []
    if variant == "quality_split":
        for row in rows:
            if dec(row["content_accuracy_pct"]) >= QUALITY_SPLIT_ACCURACY_THRESHOLD:
                high.append(row)
            else:
                base.append(row)
    else:
        pinned_at = product.get("last_pinned_at")
        for row in rows:
            if pinned_at is not None and row["observed_at"] >= pinned_at:
                high.append(row)
            else:
                base.append(row)
    if not high or not base:
        return ZERO2, len(high), len(base)
    mean_high = Fraction(0)
    for row in high:
        mean_high += Fraction(dec(row["conversion_rate_pct"]))
    mean_high = mean_high / Fraction(len(high))
    mean_base = Fraction(0)
    for row in base:
        mean_base += Fraction(dec(row["conversion_rate_pct"]))
    mean_base = mean_base / Fraction(len(base))
    if mean_base == 0:
        return ZERO2, len(high), len(base)
    lift = Fraction(100) * (mean_high - mean_base) / mean_base
    return round2(lift), len(high), len(base)


# --------------------------------------------------------------- fee ledger
def feed_slots_reserved(retailer_id):
    total = 0
    for job in jobs_of_retailer(retailer_id):
        if job["state"] in HOLDING_JOB_STATES:
            total += int(job["slot_count"])
    return total


def pin_count(content_version_id):
    total = 0
    for listing in db.listings.values():
        if listing.get("pinned_content_version_id") == content_version_id:
            total += 1
    for deployment in db.deployments.values():
        if deployment["state"] not in ACTIVE_DEPLOYMENT_STATES:
            continue
        change_request = db.change_requests.get(deployment["change_request_id"])
        if change_request is not None and change_request.get("target_content_version_id") == content_version_id:
            total += 1
    return total


def service_fee_cents(slot_count, window_start, current_utc):
    """Five pinned steps; the surcharge tier keys on the pre-surcharge total."""
    subtotal = PER_SKU_RATE_CENTS * int(slot_count)
    if subtotal < 5000:
        discount_pct = Decimal("0.00")
    elif subtotal < 15000:
        discount_pct = Decimal("0.05")
    elif subtotal < 25000:
        discount_pct = Decimal("0.10")
    else:
        discount_pct = Decimal("0.15")
    discounted = round0(Decimal(subtotal) * (Decimal("1") - discount_pct))
    rush = (window_start - current_utc) < timedelta(hours=RUSH_WINDOW_HOURS)
    if not rush:
        surcharge_pct = Decimal("0.00")
    elif discounted < Decimal(RUSH_TIER_BOUNDARY_CENTS):
        surcharge_pct = Decimal("0.20")
    else:
        surcharge_pct = Decimal("0.12")
    surcharge = round0(discounted * surcharge_pct)
    return int(discounted + surcharge)
