"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "COMMUNITY_NAME": "Test Community",
    "COUNTY_CODE": "C000",
    "SURVEYOR_LICENSE": "SURV-TEST",
    "ADDRESS": "1 Test St",
}


def create_community_payload(**overrides) -> dict:
    """POST /communities input fields. crs_class and participating are optional
    (server defaults: participating true, crs_class 10)."""
    defaults = {
        "name": DEFAULTS["COMMUNITY_NAME"],
        "county_code": DEFAULTS["COUNTY_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(community_id: str, owner_id: str, **overrides) -> dict:
    """POST /properties input fields. has_active_mortgage is optional (default false)."""
    defaults = {
        "community_id": community_id,
        "owner_id": owner_id,
        "address": DEFAULTS["ADDRESS"],
        "flood_zone": "AE",
        "occupancy": "PRIMARY_RESIDENCE",
        "base_flood_elevation_ft": 8.0,
    }
    defaults.update(overrides)
    return defaults


def create_elevation_certificate_payload(property_id: str, **overrides) -> dict:
    """POST /elevation-certificates input fields. superseded is optional (default false)."""
    defaults = {
        "property_id": property_id,
        "surveyor_license": DEFAULTS["SURVEYOR_LICENSE"],
        "lowest_floor_elevation_ft": 10.0,
    }
    defaults.update(overrides)
    return defaults


def create_policy_quote_payload(rating_method: str, **overrides) -> dict:
    """POST /properties/{id}/policies input fields. Deductibles and is_lender_required
    are optional (server defaults: building_deductible 2000, contents_deductible 1000,
    is_lender_required false)."""
    defaults = {
        "rating_method": rating_method,
        "building_coverage": 100000,
        "contents_coverage": 40000,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(policy_id: str, claimant_id: str, date_of_loss: str, **overrides) -> dict:
    """POST /claims input fields. building_loss, contents_loss, depreciation_pct,
    substantial_damage, icc_eligible_cost are optional (server defaults 0/0/0/false/0)."""
    defaults = {
        "policy_id": policy_id,
        "claimant_id": claimant_id,
        "date_of_loss": date_of_loss,
    }
    defaults.update(overrides)
    return defaults


def create_proof_of_loss_payload(claim_id: str, **overrides) -> dict:
    """POST /proofs-of-loss input fields. documented_building_loss and
    documented_contents_loss are optional (default 0)."""
    defaults = {
        "claim_id": claim_id,
    }
    defaults.update(overrides)
    return defaults


def create_policy_transfer_payload(from_policy_id: str, new_owner_id: str,
                                   expected_policy_version: int, **overrides) -> dict:
    """POST /policy-transfers input fields."""
    defaults = {
        "from_policy_id": from_policy_id,
        "new_owner_id": new_owner_id,
        "expected_policy_version": expected_policy_version,
    }
    defaults.update(overrides)
    return defaults
