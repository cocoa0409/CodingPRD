"""Composite setup helpers.

Five tiers of helper, from a single create through to a fully wound-down lease:

* Tier 1 -- single-resource creates and state progressions.
* Tier 2 -- entity hierarchy: a building with plates, a tenant with a lease,
  a project with phase packages.
* Tier 3 -- lifecycle shortcuts that drive a resource to a named state in one
  call: an accepted assessment, a conversion-approved building, an executed
  lease, a permitted project, a project at substantial completion.
* Tier 4 -- accumulation and threshold targeting: committing allowance phase by
  phase, funding escrow to exactly the requirement, stacking hazardous material
  quantities against a control area, filling an amenity to its capacity.
* Tier 5 -- finalisation and terminal states: an accepted project, an expiring
  lease, a surrendered lease.

Every helper takes the API client first, returns plain response data, and uses
``get_success_data`` so that a setup failure surfaces as a readable payload
rather than as a KeyError deep inside a test.
"""

from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import CLOCK_START, LAB_PREMIUM_PSF, lease_economics
from .test_users import (
    AHJ_HEADERS,
    CX_AGENT_HEADERS,
    ENGINEER_HEADERS,
    LANDLORD_HEADERS,
    LANDLORD_NEGOTIATOR_HEADERS,
    LANDLORD_SIGNER_HEADERS,
    USER_CX_TECH,
    USER_CX_WITNESS,
    make_tenant_headers,
)

_ISO = "%Y-%m-%dT%H:%M:%SZ"


# ---------------------------------------------------------------------------
# Instant helpers for the logical clock
# ---------------------------------------------------------------------------


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> str:
    """Build an ISO 8601 UTC instant of the form the API accepts."""
    return datetime(year, month, day, hour, minute).strftime(_ISO)


def shift(instant: str, days: int = 0, hours: int = 0, minutes: int = 0) -> str:
    """Move an instant by a signed offset, keeping the same textual format."""
    base = datetime.strptime(instant.replace(".000Z", "Z"), _ISO)
    return (base + timedelta(days=days, hours=hours, minutes=minutes)).strftime(_ISO)


def same_instant(left: str, right: str) -> bool:
    """Compare two timestamps that may differ only in fractional-second text."""

    def _norm(value: str) -> datetime:
        text = value.replace("Z", "")
        if "." in text:
            text = text.split(".")[0]
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S")

    return _norm(left) == _norm(right)


# A window comfortably inside the default delivery term.
DEFAULT_WINDOW_START = utc(2026, 9, 1, 8)
DEFAULT_WINDOW_END = utc(2026, 9, 5, 17)


def nth_window(index: int, days: int = 4) -> Tuple[str, str]:
    """A sequence of well-separated windows inside the default delivery term."""
    start = shift(utc(2026, 9, 1, 8), days=index * 20)
    return start, shift(start, days=days)


# ---------------------------------------------------------------------------
# Tier 1 -- single-resource creates and progressions
# ---------------------------------------------------------------------------


def set_clock(api, current_utc: str, headers: Optional[Dict] = None) -> str:
    """Move the logical clock and return the instant now in force."""
    data = get_success_data(
        api.set_clock(current_utc, headers or LANDLORD_HEADERS)
    )
    return data.get("current_utc", current_utc)


def reset_clock(api, headers: Optional[Dict] = None) -> str:
    """Return the logical clock to the instant it starts at."""
    return set_clock(api, CLOCK_START, headers)


def create_building(api, headers: Optional[Dict] = None, **overrides) -> Dict:
    return get_success_data(
        api.create_building(f.building_payload(**overrides), headers or LANDLORD_HEADERS)
    )


def create_floor(
    api, building_id: str, floor_number: int = 1, headers: Optional[Dict] = None, **overrides
) -> Dict:
    return get_success_data(
        api.create_floor(
            building_id,
            f.floor_payload(floor_number, **overrides),
            headers or ENGINEER_HEADERS,
        )
    )


def create_tenant(
    api, research_type: str = "BSL2_BIOLOGY", headers: Optional[Dict] = None, **overrides
) -> Dict:
    return get_success_data(
        api.create_tenant(
            f.tenant_payload(research_type, **overrides), headers or LANDLORD_HEADERS
        )
    )


