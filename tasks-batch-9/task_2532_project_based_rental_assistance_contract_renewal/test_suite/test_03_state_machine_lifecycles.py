"""State machines: declared openings, refused edges, repeated triggers, terminal states and
the two loops (study challenge, utility allowance rejection)."""
from test_helpers import (
    ApiErrorId,
    REFERENCE_HOUSEHOLD_ONE,
    TEST_USERS,
    api_client,
    assert_renewal_case,
    assert_unit_invariant,
    create_direct_ledger_claim,
    create_direct_ledger_claim_payload,
    create_renewal_case_payload,
    create_study_payload,
    create_tenant_notice_payload,
    create_utility_allowance_analysis_payload,
    create_ua_analysis,
    create_voucher,
    create_voucher_submission_payload,
    current_contract_version,
    decide_claim_payload,
    decide_utility_allowance_payload,
    elect_adjustment_payload,
    execute_renewal_payload,
    challenge_study_payload,
    create_comparable_payload,
    create_tenant_household_payload,
    move_out_payload,
    reverse_voucher_payload,
    select_option_payload,
    set_clock_date,
    setup_adjustment_elected,
    setup_certified_household,
    setup_portfolio,
    setup_reference_households,
    validate_error,
    validate_paginated,
    validate_success,
)

CA_HEADERS = TEST_USERS["contract_administrator_headers"]
CA_APPROVER_HEADERS = TEST_USERS["contract_administrator_approver_headers"]

ALDER_COURT = {
    "address_label": "88 Alder Court",
    "raw_rent_cents": 125000,
    "adjustment_total_cents": 4650,
    "utility_adjustment_cents": 1500,
    "weight": 3,
}


