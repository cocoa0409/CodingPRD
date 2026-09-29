"""Role-matrix closure, segregation of duties, requester scoping and shared peer work."""
from test_helpers import (
    ApiErrorId,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    AUTHOR,
    AUTHOR_ID,
    ENGINEER,
    INDEPENDENT_REVIEWER,
    LIAISON,
    REVIEWER,
    REVIEWER_ID,
    TECHNICIAN,
    create_corridor,
    create_requester,
    effective_splits,
    log_observation,
    propose_config,
    setup_coordinated_plan,
    setup_field_tuning_project,
)
from test_helpers.factories import complaint_payload
from test_helpers.test_users import (
    make_certifying_engineer_headers,
    make_public_requester_headers,
)

# A syntactically valid UUID that names no row in any table.
UNKNOWN_ID = "11111111-1111-4111-8111-111111111111"

# A PublicRequester header whose identity is not a persisted requester row; it is
# only ever used where the role gate answers before ownership is considered.
PUBLIC = make_public_requester_headers(UNKNOWN_ID)

# The plan author wearing the reviewing role: same operator identifier, different
# role name, which is exactly what the segregation-of-duties comparand ignores.
AUTHOR_AS_REVIEWER = make_certifying_engineer_headers(AUTHOR_ID)

# Four phases drafted at 21 / 30 / 22 / 22 for a total of 95 at a drafted cycle of
# 90.  Phase 2 serves a 62.0 ft crossing with only 10.0 s of pedestrian clearance,
# so the pipeline mints exactly one failing check for the reviewer to waive.
SOD_SPLITS = [
    {"phase_number": 1, "split_sec": 21, "min_green_sec": 10,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0},
    {"phase_number": 2, "split_sec": 30, "min_green_sec": 15,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0, "is_pedestrian_phase": True,
     "walk_sec": 5.0, "ped_clear_sec": 10.0, "crosswalk_length_ft": 62.0},
    {"phase_number": 4, "split_sec": 22, "min_green_sec": 10,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0},
    {"phase_number": 6, "split_sec": 22, "min_green_sec": 10,
     "yellow_sec": 3.0, "red_clearance_sec": 1.0},
]


