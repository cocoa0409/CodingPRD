"""OTA collection agreements: half-open coverage overlap (with adjacency allowed)
and the registered-platform activation guard."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_ota_agreement,
    TEST_USERS,
    create_active_operator, create_ota_platform, create_ota_agreement, activate_ota_agreement,
)

ADMIN = TEST_USERS["taxadmin_headers"]


# ============================================================
# Difficulty: resource_temporal_overlap/ota_agreement_half_open_overlap_adjacency
# ============================================================
def _operator_platform_with_active_a(api):
    op = create_active_operator(api)
    plat = create_ota_platform(api, name="BookIt", registered=True)
    ag_a = create_ota_agreement(api, op["id"], plat["id"], collection_method="GROSS",
                                effective_date="2026-01-01T00:00:00Z", end_date="2026-04-01T00:00:00Z")
    activate_ota_agreement(api, ag_a["id"])
    return op, plat


def test_overlapping_coverage_activate_rejected(api):
    """PRD 3.3: "the agreement's coverage interval, treated as the half-open span from
    `effective_date` (inclusive) up to `end_date` (exclusive), must not overlap any
    other already-`ACTIVE` agreement for the same operator-and-platform pair, or it is
    rejected with `ERR_AGREEMENT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/ota_agreement_half_open_overlap_adjacency
    """
    op, plat = _operator_platform_with_active_a(api)
    ag_b = create_ota_agreement(api, op["id"], plat["id"], collection_method="GROSS",
                                effective_date="2026-03-01T00:00:00Z", end_date="2026-06-01T00:00:00Z")
    resp = api.activate_ota_agreement(ag_b["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_OVERLAP.value)
    assert validate_success(api.get_ota_agreement(ag_b["id"], ADMIN), 200)["status"] == "PROPOSED"


def test_adjacent_coverage_activates_cleanly(api):
    """PRD 3.3: "the agreement's coverage interval, treated as the half-open span from
    `effective_date` (inclusive) up to `end_date` (exclusive), must not overlap any
    other already-`ACTIVE` agreement for the same operator-and-platform pair".

    Design: Difficulty/resource_temporal_overlap/ota_agreement_half_open_overlap_adjacency
    """
    op, plat = _operator_platform_with_active_a(api)
    ag_c = create_ota_agreement(api, op["id"], plat["id"], collection_method="GROSS",
                                effective_date="2026-04-01T00:00:00Z", end_date="2026-07-01T00:00:00Z")
    data = validate_success(api.activate_ota_agreement(ag_c["id"], ADMIN), 200)
    assert_ota_agreement(data)
    assert data["status"] == "ACTIVE"


# ---- Corner: validations/platform_not_registered_blocks_agreement_activate ----
def test_unregistered_platform_blocks_activation(api):
    """PRD 3.3: "the referenced platform's `registered` flag must be true, or the
    request is rejected with `ERR_PLATFORM_NOT_REGISTERED`".

    Design: Corner/validations/platform_not_registered_blocks_agreement_activate
    """
    op = create_active_operator(api)
    plat = create_ota_platform(api, name="Unreg", registered=False)
    ag = create_ota_agreement(api, op["id"], plat["id"], collection_method="NET",
                              effective_date="2026-01-01T00:00:00Z", end_date="2026-04-01T00:00:00Z")
    resp = api.activate_ota_agreement(ag["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PLATFORM_NOT_REGISTERED.value)
    assert validate_success(api.get_ota_agreement(ag["id"], ADMIN), 200)["status"] == "PROPOSED"
