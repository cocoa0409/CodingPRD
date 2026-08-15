"""Claim screening: clean path, state gates, fiscal checks, provider
termination, DRG table closure, high-dollar threshold and its IBR cascade,
immediate consistency, and list filtering with default pagination."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_claim_line_payload,
    create_claim_with_lines,
    create_provider,
    get_abrasion_profile,
    get_claim,
    get_claim_ibr,
    make_adjudicator_headers,
    make_provider_headers,
    run_claim_edits,
    screen_one_line_claim,
    setup_provider_with_active_edit,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["plan_admin_headers"]


def test_clean_claim_screens_straight_to_ready_to_pay(api):
    """PRD §3.4: "When the run produced none of those, the claim goes straight
    to `READY_TO_PAY` and its `determined_at` — null until the claim is first
    determined — is stamped, anchoring the dispute window of Section 3.6."
    PRD §3.4: "For non-inpatient claims the baseline is simply
    `total_billed_cents`. Either way, `initial_allowed_cents` is set to that
    baseline, `allowed_amount_cents` starts equal to it, and
    `denied_amount_cents` starts at zero."

    Design: Corner/state_machines/clean_claim_screens_straight_to_ready_to_pay
    """
    provider = create_provider(npi="NPI-SM3", name="Clean Prov")
    claim = screen_one_line_claim(provider["id"], billed=12345,
                                  claim_number="CL1", member_id="M-CL1")
    assert claim["status"] == "READY_TO_PAY"
    assert claim["allowed_amount_cents"] == 12345
    assert claim["denied_amount_cents"] == 0
    assert claim["high_dollar_flag"] is False
    assert claim["readmission_flag"] is False
    assert claim["determined_at"] is not None, (
        "determined_at is stamped even on the clean path"
    )


def test_run_edits_twice_rejected(api):
    """PRD §3.4: "the claim must be `RECEIVED`, else
    `ERR_CLAIM_NOT_SCREENABLE` (HTTP 409)"

    Design: Corner/state_machines/run_edits_twice_rejected
    """
    provider = create_provider(npi="NPI-SM4", name="Re Prov")
    claim = screen_one_line_claim(provider["id"], billed=5000,
                                  claim_number="RE1", member_id="M-RE1")
    assert claim["status"] == "READY_TO_PAY"
    resp = api.run_edits(claim["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_SCREENABLE,
                   expected_status=409)


def test_claim_lines_locked_after_screening(api):
    """PRD §3.4: "Once the claim has left `RECEIVED` its lines are locked, and
    adding another is rejected with `ERR_CLAIM_LINES_LOCKED` (HTTP 409)."

    Design: Corner/validations/claim_lines_locked_after_screening
    """
    provider = create_provider(npi="NPI-LK", name="Lock Prov")
    claim = screen_one_line_claim(provider["id"], billed=5000,
                                  claim_number="LK1", member_id="M-LK1")
    assert claim["status"] == "READY_TO_PAY"
    resp = api.add_claim_line(
        claim["id"], create_claim_line_payload(2, "99214", 100),
        make_provider_headers(provider["id"]))
    validate_error(resp, ApiErrorId.ERR_CLAIM_LINES_LOCKED, expected_status=409)
    _lines, meta = validate_paginated(api.list_claim_lines(claim["id"], ADMIN))
    assert meta["total_count"] == 1, "the claim still has exactly one line"


def test_line_amount_mismatch_and_missing_lines(api):
    """PRD §3.4: "the claim must carry at least one line, else
    `ERR_NO_CLAIM_LINES` (HTTP 422), and the line `billed_cents` must sum
    exactly to the header `total_billed_cents`, else
    `ERR_LINE_AMOUNT_MISMATCH` (HTTP 422)."

    Design: Corner/validations/line_amount_mismatch_and_missing_lines
    """
    provider = create_provider(npi="NPI-LM", name="Line Prov")
    claim_a = create_claim_with_lines(
        provider["id"], lines=((1, "99213", 500),), claim_number="LM1",
        member_id="M-LM1", total_billed_cents=1000)
    resp_a = api.run_edits(claim_a["id"], ADMIN)
    validate_error(resp_a, ApiErrorId.ERR_LINE_AMOUNT_MISMATCH,
                   expected_status=422)
    assert get_claim(claim_a["id"])["status"] == "RECEIVED"

    claim_b = create_claim_with_lines(
        provider["id"], lines=(), claim_number="LM2", member_id="M-LM2",
        total_billed_cents=1000)
    resp_b = api.run_edits(claim_b["id"], ADMIN)
    validate_error(resp_b, ApiErrorId.ERR_NO_CLAIM_LINES, expected_status=422)
    assert get_claim(claim_b["id"])["status"] == "RECEIVED"


def test_run_edits_on_terminated_provider_rejected(api):
    """PRD §3.4: "the provider must still be `ACTIVE`, else
    `ERR_PROVIDER_TERMINATED` (HTTP 422)"
    PRD §3.1: "the plan may later patch that `status` to `TERMINATED`, after
    which the provider's claims can no longer pass screening (Section 3.4)."

    Design: Corner/validations/run_edits_on_terminated_provider_rejected
    """
    provider = create_provider(npi="NPI-TP", name="Term Prov")
    claim = create_claim_with_lines(provider["id"], claim_number="TP1",
                                    member_id="M-TP1", total_billed_cents=5000,
                                    lines=((1, "99213", 5000),))
    validate_success(api.patch_provider(provider["id"], {"status": "TERMINATED"},
                                        ADMIN))
    resp = api.run_edits(claim["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROVIDER_TERMINATED,
                   expected_status=422)
    assert get_claim(claim["id"])["status"] == "RECEIVED"


def test_unknown_drg_code_at_screening_rejected(api):
    """PRD §3.4: "for an inpatient claim the `drg_code` must be a known DRG
    weight key, else `ERR_DRG_CODE_UNKNOWN` (HTTP 422)"
    PRD §3.4: "the weight table holds 1.5 for DRG 470, 0.95 for DRG 193, and
    0.72 for DRG 392"

    Design: Corner/validations/unknown_drg_code_at_screening_rejected
    """
    provider = create_provider(npi="NPI-DG", name="Drg Prov")
    claim = create_claim_with_lines(
        provider["id"], claim_number="DG1", member_id="M-DG1",
        claim_type="INSTITUTIONAL_INPATIENT", total_billed_cents=500000,
        service_from="2026-07-01T00:00:00Z", service_to="2026-07-05T00:00:00Z",
        admission_date="2026-07-01T00:00:00Z",
        discharge_date="2026-07-05T00:00:00Z", drg_code="999",
        discharge_disposition="HOME", lines=((1, "REV-010", 500000),))
    resp = api.run_edits(claim["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_DRG_CODE_UNKNOWN, expected_status=422)
    assert get_claim(claim["id"])["status"] == "RECEIVED"


def test_adjudicator_cannot_run_edits(api):
    """PRD §2.1: "A request whose role is not listed among the roles
    authorized for the target endpoint is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: run-edits is authorized for PlanAdmin only.

    Design: Corner/rbac/adjudicator_cannot_run_edits
    """
    provider = create_provider(npi="NPI-ADJ", name="Adj Prov")
    claim = create_claim_with_lines(provider["id"], claim_number="AD1",
                                    member_id="M-AD1", total_billed_cents=5000,
                                    lines=((1, "99213", 5000),))
    resp = api.run_edits(claim["id"], make_adjudicator_headers("adj-1"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)
    assert get_claim(claim["id"])["status"] == "RECEIVED"


def test_run_edits_response_immediately_reflects_screening(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.4: "When the run produced any applied hit, any auto-created review,
    or a true `high_dollar_flag`, the claim becomes `PENDED`."
    PRD §3.4: "Either way the run increments the claim's `version` by one."

    Design: Corner/consistency_model/run_edits_response_immediately_reflects_screening
    """
    provider, _rule, _version = setup_provider_with_active_edit(
        npi="NPI-IM", edit_code="IM-DENY")
    created = create_claim_with_lines(provider["id"], claim_number="IM1",
                                      member_id="M-IM1", total_billed_cents=40000,
                                      lines=((1, "99213", 40000),))
    screened = validate_success(api.run_edits(created["id"], ADMIN))
    assert screened["status"] == "PENDED"
    assert screened["allowed_amount_cents"] == 0
    assert screened["denied_amount_cents"] == 40000
    assert screened["version"] == created["version"] + 1, (
        "the screening response itself carries the incremented version"
    )


