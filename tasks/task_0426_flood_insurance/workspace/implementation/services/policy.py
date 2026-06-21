"""Policy quote pricing helper: resolves the latest non-superseded elevation
certificate for a property and computes the quoted premium via the calculation
service (PRD §3.3, §3.4).
"""

from decimal import Decimal

from db import db
from services.calculations import compute_premium, crs_discount_pct


def latest_freeboard(property_id):
    """Latest non-superseded ElevationCertificate.freeboard_ft for a property by
    created_at, or None when no usable certificate exists.

    Per PRD §3.4 a RR2.0 quote reads the latest non-superseded certificate's
    freeboard. When no such certificate exists, a freeboard of 0 (elevation
    factor 1.00, neutral) is used.
    """
    certs = [e for e in db.elevation_certificates.values()
             if e["property_id"] == property_id and not e["superseded"]]
    if not certs:
        return None
    certs.sort(key=lambda e: e["created_at"])
    return certs[-1]["freeboard_ft"]


def quote_premium(policy, prop, community):
    """Compute quoted_premium for a policy using the property's community CRS
    discount and (RR2.0 only) the latest non-superseded elevation certificate."""
    crs_discount = crs_discount_pct(community["crs_class"])
    freeboard = 0
    if policy["rating_method"] == "RISK_RATING_2_0":
        fb = latest_freeboard(prop["id"])
        freeboard = fb if fb is not None else 0
    return compute_premium(
        policy["rating_method"],
        prop["flood_zone"],
        policy["building_coverage"],
        policy["contents_coverage"],
        prop["occupancy"],
        crs_discount,
        freeboard,
    )
