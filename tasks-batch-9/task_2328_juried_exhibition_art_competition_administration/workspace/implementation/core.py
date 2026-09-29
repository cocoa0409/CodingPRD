"""Shared infrastructure: in-memory store, logical clock, envelope, auth,
validation helpers, money calculations and derived-field recomputes.

Storage is process-memory only.  Nothing is seeded: every collection starts
empty on every boot.
"""

import datetime as dt
import random
import string
import uuid
from decimal import Decimal, ROUND_HALF_UP

from flask import g, jsonify, request

from errors import ApiError

# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

COLLECTIONS = (
    "exhibitions",
    "artists",
    "entries",
    "artworks",
    "artwork_images",
    "jurors",
    "conflict_declarations",
    "jury_rounds",
    "juror_assignments",
    "scores",
    "wall_segments",
    "condition_reports",
    "sponsors",
    "awards",
    "sales",
)

CLOCK_EPOCH = dt.datetime(2026, 8, 1, 0, 0, 0, tzinfo=dt.timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_EPOCH
        self.clock_raw = "2026-08-01T00:00:00Z"
        self._seq = 0
        self._last_created = None

    def next_seq(self):
        self._seq += 1
        return self._seq

    def stamp(self):
        """Strictly increasing wall-clock creation timestamp (ms precision)."""
        now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0) + dt.timedelta(
            microseconds=(dt.datetime.now(dt.timezone.utc).microsecond // 1000) * 1000
        )
        if self._last_created is not None and now <= self._last_created:
            now = self._last_created + dt.timedelta(milliseconds=1)
        self._last_created = now
        return now


db = Store()


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def iso(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (moment.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO-8601 UTC instant.  Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        moment = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment.astimezone(dt.timezone.utc)


def now():
    return db.clock


def ts(record, field):
    """Read a stored timestamp field as an aware datetime (or None)."""
    return parse_dt(record.get(field))


# ---------------------------------------------------------------------------
# Money / number helpers
# ---------------------------------------------------------------------------


def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value):
    """Round half up to a whole cent."""
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu2(value):
    """Round half up to two decimal places, returned as a float."""
    return float(D(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def num(value):
    """Normalise a derived float so accumulated binary noise never leaks out."""
    return round(float(value), 6)


# ---------------------------------------------------------------------------
# Versioning: a per-request dirty set flushed exactly once
# ---------------------------------------------------------------------------


def _dirty():
    if not hasattr(g, "dirty_records"):
        g.dirty_records = []
    return g.dirty_records


def touch(record):
    bucket = _dirty()
    for existing in bucket:
        if existing is record:
            return record
    bucket.append(record)
    return record


def setv(record, field, value):
    """Assign a field, marking the record dirty only when the value moves."""
    if record.get(field) != value:
        record[field] = value
        touch(record)
    return record


def exempt(record):
    """Records created during this request must stay at version 1."""
    if not hasattr(g, "exempt_records"):
        g.exempt_records = set()
    g.exempt_records.add(id(record))
    return record


def _is_exempt(record):
    return id(record) in getattr(g, "exempt_records", ())


def flush():
    for record in _dirty():
        if _is_exempt(record):
            continue
        if "version" in record:
            record["version"] = record["version"] + 1
        if "updated_at" in record:
            record["updated_at"] = iso(db.stamp())
    g.dirty_records = []


# ---------------------------------------------------------------------------
# Record creation
# ---------------------------------------------------------------------------


def new_record(fields, versioned=True):
    created = iso(db.stamp())
    record = {"id": str(uuid.uuid4()), "created_at": created}
    if versioned:
        record["updated_at"] = created
        record["version"] = 1
    record.update(fields)
    record["_seq"] = db.next_seq()
    exempt(record)
    return record


def order_key(record):
    return (record.get("created_at") or "", record.get("_seq") or 0)


def ordered(records):
    return sorted(records, key=order_key)


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def _meta():
    rid = "req_" + "".join(random.choice(_ALNUM) for _ in range(20))
    return {
        "api_request_id": rid,
        "api_request_timestamp": iso(dt.datetime.now(dt.timezone.utc)),
    }


def public(record):
    if record is None:
        return None
    return {k: v for k, v in record.items() if not k.startswith("_")}


def ok(data=None, status=200):
    flush()
    payload = {"meta": _meta(), "response_type": "object", "data": {}}
    if data is not None:
        payload["data"] = public(data) if isinstance(data, dict) else data
    return jsonify(payload), status


def created(data):
    return ok(data, 201)


def listing(records, transform=public):
    flush()
    limit, offset = pagination()
    items = list(records)
    total = len(items)
    page = items[offset : offset + limit]
    meta = _meta()
    meta.update(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": offset + len(page) < total,
        }
    )
    return (
        jsonify(
            {
                "meta": meta,
                "response_type": "array",
                "data": [transform(r) for r in page],
            }
        ),
        200,
    )


def error_response(error_id, message=None):
    err = ApiError(error_id, message)
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": err.error_id, "message": err.message},
            }
        ),
        err.http_status,
    )


