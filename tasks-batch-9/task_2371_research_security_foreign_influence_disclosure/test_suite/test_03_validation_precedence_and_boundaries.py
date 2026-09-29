"""Validation precedence and boundary precision.

Every test builds its own data from scratch: the harness restarts the server
before each test, so the database is empty and the logical clock sits at its
mandatory startup default of 2026-08-01T00:00:00Z. Time is moved only through
the documented clock endpoint.
"""

import pytest

from test_helpers import (
    DEFAULT_CLOCK,
    NON_EXISTENT_UUID,
    RSO,
    ApiErrorId,
    add_personnel,
    assign_and_complete_training,
    assign_training,
    clear_project_security,
    create_access_grant,
    create_access_grant_payload,
    create_investigator,
    create_project,
    get_success_data,
    read_investigator,
    read_project,
    set_clock,
    set_grant_status,
    setup_owned_organization_pair,
    setup_screened_subaward,
    setup_terminated_subaward,
    validate_error,
    validate_success,
)

GRANT_A_VALID_FROM = "2026-09-01T00:00:00Z"
GRANT_A_VALID_UNTIL = "2026-12-01T00:00:00Z"
GRANT_B_VALID_FROM = "2026-10-01T00:00:00Z"
GRANT_B_VALID_UNTIL = "2026-11-01T00:00:00Z"

MITIGATION_PAYLOAD = {
    "to_status": "MITIGATED",
    "mitigation_justification": "Scope narrowed to commercially available parts.",
}


# --------------------------------------------------------------------------- #
# Local setup helpers
# --------------------------------------------------------------------------- #

def _setup_capacity_one_area_with_untrained_second_holder():
    """A CLEARED project whose controlled area holds exactly one investigator.

    The first investigator has a COMPLETED CONTROLLED_AREA_SAFETY course and an
    ACTIVE grant over the whole window; the second holds an ACTIVE personnel row
    but no training assignment at all and a REQUESTED grant whose window sits
    inside the first one, so activating it would project a peak of 2 against a
    controlled_area_capacity of 1.

    Returns (project, untrained_investigator, requested_grant).
    """
    project = create_project(
        title="Catalysis Clean Room",
        agency_code="DOE",
        sensitivity_level="CONTROLLED",
        controlled_area_capacity=1,
    )
    trained = create_investigator(institutional_base_effort_pct=0)
    untrained = create_investigator(institutional_base_effort_pct=0)
    add_personnel(
        project["id"],
        trained["id"],
        role_on_project="PI",
        committed_person_months=2.00,
    )
    add_personnel(
        project["id"],
        untrained["id"],
        role_on_project="KEY_PERSON",
        committed_person_months=6.00,
    )
    assign_and_complete_training(
        trained["id"], course_code="CONTROLLED_AREA_SAFETY"
    )
    clear_project_security(project["id"])

    first_grant = create_access_grant(
        project["id"],
        trained["id"],
        valid_from=GRANT_A_VALID_FROM,
        valid_until=GRANT_A_VALID_UNTIL,
    )
    set_grant_status(first_grant["id"], "ACTIVE")

    second_grant = create_access_grant(
        project["id"],
        untrained["id"],
        valid_from=GRANT_B_VALID_FROM,
        valid_until=GRANT_B_VALID_UNTIL,
    )
    return read_project(project["id"]), untrained, second_grant


def _setup_project_with_stale_version_and_one_grant():
    """A capacity-2 project, a spare investigator and a stale project version.

    The captured version is read before the first access-grant create, which
    increments the project's version and therefore makes the captured value
    stale.

    Returns (project, spare_investigator, stale_version).
    """
    holder = create_investigator(institutional_base_effort_pct=0)
    spare = create_investigator(institutional_base_effort_pct=0)
    project = create_project(
        title="Autonomy Integration Lab",
        agency_code="DOD",
        sensitivity_level="CONTROLLED",
        controlled_area_capacity=2,
    )
    stale_version = read_project(project["id"])["version"]
    create_access_grant(
        project["id"],
        holder["id"],
        valid_from=GRANT_A_VALID_FROM,
        valid_until=GRANT_A_VALID_UNTIL,
    )
    return project, spare, stale_version


# --------------------------------------------------------------------------- #
# Terminal-state check outranks the restricted-entity check on mitigation
# --------------------------------------------------------------------------- #

