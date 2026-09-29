"""One method per endpoint of the Fair Trade Certification API (PRD section 4).

Every endpoint is mounted beneath the ``/fairtrade`` prefix. Methods return the
raw ``requests.Response`` so tests can assert on status codes as well as
bodies.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/fairtrade"


class ApiClient(GenericApiClient):
    """Domain client for the Fair Trade Certification API."""

    # -- the deterministic logical clock (PRD 2.4) -------------------------

    def set_clock(
        self, to_iso8601: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )

    def set_clock_raw(
        self, payload: Any, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # -- certificate holders ----------------------------------------------

    def create_holder(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/certificate-holders", payload, headers)

    def certify_holder(
        self, holder_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/certificate-holders/{holder_id}/certify",
            payload if payload is not None else {},
            headers,
        )

    def suspend_holder(
        self, holder_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/certificate-holders/{holder_id}/suspend", payload, headers
        )

    def reinstate_holder(
        self, holder_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/certificate-holders/{holder_id}/reinstate",
            payload if payload is not None else {},
            headers,
        )

    def transition_holder(
        self, holder_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/certificate-holders/{holder_id}/transition",
            payload if payload is not None else {},
            headers,
        )

    def decertify_holder(
        self, holder_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/certificate-holders/{holder_id}/decertify", payload, headers
        )

    def issue_label_license(
        self, holder_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/certificate-holders/{holder_id}/label-license",
            payload,
            headers,
        )

    def pay_license_fee(
        self, holder_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/certificate-holders/{holder_id}/label-license/payments",
            payload,
            headers,
        )

    def get_holder(self, holder_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/certificate-holders/{holder_id}", None, headers)

    def list_holders(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/certificate-holders", params, headers)

    def get_traceability_summary(
        self, holder_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/certificate-holders/{holder_id}/traceability-summary",
            None,
            headers,
        )

    # -- supply chain nodes -------------------------------------------------

    def create_node(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/supply-chain-nodes", payload, headers)

    def declare_harvest(
        self, node_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/supply-chain-nodes/{node_id}/harvest-declarations",
            payload,
            headers,
        )

    def get_node(self, node_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/supply-chain-nodes/{node_id}", None, headers)

    def list_nodes(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/supply-chain-nodes", params, headers)

    # -- premium committees, funds and the ledger ---------------------------

    def create_committee(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/premium-committees", payload, headers)

    def get_committee(self, committee_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/premium-committees/{committee_id}", None, headers)

    def list_holder_committees(
        self, holder_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/certificate-holders/{holder_id}/premium-committees",
            params,
            headers,
        )

    def list_holder_funds(
        self, holder_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/certificate-holders/{holder_id}/premium-funds", params, headers
        )

    def get_ledger_entry(self, entry_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/premium-ledger-entries/{entry_id}", None, headers
        )

    def list_ledger_entries(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/premium-ledger-entries", params, headers)

    # -- trade transactions -------------------------------------------------

    def create_trade(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/trade-transactions", payload, headers)

    def verify_trade(
        self, trade_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/trade-transactions/{trade_id}/verify", payload, headers
        )

    def settle_trade(
        self, trade_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/trade-transactions/{trade_id}/settle",
            payload if payload is not None else {},
            headers,
        )

    def void_trade(
        self, trade_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/trade-transactions/{trade_id}/void", payload, headers
        )

    def get_trade(self, trade_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/trade-transactions/{trade_id}", None, headers)

    def list_trades(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/trade-transactions", params, headers)

    # -- volume reports -----------------------------------------------------

    def create_volume_report(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/volume-reports", payload, headers)

    def reconcile_volume_report(
        self, report_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/volume-reports/{report_id}/reconcile", payload, headers
        )

    def get_volume_report(self, report_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/volume-reports/{report_id}", None, headers)

    def list_holder_volume_reports(
        self, holder_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/certificate-holders/{holder_id}/volume-reports", params, headers
        )

    # -- premium use proposals and ballots ----------------------------------

    def create_proposal(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/premium-use-proposals", payload, headers)

    def open_vote(
        self, proposal_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/premium-use-proposals/{proposal_id}/open-vote",
            payload if payload is not None else {},
            headers,
        )

    def cast_vote(
        self, proposal_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/premium-use-proposals/{proposal_id}/votes", payload, headers
        )

    def close_vote(
        self, proposal_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/premium-use-proposals/{proposal_id}/close-vote",
            payload if payload is not None else {},
            headers,
        )

    def revise_proposal(
        self, proposal_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/premium-use-proposals/{proposal_id}/revise", payload, headers
        )

    def disburse_proposal(
        self, proposal_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/premium-use-proposals/{proposal_id}/disburse",
            payload if payload is not None else {},
            headers,
        )

    def cancel_proposal(
        self, proposal_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/premium-use-proposals/{proposal_id}/cancel",
            payload if payload is not None else {},
            headers,
        )

    def get_proposal(self, proposal_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/premium-use-proposals/{proposal_id}", None, headers
        )

    def list_committee_proposals(
        self, committee_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/premium-committees/{committee_id}/premium-use-proposals",
            params,
            headers,
        )

    def list_proposal_votes(
        self, proposal_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/premium-use-proposals/{proposal_id}/votes", params, headers
        )

    # -- audits, findings and corrective action ----------------------------

    def create_audit(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/audits", payload, headers)

    def start_audit(
        self, audit_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/audits/{audit_id}/start",
            payload if payload is not None else {},
            headers,
        )

    def create_nonconformity(
        self, audit_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/audits/{audit_id}/nonconformities", payload, headers
        )

    def close_audit(
        self, audit_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/audits/{audit_id}/close",
            payload if payload is not None else {},
            headers,
        )

    def submit_cap(
        self, nonconformity_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/nonconformities/{nonconformity_id}/cap-submissions",
            payload,
            headers,
        )

    def review_cap(
        self, nonconformity_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/nonconformities/{nonconformity_id}/cap-review", payload, headers
        )

    def get_audit(self, audit_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/audits/{audit_id}", None, headers)

    def list_holder_audits(
        self, holder_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/certificate-holders/{holder_id}/audits", params, headers
        )

    def get_nonconformity(
        self, nonconformity_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/nonconformities/{nonconformity_id}", None, headers
        )

    def list_audit_nonconformities(
        self, audit_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/audits/{audit_id}/nonconformities", params, headers
        )

    # -- label licensing and on-pack mark usage ----------------------------

    def create_mark_usage_request(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/mark-usage-requests", payload, headers)

    def decide_mark_usage_request(
        self, request_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/mark-usage-requests/{request_id}/decide", payload, headers
        )

    def get_mark_usage_request(
        self, request_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/mark-usage-requests/{request_id}", None, headers)

    def list_holder_mark_usage_requests(
        self, holder_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{PREFIX}/certificate-holders/{holder_id}/mark-usage-requests",
            params,
            headers,
        )

    # -- the compliance sweep ----------------------------------------------

    def run_compliance_sweep(
        self, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/compliance-sweeps",
            payload if payload is not None else {},
            headers,
        )
