"""Typed wrapper over the shared HTTP client: one method per PRD endpoint.

Every path lives under the `/gpo` prefix.  Methods return the raw
``requests.Response`` so that callers can hand it to ``validate_success`` or
``validate_error`` and assert on the HTTP status themselves.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX

Json = Dict[str, Any]
Headers = Optional[Dict[str, str]]
Params = Optional[Dict[str, Any]]


class GpoApiClient:
    """Thin, explicit binding of the Group Purchasing endpoint surface."""

    def __init__(self, base_url: Optional[str] = None) -> None:
        self._client = GenericApiClient(base_url)

    # -- low level ---------------------------------------------------------

    def _get(self, path: str, headers: Headers = None, params: Params = None):
        return self._client.get(API_PREFIX + path, headers=headers, params=params)

    def _post(self, path: str, payload: Optional[Json] = None, headers: Headers = None):
        return self._client.post(
            API_PREFIX + path, json=payload if payload is not None else {}, headers=headers
        )

    def _patch(self, path: str, payload: Optional[Json] = None, headers: Headers = None):
        return self._client._request(
            "PATCH",
            API_PREFIX + path,
            payload=payload if payload is not None else {},
            headers=headers,
        )

    # -- logical clock -----------------------------------------------------

    def set_clock(self, current_utc: str, headers: Headers = None) -> requests.Response:
        return self._post("/_clock/set_current_utc", {"current_utc": current_utc}, headers)

    # -- contracts ---------------------------------------------------------

    def create_contract(self, payload: Json, headers: Headers = None) -> requests.Response:
        return self._post("/contracts", payload, headers)

    def list_contracts(self, params: Params = None, headers: Headers = None) -> requests.Response:
        return self._get("/contracts", headers, params)

    def get_contract(self, contract_id: str, headers: Headers = None) -> requests.Response:
        return self._get("/contracts/{0}".format(contract_id), headers)

    def patch_contract_tiers(
        self, contract_id: str, payload: Json, headers: Headers = None
    ) -> requests.Response:
        return self._patch("/contracts/{0}/tiers".format(contract_id), payload, headers)

    def activate_contract(
        self, contract_id: str, payload: Optional[Json] = None, headers: Headers = None
    ) -> requests.Response:
        return self._post("/contracts/{0}/activate".format(contract_id), payload, headers)

    def suspend_contract(
        self, contract_id: str, payload: Optional[Json] = None, headers: Headers = None
    ) -> requests.Response:
        return self._post("/contracts/{0}/suspend".format(contract_id), payload, headers)

    def list_contract_evidence_reviews(
        self, contract_id: str, params: Params = None, headers: Headers = None
    ) -> requests.Response:
        """A contract's dossiers, discovered the only way the PRD publishes.

        PRD §2.8: "The resource graph is deliberately **flat**. Only one route in
        the whole API nests a child under its parent, namely adding an item to a
        contract's catalog. [...] children are discovered by **filtering a
        top-level list**, not by reading a nested path: catalog items and evidence
        reviews and fee distributions are filtered by ``contract_id``."
        """
        query = dict(params or {})
        query["contract_id"] = contract_id
        return self._get("/clinical-evidence-reviews", headers, query)

    # -- contract items ----------------------------------------------------

    def create_contract_item(
        self, contract_id: str, payload: Json, headers: Headers = None
    ) -> requests.Response:
        return self._post("/contracts/{0}/items".format(contract_id), payload, headers)

    def list_contract_items(
        self, params: Params = None, headers: Headers = None
    ) -> requests.Response:
        return self._get("/contract-items", headers, params)

    def get_contract_item(self, item_id: str, headers: Headers = None) -> requests.Response:
        return self._get("/contract-items/{0}".format(item_id), headers)

    def patch_item_base_price(
        self, item_id: str, payload: Json, headers: Headers = None
    ) -> requests.Response:
        return self._patch("/contract-items/{0}/base-price".format(item_id), payload, headers)

    def delist_contract_item(
        self, item_id: str, payload: Optional[Json] = None, headers: Headers = None
    ) -> requests.Response:
        return self._post("/contract-items/{0}/delist".format(item_id), payload, headers)

    # -- members -----------------------------------------------------------

    def create_member(self, payload: Json, headers: Headers = None) -> requests.Response:
        return self._post("/members", payload, headers)

    def list_members(self, params: Params = None, headers: Headers = None) -> requests.Response:
        return self._get("/members", headers, params)

    def get_member(self, member_id: str, headers: Headers = None) -> requests.Response:
        return self._get("/members/{0}".format(member_id), headers)

    def patch_member_item_master(
        self, member_id: str, payload: Json, headers: Headers = None
    ) -> requests.Response:
        return self._patch("/members/{0}/item-master".format(member_id), payload, headers)

    def suspend_member(
        self, member_id: str, payload: Optional[Json] = None, headers: Headers = None
    ) -> requests.Response:
        return self._post("/members/{0}/suspend".format(member_id), payload, headers)

    # -- clinical evidence reviews ----------------------------------------

    def create_evidence_review(self, payload: Json, headers: Headers = None) -> requests.Response:
        return self._post("/clinical-evidence-reviews", payload, headers)

    def list_evidence_reviews(
        self, params: Params = None, headers: Headers = None
    ) -> requests.Response:
        return self._get("/clinical-evidence-reviews", headers, params)

    def get_evidence_review(self, review_id: str, headers: Headers = None) -> requests.Response:
        return self._get("/clinical-evidence-reviews/{0}".format(review_id), headers)

    def patch_review_scores(
        self, review_id: str, payload: Json, headers: Headers = None
    ) -> requests.Response:
        return self._patch(
            "/clinical-evidence-reviews/{0}/scores".format(review_id), payload, headers
        )

    def request_review_revision(
        self, review_id: str, payload: Optional[Json] = None, headers: Headers = None
    ) -> requests.Response:
        return self._post(
            "/clinical-evidence-reviews/{0}/request-revision".format(review_id), payload, headers
        )

    def resubmit_review(
        self, review_id: str, payload: Optional[Json] = None, headers: Headers = None
    ) -> requests.Response:
        return self._post(
            "/clinical-evidence-reviews/{0}/resubmit".format(review_id), payload, headers
        )

    def endorse_review(
        self, review_id: str, payload: Optional[Json] = None, headers: Headers = None
    ) -> requests.Response:
        return self._post(
            "/clinical-evidence-reviews/{0}/endorse".format(review_id), payload, headers
        )

    def reject_review(
        self, review_id: str, payload: Optional[Json] = None, headers: Headers = None
    ) -> requests.Response:
        return self._post(
            "/clinical-evidence-reviews/{0}/reject".format(review_id), payload, headers
        )

    # -- commitments -------------------------------------------------------

    def create_commitment(self, payload: Json, headers: Headers = None) -> requests.Response:
        return self._post("/commitments", payload, headers)

    def list_commitments(self, params: Params = None, headers: Headers = None) -> requests.Response:
        return self._get("/commitments", headers, params)

    def get_commitment(self, commitment_id: str, headers: Headers = None) -> requests.Response:
        return self._get("/commitments/{0}".format(commitment_id), headers)

    def issue_lop(
        self, commitment_id: str, payload: Optional[Json] = None, headers: Headers = None
    ) -> requests.Response:
        return self._post("/commitments/{0}/lop/issue".format(commitment_id), payload, headers)

    def sign_lop(
        self, commitment_id: str, payload: Optional[Json] = None, headers: Headers = None
    ) -> requests.Response:
        return self._post("/commitments/{0}/lop/sign".format(commitment_id), payload, headers)

    def countersign_lop(
        self, commitment_id: str, payload: Optional[Json] = None, headers: Headers = None
    ) -> requests.Response:
        return self._post(
            "/commitments/{0}/lop/countersign".format(commitment_id), payload, headers
        )

    def void_lop(
        self, commitment_id: str, payload: Optional[Json] = None, headers: Headers = None
    ) -> requests.Response:
        return self._post("/commitments/{0}/lop/void".format(commitment_id), payload, headers)

    def open_requalification(
        self, commitment_id: str, payload: Optional[Json] = None, headers: Headers = None
    ) -> requests.Response:
        return self._post(
            "/commitments/{0}/open-requalification".format(commitment_id), payload, headers
        )

    def terminate_commitment(
        self, commitment_id: str, payload: Optional[Json] = None, headers: Headers = None
    ) -> requests.Response:
        return self._post("/commitments/{0}/terminate".format(commitment_id), payload, headers)

    def get_leakage_report(
        self, commitment_id: str, params: Params = None, headers: Headers = None
    ) -> requests.Response:
        return self._get("/commitments/{0}/leakage-report".format(commitment_id), headers, params)

    # -- item cross references --------------------------------------------

    def create_cross_reference(self, payload: Json, headers: Headers = None) -> requests.Response:
        return self._post("/item-cross-references", payload, headers)

    def list_cross_references(
        self, params: Params = None, headers: Headers = None
    ) -> requests.Response:
        return self._get("/item-cross-references", headers, params)

    def get_cross_reference(self, xref_id: str, headers: Headers = None) -> requests.Response:
        return self._get("/item-cross-references/{0}".format(xref_id), headers)

    def approve_cross_reference(
        self, xref_id: str, payload: Optional[Json] = None, headers: Headers = None
    ) -> requests.Response:
        return self._post("/item-cross-references/{0}/approve".format(xref_id), payload, headers)

    def reject_cross_reference(
        self, xref_id: str, payload: Optional[Json] = None, headers: Headers = None
    ) -> requests.Response:
        return self._post("/item-cross-references/{0}/reject".format(xref_id), payload, headers)

    # -- price activations -------------------------------------------------

    def create_price_activation(self, payload: Json, headers: Headers = None) -> requests.Response:
        return self._post("/price-activations", payload, headers)

    def list_price_activations(
        self, params: Params = None, headers: Headers = None
    ) -> requests.Response:
        return self._get("/price-activations", headers, params)

    def get_price_activation(
        self, activation_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._get("/price-activations/{0}".format(activation_id), headers)

    def endorse_price_activation(
        self, activation_id: str, payload: Optional[Json] = None, headers: Headers = None
    ) -> requests.Response:
        return self._post("/price-activations/{0}/endorse".format(activation_id), payload, headers)

    def approve_price_activation(
        self, activation_id: str, payload: Optional[Json] = None, headers: Headers = None
    ) -> requests.Response:
        return self._post("/price-activations/{0}/approve".format(activation_id), payload, headers)

    def activate_price_activation(
        self, activation_id: str, payload: Optional[Json] = None, headers: Headers = None
    ) -> requests.Response:
        return self._post("/price-activations/{0}/activate".format(activation_id), payload, headers)

    def deny_price_activation(
        self, activation_id: str, payload: Optional[Json] = None, headers: Headers = None
    ) -> requests.Response:
        return self._post("/price-activations/{0}/deny".format(activation_id), payload, headers)

    # -- distributor files -------------------------------------------------

    def create_distributor_file(self, payload: Json, headers: Headers = None) -> requests.Response:
        return self._post("/distributor-files", payload, headers)

    def list_distributor_files(
        self, params: Params = None, headers: Headers = None
    ) -> requests.Response:
        return self._get("/distributor-files", headers, params)

    def get_distributor_file(self, file_id: str, headers: Headers = None) -> requests.Response:
        return self._get("/distributor-files/{0}".format(file_id), headers)

    def validate_distributor_file(
        self, file_id: str, payload: Optional[Json] = None, headers: Headers = None
    ) -> requests.Response:
        return self._post("/distributor-files/{0}/validate".format(file_id), payload, headers)

    def load_distributor_file(
        self, file_id: str, payload: Optional[Json] = None, headers: Headers = None
    ) -> requests.Response:
        return self._post("/distributor-files/{0}/load".format(file_id), payload, headers)

    def reverse_distributor_file(
        self, file_id: str, payload: Optional[Json] = None, headers: Headers = None
    ) -> requests.Response:
        return self._post("/distributor-files/{0}/reverse".format(file_id), payload, headers)

    # -- purchase lines ----------------------------------------------------

    def list_purchase_lines(
        self, params: Params = None, headers: Headers = None
    ) -> requests.Response:
        return self._get("/purchase-lines", headers, params)

    def get_purchase_line(self, line_id: str, headers: Headers = None) -> requests.Response:
        return self._get("/purchase-lines/{0}".format(line_id), headers)

    # -- compliance measurements ------------------------------------------

    def create_measurement(self, payload: Json, headers: Headers = None) -> requests.Response:
        return self._post("/compliance-measurements", payload, headers)

    def list_measurements(
        self, params: Params = None, headers: Headers = None
    ) -> requests.Response:
        return self._get("/compliance-measurements", headers, params)

    def get_measurement(self, measurement_id: str, headers: Headers = None) -> requests.Response:
        return self._get("/compliance-measurements/{0}".format(measurement_id), headers)

    def measure(
        self, measurement_id: str, payload: Optional[Json] = None, headers: Headers = None
    ) -> requests.Response:
        return self._post(
            "/compliance-measurements/{0}/measure".format(measurement_id), payload, headers
        )

    def finalize_measurement(
        self, measurement_id: str, payload: Optional[Json] = None, headers: Headers = None
    ) -> requests.Response:
        return self._post(
            "/compliance-measurements/{0}/finalize".format(measurement_id), payload, headers
        )

    def supersede_measurement(
        self, measurement_id: str, payload: Optional[Json] = None, headers: Headers = None
    ) -> requests.Response:
        return self._post(
            "/compliance-measurements/{0}/supersede".format(measurement_id), payload, headers
        )

    # -- admin fee distributions ------------------------------------------

    def create_distribution(self, payload: Json, headers: Headers = None) -> requests.Response:
        return self._post("/admin-fee-distributions", payload, headers)

    def list_distributions(
        self, params: Params = None, headers: Headers = None
    ) -> requests.Response:
        return self._get("/admin-fee-distributions", headers, params)

    def get_distribution(self, distribution_id: str, headers: Headers = None) -> requests.Response:
        return self._get("/admin-fee-distributions/{0}".format(distribution_id), headers)

    def collect_distribution(
        self, distribution_id: str, payload: Optional[Json] = None, headers: Headers = None
    ) -> requests.Response:
        return self._post(
            "/admin-fee-distributions/{0}/collect".format(distribution_id), payload, headers
        )

    def distribute_distribution(
        self, distribution_id: str, payload: Optional[Json] = None, headers: Headers = None
    ) -> requests.Response:
        return self._post(
            "/admin-fee-distributions/{0}/distribute".format(distribution_id), payload, headers
        )

    def reverse_distribution(
        self, distribution_id: str, payload: Optional[Json] = None, headers: Headers = None
    ) -> requests.Response:
        return self._post(
            "/admin-fee-distributions/{0}/reverse".format(distribution_id), payload, headers
        )
