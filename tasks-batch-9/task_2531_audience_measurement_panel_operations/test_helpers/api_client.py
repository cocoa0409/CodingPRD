"""Typed client for every operation in the PRD 4 endpoint table.

One method per row of the table (39 writes, 33 reads). Every method returns the
raw ``requests.Response`` so a test can hand it to ``validate_success`` /
``validate_error`` / ``validate_paginated`` and assert on the HTTP status itself.

Conventions used throughout:

* ``headers`` is always the first positional argument and is expected to come
  from one of the builders in ``test_helpers.test_users``.
* Optional request fields default to ``_OMIT``; a field left at ``_OMIT`` is not
  transmitted at all, which is distinct from transmitting it as ``null``. Pass
  ``None`` explicitly when a test needs an explicit JSON null.
* ``**extra`` on the write methods lets a test add unknown, system-owned or
  malformed fields without a bespoke helper -- which is how the "supplied input
  is ignored" rules of PRD 3.2 and 3.8 are probed.
* List reads accept ``limit`` / ``offset`` plus their declared PRD 2.3 filters,
  and additionally ``**extra_params`` so out-of-range or unknown query values can
  be probed.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

_OMIT = object()


def _body(fields: Dict[str, Any], extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Drop omitted fields, keep explicit nulls, then merge test-supplied extras."""
    payload = {key: value for key, value in fields.items() if value is not _OMIT}
    if extra:
        payload.update(extra)
    return payload


def _params(fields: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in fields.items() if value is not _OMIT}


