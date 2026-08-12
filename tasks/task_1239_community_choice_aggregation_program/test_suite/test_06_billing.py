"""Monthly billing: per-line rounding discipline, enrollment gating, the
PCIA final-rate rule, the submit/reject/reopen branch, and read paths."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_billing_extract,
    assert_billing_line,
    advance_through_enrollment,
    close_notice_at_deadline,
    create_account_spec,
    create_billing_line_payload,
    create_extract,
    create_forecast,
    create_notice,
    create_product_payload,
    create_rate_schedule_payload,
    get_account,
    get_extract,
    get_notice,
    ingest_accounts,
    issue_notice,
    parse_iso,
    post_line,
    record_opt_out,
    set_clock,
    setup_accepted_extract,
    setup_active_authority,
    setup_draft_extract_with_lines,
    setup_enrolled_accounts,
    validate_error,
    validate_paginated,
    validate_success,
)

RA = TEST_USERS["rate_analyst_headers"]
BC = TEST_USERS["billing_coordinator_headers"]
CS = TEST_USERS["customer_service_headers"]
PO = TEST_USERS["program_operator_headers"]
UL = TEST_USERS["utility_liaison_headers"]


def test_billing_line_round_per_line_values(api):
    """PRD §2.6: "**Round per line, then sum** — never sum-then-round. Each billing line's generation charge and PCIA charge is rounded to whole cents independently at posting time, and the parent extract's totals are the sums of those already-rounded line values."
    PRD §3.6: "The `generation_charge_cents` is the usage multiplied by the adopted `energy_rate_cents_per_kwh` for the product matching the account's current `product_election`, where the schedule's window covers the first day of the service month, rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/billing_line_round_per_line_then_sum
    """
    setup_active_authority()
    enrolled = setup_enrolled_accounts(
        specs=[
            create_account_spec(utility_account_number="U-3001"),
            create_account_spec(utility_account_number="U-3002"),
            create_account_spec(utility_account_number="U-3003"),
        ]
    )
    extract = setup_draft_extract_with_lines(
        "2026-05", [(account_id, 1) for account_id in enrolled["account_ids"]]
    )

    lines, _meta = validate_paginated(api.list_extract_lines(extract["id"], BC))
    assert len(lines) == 3
    for line in lines:
        assert_billing_line(line)
        # round_half_up(1 * 11.40) == 11 per line
        assert line["generation_charge_cents"] == 11
        # round_half_up(1 * 1.50) == 2 per line
        assert line["pcia_charge_cents"] == 2


def test_extract_total_sums_rounded_lines(api):
    """PRD §2.6: "**Round per line, then sum** — never sum-then-round. Each billing line's generation charge and PCIA charge is rounded to whole cents independently at posting time, and the parent extract's totals are the sums of those already-rounded line values. The same discipline applies wherever an accumulation occurs: per-item rounding happens first, accumulation second."

    Design: Difficulty/combinatorial_formula/billing_line_round_per_line_then_sum
    """
    setup_active_authority()
    enrolled = setup_enrolled_accounts(
        specs=[
            create_account_spec(utility_account_number="U-3001"),
            create_account_spec(utility_account_number="U-3002"),
            create_account_spec(utility_account_number="U-3003"),
        ]
    )
    extract = setup_draft_extract_with_lines(
        "2026-05", [(account_id, 1) for account_id in enrolled["account_ids"]]
    )

    # Pinned per-line-then-sum: 3 * round_half_up(11.40) = 3 * 11 = 33.
    # The forbidden sum-then-round order would give round_half_up(34.20) = 34.
    assert extract["line_count"] == 3
    assert extract["total_billed_cents"] == 33
    assert extract["total_pcia_collected_cents"] == 6


def test_billing_line_rejected_for_opted_back_account(api):
    """PRD §3.6: "Posting a line requires the parent extract to be in `DRAFT` and the account to be `ENROLLED` for the billed month — a line against a non-enrolled account is `ERR_REFERENTIAL_STATE`, and the adopted-schedule prerequisites surface as `ERR_NO_DEFAULT_PRODUCT` or `ERR_REFERENTIAL_STATE` as applicable."
    PRD §3.3: "For an already-`ENROLLED` account, an `OPT_BACK_TO_BUNDLED` election moves it to `OPTED_BACK_TO_BUNDLED`, which cascades in two hops: first, the account becomes ineligible for any future billing line posting, so line creation against it is rejected; second, the next actual-trued load forecast snapshot excludes the account entirely, which itself shifts that snapshot's coverage position."

    Design: Difficulty/cross_entity_state_dependency/billing_line_gated_by_account_enrollment
    """
    setup_active_authority()
    enrolled = setup_enrolled_accounts(
        specs=[create_account_spec(utility_account_number="U-7001")]
    )
    account_id = enrolled["account_ids"][0]
    notice_id = enrolled["notice"]["id"]

    validate_success(
        record_opt_out(account_id, notice_id, election_type="OPT_BACK_TO_BUNDLED"),
        201,
    )
    assert get_account(account_id)["enrollment_state"] == "OPTED_BACK_TO_BUNDLED"

    extract = create_extract("2026-06")
    res = api.post_billing_line(
        extract["id"],
        create_billing_line_payload(service_account_id=account_id, usage_kwh=400),
        BC,
    )
    validate_error(res, ApiErrorId.ERR_REFERENTIAL_STATE)

    extract_after = get_extract(extract["id"])
    assert extract_after["line_count"] == 0
    assert extract_after["total_billed_cents"] == 0


def test_billing_line_accepted_for_enrolled_account_in_same_extract(api):
    """PRD §3.6: "Posting a line requires the parent extract to be in `DRAFT` and the account to be `ENROLLED` for the billed month — a line against a non-enrolled account is `ERR_REFERENTIAL_STATE`, and the adopted-schedule prerequisites surface as `ERR_NO_DEFAULT_PRODUCT` or `ERR_REFERENTIAL_STATE` as applicable."

    Design: Difficulty/cross_entity_state_dependency/billing_line_gated_by_account_enrollment
    """
    setup_active_authority()
    enrolled = setup_enrolled_accounts(
        specs=[
            create_account_spec(utility_account_number="U-7001"),
            create_account_spec(utility_account_number="U-7002"),
        ]
    )
    opted_back, still_enrolled = enrolled["account_ids"]
    notice_id = enrolled["notice"]["id"]
    validate_success(
        record_opt_out(opted_back, notice_id, election_type="OPT_BACK_TO_BUNDLED"),
        201,
    )

    extract = create_extract("2026-06")
    line = validate_success(
        api.post_billing_line(
            extract["id"],
            create_billing_line_payload(
                service_account_id=still_enrolled, usage_kwh=400
            ),
            BC,
        ),
        201,
    )
    assert_billing_line(line)
    assert get_extract(extract["id"])["line_count"] == 1, (
        "the extract itself is legally DRAFT — only the opted-back account's "
        "state blocked the earlier posting"
    )


def test_billing_line_uses_adopted_pcia_rate_not_proposed(api):
    """PRD §3.6: "The `pcia_charge_cents` is the usage multiplied by the `pcia_rate_cents_per_kwh` carried on the adopted schedule for the account's `vintage_year`, likewise rounded half up per line."
    PRD §3.5: "When an account's vintage-year schedule row has not yet been adopted at forecast time, the provisional figure uses the PCIA rate of the most recently superseded schedule; final billing always uses the adopted row, so provisional and final figures legitimately differ for identical accounts."

    Design: Difficulty/dual_variant_calc/pcia_exit_fee_provisional_vs_final_forecast
    """
    setup_active_authority(rate_setting_policy="DISCOUNT_TO_INCUMBENT", discount_floor_bps=100)
    enrolled = setup_enrolled_accounts(
        specs=[create_account_spec(utility_account_number="U-2001", annual_kwh_estimate=9600)]
    )
    account_id = enrolled["account_ids"][0]

    # A 2027 row carrying pcia 2.10 exists but is only PROPOSED — final billing
    # must never price off a non-adopted (provisional) row.
    default_product_id = _get_default_product_id(api)
    sched_2027 = validate_success(
        api.create_rate_schedule(
            create_rate_schedule_payload(
                product_id=default_product_id,
                period_start="2027-01-01T00:00:00Z",
                period_end="2028-01-01T00:00:00Z",
                energy_rate_cents_per_kwh=11.60,
                pcia_rate_cents_per_kwh=2.10,
            ),
            RA,
        ),
        201,
    )
    validate_success(api.propose_rate_schedule(sched_2027["id"], {}, RA), 200)
    create_forecast("PLAN-2027", "ADOPTED_PLAN", 2027)

    line = post_line(create_extract("2026-05")["id"], account_id, 800)
    assert_billing_line(line)
    # Final billing uses the ADOPTED 2026 row: 800 kWh x 11.40 c = 9120 c.
    assert line["generation_charge_cents"] == 9120
    # 800 kWh x ADOPTED 1.50 c/kWh = 1200 c; the provisional 2.10 row would
    # have priced the same usage at 1680 c.
    assert line["pcia_charge_cents"] == 1200


def test_extract_totals_reflect_adopted_pcia_rate(api):
    """PRD §3.6: "The `pcia_charge_cents` is the usage multiplied by the `pcia_rate_cents_per_kwh` carried on the adopted schedule for the account's `vintage_year`, likewise rounded half up per line."
    PRD §3.6: "Each line's `billing_extract_id` is set by the system from the nested path of the posting operation rather than from the payload. Each line snapshots `product_election_at_billing` so that later election changes never rewrite history, and each posting refreshes the extract's `line_count`, `total_billed_cents`, and `total_pcia_collected_cents` — the PCIA total being money owed to the incumbent, not CCA revenue."

    Design: Difficulty/dual_variant_calc/pcia_exit_fee_provisional_vs_final_forecast
    """
    setup_active_authority(rate_setting_policy="DISCOUNT_TO_INCUMBENT", discount_floor_bps=100)
    enrolled = setup_enrolled_accounts(
        specs=[create_account_spec(utility_account_number="U-2001", annual_kwh_estimate=9600)]
    )
    account_id = enrolled["account_ids"][0]

    default_product_id = _get_default_product_id(api)
    sched_2027 = validate_success(
        api.create_rate_schedule(
            create_rate_schedule_payload(
                product_id=default_product_id,
                period_start="2027-01-01T00:00:00Z",
                period_end="2028-01-01T00:00:00Z",
                energy_rate_cents_per_kwh=11.60,
                pcia_rate_cents_per_kwh=2.10,
            ),
            RA,
        ),
        201,
    )
    validate_success(api.propose_rate_schedule(sched_2027["id"], {}, RA), 200)
    create_forecast("PLAN-2027", "ADOPTED_PLAN", 2027)

    extract = create_extract("2026-05")
    post_line(extract["id"], account_id, 800)

    extract_after = get_extract(extract["id"])
    assert_billing_extract(extract_after)
    assert extract_after["line_count"] == 1
    assert extract_after["total_billed_cents"] == 9120
    assert extract_after["total_pcia_collected_cents"] == 1200

    # The provisional row stays PROPOSED — it was never adopted.
    sched_after = validate_success(api.get_rate_schedule(sched_2027["id"], RA), 200)
    assert sched_after["status"] == "PROPOSED"


def _get_default_product_id(api) -> str:
    products, _meta = validate_paginated(api.list_products(RA))
    assert len(products) == 1
    return products[0]["id"]


def test_extract_reject_reopen_restores_line_posting(api):
    """PRD §3.6: "A rejected extract is not dead — a `BillingCoordinator` reopens it, returning it to `DRAFT` so lines can be added or removed again."
    PRD §3.6: "The `generation_charge_cents` is the usage multiplied by the adopted `energy_rate_cents_per_kwh` for the product matching the account's current `product_election`, where the schedule's window covers the first day of the service month, rounded half up to whole cents."

    Design: Difficulty/non_linear_state_machine/billing_extract_submit_reject_reopen_branch
    """
    setup_active_authority()
    enrolled = setup_enrolled_accounts(
        specs=[create_account_spec(utility_account_number="U-4001")]
    )
    account_id = enrolled["account_ids"][0]

    extract = setup_draft_extract_with_lines("2026-05", [(account_id, 500)])
    validate_success(api.submit_billing_extract(extract["id"], {}, BC), 200)
    rejected = validate_success(api.utility_reject_extract(extract["id"], {}, UL), 200)
    assert rejected["status"] == "REJECTED_BY_UTILITY"
    reopened = validate_success(api.reopen_billing_extract(extract["id"], {}, BC), 200)
    assert reopened["status"] == "DRAFT"

    # Line mutability is restored by the revert branch.
    post_line(extract["id"], account_id, 250)
    extract_after = get_extract(extract["id"])
    assert extract_after["line_count"] == 2
    # 500 x 11.40 = 5700 plus 250 x 11.40 = 2850
    assert extract_after["total_billed_cents"] == 8550


def test_extract_reject_branch_never_credits_account_ledger(api):
    """PRD §3.6: "acceptance moves the extract `SUBMITTED → ACCEPTED` and cascades every child line's `generation_charge_cents` onto its account's `cumulative_billed_cents`, refreshing each affected account's `updated_at` and incrementing each account's `version`; rejection moves it `SUBMITTED → REJECTED_BY_UTILITY` with no cascade."

    Design: Difficulty/non_linear_state_machine/billing_extract_submit_reject_reopen_branch
    """
    setup_active_authority()
    enrolled = setup_enrolled_accounts(
        specs=[create_account_spec(utility_account_number="U-4001")]
    )
    account_id = enrolled["account_ids"][0]

    extract = setup_draft_extract_with_lines("2026-05", [(account_id, 500)])
    validate_success(api.submit_billing_extract(extract["id"], {}, BC), 200)
    validate_success(api.utility_reject_extract(extract["id"], {}, UL), 200)
    validate_success(api.reopen_billing_extract(extract["id"], {}, BC), 200)
    post_line(extract["id"], account_id, 250)

    account = get_account(account_id)
    assert account["cumulative_billed_cents"] == 0, (
        "the ACCEPTED fork was never taken, so no ledger credit ever fired"
    )
    assert account["cumulative_remitted_cents"] == 0


def test_billing_line_input_set_excludes_non_enrolled(api):
    """PRD §3.6: "Posting a line requires the parent extract to be in `DRAFT` and the account to be `ENROLLED` for the billed month — a line against a non-enrolled account is `ERR_REFERENTIAL_STATE`, and the adopted-schedule prerequisites surface as `ERR_NO_DEFAULT_PRODUCT` or `ERR_REFERENTIAL_STATE` as applicable."
    PRD §3.2: "At close, the wave's `account_count_opted_out` is recomputed as the number of opt-out requests filed under this notice with `election_type` equal to `OPT_OUT` that have not been rescinded by a later reversal request."

    Design: Corner/calculations/billing_line_input_set_excludes_non_enrolled
    """
    setup_active_authority()
    ids = ingest_accounts([create_account_spec(utility_account_number="U-6101")])
    notice = create_notice()
    issue_notice(notice["id"])

    # Opt out inside the window; the account is then excluded from the sweep.
    validate_success(record_opt_out(ids[0], notice["id"]), 201)
    closed = close_notice_at_deadline(notice["id"])
    assert closed["account_count_opted_out"] == 1
    settled, _epoch = advance_through_enrollment(notice["id"])
    assert settled["account_count_enrolled"] == 0
    assert get_account(ids[0])["enrollment_state"] == "OPTED_OUT"

    extract = create_extract("2026-05")
    res = api.post_billing_line(
        extract["id"],
        create_billing_line_payload(service_account_id=ids[0], usage_kwh=500),
        BC,
    )
    validate_error(res, ApiErrorId.ERR_REFERENTIAL_STATE)
    assert get_extract(extract["id"])["line_count"] == 0


def test_immediate_consistency_submit_visible_in_same_response(api):
    """PRD §3.6: "Submission moves the extract `DRAFT → SUBMITTED`, requires at least one line and an `ACTIVE` authority, and stamps `submitted_on` from the logical clock."
    PRD §2.4: "A `BoardDirector` may set the logical clock by supplying a `to_iso8601` instant, and every timestamp the server stamps itself — `received_at` on an opt-out election, `submitted_on` on an extract, `as_of` on a forecast snapshot, `retired_on` on a REC retirement — is taken from this logical clock."

    Design: Corner/consistency_model/immediate_consistency_mutation_visible_in_same_response
    """
    setup_active_authority()
    enrolled = setup_enrolled_accounts(
        specs=[create_account_spec(utility_account_number="U-C01")]
    )
    extract = setup_draft_extract_with_lines(
        "2026-05", [(enrolled["account_ids"][0], 1000)]
    )

    set_clock("2026-05-20T12:00:00Z")
    submitted = validate_success(api.submit_billing_extract(extract["id"], {}, BC), 200)
    assert submitted["status"] == "SUBMITTED"
    assert parse_iso(submitted["submitted_on"]) == parse_iso("2026-05-20T12:00:00Z"), (
        "submitted_on is stamped from the logical clock at submit time"
    )

    reread = get_extract(extract["id"])
    assert reread["status"] == "SUBMITTED"
    assert parse_iso(reread["submitted_on"]) == parse_iso(submitted["submitted_on"])
    assert reread["total_billed_cents"] == 11400


def test_reverse_reachability_reads(api):
    """PRD §3.2: "An account-by-account read of the election trail is available through the reverse-reachability listing of opt-out requests under a notice."
    PRD §3.6: "Lines are also reachable in aggregate through a filtered listing that accepts `service_account_id` or `billing_extract_id` as filters, giving reverse reachability from an account to its billing history."
    PRD §4: "GET | `/cca/products/{id}/rate-schedules` | List schedules of a product" and "GET | `/cca/billing-extracts/{id}/lines` | List lines of an extract".

    Design: Corner/endpoints/reverse_reachability_reads
    """
    ctx = setup_active_authority()
    enrolled = setup_enrolled_accounts(
        specs=[create_account_spec(utility_account_number="U-R01")]
    )
    account_id = enrolled["account_ids"][0]
    notice_id = enrolled["notice"]["id"]
    extract = setup_draft_extract_with_lines("2026-05", [(account_id, 1000)])

    schedules, _ = validate_paginated(
        api.list_product_rate_schedules(ctx["product"]["id"], RA)
    )
    assert len(schedules) == 1

    lines, _ = validate_paginated(api.list_extract_lines(extract["id"], BC))
    assert len(lines) == 1
    assert lines[0]["generation_charge_cents"] == 11400

    opt_outs, _ = validate_paginated(api.list_notice_opt_out_requests(notice_id, PO))
    assert opt_outs == [], "no elections were recorded under this notice"

    account_lines, _ = validate_paginated(
        api.list_billing_lines(BC, params={"service_account_id": account_id})
    )
    assert len(account_lines) == 1
    assert account_lines[0]["billing_extract_id"] == extract["id"]
