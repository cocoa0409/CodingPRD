"""Status transitions across the conservation register.

Every row in this system starts in a declared state, accepts a named trigger only
from the source states the contract declares for it, and commits a fixed set of
side effects when that trigger fires.  These tests walk the accepted hops of the
survey, visit, proposal, allocation, consultation, notice, case and incident
lifecycles, and confirm that a trigger fired from any other state is refused with
that entity's own conflict code while every counter stays where it was.
"""

from datetime import datetime

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_no_version_change,
    assert_pool_availability_identity,
)
from test_helpers.constants import TEST_DEFAULTS
from test_helpers.test_users import (
    COMMISSION_MEMBER_USER_IDS,
    SURVEYOR_USER_ID,
    TEST_USERS,
    make_artist_representative_headers,
    make_commission_member_headers,
    make_conservator_vendor_headers,
)


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating optional fractional seconds."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_freshly_created_rows_start_in_their_declared_initial_states(api):
    """PRD §3.2: "A freshly opened survey has `photo_count` at zero, an empty
    `photo_view_codes`, a null `condition_index` and a `recommendation` of `NONE`."
    PRD §3.3: "A visit that has never been aborted keeps `abort_reason` at `NONE`."
    PRD §3.10: "A successful reservation is created in `RESERVED` with
    `release_reason` of `NONE` and `released_at` null, lowers the pool's
    `available_cents` by `amount_cents`, and increments the pool's own `version` —
    which is what makes a second reservation from a stale read fail."
    PRD §3.11: "The incident is created with `damage_status` of `REPORTED`,
    `claim_status` of `NONE`, `triage_class` of `NONE`, `claim_basis` of `NONE`,
    both `claimed_gross_cents` and `settlement_cents` at zero, and `reported_at`
    stamped from the logical clock."
    PRD §3.6: "Creation stamps `sent_on` with the logical clock's calendar date and
    derives `due_at` by advancing the logical clock by the artist's
    `consultation_response_days`."
    PRD §3.6: "Creation stamps `sent_at` from the logical clock, derives
    `earliest_action_at` by advancing that instant by the artist's
    `notice_wait_days`, sets `status` to `SENT`, leaves `acknowledged_at` and
    `consumed_by_ref` null, and raises the work's `open_notice_count` by one — that
    counter being maintained as the number of the work's notices sitting in `SENT`,
    `ACKNOWLEDGED` or `WAIT_ELAPSED`."
    PRD §3.8: "The case is created in `INITIATED` with `initiated_by_user_id`
    stamped from the acting `X-User-ID`, an empty `vote_records`, all four ballot
    counters at zero and `decision_ratio` null."
    PRD §2.7: "A newly accessioned work begins `ON_VIEW` and `MONITORED`."

    Design: Corner/state_machines/every_new_row_starts_in_its_declared_initial_state
    """
    register = fixtures.setup_register(api)
    artwork_id = register["artwork"]["id"]
    artist_id = register["artist"]["id"]
    protocol = fixtures.create_protocol(api)
    conservator = fixtures.create_conservator(api)
    pool = fixtures.create_pool(api)

    survey = validate_success(
        api.create_condition_assessment(
            factories.condition_assessment_payload(artwork_id),
            TEST_USERS["surveyor_headers"],
        ),
        201,
    )
    assert survey["status"] == "DRAFT"
    assert survey["photo_count"] == 0
    assert survey["photo_view_codes"] == []
    assert survey["condition_index"] is None
    assert survey["recommendation"] == "NONE"
    assert survey["revision_rounds"] == 0

    visit = validate_success(
        api.create_maintenance_visit(
            factories.maintenance_visit_payload(artwork_id, protocol["id"]),
            TEST_USERS["crew_headers"],
        ),
        201,
    )
    assert visit["status"] == "SCHEDULED"
    assert visit["abort_reason"] == "NONE"
    assert visit["started_at"] is None
    assert visit["completed_at"] is None
    assert visit["sla_deadline_at"] is None
    assert visit["sla_breached"] is False

    allocation = validate_success(
        api.create_funding_allocation(
            factories.funding_allocation_payload(
                pool["id"],
                pool["version"],
                purpose="MAINTENANCE",
                amount_cents=100_000,
                visit_id=visit["id"],
            ),
            TEST_USERS["finance_headers"],
        ),
        201,
    )
    assert allocation["status"] == "RESERVED"
    assert allocation["release_reason"] == "NONE"
    assert allocation["released_at"] is None

    incident = validate_success(
        api.create_damage_incident(
            factories.damage_incident_payload(
                artwork_id, incident_type="GRAFFITI", damage_extent_pct=0.10
            ),
            TEST_USERS["registrar_headers"],
        ),
        201,
    )
    assert incident["damage_status"] == "REPORTED"
    assert incident["claim_status"] == "NONE"
    assert incident["triage_class"] == "NONE"
    assert incident["claim_basis"] == "NONE"
    assert incident["claimed_gross_cents"] == 0
    assert incident["settlement_cents"] == 0

    consultation = validate_success(
        api.create_artist_consultation(
            factories.artist_consultation_payload(
                artwork_id, artist_id, subject="RELOCATION"
            ),
            TEST_USERS["chief_conservator_headers"],
        ),
        201,
    )
    assert consultation["status"] == "PENDING"
    assert consultation["responded_at"] is None
    assert consultation["sent_on"] == "2026-08-01"
    # The clock's default plus the artist's default 30 response days.
    assert _instant(consultation["due_at"]) == _instant("2026-08-31T00:00:00Z")

    notice = validate_success(
        api.create_moral_rights_notice(
            factories.moral_rights_notice_payload(artwork_id, artist_id),
            TEST_USERS["manager_headers"],
        ),
        201,
    )
    assert notice["status"] == "SENT"
    assert notice["acknowledged_at"] is None
    assert notice["consumed_by_ref"] is None
    assert _instant(notice["sent_at"]) == _instant("2026-08-01T00:00:00Z")
    # The clock's default plus the artist's default 90 notice wait days.
    assert _instant(notice["earliest_action_at"]) == _instant("2026-10-30T00:00:00Z")

    case = validate_success(
        api.create_deaccession_case(
            factories.deaccession_case_payload(
                artwork_id,
                criteria=["LACK_OF_RELEVANCE"],
                disposition="RETURN_TO_ARTIST",
            ),
            TEST_USERS["manager_headers"],
        ),
        201,
    )
    assert case["status"] == "INITIATED"
    assert case["vote_records"] == []
    assert case["approve_count"] == 0
    assert case["deny_count"] == 0
    assert case["abstain_count"] == 0
    assert case["recuse_count"] == 0
    assert case["decision_ratio"] is None
    assert case["public_comment_closes_at"] is None

    assert conservator["status"] == "ACTIVE"
    assert conservator["active_engagement_count"] == 0

    work = fixtures.read_artwork(api, artwork_id)
    assert work["custody_status"] == "ON_VIEW"
    assert work["conservation_status"] == "MONITORED"
    assert work["open_notice_count"] == 1


