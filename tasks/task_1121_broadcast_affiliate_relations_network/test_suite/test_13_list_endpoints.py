"""List / FK reverse-reachability endpoints (corner: endpoints section)."""
import pytest

from test_helpers import (
    create_agreement_payload,
    create_network_payload,
    create_station_group_payload,
    create_station_payload,
    get_success_data,
    make_nar_headers,
    make_platform_admin_headers,
    setup_clock,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client


class TestListAgreementsForStation:
    def test_list_agreements_scoped_to_station(self, api):
        """PRD §2.5: "the corresponding list endpoints accept foreign-key
        filters ... to traverse relationships in reverse."
        PRD §4: GET /networks/{nid}/stations/{sid}/agreements "List
        agreements for a station".

        Design: Corner/endpoints/fk_reverse_reachability_list_agreements
        """
        setup_clock("2026-05-01T00:00:00Z")
        admin = make_platform_admin_headers()
        nar = make_nar_headers()
        net = get_success_data(api_client.create_network(create_network_payload(), admin))
        grp = get_success_data(
            api_client.create_station_group(create_station_group_payload(), admin)
        )
        station = get_success_data(
            api_client.create_station(
                net["id"], create_station_payload(station_group_id=grp["id"]), nar
            )
        )
        # Two agreements, both on this station.
        get_success_data(
            api_client.create_agreement(net["id"], station["id"],
                                        create_agreement_payload(), nar)
        )
        get_success_data(
            api_client.create_agreement(
                net["id"], station["id"],
                create_agreement_payload(
                    term_start_utc="2027-01-01T00:00:00Z",
                    term_end_utc="2028-01-01T00:00:00Z",
                ),
                nar,
            )
        )
        resp = api_client.list_agreements(net["id"], station["id"], nar)
        data_list, meta = validate_paginated(resp)
        assert meta["total_count"] == 2, (
            f"Station has exactly 2 agreements; total_count={meta['total_count']}"
        )
        assert len(data_list) == 2
