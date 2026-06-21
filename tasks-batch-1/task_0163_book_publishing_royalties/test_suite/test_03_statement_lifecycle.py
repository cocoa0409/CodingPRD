"""Statement and contract lifecycle: branching side-effects, tax at pay,
subsidiary-right fork, period bubble-up, terminal lockdown, and version bumps.

Covers depth instances under non_linear_state_machine plus corner state_machine,
cross_cutting, and consistency_model instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    fixtures,
    TEST_USERS,
    ApiErrorId,
)

PUB = TEST_USERS["publisher_headers"]


# ==========================================================================
# Queue A — non_linear_state_machine
# ==========================================================================
def test_finalize_then_pay_divergent_side_effects_tax_only_at_pay(api):
    """PRD §3.6: "Payment is the terminal step and the only point at which tax is
    applied. The Publisher pays a `FINALIZED` statement, transitioning its
    `status` from `FINALIZED` to `PAID` ... On payment the system computes
    `tax_withheld_cents` as the author-facing amount — `payable_before_commission_cents`
    minus `agent_commission_cents` — multiplied by the author's
    `tax_withholding_pct`, rounded half up to whole cents, then recomputes
    `net_to_author_cents`"

    PRD §3.6: "Before payment, `tax_withheld_cents` carries its default of 0."

    Gross 300000, no reserve/commission, tax_withholding 0.10: tax 0 at finalize,
    30000 at pay, net 270000, status PAID.

    Design: Difficulty/non_linear_state_machine/statement_branching_draft_finalized_paid_divergent_side_effects
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.SINGLE_TIER,
        advance_cents=0,
        reserve_pct=0,
        reserve_hold_periods=1,
        agent_commission_pct=0,
        tax_withholding_pct=0.10,
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]

    period = fixtures.run_period_to_closed(cid, fid, "P1", 1, 1000, 0)
    s1 = get_success_data(api.generate_statement(period["id"], PUB))
    s1 = fixtures.finalize_statement(s1["id"], cid)
    assert s1["tax_withheld_cents"] == 0, "tax not applied on the FINALIZE edge"

    s1 = fixtures.pay_statement(s1["id"], cid)
    assert s1["tax_withheld_cents"] == 30000
    assert s1["net_to_author_cents"] == 270000
    assert s1["status"] == "PAID"


