"""Resource serialisation. Derived counters are computed at read time."""
import db
from services import derive


def plain(record):
    return db.public(record)


organizer = plain
venue = plain
buyer = plain
event = plain
promo_code_base = plain


def ticket_type(record):
    data = db.public(record)
    sold = derive.tier_sold(record["id"])
    held = derive.tier_held(record["id"])
    data["sold_count"] = sold
    data["held_count"] = held
    data["available"] = record["quantity_total"] - sold - held
    data["available_count"] = data["available"]
    return data


def seat_block(record):
    data = db.public(record)
    data["seats_total"] = record["seat_to"] - record["seat_from"] + 1
    data["seats_taken"] = derive.seats_taken(record["id"])
    return data


def promo_code(record):
    data = db.public(record)
    data["uses_count"] = derive.promo_uses(record["id"])
    return data


order = plain
order_item = plain
attendee = plain
scan = plain
refund_request = plain
transfer_request = plain
waitlist_entry = plain
payout = plain
