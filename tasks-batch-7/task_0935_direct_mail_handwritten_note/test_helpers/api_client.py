"""API client: one method per endpoint described in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ---------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Accounts and the permit escrow ---------------------------------
    def create_account(self, payload, headers):
        return self._request("POST", "/mail/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/mail/accounts/{account_id}", headers=headers)

    def create_postage_topup(self, account_id, payload, headers):
        return self._request(
            "POST", f"/mail/accounts/{account_id}/postage-topups", payload, headers
        )

    # ---- Blackout calendar ----------------------------------------------
    def create_blackout_date(self, payload, headers):
        return self._request("POST", "/mail/blackout-dates", payload, headers)

    def list_blackout_dates(self, headers, params=None):
        return self._request("GET", "/mail/blackout-dates", headers=headers, params=params)

    # ---- Handwriting styles ---------------------------------------------
    def create_handwriting_style(self, payload, headers):
        return self._request("POST", "/mail/handwriting-styles", payload, headers)

    # ---- Writing machines ------------------------------------------------
    def create_machine(self, payload, headers):
        return self._request("POST", "/mail/machines", payload, headers)

    def get_machine(self, machine_id, headers):
        return self._request("GET", f"/mail/machines/{machine_id}", headers=headers)

    # ---- Ink lots --------------------------------------------------------
    def create_ink_lot(self, payload, headers):
        return self._request("POST", "/mail/ink-lots", payload, headers)

    def get_ink_lot(self, ink_lot_id, headers):
        return self._request("GET", f"/mail/ink-lots/{ink_lot_id}", headers=headers)

    def quarantine_ink_lot(self, ink_lot_id, payload, headers):
        return self._request(
            "POST", f"/mail/ink-lots/{ink_lot_id}/quarantine", payload, headers
        )

    def release_ink_lot(self, ink_lot_id, headers):
        return self._request("POST", f"/mail/ink-lots/{ink_lot_id}/release", {}, headers)

    # ---- Campaigns -------------------------------------------------------
    def create_campaign(self, payload, headers):
        return self._request("POST", "/mail/campaigns", payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/mail/campaigns/{campaign_id}", headers=headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/mail/campaigns", headers=headers, params=params)

    def activate_campaign(self, campaign_id, headers):
        return self._request("POST", f"/mail/campaigns/{campaign_id}/activate", {}, headers)

    def pause_campaign(self, campaign_id, headers):
        return self._request("POST", f"/mail/campaigns/{campaign_id}/pause", {}, headers)

    def create_compliance_hold(self, campaign_id, payload, headers):
        return self._request(
            "POST", f"/mail/campaigns/{campaign_id}/compliance-holds", payload, headers
        )

    def create_compliance_release(self, campaign_id, headers):
        return self._request(
            "POST", f"/mail/campaigns/{campaign_id}/compliance-releases", {}, headers
        )

    def billing_close_campaign(self, campaign_id, headers):
        return self._request(
            "POST", f"/mail/campaigns/{campaign_id}/billing-close", {}, headers
        )

    def get_postage_reconciliation(self, campaign_id, headers):
        return self._request(
            "GET", f"/mail/campaigns/{campaign_id}/postage-reconciliation", headers=headers
        )

    def get_deliverability_report(self, campaign_id, headers):
        return self._request(
            "GET", f"/mail/campaigns/{campaign_id}/deliverability-report", headers=headers
        )

    # ---- Templates -------------------------------------------------------
    def create_template(self, payload, headers):
        return self._request("POST", "/mail/templates", payload, headers)

    def get_template(self, template_id, headers):
        return self._request("GET", f"/mail/templates/{template_id}", headers=headers)

    def list_templates(self, headers, params=None):
        return self._request("GET", "/mail/templates", headers=headers, params=params)

    def patch_template(self, template_id, payload, headers):
        return self._request("PATCH", f"/mail/templates/{template_id}", payload, headers)

    # ---- Mailing lists ---------------------------------------------------
    def create_mailing_list(self, payload, headers):
        return self._request("POST", "/mail/mailing-lists", payload, headers)

    def get_mailing_list(self, mailing_list_id, headers):
        return self._request(
            "GET", f"/mail/mailing-lists/{mailing_list_id}", headers=headers
        )

    def list_mailing_lists(self, headers, params=None):
        return self._request("GET", "/mail/mailing-lists", headers=headers, params=params)

    def create_list_record(self, mailing_list_id, payload, headers):
        return self._request(
            "POST", f"/mail/mailing-lists/{mailing_list_id}/records", payload, headers
        )

    def create_cass_run(self, mailing_list_id, headers):
        return self._request(
            "POST", f"/mail/mailing-lists/{mailing_list_id}/cass-runs", {}, headers
        )

    def create_dedupe_run(self, mailing_list_id, payload, headers):
        return self._request(
            "POST", f"/mail/mailing-lists/{mailing_list_id}/dedupe-runs", payload, headers
        )

    def lock_mailing_list(self, mailing_list_id, headers):
        return self._request(
            "POST", f"/mail/mailing-lists/{mailing_list_id}/lock", {}, headers
        )

    # ---- Recipient records ----------------------------------------------
    def get_list_record(self, list_record_id, headers):
        return self._request("GET", f"/mail/list-records/{list_record_id}", headers=headers)

    def list_list_records(self, headers, params=None):
        return self._request("GET", "/mail/list-records", headers=headers, params=params)

    def create_ncoa_move(self, list_record_id, payload, headers):
        return self._request(
            "POST", f"/mail/list-records/{list_record_id}/ncoa-moves", payload, headers
        )

    def create_return(self, list_record_id, payload, headers):
        return self._request(
            "POST", f"/mail/list-records/{list_record_id}/returns", payload, headers
        )

    # ---- Mail jobs -------------------------------------------------------
    def create_mail_job(self, payload, headers):
        return self._request("POST", "/mail/mail-jobs", payload, headers)

    def get_mail_job(self, mail_job_id, headers):
        return self._request("GET", f"/mail/mail-jobs/{mail_job_id}", headers=headers)

    def list_mail_jobs(self, headers, params=None):
        return self._request("GET", "/mail/mail-jobs", headers=headers, params=params)

    def estimate_mail_job(self, mail_job_id, headers):
        return self._request("POST", f"/mail/mail-jobs/{mail_job_id}/estimate", {}, headers)

    def schedule_mail_job(self, mail_job_id, payload, headers):
        return self._request(
            "POST", f"/mail/mail-jobs/{mail_job_id}/schedule", payload, headers
        )

    def commit_mail_job(self, mail_job_id, headers):
        return self._request("POST", f"/mail/mail-jobs/{mail_job_id}/commit", {}, headers)

    def void_mail_job(self, mail_job_id, payload, headers):
        return self._request("POST", f"/mail/mail-jobs/{mail_job_id}/void", payload, headers)

    def mail_mail_job(self, mail_job_id, headers):
        return self._request("POST", f"/mail/mail-jobs/{mail_job_id}/mail", {}, headers)

    # ---- EDDM carrier routes --------------------------------------------
    def create_eddm_route(self, mail_job_id, payload, headers):
        return self._request(
            "POST", f"/mail/mail-jobs/{mail_job_id}/eddm-routes", payload, headers
        )

    def get_eddm_route(self, eddm_route_selection_id, headers):
        return self._request(
            "GET", f"/mail/eddm-routes/{eddm_route_selection_id}", headers=headers
        )

    def list_eddm_routes(self, headers, params=None):
        return self._request("GET", "/mail/eddm-routes", headers=headers, params=params)

    # ---- Proofs ----------------------------------------------------------
    def create_proof(self, payload, headers):
        return self._request("POST", "/mail/proofs", payload, headers)

    def get_proof(self, proof_id, headers):
        return self._request("GET", f"/mail/proofs/{proof_id}", headers=headers)

    def list_proofs(self, headers, params=None):
        return self._request("GET", "/mail/proofs", headers=headers, params=params)

    def submit_proof(self, proof_id, headers):
        return self._request("POST", f"/mail/proofs/{proof_id}/submit", {}, headers)

    def approve_proof(self, proof_id, payload, headers):
        return self._request("POST", f"/mail/proofs/{proof_id}/approve", payload, headers)

    def reject_proof(self, proof_id, payload, headers):
        return self._request("POST", f"/mail/proofs/{proof_id}/reject", payload, headers)

    # ---- Production runs -------------------------------------------------
    def create_production_run(self, mail_job_id, payload, headers):
        return self._request(
            "POST", f"/mail/mail-jobs/{mail_job_id}/production-runs", payload, headers
        )

    def get_production_run(self, production_run_id, headers):
        return self._request(
            "GET", f"/mail/production-runs/{production_run_id}", headers=headers
        )

    def list_production_runs(self, headers, params=None):
        return self._request("GET", "/mail/production-runs", headers=headers, params=params)

    def start_production_run(self, production_run_id, headers):
        return self._request(
            "POST", f"/mail/production-runs/{production_run_id}/start", {}, headers
        )

    def complete_production_run(self, production_run_id, headers):
        return self._request(
            "POST", f"/mail/production-runs/{production_run_id}/complete", {}, headers
        )

    def fail_production_run(self, production_run_id, payload, headers):
        return self._request(
            "POST", f"/mail/production-runs/{production_run_id}/fail", payload, headers
        )

    def void_production_run(self, production_run_id, payload, headers):
        return self._request(
            "POST", f"/mail/production-runs/{production_run_id}/void", payload, headers
        )

    # ---- Drip scheduling -------------------------------------------------
    def create_drip_schedule(self, payload, headers):
        return self._request("POST", "/mail/drip-schedules", payload, headers)

    def get_drip_schedule(self, drip_schedule_id, headers):
        return self._request(
            "GET", f"/mail/drip-schedules/{drip_schedule_id}", headers=headers
        )

    def list_drip_schedules(self, headers, params=None):
        return self._request("GET", "/mail/drip-schedules", headers=headers, params=params)

    def create_drip_step(self, drip_schedule_id, payload, headers):
        return self._request(
            "POST", f"/mail/drip-schedules/{drip_schedule_id}/steps", payload, headers
        )

    def get_drip_step(self, drip_step_id, headers):
        return self._request("GET", f"/mail/drip-steps/{drip_step_id}", headers=headers)

    def list_drip_steps(self, headers, params=None):
        return self._request("GET", "/mail/drip-steps", headers=headers, params=params)

    def release_drip_step(self, drip_step_id, headers):
        return self._request("POST", f"/mail/drip-steps/{drip_step_id}/release", {}, headers)

    # ---- Postage ledger --------------------------------------------------
    def get_postage_ledger_entry(self, postage_ledger_entry_id, headers):
        return self._request(
            "GET", f"/mail/postage-ledger-entries/{postage_ledger_entry_id}", headers=headers
        )

    def list_postage_ledger_entries(self, headers, params=None):
        return self._request(
            "GET", "/mail/postage-ledger-entries", headers=headers, params=params
        )

    # ---- Returns and reprints -------------------------------------------
    def get_return_event(self, return_event_id, headers):
        return self._request("GET", f"/mail/return-events/{return_event_id}", headers=headers)

    def list_return_events(self, headers, params=None):
        return self._request("GET", "/mail/return-events", headers=headers, params=params)

    def create_reprint_request(self, payload, headers):
        return self._request("POST", "/mail/reprint-requests", payload, headers)

    def get_reprint_request(self, reprint_request_id, headers):
        return self._request(
            "GET", f"/mail/reprint-requests/{reprint_request_id}", headers=headers
        )

    def list_reprint_requests(self, headers, params=None):
        return self._request("GET", "/mail/reprint-requests", headers=headers, params=params)

    def fulfill_reprint_request(self, reprint_request_id, headers):
        return self._request(
            "POST", f"/mail/reprint-requests/{reprint_request_id}/fulfill", {}, headers
        )

    def deny_reprint_request(self, reprint_request_id, payload, headers):
        return self._request(
            "POST", f"/mail/reprint-requests/{reprint_request_id}/deny", payload, headers
        )


api_client = ApiClient()
