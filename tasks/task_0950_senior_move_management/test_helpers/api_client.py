"""API client: one method per endpoint in the Senior Move Management API."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock -----------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- clients -----------------------------------------------------------
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    # --- engagements -------------------------------------------------------
    def create_engagement(self, payload, headers):
        return self._request("POST", "/engagements", payload, headers)

    def list_engagements(self, headers, params=None):
        return self._request("GET", "/engagements", headers=headers, params=params)

    def get_engagement(self, engagement_id, headers):
        return self._request("GET", f"/engagements/{engagement_id}", headers=headers)

    def patch_engagement(self, engagement_id, payload, headers):
        return self._request(
            "PATCH", f"/engagements/{engagement_id}", payload, headers
        )

    def hold_engagement(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/hold", payload, headers
        )

    def resume_engagement(self, engagement_id, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/resume", {}, headers
        )

    def cancel_engagement(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/cancel", payload, headers
        )

    def close_out_engagement(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/close-out", payload, headers
        )

    def ops_run(self, engagement_id, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/ops-run", {}, headers
        )

    def get_engagement_summary(self, engagement_id, headers):
        return self._request(
            "GET", f"/engagements/{engagement_id}/summary", headers=headers
        )

    # --- portal parties ----------------------------------------------------
    def create_portal_party(self, payload, headers):
        return self._request("POST", "/portal-parties", payload, headers)

    def list_portal_parties(self, headers, params=None):
        return self._request("GET", "/portal-parties", headers=headers, params=params)

    def get_portal_party(self, party_id, headers):
        return self._request("GET", f"/portal-parties/{party_id}", headers=headers)

    # --- authority records -------------------------------------------------
    def create_authority_record(self, payload, headers):
        return self._request("POST", "/authority-records", payload, headers)

    def list_authority_records(self, headers, params=None):
        return self._request(
            "GET", "/authority-records", headers=headers, params=params
        )

    def get_authority_record(self, authority_id, headers):
        return self._request(
            "GET", f"/authority-records/{authority_id}", headers=headers
        )

    def activate_authority_record(self, authority_id, headers):
        return self._request(
            "POST", f"/authority-records/{authority_id}/activate", {}, headers
        )

    def suspend_authority_record(self, authority_id, payload, headers):
        return self._request(
            "POST", f"/authority-records/{authority_id}/suspend", payload, headers
        )

    def reinstate_authority_record(self, authority_id, headers):
        return self._request(
            "POST", f"/authority-records/{authority_id}/reinstate", {}, headers
        )

    def revoke_authority_record(self, authority_id, payload, headers):
        return self._request(
            "POST", f"/authority-records/{authority_id}/revoke", payload, headers
        )

    # --- destination residences -------------------------------------------
    def create_destination_residence(self, payload, headers):
        return self._request("POST", "/destination-residences", payload, headers)

    def list_destination_residences(self, headers, params=None):
        return self._request(
            "GET", "/destination-residences", headers=headers, params=params
        )

    def get_destination_residence(self, residence_id, headers):
        return self._request(
            "GET", f"/destination-residences/{residence_id}", headers=headers
        )

    def propose_placement(self, residence_id, headers):
        return self._request(
            "POST",
            f"/destination-residences/{residence_id}/propose-placement",
            {},
            headers,
        )

    def approve_placement(self, residence_id, payload, headers):
        return self._request(
            "POST",
            f"/destination-residences/{residence_id}/approve-placement",
            payload,
            headers,
        )

    def revise_placement(self, residence_id, payload, headers):
        return self._request(
            "POST",
            f"/destination-residences/{residence_id}/revise-placement",
            payload,
            headers,
        )

    # --- destination rooms -------------------------------------------------
    def create_destination_room(self, payload, headers):
        return self._request("POST", "/destination-rooms", payload, headers)

    def list_destination_rooms(self, headers, params=None):
        return self._request(
            "GET", "/destination-rooms", headers=headers, params=params
        )

    def get_destination_room(self, room_id, headers):
        return self._request("GET", f"/destination-rooms/{room_id}", headers=headers)

    # --- inventory items ---------------------------------------------------
    def create_inventory_item(self, payload, headers):
        return self._request("POST", "/inventory-items", payload, headers)

    def list_inventory_items(self, headers, params=None):
        return self._request("GET", "/inventory-items", headers=headers, params=params)

    def get_inventory_item(self, item_id, headers):
        return self._request("GET", f"/inventory-items/{item_id}", headers=headers)

    def designate_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"/inventory-items/{item_id}/designate", payload, headers
        )

    def appraise_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"/inventory-items/{item_id}/appraise", payload, headers
        )

    def advance_handling(self, item_id, payload, headers):
        return self._request(
            "POST", f"/inventory-items/{item_id}/advance-handling", payload, headers
        )

    # --- family holds ------------------------------------------------------
    def create_family_hold(self, payload, headers):
        return self._request("POST", "/family-holds", payload, headers)

    def list_family_holds(self, headers, params=None):
        return self._request("GET", "/family-holds", headers=headers, params=params)

    def get_family_hold(self, hold_id, headers):
        return self._request("GET", f"/family-holds/{hold_id}", headers=headers)

    def escalate_family_hold(self, hold_id, payload, headers):
        return self._request(
            "POST", f"/family-holds/{hold_id}/escalate", payload, headers
        )

    def remand_family_hold(self, hold_id, payload, headers):
        return self._request(
            "POST", f"/family-holds/{hold_id}/remand", payload, headers
        )

    def resolve_family_hold(self, hold_id, payload, headers):
        return self._request(
            "POST", f"/family-holds/{hold_id}/resolve", payload, headers
        )

    def withdraw_family_hold(self, hold_id, headers):
        return self._request("POST", f"/family-holds/{hold_id}/withdraw", {}, headers)

    # --- sort plans --------------------------------------------------------
    def create_sort_plan(self, payload, headers):
        return self._request("POST", "/sort-plans", payload, headers)

    def list_sort_plans(self, headers, params=None):
        return self._request("GET", "/sort-plans", headers=headers, params=params)

    def get_sort_plan(self, plan_id, headers):
        return self._request("GET", f"/sort-plans/{plan_id}", headers=headers)

    def submit_sort_plan(self, plan_id, headers):
        return self._request("POST", f"/sort-plans/{plan_id}/submit", {}, headers)

    def approve_sort_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/sort-plans/{plan_id}/approve", payload, headers
        )

    def reject_sort_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/sort-plans/{plan_id}/reject", payload, headers)

    def reopen_sort_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/sort-plans/{plan_id}/reopen", payload, headers)

    # --- move-day plans ----------------------------------------------------
    def create_move_day_plan(self, payload, headers):
        return self._request("POST", "/move-day-plans", payload, headers)

    def list_move_day_plans(self, headers, params=None):
        return self._request("GET", "/move-day-plans", headers=headers, params=params)

    def get_move_day_plan(self, plan_id, headers):
        return self._request("GET", f"/move-day-plans/{plan_id}", headers=headers)

    def confirm_move_day_plan(self, plan_id, headers):
        return self._request("POST", f"/move-day-plans/{plan_id}/confirm", {}, headers)

    def recrew_move_day_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/move-day-plans/{plan_id}/recrew", payload, headers
        )

    def freeze_move_day_plan(self, plan_id, headers):
        return self._request("POST", f"/move-day-plans/{plan_id}/freeze", {}, headers)

    def start_move_day_plan(self, plan_id, headers):
        return self._request("POST", f"/move-day-plans/{plan_id}/start", {}, headers)

    def complete_move_day_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/move-day-plans/{plan_id}/complete", payload, headers
        )

    def reschedule_move_day_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/move-day-plans/{plan_id}/reschedule", payload, headers
        )

    # --- crew --------------------------------------------------------------
    def create_crew_member(self, payload, headers):
        return self._request("POST", "/crew-members", payload, headers)

    def get_crew_member(self, crew_member_id, headers):
        return self._request("GET", f"/crew-members/{crew_member_id}", headers=headers)

    def create_crew_assignment(self, payload, headers):
        return self._request("POST", "/crew-assignments", payload, headers)

    def list_crew_assignments(self, headers, params=None):
        return self._request("GET", "/crew-assignments", headers=headers, params=params)

    def get_crew_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/crew-assignments/{assignment_id}", headers=headers
        )

    def confirm_crew_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/crew-assignments/{assignment_id}/confirm", {}, headers
        )

    def check_in_crew_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/crew-assignments/{assignment_id}/check-in", payload, headers
        )

    def check_out_crew_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/crew-assignments/{assignment_id}/check-out", payload, headers
        )

    def no_show_crew_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/crew-assignments/{assignment_id}/no-show", payload, headers
        )

    # --- time entries ------------------------------------------------------
    def create_time_entry(self, payload, headers):
        return self._request("POST", "/time-entries", payload, headers)

    def list_time_entries(self, headers, params=None):
        return self._request("GET", "/time-entries", headers=headers, params=params)

    def get_time_entry(self, entry_id, headers):
        return self._request("GET", f"/time-entries/{entry_id}", headers=headers)

    def void_time_entry(self, entry_id, payload, headers):
        return self._request(
            "POST", f"/time-entries/{entry_id}/void", payload, headers
        )

    # --- vendors -----------------------------------------------------------
    def create_vendor(self, payload, headers):
        return self._request("POST", "/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    def renew_vendor_coi(self, vendor_id, payload, headers):
        return self._request(
            "POST", f"/vendors/{vendor_id}/renew-coi", payload, headers
        )

    # --- vendor assignments ------------------------------------------------
    def create_vendor_assignment(self, payload, headers):
        return self._request("POST", "/vendor-assignments", payload, headers)

    def list_vendor_assignments(self, headers, params=None):
        return self._request(
            "GET", "/vendor-assignments", headers=headers, params=params
        )

    def get_vendor_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/vendor-assignments/{assignment_id}", headers=headers
        )

    def accept_vendor_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/vendor-assignments/{assignment_id}/accept", {}, headers
        )

    def schedule_vendor_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/vendor-assignments/{assignment_id}/schedule", {}, headers
        )

    def perform_vendor_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/vendor-assignments/{assignment_id}/perform", payload, headers
        )

    def sign_off_vendor_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/vendor-assignments/{assignment_id}/sign-off", payload, headers
        )

    def pay_vendor_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/vendor-assignments/{assignment_id}/pay", {}, headers
        )

    def cancel_vendor_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/vendor-assignments/{assignment_id}/cancel", payload, headers
        )

    # --- consignment lots --------------------------------------------------
    def create_consignment_lot(self, payload, headers):
        return self._request("POST", "/consignment-lots", payload, headers)

    def list_consignment_lots(self, headers, params=None):
        return self._request(
            "GET", "/consignment-lots", headers=headers, params=params
        )

    def get_consignment_lot(self, lot_id, headers):
        return self._request("GET", f"/consignment-lots/{lot_id}", headers=headers)

    def mark_down_lot(self, lot_id, headers):
        return self._request(
            "POST", f"/consignment-lots/{lot_id}/mark-down", {}, headers
        )

    def record_lot_sale(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/consignment-lots/{lot_id}/record-sale", payload, headers
        )

    def settle_lot(self, lot_id, headers):
        return self._request("POST", f"/consignment-lots/{lot_id}/settle", {}, headers)

    def declare_lot_unsold(self, lot_id, headers):
        return self._request(
            "POST", f"/consignment-lots/{lot_id}/declare-unsold", {}, headers
        )

    def return_lot_to_client(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/consignment-lots/{lot_id}/return-to-client", payload, headers
        )

    def haul_away_lot(self, lot_id, headers):
        return self._request(
            "POST", f"/consignment-lots/{lot_id}/haul-away", {}, headers
        )

    # --- invoices ----------------------------------------------------------
    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/issue", {}, headers)

    def recall_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/invoices/{invoice_id}/recall", payload, headers
        )

    def dispute_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/invoices/{invoice_id}/dispute", payload, headers
        )

    def resolve_invoice_dispute(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/invoices/{invoice_id}/resolve-dispute", payload, headers
        )

    def finalize_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/finalize", {}, headers)

    def record_payment(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/invoices/{invoice_id}/record-payment", payload, headers
        )

    # --- invoice lines -----------------------------------------------------
    def create_invoice_line(self, payload, headers):
        return self._request("POST", "/invoice-lines", payload, headers)

    def list_invoice_lines(self, headers, params=None):
        return self._request("GET", "/invoice-lines", headers=headers, params=params)

    def get_invoice_line(self, line_id, headers):
        return self._request("GET", f"/invoice-lines/{line_id}", headers=headers)

    # --- milestones --------------------------------------------------------
    def list_milestones(self, headers, params=None):
        return self._request("GET", "/milestones", headers=headers, params=params)

    def get_milestone(self, milestone_id, headers):
        return self._request("GET", f"/milestones/{milestone_id}", headers=headers)

    def complete_milestone(self, milestone_id, payload, headers):
        return self._request(
            "POST", f"/milestones/{milestone_id}/complete", payload, headers
        )

    def reopen_milestone(self, milestone_id, payload, headers):
        return self._request(
            "POST", f"/milestones/{milestone_id}/reopen", payload, headers
        )

    # --- unpack sessions ---------------------------------------------------
    def create_unpack_session(self, payload, headers):
        return self._request("POST", "/unpack-sessions", payload, headers)

    def list_unpack_sessions(self, headers, params=None):
        return self._request("GET", "/unpack-sessions", headers=headers, params=params)

    def get_unpack_session(self, session_id, headers):
        return self._request("GET", f"/unpack-sessions/{session_id}", headers=headers)

    def start_unpack_session(self, session_id, headers):
        return self._request(
            "POST", f"/unpack-sessions/{session_id}/start", {}, headers
        )

    def complete_unpack_session(self, session_id, headers):
        return self._request(
            "POST", f"/unpack-sessions/{session_id}/complete", {}, headers
        )

    # --- punch list --------------------------------------------------------
    def create_punch_list_item(self, payload, headers):
        return self._request("POST", "/punch-list-items", payload, headers)

    def list_punch_list_items(self, headers, params=None):
        return self._request(
            "GET", "/punch-list-items", headers=headers, params=params
        )

    def get_punch_list_item(self, item_id, headers):
        return self._request("GET", f"/punch-list-items/{item_id}", headers=headers)

    def resolve_punch_list_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"/punch-list-items/{item_id}/resolve", payload, headers
        )

    def reopen_punch_list_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"/punch-list-items/{item_id}/reopen", payload, headers
        )

    # --- raw escape hatch for header-shape probes --------------------------
    def raw(self, method, path, payload=None, headers=None, params=None):
        return self._request(method, path, payload, headers, params)


api_client = ApiClient()
