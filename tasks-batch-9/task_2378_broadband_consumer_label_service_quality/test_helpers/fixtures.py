"""Composite setup chains.

Every helper here performs setup only: it uses the lenient
:func:`get_success_data` so a broken prerequisite fails loudly as a setup error
rather than masquerading as an assertion about the behaviour under test. Tests
make their own assertions on their own calls.

The chains are layered smallest-first: single-resource creators, then the
multi-step compositions (a published methodology, a certified attestation, a
published label, an investigated complaint), then
:func:`build_reference_environment`, the whole reference world used by most
scenarios.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    REFERENCE_NOW,
    REFERENCE_SAMPLES,
    REFERENCE_WINDOW_END,
    REFERENCE_WINDOW_START,
)
from .factories import (
    build_attestation_payload,
    build_close_inquiry_payload,
    build_complaint_payload,
    build_disclosure_payload,
    build_dismiss_payload,
    build_filing_payload,
    build_invalidate_run_payload,
    build_label_version_payload,
    build_measurement_probe_payload,
    build_methodology_document_payload,
    build_plan_change_notice_payload,
    build_reference_fee_payloads,
    build_regulator_inquiry_payload,
    build_service_plan_payload,
    build_subscriber_account_payload,
    build_test_run_payload,
    build_translation_payload,
    build_triage_payload,
    build_uphold_payload,
    build_void_credit_payload,
)
from .test_users import (
    COMPLAINT_ANALYST_HEADERS,
    COMPLIANCE_OFFICER_2_HEADERS,
    COMPLIANCE_OFFICER_HEADERS,
    LOCALIZATION_SPECIALIST_2_HEADERS,
    LOCALIZATION_SPECIALIST_HEADERS,
    NETWORK_ENGINEER_HEADERS,
    REGULATORY_LIAISON_HEADERS,
    RETAIL_AGENT_HEADERS,
    make_subscriber_headers,
)
from .types import (
    CreditBasis,
    FilingType,
    MetricVariant,
)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


def set_clock(to_iso8601: str) -> str:
    """Reposition the logical clock; returns the new `current_utc`."""
    data = get_success_data(api_client.set_clock(to_iso8601, COMPLIANCE_OFFICER_HEADERS))
    return data["current_utc"]


# ---------------------------------------------------------------------------
# Service plans and fee lines
# ---------------------------------------------------------------------------


def create_service_plan(**overrides: Any) -> Dict[str, Any]:
    payload = build_service_plan_payload(**overrides)
    return get_success_data(
        api_client.create_service_plan(payload, COMPLIANCE_OFFICER_HEADERS)
    )


def read_service_plan(plan_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_service_plan(plan_id, COMPLIANCE_OFFICER_HEADERS)
    )


def current_plan_version(plan_id: str) -> int:
    """The plan's current `version`, for the optimistic-concurrency field."""
    return read_service_plan(plan_id)["version"]


