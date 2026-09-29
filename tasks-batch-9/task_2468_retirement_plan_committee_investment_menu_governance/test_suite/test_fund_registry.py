"""The candidate fund catalogue and the asset-class slots that funds are seated
into: what a fund read returns for an id nobody minted, which creation payloads
the field domains of PRD 3.3 reject, what a freshly created slot looks like, how
the fund listing pages and filters, and why a fund belonging to another plan can
never be seated (PRD 2.12 priority 35).
"""

from test_helpers.api_client import paginate_params
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    NON_EXISTENT_UUID,
    assert_capacity_triple,
    assert_cents,
    assert_common_fields,
    assert_contains_ids,
    assert_excludes_ids,
    assert_fields,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    Paths,
    fund_payload,
    seat_fund_payload,
    slot_payload,
    target_date_fund_payload,
    without,
)
from test_helpers.fixtures import (
    create_slot,
    read_fund,
    read_plan,
    read_slot,
    register_plan,
)
from test_helpers.test_users import auditor_headers, consultant_headers
from test_helpers.types import (
    AssetClass,
    CreditAccrualStatus,
    FundMenuStatus,
    ShareClass,
    SlotDesignation,
    SlotStatus,
    WatchStatus,
)


# --------------------------------------------------------------------------
# Reading a fund that does not exist
# --------------------------------------------------------------------------


def test_fund_read_with_an_unknown_id_is_a_not_found(api):
    """A fund read for an id nobody minted is a not-found, even before any plan
    has been registered.

    Design: Corner/entities/fund_read_with_unknown_id_returns_resource_not_found
    """
    response = api.get(Paths.fund(NON_EXISTENT_UUID), auditor_headers())

    error = validate_error(response, ApiErrorId.RESOURCE_NOT_FOUND)
    assert response.json()["response_type"] == "error", response.json()["response_type"]
    assert error["message"], error

    # Nothing was created by the failed read.
    _rows, meta = validate_paginated(
        api.get(Paths.FUNDS, auditor_headers(), paginate_params(limit=10, offset=0))
    )
    assert meta["total_count"] == 0, meta


# --------------------------------------------------------------------------
# Fund creation field domains
# --------------------------------------------------------------------------


def test_fund_create_without_a_style_drift_r2_is_rejected(api, adopted_ips):
    """style_drift_r2 has no declared default, so a creation payload that omits it
    is an invalid request and no fund row appears.

    Design: Corner/entities/fund_create_missing_style_drift_r2_is_rejected_as_invalid_request
    """
    ctx = adopted_ips

    payload = without(
        fund_payload(
            ctx.plan_id,
            ticker="NOR2X",
            fund_name="Northgate Real Assets R3",
            asset_class_code=AssetClass.REAL_ASSETS,
            share_class_code=ShareClass.R3,
            gross_expense_ratio_bps=70,
            net_expense_ratio_bps=70,
            revenue_share_bps=15,
            peer_median_expense_bps=65,
            track_record_quarters=20,
            manager_tenure_quarters=12,
            plan_assets_cents=0,
        ),
        "style_drift_r2",
    )
    response = api.post(Paths.FUNDS, payload, consultant_headers())

    validate_error(response, ApiErrorId.INVALID_REQUEST)

    _rows, meta = validate_paginated(
        api.get(
            Paths.FUNDS,
            auditor_headers(),
            paginate_params(
                plan_id=ctx.plan_id, asset_class_code=AssetClass.REAL_ASSETS
            ),
        )
    )
    assert meta["total_count"] == 0, meta


def test_fund_create_with_a_net_expense_above_its_gross_is_rejected(api, adopted_ips):
    """A net expense ratio may not exceed the gross expense ratio of the same
    fund.

    Design: Corner/entities/fund_create_with_net_above_gross_expense_is_rejected
    """
    ctx = adopted_ips

    response = api.post(
        Paths.FUNDS,
        fund_payload(
            ctx.plan_id,
            ticker="INVRT",
            fund_name="Inverted Fee Stable Value",
            asset_class_code=AssetClass.STABLE_VALUE,
            share_class_code=ShareClass.INSTITUTIONAL,
            gross_expense_ratio_bps=55,
            net_expense_ratio_bps=60,
            revenue_share_bps=0,
            peer_median_expense_bps=50,
            track_record_quarters=48,
            manager_tenure_quarters=30,
            style_drift_r2=0.9100,
            plan_assets_cents=0,
        ),
        consultant_headers(),
    )

    validate_error(response, ApiErrorId.INVALID_REQUEST)

    _rows, meta = validate_paginated(
        api.get(
            Paths.FUNDS,
            auditor_headers(),
            paginate_params(
                plan_id=ctx.plan_id, asset_class_code=AssetClass.STABLE_VALUE
            ),
        )
    )
    assert meta["total_count"] == 0, meta


