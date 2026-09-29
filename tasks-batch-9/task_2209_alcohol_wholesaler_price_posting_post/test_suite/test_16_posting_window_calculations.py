"""Effective dates, deadline and window boundaries, and derived posting prices.

Every expectation in this module is fixed by the PRD: effective-date arithmetic and
the posting deadline instant (§3.3), the post-and-hold window (§2.7, §3.4), the
correction window and the clerical limit (§3.6), tier and combination price
derivation with its cooldown buffer (§3.5), and posted-price resolution (§3.7).
"""

from test_helpers import (
    certify_schedule,
    create_combination_sale_payload,
    create_error_correction_payload,
    create_hold_amendment_payload,
    create_price_schedule_payload,
    create_quantity_discount_tier_payload,
    new_brand,
    new_combination,
    new_filing_agent,
    new_item,
    new_schedule,
    new_state_program,
    new_wholesaler,
    read_exposure,
    read_item,
    read_posted_price,
    read_schedule,
    read_wholesaler,
    regulator_headers,
    run_posting,
    set_clock,
    setup_certified_schedule,
    setup_draft_schedule,
    setup_licensee_base,
    setup_two_wholesalers_certified,
    submit_schedule,
    validate_error,
    validate_paginated,
    validate_success,
)

ITEM_750_12 = {
    "size_ml": 750,
    "bottles_per_case": 12,
    "case_price_cents": 120_000,
    "unit_price_cents": 11_000,
}


def _filer_with_draft_schedule(program_id, license_number, agent_name, posting_month, item_spec):
    """Register a wholesaler with an approved brand and one DRAFT schedule item."""
    wholesaler = new_wholesaler(
        program_id,
        license_number=license_number,
        legal_name="{} Distributing".format(license_number),
    )
    agent, agent_headers = new_filing_agent(wholesaler["id"], agent_name)
    brand = new_brand(wholesaler["id"], agent_headers, approve=True)
    schedule = new_schedule(
        wholesaler["id"], program_id, agent_headers, posting_month=posting_month
    )
    item = new_item(schedule["id"], brand["id"], agent_headers, **item_spec)
    return {
        "wholesaler": wholesaler,
        "agent_headers": agent_headers,
        "brand": brand,
        "schedule": schedule,
        "item": item,
    }


def test_01_effective_date_is_the_month_after_the_posting_month_and_december_rolls_the_year(api):
    """PRD §3.3: "A `posting_month` of `2026-09` therefore yields an `effective_date` of `2026-10-01T00:00:00.000Z`, and a `posting_month` of `2026-12` yields `2027-01-01T00:00:00.000Z`."

    Both schedules are opened by the same filing agent against the same program, so the
    only thing that differs is the month string being parsed.

    Design: Corner/calculations/schedule_effective_date_is_the_month_after_the_posting_month_and_rolls_the_year_in_december
    """
    scene = setup_licensee_base(clock="2026-08-01T00:00:00Z")

    september = validate_success(
        api.create_price_schedule(
            create_price_schedule_payload(
                scene["wholesaler"]["id"], scene["program"]["id"], posting_month="2026-09"
            ),
            scene["agent_headers"],
        ),
        201,
    )
    december = validate_success(
        api.create_price_schedule(
            create_price_schedule_payload(
                scene["wholesaler"]["id"], scene["program"]["id"], posting_month="2026-12"
            ),
            scene["agent_headers"],
        ),
        201,
    )

    assert september["effective_date"] == "2026-10-01T00:00:00.000Z", (
        "a posting_month of 2026-09 must take effect at the first instant of October 2026, "
        "got {}".format(september["effective_date"])
    )
    assert december["effective_date"] == "2027-01-01T00:00:00.000Z", (
        "a posting_month of 2026-12 must roll the year and take effect 2027-01-01T00:00:00.000Z, "
        "got {}".format(december["effective_date"])
    )

    for schedule in (september, december):
        assert schedule["status"] == "DRAFT", (
            "a new schedule always begins in DRAFT, got {}".format(schedule["status"])
        )
        assert schedule["is_late"] is False, "a new schedule begins with is_late false"
        assert schedule.get("filed_at") is None, "a new schedule begins with filed_at unset"
        assert schedule["item_count"] == 0, "a new schedule begins with item_count 0"


