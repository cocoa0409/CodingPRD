"""The four-hop opt-out cascade, the minted enhanced vouchers, the finalization guard pair
and the compensations that unwind both the cascade and the unit ledger."""
from test_helpers import (
    ApiErrorId,
    REFERENCE_HOUSEHOLD_ONE,
    REFERENCE_HOUSEHOLD_TWO,
    TEST_USERS,
    api_client,
    assert_unit_invariant,
    certify_household,
    create_household,
    create_renewal_case_payload,
    issue_enhanced_voucher,
    issue_opt_out_notice,
    move_out_household,
    rescind_enhanced_voucher,
    rescind_notice,
    rescind_payload,
    set_clock_date,
    setup_case_with_households,
    setup_opt_out_noticed_case,
    setup_portfolio,
    validate_error,
    validate_paginated,
    validate_success,
)

CA_HEADERS = TEST_USERS["contract_administrator_headers"]
CA_APPROVER_HEADERS = TEST_USERS["contract_administrator_approver_headers"]
PHA_HEADERS = TEST_USERS["pha_administrator_headers"]
PHA_USER_ID = TEST_USERS["pha_administrator_user_id"]

HOUSEHOLD_UNCERTIFIED = {
    "unit_number": "103",
    "household_name": "Castellanos",
    "annual_adjusted_income_cents": 2400000,
    "annual_gross_income_cents": 2400000,
    "family_size": 4,
}
HOUSEHOLD_DEPARTING = {
    "unit_number": "104",
    "household_name": "Dunmore",
    "annual_adjusted_income_cents": 1200000,
    "annual_gross_income_cents": 1200000,
    "family_size": 2,
}
HOUSEHOLD_AT_THE_PAYMENT_STANDARD = {
    "unit_number": "101",
    "household_name": "Whitfield",
    "annual_adjusted_income_cents": 5500001,
    "annual_gross_income_cents": 5500001,
    "family_size": 2,
}


