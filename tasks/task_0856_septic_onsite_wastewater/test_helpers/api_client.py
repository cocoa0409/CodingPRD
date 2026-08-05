"""API client: one method per endpoint of the on-site wastewater register."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Parcels ───────────────────────────────────────────────────────────────
    def create_parcel(self, payload, headers):
        return self._request("POST", "/parcels", payload, headers)

    def list_parcels(self, headers, params=None):
        return self._request("GET", "/parcels", headers=headers, params=params)

    def get_parcel(self, parcel_id, headers):
        return self._request("GET", f"/parcels/{parcel_id}", headers=headers)

    def list_parcel_wells(self, parcel_id, headers, params=None):
        return self._request(
            "GET", f"/parcels/{parcel_id}/wells", headers=headers, params=params
        )

    def list_parcel_site_evaluations(self, parcel_id, headers, params=None):
        return self._request(
            "GET",
            f"/parcels/{parcel_id}/site-evaluations",
            headers=headers,
            params=params,
        )

    def get_compliance_dossier(self, parcel_id, headers):
        return self._request(
            "GET", f"/parcels/{parcel_id}/compliance-dossier", headers=headers
        )

    def record_fee_payment(self, parcel_id, payload, headers):
        return self._request(
            "POST", f"/parcels/{parcel_id}/fee-payments", payload, headers
        )

    # ── Contractors ───────────────────────────────────────────────────────────
    def create_contractor(self, payload, headers):
        return self._request("POST", "/contractors", payload, headers)

    def get_contractor(self, contractor_id, headers):
        return self._request("GET", f"/contractors/{contractor_id}", headers=headers)

    def set_license_status(self, contractor_id, payload, headers):
        return self._request(
            "POST", f"/contractors/{contractor_id}/license-status", payload, headers
        )

    # ── Wells and water samples ───────────────────────────────────────────────
    def create_well(self, payload, headers):
        return self._request("POST", "/wells", payload, headers)

    def get_well(self, well_id, headers):
        return self._request("GET", f"/wells/{well_id}", headers=headers)

    def list_water_samples(self, well_id, headers, params=None):
        return self._request(
            "GET", f"/wells/{well_id}/water-samples", headers=headers, params=params
        )

    def create_water_sample(self, well_id, payload, headers):
        return self._request(
            "POST", f"/wells/{well_id}/water-samples", payload, headers
        )

    # ── Site evaluations ──────────────────────────────────────────────────────
    def create_site_evaluation(self, payload, headers):
        return self._request("POST", "/site-evaluations", payload, headers)

    def get_site_evaluation(self, site_evaluation_id, headers):
        return self._request(
            "GET", f"/site-evaluations/{site_evaluation_id}", headers=headers
        )

    def list_evaluation_system_designs(self, site_evaluation_id, headers, params=None):
        return self._request(
            "GET",
            f"/site-evaluations/{site_evaluation_id}/system-designs",
            headers=headers,
            params=params,
        )

    def add_perc_hole(self, site_evaluation_id, payload, headers):
        return self._request(
            "POST", f"/site-evaluations/{site_evaluation_id}/perc-holes", payload, headers
        )

    def submit_site_evaluation(self, site_evaluation_id, headers, payload=None):
        return self._request(
            "POST",
            f"/site-evaluations/{site_evaluation_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def review_site_evaluation(self, site_evaluation_id, payload, headers):
        return self._request(
            "POST", f"/site-evaluations/{site_evaluation_id}/review", payload, headers
        )

    # ── System designs ────────────────────────────────────────────────────────
    def create_system_design(self, payload, headers):
        return self._request("POST", "/system-designs", payload, headers)

    def get_system_design(self, system_design_id, headers):
        return self._request(
            "GET", f"/system-designs/{system_design_id}", headers=headers
        )

    def submit_system_design(self, system_design_id, headers, payload=None):
        return self._request(
            "POST",
            f"/system-designs/{system_design_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def review_system_design(self, system_design_id, payload, headers):
        return self._request(
            "POST", f"/system-designs/{system_design_id}/review", payload, headers
        )

    def variance_decision(self, system_design_id, payload, headers):
        return self._request(
            "POST",
            f"/system-designs/{system_design_id}/variance-decision",
            payload,
            headers,
        )

    # ── Construction permits ──────────────────────────────────────────────────
    def create_construction_permit(self, payload, headers):
        return self._request("POST", "/construction-permits", payload, headers)

    def get_construction_permit(self, permit_id, headers):
        return self._request(
            "GET", f"/construction-permits/{permit_id}", headers=headers
        )

    def list_construction_permits(self, headers, params=None):
        return self._request(
            "GET", "/construction-permits", headers=headers, params=params
        )

    def void_construction_permit(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/construction-permits/{permit_id}/void", payload, headers
        )

    # ── Inspections ───────────────────────────────────────────────────────────
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def record_inspection_result(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/inspections/{inspection_id}/result", payload, headers
        )

    def reschedule_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/inspections/{inspection_id}/reschedule", payload, headers
        )

    # ── Operating permits ─────────────────────────────────────────────────────
    def create_operating_permit(self, payload, headers):
        return self._request("POST", "/operating-permits", payload, headers)

    def get_operating_permit(self, operating_permit_id, headers):
        return self._request(
            "GET", f"/operating-permits/{operating_permit_id}", headers=headers
        )

    def list_operating_permits(self, headers, params=None):
        return self._request(
            "GET", "/operating-permits", headers=headers, params=params
        )

    def set_operating_permit_status(self, operating_permit_id, payload, headers):
        return self._request(
            "POST", f"/operating-permits/{operating_permit_id}/status", payload, headers
        )

    # ── Pumping records ───────────────────────────────────────────────────────
    def create_pumping_record(self, payload, headers):
        return self._request("POST", "/pumping-records", payload, headers)

    def get_pumping_record(self, pumping_record_id, headers):
        return self._request(
            "GET", f"/pumping-records/{pumping_record_id}", headers=headers
        )

    def list_pumping_records(self, headers, params=None):
        return self._request("GET", "/pumping-records", headers=headers, params=params)

    # ── Repair orders ─────────────────────────────────────────────────────────
    def create_repair_order(self, payload, headers):
        return self._request("POST", "/repair-orders", payload, headers)

    def get_repair_order(self, repair_order_id, headers):
        return self._request("GET", f"/repair-orders/{repair_order_id}", headers=headers)

    def list_repair_orders(self, headers, params=None):
        return self._request("GET", "/repair-orders", headers=headers, params=params)

    def issue_repair_order(self, repair_order_id, headers, payload=None):
        return self._request(
            "POST",
            f"/repair-orders/{repair_order_id}/issue",
            payload if payload is not None else {},
            headers,
        )

    def extend_repair_order(self, repair_order_id, headers, payload=None):
        return self._request(
            "POST",
            f"/repair-orders/{repair_order_id}/extend",
            payload if payload is not None else {},
            headers,
        )

    def resolve_repair_order(self, repair_order_id, payload, headers):
        return self._request(
            "POST", f"/repair-orders/{repair_order_id}/resolve", payload, headers
        )

    # ── Transfer inspections ──────────────────────────────────────────────────
    def create_transfer_inspection(self, payload, headers):
        return self._request("POST", "/transfer-inspections", payload, headers)

    def get_transfer_inspection(self, transfer_inspection_id, headers):
        return self._request(
            "GET", f"/transfer-inspections/{transfer_inspection_id}", headers=headers
        )

    def list_transfer_inspections(self, headers, params=None):
        return self._request(
            "GET", "/transfer-inspections", headers=headers, params=params
        )

    def certify_transfer_inspection(self, transfer_inspection_id, payload, headers):
        return self._request(
            "POST",
            f"/transfer-inspections/{transfer_inspection_id}/certify",
            payload,
            headers,
        )

    # ── Reporting and the logical clock ───────────────────────────────────────
    def get_compliance_summary(self, headers, params=None):
        return self._request(
            "GET", "/reports/compliance-summary", headers=headers, params=params
        )

    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