def test_02_late_filing_admits_the_deadline_millisecond_and_rejects_the_next_one(api):
    """PRD §3.3: "`is_late` is set to `true` when `filed_at` is strictly after the deadline instant and to `false` otherwise; a `filed_at` exactly equal to the deadline instant is on time."

    Three wholesalers file the same posting month at three consecutive milliseconds
    around the `2026-09-10T23:59:59.999Z` deadline instant of §3.3.

    Design: Corner/calculations/late_filing_determination_admits_the_deadline_millisecond_and_rejects_the_next_one
    """
    set_clock("2026-09-10T23:59:59.998Z")
    program = new_state_program()

    filer_a = _filer_with_draft_schedule(
        program["id"], "W-1001", "Anna Early", "2026-09", ITEM_750_12
    )
    filer_b = _filer_with_draft_schedule(
        program["id"],
        "W-2002",
        "Ben Exact",
        "2026-09",
        {
            "size_ml": 750,
            "bottles_per_case": 12,
            "case_price_cents": 110_000,
            "unit_price_cents": 10_000,
        },
    )
    filer_c = _filer_with_draft_schedule(
        program["id"],
        "W-3003",
        "Cara Late",
        "2026-09",
        {
            "size_ml": 750,
            "bottles_per_case": 12,
            "case_price_cents": 100_000,
            "unit_price_cents": 9_000,
        },
    )

    submitted_a = validate_success(
        api.submit_price_schedule(filer_a["schedule"]["id"], filer_a["agent_headers"]), 200
    )
    set_clock("2026-09-10T23:59:59.999Z")
    submitted_b = validate_success(
        api.submit_price_schedule(filer_b["schedule"]["id"], filer_b["agent_headers"]), 200
    )
    set_clock("2026-09-11T00:00:00.000Z")
    submitted_c = validate_success(
        api.submit_price_schedule(filer_c["schedule"]["id"], filer_c["agent_headers"]), 200
    )

    for submitted in (submitted_a, submitted_b, submitted_c):
        assert submitted["status"] == "SUBMITTED", (
            "filing is the DRAFT to SUBMITTED transition, got {}".format(submitted["status"])
        )

    assert submitted_a["is_late"] is False, "a filing one millisecond before the deadline is on time"
    assert submitted_a["filed_at"] == "2026-09-10T23:59:59.998Z", (
        "filed_at must echo the current server time, got {}".format(submitted_a["filed_at"])
    )
    assert submitted_b["is_late"] is False, (
        "a filed_at exactly equal to the deadline instant is on time"
    )
    assert submitted_b["filed_at"] == "2026-09-10T23:59:59.999Z", (
        "filed_at must echo the deadline instant, got {}".format(submitted_b["filed_at"])
    )
    assert submitted_c["is_late"] is True, (
        "a filing one millisecond after the deadline instant is late"
    )
    assert submitted_c["filed_at"] == "2026-09-11T00:00:00.000Z", (
        "filed_at must echo the current server time, got {}".format(submitted_c["filed_at"])
    )

    for filer in (filer_a, filer_b):
        wholesaler = read_wholesaler(filer["wholesaler"]["id"])
        assert wholesaler["late_filing_count"] == 0, (
            "an on-time filing moves no counter on the wholesaler"
        )
        assert wholesaler["late_filing_penalty_accrued_cents"] == 0, (
            "an on-time filing accrues no late filing penalty"
        )

    wholesaler_c = read_wholesaler(filer_c["wholesaler"]["id"])
    assert wholesaler_c["late_filing_count"] == 1, (
        "the late filer's late_filing_count must be 1, got {}".format(
            wholesaler_c["late_filing_count"]
        )
    )
    assert wholesaler_c["late_filing_penalty_accrued_cents"] == 250_000, (
        "the program's default late_filing_penalty_cents of 250000 must accrue, got {}".format(
            wholesaler_c["late_filing_penalty_accrued_cents"]
        )
    )
    assert wholesaler_c["penalty_exposure_cents"] == 250_000, (
        "penalty_exposure_cents must be recomputed to 250000, got {}".format(
            wholesaler_c["penalty_exposure_cents"]
        )
    )


