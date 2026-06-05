"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Reference data ────────────────────────────────────────────────
    def create_transplant_center(self, payload, headers):
        return self._request("POST", "/transplant-centers", payload, headers)

    def get_transplant_center(self, center_id, headers):
        return self._request("GET", f"/transplant-centers/{center_id}", headers=headers)

    def create_opo(self, payload, headers):
        return self._request("POST", "/organ-procurement-orgs", payload, headers)

    def get_opo(self, opo_id, headers):
        return self._request("GET", f"/organ-procurement-orgs/{opo_id}", headers=headers)

    # ─── Candidate lifecycle ───────────────────────────────────────────
    def create_candidate(self, payload, headers):
        return self._request("POST", "/candidates", payload, headers)

    def list_candidates(self, headers, params=None):
        return self._request("GET", "/candidates", headers=headers, params=params)

    def get_candidate(self, candidate_id, headers):
        return self._request("GET", f"/candidates/{candidate_id}", headers=headers)

    def list_candidate(self, candidate_id, headers):
        return self._request("POST", f"/candidates/{candidate_id}/list", payload={}, headers=headers)

    def deactivate_candidate(self, candidate_id, headers):
        return self._request("POST", f"/candidates/{candidate_id}/deactivate", payload={}, headers=headers)

    def reactivate_candidate(self, candidate_id, headers):
        return self._request("POST", f"/candidates/{candidate_id}/reactivate", payload={}, headers=headers)

    def remove_candidate(self, candidate_id, payload, headers):
        return self._request("POST", f"/candidates/{candidate_id}/remove", payload, headers)

    # ─── Clinical scores ───────────────────────────────────────────────
    def create_clinical_score(self, candidate_id, payload, headers):
        return self._request("POST", f"/candidates/{candidate_id}/clinical-scores", payload, headers)

    def list_clinical_scores(self, candidate_id, headers, params=None):
        return self._request("GET", f"/candidates/{candidate_id}/clinical-scores", headers=headers, params=params)

    def get_clinical_score(self, score_id, headers):
        return self._request("GET", f"/clinical-scores/{score_id}", headers=headers)

    def finalize_clinical_score(self, score_id, headers):
        return self._request("POST", f"/clinical-scores/{score_id}/finalize", payload={}, headers=headers)

    # ─── Waitlist registrations ────────────────────────────────────────
    def list_registrations(self, candidate_id, headers, params=None):
        return self._request("GET", f"/candidates/{candidate_id}/registrations", headers=headers, params=params)

    # ─── Donor organs ──────────────────────────────────────────────────
    def create_donor_organ(self, payload, headers):
        return self._request("POST", "/donor-organs", payload, headers)

    def list_donor_organs(self, headers, params=None):
        return self._request("GET", "/donor-organs", headers=headers, params=params)

    def get_donor_organ(self, organ_id, headers):
        return self._request("GET", f"/donor-organs/{organ_id}", headers=headers)

    def discard_donor_organ(self, organ_id, headers):
        return self._request("POST", f"/donor-organs/{organ_id}/discard", payload={}, headers=headers)

    def offer_next(self, organ_id, payload, headers):
        return self._request("POST", f"/donor-organs/{organ_id}/offer-next", payload, headers)

    # ─── Match runs ────────────────────────────────────────────────────
    def create_match_run(self, payload, headers):
        return self._request("POST", "/match-runs", payload, headers)

    def get_match_run(self, run_id, headers):
        return self._request("GET", f"/match-runs/{run_id}", headers=headers)

    def list_match_runs(self, headers, params=None):
        return self._request("GET", "/match-runs", headers=headers, params=params)

    def list_match_run_entries(self, run_id, headers, params=None):
        return self._request("GET", f"/match-runs/{run_id}/entries", headers=headers, params=params)

    def get_match_list_entry(self, entry_id, headers):
        return self._request("GET", f"/match-list-entries/{entry_id}", headers=headers)

    def list_match_list_entries(self, headers, params=None):
        return self._request("GET", "/match-list-entries", headers=headers, params=params)

    # ─── Offers ────────────────────────────────────────────────────────
    def create_offer(self, payload, headers):
        return self._request("POST", "/offers", payload, headers)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/offers/{offer_id}", headers=headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/offers", headers=headers, params=params)

    def accept_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/offers/{offer_id}/accept", payload, headers)

    def decline_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/offers/{offer_id}/decline", payload, headers)

    def expire_offer(self, offer_id, headers):
        return self._request("POST", f"/offers/{offer_id}/expire", payload={}, headers=headers)

    # ─── Transplants & follow-ups ──────────────────────────────────────
    def create_transplant(self, payload, headers):
        return self._request("POST", "/transplants", payload, headers)

    def get_transplant(self, transplant_id, headers):
        return self._request("GET", f"/transplants/{transplant_id}", headers=headers)

    def list_transplants(self, headers, params=None):
        return self._request("GET", "/transplants", headers=headers, params=params)

    def mark_graft_failed(self, transplant_id, headers):
        return self._request("POST", f"/transplants/{transplant_id}/mark-graft-failed", payload={}, headers=headers)

    def create_follow_up(self, transplant_id, payload, headers):
        return self._request("POST", f"/transplants/{transplant_id}/follow-ups", payload, headers)

    def list_follow_ups(self, transplant_id, headers, params=None):
        return self._request("GET", f"/transplants/{transplant_id}/follow-ups", headers=headers, params=params)

    def get_follow_up(self, follow_up_id, headers):
        return self._request("GET", f"/follow-ups/{follow_up_id}", headers=headers)

    def complete_follow_up(self, follow_up_id, headers):
        return self._request("POST", f"/follow-ups/{follow_up_id}/complete", payload={}, headers=headers)

    def mark_follow_up_missed(self, follow_up_id, headers):
        return self._request("POST", f"/follow-ups/{follow_up_id}/mark-missed", payload={}, headers=headers)

    # ─── UNOS reports ──────────────────────────────────────────────────
    def create_unos_report(self, payload, headers):
        return self._request("POST", "/unos-reports", payload, headers)

    def get_unos_report(self, report_id, headers):
        return self._request("GET", f"/unos-reports/{report_id}", headers=headers)

    def list_unos_reports(self, headers, params=None):
        return self._request("GET", "/unos-reports", headers=headers, params=params)

    def accept_unos_report(self, report_id, headers):
        return self._request("POST", f"/unos-reports/{report_id}/accept", payload={}, headers=headers)

    def reject_unos_report(self, report_id, payload, headers):
        return self._request("POST", f"/unos-reports/{report_id}/reject", payload, headers)

    # ─── Deterministic clock ───────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers):
        return self._request("GET", "/_clock", headers=headers)


api_client = ApiClient()
