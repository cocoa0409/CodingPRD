"""Commissioning a station is decided by a field on its parent host site."""
from test_helpers import (
    FULLY_COMPLIANT_PORT,
    OPERATOR_HEADERS,
    ApiErrorId,
    api_client,
    assert_instant_equals,
    read_host_site,
    read_station,
    setup_station,
    validate_error,
    validate_success,
)


def _commissioning_station_under_a_draft_agreement():
    """Every gate on the station itself passes; only the parent site's agreement
    is still in DRAFT."""
    return setup_station(
        clock="2026-06-04T09:00:00Z",
        site_code="HS-XD-1",
        station_code="ST-XD-1",
        committed_service_capacity_kw=400.00,
        power_class="DCFC_150",
        declared_port_count=1,
        host_site_overrides={"agreement_status": "DRAFT"},
        ports=[dict(FULLY_COMPLIANT_PORT, dispenser_serial="DS-XD-1", connector_type="CCS1")],
        stop_at="COMMISSIONING",
    )


def test_a_draft_host_agreement_blocks_an_otherwise_flawless_commission():
    """The commission call never names the host site, yet the host site decides it.

    PRD §3.3, gate 1: "The host site's `agreement_status` must be `EXECUTED`;
    otherwise `ERR_HOST_AGREEMENT_NOT_EXECUTED`."

    Design: Difficulty/cross_entity_state_dependency/station_commission_blocked_until_host_site_agreement_is_executed
    """
    scenario = _commissioning_station_under_a_draft_agreement()
    station_id = scenario["station"]["id"]

    response = api_client.commission_station(station_id, OPERATOR_HEADERS)

    validate_error(response, ApiErrorId.ERR_HOST_AGREEMENT_NOT_EXECUTED, 422)

    station = read_station(station_id)
    assert station["status"] == "COMMISSIONING"
    assert station["commissioned_at"] is None
    assert float(station["payment_interop_score"]) == 100.00, (
        "the block came from the parent site, not from the interoperability gate"
    )


def test_executing_the_parent_agreement_unblocks_the_identical_commission_call():
    """Nothing on the station changes between the two attempts.

    PRD §3.3: once the gates clear, commissioning "advances `COMMISSIONING →
    OPERATIONAL`" and "the station stamps `commissioned_at` from the logical
    clock".

    Design: Difficulty/cross_entity_state_dependency/station_commission_blocked_until_host_site_agreement_is_executed
    """
    scenario = _commissioning_station_under_a_draft_agreement()
    station_id = scenario["station"]["id"]
    host_site_id = scenario["host_site"]["id"]

    api_client.commission_station(station_id, OPERATOR_HEADERS)

    validate_success(
        api_client.update_host_site(
            host_site_id, {"agreement_status": "EXECUTED"}, OPERATOR_HEADERS
        )
    )
    assert read_host_site(host_site_id)["agreement_status"] == "EXECUTED"

    data = validate_success(api_client.commission_station(station_id, OPERATOR_HEADERS))

    assert data["status"] == "OPERATIONAL"
    assert data["suspension_source"] == "NONE"
    assert_instant_equals(data["commissioned_at"], "2026-06-04T09:00:00Z", "commissioned_at")