def test_every_created_entity_opens_in_its_declared_initial_state():
    """A case "begins with `renewal_option` and `adjustment_method` both null,
    `rcs_required` false", a study "is born in state `DRAFT` with `challenge_round` at 0",
    an analysis "is created in state `DRAFT`", "A new household is `ACTIVE`", a voucher "is
    created in state `DRAFT`", a claim lands "in state `DRAFT`" and a notice "is created with
    `status` `ISSUED`".

    Design: Corner/state_machines/every_created_entity_opens_in_its_declared_initial_state
    """
    ctx = setup_portfolio()
    contract_id = ctx["contract"]["id"]
    prop_id = ctx["property"]["id"]
    owner_headers = ctx["owner_headers"]
    set_clock_date("2026-12-01")

    case = validate_success(
        api_client.create_renewal_case(
            create_renewal_case_payload(contract_id), owner_headers
        ),
        expected_status=201,
    )
    assert_renewal_case(case)
    assert case["rent_track_status"] == "TERMS_PENDING"
    assert case["notice_track_status"] == "NOTICES_PENDING"
    assert case["opened_on_date"] == "2026-12-01"
    assert case["days_to_expiration_at_open"] == 395, (
        f"2026-12-01 to 2027-12-31 is 395 whole days, got {case['days_to_expiration_at_open']}"
    )
    assert case["rcs_required"] is False
    assert case["renewal_option"] is None
    assert case["adjustment_method"] is None
    assert case["approved_rent_per_unit_cents"] is None
    assert case["challenge_reviewer_user_id"] is None
    assert case["rents_approver_user_id"] is None
    assert case["opt_out_notice_id"] is None

    contract = validate_success(api_client.get_hap_contract(contract_id, CA_HEADERS))
    assert contract["lifecycle_status"] == "RENEWAL_PENDING", (
        f"opening a case moves the contract off ACTIVE, got {contract['lifecycle_status']}"
    )

    selected = validate_success(
        api_client.select_option(
            case["id"], select_option_payload("OPTION_2_OCAF"), owner_headers
        )
    )
    assert selected["rent_track_status"] == "OPTION_SELECTED"
    assert selected["rcs_required"] is False

    elected = validate_success(
        api_client.elect_adjustment(
            case["id"], elect_adjustment_payload("OCAF"), owner_headers
        )
    )
    assert elected["rent_track_status"] == "OPTION_SELECTED", (
        "recording the election is a self-transition on the rent track, got "
        f"{elected['rent_track_status']}"
    )
    assert elected["adjustment_method"] == "OCAF"

    study = validate_success(
        api_client.create_study(create_study_payload(case["id"]), owner_headers),
        expected_status=201,
    )
    assert study["state"] == "DRAFT"
    assert study["challenge_round"] == 0
    assert study["accepted_comparable_count"] == 0
    assert study["submitted_on_date"] is None
    assert study["last_challenge_reason"] is None

    analysis = validate_success(
        api_client.create_utility_allowance_analysis(
            create_utility_allowance_analysis_payload(
                prop_id, effective_date="2027-01-01", utility_rate_change_pct=0.09
            ),
            owner_headers,
        ),
        expected_status=201,
    )
    assert analysis["state"] == "DRAFT"
    assert analysis["approver_user_id"] is None
    assert analysis["applied_on_date"] is None
    assert analysis["recertified_tenant_count"] == 0

    household = validate_success(
        api_client.create_tenant_household(
            create_tenant_household_payload(prop_id, **REFERENCE_HOUSEHOLD_ONE),
            owner_headers,
        ),
        expected_status=201,
    )
    assert household["status"] == "ACTIVE"
    assert household["move_out_date"] is None
    assert household["ev_eligible"] is False

    voucher = validate_success(
        api_client.create_voucher_submission(
            create_voucher_submission_payload(
                contract_id, current_contract_version(contract_id), period_month="2026-07"
            ),
            owner_headers,
        ),
        expected_status=201,
    )
    assert voucher["state"] == "DRAFT"
    assert voucher["paid_amount_cents"] is None
    assert voucher["paid_on_date"] is None
    assert voucher["reversal_reason"] is None

    claim = validate_success(
        api_client.create_special_claim(
            create_direct_ledger_claim_payload(
                contract_id, "UNPAID_RENT", "101", "2026-07", 90000, 20000
            ),
            owner_headers,
        ),
        expected_status=201,
    )
    assert claim["state"] == "DRAFT"
    assert claim["paid_amount_cents"] is None
    assert claim["decision_reason"] is None

    notice = validate_success(
        api_client.create_tenant_notice(
            create_tenant_notice_payload(
                case["id"], notice_type="RENEWAL_INTENT", effective_date="2027-06-01"
            ),
            owner_headers,
        ),
        expected_status=201,
    )
    assert notice["status"] == "ISSUED", (
        f"there is no pre-issue state for a notice, got {notice['status']}"
    )
    assert notice["issued_date"] == "2026-12-01"
    assert notice["lead_days"] == 182, (
        f"2026-12-01 to 2027-06-01 is 182 whole days, got {notice['lead_days']}"
    )
    assert notice["required_lead_days"] == 120
    assert notice["rescind_reason"] is None


