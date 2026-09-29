"""Error catalogue: each refusal reached through a genuine business path, with
the surrounding state proved untouched and a sibling call proving the gate is
keyed on what the contract says it is keyed on.
"""

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    FARM_DIRECTOR_HEADERS,
    INTERNATIONAL_SCOUT_HEADERS,
    MEDICAL_DIRECTOR_HEADERS,
    ApiClient,
    ApiErrorId,
    assert_decimal,
    assert_integer,
    assert_money,
    assert_status,
    factories,
    fixtures,
    make_affiliate_operator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _dispose_review(api: ApiClient, review_id: str, action: str, headers=None, **fields):
    """Raw inspection disposition, so a refusal can be inspected rather than raised."""
    return api.dispose_facility_review(
        review_id,
        factories.disposition_payload(action, **fields),
        headers or COMPLIANCE_OFFICER_HEADERS,
    )


def _dispose_agreement(api: ApiClient, agreement_id: str, action: str, headers=None, **fields):
    """Raw licence disposition, so a refusal can be inspected rather than raised."""
    return api.dispose_agreement(
        agreement_id,
        factories.disposition_payload(action, **fields),
        headers or COMPLIANCE_OFFICER_HEADERS,
    )


def _dispose_assignment(api: ApiClient, assignment_id: str, action: str, **fields):
    """Raw assignment disposition, so a refusal can be inspected rather than raised."""
    return api.dispose_assignment(
        assignment_id, factories.disposition_payload(action, **fields), FARM_DIRECTOR_HEADERS
    )


def _dispose_signing(api: ApiClient, signing_id: str, action: str, **fields):
    """Raw signing disposition, so a refusal can be inspected rather than raised."""
    return api.dispose_international_signing(
        signing_id, factories.disposition_payload(action, **fields), COMPLIANCE_OFFICER_HEADERS
    )


def _dispose_allocation(api: ApiClient, allocation_id: str, action: str, **fields):
    """Raw allocation disposition, so a refusal can be inspected rather than raised."""
    return api.dispose_staff_allocation(
        allocation_id, factories.disposition_payload(action, **fields), FARM_DIRECTOR_HEADERS
    )


def test_a_waiver_is_refused_on_a_major_finding_and_granted_on_a_minor_one(api: ApiClient):
    """The gate reads the banding, so the same action succeeds one row over.

    PRD 3.1: "Waiver is available only for a `MINOR` finding; attempting it on a
    `MAJOR` finding, or on a clean `NONE` finding, is refused with
    `ERR_WAIVER_NOT_PERMITTED`."  The granted waiver removes its row from the
    rollup, per PRD 3.1: "A waiver from `OPEN` records `waiver_granted_by_user_id`
    from the acting `X-User-ID`, drops the inspection out of both the
    `facility_score` mean and the deficiency tallies, and recomputes
    `facility_status`."  The surviving major finding still governs the standing,
    per PRD 2.9: "`facility_status` is `DEFICIENT` when the open-major tally is at
    least 1".

    Design: Corner/errors/waive_is_refused_on_a_major_deficiency
    """
    fixtures.set_clock(api, "2026-03-01T00:00:00Z")
    affiliate = fixtures.create_affiliate(
        api,
        COMPLIANCE_OFFICER_HEADERS,
        name="Waiver Club",
        level="SINGLE_A",
        market_city="Fayetteville",
        meal_stipend_cents_per_day=2600,
    )
    major = fixtures.file_facility_review(api, affiliate["id"], "CLUBHOUSE", "2026-03-01", 60)
    minor = fixtures.file_facility_review(api, affiliate["id"], "LIGHTING", "2026-03-01", 75)

    refused = _dispose_review(api, major["id"], "WAIVE", note="requesting relief")
    validate_error(refused, ApiErrorId.ERR_WAIVER_NOT_PERMITTED.value, 422)
    assert_status(
        fixtures.read_review(api, affiliate["id"], major["id"]), "OPEN", "FacilityStandardReview"
    )

    waived = fixtures.dispose_facility_review(
        api, minor["id"], "WAIVE", note="lighting relief granted"
    )
    assert_status(waived, "WAIVED", "FacilityStandardReview")

    club = fixtures.read_affiliate(api, affiliate["id"])
    assert_decimal(club["facility_score"], "60.00", 2, "Affiliate.facility_score")
    assert club["facility_status"] == "DEFICIENT", (
        f"the surviving major finding keeps the club DEFICIENT, got {club['facility_status']!r}"
    )


