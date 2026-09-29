"""Resource shapes, derived counters and the append-only ledger records.

Every test here asserts a rule stated verbatim in the PRD sentence quoted in
its docstring: the server-minted counters of a freshly registered party, the
stored-plus-derived shape of a bank read, the filtered and paginated list
reads, the per-collection not-found codes, the schema-validation rejections,
the declared defaults, and the immutability of the two append-only event
records (prospectus votes and credit ledger entries).
"""

from datetime import datetime

from test_helpers import (
    ApiErrorId,
    CLOCK_EPOCH,
    api_client,
    assert_bank,
    assert_cents,
    assert_credits,
    assert_irt_member,
    assert_ledger_entry,
    assert_ledger_sequence,
    assert_ledger_shape,
    assert_permittee,
    assert_prospectus,
    assert_prospectus_vote,
    assert_sponsor,
    bank_state,
    cancel_sale_payload,
    create_bank_payload,
    create_irt_member_payload,
    create_milestone_payload,
    create_permittee_payload,
    create_prospectus_payload,
    create_sponsor_payload,
    get_success_data,
    make_irt_chair_headers,
    make_program_admin_headers,
    make_sponsor_headers,
    quote_credits,
    register_sponsor,
    reserve_sale,
    set_clock,
    setup_draft_bank,
    setup_sellable_bank,
    validate_error,
    validate_paginated,
    validate_success,
)

# No row of any kind is ever created under this identifier.
NON_EXISTENT_ID = "00000000-0000-0000-0000-000000000000"

OBJECTIVE_SUMMARY = "Restore 205 acres of depressional wetland"