def test_triggers_not_declared_from_the_current_state_are_refused_without_side_effects():
    """Payment is declared only on a `SUBMITTED` voucher, a decision only on a `SUBMITTED`
    claim, and the adjustment election "is available only while the rent track sits at
    `OPTION_SELECTED`" — each undeclared edge is `ERR_TRANSITION_NOT_ALLOWED` and moves
    nothing.

    Design: Corner/state_machines/triggers_not_declared_from_the_current_state_are_refused_without_side_effects
    """
    ctx = setup_portfolio()
    contract_id = ctx["contract"]["id"]
    owner_headers = ctx["owner_headers"]
    setup_certified_household(ctx["property"]["id"], owner_headers, REFERENCE_HOUSEHOLD_ONE)
    set_clock_date("2026-12-01")
    case = validate_success(
        api_client.create_renewal_case(
            create_renewal_case_payload(contract_id), owner_headers
        ),
        expected_status=201,
    )
    voucher = create_voucher(contract_id, owner_headers, "2026-07")
    assert voucher["requested_hap_cents"] == 84500
    claim = create_direct_ledger_claim(
        contract_id, owner_headers, "UNPAID_RENT", "101", "2026-07", 90000, 20000
    )

    validate_error(
        api_client.pay_voucher_submission(voucher["id"], CA_APPROVER_HEADERS),
        ApiErrorId.ERR_TRANSITION_NOT_ALLOWED.value,
        expected_status=409,
    )
    validate_error(
        api_client.decide_special_claim(
            claim["id"], decide_claim_payload("APPROVE"), CA_HEADERS
        ),
        ApiErrorId.ERR_TRANSITION_NOT_ALLOWED.value,
        expected_status=409,
    )
    validate_error(
        api_client.elect_adjustment(
            case["id"], elect_adjustment_payload("OCAF"), owner_headers
        ),
        ApiErrorId.ERR_TRANSITION_NOT_ALLOWED.value,
        expected_status=409,
    )

    voucher_after = validate_success(
        api_client.get_voucher_submission(voucher["id"], CA_HEADERS)
    )
    assert voucher_after["state"] == "DRAFT"
    assert voucher_after["paid_amount_cents"] is None

    claim_after = validate_success(api_client.get_special_claim(claim["id"], CA_HEADERS))
    assert claim_after["state"] == "DRAFT"
    assert claim_after["decision_reason"] is None

    case_after = validate_success(api_client.get_renewal_case(case["id"], CA_HEADERS))
    assert case_after["rent_track_status"] == "TERMS_PENDING"
    assert case_after["adjustment_method"] is None
    assert case_after["ocaf_rent_per_unit_cents"] is None
    assert case_after["budget_rent_per_unit_cents"] is None

    contract_after = validate_success(api_client.get_hap_contract(contract_id, CA_HEADERS))
    assert contract_after["hap_ledger_balance_cents"] == 30000000
    assert contract_after["paid_hap_total_cents"] == 0


def test_repeating_an_already_applied_trigger_is_rejected_rather_than_silently_ignored():
    """Submission is declared "from `DRAFT` to `SUBMITTED`, or from `CHALLENGED` back to
    `SUBMITTED`" and payment only from `SUBMITTED`, so the second submit and the second pay
    are refused and the ledger is debited exactly once.

    Design: Corner/state_machines/repeating_an_already_applied_trigger_is_rejected_rather_than_silently_ignored
    """
    ctx = setup_portfolio()
    contract_id = ctx["contract"]["id"]
    owner_headers = ctx["owner_headers"]
    setup_reference_households(ctx["property"]["id"], owner_headers, "2026-07-01")
    ctx = setup_adjustment_elected(
        renewal_option="OPTION_2_OCAF", adjustment_method="OCAF", base=ctx
    )

    study = validate_success(
        api_client.create_study(create_study_payload(ctx["case"]["id"]), owner_headers),
        expected_status=201,
    )
    validate_success(
        api_client.create_comparable(
            create_comparable_payload(study["id"], **ALDER_COURT), owner_headers
        ),
        expected_status=201,
    )
    submitted = validate_success(api_client.submit_study(study["id"], owner_headers))
    assert submitted["state"] == "SUBMITTED"
    assert submitted["submitted_on_date"] == "2026-12-01"
    assert submitted["estimated_market_rent_cents"] == 131200, (
        "125000 + 4650 + 1500 rounds to the whole dollar 131200, got "
        f"{submitted['estimated_market_rent_cents']}"
    )

    voucher = create_voucher(contract_id, owner_headers, "2026-07")
    validate_success(api_client.submit_voucher_submission(voucher["id"], owner_headers))
    paid = validate_success(
        api_client.pay_voucher_submission(voucher["id"], CA_APPROVER_HEADERS)
    )
    assert paid["paid_amount_cents"] == 211500, (
        f"84500 plus 127000 for the two households, got {paid['paid_amount_cents']}"
    )
    assert paid["paid_on_date"] == "2026-12-01"

    validate_error(
        api_client.submit_study(study["id"], owner_headers),
        ApiErrorId.ERR_TRANSITION_NOT_ALLOWED.value,
        expected_status=409,
    )
    validate_error(
        api_client.pay_voucher_submission(voucher["id"], CA_APPROVER_HEADERS),
        ApiErrorId.ERR_TRANSITION_NOT_ALLOWED.value,
        expected_status=409,
    )

    study_after = validate_success(api_client.get_study(study["id"], CA_HEADERS))
    assert study_after["state"] == "SUBMITTED"
    assert study_after["submitted_on_date"] == "2026-12-01"
    assert study_after["estimated_market_rent_cents"] == 131200

    voucher_after = validate_success(
        api_client.get_voucher_submission(voucher["id"], CA_HEADERS)
    )
    assert voucher_after["paid_amount_cents"] == 211500, "a single debit, not two"

    contract_after = validate_success(api_client.get_hap_contract(contract_id, CA_HEADERS))
    assert contract_after["paid_hap_total_cents"] == 211500
    assert contract_after["hap_ledger_balance_cents"] == 29788500, (
        f"30000000 less one 211500 debit, got {contract_after['hap_ledger_balance_cents']}"
    )


