"""Cross-entity state gates: writes refused because of a state that lives on a neighbouring
row, replayed unchanged once the neighbour moves."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_scoped_request,
    api_client,
    get_success_data,
    make_quality_reviewer_headers,
    milestone_payload,
    project_request_payload,
    read_cycle,
    read_engagement,
    read_request,
    read_time_logs,
    read_window,
    set_clock,
    setup_offer,
    setup_sent_agreement,
    setup_submitted_engagement,
    validate_error,
    validate_paginated,
    validate_success,
)

LEASE_SCHEDULE = [
    {
        "title": "Lease schedule",
        "sequence_no": 1,
        "weight_pct": 100.00,
        "hours_estimate": 40.00,
        "acceptance_criteria": "Schedule signed off by counsel",
    }
]

SEVEN_AND_A_QUARTER_HOURS = {
    "work_date": "2026-08-12T00:00:00Z",
    "hours": 7.25,
    "activity_class": "DELIVERY",
}

MIXED_CLASS_LOGS = [
    {"work_date": "2026-08-12T00:00:00Z", "hours": 7.25, "activity_class": "DELIVERY"},
    {"work_date": "2026-08-13T00:00:00Z", "hours": 3.50, "activity_class": "ADMIN"},
    {"work_date": "2026-08-14T00:00:00Z", "hours": 2.00, "activity_class": "TRAVEL"},
]

CHECKIN_DUE_AT = "2026-08-20T00:00:00Z"
GRACE_BAND_FLOOR = "2026-08-19T00:00:00Z"


# ---------------------------------------------------------------------------
# The governing agreement gates the engagement, its logs and its check-ins
# ---------------------------------------------------------------------------
def _sent_agreement_world():
    """An engagement sitting in `NOT_STARTED` whose only defect is remote: the governing
    agreement was drafted and sent but neither counterparty has executed it."""
    return setup_sent_agreement(
        skill_code="LEGAL_CONTRACTS",
        deliverables=LEASE_SCHEDULE,
        title="Lease portfolio diligence",
    )


def _execute_both_counterparties(world):
    """Both signature slots stamped, which is the only change the replayed calls rely on."""
    get_success_data(
        api_client.execute_agreement(
            world["agreement"]["id"], world["volunteer_headers"]
        )
    )
    return get_success_data(
        api_client.execute_agreement(
            world["agreement"]["id"], world["partner_headers"]
        )
    )


def test_01_a_merely_sent_agreement_refuses_the_start_of_its_engagement(api):
    """PRD §2.12: "The engagement's agreement has `status` `EXECUTED` — on
    `POST /engagements/{id}/start` and `POST /engagements/{id}/time-logs` — otherwise
    `ERR_AGREEMENT_NOT_EXECUTED` (409)."
    PRD §3.6: "An engagement whose agreement has not reached `EXECUTED` cannot be started
    and cannot receive time logs; both are refused with `ERR_AGREEMENT_NOT_EXECUTED`."

    Design: Difficulty/cross_entity_state_dependency/agreement_execution_gates_engagement_start
    """
    world = _sent_agreement_world()
    before = read_engagement(world)
    assert before["work_status"] == "NOT_STARTED", (
        f"Setup expected the exact from-state NOT_STARTED, got {before['work_status']}"
    )

    response = api_client.start_engagement(
        world["engagement"]["id"], world["volunteer_headers"]
    )

    validate_error(response, ApiErrorId.ERR_AGREEMENT_NOT_EXECUTED)
    body = response.json()
    assert body["data"]["error_id"] != ApiErrorId.ERR_INVALID_WORK_STATE.value, (
        "NOT_STARTED is the from-state the start endpoint wants, so the work-state rung "
        "must pass"
    )
    after = read_engagement(world)
    assert after["work_status"] == "NOT_STARTED", (
        f"Expected work_status still NOT_STARTED, got {after['work_status']}"
    )
    assert after["version"] == before["version"], (
        f"A rejection applies nothing, so version must stay {before['version']}, got "
        f"{after['version']}"
    )


def test_02_the_identical_start_succeeds_once_both_parties_execute(api):
    """PRD §3.7: "Work begins when the engaged volunteer starts the engagement, moving its
    `work_status` `NOT_STARTED → IN_PROGRESS` and carrying the parent request
    `ENGAGED → IN_DELIVERY`."
    PRD §3.7: "The agreement gate is the point of the whole negotiation: no hour of donated
    work may be performed before the IP and confidentiality terms are executed."

    Design: Difficulty/cross_entity_state_dependency/agreement_execution_gates_engagement_start
    """
    world = _sent_agreement_world()
    validate_error(
        api_client.start_engagement(
            world["engagement"]["id"], world["volunteer_headers"]
        ),
        ApiErrorId.ERR_AGREEMENT_NOT_EXECUTED,
    )

    executed = _execute_both_counterparties(world)
    assert executed["status"] == "EXECUTED", (
        f"Expected the agreement EXECUTED after both signatures, got "
        f"{executed['status']}"
    )

    started = validate_success(
        api_client.start_engagement(
            world["engagement"]["id"], world["volunteer_headers"]
        )
    )
    assert started["work_status"] == "IN_PROGRESS", (
        f"The replayed call must now succeed into IN_PROGRESS, got "
        f"{started['work_status']}"
    )
    assert read_request(world)["status"] == "IN_DELIVERY", (
        f"Expected the parent request IN_DELIVERY, got {read_request(world)['status']}"
    )


def test_03_a_flawless_time_log_is_refused_by_the_parent_work_state(api):
    """PRD §2.12: "The engagement's `work_status` is in the from-set of the requested
    transition — start requires `NOT_STARTED`, submit requires `IN_PROGRESS`, time logging
    and scope-change creation require `IN_PROGRESS`, opening a quality review requires
    `SUBMITTED`, handoff requires `ACCEPTED`, and terminate requires a non-terminal value —
    on `POST /engagements/{id}/start`, `POST /engagements/{id}/submit`,
    `POST /engagements/{id}/time-logs`, `POST /engagements/{id}/scope-change-requests`,
    `POST /engagements/{id}/quality-reviews`, `POST /engagements/{id}/handoff`,
    `POST /engagements/{id}/terminate`, `POST /engagements/{id}/satisfaction-surveys` and
    `POST /milestones/{id}/hold`, otherwise `ERR_INVALID_WORK_STATE` (409)."
    PRD §2.12: "The ordering is global: a check with a lower number always wins over a check
    with a higher number on the same endpoint."

    Design: Difficulty/cross_entity_state_dependency/unexecuted_agreement_blocks_time_log_via_work_state
    """
    world = _sent_agreement_world()

    response = api_client.create_time_log(
        world["engagement"]["id"], SEVEN_AND_A_QUARTER_HOURS, world["volunteer_headers"]
    )

    validate_error(response, ApiErrorId.ERR_INVALID_WORK_STATE)
    body = response.json()
    assert body["data"]["error_id"] != ApiErrorId.ERR_AGREEMENT_NOT_EXECUTED.value, (
        "The work-state rung at 23 outranks the agreement rung at 36"
    )
    assert body["data"]["error_id"] != ApiErrorId.ERR_ZERO_HOURS_NOT_ALLOWED.value, (
        "7.25 hours is a perfectly valid figure"
    )
    assert body["data"]["error_id"] != ApiErrorId.ERR_WINDOW_OUTSIDE_CYCLE.value, (
        "The work date sits inside the pinned availability window"
    )
    assert body["data"]["error_id"] != ApiErrorId.ERR_AVAILABILITY_HOURS_EXCEEDED.value, (
        "The window has hundreds of unheld hours"
    )
    assert read_time_logs(world) == [], (
        f"A refused log must not be persisted, got {read_time_logs(world)}"
    )
    assert read_window(world)["hours_committed"] == pytest.approx(40.00, abs=0.01), (
        f"Expected the window ledger untouched at 40.00, got "
        f"{read_window(world)['hours_committed']}"
    )


def test_04_the_identical_time_log_is_accepted_once_the_work_is_live(api):
    """PRD §3.7: "Each line is stored with `approved` false, a null `approved_at` and a null
    `milestone_id`, a `rate_basis_usd` snapshotting the volunteer's
    `professional_rate_usd_per_hour` as it stood at log creation, and a `logged_by_user_id`
    recording the submitting volunteer."

    Design: Difficulty/cross_entity_state_dependency/unexecuted_agreement_blocks_time_log_via_work_state
    """
    world = _sent_agreement_world()
    validate_error(
        api_client.create_time_log(
            world["engagement"]["id"],
            SEVEN_AND_A_QUARTER_HOURS,
            world["volunteer_headers"],
        ),
        ApiErrorId.ERR_INVALID_WORK_STATE,
    )

    _execute_both_counterparties(world)
    get_success_data(
        api_client.start_engagement(
            world["engagement"]["id"], world["volunteer_headers"]
        )
    )

    log = validate_success(
        api_client.create_time_log(
            world["engagement"]["id"],
            SEVEN_AND_A_QUARTER_HOURS,
            world["volunteer_headers"],
        ),
        201,
    )
    assert log["hours"] == pytest.approx(7.25, abs=0.01), (
        f"Expected hours 7.25, got {log['hours']}"
    )
    assert log["rate_basis_usd"] == pytest.approx(150.00, abs=0.01), (
        f"Expected rate_basis_usd 150.00 snapshotted from the volunteer, got "
        f"{log['rate_basis_usd']}"
    )
    assert log["approved"] is False, (
        f"A new log starts unapproved, got {log['approved']}"
    )


def test_05_a_checkin_may_be_scheduled_before_work_starts_but_not_held(api):
    """PRD §3.7: "Check-ins are scheduled by a `ProgramManager`, who supplies only a
    `due_at`; the milestone is created in `checkin_status` `SCHEDULED` with a `sequence_no`
    one greater than the highest among its siblings, and with null `held_at`,
    `reported_cumulative_hours`, `variance_hours` and `waiver_reason` and
    `escalation_raised` false."
    PRD §2.12: "The milestone's `checkin_status` is `SCHEDULED` — on
    `POST /milestones/{id}/hold` — otherwise `ERR_MILESTONE_NOT_SCHEDULED` (409)."

    Design: Difficulty/cross_entity_state_dependency/unexecuted_agreement_blocks_milestone_checkin_two_hops
    """
    world = _sent_agreement_world()

    milestone = validate_success(
        api_client.create_milestone(
            world["engagement"]["id"],
            milestone_payload(due_at=CHECKIN_DUE_AT),
            world["pm_headers"],
        ),
        201,
    )
    assert milestone["checkin_status"] == "SCHEDULED", (
        f"Scheduling on a NOT_STARTED engagement is allowed, got "
        f"{milestone['checkin_status']}"
    )
    set_clock(GRACE_BAND_FLOOR, world["pm_headers"])

    response = api_client.hold_milestone(
        milestone["id"], {"reported_cumulative_hours": 0.00}, world["pm_headers"]
    )

    validate_error(response, ApiErrorId.ERR_INVALID_WORK_STATE)
    body = response.json()
    assert body["data"]["error_id"] != ApiErrorId.ERR_MILESTONE_NOT_SCHEDULED.value, (
        "The milestone's own state is SCHEDULED, so its own rung passes"
    )
    unchanged = get_success_data(
        api_client.get_milestone(milestone["id"], world["pm_headers"])
    )
    assert unchanged["checkin_status"] == "SCHEDULED", (
        f"Expected checkin_status still SCHEDULED, got {unchanged['checkin_status']}"
    )
    assert unchanged["held_at"] is None, (
        f"Expected a null held_at, got {unchanged['held_at']}"
    )
    assert read_engagement(world)["approved_hours"] == pytest.approx(0.00, abs=0.01), (
        f"The hold's approval side effect must not have run, got "
        f"{read_engagement(world)['approved_hours']}"
    )


def test_06_the_identical_hold_succeeds_two_hops_after_the_agreement_moves(api):
    """PRD §3.7: "The hold moves the milestone `SCHEDULED → HELD` with `held_at` stamped,
    and then, in this order: every child time log of the engagement that is still unapproved
    and whose `work_date` is at or before the milestone's `due_at` flips `approved` to true
    with `approved_at` stamped and its `milestone_id` set to this milestone; the
    engagement's `approved_hours` is recomputed; the creep calculation reruns and may move
    `creep_escalation_level`; `variance_hours` is computed as the reported cumulative hours
    less the engagement's `approved_hours` *measured after those approvals*, which is why an
    early hold can show a negative variance; and `escalation_raised` is set to true when the
    recomputed `creep_escalation_level` is `ESCALATED` or `BREACH`."

    Design: Difficulty/cross_entity_state_dependency/unexecuted_agreement_blocks_milestone_checkin_two_hops
    """
    world = _sent_agreement_world()
    milestone = get_success_data(
        api_client.create_milestone(
            world["engagement"]["id"],
            milestone_payload(due_at=CHECKIN_DUE_AT),
            world["pm_headers"],
        )
    )
    set_clock(GRACE_BAND_FLOOR, world["pm_headers"])
    validate_error(
        api_client.hold_milestone(
            milestone["id"], {"reported_cumulative_hours": 0.00}, world["pm_headers"]
        ),
        ApiErrorId.ERR_INVALID_WORK_STATE,
    )

    _execute_both_counterparties(world)
    get_success_data(
        api_client.start_engagement(
            world["engagement"]["id"], world["volunteer_headers"]
        )
    )

    held = validate_success(
        api_client.hold_milestone(
            milestone["id"], {"reported_cumulative_hours": 0.00}, world["pm_headers"]
        )
    )
    assert held["checkin_status"] == "HELD", (
        f"Expected checkin_status HELD, got {held['checkin_status']}"
    )
    assert held["held_at"].startswith("2026-08-19T00:00:00"), (
        f"Expected held_at stamped at 2026-08-19T00:00:00Z, got {held['held_at']}"
    )
    assert held["variance_hours"] == pytest.approx(0.00, abs=0.01), (
        f"Expected variance_hours 0.00, got {held['variance_hours']}"
    )
    assert held["escalation_raised"] is False, (
        f"Expected escalation_raised false, got {held['escalation_raised']}"
    )


# ---------------------------------------------------------------------------
# The pinned scope's authorship gates the review round
# ---------------------------------------------------------------------------
def _submitted_for_review():
    """A cleanly delivered engagement in `SUBMITTED`, whose pinned revision was authored by
    the roster's scoping specialist."""
    return setup_submitted_engagement(
        skill_code="LEGAL_CONTRACTS",
        deliverables=LEASE_SCHEDULE,
        time_logs=MIXED_CLASS_LOGS,
        reported_cumulative_hours=12.75,
        title="Lease portfolio diligence",
    )


