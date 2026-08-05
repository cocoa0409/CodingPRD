"""ITA voucher obligation, the dual obligated/expended ledger, fiscal validations,
cross-entity program gating, and voucher listing."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    setup_training_ready, setup_obligated_voucher,
    create_voucher, obligate_voucher, area_version,
    create_voucher_payload,
    ADMIN, CM, FO, ANY,
)


# --- Dual-variant ledger: obligated (forward) vs expended (chronological) ---
def test_voucher_obligated_and_expended_diverge_after_partial_disbursement(api):
    """PRD §3.4: "A voucher tracks two figures with deliberately different algorithms:
    `amount_obligated_cents` is a forward-looking commitment fixed at the full authorized
    cost the moment the voucher is obligated, while `amount_expended_cents` is the
    chronological running sum of the voucher's posted disbursement amounts taken in
    creation order."

    Design: Difficulty/dual_variant_calc/ita_obligated_vs_expended
    """
    ctx = setup_obligated_voucher(api, authorized_cost_cents=800000)
    v_id = ctx["v_id"]
    validate_success(api.disburse_voucher(v_id, {"amount_cents": 300000}, FO), 201)
    validate_success(api.disburse_voucher(v_id, {"amount_cents": 200000}, FO), 201)
    v = validate_success(api.get_voucher(v_id, ANY))
    assert v["amount_obligated_cents"] == 800000, v
    assert v["amount_expended_cents"] == 500000, v
    assert v["amount_obligated_cents"] != v["amount_expended_cents"], v


def test_area_ledger_tracks_obligated_and_expended_separately(api):
    """PRD §3.4: "On success a new immutable disbursement record is created, the voucher's
    `amount_expended_cents` increases by the disbursed amount, the area's obligated budget
    decreases by that amount while its expended budget increases by the same amount, and
    the area's `version` increments by one."

    Design: Difficulty/dual_variant_calc/ita_obligated_vs_expended
    """
    ctx = setup_obligated_voucher(api, authorized_cost_cents=800000)
    validate_success(api.disburse_voucher(ctx["v_id"], {"amount_cents": 300000}, FO), 201)
    validate_success(api.disburse_voucher(ctx["v_id"], {"amount_cents": 200000}, FO), 201)
    area = validate_success(api.get_local_area(ctx["la_id"], ANY))
    assert area["ita_budget_available_cents"] == 4200000, area
    assert area["ita_budget_obligated_cents"] == 300000, area
    assert area["ita_budget_expended_cents"] == 500000, area


# --- ITA individual cap: exact boundary ---
def test_obligate_at_exact_individual_cap_succeeds(api):
    """PRD §3.4: "the authorized cost must not exceed the area's `ita_individual_cap_cents`
    (`ERR_ITA_CAP_EXCEEDED`)".

    Design: Difficulty/boundary_precision_check/ita_cap_exact_boundary
    """
    ctx = setup_training_ready(api)  # individual cap 800000
    v1 = create_voucher(api, ctx["p_id"], ctx["prog_id"], ctx["cp_id"],
                        authorized_cost_cents=800000,
                        planned_start_date="2026-06-01T00:00:00Z",
                        planned_end_date="2026-08-01T00:00:00Z")
    obligated = obligate_voucher(api, v1["id"], ctx["la_version"])
    assert obligated["status"] == "OBLIGATED", obligated


def test_obligate_one_cent_over_individual_cap_rejected(api):
    """PRD §3.4: "the authorized cost must not exceed the area's `ita_individual_cap_cents`
    (`ERR_ITA_CAP_EXCEEDED`)".

    Design: Difficulty/boundary_precision_check/ita_cap_exact_boundary
    """
    ctx = setup_training_ready(api)  # individual cap 800000, program cost 1000000
    v1 = create_voucher(api, ctx["p_id"], ctx["prog_id"], ctx["cp_id"],
                        authorized_cost_cents=800000,
                        planned_start_date="2026-06-01T00:00:00Z",
                        planned_end_date="2026-08-01T00:00:00Z")
    obligate_voucher(api, v1["id"], ctx["la_version"])
    v2 = create_voucher(api, ctx["p_id"], ctx["prog_id"], ctx["cp_id"],
                        authorized_cost_cents=800001,
                        planned_start_date="2026-08-01T00:00:00Z",
                        planned_end_date="2026-10-01T00:00:00Z")
    fresh = area_version(api, ctx["la_id"])
    resp = api.obligate_voucher(v2["id"], {"expected_local_area_version": fresh}, CM)
    validate_error(resp, ApiErrorId.ERR_ITA_CAP_EXCEEDED.value)


def test_obligate_over_available_budget_rejected(api):
    """PRD §3.4: "the authorized cost must not exceed the area's `ita_budget_available_cents`
    (`ERR_ITA_BUDGET_EXCEEDED`)".

    Design: Corner/validations/obligate_over_budget_returns_budget_exceeded
    """
    ctx = setup_training_ready(api, area_overrides={"ita_budget_total_cents": 100000})
    v = create_voucher(api, ctx["p_id"], ctx["prog_id"], ctx["cp_id"],
                       authorized_cost_cents=200000)
    resp = api.obligate_voucher(v["id"], {"expected_local_area_version": ctx["la_version"]}, CM)
    validate_error(resp, ApiErrorId.ERR_ITA_BUDGET_EXCEEDED.value)


def test_disburse_over_remaining_obligation_rejected(api):
    """PRD §3.4: "The disbursed amount may not exceed the voucher's remaining unexpended
    obligation — that is, `amount_obligated_cents` minus `amount_expended_cents` —
    otherwise the post is rejected with `ERR_DISBURSEMENT_EXCEEDS_OBLIGATION`."

    Design: Corner/validations/disburse_over_obligation_returns_exceeds_obligation
    """
    ctx = setup_obligated_voucher(api, authorized_cost_cents=100000)
    resp = api.disburse_voucher(ctx["v_id"], {"amount_cents": 150000}, FO)
    validate_error(resp, ApiErrorId.ERR_DISBURSEMENT_EXCEEDS_OBLIGATION.value)


# --- Cross-entity: obligate gated on program eligibility ---
def test_obligate_with_suspended_program_rejected(api):
    """PRD §3.4: "the referenced program's status must be `ACTIVE`
    (`ERR_PROGRAM_NOT_ELIGIBLE`)".

    Design: Difficulty/cross_entity_state_dependency/obligate_requires_eligible_program
    """
    ctx = setup_training_ready(api)
    validate_success(api.suspend_provider(ctx["prov_id"], ADMIN))
    v = create_voucher(api, ctx["p_id"], ctx["prog_id"], ctx["cp_id"],
                       authorized_cost_cents=100000)
    resp = api.obligate_voucher(v["id"], {"expected_local_area_version": ctx["la_version"]}, CM)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ELIGIBLE.value)


def test_obligate_with_active_program_succeeds(api):
    """PRD §3.4: "the referenced program's status must be `ACTIVE`
    (`ERR_PROGRAM_NOT_ELIGIBLE`)". PRD §3.4: "On success the voucher moves to `OBLIGATED`".

    Design: Difficulty/cross_entity_state_dependency/obligate_requires_eligible_program
    """
    ctx = setup_training_ready(api)
    v = create_voucher(api, ctx["p_id"], ctx["prog_id"], ctx["cp_id"],
                       authorized_cost_cents=100000)
    obligated = obligate_voucher(api, v["id"], ctx["la_version"])
    assert obligated["status"] == "OBLIGATED", obligated


def test_create_voucher_nonexistent_program_not_found(api):
    """PRD §2.10: "the existence of the path resource and of every referenced foreign-key
    resource is checked, validated left-to-right along the URL so that the first identifier
    in the path that does not resolve produces `ERR_NOT_FOUND` (404) before any deeper
    lookup is attempted."

    Design: Corner/entities/create_voucher_nonexistent_program_returns_not_found
    """
    ctx = setup_training_ready(api)
    resp = api.create_voucher(
        ctx["p_id"],
        create_voucher_payload("00000000-0000-0000-0000-000000000000", ctx["cp_id"],
                               authorized_cost_cents=100000),
        CM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_cancel_completed_voucher_rejected(api):
    """PRD §3.4: "Cancelling a voucher is permitted from either `DRAFT` or `OBLIGATED`
    (rejected with `ERR_INVALID_STATE` from any other state) and moves it to `CANCELLED`."

    Design: Corner/state_machines/cancel_completed_voucher_returns_invalid_state
    """
    ctx = setup_obligated_voucher(api, authorized_cost_cents=100000)
    validate_success(api.complete_voucher(ctx["v_id"], {"credential_earned": False}, CM))
    resp = api.cancel_voucher(ctx["v_id"], CM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_list_vouchers_by_participant_returns_created_voucher(api):
    """PRD §3.4: "Creating a voucher under a participant fixes its `participant_id` and
    records the `program_id` of the ETPL program to be funded".

    Design: Corner/endpoints/list_vouchers_by_participant_returns_created_voucher
    """
    ctx = setup_training_ready(api)
    v = create_voucher(api, ctx["p_id"], ctx["prog_id"], ctx["cp_id"],
                       authorized_cost_cents=100000)
    resp = api.list_vouchers(ANY, params={"participant_id": ctx["p_id"]})
    data, _meta = validate_paginated(resp)
    ids = [row["id"] for row in data]
    assert v["id"] in ids, data
    match = next(row for row in data if row["id"] == v["id"])
    assert match["participant_id"] == ctx["p_id"], match


def test_disbursements_reverse_list_returns_posted_rows(api):
    """PRD §3.4: "On success a new immutable disbursement record is created, the voucher's
    `amount_expended_cents` increases by the disbursed amount".

    Design: Corner/endpoints/disbursements_reverse_list_returns_posted_rows
    """
    ctx = setup_obligated_voucher(api, authorized_cost_cents=100000)
    validate_success(api.disburse_voucher(ctx["v_id"], {"amount_cents": 30000}, FO), 201)
    resp = api.list_disbursements(ctx["v_id"], ANY)
    data, _meta = validate_paginated(resp)
    assert len(data) == 1, data
    assert data[0]["amount_cents"] == 30000, data
