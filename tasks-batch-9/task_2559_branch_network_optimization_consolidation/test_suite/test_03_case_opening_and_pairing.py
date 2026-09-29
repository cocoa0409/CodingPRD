"""Opening a consolidation case: survivor selection, the branch hold and its guards."""

from test_helpers import (
    COMPLIANCE,
    HR,
    REAL_ESTATE,
    STRATEGIST,
    ApiErrorId,
    api_client,
    branch_payload,
    consolidation_case_payload,
    de_novo_plan_payload,
    impact_assessment_payload,
    leased_property_disposition_payload,
    read_branch,
    read_case,
    receiving_branch_payload,
    record_snapshot,
    retention_forecast_payload,
    setup_case_with_forecast,
    setup_market,
    setup_market_with_branches,
    staff_disposition_payload,
    transition_campaign_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_01_omitting_the_survivor_runs_the_selector_over_the_eligible_peers():
    """With four peers on file the selector rejects the drive-up format and the peer under
    the absorption floor, then breaks a perfect deposits-and-transactions tie on the older
    registration.

    PRD: "The candidate set is every branch of the closing branch's trade area other than the closing branch itself, in `ACTIVE` status, of `FULL_SERVICE` or `LIMITED_SERVICE` format, and holding `deposit_balance_cents` of at least half the closing branch's `deposit_balance_cents` — the absorption floor is 5000 basis points of the closing balance."
    PRD: "Candidates are ranked by `deposit_balance_cents` descending, then by `monthly_transaction_count` descending, then by `created_at` ascending, and the first row under that ranking is selected; the final tie-break is the creation timestamp and never the identifier."
    Design: Corner/calculations/receiving_branch_selector_picks_highest_deposits_with_created_at_tiebreak
    """
    ctx = setup_market_with_branches()
    tied_but_newer = validate_success(
        api_client.create_branch(
            branch_payload(
                ctx["market"]["id"],
                branch_code="RB-104",
                branch_type="LIMITED_SERVICE",
                deposit_balance_cents=9600000000,
                monthly_transaction_count=8100,
                digital_adoption_bps=5900,
                annual_noninterest_expense_cents=44000000,
                annual_revenue_cents=80000000,
                fte_count=8,
                atm_count=1,
                opened_on="2011-04-01",
            ),
            STRATEGIST,
        ),
        expected_status=201,
    )
    below_floor = validate_success(
        api_client.create_branch(
            branch_payload(
                ctx["market"]["id"],
                branch_code="RB-105",
                deposit_balance_cents=2000000000,
                monthly_transaction_count=3000,
                digital_adoption_bps=4800,
                annual_noninterest_expense_cents=30000000,
                annual_revenue_cents=26000000,
                fte_count=6,
                atm_count=1,
                opened_on="2014-09-01",
            ),
            STRATEGIST,
        ),
        expected_status=201,
    )
    wrong_format = validate_success(
        api_client.create_branch(
            branch_payload(
                ctx["market"]["id"],
                branch_code="RB-106",
                branch_type="DRIVE_UP",
                tenure_class="OWNED",
                deposit_balance_cents=20000000000,
                monthly_transaction_count=9000,
                digital_adoption_bps=6400,
                annual_noninterest_expense_cents=20000000,
                annual_revenue_cents=90000000,
                fte_count=3,
                atm_count=4,
                opened_on="2001-02-01",
            ),
            STRATEGIST,
        ),
        expected_status=201,
    )

    case = validate_success(
        api_client.create_consolidation_case(
            consolidation_case_payload(
                ctx["closing_branch"]["id"], ctx["closing_branch"]["version"]
            ),
            STRATEGIST,
        ),
        expected_status=201,
    )

    assert case["receiving_branch_id"] == ctx["receiving_branch"]["id"]
    assert case["receiving_branch_id"] != tied_but_newer["id"]
    assert case["receiving_branch_id"] != below_floor["id"]
    assert case["receiving_branch_id"] != wrong_format["id"]
    assert case["status"] == "DRAFT"
    assert read_branch(ctx["closing_branch"]["id"])["status"] == "UNDER_REVIEW"
    assert read_branch(tied_but_newer["id"])["status"] == "ACTIVE"
    assert read_branch(wrong_format["id"])["status"] == "ACTIVE"


def test_02_a_peer_one_cent_under_the_absorption_floor_empties_the_candidate_set():
    """The floor is inclusive at half the closing book, so a single peer one cent short leaves
    the selector with nothing and the case is never opened.

    PRD: "An empty candidate set fails the create with `ERR_NO_ELIGIBLE_RECEIVING_BRANCH`."
    PRD: "Threshold comparisons are inclusive at the lower boundary unless the narrative says otherwise; a value sitting exactly on a floor satisfies that floor."
    Design: Corner/calculations/no_eligible_receiving_branch_when_every_peer_is_one_cent_below_absorb_floor
    """
    market = setup_market()
    closing = validate_success(
        api_client.create_branch(branch_payload(market["id"]), STRATEGIST),
        expected_status=201,
    )
    validate_success(
        api_client.create_branch(
            branch_payload(
                market["id"],
                branch_code="RB-107",
                deposit_balance_cents=2399999999,
                monthly_transaction_count=4000,
                digital_adoption_bps=5000,
                annual_noninterest_expense_cents=31000000,
                annual_revenue_cents=34000000,
                fte_count=7,
                atm_count=1,
                opened_on="2009-05-01",
            ),
            STRATEGIST,
        ),
        expected_status=201,
    )

    validate_error(
        api_client.create_consolidation_case(
            consolidation_case_payload(closing["id"], closing["version"]), STRATEGIST
        ),
        ApiErrorId.ERR_NO_ELIGIBLE_RECEIVING_BRANCH.value,
    )

    untouched = read_branch(closing["id"])
    assert untouched["status"] == "ACTIVE"
    assert untouched["version"] == closing["version"]
    _, meta = validate_paginated(
        api_client.list_consolidation_cases(
            STRATEGIST, {"closing_branch_id": closing["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_03_every_new_record_in_the_chain_lands_in_its_declared_opening_state():
    """One pass creates a case, a forecast, an assessment, an employee disposition, a premises
    disposition, a transition wave and a de novo site plan; each opens in its declared state.

    PRD: "The new forecast is written in `ACTIVE` status, and the case's prior `ACTIVE` forecast, if any, transitions to `SUPERSEDED`; only the single `ACTIVE` forecast ever feeds the case's fields."
    PRD: "The server copies `source_branch_id` from the case's `closing_branch_id`, opens the record with `disposition_state` at `PROPOSED` and `notification_state` at `PENDING`, increments the case's `pending_disposition_count` by one, recomputes the case's `severance_pool_cents` and savings chain, and increments the case's `version`."
    PRD: "The record opens in `PENDING` status and the server copies `tenure_class` from the branch, which selects the fork the rest of the record follows."
    PRD: "The server copies `receiving_branch_id` from the case — the receiving branch is the resource whose calendar the wave occupies — and opens the campaign in `PLANNED` status."
    PRD: "The plan opens in `SITE_IDENTIFIED` status with `ramp_status` at `UNTRACKED`, `ramp_month_index` at zero, `ramp_attainment_bps` at zero, and `opened_branch_id` null."
    Design: Corner/state_machines/newly_created_entities_start_in_declared_initial_states
    """
    ctx = setup_market_with_branches()
    case = validate_success(
        api_client.create_consolidation_case(
            consolidation_case_payload(
                ctx["closing_branch"]["id"],
                ctx["closing_branch"]["version"],
                receiving_branch_id=ctx["receiving_branch"]["id"],
            ),
            STRATEGIST,
        ),
        expected_status=201,
    )
    assert case["status"] == "DRAFT"

    forecast = validate_success(
        api_client.create_retention_forecast(
            retention_forecast_payload(case["id"], case["version"]), STRATEGIST
        ),
        expected_status=201,
    )
    assert forecast["status"] == "ACTIVE"

    assessment = validate_success(
        api_client.create_impact_assessment(
            case["id"], impact_assessment_payload(), COMPLIANCE
        ),
        expected_status=201,
    )
    assert assessment["status"] == "DRAFT"
    assert assessment["finalized_on"] is None

    staff = validate_success(
        api_client.create_staff_disposition(
            staff_disposition_payload(
                case["id"],
                employee_ref="EMP-001",
                role_title="Personal Banker",
                tenure_months=84,
                annual_salary_cents=5200000,
                proposed_disposition="REDEPLOYMENT",
                target_branch_id=ctx["receiving_branch"]["id"],
            ),
            HR,
        ),
        expected_status=201,
    )
    assert staff["disposition_state"] == "PROPOSED"
    assert staff["notification_state"] == "PENDING"
    assert staff["notified_on"] is None

    premises = validate_success(
        api_client.create_property_disposition(
            leased_property_disposition_payload(
                ctx["closing_branch"]["id"], case["id"]
            ),
            REAL_ESTATE,
        ),
        expected_status=201,
    )
    assert premises["status"] == "PENDING"
    assert premises["marketing_started_on"] is None

    wave = validate_success(
        api_client.create_transition_campaign(
            transition_campaign_payload(case["id"]), COMPLIANCE
        ),
        expected_status=201,
    )
    assert wave["status"] == "PLANNED"
    assert wave["launched_on"] is None

    plan = validate_success(
        api_client.create_de_novo_plan(
            de_novo_plan_payload(
                ctx["market"]["id"],
                site_label="Harbor Metro Gateway",
                proposed_branch_code="RB-701",
                target_year1_deposits_cents=12000000000,
                capex_budget_cents=4500000000,
            ),
            STRATEGIST,
        ),
        expected_status=201,
    )
    assert plan["status"] == "SITE_IDENTIFIED"
    assert plan["ramp_status"] == "UNTRACKED"
    assert plan["ramp_month_index"] == 0
    assert plan["ramp_attainment_bps"] == 0
    assert plan["opened_branch_id"] is None

    assert read_branch(ctx["closing_branch"]["id"])["status"] == "UNDER_REVIEW"
    assert read_branch(ctx["receiving_branch"]["id"])["status"] == "ACTIVE"


def test_04_opening_a_case_puts_only_the_closing_branch_under_review():
    """The hold falls on the closing branch alone: its status and version move, the survivor is
    untouched, and the trade area's footprint does not shift because both statuses count.

    PRD: "When the create succeeds the branch transitions `ACTIVE → UNDER_REVIEW` and its `version` increments by one."
    PRD: "One subtlety follows directly from the counted set: moving a branch from `ACTIVE` to `UNDER_REVIEW` when a consolidation case opens against it does **not** change `own_branch_count`, because both statuses are counted, so the tier does not move at that point in the lifecycle."
    Design: Corner/state_machines/case_creation_moves_closing_branch_to_under_review
    """
    ctx = setup_market_with_branches()

    case = validate_success(
        api_client.create_consolidation_case(
            consolidation_case_payload(
                ctx["closing_branch"]["id"],
                ctx["closing_branch"]["version"],
                rationale_code="DIGITAL_MIGRATION",
                receiving_branch_id=ctx["receiving_branch"]["id"],
            ),
            STRATEGIST,
        ),
        expected_status=201,
    )

    closing = read_branch(ctx["closing_branch"]["id"])
    receiving = read_branch(ctx["receiving_branch"]["id"])
    market = validate_success(
        api_client.get_market_area(ctx["market"]["id"], STRATEGIST)
    )

    assert closing["status"] == "UNDER_REVIEW"
    assert closing["version"] == 2
    assert closing["deposit_balance_cents"] == 4800000000
    assert closing["absorbing_branch_id"] is None
    assert receiving["status"] == "ACTIVE"
    assert receiving["version"] == ctx["receiving_branch"]["version"]
    assert market["own_branch_count"] == 2
    assert market["saturation_tier"] == "SATURATED"
    assert case["status"] == "DRAFT"


def test_05_a_branch_already_held_by_a_draft_proposal_is_not_active():
    """A draft proposal is not an open case, but it has already taken the branch out of active
    service, so a second proposal on a freshly re-read version reports the status diagnosis.

    PRD: "if it is non-active for any other reason — sitting at `UNDER_REVIEW` under an existing draft case, still `DE_NOVO_RAMPING`, or already `CLOSED` — the refusal is `ERR_BRANCH_NOT_ACTIVE`."
    PRD: "If it already carries a case in `SUBMITTED`, `APPROVED`, `NOTICE_FILED`, `CLOSURE_EXECUTED` or `POST_CLOSE_MONITORING` status the create is refused with `ERR_BRANCH_HAS_OPEN_CASE`; if it is non-active for any other reason — sitting at `UNDER_REVIEW` under an existing draft case, still `DE_NOVO_RAMPING`, or already `CLOSED` — the refusal is `ERR_BRANCH_NOT_ACTIVE`."
    Design: Corner/validations/second_case_on_a_branch_held_by_a_draft_case_returns_branch_not_active
    """
    ctx = setup_market_with_branches()
    first = validate_success(
        api_client.create_consolidation_case(
            consolidation_case_payload(
                ctx["closing_branch"]["id"],
                ctx["closing_branch"]["version"],
                receiving_branch_id=ctx["receiving_branch"]["id"],
            ),
            STRATEGIST,
        ),
        expected_status=201,
    )
    held = read_branch(ctx["closing_branch"]["id"])
    assert held["version"] != ctx["closing_branch"]["version"]
    assert held["status"] == "UNDER_REVIEW"

    validate_error(
        api_client.create_consolidation_case(
            consolidation_case_payload(
                held["id"],
                held["version"],
                rationale_code="LEASE_EXPIRY",
                planned_closure_date="2027-01-15",
                receiving_branch_id=ctx["receiving_branch"]["id"],
            ),
            STRATEGIST,
        ),
        ApiErrorId.ERR_BRANCH_NOT_ACTIVE.value,
    )

    assert read_case(first["id"])["status"] == "DRAFT"
    _, meta = validate_paginated(
        api_client.list_consolidation_cases(
            STRATEGIST, {"closing_branch_id": held["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_06_an_open_case_outranks_the_generic_not_active_diagnosis():
    """Once the first proposal is submitted both guards are violated at once, and the caller is
    told about the open case rather than about the branch status.

    PRD: "This check deliberately outranks the plain not-active check at position 31, so that a branch tied up by an in-flight case reports the specific open-case diagnosis rather than the generic one."
    PRD: "The server evaluates guards in one fixed global order and returns the first failure it encounters; it never masks an earlier-ranked failure behind a later-ranked one."
    Design: Corner/validations/submitted_case_on_the_same_branch_outranks_the_not_active_diagnosis
    """
    ctx = setup_case_with_forecast()
    submitted = validate_success(
        api_client.submit_consolidation_case(ctx["case"]["id"], STRATEGIST)
    )
    assert submitted["status"] == "SUBMITTED"
    held = read_branch(ctx["closing_branch"]["id"])
    assert held["status"] == "UNDER_REVIEW"

    validate_error(
        api_client.create_consolidation_case(
            consolidation_case_payload(
                held["id"],
                held["version"],
                rationale_code="LEASE_EXPIRY",
                planned_closure_date="2027-01-15",
                receiving_branch_id=ctx["receiving_branch"]["id"],
            ),
            STRATEGIST,
        ),
        ApiErrorId.ERR_BRANCH_HAS_OPEN_CASE.value,
    )

    _, meta = validate_paginated(
        api_client.list_consolidation_cases(
            STRATEGIST, {"closing_branch_id": held["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_07_a_branch_version_consumed_by_a_reporting_period_no_longer_pins_the_create():
    """A reporting period recorded between the read and the write moves the branch version, so
    the client's token is stale; re-reading and resubmitting the identical body succeeds.

    PRD: "A `POST /distribution/consolidation-cases` request must carry `expected_branch_version` holding the client's last observed `version` of the branch named by `closing_branch_id`."
    PRD: "If the branch's `version` has advanced since the client read it, the create is rejected with `ERR_STALE_BRANCH_VERSION` (HTTP 412)."
    Design: Corner/cross-cutting complexity layers/case_create_with_a_stale_branch_version_returns_412
    """
    market = setup_market()
    closing = validate_success(
        api_client.create_branch(branch_payload(market["id"]), STRATEGIST),
        expected_status=201,
    )
    receiving = validate_success(
        api_client.create_branch(receiving_branch_payload(market["id"]), STRATEGIST),
        expected_status=201,
    )
    period = record_snapshot(
        closing["id"], period_label="2026-Q2", period_end_date="2026-06-30"
    )
    assert period["composite_score_bps"] == 4535

    body = consolidation_case_payload(
        closing["id"], closing["version"], receiving_branch_id=receiving["id"]
    )
    validate_error(
        api_client.create_consolidation_case(body, STRATEGIST),
        ApiErrorId.ERR_STALE_BRANCH_VERSION.value,
    )

    refreshed = read_branch(closing["id"])
    assert refreshed["version"] > closing["version"]
    assert refreshed["status"] == "ACTIVE"
    assert refreshed["performance_band"] == "STABLE"
    _, meta = validate_paginated(api_client.list_consolidation_cases(STRATEGIST))
    assert meta["total_count"] == 0

    body["expected_branch_version"] = refreshed["version"]
    case = validate_success(
        api_client.create_consolidation_case(body, STRATEGIST), expected_status=201
    )
    assert case["status"] == "DRAFT"

    after = read_branch(closing["id"])
    assert after["status"] == "UNDER_REVIEW"
    assert after["version"] > refreshed["version"]