def test_claims_filter_pagination_interaction(api):
    """PRD §3.4: "Claims can be listed with optional `provider_id`, `status`,
    and `member_id` filters"
    PRD §2.3: "The `limit` defaults to 10, must be at least 1, and may not
    exceed 100; the `offset` defaults to 0. The `meta` object of every list
    response carries `limit`, `offset`, `total_count`, and `has_more`"

    Design: Corner/cross_cutting_layers/claims_filter_pagination_interaction
    """
    provider, _rule, _version = setup_provider_with_active_edit(
        npi="NPI-PG", edit_code="PG-DENY")
    pended = screen_one_line_claim(provider["id"], billed=30000,
                                   claim_number="PG1", member_id="M-PG1")
    # The ACTIVE edit covers PROFESSIONAL only (PRD 3.4 eligibility), so the
    # clean claim is INSTITUTIONAL_OUTPATIENT — no eligible edit fires on it.
    clean_created = create_claim_with_lines(
        provider["id"], lines=((1, "99213", 5000),), claim_number="PG2",
        member_id="M-PG2", claim_type="INSTITUTIONAL_OUTPATIENT")
    clean = run_claim_edits(clean_created["id"])
    assert pended["status"] == "PENDED"
    assert clean["status"] == "READY_TO_PAY"

    data, meta = validate_paginated(api.list_claims(
        ADMIN, params={"provider_id": provider["id"], "status": "PENDED"}))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert meta["limit"] == 10, "default limit applies"
    assert data[0]["id"] == pended["id"]

    _all, meta_all = validate_paginated(
        api.list_claims(ADMIN, params={"provider_id": provider["id"]}))
    assert meta_all["total_count"] == 2


