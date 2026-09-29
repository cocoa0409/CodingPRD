"""Composite scenario builders.

The server is restarted with an empty database before every test, so every
scenario has to be rebuilt from scratch through PRD-declared endpoints only.
These builders walk the workflow of PRD section 3 in order and hand back a
`Scenario` carrying the rows they created, so a test can start from the state it
actually cares about and still assert on everything upstream of it.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import DuctSealingApiClient
from .constants import (
    CLOCK_STARTUP_ISO,
    DECISION_ACCEPT,
    PHASE_POST,
    PHASE_PRE,
    SCREENING_CLEARED,
)
from .test_users import (
    ADMIN_HEADERS,
    INSPECTOR_HEADERS,
    QA_HEADERS,
    make_field_technician_headers,
)

#: The default injection curve: four points that fall to 55.0 CFM without ever
#: stalling and without ever reaching the injection-pressure cutoff.
DEFAULT_SAMPLES: Tuple[Tuple[int, float, int, float], ...] = (
    (1, 300.0, 0, 700.0),
    (2, 200.0, 240, 720.0),
    (3, 120.0, 480, 730.0),
    (4, 55.0, 720, 740.0),
)


@dataclass
class Scenario:
    """The rows a builder created, plus the headers needed to act on them."""

    api: DuctSealingApiClient
    program: Optional[Dict[str, Any]] = None
    technician: Optional[Dict[str, Any]] = None
    project: Optional[Dict[str, Any]] = None
    duct_systems: List[Dict[str, Any]] = field(default_factory=list)
    pre_tests: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    post_tests: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    seal_job: Optional[Dict[str, Any]] = None
    seal_jobs: List[Dict[str, Any]] = field(default_factory=list)
    report: Optional[Dict[str, Any]] = None
    claim: Optional[Dict[str, Any]] = None
    complaint: Optional[Dict[str, Any]] = None

    # -- convenient handles ------------------------------------------------
    @property
    def duct_system(self) -> Dict[str, Any]:
        assert self.duct_systems, "no duct system has been created yet"
        return self.duct_systems[0]

    @property
    def program_id(self) -> str:
        assert self.program is not None, "this scenario has no utility program"
        return self.program["id"]

    @property
    def project_id(self) -> str:
        assert self.project is not None
        return self.project["id"]

    @property
    def duct_system_id(self) -> str:
        return self.duct_system["id"]

    @property
    def technician_id(self) -> str:
        assert self.technician is not None
        return self.technician["id"]

    @property
    def seal_job_id(self) -> str:
        assert self.seal_job is not None
        return self.seal_job["id"]

    @property
    def report_id(self) -> str:
        assert self.report is not None
        return self.report["id"]

    @property
    def claim_id(self) -> str:
        assert self.claim is not None
        return self.claim["id"]

    @property
    def complaint_id(self) -> str:
        assert self.complaint is not None
        return self.complaint["id"]

    @property
    def tech_headers(self) -> Dict[str, str]:
        return make_field_technician_headers(self.technician_id)

    @property
    def pre_test(self) -> Dict[str, Any]:
        return self.pre_tests[self.duct_system_id]

    @property
    def post_test(self) -> Dict[str, Any]:
        return self.post_tests[self.duct_system_id]

    # -- fresh reads -------------------------------------------------------
    def read_program(self) -> Dict[str, Any]:
        return get_success_data(self.api.get_utility_program(self.program_id, ADMIN_HEADERS))

    def read_technician(self) -> Dict[str, Any]:
        return get_success_data(self.api.get_technician(self.technician_id, ADMIN_HEADERS))

    def read_project(self) -> Dict[str, Any]:
        return get_success_data(self.api.get_project(self.project_id, ADMIN_HEADERS))

    def read_duct_system(self, duct_system_id: Optional[str] = None) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_duct_system(duct_system_id or self.duct_system_id, ADMIN_HEADERS)
        )

    def read_seal_job(self, seal_job_id: Optional[str] = None) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_seal_job(seal_job_id or self.seal_job_id, ADMIN_HEADERS)
        )

    def read_report(self, report_id: Optional[str] = None) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_verification_report(report_id or self.report_id, ADMIN_HEADERS)
        )

    def read_claim(self, claim_id: Optional[str] = None) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_rebate_claim(claim_id or self.claim_id, ADMIN_HEADERS)
        )

    def read_complaint(self, complaint_id: Optional[str] = None) -> Dict[str, Any]:
        assert complaint_id or self.complaint is not None
        return get_success_data(
            self.api.get_comfort_complaint(
                complaint_id or self.complaint["id"], ADMIN_HEADERS
            )
        )

    def duct_system_version(self, duct_system_id: Optional[str] = None) -> int:
        return self.read_duct_system(duct_system_id)["version"]

    def seal_job_version(self, seal_job_id: Optional[str] = None) -> int:
        return self.read_seal_job(seal_job_id)["version"]


# ---------------------------------------------------------------------------
# Step builders — each one advances a scenario by exactly one workflow step
# ---------------------------------------------------------------------------
def set_clock(api: DuctSealingApiClient, to_iso8601: str = CLOCK_STARTUP_ISO) -> None:
    """Move the logical clock, "an administrative test-driving capability"."""
    get_success_data(api.set_clock(to_iso8601, ADMIN_HEADERS))


def add_program(sc: Scenario, **overrides: Any) -> Dict[str, Any]:
    sc.program = get_success_data(
        sc.api.create_utility_program(f.utility_program_payload(**overrides), ADMIN_HEADERS),
        201,
    )
    return sc.program


def add_technician(sc: Scenario, **overrides: Any) -> Dict[str, Any]:
    tech = get_success_data(
        sc.api.create_technician(f.technician_payload(**overrides), ADMIN_HEADERS), 201
    )
    if sc.technician is None:
        sc.technician = tech
    return tech


def add_project(sc: Scenario, **overrides: Any) -> Dict[str, Any]:
    payload = f.project_payload(**overrides)
    if "utility_program_id" not in payload and sc.program is not None:
        payload["utility_program_id"] = sc.program["id"]
    sc.project = get_success_data(sc.api.create_project(payload, ADMIN_HEADERS), 201)
    return sc.project


def add_duct_system(
    sc: Scenario, clear_screening: bool = True, lab_reference: str = "LAB-1001", **overrides: Any
) -> Dict[str, Any]:
    """Catalogue one duct system and, by default, clear its asbestos screening."""
    duct_system = get_success_data(
        sc.api.create_duct_system(
            sc.project_id, f.duct_system_payload(**overrides), ADMIN_HEADERS
        ),
        201,
    )
    if clear_screening:
        duct_system = get_success_data(
            sc.api.record_asbestos_screening(
                duct_system["id"],
                f.asbestos_screening_payload(
                    asbestos_screening_result=SCREENING_CLEARED,
                    lab_reference=lab_reference,
                ),
                QA_HEADERS,
            )
        )
    sc.duct_systems.append(duct_system)
    return duct_system


def add_accepted_leakage_test(
    sc: Scenario,
    duct_system: Optional[Dict[str, Any]] = None,
    phase: str = PHASE_PRE,
    measured_leakage_cfm: float = 300.0,
    test_pressure_pa: float = 25.0,
    ambient_temp_f: float = 78.0,
    fan_ring_config: Optional[str] = None,
    decision: str = DECISION_ACCEPT,
    **reservation_overrides: Any,
) -> Dict[str, Any]:
    """Walk one measurement from `DRAFT` through `PRESSURIZED` and `RECORDED` to
    its review outcome, and remember it against its duct system."""
    duct_system = duct_system or sc.duct_system
    if phase == PHASE_PRE:
        reservation = f.leakage_test_payload(duct_system["id"], **reservation_overrides)
    else:
        reservation = f.post_leakage_test_payload(
            duct_system["id"], **reservation_overrides
        )
    test = get_success_data(
        sc.api.create_leakage_test(reservation, sc.tech_headers), 201
    )
    pressurize = f.pressurize_payload(
        test_pressure_pa=test_pressure_pa,
        masked_register_count=duct_system["total_register_count"],
    )
    if fan_ring_config is not None:
        pressurize["fan_ring_config"] = fan_ring_config
    get_success_data(
        sc.api.pressurize_leakage_test(test["id"], pressurize, sc.tech_headers)
    )
    get_success_data(
        sc.api.record_leakage_test(
            test["id"],
            f.record_payload(
                measured_leakage_cfm=measured_leakage_cfm, ambient_temp_f=ambient_temp_f
            ),
            sc.tech_headers,
        )
    )
    reviewed = get_success_data(
        sc.api.review_leakage_test(
            test["id"], f.review_payload(decision=decision), QA_HEADERS
        )
    )
    if phase == PHASE_PRE:
        sc.pre_tests[duct_system["id"]] = reviewed
    else:
        sc.post_tests[duct_system["id"]] = reviewed
    return reviewed


def add_combustion_test(sc: Scenario, phase: str = PHASE_PRE, **overrides: Any) -> Dict[str, Any]:
    payload = (
        f.combustion_test_payload(**overrides)
        if phase == PHASE_PRE
        else f.post_combustion_test_payload(**overrides)
    )
    payload["phase"] = phase
    return get_success_data(
        sc.api.create_combustion_test(sc.project_id, payload, sc.tech_headers), 201
    )


def schedule_seal_job(
    sc: Scenario,
    duct_system: Optional[Dict[str, Any]] = None,
    pre_test: Optional[Dict[str, Any]] = None,
    technician: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Book a run, reading the duct system's live `version` for the OCC guard."""
    duct_system = duct_system or sc.duct_system
    pre_test = pre_test or sc.pre_tests[duct_system["id"]]
    technician = technician or sc.technician
    headers = make_field_technician_headers(technician["id"])
    payload = f.seal_job_payload(
        duct_system["id"],
        pre_test["id"],
        technician["id"],
        sc.duct_system_version(duct_system["id"]),
        **overrides,
    )
    job = get_success_data(sc.api.create_seal_job(payload, headers), 201)
    sc.seal_jobs.append(job)
    sc.seal_job = job
    return job


