"""Case opening, eligibility snapshot, required-document computation, and the
open-case occupation slot."""
from test_helpers import (
    ApiErrorId,
    api_client,
    build_conversion_case,
    get_case,
    list_case_documents,
    make_account,
    make_admin_headers,
    make_participant,
    make_participant_headers,
    make_plan,
    make_processor_headers,
    set_logical_clock,
    submit_case,
    validate_error,
    validate_paginated,
    validate_success,
)


def _open_draft_case(participant, account, case_type, **extra):
    payload = {"case_type": case_type, "source_account_id": account["id"]}
    payload.update(extra)
    resp = api_client.create_rollover_case(payload, make_participant_headers(participant["id"]))
    return validate_success(resp, expected_status=201)


def test_case_created_in_initial_draft(api):
    """PRD §3.3: "A `Participant` opens a case in `DRAFT` status (version 1) by
    naming a `case_type` — `DIRECT_ROLLOVER_OUT`, `INDIRECT_ROLLOVER_OUT`,
    `PLAN_TRANSFER`, `IN_PLAN_ROTH_CONVERSION`, or `ROLLOVER_IN` — plus the
    election fields appropriate to the type."
    PRD §3.6: "Assembly runs two pinned calculations in sequence and locks their
    outputs onto the case." (No amounts are locked before assembly.)

    Design: Corner/state_machines/case_created_in_initial_draft
    """
    plan = make_plan(clock="2026-05-01T00:00:00Z")
    participant = make_participant()
    account = make_account(participant["id"], plan["id"], [
        {"source_type": "PRE_TAX", "balance_cents": 500000, "basis_cents": 0, "vested_pct": 100},
    ])
    case = _open_draft_case(participant, account, "DIRECT_ROLLOVER_OUT",
                            receiving_institution_name="External IRA Trust")
    assert case["status"] == "DRAFT", f"case must open in DRAFT, got {case['status']}"
    assert case["version"] == 1, f"case version must start at 1, got {case['version']}"
    assert case.get("gross_cents") is None, (
        f"no computed amounts may be locked on a DRAFT case, got {case.get('gross_cents')}"
    )


def test_case_submit_computes_docs_and_routes(api):
    """PRD §3.4: "Submit also computes the case's **required-document set** and
    routes the case within the same request: if the set is empty, the case lands
    directly in `ELIGIBILITY_REVIEW`; otherwise it lands in `DOCS_PENDING`.
    Documents are created in exactly the deterministic order listed below — the
    list order is part of the contract:"
    PRD §3.4: "2. `SEPARATION_VERIFICATION`, required when the qualifying event
    is `SEPARATION`." / "4. `IDENTITY_PROOF`, required for
    `INDIRECT_ROLLOVER_OUT` cases."
    PRD §3.3: "The eligibility snapshot evaluates the participant's
    **qualifying event**, stored on the case as `qualifying_event`, with branch
    priority pinned top-down — the first matching branch wins:"

    Design: Corner/state_machines/case_submit_computes_docs_and_routes
    """
    plan = make_plan(clock="2026-05-01T00:00:00Z")
    participant = make_participant()
    account = make_account(participant["id"], plan["id"], [
        {"source_type": "PRE_TAX", "balance_cents": 500000, "basis_cents": 0, "vested_pct": 100},
    ])
    case = _open_draft_case(participant, account, "INDIRECT_ROLLOVER_OUT",
                            receiving_institution_name="External IRA Trust",
                            withholding_acknowledged=True)
    submitted = submit_case(case["id"], participant["id"])
    assert submitted["status"] == "DOCS_PENDING", (
        f"non-empty doc set must route to DOCS_PENDING, got {submitted['status']}"
    )
    assert submitted["qualifying_event"] == "SEPARATION", (
        f"SEPARATED participant must snapshot SEPARATION, got {submitted['qualifying_event']}"
    )
    docs = list_case_documents(case["id"])
    assert [d["doc_type"] for d in docs] == ["SEPARATION_VERIFICATION", "IDENTITY_PROOF"], (
        f"documents must be created in the pinned list order, got {[d['doc_type'] for d in docs]}"
    )
    assert all(d["status"] == "REQUIRED" for d in docs), "each new document starts REQUIRED"


