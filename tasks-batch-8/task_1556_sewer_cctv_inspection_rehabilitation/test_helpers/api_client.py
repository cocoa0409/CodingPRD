"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/sewer/_clock/set_current_utc", payload, headers)

    # --- SewerDistrict ---
    def create_district(self, payload, headers):
        return self._request("POST", "/sewer/districts", payload, headers)

    def get_district(self, district_id, headers):
        return self._request("GET", f"/sewer/districts/{district_id}", headers=headers)

    def list_districts(self, headers, params=None):
        return self._request("GET", "/sewer/districts", headers=headers, params=params)

    # --- Technician ---
    def create_technician(self, payload, headers):
        return self._request("POST", "/sewer/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/sewer/technicians/{technician_id}", headers=headers)

    def update_technician(self, technician_id, payload, headers):
        return self._request("PATCH", f"/sewer/technicians/{technician_id}", payload, headers)

    # --- InspectionCycle ---
    def create_inspection_cycle(self, district_id, payload, headers):
        return self._request("POST", f"/sewer/districts/{district_id}/inspection-cycles", payload, headers)

    def get_inspection_cycle(self, cycle_id, headers):
        return self._request("GET", f"/sewer/inspection-cycles/{cycle_id}", headers=headers)

    def list_inspection_cycles(self, district_id, headers, params=None):
        return self._request("GET", f"/sewer/districts/{district_id}/inspection-cycles", headers=headers, params=params)

    def open_inspection_cycle(self, cycle_id, headers):
        return self._request("POST", f"/sewer/inspection-cycles/{cycle_id}/open", {}, headers)

    def close_inspection_cycle(self, cycle_id, headers):
        return self._request("POST", f"/sewer/inspection-cycles/{cycle_id}/close", {}, headers)

    # --- PipeSegment ---
    def create_segment(self, district_id, payload, headers):
        return self._request("POST", f"/sewer/districts/{district_id}/segments", payload, headers)

    def get_segment(self, segment_id, headers):
        return self._request("GET", f"/sewer/segments/{segment_id}", headers=headers)

    def list_segments(self, district_id, headers, params=None):
        return self._request("GET", f"/sewer/districts/{district_id}/segments", headers=headers, params=params)

    # --- Lateral ---
    def create_lateral(self, segment_id, payload, headers):
        return self._request("POST", f"/sewer/segments/{segment_id}/laterals", payload, headers)

    def list_laterals(self, segment_id, headers, params=None):
        return self._request("GET", f"/sewer/segments/{segment_id}/laterals", headers=headers, params=params)

    def reinstate_lateral(self, segment_id, lateral_id, headers):
        return self._request("POST", f"/sewer/segments/{segment_id}/laterals/{lateral_id}/reinstate", {}, headers)

    # --- CctvInspection ---
    def create_cctv_inspection(self, segment_id, payload, headers):
        return self._request("POST", f"/sewer/segments/{segment_id}/cctv-inspections", payload, headers)

    def get_cctv_inspection(self, inspection_id, headers):
        return self._request("GET", f"/sewer/cctv-inspections/{inspection_id}", headers=headers)

    def list_segment_inspections(self, segment_id, headers, params=None):
        return self._request("GET", f"/sewer/segments/{segment_id}/cctv-inspections", headers=headers, params=params)

    def list_cctv_inspections(self, headers, params=None):
        return self._request("GET", "/sewer/cctv-inspections", headers=headers, params=params)

    def start_inspection(self, inspection_id, headers):
        return self._request("POST", f"/sewer/cctv-inspections/{inspection_id}/start", {}, headers)

    def begin_coding(self, inspection_id, headers):
        return self._request("POST", f"/sewer/cctv-inspections/{inspection_id}/begin-coding", {}, headers)

    def submit_qa(self, inspection_id, headers):
        return self._request("POST", f"/sewer/cctv-inspections/{inspection_id}/submit-qa", {}, headers)

    def certify_inspection(self, inspection_id, headers):
        return self._request("POST", f"/sewer/cctv-inspections/{inspection_id}/certify", {}, headers)

    def reject_inspection(self, inspection_id, headers, payload=None):
        return self._request("POST", f"/sewer/cctv-inspections/{inspection_id}/reject", payload or {}, headers)

    def void_inspection(self, inspection_id, headers):
        return self._request("POST", f"/sewer/cctv-inspections/{inspection_id}/void", {}, headers)

    # --- DefectObservation ---
    def create_defect(self, inspection_id, payload, headers):
        return self._request("POST", f"/sewer/cctv-inspections/{inspection_id}/defects", payload, headers)

    def list_defects(self, inspection_id, headers, params=None):
        return self._request("GET", f"/sewer/cctv-inspections/{inspection_id}/defects", headers=headers, params=params)

    def delete_defect(self, inspection_id, defect_id, headers):
        return self._request("DELETE", f"/sewer/cctv-inspections/{inspection_id}/defects/{defect_id}", headers=headers)

    # --- RehabPlan ---
    def create_rehab_plan(self, segment_id, payload, headers):
        return self._request("POST", f"/sewer/segments/{segment_id}/rehab-plans", payload, headers)

    def get_rehab_plan(self, plan_id, headers):
        return self._request("GET", f"/sewer/rehab-plans/{plan_id}", headers=headers)

    def list_segment_plans(self, segment_id, headers, params=None):
        return self._request("GET", f"/sewer/segments/{segment_id}/rehab-plans", headers=headers, params=params)

    def list_rehab_plans(self, headers, params=None):
        return self._request("GET", "/sewer/rehab-plans", headers=headers, params=params)

    def propose_plan(self, plan_id, headers):
        return self._request("POST", f"/sewer/rehab-plans/{plan_id}/propose", {}, headers)

    def approve_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/sewer/rehab-plans/{plan_id}/approve", payload, headers)

    def reopen_plan(self, plan_id, headers):
        return self._request("POST", f"/sewer/rehab-plans/{plan_id}/reopen", {}, headers)

    def cancel_plan(self, plan_id, headers):
        return self._request("POST", f"/sewer/rehab-plans/{plan_id}/cancel", {}, headers)

    # --- WorkOrder ---
    def create_work_order(self, plan_id, payload, headers):
        return self._request("POST", f"/sewer/rehab-plans/{plan_id}/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/sewer/work-orders/{work_order_id}", headers=headers)

    def list_plan_work_orders(self, plan_id, headers, params=None):
        return self._request("GET", f"/sewer/rehab-plans/{plan_id}/work-orders", headers=headers, params=params)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/sewer/work-orders", headers=headers, params=params)

    def mobilize_work_order(self, work_order_id, headers):
        return self._request("POST", f"/sewer/work-orders/{work_order_id}/mobilize", {}, headers)

    def begin_work(self, work_order_id, headers):
        return self._request("POST", f"/sewer/work-orders/{work_order_id}/begin-work", {}, headers)

    def stand_down_work_order(self, work_order_id, headers):
        return self._request("POST", f"/sewer/work-orders/{work_order_id}/stand-down", {}, headers)

    def submit_punch(self, work_order_id, headers):
        return self._request("POST", f"/sewer/work-orders/{work_order_id}/submit-punch", {}, headers)

    def resume_work(self, work_order_id, headers):
        return self._request("POST", f"/sewer/work-orders/{work_order_id}/resume-work", {}, headers)

    def complete_work_order(self, work_order_id, headers):
        return self._request("POST", f"/sewer/work-orders/{work_order_id}/complete", {}, headers)

    def cancel_work_order(self, work_order_id, headers):
        return self._request("POST", f"/sewer/work-orders/{work_order_id}/cancel", {}, headers)

    def invoice_work_order(self, work_order_id, headers):
        return self._request("POST", f"/sewer/work-orders/{work_order_id}/invoice", {}, headers)

    def void_invoice(self, work_order_id, headers):
        return self._request("POST", f"/sewer/work-orders/{work_order_id}/void-invoice", {}, headers)

    def mark_paid(self, work_order_id, headers):
        return self._request("POST", f"/sewer/work-orders/{work_order_id}/mark-paid", {}, headers)

    # --- WorkOrderLineItem ---
    def create_line_item(self, work_order_id, payload, headers):
        return self._request("POST", f"/sewer/work-orders/{work_order_id}/line-items", payload, headers)

    def list_line_items(self, work_order_id, headers, params=None):
        return self._request("GET", f"/sewer/work-orders/{work_order_id}/line-items", headers=headers, params=params)

    def update_line_item(self, work_order_id, line_id, payload, headers):
        return self._request("PATCH", f"/sewer/work-orders/{work_order_id}/line-items/{line_id}", payload, headers)

    # --- BypassPlan ---
    def create_bypass_plan(self, work_order_id, payload, headers):
        return self._request("POST", f"/sewer/work-orders/{work_order_id}/bypass-plans", payload, headers)

    def get_bypass_plan(self, bypass_plan_id, headers):
        return self._request("GET", f"/sewer/bypass-plans/{bypass_plan_id}", headers=headers)

    def list_bypass_plans(self, work_order_id, headers, params=None):
        return self._request("GET", f"/sewer/work-orders/{work_order_id}/bypass-plans", headers=headers, params=params)

    def approve_bypass_plan(self, bypass_plan_id, headers):
        return self._request("POST", f"/sewer/bypass-plans/{bypass_plan_id}/approve", {}, headers)

    def reject_bypass_plan(self, bypass_plan_id, headers):
        return self._request("POST", f"/sewer/bypass-plans/{bypass_plan_id}/reject", {}, headers)

    def activate_bypass_plan(self, bypass_plan_id, headers):
        return self._request("POST", f"/sewer/bypass-plans/{bypass_plan_id}/activate", {}, headers)

    def demobilize_bypass_plan(self, bypass_plan_id, headers):
        return self._request("POST", f"/sewer/bypass-plans/{bypass_plan_id}/demobilize", {}, headers)

    def close_bypass_plan(self, bypass_plan_id, headers):
        return self._request("POST", f"/sewer/bypass-plans/{bypass_plan_id}/close", {}, headers)

    # --- CustomerNotice ---
    def create_customer_notice(self, work_order_id, payload, headers):
        return self._request("POST", f"/sewer/work-orders/{work_order_id}/customer-notices", payload, headers)

    def get_customer_notice(self, notice_id, headers):
        return self._request("GET", f"/sewer/customer-notices/{notice_id}", headers=headers)

    def list_customer_notices(self, work_order_id, headers, params=None):
        return self._request("GET", f"/sewer/work-orders/{work_order_id}/customer-notices", headers=headers, params=params)

    def send_notice(self, notice_id, headers):
        return self._request("POST", f"/sewer/customer-notices/{notice_id}/send", {}, headers)

    def acknowledge_notice(self, notice_id, headers):
        return self._request("POST", f"/sewer/customer-notices/{notice_id}/acknowledge", {}, headers)

    # --- WarrantyCase ---
    def create_warranty_case(self, segment_id, payload, headers):
        return self._request("POST", f"/sewer/segments/{segment_id}/warranty-cases", payload, headers)

    def get_warranty_case(self, case_id, headers):
        return self._request("GET", f"/sewer/warranty-cases/{case_id}", headers=headers)

    def list_segment_warranty_cases(self, segment_id, headers, params=None):
        return self._request("GET", f"/sewer/segments/{segment_id}/warranty-cases", headers=headers, params=params)

    def list_warranty_cases(self, headers, params=None):
        return self._request("GET", "/sewer/warranty-cases", headers=headers, params=params)

    def authorize_repair(self, case_id, headers):
        return self._request("POST", f"/sewer/warranty-cases/{case_id}/authorize-repair", {}, headers)

    def deny_warranty_case(self, case_id, payload, headers):
        return self._request("POST", f"/sewer/warranty-cases/{case_id}/deny", payload, headers)

    def resolve_warranty_case(self, case_id, payload, headers):
        return self._request("POST", f"/sewer/warranty-cases/{case_id}/resolve", payload, headers)

    def reopen_warranty_case(self, case_id, headers):
        return self._request("POST", f"/sewer/warranty-cases/{case_id}/reopen", {}, headers)

    def withdraw_warranty_case(self, case_id, headers):
        return self._request("POST", f"/sewer/warranty-cases/{case_id}/withdraw", {}, headers)

    # --- FlowMonitoringPeriod ---
    def create_flow_period(self, district_id, payload, headers):
        return self._request("POST", f"/sewer/districts/{district_id}/flow-periods", payload, headers)

    def get_flow_period(self, period_id, headers):
        return self._request("GET", f"/sewer/flow-periods/{period_id}", headers=headers)

    def list_flow_periods(self, district_id, headers, params=None):
        return self._request("GET", f"/sewer/districts/{district_id}/flow-periods", headers=headers, params=params)

    def activate_flow_period(self, period_id, headers):
        return self._request("POST", f"/sewer/flow-periods/{period_id}/activate", {}, headers)

    def close_flow_period(self, period_id, payload, headers):
        return self._request("POST", f"/sewer/flow-periods/{period_id}/close", payload, headers)

    def analyze_flow_period(self, period_id, headers):
        return self._request("POST", f"/sewer/flow-periods/{period_id}/analyze", {}, headers)


api_client = ApiClient()
