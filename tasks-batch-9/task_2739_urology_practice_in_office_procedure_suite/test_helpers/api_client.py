"""
Typed HTTP client for the Urology Practice & In-Office Procedure Suite API.

One method per endpoint of the contract. Every resource sits directly beneath
the ``/urology`` prefix, so no path is nested inside another resource. List
methods accept their filters as keyword arguments; a filter left at ``None`` is
dropped so that omitting it means "unfiltered" rather than "match null".
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


def _clean(params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Drop unsupplied query parameters so they are not sent at all."""
    if params is None:
        return None
    return {k: v for k, v in params.items() if v is not None}


class ApiClient(GenericApiClient):
    """Thin, fully explicit wrapper over the contract's 66 endpoints."""

    # ─── Providers ─────────────────────────────────────────────────────────
    def create_provider(self, payload, headers):
        return self._request("POST", "/urology/providers", payload, headers)

    def update_provider(self, provider_id, payload, headers):
        return self._request(
            "PATCH", f"/urology/providers/{provider_id}", payload, headers
        )

    def get_provider(self, provider_id, headers):
        return self._request(
            "GET", f"/urology/providers/{provider_id}", None, headers
        )

    def list_providers(self, headers, **filters):
        return self._request("GET", "/urology/providers", _clean(filters), headers)

    # ─── Patients ──────────────────────────────────────────────────────────
    def create_patient(self, payload, headers):
        return self._request("POST", "/urology/patients", payload, headers)

    def update_patient(self, patient_id, payload, headers):
        return self._request(
            "PATCH", f"/urology/patients/{patient_id}", payload, headers
        )

    def get_patient(self, patient_id, headers):
        return self._request(
            "GET", f"/urology/patients/{patient_id}", None, headers
        )

    def list_patients(self, headers, **filters):
        return self._request("GET", "/urology/patients", _clean(filters), headers)

    # ─── Procedure rooms ───────────────────────────────────────────────────
    def create_procedure_room(self, payload, headers):
        return self._request("POST", "/urology/procedure-rooms", payload, headers)

    def update_procedure_room(self, room_id, payload, headers):
        return self._request(
            "PATCH", f"/urology/procedure-rooms/{room_id}", payload, headers
        )

    def get_procedure_room(self, room_id, headers):
        return self._request(
            "GET", f"/urology/procedure-rooms/{room_id}", None, headers
        )

    def list_procedure_rooms(self, headers, **filters):
        return self._request(
            "GET", "/urology/procedure-rooms", _clean(filters), headers
        )

    # ─── Procedure types ───────────────────────────────────────────────────
    def create_procedure_type(self, payload, headers):
        return self._request("POST", "/urology/procedure-types", payload, headers)

    def get_procedure_type(self, procedure_type_id, headers):
        return self._request(
            "GET", f"/urology/procedure-types/{procedure_type_id}", None, headers
        )

    def list_procedure_types(self, headers, **filters):
        return self._request(
            "GET", "/urology/procedure-types", _clean(filters), headers
        )

    # ─── Scope assets ──────────────────────────────────────────────────────
    def create_scope_asset(self, payload, headers):
        return self._request("POST", "/urology/scope-assets", payload, headers)

    def commission_scope_asset(self, scope_id, payload, headers):
        return self._request(
            "POST", f"/urology/scope-assets/{scope_id}/commissioning", payload, headers
        )

    def get_scope_asset(self, scope_id, headers):
        return self._request(
            "GET", f"/urology/scope-assets/{scope_id}", None, headers
        )

    def list_scope_assets(self, headers, **filters):
        return self._request(
            "GET", "/urology/scope-assets", _clean(filters), headers
        )

    # ─── Consignment lots ──────────────────────────────────────────────────
    def create_consignment_lot(self, payload, headers):
        return self._request("POST", "/urology/consignment-lots", payload, headers)

    def return_consignment_lot(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/urology/consignment-lots/{lot_id}/return", payload, headers
        )

    def get_consignment_lot(self, lot_id, headers):
        return self._request(
            "GET", f"/urology/consignment-lots/{lot_id}", None, headers
        )

    def list_consignment_lots(self, headers, **filters):
        return self._request(
            "GET", "/urology/consignment-lots", _clean(filters), headers
        )

    # ─── Procedure cases ───────────────────────────────────────────────────
    def create_procedure_case(self, payload, headers):
        return self._request("POST", "/urology/procedure-cases", payload, headers)

    def schedule_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/urology/procedure-cases/{case_id}/schedule", payload, headers
        )

    def reschedule_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/urology/procedure-cases/{case_id}/reschedule", payload, headers
        )

    def acknowledge_prep(self, case_id, payload, headers):
        return self._request(
            "POST",
            f"/urology/procedure-cases/{case_id}/prep-acknowledgements",
            payload,
            headers,
        )

    def review_clearance(self, case_id, payload, headers):
        return self._request(
            "POST",
            f"/urology/procedure-cases/{case_id}/clearance-review",
            payload,
            headers,
        )

    def assign_scope(self, case_id, payload, headers):
        return self._request(
            "POST",
            f"/urology/procedure-cases/{case_id}/scope-assignment",
            payload,
            headers,
        )

    def reserve_device(self, case_id, payload, headers):
        return self._request(
            "POST",
            f"/urology/procedure-cases/{case_id}/device-reservation",
            payload,
            headers,
        )

    def check_in_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/urology/procedure-cases/{case_id}/check-in", payload, headers
        )

    def complete_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/urology/procedure-cases/{case_id}/complete", payload, headers
        )

    def cancel_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/urology/procedure-cases/{case_id}/cancel", payload, headers
        )

    def no_show_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/urology/procedure-cases/{case_id}/no-show", payload, headers
        )

    def get_procedure_case(self, case_id, headers):
        return self._request(
            "GET", f"/urology/procedure-cases/{case_id}", None, headers
        )

    def get_case_readiness(self, case_id, headers):
        return self._request(
            "GET", f"/urology/procedure-cases/{case_id}/readiness", None, headers
        )

    def list_procedure_cases(self, headers, **filters):
        return self._request(
            "GET", "/urology/procedure-cases", _clean(filters), headers
        )

    # ─── Antibiotic orders ─────────────────────────────────────────────────
    def create_antibiotic_order(self, payload, headers):
        return self._request("POST", "/urology/antibiotic-orders", payload, headers)

    def administer_antibiotic_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/urology/antibiotic-orders/{order_id}/administer", payload, headers
        )

    def get_antibiotic_order(self, order_id, headers):
        return self._request(
            "GET", f"/urology/antibiotic-orders/{order_id}", None, headers
        )

    def list_antibiotic_orders(self, headers, **filters):
        return self._request(
            "GET", "/urology/antibiotic-orders", _clean(filters), headers
        )

    # ─── Reprocessing logs ─────────────────────────────────────────────────
    def create_reprocessing_log(self, payload, headers):
        return self._request("POST", "/urology/reprocessing-logs", payload, headers)

    def complete_reprocessing_log(self, log_id, payload, headers):
        return self._request(
            "POST", f"/urology/reprocessing-logs/{log_id}/complete", payload, headers
        )

    def get_reprocessing_log(self, log_id, headers):
        return self._request(
            "GET", f"/urology/reprocessing-logs/{log_id}", None, headers
        )

    def list_reprocessing_logs(self, headers, **filters):
        return self._request(
            "GET", "/urology/reprocessing-logs", _clean(filters), headers
        )

    # ─── Specimens ─────────────────────────────────────────────────────────
    def create_specimen(self, payload, headers):
        return self._request("POST", "/urology/specimens", payload, headers)

    def accession_specimen(self, specimen_id, payload, headers):
        return self._request(
            "POST", f"/urology/specimens/{specimen_id}/accession", payload, headers
        )

    def result_specimen(self, specimen_id, payload, headers):
        return self._request(
            "POST", f"/urology/specimens/{specimen_id}/result", payload, headers
        )

    def record_notification_attempt(self, specimen_id, payload, headers):
        return self._request(
            "POST",
            f"/urology/specimens/{specimen_id}/notification-attempt",
            payload,
            headers,
        )

    def get_specimen(self, specimen_id, headers):
        return self._request("GET", f"/urology/specimens/{specimen_id}", None, headers)

    def list_specimens(self, headers, **filters):
        return self._request("GET", "/urology/specimens", _clean(filters), headers)

    # ─── Surveillance recalls ──────────────────────────────────────────────
    def create_surveillance_recall(self, payload, headers):
        return self._request(
            "POST", "/urology/surveillance-recalls", payload, headers
        )

    def close_surveillance_recall(self, recall_id, payload, headers):
        return self._request(
            "POST", f"/urology/surveillance-recalls/{recall_id}/close", payload, headers
        )

    def run_recall_sweep(self, payload, headers):
        return self._request("POST", "/urology/recall-sweeps", payload, headers)

    def get_surveillance_recall(self, recall_id, headers):
        return self._request(
            "GET", f"/urology/surveillance-recalls/{recall_id}", None, headers
        )

    def list_surveillance_recalls(self, headers, **filters):
        return self._request(
            "GET", "/urology/surveillance-recalls", _clean(filters), headers
        )

    # ─── Pelvic health referrals ───────────────────────────────────────────
    def create_pelvic_health_referral(self, payload, headers):
        return self._request(
            "POST", "/urology/pelvic-health-referrals", payload, headers
        )

    def decide_pelvic_health_referral(self, referral_id, payload, headers):
        return self._request(
            "POST",
            f"/urology/pelvic-health-referrals/{referral_id}/decision",
            payload,
            headers,
        )

    def log_referral_visit(self, referral_id, payload, headers):
        return self._request(
            "POST",
            f"/urology/pelvic-health-referrals/{referral_id}/visits",
            payload,
            headers,
        )

    def get_pelvic_health_referral(self, referral_id, headers):
        return self._request(
            "GET", f"/urology/pelvic-health-referrals/{referral_id}", None, headers
        )

    def list_pelvic_health_referrals(self, headers, **filters):
        return self._request(
            "GET", "/urology/pelvic-health-referrals", _clean(filters), headers
        )

    # ─── Logical clock ─────────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST",
            "/urology/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )
