"""Composite state builders and pytest fixtures.

The server is relaunched with an empty database before every single test, so
every scenario has to be built from scratch through the public API. The builders
below assemble the recurring shapes — credentialed officials, an agency-approved
program, an open term, a student with a verified certificate of eligibility, and
a certification that has been priced, submitted, certified and paid — and the
fixtures wrap the most frequently reused combinations.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import pytest

from prd_bench_local_runner.testing import get_success_data

from . import constants as c
from . import factories as f
from .api_client import VetEdApiClient
from .test_users import (
    BURSAR_HEADERS,
    SAA_HEADERS,
    VA_HEADERS,
    make_sco_headers,
    make_student_headers,
    make_supervisory_sco_headers,
)
from .types import Headers, JsonDict


# ─── Result containers ────────────────────────────────────────────────
@dataclass
class Officials:
    """A front-line and a supervisory certifying official, with their headers."""

    sco_id: str
    sup_id: str
    sco_headers: Headers
    sup_headers: Headers


@dataclass
class Baseline:
    """Officials plus an agency-approved program and an open term."""

    officials: Officials
    program_id: str
    catalog_id: str
    term_id: str

    @property
    def sco_id(self) -> str:
        return self.officials.sco_id

    @property
    def sup_id(self) -> str:
        return self.officials.sup_id

    @property
    def sco_headers(self) -> Headers:
        return self.officials.sco_headers

    @property
    def sup_headers(self) -> Headers:
        return self.officials.sup_headers


@dataclass
class CertificationScenario:
    """A baseline plus one student and one certification at some point in its life."""

    base: Baseline
    student_id: str
    student_headers: Headers
    certification_id: str
    certification_version: int
    tuition_report_id: Optional[str] = None
    agreement_id: Optional[str] = None
    agreement_version: Optional[int] = None
    award_id: Optional[str] = None
    change_report_id: Optional[str] = None
    debt_id: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def sco_id(self) -> str:
        return self.base.sco_id

    @property
    def sup_id(self) -> str:
        return self.base.sup_id

    @property
    def sco_headers(self) -> Headers:
        return self.base.sco_headers

    @property
    def sup_headers(self) -> Headers:
        return self.base.sup_headers

    @property
    def program_id(self) -> str:
        return self.base.program_id

    @property
    def catalog_id(self) -> str:
        return self.base.catalog_id

    @property
    def term_id(self) -> str:
        return self.base.term_id


# ─── Atomic builders ──────────────────────────────────────────────────
def set_clock_to(api: VetEdApiClient, date_iso: str) -> JsonDict:
    """Advance the logical clock to midnight UTC on the given calendar date."""
    return get_success_data(
        api.set_clock(f.clock_payload(f.clock_instant(date_iso)), VA_HEADERS)
    )


def create_officials(api: VetEdApiClient) -> Officials:
    """Credential one front-line and one supervisory certifying official."""
    sco = get_success_data(
        api.create_certifying_official(f.sco_official_payload(), VA_HEADERS)
    )
    sup = get_success_data(
        api.create_certifying_official(f.supervisory_official_payload(), VA_HEADERS)
    )
    return Officials(
        sco_id=sco["id"],
        sup_id=sup["id"],
        sco_headers=make_sco_headers(sco["id"]),
        sup_headers=make_supervisory_sco_headers(sup["id"]),
    )


def create_program(
    api: VetEdApiClient, sup_headers: Headers, **overrides: Any
) -> str:
    """Create a program of study; it opens at DRAFT with no catalog pinned."""
    program = get_success_data(
        api.create_program(f.program_payload(**overrides), sup_headers)
    )
    return program["id"]


def create_catalog_version(
    api: VetEdApiClient, sup_headers: Headers, program_id: str, **overrides: Any
) -> str:
    """Create a catalog version for a program; it opens at DRAFT."""
    catalog = get_success_data(
        api.create_catalog_version(
            f.catalog_version_payload(program_id, **overrides), sup_headers
        )
    )
    return catalog["id"]


def approve_catalog_version(
    api: VetEdApiClient,
    sup_headers: Headers,
    catalog_id: str,
    decision: str = c.SAA_DECISION_APPROVED,
    **decision_overrides: Any,
) -> JsonDict:
    """Send a catalog version to the agency and record the agency's decision."""
    get_success_data(api.submit_catalog_version_to_saa(catalog_id, {}, sup_headers))
    return get_success_data(
        api.record_saa_decision(
            catalog_id, f.saa_decision_payload(decision, **decision_overrides), SAA_HEADERS
        )
    )


def create_approved_program(
    api: VetEdApiClient,
    sup_headers: Headers,
    program_overrides: Optional[Dict[str, Any]] = None,
    catalog_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str]:
    """Create a program and drive one catalog version all the way to APPROVED."""
    program_id = create_program(api, sup_headers, **(program_overrides or {}))
    catalog_id = create_catalog_version(
        api, sup_headers, program_id, **(catalog_overrides or {})
    )
    approve_catalog_version(api, sup_headers, catalog_id)
    return program_id, catalog_id


