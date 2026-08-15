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
    # Program cycles
    # ------------------------------------------------------------------
    def create_program_cycle(self, payload, headers):
        return self._request("POST", "/program-cycles", payload, headers)

    def get_program_cycle(self, cycle_id, headers):
        return self._request("GET", f"/program-cycles/{cycle_id}", headers=headers)

    def lock_program_cycle(self, cycle_id, headers):
        return self._request("POST", f"/program-cycles/{cycle_id}/lock", {}, headers)

    def close_program_cycle(self, cycle_id, headers):
        return self._request("POST", f"/program-cycles/{cycle_id}/close", {}, headers)

    def adjust_appropriation(self, cycle_id, payload, headers):
        return self._request("POST",
                             f"/program-cycles/{cycle_id}/appropriation-adjustments",
                             payload, headers)

    # ------------------------------------------------------------------
    # Property owners
    # ------------------------------------------------------------------
    def create_property_owner(self, payload, headers):
        return self._request("POST", "/property-owners", payload, headers)

    def get_property_owner(self, owner_id, headers):
        return self._request("GET", f"/property-owners/{owner_id}", headers=headers)

    # ------------------------------------------------------------------
    # Parcels
    # ------------------------------------------------------------------
    def create_parcel(self, payload, headers):
        return self._request("POST", "/parcels", payload, headers)

    def list_parcels(self, headers, params=None):
        return self._request("GET", "/parcels", headers=headers, params=params)

    def get_parcel(self, parcel_id, headers):
        return self._request("GET", f"/parcels/{parcel_id}", headers=headers)

    # ------------------------------------------------------------------
    # Sidewalk segments
    # ------------------------------------------------------------------
    def create_segment(self, payload, headers):
        return self._request("POST", "/segments", payload, headers)

    def list_segments(self, headers, params=None):
        return self._request("GET", "/segments", headers=headers, params=params)

    def get_segment(self, segment_id, headers):
        return self._request("GET", f"/segments/{segment_id}", headers=headers)

    # ------------------------------------------------------------------
    # Defects
    # ------------------------------------------------------------------
    def create_defect(self, payload, headers):
        return self._request("POST", "/defects", payload, headers)

    def list_defects(self, headers, params=None):
        return self._request("GET", "/defects", headers=headers, params=params)

    def get_defect(self, defect_id, headers):
        return self._request("GET", f"/defects/{defect_id}", headers=headers)

    def list_defect_forestry_reviews(self, defect_id, headers, params=None):
        return self._request("GET", f"/defects/{defect_id}/forestry-reviews",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Repair notices
    # ------------------------------------------------------------------
    def create_repair_notice(self, payload, headers):
        return self._request("POST", "/repair-notices", payload, headers)

    def list_repair_notices(self, headers, params=None):
        return self._request("GET", "/repair-notices", headers=headers, params=params)

    def get_repair_notice(self, notice_id, headers):
        return self._request("GET", f"/repair-notices/{notice_id}", headers=headers)

    def issue_repair_notice(self, notice_id, headers):
        return self._request("POST", f"/repair-notices/{notice_id}/issue", {}, headers)

    def extend_repair_notice(self, notice_id, payload, headers):
        return self._request("POST", f"/repair-notices/{notice_id}/extensions",
                             payload, headers)

    def appeal_repair_notice(self, notice_id, payload, headers):
        return self._request("POST", f"/repair-notices/{notice_id}/appeal",
                             payload, headers)

    def decide_appeal(self, notice_id, payload, headers):
        return self._request("POST", f"/repair-notices/{notice_id}/appeal-decision",
                             payload, headers)

    def create_inspection(self, notice_id, payload, headers):
        return self._request("POST", f"/repair-notices/{notice_id}/inspections",
                             payload, headers)

    def list_inspections(self, notice_id, headers, params=None):
        return self._request("GET", f"/repair-notices/{notice_id}/inspections",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Cost-share applications
    # ------------------------------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", "/cost-share-applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/cost-share-applications",
                             headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET",
                             f"/cost-share-applications/{application_id}",
                             headers=headers)

    def decide_application(self, application_id, payload, headers):
        return self._request("POST",
                             f"/cost-share-applications/{application_id}/decision",
                             payload, headers)

    def resubmit_application(self, application_id, headers):
        return self._request("POST",
                             f"/cost-share-applications/{application_id}/resubmit",
                             {}, headers)

    def obligate_application(self, application_id, headers):
        return self._request("POST",
                             f"/cost-share-applications/{application_id}/obligate",
                             {}, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST",
                             f"/cost-share-applications/{application_id}/withdraw",
                             {}, headers)

    def reimburse_application(self, application_id, payload, headers):
        return self._request("POST",
                             f"/cost-share-applications/{application_id}/reimburse",
                             payload, headers)

    # ------------------------------------------------------------------
    # Bid batches
    # ------------------------------------------------------------------
    def create_bid_batch(self, payload, headers):
        return self._request("POST", "/bid-batches", payload, headers)

    def list_bid_batches(self, headers, params=None):
        return self._request("GET", "/bid-batches", headers=headers, params=params)

    def get_bid_batch(self, batch_id, headers):
        return self._request("GET", f"/bid-batches/{batch_id}", headers=headers)

    def seal_bid_batch(self, batch_id, headers):
        return self._request("POST", f"/bid-batches/{batch_id}/seal", {}, headers)

    def award_bid_batch(self, batch_id, headers):
        return self._request("POST", f"/bid-batches/{batch_id}/award", {}, headers)

    def start_batch_work(self, batch_id, headers):
        return self._request("POST", f"/bid-batches/{batch_id}/start-work", {}, headers)

    def cancel_bid_batch(self, batch_id, headers):
        return self._request("POST", f"/bid-batches/{batch_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Batch work items
    # ------------------------------------------------------------------
    def create_work_item(self, payload, headers):
        return self._request("POST", "/batch-work-items", payload, headers)

    def list_work_items(self, headers, params=None):
        return self._request("GET", "/batch-work-items", headers=headers, params=params)

    def get_work_item(self, item_id, headers):
        return self._request("GET", f"/batch-work-items/{item_id}", headers=headers)

    def remove_work_item(self, item_id, headers):
        return self._request("POST", f"/batch-work-items/{item_id}/remove", {}, headers)

    def complete_work_item(self, item_id, headers):
        return self._request("POST", f"/batch-work-items/{item_id}/complete",
                             {}, headers)

    def verify_work_item(self, item_id, headers):
        return self._request("POST", f"/batch-work-items/{item_id}/verify", {}, headers)

    # ------------------------------------------------------------------
    # Contractors
    # ------------------------------------------------------------------
    def create_contractor(self, payload, headers):
        return self._request("POST", "/contractors", payload, headers)

    def list_contractors(self, headers, params=None):
        return self._request("GET", "/contractors", headers=headers, params=params)

    def suspend_contractor(self, contractor_id, headers):
        return self._request("POST", f"/contractors/{contractor_id}/suspend",
                             {}, headers)

    # ------------------------------------------------------------------
    # Bids
    # ------------------------------------------------------------------
    def create_bid(self, payload, headers):
        return self._request("POST", "/bids", payload, headers)

    def list_bids(self, headers, params=None):
        return self._request("GET", "/bids", headers=headers, params=params)

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"/bids/{bid_id}", headers=headers)

    def withdraw_bid(self, bid_id, headers):
        return self._request("POST", f"/bids/{bid_id}/withdraw", {}, headers)

    # ------------------------------------------------------------------
    # Forestry reviews
    # ------------------------------------------------------------------
    def decide_forestry_review(self, review_id, payload, headers):
        return self._request("POST", f"/forestry-reviews/{review_id}/decision",
                             payload, headers)

    def clear_forestry_review(self, review_id, headers):
        return self._request("POST", f"/forestry-reviews/{review_id}/clear",
                             {}, headers)

    # ------------------------------------------------------------------
    # Lien cases
    # ------------------------------------------------------------------
    def create_lien_case(self, payload, headers):
        return self._request("POST", "/lien-cases", payload, headers)

    def list_lien_cases(self, headers, params=None):
        return self._request("GET", "/lien-cases", headers=headers, params=params)

    def get_lien_case(self, lien_id, headers):
        return self._request("GET", f"/lien-cases/{lien_id}", headers=headers)

    def get_payoff_quote(self, lien_id, headers):
        return self._request("GET", f"/lien-cases/{lien_id}/payoff-quote",
                             headers=headers)

    def record_lien_case(self, lien_id, headers):
        return self._request("POST", f"/lien-cases/{lien_id}/record", {}, headers)

    def post_lien_payment(self, lien_id, payload, headers):
        return self._request("POST", f"/lien-cases/{lien_id}/payments",
                             payload, headers)

    def refer_foreclosure(self, lien_id, headers):
        return self._request("POST",
                             f"/lien-cases/{lien_id}/foreclosure-referral",
                             {}, headers)

    # ------------------------------------------------------------------
    # Delinquency sweeps
    # ------------------------------------------------------------------
    def run_delinquency_sweep(self, headers):
        return self._request("POST", "/delinquency-sweeps", {}, headers)


api_client = ApiClient()
