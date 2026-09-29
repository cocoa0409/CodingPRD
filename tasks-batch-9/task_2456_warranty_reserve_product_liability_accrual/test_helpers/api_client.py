"""Typed API client for the Warranty Reserve & Product Liability Accrual API.

Every method is a thin wrapper over the generic client's HTTP verbs, so the
raw response object (status + body envelope) is always returned unchanged and
error-path assertions stay possible.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

BASE_PREFIX = "/warranty"


def _params(**kwargs: Any) -> Optional[Dict[str, Any]]:
    """Drop unset query parameters so defaults can be exercised."""
    cleaned = {k: v for k, v in kwargs.items() if v is not None}
    return cleaned or None


def _body(**kwargs: Any) -> Dict[str, Any]:
    """Drop unset body fields so optional-field omission can be exercised."""
    return {k: v for k, v in kwargs.items() if v is not None}


class WarrantyApiClient(GenericApiClient):
    """One method per endpoint in the API surface."""

    def patch(self, path: str, json: Any = None, headers: Optional[Dict[str, str]] = None):
        return self._request("PATCH", path, payload=json, headers=headers)

    # ------------------------------------------------------------------
    # Accrual periods
    # ------------------------------------------------------------------
    def create_period(
        self,
        headers: Dict[str, str],
        period_code: str,
        period_start_date: str,
        period_end_date: str,
        **extra: Any,
    ):
        payload = {
            "period_code": period_code,
            "period_start_date": period_start_date,
            "period_end_date": period_end_date,
        }
        payload.update(extra)
        return self.post(f"{BASE_PREFIX}/periods", payload, headers=headers)

    def create_period_raw(self, headers: Dict[str, str], payload: Dict[str, Any]):
        return self.post(f"{BASE_PREFIX}/periods", payload, headers=headers)

    def get_period(self, headers: Dict[str, str], period_id: str):
        return self.get(f"{BASE_PREFIX}/periods/{period_id}", headers=headers)

    def lock_analysis(self, headers: Dict[str, str], period_id: str, payload: Optional[Dict[str, Any]] = None):
        return self.post(
            f"{BASE_PREFIX}/periods/{period_id}/lock-analysis",
            payload if payload is not None else {},
            headers=headers,
        )

    def open_actuarial_review(
        self, headers: Dict[str, str], period_id: str, payload: Optional[Dict[str, Any]] = None
    ):
        return self.post(
            f"{BASE_PREFIX}/periods/{period_id}/open-actuarial-review",
            payload if payload is not None else {},
            headers=headers,
        )

    def reopen_analysis(self, headers: Dict[str, str], period_id: str, payload: Optional[Dict[str, Any]] = None):
        return self.post(
            f"{BASE_PREFIX}/periods/{period_id}/reopen-analysis",
            payload if payload is not None else {},
            headers=headers,
        )

    def close_period(self, headers: Dict[str, str], period_id: str, payload: Optional[Dict[str, Any]] = None):
        return self.post(
            f"{BASE_PREFIX}/periods/{period_id}/close",
            payload if payload is not None else {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Reserve rollforwards
    # ------------------------------------------------------------------
    def generate_rollforward(
        self,
        headers: Dict[str, str],
        period_id: str,
        expected_period_version: Optional[int] = None,
        payload: Optional[Dict[str, Any]] = None,
    ):
        body = payload if payload is not None else _body(expected_period_version=expected_period_version)
        return self.post(f"{BASE_PREFIX}/periods/{period_id}/rollforward", body, headers=headers)

    def get_rollforward(self, headers: Dict[str, str], rollforward_id: str):
        return self.get(f"{BASE_PREFIX}/rollforwards/{rollforward_id}", headers=headers)

    def list_rollforwards(
        self,
        headers: Dict[str, str],
        period_id: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
        **extra: Any,
    ):
        params = _params(period_id=period_id, limit=limit, offset=offset, **extra)
        return self.get(f"{BASE_PREFIX}/rollforwards", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Product families
    # ------------------------------------------------------------------
    def create_product_family(
        self,
        headers: Dict[str, str],
        family_code: str,
        name: str,
        launch_date: str,
        base_warranty_months: int,
        standard_cost_per_claim_cents: int,
        reserve_cap_cents: int,
        engineering_estimate_rate_ppm: Optional[int] = None,
        analog_family_id: Optional[str] = None,
        **extra: Any,
    ):
        payload = _body(
            family_code=family_code,
            name=name,
            launch_date=launch_date,
            base_warranty_months=base_warranty_months,
            standard_cost_per_claim_cents=standard_cost_per_claim_cents,
            reserve_cap_cents=reserve_cap_cents,
            engineering_estimate_rate_ppm=engineering_estimate_rate_ppm,
            analog_family_id=analog_family_id,
        )
        payload.update(extra)
        return self.post(f"{BASE_PREFIX}/product-families", payload, headers=headers)

    def create_product_family_raw(self, headers: Dict[str, str], payload: Dict[str, Any]):
        return self.post(f"{BASE_PREFIX}/product-families", payload, headers=headers)

    def update_product_family(self, headers: Dict[str, str], family_id: str, payload: Dict[str, Any]):
        return self.patch(f"{BASE_PREFIX}/product-families/{family_id}", payload, headers=headers)

    def get_product_family(self, headers: Dict[str, str], family_id: str):
        return self.get(f"{BASE_PREFIX}/product-families/{family_id}", headers=headers)

    def list_product_families(
        self,
        headers: Dict[str, str],
        analog_family_id: Optional[str] = None,
        history_maturity_status: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
        **extra: Any,
    ):
        params = _params(
            analog_family_id=analog_family_id,
            history_maturity_status=history_maturity_status,
            limit=limit,
            offset=offset,
            **extra,
        )
        return self.get(f"{BASE_PREFIX}/product-families", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Product vintages
    # ------------------------------------------------------------------
    def create_vintage(
        self,
        headers: Dict[str, str],
        family_id: str,
        vintage_code: str,
        units_shipped: int,
        ship_period_code: str,
        warranty_expiry_date: str,
        **extra: Any,
    ):
        payload = {
            "family_id": family_id,
            "vintage_code": vintage_code,
            "units_shipped": units_shipped,
            "ship_period_code": ship_period_code,
            "warranty_expiry_date": warranty_expiry_date,
        }
        payload.update(extra)
        return self.post(f"{BASE_PREFIX}/vintages", payload, headers=headers)

    def create_vintage_raw(self, headers: Dict[str, str], payload: Dict[str, Any]):
        return self.post(f"{BASE_PREFIX}/vintages", payload, headers=headers)

    def get_vintage(self, headers: Dict[str, str], vintage_id: str):
        return self.get(f"{BASE_PREFIX}/vintages/{vintage_id}", headers=headers)

    def list_vintages(
        self,
        headers: Dict[str, str],
        family_id: Optional[str] = None,
        exposure_status: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
        **extra: Any,
    ):
        params = _params(
            family_id=family_id, exposure_status=exposure_status, limit=limit, offset=offset, **extra
        )
        return self.get(f"{BASE_PREFIX}/vintages", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Failure modes
    # ------------------------------------------------------------------
    def create_failure_mode(
        self,
        headers: Dict[str, str],
        family_id: str,
        mode_code: str,
        description: str,
        severity: str,
        cost_per_claim_cents: int,
        supplier_id: Optional[str] = None,
        **extra: Any,
    ):
        payload = _body(
            family_id=family_id,
            mode_code=mode_code,
            description=description,
            severity=severity,
            cost_per_claim_cents=cost_per_claim_cents,
            supplier_id=supplier_id,
        )
        payload.update(extra)
        return self.post(f"{BASE_PREFIX}/failure-modes", payload, headers=headers)

    def create_failure_mode_raw(self, headers: Dict[str, str], payload: Dict[str, Any]):
        return self.post(f"{BASE_PREFIX}/failure-modes", payload, headers=headers)

    def get_failure_mode(self, headers: Dict[str, str], failure_mode_id: str):
        return self.get(f"{BASE_PREFIX}/failure-modes/{failure_mode_id}", headers=headers)

    def list_failure_modes(
        self,
        headers: Dict[str, str],
        family_id: Optional[str] = None,
        supplier_id: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
        **extra: Any,
    ):
        params = _params(family_id=family_id, supplier_id=supplier_id, limit=limit, offset=offset, **extra)
        return self.get(f"{BASE_PREFIX}/failure-modes", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Claim observations
    # ------------------------------------------------------------------
    def create_claim_observation(
        self,
        headers: Dict[str, str],
        vintage_id: str,
        failure_mode_id: str,
        observation_period_code: str,
        months_in_service_from: int,
        months_in_service_to: int,
        claim_count: int,
        paid_cost_cents: int,
        **extra: Any,
    ):
        payload = {
            "vintage_id": vintage_id,
            "failure_mode_id": failure_mode_id,
            "observation_period_code": observation_period_code,
            "months_in_service_from": months_in_service_from,
            "months_in_service_to": months_in_service_to,
            "claim_count": claim_count,
            "paid_cost_cents": paid_cost_cents,
        }
        payload.update(extra)
        return self.post(f"{BASE_PREFIX}/claim-observations", payload, headers=headers)

    def create_claim_observation_raw(self, headers: Dict[str, str], payload: Dict[str, Any]):
        return self.post(f"{BASE_PREFIX}/claim-observations", payload, headers=headers)

    def get_claim_observation(self, headers: Dict[str, str], observation_id: str):
        return self.get(f"{BASE_PREFIX}/claim-observations/{observation_id}", headers=headers)

    def list_claim_observations(
        self,
        headers: Dict[str, str],
        vintage_id: Optional[str] = None,
        failure_mode_id: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
        **extra: Any,
    ):
        params = _params(
            vintage_id=vintage_id, failure_mode_id=failure_mode_id, limit=limit, offset=offset, **extra
        )
        return self.get(f"{BASE_PREFIX}/claim-observations", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Warranty accruals
    # ------------------------------------------------------------------
    def create_accrual(
        self,
        headers: Dict[str, str],
        period_id: str,
        vintage_id: str,
        method: str,
        elapsed_exposure_bps: int,
        expected_period_version: Optional[int] = None,
        **extra: Any,
    ):
        payload = _body(
            period_id=period_id,
            vintage_id=vintage_id,
            method=method,
            elapsed_exposure_bps=elapsed_exposure_bps,
            expected_period_version=expected_period_version,
        )
        payload.update(extra)
        return self.post(f"{BASE_PREFIX}/accruals", payload, headers=headers)

    def create_accrual_raw(self, headers: Dict[str, str], payload: Dict[str, Any]):
        return self.post(f"{BASE_PREFIX}/accruals", payload, headers=headers)

    def get_accrual(self, headers: Dict[str, str], accrual_id: str):
        return self.get(f"{BASE_PREFIX}/accruals/{accrual_id}", headers=headers)

    def list_accruals(
        self,
        headers: Dict[str, str],
        period_id: Optional[str] = None,
        vintage_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
        **extra: Any,
    ):
        params = _params(
            period_id=period_id, vintage_id=vintage_id, status=status, limit=limit, offset=offset, **extra
        )
        return self.get(f"{BASE_PREFIX}/accruals", headers=headers, params=params)

    def propose_accrual(self, headers: Dict[str, str], accrual_id: str, payload: Optional[Dict[str, Any]] = None):
        return self.post(
            f"{BASE_PREFIX}/accruals/{accrual_id}/propose",
            payload if payload is not None else {},
            headers=headers,
        )

    def revise_accrual(self, headers: Dict[str, str], accrual_id: str, payload: Optional[Dict[str, Any]] = None):
        return self.post(
            f"{BASE_PREFIX}/accruals/{accrual_id}/revise",
            payload if payload is not None else {},
            headers=headers,
        )

    def post_accrual(self, headers: Dict[str, str], accrual_id: str, payload: Optional[Dict[str, Any]] = None):
        return self.post(
            f"{BASE_PREFIX}/accruals/{accrual_id}/post",
            payload if payload is not None else {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Adequacy reviews
    # ------------------------------------------------------------------
    def create_adequacy_review(
        self, headers: Dict[str, str], period_id: str, family_id: str, **extra: Any
    ):
        payload = {"period_id": period_id, "family_id": family_id}
        payload.update(extra)
        return self.post(f"{BASE_PREFIX}/adequacy-reviews", payload, headers=headers)

    def create_adequacy_review_raw(self, headers: Dict[str, str], payload: Dict[str, Any]):
        return self.post(f"{BASE_PREFIX}/adequacy-reviews", payload, headers=headers)

    def get_adequacy_review(self, headers: Dict[str, str], review_id: str):
        return self.get(f"{BASE_PREFIX}/adequacy-reviews/{review_id}", headers=headers)

    def list_adequacy_reviews(
        self,
        headers: Dict[str, str],
        period_id: Optional[str] = None,
        family_id: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
        **extra: Any,
    ):
        params = _params(period_id=period_id, family_id=family_id, limit=limit, offset=offset, **extra)
        return self.get(f"{BASE_PREFIX}/adequacy-reviews", headers=headers, params=params)

    def apply_true_up(self, headers: Dict[str, str], review_id: str, payload: Optional[Dict[str, Any]] = None):
        return self.post(
            f"{BASE_PREFIX}/adequacy-reviews/{review_id}/apply-true-up",
            payload if payload is not None else {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Field actions
    # ------------------------------------------------------------------
    def create_field_action(
        self,
        headers: Dict[str, str],
        family_id: str,
        action_code: str,
        action_type: str,
        affected_build_start_date: str,
        affected_build_end_date: str,
        affected_unit_count: int,
        regulatory_notice_filed: Optional[bool] = None,
        **extra: Any,
    ):
        payload = _body(
            family_id=family_id,
            action_code=action_code,
            action_type=action_type,
            affected_build_start_date=affected_build_start_date,
            affected_build_end_date=affected_build_end_date,
            affected_unit_count=affected_unit_count,
            regulatory_notice_filed=regulatory_notice_filed,
        )
        payload.update(extra)
        return self.post(f"{BASE_PREFIX}/field-actions", payload, headers=headers)

    def create_field_action_raw(self, headers: Dict[str, str], payload: Dict[str, Any]):
        return self.post(f"{BASE_PREFIX}/field-actions", payload, headers=headers)

    def get_field_action(self, headers: Dict[str, str], field_action_id: str):
        return self.get(f"{BASE_PREFIX}/field-actions/{field_action_id}", headers=headers)

    def list_field_actions(
        self,
        headers: Dict[str, str],
        family_id: Optional[str] = None,
        selected_remedy_option_id: Optional[str] = None,
        approved_period_id: Optional[str] = None,
        approval_state: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
        **extra: Any,
    ):
        params = _params(
            family_id=family_id,
            selected_remedy_option_id=selected_remedy_option_id,
            approved_period_id=approved_period_id,
            approval_state=approval_state,
            limit=limit,
            offset=offset,
            **extra,
        )
        return self.get(f"{BASE_PREFIX}/field-actions", headers=headers, params=params)

    def create_remedy_option(
        self,
        headers: Dict[str, str],
        field_action_id: str,
        option_code: str,
        remedy_class: str,
        parts_cost_cents: int,
        labor_hours_centi: int,
        admin_cost_cents: int,
        expected_take_rate_bps: int,
        is_engineering_approved: Optional[bool] = None,
        **extra: Any,
    ):
        payload = _body(
            option_code=option_code,
            remedy_class=remedy_class,
            parts_cost_cents=parts_cost_cents,
            labor_hours_centi=labor_hours_centi,
            admin_cost_cents=admin_cost_cents,
            expected_take_rate_bps=expected_take_rate_bps,
            is_engineering_approved=is_engineering_approved,
        )
        payload.update(extra)
        return self.post(
            f"{BASE_PREFIX}/field-actions/{field_action_id}/remedy-options", payload, headers=headers
        )

    def create_remedy_option_raw(
        self, headers: Dict[str, str], field_action_id: str, payload: Dict[str, Any]
    ):
        return self.post(
            f"{BASE_PREFIX}/field-actions/{field_action_id}/remedy-options", payload, headers=headers
        )

    def list_remedy_options(
        self,
        headers: Dict[str, str],
        field_action_id: str,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
        **extra: Any,
    ):
        params = _params(limit=limit, offset=offset, **extra)
        return self.get(
            f"{BASE_PREFIX}/field-actions/{field_action_id}/remedy-options", headers=headers, params=params
        )

    def select_remedy(
        self,
        headers: Dict[str, str],
        field_action_id: str,
        expected_field_action_version: Optional[int] = None,
        remedy_option_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ):
        body = (
            payload
            if payload is not None
            else _body(
                expected_field_action_version=expected_field_action_version,
                remedy_option_id=remedy_option_id,
            )
        )
        return self.post(
            f"{BASE_PREFIX}/field-actions/{field_action_id}/select-remedy", body, headers=headers
        )

    def submit_field_action(
        self, headers: Dict[str, str], field_action_id: str, payload: Optional[Dict[str, Any]] = None
    ):
        return self.post(
            f"{BASE_PREFIX}/field-actions/{field_action_id}/submit",
            payload if payload is not None else {},
            headers=headers,
        )

    def decide_field_action(
        self,
        headers: Dict[str, str],
        field_action_id: str,
        decision: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ):
        body = payload if payload is not None else _body(decision=decision)
        return self.post(
            f"{BASE_PREFIX}/field-actions/{field_action_id}/decision", body, headers=headers
        )

    def execution_progress(
        self,
        headers: Dict[str, str],
        field_action_id: str,
        to_execution_state: Optional[str] = None,
        incurred_cost_cents: Optional[int] = None,
        payload: Optional[Dict[str, Any]] = None,
    ):
        body = (
            payload
            if payload is not None
            else _body(
                to_execution_state=to_execution_state, incurred_cost_cents=incurred_cost_cents
            )
        )
        return self.post(
            f"{BASE_PREFIX}/field-actions/{field_action_id}/execution-progress", body, headers=headers
        )

    # ------------------------------------------------------------------
    # Service contracts
    # ------------------------------------------------------------------
    def create_service_contract(
        self,
        headers: Dict[str, str],
        family_id: str,
        contract_number: str,
        sold_date: str,
        term_months: int,
        total_contract_price_cents: int,
        recognition_method: str,
        **extra: Any,
    ):
        payload = {
            "family_id": family_id,
            "contract_number": contract_number,
            "sold_date": sold_date,
            "term_months": term_months,
            "total_contract_price_cents": total_contract_price_cents,
            "recognition_method": recognition_method,
        }
        payload.update(extra)
        return self.post(f"{BASE_PREFIX}/service-contracts", payload, headers=headers)

    def create_service_contract_raw(self, headers: Dict[str, str], payload: Dict[str, Any]):
        return self.post(f"{BASE_PREFIX}/service-contracts", payload, headers=headers)

    def get_service_contract(self, headers: Dict[str, str], contract_id: str):
        return self.get(f"{BASE_PREFIX}/service-contracts/{contract_id}", headers=headers)

    def list_service_contracts(
        self,
        headers: Dict[str, str],
        family_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
        **extra: Any,
    ):
        params = _params(family_id=family_id, status=status, limit=limit, offset=offset, **extra)
        return self.get(f"{BASE_PREFIX}/service-contracts", headers=headers, params=params)

    def cancel_service_contract(
        self, headers: Dict[str, str], contract_id: str, payload: Optional[Dict[str, Any]] = None
    ):
        return self.post(
            f"{BASE_PREFIX}/service-contracts/{contract_id}/cancel",
            payload if payload is not None else {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Suppliers
    # ------------------------------------------------------------------
    def create_supplier(
        self,
        headers: Dict[str, str],
        supplier_code: str,
        name: str,
        credit_rating: str,
        annual_purchase_volume_cents: int,
        contractual_recovery_cap_bps: int,
        **extra: Any,
    ):
        payload = {
            "supplier_code": supplier_code,
            "name": name,
            "credit_rating": credit_rating,
            "annual_purchase_volume_cents": annual_purchase_volume_cents,
            "contractual_recovery_cap_bps": contractual_recovery_cap_bps,
        }
        payload.update(extra)
        return self.post(f"{BASE_PREFIX}/suppliers", payload, headers=headers)

    def create_supplier_raw(self, headers: Dict[str, str], payload: Dict[str, Any]):
        return self.post(f"{BASE_PREFIX}/suppliers", payload, headers=headers)

    def get_supplier(self, headers: Dict[str, str], supplier_id: str):
        return self.get(f"{BASE_PREFIX}/suppliers/{supplier_id}", headers=headers)

    # ------------------------------------------------------------------
    # Supplier recoveries
    # ------------------------------------------------------------------
    def create_supplier_recovery(
        self,
        headers: Dict[str, str],
        supplier_id: str,
        failure_mode_id: str,
        asserted_amount_cents: int,
        field_action_id: Optional[str] = None,
        **extra: Any,
    ):
        payload = _body(
            supplier_id=supplier_id,
            failure_mode_id=failure_mode_id,
            asserted_amount_cents=asserted_amount_cents,
            field_action_id=field_action_id,
        )
        payload.update(extra)
        return self.post(f"{BASE_PREFIX}/supplier-recoveries", payload, headers=headers)

    def create_supplier_recovery_raw(self, headers: Dict[str, str], payload: Dict[str, Any]):
        return self.post(f"{BASE_PREFIX}/supplier-recoveries", payload, headers=headers)

    def get_supplier_recovery(self, headers: Dict[str, str], recovery_id: str):
        return self.get(f"{BASE_PREFIX}/supplier-recoveries/{recovery_id}", headers=headers)

    def list_supplier_recoveries(
        self,
        headers: Dict[str, str],
        supplier_id: Optional[str] = None,
        failure_mode_id: Optional[str] = None,
        field_action_id: Optional[str] = None,
        settled_period_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
        **extra: Any,
    ):
        params = _params(
            supplier_id=supplier_id,
            failure_mode_id=failure_mode_id,
            field_action_id=field_action_id,
            settled_period_id=settled_period_id,
            status=status,
            limit=limit,
            offset=offset,
            **extra,
        )
        return self.get(f"{BASE_PREFIX}/supplier-recoveries", headers=headers, params=params)

    def assert_recovery(
        self,
        headers: Dict[str, str],
        recovery_id: str,
        revised_asserted_amount_cents: Optional[int] = None,
        payload: Optional[Dict[str, Any]] = None,
    ):
        body = (
            payload
            if payload is not None
            else _body(revised_asserted_amount_cents=revised_asserted_amount_cents)
        )
        return self.post(f"{BASE_PREFIX}/supplier-recoveries/{recovery_id}/assert", body, headers=headers)

    def respond_recovery(
        self,
        headers: Dict[str, str],
        recovery_id: str,
        response_note: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ):
        body = payload if payload is not None else _body(response_note=response_note)
        return self.post(
            f"{BASE_PREFIX}/supplier-recoveries/{recovery_id}/respond", body, headers=headers
        )

    def close_recovery(
        self,
        headers: Dict[str, str],
        recovery_id: str,
        outcome: Optional[str] = None,
        settled_amount_cents: Optional[int] = None,
        payload: Optional[Dict[str, Any]] = None,
    ):
        body = (
            payload
            if payload is not None
            else _body(outcome=outcome, settled_amount_cents=settled_amount_cents)
        )
        return self.post(f"{BASE_PREFIX}/supplier-recoveries/{recovery_id}/close", body, headers=headers)

    # ------------------------------------------------------------------
    # Liability reserves
    # ------------------------------------------------------------------
    def create_liability_reserve(
        self,
        headers: Dict[str, str],
        period_id: str,
        family_id: str,
        reported_claim_count: int,
        asserted_case_reserve_cents: int,
        reporting_lag_months: int,
        severity_trend_bps: int,
        **extra: Any,
    ):
        payload = {
            "period_id": period_id,
            "family_id": family_id,
            "reported_claim_count": reported_claim_count,
            "asserted_case_reserve_cents": asserted_case_reserve_cents,
            "reporting_lag_months": reporting_lag_months,
            "severity_trend_bps": severity_trend_bps,
        }
        payload.update(extra)
        return self.post(f"{BASE_PREFIX}/liability-reserves", payload, headers=headers)

    def create_liability_reserve_raw(self, headers: Dict[str, str], payload: Dict[str, Any]):
        return self.post(f"{BASE_PREFIX}/liability-reserves", payload, headers=headers)

    def get_liability_reserve(self, headers: Dict[str, str], reserve_id: str):
        return self.get(f"{BASE_PREFIX}/liability-reserves/{reserve_id}", headers=headers)

    def list_liability_reserves(
        self,
        headers: Dict[str, str],
        period_id: Optional[str] = None,
        family_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[Any] = None,
        offset: Optional[Any] = None,
        **extra: Any,
    ):
        params = _params(
            period_id=period_id, family_id=family_id, status=status, limit=limit, offset=offset, **extra
        )
        return self.get(f"{BASE_PREFIX}/liability-reserves", headers=headers, params=params)

    def actuarial_decision(
        self,
        headers: Dict[str, str],
        reserve_id: str,
        decision: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ):
        body = payload if payload is not None else _body(decision=decision)
        return self.post(
            f"{BASE_PREFIX}/liability-reserves/{reserve_id}/actuarial-decision", body, headers=headers
        )

    def book_liability_reserve(
        self, headers: Dict[str, str], reserve_id: str, payload: Optional[Dict[str, Any]] = None
    ):
        return self.post(
            f"{BASE_PREFIX}/liability-reserves/{reserve_id}/book",
            payload if payload is not None else {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(
        self,
        headers: Dict[str, str],
        to_iso8601: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ):
        body = payload if payload is not None else _body(to_iso8601=to_iso8601)
        return self.post(f"{BASE_PREFIX}/_clock/set_current_utc", body, headers=headers)
