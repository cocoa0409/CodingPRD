"""Stop notices and bond claims on public projects: eligibility gates, closed
coverage overlap, deadlines, lazy expiry, and resolution (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    create_bond_claim,
    create_company,
    create_party,
    create_project,
    create_stop_notice,
    make_customer_admin_headers,
    set_clock,
    setup_tx_public_project,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as api
from test_helpers.factories import (
    create_bond_claim_payload,
    create_stop_notice_payload,
)
from test_helpers.test_users import TEST_USERS

_PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
_OPS_AGENT = TEST_USERS["ops_agent_headers"]


# ─── Closed-interval coverage overlap (queue A: resource_temporal_overlap) ──

def _setup_served_stop_notice():
    """TX STATE_PUBLIC project (span 2026-05-02..2026-06-10, so the stop-notice
    deadline is 2026-07-10) with stop notice A covering [2026-06-01,
    2026-06-30] SERVED on 2026-06-20."""
    ctx = setup_tx_public_project()
    notice_a = create_stop_notice(
        ctx["project"]["id"], ctx["company"]["id"],
        amount_cents=50000, coverage_start="2026-06-01",
        coverage_end="2026-06-30",
    )
    notice_a = validate_success(
        api.serve_stop_notice(notice_a["id"], {"served_at": "2026-06-20"},
                              _OPS_AGENT),
        200,
    )
    assert notice_a["status"] == "SERVED"
    return ctx, notice_a


def test_stop_notice_boundary_touch_is_overlap():
    """PRD §3.7: "Coverage intervals must not collide: if the new notice's
    interval overlaps that of a `SERVED` stop notice on the same project — and
    sharing even a single boundary day counts as overlap — the request fails
    with `ERR_STOP_NOTICE_OVERLAP` (HTTP 409)"
    (new coverage_start 2026-06-30 touches the served notice's coverage_end.)

    Design: Difficulty/resource_temporal_overlap/stop_notice_closed_interval_overlap
    """
    ctx, _notice_a = _setup_served_stop_notice()

    res = api.create_stop_notice(
        create_stop_notice_payload(
            ctx["project"]["id"], amount_cents=30000,
            coverage_start="2026-06-30", coverage_end="2026-07-15",
        ),
        make_customer_admin_headers(ctx["company"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_STOP_NOTICE_OVERLAP)


def test_stop_notice_one_day_clear_accepted():
    """PRD §3.7: "the claimed coverage as `coverage_start` and `coverage_end` —
    a closed interval including both endpoints, with `coverage_end` never
    earlier than `coverage_start`." and "if the new notice's interval overlaps
    that of a `SERVED` stop notice on the same project — and sharing even a
    single boundary day counts as overlap — the request fails with
    `ERR_STOP_NOTICE_OVERLAP` (HTTP 409)"
    (starting 2026-07-01, one day after the served interval ends, is clear.)

    Design: Difficulty/resource_temporal_overlap/stop_notice_closed_interval_overlap
    """
    ctx, _notice_a = _setup_served_stop_notice()

    notice_c = create_stop_notice(
        ctx["project"]["id"], ctx["company"]["id"],
        amount_cents=30000, coverage_start="2026-07-01",
        coverage_end="2026-07-15",
    )
    assert notice_c["status"] == "DRAFT"


# ─── Public-remedy eligibility gates (queue B) ───────────────────────

def test_stop_notice_on_private_project_rejected():
    """PRD §3.7: "Only a `STATE_PUBLIC` project accepts a stop notice; any other
    project type is rejected with `ERR_STOP_NOTICE_NOT_PERMITTED` (HTTP 422)."

    Design: Corner/validations/stop_notice_on_private_project_rejected
    """
    company = create_company(name="SP Co")
    project = create_project(company["id"], name="SP Job")

    res = api.create_stop_notice(
        create_stop_notice_payload(
            project["id"], amount_cents=5000,
            coverage_start="2026-06-01", coverage_end="2026-06-30",
        ),
        make_customer_admin_headers(company["id"]),
    )
    validate_error(res, ApiErrorId.ERR_STOP_NOTICE_NOT_PERMITTED)


def test_bond_claim_on_private_project_rejected():
    """PRD §3.7: "The project must be `STATE_PUBLIC` or `FEDERAL_PUBLIC`;
    private projects are rejected with `ERR_BOND_CLAIM_NOT_PERMITTED`
    (HTTP 422)."

    Design: Corner/validations/bond_claim_on_private_project_rejected
    """
    company = create_company(name="BP Co")
    project = create_project(company["id"], name="BP Job")
    surety = create_party(project["id"], company["id"], "SURETY",
                          legal_name="SureBond", address="1 Bp Ave")

    res = api.create_bond_claim(
        create_bond_claim_payload(project["id"], surety["id"], amount_cents=5000),
        make_customer_admin_headers(company["id"]),
    )
    validate_error(res, ApiErrorId.ERR_BOND_CLAIM_NOT_PERMITTED)


# ─── Stop notice / bond claim lifecycle edges (queue B) ──────────────

def test_stop_notice_clock_expiry():
    """PRD §3.7: "A `DRAFT` notice whose deadline falls behind the logical clock
    auto-expires to `EXPIRED`, lazily, on its next read or mutation."
    (deadline 2026-07-10 = last furnishing 2026-06-10 + 30 days; clock moved to
    2026-07-11.)

    Design: Corner/state_machines/stop_notice_clock_expiry
    """
    ctx = setup_tx_public_project()
    create_stop_notice(ctx["project"]["id"], ctx["company"]["id"],
                       amount_cents=50000, coverage_start="2026-06-01",
                       coverage_end="2026-06-30")

    set_clock("2026-07-11T00:00:00Z")

    notices, meta = validate_paginated(
        api.list_project_stop_notices(ctx["project"]["id"], _OPS_AGENT)
    )
    assert meta["total_count"] == 1
    assert notices[0]["status"] == "EXPIRED"


def test_bond_claim_resolve_twice_rejected():
    """PRD §3.7: "An `OpsAgent` later resolves a `SUBMITTED` claim with an
    `outcome`: the claim becomes `PAID` or `DENIED`, the `resolve_outcome` —
    null until resolution — is recorded accordingly, and the posture is
    recomputed."
    PRD §2.10: "when no specific state error applies, the generic
    `ERR_INVALID_STATE` is used."

    Design: Corner/state_machines/bond_claim_resolve_twice_rejected
    """
    ctx = setup_tx_public_project()
    surety = create_party(ctx["project"]["id"], ctx["company"]["id"], "SURETY",
                          legal_name="SureBond", address="1 Bc Ave")
    claim = create_bond_claim(ctx["project"]["id"], ctx["company"]["id"],
                              surety["id"], amount_cents=70000)

    submitted = validate_success(
        api.submit_bond_claim(claim["id"], {"submitted_at": "2026-07-01"},
                              _OPS_AGENT),
        200,
    )
    assert submitted["status"] == "SUBMITTED"

    resolved = validate_success(
        api.resolve_bond_claim(claim["id"], {"outcome": "PAID"}, _OPS_AGENT),
        200,
    )
    assert resolved["status"] == "PAID"
    assert resolved["resolve_outcome"] == "PAID"

    res = api.resolve_bond_claim(claim["id"], {"outcome": "DENIED"}, _OPS_AGENT)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    claims, _meta = validate_paginated(
        api.list_project_bond_claims(ctx["project"]["id"], _OPS_AGENT)
    )
    assert claims[0]["status"] == "PAID"
    assert claims[0]["resolve_outcome"] == "PAID"