def test_mitigating_a_terminated_sdn_subaward_reports_the_transition_error(api):
    """PRD §2.8: "Because most write endpoints in this system are guarded by
    several independent checks at once, the **order** in which those checks run is
    part of the contract: a request that violates two rules must fail with the
    earlier rule's error, not the later one's. The evaluation order is the
    following twenty steps, and the first step that fails ends the request."

    Design: Difficulty/priority_pair_validation_conflict/terminal_state_check_outranks_restricted_entity_check_on_mitigation
    """
    set_clock(DEFAULT_CLOCK)
    _project, _organization, subaward = setup_terminated_subaward(
        variant="DIRECT_MATCH", organization_designation="SDN"
    )
    # Both the transition check (step 7) and the restricted-entity check
    # (step 12) would fail on this request.
    assert subaward["status"] == "TERMINATED"
    assert subaward["screening_designation"] == "SDN"

    response = api.set_subaward_status(subaward["id"], MITIGATION_PAYLOAD, RSO)
    validate_error(
        response,
        ApiErrorId.ERR_INVALID_SUBAWARD_TRANSITION.value,
        expected_status=409,
    )

    unchanged = get_success_data(api.get_subaward(subaward["id"], RSO))
    assert unchanged["status"] == "TERMINATED"
    assert unchanged["mitigation_justification"] is None


def test_mitigating_a_blocked_sdn_subaward_reports_the_restricted_entity_error(api):
    """PRD §3.6: "Mitigation is admissible from `FLAGGED → MITIGATED` and from
    `BLOCKED → MITIGATED`, and both paths carry exactly the same two conditions:
    `screening_designation` must not be `SDN`, else `ERR_RESTRICTED_ENTITY_BLOCKED`
    — a specially designated national is never mitigable, only terminated — and a
    `mitigation_justification` must be supplied, else `ERR_INVALID_REQUEST`."

    Design: Difficulty/priority_pair_validation_conflict/terminal_state_check_outranks_restricted_entity_check_on_mitigation
    """
    set_clock(DEFAULT_CLOCK)
    _project, _organization, subaward = setup_screened_subaward(
        variant="DIRECT_MATCH", organization_designation="SDN"
    )
    # The declared BLOCKED -> MITIGATED edge exists, so the state check passes
    # and only the SDN condition is left to fail.
    assert subaward["status"] == "BLOCKED"
    assert subaward["screening_designation"] == "SDN"
    assert subaward["screening_risk_points"] == 90

    response = api.set_subaward_status(subaward["id"], MITIGATION_PAYLOAD, RSO)
    validate_error(
        response,
        ApiErrorId.ERR_RESTRICTED_ENTITY_BLOCKED.value,
        expected_status=409,
    )

    unchanged = get_success_data(api.get_subaward(subaward["id"], RSO))
    assert unchanged["status"] == "BLOCKED"
    assert unchanged["mitigation_justification"] is None


# --------------------------------------------------------------------------- #
# Area-training check outranks the area-capacity check on grant activation
# --------------------------------------------------------------------------- #

def test_grant_activation_without_area_training_reports_the_training_error(api):
    """PRD §2.8: "Training gate — `CONTROLLED_AREA_SAFETY` must be satisfied
    before a grant activates, and `FOREIGN_TRAVEL_BRIEF` before a loaner-tier trip
    is approved; separately, no project-scoped assignment may be `ASSIGNED` or
    `EXPIRED` at award activation. Applies to
    `POST /controlled-access-grants/{grant_id}/status` and
    `POST /travel-registrations/{registration_id}/status`; failure is
    `ERR_AREA_TRAINING_INCOMPLETE` or `ERR_TRAVEL_BRIEFING_REQUIRED` (both 409)."

    Design: Difficulty/priority_pair_validation_conflict/area_training_check_outranks_area_capacity_check_on_activation
    """
    set_clock(DEFAULT_CLOCK)
    _project, _untrained, grant = _setup_capacity_one_area_with_untrained_second_holder()
    # The stored projection already shows the capacity conflict this request
    # also carries: a peak of 2 against a controlled_area_capacity of 1.
    assert grant["status"] == "REQUESTED"
    assert grant["peak_concurrency_at_request"] == 2

    response = api.set_access_grant_status(
        grant["id"], {"to_status": "ACTIVE"}, RSO
    )
    validate_error(
        response,
        ApiErrorId.ERR_AREA_TRAINING_INCOMPLETE.value,
        expected_status=409,
    )

    unchanged = get_success_data(api.get_access_grant(grant["id"], RSO))
    assert unchanged["status"] == "REQUESTED"


