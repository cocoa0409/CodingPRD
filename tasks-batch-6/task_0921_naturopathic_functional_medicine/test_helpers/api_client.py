"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- clock
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # -------------------------------------------------------- practitioners
    def create_practitioner(self, payload, headers):
        return self._request("POST", "/practitioners", payload, headers)

    def get_practitioner(self, practitioner_id, headers):
        return self._request(
            "GET", f"/practitioners/{practitioner_id}", headers=headers
        )

    # ------------------------------------------------------------- patients
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    def get_patient_gate(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}/gate", headers=headers)

    def open_scope_review(self, patient_id, payload, headers):
        return self._request(
            "POST", f"/patients/{patient_id}/scope-reviews", payload, headers
        )

    def close_scope_review(self, patient_id, payload, headers):
        return self._request(
            "POST", f"/patients/{patient_id}/scope-reviews/close", payload, headers
        )

    # ------------------------------------------------------ intake sections
    def create_intake_section(self, patient_id, payload, headers):
        return self._request(
            "POST", f"/patients/{patient_id}/intake-sections", payload, headers
        )

    def list_intake_sections(self, patient_id, headers, params=None):
        return self._request(
            "GET", f"/patients/{patient_id}/intake-sections", headers=headers,
            params=params,
        )

    def attest_intake_section(self, section_id, headers, payload=None):
        return self._request(
            "POST", f"/intake-sections/{section_id}/attest", payload or {}, headers
        )

    # ---------------------------------------------------------- memberships
    def create_membership(self, payload, headers):
        return self._request("POST", "/memberships", payload, headers)

    def list_memberships(self, patient_id, headers, params=None):
        return self._request(
            "GET", f"/patients/{patient_id}/memberships", headers=headers, params=params
        )

    def pause_membership(self, membership_id, headers, payload=None):
        return self._request(
            "POST", f"/memberships/{membership_id}/pause", payload or {}, headers
        )

    def resume_membership(self, membership_id, headers, payload=None):
        return self._request(
            "POST", f"/memberships/{membership_id}/resume", payload or {}, headers
        )

    def change_membership_tier(self, membership_id, payload, headers):
        return self._request(
            "PATCH", f"/memberships/{membership_id}/tier", payload, headers
        )

    def roll_membership_cycle(self, membership_id, payload, headers):
        return self._request(
            "POST", f"/memberships/{membership_id}/roll-cycle", payload, headers
        )

    # ----------------------------------------------------------- lab orders
    def create_lab_order(self, payload, headers):
        return self._request("POST", "/lab-orders", payload, headers)

    def get_lab_order(self, lab_order_id, headers):
        return self._request("GET", f"/lab-orders/{lab_order_id}", headers=headers)

    def list_lab_orders(self, headers, params=None):
        return self._request("GET", "/lab-orders", headers=headers, params=params)

    def collect_lab_order(self, lab_order_id, headers, payload=None):
        return self._request(
            "POST", f"/lab-orders/{lab_order_id}/collect", payload or {}, headers
        )

    def create_lab_result(self, lab_order_id, payload, headers):
        return self._request(
            "POST", f"/lab-orders/{lab_order_id}/results", payload, headers
        )

    def list_lab_results(self, lab_order_id, headers, params=None):
        return self._request(
            "GET", f"/lab-orders/{lab_order_id}/results", headers=headers, params=params
        )

    def interpret_lab_order(self, lab_order_id, payload, headers):
        return self._request(
            "POST", f"/lab-orders/{lab_order_id}/interpret", payload, headers
        )

    def release_washout_hold(self, lab_order_id, headers, payload=None):
        return self._request(
            "POST",
            f"/lab-orders/{lab_order_id}/release-washout-hold",
            payload or {},
            headers,
        )

    def cancel_lab_order(self, lab_order_id, payload, headers):
        return self._request(
            "POST", f"/lab-orders/{lab_order_id}/cancel", payload, headers
        )

    # ------------------------------------------------------------ protocols
    def create_protocol(self, payload, headers):
        return self._request("POST", "/protocols", payload, headers)

    def get_protocol(self, protocol_id, headers):
        return self._request("GET", f"/protocols/{protocol_id}", headers=headers)

    def list_protocols(self, headers, params=None):
        return self._request("GET", "/protocols", headers=headers, params=params)

    def create_protocol_item(self, protocol_id, payload, headers):
        return self._request(
            "POST", f"/protocols/{protocol_id}/items", payload, headers
        )

    def issue_protocol(self, protocol_id, headers, payload=None):
        return self._request(
            "POST", f"/protocols/{protocol_id}/issue", payload or {}, headers
        )

    def activate_protocol(self, protocol_id, headers, payload=None):
        return self._request(
            "POST", f"/protocols/{protocol_id}/activate", payload or {}, headers
        )

    def complete_protocol(self, protocol_id, headers, payload=None):
        return self._request(
            "POST", f"/protocols/{protocol_id}/complete", payload or {}, headers
        )

    def discontinue_protocol(self, protocol_id, payload, headers):
        return self._request(
            "POST", f"/protocols/{protocol_id}/discontinue", payload, headers
        )

    # ------------------------------------------------------- protocol items
    def get_protocol_item(self, item_id, headers):
        return self._request("GET", f"/protocol-items/{item_id}", headers=headers)

    def list_protocol_items(self, headers, params=None):
        return self._request("GET", "/protocol-items", headers=headers, params=params)

    def create_titration_decision(self, item_id, payload, headers):
        return self._request(
            "POST", f"/protocol-items/{item_id}/titration-decisions", payload, headers
        )

    def create_adverse_reaction(self, item_id, payload, headers):
        return self._request(
            "POST", f"/protocol-items/{item_id}/adverse-reactions", payload, headers
        )

    # ------------------------------------------------------------ dispensary
    def create_dispensary_product(self, payload, headers):
        return self._request("POST", "/dispensary-products", payload, headers)

    def get_dispensary_product(self, product_id, headers):
        return self._request(
            "GET", f"/dispensary-products/{product_id}", headers=headers
        )

    def create_product_lot(self, product_id, payload, headers):
        return self._request(
            "POST", f"/dispensary-products/{product_id}/lots", payload, headers
        )

    def get_product_lot(self, lot_id, headers):
        return self._request("GET", f"/product-lots/{lot_id}", headers=headers)

    def list_product_lots(self, headers, params=None):
        return self._request("GET", "/product-lots", headers=headers, params=params)

    def create_dispense(self, payload, headers):
        return self._request("POST", "/dispenses", payload, headers)

    def get_dispense(self, dispense_id, headers):
        return self._request("GET", f"/dispenses/{dispense_id}", headers=headers)

    def list_dispenses(self, headers, params=None):
        return self._request("GET", "/dispenses", headers=headers, params=params)

    def reverse_dispense(self, dispense_id, payload, headers):
        return self._request(
            "POST", f"/dispenses/{dispense_id}/reverse", payload, headers
        )

    # ----------------------------------------------------------- encounters
    def create_encounter(self, payload, headers):
        return self._request("POST", "/encounters", payload, headers)

    def get_encounter(self, encounter_id, headers):
        return self._request("GET", f"/encounters/{encounter_id}", headers=headers)

    def list_encounters(self, headers, params=None):
        return self._request("GET", "/encounters", headers=headers, params=params)

    def complete_encounter(self, encounter_id, payload, headers):
        return self._request(
            "POST", f"/encounters/{encounter_id}/complete", payload, headers
        )

    def cancel_encounter(self, encounter_id, payload, headers):
        return self._request(
            "POST", f"/encounters/{encounter_id}/cancel", payload, headers
        )

    def no_show_encounter(self, encounter_id, headers, payload=None):
        return self._request(
            "POST", f"/encounters/{encounter_id}/no-show", payload or {}, headers
        )

    # ------------------------------------------------------ message threads
    def create_message_thread(self, payload, headers):
        return self._request("POST", "/message-threads", payload, headers)

    def get_message_thread(self, thread_id, headers):
        return self._request("GET", f"/message-threads/{thread_id}", headers=headers)

    def list_message_threads(self, headers, params=None):
        return self._request("GET", "/message-threads", headers=headers, params=params)

    def create_message(self, thread_id, payload, headers):
        return self._request(
            "POST", f"/message-threads/{thread_id}/messages", payload, headers
        )

    def convert_thread_to_evisit(self, thread_id, headers, payload=None):
        return self._request(
            "POST",
            f"/message-threads/{thread_id}/convert-to-evisit",
            payload or {},
            headers,
        )

    def close_message_thread(self, thread_id, headers, payload=None):
        return self._request(
            "POST", f"/message-threads/{thread_id}/close", payload or {}, headers
        )

    # ------------------------------------------------------------ superbills
    def create_superbill(self, payload, headers):
        return self._request("POST", "/superbills", payload, headers)

    def get_superbill(self, superbill_id, headers):
        return self._request("GET", f"/superbills/{superbill_id}", headers=headers)

    def list_superbills(self, headers, params=None):
        return self._request("GET", "/superbills", headers=headers, params=params)

    def create_superbill_transition(self, superbill_id, payload, headers):
        return self._request(
            "POST", f"/superbills/{superbill_id}/transitions", payload, headers
        )

    # ------------------------------------------------------------- referrals
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def create_referral_transition(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/referrals/{referral_id}/transitions", payload, headers
        )


api_client = ApiClient()
