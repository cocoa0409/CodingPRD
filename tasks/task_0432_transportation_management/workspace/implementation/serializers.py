"""Public serialization of entities, including recompute-on-read of derived
fields (PRD §2.5: a GET always reflects the current truth)."""
import calculations as calc
from helpers import clean


def carrier_view(carrier):
    """Recompute on_time_pct and scorecard_grade from the live counters (PRD §3.1)."""
    out = clean(carrier)
    out["on_time_pct"] = calc.on_time_pct(carrier)
    out["scorecard_grade"] = calc.scorecard_grade(carrier)
    return out


def rate_view(rate):
    return clean(rate)


def order_view(order):
    return clean(order)


def shipment_view(shipment):
    return clean(shipment)


def tender_view(tender):
    return clean(tender)


def load_view(load):
    """Recompute consolidated_weight_lbs from live shipments (PRD §3.6)."""
    out = clean(load)
    out["consolidated_weight_lbs"] = calc.consolidated_weight(load)
    return out


def appt_view(appt):
    return clean(appt)


def invoice_view(invoice):
    return clean(invoice)


def claim_view(claim):
    return clean(claim)
