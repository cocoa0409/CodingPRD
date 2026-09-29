"""Corner queue - section errors, part F: settlement arithmetic and closure refusals."""
from test_helpers import (
    ApiErrorId,
    add_nested,
    approve_plan,
    assert_instant_equals,
    calibrate,
    corridor,
    decide_payment,
    draft_plan,
    licensed_respondent,
    make_respondent_headers,
    new_jurisdiction,
    open_profile,
    progress_plan,
    read_payment,
    read_plan,
    read_respondent,
    setup_approved_respondent,
    submit_payment,
    submit_plan,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ANALYST, COMMITTEE, OFFICER, RM


def _de():
    return new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )


def test_settlement_allocation_arithmetic_guards_all_three_refusals(api):
    """Three distinct refusals share one endpoint, and the obligation invariant survives every
    one of them - while the three-corridor split shows the negative residue landing entirely on
    the first line.

    Design: Corner/errors/settlement_allocation_arithmetic_guards_all_three_refusals
    """
    _de()
    new_jurisdiction(
        jurisdiction_code="JP", name="Japan", basel_aml_index=3.0, corridor_risk_weight=1.0
    )
    new_jurisdiction(
        jurisdiction_code="GB", name="United Kingdom", basel_aml_index=3.5,
        corridor_risk_weight=1.0,
    )
    bundle = setup_approved_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    rid = bundle["respondent"]["id"]
    open_profile(
        rid,
        [corridor("DE", 300000.00, 60), corridor("JP", 200000.00, 40),
         corridor("GB", 100000.00, 20)],
    )
    plan = draft_plan(
        rid, RM, termination_reason="COMMERCIAL", cap_basis="FORWARD_PROJECTED",
        original_obligation_cents=1000000,
    )
    submit_plan(plan["id"])
    approved = approve_plan(plan["id"])
    assert approved["notice_period_days"] == 105
    assert approved["wind_down_cap_usd"] == 1050000.00

    first = validate_success(
        api.allocate_settlement(plan["id"], {"action": "ALLOCATE", "amount_cents": 1001}, RM)
    )
    assert [(line["jurisdiction_code"], line["line_cents"]) for line in
            first["allocation_lines"]] == [("DE", 500), ("JP", 334), ("GB", 167)]
    assert first["settled_cents"] == 1001
    assert first["outstanding_obligation_cents"] == 998999
    assert first["allocation_round"] == 1
    assert first["last_allocated_cents"] == 1001

    mismatch = api.allocate_settlement(
        plan["id"], {"action": "REVERSE", "amount_cents": 999}, RM
    )
    validate_error(mismatch, ApiErrorId.ERR_REVERSAL_AMOUNT_MISMATCH, expected_status=422)
    unchanged = read_plan(plan["id"])
    assert unchanged["settled_cents"] == 1001
    assert unchanged["allocation_round"] == 1
    assert unchanged["outstanding_obligation_cents"] + unchanged["settled_cents"] == 1000000

    over = api.allocate_settlement(
        plan["id"], {"action": "ALLOCATE", "amount_cents": 999000}, RM
    )
    validate_error(over, ApiErrorId.ERR_SETTLEMENT_EXCEEDS_OUTSTANDING, expected_status=422)
    assert read_plan(plan["id"])["settled_cents"] == 1001

    reversed_plan = validate_success(
        api.allocate_settlement(plan["id"], {"action": "REVERSE", "amount_cents": 1001}, RM)
    )
    assert reversed_plan["settled_cents"] == 0
    assert reversed_plan["outstanding_obligation_cents"] == 1000000
    assert reversed_plan["allocation_round"] == 0
    assert reversed_plan["last_allocated_cents"] == 0
    assert reversed_plan["allocation_lines"] == []

    nothing_left = api.allocate_settlement(
        plan["id"], {"action": "REVERSE", "amount_cents": 1001}, RM
    )
    validate_error(nothing_left, ApiErrorId.ERR_NO_ALLOCATION_TO_REVERSE, expected_status=422)

    exact = validate_success(
        api.allocate_settlement(plan["id"], {"action": "ALLOCATE", "amount_cents": 1000000}, RM)
    )
    assert [(line["jurisdiction_code"], line["line_cents"]) for line in
            exact["allocation_lines"]] == [("DE", 500000), ("JP", 333333), ("GB", 166667)]
    assert exact["settled_cents"] == 1000000
    assert exact["outstanding_obligation_cents"] == 0
    assert exact["allocation_round"] == 1

    against_zero = api.allocate_settlement(
        plan["id"], {"action": "ALLOCATE", "amount_cents": 1}, RM
    )
    validate_error(
        against_zero, ApiErrorId.ERR_SETTLEMENT_EXCEEDS_OUTSTANDING, expected_status=422
    )
    settled = read_plan(plan["id"])
    assert settled["outstanding_obligation_cents"] + settled["settled_cents"] == 1000000


