"""Filing lifecycle: e-file branching, reject/reopen cycle, amendment cascade,
cross-entity state dependencies, and conserved-quantity invariants.

Translates difficulty queue A rules non_linear_state_machine, transitive_cascade,
cross_entity_state_dependency, compensating_invariant; plus corner queue B
state_machine instances.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_taxpayer_headers, make_irs_gateway_headers,
    efile_payload, acknowledge_payload, create_amended_return_payload,
    assert_balance_due_ledger_reconciles,
    setup_computed_return, setup_transmitted_efile, setup_filed_return,
    setup_rejected_return, setup_draft_amendment,
    create_income_document_payload,
)
from test_helpers import fixtures as FIX


# =====================================================================
# non_linear_state_machine / taxreturn_reject_reopen_recompute_refile_cycle
# =====================================================================

def test_reject_reopen_recompute_returns_to_ready(api):
    """PRD §3.6: "The taxpayer or preparer reopens it by editing the return with the
    `reopen` flag set true while the return is in `REJECTED`, which moves it
    `REJECTED → DRAFT` and increments its `version`."
    PRD §3.6: "The filer then corrects the children, recomputes (advancing
    `DRAFT → READY`), and re-transmits."

    Design: Difficulty/non_linear_state_machine/taxreturn_reject_reopen_recompute_refile_cycle
    """
    taxpayer, rejected, _ef = setup_rejected_return()
    h = make_taxpayer_headers(taxpayer["id"])
    assert rejected["status"] == "REJECTED"
    reopened = validate_success(
        api.patch_tax_return(rejected["id"], {"reopen": True}, h), 200)
    assert reopened["status"] == "DRAFT"
    recomputed = validate_success(api.compute_tax_return(rejected["id"], h), 200)
    assert recomputed["status"] == "READY"


def test_reopen_increments_version_then_recompute(api):
    """PRD §3.6: "The taxpayer or preparer reopens it by editing the return with the
    `reopen` flag set true while the return is in `REJECTED`, which moves it
    `REJECTED → DRAFT` and increments its `version`."
    PRD §3.5: "Each compute sets `computed_at` to the current time and increments the
    return's `version` by one."

    Design: Difficulty/non_linear_state_machine/taxreturn_reject_reopen_recompute_refile_cycle
    """
    taxpayer, rejected, _ef = setup_rejected_return()
    h = make_taxpayer_headers(taxpayer["id"])
    v_rejected = rejected["version"]
    reopened = validate_success(
        api.patch_tax_return(rejected["id"], {"reopen": True}, h), 200)
    assert reopened["version"] == v_rejected + 1
    recomputed = validate_success(api.compute_tax_return(rejected["id"], h), 200)
    assert recomputed["version"] == reopened["version"] + 1
    assert recomputed["status"] == "READY"


# =====================================================================
# non_linear_state_machine / efiling_transmitted_branches_accept_or_reject
# =====================================================================

def test_efile_transmitted_branches_to_accepted(api):
    """PRD §3.6: "When the outcome is `ACCEPTED`, the submission moves
    `TRANSMITTED → ACCEPTED`, its `ack_code` is set from the request, its `version`
    increments, and the parent return is driven `READY → FILED` with the return's
    `version` incremented."

    Design: Difficulty/non_linear_state_machine/efiling_transmitted_branches_accept_or_reject
    """
    taxpayer, _ret, efiling = setup_transmitted_efile()
    resp = api.acknowledge_efiling(
        efiling["id"], acknowledge_payload("ACCEPTED", "A0000"), make_irs_gateway_headers())
    acked = validate_success(resp, 200)
    assert acked["status"] == "ACCEPTED"
    ret_after = validate_success(
        api.get_tax_return(efiling["return_id"], make_taxpayer_headers(taxpayer["id"])), 200)
    assert ret_after["status"] == "FILED"


def test_efile_transmitted_branches_to_rejected(api):
    """PRD §3.6: "When the outcome is `REJECTED`, the submission moves
    `TRANSMITTED → REJECTED`, its `ack_code` is set from the request, its `version`
    increments, and the parent return is driven `READY → REJECTED` with the return's
    `version` incremented."

    Design: Difficulty/non_linear_state_machine/efiling_transmitted_branches_accept_or_reject
    """
    taxpayer, _ret, efiling = setup_transmitted_efile()
    resp = api.acknowledge_efiling(
        efiling["id"], acknowledge_payload("REJECTED", "R0001"), make_irs_gateway_headers())
    acked = validate_success(resp, 200)
    assert acked["status"] == "REJECTED"
    ret_after = validate_success(
        api.get_tax_return(efiling["return_id"], make_taxpayer_headers(taxpayer["id"])), 200)
    assert ret_after["status"] == "REJECTED"


# =====================================================================
# transitive_cascade / amend_file_cascades_three_levels_to_efiling
# =====================================================================

def test_amend_file_cascades_three_hops(api):
    """PRD §3.7: "the amendment delta is computed: `delta_cents` is set to
    `corrected_balance_due_cents` minus the original return's frozen `balance_due_cents`,
    and the amendment moves `DRAFT → FILED` with its `version` incremented. Second, the
    original return is driven `FILED → AMENDED`, refreshing its `updated_at` and
    incrementing its `version`. Third, that `AMENDED` transition cascades to the
    original return's `ACCEPTED` e-file submission, setting that submission's
    `superseded_by_amendment` flag to true and incrementing its `version` — marking the
    superseded submission for audit."

    Design: Difficulty/transitive_cascade/amend_file_cascades_three_levels_to_efiling
    """
    taxpayer, filed, efiling, amendment = setup_draft_amendment(
        corrected_balance_due_cents=50_000,
        correction_period_start="2025-01-01T00:00:00Z",
        correction_period_end="2025-12-31T00:00:00Z")
    h = make_taxpayer_headers(taxpayer["id"])
    filed_amd = validate_success(api.file_amended_return(amendment["id"], h), 200)
    assert filed_amd["status"] == "FILED"
    original_after = validate_success(api.get_tax_return(filed["id"], h), 200)
    assert original_after["status"] == "AMENDED"
    ef_after = validate_success(api.get_efiling(efiling["id"], h), 200)
    assert ef_after["superseded_by_amendment"] is True


def test_amend_file_supersedes_accepted_submission(api):
    """PRD §3.7: "Third, that `AMENDED` transition cascades to the original return's
    `ACCEPTED` e-file submission, setting that submission's `superseded_by_amendment`
    flag to true and incrementing its `version` — marking the superseded submission for
    audit."

    Design: Difficulty/transitive_cascade/amend_file_cascades_three_levels_to_efiling
    """
    taxpayer, filed, efiling, amendment = setup_draft_amendment(
        corrected_balance_due_cents=50_000,
        correction_period_start="2025-01-01T00:00:00Z",
        correction_period_end="2025-12-31T00:00:00Z")
    h = make_taxpayer_headers(taxpayer["id"])
    ef_before = validate_success(api.get_efiling(efiling["id"], h), 200)
    assert ef_before["superseded_by_amendment"] is False
    validate_success(api.file_amended_return(amendment["id"], h), 200)
    ef_after = validate_success(api.get_efiling(efiling["id"], h), 200)
    assert ef_after["superseded_by_amendment"] is True
    assert ef_after["version"] == ef_before["version"] + 1


# =====================================================================
# transitive_cascade / efile_accept_cascades_two_levels_to_return_filed
# =====================================================================

def test_efile_accept_cascades_two_hops_to_filed(api):
    """PRD §3.6: "When the outcome is `ACCEPTED`, the submission moves
    `TRANSMITTED → ACCEPTED`, its `ack_code` is set from the request, its `version`
    increments, and the parent return is driven `READY → FILED` with the return's
    `version` incremented."

    Design: Difficulty/transitive_cascade/efile_accept_cascades_two_levels_to_return_filed
    """
    taxpayer, _ret, efiling = setup_transmitted_efile()
    h = make_taxpayer_headers(taxpayer["id"])
    acked = validate_success(api.acknowledge_efiling(
        efiling["id"], acknowledge_payload("ACCEPTED", "A0000"),
        make_irs_gateway_headers()), 200)
    assert acked["status"] == "ACCEPTED"
    ret_after = validate_success(api.get_tax_return(efiling["return_id"], h), 200)
    assert ret_after["status"] == "FILED"


def test_efile_accept_increments_both_versions(api):
    """PRD §3.6: "When the outcome is `ACCEPTED`, the submission moves
    `TRANSMITTED → ACCEPTED`, its `ack_code` is set from the request, its `version`
    increments, and the parent return is driven `READY → FILED` with the return's
    `version` incremented."

    Design: Difficulty/transitive_cascade/efile_accept_cascades_two_levels_to_return_filed
    """
    taxpayer, ret_after_efile, efiling = setup_transmitted_efile()
    h = make_taxpayer_headers(taxpayer["id"])
    ret_v_before = ret_after_efile["version"]
    ef_v_before = efiling["version"]
    acked = validate_success(api.acknowledge_efiling(
        efiling["id"], acknowledge_payload("ACCEPTED", "A0000"),
        make_irs_gateway_headers()), 200)
    assert acked["version"] == ef_v_before + 1
    ret_after = validate_success(api.get_tax_return(efiling["return_id"], h), 200)
    assert ret_after["version"] == ret_v_before + 1


# =====================================================================
# cross_entity_state_dependency / return_filed_requires_efiling_accepted
# =====================================================================

def test_return_stays_ready_until_efile_accepted(api):
    """PRD §3.6: "Transmission is only allowed from `READY`: the return's `computed_at`
    must reflect the current children with no edit since the last compute."
    PRD §3.6: "When the outcome is `ACCEPTED`, the submission moves
    `TRANSMITTED → ACCEPTED`, its `ack_code` is set from the request, its `version`
    increments, and the parent return is driven `READY → FILED` with the return's
    `version` incremented."

    Design: Difficulty/cross_entity_state_dependency/return_filed_requires_efiling_accepted
    """
    taxpayer, ret_after_efile, efiling = setup_transmitted_efile()
    h = make_taxpayer_headers(taxpayer["id"])
    before = validate_success(api.get_tax_return(efiling["return_id"], h), 200)
    assert before["status"] == "READY"
    validate_success(api.acknowledge_efiling(
        efiling["id"], acknowledge_payload("ACCEPTED", "A0000"),
        make_irs_gateway_headers()), 200)
    after = validate_success(api.get_tax_return(efiling["return_id"], h), 200)
    assert after["status"] == "FILED"


def test_filed_only_via_accepted_submission(api):
    """PRD §3.6: "When the outcome is `ACCEPTED`, the submission moves
    `TRANSMITTED → ACCEPTED`, its `ack_code` is set from the request, its `version`
    increments, and the parent return is driven `READY → FILED` with the return's
    `version` incremented."

    Design: Difficulty/cross_entity_state_dependency/return_filed_requires_efiling_accepted
    """
    taxpayer, filed, efiling = setup_filed_return()
    h = make_taxpayer_headers(taxpayer["id"])
    ef = validate_success(api.get_efiling(efiling["id"], h), 200)
    assert ef["status"] == "ACCEPTED"
    ret = validate_success(api.get_tax_return(filed["id"], h), 200)
    assert ret["status"] == "FILED"


# =====================================================================
# cross_entity_state_dependency / amend_file_requires_original_return_filed
# =====================================================================

def test_amend_file_permitted_when_original_filed(api):
    """PRD §3.7: "Filing the 1040X is again reserved to the `Taxpayer` and is only
    defined when the amendment is in `DRAFT` and the original return is still `FILED`
    (the cross-entity guard reuses `ERR_ORIGINAL_NOT_FILED`)."
    PRD §3.7: "Second, the original return is driven `FILED → AMENDED`, refreshing its
    `updated_at` and incrementing its `version`."

    Design: Difficulty/cross_entity_state_dependency/amend_file_requires_original_return_filed
    """
    taxpayer, filed, _ef, amendment = setup_draft_amendment(
        corrected_balance_due_cents=60_000,
        correction_period_start="2025-01-01T00:00:00Z",
        correction_period_end="2025-12-31T00:00:00Z")
    h = make_taxpayer_headers(taxpayer["id"])
    filed_amd = validate_success(api.file_amended_return(amendment["id"], h), 200)
    assert filed_amd["status"] == "FILED"
    original_after = validate_success(api.get_tax_return(filed["id"], h), 200)
    assert original_after["status"] == "AMENDED"


def test_amend_create_blocked_when_original_not_filed(api):
    """PRD §3.7: "The amendment may only target an original return currently in `FILED`
    status — not `DRAFT`, `READY`, or `AMENDED` — and a violation is rejected with
    `ERR_ORIGINAL_NOT_FILED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/amend_file_requires_original_return_filed
    """
    taxpayer, computed = setup_computed_return()  # READY, not FILED
    h = make_taxpayer_headers(taxpayer["id"])
    resp = api.create_amended_return(
        create_amended_return_payload(
            computed["id"], taxpayer["id"], computed["version"],
            corrected_balance_due_cents=40_000,
            correction_period_start="2025-01-01T00:00:00Z",
            correction_period_end="2025-06-30T00:00:00Z"),
        h)
    validate_error(resp, ApiErrorId.ERR_ORIGINAL_NOT_FILED.value)


# =====================================================================
# compensating_invariant / amendment_delta_conserves_balance_due_ledger
# =====================================================================

def test_amendment_delta_conserves_balance_due(api):
    """PRD §3.7: "the amendment delta is computed: `delta_cents` is set to
    `corrected_balance_due_cents` minus the original return's frozen `balance_due_cents`,
    and the amendment moves `DRAFT → FILED` with its `version` incremented."
    PRD §3.7: "the original's frozen `balance_due_cents` plus the amendment's
    `delta_cents` equals the amendment's `corrected_balance_due_cents`, reconstructing
    the corrected balance with zero drift."

    Design: Difficulty/compensating_invariant/amendment_delta_conserves_balance_due_ledger
    """
    taxpayer, filed, _ef, amendment = setup_draft_amendment(
        corrected_balance_due_cents=20_600,
        correction_period_start="2025-01-01T00:00:00Z",
        correction_period_end="2025-12-31T00:00:00Z")
    h = make_taxpayer_headers(taxpayer["id"])
    # original was W-2 8,000,000 wages, 900,000 withholding -> balance_due 35,300
    assert filed["balance_due_cents"] == 35_300
    filed_amd = validate_success(api.file_amended_return(amendment["id"], h), 200)
    assert filed_amd["delta_cents"] == -14_700
    assert filed_amd["corrected_balance_due_cents"] == 20_600
    assert_balance_due_ledger_reconciles(35_300, filed_amd["delta_cents"],
                                         filed_amd["corrected_balance_due_cents"])


def test_amendment_delta_equals_corrected_minus_original(api):
    """PRD §3.7: "the amendment delta is computed: `delta_cents` is set to
    `corrected_balance_due_cents` minus the original return's frozen `balance_due_cents`,
    and the amendment moves `DRAFT → FILED` with its `version` incremented."

    Design: Difficulty/compensating_invariant/amendment_delta_conserves_balance_due_ledger
    """
    taxpayer, filed, _ef, amendment = setup_draft_amendment(
        corrected_balance_due_cents=100_000,
        correction_period_start="2025-01-01T00:00:00Z",
        correction_period_end="2025-12-31T00:00:00Z")
    h = make_taxpayer_headers(taxpayer["id"])
    filed_amd = validate_success(api.file_amended_return(amendment["id"], h), 200)
    # corrected 100,000 - original 35,300 = 64,700
    assert filed_amd["delta_cents"] == 64_700
    assert_balance_due_ledger_reconciles(filed["balance_due_cents"],
                                         filed_amd["delta_cents"],
                                         filed_amd["corrected_balance_due_cents"])


# =====================================================================
# compensating_invariant / reopen_recompute_conserves_total_payments
# =====================================================================

def test_reopen_recompute_conserves_total_payments(api):
    """PRD §3.6: "This loop is payment-neutral by invariant: across a reopen and the
    compensating recompute, when no income document and no estimated payment is added or
    removed in between, `total_payments_cents` must be left exactly unchanged from its
    value before rejection."
    PRD §3.6: "`total_payments_cents` always equals the sum of `federal_withholding_cents`
    over the income documents plus the sum of `amount_cents` over the estimated
    payments, and that identity must hold with zero drift across the reopen-and-recompute
    cycle."

    Design: Difficulty/compensating_invariant/reopen_recompute_conserves_total_payments
    """
    taxpayer, tax_return = FIX.setup_taxpayer_and_return(
        return_overrides={"filing_status": "SINGLE", "deduction_method": "STANDARD"})
    h = make_taxpayer_headers(taxpayer["id"])
    FIX.add_income_document(tax_return["id"], taxpayer["id"],
                            doc_type="W2", payer_name="Acme",
                            box_amount_cents=8_000_000, federal_withholding_cents=900_000)
    FIX.add_estimated_payment(tax_return["id"], taxpayer["id"],
                              quarter="Q1", amount_cents=200_000,
                              paid_on="2025-04-10T00:00:00Z",
                              period_start="2025-01-01T00:00:00Z",
                              period_end="2025-04-01T00:00:00Z")
    computed = validate_success(api.compute_tax_return(tax_return["id"], h), 200)
    assert computed["total_payments_cents"] == 1_100_000
    efiling = validate_success(api.efile_tax_return(
        tax_return["id"], efile_payload(computed["version"]), h), 201)
    validate_success(api.acknowledge_efiling(
        efiling["id"], acknowledge_payload("REJECTED", "R0002"),
        make_irs_gateway_headers()), 200)
    validate_success(api.patch_tax_return(tax_return["id"], {"reopen": True}, h), 200)
    recomputed = validate_success(api.compute_tax_return(tax_return["id"], h), 200)
    assert recomputed["total_payments_cents"] == 1_100_000
    assert recomputed["status"] == "READY"


def test_total_payments_unchanged_from_pre_rejection_value(api):
    """PRD §3.6: "This loop is payment-neutral by invariant: across a reopen and the
    compensating recompute, when no income document and no estimated payment is added or
    removed in between, `total_payments_cents` must be left exactly unchanged from its
    value before rejection."
    PRD §3.6: "`total_payments_cents` always equals the sum of `federal_withholding_cents`
    over the income documents plus the sum of `amount_cents` over the estimated
    payments, and that identity must hold with zero drift across the reopen-and-recompute
    cycle."

    Design: Difficulty/compensating_invariant/reopen_recompute_conserves_total_payments
    """
    taxpayer, tax_return = FIX.setup_taxpayer_and_return(
        return_overrides={"filing_status": "SINGLE", "deduction_method": "STANDARD"})
    h = make_taxpayer_headers(taxpayer["id"])
    FIX.add_income_document(tax_return["id"], taxpayer["id"],
                            doc_type="W2", payer_name="Acme",
                            box_amount_cents=8_000_000, federal_withholding_cents=900_000)
    FIX.add_estimated_payment(tax_return["id"], taxpayer["id"],
                              quarter="Q1", amount_cents=200_000,
                              paid_on="2025-04-10T00:00:00Z",
                              period_start="2025-01-01T00:00:00Z",
                              period_end="2025-04-01T00:00:00Z")
    computed = validate_success(api.compute_tax_return(tax_return["id"], h), 200)
    payments_before_rejection = computed["total_payments_cents"]
    efiling = validate_success(api.efile_tax_return(
        tax_return["id"], efile_payload(computed["version"]), h), 201)
    validate_success(api.acknowledge_efiling(
        efiling["id"], acknowledge_payload("REJECTED", "R0003"),
        make_irs_gateway_headers()), 200)
    validate_success(api.patch_tax_return(tax_return["id"], {"reopen": True}, h), 200)
    recomputed = validate_success(api.compute_tax_return(tax_return["id"], h), 200)
    # zero drift: identical to the pre-rejection figure (= 900,000 + 200,000).
    assert recomputed["total_payments_cents"] == payments_before_rejection
    assert recomputed["total_payments_cents"] == 900_000 + 200_000


# =====================================================================
# Corner B / state_machines
# =====================================================================

def test_new_return_initial_state_draft(api):
    """PRD §3.1: "A newly created return begins life in `DRAFT` status with `version` 1,
    and all of its computed money fields — `total_income_cents`, `agi_cents`,
    `taxable_income_cents`, `tax_before_credits_cents`, `total_credits_cents`,
    `tax_after_credits_cents`, `total_payments_cents`, and `balance_due_cents` — start
    at 0, with `computed_at` null until the first successful computation."

    Design: Corner/state_machines/newly_created_return_initial_state_draft
    """
    taxpayer, tax_return = FIX.setup_taxpayer_and_return()
    assert tax_return["status"] == "DRAFT"


def test_efile_from_draft_rejected_not_computed(api):
    """PRD §3.6: "If the return is `DRAFT` (its compute is stale or absent), the
    transmission is rejected with `ERR_RETURN_NOT_COMPUTED` (HTTP 409)".

    Design: Corner/state_machines/efile_from_draft_rejected_not_computed
    """
    taxpayer, tax_return, _doc = FIX.setup_draft_return_with_w2()
    h = make_taxpayer_headers(taxpayer["id"])
    current = validate_success(api.get_tax_return(tax_return["id"], h), 200)
    resp = api.efile_tax_return(
        tax_return["id"], efile_payload(current["version"]), h)
    validate_error(resp, ApiErrorId.ERR_RETURN_NOT_COMPUTED.value)


def test_acknowledge_already_accepted_invalid_state(api):
    """PRD §3.6: "Acknowledgement is only defined when the submission is in
    `TRANSMITTED`; otherwise it is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/acknowledge_already_accepted_invalid_state
    """
    _tp, _ret, efiling = setup_filed_return()
    resp = api.acknowledge_efiling(
        efiling["id"], acknowledge_payload("ACCEPTED", "A0000"),
        make_irs_gateway_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_reopen_draft_return_invalid_state(api):
    """PRD §3.6: "The taxpayer or preparer reopens it by editing the return with the
    `reopen` flag set true while the return is in `REJECTED`, which moves it
    `REJECTED → DRAFT` and increments its `version`."
    PRD §2.9: "Then state-machine legality of the requested transition
    (`ERR_INVALID_STATE`, HTTP 409)."

    Design: Corner/state_machines/reopen_draft_return_invalid_state
    """
    taxpayer, tax_return = FIX.setup_taxpayer_and_return()
    h = make_taxpayer_headers(taxpayer["id"])
    resp = api.patch_tax_return(tax_return["id"], {"reopen": True}, h)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_child_edit_on_ready_return_resets_to_draft(api):
    """PRD §2.7: "Whenever a child is added or an income document, schedule, dependent,
    or credit claim is created on a return that is currently in `READY` status, that
    mutation invalidates the prior computation: the return is reset to `DRAFT`, its
    `updated_at` is refreshed, and its `version` is incremented by one."

    Design: Corner/state_machines/child_edit_on_ready_return_resets_to_draft
    """
    taxpayer, computed = setup_computed_return(federal_withholding_cents=0)
    h = make_taxpayer_headers(taxpayer["id"])
    assert computed["status"] == "READY"
    validate_success(api.create_income_document(
        computed["id"],
        create_income_document_payload(doc_type="1099_INT", payer_name="Bank",
                                       box_amount_cents=50_000), h), 201)
    after = validate_success(api.get_tax_return(computed["id"], h), 200)
    assert after["status"] == "DRAFT"


def test_amend_create_when_original_amended_rejected(api):
    """PRD §3.7: "The amendment may only target an original return currently in `FILED`
    status — not `DRAFT`, `READY`, or `AMENDED` — and a violation is rejected with
    `ERR_ORIGINAL_NOT_FILED` (HTTP 409)."

    Design: Corner/state_machines/amend_file_when_original_already_amended_invalid
    """
    # First amendment files and drives original to AMENDED.
    taxpayer, original_after, _ef, _filed_amd = FIX.setup_filed_amendment(
        corrected_balance_due_cents=40_000,
        correction_period_start="2025-01-01T00:00:00Z",
        correction_period_end="2025-06-30T00:00:00Z")
    h = make_taxpayer_headers(taxpayer["id"])
    assert original_after["status"] == "AMENDED"
    # Second amendment create against the now-AMENDED original.
    resp = api.create_amended_return(
        create_amended_return_payload(
            original_after["id"], taxpayer["id"], original_after["version"],
            corrected_balance_due_cents=30_000,
            correction_period_start="2025-07-01T00:00:00Z",
            correction_period_end="2025-12-31T00:00:00Z"),
        h)
    validate_error(resp, ApiErrorId.ERR_ORIGINAL_NOT_FILED.value)