def create_amenity(
    api,
    building_id: str,
    serving_floor_number: int = 1,
    headers: Optional[Dict] = None,
    **overrides,
) -> Dict:
    return get_success_data(
        api.create_amenity(
            building_id,
            f.amenity_payload(serving_floor_number, **overrides),
            headers or LANDLORD_HEADERS,
        )
    )


def get_building(api, building_id: str, headers: Optional[Dict] = None) -> Dict:
    return get_success_data(api.get_building(building_id, headers or LANDLORD_HEADERS))


def get_floor(api, floor_id: str, headers: Optional[Dict] = None) -> Dict:
    return get_success_data(api.get_floor(floor_id, headers or LANDLORD_HEADERS))


def get_lease(api, lease_id: str, headers: Optional[Dict] = None) -> Dict:
    return get_success_data(api.get_lease(lease_id, headers or LANDLORD_HEADERS))


def get_proposal(api, proposal_id: str, headers: Optional[Dict] = None) -> Dict:
    return get_success_data(api.get_proposal(proposal_id, headers or LANDLORD_HEADERS))


def get_project(api, project_id: str, headers: Optional[Dict] = None) -> Dict:
    return get_success_data(api.get_project(project_id, headers or LANDLORD_HEADERS))


def get_phase(api, phase_id: str, headers: Optional[Dict] = None) -> Dict:
    return get_success_data(api.get_phase(phase_id, headers or LANDLORD_HEADERS))


def get_reservation(api, reservation_id: str, headers: Optional[Dict] = None) -> Dict:
    return get_success_data(
        api.get_reservation(reservation_id, headers or LANDLORD_HEADERS)
    )


def get_permit(api, permit_id: str, headers: Optional[Dict] = None) -> Dict:
    return get_success_data(api.get_hazmat_permit(permit_id, headers or LANDLORD_HEADERS))


def get_allocation(api, allocation_id: str, headers: Optional[Dict] = None) -> Dict:
    return get_success_data(
        api.get_allocation(allocation_id, headers or LANDLORD_HEADERS)
    )


def get_assessment(api, assessment_id: str, headers: Optional[Dict] = None) -> Dict:
    return get_success_data(
        api.get_assessment(assessment_id, headers or LANDLORD_HEADERS)
    )


def get_record(api, record_id: str, headers: Optional[Dict] = None) -> Dict:
    return get_success_data(
        api.get_commissioning_record(record_id, headers or CX_AGENT_HEADERS)
    )


def get_utilization(
    api,
    floor_id: str,
    hazard_class: str = "FLAMMABLE_IB",
    control_area_index: Optional[int] = None,
    headers: Optional[Dict] = None,
) -> Dict:
    params: Dict = {"hazard_class": hazard_class}
    if control_area_index is not None:
        params["control_area_index"] = control_area_index
    return get_success_data(
        api.get_hazmat_utilization(floor_id, headers or LANDLORD_HEADERS, params)
    )


# ---------------------------------------------------------------------------
# Tier 2 -- entity hierarchy
# ---------------------------------------------------------------------------


def setup_building_with_floors(
    api,
    floor_numbers: Sequence[int] = (1,),
    building_overrides: Optional[Dict] = None,
    floor_overrides: Optional[Dict[int, Dict]] = None,
) -> Dict:
    """A registered building plus one plate per requested floor number.

    Returns ``{"building": ..., "floors": {floor_number: floor}}``.
    """
    building = create_building(api, **(building_overrides or {}))
    floors: Dict[int, Dict] = {}
    for number in floor_numbers:
        overrides = (floor_overrides or {}).get(number, {})
        floors[number] = create_floor(api, building["id"], number, **overrides)
    return {"building": get_building(api, building["id"]), "floors": floors}


def open_assessment(
    api, building_id: str, headers: Optional[Dict] = None, **overrides
) -> Dict:
    return get_success_data(
        api.create_assessment(
            building_id, f.assessment_payload(**overrides), headers or ENGINEER_HEADERS
        )
    )


def submit_assessment(api, assessment_id: str, headers: Optional[Dict] = None) -> Dict:
    return get_success_data(
        api.submit_assessment(assessment_id, headers or ENGINEER_HEADERS)
    )