def test_07_the_author_of_the_pinned_scope_cannot_open_the_review_round(api):
    """PRD §3.8: "Opening is barred to an operator whose identifier equals the
    `authored_by_user_id` of the engagement's pinned revision, and to an operator other than
    the one who owned a prior round on the same engagement; either bar answers
    `ERR_SEGREGATION_OF_DUTIES`."
    PRD §2.12: "Segregation of duties holds — `ERR_SEGREGATION_OF_DUTIES` (403) — on
    `POST /engagements/{id}/quality-reviews` and `POST /quality-reviews/{id}/decide`."

    Design: Difficulty/cross_entity_state_dependency/pinned_scope_authorship_gates_quality_review_open
    """
    world = _submitted_for_review()
    assert read_engagement(world)["work_status"] == "SUBMITTED", (
        "Setup expected the exact from-state SUBMITTED so only the identity rung can fire"
    )
    author_as_reviewer = make_quality_reviewer_headers(user_id=world["spec_user_id"])

    response = api_client.create_quality_review(
        world["engagement"]["id"], author_as_reviewer
    )

    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    body = response.json()
    assert body["data"]["error_id"] != ApiErrorId.ERR_INVALID_WORK_STATE.value, (
        "The engagement is SUBMITTED, exactly what the endpoint requires"
    )
    assert body["data"]["error_id"] != ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, (
        "QualityReviewer is a permitted role on this endpoint"
    )
    rows, _meta = validate_paginated(
        api_client.list_quality_reviews(
            world["engagement"]["id"], world["pm_headers"]
        )
    )
    assert rows == [], f"Expected no review round to survive the refusal, got {rows}"
    assert read_engagement(world)["work_status"] == "SUBMITTED", (
        f"Expected work_status still SUBMITTED, got "
        f"{read_engagement(world)['work_status']}"
    )