def test_recording_the_opt_out_fans_out_across_four_kinds_of_entity():
    """"The notice track moves `NOTICES_PENDING` → `OPT_OUT_NOTICED` and `opt_out_notice_id`
    is confirmed as that notice's identifier. Caused by that, the contract's
    `lifecycle_status` moves `RENEWAL_PENDING` → `OPT_OUT_PENDING` ... every household of the
    property whose `status` is `ACTIVE` moves `ACTIVE` → `OPT_OUT_NOTICED`, has `ev_eligible`
    set to true ... one enhanced voucher row in state `PENDING` is created for each household
    that just became eligible".

    Design: Difficulty/transitive_cascade/record_opt_out_propagates_through_contract_households_into_minted_enhanced_vouchers
    """
    ctx = setup_case_with_households()
    case_id = ctx["case"]["id"]
    contract_id = ctx["contract"]["id"]
    prop_id = ctx["property"]["id"]
    assert ctx["certification_one"]["ttp_cents"] == 45000
    assert ctx["certification_two"]["ttp_cents"] == 2500
    version_before = {
        "case": ctx["case"]["version"],
        "one": ctx["household_one"]["version"],
        "two": ctx["household_two"]["version"],
    }

    validate_error(
        api_client.record_opt_out(case_id, ctx["owner_headers"]),
        ApiErrorId.ERR_OPT_OUT_NOTICE_MISSING.value,
        expected_status=422,
    )
    unarmed = validate_success(api_client.get_renewal_case(case_id, CA_HEADERS))
    assert unarmed["notice_track_status"] == "NOTICES_PENDING"
    assert unarmed["opt_out_notice_id"] is None
    assert unarmed["version"] == version_before["case"], (
        f"the refused cascade mutated nothing, got version {unarmed['version']}"
    )
    assert validate_success(api_client.get_hap_contract(contract_id, CA_HEADERS))[
        "lifecycle_status"
    ] == "RENEWAL_PENDING"
    _, empty_meta = validate_paginated(
        api_client.list_case_enhanced_vouchers(case_id, PHA_HEADERS)
    )
    assert empty_meta["total_count"] == 0, (
        f"no voucher exists before the opt-out is recorded, got {empty_meta['total_count']}"
    )

    notice = issue_opt_out_notice(case_id, ctx["owner_headers"], "2027-12-31")
    assert notice["lead_days"] == 395, (
        f"2026-12-01 to 2027-12-31 is 395 whole days, got {notice['lead_days']}"
    )
    assert notice["required_lead_days"] == 365
    armed = validate_success(api_client.get_renewal_case(case_id, CA_HEADERS))
    assert armed["opt_out_notice_id"] == notice["id"]
    assert armed["notice_track_status"] == "NOTICES_PENDING", (
        "the one-year notice merely arms the opt-out, got "
        f"{armed['notice_track_status']}"
    )

    recorded = validate_success(api_client.record_opt_out(case_id, ctx["owner_headers"]))
    assert recorded["notice_track_status"] == "OPT_OUT_NOTICED"
    assert recorded["opt_out_notice_id"] == notice["id"]

    contract_after = validate_success(api_client.get_hap_contract(contract_id, CA_HEADERS))
    assert contract_after["lifecycle_status"] == "OPT_OUT_PENDING", (
        "hop two reached the contract, got " f"{contract_after['lifecycle_status']}"
    )

    for key, household in (
        ("one", ctx["household_one"]),
        ("two", ctx["household_two"]),
    ):
        row = validate_success(
            api_client.get_tenant_household(household["id"], CA_HEADERS)
        )
        assert row["status"] == "OPT_OUT_NOTICED", (
            f"hop three reached household {key}, got {row['status']}"
        )
        assert row["ev_eligible"] is True
        assert row["version"] == version_before[key] + 1

    vouchers, meta = validate_paginated(
        api_client.list_case_enhanced_vouchers(case_id, PHA_HEADERS)
    )
    assert meta["total_count"] == 2, (
        f"hop four created one row per newly eligible household, got {meta['total_count']}"
    )
    assert [v["state"] for v in vouchers] == ["PENDING", "PENDING"]
    assert [v["payment_standard_cents"] for v in vouchers] == [137500, 137500], (
        "the greater of the null comparable market rent and the 126000 published FMR plus "
        f"the 11500 allowance is 137500, got {[v['payment_standard_cents'] for v in vouchers]}"
    )
    assert [v["ttp_snapshot_cents"] for v in vouchers] == [45000, 2500]
    assert vouchers[0]["entitlement_cents"] == 92500, (
        f"137500 less the 45000 snapshot payment is 92500, got {vouchers[0]['entitlement_cents']}"
    )
    assert vouchers[1]["entitlement_cents"] == 135000, (
        "137500 less the 2500 minimum rent is 135000, got "
        f"{vouchers[1]['entitlement_cents']}"
    )
    assert [v["tenant_id"] for v in vouchers] == [
        ctx["household_one"]["id"],
        ctx["household_two"]["id"],
    ], "the rows are minted in household created_at ascending order"

    prop_after = validate_success(api_client.get_property(prop_id, CA_HEADERS))
    assert prop_after["units_under_hap_count"] == 20, (
        "no unit counter moves at this stage, got "
        f"{prop_after['units_under_hap_count']}"
    )
    assert prop_after["enhanced_voucher_unit_count"] == 0
    assert prop_after["released_unit_count"] == 0
    assert_unit_invariant(prop_after)


