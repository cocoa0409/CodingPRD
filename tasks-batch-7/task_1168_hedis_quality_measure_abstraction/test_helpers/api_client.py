"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/hedis/_clock/set_current_utc", payload, headers)

    # --- MeasurementSeason ---
    def create_season(self, payload, headers):
        return self._request("POST", "/hedis/seasons", payload, headers)

    def get_season(self, season_id, headers):
        return self._request("GET", f"/hedis/seasons/{season_id}", headers=headers)

    def open_season(self, season_id, headers):
        return self._request("POST", f"/hedis/seasons/{season_id}/open", headers=headers)

    def close_season_submission(self, season_id, headers):
        return self._request(
            "POST", f"/hedis/seasons/{season_id}/close-submission", headers=headers
        )

    def list_season_specifications(self, season_id, headers, params=None):
        return self._request(
            "GET", f"/hedis/seasons/{season_id}/measure-specifications",
            headers=headers, params=params,
        )

    def list_season_engagements(self, season_id, headers, params=None):
        return self._request(
            "GET", f"/hedis/seasons/{season_id}/audit-engagements",
            headers=headers, params=params,
        )

    # --- MeasureSpecification ---
    def create_spec(self, payload, headers):
        return self._request("POST", "/hedis/measure-specifications", payload, headers)

    def get_spec(self, spec_id, headers):
        return self._request(
            "GET", f"/hedis/measure-specifications/{spec_id}", headers=headers
        )

    def activate_spec(self, spec_id, headers):
        return self._request(
            "POST", f"/hedis/measure-specifications/{spec_id}/activate", headers=headers
        )

    def retire_spec(self, spec_id, headers):
        return self._request(
            "POST", f"/hedis/measure-specifications/{spec_id}/retire", headers=headers
        )

    # --- Member / enrollment ---
    def create_member(self, payload, headers=None):
        return self._request("POST", "/hedis/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/hedis/members/{member_id}", headers=headers)

    def list_member_enrollment_segments(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/hedis/members/{member_id}/enrollment-segments",
            headers=headers, params=params,
        )

    def create_enrollment_segment(self, payload, headers):
        return self._request("POST", "/hedis/enrollment-segments", payload, headers)

    # --- Provider ---
    def create_provider(self, payload, headers):
        return self._request("POST", "/hedis/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/hedis/providers/{provider_id}", headers=headers)

    def get_provider_gap_burden(self, provider_id, headers, params=None):
        return self._request(
            "GET", f"/hedis/providers/{provider_id}/gap-burden",
            headers=headers, params=params,
        )

    # --- MeasureRun ---
    def create_run(self, payload, headers):
        return self._request("POST", "/hedis/measure-runs", payload, headers)

    def get_run(self, run_id, headers):
        return self._request("GET", f"/hedis/measure-runs/{run_id}", headers=headers)

    def list_runs(self, headers, params=None):
        return self._request("GET", "/hedis/measure-runs", headers=headers, params=params)

    def identify_population(self, run_id, headers):
        return self._request(
            "POST", f"/hedis/measure-runs/{run_id}/identify-population", headers=headers
        )

    def compute_rate(self, run_id, payload, headers):
        return self._request(
            "POST", f"/hedis/measure-runs/{run_id}/compute-rate", payload, headers
        )

    def submit_run(self, run_id, headers):
        return self._request(
            "POST", f"/hedis/measure-runs/{run_id}/submit", headers=headers
        )

    def certify_run(self, run_id, payload, headers):
        return self._request(
            "POST", f"/hedis/measure-runs/{run_id}/certify", payload, headers
        )

    def reopen_run(self, run_id, headers):
        return self._request(
            "POST", f"/hedis/measure-runs/{run_id}/reopen", headers=headers
        )

    def list_run_samples(self, run_id, headers, params=None):
        return self._request(
            "GET", f"/hedis/measure-runs/{run_id}/samples", headers=headers, params=params
        )

    def list_run_population_entries(self, run_id, headers, params=None):
        return self._request(
            "GET", f"/hedis/measure-runs/{run_id}/population-entries",
            headers=headers, params=params,
        )

    def list_run_supplemental_batches(self, run_id, headers, params=None):
        return self._request(
            "GET", f"/hedis/measure-runs/{run_id}/supplemental-batches",
            headers=headers, params=params,
        )

    def list_run_gap_items(self, run_id, headers, params=None):
        return self._request(
            "GET", f"/hedis/measure-runs/{run_id}/gap-items",
            headers=headers, params=params,
        )

    def list_run_engagements(self, run_id, headers, params=None):
        return self._request(
            "GET", f"/hedis/measure-runs/{run_id}/audit-engagements",
            headers=headers, params=params,
        )

    # --- PopulationEntry ---
    def exclude_population_entry(self, entry_id, payload, headers):
        return self._request(
            "POST", f"/hedis/population-entries/{entry_id}/exclude", payload, headers
        )

    # --- Sample ---
    def create_sample(self, payload, headers):
        return self._request("POST", "/hedis/samples", payload, headers)

    def get_sample(self, sample_id, headers):
        return self._request("GET", f"/hedis/samples/{sample_id}", headers=headers)

    def finalize_sample(self, sample_id, headers):
        return self._request(
            "POST", f"/hedis/samples/{sample_id}/finalize", headers=headers
        )

    def evaluate_irr(self, sample_id, headers):
        return self._request(
            "POST", f"/hedis/samples/{sample_id}/evaluate-irr", headers=headers
        )

    def list_sample_chases(self, sample_id, headers, params=None):
        return self._request(
            "GET", f"/hedis/samples/{sample_id}/chart-chases",
            headers=headers, params=params,
        )

    # --- ChartChase ---
    def get_chase(self, chase_id, headers):
        return self._request("GET", f"/hedis/chart-chases/{chase_id}", headers=headers)

    def receive_chase(self, chase_id, headers):
        return self._request(
            "POST", f"/hedis/chart-chases/{chase_id}/receive", headers=headers
        )

    def reject_chase_unreadable(self, chase_id, headers):
        return self._request(
            "POST", f"/hedis/chart-chases/{chase_id}/reject-unreadable", headers=headers
        )

    def rechase_chase(self, chase_id, headers):
        return self._request(
            "POST", f"/hedis/chart-chases/{chase_id}/rechase", headers=headers
        )

    def withdraw_chase(self, chase_id, headers):
        return self._request(
            "POST", f"/hedis/chart-chases/{chase_id}/withdraw", headers=headers
        )

    def mark_chase_excluded(self, chase_id, payload, headers):
        return self._request(
            "POST", f"/hedis/chart-chases/{chase_id}/mark-excluded", payload, headers
        )

    def list_chase_abstractions(self, chase_id, headers, params=None):
        return self._request(
            "GET", f"/hedis/chart-chases/{chase_id}/abstractions",
            headers=headers, params=params,
        )

    # --- Abstraction ---
    def create_abstraction(self, payload, headers):
        return self._request("POST", "/hedis/abstractions", payload, headers)

    def get_abstraction(self, abstraction_id, headers):
        return self._request(
            "GET", f"/hedis/abstractions/{abstraction_id}", headers=headers
        )

    def update_abstraction(self, abstraction_id, payload, headers):
        return self._request(
            "PUT", f"/hedis/abstractions/{abstraction_id}", payload, headers
        )

    def submit_abstraction(self, abstraction_id, headers):
        return self._request(
            "POST", f"/hedis/abstractions/{abstraction_id}/submit", headers=headers
        )

    def retract_abstraction(self, abstraction_id, headers):
        return self._request(
            "POST", f"/hedis/abstractions/{abstraction_id}/retract", headers=headers
        )

    def list_abstraction_overreads(self, abstraction_id, headers, params=None):
        return self._request(
            "GET", f"/hedis/abstractions/{abstraction_id}/over-reads",
            headers=headers, params=params,
        )

    # --- OverReadReview ---
    def create_overread(self, payload, headers):
        return self._request("POST", "/hedis/over-reads", payload, headers)

    # --- Supplemental ---
    def create_supplemental_batch(self, payload, headers):
        return self._request("POST", "/hedis/supplemental-batches", payload, headers)

    def get_supplemental_batch(self, batch_id, headers):
        return self._request(
            "GET", f"/hedis/supplemental-batches/{batch_id}", headers=headers
        )

    def screen_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/hedis/supplemental-batches/{batch_id}/screen", headers=headers
        )

    def accept_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/hedis/supplemental-batches/{batch_id}/accept", headers=headers
        )

    def reject_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/hedis/supplemental-batches/{batch_id}/reject", headers=headers
        )

    def list_batch_records(self, batch_id, headers, params=None):
        return self._request(
            "GET", f"/hedis/supplemental-batches/{batch_id}/records",
            headers=headers, params=params,
        )

    def create_supplemental_record(self, payload, headers):
        return self._request("POST", "/hedis/supplemental-records", payload, headers)

    # --- GapItem ---
    def mark_gap_outreach_done(self, gap_id, headers):
        return self._request(
            "POST", f"/hedis/gap-items/{gap_id}/mark-outreach-done", headers=headers
        )

    def close_gap(self, gap_id, payload, headers):
        return self._request("POST", f"/hedis/gap-items/{gap_id}/close", payload, headers)

    # --- Audit ---
    def create_engagement(self, payload, headers):
        return self._request("POST", "/hedis/audit-engagements", payload, headers)

    def get_engagement(self, engagement_id, headers):
        return self._request(
            "GET", f"/hedis/audit-engagements/{engagement_id}", headers=headers
        )

    def begin_review(self, engagement_id, headers):
        return self._request(
            "POST", f"/hedis/audit-engagements/{engagement_id}/begin-review",
            headers=headers,
        )

    def complete_engagement(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/hedis/audit-engagements/{engagement_id}/complete",
            payload, headers,
        )

    def list_engagement_findings(self, engagement_id, headers, params=None):
        return self._request(
            "GET", f"/hedis/audit-engagements/{engagement_id}/findings",
            headers=headers, params=params,
        )

    def create_finding(self, payload, headers):
        return self._request("POST", "/hedis/audit-findings", payload, headers)

    def resolve_finding(self, finding_id, headers):
        return self._request(
            "POST", f"/hedis/audit-findings/{finding_id}/resolve", headers=headers
        )


api_client = ApiClient()
