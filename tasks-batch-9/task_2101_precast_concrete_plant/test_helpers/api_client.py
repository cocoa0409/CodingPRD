"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock --------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- projects -------------------------------------------------------
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    # ---- mix designs ----------------------------------------------------
    def create_mix_design(self, payload, headers):
        return self._request("POST", "/mix-designs", payload, headers)

    def get_mix_design(self, mix_design_id, headers):
        return self._request("GET", f"/mix-designs/{mix_design_id}", headers=headers)

    def qualify_mix_design(self, mix_design_id, headers, payload=None):
        return self._request(
            "POST", f"/mix-designs/{mix_design_id}/qualify", payload or {}, headers
        )

    def suspend_mix_design(self, mix_design_id, payload, headers):
        return self._request(
            "POST", f"/mix-designs/{mix_design_id}/suspend", payload, headers
        )

    def reinstate_mix_design(self, mix_design_id, headers, payload=None):
        return self._request(
            "POST", f"/mix-designs/{mix_design_id}/reinstate", payload or {}, headers
        )

    def retire_mix_design(self, mix_design_id, headers, payload=None):
        return self._request(
            "POST", f"/mix-designs/{mix_design_id}/retire", payload or {}, headers
        )

    # ---- steam zones ----------------------------------------------------
    def create_steam_zone(self, payload, headers):
        return self._request("POST", "/steam-zones", payload, headers)

    def get_steam_zone(self, steam_zone_id, headers):
        return self._request("GET", f"/steam-zones/{steam_zone_id}", headers=headers)

    def list_steam_zone_casting_beds(self, steam_zone_id, headers, params=None):
        return self._request(
            "GET", f"/steam-zones/{steam_zone_id}/casting-beds", headers=headers, params=params
        )

    def list_steam_zone_curing_cycles(self, steam_zone_id, headers, params=None):
        return self._request(
            "GET", f"/steam-zones/{steam_zone_id}/curing-cycles", headers=headers, params=params
        )

    # ---- casting beds ---------------------------------------------------
    def create_casting_bed(self, payload, headers):
        return self._request("POST", "/casting-beds", payload, headers)

    def get_casting_bed(self, casting_bed_id, headers):
        return self._request("GET", f"/casting-beds/{casting_bed_id}", headers=headers)

    # ---- bed runs -------------------------------------------------------
    def create_bed_run(self, payload, headers):
        return self._request("POST", "/bed-runs", payload, headers)

    def get_bed_run(self, bed_run_id, headers):
        return self._request("GET", f"/bed-runs/{bed_run_id}", headers=headers)

    def list_bed_runs(self, headers, params=None):
        return self._request("GET", "/bed-runs", headers=headers, params=params)

    def tension_bed_run(self, bed_run_id, payload, headers):
        return self._request("POST", f"/bed-runs/{bed_run_id}/tension", payload, headers)

    def abort_tensioning(self, bed_run_id, payload, headers):
        return self._request(
            "POST", f"/bed-runs/{bed_run_id}/abort-tensioning", payload, headers
        )

    def cast_bed_run(self, bed_run_id, headers, payload=None):
        return self._request("POST", f"/bed-runs/{bed_run_id}/cast", payload or {}, headers)

    def request_release(self, bed_run_id, headers, payload=None):
        return self._request(
            "POST", f"/bed-runs/{bed_run_id}/request-release", payload or {}, headers
        )

    def strip_bed_run(self, bed_run_id, headers, payload=None):
        return self._request("POST", f"/bed-runs/{bed_run_id}/strip", payload or {}, headers)

    def create_cylinder_set(self, bed_run_id, payload, headers):
        return self._request(
            "POST", f"/bed-runs/{bed_run_id}/cylinder-sets", payload, headers
        )

    def list_bed_run_cylinder_sets(self, bed_run_id, headers, params=None):
        return self._request(
            "GET", f"/bed-runs/{bed_run_id}/cylinder-sets", headers=headers, params=params
        )

    def create_curing_cycle(self, bed_run_id, payload, headers):
        return self._request(
            "POST", f"/bed-runs/{bed_run_id}/curing-cycles", payload, headers
        )

    def list_bed_run_curing_cycles(self, bed_run_id, headers, params=None):
        return self._request(
            "GET", f"/bed-runs/{bed_run_id}/curing-cycles", headers=headers, params=params
        )

    # ---- curing cycles --------------------------------------------------
    def complete_curing_cycle(self, curing_cycle_id, headers, payload=None):
        return self._request(
            "POST", f"/curing-cycles/{curing_cycle_id}/complete", payload or {}, headers
        )

    # ---- cylinder sets and breaks --------------------------------------
    def get_cylinder_set(self, cylinder_set_id, headers):
        return self._request("GET", f"/cylinder-sets/{cylinder_set_id}", headers=headers)

    def record_cylinder_break(self, cylinder_set_id, payload, headers):
        return self._request(
            "POST", f"/cylinder-sets/{cylinder_set_id}/breaks", payload, headers
        )

    def list_cylinder_breaks(self, cylinder_set_id, headers, params=None):
        return self._request(
            "GET", f"/cylinder-sets/{cylinder_set_id}/breaks", headers=headers, params=params
        )

    # ---- pieces ---------------------------------------------------------
    def create_piece(self, payload, headers):
        return self._request("POST", "/pieces", payload, headers)

    def get_piece(self, piece_id, headers):
        return self._request("GET", f"/pieces/{piece_id}", headers=headers)

    def list_pieces(self, headers, params=None):
        return self._request("GET", "/pieces", headers=headers, params=params)

    def assign_piece_to_run(self, piece_id, payload, headers):
        return self._request("POST", f"/pieces/{piece_id}/assign-run", payload, headers)

    def confirm_piece_erected(self, piece_id, headers, payload=None):
        return self._request(
            "POST", f"/pieces/{piece_id}/confirm-erected", payload or {}, headers
        )

    def list_piece_yard_placements(self, piece_id, headers, params=None):
        return self._request(
            "GET", f"/pieces/{piece_id}/yard-placements", headers=headers, params=params
        )

    def list_piece_shipment_lines(self, piece_id, headers, params=None):
        return self._request(
            "GET", f"/pieces/{piece_id}/shipment-lines", headers=headers, params=params
        )

    def list_piece_repair_dispositions(self, piece_id, headers, params=None):
        return self._request(
            "GET", f"/pieces/{piece_id}/repair-dispositions", headers=headers, params=params
        )

    # ---- yard -----------------------------------------------------------
    def create_yard_slot(self, payload, headers):
        return self._request("POST", "/yard-slots", payload, headers)

    def get_yard_slot(self, yard_slot_id, headers):
        return self._request("GET", f"/yard-slots/{yard_slot_id}", headers=headers)

    def list_yard_slot_placements(self, yard_slot_id, headers, params=None):
        return self._request(
            "GET", f"/yard-slots/{yard_slot_id}/yard-placements", headers=headers, params=params
        )

    def create_yard_placement(self, payload, headers):
        return self._request("POST", "/yard-placements", payload, headers)

    def pull_yard_placement(self, yard_placement_id, payload, headers):
        return self._request(
            "POST", f"/yard-placements/{yard_placement_id}/pull", payload, headers
        )

    # ---- haul permits ---------------------------------------------------
    def create_haul_permit(self, payload, headers):
        return self._request("POST", "/haul-permits", payload, headers)

    def get_haul_permit(self, haul_permit_id, headers):
        return self._request("GET", f"/haul-permits/{haul_permit_id}", headers=headers)

    def list_haul_permits(self, headers, params=None):
        return self._request("GET", "/haul-permits", headers=headers, params=params)

    def issue_haul_permit(self, haul_permit_id, headers, payload=None):
        return self._request(
            "POST", f"/haul-permits/{haul_permit_id}/issue", payload or {}, headers
        )

    # ---- shipments ------------------------------------------------------
    def create_shipment(self, payload, headers):
        return self._request("POST", "/shipments", payload, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/shipments", headers=headers, params=params)

    def create_shipment_line(self, shipment_id, payload, headers):
        return self._request("POST", f"/shipments/{shipment_id}/lines", payload, headers)

    def list_shipment_lines(self, shipment_id, headers, params=None):
        return self._request(
            "GET", f"/shipments/{shipment_id}/lines", headers=headers, params=params
        )

    def dispatch_shipment(self, shipment_id, headers, payload=None):
        return self._request(
            "POST", f"/shipments/{shipment_id}/dispatch", payload or {}, headers
        )

    def deliver_shipment(self, shipment_id, headers, payload=None):
        return self._request(
            "POST", f"/shipments/{shipment_id}/deliver", payload or {}, headers
        )

    # ---- repair dispositions -------------------------------------------
    def create_repair_disposition(self, payload, headers):
        return self._request("POST", "/repair-dispositions", payload, headers)

    def decide_disposition(self, repair_disposition_id, payload, headers):
        return self._request(
            "POST", f"/repair-dispositions/{repair_disposition_id}/disposition", payload, headers
        )

    def start_repair(self, repair_disposition_id, headers, payload=None):
        return self._request(
            "POST",
            f"/repair-dispositions/{repair_disposition_id}/start-repair",
            payload or {},
            headers,
        )

    def submit_reinspection(self, repair_disposition_id, headers, payload=None):
        return self._request(
            "POST",
            f"/repair-dispositions/{repair_disposition_id}/submit-reinspection",
            payload or {},
            headers,
        )

    def reinspect(self, repair_disposition_id, payload, headers):
        return self._request(
            "POST", f"/repair-dispositions/{repair_disposition_id}/reinspect", payload, headers
        )


api_client = ApiClient()
