"""Public serialization of stored records. Strips internal fields and renders
money fields as JSON numbers (PRD §2.5)."""
from services.calculations import to_number

# Money fields per entity that must be rendered as 2-dp JSON numbers.
_BOOKING_MONEY = (
    "quote_subtotal", "deposit_due", "balance_due", "travel_fee",
    "final_subtotal", "amount_paid", "amount_refunded",
)


def _strip(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}


def booking_out(b):
    out = _strip(b)
    for f in _BOOKING_MONEY:
        if out.get(f) is not None:
            out[f] = to_number(out[f])
    return out


def package_out(p):
    out = _strip(p)
    for f in ("base_price", "overtime_rate_per_hour", "idle_rate_per_hour", "overage_print_rate"):
        if out.get(f) is not None:
            out[f] = to_number(out[f])
    return out


def addon_out(a):
    out = _strip(a)
    if out.get("unit_price") is not None:
        out["unit_price"] = to_number(out["unit_price"])
    return out


def addon_line_out(l):
    out = _strip(l)
    if out.get("line_total") is not None:
        out["line_total"] = to_number(out["line_total"])
    return out


def payment_out(p):
    out = _strip(p)
    if out.get("amount") is not None:
        out["amount"] = to_number(out["amount"])
    return out


def plain_out(record):
    return _strip(record)