def create_term(api: VetEdApiClient, sup_headers: Headers, **overrides: Any) -> str:
    """Create an academic term; it opens at OPEN."""
    term = get_success_data(
        api.create_academic_term(f.academic_term_payload(**overrides), sup_headers)
    )
    return term["id"]


def create_student(
    api: VetEdApiClient, sco_headers: Headers, **overrides: Any
) -> str:
    """Register a veteran student; the certificate of eligibility is NOT_SUBMITTED."""
    student = get_success_data(
        api.create_veteran_student(f.veteran_student_payload(**overrides), sco_headers)
    )
    return student["id"]


def create_verified_student(
    api: VetEdApiClient,
    sco_headers: Headers,
    verify_overrides: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> str:
    """Register a student and verify their certificate of eligibility."""
    student_id = create_student(api, sco_headers, **overrides)
    get_success_data(
        api.verify_coe(
            student_id, f.verify_coe_payload(**(verify_overrides or {})), sco_headers
        )
    )
    return student_id


def create_certification(
    api: VetEdApiClient,
    sco_headers: Headers,
    student_id: str,
    term_id: str,
    program_id: str,
    **overrides: Any,
) -> Tuple[str, int]:
    """Draft an enrollment certification; returns its id and its current version."""
    cert = get_success_data(
        api.create_enrollment_certification(
            f.certification_payload(student_id, term_id, program_id, **overrides),
            sco_headers,
        )
    )
    return cert["id"], cert["version"]


def price_certification(
    api: VetEdApiClient,
    certification_id: str,
    expected_certification_version: int,
    **overrides: Any,
) -> Tuple[str, int]:
    """File a tuition and fee report; returns the report id and the new certification version."""
    report = get_success_data(
        api.create_tuition_fee_report(
            f.tuition_fee_report_payload(
                certification_id, expected_certification_version, **overrides
            ),
            BURSAR_HEADERS,
        )
    )
    return report["id"], expected_certification_version + 1


def submit_certification(
    api: VetEdApiClient, sco_headers: Headers, certification_id: str
) -> JsonDict:
    """Submit a certification for supervisory certification."""
    return get_success_data(api.submit_certification(certification_id, {}, sco_headers))


def certify_certification(
    api: VetEdApiClient, sup_headers: Headers, certification_id: str
) -> JsonDict:
    """Certify enrollment to VA as the supervisory official."""
    return get_success_data(api.certify_certification(certification_id, {}, sup_headers))


def record_va_payment(
    api: VetEdApiClient,
    certification_id: str,
    tuition_amount_cents: int,
    mha_amount_cents: int,
    posted_on: str,
) -> JsonDict:
    """Record what VA actually disbursed against a certified certification."""
    return get_success_data(
        api.record_va_payment(
            certification_id,
            f.record_va_payment_payload(
                tuition_amount_cents, mha_amount_cents, posted_on
            ),
            VA_HEADERS,
        )
    )


def create_agreement(
    api: VetEdApiClient, sup_headers: Headers, **overrides: Any
) -> Tuple[str, int]:
    """Create a Yellow Ribbon agreement; returns its id and its current version."""
    agreement = get_success_data(
        api.create_yellow_ribbon_agreement(
            f.yellow_ribbon_agreement_payload(**overrides), sup_headers
        )
    )
    return agreement["id"], agreement["version"]


def create_award(
    api: VetEdApiClient,
    sup_headers: Headers,
    certification_id: str,
    agreement_id: str,
    expected_agreement_version: int,
) -> JsonDict:
    """Match a certification's Yellow Ribbon gap against an agreement."""
    return get_success_data(
        api.create_yellow_ribbon_award(
            f.yellow_ribbon_award_payload(
                certification_id, agreement_id, expected_agreement_version
            ),
            sup_headers,
        )
    )


def read_certification(
    api: VetEdApiClient, headers: Headers, certification_id: str
) -> JsonDict:
    return get_success_data(api.get_enrollment_certification(certification_id, headers))


def read_student(api: VetEdApiClient, headers: Headers, student_id: str) -> JsonDict:
    return get_success_data(api.get_veteran_student(student_id, headers))


def read_agreement(api: VetEdApiClient, headers: Headers, agreement_id: str) -> JsonDict:
    return get_success_data(api.get_yellow_ribbon_agreement(agreement_id, headers))


def read_audit_entries(
    api: VetEdApiClient,
    headers: Headers,
    certification_id: str,
    params: Optional[JsonDict] = None,
) -> List[JsonDict]:
    response = api.list_audit_entries(certification_id, headers, params)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def read_agreement_version(
    api: VetEdApiClient, headers: Headers, agreement_id: str
) -> int:
    return read_agreement(api, headers, agreement_id)["version"]


# ─── Composite builders ───────────────────────────────────────────────
def build_baseline(api: VetEdApiClient) -> Baseline:
    """Officials, an agency-approved program with its catalog, and an open term."""
    officials = create_officials(api)
    program_id, catalog_id = create_approved_program(api, officials.sup_headers)
    term_id = create_term(api, officials.sup_headers)
    return Baseline(
        officials=officials,
        program_id=program_id,
        catalog_id=catalog_id,
        term_id=term_id,
    )


def build_draft_certification(
    api: VetEdApiClient,
    base: Baseline,
    student_overrides: Optional[Dict[str, Any]] = None,
    certification_overrides: Optional[Dict[str, Any]] = None,
) -> CertificationScenario:
    """A verified student with one DRAFT certification against the approved program."""
    student_id = create_verified_student(
        api, base.sco_headers, **(student_overrides or {})
    )
    certification_id, version = create_certification(
        api,
        base.sco_headers,
        student_id,
        base.term_id,
        base.program_id,
        **(certification_overrides or {}),
    )
    return CertificationScenario(
        base=base,
        student_id=student_id,
        student_headers=make_student_headers(student_id),
        certification_id=certification_id,
        certification_version=version,
    )


def build_priced_certification(
    api: VetEdApiClient,
    base: Baseline,
    student_overrides: Optional[Dict[str, Any]] = None,
    certification_overrides: Optional[Dict[str, Any]] = None,
    pricing_overrides: Optional[Dict[str, Any]] = None,
) -> CertificationScenario:
    """A DRAFT certification with a REPORTED tuition and fee report in force."""
    scenario = build_draft_certification(
        api, base, student_overrides, certification_overrides
    )
    report_id, new_version = price_certification(
        api,
        scenario.certification_id,
        scenario.certification_version,
        **(pricing_overrides or {}),
    )
    scenario.tuition_report_id = report_id
    scenario.certification_version = new_version
    return scenario


def build_submitted_certification(
    api: VetEdApiClient,
    base: Baseline,
    student_overrides: Optional[Dict[str, Any]] = None,
    certification_overrides: Optional[Dict[str, Any]] = None,
    pricing_overrides: Optional[Dict[str, Any]] = None,
) -> CertificationScenario:
    """A priced certification submitted by the front-line official."""
    scenario = build_priced_certification(
        api, base, student_overrides, certification_overrides, pricing_overrides
    )
    submitted = submit_certification(api, base.sco_headers, scenario.certification_id)
    scenario.certification_version = submitted["version"]
    return scenario


def build_certified_certification(
    api: VetEdApiClient,
    base: Baseline,
    student_overrides: Optional[Dict[str, Any]] = None,
    certification_overrides: Optional[Dict[str, Any]] = None,
    pricing_overrides: Optional[Dict[str, Any]] = None,
) -> CertificationScenario:
    """A submitted certification certified to VA by the supervisory official."""
    scenario = build_submitted_certification(
        api, base, student_overrides, certification_overrides, pricing_overrides
    )
    certified = certify_certification(
        api, base.sup_headers, scenario.certification_id
    )
    scenario.certification_version = certified["version"]
    scenario.extra["certified"] = certified
    return scenario


def build_paid_certification(
    api: VetEdApiClient,
    base: Baseline,
    tuition_amount_cents: int,
    mha_amount_cents: int,
    posted_on: str = c.CLOCK_START_DATE,
    student_overrides: Optional[Dict[str, Any]] = None,
    certification_overrides: Optional[Dict[str, Any]] = None,
    pricing_overrides: Optional[Dict[str, Any]] = None,
) -> CertificationScenario:
    """A certified certification against which VA's disbursement has been recorded."""
    scenario = build_certified_certification(
        api, base, student_overrides, certification_overrides, pricing_overrides
    )
    paid = record_va_payment(
        api,
        scenario.certification_id,
        tuition_amount_cents,
        mha_amount_cents,
        posted_on,
    )
    scenario.certification_version = paid["version"]
    scenario.extra["paid"] = paid
    return scenario


# ─── Pytest fixtures ──────────────────────────────────────────────────
@pytest.fixture
def officials(api: VetEdApiClient) -> Officials:
    """One front-line and one supervisory certifying official."""
    return create_officials(api)


@pytest.fixture
def baseline(api: VetEdApiClient) -> Baseline:
    """Officials, an agency-approved program and an open fall term."""
    return build_baseline(api)


@pytest.fixture
def draft_certification(
    api: VetEdApiClient, baseline: Baseline
) -> CertificationScenario:
    """A verified student with one DRAFT full-time certification."""
    return build_draft_certification(api, baseline)


@pytest.fixture
def priced_certification(
    api: VetEdApiClient, baseline: Baseline
) -> CertificationScenario:
    """A DRAFT certification with a REPORTED tuition and fee report in force."""
    return build_priced_certification(api, baseline)


@pytest.fixture
def submitted_certification(
    api: VetEdApiClient, baseline: Baseline
) -> CertificationScenario:
    """A priced certification awaiting supervisory certification."""
    return build_submitted_certification(api, baseline)


@pytest.fixture
def certified_certification(
    api: VetEdApiClient, baseline: Baseline
) -> CertificationScenario:
    """A certification already certified to VA on the canonical figures."""
    return build_certified_certification(api, baseline)
