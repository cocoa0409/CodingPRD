"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/toy-drive/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Campaign ---
    def create_campaign(self, payload, headers):
        return self._request("POST", "/toy-drive/campaigns", payload, headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/toy-drive/campaigns", headers=headers, params=params)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/toy-drive/campaigns/{campaign_id}", headers=headers)

    def patch_campaign(self, campaign_id, payload, headers):
        return self._request("PATCH", f"/toy-drive/campaigns/{campaign_id}", payload, headers)

    def open_intake(self, campaign_id, headers):
        return self._request("POST", f"/toy-drive/campaigns/{campaign_id}/open-intake",
                             {}, headers)

    def close_intake(self, campaign_id, headers):
        return self._request("POST", f"/toy-drive/campaigns/{campaign_id}/close-intake",
                             {}, headers)

    def advance_campaign(self, campaign_id, expected_campaign_version, headers):
        return self._request("POST", f"/toy-drive/campaigns/{campaign_id}/advance",
                             {"expected_campaign_version": expected_campaign_version}, headers)

    def close_campaign(self, campaign_id, headers):
        return self._request("POST", f"/toy-drive/campaigns/{campaign_id}/close", {}, headers)

    def backfill_select(self, campaign_id, limit, headers):
        return self._request("POST", f"/toy-drive/campaigns/{campaign_id}/backfill/select",
                             {"limit": limit}, headers)

    def generate_thank_you_notes(self, campaign_id, headers):
        return self._request(
            "POST", f"/toy-drive/campaigns/{campaign_id}/thank-you-notes/generate",
            {}, headers)

    # --- PartnerAgency ---
    def create_agency(self, payload, headers):
        return self._request("POST", "/toy-drive/agencies", payload, headers)

    def list_agencies(self, headers, params=None):
        return self._request("GET", "/toy-drive/agencies", headers=headers, params=params)

    def get_agency(self, agency_id, headers):
        return self._request("GET", f"/toy-drive/agencies/{agency_id}", headers=headers)

    def suspend_agency(self, agency_id, headers):
        return self._request("POST", f"/toy-drive/agencies/{agency_id}/suspend", {}, headers)

    def list_agency_families(self, agency_id, headers, params=None):
        return self._request("GET", f"/toy-drive/agencies/{agency_id}/families",
                             headers=headers, params=params)

    # --- Family ---
    def create_family(self, payload, headers):
        return self._request("POST", "/toy-drive/families", payload, headers)

    def list_families(self, headers, params=None):
        return self._request("GET", "/toy-drive/families", headers=headers, params=params)

    def get_family(self, family_id, headers):
        return self._request("GET", f"/toy-drive/families/{family_id}", headers=headers)

    def list_family_children(self, family_id, headers, params=None):
        return self._request("GET", f"/toy-drive/families/{family_id}/children",
                             headers=headers, params=params)

    def list_family_audit_events(self, family_id, headers, params=None):
        return self._request("GET", f"/toy-drive/families/{family_id}/audit-events",
                             headers=headers, params=params)

    def list_family_distribution_slots(self, family_id, headers, params=None):
        return self._request("GET", f"/toy-drive/families/{family_id}/distribution-slots",
                             headers=headers, params=params)

    def begin_review(self, family_id, headers):
        return self._request("POST", f"/toy-drive/families/{family_id}/begin-review",
                             {}, headers)

    def verify_family(self, family_id, headers, verification_note=None):
        payload = {}
        if verification_note is not None:
            payload["verification_note"] = verification_note
        return self._request("POST", f"/toy-drive/families/{family_id}/verify",
                             payload, headers)

    def reject_family(self, family_id, headers, verification_note=None):
        payload = {}
        if verification_note is not None:
            payload["verification_note"] = verification_note
        return self._request("POST", f"/toy-drive/families/{family_id}/reject",
                             payload, headers)

    def return_to_referral(self, family_id, headers, verification_note=None):
        payload = {}
        if verification_note is not None:
            payload["verification_note"] = verification_note
        return self._request("POST", f"/toy-drive/families/{family_id}/return-to-referral",
                             payload, headers)

    def withdraw_family(self, family_id, headers, verification_note=None):
        payload = {}
        if verification_note is not None:
            payload["verification_note"] = verification_note
        return self._request("POST", f"/toy-drive/families/{family_id}/withdraw",
                             payload, headers)

    # --- Child ---
    def create_child(self, family_id, payload, headers):
        return self._request("POST", f"/toy-drive/families/{family_id}/children",
                             payload, headers)

    def get_child(self, child_id, headers):
        return self._request("GET", f"/toy-drive/children/{child_id}", headers=headers)

    def list_child_gifts(self, child_id, headers, params=None):
        return self._request("GET", f"/toy-drive/children/{child_id}/gifts",
                             headers=headers, params=params)

    def list_child_wish_items(self, child_id, headers, params=None):
        return self._request("GET", f"/toy-drive/children/{child_id}/wish-items",
                             headers=headers, params=params)

    # --- WishItem ---
    def create_wish_item(self, child_id, payload, headers):
        return self._request("POST", f"/toy-drive/children/{child_id}/wish-items",
                             payload, headers)

    def get_wish_item(self, wish_item_id, headers):
        return self._request("GET", f"/toy-drive/wish-items/{wish_item_id}", headers=headers)

    def list_wish_item_gifts(self, wish_item_id, headers, params=None):
        return self._request("GET", f"/toy-drive/wish-items/{wish_item_id}/gifts",
                             headers=headers, params=params)

    def list_wish_item_backfill_purchases(self, wish_item_id, headers, params=None):
        return self._request("GET",
                             f"/toy-drive/wish-items/{wish_item_id}/backfill-purchases",
                             headers=headers, params=params)

    def approve_wish_item(self, wish_item_id, headers):
        return self._request("POST", f"/toy-drive/wish-items/{wish_item_id}/approve",
                             {}, headers)

    def reject_wish_item(self, wish_item_id, headers):
        return self._request("POST", f"/toy-drive/wish-items/{wish_item_id}/reject",
                             {}, headers)

    # --- Donor ---
    def create_donor(self, payload, headers):
        return self._request("POST", "/toy-drive/donors", payload, headers)

    def list_donors(self, headers, params=None):
        return self._request("GET", "/toy-drive/donors", headers=headers, params=params)

    def get_donor(self, donor_id, headers):
        return self._request("GET", f"/toy-drive/donors/{donor_id}", headers=headers)

    # --- Adoption ---
    def create_adoption(self, payload, headers):
        return self._request("POST", "/toy-drive/adoptions", payload, headers)

    def list_adoptions(self, headers, params=None):
        return self._request("GET", "/toy-drive/adoptions", headers=headers, params=params)

    def get_adoption(self, adoption_id, headers):
        return self._request("GET", f"/toy-drive/adoptions/{adoption_id}", headers=headers)

    def list_adoption_gifts(self, adoption_id, headers, params=None):
        return self._request("GET", f"/toy-drive/adoptions/{adoption_id}/gifts",
                             headers=headers, params=params)

    def confirm_adoption(self, adoption_id, headers):
        return self._request("POST", f"/toy-drive/adoptions/{adoption_id}/confirm",
                             {}, headers)

    def cancel_adoption(self, adoption_id, headers, reason=None):
        payload = {}
        if reason is not None:
            payload["reason"] = reason
        return self._request("POST", f"/toy-drive/adoptions/{adoption_id}/cancel",
                             payload, headers)

    def admin_cancel_adoption(self, adoption_id, reason, headers):
        return self._request("POST", f"/toy-drive/adoptions/{adoption_id}/admin-cancel",
                             {"reason": reason}, headers)

    # --- Gift ---
    def create_gift(self, payload, headers):
        return self._request("POST", "/toy-drive/gifts", payload, headers)

    def get_gift(self, gift_id, headers):
        return self._request("GET", f"/toy-drive/gifts/{gift_id}", headers=headers)

    def ship_gift(self, gift_id, headers):
        return self._request("POST", f"/toy-drive/gifts/{gift_id}/ship", {}, headers)

    def receive_gift(self, gift_id, headers, override_note=None):
        payload = {}
        if override_note is not None:
            payload["override_note"] = override_note
        return self._request("POST", f"/toy-drive/gifts/{gift_id}/receive",
                             payload, headers)

    def sort_gift(self, gift_id, headers):
        return self._request("POST", f"/toy-drive/gifts/{gift_id}/sort", {}, headers)

    def stage_gift(self, gift_id, slot_id, headers):
        return self._request("POST", f"/toy-drive/gifts/{gift_id}/stage",
                             {"slot_id": slot_id}, headers)

    # --- BackfillPurchase ---
    def list_backfill_purchases(self, headers, params=None):
        return self._request("GET", "/toy-drive/backfill-purchases",
                             headers=headers, params=params)

    def get_backfill_purchase(self, purchase_id, headers):
        return self._request("GET", f"/toy-drive/backfill-purchases/{purchase_id}",
                             headers=headers)

    def mark_purchased(self, purchase_id, final_cost_cents, headers):
        return self._request("POST",
                             f"/toy-drive/backfill-purchases/{purchase_id}/mark-purchased",
                             {"final_cost_cents": final_cost_cents}, headers)

    def cancel_backfill_purchase(self, purchase_id, headers):
        return self._request("POST",
                             f"/toy-drive/backfill-purchases/{purchase_id}/cancel",
                             {}, headers)

    def sort_backfill_purchase(self, purchase_id, headers):
        return self._request("POST",
                             f"/toy-drive/backfill-purchases/{purchase_id}/sort",
                             {}, headers)

    # --- DistributionEvent ---
    def create_distribution_event(self, payload, headers):
        return self._request("POST", "/toy-drive/distribution-events", payload, headers)

    def list_distribution_events(self, headers, params=None):
        return self._request("GET", "/toy-drive/distribution-events",
                             headers=headers, params=params)

    def get_distribution_event(self, event_id, headers):
        return self._request("GET", f"/toy-drive/distribution-events/{event_id}",
                             headers=headers)

    def list_event_slots(self, event_id, headers, params=None):
        return self._request("GET", f"/toy-drive/distribution-events/{event_id}/slots",
                             headers=headers, params=params)

    def open_slots(self, event_id, headers):
        return self._request("POST",
                             f"/toy-drive/distribution-events/{event_id}/open-slots",
                             {}, headers)

    def begin_sorting(self, event_id, headers):
        return self._request("POST",
                             f"/toy-drive/distribution-events/{event_id}/begin-sorting",
                             {}, headers)

    def lock_event(self, event_id, headers):
        return self._request("POST", f"/toy-drive/distribution-events/{event_id}/lock",
                             {}, headers)

    def complete_event(self, event_id, headers):
        return self._request("POST",
                             f"/toy-drive/distribution-events/{event_id}/complete",
                             {}, headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST",
                             f"/toy-drive/distribution-events/{event_id}/cancel",
                             {}, headers)

    # --- DistributionSlot ---
    def create_distribution_slot(self, payload, headers):
        return self._request("POST", "/toy-drive/distribution-slots", payload, headers)

    def get_distribution_slot(self, slot_id, headers):
        return self._request("GET", f"/toy-drive/distribution-slots/{slot_id}",
                             headers=headers)

    def list_slot_gifts(self, slot_id, headers, params=None):
        return self._request("GET", f"/toy-drive/distribution-slots/{slot_id}/gifts",
                             headers=headers, params=params)

    def check_in_slot(self, slot_id, headers):
        return self._request("POST",
                             f"/toy-drive/distribution-slots/{slot_id}/check-in",
                             {}, headers)

    def complete_slot(self, slot_id, headers):
        return self._request("POST",
                             f"/toy-drive/distribution-slots/{slot_id}/complete",
                             {}, headers)

    def cancel_slot(self, slot_id, headers):
        return self._request("POST",
                             f"/toy-drive/distribution-slots/{slot_id}/cancel",
                             {}, headers)

    # --- DuplicateFlag ---
    def list_duplicate_flags(self, headers, params=None):
        return self._request("GET", "/toy-drive/duplicate-flags",
                             headers=headers, params=params)

    def get_duplicate_flag(self, flag_id, headers):
        return self._request("GET", f"/toy-drive/duplicate-flags/{flag_id}",
                             headers=headers)

    def create_duplicate_flag(self, family_id, other_family_id, headers):
        return self._request("POST", "/toy-drive/duplicate-flags",
                             {"family_id": family_id, "other_family_id": other_family_id},
                             headers)

    def confirm_duplicate_flag(self, flag_id, headers, resolution_note=None):
        payload = {}
        if resolution_note is not None:
            payload["resolution_note"] = resolution_note
        return self._request("POST", f"/toy-drive/duplicate-flags/{flag_id}/confirm",
                             payload, headers)

    def dismiss_duplicate_flag(self, flag_id, headers, resolution_note=None):
        payload = {}
        if resolution_note is not None:
            payload["resolution_note"] = resolution_note
        return self._request("POST", f"/toy-drive/duplicate-flags/{flag_id}/dismiss",
                             payload, headers)

    # --- ThankYouNote ---
    def list_thank_you_notes(self, headers, params=None):
        return self._request("GET", "/toy-drive/thank-you-notes",
                             headers=headers, params=params)

    def get_thank_you_note(self, note_id, headers):
        return self._request("GET", f"/toy-drive/thank-you-notes/{note_id}",
                             headers=headers)

    def send_thank_you_note(self, note_id, headers):
        return self._request("POST", f"/toy-drive/thank-you-notes/{note_id}/send",
                             {}, headers)

    def cancel_thank_you_note(self, note_id, headers):
        return self._request("POST", f"/toy-drive/thank-you-notes/{note_id}/cancel",
                             {}, headers)

    def mark_thank_you_note_bounced(self, note_id, headers):
        return self._request("POST",
                             f"/toy-drive/thank-you-notes/{note_id}/mark-bounced",
                             {}, headers)

    # --- SeasonSettings singleton ---
    def get_season_settings(self, headers):
        return self._request("GET", "/toy-drive/season-settings", headers=headers)

    def update_season_settings(self, payload, headers):
        return self._request("PUT", "/toy-drive/season-settings", payload, headers)


api_client = ApiClient()