def test_08_a_reviewer_who_did_not_author_the_scope_opens_the_round(api):
    """PRD §3.8: "A `QualityReviewer` opens a review round on an engagement that has reached
    `SUBMITTED`."
    PRD §3.8: "The new review is created in `status` `OPEN` with a `round_no` one greater
    than the highest among its siblings on that engagement, a `reviewer_user_id` recording
    the opening operator's `X-User-ID`, a `scored_deliverable_count` of 0, a null
    `weighted_score`, an `outcome` of `PENDING`, and null `rework_deadline_at` and
    `decided_at`."

    Design: Difficulty/cross_entity_state_dependency/pinned_scope_authorship_gates_quality_review_open
    """
    world = _submitted_for_review()
    validate_error(
        api_client.create_quality_review(
            world["engagement"]["id"],
            make_quality_reviewer_headers(user_id=world["spec_user_id"]),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )

    review = validate_success(
        api_client.create_quality_review(
            world["engagement"]["id"], world["reviewer_headers"]
        ),
        201,
    )
    assert review["status"] == "OPEN", (
        f"Expected the round OPEN, got {review['status']}"
    )
    assert review["round_no"] == 1, (
        f"Expected round_no 1, got {review['round_no']}"
    )
    assert review["reviewer_user_id"] == world["reviewer_user_id"], (
        f"Expected reviewer_user_id {world['reviewer_user_id']}, got "
        f"{review['reviewer_user_id']}"
    )
    assert review["outcome"] == "PENDING", (
        f"Expected outcome PENDING, got {review['outcome']}"
    )


# ---------------------------------------------------------------------------
# Two ancestors the request merely points at: its cycle and its partner
# ---------------------------------------------------------------------------
def _single_slot_world():
    """A one-slot cycle whose single slot is already held by an `OFFERED` offer on request
    A, plus a second request that is match-ready in every respect of its own."""
    world = setup_offer(
        cycle_slots=1,
        skill_code="LEGAL_CONTRACTS",
        deliverables=LEASE_SCHEDULE,
        title="First lease tranche",
    )
    world["second"] = add_scoped_request(
        world,
        skill_code="LEGAL_CONTRACTS",
        urgency="CRITICAL",
        deliverables=LEASE_SCHEDULE,
        title="Second lease tranche",
    )
    return world


def test_09_a_frozen_cycle_refuses_a_match_that_is_otherwise_flawless(api):
    """PRD §2.12: "The cycle's `posture` is not `FROZEN` — on
    `POST /project-requests/{id}/match` and `POST /match-offers/{id}/accept` — otherwise
    `ERR_CYCLE_CAPACITY_FROZEN` (409)."
    PRD §3.1: "`posture` is `OPEN` while utilization is below 0.8000, `RESTRICTED` from
    0.8000 up to but not including 1.0000, and `FROZEN` at 1.0000 and above; both band
    floors are inclusive, so a utilization of exactly 0.8000 is `RESTRICTED` and exactly
    1.0000 is `FROZEN`."

    Design: Difficulty/cross_entity_state_dependency/frozen_cycle_posture_and_suspended_partner_block_new_commitments
    """
    world = _single_slot_world()
    second_id = world["second"]["request"]["id"]

    cycle = read_cycle(world)
    assert cycle["slots_committed"] == 0, (
        f"Expected slots_committed 0, got {cycle['slots_committed']}"
    )
    assert cycle["slots_reserved"] == 1, (
        f"Expected slots_reserved 1 from the single OFFERED hold, got "
        f"{cycle['slots_reserved']}"
    )
    assert cycle["slots_available"] == 0, (
        f"Expected slots_available 0, got {cycle['slots_available']}"
    )
    assert cycle["utilization_ratio"] == pytest.approx(1.0000, abs=1e-4), (
        f"Expected utilization_ratio exactly 1.0000, got {cycle['utilization_ratio']}"
    )
    assert cycle["posture"] == "FROZEN", (
        f"Expected posture FROZEN, got {cycle['posture']}"
    )

    response = api_client.match_project_request(second_id, world["spec_headers"])

    validate_error(response, ApiErrorId.ERR_CYCLE_CAPACITY_FROZEN)
    body = response.json()
    for excluded in (
        ApiErrorId.ERR_INVALID_REQUEST_STATE,
        ApiErrorId.ERR_PARTNER_SUSPENDED,
        ApiErrorId.ERR_CYCLE_RESTRICTED_URGENCY,
        ApiErrorId.ERR_PARTNER_ENGAGEMENT_LIMIT,
        ApiErrorId.ERR_AVAILABILITY_HOURS_EXCEEDED,
        ApiErrorId.ERR_NO_ELIGIBLE_VOLUNTEER,
    ):
        assert body["data"]["error_id"] != excluded.value, (
            f"The request is match-ready on its own terms, so {excluded.value} must not "
            f"be the answer"
        )

    offers, _meta = validate_paginated(
        api_client.list_match_offers(world["pm_headers"])
    )
    assert len(offers) == 1, (
        f"Expected only the pre-existing offer to exist, got {len(offers)}"
    )
    assert offers[0]["status"] == "OFFERED", (
        f"Expected the surviving offer still OFFERED, got {offers[0]['status']}"
    )
    engagements, _meta = validate_paginated(
        api_client.list_engagements(world["pm_headers"])
    )
    assert engagements == [], (
        f"A refused match creates no engagement, got {engagements}"
    )
    refused = get_success_data(
        api_client.get_project_request(second_id, world["pm_headers"])
    )
    assert refused["status"] == "SCOPED", (
        f"Expected the request still SCOPED, got {refused['status']}"
    )
    assert refused["failed_match_rounds"] == 0, (
        f"A refusal at the posture rung is not a failed match round, got "
        f"{refused['failed_match_rounds']}"
    )
    assert read_window(world)["hours_committed"] == pytest.approx(40.00, abs=0.01), (
        f"Expected the window ledger untouched at 40.00, got "
        f"{read_window(world)['hours_committed']}"
    )


def test_10_withdrawing_a_sibling_offer_thaws_the_cycle_for_the_replay(api):
    """PRD §3.5: "The offer moves `OFFERED → WITHDRAWN` with `responded_at` and the reason
    stamped, and the same hour and slot releases run."
    PRD §3.5: "Matching is a `ScopingSpecialist` action on a `SCOPED` request, and it moves
    the request `SCOPED → MATCHING` while producing exactly one offer for exactly one
    volunteer."

    Design: Difficulty/cross_entity_state_dependency/frozen_cycle_posture_and_suspended_partner_block_new_commitments
    """
    world = _single_slot_world()
    second_id = world["second"]["request"]["id"]
    validate_error(
        api_client.match_project_request(second_id, world["spec_headers"]),
        ApiErrorId.ERR_CYCLE_CAPACITY_FROZEN,
    )

    withdrawn = validate_success(
        api_client.withdraw_match_offer(world["offer"]["id"], world["spec_headers"])
    )
    assert withdrawn["status"] == "WITHDRAWN", (
        f"Expected the sibling offer WITHDRAWN, got {withdrawn['status']}"
    )
    cycle = read_cycle(world)
    assert cycle["slots_reserved"] == 0, (
        f"Expected slots_reserved 0 after the release, got {cycle['slots_reserved']}"
    )
    assert cycle["utilization_ratio"] == pytest.approx(0.0000, abs=1e-4), (
        f"Expected utilization_ratio 0.0000, got {cycle['utilization_ratio']}"
    )
    assert cycle["posture"] == "OPEN", (
        f"Expected posture OPEN, got {cycle['posture']}"
    )

    offer = validate_success(
        api_client.match_project_request(second_id, world["spec_headers"]), 201
    )
    assert offer["status"] == "OFFERED", (
        f"Expected the new offer OFFERED, got {offer['status']}"
    )
    assert offer["project_request_id"] == second_id, (
        f"Expected the offer to belong to the replayed request, got "
        f"{offer['project_request_id']}"
    )
    matched = get_success_data(
        api_client.get_project_request(second_id, world["pm_headers"])
    )
    assert matched["status"] == "MATCHING", (
        f"Expected the request MATCHING, got {matched['status']}"
    )


def test_11_a_suspended_partner_refuses_a_brand_new_request(api):
    """PRD §3.2: "The transition stamps `suspended_at` from the logical clock; every project
    request of that partner sitting in `DRAFT`, `SCOPING`, `SCOPED`, `MATCHING` or
    `RESCOPING` moves to `ABANDONED`; each abandoned request in turn moves its `OFFERED`
    match offers to `WITHDRAWN` with `withdraw_reason` set to `PARTNER_SUSPENDED`; each such
    withdrawal subtracts that offer's `reserved_hours` from the holding window's
    `hours_committed` and forces the cycle's `slots_reserved` to be recomputed; and every
    engagement of that partner whose `work_status` is `NOT_STARTED`, `IN_PROGRESS`,
    `SUBMITTED` or `ACCEPTED` moves to `TERMINATED` with `termination_reason` set to
    `PARTNER_SUSPENDED`."
    PRD §3.3: "Filing against a suspended partner is refused with `ERR_PARTNER_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/frozen_cycle_posture_and_suspended_partner_block_new_commitments
    """
    world = _single_slot_world()
    second_id = world["second"]["request"]["id"]
    get_success_data(
        api_client.withdraw_match_offer(world["offer"]["id"], world["spec_headers"])
    )
    second_offer = get_success_data(
        api_client.match_project_request(second_id, world["spec_headers"])
    )

    suspended = validate_success(
        api_client.patch_partner_org_status(
            world["partner"]["id"], {"to_status": "SUSPENDED"}, world["pm_headers"]
        )
    )
    assert suspended["status"] == "SUSPENDED", (
        f"Expected the partner SUSPENDED, got {suspended['status']}"
    )
    abandoned = get_success_data(
        api_client.get_project_request(second_id, world["pm_headers"])
    )
    assert abandoned["status"] == "ABANDONED", (
        f"The cascade abandons the matching request, got {abandoned['status']}"
    )
    swept = get_success_data(
        api_client.get_match_offer(second_offer["id"], world["pm_headers"])
    )
    assert swept["status"] == "WITHDRAWN", (
        f"Expected the open offer WITHDRAWN, got {swept['status']}"
    )
    assert swept["withdraw_reason"] == "PARTNER_SUSPENDED", (
        f"Expected withdraw_reason PARTNER_SUSPENDED, got {swept['withdraw_reason']}"
    )
    assert read_window(world)["hours_committed"] == pytest.approx(0.00, abs=0.01), (
        f"Expected the released window ledger at 0.00, got "
        f"{read_window(world)['hours_committed']}"
    )
    cycle = read_cycle(world)
    assert cycle["slots_reserved"] == 0, (
        f"Expected slots_reserved 0, got {cycle['slots_reserved']}"
    )
    assert cycle["posture"] == "OPEN", (
        f"The cycle is back to OPEN, so the posture rung cannot be the cause, got "
        f"{cycle['posture']}"
    )

    response = api_client.create_project_request(
        project_request_payload(
            world["partner"]["id"],
            world["cycle"]["id"],
            title="Third lease tranche",
            discipline="LEGAL",
            required_skill_code="LEGAL_CONTRACTS",
        ),
        world["partner_headers"],
    )

    validate_error(response, ApiErrorId.ERR_PARTNER_SUSPENDED)
    body = response.json()
    for excluded in (
        ApiErrorId.ERR_VALIDATION,
        ApiErrorId.ERR_PARTNER_ORG_NOT_FOUND,
        ApiErrorId.ERR_PROGRAM_CYCLE_NOT_FOUND,
        ApiErrorId.ERR_CYCLE_CAPACITY_FROZEN,
        ApiErrorId.ERR_CYCLE_RESTRICTED_URGENCY,
    ):
        assert body["data"]["error_id"] != excluded.value, (
            f"The payload is complete and both foreign keys resolve, so {excluded.value} "
            f"must not be the answer"
        )
    rows, _meta = validate_paginated(
        api_client.list_project_requests(world["pm_headers"])
    )
    assert len(rows) == 2, (
        f"Expected only the two pre-existing requests to exist, got {len(rows)}"
    )
