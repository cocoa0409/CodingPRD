"""Reimbursement drawdowns: reimbursable calculation, obligation ledger, OCC, pagination."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    setup_active_subaward,
    setup_active_subaward_with_drawdown,
    setup_draft_subaward,
    submit_drawdown,
    get_subaward,
    get_nonprofit,
    MTDC_BUDGET_LINES,
    create_drawdown_payload,
    make_subrecipient_headers,
    make_grants_manager_headers,
    make_program_officer_headers,
)


def test_drawdown_provisional_reimbursable_at_submit(api):
    """PRD §3.6: "the provisional reimbursable amount, provisional_reimbursable_cents, is set
    to the smaller of requested_amount_cents and that available headroom, the drawdown's
    reimbursable_cents is set equal to it, the subaward's obligated_cents is debited by that
    amount, and the subaward's version is incremented by one."

    requested 5000000, available 26200000 -> provisional 5000000.

    Design: Difficulty/dual_variant_calc/drawdown_provisional_vs_final_reimbursable
    """
    ctx = setup_active_subaward(requested_amount_cents=26_200_000, budget_lines=MTDC_BUDGET_LINES)
    dd = submit_drawdown(ctx["sub_id"], ctx["np_id"], 5_000_000, ctx["version"])
    assert dd["provisional_reimbursable_cents"] == 5_000_000
    assert dd["reimbursable_cents"] == 5_000_000


def test_drawdown_final_reimbursable_subtracts_disallowed(api):
    """PRD §3.6: "the final reimbursable amount, final_reimbursable_cents, is set to the
    smaller of requested_amount_cents minus disallowed_amount_cents and the same available
    headroom that was measured at submission. The drawdown's reimbursable_cents becomes this
    final value, the subaward's obligated_cents is adjusted by the difference between the final
    and the earlier provisional amount."

    requested 5000000, disallowed 750000, available 26200000 -> final 4250000, obligated 4250000.

    Design: Difficulty/dual_variant_calc/drawdown_provisional_vs_final_reimbursable
    """
    ctx = setup_active_subaward(requested_amount_cents=26_200_000, budget_lines=MTDC_BUDGET_LINES)
    dd = submit_drawdown(ctx["sub_id"], ctx["np_id"], 5_000_000, ctx["version"])
    approved = validate_success(
        api.approve_drawdown(dd["id"], {"disallowed_amount_cents": 750_000},
                             make_grants_manager_headers("gm-1")),
        200,
    )
    assert approved["final_reimbursable_cents"] == 4_250_000
    assert get_subaward(ctx["sub_id"])["obligated_cents"] == 4_250_000


def test_drawdown_over_available_budget_rejected(api):
    """PRD §3.6: "If requested_amount_cents exceeds that available headroom the submission is
    rejected with ERR_INSUFFICIENT_BUDGET."

    Design: Corner/validations/drawdown_over_available_budget_rejected
    """
    ctx = setup_active_subaward()  # total 11000000, obligated 0
    payload = create_drawdown_payload(12_000_000, ctx["version"])
    res = api.create_drawdown(ctx["sub_id"], payload, make_subrecipient_headers(ctx["np_id"]))
    validate_error(res, "ERR_INSUFFICIENT_BUDGET")


def test_drawdown_on_draft_subaward_rejected(api):
    """PRD §3.6: "A drawdown created against a subaward that is not ACTIVE is rejected with
    ERR_SUBAWARD_NOT_ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/drawdown_requires_active_subaward
    """
    ctx = setup_draft_subaward()
    version = get_subaward(ctx["sub_id"])["version"]
    payload = create_drawdown_payload(100_000, version)
    res = api.create_drawdown(ctx["sub_id"], payload, make_subrecipient_headers(ctx["np_id"]))
    validate_error(res, "ERR_SUBAWARD_NOT_ACTIVE")


def test_drawdown_on_draft_subaward_creates_nothing(api):
    """PRD §3.6: "A drawdown created against a subaward that is not ACTIVE is rejected with
    ERR_SUBAWARD_NOT_ACTIVE."

    A rejected create must not persist a drawdown on the subaward.

    Design: Difficulty/cross_entity_state_dependency/drawdown_requires_active_subaward
    """
    ctx = setup_draft_subaward()
    version = get_subaward(ctx["sub_id"])["version"]
    payload = create_drawdown_payload(100_000, version)
    validate_error(
        api.create_drawdown(ctx["sub_id"], payload, make_subrecipient_headers(ctx["np_id"])),
        "ERR_SUBAWARD_NOT_ACTIVE",
    )
    data, meta = validate_paginated(
        api.list_drawdowns(ctx["sub_id"], make_program_officer_headers())
    )
    assert meta["total_count"] == 0


def test_obligation_debited_on_submit(api):
    """PRD §3.6: "the subaward's `obligated_cents` is debited by that amount, and the subaward's
    `version` is incremented by one."

    Design: Difficulty/compensating_invariant/obligation_conserved_across_submit_then_return
    """
    ctx = setup_active_subaward_with_drawdown(drawdown_amount=5_000_000)
    assert get_subaward(ctx["sub_id"])["obligated_cents"] == 5_000_000


def test_obligation_conserved_after_submit_then_return(api):
    """PRD §3.6: "Returning a submitted drawdown instead moves it from SUBMITTED to RETURNED,
    optionally recording a reason: its reimbursable_cents is set to 0, the subaward's
    obligated_cents is credited back by the prior provisional_reimbursable_cents."

    After submit (debit 5000000) then return (credit 5000000), obligated_cents == 0.

    Design: Difficulty/compensating_invariant/obligation_conserved_across_submit_then_return
    """
    ctx = setup_active_subaward_with_drawdown(drawdown_amount=5_000_000)
    returned = validate_success(
        api.return_drawdown(ctx["dd_id"], {"reason": "docs missing"},
                            make_grants_manager_headers("gm-1")),
        200,
    )
    assert returned["status"] == "RETURNED"
    assert get_subaward(ctx["sub_id"])["obligated_cents"] == 0


def test_pay_increments_disbursed_and_cumulative(api):
    """PRD §3.6: "A ProgramOfficer disburses an approved drawdown by paying it, moving it from
    APPROVED to PAID, which adds its reimbursable_cents to the subaward's disbursed_cents and
    recomputes the nonprofit's cumulative_federal_expenditures_cents."

    Design: Corner/endpoints/drawdown_pay_increments_disbursed_and_cumulative
    """
    ctx = setup_active_subaward_with_drawdown(drawdown_amount=5_000_000)
    validate_success(
        api.approve_drawdown(ctx["dd_id"], {}, make_grants_manager_headers("gm-1")), 200
    )
    validate_success(api.pay_drawdown(ctx["dd_id"], make_program_officer_headers()), 200)

    assert get_subaward(ctx["sub_id"])["disbursed_cents"] == 5_000_000
    assert get_nonprofit(ctx["np_id"])["cumulative_federal_expenditures_cents"] == 5_000_000


def test_second_drawdown_with_stale_version_rejected(api):
    """PRD §2.8: "When `expected_subaward_version` does not equal the subaward's current
    `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/drawdown_create_stale_subaward_version_returns_412
    """
    ctx = setup_active_subaward()
    stale_version = ctx["version"]
    submit_drawdown(ctx["sub_id"], ctx["np_id"], 1_000_000, stale_version)  # advances version

    payload = create_drawdown_payload(
        1_000_000, stale_version,
        period_covered_start="2026-07-01T00:00:00Z", period_covered_end="2026-07-31T00:00:00Z",
    )
    res = api.create_drawdown(ctx["sub_id"], payload, make_subrecipient_headers(ctx["np_id"]))
    validate_error(res, "ERR_STALE_VERSION")


def test_drawdowns_list_pagination_envelope(api):
    """PRD §2.3: "The limit parameter caps the number of items returned; it defaults to 10,
    with a minimum of 1 and a maximum of 100. ... Every list response echoes limit, offset,
    total_count, and has_more in the envelope's meta object."

    Design: Corner/endpoints/drawdowns_list_pagination_envelope
    """
    ctx = setup_active_subaward()
    submit_drawdown(ctx["sub_id"], ctx["np_id"], 1_000_000, ctx["version"])
    v2 = get_subaward(ctx["sub_id"])["version"]
    submit_drawdown(
        ctx["sub_id"], ctx["np_id"], 1_000_000, v2,
        period_start="2026-07-01T00:00:00Z", period_end="2026-07-31T00:00:00Z",
    )

    data, meta = validate_paginated(
        api.list_drawdowns(ctx["sub_id"], make_program_officer_headers(), params={"limit": 1, "offset": 0})
    )
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_approve_already_approved_drawdown_rejected(api):
    """PRD §3.6: "Any drawdown transition attempted from an illegal state is rejected with
    ERR_INVALID_DRAWDOWN_STATE."

    Design: Corner/state_machines/approve_already_approved_drawdown_rejected
    """
    ctx = setup_active_subaward_with_drawdown(drawdown_amount=5_000_000)
    validate_success(
        api.approve_drawdown(ctx["dd_id"], {}, make_grants_manager_headers("gm-1")), 200
    )
    res = api.approve_drawdown(ctx["dd_id"], {}, make_grants_manager_headers("gm-1"))
    validate_error(res, "ERR_INVALID_DRAWDOWN_STATE")
