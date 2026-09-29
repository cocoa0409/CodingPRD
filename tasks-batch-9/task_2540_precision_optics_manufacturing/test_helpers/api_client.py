"""Typed client over the precision optics manufacturing HTTP surface.

One method per row of the PRD endpoint table. Every method returns the raw
``requests.Response`` so that callers may validate the envelope, the HTTP
status and the error identifier themselves.
"""

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .types import Headers, Params, Payload


class OpticsApiClient(GenericApiClient):
    """Endpoint-per-method client for the optics manufacturing API."""

    # ------------------------------------------------------------------
    # Optical designs
    # ------------------------------------------------------------------
    def create_optical_design(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post("/optics/optical-designs", json=payload, headers=headers)

    def get_optical_design(
        self, design_id: str, headers: Headers
    ) -> requests.Response:
        return self.get(f"/optics/optical-designs/{design_id}", headers=headers)

    def list_optical_designs(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self.get("/optics/optical-designs", headers=headers, params=params)

    def create_tolerance_allocation(
        self, design_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"/optics/optical-designs/{design_id}/tolerance-allocations",
            json=payload,
            headers=headers,
        )

    def list_tolerance_allocations(
        self, design_id: str, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self.get(
            f"/optics/optical-designs/{design_id}/tolerance-allocations",
            headers=headers,
            params=params,
        )

    def get_tolerance_allocation(
        self, allocation_id: str, headers: Headers
    ) -> requests.Response:
        return self.get(
            f"/optics/tolerance-allocations/{allocation_id}", headers=headers
        )

    def retire_tolerance_allocation(
        self, allocation_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self.post(
            f"/optics/tolerance-allocations/{allocation_id}/retire",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def run_tolerance_analysis(
        self, design_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self.post(
            f"/optics/optical-designs/{design_id}/tolerance-analysis",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def release_optical_design(
        self, design_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self.post(
            f"/optics/optical-designs/{design_id}/release",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def create_design_revision(
        self, design_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"/optics/optical-designs/{design_id}/revisions",
            json=payload,
            headers=headers,
        )

    def list_design_export_classifications(
        self, design_id: str, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self.get(
            f"/optics/optical-designs/{design_id}/export-classifications",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Glass lots
    # ------------------------------------------------------------------
    def create_glass_lot(self, payload: Payload, headers: Headers) -> requests.Response:
        return self.post("/optics/glass-lots", json=payload, headers=headers)

    def certify_glass_lot(
        self, glass_lot_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"/optics/glass-lots/{glass_lot_id}/certification",
            json=payload,
            headers=headers,
        )

    def block_glass_lot(
        self, glass_lot_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"/optics/glass-lots/{glass_lot_id}/block", json=payload, headers=headers
        )

    def get_glass_lot(self, glass_lot_id: str, headers: Headers) -> requests.Response:
        return self.get(f"/optics/glass-lots/{glass_lot_id}", headers=headers)

    def list_glass_lots(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self.get("/optics/glass-lots", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Work orders
    # ------------------------------------------------------------------
    def create_work_order(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post("/optics/work-orders", json=payload, headers=headers)

    def get_work_order(self, work_order_id: str, headers: Headers) -> requests.Response:
        return self.get(f"/optics/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self.get("/optics/work-orders", headers=headers, params=params)

    def list_work_order_components(
        self, work_order_id: str, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self.get(
            f"/optics/work-orders/{work_order_id}/assembly-components",
            headers=headers,
            params=params,
        )

    def compliance_screen_work_order(
        self, work_order_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self.post(
            f"/optics/work-orders/{work_order_id}/compliance-screen",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def release_work_order_to_assembly(
        self, work_order_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self.post(
            f"/optics/work-orders/{work_order_id}/release-to-assembly",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def scrap_work_order(
        self, work_order_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"/optics/work-orders/{work_order_id}/scrap", json=payload, headers=headers
        )

    def cancel_work_order(
        self, work_order_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"/optics/work-orders/{work_order_id}/cancel", json=payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Metrology instruments
    # ------------------------------------------------------------------
    def create_metrology_instrument(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post("/optics/metrology-instruments", json=payload, headers=headers)

    def get_metrology_instrument(
        self, instrument_id: str, headers: Headers
    ) -> requests.Response:
        return self.get(
            f"/optics/metrology-instruments/{instrument_id}", headers=headers
        )

    def list_metrology_instruments(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self.get("/optics/metrology-instruments", headers=headers, params=params)

    def record_calibration(
        self, instrument_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self.post(
            f"/optics/metrology-instruments/{instrument_id}/calibrations",
            json=payload if payload is not None else {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Process runs
    # ------------------------------------------------------------------
    def create_process_run(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post("/optics/process-runs", json=payload, headers=headers)

    def get_process_run(
        self, process_run_id: str, headers: Headers
    ) -> requests.Response:
        return self.get(f"/optics/process-runs/{process_run_id}", headers=headers)

    def list_process_runs(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self.get("/optics/process-runs", headers=headers, params=params)

    def list_process_run_reports(
        self, process_run_id: str, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self.get(
            f"/optics/process-runs/{process_run_id}/metrology-reports",
            headers=headers,
            params=params,
        )

    def start_process_run(
        self, process_run_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self.post(
            f"/optics/process-runs/{process_run_id}/start",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def complete_process_run(
        self, process_run_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"/optics/process-runs/{process_run_id}/complete",
            json=payload,
            headers=headers,
        )

    def cancel_process_run(
        self, process_run_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"/optics/process-runs/{process_run_id}/cancel",
            json=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Metrology reports
    # ------------------------------------------------------------------
    def create_metrology_report(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post("/optics/metrology-reports", json=payload, headers=headers)

    def get_metrology_report(
        self, report_id: str, headers: Headers
    ) -> requests.Response:
        return self.get(f"/optics/metrology-reports/{report_id}", headers=headers)

    def sign_metrology_report(
        self, report_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self.post(
            f"/optics/metrology-reports/{report_id}/sign",
            json=payload if payload is not None else {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Coating chambers and coating runs
    # ------------------------------------------------------------------
    def create_coating_chamber(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post("/optics/coating-chambers", json=payload, headers=headers)

    def get_coating_chamber(
        self, chamber_id: str, headers: Headers
    ) -> requests.Response:
        return self.get(f"/optics/coating-chambers/{chamber_id}", headers=headers)

    def list_coating_chambers(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self.get("/optics/coating-chambers", headers=headers, params=params)

    def create_coating_run(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post("/optics/coating-runs", json=payload, headers=headers)

    def get_coating_run(
        self, coating_run_id: str, headers: Headers
    ) -> requests.Response:
        return self.get(f"/optics/coating-runs/{coating_run_id}", headers=headers)

    def list_coating_runs(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self.get("/optics/coating-runs", headers=headers, params=params)

    def deposit_coating_run(
        self, coating_run_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self.post(
            f"/optics/coating-runs/{coating_run_id}/deposit",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def verify_coating_spectrum(
        self, coating_run_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"/optics/coating-runs/{coating_run_id}/spectral-verification",
            json=payload,
            headers=headers,
        )

    def strip_coating_run(
        self, coating_run_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self.post(
            f"/optics/coating-runs/{coating_run_id}/strip",
            json=payload if payload is not None else {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Assemblies and components
    # ------------------------------------------------------------------
    def create_assembly(self, payload: Payload, headers: Headers) -> requests.Response:
        return self.post("/optics/assemblies", json=payload, headers=headers)

    def get_assembly(self, assembly_id: str, headers: Headers) -> requests.Response:
        return self.get(f"/optics/assemblies/{assembly_id}", headers=headers)

    def list_assemblies(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self.get("/optics/assemblies", headers=headers, params=params)

    def create_assembly_component(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post("/optics/assembly-components", json=payload, headers=headers)

    def list_assembly_components(
        self, assembly_id: str, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self.get(
            f"/optics/assemblies/{assembly_id}/components",
            headers=headers,
            params=params,
        )

    def get_assembly_component(
        self, component_id: str, headers: Headers
    ) -> requests.Response:
        return self.get(f"/optics/assembly-components/{component_id}", headers=headers)

    def cement_assembly(
        self, assembly_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"/optics/assemblies/{assembly_id}/cement", json=payload, headers=headers
        )

    def mount_assembly(
        self, assembly_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"/optics/assemblies/{assembly_id}/mount", json=payload, headers=headers
        )

    def align_assembly(
        self, assembly_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self.post(
            f"/optics/assemblies/{assembly_id}/align",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def seal_assembly(
        self, assembly_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self.post(
            f"/optics/assemblies/{assembly_id}/seal",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def release_assembly(
        self, assembly_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self.post(
            f"/optics/assemblies/{assembly_id}/release",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def get_release_readiness(
        self, assembly_id: str, headers: Headers
    ) -> requests.Response:
        return self.get(
            f"/optics/assemblies/{assembly_id}/release-readiness", headers=headers
        )

    def list_assembly_inspection_records(
        self, assembly_id: str, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self.get(
            f"/optics/assemblies/{assembly_id}/inspection-records",
            headers=headers,
            params=params,
        )

    def list_assembly_documentation_packages(
        self, assembly_id: str, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self.get(
            f"/optics/assemblies/{assembly_id}/documentation-packages",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Inspection records
    # ------------------------------------------------------------------
    def create_inspection_record(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post("/optics/inspection-records", json=payload, headers=headers)

    def get_inspection_record(
        self, record_id: str, headers: Headers
    ) -> requests.Response:
        return self.get(f"/optics/inspection-records/{record_id}", headers=headers)

    def waive_inspection_record(
        self, record_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"/optics/inspection-records/{record_id}/waiver",
            json=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Export classifications
    # ------------------------------------------------------------------
    def create_export_classification(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post(
            "/optics/export-classifications", json=payload, headers=headers
        )

    def get_export_classification(
        self, classification_id: str, headers: Headers
    ) -> requests.Response:
        return self.get(
            f"/optics/export-classifications/{classification_id}", headers=headers
        )

    def record_license_decision(
        self, classification_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"/optics/export-classifications/{classification_id}/license-decision",
            json=payload,
            headers=headers,
        )

    def record_license_revocation(
        self, classification_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"/optics/export-classifications/{classification_id}/revocation",
            json=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Documentation packages
    # ------------------------------------------------------------------
    def create_documentation_package(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post(
            "/optics/documentation-packages", json=payload, headers=headers
        )

    def get_documentation_package(
        self, package_id: str, headers: Headers
    ) -> requests.Response:
        return self.get(f"/optics/documentation-packages/{package_id}", headers=headers)

    def attach_document(
        self, package_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"/optics/documentation-packages/{package_id}/documents",
            json=payload,
            headers=headers,
        )

    def submit_documentation_package(
        self, package_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self.post(
            f"/optics/documentation-packages/{package_id}/submit",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def review_documentation_package(
        self, package_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self.post(
            f"/optics/documentation-packages/{package_id}/review",
            json=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Administrative logical clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Headers) -> requests.Response:
        return self.post(
            "/_clock/set_current_utc",
            json={"current_utc": current_utc},
            headers=headers,
        )

    def raw_post(
        self, path: str, payload: Optional[Dict[str, Any]], headers: Headers
    ) -> requests.Response:
        """Escape hatch for calling an arbitrary path with an arbitrary body."""
        return self.post(path, json=payload, headers=headers)

    def raw_get(
        self, path: str, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        """Escape hatch for reading an arbitrary path."""
        return self.get(path, headers=headers, params=params)
