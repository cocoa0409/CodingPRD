"""Settlement-post validation precedence, the contract-priced state dependency, and
single-violation error scenarios.

Queue A (Difficulty) — priority_pair_validation_conflict (mismatch>not-priced,
                       overfill>insufficient), cross_entity_state_dependency
                       (settlement requires contract priced).
Queue B (Corner) — validations (freeze program mismatch, existence-before-state),
                   errors (unauthenticated, margin-call-unmet, bad enum, stale version).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS, build_user_headers,
)
import test_helpers.fixtures as fx

MERCH = TEST_USERS["merchandiser_headers"]
CLERK = TEST_USERS["grade_clerk_headers"]
OFFICER = TEST_USERS["settlement_officer_headers"]
RISK = TEST_USERS["risk_manager_headers"]


def _post_with_version(api, settlement_id, position_id, role=OFFICER):
    pos = validate_success(api.get_storage_position(position_id, OFFICER))
    return api.post_settlement(
        settlement_id, {"expected_storage_position_version": pos["version"]}, role
    )


def test_settlement_commodity_mismatch_beats_contract_not_priced(api):
    """PRD §2.6: "a settlement post checks commodity/member coherence, contract pricing
    readiness, contract overfill, and bushel availability". PRD §3.5: "The contract and
    the storage position must share both `commodity_id` and `member_id`; if they do not,
    the post is rejected with `ERR_COMMODITY_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/settlement_state_beats_referential_contract_not_priced_vs_commodity_mismatch
    """
    fx.reset_clock_default()
    corn = fx.create_commodity()
    wheat = fx.create_wheat_commodity()
    fx.create_price_board(corn["id"])
    member = fx.create_member(name="Hank Farm")
    # WHEAT position for member
    _, _, _graded, position = fx.create_graded_position(
        commodity_id=wheat["id"], member_id=member["id"],
        gross_weight_lbs=76000, tare_weight_lbs=16000, moisture_pct=13.5, member_name="Hank Farm",
    )
    # OPEN (unpriced) CASH contract on CORN -> both commodity mismatch AND not-priced hold
    contract = fx.create_open_cash_contract(member["id"], corn["id"], contracted_bushels=1000)
    settlement = fx.create_draft_settlement(contract["id"], position["id"], priced_bushels=500)
    resp = _post_with_version(api, settlement["id"], position["id"])
    validate_error(resp, ApiErrorId.ERR_COMMODITY_MISMATCH.value)


def test_settlement_commodity_mismatch_leaves_settlement_draft(api):
    """PRD §3.5: "if they do not, the post is rejected with `ERR_COMMODITY_MISMATCH`."
    PRD §3.5: "A settlement is born `DRAFT` and carries no ledger effects until it is
    posted."

    Design: Difficulty/priority_pair_validation_conflict/settlement_state_beats_referential_contract_not_priced_vs_commodity_mismatch
    """
    fx.reset_clock_default()
    corn = fx.create_commodity()
    wheat = fx.create_wheat_commodity()
    fx.create_price_board(corn["id"])
    member = fx.create_member(name="Hank2 Farm")
    _, _, _graded, position = fx.create_graded_position(
        commodity_id=wheat["id"], member_id=member["id"],
        gross_weight_lbs=76000, tare_weight_lbs=16000, moisture_pct=13.5, member_name="Hank2 Farm",
    )
    contract = fx.create_open_cash_contract(member["id"], corn["id"], contracted_bushels=1000)
    settlement = fx.create_draft_settlement(contract["id"], position["id"], priced_bushels=500)
    _post_with_version(api, settlement["id"], position["id"])
    after = validate_success(api.get_settlement(settlement["id"], OFFICER))
    assert after["status"] == "DRAFT"


def test_settlement_overfill_beats_insufficient_bushels(api):
    """PRD §2.6: "a settlement post checks commodity/member coherence, contract pricing
    readiness, contract overfill, and bushel availability". PRD §3.5: "The bushels drawn
    must not exceed the contract's remaining unfilled room, that is the contracted bushels
    minus the already-priced bushels; exceeding it yields `ERR_CONTRACT_OVERFILL`."

    Design: Difficulty/priority_pair_validation_conflict/settlement_overfill_beats_insufficient_bushels_constraint_pair
    """
    fx.reset_clock_default()
    corn = fx.create_commodity()
    fx.create_price_board(corn["id"])
    member = fx.create_member(name="Ivy Farm")
    _, _, _graded, position = fx.create_graded_position(
        commodity_id=corn["id"], member_id=member["id"], member_name="Ivy Farm",
    )
    contract = fx.create_priced_cash_contract(member["id"], corn["id"], contracted_bushels=1000)
    # 1500 exceeds both the 1000 contract room and the 1000 available bushels
    settlement = fx.create_draft_settlement(contract["id"], position["id"], priced_bushels=1500)
    resp = _post_with_version(api, settlement["id"], position["id"])
    validate_error(resp, ApiErrorId.ERR_CONTRACT_OVERFILL.value)


def test_settlement_overfill_leaves_position_undrawn(api):
    """PRD §3.5: "exceeding it yields `ERR_CONTRACT_OVERFILL`." PRD §3.5: "the position's
    `bushels_available` is reduced by the priced bushels" (only on a successful post).

    Design: Difficulty/priority_pair_validation_conflict/settlement_overfill_beats_insufficient_bushels_constraint_pair
    """
    fx.reset_clock_default()
    corn = fx.create_commodity()
    fx.create_price_board(corn["id"])
    member = fx.create_member(name="Ivy2 Farm")
    _, _, _graded, position = fx.create_graded_position(
        commodity_id=corn["id"], member_id=member["id"], member_name="Ivy2 Farm",
    )
    contract = fx.create_priced_cash_contract(member["id"], corn["id"], contracted_bushels=1000)
    settlement = fx.create_draft_settlement(contract["id"], position["id"], priced_bushels=1500)
    _post_with_version(api, settlement["id"], position["id"])
    pos_after = validate_success(api.get_storage_position(position["id"], OFFICER))
    assert pos_after["bushels_available"] == 1000.0


def test_settlement_post_requires_contract_priced(api):
    """PRD §3.5: "The contract must be ready to settle — either `PRICED`, or a `FORWARD`
    contract with both legs fixed — otherwise `ERR_CONTRACT_NOT_PRICED`."

    Design: Difficulty/cross_entity_state_dependency/settlement_post_requires_contract_priced_state
    """
    fx.reset_clock_default()
    corn = fx.create_commodity()
    fx.create_price_board(corn["id"])
    member = fx.create_member(name="Kit Farm")
    _, _, _graded, position = fx.create_graded_position(
        commodity_id=corn["id"], member_id=member["id"], member_name="Kit Farm",
    )
    # OPEN (never fixed) CASH contract, same member/commodity -> only not-priced fires
    contract = fx.create_open_cash_contract(member["id"], corn["id"], contracted_bushels=1000)
    settlement = fx.create_draft_settlement(contract["id"], position["id"], priced_bushels=500)
    resp = _post_with_version(api, settlement["id"], position["id"])
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_PRICED.value)


def test_settlement_not_priced_leaves_contract_open_and_settlement_draft(api):
    """PRD §3.5: "otherwise `ERR_CONTRACT_NOT_PRICED`." PRD §3.4: "A contract is born
    `OPEN`." PRD §3.5: "A settlement is born `DRAFT`".

    Design: Difficulty/cross_entity_state_dependency/settlement_post_requires_contract_priced_state
    """
    fx.reset_clock_default()
    corn = fx.create_commodity()
    fx.create_price_board(corn["id"])
    member = fx.create_member(name="Kit2 Farm")
    _, _, _graded, position = fx.create_graded_position(
        commodity_id=corn["id"], member_id=member["id"], member_name="Kit2 Farm",
    )
    contract = fx.create_open_cash_contract(member["id"], corn["id"], contracted_bushels=1000)
    settlement = fx.create_draft_settlement(contract["id"], position["id"], priced_bushels=500)
    _post_with_version(api, settlement["id"], position["id"])
    contract_after = validate_success(api.get_contract(contract["id"], MERCH))
    settlement_after = validate_success(api.get_settlement(settlement["id"], OFFICER))
    assert contract_after["status"] == "OPEN"
    assert settlement_after["status"] == "DRAFT"


def test_freeze_charge_on_warehouse_receipt_returns_program_mismatch(api):
    """PRD §3.3: "A `WAREHOUSE_RECEIPT` position does not accrue per-day storage and cannot
    be charge-frozen; attempting to freeze it is rejected with `ERR_PROGRAM_MISMATCH`."

    Design: Corner/validations/freeze_charge_on_warehouse_receipt_position_returns_program_mismatch
    """
    fx.reset_clock_default()
    commodity = fx.create_commodity()
    member = fx.create_member(name="KK Farm")
    _, _, _graded, position = fx.create_graded_position(
        commodity_id=commodity["id"], member_id=member["id"],
        deposit_account_type="WAREHOUSE_RECEIPT", member_name="KK Farm",
    )
    resp = api.freeze_charge(position["id"], MERCH)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_MISMATCH.value)
    after = validate_success(api.get_storage_position(position["id"], OFFICER))
    assert after["status"] == "STORED"


def test_existence_checked_before_state_on_grade(api):
    """PRD §2.6: "then the existence of every path id and body foreign key
    (`ERR_NOT_FOUND`), then request-body shape and field constraints
    (`ERR_INVALID_REQUEST`). Only after those four universal gates pass does the system
    evaluate state-machine eligibility (`ERR_INVALID_STATE`)".

    Design: Corner/validations/existence_before_state_grade_nonexistent_ticket_returns_not_found
    """
    resp = api.grade_scale_ticket("00000000-0000-4000-8000-000000000999", CLERK)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_unknown_role_header_returns_unauthenticated(api):
    """PRD §2.1: "If `X-User-Role` is missing or does not name one of the five known roles,
    the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/error_unauthenticated_unknown_role_header
    """
    headers = build_user_headers("test-user", "NotARole")
    resp = api.get_commodity("00000000-0000-4000-8000-000000000000", headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_meet_call_underfunded_deposit_returns_margin_call_unmet(api):
    """PRD §3.8: "the deposit must be at least the outstanding `margin_call_dollars`; a
    deposit short of the call is rejected with `ERR_MARGIN_CALL_UNMET`."

    Design: Corner/errors/error_margin_call_unmet_underfunded_deposit
    """
    commodity = fx.create_commodity()
    hedge, _marked = fx.open_hedge_in_margin_call(commodity_id=commodity["id"])
    hp = validate_success(api.get_hedge_position(hedge["id"], RISK))
    resp = api.meet_call(
        hedge["id"],
        {"deposit_dollars": 4000, "expected_hedge_position_version": hp["version"]},
        RISK,
    )
    validate_error(resp, ApiErrorId.ERR_MARGIN_CALL_UNMET.value)
    after = validate_success(api.get_hedge_position(hedge["id"], RISK))
    assert after["status"] == "MARGIN_CALL"
    assert after["margin_call_dollars"] == 4500.00


def test_create_contract_bad_type_enum_returns_invalid_request(api):
    """PRD §2.5: "every enum value must fall within its declared set ... Any of these
    failures yields `ERR_INVALID_REQUEST` (HTTP 422)." PRD §3.4: "the `contract_type`
    (`CASH`, `FORWARD`, `BASIS`, or `HTA`)".

    Design: Corner/errors/error_invalid_request_bad_contract_type_enum
    """
    commodity = fx.create_commodity()
    member = fx.create_member(name="NN Farm")
    resp = api.create_contract(
        {
            "member_id": member["id"], "commodity_id": commodity["id"],
            "contract_type": "SWAP", "contracted_bushels": 1000,
        },
        MERCH,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_settlement_post_stale_position_version_returns_stale_version(api):
    """PRD §2.10: "A post request must carry `expected_storage_position_version` ... The
    server compares it against the position's current `version`; if they do not match —
    because a prior settlement post or a shipment load already drew down that position's
    `bushels_available` and advanced its `version` since the client read it — the post is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/error_stale_version_settlement_post_412
    """
    fx.reset_clock_default()
    commodity = fx.create_commodity()
    fx.create_price_board(commodity["id"])
    member = fx.create_member(name="SS Farm")
    _, _, _graded, position = fx.create_graded_position(
        commodity_id=commodity["id"], member_id=member["id"], member_name="SS Farm",
    )
    stale_pos = validate_success(api.get_storage_position(position["id"], OFFICER))
    stale_version = stale_pos["version"]
    # a freeze advances the position version past the observed value
    api.freeze_charge(position["id"], MERCH)
    contract = fx.create_priced_cash_contract(member["id"], commodity["id"], contracted_bushels=1000)
    settlement = fx.create_draft_settlement(
        contract["id"], position["id"], priced_bushels=400, storage_basis="ESTIMATE"
    )
    resp = api.post_settlement(
        settlement["id"], {"expected_storage_position_version": stale_version}, OFFICER
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    after = validate_success(api.get_settlement(settlement["id"], OFFICER))
    assert after["status"] == "DRAFT"
