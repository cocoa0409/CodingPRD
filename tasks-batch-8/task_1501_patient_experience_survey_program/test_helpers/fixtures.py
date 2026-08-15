"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch via PRD-declared endpoints
(the server is restarted before each test, so nothing carries over). Setup
calls use get_success_data() so failures surface as clear "Setup failed"
errors rather than confusing assertion failures.

Identity threading: VendorOperator and UnitManager are entity-backed roles
(PRD §2.1), so intake / mark-undeliverable calls use
make_vendor_headers(<SurveyVendor.id>) and ticket calls use
make_unit_manager_headers(<CareUnit.id>) — never the shared constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import ELIGIBLE_TEMPLATE_BASE, TEST_DEFAULTS
from .factories import (
    create_cycle_payload,
    create_discharge_import_payload,
    create_initiative_payload,
    create_program_payload,
    create_provider_payload,
    create_response_import_payload,
    create_response_payload,
    create_sample_case_import_payload,
    create_sample_case_payload,
    create_ticket_payload,
    create_unit_payload,
    create_vendor_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_unit_manager_headers, make_vendor_headers

ADMIN = TEST_USERS["admin_headers"]
STEWARD = TEST_USERS["steward_headers"]
ANY_READ = TEST_USERS["admin_headers"]  # GET endpoints are roles: [Any]

# Canonical per-quarter (discharge window, fielding window, close clock) used
# when a test needs several cycles of one program whose fielding windows never
# touch (PRD §3.3 closed-interval rule).
QUARTER_WINDOWS = {
    1: ("2026-06-01", "2026-06-30", "2026-08-03", "2026-08-31",
        "2026-08-31T00:00:00Z"),
    2: ("2026-07-01", "2026-07-31", "2026-09-01", "2026-09-30",
        "2026-09-30T00:00:00Z"),
    3: ("2026-08-01", "2026-08-31", "2026-10-01", "2026-10-31",
        "2026-10-31T00:00:00Z"),
}


# ---------------------------------------------------------------------------
# Tier 0: single-call wrappers
# ---------------------------------------------------------------------------

def make_program(name="Test Program", sampling_protocol="CENSUS",
                 admin_mode="MAIL_ONLY") -> dict:
    return get_success_data(api_client.create_program(
        create_program_payload(
            name=name, sampling_protocol=sampling_protocol, admin_mode=admin_mode),
        ADMIN))


def get_program(program_id: str) -> dict:
    return get_success_data(api_client.get_program(program_id, ANY_READ))


def make_vendor(program_id: str, expected_program_version: int,
                name="Vendor 1", cycle_budget_cents=None) -> dict:
    """Register a vendor; the OCC field expected_program_version is required
    (PRD §2.10)."""
    return get_success_data(api_client.create_vendor(
        create_vendor_payload(
            program_id, expected_program_version, name=name,
            cycle_budget_cents=(
                TEST_DEFAULTS["VENDOR_BUDGET_CENTS"]
                if cycle_budget_cents is None else cycle_budget_cents)),
        ADMIN))


def get_vendor(vendor_id: str) -> dict:
    return get_success_data(api_client.get_vendor(vendor_id, ANY_READ))


def make_unit(program_id: str, name="Unit 1", unit_code="U1") -> dict:
    return get_success_data(api_client.create_unit(
        create_unit_payload(program_id, name=name, unit_code=unit_code), ADMIN))


def make_provider(program_id: str, full_name="Dr A", npi="NPI1",
                  specialty="IM") -> dict:
    return get_success_data(api_client.create_provider(
        create_provider_payload(
            program_id, full_name=full_name, npi=npi, specialty=specialty),
        ADMIN))


def make_cycle(program_id: str, label="Q1", cycle_index=1, **overrides) -> dict:
    return get_success_data(api_client.create_cycle(
        create_cycle_payload(
            program_id, label=label, cycle_index=cycle_index, **overrides),
        ADMIN))


def get_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.get_cycle(cycle_id, ANY_READ))


def get_case(case_id: str) -> dict:
    return get_success_data(api_client.get_sample_case(case_id, ANY_READ))


def get_response(response_id: str) -> dict:
    return get_success_data(api_client.get_response(response_id, ANY_READ))


def get_initiative(initiative_id: str) -> dict:
    return get_success_data(api_client.get_initiative(initiative_id, ANY_READ))


def get_ticket(ticket_id: str) -> dict:
    return get_success_data(api_client.get_ticket(ticket_id, ANY_READ))


def set_clock(to_iso8601: str) -> None:
    get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), ADMIN))


