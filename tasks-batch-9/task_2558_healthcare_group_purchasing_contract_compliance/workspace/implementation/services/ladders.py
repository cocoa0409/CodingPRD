"""Tier ladder and holdback ladder well-formedness (PRD section 3.1)."""

from decimal import Decimal

from errors import ApiError
from validation import bad, field_decimal, field_int, field_string

ZERO = Decimal("0.00")


def _tier_ladder_error(message):
    return ApiError("ERR_INVALID_TIER_LADDER", message)


def _holdback_ladder_error(message):
    return ApiError("ERR_INVALID_HOLDBACK_LADDER", message)


def _wrap(entry, label, name):
    """Present one nested field to the scalar validators under a clear label."""
    return {"%s.%s" % (label, name): entry.get(name)}


def parse_tier_ladder(body, key="tiers"):
    """Validate and normalise the tier ladder; returns the stored entries."""
    if key not in body or body[key] is None:
        raise bad("Field '%s' is required." % key)
    raw = body[key]
    if not isinstance(raw, list):
        raise bad("Field '%s' must be an array." % key)

    entries = []
    for index, entry in enumerate(raw):
        label = "%s[%d]" % (key, index)
        if not isinstance(entry, dict):
            raise bad("Field '%s' must be an object." % label)
        tier_code = field_string(_wrap(entry, label, "tier_code"), "%s.tier_code" % label, 1, 40)
        min_volume = field_int(
            _wrap(entry, label, "min_committed_volume_units"),
            "%s.min_committed_volume_units" % label,
            minimum=0,
        )
        min_compliance = field_decimal(
            _wrap(entry, label, "min_compliance_pct"),
            "%s.min_compliance_pct" % label,
            minimum=Decimal("0.00"),
            maximum=Decimal("100.00"),
            scale=2,
        )
        discount_bps = field_int(
            _wrap(entry, label, "discount_bps"),
            "%s.discount_bps" % label,
            minimum=0,
            maximum=5000,
        )
        entries.append(
            {
                "tier_code": tier_code,
                "min_committed_volume_units": min_volume,
                "min_compliance_pct": min_compliance,
                "discount_bps": discount_bps,
            }
        )

    # A ladder that is empty or exceeds five entries is malformed.
    if len(entries) < 1 or len(entries) > 5:
        raise _tier_ladder_error("The tier ladder carries one to five entries.")

    defaults = [
        entry
        for entry in entries
        if entry["min_committed_volume_units"] == 0 and entry["min_compliance_pct"] == ZERO
    ]
    if len(defaults) != 1:
        raise _tier_ladder_error(
            "The tier ladder must carry exactly one default entry with "
            "min_committed_volume_units 0 and min_compliance_pct 0.00."
        )

    ordered_entries = sorted(entries, key=lambda entry: entry["min_committed_volume_units"])
    previous = None
    for entry in ordered_entries:
        if previous is not None and entry["discount_bps"] <= previous["discount_bps"]:
            raise _tier_ladder_error(
                "discount_bps must increase strictly with min_committed_volume_units."
            )
        previous = entry

    codes = [entry["tier_code"] for entry in entries]
    if len(set(codes)) != len(codes):
        raise ApiError("ERR_DUPLICATE_TIER_CODE", "tier_code must be unique in the ladder.")

    return entries


def parse_holdback_ladder(body, key="holdback_tiers"):
    """Validate and normalise the holdback ladder; returns stored entries."""
    if key not in body or body[key] is None:
        raise bad("Field '%s' is required." % key)
    raw = body[key]
    if not isinstance(raw, list):
        raise _holdback_ladder_error("The holdback ladder must be an array.")
    if len(raw) < 1 or len(raw) > 4:
        raise _holdback_ladder_error("The holdback ladder carries one to four entries.")

    entries = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise _holdback_ladder_error("Each holdback ladder entry must be an object.")
        minimum = entry.get("min_gross_pool_cents")
        bps = entry.get("holdback_bps")
        if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 0:
            raise _holdback_ladder_error(
                "min_gross_pool_cents must be an integer of zero or greater."
            )
        if isinstance(bps, bool) or not isinstance(bps, int) or bps < 0 or bps > 1000:
            raise _holdback_ladder_error("holdback_bps must be an integer between 0 and 1000.")
        entries.append({"min_gross_pool_cents": minimum, "holdback_bps": bps})

    thresholds = [entry["min_gross_pool_cents"] for entry in entries]
    if len(set(thresholds)) != len(thresholds):
        raise _holdback_ladder_error("min_gross_pool_cents must be unique in the ladder.")

    ordered_entries = sorted(entries, key=lambda entry: entry["min_gross_pool_cents"])
    previous = None
    for entry in ordered_entries:
        if previous is not None and entry["holdback_bps"] < previous["holdback_bps"]:
            raise _holdback_ladder_error(
                "holdback_bps must be non-decreasing across the ladder."
            )
        previous = entry

    return entries