def test_survey_review_triggers_from_the_wrong_source_state_are_refused(api):
    """PRD §3.2: "Submission moves the survey to `SUBMITTED`, from `DRAFT` on the
    first pass and from `REVISION_REQUESTED` on any later pass, and may carry an
    optional `surveyor_note`."
    PRD §3.2: "Review belongs to the `ChiefConservator`, who may send a `SUBMITTED`
    survey back with a mandatory `reviewer_note`, moving it
    `SUBMITTED → REVISION_REQUESTED` and increasing `revision_rounds` by one."
    PRD §3.2: "Finalization is the `ChiefConservator`'s act, carries an optional
    `finalization_note`, and moves the survey `SUBMITTED → FINALIZED`."
    PRD §2.8: "The state precondition of the requested transition, returning the
    target entity's own code: `ERR_ASSESSMENT_INVALID_STATE`,
    `ERR_PROPOSAL_INVALID_STATE`, `ERR_VISIT_INVALID_STATE`,
    `ERR_CASE_INVALID_STATE`, `ERR_NOTICE_INVALID_STATE`,
    `ERR_CONSULTATION_INVALID_STATE`, `ERR_ALLOCATION_INVALID_STATE`,
    `ERR_INCIDENT_INVALID_STATE` or `ERR_CLAIM_INVALID_STATE`."

    Design: Corner/state_machines/assessment_triggers_from_the_wrong_source_state_are_rejected
    """
    register = fixtures.setup_register(api)
    survey = fixtures.create_assessment(api, register["artwork"]["id"])
    fixtures.attach_photos(api, survey["id"])

    documented = fixtures.read_assessment(api, survey["id"])
    assert documented["status"] == "DRAFT"
    assert documented["photo_count"] == 3

    # Neither finalization nor a revision request is declared from DRAFT.
    validate_error(
        api.finalize_condition_assessment(
            survey["id"], {}, TEST_USERS["chief_conservator_headers"]
        ),
        ApiErrorId.ERR_ASSESSMENT_INVALID_STATE.value,
    )
    validate_error(
        api.request_assessment_revision(
            survey["id"],
            {"reviewer_note": "not yet submitted"},
            TEST_USERS["chief_conservator_headers"],
        ),
        ApiErrorId.ERR_ASSESSMENT_INVALID_STATE.value,
    )

    still_draft = fixtures.read_assessment(api, survey["id"])
    assert still_draft["status"] == "DRAFT"
    assert still_draft["revision_rounds"] == 0
    assert_no_version_change(documented, still_draft, "condition survey")

    submitted = validate_success(
        api.submit_condition_assessment(survey["id"], {}, TEST_USERS["surveyor_headers"])
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_by_user_id"] == SURVEYOR_USER_ID

    # Submission is declared from DRAFT and REVISION_REQUESTED only.
    validate_error(
        api.submit_condition_assessment(survey["id"], {}, TEST_USERS["surveyor_headers"]),
        ApiErrorId.ERR_ASSESSMENT_INVALID_STATE.value,
    )

    final = fixtures.read_assessment(api, survey["id"])
    assert final["status"] == "SUBMITTED"
    assert final["revision_rounds"] == 0
    assert final["version"] == documented["version"] + 1


def test_visit_completion_and_case_execution_outside_their_source_states_are_refused(api):
    """PRD §3.3: "Completing a visit, again a crew act with an optional
    `completion_note`, moves it `IN_PROGRESS → COMPLETED`."
    PRD §3.8: "Balloting is open to `ArtCommissionMember` and `PublicArtManager` and
    happens while the case sits in `BOARD_REVIEW`."
    PRD §3.8: "Execution is the manager's final act, carries an optional
    `execution_note` and moves the case `APPROVED → EXECUTED`, stamping
    `executed_at` from the logical clock."

    Design: Corner/state_machines/visit_and_case_triggers_outside_their_source_states_are_rejected
    """
    state = fixtures.setup_scheduled_visit(api)
    case = fixtures.open_case(api, state["artwork"]["id"])
    assert state["visit"]["status"] == "SCHEDULED"
    assert case["status"] == "INITIATED"

    validate_error(
        api.complete_maintenance_visit(
            state["visit"]["id"], {}, TEST_USERS["crew_headers"]
        ),
        ApiErrorId.ERR_VISIT_INVALID_STATE.value,
    )
    validate_error(
        api.execute_deaccession_case(case["id"], {}, TEST_USERS["manager_headers"]),
        ApiErrorId.ERR_CASE_INVALID_STATE.value,
    )
    validate_error(
        api.cast_deaccession_ballot(
            case["id"],
            {"ballot": "APPROVE"},
            make_commission_member_headers(COMMISSION_MEMBER_USER_IDS[0]),
        ),
        ApiErrorId.ERR_CASE_INVALID_STATE.value,
    )

    visit = fixtures.read_visit(api, state["visit"]["id"])
    assert visit["status"] == "SCHEDULED"
    assert visit["completed_at"] is None
    assert_no_version_change(state["visit"], visit, "maintenance visit")

    unchanged_case = fixtures.read_case(api, case["id"])
    assert unchanged_case["status"] == "INITIATED"
    assert unchanged_case["executed_at"] is None
    assert unchanged_case["approve_count"] == 0
    assert unchanged_case["vote_records"] == []

    assert fixtures.read_artwork(api, state["artwork"]["id"])["custody_status"] == "ON_VIEW"
    site = fixtures.read_site(api, state["site"]["id"])
    assert site["installed_units_used"] == TEST_DEFAULTS["FOOTPRINT_UNITS"]


def test_one_shot_transitions_are_refused_on_their_second_attempt(api):
    """PRD §3.6: "The artist's representative may acknowledge it, moving
    `SENT → ACKNOWLEDGED` with an optional `acknowledgement_note` and stamping
    `acknowledged_at`; this is permitted only from `SENT`, only by the artist named
    on the notice, and an attempt from any other status draws
    `ERR_NOTICE_INVALID_STATE`."
    PRD §3.6: "`CONCURRED`, `OBJECTED`, `LAPSED` and `WAIVED` are all terminal."
    PRD §3.10: "A `FinanceOfficer` may release an allocation directly, with an
    optional `release_note`, but only while it sits in `RESERVED`; an attempt
    against any other status draws `ERR_ALLOCATION_INVALID_STATE`."
    PRD §2.7: "When a requested move is not declared for the current value of the
    dimension it targets, the rejection names the dimension:
    `ERR_INCIDENT_INVALID_STATE` for the damage dimension and
    `ERR_CLAIM_INVALID_STATE` for the insurance dimension."
    PRD §3.11: "Resolution is again the `FinanceOfficer`'s act and requires
    `claim_status` to be `FILED`."
    PRD §3.11: "On settlement the named pool's `recovery_credits_cents` rises by
    `settlement_cents` and its `available_cents` rises by the same amount, and the
    pool's `version` increments — which is exactly the kind of unrequested movement
    that makes the pool version check in §2.11 necessary."

    Design: Corner/state_machines/repeating_a_consumed_trigger_is_rejected_on_the_second_attempt
    """
    register = fixtures.setup_register(api)
    artwork_id = register["artwork"]["id"]
    artist_id = register["artist"]["id"]
    artist_headers = make_artist_representative_headers(artist_id)

    pool = fixtures.create_pool(api)
    protocol = fixtures.create_protocol(api)
    visit = fixtures.schedule_visit(api, artwork_id, protocol["id"])
    allocation = fixtures.reserve_allocation(
        api,
        pool["id"],
        purpose="MAINTENANCE",
        amount_cents=200_000,
        visit_id=visit["id"],
    )
    consultation = fixtures.open_consultation(
        api, artwork_id, artist_id, subject="RELOCATION"
    )
    notice = fixtures.send_notice(api, artwork_id, artist_id)
    incident = fixtures.report_incident(api, artwork_id)

    acknowledged = validate_success(
        api.acknowledge_moral_rights_notice(notice["id"], {}, artist_headers)
    )
    assert acknowledged["status"] == "ACKNOWLEDGED"
    validate_error(
        api.acknowledge_moral_rights_notice(notice["id"], {}, artist_headers),
        ApiErrorId.ERR_NOTICE_INVALID_STATE.value,
    )

    concurred = validate_success(
        api.respond_to_consultation(
            consultation["id"], {"response": "CONCUR"}, artist_headers
        )
    )
    assert concurred["status"] == "CONCURRED"
    validate_error(
        api.respond_to_consultation(
            consultation["id"], {"response": "OBJECT"}, artist_headers
        ),
        ApiErrorId.ERR_CONSULTATION_INVALID_STATE.value,
    )

    released = validate_success(
        api.release_funding_allocation(
            allocation["id"], {}, TEST_USERS["finance_headers"]
        )
    )
    assert released["status"] == "RELEASED"
    assert released["release_reason"] == "MANUAL_RELEASE"
    validate_error(
        api.release_funding_allocation(
            allocation["id"], {}, TEST_USERS["finance_headers"]
        ),
        ApiErrorId.ERR_ALLOCATION_INVALID_STATE.value,
    )

    triaged = validate_success(
        api.triage_damage_incident(
            incident["id"],
            {"triage_class": "CONSERVATOR_TREATMENT"},
            TEST_USERS["chief_conservator_headers"],
        )
    )
    assert triaged["damage_status"] == "TRIAGED"
    validate_error(
        api.triage_damage_incident(
            incident["id"],
            {"triage_class": "ROUTINE_MAINTENANCE"},
            TEST_USERS["chief_conservator_headers"],
        ),
        ApiErrorId.ERR_INCIDENT_INVALID_STATE.value,
    )

    fixtures.file_claim(api, incident["id"], "ACV", credited_pool_id=pool["id"])
    settled = validate_success(
        api.resolve_insurance_claim(
            incident["id"], {"outcome": "SETTLE"}, TEST_USERS["finance_headers"]
        )
    )
    assert settled["claim_status"] == "SETTLED"
    assert settled["settlement_cents"] > 0
    validate_error(
        api.resolve_insurance_claim(
            incident["id"], {"outcome": "DENY"}, TEST_USERS["finance_headers"]
        ),
        ApiErrorId.ERR_CLAIM_INVALID_STATE.value,
    )

    # Each refused retry left the winning outcome and its side effect in place.
    assert fixtures.read_notice(api, notice["id"])["status"] == "ACKNOWLEDGED"
    assert fixtures.read_consultation(api, consultation["id"])["status"] == "CONCURRED"
    final_allocation = fixtures.read_allocation(api, allocation["id"])
    assert final_allocation["status"] == "RELEASED"
    assert final_allocation["release_reason"] == "MANUAL_RELEASE"

    final_incident = fixtures.read_incident(api, incident["id"])
    assert final_incident["triage_class"] == "CONSERVATOR_TREATMENT"
    assert final_incident["claim_status"] == "SETTLED"
    assert final_incident["settlement_cents"] == settled["settlement_cents"]

    final_pool = fixtures.read_pool(api, pool["id"])
    assert final_pool["recovery_credits_cents"] == settled["settlement_cents"]
    # The released allocation is no longer an encumbrance, and the settlement was
    # credited exactly once.
    assert_pool_availability_identity(final_pool, 0)


def test_treatment_completion_applies_every_side_effect_and_then_locks_the_proposal(api):
    """PRD §3.5: "Completion, also the vendor's act, carries a mandatory
    `completion_report_ref` and moves the proposal `IN_EXECUTION → COMPLETED`."
    PRD §3.5: "The work's custody returns `IN_TREATMENT → ON_VIEW` and its
    conservation dimension moves `TREATMENT_IN_PROGRESS → STABILIZED`."
    PRD §3.5: "Its `treatment_priority_score` and `treatment_priority_rank` are
    cleared to null and its `priority_basis` returns to `NONE`, after which the
    ranks of the remaining cohort are recomputed."
    PRD §3.5: "The proposal's `COMMITTED` allocation moves to `DISBURSED`, the
    conservator's `active_engagement_count` falls by one, and every damage incident
    whose `linked_proposal_id` names this proposal and whose `damage_status` is
    `TRIAGED` moves `TRIAGED → RESOLVED`."
    PRD §3.5: "`COMPLETED`, `REJECTED` and `WITHDRAWN` are terminal for a proposal."
    PRD §3.5: "The site's `installed_units_used` is deliberately left unchanged,
    because a work under treatment still occupies its site."

    Design: Corner/state_machines/treatment_execution_applies_every_declared_side_effect_and_then_locks_down
    """
    state = fixtures.setup_approved_proposal(api)
    artwork_id = state["artwork"]["id"]
    proposal_id = state["proposal"]["id"]
    conservator_id = state["conservator"]["id"]
    vendor_headers = make_conservator_vendor_headers(conservator_id)

    incident = fixtures.setup_incident_triaged(
        api, artwork_id, linked_proposal_id=proposal_id
    )
    assert incident["damage_status"] == "TRIAGED"

    index_before = fixtures.read_artwork(api, artwork_id)["condition_index"]
    in_execution = fixtures.start_execution(api, proposal_id, conservator_id)
    assert in_execution["status"] == "IN_EXECUTION"
    assert fixtures.read_artwork(api, artwork_id)["custody_status"] == "IN_TREATMENT"

    completed = validate_success(
        api.complete_treatment_proposal(
            proposal_id, {"completion_report_ref": "REPORT-2026-014"}, vendor_headers
        )
    )
    assert completed["status"] == "COMPLETED"
    assert (
        completed["pinned_estimate_total_cents"]
        == TEST_DEFAULTS["TWO_LINE_ESTIMATE_TOTAL_CENTS"]
    )
    assert completed["pinned_estimate_total_cents"] == completed["estimate_total_cents"]

    work = fixtures.read_artwork(api, artwork_id)
    assert work["custody_status"] == "ON_VIEW"
    assert work["conservation_status"] == "STABILIZED"
    assert work["treatment_priority_score"] is None
    assert work["treatment_priority_rank"] is None
    assert work["priority_basis"] == "NONE"
    assert work["condition_index"] == index_before

    allocation = fixtures.read_allocation(api, state["allocation"]["id"])
    assert allocation["status"] == "DISBURSED"
    pool = fixtures.read_pool(api, state["pool"]["id"])
    # A disbursed allocation is still an encumbrance against the pool.
    assert_pool_availability_identity(pool, allocation["amount_cents"])

    assert fixtures.read_conservator(api, conservator_id)["active_engagement_count"] == 0

    resolved = fixtures.read_incident(api, incident["id"])
    assert resolved["damage_status"] == "RESOLVED"
    assert resolved["claim_status"] == "NONE"

    site = fixtures.read_site(api, state["site"]["id"])
    assert site["installed_units_used"] == TEST_DEFAULTS["FOOTPRINT_UNITS"]

    # COMPLETED is terminal, so an immediate replay touches nothing.
    validate_error(
        api.complete_treatment_proposal(
            proposal_id,
            {"completion_report_ref": "REPORT-2026-014-RETRY"},
            vendor_headers,
        ),
        ApiErrorId.ERR_PROPOSAL_INVALID_STATE.value,
    )
    replayed = fixtures.read_proposal(api, proposal_id)
    assert replayed["status"] == "COMPLETED"
    assert_no_version_change(completed, replayed, "treatment proposal")
    assert fixtures.read_allocation(api, state["allocation"]["id"])["status"] == "DISBURSED"
    assert fixtures.read_incident(api, incident["id"])["damage_status"] == "RESOLVED"


def test_approving_one_proposal_supersedes_the_rival_proposal_on_the_same_work(api):
    """PRD §3.5: "Cascade C then runs: every other proposal on the same work
    sitting in `DRAFT`, `SUBMITTED` or `REVISION_REQUESTED` moves to `WITHDRAWN`
    with `withdraw_reason` set to `PROPOSAL_SUPERSEDED`; every `RESERVED` or
    `COMMITTED` allocation attached to those superseded proposals moves to
    `RELEASED` with `release_reason` set to `PROPOSAL_WITHDRAWN`; and each affected
    pool's `available_cents` is recomputed upward by the released amounts."
    PRD §3.5: "On success, `pinned_estimate_total_cents` freezes at the proposal's
    `estimate_total_cents` at that instant, which later becomes the basis of a
    restoration insurance claim, and `approved_by_user_id` records the acting user."
    PRD §3.5: "The engaged conservator's `active_engagement_count` rises by one."
    PRD §3.2: "Hop 1: every other survey on the same work that was sitting in
    `FINALIZED` moves `FINALIZED → SUPERSEDED`, so a work has at most one finalized
    survey at a time."

    Design: Corner/state_machines/approving_one_proposal_supersedes_the_rival_proposal_on_the_same_artwork
    """
    register = fixtures.setup_register(api)
    artwork_id = register["artwork"]["id"]
    conservator = fixtures.create_conservator(api)
    pool = fixtures.create_pool(api)

    first_survey = fixtures.setup_assessment_finalized(api, artwork_id)
    loser = fixtures.create_proposal_with_lines(
        api,
        artwork_id,
        conservator["id"],
        first_survey["id"],
        lines=[
            {"labor_hours": 10, "complexity_class": "STABILIZATION", "materials_cents": 0}
        ],
        treatment_scope="STABILIZATION",
        engagement_start="2026-09-01T00:00:00Z",
        engagement_end="2026-09-05T00:00:00Z",
    )
    loser_allocation = fixtures.reserve_allocation(
        api,
        pool["id"],
        purpose="TREATMENT",
        amount_cents=loser["estimate_total_cents"],
        proposal_id=loser["id"],
    )
    loser = fixtures.submit_proposal(api, loser["id"])
    assert loser["status"] == "SUBMITTED"

    # A second survey of the same work justifies a rival proposal.
    second_survey = fixtures.setup_assessment_finalized(
        api,
        artwork_id,
        surface_score=3,
        structural_score=2,
        coating_score=2,
        mount_score=2,
        graffiti_score=1,
    )
    winner = fixtures.create_proposal_with_lines(
        api,
        artwork_id,
        conservator["id"],
        second_survey["id"],
        lines=[
            {
                "labor_hours": 20,
                "complexity_class": "STRUCTURAL",
                "materials_cents": 50_000,
            }
        ],
        treatment_scope="STRUCTURAL",
        engagement_start="2026-10-01T00:00:00Z",
        engagement_end="2026-10-05T00:00:00Z",
    )
    winner_allocation = fixtures.reserve_allocation(
        api,
        pool["id"],
        purpose="TREATMENT",
        amount_cents=winner["estimate_total_cents"],
        proposal_id=winner["id"],
    )
    winner = fixtures.submit_proposal(api, winner["id"])

    pool_before = fixtures.read_pool(api, pool["id"])
    assert_pool_availability_identity(
        pool_before,
        loser_allocation["amount_cents"] + winner_allocation["amount_cents"],
    )

    approved = validate_success(
        api.approve_treatment_proposal(
            winner["id"],
            {"approval_note": "structural campaign wins"},
            TEST_USERS["manager_headers"],
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["pinned_estimate_total_cents"] == winner["estimate_total_cents"]

    superseded = fixtures.read_proposal(api, loser["id"])
    assert superseded["status"] == "WITHDRAWN"
    assert superseded["withdraw_reason"] == "PROPOSAL_SUPERSEDED"

    refunded = fixtures.read_allocation(api, loser_allocation["id"])
    assert refunded["status"] == "RELEASED"
    assert refunded["release_reason"] == "PROPOSAL_WITHDRAWN"
    assert fixtures.read_allocation(api, winner_allocation["id"])["status"] == "RESERVED"

    pool_after = fixtures.read_pool(api, pool["id"])
    assert_pool_availability_identity(pool_after, winner_allocation["amount_cents"])
    assert (
        pool_after["available_cents"]
        == pool_before["available_cents"] + loser_allocation["amount_cents"]
    )

    assert fixtures.read_assessment(api, first_survey["id"])["status"] == "SUPERSEDED"
    assert fixtures.read_assessment(api, second_survey["id"])["status"] == "FINALIZED"
    assert fixtures.read_conservator(api, conservator["id"])["active_engagement_count"] == 1


def test_rejecting_a_submitted_proposal_returns_its_reservation_to_the_pool(api):
    """PRD §3.4: "The manager may instead reject a `SUBMITTED` proposal with a
    mandatory `rejection_reason`, moving it `SUBMITTED → REJECTED`."
    PRD §3.4: "Rejection releases every funding allocation attached to the proposal
    that sits in `RESERVED` or `COMMITTED`, stamping `release_reason` as
    `PROPOSAL_REJECTED`, and the affected pool's `available_cents` rises
    accordingly."

    Design: Corner/state_machines/rejecting_a_submitted_proposal_returns_its_reservation_to_the_pool
    """
    state = fixtures.setup_submitted_proposal(api)
    proposal_id = state["proposal"]["id"]
    allocation = fixtures.reserve_allocation(
        api,
        state["pool"]["id"],
        purpose="TREATMENT",
        amount_cents=state["proposal"]["estimate_total_cents"],
        proposal_id=proposal_id,
    )

    pool_before = fixtures.read_pool(api, state["pool"]["id"])
    assert_pool_availability_identity(pool_before, allocation["amount_cents"])

    rejected = validate_success(
        api.reject_treatment_proposal(
            proposal_id,
            {"rejection_reason": "scope does not address the structural finding"},
            TEST_USERS["manager_headers"],
        )
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["pinned_estimate_total_cents"] is None

    released = fixtures.read_allocation(api, allocation["id"])
    assert released["status"] == "RELEASED"
    assert released["release_reason"] == "PROPOSAL_REJECTED"

    pool_after = fixtures.read_pool(api, state["pool"]["id"])
    assert_pool_availability_identity(pool_after, 0)
    assert pool_after["available_cents"] == pool_after["draw_authorized_cents"]
    assert (
        pool_after["available_cents"]
        == pool_before["available_cents"] + allocation["amount_cents"]
    )

    # Rejection never counted an engagement, and the work still needs treatment.
    assert (
        fixtures.read_conservator(api, state["conservator"]["id"])[
            "active_engagement_count"
        ]
        == 0
    )
    assert (
        fixtures.read_artwork(api, state["artwork"]["id"])["conservation_status"]
        == "TREATMENT_REQUIRED"
    )


def test_executing_a_deaccession_consumes_the_authorising_notice_and_voids_the_rest(api):
    """PRD §3.6: "When the action proceeds, the authorising notice is spent —
    moving `ACKNOWLEDGED → CONSUMED` where the artist had acknowledged it, or
    `WAIT_ELAPSED → CONSUMED` where the waiting period had simply run out — its
    `consumed_by_ref` records the identifier of the relocation or deaccession that
    used it, and the work's `open_notice_count` falls by one."
    PRD §3.6: "When Cascade B hop 2 runs, every notice on the departing work in
    `SENT`, `ACKNOWLEDGED` or `WAIT_ELAPSED` other than the one the execution
    consumed moves to `VOID`, each decrement lowering the work's
    `open_notice_count` by one."
    PRD §3.6: "Cascade B hop 2 also moves `PENDING` consultations to `LAPSED` when
    the work leaves the collection."
    PRD §3.8: "Hop 1: the work's `custody_status` becomes `DESTROYED` when the
    disposition is `DESTRUCTION` and `DEACCESSIONED` for `SALE`, `TRANSFER` or
    `RETURN_TO_ARTIST`, moving from `ON_VIEW` or from `IN_STORAGE` in either case;
    where the work was `ON_VIEW`, its site's `installed_units_used` falls by the
    work's `footprint_units`, and where it was already `IN_STORAGE` no site
    adjustment is needed because none was being consumed."

    Design: Corner/state_machines/executing_a_deaccession_consumes_one_notice_and_voids_the_others
    """
    register = fixtures.setup_register(api)
    artwork_id = register["artwork"]["id"]
    artist_id = register["artist"]["id"]

    removal_notice = fixtures.setup_acknowledged_notice(
        api, artwork_id, artist_id, action_type="REMOVAL"
    )
    assert removal_notice["status"] == "ACKNOWLEDGED"
    alteration_notice = fixtures.send_notice(
        api, artwork_id, artist_id, action_type="ALTERATION"
    )
    consultation = fixtures.open_consultation(
        api, artwork_id, artist_id, subject="DEACCESSION"
    )
    assert consultation["status"] == "PENDING"

    case = fixtures.setup_case_approved(
        api,
        artwork_id,
        criteria=["LACK_OF_RELEVANCE", "SITE_REDEVELOPMENT"],
        disposition="RETURN_TO_ARTIST",
    )
    assert case["status"] == "APPROVED"
    assert case["approve_count"] == 5

    before = fixtures.read_artwork(api, artwork_id)
    assert before["open_notice_count"] == 2
    assert before["moral_rights_status"] == "ACTIVE"
    # The notice matured 90 days after it was sent from the clock's default.
    assert _instant(removal_notice["earliest_action_at"]) == _instant(
        "2026-10-30T00:00:00Z"
    )

    fixtures.set_clock(api, "2026-11-01T00:00:00Z")
    executed = validate_success(
        api.execute_deaccession_case(
            case["id"],
            {"execution_note": "returned to the artist's studio"},
            TEST_USERS["manager_headers"],
        )
    )
    assert executed["status"] == "EXECUTED"
    assert _instant(executed["executed_at"]) == _instant("2026-11-01T00:00:00Z")

    work = fixtures.read_artwork(api, artwork_id)
    assert work["custody_status"] == "DEACCESSIONED"
    assert work["open_notice_count"] == 0
    assert fixtures.read_site(api, register["site"]["id"])["installed_units_used"] == 0

    consumed = fixtures.read_notice(api, removal_notice["id"])
    assert consumed["status"] == "CONSUMED"
    assert consumed["consumed_by_ref"] == case["id"]

    voided = fixtures.read_notice(api, alteration_notice["id"])
    assert voided["status"] == "VOID"
    assert voided["consumed_by_ref"] is None

    lapsed = fixtures.read_consultation(api, consultation["id"])
    assert lapsed["status"] == "LAPSED"
    assert lapsed["responded_at"] is None


def test_waived_moral_rights_stamp_the_consultation_and_clear_a_destruction(api):
    """PRD §3.6: "The row is created in `PENDING` — except where the work's
    `moral_rights_status` is `WAIVED` at creation time, in which case the row is
    stamped `WAIVED` immediately and `responded_at` stays null."
    PRD §3.6: "A consultation on a waived artist's work is therefore never
    observable in `PENDING`."
    PRD §3.8: "A ratio of 0.60 or above moves the case `BOARD_REVIEW → APPROVED`; a
    ratio below 0.60 — including that all-abstention case — moves it
    `BOARD_REVIEW → DENIED`."
    PRD §3.8: "A `DESTRUCTION` disposition may only execute when the work's
    `recognized_stature` is false; a protected work draws
    `ERR_RECOGNIZED_STATURE_PROTECTED`."

    Design: Corner/state_machines/waived_moral_rights_allow_destruction_and_stamp_consultations_waived_at_creation
    """
    register = fixtures.setup_register(
        api,
        artist={"moral_rights_waiver_on_file": True},
        artwork={"recognized_stature": False},
    )
    artwork_id = register["artwork"]["id"]
    assert fixtures.read_artwork(api, artwork_id)["moral_rights_status"] == "WAIVED"

    consultation = validate_success(
        api.create_artist_consultation(
            factories.artist_consultation_payload(
                artwork_id, register["artist"]["id"], subject="DEACCESSION"
            ),
            TEST_USERS["manager_headers"],
        ),
        201,
    )
    assert consultation["status"] == "WAIVED"
    assert consultation["responded_at"] is None

    case = fixtures.setup_case_at_board_review(
        api,
        artwork_id,
        criteria=["DETERIORATION_BEYOND_REPAIR", "PUBLIC_SAFETY_HAZARD"],
        disposition="DESTRUCTION",
    )
    assert case["status"] == "BOARD_REVIEW"

    # Three approvals against two denials is a ratio of exactly 0.60.
    tallied = fixtures.cast_ballots(
        api, case["id"], ["APPROVE", "APPROVE", "APPROVE", "DENY", "DENY"]
    )
    assert tallied["approve_count"] == 3
    assert tallied["deny_count"] == 2
    assert tallied["recuse_count"] == 0
    assert abs(tallied["decision_ratio"] - 0.60) < 1e-9
    assert tallied["status"] == "APPROVED"

    executed = validate_success(
        api.execute_deaccession_case(case["id"], {}, TEST_USERS["manager_headers"])
    )
    assert executed["status"] == "EXECUTED"

    destroyed = fixtures.read_artwork(api, artwork_id)
    assert destroyed["custody_status"] == "DESTROYED"
    assert fixtures.read_site(api, register["site"]["id"])["installed_units_used"] == 0

    # A waived work needed no statutory notice at any point.
    notices, meta = validate_paginated(
        api.list_moral_rights_notices(
            TEST_USERS["manager_headers"], params={"artwork_id": artwork_id}
        )
    )
    assert notices == []
    assert meta["total_count"] == 0


def test_graffiti_visit_completed_at_the_sla_deadline_is_compliant_and_rebases_the_cycle(
    api,
):
    """PRD §3.3: "When a visit is scheduled to clear a tag, the payload carries
    `graffiti_reported_at`, the instant the graffiti was reported, and the server
    derives `sla_deadline_at` by adding a response allowance chosen by the work's
    material: `MURAL_COATING` must be cleared within 48 hours, `PAINTED_STEEL`
    within three days, and both `BRONZE` and `STONE` within five days."
    PRD §3.3: "On success `completed_at` is stamped from the logical clock and the
    SLA is judged: where a deadline exists, `sla_breached` becomes true only when
    `completed_at` falls strictly after `sla_deadline_at`, so a crew that finishes
    at the deadline instant exactly is compliant."
    PRD §3.3: "The work's `last_maintenance_completed_on` becomes the calendar date
    of `completed_at`, its `next_maintenance_due_on` becomes that same date advanced
    by the completed protocol's `cycle_days`, and its `maintenance_applications_ytd`
    is recomputed as the number of its completed visits whose completion year
    matches the logical clock's year."
    PRD §3.3: "The count of visits at the same site whose `status` is `SCHEDULED` or
    `IN_PROGRESS` and whose window collides with the requested one must be strictly
    less than that site's `concurrent_work_capacity`; otherwise the request is
    refused with `ERR_SITE_WORK_CAPACITY_CONFLICT`."

    Design: Corner/state_machines/graffiti_visit_completion_at_the_sla_deadline_is_compliant_and_reschedules_the_cycle
    """
    state = fixtures.setup_scheduled_visit(
        api,
        protocol={
            "protocol_code": "GRAF-BR",
            "method": "GRAFFITI_REMOVAL",
            "cycle_days": 180,
            "solvent_class": "MILD",
        },
        visit={
            "window_start": "2026-08-05T08:00:00Z",
            "window_end": "2026-08-12T17:00:00Z",
            "graffiti_reported_at": "2026-08-06T09:00:00Z",
        },
    )
    artwork_id = state["artwork"]["id"]
    first = state["visit"]
    # BRONZE allows five days from the report instant.
    assert _instant(first["sla_deadline_at"]) == _instant("2026-08-11T09:00:00Z")
    assert first["sla_breached"] is False

    fixtures.set_clock(api, "2026-08-05T08:00:00Z")
    validate_success(
        api.start_maintenance_visit(first["id"], {}, TEST_USERS["crew_headers"])
    )

    fixtures.set_clock(api, "2026-08-11T09:00:00Z")
    completed = validate_success(
        api.complete_maintenance_visit(
            first["id"],
            {"completion_note": "tag removed at the deadline hour"},
            TEST_USERS["crew_headers"],
        )
    )
    assert completed["status"] == "COMPLETED"
    assert _instant(completed["completed_at"]) == _instant("2026-08-11T09:00:00Z")
    assert completed["sla_breached"] is False

    work = fixtures.read_artwork(api, artwork_id)
    assert work["last_maintenance_completed_on"] == "2026-08-11"
    assert work["next_maintenance_due_on"] == "2027-02-07"
    assert work["maintenance_applications_ytd"] == 1

    # The first visit's window still overlaps this one, but a COMPLETED visit no
    # longer counts against the site's concurrent work capacity.
    second = fixtures.schedule_visit(
        api,
        artwork_id,
        state["protocol"]["id"],
        window_start="2026-08-12T08:00:00Z",
        window_end="2026-08-13T17:00:00Z",
        graffiti_reported_at="2026-08-06T09:00:00Z",
    )
    assert second["status"] == "SCHEDULED"
    assert _instant(second["sla_deadline_at"]) == _instant("2026-08-11T09:00:00Z")

    fixtures.set_clock(api, "2026-08-12T08:00:00Z")
    validate_success(
        api.start_maintenance_visit(second["id"], {}, TEST_USERS["crew_headers"])
    )
    fixtures.set_clock(api, "2026-08-12T10:00:00Z")
    breached = validate_success(
        api.complete_maintenance_visit(second["id"], {}, TEST_USERS["crew_headers"])
    )
    assert breached["status"] == "COMPLETED"
    assert _instant(breached["completed_at"]) == _instant("2026-08-12T10:00:00Z")
    assert breached["sla_breached"] is True

    work = fixtures.read_artwork(api, artwork_id)
    assert work["last_maintenance_completed_on"] == "2026-08-12"
    assert work["next_maintenance_due_on"] == "2027-02-08"
    assert work["maintenance_applications_ytd"] == 2
    assert work["custody_status"] == "ON_VIEW"
    assert fixtures.read_visit(api, first["id"])["status"] == "COMPLETED"