def import_discharges(program_id: str, unit_id: str, provider_id: str,
                      count: int, mrn_prefix="M", **template_overrides) -> list:
    """Bulk discharge feed (PRD §3.2). Returns discharge_ids in creation order."""
    payload = create_discharge_import_payload(
        program_id, unit_id, provider_id, count,
        mrn_prefix=mrn_prefix, **template_overrides)
    data = get_success_data(api_client.import_discharges(payload, STEWARD))
    assert data["created_count"] == count, (
        f"Setup failed: discharge import created {data['created_count']} "
        f"of {count}")
    return data["discharge_ids"]


def import_cases(cycle_id: str, discharge_ids: list, mode_assigned="MAIL",
                 postage_cost_cents=None) -> list:
    """Bulk sampling (PRD §3.3). Returns sample_case_ids in creation order."""
    payload = create_sample_case_import_payload(
        cycle_id, discharge_ids, mode_assigned=mode_assigned,
        postage_cost_cents=(TEST_DEFAULTS["POSTAGE_COST_CENTS"]
                            if postage_cost_cents is None
                            else postage_cost_cents))
    data = get_success_data(api_client.import_sample_cases(payload, STEWARD))
    assert data["created_count"] == len(discharge_ids), (
        f"Setup failed: case import created {data['created_count']} "
        f"of {len(discharge_ids)}")
    return data["sample_case_ids"]


def import_responses(case_ids: list, vendor_id: str, mode_used="MAIL",
                     score=4, comment_text=None) -> list:
    """Bulk response intake (PRD §3.4) by the owning VendorOperator.
    Returns response_ids in creation order."""
    overrides = {"mode_used": mode_used}
    for key in ("nurse_comm_score", "doctor_comm_score", "cleanliness_score",
                "overall_rating_score"):
        overrides[key] = score
    if comment_text is not None:
        overrides["comment_text"] = comment_text
    payload = create_response_import_payload(case_ids, **overrides)
    data = get_success_data(api_client.import_responses(
        payload, make_vendor_headers(vendor_id)))
    assert data["created_count"] == len(case_ids), (
        f"Setup failed: response import created {data['created_count']} "
        f"of {len(case_ids)}")
    return data["response_ids"]


def record_response(case_id: str, vendor_id: str, mode_used="MAIL", score=4,
                    comment_text=None, **score_overrides) -> dict:
    """Single response intake (PRD §3.4). Returns the SurveyResponse."""
    payload = create_response_payload(
        case_id, mode_used=mode_used,
        nurse_comm_score=score_overrides.get("nurse_comm_score", score),
        doctor_comm_score=score_overrides.get("doctor_comm_score", score),
        cleanliness_score=score_overrides.get("cleanliness_score", score),
        overall_rating_score=score_overrides.get("overall_rating_score", score))
    if comment_text is not None:
        payload["comment_text"] = comment_text
    return get_success_data(api_client.create_response(
        payload, make_vendor_headers(vendor_id)))


# ---------------------------------------------------------------------------
# Tier 1: program context assembly
# ---------------------------------------------------------------------------

def setup_program(admin_mode="MAIL_ONLY", sampling_protocol="CENSUS",
                  vendor_budget_cents=None, name="Test Program",
                  with_org=True) -> dict:
    """Program + ACTIVE vendor (+ one care unit + one provider).

    Returns {"program", "vendor", "unit", "provider"}. The vendor registration
    is OCC-guarded (PRD §2.10): it carries the program's freshly read version.
    """
    program = make_program(
        name=name, sampling_protocol=sampling_protocol, admin_mode=admin_mode)
    vendor = make_vendor(program["id"], program["version"],
                         cycle_budget_cents=vendor_budget_cents)
    unit = make_unit(program["id"]) if with_org else None
    provider = make_provider(program["id"]) if with_org else None
    return {
        "program": program,
        "vendor": vendor,
        "unit": unit,
        "provider": provider,
    }


