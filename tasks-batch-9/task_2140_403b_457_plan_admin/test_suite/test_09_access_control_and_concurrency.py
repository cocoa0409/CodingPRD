"""Authentication, role and ownership gates, optimistic concurrency, and the clock."""

from datetime import datetime

from test_helpers import (
    ApiErrorId,
    NO_AUTH_HEADERS,
    contract_version,
    create_active_plan,
    create_plan_payload,
    create_remittance_batch_payload,
    make_line_item,
    make_officer_headers,
    make_operator_headers,
    make_sponsor_headers,
    make_vendor_headers,
    open_contract,
    register_employer,
    register_nonqualified_employer,
    register_participant,
    register_vendor,
    report_balance,
    set_clock,
    setup_basic_403b,
    setup_plan_env,
    validate_error,
    validate_paginated,
    validate_success,
)


def _as_instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_future_withholding_date_beats_the_total_mismatch(api):
    """PRD §2.6 rung 29: "No supplied date lies in the future — otherwise
    `ERR_DATE_IN_FUTURE` (HTTP 422). The dates policed are `withholding_date`,
    `deposit_date`, `issued_date`, `as_of_date`, `data_current_through_date`,
    `fulfillment_date` and `execution_date`, on remittance batch creation, deposit
    recording, notice filing, balance reporting, data-feed posting, request fulfilment and
    movement execution respectively."
    PRD §2.6: "The ladder is evaluated strictly in ascending order and the first rung that
    fails decides the response."

    Design: Difficulty/priority_pair_validation_conflict/date_in_future_temporal_beats_remittance_total_mismatch_constraint
    """
    env = setup_basic_403b()

    response = api.create_remittance_batch(
        create_remittance_batch_payload(
            env["plan_id"], [make_line_item(env["account_id"], 100_000)],
            pay_period_start="2026-09-01", pay_period_end="2026-09-16",
            withholding_date="2026-09-15", total_elective_deferral_cents=999_999,
        ),
        make_sponsor_headers(env["employer_id"]),
    )

    validate_error(response, ApiErrorId.ERR_DATE_IN_FUTURE.value)
    rows, _meta = validate_paginated(
        api.list_remittance_batches(make_officer_headers(), {"plan_id": env["plan_id"]})
    )
    assert rows == []


def test_total_mismatch_surfaces_once_the_dates_are_in_the_past(api):
    """PRD §3.7: "First, the declared `total_elective_deferral_cents` must equal the sum of
    `elective_deferral_cents` over the lines exactly, failing which the batch is refused
    with `ERR_REMITTANCE_TOTAL_MISMATCH`; note that `employer_contribution_cents` plays no
    part in that reconciliation."
    PRD §2.6 rung 33: "A batch's declared total reconciles to its lines — otherwise
    `ERR_REMITTANCE_TOTAL_MISMATCH` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/date_in_future_temporal_beats_remittance_total_mismatch_constraint
    """
    env = setup_basic_403b()
    validate_error(
        api.create_remittance_batch(
            create_remittance_batch_payload(
                env["plan_id"], [make_line_item(env["account_id"], 100_000)],
                pay_period_start="2026-09-01", pay_period_end="2026-09-16",
                withholding_date="2026-09-15", total_elective_deferral_cents=999_999,
            ),
            make_sponsor_headers(env["employer_id"]),
        ),
        ApiErrorId.ERR_DATE_IN_FUTURE.value,
    )

    response = api.create_remittance_batch(
        create_remittance_batch_payload(
            env["plan_id"], [make_line_item(env["account_id"], 100_000)],
            pay_period_start="2026-07-01", pay_period_end="2026-07-16",
            withholding_date="2026-07-15", total_elective_deferral_cents=999_999,
        ),
        make_sponsor_headers(env["employer_id"]),
    )

    validate_error(response, ApiErrorId.ERR_REMITTANCE_TOTAL_MISMATCH.value)
    rows, _meta = validate_paginated(
        api.list_remittance_batches(make_officer_headers(), {"plan_id": env["plan_id"]})
    )
    assert rows == []