def _instant(timestamp: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into a comparable instant."""
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


def test_new_sponsor_stamps_zero_bank_count_and_good_standing():
    """Registration mints the sponsor's two derived properties itself.

    PRD §3.1: "Two sponsor properties are derived rather than supplied: `banks_count`, the number of bank rows naming this sponsor, counted across every bank status without exception and initialised to 0; and `good_standing`, a boolean that is true precisely when the sponsor owns no bank in `SUSPENDED` status, and therefore initialised to true."
    PRD §2.4: "`version` is an integer that begins at 1 and increments by exactly 1 on every mutation of the row; it is the token the optimistic-concurrency machinery of §2.7 is built on."

    Design: Corner/entities/sponsor_and_permittee_creation_stamps_derived_counters
    """
    set_clock(CLOCK_EPOCH)

    response = api_client.create_sponsor(
        create_sponsor_payload(
            legal_name="Cypress Bend Mitigation LLC",
            legal_entity_type="PRIVATE_ENTREPRENEURIAL",
            performance_bond_cents=30_000_000,
        ),
        make_program_admin_headers(),
    )
    sponsor = validate_success(response, 201)
    assert_sponsor(sponsor)

    assert sponsor["banks_count"] == 0, (
        f"a sponsor naming no bank rows reports banks_count 0, got {sponsor['banks_count']}"
    )
    assert sponsor["good_standing"] is True, (
        "good_standing is initialised to true because no bank is SUSPENDED"
    )
    assert_cents(sponsor["performance_bond_cents"], 30_000_000, "performance_bond_cents")
    assert sponsor["version"] == 1, (
        f"version begins at 1 on the first write, got {sponsor['version']}"
    )


def test_new_permittee_stamps_zero_escrow_and_full_unmet_requirement():
    """A permit holder's four fiscal counters are derived, never supplied.

    PRD §3.1: "`deposited_cents` accumulates every escrow deposit ever recorded and starts at 0."
    PRD §3.1: "`escrow_balance_cents` is the deposited total minus the sum of the settled prices of all of this holder's sales standing in `EXECUTED` or `ASSIGNED` status, and likewise starts at 0."
    PRD §3.1: "`assigned_credits` is the total requested-credit quantity across this holder's sales standing in `ASSIGNED` status, starting at 0."
    PRD §3.1: "`unmet_requirement_credits` is the required credits minus the assigned credits, floored at zero so it can never go negative, carried to 2 decimal places, and therefore equal to the required credits at registration."

    Design: Corner/entities/sponsor_and_permittee_creation_stamps_derived_counters
    """
    set_clock(CLOCK_EPOCH)

    response = api_client.create_permittee(
        create_permittee_payload(
            organization_name="Delta Logistics Park",
            permit_number="COE-2026-00417",
            impact_huc8_code="03130002",
            required_credits=20.00,
        ),
        make_program_admin_headers(),
    )
    permittee = validate_success(response, 201)
    assert_permittee(permittee)

    assert_cents(permittee["deposited_cents"], 0, "deposited_cents at registration")
    assert_cents(permittee["escrow_balance_cents"], 0, "escrow_balance_cents at registration")
    assert_credits(permittee["assigned_credits"], 0.00, "assigned_credits at registration")
    assert_credits(permittee["required_credits"], 20.00, "required_credits")
    assert_credits(
        permittee["unmet_requirement_credits"],
        20.00,
        "unmet_requirement_credits equals required_credits at registration",
    )


def test_bank_read_returns_stored_inputs_plus_every_derived_field():
    """The single-resource bank read carries the stored site definition, the
    capitalised stewardship requirement and the frozen opening posture.

    PRD §3.2: "A newly registered bank opens in `DRAFT` status with a `sales_posture` of `FROZEN`, and every credit aggregate — `total_authorized_credits`, `credits_released`, `credits_sold`, `credits_on_hold` and `credits_available` — initialised to 0.00."
    PRD §3.2: "Its `easement_recorded` flag is false with `easement_recorded_at` and `easement_deed_reference` both null; its `stewardship_funded_cents`, `deferral_count` and `open_quote_count` are 0; and `instrument_executed_at` and `closed_at` are null."
    PRD §3.2: "The calculation capitalises the annual stewardship cost at a non-wasting payout rate of 3.75 percent: the base endowment is the annual stewardship cost divided by 0.0375, rounded **up** to the next whole cent whatever the remainder."
    PRD §3.2: "An administrative fee of 1.50 percent of that base endowment is then computed and rounded half up to whole cents. The required endowment is the base endowment plus the administrative fee."
    PRD §3.2: "Registration also raises the owning sponsor's bank count by one."

    Design: Corner/entities/bank_creation_and_retrieval_returns_stored_and_derived_state
    """
    set_clock(CLOCK_EPOCH)
    world = setup_draft_bank(
        site_huc8_code="03130002",
        service_area_huc8_codes=["03130002", "03130003"],
        hgm_class="DEPRESSIONAL",
        annual_stewardship_cost_cents=4_200_000,
    )

    bank = validate_success(
        api_client.get_bank(world["bank"]["id"], world["sponsor_headers"]), 200
    )
    assert_bank(bank)

    assert bank["status"] == "DRAFT", f"a newly registered bank opens in DRAFT, got {bank['status']}"
    assert bank["sales_posture"] == "FROZEN", (
        f"a DRAFT bank's posture is FROZEN, got {bank['sales_posture']}"
    )
    assert_cents(
        bank["stewardship_required_cents"],
        113_680_000,
        "stewardship_required_cents capitalised from 4200000",
    )
    assert_cents(bank["stewardship_funded_cents"], 0, "stewardship_funded_cents")
    assert_credits(bank["total_authorized_credits"], 0.00, "total_authorized_credits")
    assert_credits(bank["credits_released"], 0.00, "credits_released")
    assert_credits(bank["credits_sold"], 0.00, "credits_sold")
    assert_credits(bank["credits_on_hold"], 0.00, "credits_on_hold")
    assert_credits(bank["credits_available"], 0.00, "credits_available")
    assert bank["easement_recorded"] is False, "easement_recorded opens false"
    assert bank["easement_recorded_at"] is None, "easement_recorded_at opens null"
    assert bank["easement_deed_reference"] is None, "easement_deed_reference opens null"
    assert bank["deferral_count"] == 0, "deferral_count opens at 0"
    assert bank["open_quote_count"] == 0, "open_quote_count opens at 0"
    assert bank["instrument_executed_at"] is None, "instrument_executed_at opens null"
    assert bank["closed_at"] is None, "closed_at opens null"
    assert bank["site_huc8_code"] == "03130002", "the stored site watershed is returned unchanged"
    assert bank["service_area_huc8_codes"] == ["03130002", "03130003"], (
        f"the stored service area is returned unchanged, got {bank['service_area_huc8_codes']}"
    )
    assert bank["hgm_class"] == "DEPRESSIONAL", "the stored hydrogeomorphic class is returned"
    assert_cents(
        bank["annual_stewardship_cost_cents"], 4_200_000, "annual_stewardship_cost_cents"
    )

    sponsor = validate_success(
        api_client.get_sponsor(world["sponsor"]["id"], make_program_admin_headers()), 200
    )
    assert sponsor["banks_count"] == 1, (
        f"registering one bank raises the sponsor's bank count to 1, got {sponsor['banks_count']}"
    )


def _two_sponsor_bank_world():
    """Sponsor A owning two bank sites and sponsor B owning one."""
    set_clock(CLOCK_EPOCH)
    sponsor_a = register_sponsor(
        legal_name="Cypress Bend Mitigation LLC",
        legal_entity_type="PRIVATE_ENTREPRENEURIAL",
        performance_bond_cents=30_000_000,
    )
    sponsor_b = register_sponsor(
        legal_name="Blackwater Restoration Trust",
        legal_entity_type="NGO",
        performance_bond_cents=30_000_000,
    )
    headers_a = make_sponsor_headers(sponsor_a["id"])
    headers_b = make_sponsor_headers(sponsor_b["id"])

    bank_a1 = get_success_data(
        api_client.create_bank(
            create_bank_payload(
                sponsor_a["id"],
                site_name="Cypress Bend",
                site_huc8_code="03130002",
                service_area_huc8_codes=["03130002", "03130003"],
                hgm_class="DEPRESSIONAL",
                annual_stewardship_cost_cents=4_200_000,
            ),
            headers_a,
        )
    )
    bank_a2 = get_success_data(
        api_client.create_bank(
            create_bank_payload(
                sponsor_a["id"],
                site_name="Cypress Bend North",
                site_huc8_code="03130003",
                service_area_huc8_codes=["03130003"],
                hgm_class="RIVERINE",
                annual_stewardship_cost_cents=3_000_000,
            ),
            headers_a,
        )
    )
    bank_b1 = get_success_data(
        api_client.create_bank(
            create_bank_payload(
                sponsor_b["id"],
                site_name="Blackwater Flats",
                site_huc8_code="03140101",
                service_area_huc8_codes=["03140101"],
                hgm_class="FLATS",
                annual_stewardship_cost_cents=2_000_000,
            ),
            headers_b,
        )
    )
    return sponsor_a, sponsor_b, bank_a1, bank_a2, bank_b1


def test_bank_listing_paginates_inside_the_sponsor_filter():
    """A one-row page over a two-row sponsor filter reports the pre-pagination
    total and walks both rows without ever leaking the other sponsor's bank.

    PRD §2.3: "Four pagination fields accompany every list response inside `meta`: the echoed `limit`, the echoed `offset`, `total_count` carrying the number of rows matching the filter before pagination is applied, and `has_more` indicating whether any rows remain beyond the current page."
    PRD §3.9: "Banks may be filtered by `sponsor_id`, by `status` and by `sales_posture`."

    Design: Corner/entities/banks_listing_filters_by_sponsor_and_paginates
    """
    sponsor_a, _sponsor_b, bank_a1, bank_a2, bank_b1 = _two_sponsor_bank_world()
    admin_headers = make_program_admin_headers()

    first_rows, first_meta = validate_paginated(
        api_client.list_banks(
            admin_headers, params={"sponsor_id": sponsor_a["id"], "limit": 1, "offset": 0}
        )
    )
    assert first_meta["total_count"] == 2, (
        f"sponsor A owns two banks before pagination, got {first_meta['total_count']}"
    )
    assert first_meta["has_more"] is True, "one row of two leaves a further row beyond the page"
    assert first_meta["limit"] == 1, "limit is echoed back"
    assert first_meta["offset"] == 0, "offset is echoed back"
    assert len(first_rows) == 1, f"limit 1 returns exactly one row, got {len(first_rows)}"

    second_rows, second_meta = validate_paginated(
        api_client.list_banks(
            admin_headers, params={"sponsor_id": sponsor_a["id"], "limit": 1, "offset": 1}
        )
    )
    assert second_meta["total_count"] == 2, (
        f"total_count ignores the offset, got {second_meta['total_count']}"
    )
    assert second_meta["has_more"] is False, "the second of two rows leaves nothing beyond it"
    assert len(second_rows) == 1, f"limit 1 returns exactly one row, got {len(second_rows)}"

    paged_ids = [first_rows[0]["id"], second_rows[0]["id"]]
    assert paged_ids[0] != paged_ids[1], "the two pages return different bank rows"
    assert set(paged_ids) == {bank_a1["id"], bank_a2["id"]}, (
        "the two pages together cover exactly sponsor A's two banks"
    )
    assert bank_b1["id"] not in paged_ids, "sponsor B's bank never appears under sponsor A's filter"


def test_bank_listing_by_status_spans_every_sponsor():
    """The status filter is independent of the sponsor filter: all three DRAFT
    banks are returned, and each sponsor's own bank count stays exact.

    PRD §3.9: "Banks may be filtered by `sponsor_id`, by `status` and by `sales_posture`."
    PRD §3.1: "Two sponsor properties are derived rather than supplied: `banks_count`, the number of bank rows naming this sponsor, counted across every bank status without exception and initialised to 0; and `good_standing`, a boolean that is true precisely when the sponsor owns no bank in `SUSPENDED` status, and therefore initialised to true."

    Design: Corner/entities/banks_listing_filters_by_sponsor_and_paginates
    """
    sponsor_a, sponsor_b, bank_a1, bank_a2, bank_b1 = _two_sponsor_bank_world()
    admin_headers = make_program_admin_headers()

    rows, meta = validate_paginated(
        api_client.list_banks(admin_headers, params={"status": "DRAFT", "limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 3, (
        f"all three banks stand in DRAFT, got total_count {meta['total_count']}"
    )
    assert meta["has_more"] is False, "three rows fit inside a page of ten"
    assert len(rows) == 3, f"three DRAFT rows are returned, got {len(rows)}"
    assert {row["id"] for row in rows} == {bank_a1["id"], bank_a2["id"], bank_b1["id"]}, (
        "the DRAFT listing spans both sponsors"
    )

    refreshed_a = validate_success(api_client.get_sponsor(sponsor_a["id"], admin_headers), 200)
    refreshed_b = validate_success(api_client.get_sponsor(sponsor_b["id"], admin_headers), 200)
    assert refreshed_a["banks_count"] == 2, (
        f"sponsor A names two bank rows, got {refreshed_a['banks_count']}"
    )
    assert refreshed_b["banks_count"] == 1, (
        f"sponsor B names one bank row, got {refreshed_b['banks_count']}"
    )


def test_each_collection_returns_its_own_not_found_code():
    """The same non-existent identifier yields ten distinct 404 codes, one per
    collection, never a single generic one.

    PRD §2.10: "Next, every identifier embedded in the request path is resolved left to right, each returning its own not-found code: `ERR_SPONSOR_NOT_FOUND`, `ERR_PERMITTEE_NOT_FOUND`, `ERR_IRT_MEMBER_NOT_FOUND`, `ERR_BANK_NOT_FOUND`, `ERR_PROSPECTUS_NOT_FOUND`, `ERR_WORK_PLAN_NOT_FOUND`, `ERR_MILESTONE_NOT_FOUND`, `ERR_MONITORING_REPORT_NOT_FOUND`, `ERR_REMEDIAL_ACTION_NOT_FOUND` or `ERR_CREDIT_SALE_NOT_FOUND`."

    Design: Corner/entities/unknown_ids_return_entity_specific_not_found_errors
    """
    set_clock(CLOCK_EPOCH)
    admin_headers = make_program_admin_headers()

    validate_error(
        api_client.get_sponsor(NON_EXISTENT_ID, admin_headers),
        ApiErrorId.ERR_SPONSOR_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_permittee(NON_EXISTENT_ID, admin_headers),
        ApiErrorId.ERR_PERMITTEE_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_irt_member(NON_EXISTENT_ID, admin_headers),
        ApiErrorId.ERR_IRT_MEMBER_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_bank(NON_EXISTENT_ID, admin_headers),
        ApiErrorId.ERR_BANK_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_prospectus(NON_EXISTENT_ID, admin_headers),
        ApiErrorId.ERR_PROSPECTUS_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.submit_work_plan(NON_EXISTENT_ID, make_sponsor_headers(NON_EXISTENT_ID)),
        ApiErrorId.ERR_WORK_PLAN_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_milestone(NON_EXISTENT_ID, admin_headers),
        ApiErrorId.ERR_MILESTONE_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_monitoring_report(NON_EXISTENT_ID, admin_headers),
        ApiErrorId.ERR_MONITORING_REPORT_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_remedial_action(NON_EXISTENT_ID, admin_headers),
        ApiErrorId.ERR_REMEDIAL_ACTION_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_credit_sale(NON_EXISTENT_ID, admin_headers),
        ApiErrorId.ERR_CREDIT_SALE_NOT_FOUND,
        404,
    )


def test_bank_creation_rejects_each_omitted_required_field_and_creates_nothing():
    """Omitting site_name, site_huc8_code or annual_stewardship_cost_cents is a
    schema breach rather than a silent default, and no bank row survives it.

    PRD §3.2: "A sponsor opens a bank site by registering it under its own `sponsor_id`, together with a `site_name`, the `site_huc8_code` of the watershed the site physically occupies, the `service_area_huc8_codes` list defining where credits from this bank may be sold, the site's `hgm_class`, and its `annual_stewardship_cost_cents`."
    PRD §2.10: "Schema validation follows: required fields present, JSON types correct, enum members recognised, HUC-8 codes matching exactly eight decimal digits, credit quantities strictly positive with at most 2 decimal places, cent amounts non-negative integers, a release percentage greater than zero and no greater than one, `limit` within 1 through 100, `offset` non-negative, `window_end` strictly after `window_start`, a non-empty credit-strata array with no repeated stratum code, and a measurements array with no repeated standard code — any breach yields `ERR_INVALID_REQUEST`."

    Design: Corner/entities/bank_creation_missing_required_fields_rejected
    """
    set_clock(CLOCK_EPOCH)
    sponsor = register_sponsor(
        legal_name="Cypress Bend Mitigation LLC",
        legal_entity_type="PRIVATE_ENTREPRENEURIAL",
        performance_bond_cents=30_000_000,
    )
    sponsor_headers = make_sponsor_headers(sponsor["id"])

    validate_error(
        api_client.create_bank(
            {
                "sponsor_id": sponsor["id"],
                "site_huc8_code": "03130002",
                "service_area_huc8_codes": ["03130002"],
                "hgm_class": "DEPRESSIONAL",
                "annual_stewardship_cost_cents": 4_200_000,
            },
            sponsor_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api_client.create_bank(
            {
                "sponsor_id": sponsor["id"],
                "site_name": "Cypress Bend",
                "service_area_huc8_codes": ["03130002"],
                "hgm_class": "DEPRESSIONAL",
                "annual_stewardship_cost_cents": 4_200_000,
            },
            sponsor_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api_client.create_bank(
            {
                "sponsor_id": sponsor["id"],
                "site_name": "Cypress Bend",
                "site_huc8_code": "03130002",
                "service_area_huc8_codes": ["03130002"],
                "hgm_class": "DEPRESSIONAL",
            },
            sponsor_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )

    _rows, meta = validate_paginated(
        api_client.list_banks(
            make_program_admin_headers(),
            params={"sponsor_id": sponsor["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 0, (
        f"three rejected registrations create no bank row, got {meta['total_count']}"
    )

    refreshed = validate_success(
        api_client.get_sponsor(sponsor["id"], make_program_admin_headers()), 200
    )
    assert refreshed["banks_count"] == 0, (
        f"the sponsor still names no bank row, got {refreshed['banks_count']}"
    )


def test_omitted_optional_inputs_fall_back_to_declared_defaults():
    """An omitted bond becomes 0, an omitted roster status becomes SEATED, and a
    fresh prospectus opens on round 1 with all three tallies at zero.

    PRD §3.1: "A `performance_bond_cents` figure may be supplied at registration to record the performance assurance the sponsor has posted; it must not be negative, and when it is omitted it defaults to 0."
    PRD §3.1: "A member's `roster_status` is either `SEATED` or `RECUSED` and defaults to `SEATED` when not supplied."
    PRD §3.3: "A prospectus opens in `DRAFT` status with `revision_round` stamped at 1, all three vote tallies at 0, `veto_recorded` false, and `submitted_at`, `review_opened_at`, `decision_recorded_by` and `decided_at` all null."

    Design: Corner/entities/optional_inputs_fall_back_to_declared_defaults
    """
    set_clock(CLOCK_EPOCH)
    admin_headers = make_program_admin_headers()

    sponsor = validate_success(
        api_client.create_sponsor(
            {
                "legal_name": "Cypress Bend Mitigation LLC",
                "legal_entity_type": "PRIVATE_ENTREPRENEURIAL",
            },
            admin_headers,
        ),
        201,
    )
    assert_sponsor(sponsor)
    assert_cents(
        sponsor["performance_bond_cents"], 0, "an omitted performance_bond_cents defaults to 0"
    )

    member = validate_success(
        api_client.create_irt_member(
            create_irt_member_payload(member_name="R. Alvarez", agency="USACE"), admin_headers
        ),
        201,
    )
    assert_irt_member(member)
    assert member["roster_status"] == "SEATED", (
        f"an omitted roster_status defaults to SEATED, got {member['roster_status']}"
    )

    sponsor_headers = make_sponsor_headers(sponsor["id"])
    bank = get_success_data(
        api_client.create_bank(
            create_bank_payload(
                sponsor["id"],
                site_name="Cypress Bend",
                site_huc8_code="03130002",
                service_area_huc8_codes=["03130002"],
                hgm_class="DEPRESSIONAL",
                annual_stewardship_cost_cents=4_200_000,
            ),
            sponsor_headers,
        )
    )

    prospectus = validate_success(
        api_client.create_prospectus(
            create_prospectus_payload(
                bank["id"], objective_summary=OBJECTIVE_SUMMARY, proposed_credits=98.77
            ),
            sponsor_headers,
        ),
        201,
    )
    assert_prospectus(prospectus)
    assert prospectus["status"] == "DRAFT", (
        f"a prospectus opens in DRAFT, got {prospectus['status']}"
    )
    assert prospectus["revision_round"] == 1, (
        f"revision_round is stamped at 1, got {prospectus['revision_round']}"
    )
    assert prospectus["concur_count"] == 0, "the concur tally opens at 0"
    assert prospectus["object_count"] == 0, "the object tally opens at 0"
    assert prospectus["abstain_count"] == 0, "the abstain tally opens at 0"
    assert prospectus["veto_recorded"] is False, "veto_recorded opens false"


def test_veto_authority_and_unmet_requirement_are_computed_not_supplied():
    """Veto authority follows from the agency alone, and a brand-new permit
    holder's unmet obligation equals its required credits.

    PRD §3.1: "The `veto_authority` flag is derived, never supplied: it is true precisely when the member's agency is `USACE`, because the chartering agency alone holds veto power over a prospectus."
    PRD §3.1: "`unmet_requirement_credits` is the required credits minus the assigned credits, floored at zero so it can never go negative, carried to 2 decimal places, and therefore equal to the required credits at registration."

    Design: Corner/entities/computed_fields_are_derived_from_inputs_not_supplied_values
    """
    set_clock(CLOCK_EPOCH)
    admin_headers = make_program_admin_headers()

    corps = validate_success(
        api_client.create_irt_member(
            create_irt_member_payload(member_name="R. Alvarez", agency="USACE"), admin_headers
        ),
        201,
    )
    epa = validate_success(
        api_client.create_irt_member(
            create_irt_member_payload(member_name="T. Nakamura", agency="EPA"), admin_headers
        ),
        201,
    )
    deq = validate_success(
        api_client.create_irt_member(
            create_irt_member_payload(member_name="L. Okonkwo", agency="STATE_DEQ"), admin_headers
        ),
        201,
    )
    for member in (corps, epa, deq):
        assert_irt_member(member)

    assert corps["veto_authority"] is True, "the USACE seat holds veto authority"
    assert epa["veto_authority"] is False, "the EPA seat holds no veto authority"
    assert deq["veto_authority"] is False, "the STATE_DEQ seat holds no veto authority"

    permittee = validate_success(
        api_client.create_permittee(
            create_permittee_payload(
                organization_name="Delta Logistics Park",
                permit_number="COE-2026-00417",
                impact_huc8_code="03130002",
                required_credits=7.25,
            ),
            admin_headers,
        ),
        201,
    )
    assert_permittee(permittee)
    assert_credits(permittee["required_credits"], 7.25, "required_credits")
    assert_credits(permittee["assigned_credits"], 0.00, "assigned_credits at registration")
    assert_credits(
        permittee["unmet_requirement_credits"],
        7.25,
        "unmet_requirement_credits equals required_credits at registration",
    )


def test_created_at_is_stamped_from_the_logical_clock_not_wall_time():
    """A bank written while the clock reads 2026-08-01 carries exactly that
    stamp, and a prospectus drafted after the clock moves carries the later one
    while the untouched bank row keeps its original stamp and version.

    PRD §2.6: "All time-dependent behaviour is evaluated against an injectable logical clock rather than wall-clock time."
    PRD §2.6: "Every timestamp the server stamps, every window comparison, every hold expiry and every demand quarter boundary is computed from that clock."
    PRD §2.4: "`created_at` is an ISO 8601 UTC timestamp with three fractional digits, stamped when the row is first written."
    PRD §2.4: "`version` is an integer that begins at 1 and increments by exactly 1 on every mutation of the row; it is the token the optimistic-concurrency machinery of §2.7 is built on."

    Design: Corner/entities/system_fields_are_stamped_by_the_server_from_the_logical_clock
    """
    set_clock("2026-08-01T00:00:00Z")
    sponsor = register_sponsor(
        legal_name="Cypress Bend Mitigation LLC",
        legal_entity_type="PRIVATE_ENTREPRENEURIAL",
        performance_bond_cents=30_000_000,
    )
    sponsor_headers = make_sponsor_headers(sponsor["id"])

    bank = validate_success(
        api_client.create_bank(
            create_bank_payload(
                sponsor["id"],
                site_name="Cypress Bend",
                site_huc8_code="03130002",
                service_area_huc8_codes=["03130002"],
                hgm_class="DEPRESSIONAL",
                annual_stewardship_cost_cents=4_200_000,
            ),
            sponsor_headers,
        ),
        201,
    )
    assert_bank(bank)
    assert _instant(bank["created_at"]) == _instant("2026-08-01T00:00:00Z"), (
        f"created_at is taken from the logical clock, got {bank['created_at']}"
    )
    assert bank["version"] == 1, f"version begins at 1, got {bank['version']}"

    set_clock("2026-08-15T00:00:00Z")

    prospectus = validate_success(
        api_client.create_prospectus(
            create_prospectus_payload(
                bank["id"], objective_summary=OBJECTIVE_SUMMARY, proposed_credits=98.77
            ),
            sponsor_headers,
        ),
        201,
    )
    assert_prospectus(prospectus)
    assert _instant(prospectus["created_at"]) == _instant("2026-08-15T00:00:00Z"), (
        f"the advanced clock stamps the later row, got {prospectus['created_at']}"
    )

    refreshed = validate_success(api_client.get_bank(bank["id"], sponsor_headers), 200)
    assert _instant(refreshed["created_at"]) == _instant("2026-08-01T00:00:00Z"), (
        f"the bank's created_at is never restamped, got {refreshed['created_at']}"
    )
    assert _instant(refreshed["updated_at"]) == _instant("2026-08-01T00:00:00Z"), (
        "drafting a prospectus mutates no field of the bank row, so its updated_at "
        f"stands at the creation instant, got {refreshed['updated_at']}"
    )
    assert refreshed["version"] == 1, (
        f"an unmutated bank row stays on version 1, got {refreshed['version']}"
    )


def test_out_of_enum_and_malformed_interval_inputs_are_rejected_before_state():
    """A bad enum member, a HUC-8 code of the wrong length, a release percentage
    above one and a zero-length window are all schema breaches.

    PRD §2.10: "Schema validation follows: required fields present, JSON types correct, enum members recognised, HUC-8 codes matching exactly eight decimal digits, credit quantities strictly positive with at most 2 decimal places, cent amounts non-negative integers, a release percentage greater than zero and no greater than one, `limit` within 1 through 100, `offset` non-negative, `window_end` strictly after `window_start`, a non-empty credit-strata array with no repeated stratum code, and a measurements array with no repeated standard code — any breach yields `ERR_INVALID_REQUEST`."
    PRD §3.2: "The hydrogeomorphic class is one of `RIVERINE`, `DEPRESSIONAL`, `SLOPE`, `FLATS` or `ESTUARINE`, and it is the field that selects the bank's base credit price."
    PRD §3.6: "The release percentage is the fraction of the bank's authorised credit total that this milestone frees, strictly greater than zero and no greater than 1, carried to 3 decimal places."

    Design: Corner/entities/creation_with_invalid_enum_and_interval_inputs_is_rejected
    """
    set_clock(CLOCK_EPOCH)
    world = setup_draft_bank()
    sponsor_headers = world["sponsor_headers"]
    bank_id = world["bank"]["id"]

    validate_error(
        api_client.create_bank(
            create_bank_payload(
                world["sponsor"]["id"],
                site_name="Peat Hollow",
                site_huc8_code="03130004",
                service_area_huc8_codes=["03130004"],
                hgm_class="BOG",
                annual_stewardship_cost_cents=4_200_000,
            ),
            sponsor_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api_client.create_bank(
            create_bank_payload(
                world["sponsor"]["id"],
                site_name="Peat Hollow",
                site_huc8_code="0313",
                service_area_huc8_codes=["0313"],
                hgm_class="FLATS",
                annual_stewardship_cost_cents=4_200_000,
            ),
            sponsor_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api_client.create_milestone(
            create_milestone_payload(
                bank_id,
                milestone_code="INSTRUMENT_EXECUTION",
                release_pct=1.500,
                window_start="2026-08-01T00:00:00Z",
                window_end="2026-09-01T00:00:00Z",
            ),
            sponsor_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api_client.create_milestone(
            create_milestone_payload(
                bank_id,
                milestone_code="INSTRUMENT_EXECUTION",
                release_pct=0.150,
                window_start="2026-09-01T00:00:00Z",
                window_end="2026-09-01T00:00:00Z",
            ),
            sponsor_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )

    _bank_rows, bank_meta = validate_paginated(
        api_client.list_banks(
            make_program_admin_headers(),
            params={"sponsor_id": world["sponsor"]["id"], "limit": 10, "offset": 0},
        )
    )
    assert bank_meta["total_count"] == 1, (
        f"only the valid bank site survives, got {bank_meta['total_count']}"
    )

    _milestone_rows, milestone_meta = validate_paginated(
        api_client.list_milestones(sponsor_headers, params={"bank_id": bank_id, "limit": 10, "offset": 0})
    )
    assert milestone_meta["total_count"] == 0, (
        f"neither rejected milestone was scheduled, got {milestone_meta['total_count']}"
    )


def test_ledger_entries_and_votes_stay_immutable_append_only_events():
    """A reservation and its withdrawal append rows 3 and 4 without touching
    rows 1 and 2, and neither a ledger entry nor a prospectus vote ever exposes
    an updated_at or a version.

    PRD §2.4: "A prospectus vote, once cast, is never edited: it carries only `id` and `created_at`, and both `updated_at` and `version` are absent from its representation."
    PRD §2.4: "A credit ledger entry is likewise append-only and never rewritten or deleted: it too carries only `id` and `created_at`, with no `updated_at` and no `version`."
    PRD §2.11: "`balance_after` records the bank's available credits immediately after the entry was appended, and is therefore the running accumulation of every `delta_credits` from sequence number 1 through this entry inclusive."
    PRD §2.11: "The ledger is append-only: no entry is ever amended and none is ever deleted, so every aggregate is recomputable from history alone."
    PRD §3.8: "Cancelling a reservation advances `RESERVED → CANCELLED`, and additionally appends a `HOLD_RELEASED` entry returning the held credits to the available pool before recomputing the bank's on-hold and available credits and its posture."

    Design: Corner/entities/ledger_entries_and_votes_are_immutable_append_only_events
    """
    set_clock(CLOCK_EPOCH)
    world = setup_sellable_bank()
    bank_id = world["bank"]["id"]

    sale = quote_credits(world, 3.00, impact_huc8_code="03130002")
    reserve_sale(world, sale["id"])

    cancelled = validate_success(
        api_client.cancel_credit_sale(
            sale["id"], cancel_sale_payload("BUYER_WITHDREW"), world["permittee_headers"]
        ),
        200,
    )
    assert cancelled["status"] == "CANCELLED", (
        f"withdrawing a reservation cancels the sale, got {cancelled['status']}"
    )

    rows, meta = validate_paginated(
        api_client.list_bank_ledger(
            bank_id, world["sponsor_headers"], params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 4, (
        f"four entries have been appended in this bank's life, got {meta['total_count']}"
    )
    assert_ledger_sequence(rows)
    assert_ledger_shape(
        rows,
        [
            ("GENERATED", 0.00, 0.00),
            ("RELEASED", 14.82, 14.82),
            ("HOLD_PLACED", -3.00, 11.82),
            ("HOLD_RELEASED", 3.00, 14.82),
        ],
    )

    expected_sources = [
        "MITIGATION_BANK",
        "RELEASE_MILESTONE",
        "CREDIT_SALE",
        "CREDIT_SALE",
    ]
    for index, (entry, source_type) in enumerate(zip(rows, expected_sources), start=1):
        assert_ledger_entry(entry)
        assert entry["sequence_number"] == index, (
            f"row {index}: expected sequence_number {index}, got {entry['sequence_number']}"
        )
        assert entry["source_entity_type"] == source_type, (
            f"row {index}: expected source_entity_type {source_type}, "
            f"got {entry['source_entity_type']}"
        )
        assert entry["bank_id"] == bank_id, f"row {index} belongs to the bank it was appended for"
        assert "updated_at" not in entry, f"row {index} is an immutable event with no updated_at"
        assert "version" not in entry, f"row {index} is an immutable event with no version"

    assert rows[0]["source_id"] == bank_id, (
        "the GENERATED entry is attributed to the bank itself"
    )
    assert rows[2]["source_id"] == sale["id"], (
        "the HOLD_PLACED entry is attributed to the credit sale that placed it"
    )
    assert rows[3]["source_id"] == sale["id"], (
        "the HOLD_RELEASED entry is attributed to the credit sale that released it"
    )

    votes, votes_meta = validate_paginated(
        api_client.list_prospectus_votes(
            world["prospectus"]["id"], make_irt_chair_headers(), params={"limit": 10, "offset": 0}
        )
    )
    assert votes_meta["total_count"] == 3, (
        f"three positions were recorded on the round, got {votes_meta['total_count']}"
    )
    for vote in votes:
        assert_prospectus_vote(vote)
        assert vote["position"] == "CONCUR", (
            f"each vote still reads exactly as cast, got {vote['position']}"
        )
        assert vote["revision_round"] == 1, (
            f"each vote stays scoped to the round it was cast in, got {vote['revision_round']}"
        )
        assert "updated_at" not in vote, "a prospectus vote carries no updated_at"
        assert "version" not in vote, "a prospectus vote carries no version"

    bank = bank_state(world)
    assert_bank(bank)
    assert_credits(bank["credits_available"], 14.82, "credits_available after the withdrawal")
    assert_credits(bank["credits_on_hold"], 0.00, "credits_on_hold after the withdrawal")
    assert_credits(bank["credits_released"], 14.82, "credits_released")