def test_the_two_uniqueness_scopes_bite_at_different_moments(api: ApiClient):
    """A duplicate season is refused on create; a duplicate licence only on submit.

    PRD 2.6: "Uniqueness holds (409): at most one agreement per affiliate in status
    `SUBMITTED` or `ACTIVE` (`ERR_DUPLICATE_ACTIVE_AGREEMENT`), `season_year`
    unique across signing pools (`ERR_DUPLICATE_POOL_SEASON`), and at most one
    `ACTIVE` development plan per assignment (`ERR_DUPLICATE_ACTIVE_PLAN`)."  A
    second draft is therefore legal, because PRD 3.2 puts the collision at
    submission: "Submission is the club's act. When the club's `AffiliateOperator`
    submits, the licence moves `DRAFT` → `SUBMITTED`, and three conditions must
    hold: the acting `X-User-ID` must equal the agreement's `affiliate_id`,
    `term_end_date` must be strictly after `term_start_date`, and no other
    agreement for the same club may currently sit in status `SUBMITTED` or
    `ACTIVE` — a second concurrent licence is refused with
    `ERR_DUPLICATE_ACTIVE_AGREEMENT`."

    Design: Corner/errors/uniqueness_conflicts_on_pool_season_and_on_active_agreement
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    pool = fixtures.create_pool(api, season_year=2026, base_pool_cents=5000000)
    affiliate = fixtures.create_affiliate(
        api,
        COMPLIANCE_OFFICER_HEADERS,
        name="Duplicate Club",
        level="HIGH_A",
        market_city="Asheville",
        meal_stipend_cents_per_day=2800,
    )
    operator_headers = make_affiliate_operator_headers(affiliate["id"])
    first = fixtures.create_agreement(
        api,
        affiliate["id"],
        facility_standard_tier="TIER_2",
        club_reimbursement_cap_cents=900000,
        minimum_active_players=0,
    )
    fixtures.submit_agreement(api, first["id"], affiliate["id"])

    duplicate_pool = api.create_signing_pool(
        factories.signing_pool_payload(season_year=2026, base_pool_cents=6000000),
        COMPLIANCE_OFFICER_HEADERS,
    )
    validate_error(duplicate_pool, ApiErrorId.ERR_DUPLICATE_POOL_SEASON.value, 409)
    assert_money(
        fixtures.read_pool(api, pool["id"])["base_pool_cents"], 5000000, "base_pool_cents"
    )

    second = fixtures.create_agreement(
        api,
        affiliate["id"],
        term_start_date="2027-01-01",
        term_end_date="2027-12-31",
        facility_standard_tier="TIER_2",
        club_reimbursement_cap_cents=900000,
        minimum_active_players=0,
    )
    assert_status(second, "DRAFT", "AffiliationAgreement")

    duplicate_submit = _dispose_agreement(api, second["id"], "SUBMIT", operator_headers)
    validate_error(duplicate_submit, ApiErrorId.ERR_DUPLICATE_ACTIVE_AGREEMENT.value, 409)
    assert_status(
        fixtures.read_agreement(api, affiliate["id"], second["id"]),
        "DRAFT",
        "AffiliationAgreement",
    )

    rows, meta = validate_paginated(
        api.list_agreements(affiliate["id"], COMPLIANCE_OFFICER_HEADERS)
    )
    assert_integer(meta["total_count"], 2, "agreement total_count")
    submitted = [row for row in rows if row["status"] == "SUBMITTED"]
    assert len(submitted) == 1, f"exactly one licence may be submitted, got {rows}"


def test_a_licence_settles_exactly_once_and_the_replay_stores_nothing(api: ApiClient):
    """The second SETTLE is refused on the ledger flag, not on the state machine.

    PRD 2.6 gives the replay its own rung: "A `SETTLE` action requires the
    agreement's `settlement_status` to be `NOT_SETTLED`, otherwise
    `ERR_ALREADY_SETTLED` (409)."  PRD 3.3 says the same from the ledger's side:
    "A licence may be settled exactly once — a second settlement attempt is
    refused with `ERR_ALREADY_SETTLED`."  The first settlement's inputs are what
    PRD 3.3 prescribes — "The final computation, which runs on settlement, reads
    the audited figures `audited_housing_expense_cents`,
    `audited_meal_expense_cents`, `audited_travel_expense_cents` and
    `audited_upkeep_expense_cents` wherever they are non-null, and falls back to
    the corresponding declared figure for any audited figure that was not
    supplied." — so 300000 audited housing and 200000 declared meals give club
    lines of 225000 and 120000, both under their pro-rata sub-caps.

    Design: Corner/errors/settling_an_already_settled_agreement_is_refused
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Settle Once Club",
            "level": "DOUBLE_A",
            "market_city": "Amarillo",
            "meal_stipend_cents_per_day": 2900,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_2",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
            "housing_expense_cents": 400000,
            "meal_expense_cents": 200000,
        },
        creator_headers=COMPLIANCE_OFFICER_HEADERS,
    )

    settled = fixtures.dispose_agreement(
        api, club["agreement_id"], "SETTLE", audited_housing_expense_cents=300000
    )
    assert_money(settled["final_club_obligation_cents"], 345000, "final_club_obligation_cents")
    assert_money(settled["affiliate_overflow_cents"], 0, "affiliate_overflow_cents")
    assert settled["settlement_status"] == "SETTLED", (
        f"the first settlement flips the flag, got {settled['settlement_status']!r}"
    )

    replay = _dispose_agreement(
        api, club["agreement_id"], "SETTLE", audited_housing_expense_cents=999999
    )
    validate_error(replay, ApiErrorId.ERR_ALREADY_SETTLED.value, 409)

    # An agreement id is not an affiliate id: the path rung resolves each space separately.
    wrong_space = api.get_affiliate(club["agreement_id"], COMPLIANCE_OFFICER_HEADERS)
    validate_error(wrong_space, ApiErrorId.ERR_AFFILIATE_NOT_FOUND.value, 404)

    after = fixtures.read_agreement(api, club["affiliate_id"], club["agreement_id"])
    assert_money(
        after["audited_housing_expense_cents"], 300000, "audited_housing_expense_cents"
    )
    assert_status(after, "ACTIVE", "AffiliationAgreement")