def test_subsidiary_right_forks_void_or_statemented(api):
    """PRD §3.4: "A `REGISTERED` right that never closed — a deal that fell
    through — may be voided by the Publisher, moving its `status` to `VOID`."

    PRD §3.4: "The other path a right can take — from `REGISTERED` to the terminal
    `STATEMENTED` — happens automatically when a statement finalize credits it"

    PRD §3.6: "It transitions each credited `SubsidiaryRight` from `REGISTERED` to
    `STATEMENTED` and stamps its `statement_id` with this statement's `id`."

    Two REGISTERED rights: one voided (VOID), one credited at finalize
    (STATEMENTED with statement_id stamped, income 400000).

    Design: Difficulty/non_linear_state_machine/subsidiary_right_branching_statemented_or_void
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.SINGLE_TIER, advance_cents=0, reserve_pct=0, reserve_hold_periods=1
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]

    r_void = get_success_data(
        api.create_subsidiary_right(
            cid, {"right_type": "FOREIGN", "proceeds_cents": 1000000, "author_share_pct": 0.50}, PUB
        )
    )
    r_keep = get_success_data(
        api.create_subsidiary_right(
            cid, {"right_type": "AUDIO", "proceeds_cents": 800000, "author_share_pct": 0.50}, PUB
        )
    )

    period = fixtures.run_period_to_closed(cid, fid, "P1", 1, 100, 0)
    s1 = get_success_data(api.generate_statement(period["id"], PUB))

    voided = validate_success(api.void_subsidiary_right(r_void["id"], PUB))
    assert voided["status"] == "VOID"

    s1 = fixtures.finalize_statement(s1["id"], cid)

    kept = validate_success(api.get_subsidiary_right(r_keep["id"], PUB))
    assert kept["status"] == "STATEMENTED"
    assert kept["statement_id"] == s1["id"]
    assert s1["subsidiary_income_cents"] == 400000


# ==========================================================================
# Queue B — corner state_machines
# ==========================================================================
def test_contract_initial_state_is_draft(api):
    """PRD §3.1: "A contract is born in `DRAFT` status."

    Design: Corner/state_machines/contract_initial_state_is_draft
    """
    author = fixtures.create_author()
    contract = validate_success(
        api.create_contract({"author_id": author["id"], "advance_cents": 0}, PUB), 201
    )
    assert contract["status"] == "DRAFT"


def test_activate_contract_valid_transition(api):
    """PRD §3.1: "On success, activation sets `status` to `ACTIVE`, re-establishes
    `unrecouped_advance_cents` as `advance_cents`, and advances the contract's
    `version` by one."

    Design: Corner/state_machines/activate_contract_valid_transition
    """
    author = fixtures.create_author()
    contract = fixtures.create_contract(
        author["id"], advance_cents=700000, reserve_pct=0.25, reserve_hold_periods=2
    )
    fixtures.add_tiers(contract["id"], fixtures.SINGLE_TIER)
    title = fixtures.add_title(contract["id"], name="Act Book")
    fixtures.add_format(title["id"], list_price_cents=3000)

    activated = validate_success(api.activate_contract(contract["id"], PUB))
    assert activated["status"] == "ACTIVE"
    assert activated["unrecouped_advance_cents"] == 700000


def test_activate_without_tiers_rejected(api):
    """PRD §3.1: "a contract lacking tiers, a title, or a format is rejected at
    activation with `ERR_CONTRACT_NOT_READY` (HTTP 409)."

    Design: Corner/state_machines/activate_without_tiers_rejected
    """
    author = fixtures.create_author()
    contract = fixtures.create_contract(author["id"], advance_cents=0)
    title = fixtures.add_title(contract["id"], name="NoTier Book")
    fixtures.add_format(title["id"], list_price_cents=3000)

    resp = api.activate_contract(contract["id"], PUB)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_READY.value)


def test_publish_title_with_no_format_rejected(api):
    """PRD §3.2: "a title with zero formats cannot be published and the attempt is
    rejected with `ERR_TITLE_HAS_NO_FORMAT` (HTTP 409)."

    Design: Corner/state_machines/publish_title_with_no_format_rejected
    """
    author = fixtures.create_author()
    contract = fixtures.create_contract(author["id"], advance_cents=0)
    fixtures.add_tiers(contract["id"], fixtures.SINGLE_TIER)
    anchor = fixtures.add_title(contract["id"], name="Anchor Title")
    fixtures.add_format(anchor["id"], list_price_cents=3000)
    empty = fixtures.add_title(contract["id"], name="Empty Title")
    get_success_data(api.activate_contract(contract["id"], PUB))

    resp = api.publish_title(empty["id"], PUB)
    validate_error(resp, ApiErrorId.ERR_TITLE_HAS_NO_FORMAT.value)


def test_pay_before_finalize_invalid_state(api):
    """PRD §3.1: "Any lifecycle transition requested against a resource not in the
    permitting state — finalizing a non-`DRAFT` statement, paying a
    non-`FINALIZED` statement, voiding a non-`REGISTERED` right, and the like — is
    rejected with `ERR_INVALID_STATE` (HTTP 409) where a more specific code does
    not govern."

    Design: Corner/state_machines/pay_before_finalize_invalid_from
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.SINGLE_TIER, advance_cents=0, reserve_pct=0, reserve_hold_periods=1
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]

    period = fixtures.run_period_to_closed(cid, fid, "P1", 1, 50, 0)
    s1 = get_success_data(api.generate_statement(period["id"], PUB))

    cv = fixtures.current_version(cid)
    resp = api.pay_statement(s1["id"], {"expected_contract_version": cv}, PUB)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_terminated_contract_relock(api):
    """PRD §3.1: "Once `TERMINATED`, the contract blocks all further posting."

    PRD §3.1: "Any lifecycle transition requested against a resource not in the
    permitting state ... is rejected with `ERR_INVALID_STATE` (HTTP 409) where a
    more specific code does not govern."

    Re-terminating a TERMINATED contract returns ERR_INVALID_STATE.

    Design: Corner/state_machines/terminated_contract_lockdown
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.SINGLE_TIER, advance_cents=0, reserve_pct=0, reserve_hold_periods=1, publish=False
    )
    cid = base["contract"]["id"]
    validate_success(api.terminate_contract(cid, PUB))

    resp = api.terminate_contract(cid, PUB)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_generate_statement_twice_rejected(api):
    """PRD §3.5: "a second generate against a period that already has a statement
    is rejected with `ERR_STATEMENT_EXISTS` (HTTP 409)."

    Design: Corner/state_machines/generate_statement_twice_idempotency_guard
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.SINGLE_TIER, advance_cents=0, reserve_pct=0, reserve_hold_periods=1
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]

    period = fixtures.run_period_to_closed(cid, fid, "P1", 1, 50, 0)
    get_success_data(api.generate_statement(period["id"], PUB))

    resp = api.generate_statement(period["id"], PUB)
    validate_error(resp, ApiErrorId.ERR_STATEMENT_EXISTS.value)


