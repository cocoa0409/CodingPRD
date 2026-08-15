"""Commission schedule windows: half-open overlap semantics and product OCC."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_carrier,
    create_product,
    create_schedule,
    create_schedule_payload,
    get_product_version,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def _product():
    carrier = create_carrier(name="Carrier W", carrier_code="CW")
    return create_product(carrier["id"], product_code="PW", name="Product W")


class TestScheduleHalfOpenAdjacency:
    """Difficulty instance: half-open schedule windows — touching boundaries
    are free, interior intersections are rejected."""

    def test_adjacent_windows_accepted(self):
        """PRD §3.2: "The window is a half-open interval: a new schedule whose
        `effective_from` falls exactly on an existing same-tier schedule's
        `effective_to` does not overlap it."

        Design: Difficulty/resource_temporal_overlap/schedule_half_open_adjacency
        """
        product = _product()
        first = create_schedule(
            product["id"],
            tier="STANDARD",
            commission_rate_bps=5000,
            effective_from="2026-01-01",
            effective_to="2027-01-01",
            supersede_existing=False,
        )
        assert first["status"] == "ACTIVE"

        second = create_schedule(
            product["id"],
            tier="STANDARD",
            commission_rate_bps=5200,
            effective_from="2027-01-01",
            supersede_existing=False,
        )
        assert second["status"] == "ACTIVE"
        assert second["effective_from"] == "2027-01-01"
        assert second["id"] != first["id"]

    def test_interior_overlap_rejected(self):
        """PRD §3.2: "When `supersede_existing` is not set, a new same-tier
        schedule whose half-open window intersects an existing same-tier
        window on the same product is rejected with
        `ERR_SCHEDULE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/schedule_half_open_adjacency
        """
        product = _product()
        create_schedule(
            product["id"],
            tier="STANDARD",
            commission_rate_bps=5000,
            effective_from="2026-01-01",
            effective_to="2027-01-01",
            supersede_existing=False,
        )
        create_schedule(
            product["id"],
            tier="STANDARD",
            commission_rate_bps=5200,
            effective_from="2027-01-01",
            supersede_existing=False,
        )
        res = api_client.create_commission_schedule(
            product["id"],
            create_schedule_payload(
                tier="STANDARD",
                commission_rate_bps=5400,
                advance_months=12,
                effective_from="2026-06-01",
                effective_to="2026-12-01",
                supersede_existing=False,
                expected_product_version=get_product_version(product["id"]),
            ),
            ADMIN,
        )
        validate_error(
            res, ApiErrorId.ERR_SCHEDULE_WINDOW_OVERLAP, expected_status=409
        )


class TestScheduleCreateOcc:
    def test_stale_product_version_rejected(self):
        """PRD §2.7: "Creating a commission schedule requires the request to
        carry `expected_product_version`, holding the client last-observed
        `version` of the parent product. If the product's current `version`
        has advanced beyond what the client observed — for example because
        another writer has just created a superseding schedule, which
        legitimately retires the prior schedule and advances the product's
        version — the create is rejected with `ERR_STALE_VERSION` (HTTP 412),
        so the client cannot price against a schedule set it has not
        observed."
        PRD §3.2: "Creating any schedule advances the parent product's
        `version` by one."

        Design: Corner/cross_cutting_layers/occ_schedule_create_stale_version
        """
        product = _product()
        observed_version = product["version"]

        first = validate_success(
            api_client.create_commission_schedule(
                product["id"],
                create_schedule_payload(
                    tier="STANDARD",
                    commission_rate_bps=5000,
                    advance_months=12,
                    effective_from="2026-01-01",
                    expected_product_version=observed_version,
                ),
                ADMIN,
            ),
            201,
        )
        assert first["status"] == "ACTIVE"

        res = api_client.create_commission_schedule(
            product["id"],
            create_schedule_payload(
                tier="GOLD",
                commission_rate_bps=6000,
                advance_months=12,
                effective_from="2026-01-01",
                expected_product_version=observed_version,
            ),
            ADMIN,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        product_after = validate_success(
            api_client.get_product(product["id"], ADMIN), 200
        )
        assert product_after["version"] == observed_version + 1, (
            "the rejected create must not advance the product version"
        )
