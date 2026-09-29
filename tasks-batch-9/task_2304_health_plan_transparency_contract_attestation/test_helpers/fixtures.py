"""Composite setup helpers.

Each test starts against an empty database, so every precondition has to be
built from scratch through the published endpoints. These helpers do that and
return the resources they created, so a test body can go straight to the
behaviour it is about. All of them accept ``**overrides`` that are forwarded to
the underlying payload factory.

Helpers use ``get_success_data`` rather than a strict validator, because setup
failures should surface as a missing key in the test body rather than as a
confusing assertion inside a fixture.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .test_users import (
    COMPLIANCE_OFFICER_HEADERS,
    EXTERNAL_AUDITOR_HEADERS,
    OFFICER_PREPARER_HEADERS,
    OFFICER_SIGNER_HEADERS,
    PLATFORM_OPERATOR_HEADERS,
    SPONSOR_ADMIN_HEADERS,
    make_vendor_contact_headers,
)
from .types import (
    AMENDMENT_TYPE_DATA_RIGHTS,
    FILE_TYPE_ALLOWED_AMOUNTS,
    FILE_TYPE_IN_NETWORK_RATES,
    SECTION_D2_SPENDING,
    SECTION_D6_RX_TOTALS,
    VENDOR_TYPE_BROKER,
    VENDOR_TYPE_CONSULTANT,
    VENDOR_TYPE_NETWORK_VENDOR,
    VENDOR_TYPE_PBM,
    VENDOR_TYPE_TPA,
)

JsonDict = dict[str, Any]
Headers = Mapping[str, str]


# ---------------------------------------------------------------------------
# Tier 0: primitives and reads
# ---------------------------------------------------------------------------


def set_clock(api: ApiClient, current_utc: str) -> JsonDict:
    """Move the logical clock to ``current_utc``."""
    response = api.set_clock(
        f.clock_payload(current_utc), PLATFORM_OPERATOR_HEADERS
    )
    return get_success_data(response)


def read_plan_year(api: ApiClient, plan_year_id: str) -> JsonDict:
    """Read one plan year through the sponsor's view."""
    return get_success_data(api.get_plan_year(plan_year_id, SPONSOR_ADMIN_HEADERS))


def read_contract(api: ApiClient, contract_id: str) -> JsonDict:
    """Read one contract through the sponsor's view."""
    return get_success_data(api.get_contract(contract_id, SPONSOR_ADMIN_HEADERS))


def current_plan_year_version(api: ApiClient, plan_year_id: str) -> int:
    """Read the plan year immediately before issuing a version-guarded create."""
    return read_plan_year(api, plan_year_id)["version"]


def current_contract_version(api: ApiClient, contract_id: str) -> int:
    """Read the contract immediately before issuing a version-guarded create."""
    return read_contract(api, contract_id)["version"]


def list_ledger_entries(
    api: ApiClient, plan_year_id: str, **filters: Any
) -> list[JsonDict]:
    """Every ledger entry of a plan year, in chronological order."""
    params: JsonDict = {"plan_year_id": plan_year_id, "limit": 100}
    params.update(filters)
    body = get_success_data(
        api.list_ledger_entries(COMPLIANCE_OFFICER_HEADERS, params=params)
    )
    return body if isinstance(body, list) else body["data"]


def ledger_entries_of(
    api: ApiClient, plan_year_id: str, **filters: Any
) -> list[JsonDict]:
    """Alias kept for readability at call sites that only want the rows."""
    return list_ledger_entries(api, plan_year_id, **filters)


