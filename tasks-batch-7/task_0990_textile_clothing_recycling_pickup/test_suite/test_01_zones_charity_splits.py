"""Zone onboarding, resident enrolment, charity-split configuration, and zone OCC."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS,
    new_zone, new_charity, new_resident, set_zone_splits, read_zone,
    create_resident_payload, charity_split_payload,
)

OP = TEST_USERS["zone_operator_headers"]


def test_create_zone_applies_defaults(api):
    """PRD §3.1: "At creation the zone's `charity_splits` defaults to an empty array,
    meaning no charitable split is configured until the operator defines one."
    PRD §2.4: "The `version` is a server-managed integer that starts at its initial
    value on creation and increments by one on every mutation; clients use it for
    optimistic concurrency."

    Design: Corner/entities/create_zone_applies_defaults
    """
    resp = api_client.create_zone({"name": "Zone E1"}, OP)
    zone = validate_success(resp, 201)
    assert zone["charity_splits"] == [], f"expected empty splits default, got {zone['charity_splits']}"
    assert isinstance(zone["version"], int) and zone["version"] >= 0
    assert zone["id"] and zone["created_at"] and zone["updated_at"]


def test_resident_fk_requires_existing_zone(api):
    """PRD §2.5: "Identifiers referenced in the request body — for example the
    `zone_id` on a resident or sponsor fund, the `resident_id` on a bag kit or
    pickup, or each `charity_id` inside a `charity_splits` line — are subject to
    the same existence rule and are likewise rejected with `ERR_NOT_FOUND` when
    they do not resolve."

    Design: Corner/entities/resident_fk_requires_existing_zone
    """
    payload = create_resident_payload(NON_EXISTENT_UUID, full_name="Seth S", email="seth@x.com")
    resp = api_client.create_resident(payload, OP)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_get_resident_not_found_returns_404(api):
    """PRD §2.5: "A request whose leftmost identifier is unknown is rejected with
    `ERR_NOT_FOUND` (HTTP 404) before any deeper checks are evaluated."

    Design: Corner/entities/get_resident_not_found_returns_404
    """
    resp = api_client.get_resident(NON_EXISTENT_UUID, OP)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_split_sum_over_100_rejected(api):
    """PRD §3.1: "The same charity may not appear twice in one zone's split
    configuration, and the percentages across all lines must sum to no more than
    100; otherwise the update is rejected with `ERR_SPLIT_SUM_INVALID` (HTTP 422)."

    Design: Corner/validations/split_sum_over_100_rejected
    """
    zone = new_zone("Zone V4")
    ch1 = new_charity("ClothesAid")
    ch2 = new_charity("FiberFund")
    payload = charity_split_payload(
        [{"charity_id": ch1["id"], "pct": 60}, {"charity_id": ch2["id"], "pct": 50}],
        zone["version"],
    )
    resp = api_client.replace_charity_split(zone["id"], payload, OP)
    validate_error(resp, ApiErrorId.ERR_SPLIT_SUM_INVALID)
    after = read_zone(zone["id"])
    assert after["charity_splits"] == [], "rejected update must not mutate the split configuration"
    assert after["version"] == zone["version"], "rejected update must not bump the zone version"


def test_charity_split_update_stale_version_returns_412(api):
    """PRD §2.7: "A replace of a `ServiceZone`'s charity split configuration must
    carry `expected_zone_version` equal to the zone's current `version`. A stale
    submission is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful
    update increments the zone's `version` by one and refreshes `updated_at`."

    Design: Corner/cross_cutting_layers/charity_split_update_stale_version_returns_412
    """
    zone = new_zone("Zone XL2")
    ch1 = new_charity("ClothesAid")
    v1 = zone["version"]

    updated = set_zone_splits(zone, [(ch1, 50)])
    assert updated["version"] == v1 + 1, (
        f"successful split update must increment version by one: {v1} -> {updated['version']}"
    )

    stale_payload = charity_split_payload([{"charity_id": ch1["id"], "pct": 25}], v1)
    resp = api_client.replace_charity_split(zone["id"], stale_payload, OP)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    after = read_zone(zone["id"])
    assert after["charity_splits"] == [{"charity_id": ch1["id"], "pct": 50}], (
        f"stale update must not replace the live configuration: {after['charity_splits']}"
    )