def test_each_minted_voucher_is_priced_from_its_own_household_snapshot():
    """"`ttp_snapshot_cents` is the `ttp_cents` of that household's certification whose
    `status` is `ACTIVE`, or zero when the household has never been certified.
    `entitlement_cents` is the payment standard less the greater of the snapshot total tenant
    payment and the 2,500-cent minimum rent, floored at zero".

    Design: Difficulty/transitive_cascade/record_opt_out_propagates_through_contract_households_into_minted_enhanced_vouchers
    """
    ctx = setup_portfolio()
    prop_id = ctx["property"]["id"]
    owner_headers = ctx["owner_headers"]

    one = create_household(prop_id, owner_headers, **REFERENCE_HOUSEHOLD_ONE)
    two = create_household(prop_id, owner_headers, **REFERENCE_HOUSEHOLD_TWO)
    never_certified = create_household(prop_id, owner_headers, **HOUSEHOLD_UNCERTIFIED)
    departing = create_household(prop_id, owner_headers, **HOUSEHOLD_DEPARTING)
    certify_household(one["id"], owner_headers, "2026-07-01")
    certify_household(two["id"], owner_headers, "2026-07-01")
    certify_household(departing["id"], owner_headers, "2026-07-01")

    set_clock_date("2026-12-01")
    gone = move_out_household(departing["id"], owner_headers, "2026-12-01")
    assert gone["status"] == "MOVED_OUT"

    case = validate_success(
        api_client.create_renewal_case(
            create_renewal_case_payload(ctx["contract"]["id"]), owner_headers
        ),
        expected_status=201,
    )
    issue_opt_out_notice(case["id"], owner_headers, "2027-12-31")
    validate_success(api_client.record_opt_out(case["id"], owner_headers))

    vouchers, meta = validate_paginated(
        api_client.list_case_enhanced_vouchers(case["id"], PHA_HEADERS)
    )
    assert meta["total_count"] == 3, (
        "only the three households that were ACTIVE became eligible, got "
        f"{meta['total_count']}"
    )
    assert [v["tenant_id"] for v in vouchers] == [
        one["id"],
        two["id"],
        never_certified["id"],
    ]
    assert [v["ttp_snapshot_cents"] for v in vouchers] == [45000, 2500, 0], (
        "the never-certified household snapshots zero rather than inheriting a sibling's "
        f"figure, got {[v['ttp_snapshot_cents'] for v in vouchers]}"
    )
    assert [v["entitlement_cents"] for v in vouchers] == [92500, 135000, 135000], (
        "the 2500 minimum rent floors the deduction for both the low-payment and the "
        f"uncertified household, got {[v['entitlement_cents'] for v in vouchers]}"
    )
    assert {v["payment_standard_cents"] for v in vouchers} == {137500}

    assert validate_success(
        api_client.get_tenant_household(departing["id"], CA_HEADERS)
    )["status"] == "MOVED_OUT", "a departed household is not swept into the cascade"
    assert validate_success(
        api_client.get_tenant_household(never_certified["id"], CA_HEADERS)
    )["ev_eligible"] is True

    prop_after = validate_success(api_client.get_property(prop_id, CA_HEADERS))
    assert prop_after["units_under_hap_count"] == 19, (
        "only the earlier move-out touched the ledger, got "
        f"{prop_after['units_under_hap_count']}"
    )
    assert prop_after["enhanced_voucher_unit_count"] == 0
    assert prop_after["released_unit_count"] == 1
    assert_unit_invariant(prop_after)


