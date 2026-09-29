"""Composable setup builders.

The harness restarts the API server before every test, so each fixture starts
from an empty database and rebuilds all of its preconditions through the
endpoints the PRD declares. Nothing is seeded out of band.

`TriageWorld` is a thin recorder over `ApiClient`: each method performs one
declared call, remembers the resource it produced, and returns the resource
body. Internal steps use the lenient `get_success_data` so that a *setup*
failure surfaces as a setup error rather than masquerading as the assertion
under test.
"""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient, api_client
from .constants import CLOCK_DEFAULT_UTC
from .test_users import (
    make_charge_nurse_headers,
    make_compliance_auditor_headers,
    make_intake_agent_headers,
    make_platform_admin_headers,
    make_practice_liaison_headers,
    make_triage_nurse_headers,
)


class TriageWorld:
    """Builds triage-call scenarios out of PRD-declared endpoint calls."""

    def __init__(self, client: ApiClient):
        self.api = client
        self.admin = make_platform_admin_headers()
        self.intake = make_intake_agent_headers()
        self.auditor = make_compliance_auditor_headers()
        self.practice_id: Optional[str] = None
        self.nurses: Dict[str, Dict[str, Any]] = {}
        self.protocols: Dict[str, Dict[str, Any]] = {}
        self.patients: Dict[str, Dict[str, Any]] = {}
        self.calls: List[Dict[str, Any]] = []

    # ── The logical clock (PRD §2.4) ───────────────────────────────────────
    def set_clock(self, to_iso8601: str) -> Dict[str, Any]:
        return get_success_data(self.api.set_clock(to_iso8601))

    # ── Practice, patients, protocols ─────────────────────────────────────
    def create_practice(self, **overrides: Any) -> Dict[str, Any]:
        practice = get_success_data(
            self.api.create_practice(f.practice_payload(**overrides), self.admin)
        )
        self.practice_id = practice["id"]
        return practice

    def practice(self, practice_id: Optional[str] = None) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_practice(practice_id or self.practice_id, self.admin)
        )

    def suspend_practice(self, practice_id: Optional[str] = None) -> Dict[str, Any]:
        return get_success_data(
            self.api.patch_practice_status(
                practice_id or self.practice_id,
                f.practice_status_payload("SUSPENDED"),
                self.admin,
            )
        )

    def create_patient(
        self, key: str = "patient", practice_id: Optional[str] = None, **overrides: Any
    ) -> Dict[str, Any]:
        patient = get_success_data(
            self.api.create_patient(
                practice_id or self.practice_id,
                f.patient_payload(**overrides),
                self.admin,
            )
        )
        self.patients[key] = patient
        return patient

    def create_protocol(self, key: str = "protocol", **overrides: Any) -> Dict[str, Any]:
        protocol = get_success_data(
            self.api.create_protocol(f.protocol_payload(**overrides), self.admin)
        )
        self.protocols[key] = protocol
        return protocol

    def retire_protocol(self, protocol_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.retire_protocol(protocol_id, {}, self.admin))

    # ── Nurses ────────────────────────────────────────────────────────────
    def create_nurse(self, key: str = "nurse_a", **overrides: Any) -> Dict[str, Any]:
        nurse = get_success_data(
            self.api.create_nurse(f.nurse_payload(**overrides), self.admin)
        )
        self.nurses[key] = nurse
        return nurse

    def nurse(self, key_or_id: str) -> Dict[str, Any]:
        nurse_id = self.nurses[key_or_id]["id"] if key_or_id in self.nurses else key_or_id
        return get_success_data(self.api.get_nurse(nurse_id, self.admin))

    def nurse_id(self, key: str) -> str:
        return self.nurses[key]["id"]

    def add_license(self, nurse_key: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_license(
                self.nurse_id(nurse_key), f.license_payload(**overrides), self.admin
            )
        )

    def licenses(self, nurse_key: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.list_licenses(self.nurse_id(nurse_key), self.admin)
        )

    def add_shift(self, nurse_key: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_shift(
                self.nurse_id(nurse_key), f.shift_payload(**overrides), self.admin
            )
        )

    def nurse_headers(self, nurse_key: str) -> Dict[str, str]:
        return make_triage_nurse_headers(self.nurse_id(nurse_key))

    def charge_headers(self, nurse_key: str) -> Dict[str, str]:
        return make_charge_nurse_headers(self.nurse_id(nurse_key))

    def liaison_headers(self, practice_id: Optional[str] = None) -> Dict[str, str]:
        return make_practice_liaison_headers(practice_id or self.practice_id)

    # ── Coverage windows ──────────────────────────────────────────────────
    def create_coverage_window(
        self, practice_id: Optional[str] = None, as_liaison: bool = False, **overrides: Any
    ) -> Dict[str, Any]:
        pid = practice_id or self.practice_id
        headers = self.liaison_headers(pid) if as_liaison else self.admin
        return get_success_data(
            self.api.create_coverage_window(
                f.coverage_window_payload(pid, **overrides), headers
            )
        )

    def activate_coverage_window(
        self, window_id: str, as_liaison_for: Optional[str] = None
    ) -> Dict[str, Any]:
        headers = (
            self.liaison_headers(as_liaison_for) if as_liaison_for else self.admin
        )
        return get_success_data(
            self.api.activate_coverage_window(window_id, {}, headers)
        )

    def active_coverage(self, **overrides: Any) -> Dict[str, Any]:
        """Draft a coverage window and activate it in one step."""
        window = self.create_coverage_window(**overrides)
        return self.activate_coverage_window(window["id"])

    def coverage_window(self, window_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_coverage_window(window_id, self.admin))

    # ── Opening a call ────────────────────────────────────────────────────
    def open_call(self, practice_id: Optional[str] = None, **overrides: Any):
        call = get_success_data(
            self.api.create_triage_call(
                f.triage_call_payload(practice_id or self.practice_id, **overrides),
                self.intake,
            )
        )
        self.calls.append(call)
        return call

    def call(self, call_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_triage_call(call_id, self.admin))

    def call_version(self, call_id: str) -> int:
        return self.call(call_id)["version"]

    def match_patient(self, call_id: str, patient_id: str, **overrides: Any):
        return get_success_data(
            self.api.match_patient(
                call_id, f.match_patient_payload(patient_id, **overrides), self.intake
            )
        )

    def record_consent(self, call_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.record_consent(call_id, f.consent_payload(**overrides), self.intake)
        )

    def assign_nurse(
        self, call_id: str, preferred_nurse_key: Optional[str] = None, **overrides: Any
    ) -> Dict[str, Any]:
        preferred = (
            self.nurse_id(preferred_nurse_key) if preferred_nurse_key else None
        )
        return get_success_data(
            self.api.assign_nurse(
                call_id, f.assign_nurse_payload(preferred, **overrides), self.intake
            )
        )

    def abandon_call(self, call_id: str, as_intake: bool = True, **overrides: Any):
        return get_success_data(
            self.api.abandon_call(call_id, f.abandon_payload(**overrides), self.intake)
        )

    # ── Assessment and disposition ────────────────────────────────────────
    def create_assessment(
        self, call_id: str, nurse_key: str, protocol_key: str = "protocol", **overrides: Any
    ) -> Dict[str, Any]:
        protocol_id = self.protocols[protocol_key]["id"]
        payload = f.assessment_payload(protocol_id, **overrides)
        return get_success_data(
            self.api.create_assessment(call_id, payload, self.nurse_headers(nurse_key))
        )

    def create_provisional_assessment(
        self,
        call_id: str,
        nurse_key: str,
        protocol_key: str = "protocol",
        stated_age_years: int = 36,
        **overrides: Any,
    ) -> Dict[str, Any]:
        protocol_id = self.protocols[protocol_key]["id"]
        payload = f.provisional_assessment_payload(
            protocol_id, stated_age_years, **overrides
        )
        return get_success_data(
            self.api.create_assessment(call_id, payload, self.nurse_headers(nurse_key))
        )

    def assessment(self, assessment_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_assessment(assessment_id, self.admin))

    def create_disposition(
        self,
        call_id: str,
        assessment_id: str,
        final_level: str,
        nurse_key: str,
        expected_call_version: Optional[int] = None,
        **overrides: Any,
    ) -> Dict[str, Any]:
        version = (
            expected_call_version
            if expected_call_version is not None
            else self.call_version(call_id)
        )
        payload = f.disposition_payload(
            call_id, assessment_id, final_level, version, **overrides
        )
        return get_success_data(
            self.api.create_disposition(payload, self.nurse_headers(nurse_key))
        )

    def disposition(self, disposition_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_disposition(disposition_id, self.admin))

    def override_disposition(
        self, disposition_id: str, final_level: str, charge_nurse_key: str, **overrides: Any
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.override_disposition(
                disposition_id,
                f.override_payload(final_level, **overrides),
                self.charge_headers(charge_nurse_key),
            )
        )

    # ── Callback tasks ────────────────────────────────────────────────────
    def callback_for(self, disposition_id: str) -> Dict[str, Any]:
        """The callback task the disposition raised (PRD §3.8 listing filter)."""
        body = get_success_data(
            self.api.list_callback_tasks(
                self.admin, {"disposition_id": disposition_id}
            )
        )
        rows = body if isinstance(body, list) else body.get("data", body)
        assert rows, f"no callback task exists for disposition {disposition_id}"
        return rows[0]

    def callbacks_for(self, disposition_id: str) -> List[Dict[str, Any]]:
        body = get_success_data(
            self.api.list_callback_tasks(
                self.admin, {"disposition_id": disposition_id}
            )
        )
        return body if isinstance(body, list) else body.get("data", body)

    def live_callback_for(self, disposition_id: str) -> Dict[str, Any]:
        """The disposition's still-workable callback task.

        PRD §3.6: when a disposition is overridden down to a less severe level the
        original task "flips to `CANCELLED`" and "a replacement task is created",
        so the disposition owns more than one row. Only a task whose `status` is
        `PENDING`, `ATTEMPTED` or `REACHED` may be attempted or verified, so that
        is the row a caller who intends to work the callback wants.
        """
        rows = self.callbacks_for(disposition_id)
        live = [r for r in rows if r["status"] in ("PENDING", "ATTEMPTED", "REACHED")]
        assert live, (
            f"no workable callback task exists for disposition {disposition_id}; "
            f"statuses seen: {[r['status'] for r in rows]}"
        )
        return live[-1]

    def callback(self, task_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_callback_task(task_id, self.admin))

    def record_attempt(
        self, task_id: str, nurse_key: str, outcome: str = "REACHED", **overrides: Any
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_callback_attempt(
                task_id,
                f.attempt_payload(outcome, **overrides),
                self.nurse_headers(nurse_key),
            )
        )

    def verify_callback(
        self,
        task_id: str,
        verifier_key: str,
        patient_condition: str = "IMPROVED",
        advice_followed: bool = True,
        **overrides: Any,
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.verify_callback(
                task_id,
                f.verify_payload(patient_condition, advice_followed, **overrides),
                self.nurse_headers(verifier_key),
            )
        )

    def reach_and_verify(
        self,
        disposition_id: str,
        advising_nurse_key: str,
        verifier_key: str,
        patient_condition: str = "IMPROVED",
        advice_followed: bool = True,
    ) -> Dict[str, Any]:
        """Attempt the callback, then verify it with a different nurse."""
        task = self.live_callback_for(disposition_id)
        self.record_attempt(task["id"], advising_nurse_key, "REACHED")
        return self.verify_callback(
            task["id"], verifier_key, patient_condition, advice_followed
        )

    # ── Warm transfer ─────────────────────────────────────────────────────
    def open_warm_transfer(self, call_id: str, nurse_key: str, **overrides: Any):
        return get_success_data(
            self.api.create_warm_transfer(
                call_id, f.warm_transfer_payload(**overrides), self.nurse_headers(nurse_key)
            )
        )

    def confirm_location(
        self, transfer_id: str, nurse_key: str, location_confidence_pct: int = 90
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.confirm_transfer_location(
                transfer_id,
                f.confirm_location_payload(location_confidence_pct),
                self.nurse_headers(nurse_key),
            )
        )

    def psap_response(
        self,
        transfer_id: str,
        accepted: bool = True,
        psap_incident_number: Optional[str] = "SFFD-2026-0001",
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.psap_response(
                transfer_id,
                f.psap_response_payload(accepted, psap_incident_number),
                self.intake,
            )
        )

    def complete_handoff(self, transfer_id: str, nurse_key: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.complete_handoff(transfer_id, {}, self.nurse_headers(nurse_key))
        )

    def warm_transfer(self, transfer_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_warm_transfer(transfer_id, self.admin))

    def full_warm_transfer(
        self, call_id: str, nurse_key: str, **overrides: Any
    ) -> Dict[str, Any]:
        """Open, attest, accept and hand off a transfer (PRD §3.7 order)."""
        transfer = self.open_warm_transfer(call_id, nurse_key, **overrides)
        self.confirm_location(transfer["id"], nurse_key)
        self.psap_response(transfer["id"], True)
        return self.complete_handoff(transfer["id"], nurse_key)

    # ── Closing and billing ───────────────────────────────────────────────
    def complete_call(
        self, call_id: str, nurse_key: str, handle_minutes: int = 13
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.complete_call(
                call_id,
                f.complete_payload(handle_minutes),
                self.nurse_headers(nurse_key),
            )
        )

    def reopen_call(self, call_id: str, charge_nurse_key: str, **overrides: Any):
        return get_success_data(
            self.api.reopen_call(
                call_id, f.reopen_payload(**overrides), self.charge_headers(charge_nurse_key)
            )
        )

    # ── Outcome audit and readouts ────────────────────────────────────────
    def file_audit_record(self, disposition_id: str, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_audit_record(
                disposition_id, f.audit_record_payload(**overrides), self.auditor
            )
        )

    def compliance_summary(self, practice_id: Optional[str] = None) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_compliance_summary(practice_id or self.practice_id, self.auditor)
        )

    def after_hours_invoice(self, practice_id: Optional[str] = None) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_after_hours_invoice(practice_id or self.practice_id, self.admin)
        )

    def staffing_adequacy(self, **overrides: Any) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_staffing_adequacy(self.admin, f.staffing_query(**overrides))
        )

    # ── Lifecycle shortcuts ───────────────────────────────────────────────
    def bootstrap(
        self,
        clock: str = "2026-08-03T14:30:00Z",
        nurse_keys: tuple = ("nurse_a",),
        practice: Optional[Dict[str, Any]] = None,
        protocol: Optional[Dict[str, Any]] = None,
        license_state: str = "CA",
        with_shifts: bool = True,
        license_expires_on: str = "2027-01-31",
        **nurse_overrides: Any,
    ) -> Dict[str, Any]:
        """Clock, practice, licensed nurses, one protocol and one patient.

        The clock is set first because the after-hours determination, licence
        status and shift status are all read from it (PRD §2.4). Each nurse is
        given a shift spanning the whole of the clock's calendar day so that the
        routing clause requiring "at least one `NurseShift` whose interval
        contains the logical clock" is satisfied.
        """
        self.set_clock(clock)
        day = clock[:10]
        shift_start = f"{day}T00:00:00Z"
        shift_end = f"{day[:8]}{int(day[8:10]) + 1:02d}T00:00:00Z"
        self.create_practice(**(practice or {}))
        names = {
            "nurse_a": "Nora Vance",
            "nurse_b": "Ben Ortiz",
            "nurse_c": "Cira Lund",
            "nurse_d": "Dot Nevins",
        }
        numbers = {
            "nurse_a": "11111",
            "nurse_b": "22222",
            "nurse_c": "33333",
            "nurse_d": "44444",
        }
        seniority = {"nurse_a": 3, "nurse_b": 4, "nurse_c": 2, "nurse_d": 1}
        for key in nurse_keys:
            self.create_nurse(
                key,
                full_name=names.get(key, key),
                seniority_level=seniority.get(key, 3),
                **nurse_overrides,
            )
            self.add_license(
                key,
                state_code=license_state,
                license_number=f"{license_state}-{numbers.get(key, '90000')}",
                expires_on=license_expires_on,
            )
            if with_shifts:
                self.add_shift(key, start_utc=shift_start, end_utc=shift_end)
        self.create_protocol("protocol", **(protocol or {}))
        self.create_patient("patient")
        return {
            "practice_id": self.practice_id,
            "protocol_id": self.protocols["protocol"]["id"],
            "patient_id": self.patients["patient"]["id"],
        }

    def call_through_consent(self, **overrides: Any) -> Dict[str, Any]:
        """Open a call, bind the chart and record consent (PRD §3.3 order)."""
        call = self.open_call(**overrides)
        self.match_patient(call["id"], self.patients["patient"]["id"])
        return self.record_consent(call["id"])

    def call_through_assignment(
        self, preferred_nurse_key: Optional[str] = None, **overrides: Any
    ) -> Dict[str, Any]:
        call = self.call_through_consent(**overrides)
        return self.assign_nurse(call["id"], preferred_nurse_key)

    def call_through_assessment(
        self,
        nurse_key: str = "nurse_a",
        protocol_key: str = "protocol",
        red_flag_count: int = 1,
        **overrides: Any,
    ) -> tuple:
        """Returns (call, assessment) with the call in ASSESSING."""
        call = self.call_through_assignment(nurse_key, **overrides)
        assessment = self.create_assessment(
            call["id"], nurse_key, protocol_key, red_flag_count=red_flag_count
        )
        return self.call(call["id"]), assessment

    def dispositioned_call(
        self,
        final_level: str,
        nurse_key: str = "nurse_a",
        protocol_key: str = "protocol",
        red_flag_count: int = 1,
        **overrides: Any,
    ) -> tuple:
        """Returns (call, assessment, disposition) with the call DISPOSITIONED."""
        call, assessment = self.call_through_assessment(
            nurse_key, protocol_key, red_flag_count, **overrides
        )
        disposition = self.create_disposition(
            call["id"], assessment["id"], final_level, nurse_key
        )
        return self.call(call["id"]), assessment, disposition


# ── pytest fixtures ────────────────────────────────────────────────────────
@pytest.fixture
def api() -> ApiClient:
    """The endpoint surface. Function-scoped: the server restarts per test."""
    return api_client


@pytest.fixture
def world(api: ApiClient) -> TriageWorld:
    """A scenario builder over an empty database."""
    return TriageWorld(api)


@pytest.fixture
def fresh_clock(api: ApiClient) -> str:
    """PRD §2.4: "On a freshly started server the logical clock reads
    `2026-08-01T00:00:00Z`"."""
    return CLOCK_DEFAULT_UTC