def test_wind_down_releases_stop_at_the_cap(api):
    """The cap is a running ledger rather than a per-payment limit, so two identical releases
    against it behave differently, and the refused one adds nothing to the ledger.

    Design: Corner/errors/wind_down_releases_stop_at_the_cap_and_the_posture_check_outranks_it
    """
    _de()
    bundle = setup_approved_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=1000.00, expected_monthly_count=10,
    )
    rid = bundle["respondent"]["id"]
    profile = open_profile(rid, [corridor("DE", 1000.00, 10)])
    calibrated = calibrate(profile["id"])
    assert calibrated["hold_threshold_usd"] == 1100.00
    validate_success(api.amend_respondent(rid, {"payment_posture": "SCREEN_ONLY"}, RM))

    held = []
    for _ in range(2):
        instruction = submit_payment(
            rid, "DE", "DE", amount_usd=1500.00, purpose_code="SETTLEMENT"
        )
        assert instruction["screening_state"] == "HELD_FOR_REVIEW"
        assert instruction["hold_reason"] == "POSTURE_SCREEN_ONLY"
        held.append(instruction)

    plan = draft_plan(
        rid, RM, termination_reason="COMMERCIAL", cap_basis="FORWARD_PROJECTED",
        original_obligation_cents=0,
    )
    submit_plan(plan["id"])
    approved = approve_plan(plan["id"])
    assert approved["notice_period_days"] == 90
    assert approved["wind_down_cap_usd"] == 1800.00
    assert read_respondent(rid)["payment_posture"] == "WIND_DOWN_ONLY"
    served = progress_plan(plan["id"], "SERVE_NOTICE")
    assert_instant_equals(served["wind_down_end_at"], "2026-10-30T00:00:00Z")

    released = decide_payment(held[0]["id"], "RELEASE", "WIND_DOWN_PERMITTED")
    assert released["screening_state"] == "RELEASED"
    assert read_plan(plan["id"])["wind_down_released_usd"] == 1500.00

    over_cap = api.decide_screening(
        held[1]["id"], {"action": "RELEASE", "decision_reason": "WIND_DOWN_PERMITTED"}, OFFICER
    )
    validate_error(over_cap, ApiErrorId.ERR_WIND_DOWN_CAP_EXCEEDED, expected_status=422)
    assert read_payment(held[1]["id"])["screening_state"] == "HELD_FOR_REVIEW"
    assert read_plan(plan["id"])["wind_down_released_usd"] == 1500.00


def test_chronological_cap_basis_without_any_activity_history(api):
    """The empty-history case refuses at approval rather than falling back to the declared
    volume, and the plan is still disposable afterwards, which unwinds the exit posture.

    Design: Corner/errors/chronological_cap_basis_without_any_activity_history
    """
    _de()
    bundle = setup_approved_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    rid = bundle["respondent"]["id"]
    plan = draft_plan(
        rid, RM, termination_reason="RISK_APPETITE", cap_basis="CHRONOLOGICAL_ACTUAL",
        original_obligation_cents=0,
    )
    assert plan["notice_period_days"] == 60
    assert plan["state"] == "DRAFT"
    drafting = read_respondent(rid)
    assert drafting["dd_state"] == "EXITING"
    assert drafting["payment_posture"] == "WIND_DOWN_ONLY"
    assert submit_plan(plan["id"])["state"] == "PENDING_APPROVAL"

    refused = api.approve_closure_plan(plan["id"], {"action": "APPROVE"}, COMMITTEE)
    validate_error(
        refused, ApiErrorId.ERR_INSUFFICIENT_ACTIVITY_HISTORY, expected_status=422
    )
    stored = read_plan(plan["id"])
    assert stored["state"] == "PENDING_APPROVAL"
    assert stored["approved_by_user_id"] is None

    rejected = approve_plan(plan["id"], "REJECT")
    assert rejected["state"] == "ABORTED"
    assert rejected["abort_reason"] == "COMMERCIAL_DECISION"
    unwound = read_respondent(rid)
    assert unwound["dd_state"] == "APPROVED"
    assert unwound["payment_posture"] == "SCREEN_ONLY"


def test_a_nested_chain_that_revisits_a_respondent_is_a_cycle(api):
    """Two known respondents each naming the other closes the only loop the API can build, and
    the same configuration is refused when declared but stored as prohibited when detected.

    Design: Corner/errors/a_nested_chain_that_revisits_a_respondent_is_a_cycle
    """
    _de()
    bank_a = licensed_respondent(
        "DE", legal_name="A Bank AG", swift_bic="ABNKDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    bank_b = licensed_respondent(
        "DE", legal_name="B Bank AG", swift_bic="BBNKDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    assert bank_a["nested_activity_permitted"] is False
    assert bank_b["nested_activity_permitted"] is False
    outward = add_nested(
        bank_a["id"], "DE", ANALYST, downstream_institution_name="B Bank AG",
        discovery_source="QUESTIONNAIRE", downstream_respondent_bank_id=bank_b["id"],
    )
    assert outward["state"] == "DISCLOSED"
    assert outward["depth"] == 1

    declared = api.create_nested_relationship(
        bank_b["id"],
        {"downstream_institution_name": "A Bank AG", "downstream_jurisdiction_code": "DE",
         "relationship_type": "PAYABLE_THROUGH", "discovery_source": "QUESTIONNAIRE",
         "downstream_respondent_bank_id": bank_a["id"]},
        make_respondent_headers(bank_b["id"]),
    )
    validate_error(declared, ApiErrorId.ERR_NESTED_CYCLE_DETECTED, expected_status=422)
    _rows, meta = validate_paginated(
        api.list_nested_relationships(ANALYST, params={"respondent_bank_id": bank_b["id"]})
    )
    assert meta["total_count"] == 0

    detected = validate_success(
        api.create_nested_relationship(
            bank_b["id"],
            {"downstream_institution_name": "A Bank AG", "downstream_jurisdiction_code": "DE",
             "relationship_type": "PAYABLE_THROUGH",
             "discovery_source": "TRANSACTION_MONITORING",
             "downstream_respondent_bank_id": bank_a["id"]},
            ANALYST,
        ),
        expected_status=201,
    )
    assert detected["state"] == "PROHIBITED"
    assert detected["prohibition_reason"] == "CYCLE"

    rolled_up = read_respondent(bank_b["id"])
    assert rolled_up["nested_exposure_units"] == 0
    assert rolled_up["max_nested_depth"] == 0
