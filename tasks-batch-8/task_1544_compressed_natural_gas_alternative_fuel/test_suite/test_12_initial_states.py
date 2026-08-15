"""Initial states on create for every stateful entity (PRD §3)."""
from test_helpers import (
    create_active_station,
    create_backup,
    create_claim,
    create_contract,
    create_fleet_account,
    create_fleet_card,
    create_inspection,
    create_window,
)


class TestInitialStatesOnCreate:
    def test_initial_states_on_create(self, api):
        """PRD §3.3: "A new card starts ACTIVE with `current_day_gge` at zero
        and `current_day_date` set to the current UTC date."
        PRD §3.6: "The window is born SCHEDULED."
        PRD §3.8: "The contract starts DRAFT."
        PRD §3.6: "The arrangement starts RESERVED with `used_gge` at zero."
        PRD §3.7: "the inspection starts SCHEDULED."
        PRD §3.9: "The claim starts DRAFT and its provisional figures are
        computed immediately."

        Design: Corner/state_machines/initial_states_on_create
        """
        env = create_active_station(station_name="Init", station_code="ST-INIT")
        station_id = env["station"]["id"]
        account = create_fleet_account(account_name="Init Co", credit_limit_cents=100000)

        card = create_fleet_card(account["id"], daily_gge_limit=100.0)
        assert card["status"] == "ACTIVE"

        window = create_window(
            station_id, compressor_id=env["compressors"][0]["id"]
        )
        assert window["status"] == "SCHEDULED"

        contract = create_contract(
            account["id"], station_id, committed_monthly_gge=50.0,
            start_month="2026-08", end_month="2026-12",
        )
        assert contract["status"] == "DRAFT"

        backup = create_backup(station_id, committed_gge=500)
        assert backup["status"] == "RESERVED"

        inspection = create_inspection(
            station_id, inspection_type="ANNUAL_COMPREHENSIVE"
        )
        assert inspection["status"] == "SCHEDULED"

        claim = create_claim(
            station_id,
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-09-01T00:00:00Z",
        )
        assert claim["status"] == "DRAFT"
