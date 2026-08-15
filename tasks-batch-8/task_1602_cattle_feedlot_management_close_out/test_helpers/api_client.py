"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Owners
    # ------------------------------------------------------------------
    def create_owner(self, payload, headers):
        return self._request("POST", "/feedlot/owners", payload, headers)

    def list_owners(self, headers, params=None):
        return self._request("GET", "/feedlot/owners", headers=headers, params=params)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/feedlot/owners/{owner_id}", headers=headers)

    def patch_owner(self, owner_id, payload, headers):
        return self._request("PATCH", f"/feedlot/owners/{owner_id}", payload, headers)

    def list_owner_lots(self, owner_id, headers, params=None):
        return self._request("GET", f"/feedlot/owners/{owner_id}/lots",
                             headers=headers, params=params)

    def list_owner_invoices(self, owner_id, headers, params=None):
        return self._request("GET", f"/feedlot/owners/{owner_id}/invoices",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Pens
    # ------------------------------------------------------------------
    def create_pen(self, payload, headers):
        return self._request("POST", "/feedlot/pens", payload, headers)

    def list_pens(self, headers, params=None):
        return self._request("GET", "/feedlot/pens", headers=headers, params=params)

    def get_pen(self, pen_id, headers):
        return self._request("GET", f"/feedlot/pens/{pen_id}", headers=headers)

    def patch_pen(self, pen_id, payload, headers):
        return self._request("PATCH", f"/feedlot/pens/{pen_id}", payload, headers)

    def list_pen_assignments(self, pen_id, headers, params=None):
        return self._request("GET", f"/feedlot/pens/{pen_id}/assignments",
                             headers=headers, params=params)

    def list_pen_feed_calls(self, pen_id, headers, params=None):
        return self._request("GET", f"/feedlot/pens/{pen_id}/feed-calls",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Lots
    # ------------------------------------------------------------------
    def create_lot(self, payload, headers):
        return self._request("POST", "/feedlot/lots", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/feedlot/lots/{lot_id}", headers=headers)

    def market_lot(self, lot_id, headers):
        return self._request("POST", f"/feedlot/lots/{lot_id}/market", {}, headers)

    def fail_sale_lot(self, lot_id, headers):
        return self._request("POST", f"/feedlot/lots/{lot_id}/fail-sale", {}, headers)

    def ship_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/feedlot/lots/{lot_id}/ship", payload, headers)

    def list_lot_assignments(self, lot_id, headers, params=None):
        return self._request("GET", f"/feedlot/lots/{lot_id}/assignments",
                             headers=headers, params=params)

    def list_lot_ration_assignments(self, lot_id, headers, params=None):
        return self._request("GET", f"/feedlot/lots/{lot_id}/ration-assignments",
                             headers=headers, params=params)

    def list_lot_health_events(self, lot_id, headers, params=None):
        return self._request("GET", f"/feedlot/lots/{lot_id}/health-events",
                             headers=headers, params=params)

    def list_lot_death_losses(self, lot_id, headers, params=None):
        return self._request("GET", f"/feedlot/lots/{lot_id}/death-losses",
                             headers=headers, params=params)

    def list_lot_hedges(self, lot_id, headers, params=None):
        return self._request("GET", f"/feedlot/lots/{lot_id}/hedges",
                             headers=headers, params=params)

    def list_lot_close_outs(self, lot_id, headers, params=None):
        return self._request("GET", f"/feedlot/lots/{lot_id}/close-outs",
                             headers=headers, params=params)

    def list_lot_invoices(self, lot_id, headers, params=None):
        return self._request("GET", f"/feedlot/lots/{lot_id}/invoices",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Rations
    # ------------------------------------------------------------------
    def create_ration(self, payload, headers):
        return self._request("POST", "/feedlot/rations", payload, headers)

    def list_rations(self, headers, params=None):
        return self._request("GET", "/feedlot/rations", headers=headers, params=params)

    def get_ration(self, ration_id, headers):
        return self._request("GET", f"/feedlot/rations/{ration_id}", headers=headers)

    def list_ration_assignments_for_ration(self, ration_id, headers, params=None):
        return self._request("GET", f"/feedlot/rations/{ration_id}/ration-assignments",
                             headers=headers, params=params)

    def list_ration_feed_calls(self, ration_id, headers, params=None):
        return self._request("GET", f"/feedlot/rations/{ration_id}/feed-calls",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Pen assignments
    # ------------------------------------------------------------------
    def create_assignment(self, payload, headers):
        return self._request("POST", "/feedlot/assignments", payload, headers)

    def end_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/feedlot/assignments/{assignment_id}/end",
                             payload, headers)

    # ------------------------------------------------------------------
    # Ration assignments
    # ------------------------------------------------------------------
    def create_ration_assignment(self, payload, headers):
        return self._request("POST", "/feedlot/ration-assignments", payload, headers)

    # ------------------------------------------------------------------
    # Feed calls
    # ------------------------------------------------------------------
    def create_feed_call(self, payload, headers):
        return self._request("POST", "/feedlot/feed-calls", payload, headers)

    # ------------------------------------------------------------------
    # Health events
    # ------------------------------------------------------------------
    def create_health_event(self, payload, headers):
        return self._request("POST", "/feedlot/health-events", payload, headers)

    # ------------------------------------------------------------------
    # Death losses
    # ------------------------------------------------------------------
    def create_death_loss(self, payload, headers):
        return self._request("POST", "/feedlot/death-losses", payload, headers)

    def get_death_loss(self, death_loss_id, headers):
        return self._request("GET", f"/feedlot/death-losses/{death_loss_id}",
                             headers=headers)

    def void_death_loss(self, death_loss_id, headers):
        return self._request("POST", f"/feedlot/death-losses/{death_loss_id}/void",
                             {}, headers)

    def list_death_loss_claims(self, death_loss_id, headers, params=None):
        return self._request("GET",
                             f"/feedlot/death-losses/{death_loss_id}/insurance-claims",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Insurance claims
    # ------------------------------------------------------------------
    def create_insurance_claim(self, payload, headers):
        return self._request("POST", "/feedlot/insurance-claims", payload, headers)

    def decide_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/feedlot/insurance-claims/{claim_id}/decide",
                             payload, headers)

    def appeal_claim(self, claim_id, headers):
        return self._request("POST", f"/feedlot/insurance-claims/{claim_id}/appeal",
                             {}, headers)

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"/feedlot/insurance-claims/{claim_id}/pay",
                             {}, headers)

    # ------------------------------------------------------------------
    # Hedge positions
    # ------------------------------------------------------------------
    def create_hedge(self, payload, headers):
        return self._request("POST", "/feedlot/hedges", payload, headers)

    def offset_hedge(self, hedge_id, payload, headers):
        return self._request("POST", f"/feedlot/hedges/{hedge_id}/offset",
                             payload, headers)

    # ------------------------------------------------------------------
    # Close-outs
    # ------------------------------------------------------------------
    def create_close_out(self, payload, headers):
        return self._request("POST", "/feedlot/close-outs", payload, headers)

    def confirm_close_out(self, close_out_id, payload, headers):
        return self._request("POST", f"/feedlot/close-outs/{close_out_id}/confirm",
                             payload, headers)

    # ------------------------------------------------------------------
    # Invoices
    # ------------------------------------------------------------------
    def pay_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/feedlot/invoices/{invoice_id}/payments",
                             payload, headers)

    def void_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/feedlot/invoices/{invoice_id}/void",
                             payload, headers)


api_client = ApiClient()