def test_the_notice_period_check_outranks_the_unresolved_voucher_check():
    """"The clock date must have reached or passed the `effective_date` of the notice named by
    `opt_out_notice_id` ... otherwise `ERR_OPT_OUT_NOTICE_PERIOD_INCOMPLETE` (HTTP 422). And
    every household of the property still in `status` `OPT_OUT_NOTICED` must hold an enhanced
    voucher in state `ISSUED`, otherwise `ERR_TENANT_VOUCHER_UNRESOLVED` (HTTP 422). The
    temporal check is evaluated first".

    Design: Difficulty/priority_pair_validation_conflict/finalize_opt_out_notice_period_outranks_the_unresolved_voucher_check
    """
    ctx = setup_opt_out_noticed_case()
    case_id = ctx["case"]["id"]
    contract_id = ctx["contract"]["id"]
    assert [v["state"] for v in ctx["enhanced_vouchers"]] == ["PENDING", "PENDING"], (
        "both rules are violated at once: the period has not elapsed and no voucher is "
        f"issued, got {[v['state'] for v in ctx['enhanced_vouchers']]}"
    )

    validate_error(
        api_client.finalize_opt_out(case_id, CA_APPROVER_HEADERS),
        ApiErrorId.ERR_OPT_OUT_NOTICE_PERIOD_INCOMPLETE.value,
        expected_status=422,
    )
    after_temporal = validate_success(api_client.get_renewal_case(case_id, CA_HEADERS))
    assert after_temporal["notice_track_status"] == "OPT_OUT_NOTICED"
    assert validate_success(api_client.get_hap_contract(contract_id, CA_HEADERS))[
        "lifecycle_status"
    ] == "OPT_OUT_PENDING"

    set_clock_date("2027-12-31")
    validate_error(
        api_client.finalize_opt_out(case_id, CA_APPROVER_HEADERS),
        ApiErrorId.ERR_TENANT_VOUCHER_UNRESOLVED.value,
        expected_status=422,
    )
    after_referential = validate_success(api_client.get_renewal_case(case_id, CA_HEADERS))
    assert after_referential["notice_track_status"] == "OPT_OUT_NOTICED", (
        "advancing the clock exposed the second violation without moving the track, got "
        f"{after_referential['notice_track_status']}"
    )
    contract_after = validate_success(api_client.get_hap_contract(contract_id, CA_HEADERS))
    assert contract_after["lifecycle_status"] == "OPT_OUT_PENDING"
    assert contract_after["hap_ledger_balance_cents"] == 30000000, (
        "neither refusal zeroed the ledger, got "
        f"{contract_after['hap_ledger_balance_cents']}"
    )
    prop_after = validate_success(api_client.get_property(ctx["property"]["id"], CA_HEADERS))
    assert prop_after["units_under_hap_count"] == 20
    assert prop_after["enhanced_voucher_unit_count"] == 0
    assert prop_after["released_unit_count"] == 0
    assert_unit_invariant(prop_after)


def test_clearing_both_conditions_finalizes_the_opt_out_and_closes_the_unit_ledger():
    """"Finalization moves the notice track `OPT_OUT_NOTICED` → the terminal
    `OPT_OUT_FINALIZED`, moves the contract's `lifecycle_status` `OPT_OUT_PENDING` → the
    terminal `EXPIRED_OPT_OUT` with `hap_ledger_balance_cents` zeroed ... whatever remained in
    `units_under_hap_count` is added to `released_unit_count`, `units_under_hap_count` is set
    to 0".

    Design: Difficulty/priority_pair_validation_conflict/finalize_opt_out_notice_period_outranks_the_unresolved_voucher_check
    """
    ctx = setup_opt_out_noticed_case()
    case_id = ctx["case"]["id"]
    contract_id = ctx["contract"]["id"]
    prop_id = ctx["property"]["id"]
    ev_one, ev_two = ctx["enhanced_vouchers"]

    set_clock_date("2027-12-31")
    validate_error(
        api_client.finalize_opt_out(case_id, CA_APPROVER_HEADERS),
        ApiErrorId.ERR_TENANT_VOUCHER_UNRESOLVED.value,
        expected_status=422,
    )

    issued_one = issue_enhanced_voucher(ev_one["id"])
    assert issued_one["state"] == "ISSUED"
    validate_error(
        api_client.finalize_opt_out(case_id, CA_APPROVER_HEADERS),
        ApiErrorId.ERR_TENANT_VOUCHER_UNRESOLVED.value,
        expected_status=422,
    )
    issued_two = issue_enhanced_voucher(ev_two["id"])
    assert issued_two["state"] == "ISSUED"

    midway = validate_success(api_client.get_property(prop_id, CA_HEADERS))
    assert midway["units_under_hap_count"] == 18, (
        "each issuance moved one unit out from under the contract, got "
        f"{midway['units_under_hap_count']}"
    )
    assert midway["enhanced_voucher_unit_count"] == 2
    assert midway["released_unit_count"] == 0

    finalized = validate_success(
        api_client.finalize_opt_out(case_id, CA_APPROVER_HEADERS)
    )
    assert finalized["notice_track_status"] == "OPT_OUT_FINALIZED", (
        "every household is resolved and the period has elapsed, got "
        f"{finalized['notice_track_status']}"
    )

    contract_after = validate_success(api_client.get_hap_contract(contract_id, CA_HEADERS))
    assert contract_after["lifecycle_status"] == "EXPIRED_OPT_OUT"
    assert contract_after["hap_ledger_balance_cents"] == 0, (
        f"finalization zeroed the ledger, got {contract_after['hap_ledger_balance_cents']}"
    )

    prop_after = validate_success(api_client.get_property(prop_id, CA_HEADERS))
    assert prop_after["units_under_hap_count"] == 0
    assert prop_after["enhanced_voucher_unit_count"] == 2, (
        "the two enhanced-voucher units are not released, got "
        f"{prop_after['enhanced_voucher_unit_count']}"
    )
    assert prop_after["released_unit_count"] == 18, (
        "the 18 units still under HAP were released wholesale, got "
        f"{prop_after['released_unit_count']}"
    )
    assert_unit_invariant(prop_after)
    assert validate_success(api_client.get_tenant_notice(ctx["notice"]["id"], CA_HEADERS))[
        "status"
    ] == "ISSUED", "finalization does not disturb the notice row"