def test_03_late_filing_penalty_accrues_once_per_late_schedule_and_accumulates(api):
    """PRD §3.3: "When `is_late` comes out `true`, the wholesaler's `late_filing_count` is incremented by 1, the program's `late_filing_penalty_cents` is added to the wholesaler's `late_filing_penalty_accrued_cents`, `penalty_exposure_cents` is recomputed as the sum of the four buckets, and the wholesaler's `version` is advanced by 1."

    Two separate schedules of one wholesaler are both filed after their deadlines, so the
    accrual happens twice and the bucket accumulates.

    Design: Corner/calculations/late_filing_penalty_accrues_once_per_late_schedule_and_accumulates_on_the_wholesaler
    """
    set_clock("2026-09-11T00:00:00.000Z")
    scene = setup_licensee_base(clock=None)

    july = new_schedule(
        scene["wholesaler"]["id"],
        scene["program"]["id"],
        scene["agent_headers"],
        posting_month="2026-07",
    )
    new_item(july["id"], scene["brand"]["id"], scene["agent_headers"], **ITEM_750_12)
    august = new_schedule(
        scene["wholesaler"]["id"],
        scene["program"]["id"],
        scene["agent_headers"],
        posting_month="2026-08",
    )
    new_item(
        august["id"],
        scene["brand"]["id"],
        scene["agent_headers"],
        size_ml=750,
        bottles_per_case=12,
        case_price_cents=125_000,
        unit_price_cents=12_000,
    )

    first = validate_success(
        api.submit_price_schedule(july["id"], scene["agent_headers"]), 200
    )
    assert first["is_late"] is True, "a 2026-07 filing made on 2026-09-11 is late"
    after_first = read_wholesaler(scene["wholesaler"]["id"])
    assert after_first["late_filing_count"] == 1, (
        "the first late filing sets late_filing_count to 1, got {}".format(
            after_first["late_filing_count"]
        )
    )
    assert after_first["late_filing_penalty_accrued_cents"] == 250_000, (
        "the first late filing accrues 250000 cents, got {}".format(
            after_first["late_filing_penalty_accrued_cents"]
        )
    )

    second = validate_success(
        api.submit_price_schedule(august["id"], scene["agent_headers"]), 200
    )
    assert second["is_late"] is True, "a 2026-08 filing made on 2026-09-11 is late as well"

    after_second = read_wholesaler(scene["wholesaler"]["id"])
    assert after_second["late_filing_count"] == 2, (
        "each late schedule increments late_filing_count, got {}".format(
            after_second["late_filing_count"]
        )
    )
    assert after_second["late_filing_penalty_accrued_cents"] == 500_000, (
        "two late filings accrue 500000 cents in total, got {}".format(
            after_second["late_filing_penalty_accrued_cents"]
        )
    )
    assert after_second["correction_penalty_accrued_cents"] == 0, (
        "the correction bucket is untouched by late filing"
    )
    assert after_second["amendment_penalty_accrued_cents"] == 0, (
        "the amendment bucket is untouched by late filing"
    )
    assert after_second["assessed_penalty_cents"] == 0, (
        "the assessed bucket is untouched by late filing"
    )
    assert after_second["penalty_exposure_cents"] == 500_000, (
        "penalty_exposure_cents is the plain sum of the four buckets, got {}".format(
            after_second["penalty_exposure_cents"]
        )
    )

    exposure = read_exposure(scene["wholesaler"]["id"])
    assert exposure["accrued_cents"] == 500_000, (
        "the exposure read reports 500000 accrued cents, got {}".format(
            exposure["accrued_cents"]
        )
    )
    assert exposure["provisional_cents"] == 0, (
        "assessed_exposure reports provisional_cents 0"
    )
    assert exposure["exposure_cents"] == 500_000, (
        "the exposure read reports 500000 cents of exposure, got {}".format(
            exposure["exposure_cents"]
        )
    )


