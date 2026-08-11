"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- CaptiveEntity ---
    def create_captive(self, payload, headers):
        return self._request("POST", "/api/captives", payload, headers)

    def list_captives(self, headers, params=None):
        return self._request("GET", "/api/captives", headers=headers, params=params)

    def get_captive(self, captive_id, headers):
        return self._request("GET", f"/api/captives/{captive_id}", headers=headers)

    def activate_captive(self, captive_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/activate", {}, headers)

    def suspend_captive(self, captive_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/suspend", {}, headers)

    def reinstate_captive(self, captive_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/reinstate", {}, headers)

    def dissolve_captive(self, captive_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/dissolve", {}, headers)

    # --- DomicileFiling ---
    def create_domicile_filing(self, captive_id, payload, headers):
        return self._request("POST", f"/api/captives/{captive_id}/domicile-filings", payload, headers)

    def list_domicile_filings(self, captive_id, headers, params=None):
        return self._request("GET", f"/api/captives/{captive_id}/domicile-filings", headers=headers, params=params)

    def get_domicile_filing(self, captive_id, filing_id, headers):
        return self._request("GET", f"/api/captives/{captive_id}/domicile-filings/{filing_id}", headers=headers)

    def submit_filing(self, captive_id, filing_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/domicile-filings/{filing_id}/submit", {}, headers)

    def acknowledge_filing(self, captive_id, filing_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/domicile-filings/{filing_id}/acknowledge", {}, headers)

    def approve_filing(self, captive_id, filing_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/domicile-filings/{filing_id}/approve", {}, headers)

    def reject_filing(self, captive_id, filing_id, payload, headers):
        return self._request("POST", f"/api/captives/{captive_id}/domicile-filings/{filing_id}/reject", payload, headers)

    def withdraw_filing(self, captive_id, filing_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/domicile-filings/{filing_id}/withdraw", {}, headers)

    # --- InsuranceProgram ---
    def create_program(self, captive_id, payload, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs", payload, headers)

    def list_programs(self, captive_id, headers, params=None):
        return self._request("GET", f"/api/captives/{captive_id}/programs", headers=headers, params=params)

    def get_program(self, captive_id, program_id, headers):
        return self._request("GET", f"/api/captives/{captive_id}/programs/{program_id}", headers=headers)

    def quote_program(self, captive_id, program_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/quote", {}, headers)

    def bind_program(self, captive_id, program_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/bind", {}, headers)

    def activate_program(self, captive_id, program_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/activate", {}, headers)

    def enter_runoff_program(self, captive_id, program_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/enter-runoff", {}, headers)

    def close_program(self, captive_id, program_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/close", {}, headers)

    def cancel_program(self, captive_id, program_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/cancel", {}, headers)

    # --- FrontingArrangement ---
    def create_fronting(self, captive_id, program_id, payload, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/fronting", payload, headers)

    def list_frontings(self, captive_id, program_id, headers, params=None):
        return self._request("GET", f"/api/captives/{captive_id}/programs/{program_id}/fronting", headers=headers, params=params)

    def get_fronting(self, captive_id, program_id, fronting_id, headers):
        return self._request("GET", f"/api/captives/{captive_id}/programs/{program_id}/fronting/{fronting_id}", headers=headers)

    def agree_fronting_terms(self, captive_id, program_id, fronting_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/fronting/{fronting_id}/agree-terms", {}, headers)

    def post_fronting_collateral(self, captive_id, program_id, fronting_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/fronting/{fronting_id}/post-collateral", {}, headers)

    def activate_fronting(self, captive_id, program_id, fronting_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/fronting/{fronting_id}/activate", {}, headers)

    def terminate_fronting(self, captive_id, program_id, fronting_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/fronting/{fronting_id}/terminate", {}, headers)

    # --- CollateralPosting ---
    def create_collateral(self, captive_id, program_id, fronting_id, payload, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/fronting/{fronting_id}/collateral", payload, headers)

    def list_collateral(self, captive_id, program_id, fronting_id, headers, params=None):
        return self._request("GET", f"/api/captives/{captive_id}/programs/{program_id}/fronting/{fronting_id}/collateral", headers=headers, params=params)

    def get_collateral(self, captive_id, program_id, fronting_id, collateral_id, headers):
        return self._request("GET", f"/api/captives/{captive_id}/programs/{program_id}/fronting/{fronting_id}/collateral/{collateral_id}", headers=headers)

    def verify_collateral(self, captive_id, program_id, fronting_id, collateral_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/fronting/{fronting_id}/collateral/{collateral_id}/verify", {}, headers)

    # --- OperatingUnit ---
    def create_operating_unit(self, captive_id, payload, headers):
        return self._request("POST", f"/api/captives/{captive_id}/operating-units", payload, headers)

    def list_operating_units(self, captive_id, headers, params=None):
        return self._request("GET", f"/api/captives/{captive_id}/operating-units", headers=headers, params=params)

    def get_operating_unit(self, captive_id, unit_id, headers):
        return self._request("GET", f"/api/captives/{captive_id}/operating-units/{unit_id}", headers=headers)

    # --- PremiumAllocation ---
    def create_allocation(self, captive_id, program_id, payload, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/allocations", payload, headers)

    def list_allocations(self, captive_id, program_id, headers, params=None):
        return self._request("GET", f"/api/captives/{captive_id}/programs/{program_id}/allocations", headers=headers, params=params)

    def get_allocation(self, captive_id, program_id, alloc_id, headers):
        return self._request("GET", f"/api/captives/{captive_id}/programs/{program_id}/allocations/{alloc_id}", headers=headers)

    def audit_allocation(self, captive_id, program_id, alloc_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/allocations/{alloc_id}/audit", {}, headers)

    def finalize_allocation(self, captive_id, program_id, alloc_id, payload, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/allocations/{alloc_id}/finalize", payload, headers)

    def dispute_allocation(self, captive_id, program_id, alloc_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/allocations/{alloc_id}/dispute", {}, headers)

    def resolve_dispute_allocation(self, captive_id, program_id, alloc_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/allocations/{alloc_id}/resolve-dispute", {}, headers)

    def cancel_allocation(self, captive_id, program_id, alloc_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/allocations/{alloc_id}/cancel", {}, headers)

    # --- Claim ---
    def create_claim(self, captive_id, program_id, payload, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/claims", payload, headers)

    def list_claims(self, captive_id, program_id, headers, params=None):
        return self._request("GET", f"/api/captives/{captive_id}/programs/{program_id}/claims", headers=headers, params=params)

    def get_claim(self, captive_id, program_id, claim_id, headers):
        return self._request("GET", f"/api/captives/{captive_id}/programs/{program_id}/claims/{claim_id}", headers=headers)

    def acknowledge_claim(self, captive_id, program_id, claim_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/claims/{claim_id}/acknowledge", {}, headers)

    def investigate_claim(self, captive_id, program_id, claim_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/claims/{claim_id}/investigate", {}, headers)

    def set_claim_reserve(self, captive_id, program_id, claim_id, payload, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/claims/{claim_id}/set-reserve", payload, headers)

    def settle_claim(self, captive_id, program_id, claim_id, payload, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/claims/{claim_id}/settle", payload, headers)

    def deny_claim(self, captive_id, program_id, claim_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/claims/{claim_id}/deny", {}, headers)

    def close_claim_without_payment(self, captive_id, program_id, claim_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/claims/{claim_id}/close-without-payment", {}, headers)

    # --- TPAAssignment ---
    def create_tpa(self, captive_id, program_id, claim_id, payload, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/claims/{claim_id}/tpa", payload, headers)

    def list_tpas(self, captive_id, program_id, claim_id, headers, params=None):
        return self._request("GET", f"/api/captives/{captive_id}/programs/{program_id}/claims/{claim_id}/tpa", headers=headers, params=params)

    def get_tpa(self, captive_id, program_id, claim_id, tpa_id, headers):
        return self._request("GET", f"/api/captives/{captive_id}/programs/{program_id}/claims/{claim_id}/tpa/{tpa_id}", headers=headers)

    def suspend_tpa(self, captive_id, program_id, claim_id, tpa_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/claims/{claim_id}/tpa/{tpa_id}/suspend", {}, headers)

    def reinstate_tpa(self, captive_id, program_id, claim_id, tpa_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/claims/{claim_id}/tpa/{tpa_id}/reinstate", {}, headers)

    def terminate_tpa(self, captive_id, program_id, claim_id, tpa_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/claims/{claim_id}/tpa/{tpa_id}/terminate", {}, headers)

    # --- ActuarialReserve ---
    def create_reserve(self, captive_id, program_id, payload, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/reserves", payload, headers)

    def list_reserves(self, captive_id, program_id, headers, params=None):
        return self._request("GET", f"/api/captives/{captive_id}/programs/{program_id}/reserves", headers=headers, params=params)

    def get_reserve(self, captive_id, program_id, reserve_id, headers):
        return self._request("GET", f"/api/captives/{captive_id}/programs/{program_id}/reserves/{reserve_id}", headers=headers)

    def review_reserve(self, captive_id, program_id, reserve_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/reserves/{reserve_id}/review", {}, headers)

    def certify_reserve(self, captive_id, program_id, reserve_id, payload, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/reserves/{reserve_id}/certify", payload, headers)

    def file_reserve(self, captive_id, program_id, reserve_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/programs/{program_id}/reserves/{reserve_id}/file", {}, headers)

    # --- AnnualStatement ---
    def create_annual_statement(self, captive_id, payload, headers):
        return self._request("POST", f"/api/captives/{captive_id}/annual-statements", payload, headers)

    def list_annual_statements(self, captive_id, headers, params=None):
        return self._request("GET", f"/api/captives/{captive_id}/annual-statements", headers=headers, params=params)

    def get_annual_statement(self, captive_id, statement_id, headers):
        return self._request("GET", f"/api/captives/{captive_id}/annual-statements/{statement_id}", headers=headers)

    def submit_statement_for_review(self, captive_id, statement_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/annual-statements/{statement_id}/submit-for-review", {}, headers)

    def board_approve_statement(self, captive_id, statement_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/annual-statements/{statement_id}/board-approve", {}, headers)

    def file_statement(self, captive_id, statement_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/annual-statements/{statement_id}/file", {}, headers)

    def amend_statement(self, captive_id, statement_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/annual-statements/{statement_id}/amend", {}, headers)

    # --- BoardMeeting ---
    def create_board_meeting(self, captive_id, payload, headers):
        return self._request("POST", f"/api/captives/{captive_id}/board-meetings", payload, headers)

    def list_board_meetings(self, captive_id, headers, params=None):
        return self._request("GET", f"/api/captives/{captive_id}/board-meetings", headers=headers, params=params)

    def get_board_meeting(self, captive_id, meeting_id, headers):
        return self._request("GET", f"/api/captives/{captive_id}/board-meetings/{meeting_id}", headers=headers)

    def convene_meeting(self, captive_id, meeting_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/board-meetings/{meeting_id}/convene", {}, headers)

    def draft_minutes(self, captive_id, meeting_id, payload, headers):
        return self._request("POST", f"/api/captives/{captive_id}/board-meetings/{meeting_id}/draft-minutes", payload, headers)

    def approve_minutes(self, captive_id, meeting_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/board-meetings/{meeting_id}/approve-minutes", {}, headers)

    def file_meeting(self, captive_id, meeting_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/board-meetings/{meeting_id}/file", {}, headers)

    def cancel_meeting(self, captive_id, meeting_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/board-meetings/{meeting_id}/cancel", {}, headers)

    # --- TaxPosition ---
    def create_tax_position(self, captive_id, payload, headers):
        return self._request("POST", f"/api/captives/{captive_id}/tax-positions", payload, headers)

    def list_tax_positions(self, captive_id, headers, params=None):
        return self._request("GET", f"/api/captives/{captive_id}/tax-positions", headers=headers, params=params)

    def get_tax_position(self, captive_id, position_id, headers):
        return self._request("GET", f"/api/captives/{captive_id}/tax-positions/{position_id}", headers=headers)

    def analyze_tax_position(self, captive_id, position_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/tax-positions/{position_id}/analyze", {}, headers)

    def issue_opinion(self, captive_id, position_id, payload, headers):
        return self._request("POST", f"/api/captives/{captive_id}/tax-positions/{position_id}/issue-opinion", payload, headers)

    def file_tax_position(self, captive_id, position_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/tax-positions/{position_id}/file", {}, headers)

    def challenge_tax_position(self, captive_id, position_id, headers):
        return self._request("POST", f"/api/captives/{captive_id}/tax-positions/{position_id}/challenge", {}, headers)

    # --- AuditLog ---
    def list_audit_logs(self, captive_id, headers, params=None):
        return self._request("GET", f"/api/captives/{captive_id}/audit-logs", headers=headers, params=params)

    def get_audit_log(self, captive_id, log_id, headers):
        return self._request("GET", f"/api/captives/{captive_id}/audit-logs/{log_id}", headers=headers)

    # --- Flat GET endpoints ---
    def get_domicile_filing_flat(self, filing_id, headers):
        return self._request("GET", f"/api/domicile-filings/{filing_id}", headers=headers)

    def get_program_flat(self, program_id, headers):
        return self._request("GET", f"/api/programs/{program_id}", headers=headers)

    def get_fronting_flat(self, fronting_id, headers):
        return self._request("GET", f"/api/fronting-arrangements/{fronting_id}", headers=headers)

    def get_collateral_flat(self, collateral_id, headers):
        return self._request("GET", f"/api/collateral-postings/{collateral_id}", headers=headers)

    def get_operating_unit_flat(self, unit_id, headers):
        return self._request("GET", f"/api/operating-units/{unit_id}", headers=headers)

    def get_allocation_flat(self, alloc_id, headers):
        return self._request("GET", f"/api/premium-allocations/{alloc_id}", headers=headers)

    def get_claim_flat(self, claim_id, headers):
        return self._request("GET", f"/api/claims/{claim_id}", headers=headers)

    def get_tpa_flat(self, tpa_id, headers):
        return self._request("GET", f"/api/tpa-assignments/{tpa_id}", headers=headers)

    def get_reserve_flat(self, reserve_id, headers):
        return self._request("GET", f"/api/actuarial-reserves/{reserve_id}", headers=headers)

    def get_annual_statement_flat(self, statement_id, headers):
        return self._request("GET", f"/api/annual-statements/{statement_id}", headers=headers)

    def get_board_meeting_flat(self, meeting_id, headers):
        return self._request("GET", f"/api/board-meetings/{meeting_id}", headers=headers)

    def get_tax_position_flat(self, position_id, headers):
        return self._request("GET", f"/api/tax-positions/{position_id}", headers=headers)

    def get_audit_log_flat(self, log_id, headers):
        return self._request("GET", f"/api/audit-logs/{log_id}", headers=headers)

    # --- Flat filtered-list endpoints ---
    def list_domicile_filings_flat(self, headers, params=None):
        return self._request("GET", "/api/domicile-filings", headers=headers, params=params)

    def list_programs_flat(self, headers, params=None):
        return self._request("GET", "/api/programs", headers=headers, params=params)

    def list_frontings_flat(self, headers, params=None):
        return self._request("GET", "/api/fronting-arrangements", headers=headers, params=params)

    def list_collateral_flat(self, headers, params=None):
        return self._request("GET", "/api/collateral-postings", headers=headers, params=params)

    def list_operating_units_flat(self, headers, params=None):
        return self._request("GET", "/api/operating-units", headers=headers, params=params)

    def list_allocations_flat(self, headers, params=None):
        return self._request("GET", "/api/premium-allocations", headers=headers, params=params)

    def list_claims_flat(self, headers, params=None):
        return self._request("GET", "/api/claims", headers=headers, params=params)

    def list_tpas_flat(self, headers, params=None):
        return self._request("GET", "/api/tpa-assignments", headers=headers, params=params)

    def list_reserves_flat(self, headers, params=None):
        return self._request("GET", "/api/actuarial-reserves", headers=headers, params=params)

    def list_annual_statements_flat(self, headers, params=None):
        return self._request("GET", "/api/annual-statements", headers=headers, params=params)

    def list_board_meetings_flat(self, headers, params=None):
        return self._request("GET", "/api/board-meetings", headers=headers, params=params)

    def list_tax_positions_flat(self, headers, params=None):
        return self._request("GET", "/api/tax-positions", headers=headers, params=params)

    def list_audit_logs_flat(self, headers, params=None):
        return self._request("GET", "/api/audit-logs", headers=headers, params=params)

    # --- Test-driving endpoint ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
