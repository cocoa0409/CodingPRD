"""HTTP client for the condominium conversion registry API.

One method per endpoint the tests exercise. Every method returns the raw
`requests.Response` so tests can assert on status codes and error envelopes.
The base URL comes from the runner via `API_BASE_URL`; nothing here starts,
stops or health-checks the server.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .types import Headers, JsonDict


class ConversionApiClient(GenericApiClient):
    """Domain client covering the endpoints named in the PRD's API surface."""

    # ---- generic verbs -----------------------------------------------------
    def patch(self, path: str, json: Any = None, headers: Optional[Headers] = None):
        return self._request("PATCH", path, payload=json, headers=headers)

    # ---- logical clock -----------------------------------------------------
    def set_clock(self, current_utc: str, headers: Headers):
        return self.post(
            "/_clock/set_current_utc", json={"current_utc": current_utc}, headers=headers
        )

    def get_clock(self, headers: Headers):
        return self.get("/_clock/current", headers=headers)

    # ---- conversion projects ----------------------------------------------
    def create_project(self, payload: JsonDict, headers: Headers):
        return self.post("/conversion-projects", json=payload, headers=headers)

    def list_projects(self, headers: Headers, params: Optional[Dict] = None):
        return self.get("/conversion-projects", headers=headers, params=params)

    def get_project(self, project_id: str, headers: Headers):
        return self.get("/conversion-projects/%s" % project_id, headers=headers)

    def patch_project(self, project_id: str, payload: JsonDict, headers: Headers):
        return self.patch(
            "/conversion-projects/%s" % project_id, json=payload, headers=headers
        )

    def recalculate_posture(self, project_id: str, headers: Headers):
        return self.post(
            "/conversion-projects/%s/posture-recalculations" % project_id,
            json={},
            headers=headers,
        )

    def escrow_summary(self, project_id: str, headers: Headers):
        return self.get(
            "/conversion-projects/%s/escrow-summary" % project_id, headers=headers
        )

    def warrantability_summary(self, project_id: str, headers: Headers):
        return self.get(
            "/conversion-projects/%s/warrantability-summary" % project_id, headers=headers
        )

    def relocation_summary(self, project_id: str, headers: Headers):
        return self.get(
            "/conversion-projects/%s/relocation-summary" % project_id, headers=headers
        )

    def warranty_summary(self, project_id: str, headers: Headers):
        return self.get(
            "/conversion-projects/%s/warranty-summary" % project_id, headers=headers
        )

    # ---- engineering reports ----------------------------------------------
    def create_report(self, project_id: str, payload: JsonDict, headers: Headers):
        return self.post(
            "/conversion-projects/%s/engineering-reports" % project_id,
            json=payload,
            headers=headers,
        )

    def list_reports(
        self, project_id: str, headers: Headers, params: Optional[Dict] = None
    ):
        return self.get(
            "/conversion-projects/%s/engineering-reports" % project_id,
            headers=headers,
            params=params,
        )

    def get_report(self, report_id: str, headers: Headers):
        return self.get("/engineering-reports/%s" % report_id, headers=headers)

    def submit_report(self, report_id: str, headers: Headers):
        return self.post(
            "/engineering-reports/%s/submit" % report_id, json={}, headers=headers
        )

    def peer_review(self, report_id: str, payload: JsonDict, headers: Headers):
        return self.post(
            "/engineering-reports/%s/peer-review-decisions" % report_id,
            json=payload,
            headers=headers,
        )

    def request_revision(
        self, report_id: str, headers: Headers, payload: Optional[JsonDict] = None
    ):
        return self.post(
            "/engineering-reports/%s/revisions" % report_id,
            json=payload or {},
            headers=headers,
        )

    # ---- major components -------------------------------------------------
    def create_component(self, report_id: str, payload: JsonDict, headers: Headers):
        return self.post(
            "/engineering-reports/%s/major-components" % report_id,
            json=payload,
            headers=headers,
        )

    def list_components(
        self, report_id: str, headers: Headers, params: Optional[Dict] = None
    ):
        return self.get(
            "/engineering-reports/%s/major-components" % report_id,
            headers=headers,
            params=params,
        )

    def get_component(self, component_id: str, headers: Headers):
        return self.get("/major-components/%s" % component_id, headers=headers)

    def patch_component(self, component_id: str, payload: JsonDict, headers: Headers):
        return self.patch(
            "/major-components/%s" % component_id, json=payload, headers=headers
        )

    def verify_component(self, component_id: str, verified: bool, headers: Headers):
        return self.post(
            "/major-components/%s/verification" % component_id,
            json={"verified": verified},
            headers=headers,
        )

    # ---- suitability assessments ------------------------------------------
    def create_assessment(self, report_id: str, payload: JsonDict, headers: Headers):
        return self.post(
            "/engineering-reports/%s/suitability-assessments" % report_id,
            json=payload,
            headers=headers,
        )

    def list_report_assessments(
        self, report_id: str, headers: Headers, params: Optional[Dict] = None
    ):
        return self.get(
            "/engineering-reports/%s/suitability-assessments" % report_id,
            headers=headers,
            params=params,
        )

    def list_assessments(self, headers: Headers, params: Optional[Dict] = None):
        return self.get("/suitability-assessments", headers=headers, params=params)

    def get_assessment(self, assessment_id: str, headers: Headers):
        return self.get("/suitability-assessments/%s" % assessment_id, headers=headers)

    # ---- declaration packages ---------------------------------------------
    def create_package(self, project_id: str, payload: JsonDict, headers: Headers):
        return self.post(
            "/conversion-projects/%s/declaration-packages" % project_id,
            json=payload,
            headers=headers,
        )

    def list_packages(
        self, project_id: str, headers: Headers, params: Optional[Dict] = None
    ):
        return self.get(
            "/conversion-projects/%s/declaration-packages" % project_id,
            headers=headers,
            params=params,
        )

    def get_package(self, package_id: str, headers: Headers):
        return self.get("/declaration-packages/%s" % package_id, headers=headers)

    def patch_package(self, package_id: str, payload: JsonDict, headers: Headers):
        return self.patch(
            "/declaration-packages/%s" % package_id, json=payload, headers=headers
        )

    def certify_plat(self, package_id: str, headers: Headers):
        return self.post(
            "/declaration-packages/%s/plat-certification" % package_id,
            json={},
            headers=headers,
        )

    def record_package(self, package_id: str, headers: Headers):
        return self.post(
            "/declaration-packages/%s/record" % package_id, json={}, headers=headers
        )

    def assessment_allocation(self, package_id: str, headers: Headers):
        return self.get(
            "/declaration-packages/%s/assessment-allocation" % package_id, headers=headers
        )

    # ---- units -------------------------------------------------------------
    def create_unit(self, package_id: str, payload: JsonDict, headers: Headers):
        return self.post(
            "/declaration-packages/%s/units" % package_id, json=payload, headers=headers
        )

    def list_package_units(
        self, package_id: str, headers: Headers, params: Optional[Dict] = None
    ):
        return self.get(
            "/declaration-packages/%s/units" % package_id, headers=headers, params=params
        )

    def list_units(self, headers: Headers, params: Optional[Dict] = None):
        return self.get("/units", headers=headers, params=params)

    def get_unit(self, unit_id: str, headers: Headers):
        return self.get("/units/%s" % unit_id, headers=headers)

    def patch_unit(self, unit_id: str, payload: JsonDict, headers: Headers):
        return self.patch("/units/%s" % unit_id, json=payload, headers=headers)

    def withdraw_unit(
        self, unit_id: str, headers: Headers, payload: Optional[JsonDict] = None
    ):
        return self.post(
            "/units/%s/withdraw" % unit_id, json=payload or {}, headers=headers
        )

    def reinstate_unit(self, unit_id: str, headers: Headers):
        return self.post("/units/%s/reinstate" % unit_id, json={}, headers=headers)

    # ---- public offering statements ---------------------------------------
    def create_pos(self, project_id: str, payload: JsonDict, headers: Headers):
        return self.post(
            "/conversion-projects/%s/public-offering-statements" % project_id,
            json=payload,
            headers=headers,
        )

    def list_project_pos(
        self, project_id: str, headers: Headers, params: Optional[Dict] = None
    ):
        return self.get(
            "/conversion-projects/%s/public-offering-statements" % project_id,
            headers=headers,
            params=params,
        )

    def list_pos(self, headers: Headers, params: Optional[Dict] = None):
        return self.get("/public-offering-statements", headers=headers, params=params)

    def get_pos(self, pos_id: str, headers: Headers):
        return self.get("/public-offering-statements/%s" % pos_id, headers=headers)

    def put_section(
        self, pos_id: str, section_code: str, payload: JsonDict, headers: Headers
    ):
        return self.put(
            "/public-offering-statements/%s/sections/%s" % (pos_id, section_code),
            json=payload,
            headers=headers,
        )

    def list_sections(self, pos_id: str, headers: Headers, params: Optional[Dict] = None):
        return self.get(
            "/public-offering-statements/%s/sections" % pos_id,
            headers=headers,
            params=params,
        )

    def get_section(self, pos_id: str, section_code: str, headers: Headers):
        return self.get(
            "/public-offering-statements/%s/sections/%s" % (pos_id, section_code),
            headers=headers,
        )

    def confer_effectiveness(self, pos_id: str, headers: Headers):
        return self.post(
            "/public-offering-statements/%s/effectiveness" % pos_id,
            json={},
            headers=headers,
        )

    def file_amendment(self, pos_id: str, payload: JsonDict, headers: Headers):
        return self.post(
            "/public-offering-statements/%s/amendments" % pos_id,
            json=payload,
            headers=headers,
        )

    # ---- tenant households -------------------------------------------------
    def create_household(self, project_id: str, payload: JsonDict, headers: Headers):
        return self.post(
            "/conversion-projects/%s/tenant-households" % project_id,
            json=payload,
            headers=headers,
        )

    def list_project_households(
        self, project_id: str, headers: Headers, params: Optional[Dict] = None
    ):
        return self.get(
            "/conversion-projects/%s/tenant-households" % project_id,
            headers=headers,
            params=params,
        )

    def list_households(self, headers: Headers, params: Optional[Dict] = None):
        return self.get("/tenant-households", headers=headers, params=params)

    def get_household(self, household_id: str, headers: Headers):
        return self.get("/tenant-households/%s" % household_id, headers=headers)

    def patch_household(self, household_id: str, payload: JsonDict, headers: Headers):
        return self.patch(
            "/tenant-households/%s" % household_id, json=payload, headers=headers
        )

    def serve_notice(self, household_id: str, headers: Headers):
        return self.post(
            "/tenant-households/%s/notices" % household_id, json={}, headers=headers
        )

    def rofr_response(self, household_id: str, response: str, headers: Headers):
        return self.post(
            "/tenant-households/%s/rofr-responses" % household_id,
            json={"response": response},
            headers=headers,
        )

    def disburse_relocation(self, household_id: str, amount_cents: int, headers: Headers):
        return self.post(
            "/tenant-households/%s/relocation-disbursements" % household_id,
            json={"amount_cents": amount_cents},
            headers=headers,
        )

    def occupancy_outcome(self, household_id: str, outcome: str, headers: Headers):
        return self.post(
            "/tenant-households/%s/occupancy-outcomes" % household_id,
            json={"outcome": outcome},
            headers=headers,
        )

    # ---- reserve studies ---------------------------------------------------
    def create_reserve_study(self, project_id: str, payload: JsonDict, headers: Headers):
        return self.post(
            "/conversion-projects/%s/reserve-studies" % project_id,
            json=payload,
            headers=headers,
        )

    def list_project_reserve_studies(
        self, project_id: str, headers: Headers, params: Optional[Dict] = None
    ):
        return self.get(
            "/conversion-projects/%s/reserve-studies" % project_id,
            headers=headers,
            params=params,
        )

    def get_reserve_study(self, study_id: str, headers: Headers):
        return self.get("/reserve-studies/%s" % study_id, headers=headers)

    def patch_reserve_study(self, study_id: str, payload: JsonDict, headers: Headers):
        return self.patch(
            "/reserve-studies/%s" % study_id, json=payload, headers=headers
        )

    # ---- initial budgets ---------------------------------------------------
    def create_budget(self, project_id: str, payload: JsonDict, headers: Headers):
        return self.post(
            "/conversion-projects/%s/initial-budgets" % project_id,
            json=payload,
            headers=headers,
        )

    def list_project_budgets(
        self, project_id: str, headers: Headers, params: Optional[Dict] = None
    ):
        return self.get(
            "/conversion-projects/%s/initial-budgets" % project_id,
            headers=headers,
            params=params,
        )

    def get_budget(self, budget_id: str, headers: Headers):
        return self.get("/initial-budgets/%s" % budget_id, headers=headers)

    def patch_budget(self, budget_id: str, payload: JsonDict, headers: Headers):
        return self.patch("/initial-budgets/%s" % budget_id, json=payload, headers=headers)

    def adopt_budget(self, budget_id: str, headers: Headers):
        return self.post(
            "/initial-budgets/%s/adoption" % budget_id, json={}, headers=headers
        )

    # ---- closing batches ---------------------------------------------------
    def create_batch(self, project_id: str, payload: JsonDict, headers: Headers):
        return self.post(
            "/conversion-projects/%s/closing-batches" % project_id,
            json=payload,
            headers=headers,
        )

    def list_batches(
        self, project_id: str, headers: Headers, params: Optional[Dict] = None
    ):
        return self.get(
            "/conversion-projects/%s/closing-batches" % project_id,
            headers=headers,
            params=params,
        )

    def get_batch(self, batch_id: str, headers: Headers):
        return self.get("/closing-batches/%s" % batch_id, headers=headers)

    def patch_batch(self, batch_id: str, payload: JsonDict, headers: Headers):
        return self.patch("/closing-batches/%s" % batch_id, json=payload, headers=headers)

    def assign_agreement(self, batch_id: str, payload: JsonDict, headers: Headers):
        return self.post(
            "/closing-batches/%s/agreement-assignments" % batch_id,
            json=payload,
            headers=headers,
        )

    def unassign_agreement(self, batch_id: str, agreement_id: str, headers: Headers):
        return self.delete(
            "/closing-batches/%s/agreement-assignments/%s" % (batch_id, agreement_id),
            headers=headers,
        )

    def evaluate_threshold(self, batch_id: str, headers: Headers):
        return self.post(
            "/closing-batches/%s/threshold-evaluations" % batch_id,
            json={},
            headers=headers,
        )

    def release_batch(self, batch_id: str, headers: Headers):
        return self.post(
            "/closing-batches/%s/release" % batch_id, json={}, headers=headers
        )

    def threshold_summary(self, batch_id: str, headers: Headers):
        return self.get(
            "/closing-batches/%s/threshold-summary" % batch_id, headers=headers
        )

    def list_batch_agreements(
        self, batch_id: str, headers: Headers, params: Optional[Dict] = None
    ):
        return self.get(
            "/closing-batches/%s/agreements" % batch_id, headers=headers, params=params
        )

    # ---- purchase agreements ----------------------------------------------
    def create_agreement(self, unit_id: str, payload: JsonDict, headers: Headers):
        return self.post(
            "/units/%s/purchase-agreements" % unit_id, json=payload, headers=headers
        )

    def list_unit_agreements(
        self, unit_id: str, headers: Headers, params: Optional[Dict] = None
    ):
        return self.get(
            "/units/%s/purchase-agreements" % unit_id, headers=headers, params=params
        )

    def list_agreements(self, headers: Headers, params: Optional[Dict] = None):
        return self.get("/purchase-agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id: str, headers: Headers):
        return self.get("/purchase-agreements/%s" % agreement_id, headers=headers)

    def patch_agreement(self, agreement_id: str, payload: JsonDict, headers: Headers):
        return self.patch(
            "/purchase-agreements/%s" % agreement_id, json=payload, headers=headers
        )

    def deliver_pos(self, agreement_id: str, headers: Headers):
        return self.post(
            "/purchase-agreements/%s/pos-deliveries" % agreement_id,
            json={},
            headers=headers,
        )

    def deposit_escrow(self, agreement_id: str, amount_cents: int, headers: Headers):
        return self.post(
            "/purchase-agreements/%s/escrow-deposits" % agreement_id,
            json={"amount_cents": amount_cents},
            headers=headers,
        )

    def harden_agreement(self, agreement_id: str, headers: Headers):
        return self.post(
            "/purchase-agreements/%s/hardening" % agreement_id, json={}, headers=headers
        )

    def rescind_agreement(
        self, agreement_id: str, headers: Headers, payload: Optional[JsonDict] = None
    ):
        return self.post(
            "/purchase-agreements/%s/rescission" % agreement_id,
            json=payload or {},
            headers=headers,
        )

    def close_agreement(self, agreement_id: str, headers: Headers):
        return self.post(
            "/purchase-agreements/%s/closing" % agreement_id, json={}, headers=headers
        )

    # ---- warranty claims ---------------------------------------------------
    def create_claim(self, project_id: str, payload: JsonDict, headers: Headers):
        return self.post(
            "/conversion-projects/%s/warranty-claims" % project_id,
            json=payload,
            headers=headers,
        )

    def list_project_claims(
        self, project_id: str, headers: Headers, params: Optional[Dict] = None
    ):
        return self.get(
            "/conversion-projects/%s/warranty-claims" % project_id,
            headers=headers,
            params=params,
        )

    def list_claims(self, headers: Headers, params: Optional[Dict] = None):
        return self.get("/warranty-claims", headers=headers, params=params)

    def get_claim(self, claim_id: str, headers: Headers):
        return self.get("/warranty-claims/%s" % claim_id, headers=headers)

    def triage_claim(self, claim_id: str, payload: JsonDict, headers: Headers):
        return self.post(
            "/warranty-claims/%s/triage" % claim_id, json=payload, headers=headers
        )

    def schedule_remediation(self, claim_id: str, payload: JsonDict, headers: Headers):
        return self.post(
            "/warranty-claims/%s/remediation-schedule" % claim_id,
            json=payload,
            headers=headers,
        )

    def complete_claim(
        self, claim_id: str, headers: Headers, payload: Optional[JsonDict] = None
    ):
        return self.post(
            "/warranty-claims/%s/completion" % claim_id,
            json=payload or {},
            headers=headers,
        )

    def reopen_claim(
        self, claim_id: str, headers: Headers, payload: Optional[JsonDict] = None
    ):
        return self.post(
            "/warranty-claims/%s/reopening" % claim_id, json=payload or {}, headers=headers
        )
