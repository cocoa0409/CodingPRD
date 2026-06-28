"""Contract administration: CLINs, invoices, modifications, ceilings, and CPFF fees.

Covers queue-A difficulty instances for the FFP/CPFF invoice-amount divergence, the
sum-then-fee CPFF rounding, the state-vs-ceiling precedence, the contract<->modification
cross-entity dependency, the option-window temporal boundary, and obligation conservation;
queue-B corner instances for calculations, CLIN/invoice/ceiling validations, OCC on the
contract, cascading side effects, RBAC/auth, and the default-clock scheduled action.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS, make_co_headers, make_vendor_headers, get_success_data,
    set_clock, create_active_vendor,
    create_draft_solicitation_with_factors, open_solicitation,
    create_scored_draft_proposal, submit_proposal,
    setup_active_ffp_contract, setup_active_cpff_contract, fresh_contract_version,
    create_vendor_payload, create_ffp_invoice_payload, create_cpff_invoice_payload,
    create_clin_payload, create_modification_payload, create_contract_payload,
    create_award_payload,
)

CO = TEST_USERS["co_headers"]
VENDOR_FALLBACK = TEST_USERS["vendor_headers"]


# ─── FFP invoice amount ────────────────────────────────────────────
def test_ffp_invoice_amount_units_times_price(api):
    """PRD §3.5: "For a firm-fixed-price invoice, the `amount_cents` is the referenced
    CLIN's `unit_price_cents` multiplied by the invoice's `invoiced_qty`, and the
    `fee_portion_cents` is 0."

    Design: Corner/calculations/ffp_invoice_amount_units_times_price
    """
    ctx = setup_active_ffp_contract(base_value_cents=50000000, with_clin=True,
                                    clin_unit_price=50000, clin_funded_qty=100,
                                    vendor_uei="FFPV00000001",
                                    close_at="2026-02-05T00:00:00Z")
    cv = fresh_contract_version(ctx["contract"]["id"])
    res = api.create_invoice(
        create_ffp_invoice_payload(ctx["contract"]["id"], ctx["clin"]["id"], 30, cv),
        make_vendor_headers(ctx["vendor"]["id"]),
    )
    invoice = validate_success(res, 201)
    assert invoice["amount_cents"] == 1500000, (
        f"expected 1500000 (50000 * 30), got {invoice['amount_cents']}"
    )
    assert invoice["fee_portion_cents"] == 0, (
        f"expected fee 0 for FFP, got {invoice['fee_portion_cents']}"
    )


# ─── FFP vs CPFF invoice-amount divergence ─────────────────────────
def test_cpff_invoice_amount_cost_plus_proportional_fee(api):
    """PRD §3.5: "the `fee_portion_cents` is the contract's `fixed_fee_cents` multiplied by
    the ratio of the invoice's `allowable_cost_cents` to the contract's
    `total_estimated_cost_cents`, rounded half-up to a whole cent; the `amount_cents` is
    then the invoice's `allowable_cost_cents` plus that `fee_portion_cents`."

    Design: Difficulty/dual_variant_calc/ffp_vs_cpff_invoice_amount_diverge
    """
    ctx = setup_active_cpff_contract(
        base_value_cents=108000000, total_estimated_cost_cents=100000000,
        fixed_fee_cents=8000000, vendor_uei="DUAL00000001",
        close_at="2026-02-10T00:00:00Z",
    )
    cv = fresh_contract_version(ctx["contract"]["id"])
    res = api.create_invoice(
        create_cpff_invoice_payload(ctx["contract"]["id"], 25000000, cv),
        make_vendor_headers(ctx["vendor"]["id"]),
    )
    invoice = validate_success(res, 201)
    assert invoice["fee_portion_cents"] == 2000000, (
        f"expected fee 2000000 (8000000 * 25000000/100000000), "
        f"got {invoice['fee_portion_cents']}"
    )
    assert invoice["amount_cents"] == 27000000, (
        f"expected amount 27000000 (cost 25000000 + fee 2000000), "
        f"got {invoice['amount_cents']}"
    )


def test_ffp_amount_diverges_from_claimed_cost(api):
    """PRD §3.5: "For a firm-fixed-price invoice, the `amount_cents` is the referenced
    CLIN's `unit_price_cents` multiplied by the invoice's `invoiced_qty`, and the
    `fee_portion_cents` is 0."

    The FFP arm of the divergence: a 30-unit invoice at unit_price 50000 yields 1500000
    with zero fee — distinct from the CPFF cost-plus arm.

    Design: Difficulty/dual_variant_calc/ffp_vs_cpff_invoice_amount_diverge
    """
    ctx = setup_active_ffp_contract(base_value_cents=50000000, with_clin=True,
                                    clin_unit_price=50000, clin_funded_qty=100,
                                    vendor_uei="DUAL00000002",
                                    close_at="2026-02-10T00:00:00Z")
    cv = fresh_contract_version(ctx["contract"]["id"])
    invoice = validate_success(
        api.create_invoice(
            create_ffp_invoice_payload(ctx["contract"]["id"], ctx["clin"]["id"], 30, cv),
            make_vendor_headers(ctx["vendor"]["id"]),
        ),
        201,
    )
    assert invoice["amount_cents"] == 1500000, (
        f"expected 1500000 (units*price), got {invoice['amount_cents']}"
    )
    assert invoice["fee_portion_cents"] == 0, (
        f"expected fee 0 for FFP, got {invoice['fee_portion_cents']}"
    )


# ─── CPFF sum-then-fee rounding (round once) ───────────────────────
def test_cpff_fee_rounded_once_sum_then_fee(api):
    """PRD §3.5: "compute the fee on the summed allowable cost and round it once — do not
    round a per-line fee and then sum, because the two approaches diverge by a cent on
    some inputs (for example, a fee ratio of one-fifteenth applied across three separate
    one-dollar lines yields 20 cents the sum-then-round way but 21 cents the
    round-then-sum way)."

    Design: Difficulty/combinatorial_formula/cpff_fee_round_once_sum_then_fee
    """
    ctx = setup_active_cpff_contract(
        base_value_cents=96000000, total_estimated_cost_cents=90000000,
        fixed_fee_cents=6000000, vendor_uei="ROUN00000001",
        close_at="2026-02-05T00:00:00Z", tech_score=88,
    )
    cv = fresh_contract_version(ctx["contract"]["id"])
    invoice = validate_success(
        api.create_invoice(
            create_cpff_invoice_payload(ctx["contract"]["id"], 300, cv),
            make_vendor_headers(ctx["vendor"]["id"]),
        ),
        201,
    )
    assert invoice["fee_portion_cents"] == 20, (
        f"expected fee 20 (round(6000000 * 300/90000000) == round(20.0)); "
        f"NOT 21 from per-line rounding, got {invoice['fee_portion_cents']}"
    )
    assert invoice["amount_cents"] == 320, (
        f"expected amount 320 (cost 300 + fee 20), got {invoice['amount_cents']}"
    )


def test_cpff_fee_single_rounding_second_input(api):
    """PRD §3.5: "the `fee_portion_cents` is the contract's `fixed_fee_cents` multiplied by
    the ratio of the invoice's `allowable_cost_cents` to the contract's
    `total_estimated_cost_cents`, rounded half-up to a whole cent; the `amount_cents` is
    then the invoice's `allowable_cost_cents` plus that `fee_portion_cents`."

    Second data point for the round-once rule: ratio 1/15 over a summed allowable cost
    of 315 yields exactly 21 cents (6000000 * 315 / 90000000 == 21.0).

    Design: Difficulty/combinatorial_formula/cpff_fee_round_once_sum_then_fee
    """
    ctx = setup_active_cpff_contract(
        base_value_cents=96000000, total_estimated_cost_cents=90000000,
        fixed_fee_cents=6000000, vendor_uei="ROUN00000002",
        close_at="2026-02-05T00:00:00Z", tech_score=88,
    )
    cv = fresh_contract_version(ctx["contract"]["id"])
    invoice = validate_success(
        api.create_invoice(
            create_cpff_invoice_payload(ctx["contract"]["id"], 315, cv),
            make_vendor_headers(ctx["vendor"]["id"]),
        ),
        201,
    )
    assert invoice["fee_portion_cents"] == 21, (
        f"expected fee 21 (round(6000000 * 315/90000000)), got {invoice['fee_portion_cents']}"
    )
    assert invoice["amount_cents"] == 336, (
        f"expected amount 336 (cost 315 + fee 21), got {invoice['amount_cents']}"
    )


# ─── Obligated amount calculation ──────────────────────────────────
def test_obligated_amount_grows_on_funding_mod(api):
    """PRD §3.5: "it is the contract's `base_value_cents`, plus the sum of
    `option_value_cents` over the contract's approved option-exercise modifications, plus
    the sum of `delta_cents` over the contract's approved funding modifications."

    Design: Corner/calculations/obligated_amount_grows_on_funding_mod
    """
    ctx = setup_active_ffp_contract(base_value_cents=50000000, with_clin=False,
                                    vendor_uei="FUND00000001",
                                    close_at="2026-02-05T00:00:00Z")
    mod = get_success_data(
        api.create_modification(ctx["contract"]["id"],
                                create_modification_payload("FUNDING", delta_cents=10000000), CO)
    )
    get_success_data(api.approve_modification(mod["id"], CO))
    contract = validate_success(api.get_contract(ctx["contract"]["id"], CO), 200)
    assert contract["obligated_amount_cents"] == 60000000, (
        f"expected 60000000 (50000000 base + 10000000 funding), "
        f"got {contract['obligated_amount_cents']}"
    )


def test_obligation_conserved_when_mod_rejected_after_approve(api):
    """PRD §3.5: "it is the contract's `base_value_cents`, plus the sum of
    `option_value_cents` over the contract's approved option-exercise modifications, plus
    the sum of `delta_cents` over the contract's approved funding modifications."
    PRD §3.5: "Rejecting a modification drives `PROPOSED` to `REJECTED` and increments
    only the modification's `version`."

    A rejected funding mod contributes nothing, so obligation stays at base + the one
    approved mod.

    Design: Difficulty/compensating_invariant/obligation_conserved_on_mod_reject_after_approve
    """
    ctx = setup_active_ffp_contract(base_value_cents=50000000, with_clin=False,
                                    vendor_uei="OBLG00000001",
                                    close_at="2026-02-05T00:00:00Z")
    cid = ctx["contract"]["id"]
    mod1 = get_success_data(
        api.create_modification(cid, create_modification_payload("FUNDING", delta_cents=10000000), CO)
    )
    get_success_data(api.approve_modification(mod1["id"], CO))
    mod2 = get_success_data(
        api.create_modification(cid, create_modification_payload("FUNDING", delta_cents=5000000), CO)
    )
    get_success_data(api.reject_modification(mod2["id"], CO))
    contract = validate_success(api.get_contract(cid, CO), 200)
    assert contract["obligated_amount_cents"] == 60000000, (
        f"expected 60000000 (50000000 base + 10000000 approved; rejected +5000000 "
        f"leaves obligation unchanged), got {contract['obligated_amount_cents']}"
    )


def test_obligation_equals_base_with_no_approved_mods(api):
    """PRD §3.5: "With no approved modifications the obligated amount equals the base
    value".

    Second assertion of the conserved-obligation invariant.

    Design: Difficulty/compensating_invariant/obligation_conserved_on_mod_reject_after_approve
    """
    ctx = setup_active_ffp_contract(base_value_cents=50000000, with_clin=False,
                                    vendor_uei="OBLG00000002",
                                    close_at="2026-02-05T00:00:00Z")
    cid = ctx["contract"]["id"]
    mod = get_success_data(
        api.create_modification(cid, create_modification_payload("FUNDING", delta_cents=5000000), CO)
    )
    get_success_data(api.reject_modification(mod["id"], CO))
    contract = validate_success(api.get_contract(cid, CO), 200)
    assert contract["obligated_amount_cents"] == 50000000, (
        f"expected obligation to equal base 50000000 (no approved mods), "
        f"got {contract['obligated_amount_cents']}"
    )


# ─── CLIN / invoice shape / over-delivery / ceiling validations ────
def test_duplicate_clin_number_rejected(api):
    """PRD §3.5: "The `clin_number` must be unique within its contract; a duplicate is
    rejected with `ERR_DUPLICATE_CLIN`."

    Design: Corner/validations/error_duplicate_clin_on_create
    """
    ctx = setup_active_ffp_contract(base_value_cents=50000000, with_clin=True,
                                    clin_unit_price=50000, clin_funded_qty=100,
                                    vendor_uei="CLIN00000001",
                                    close_at="2026-02-05T00:00:00Z")
    res = api.add_clin(ctx["contract"]["id"], create_clin_payload("0001", 60000, 50), CO)
    validate_error(res, "ERR_DUPLICATE_CLIN", expected_status=409)


def test_cpff_invoice_against_ffp_contract_shape_mismatch(api):
    """PRD §3.5: "A firm-fixed-price invoice must carry a `clin_id` and an `invoiced_qty`
    and must not carry `allowable_cost_cents`; a cost-plus invoice must carry
    `allowable_cost_cents` and must not carry a `clin_id`. A payload that does not match
    its contract's type is rejected with `ERR_INVOICE_SHAPE_MISMATCH`."

    Design: Corner/validations/error_invoice_shape_mismatch
    """
    ctx = setup_active_ffp_contract(base_value_cents=50000000, with_clin=True,
                                    clin_unit_price=50000, clin_funded_qty=100,
                                    vendor_uei="SHAP00000001",
                                    close_at="2026-02-05T00:00:00Z")
    cv = fresh_contract_version(ctx["contract"]["id"])
    res = api.create_invoice(
        create_cpff_invoice_payload(ctx["contract"]["id"], 1000000, cv),
        make_vendor_headers(ctx["vendor"]["id"]),
    )
    validate_error(res, "ERR_INVOICE_SHAPE_MISMATCH", expected_status=422)


def test_clin_overdelivery_on_approve_rejected(api):
    """PRD §3.5: "For a firm-fixed-price invoice, the CLIN's current `delivered_qty` plus
    the invoice's `invoiced_qty` must not exceed the CLIN's `funded_qty`; an approval that
    would over-deliver the CLIN is rejected with `ERR_CLIN_OVERDELIVERY`."

    Design: Corner/validations/error_clin_overdelivery_on_approve
    """
    ctx = setup_active_ffp_contract(base_value_cents=50000000, with_clin=True,
                                    clin_unit_price=50000, clin_funded_qty=100,
                                    vendor_uei="OVER00000001",
                                    close_at="2026-02-05T00:00:00Z")
    cv = fresh_contract_version(ctx["contract"]["id"])
    invoice = get_success_data(
        api.create_invoice(
            create_ffp_invoice_payload(ctx["contract"]["id"], ctx["clin"]["id"], 120, cv),
            make_vendor_headers(ctx["vendor"]["id"]),
        )
    )
    res = api.approve_invoice(invoice["id"], CO)
    validate_error(res, "ERR_CLIN_OVERDELIVERY", expected_status=422)


def test_cpff_contract_missing_fee_fields_validation(api):
    """PRD §3.5: "A `CPFF` contract created without its `total_estimated_cost_cents` or
    `fixed_fee_cents` is rejected with `ERR_VALIDATION`."

    Design: Corner/errors/error_validation_cpff_missing_fee_fields
    """
    # Build an award, then attempt a CPFF contract that omits the fee fields.
    from test_helpers import setup_award
    a = setup_award(vendor_uei="CPMS00000001", close_at="2026-02-05T00:00:00Z")
    res = api.create_contract(
        create_contract_payload(a["award"]["id"], "CPFF", 50000000), CO
    )
    validate_error(res, "ERR_VALIDATION", expected_status=422)


# ─── State vs ceiling precedence on invoice approve ────────────────
def test_reapprove_approved_invoice_state_beats_ceiling(api):
    """PRD §3.8: "State validity comes fifth: a transition requested from a state in which
    it is not defined is rejected with `ERR_INVALID_STATE` (HTTP 409) on every
    state-transition endpoint."
    PRD §3.8: "Only after these gates pass does the system evaluate the operation-specific
    business rules — proposal eligibility on award, set-aside and registration and
    deadline checks on submission, the option window and factor-weight and uniqueness and
    shape and over-delivery and ceiling checks on their respective operations."

    Re-approving an already-APPROVED invoice (whose contract is also at ceiling) returns
    the state error, not the ceiling error.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_ceiling_on_invoice_approve
    """
    ctx = setup_active_ffp_contract(base_value_cents=50000000, with_clin=True,
                                    clin_unit_price=500000, clin_funded_qty=100,
                                    vendor_uei="INVV00000001",
                                    close_at="2026-02-05T00:00:00Z")
    cv = fresh_contract_version(ctx["contract"]["id"])
    invoice = get_success_data(
        api.create_invoice(
            create_ffp_invoice_payload(ctx["contract"]["id"], ctx["clin"]["id"], 100, cv),
            make_vendor_headers(ctx["vendor"]["id"]),
        )
    )
    get_success_data(api.approve_invoice(invoice["id"], CO))  # now APPROVED, ceiling reached
    res = api.approve_invoice(invoice["id"], CO)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_ceiling_exceeded_when_state_valid(api):
    """PRD §3.8: "Only after these gates pass does the system evaluate the operation-specific
    business rules — proposal eligibility on award, set-aside and registration and
    deadline checks on submission, the option window and factor-weight and uniqueness and
    shape and over-delivery and ceiling checks on their respective operations."
    PRD §3.5: "For every invoice, the contract's `cumulative_invoiced_cents` plus this
    invoice's `amount_cents` must not exceed the contract's `obligated_amount_cents`; an
    approval that would breach the ceiling is rejected with `ERR_CEILING_EXCEEDED`."

    Partner to the state-beats-ceiling case: when the invoice is in the valid SUBMITTED
    state (so the fifth-precedence state gate passes), the ceiling business rule is what
    rejects an over-ceiling approval.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_ceiling_on_invoice_approve
    """
    # Contract obligated 50000000; a single SUBMITTED invoice for 60000000 would breach it.
    ctx = setup_active_ffp_contract(base_value_cents=50000000, with_clin=True,
                                    clin_unit_price=600000, clin_funded_qty=200,
                                    vendor_uei="CEIL00000001",
                                    close_at="2026-02-05T00:00:00Z")
    cid = ctx["contract"]["id"]
    cv = fresh_contract_version(cid)
    invoice = get_success_data(
        api.create_invoice(
            create_ffp_invoice_payload(cid, ctx["clin"]["id"], 100, cv),  # 600000*100 = 60000000
            make_vendor_headers(ctx["vendor"]["id"]),
        )
    )
    # Invoice is SUBMITTED (valid state to approve from); ceiling breach governs.
    res = api.approve_invoice(invoice["id"], CO)
    validate_error(res, "ERR_CEILING_EXCEEDED", expected_status=422)


# ─── Cross-entity state dependency: option exercise needs WITHIN_CEILING ─
def test_option_exercise_blocked_when_ceiling_reached(api):
    """PRD §3.5: "for an option-exercise modification, it is additionally permitted only
    when the contract's funding posture is `WITHIN_CEILING` and the current logical clock
    is at or before the `option_window_close_at`."
    PRD §3.5: "An option exercise approved while the contract has reached its ceiling is
    rejected with `ERR_CEILING_REACHED_NO_OPTION`".

    Design: Difficulty/cross_entity_state_dependency/option_exercise_requires_contract_within_ceiling
    """
    ctx = setup_active_ffp_contract(base_value_cents=50000000, with_clin=True,
                                    clin_unit_price=500000, clin_funded_qty=100,
                                    vendor_uei="OPTV00000001",
                                    close_at="2026-02-05T00:00:00Z")
    cid = ctx["contract"]["id"]
    cv = fresh_contract_version(cid)
    invoice = get_success_data(
        api.create_invoice(
            create_ffp_invoice_payload(cid, ctx["clin"]["id"], 100, cv),
            make_vendor_headers(ctx["vendor"]["id"]),
        )
    )
    get_success_data(api.approve_invoice(invoice["id"], CO))  # cumulative == obligated => CEILING_REACHED
    mod = get_success_data(
        api.create_modification(
            cid,
            create_modification_payload("OPTION_EXERCISE", option_value_cents=10000000,
                                        option_window_close_at="2026-12-31T00:00:00Z"),
            CO,
        )
    )
    res = api.approve_modification(mod["id"], CO)
    validate_error(res, "ERR_CEILING_REACHED_NO_OPTION", expected_status=422)


def test_option_exercise_within_ceiling_succeeds(api):
    """PRD §3.5: "for an option-exercise modification, it is additionally permitted only
    when the contract's funding posture is `WITHIN_CEILING` and the current logical clock
    is at or before the `option_window_close_at`."

    Partner: with the contract still WITHIN_CEILING and inside the window, the option
    exercise is approved and raises the obligation.

    Design: Difficulty/cross_entity_state_dependency/option_exercise_requires_contract_within_ceiling
    """
    ctx = setup_active_ffp_contract(base_value_cents=50000000, with_clin=False,
                                    vendor_uei="OPTV00000002",
                                    close_at="2026-02-05T00:00:00Z")
    cid = ctx["contract"]["id"]
    mod = get_success_data(
        api.create_modification(
            cid,
            create_modification_payload("OPTION_EXERCISE", option_value_cents=10000000,
                                        option_window_close_at="2026-12-31T00:00:00Z"),
            CO,
        )
    )
    approved = validate_success(api.approve_modification(mod["id"], CO), 200)
    assert approved["status"] == "APPROVED", f"expected APPROVED, got {approved['status']}"
    contract = validate_success(api.get_contract(cid, CO), 200)
    assert contract["obligated_amount_cents"] == 60000000, (
        f"expected obligation raised to 60000000, got {contract['obligated_amount_cents']}"
    )


# ─── Option-window temporal boundary ───────────────────────────────
def test_option_window_late_approval_rejected(api):
    """PRD §3.5: "an option exercise approved after its window has closed is rejected with
    `ERR_OPTION_WINDOW_CLOSED`."

    Design: Difficulty/resource_temporal_overlap/option_window_exclusive_late_rejection
    """
    ctx = setup_active_ffp_contract(base_value_cents=50000000, with_clin=False,
                                    vendor_uei="WIND00000001",
                                    close_at="2026-02-05T00:00:00Z")
    cid = ctx["contract"]["id"]
    mod = get_success_data(
        api.create_modification(
            cid,
            create_modification_payload("OPTION_EXERCISE", option_value_cents=10000000,
                                        option_window_close_at="2026-06-01T00:00:00Z"),
            CO,
        )
    )
    set_clock("2026-06-02T00:00:00Z")  # past the window
    res = api.approve_modification(mod["id"], CO)
    validate_error(res, "ERR_OPTION_WINDOW_CLOSED", expected_status=422)


def test_option_window_approval_at_boundary_succeeds(api):
    """PRD §3.5: "for an option-exercise modification, it is additionally permitted only
    when the contract's funding posture is `WITHIN_CEILING` and the current logical clock
    is at or before the `option_window_close_at`."

    Boundary partner: approval at exactly option_window_close_at is on time (inclusive
    upper bound).

    Design: Difficulty/resource_temporal_overlap/option_window_exclusive_late_rejection
    """
    ctx = setup_active_ffp_contract(base_value_cents=50000000, with_clin=False,
                                    vendor_uei="WIND00000002",
                                    close_at="2026-02-05T00:00:00Z")
    cid = ctx["contract"]["id"]
    mod = get_success_data(
        api.create_modification(
            cid,
            create_modification_payload("OPTION_EXERCISE", option_value_cents=10000000,
                                        option_window_close_at="2026-06-01T00:00:00Z"),
            CO,
        )
    )
    set_clock("2026-06-01T00:00:00Z")  # exactly the window close instant
    approved = validate_success(api.approve_modification(mod["id"], CO), 200)
    assert approved["status"] == "APPROVED", (
        f"clock == option_window_close_at is inclusive/on-time; got {approved['status']}"
    )


# ─── OCC on contract (invoice create) ──────────────────────────────
def test_invoice_create_stale_contract_version_rejected(api):
    """PRD §2.7: "Creating an invoice against a contract requires the request body to
    carry `expected_contract_version`, the version of the contract the client last read.
    If that value does not match the contract's current `version`, the create is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_invoice_create_stale_contract_version
    """
    ctx = setup_active_ffp_contract(base_value_cents=50000000, with_clin=True,
                                    clin_unit_price=50000, clin_funded_qty=100,
                                    vendor_uei="IOCA00000001",
                                    close_at="2026-02-05T00:00:00Z")
    cid = ctx["contract"]["id"]
    stale = ctx["contract"]["version"]  # captured before the funding-mod approval below
    mod = get_success_data(
        api.create_modification(cid, create_modification_payload("FUNDING", delta_cents=10000000), CO)
    )
    get_success_data(api.approve_modification(mod["id"], CO))  # bumps contract.version
    res = api.create_invoice(
        create_ffp_invoice_payload(cid, ctx["clin"]["id"], 10, stale),
        make_vendor_headers(ctx["vendor"]["id"]),
    )
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_invoice_create_correct_contract_version_succeeds(api):
    """PRD §2.7: "Creating an invoice against a contract requires the request body to
    carry `expected_contract_version`, the version of the contract the client last read."
    PRD §3.5: "A new invoice is born in `SUBMITTED` status".

    OCC happy path: the freshly-read version is accepted.

    Design: Corner/cross_cutting_complexity_layers/occ_invoice_correct_version_succeeds
    """
    ctx = setup_active_ffp_contract(base_value_cents=50000000, with_clin=True,
                                    clin_unit_price=50000, clin_funded_qty=100,
                                    vendor_uei="OKVN00000001",
                                    close_at="2026-02-05T00:00:00Z")
    cv = fresh_contract_version(ctx["contract"]["id"])
    res = api.create_invoice(
        create_ffp_invoice_payload(ctx["contract"]["id"], ctx["clin"]["id"], 10, cv),
        make_vendor_headers(ctx["vendor"]["id"]),
    )
    invoice = validate_success(res, 201)
    assert invoice["status"] == "SUBMITTED", f"expected SUBMITTED, got {invoice['status']}"


# ─── Cascading side effects on invoice approve ─────────────────────
def test_invoice_approve_updates_delivered_qty_and_cumulative(api):
    """PRD §3.5: "On a successful approval, the system sets `status` to `APPROVED`,
    recomputes the contract's `cumulative_invoiced_cents`, adds the `invoiced_qty` to the
    CLIN's `delivered_qty` for firm-fixed-price work".

    Design: Corner/cross_cutting_complexity_layers/cascade_invoice_approve_updates_delivered_qty_and_cumulative
    """
    ctx = setup_active_ffp_contract(base_value_cents=50000000, with_clin=True,
                                    clin_unit_price=50000, clin_funded_qty=100,
                                    vendor_uei="CASC00000001",
                                    close_at="2026-02-05T00:00:00Z")
    cid = ctx["contract"]["id"]
    cv = fresh_contract_version(cid)
    invoice = get_success_data(
        api.create_invoice(
            create_ffp_invoice_payload(cid, ctx["clin"]["id"], 30, cv),
            make_vendor_headers(ctx["vendor"]["id"]),
        )
    )
    get_success_data(api.approve_invoice(invoice["id"], CO))
    clins, _ = _list_clins(api, cid)
    assert clins[0]["delivered_qty"] == 30, (
        f"expected delivered_qty 30, got {clins[0]['delivered_qty']}"
    )
    contract = validate_success(api.get_contract(cid, CO), 200)
    assert contract["cumulative_invoiced_cents"] == 1500000, (
        f"expected cumulative 1500000 (50000*30), got {contract['cumulative_invoiced_cents']}"
    )


# ─── Reject invoice ────────────────────────────────────────────────
def test_reject_invoice_sets_rejected_and_excludes_from_cumulative(api):
    """PRD §3.5: "Rejection drives `SUBMITTED` to `REJECTED` and increments the invoice's
    `version`." PRD §3.5: "The **cumulative invoiced amount** is the sum of `amount_cents`
    over the contract's invoices whose status is `APPROVED`; submitted and rejected
    invoices contribute nothing."

    Design: Corner/endpoints/reject_invoice_sets_rejected
    """
    ctx = setup_active_ffp_contract(base_value_cents=50000000, with_clin=True,
                                    clin_unit_price=50000, clin_funded_qty=100,
                                    vendor_uei="REJV00000001",
                                    close_at="2026-02-05T00:00:00Z")
    cid = ctx["contract"]["id"]
    cv = fresh_contract_version(cid)
    invoice = get_success_data(
        api.create_invoice(
            create_ffp_invoice_payload(cid, ctx["clin"]["id"], 30, cv),
            make_vendor_headers(ctx["vendor"]["id"]),
        )
    )
    rejected = validate_success(api.reject_invoice(invoice["id"], CO), 200)
    assert rejected["status"] == "REJECTED", f"expected REJECTED, got {rejected['status']}"
    contract = validate_success(api.get_contract(cid, CO), 200)
    assert contract["cumulative_invoiced_cents"] == 0, (
        f"expected cumulative 0 (rejected invoice excluded), "
        f"got {contract['cumulative_invoiced_cents']}"
    )


# ─── Default logical clock (scheduled action) ──────────────────────
def test_default_clock_allows_open_at_startup_default(api):
    """PRD §2.4: "On server startup the logical clock reads exactly
    `2026-01-01T00:00:00Z`, and until it is explicitly moved it stays at that default and
    never falls back to real time." PRD §3.2: "Opening is permitted only when at least one
    evaluation factor exists for the solicitation, exactly one factor of kind `PRICE`
    exists, the sum of the weights across the non-price factors equals 1.0, and the
    `open_at` lies at or before the current logical clock."

    Design: Corner/cross_cutting_complexity_layers/scheduled_clock_default_startup_value
    """
    # NB: no clock-set call is issued in this test; the clock holds the startup default.
    sol, _ = create_draft_solicitation_with_factors(
        open_at="2026-01-01T00:00:00Z", close_at="2026-03-01T00:00:00Z"
    )
    opened = validate_success(api.open_solicitation(sol["id"], CO), 200)
    assert opened["status"] == "OPEN", (
        f"clock == startup default 2026-01-01T00:00:00Z >= open_at; "
        f"expected OPEN, got {opened['status']}"
    )


# ─── Cross-entity state dependency: proposal submit needs ACTIVE vendor ─
def test_submit_proposal_requires_active_vendor(api):
    """PRD §3.3: "The submitting vendor's registration must have a `sam_status` of
    `ACTIVE` and a `registration_expires_at` strictly after the current logical clock; a
    submission from a vendor that is not active or whose registration has lapsed is
    rejected with `ERR_REGISTRATION_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/proposal_submit_requires_vendor_active
    """
    from test_helpers import create_proposal_payload, create_score_payload
    set_clock("2026-02-01T00:00:00Z")
    sol, factors = create_draft_solicitation_with_factors(
        open_at="2026-02-01T00:00:00Z", close_at="2026-03-01T00:00:00Z"
    )
    open_solicitation(sol["id"])
    # A DRAFT vendor that is never activated.
    vendor = get_success_data(
        api.create_vendor(create_vendor_payload(legal_name="DraftVendor", uei="DRFT00000001",
                                                employee_count=5), VENDOR_FALLBACK)
    )
    vh = make_vendor_headers(vendor["id"])
    prop = get_success_data(
        api.create_proposal(create_proposal_payload(sol["id"], vendor["id"], 40000000), vh)
    )
    get_success_data(api.add_score(prop["id"], create_score_payload(factors["TECHNICAL"]["id"], 90), vh))
    get_success_data(api.add_score(prop["id"], create_score_payload(factors["PRICE"]["id"], 100), vh))
    res = api.submit_proposal(prop["id"], vh)
    validate_error(res, "ERR_REGISTRATION_NOT_ACTIVE", expected_status=422)


def test_submit_proposal_with_active_vendor_succeeds(api):
    """PRD §3.3: "The submitting vendor's registration must have a `sam_status` of
    `ACTIVE` and a `registration_expires_at` strictly after the current logical clock".

    Partner: an ACTIVE vendor (entity-pair satisfied) submits successfully.

    Design: Difficulty/cross_entity_state_dependency/proposal_submit_requires_vendor_active
    """
    from test_helpers import create_proposal_payload, create_score_payload
    set_clock("2026-02-01T00:00:00Z")
    vendor = create_active_vendor("DRFT00000002", employee_count=5)
    sol, factors = create_draft_solicitation_with_factors(
        open_at="2026-02-01T00:00:00Z", close_at="2026-03-01T00:00:00Z"
    )
    open_solicitation(sol["id"])
    vh = make_vendor_headers(vendor["id"])
    prop = get_success_data(
        api.create_proposal(create_proposal_payload(sol["id"], vendor["id"], 40000000), vh)
    )
    get_success_data(api.add_score(prop["id"], create_score_payload(factors["TECHNICAL"]["id"], 90), vh))
    get_success_data(api.add_score(prop["id"], create_score_payload(factors["PRICE"]["id"], 100), vh))
    submitted = validate_success(api.submit_proposal(prop["id"], vh), 200)
    assert submitted["status"] == "SUBMITTED", (
        f"an ACTIVE vendor must submit successfully; got {submitted['status']}"
    )


# ─── RBAC / auth ───────────────────────────────────────────────────
def test_vendor_cannot_open_solicitation(api):
    """PRD §2.1: "A request whose role is not permitted to perform the requested operation
    is rejected with `ERR_FORBIDDEN_ROLE`." PRD §4: opening a solicitation is authorized
    for ContractingOfficer only.

    Design: Corner/rbac/vendor_cannot_open_solicitation
    """
    set_clock("2026-02-01T00:00:00Z")
    sol, _ = create_draft_solicitation_with_factors(
        open_at="2026-02-01T00:00:00Z", close_at="2026-03-01T00:00:00Z"
    )
    res = api.open_solicitation(sol["id"], make_vendor_headers("some-vendor-id"))
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_auditor_cannot_create_vendor(api):
    """PRD §2.1: "An auditor may read every resource in the system but may mutate nothing."
    PRD §2.1: "A request whose role is not permitted to perform the requested operation is
    rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/auditor_cannot_create_vendor
    """
    res = api.create_vendor(create_vendor_payload(legal_name="AuditAttempt", uei="AUDT00000001",
                                                  employee_count=5),
                            TEST_USERS["auditor_headers"])
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "Every request to the API must be authenticated by two mandatory HTTP
    headers: `X-User-ID`, which identifies the acting operator, and `X-User-Role`, which
    declares the capacity in which they act."
    PRD §2.1: "A request missing either header is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_header_unauthenticated
    """
    res = api.list_vendors({})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


# ─── helpers ───────────────────────────────────────────────────────
def _list_clins(api, contract_id):
    from test_helpers import validate_paginated as _vp
    resp = api.list_clins(contract_id, CO)
    try:
        return _vp(resp)
    except AssertionError:
        # Non-paginated list fallback: return raw data list with empty meta.
        body = resp.json()
        return body["data"], body.get("meta", {})
