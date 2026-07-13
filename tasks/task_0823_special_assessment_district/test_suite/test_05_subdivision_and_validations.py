"""Subdivision/consolidation benefit-unit conservation, and parcel-creation validations.

Covers difficulty instance benefit_unit_conservation_under_subdivide_then_consolidate and
corner instances subdivide_benefit_units_mismatch_rejected, duplicate_apn_within_district_rejected.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_district, add_parcel, refresh_parcel, list_parcel_children,
    subdivide_payload, create_parcel_payload,
)

ADMIN = TEST_USERS["admin_headers"]


# --- benefit-unit conservation across a subdivide/consolidate round trip ---

def _subdivided_parent(api):
    district = create_district(api, name="DSU", formation_method="BENEFIT_UNITS",
                               total_project_cost_cents=6_000_000)
    parent = add_parcel(api, district["id"], apn="SU-1", owner_name="O1", benefit_units=60)
    validate_success(api.subdivide_parcel(parent["id"], subdivide_payload([
        {"apn": "SU-1-a", "owner_name": "O1a", "benefit_units": 40},
        {"apn": "SU-1-b", "owner_name": "O1b", "benefit_units": 20},
    ]), ADMIN))
    return district, parent


def test_consolidate_restores_parent_active_with_conserved_benefit_units(api):
    """PRD §3.2: "As a compensating action, each child transitions to WITHDRAWN ... while the
    parent is restored to ACTIVE with its remaining_principal_cents unchanged from before the
    split — the benefit-unit total is preserved throughout the round trip."

    Design: Difficulty/compensating_invariant/benefit_unit_conservation_under_subdivide_then_consolidate
    """
    _, parent = _subdivided_parent(api)
    validate_success(api.consolidate_parcel(parent["id"], ADMIN))
    restored = refresh_parcel(api, parent["id"])
    assert restored["status"] == "ACTIVE"
    assert restored["benefit_units"] == 60


def test_consolidate_withdraws_every_child(api):
    """PRD §3.2: "each child transitions to `WITHDRAWN` and its `SCHEDULED` installments
    transition to `CANCELLED`, while the parent is restored to `ACTIVE`".

    Design: Difficulty/compensating_invariant/benefit_unit_conservation_under_subdivide_then_consolidate
    """
    _, parent = _subdivided_parent(api)
    validate_success(api.consolidate_parcel(parent["id"], ADMIN))
    children = list_parcel_children(api, parent["id"])
    assert children, "expected the subdivision children to be listable by parent_parcel_id"
    assert all(child["status"] == "WITHDRAWN" for child in children)


# --- corner: subdivide benefit-unit mismatch ---

def test_subdivide_benefit_units_mismatch_rejected(api):
    """PRD §3.2: "the sum of the children's `benefit_units` must equal the parent's
    `benefit_units` exactly, or the request is rejected with `ERR_BENEFIT_UNITS_MISMATCH`
    (HTTP 422)."

    Design: Corner/validations/subdivide_benefit_units_mismatch_rejected
    """
    district = create_district(api, name="DV2", formation_method="BENEFIT_UNITS",
                               total_project_cost_cents=600_000)
    parent = add_parcel(api, district["id"], apn="V2-1", owner_name="O", benefit_units=60)
    validate_error(api.subdivide_parcel(parent["id"], subdivide_payload([
        {"apn": "V2-1-a", "owner_name": "Oa", "benefit_units": 40},
        {"apn": "V2-1-b", "owner_name": "Ob", "benefit_units": 30},
    ]), ADMIN), ApiErrorId.ERR_BENEFIT_UNITS_MISMATCH.value)
    assert refresh_parcel(api, parent["id"])["status"] == "ACTIVE"


# --- corner: duplicate APN within a district ---

def test_duplicate_apn_within_district_rejected(api):
    """PRD §3.1: "The apn must be unique among the parcels of that district; a collision is
    rejected with ERR_APN_DUPLICATE (HTTP 409)."

    Design: Corner/validations/duplicate_apn_within_district_rejected
    """
    district = create_district(api, name="DV1", formation_method="BENEFIT_UNITS",
                               total_project_cost_cents=500_000)
    add_parcel(api, district["id"], apn="V1-1", owner_name="O", benefit_units=50)
    validate_error(api.create_parcel(district["id"],
                                     create_parcel_payload(apn="V1-1", owner_name="O2", benefit_units=50),
                                     ADMIN),
                   ApiErrorId.ERR_APN_DUPLICATE.value)