def test_terminal_states_refuse_every_further_trigger_on_case_voucher_and_claim():
    """`EXECUTED` is terminal on the rent track, `REVERSED` on a voucher and `DENIED` on a
    claim: "Payment of an `APPROVED` claim" and payment of a submitted voucher have no edge
    out of those states.

    Design: Corner/state_machines/terminal_states_refuse_every_further_trigger_on_case_voucher_and_claim
    """
    ctx = setup_portfolio()
    contract_id = ctx["contract"]["id"]
    owner_headers = ctx["owner_headers"]
    setup_certified_household(ctx["property"]["id"], owner_headers, REFERENCE_HOUSEHOLD_ONE)
    ctx = setup_adjustment_elected(
        renewal_option="OPTION_2_OCAF", adjustment_method="OCAF", base=ctx
    )
    case_id = ctx["case"]["id"]
    assert ctx["case"]["ocaf_rent_per_unit_cents"] == 120752

    validate_success(
        api_client.create_tenant_notice(
            create_tenant_notice_payload(
                case_id, notice_type="RENEWAL_INTENT", effective_date="2027-06-01"
            ),
            owner_headers,
        ),
        expected_status=201,
    )
    approved = validate_success(api_client.approve_rents(case_id, CA_APPROVER_HEADERS))
    assert approved["approved_rent_per_unit_cents"] == 120752
    assert approved["rent_track_status"] == "RENTS_APPROVED"

    executed = validate_success(
        api_client.execute_renewal(
            case_id,
            execute_renewal_payload(current_contract_version(contract_id)),
            CA_APPROVER_HEADERS,
        )
    )
    assert executed["rent_track_status"] == "EXECUTED"

    contract = validate_success(api_client.get_hap_contract(contract_id, CA_HEADERS))
    assert contract["lifecycle_status"] == "RENEWED"
    assert contract["renewed_rent_per_unit_cents"] == 120752
    assert contract["contract_rent_per_unit_cents"] == 120752
    assert contract["renewed_expiration_date"] == "2028-12-31", (
        f"2027-12-31 advanced by 12 whole months, got {contract['renewed_expiration_date']}"
    )
    assert contract["renewed_option"] == "OPTION_2_OCAF"

    voucher = create_voucher(contract_id, owner_headers, "2026-07")
    assert voucher["requested_hap_cents"] == 84500, (
        "the certification snapshot, not the renewed rent, drives the closed month, got "
        f"{voucher['requested_hap_cents']}"
    )
    validate_success(api_client.submit_voucher_submission(voucher["id"], owner_headers))
    validate_success(api_client.pay_voucher_submission(voucher["id"], CA_APPROVER_HEADERS))
    reversed_voucher = validate_success(
        api_client.reverse_voucher_submission(
            voucher["id"],
            reverse_voucher_payload("Paid against the wrong contract"),
            CA_APPROVER_HEADERS,
        )
    )
    assert reversed_voucher["state"] == "REVERSED"

    claim = create_direct_ledger_claim(
        contract_id, owner_headers, "UNPAID_RENT", "101", "2026-07", 90000, 20000
    )
    submitted_claim = validate_success(
        api_client.submit_special_claim(claim["id"], owner_headers)
    )
    assert submitted_claim["computed_amount_cents"] == 70000, (
        f"90000 claimed less the 20000 deposit, got {submitted_claim['computed_amount_cents']}"
    )
    denied = validate_success(
        api_client.decide_special_claim(
            claim["id"],
            decide_claim_payload("DENY", "Tenant ledger does not support the arrears"),
            CA_HEADERS,
        )
    )
    assert denied["state"] == "DENIED"
    assert denied["decision_reason"] == "Tenant ledger does not support the arrears"

    fresh_version = current_contract_version(contract_id)
    validate_error(
        api_client.approve_rents(case_id, CA_APPROVER_HEADERS),
        ApiErrorId.ERR_TRANSITION_NOT_ALLOWED.value,
        expected_status=409,
    )
    validate_error(
        api_client.execute_renewal(
            case_id, execute_renewal_payload(fresh_version), CA_APPROVER_HEADERS
        ),
        ApiErrorId.ERR_TRANSITION_NOT_ALLOWED.value,
        expected_status=409,
    )
    validate_error(
        api_client.pay_voucher_submission(voucher["id"], CA_APPROVER_HEADERS),
        ApiErrorId.ERR_TRANSITION_NOT_ALLOWED.value,
        expected_status=409,
    )
    validate_error(
        api_client.pay_special_claim(claim["id"], CA_APPROVER_HEADERS),
        ApiErrorId.ERR_TRANSITION_NOT_ALLOWED.value,
        expected_status=409,
    )

    case_after = validate_success(api_client.get_renewal_case(case_id, CA_HEADERS))
    assert case_after["rent_track_status"] == "EXECUTED"
    voucher_final = validate_success(
        api_client.get_voucher_submission(voucher["id"], CA_HEADERS)
    )
    assert voucher_final["state"] == "REVERSED"
    claim_final = validate_success(api_client.get_special_claim(claim["id"], CA_HEADERS))
    assert claim_final["state"] == "DENIED"
    contract_final = validate_success(api_client.get_hap_contract(contract_id, CA_HEADERS))
    assert contract_final["hap_ledger_balance_cents"] == 30000000, (
        "the reversal restored the ledger and no refused call touched it, got "
        f"{contract_final['hap_ledger_balance_cents']}"
    )