# ---------------------------------------------------------------------------
# Query parameters
# ---------------------------------------------------------------------------


def pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None or limit == "":
        limit_v = 10
    else:
        try:
            limit_v = int(str(limit))
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit_v < 1 or limit_v > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset is None or offset == "":
        offset_v = 0
    else:
        try:
            offset_v = int(str(offset))
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset_v < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must not be negative.")
    return limit_v, offset_v


def qs(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def qs_int(name):
    value = qs(name)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)


# ---------------------------------------------------------------------------
# Authentication / authorisation
# ---------------------------------------------------------------------------

ROLES = (
    "CallManager",
    "JuryChair",
    "Juror",
    "Artist",
    "Registrar",
    "FinanceOfficer",
)
ALL_ROLES = list(ROLES)


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = str(user_id)
    g.role = role
    return g.user_id, g.role


def require_roles(*roles):
    allowed = []
    for item in roles:
        if isinstance(item, (list, tuple)):
            allowed.extend(item)
        else:
            allowed.append(item)
    if g.role not in allowed:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")


def user_id():
    return g.user_id


def role():
    return g.role


def own(condition):
    if not condition:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

_NOT_FOUND = {
    "exhibitions": "ERR_EXHIBITION_NOT_FOUND",
    "artists": "ERR_ARTIST_NOT_FOUND",
    "entries": "ERR_ENTRY_NOT_FOUND",
    "artworks": "ERR_ARTWORK_NOT_FOUND",
    "jurors": "ERR_JUROR_NOT_FOUND",
    "jury_rounds": "ERR_JURY_ROUND_NOT_FOUND",
    "juror_assignments": "ERR_ASSIGNMENT_NOT_FOUND",
    "wall_segments": "ERR_WALL_SEGMENT_NOT_FOUND",
    "sponsors": "ERR_SPONSOR_NOT_FOUND",
    "awards": "ERR_AWARD_NOT_FOUND",
    "sales": "ERR_SALE_NOT_FOUND",
    "scores": "ERR_SCORE_NOT_FOUND",
}


def find(collection, identifier):
    table = getattr(db, collection)
    if not isinstance(identifier, str):
        raise ApiError(_NOT_FOUND[collection])
    record = table.get(identifier)
    if record is None:
        raise ApiError(_NOT_FOUND[collection])
    return record


def fk(body_dict, field, collection, required=False):
    """Resolve a body foreign key (ladder step 4).  Absent -> None."""
    if field not in body_dict or body_dict.get(field) is None:
        if required:
            return None
        return None
    return find(collection, body_dict.get(field))


def all_of(collection):
    return ordered(getattr(db, collection).values())


# ---------------------------------------------------------------------------
# Body parsing / schema validation (ladder step 6)
# ---------------------------------------------------------------------------


