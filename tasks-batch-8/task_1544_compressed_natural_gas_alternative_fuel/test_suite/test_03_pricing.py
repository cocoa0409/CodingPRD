"""Pricing policy lifecycle, supersede semantics, and OCC on the station
(PRD §2.9, §3.2, §3.4)."""
from test_helpers import (
    ApiErrorId,
    authorize_session,
    create_active_station,
    create_fleet_account,
    create_fleet_card,
    create_pricing_policy,
    get_station_version,
    validate_error,
    validate_success,
)


class TestPolicySupersede:
    def test_pricing_policy_create_supersedes_same_key(self, api, network_operator_headers):
        """PRD §3.2: "If an ACTIVE policy already exists with the same station,
        scope, and fuel key, that prior policy is immediately SUPERSEDED and
        its `version` increments by one, so at most one ACTIVE policy ever
        exists for a given key; creation also increments the station's
        `version` by one."
        PRD §3.4: "Otherwise the system selects the ACTIVE pricing policy
        matching the station, an `access_scope` equal to the session's
        `access_type`, and a `fuel_type` equal to the dispensing unit's fuel,
        whose window contains the current instant (`effective_from` inclusive,
        `effective_to` exclusive)."

        Design: Corner/state_machines/pricing_policy_create_supersedes_same_key
        """
        env = create_active_station(station_name="Sup", station_code="ST-SUP")
        station_id = env["station"]["id"]
        p1 = create_pricing_policy(station_id, price_per_gge_cents=289)
        account = create_fleet_account(account_name="Sup Co")
        card = create_fleet_card(account["id"], daily_gge_limit=100.0)

        p2 = create_pricing_policy(station_id, price_per_gge_cents=319)
        p1_after = validate_success(api.get_pricing_policy(p1["id"], network_operator_headers), 200)
        assert p1_after["status"] == "SUPERSEDED"
        assert p2["status"] == "ACTIVE"

        resp = authorize_session(card["id"], env["dispensers"][0]["id"], "CR-SU1", 10.0)
        session = validate_success(resp, 201)
        assert session["unit_price_cents"] == 319, (
            "replacement policy price resolved at authorize"
        )


class TestPolicyOcc:
    def test_occ_stale_station_version_on_policy_create_returns_412(
        self, api, network_operator_headers
    ):
        """PRD §2.9: "Creating a pricing policy through
        `POST /cng/pricing-policies` requires the request to carry
        `expected_station_version`, holding the client's last observed
        `version` of the station the policy is being created against. If the
        station's current `version` has advanced beyond what the client
        observed — because activation, suspension, resumption, or a prior
        policy creation moved it — the create is rejected with
        `ERR_STALE_STATION_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_station_version_on_policy_create_returns_412
        """
        env = create_active_station(station_name="OCC1", station_code="ST-OCC1")
        station_id = env["station"]["id"]
        observed_version = env["station"]["version"]

        p1 = create_pricing_policy(
            station_id, price_per_gge_cents=289, expected_station_version=observed_version
        )
        assert p1["status"] == "ACTIVE"

        # The first create bumped Station.version, so the same observed version is stale.
        from test_helpers.factories import create_pricing_policy_payload

        resp = api.create_pricing_policy(
            create_pricing_policy_payload(
                station_id, observed_version, price_per_gge_cents=319
            ),
            network_operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_STATION_VERSION, 412)