def add_fee_line(plan_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(
        api_client.add_fee_line_item(plan_id, payload, COMPLIANCE_OFFICER_HEADERS)
    )


def add_reference_fee_lines(plan_id: str) -> List[Dict[str, Any]]:
    """The five reference fee lines, added in the order the itemisation walks."""
    return [add_fee_line(plan_id, payload) for payload in build_reference_fee_payloads()]


def create_reference_plan(**overrides: Any) -> Dict[str, Any]:
    """The reference plan together with its five fee lines."""
    plan = create_service_plan(**overrides)
    add_reference_fee_lines(plan["id"])
    return read_service_plan(plan["id"])


# ---------------------------------------------------------------------------
# Measurement infrastructure
# ---------------------------------------------------------------------------


def create_methodology_document(**overrides: Any) -> Dict[str, Any]:
    payload = build_methodology_document_payload(**overrides)
    return get_success_data(
        api_client.create_methodology_document(payload, NETWORK_ENGINEER_HEADERS)
    )


def create_published_methodology(**overrides: Any) -> Dict[str, Any]:
    """A methodology document authored by an engineer and published by an
    officer, which is the only form a run or attestation may cite."""
    doc = create_methodology_document(**overrides)
    return get_success_data(
        api_client.publish_methodology_document(doc["id"], COMPLIANCE_OFFICER_HEADERS)
    )


def create_measurement_probe(**overrides: Any) -> Dict[str, Any]:
    payload = build_measurement_probe_payload(**overrides)
    return get_success_data(
        api_client.create_measurement_probe(payload, NETWORK_ENGINEER_HEADERS)
    )


def record_test_run(
    probe_id: str,
    plan_id: str,
    methodology_doc_id: str,
    window_start: str = REFERENCE_WINDOW_START,
    window_end: str = REFERENCE_WINDOW_END,
    samples: Optional[Sequence[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = build_test_run_payload(
        probe_id,
        plan_id,
        methodology_doc_id,
        window_start=window_start,
        window_end=window_end,
        samples=list(samples) if samples is not None else list(REFERENCE_SAMPLES),
        **overrides,
    )
    return get_success_data(
        api_client.create_test_run(payload, NETWORK_ENGINEER_HEADERS)
    )


def invalidate_test_run(run_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = build_invalidate_run_payload(**overrides)
    return get_success_data(
        api_client.invalidate_test_run(run_id, payload, NETWORK_ENGINEER_HEADERS)
    )


def create_attestation(
    plan_id: str,
    methodology_doc_id: str,
    metric_variant: str = MetricVariant.PEAK_HOUR_MEDIAN.value,
    expected_plan_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    version = (
        expected_plan_version
        if expected_plan_version is not None
        else current_plan_version(plan_id)
    )
    payload = build_attestation_payload(
        plan_id, methodology_doc_id, version, metric_variant=metric_variant, **overrides
    )
    return get_success_data(
        api_client.create_performance_attestation(payload, NETWORK_ENGINEER_HEADERS)
    )


def certify_attestation(attestation_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.certify_performance_attestation(
            attestation_id, COMPLIANCE_OFFICER_HEADERS
        )
    )


def create_certified_attestation(
    plan_id: str,
    methodology_doc_id: str,
    metric_variant: str = MetricVariant.PEAK_HOUR_MEDIAN.value,
    **overrides: Any,
) -> Dict[str, Any]:
    attestation = create_attestation(
        plan_id, methodology_doc_id, metric_variant=metric_variant, **overrides
    )
    return certify_attestation(attestation["id"])


def create_measured_plan(
    plan_overrides: Optional[Dict[str, Any]] = None,
    methodology_overrides: Optional[Dict[str, Any]] = None,
    probe_overrides: Optional[Dict[str, Any]] = None,
    samples: Optional[Sequence[Dict[str, Any]]] = None,
    metric_variant: str = MetricVariant.PEAK_HOUR_MEDIAN.value,
    certify: bool = True,
) -> Dict[str, Any]:
    """A plan with fee lines, a published methodology, a probe, one recorded run
    and an attestation over that run.

    Returns a dict with keys `plan`, `methodology`, `probe`, `run` and
    `attestation`.
    """
    plan = create_reference_plan(**(plan_overrides or {}))
    methodology = create_published_methodology(**(methodology_overrides or {}))
    probe = create_measurement_probe(**(probe_overrides or {}))
    run = record_test_run(
        probe["id"], plan["id"], methodology["id"], samples=samples
    )
    if certify:
        attestation = create_certified_attestation(
            plan["id"], methodology["id"], metric_variant=metric_variant
        )
    else:
        attestation = create_attestation(
            plan["id"], methodology["id"], metric_variant=metric_variant
        )
    return {
        "plan": read_service_plan(plan["id"]),
        "methodology": methodology,
        "probe": probe,
        "run": run,
        "attestation": attestation,
    }


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------


def draft_label(
    plan_id: str,
    effective_from: str = REFERENCE_NOW,
    expected_plan_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    version = (
        expected_plan_version
        if expected_plan_version is not None
        else current_plan_version(plan_id)
    )
    payload = build_label_version_payload(
        plan_id, effective_from, version, **overrides
    )
    return get_success_data(
        api_client.create_label_version(payload, COMPLIANCE_OFFICER_HEADERS)
    )


def read_label(label_version_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_label_version(label_version_id, COMPLIANCE_OFFICER_HEADERS)
    )


def add_translation(
    label_version_id: str, locale: str = "en-US", **overrides: Any
) -> Dict[str, Any]:
    payload = build_translation_payload(locale=locale, **overrides)
    return get_success_data(
        api_client.create_label_translation(
            label_version_id, payload, LOCALIZATION_SPECIALIST_HEADERS
        )
    )


def add_verified_translation(
    label_version_id: str, locale: str = "en-US", **overrides: Any
) -> Dict[str, Any]:
    """A translation authored by one specialist and verified by another, as the
    maker-checker control on verification requires."""
    translation = add_translation(label_version_id, locale=locale, **overrides)
    return get_success_data(
        api_client.verify_label_translation(
            label_version_id, translation["id"], LOCALIZATION_SPECIALIST_2_HEADERS
        )
    )


def publish_label(label_version_id: str) -> Dict[str, Any]:
    """Published by a second officer, since a label may not be published by the
    officer who drafted it."""
    return get_success_data(
        api_client.publish_label_version(
            label_version_id, COMPLIANCE_OFFICER_2_HEADERS
        )
    )


def create_published_label(
    plan_id: str,
    effective_from: str = REFERENCE_NOW,
    locales: Sequence[str] = ("en-US",),
    expected_plan_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Draft a label, verify a translation for every required locale, publish."""
    label = draft_label(
        plan_id,
        effective_from=effective_from,
        expected_plan_version=expected_plan_version,
        **overrides,
    )
    for locale in locales:
        add_verified_translation(label["id"], locale=locale)
    return publish_label(label["id"])


# ---------------------------------------------------------------------------
# Retail surface
# ---------------------------------------------------------------------------


def create_subscriber_account(
    plan_id: str, service_start_date: str = REFERENCE_NOW, **overrides: Any
) -> Dict[str, Any]:
    payload = build_subscriber_account_payload(
        plan_id, service_start_date, **overrides
    )
    return get_success_data(
        api_client.create_subscriber_account(payload, RETAIL_AGENT_HEADERS)
    )


def read_subscriber_account(account_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_subscriber_account(account_id, COMPLIANCE_OFFICER_HEADERS)
    )


def record_disclosure(
    account_id: str, headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    payload = build_disclosure_payload(**overrides)
    return get_success_data(
        api_client.record_label_disclosure(
            account_id, payload, headers or RETAIL_AGENT_HEADERS
        )
    )


def create_plan_change_notice(
    account_id: str, target_plan_id: str, effective_date: str, **overrides: Any
) -> Dict[str, Any]:
    payload = build_plan_change_notice_payload(
        account_id, target_plan_id, effective_date, **overrides
    )
    return get_success_data(
        api_client.create_plan_change_notice(payload, RETAIL_AGENT_HEADERS)
    )


def acknowledge_notice(notice_id: str, account_id: str) -> Dict[str, Any]:
    """Only the subscriber who owns the account may acknowledge."""
    return get_success_data(
        api_client.acknowledge_plan_change_notice(
            notice_id, make_subscriber_headers(account_id)
        )
    )


# ---------------------------------------------------------------------------
# Complaints, credits and dockets
# ---------------------------------------------------------------------------


def file_complaint(
    account_id: str,
    disputed_label_version_id: str,
    service_observed_date: str = REFERENCE_NOW,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = build_complaint_payload(
        account_id, disputed_label_version_id, service_observed_date, **overrides
    )
    return get_success_data(
        api_client.create_complaint(payload, headers or COMPLAINT_ANALYST_HEADERS)
    )


def read_complaint(complaint_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_complaint(complaint_id, COMPLAINT_ANALYST_HEADERS)
    )


def triage_complaint(complaint_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = build_triage_payload(**overrides)
    return get_success_data(
        api_client.triage_complaint(complaint_id, payload, COMPLAINT_ANALYST_HEADERS)
    )


def investigate_complaint(complaint_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.investigate_complaint(complaint_id, COMPLAINT_ANALYST_HEADERS)
    )


def create_investigated_complaint(
    account_id: str,
    disputed_label_version_id: str,
    service_observed_date: str = REFERENCE_NOW,
    **overrides: Any,
) -> Dict[str, Any]:
    """A complaint walked `INTAKE → TRIAGED → UNDER_INVESTIGATION`, which is the
    only state a resolution may be taken from."""
    complaint = file_complaint(
        account_id,
        disputed_label_version_id,
        service_observed_date=service_observed_date,
        **overrides,
    )
    triage_complaint(complaint["id"])
    return investigate_complaint(complaint["id"])


def uphold_complaint(
    complaint_id: str,
    credit_basis: str = CreditBasis.PRORATA_DAYS.value,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = build_uphold_payload(credit_basis=credit_basis, **overrides)
    return get_success_data(
        api_client.resolve_complaint(complaint_id, payload, COMPLAINT_ANALYST_HEADERS)
    )


def dismiss_complaint(complaint_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = build_dismiss_payload(**overrides)
    return get_success_data(
        api_client.resolve_complaint(complaint_id, payload, COMPLAINT_ANALYST_HEADERS)
    )


def create_upheld_complaint(
    account_id: str,
    disputed_label_version_id: str,
    service_observed_date: str = REFERENCE_NOW,
    credit_basis: str = CreditBasis.PRORATA_DAYS.value,
    **overrides: Any,
) -> Dict[str, Any]:
    """A complaint carried all the way to `UPHELD`, which issues a credit."""
    complaint = create_investigated_complaint(
        account_id,
        disputed_label_version_id,
        service_observed_date=service_observed_date,
        **overrides,
    )
    return uphold_complaint(complaint["id"], credit_basis=credit_basis)


def create_dismissed_complaint(
    account_id: str,
    disputed_label_version_id: str,
    service_observed_date: str = REFERENCE_NOW,
    **overrides: Any,
) -> Dict[str, Any]:
    complaint = create_investigated_complaint(
        account_id,
        disputed_label_version_id,
        service_observed_date=service_observed_date,
        **overrides,
    )
    return dismiss_complaint(complaint["id"])


def credits_of_complaint(complaint_id: str, **params: Any) -> List[Dict[str, Any]]:
    return get_success_data(
        api_client.list_complaint_remediation_credits(
            complaint_id, COMPLAINT_ANALYST_HEADERS, params=params or None
        )
    )


def first_credit_of(complaint_id: str) -> Dict[str, Any]:
    """The single credit issued by upholding a complaint."""
    rows = credits_of_complaint(complaint_id)
    assert rows, f"complaint {complaint_id} has no remediation credit"
    return rows[0]


def read_credit(credit_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_remediation_credit(credit_id, COMPLIANCE_OFFICER_HEADERS)
    )


def read_regulator_inquiry(inquiry_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_regulator_inquiry(inquiry_id, REGULATORY_LIAISON_HEADERS)
    )


def read_test_run(run_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_test_run(run_id, NETWORK_ENGINEER_HEADERS)
    )


def read_attestation(attestation_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_performance_attestation(attestation_id, NETWORK_ENGINEER_HEADERS)
    )


def read_plan_change_notice(notice_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_plan_change_notice(notice_id, RETAIL_AGENT_HEADERS)
    )


def void_credit(credit_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = build_void_credit_payload(**overrides)
    return get_success_data(
        api_client.void_remediation_credit(
            credit_id, payload, COMPLIANCE_OFFICER_HEADERS
        )
    )


def create_regulator_inquiry(complaint_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = build_regulator_inquiry_payload(complaint_id, **overrides)
    return get_success_data(
        api_client.create_regulator_inquiry(payload, REGULATORY_LIAISON_HEADERS)
    )


def file_inquiry_filing(
    inquiry_id: str,
    filing_type: str = FilingType.TECHNICAL_PACKET.value,
    evidence_ref: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = build_filing_payload(
        filing_type=filing_type, evidence_ref=evidence_ref, **overrides
    )
    return get_success_data(
        api_client.file_inquiry_filing(inquiry_id, payload, REGULATORY_LIAISON_HEADERS)
    )


def close_regulator_inquiry(inquiry_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = build_close_inquiry_payload(**overrides)
    return get_success_data(
        api_client.close_regulator_inquiry(
            inquiry_id, payload, REGULATORY_LIAISON_HEADERS
        )
    )


# ---------------------------------------------------------------------------
# The reference world
# ---------------------------------------------------------------------------


@dataclass
class ReferenceEnvironment:
    """The reference world: one fully substantiated, published label on a fibre
    plan with five fee lines, one enrolled account, and the ids needed to reach
    every downstream flow.
    """

    plan: Dict[str, Any]
    methodology: Dict[str, Any]
    probe: Dict[str, Any]
    run: Dict[str, Any]
    attestation: Dict[str, Any]
    label: Dict[str, Any]
    account: Dict[str, Any]
    fee_lines: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def plan_id(self) -> str:
        return self.plan["id"]

    @property
    def methodology_id(self) -> str:
        return self.methodology["id"]

    @property
    def probe_id(self) -> str:
        return self.probe["id"]

    @property
    def run_id(self) -> str:
        return self.run["id"]

    @property
    def attestation_id(self) -> str:
        return self.attestation["id"]

    @property
    def label_id(self) -> str:
        return self.label["id"]

    @property
    def account_id(self) -> str:
        return self.account["id"]

    @property
    def subscriber_headers(self) -> Dict[str, str]:
        """Headers for the account holder: `X-User-ID` is the account's own
        `id`."""
        return make_subscriber_headers(self.account_id)

    def reload_plan(self) -> Dict[str, Any]:
        self.plan = read_service_plan(self.plan_id)
        return self.plan

    def reload_label(self) -> Dict[str, Any]:
        self.label = read_label(self.label_id)
        return self.label

    def reload_account(self) -> Dict[str, Any]:
        self.account = read_subscriber_account(self.account_id)
        return self.account

    def reload_attestation(self) -> Dict[str, Any]:
        self.attestation = get_success_data(
            api_client.get_performance_attestation(
                self.attestation_id, NETWORK_ENGINEER_HEADERS
            )
        )
        return self.attestation

    def reload_run(self) -> Dict[str, Any]:
        self.run = get_success_data(
            api_client.get_test_run(self.run_id, NETWORK_ENGINEER_HEADERS)
        )
        return self.run


def build_reference_environment(
    clock: str = REFERENCE_NOW,
    plan_overrides: Optional[Dict[str, Any]] = None,
    metric_variant: str = MetricVariant.PEAK_HOUR_MEDIAN.value,
    samples: Optional[Sequence[Dict[str, Any]]] = None,
    account_overrides: Optional[Dict[str, Any]] = None,
) -> ReferenceEnvironment:
    """Position the clock, then build the whole reference world in one call."""
    set_clock(clock)

    plan = create_service_plan(**(plan_overrides or {}))
    fee_lines = add_reference_fee_lines(plan["id"])

    methodology = create_published_methodology()
    probe = create_measurement_probe()
    run = record_test_run(
        probe["id"], plan["id"], methodology["id"], samples=samples
    )

    attestation = create_certified_attestation(
        plan["id"], methodology["id"], metric_variant=metric_variant
    )
    label = create_published_label(plan["id"], effective_from=clock)

    account = create_subscriber_account(
        plan["id"], service_start_date=clock, **(account_overrides or {})
    )

    return ReferenceEnvironment(
        plan=read_service_plan(plan["id"]),
        methodology=methodology,
        probe=probe,
        run=run,
        attestation=attestation,
        label=read_label(label["id"]),
        account=account,
        fee_lines=fee_lines,
    )