def mask_all_registers(
    sc: Scenario,
    seal_job: Optional[Dict[str, Any]] = None,
    duct_system: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Mask every register, since "`masked_register_count` equals the duct
    system's `total_register_count`" is a precondition of starting injection."""
    seal_job = seal_job or sc.seal_job
    duct_system = duct_system or sc.duct_system
    labels = f.register_labels(duct_system["total_register_count"])
    return get_success_data(
        sc.api.mask_registers(seal_job["id"], f.masks_payload(labels), sc.tech_headers)
    )


def begin_injection(sc: Scenario, seal_job: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    seal_job = seal_job or sc.seal_job
    return get_success_data(sc.api.start_injection(seal_job["id"], None, sc.tech_headers))


def stream_samples(
    sc: Scenario,
    samples: Sequence[Tuple[int, float, int, float]] = DEFAULT_SAMPLES,
    seal_job: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Append each `(sample_seq, cfm, elapsed_seconds, injection_pressure_pa)`."""
    seal_job = seal_job or sc.seal_job
    stored = []
    for seq, cfm, elapsed, pressure in samples:
        stored.append(
            get_success_data(
                sc.api.append_leakage_sample(
                    seal_job["id"],
                    f.leakage_sample_payload(seq, cfm, elapsed, pressure),
                    sc.tech_headers,
                ),
                201,
            )
        )
    return stored


def complete_seal(
    sc: Scenario, seal_job: Optional[Dict[str, Any]] = None, **overrides: Any
) -> Dict[str, Any]:
    seal_job = seal_job or sc.seal_job
    return get_success_data(
        sc.api.complete_seal(
            seal_job["id"], f.complete_seal_payload(**overrides), sc.tech_headers
        )
    )


def draft_report(
    sc: Scenario,
    seal_job: Optional[Dict[str, Any]] = None,
    post_test: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    seal_job = seal_job or sc.seal_job
    post_test = post_test or sc.post_tests[seal_job["duct_system_id"]]
    payload = f.verification_report_payload(
        seal_job["id"], post_test["id"], sc.seal_job_version(seal_job["id"]), **overrides
    )
    sc.report = get_success_data(sc.api.create_verification_report(payload, QA_HEADERS), 201)
    return sc.report


def issue_report(
    sc: Scenario, report: Optional[Dict[str, Any]] = None, headers=None, **overrides: Any
) -> Dict[str, Any]:
    report = report or sc.report
    issued = get_success_data(
        sc.api.issue_verification_report(
            report["id"], f.issue_payload(**overrides), headers or QA_HEADERS
        )
    )
    if sc.report is not None and sc.report["id"] == report["id"]:
        sc.report = issued
    return issued


def submit_claim(sc: Scenario, report: Optional[Dict[str, Any]] = None, **overrides: Any) -> Dict[str, Any]:
    report = report or sc.report
    payload = f.rebate_claim_payload(report["id"], sc.program_id, **overrides)
    sc.claim = get_success_data(sc.api.create_rebate_claim(payload, ADMIN_HEADERS), 201)
    return sc.claim


def record_spot_check(sc: Scenario, **overrides: Any) -> Dict[str, Any]:
    sc.claim = get_success_data(
        sc.api.record_inspector_verification(
            sc.claim_id, f.inspector_verification_payload(**overrides), INSPECTOR_HEADERS
        )
    )
    return sc.claim


def add_complaint(sc: Scenario, **overrides: Any) -> Dict[str, Any]:
    complaint = get_success_data(
        sc.api.create_comfort_complaint(
            f.comfort_complaint_payload(sc.project_id, **overrides), ADMIN_HEADERS
        ),
        201,
    )
    if sc.complaint is None:
        sc.complaint = complaint
    return complaint


def diagnose_complaint(
    sc: Scenario, complaint: Optional[Dict[str, Any]] = None, **overrides: Any
) -> Dict[str, Any]:
    complaint = complaint or sc.complaint
    return get_success_data(
        sc.api.diagnose_comfort_complaint(
            complaint["id"], f.diagnose_payload(**overrides), sc.tech_headers
        )
    )


def add_airflow_reading(
    sc: Scenario,
    room_label: str,
    reading_seq: int,
    measured_cfm: float,
    design_cfm: float = 120.0,
    complaint: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    complaint = complaint or sc.complaint
    return get_success_data(
        sc.api.create_airflow_reading(
            complaint["id"],
            f.airflow_reading_payload(
                room_label, reading_seq, measured_cfm, design_cfm, **overrides
            ),
            sc.tech_headers,
        ),
        201,
    )


def enter_balancing(
    sc: Scenario, complaint: Optional[Dict[str, Any]] = None, **overrides: Any
) -> Dict[str, Any]:
    complaint = complaint or sc.complaint
    return get_success_data(
        sc.api.balance_comfort_complaint(
            complaint["id"], f.balance_payload(**overrides), sc.tech_headers
        )
    )


# ---------------------------------------------------------------------------
# Tiered composite scenarios
# ---------------------------------------------------------------------------
def scenario_base(
    api: DuctSealingApiClient,
    *,
    with_program: bool = True,
    clock: Optional[str] = CLOCK_STARTUP_ISO,
    program: Optional[Dict[str, Any]] = None,
    technician: Optional[Dict[str, Any]] = None,
    project: Optional[Dict[str, Any]] = None,
) -> Scenario:
    """Tier 1: the commercial frame — program (optional), technician, project."""
    sc = Scenario(api=api)
    if clock is not None:
        set_clock(api, clock)
    if with_program:
        add_program(sc, **(program or {}))
    add_technician(sc, **(technician or {}))
    project_overrides = dict(project or {})
    if not with_program:
        project_overrides.setdefault("utility_program_id", None)
    add_project(sc, **project_overrides)
    return sc


def scenario_eligible_system(
    api: DuctSealingApiClient,
    *,
    duct_system: Optional[Dict[str, Any]] = None,
    clear_screening: bool = True,
    **base: Any,
) -> Scenario:
    """Tier 2: one catalogued duct system, screened `CLEARED` and so `ELIGIBLE`."""
    sc = scenario_base(api, **base)
    add_duct_system(sc, clear_screening=clear_screening, **(duct_system or {}))
    return sc


def scenario_with_baseline(
    api: DuctSealingApiClient,
    *,
    pre: Optional[Dict[str, Any]] = None,
    **upstream: Any,
) -> Scenario:
    """Tier 3: an accepted `PRE` measurement, so the leakage ledger has a baseline."""
    sc = scenario_eligible_system(api, **upstream)
    add_accepted_leakage_test(sc, phase=PHASE_PRE, **(pre or {}))
    return sc


def scenario_ready_to_inject(
    api: DuctSealingApiClient,
    *,
    combustion: Optional[Dict[str, Any]] = None,
    with_combustion: bool = True,
    **upstream: Any,
) -> Scenario:
    """Tier 3b: baseline plus the pre-phase combustion coverage injection needs."""
    sc = scenario_with_baseline(api, **upstream)
    if with_combustion:
        add_combustion_test(sc, phase=PHASE_PRE, **(combustion or {}))
    return sc


def scenario_scheduled_job(
    api: DuctSealingApiClient,
    *,
    job: Optional[Dict[str, Any]] = None,
    **upstream: Any,
) -> Scenario:
    """Tier 4: a booked run sitting in `SCHEDULED`."""
    sc = scenario_ready_to_inject(api, **upstream)
    schedule_seal_job(sc, **(job or {}))
    return sc


def scenario_masking_job(api: DuctSealingApiClient, **upstream: Any) -> Scenario:
    """Tier 4b: every register masked, so the run sits in `MASKING`."""
    sc = scenario_scheduled_job(api, **upstream)
    mask_all_registers(sc)
    return sc


def scenario_injecting_job(api: DuctSealingApiClient, **upstream: Any) -> Scenario:
    """Tier 5: the run is `INJECTING` and the duct system is `SEALING`."""
    sc = scenario_masking_job(api, **upstream)
    begin_injection(sc)
    return sc


def scenario_sealed_job(
    api: DuctSealingApiClient,
    *,
    samples: Sequence[Tuple[int, float, int, float]] = DEFAULT_SAMPLES,
    seal: Optional[Dict[str, Any]] = None,
    **upstream: Any,
) -> Scenario:
    """Tier 5b: the curve has been streamed and the run closed out to `SEALED`."""
    sc = scenario_injecting_job(api, **upstream)
    stream_samples(sc, samples)
    complete_seal(sc, **(seal or {}))
    return sc


def scenario_post_verified(
    api: DuctSealingApiClient,
    *,
    post: Optional[Dict[str, Any]] = None,
    post_combustion: Optional[Dict[str, Any]] = None,
    with_post_combustion: bool = True,
    **upstream: Any,
) -> Scenario:
    """Tier 5c: a sealed run plus its accepted `POST` measurement and coverage."""
    sc = scenario_sealed_job(api, **upstream)
    add_accepted_leakage_test(
        sc, phase=PHASE_POST, **({"measured_leakage_cfm": 55.0} | (post or {}))
    )
    if with_post_combustion:
        add_combustion_test(sc, phase=PHASE_POST, **(post_combustion or {}))
    return sc


def scenario_draft_report(
    api: DuctSealingApiClient, *, report: Optional[Dict[str, Any]] = None, **upstream: Any
) -> Scenario:
    """Tier 6: the verification report exists in `DRAFT` with frozen numbers."""
    sc = scenario_post_verified(api, **upstream)
    draft_report(sc, **(report or {}))
    return sc


def scenario_issued_report(
    api: DuctSealingApiClient, *, issue: Optional[Dict[str, Any]] = None, **upstream: Any
) -> Scenario:
    """Tier 6b: the report is `ISSUED`, the run `VERIFIED`, the system `VERIFIED`."""
    sc = scenario_draft_report(api, **upstream)
    issue_report(sc, **(issue or {}))
    return sc


def scenario_submitted_claim(
    api: DuctSealingApiClient, *, claim: Optional[Dict[str, Any]] = None, **upstream: Any
) -> Scenario:
    """Tier 7: the rebate claim is `SUBMITTED` and its payable amount committed."""
    sc = scenario_issued_report(api, **upstream)
    submit_claim(sc, **(claim or {}))
    return sc