def test_the_fourth_revision_request_is_refused_with_the_cycle_count_pinned(api: ApiClient):
    """The cap counts cycles walked, so the plan is refused while sitting in ACTIVE.

    PRD 3.7: "A plan may enter revision at most three times: a fourth request, made
    when `review_cycle_count` has already reached 3, is refused with
    `ERR_CYCLE_LIMIT_REACHED`."  Each accepted request behaves as PRD 3.7 says: "the
    request carries `revision_note`, which is stored, and `review_cycle_count` is
    incremented."  And PRD 3.7 adds the reading it zeroes: "Because the player now
    has no `ACTIVE` plan, requesting a revision sets that player's
    `promotion_readiness` to `0.0000`."  The third resubmission therefore returns
    the plan to `ACTIVE` with the count already exhausted.

    Design: Corner/errors/fourth_plan_revision_request_hits_the_cycle_cap
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    club = fixtures.licensed_affiliate_with_active_player(
        api,
        affiliate_overrides={
            "name": "Revision Club",
            "level": "SINGLE_A",
            "market_city": "Delmarva",
            "meal_stipend_cents_per_day": 2600,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_2",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
        },
        player_overrides={
            "full_name": "Revising Prospect",
            "origin": "DOMESTIC_DRAFT",
            "signed_date": "2025-06-10",
        },
        effective_date="2026-04-01",
        end_date="2026-06-30",
    )
    plan_id = fixtures.active_plan_on(
        api,
        club["assignment_id"],
        target_level="HIGH_A",
        curriculum_modules=["MOD_MECHANICS", "MOD_APPROACH"],
    )["plan_id"]

    for cycle, note in enumerate(("cycle one", "cycle two", "cycle three"), start=1):
        revised = fixtures.dispose_plan(
            api, plan_id, "REQUEST_REVISION", COMPLIANCE_OFFICER_HEADERS, revision_note=note
        )
        assert_status(revised, "REVISION_REQUESTED", "DevelopmentPlan")
        assert_integer(revised["review_cycle_count"], cycle, "review_cycle_count")
        assert revised["revision_note"] == note, (
            f"the request must store its own note, got {revised['revision_note']!r}"
        )
        during_revision = fixtures.read_player(api, club["player_id"])
        assert_decimal(
            during_revision["promotion_readiness"], "0.0000", 4, "Player.promotion_readiness"
        )
        resumed = fixtures.dispose_plan(api, plan_id, "RESUBMIT")
        assert_status(resumed, "ACTIVE", "DevelopmentPlan")

    exhausted = api.dispose_development_plan(
        plan_id,
        factories.disposition_payload("REQUEST_REVISION", revision_note="cycle four"),
        COMPLIANCE_OFFICER_HEADERS,
    )
    validate_error(exhausted, ApiErrorId.ERR_CYCLE_LIMIT_REACHED.value, 409)

    after = fixtures.read_plan(api, club["assignment_id"], plan_id)
    assert_status(after, "ACTIVE", "DevelopmentPlan")
    assert_integer(after["review_cycle_count"], 3, "review_cycle_count")
    assert after["revision_note"] == "cycle three", (
        f"the refused request stores nothing, got {after['revision_note']!r}"
    )


def test_the_reserve_list_fills_before_the_roster_does_and_only_for_domestic_players(
    api: ApiClient,
):
    """One reserve slot with thirty roster slots isolates which quota is speaking.

    PRD 3.6 orders the quotas and names this one: "Adding a domestic-reserve-list
    player to a club requires the club's `reserve_list_count` to be strictly below
    its `reserve_slots` (`ERR_DOMESTIC_RESERVE_LIST_FULL`)."  Membership of that
    list is derived, per PRD 3.5: "`is_on_domestic_reserve_list` reads true when
    the player's `roster_status` is any of `RESERVE_LIST`, `ACTIVE` or `RESTRICTED`
    and their `origin` is either `DOMESTIC_DRAFT` or `FOREIGN_PRO`. Players whose
    `origin` is `INTERNATIONAL_FA` are never carried on the domestic reserve list,
    whatever their roster standing."  So the internationally signed player is
    admitted after the refusal, and the roster quota — thirty by the PRD 2.7
    default for `HIGH_A` — never engages.

    Design: Corner/errors/domestic_reserve_list_capacity_blocks_a_second_domestic_activation
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "One Slot Club",
            "level": "HIGH_A",
            "market_city": "Everett",
            "meal_stipend_cents_per_day": 2800,
            "reserve_slots": 1,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_2",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
        },
    )
    assert_integer(club["affiliate"]["roster_limit"], 30, "roster_limit")

    first = fixtures.pending_assignment(
        api,
        club["affiliate_id"],
        player_overrides={
            "full_name": "Domestic One",
            "origin": "DOMESTIC_DRAFT",
            "signed_date": "2025-06-10",
        },
        effective_date="2026-04-01",
        end_date="2026-06-30",
    )
    second = fixtures.pending_assignment(
        api,
        club["affiliate_id"],
        player_overrides={
            "full_name": "Domestic Two",
            "origin": "DOMESTIC_DRAFT",
            "signed_date": "2025-06-11",
        },
        effective_date="2026-04-01",
        end_date="2026-06-30",
    )
    third = fixtures.pending_assignment(
        api,
        club["affiliate_id"],
        player_overrides={
            "full_name": "International Three",
            "origin": "INTERNATIONAL_FA",
            "signed_date": "2026-01-15",
        },
        effective_date="2026-04-01",
        end_date="2026-06-30",
    )

    fixtures.dispose_assignment(api, first["assignment_id"], "ACTIVATE")
    filled = fixtures.read_affiliate(api, club["affiliate_id"])
    assert_integer(filled["reserve_list_count"], 1, "reserve_list_count")
    assert_integer(filled["active_roster_count"], 1, "active_roster_count")

    refused = _dispose_assignment(api, second["assignment_id"], "ACTIVATE")
    validate_error(refused, ApiErrorId.ERR_DOMESTIC_RESERVE_LIST_FULL.value, 409)
    assert_status(
        fixtures.read_assignment(api, second["assignment_id"]),
        "PENDING_CLEARANCE",
        "PlayerAssignment",
    )
    assert fixtures.read_player(api, second["player_id"])["roster_status"] == "RESERVE_LIST", (
        "a refused activation leaves the player's roster standing untouched"
    )

    admitted = fixtures.dispose_assignment(api, third["assignment_id"], "ACTIVATE")
    assert_status(admitted, "ACTIVE", "PlayerAssignment")
    after = fixtures.read_affiliate(api, club["affiliate_id"])
    assert_integer(after["active_roster_count"], 2, "active_roster_count")
    assert_integer(after["reserve_list_count"], 1, "reserve_list_count")
    assert fixtures.read_player(api, third["player_id"])["is_on_domestic_reserve_list"] is False, (
        "an INTERNATIONAL_FA player is never carried on the domestic reserve list"
    )
    assert fixtures.read_player(api, first["player_id"])["is_on_domestic_reserve_list"] is True, (
        "an active DOMESTIC_DRAFT player is carried on the domestic reserve list"
    )