def decide_assessment(
    api,
    assessment_id: str,
    decision: str = "ACCEPT",
    return_note: Optional[str] = None,
    headers: Optional[Dict] = None,
) -> Dict:
    payload = f.assessment_decision_payload(decision)
    if return_note is not None:
        payload["return_note"] = return_note
    return get_success_data(
        api.decide_assessment(assessment_id, payload, headers or LANDLORD_HEADERS)
    )


def add_scope_item(
    api,
    building_id: str,
    discipline: str = "LAB_EXHAUST",
    headers: Optional[Dict] = None,
    **overrides,
) -> Dict:
    return get_success_data(
        api.create_scope_item(
            building_id,
            f.scope_item_payload(discipline, **overrides),
            headers or LANDLORD_HEADERS,
        )
    )


def complete_scope_item(api, item_id: str, headers: Optional[Dict] = None) -> Dict:
    return get_success_data(
        api.complete_scope_item(item_id, headers or ENGINEER_HEADERS)
    )


def approve_conversion(api, building_id: str, headers: Optional[Dict] = None) -> Dict:
    return get_success_data(
        api.approve_conversion(building_id, headers or LANDLORD_HEADERS)
    )


def create_lease(
    api,
    tenant_id: str,
    building_id: str,
    premises_floor_id: str,
    rentable_sf: int = 20000,
    headers: Optional[Dict] = None,
    **overrides,
) -> Dict:
    return get_success_data(
        api.create_lease(
            f.lease_payload(
                tenant_id, building_id, premises_floor_id, rentable_sf, **overrides
            ),
            headers or LANDLORD_HEADERS,
        )
    )


def create_project(
    api, lease_id: str, floor_id: str, headers: Optional[Dict] = None, **overrides
) -> Dict:
    return get_success_data(
        api.create_project(
            f.project_payload(lease_id, floor_id, **overrides), headers or LANDLORD_HEADERS
        )
    )


def create_phase(
    api,
    project_id: str,
    sequence_no: int = 1,
    premium_class: str = "LAB_MEP",
    work_class: str = "QUIET",
    hard_cost_usd: float = 100000.00,
    headers: Optional[Dict] = None,
    **overrides,
) -> Dict:
    return get_success_data(
        api.create_phase(
            project_id,
            f.phase_payload(
                sequence_no, premium_class, work_class, hard_cost_usd, **overrides
            ),
            headers or LANDLORD_HEADERS,
        )
    )


# ---------------------------------------------------------------------------
# Tier 3 -- lifecycle shortcuts
# ---------------------------------------------------------------------------


def setup_assessed_building(
    api,
    floor_numbers: Sequence[int] = (1,),
    building_overrides: Optional[Dict] = None,
    floor_overrides: Optional[Dict[int, Dict]] = None,
    assessment_overrides: Optional[Dict] = None,
    decision: str = "ACCEPT",
) -> Dict:
    """A building carried through open, submit and decide in one call.

    Returns ``{"building", "floors", "assessment"}`` with the building re-read
    after the decision so that its `suitability_state`, verdict and `version`
    are the post-decision values.
    """
    bundle = setup_building_with_floors(
        api, floor_numbers, building_overrides, floor_overrides
    )
    assessment = open_assessment(
        api, bundle["building"]["id"], **(assessment_overrides or {})
    )
    submit_assessment(api, assessment["id"])
    assessment = decide_assessment(api, assessment["id"], decision)
    bundle["assessment"] = assessment
    bundle["building"] = get_building(api, bundle["building"]["id"])
    return bundle


def setup_conversion_approved_building(
    api,
    floor_numbers: Sequence[int] = (1, 2),
    building_overrides: Optional[Dict] = None,
    floor_overrides: Optional[Dict[int, Dict]] = None,
    assessment_overrides: Optional[Dict] = None,
    exhaust_delta_cfm: float = 20000,
    power_delta_kw: float = 400,
    declare_disciplines: Sequence[str] = ("LAB_EXHAUST",),
    complete_disciplines: Sequence[str] = (),
) -> Dict:
    """A building at `CONVERSION_APPROVED`, optionally with scope items complete.

    ``declare_disciplines`` are recorded as scope items before approval;
    ``complete_disciplines`` are closed out afterwards, folding their declared
    deltas into the pools. Returns the assessed-building bundle plus
    ``{"scope_items": {discipline: item}}``.
    """
    bundle = setup_assessed_building(
        api, floor_numbers, building_overrides, floor_overrides, assessment_overrides
    )
    building_id = bundle["building"]["id"]
    scope_items: Dict[str, Dict] = {}
    for discipline in declare_disciplines:
        deltas: Dict = {}
        if discipline == "LAB_EXHAUST":
            deltas["capacity_delta_cfm"] = exhaust_delta_cfm
        if discipline == "EMERGENCY_POWER":
            deltas["capacity_delta_kw"] = power_delta_kw
        scope_items[discipline] = add_scope_item(api, building_id, discipline, **deltas)
    approve_conversion(api, building_id)
    for discipline in complete_disciplines:
        scope_items[discipline] = complete_scope_item(
            api, scope_items[discipline]["id"]
        )
    bundle["scope_items"] = scope_items
    bundle["building"] = get_building(api, building_id)
    return bundle


def setup_conversion_complete_building(
    api,
    floor_numbers: Sequence[int] = (1, 2),
    exhaust_delta_cfm: float = 20000,
    power_delta_kw: float = 400,
    **kwargs,
) -> Dict:
    """A building carried all the way to the terminal `CONVERSION_COMPLETE`."""
    all_four = (
        "LAB_EXHAUST",
        "EMERGENCY_POWER",
        "CHEMICAL_STORAGE",
        "WASTE_HANDLING",
    )
    return setup_conversion_approved_building(
        api,
        floor_numbers,
        exhaust_delta_cfm=exhaust_delta_cfm,
        power_delta_kw=power_delta_kw,
        declare_disciplines=all_four,
        complete_disciplines=all_four,
        **kwargs,
    )


def setup_lease_at_loi(
    api,
    research_type: str = "BSL2_BIOLOGY",
    premises_floor_number: int = 2,
    rentable_sf: int = 20000,
    floor_numbers: Sequence[int] = (1, 2),
    lease_overrides: Optional[Dict] = None,
    **building_kwargs,
) -> Dict:
    """A conversion-approved building plus a tenant and a lease at `LOI`.

    Returns the building bundle plus ``{"tenant", "tenant_headers", "lease",
    "premises_floor"}``.
    """
    bundle = setup_conversion_approved_building(
        api, floor_numbers=floor_numbers, **building_kwargs
    )
    tenant = create_tenant(api, research_type)
    premises_floor = bundle["floors"][premises_floor_number]
    lease = create_lease(
        api,
        tenant["id"],
        bundle["building"]["id"],
        premises_floor["id"],
        rentable_sf,
        **(lease_overrides or {}),
    )
    bundle.update(
        {
            "tenant": tenant,
            "tenant_headers": make_tenant_headers(tenant["id"]),
            "lease": lease,
            "premises_floor": premises_floor,
            "premises_floor_number": premises_floor_number,
        }
    )
    return bundle


def accept_terms(
    api,
    lease: Dict,
    tenant_id: str,
    allowance_psf: float,
    author_headers: Optional[Dict] = None,
) -> Dict:
    """One landlord round accepted by the tenant, authorising the allowance.

    The author is a distinct asset-management operator from the signer so that
    execution is not barred by separation of duties.
    """
    proposal = get_success_data(
        api.create_proposal(
            lease["id"],
            f.proposal_payload(lease["version"], allowance_psf),
            author_headers or LANDLORD_NEGOTIATOR_HEADERS,
        )
    )
    get_success_data(api.accept_proposal(proposal["id"], make_tenant_headers(tenant_id)))
    # The acceptance touches both the proposal and the lease, so each is read back
    # from its own single-resource endpoint rather than out of the accept body.
    return {
        "proposal": get_proposal(api, proposal["id"]),
        "lease": get_lease(api, lease["id"]),
    }


