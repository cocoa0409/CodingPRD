"""Typed HTTP client: one method per declared endpoint.

Every method returns the raw `requests.Response` so a caller may hand it to
either `validate_success` or `validate_error`. Headers are always explicit --
there is no implicit acting identity.
"""

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient


class PrtApiClient:
    """Thin, endpoint-shaped wrapper over the generic HTTP client."""

    def __init__(self, base_url: Optional[str] = None) -> None:
        self._client = GenericApiClient(base_url=base_url)

    # -- primitives ---------------------------------------------------------

    def get(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._client.get(path, headers=headers, params=params)

    def post(
        self,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._client.post(path, json=payload, headers=headers)

    # -- logical clock ------------------------------------------------------

    def set_clock(
        self, current_utc: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/_clock/set_current_utc", {"current_utc": current_utc}, headers)

    # -- pension plans ------------------------------------------------------

    def create_plan(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/prt/plans", payload, headers)

    def get_plan(
        self, plan_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get("/prt/plans/{}".format(plan_id), headers)

    def get_funded_status(
        self, plan_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get("/prt/plans/{}/funded-status".format(plan_id), headers)

    def post_valuation_update(
        self, plan_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/prt/plans/{}/valuation-updates".format(plan_id), payload, headers)

    def post_settlement_amendment(
        self, plan_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/prt/plans/{}/settlement-amendment".format(plan_id), payload, headers)

    def post_termination_filing(
        self, plan_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/prt/plans/{}/termination-filing".format(plan_id), payload, headers)

    def post_filing_review(
        self, plan_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/prt/plans/{}/filing-review".format(plan_id), payload, headers)

    # -- de-risking strategies ---------------------------------------------

    def create_strategy(
        self, plan_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/prt/plans/{}/strategies".format(plan_id), payload, headers)

    def list_strategies(
        self,
        plan_id: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self.get("/prt/plans/{}/strategies".format(plan_id), headers, params)

    def post_strategy_submission(
        self,
        strategy_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            "/prt/strategies/{}/submission".format(strategy_id), payload or {}, headers
        )

    def post_strategy_decision(
        self, strategy_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/prt/strategies/{}/decision".format(strategy_id), payload, headers)

    # -- participant records -----------------------------------------------

    def create_participant(
        self, plan_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/prt/plans/{}/participants".format(plan_id), payload, headers)

    def get_participant(
        self, participant_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get("/prt/participants/{}".format(participant_id), headers)

    def list_participants(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self.get("/prt/participants", headers, params)

    def post_address_search(
        self, participant_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(
            "/prt/participants/{}/address-searches".format(participant_id), payload, headers
        )

    def post_mortality_check(
        self, participant_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(
            "/prt/participants/{}/mortality-checks".format(participant_id), payload, headers
        )

    # -- benefit audits ----------------------------------------------------

    def create_benefit_audit(
        self, participant_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(
            "/prt/participants/{}/benefit-audits".format(participant_id), payload, headers
        )

    def list_benefit_audits(
        self,
        participant_id: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self.get(
            "/prt/participants/{}/benefit-audits".format(participant_id), headers, params
        )

    def post_audit_resolution(
        self, audit_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/prt/benefit-audits/{}/resolution".format(audit_id), payload, headers)

    # -- lump sum windows --------------------------------------------------

    def create_window(
        self, plan_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/prt/plans/{}/lump-sum-windows".format(plan_id), payload, headers)

    def list_windows(
        self,
        plan_id: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self.get("/prt/plans/{}/lump-sum-windows".format(plan_id), headers, params)

    def post_window_opening(
        self,
        window_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post("/prt/lump-sum-windows/{}/opening".format(window_id), payload or {}, headers)

    def post_window_closing(
        self,
        window_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post("/prt/lump-sum-windows/{}/closing".format(window_id), payload or {}, headers)

    def post_window_settlement(
        self,
        window_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            "/prt/lump-sum-windows/{}/settlement".format(window_id), payload or {}, headers
        )

    # -- participant elections ---------------------------------------------

    def get_election(
        self, election_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get("/prt/elections/{}".format(election_id), headers)

    def list_elections(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self.get("/prt/elections", headers, params)

    def post_election(
        self, election_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/prt/elections/{}/election".format(election_id), payload, headers)

    def post_election_revocation(
        self,
        election_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post("/prt/elections/{}/revocation".format(election_id), payload or {}, headers)

    # -- buyout tranches ---------------------------------------------------

    def create_tranche(
        self, plan_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/prt/plans/{}/tranches".format(plan_id), payload, headers)

    def get_tranche(
        self, tranche_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get("/prt/tranches/{}".format(tranche_id), headers)

    def list_tranches(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self.get("/prt/tranches", headers, params)

    def post_participant_assignment(
        self, tranche_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(
            "/prt/tranches/{}/participant-assignments".format(tranche_id), payload, headers
        )

    def post_tranche_quoting(
        self,
        tranche_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post("/prt/tranches/{}/quoting".format(tranche_id), payload or {}, headers)

    def post_insurer_selection(
        self, tranche_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/prt/tranches/{}/insurer-selection".format(tranche_id), payload, headers)

    def post_pricing_lock(
        self,
        tranche_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post("/prt/tranches/{}/pricing-lock".format(tranche_id), payload or {}, headers)

    def post_tranche_settlement(
        self,
        tranche_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post("/prt/tranches/{}/settlement".format(tranche_id), payload or {}, headers)

    def post_tranche_abandonment(
        self, tranche_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/prt/tranches/{}/abandonment".format(tranche_id), payload, headers)

    # -- annuity quotes ----------------------------------------------------

    def create_quote(
        self, tranche_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/prt/tranches/{}/quotes".format(tranche_id), payload, headers)

    def get_quote(
        self, quote_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get("/prt/quotes/{}".format(quote_id), headers)

    def list_quotes(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self.get("/prt/quotes", headers, params)

    def post_quote_submission(
        self, quote_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/prt/quotes/{}/submission".format(quote_id), payload, headers)

    # -- insurers ----------------------------------------------------------

    def create_insurer(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/prt/insurers", payload, headers)

    def get_insurer(
        self, insurer_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get("/prt/insurers/{}".format(insurer_id), headers)

    def post_rating_change(
        self, insurer_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/prt/insurers/{}/rating-changes".format(insurer_id), payload, headers)

    # -- independent experts -----------------------------------------------

    def create_expert(
        self, plan_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/prt/plans/{}/independent-experts".format(plan_id), payload, headers)

    def get_expert(
        self, expert_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get("/prt/independent-experts/{}".format(expert_id), headers)

    def list_experts(
        self,
        plan_id: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self.get("/prt/plans/{}/independent-experts".format(plan_id), headers, params)

    def post_independence_review(
        self, expert_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(
            "/prt/independent-experts/{}/independence-review".format(expert_id), payload, headers
        )

    def post_expert_opinion(
        self, expert_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(
            "/prt/independent-experts/{}/opinion".format(expert_id), payload, headers
        )

    # -- asset transfers ---------------------------------------------------

    def create_asset_transfer(
        self, tranche_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/prt/tranches/{}/asset-transfers".format(tranche_id), payload, headers)

    def list_asset_transfers(
        self,
        tranche_id: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self.get("/prt/tranches/{}/asset-transfers".format(tranche_id), headers, params)

    def post_insurer_review(
        self, transfer_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(
            "/prt/asset-transfers/{}/insurer-review".format(transfer_id), payload, headers
        )

    # -- settlement entries ------------------------------------------------

    def get_settlement_entry(
        self, entry_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get("/prt/settlement-entries/{}".format(entry_id), headers)

    def list_settlement_entries(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self.get("/prt/settlement-entries", headers, params)

    # -- participant complaints --------------------------------------------

    def create_complaint(
        self, participant_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(
            "/prt/participants/{}/complaints".format(participant_id), payload, headers
        )

    def get_complaint(
        self, complaint_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get("/prt/complaints/{}".format(complaint_id), headers)

    def list_complaints(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self.get("/prt/complaints", headers, params)

    def post_complaint_triage(
        self, complaint_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/prt/complaints/{}/triage".format(complaint_id), payload, headers)

    def post_complaint_resolution(
        self, complaint_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/prt/complaints/{}/resolution".format(complaint_id), payload, headers)


def api_client(base_url: Optional[str] = None) -> PrtApiClient:
    """Construct the endpoint-shaped client used by every test."""
    return PrtApiClient(base_url=base_url)