def test_a_fourth_optional_window_is_refused_once_all_three_years_are_spent(api: ApiClient):
    """Completing each window keeps the charge, so the fourth activation runs dry.

    PRD 3.6 puts the quota last among the activation conditions: "And for a `LEVEL`
    or `COMPLEX` assignment whose `projected_optional_days` is 20 or more, the
    player must have at least one option year left
    (`ERR_OPTION_YEARS_EXHAUSTED`)."  Nothing gives the years back, because PRD 3.6
    is explicit about completion: "Note that completion does not rescind the option
    year the assignment charged — a completed optional assignment has been used."
    Each window projects twenty-five days by the PRD 3.6 rule that
    `projected_optional_days` "is computed as the number of days from
    `effective_date` to `end_date` plus one", and consecutive windows are separated
    by more than the two-day buffer PRD 3.6 requires.

    Design: Corner/errors/fourth_option_year_charge_is_refused_as_exhausted
    """
    fixtures.set_clock(api, "2026-01-01T00:00:00Z")
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Option Club",
            "level": "SINGLE_A",
            "market_city": "Jupiter",
            "meal_stipend_cents_per_day": 2600,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_2",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
        },
    )
    player = fixtures.cleared_player(
        api,
        clearance_type="LEVEL_ASSIGNMENT",
        expires_on="2026-12-31",
        full_name="Thrice Optioned",
        origin="DOMESTIC_DRAFT",
        signed_date="2024-06-10",
    )

    windows = [
        ("2026-01-01", "2026-01-25"),
        ("2026-02-01", "2026-02-25"),
        ("2026-03-01", "2026-03-25"),
    ]
    for spent, (start, end) in enumerate(windows, start=1):
        row = fixtures.create_assignment(
            api,
            player["player_id"],
            club["affiliate_id"],
            assignment_type="LEVEL",
            movement_reason="LATERAL",
            effective_date=start,
            end_date=end,
        )
        assert_integer(row["projected_optional_days"], 25, "projected_optional_days")
        activated = fixtures.dispose_assignment(api, row["id"], "ACTIVATE")
        assert activated["option_year_charged"] is True, (
            f"a twenty-five-day level window charges an option year, got {activated!r}"
        )
        after_charge = fixtures.read_player(api, player["player_id"])
        assert_integer(after_charge["option_years_used"], spent, "option_years_used")
        assert_integer(after_charge["option_years_remaining"], 3 - spent, "option_years_remaining")
        fixtures.dispose_assignment(api, row["id"], "COMPLETE")
        after_completion = fixtures.read_player(api, player["player_id"])
        assert_integer(after_completion["option_years_used"], spent, "option_years_used")

    fourth = fixtures.create_assignment(
        api,
        player["player_id"],
        club["affiliate_id"],
        assignment_type="LEVEL",
        movement_reason="LATERAL",
        effective_date="2026-04-01",
        end_date="2026-04-25",
    )
    exhausted = _dispose_assignment(api, fourth["id"], "ACTIVATE")
    validate_error(exhausted, ApiErrorId.ERR_OPTION_YEARS_EXHAUSTED.value, 422)

    refused = fixtures.read_assignment(api, fourth["id"])
    assert_status(refused, "PENDING_CLEARANCE", "PlayerAssignment")
    assert refused["option_year_charged"] is False, (
        f"a refused activation charges nothing, got {refused!r}"
    )
    exhausted_player = fixtures.read_player(api, player["player_id"])
    assert_integer(exhausted_player["option_years_used"], 3, "option_years_used")
    assert_integer(exhausted_player["option_years_remaining"], 0, "option_years_remaining")
    assert_integer(
        fixtures.read_affiliate(api, club["affiliate_id"])["active_roster_count"],
        0,
        "active_roster_count",
    )


