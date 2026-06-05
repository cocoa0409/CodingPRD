"""Account-opening dependencies: HSA activation gated on the participant's HDHP flag, and
coverage-window overlap with closed vs half-open interval semantics. Plus a dangling body-FK.

Translates Difficulty/cross_entity_state_dependency (hdhp), Difficulty/resource_temporal_overlap,
and Corner/errors/resource_not_found_on_account_body_fk.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, TEST_USERS,
    set_clock, create_plan_year, create_participant, create_account, create_account_payload,
    setup_plan_year_and_participant, ApiErrorId,
)

ADMIN = TEST_USERS["plan_admin_headers"]


def test_hsa_activation_blocked_when_participant_not_hdhp_covered(api):
    """PRD §3.2: "for an HSA it requires the owning participant's `hdhp_covered` to be
    `true`."
    PRD §3.2: "Activation is permitted only while the account is `PENDING`; otherwise it is
    rejected with `ERR_INVALID_STATE` (HTTP 409)."

    A PENDING HSA owned by a non-HDHP participant cannot activate.

    Design: Difficulty/cross_entity_state_dependency/hsa_activation_blocked_by_participant_hdhp_flag
    """
    set_clock("2026-06-01T00:00:00Z")
    py = create_plan_year()
    p = create_participant(email="p7b@x.com", hdhp_covered=False)
    acc = create_account(p["id"], py["id"], "HSA",
                         coverage_tier="SELF_ONLY", elected_amount_cents=437500)
    resp = api.activate_account(acc["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_hsa_activation_blocked_leaves_account_pending(api):
    """PRD §3.2: "A freshly opened account begins with `funding_status` of `PENDING`".

    The rejected activation leaves funding_status PENDING (no transition).

    Design: Difficulty/cross_entity_state_dependency/hsa_activation_blocked_by_participant_hdhp_flag
    """
    set_clock("2026-06-01T00:00:00Z")
    py = create_plan_year()
    p = create_participant(email="p7b2@x.com", hdhp_covered=False)
    acc = create_account(p["id"], py["id"], "HSA",
                         coverage_tier="SELF_ONLY", elected_amount_cents=437500)
    api.activate_account(acc["id"], ADMIN)
    after = validate_success(api.get_account(acc["id"], ADMIN))
    assert after["funding_status"] == "PENDING"


def test_health_fsa_closed_interval_shared_boundary_collides(api):
    """PRD §3.2: "two Health FSA windows collide when the new account's start is on or before
    the existing account's effective end and the existing account's start is on or before the
    new account's effective end — so a single shared boundary day is a collision."
    PRD §3.2: "A detected overlap is rejected with `ERR_COVERAGE_WINDOW_OVERLAP` (HTTP 409)."

    Two HEALTH_FSA windows sharing the boundary day 2026-06-30 collide.

    Design: Difficulty/resource_temporal_overlap/health_fsa_closed_interval_shared_boundary_collides
    """
    set_clock("2026-01-15T00:00:00Z")
    py1 = create_plan_year(label="PY-H1", coverage_start="2026-01-01",
                           coverage_end="2026-06-30", run_out_end="2026-09-30")
    py2 = create_plan_year(label="PY-H2", coverage_start="2026-06-30",
                           coverage_end="2026-12-31", run_out_end="2027-03-31")
    p = create_participant(email="p8a@x.com")
    create_account(p["id"], py1["id"], "HEALTH_FSA", elected_amount_cents=100000)
    resp = api.create_account(
        create_account_payload(p["id"], py2["id"], "HEALTH_FSA", elected_amount_cents=100000),
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_COVERAGE_WINDOW_OVERLAP.value)


def test_health_fsa_overlap_rejection_does_not_persist_second_account(api):
    """PRD §3.2: "Opening a Health FSA or DCFSA also runs a coverage-window-overlap guard
    against the participant's existing non-`CLOSED` accounts of the same `account_type`."

    The participant still has exactly one HEALTH_FSA after the collision is rejected.

    Design: Difficulty/resource_temporal_overlap/health_fsa_closed_interval_shared_boundary_collides
    """
    set_clock("2026-01-15T00:00:00Z")
    py1 = create_plan_year(label="PY-H1", coverage_start="2026-01-01",
                           coverage_end="2026-06-30", run_out_end="2026-09-30")
    py2 = create_plan_year(label="PY-H2", coverage_start="2026-06-30",
                           coverage_end="2026-12-31", run_out_end="2027-03-31")
    p = create_participant(email="p8a2@x.com")
    create_account(p["id"], py1["id"], "HEALTH_FSA", elected_amount_cents=100000)
    api.create_account(
        create_account_payload(p["id"], py2["id"], "HEALTH_FSA", elected_amount_cents=100000),
        ADMIN)
    rows, _ = validate_paginated(api.list_accounts(
        ADMIN, params={"participant_id": p["id"], "account_type": "HEALTH_FSA"}))
    assert len(rows) == 1, "the overlapping second account was not created"


def test_dcfsa_half_open_interval_shared_boundary_permitted(api):
    """PRD §3.2: "For a DCFSA the interval is half-open, from `coverage_start` up to but not
    including `coverage_end`; two DCFSA windows collide when the new account's start is
    strictly before the existing account's `coverage_end` and the existing account's start is
    strictly before the new account's `coverage_end` — so a shared boundary day is not a
    collision, and back-to-back DCFSA years are permitted."

    Two DCFSA windows abutting at 2026-12-31 do not collide; the second opens (201).

    Design: Difficulty/resource_temporal_overlap/dcfsa_half_open_interval_shared_boundary_permitted
    """
    set_clock("2026-01-15T00:00:00Z")
    py1 = create_plan_year(label="PY-D1", coverage_start="2026-01-01",
                           coverage_end="2026-12-31", run_out_end="2027-03-31")
    py2 = create_plan_year(label="PY-D2", coverage_start="2026-12-31",
                           coverage_end="2027-12-31", run_out_end="2028-03-31")
    p = create_participant(email="p8b@x.com", marital_status="SINGLE")
    create_account(p["id"], py1["id"], "DCFSA", elected_amount_cents=300000)
    resp = api.create_account(
        create_account_payload(p["id"], py2["id"], "DCFSA", elected_amount_cents=300000),
        ADMIN)
    validate_success(resp, expected_status=201)


def test_dcfsa_back_to_back_years_both_persist(api):
    """PRD §3.2: "a shared boundary day is not a collision, and back-to-back DCFSA years are
    permitted."

    Both abutting DCFSA accounts exist for the participant after the second opens.

    Design: Difficulty/resource_temporal_overlap/dcfsa_half_open_interval_shared_boundary_permitted
    """
    set_clock("2026-01-15T00:00:00Z")
    py1 = create_plan_year(label="PY-D1", coverage_start="2026-01-01",
                           coverage_end="2026-12-31", run_out_end="2027-03-31")
    py2 = create_plan_year(label="PY-D2", coverage_start="2026-12-31",
                           coverage_end="2027-12-31", run_out_end="2028-03-31")
    p = create_participant(email="p8b2@x.com", marital_status="SINGLE")
    create_account(p["id"], py1["id"], "DCFSA", elected_amount_cents=300000)
    validate_success(api.create_account(
        create_account_payload(p["id"], py2["id"], "DCFSA", elected_amount_cents=300000),
        ADMIN), expected_status=201)
    rows, _ = validate_paginated(api.list_accounts(
        ADMIN, params={"participant_id": p["id"], "account_type": "DCFSA"}))
    assert len(rows) == 2, "both back-to-back DCFSA accounts exist"


def test_create_account_with_dangling_participant_id_returns_not_found(api):
    """PRD §2.8: "Body-referenced foreign keys — `account_id`, `plan_year_id`,
    `participant_id`, and every member of `claim_ids` — are likewise required to reference
    existing entities, and a dangling reference is rejected with the same
    `ERR_RESOURCE_NOT_FOUND`."

    Design: Corner/errors/resource_not_found_on_account_body_fk
    """
    py, _ = setup_plan_year_and_participant(clock=None)
    resp = api.create_account(
        create_account_payload(
            "00000000-0000-4000-8000-000000000000", py["id"], "HEALTH_FSA",
            elected_amount_cents=100000),
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)