def test_04_hold_window_last_millisecond_still_admits_and_accepts_an_amendment(api):
    """PRD §2.7: "The window is open when the current server time is at or after `certified_at` and strictly before `hold_window_ends_at`."

    Wholesaler A files at the very last millisecond of its three-day window and the
    regulator accepts it, so the acceptance cascade of §3.6 runs.

    Design: Corner/calculations/hold_window_last_millisecond_still_admits_and_accepts_an_amendment
    """
    scene = setup_two_wholesalers_certified(
        clock="2026-08-01T00:00:00Z",
        posting_month="2026-09",
        item_a_specs=[dict(ITEM_750_12)],
        item_b_spec={
            "size_ml": 750,
            "bottles_per_case": 12,
            "case_price_cents": 110_000,
            "unit_price_cents": 10_000,
        },
    )
    item_a = scene["items_a"][0]

    set_clock("2026-08-03T23:59:59.999Z")
    schedule_a = read_schedule(scene["schedule_a"]["id"])
    assert schedule_a["hold_window_ends_at"] == "2026-08-04T00:00:00.000Z", (
        "a schedule certified at 2026-08-01T00:00:00.000Z with a three-day window ends at "
        "2026-08-04T00:00:00.000Z, got {}".format(schedule_a["hold_window_ends_at"])
    )

    filed = validate_success(
        api.create_hold_amendment(
            create_hold_amendment_payload(
                item_a["id"], scene["item_b"]["id"], 115_000, 10_500, schedule_a["version"]
            ),
            scene["agent_a_headers"],
        ),
        201,
    )
    assert filed["status"] == "PENDING", (
        "a valid amendment is created in PENDING, got {}".format(filed["status"])
    )
    assert filed.get("prior_case_price_cents") is None, (
        "a newly filed amendment carries prior_case_price_cents unset"
    )
    assert filed.get("prior_unit_price_cents") is None, (
        "a newly filed amendment carries prior_unit_price_cents unset"
    )

    accepted = validate_success(
        api.accept_hold_amendment(filed["id"], regulator_headers()), 200
    )
    assert accepted["status"] == "ACCEPTED", (
        "acceptance is the PENDING to ACCEPTED transition, got {}".format(accepted["status"])
    )
    assert accepted["prior_case_price_cents"] == 120_000, (
        "acceptance captures the amending item's prior case price 120000, got {}".format(
            accepted["prior_case_price_cents"]
        )
    )
    assert accepted["prior_unit_price_cents"] == 11_000, (
        "acceptance captures the amending item's prior unit price 11000, got {}".format(
            accepted["prior_unit_price_cents"]
        )
    )

    amended_item = read_item(item_a["id"])
    assert amended_item["case_price_cents"] == 115_000, (
        "the accepted amendment writes 115000 into the item, got {}".format(
            amended_item["case_price_cents"]
        )
    )
    assert amended_item["unit_price_cents"] == 10_500, (
        "the accepted amendment writes 10500 into the item, got {}".format(
            amended_item["unit_price_cents"]
        )
    )
    assert amended_item["amendment_count"] == 1, (
        "acceptance increments amendment_count to 1, got {}".format(
            amended_item["amendment_count"]
        )
    )
    assert amended_item["certified_case_price_cents"] == 120_000, (
        "the certification snapshot never changes, got {}".format(
            amended_item["certified_case_price_cents"]
        )
    )


def test_05_correction_window_end_instant_is_excluded_while_the_millisecond_before_is_admitted(api):
    """PRD §3.6: "A current server time at or after that end instant refuses the filing with `ERR_CORRECTION_WINDOW_CLOSED`."

    Certification at 2026-08-01T00:00:00.000Z with the default fifteen-day window closes
    the window at 2026-08-16T00:00:00.000Z, so the millisecond before it is the last one
    that admits a correction.

    Design: Corner/calculations/correction_window_end_instant_is_excluded_while_the_millisecond_before_is_admitted
    """
    scene = setup_certified_schedule(
        posting_month="2026-09",
        item_specs=[dict(ITEM_750_12)],
        clock="2026-08-01T00:00:00Z",
    )
    item = scene["items"][0]

    set_clock("2026-08-15T23:59:59.999Z")
    admitted = validate_success(
        api.create_error_correction(
            create_error_correction_payload(item["id"], 114_000, 10_800),
            scene["agent_headers"],
        ),
        201,
    )
    assert admitted["status"] == "SUBMITTED", (
        "a filed correction begins in SUBMITTED, got {}".format(admitted["status"])
    )
    assert admitted["prior_case_price_cents"] == 120_000, (
        "filing captures the item's current case price 120000, got {}".format(
            admitted["prior_case_price_cents"]
        )
    )
    assert abs(admitted["variance_pct"] - 0.05) < 1e-9, (
        "a 6000 cent move off 120000 is a variance_pct of 0.05, got {}".format(
            admitted["variance_pct"]
        )
    )

    set_clock("2026-08-16T00:00:00.000Z")
    refused = api.create_error_correction(
        create_error_correction_payload(item["id"], 113_000, 10_700),
        scene["agent_headers"],
    )
    validate_error(refused, "ERR_CORRECTION_WINDOW_CLOSED", 409)

    data, meta = validate_paginated(
        api.list_error_corrections(regulator_headers(), params={"item_id": item["id"]})
    )
    assert meta["total_count"] == 1, (
        "only the admitted correction may exist, got total_count {}".format(meta["total_count"])
    )
    assert data[0]["id"] == admitted["id"], (
        "the surviving correction must be the one filed inside the window"
    )

    unchanged = read_item(item["id"])
    assert unchanged["case_price_cents"] == 120_000, (
        "a refused correction leaves the item price at 120000, got {}".format(
            unchanged["case_price_cents"]
        )
    )
    assert unchanged["correction_count"] == 0, (
        "a merely submitted correction does not move the item's correction_count"
    )


