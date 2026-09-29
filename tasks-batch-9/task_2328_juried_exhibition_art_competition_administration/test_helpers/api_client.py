"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Juried Exhibition Administration API."""

    # ─── Exhibitions ──────────────────────────────────

    def create_exhibition(self, payload, headers):
        return self._request("POST", "/exhibitions", payload, headers)

    def list_exhibitions(self, headers, params=None):
        return self._request("GET", "/exhibitions", headers=headers, params=params)

    def get_exhibition(self, exhibition_id, headers):
        return self._request("GET", f"/exhibitions/{exhibition_id}", headers=headers)

    def advance_exhibition_phase(self, exhibition_id, payload, headers):
        return self._request(
            "POST", f"/exhibitions/{exhibition_id}/phase-advance", payload, headers
        )

    def run_acceptance_list(self, exhibition_id, payload, headers):
        return self._request(
            "POST", f"/exhibitions/{exhibition_id}/acceptance-list", payload, headers
        )

    def advance_settlement(self, exhibition_id, payload, headers):
        return self._request(
            "POST", f"/exhibitions/{exhibition_id}/settlement", payload, headers
        )

    def run_unclaimed_sweep(self, exhibition_id, headers, payload=None):
        return self._request(
            "POST", f"/exhibitions/{exhibition_id}/unclaimed-sweep",
            payload if payload is not None else {}, headers,
        )

    # ─── Artists ──────────────────────────────────────

    def create_artist(self, payload, headers):
        return self._request("POST", "/artists", payload, headers)

    def get_artist(self, artist_id, headers):
        return self._request("GET", f"/artists/{artist_id}", headers=headers)

    def patch_artist(self, artist_id, payload, headers):
        return self._request("PATCH", f"/artists/{artist_id}", payload, headers)

    def list_artist_conflict_declarations(self, artist_id, headers, params=None):
        return self._request(
            "GET", f"/artists/{artist_id}/conflict-declarations",
            headers=headers, params=params,
        )

    # ─── Entries ──────────────────────────────────────

    def create_entry(self, payload, headers):
        return self._request("POST", "/entries", payload, headers)

    def list_entries(self, headers, params=None):
        return self._request("GET", "/entries", headers=headers, params=params)

    def get_entry(self, entry_id, headers):
        return self._request("GET", f"/entries/{entry_id}", headers=headers)

    def attach_artwork(self, entry_id, payload, headers):
        return self._request("POST", f"/entries/{entry_id}/artworks", payload, headers)

    def submit_entry(self, entry_id, headers, payload=None):
        return self._request(
            "POST", f"/entries/{entry_id}/submit",
            payload if payload is not None else {}, headers,
        )

    def pay_entry_fee(self, entry_id, payload, headers):
        return self._request(
            "POST", f"/entries/{entry_id}/fee-payment", payload, headers
        )

    def waive_entry_fee(self, entry_id, headers, payload=None):
        return self._request(
            "POST", f"/entries/{entry_id}/fee-waiver",
            payload if payload is not None else {}, headers,
        )

    def withdraw_entry(self, entry_id, headers, payload=None):
        return self._request(
            "POST", f"/entries/{entry_id}/withdraw",
            payload if payload is not None else {}, headers,
        )

    # ─── Artworks ─────────────────────────────────────

    def list_artworks(self, headers, params=None):
        return self._request("GET", "/artworks", headers=headers, params=params)

    def get_artwork(self, artwork_id, headers):
        return self._request("GET", f"/artworks/{artwork_id}", headers=headers)

    def upload_artwork_image(self, artwork_id, payload, headers):
        return self._request(
            "POST", f"/artworks/{artwork_id}/images", payload, headers
        )

    def list_artwork_images(self, artwork_id, headers, params=None):
        return self._request(
            "GET", f"/artworks/{artwork_id}/images", headers=headers, params=params
        )

    def file_condition_report(self, artwork_id, payload, headers):
        return self._request(
            "POST", f"/artworks/{artwork_id}/condition-reports", payload, headers
        )

    def list_condition_reports(self, artwork_id, headers, params=None):
        return self._request(
            "GET", f"/artworks/{artwork_id}/condition-reports",
            headers=headers, params=params,
        )

    def promote_artwork(self, artwork_id, payload, headers):
        return self._request(
            "POST", f"/artworks/{artwork_id}/promotion", payload, headers
        )

    def file_installation_plan(self, artwork_id, payload, headers):
        return self._request(
            "POST", f"/artworks/{artwork_id}/installation-plan", payload, headers
        )

    def install_artwork(self, artwork_id, headers, payload=None):
        return self._request(
            "POST", f"/artworks/{artwork_id}/install",
            payload if payload is not None else {}, headers,
        )

    def deinstall_artwork(self, artwork_id, headers, payload=None):
        return self._request(
            "POST", f"/artworks/{artwork_id}/deinstall",
            payload if payload is not None else {}, headers,
        )

    def arrange_return_shipment(self, artwork_id, payload, headers):
        return self._request(
            "POST", f"/artworks/{artwork_id}/return-shipment", payload, headers
        )

    def complete_return(self, artwork_id, headers, payload=None):
        return self._request(
            "POST", f"/artworks/{artwork_id}/return-completion",
            payload if payload is not None else {}, headers,
        )

    # ─── Jurors ───────────────────────────────────────

    def create_juror(self, payload, headers):
        return self._request("POST", "/jurors", payload, headers)

    def get_juror(self, juror_id, headers):
        return self._request("GET", f"/jurors/{juror_id}", headers=headers)

    def confirm_juror(self, juror_id, headers, payload=None):
        return self._request(
            "POST", f"/jurors/{juror_id}/confirm",
            payload if payload is not None else {}, headers,
        )

    def file_conflict_declaration(self, juror_id, payload, headers):
        return self._request(
            "POST", f"/jurors/{juror_id}/conflict-declarations", payload, headers
        )

    def list_juror_conflict_declarations(self, juror_id, headers, params=None):
        return self._request(
            "GET", f"/jurors/{juror_id}/conflict-declarations",
            headers=headers, params=params,
        )

    def resign_juror(self, juror_id, headers, payload=None):
        return self._request(
            "POST", f"/jurors/{juror_id}/resign",
            payload if payload is not None else {}, headers,
        )

    def pay_juror_honorarium(self, juror_id, payload, headers):
        return self._request(
            "POST", f"/jurors/{juror_id}/honorarium-payment", payload, headers
        )

    # ─── Jury rounds, assignments and scores ──────────

    def create_jury_round(self, payload, headers):
        return self._request("POST", "/jury-rounds", payload, headers)

    def list_jury_rounds(self, headers, params=None):
        return self._request("GET", "/jury-rounds", headers=headers, params=params)

    def get_jury_round(self, jury_round_id, headers):
        return self._request("GET", f"/jury-rounds/{jury_round_id}", headers=headers)

    def set_jury_round_status(self, jury_round_id, payload, headers):
        return self._request(
            "POST", f"/jury-rounds/{jury_round_id}/status", payload, headers
        )

    def create_juror_assignment(self, jury_round_id, payload, headers):
        return self._request(
            "POST", f"/jury-rounds/{jury_round_id}/assignments", payload, headers
        )

    def list_juror_assignments(self, headers, params=None):
        return self._request(
            "GET", "/juror-assignments", headers=headers, params=params
        )

    def get_juror_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/juror-assignments/{assignment_id}", headers=headers
        )

    def cancel_juror_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST", f"/juror-assignments/{assignment_id}/cancel",
            payload if payload is not None else {}, headers,
        )

    def submit_score(self, jury_round_id, payload, headers):
        return self._request(
            "POST", f"/jury-rounds/{jury_round_id}/scores", payload, headers
        )

    def list_scores(self, headers, params=None):
        return self._request("GET", "/scores", headers=headers, params=params)

    def get_score(self, score_id, headers):
        return self._request("GET", f"/scores/{score_id}", headers=headers)

    # ─── Wall segments ────────────────────────────────

    def create_wall_segment(self, payload, headers):
        return self._request("POST", "/wall-segments", payload, headers)

    def list_wall_segments(self, headers, params=None):
        return self._request("GET", "/wall-segments", headers=headers, params=params)

    def get_wall_segment(self, wall_segment_id, headers):
        return self._request(
            "GET", f"/wall-segments/{wall_segment_id}", headers=headers
        )

    # ─── Sponsors ─────────────────────────────────────

    def create_sponsor(self, payload, headers):
        return self._request("POST", "/sponsors", payload, headers)

    def list_sponsors(self, headers, params=None):
        return self._request("GET", "/sponsors", headers=headers, params=params)

    def get_sponsor(self, sponsor_id, headers):
        return self._request("GET", f"/sponsors/{sponsor_id}", headers=headers)

    # ─── Awards ───────────────────────────────────────

    def create_award(self, payload, headers):
        return self._request("POST", "/awards", payload, headers)

    def list_awards(self, headers, params=None):
        return self._request("GET", "/awards", headers=headers, params=params)

    def get_award(self, award_id, headers):
        return self._request("GET", f"/awards/{award_id}", headers=headers)

    def confirm_award(self, award_id, payload, headers):
        return self._request("POST", f"/awards/{award_id}/confirm", payload, headers)

    def rescind_award(self, award_id, payload, headers):
        return self._request("POST", f"/awards/{award_id}/rescind", payload, headers)

    # ─── Sales ────────────────────────────────────────

    def create_sale(self, payload, headers):
        return self._request("POST", "/sales", payload, headers)

    def list_sales(self, headers, params=None):
        return self._request("GET", "/sales", headers=headers, params=params)

    def get_sale(self, sale_id, headers):
        return self._request("GET", f"/sales/{sale_id}", headers=headers)

    def invoice_sale(self, sale_id, headers, payload=None):
        return self._request(
            "POST", f"/sales/{sale_id}/invoice",
            payload if payload is not None else {}, headers,
        )

    def record_sale_payment(self, sale_id, payload, headers):
        return self._request("POST", f"/sales/{sale_id}/payment", payload, headers)

    def release_sale_payout(self, sale_id, payload, headers):
        return self._request("POST", f"/sales/{sale_id}/payout", payload, headers)

    def void_sale(self, sale_id, payload, headers):
        return self._request("POST", f"/sales/{sale_id}/void", payload, headers)

    # ─── Logical clock ────────────────────────────────

    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