def body():
    if not request.data:
        return {}
    try:
        parsed = request.get_json(force=True, silent=True)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Body must be valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Body must be a JSON object.")
    return parsed


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def req(body_dict, field):
    if field not in body_dict or body_dict.get(field) is None:
        bad("%s is required." % field)
    return body_dict[field]


def v_str(body_dict, field, required=True, default=None, allow_empty=False):
    if field not in body_dict or body_dict.get(field) is None:
        if required:
            bad("%s is required." % field)
        return default
    value = body_dict[field]
    if not isinstance(value, str):
        bad("%s must be a string." % field)
    if not allow_empty and not value.strip():
        bad("%s must not be empty." % field)
    return value


def v_int(body_dict, field, required=True, default=None, minimum=None, maximum=None):
    if field not in body_dict or body_dict.get(field) is None:
        if required:
            bad("%s is required." % field)
        return default
    value = body_dict[field]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer." % field)
    if minimum is not None and value < minimum:
        bad("%s must be at least %s." % (field, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be at most %s." % (field, maximum))
    return value


def v_num(body_dict, field, required=True, default=None, minimum=None, maximum=None):
    if field not in body_dict or body_dict.get(field) is None:
        if required:
            bad("%s is required." % field)
        return default
    value = body_dict[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("%s must be a number." % field)
    if minimum is not None and value < minimum:
        bad("%s must be at least %s." % (field, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be at most %s." % (field, maximum))
    return float(value)


def v_bool(body_dict, field, required=False, default=None):
    if field not in body_dict or body_dict.get(field) is None:
        if required:
            bad("%s is required." % field)
        return default
    value = body_dict[field]
    if not isinstance(value, bool):
        bad("%s must be a boolean." % field)
    return value


def v_enum(body_dict, field, members, required=True, default=None):
    if field not in body_dict or body_dict.get(field) is None:
        if required:
            bad("%s is required." % field)
        return default
    value = body_dict[field]
    if not isinstance(value, str) or value not in members:
        bad("%s must be one of %s." % (field, ", ".join(members)))
    return value


def v_dt(body_dict, field, required=True, default=None):
    if field not in body_dict or body_dict.get(field) is None:
        if required:
            bad("%s is required." % field)
        return default
    value = body_dict[field]
    if not isinstance(value, str) or parse_dt(value) is None:
        bad("%s must be an ISO 8601 UTC instant." % field)
    return value


def v_list(body_dict, field, members=None, required=True, default=None, non_empty=True):
    if field not in body_dict or body_dict.get(field) is None:
        if required:
            bad("%s is required." % field)
        return default
    value = body_dict[field]
    if not isinstance(value, list):
        bad("%s must be an array." % field)
    if non_empty and len(value) == 0:
        bad("%s must not be empty." % field)
    for item in value:
        if not isinstance(item, str):
            bad("%s must be an array of strings." % field)
        if members is not None and item not in members:
            bad("%s contains an unsupported value." % field)
    return list(value)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

MEDIA_CATEGORIES = (
    "PAINTING",
    "SCULPTURE",
    "PHOTOGRAPHY",
    "PRINTMAKING",
    "TEXTILE",
    "NEW_MEDIA",
)
EXHIBITION_STATUSES = (
    "DRAFT",
    "OPEN_FOR_ENTRIES",
    "JURYING",
    "RESULTS_PUBLISHED",
    "INSTALLATION",
    "ON_VIEW",
    "CLOSED",
)
SETTLEMENT_STATUSES = ("NOT_STARTED", "RECONCILING", "PAYOUTS_RELEASED", "BOOKS_CLOSED")
ENTRY_STATUSES = ("DRAFT", "PENDING_FEE", "SUBMITTED", "WITHDRAWN")
ARTWORK_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "WITHDRAWN",
    "SHORTLISTED",
    "DECLINED",
    "ACCEPTED",
    "WAITLISTED",
    "DELIVERED",
    "ON_VIEW",
    "SOLD",
    "RETURN_PENDING",
    "RETURN_SCHEDULED",
    "RETURNED",
    "UNCLAIMED_FORFEIT",
)
PLACEMENT_STATUSES = ("UNPLACED", "PLANNED", "INSTALLED", "DEINSTALLED")
IMAGE_ROLES = ("PRIMARY", "DETAIL")
IMAGE_FORMATS = ("JPEG", "PNG", "TIFF")
COLOR_PROFILES = ("SRGB", "ADOBE_RGB", "CMYK")
JUROR_STATUSES = ("INVITED", "CONFIRMED", "RESIGNED")
RELATION_TYPES = (
    "FAMILY",
    "TEACHER_STUDENT",
    "SAME_GALLERY",
    "COLLABORATOR",
    "FINANCIAL_INTEREST",
)
ROUND_TYPES = ("BLIND_SCORING", "DELIBERATION")
ROUND_STATUSES = ("PENDING", "OPEN", "SCORING_COMPLETE", "CLOSED")
ASSIGNMENT_STATUSES = ("BOOKED", "COMPLETED", "CANCELLED")
LIGHTING_CLASSES = ("STANDARD", "MUSEUM")
CONDITION_STAGES = ("INTAKE", "DEINSTALL")
CONDITION_GRADES = ("A", "B", "C", "DAMAGED")
RECOGNITION_TIERS = ("NONE", "BRONZE", "SILVER", "GOLD", "PRESENTING")
AWARD_CATEGORIES = ("BEST_IN_SHOW", "JURORS_CHOICE", "MEDIUM_MERIT", "PURCHASE_AWARD")
AWARD_STATUSES = ("PROPOSED", "CONFIRMED", "RESCINDED")
SALE_TYPES = ("GALLERY_SALE", "PURCHASE_AWARD")
SALE_STATUSES = ("RECORDED", "INVOICED", "PAID", "PAYOUT_RELEASED", "VOIDED")
RETURN_METHODS = ("ARTIST_PICKUP", "COURIER")

ACCEPTED_COUNT_STATES = (
    "ACCEPTED",
    "DELIVERED",
    "ON_VIEW",
    "SOLD",
    "RETURN_PENDING",
    "RETURN_SCHEDULED",
    "RETURNED",
    "UNCLAIMED_FORFEIT",
)
SHORTLISTED_COUNT_STATES = (
    "SHORTLISTED",
    "ACCEPTED",
    "WAITLISTED",
    "DELIVERED",
    "ON_VIEW",
    "SOLD",
    "RETURN_PENDING",
    "RETURN_SCHEDULED",
    "RETURNED",
    "UNCLAIMED_FORFEIT",
)
INSURED_STATES = ("DELIVERED", "ON_VIEW", "SOLD")
LIVE_SALE_STATES = ("RECORDED", "INVOICED", "PAID", "PAYOUT_RELEASED")

# Calculation constants
OVERSIZE_LONG_EDGE_CM = 120.0
OVERSIZE_SURCHARGE_CENTS = 2000
NON_EXPERT_CAP = Decimal("8.00")
PURCHASE_AWARD_COMMISSION_PCT = Decimal("0.10")
INS_TIER1_RATE_CENTS = 350
INS_TIER2_RATE_CENTS = 275
INS_TIER3_RATE_CENTS = 190
INS_MIN_PREMIUM_CENTS = 25000
MEDIUM_CAP_PCT = Decimal("0.40")
RECOVERY_TIER1_CENTS = 50000
RECOVERY_TIER2_CENTS = 150000
STORAGE_FEE_PER_DAY_CENTS = 1500
STORAGE_FEE_CAP_PCT = Decimal("0.5")
FORFEIT_GRACE_DAYS = 30
WALL_BUFFER_CM = 15.0
SPONSOR_TIERS = (
    (5000000, "PRESENTING"),
    (2500000, "GOLD"),
    (1000000, "SILVER"),
    (250000, "BRONZE"),
)


# ---------------------------------------------------------------------------
# Graph navigation
# ---------------------------------------------------------------------------


def entry_of(artwork):
    return db.entries.get(artwork.get("entry_id"))


def exhibition_of_entry(entry):
    return db.exhibitions.get(entry.get("exhibition_id"))


def exhibition_of_artwork(artwork):
    entry = entry_of(artwork)
    return exhibition_of_entry(entry) if entry else None


def artist_of_artwork(artwork):
    entry = entry_of(artwork)
    return db.artists.get(entry.get("artist_id")) if entry else None


def entries_of_exhibition(exhibition_id):
    return [e for e in all_of("entries") if e.get("exhibition_id") == exhibition_id]


def artworks_of_entry(entry_id):
    return [a for a in all_of("artworks") if a.get("entry_id") == entry_id]


def artworks_of_exhibition(exhibition_id):
    result = []
    for artwork in all_of("artworks"):
        entry = db.entries.get(artwork.get("entry_id"))
        if entry is not None and entry.get("exhibition_id") == exhibition_id:
            result.append(artwork)
    return ordered(result)


def rounds_of_exhibition(exhibition_id):
    return [r for r in all_of("jury_rounds") if r.get("exhibition_id") == exhibition_id]


def scores_of_round(round_id):
    return [s for s in all_of("scores") if s.get("jury_round_id") == round_id]


def assignments_of_juror(juror_id):
    return [a for a in all_of("juror_assignments") if a.get("juror_id") == juror_id]


def assignments_of_round(round_id):
    return [
        a for a in all_of("juror_assignments") if a.get("jury_round_id") == round_id
    ]


def sales_of_exhibition(exhibition_id):
    result = []
    for sale in all_of("sales"):
        artwork = db.artworks.get(sale.get("artwork_id"))
        if artwork is None:
            continue
        exhibition = exhibition_of_artwork(artwork)
        if exhibition is not None and exhibition["id"] == exhibition_id:
            result.append(sale)
    return result


def sales_of_artwork(artwork_id):
    return [s for s in all_of("sales") if s.get("artwork_id") == artwork_id]


def artworks_on_wall(wall_id):
    return [a for a in all_of("artworks") if a.get("wall_segment_id") == wall_id]


def reports_of_artwork(artwork_id):
    return [
        r for r in all_of("condition_reports") if r.get("artwork_id") == artwork_id
    ]


def images_of_artwork(artwork_id):
    return [i for i in all_of("artwork_images") if i.get("artwork_id") == artwork_id]


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------


def calc_entry_fee(entry, exhibition, artist):
    discount = D(exhibition["member_discount_pct"]) if artist.get(
        "member_status"
    ) == "MEMBER" else Decimal("0")
    factor = Decimal("1") - discount
    base_line = rhu(D(exhibition["entry_fee_base_cents"]) * factor)
    works = [
        a for a in artworks_of_entry(entry["id"]) if a.get("status") != "WITHDRAWN"
    ]
    additional_works = max(0, len(works) - int(exhibition["works_included_in_base"]))
    additional_line = rhu(D(exhibition["entry_fee_additional_cents"]) * factor)
    oversize = sum(
        1 for a in works if float(a["longest_edge_cm"]) > OVERSIZE_LONG_EDGE_CM
    )
    return (
        base_line
        + additional_works * additional_line
        + oversize * OVERSIZE_SURCHARGE_CENTS
    )


def calc_composite(exhibition, juror, artwork, technique, originality, relevance):
    raw = (
        D(technique) * D(exhibition["score_weight_technique"])
        + D(originality) * D(exhibition["score_weight_originality"])
        + D(relevance) * D(exhibition["score_weight_relevance"])
    )
    match = artwork["medium_category"] in (juror.get("expertise_categories") or [])
    adjusted = raw if match else min(raw, NON_EXPERT_CAP)
    return match, rhu2(adjusted)


def valid_scores_for(artwork_id, round_id):
    scores = [
        s
        for s in scores_of_round(round_id)
        if s.get("artwork_id") == artwork_id and not s.get("voided_by_conflict")
    ]
    return sorted(
        scores,
        key=lambda s: (s.get("created_at"), D(s.get("composite_score")), s.get("_seq")),
    )


def mean_of(scores):
    if not scores:
        return None
    total = sum((D(s["composite_score"]) for s in scores), Decimal("0"))
    return rhu2(total / D(len(scores)))


def calc_insurance_premium(insured_total):
    if insured_total <= 0:
        return 0
    thousands = -(-int(insured_total) // 100000)
    t1 = min(thousands, 50)
    t2 = min(max(thousands - 50, 0), 150)
    t3 = max(thousands - 200, 0)
    raw = (
        t1 * INS_TIER1_RATE_CENTS
        + t2 * INS_TIER2_RATE_CENTS
        + t3 * INS_TIER3_RATE_CENTS
    )
    return max(INS_MIN_PREMIUM_CENTS, raw)


def calc_sale_split(exhibition, sale_type, sale_price_cents, tax_exempt):
    price = int(sale_price_cents)
    if tax_exempt:
        taxable_base = price
        sales_tax = 0
    elif sale_type == "GALLERY_SALE":
        taxable_base = rhu(D(price) / (Decimal("1") + D(exhibition["sales_tax_pct"])))
        sales_tax = price - taxable_base
    else:
        taxable_base = price
        sales_tax = rhu(D(price) * D(exhibition["sales_tax_pct"]))
    if sale_type == "PURCHASE_AWARD":
        commission_pct = PURCHASE_AWARD_COMMISSION_PCT
    else:
        commission_pct = D(exhibition["commission_pct"])
    commission = rhu(D(taxable_base) * commission_pct)
    artist_payable = taxable_base - commission
    buyer_total = taxable_base + sales_tax
    return {
        "taxable_base_cents": taxable_base,
        "sales_tax_cents": sales_tax,
        "commission_cents": commission,
        "artist_payable_cents": artist_payable,
        "buyer_total_cents": buyer_total,
    }


def calc_sponsor_tier(contribution_cents):
    for floor_cents, tier in SPONSOR_TIERS:
        if contribution_cents >= floor_cents:
            return tier
    return "NONE"


# ---------------------------------------------------------------------------
# Recomputes
# ---------------------------------------------------------------------------


def recompute_entry_counts(entry):
    if entry is None:
        return
    works = artworks_of_entry(entry["id"])
    setv(
        entry,
        "works_count",
        sum(1 for a in works if a.get("status") != "WITHDRAWN"),
    )
    setv(
        entry,
        "shortlisted_count",
        sum(1 for a in works if a.get("status") in SHORTLISTED_COUNT_STATES),
    )


def recompute_exhibition_counts(exhibition):
    if exhibition is None:
        return
    works = artworks_of_exhibition(exhibition["id"])
    setv(
        exhibition,
        "shortlisted_count",
        sum(1 for a in works if a.get("status") == "SHORTLISTED"),
    )
    setv(
        exhibition,
        "accepted_count",
        sum(1 for a in works if a.get("status") in ACCEPTED_COUNT_STATES),
    )
    setv(
        exhibition,
        "waitlisted_count",
        sum(1 for a in works if a.get("status") == "WAITLISTED"),
    )


def recompute_insurance(exhibition):
    if exhibition is None:
        return
    works = artworks_of_exhibition(exhibition["id"])
    total = sum(
        int(a["declared_value_cents"]) for a in works if a.get("status") in INSURED_STATES
    )
    setv(exhibition, "insured_value_total_cents", total)
    setv(exhibition, "insurance_premium_cents", calc_insurance_premium(total))
    recompute_retention(exhibition)


def recompute_money(exhibition):
    if exhibition is None:
        return
    sales = [
        s for s in sales_of_exhibition(exhibition["id"]) if s.get("status") in LIVE_SALE_STATES
    ]
    setv(exhibition, "sales_gross_cents", sum(int(s["sale_price_cents"]) for s in sales))
    setv(exhibition, "commission_total_cents", sum(int(s["commission_cents"]) for s in sales))
    setv(exhibition, "sales_tax_total_cents", sum(int(s["sales_tax_cents"]) for s in sales))
    setv(
        exhibition,
        "artist_payable_total_cents",
        sum(int(s["artist_payable_cents"]) for s in sales),
    )
    setv(
        exhibition,
        "payouts_released_cents",
        sum(
            int(s["artist_payable_cents"])
            for s in sales
            if s.get("status") == "PAYOUT_RELEASED"
        ),
    )
    recompute_retention(exhibition)


def recompute_retention(exhibition):
    """council_retention_cents is live only while the books are still open."""
    if exhibition is None:
        return
    if exhibition.get("settlement_status") not in ("RECONCILING", "PAYOUTS_RELEASED"):
        return
    commission_total = int(exhibition["commission_total_cents"])
    premium = int(exhibition["insurance_premium_cents"])
    if commission_total >= RECOVERY_TIER2_CENTS:
        rate = Decimal("0.75")
    elif commission_total >= RECOVERY_TIER1_CENTS:
        rate = Decimal("0.50")
    else:
        rate = Decimal("0.25")
    setv(
        exhibition,
        "council_retention_cents",
        commission_total - rhu(D(premium) * rate),
    )


def recompute_awards(exhibition):
    if exhibition is None:
        return
    total = 0
    for award in all_of("awards"):
        if (
            award.get("exhibition_id") == exhibition["id"]
            and award.get("status") == "CONFIRMED"
            and not award.get("sponsor_id")
        ):
            total += int(award["prize_cents"])
    setv(exhibition, "award_committed_cents", total)


def recompute_sponsor(sponsor):
    if sponsor is None:
        return
    total = 0
    for award in all_of("awards"):
        if award.get("sponsor_id") == sponsor["id"] and award.get("status") == "CONFIRMED":
            total += int(award["prize_cents"])
    setv(sponsor, "purchase_award_committed_cents", total)


def recompute_wall(wall):
    if wall is None:
        return
    works = [
        a
        for a in artworks_on_wall(wall["id"])
        if a.get("placement_status") in ("PLANNED", "INSTALLED")
    ]
    occupied = 0.0
    load = 0.0
    for artwork in works:
        occupied += float(artwork["span_end_cm"]) - float(artwork["span_start_cm"])
        load += float(artwork["weight_kg"])
    setv(wall, "occupied_cm", num(occupied))
    setv(wall, "available_cm", num(float(wall["length_cm"]) - occupied))
    setv(wall, "loaded_weight_kg", num(load))


def recompute_artwork_scores(artwork, jury_round=None):
    """Refresh provisional_mean_score and valid_score_count."""
    if artwork is None:
        return
    exhibition = exhibition_of_artwork(artwork)
    if jury_round is not None:
        scores = valid_scores_for(artwork["id"], jury_round["id"])
        mean = mean_of(scores)
        setv(artwork, "provisional_mean_score", mean)
    if exhibition is not None:
        first = None
        for candidate in rounds_of_exhibition(exhibition["id"]):
            if int(candidate.get("round_number", 0)) == 1:
                first = candidate
                break
        if first is not None:
            setv(
                artwork,
                "valid_score_count",
                len(valid_scores_for(artwork["id"], first["id"])),
            )
        else:
            setv(artwork, "valid_score_count", 0)


def recompute_round(jury_round):
    if jury_round is None:
        return
    exhibition = db.exhibitions.get(jury_round.get("exhibition_id"))
    scores = [s for s in scores_of_round(jury_round["id"]) if not s.get("voided_by_conflict")]
    setv(
        jury_round,
        "scored_artwork_count",
        len({s["artwork_id"] for s in scores}),
    )
    quorum = int(jury_round["quorum_required"])
    shortfall = 0
    if exhibition is not None:
        for artwork in artworks_of_exhibition(exhibition["id"]):
            if artwork.get("status") != "SUBMITTED":
                continue
            count = sum(1 for s in scores if s["artwork_id"] == artwork["id"])
            if count < quorum:
                shortfall += 1
    setv(jury_round, "quorum_shortfall_count", shortfall)


def recompute_rounds_of(exhibition):
    if exhibition is None:
        return
    for jury_round in rounds_of_exhibition(exhibition["id"]):
        recompute_round(jury_round)


def recompute_assignment_counts(assignment):
    if assignment is None:
        return
    count = sum(
        1
        for s in all_of("scores")
        if s.get("jury_round_id") == assignment.get("jury_round_id")
        and s.get("juror_id") == assignment.get("juror_id")
    )
    setv(assignment, "scores_submitted_count", count)


def prorate_honorarium(juror):
    """Recompute every share of a juror, then their committed total."""
    if juror is None:
        return
    active = [
        a
        for a in assignments_of_juror(juror["id"])
        if a.get("status") in ("BOOKED", "COMPLETED")
    ]
    for assignment in assignments_of_juror(juror["id"]):
        if assignment.get("status") == "CANCELLED":
            setv(assignment, "honorarium_share_cents", 0)
    if not active:
        setv(juror, "honorarium_committed_cents", 0)
        setv(juror, "assignment_count", 0)
        return
    honorarium = int(juror["honorarium_cents"])
    total_minutes = sum(int(a["session_minutes"]) for a in active)
    shares = {}
    if total_minutes <= 0:
        for assignment in active:
            shares[assignment["id"]] = 0
    else:
        for assignment in active:
            shares[assignment["id"]] = (
                honorarium * int(assignment["session_minutes"])
            ) // total_minutes
    remainder = honorarium - sum(shares.values())
    if remainder > 0:
        for assignment in ordered(active)[:remainder]:
            shares[assignment["id"]] += 1
    for assignment in active:
        setv(assignment, "honorarium_share_cents", shares[assignment["id"]])
    setv(juror, "honorarium_committed_cents", sum(shares.values()))
    setv(juror, "assignment_count", len(active))


def recompute_jury_cost(exhibition):
    if exhibition is None:
        return
    total = 0
    for jury_round in rounds_of_exhibition(exhibition["id"]):
        for assignment in assignments_of_round(jury_round["id"]):
            if assignment.get("status") in ("BOOKED", "COMPLETED"):
                total += int(assignment["honorarium_share_cents"])
    setv(exhibition, "jury_cost_committed_cents", total)


def recompute_jury_cost_for_juror(juror):
    seen = set()
    for assignment in assignments_of_juror(juror["id"]):
        jury_round = db.jury_rounds.get(assignment.get("jury_round_id"))
        if jury_round is None:
            continue
        exhibition = db.exhibitions.get(jury_round.get("exhibition_id"))
        if exhibition is None or exhibition["id"] in seen:
            continue
        seen.add(exhibition["id"])
        recompute_jury_cost(exhibition)


def recompute_artist_forfeits(artist):
    if artist is None:
        return
    count = 0
    for artwork in all_of("artworks"):
        if artwork.get("status") != "UNCLAIMED_FORFEIT":
            continue
        entry = db.entries.get(artwork.get("entry_id"))
        if entry is not None and entry.get("artist_id") == artist["id"]:
            count += 1
    setv(artist, "unclaimed_forfeit_count", count)
    if count >= 2:
        setv(artist, "payout_hold", True)


# ---------------------------------------------------------------------------
# Status mutators (with their cascade of derived recomputes)
# ---------------------------------------------------------------------------


def set_artwork_status(artwork, new_status):
    if artwork.get("status") == new_status:
        return artwork
    artwork["status"] = new_status
    touch(artwork)
    recompute_entry_counts(entry_of(artwork))
    exhibition = exhibition_of_artwork(artwork)
    recompute_exhibition_counts(exhibition)
    recompute_insurance(exhibition)
    return artwork


def set_placement(artwork, new_placement):
    old_wall = artwork.get("wall_segment_id")
    if artwork.get("placement_status") != new_placement:
        artwork["placement_status"] = new_placement
        touch(artwork)
    if old_wall:
        recompute_wall(db.wall_segments.get(old_wall))
    return artwork
