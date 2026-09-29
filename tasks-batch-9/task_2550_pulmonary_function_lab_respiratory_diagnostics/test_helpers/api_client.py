"""One method per declared endpoint of the pulmonary function laboratory API.

Every method returns the raw HTTP response so that tests can assert status
codes as well as bodies.  Collection reads take their filters as keyword
arguments and pass them through as query parameters.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


def _query(**filters: Any) -> Dict[str, Any]:
    """Drop unsupplied filters so an omitted one is really omitted."""
    return {k: v for k, v in filters.items() if v is not None}


class ApiClient(GenericApiClient):
    """Typed surface over the ``/pft-lab`` API."""

    # ------------------------------------------------------------- devices
    def create_device(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/devices", payload, headers)

    def get_device(self, device_id: str, headers: dict):
        return self._request("GET", f"{API_PREFIX}/devices/{device_id}", None, headers)

    def list_devices(
        self,
        headers: dict,
        status: Optional[str] = None,
        modality: Optional[str] = None,
        quarantine_trigger_staff_id: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/devices",
            _query(
                status=status,
                modality=modality,
                quarantine_trigger_staff_id=quarantine_trigger_staff_id,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def create_quality_event(self, device_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/devices/{device_id}/quality-events", payload, headers
        )

    def get_quality_event(self, event_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/device-quality-events/{event_id}", None, headers
        )

    def list_quality_events(
        self,
        headers: dict,
        device_id: Optional[str] = None,
        subject_staff_id: Optional[str] = None,
        performed_by_staff_id: Optional[str] = None,
        event_type: Optional[str] = None,
        outcome: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/device-quality-events",
            _query(
                device_id=device_id,
                subject_staff_id=subject_staff_id,
                performed_by_staff_id=performed_by_staff_id,
                event_type=event_type,
                outcome=outcome,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def return_device_to_service(self, device_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{API_PREFIX}/devices/{device_id}/return-to-service",
            payload,
            headers,
        )

    # --------------------------------------------------------------- staff
    def create_staff(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/staff", payload, headers)

    def get_staff(self, staff_id: str, headers: dict):
        return self._request("GET", f"{API_PREFIX}/staff/{staff_id}", None, headers)

    # ------------------------------------------------------------ patients
    def create_patient(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/patients", payload, headers)

    def get_patient(self, patient_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/patients/{patient_id}", None, headers
        )

    # -------------------------------------------------- reference equations
    def create_reference_equation(self, payload: dict, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/reference-equations", payload, headers
        )

    # --------------------------------------------------------- rescue lots
    def create_rescue_lot(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/rescue-lots", payload, headers)

    def get_rescue_lot(self, lot_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/rescue-lots/{lot_id}", None, headers
        )

    # --------------------------------------------------------- test orders
    def create_test_order(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/test-orders", payload, headers)

    def get_test_order(self, order_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/test-orders/{order_id}", None, headers
        )

    def list_test_orders(
        self,
        headers: dict,
        patient_id: Optional[str] = None,
        ordering_staff_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/test-orders",
            _query(
                patient_id=patient_id,
                ordering_staff_id=ordering_staff_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def submit_test_order(self, order_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"{API_PREFIX}/test-orders/{order_id}/submit", payload or {}, headers
        )

    def patch_test_order(self, order_id: str, payload: dict, headers: dict):
        return self._request(
            "PATCH", f"{API_PREFIX}/test-orders/{order_id}", payload, headers
        )

    def cancel_test_order(self, order_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/test-orders/{order_id}/cancel", payload, headers
        )

    # ---------------------------------------------------- medication holds
    def create_medication_hold(self, order_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{API_PREFIX}/test-orders/{order_id}/medication-holds",
            payload,
            headers,
        )

    def list_order_medication_holds(
        self,
        order_id: str,
        headers: dict,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/test-orders/{order_id}/medication-holds",
            _query(status=status, limit=limit, offset=offset),
            headers,
        )

    def get_medication_hold(self, hold_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/medication-holds/{hold_id}", None, headers
        )

    def list_medication_holds(
        self,
        headers: dict,
        order_id: Optional[str] = None,
        medication_class: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/medication-holds",
            _query(
                order_id=order_id,
                medication_class=medication_class,
                status=status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def attest_medication_hold(self, hold_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/medication-holds/{hold_id}/attest", payload, headers
        )

    # ------------------------------------------------------- test sessions
    def create_test_session(self, payload: dict, headers: dict):
        return self._request("POST", f"{API_PREFIX}/test-sessions", payload, headers)

    def get_test_session(self, session_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/test-sessions/{session_id}", None, headers
        )

    def list_test_sessions(
        self,
        headers: dict,
        order_id: Optional[str] = None,
        device_id: Optional[str] = None,
        technologist_staff_id: Optional[str] = None,
        reference_equation_id: Optional[str] = None,
        session_status: Optional[str] = None,
        custody_status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/test-sessions",
            _query(
                order_id=order_id,
                device_id=device_id,
                technologist_staff_id=technologist_staff_id,
                reference_equation_id=reference_equation_id,
                session_status=session_status,
                custody_status=custody_status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    # ----------------------------------------------------------- maneuvers
    def create_maneuver(self, session_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/test-sessions/{session_id}/maneuvers", payload, headers
        )

    def list_session_maneuvers(
        self,
        session_id: str,
        headers: dict,
        phase: Optional[str] = None,
        acceptability: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/test-sessions/{session_id}/maneuvers",
            _query(phase=phase, acceptability=acceptability, limit=limit, offset=offset),
            headers,
        )

    def get_maneuver(self, maneuver_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/maneuvers/{maneuver_id}", None, headers
        )

    def list_maneuvers(
        self,
        headers: dict,
        session_id: Optional[str] = None,
        phase: Optional[str] = None,
        acceptability: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/maneuvers",
            _query(
                session_id=session_id,
                phase=phase,
                acceptability=acceptability,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def finalize_session_quality(self, session_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{API_PREFIX}/test-sessions/{session_id}/finalize-quality",
            payload,
            headers,
        )

    # ------------------------------------------------------ custody events
    def create_custody_event(self, session_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{API_PREFIX}/test-sessions/{session_id}/custody-events",
            payload,
            headers,
        )

    def list_session_custody_events(
        self,
        session_id: str,
        headers: dict,
        event_type: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/test-sessions/{session_id}/custody-events",
            _query(event_type=event_type, limit=limit, offset=offset),
            headers,
        )

    def get_custody_event(self, event_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/custody-events/{event_id}", None, headers
        )

    def list_custody_events(
        self,
        headers: dict,
        session_id: Optional[str] = None,
        event_type: Optional[str] = None,
        actor_user_id: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/custody-events",
            _query(
                session_id=session_id,
                event_type=event_type,
                actor_user_id=actor_user_id,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    # ------------------------------------------------------ challenge runs
    def create_challenge_run(self, session_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{API_PREFIX}/test-sessions/{session_id}/challenge-runs",
            payload,
            headers,
        )

    def get_challenge_run(self, run_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/challenge-runs/{run_id}", None, headers
        )

    def list_challenge_runs(
        self,
        headers: dict,
        session_id: Optional[str] = None,
        rescue_lot_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/challenge-runs",
            _query(
                session_id=session_id,
                rescue_lot_id=rescue_lot_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def create_challenge_step(self, run_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/challenge-runs/{run_id}/steps", payload, headers
        )

    def abort_challenge_run(self, run_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{API_PREFIX}/challenge-runs/{run_id}/abort", payload, headers
        )

    # ------------------------------------------------ interpretation reports
    def create_interpretation_report(self, session_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{API_PREFIX}/test-sessions/{session_id}/interpretation-reports",
            payload,
            headers,
        )

    def get_interpretation_report(self, report_id: str, headers: dict):
        return self._request(
            "GET", f"{API_PREFIX}/interpretation-reports/{report_id}", None, headers
        )

    def list_interpretation_reports(
        self,
        headers: dict,
        session_id: Optional[str] = None,
        interpreter_staff_id: Optional[str] = None,
        superseded_by_report_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/interpretation-reports",
            _query(
                session_id=session_id,
                interpreter_staff_id=interpreter_staff_id,
                superseded_by_report_id=superseded_by_report_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def sign_interpretation_report(self, report_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{API_PREFIX}/interpretation-reports/{report_id}/sign",
            payload,
            headers,
        )

    def amend_interpretation_report(self, report_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{API_PREFIX}/interpretation-reports/{report_id}/amend",
            payload,
            headers,
        )

    # ------------------------------------------------------- logical clock
    def set_logical_clock(self, to_iso8601: str, headers: dict):
        return self._request(
            "POST",
            f"{API_PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )
