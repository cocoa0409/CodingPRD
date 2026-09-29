"""Composite setup helpers.

Every helper builds its state from scratch through PRD-declared endpoints only,
because each test starts against an empty database.  Ownership-gated calls are
always issued with the per-instance header builders: a floor is measured by the
dispatcher of the plant that built it, a leg departs under the carrier that
owns it, and a set job's scope is recorded by that job's own crew lead.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_STARTUP_UTC
from .factories import (
    adjudicate_damage_claim_payload,
    create_anchor_certification_payload,
    create_damage_claim_payload,
    create_escort_assignment_payload,
    create_escort_crew_payload,
    create_hauler_payload,
    create_marriage_joint_payload,
    create_order_payload,
    create_permit_payload,
    create_plant_payload,
    create_route_leg_payload,
    create_section_payload,
    create_set_crew_payload,
    create_set_job_payload,
    create_site_payload,
    readiness_inspection_payload,
    resubmit_anchor_certification_payload,
    review_anchor_certification_payload,
    review_damage_claim_payload,
    reverse_damage_claim_payload,
    scope_split_payload,
    utility_crossover_payload,
)
from .test_users import (
    ANCHOR_INSPECTOR_USER_ID,
    SITE_INSPECTOR_USER_ID,
    TEST_USERS,
    make_claims_adjuster_headers,
    make_inspector_headers,
    make_network_admin_headers,
    make_permit_desk_headers,
    make_plant_dispatcher_headers,
    make_set_crew_lead_headers,
    make_transport_manager_headers,
)

ADMIN = TEST_USERS["network_admin_headers"]
PERMIT_DESK = TEST_USERS["permit_desk_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]


# ---------------------------------------------------------------------------
# The logical clock
# ---------------------------------------------------------------------------


def set_logical_clock(current_utc=CLOCK_STARTUP_UTC):
    """Move the server's logical current UTC instant."""
    return get_success_data(
        api_client.set_clock({"current_utc": current_utc}, ADMIN)
    )


# ---------------------------------------------------------------------------
# Tier 1 — single-row registrations
# ---------------------------------------------------------------------------


def register_plant(**overrides):
    return get_success_data(
        api_client.create_plant(create_plant_payload(**overrides), ADMIN)
    )


def register_hauler(**overrides):
    return get_success_data(
        api_client.create_hauler(create_hauler_payload(**overrides), ADMIN)
    )


def register_escort_crew(**overrides):
    return get_success_data(
        api_client.create_escort_crew(create_escort_crew_payload(**overrides), ADMIN)
    )


def register_set_crew(**overrides):
    return get_success_data(
        api_client.create_set_crew(create_set_crew_payload(**overrides), ADMIN)
    )


def open_order(plant_id, **overrides):
    return get_success_data(
        api_client.create_order(create_order_payload(plant_id, **overrides), ADMIN)
    )


def register_site(order_id, **overrides):
    return get_success_data(
        api_client.create_site(create_site_payload(order_id, **overrides), ADMIN)
    )


# ---------------------------------------------------------------------------
# Reading live versions (the two anchored writes need the parent's version)
# ---------------------------------------------------------------------------


def current_order_version(order_id):
    return get_success_data(api_client.get_order(order_id, ADMIN))["version"]


def current_section_version(section_id):
    return get_success_data(api_client.get_section(section_id, ADMIN))["version"]


def read_order(order_id):
    return get_success_data(api_client.get_order(order_id, ADMIN))


def read_section(section_id):
    return get_success_data(api_client.get_section(section_id, ADMIN))


def read_site(site_id):
    return get_success_data(api_client.get_site(site_id, ADMIN))


def read_permit(permit_id):
    return get_success_data(api_client.get_permit(permit_id, ADMIN))


def read_route_leg(leg_id):
    return get_success_data(api_client.get_route_leg(leg_id, ADMIN))


def read_escort_crew(crew_id):
    return get_success_data(api_client.get_escort_crew(crew_id, ADMIN))


def read_escort_assignment(assignment_id):
    return get_success_data(api_client.get_escort_assignment(assignment_id, ADMIN))


