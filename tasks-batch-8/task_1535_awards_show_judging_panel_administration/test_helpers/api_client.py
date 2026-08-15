"""API client: one method per endpoint defined in the PRD (§4).

All routes are mounted under the /awards prefix, including the logical-clock
control used by tests to drive every time-window gate (PRD §2.6).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/awards/_clock/set_current_utc", payload, headers)

    # --- seasons ---
    def create_season(self, payload, headers):
        return self._request("POST", "/awards/seasons", payload, headers)

    def list_seasons(self, headers, params=None):
        return self._request("GET", "/awards/seasons", headers=headers, params=params)

    def get_season(self, season_id, headers):
        return self._request("GET", f"/awards/seasons/{season_id}", headers=headers)

    def open_season(self, season_id, headers):
        return self._request("POST", f"/awards/seasons/{season_id}/open", {}, headers)

    def close_submissions(self, season_id, headers):
        return self._request(
            "POST", f"/awards/seasons/{season_id}/close-submissions", {}, headers
        )

    def begin_judging(self, season_id, headers):
        return self._request(
            "POST", f"/awards/seasons/{season_id}/begin-judging", {}, headers
        )

    def lock_finalists(self, season_id, headers):
        return self._request(
            "POST", f"/awards/seasons/{season_id}/lock-finalists", {}, headers
        )

    def embargo_season(self, season_id, payload, headers):
        return self._request(
            "POST", f"/awards/seasons/{season_id}/embargo", payload, headers
        )

    def go_live(self, season_id, headers):
        return self._request("POST", f"/awards/seasons/{season_id}/go-live", {}, headers)

    def publish_results(self, season_id, headers):
        return self._request(
            "POST", f"/awards/seasons/{season_id}/publish-results", {}, headers
        )

    def archive_season(self, season_id, headers):
        return self._request("POST", f"/awards/seasons/{season_id}/archive", {}, headers)

    def cancel_season(self, season_id, headers):
        return self._request("POST", f"/awards/seasons/{season_id}/cancel", {}, headers)

    # --- categories ---
    def create_category(self, season_id, payload, headers):
        return self._request(
            "POST", f"/awards/seasons/{season_id}/categories", payload, headers
        )

    def list_categories(self, season_id, headers, params=None):
        return self._request(
            "GET", f"/awards/seasons/{season_id}/categories", headers=headers, params=params
        )

    def get_category(self, category_id, headers):
        return self._request("GET", f"/awards/categories/{category_id}", headers=headers)

    def publish_category(self, category_id, headers):
        return self._request(
            "POST", f"/awards/categories/{category_id}/publish", {}, headers
        )

    def suspend_category(self, category_id, headers):
        return self._request(
            "POST", f"/awards/categories/{category_id}/suspend", {}, headers
        )

    def retire_category(self, category_id, headers):
        return self._request(
            "POST", f"/awards/categories/{category_id}/retire", {}, headers
        )

    # --- entrants ---
    def create_entrant(self, payload, headers):
        return self._request("POST", "/awards/entrants", payload, headers)

    def list_entrants(self, headers, params=None):
        return self._request("GET", "/awards/entrants", headers=headers, params=params)

    def get_entrant(self, entrant_id, headers):
        return self._request("GET", f"/awards/entrants/{entrant_id}", headers=headers)

    def list_entrant_entries(self, entrant_id, headers, params=None):
        return self._request(
            "GET", f"/awards/entrants/{entrant_id}/entries", headers=headers, params=params
        )

    # --- entries & materials ---
    def create_entry(self, category_id, payload, headers):
        return self._request(
            "POST", f"/awards/categories/{category_id}/entries", payload, headers
        )

    def list_category_entries(self, category_id, headers, params=None):
        return self._request(
            "GET", f"/awards/categories/{category_id}/entries", headers=headers, params=params
        )

    def get_entry(self, entry_id, headers):
        return self._request("GET", f"/awards/entries/{entry_id}", headers=headers)

    def create_material(self, entry_id, payload, headers):
        return self._request(
            "POST", f"/awards/entries/{entry_id}/materials", payload, headers
        )

    def list_materials(self, entry_id, headers, params=None):
        return self._request(
            "GET", f"/awards/entries/{entry_id}/materials", headers=headers, params=params
        )

    def accept_material(self, material_id, headers):
        return self._request(
            "POST", f"/awards/materials/{material_id}/accept", {}, headers
        )

    def reject_material(self, material_id, headers):
        return self._request(
            "POST", f"/awards/materials/{material_id}/reject", {}, headers
        )

    def submit_entry(self, entry_id, headers):
        return self._request("POST", f"/awards/entries/{entry_id}/submit", {}, headers)

    def waive_fee(self, entry_id, headers):
        return self._request("POST", f"/awards/entries/{entry_id}/waive-fee", {}, headers)

    def mark_eligible(self, entry_id, headers):
        return self._request(
            "POST", f"/awards/entries/{entry_id}/mark-eligible", {}, headers
        )

    def mark_ineligible(self, entry_id, headers):
        return self._request(
            "POST", f"/awards/entries/{entry_id}/mark-ineligible", {}, headers
        )

    def request_recheck(self, entry_id, headers):
        return self._request(
            "POST", f"/awards/entries/{entry_id}/request-recheck", {}, headers
        )

    def withdraw_entry(self, entry_id, headers):
        return self._request("POST", f"/awards/entries/{entry_id}/withdraw", {}, headers)

    # --- invoices ---
    def list_entry_invoices(self, entry_id, headers, params=None):
        return self._request(
            "GET", f"/awards/entries/{entry_id}/invoices", headers=headers, params=params
        )

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/awards/invoices/{invoice_id}", headers=headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/awards/invoices/{invoice_id}/pay", {}, headers)

    # --- judges ---
    def create_judge(self, payload, headers):
        return self._request("POST", "/awards/judges", payload, headers)

    def list_judges(self, headers, params=None):
        return self._request("GET", "/awards/judges", headers=headers, params=params)

    def get_judge(self, judge_id, headers):
        return self._request("GET", f"/awards/judges/{judge_id}", headers=headers)

    def accept_judge(self, judge_id, headers):
        return self._request("POST", f"/awards/judges/{judge_id}/accept", {}, headers)

    def decline_judge(self, judge_id, headers):
        return self._request("POST", f"/awards/judges/{judge_id}/decline", {}, headers)

    def activate_judge(self, judge_id, headers):
        return self._request("POST", f"/awards/judges/{judge_id}/activate", {}, headers)

    def suspend_judge(self, judge_id, headers):
        return self._request("POST", f"/awards/judges/{judge_id}/suspend", {}, headers)

    def retire_judge(self, judge_id, headers):
        return self._request("POST", f"/awards/judges/{judge_id}/retire", {}, headers)

    # --- conflict declarations ---
    def create_conflict_declaration(self, judge_id, payload, headers):
        return self._request(
            "POST", f"/awards/judges/{judge_id}/conflict-declarations", payload, headers
        )

    def list_judge_declarations(self, judge_id, headers, params=None):
        return self._request(
            "GET",
            f"/awards/judges/{judge_id}/conflict-declarations",
            headers=headers,
            params=params,
        )

    def list_season_declarations(self, season_id, headers, params=None):
        return self._request(
            "GET",
            f"/awards/seasons/{season_id}/conflict-declarations",
            headers=headers,
            params=params,
        )

    def list_entrant_declarations(self, entrant_id, headers, params=None):
        return self._request(
            "GET",
            f"/awards/entrants/{entrant_id}/conflict-declarations",
            headers=headers,
            params=params,
        )

    def list_category_declarations(self, category_id, headers, params=None):
        return self._request(
            "GET",
            f"/awards/categories/{category_id}/conflict-declarations",
            headers=headers,
            params=params,
        )

    def acknowledge_declaration(self, declaration_id, headers):
        return self._request(
            "POST",
            f"/awards/conflict-declarations/{declaration_id}/acknowledge",
            {},
            headers,
        )

    def rescind_declaration(self, declaration_id, headers):
        return self._request(
            "POST", f"/awards/conflict-declarations/{declaration_id}/rescind", {}, headers
        )

    # --- scoring rounds ---
    def create_round(self, category_id, payload, headers):
        return self._request(
            "POST", f"/awards/categories/{category_id}/scoring-rounds", payload, headers
        )

    def list_rounds(self, category_id, headers, params=None):
        return self._request(
            "GET",
            f"/awards/categories/{category_id}/scoring-rounds",
            headers=headers,
            params=params,
        )

    def get_round(self, round_id, headers):
        return self._request("GET", f"/awards/scoring-rounds/{round_id}", headers=headers)

    def lock_panel(self, round_id, headers):
        return self._request(
            "POST", f"/awards/scoring-rounds/{round_id}/lock-panel", {}, headers
        )

    def open_round(self, round_id, headers):
        return self._request("POST", f"/awards/scoring-rounds/{round_id}/open", {}, headers)

    def close_round(self, round_id, headers):
        return self._request("POST", f"/awards/scoring-rounds/{round_id}/close", {}, headers)

    def normalize_round(self, round_id, headers):
        return self._request(
            "POST", f"/awards/scoring-rounds/{round_id}/normalize", {}, headers
        )

    # --- panel assignments ---
    def create_panel_assignment(self, round_id, payload, headers):
        return self._request(
            "POST", f"/awards/scoring-rounds/{round_id}/panel-assignments", payload, headers
        )

    def list_round_assignments(self, round_id, headers, params=None):
        return self._request(
            "GET",
            f"/awards/scoring-rounds/{round_id}/panel-assignments",
            headers=headers,
            params=params,
        )

    def list_judge_assignments(self, judge_id, headers, params=None):
        return self._request(
            "GET",
            f"/awards/judges/{judge_id}/panel-assignments",
            headers=headers,
            params=params,
        )

    def list_category_assignments(self, category_id, headers, params=None):
        return self._request(
            "GET",
            f"/awards/categories/{category_id}/panel-assignments",
            headers=headers,
            params=params,
        )

    def confirm_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/awards/panel-assignments/{assignment_id}/confirm", {}, headers
        )

    def recuse_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/awards/panel-assignments/{assignment_id}/recuse", {}, headers
        )

    def remove_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/awards/panel-assignments/{assignment_id}/remove", {}, headers
        )

    # --- scores ---
    def create_score(self, round_id, payload, headers):
        return self._request(
            "POST", f"/awards/scoring-rounds/{round_id}/scores", payload, headers
        )

    def list_round_scores(self, round_id, headers, params=None):
        return self._request(
            "GET", f"/awards/scoring-rounds/{round_id}/scores", headers=headers, params=params
        )

    def list_entry_scores(self, entry_id, headers, params=None):
        return self._request(
            "GET", f"/awards/entries/{entry_id}/scores", headers=headers, params=params
        )

    def list_judge_scores(self, judge_id, headers, params=None):
        return self._request(
            "GET", f"/awards/judges/{judge_id}/scores", headers=headers, params=params
        )

    def submit_score(self, score_id, headers):
        return self._request("POST", f"/awards/scores/{score_id}/submit", {}, headers)

    # --- finalists ---
    def list_finalists(self, category_id, headers, params=None):
        return self._request(
            "GET", f"/awards/categories/{category_id}/finalists", headers=headers, params=params
        )

    def get_entry_finalist_record(self, entry_id, headers):
        return self._request(
            "GET", f"/awards/entries/{entry_id}/finalist-record", headers=headers
        )

    def list_entry_announcements(self, entry_id, headers, params=None):
        return self._request(
            "GET", f"/awards/entries/{entry_id}/announcements", headers=headers, params=params
        )

    def notify_finalist(self, finalist_id, headers):
        return self._request("POST", f"/awards/finalists/{finalist_id}/notify", {}, headers)

    def acknowledge_finalist(self, finalist_id, headers):
        return self._request(
            "POST", f"/awards/finalists/{finalist_id}/acknowledge", {}, headers
        )

    def decline_finalist(self, finalist_id, headers):
        return self._request("POST", f"/awards/finalists/{finalist_id}/decline", {}, headers)

    # --- ceremonies ---
    def create_ceremony(self, season_id, payload, headers):
        return self._request(
            "POST", f"/awards/seasons/{season_id}/ceremonies", payload, headers
        )

    def list_ceremonies(self, season_id, headers, params=None):
        return self._request(
            "GET", f"/awards/seasons/{season_id}/ceremonies", headers=headers, params=params
        )

    def get_ceremony(self, ceremony_id, headers):
        return self._request("GET", f"/awards/ceremonies/{ceremony_id}", headers=headers)

    def rehearse_ceremony(self, ceremony_id, headers):
        return self._request(
            "POST", f"/awards/ceremonies/{ceremony_id}/rehearse", {}, headers
        )

    def conclude_ceremony(self, ceremony_id, headers):
        return self._request(
            "POST", f"/awards/ceremonies/{ceremony_id}/conclude", {}, headers
        )

    def abort_ceremony(self, ceremony_id, headers):
        return self._request(
            "POST", f"/awards/ceremonies/{ceremony_id}/abort", {}, headers
        )

    # --- winner announcements ---
    def create_announcement(self, category_id, payload, headers):
        return self._request(
            "POST", f"/awards/categories/{category_id}/announcements", payload, headers
        )

    def get_announcement(self, announcement_id, headers):
        return self._request(
            "GET", f"/awards/announcements/{announcement_id}", headers=headers
        )

    def list_category_announcements(self, category_id, headers, params=None):
        return self._request(
            "GET",
            f"/awards/categories/{category_id}/announcements",
            headers=headers,
            params=params,
        )

    def list_ceremony_announcements(self, ceremony_id, headers, params=None):
        return self._request(
            "GET",
            f"/awards/ceremonies/{ceremony_id}/announcements",
            headers=headers,
            params=params,
        )

    def announce(self, announcement_id, headers):
        return self._request(
            "POST", f"/awards/announcements/{announcement_id}/announce", {}, headers
        )

    def retract_announcement(self, announcement_id, payload, headers):
        return self._request(
            "POST", f"/awards/announcements/{announcement_id}/retract", payload, headers
        )

    def restage_announcement(self, announcement_id, headers):
        return self._request(
            "POST", f"/awards/announcements/{announcement_id}/restage", {}, headers
        )

    # --- fulfillment orders ---
    def list_season_fulfillment_orders(self, season_id, headers, params=None):
        return self._request(
            "GET",
            f"/awards/seasons/{season_id}/fulfillment-orders",
            headers=headers,
            params=params,
        )

    def list_entry_fulfillment_orders(self, entry_id, headers, params=None):
        return self._request(
            "GET",
            f"/awards/entries/{entry_id}/fulfillment-orders",
            headers=headers,
            params=params,
        )

    def list_announcement_fulfillment_orders(self, announcement_id, headers, params=None):
        return self._request(
            "GET",
            f"/awards/announcements/{announcement_id}/fulfillment-orders",
            headers=headers,
            params=params,
        )

    def queue_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/awards/fulfillment-orders/{order_id}/queue", payload, headers
        )

    def start_production(self, order_id, headers):
        return self._request(
            "POST", f"/awards/fulfillment-orders/{order_id}/start-production", {}, headers
        )

    def ship_order(self, order_id, headers):
        return self._request(
            "POST", f"/awards/fulfillment-orders/{order_id}/ship", {}, headers
        )

    def deliver_order(self, order_id, headers):
        return self._request(
            "POST", f"/awards/fulfillment-orders/{order_id}/deliver", {}, headers
        )

    # --- appeals ---
    def create_appeal(self, entry_id, payload, headers):
        return self._request("POST", f"/awards/entries/{entry_id}/appeals", payload, headers)

    def list_entry_appeals(self, entry_id, headers, params=None):
        return self._request(
            "GET", f"/awards/entries/{entry_id}/appeals", headers=headers, params=params
        )

    def list_entrant_appeals(self, entrant_id, headers, params=None):
        return self._request(
            "GET", f"/awards/entrants/{entrant_id}/appeals", headers=headers, params=params
        )

    def take_appeal_under_review(self, appeal_id, headers):
        return self._request(
            "POST", f"/awards/appeals/{appeal_id}/take-under-review", {}, headers
        )

    def uphold_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/awards/appeals/{appeal_id}/uphold", payload, headers)

    def deny_appeal(self, appeal_id, headers):
        return self._request("POST", f"/awards/appeals/{appeal_id}/deny", {}, headers)

    def withdraw_appeal(self, appeal_id, headers):
        return self._request("POST", f"/awards/appeals/{appeal_id}/withdraw", {}, headers)

    # --- audit log ---
    def list_audit_logs(self, season_id, headers, params=None):
        return self._request(
            "GET", f"/awards/seasons/{season_id}/audit-logs", headers=headers, params=params
        )


api_client = ApiClient()
