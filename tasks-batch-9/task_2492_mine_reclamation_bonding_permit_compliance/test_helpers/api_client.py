"""API client: one method per endpoint defined in the PRD.

Every path is mounted under the ``/mining`` umbrella prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/mining"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (PRD §2.4)
    # ------------------------------------------------------------------
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc}, headers,
        )

    # ------------------------------------------------------------------
    # Operators (PRD §3.1)
    # ------------------------------------------------------------------
    def create_operator(self, payload, headers):
        return self._request("POST", f"{PREFIX}/operators", payload, headers)

    def get_operator(self, operator_id, headers):
        return self._request("GET", f"{PREFIX}/operators/{operator_id}", headers=headers)

    def list_operators(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/operators", headers=headers, params=params)

    def patch_operator_financials(self, operator_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/operators/{operator_id}/financials", payload, headers
        )

    def run_financial_test(self, operator_id, headers):
        return self._request(
            "POST", f"{PREFIX}/operators/{operator_id}/financial-test", None, headers
        )

    def list_operator_permits(self, operator_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/operators/{operator_id}/permits", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Mine sites (PRD §3.1, §3.8)
    # ------------------------------------------------------------------
    def create_mine_site(self, payload, headers):
        return self._request("POST", f"{PREFIX}/mine-sites", payload, headers)

    def get_mine_site(self, site_id, headers):
        return self._request("GET", f"{PREFIX}/mine-sites/{site_id}", headers=headers)

    def list_mine_sites(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/mine-sites", headers=headers, params=params)

    def nominate_legacy_site(self, site_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/mine-sites/{site_id}/nominate-legacy", payload, headers
        )

    def award_legacy_funding(self, site_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/mine-sites/{site_id}/award-legacy-funding", payload, headers
        )

    def list_mine_site_permits(self, site_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/mine-sites/{site_id}/permits", headers=headers, params=params
        )

    def list_legacy_funding_queue(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/legacy-funding-queue", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Inspector profiles (PRD §3.1)
    # ------------------------------------------------------------------
    def create_inspector_profile(self, payload, headers):
        return self._request("POST", f"{PREFIX}/inspector-profiles", payload, headers)

    def get_inspector_profile(self, inspector_id, headers):
        return self._request(
            "GET", f"{PREFIX}/inspector-profiles/{inspector_id}", headers=headers
        )

    def list_inspector_profiles(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/inspector-profiles", headers=headers, params=params
        )

    def list_inspector_inspections(self, inspector_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/inspector-profiles/{inspector_id}/inspections",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Permits (PRD §3.2, §3.4)
    # ------------------------------------------------------------------
    def create_permit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"{PREFIX}/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/permits", headers=headers, params=params)

    def decide_permit(self, permit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/permits/{permit_id}/decide", payload, headers
        )

    def recalculate_bond(self, permit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/permits/{permit_id}/recalculate-bond", payload, headers
        )

    def cease_mining(self, permit_id, headers):
        return self._request(
            "POST", f"{PREFIX}/permits/{permit_id}/cease-mining", None, headers
        )

    def report_disturbance(self, permit_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/permits/{permit_id}/disturbance", payload, headers
        )

    def list_permit_estimates(self, permit_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/permits/{permit_id}/reclamation-cost-estimates",
            headers=headers, params=params,
        )

    def list_permit_instruments(self, permit_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/permits/{permit_id}/bond-instruments",
            headers=headers, params=params,
        )

    def list_permit_release_applications(self, permit_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/permits/{permit_id}/bond-release-applications",
            headers=headers, params=params,
        )

    def list_permit_inspections(self, permit_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/permits/{permit_id}/inspections",
            headers=headers, params=params,
        )

    def list_permit_violation_notices(self, permit_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/permits/{permit_id}/violation-notices",
            headers=headers, params=params,
        )

    def list_permit_revisions_for_permit(self, permit_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/permits/{permit_id}/permit-revisions",
            headers=headers, params=params,
        )

    def list_permit_forfeiture_proceedings(self, permit_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/permits/{permit_id}/forfeiture-proceedings",
            headers=headers, params=params,
        )

    def get_bond_summary(self, permit_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/permits/{permit_id}/bond-summary",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Reclamation cost estimates (PRD §3.2)
    # ------------------------------------------------------------------
    def create_estimate(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/reclamation-cost-estimates", payload, headers
        )

    def get_estimate(self, estimate_id, headers):
        return self._request(
            "GET", f"{PREFIX}/reclamation-cost-estimates/{estimate_id}", headers=headers
        )

    def list_estimates(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/reclamation-cost-estimates", headers=headers, params=params
        )

    def accept_estimate(self, estimate_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/reclamation-cost-estimates/{estimate_id}/accept",
            payload, headers,
        )

    # ------------------------------------------------------------------
    # Bond instruments (PRD §3.3)
    # ------------------------------------------------------------------
    def create_bond_instrument(self, payload, headers):
        return self._request("POST", f"{PREFIX}/bond-instruments", payload, headers)

    def get_bond_instrument(self, instrument_id, headers):
        return self._request(
            "GET", f"{PREFIX}/bond-instruments/{instrument_id}", headers=headers
        )

    def list_bond_instruments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/bond-instruments", headers=headers, params=params
        )

    def accept_bond_instrument(self, instrument_id, headers):
        return self._request(
            "POST", f"{PREFIX}/bond-instruments/{instrument_id}/accept", None, headers
        )

    # ------------------------------------------------------------------
    # Bond release applications (PRD §3.5)
    # ------------------------------------------------------------------
    def create_release_application(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/bond-release-applications", payload, headers
        )

    def get_release_application(self, application_id, headers):
        return self._request(
            "GET", f"{PREFIX}/bond-release-applications/{application_id}", headers=headers
        )

    def list_release_applications(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/bond-release-applications", headers=headers, params=params
        )

    def publish_notice(self, application_id, headers):
        return self._request(
            "POST", f"{PREFIX}/bond-release-applications/{application_id}/publish-notice",
            None, headers,
        )

    def file_public_comment(self, application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/bond-release-applications/{application_id}/comment",
            payload, headers,
        )

    def resolve_objections(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/bond-release-applications/{application_id}/resolve-objections",
            payload, headers,
        )

    def decide_release_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/bond-release-applications/{application_id}/decide",
            payload, headers,
        )

    def reinstate_release_application(self, application_id, headers):
        return self._request(
            "POST", f"{PREFIX}/bond-release-applications/{application_id}/reinstate",
            None, headers,
        )

    def rescind_release_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/bond-release-applications/{application_id}/rescind",
            payload, headers,
        )

    # ------------------------------------------------------------------
    # Inspections (PRD §3.6)
    # ------------------------------------------------------------------
    def create_inspection(self, payload, headers):
        return self._request("POST", f"{PREFIX}/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request(
            "GET", f"{PREFIX}/inspections/{inspection_id}", headers=headers
        )

    def list_inspections(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/inspections", headers=headers, params=params)

    def record_inspection_result(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/inspections/{inspection_id}/record-result", payload, headers
        )

    # ------------------------------------------------------------------
    # Violation notices (PRD §3.6)
    # ------------------------------------------------------------------
    def create_violation_notice(self, payload, headers):
        return self._request("POST", f"{PREFIX}/violation-notices", payload, headers)

    def get_violation_notice(self, notice_id, headers):
        return self._request(
            "GET", f"{PREFIX}/violation-notices/{notice_id}", headers=headers
        )

    def list_violation_notices(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/violation-notices", headers=headers, params=params
        )

    def order_cessation(self, notice_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/violation-notices/{notice_id}/order-cessation",
            payload, headers,
        )

    def abate_notice(self, notice_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/violation-notices/{notice_id}/abate", payload, headers
        )

    def vacate_notice(self, notice_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/violation-notices/{notice_id}/vacate", payload, headers
        )

    def assess_penalty(self, notice_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/violation-notices/{notice_id}/assess-penalty",
            payload, headers,
        )

    def pay_penalty(self, notice_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/violation-notices/{notice_id}/pay-penalty", payload, headers
        )

    # ------------------------------------------------------------------
    # Permit revisions (PRD §3.4)
    # ------------------------------------------------------------------
    def create_permit_revision(self, payload, headers):
        return self._request("POST", f"{PREFIX}/permit-revisions", payload, headers)

    def get_permit_revision(self, revision_id, headers):
        return self._request(
            "GET", f"{PREFIX}/permit-revisions/{revision_id}", headers=headers
        )

    def list_permit_revisions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/permit-revisions", headers=headers, params=params
        )

    def request_revision_info(self, revision_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/permit-revisions/{revision_id}/request-info",
            payload, headers,
        )

    def resubmit_revision(self, revision_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/permit-revisions/{revision_id}/resubmit", payload, headers
        )

    def decide_permit_revision(self, revision_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/permit-revisions/{revision_id}/decide", payload, headers
        )

    # ------------------------------------------------------------------
    # Forfeiture proceedings (PRD §3.7)
    # ------------------------------------------------------------------
    def create_forfeiture_proceeding(self, payload, headers):
        return self._request("POST", f"{PREFIX}/forfeiture-proceedings", payload, headers)

    def get_forfeiture_proceeding(self, proceeding_id, headers):
        return self._request(
            "GET", f"{PREFIX}/forfeiture-proceedings/{proceeding_id}", headers=headers
        )

    def list_forfeiture_proceedings(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/forfeiture-proceedings", headers=headers, params=params
        )

    def contest_forfeiture(self, proceeding_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/forfeiture-proceedings/{proceeding_id}/contest",
            payload, headers,
        )

    def finalize_forfeiture(self, proceeding_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/forfeiture-proceedings/{proceeding_id}/finalize",
            payload, headers,
        )

    def record_state_reclamation(self, proceeding_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/forfeiture-proceedings/{proceeding_id}/record-state-reclamation",
            payload, headers,
        )


api_client = ApiClient()