def test_every_role_exclusive_operation_is_closed_to_the_other_five_roles():
    """Thirty-two endpoint-and-role pairings from outside the matrix, on an empty database.

    PRD §2.1: "When the headers are well formed but the named role is not among
    those authorised for the target endpoint in §4, the request fails with
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    PRD §2.7 pins the role gate above every identifier resolution: "Checks are
    evaluated in the fixed order below" places "3. The acting role is authorised
    for the target endpoint — `ERR_ROLE_NOT_PERMITTED`." ahead of "6. Path
    identifiers resolve, left to right — the eleven 404 codes of §2.6."

    Every path identifier offered below names nothing at all, so a role-clean
    caller would have been told 404; the answer is the role gate instead, and no
    row is left behind by any of the thirty-two attempts.

    Design: Corner/rbac/every_roles_exclusive_operations_are_closed_to_the_other_five_roles
    """
    refusals = [
        # SignalOpsAdmin owns the inventory, the screening, the phase gates it
        # holds, priority deployment and the logical clock.
        ("register an intersection as the timing engineer",
         api_client.create_intersection(
             {"location_name": "Main St @ 1st Ave", "controller_type": "TS2_CABINET"}, ENGINEER
         )),
        ("update an intersection as the field technician",
         api_client.update_intersection(UNKNOWN_ID, {"comm_status": "OFFLINE"}, TECHNICIAN)),
        ("screen a corridor as the certifying engineer",
         api_client.screen_corridor(UNKNOWN_ID, REVIEWER)),
        ("decide selection as the timing engineer",
         api_client.corridor_selection_decision(
             UNKNOWN_ID, {"decision": "SELECT", "rationale": "Not my call to make."}, ENGINEER
         )),
        ("start fine tuning as the timing engineer",
         api_client.project_field_tuning(UNKNOWN_ID, {"action": "START"}, ENGINEER)),
        ("close a project as the timing engineer",
         api_client.close_project(UNKNOWN_ID, {"reason": "Not my call to make."}, ENGINEER)),
        ("deploy priority as the certifying engineer",
         api_client.deploy_priority_config(UNKNOWN_ID, REVIEWER)),
        ("suspend priority as the timing engineer",
         api_client.suspend_priority_config(
             UNKNOWN_ID, ENGINEER, {"reason": "Not my call to make."}
         )),
        ("move the logical clock as the certifying engineer",
         api_client.set_clock("2026-08-02T00:00:00Z", REVIEWER)),
        # TimingEngineer opens projects, drafts the timing and implements it.
        ("open a project as the administrator",
         api_client.create_retiming_project(
             {
                 "corridor_id": UNKNOWN_ID,
                 "study_window_start_at": "2026-07-01T00:00:00Z",
                 "study_window_days": 180,
                 "lead_engineer_user_id": "timing-eng-1",
             },
             ADMIN,
         )),
        ("advance a project as the administrator",
         api_client.advance_project(UNKNOWN_ID, ADMIN)),
        ("coordinate a project as the certifying engineer",
         api_client.coordinate_project(UNKNOWN_ID, REVIEWER)),
        ("implement a project as the administrator",
         api_client.implement_project(UNKNOWN_ID, ADMIN)),
        ("draft a timing plan as the certifying engineer",
         api_client.create_timing_plan(
             {
                 "project_id": UNKNOWN_ID,
                 "intersection_id": UNKNOWN_ID,
                 "tod_period": "AM_PEAK",
                 "tod_start_min": 360,
                 "tod_end_min": 540,
                 "cycle_length_sec": 90,
             },
             REVIEWER,
         )),
        ("adjust a phase split as the administrator",
         api_client.update_phase_split(UNKNOWN_ID, {"split_sec": 25}, ADMIN)),
        ("submit a plan as the certifying engineer",
         api_client.submit_timing_plan(UNKNOWN_ID, REVIEWER)),
        ("propose a priority configuration as the administrator",
         api_client.create_priority_config(
             {
                 "intersection_id": UNKNOWN_ID,
                 "priority_type": "EVP",
                 "requested_max_extension_sec": 10,
                 "conflict_resolution_rank": 1,
             },
             ADMIN,
         )),
        # CertifyingEngineer certifies, returns, waives, approves and evaluates.
        ("certify a plan as the timing engineer",
         api_client.certify_timing_plan(UNKNOWN_ID, ENGINEER)),
        ("return a plan as the administrator",
         api_client.return_timing_plan(UNKNOWN_ID, {"reason": "Not my call to make."}, ADMIN)),
        ("waive a pedestrian check as the administrator",
         api_client.waive_pedestrian_check(
             UNKNOWN_ID, {"waiver_justification": "Not my call to make."}, ADMIN
         )),
        ("approve a priority configuration as the timing engineer",
         api_client.approve_priority_config(UNKNOWN_ID, {"decision": "APPROVE"}, ENGINEER)),
        ("produce an evaluation as the timing engineer",
         api_client.create_performance_evaluation(UNKNOWN_ID, {}, ENGINEER)),
        ("certify an evaluation as the administrator",
         api_client.certify_performance_evaluation(UNKNOWN_ID, ADMIN)),
        # FieldTechnician collects the field data.
        ("record a turning movement count as the timing engineer",
         api_client.create_turning_movement_count(
             UNKNOWN_ID,
             {
                 "project_id": UNKNOWN_ID,
                 "study_role": "BEFORE",
                 "count_date": "2026-07-15T00:00:00Z",
                 "period": "AM_PEAK",
                 "phase_volumes": {"1": 350},
             },
             ENGINEER,
         )),
        ("record a travel time run as the timing engineer",
         api_client.create_travel_time_run(
             UNKNOWN_ID,
             {
                 "study_role": "BEFORE",
                 "direction": "NB",
                 "started_at": "2026-07-15T09:00:00Z",
                 "duration_sec": 320,
                 "stops_count": 5,
                 "arrivals_on_green_count": 4,
                 "total_arrivals": 12,
             },
             ENGINEER,
         )),
        ("log a field observation as the citizen liaison",
         api_client.create_field_observation(
             {
                 "project_id": UNKNOWN_ID,
                 "intersection_id": UNKNOWN_ID,
                 "tod_period": "AM_PEAK",
                 "observed_at": "2026-08-01T00:00:00Z",
                 "finding_code": "QUEUE_SPILLBACK",
             },
             LIAISON,
         )),
        # CitizenLiaison registers requesters and drives the complaint machine.
        ("register a requester as the administrator",
         api_client.create_requester(
             {"display_name": "Dana Reyes", "email": "dana@example.org"}, ADMIN
         )),
        ("triage a complaint as the field technician",
         api_client.triage_complaint(UNKNOWN_ID, {"disposition": "TRIAGE"}, TECHNICIAN)),
        ("link a complaint as the timing engineer",
         api_client.link_complaint(UNKNOWN_ID, {"project_id": UNKNOWN_ID}, ENGINEER)),
        ("resolve a complaint as the administrator",
         api_client.resolve_complaint(
             UNKNOWN_ID, ADMIN, {"resolution_note": "Not my call to make."}
         )),
        ("reopen a complaint as the public requester",
         api_client.reopen_complaint(
             UNKNOWN_ID, PUBLIC, {"reason": "Not my call to make."}
         )),
        # PublicRequester holds no operational read at all.
        ("list corridors as the public requester", api_client.list_corridors(PUBLIC)),
    ]

    assert len(refusals) == 32, "the matrix is probed in both directions, 32 pairings in all"
    for description, response in refusals:
        validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)
        assert response.status_code == 403, f"{description} is a permission shortfall, not a 404"

    # None of the thirty-two attempts wrote anything, and the two entities that a
    # role-clean caller could have created on an empty database are still absent.
    _, intersection_meta = validate_paginated(api_client.list_intersections(ADMIN))
    assert intersection_meta["total_count"] == 0, "a refused create writes no intersection"
    _, corridor_meta = validate_paginated(api_client.list_corridors(ADMIN))
    assert corridor_meta["total_count"] == 0, "a refused create writes no corridor"