def test_an_issued_enhanced_voucher_freezes_the_notice_the_owner_wants_to_rescind():
    """"This unwinding is only available while nothing has been issued: if even one enhanced
    voucher on the case is already in state `ISSUED`, the rescission of a one-year opt-out
    notice is refused with `ERR_ENHANCED_VOUCHER_ISSUED_BLOCKS_RESCIND` (HTTP 409), and the
    agency must rescind the vouchers first".

    Design: Difficulty/cross_entity_state_dependency/opt_out_notice_rescission_is_blocked_by_an_issued_enhanced_voucher
    """
    ctx = setup_opt_out_noticed_case()
    case_id = ctx["case"]["id"]
    notice_id = ctx["notice"]["id"]
    ev_one, ev_two = ctx["enhanced_vouchers"]

    issued = issue_enhanced_voucher(ev_one["id"])
    assert issued["state"] == "ISSUED"
    assert issued["entitlement_cents"] == 92500
    assert validate_success(
        api_client.get_tenant_household(ctx["household_one"]["id"], CA_HEADERS)
    )["status"] == "EV_ISSUED"

    validate_error(
        api_client.rescind_tenant_notice(
            notice_id,
            rescind_payload("Owner reconsidered and will renew"),
            ctx["owner_headers"],
        ),
        ApiErrorId.ERR_ENHANCED_VOUCHER_ISSUED_BLOCKS_RESCIND.value,
        expected_status=409,
    )

    assert validate_success(api_client.get_tenant_notice(notice_id, CA_HEADERS))[
        "status"
    ] == "ISSUED", "the blocked rescission left the notice standing"
    frozen_case = validate_success(api_client.get_renewal_case(case_id, CA_HEADERS))
    assert frozen_case["notice_track_status"] == "OPT_OUT_NOTICED"
    assert frozen_case["opt_out_notice_id"] == notice_id
    assert validate_success(api_client.get_hap_contract(ctx["contract"]["id"], CA_HEADERS))[
        "lifecycle_status"
    ] == "OPT_OUT_PENDING"
    assert validate_success(api_client.get_enhanced_voucher(ev_two["id"], PHA_HEADERS))[
        "state"
    ] == "PENDING", "the sibling voucher was not swept by the refused rescission"
    assert validate_success(
        api_client.get_tenant_household(ctx["household_two"]["id"], CA_HEADERS)
    )["status"] == "OPT_OUT_NOTICED"

    prop_after = validate_success(api_client.get_property(ctx["property"]["id"], CA_HEADERS))
    assert prop_after["units_under_hap_count"] == 19, (
        "only the issuance moved the ledger, got " f"{prop_after['units_under_hap_count']}"
    )
    assert prop_after["enhanced_voucher_unit_count"] == 1
    assert prop_after["released_unit_count"] == 0
    assert_unit_invariant(prop_after)


