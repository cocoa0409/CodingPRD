"""HTTP client with one method per endpoint the PRD declares.

Every method returns the raw response so tests can assert on the HTTP status as
well as the envelope.  Collection reads accept keyword filters that mirror the
query parameters the PRD lists for that collection.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

ROOT = "/draft-service"


def _params(**kwargs) -> Dict[str, Any]:
    """Drop unsupplied filters so an omitted parameter is genuinely absent."""
    return {k: v for k, v in kwargs.items() if v is not None}


class ApiClient(GenericApiClient):
    """One method per PRD endpoint, grouped by workflow."""

    # -- Logical service clock ------------------------------------------------
    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{ROOT}/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{ROOT}/_clock/set_current_utc", payload, headers)

    # -- Service accounts -----------------------------------------------------
    def create_account(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{ROOT}/accounts", payload, headers)

    def get_account(self, account_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{ROOT}/accounts/{account_id}", None, headers)

    def list_accounts(
        self,
        headers: Dict[str, str],
        status: Optional[str] = None,
        billing_mode: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ):
        return self._request(
            "GET",
            f"{ROOT}/accounts",
            _params(status=status, billing_mode=billing_mode, limit=limit, offset=offset),
            headers,
        )

    def set_account_status(self, account_id: str, to_status: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{ROOT}/accounts/{account_id}/status", {"to_status": to_status}, headers
        )

    # -- Service contracts ----------------------------------------------------
    def create_contract(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{ROOT}/contracts", payload, headers)

    def get_contract(self, contract_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{ROOT}/contracts/{contract_id}", None, headers)

    def list_contracts(
        self,
        headers: Dict[str, str],
        account_id: Optional[str] = None,
        brewer_program_id: Optional[str] = None,
        status: Optional[str] = None,
        funding_status: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ):
        return self._request(
            "GET",
            f"{ROOT}/contracts",
            _params(
                account_id=account_id,
                brewer_program_id=brewer_program_id,
                status=status,
                funding_status=funding_status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def set_contract_status(self, contract_id: str, to_status: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{ROOT}/contracts/{contract_id}/status", {"to_status": to_status}, headers
        )

    # -- Beer lines -----------------------------------------------------------
    def create_beer_line(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{ROOT}/beer-lines", payload, headers)

    def get_beer_line(self, line_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{ROOT}/beer-lines/{line_id}", None, headers)

    def list_beer_lines(
        self,
        headers: Dict[str, str],
        account_id: Optional[str] = None,
        status: Optional[str] = None,
        compliance_flag: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ):
        return self._request(
            "GET",
            f"{ROOT}/beer-lines",
            _params(
                account_id=account_id,
                status=status,
                compliance_flag=compliance_flag,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def return_line_to_service(self, line_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{ROOT}/beer-lines/{line_id}/return-to-service", {}, headers
        )

    # -- Technicians ----------------------------------------------------------
    def create_technician(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{ROOT}/technicians", payload, headers)

    def get_technician(self, technician_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{ROOT}/technicians/{technician_id}", None, headers)

    def list_technicians(
        self,
        headers: Dict[str, str],
        status: Optional[str] = None,
        certification_level: Optional[str] = None,
        caustic_certified: Optional[Any] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ):
        return self._request(
            "GET",
            f"{ROOT}/technicians",
            _params(
                status=status,
                certification_level=certification_level,
                caustic_certified=caustic_certified,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    # -- Chemical lots --------------------------------------------------------
    def create_chemical_lot(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{ROOT}/chemical-lots", payload, headers)

    def get_chemical_lot(self, lot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{ROOT}/chemical-lots/{lot_id}", None, headers)

    def list_chemical_lots(
        self,
        headers: Dict[str, str],
        chemical_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ):
        return self._request(
            "GET",
            f"{ROOT}/chemical-lots",
            _params(chemical_type=chemical_type, status=status, limit=limit, offset=offset),
            headers,
        )

    def set_chemical_lot_status(self, lot_id: str, to_status: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{ROOT}/chemical-lots/{lot_id}/status", {"to_status": to_status}, headers
        )

    # -- Catalogue parts ------------------------------------------------------
    def create_part(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{ROOT}/parts", payload, headers)

    def get_part(self, part_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{ROOT}/parts/{part_id}", None, headers)

    def list_parts(
        self,
        headers: Dict[str, str],
        component_type: Optional[str] = None,
        brewer_funded_eligible: Optional[Any] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ):
        return self._request(
            "GET",
            f"{ROOT}/parts",
            _params(
                component_type=component_type,
                brewer_funded_eligible=brewer_funded_eligible,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    # -- Brewer quality programmes -------------------------------------------
    def create_brewer_program(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{ROOT}/brewer-programs", payload, headers)

    def get_brewer_program(self, program_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{ROOT}/brewer-programs/{program_id}", None, headers)

    def list_brewer_programs(
        self,
        headers: Dict[str, str],
        status: Optional[str] = None,
        funded_scope: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ):
        return self._request(
            "GET",
            f"{ROOT}/brewer-programs",
            _params(status=status, funded_scope=funded_scope, limit=limit, offset=offset),
            headers,
        )

    def adjust_program_cap(self, program_id: str, additional_cents: int, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{ROOT}/brewer-programs/{program_id}/cap-adjustment",
            {"additional_cents": additional_cents},
            headers,
        )

    def end_brewer_program(self, program_id: str, end_note: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{ROOT}/brewer-programs/{program_id}/end", {"end_note": end_note}, headers
        )

    # -- Service visits -------------------------------------------------------
    def create_service_visit(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{ROOT}/service-visits", payload, headers)

    def get_service_visit(self, visit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{ROOT}/service-visits/{visit_id}", None, headers)

    def list_service_visits(
        self,
        headers: Dict[str, str],
        account_id: Optional[str] = None,
        technician_id: Optional[str] = None,
        rescheduled_from_visit_id: Optional[str] = None,
        work_status: Optional[str] = None,
        verification_status: Optional[str] = None,
        settlement_state: Optional[str] = None,
        scheduled_date: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ):
        return self._request(
            "GET",
            f"{ROOT}/service-visits",
            _params(
                account_id=account_id,
                technician_id=technician_id,
                rescheduled_from_visit_id=rescheduled_from_visit_id,
                work_status=work_status,
                verification_status=verification_status,
                settlement_state=settlement_state,
                scheduled_date=scheduled_date,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def start_visit(self, visit_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{ROOT}/service-visits/{visit_id}/start", {}, headers)

    def complete_visit_work(self, visit_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{ROOT}/service-visits/{visit_id}/complete-work", {}, headers
        )

    def reschedule_visit(self, visit_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{ROOT}/service-visits/{visit_id}/reschedule", payload, headers
        )

    def record_verification(self, visit_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{ROOT}/service-visits/{visit_id}/verification", payload, headers
        )

    def record_verification_waiver(self, visit_id: str, waiver_note: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{ROOT}/service-visits/{visit_id}/verification-waiver",
            {"waiver_note": waiver_note},
            headers,
        )

    # -- Cleaning cycles ------------------------------------------------------
    def create_cleaning_cycle(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{ROOT}/cleaning-cycles", payload, headers)

    def get_cleaning_cycle(self, cycle_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{ROOT}/cleaning-cycles/{cycle_id}", None, headers)

    def list_cleaning_cycles(
        self,
        headers: Dict[str, str],
        visit_id: Optional[str] = None,
        line_id: Optional[str] = None,
        chemical_lot_id: Optional[str] = None,
        record_status: Optional[str] = None,
        compliance_result: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ):
        return self._request(
            "GET",
            f"{ROOT}/cleaning-cycles",
            _params(
                visit_id=visit_id,
                line_id=line_id,
                chemical_lot_id=chemical_lot_id,
                record_status=record_status,
                compliance_result=compliance_result,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def void_cleaning_cycle(self, cycle_id: str, void_reason: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{ROOT}/cleaning-cycles/{cycle_id}/void",
            {"void_reason": void_reason},
            headers,
        )

    # -- Balance records ------------------------------------------------------
    def create_balance_record(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{ROOT}/balance-records", payload, headers)

    def get_balance_record(self, record_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{ROOT}/balance-records/{record_id}", None, headers)

    def list_balance_records(
        self,
        headers: Dict[str, str],
        line_id: Optional[str] = None,
        visit_id: Optional[str] = None,
        status: Optional[str] = None,
        balance_state: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ):
        return self._request(
            "GET",
            f"{ROOT}/balance-records",
            _params(
                line_id=line_id,
                visit_id=visit_id,
                status=status,
                balance_state=balance_state,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def decide_balance_record(self, record_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{ROOT}/balance-records/{record_id}/decision", payload, headers
        )

    # -- Component inspections ------------------------------------------------
    def create_component_inspection(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{ROOT}/component-inspections", payload, headers)

    def get_component_inspection(self, inspection_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{ROOT}/component-inspections/{inspection_id}", None, headers
        )

    def list_component_inspections(
        self,
        headers: Dict[str, str],
        visit_id: Optional[str] = None,
        line_id: Optional[str] = None,
        part_sku_id: Optional[str] = None,
        component_type: Optional[str] = None,
        condition_grade: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ):
        return self._request(
            "GET",
            f"{ROOT}/component-inspections",
            _params(
                visit_id=visit_id,
                line_id=line_id,
                part_sku_id=part_sku_id,
                component_type=component_type,
                condition_grade=condition_grade,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    # -- Quality complaints ---------------------------------------------------
    def create_quality_complaint(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{ROOT}/quality-complaints", payload, headers)

    def get_quality_complaint(self, complaint_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{ROOT}/quality-complaints/{complaint_id}", None, headers)

    def list_quality_complaints(
        self,
        headers: Dict[str, str],
        account_id: Optional[str] = None,
        line_id: Optional[str] = None,
        status: Optional[str] = None,
        symptom: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ):
        return self._request(
            "GET",
            f"{ROOT}/quality-complaints",
            _params(
                account_id=account_id,
                line_id=line_id,
                status=status,
                symptom=symptom,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def record_diagnostic_round(self, complaint_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{ROOT}/quality-complaints/{complaint_id}/diagnostic-round", payload, headers
        )

    def close_quality_complaint(self, complaint_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{ROOT}/quality-complaints/{complaint_id}/closure", payload, headers
        )

    def reopen_quality_complaint(self, complaint_id: str, reopen_reason: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{ROOT}/quality-complaints/{complaint_id}/reopen",
            {"reopen_reason": reopen_reason},
            headers,
        )

    # -- Glycol loops and cooler readings -------------------------------------
    def get_glycol_loop(self, loop_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{ROOT}/glycol-loops/{loop_id}", None, headers)

    def list_glycol_loops(
        self,
        headers: Dict[str, str],
        account_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ):
        return self._request(
            "GET",
            f"{ROOT}/glycol-loops",
            _params(account_id=account_id, status=status, limit=limit, offset=offset),
            headers,
        )

    def record_glycol_maintenance(self, loop_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"{ROOT}/glycol-loops/{loop_id}/maintenance", payload, headers
        )

    def create_cooler_reading(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"{ROOT}/cooler-readings", payload, headers)

    def get_cooler_reading(self, reading_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{ROOT}/cooler-readings/{reading_id}", None, headers)

    def list_cooler_readings(
        self,
        headers: Dict[str, str],
        glycol_loop_id: Optional[str] = None,
        source: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
    ):
        return self._request(
            "GET",
            f"{ROOT}/cooler-readings",
            _params(glycol_loop_id=glycol_loop_id, source=source, limit=limit, offset=offset),
            headers,
        )


#: Module-level singleton the pytest bridge exposes as the ``api`` fixture.
api_client = ApiClient()