def test_the_academy_bed_count_admits_one_signing_and_refuses_the_next(api: ApiClient):
    """A single certified bed makes the second approval a capacity refusal.

    PRD 3.9: "And the academy must have a bed free: its count of housed players —
    its `reserve_list_count` plus the signings already `APPROVED` at that academy —
    must be strictly below its `housing_beds`, otherwise
    `ERR_ACADEMY_HOUSING_FULL`."  The first approval therefore fills the only bed
    and charges the pool, since PRD 3.9 makes `pool_charge_cents` "simply its
    `bonus_cents`", while the refused one contributes nothing — PRD 3.9: "signings
    in `SUBMITTED`, `REJECTED` or `VOIDED` contribute nothing to either."

    Design: Corner/errors/academy_housing_capacity_blocks_the_second_signing_approval
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    academy = fixtures.licensed_academy(
        api,
        affiliate_overrides={
            "name": "One Bed Academy",
            "market_city": "La Romana",
            "meal_stipend_cents_per_day": 2500,
            "housing_beds": 1,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_2",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
        },
    )
    pool = fixtures.create_pool(api, season_year=2026, base_pool_cents=5000000)
    first_player = fixtures.create_player(
        api,
        INTERNATIONAL_SCOUT_HEADERS,
        full_name="Bed One",
        origin="INTERNATIONAL_FA",
        signed_date="2026-01-15",
    )
    second_player = fixtures.create_player(
        api,
        INTERNATIONAL_SCOUT_HEADERS,
        full_name="Bed Two",
        origin="INTERNATIONAL_FA",
        signed_date="2026-01-16",
    )
    first = fixtures.create_signing(
        api, pool["id"], first_player["id"], academy["affiliate_id"], bonus_cents=400000
    )
    second = fixtures.create_signing(
        api, pool["id"], second_player["id"], academy["affiliate_id"], bonus_cents=400000
    )

    approved = fixtures.dispose_signing(api, first["id"], "APPROVE")
    assert_status(approved, "APPROVED", "InternationalSigning")
    assert_money(approved["pool_charge_cents"], 400000, "pool_charge_cents")

    full = _dispose_signing(api, second["id"], "APPROVE")
    validate_error(full, ApiErrorId.ERR_ACADEMY_HOUSING_FULL.value, 409)
    assert_status(
        fixtures.read_signing(api, second["id"]), "SUBMITTED", "InternationalSigning"
    )

    _, meta = validate_paginated(
        api.list_international_signings(
            COMPLIANCE_OFFICER_HEADERS, {"academy_affiliate_id": academy["affiliate_id"], "status": "APPROVED"}
        )
    )
    assert_integer(meta["total_count"], 1, "approved signing total_count")

    ledger = fixtures.read_pool(api, pool["id"])
    assert_money(ledger["allocated_cents"], 400000, "allocated_cents")
    assert_status(ledger, "OPEN", "SigningPool")


def test_a_certification_lapsing_before_the_start_date_blocks_the_activation(api: ApiClient):
    """The gate compares the member's expiry against the allocation's own start.

    PRD 3.4: "It further requires that the member's `certification_expires_on` is
    not earlier than the allocation's `effective_start` — a certification lapsing
    before the assignment even begins is refused with `ERR_CERTIFICATION_EXPIRED`
    — and it re-runs the overcommitment check just described, refusing with
    `ERR_STAFF_FTE_OVERCOMMITTED` when the member's overlapping active commitments
    plus this allocation exceed 100."  Because the refusal leaves the row in
    `PROPOSED`, the recall path is still open, and PRD 3.4 says that path recomputes
    nothing: the member's committed share is the sum "across their `ACTIVE`
    allocations", of which there are none.

    Design: Corner/errors/expired_certification_blocks_the_allocation_activation
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Certification Club",
            "level": "HIGH_A",
            "market_city": "Spokane",
            "meal_stipend_cents_per_day": 2800,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_2",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
        },
    )
    member = fixtures.create_staff_member(
        api,
        full_name="Lapsed Coach",
        discipline="STRENGTH",
        curriculum_version_certified="2026.1",
        certification_expires_on="2026-03-31",
    )
    allocation = fixtures.create_allocation(
        api,
        member["id"],
        club["affiliate_id"],
        staff_role="STRENGTH_COACH",
        fte_pct=40,
        effective_start="2026-04-01",
        effective_end="2026-09-01",
        curriculum_version="2026.1",
    )
    assert_status(allocation, "PROPOSED", "StaffAllocation")

    lapsed = _dispose_allocation(api, allocation["id"], "ACTIVATE")
    validate_error(lapsed, ApiErrorId.ERR_CERTIFICATION_EXPIRED.value, 422)
    assert_status(
        fixtures.read_allocation(api, club["affiliate_id"], allocation["id"]),
        "PROPOSED",
        "StaffAllocation",
    )
    assert_integer(
        validate_success(api.get_staff_member(member["id"], FARM_DIRECTOR_HEADERS))[
            "total_committed_fte_pct"
        ],
        0,
        "total_committed_fte_pct",
    )

    recalled = fixtures.dispose_allocation(api, allocation["id"], "RECALL", note="certification lapsed")
    assert_status(recalled, "RECALLED", "StaffAllocation")
    assert_integer(
        validate_success(api.get_staff_member(member["id"], FARM_DIRECTOR_HEADERS))[
            "total_committed_fte_pct"
        ],
        0,
        "total_committed_fte_pct",
    )


_UNKNOWN_IDS = (
    "00000000-0000-4000-8000-000000000001",
    "00000000-0000-4000-8000-000000000002",
    "00000000-0000-4000-8000-000000000003",
    "00000000-0000-4000-8000-000000000004",
    "00000000-0000-4000-8000-000000000005",
    "00000000-0000-4000-8000-000000000006",
    "00000000-0000-4000-8000-000000000007",
    "00000000-0000-4000-8000-000000000008",
)