def test_target_date_suite_create_without_a_landing_point_age_is_rejected(api, adopted_ips):
    """A fund flagged as a target-date suite must carry all four glidepath fields;
    omitting the landing point age is an invalid request.

    Design: Corner/entities/fund_create_with_net_above_gross_expense_is_rejected
    """
    ctx = adopted_ips

    payload = without(
        target_date_fund_payload(
            ctx.plan_id,
            ticker="TDHOL",
            fund_name="Holloway Target Retirement Suite",
        ),
        "landing_point_age",
    )
    response = api.post(Paths.FUNDS, payload, consultant_headers())

    validate_error(response, ApiErrorId.INVALID_REQUEST)

    _rows, meta = validate_paginated(
        api.get(
            Paths.FUNDS,
            auditor_headers(),
            paginate_params(
                plan_id=ctx.plan_id, asset_class_code=AssetClass.TARGET_DATE
            ),
        )
    )
    assert meta["total_count"] == 0, meta


# --------------------------------------------------------------------------
# Slot creation
# --------------------------------------------------------------------------


def test_slot_create_mints_its_system_fields_and_pins_the_adopted_statement(api, adopted_ips):
    """A new asset-class slot is EMPTY with no fund, no at-risk history and no
    prior review status, pinned to the plan's adopted policy statement, and it
    consumes none of the plan's capacity.

    Design: Corner/entities/asset_class_slot_system_fields_and_ips_pin_are_server_minted
    """
    ctx = adopted_ips

    response = api.post(
        Paths.SLOTS,
        slot_payload(
            ctx.plan_id,
            ctx.ips_id,
            asset_class_code=AssetClass.US_LARGE_CAP,
            designation=SlotDesignation.CORE,
            slot_index=1,
        ),
        consultant_headers(),
    )
    slot = validate_success(response, 201)

    assert_common_fields(slot)
    assert_fields(
        slot,
        plan_id=ctx.plan_id,
        # PRD 3.3: the slot records the statement that defined it, and creation is
        # only legal while exactly one statement is ADOPTED.
        ips_id=ctx.ips_id,
        asset_class_code=AssetClass.US_LARGE_CAP,
        designation=SlotDesignation.CORE,
        slot_index=1,
        status=SlotStatus.EMPTY,
        current_fund_id=None,
        at_risk_since_quarter_index=None,
        status_before_last_review=None,
        version=1,
    )

    # PRD 2.10: only ACTIVE, AT_RISK and PENDING_REPLACEMENT slots are occupied.
    plan = read_plan(api, ctx.plan_id)
    assert_capacity_triple(plan, occupied=0, reserved=0, available=6)


# --------------------------------------------------------------------------
# Listing the candidate universe
# --------------------------------------------------------------------------


def test_funds_list_returns_only_the_requested_page_of_the_universe(api, full_menu):
    """A two-row window over a seven-fund catalogue returns two rows and reports
    the whole total with more pages to come.

    Design: Corner/entities/funds_list_paginates_and_filters_the_candidate_universe
    """
    ctx = full_menu

    response = api.get(
        Paths.FUNDS,
        auditor_headers(),
        paginate_params(limit=2, offset=0, plan_id=ctx.plan_id),
    )
    rows, meta = validate_paginated(response)

    assert response.json()["response_type"] == "array", response.json()["response_type"]
    assert len(rows) == 2, rows
    assert meta["limit"] == 2, meta
    assert meta["offset"] == 0, meta
    assert meta["total_count"] == 7, meta
    assert meta["has_more"] is True, meta

    tail_rows, tail_meta = validate_paginated(
        api.get(
            Paths.FUNDS,
            auditor_headers(),
            paginate_params(limit=2, offset=6, plan_id=ctx.plan_id),
        )
    )
    assert len(tail_rows) == 1, tail_rows
    assert tail_meta["has_more"] is False, tail_meta