def test_conversion_without_docs_routes_straight_to_review(api):
    """PRD §3.3: "`ROLLOVER_IN` and `IN_PLAN_ROTH_CONVERSION` cases are exempt
    from the qualifying-event requirement entirely — inbound money needs no
    distribution event, and a conversion is not a distribution."
    PRD §3.4: "Submit also computes the case's **required-document set** and
    routes the case within the same request: if the set is empty, the case lands
    directly in `ELIGIBILITY_REVIEW`; otherwise it lands in `DOCS_PENDING`."

    Design: Corner/state_machines/conversion_without_docs_routes_straight_to_review
    """
    bundle = build_conversion_case(
        balances=[
            {"source_type": "PRE_TAX", "balance_cents": 3000000, "basis_cents": 0, "vested_pct": 100},
            {"source_type": "AFTER_TAX", "balance_cents": 600000, "basis_cents": 500000, "vested_pct": 100},
        ],
        approve=False,
    )
    case = get_case(bundle["case"]["id"])
    assert case["status"] == "ELIGIBILITY_REVIEW", (
        f"empty document set must auto-route to ELIGIBILITY_REVIEW, got {case['status']}"
    )
    docs = list_case_documents(case["id"])
    assert docs == [], f"conversion requires no documents, got {[d['doc_type'] for d in docs]}"


def test_eligibility_branch_termination_overrides_employment(api):
    """PRD §3.3: "1. If the source plan's `status` is `TERMINATED`, the event is
    `PLAN_TERMINATION`. Plan termination overrides every employment-based
    event."
    PRD §3.3: "2. Else if the participant's `employment_status` is `SEPARATED`
    or `RETIRED`, the event is `SEPARATION`."

    Design: Difficulty/combinatorial_formula/eligibility_multi_input_branch
    """
    proc = make_processor_headers("proc-1")
    plan_t = make_plan(name="Plan T", clock="2026-05-01T00:00:00Z")
    plan_a = make_plan(name="Plan A")
    # Participant in the terminating plan is ACTIVE: plan-status branch must win.
    p_term = make_participant(
        full_name="Tee Rminated", date_of_birth="1990-01-01", employment_status="ACTIVE",
        marital_status="SINGLE", separation_date=None,
    )
    p_sep = make_participant(full_name="Sep Arated", date_of_birth="1990-01-01")
    a_term = make_account(p_term["id"], plan_t["id"], [
        {"source_type": "PRE_TAX", "balance_cents": 500000, "basis_cents": 0, "vested_pct": 100},
    ])
    a_sep = make_account(p_sep["id"], plan_a["id"], [
        {"source_type": "PRE_TAX", "balance_cents": 500000, "basis_cents": 0, "vested_pct": 100},
    ])
    validate_success(api_client.terminate_plan(plan_t["id"], make_admin_headers()))
    c_term = _open_draft_case(p_term, a_term, "INDIRECT_ROLLOVER_OUT",
                              receiving_institution_name="External IRA Trust",
                              withholding_acknowledged=True)
    c_sep = _open_draft_case(p_sep, a_sep, "INDIRECT_ROLLOVER_OUT",
                             receiving_institution_name="External IRA Trust",
                             withholding_acknowledged=True)

    r_term = validate_success(api_client.submit_case(c_term["id"], make_participant_headers(p_term["id"])))
    r_sep = validate_success(api_client.submit_case(c_sep["id"], make_participant_headers(p_sep["id"])))
    assert r_term["qualifying_event"] == "PLAN_TERMINATION", (
        f"plan-status branch must override ACTIVE employment, got {r_term['qualifying_event']}"
    )
    assert r_sep["qualifying_event"] == "SEPARATION", (
        f"SEPARATED participant must take the SEPARATION branch, got {r_sep['qualifying_event']}"
    )
    assert r_term["status"] == "DOCS_PENDING" and r_sep["status"] == "DOCS_PENDING"


