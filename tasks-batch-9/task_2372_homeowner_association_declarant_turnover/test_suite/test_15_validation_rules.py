"""Individual validation rules: the statutory clock, scoped uniqueness and the ladder."""

from typing import Any, Dict

import pytest
from test_helpers import (
    DECLARANT_HEADERS,
    ERR_DUPLICATE_LOT_NUMBER,
    ERR_FIXED_TURNOVER_DATE_NOT_REACHED,
    ERR_INVALID_REQUEST,
    ERR_SUBSIDY_STILL_ACTIVE,
    ERR_TURNOVER_CASE_NOT_FOUND,
    FUNDING_METHOD_CASH_FLOW,
    NON_EXISTENT_UUID,
    TRIGGER_BASIS_FIXED_DATE,
    ApiClient,
    assert_instant,
    assert_pct,
    assert_schedule_waterfall,
    build_adopted_reserve_study,
    certify_trigger_payload,
    create_schedule_with_fresh_version,
    do_advance_financial,
    do_certify_trigger,
    do_close_sale,
    lot_payload,
    make_transition_committee_headers,
    read_association,
    read_turnover_case,
    records_item_payload,
    seed_association,
    seed_audit_engagement,
    seed_lot,
    seed_turnover_case,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

# ─── Ivywick: the declaration date is an inclusive bound ───────────────


@pytest.fixture
def ivywick(api: ApiClient) -> Dict[str, Any]:
    """A community whose outside turnover date is still four months away."""
    association = seed_association(
        api,
        name="Ivywick",
        total_planned_lots=6,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2026-12-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=0,
        reserve_claim_pool_cents=0,
        declarant_monthly_subsidy_cents=0,
    )
    case = seed_turnover_case(api, association["id"], total_seats=3)
    return {
        "association": association,
        "case": case,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestFixedDateCertificationBound:
    """One second early is refused; the instant itself certifies."""

    def test_certifying_before_the_declaration_instant_is_refused_twice(
        self, api: ApiClient, ivywick: Dict[str, Any]
    ) -> None:
        """Neither the default clock nor 23:59:59 the night before is enough.

        "On the `FIXED_DATE` basis, the logical clock must have reached the
        association's `fixed_turnover_date`, with the instant itself sufficient;
        earlier is `ERR_FIXED_TURNOVER_DATE_NOT_REACHED`."

        Design: Corner/validations/fixed_date_certification_before_the_declaration_date_is_rejected
        """
        case_id = ivywick["case"]["id"]
        committee = ivywick["committee_headers"]
        request = certify_trigger_payload(trigger_basis=TRIGGER_BASIS_FIXED_DATE)

        validate_error(
            api.certify_trigger(case_id, request, committee),
            ERR_FIXED_TURNOVER_DATE_NOT_REACHED,
        )

        set_clock(api, "2026-11-30T23:59:59Z")
        validate_error(
            api.certify_trigger(case_id, request, committee),
            ERR_FIXED_TURNOVER_DATE_NOT_REACHED,
        )

        case = read_turnover_case(api, case_id)
        assert case["governance_status"] == "DECLARANT_CONTROL"
        assert case["trigger_basis"] is None, (
            "A refused certification records no attempt"
        )
        assert case["trigger_certified_at"] is None

    def test_the_declaration_instant_itself_certifies_the_trigger(
        self, api: ApiClient, ivywick: Dict[str, Any]
    ) -> None:
        """At exactly 2026-12-01T00:00:00Z the same request succeeds.

        "the supplied `trigger_basis` is recorded, `trigger_certified_at` is
        stamped from the logical clock, `trigger_certified_by_user_id` captures
        the acting `X-User-ID`, `owner_elected_seats_required` is computed"

        Design: Corner/validations/fixed_date_certification_before_the_declaration_date_is_rejected
        """
        association_id = ivywick["association"]["id"]
        case_id = ivywick["case"]["id"]

        set_clock(api, "2026-11-30T23:59:59Z")
        validate_error(
            api.certify_trigger(
                case_id,
                certify_trigger_payload(trigger_basis=TRIGGER_BASIS_FIXED_DATE),
                ivywick["committee_headers"],
            ),
            ERR_FIXED_TURNOVER_DATE_NOT_REACHED,
        )

        set_clock(api, "2026-12-01T00:00:00Z")
        certified = do_certify_trigger(
            api, case_id, association_id, TRIGGER_BASIS_FIXED_DATE
        )
        assert certified["trigger_basis"] == TRIGGER_BASIS_FIXED_DATE
        assert_instant(
            certified["trigger_certified_at"],
            "2026-12-01T00:00:00Z",
            "trigger_certified_at",
        )
        assert certified["governance_status"] == "ELECTION_CALLED"
        assert certified["owner_elected_seats_required"] == 2


# ─── Jesmond Vale and Kirkmoor: uniqueness is per association ──────────


@pytest.fixture
def two_communities(api: ApiClient) -> Dict[str, Any]:
    """Two declarations, the first already carrying lot L-100."""
    jesmond_vale = seed_association(
        api,
        name="Jesmond Vale",
        total_planned_lots=4,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2027-01-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=0,
        reserve_claim_pool_cents=0,
        declarant_monthly_subsidy_cents=0,
    )
    kirkmoor = seed_association(
        api,
        name="Kirkmoor",
        total_planned_lots=4,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2027-01-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=0,
        reserve_claim_pool_cents=0,
        declarant_monthly_subsidy_cents=0,
    )
    lot = seed_lot(api, jesmond_vale["id"], "L-100")
    return {
        "jesmond_vale": jesmond_vale,
        "kirkmoor": kirkmoor,
        "lot": lot,
    }


class TestLotNumberUniquenessScope:
    """The plat number collides inside one community and travels between two."""

    def test_the_repeat_is_refused_here_and_accepted_next_door(
        self, api: ApiClient, two_communities: Dict[str, Any]
    ) -> None:
        """Two distinct rows end up sharing the lot number L-100.

        "The `Declarant` records each platted lot against an `association_id` with
        the `lot_number` printed on the recorded plat (1 to 16 characters, unique
        within the association — a repeat is `ERR_DUPLICATE_LOT_NUMBER`)."

        Design: Corner/validations/duplicate_lot_number_is_scoped_to_a_single_association
        """
        first_id = two_communities["jesmond_vale"]["id"]
        second_id = two_communities["kirkmoor"]["id"]

        validate_error(
            api.create_lot(lot_payload(first_id, "L-100"), DECLARANT_HEADERS),
            ERR_DUPLICATE_LOT_NUMBER,
        )

        elsewhere = validate_success(
            api.create_lot(lot_payload(second_id, "L-100"), DECLARANT_HEADERS),
            expected_status=201,
        )
        assert elsewhere["lot_number"] == "L-100"
        assert elsewhere["association_id"] == second_id
        assert elsewhere["id"] != two_communities["lot"]["id"]

        _first_rows, first_meta = validate_paginated(
            api.list_lots(first_id, make_transition_committee_headers(first_id))
        )
        assert first_meta["total_count"] == 1, "The refused repeat created no row"

        _second_rows, second_meta = validate_paginated(
            api.list_lots(second_id, make_transition_committee_headers(second_id))
        )
        assert second_meta["total_count"] == 1


# ─── Lowther Green: no re-forecast while the subsidy runs ─────────────


@pytest.fixture
def lowther_green(api: ApiClient) -> Dict[str, Any]:
    """Three closed lots, an adopted study and a subsidy that has not ended."""
    association = seed_association(
        api,
        name="Lowther Green",
        total_planned_lots=3,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2027-01-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=1200000,
        reserve_claim_pool_cents=0,
        declarant_monthly_subsidy_cents=150000,
    )
    case = seed_turnover_case(api, association["id"], total_seats=3)
    for index, closing_date in enumerate(
        ("2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z"), start=1
    ):
        lot = seed_lot(api, association["id"], f"L-{index}")
        do_close_sale(api, lot["id"], closing_date)
    study = build_adopted_reserve_study(
        api,
        association["id"],
        funding_method=FUNDING_METHOD_CASH_FLOW,
        planned_annual_contribution_cents=700000,
        projected_annual_expenditure_cents=500000,
    )
    engagement = seed_audit_engagement(
        api, association["id"], "2026-01-01T00:00:00Z", "2026-06-30T00:00:00Z"
    )
    return {
        "association": association,
        "case": case,
        "study": study,
        "engagement": engagement,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestReforecastWaitsForTheSubsidyToEnd:
    """The adopted study is not enough while the financial dimension is open."""

    def test_the_schedule_is_refused_while_the_financial_dimension_is_subsidy_active(
        self, api: ApiClient, lowther_green: Dict[str, Any]
    ) -> None:
        """The other precondition already holds, so only the subsidy rule answers.

        "The association's financial dimension must have left `SUBSIDY_ACTIVE`,
        else `ERR_SUBSIDY_STILL_ACTIVE`, and an `ADOPTED` reserve study must
        exist, else `ERR_RESERVE_STUDY_NOT_ADOPTED`."

        Design: Corner/validations/assessment_schedule_creation_while_the_subsidy_is_active_is_rejected
        """
        association_id = lowther_green["association"]["id"]
        assert lowther_green["study"]["status"] == "ADOPTED"
        assert lowther_green["study"]["recommended_annual_contribution_cents"] == 700000

        validate_error(
            create_schedule_with_fresh_version(api, association_id, 2027, 4000000),
            ERR_SUBSIDY_STILL_ACTIVE,
        )

        _rows, meta = validate_paginated(
            api.list_assessment_schedules(
                association_id, lowther_green["committee_headers"]
            )
        )
        assert meta["total_count"] == 0, "The refused creation persisted nothing"

    def test_ending_the_subsidy_lets_the_same_request_through_with_no_offset(
        self, api: ApiClient, lowther_green: Dict[str, Any]
    ) -> None:
        """A subsidy ending in October 2026 offsets none of fiscal 2027.

        "`subsidy_offset_cents` is the association's
        `declarant_monthly_subsidy_cents` multiplied by the number of months of
        the fiscal year still covered by the subsidy, counted as those of the
        year's twelve year-month labels that sort strictly before the year-month
        of the association's `subsidy_end_date`, and taken as zero when that date
        is null."

        Design: Corner/validations/assessment_schedule_creation_while_the_subsidy_is_active_is_rejected
        """
        association_id = lowther_green["association"]["id"]
        case_id = lowther_green["case"]["id"]

        validate_error(
            create_schedule_with_fresh_version(api, association_id, 2027, 4000000),
            ERR_SUBSIDY_STILL_ACTIVE,
        )

        advanced = do_advance_financial(
            api, case_id, association_id, "2026-10-01T00:00:00Z"
        )
        assert advanced["financial_status"] == "AUDIT_IN_PROGRESS"

        association = read_association(api, association_id)
        assert_instant(
            association["subsidy_end_date"], "2026-10-01T00:00:00Z", "subsidy_end_date"
        )

        schedule = validate_success(
            create_schedule_with_fresh_version(api, association_id, 2027, 4000000),
            expected_status=201,
        )
        assert_schedule_waterfall(
            schedule,
            billable_lot_count=3,
            reserve_contribution=700000,
            subsidy_offset=0,
            annual_requirement=4700000,
            per_lot_monthly=130556,
            annual_total=4700016,
            residual=16,
            increase_pct=0.00,
            owner_vote_required=False,
        )
        assert schedule["status"] == "DRAFT"


# ─── Mearnsbeck: body reference existence outranks body shape ──────────


@pytest.fixture
def mearnsbeck(api: ApiClient) -> Dict[str, Any]:
    """One case that can act as the resolvable parent in the control call."""
    association = seed_association(
        api,
        name="Mearnsbeck",
        total_planned_lots=6,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2027-01-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=0,
        reserve_claim_pool_cents=0,
        declarant_monthly_subsidy_cents=0,
    )
    case = seed_turnover_case(api, association["id"], total_seats=3)
    return {
        "association": association,
        "case": case,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestBodyReferenceOutranksBodyShape:
    """A request that is both unresolvable and malformed reports the 404."""

    def test_the_unknown_parent_answers_before_the_illegal_enum(
        self, api: ApiClient, mearnsbeck: Dict[str, Any]
    ) -> None:
        """With a real parent the identical illegal category surfaces as a 400.

        "**Body reference existence.** Every foreign key in the body resolves and
        cross-entity bodies agree, else the matching 404 code."

        Design: Corner/validations/unresolved_body_foreign_key_outranks_body_shape_validation
        """
        case_id = mearnsbeck["case"]["id"]

        validate_error(
            api.create_records_item(
                records_item_payload(
                    NON_EXISTENT_UUID, "NOT_A_CATEGORY", required=True
                ),
                DECLARANT_HEADERS,
            ),
            ERR_TURNOVER_CASE_NOT_FOUND,
        )
        validate_error(
            api.create_records_item(
                records_item_payload(case_id, "NOT_A_CATEGORY", required=True),
                DECLARANT_HEADERS,
            ),
            ERR_INVALID_REQUEST,
        )

        _rows, meta = validate_paginated(
            api.list_records_items(case_id, mearnsbeck["committee_headers"])
        )
        assert meta["total_count"] == 0, "Neither rejected call created a row"

        case = read_turnover_case(api, case_id)
        assert_pct(
            case["records_transfer_completeness_pct"],
            100.00,
            "records_transfer_completeness_pct",
        )