def first_accrual_id(
    api: ApiClient, plan_year_id: str, deficiency_type: str | None = None
) -> str:
    """The identifier of the earliest ``ACCRUAL`` entry of a plan year."""
    filters: JsonDict = {"entry_type": "ACCRUAL"}
    if deficiency_type is not None:
        filters["deficiency_type"] = deficiency_type
    entries = list_ledger_entries(api, plan_year_id, **filters)
    return entries[0]["id"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource state progression
# ---------------------------------------------------------------------------


def create_plan_year(api: ApiClient, **overrides: Any) -> JsonDict:
    """A plan year in ``SETUP`` with posture ``COMPLIANT``."""
    return get_success_data(
        api.create_plan_year(f.plan_year_payload(**overrides), SPONSOR_ADMIN_HEADERS)
    )


def create_vendor(api: ApiClient, **overrides: Any) -> JsonDict:
    """A registered service provider."""
    return get_success_data(
        api.create_vendor(f.vendor_payload(**overrides), SPONSOR_ADMIN_HEADERS)
    )


def create_tpa_vendor(api: ApiClient, **overrides: Any) -> JsonDict:
    """The third-party administrator every plan year needs on its roster."""
    return create_vendor(
        api,
        legal_name=f.TPA_LEGAL_NAME,
        vendor_type=VENDOR_TYPE_TPA,
        contact_email=f.TPA_CONTACT_EMAIL,
        **overrides,
    )


def create_pbm_vendor(api: ApiClient, **overrides: Any) -> JsonDict:
    """A pharmacy benefit manager."""
    return create_vendor(
        api,
        legal_name=f.PBM_LEGAL_NAME,
        vendor_type=VENDOR_TYPE_PBM,
        contact_email=f.PBM_CONTACT_EMAIL,
        **overrides,
    )


def create_broker_vendor(api: ApiClient, **overrides: Any) -> JsonDict:
    """A broker, whose contracts must carry a compensation disclosure."""
    return create_vendor(
        api,
        legal_name=f.BROKER_LEGAL_NAME,
        vendor_type=VENDOR_TYPE_BROKER,
        contact_email=f.BROKER_CONTACT_EMAIL,
        **overrides,
    )


def create_consultant_vendor(api: ApiClient, **overrides: Any) -> JsonDict:
    """A consultant, whose disclosures are judged on direct compensation alone."""
    return create_vendor(
        api,
        legal_name=f.CONSULTANT_LEGAL_NAME,
        vendor_type=VENDOR_TYPE_CONSULTANT,
        contact_email=f.CONSULTANT_CONTACT_EMAIL,
        **overrides,
    )


def create_network_vendor(api: ApiClient, **overrides: Any) -> JsonDict:
    """A network vendor, which is not material to the attestation."""
    return create_vendor(
        api,
        legal_name=f.NETWORK_VENDOR_LEGAL_NAME,
        vendor_type=VENDOR_TYPE_NETWORK_VENDOR,
        contact_email=f.NETWORK_VENDOR_CONTACT_EMAIL,
        **overrides,
    )


def create_contract(
    api: ApiClient, plan_year_id: str, vendor_id: str, **overrides: Any
) -> JsonDict:
    """A service provider contract at ``NOT_REVIEWED`` / ``NOT_SECURED``."""
    return get_success_data(
        api.create_contract(
            f.contract_payload(plan_year_id, vendor_id, **overrides),
            SPONSOR_ADMIN_HEADERS,
        )
    )


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy
# ---------------------------------------------------------------------------


def plan_year_with_tpa_contract(api: ApiClient, **overrides: Any) -> JsonDict:
    """A plan year in ``SETUP`` that already has a TPA on its roster.

    Returns ``{"plan_year", "tpa_vendor", "tpa_contract"}``.
    """
    plan_year = create_plan_year(api, **overrides)
    vendor = create_tpa_vendor(api)
    contract = create_contract(
        api, plan_year["id"], vendor["id"], contract_type=VENDOR_TYPE_TPA
    )
    return {
        "plan_year": plan_year,
        "tpa_vendor": vendor,
        "tpa_contract": contract,
    }


def activated_plan_year(api: ApiClient, **overrides: Any) -> JsonDict:
    """A plan year advanced to ``ACTIVE`` with its TPA contract in place.

    Returns ``{"plan_year", "tpa_vendor", "tpa_contract"}`` where ``plan_year``
    is the post-activation representation.
    """
    setup = plan_year_with_tpa_contract(api, **overrides)
    activated = get_success_data(
        api.activate_plan_year(setup["plan_year"]["id"], SPONSOR_ADMIN_HEADERS)
    )
    setup["plan_year"] = activated
    return setup


def add_contract_for_vendor_type(
    api: ApiClient,
    plan_year_id: str,
    vendor_type: str,
    **overrides: Any,
) -> JsonDict:
    """Register a vendor of ``vendor_type`` and contract it to the plan year.

    Returns ``{"vendor", "contract"}``.
    """
    creators = {
        VENDOR_TYPE_TPA: create_tpa_vendor,
        VENDOR_TYPE_PBM: create_pbm_vendor,
        VENDOR_TYPE_BROKER: create_broker_vendor,
        VENDOR_TYPE_CONSULTANT: create_consultant_vendor,
        VENDOR_TYPE_NETWORK_VENDOR: create_network_vendor,
    }
    vendor = creators[vendor_type](api)
    contract = create_contract(
        api,
        plan_year_id,
        vendor["id"],
        contract_type=vendor_type,
        **overrides,
    )
    return {"vendor": vendor, "contract": contract}


def activated_plan_year_with_roster(api: ApiClient, **overrides: Any) -> JsonDict:
    """An ``ACTIVE`` plan year carrying TPA, PBM, broker and consultant contracts.

    Returns ``{"plan_year", "tpa_vendor", "tpa_contract", "pbm_vendor",
    "pbm_contract", "broker_vendor", "broker_contract", "consultant_vendor",
    "consultant_contract"}``.
    """
    setup = activated_plan_year(api, **overrides)
    plan_year_id = setup["plan_year"]["id"]

    pbm = add_contract_for_vendor_type(
        api,
        plan_year_id,
        VENDOR_TYPE_PBM,
        annual_fee_cents=12_000_000,
    )
    broker = add_contract_for_vendor_type(
        api,
        plan_year_id,
        VENDOR_TYPE_BROKER,
        annual_fee_cents=2_400_000,
    )
    consultant = add_contract_for_vendor_type(
        api,
        plan_year_id,
        VENDOR_TYPE_CONSULTANT,
        annual_fee_cents=1_800_000,
    )

    setup.update(
        {
            "pbm_vendor": pbm["vendor"],
            "pbm_contract": pbm["contract"],
            "broker_vendor": broker["vendor"],
            "broker_contract": broker["contract"],
            "consultant_vendor": consultant["vendor"],
            "consultant_contract": consultant["contract"],
        }
    )
    return setup


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts — gag review
# ---------------------------------------------------------------------------


def open_gag_review(
    api: ApiClient, contract_id: str, **overrides: Any
) -> JsonDict:
    """Move a contract's gag dimension to ``IN_REVIEW`` with a clause inventory."""
    return get_success_data(
        api.gag_review(
            contract_id,
            f.gag_review_payload(**overrides),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )


def gag_compliant_contract(api: ApiClient, contract_id: str) -> JsonDict:
    """Take a contract's gag dimension all the way to the terminal ``COMPLIANT``."""
    open_gag_review(api, contract_id, clause_inventory_count=40, prohibited_clause_count=0)
    return get_success_data(
        api.clear_gag(
            contract_id, COMPLIANCE_OFFICER_HEADERS, f.clear_gag_payload()
        )
    )


def clear_gag_on_every_material_contract(api: ApiClient, roster: JsonDict) -> None:
    """Clear the gag dimension of each contract material to the attestation.

    The PRD examines contracts whose ``contract_type`` is ``TPA``, ``PBM``,
    ``BROKER`` or ``CONSULTANT``; ``NETWORK_VENDOR`` contracts are not
    examined and are therefore left alone.
    """
    for key in (
        "tpa_contract",
        "pbm_contract",
        "broker_contract",
        "consultant_contract",
    ):
        contract = roster.get(key)
        if contract is not None:
            gag_compliant_contract(api, contract["id"])


def gag_non_compliant_contract(
    api: ApiClient, contract_id: str, prohibited_clause_count: int = 1
) -> JsonDict:
    """Escalate a contract's gag dimension to the terminal ``NON_COMPLIANT``.

    The escalation posts one ``GAG_CLAUSE`` accrual and downgrades the plan
    year's posture in the same request.
    """
    open_gag_review(
        api,
        contract_id,
        clause_inventory_count=40,
        prohibited_clause_count=prohibited_clause_count,
    )
    return get_success_data(
        api.escalate_gag(
            contract_id, COMPLIANCE_OFFICER_HEADERS, f.escalate_gag_payload()
        )
    )


def contract_at_remediation_requested(
    api: ApiClient, contract_id: str, prohibited_clause_count: int = 2
) -> JsonDict:
    """Take a contract to ``REMEDIATION_REQUESTED`` with clauses outstanding."""
    open_gag_review(
        api,
        contract_id,
        clause_inventory_count=40,
        prohibited_clause_count=prohibited_clause_count,
    )
    return get_success_data(
        api.request_remediation(
            contract_id, COMPLIANCE_OFFICER_HEADERS, f.request_remediation_payload()
        )
    )


def contract_with_remediation_rounds_exhausted(
    api: ApiClient, contract_id: str, vendor_id: str
) -> JsonDict:
    """Run the gag remediation loop twice so ``remediation_round`` reaches 2.

    Returns the contract as it stands after the second vendor submission, which
    leaves the gag dimension at ``IN_REVIEW`` with no remediation headroom.
    """
    vendor_headers = make_vendor_contact_headers(vendor_id)
    open_gag_review(
        api, contract_id, clause_inventory_count=40, prohibited_clause_count=3
    )
    for restated in (2, 1):
        get_success_data(
            api.request_remediation(
                contract_id,
                COMPLIANCE_OFFICER_HEADERS,
                f.request_remediation_payload(),
            )
        )
        get_success_data(
            api.submit_remediation(
                contract_id,
                f.submit_remediation_payload(prohibited_clause_count=restated),
                vendor_headers,
            )
        )
    return read_contract(api, contract_id)


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts — amendments and data rights
# ---------------------------------------------------------------------------


def propose_amendment(
    api: ApiClient, contract_id: str, **overrides: Any
) -> JsonDict:
    """Propose an amendment, reading the contract's version immediately first."""
    expected_version = current_contract_version(api, contract_id)
    return get_success_data(
        api.create_amendment(
            f.amendment_payload(contract_id, expected_version, **overrides),
            SPONSOR_ADMIN_HEADERS,
        )
    )


def contract_with_secured_data_rights(
    api: ApiClient, contract_id: str, **overrides: Any
) -> JsonDict:
    """Secure a contract's data rights through an executed ``DATA_RIGHTS`` amendment.

    Returns ``{"amendment", "contract"}`` with both post-execution shapes.
    """
    amendment = propose_amendment(
        api,
        contract_id,
        amendment_type=AMENDMENT_TYPE_DATA_RIGHTS,
        data_rights_granted=True,
        **overrides,
    )
    executed = get_success_data(
        api.execute_amendment(
            amendment["id"], SPONSOR_ADMIN_HEADERS, f.execute_amendment_payload()
        )
    )
    return {"amendment": executed, "contract": read_contract(api, contract_id)}


def countered_amendment(
    api: ApiClient, contract_id: str, vendor_id: str, **overrides: Any
) -> JsonDict:
    """Propose an amendment and have the contracted vendor counter it."""
    amendment = propose_amendment(api, contract_id, **overrides)
    return get_success_data(
        api.counter_amendment(
            amendment["id"],
            f.counter_amendment_payload(),
            make_vendor_contact_headers(vendor_id),
        )
    )


def amendment_at_final_negotiation_round(
    api: ApiClient, contract_id: str, vendor_id: str, **overrides: Any
) -> JsonDict:
    """Drive an amendment's ``round`` to 3, where revision is refused.

    Each loop is a vendor counter followed by a sponsor revision, and the
    revision is what increments the round.
    """
    vendor_headers = make_vendor_contact_headers(vendor_id)
    amendment = propose_amendment(api, contract_id, **overrides)
    for _ in range(2):
        get_success_data(
            api.counter_amendment(
                amendment["id"], f.counter_amendment_payload(), vendor_headers
            )
        )
        amendment = get_success_data(
            api.revise_proposal(
                amendment["id"],
                f.revise_proposal_payload(),
                SPONSOR_ADMIN_HEADERS,
            )
        )
    return amendment


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts — machine-readable files and refresh cycles
# ---------------------------------------------------------------------------


def stage_mrf(api: ApiClient, plan_year_id: str, **overrides: Any) -> JsonDict:
    """Stage one machine-readable file in ``DRAFT``."""
    return get_success_data(
        api.create_mrf(
            f.mrf_payload(plan_year_id, **overrides), SPONSOR_ADMIN_HEADERS
        )
    )


def published_mrf(
    api: ApiClient, plan_year_id: str, file_type: str, posting_month: str, **overrides: Any
) -> JsonDict:
    """Stage a file and validate it with zero errors so it reaches ``PUBLISHED``."""
    staged = stage_mrf(
        api,
        plan_year_id,
        file_type=file_type,
        posting_month=posting_month,
        **overrides,
    )
    return get_success_data(
        api.validate_mrf(
            staged["id"],
            f.validate_mrf_payload(validation_error_count=0),
            SPONSOR_ADMIN_HEADERS,
        )
    )


def rejected_mrf(
    api: ApiClient,
    plan_year_id: str,
    file_type: str,
    posting_month: str,
    validation_error_count: int = 3,
    **overrides: Any,
) -> JsonDict:
    """Stage a file and validate it with errors so it reaches ``REJECTED``."""
    staged = stage_mrf(
        api,
        plan_year_id,
        file_type=file_type,
        posting_month=posting_month,
        **overrides,
    )
    return get_success_data(
        api.validate_mrf(
            staged["id"],
            f.validate_mrf_payload(validation_error_count=validation_error_count),
            SPONSOR_ADMIN_HEADERS,
        )
    )


def published_mrf_pair(
    api: ApiClient, plan_year_id: str, posting_month: str
) -> JsonDict:
    """Publish both required file types for one posting month.

    Certification requires a ``PUBLISHED`` file for each of the two
    ``file_type`` values, so both are staged and validated here. Returns
    ``{"in_network_rates", "allowed_amounts"}``.
    """
    in_network = published_mrf(
        api,
        plan_year_id,
        FILE_TYPE_IN_NETWORK_RATES,
        posting_month,
        public_url=f"https://transparency.meridian.example/{posting_month}-rates.json",
    )
    allowed = published_mrf(
        api,
        plan_year_id,
        FILE_TYPE_ALLOWED_AMOUNTS,
        posting_month,
        public_url=f"https://transparency.meridian.example/{posting_month}-allowed.json",
        row_count=94_000,
    )
    return {"in_network_rates": in_network, "allowed_amounts": allowed}


def open_refresh_cycle(api: ApiClient, plan_year_id: str, **overrides: Any) -> JsonDict:
    """Open a monthly refresh cycle in ``PENDING`` with its derived deadline."""
    return get_success_data(
        api.create_refresh_cycle(
            f.refresh_cycle_payload(plan_year_id, **overrides),
            SPONSOR_ADMIN_HEADERS,
        )
    )


def certified_refresh_cycle(
    api: ApiClient,
    plan_year_id: str,
    period_month: str,
    period_start: str,
    period_end: str,
) -> JsonDict:
    """Open a cycle, publish both files for its month, and certify it.

    Returns ``{"cycle", "files"}``.
    """
    cycle = open_refresh_cycle(
        api,
        plan_year_id,
        period_month=period_month,
        period_start=period_start,
        period_end=period_end,
    )
    files = published_mrf_pair(api, plan_year_id, period_month)
    certified = get_success_data(
        api.certify_refresh_cycle(
            cycle["id"], COMPLIANCE_OFFICER_HEADERS, f.certify_cycle_payload()
        )
    )
    return {"cycle": certified, "files": files}


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts — price comparison tool
# ---------------------------------------------------------------------------


def register_price_comparison_tool(
    api: ApiClient, plan_year_id: str, **overrides: Any
) -> JsonDict:
    """Register a tool in ``PENDING_LAUNCH``."""
    return get_success_data(
        api.create_price_comparison_tool(
            f.price_comparison_tool_payload(plan_year_id, **overrides),
            SPONSOR_ADMIN_HEADERS,
        )
    )


def live_price_comparison_tool(
    api: ApiClient, plan_year_id: str, **overrides: Any
) -> JsonDict:
    """Register a tool with enough covered items and launch it to ``LIVE``."""
    tool = register_price_comparison_tool(api, plan_year_id, **overrides)
    return get_success_data(
        api.launch_price_comparison_tool(tool["id"], SPONSOR_ADMIN_HEADERS)
    )


def append_outage_windows(
    api: ApiClient, tool_id: str, windows: Sequence[JsonDict]
) -> list[JsonDict]:
    """Append each window in order, returning the tool after every append."""
    results: list[JsonDict] = []
    for window in windows:
        results.append(
            get_success_data(
                api.append_outage_window(
                    tool_id, f.outage_window_payload(**window), SPONSOR_ADMIN_HEADERS
                )
            )
        )
    return results


def evaluate_tool(
    api: ApiClient, tool_id: str, evaluation_month: str
) -> JsonDict:
    """Score one elapsed month's uptime for a tool."""
    return get_success_data(
        api.evaluate_price_comparison_tool(
            tool_id,
            f.evaluation_payload(evaluation_month=evaluation_month),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )


def tool_with_downtime_in_month(
    api: ApiClient,
    plan_year_id: str,
    downtime_minutes: int,
    window_start: str,
    **overrides: Any,
) -> JsonDict:
    """A launched tool carrying one outage window of ``downtime_minutes``.

    ``window_start`` is an ISO instant on a whole minute; the window's end is
    derived by adding the requested number of minutes, so the merged downtime
    for the month equals ``downtime_minutes`` exactly.
    """
    from datetime import datetime, timedelta, timezone

    start = datetime.strptime(window_start, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    end = start + timedelta(minutes=downtime_minutes)
    tool = live_price_comparison_tool(api, plan_year_id, **overrides)
    append_outage_windows(
        api,
        tool["id"],
        [
            {
                "window_start": window_start,
                "window_end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "cause": "Regional cache outage",
            }
        ],
    )
    return get_success_data(
        api.get_price_comparison_tool(tool["id"], SPONSOR_ADMIN_HEADERS)
    )


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts — prescription-drug assembly
# ---------------------------------------------------------------------------


def open_rx_submission(api: ApiClient, plan_year_id: str, **overrides: Any) -> JsonDict:
    """Open a prescription-drug data submission in ``OPEN``."""
    return get_success_data(
        api.create_rx_submission(
            f.rx_submission_payload(plan_year_id, **overrides),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )


def request_package(
    api: ApiClient, rx_submission_id: str, vendor_id: str, **overrides: Any
) -> JsonDict:
    """Register one expected vendor data section in ``EXPECTED``."""
    return get_success_data(
        api.create_vendor_data_package(
            f.vendor_data_package_payload(rx_submission_id, vendor_id, **overrides),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )


def delivered_package(
    api: ApiClient, package_id: str, vendor_id: str, **overrides: Any
) -> JsonDict:
    """Have the owning vendor deliver a package, moving it to ``RECEIVED``."""
    return get_success_data(
        api.deliver_package(
            package_id,
            f.deliver_package_payload(**overrides),
            make_vendor_contact_headers(vendor_id),
        )
    )


def validated_package(
    api: ApiClient, package_id: str, vendor_id: str, **overrides: Any
) -> JsonDict:
    """Deliver then validate a package, adding its records to the assembled count."""
    delivered_package(api, package_id, vendor_id, **overrides)
    return get_success_data(
        api.validate_package(package_id, COMPLIANCE_OFFICER_HEADERS)
    )


def rx_submission_with_secured_vendor(
    api: ApiClient, **overrides: Any
) -> JsonDict:
    """An ``ACTIVE`` plan year whose PBM can legitimately deliver rx data.

    Builds the roster, secures the PBM contract's data rights through an
    executed ``DATA_RIGHTS`` amendment, opens the submission and registers one
    expected package. Returns ``{"plan_year", "tpa_vendor", "tpa_contract",
    "pbm_vendor", "pbm_contract", "amendment", "submission", "package"}``.
    """
    setup = activated_plan_year(api, **overrides)
    plan_year_id = setup["plan_year"]["id"]
    pbm = add_contract_for_vendor_type(
        api, plan_year_id, VENDOR_TYPE_PBM, annual_fee_cents=12_000_000
    )
    secured = contract_with_secured_data_rights(api, pbm["contract"]["id"])
    submission = open_rx_submission(api, plan_year_id)
    package = request_package(
        api,
        submission["id"],
        pbm["vendor"]["id"],
        data_section=SECTION_D2_SPENDING,
        expected_record_count=1200,
    )
    setup.update(
        {
            "pbm_vendor": pbm["vendor"],
            "pbm_contract": secured["contract"],
            "amendment": secured["amendment"],
            "submission": submission,
            "package": package,
        }
    )
    return setup


def reconciled_rx_submission(api: ApiClient, **overrides: Any) -> JsonDict:
    """A submission in ``RECONCILED`` built from two validated packages.

    The two packages carry the PRD's worked reconciliation figures, so the
    resulting submission holds gross spend of 10,000,000 cents, reported
    rebates of 2,400,000 cents, a 0.20 cap tier, a credit of 2,000,000 cents
    and net plan spend of 8,000,000 cents. Returns the setup dictionary plus
    ``{"package_a", "package_b", "submission"}``.
    """
    setup = rx_submission_with_secured_vendor(api, **overrides)
    submission_id = setup["submission"]["id"]
    pbm_vendor_id = setup["pbm_vendor"]["id"]

    package_a = setup["package"]
    validated_package(
        api,
        package_a["id"],
        pbm_vendor_id,
        record_count=1200,
        plan_paid_cents=6_000_000,
        member_paid_cents=1_000_000,
        rebate_cents=1_500_000,
    )
    package_b = request_package(
        api,
        submission_id,
        pbm_vendor_id,
        data_section=SECTION_D6_RX_TOTALS,
        expected_record_count=800,
    )
    validated_package(
        api,
        package_b["id"],
        pbm_vendor_id,
        record_count=800,
        plan_paid_cents=2_500_000,
        member_paid_cents=500_000,
        rebate_cents=900_000,
    )
    reconciled = get_success_data(
        api.reconcile_rx_submission(submission_id, COMPLIANCE_OFFICER_HEADERS)
    )
    setup.update(
        {
            "package_a": package_a,
            "package_b": package_b,
            "submission": reconciled,
        }
    )
    return setup


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts — compensation disclosures
# ---------------------------------------------------------------------------


def received_compensation_disclosure(
    api: ApiClient, contract_id: str, **overrides: Any
) -> JsonDict:
    """Record a disclosure in ``RECEIVED`` against a broker or consultant contract."""
    return get_success_data(
        api.create_compensation_disclosure(
            f.compensation_disclosure_payload(contract_id, **overrides),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )


def assessed_compensation_disclosure(
    api: ApiClient, contract_id: str, **overrides: Any
) -> JsonDict:
    """Record and then assess a disclosure, returning the assessment response."""
    disclosure = received_compensation_disclosure(api, contract_id, **overrides)
    return get_success_data(
        api.assess_compensation_disclosure(
            disclosure["id"], COMPLIANCE_OFFICER_HEADERS, f.assess_disclosure_payload()
        )
    )


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts — attestations
# ---------------------------------------------------------------------------


def attestation_draft(
    api: ApiClient,
    plan_year_id: str,
    preparer_headers: Headers = OFFICER_PREPARER_HEADERS,
    **overrides: Any,
) -> JsonDict:
    """Create an attestation draft, reading the plan year's version immediately first.

    The creating officer's identity becomes ``prepared_by_user_id``, which is
    the segregation-of-duties anchor for the submission and adjudication that
    follow.
    """
    expected_version = current_plan_year_version(api, plan_year_id)
    return get_success_data(
        api.create_attestation(
            f.attestation_payload(plan_year_id, expected_version, **overrides),
            preparer_headers,
        )
    )


def submitted_attestation(
    api: ApiClient,
    plan_year_id: str,
    preparer_headers: Headers = OFFICER_PREPARER_HEADERS,
    submitter_headers: Headers = OFFICER_SIGNER_HEADERS,
    **overrides: Any,
) -> JsonDict:
    """Prepare and submit an attestation with two distinct officer identities."""
    draft = attestation_draft(api, plan_year_id, preparer_headers, **overrides)
    return get_success_data(
        api.submit_attestation(
            draft["id"], f.submit_attestation_payload(), submitter_headers
        )
    )


def submittable_attestation_setup(api: ApiClient, **overrides: Any) -> JsonDict:
    """An ``ACTIVE`` plan year whose attestation can legitimately be submitted.

    Every material contract is cleared to gag-``COMPLIANT`` and a draft is
    prepared with contract-terms evidence attached. Returns the roster
    dictionary plus ``{"attestation"}``.
    """
    setup = activated_plan_year_with_roster(api, **overrides)
    clear_gag_on_every_material_contract(api, setup)
    setup["attestation"] = attestation_draft(
        api, setup["plan_year"]["id"], OFFICER_PREPARER_HEADERS
    )
    return setup


def accepted_attestation(api: ApiClient, **overrides: Any) -> JsonDict:
    """Take an attestation all the way to the terminal ``ACCEPTED``.

    Three distinct identities touch the record: a preparer, a submitter and an
    auditor who is neither. Returns the roster plus ``{"attestation"}``.
    """
    setup = submittable_attestation_setup(api, **overrides)
    attestation_id = setup["attestation"]["id"]
    get_success_data(
        api.submit_attestation(
            attestation_id, f.submit_attestation_payload(), OFFICER_SIGNER_HEADERS
        )
    )
    setup["attestation"] = get_success_data(
        api.accept_attestation(
            attestation_id, EXTERNAL_AUDITOR_HEADERS, f.accept_attestation_payload()
        )
    )
    return setup


def rejected_attestation(api: ApiClient, **overrides: Any) -> JsonDict:
    """Take an attestation to ``REJECTED``, which posts one lateness accrual.

    Returns the roster plus ``{"attestation"}``.
    """
    setup = submittable_attestation_setup(api, **overrides)
    attestation_id = setup["attestation"]["id"]
    get_success_data(
        api.submit_attestation(
            attestation_id, f.submit_attestation_payload(), OFFICER_SIGNER_HEADERS
        )
    )
    setup["attestation"] = get_success_data(
        api.reject_attestation(
            attestation_id, f.reject_attestation_payload(), EXTERNAL_AUDITOR_HEADERS
        )
    )
    return setup


# ---------------------------------------------------------------------------
# Tier 4: accumulation and threshold targeting
# ---------------------------------------------------------------------------


def plan_year_at_deficient_posture(api: ApiClient, **overrides: Any) -> JsonDict:
    """An ``ACTIVE`` plan year sitting at exactly the deficient threshold.

    One escalated contract carries six points, and six points is the inclusive
    floor of ``DEFICIENT``. Returns the roster plus ``{"escalated_contract"}``
    and a refreshed ``plan_year``.
    """
    setup = activated_plan_year_with_roster(api, **overrides)
    gag_non_compliant_contract(api, setup["broker_contract"]["id"])
    setup["escalated_contract"] = read_contract(
        api, setup["broker_contract"]["id"]
    )
    setup["plan_year"] = read_plan_year(api, setup["plan_year"]["id"])
    return setup


def plan_year_with_gag_accrual(api: ApiClient, **overrides: Any) -> JsonDict:
    """An ``ACTIVE`` plan year carrying exactly one ``GAG_CLAUSE`` accrual.

    Returns the roster plus ``{"escalated_contract", "accrual"}``.
    """
    setup = activated_plan_year(api, **overrides)
    plan_year_id = setup["plan_year"]["id"]
    broker = add_contract_for_vendor_type(
        api, plan_year_id, VENDOR_TYPE_BROKER, annual_fee_cents=2_400_000
    )
    gag_non_compliant_contract(api, broker["contract"]["id"])
    entries = list_ledger_entries(api, plan_year_id, entry_type="ACCRUAL")
    setup.update(
        {
            "broker_vendor": broker["vendor"],
            "broker_contract": read_contract(api, broker["contract"]["id"]),
            "escalated_contract": read_contract(api, broker["contract"]["id"]),
            "accrual": entries[0],
            "plan_year": read_plan_year(api, plan_year_id),
        }
    )
    return setup


def run_compliance(api: ApiClient, plan_year_id: str) -> JsonDict:
    """Trigger a compliance run and return its summary object."""
    return get_success_data(
        api.run_compliance(plan_year_id, COMPLIANCE_OFFICER_HEADERS)
    )


def read_penalty_projection(
    api: ApiClient, plan_year_id: str, as_of_date: str | None = None
) -> JsonDict:
    """Read the dual-variant projection, optionally as of a supplied date."""
    params = {"as_of_date": as_of_date} if as_of_date is not None else None
    return get_success_data(
        api.get_penalty_projection(
            plan_year_id, COMPLIANCE_OFFICER_HEADERS, params=params
        )
    )


# ---------------------------------------------------------------------------
# Tier 5: finalisation and terminal states
# ---------------------------------------------------------------------------


def frozen_plan_year(
    api: ApiClient, plan_year_id: str, reason: str = "Evidence trail no longer reliable"
) -> JsonDict:
    """Freeze a plan year, forcing posture ``FROZEN`` and locking child mutations."""
    return get_success_data(
        api.freeze_plan_year(
            plan_year_id, {"reason": reason}, EXTERNAL_AUDITOR_HEADERS
        )
    )


def unfrozen_plan_year(api: ApiClient, plan_year_id: str) -> JsonDict:
    """Clear a plan year's freeze flag and walk the posture ladder afresh."""
    return get_success_data(
        api.unfreeze_plan_year(plan_year_id, EXTERNAL_AUDITOR_HEADERS)
    )


def reversed_accrual(
    api: ApiClient, entry_id: str, **overrides: Any
) -> JsonDict:
    """Append a compensating entry negating the addressed accrual."""
    return get_success_data(
        api.reverse_ledger_entry(
            entry_id, f.reverse_entry_payload(**overrides), EXTERNAL_AUDITOR_HEADERS
        )
    )


def active_remediation_plan(
    api: ApiClient, plan_year_id: str, **overrides: Any
) -> JsonDict:
    """Open a remediation plan in ``ACTIVE`` with no milestones recorded yet."""
    return get_success_data(
        api.create_remediation_plan(
            f.remediation_plan_payload(plan_year_id, **overrides),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )


def remediation_plan_with_all_milestones(
    api: ApiClient,
    plan_year_id: str,
    milestone_labels: Sequence[str] | None = None,
    **overrides: Any,
) -> JsonDict:
    """A remediation plan whose ``completed_milestone_count`` equals its target.

    Returns the plan as it stands after the last milestone was recorded.
    """
    labels = list(
        milestone_labels
        if milestone_labels is not None
        else (
            "Disclosure clause struck by rider",
            "Executed rider re-reviewed by compliance",
        )
    )
    plan = active_remediation_plan(
        api, plan_year_id, milestone_count=len(labels), **overrides
    )
    for label in labels:
        plan = get_success_data(
            api.record_milestone_completion(
                plan["id"],
                f.milestone_completion_payload(milestone_label=label),
                COMPLIANCE_OFFICER_HEADERS,
            )
        )
    return plan


def completed_remediation_plan(
    api: ApiClient,
    plan_year_id: str,
    milestone_labels: Sequence[str] | None = None,
    **overrides: Any,
) -> JsonDict:
    """A remediation plan taken to the terminal ``COMPLETED`` with its abatement posted."""
    plan = remediation_plan_with_all_milestones(
        api, plan_year_id, milestone_labels, **overrides
    )
    return get_success_data(
        api.complete_remediation_plan(
            plan["id"], COMPLIANCE_OFFICER_HEADERS, f.complete_remediation_payload()
        )
    )