def test_the_agency_clears_the_blocker_and_the_notice_rescission_unwinds_the_cascade():
    """"Rescinding the notice that is the case's `opt_out_notice_id`, while the notice track is
    `OPT_OUT_NOTICED`, compensates the entire opt-out cascade: the notice track returns
    `OPT_OUT_NOTICED` → `NOTICES_PENDING`, `opt_out_notice_id` is cleared to null ... every
    household on the case with `status` `OPT_OUT_NOTICED` returns to `ACTIVE` with
    `ev_eligible` set back to false ... and every enhanced voucher on the case in state
    `PENDING` moves `PENDING` → `RESCINDED`".

    Design: Difficulty/cross_entity_state_dependency/opt_out_notice_rescission_is_blocked_by_an_issued_enhanced_voucher
    """
    ctx = setup_opt_out_noticed_case()
    case_id = ctx["case"]["id"]
    notice_id = ctx["notice"]["id"]
    ev_one, ev_two = ctx["enhanced_vouchers"]
    issue_enhanced_voucher(ev_one["id"])

    validate_error(
        api_client.rescind_tenant_notice(
            notice_id,
            rescind_payload("Owner reconsidered and will renew"),
            ctx["owner_headers"],
        ),
        ApiErrorId.ERR_ENHANCED_VOUCHER_ISSUED_BLOCKS_RESCIND.value,
        expected_status=409,
    )

    cleared = rescind_enhanced_voucher(
        ev_one["id"], "PHA withdrew the voucher before lease-up"
    )
    assert cleared["state"] == "RESCINDED"
    assert validate_success(
        api_client.get_tenant_household(ctx["household_one"]["id"], CA_HEADERS)
    )["status"] == "OPT_OUT_NOTICED", (
        "the household fell back to the noticed state, which the owner may now unwind"
    )

    rescinded = rescind_notice(
        notice_id, "Owner reconsidered and will renew", ctx["owner_headers"]
    )
    assert rescinded["status"] == "RESCINDED"
    assert rescinded["rescind_reason"] == "Owner reconsidered and will renew"

    case_after = validate_success(api_client.get_renewal_case(case_id, CA_HEADERS))
    assert case_after["notice_track_status"] == "NOTICES_PENDING"
    assert case_after["opt_out_notice_id"] is None

    assert validate_success(api_client.get_enhanced_voucher(ev_two["id"], PHA_HEADERS))[
        "state"
    ] == "RESCINDED", "the still-pending voucher was swept by the unwinding"
    assert validate_success(api_client.get_enhanced_voucher(ev_one["id"], PHA_HEADERS))[
        "state"
    ] == "RESCINDED", "the already-rescinded voucher stayed in its terminal state"

    for household in (ctx["household_one"], ctx["household_two"]):
        row = validate_success(
            api_client.get_tenant_household(household["id"], CA_HEADERS)
        )
        assert row["status"] == "ACTIVE", (
            f"the household returned to project-based assistance, got {row['status']}"
        )
        assert row["ev_eligible"] is False

    assert validate_success(api_client.get_hap_contract(ctx["contract"]["id"], CA_HEADERS))[
        "lifecycle_status"
    ] == "RENEWAL_PENDING", "the contract returned to the renewal path"

    prop_after = validate_success(api_client.get_property(ctx["property"]["id"], CA_HEADERS))
    assert prop_after["units_under_hap_count"] == 20
    assert prop_after["enhanced_voucher_unit_count"] == 0
    assert prop_after["released_unit_count"] == 0
    assert_unit_invariant(prop_after)


