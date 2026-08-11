"""Pre-built role headers for every role in the PRD (§2.1).

Entity-backed roles (Resident, PartnerManager, SponsorManager, CharityAdmin)
MUST use their per-instance builder with the real entity id whenever the call
is ownership-gated. Driver is opaque, but mark-collected / mark-no-show on a
ROUTED pickup bind X-User-ID to the pickup's stored driver_id, so a builder is
provided for it too.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "zone_operator_headers": build_user_headers("test-operator-1", "ZoneOperator"),
    "driver_headers": build_user_headers("drv-1", "Driver"),
    "inspector_headers": build_user_headers("insp-1", "Inspector"),
    "sensor_gateway_headers": build_user_headers("sensor-gw-1", "SensorGateway"),
    # Entity-backed roles — fallback only for tests that do NOT exercise ownership.
    "resident_headers": build_user_headers("test-resident-1", "Resident"),
    "partner_manager_headers": build_user_headers("test-partner-1", "PartnerManager"),
    "sponsor_manager_headers": build_user_headers("test-fund-1", "SponsorManager"),
    "charity_admin_headers": build_user_headers("test-charity-1", "CharityAdmin"),
}


def make_resident_headers(user_id: str) -> dict:
    """Resident is entity-backed: pass the actual Resident.id as user_id."""
    return build_user_headers(user_id, "Resident")


def make_driver_headers(user_id: str) -> dict:
    """Driver is opaque, but ROUTED-pickup collection binds X-User-ID to driver_id."""
    return build_user_headers(user_id, "Driver")


def make_partner_manager_headers(user_id: str) -> dict:
    """PartnerManager is entity-backed: pass the acting Partner.id as user_id."""
    return build_user_headers(user_id, "PartnerManager")


def make_inspector_headers(user_id: str) -> dict:
    """Inspector is opaque; the id is persisted as reported_by on reports."""
    return build_user_headers(user_id, "Inspector")


def make_sponsor_manager_headers(user_id: str) -> dict:
    """SponsorManager is entity-backed: pass the acting SponsorFund.id as user_id."""
    return build_user_headers(user_id, "SponsorManager")


def make_charity_admin_headers(user_id: str) -> dict:
    """CharityAdmin is entity-backed: pass the acting Charity.id as user_id."""
    return build_user_headers(user_id, "CharityAdmin")


def make_sensor_gateway_headers(user_id: str) -> dict:
    """SensorGateway is opaque."""
    return build_user_headers(user_id, "SensorGateway")
