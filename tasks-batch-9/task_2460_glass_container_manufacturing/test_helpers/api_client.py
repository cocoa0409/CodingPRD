"""Typed HTTP client with one method per declared endpoint."""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH


def _params(**kwargs):
    """Drop unset query parameters so defaults stay server-side."""
    cleaned = {key: value for key, value in kwargs.items() if value is not None}
    return cleaned or None


class ApiClient(GenericApiClient):
    """One method per endpoint; every method takes explicit headers."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: dict):
        return self._request("POST", CLOCK_PATH, {"current_utc": current_utc}, headers)

    # ------------------------------------------------------------------
    # Furnaces
    # ------------------------------------------------------------------
    def create_furnace(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/furnaces", payload, headers)

    def list_furnaces(self, headers: dict, limit: Optional[int] = None, offset: Optional[int] = None):
        return self._request(
            "GET", f"{API_PREFIX}/furnaces", None, headers, _params(limit=limit, offset=offset)
        )

    def get_furnace(self, furnace_id: str, headers: dict):
        return self._request("GET", f"{API_PREFIX}/furnaces/{furnace_id}", None, headers)

    def list_furnace_campaigns(
        self,
        furnace_id: str,
        headers: dict,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/furnaces/{furnace_id}/campaigns",
            None,
            headers,
            _params(status=status, limit=limit, offset=offset),
        )

    def list_furnace_batch_recipes(
        self,
        furnace_id: str,
        headers: dict,
        color: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/furnaces/{furnace_id}/batch-recipes",
            None,
            headers,
            _params(color=color, limit=limit, offset=offset),
        )

    def list_furnace_color_changes(
        self,
        furnace_id: str,
        headers: dict,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/furnaces/{furnace_id}/color-changes",
            None,
            headers,
            _params(status=status, limit=limit, offset=offset),
        )

    def list_furnace_forming_machines(
        self,
        furnace_id: str,
        headers: dict,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/furnaces/{furnace_id}/forming-machines",
            None,
            headers,
            _params(limit=limit, offset=offset),
        )

    # ------------------------------------------------------------------
    # Campaigns
    # ------------------------------------------------------------------
    def create_campaign(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/campaigns", payload, headers)

    def get_campaign(self, campaign_id: str, headers: dict):
        return self._request("GET", f"{API_PREFIX}/campaigns/{campaign_id}", None, headers)

    def activate_campaign(self, campaign_id: str, headers: dict):
        return self._request("POST", f"{API_PREFIX}/campaigns/{campaign_id}/activate", {}, headers)

    def wind_down_campaign(self, campaign_id: str, headers: dict):
        return self._request("POST", f"{API_PREFIX}/campaigns/{campaign_id}/wind-down", {}, headers)

    def schedule_campaign_rebuild(self, campaign_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/campaigns/{campaign_id}/schedule-rebuild", payload, headers
        )

    def close_campaign(self, campaign_id: str, headers: dict):
        return self._request("POST", f"{API_PREFIX}/campaigns/{campaign_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # Batch recipes
    # ------------------------------------------------------------------
    def create_batch_recipe(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/batch-recipes", payload, headers)

    def get_batch_recipe(self, batch_recipe_id: str, headers: dict):
        return self._request("GET", f"{API_PREFIX}/batch-recipes/{batch_recipe_id}", None, headers)

    def approve_batch_recipe(self, batch_recipe_id: str, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/batch-recipes/{batch_recipe_id}/approve", {}, headers
        )

    # ------------------------------------------------------------------
    # Colour changes
    # ------------------------------------------------------------------
    def create_color_change(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/color-changes", payload, headers)

    def get_color_change(self, color_change_id: str, headers: dict):
        return self._request("GET", f"{API_PREFIX}/color-changes/{color_change_id}", None, headers)

    def complete_color_change(self, color_change_id: str, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/color-changes/{color_change_id}/complete", {}, headers
        )

    def abort_color_change(self, color_change_id: str, headers: dict, reason: Optional[str] = None):
        payload = {} if reason is None else {"reason": reason}
        return self._request(
            "POST", f"{API_PREFIX}/color-changes/{color_change_id}/abort", payload, headers
        )

    # ------------------------------------------------------------------
    # Forming machines
    # ------------------------------------------------------------------
    def create_forming_machine(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/forming-machines", payload, headers)

    def get_forming_machine(self, forming_machine_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/forming-machines/{forming_machine_id}", None, headers
        )

    # ------------------------------------------------------------------
    # Customers
    # ------------------------------------------------------------------
    def create_customer(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/customers", payload, headers)

    def get_customer(self, customer_id: str, headers: dict):
        return self._request("GET", f"{API_PREFIX}/customers/{customer_id}", None, headers)

    def patch_customer_palletization_standard(self, customer_id: str, payload: dict, headers: dict):
        return self._request(
            "PATCH", f"{API_PREFIX}/customers/{customer_id}/palletization-standard", payload, headers
        )

    # ------------------------------------------------------------------
    # Bottle designs
    # ------------------------------------------------------------------
    def create_bottle_design(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/bottle-designs", payload, headers)

    def list_bottle_designs(
        self,
        headers: dict,
        customer_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/bottle-designs",
            None,
            headers,
            _params(customer_id=customer_id, status=status, limit=limit, offset=offset),
        )

    def get_bottle_design(self, bottle_design_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/bottle-designs/{bottle_design_id}", None, headers
        )

    def submit_bottle_design(self, bottle_design_id: str, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/bottle-designs/{bottle_design_id}/submit", {}, headers
        )

    def request_design_changes(
        self, bottle_design_id: str, headers: dict, note: Optional[str] = None
    ):
        payload = {} if note is None else {"note": note}
        return self._request(
            "POST",
            f"{API_PREFIX}/bottle-designs/{bottle_design_id}/request-changes",
            payload,
            headers,
        )

    def risk_signoff_bottle_design(self, bottle_design_id: str, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/bottle-designs/{bottle_design_id}/risk-signoff", {}, headers
        )

    def approve_bottle_design(self, bottle_design_id: str, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/bottle-designs/{bottle_design_id}/approve", {}, headers
        )

    # ------------------------------------------------------------------
    # Mold sets
    # ------------------------------------------------------------------
    def create_mold_set(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/mold-sets", payload, headers)

    def list_mold_sets(
        self,
        headers: dict,
        bottle_design_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/mold-sets",
            None,
            headers,
            _params(bottle_design_id=bottle_design_id, status=status, limit=limit, offset=offset),
        )

    def get_mold_set(self, mold_set_id: str, headers: dict):
        return self._request("GET", f"{API_PREFIX}/mold-sets/{mold_set_id}", None, headers)

    def unmount_mold_set(self, mold_set_id: str, headers: dict):
        return self._request("POST", f"{API_PREFIX}/mold-sets/{mold_set_id}/unmount", {}, headers)

    def send_mold_set_to_repair(self, mold_set_id: str, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/mold-sets/{mold_set_id}/send-to-repair", {}, headers
        )

    def return_mold_set_from_repair(self, mold_set_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/mold-sets/{mold_set_id}/return-from-repair", payload, headers
        )

    # ------------------------------------------------------------------
    # Lightweighting programs
    # ------------------------------------------------------------------
    def create_lightweighting_program(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/lightweighting-programs", payload, headers)

    def list_lightweighting_programs(
        self,
        headers: dict,
        baseline_design_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/lightweighting-programs",
            None,
            headers,
            _params(
                baseline_design_id=baseline_design_id, status=status, limit=limit, offset=offset
            ),
        )

    def get_lightweighting_program(self, program_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/lightweighting-programs/{program_id}", None, headers
        )

    def assess_program_risk(self, program_id: str, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/lightweighting-programs/{program_id}/assess-risk", {}, headers
        )

    def program_customer_decision(self, program_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{API_PREFIX}/lightweighting-programs/{program_id}/customer-decision",
            payload,
            headers,
        )

    def adopt_program(self, program_id: str, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/lightweighting-programs/{program_id}/adopt", {}, headers
        )

    def suspend_program(self, program_id: str, headers: dict, reason: Optional[str] = None):
        payload = {} if reason is None else {"reason": reason}
        return self._request(
            "POST", f"{API_PREFIX}/lightweighting-programs/{program_id}/suspend", payload, headers
        )

    # ------------------------------------------------------------------
    # Production jobs
    # ------------------------------------------------------------------
    def create_production_job(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/production-jobs", payload, headers)

    def list_production_jobs(
        self,
        headers: dict,
        campaign_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/production-jobs",
            None,
            headers,
            _params(campaign_id=campaign_id, status=status, limit=limit, offset=offset),
        )

    def get_production_job(self, production_job_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/production-jobs/{production_job_id}", None, headers
        )

    def get_job_refractory_projection(self, production_job_id: str, headers: dict):
        return self._request(
            "GET",
            f"{API_PREFIX}/production-jobs/{production_job_id}/refractory-projection",
            None,
            headers,
        )

    def start_production_job(self, production_job_id: str, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/production-jobs/{production_job_id}/start", {}, headers
        )

    def close_production_job(self, production_job_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/production-jobs/{production_job_id}/close", payload, headers
        )

    def cancel_production_job(self, production_job_id: str, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/production-jobs/{production_job_id}/cancel", {}, headers
        )

    # ------------------------------------------------------------------
    # Pack lots
    # ------------------------------------------------------------------
    def list_pack_lots(
        self,
        headers: dict,
        production_job_id: Optional[str] = None,
        customer_id: Optional[str] = None,
        quality_status: Optional[str] = None,
        logistics_status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/pack-lots",
            None,
            headers,
            _params(
                production_job_id=production_job_id,
                customer_id=customer_id,
                quality_status=quality_status,
                logistics_status=logistics_status,
                limit=limit,
                offset=offset,
            ),
        )

    def get_pack_lot(self, pack_lot_id: str, headers: dict):
        return self._request("GET", f"{API_PREFIX}/pack-lots/{pack_lot_id}", None, headers)

    def record_inspection_result(self, pack_lot_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/pack-lots/{pack_lot_id}/inspection-results", payload, headers
        )

    def list_inspection_results(
        self,
        pack_lot_id: str,
        headers: dict,
        defect_class: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/pack-lots/{pack_lot_id}/inspection-results",
            None,
            headers,
            _params(defect_class=defect_class, limit=limit, offset=offset),
        )

    def release_pack_lot(self, pack_lot_id: str, headers: dict):
        return self._request("POST", f"{API_PREFIX}/pack-lots/{pack_lot_id}/release", {}, headers)

    def rework_release_pack_lot(self, pack_lot_id: str, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/pack-lots/{pack_lot_id}/rework-release", {}, headers
        )

    def palletize_pack_lot(self, pack_lot_id: str, headers: dict):
        return self._request("POST", f"{API_PREFIX}/pack-lots/{pack_lot_id}/palletize", {}, headers)

    def ship_pack_lot(self, pack_lot_id: str, headers: dict):
        return self._request("POST", f"{API_PREFIX}/pack-lots/{pack_lot_id}/ship", {}, headers)

    # ------------------------------------------------------------------
    # Complaints
    # ------------------------------------------------------------------
    def create_complaint(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/complaints", payload, headers)

    def list_complaints(
        self,
        headers: dict,
        customer_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/complaints",
            None,
            headers,
            _params(customer_id=customer_id, status=status, limit=limit, offset=offset),
        )

    def get_complaint(self, complaint_id: str, headers: dict):
        return self._request("GET", f"{API_PREFIX}/complaints/{complaint_id}", None, headers)

    def investigate_complaint(self, complaint_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/complaints/{complaint_id}/investigate", payload, headers
        )

    def settle_complaint(self, complaint_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/complaints/{complaint_id}/settle", payload, headers
        )