def test_eligibility_branch_age_59_half_fallback(api):
    """PRD §3.3: "4. Else if the participant's `age_months` at the clock date is
    at least 714 — that is, exactly 59½ years, the age threshold pinned in whole
    months — the event is `AGE_59_HALF`. This is the fallback branch and the
    only one sensitive to the 59.50 boundary."

    Design: Difficulty/combinatorial_formula/eligibility_multi_input_branch
    """
    plan = make_plan(clock="2026-05-01T00:00:00Z")
    # dob 1966-11-01 at clock 2026-05-01 -> (2026-1966)*12 + (5-11) = 714 exactly.
    participant = make_participant(
        full_name="Age Boundary", date_of_birth="1966-11-01", employment_status="ACTIVE",
        marital_status="SINGLE", separation_date=None,
    )
    account = make_account(participant["id"], plan["id"], [
        {"source_type": "PRE_TAX", "balance_cents": 500000, "basis_cents": 0, "vested_pct": 100},
    ])
    case = _open_draft_case(participant, account, "INDIRECT_ROLLOVER_OUT",
                            receiving_institution_name="External IRA Trust",
                            withholding_acknowledged=True)
    submitted = submit_case(case["id"], participant["id"])
    assert submitted["qualifying_event"] == "AGE_59_HALF", (
        f"age_months == 714 must take the AGE_59_HALF fallback, got {submitted['qualifying_event']}"
    )
    assert submitted["status"] == "DOCS_PENDING"


def test_age_714_month_boundary_eligible(api):
    """PRD §3.3: "4. Else if the participant's `age_months` at the clock date is
    at least 714 — that is, exactly 59½ years, the age threshold pinned in whole
    months — the event is `AGE_59_HALF`."
    PRD §3.2: "`age_months`, the count of complete calendar months elapsed —
    computed as twelve times the year difference plus the month difference,
    minus one when the clock's day-of-month is earlier than the birth
    day-of-month"

    Design: Difficulty/boundary_precision_check/age_714_month_boundary
    """
    plan = make_plan(clock="2026-05-01T00:00:00Z")
    participant = make_participant(
        full_name="Ok Boundary", date_of_birth="1966-11-01", employment_status="ACTIVE",
        marital_status="SINGLE", separation_date=None,
    )
    account = make_account(participant["id"], plan["id"], [
        {"source_type": "PRE_TAX", "balance_cents": 500000, "basis_cents": 0, "vested_pct": 100},
    ])
    case = _open_draft_case(participant, account, "INDIRECT_ROLLOVER_OUT",
                            receiving_institution_name="External IRA Trust",
                            withholding_acknowledged=True)
    submitted = submit_case(case["id"], participant["id"])
    # 714 months exactly: >= threshold is met.
    assert submitted["qualifying_event"] == "AGE_59_HALF"
    assert submitted["status"] == "DOCS_PENDING", (
        f"boundary-age submit must succeed, got {submitted['status']}"
    )