def test_finalize_bubbles_period_to_statemented(api):
    """PRD §3.6: "It transitions the owning `SalesPeriod` from `CLOSED` to
    `STATEMENTED`, bubbling up from the statement's finalize."

    Design: Corner/state_machines/period_statemented_bubble_up_on_finalize
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.SINGLE_TIER, advance_cents=0, reserve_pct=0, reserve_hold_periods=1
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]

    period = fixtures.run_period_to_closed(cid, fid, "P1", 1, 50, 0)
    s1 = get_success_data(api.generate_statement(period["id"], PUB))
    fixtures.finalize_statement(s1["id"], cid)

    reread = validate_success(api.get_sales_period(period["id"], PUB))
    assert reread["status"] == "STATEMENTED"


# ==========================================================================
# Queue B — cross_cutting_complexity_layers / consistency_model
# ==========================================================================
def test_contract_version_increments_on_activate(api):
    """PRD §2.4: "an integer `version` that begins at 1 and increments by one each
    time the resource is mutated."

    PRD §3.1: "On success, activation sets `status` to `ACTIVE`, re-establishes
    `unrecouped_advance_cents` as `advance_cents`, and advances the contract's
    `version` by one."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_each_mutation
    """
    author = fixtures.create_author()
    contract = validate_success(
        api.create_contract({"author_id": author["id"], "advance_cents": 0}, PUB), 201
    )
    assert contract["version"] == 1

    fixtures.add_tiers(contract["id"], fixtures.SINGLE_TIER)
    title = fixtures.add_title(contract["id"], name="Ver Book")
    fixtures.add_format(title["id"], list_price_cents=3000)

    activated = validate_success(api.activate_contract(contract["id"], PUB))
    assert activated["version"] == 2


def test_finalize_changes_visible_in_same_response(api):
    """PRD §3.6: "The Publisher finalizes a `DRAFT` statement, transitioning its
    `status` from `DRAFT` to `FINALIZED` ... On finalize, the system recomputes
    every monetary field against live state — this committed variant is canonical
    and supersedes the draft snapshot"

    Net 100 at 0.10*3000 = 30000 gross, visible with status FINALIZED in the
    finalize response itself.

    Design: Corner/consistency_model/finalize_changes_visible_in_same_response
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.SINGLE_TIER, advance_cents=0, reserve_pct=0, reserve_hold_periods=1
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]

    period = fixtures.run_period_to_closed(cid, fid, "P1", 1, 100, 0)
    s1 = get_success_data(api.generate_statement(period["id"], PUB))

    cv = fixtures.current_version(cid)
    finalized = validate_success(api.finalize_statement(s1["id"], {"expected_contract_version": cv}, PUB))
    assert finalized["status"] == "FINALIZED"
    assert finalized["gross_royalty_cents"] == 30000