def test_high_dollar_exact_threshold_flags(api):
    """PRD §3.4: "The high-dollar check flags the claim when
    `total_billed_cents` reaches 10,000,000 cents ($100,000.00) — the boundary
    is inclusive, so exactly 10,000,000 cents flags and 9,999,999 does not —
    and sets `high_dollar_flag` accordingly."
    PRD §3.4: "A flagged claim immediately spawns an itemized bill review in
    `REQUESTED` with `due_at` set thirty days out"

    Design: Difficulty/boundary_precision_check/high_dollar_exact_threshold_flags
    """
    provider = create_provider(npi="NPI-B6", name="Boundary Prov")
    claim = screen_one_line_claim(provider["id"], billed=10000000,
                                  claim_number="B6A", member_id="M-B6A")
    assert claim["high_dollar_flag"] is True, "exactly 10000000 flags (>=)"
    assert claim["status"] == "PENDED"
    ibr = get_claim_ibr(claim["id"])
    assert ibr["status"] == "REQUESTED"


def test_high_dollar_below_threshold_does_not_flag(api):
    """PRD §3.4: "The high-dollar check flags the claim when
    `total_billed_cents` reaches 10,000,000 cents ($100,000.00) — the boundary
    is inclusive, so exactly 10,000,000 cents flags and 9,999,999 does not —
    and sets `high_dollar_flag` accordingly."
    PRD §3.4: "When the run produced none of those, the claim goes straight to
    `READY_TO_PAY`"

    Design: Difficulty/boundary_precision_check/high_dollar_exact_threshold_flags
    """
    provider = create_provider(npi="NPI-B6B", name="Below Prov")
    claim = screen_one_line_claim(provider["id"], billed=9999999,
                                  claim_number="B6B", member_id="M-B6B")
    assert claim["high_dollar_flag"] is False, "9999999 must not flag"
    assert claim["status"] == "READY_TO_PAY"
    _rows, meta = validate_paginated(
        api.list_ibrs(ADMIN, params={"claim_id": claim["id"]}))
    assert meta["total_count"] == 0, "no itemized bill review may be created"


def test_high_dollar_ibr_chain_flag_pends_and_spawns_ibr(api):
    """PRD §3.4: "A flagged claim immediately spawns an itemized bill review
    in `REQUESTED` with `due_at` set thirty days out"
    PRD §3.4: "When the run produced any applied hit, any auto-created review,
    or a true `high_dollar_flag`, the claim becomes `PENDED`."
    PRD §2.6: "At server startup the logical clock reads exactly
    2026-08-01T00:00:00Z"

    Design: Difficulty/transitive_cascade/run_edits_high_dollar_ibr_chain
    """
    provider = create_provider(npi="NPI-H1", name="HighDollar Prov")
    claim = screen_one_line_claim(provider["id"], billed=10000000,
                                  claim_number="HD1", member_id="M-H1")
    assert claim["high_dollar_flag"] is True
    assert claim["status"] == "PENDED"

    ibr = get_claim_ibr(claim["id"])
    assert ibr["status"] == "REQUESTED"
    assert ibr["due_at"].startswith("2026-08-31T00:00:00"), (
        f"due_at = default clock + 30 days, got {ibr['due_at']}"
    )


def test_high_dollar_ibr_chain_increments_open_ibr_count(api):
    """PRD §3.4: "A flagged claim immediately spawns an itemized bill review
    in `REQUESTED` with `due_at` set thirty days out, and that creation adds
    one to the provider's `open_ibr_count`."
    PRD §3.1: "The `open_ibr_count` tracks how many of the provider's itemized
    bill reviews currently sit in `REQUESTED`, `DOCUMENTS_RECEIVED`, or
    `IN_AUDIT`."

    Design: Difficulty/transitive_cascade/run_edits_high_dollar_ibr_chain
    """
    provider = create_provider(npi="NPI-H2", name="HighDollar Prov 2")
    assert get_abrasion_profile(provider["id"])["open_ibr_count"] == 0
    claim = screen_one_line_claim(provider["id"], billed=10000000,
                                  claim_number="HD2", member_id="M-H2")
    assert claim["high_dollar_flag"] is True
    profile = get_abrasion_profile(provider["id"])
    assert profile["open_ibr_count"] == 1, (
        "the auto-created REQUESTED review opens provider audit occupancy"
    )