def test_issuing_then_rescinding_one_voucher_returns_all_three_counters():
    """"Issuance ... moves one unit across the property ledger: `units_under_hap_count`
    decrements by 1, `enhanced_voucher_unit_count` increments by 1 ... Rescission is the exact
    compensation ... `enhanced_voucher_unit_count` decrements by 1, `units_under_hap_count`
    increments by 1, and the property's `version` increments by 1 — all three counters back to
    their pre-issuance values".

    Design: Difficulty/compensating_invariant/rescinding_an_issued_enhanced_voucher_restores_the_three_unit_counters_without_drift
    """
    ctx = setup_opt_out_noticed_case()
    prop_id = ctx["property"]["id"]
    ev_one = ctx["enhanced_vouchers"][0]

    before = validate_success(api_client.get_property(prop_id, CA_HEADERS))
    assert before["units_under_hap_count"] == 20
    assert before["enhanced_voucher_unit_count"] == 0
    assert before["released_unit_count"] == 0
    assert before["assisted_unit_count"] == 20
    assert_unit_invariant(before)
    version_before = before["version"]

    issued = issue_enhanced_voucher(ev_one["id"])
    assert issued["state"] == "ISSUED"
    assert issued["issuing_pha_user_id"] == PHA_USER_ID
    assert issued["issued_on_date"] == "2026-12-01", (
        f"issuance stamps the clock date, got {issued['issued_on_date']}"
    )

    midway = validate_success(api_client.get_property(prop_id, CA_HEADERS))
    assert midway["units_under_hap_count"] == 19
    assert midway["enhanced_voucher_unit_count"] == 1
    assert midway["released_unit_count"] == 0, (
        "issuance moves a unit sideways, not out, got " f"{midway['released_unit_count']}"
    )
    assert_unit_invariant(midway)

    rescinded = rescind_enhanced_voucher(
        ev_one["id"], "PHA withdrew the voucher before lease-up"
    )
    assert rescinded["state"] == "RESCINDED"
    assert validate_success(
        api_client.get_tenant_household(ctx["household_one"]["id"], CA_HEADERS)
    )["status"] == "OPT_OUT_NOTICED"

    after = validate_success(api_client.get_property(prop_id, CA_HEADERS))
    assert after["units_under_hap_count"] == 20, (
        "the unit came back under HAP rather than landing in released, got "
        f"{after['units_under_hap_count']}"
    )
    assert after["enhanced_voucher_unit_count"] == 0
    assert after["released_unit_count"] == 0
    assert_unit_invariant(after)
    assert after["version"] > version_before, (
        "two writes happened even though the counters are restored, got version "
        f"{after['version']} against {version_before}"
    )


def test_the_voucher_compensation_touches_nothing_beyond_the_counters():
    """"Rescission is the exact compensation. A `PhaAdministrator` rescinds an `ISSUED` voucher
    with a payload carrying a `reason`, provided the household's `status` is still `EV_ISSUED`
    and not `MOVED_OUT` ... `RESCINDED` is terminal for a voucher".

    Design: Difficulty/compensating_invariant/rescinding_an_issued_enhanced_voucher_restores_the_three_unit_counters_without_drift
    """
    ctx = setup_opt_out_noticed_case()
    case_id = ctx["case"]["id"]
    ev_one, ev_two = ctx["enhanced_vouchers"]
    contract_before = validate_success(
        api_client.get_hap_contract(ctx["contract"]["id"], CA_HEADERS)
    )
    case_before = validate_success(api_client.get_renewal_case(case_id, CA_HEADERS))
    household_two_before = validate_success(
        api_client.get_tenant_household(ctx["household_two"]["id"], CA_HEADERS)
    )

    issue_enhanced_voucher(ev_one["id"])
    rescind_enhanced_voucher(ev_one["id"], "PHA withdrew the voucher before lease-up")

    assert validate_success(api_client.get_enhanced_voucher(ev_two["id"], PHA_HEADERS))[
        "state"
    ] == "PENDING", "the sibling voucher was never in play"
    case_after = validate_success(api_client.get_renewal_case(case_id, CA_HEADERS))
    assert case_after["notice_track_status"] == "OPT_OUT_NOTICED"
    assert case_after["version"] == case_before["version"], (
        f"the case was untouched, got version {case_after['version']}"
    )
    contract_after = validate_success(
        api_client.get_hap_contract(ctx["contract"]["id"], CA_HEADERS)
    )
    assert contract_after["lifecycle_status"] == "OPT_OUT_PENDING"
    assert contract_after["version"] == contract_before["version"], (
        f"the contract was untouched, got version {contract_after['version']}"
    )
    assert validate_success(api_client.get_tenant_notice(ctx["notice"]["id"], CA_HEADERS))[
        "status"
    ] == "ISSUED"
    household_two_after = validate_success(
        api_client.get_tenant_household(ctx["household_two"]["id"], CA_HEADERS)
    )
    assert household_two_after["version"] == household_two_before["version"]
    assert household_two_after["status"] == "OPT_OUT_NOTICED"

    validate_error(
        api_client.issue_enhanced_voucher(ev_one["id"], PHA_HEADERS),
        ApiErrorId.ERR_TRANSITION_NOT_ALLOWED.value,
        expected_status=409,
    )
    assert validate_success(api_client.get_enhanced_voucher(ev_one["id"], PHA_HEADERS))[
        "state"
    ] == "RESCINDED", "the terminal state is locked down against a repeat issuance"
    final_property = validate_success(
        api_client.get_property(ctx["property"]["id"], CA_HEADERS)
    )
    assert final_property["units_under_hap_count"] == 20
    assert final_property["enhanced_voucher_unit_count"] == 0
    assert_unit_invariant(final_property)