def test_each_id_bearing_path_answers_with_its_own_not_found_code(api: ApiClient):
    """Eight probes against an empty database, eight distinct 404 identities.

    PRD 2.6: "Every id embedded in the request path resolves to a stored resource,
    validated strictly left to right, otherwise the not-found error for the
    leftmost unresolved segment (404) — one of `ERR_AFFILIATE_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_FACILITY_REVIEW_NOT_FOUND`,
    `ERR_STAFF_MEMBER_NOT_FOUND`, `ERR_STAFF_ALLOCATION_NOT_FOUND`,
    `ERR_PLAYER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_DEVELOPMENT_PLAN_NOT_FOUND`, `ERR_MEDICAL_CLEARANCE_NOT_FOUND`,
    `ERR_SIGNING_POOL_NOT_FOUND`, `ERR_SIGNING_NOT_FOUND` or
    `ERR_TRANSACTION_REPORT_NOT_FOUND`."  Each probe carries a well-formed action
    payload, so nothing later in the ladder can pre-empt the existence check.

    Design: Corner/errors/every_entity_reports_its_own_not_found_code
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    review, allocation, plan, clearance, pool, signing, report, member = _UNKNOWN_IDS

    validate_error(
        api.dispose_facility_review(
            review, factories.disposition_payload("CLOSE"), COMPLIANCE_OFFICER_HEADERS
        ),
        ApiErrorId.ERR_FACILITY_REVIEW_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.dispose_staff_allocation(
            allocation, factories.disposition_payload("ACTIVATE"), FARM_DIRECTOR_HEADERS
        ),
        ApiErrorId.ERR_STAFF_ALLOCATION_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.dispose_development_plan(
            plan, factories.disposition_payload("ACTIVATE"), FARM_DIRECTOR_HEADERS
        ),
        ApiErrorId.ERR_DEVELOPMENT_PLAN_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.dispose_medical_clearance(
            clearance,
            factories.disposition_payload(
                "ISSUE", cleared_workload_ceiling_index=10.00, expires_on="2026-12-31"
            ),
            MEDICAL_DIRECTOR_HEADERS,
        ),
        ApiErrorId.ERR_MEDICAL_CLEARANCE_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_signing_pool(pool, COMPLIANCE_OFFICER_HEADERS),
        ApiErrorId.ERR_SIGNING_POOL_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_international_signing(signing, INTERNATIONAL_SCOUT_HEADERS),
        ApiErrorId.ERR_SIGNING_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.dispose_transaction_report(
            report, factories.disposition_payload("FILE"), COMPLIANCE_OFFICER_HEADERS
        ),
        ApiErrorId.ERR_TRANSACTION_REPORT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_staff_member(member, FARM_DIRECTOR_HEADERS),
        ApiErrorId.ERR_STAFF_MEMBER_NOT_FOUND.value,
        404,
    )


def test_two_terminal_rows_each_refuse_with_their_own_state_error(api: ApiClient):
    """A waived inspection and a recalled allocation answer in their own vocabulary.

    PRD 3.1 names the inspection's code: "Any inspection action that is not a
    declared transition out of the row's current status — waiving an already-closed
    inspection, closing one that has not yet submitted remediation, submitting
    remediation on a `WAIVED` row — is refused with `ERR_INVALID_REVIEW_STATE`".
    PRD 3.4 names the allocation's, and makes the recalled row terminal in both
    directions: "Both `ENDED` and `RECALLED` are terminal. Any action that is not a
    declared transition out of the allocation's current status is refused with
    `ERR_INVALID_ALLOCATION_STATE`".  Because the state check comes first, the
    certification gate PRD 3.4 attaches to activation is never consulted, and the
    member's committed share — which PRD 3.4 sums only over `ACTIVE` allocations —
    stays at zero.

    Design: Corner/errors/review_and_allocation_state_errors_are_entity_specific
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "State Error Club",
            "level": "HIGH_A",
            "market_city": "Hickory",
            "meal_stipend_cents_per_day": 2800,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_2",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
        },
        creator_headers=COMPLIANCE_OFFICER_HEADERS,
    )
    review = fixtures.file_facility_review(
        api, club["affiliate_id"], "LIGHTING", "2026-04-01", 75
    )
    member = fixtures.create_staff_member(
        api,
        full_name="Recalled Coach",
        discipline="PITCHING",
        curriculum_version_certified="2026.1",
        certification_expires_on="2027-01-31",
    )
    allocation = fixtures.create_allocation(
        api,
        member["id"],
        club["affiliate_id"],
        staff_role="PITCHING_COACH",
        fte_pct=50,
        effective_start="2026-04-01",
        effective_end="2026-09-01",
        curriculum_version="2026.1",
    )

    waived = fixtures.dispose_facility_review(api, review["id"], "WAIVE", note="minor relief")
    assert_status(waived, "WAIVED", "FacilityStandardReview")
    reopened = _dispose_review(api, review["id"], "REOPEN")
    validate_error(reopened, ApiErrorId.ERR_INVALID_REVIEW_STATE.value, 409)
    after_review = fixtures.read_review(api, club["affiliate_id"], review["id"])
    assert_status(after_review, "WAIVED", "FacilityStandardReview")
    assert_integer(after_review["reopen_count"], 0, "reopen_count")

    recalled = fixtures.dispose_allocation(api, allocation["id"], "RECALL")
    assert_status(recalled, "RECALLED", "StaffAllocation")
    reactivated = _dispose_allocation(api, allocation["id"], "ACTIVATE")
    validate_error(reactivated, ApiErrorId.ERR_INVALID_ALLOCATION_STATE.value, 409)
    ended = _dispose_allocation(api, allocation["id"], "END")
    validate_error(ended, ApiErrorId.ERR_INVALID_ALLOCATION_STATE.value, 409)
    assert_status(
        fixtures.read_allocation(api, club["affiliate_id"], allocation["id"]),
        "RECALLED",
        "StaffAllocation",
    )

    assert_integer(
        validate_success(api.get_staff_member(member["id"], FARM_DIRECTOR_HEADERS))[
            "total_committed_fte_pct"
        ],
        0,
        "total_committed_fte_pct",
    )
    assert (
        fixtures.read_agreement(api, club["affiliate_id"], club["agreement_id"])["posture"]
        == "OPEN"
    ), "no refused disposition may move the licence posture"


def _create_assignment(api: ApiClient, player_id: str, affiliate_id: str, **overrides):
    """Raw assignment creation, so a refusal can be inspected rather than raised."""
    expected = overrides.pop("expected_player_version", None)
    if expected is None:
        expected = fixtures.player_version(api, player_id)
    return api.create_assignment(
        factories.assignment_payload(player_id, affiliate_id, expected, **overrides),
        FARM_DIRECTOR_HEADERS,
    )


