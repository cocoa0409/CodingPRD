"""Settlement mechanics on the financing side: the reserve sweep clamp, the funding
ceiling, the covenant postures that gate approval and payment, and the computed summary."""
from test_helpers import (
    ADMIN,
    FINANCE_A,
    FINANCE_B,
    OPERATOR,
    USER_FINANCE_A,
    USER_FINANCE_B,
    create_facility,
    create_statement,
    fund_reserve,
    read_facility_version,
    setup_facility_with_funded_reserve,
    setup_plant,
    setup_separated_plant_with_paid_statement,
    validate_error,
    validate_success,
)


def test_01_the_sweep_is_clamped_by_the_unfunded_reserve_not_by_the_rate(api):
    """The rate would sweep 467500 but only 200000 of the reserve is still unfunded.

    PRD: "Step six sets `reserve_sweep_cents` to the lesser of two figures: `after_fee_cents` multiplied by the sweep rate of 0.2500 and rounded half up to a whole cent, and the unfunded portion of the reserve, which is the facility's `reserve_target_cents` less its `reserve_balance_cents` or zero if that difference is negative."

    Design: Corner/calculations/calc_reserve_sweep_is_capped_by_the_unfunded_reserve_not_by_the_sweep_rate
    """
    facility = setup_facility_with_funded_reserve(3_800_000)
    assert facility["reserve_balance_cents"] == 3_800_000

    statement = validate_success(
        api.create_statement(
            {
                "facility_id": facility["id"],
                "period_start_date": "2026-09-01",
                "period_end_date": "2026-09-30",
                "gas_revenue_cents": 2_000_000,
                "expected_facility_version": facility["version"],
            },
            FINANCE_A,
        ),
        201,
    )
    assert statement["credit_revenue_cents"] == 0
    assert statement["gross_revenue_cents"] == 2_000_000
    assert statement["management_fee_rate"] == 0.0650
    assert statement["management_fee_cents"] == 130000
    assert statement["after_fee_cents"] == 1870000
    assert statement["reserve_sweep_cents"] == 200000
    assert statement["net_distributable_cents"] == 1670000
    assert statement["dscr_at_close"] == 1.247
    assert statement["total_dairy_share_cents"] == 0

    reread = validate_success(api.get_facility(facility["id"], ADMIN))
    assert reread["dscr_current"] == 1.247
    assert reread["distribution_posture"] == "RESTRICTED"


def test_02_an_overfunding_and_a_zero_deposit_share_one_error(api):
    """Both clauses of the funding rule answer with the reserve ceiling error.

    PRD: "The funding is accepted only if `reserve_balance_cents` plus `amount_cents` would not exceed `reserve_target_cents`; a request that would overfund the account, or one whose `amount_cents` is not strictly positive, is rejected with `ERR_RESERVE_TARGET_EXCEEDED`."

    Design: Corner/validations/validation_reserve_funding_must_be_positive_and_within_the_target
    """
    facility = create_facility()

    validate_error(
        api.fund_reserve(
            facility["id"],
            {"amount_cents": 4_500_000, "memo": "Over-funding attempt"},
            FINANCE_A,
        ),
        "ERR_RESERVE_TARGET_EXCEEDED",
        422,
    )
    validate_error(
        api.fund_reserve(
            facility["id"],
            {"amount_cents": 0, "memo": "Zero deposit attempt"},
            FINANCE_A,
        ),
        "ERR_RESERVE_TARGET_EXCEEDED",
        422,
    )

    unchanged = validate_success(api.get_facility(facility["id"], ADMIN))
    assert unchanged["reserve_balance_cents"] == 0
    assert unchanged["version"] == 1


def test_03_an_equity_injection_invalidates_a_clients_facility_version(api):
    """The waterfall reads the reserve balance, so the pre-funding version is refused.

    PRD: "Creating a `RevenueStatement` requires `expected_facility_version` as a mandatory, non-optional field in the request body, carrying the client's last observed `version` of the target `DigesterFacility`."

    Design: Corner/cross_cutting_layers/ccl_reserve_funding_bumps_the_facility_version_and_staleness_is_rejected
    """
    facility = create_facility()
    stale_version = facility["version"]
    funded = fund_reserve(facility["id"], 500_000)
    fresh_version = funded["version"]
    assert fresh_version > stale_version

    body = {
        "facility_id": facility["id"],
        "period_start_date": "2026-08-01",
        "period_end_date": "2026-08-31",
        "gas_revenue_cents": 2_010_000,
        "expected_facility_version": stale_version,
    }
    validate_error(api.create_statement(dict(body), FINANCE_A), "ERR_STALE_VERSION", 412)

    body["expected_facility_version"] = fresh_version
    statement = validate_success(api.create_statement(dict(body), FINANCE_A), 201)
    assert statement["management_fee_rate"] == 0.0650
    assert statement["management_fee_cents"] == 130650
    assert statement["after_fee_cents"] == 1879350
    assert statement["reserve_sweep_cents"] == 469838
    assert statement["net_distributable_cents"] == 1409512
    assert statement["status"] == "DRAFT"

    reread = validate_success(api.get_facility(facility["id"], ADMIN))
    assert reread["reserve_balance_cents"] == 500_000


