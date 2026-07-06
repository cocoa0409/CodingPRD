"""Composite setup helpers.

Every fixture builds its preconditions from scratch (the server DB is empty before
each test) using only PRD-declared endpoints, and uses the lenient get_success_data()
so setup failures surface as clear "Setup failed" errors.

All five roles are opaque, so the shared TEST_USERS constants are used throughout.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS
from .factories import (
    create_cemetery_payload,
    create_section_payload,
    create_gravesite_payload,
    create_niche_payload,
    create_burial_case_payload,
    create_pmc_payload,
    create_interment_schedule_payload,
    create_marker_order_payload,
    create_military_honors_payload,
)

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["eligibility_officer_headers"]
CLERK = TEST_USERS["scheduling_clerk_headers"]
MARKER = TEST_USERS["marker_clerk_headers"]
HONORS = TEST_USERS["honors_coordinator_headers"]


# ---------------------------------------------------------------------------
# Tier 1/2: physical estate
# ---------------------------------------------------------------------------
def create_cemetery(**overrides) -> dict:
    """Create a cemetery. Returns the cemetery object."""
    resp = api_client.create_cemetery(create_cemetery_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_in_ground_section(cemetery_id, code="A", **overrides) -> dict:
    resp = api_client.create_section(
        cemetery_id, create_section_payload(cemetery_id, code=code, kind="IN_GROUND", **overrides), ADMIN
    )
    return get_success_data(resp)


def create_columbarium_section(cemetery_id, code="C", **overrides) -> dict:
    resp = api_client.create_section(
        cemetery_id, create_section_payload(cemetery_id, code=code, kind="COLUMBARIUM", **overrides), ADMIN
    )
    return get_success_data(resp)


def create_gravesite(cemetery_id, section_id, grid_ref="R1C1", gravesite_class="STANDARD",
                     depth_capacity=1, **overrides) -> dict:
    resp = api_client.create_gravesite(
        cemetery_id, section_id,
        create_gravesite_payload(section_id, grid_ref=grid_ref, gravesite_class=gravesite_class,
                                 depth_capacity=depth_capacity, **overrides),
        ADMIN,
    )
    return get_success_data(resp)


def create_niche(cemetery_id, section_id, niche_ref="T1N1", urn_capacity=2, **overrides) -> dict:
    resp = api_client.create_niche(
        cemetery_id, section_id,
        create_niche_payload(section_id, niche_ref=niche_ref, urn_capacity=urn_capacity, **overrides),
        ADMIN,
    )
    return get_success_data(resp)


def setup_cemetery_with_gravesite(depth_capacity=1, gravesite_class="STANDARD",
                                  honors_squad_capacity=2, section_code="A", grid_ref="R1C1"):
    """Cemetery + IN_GROUND section + one gravesite. Returns (cemetery, section, gravesite)."""
    cem = create_cemetery(honors_squad_capacity=honors_squad_capacity)
    sec = create_in_ground_section(cem["id"], code=section_code)
    grv = create_gravesite(cem["id"], sec["id"], grid_ref=grid_ref,
                           gravesite_class=gravesite_class, depth_capacity=depth_capacity)
    return cem, sec, grv


def setup_cemetery_with_niche(urn_capacity=2, honors_squad_capacity=2, section_code="C", niche_ref="T1N1"):
    """Cemetery + COLUMBARIUM section + one niche. Returns (cemetery, section, niche)."""
    cem = create_cemetery(honors_squad_capacity=honors_squad_capacity)
    sec = create_columbarium_section(cem["id"], code=section_code)
    niche = create_niche(cem["id"], sec["id"], niche_ref=niche_ref, urn_capacity=urn_capacity)
    return cem, sec, niche


# ---------------------------------------------------------------------------
# Tier 1: burial-case state progression
# ---------------------------------------------------------------------------
def open_case(cemetery_id, **overrides) -> dict:
    """Open a SUBMITTED burial case. Returns the case object."""
    resp = api_client.create_burial_case(cemetery_id, create_burial_case_payload(cemetery_id, **overrides), OFFICER)
    return get_success_data(resp)


def run_eligibility(cemetery_id, case_id) -> dict:
    """Run the eligibility determination. Returns the EligibilityDetermination object."""
    resp = api_client.run_eligibility(cemetery_id, case_id, OFFICER)
    return get_success_data(resp)


def open_and_approve_case(cemetery_id, **overrides) -> dict:
    """Open a case and run eligibility (expected APPROVED -> ELIGIBLE). Returns the ELIGIBLE case (re-read)."""
    case = open_case(cemetery_id, **overrides)
    run_eligibility(cemetery_id, case["id"])
    return get_success_data(api_client.get_burial_case(cemetery_id, case["id"], OFFICER))


def get_case(cemetery_id, case_id, headers=None) -> dict:
    return get_success_data(api_client.get_burial_case(cemetery_id, case_id, headers or OFFICER))


def get_gravesite(cemetery_id, section_id, gravesite_id) -> dict:
    return get_success_data(api_client.get_gravesite(cemetery_id, section_id, gravesite_id, ADMIN))


def get_niche(cemetery_id, section_id, niche_id) -> dict:
    return get_success_data(api_client.get_niche(cemetery_id, section_id, niche_id, ADMIN))


def get_section(cemetery_id, section_id) -> dict:
    return get_success_data(api_client.get_section(cemetery_id, section_id, ADMIN))


def get_pmc(cemetery_id, pmc_id) -> dict:
    return get_success_data(api_client.get_pmc(cemetery_id, pmc_id, OFFICER))


def get_schedule(cemetery_id, schedule_id) -> dict:
    return get_success_data(api_client.get_interment_schedule(cemetery_id, schedule_id, CLERK))


def get_honors(cemetery_id, honors_id) -> dict:
    return get_success_data(api_client.get_military_honors(cemetery_id, honors_id, HONORS))


def get_marker(cemetery_id, marker_id) -> dict:
    return get_success_data(api_client.get_marker_order(cemetery_id, marker_id, MARKER))


# ---------------------------------------------------------------------------
# Tier 3: assignment / scheduling shortcuts
# ---------------------------------------------------------------------------
def assign_plot_auto(cemetery_id, case_id) -> dict:
    """Auto-select assign-plot. Returns the ASSIGNED case."""
    return get_success_data(api_client.assign_plot(cemetery_id, case_id, CLERK))


def assign_plot_explicit(cemetery_id, case_id, unit_id, unit_type,
                         expected_gravesite_version=None) -> dict:
    payload = {"unit_id": unit_id, "unit_type": unit_type}
    if expected_gravesite_version is not None:
        payload["expected_gravesite_version"] = expected_gravesite_version
    return get_success_data(api_client.assign_plot(cemetery_id, case_id, CLERK, payload=payload))


def setup_assigned_case(depth_capacity=1, gravesite_class="STANDARD",
                        requested_class="STANDARD", honors_squad_capacity=2, **case_overrides):
    """Cemetery + gravesite + VETERAN case approved and auto-assigned (ASSIGNED).
    Returns (cemetery, section, gravesite, case)."""
    cem, sec, grv = setup_cemetery_with_gravesite(
        depth_capacity=depth_capacity, gravesite_class=gravesite_class,
        honors_squad_capacity=honors_squad_capacity,
    )
    case = open_and_approve_case(cem["id"], requested_class=requested_class, **case_overrides)
    assign_plot_auto(cem["id"], case["id"])
    return cem, sec, grv, get_case(cem["id"], case["id"])


def create_schedule(cemetery_id, case_id, window_start, window_end) -> dict:
    """Create an interment schedule (ASSIGNED -> SCHEDULED). Returns the schedule."""
    resp = api_client.create_interment_schedule(
        cemetery_id, create_interment_schedule_payload(case_id, window_start, window_end), CLERK
    )
    return get_success_data(resp)


def setup_scheduled_case(window_start="2026-06-10T10:00:00Z", window_end="2026-06-10T12:00:00Z",
                         depth_capacity=1, honors_squad_capacity=2, **case_overrides):
    """Cemetery + gravesite + case approved, assigned, and scheduled (SCHEDULED).
    Returns (cemetery, section, gravesite, case, schedule)."""
    cem, sec, grv, case = setup_assigned_case(
        depth_capacity=depth_capacity, honors_squad_capacity=honors_squad_capacity, **case_overrides
    )
    sched = create_schedule(cem["id"], case["id"], window_start, window_end)
    return cem, sec, grv, get_case(cem["id"], case["id"]), sched


# ---------------------------------------------------------------------------
# Tier 3: honors shortcuts
# ---------------------------------------------------------------------------
def request_honors(cemetery_id, schedule_id, detail_size="TWO_PERSON") -> dict:
    resp = api_client.create_military_honors(
        cemetery_id, create_military_honors_payload(schedule_id, detail_size=detail_size), HONORS
    )
    return get_success_data(resp)


def confirm_honors(cemetery_id, honors_id) -> dict:
    return get_success_data(api_client.confirm_military_honors(cemetery_id, honors_id, HONORS))


def setup_confirmed_honors(detail_size="FULL_SQUAD", honors_squad_capacity=3,
                           window_start="2026-06-10T10:00:00Z", window_end="2026-06-10T12:00:00Z"):
    """Cemetery + gravesite + case scheduled + honors REQUESTED then CONFIRMED.
    Returns (cemetery, section, gravesite, case, schedule, honors)."""
    cem, sec, grv, case, sched = setup_scheduled_case(
        window_start=window_start, window_end=window_end, honors_squad_capacity=honors_squad_capacity
    )
    hon = request_honors(cem["id"], sched["id"], detail_size=detail_size)
    confirm_honors(cem["id"], hon["id"])
    return cem, sec, grv, get_case(cem["id"], case["id"]), sched, get_honors(cem["id"], hon["id"])


# ---------------------------------------------------------------------------
# Tier 3/5: marker shortcuts
# ---------------------------------------------------------------------------
def create_marker(cemetery_id, case_id, marker_type="FLAT_GRANITE",
                  inscription_lines=None, emblem_of_belief=None) -> dict:
    payload = create_marker_order_payload(
        case_id, marker_type=marker_type,
        inscription_lines=inscription_lines if inscription_lines is not None else ["A VETERAN"],
    )
    if emblem_of_belief is not None:
        payload["emblem_of_belief"] = emblem_of_belief
    resp = api_client.create_marker_order(cemetery_id, payload, MARKER)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 4/5: pre-need (PMC) shortcuts
# ---------------------------------------------------------------------------
def create_pmc(cemetery_id, case_id) -> dict:
    """Open a PENDING PMC. Returns the PMC (has version captured for OCC)."""
    resp = api_client.create_pmc(cemetery_id, create_pmc_payload(case_id), OFFICER)
    return get_success_data(resp)


def approve_pmc(cemetery_id, pmc_id, expected_pmc_version) -> dict:
    return get_success_data(api_client.approve_pmc(cemetery_id, pmc_id, expected_pmc_version, OFFICER))


def setup_preneed_eligible_case(honors_squad_capacity=1, requested_class="STANDARD", **case_overrides):
    """Cemetery + gravesite + PRE_NEED VETERAN case approved (ELIGIBLE), plus a PENDING PMC.
    Returns (cemetery, section, gravesite, case, pmc)."""
    cem, sec, grv = setup_cemetery_with_gravesite(honors_squad_capacity=honors_squad_capacity)
    case = open_and_approve_case(cem["id"], case_type="PRE_NEED",
                                 requested_class=requested_class, **case_overrides)
    pmc = create_pmc(cem["id"], case["id"])
    return cem, sec, grv, get_case(cem["id"], case["id"]), pmc


def setup_preneed_approved_case(honors_squad_capacity=1, requested_class="STANDARD", **case_overrides):
    """Cemetery + gravesite + PRE_NEED VETERAN case ELIGIBLE with an APPROVED PMC (not yet assigned).
    Returns (cemetery, section, gravesite, case, pmc). Caller must set the clock first if needed."""
    cem, sec, grv, case, pmc = setup_preneed_eligible_case(
        honors_squad_capacity=honors_squad_capacity, requested_class=requested_class, **case_overrides
    )
    approve_pmc(cem["id"], pmc["id"], pmc["version"])
    return cem, sec, grv, get_case(cem["id"], case["id"]), get_pmc(cem["id"], pmc["id"])


def set_clock(to_iso8601):
    """Set the logical clock (NCA_Admin)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))