def test_a_restricted_posture_stops_promotions_and_academy_approvals_only(api: ApiClient):
    """An uncovered required role restricts both clubs, and a lateral move still runs.

    PRD 2.9 draws the boundary exactly: "`RESTRICTED` blocks exactly two operations
    — creating an assignment whose `movement_reason` is `PROMOTION`, and approving
    an international signing at the academy — each rejected with
    `ERR_AGREEMENT_POSTURE_RESTRICTED`; every other write proceeds normally while
    `RESTRICTED`. `OPEN` blocks nothing."  Both licences land there on activation,
    because of what PRD 3.2 says activation does: "Activation then runs the posture
    derivation, writing `posture` to either `OPEN` or `RESTRICTED` according to the
    rules in Section 2.9 — a club that satisfies its staffing floor and role
    coverage comes out `OPEN`, a club that does not comes out `RESTRICTED` and is
    immediately barred from promotions."

    Design: Corner/errors/restricted_posture_blocks_promotions_and_academy_approvals
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Restricted Club",
            "level": "DOUBLE_A",
            "market_city": "Biloxi",
            "meal_stipend_cents_per_day": 2900,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_2",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
            "required_staff_roles": ["PITCHING_COACH"],
        },
        creator_headers=COMPLIANCE_OFFICER_HEADERS,
    )
    academy = fixtures.licensed_academy(
        api,
        affiliate_overrides={
            "name": "Restricted Academy",
            "market_city": "Bani",
            "meal_stipend_cents_per_day": 2500,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_2",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
            "required_staff_roles": ["PITCHING_COACH"],
        },
    )
    assert club["agreement"]["posture"] == "RESTRICTED", (
        f"an uncovered required role restricts the club, got {club['agreement']['posture']!r}"
    )
    assert academy["agreement"]["posture"] == "RESTRICTED", (
        f"an uncovered required role restricts the academy, got {academy['agreement']['posture']!r}"
    )

    prospect = fixtures.cleared_player(
        api,
        clearance_type="LEVEL_ASSIGNMENT",
        creator_headers=FARM_DIRECTOR_HEADERS,
        full_name="Restricted Prospect",
        origin="DOMESTIC_DRAFT",
        signed_date="2024-06-10",
        service_days_accrued=400,
    )
    pool = fixtures.create_pool(api, season_year=2026, base_pool_cents=5000000)
    signing_player = fixtures.create_player(
        api,
        INTERNATIONAL_SCOUT_HEADERS,
        full_name="Restricted Signing",
        origin="INTERNATIONAL_FA",
        signed_date="2026-01-15",
    )
    signing = fixtures.create_signing(
        api, pool["id"], signing_player["id"], academy["affiliate_id"], bonus_cents=400000
    )

    promotion = _create_assignment(
        api,
        prospect["player_id"],
        club["affiliate_id"],
        assignment_type="LEVEL",
        movement_reason="PROMOTION",
        effective_date="2026-04-01",
        end_date="2026-06-30",
    )
    validate_error(promotion, ApiErrorId.ERR_AGREEMENT_POSTURE_RESTRICTED.value, 409)
    _, promotion_meta = validate_paginated(
        api.list_assignments(FARM_DIRECTOR_HEADERS, {"player_id": prospect["player_id"]})
    )
    assert_integer(promotion_meta["total_count"], 0, "assignment total_count")

    approval = _dispose_signing(api, signing["id"], "APPROVE")
    validate_error(approval, ApiErrorId.ERR_AGREEMENT_POSTURE_RESTRICTED.value, 409)
    assert_status(
        fixtures.read_signing(api, signing["id"]), "SUBMITTED", "InternationalSigning"
    )

    lateral = fixtures.create_assignment(
        api,
        prospect["player_id"],
        club["affiliate_id"],
        assignment_type="LEVEL",
        movement_reason="LATERAL",
        effective_date="2026-04-01",
        end_date="2026-06-30",
    )
    assert_status(lateral, "PENDING_CLEARANCE", "PlayerAssignment")
    assert_money(fixtures.read_pool(api, pool["id"])["allocated_cents"], 0, "allocated_cents")


def test_a_capped_pool_refuses_a_later_approval_and_state_outranks_the_cap(api: ApiClient):
    """One oversized bonus caps the pool; a stale rejection answers before it does.

    PRD 3.9 fixes both the tax and the cap: "For any overage amount, the tax on
    that amount is seventy-five hundredths of the first five thousand dollars of
    overage — the portion up to 500000 cents — plus the full amount of the next
    five thousand dollars of overage, that is the portion between 500000 and 1000000
    cents, plus the full amount of any overage above 1000000 cents." and "the pool's
    status becomes `HARD_CAPPED` when the allocated amount is strictly greater than
    the effective pool, or stays `OPEN` otherwise."  Approval then requires that
    status, per PRD 3.9: "The pool must be in status `OPEN`, otherwise
    `ERR_POOL_HARD_CAPPED`."  A signing that was already rejected answers earlier,
    because PRD 2.6 places the state check ahead of the fiscal gates: "The target
    resource is in a state from which the requested action is a declared transition,
    otherwise the state error for that resource type (409)."

    Design: Corner/errors/hard_capped_pool_and_rejected_signing_refuse_further_approval
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    academy = fixtures.licensed_academy(
        api,
        affiliate_overrides={
            "name": "Capped Academy",
            "market_city": "Nagua",
            "meal_stipend_cents_per_day": 2500,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_2",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
        },
    )
    pool = fixtures.create_pool(api, season_year=2026, base_pool_cents=1000000)
    players = [
        fixtures.create_player(
            api,
            INTERNATIONAL_SCOUT_HEADERS,
            full_name=name,
            origin="INTERNATIONAL_FA",
            signed_date=signed,
        )
        for name, signed in (
            ("Cap Filler", "2026-01-15"),
            ("After Cap", "2026-01-16"),
            ("Rejected Signing", "2026-01-17"),
        )
    ]

    stale = fixtures.create_signing(
        api, pool["id"], players[2]["id"], academy["affiliate_id"], bonus_cents=100000
    )
    rejected = fixtures.dispose_signing(api, stale["id"], "REJECT")
    assert_status(rejected, "REJECTED", "InternationalSigning")

    filler = fixtures.create_signing(
        api, pool["id"], players[0]["id"], academy["affiliate_id"], bonus_cents=1200000
    )
    approved = fixtures.dispose_signing(api, filler["id"], "APPROVE")
    assert_status(approved, "APPROVED", "InternationalSigning")
    assert_money(approved["overage_tax_cents"], 150000, "overage_tax_cents")
    assert approved["tier3_breach"] is False, (
        f"a 200000-cent overage does not cross the second ceiling, got {approved!r}"
    )
    capped = fixtures.read_pool(api, pool["id"])
    assert_money(capped["allocated_cents"], 1200000, "allocated_cents")
    assert_money(capped["remaining_cents"], -200000, "remaining_cents")
    assert_status(capped, "HARD_CAPPED", "SigningPool")

    late = fixtures.create_signing(
        api, pool["id"], players[1]["id"], academy["affiliate_id"], bonus_cents=100000
    )
    assert_status(late, "SUBMITTED", "InternationalSigning")

    fiscal = _dispose_signing(api, late["id"], "APPROVE")
    validate_error(fiscal, ApiErrorId.ERR_POOL_HARD_CAPPED.value, 409)

    stale_replay = _dispose_signing(api, stale["id"], "APPROVE")
    validate_error(stale_replay, ApiErrorId.ERR_INVALID_SIGNING_STATE.value, 409)

    after = fixtures.read_pool(api, pool["id"])
    assert_money(after["allocated_cents"], 1200000, "allocated_cents")
    assert_money(after["forfeited_cents"], 0, "forfeited_cents")
    assert_money(after["overage_tax_accrued_cents"], 150000, "overage_tax_accrued_cents")