def setup_cycle_in_state(prog_ctx: dict, target_state: str, label="Q1",
                         cycle_index=1, discharge_count=1, mrn_prefix="M",
                         mode_assigned="MAIL", postage_cost_cents=100,
                         **cycle_overrides) -> dict:
    """Walk a cycle to DRAFT / SAMPLING_OPEN / FIELDING (PRD §3.3).

    Returns a context dict {"program", "vendor", "unit", "provider", "cycle",
    "discharge_ids", "case_ids"}. Sampling targets the cycle's own discharge
    window so the default June window is honored for cycle_index 1; other
    indexes take their windows from QUARTER_WINDOWS unless overridden.
    """
    program = prog_ctx["program"]
    unit = prog_ctx["unit"]
    provider = prog_ctx["provider"]
    vendor = prog_ctx["vendor"]

    if cycle_index in QUARTER_WINDOWS and not cycle_overrides:
        (dw_start, dw_end, fw_start, fw_end, _close_clock) = (
            QUARTER_WINDOWS[cycle_index])
        cycle_overrides = {
            "discharge_window_start": dw_start,
            "discharge_window_end": dw_end,
            "fielding_start_date": fw_start,
            "fielding_end_date": fw_end,
        }
    cycle = make_cycle(program["id"], label=label, cycle_index=cycle_index,
                       **cycle_overrides)

    discharge_ids: list = []
    case_ids: list = []
    if target_state == "DRAFT":
        pass
    else:
        get_success_data(api_client.open_sampling(cycle["id"], ADMIN))
        if discharge_count > 0:
            discharge_ids = import_discharges(
                program["id"], unit["id"], provider["id"], discharge_count,
                mrn_prefix=mrn_prefix,
                admit_date=cycle["discharge_window_start"],
                discharge_date=_third_day(cycle["discharge_window_start"]))
            case_ids = import_cases(cycle["id"], discharge_ids,
                                    mode_assigned=mode_assigned,
                                    postage_cost_cents=postage_cost_cents)
            if target_state in ("FIELDING", "RECONCILIATION", "SCORING",
                                "PUBLISHED"):
                get_success_data(api_client.start_fielding(cycle["id"], ADMIN))
        elif target_state != "SAMPLING_OPEN":
            raise AssertionError(
                "Setup failed: cannot reach FIELDING+ without sampled cases "
                "(ERR_NO_CASES_SAMPLED, PRD §3.3)")

    cycle = get_cycle(cycle["id"])
    assert cycle["status"] == target_state, (
        f"Setup failed: cycle in {cycle['status']}, wanted {target_state}")
    return {
        "program": program,
        "vendor": vendor,
        "unit": unit,
        "provider": provider,
        "cycle": cycle,
        "discharge_ids": discharge_ids,
        "case_ids": case_ids,
    }


def _third_day(iso_date: str) -> str:
    """discharge_date two days after admit_date keeps the stay overnight
    (no SHORT_STAY reason, PRD §3.2) while staying inside a monthly window."""
    return iso_date[:8] + "03"


# ---------------------------------------------------------------------------
# Tier 2: publishable cycles with engineered unit-level adjusted percentages
# ---------------------------------------------------------------------------

def setup_published_cycle(prog_ctx: dict, cycle_index: int, label: str,
                          topbox_count: int, low_count: int,
                          unit_id: str = None, provider_id: str = None,
                          mrn_prefix="M", mode_used="MAIL",
                          mode_assigned="MAIL") -> dict:
    """Build a PUBLISHED cycle whose program-level (and unit-level, when all
    cases share one unit) adjusted top-box percentage is exactly
    round_half_up(100 * topbox_count / (topbox_count + low_count), 2):
    `topbox_count` all-4 responses plus `low_count` all-3 responses, all in
    `mode_used`. Requires topbox_count + low_count >= 25 so the publication
    gate passes (PRD §3.6); response rate is 100.00.

    Returns {"cycle", "case_ids"} with the cycle re-read as PUBLISHED.
    """
    program = prog_ctx["program"]
    vendor = prog_ctx["vendor"]
    unit_id = unit_id or prog_ctx["unit"]["id"]
    provider_id = provider_id or prog_ctx["provider"]["id"]

    (dw_start, dw_end, fw_start, fw_end, close_clock) = (
        QUARTER_WINDOWS[cycle_index])
    cycle = make_cycle(
        program["id"], label=label, cycle_index=cycle_index,
        discharge_window_start=dw_start, discharge_window_end=dw_end,
        fielding_start_date=fw_start, fielding_end_date=fw_end,
        target_sample_size=max(100, topbox_count + low_count))
    get_success_data(api_client.open_sampling(cycle["id"], ADMIN))
    d_top = import_discharges(
        program["id"], unit_id, provider_id, topbox_count,
        mrn_prefix=f"{mrn_prefix}T{label}",
        admit_date=dw_start, discharge_date=_third_day(dw_start))
    k_top = import_cases(cycle["id"], d_top, mode_assigned=mode_assigned)
    k_low: list = []
    if low_count > 0:
        # PRD §3.2: import count must be between 1 and 500; skip when zero.
        d_low = import_discharges(
            program["id"], unit_id, provider_id, low_count,
            mrn_prefix=f"{mrn_prefix}L{label}",
            admit_date=dw_start, discharge_date=_third_day(dw_start))
        k_low = import_cases(cycle["id"], d_low, mode_assigned=mode_assigned)
    get_success_data(api_client.start_fielding(cycle["id"], ADMIN))
    import_responses(k_top, vendor["id"], mode_used=mode_used, score=4)
    if k_low:
        import_responses(k_low, vendor["id"], mode_used=mode_used, score=3)
    set_clock(close_clock)
    get_success_data(api_client.close_fielding(cycle["id"], ADMIN))
    get_success_data(api_client.begin_scoring(cycle["id"], ADMIN))
    published = get_success_data(api_client.publish_cycle(cycle["id"], ADMIN))
    assert published["status"] == "PUBLISHED", (
        f"Setup failed: publish landed in {published['status']}")
    return {"cycle": published, "case_ids": k_top + k_low}