def setup_lease_at_terms_accepted(
    api, allowance_psf: float = 200.00, **kwargs
) -> Dict:
    """A lease at `TERMS_ACCEPTED` with its ledger opened."""
    bundle = setup_lease_at_loi(api, **kwargs)
    accepted = accept_terms(
        api, bundle["lease"], bundle["tenant"]["id"], allowance_psf
    )
    bundle["proposal"] = accepted["proposal"]
    bundle["lease"] = accepted["lease"]
    bundle["accepted_allowance_psf"] = allowance_psf
    return bundle


def fund_escrow_exactly(api, lease_id: str, headers: Optional[Dict] = None) -> Dict:
    """Deposit exactly the lease's `restoration_escrow_required_usd`."""
    lease = get_lease(api, lease_id)
    required = lease["restoration_escrow_required_usd"]
    return get_success_data(
        api.create_escrow_deposit(
            lease_id, f.escrow_deposit_payload(required), headers or LANDLORD_HEADERS
        )
    )


def execute_lease(api, lease_id: str, headers: Optional[Dict] = None) -> Dict:
    return get_success_data(
        api.execute_lease(lease_id, headers or LANDLORD_SIGNER_HEADERS)
    )


def setup_executed_lease(api, allowance_psf: float = 200.00, **kwargs) -> Dict:
    """A lease at `EXECUTED`: terms accepted, escrow funded to the requirement."""
    bundle = setup_lease_at_terms_accepted(api, allowance_psf=allowance_psf, **kwargs)
    fund_escrow_exactly(api, bundle["lease"]["id"])
    bundle["lease"] = execute_lease(api, bundle["lease"]["id"])
    return bundle


def apply_and_issue_permit(api, project_id: str) -> Dict:
    """Carry a project's permit dimension from `P_UNPERMITTED` to `P_ISSUED`."""
    get_success_data(api.apply_for_permit(project_id, LANDLORD_HEADERS))
    return get_success_data(
        api.decide_permit(project_id, f.permit_decision_payload("ISSUE"), AHJ_HEADERS)
    )


def setup_permitted_project(
    api,
    allowance_psf: float = 200.00,
    project_overrides: Optional[Dict] = None,
    complete_disciplines: Sequence[str] = ("LAB_EXHAUST",),
    **kwargs,
) -> Dict:
    """An executed lease with a project at `P_ISSUED`.

    The lab exhaust scope item is completed by default because a laboratory
    permit application is refused while the riser is still being built.
    """
    bundle = setup_executed_lease(
        api,
        allowance_psf=allowance_psf,
        complete_disciplines=complete_disciplines,
        **kwargs,
    )
    project = create_project(
        api,
        bundle["lease"]["id"],
        bundle["premises_floor"]["id"],
        **(project_overrides or {}),
    )
    bundle["project"] = apply_and_issue_permit(api, project["id"])
    bundle["building"] = get_building(api, bundle["building"]["id"])
    return bundle


def schedule_phase(
    api,
    phase_id: str,
    window_start: str = DEFAULT_WINDOW_START,
    window_end: str = DEFAULT_WINDOW_END,
    headers: Optional[Dict] = None,
) -> Dict:
    return get_success_data(
        api.schedule_phase(
            phase_id,
            f.schedule_payload(window_start, window_end),
            headers or LANDLORD_HEADERS,
        )
    )


def progress_phase(
    api, phase_id: str, target_status: str, headers: Optional[Dict] = None
) -> Dict:
    return get_success_data(
        api.progress_phase(
            phase_id, f.progress_payload(target_status), headers or LANDLORD_HEADERS
        )
    )


def start_phase(
    api,
    phase_id: str,
    window_start: str = DEFAULT_WINDOW_START,
    window_end: str = DEFAULT_WINDOW_END,
) -> Dict:
    """Schedule a package and carry it to `IN_PROGRESS`."""
    schedule_phase(api, phase_id, window_start, window_end)
    return progress_phase(api, phase_id, "IN_PROGRESS")


def complete_phase(
    api,
    phase_id: str,
    window_start: str = DEFAULT_WINDOW_START,
    window_end: str = DEFAULT_WINDOW_END,
) -> Dict:
    """Schedule, start and complete a package, committing its eligible allowance."""
    start_phase(api, phase_id, window_start, window_end)
    return progress_phase(api, phase_id, "COMPLETE")