def test_06_correction_variance_exactly_at_the_clerical_limit_is_admitted(api):
    """PRD §3.6: "A `variance_pct` strictly greater than `0.10` is not a clerical error but a rewrite, and is refused with `ERR_CORRECTION_EXCEEDS_CLERICAL_LIMIT`; a `variance_pct` exactly equal to `0.10` is accepted."

    Off a prior case price of 120,000 cents, a corrected price of 108,000 is exactly one
    tenth away and 107,999 is one cent beyond it.

    Design: Corner/calculations/correction_variance_exactly_at_the_clerical_limit_is_admitted_and_one_cent_beyond_is_refused
    """
    scene = setup_certified_schedule(
        posting_month="2026-09",
        item_specs=[dict(ITEM_750_12)],
        clock="2026-08-01T00:00:00Z",
    )
    item = scene["items"][0]
    set_clock("2026-08-05T00:00:00.000Z")

    refused = api.create_error_correction(
        create_error_correction_payload(item["id"], 107_999, 10_000),
        scene["agent_headers"],
    )
    validate_error(refused, "ERR_CORRECTION_EXCEEDS_CLERICAL_LIMIT", 422)

    admitted = validate_success(
        api.create_error_correction(
            create_error_correction_payload(item["id"], 108_000, 10_000),
            scene["agent_headers"],
        ),
        201,
    )
    assert admitted["status"] == "SUBMITTED", (
        "a correction at exactly the clerical limit is accepted into SUBMITTED, got {}".format(
            admitted["status"]
        )
    )
    assert abs(admitted["variance_pct"] - 0.10) < 1e-9, (
        "a 12000 cent move off 120000 is a variance_pct of 0.10, got {}".format(
            admitted["variance_pct"]
        )
    )
    assert admitted["prior_case_price_cents"] == 120_000, (
        "filing captures the prior case price 120000, got {}".format(
            admitted["prior_case_price_cents"]
        )
    )
    assert admitted["prior_unit_price_cents"] == 11_000, (
        "filing captures the prior unit price 11000, got {}".format(
            admitted["prior_unit_price_cents"]
        )
    )

    data, meta = validate_paginated(
        api.list_error_corrections(regulator_headers(), params={"item_id": item["id"]})
    )
    assert meta["total_count"] == 1, (
        "the refused filing must not have created a record, got total_count {}".format(
            meta["total_count"]
        )
    )
    assert data[0]["id"] == admitted["id"], "the only correction is the admitted one"


def test_07_tier_discounted_case_price_rounds_a_half_cent_upward(api):
    """PRD §3.5: "The tier's own price is derived, never supplied: `discounted_case_price_cents` is the item's `case_price_cents` multiplied by the quantity one minus `discount_pct`, rounded half up to whole cents."

    100,005 cents at a ten percent discount is 90,004.5 cents, and round half up carries
    it to 90,005.

    Design: Corner/calculations/tier_discounted_case_price_rounds_a_half_cent_upward
    """
    scene = setup_licensee_base(clock="2026-08-01T00:00:00Z")
    setup_draft_schedule(
        scene,
        posting_month="2026-09",
        item_specs=[
            {
                "size_ml": 750,
                "bottles_per_case": 12,
                "case_price_cents": 100_005,
                "unit_price_cents": 9_000,
            }
        ],
    )
    item = scene["items"][0]

    tier = validate_success(
        api.create_quantity_discount_tier(
            create_quantity_discount_tier_payload(item["id"], min_cases=2, discount_pct=0.10),
            scene["agent_headers"],
        ),
        201,
    )
    assert tier["discounted_case_price_cents"] == 90_005, (
        "100005 cents less ten percent is 90004.5 and rounds half up to 90005, got {}".format(
            tier["discounted_case_price_cents"]
        )
    )
    assert tier["min_cases"] == 2, "the tier echoes its min_cases of 2"
    assert abs(tier["discount_pct"] - 0.10) < 1e-9, (
        "the tier echoes its discount_pct of 0.10, got {}".format(tier["discount_pct"])
    )
    assert tier["status"] == "ACTIVE", (
        "a new tier is ACTIVE, got {}".format(tier["status"])
    )

    unchanged = read_item(item["id"])
    assert unchanged["case_price_cents"] == 100_005, (
        "deriving a tier price does not move the item's own case price, got {}".format(
            unchanged["case_price_cents"]
        )
    )


