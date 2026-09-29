"""API client: one method per endpoint defined in the PRD.

Every method takes an explicit ``headers`` dict so a test can choose which
role and which ``X-User-ID`` acts, which the PRD's ownership and
segregation-of-duties rules both require.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """One method per row of the PRD's endpoint table."""

    # ── Performance spaces ────────────────────────────

    def create_performance_space(self, payload: dict, headers: dict):
        return self._request("POST", "/performance-spaces", payload, headers)

    def get_performance_space(self, space_id: str, headers: dict):
        return self._request("GET", f"/performance-spaces/{space_id}", headers=headers)

    # ── Artists ───────────────────────────────────────

    def create_artist(self, payload: dict, headers: dict):
        return self._request("POST", "/artists", payload, headers)

    def get_artist(self, artist_id: str, headers: dict):
        return self._request("GET", f"/artists/{artist_id}", headers=headers)

    # ── Rental clients ────────────────────────────────

    def create_rental_client(self, payload: dict, headers: dict):
        return self._request("POST", "/rental-clients", payload, headers)

    def get_rental_client(self, client_id: str, headers: dict):
        return self._request("GET", f"/rental-clients/{client_id}", headers=headers)

    # ── Union departments ─────────────────────────────

    def create_union_department(self, payload: dict, headers: dict):
        return self._request("POST", "/union-departments", payload, headers)

    def get_union_department(self, department_id: str, headers: dict):
        return self._request("GET", f"/union-departments/{department_id}", headers=headers)

    def list_department_labor_calls(self, department_id: str, headers: dict,
                                   params: Optional[dict] = None):
        return self._request("GET", f"/union-departments/{department_id}/labor-calls",
                            headers=headers, params=params)

    # ── Equipment inventory ───────────────────────────

    def create_equipment_item(self, payload: dict, headers: dict):
        return self._request("POST", "/equipment-items", payload, headers)

    def get_equipment_item(self, item_id: str, headers: dict):
        return self._request("GET", f"/equipment-items/{item_id}", headers=headers)

    def list_equipment_item_rental_lines(self, item_id: str, headers: dict,
                                         params: Optional[dict] = None):
        return self._request("GET", f"/equipment-items/{item_id}/rental-lines",
                            headers=headers, params=params)

    # ── Engagements ───────────────────────────────────

    def create_engagement(self, payload: dict, headers: dict):
        return self._request("POST", "/engagements", payload, headers)

    def get_engagement(self, engagement_id: str, headers: dict):
        return self._request("GET", f"/engagements/{engagement_id}", headers=headers)

    def list_engagements(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/engagements", headers=headers, params=params)

    def assess_risk(self, engagement_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/engagements/{engagement_id}/assess-risk",
                            payload, headers)

    def record_deposit(self, engagement_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/engagements/{engagement_id}/record-deposit",
                            payload, headers)

    def confirm_engagement(self, engagement_id: str, headers: dict):
        return self._request("POST", f"/engagements/{engagement_id}/confirm", {}, headers)

    def cancel_engagement(self, engagement_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/engagements/{engagement_id}/cancel",
                            payload, headers)

    # ── Fee negotiations ──────────────────────────────

    def open_fee_negotiation(self, engagement_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/engagements/{engagement_id}/fee-negotiations",
                            payload, headers)

    def list_fee_negotiations(self, engagement_id: str, headers: dict,
                              params: Optional[dict] = None):
        return self._request("GET", f"/engagements/{engagement_id}/fee-negotiations",
                            headers=headers, params=params)

    def counter_fee_negotiation(self, negotiation_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/fee-negotiations/{negotiation_id}/counter",
                            payload, headers)

    def revise_fee_offer(self, negotiation_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/fee-negotiations/{negotiation_id}/revise-offer",
                            payload, headers)

    def accept_fee_negotiation(self, negotiation_id: str, headers: dict):
        return self._request("POST", f"/fee-negotiations/{negotiation_id}/accept",
                            {}, headers)

    # ── Technical riders and equipment lines ──────────

    def submit_tech_rider(self, engagement_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/engagements/{engagement_id}/tech-riders",
                            payload, headers)

    def list_engagement_tech_riders(self, engagement_id: str, headers: dict,
                                    params: Optional[dict] = None):
        return self._request("GET", f"/engagements/{engagement_id}/tech-riders",
                            headers=headers, params=params)

    def get_tech_rider(self, rider_id: str, headers: dict):
        return self._request("GET", f"/tech-riders/{rider_id}", headers=headers)

    def review_tech_rider(self, rider_id: str, headers: dict):
        return self._request("POST", f"/tech-riders/{rider_id}/review", {}, headers)

    def create_equipment_line(self, rider_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/tech-riders/{rider_id}/equipment-lines",
                            payload, headers)

    def list_rider_equipment_lines(self, rider_id: str, headers: dict,
                                   params: Optional[dict] = None):
        return self._request("GET", f"/tech-riders/{rider_id}/equipment-lines",
                            headers=headers, params=params)

    def clear_tech_rider(self, rider_id: str, headers: dict):
        return self._request("POST", f"/tech-riders/{rider_id}/clear", {}, headers)

    # ── Labor calls ───────────────────────────────────

    def create_labor_call(self, engagement_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/engagements/{engagement_id}/labor-calls",
                            payload, headers)

    def list_engagement_labor_calls(self, engagement_id: str, headers: dict,
                                    params: Optional[dict] = None):
        return self._request("GET", f"/engagements/{engagement_id}/labor-calls",
                            headers=headers, params=params)

    def report_labor_hours(self, labor_call_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/labor-calls/{labor_call_id}/report-hours",
                            payload, headers)

    # ── Ticketing ─────────────────────────────────────

    def create_price_tier(self, engagement_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/engagements/{engagement_id}/price-tiers",
                            payload, headers)

    def list_engagement_price_tiers(self, engagement_id: str, headers: dict,
                                    params: Optional[dict] = None):
        return self._request("GET", f"/engagements/{engagement_id}/price-tiers",
                            headers=headers, params=params)

    def get_price_tier(self, tier_id: str, headers: dict):
        return self._request("GET", f"/price-tiers/{tier_id}", headers=headers)

    def put_engagement_on_sale(self, engagement_id: str, headers: dict):
        return self._request("POST", f"/engagements/{engagement_id}/on-sale", {}, headers)

    def create_ticket_sale(self, tier_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/price-tiers/{tier_id}/ticket-sales",
                            payload, headers)

    def list_tier_ticket_sales(self, tier_id: str, headers: dict,
                               params: Optional[dict] = None):
        return self._request("GET", f"/price-tiers/{tier_id}/ticket-sales",
                            headers=headers, params=params)

    # ── Subscription packages ─────────────────────────

    def create_subscription_package(self, payload: dict, headers: dict):
        return self._request("POST", "/subscription-packages", payload, headers)

    def sell_subscription_orders(self, package_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/subscription-packages/{package_id}/sell",
                            payload, headers)

    # ── Settlement ────────────────────────────────────

    def open_settlement(self, engagement_id: str, headers: dict):
        return self._request("POST", f"/engagements/{engagement_id}/settlements",
                            {}, headers)

    def list_engagement_settlements(self, engagement_id: str, headers: dict,
                                    params: Optional[dict] = None):
        return self._request("GET", f"/engagements/{engagement_id}/settlements",
                            headers=headers, params=params)

    def reconcile_settlement_expenses(self, settlement_id: str, payload: dict,
                                      headers: dict):
        return self._request("POST", f"/settlements/{settlement_id}/reconcile-expenses",
                            payload, headers)

    def finalize_settlement(self, settlement_id: str, headers: dict):
        return self._request("POST", f"/settlements/{settlement_id}/finalize",
                            {}, headers)

    def get_box_office_statement(self, engagement_id: str, headers: dict):
        return self._request("GET", f"/engagements/{engagement_id}/box-office-statement",
                            headers=headers)

    # ── Education programs ────────────────────────────

    def create_education_program(self, engagement_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/engagements/{engagement_id}/education-programs",
                            payload, headers)

    def list_engagement_education_programs(self, engagement_id: str, headers: dict,
                                           params: Optional[dict] = None):
        return self._request("GET", f"/engagements/{engagement_id}/education-programs",
                            headers=headers, params=params)

    # ── Capital reserve ledger ────────────────────────

    def create_reserve_ledger_entry(self, payload: dict, headers: dict):
        return self._request("POST", "/reserve-ledger-entries", payload, headers)

    def list_reserve_ledger_entries(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/reserve-ledger-entries", headers=headers,
                            params=params)

    def list_engagement_reserve_ledger_entries(self, engagement_id: str, headers: dict,
                                               params: Optional[dict] = None):
        return self._request("GET",
                            f"/engagements/{engagement_id}/reserve-ledger-entries",
                            headers=headers, params=params)

    # ── Logical season clock ──────────────────────────

    def set_logical_clock(self, to_iso8601: str, headers: dict):
        return self._request("POST", "/_clock/set_current_utc",
                            {"to_iso8601": to_iso8601}, headers)

    # ── Raw escape hatch ──────────────────────────────

    def raw_post(self, path: str, payload: Any, headers: Dict[str, str]):
        """POST with fully caller-controlled headers.

        Needed for the authentication cases where a header must be omitted
        entirely or carry a role name the system does not recognize.
        """
        return self._request("POST", path, payload, headers)

    def raw_get(self, path: str, headers: Dict[str, str],
                params: Optional[dict] = None):
        """GET with fully caller-controlled headers."""
        return self._request("GET", path, headers=headers, params=params)


api_client = ApiClient()