class ApiClient(GenericApiClient):
    """Audience measurement panel operations API client."""

    # ------------------------------------------------------------------
    # Escape hatches for malformed-request probes
    # ------------------------------------------------------------------

    def post_raw(self, path: str, payload: Any, headers: Optional[Dict[str, str]] = None):
        return self._request("POST", path, payload=payload, headers=headers)

    def get_raw(self, path: str, headers: Optional[Dict[str, str]] = None, params: Any = None):
        return self._request("GET", path, headers=headers, params=params)

    # ==================================================================
    # The logical clock (PRD 2.4)
    # ==================================================================

    def set_logical_clock(self, headers, current_utc=_OMIT, **extra):
        """POST /_clock/set_current_utc -> 200. Any role may advance the clock."""
        return self._request(
            "POST",
            "/_clock/set_current_utc",
            payload=_body({"current_utc": current_utc}, extra),
            headers=headers,
        )

    # ==================================================================
    # Markets and quota cells (PRD 3.1)
    # ==================================================================

    def create_market(
        self,
        headers,
        name=_OMIT,
        market_code=_OMIT,
        dma_rank=_OMIT,
        incentive_budget_cents=_OMIT,
        **extra,
    ):
        """POST /markets -> 201."""
        return self._request(
            "POST",
            "/markets",
            payload=_body(
                {
                    "name": name,
                    "market_code": market_code,
                    "dma_rank": dma_rank,
                    "incentive_budget_cents": incentive_budget_cents,
                },
                extra,
            ),
            headers=headers,
        )

    def get_market(self, headers, market_id):
        """GET /markets/{market_id} -> 200."""
        return self._request("GET", f"/markets/{market_id}", headers=headers)

    def list_markets(
        self,
        headers,
        recruitment_posture=_OMIT,
        accreditation_status=_OMIT,
        limit=_OMIT,
        offset=_OMIT,
        **extra_params,
    ):
        """GET /markets -> 200, created_at DESC then market_code ASC."""
        params = _params(
            {
                "recruitment_posture": recruitment_posture,
                "accreditation_status": accreditation_status,
                "limit": limit,
                "offset": offset,
            }
        )
        params.update(extra_params)
        return self._request("GET", "/markets", headers=headers, params=params)

    def adjust_market_budget(self, headers, market_id, delta_cents=_OMIT, memo=_OMIT, **extra):
        """POST /markets/{market_id}/budget-adjustments -> 200."""
        return self._request(
            "POST",
            f"/markets/{market_id}/budget-adjustments",
            payload=_body({"delta_cents": delta_cents, "memo": memo}, extra),
            headers=headers,
        )

    def create_quota_cell(
        self,
        headers,
        market_id,
        age_band=_OMIT,
        income_band=_OMIT,
        geo_zone=_OMIT,
        target_households=_OMIT,
        base_incentive_cents=_OMIT,
        **extra,
    ):
        """POST /markets/{market_id}/quota-cells -> 201."""
        return self._request(
            "POST",
            f"/markets/{market_id}/quota-cells",
            payload=_body(
                {
                    "age_band": age_band,
                    "income_band": income_band,
                    "geo_zone": geo_zone,
                    "target_households": target_households,
                    "base_incentive_cents": base_incentive_cents,
                },
                extra,
            ),
            headers=headers,
        )

    def get_quota_cell(self, headers, quota_cell_id):
        """GET /quota-cells/{quota_cell_id} -> 200."""
        return self._request("GET", f"/quota-cells/{quota_cell_id}", headers=headers)

    def list_quota_cells(
        self,
        headers,
        market_id=_OMIT,
        quota_status=_OMIT,
        incentive_boost_active=_OMIT,
        limit=_OMIT,
        offset=_OMIT,
        **extra_params,
    ):
        """GET /quota-cells -> 200 (paginated), created_at ASC."""
        params = _params(
            {
                "market_id": market_id,
                "quota_status": quota_status,
                "incentive_boost_active": incentive_boost_active,
                "limit": limit,
                "offset": offset,
            }
        )
        params.update(extra_params)
        return self._request("GET", "/quota-cells", headers=headers, params=params)

    # ==================================================================
    # Population universes and editing rule sets (PRD 3.5)
    # ==================================================================

    def create_universe_estimate(
        self,
        headers,
        market_id=_OMIT,
        vintage_label=_OMIT,
        effective_from=_OMIT,
        effective_to=_OMIT,
        cell_populations=_OMIT,
        expected_market_version=_OMIT,
        **extra,
    ):
        """POST /universe-estimates -> 201. `expected_market_version` is mandatory."""
        return self._request(
            "POST",
            "/universe-estimates",
            payload=_body(
                {
                    "market_id": market_id,
                    "vintage_label": vintage_label,
                    "effective_from": effective_from,
                    "effective_to": effective_to,
                    "cell_populations": cell_populations,
                    "expected_market_version": expected_market_version,
                },
                extra,
            ),
            headers=headers,
        )

    def publish_universe_estimate(self, headers, universe_estimate_id, **extra):
        """POST /universe-estimates/{universe_estimate_id}/publish -> 200."""
        return self._request(
            "POST",
            f"/universe-estimates/{universe_estimate_id}/publish",
            payload=_body({}, extra),
            headers=headers,
        )

    def get_universe_estimate(self, headers, universe_estimate_id):
        """GET /universe-estimates/{universe_estimate_id} -> 200."""
        return self._request(
            "GET", f"/universe-estimates/{universe_estimate_id}", headers=headers
        )

    def list_universe_estimates(
        self,
        headers,
        market_id=_OMIT,
        status=_OMIT,
        limit=_OMIT,
        offset=_OMIT,
        **extra_params,
    ):
        """GET /universe-estimates -> 200 (paginated), created_at ASC."""
        params = _params(
            {"market_id": market_id, "status": status, "limit": limit, "offset": offset}
        )
        params.update(extra_params)
        return self._request("GET", "/universe-estimates", headers=headers, params=params)

    def create_edit_rule_set(
        self,
        headers,
        label=_OMIT,
        missing_interval_ascription_minutes=_OMIT,
        invalid_tuning_max_minutes=_OMIT,
        outlier_household_minutes_cap=_OMIT,
        outlier_weight_ratio_cap=_OMIT,
        fault_missing_minutes_threshold=_OMIT,
        **extra,
    ):
        """POST /edit-rule-sets -> 201."""
        return self._request(
            "POST",
            "/edit-rule-sets",
            payload=_body(
                {
                    "label": label,
                    "missing_interval_ascription_minutes": missing_interval_ascription_minutes,
                    "invalid_tuning_max_minutes": invalid_tuning_max_minutes,
                    "outlier_household_minutes_cap": outlier_household_minutes_cap,
                    "outlier_weight_ratio_cap": outlier_weight_ratio_cap,
                    "fault_missing_minutes_threshold": fault_missing_minutes_threshold,
                },
                extra,
            ),
            headers=headers,
        )

    def publish_edit_rule_set(self, headers, edit_rule_set_id, **extra):
        """POST /edit-rule-sets/{edit_rule_set_id}/publish -> 200."""
        return self._request(
            "POST",
            f"/edit-rule-sets/{edit_rule_set_id}/publish",
            payload=_body({}, extra),
            headers=headers,
        )

    def get_edit_rule_set(self, headers, edit_rule_set_id):
        """GET /edit-rule-sets/{edit_rule_set_id} -> 200."""
        return self._request("GET", f"/edit-rule-sets/{edit_rule_set_id}", headers=headers)

    def list_edit_rule_sets(
        self, headers, status=_OMIT, limit=_OMIT, offset=_OMIT, **extra_params
    ):
        """GET /edit-rule-sets -> 200 (paginated), created_at ASC."""
        params = _params({"status": status, "limit": limit, "offset": offset})
        params.update(extra_params)
        return self._request("GET", "/edit-rule-sets", headers=headers, params=params)

    # ==================================================================
    # Households (PRD 3.2) and the incentive ledger (PRD 3.4)
    # ==================================================================

    def create_household(
        self,
        headers,
        market_id=_OMIT,
        quota_cell_id=_OMIT,
        recruitment_source=_OMIT,
        persons_count=_OMIT,
        **extra,
    ):
        """POST /households -> 201."""
        return self._request(
            "POST",
            "/households",
            payload=_body(
                {
                    "market_id": market_id,
                    "quota_cell_id": quota_cell_id,
                    "recruitment_source": recruitment_source,
                    "persons_count": persons_count,
                },
                extra,
            ),
            headers=headers,
        )

    def create_enumeration(
        self,
        headers,
        household_id,
        roster_persons_count=_OMIT,
        tv_sets_count=_OMIT,
        **extra,
    ):
        """POST /households/{household_id}/enumerations -> 200."""
        return self._request(
            "POST",
            f"/households/{household_id}/enumerations",
            payload=_body(
                {
                    "roster_persons_count": roster_persons_count,
                    "tv_sets_count": tv_sets_count,
                },
                extra,
            ),
            headers=headers,
        )

    def retire_household(self, headers, household_id, retired_reason=_OMIT, **extra):
        """POST /households/{household_id}/retire -> 200."""
        return self._request(
            "POST",
            f"/households/{household_id}/retire",
            payload=_body({"retired_reason": retired_reason}, extra),
            headers=headers,
        )

    def accrue_incentive(self, headers, household_id, period_label=_OMIT, **extra):
        """POST /households/{household_id}/accrue-incentive -> 200."""
        return self._request(
            "POST",
            f"/households/{household_id}/accrue-incentive",
            payload=_body({"period_label": period_label}, extra),
            headers=headers,
        )

    def reverse_accrual(
        self, headers, household_id, period_label=_OMIT, memo=_OMIT, **extra
    ):
        """POST /households/{household_id}/reverse-accrual -> 200."""
        return self._request(
            "POST",
            f"/households/{household_id}/reverse-accrual",
            payload=_body({"period_label": period_label, "memo": memo}, extra),
            headers=headers,
        )

    def get_household(self, headers, household_id):
        """GET /households/{household_id} -> 200."""
        return self._request("GET", f"/households/{household_id}", headers=headers)

    def list_households(
        self,
        headers,
        market_id=_OMIT,
        quota_cell_id=_OMIT,
        status=_OMIT,
        enumeration_verdict=_OMIT,
        limit=_OMIT,
        offset=_OMIT,
        **extra_params,
    ):
        """GET /households -> 200 (paginated), created_at ASC."""
        params = _params(
            {
                "market_id": market_id,
                "quota_cell_id": quota_cell_id,
                "status": status,
                "enumeration_verdict": enumeration_verdict,
                "limit": limit,
                "offset": offset,
            }
        )
        params.update(extra_params)
        return self._request("GET", "/households", headers=headers, params=params)

    # ==================================================================
    # Meters (PRD 3.3)
    # ==================================================================

    def create_meter(
        self, headers, household_id=_OMIT, meter_type=_OMIT, serial_no=_OMIT, **extra
    ):
        """POST /meters -> 201. Shipping a device; also schedules the install."""
        return self._request(
            "POST",
            "/meters",
            payload=_body(
                {
                    "household_id": household_id,
                    "meter_type": meter_type,
                    "serial_no": serial_no,
                },
                extra,
            ),
            headers=headers,
        )

    def confirm_meter_install(self, headers, meter_id, **extra):
        """POST /meters/{meter_id}/install-confirmations -> 200. No payload at all."""
        return self._request(
            "POST",
            f"/meters/{meter_id}/install-confirmations",
            payload=_body({}, extra),
            headers=headers,
        )

    def report_meter_fault(self, headers, meter_id, fault_code=_OMIT, **extra):
        """POST /meters/{meter_id}/fault-reports -> 200."""
        return self._request(
            "POST",
            f"/meters/{meter_id}/fault-reports",
            payload=_body({"fault_code": fault_code}, extra),
            headers=headers,
        )

    def repair_meter(self, headers, meter_id, repair_note=_OMIT, **extra):
        """POST /meters/{meter_id}/repairs -> 200."""
        return self._request(
            "POST",
            f"/meters/{meter_id}/repairs",
            payload=_body({"repair_note": repair_note}, extra),
            headers=headers,
        )

    def remove_meter(self, headers, meter_id, removal_note=_OMIT, **extra):
        """POST /meters/{meter_id}/removals -> 200."""
        return self._request(
            "POST",
            f"/meters/{meter_id}/removals",
            payload=_body({"removal_note": removal_note}, extra),
            headers=headers,
        )

    def get_meter(self, headers, meter_id):
        """GET /meters/{meter_id} -> 200."""
        return self._request("GET", f"/meters/{meter_id}", headers=headers)

    def list_meters(
        self,
        headers,
        household_id=_OMIT,
        install_status=_OMIT,
        health_status=_OMIT,
        meter_type=_OMIT,
        limit=_OMIT,
        offset=_OMIT,
        **extra_params,
    ):
        """GET /meters -> 200 (paginated), created_at ASC."""
        params = _params(
            {
                "household_id": household_id,
                "install_status": install_status,
                "health_status": health_status,
                "meter_type": meter_type,
                "limit": limit,
                "offset": offset,
            }
        )
        params.update(extra_params)
        return self._request("GET", "/meters", headers=headers, params=params)

    # ==================================================================
    # Tuning intervals (PRD 3.6) -- a confidential read surface
    # ==================================================================

    def create_tuning_interval(
        self,
        headers,
        meter_id=_OMIT,
        household_id=_OMIT,
        source_methodology=_OMIT,
        start_iso=_OMIT,
        end_iso=_OMIT,
        station_code=_OMIT,
        tuning_minutes=_OMIT,
        **extra,
    ):
        """POST /tuning-intervals -> 201."""
        return self._request(
            "POST",
            "/tuning-intervals",
            payload=_body(
                {
                    "meter_id": meter_id,
                    "household_id": household_id,
                    "source_methodology": source_methodology,
                    "start_iso": start_iso,
                    "end_iso": end_iso,
                    "station_code": station_code,
                    "tuning_minutes": tuning_minutes,
                },
                extra,
            ),
            headers=headers,
        )

    def get_tuning_interval(self, headers, tuning_interval_id):
        """GET /tuning-intervals/{tuning_interval_id} -> 200. Confidential read."""
        return self._request(
            "GET", f"/tuning-intervals/{tuning_interval_id}", headers=headers
        )

    def list_tuning_intervals(
        self,
        headers,
        meter_id=_OMIT,
        household_id=_OMIT,
        processing_run_id=_OMIT,
        state=_OMIT,
        source_methodology=_OMIT,
        ascribed=_OMIT,
        limit=_OMIT,
        offset=_OMIT,
        **extra_params,
    ):
        """GET /tuning-intervals -> 200, start_iso ASC then created_at ASC."""
        params = _params(
            {
                "meter_id": meter_id,
                "household_id": household_id,
                "processing_run_id": processing_run_id,
                "state": state,
                "source_methodology": source_methodology,
                "ascribed": ascribed,
                "limit": limit,
                "offset": offset,
            }
        )
        params.update(extra_params)
        return self._request("GET", "/tuning-intervals", headers=headers, params=params)

    # ==================================================================
    # Processing runs (PRD 3.6, 3.7)
    # ==================================================================

    def create_processing_run(
        self,
        headers,
        market_id=_OMIT,
        universe_estimate_id=_OMIT,
        edit_rule_set_id=_OMIT,
        window_start_iso=_OMIT,
        window_end_iso=_OMIT,
        expected_market_version=_OMIT,
        **extra,
    ):
        """POST /processing-runs -> 201. `expected_market_version` is mandatory."""
        return self._request(
            "POST",
            "/processing-runs",
            payload=_body(
                {
                    "market_id": market_id,
                    "universe_estimate_id": universe_estimate_id,
                    "edit_rule_set_id": edit_rule_set_id,
                    "window_start_iso": window_start_iso,
                    "window_end_iso": window_end_iso,
                    "expected_market_version": expected_market_version,
                },
                extra,
            ),
            headers=headers,
        )

    def detect_faults(self, headers, processing_run_id, **extra):
        """POST /processing-runs/{processing_run_id}/detect-faults -> 200."""
        return self._request(
            "POST",
            f"/processing-runs/{processing_run_id}/detect-faults",
            payload=_body({}, extra),
            headers=headers,
        )

    def edit_processing_run(self, headers, processing_run_id, **extra):
        """POST /processing-runs/{processing_run_id}/edit -> 200."""
        return self._request(
            "POST",
            f"/processing-runs/{processing_run_id}/edit",
            payload=_body({}, extra),
            headers=headers,
        )

    def weight_processing_run(self, headers, processing_run_id, weight_variant=_OMIT, **extra):
        """POST /processing-runs/{processing_run_id}/weight -> 200."""
        return self._request(
            "POST",
            f"/processing-runs/{processing_run_id}/weight",
            payload=_body({"weight_variant": weight_variant}, extra),
            headers=headers,
        )

    def publish_processing_run(self, headers, processing_run_id, **extra):
        """POST /processing-runs/{processing_run_id}/publish -> 200."""
        return self._request(
            "POST",
            f"/processing-runs/{processing_run_id}/publish",
            payload=_body({}, extra),
            headers=headers,
        )

    def repin_processing_run(
        self,
        headers,
        processing_run_id,
        universe_estimate_id=_OMIT,
        edit_rule_set_id=_OMIT,
        **extra,
    ):
        """POST /processing-runs/{processing_run_id}/repin -> 200. Both pins optional."""
        return self._request(
            "POST",
            f"/processing-runs/{processing_run_id}/repin",
            payload=_body(
                {
                    "universe_estimate_id": universe_estimate_id,
                    "edit_rule_set_id": edit_rule_set_id,
                },
                extra,
            ),
            headers=headers,
        )

    def get_processing_run(self, headers, processing_run_id):
        """GET /processing-runs/{processing_run_id} -> 200."""
        return self._request("GET", f"/processing-runs/{processing_run_id}", headers=headers)

    def list_processing_runs(
        self,
        headers,
        market_id=_OMIT,
        universe_estimate_id=_OMIT,
        edit_rule_set_id=_OMIT,
        state=_OMIT,
        weight_variant=_OMIT,
        limit=_OMIT,
        offset=_OMIT,
        **extra_params,
    ):
        """GET /processing-runs -> 200, window_start_iso ASC then created_at ASC."""
        params = _params(
            {
                "market_id": market_id,
                "universe_estimate_id": universe_estimate_id,
                "edit_rule_set_id": edit_rule_set_id,
                "state": state,
                "weight_variant": weight_variant,
                "limit": limit,
                "offset": offset,
            }
        )
        params.update(extra_params)
        return self._request("GET", "/processing-runs", headers=headers, params=params)

    # ==================================================================
    # Household weights (PRD 3.7) -- a confidential read surface
    # ==================================================================

    def get_household_weight(self, headers, household_weight_id):
        """GET /household-weights/{household_weight_id} -> 200. Confidential read."""
        return self._request(
            "GET", f"/household-weights/{household_weight_id}", headers=headers
        )

    def list_household_weights(
        self,
        headers,
        processing_run_id=_OMIT,
        household_id=_OMIT,
        capped=_OMIT,
        weight_variant=_OMIT,
        limit=_OMIT,
        offset=_OMIT,
        **extra_params,
    ):
        """GET /household-weights -> 200 (paginated), created_at ASC."""
        params = _params(
            {
                "processing_run_id": processing_run_id,
                "household_id": household_id,
                "capped": capped,
                "weight_variant": weight_variant,
                "limit": limit,
                "offset": offset,
            }
        )
        params.update(extra_params)
        return self._request("GET", "/household-weights", headers=headers, params=params)

    # ==================================================================
    # Clients and deliverables (PRD 3.8)
    # ==================================================================

    def create_client(
        self, headers, name=_OMIT, tier=_OMIT, contract_market_ids=_OMIT, **extra
    ):
        """POST /clients -> 201. `tier` is the only commercial input."""
        return self._request(
            "POST",
            "/clients",
            payload=_body(
                {
                    "name": name,
                    "tier": tier,
                    "contract_market_ids": contract_market_ids,
                },
                extra,
            ),
            headers=headers,
        )

    def suspend_client(self, headers, client_id, suspended_reason=_OMIT, **extra):
        """POST /clients/{client_id}/suspend -> 200."""
        return self._request(
            "POST",
            f"/clients/{client_id}/suspend",
            payload=_body({"suspended_reason": suspended_reason}, extra),
            headers=headers,
        )

    def reinstate_client(self, headers, client_id, **extra):
        """POST /clients/{client_id}/reinstate -> 200. Releases nothing."""
        return self._request(
            "POST",
            f"/clients/{client_id}/reinstate",
            payload=_body({}, extra),
            headers=headers,
        )

    def create_scheduled_deliverable(
        self,
        headers,
        client_id,
        processing_run_id=_OMIT,
        requested_cell_count=_OMIT,
        **extra,
    ):
        """POST /clients/{client_id}/scheduled-deliverables -> 201."""
        return self._request(
            "POST",
            f"/clients/{client_id}/scheduled-deliverables",
            payload=_body(
                {
                    "processing_run_id": processing_run_id,
                    "requested_cell_count": requested_cell_count,
                },
                extra,
            ),
            headers=headers,
        )

    def get_client(self, headers, client_id):
        """GET /clients/{client_id} -> 200."""
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def list_clients(
        self, headers, tier=_OMIT, status=_OMIT, limit=_OMIT, offset=_OMIT, **extra_params
    ):
        """GET /clients -> 200 (paginated), created_at ASC."""
        params = _params({"tier": tier, "status": status, "limit": limit, "offset": offset})
        params.update(extra_params)
        return self._request("GET", "/clients", headers=headers, params=params)

    def create_custom_analysis(
        self,
        headers,
        client_id=_OMIT,
        processing_run_id=_OMIT,
        question=_OMIT,
        requested_cell_count=_OMIT,
        **extra,
    ):
        """POST /client-deliverables -> 201. Files a custom analysis."""
        return self._request(
            "POST",
            "/client-deliverables",
            payload=_body(
                {
                    "client_id": client_id,
                    "processing_run_id": processing_run_id,
                    "question": question,
                    "requested_cell_count": requested_cell_count,
                },
                extra,
            ),
            headers=headers,
        )

    def start_deliverable(self, headers, client_deliverable_id, **extra):
        """POST /client-deliverables/{client_deliverable_id}/start -> 200."""
        return self._request(
            "POST",
            f"/client-deliverables/{client_deliverable_id}/start",
            payload=_body({}, extra),
            headers=headers,
        )

    def dispatch_deliverable(self, headers, client_deliverable_id, **extra):
        """POST /client-deliverables/{client_deliverable_id}/dispatch -> 200."""
        return self._request(
            "POST",
            f"/client-deliverables/{client_deliverable_id}/dispatch",
            payload=_body({}, extra),
            headers=headers,
        )

    def deliver_deliverable(
        self, headers, client_deliverable_id, findings_summary=_OMIT, **extra
    ):
        """POST /client-deliverables/{client_deliverable_id}/deliver -> 200."""
        return self._request(
            "POST",
            f"/client-deliverables/{client_deliverable_id}/deliver",
            payload=_body({"findings_summary": findings_summary}, extra),
            headers=headers,
        )

    def request_deliverable_revision(
        self, headers, client_deliverable_id, reason=_OMIT, **extra
    ):
        """POST /client-deliverables/{client_deliverable_id}/request-revision -> 200."""
        return self._request(
            "POST",
            f"/client-deliverables/{client_deliverable_id}/request-revision",
            payload=_body({"reason": reason}, extra),
            headers=headers,
        )

    def hold_deliverable(self, headers, client_deliverable_id, hold_reason=_OMIT, **extra):
        """POST /client-deliverables/{client_deliverable_id}/hold -> 200."""
        return self._request(
            "POST",
            f"/client-deliverables/{client_deliverable_id}/hold",
            payload=_body({"hold_reason": hold_reason}, extra),
            headers=headers,
        )

    def release_deliverable(self, headers, client_deliverable_id, **extra):
        """POST /client-deliverables/{client_deliverable_id}/release -> 200."""
        return self._request(
            "POST",
            f"/client-deliverables/{client_deliverable_id}/release",
            payload=_body({}, extra),
            headers=headers,
        )

    def get_client_deliverable(self, headers, client_deliverable_id):
        """GET /client-deliverables/{client_deliverable_id} -> 200."""
        return self._request(
            "GET", f"/client-deliverables/{client_deliverable_id}", headers=headers
        )

    def list_client_deliverables(
        self,
        headers,
        client_id=_OMIT,
        processing_run_id=_OMIT,
        kind=_OMIT,
        state=_OMIT,
        hold_reason=_OMIT,
        limit=_OMIT,
        offset=_OMIT,
        **extra_params,
    ):
        """GET /client-deliverables -> 200 (paginated), created_at ASC."""
        params = _params(
            {
                "client_id": client_id,
                "processing_run_id": processing_run_id,
                "kind": kind,
                "state": state,
                "hold_reason": hold_reason,
                "limit": limit,
                "offset": offset,
            }
        )
        params.update(extra_params)
        return self._request("GET", "/client-deliverables", headers=headers, params=params)

    # ==================================================================
    # Methodology changes and notifications (PRD 3.9)
    # ==================================================================

    def create_methodology_change(
        self,
        headers,
        title=_OMIT,
        target_edit_rule_set_id=_OMIT,
        proposed_edit_rule_set_id=_OMIT,
        affected_market_ids=_OMIT,
        supersedes_change_id=_OMIT,
        **extra,
    ):
        """POST /methodology-changes -> 201."""
        return self._request(
            "POST",
            "/methodology-changes",
            payload=_body(
                {
                    "title": title,
                    "target_edit_rule_set_id": target_edit_rule_set_id,
                    "proposed_edit_rule_set_id": proposed_edit_rule_set_id,
                    "affected_market_ids": affected_market_ids,
                    "supersedes_change_id": supersedes_change_id,
                },
                extra,
            ),
            headers=headers,
        )

    def create_impact_analysis(
        self,
        headers,
        methodology_change_id,
        baseline_processing_run_id=_OMIT,
        expected_methodology_change_version=_OMIT,
        **extra,
    ):
        """POST /methodology-changes/{id}/impact-analyses -> 200."""
        return self._request(
            "POST",
            f"/methodology-changes/{methodology_change_id}/impact-analyses",
            payload=_body(
                {
                    "baseline_processing_run_id": baseline_processing_run_id,
                    "expected_methodology_change_version": expected_methodology_change_version,
                },
                extra,
            ),
            headers=headers,
        )

    def notify_methodology_change(self, headers, methodology_change_id, **extra):
        """POST /methodology-changes/{methodology_change_id}/notify -> 200."""
        return self._request(
            "POST",
            f"/methodology-changes/{methodology_change_id}/notify",
            payload=_body({}, extra),
            headers=headers,
        )

    def request_methodology_change_revision(
        self, headers, methodology_change_id, reason=_OMIT, **extra
    ):
        """POST /methodology-changes/{methodology_change_id}/request-revision -> 200."""
        return self._request(
            "POST",
            f"/methodology-changes/{methodology_change_id}/request-revision",
            payload=_body({"reason": reason}, extra),
            headers=headers,
        )

    def activate_methodology_change(self, headers, methodology_change_id, **extra):
        """POST /methodology-changes/{methodology_change_id}/activate -> 200."""
        return self._request(
            "POST",
            f"/methodology-changes/{methodology_change_id}/activate",
            payload=_body({}, extra),
            headers=headers,
        )

    def get_methodology_change(self, headers, methodology_change_id):
        """GET /methodology-changes/{methodology_change_id} -> 200."""
        return self._request(
            "GET", f"/methodology-changes/{methodology_change_id}", headers=headers
        )

    def list_methodology_changes(
        self,
        headers,
        state=_OMIT,
        target_edit_rule_set_id=_OMIT,
        proposed_edit_rule_set_id=_OMIT,
        supersedes_change_id=_OMIT,
        limit=_OMIT,
        offset=_OMIT,
        **extra_params,
    ):
        """GET /methodology-changes -> 200 (paginated), created_at ASC."""
        params = _params(
            {
                "state": state,
                "target_edit_rule_set_id": target_edit_rule_set_id,
                "proposed_edit_rule_set_id": proposed_edit_rule_set_id,
                "supersedes_change_id": supersedes_change_id,
                "limit": limit,
                "offset": offset,
            }
        )
        params.update(extra_params)
        return self._request("GET", "/methodology-changes", headers=headers, params=params)

    def acknowledge_notification(self, headers, client_notification_id, **extra):
        """POST /client-notifications/{client_notification_id}/acknowledge -> 200."""
        return self._request(
            "POST",
            f"/client-notifications/{client_notification_id}/acknowledge",
            payload=_body({}, extra),
            headers=headers,
        )

    def get_client_notification(self, headers, client_notification_id):
        """GET /client-notifications/{client_notification_id} -> 200."""
        return self._request(
            "GET", f"/client-notifications/{client_notification_id}", headers=headers
        )

    def list_client_notifications(
        self,
        headers,
        methodology_change_id=_OMIT,
        client_id=_OMIT,
        state=_OMIT,
        impact_tier=_OMIT,
        limit=_OMIT,
        offset=_OMIT,
        **extra_params,
    ):
        """GET /client-notifications -> 200 (paginated), created_at ASC."""
        params = _params(
            {
                "methodology_change_id": methodology_change_id,
                "client_id": client_id,
                "state": state,
                "impact_tier": impact_tier,
                "limit": limit,
                "offset": offset,
            }
        )
        params.update(extra_params)
        return self._request("GET", "/client-notifications", headers=headers, params=params)

    # ==================================================================
    # Accreditation audits (PRD 3.9)
    # ==================================================================

    def create_accreditation_audit(
        self,
        headers,
        market_id=_OMIT,
        scope_edit_rule_set_id=_OMIT,
        auditor_note=_OMIT,
        **extra,
    ):
        """POST /accreditation-audits -> 201. Opening it freezes the market."""
        return self._request(
            "POST",
            "/accreditation-audits",
            payload=_body(
                {
                    "market_id": market_id,
                    "scope_edit_rule_set_id": scope_edit_rule_set_id,
                    "auditor_note": auditor_note,
                },
                extra,
            ),
            headers=headers,
        )

    def finalize_accreditation_audit(
        self,
        headers,
        accreditation_audit_id,
        outcome=_OMIT,
        limitation_disclosures=_OMIT,
        **extra,
    ):
        """POST /accreditation-audits/{accreditation_audit_id}/finalize -> 200."""
        return self._request(
            "POST",
            f"/accreditation-audits/{accreditation_audit_id}/finalize",
            payload=_body(
                {
                    "outcome": outcome,
                    "limitation_disclosures": limitation_disclosures,
                },
                extra,
            ),
            headers=headers,
        )

    def get_accreditation_audit(self, headers, accreditation_audit_id):
        """GET /accreditation-audits/{accreditation_audit_id} -> 200."""
        return self._request(
            "GET", f"/accreditation-audits/{accreditation_audit_id}", headers=headers
        )

    def list_accreditation_audits(
        self,
        headers,
        market_id=_OMIT,
        scope_edit_rule_set_id=_OMIT,
        state=_OMIT,
        outcome=_OMIT,
        limit=_OMIT,
        offset=_OMIT,
        **extra_params,
    ):
        """GET /accreditation-audits -> 200 (paginated), created_at ASC."""
        params = _params(
            {
                "market_id": market_id,
                "scope_edit_rule_set_id": scope_edit_rule_set_id,
                "state": state,
                "outcome": outcome,
                "limit": limit,
                "offset": offset,
            }
        )
        params.update(extra_params)
        return self._request(
            "GET", "/accreditation-audits", headers=headers, params=params
        )


# Module-level singleton used by every fixture and test.
api_client = ApiClient()
