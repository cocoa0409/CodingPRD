"""Composite setup helpers — multi-step preambles shared across tests.

All helpers use get_success_data() so setup failures surface as clear
'Setup failed' errors rather than confusing assertion failures. Every helper
builds its preconditions from scratch against the PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS as D
from .factories import (
    create_benchmark_payload, create_carve_out_payload, create_contract_payload,
    create_contract_version_payload, create_continuity_case_payload,
    create_fee_schedule_entry_payload, create_network_payload,
    create_paid_claim_payload, create_provider_payload,
    create_rate_parity_rule_payload, create_simulation_batch_payload,
    create_simulation_claim_payload, create_termination_notice_payload,
)
from .test_users import TEST_USERS, make_contract_legal_headers, make_contract_manager_headers

ADMIN = TEST_USERS["plan_admin_headers"]
CM = TEST_USERS["contract_manager_headers"]
CL = TEST_USERS["contract_legal_headers"]
CA = TEST_USERS["configuration_analyst_headers"]
PI = TEST_USERS["payment_integrity_headers"]


# ---------------------------------------------------------------------------
# Tier 1: leaf reference data
# ---------------------------------------------------------------------------

def create_network(name=None, line_of_business=None) -> dict:
    payload = create_network_payload()
    if name is not None:
        payload["name"] = name
    if line_of_business is not None:
        payload["line_of_business"] = line_of_business
    return get_success_data(api_client.create_network(payload, ADMIN))


def create_published_benchmark(hcpcs_code=None, locality_code=None,
                               benchmark_year=None, amount_cents=None) -> dict:
    payload = create_benchmark_payload()
    if hcpcs_code is not None:
        payload["hcpcs_code"] = hcpcs_code
    if locality_code is not None:
        payload["locality_code"] = locality_code
    if benchmark_year is not None:
        payload["benchmark_year"] = benchmark_year
    if amount_cents is not None:
        payload["benchmark_amount_cents"] = amount_cents
    bench = get_success_data(api_client.create_benchmark(payload, ADMIN))
    get_success_data(api_client.publish_benchmark(bench["id"], ADMIN))
    return bench


def create_provider(legal_name=None, tin=None, npi=None, locality_code=None) -> dict:
    payload = create_provider_payload()
    if legal_name is not None:
        payload["legal_name"] = legal_name
    if tin is not None:
        payload["tin"] = tin
    if npi is not None:
        payload["npi"] = npi
    if locality_code is not None:
        payload["locality_code"] = locality_code
    return get_success_data(api_client.create_provider(payload, ADMIN))


def create_parity_rule(lob_a="COMMERCIAL_PPO", lob_b="MEDICARE_ADVANTAGE",
                       band_bps=11000) -> dict:
    return get_success_data(api_client.create_rate_parity_rule(
        create_rate_parity_rule_payload(
            line_of_business_a=lob_a, line_of_business_b=lob_b, band_bps=band_bps,
        ), ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: contract lifecycle progression
# ---------------------------------------------------------------------------

def create_draft_contract(network_id=None, provider_id=None,
                          escalator_bps=0, escalator_mode="ANNIVERSARY",
                          base_effective_date="2026-07-01",
                          term_months=36, auto_renew=False) -> dict:
    """Create provider (if not given) + contract in DRAFT."""
    if network_id is None:
        network_id = create_network()["id"]
    if provider_id is None:
        provider_id = create_provider()["id"]
    payload = create_contract_payload(
        network_id=network_id, base_effective_date=base_effective_date,
        term_months=term_months, escalator_bps=escalator_bps,
        escalator_mode=escalator_mode, auto_renew=auto_renew,
    )
    return get_success_data(api_client.create_contract(provider_id, payload, CM))


def create_contract_in_negotiation(**kwargs) -> dict:
    contract = create_draft_contract(**kwargs)
    return get_success_data(api_client.begin_negotiation(contract["id"], CM))


def create_contract_pending_signature(submitter_id=None, **kwargs) -> dict:
    """Contract in PENDING_SIGNATURE with submitted_by_user_id recorded."""
    submitter_id = submitter_id or D["SUBMITTER_USER_ID"]
    contract = create_contract_in_negotiation(**kwargs)
    submit_headers = make_contract_manager_headers(submitter_id)
    return get_success_data(api_client.submit_for_signature(contract["id"], submit_headers))


def create_signed_contract(signer_id=None, **kwargs) -> dict:
    """Contract in SIGNED. Uses a different signer from the submitter."""
    signer_id = signer_id or D["SIGNER_USER_ID"]
    contract = create_contract_pending_signature(**kwargs)
    sign_headers = make_contract_legal_headers(signer_id)
    return get_success_data(api_client.sign_contract(contract["id"], sign_headers))


def create_contract_in_configuration(**kwargs):
    """(contract_in_configuration, contract_version_counter_after_begin_config)."""
    contract = create_signed_contract(**kwargs)
    contract = get_success_data(api_client.begin_configuration(contract["id"], CA))
    return contract


def create_contract_with_draft_version(version_number=1,
                                       effective_date="2026-07-01",
                                       retro_effective_date=None,
                                       **kwargs):
    """(contract_in_IN_CONFIGURATION, version_dict, contract_version_counter)."""
    contract = create_contract_in_configuration(**kwargs)
    payload = create_contract_version_payload(
        version_number=version_number, effective_date=effective_date,
        expected_contract_version=contract["version"],
    )
    if retro_effective_date is not None:
        payload["retro_effective_date"] = retro_effective_date
    version = get_success_data(api_client.create_contract_version(contract["id"], payload, CM))
    return contract, version, contract["version"]


# ---------------------------------------------------------------------------
# Tier 3: entries, mapping, load/validate cycle
# ---------------------------------------------------------------------------

def add_flat_rate_entry(version_id, hcpcs_code="99213",
                        service_category="OFFICE_VISIT", flat_rate_cents=5000) -> dict:
    payload = create_fee_schedule_entry_payload(
        hcpcs_code=hcpcs_code, service_category=service_category,
        rate_type="FLAT_RATE", flat_rate_cents=flat_rate_cents,
    )
    payload.pop("pct_of_medicare_bps", None)
    return get_success_data(api_client.create_fee_schedule_entry(version_id, payload, CA))


def add_pct_entry(version_id, hcpcs_code="99213", service_category="OFFICE_VISIT",
                  pct_of_medicare_bps=10000, benchmark_lookup_mode=None) -> dict:
    payload = create_fee_schedule_entry_payload(
        hcpcs_code=hcpcs_code, service_category=service_category,
        rate_type="PERCENT_OF_MEDICARE", pct_of_medicare_bps=pct_of_medicare_bps,
    )
    if benchmark_lookup_mode is not None:
        payload["benchmark_lookup_mode"] = benchmark_lookup_mode
    return get_success_data(api_client.create_fee_schedule_entry(version_id, payload, CA))


def add_mapped_entry(version_id, hcpcs_code="99213", **entry_kwargs) -> dict:
    entry = add_pct_entry(version_id, hcpcs_code=hcpcs_code, **entry_kwargs)
    return get_success_data(api_client.map_benchmark(entry["id"], CA))


def load_and_validate_version(version_id) -> dict:
    get_success_data(api_client.load_version(version_id, CA))
    return get_success_data(api_client.validate_version(version_id, CA))


# ---------------------------------------------------------------------------
# Tier 4: full paths to advanced contract states
# ---------------------------------------------------------------------------

def setup_contract_in_configuration_with_mapped_version(
        hcpcs_code="99213", pct_of_medicare_bps=10000, benchmark_cents=10000,
        benchmark_year=2026, version_effective_date="2026-07-01",
        version_number=1, carve_outs=None, **contract_kwargs):
    """Full chain: contract in IN_CONFIGURATION, one version VALIDATED with one
    MAPPED->LOCKED entry. Returns dict of all created artefacts.

    carve_outs: optional list of override dicts for create_carve_out_payload.
    Carve-outs are created while the version is still DRAFT (after the entry is
    mapped, before load/validate) because PRD 3.5 accepts carve-outs only while
    the version is in DRAFT, LOADED, or REJECTED.
    """
    net = create_network()
    bench = create_published_benchmark(
        hcpcs_code=hcpcs_code, benchmark_year=benchmark_year,
        amount_cents=benchmark_cents,
    )
    prov = create_provider()
    contract = create_contract_in_configuration(
        network_id=net["id"], provider_id=prov["id"], **contract_kwargs)
    payload = create_contract_version_payload(
        version_number=version_number, effective_date=version_effective_date,
        expected_contract_version=contract["version"],
    )
    version = get_success_data(api_client.create_contract_version(contract["id"], payload, CM))
    entry = add_mapped_entry(
        version["id"], hcpcs_code=hcpcs_code, pct_of_medicare_bps=pct_of_medicare_bps)
    created_carve_outs = []
    for spec in (carve_outs or []):
        created_carve_outs.append(get_success_data(api_client.create_carve_out(
            version["id"], create_carve_out_payload(**spec), CL)))
    version = load_and_validate_version(version["id"])
    return {
        "network": net, "benchmark": bench, "provider": prov,
        "contract": contract, "version": version, "entry": entry,
        "carve_outs": created_carve_outs,
    }


def setup_contract_in_testing(**kwargs):
    """Contract in IN_TESTING with one VALIDATED version + one OPEN batch."""
    artefacts = setup_contract_in_configuration_with_mapped_version(**kwargs)
    contract = get_success_data(api_client.begin_testing(artefacts["contract"]["id"], CA))
    batch = get_success_data(api_client.create_simulation_batch(
        artefacts["version"]["id"], create_simulation_batch_payload(), CA))
    artefacts["contract"] = contract
    artefacts["batch"] = batch
    return artefacts


def setup_contract_ready_for_go_live(**kwargs):
    """Contract in READY_FOR_GO_LIVE: testing + one PASSED batch."""
    artefacts = setup_contract_in_testing(**kwargs)
    claim = get_success_data(api_client.create_simulation_claim(
        artefacts["batch"]["id"], create_simulation_claim_payload(), CA))
    get_success_data(api_client.price_batch(artefacts["batch"]["id"], CA))
    batch = get_success_data(api_client.score_batch(artefacts["batch"]["id"], CA))
    contract = get_success_data(api_client.mark_ready(artefacts["contract"]["id"], CA))
    artefacts["batch"] = batch
    artefacts["claim"] = claim
    artefacts["contract"] = contract
    return artefacts


def setup_contract_active(**kwargs):
    """Contract fully ACTIVE with one EFFECTIVE version."""
    artefacts = setup_contract_ready_for_go_live(**kwargs)
    contract = get_success_data(api_client.approve_go_live(artefacts["contract"]["id"], ADMIN))
    # Re-read the version: it has transitioned to EFFECTIVE.
    version = get_success_data(api_client.get_contract_version(artefacts["version"]["id"], ADMIN))
    artefacts["contract"] = contract
    artefacts["version"] = version
    return artefacts


# ---------------------------------------------------------------------------
# Tier 5: amendment + retro runs
# ---------------------------------------------------------------------------

def setup_contract_with_retro_run(claim_specs=None,
                                  v2_effective_date="2026-09-01",
                                  v2_retro_effective_date="2026-08-01",
                                  v2_pct_of_medicare_bps=12000,
                                  **contract_kwargs):
    """Contract ACTIVE twice (v1 SUPERSEDED, v2 EFFECTIVE with retro). A retro
    adjustment run has been spawned under v2 with window
    [v2_retro_effective_date, v2_effective_date). Paid claims are loaded between
    the two activations.

    claim_specs: list of dicts passed to create_paid_claim_payload.

    Returns artefacts with keys: contract, v1, v2, e2, batch2, run, paid_claims.
    """
    if claim_specs is None:
        claim_specs = [{"claim_number": "CLM-1", "service_date": "2026-08-10",
                        "billed_cents": 15000, "paid_cents": 10000}]
    artefacts = setup_contract_active(**contract_kwargs)
    contract = artefacts["contract"]
    net = artefacts["network"]
    prov = artefacts["provider"]

    paid_claims = []
    for spec in claim_specs:
        pc = get_success_data(api_client.create_paid_claim(
            contract["id"], create_paid_claim_payload(**spec), PI))
        paid_claims.append(pc)

    # Amendment cycle: ACTIVE -> IN_CONFIGURATION, load v2 with retro date.
    contract = get_success_data(api_client.begin_configuration(contract["id"], CA))
    v2_payload = create_contract_version_payload(
        version_number=2, effective_date=v2_effective_date,
        retro_effective_date=v2_retro_effective_date,
        expected_contract_version=contract["version"],
    )
    v2 = get_success_data(api_client.create_contract_version(contract["id"], v2_payload, CM))
    e2 = add_mapped_entry(v2["id"], pct_of_medicare_bps=v2_pct_of_medicare_bps)
    v2 = load_and_validate_version(v2["id"])
    contract = get_success_data(api_client.begin_testing(contract["id"], CA))
    batch2 = get_success_data(api_client.create_simulation_batch(
        v2["id"], create_simulation_batch_payload(label="B2"), CA))
    # Claim priced at v2's projected rate so the batch passes
    expected = 12000  # 10000 * 12000 / 10000
    get_success_data(api_client.create_simulation_claim(
        batch2["id"], create_simulation_claim_payload(
            service_date="2026-09-15", billed_cents=20000,
            expected_allowed_cents=expected,
        ), CA))
    get_success_data(api_client.price_batch(batch2["id"], CA))
    get_success_data(api_client.score_batch(batch2["id"], CA))
    get_success_data(api_client.mark_ready(contract["id"], CA))
    contract = get_success_data(api_client.approve_go_live(contract["id"], ADMIN))

    runs = get_success_data(api_client.list_retro_runs(v2["id"], ADMIN))
    run = runs[0] if isinstance(runs, list) else runs.get("data", [None])[0]

    return {
        "network": net, "provider": prov, "benchmark": artefacts["benchmark"],
        "contract": contract, "v1": artefacts["version"], "v2": v2, "e2": e2,
        "batch2": batch2, "run": run, "paid_claims": paid_claims,
    }


# ---------------------------------------------------------------------------
# Tier 6: termination & continuity-of-care
# ---------------------------------------------------------------------------

def setup_issued_notice(notice_date="2026-05-01", termination_date="2026-08-15",
                        **contract_kwargs):
    """Contract ACTIVE -> TERMINATION_NOTICE via an ISSUED notice.
    Returns dict with contract, notice, and the underlying artefacts."""
    artefacts = setup_contract_active(**contract_kwargs)
    contract = artefacts["contract"]
    notice = get_success_data(api_client.create_termination_notice(
        contract["id"],
        create_termination_notice_payload(
            notice_date=notice_date, termination_date=termination_date,
            expected_contract_version=contract["version"],
        ), CM))
    notice = get_success_data(api_client.issue_notice(notice["id"], CM))
    artefacts["notice"] = notice
    return artefacts


def add_continuity_case(notice_id, member_ref="M1", condition_category="PREGNANCY",
                        treatment_end_date="2026-12-01") -> dict:
    return get_success_data(api_client.create_continuity_case(
        notice_id, create_continuity_case_payload(
            member_ref=member_ref, condition_category=condition_category,
            treatment_end_date=treatment_end_date,
        ), CM))


def set_clock(to_iso8601: str):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))
