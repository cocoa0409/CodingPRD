"""HTTP client with one method per endpoint of the API under test."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

Headers = Dict[str, str]


def _prune(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Drop keys whose value is the sentinel ``_OMIT``.

    Tests use ``_OMIT`` to express "do not send this field at all", which is a
    different request from sending the field with a null value.
    """
    if payload is None:
        return None
    return {k: v for k, v in payload.items() if v is not _OMIT}


class _Omit:
    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "_OMIT"


_OMIT = _Omit()


class IpaApiClient(GenericApiClient):
    """One method per row of the endpoint table."""

    # -- Delegation agreements ---------------------------------------------
    def create_agreement(self, payload: Dict[str, Any], headers: Headers):
        return self._request(
            "POST", "/ipa/delegation-agreements", payload=_prune(payload), headers=headers
        )

    def list_agreements(self, headers: Headers, params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/ipa/delegation-agreements", payload=_prune(params), headers=headers
        )

    def get_agreement(self, agreement_id: str, headers: Headers):
        return self._request(
            "GET", f"/ipa/delegation-agreements/{agreement_id}", headers=headers
        )

    def set_agreement_state(
        self, agreement_id: str, payload: Dict[str, Any], headers: Headers
    ):
        return self._request(
            "POST",
            f"/ipa/delegation-agreements/{agreement_id}/state",
            payload=_prune(payload),
            headers=headers,
        )

    # -- Physicians ---------------------------------------------------------
    def create_physician(
        self, agreement_id: str, payload: Dict[str, Any], headers: Headers
    ):
        return self._request(
            "POST",
            f"/ipa/delegation-agreements/{agreement_id}/physicians",
            payload=_prune(payload),
            headers=headers,
        )

    def list_agreement_physicians(
        self, agreement_id: str, headers: Headers, params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET",
            f"/ipa/delegation-agreements/{agreement_id}/physicians",
            payload=_prune(params),
            headers=headers,
        )

    def get_physician(self, physician_id: str, headers: Headers):
        return self._request("GET", f"/ipa/physicians/{physician_id}", headers=headers)

    def set_physician_state(
        self, physician_id: str, payload: Dict[str, Any], headers: Headers
    ):
        return self._request(
            "POST",
            f"/ipa/physicians/{physician_id}/state",
            payload=_prune(payload),
            headers=headers,
        )

    def set_panel_status(
        self, physician_id: str, payload: Dict[str, Any], headers: Headers
    ):
        return self._request(
            "PATCH",
            f"/ipa/physicians/{physician_id}/panel-status",
            payload=_prune(payload),
            headers=headers,
        )

    # -- Enrollees ----------------------------------------------------------
    def create_enrollee(
        self, agreement_id: str, payload: Dict[str, Any], headers: Headers
    ):
        return self._request(
            "POST",
            f"/ipa/delegation-agreements/{agreement_id}/enrollees",
            payload=_prune(payload),
            headers=headers,
        )

    def list_enrollees(self, headers: Headers, params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/ipa/enrollees", payload=_prune(params), headers=headers
        )

    def get_enrollee(self, enrollee_id: str, headers: Headers):
        return self._request("GET", f"/ipa/enrollees/{enrollee_id}", headers=headers)

    # -- Member assignments -------------------------------------------------
    def create_assignment(self, payload: Dict[str, Any], headers: Headers):
        return self._request(
            "POST", "/ipa/member-assignments", payload=_prune(payload), headers=headers
        )

    def list_assignments(self, headers: Headers, params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/ipa/member-assignments", payload=_prune(params), headers=headers
        )

    def get_assignment(self, assignment_id: str, headers: Headers):
        return self._request(
            "GET", f"/ipa/member-assignments/{assignment_id}", headers=headers
        )

    def set_assignment_state(
        self, assignment_id: str, payload: Dict[str, Any], headers: Headers
    ):
        return self._request(
            "POST",
            f"/ipa/member-assignments/{assignment_id}/state",
            payload=_prune(payload),
            headers=headers,
        )

    # -- Enrollment files ---------------------------------------------------
    def create_enrollment_file(
        self, agreement_id: str, payload: Dict[str, Any], headers: Headers
    ):
        return self._request(
            "POST",
            f"/ipa/delegation-agreements/{agreement_id}/enrollment-files",
            payload=_prune(payload),
            headers=headers,
        )

    def list_agreement_enrollment_files(
        self, agreement_id: str, headers: Headers, params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET",
            f"/ipa/delegation-agreements/{agreement_id}/enrollment-files",
            payload=_prune(params),
            headers=headers,
        )

    def get_enrollment_file(self, file_id: str, headers: Headers):
        return self._request("GET", f"/ipa/enrollment-files/{file_id}", headers=headers)

    def create_enrollment_file_row(
        self, file_id: str, payload: Dict[str, Any], headers: Headers
    ):
        return self._request(
            "POST",
            f"/ipa/enrollment-files/{file_id}/rows",
            payload=_prune(payload),
            headers=headers,
        )

    def list_enrollment_file_rows(
        self, file_id: str, headers: Headers, params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET",
            f"/ipa/enrollment-files/{file_id}/rows",
            payload=_prune(params),
            headers=headers,
        )

    def set_enrollment_file_state(
        self, file_id: str, payload: Dict[str, Any], headers: Headers
    ):
        return self._request(
            "POST",
            f"/ipa/enrollment-files/{file_id}/state",
            payload=_prune(payload),
            headers=headers,
        )

    def list_file_remittances(
        self, file_id: str, headers: Headers, params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET",
            f"/ipa/enrollment-files/{file_id}/remittances",
            payload=_prune(params),
            headers=headers,
        )

    def get_remittance(self, remittance_id: str, headers: Headers):
        return self._request(
            "GET", f"/ipa/capitation-remittances/{remittance_id}", headers=headers
        )

    # -- Risk pools ---------------------------------------------------------
    def create_risk_pool(
        self, agreement_id: str, payload: Dict[str, Any], headers: Headers
    ):
        return self._request(
            "POST",
            f"/ipa/delegation-agreements/{agreement_id}/risk-pools",
            payload=_prune(payload),
            headers=headers,
        )

    def list_agreement_risk_pools(
        self, agreement_id: str, headers: Headers, params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET",
            f"/ipa/delegation-agreements/{agreement_id}/risk-pools",
            payload=_prune(params),
            headers=headers,
        )

    def get_risk_pool(self, pool_id: str, headers: Headers):
        return self._request("GET", f"/ipa/risk-pools/{pool_id}", headers=headers)

    def get_settlement_preview(
        self, pool_id: str, headers: Headers, params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET",
            f"/ipa/risk-pools/{pool_id}/settlement-preview",
            payload=_prune(params),
            headers=headers,
        )

    def set_risk_pool_state(self, pool_id: str, payload: Dict[str, Any], headers: Headers):
        return self._request(
            "POST",
            f"/ipa/risk-pools/{pool_id}/state",
            payload=_prune(payload),
            headers=headers,
        )

    # -- Downstream claims --------------------------------------------------
    def create_claim(self, payload: Dict[str, Any], headers: Headers):
        return self._request(
            "POST", "/ipa/downstream-claims", payload=_prune(payload), headers=headers
        )

    def list_claims(self, headers: Headers, params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/ipa/downstream-claims", payload=_prune(params), headers=headers
        )

    def get_claim(self, claim_id: str, headers: Headers):
        return self._request("GET", f"/ipa/downstream-claims/{claim_id}", headers=headers)

    def set_claim_state(self, claim_id: str, payload: Dict[str, Any], headers: Headers):
        return self._request(
            "POST",
            f"/ipa/downstream-claims/{claim_id}/state",
            payload=_prune(payload),
            headers=headers,
        )

    # -- Stop-loss recoveries -----------------------------------------------
    def create_recovery(self, payload: Dict[str, Any], headers: Headers):
        return self._request(
            "POST", "/ipa/stop-loss-recoveries", payload=_prune(payload), headers=headers
        )

    def list_recoveries(self, headers: Headers, params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/ipa/stop-loss-recoveries", payload=_prune(params), headers=headers
        )

    def get_recovery(self, recovery_id: str, headers: Headers):
        return self._request(
            "GET", f"/ipa/stop-loss-recoveries/{recovery_id}", headers=headers
        )

    def set_recovery_state(
        self, recovery_id: str, payload: Dict[str, Any], headers: Headers
    ):
        return self._request(
            "POST",
            f"/ipa/stop-loss-recoveries/{recovery_id}/state",
            payload=_prune(payload),
            headers=headers,
        )

    # -- Quality scorecards -------------------------------------------------
    def create_scorecard(self, payload: Dict[str, Any], headers: Headers):
        return self._request(
            "POST", "/ipa/quality-scorecards", payload=_prune(payload), headers=headers
        )

    def list_physician_scorecards(
        self, physician_id: str, headers: Headers, params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET",
            f"/ipa/physicians/{physician_id}/scorecards",
            payload=_prune(params),
            headers=headers,
        )

    def get_scorecard(self, scorecard_id: str, headers: Headers):
        return self._request(
            "GET", f"/ipa/quality-scorecards/{scorecard_id}", headers=headers
        )

    def set_scorecard_state(
        self, scorecard_id: str, payload: Dict[str, Any], headers: Headers
    ):
        return self._request(
            "POST",
            f"/ipa/quality-scorecards/{scorecard_id}/state",
            payload=_prune(payload),
            headers=headers,
        )

    # -- Pool distributions -------------------------------------------------
    def list_distributions(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", "/ipa/pool-distributions", payload=_prune(params), headers=headers
        )

    def get_distribution(self, distribution_id: str, headers: Headers):
        return self._request(
            "GET", f"/ipa/pool-distributions/{distribution_id}", headers=headers
        )

    # -- Logical clock ------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Headers):
        return self._request(
            "POST",
            "/_clock/set_current_utc",
            payload={"current_utc": current_utc},
            headers=headers,
        )