def test_04_a_locked_covenant_posture_refuses_approval(api):
    """A gross of exactly 1000000 takes the inclusive tier-one fee and locks the facility.

    PRD: "It requires that the facility's `distribution_posture` is not `LOCKED`, otherwise `ERR_DISTRIBUTION_LOCKED`, and that `total_dairy_share_cents` is less than or equal to `net_distributable_cents`, otherwise `ERR_SHARE_EXCEEDS_DISTRIBUTABLE`."

    Design: Corner/validations/validation_locked_distribution_posture_blocks_approval
    """
    facility = create_facility()
    statement = create_statement(
        facility["id"],
        gas_revenue_cents=1_000_000,
        period_start_date="2026-08-01",
        period_end_date="2026-08-31",
    )
    assert statement["management_fee_rate"] == 0.0800
    assert statement["management_fee_cents"] == 80000
    assert statement["after_fee_cents"] == 920000
    assert statement["reserve_sweep_cents"] == 230000
    assert statement["net_distributable_cents"] == 690000
    assert statement["dscr_at_close"] == 0.613

    validate_error(
        api.approve_statement(
            statement["id"],
            {"approval_note": "Attempted approval under a locked covenant"},
            FINANCE_A,
        ),
        "ERR_DISTRIBUTION_LOCKED",
        409,
    )

    unchanged = validate_success(api.get_statement(statement["id"], FINANCE_A))
    assert unchanged["status"] == "DRAFT"
    assert unchanged["approved_by_user_id"] is None
    locked = validate_success(api.get_facility(facility["id"], ADMIN))
    assert locked["distribution_posture"] == "LOCKED"