def test_grant_activation_with_area_training_reports_the_capacity_error(api):
    """PRD §3.7: "The check fails only on strictly greater: a peak exactly equal
    to the project's `controlled_area_capacity` is admissible, and a peak of one
    more than the capacity is refused with `ERR_AREA_CAPACITY_EXCEEDED` (HTTP
    409)."

    Design: Difficulty/priority_pair_validation_conflict/area_training_check_outranks_area_capacity_check_on_activation
    """
    set_clock(DEFAULT_CLOCK)
    project, untrained, grant = _setup_capacity_one_area_with_untrained_second_holder()
    # Satisfy the training gate so the capacity projection is the only rule left.
    assign_and_complete_training(
        untrained["id"], course_code="CONTROLLED_AREA_SAFETY"
    )

    response = api.set_access_grant_status(
        grant["id"], {"to_status": "ACTIVE"}, RSO
    )
    validate_error(
        response,
        ApiErrorId.ERR_AREA_CAPACITY_EXCEEDED.value,
        expected_status=409,
    )

    unchanged = get_success_data(api.get_access_grant(grant["id"], RSO))
    assert unchanged["status"] == "REQUESTED"
    assert unchanged["peak_concurrency_at_request"] == 2

    current = read_project(project["id"])
    assert current["controlled_area_capacity"] == 1
    assert current["active_grant_count"] == 1


# --------------------------------------------------------------------------- #
# Body foreign-key existence outranks the parent version guard on grant create
# --------------------------------------------------------------------------- #

def test_grant_create_with_unknown_investigator_and_stale_version_reports_not_found(api):
    """PRD §2.8: "Body foreign-key existence — every `*_id` field in the request
    body resolves, in declaration order, on every endpoint whose input carries
    one; failure is the matching 404."

    Design: Difficulty/priority_pair_validation_conflict/body_fk_existence_outranks_optimistic_concurrency_on_grant_create
    """
    set_clock(DEFAULT_CLOCK)
    project, _spare, stale_version = _setup_project_with_stale_version_and_one_grant()
    before = read_project(project["id"])
    # The captured version really is stale, so both step 5 and step 8 would fail.
    assert before["version"] > stale_version

    response = api.create_access_grant(
        create_access_grant_payload(
            project["id"],
            NON_EXISTENT_UUID,
            stale_version,
            valid_from=GRANT_A_VALID_FROM,
            valid_until=GRANT_A_VALID_UNTIL,
        ),
        RSO,
    )
    validate_error(
        response,
        ApiErrorId.ERR_INVESTIGATOR_NOT_FOUND.value,
        expected_status=404,
    )

    after = read_project(project["id"])
    assert after["version"] == before["version"]


def test_grant_create_with_a_known_investigator_and_stale_version_reports_stale(api):
    """PRD §2.7: "`POST /controlled-access-grants` requires
    `expected_project_version`, carrying the client's last observed `version` of
    the target `Project`. Multiple `REQUESTED` grants on the same controlled area
    are legitimate, so a grant sized against a capacity picture that no longer
    exists would be accepted on state grounds alone. A mismatch is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Difficulty/priority_pair_validation_conflict/body_fk_existence_outranks_optimistic_concurrency_on_grant_create
    """
    set_clock(DEFAULT_CLOCK)
    project, spare, stale_version = _setup_project_with_stale_version_and_one_grant()
    before = read_project(project["id"])

    stale_response = api.create_access_grant(
        create_access_grant_payload(
            project["id"],
            spare["id"],
            stale_version,
            valid_from=GRANT_A_VALID_FROM,
            valid_until=GRANT_A_VALID_UNTIL,
        ),
        RSO,
    )
    validate_error(
        stale_response, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412
    )
    assert read_project(project["id"])["version"] == before["version"]

    # The identical request carrying the project's current version is accepted.
    fresh_response = api.create_access_grant(
        create_access_grant_payload(
            project["id"],
            spare["id"],
            read_project(project["id"])["version"],
            valid_from=GRANT_A_VALID_FROM,
            valid_until=GRANT_A_VALID_UNTIL,
        ),
        RSO,
    )
    grant = validate_success(fresh_response, expected_status=201)
    assert grant["status"] == "REQUESTED"
    assert grant["peak_concurrency_at_request"] == 2
    assert read_project(project["id"])["version"] == before["version"] + 1


# --------------------------------------------------------------------------- #
# The controlling-interest threshold is inclusive at 50.00 percent
# --------------------------------------------------------------------------- #

