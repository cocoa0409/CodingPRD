"""Information sharing agreements: buffered windows, suspension and staleness."""

from test_helpers import (
    ApiErrorId,
    create_agreement,
    create_agreement_payload,
    make_officer_headers,
    make_sponsor_headers,
    make_vendor_headers,
    move_agreement,
    open_contract,
    post_data_feed,
    register_participant,
    report_balance,
    set_clock,
    setup_403b_with_agreement,
    setup_active_agreement,
    setup_plan_env,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_agreement_with_zero_day_gap_is_rejected(api):
    """PRD §3.2: "Concretely, for a given `plan_id` and `vendor_id`, the new agreement
    conflicts with any existing agreement whose `status` is anything other than
    `TERMINATED` when the new window's `effective_from` falls on or before one day
    after that agreement's `effective_through`, and simultaneously that agreement's
    `effective_from` falls on or before one day after the new window's
    `effective_through`. Back-to-back agreements with a zero-day gap therefore collide
    and are refused with `ERR_ISA_INTERVAL_OVERLAP`; a genuine gap of at least one
    clear calendar day between the old `effective_through` and the new
    `effective_from` is admissible."

    Design: Difficulty/resource_temporal_overlap/isa_interval_minimum_gap_buffer_enforced
    """
    env = setup_plan_env(plan_type="PLAN_457B", num_vendors=1, plan_overrides={"plan_name": "Riverbend 457(b)"})
    first = create_agreement(
        env["plan_id"], env["vendor_id"], env["employer_id"],
        effective_from="2026-01-01", effective_through="2026-06-30",
    )
    assert first["status"] == "PENDING"
    assert first["effective_through"] == "2026-06-30"

    response = api.create_agreement(
        create_agreement_payload(
            env["plan_id"], env["vendor_id"],
            effective_from="2026-07-01", effective_through="2026-12-31",
        ),
        make_sponsor_headers(env["employer_id"]),
    )

    validate_error(response, ApiErrorId.ERR_ISA_INTERVAL_OVERLAP.value)
    rows, _meta = validate_paginated(
        api.list_agreements(make_officer_headers(), {"plan_id": env["plan_id"]})
    )
    assert len(rows) == 1, "the colliding agreement must not have been stored"


def test_agreement_with_one_clear_day_gap_is_admitted(api):
    """PRD §3.2: "Agreement windows for the same plan-and-vendor pair must keep a clear
    day between them."
    PRD §3.2: "Back-to-back agreements with a zero-day gap therefore collide and are
    refused with `ERR_ISA_INTERVAL_OVERLAP`; a genuine gap of at least one clear
    calendar day between the old `effective_through` and the new `effective_from` is
    admissible."

    Design: Difficulty/resource_temporal_overlap/isa_interval_minimum_gap_buffer_enforced
    """
    env = setup_plan_env(plan_type="PLAN_457B", num_vendors=1, plan_overrides={"plan_name": "Riverbend 457(b)"})
    create_agreement(
        env["plan_id"], env["vendor_id"], env["employer_id"],
        effective_from="2026-01-01", effective_through="2026-06-30",
    )

    second = validate_success(
        api.create_agreement(
            create_agreement_payload(
                env["plan_id"], env["vendor_id"],
                effective_from="2026-07-02", effective_through="2026-12-31",
            ),
            make_sponsor_headers(env["employer_id"]),
        ),
        expected_status=201,
    )

    assert second["status"] == "PENDING"
    rows, _meta = validate_paginated(
        api.list_agreements(make_officer_headers(), {"plan_id": env["plan_id"]})
    )
    assert len(rows) == 2, "one clear calendar day between the windows is admissible"


def test_suspending_agreement_drops_the_verified_year_to_date_figure(api):
    """PRD §3.2: "Suspension moves an active agreement `ACTIVE → SUSPENDED` and has two
    consequences worth stating plainly: every provider contract whose plan-and-vendor
    pair matches the suspended agreement stops counting as verified for the
    verified-basis view of deferral aggregation, and loan capacity refuses to be quoted
    at all for any participant holding such a contract."
    PRD §3.5: "`ytd_gross_cents` is the sum of `ytd_elective_deferrals_cents` over the
    included set; `ytd_verified_cents` is that same sum over the verified set only."

    Design: Difficulty/non_linear_state_machine/isa_suspend_reinstate_cycle_flips_verified_aggregate
    """
    env = setup_403b_with_agreement()
    report_balance(
        env["account_id"], env["vendor_id"],
        as_of_date="2026-07-31", accumulated_benefit_cents=5_000_000,
        outstanding_loan_balance_cents=0, highest_outstanding_loan_12mo_cents=0,
        ytd_elective_deferrals_cents=1_000_000,
    )

    before = validate_success(
        api.get_contribution_limit_summary(
            env["participant_id"], make_officer_headers(), {"plan_id": env["plan_id"]}
        )
    )
    assert before["total_limit_cents"] == 3_250_000
    assert before["ytd_gross_cents"] == 1_000_000
    assert before["ytd_verified_cents"] == 1_000_000
    assert before["room_gross_cents"] == 2_250_000
    assert before["room_verified_cents"] == 2_250_000

    suspended = move_agreement(env["agreement_id"], env["employer_id"], "SUSPENDED")
    assert suspended["status"] == "SUSPENDED"

    after = validate_success(
        api.get_contribution_limit_summary(
            env["participant_id"], make_officer_headers(), {"plan_id": env["plan_id"]}
        )
    )
    assert after["ytd_gross_cents"] == 1_000_000, "the gross basis counts every included contract"
    assert after["ytd_verified_cents"] == 0
    assert after["room_gross_cents"] == 2_250_000
    assert after["room_verified_cents"] == 3_250_000


def test_data_feed_reinstates_suspended_agreement_and_restores_verified_total(api):
    """PRD §3.2: "A `VendorRepresentative` posts a feed by supplying a single
    `data_current_through_date`, which must not be after the current logical clock
    date. The server stores it, recomputes `data_stale` against the 45-day window of
    §2.9, and — when the agreement was `SUSPENDED` — returns it to `ACTIVE` in the same
    operation, incrementing `version` by one."
    PRD §3.5: "The verified set — reported as `verified_vendor_account_ids` — is the
    subset of the included set for which an information sharing agreement exists
    between that contract's plan and that contract's vendor with `status` `ACTIVE`,
    `shares_contribution_data` true and `data_stale` false."

    Design: Difficulty/non_linear_state_machine/isa_suspend_reinstate_cycle_flips_verified_aggregate
    """
    env = setup_403b_with_agreement()
    report_balance(
        env["account_id"], env["vendor_id"],
        as_of_date="2026-07-31", accumulated_benefit_cents=5_000_000,
        outstanding_loan_balance_cents=0, highest_outstanding_loan_12mo_cents=0,
        ytd_elective_deferrals_cents=1_000_000,
    )
    move_agreement(env["agreement_id"], env["employer_id"], "SUSPENDED")

    reinstated = validate_success(
        api.post_data_feed(
            env["agreement_id"],
            {"data_current_through_date": "2026-07-31"},
            make_vendor_headers(env["vendor_id"]),
        )
    )

    assert reinstated["status"] == "ACTIVE", "a feed returns a suspended agreement to ACTIVE"
    assert reinstated["data_stale"] is False

    summary = validate_success(
        api.get_contribution_limit_summary(
            env["participant_id"], make_officer_headers(), {"plan_id": env["plan_id"]}
        )
    )
    assert summary["ytd_verified_cents"] == 1_000_000
    assert summary["room_verified_cents"] == 2_250_000
    assert summary["ytd_gross_cents"] == 1_000_000


def test_agreement_cannot_move_from_pending_to_suspended(api):
    """PRD §3.2: "The agreement lifecycle begins with the sponsor admin moving it
    `PENDING → ACTIVE`, which requires the agreement to be `PENDING` and the governing
    plan to be `ACTIVE` or `FROZEN`, and bumps the agreement's `version` by one.
    Suspension moves an active agreement `ACTIVE → SUSPENDED` and has two consequences
    worth stating plainly: every provider contract whose plan-and-vendor pair matches
    the suspended agreement stops counting as verified for the verified-basis view of
    deferral aggregation, and loan capacity refuses to be quoted at all for any
    participant holding such a contract."
    PRD §2.9: "A brand-new agreement is therefore stale from the moment it is created
    and stays stale until a feed arrives."

    Design: Corner/state_machines/isa_pending_to_suspended_is_not_a_declared_transition
    """
    env = setup_plan_env(plan_type="PLAN_403B", num_vendors=1)
    agreement = create_agreement(env["plan_id"], env["vendor_id"], env["employer_id"])

    response = api.set_agreement_status(
        agreement["id"], {"to_status": "SUSPENDED"}, make_sponsor_headers(env["employer_id"])
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
    unchanged = validate_success(api.get_agreement(agreement["id"], make_officer_headers()))
    assert unchanged["status"] == "PENDING"
    assert unchanged["data_stale"] is True


def test_agreement_staleness_boundary_at_forty_five_days(api):
    """PRD §2.9: "The derived flag `data_stale` is true exactly when
    `data_current_through_date` is null, or when the number of days from
    `data_current_through_date` to the current logical clock date is more than 45."
    PRD §2.9: "A feed that leaves the agreement covered through a date exactly 45 days
    before the clock is still current; one more day and it goes stale."

    Design: Corner/cross_cutting_complexity_layers/information_sharing_agreement_staleness_threshold_at_exactly_forty_five_days
    """
    env = setup_plan_env(plan_type="PLAN_403B", num_vendors=1)
    agreement = setup_active_agreement(
        env["plan_id"], env["vendor_id"], env["employer_id"], feed_date="2026-06-17"
    )
    participant = register_participant(env["employer_id"])
    account = open_contract(
        participant["id"], env["plan_id"], env["vendor_id"], env["employer_id"],
        accumulated_benefit_cents=5_000_000,
    )
    report_balance(
        account["id"], env["vendor_id"], as_of_date="2026-06-17",
        accumulated_benefit_cents=5_000_000, outstanding_loan_balance_cents=0,
        highest_outstanding_loan_12mo_cents=0, ytd_elective_deferrals_cents=1_000_000,
    )

    at_boundary = validate_success(api.get_agreement(agreement["id"], make_officer_headers()))
    assert at_boundary["data_stale"] is False, "exactly 45 days old is still current"

    summary = validate_success(
        api.get_contribution_limit_summary(
            participant["id"], make_officer_headers(), {"plan_id": env["plan_id"]}
        )
    )
    assert summary["ytd_verified_cents"] == 1_000_000
    assert summary["room_verified_cents"] == 2_250_000

    set_clock("2026-08-02T00:00:00Z")

    gone_stale = validate_success(api.get_agreement(agreement["id"], make_officer_headers()))
    assert gone_stale["data_stale"] is True, "46 days old is stale"
    later = validate_success(
        api.get_contribution_limit_summary(
            participant["id"], make_officer_headers(), {"plan_id": env["plan_id"]}
        )
    )
    assert later["ytd_verified_cents"] == 0
    assert later["room_verified_cents"] == 3_250_000
    assert later["ytd_gross_cents"] == 1_000_000
