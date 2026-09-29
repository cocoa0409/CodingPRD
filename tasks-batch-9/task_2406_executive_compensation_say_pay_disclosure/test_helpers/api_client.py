"""API client: one method per endpoint defined in the PRD (api prefix /exec-comp)."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/exec-comp"


class ApiClient(GenericApiClient):
    """Typed wrapper over every endpoint in the PRD's endpoint table."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_current_utc(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Company
    # ------------------------------------------------------------------
    def create_company(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/companies", payload, headers)

    def get_company(self, company_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/companies/{company_id}", headers=headers)

    def refresh_market_data(
        self, company_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/companies/{company_id}/market-data", payload, headers
        )

    def list_company_peer_groups(
        self, company_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/companies/{company_id}/peer-groups", headers=headers, params=params
        )

    def list_company_peer_memberships(
        self, company_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/companies/{company_id}/peer-memberships",
            headers=headers,
            params=params,
        )

    def list_company_executives(
        self, company_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/companies/{company_id}/executives", headers=headers, params=params
        )

    def list_company_restatement_events(
        self, company_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/companies/{company_id}/restatement-events",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Executive
    # ------------------------------------------------------------------
    def create_executive(
        self, company_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/companies/{company_id}/executives", payload, headers
        )

    # ------------------------------------------------------------------
    # PeerGroup / PeerGroupMember
    # ------------------------------------------------------------------
    def create_peer_group(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/peer-groups", payload, headers)

    def get_peer_group(self, peer_group_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/peer-groups/{peer_group_id}", headers=headers)

    def add_peer_group_member(
        self, peer_group_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/peer-groups/{peer_group_id}/members", payload, headers
        )

    def list_peer_group_members(
        self, peer_group_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/peer-groups/{peer_group_id}/members", headers=headers, params=params
        )

    def exclude_peer_group_member(
        self, member_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/peer-group-members/{member_id}/exclude", payload, headers
        )

    def screen_peer_group(
        self, peer_group_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/peer-groups/{peer_group_id}/screen", payload or {}, headers
        )

    def approve_peer_group(
        self, peer_group_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/peer-groups/{peer_group_id}/approve", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # PayProgram
    # ------------------------------------------------------------------
    def create_pay_program(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/pay-programs", payload, headers)

    def list_pay_programs(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/pay-programs", headers=headers, params=params)

    def get_pay_program(self, program_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/pay-programs/{program_id}", headers=headers)

    def reallocate_pay_mix(
        self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/pay-programs/{program_id}/mix-reallocation", payload, headers
        )

    def get_pay_for_performance(self, program_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/pay-programs/{program_id}/pay-for-performance", headers=headers
        )

    def approve_pay_program(
        self, program_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/pay-programs/{program_id}/approve", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # IncentiveMetric
    # ------------------------------------------------------------------
    def create_incentive_metric(
        self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/pay-programs/{program_id}/incentive-metrics", payload, headers
        )

    def list_incentive_metrics(
        self, program_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/pay-programs/{program_id}/incentive-metrics",
            headers=headers,
            params=params,
        )

    def adjust_incentive_metric(
        self, metric_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/incentive-metrics/{metric_id}/adjustments", payload, headers
        )

    def submit_metric_result(
        self, metric_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/incentive-metrics/{metric_id}/results", payload, headers
        )

    def certify_metric_result(
        self, metric_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{PREFIX}/incentive-metrics/{metric_id}/certify-result",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # PayoutAward
    # ------------------------------------------------------------------
    def create_payout_award(
        self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/pay-programs/{program_id}/payout-awards", payload, headers
        )

    def list_payout_awards(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/payout-awards", headers=headers, params=params)

    def get_payout_award(self, award_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/payout-awards/{award_id}", headers=headers)

    def settle_payout_award(
        self, award_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/payout-awards/{award_id}/settlement", payload, headers
        )

    # ------------------------------------------------------------------
    # CdaDraft
    # ------------------------------------------------------------------
    def create_cda_draft(
        self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/pay-programs/{program_id}/cda-drafts", payload, headers
        )

    def list_cda_drafts(
        self, program_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/pay-programs/{program_id}/cda-drafts", headers=headers, params=params
        )

    def submit_cda_review(
        self, draft_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/cda-drafts/{draft_id}/submit-review", payload or {}, headers
        )

    def request_cda_revision(
        self, draft_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/cda-drafts/{draft_id}/request-revision", payload or {}, headers
        )

    def legal_clear_cda_draft(
        self, draft_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/cda-drafts/{draft_id}/legal-clear", payload or {}, headers
        )

    def file_cda_draft(
        self, draft_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/cda-drafts/{draft_id}/file", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # ProxyAdvisorScreen
    # ------------------------------------------------------------------
    def create_proxy_advisor_screen(
        self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/pay-programs/{program_id}/proxy-advisor-screens",
            payload,
            headers,
        )

    def list_proxy_advisor_screens(
        self, program_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/pay-programs/{program_id}/proxy-advisor-screens",
            headers=headers,
            params=params,
        )

    def rerun_proxy_advisor_screen(
        self, screen_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/proxy-advisor-screens/{screen_id}/rerun", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # OutreachEngagement
    # ------------------------------------------------------------------
    def create_outreach_engagement(
        self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/pay-programs/{program_id}/outreach-engagements", payload, headers
        )

    def list_outreach_engagements(
        self, program_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/pay-programs/{program_id}/outreach-engagements",
            headers=headers,
            params=params,
        )

    def schedule_outreach_engagement(
        self, engagement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/outreach-engagements/{engagement_id}/schedule", payload, headers
        )

    def hold_outreach_engagement(
        self, engagement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/outreach-engagements/{engagement_id}/hold", payload, headers
        )

    # ------------------------------------------------------------------
    # Say-on-pay vote / remediation
    # ------------------------------------------------------------------
    def certify_vote(self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/pay-programs/{program_id}/vote-certification", payload, headers
        )

    def remediate_pay_program(
        self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/pay-programs/{program_id}/remediation", payload, headers
        )

    # ------------------------------------------------------------------
    # RestatementEvent / ClawbackDetermination
    # ------------------------------------------------------------------
    def create_restatement_event(
        self, company_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/companies/{company_id}/restatement-events", payload, headers
        )

    def analyze_restatement_event(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/restatement-events/{event_id}/analyze", payload, headers
        )

    def order_restatement_recovery(
        self, event_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PREFIX}/restatement-events/{event_id}/order-recovery", payload or {}, headers
        )

    def list_clawback_determinations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/clawback-determinations", headers=headers, params=params
        )

    def get_clawback_determination(self, determination_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/clawback-determinations/{determination_id}", headers=headers
        )

    def acknowledge_clawback_determination(
        self, determination_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{PREFIX}/clawback-determinations/{determination_id}/acknowledge",
            payload or {},
            headers,
        )

    def recover_clawback_determination(
        self, determination_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{PREFIX}/clawback-determinations/{determination_id}/recover",
            payload or {},
            headers,
        )

    def reverse_clawback_recovery(
        self, determination_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/clawback-determinations/{determination_id}/reverse-recovery",
            payload,
            headers,
        )


api_client = ApiClient()
