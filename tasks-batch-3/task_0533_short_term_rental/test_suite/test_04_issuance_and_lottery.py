"""Permit issuance eligibility gates, density cap, and lottery waterfall.

Covers difficulty queue A instances for zone eligibility, occupancy boundary,
gate ordering, density-cap overlap, and the lottery draw cascade; plus corner
queue B instances for the individual issuance validations and lottery OCC.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, PermitStatus,
    make_host_headers, TEST_USERS,
    setup_draft_permit, setup_issued_permit, create_draft_permit,
    create_zone, create_host, create_property, attest_primary,
    setup_lottery_pending_permit,
)

REGISTRAR = TEST_USERS["registrar_headers"]


# --------------------------------------------------------------------------
# Eligibility gates
# --------------------------------------------------------------------------

def test_issue_into_ineligible_zone_rejected(api):
    """PRD §3.4: "The zoning gate comes first: the referenced property's zone
    must be short-term-rental eligible, and if its str_eligible is false the
    issue is rejected with ERR_ZONE_INELIGIBLE (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/permit_issue_requires_zone_str_eligible
    """
    _, host, _, permit = setup_draft_permit(
        zone_overrides={"str_eligible": False, "whole_home_allowed": False},
    )
    validate_error(api.issue_permit(permit["id"], REGISTRAR), ApiErrorId.ERR_ZONE_INELIGIBLE)


def test_whole_home_forbidden_in_disallowed_zone(api):
    """PRD §3.4: "if the permit_type is WHOLE_HOME, the zone's whole_home_allowed
    must be true, otherwise the issue is rejected with ERR_WHOLE_HOME_FORBIDDEN
    (HTTP 422)."

    Design: Corner/validations/whole_home_forbidden_in_disallowed_zone
    """
    _, host, _, permit = setup_draft_permit(
        zone_overrides={"str_eligible": True, "whole_home_allowed": False},
        permit_overrides={"permit_type": "WHOLE_HOME"},
        attest=False,
    )
    validate_error(api.issue_permit(permit["id"], REGISTRAR), ApiErrorId.ERR_WHOLE_HOME_FORBIDDEN)


def test_primary_residence_permit_on_non_primary_property_rejected(api):
    """PRD §3.4: "if the permit_type is PRIMARY_RESIDENCE, the property must be
    the host's primary residence (its is_primary_residence must be true),
    otherwise the issue is rejected with ERR_NOT_PRIMARY_RESIDENCE (HTTP 422)."

    Design: Corner/validations/primary_residence_permit_on_non_primary_property_rejected
    """
    _, host, _, permit = setup_draft_permit(
        permit_overrides={"permit_type": "PRIMARY_RESIDENCE"},
        attest=False,
    )
    validate_error(api.issue_permit(permit["id"], REGISTRAR), ApiErrorId.ERR_NOT_PRIMARY_RESIDENCE)


def test_occupancy_at_max_boundary_issue_succeeds(api):
    """PRD §3.4: "the occupancy gate: attested_occupancy must be at least one and
    at most the property's max_occupancy, otherwise ERR_OCCUPANCY_EXCEEDS_MAX
    (HTTP 422)."
    PRD §3.2: "the system computes the property's max_occupancy as twice the
    bedroom count plus one."

    3-bedroom property => max_occupancy 7; attested_occupancy 7 is at the
    inclusive boundary and issues successfully.

    Design: Difficulty/boundary_precision_check/occupancy_at_max_boundary_issue_succeeds
    """
    _, host, _, permit = setup_draft_permit(
        prop_overrides={"bedroom_count": 3},
        permit_overrides={"attested_occupancy": 7},
    )
    data = validate_success(api.issue_permit(permit["id"], REGISTRAR))
    assert data["status"] == PermitStatus.ISSUED.value


def test_occupancy_over_max_rejected(api):
    """PRD §3.4: "the occupancy gate: attested_occupancy must be at least one and
    at most the property's max_occupancy, otherwise ERR_OCCUPANCY_EXCEEDS_MAX
    (HTTP 422)."

    3-bedroom property => max_occupancy 7; attested_occupancy 8 exceeds it.

    Design: Corner/validations/occupancy_over_max_rejected
    """
    _, host, _, permit = setup_draft_permit(
        prop_overrides={"bedroom_count": 3},
        permit_overrides={"attested_occupancy": 8},
    )
    validate_error(api.issue_permit(permit["id"], REGISTRAR), ApiErrorId.ERR_OCCUPANCY_EXCEEDS_MAX)


def test_barred_host_cannot_be_issued(api):
    """PRD §3.4: "Next the standing gate: the owning host's standing must be
    GOOD, otherwise ERR_HOST_BARRED (HTTP 422)."
    PRD §3.7: "a BARRED host cannot receive newly issued permits and cannot
    renew."

    A host barred by 3 upheld strike points (NOISE=1 + OVER_OCCUPANCY=2) cannot
    have a second permit issued.

    Design: Corner/validations/barred_host_cannot_be_issued
    """
    zone = create_zone()
    host = create_host()
    prop_a = create_property(host["id"], zone["id"], street_address="Bar-A St")
    prop_b = create_property(host["id"], zone["id"], street_address="Bar-B St")
    attest_primary(host["id"], prop_a["id"])
    permit_a = create_draft_permit(prop_a["id"], permit_type="PRIMARY_RESIDENCE")
    permit_a = validate_success(api.issue_permit(permit_a["id"], REGISTRAR))
    c1 = validate_success(api.create_complaint({"permit_id": permit_a["id"], "category": "NOISE"}, REGISTRAR), 201)
    validate_success(api.uphold_complaint(c1["id"], REGISTRAR))
    c2 = validate_success(api.create_complaint({"permit_id": permit_a["id"], "category": "OVER_OCCUPANCY"}, REGISTRAR), 201)
    validate_success(api.uphold_complaint(c2["id"], REGISTRAR))

    permit_b = create_draft_permit(prop_b["id"], permit_type="WHOLE_HOME")
    validate_error(api.issue_permit(permit_b["id"], REGISTRAR), ApiErrorId.ERR_HOST_BARRED)


# --------------------------------------------------------------------------
# Gate ordering (priority-pair conflicts)
# --------------------------------------------------------------------------

def test_reissue_issued_permit_hits_state_check_first(api):
    """PRD §2.9: "Only after references resolve is the target's state checked: if
    the requested transition is not defined from the resource's current state,
    the request is rejected with ERR_INVALID_STATE (HTTP 409). Domain-specific
    business rules - eligibility, safety, caps, windows, and so on - are
    evaluated after the state check."

    Re-issuing an already-ISSUED permit hits the state check (not DRAFT) before
    any business rule, so ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_issue
    """
    _, host, _, permit = setup_issued_permit()
    validate_error(api.issue_permit(permit["id"], REGISTRAR), ApiErrorId.ERR_INVALID_STATE)


def test_safety_gate_fires_before_cap_gate(api):
    """PRD §3.4: "Next the safety gate: safety_attested must be true, otherwise
    ERR_SAFETY_NOT_ATTESTED (HTTP 422)."
    PRD §3.4: "The final gate is the density cap."

    A DRAFT permit with safety_attested=false in a zone already at its cap fails
    the earlier safety gate, so ERR_SAFETY_NOT_ATTESTED wins over the cap error.

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_constraint_on_issue
    """
    zone = create_zone(permit_cap=1, lottery_enabled=False)
    host_a = create_host()
    host_b = create_host()
    prop_a = create_property(host_a["id"], zone["id"], street_address="Safe-A St")
    prop_b = create_property(host_b["id"], zone["id"], street_address="Safe-B St")
    attest_primary(host_a["id"], prop_a["id"])
    attest_primary(host_b["id"], prop_b["id"])
    permit_a = create_draft_permit(prop_a["id"], permit_type="PRIMARY_RESIDENCE")
    validate_success(api.issue_permit(permit_a["id"], REGISTRAR))
    permit_b = create_draft_permit(prop_b["id"], permit_type="PRIMARY_RESIDENCE", safety_attested=False)
    validate_error(api.issue_permit(permit_b["id"], REGISTRAR), ApiErrorId.ERR_SAFETY_NOT_ATTESTED)


# --------------------------------------------------------------------------
# Density cap overlap
# --------------------------------------------------------------------------

def test_permit_cap_reached_blocks_second_issue(api):
    """PRD §3.4: "If instead the zone's active permit count is at or beyond the
    permit_cap, behavior forks on the zone's lottery_enabled flag: ... when
    lottery is disabled, the issue is rejected with ERR_PERMIT_CAP_REACHED
    (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/permit_cap_density_overlap_within_zone
    """
    zone = create_zone(permit_cap=1, lottery_enabled=False)
    host_a = create_host()
    host_b = create_host()
    prop_a = create_property(host_a["id"], zone["id"], street_address="Cap-A St")
    prop_b = create_property(host_b["id"], zone["id"], street_address="Cap-B St")
    attest_primary(host_a["id"], prop_a["id"])
    attest_primary(host_b["id"], prop_b["id"])
    permit_a = create_draft_permit(prop_a["id"], permit_type="PRIMARY_RESIDENCE")
    validate_success(api.issue_permit(permit_a["id"], REGISTRAR))
    permit_b = create_draft_permit(prop_b["id"], permit_type="PRIMARY_RESIDENCE")
    validate_error(api.issue_permit(permit_b["id"], REGISTRAR), ApiErrorId.ERR_PERMIT_CAP_REACHED)


# --------------------------------------------------------------------------
# Lottery waterfall
# --------------------------------------------------------------------------

def test_lottery_draw_awards_seat_and_increments_count(api):
    """PRD §3.5: "The first seats_available of them are awarded: each awarded
    permit transitions from LOTTERY_PENDING to ISSUED, receives an issued_at of
    the current clock time and an expires_at of issued_at plus 365 days,
    increments the zone's active permit count by one per award, and increments
    its own version."

    Zone cap 1 with one ISSUED permit (apc 1); a second permit routed to
    LOTTERY_PENDING is awarded on draw => ISSUED, apc becomes 2.

    Design: Difficulty/transitive_cascade/lottery_draw_award_issues_and_counts_seat_depth2
    """
    zone, host_a, permit_a, host_b, permit_b, rnd, rv = setup_lottery_pending_permit()
    validate_success(api.draw_lottery_round(rnd["id"], {"expected_lottery_round_version": rv}, REGISTRAR))
    permit_b_after = validate_success(api.get_permit(permit_b["id"], REGISTRAR))
    assert permit_b_after["status"] == PermitStatus.ISSUED.value
    zone_after = validate_success(api.get_zone(zone["id"], REGISTRAR))
    assert zone_after["active_permit_count"] == 2, (
        f"expected active_permit_count 2, got {zone_after['active_permit_count']}"
    )
