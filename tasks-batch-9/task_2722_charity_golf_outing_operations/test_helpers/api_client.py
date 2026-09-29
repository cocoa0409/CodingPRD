"""Endpoint-aware HTTP client for the Charity Golf Outing Operations API.

One method per endpoint of the PRD endpoint table.  Every collection is mounted
under ``/outing-ops``; the logical-clock control endpoint sits at the server
root.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/outing-ops"


def _params(**kwargs: Any) -> Dict[str, Any]:
    """Drop unset query parameters so defaults stay server-side."""
    return {k: v for k, v in kwargs.items() if v is not None}


class ApiClient(GenericApiClient):
    """Typed facade over the generic request client."""

    # ------------------------------------------------------ logical clock ---

    def set_clock(self, current_utc: str, headers: Optional[Dict[str, str]] = None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------ outings ---

    def create_outing(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"{PREFIX}/outings", payload, headers)

    def get_outing(self, outing_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{PREFIX}/outings/{outing_id}", None, headers)

    def list_outings(
        self,
        headers: Optional[Dict[str, str]] = None,
        play_status: Optional[str] = None,
        finance_status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{PREFIX}/outings",
            None,
            headers,
            params=_params(
                play_status=play_status,
                finance_status=finance_status,
                limit=limit,
                offset=offset,
            ),
        )

    def play_transition(
        self, outing_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/outings/{outing_id}/play-transition", payload, headers
        )

    def finance_transition(
        self, outing_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/outings/{outing_id}/finance-transition", payload, headers
        )

    def get_proceeds_report(self, outing_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{PREFIX}/outings/{outing_id}/proceeds-report", None, headers)

    def get_pairing_sheet(
        self,
        outing_id: str,
        headers: Optional[Dict[str, str]] = None,
        wave: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{PREFIX}/outings/{outing_id}/pairing-sheet",
            None,
            headers,
            params=_params(wave=wave, limit=limit, offset=offset),
        )

    # ---------------------------------------------------------- contracts ---

    def create_contract(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"{PREFIX}/contracts", payload, headers)

    def get_contract(self, contract_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{PREFIX}/contracts/{contract_id}", None, headers)

    def list_contracts(
        self,
        headers: Optional[Dict[str, str]] = None,
        outing_id: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{PREFIX}/contracts",
            None,
            headers,
            params=_params(outing_id=outing_id, limit=limit, offset=offset),
        )

    def contract_lifecycle(
        self, contract_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/contracts/{contract_id}/lifecycle", payload, headers
        )

    # ------------------------------------------------------- package tiers ---

    def create_package_tier(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request("POST", f"{PREFIX}/package-tiers", payload, headers)

    def get_package_tier(self, tier_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{PREFIX}/package-tiers/{tier_id}", None, headers)

    def list_package_tiers(
        self,
        headers: Optional[Dict[str, str]] = None,
        outing_id: Optional[str] = None,
        kind: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{PREFIX}/package-tiers",
            None,
            headers,
            params=_params(outing_id=outing_id, kind=kind, limit=limit, offset=offset),
        )

    # ------------------------------------------------------- registrations ---

    def create_registration(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request("POST", f"{PREFIX}/registrations", payload, headers)

    def get_registration(self, registration_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{PREFIX}/registrations/{registration_id}", None, headers)

    def list_registrations(
        self,
        headers: Optional[Dict[str, str]] = None,
        outing_id: Optional[str] = None,
        package_tier_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{PREFIX}/registrations",
            None,
            headers,
            params=_params(
                outing_id=outing_id,
                package_tier_id=package_tier_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

    def record_registration_payment(
        self,
        registration_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"{PREFIX}/registrations/{registration_id}/payment", payload, headers
        )

    def amend_tier(
        self,
        registration_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"{PREFIX}/registrations/{registration_id}/amend-tier", payload, headers
        )

    def registration_lifecycle(
        self,
        registration_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"{PREFIX}/registrations/{registration_id}/lifecycle", payload, headers
        )

    # ------------------------------------------------------------- players ---

    def create_player(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"{PREFIX}/players", payload, headers)

    def get_player(self, player_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{PREFIX}/players/{player_id}", None, headers)

    def list_players(
        self,
        headers: Optional[Dict[str, str]] = None,
        registration_id: Optional[str] = None,
        team_id: Optional[str] = None,
        amateur_status: Optional[str] = None,
        checked_in: Optional[Any] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{PREFIX}/players",
            None,
            headers,
            params=_params(
                registration_id=registration_id,
                team_id=team_id,
                amateur_status=amateur_status,
                checked_in=checked_in,
                limit=limit,
                offset=offset,
            ),
        )

    def update_handicap_index(
        self, player_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/players/{player_id}/handicap-index", payload, headers
        )

    # --------------------------------------------------------------- teams ---

    def create_team(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"{PREFIX}/teams", payload, headers)

    def get_team(self, team_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{PREFIX}/teams/{team_id}", None, headers)

    def list_teams(
        self,
        headers: Optional[Dict[str, str]] = None,
        outing_id: Optional[str] = None,
        wave: Optional[str] = None,
        starting_hole: Optional[int] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{PREFIX}/teams",
            None,
            headers,
            params=_params(
                outing_id=outing_id,
                wave=wave,
                starting_hole=starting_hole,
                limit=limit,
                offset=offset,
            ),
        )

    def tee_assignment(
        self, team_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request("POST", f"{PREFIX}/teams/{team_id}/tee-assignment", payload, headers)

    def post_score(
        self, team_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request("POST", f"{PREFIX}/teams/{team_id}/score", payload, headers)

    # --------------------------------------------------- sponsorship assets ---

    def create_sponsorship_asset(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request("POST", f"{PREFIX}/sponsorship-assets", payload, headers)

    def get_sponsorship_asset(self, asset_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{PREFIX}/sponsorship-assets/{asset_id}", None, headers)

    def list_sponsorship_assets(
        self,
        headers: Optional[Dict[str, str]] = None,
        outing_id: Optional[str] = None,
        asset_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{PREFIX}/sponsorship-assets",
            None,
            headers,
            params=_params(
                outing_id=outing_id,
                asset_type=asset_type,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

    def asset_inventory(
        self, asset_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/sponsorship-assets/{asset_id}/inventory", payload, headers
        )

    # -------------------------------------------------- sponsor allocations ---

    def create_sponsor_allocation(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request("POST", f"{PREFIX}/sponsor-allocations", payload, headers)

    def get_sponsor_allocation(
        self, allocation_id: str, headers: Optional[Dict[str, str]] = None
    ):
        return self._request("GET", f"{PREFIX}/sponsor-allocations/{allocation_id}", None, headers)

    def list_sponsor_allocations(
        self,
        headers: Optional[Dict[str, str]] = None,
        registration_id: Optional[str] = None,
        sponsorship_asset_id: Optional[str] = None,
        status: Optional[str] = None,
        source: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{PREFIX}/sponsor-allocations",
            None,
            headers,
            params=_params(
                registration_id=registration_id,
                sponsorship_asset_id=sponsorship_asset_id,
                status=status,
                source=source,
                limit=limit,
                offset=offset,
            ),
        )

    def allocation_fulfillment(
        self, allocation_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/sponsor-allocations/{allocation_id}/fulfillment", payload, headers
        )

    # ------------------------------------------------------------ contests ---

    def create_contest(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"{PREFIX}/contests", payload, headers)

    def get_contest(self, contest_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{PREFIX}/contests/{contest_id}", None, headers)

    def list_contests(
        self,
        headers: Optional[Dict[str, str]] = None,
        outing_id: Optional[str] = None,
        winner_player_id: Optional[str] = None,
        contest_type: Optional[str] = None,
        status: Optional[str] = None,
        insurance_status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{PREFIX}/contests",
            None,
            headers,
            params=_params(
                outing_id=outing_id,
                winner_player_id=winner_player_id,
                contest_type=contest_type,
                status=status,
                insurance_status=insurance_status,
                limit=limit,
                offset=offset,
            ),
        )

    def bind_insurance(
        self, contest_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request("POST", f"{PREFIX}/contests/{contest_id}/insurance", payload, headers)

    def contest_status(
        self, contest_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request("POST", f"{PREFIX}/contests/{contest_id}/status", payload, headers)

    def award_contest(
        self, contest_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request("POST", f"{PREFIX}/contests/{contest_id}/award", payload, headers)

    # --------------------------------------------------- fundraising items ---

    def create_fundraising_item(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request("POST", f"{PREFIX}/fundraising-items", payload, headers)

    def get_fundraising_item(self, item_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{PREFIX}/fundraising-items/{item_id}", None, headers)

    def list_fundraising_items(
        self,
        headers: Optional[Dict[str, str]] = None,
        outing_id: Optional[str] = None,
        buyer_registration_id: Optional[str] = None,
        item_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{PREFIX}/fundraising-items",
            None,
            headers,
            params=_params(
                outing_id=outing_id,
                buyer_registration_id=buyer_registration_id,
                item_type=item_type,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

    def record_item_sale(
        self, item_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request("POST", f"{PREFIX}/fundraising-items/{item_id}/sale", payload, headers)

    def record_item_payment(
        self, item_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/fundraising-items/{item_id}/payment", payload, headers
        )

    def item_lifecycle(
        self, item_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/fundraising-items/{item_id}/lifecycle", payload, headers
        )

    # ------------------------------------------------------------ receipts ---

    def create_receipt(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"{PREFIX}/receipts", payload, headers)

    def get_receipt(self, receipt_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"{PREFIX}/receipts/{receipt_id}", None, headers)

    def list_receipts(
        self,
        headers: Optional[Dict[str, str]] = None,
        outing_id: Optional[str] = None,
        registration_id: Optional[str] = None,
        fundraising_item_id: Optional[str] = None,
        reverses_receipt_id: Optional[str] = None,
        receipt_kind: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{PREFIX}/receipts",
            None,
            headers,
            params=_params(
                outing_id=outing_id,
                registration_id=registration_id,
                fundraising_item_id=fundraising_item_id,
                reverses_receipt_id=reverses_receipt_id,
                receipt_kind=receipt_kind,
                limit=limit,
                offset=offset,
            ),
        )

    def reverse_receipt(
        self, receipt_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ):
        return self._request("POST", f"{PREFIX}/receipts/{receipt_id}/reversal", payload, headers)