def test_a_study_with_every_comparable_struck_cannot_be_resubmitted():
    """"Either way it requires at least one comparable of the study to be in `status`
    `ACCEPTED`; a study whose every comparable has been struck, or which never had one, is
    refused with `ERR_NO_ELIGIBLE_COMPARABLES` (HTTP 422)".

    Design: Corner/state_machines/a_study_with_every_comparable_struck_cannot_be_resubmitted
    """
    ctx = setup_adjustment_elected(
        renewal_option="OPTION_2_OCAF", adjustment_method="OCAF"
    )
    case_id = ctx["case"]["id"]
    owner_headers = ctx["owner_headers"]

    empty_study = validate_success(
        api_client.create_study(create_study_payload(case_id), owner_headers),
        expected_status=201,
    )
    assert empty_study["accepted_comparable_count"] == 0

    populated = validate_success(
        api_client.create_study(
            create_study_payload(case_id, appraiser_name="Ives Valuation LLC"), owner_headers
        ),
        expected_status=201,
    )
    comparable = validate_success(
        api_client.create_comparable(
            create_comparable_payload(populated["id"], **ALDER_COURT), owner_headers
        ),
        expected_status=201,
    )
    assert comparable["status"] == "ACCEPTED"
    assert comparable["adjusted_rent_cents"] == 131200

    submitted = validate_success(api_client.submit_study(populated["id"], owner_headers))
    assert submitted["estimated_market_rent_cents"] == 131200

    challenged = validate_success(
        api_client.challenge_study(
            populated["id"],
            challenge_study_payload(
                "Alder Court is a different submarket", [comparable["id"]]
            ),
            CA_HEADERS,
        )
    )
    assert challenged["state"] == "CHALLENGED"
    assert challenged["challenge_round"] == 1
    assert challenged["accepted_comparable_count"] == 0
    assert challenged["estimated_market_rent_cents"] is None, (
        "with no accepted comparable the weighted mean is undefined, got "
        f"{challenged['estimated_market_rent_cents']}"
    )

    validate_error(
        api_client.submit_study(empty_study["id"], owner_headers),
        ApiErrorId.ERR_NO_ELIGIBLE_COMPARABLES.value,
        expected_status=422,
    )
    validate_error(
        api_client.submit_study(populated["id"], owner_headers),
        ApiErrorId.ERR_NO_ELIGIBLE_COMPARABLES.value,
        expected_status=422,
    )

    assert validate_success(api_client.get_study(empty_study["id"], CA_HEADERS))["state"] == (
        "DRAFT"
    )
    assert validate_success(api_client.get_study(populated["id"], CA_HEADERS))["state"] == (
        "CHALLENGED"
    )
    comparables, _ = validate_paginated(
        api_client.list_study_comparables(populated["id"], CA_HEADERS)
    )
    assert [row["status"] for row in comparables] == ["STRUCK"]
    case_after = validate_success(api_client.get_renewal_case(case_id, CA_HEADERS))
    assert case_after["comparable_market_rent_cents"] is None, (
        "the challenge wrote the recomputed estimate onto the case, got "
        f"{case_after['comparable_market_rent_cents']}"
    )