def read_set_job(job_id):
    return get_success_data(api_client.get_set_job(job_id, ADMIN))


def read_set_crew(crew_id):
    return get_success_data(api_client.get_set_crew(crew_id, ADMIN))


def read_plant(plant_id):
    return get_success_data(api_client.get_plant(plant_id, ADMIN))


def read_hauler(hauler_id):
    return get_success_data(api_client.get_hauler(hauler_id, ADMIN))


def read_anchor_certification(cert_id):
    return get_success_data(api_client.get_anchor_certification(cert_id, ADMIN))


def read_damage_claim(claim_id):
    return get_success_data(api_client.get_damage_claim(claim_id, ADMIN))


def read_order_summary(order_id):
    return get_success_data(api_client.get_order_summary(order_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1 — floors
# ---------------------------------------------------------------------------


def record_section(order_id, plant_id, **overrides):
    """Record one floor as the dispatcher of the plant that builds it."""
    return get_success_data(
        api_client.create_section(
            create_section_payload(order_id, **overrides),
            make_plant_dispatcher_headers(plant_id),
        )
    )


def measure_section(section_id, plant_id, measured_width_in, measured_height_in):
    return get_success_data(
        api_client.measure_section(
            section_id,
            {
                "measured_width_in": measured_width_in,
                "measured_height_in": measured_height_in,
            },
            make_plant_dispatcher_headers(plant_id),
        )
    )


def release_section(section_id, plant_id):
    return get_success_data(
        api_client.release_section(
            section_id, {}, make_plant_dispatcher_headers(plant_id)
        )
    )


def measure_and_release_section(
    section_id, plant_id, measured_width_in=None, measured_height_in=None
):
    """Walk a floor AT_PLANT -> MEASURED -> PERMIT_PENDING.

    When the measured figures are omitted they mirror the declared ones, so the
    final permit evaluation lands on the same numbers as the provisional one.
    """
    section = read_section(section_id)
    width = (
        measured_width_in
        if measured_width_in is not None
        else section["declared_width_in"]
    )
    height = (
        measured_height_in
        if measured_height_in is not None
        else section["declared_height_in"]
    )
    measure_section(section_id, plant_id, width, height)
    return release_section(section_id, plant_id)


# ---------------------------------------------------------------------------
# Tier 1 — permits, legs and escort reservations
# ---------------------------------------------------------------------------


def request_permit(
    section_id, state_code="AZ", planned_leg_count=1, expected_section_version=None, **overrides
):
    version = (
        expected_section_version
        if expected_section_version is not None
        else current_section_version(section_id)
    )
    payload = create_permit_payload(
        section_id,
        version,
        state_code=state_code,
        planned_leg_count=planned_leg_count,
        **overrides,
    )
    return get_success_data(api_client.create_permit(payload, PERMIT_DESK))


def add_route_leg(permit_id, hauler_id, **overrides):
    return get_success_data(
        api_client.create_route_leg(
            create_route_leg_payload(permit_id, hauler_id, **overrides), PERMIT_DESK
        )
    )


def pay_permit_fee(permit_id, hauler_id, amount_cents):
    return get_success_data(
        api_client.pay_permit_fee(
            permit_id,
            {"amount_cents": amount_cents},
            make_transport_manager_headers(hauler_id),
        )
    )


def issue_permit(permit_id):
    return get_success_data(api_client.issue_permit(permit_id, {}, PERMIT_DESK))


def pay_and_issue_permit(permit_id, hauler_id, amount_cents=None):
    """Remit enough to cover the fee, then issue the permit."""
    permit = read_permit(permit_id)
    remittance = (
        amount_cents if amount_cents is not None else permit["provisional_fee_cents"]
    )
    pay_permit_fee(permit_id, hauler_id, remittance)
    return issue_permit(permit_id)


def revoke_permit(permit_id, reason_code="BRIDGE_POSTING"):
    return get_success_data(
        api_client.revoke_permit(permit_id, {"reason_code": reason_code}, PERMIT_DESK)
    )


def reserve_escort(route_leg_id, escort_crew_id, hauler_id, **overrides):
    return get_success_data(
        api_client.create_escort_assignment(
            create_escort_assignment_payload(route_leg_id, escort_crew_id, **overrides),
            make_transport_manager_headers(hauler_id),
        )
    )


def release_escort(assignment_id, hauler_id):
    return get_success_data(
        api_client.release_escort_assignment(
            assignment_id, {}, make_transport_manager_headers(hauler_id)
        )
    )


def depart_leg(leg_id, hauler_id):
    return get_success_data(
        api_client.depart_route_leg(
            leg_id, {}, make_transport_manager_headers(hauler_id)
        )
    )


def arrive_leg(leg_id, hauler_id):
    return get_success_data(
        api_client.arrive_route_leg(
            leg_id, {}, make_transport_manager_headers(hauler_id)
        )
    )


# ---------------------------------------------------------------------------
# Tier 1 — sites, set jobs, joints, anchoring, claims
# ---------------------------------------------------------------------------


def inspect_site(
    site_id,
    pad_pass=True,
    pier_plan_pass=True,
    utility_pass=True,
    inspector_user_id=SITE_INSPECTOR_USER_ID,
):
    return get_success_data(
        api_client.inspect_site_readiness(
            site_id,
            readiness_inspection_payload(
                pad_pass=pad_pass,
                pier_plan_pass=pier_plan_pass,
                utility_pass=utility_pass,
            ),
            make_inspector_headers(inspector_user_id),
        )
    )


def book_set_job(order_id, set_crew_id, expected_order_version=None, **overrides):
    version = (
        expected_order_version
        if expected_order_version is not None
        else current_order_version(order_id)
    )
    return get_success_data(
        api_client.create_set_job(
            create_set_job_payload(order_id, set_crew_id, version, **overrides), ADMIN
        )
    )


def dispatch_set_job(job_id):
    return get_success_data(api_client.dispatch_set_job(job_id, {}, ADMIN))


def record_marriage_joint(set_job_id, set_crew_id, joint_index=1, **overrides):
    return get_success_data(
        api_client.create_marriage_joint(
            create_marriage_joint_payload(set_job_id, joint_index, **overrides),
            make_set_crew_lead_headers(set_crew_id),
        )
    )


def close_marriage_line(job_id, set_crew_id):
    return get_success_data(
        api_client.close_marriage_line(job_id, {}, make_set_crew_lead_headers(set_crew_id))
    )


def record_scope_split(job_id, set_crew_id, **overrides):
    return get_success_data(
        api_client.record_scope_split(
            job_id,
            scope_split_payload(**overrides),
            make_set_crew_lead_headers(set_crew_id),
        )
    )


def record_utility_crossover(job_id, set_crew_id, crossover_count=1):
    return get_success_data(
        api_client.record_utility_crossover(
            job_id,
            utility_crossover_payload(crossover_count),
            make_set_crew_lead_headers(set_crew_id),
        )
    )


def submit_anchor_certification(set_job_id, set_crew_id, **overrides):
    return get_success_data(
        api_client.create_anchor_certification(
            create_anchor_certification_payload(set_job_id, **overrides),
            make_set_crew_lead_headers(set_crew_id),
        )
    )


def review_anchor_certification(
    cert_id, decision="CERTIFY", inspector_user_id=ANCHOR_INSPECTOR_USER_ID, **overrides
):
    return get_success_data(
        api_client.review_anchor_certification(
            cert_id,
            review_anchor_certification_payload(decision, **overrides),
            make_inspector_headers(inspector_user_id),
        )
    )


def resubmit_anchor_certification(cert_id, set_crew_id, **overrides):
    return get_success_data(
        api_client.resubmit_anchor_certification(
            cert_id,
            resubmit_anchor_certification_payload(**overrides),
            make_set_crew_lead_headers(set_crew_id),
        )
    )


def open_damage_claim(order_id, section_id, hauler_id, set_crew_id, headers=None, **overrides):
    return get_success_data(
        api_client.create_damage_claim(
            create_damage_claim_payload(
                order_id, section_id, hauler_id, set_crew_id, **overrides
            ),
            headers or ADJUSTER,
        )
    )


def review_damage_claim(claim_id, **overrides):
    return get_success_data(
        api_client.review_damage_claim(
            claim_id, review_damage_claim_payload(**overrides), ADJUSTER
        )
    )


def adjudicate_damage_claim(claim_id, allocation_basis="STAGE"):
    return get_success_data(
        api_client.adjudicate_damage_claim(
            claim_id, adjudicate_damage_claim_payload(allocation_basis), ADJUSTER
        )
    )


def reverse_damage_claim(claim_id, reason_code="NEW_EVIDENCE"):
    return get_success_data(
        api_client.reverse_damage_claim(
            claim_id, reverse_damage_claim_payload(reason_code=reason_code), ADJUSTER
        )
    )


# ---------------------------------------------------------------------------
# Tier 2 — the trading-partner network
# ---------------------------------------------------------------------------


def setup_network(
    plant_overrides=None,
    hauler_overrides=None,
    escort_overrides=None,
    set_crew_overrides=None,
    reset_clock=True,
):
    """Register one plant, one carrier, one escort crew and one installer crew.

    Returns ``{"plant", "hauler", "escort_crew", "set_crew"}``.
    """
    if reset_clock:
        set_logical_clock()
    return {
        "plant": register_plant(**(plant_overrides or {})),
        "hauler": register_hauler(**(hauler_overrides or {})),
        "escort_crew": register_escort_crew(**(escort_overrides or {})),
        "set_crew": register_set_crew(**(set_crew_overrides or {})),
    }


# ---------------------------------------------------------------------------
# Tier 3 — a whole home on the pad
# ---------------------------------------------------------------------------


def setup_delivered_order(
    section_count=1,
    destination_state="AZ",
    wind_zone="I",
    state_code=None,
    declared_width_in=168,
    declared_height_in=150,
    plant=None,
    hauler=None,
    order_overrides=None,
    section_overrides=None,
    corridor_id="AZ-I10",
    window_start="2026-08-03T06:00:00.000Z",
    window_end="2026-08-03T14:00:00.000Z",
    deliver=True,
    reset_clock=True,
):
    """Open an order, record every floor and walk each one to `DELIVERED`.

    Each floor is measured at its declared figures, released, permitted in the
    destination state with one corridor leg, paid for at its provisional fee and
    issued, then departed and arrived — so the floor's `transit_status` lands on
    `DELIVERED` and the order has an issued permit per floor.  The default
    figures (an `AZ` permit for a 168-inch-wide, 150-inch-tall floor on a single
    leg) require no escort and no pilot car, so issuance needs no reservations.

    Returns ``{"plant", "hauler", "order", "sections", "permits", "legs"}``.
    """
    if reset_clock:
        set_logical_clock()
    plant = plant or register_plant(state_code=destination_state)
    hauler = hauler or register_hauler(endorsed_states=[destination_state])
    order = open_order(
        plant["id"],
        section_count=section_count,
        destination_state=destination_state,
        wind_zone=wind_zone,
        **(order_overrides or {}),
    )
    permit_state = state_code or destination_state

    sections, permits, legs = [], [], []
    for index in range(1, section_count + 1):
        section = record_section(
            order["id"],
            plant["id"],
            section_index=index,
            declared_width_in=declared_width_in,
            declared_height_in=declared_height_in,
            **(section_overrides or {}),
        )
        measure_and_release_section(section["id"], plant["id"])
        permit = request_permit(
            section["id"], state_code=permit_state, planned_leg_count=1
        )
        leg = add_route_leg(
            permit["id"],
            hauler["id"],
            sequence_no=1,
            corridor_id=corridor_id,
            state_code=permit_state,
            window_start=window_start,
            window_end=window_end,
        )
        pay_and_issue_permit(permit["id"], hauler["id"])
        if deliver:
            depart_leg(leg["id"], hauler["id"])
            arrive_leg(leg["id"], hauler["id"])
        sections.append(read_section(section["id"]))
        permits.append(read_permit(permit["id"]))
        legs.append(read_route_leg(leg["id"]))

    return {
        "plant": plant,
        "hauler": hauler,
        "order": read_order(order["id"]),
        "sections": sections,
        "permits": permits,
        "legs": legs,
    }


def setup_order_with_ready_site(
    section_count=1,
    pier_count=None,
    pad_type="RUNNER",
    site_inspector_user_id=SITE_INSPECTOR_USER_ID,
    **delivered_kwargs,
):
    """A fully delivered order whose destination site has passed readiness.

    The pier plan is laid out with six piers per declared section, which is the
    minimum the readiness evaluation demands, so a clean verdict lands on
    `READY` with a `blocking_defect_count` of 0.

    Returns the `setup_delivered_order` mapping plus ``"site"``.
    """
    scenario = setup_delivered_order(section_count=section_count, **delivered_kwargs)
    piers = pier_count if pier_count is not None else 6 * section_count
    site = register_site(
        scenario["order"]["id"], pad_type=pad_type, pier_count=piers
    )
    scenario["site"] = inspect_site(
        site["id"], inspector_user_id=site_inspector_user_id
    )
    scenario["order"] = read_order(scenario["order"]["id"])
    return scenario


def setup_booked_set_job(
    section_count=1,
    set_crew=None,
    set_crew_overrides=None,
    job_overrides=None,
    **site_kwargs,
):
    """A delivered order with a ready site and a `SCHEDULED` set job.

    Returns the `setup_order_with_ready_site` mapping plus ``"set_crew"`` and
    ``"set_job"``.
    """
    scenario = setup_order_with_ready_site(section_count=section_count, **site_kwargs)
    crew = set_crew or register_set_crew(**(set_crew_overrides or {}))
    scenario["set_crew"] = crew
    scenario["set_job"] = book_set_job(
        scenario["order"]["id"], crew["id"], **(job_overrides or {})
    )
    scenario["order"] = read_order(scenario["order"]["id"])
    return scenario


def setup_dispatched_set_job(section_count=1, **kwargs):
    """A set job whose progress dimension has reached `DISPATCHED`."""
    scenario = setup_booked_set_job(section_count=section_count, **kwargs)
    scenario["set_job"] = dispatch_set_job(scenario["set_job"]["id"])
    scenario["order"] = read_order(scenario["order"]["id"])
    return scenario


# ---------------------------------------------------------------------------
# Tier 4 — the marriage line, the scope and the anchoring package
# ---------------------------------------------------------------------------


def record_in_tolerance_joints(job_id, set_crew_id, joint_count):
    """Record `joint_count` joints whose readings are all inside tolerance.

    A gap of exactly 0.25 inches, a zero offset and no shim contribute nothing,
    so every joint scores 0.00 and the closed line scores 0.00 as well.
    """
    joints = []
    for index in range(1, joint_count + 1):
        joints.append(
            record_marriage_joint(
                job_id,
                set_crew_id,
                joint_index=index,
                gap_in=0.25,
                vertical_offset_in=0.0,
                ridge_beam_shim_in=0.0,
            )
        )
    return joints


def setup_set_complete_job(section_count=1, joint_readings=None, **kwargs):
    """A dispatched job whose marriage line has been closed.

    `joint_readings` is an optional list of per-joint payload overrides in
    ascending joint order; when omitted every joint is recorded inside
    tolerance.  Returns the dispatched-job mapping plus ``"joints"``.
    """
    scenario = setup_dispatched_set_job(section_count=section_count, **kwargs)
    job_id = scenario["set_job"]["id"]
    crew_id = scenario["set_crew"]["id"]
    required_joints = max(0, section_count - 1)
    if joint_readings is None:
        scenario["joints"] = record_in_tolerance_joints(
            job_id, crew_id, required_joints
        )
    else:
        scenario["joints"] = [
            record_marriage_joint(job_id, crew_id, joint_index=index, **readings)
            for index, readings in enumerate(joint_readings, start=1)
        ]
    scenario["set_job"] = close_marriage_line(job_id, crew_id)
    scenario["order"] = read_order(scenario["order"]["id"])
    return scenario


def certify_anchoring_package(
    set_job_id,
    set_crew_id,
    section_count=1,
    wind_zone="I",
    destination_state="AZ",
    anchor_overrides=None,
    inspector_user_id=ANCHOR_INSPECTOR_USER_ID,
):
    """Submit an anchoring package that passes both verdicts, then certify it.

    The HUD figure is the per-zone anchor count multiplied by the declared
    section count, and the state figure adds four more anchors when the
    destination state is `KS` or `CO`; the package is submitted with one strap
    per anchor and 180 foot-pounds of average torque.
    """
    per_zone = {"I": 8, "II": 12, "III": 16}[wind_zone]
    required = per_zone * section_count
    if destination_state in ("KS", "CO"):
        required += 4
    payload = {
        "anchor_count": required,
        "avg_torque_ft_lb": 180,
        "strap_count": required,
        "pier_count": 6 * section_count,
    }
    payload.update(anchor_overrides or {})
    cert = submit_anchor_certification(set_job_id, set_crew_id, **payload)
    return review_anchor_certification(
        cert["id"], decision="CERTIFY", inspector_user_id=inspector_user_id
    )


def setup_job_ready_for_final_inspection(
    section_count=1,
    wind_zone="I",
    destination_state="AZ",
    labor_base_cents=480000,
    scope_overrides=None,
    crossover_count=1,
    anchor_overrides=None,
    anchor_inspector_user_id=ANCHOR_INSPECTOR_USER_ID,
    **kwargs
):
    """Everything the final installation inspection demands, and nothing more.

    Walks the job to `SET_COMPLETE` with a closed marriage line, records the
    scope split and the utility crossover so the scope dimension reaches
    `SCOPE_DELIVERED` with `crossover_recorded` true, and certifies the
    anchoring package under an inspector other than the one who signed the
    site-readiness verdict.

    Returns the `setup_set_complete_job` mapping plus ``"anchor_certification"``.
    """
    job_overrides = kwargs.pop("job_overrides", None) or {}
    job_overrides.setdefault("labor_base_cents", labor_base_cents)
    scenario = setup_set_complete_job(
        section_count=section_count,
        wind_zone=wind_zone,
        destination_state=destination_state,
        job_overrides=job_overrides,
        **kwargs,
    )
    job_id = scenario["set_job"]["id"]
    crew_id = scenario["set_crew"]["id"]
    record_scope_split(job_id, crew_id, **(scope_overrides or {}))
    record_utility_crossover(job_id, crew_id, crossover_count=crossover_count)
    scenario["anchor_certification"] = certify_anchoring_package(
        job_id,
        crew_id,
        section_count=section_count,
        wind_zone=wind_zone,
        destination_state=destination_state,
        anchor_overrides=anchor_overrides,
        inspector_user_id=anchor_inspector_user_id,
    )
    scenario["set_job"] = read_set_job(job_id)
    scenario["order"] = read_order(scenario["order"]["id"])
    return scenario


# ---------------------------------------------------------------------------
# Tier 4 — escort reservations against a live corridor leg
# ---------------------------------------------------------------------------


def setup_leg_awaiting_escorts(
    state_code="AZ",
    destination_state="AZ",
    declared_width_in=168,
    declared_height_in=150,
    planned_leg_count=1,
    night_move=False,
    corridor_id="AZ-I10",
    window_start="2026-08-03T06:00:00.000Z",
    window_end="2026-08-03T18:00:00.000Z",
    escort_crews=None,
    reset_clock=True,
):
    """A released floor with a requested permit and one `SCHEDULED` leg.

    `escort_crews` is an optional list of escort-crew payload overrides; each
    one is registered and returned under ``"escort_crews"``.  The permit is left
    in `REQUESTED` so reservations can be made before any fee is remitted.

    Returns ``{"plant", "hauler", "order", "section", "permit", "leg",
    "escort_crews"}``.
    """
    if reset_clock:
        set_logical_clock()
    plant = register_plant(state_code=destination_state)
    hauler = register_hauler(endorsed_states=[destination_state])
    crews = [register_escort_crew(**(spec or {})) for spec in (escort_crews or [])]
    order = open_order(
        plant["id"], section_count=1, destination_state=destination_state
    )
    section = record_section(
        order["id"],
        plant["id"],
        declared_width_in=declared_width_in,
        declared_height_in=declared_height_in,
    )
    measure_and_release_section(section["id"], plant["id"])
    permit = request_permit(
        section["id"],
        state_code=state_code,
        planned_leg_count=planned_leg_count,
        night_move=night_move,
    )
    leg = add_route_leg(
        permit["id"],
        hauler["id"],
        sequence_no=1,
        corridor_id=corridor_id,
        state_code=state_code,
        window_start=window_start,
        window_end=window_end,
    )
    return {
        "plant": plant,
        "hauler": hauler,
        "order": read_order(order["id"]),
        "section": read_section(section["id"]),
        "permit": read_permit(permit["id"]),
        "leg": leg,
        "escort_crews": crews,
    }


# ---------------------------------------------------------------------------
# Tier 5 — claims, the chargeback ledger and terminal states
# ---------------------------------------------------------------------------


def setup_claim_under_review(
    claimed_amount_cents=100000,
    discovered_stage="IN_TRANSIT",
    claim_overrides=None,
    deliver=True,
    reset_clock=True,
):
    """One floor, one carrier, one installer crew and a claim `UNDER_REVIEW`.

    Returns ``{"plant", "hauler", "set_crew", "order", "section", "permit",
    "leg", "claim"}``.
    """
    scenario = setup_delivered_order(
        section_count=1, deliver=deliver, reset_clock=reset_clock
    )
    set_crew = register_set_crew()
    claim = open_damage_claim(
        scenario["order"]["id"],
        scenario["sections"][0]["id"],
        scenario["hauler"]["id"],
        set_crew["id"],
        discovered_stage=discovered_stage,
        claimed_amount_cents=claimed_amount_cents,
        **(claim_overrides or {}),
    )
    review_damage_claim(claim["id"])
    scenario["set_crew"] = set_crew
    scenario["section"] = scenario["sections"][0]
    scenario["permit"] = scenario["permits"][0]
    scenario["leg"] = scenario["legs"][0]
    scenario["claim"] = read_damage_claim(claim["id"])
    return scenario


def setup_adjudicated_claim(allocation_basis="STAGE", **kwargs):
    """A settled claim, with the chargeback fan-out already applied."""
    scenario = setup_claim_under_review(**kwargs)
    scenario["claim"] = adjudicate_damage_claim(
        scenario["claim"]["id"], allocation_basis=allocation_basis
    )
    scenario["plant"] = read_plant(scenario["plant"]["id"])
    scenario["hauler"] = read_hauler(scenario["hauler"]["id"])
    scenario["set_crew"] = read_set_crew(scenario["set_crew"]["id"])
    scenario["order"] = read_order(scenario["order"]["id"])
    return scenario


def setup_scheduled_leg_for_claim(
    claimed_amount_cents=611112,
    discovered_stage="IN_TRANSIT",
    claim_overrides=None,
    reset_clock=True,
):
    """A `SCHEDULED` corridor leg plus a claim `UNDER_REVIEW` against its carrier.

    The floor is released and permitted and the leg is added, but the load never
    rolls, so the leg is still `SCHEDULED` and a carrier suspension can drive it
    to `HAULER_HOLD`.
    """
    if reset_clock:
        set_logical_clock()
    plant = register_plant(state_code="AZ")
    hauler = register_hauler(endorsed_states=["AZ"])
    set_crew = register_set_crew()
    order = open_order(plant["id"], section_count=1)
    section = record_section(order["id"], plant["id"])
    measure_and_release_section(section["id"], plant["id"])
    permit = request_permit(section["id"], state_code="AZ", planned_leg_count=1)
    leg = add_route_leg(permit["id"], hauler["id"], sequence_no=1, state_code="AZ")
    claim = open_damage_claim(
        order["id"],
        section["id"],
        hauler["id"],
        set_crew["id"],
        discovered_stage=discovered_stage,
        claimed_amount_cents=claimed_amount_cents,
        **(claim_overrides or {}),
    )
    review_damage_claim(claim["id"])
    return {
        "plant": plant,
        "hauler": hauler,
        "set_crew": set_crew,
        "order": read_order(order["id"]),
        "section": read_section(section["id"]),
        "permit": read_permit(permit["id"]),
        "leg": read_route_leg(leg["id"]),
        "claim": read_damage_claim(claim["id"]),
    }