def hold_phase(
    api, phase_id: str, hold_reason: str = "Plate exceeded VC_C during coring"
) -> Dict:
    return get_success_data(
        api.hold_phase(phase_id, f.hold_payload(hold_reason), ENGINEER_HEADERS)
    )


def declare_substantial_completion(api, project_id: str) -> Dict:
    return get_success_data(
        api.declare_milestone(project_id, f.milestone_payload(), LANDLORD_HEADERS)
    )


# ---------------------------------------------------------------------------
# Tier 4 -- accumulation and threshold targeting
# ---------------------------------------------------------------------------


def setup_project_with_phases(
    api,
    phase_specs: Sequence[Dict],
    allowance_psf: float = 200.00,
    **kwargs,
) -> Dict:
    """A permitted project carrying the requested phase packages in `DRAFT`.

    Each spec is passed straight to the phase factory, so a spec may name
    ``sequence_no``, ``premium_class``, ``work_class``, ``hard_cost_usd``,
    ``restoration_cost_usd``, ``predecessor_phase_id`` or ``affected_amenity_id``.
    Specs may also carry ``predecessor_index`` to chain onto an earlier spec in
    the same list.
    """
    bundle = setup_permitted_project(api, allowance_psf=allowance_psf, **kwargs)
    phases: List[Dict] = []
    for index, spec in enumerate(phase_specs):
        spec = dict(spec)
        predecessor_index = spec.pop("predecessor_index", None)
        if predecessor_index is not None:
            spec["predecessor_phase_id"] = phases[predecessor_index]["id"]
        spec.setdefault("sequence_no", index + 1)
        phases.append(create_phase(api, bundle["project"]["id"], **spec))
    bundle["phases"] = phases
    bundle["project"] = get_project(api, bundle["project"]["id"])
    return bundle


def setup_lease_with_committed_phases(
    api,
    phase_specs: Sequence[Dict],
    allowance_psf: float = 200.00,
    complete_order: Optional[Sequence[int]] = None,
    **kwargs,
) -> Dict:
    """A permitted project whose phase packages have reached `COMPLETE`.

    ``complete_order`` names the chronological order in which packages reach
    completion, which is the order the allowance bucket is consumed in --
    deliberately not `sequence_no` order.
    """
    bundle = setup_project_with_phases(
        api, phase_specs, allowance_psf=allowance_psf, **kwargs
    )
    order = list(complete_order) if complete_order is not None else range(
        len(bundle["phases"])
    )
    for position, phase_index in enumerate(order):
        start, end = nth_window(position)
        complete_phase(api, bundle["phases"][phase_index]["id"], start, end)
    bundle["phases"] = [get_phase(api, p["id"]) for p in bundle["phases"]]
    bundle["lease"] = get_lease(api, bundle["lease"]["id"])
    bundle["project"] = get_project(api, bundle["project"]["id"])
    return bundle


def create_reservation(
    api,
    project_id: str,
    expected_building_version: int,
    exhaust_cfm: float = 12000,
    power_kw: float = 180,
    headers: Optional[Dict] = None,
) -> Dict:
    return get_success_data(
        api.create_reservation(
            f.reservation_payload(
                project_id, expected_building_version, exhaust_cfm, power_kw
            ),
            headers or LANDLORD_HEADERS,
        )
    )


def reserve_capacity(
    api,
    project_id: str,
    building_id: str,
    exhaust_cfm: float = 12000,
    power_kw: float = 180,
) -> Dict:
    """Reserve capacity against the building's current `version`."""
    building = get_building(api, building_id)
    return create_reservation(
        api, project_id, building["version"], exhaust_cfm, power_kw
    )


def file_hazmat_permit(
    api,
    project_id: str,
    floor_id: str,
    hazard_class: str = "FLAMMABLE_IB",
    use_condition: str = "CLOSED_SYSTEM_USE",
    quantity_gal: float = 100.00,
    control_area_index: int = 1,
    headers: Optional[Dict] = None,
) -> Dict:
    return get_success_data(
        api.create_hazmat_permit(
            f.hazmat_permit_payload(
                project_id,
                floor_id,
                hazard_class,
                use_condition,
                quantity_gal,
                control_area_index,
            ),
            headers or LANDLORD_HEADERS,
        )
    )