def test_09_posted_price_candidates_admit_only_effective_or_superseded_items(api):
    """PRD §3.7: "The candidate set is every price schedule item whose posting key matches the subject item's posting key, whose `status` is `EFFECTIVE` or `SUPERSEDED`, and whose owning schedule's `effective_date` is at or before the as-of instant."

    Three schedules share one posting key: September is effective, October is only posted
    and November is only submitted, so every read resolves to the September item.

    Design: Corner/calculations/posted_price_candidate_set_admits_only_effective_or_superseded_items_whose_effective_date_has_been_reached
    """
    scene = setup_licensee_base(clock="2026-08-01T00:00:00Z")
    wholesaler_id = scene["wholesaler"]["id"]
    program_id = scene["program"]["id"]
    brand_id = scene["brand"]["id"]
    agent_headers = scene["agent_headers"]
    certifier_headers = scene["certifier_headers"]

    schedule_sep = new_schedule(wholesaler_id, program_id, agent_headers, posting_month="2026-09")
    item_sep = new_item(schedule_sep["id"], brand_id, agent_headers, **ITEM_750_12)
    submit_schedule(schedule_sep["id"], agent_headers)
    certify_schedule(schedule_sep["id"], certifier_headers)

    schedule_oct = new_schedule(wholesaler_id, program_id, agent_headers, posting_month="2026-10")
    item_oct = new_item(
        schedule_oct["id"],
        brand_id,
        agent_headers,
        size_ml=750,
        bottles_per_case=12,
        case_price_cents=125_000,
        unit_price_cents=12_000,
    )
    submit_schedule(schedule_oct["id"], agent_headers)
    certify_schedule(schedule_oct["id"], certifier_headers)

    schedule_nov = new_schedule(wholesaler_id, program_id, agent_headers, posting_month="2026-11")
    item_nov = new_item(
        schedule_nov["id"],
        brand_id,
        agent_headers,
        size_ml=750,
        bottles_per_case=12,
        case_price_cents=90_000,
        unit_price_cents=9_000,
    )
    submit_schedule(schedule_nov["id"], agent_headers)

    set_clock("2026-10-01T00:00:00.000Z")
    run_posting(program_id)

    for subject in (item_sep, item_oct, item_nov):
        resolved = read_posted_price(subject["id"], as_of="2027-01-01T00:00:00Z")
        assert resolved["resolved_item_id"] == item_sep["id"], (
            "only the EFFECTIVE September item is a candidate, got resolved_item_id {}".format(
                resolved["resolved_item_id"]
            )
        )
        assert resolved["posted_case_price_cents"] == 120_000, (
            "the resolved case price is the September item's 120000, got {}".format(
                resolved["posted_case_price_cents"]
            )
        )
        assert resolved["posted_unit_price_cents"] == 11_000, (
            "the resolved unit price is the September item's 11000, got {}".format(
                resolved["posted_unit_price_cents"]
            )
        )
        assert resolved["variant"] == "as_amended", (
            "an omitted variant resolves as_amended, got {}".format(resolved["variant"])
        )
        assert resolved["as_of"] == "2027-01-01T00:00:00.000Z", (
            "the as_of instant is echoed with three fractional digits, got {}".format(
                resolved["as_of"]
            )
        )

    assert read_item(item_oct["id"])["status"] == "POSTED", (
        "the October item is certified but its effective date has not been reached"
    )
    assert read_item(item_nov["id"])["status"] == "DRAFT", (
        "items remain DRAFT right through submission"
    )
    assert read_schedule(schedule_nov["id"]).get("certified_at") is None, (
        "the November schedule was never certified"
    )