def field_and_publish_cycle(prog_ctx: dict, cycle: dict, topbox_count: int,
                            low_count: int, unit_id: str = None,
                            provider_id: str = None, mrn_prefix="M",
                            mode_used="MAIL", mode_assigned="MAIL") -> dict:
    """Field an EXISTING DRAFT cycle (created via make_cycle) through
    SAMPLING_OPEN -> FIELDING -> RECONCILIATION -> SCORING -> PUBLISHED with
    `topbox_count` all-4 + `low_count` all-3 responses in `mode_used`, giving
    an adjusted top-box percentage of exactly
    round_half_up(100 * topbox_count / (topbox_count + low_count), 2) on the
    attributed unit. Returns the cycle re-read as PUBLISHED.
    """
    program = prog_ctx["program"]
    vendor = prog_ctx["vendor"]
    unit_id = unit_id or prog_ctx["unit"]["id"]
    provider_id = provider_id or prog_ctx["provider"]["id"]

    get_success_data(api_client.open_sampling(cycle["id"], ADMIN))
    dw_start = cycle["discharge_window_start"]
    d_top = import_discharges(
        program["id"], unit_id, provider_id, topbox_count,
        mrn_prefix=f"{mrn_prefix}T{cycle['label']}",
        admit_date=dw_start, discharge_date=_third_day(dw_start))
    k_top = import_cases(cycle["id"], d_top, mode_assigned=mode_assigned)
    k_low: list = []
    if low_count > 0:
        # PRD §3.2: import count must be between 1 and 500; skip when zero.
        d_low = import_discharges(
            program["id"], unit_id, provider_id, low_count,
            mrn_prefix=f"{mrn_prefix}L{cycle['label']}",
            admit_date=dw_start, discharge_date=_third_day(dw_start))
        k_low = import_cases(cycle["id"], d_low, mode_assigned=mode_assigned)
    get_success_data(api_client.start_fielding(cycle["id"], ADMIN))
    import_responses(k_top, vendor["id"], mode_used=mode_used, score=4)
    if k_low:
        import_responses(k_low, vendor["id"], mode_used=mode_used, score=3)
    # Close the moment the fielding window ends (the gate is inclusive).
    set_clock(cycle["fielding_end_date"] + "T00:00:00Z")
    get_success_data(api_client.close_fielding(cycle["id"], ADMIN))
    get_success_data(api_client.begin_scoring(cycle["id"], ADMIN))
    published = get_success_data(api_client.publish_cycle(cycle["id"], ADMIN))
    assert published["status"] == "PUBLISHED", (
        f"Setup failed: publish landed in {published['status']}")
    return published


def make_active_initiative(unit_id: str, domain: str, baseline_cycle_id: str,
                           evaluation_cycle_id: str, target_score: float
                           ) -> dict:
    """Create + activate an initiative (DRAFT -> ACTIVE, pinning
    baseline_score from the baseline cycle, PRD §3.8)."""
    initiative = get_success_data(api_client.create_initiative(
        create_initiative_payload(
            unit_id, domain, baseline_cycle_id, evaluation_cycle_id,
            target_score=target_score),
        ADMIN))
    activated = get_success_data(
        api_client.activate_initiative(initiative["id"], ADMIN))
    assert activated["status"] == "ACTIVE", (
        f"Setup failed: initiative activation landed in "
        f"{activated['status']}")
    return activated


def make_ticket(unit_id: str, response_id: str, domain="OVERALL_RATING",
                priority="MEDIUM") -> dict:
    """Route a commented response into a service-recovery ticket (PRD §3.9)
    as the owning UnitManager."""
    return get_success_data(api_client.create_ticket(
        create_ticket_payload(unit_id, response_id, domain=domain,
                              priority=priority),
        make_unit_manager_headers(unit_id)))