def test_funds_list_filtered_to_candidates_excludes_the_seated_funds(api, full_menu):
    """Filtering the catalogue by menu status returns exactly the two unseated
    funds; the seated ones read ACTIVE and accruing revenue credit.

    Design: Corner/entities/funds_list_paginates_and_filters_the_candidate_universe
    """
    ctx = full_menu

    rows, meta = validate_paginated(
        api.get(
            Paths.FUNDS,
            auditor_headers(),
            paginate_params(
                limit=10,
                offset=0,
                plan_id=ctx.plan_id,
                menu_status=FundMenuStatus.CANDIDATE,
            ),
        )
    )
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is False, meta
    assert_contains_ids(rows, ctx.fund("lc_b")["id"], ctx.fund("td_thru")["id"])
    assert_excludes_ids(rows, ctx.fund("lc_a")["id"], ctx.fund("bond")["id"])
    for row in rows:
        assert row["menu_status"] == FundMenuStatus.CANDIDATE, row

    # PRD 3.3: seating turns the fund ACTIVE and starts its revenue credit accrual.
    seated = read_fund(api, ctx.fund("lc_a")["id"])
    assert_fields(
        seated,
        menu_status=FundMenuStatus.ACTIVE,
        credit_accrual_status=CreditAccrualStatus.ACCRUING,
        watch_status=WatchStatus.CLEAR,
        qdia_flag=False,
    )

    plan = read_plan(api, ctx.plan_id)
    assert_capacity_triple(plan, occupied=5, reserved=0, available=1)
    # PRD 2.10: the total is the sum over funds that hold a menu position.
    assert_cents(plan["total_plan_assets_cents"], 1200000000, "total_plan_assets_cents")


# --------------------------------------------------------------------------
# Seating a fund that belongs to another plan
# --------------------------------------------------------------------------


def test_seating_a_fund_owned_by_another_plan_is_a_cross_plan_reference(api, full_menu):
    """A slot may only be seated with a fund registered under its own plan; a
    fund belonging to a second plan is a cross-plan reference and changes
    nothing on either side.

    Design: Corner/entities/seating_a_fund_owned_by_another_plan_returns_cross_plan_reference
    """
    ctx = full_menu

    other_plan = register_plan(
        api,
        plan_name="Harbor Freight Cooperative 403(b)",
        plan_sponsor_name="Harbor Freight Cooperative",
        plan_type="403B",
        participant_account_count=400,
        menu_slot_capacity=3,
    )
    alien_fund = get_success_data(
        api.post(
            Paths.FUNDS,
            fund_payload(
                other_plan["id"],
                ticker="EMKTX",
                fund_name="Harbor Emerging Markets Institutional",
                asset_class_code=AssetClass.EMERGING_MKTS,
                share_class_code=ShareClass.INSTITUTIONAL,
                gross_expense_ratio_bps=40,
                net_expense_ratio_bps=40,
                revenue_share_bps=0,
                peer_median_expense_bps=45,
                track_record_quarters=36,
                manager_tenure_quarters=20,
                style_drift_r2=0.9300,
                plan_assets_cents=0,
            ),
            consultant_headers(),
        ),
        201,
    )
    assert alien_fund["plan_id"] == other_plan["id"]

    slot = create_slot(
        ctx,
        "emerging",
        AssetClass.EMERGING_MKTS,
        6,
        designation=SlotDesignation.SPECIALTY,
    )

    response = api.post(
        Paths.seat_fund(slot["id"]),
        seat_fund_payload(alien_fund["id"]),
        consultant_headers(),
    )
    validate_error(response, ApiErrorId.CROSS_PLAN_REFERENCE)

    slot_after = read_slot(api, slot["id"])
    assert_fields(slot_after, status=SlotStatus.EMPTY, current_fund_id=None)

    fund_after = read_fund(api, alien_fund["id"])
    assert_fields(
        fund_after,
        plan_id=other_plan["id"],
        menu_status=FundMenuStatus.CANDIDATE,
        credit_accrual_status=CreditAccrualStatus.NOT_ACCRUING,
    )

    plan = read_plan(api, ctx.plan_id)
    assert_capacity_triple(plan, occupied=5, reserved=0, available=1)