def test_age_713_month_boundary_not_eligible(api):
    """PRD §3.3: "5. Otherwise the event is `NONE`, and the submit is rejected
    with `ERR_NOT_ELIGIBLE`."
    PRD §3.2: "`age_months`, the count of complete calendar months elapsed —
    computed as twelve times the year difference plus the month difference,
    minus one when the clock's day-of-month is earlier than the birth
    day-of-month"

    Design: Difficulty/boundary_precision_check/age_714_month_boundary
    """
    plan = make_plan(clock="2026-05-01T00:00:00Z")
    # dob 1966-11-02 at clock 2026-05-01: raw months 714, minus one because the
    # clock's day-of-month (1) is earlier than the birth day-of-month (2) -> 713.
    participant = make_participant(
        full_name="No Boundary", date_of_birth="1966-11-02", employment_status="ACTIVE",
        marital_status="SINGLE", separation_date=None,
    )
    account = make_account(participant["id"], plan["id"], [
        {"source_type": "PRE_TAX", "balance_cents": 500000, "basis_cents": 0, "vested_pct": 100},
    ])
    case = _open_draft_case(participant, account, "INDIRECT_ROLLOVER_OUT",
                            receiving_institution_name="External IRA Trust",
                            withholding_acknowledged=True)
    resp = api_client.submit_case(case["id"], make_participant_headers(participant["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_ELIGIBLE, expected_status=422)


def test_indirect_submit_requires_withholding_ack(api):
    """PRD §3.3: "an `INDIRECT_ROLLOVER_OUT` case must carry
    `withholding_acknowledged` as true (else `ERR_WITHHOLDING_ACK_REQUIRED`)"
    PRD §3.3: "`withholding_acknowledged` records the participant's
    acknowledgement of mandatory federal withholding, defaulting to `false`."

    Design: Corner/validations/indirect_submit_requires_withholding_ack
    """
    plan = make_plan(clock="2026-05-01T00:00:00Z")
    participant = make_participant()
    account = make_account(participant["id"], plan["id"], [
        {"source_type": "PRE_TAX", "balance_cents": 500000, "basis_cents": 0, "vested_pct": 100},
    ])
    # No withholding_acknowledged on creation -> defaults to false.
    case = _open_draft_case(participant, account, "INDIRECT_ROLLOVER_OUT",
                            receiving_institution_name="External IRA Trust")
    resp = api_client.submit_case(case["id"], make_participant_headers(participant["id"]))
    validate_error(resp, ApiErrorId.ERR_WITHHOLDING_ACK_REQUIRED, expected_status=422)
    assert get_case(case["id"])["status"] == "DRAFT", "rejected submit must leave the case DRAFT"


def test_frozen_plan_blocks_case_submit(api):
    """PRD §3.3: "then state guards — the source plan must be `ACTIVE` (a
    `FROZEN` plan yields `ERR_PLAN_FROZEN`, while a `TERMINATED` plan notably
    does *not* block submission, because termination is itself a qualifying
    event)"

    Design: Corner/validations/frozen_plan_blocks_case_submit
    """
    plan = make_plan(clock="2026-05-01T00:00:00Z")
    participant = make_participant()
    account = make_account(participant["id"], plan["id"], [
        {"source_type": "PRE_TAX", "balance_cents": 500000, "basis_cents": 0, "vested_pct": 100},
    ])
    validate_success(api_client.freeze_plan(plan["id"], make_admin_headers()))
    case = _open_draft_case(participant, account, "INDIRECT_ROLLOVER_OUT",
                            receiving_institution_name="External IRA Trust",
                            withholding_acknowledged=True)
    resp = api_client.submit_case(case["id"], make_participant_headers(participant["id"]))
    validate_error(resp, ApiErrorId.ERR_PLAN_FROZEN, expected_status=409)
    assert get_case(case["id"])["status"] == "DRAFT"


def test_open_case_slot_blocks_second_case_until_predecessor_terminal(api):
    """PRD §3.3: "A source account may host at most one non-terminal case at a
    time. The occupation interval is half-open — a case occupies its source
    account from creation until it reaches a terminal state — so a second case
    opened on the same account while the first is still in flight is rejected
    with `ERR_OPEN_CASE_EXISTS`, but a case opened the moment its predecessor
    completes is allowed."
    PRD §3.3: "The open-case exclusivity rule (`ERR_OPEN_CASE_EXISTS`) guards
    here too."

    Design: Difficulty/resource_temporal_overlap/account_case_slot_half_open
    """
    plan = make_plan(clock="2026-05-01T00:00:00Z")
    participant = make_participant()
    account = make_account(participant["id"], plan["id"], [
        {"source_type": "PRE_TAX", "balance_cents": 500000, "basis_cents": 0, "vested_pct": 100},
    ])
    p_headers = make_participant_headers(participant["id"])
    case1 = _open_draft_case(participant, account, "INDIRECT_ROLLOVER_OUT",
                             receiving_institution_name="External IRA Trust",
                             withholding_acknowledged=True)
    submit_case(case1["id"], participant["id"])  # case1 now non-terminal DOCS_PENDING

    # A second case opened while case1 is still in flight is rejected.
    resp = api_client.create_rollover_case(
        {"case_type": "DIRECT_ROLLOVER_OUT",
         "source_account_id": account["id"],
         "receiving_institution_name": "External IRA Trust"},
        p_headers,
    )
    validate_error(resp, ApiErrorId.ERR_OPEN_CASE_EXISTS, expected_status=409)

    # Half-open interval end: once case1 is CANCELLED (terminal), the slot frees.
    cancelled = validate_success(api_client.cancel_case(case1["id"], p_headers))
    assert cancelled["status"] == "CANCELLED"
    case2 = _open_draft_case(participant, account, "DIRECT_ROLLOVER_OUT",
                             receiving_institution_name="External IRA Trust")
    submitted2 = validate_success(api_client.submit_case(case2["id"], p_headers))
    assert submitted2["status"] == "DOCS_PENDING", (
        f"open after the predecessor turned terminal must succeed, got {submitted2['status']}"
    )


def test_open_case_slot_occupation_starts_at_creation(api):
    """PRD §3.3: "The occupation interval is half-open — a case occupies its
    source account from creation until it reaches a terminal state — so a second
    case opened on the same account while the first is still in flight is
    rejected with `ERR_OPEN_CASE_EXISTS`, but a case opened the moment its
    predecessor completes is allowed."

    Design: Difficulty/resource_temporal_overlap/account_case_slot_half_open
    """
    plan = make_plan(clock="2026-05-01T00:00:00Z")
    participant = make_participant()
    account = make_account(participant["id"], plan["id"], [
        {"source_type": "PRE_TAX", "balance_cents": 500000, "basis_cents": 0, "vested_pct": 100},
    ])
    p_headers = make_participant_headers(participant["id"])
    # case1 never leaves DRAFT: occupation begins at creation, not at submit.
    case1 = _open_draft_case(participant, account, "INDIRECT_ROLLOVER_OUT",
                             receiving_institution_name="External IRA Trust",
                             withholding_acknowledged=True)

    resp = api_client.create_rollover_case(
        {"case_type": "INDIRECT_ROLLOVER_OUT",
         "source_account_id": account["id"],
         "receiving_institution_name": "External IRA Trust",
         "withholding_acknowledged": True},
        p_headers,
    )
    validate_error(resp, ApiErrorId.ERR_OPEN_CASE_EXISTS, expected_status=409)

    cancelled = validate_success(api_client.cancel_case(case1["id"], p_headers))
    assert cancelled["status"] == "CANCELLED"
    case2 = _open_draft_case(participant, account, "INDIRECT_ROLLOVER_OUT",
                             receiving_institution_name="External IRA Trust",
                             withholding_acknowledged=True)
    submitted2 = validate_success(api_client.submit_case(case2["id"], p_headers))
    assert submitted2["status"] == "DOCS_PENDING"


def test_case_list_pagination_envelope(api):
    """PRD §2.3: "Paginated list responses include the following fields in the
    `meta` object of the response envelope: `limit`, `offset`, `total_count`,
    and `has_more`."
    PRD §2.3: "Unless otherwise specified, all list endpoints return resources
    sorted by their creation timestamp in ascending order (oldest first)."
    PRD §2.3: "The `limit` parameter specifies the maximum number of items to
    return. If not provided, it defaults to 10, with a minimum of 1 and a
    maximum of 100."

    Design: Corner/entities/case_list_pagination_envelope
    """
    plan = make_plan(clock="2026-05-01T00:00:00Z")
    participant = make_participant()
    account = make_account(participant["id"], plan["id"], [
        {"source_type": "PRE_TAX", "balance_cents": 500000, "basis_cents": 0, "vested_pct": 100},
    ])
    p_headers = make_participant_headers(participant["id"])
    case1 = _open_draft_case(participant, account, "INDIRECT_ROLLOVER_OUT",
                             receiving_institution_name="External IRA Trust",
                             withholding_acknowledged=True)
    # PRD §3.3: at most one non-terminal case per source account — cancel case1
    # (terminal) to free the slot before opening the second case. The CANCELLED
    # row persists and is still listed.
    validate_success(api_client.cancel_case(case1["id"], p_headers))
    _open_draft_case(participant, account, "DIRECT_ROLLOVER_OUT",
                     receiving_institution_name="External IRA Trust")
    resp = api_client.list_rollover_cases(
        make_processor_headers("proc-1"),
        params={"source_account_id": account["id"], "limit": 1, "offset": 0},
    )
    rows, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"total_count must be 2, got {meta['total_count']}"
    assert meta["has_more"] is True, "has_more must be true with limit=1 over 2 rows"
    assert meta["limit"] == 1 and meta["offset"] == 0
    assert len(rows) == 1
    assert rows[0]["id"] == case1["id"], "rows must be ordered created_at ASC (oldest first)"