def decide_hazmat_permit(
    api, permit_id: str, decision: str = "APPROVE", decision_reason: Optional[str] = None
) -> Dict:
    payload = f.hazmat_decision_payload(decision)
    if decision_reason is not None:
        payload["decision_reason"] = decision_reason
    return get_success_data(api.decide_hazmat_permit(permit_id, payload, AHJ_HEADERS))


def approve_hazmat_permit(api, permit_id: str) -> Dict:
    """File-and-approve shortcut for a permit that must sit in `APPROVED`."""
    return decide_hazmat_permit(api, permit_id, "APPROVE")


def book_allocation(
    api,
    amenity_id: str,
    project_id: str,
    window_start: str,
    window_end: str,
    headcount: int = 2,
    headers: Optional[Dict] = None,
) -> Dict:
    return get_success_data(
        api.create_allocation(
            f.allocation_payload(
                amenity_id, project_id, window_start, window_end, headcount
            ),
            headers or LANDLORD_HEADERS,
        )
    )


def confirm_allocation(api, allocation_id: str, headers: Optional[Dict] = None) -> Dict:
    return get_success_data(
        api.confirm_allocation(allocation_id, headers or LANDLORD_HEADERS)
    )


def book_and_confirm_allocation(
    api,
    amenity_id: str,
    project_id: str,
    window_start: str,
    window_end: str,
    headcount: int = 2,
) -> Dict:
    allocation = book_allocation(
        api, amenity_id, project_id, window_start, window_end, headcount
    )
    return confirm_allocation(api, allocation["id"])


def draw_allowance(api, lease_id: str, requested_usd: float) -> Dict:
    return get_success_data(
        api.create_disbursement(
            lease_id, f.disbursement_payload(requested_usd), LANDLORD_HEADERS
        )
    )


# ---------------------------------------------------------------------------
# Tier 5 -- finalisation and terminal states
# ---------------------------------------------------------------------------


def schedule_script(
    api,
    project_id: str,
    script_type: str,
    executed_by_user_id: str = USER_CX_TECH,
    scheduled_for: str = "2026-11-01T09:00:00Z",
    headers: Optional[Dict] = None,
) -> Dict:
    return get_success_data(
        api.create_commissioning_record(
            project_id,
            f.commissioning_record_payload(
                script_type, executed_by_user_id, scheduled_for
            ),
            headers or CX_AGENT_HEADERS,
        )
    )


def record_result(
    api,
    record_id: str,
    result: str = "PASS",
    witnessed_by_user_id: str = USER_CX_WITNESS,
    measured_value: Optional[float] = None,
    headers: Optional[Dict] = None,
) -> Dict:
    payload = f.commissioning_result_payload(result, witnessed_by_user_id)
    if measured_value is not None:
        payload["measured_value"] = measured_value
    return get_success_data(
        api.record_commissioning_result(record_id, payload, headers or CX_AGENT_HEADERS)
    )


def setup_project_at_substantial_completion(
    api,
    phase_specs: Optional[Sequence[Dict]] = None,
    allowance_psf: float = 200.00,
    **kwargs,
) -> Dict:
    """A project at `C_SUBSTANTIAL_COMPLETION` with one completed package.

    Scripts are run against finished work, so this is the state every
    commissioning result depends on.
    """
    specs = phase_specs or [
        {"premium_class": "LAB_MEP", "work_class": "QUIET", "hard_cost_usd": 100000.00}
    ]
    bundle = setup_lease_with_committed_phases(
        api, specs, allowance_psf=allowance_psf, **kwargs
    )
    bundle["project"] = declare_substantial_completion(api, bundle["project"]["id"])
    return bundle


def pass_all_scripts(api, project_id: str, research_type: str) -> List[Dict]:
    """Schedule and pass every script the research programme requires."""
    from .constants import REQUIRED_COMMISSIONING_SCRIPTS

    records: List[Dict] = []
    for script_type in REQUIRED_COMMISSIONING_SCRIPTS[research_type]:
        record = schedule_script(api, project_id, script_type)
        records.append(record_result(api, record["id"], "PASS"))
    return records