def test_a_voucher_worth_nothing_is_still_minted_but_cannot_be_issued():
    """"A household whose entitlement computes to zero still receives a `PENDING` row — the
    record exists for audit — but its voucher cannot be issued", and "A zero entitlement is
    refused with `ERR_NO_ENHANCEMENT_ENTITLEMENT` (HTTP 422)".

    Design: Corner/errors/an_enhanced_voucher_worth_nothing_is_minted_but_cannot_be_issued
    """
    ctx = setup_portfolio()
    household = create_household(
        ctx["property"]["id"], ctx["owner_headers"], **HOUSEHOLD_AT_THE_PAYMENT_STANDARD
    )
    cert = certify_household(household["id"], ctx["owner_headers"], "2026-07-01")
    assert cert["ttp_cents"] == 137500, (
        "round_half_up(5500001 / 12) is 458333 and 30 percent of that is 137500, which beats "
        f"the 45833 gross arm and the 2500 floor, got {cert['ttp_cents']}"
    )
    assert cert["hap_cents"] == 0, (
        "the gross rent 129500 less a 137500 payment is floored at zero, got "
        f"{cert['hap_cents']}"
    )

    set_clock_date("2026-12-01")
    case = validate_success(
        api_client.create_renewal_case(
            create_renewal_case_payload(ctx["contract"]["id"]), ctx["owner_headers"]
        ),
        expected_status=201,
    )
    notice = issue_opt_out_notice(case["id"], ctx["owner_headers"], "2027-12-01")
    assert notice["lead_days"] == 365, (
        f"2026-12-01 to 2027-12-01 is exactly 365 whole days, got {notice['lead_days']}"
    )
    assert notice["required_lead_days"] == 365
    recorded = validate_success(
        api_client.record_opt_out(case["id"], ctx["owner_headers"])
    )
    assert recorded["notice_track_status"] == "OPT_OUT_NOTICED"

    rows, meta = validate_paginated(
        api_client.list_case_enhanced_vouchers(case["id"], PHA_HEADERS, state="PENDING")
    )
    assert meta["total_count"] == 1, (
        "the cascade minted the row before any worth test, got " f"{meta['total_count']}"
    )
    voucher = rows[0]
    assert voucher["payment_standard_cents"] == 137500
    assert voucher["ttp_snapshot_cents"] == 137500
    assert voucher["entitlement_cents"] == 0, (
        "the entitlement is clamped at zero rather than going negative, got "
        f"{voucher['entitlement_cents']}"
    )

    validate_error(
        api_client.issue_enhanced_voucher(voucher["id"], PHA_HEADERS),
        ApiErrorId.ERR_NO_ENHANCEMENT_ENTITLEMENT.value,
        expected_status=422,
    )
    after = validate_success(api_client.get_enhanced_voucher(voucher["id"], PHA_HEADERS))
    assert after["state"] == "PENDING"
    assert after["issued_on_date"] is None
    assert after["issuing_pha_user_id"] is None
    assert validate_success(
        api_client.get_tenant_household(household["id"], CA_HEADERS)
    )["status"] == "OPT_OUT_NOTICED"
    prop_after = validate_success(api_client.get_property(ctx["property"]["id"], CA_HEADERS))
    assert prop_after["units_under_hap_count"] == 20
    assert prop_after["enhanced_voucher_unit_count"] == 0
    assert_unit_invariant(prop_after)