def test_05_a_distribution_override_unblocks_approval_and_leaves_ops_alone(api):
    """The waiver softens LOCKED to RESTRICTED without touching the biological dimension.

    PRD: "An `OPS` override moves `ops_posture` from `UPSET` to `RESTRICTED`; a `DISTRIBUTION` override moves `distribution_posture` from `LOCKED` to `RESTRICTED`."

    Design: Corner/endpoints/endpoint_posture_override_softens_the_distribution_dimension_only
    """
    facility = create_facility()
    statement = create_statement(
        facility["id"],
        gas_revenue_cents=1_000_000,
        period_start_date="2026-08-01",
        period_end_date="2026-08-31",
    )
    assert statement["dscr_at_close"] == 0.613

    overridden = validate_success(
        api.override_posture(
            facility["id"],
            {
                "dimension": "DISTRIBUTION",
                "justification": "Lender waiver letter dated 2026-08-05",
            },
            ADMIN,
        )
    )
    assert overridden["posture_override_active"] is True
    assert overridden["distribution_posture"] == "RESTRICTED"
    assert overridden["ops_posture"] == "STABLE"
    assert overridden["dscr_current"] == 0.613

    approved = validate_success(
        api.approve_statement(
            statement["id"], {"approval_note": "Approved under the lender waiver"}, FINANCE_A
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == USER_FINANCE_A
    assert approved["net_distributable_cents"] == 690000


def test_06_a_gross_basis_share_can_outgrow_the_distributable_pool(api):
    """0.9500 of the pre-fee gross is more than the post-sweep pool can pay.

    PRD: "**Budget ceilings**, at the same rank: `ERR_NITROGEN_BUDGET_EXCEEDED` and `ERR_SHARE_EXCEEDS_DISTRIBUTABLE` (both 422)."

    Design: Corner/validations/validation_dairy_shares_above_the_distributable_pool_block_approval
    """
    plant = setup_plant(
        agreement_overrides={"revenue_share_pct": 0.9500, "revenue_share_basis": "GROSS"}
    )
    statement = create_statement(
        plant["facility"]["id"],
        gas_revenue_cents=2_000_000,
        period_start_date="2026-08-01",
        period_end_date="2026-08-31",
    )
    assert statement["net_distributable_cents"] == 1402500
    assert statement["total_dairy_share_cents"] == 1900000
    assert statement["dscr_at_close"] == 1.247

    validate_error(
        api.approve_statement(
            statement["id"],
            {"approval_note": "Attempted approval of an over-committed pool"},
            FINANCE_A,
        ),
        "ERR_SHARE_EXCEEDS_DISTRIBUTABLE",
        422,
    )

    unchanged = validate_success(api.get_statement(statement["id"], FINANCE_A))
    assert unchanged["status"] == "DRAFT"
    facility = validate_success(api.get_facility(plant["facility"]["id"], ADMIN))
    assert facility["dairy_share_paid_cents"] == 0


def test_07_an_approved_period_is_owned_and_cannot_be_superseded(api):
    """A DRAFT would have been retired; an APPROVED statement answers with a conflict.

    PRD: "No statement on the same facility whose status is `APPROVED` or `PAID` may have a period overlapping the requested period, or the create is rejected with `ERR_STATEMENT_PERIOD_OVERLAP`."

    Design: Corner/validations/validation_approved_statement_blocks_an_overlapping_settlement_period
    """
    facility = create_facility()
    august = create_statement(
        facility["id"],
        gas_revenue_cents=2_010_000,
        period_start_date="2026-08-01",
        period_end_date="2026-08-31",
    )
    validate_success(
        api.approve_statement(
            august["id"], {"approval_note": "August settlement approved"}, FINANCE_A
        )
    )

    validate_error(
        api.create_statement(
            {
                "facility_id": facility["id"],
                "period_start_date": "2026-08-15",
                "period_end_date": "2026-09-15",
                "gas_revenue_cents": 500_000,
                "expected_facility_version": read_facility_version(facility["id"]),
            },
            FINANCE_B,
        ),
        "ERR_STATEMENT_PERIOD_OVERLAP",
        409,
    )

    untouched = validate_success(api.get_statement(august["id"], FINANCE_A))
    assert untouched["status"] == "APPROVED"
    assert untouched["net_distributable_cents"] == 1409512
    assert untouched["superseded_by_statement_id"] is None
    reread = validate_success(api.get_facility(facility["id"], ADMIN))
    assert reread["distribution_posture"] == "OPEN"


def test_08_the_approver_of_a_statement_cannot_release_its_payment(api):
    """The bar is on the user id; the same role in another pair of hands pays it.

    PRD: "The acting `X-User-ID` must differ from `approved_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/rbac_the_approver_of_a_statement_may_not_release_its_payment
    """
    facility = create_facility()
    statement = create_statement(
        facility["id"],
        gas_revenue_cents=2_010_000,
        period_start_date="2026-08-01",
        period_end_date="2026-08-31",
    )
    validate_success(
        api.approve_statement(
            statement["id"], {"approval_note": "August settlement approved"}, FINANCE_A
        )
    )

    validate_error(
        api.pay_statement(
            statement["id"], {"payment_reference": "ACH-2026-08-0001"}, FINANCE_A
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )

    paid = validate_success(
        api.pay_statement(
            statement["id"], {"payment_reference": "ACH-2026-08-0002"}, FINANCE_B
        )
    )
    assert paid["status"] == "PAID"
    assert paid["approved_by_user_id"] == USER_FINANCE_A
    assert paid["paid_by_user_id"] == USER_FINANCE_B

    ledger = validate_success(api.get_facility(facility["id"], ADMIN))
    assert ledger["retained_to_date_cents"] == 1409512


def test_09_the_financial_summary_recomputes_the_mass_invariant_on_read(api):
    """A pure read: the conserved mass figures and the cumulative cash ledger together.

    PRD: "Two computed read operations exist specifically to expose these invariants: a facility financial summary that recomputes the mass-control figures before responding and also surfaces `gross_revenue_to_date_cents`, `dairy_share_paid_cents` and `retained_to_date_cents`, and a pathway credit ledger that recomputes the credit-control figures before responding."

    Design: Corner/endpoints/endpoint_financial_summary_recomputes_the_mass_invariant_on_read
    """
    plant = setup_separated_plant_with_paid_statement()
    assert plant["statement"]["status"] == "PAID"

    summary = validate_success(
        api.get_financial_summary(plant["facility"]["id"], OPERATOR)
    )
    assert summary["total_manure_received_tonnes"] == 150.000
    assert summary["unseparated_manure_tonnes"] == 0.000
    assert summary["digestate_solids_produced_tonnes"] == 26.000
    assert summary["digestate_liquid_produced_tonnes"] == 124.000
    assert summary["mass_control_residual_tonnes"] == 0.000
    assert summary["gross_revenue_to_date_cents"] == 2_010_000
    assert summary["dairy_share_paid_cents"] == 310092
    assert summary["retained_to_date_cents"] == 1099420

    facility = validate_success(api.get_facility(plant["facility"]["id"], ADMIN))
    assert facility["reserve_balance_cents"] == 469838
    assert facility["dscr_current"] == 1.253
    assert facility["distribution_posture"] == "OPEN"