def setup_accepted_project(
    api,
    research_type: str = "ANALYTICAL_QC",
    reserve: bool = True,
    exhaust_cfm: float = 12000,
    power_kw: float = 180,
    **kwargs,
) -> Dict:
    """A project at `C_ACCEPTED` with the lease carried to `ACTIVE`.

    A capacity reservation is taken beforehand by default so that the four-hop
    acceptance cascade has a reservation to commit.
    """
    bundle = setup_project_at_substantial_completion(
        api, research_type=research_type, **kwargs
    )
    if reserve:
        bundle["reservation"] = reserve_capacity(
            api,
            bundle["project"]["id"],
            bundle["building"]["id"],
            exhaust_cfm,
            power_kw,
        )
    bundle["records"] = pass_all_scripts(
        api, bundle["project"]["id"], research_type
    )
    bundle["project"] = get_project(api, bundle["project"]["id"])
    bundle["lease"] = get_lease(api, bundle["lease"]["id"])
    bundle["building"] = get_building(api, bundle["building"]["id"])
    if reserve:
        bundle["reservation"] = get_reservation(api, bundle["reservation"]["id"])
    return bundle


def issue_expiration_notice(
    api, lease_id: str, expiration_date: str = "2027-06-30T00:00:00Z"
) -> Dict:
    return get_success_data(
        api.issue_expiration_notice(
            lease_id, f.expiration_notice_payload(expiration_date), LANDLORD_HEADERS
        )
    )


def setup_expiring_lease(
    api, expiration_date: str = "2027-06-30T00:00:00Z", **kwargs
) -> Dict:
    """An accepted project whose lease has been carried `ACTIVE -> EXPIRING`."""
    bundle = setup_accepted_project(api, **kwargs)
    bundle["lease"] = issue_expiration_notice(
        api, bundle["lease"]["id"], expiration_date
    )
    return bundle


def settle_restoration(api, lease_id: str) -> Dict:
    return get_success_data(api.settle_restoration(lease_id, LANDLORD_HEADERS))


def setup_surrendered_lease(api, **kwargs) -> Dict:
    """A lease carried to the terminal `SURRENDERED` through settlement."""
    bundle = setup_expiring_lease(api, **kwargs)
    bundle["lease"] = settle_restoration(api, bundle["lease"]["id"])
    bundle["building"] = get_building(api, bundle["building"]["id"])
    return bundle


# ---------------------------------------------------------------------------
# Cross-tenant and two-project arrangements
# ---------------------------------------------------------------------------


def add_second_tenant_project(
    api,
    bundle: Dict,
    research_type: str = "CHEMISTRY_SYNTHESIS",
    rentable_sf: int = 2000,
    allowance_psf: float = 70.00,
    premises_floor_number: Optional[int] = None,
) -> Dict:
    """Put a second tenant's permitted project on a plate of the same building.

    The floor-wide hazardous material limit is shared across every tenant on the
    plate, so several rules can only be reached with two tenants in place.
    Returns ``{"tenant", "tenant_headers", "lease", "project"}``.
    """
    floor_number = premises_floor_number or bundle["premises_floor_number"]
    floor = bundle["floors"][floor_number]
    tenant = create_tenant(api, research_type, legal_name="Second Tenant Labs LLC")
    lease = create_lease(
        api, tenant["id"], bundle["building"]["id"], floor["id"], rentable_sf
    )
    accept_terms(api, lease, tenant["id"], allowance_psf)
    fund_escrow_exactly(api, lease["id"])
    lease = execute_lease(api, lease["id"])
    project = create_project(api, lease["id"], floor["id"])
    project = apply_and_issue_permit(api, project["id"])
    return {
        "tenant": tenant,
        "tenant_headers": make_tenant_headers(tenant["id"]),
        "lease": lease,
        "project": project,
        "floor": floor,
    }


def expected_authorization(
    research_type: str,
    accepted_allowance_psf: float,
    premises_floor_number: int,
    rentable_sf: int,
) -> Dict[str, float]:
    """The seven ordered economics steps for a prospective deal."""
    return lease_economics(
        accepted_allowance_psf,
        LAB_PREMIUM_PSF[research_type],
        premises_floor_number,
        rentable_sf,
    )


def ids(rows: Iterable[Dict]) -> List[str]:
    """The `id` of every row in a listing, in the order the listing returned them."""
    return [row["id"] for row in rows]