def test_one_assignment_supplies_a_report_conflict_and_a_plan_conflict(api: ApiClient):
    """The auto-filed report refuses the league's verdict; the second plan refuses ACTIVE.

    PRD 3.8 makes the report's terminal vocabulary explicit: "Any action that is not
    a declared transition out of the report's current status is refused with
    `ERR_INVALID_REPORT_STATE`."  PRD 3.7 supplies the plan's: "Activating a plan
    moves it `DRAFT` → `ACTIVE` and is a `FarmDirector` act with three
    preconditions: the owning assignment must be in status `ACTIVE`, otherwise
    `ERR_INVALID_ASSIGNMENT_STATE`; the plan's `curriculum_version` must equal the
    organization-wide version, otherwise `ERR_CURRICULUM_VERSION_MISMATCH`; and no
    other plan on the same assignment may already be `ACTIVE`, otherwise
    `ERR_DUPLICATE_ACTIVE_PLAN`."  The second plan is nonetheless persisted, since
    PRD 3.7 puts no such gate on creation: "A new plan is persisted in status
    `DRAFT`".

    Design: Corner/errors/report_and_plan_conflicts_on_a_single_assignment
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    club = fixtures.licensed_affiliate_with_active_player(
        api,
        affiliate_overrides={
            "name": "Conflict Club",
            "level": "SINGLE_A",
            "market_city": "Salem",
            "meal_stipend_cents_per_day": 2600,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_2",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
        },
        player_overrides={
            "full_name": "Conflict Player",
            "origin": "DOMESTIC_DRAFT",
            "signed_date": "2025-06-10",
        },
        effective_date="2026-04-01",
        end_date="2026-06-30",
    )
    first_plan = fixtures.active_plan_on(
        api,
        club["assignment_id"],
        target_level="HIGH_A",
        curriculum_modules=["MOD_MECHANICS", "MOD_APPROACH"],
    )
    second_plan = fixtures.create_plan(
        api,
        club["assignment_id"],
        target_level="DOUBLE_A",
        curriculum_modules=["MOD_DEFENSE"],
    )
    assert_status(second_plan, "DRAFT", "DevelopmentPlan")

    reports = fixtures.reports_for(api, club["assignment_id"])
    assert len(reports) == 1, f"activation files exactly one report, got {reports}"
    report = reports[0]
    assert_status(report, "PENDING", "TransactionReport")

    accepted = api.dispose_transaction_report(
        report["id"], factories.disposition_payload("LEAGUE_ACCEPT"), COMPLIANCE_OFFICER_HEADERS
    )
    validate_error(accepted, ApiErrorId.ERR_INVALID_REPORT_STATE.value, 409)
    refiled = api.dispose_transaction_report(
        report["id"], factories.disposition_payload("REFILE"), COMPLIANCE_OFFICER_HEADERS
    )
    validate_error(refiled, ApiErrorId.ERR_INVALID_REPORT_STATE.value, 409)

    still_pending = fixtures.reports_for(api, club["assignment_id"])[0]
    assert_status(still_pending, "PENDING", "TransactionReport")
    assert still_pending["certified_by_user_id"] is None, (
        f"a refused filing certifies nobody, got {still_pending['certified_by_user_id']!r}"
    )
    assert_integer(still_pending["refile_count"], 0, "refile_count")

    duplicate = api.dispose_development_plan(
        second_plan["id"], factories.disposition_payload("ACTIVATE"), FARM_DIRECTOR_HEADERS
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_ACTIVE_PLAN.value, 409)

    active_rows, active_meta = validate_paginated(
        api.list_development_plans(
            club["assignment_id"], FARM_DIRECTOR_HEADERS, {"status": "ACTIVE"}
        )
    )
    assert_integer(active_meta["total_count"], 1, "active plan total_count")
    assert active_rows[0]["id"] == first_plan["plan_id"], (
        "the only ACTIVE plan must be the one that was activated first"
    )
    assert_status(
        fixtures.read_plan(api, club["assignment_id"], second_plan["id"]),
        "DRAFT",
        "DevelopmentPlan",
    )
