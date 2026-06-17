"""Serialize stored records into response shapes (strip internal fields)."""

# Field order per entity (id/timestamps/version handled by full vs lean shape).
FULL_FIELDS = {
    "Brokerage": ["name", "side", "default_commission_pct"],
    "Broker": ["brokerage_id", "full_name", "license_no", "role", "status"],
    "Property": ["listing_broker_id", "name", "market", "asset_class",
                 "total_sf", "available_sf"],
    "Space": ["property_id", "suite_no", "rentable_sf", "asking_rent_psf_yr",
              "free_rent_months", "ti_allowance_psf", "status", "held_by_tour_id"],
    "Listing": ["space_id", "listing_broker_id", "term_months",
                "annual_escalation_pct", "co_broke_offered_pct", "status",
                "open_deal_count"],
    "Requirement": ["tenant_broker_id", "tenant_name", "market", "asset_class",
                    "min_sf", "max_sf", "max_rent_psf_yr", "status", "match_count"],
    "Tour": ["requirement_id", "tenant_broker_id", "space_id", "window_start",
             "window_end", "status", "holds_space"],
    "Deal": ["listing_id", "requirement_id", "listing_broker_id",
             "procuring_broker_id", "is_co_broke", "stage", "round_count",
             "accepted_proposal_id", "total_consideration", "total_commission"],
    "Proposal": ["deal_id", "from_side", "base_rent_psf_yr", "term_months",
                 "free_rent_months", "ti_allowance_psf", "annual_escalation_pct",
                 "outcome", "net_effective_rent_psf_yr"],
}

LEAN_FIELDS = {
    "CommissionSplit": ["deal_id", "broker_id", "side", "amount"],
    "Comp": ["space_id", "deal_id", "market", "effective_rent_psf_yr",
             "term_months", "executed_at"],
}


def _common_full(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def _common_lean(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
    }


def serialize(entity, rec):
    if rec is None:
        return None
    if entity in FULL_FIELDS:
        out = _common_full(rec)
        for f in FULL_FIELDS[entity]:
            out[f] = rec.get(f)
        return out
    out = _common_lean(rec)
    for f in LEAN_FIELDS[entity]:
        out[f] = rec.get(f)
    return out


def serialize_many(entity, recs):
    return [serialize(entity, r) for r in recs]