def test_10_posted_price_resolution_orders_candidates_by_effective_date_not_certification(api):
    """PRD §3.7: "Otherwise the resolved item is the candidate with the greatest owning-schedule `effective_date`; ties are broken by the greatest owning-schedule `certified_at`; any remaining tie is broken by the earliest `created_at` — that is, ascending."

    The October schedule is certified first and the September schedule second, so ordering
    by certification time would invert the answer that ordering by effective date gives.

    Design: Corner/calculations/posted_price_resolution_orders_candidates_by_effective_date_not_by_certification_time
    """
    scene = setup_licensee_base(clock="2026-08-01T00:00:00Z")
    wholesaler_id = scene["wholesaler"]["id"]
    program_id = scene["program"]["id"]
    brand_id = scene["brand"]["id"]
    agent_headers = scene["agent_headers"]
    certifier_headers = scene["certifier_headers"]

    schedule_oct = new_schedule(wholesaler_id, program_id, agent_headers, posting_month="2026-10")
    item_oct = new_item(
        schedule_oct["id"],
        brand_id,
        agent_headers,
        size_ml=750,
        bottles_per_case=12,
        case_price_cents=125_000,
        unit_price_cents=12_000,
    )
    submit_schedule(schedule_oct["id"], agent_headers)
    certify_schedule(schedule_oct["id"], certifier_headers)

    set_clock("2026-08-05T00:00:00.000Z")
    schedule_sep = new_schedule(wholesaler_id, program_id, agent_headers, posting_month="2026-09")
    item_sep = new_item(schedule_sep["id"], brand_id, agent_headers, **ITEM_750_12)
    submit_schedule(schedule_sep["id"], agent_headers)
    certify_schedule(schedule_sep["id"], certifier_headers)

    set_clock("2026-10-01T00:00:00.000Z")
    run_posting(program_id)
    set_clock("2026-11-01T00:00:00.000Z")
    run_posting(program_id)

    later = read_posted_price(item_sep["id"], as_of="2026-11-15T00:00:00Z")
    assert later["resolved_item_id"] == item_oct["id"], (
        "as of 2026-11-15 the greatest effective date belongs to the October schedule, "
        "got resolved_item_id {}".format(later["resolved_item_id"])
    )
    assert later["posted_case_price_cents"] == 125_000, (
        "the October price of 125000 wins the later read, got {}".format(
            later["posted_case_price_cents"]
        )
    )
    assert later["posted_unit_price_cents"] == 12_000, (
        "the October unit price of 12000 wins the later read, got {}".format(
            later["posted_unit_price_cents"]
        )
    )

    earlier = read_posted_price(item_sep["id"], as_of="2026-10-15T00:00:00Z")
    assert earlier["resolved_item_id"] == item_sep["id"], (
        "as of 2026-10-15 the October schedule's effective date has not been reached, "
        "got resolved_item_id {}".format(earlier["resolved_item_id"])
    )
    assert earlier["posted_case_price_cents"] == 120_000, (
        "the September price of 120000 wins the earlier read even though it was certified "
        "later, got {}".format(earlier["posted_case_price_cents"])
    )
    assert earlier["posted_unit_price_cents"] == 11_000, (
        "the September unit price of 11000 wins the earlier read, got {}".format(
            earlier["posted_unit_price_cents"]
        )
    )

    assert read_schedule(schedule_sep["id"])["certified_at"] == "2026-08-05T00:00:00.000Z", (
        "the September schedule was certified second"
    )
    assert read_schedule(schedule_oct["id"])["certified_at"] == "2026-08-01T00:00:00.000Z", (
        "the October schedule was certified first"
    )
    assert read_item(item_sep["id"])["status"] == "SUPERSEDED", (
        "the September item has been displaced yet still won the earlier as-of read"
    )


def test_15_combination_cooldown_admits_a_window_starting_exactly_at_the_buffer_end(api):
    """PRD §3.5: "Both comparisons are strict, so a requested window beginning exactly at an existing window's end plus the buffer does not conflict."

    An existing window ending 2026-10-10T00:00:00.000Z widened by the default seven-day
    buffer reaches 2026-10-17T00:00:00.000Z, so a request starting one day earlier
    conflicts and a request starting exactly there does not.

    Design: Corner/calculations/combination_cooldown_admits_a_window_starting_exactly_at_the_buffer_end
    """
    scene = setup_licensee_base(clock="2026-08-01T00:00:00Z")
    setup_draft_schedule(
        scene,
        posting_month="2026-09",
        item_specs=[
            dict(ITEM_750_12),
            {
                "size_ml": 375,
                "bottles_per_case": 6,
                "case_price_cents": 30_000,
                "unit_price_cents": 5_500,
            },
        ],
    )
    members = [scene["items"][0]["id"], scene["items"][1]["id"]]

    first = new_combination(
        scene["schedule"]["id"],
        members,
        140_000,
        scene["agent_headers"],
        promo_starts_at="2026-10-01T00:00:00Z",
        promo_ends_at="2026-10-10T00:00:00Z",
    )

    conflicting = api.create_combination_sale(
        create_combination_sale_payload(
            scene["schedule"]["id"],
            members,
            140_000,
            promo_starts_at="2026-10-16T00:00:00Z",
            promo_ends_at="2026-10-25T00:00:00Z",
        ),
        scene["agent_headers"],
    )
    validate_error(conflicting, "ERR_COMBINATION_COOLDOWN_VIOLATION", 409)

    admitted = validate_success(
        api.create_combination_sale(
            create_combination_sale_payload(
                scene["schedule"]["id"],
                members,
                140_000,
                promo_starts_at="2026-10-17T00:00:00Z",
                promo_ends_at="2026-10-25T00:00:00Z",
            ),
            scene["agent_headers"],
        ),
        201,
    )
    assert admitted["status"] == "ACTIVE", (
        "a new combination sale is ACTIVE, got {}".format(admitted["status"])
    )
    assert admitted["floor_price_cents"] == 150_000, (
        "the floor is the plain sum of member case prices, 120000 plus 30000, got {}".format(
            admitted["floor_price_cents"]
        )
    )
    assert admitted["min_allowed_price_cents"] == 135_000, (
        "a floor of exactly 150000 lands in the ten percent band and yields 135000, "
        "got {}".format(admitted["min_allowed_price_cents"])
    )

    data, meta = validate_paginated(
        api.list_combination_sales(
            regulator_headers(), params={"schedule_id": scene["schedule"]["id"]}
        )
    )
    assert meta["total_count"] == 2, (
        "the refused request created nothing, so exactly two combinations exist, "
        "got total_count {}".format(meta["total_count"])
    )
    for combination in data:
        assert combination["status"] == "ACTIVE", (
            "both surviving combinations are ACTIVE, got {}".format(combination["status"])
        )

    original = [row for row in data if row["id"] == first["id"]][0]
    assert original["promo_starts_at"] == "2026-10-01T00:00:00.000Z", (
        "datetimes are emitted with three fractional digits, got {}".format(
            original["promo_starts_at"]
        )
    )
    assert original["status"] == "ACTIVE", "the pre-existing combination is untouched"


