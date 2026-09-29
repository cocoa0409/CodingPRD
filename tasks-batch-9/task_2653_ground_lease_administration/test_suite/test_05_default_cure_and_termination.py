"""Default notices: deadlines computed once at service, the inclusive lessee
window, the sweep that lapses it strictly, the mortgagee fork and the full
termination fan-out with the replacement lease it makes possible."""

from test_helpers import (
    ERR_CURE_WINDOW_CLOSED,
    ERR_INVALID_STATE,
    assert_fields,
    factories as f,
    fixtures as fx,
    make_asset_manager_headers,
    make_ground_tenant_headers,
    make_lessor_admin_headers,
    make_mortgagee_agent_headers,
    validate_error,
    validate_success,
)


def _encumbered_lease_in_default(api):
    """1000000 of arrears, two RECORDED mortgages with 30- and 15-day extensions,
    and a monetary notice served by acct-1."""
    env = fx.standard_lease(api, "PIER-48")
    fx.add_arrears(api, env["lease_id"], 1000000)
    senior = fx.record_senior_mortgage(api, env["lease_id"])
    mezz = fx.record_mezz_mortgage(api, env["lease_id"])
    notice = fx.served_default_notice(
        api, env["lease_id"], "MONETARY_RENT_ARREARS", 1000000, user_id="acct-1"
    )
    return env, senior, mezz, notice


def test_the_lender_window_is_derived_from_the_widest_extension_in_the_register(api):
    """PRD §3.7: "otherwise `mortgagee_cure_deadline` is `lessee_cure_deadline` advanced by the **largest** `cure_extension_days` among those noticed mortgages — the widest extension in the register governs, not the sum and not the narrowest."

    Design: Difficulty/non_linear_state_machine/default_notice_forks_into_mortgagee_branch_after_lessee_window_lapses
    """
    env, senior, mezz, notice = _encumbered_lease_in_default(api)

    assert_fields(
        notice,
        status="SERVED",
        served_at="2026-08-01T00:00:00Z",
        served_by_user_id="acct-1",
        lessee_cure_deadline="2026-08-11T00:00:00Z",
        mortgagee_cure_deadline="2026-09-10T00:00:00Z",
        mortgagee_notified_at="2026-08-01T00:00:00Z",
    )
    for mortgage_id in (senior["id"], mezz["id"]):
        row = validate_success(
            api.get_mortgage(mortgage_id, make_lessor_admin_headers())
        )
        assert_fields(row, status="NOTICE_SERVED",
                      mortgagee_notified_at="2026-08-01T00:00:00Z")
    assert fx.read_lease(api, env["lease_id"])["lease_status"] == "IN_DEFAULT"


def test_termination_is_refused_while_the_lender_window_is_still_open(api):
    """PRD §3.7: "From `LESSEE_CURE_LAPSED` the notice is terminable only where the lease is **unencumbered** — that is, where no mortgage on the lease sits in `RECORDED`, `NOTICE_SERVED` or `CURING` — since an encumbered lease must give its lender the mortgagee window first."

    Design: Difficulty/non_linear_state_machine/default_notice_forks_into_mortgagee_branch_after_lessee_window_lapses
    """
    env, _senior, _mezz, notice = _encumbered_lease_in_default(api)

    fx.set_clock(api, "2026-08-12T00:00:00Z")
    report = fx.run_sweep(api)
    assert report["cure_windows_lapsed"] == 1
    lapsed = validate_success(
        api.get_default_notice(notice["id"], make_lessor_admin_headers())
    )
    assert lapsed["status"] == "LESSEE_CURE_LAPSED"

    validate_error(
        api.terminate_lease(notice["id"], make_asset_manager_headers("am-1")),
        ERR_INVALID_STATE,
        expected_status=409,
    )
    unchanged = validate_success(
        api.get_default_notice(notice["id"], make_lessor_admin_headers())
    )
    assert unchanged["status"] == "LESSEE_CURE_LAPSED"
    assert fx.read_lease(api, env["lease_id"])["lease_status"] == "IN_DEFAULT"


