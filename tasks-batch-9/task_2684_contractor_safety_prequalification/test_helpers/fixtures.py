"""Composite state builders and pytest fixtures.

Every test starts against an empty database, so all state is built through
declared endpoints. The builder below climbs the lifecycle in tiers: single
rows, then insured contractors, then submitted prequalifications, then graded
standings, then badged workers.
"""

from typing import Dict, Iterable, List, Optional, Sequence

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_success

from . import factories as f
from .api_client import SafetyPrequalApiClient
from .api_errors import install_error_status_map
from .constants import (
    ANALYST_INSURANCE,
    ANALYST_STATISTICS,
    HAZARD_REQUIRED_PROGRAMS,
    HAZARD_REQUIRED_QUALIFICATIONS,
    INITIAL_CLOCK,
)
from .test_users import (
    make_analyst_headers,
    make_client_manager_headers,
    make_contractor_admin_headers,
    make_network_admin_headers,
)


class ScenarioBuilder:
    """Drives the public API to assemble the state a test needs."""

    def __init__(self, api: SafetyPrequalApiClient):
        self.api = api
        self.admin_headers = make_network_admin_headers()
        self.insurance_analyst_headers = make_analyst_headers(ANALYST_INSURANCE)
        self.statistics_analyst_headers = make_analyst_headers(ANALYST_STATISTICS)

    # -- identity shortcuts ---------------------------------------------

    def contractor_headers(self, contractor_id: str) -> dict:
        return make_contractor_admin_headers(contractor_id)

    def manager_headers(self, client_id: str) -> dict:
        return make_client_manager_headers(client_id)

    # -- tier 1: single rows --------------------------------------------

    def set_clock(self, instant: str) -> dict:
        return get_success_data(
            self.api.set_clock(f.clock_payload(instant), self.admin_headers)
        )

    def create_client(self, **overrides) -> dict:
        return get_success_data(
            self.api.create_client(f.client_payload(**overrides), self.admin_headers)
        )

    def create_site(self, client_id: str, **overrides) -> dict:
        return get_success_data(
            self.api.create_site(
                client_id, f.site_payload(**overrides), self.manager_headers(client_id)
            )
        )

    def create_contractor(self, **overrides) -> dict:
        return get_success_data(
            self.api.create_contractor(
                f.contractor_payload(**overrides), self.admin_headers
            )
        )

    def read_contractor(self, contractor_id: str) -> dict:
        return validate_success(
            self.api.get_contractor(contractor_id, self.admin_headers)
        )

    def read_prequalification(self, prequalification_id: str, headers: Optional[dict] = None) -> dict:
        return validate_success(
            self.api.get_prequalification(
                prequalification_id, headers or self.admin_headers
            )
        )

    def create_worker(self, contractor_id: str, **overrides) -> dict:
        return get_success_data(
            self.api.create_worker(
                contractor_id,
                f.worker_payload(**overrides),
                self.contractor_headers(contractor_id),
            )
        )

    def add_qualification(self, worker_id: str, contractor_id: str, **overrides) -> dict:
        return get_success_data(
            self.api.create_qualification(
                worker_id,
                f.qualification_payload(**overrides),
                self.contractor_headers(contractor_id),
            )
        )

    def file_certificate(self, contractor_id: str, coverage_type: str = "GL", **overrides) -> dict:
        return get_success_data(
            self.api.create_certificate(
                contractor_id,
                f.certificate_payload(coverage_type, **overrides),
                self.contractor_headers(contractor_id),
            )
        )

    def decide_certificate(
        self, certificate_id: str, decision: str = "VERIFY", analyst_id: str = ANALYST_INSURANCE
    ) -> dict:
        return get_success_data(
            self.api.verify_certificate(
                certificate_id,
                f.certificate_decision_payload(decision),
                make_analyst_headers(analyst_id),
            )
        )

    def verified_certificate(
        self, contractor_id: str, coverage_type: str = "GL", **overrides
    ) -> dict:
        row = self.file_certificate(contractor_id, coverage_type, **overrides)
        return self.decide_certificate(row["id"])

    # -- tier 2: insured contractors and crews ---------------------------

    def insure(
        self, contractor_id: str, coverage_types: Sequence[str] = ("GL", "WC"), **overrides
    ) -> Dict[str, dict]:
        """File and verify one adequate certificate per coverage type."""
        certificates: Dict[str, dict] = {}
        for coverage_type in coverage_types:
            certificates[coverage_type] = self.verified_certificate(
                contractor_id, coverage_type, **overrides
            )
        return certificates

    def worker_with_qualifications(
        self,
        contractor_id: str,
        qualification_codes: Iterable[str] = ("OSHA10",),
        full_name: str = "Dana Ruiz",
        employee_ref: str = "EMP-1001",
        trade_code: str = "MECHANICAL_TRADE",
        expiration_date: str = "2029-01-15T00:00:00Z",
        issued_date: str = "2026-01-15T00:00:00Z",
    ) -> dict:
        worker = self.create_worker(
            contractor_id,
            full_name=full_name,
            employee_ref=employee_ref,
            trade_code=trade_code,
        )
        for code in qualification_codes:
            self.add_qualification(
                worker["id"],
                contractor_id,
                qualification_code=code,
                issued_date=issued_date,
                expiration_date=expiration_date,
                evidence_ref=f"CERT-{code}-{employee_ref}",
            )
        return worker

    def qualifications_for_site(self, hazard_classes: Iterable[str]) -> List[str]:
        """The credential demand a site's hazard classes add up to."""
        demanded: List[str] = []
        for hazard in hazard_classes:
            for code in HAZARD_REQUIRED_QUALIFICATIONS[hazard]:
                if code not in demanded:
                    demanded.append(code)
        return sorted(demanded)

    def programs_for_profile(self, hazard_profile: Iterable[str]) -> List[str]:
        """The written-program demand a contractor's hazard profile adds up to."""
        required: List[str] = []
        for hazard in hazard_profile:
            for program_type in HAZARD_REQUIRED_PROGRAMS[hazard]:
                if program_type not in required:
                    required.append(program_type)
        return required

    # -- tier 3: prequalification lifecycle ------------------------------

    def open_prequalification(
        self,
        contractor_id: str,
        client_id: str,
        cycle_year: int = 2026,
        expected_contractor_version: Optional[int] = None,
    ) -> dict:
        if expected_contractor_version is None:
            expected_contractor_version = self.read_contractor(contractor_id)["version"]
        return get_success_data(
            self.api.create_prequalification(
                f.prequalification_payload(
                    contractor_id, client_id, expected_contractor_version, cycle_year
                ),
                self.contractor_headers(contractor_id),
            )
        )

    def file_statistic(self, prequalification_id: str, contractor_id: str, **overrides) -> dict:
        return get_success_data(
            self.api.create_statistic(
                prequalification_id,
                f.statistic_payload(**overrides),
                self.contractor_headers(contractor_id),
            )
        )

    def decide_statistic(
        self, statistic_id: str, decision: str = "VERIFY", analyst_id: str = ANALYST_STATISTICS
    ) -> dict:
        return get_success_data(
            self.api.verify_statistic(
                statistic_id,
                f.statistic_decision_payload(decision),
                make_analyst_headers(analyst_id),
            )
        )

    def verified_statistic(
        self, prequalification_id: str, contractor_id: str, analyst_id: str = ANALYST_STATISTICS, **overrides
    ) -> dict:
        row = self.file_statistic(prequalification_id, contractor_id, **overrides)
        return self.decide_statistic(row["id"], "VERIFY", analyst_id)

    def tender_program(
        self, prequalification_id: str, contractor_id: str, program_type: str = "HAZCOM", **overrides
    ) -> dict:
        return get_success_data(
            self.api.create_program(
                prequalification_id,
                f.program_payload(program_type, **overrides),
                self.contractor_headers(contractor_id),
            )
        )

    def review_program(
        self, program_id: str, client_id: str, decision: str = "ACCEPT", reviewer_note: Optional[str] = None
    ) -> dict:
        return get_success_data(
            self.api.review_program(
                program_id,
                f.program_review_payload(decision, reviewer_note),
                self.manager_headers(client_id),
            )
        )

    def accept_required_programs(
        self,
        prequalification_id: str,
        contractor_id: str,
        client_id: str,
        hazard_profile: Sequence[str] = ("GENERAL",),
    ) -> Dict[str, dict]:
        accepted: Dict[str, dict] = {}
        for program_type in self.programs_for_profile(hazard_profile):
            row = self.tender_program(prequalification_id, contractor_id, program_type)
            accepted[program_type] = self.review_program(row["id"], client_id, "ACCEPT")
        return accepted

    def submit_prequalification(self, prequalification_id: str, contractor_id: str) -> dict:
        return get_success_data(
            self.api.submit_prequalification(
                prequalification_id, {}, self.contractor_headers(contractor_id)
            )
        )

    def grade_prequalification(self, prequalification_id: str, client_id: str) -> dict:
        return get_success_data(
            self.api.grade_prequalification(
                prequalification_id, {}, self.manager_headers(client_id)
            )
        )

    # -- tier 4: badges, incidents and edges -----------------------------

    def grant_badge(
        self,
        worker_id: str,
        site_id: str,
        prequalification_id: str,
        contractor_id: str,
        expires_at: str = "2026-12-31T00:00:00Z",
    ) -> dict:
        return get_success_data(
            self.api.create_grant(
                f.grant_payload(worker_id, site_id, prequalification_id, expires_at),
                self.contractor_headers(contractor_id),
            )
        )

    def revoke_badge(self, grant_id: str, client_id: str, reason: Optional[str] = "CLIENT_REVOKED") -> dict:
        return get_success_data(
            self.api.revoke_grant(
                grant_id, f.revoke_payload(reason), self.manager_headers(client_id)
            )
        )

    def file_incident(
        self,
        client_id: str,
        contractor_id: str,
        site_id: str,
        severity: str = "RECORDABLE",
        occurred_at: str = "2026-08-01T00:00:00Z",
        description: str = "Struck-by injury during pipe rigging",
    ) -> dict:
        return get_success_data(
            self.api.create_incident(
                f.incident_payload(
                    contractor_id,
                    site_id,
                    severity=severity,
                    occurred_at=occurred_at,
                    description=description,
                ),
                self.manager_headers(client_id),
            )
        )

    def close_incident(self, incident_id: str, client_id: str, note: str = "Root cause addressed") -> dict:
        return get_success_data(
            self.api.close_incident_review(
                incident_id, f.close_review_payload(note), self.manager_headers(client_id)
            )
        )

    def create_link(
        self,
        parent_contractor_id: str,
        child_contractor_id: str,
        prequalification_id: str,
        acting_contractor_id: str,
        scope_of_work: Optional[List[str]] = None,
    ) -> dict:
        return get_success_data(
            self.api.create_link(
                f.link_payload(
                    parent_contractor_id,
                    child_contractor_id,
                    prequalification_id,
                    scope_of_work,
                ),
                self.contractor_headers(acting_contractor_id),
            )
        )

    # -- tier 5: whole standings ----------------------------------------

    def graded_standing(
        self,
        client_overrides: Optional[dict] = None,
        contractor_overrides: Optional[dict] = None,
        statistic_overrides: Optional[dict] = None,
        certificate_overrides: Optional[dict] = None,
        site_overrides: Optional[dict] = None,
        coverage_types: Sequence[str] = ("GL", "WC"),
        cycle_year: int = 2026,
        with_site: bool = True,
        with_worker: bool = True,
        submit: bool = True,
        grade: bool = True,
    ) -> dict:
        """Build a client, an insured contractor and one prequalification.

        The prequalification is carried as far as the flags ask: filed and
        verified statistic, accepted required programs, submitted, graded.
        """
        client = self.create_client(**(client_overrides or {}))
        contractor = self.create_contractor(**(contractor_overrides or {}))
        hazard_profile = contractor["hazard_profile"]

        certificates = self.insure(
            contractor["id"], coverage_types, **(certificate_overrides or {})
        )

        site = None
        worker = None
        if with_site:
            site = self.create_site(client["id"], **(site_overrides or {}))
        if with_worker:
            hazard_classes = site["required_hazard_classes"] if site else ["GENERAL"]
            worker = self.worker_with_qualifications(
                contractor["id"], self.qualifications_for_site(hazard_classes)
            )

        prequalification = self.open_prequalification(
            contractor["id"], client["id"], cycle_year
        )
        statistic = self.verified_statistic(
            prequalification["id"], contractor["id"], **(statistic_overrides or {})
        )
        programs = self.accept_required_programs(
            prequalification["id"], contractor["id"], client["id"], hazard_profile
        )
        if submit:
            prequalification = self.submit_prequalification(
                prequalification["id"], contractor["id"]
            )
        if submit and grade:
            prequalification = self.grade_prequalification(
                prequalification["id"], client["id"]
            )

        return {
            "client": client,
            "client_id": client["id"],
            "contractor": contractor,
            "contractor_id": contractor["id"],
            "certificates": certificates,
            "site": site,
            "site_id": site["id"] if site else None,
            "worker": worker,
            "worker_id": worker["id"] if worker else None,
            "prequalification": prequalification,
            "prequalification_id": prequalification["id"],
            "statistic": statistic,
            "statistic_id": statistic["id"],
            "programs": programs,
            "manager_headers": self.manager_headers(client["id"]),
            "contractor_headers": self.contractor_headers(contractor["id"]),
            "admin_headers": self.admin_headers,
        }


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def api() -> SafetyPrequalApiClient:
    """The endpoint client, with the error catalogue registered."""
    install_error_status_map()
    return SafetyPrequalApiClient()


