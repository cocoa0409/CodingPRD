"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Ops / logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/surveillance/_clock/set_current_utc", payload, headers)

    def ops_run(self, headers):
        return self._request("POST", "/surveillance/ops/runs", {}, headers)

    # --- Employees ---
    def create_employee(self, payload, headers):
        return self._request("POST", "/surveillance/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/surveillance/employees/{employee_id}", headers=headers)

    def employment_transition(self, employee_id, payload, headers):
        return self._request("POST", f"/surveillance/employees/{employee_id}/employment-transition", payload, headers)

    def attest(self, employee_id, headers):
        return self._request("POST", f"/surveillance/employees/{employee_id}/attest", {}, headers)

    def list_employee_personal_trades(self, employee_id, headers, params=None):
        return self._request("GET", f"/surveillance/employees/{employee_id}/personal-trades", headers=headers, params=params)

    def list_employee_comm_review_items(self, employee_id, headers, params=None):
        return self._request("GET", f"/surveillance/employees/{employee_id}/comm-review-items", headers=headers, params=params)

    # --- Venues ---
    def create_venue(self, payload, headers):
        return self._request("POST", "/surveillance/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/surveillance/venues/{venue_id}", headers=headers)

    def venue_transition(self, venue_id, payload, headers):
        return self._request("POST", f"/surveillance/venues/{venue_id}/transition", payload, headers)

    def list_venue_arrangements(self, venue_id, headers, params=None):
        return self._request("GET", f"/surveillance/venues/{venue_id}/routing-arrangements", headers=headers, params=params)

    def list_venue_snapshots(self, venue_id, headers, params=None):
        return self._request("GET", f"/surveillance/venues/{venue_id}/execution-quality-snapshots", headers=headers, params=params)

    # --- Routing arrangements ---
    def create_arrangement(self, payload, headers):
        return self._request("POST", "/surveillance/routing-arrangements", payload, headers)

    def get_arrangement(self, arrangement_id, headers):
        return self._request("GET", f"/surveillance/routing-arrangements/{arrangement_id}", headers=headers)

    def arrangement_transition(self, arrangement_id, payload, headers):
        return self._request("POST", f"/surveillance/routing-arrangements/{arrangement_id}/transition", payload, headers)

    def amend_arrangement(self, arrangement_id, payload, headers):
        return self._request("POST", f"/surveillance/routing-arrangements/{arrangement_id}/amend", payload, headers)

    def list_arrangement_orders(self, arrangement_id, headers, params=None):
        return self._request("GET", f"/surveillance/routing-arrangements/{arrangement_id}/orders", headers=headers, params=params)

    # --- Orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/surveillance/orders", payload, headers)

    def order_transition(self, order_id, payload, headers):
        return self._request("POST", f"/surveillance/orders/{order_id}/transition", payload, headers)

    # --- Execution quality snapshots ---
    def create_snapshot(self, payload, headers):
        return self._request("POST", "/surveillance/execution-quality-snapshots", payload, headers)

    def lock_snapshot(self, snapshot_id, headers):
        return self._request("POST", f"/surveillance/execution-quality-snapshots/{snapshot_id}/lock", {}, headers)

    # --- PFOF disclosures ---
    def create_disclosure(self, payload, headers):
        return self._request("POST", "/surveillance/pfof-disclosures", payload, headers)

    def get_disclosure(self, disclosure_id, headers):
        return self._request("GET", f"/surveillance/pfof-disclosures/{disclosure_id}", headers=headers)

    def list_disclosures(self, headers, params=None):
        return self._request("GET", "/surveillance/pfof-disclosures", headers=headers, params=params)

    def disclosure_transition(self, disclosure_id, payload, headers):
        return self._request("POST", f"/surveillance/pfof-disclosures/{disclosure_id}/transition", payload, headers)

    def revise_disclosure(self, disclosure_id, payload, headers):
        return self._request("POST", f"/surveillance/pfof-disclosures/{disclosure_id}/revise", payload, headers)

    # --- Best-execution reviews ---
    def create_review(self, payload, headers):
        return self._request("POST", "/surveillance/best-ex-reviews", payload, headers)

    def get_review(self, review_id, headers):
        return self._request("GET", f"/surveillance/best-ex-reviews/{review_id}", headers=headers)

    def review_transition(self, review_id, payload, headers):
        return self._request("POST", f"/surveillance/best-ex-reviews/{review_id}/transition", payload, headers)

    def vote_review(self, review_id, headers):
        return self._request("POST", f"/surveillance/best-ex-reviews/{review_id}/vote", {}, headers)

    # --- Surveillance alerts ---
    def list_alerts(self, headers, params=None):
        return self._request("GET", "/surveillance/surveillance-alerts", headers=headers, params=params)

    def get_alert(self, alert_id, headers):
        return self._request("GET", f"/surveillance/surveillance-alerts/{alert_id}", headers=headers)

    def alert_transition(self, alert_id, payload, headers):
        return self._request("POST", f"/surveillance/surveillance-alerts/{alert_id}/transition", payload, headers)

    # --- Surveillance cases ---
    def list_cases(self, headers, params=None):
        return self._request("GET", "/surveillance/surveillance-cases", headers=headers, params=params)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/surveillance/surveillance-cases/{case_id}", headers=headers)

    def case_review_transition(self, case_id, payload, headers):
        return self._request("POST", f"/surveillance/surveillance-cases/{case_id}/review-transition", payload, headers)

    def case_filing_transition(self, case_id, payload, headers):
        return self._request("POST", f"/surveillance/surveillance-cases/{case_id}/filing-transition", payload, headers)

    # --- Personal trades ---
    def create_personal_trade(self, payload, headers):
        return self._request("POST", "/surveillance/personal-trades", payload, headers)

    def personal_trade_transition(self, trade_id, payload, headers):
        return self._request("POST", f"/surveillance/personal-trades/{trade_id}/transition", payload, headers)

    # --- Restricted list ---
    def create_restricted_entry(self, payload, headers):
        return self._request("POST", "/surveillance/restricted-list-entries", payload, headers)

    def get_restricted_entry(self, entry_id, headers):
        return self._request("GET", f"/surveillance/restricted-list-entries/{entry_id}", headers=headers)

    # --- Communications review ---
    def create_comm_item(self, payload, headers):
        return self._request("POST", "/surveillance/comm-review-items", payload, headers)

    def comm_item_transition(self, item_id, payload, headers):
        return self._request("POST", f"/surveillance/comm-review-items/{item_id}/transition", payload, headers)

    # --- Lexicon policies ---
    def create_lexicon_policy(self, payload, headers):
        return self._request("POST", "/surveillance/lexicon-policies", payload, headers)

    def get_lexicon_policy(self, policy_id, headers):
        return self._request("GET", f"/surveillance/lexicon-policies/{policy_id}", headers=headers)

    def patch_lexicon_policy(self, policy_id, payload, headers):
        return self._request("PATCH", f"/surveillance/lexicon-policies/{policy_id}", payload, headers)

    # --- Compliance policies ---
    def create_compliance_policy(self, payload, headers):
        return self._request("POST", "/surveillance/compliance-policies", payload, headers)

    def get_compliance_policy(self, policy_id, headers):
        return self._request("GET", f"/surveillance/compliance-policies/{policy_id}", headers=headers)

    def publish_compliance_policy(self, policy_id, headers):
        return self._request("POST", f"/surveillance/compliance-policies/{policy_id}/publish", {}, headers)

    # --- Training assignments ---
    def list_training_assignments(self, headers, params=None):
        return self._request("GET", "/surveillance/training-assignments", headers=headers, params=params)

    def get_training_assignment(self, assignment_id, headers):
        return self._request("GET", f"/surveillance/training-assignments/{assignment_id}", headers=headers)

    def complete_training_assignment(self, assignment_id, headers):
        return self._request("POST", f"/surveillance/training-assignments/{assignment_id}/complete", {}, headers)


api_client = ApiClient()
# The per-test-server harness SIGKILLs and respawns the server before every
# test. A pooled keep-alive connection would then be silently dead and the
# first request on it can fail with ConnectionResetError (104). Sending
# `Connection: close` keeps every request on a fresh connection — a pure
# transport-level choice with no effect on the API surface under test.
api_client.session.headers["Connection"] = "close"
