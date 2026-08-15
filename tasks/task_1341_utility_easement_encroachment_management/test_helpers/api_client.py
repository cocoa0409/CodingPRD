"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # EasementCase
    # ------------------------------------------------------------------
    def create_case(self, payload, headers):
        return self._request("POST", "/easement-cases", payload, headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/easement-cases", headers=headers, params=params)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/easement-cases/{case_id}", headers=headers)

    def begin_mapping(self, case_id, headers):
        return self._request("POST", f"/easement-cases/{case_id}/begin-mapping", {}, headers)

    def activate_monitoring(self, case_id, headers):
        return self._request("POST", f"/easement-cases/{case_id}/activate-monitoring", {}, headers)

    def close_case(self, case_id, headers):
        return self._request("POST", f"/easement-cases/{case_id}/close-case", {}, headers)

    def condemn_case(self, case_id, headers):
        return self._request("POST", f"/easement-cases/{case_id}/condemn", {}, headers)

    def abandon_case(self, case_id, headers):
        return self._request("POST", f"/easement-cases/{case_id}/abandon", {}, headers)

    # ------------------------------------------------------------------
    # EasementDocument
    # ------------------------------------------------------------------
    def create_document(self, case_id, payload, headers):
        return self._request("POST", f"/easement-cases/{case_id}/documents", payload, headers)

    def list_documents(self, case_id, headers, params=None):
        return self._request("GET", f"/easement-cases/{case_id}/documents", headers=headers, params=params)

    def get_document(self, case_id, doc_id, headers):
        return self._request("GET", f"/easement-cases/{case_id}/documents/{doc_id}", headers=headers)

    def record_document(self, case_id, doc_id, headers):
        return self._request("POST", f"/easement-cases/{case_id}/documents/{doc_id}/record", {}, headers)

    def reject_defective_document(self, case_id, doc_id, headers):
        return self._request("POST", f"/easement-cases/{case_id}/documents/{doc_id}/reject-defective", {}, headers)

    # ------------------------------------------------------------------
    # Encroachment
    # ------------------------------------------------------------------
    def create_encroachment(self, case_id, payload, headers):
        return self._request("POST", f"/easement-cases/{case_id}/encroachments", payload, headers)

    def list_encroachments(self, case_id, headers, params=None):
        return self._request("GET", f"/easement-cases/{case_id}/encroachments", headers=headers, params=params)

    def get_encroachment(self, case_id, enc_id, headers):
        return self._request("GET", f"/easement-cases/{case_id}/encroachments/{enc_id}", headers=headers)

    def notify_encroachment(self, case_id, enc_id, payload, headers):
        return self._request("POST", f"/easement-cases/{case_id}/encroachments/{enc_id}/notify", payload, headers)

    def begin_encroachment_negotiation(self, case_id, enc_id, headers):
        return self._request("POST", f"/easement-cases/{case_id}/encroachments/{enc_id}/begin-negotiation", {}, headers)

    def counter_encroachment(self, case_id, enc_id, headers):
        return self._request("POST", f"/easement-cases/{case_id}/encroachments/{enc_id}/counter", {}, headers)

    def resume_encroachment_negotiation(self, case_id, enc_id, headers):
        return self._request("POST", f"/easement-cases/{case_id}/encroachments/{enc_id}/resume-negotiation", {}, headers)

    def agree_encroachment_removal(self, case_id, enc_id, headers):
        return self._request("POST", f"/easement-cases/{case_id}/encroachments/{enc_id}/agree-removal", {}, headers)

    def confirm_encroachment_removal(self, case_id, enc_id, headers):
        return self._request("POST", f"/easement-cases/{case_id}/encroachments/{enc_id}/confirm-removal", {}, headers)

    def escalate_encroachment(self, case_id, enc_id, headers):
        return self._request("POST", f"/easement-cases/{case_id}/encroachments/{enc_id}/escalate", {}, headers)

    def waive_encroachment(self, case_id, enc_id, headers):
        return self._request("POST", f"/easement-cases/{case_id}/encroachments/{enc_id}/waive", {}, headers)

    # ------------------------------------------------------------------
    # AcquisitionOffer
    # ------------------------------------------------------------------
    def create_offer(self, case_id, payload, headers):
        return self._request("POST", f"/easement-cases/{case_id}/offers", payload, headers)

    def list_offers(self, case_id, headers, params=None):
        return self._request("GET", f"/easement-cases/{case_id}/offers", headers=headers, params=params)

    def get_offer(self, case_id, offer_id, headers):
        return self._request("GET", f"/easement-cases/{case_id}/offers/{offer_id}", headers=headers)

    def tender_offer(self, case_id, offer_id, payload, headers):
        return self._request("POST", f"/easement-cases/{case_id}/offers/{offer_id}/tender", payload, headers)

    def counter_offer(self, case_id, offer_id, payload, headers):
        return self._request("POST", f"/easement-cases/{case_id}/offers/{offer_id}/counter", payload, headers)

    def re_tender_offer(self, case_id, offer_id, payload, headers):
        return self._request("POST", f"/easement-cases/{case_id}/offers/{offer_id}/re-tender", payload, headers)

    def accept_offer(self, case_id, offer_id, headers):
        return self._request("POST", f"/easement-cases/{case_id}/offers/{offer_id}/accept", {}, headers)

    def reject_offer(self, case_id, offer_id, headers):
        return self._request("POST", f"/easement-cases/{case_id}/offers/{offer_id}/reject", {}, headers)

    def withdraw_offer(self, case_id, offer_id, headers):
        return self._request("POST", f"/easement-cases/{case_id}/offers/{offer_id}/withdraw", {}, headers)

    def refer_offer_to_condemnation(self, case_id, offer_id, headers):
        return self._request("POST", f"/easement-cases/{case_id}/offers/{offer_id}/refer-to-condemnation", {}, headers)

    # ------------------------------------------------------------------
    # ThirdPartyPermit
    # ------------------------------------------------------------------
    def create_permit(self, case_id, payload, headers):
        return self._request("POST", f"/easement-cases/{case_id}/permits", payload, headers)

    def list_permits(self, case_id, headers, params=None):
        return self._request("GET", f"/easement-cases/{case_id}/permits", headers=headers, params=params)

    def get_permit(self, case_id, permit_id, headers):
        return self._request("GET", f"/easement-cases/{case_id}/permits/{permit_id}", headers=headers)

    def schedule_permit_inspection(self, case_id, permit_id, headers):
        return self._request("POST", f"/easement-cases/{case_id}/permits/{permit_id}/schedule-inspection", {}, headers)

    def record_permit_inspection(self, case_id, permit_id, payload, headers):
        return self._request("POST", f"/easement-cases/{case_id}/permits/{permit_id}/record-inspection", payload, headers)

    def approve_permit(self, case_id, permit_id, payload, headers):
        return self._request("POST", f"/easement-cases/{case_id}/permits/{permit_id}/approve", payload, headers)

    def deny_permit(self, case_id, permit_id, headers):
        return self._request("POST", f"/easement-cases/{case_id}/permits/{permit_id}/deny", {}, headers)

    def revoke_permit(self, case_id, permit_id, headers):
        return self._request("POST", f"/easement-cases/{case_id}/permits/{permit_id}/revoke", {}, headers)

    # ------------------------------------------------------------------
    # VegetationZone / VegetationViolation
    # ------------------------------------------------------------------
    def create_vegetation_zone(self, case_id, payload, headers):
        return self._request("POST", f"/easement-cases/{case_id}/vegetation-zones", payload, headers)

    def list_vegetation_zones(self, case_id, headers, params=None):
        return self._request("GET", f"/easement-cases/{case_id}/vegetation-zones", headers=headers, params=params)

    def get_vegetation_zone(self, case_id, zone_id, headers):
        return self._request("GET", f"/easement-cases/{case_id}/vegetation-zones/{zone_id}", headers=headers)

    def create_vegetation_violation(self, case_id, zone_id, payload, headers):
        return self._request("POST", f"/easement-cases/{case_id}/vegetation-zones/{zone_id}/violations", payload, headers)

    def list_vegetation_violations(self, case_id, zone_id, headers, params=None):
        return self._request("GET", f"/easement-cases/{case_id}/vegetation-zones/{zone_id}/violations", headers=headers, params=params)

    def notify_vegetation_violation(self, case_id, zone_id, viol_id, headers):
        return self._request("POST", f"/easement-cases/{case_id}/vegetation-zones/{zone_id}/violations/{viol_id}/notify", {}, headers)

    def confirm_vegetation_remediation(self, case_id, zone_id, viol_id, headers):
        return self._request("POST", f"/easement-cases/{case_id}/vegetation-zones/{zone_id}/violations/{viol_id}/confirm-remediation", {}, headers)

    def exempt_vegetation_violation(self, case_id, zone_id, viol_id, headers):
        return self._request("POST", f"/easement-cases/{case_id}/vegetation-zones/{zone_id}/violations/{viol_id}/exempt", {}, headers)

    # ------------------------------------------------------------------
    # TitleSearchTask
    # ------------------------------------------------------------------
    def create_title_search(self, case_id, payload, headers):
        return self._request("POST", f"/easement-cases/{case_id}/title-searches", payload, headers)

    def list_title_searches(self, case_id, headers, params=None):
        return self._request("GET", f"/easement-cases/{case_id}/title-searches", headers=headers, params=params)

    def get_title_search(self, case_id, task_id, headers):
        return self._request("GET", f"/easement-cases/{case_id}/title-searches/{task_id}", headers=headers)

    def begin_title_search(self, case_id, task_id, headers):
        return self._request("POST", f"/easement-cases/{case_id}/title-searches/{task_id}/begin", {}, headers)

    def complete_title_search(self, case_id, task_id, payload, headers):
        return self._request("POST", f"/easement-cases/{case_id}/title-searches/{task_id}/complete", payload, headers)

    def cancel_title_search(self, case_id, task_id, headers):
        return self._request("POST", f"/easement-cases/{case_id}/title-searches/{task_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # LitigationReferral
    # ------------------------------------------------------------------
    def create_litigation_referral(self, case_id, payload, headers):
        return self._request("POST", f"/easement-cases/{case_id}/litigation-referrals", payload, headers)

    def list_litigation_referrals(self, case_id, headers, params=None):
        return self._request("GET", f"/easement-cases/{case_id}/litigation-referrals", headers=headers, params=params)

    def get_litigation_referral(self, case_id, ref_id, headers):
        return self._request("GET", f"/easement-cases/{case_id}/litigation-referrals/{ref_id}", headers=headers)

    def accept_litigation_referral(self, case_id, ref_id, headers):
        return self._request("POST", f"/easement-cases/{case_id}/litigation-referrals/{ref_id}/accept", {}, headers)

    def file_litigation_referral(self, case_id, ref_id, headers):
        return self._request("POST", f"/easement-cases/{case_id}/litigation-referrals/{ref_id}/file", {}, headers)

    def settle_litigation_referral(self, case_id, ref_id, headers):
        return self._request("POST", f"/easement-cases/{case_id}/litigation-referrals/{ref_id}/settle", {}, headers)

    def record_litigation_judgment(self, case_id, ref_id, headers):
        return self._request("POST", f"/easement-cases/{case_id}/litigation-referrals/{ref_id}/record-judgment", {}, headers)

    def withdraw_litigation_referral(self, case_id, ref_id, headers):
        return self._request("POST", f"/easement-cases/{case_id}/litigation-referrals/{ref_id}/withdraw", {}, headers)

    # ------------------------------------------------------------------
    # Flat retrieval paths (PRD section 2.9)
    # ------------------------------------------------------------------
    def get_document_flat(self, doc_id, headers):
        return self._request("GET", f"/easement-cases/documents/{doc_id}", headers=headers)

    def list_documents_flat(self, headers, params=None):
        return self._request("GET", "/easement-cases/documents", headers=headers, params=params)

    def get_encroachment_flat(self, enc_id, headers):
        return self._request("GET", f"/easement-cases/encroachments/{enc_id}", headers=headers)

    def list_encroachments_flat(self, headers, params=None):
        return self._request("GET", "/easement-cases/encroachments", headers=headers, params=params)

    def get_offer_flat(self, offer_id, headers):
        return self._request("GET", f"/easement-cases/offers/{offer_id}", headers=headers)

    def list_offers_flat(self, headers, params=None):
        return self._request("GET", "/easement-cases/offers", headers=headers, params=params)

    def get_permit_flat(self, permit_id, headers):
        return self._request("GET", f"/easement-cases/permits/{permit_id}", headers=headers)

    def list_permits_flat(self, headers, params=None):
        return self._request("GET", "/easement-cases/permits", headers=headers, params=params)

    def get_vegetation_zone_flat(self, zone_id, headers):
        return self._request("GET", f"/easement-cases/vegetation-zones/{zone_id}", headers=headers)

    def list_vegetation_zones_flat(self, headers, params=None):
        return self._request("GET", "/easement-cases/vegetation-zones", headers=headers, params=params)

    def get_vegetation_violation_flat(self, viol_id, headers):
        return self._request("GET", f"/easement-cases/violations/{viol_id}", headers=headers)

    def list_vegetation_violations_flat(self, headers, params=None):
        return self._request("GET", "/easement-cases/violations", headers=headers, params=params)

    def get_title_search_flat(self, task_id, headers):
        return self._request("GET", f"/easement-cases/title-searches/{task_id}", headers=headers)

    def list_title_searches_flat(self, headers, params=None):
        return self._request("GET", "/easement-cases/title-searches", headers=headers, params=params)

    def get_litigation_referral_flat(self, ref_id, headers):
        return self._request("GET", f"/easement-cases/litigation-referrals/{ref_id}", headers=headers)

    def list_litigation_referrals_flat(self, headers, params=None):
        return self._request("GET", "/easement-cases/litigation-referrals", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Logical clock (PRD section 2.10)
    # ------------------------------------------------------------------
    def set_current_utc(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
