"""Composite setup helpers — multi-step API sequences used by many tests.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (per-test-server isolation means each test starts with an empty DB).
All internal calls use get_success_data() so setup failures surface as a clear
"Setup failed" rather than a confusing assertion mismatch.

Identity threading: any StationGroupOwner call uses
make_station_group_owner_headers(station_group_id) — never the shared constant
— because StationGroupOwner is entity_backed:StationGroup (PRD §2.1).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULTS
from .factories import (
    create_agreement_payload,
    create_avail_allocation_payload,
    create_clearance_report_payload,
    create_compliance_report_payload,
    create_exclusivity_claim_payload,
    create_network_payload,
    create_outage_event_payload,
    create_preemption_payload,
    create_program_payload,
    create_renewal_offer_payload,
    create_retrans_settlement_payload,
    create_station_group_payload,
    create_station_payload,
    create_territory_payload,
)
from .test_users import (
    make_auditor_headers,
    make_nar_headers,
    make_platform_admin_headers,
    make_station_group_owner_headers,
)


def setup_clock(iso: str = DEFAULTS["TERM_START"]):
    """Drive the logical clock to a specific instant (PRD §2.8)."""
    headers = make_platform_admin_headers()
    get_success_data(api_client.set_current_utc({"to_iso8601": iso}, headers))


def create_network(**overrides):
    headers = make_platform_admin_headers()
    payload = create_network_payload(**overrides)
    return get_success_data(api_client.create_network(payload, headers))


def create_station_group(leverage_tier: str = DEFAULTS["LEVERAGE_TIER"], **overrides):
    headers = make_platform_admin_headers()
    payload = create_station_group_payload(leverage_tier=leverage_tier, **overrides)
    return get_success_data(api_client.create_station_group(payload, headers))


def create_station(network_id: str, station_group_id: str, **overrides):
    headers = make_nar_headers()
    payload = create_station_payload(station_group_id=station_group_id, **overrides)
    return get_success_data(api_client.create_station(network_id, payload, headers))


def create_territory(network_id: str, **overrides):
    headers = make_nar_headers()
    payload = create_territory_payload(**overrides)
    return get_success_data(api_client.create_territory(network_id, payload, headers))


def create_program(network_id: str, **overrides):
    headers = make_nar_headers()
    payload = create_program_payload(**overrides)
    return get_success_data(api_client.create_program(network_id, payload, headers))


# ---------------------------------------------------------------------------
# Tier 1: agreement state progression
# ---------------------------------------------------------------------------

def create_draft_agreement(network_id: str, station_id: str, **overrides):
    headers = make_nar_headers()
    payload = create_agreement_payload(**overrides)
    return get_success_data(api_client.create_agreement(network_id, station_id, payload, headers))


def create_pending_agreement(network_id: str, station_id: str, **overrides):
    """DRAFT -> PENDING_ACTIVATION."""
    headers = make_nar_headers()
    agreement = create_draft_agreement(network_id, station_id, **overrides)
    return get_success_data(
        api_client.submit_agreement(network_id, station_id, agreement["id"], headers)
    )


def create_active_agreement(network_id: str, station_id: str, **overrides):
    """DRAFT -> PENDING_ACTIVATION -> ACTIVE. Requires the territory covering
    the station's dma_code to have null or self exclusivity holder, and
    Network.current_utc >= term_start_utc (PRD §3.2)."""
    headers = make_nar_headers()
    pending = create_pending_agreement(network_id, station_id, **overrides)
    return get_success_data(
        api_client.activate_agreement(network_id, station_id, pending["id"], headers)
    )


# ---------------------------------------------------------------------------
# Tier 2: full bootstrap — network, group, station, territory, ACTIVE agreement
# ---------------------------------------------------------------------------

def setup_basic_scenario(
    *,
    clock_iso: str = "2026-05-01T00:00:00Z",
    leverage_tier: str = DEFAULTS["LEVERAGE_TIER"],
    dma_code: str = DEFAULTS["DMA_CODE"],
    clearance_obligation_hours: int = DEFAULTS["CLEARANCE_OBLIGATION_HOURS"],
    term_start_utc: str = DEFAULTS["TERM_START"],
    term_end_utc: str = DEFAULTS["TERM_END"],
    reverse_comp_pct: float = DEFAULTS["REVERSE_COMP_PCT"],
    retrans_share_pct: float = DEFAULTS["RETRANS_SHARE_PCT"],
):
    """Returns dict with keys:
        network, group, station, territory, agreement
        nar_headers, admin_headers, sgo_headers (station-group-scoped)
    The agreement is ACTIVE.
    """
    setup_clock(clock_iso)
    admin_headers = make_platform_admin_headers()
    nar_headers = make_nar_headers()

    network = create_network()
    group = create_station_group(leverage_tier=leverage_tier)
    sgo_headers = make_station_group_owner_headers(group["id"])
    station = create_station(network["id"], group["id"], dma_code=dma_code)
    territory = create_territory(network["id"], dma_code=dma_code)
    agreement = create_active_agreement(
        network["id"],
        station["id"],
        term_start_utc=term_start_utc,
        term_end_utc=term_end_utc,
        reverse_comp_pct=reverse_comp_pct,
        retrans_share_pct=retrans_share_pct,
        clearance_obligation_hours=clearance_obligation_hours,
    )
    return {
        "network": network,
        "group": group,
        "station": station,
        "territory": territory,
        "agreement": agreement,
        "admin_headers": admin_headers,
        "nar_headers": nar_headers,
        "sgo_headers": sgo_headers,
    }


def setup_scenario_no_territory(
    *,
    clock_iso: str = "2026-05-01T00:00:00Z",
    leverage_tier: str = DEFAULTS["LEVERAGE_TIER"],
):
    """Network + group + station, no territory (no ACTIVE agreement possible
    without exclusivity-holder-null territory in PRD §3.2 — but submitting to
    PENDING_ACTIVATION is allowed)."""
    setup_clock(clock_iso)
    admin_headers = make_platform_admin_headers()
    nar_headers = make_nar_headers()
    network = create_network()
    group = create_station_group(leverage_tier=leverage_tier)
    sgo_headers = make_station_group_owner_headers(group["id"])
    station = create_station(network["id"], group["id"])
    return {
        "network": network,
        "group": group,
        "station": station,
        "admin_headers": admin_headers,
        "nar_headers": nar_headers,
        "sgo_headers": sgo_headers,
    }


# ---------------------------------------------------------------------------
# Tier 3: Preemption lifecycle
# ---------------------------------------------------------------------------

def create_preemption_request(network_id, station_id, program_id, agreement_id, sgo_headers, **overrides):
    payload = create_preemption_payload(
        program_id=program_id, agreement_id=agreement_id, **overrides
    )
    return get_success_data(
        api_client.create_preemption(network_id, station_id, payload, sgo_headers)
    )


def walk_preemption_to_under_review(network_id, station_id, preemption_id, nar_headers):
    return get_success_data(
        api_client.begin_review_preemption(network_id, station_id, preemption_id, nar_headers)
    )


def walk_preemption_to_countered(
    network_id, station_id, preemption_id, nar_headers,
    counter_start_utc, counter_end_utc,
):
    walk_preemption_to_under_review(network_id, station_id, preemption_id, nar_headers)
    return get_success_data(
        api_client.counter_preemption(
            network_id, station_id, preemption_id,
            {"counter_start_utc": counter_start_utc, "counter_end_utc": counter_end_utc},
            nar_headers,
        )
    )


# ---------------------------------------------------------------------------
# Tier 3: Clearance report lifecycle
# ---------------------------------------------------------------------------

def create_clearance_report(network_id, station_id, sgo_headers, **overrides):
    payload = create_clearance_report_payload(**overrides)
    return get_success_data(
        api_client.create_clearance_report(network_id, station_id, payload, sgo_headers)
    )


def walk_clearance_to_filed(network_id, station_id, report_id, sgo_headers):
    return get_success_data(
        api_client.file_clearance_report(network_id, station_id, report_id, sgo_headers)
    )


def walk_clearance_to_audited(network_id, station_id, report_id, sgo_headers, nar_headers):
    walk_clearance_to_filed(network_id, station_id, report_id, sgo_headers)
    return get_success_data(
        api_client.audit_clearance_report(network_id, station_id, report_id, nar_headers)
    )


# ---------------------------------------------------------------------------
# Tier 3: Compliance report lifecycle
# ---------------------------------------------------------------------------

def create_compliance_report(network_id, station_id, headers, **overrides):
    payload = create_compliance_report_payload(**overrides)
    return get_success_data(
        api_client.create_compliance_report(network_id, station_id, payload, headers)
    )


def walk_compliance_to_failed(network_id, station_id, report_id, sgo_headers, nar_headers,
                              finding_count: int = 1):
    get_success_data(
        api_client.submit_compliance_report(network_id, station_id, report_id, sgo_headers)
    )
    get_success_data(
        api_client.audit_compliance_report(
            network_id, station_id, report_id, {"finding_count": finding_count}, nar_headers
        )
    )
    return get_success_data(
        api_client.resolve_fail_compliance_report(network_id, station_id, report_id, nar_headers)
    )


def drive_network_into_sweep_lockdown(network_id, station_id, sgo_headers, nar_headers):
    """Create + drive 3 ComplianceReports to FAILED to force SWEEP_LOCKDOWN (PRD §2.9)."""
    reports = []
    for _ in range(3):
        report = create_compliance_report(network_id, station_id, sgo_headers)
        walk_compliance_to_failed(network_id, station_id, report["id"], sgo_headers, nar_headers)
        reports.append(report)
    return reports


# ---------------------------------------------------------------------------
# Tier 3: Outage lifecycle
# ---------------------------------------------------------------------------

def create_outage_event(network_id, station_id, sgo_headers, **overrides):
    payload = create_outage_event_payload(**overrides)
    return get_success_data(
        api_client.create_outage_event(network_id, station_id, payload, sgo_headers)
    )


def confirm_outage_event(network_id, station_id, event_id, nar_headers):
    return get_success_data(
        api_client.confirm_outage_event(network_id, station_id, event_id, nar_headers)
    )


def create_and_confirm_outage(network_id, station_id, sgo_headers, nar_headers, **overrides):
    """Report + confirm. Returns (event, credit) — the credit is the PENDING
    outage credit created by confirmation (PRD §3.7)."""
    event = create_outage_event(network_id, station_id, sgo_headers, **overrides)
    confirm_outage_event(network_id, station_id, event["id"], nar_headers)
    # The confirm response is the OutageEvent; fetch the credit via list.
    credits_resp = get_success_data(
        api_client.list_outage_credits(network_id, station_id, nar_headers,
                                       params={"outage_event_id": event["id"]})
    )
    # credits_resp for list endpoints returns the full envelope; data is the array.
    credits = credits_resp.get("data") if isinstance(credits_resp, dict) else None
    credit = credits[0] if credits else None
    return event, credit


# ---------------------------------------------------------------------------
# Tier 3: Avail allocations
# ---------------------------------------------------------------------------

def create_avail_allocation(network_id, station_id, program_id, sgo_headers, **overrides):
    payload = create_avail_allocation_payload(program_id=program_id, **overrides)
    return get_success_data(
        api_client.create_avail_allocation(network_id, station_id, payload, sgo_headers)
    )


def confirm_avail_allocation(network_id, station_id, alloc_id, nar_headers):
    return get_success_data(
        api_client.confirm_avail_allocation(network_id, station_id, alloc_id, nar_headers)
    )


# ---------------------------------------------------------------------------
# Tier 3: Retrans settlements
# ---------------------------------------------------------------------------

def create_retrans_settlement(network_id, station_id, agreement_id, headers, **overrides):
    payload = create_retrans_settlement_payload(agreement_id=agreement_id, **overrides)
    return get_success_data(
        api_client.create_retrans_settlement(network_id, station_id, payload, headers)
    )


def commit_retrans_settlement(network_id, station_id, settlement_id, nar_headers,
                              expected_station_version):
    return get_success_data(
        api_client.commit_retrans_settlement(
            network_id, station_id, settlement_id,
            {"expected_station_version": expected_station_version},
            nar_headers,
        )
    )


# ---------------------------------------------------------------------------
# Tier 3: Renewal offers
# ---------------------------------------------------------------------------

def create_renewal_offer(network_id, station_id, agreement_id, headers, **overrides):
    payload = create_renewal_offer_payload(**overrides)
    return get_success_data(
        api_client.create_renewal_offer(network_id, station_id, agreement_id, payload, headers)
    )


# ---------------------------------------------------------------------------
# Tier 3: Syndication exclusivity claims
# ---------------------------------------------------------------------------

def create_exclusivity_claim(network_id, territory_id, sgo_headers,
                             program_id, claimant_station_id, respondent_station_id,
                             **overrides):
    payload = create_exclusivity_claim_payload(
        program_id=program_id,
        claimant_station_id=claimant_station_id,
        respondent_station_id=respondent_station_id,
        **overrides,
    )
    return get_success_data(
        api_client.create_exclusivity_claim(network_id, territory_id, payload, sgo_headers)
    )
