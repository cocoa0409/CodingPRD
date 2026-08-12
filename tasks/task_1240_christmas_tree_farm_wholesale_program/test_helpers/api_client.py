"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Season ---
    def create_season(self, payload, headers):
        return self._request("POST", "/api/seasons", payload, headers)

    def get_season(self, season_id, headers):
        return self._request("GET", f"/api/seasons/{season_id}", headers=headers)

    def advance_posture(self, season_id, target_posture, headers):
        return self._request(
            "POST", f"/api/seasons/{season_id}/advance-posture",
            {"target_posture": target_posture}, headers,
        )

    def run_ops(self, season_id, headers):
        return self._request(
            "POST", f"/api/seasons/{season_id}/run-ops", {}, headers,
        )

    # --- Block ---
    def create_block(self, payload, headers):
        return self._request("POST", "/api/blocks", payload, headers)

    def get_block(self, block_id, headers):
        return self._request("GET", f"/api/blocks/{block_id}", headers=headers)

    def list_blocks(self, headers, params=None):
        return self._request("GET", "/api/blocks", headers=headers, params=params)

    def advance_rotation(self, block_id, headers):
        return self._request(
            "POST", f"/api/blocks/{block_id}/advance-rotation", {}, headers,
        )

    # --- CropLot / StandBucket ---
    def create_crop_lot(self, payload, headers):
        return self._request("POST", "/api/crop-lots", payload, headers)

    def get_crop_lot(self, crop_lot_id, headers):
        return self._request("GET", f"/api/crop-lots/{crop_lot_id}", headers=headers)

    def list_crop_lots(self, headers, params=None):
        return self._request("GET", "/api/crop-lots", headers=headers, params=params)

    def list_stand_buckets(self, crop_lot_id, headers, params=None):
        return self._request(
            "GET", f"/api/crop-lots/{crop_lot_id}/stand-buckets",
            headers=headers, params=params,
        )

    def list_lot_surveys(self, crop_lot_id, headers, params=None):
        return self._request(
            "GET", f"/api/crop-lots/{crop_lot_id}/surveys",
            headers=headers, params=params,
        )

    # --- InventorySurvey ---
    def create_survey(self, payload, headers):
        return self._request("POST", "/api/surveys", payload, headers)

    def post_survey(self, survey_id, expected_crop_lot_version, headers):
        return self._request(
            "POST", f"/api/surveys/{survey_id}/post",
            {"expected_crop_lot_version": expected_crop_lot_version}, headers,
        )

    # --- BuyerAccount ---
    def create_buyer_account(self, payload, headers):
        return self._request("POST", "/api/buyer-accounts", payload, headers)

    def get_buyer_account(self, buyer_id, headers):
        return self._request(
            "GET", f"/api/buyer-accounts/{buyer_id}", headers=headers,
        )

    def set_buyer_standing(self, buyer_id, to_standing, headers):
        return self._request(
            "POST", f"/api/buyer-accounts/{buyer_id}/set-standing",
            {"to_standing": to_standing}, headers,
        )

    # --- WholesaleOrder ---
    def create_order(self, payload, headers):
        return self._request("POST", "/api/wholesale-orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request(
            "GET", f"/api/wholesale-orders/{order_id}", headers=headers,
        )

    def list_orders(self, headers, params=None):
        return self._request(
            "GET", "/api/wholesale-orders", headers=headers, params=params,
        )

    def submit_order(self, order_id, headers):
        return self._request(
            "POST", f"/api/wholesale-orders/{order_id}/submit", {}, headers,
        )

    def cancel_order(self, order_id, headers):
        return self._request(
            "POST", f"/api/wholesale-orders/{order_id}/cancel", {}, headers,
        )

    def allocate_order(self, order_id, quantity, expected_order_version, headers):
        return self._request(
            "POST", f"/api/wholesale-orders/{order_id}/allocate",
            {"quantity": quantity, "expected_order_version": expected_order_version},
            headers,
        )

    # --- Allocation ---
    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/api/allocations/{allocation_id}", headers=headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/api/allocations", headers=headers, params=params)

    def release_allocation(self, allocation_id, headers):
        return self._request(
            "POST", f"/api/allocations/{allocation_id}/release", {}, headers,
        )

    # --- Crew ---
    def create_crew(self, payload, headers):
        return self._request("POST", "/api/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/api/crews/{crew_id}", headers=headers)

    def list_crews(self, headers, params=None):
        return self._request("GET", "/api/crews", headers=headers, params=params)

    def lay_off_crew(self, crew_id, headers):
        return self._request(
            "POST", f"/api/crews/{crew_id}/lay-off", {}, headers,
        )

    # --- HarvestTicket ---
    def create_ticket(self, payload, headers):
        return self._request("POST", "/api/harvest-tickets", payload, headers)

    def get_ticket(self, ticket_id, headers):
        return self._request(
            "GET", f"/api/harvest-tickets/{ticket_id}", headers=headers,
        )

    def list_tickets(self, headers, params=None):
        return self._request(
            "GET", "/api/harvest-tickets", headers=headers, params=params,
        )

    def void_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/api/harvest-tickets/{ticket_id}/void", {}, headers,
        )

    # --- Load ---
    def create_load(self, payload, headers):
        return self._request("POST", "/api/loads", payload, headers)

    def get_load(self, load_id, headers):
        return self._request("GET", f"/api/loads/{load_id}", headers=headers)

    def list_loads(self, headers, params=None):
        return self._request("GET", "/api/loads", headers=headers, params=params)

    def add_load_line(self, load_id, allocation_id, quantity, headers):
        return self._request(
            "POST", f"/api/loads/{load_id}/lines",
            {"allocation_id": allocation_id, "quantity": quantity}, headers,
        )

    def ship_load(self, load_id, headers):
        return self._request("POST", f"/api/loads/{load_id}/ship", {}, headers)

    def cancel_load(self, load_id, headers):
        return self._request("POST", f"/api/loads/{load_id}/cancel", {}, headers)

    # --- Consignment ---
    def create_consignment(self, payload, headers):
        return self._request("POST", "/api/consignments", payload, headers)

    def get_consignment(self, consignment_id, headers):
        return self._request(
            "GET", f"/api/consignments/{consignment_id}", headers=headers,
        )

    def list_consignments(self, headers, params=None):
        return self._request(
            "GET", "/api/consignments", headers=headers, params=params,
        )

    def deliver_consignment(self, consignment_id, delivered_count, headers):
        return self._request(
            "POST", f"/api/consignments/{consignment_id}/deliver",
            {"delivered_count": delivered_count}, headers,
        )

    def report_return(self, consignment_id, returned_count, headers):
        return self._request(
            "POST", f"/api/consignments/{consignment_id}/report-return",
            {"returned_count": returned_count}, headers,
        )

    def settle_consignment(self, consignment_id, headers):
        return self._request(
            "POST", f"/api/consignments/{consignment_id}/settle", {}, headers,
        )

    def dispute_consignment(self, consignment_id, headers):
        return self._request(
            "POST", f"/api/consignments/{consignment_id}/dispute", {}, headers,
        )

    # --- UcutTag ---
    def create_ucut_tag(self, payload, headers):
        return self._request("POST", "/api/ucut-tags", payload, headers)

    def get_ucut_tag(self, tag_id, headers):
        return self._request("GET", f"/api/ucut-tags/{tag_id}", headers=headers)

    def list_ucut_tags(self, headers, params=None):
        return self._request("GET", "/api/ucut-tags", headers=headers, params=params)

    def redeem_ucut_tag(self, tag_id, headers):
        return self._request(
            "POST", f"/api/ucut-tags/{tag_id}/redeem", {}, headers,
        )

    def release_ucut_tag(self, tag_id, headers):
        return self._request(
            "POST", f"/api/ucut-tags/{tag_id}/release", {}, headers,
        )

    # --- CullRecord ---
    def create_cull_record(self, payload, headers):
        return self._request("POST", "/api/cull-records", payload, headers)

    def get_cull_record(self, cull_id, headers):
        return self._request("GET", f"/api/cull-records/{cull_id}", headers=headers)

    def list_cull_records(self, headers, params=None):
        return self._request(
            "GET", "/api/cull-records", headers=headers, params=params,
        )

    # --- ReplantPlan ---
    def create_replant_plan(self, payload, headers):
        return self._request("POST", "/api/replant-plans", payload, headers)

    def get_replant_plan(self, plan_id, headers):
        return self._request(
            "GET", f"/api/replant-plans/{plan_id}", headers=headers,
        )

    def list_replant_plans(self, headers, params=None):
        return self._request(
            "GET", "/api/replant-plans", headers=headers, params=params,
        )

    def approve_replant_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/api/replant-plans/{plan_id}/approve", {}, headers,
        )

    def reject_replant_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/api/replant-plans/{plan_id}/reject", {}, headers,
        )

    def execute_replant_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/api/replant-plans/{plan_id}/execute", {}, headers,
        )


api_client = ApiClient()