def test_move_out_releases_the_unit_and_prorates_that_household_in_the_closing_voucher():
    """"`released_unit_count` always increments by 1, and the offsetting decrement lands on
    `enhanced_voucher_unit_count` when the household was `EV_ISSUED` and on
    `units_under_hap_count` otherwise", while "the household's certifications are left
    completely untouched" so the closing period still prorates.

    Design: Corner/state_machines/move_out_releases_the_unit_and_prorates_that_household_in_the_closing_voucher
    """
    ctx = setup_portfolio()
    contract_id = ctx["contract"]["id"]
    owner_headers = ctx["owner_headers"]
    households = setup_reference_households(
        ctx["property"]["id"], owner_headers, "2026-07-01"
    )
    second = households["household_two"]
    second_cert = households["certification_two"]

    moved_out = validate_success(
        api_client.move_out_tenant_household(
            second["id"], move_out_payload("2026-07-16"), owner_headers
        )
    )
    assert moved_out["status"] == "MOVED_OUT"
    assert moved_out["move_out_date"] == "2026-07-16"
    assert moved_out["current_hap_cents"] == 127000

    prop_after = validate_success(
        api_client.get_property(ctx["property"]["id"], owner_headers)
    )
    assert prop_after["units_under_hap_count"] == 19
    assert prop_after["enhanced_voucher_unit_count"] == 0
    assert prop_after["released_unit_count"] == 1
    assert_unit_invariant(prop_after)

    voucher = create_voucher(contract_id, owner_headers, "2026-07")
    assert voucher["included_certification_count"] == 2
    assert voucher["requested_hap_cents"] == 145952, (
        "84500 for the full-month household plus round_half_up(127000 * 15 / 31) = 61452, "
        f"got {voucher['requested_hap_cents']}"
    )

    cert_after = validate_success(
        api_client.get_tenant_certification(second_cert["id"], owner_headers)
    )
    assert cert_after["status"] == "ACTIVE", (
        f"move-out leaves certifications untouched, got {cert_after['status']}"
    )
    assert cert_after["hap_cents"] == 127000
    first_after = validate_success(
        api_client.get_tenant_household(households["household_one"]["id"], owner_headers)
    )
    assert first_after["status"] == "ACTIVE"


