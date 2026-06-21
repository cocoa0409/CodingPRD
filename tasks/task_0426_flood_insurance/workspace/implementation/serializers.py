"""Entity -> response-dict serializers.

Records are stored as plain dicts already shaped close to the output contract;
serializers return shallow copies so callers cannot mutate the store.
"""


def serialize_community(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "name": c["name"],
        "county_code": c["county_code"],
        "participating": c["participating"],
        "crs_class": c["crs_class"],
        "crs_discount_pct": c["crs_discount_pct"],
    }


def serialize_property(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "community_id": p["community_id"],
        "owner_id": p["owner_id"],
        "address": p["address"],
        "flood_zone": p["flood_zone"],
        "is_sfha": p["is_sfha"],
        "occupancy": p["occupancy"],
        "base_flood_elevation_ft": p["base_flood_elevation_ft"],
        "has_active_mortgage": p["has_active_mortgage"],
        "loss_history_count": p["loss_history_count"],
        "is_repetitive_loss": p["is_repetitive_loss"],
        "compliance_status": p["compliance_status"],
        "active_policy_id": p["active_policy_id"],
    }


def serialize_elevation_certificate(e):
    # Immutable evidence record: only id + created_at common fields.
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "property_id": e["property_id"],
        "surveyor_license": e["surveyor_license"],
        "lowest_floor_elevation_ft": e["lowest_floor_elevation_ft"],
        "freeboard_ft": e["freeboard_ft"],
        "superseded": e["superseded"],
    }


def serialize_policy(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "property_id": p["property_id"],
        "holder_id": p["holder_id"],
        "rating_method": p["rating_method"],
        "building_coverage": p["building_coverage"],
        "contents_coverage": p["contents_coverage"],
        "building_deductible": p["building_deductible"],
        "contents_deductible": p["contents_deductible"],
        "is_lender_required": p["is_lender_required"],
        "status": p["status"],
        "quoted_premium": p["quoted_premium"],
        "bind_date": p["bind_date"],
        "effective_date": p["effective_date"],
        "expiration_date": p["expiration_date"],
        "earned_premium": p["earned_premium"],
        "premium_credit_balance": p["premium_credit_balance"],
        "total_claims_paid": p["total_claims_paid"],
        "refund_to_holder": p.get("refund_to_holder", 0),
    }


def serialize_claim(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "policy_id": c["policy_id"],
        "claimant_id": c["claimant_id"],
        "date_of_loss": c["date_of_loss"],
        "building_loss": c["building_loss"],
        "contents_loss": c["contents_loss"],
        "depreciation_pct": c["depreciation_pct"],
        "substantial_damage": c["substantial_damage"],
        "icc_eligible_cost": c["icc_eligible_cost"],
        "status": c["status"],
        "settlement_total": c["settlement_total"],
        "building_payable": c["building_payable"],
        "contents_payable": c["contents_payable"],
        "icc_payable": c["icc_payable"],
    }


def serialize_proof_of_loss(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "claim_id": p["claim_id"],
        "documented_building_loss": p["documented_building_loss"],
        "documented_contents_loss": p["documented_contents_loss"],
        "filed_at": p["filed_at"],
        "days_after_loss": p["days_after_loss"],
        "review_status": p["review_status"],
    }


def serialize_policy_transfer(t):
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
        "from_policy_id": t["from_policy_id"],
        "new_owner_id": t["new_owner_id"],
        "superseded_policy_id": t["superseded_policy_id"],
        "credited_amount": t["credited_amount"],
        "effective_at": t["effective_at"],
    }