def test_18_amendment_may_match_the_reference_exactly_but_not_equal_or_undercut_bounds(api):
    """PRD §3.6: "And it must not undercut the price being matched: `new_case_price_cents` must be at or above the reference item's current `case_price_cents`, and a value below it is refused with `ERR_AMENDMENT_BELOW_REFERENCE` — matching the reference exactly is permitted."

    Wholesaler A is posted at 120,000 cents and the competitor it matches at 110,000, so
    120,000 is not a reduction, 109,999 undercuts the reference and 110,000 is admissible.

    Design: Corner/calculations/amendment_admissibility_permits_matching_the_reference_exactly_and_refuses_equal_or_lower_than_bounds
    """
    scene = setup_two_wholesalers_certified(
        clock="2026-08-01T00:00:00Z",
        posting_month="2026-09",
        item_a_specs=[dict(ITEM_750_12)],
        item_b_spec={
            "size_ml": 750,
            "bottles_per_case": 12,
            "case_price_cents": 110_000,
            "unit_price_cents": 10_000,
        },
    )
    item_a = scene["items_a"][0]
    reference_id = scene["item_b"]["id"]
    version = read_schedule(scene["schedule_a"]["id"])["version"]

    not_a_reduction = api.create_hold_amendment(
        create_hold_amendment_payload(item_a["id"], reference_id, 120_000, 11_000, version),
        scene["agent_a_headers"],
    )
    validate_error(not_a_reduction, "ERR_AMENDMENT_NOT_A_REDUCTION", 422)

    below_reference = api.create_hold_amendment(
        create_hold_amendment_payload(item_a["id"], reference_id, 109_999, 10_000, version),
        scene["agent_a_headers"],
    )
    validate_error(below_reference, "ERR_AMENDMENT_BELOW_REFERENCE", 422)

    matching = validate_success(
        api.create_hold_amendment(
            create_hold_amendment_payload(item_a["id"], reference_id, 110_000, 10_000, version),
            scene["agent_a_headers"],
        ),
        201,
    )
    assert matching["status"] == "PENDING", (
        "matching the reference exactly is permitted and files a PENDING amendment, "
        "got {}".format(matching["status"])
    )
    assert matching["new_case_price_cents"] == 110_000, (
        "the amendment echoes the matched price 110000, got {}".format(
            matching["new_case_price_cents"]
        )
    )

    data, meta = validate_paginated(
        api.list_hold_amendments(
            regulator_headers(), params={"amending_item_id": item_a["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        "the two refused filings created nothing, got total_count {}".format(
            meta["total_count"]
        )
    )
    assert data[0]["id"] == matching["id"], "the only amendment is the admissible one"

    unchanged = read_item(item_a["id"])
    assert unchanged["case_price_cents"] == 120_000, (
        "a merely pending amendment leaves the item at 120000, got {}".format(
            unchanged["case_price_cents"]
        )
    )
    assert unchanged["amendment_count"] == 0, (
        "amendment_count only moves at acceptance, got {}".format(
            unchanged["amendment_count"]
        )
    )