def test_request_without_identity_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request to the API must carry two headers: `X-User-ID`, identifying
    the acting principal, and `X-User-Role`, naming the role that principal is acting in.
    If either header is absent, or if `X-User-Role` does not spell one of the five declared
    roles exactly, the request is refused with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.1: "These two checks precede every other check the server performs, in that
    order."

    Design: Corner/validations/create_plan_missing_auth_headers_returns_unauthenticated
    """
    set_clock()
    employer = register_employer()
    payload = create_plan_payload(employer["id"])
    payload.pop("plan_type")

    response = api.create_plan(payload, NO_AUTH_HEADERS)

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_vendor_cannot_report_on_another_vendors_contract(api):
    """PRD §2.1: "When `X-User-Role` is `VendorRepresentative`, `X-User-ID` is the `id` of
    the acting `Vendor`; ownership checks on any resource that references a `Vendor`
    compare the resource's `vendor_id` to `X-User-ID`, and a movement request may be
    answered only when the destination contract's `vendor_id` equals `X-User-ID`."
    PRD §3.4: "A `VendorRepresentative` refreshes the picture by posting a balance report
    against one of its own contracts."

    Design: Corner/validations/vendor_representative_cannot_report_on_another_vendors_contract
    """
    env = setup_plan_env(plan_type="PLAN_403B", num_vendors=2)
    participant = register_participant(env["employer_id"])
    account = open_contract(
        participant["id"], env["plan_id"], env["vendor_ids"][0], env["employer_id"],
        contract_number="NLA-0001", accumulated_benefit_cents=1_000_000,
    )
    version = contract_version(account["id"], env["vendor_ids"][0])

    response = api.report_balance(
        account["id"],
        {
            "expected_vendor_account_version": version, "as_of_date": "2026-07-31",
            "accumulated_benefit_cents": 9_999_999, "outstanding_loan_balance_cents": 0,
            "highest_outstanding_loan_12mo_cents": 0,
        },
        make_vendor_headers(env["vendor_ids"][1]),
    )

    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    unchanged = validate_success(api.get_vendor_account(account["id"], make_officer_headers()))
    assert unchanged["accumulated_benefit_cents"] == 1_000_000
    assert unchanged["last_balance_report_date"] is None


def test_top_hat_plan_cannot_open_a_contract_for_a_non_select_employee(api):
    """PRD §3.4: "On a plan whose regime is `TOP_HAT_457`, a contract may only be opened
    for a participant whose `is_select_management_or_hce` is true; otherwise the attempt is
    refused with `ERR_NOT_TOP_HAT_ELIGIBLE`."
    PRD §2.8: "Otherwise the plan is a `PLAN_457B`, and the regime is
    `GOVERNMENTAL_457_ALL_EMPLOYEES` when the sponsor is governmental and `TOP_HAT_457`
    when it is not."

    Design: Corner/validations/top_hat_plan_cannot_open_a_contract_for_a_non_select_employee
    """
    set_clock()
    employer = register_nonqualified_employer()
    vendor = register_vendor()
    plan = create_active_plan(
        employer["id"], plan_name="Lakeside 457(b)", plan_type="PLAN_457B",
        reported_participant_count=40,
    )
    select_employee = register_participant(
        employer["id"], full_name="Hedy Marsh", date_of_birth="1971-01-01",
        hire_date="2005-01-01", includible_compensation_cents=20_000_000,
        years_of_service=21, is_select_management_or_hce=True,
    )
    rank_and_file = register_participant(
        employer["id"], full_name="Ivan Cole", date_of_birth="1985-04-04",
        hire_date="2019-01-01", includible_compensation_cents=4_000_000, years_of_service=7,
    )

    refused = api.create_vendor_account(
        {
            "participant_id": rank_and_file["id"], "plan_id": plan["id"],
            "vendor_id": vendor["id"], "contract_number": "NLA-R001",
            "accumulated_benefit_cents": 0,
        },
        make_sponsor_headers(employer["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_NOT_TOP_HAT_ELIGIBLE.value)

    allowed = validate_success(
        api.create_vendor_account(
            {
                "participant_id": select_employee["id"], "plan_id": plan["id"],
                "vendor_id": vendor["id"], "contract_number": "NLA-S001",
                "accumulated_benefit_cents": 0,
            },
            make_sponsor_headers(employer["id"]),
        ),
        expected_status=201,
    )
    assert allowed["status"] == "OPEN"

    rows, _meta = validate_paginated(
        api.list_vendor_accounts(make_officer_headers(), {"plan_id": plan["id"]})
    )
    assert len(rows) == 1


def test_vendor_representative_cannot_create_a_plan(api):
    """PRD §2.1: "If both headers are well formed but the named role is not among the roles
    the addressed endpoint admits, the refusal is `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: "| POST | `/plan-admin/plans` | Create a plan in DRAFT. nondiscrimination_regime, is_small_plan and is_governmental_457 are computed from the sponsor and plan_type | `PlanSponsorAdmin` |"

    Design: Corner/rbac/vendor_representative_cannot_create_a_plan
    """
    set_clock()
    employer = register_employer()
    vendor = register_vendor()

    response = api.create_plan(
        create_plan_payload(employer["id"], plan_name="Vendor Plan"),
        make_vendor_headers(vendor["id"]),
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)
    rows, _meta = validate_paginated(api.list_plans(make_officer_headers()))
    assert rows == []


def test_system_operator_registers_vendors_but_cannot_create_a_plan(api):
    """PRD §2.1: "A `SystemOperator` is the platform operator that seeds sponsors and
    providers and controls the logical clock."
    PRD §4: "| POST | `/plan-admin/vendors` | Register an annuity or custodial provider | `SystemOperator` |"
    PRD §2.1: "If both headers are well formed but the named role is not among the roles
    the addressed endpoint admits, the refusal is `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/system_operator_cannot_create_a_plan_but_can_register_a_vendor
    """
    set_clock()
    employer = register_employer()

    vendor = validate_success(
        api.create_vendor(
            {
                "legal_name": "Northline Annuity", "vendor_code": "NLA",
                "contact_email": "ops@northline.example",
            },
            make_operator_headers(),
        ),
        expected_status=201,
    )
    assert vendor["vendor_code"] == "NLA"

    response = api.create_plan(
        create_plan_payload(employer["id"], plan_name="Operator Plan"), make_operator_headers()
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)
    rows, _meta = validate_paginated(api.list_plans(make_officer_headers()))
    assert rows == []


def test_stale_vendor_account_version_on_balance_report_is_rejected(api):
    """PRD §2.5: "A `POST /plan-admin/vendor-accounts/{id}/balance-report` request must
    likewise carry `expected_vendor_account_version` as a required, non-optional field,
    holding the `version` of the target `VendorAccount` as the reporting provider last read
    it. A mismatch with the contract's current `version` is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.4: "Accepting the report recomputes `vested_balance_cents`, recomputes every
    participant aggregate listed in §2.10 along with `loan_eligibility_flag`, stores the
    `as_of_date` as `last_balance_report_date`, and increments the contract's `version` by
    one."

    Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_stale_vendor_account_version_on_balance_report
    """
    env = setup_plan_env(plan_type="PLAN_403B", num_vendors=1)
    participant = register_participant(env["employer_id"])
    account = open_contract(
        participant["id"], env["plan_id"], env["vendor_id"], env["employer_id"],
        contract_number="NLA-0001", accumulated_benefit_cents=1_000_000,
    )
    stale_version = contract_version(account["id"], env["vendor_id"])
    report_balance(
        account["id"], env["vendor_id"], as_of_date="2026-07-31",
        accumulated_benefit_cents=2_000_000, outstanding_loan_balance_cents=0,
        highest_outstanding_loan_12mo_cents=0, ytd_elective_deferrals_cents=300_000,
    )

    stale = api.report_balance(
        account["id"],
        {
            "expected_vendor_account_version": stale_version, "as_of_date": "2026-07-31",
            "accumulated_benefit_cents": 7_777_777, "outstanding_loan_balance_cents": 0,
            "highest_outstanding_loan_12mo_cents": 0, "ytd_elective_deferrals_cents": 999_999,
        },
        make_vendor_headers(env["vendor_id"]),
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value)
    held = validate_success(api.get_vendor_account(account["id"], make_officer_headers()))
    assert held["accumulated_benefit_cents"] == 2_000_000
    assert held["ytd_elective_deferrals_cents"] == 300_000

    refreshed = report_balance(
        account["id"], env["vendor_id"], as_of_date="2026-07-31",
        accumulated_benefit_cents=7_777_777, outstanding_loan_balance_cents=0,
        highest_outstanding_loan_12mo_cents=0, ytd_elective_deferrals_cents=999_999,
    )
    assert refreshed["accumulated_benefit_cents"] == 7_777_777
    assert refreshed["ytd_elective_deferrals_cents"] == 999_999
    assert refreshed["vested_balance_cents"] == 7_777_777
    assert validate_success(
        api.get_participant(participant["id"], make_officer_headers())
    )["total_accumulated_benefit_cents"] == 7_777_777


def test_participant_aggregates_reconcile_after_each_balance_report(api):
    """PRD §2.10: "The participant aggregates are all sums taken over the participant's
    contracts whose `status` is `OPEN`; a contract whose `status` is `CLOSED` leaves every
    aggregation set the moment it closes. `total_accumulated_benefit_cents` sums
    `accumulated_benefit_cents`. `total_vested_balance_cents` sums `vested_balance_cents`.
    `total_outstanding_loan_balance_cents` sums `outstanding_loan_balance_cents`.
    `highest_outstanding_loan_12mo_cents` sums `highest_outstanding_loan_12mo_cents`."
    PRD §3.4: "Accepting the report recomputes `vested_balance_cents`, recomputes every
    participant aggregate listed in §2.10 along with `loan_eligibility_flag`, stores the
    `as_of_date` as `last_balance_report_date`, and increments the contract's `version` by
    one."

    Design: Corner/cross_cutting_complexity_layers/derived_participant_aggregates_reconcile_after_each_balance_report
    """
    env = setup_plan_env(plan_type="PLAN_403B", num_vendors=2)
    participant = register_participant(env["employer_id"])
    account_one = open_contract(
        participant["id"], env["plan_id"], env["vendor_ids"][0], env["employer_id"],
        contract_number="NLA-0001", accumulated_benefit_cents=1_000_000,
    )
    account_two = open_contract(
        participant["id"], env["plan_id"], env["vendor_ids"][1], env["employer_id"],
        contract_number="CDR-0001", accumulated_benefit_cents=1_000_000,
        vested_percentage_bps=5000,
    )
    before = validate_success(api.get_participant(participant["id"], make_officer_headers()))
    assert before["total_accumulated_benefit_cents"] == 2_000_000
    assert before["total_vested_balance_cents"] == 1_500_000

    report_balance(
        account_one["id"], env["vendor_ids"][0], as_of_date="2026-07-31",
        accumulated_benefit_cents=5_000_000, outstanding_loan_balance_cents=200_000,
        highest_outstanding_loan_12mo_cents=400_000,
    )
    report_balance(
        account_two["id"], env["vendor_ids"][1], as_of_date="2026-07-31",
        accumulated_benefit_cents=3_000_000, outstanding_loan_balance_cents=300_000,
        highest_outstanding_loan_12mo_cents=500_000,
    )

    assert validate_success(
        api.get_vendor_account(account_one["id"], make_officer_headers())
    )["vested_balance_cents"] == 5_000_000
    assert validate_success(
        api.get_vendor_account(account_two["id"], make_officer_headers())
    )["vested_balance_cents"] == 1_500_000
    participant_row = validate_success(
        api.get_participant(participant["id"], make_officer_headers())
    )
    assert participant_row["total_accumulated_benefit_cents"] == 8_000_000
    assert participant_row["total_vested_balance_cents"] == 6_500_000
    assert participant_row["total_outstanding_loan_balance_cents"] == 500_000
    assert participant_row["highest_outstanding_loan_12mo_cents"] == 900_000
    assert participant_row["loan_eligibility_flag"] == "AVAILABLE"


def test_logical_clock_starts_at_the_declared_instant(api):
    """PRD §2.7: "At startup, before any operator sets it, the logical clock reads exactly
    `2026-08-01T00:00:00Z`, and it must never fall back to real wall-clock time. An
    operator may move the clock by supplying a `to_iso8601` instant; the response reports
    `current_utc` and `previous_utc`."

    Design: Corner/endpoints/logical_clock_defaults_to_2026_08_01_before_any_set_call
    """
    register_employer()

    first = validate_success(
        api.set_clock({"to_iso8601": "2026-09-30T00:00:00Z"}, make_operator_headers())
    )
    second = validate_success(
        api.set_clock({"to_iso8601": "2026-08-01T00:00:00Z"}, make_operator_headers())
    )

    assert _as_instant(first["previous_utc"]) == _as_instant("2026-08-01T00:00:00Z"), (
        "the startup default, not real wall-clock time"
    )
    assert _as_instant(first["current_utc"]) == _as_instant("2026-09-30T00:00:00Z")
    assert _as_instant(second["previous_utc"]) == _as_instant("2026-09-30T00:00:00Z")
    assert _as_instant(second["current_utc"]) == _as_instant("2026-08-01T00:00:00Z")
