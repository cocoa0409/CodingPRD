"""The approval gate: consent, engagement exclusivity and the order they fire in.

Approving a treatment proposal commits a vendor, a schedule, a legal consent and
public money at once, so the gate reads the linked consultation's state, treats
the conservator's engagement window as half-open and buffered, and refuses on the
proposal's own state before it ever looks at the money.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_no_version_change, assert_treatment_proposal
from test_helpers.test_users import TEST_USERS


def _altering_proposal_with_money(api, **proposal_overrides):
    """A submitted, fully funded proposal that would change how the work looks."""
    state = fixtures.setup_submitted_proposal(
        api, proposal={"alters_appearance": True, **proposal_overrides}
    )
    state["allocation"] = fixtures.reserve_allocation(
        api,
        state["pool"]["id"],
        purpose="TREATMENT",
        amount_cents=700_000,
        proposal_id=state["proposal"]["id"],
    )
    assert state["proposal"]["estimate_total_cents"] == 683_269
    assert state["artwork"]["moral_rights_status"] == "ACTIVE"
    return state


def test_a_standing_objection_blocks_approval_and_touches_nothing(api):
    """PRD §3.5: "If it exists and is `OBJECTED`, the approval is refused with
    `ERR_ARTIST_OBJECTION_UNRESOLVED`."
    PRD §3.6: "An objection does not merely record displeasure — while the row stands
    in `OBJECTED`, the linked proposal cannot be approved."

    Design: Difficulty/cross_entity_state_dependency/proposal_approval_depends_on_artist_consultation_state
    """
    state = _altering_proposal_with_money(api)
    consultation = fixtures.open_consultation(
        api,
        state["artwork"]["id"],
        state["artist"]["id"],
        proposal_id=state["proposal"]["id"],
    )
    answered = fixtures.answer_consultation(
        api, consultation["id"], state["artist"]["id"], "OBJECT"
    )
    assert answered["status"] == "OBJECTED"

    refused = api.approve_treatment_proposal(
        state["proposal"]["id"],
        {"approval_note": "proceed despite the objection"},
        TEST_USERS["manager_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_ARTIST_OBJECTION_UNRESOLVED.value)

    # Nothing about the proposal, its money or its vendor may move: the blocker
    # lives entirely on the other entity.
    proposal = fixtures.read_proposal(api, state["proposal"]["id"])
    assert proposal["status"] == "SUBMITTED"
    assert proposal["pinned_estimate_total_cents"] is None
    assert fixtures.read_allocation(api, state["allocation"]["id"])["status"] == "RESERVED"
    assert fixtures.read_pool(api, state["pool"]["id"])["available_cents"] == 19_827_500
    assert (
        fixtures.read_conservator(api, state["conservator"]["id"])[
            "active_engagement_count"
        ]
        == 0
    )
    assert fixtures.read_consultation(api, consultation["id"])["status"] == "OBJECTED"


def test_a_lapsed_consultation_clears_the_consent_gate(api):
    """PRD §3.5: "Only `CONCURRED` or `LAPSED` clears the gate."
    PRD §3.6: "The cycle checkpoint moves every `PENDING` consultation whose `due_at`
    is at or before the logical clock to `LAPSED`, and a lapsed consultation clears
    the approval gate exactly as a concurrence does."
    PRD §3.5: "The engaged conservator's `active_engagement_count` rises by one."

    Design: Difficulty/cross_entity_state_dependency/proposal_approval_depends_on_artist_consultation_state
    """
    state = _altering_proposal_with_money(
        api,
        engagement_start="2026-10-01T00:00:00Z",
        engagement_end="2026-10-05T00:00:00Z",
    )
    consultation = fixtures.open_consultation(
        api,
        state["artwork"]["id"],
        state["artist"]["id"],
        proposal_id=state["proposal"]["id"],
    )
    assert consultation["status"] == "PENDING"

    # The artist never answers; the clock passes the 30-day response window and the
    # checkpoint records the silence.
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    validate_success(api.run_cycle({"cycle_year": 2026}, TEST_USERS["manager_headers"]))
    assert fixtures.read_consultation(api, consultation["id"])["status"] == "LAPSED"

    approved = validate_success(
        api.approve_treatment_proposal(
            state["proposal"]["id"],
            {"approval_note": "consultation lapsed unanswered"},
            TEST_USERS["manager_headers"],
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["pinned_estimate_total_cents"] == 683_269
    assert_treatment_proposal(approved)
    assert (
        fixtures.read_conservator(api, state["conservator"]["id"])[
            "active_engagement_count"
        ]
        == 1
    )


def _unfunded_draft(api):
    """A draft proposal with a full estimate and no funding anywhere in the system."""
    register = fixtures.setup_register(api)
    conservator = fixtures.create_conservator(api)
    assessment = fixtures.setup_assessment_finalized(api, register["artwork"]["id"])
    proposal = fixtures.create_proposal_with_lines(
        api, register["artwork"]["id"], conservator["id"], assessment["id"]
    )
    assert proposal["status"] == "DRAFT"
    assert proposal["estimate_total_cents"] == 683_269
    return proposal


def test_an_unsubmitted_proposal_fails_on_its_state_not_on_its_funding(api):
    """PRD §2.8: "Checks are evaluated in the following sequence, and the first one
    that fails ends the request:"
    PRD §2.8: "The state precondition of the requested transition, returning the
    target entity's own code: `ERR_ASSESSMENT_INVALID_STATE`,
    `ERR_PROPOSAL_INVALID_STATE`, `ERR_VISIT_INVALID_STATE`,
    `ERR_CASE_INVALID_STATE`, `ERR_NOTICE_INVALID_STATE`,
    `ERR_CONSULTATION_INVALID_STATE`, `ERR_ALLOCATION_INVALID_STATE`,
    `ERR_INCIDENT_INVALID_STATE` or `ERR_CLAIM_INVALID_STATE`."
    PRD §2.8: "Reserved funding covering an estimate at approval time —
    `ERR_FUNDING_NOT_RESERVED`."

    Design: Difficulty/priority_pair_validation_conflict/proposal_state_error_outranks_funding_not_reserved
    """
    proposal = _unfunded_draft(api)

    # Both the state check and the funding check would fail here, and the earlier
    # one in the sequence is the only answer the client may see.
    refused = api.approve_treatment_proposal(
        proposal["id"], {"approval_note": "approve early"}, TEST_USERS["manager_headers"]
    )
    body = validate_error(refused, ApiErrorId.ERR_PROPOSAL_INVALID_STATE.value)
    assert body["error_id"] != ApiErrorId.ERR_FUNDING_NOT_RESERVED.value

    after = fixtures.read_proposal(api, proposal["id"])
    assert after["status"] == "DRAFT"
    assert_no_version_change(proposal, after, "proposal")


def test_a_submitted_proposal_then_fails_on_the_absent_reservation(api):
    """PRD §3.5: "A funding allocation naming this proposal must exist in `RESERVED`
    status with an `amount_cents` greater than or equal to the proposal's current
    `estimate_total_cents`; otherwise the approval is refused with
    `ERR_FUNDING_NOT_RESERVED`."
    PRD §3.5: "It moves the proposal `SUBMITTED → APPROVED` and is the most heavily
    guarded operation in the system, because it commits an outside vendor, a
    schedule, a legal consent and public money in one act."

    Design: Difficulty/priority_pair_validation_conflict/proposal_state_error_outranks_funding_not_reserved
    """
    proposal = _unfunded_draft(api)
    submitted = fixtures.submit_proposal(api, proposal["id"])
    assert submitted["status"] == "SUBMITTED"

    # With the state precondition satisfied the money check is finally reachable,
    # which is what proves the first refusal was ordered ahead of it.
    refused = api.approve_treatment_proposal(
        proposal["id"], {}, TEST_USERS["manager_headers"]
    )
    validate_error(refused, ApiErrorId.ERR_FUNDING_NOT_RESERVED.value)

    after = fixtures.read_proposal(api, proposal["id"])
    assert after["status"] == "SUBMITTED"
    assert after["pinned_estimate_total_cents"] is None


def _second_work_awaiting_the_same_vendor(api, engagement_start, engagement_end):
    """Work A engaged 09-01 to 09-05, and work B queued behind it on one vendor."""
    state = fixtures.setup_approved_proposal(
        api, site={"concurrent_work_capacity": 2}, reserve_cents=700_000
    )
    assert state["proposal"]["status"] == "APPROVED"
    assert state["proposal"]["pinned_estimate_total_cents"] == 683_269

    work_b = fixtures.create_artwork(
        api,
        state["artist"]["id"],
        state["site"]["id"],
        accession_number="2024.002",
        title="Seated Figure",
        acquisition_document_ref="DEED-2014-002",
    )
    assessment_b = fixtures.setup_assessment_finalized(api, work_b["id"])
    proposal_b = fixtures.create_proposal_with_lines(
        api,
        work_b["id"],
        state["conservator"]["id"],
        assessment_b["id"],
        lines=[
            {
                "labor_hours": 4.0,
                "complexity_class": "SURFACE",
                "materials_cents": 5_000,
                "description": "wash and wax",
            }
        ],
        treatment_scope="SURFACE",
        engagement_start=engagement_start,
        engagement_end=engagement_end,
    )
    proposal_b = fixtures.submit_proposal(api, proposal_b["id"])
    # 4 hours at 14500 x 1.15 = 66700, plus 5000 of materials: subtotal 71700,
    # overhead 8246, contingency 5996, mobilization 45000, total 130942.
    assert proposal_b["estimate_total_cents"] == 130_942
    state["work_b"] = work_b
    state["proposal_b"] = proposal_b
    return state


def test_a_window_inside_the_forty_eight_hour_buffer_collides(api):
    """PRD §3.5: "A conservator's engagement windows are treated as **half-open**
    intervals — they include `engagement_start` and exclude `engagement_end` — and
    each is padded by a 48-hour mobilisation buffer on both sides."
    PRD §3.5: "A collision therefore exists with another proposal of the same
    conservator sitting in `APPROVED` or `IN_EXECUTION` exactly when this proposal's
    `engagement_start` falls before that proposal's `engagement_end` advanced by 48
    hours, and that proposal's `engagement_start` falls before this proposal's
    `engagement_end` advanced by 48 hours."

    Design: Difficulty/resource_temporal_overlap/conservator_engagement_half_open_window_with_48h_buffer
    """
    state = _second_work_awaiting_the_same_vendor(
        api, "2026-09-06T00:00:00Z", "2026-09-10T00:00:00Z"
    )

    # The raw intervals are disjoint — the second starts a day after the first ends —
    # but 2026-09-06 falls before 2026-09-05 advanced by 48 hours.
    refused = api.approve_treatment_proposal(
        state["proposal_b"]["id"],
        {"approval_note": "work B proceeds right after work A"},
        TEST_USERS["manager_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_CONSERVATOR_WINDOW_CONFLICT.value)

    blocked = fixtures.read_proposal(api, state["proposal_b"]["id"])
    assert blocked["status"] == "SUBMITTED"
    assert blocked["estimate_total_cents"] == 130_942
    assert blocked["pinned_estimate_total_cents"] is None
    assert fixtures.read_proposal(api, state["proposal"]["id"])["status"] == "APPROVED"
    assert (
        fixtures.read_conservator(api, state["conservator"]["id"])[
            "active_engagement_count"
        ]
        == 1
    )
    # Only work A's reservation was ever made, so the exclusivity check refused the
    # request before any funding rule was consulted.
    assert fixtures.read_pool(api, state["pool"]["id"])["available_cents"] == 19_827_500


def test_the_first_instant_clear_of_the_buffer_is_approvable(api):
    """PRD §3.5: "Any such collision yields `ERR_CONSERVATOR_WINDOW_CONFLICT`."
    PRD §3.5: "On success, `pinned_estimate_total_cents` freezes at the proposal's
    `estimate_total_cents` at that instant, which later becomes the basis of a
    restoration insurance claim, and `approved_by_user_id` records the acting user."

    Design: Difficulty/resource_temporal_overlap/conservator_engagement_half_open_window_with_48h_buffer
    """
    state = _second_work_awaiting_the_same_vendor(
        api, "2026-09-07T00:00:00Z", "2026-09-11T00:00:00Z"
    )
    fixtures.reserve_allocation(
        api,
        state["pool"]["id"],
        purpose="TREATMENT",
        amount_cents=200_000,
        proposal_id=state["proposal_b"]["id"],
    )

    # 2026-09-05 advanced by 48 hours is exactly 2026-09-07, and a start that does
    # not fall before that instant is the first one clear of the buffer.
    approved = validate_success(
        api.approve_treatment_proposal(
            state["proposal_b"]["id"], {}, TEST_USERS["manager_headers"]
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["pinned_estimate_total_cents"] == 130_942

    assert (
        fixtures.read_conservator(api, state["conservator"]["id"])[
            "active_engagement_count"
        ]
        == 2
    )
    assert fixtures.read_pool(api, state["pool"]["id"])["available_cents"] == 19_627_500