def test_a_rejected_utility_allowance_analysis_can_be_resubmitted_to_approval():
    """"a rejected analysis returns to `SUBMITTED` on resubmission rather than to `DRAFT`",
    and submission "requires that no **other** analysis on the same property is in state
    `SUBMITTED` or `APPROVED`; a second in-flight analysis is refused with
    `ERR_UA_ANALYSIS_IN_FLIGHT` (HTTP 409)".

    Design: Corner/state_machines/a_rejected_utility_allowance_analysis_can_be_resubmitted_and_the_loop_terminates_in_approval
    """
    ctx = setup_portfolio()
    prop_id = ctx["property"]["id"]
    owner_headers = ctx["owner_headers"]

    first = create_ua_analysis(
        prop_id, owner_headers, effective_date="2026-09-01", utility_rate_change_pct=0.09
    )
    second = create_ua_analysis(
        prop_id, owner_headers, effective_date="2026-10-01", utility_rate_change_pct=0.05
    )
    assert first["proposed_allowance_cents"] == 12535, (
        f"round_half_up(11500 * 1.09) is 12535, got {first['proposed_allowance_cents']}"
    )
    assert second["proposed_allowance_cents"] == 12075

    submitted = validate_success(
        api_client.submit_utility_allowance_analysis(first["id"], owner_headers)
    )
    assert submitted["state"] == "SUBMITTED"

    validate_error(
        api_client.submit_utility_allowance_analysis(second["id"], owner_headers),
        ApiErrorId.ERR_UA_ANALYSIS_IN_FLIGHT.value,
        expected_status=409,
    )
    assert validate_success(
        api_client.get_utility_allowance_analysis(second["id"], CA_HEADERS)
    )["state"] == "DRAFT"

    states = []
    for reason in ("Attach the utility company rate schedule", "Still missing the rate schedule"):
        rejected = validate_success(
            api_client.decide_utility_allowance_analysis(
                first["id"], decide_utility_allowance_payload("REJECT", reason), CA_HEADERS
            )
        )
        states.append(rejected["state"])
        resubmitted = validate_success(
            api_client.submit_utility_allowance_analysis(first["id"], owner_headers)
        )
        states.append(resubmitted["state"])
        assert resubmitted["proposed_allowance_cents"] == 12535, (
            "resubmission never re-derives the computed fields, got "
            f"{resubmitted['proposed_allowance_cents']}"
        )
    assert states == ["REJECTED", "SUBMITTED", "REJECTED", "SUBMITTED"], (
        f"two full loops with no round limit, got {states}"
    )

    approved = validate_success(
        api_client.decide_utility_allowance_analysis(
            first["id"], decide_utility_allowance_payload("ACCEPT"), CA_HEADERS
        )
    )
    assert approved["state"] == "APPROVED"
    assert approved["approver_user_id"] == TEST_USERS["contract_administrator_user_id"]
    assert approved["change_pct"] == 0.09

    prop_after = validate_success(api_client.get_property(prop_id, owner_headers))
    assert prop_after["current_utility_allowance_cents"] == 11500, (
        "an APPROVED analysis moves nothing until it is applied, got "
        f"{prop_after['current_utility_allowance_cents']}"
    )
