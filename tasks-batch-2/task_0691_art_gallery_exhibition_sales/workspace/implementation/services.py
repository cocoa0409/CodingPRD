"""Domain logic: common fields, computed fields, calculations, ledger, serializers.

All monetary math uses integer cents with round-half-up. The logical clock
(db.DB.clock_utc) drives every time-dependent figure.
"""
from decimal import ROUND_HALF_UP, Decimal

import clock as clockmod
import errors
from db import DB

# ---------------------------------------------------------------------------
# Constants from SCAFFOLD §1.3
# ---------------------------------------------------------------------------
MAX_MISSED_INSTALLMENTS = 2
DAYS_PER_MONTH = 30
SECONDS_PER_DAY = 86400


# ---------------------------------------------------------------------------
# Rounding helpers
# ---------------------------------------------------------------------------
def round_half_up(numerator, denominator):
    """Round (numerator / denominator) to the nearest integer, half up."""
    q = Decimal(numerator) / Decimal(denominator)
    return int(q.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Common-field management (PRD §2.4)
# ---------------------------------------------------------------------------
def stamp_new(entity):
    now = DB.now_dt()
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    entity["_seq"] = DB.next_seq()
    return entity


def touch(entity):
    """Record a mutation: refresh updated_at, bump version (PRD §2.4)."""
    entity["updated_at"] = DB.now_dt()
    entity["version"] += 1
    return entity


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def parse_pagination(args):
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise errors.validation_pagination()
        if limit < 1 or limit > 100:
            raise errors.validation_pagination()
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise errors.validation_pagination()
        if offset < 0:
            raise errors.validation_pagination()
    return limit, offset


def paginate(rows, limit, offset):
    """Sort by created_at ASC (insertion seq tiebreak) then window."""
    ordered = sorted(rows, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


# ---------------------------------------------------------------------------
# Body field helpers
# ---------------------------------------------------------------------------
def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise errors.invalid_request(f"Missing required field: {n}")


def as_int(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise errors.invalid_request(f"Missing required field: {name}")
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field {name} must be an integer.")
    return val


def as_str(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise errors.invalid_request(f"Missing required field: {name}")
        return default
    val = body[name]
    if not isinstance(val, str):
        raise errors.invalid_request(f"Field {name} must be a string.")
    return val


def state_code(body, name):
    val = as_str(body, name)
    if len(val) != 2 or not val.isalpha() or not val.isupper():
        raise errors.invalid_request(f"Field {name} must be 2 uppercase letters.")
    return val


def parse_dt_field(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise errors.invalid_request(f"Missing required field: {name}")
        return default
    try:
        return clockmod.parse_iso(body[name])
    except (ValueError, TypeError):
        raise errors.invalid_request(f"Field {name} must be an ISO 8601 instant.")


# ---------------------------------------------------------------------------
# Existence lookups (raise ERR_NOT_FOUND)
# ---------------------------------------------------------------------------
def get_gallery(gid):
    g = DB.galleries.get(gid)
    if g is None:
        raise errors.not_found("Gallery not found.")
    return g


def get_or_404(collection, _id, label):
    obj = collection.get(_id)
    if obj is None:
        raise errors.not_found(f"{label} not found.")
    return obj


# ---------------------------------------------------------------------------
# Calculations (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
def effective_split_bps(artist, gallery):
    if artist.get("split_override_bps") is not None:
        return artist["split_override_bps"]
    return gallery["default_consignment_split_bps"]


def compute_sale_money(sale, gallery):
    """sale_money_breakdown. Mutates net/tax/buyer_total on the sale dict."""
    gross = sale["gross_amount_cents"]
    discount = sale["discount_bps"]
    shipping = sale["shipping_cents"]
    net = round_half_up(gross * (10000 - discount), 10000)

    tax_exempt = (sale["buyer_state_code"] != gallery["home_state_code"]) or (
        gallery["resale_exempt_threshold_cents"] > 0
        and gross > gallery["resale_exempt_threshold_cents"]
    )
    if tax_exempt:
        tax = 0
    else:
        tax = round_half_up(net * gallery["sales_tax_rate_bps"], 10000)

    sale["net_amount_cents"] = net
    sale["tax_amount_cents"] = tax
    sale["buyer_total_cents"] = net + tax + shipping
    return sale


def compute_provisional_split(sale, artist, gallery):
    """Provisional artist share: split on undiscounted gross-derived net."""
    split = effective_split_bps(artist, gallery)
    undiscounted_net = round_half_up(sale["gross_amount_cents"] * 10000, 10000)
    artist_share = round_half_up(undiscounted_net * split, 10000)
    sale["artist_share_cents"] = artist_share
    sale["gallery_share_cents"] = sale["net_amount_cents"] - artist_share


def compute_final_split(sale, artist, gallery):
    """Final artist share: split on realized post-discount net."""
    split = effective_split_bps(artist, gallery)
    artist_share = round_half_up(sale["net_amount_cents"] * split, 10000)
    sale["artist_share_cents"] = artist_share
    sale["gallery_share_cents"] = sale["net_amount_cents"] - artist_share


def compute_installment_schedule(plan, buyer_total):
    n = plan["installment_count"]
    base = buyer_total // n
    remainder = buyer_total - base * n
    plan["installment_cents"] = base
    plan["final_installment_cents"] = base + remainder


def due_count_for_plan(plan):
    """Number of installments whose due instant <= clock (inclusive)."""
    first_due = plan["first_due_utc"]
    cadence = plan["cadence_days"]
    clock = DB.clock_utc
    count = 0
    for k in range(1, plan["installment_count"] + 1):
        offset_seconds = (k - 1) * cadence * SECONDS_PER_DAY
        due_ts = first_due.timestamp() + offset_seconds
        if clock.timestamp() >= due_ts:
            count += 1
    return count


def plan_missed_count(plan):
    due = due_count_for_plan(plan)
    return max(0, due - plan["posted_installment_count"])


def compute_lease_figures(lease):
    """months_accrued, rent_accrued, buyout_price against the clock."""
    artwork = DB.artworks.get(lease["artwork_id"])
    list_price = artwork["list_price_cents"] if artwork else 0
    elapsed = DB.clock_utc.timestamp() - lease["starts_utc"].timestamp()
    if elapsed < 0:
        months = 0
    else:
        months = int(elapsed // (DAYS_PER_MONTH * SECONDS_PER_DAY))
    months = min(lease["term_months"], months)
    rent_accrued = months * lease["monthly_rate_cents"]
    credit = round_half_up(rent_accrued * lease["purchase_credit_bps"], 10000)
    buyout = max(0, list_price - credit)
    return months, rent_accrued, buyout


# ---------------------------------------------------------------------------
# Artist ledger (SCAFFOLD §1.3 artist_ledger, PRD §2.10)
# ---------------------------------------------------------------------------
def artist_ledger(artist_id):
    accrued = 0
    for sale in DB.sales.values():
        if sale["settlement_status"] != "SETTLED":
            continue
        artwork = DB.artworks.get(sale["artwork_id"])
        if artwork and artwork["artist_id"] == artist_id:
            accrued += sale["artist_share_cents"]
    paid = 0
    for payout in DB.payouts.values():
        if payout["artist_id"] == artist_id and payout["status"] == "COMPLETED":
            paid += payout["approved_cents"]
    payable = max(0, accrued - paid)
    return accrued, paid, payable


# ---------------------------------------------------------------------------
# Exhibition slot counts (computed)
# ---------------------------------------------------------------------------
def exhibition_slot_counts(exhibition_id, wall_capacity):
    occupied = sum(
        1
        for ws in DB.wall_slots.values()
        if ws["exhibition_id"] == exhibition_id and ws["status"] == "PLACED"
    )
    available = max(0, wall_capacity - occupied)
    return occupied, available


def event_counts(event_id):
    confirmed = sum(
        1
        for r in DB.rsvps.values()
        if r["opening_event_id"] == event_id and r["status"] in ("CONFIRMED", "PROMOTED")
    )
    waitlist = sum(
        1
        for r in DB.rsvps.values()
        if r["opening_event_id"] == event_id and r["status"] == "WAITLISTED"
    )
    return confirmed, waitlist


def confirmed_seats(event_id):
    """Party-size-weighted confirmed seat count (CONFIRMED + PROMOTED)."""
    return sum(
        r["party_size"]
        for r in DB.rsvps.values()
        if r["opening_event_id"] == event_id and r["status"] in ("CONFIRMED", "PROMOTED")
    )


# ---------------------------------------------------------------------------
# Serializers (render computed/derived fields live; timestamps formatted)
# ---------------------------------------------------------------------------
def _base(entity):
    return {
        "id": entity["id"],
        "created_at": clockmod.format_iso_ms(entity["created_at"]),
        "updated_at": clockmod.format_iso_ms(entity["updated_at"]),
        "version": entity["version"],
    }


def ser_gallery(g):
    d = _base(g)
    d.update(
        {
            "name": g["name"],
            "home_state_code": g["home_state_code"],
            "sales_tax_rate_bps": g["sales_tax_rate_bps"],
            "resale_exempt_threshold_cents": g["resale_exempt_threshold_cents"],
            "default_consignment_split_bps": g["default_consignment_split_bps"],
            "clock_utc": clockmod.format_iso_clock(DB.clock_utc),
        }
    )
    return d


def ser_artist(a):
    accrued, paid, payable = artist_ledger(a["id"])
    d = _base(a)
    d.update(
        {
            "gallery_id": a["gallery_id"],
            "full_name": a["full_name"],
            "split_override_bps": a.get("split_override_bps"),
            "status": a["status"],
            "ledger_accrued_cents": accrued,
            "ledger_paid_cents": paid,
            "ledger_payable_cents": payable,
        }
    )
    return d


def ser_artwork(aw):
    d = _base(aw)
    d.update(
        {
            "gallery_id": aw["gallery_id"],
            "artist_id": aw["artist_id"],
            "title": aw["title"],
            "list_price_cents": aw["list_price_cents"],
            "insured_value_cents": aw["insured_value_cents"],
            "provenance_count": aw["provenance_count"],
            "provenance_log": [dict(e) for e in aw["provenance_log"]],
            "status": aw["status"],
        }
    )
    return d


def ser_exhibition(ex):
    occupied, available = exhibition_slot_counts(ex["id"], ex["wall_capacity"])
    d = _base(ex)
    d.update(
        {
            "gallery_id": ex["gallery_id"],
            "title": ex["title"],
            "wall_capacity": ex["wall_capacity"],
            "opens_utc": clockmod.format_iso_clock(ex["opens_utc"]),
            "closes_utc": clockmod.format_iso_clock(ex["closes_utc"]),
            "status": ex["status"],
            "slots_occupied": occupied,
            "slots_available": available,
        }
    )
    return d


def ser_wall_slot(ws):
    d = _base(ws)
    d.update(
        {
            "gallery_id": ws["gallery_id"],
            "exhibition_id": ws["exhibition_id"],
            "artwork_id": ws["artwork_id"],
            "wall_label": ws["wall_label"],
            "position_index": ws["position_index"],
            "status": ws["status"],
        }
    )
    return d


def ser_sale(s):
    d = _base(s)
    d.update(
        {
            "gallery_id": s["gallery_id"],
            "artwork_id": s["artwork_id"],
            "exhibition_id": s.get("exhibition_id"),
            "buyer_name": s["buyer_name"],
            "buyer_state_code": s["buyer_state_code"],
            "gross_amount_cents": s["gross_amount_cents"],
            "discount_bps": s["discount_bps"],
            "shipping_cents": s["shipping_cents"],
            "net_amount_cents": s["net_amount_cents"],
            "tax_amount_cents": s["tax_amount_cents"],
            "buyer_total_cents": s["buyer_total_cents"],
            "artist_share_cents": s["artist_share_cents"],
            "gallery_share_cents": s["gallery_share_cents"],
            "amount_collected_cents": s["amount_collected_cents"],
            "settlement_status": s["settlement_status"],
            "shipping_status": s["shipping_status"],
        }
    )
    return d


def ser_payment_plan(p):
    d = _base(p)
    d.update(
        {
            "gallery_id": p["gallery_id"],
            "sale_id": p["sale_id"],
            "installment_count": p["installment_count"],
            "cadence_days": p["cadence_days"],
            "first_due_utc": clockmod.format_iso_clock(p["first_due_utc"]),
            "installment_cents": p["installment_cents"],
            "final_installment_cents": p["final_installment_cents"],
            "posted_installment_count": p["posted_installment_count"],
            "missed_installment_count": plan_missed_count(p),
            "status": p["status"],
        }
    )
    return d


def ser_lease(l):
    months, rent, buyout = compute_lease_figures(l)
    d = _base(l)
    d.update(
        {
            "gallery_id": l["gallery_id"],
            "artwork_id": l["artwork_id"],
            "lessee_name": l["lessee_name"],
            "monthly_rate_cents": l["monthly_rate_cents"],
            "term_months": l["term_months"],
            "starts_utc": clockmod.format_iso_clock(l["starts_utc"]),
            "purchase_credit_bps": l["purchase_credit_bps"],
            "months_accrued": months,
            "rent_accrued_cents": rent,
            "buyout_price_cents": buyout,
            "status": l["status"],
        }
    )
    return d


def ser_opening_event(ev):
    confirmed, waitlist = event_counts(ev["id"])
    d = _base(ev)
    d.update(
        {
            "gallery_id": ev["gallery_id"],
            "exhibition_id": ev["exhibition_id"],
            "capacity": ev["capacity"],
            "starts_utc": clockmod.format_iso_clock(ev["starts_utc"]),
            "rsvp_deadline_utc": clockmod.format_iso_clock(ev["rsvp_deadline_utc"]),
            "confirmed_count": confirmed,
            "waitlist_count": waitlist,
            "status": ev["status"],
        }
    )
    return d


def ser_rsvp(r):
    d = _base(r)
    d.update(
        {
            "gallery_id": r["gallery_id"],
            "opening_event_id": r["opening_event_id"],
            "guest_name": r["guest_name"],
            "party_size": r["party_size"],
            "status": r["status"],
        }
    )
    return d


def ser_loan(l):
    d = _base(l)
    d.update(
        {
            "gallery_id": l["gallery_id"],
            "artwork_id": l["artwork_id"],
            "borrower_name": l["borrower_name"],
            "coverage_value_cents": l["coverage_value_cents"],
            "out_utc": clockmod.format_iso_clock(l["out_utc"]),
            "due_utc": clockmod.format_iso_clock(l["due_utc"]),
            "returned_utc": clockmod.format_iso_clock(l["returned_utc"])
            if l.get("returned_utc")
            else None,
            "status": l["status"],
        }
    )
    return d


def ser_payout(p):
    d = _base(p)
    d.update(
        {
            "gallery_id": p["gallery_id"],
            "artist_id": p["artist_id"],
            "requested_cents": p["requested_cents"],
            "approved_cents": p["approved_cents"],
            "status": p["status"],
        }
    )
    return d


# ---------------------------------------------------------------------------
# Provenance helper
# ---------------------------------------------------------------------------
def _append_provenance_entry(artwork, event_text):
    seq = artwork["provenance_count"] + 1
    artwork["provenance_log"].append(
        {
            "seq": seq,
            "event": event_text,
            "at_utc": clockmod.format_iso_clock(DB.clock_utc),
        }
    )
    artwork["provenance_count"] = seq


def seed_provenance(artwork, event_text):
    """Append the creation-time provenance entry WITHOUT bumping version.

    A freshly consigned artwork must read version == 1 and provenance_count == 1
    (the CONSIGNED entry is part of creation, not a separate mutation).
    """
    _append_provenance_entry(artwork, event_text)


def append_provenance(artwork, event_text):
    """Append a provenance entry as a mutation (refresh updated_at, bump version)."""
    _append_provenance_entry(artwork, event_text)
    touch(artwork)