@pytest.fixture
def build(api: SafetyPrequalApiClient) -> ScenarioBuilder:
    """Composite state builder driving the public endpoints."""
    return ScenarioBuilder(api)


@pytest.fixture
def admin_headers() -> dict:
    return make_network_admin_headers()


@pytest.fixture
def insurance_analyst_headers() -> dict:
    return make_analyst_headers(ANALYST_INSURANCE)


@pytest.fixture
def statistics_analyst_headers() -> dict:
    return make_analyst_headers(ANALYST_STATISTICS)


@pytest.fixture
def initial_clock() -> str:
    """The instant the service starts at."""
    return INITIAL_CLOCK


@pytest.fixture
def insured_contractor(build: ScenarioBuilder) -> dict:
    """A client plus a tier-1 contractor holding verified GL and WC coverage."""
    client = build.create_client()
    contractor = build.create_contractor()
    certificates = build.insure(contractor["id"])
    return {
        "client": client,
        "client_id": client["id"],
        "contractor": contractor,
        "contractor_id": contractor["id"],
        "certificates": certificates,
        "manager_headers": build.manager_headers(client["id"]),
        "contractor_headers": build.contractor_headers(contractor["id"]),
    }


@pytest.fixture
def submitted_standing(build: ScenarioBuilder) -> dict:
    """A prequalification sitting in review with both dimensions satisfied."""
    return build.graded_standing(grade=False)


@pytest.fixture
def approved_standing(build: ScenarioBuilder) -> dict:
    """The canonical approved standing: score 80.51, grade B, one badgeable worker."""
    return build.graded_standing()
