"""Corner validation tests: OCC stale versions, envelope gate, extension caps,
uniqueness, resolution references, SoD, ballot window, side gating, ownership."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_agreement,
    create_clause,
    create_draft_agreement,
    create_employer_proposal_on_table,
    create_executed_side_letter,
    create_information_request_payload,
    create_interpreted_clause,
    create_locked_scenario,
    create_past_practice_payload,
    create_proposal_payload,
    create_ratification_vote_payload,
    create_reviewed_scenario,
    create_session,
    create_side_letter_payload,
    create_union,
    get_agreement_version,
    get_success_data,
    make_chief_negotiator_headers,
    make_legal_counsel_headers,
    make_negotiator_headers,
    make_union_representative_headers,
    setup_accepted_economic_package,
    setup_open_vote,
    validate_error,
)

ADMIN = TEST_USERS["lr_admin_headers"]
MGR = TEST_USERS["lr_manager_headers"]
NEG1 = TEST_USERS["negotiator_headers"]
NEG2 = TEST_USERS["negotiator_2_headers"]
NEG3 = TEST_USERS["negotiator_3_headers"]
CHIEF = TEST_USERS["chief_negotiator_headers"]
LC = TEST_USERS["legal_counsel_headers"]


# ---------------------------------------------------------------------------
# Corner: validations / occ_stale_version_on_second_lock
# ---------------------------------------------------------------------------

def test_second_lock_with_stale_agreement_version_rejected(api):
    """PRD §2.7: "Because locking a scenario legitimately supersedes the
    previously `LOCKED` scenario and bumps the agreement's `version`, and
    because extending legitimately re-extends an already `EXTENDED` agreement
    and also bumps `version`, a second lock or a second extend carrying the
    pre-mutation version is correctly identified as stale and is rejected
    deterministically."

    Design: Corner/validations/occ_stale_version_on_second_lock
    """
    union = create_union(name="Union VA")
    agreement = create_draft_agreement(
        union["id"], title="CBA VA", headcount_baseline=100, fte_projected=120,
        avg_loaded_wage_cents=5000, costing_envelope_cents=1_000_000_000_000,
    )
    proposal = create_employer_proposal_on_table(
        agreement["id"], union["id"], title="Allowance",
        proposal_type="ECONOMIC", recurring_annual_cost_cents=100,
    )
    s1 = create_reviewed_scenario(
        agreement["id"], [proposal["id"]], name="s1", scenario_mode="FINAL", term_years=3
    )
    s2 = create_reviewed_scenario(
        agreement["id"], [proposal["id"]], name="s2", scenario_mode="PROVISIONAL", term_years=3
    )
    a_v = get_agreement_version(agreement["id"])
    locked = get_success_data(
        api.lock_costing_scenario(s1["id"], {"expected_agreement_version": a_v}, CHIEF)
    )
    assert locked["status"] == "LOCKED"
    resp = api.lock_costing_scenario(s2["id"], {"expected_agreement_version": a_v}, CHIEF)
    validate_error(resp, ApiErrorId.ERR_STALE_AGREEMENT_VERSION)
    s2_after = get_success_data(api.get_costing_scenario(s2["id"], NEG1))
    assert s2_after["status"] == "REVIEWED", "failed lock leaves state unchanged"


# ---------------------------------------------------------------------------
# Corner: validations / envelope_exceeded_by_one_cent
# ---------------------------------------------------------------------------

def test_envelope_exceeded_by_one_cent(api):
    """PRD §3.3: "the agreement's `envelope_committed_cents` plus the
    proposal's `estimated_year1_cost_cents` must not exceed the agreement's
    `costing_envelope_cents` — equality is permitted; strictly exceeding is
    rejected with `ERR_ENVELOPE_EXCEEDED` (HTTP 422)."
    (Envelope 66523199 vs locked year-1 line 66523200 exceeds by one cent.)

    Design: Corner/validations/envelope_exceeded_by_one_cent
    """
    union = create_union(name="Union VB")
    agreement = create_draft_agreement(
        union["id"], title="CBA VB",
        headcount_baseline=100, fte_projected=120, avg_loaded_wage_cents=5000,
        costing_envelope_cents=66523199,
    )
    proposal = create_employer_proposal_on_table(
        agreement["id"], union["id"], title="GWI 4%",
        proposal_type="ECONOMIC", wage_increase_pct=0.04, affected_headcount=100,
        includes_benefits=True, one_time_cost_cents=120000, recurring_annual_cost_cents=6000000,
    )
    create_locked_scenario(agreement["id"], [proposal["id"]], scenario_mode="FINAL", term_years=3)
    resp = api.transition_proposal(
        proposal["id"], {"to_status": "ACCEPTED"}, make_union_representative_headers(union["id"])
    )
    validate_error(resp, ApiErrorId.ERR_ENVELOPE_EXCEEDED)
    after = get_success_data(api.get_proposal(proposal["id"], NEG1))
    assert after["status"] == "ON_TABLE"
    from test_helpers import get_agreement
    assert get_agreement(agreement["id"])["envelope_committed_cents"] == 0


# ---------------------------------------------------------------------------
# Corner: validations / extension_not_forward_rejected
# ---------------------------------------------------------------------------

def test_extension_not_forward_rejected(api):
    """PRD §3.12: "the new expiration must be strictly later than the current
    one (otherwise `ERR_EXTENSION_NOT_FORWARD`)"

    Design: Corner/validations/extension_not_forward_rejected
    """
    union = create_union(name="Union VC")
    agreement = create_active_agreement(
        union["id"], title="CBA VC",
        effective_date="2026-01-01T00:00:00Z", expiration_date="2029-05-31T00:00:00Z",
        headcount_baseline=50, fte_projected=60, avg_loaded_wage_cents=4000,
        costing_envelope_cents=1_000_000_000,
    )
    a_v = get_agreement_version(agreement["id"])
    resp = api.extend_agreement(
        agreement["id"],
        {"new_expiration_date": "2029-05-31T00:00:00Z", "expected_agreement_version": a_v},
        CHIEF,
    )
    validate_error(resp, ApiErrorId.ERR_EXTENSION_NOT_FORWARD)
    after = get_success_data(api.get_agreement(agreement["id"], ADMIN))
    assert after["status"] == "ACTIVE"
    assert after["extension_count"] == 0


# ---------------------------------------------------------------------------
# Corner: validations / max_rounds_exceeded_at_round_12
# ---------------------------------------------------------------------------

def test_max_rounds_exceeded_at_round_12(api):
    """PRD §3.4: "The counter is submitted by the receiving side (a
    `ChiefNegotiator` for a `UNION` proposal, a `UnionRepresentative` for an
    `EMPLOYER` proposal), and is gated by `round_number` — a proposal already
    at round 12 cannot be countered, and the attempt is rejected with
    `ERR_MAX_ROUNDS_EXCEEDED`."

    Design: Corner/validations/max_rounds_exceeded_at_round_12
    """
    union = create_union(name="Union VD")
    agreement = create_draft_agreement(
        union["id"], title="CBA VD", headcount_baseline=50, fte_projected=60,
        avg_loaded_wage_cents=4000, costing_envelope_cents=1_000_000_000,
    )
    rep = make_union_representative_headers(union["id"])
    proposal = get_success_data(
        api.create_proposal(
            create_proposal_payload(
                agreement_id=agreement["id"], side="UNION",
                title="Round 1", proposal_type="NON_ECONOMIC",
            ),
            rep,
        )
    )
    get_success_data(api.transition_proposal(proposal["id"], {"to_status": "TENDERED"}, rep))
    get_success_data(api.transition_proposal(proposal["id"], {"to_status": "ON_TABLE"}, CHIEF))
    current = proposal
    for round_no in range(2, 13):
        actor = CHIEF if current["side"] == "UNION" else rep
        current = get_success_data(
            api.counter_proposal(current["id"], {"title": f"Round {round_no}"}, actor)
        )
        assert current["round_number"] == round_no
        assert current["status"] == "ON_TABLE"
    # current is now round 12, side EMPLOYER (even rounds flip to EMPLOYER).
    resp = api.counter_proposal(current["id"], {"title": "Round 13"}, rep)
    validate_error(resp, ApiErrorId.ERR_MAX_ROUNDS_EXCEEDED)


# ---------------------------------------------------------------------------
# Corner: validations / info_extension_day_and_count_caps
# ---------------------------------------------------------------------------

def test_info_extension_day_and_count_caps(api):
    """PRD §3.11: "The extension count is capped: a request may be extended at
    most twice, and each grant may add at most 5 days — violating either cap is
    rejected with `ERR_EXTENSION_LIMIT_EXCEEDED`."

    Design: Corner/validations/info_extension_day_and_count_caps
    """
    union = create_union(name="Union VE")
    agreement = create_draft_agreement(
        union["id"], title="CBA VE", deadline_mode="BUSINESS",
        headcount_baseline=50, fte_projected=60, avg_loaded_wage_cents=4000,
        costing_envelope_cents=1_000_000_000,
    )
    request = get_success_data(
        api.create_information_request(
            create_information_request_payload(
                union_id=union["id"], agreement_id=agreement["id"],
                subject="Payroll extract", received_at="2026-05-01T09:00:00Z",
            ),
            make_union_representative_headers(union["id"]),
        )
    )
    # Grant 1: +5 business days, due 2026-05-15 -> 2026-05-22.
    get_success_data(api.extend_information_request(request["id"], {"extra_business_days": 5}, MGR))
    # 6 days exceeds the per-grant cap.
    resp_days = api.extend_information_request(request["id"], {"extra_business_days": 6}, MGR)
    validate_error(resp_days, ApiErrorId.ERR_EXTENSION_LIMIT_EXCEEDED)
    # Grant 2: +5 business days, due 2026-05-22 -> 2026-05-29.
    get_success_data(api.extend_information_request(request["id"], {"extra_business_days": 5}, MGR))
    # Third extension exceeds the 2-grant cap.
    resp_count = api.extend_information_request(request["id"], {"extra_business_days": 1}, MGR)
    validate_error(resp_count, ApiErrorId.ERR_EXTENSION_LIMIT_EXCEEDED)
    after = get_success_data(api.get_information_request(request["id"], MGR))
    assert after["extension_count"] == 2
    assert after["due_at"] == "2026-05-29T17:00:00Z"


# ---------------------------------------------------------------------------
# Corner: validations / duplicate_article_ref_conflict
# ---------------------------------------------------------------------------

def test_duplicate_article_ref_conflict(api):
    """PRD §3.2: "Each clause carries `agreement_id`, an `article_ref` such as
    `12.1` (unique within its agreement — a duplicate is rejected with
    `ERR_DUPLICATE_ARTICLE_REF`)"

    Design: Corner/validations/duplicate_article_ref_conflict
    """
    union = create_union(name="Union VF")
    a1 = create_draft_agreement(union["id"], title="CBA VF-1")
    a2 = create_draft_agreement(union["id"], title="CBA VF-2")
    get_success_data(
        api.create_clause(
            {"agreement_id": a1["id"], "article_ref": "12.1", "title": "Overtime", "body_text": "OT"},
            MGR,
        )
    )
    resp = api.create_clause(
        {"agreement_id": a1["id"], "article_ref": "12.1", "title": "Overtime again", "body_text": "OT2"},
        MGR,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ARTICLE_REF)
    other = get_success_data(
        api.create_clause(
            {"agreement_id": a2["id"], "article_ref": "12.1", "title": "Overtime successor", "body_text": "OT3"},
            MGR,
        )
    )
    assert other["agreement_id"] == a2["id"], "uniqueness is per-agreement"


# ---------------------------------------------------------------------------
# Corner: validations / resolution_reference_state_gate
# ---------------------------------------------------------------------------

def test_resolution_reference_state_gate(api):
    """PRD §3.2: "A `LegalCounsel` resolves a `DISPUTED` clause (action
    `RESOLVE`) by citing exactly one of `side_letter_id` or `past_practice_id`
    — supplying both or neither is `ERR_INVALID_REQUEST` — and the cited side
    letter must be `EXECUTED` or the cited practice `VERIFIED`, otherwise
    `ERR_RESOLUTION_REFERENCE_INVALID` (HTTP 422). On a successful resolve, the
    clause becomes `RESOLVED` and `resolved_by_ref` is set to the cited id."

    Design: Corner/validations/resolution_reference_state_gate
    """
    union = create_union(name="Union VG")
    agreement = create_active_agreement(
        union["id"], title="CBA VG",
        effective_date="2026-01-01T00:00:00Z", expiration_date="2029-05-31T00:00:00Z",
        headcount_baseline=50, fte_projected=60, avg_loaded_wage_cents=4000,
        costing_envelope_cents=1_000_000_000,
    )
    clause = create_interpreted_clause(
        agreement["id"], article_ref="9.3", title="Leave", body_text="Leave terms"
    )
    get_success_data(api.interpret_clause(clause["id"], {"action": "DISPUTE"}, MGR))
    # DOCUMENTED (unverified) practice is not a valid resolution reference.
    practice = get_success_data(
        api.create_past_practice(
            create_past_practice_payload(
                union_id=union["id"], clause_id=clause["id"], title="Leave practice",
                description="Granted historically",
                first_observed_date="2023-05-01T00:00:00Z",
                last_observed_date="2025-05-01T00:00:00Z", occurrence_count=8,
            ),
            MGR,
        )
    )
    get_success_data(api.transition_past_practice(practice["id"], {"to_status": "DOCUMENTED"}, MGR))
    resp = api.interpret_clause(
        clause["id"], {"action": "RESOLVE", "past_practice_id": practice["id"]}, LC
    )
    validate_error(resp, ApiErrorId.ERR_RESOLUTION_REFERENCE_INVALID)
    # EXECUTED side letter resolves the dispute.
    letter = create_executed_side_letter(
        agreement["id"], clause["id"],
        effective_start="2026-01-01T00:00:00Z", effective_end="2027-12-31T00:00:00Z",
        title="Leave letter",
    )
    resolved = get_success_data(
        api.interpret_clause(clause["id"], {"action": "RESOLVE", "side_letter_id": letter["id"]}, LC)
    )
    assert resolved["interpretation_status"] == "RESOLVED"
    assert resolved["resolved_by_ref"] == letter["id"]


# ---------------------------------------------------------------------------
# Corner: validations / sod_scenario_review_and_lock
# ---------------------------------------------------------------------------

def test_sod_scenario_review_and_lock(api):
    """PRD §2.8: "On a `CostingScenario`, the `Negotiator` who runs the compute
    records their `X-User-ID` as `computed_by_user_id`; the subsequent review
    must be performed by a different `Negotiator`, and the subsequent lock by a
    `ChiefNegotiator` must also be performed by someone other than
    `computed_by_user_id`. ... Any attempt to review, lock, or execute with the
    same `X-User-ID` as the original producer is rejected with
    `ERR_SOD_VIOLATION` (HTTP 403)."

    Design: Corner/validations/sod_scenario_review_and_lock
    """
    union = create_union(name="Union VH")
    agreement = create_draft_agreement(
        union["id"], title="CBA VH", headcount_baseline=100, fte_projected=120,
        avg_loaded_wage_cents=5000, costing_envelope_cents=1_000_000_000_000,
    )
    proposal = create_employer_proposal_on_table(
        agreement["id"], union["id"], title="Allowance",
        proposal_type="ECONOMIC", recurring_annual_cost_cents=100,
    )
    scenario = get_success_data(
        api.create_costing_scenario(
            {
                "agreement_id": agreement["id"], "name": "sod",
                "scenario_mode": "FINAL", "term_years": 3,
                "proposal_ids": [proposal["id"]],
            },
            NEG1,
        )
    )
    get_success_data(api.transition_costing_scenario(scenario["id"], {"to_status": "COMPUTED"}, NEG1))
    # Same user id reviewing own computation -> SoD violation.
    resp_review = api.transition_costing_scenario(scenario["id"], {"to_status": "REVIEWED"}, NEG1)
    validate_error(resp_review, ApiErrorId.ERR_SOD_VIOLATION)
    # Distinct reviewer succeeds.
    get_success_data(api.transition_costing_scenario(scenario["id"], {"to_status": "REVIEWED"}, NEG2))
    a_v = get_agreement_version(agreement["id"])
    # Chief carrying the computer's user id cannot lock.
    resp_lock = api.lock_costing_scenario(
        scenario["id"], {"expected_agreement_version": a_v}, make_chief_negotiator_headers("neg-1")
    )
    validate_error(resp_lock, ApiErrorId.ERR_SOD_VIOLATION)
    # Distinct chief locks successfully.
    locked = get_success_data(
        api.lock_costing_scenario(scenario["id"], {"expected_agreement_version": a_v}, CHIEF)
    )
    assert locked["status"] == "LOCKED"


# ---------------------------------------------------------------------------
# Corner: validations / sod_side_letter_execute
# ---------------------------------------------------------------------------

def test_sod_side_letter_execute(api):
    """PRD §2.8: "On a `SideLetter`, the `LRManager` who drafts the letter
    records their `X-User-ID` as `drafted_by_user_id`; the `LegalCounsel` who
    executes the letter must be a different operator. Any attempt to review,
    lock, or execute with the same `X-User-ID` as the original producer is
    rejected with `ERR_SOD_VIOLATION` (HTTP 403)."

    Design: Corner/validations/sod_side_letter_execute
    """
    union = create_union(name="Union VI")
    agreement = create_active_agreement(
        union["id"], title="CBA VI",
        effective_date="2026-01-01T00:00:00Z", expiration_date="2029-05-31T00:00:00Z",
        headcount_baseline=50, fte_projected=60, avg_loaded_wage_cents=4000,
        costing_envelope_cents=1_000_000_000,
    )
    clause = create_clause(agreement["id"], article_ref="7.1", title="Breaks", body_text="Break terms")
    letter = get_success_data(
        api.create_side_letter(
            create_side_letter_payload(
                agreement_id=agreement["id"], clause_id=clause["id"],
                letter_type="MOU", title="Break letter",
                effective_start="2026-01-01T00:00:00Z", effective_end="2026-12-31T00:00:00Z",
            ),
            MGR,
        )
    )
    get_success_data(api.transition_side_letter(letter["id"], {"to_status": "PENDING_LEGAL"}, MGR))
    # Executor carrying the drafter's user id -> SoD violation.
    resp = api.transition_side_letter(
        letter["id"], {"to_status": "EXECUTED"}, make_legal_counsel_headers("mgr-1")
    )
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
    executed = get_success_data(api.transition_side_letter(letter["id"], {"to_status": "EXECUTED"}, LC))
    assert executed["status"] == "EXECUTED"
    assert executed["executed_by_user_id"] == "lc-1"


# ---------------------------------------------------------------------------
# Corner: validations / ballot_tally_before_close_rejected
# ---------------------------------------------------------------------------

def test_ballot_tally_before_close_rejected(api):
    """PRD §3.6: "It is rejected with `ERR_BALLOT_STILL_OPEN` if the logical
    clock has not yet reached `ballot_close_at`."

    Design: Corner/validations/ballot_tally_before_close_rejected
    """
    union, agreement, proposal, _ = setup_accepted_economic_package(
        union_name="Union VJ",
        proposal_overrides={"recurring_annual_cost_cents": 100},
        scenario_overrides={"scenario_mode": "FINAL", "term_years": 3},
    )
    vote = setup_open_vote(union, agreement, ballot_close_at="2026-06-01T00:00:00Z")
    # Clock untouched at the 2026-05-01 default — before ballot_close_at.
    resp = api.tally_vote(
        vote["id"], {"votes_for": 6, "votes_against": 1},
        make_union_representative_headers(union["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_BALLOT_STILL_OPEN)
    after = get_success_data(api.get_ratification_vote(vote["id"], CHIEF))
    assert after["status"] == "OPEN"
    assert after["votes_for"] is None, "tally must not be recorded"


# ---------------------------------------------------------------------------
# Corner: validations / wrong_side_accept_rejected
# ---------------------------------------------------------------------------

def test_wrong_side_accept_rejected(api):
    """PRD §3.3: "The receiving side then tables the proposal (`TENDERED →
    ON_TABLE`). For an `EMPLOYER` proposal, the receiver is a
    `UnionRepresentative`; for a `UNION` proposal, the receiver is a
    `ChiefNegotiator`. Tabling by the proposing side is rejected with
    `ERR_WRONG_SIDE`." and "Once `ON_TABLE`, three resolutions and one counter
    are available. The receiving side may accept (`ON_TABLE → ACCEPTED`)"

    Design: Corner/validations/wrong_side_accept_rejected
    """
    union = create_union(name="Union VK")
    agreement = create_draft_agreement(
        union["id"], title="CBA VK", headcount_baseline=50, fte_projected=60,
        avg_loaded_wage_cents=4000, costing_envelope_cents=1_000_000_000,
    )
    proposal = create_employer_proposal_on_table(
        agreement["id"], union["id"], title="Employer ask", proposal_type="NON_ECONOMIC"
    )
    # The ChiefNegotiator accepting the employer's own ON_TABLE proposal.
    resp = api.transition_proposal(proposal["id"], {"to_status": "ACCEPTED"}, CHIEF)
    validate_error(resp, ApiErrorId.ERR_WRONG_SIDE)
    after = get_success_data(api.get_proposal(proposal["id"], NEG1))
    assert after["status"] == "ON_TABLE"


# ---------------------------------------------------------------------------
# Corner: validations / union_mismatch_on_tally
# ---------------------------------------------------------------------------

def test_union_mismatch_on_tally(api):
    """PRD §2.1: "tallying a ratification vote requires that `X-User-ID` equal
    the union of the vote's agreement; ... Any mismatch is rejected with
    `ERR_UNION_MISMATCH` (HTTP 403)."

    Design: Corner/validations/union_mismatch_on_tally
    """
    union1, agreement, proposal, _ = setup_accepted_economic_package(
        union_name="Union VL1",
        proposal_overrides={"recurring_annual_cost_cents": 100},
        scenario_overrides={"scenario_mode": "FINAL", "term_years": 3},
    )
    union2 = create_union(name="Union VL2")
    vote = setup_open_vote(union1, agreement, ballot_close_at="2026-06-01T00:00:00Z")
    get_success_data(api.set_clock("2026-06-02T00:00:00Z", ADMIN))
    resp = api.tally_vote(
        vote["id"], {"votes_for": 6, "votes_against": 1},
        make_union_representative_headers(union2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNION_MISMATCH)
    after = get_success_data(api.get_ratification_vote(vote["id"], CHIEF))
    assert after["status"] == "OPEN"


# ---------------------------------------------------------------------------
# Corner: validations / decertified_union_blocks_session_create
# ---------------------------------------------------------------------------

def test_decertified_union_blocks_session_create(api):
    """PRD §2.5: "A union in `DECERTIFIED` imposes a stricter freeze — drafting
    a proposal, tendering a proposal, scheduling a session, or filing an
    information request are all rejected with `ERR_UNION_DECERTIFIED`
    (HTTP 409)." and "When a union transitions to `DECERTIFIED`, the system
    walks its agreements: every `CollectiveAgreement` of that union still in
    `DRAFT` becomes `ARCHIVED`"

    Design: Corner/validations/decertified_union_blocks_session_create
    """
    union = create_union(name="Union VM")
    agreement = create_active_agreement(
        union["id"], title="CBA VM",
        effective_date="2026-01-01T00:00:00Z", expiration_date="2026-06-15T00:00:00Z",
        headcount_baseline=50, fte_projected=60, avg_loaded_wage_cents=4000,
        costing_envelope_cents=1_000_000_000,
    )
    get_success_data(api.transition_union(union["id"], {"to_status": "DECERTIFIED"}, ADMIN))
    resp = api.create_session(
        {
            "agreement_id": agreement["id"], "mediator_id": "med-x",
            "lead_negotiator_id": "ln-x", "location": "Room 9",
            "start_at": "2026-05-20T10:00:00Z", "end_at": "2026-05-20T11:00:00Z",
        },
        NEG1,
    )
    validate_error(resp, ApiErrorId.ERR_UNION_DECERTIFIED)
    after = get_success_data(api.get_agreement(agreement["id"], ADMIN))
    assert after["status"] == "ACTIVE", "decertify cascade archives only DRAFT agreements"


# ---------------------------------------------------------------------------
# Corner: validations / session_open_before_start_rejected
# ---------------------------------------------------------------------------

def test_session_open_before_start_rejected(api):
    """PRD §3.3: "Once the logical clock reaches `start_at`, a
    `ChiefNegotiator` may move the session `SCHEDULED → IN_SESSION`; attempting
    this before `start_at` is rejected with `ERR_SESSION_NOT_STARTED`."

    Design: Corner/validations/session_open_before_start_rejected
    """
    union = create_union(name="Union VN")
    agreement = create_draft_agreement(union["id"], title="CBA VN")
    session = create_session(
        agreement["id"], mediator_id="med-y", lead_negotiator_id="ln-y",
        location="Room 1", start_at="2026-06-01T10:00:00Z", end_at="2026-06-01T11:00:00Z",
    )
    # Clock untouched at the 2026-05-01 default — before start_at.
    resp = api.transition_session(session["id"], {"to_status": "IN_SESSION"}, CHIEF)
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_STARTED)
    after = get_success_data(api.get_session(session["id"], NEG1))
    assert after["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Corner: validations / side_letter_invalid_effective_range
# ---------------------------------------------------------------------------

def test_side_letter_invalid_effective_range(api):
    """PRD §3.9: "The window is a closed interval — `effective_end` must be on
    or after `effective_start`, otherwise `ERR_INVALID_EFFECTIVE_RANGE`
    (HTTP 422)."

    Design: Corner/validations/side_letter_invalid_effective_range
    """
    union = create_union(name="Union VS")
    agreement = create_draft_agreement(
        union["id"], title="CBA VS",
        effective_date="2026-01-01T00:00:00Z", expiration_date="2029-05-31T00:00:00Z",
        headcount_baseline=50, fte_projected=60, avg_loaded_wage_cents=4000,
        costing_envelope_cents=1_000_000_000,
    )
    clause = create_clause(agreement["id"], article_ref="4.1", title="Transfers", body_text="x")
    resp = api.create_side_letter(
        create_side_letter_payload(
            agreement_id=agreement["id"], clause_id=clause["id"],
            letter_type="MOU", title="Backwards letter",
            effective_start="2027-01-01T00:00:00Z", effective_end="2026-06-30T00:00:00Z",
        ),
        MGR,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_EFFECTIVE_RANGE)


# ---------------------------------------------------------------------------
# Corner: validations / lead_negotiator_buffer_conflict
# ---------------------------------------------------------------------------

def test_lead_negotiator_buffer_conflict(api):
    """PRD §2.4: "The lead negotiator is governed by a wider buffered rule:
    expand both candidate intervals by 45 minutes on each end, and if the two
    expanded intervals intersect for sessions that share `lead_negotiator_id`
    and are in `SCHEDULED` or `IN_SESSION` status, the create is rejected with
    `ERR_NEGOTIATOR_BUFFER_CONFLICT` (HTTP 409)."
    (A 30-minute gap after a 10:00-11:00 session conflicts: expanded, the two
    intervals still intersect.)

    Design: Corner/validations/lead_negotiator_buffer_conflict
    """
    union = create_union(name="Union VT")
    agreement = create_draft_agreement(union["id"], title="CBA VT")
    create_session(
        agreement["id"], mediator_id="med-b1", lead_negotiator_id="ln-b",
        location="Room 1", start_at="2026-06-01T10:00:00Z", end_at="2026-06-01T11:00:00Z",
    )
    resp = api.create_session(
        {
            "agreement_id": agreement["id"], "mediator_id": "med-b2",
            "lead_negotiator_id": "ln-b", "location": "Room 2",
            "start_at": "2026-06-01T11:30:00Z", "end_at": "2026-06-01T12:00:00Z",
        },
        NEG1,
    )
    validate_error(resp, ApiErrorId.ERR_NEGOTIATOR_BUFFER_CONFLICT)


# ---------------------------------------------------------------------------
# Corner: validations / accept_economic_without_locked_costing
# ---------------------------------------------------------------------------

def test_accept_economic_without_locked_costing(api):
    """PRD §3.3: "First, a `LOCKED` costing scenario for the agreement whose
    `proposal_ids` contains this proposal must exist (otherwise
    `ERR_COSTING_NOT_LOCKED`)."

    Design: Corner/validations/accept_economic_without_locked_costing
    """
    union = create_union(name="Union VU")
    agreement = create_draft_agreement(
        union["id"], title="CBA VU", headcount_baseline=100, fte_projected=120,
        avg_loaded_wage_cents=5000, costing_envelope_cents=1_000_000_000_000,
    )
    proposal = create_employer_proposal_on_table(
        agreement["id"], union["id"], title="Uncosted ask",
        proposal_type="ECONOMIC", recurring_annual_cost_cents=100,
    )
    resp = api.transition_proposal(
        proposal["id"], {"to_status": "ACCEPTED"}, make_union_representative_headers(union["id"])
    )
    validate_error(resp, ApiErrorId.ERR_COSTING_NOT_LOCKED)
    after = get_success_data(api.get_proposal(proposal["id"], NEG1))
    assert after["status"] == "ON_TABLE"


# ---------------------------------------------------------------------------
# Corner: validations / session_invalid_time_range
# ---------------------------------------------------------------------------

def test_session_invalid_time_range(api):
    """PRD §2.4: "`start_at` must be strictly earlier than `end_at`, and the
    duration from `start_at` to `end_at` must not exceed 12 hours. A session
    that violates either bound is rejected with `ERR_INVALID_TIME_RANGE`
    (HTTP 422)."

    Design: Corner/validations/session_invalid_time_range
    """
    union = create_union(name="Union VV")
    agreement = create_draft_agreement(union["id"], title="CBA VV")
    resp = api.create_session(
        {
            "agreement_id": agreement["id"], "mediator_id": "med-t",
            "lead_negotiator_id": "ln-t", "location": "Room 1",
            "start_at": "2026-06-01T10:00:00Z", "end_at": "2026-06-01T10:00:00Z",
        },
        NEG1,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE)