def test_a_fifty_percent_stake_inherits_the_parents_sdn_designation(api):
    """PRD §2.10: "The 50 percent threshold is inclusive and is compared at two
    decimal places: a stake of exactly 50.00 percent conveys control and therefore
    inherits designation, while 49.99 percent does not."

    Design: Difficulty/boundary_precision_check/ownership_control_threshold_inclusive_at_50_00_pct
    """
    set_clock(DEFAULT_CLOCK)
    _parent, child = setup_owned_organization_pair(
        parent_designation="SDN",
        child_designation="NONE",
        ownership_pct=50.00,
        parent_overrides={
            "legal_name": "Northline State Holdings",
            "country_code": "RU",
            "org_type": "GOVERNMENT_AGENCY",
        },
        child_overrides={
            "legal_name": "Northline Precision Works",
            "country_code": "RU",
            "org_type": "COMPANY",
        },
    )

    stored = validate_success(
        api.get_foreign_organization(child["id"], RSO), expected_status=200
    )
    assert stored["parent_ownership_pct"] == pytest.approx(50.00, abs=0.01)
    assert stored["effective_designation"] == "SDN"
    assert stored["effective_designation_depth"] == 1
    # Imputation never rewrites the organization's own direct designation.
    assert stored["own_designation"] == "NONE"


def test_a_stake_just_below_fifty_percent_breaks_the_chain_of_control(api):
    """PRD §2.10: "The 50 percent threshold is inclusive and is compared at two
    decimal places: a stake of exactly 50.00 percent conveys control and therefore
    inherits designation, while 49.99 percent does not."

    Design: Difficulty/boundary_precision_check/ownership_control_threshold_inclusive_at_50_00_pct
    """
    set_clock(DEFAULT_CLOCK)
    _parent, child = setup_owned_organization_pair(
        parent_designation="SDN",
        child_designation="NONE",
        ownership_pct=49.99,
        parent_overrides={
            "legal_name": "Northline State Holdings",
            "country_code": "RU",
            "org_type": "GOVERNMENT_AGENCY",
        },
        child_overrides={
            "legal_name": "Northline Optical Works",
            "country_code": "RU",
            "org_type": "COMPANY",
        },
    )

    stored = validate_success(
        api.get_foreign_organization(child["id"], RSO), expected_status=200
    )
    assert stored["parent_ownership_pct"] == pytest.approx(49.99, abs=0.01)
    assert stored["effective_designation"] == "NONE"
    assert stored["effective_designation_depth"] == 0
    assert stored["own_designation"] == "NONE"


# --------------------------------------------------------------------------- #
# Training expiry is inclusive at the due instant
# --------------------------------------------------------------------------- #

def test_training_assignment_still_reads_assigned_one_second_before_the_deadline(api):
    """PRD §3.9: "Its `status` is derived on every read, and on every rule that
    consults training compliance, from its own `waived_on`, `completed_on` and
    `due_on` against the current logical clock, in exactly this order: if
    `waived_on` is not null the status is `WAIVED`; otherwise if `completed_on` is
    not null the status is `COMPLETED`; otherwise if the clock has reached or
    passed `due_on` the status is `EXPIRED`; otherwise the status is `ASSIGNED`.
    The deadline comparison is inclusive, so a clock sitting exactly on `due_on`
    reads as `EXPIRED` while one second earlier reads as `ASSIGNED`."

    Design: Difficulty/boundary_precision_check/training_expiry_inclusive_at_the_due_instant
    """
    set_clock(DEFAULT_CLOCK)
    investigator = create_investigator(institutional_base_effort_pct=0)
    assignment = assign_training(
        investigator["id"],
        course_code="RESEARCH_SECURITY_BASE",
        due_on="2026-09-01T00:00:00Z",
    )

    set_clock("2026-08-31T23:59:59Z")
    stored = validate_success(
        api.get_training_assignment(assignment["id"], RSO), expected_status=200
    )
    assert stored["status"] == "ASSIGNED"
    assert stored["completed_on"] is None
    assert stored["waived_on"] is None
    assert stored["assigned_on"].startswith("2026-08-01T00:00:00")


def test_training_assignment_reads_expired_at_the_exact_due_instant(api):
    """PRD §3.9: "The deadline comparison is inclusive, so a clock sitting exactly
    on `due_on` reads as `EXPIRED` while one second earlier reads as `ASSIGNED`."

    Design: Difficulty/boundary_precision_check/training_expiry_inclusive_at_the_due_instant
    """
    set_clock(DEFAULT_CLOCK)
    investigator = create_investigator(institutional_base_effort_pct=0)
    assignment = assign_training(
        investigator["id"],
        course_code="RESEARCH_SECURITY_BASE",
        due_on="2026-09-01T00:00:00Z",
    )

    set_clock("2026-09-01T00:00:00Z")
    stored = validate_success(
        api.get_training_assignment(assignment["id"], RSO), expected_status=200
    )
    assert stored["status"] == "EXPIRED"
    assert stored["completed_on"] is None
    assert stored["waived_on"] is None
    # An institution-wide assignment reading EXPIRED leaves the investigator
    # non-compliant.
    assert read_investigator(investigator["id"])["training_compliant"] is False