def test_the_mortgagee_cure_returns_the_acting_mortgage_and_leaves_the_others(api):
    """PRD §3.7: "Completion moves the notice `MORTGAGEE_CURING → MORTGAGEE_CURED` with `cured_by` recorded as `MORTGAGEE`, returns the acting mortgage `CURING → RECORDED`, subtracts the payment from `arrears_balance_cents` floored at 0, returns the lease's tenancy axis `IN_DEFAULT → ACTIVE`, and increments the lease `version` by one."

    Design: Difficulty/non_linear_state_machine/default_notice_forks_into_mortgagee_branch_after_lessee_window_lapses
    """
    env, senior, mezz, notice = _encumbered_lease_in_default(api)
    fx.set_clock(api, "2026-08-12T00:00:00Z")
    fx.run_sweep(api)
    agent = make_mortgagee_agent_headers(senior["id"])

    elected = validate_success(
        api.mortgagee_cure(
            notice["id"], f.mortgagee_cure_payload("ELECT", senior["id"]), agent
        )
    )
    assert elected["status"] == "MORTGAGEE_CURING"
    assert validate_success(
        api.get_mortgage(senior["id"], make_lessor_admin_headers())
    )["status"] == "CURING"
    assert validate_success(
        api.get_mortgage(mezz["id"], make_lessor_admin_headers())
    )["status"] == "NOTICE_SERVED"

    completed = validate_success(
        api.mortgagee_cure(
            notice["id"],
            f.mortgagee_cure_payload("COMPLETE", senior["id"], 1000000),
            agent,
        )
    )
    assert_fields(completed, status="MORTGAGEE_CURED", cured_by="MORTGAGEE")
    assert_fields(fx.read_lease(api, env["lease_id"]),
                  lease_status="ACTIVE", arrears_balance_cents=0)
    # §3.7 returns only "the acting mortgage `CURING → RECORDED`", and §3.2
    # contrasts that with the tenant's cure, which returns *every* NOTICE_SERVED
    # or CURING mortgage: the untouched mezzanine therefore stays NOTICE_SERVED.
    assert validate_success(
        api.get_mortgage(senior["id"], make_lessor_admin_headers())
    )["status"] == "RECORDED"
    assert validate_success(
        api.get_mortgage(mezz["id"], make_lessor_admin_headers())
    )["status"] == "NOTICE_SERVED"


def _two_unencumbered_notices(api):
    """Two identical leases held by one tenant, each with 1000000 of arrears and a
    monetary notice served at the default clock, neither carrying a mortgage."""
    lessee = fx.create_lessee(api)
    notices = {}
    leases = {}
    for label, premises_code in (("a", "PIER-57-A"), ("b", "PIER-57-B")):
        lease = fx.create_lease(api, lessee["id"], premises_code)
        fx.add_arrears(api, lease["id"], 1000000)
        leases[label] = lease
        notices[label] = fx.served_default_notice(
            api, lease["id"], "MONETARY_RENT_ARREARS", 1000000, user_id="acct-1"
        )
        assert_fields(notices[label],
                      lessee_cure_deadline="2026-08-11T00:00:00Z")
        assert notices[label]["mortgagee_cure_deadline"] is None
    return lessee, leases, notices


def test_the_sweep_leaves_the_window_open_at_exactly_the_deadline_instant(api):
    """PRD §3.7: "If the tenant does nothing, the sweep lapses its window: a notice in `SERVED` whose `lessee_cure_deadline` the logical clock has passed **strictly** moves `SERVED → LESSEE_CURE_LAPSED`, and at exactly the deadline instant it stays in `SERVED`."

    Design: Difficulty/boundary_precision_check/lessee_cure_succeeds_at_the_deadline_instant_and_fails_one_second_later
    """
    _lessee, _leases, notices = _two_unencumbered_notices(api)

    fx.set_clock(api, "2026-08-11T00:00:00Z")
    report = fx.run_sweep(api)
    assert report["cure_windows_lapsed"] == 0
    for label in ("a", "b"):
        row = validate_success(
            api.get_default_notice(notices[label]["id"], make_lessor_admin_headers())
        )
        assert row["status"] == "SERVED"


def test_a_cure_at_the_deadline_instant_succeeds(api):
    """PRD §3.7: "The window is inclusive: a cure at exactly the `lessee_cure_deadline` instant succeeds, and only a cure attempted strictly after it is refused with `ERR_CURE_WINDOW_CLOSED`."

    Design: Difficulty/boundary_precision_check/lessee_cure_succeeds_at_the_deadline_instant_and_fails_one_second_later
    """
    lessee, leases, notices = _two_unencumbered_notices(api)
    fx.set_clock(api, "2026-08-11T00:00:00Z")
    fx.run_sweep(api)

    cured = validate_success(
        api.lessee_cure(
            notices["a"]["id"],
            f.lessee_cure_payload("2026-08-11T00:00:00Z", 1000000),
            make_ground_tenant_headers(lessee["id"]),
        )
    )
    assert_fields(cured, status="LESSEE_CURED", cured_by="LESSEE")
    assert_fields(fx.read_lease(api, leases["a"]["id"]),
                  lease_status="ACTIVE", arrears_balance_cents=0)


