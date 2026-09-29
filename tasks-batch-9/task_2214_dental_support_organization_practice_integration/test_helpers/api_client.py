"""API client: one method per endpoint defined in the PRD (§4)."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed endpoint surface for the DSO Practice Integration API."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, payload, headers):
        return self._request("POST", "/dso/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Affiliations
    # ------------------------------------------------------------------

    def create_affiliation(self, payload, headers):
        return self._request("POST", "/dso/affiliations", payload, headers)

    def get_affiliation(self, affiliation_id, headers):
        return self._request(
            "GET", f"/dso/affiliations/{affiliation_id}", headers=headers
        )

    def list_affiliations(self, headers, params=None):
        return self._request("GET", "/dso/affiliations", headers=headers, params=params)

    def advance_diligence(self, affiliation_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dso/affiliations/{affiliation_id}/advance-diligence",
            payload if payload is not None else {},
            headers,
        )

    def reprice_affiliation(self, affiliation_id, payload, headers):
        return self._request(
            "POST", f"/dso/affiliations/{affiliation_id}/reprice", payload, headers
        )

    def sign_affiliation(self, affiliation_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dso/affiliations/{affiliation_id}/sign",
            payload if payload is not None else {},
            headers,
        )

    def close_affiliation(self, affiliation_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dso/affiliations/{affiliation_id}/close",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Conversion vendors
    # ------------------------------------------------------------------

    def create_conversion_vendor(self, payload, headers):
        return self._request("POST", "/dso/conversion-vendors", payload, headers)

    def get_conversion_vendor(self, conversion_vendor_id, headers):
        return self._request(
            "GET", f"/dso/conversion-vendors/{conversion_vendor_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Practices
    # ------------------------------------------------------------------

    def create_practice(self, payload, headers):
        return self._request("POST", "/dso/practices", payload, headers)

    def get_practice(self, practice_id, headers):
        return self._request("GET", f"/dso/practices/{practice_id}", headers=headers)

    def list_practices(self, headers, params=None):
        return self._request("GET", "/dso/practices", headers=headers, params=params)

    def standardize_staffing(self, practice_id, payload, headers):
        return self._request(
            "POST", f"/dso/practices/{practice_id}/standardize-staffing", payload, headers
        )

    def list_practice_vendor_consolidations(self, practice_id, headers, params=None):
        return self._request(
            "GET",
            f"/dso/practices/{practice_id}/vendor-consolidations",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Doctors
    # ------------------------------------------------------------------

    def create_doctor(self, payload, headers):
        return self._request("POST", "/dso/doctors", payload, headers)

    def get_doctor(self, doctor_id, headers):
        return self._request("GET", f"/dso/doctors/{doctor_id}", headers=headers)

    # ------------------------------------------------------------------
    # Doctor employments
    # ------------------------------------------------------------------

    def create_doctor_employment(self, payload, headers):
        return self._request("POST", "/dso/doctor-employments", payload, headers)

    def get_doctor_employment(self, doctor_employment_id, headers):
        return self._request(
            "GET", f"/dso/doctor-employments/{doctor_employment_id}", headers=headers
        )

    def list_doctor_employments(self, headers, params=None):
        return self._request(
            "GET", "/dso/doctor-employments", headers=headers, params=params
        )

    def accept_offer(self, doctor_employment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dso/doctor-employments/{doctor_employment_id}/accept-offer",
            payload if payload is not None else {},
            headers,
        )

    def harmonize_compensation(self, doctor_employment_id, payload, headers):
        return self._request(
            "POST",
            f"/dso/doctor-employments/{doctor_employment_id}/harmonize-compensation",
            payload,
            headers,
        )

    def separate_employment(self, doctor_employment_id, payload, headers):
        return self._request(
            "POST",
            f"/dso/doctor-employments/{doctor_employment_id}/separate",
            payload,
            headers,
        )

    def transfer_records_custody(self, doctor_employment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dso/doctor-employments/{doctor_employment_id}/records-custody-transfer",
            payload if payload is not None else {},
            headers,
        )

    def enforce_non_compete(self, doctor_employment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dso/doctor-employments/{doctor_employment_id}/enforce-non-compete",
            payload if payload is not None else {},
            headers,
        )

    def list_employment_supply_preference_exceptions(
        self, doctor_employment_id, headers, params=None
    ):
        return self._request(
            "GET",
            f"/dso/doctor-employments/{doctor_employment_id}/supply-preference-exceptions",
            headers=headers,
            params=params,
        )

    def list_employment_clinical_quality_reviews(
        self, doctor_employment_id, headers, params=None
    ):
        return self._request(
            "GET",
            f"/dso/doctor-employments/{doctor_employment_id}/clinical-quality-reviews",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Management services agreements
    # ------------------------------------------------------------------

    def create_service_agreement(self, payload, headers):
        return self._request("POST", "/dso/service-agreements", payload, headers)

    def get_service_agreement(self, service_agreement_id, headers):
        return self._request(
            "GET", f"/dso/service-agreements/{service_agreement_id}", headers=headers
        )

    def list_service_agreements(self, headers, params=None):
        return self._request(
            "GET", "/dso/service-agreements", headers=headers, params=params
        )

    def add_service_line_item(self, service_agreement_id, payload, headers):
        return self._request(
            "POST",
            f"/dso/service-agreements/{service_agreement_id}/line-items",
            payload,
            headers,
        )

    def list_service_line_items(self, service_agreement_id, headers, params=None):
        return self._request(
            "GET",
            f"/dso/service-agreements/{service_agreement_id}/line-items",
            headers=headers,
            params=params,
        )

    def submit_legal_review(self, service_agreement_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dso/service-agreements/{service_agreement_id}/submit-legal-review",
            payload if payload is not None else {},
            headers,
        )

    def reject_scope(self, service_agreement_id, payload, headers):
        return self._request(
            "POST",
            f"/dso/service-agreements/{service_agreement_id}/reject-scope",
            payload,
            headers,
        )

    def make_agreement_effective(self, service_agreement_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dso/service-agreements/{service_agreement_id}/make-effective",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Migration batches
    # ------------------------------------------------------------------

    def create_migration_batch(self, payload, headers):
        return self._request("POST", "/dso/migration-batches", payload, headers)

    def get_migration_batch(self, migration_batch_id, headers):
        return self._request(
            "GET", f"/dso/migration-batches/{migration_batch_id}", headers=headers
        )

    def list_migration_batches(self, headers, params=None):
        return self._request(
            "GET", "/dso/migration-batches", headers=headers, params=params
        )

    def schedule_cutover(self, migration_batch_id, payload, headers):
        return self._request(
            "POST",
            f"/dso/migration-batches/{migration_batch_id}/schedule-cutover",
            payload,
            headers,
        )

    def validate_batch(self, migration_batch_id, payload, headers):
        return self._request(
            "POST",
            f"/dso/migration-batches/{migration_batch_id}/validate",
            payload,
            headers,
        )

    def remediate_batch(self, migration_batch_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dso/migration-batches/{migration_batch_id}/remediate",
            payload if payload is not None else {},
            headers,
        )

    def rollback_batch(self, migration_batch_id, payload, headers):
        return self._request(
            "POST",
            f"/dso/migration-batches/{migration_batch_id}/rollback",
            payload,
            headers,
        )

    def reconcile_batch(self, migration_batch_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dso/migration-batches/{migration_batch_id}/reconcile",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Payer contracts and fee schedules
    # ------------------------------------------------------------------

    def create_payer_contract(self, payload, headers):
        return self._request("POST", "/dso/payer-contracts", payload, headers)

    def get_payer_contract(self, payer_contract_id, headers):
        return self._request(
            "GET", f"/dso/payer-contracts/{payer_contract_id}", headers=headers
        )

    def list_payer_contracts(self, headers, params=None):
        return self._request(
            "GET", "/dso/payer-contracts", headers=headers, params=params
        )

    def add_fee_schedule_item(self, payer_contract_id, payload, headers):
        return self._request(
            "POST",
            f"/dso/payer-contracts/{payer_contract_id}/fee-schedule-items",
            payload,
            headers,
        )

    def list_fee_schedule_items(self, payer_contract_id, headers, params=None):
        return self._request(
            "GET",
            f"/dso/payer-contracts/{payer_contract_id}/fee-schedule-items",
            headers=headers,
            params=params,
        )

    def activate_fee_schedule(self, payer_contract_id, payload, headers):
        return self._request(
            "POST",
            f"/dso/payer-contracts/{payer_contract_id}/activate-fee-schedule",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Payer enrollments
    # ------------------------------------------------------------------

    def create_payer_enrollment(self, payload, headers):
        return self._request("POST", "/dso/payer-enrollments", payload, headers)

    def get_payer_enrollment(self, payer_enrollment_id, headers):
        return self._request(
            "GET", f"/dso/payer-enrollments/{payer_enrollment_id}", headers=headers
        )

    def list_payer_enrollments(self, headers, params=None):
        return self._request(
            "GET", "/dso/payer-enrollments", headers=headers, params=params
        )

    def submit_enrollment(self, payer_enrollment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dso/payer-enrollments/{payer_enrollment_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def decide_enrollment(self, payer_enrollment_id, payload, headers):
        return self._request(
            "POST",
            f"/dso/payer-enrollments/{payer_enrollment_id}/decide",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Earn-out tranches
    # ------------------------------------------------------------------

    def create_earnout_tranche(self, payload, headers):
        return self._request("POST", "/dso/earnout-tranches", payload, headers)

    def get_earnout_tranche(self, earnout_tranche_id, headers):
        return self._request(
            "GET", f"/dso/earnout-tranches/{earnout_tranche_id}", headers=headers
        )

    def list_earnout_tranches(self, headers, params=None):
        return self._request(
            "GET", "/dso/earnout-tranches", headers=headers, params=params
        )

    def reserve_tranche(self, earnout_tranche_id, payload, headers):
        return self._request(
            "POST",
            f"/dso/earnout-tranches/{earnout_tranche_id}/reserve",
            payload,
            headers,
        )

    def settle_tranche(self, earnout_tranche_id, payload, headers):
        return self._request(
            "POST",
            f"/dso/earnout-tranches/{earnout_tranche_id}/settle",
            payload,
            headers,
        )

    def claw_back_tranche(self, earnout_tranche_id, payload, headers):
        return self._request(
            "POST",
            f"/dso/earnout-tranches/{earnout_tranche_id}/claw-back",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Supply preference exceptions
    # ------------------------------------------------------------------

    def create_supply_preference_exception(self, payload, headers):
        return self._request(
            "POST", "/dso/supply-preference-exceptions", payload, headers
        )

    def get_supply_preference_exception(self, supply_preference_exception_id, headers):
        return self._request(
            "GET",
            f"/dso/supply-preference-exceptions/{supply_preference_exception_id}",
            headers=headers,
        )

    def decide_supply_preference_exception(
        self, supply_preference_exception_id, payload, headers
    ):
        return self._request(
            "POST",
            f"/dso/supply-preference-exceptions/{supply_preference_exception_id}/decide",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Vendor consolidations
    # ------------------------------------------------------------------

    def create_vendor_consolidation(self, payload, headers):
        return self._request("POST", "/dso/vendor-consolidations", payload, headers)

    def get_vendor_consolidation(self, vendor_consolidation_id, headers):
        return self._request(
            "GET",
            f"/dso/vendor-consolidations/{vendor_consolidation_id}",
            headers=headers,
        )

    def finalize_vendor_consolidation(
        self, vendor_consolidation_id, headers, payload=None
    ):
        return self._request(
            "POST",
            f"/dso/vendor-consolidations/{vendor_consolidation_id}/finalize",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Clinical quality reviews
    # ------------------------------------------------------------------

    def create_clinical_quality_review(self, payload, headers):
        return self._request("POST", "/dso/clinical-quality-reviews", payload, headers)

    def get_clinical_quality_review(self, clinical_quality_review_id, headers):
        return self._request(
            "GET",
            f"/dso/clinical-quality-reviews/{clinical_quality_review_id}",
            headers=headers,
        )

    def close_clinical_quality_review(
        self, clinical_quality_review_id, payload, headers
    ):
        return self._request(
            "POST",
            f"/dso/clinical-quality-reviews/{clinical_quality_review_id}/close",
            payload,
            headers,
        )


api_client = ApiClient()