def test_segregation_of_duties_blocks_the_author_on_certify_waive_and_approve():
    """One operator identifier, two role names: the reviewing role does not launder the author.

    PRD §2.1: "Segregation of duties is enforced by comparing `X-User-ID` against
    the identity that authored the artefact under review, and it guards exactly
    three operations. Certifying a timing plan and waiving one of that plan's
    pedestrian compliance checks are refused with `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403) when the acting `X-User-ID` equals the plan's
    `authored_by_user_id`; approving or rejecting a priority configuration is
    refused with the same code when the acting `X-User-ID` equals that
    configuration's `proposed_by_user_id`."

    PRD §2.7 puts the gate above every state check: "4. Segregation of duties, on
    plan certification, pedestrian-check waiver and priority-configuration
    approval only — `ERR_SEGREGATION_OF_DUTIES`." precedes the rung carrying
    `ERR_PLAN_NOT_SUBMITTED`, so the author is turned away even while the plan is
    still `COORDINATED`.

    PRD §3.6: "That single residual is added to exactly one phase: the phase with
    the greatest `min_green_sec`".

    PRD §3.7: "`required_ped_clear_sec` is the crossing distance
    `crosswalk_length_ft` divided by that walking speed" ... "If the provided
    pedestrian change interval is less than the required one, the `result` is
    `FAIL` with `failure_reason` `PED_CLEAR_SHORT`." ... "After a waiver is
    applied, if the plan no longer holds any check whose `result` is `FAIL`, the
    plan's `ped_compliance_state` becomes `WAIVED`".

    Design: Corner/rbac/segregation_of_duties_blocks_the_author_on_certify_waive_and_approve
    """
    ctx = setup_coordinated_plan(plan_overrides={"cycle_length_sec": 90}, splits=SOD_SPLITS)
    plan_id = ctx["plan"]["id"]
    intersection_id = ctx["intersections"][0]["id"]

    # The comparand is recorded from the acting header at authoring time.
    assert ctx["plan"]["authored_by_user_id"] == AUTHOR_ID, "the author is stamped from X-User-ID"
    assert ctx["plan"]["status"] == "COORDINATED", "the pipeline has run but nothing is submitted"
    assert ctx["plan"]["cycle_length_sec"] == 105, "the coordinated cycle overwrites the drafted 90"
    assert effective_splits(plan_id) == {1: 23, 2: 34, 4: 24, 6: 24}, (
        "95 drafted seconds rescaled onto 105, the residual second going to phase 2"
    )

    assert len(ctx["ped_checks"]) == 1, "only the one pedestrian phase is evaluated"
    check = ctx["ped_checks"][0]
    check_id = check["id"]
    assert check["phase_number"] == 2
    assert check["required_ped_clear_sec"] == 17.8, "62.0 ft at 3.5 fps, raised to the next tenth"
    assert check["provided_ped_clear_sec"] == 10.0
    assert check["result"] == "FAIL", "a short pedestrian change interval fails first"
    assert check["failure_reason"] == "PED_CLEAR_SHORT"

    # Certifying a plan that is not even submitted yet: the author is stopped by
    # the duties gate, never by the plan's status.
    validate_error(
        api_client.certify_timing_plan(plan_id, AUTHOR_AS_REVIEWER),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    # Waiving one's own failing check is refused; the identical call under a
    # different operator identifier in the very same role is accepted.
    validate_error(
        api_client.waive_pedestrian_check(
            check_id,
            {"waiver_justification": "Author waiving their own failing check."},
            AUTHOR_AS_REVIEWER,
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    waived = validate_success(
        api_client.waive_pedestrian_check(
            check_id,
            {
                "waiver_justification": "Crosswalk is being shortened under a separate "
                                        "capital project; interim timing accepted."
            },
            INDEPENDENT_REVIEWER,
        )
    )
    assert waived["result"] == "WAIVED", "the discriminator is the acting identifier alone"
    assert waived["waived_by_user_id"] == REVIEWER_ID

    submitted = validate_success(api_client.submit_timing_plan(plan_id, ENGINEER))
    assert submitted["status"] == "SUBMITTED"
    assert submitted["ped_compliance_state"] == "WAIVED", "no failing check remains on the plan"

    validate_error(
        api_client.certify_timing_plan(plan_id, AUTHOR_AS_REVIEWER),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    certified = validate_success(api_client.certify_timing_plan(plan_id, INDEPENDENT_REVIEWER))
    assert certified["status"] == "CERTIFIED", "the refusal wrote nothing, so the plan still moves"
    assert certified["certified_by_user_id"] == REVIEWER_ID

    # The third guarded operation keys on a different authoring field.
    config = propose_config(
        intersection_id,
        headers=AUTHOR,
        priority_type="TSP",
        requested_max_extension_sec=8,
        conflict_resolution_rank=1,
    )
    assert config["proposed_by_user_id"] == AUTHOR_ID, "the proposer is stamped from X-User-ID"

    validate_error(
        api_client.approve_priority_config(config["id"], {"decision": "APPROVE"},
                                           AUTHOR_AS_REVIEWER),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    approved = validate_success(
        api_client.approve_priority_config(config["id"], {"decision": "APPROVE"},
                                          INDEPENDENT_REVIEWER)
    )
    assert approved["approval_status"] == "APPROVED", "the refused approval wrote nothing"
    assert approved["approved_by_user_id"] == REVIEWER_ID


def test_the_public_requester_is_scoped_to_their_own_row_while_the_liaison_is_not():
    """The same three endpoints, one role bounded by persisted ownership and one unbounded.

    PRD §2.1: "`PublicRequester` is the one **entity-backed** role. When
    `X-User-Role` is `PublicRequester`, `X-User-ID` is the `id` of the acting
    `Requester` row; ownership checks compare a resource's requester foreign key
    to `X-User-ID`. A `PublicRequester` reading a requester row, listing that
    requester's complaints, or filing a complaint must be acting on their own row
    — the requester identified in the path, and the `requester_id` supplied when
    filing, must equal `X-User-ID`. Otherwise the request fails with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403). A `CitizenLiaison` faces no such
    restriction and may read and file on behalf of any requester."

    PRD §2.7 places "5. Requester ownership, on reading a requester row, listing a
    requester's complaints, and filing a complaint — `ERR_NOT_RESOURCE_OWNER`."
    above "6. Path identifiers resolve, left to right — the eleven 404 codes of
    §2.6.", so a stranger's identifier and an identifier that names nothing at all
    are indistinguishable from outside: both answer 403.

    PRD §3.3: "A new requester's `open_complaint_count` starts at 0" ... "Either a
    `CitizenLiaison` or the `PublicRequester` themselves may file, the latter only
    with their own `requester_id`."

    Design: Corner/rbac/public_requester_is_scoped_to_their_own_row_while_the_liaison_is_not
    """
    corridor = create_corridor()
    first = create_requester(display_name="Dana Reyes", email="dana@example.org")
    second = create_requester(display_name="Sam Okafor", email="sam@example.org")
    first_headers = make_public_requester_headers(first["id"])
    second_headers = make_public_requester_headers(second["id"])

    own_row = validate_success(api_client.get_requester(first["id"], first_headers))
    assert own_row["display_name"] == "Dana Reyes", "reading one's own row is permitted"
    assert own_row["open_complaint_count"] == 0

    validate_error(
        api_client.get_requester(second["id"], first_headers),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        403,
    )
    validate_error(
        api_client.list_requester_complaints(second["id"], first_headers),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        403,
    )
    # A requester identifier that names nothing is still an ownership refusal, not
    # an existence disclosure.
    validate_error(
        api_client.get_requester(UNKNOWN_ID, first_headers),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        403,
    )

    # On filing, the comparand is the requester_id carried in the body.
    validate_error(
        api_client.create_complaint(
            complaint_payload(
                second["id"], corridor["id"],
                narrative="Filed on somebody else's behalf.",
            ),
            first_headers,
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        403,
    )
    own_complaint = validate_success(
        api_client.create_complaint(
            complaint_payload(
                first["id"], corridor["id"],
                narrative="Northbound queue never clears in the morning.",
            ),
            first_headers,
        ),
        201,
    )
    assert own_complaint["requester_id"] == first["id"]
    assert own_complaint["status"] == "OPEN"

    own_rows, own_meta = validate_paginated(
        api_client.list_requester_complaints(first["id"], first_headers)
    )
    assert own_meta["total_count"] == 1, "only the accepted filing exists"
    assert own_rows[0]["id"] == own_complaint["id"]
    refreshed = validate_success(api_client.get_requester(first["id"], first_headers))
    assert refreshed["open_complaint_count"] == 1, "the counter moved on the accepted filing only"

    # The identical body that was refused for the public user is accepted for the
    # liaison, who is outside the ownership gate altogether.
    liaison_complaint = validate_success(
        api_client.create_complaint(
            complaint_payload(
                second["id"], corridor["id"], category="PEDESTRIAN",
                narrative="Walk interval is too short at 1st Ave.",
            ),
            LIAISON,
        ),
        201,
    )
    assert liaison_complaint["requester_id"] == second["id"]
    foreign_row = validate_success(api_client.get_requester(second["id"], LIAISON))
    assert foreign_row["open_complaint_count"] == 1, "the liaison reads any requester's row"
    _, liaison_meta = validate_paginated(
        api_client.list_requester_complaints(first["id"], LIAISON)
    )
    assert liaison_meta["total_count"] == 1, "and lists any requester's complaints"

    # Triage is liaison-exclusive, so even the complaint's own requester is stopped
    # by the role gate before ownership is ever considered.
    validate_error(
        api_client.triage_complaint(
            liaison_complaint["id"], {"disposition": "TRIAGE"}, second_headers
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )


def test_the_two_holders_of_the_observation_patch_share_it_without_ownership_scoping():
    """The one mutating endpoint with two authorised roles, and the read shared by five.

    PRD §3.10: "Each observation is closed out by marking its `resolution_status`
    as `ADDRESSED` or `DISMISSED`; either a `FieldTechnician` or a
    `SignalOpsAdmin` may do so, and the observation must still be `OPEN`".

    PRD §2.4: "an integer that starts at 1 when the row is created and increases
    by exactly 1 on every mutation".

    PRD §2.1: "When the headers are well formed but the named role is not among
    those authorised for the target endpoint in §4, the request fails with
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Neither holder is scoped to the rows it authored: the technician logged both
    observations and the administrator still resolves the second. The roles outside
    the pair are refused even on an identifier that names nothing, because PRD §2.7
    places "3. The acting role is authorised for the target endpoint —
    `ERR_ROLE_NOT_PERMITTED`." above "6. Path identifiers resolve, left to right —
    the eleven 404 codes of §2.6."

    Design: Corner/rbac/peer_roles_share_the_observation_patch_and_every_operational_read
    """
    ctx = setup_field_tuning_project()
    project_id = ctx["project"]["id"]
    intersection_id = ctx["intersections"][0]["id"]
    assert ctx["project"]["status"] == "FIELD_TUNING", "the observation window is open"

    first = log_observation(project_id, intersection_id, finding_code="QUEUE_SPILLBACK")
    second = log_observation(project_id, intersection_id, finding_code="EARLY_RETURN_TO_GREEN")
    assert first["resolution_status"] == "OPEN"
    assert second["resolution_status"] == "OPEN"

    addressed = validate_success(
        api_client.update_field_observation(
            first["id"], {"resolution_status": "ADDRESSED"}, TECHNICIAN
        )
    )
    assert addressed["resolution_status"] == "ADDRESSED"
    assert addressed["version"] == 2, "one mutation moves the row's version by exactly 1"

    dismissed = validate_success(
        api_client.update_field_observation(
            second["id"], {"resolution_status": "DISMISSED"}, ADMIN
        )
    )
    assert dismissed["resolution_status"] == "DISMISSED", (
        "the administrator resolves a row the technician authored, unscoped"
    )
    assert dismissed["version"] == 2

    # The two roles outside the pair are refused, one on a real row and one on an
    # identifier that names nothing at all.
    validate_error(
        api_client.update_field_observation(
            first["id"], {"resolution_status": "DISMISSED"}, ENGINEER
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api_client.update_field_observation(
            UNKNOWN_ID, {"resolution_status": "DISMISSED"}, REVIEWER
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )

    # The operational read is one list shared by exactly five roles.
    for role_headers in (ADMIN, ENGINEER, REVIEWER, TECHNICIAN, LIAISON):
        rows, meta = validate_paginated(
            api_client.list_project_field_observations(project_id, role_headers)
        )
        assert meta["total_count"] == 2, "every staff role sees the identical list"
        assert {row["id"] for row in rows} == {first["id"], second["id"]}

    validate_error(
        api_client.list_project_field_observations(project_id, PUBLIC),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
        403,
    )

    # The sharing is not peculiar to observations.
    _, split_meta = validate_paginated(
        api_client.list_phase_splits(ctx["plan"]["id"], LIAISON)
    )
    assert split_meta["total_count"] == 4, "the liaison reads the plan's phase splits too"