def test_one_second_past_the_deadline_the_cure_is_refused_then_the_sweep_lapses_it(api):
    """PRD §2.5: "Cure deadlines and the new-lease election deadline are **inclusive**: an action attempted at exactly the deadline instant still succeeds, and only an action attempted strictly after the deadline is refused."

    Design: Difficulty/boundary_precision_check/lessee_cure_succeeds_at_the_deadline_instant_and_fails_one_second_later
    """
    lessee, leases, notices = _two_unencumbered_notices(api)
    fx.set_clock(api, "2026-08-11T00:00:01Z")

    validate_error(
        api.lessee_cure(
            notices["b"]["id"],
            f.lessee_cure_payload("2026-08-11T00:00:01Z", 1000000),
            make_ground_tenant_headers(lessee["id"]),
        ),
        ERR_CURE_WINDOW_CLOSED,
        expected_status=409,
    )
    refused = validate_success(
        api.get_default_notice(notices["b"]["id"], make_lessor_admin_headers())
    )
    assert refused["status"] == "SERVED"
    assert fx.read_lease(api, leases["b"]["id"])["arrears_balance_cents"] == 1000000

    report = fx.run_sweep(api)
    # §3.9 phase two lapses every notice in SERVED whose deadline the clock has
    # passed strictly, and both fixture notices share the 2026-08-11 deadline.
    assert report["cure_windows_lapsed"] == 2
    lapsed = validate_success(
        api.get_default_notice(notices["b"]["id"], make_lessor_admin_headers())
    )
    assert lapsed["status"] == "LESSEE_CURE_LAPSED"
    assert fx.read_lease(api, leases["b"]["id"])["lease_status"] == "IN_DEFAULT"


DESIGNEE = {
    "legal_name": "Seawall Fund II LLC",
    "notice_email": "asset@seawall.example",
    "credit_rating_code": "A",
}


def _lease_with_every_dependent_row_in_default(api):
    """One lease carrying insurance, a RECORDED mortgage, an ACTIVE sublease, a
    SUBMITTED statement and an ISSUED estoppel certificate, then served an
    UNPERMITTED_USE notice so no arrears are involved."""
    env = fx.standard_lease(api, "PIER-49")
    designee = fx.create_lessee(api, **DESIGNEE)
    fx.file_insurance(api, env["lease_id"])
    mortgage = fx.record_senior_mortgage(api, env["lease_id"])
    sublease = fx.active_sublease(
        api, env["lease_id"], env["lessee_id"], "UNIT-1", 4000001
    )
    statement = fx.file_statement(
        api, env["lease_id"], env["lessee_id"],
        "2025-01-01T00:00:00Z", "2026-01-01T00:00:00Z", 90000000,
    )
    certificate = fx.issue_estoppel(api, env["lease_id"], mortgage["id"])
    notice = fx.served_default_notice(
        api, env["lease_id"], "UNPERMITTED_USE", user_id="acct-1"
    )
    return {
        "env": env, "designee": designee, "mortgage": mortgage,
        "sublease": sublease, "statement": statement,
        "certificate": certificate, "notice": notice,
    }


def _lapse_both_windows(api, notice_id):
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    first = fx.run_sweep(api)
    fx.set_clock(api, "2026-10-01T00:00:00Z")
    second = fx.run_sweep(api)
    return first, second


def test_a_thirty_day_ground_runs_both_windows_before_termination_opens(api):
    """PRD §3.7: "The tenant's window length depends on the ground: 10 whole days for either of the two monetary grounds, 15 whole days for `INSURANCE_LAPSE`, and 30 whole days for `UNPERMITTED_USE` or `UNAUTHORIZED_TRANSFER`."

    Design: Difficulty/transitive_cascade/termination_fans_out_to_subleases_statements_certificates_then_mints_new_lease
    """
    world = _lease_with_every_dependent_row_in_default(api)
    admin = make_lessor_admin_headers()

    assert_fields(
        world["notice"],
        lessee_cure_deadline="2026-08-31T00:00:00Z",
        mortgagee_cure_deadline="2026-09-30T00:00:00Z",
    )
    assert_fields(fx.read_lease(api, world["env"]["lease_id"]),
                  lease_status="IN_DEFAULT", insurance_status="ACTIVE",
                  percentage_rent_sublease_base_cents=2000001)

    fx.set_clock(api, "2026-09-01T00:00:00Z")
    fx.run_sweep(api)
    after_first = validate_success(
        api.get_default_notice(world["notice"]["id"], admin)
    )
    assert after_first["status"] == "LESSEE_CURE_LAPSED"
    # §3.9 phase three: the lease's next_revaluation_date (2025-01-01, being
    # commencement plus the 5-year interval) is at or before the clock, so the
    # same sweep flags the independent rent axis BASE_ONLY -> REVALUATION_DUE.
    assert fx.read_lease(api, world["env"]["lease_id"])["rent_status"] == "REVALUATION_DUE"

    fx.set_clock(api, "2026-10-01T00:00:00Z")
    fx.run_sweep(api)
    after_second = validate_success(
        api.get_default_notice(world["notice"]["id"], admin)
    )
    assert after_second["status"] == "MORTGAGEE_CURE_LAPSED"
    assert validate_success(
        api.get_mortgage(world["mortgage"]["id"], admin)
    )["status"] == "NOTICE_SERVED"


