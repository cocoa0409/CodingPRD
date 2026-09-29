"""One method per endpoint in the PRD endpoint table, plus the logical clock.

Every method returns the raw ``requests.Response`` so tests can assert status
codes. Query parameters are passed through ``params`` so pagination and filter
tests can send them verbatim, including deliberately invalid values.
"""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH


def _params(**kwargs) -> Optional[dict]:
    """Drop keys the caller left as None so absent filters stay absent."""
    out = {k: v for k, v in kwargs.items() if v is not None}
    return out or None


class ApiClient(GenericApiClient):
    """Domain client for the commercial laundry equipment manufacturing API."""

    # ─── Logical clock (PRD 2.5) ──────────────────────────────────────────
    def set_clock(self, to_iso8601: str, headers: dict):
        return self._request("POST", CLOCK_PATH, {"to_iso8601": to_iso8601}, headers)

    # ─── MachineModel (PRD 3.1, 3.3) ──────────────────────────────────────
    def create_machine_model(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/machine-models", payload, headers)

    def get_machine_model(self, model_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/machine-models/{model_id}", None, headers
        )

    def list_machine_models(
        self,
        headers: dict,
        product_line: Optional[str] = None,
        certification_state: Optional[str] = None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/machine-models",
            None,
            headers,
            params=_params(
                product_line=product_line,
                certification_state=certification_state,
                limit=limit,
                offset=offset,
            ),
        )

    def machine_model_lifecycle_action(self, model_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{API_PREFIX}/machine-models/{model_id}/lifecycle-actions",
            payload,
            headers,
        )

    def get_warranty_analysis(
        self, model_id: str, headers: dict, duty_cycle_class: Optional[str] = None
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/machine-models/{model_id}/warranty-analysis",
            None,
            headers,
            params=_params(duty_cycle_class=duty_cycle_class),
        )

    # ─── RebateProgram (PRD 3.2) ──────────────────────────────────────────
    def create_rebate_program(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/rebate-programs", payload, headers)

    def get_rebate_program(self, program_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/rebate-programs/{program_id}", None, headers
        )

    def list_rebate_programs(
        self,
        headers: dict,
        utility_code: Optional[str] = None,
        program_state: Optional[str] = None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/rebate-programs",
            None,
            headers,
            params=_params(
                utility_code=utility_code,
                program_state=program_state,
                limit=limit,
                offset=offset,
            ),
        )

    # ─── CertificationDossier (PRD 3.3) ───────────────────────────────────
    def create_certification_dossier(self, model_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{API_PREFIX}/machine-models/{model_id}/certification-dossiers",
            payload,
            headers,
        )

    def get_certification_dossier(self, dossier_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/certification-dossiers/{dossier_id}", None, headers
        )

    def list_model_certification_dossiers(
        self,
        model_id: str,
        headers: dict,
        dossier_state: Optional[str] = None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/machine-models/{model_id}/certification-dossiers",
            None,
            headers,
            params=_params(dossier_state=dossier_state, limit=limit, offset=offset),
        )

    def create_dossier_review(self, dossier_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{API_PREFIX}/certification-dossiers/{dossier_id}/reviews",
            payload,
            headers,
        )

    def create_resurvey_submission(self, dossier_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{API_PREFIX}/certification-dossiers/{dossier_id}/resurvey-submissions",
            payload,
            headers,
        )

    # ─── ServicePart (PRD 3.9) ────────────────────────────────────────────
    def create_service_part(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/service-parts", payload, headers)

    def get_service_part(self, part_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/service-parts/{part_id}", None, headers
        )

    def list_service_parts(
        self,
        headers: dict,
        component_class: Optional[str] = None,
        stock_state: Optional[str] = None,
        supersedes_part_id: Optional[str] = None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/service-parts",
            None,
            headers,
            params=_params(
                component_class=component_class,
                stock_state=stock_state,
                supersedes_part_id=supersedes_part_id,
                limit=limit,
                offset=offset,
            ),
        )

    def create_stock_adjustment(self, part_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{API_PREFIX}/service-parts/{part_id}/stock-adjustments",
            payload,
            headers,
        )

    # ─── AssemblyStation (PRD 3.5) ────────────────────────────────────────
    def create_assembly_station(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/assembly-stations", payload, headers)

    def get_assembly_station(self, station_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/assembly-stations/{station_id}", None, headers
        )

    def list_assembly_stations(
        self,
        headers: dict,
        station_type: Optional[str] = None,
        station_state: Optional[str] = None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/assembly-stations",
            None,
            headers,
            params=_params(
                station_type=station_type,
                station_state=station_state,
                limit=limit,
                offset=offset,
            ),
        )

    # ─── Technician (PRD 3.4) ─────────────────────────────────────────────
    def create_technician(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/technicians", payload, headers)

    def get_technician(self, technician_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/technicians/{technician_id}", None, headers
        )

    def list_technicians(
        self,
        headers: dict,
        distributor_id: Optional[str] = None,
        cert_state: Optional[str] = None,
        employer: Optional[str] = None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/technicians",
            None,
            headers,
            params=_params(
                distributor_id=distributor_id,
                cert_state=cert_state,
                employer=employer,
                limit=limit,
                offset=offset,
            ),
        )

    def create_certification_action(
        self, technician_id: str, payload: dict, headers: dict
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/technicians/{technician_id}/certification-actions",
            payload,
            headers,
        )

    # ─── BuildOrder (PRD 3.5, 3.6) ────────────────────────────────────────
    def create_build_order(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/build-orders", payload, headers)

    def get_build_order(self, build_order_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/build-orders/{build_order_id}", None, headers
        )

    def list_build_orders(
        self,
        headers: dict,
        model_id: Optional[str] = None,
        build_state: Optional[str] = None,
        integrity_hold=None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/build-orders",
            None,
            headers,
            params=_params(
                model_id=model_id,
                build_state=build_state,
                integrity_hold=integrity_hold,
                limit=limit,
                offset=offset,
            ),
        )

    def release_to_floor(self, build_order_id: str, headers: dict):
        return self._request(
            "POST",
            f"{API_PREFIX}/build-orders/{build_order_id}/release-to-floor",
            {},
            headers,
        )

    def qa_signoff(self, build_order_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{API_PREFIX}/build-orders/{build_order_id}/qa-signoff",
            payload,
            headers,
        )

    # ─── StationLog (PRD 3.5) ─────────────────────────────────────────────
    def create_station_log(self, build_order_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{API_PREFIX}/build-orders/{build_order_id}/station-logs",
            payload,
            headers,
        )

    def get_station_log(self, log_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/station-logs/{log_id}", None, headers
        )

    def list_station_logs(
        self,
        headers: dict,
        build_order_id: Optional[str] = None,
        station_id: Optional[str] = None,
        technician_id: Optional[str] = None,
        outcome: Optional[str] = None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/station-logs",
            None,
            headers,
            params=_params(
                build_order_id=build_order_id,
                station_id=station_id,
                technician_id=technician_id,
                outcome=outcome,
                limit=limit,
                offset=offset,
            ),
        )

    # ─── Distributor (PRD 3.7) ────────────────────────────────────────────
    def create_distributor(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/distributors", payload, headers)

    def get_distributor(self, distributor_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/distributors/{distributor_id}", None, headers
        )

    def list_distributors(
        self,
        headers: dict,
        territory_code: Optional[str] = None,
        distributor_state: Optional[str] = None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/distributors",
            None,
            headers,
            params=_params(
                territory_code=territory_code,
                distributor_state=distributor_state,
                limit=limit,
                offset=offset,
            ),
        )

    def create_training_completion(
        self, distributor_id: str, payload: dict, headers: dict
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/distributors/{distributor_id}/training-completions",
            payload,
            headers,
        )

    def create_distributor_status_action(
        self, distributor_id: str, payload: dict, headers: dict
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/distributors/{distributor_id}/status-actions",
            payload,
            headers,
        )

    # ─── PackageQuote and QuoteLine (PRD 3.8) ─────────────────────────────
    def create_quote(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/quotes", payload, headers)

    def get_quote(self, quote_id: str, headers: dict):
        return self._request("GET", f"{API_PREFIX}/quotes/{quote_id}", None, headers)

    def list_quotes(
        self,
        headers: dict,
        distributor_id: Optional[str] = None,
        quote_state: Optional[str] = None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/quotes",
            None,
            headers,
            params=_params(
                distributor_id=distributor_id,
                quote_state=quote_state,
                limit=limit,
                offset=offset,
            ),
        )

    def create_quote_line(self, quote_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/quotes/{quote_id}/lines", payload, headers
        )

    def delete_quote_line(
        self, quote_id: str, line_id: str, expected_quote_version, headers: dict
    ):
        """Delete a quote line.

        The PRD requires the deletion to carry ``expected_quote_version``, so the
        value travels in the JSON body and is mirrored on the query string; a
        server reading either location sees the same token.
        """
        url = f"{self.base_url}{API_PREFIX}/quotes/{quote_id}/lines/{line_id}"
        body = {"expected_quote_version": expected_quote_version}
        return self.session.request(
            "DELETE", url, json=body, params=body, headers=headers
        )

    def get_quote_line(self, line_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/quote-lines/{line_id}", None, headers
        )

    def list_quote_lines(
        self,
        headers: dict,
        quote_id: Optional[str] = None,
        model_id: Optional[str] = None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/quote-lines",
            None,
            headers,
            params=_params(
                quote_id=quote_id, model_id=model_id, limit=limit, offset=offset
            ),
        )

    def submit_quote(self, quote_id: str, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/quotes/{quote_id}/submit", {}, headers
        )

    def decide_quote(self, quote_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/quotes/{quote_id}/decision", payload, headers
        )

    # ─── WarrantyClaim (PRD 3.9) ──────────────────────────────────────────
    def create_warranty_claim(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/warranty-claims/{claim_id}", None, headers
        )

    def list_warranty_claims(
        self,
        headers: dict,
        build_order_id: Optional[str] = None,
        part_id: Optional[str] = None,
        distributor_id: Optional[str] = None,
        reported_by_technician_id: Optional[str] = None,
        claim_state: Optional[str] = None,
        limit=None,
        offset=None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/warranty-claims",
            None,
            headers,
            params=_params(
                build_order_id=build_order_id,
                part_id=part_id,
                distributor_id=distributor_id,
                reported_by_technician_id=reported_by_technician_id,
                claim_state=claim_state,
                limit=limit,
                offset=offset,
            ),
        )

    def adjudicate_warranty_claim(self, claim_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{API_PREFIX}/warranty-claims/{claim_id}/adjudicate",
            payload,
            headers,
        )

    def void_warranty_claim(self, claim_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/warranty-claims/{claim_id}/void", payload, headers
        )
