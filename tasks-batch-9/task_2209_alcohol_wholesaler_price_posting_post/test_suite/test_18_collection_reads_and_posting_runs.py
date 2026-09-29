"""Collection reads, regulator adjudications, computed reads and the posting run.

Every expectation here is fixed by the PRD: pagination and filter composition (§2.3),
brand rejection and the submission prerequisite (§3.2), body foreign-key resolution
(§2.11), combination floor derivation (§3.5), the posting run and its no-op case (§3.7)
and the two exposure variants (§3.9).
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    certify_schedule,
    collect_audit,
    create_combination_sale_payload,
    create_posting_run_payload,
    new_audit,
    new_filing_agent,
    new_invoice,
    new_invoice_line,
    new_item,
    new_schedule,
    new_wholesaler,
    read_audit,
    read_combination,
    read_item,
    read_schedule,
    read_wholesaler,
    reject_brand_payload,
    regulator_headers,
    run_posting,
    set_clock,
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


def test_01_price_schedule_listing_composes_filters_with_offset_pagination(api):
    """PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more` in the `meta` object, where `total_count` is the number of records matching the filters before the pagination window is applied and `has_more` is `true` exactly when the sum of `offset` and the number of records returned is less than `total_count`."

    Wholesaler A holds three schedules and wholesaler B one, so the wholesaler filter, the
    status filter and the posting-month filter each carve a different subset.

    Design: Corner/endpoints/price_schedule_listing_composes_filters_with_offset_pagination
    """
    scene_a = setup_licensee_base(clock="2026-08-01T00:00:00Z", license_number="W-1001")
    schedule_jul = new_schedule(
        scene_a["wholesaler"]["id"],
        scene_a["program"]["id"],
        scene_a["agent_headers"],
        posting_month="2026-07",
    )
    new_item(
        schedule_jul["id"], scene_a["brand"]["id"], scene_a["agent_headers"], **ITEM_750_12
    )
    submit_schedule(schedule_jul["id"], scene_a["agent_headers"])
    schedule_aug = new_schedule(
        scene_a["wholesaler"]["id"],
        scene_a["program"]["id"],
        scene_a["agent_headers"],
        posting_month="2026-08",
    )
    schedule_sep_a = new_schedule(
        scene_a["wholesaler"]["id"],
        scene_a["program"]["id"],
        scene_a["agent_headers"],
        posting_month="2026-09",
    )

    wholesaler_b = new_wholesaler(
        scene_a["program"]["id"],
        license_number="W-2002",
        legal_name="Gulf Coast Beverage",
    )
    agent_b, agent_b_headers = new_filing_agent(wholesaler_b["id"], "Ben Filer")
    schedule_sep_b = new_schedule(
        wholesaler_b["id"],
        scene_a["program"]["id"],
        agent_b_headers,
        posting_month="2026-09",
    )

    drafts, drafts_meta = validate_paginated(
        api.list_price_schedules(
            regulator_headers(),
            params={"wholesaler_id": scene_a["wholesaler"]["id"], "status": "DRAFT"},
        )
    )
    assert drafts_meta["total_count"] == 2, (
        "wholesaler A holds two DRAFT schedules, got total_count {}".format(
            drafts_meta["total_count"]
        )
    )
    assert drafts_meta["limit"] == 10, (
        "an omitted limit defaults to 10, got {}".format(drafts_meta["limit"])
    )
    assert drafts_meta["offset"] == 0, (
        "an omitted offset defaults to 0, got {}".format(drafts_meta["offset"])
    )
    assert drafts_meta["has_more"] is False, (
        "two of two records were returned, so has_more must be false"
    )
    draft_ids = {row["id"] for row in drafts}
    assert schedule_jul["id"] not in draft_ids, (
        "the submitted July schedule must not satisfy a DRAFT status filter"
    )
    assert draft_ids == {schedule_aug["id"], schedule_sep_a["id"]}, (
        "the DRAFT page must hold exactly the August and September schedules of A"
    )

    page_one, page_one_meta = validate_paginated(
        api.list_price_schedules(
            regulator_headers(),
            params={"wholesaler_id": scene_a["wholesaler"]["id"], "limit": 2, "offset": 0},
        )
    )
    assert len(page_one) == 2, (
        "a limit of 2 returns two records, got {}".format(len(page_one))
    )
    assert page_one_meta["total_count"] == 3, (
        "total_count counts every match before the window, got {}".format(
            page_one_meta["total_count"]
        )
    )
    assert page_one_meta["limit"] == 2, "the echoed limit is 2"
    assert page_one_meta["offset"] == 0, "the echoed offset is 0"
    assert page_one_meta["has_more"] is True, (
        "0 plus 2 is less than 3, so has_more must be true"
    )

    page_two, page_two_meta = validate_paginated(
        api.list_price_schedules(
            regulator_headers(),
            params={"wholesaler_id": scene_a["wholesaler"]["id"], "limit": 2, "offset": 2},
        )
    )
    assert len(page_two) == 1, (
        "the second page holds the single remaining record, got {}".format(len(page_two))
    )
    assert page_two_meta["total_count"] == 3, (
        "total_count is unchanged by the window, got {}".format(
            page_two_meta["total_count"]
        )
    )
    assert page_two_meta["offset"] == 2, "the echoed offset is 2"
    assert page_two_meta["has_more"] is False, (
        "2 plus 1 is not less than 3, so has_more must be false"
    )
    assert {row["id"] for row in page_one} | {row["id"] for row in page_two} == {
        schedule_jul["id"],
        schedule_aug["id"],
        schedule_sep_a["id"],
    }, "the two pages together must cover all three schedules of wholesaler A"

    by_month, by_month_meta = validate_paginated(
        api.list_price_schedules(regulator_headers(), params={"posting_month": "2026-09"})
    )
    assert by_month_meta["total_count"] == 2, (
        "the posting month filter spans both wholesalers, got total_count {}".format(
            by_month_meta["total_count"]
        )
    )
    assert {row["id"] for row in by_month} == {
        schedule_sep_a["id"],
        schedule_sep_b["id"],
    }, "the 2026-09 page must hold one schedule from each wholesaler"


def test_02_brand_reject_records_the_reason_and_a_rejected_brand_still_blocks_submission(api):
    """PRD §3.2: "Rejection moves it from `PENDING` to `REJECTED`, records the supplied `rejection_reason`, and likewise advances the brand's `version` by 1."

    The schedule already carries an item priced against the brand, so the prerequisite of
    §3.2 bites at submission time.

    Design: Corner/endpoints/brand_reject_records_the_reason_and_a_rejected_brand_still_blocks_submission
    """
    scene = setup_licensee_base(
        clock="2026-08-01T00:00:00Z", approve_brand_registration=False
    )
    setup_draft_schedule(scene, posting_month="2026-09", item_specs=[dict(ITEM_750_12)])

    reason = "supplier has no federal basic permit on file"
    rejected = validate_success(
        api.reject_brand(
            scene["brand"]["id"], reject_brand_payload(reason), regulator_headers()
        ),
        200,
    )
    assert rejected["registration_status"] == "REJECTED", (
        "rejection moves the brand from PENDING to REJECTED, got {}".format(
            rejected["registration_status"]
        )
    )
    assert rejected["rejection_reason"] == reason, (
        "the supplied rejection_reason is recorded verbatim, got {!r}".format(
            rejected["rejection_reason"]
        )
    )

    refused = api.submit_price_schedule(scene["schedule"]["id"], scene["agent_headers"])
    validate_error(refused, "ERR_BRAND_NOT_REGISTERED", 409)

    unchanged = read_schedule(scene["schedule"]["id"])
    assert unchanged["status"] == "DRAFT", (
        "a refused filing leaves the schedule in DRAFT, got {}".format(unchanged["status"])
    )
    assert unchanged.get("filed_at") is None, (
        "a refused filing never stamps filed_at"
    )

    data, meta = validate_paginated(
        api.list_brands(
            regulator_headers(),
            params={
                "wholesaler_id": scene["wholesaler"]["id"],
                "registration_status": "REJECTED",
            },
        )
    )
    assert meta["total_count"] == 1, (
        "exactly one rejected brand exists, got total_count {}".format(meta["total_count"])
    )
    assert data[0]["id"] == scene["brand"]["id"], "the rejected brand is the one filed"


def test_03_posting_run_advances_every_eligible_schedule_and_leaves_the_rest_alone(api):
    """PRD §3.7: "The run considers every schedule of that program whose `status` is `POSTED` and whose two temporal gates have both passed: the schedule's `effective_date` must be at or before the current server time, and its `hold_window_ends_at` must be at or before the current server time."

    Two wholesalers of one program have certified September schedules; the same program also
    holds a certified October schedule and a merely submitted November schedule.

    Design: Corner/endpoints/posting_run_is_a_bulk_action_that_advances_every_eligible_schedule_and_leaves_the_rest_alone
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

    schedule_oct = new_schedule(
        scene["wholesaler_a"]["id"],
        scene["program"]["id"],
        scene["agent_a_headers"],
        posting_month="2026-10",
    )
    item_oct = new_item(
        schedule_oct["id"],
        scene["brand_a"]["id"],
        scene["agent_a_headers"],
        size_ml=750,
        bottles_per_case=12,
        case_price_cents=125_000,
        unit_price_cents=12_000,
    )
    submit_schedule(schedule_oct["id"], scene["agent_a_headers"])
    certify_schedule(schedule_oct["id"], scene["certifier_a_headers"])

    schedule_nov = new_schedule(
        scene["wholesaler_a"]["id"],
        scene["program"]["id"],
        scene["agent_a_headers"],
        posting_month="2026-11",
    )
    item_nov = new_item(
        schedule_nov["id"],
        scene["brand_a"]["id"],
        scene["agent_a_headers"],
        size_ml=750,
        bottles_per_case=12,
        case_price_cents=130_000,
        unit_price_cents=13_000,
    )
    submit_schedule(schedule_nov["id"], scene["agent_a_headers"])

    set_clock("2026-10-01T00:00:00.000Z")
    run = validate_success(
        api.create_posting_run(
            create_posting_run_payload(scene["program"]["id"]), regulator_headers()
        ),
        200,
    )
    assert run["state_program_id"] == scene["program"]["id"], (
        "the run echoes the program it swept"
    )
    assert run["run_at"] == "2026-10-01T00:00:00.000Z", (
        "run_at is the current server time, got {}".format(run["run_at"])
    )
    assert run["processed_schedule_count"] == 2, (
        "both September schedules are eligible, got {}".format(
            run["processed_schedule_count"]
        )
    )
    assert run["superseded_schedule_ids"] == [], (
        "nothing was displaced by a first run, got {}".format(
            run["superseded_schedule_ids"]
        )
    )
    assert set(run["effective_schedule_ids"]) == {
        scene["schedule_a"]["id"],
        scene["schedule_b"]["id"],
    }, "the run lists exactly the two September schedules it advanced"

    assert read_schedule(scene["schedule_a"]["id"])["status"] == "EFFECTIVE", (
        "wholesaler A's September schedule is now EFFECTIVE"
    )
    assert read_schedule(scene["schedule_b"]["id"])["status"] == "EFFECTIVE", (
        "wholesaler B's September schedule is now EFFECTIVE"
    )
    assert read_schedule(schedule_oct["id"])["status"] == "POSTED", (
        "the October schedule's effective date has not been reached"
    )
    assert read_schedule(schedule_nov["id"])["status"] == "SUBMITTED", (
        "the November schedule was never certified, so the run ignores it"
    )
    assert read_item(item_oct["id"])["status"] == "POSTED", (
        "the October item stays POSTED until its own schedule is swept"
    )
    assert read_item(item_nov["id"])["status"] == "DRAFT", (
        "items remain DRAFT right through submission"
    )


def test_04_combination_sale_links_two_items_and_a_missing_member_is_reported_not_found(api):
    """PRD §2.11: "The same codes are reused when a foreign key inside a request body fails to resolve at priority 5 — for instance a `state_program_id` that names nothing yields `ERR_STATE_PROGRAM_NOT_FOUND`, a `brand_id` that names nothing yields `ERR_BRAND_NOT_FOUND`, and a member of `member_item_ids` that names nothing yields `ERR_PRICE_SCHEDULE_ITEM_NOT_FOUND`."

    The same two-member declaration that fails on an unresolvable member succeeds once every
    member names a real item of the declared schedule.

    Design: Corner/endpoints/combination_sale_links_two_existing_items_and_a_missing_member_is_reported_not_found
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
    first_item = scene["items"][0]
    second_item = scene["items"][1]

    missing_member = api.create_combination_sale(
        create_combination_sale_payload(
            scene["schedule"]["id"],
            [first_item["id"], NON_EXISTENT_UUID],
            140_000,
            promo_starts_at="2026-10-01T00:00:00Z",
            promo_ends_at="2026-10-10T00:00:00Z",
        ),
        scene["agent_headers"],
    )
    validate_error(missing_member, "ERR_PRICE_SCHEDULE_ITEM_NOT_FOUND", 404)

    created = validate_success(
        api.create_combination_sale(
            create_combination_sale_payload(
                scene["schedule"]["id"],
                [first_item["id"], second_item["id"]],
                140_000,
                promo_starts_at="2026-10-01T00:00:00Z",
                promo_ends_at="2026-10-10T00:00:00Z",
            ),
            scene["agent_headers"],
        ),
        201,
    )
    assert created["member_item_ids"] == [first_item["id"], second_item["id"]], (
        "the combination echoes both member identifiers, got {}".format(
            created["member_item_ids"]
        )
    )
    assert created["floor_price_cents"] == 150_000, (
        "the floor is the plain sum of member case prices, got {}".format(
            created["floor_price_cents"]
        )
    )
    assert created["min_allowed_price_cents"] == 135_000, (
        "a floor of 150000 lands in the ten percent band and yields 135000, got {}".format(
            created["min_allowed_price_cents"]
        )
    )

    fetched = read_combination(created["id"])
    assert fetched["member_item_ids"] == [first_item["id"], second_item["id"]], (
        "a read-back reports the same members"
    )
    assert fetched["status"] == "ACTIVE", (
        "a new combination sale is ACTIVE, got {}".format(fetched["status"])
    )

    data, meta = validate_paginated(
        api.list_combination_sales(
            regulator_headers(), params={"schedule_id": scene["schedule"]["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        "the refused declaration created nothing, got total_count {}".format(
            meta["total_count"]
        )
    )
    assert data[0]["id"] == created["id"], "the only combination is the successful one"


def test_05_penalty_exposure_computed_read_is_side_effect_free_across_both_variants(api):
    """PRD §3.9: "The response reports the `wholesaler_id`, the `variant` actually applied, the `accrued_cents`, the `provisional_cents` (which is 0 under `assessed_exposure`) and the resulting `exposure_cents`, all three amounts being integers."

    The wholesaler carries one accrued late filing penalty of 250,000 cents and one collected
    audit worth 4,000 cents of projected penalty, and per §2.5 a record whose stored fields
    are not changed by a request keeps its `version` untouched.

    Design: Corner/endpoints/penalty_exposure_computed_read_is_side_effect_free_across_both_variants
    """
    scene = setup_licensee_base(clock="2026-08-11T00:00:00Z")
    schedule = new_schedule(
        scene["wholesaler"]["id"],
        scene["program"]["id"],
        scene["agent_headers"],
        posting_month="2026-08",
    )
    item = new_item(
        schedule["id"], scene["brand"]["id"], scene["agent_headers"], **ITEM_750_12
    )
    filed = submit_schedule(schedule["id"], scene["agent_headers"])
    assert filed["is_late"] is True, (
        "a 2026-08 schedule filed on 2026-08-11 is past the 2026-08-10T23:59:59.999Z deadline"
    )
    certify_schedule(schedule["id"], scene["certifier_headers"])

    set_clock("2026-09-15T00:00:00.000Z")
    run_posting(scene["program"]["id"])

    invoice = new_invoice(
        scene["wholesaler"]["id"], "2026-09-20T00:00:00Z", scene["agent_headers"]
    )
    new_invoice_line(
        invoice["id"], item["id"], 115_000, 11_000, scene["agent_headers"], cases_quantity=2
    )
    flagged = validate_success(
        api.validate_retailer_invoice(invoice["id"], scene["agent_headers"]), 200
    )
    assert flagged["validation_status"] == "FLAGGED", (
        "the line was charged below the posted price, got {}".format(
            flagged["validation_status"]
        )
    )

    audit = new_audit(scene["wholesaler"]["id"], scene["program"]["id"], "2026-09")
    collect_audit(audit["id"])
    version_before = read_wholesaler(scene["wholesaler"]["id"])["version"]

    assessed_read = validate_success(
        api.get_penalty_exposure(scene["wholesaler"]["id"], regulator_headers()), 200
    )
    assert assessed_read["variant"] == "assessed_exposure", (
        "an omitted variant reads assessed_exposure, got {}".format(
            assessed_read["variant"]
        )
    )
    assert assessed_read["accrued_cents"] == 250_000, (
        "one late filing accrued 250000 cents, got {}".format(
            assessed_read["accrued_cents"]
        )
    )
    assert assessed_read["provisional_cents"] == 0, (
        "provisional_cents is 0 under assessed_exposure, got {}".format(
            assessed_read["provisional_cents"]
        )
    )
    assert assessed_read["exposure_cents"] == 250_000, (
        "assessed exposure reports the accrued figure and nothing more, got {}".format(
            assessed_read["exposure_cents"]
        )
    )

    provisional_read = validate_success(
        api.get_penalty_exposure(
            scene["wholesaler"]["id"],
            regulator_headers(),
            params={"variant": "provisional_exposure"},
        ),
        200,
    )
    assert provisional_read["variant"] == "provisional_exposure", (
        "the requested variant is echoed, got {}".format(provisional_read["variant"])
    )
    assert provisional_read["accrued_cents"] == 250_000, (
        "both variants begin from the same accrued figure, got {}".format(
            provisional_read["accrued_cents"]
        )
    )
    assert provisional_read["provisional_cents"] == 4_000, (
        "the collected audit's 10000 cent finding projects 4000 cents, got {}".format(
            provisional_read["provisional_cents"]
        )
    )
    assert provisional_read["exposure_cents"] == 254_000, (
        "provisional exposure is 250000 plus 4000, got {}".format(
            provisional_read["exposure_cents"]
        )
    )

    after = read_wholesaler(scene["wholesaler"]["id"])
    assert after["version"] == version_before, (
        "a computed read must not advance the wholesaler's version, {} became {}".format(
            version_before, after["version"]
        )
    )
    assert after["penalty_exposure_cents"] == 250_000, (
        "the stored penalty_exposure_cents equals the assessed variant, got {}".format(
            after["penalty_exposure_cents"]
        )
    )

    audit_after = read_audit(audit["id"])
    assert audit_after["status"] == "COLLECTED", (
        "reading exposure does not assess the audit, got {}".format(audit_after["status"])
    )
    assert audit_after["penalty_assessed_cents"] == 0, (
        "an unassessed audit has assessed nothing, got {}".format(
            audit_after["penalty_assessed_cents"]
        )
    )


def test_06_posting_run_advances_only_reached_effective_dates_and_repeats_as_a_no_op(api):
    """PRD §3.7: "A run that finds nothing eligible succeeds with a `processed_schedule_count` of 0 and two empty arrays."

    Both schedules are certified on the same day, so only the calendar decides which run
    sweeps which, and a second run at the same instant has nothing left to do.

    Design: Corner/endpoints/posting_run_advances_only_reached_effective_dates_and_a_second_run_at_the_same_instant_is_a_no_op
    """
    scene = setup_licensee_base(clock="2026-08-01T00:00:00Z")
    schedule_sep = new_schedule(
        scene["wholesaler"]["id"],
        scene["program"]["id"],
        scene["agent_headers"],
        posting_month="2026-09",
    )
    new_item(schedule_sep["id"], scene["brand"]["id"], scene["agent_headers"], **ITEM_750_12)
    submit_schedule(schedule_sep["id"], scene["agent_headers"])
    certify_schedule(schedule_sep["id"], scene["certifier_headers"])

    schedule_oct = new_schedule(
        scene["wholesaler"]["id"],
        scene["program"]["id"],
        scene["agent_headers"],
        posting_month="2026-10",
    )
    new_item(
        schedule_oct["id"],
        scene["brand"]["id"],
        scene["agent_headers"],
        size_ml=750,
        bottles_per_case=12,
        case_price_cents=125_000,
        unit_price_cents=12_000,
    )
    submit_schedule(schedule_oct["id"], scene["agent_headers"])
    certify_schedule(schedule_oct["id"], scene["certifier_headers"])

    set_clock("2026-10-01T00:00:00.000Z")
    first_run = validate_success(
        api.create_posting_run(
            create_posting_run_payload(scene["program"]["id"]), regulator_headers()
        ),
        200,
    )
    assert first_run["processed_schedule_count"] == 1, (
        "only the September schedule's effective date has been reached, got {}".format(
            first_run["processed_schedule_count"]
        )
    )
    assert first_run["effective_schedule_ids"] == [schedule_sep["id"]], (
        "the first run advances the September schedule alone, got {}".format(
            first_run["effective_schedule_ids"]
        )
    )
    assert first_run["superseded_schedule_ids"] == [], (
        "there was no earlier effective schedule to displace"
    )
    version_after_first = read_schedule(schedule_sep["id"])["version"]

    second_run = validate_success(
        api.create_posting_run(
            create_posting_run_payload(scene["program"]["id"]), regulator_headers()
        ),
        200,
    )
    assert second_run["processed_schedule_count"] == 0, (
        "a repeated run at the same instant finds nothing eligible, got {}".format(
            second_run["processed_schedule_count"]
        )
    )
    assert second_run["effective_schedule_ids"] == [], (
        "a no-op run reports an empty effective array, got {}".format(
            second_run["effective_schedule_ids"]
        )
    )
    assert second_run["superseded_schedule_ids"] == [], (
        "a no-op run reports an empty superseded array, got {}".format(
            second_run["superseded_schedule_ids"]
        )
    )
    unchanged = read_schedule(schedule_sep["id"])
    assert unchanged["version"] == version_after_first, (
        "a no-op run must not touch the schedule, version {} became {}".format(
            version_after_first, unchanged["version"]
        )
    )
    assert unchanged["status"] == "EFFECTIVE", (
        "the already effective schedule stays EFFECTIVE, got {}".format(
            unchanged["status"]
        )
    )

    set_clock("2026-11-01T00:00:00.000Z")
    third_run = validate_success(
        api.create_posting_run(
            create_posting_run_payload(scene["program"]["id"]), regulator_headers()
        ),
        200,
    )
    assert third_run["processed_schedule_count"] == 1, (
        "the October schedule becomes eligible on 2026-11-01, got {}".format(
            third_run["processed_schedule_count"]
        )
    )
    assert third_run["effective_schedule_ids"] == [schedule_oct["id"]], (
        "the third run advances the October schedule, got {}".format(
            third_run["effective_schedule_ids"]
        )
    )
    assert third_run["superseded_schedule_ids"] == [schedule_sep["id"]], (
        "the displaced September schedule is reported as superseded, got {}".format(
            third_run["superseded_schedule_ids"]
        )
    )

    assert read_schedule(schedule_oct["id"])["status"] == "EFFECTIVE", (
        "the October schedule is now EFFECTIVE"
    )
    displaced = read_schedule(schedule_sep["id"])
    assert displaced["status"] == "SUPERSEDED", (
        "every item of the September schedule was displaced, got {}".format(
            displaced["status"]
        )
    )
    assert displaced["superseded_by_schedule_id"] == schedule_oct["id"], (
        "the displacing schedule is recorded, got {}".format(
            displaced["superseded_by_schedule_id"]
        )
    )