def test_termination_fans_out_to_every_dependent_row(api):
    """PRD §3.7: "Every transfer request on the lease in `ACTIVE` becomes `TERMINATED_BY_REVERSION`, and because the active sublease set is now empty the lease's `percentage_rent_sublease_base_cents` is recomputed to 0."

    Design: Difficulty/transitive_cascade/termination_fans_out_to_subleases_statements_certificates_then_mints_new_lease
    """
    world = _lease_with_every_dependent_row_in_default(api)
    admin = make_lessor_admin_headers()
    _lapse_both_windows(api, world["notice"]["id"])

    terminated = validate_success(
        api.terminate_lease(world["notice"]["id"],
                            make_asset_manager_headers("am-1"))
    )
    assert_fields(terminated, status="TERMINATION_EFFECTED",
                  terminated_by_user_id="am-1")
    assert_fields(fx.read_lease(api, world["env"]["lease_id"]),
                  lease_status="TERMINATED", rent_status="FROZEN",
                  percentage_rent_sublease_base_cents=0)

    assert validate_success(
        api.get_transfer(world["sublease"]["id"], admin)
    )["status"] == "TERMINATED_BY_REVERSION"
    assert validate_success(
        api.get_statement(world["statement"]["id"], admin)
    )["status"] == "VOID"
    assert validate_success(
        api.get_estoppel(world["certificate"]["id"], admin)
    )["status"] == "REVOKED"
    assert_fields(
        validate_success(api.get_mortgage(world["mortgage"]["id"], admin)),
        status="NEW_LEASE_ELIGIBLE",
        new_lease_election_deadline="2026-10-31T00:00:00Z",
    )
    summary = validate_success(
        api.get_rent_summary(world["env"]["lease_id"], admin)
    )
    assert summary["active_sublease_count"] == 0


def test_the_new_lease_election_mints_a_lease_with_both_lineage_pointers(api):
    """PRD §3.7: "The election mints a brand-new lease: `predecessor_lease_id` points at the terminated lease, `origin_mortgage_id` points at the electing mortgage, `lessee_id` takes `new_lessee_id`, `premises_code` is carried across, `current_annual_base_rent_cents` is carried across, `commencement_date` is the logical clock's current instant while `expiration_date` is carried across unchanged, and the collar, percentage-rent, envelope and reversion terms are all copied."

    Design: Difficulty/transitive_cascade/termination_fans_out_to_subleases_statements_certificates_then_mints_new_lease
    """
    world = _lease_with_every_dependent_row_in_default(api)
    admin = make_lessor_admin_headers()
    _lapse_both_windows(api, world["notice"]["id"])
    validate_success(
        api.terminate_lease(world["notice"]["id"],
                            make_asset_manager_headers("am-1"))
    )

    minted = validate_success(
        api.elect_new_lease(
            world["mortgage"]["id"],
            f.new_lease_election_payload(world["designee"]["id"]),
            make_mortgagee_agent_headers(world["mortgage"]["id"]),
        ),
        expected_status=201,
    )
    assert_fields(
        minted,
        predecessor_lease_id=world["env"]["lease_id"],
        origin_mortgage_id=world["mortgage"]["id"],
        lessee_id=world["designee"]["id"],
        lease_status="ACTIVE",
        rent_status="BASE_ONLY",
        current_annual_base_rent_cents=10000000,
        arrears_balance_cents=0,
        deposit_held_cents=0,
        insurance_status="LAPSED",
    )
    assert validate_success(
        api.get_mortgage(world["mortgage"]["id"], admin)
    )["status"] == "NEW_LEASE_ELECTED"
    assert_fields(fx.read_lease(api, world["env"]["lease_id"]),
                  lease_status="TERMINATED", rent_status="FROZEN")
