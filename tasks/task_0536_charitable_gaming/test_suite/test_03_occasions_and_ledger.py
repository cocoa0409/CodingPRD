"""Occasions: dual-variant net proceeds, prize ledger reserve/release, scheduling overlap."""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS, make_orgofficer_headers,
    create_active_license, schedule_occasion, create_held_occasion,
    create_reported_occasion,
    create_occasion_payload, report_occasion_payload,
)

REGULATOR = TEST_USERS["regulator_headers"]


# ─── Difficulty: provisional vs final net_proceeds on one occasion ───
def test_provisional_net_proceeds_at_hold(api):
    """PRD §3.4: "Holding computes a **provisional** `net_proceeds_cents` from the planned
    projections: `planned_gross_cents` minus `planned_prize_pool_cents` minus
    `planned_expenses_cents`."

    Design: Difficulty/dual_variant_calc/occasion_net_provisional_vs_final
    """
    org, lic = create_active_license()
    occ = create_held_occasion(org["id"], lic["id"], planned_gross_cents=200_000,
                               planned_prize_pool_cents=50_000, planned_expenses_cents=20_000)
    assert occ["net_proceeds_cents"] == 130_000, f"got {occ['net_proceeds_cents']}"


def test_final_net_proceeds_at_report(api):
    """PRD §3.4: "On success the actuals are stored, and `net_proceeds_cents` is recomputed
    as the **final** variant: `gross_receipts_cents` minus `prizes_paid_cents` minus
    `expenses_cents`."

    Design: Difficulty/dual_variant_calc/occasion_net_provisional_vs_final
    """
    org, lic = create_active_license()
    occ = create_held_occasion(org["id"], lic["id"], planned_gross_cents=200_000,
                               planned_prize_pool_cents=50_000, planned_expenses_cents=20_000)
    officer = make_orgofficer_headers(org["id"])
    reported = validate_success(
        api.report_occasion(occ["id"],
                            report_occasion_payload(gross_receipts_cents=180_000,
                                                    prizes_paid_cents=40_000,
                                                    expenses_cents=25_000),
                            officer),
        200,
    )
    assert reported["status"] == "REPORTED"
    assert reported["net_proceeds_cents"] == 115_000, f"got {reported['net_proceeds_cents']}"


# ─── Difficulty: license committed vs settled prize buckets ──────────
def test_committed_bucket_before_report(api):
    """PRD §3.5: "The forward-looking `prize_committed_cents` is the sum of
    `planned_prize_pool_cents` over all occasions of the license whose status is
    `SCHEDULED` or `HELD`."
    PRD §3.5: "The realized `prize_settled_cents` is the sum of `prizes_paid_cents` over all
    occasions whose status is `REPORTED`."

    Design: Difficulty/dual_variant_calc/license_prize_committed_vs_settled
    """
    org, lic = create_active_license()
    officer = make_orgofficer_headers(org["id"])
    create_held_occasion(org["id"], lic["id"], planned_prize_pool_cents=50_000)
    read = validate_success(api.get_license(lic["id"], officer), 200)
    assert read["prize_committed_cents"] == 50_000
    assert read["prize_settled_cents"] == 0


def test_settled_bucket_after_report(api):
    """PRD §3.4: "Reporting also transfers prize consumption on the license:
    `planned_prize_pool_cents` is subtracted from `prize_committed_cents` (retiring the
    forward reservation) and `prizes_paid_cents` is added to `prize_settled_cents`
    (recording the actual payout)."
    PRD §3.5: "The `prize_allowance_remaining_cents` is `annual_prize_limit_cents` minus
    `prize_committed_cents` minus `prize_settled_cents`."

    Design: Difficulty/dual_variant_calc/license_prize_committed_vs_settled
    """
    org, lic = create_active_license()
    officer = make_orgofficer_headers(org["id"])
    create_reported_occasion(
        org["id"], lic["id"],
        occasion_overrides={"planned_gross_cents": 200_000, "planned_prize_pool_cents": 50_000,
                            "planned_expenses_cents": 20_000},
        report_overrides={"gross_receipts_cents": 180_000, "prizes_paid_cents": 40_000,
                          "expenses_cents": 25_000},
    )
    read = validate_success(api.get_license(lic["id"], officer), 200)
    assert read["prize_committed_cents"] == 0
    assert read["prize_settled_cents"] == 40_000
    assert read["prize_allowance_remaining_cents"] == 960_000


# ─── Difficulty: reserve/release conserves the prize allowance pool ──
def test_schedule_reserves_prize_allowance(api):
    """PRD §3.3: "Scheduling an occasion reserves prize allowance: at creation,
    `planned_prize_pool_cents` is added to the license's `prize_committed_cents`."

    Design: Difficulty/compensating_invariant/prize_allowance_reserve_release_conserved
    """
    org, lic = create_active_license()
    officer = make_orgofficer_headers(org["id"])
    schedule_occasion(org["id"], lic["id"], planned_prize_pool_cents=50_000)
    read = validate_success(api.get_license(lic["id"], officer), 200)
    assert read["prize_committed_cents"] == 50_000
    assert read["prize_allowance_remaining_cents"] == 950_000


def test_cancel_releases_reserved_prize_allowance(api):
    """PRD §3.3: "Cancellation releases the reservation by subtracting
    `planned_prize_pool_cents` from the license's `prize_committed_cents`, and it cascades
    to every `EquipmentAllocation` for that occasion still in `ACTIVE` status, driving each
    to `RELEASED`."

    Design: Difficulty/compensating_invariant/prize_allowance_reserve_release_conserved
    """
    org, lic = create_active_license()
    officer = make_orgofficer_headers(org["id"])
    occ = schedule_occasion(org["id"], lic["id"], planned_prize_pool_cents=50_000)
    cancelled = validate_success(api.cancel_occasion(occ["id"], officer), 200)
    assert cancelled["status"] == "CANCELLED"
    read = validate_success(api.get_license(lic["id"], officer), 200)
    assert read["prize_committed_cents"] == 0
    assert read["prize_allowance_remaining_cents"] == 1_000_000


# ─── Difficulty: occasion schedule half-open overlap ─────────────────
def test_overlapping_occasion_rejected(api):
    """PRD §3.3: "A new occasion whose window overlaps that of any non-`CANCELLED` occasion
    on the same license is rejected with `ERR_OCCASION_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/occasion_schedule_halfopen_overlap
    """
    org, lic = create_active_license()
    officer = make_orgofficer_headers(org["id"])
    schedule_occasion(org["id"], lic["id"], scheduled_start="2026-06-01T18:00:00Z",
                      scheduled_end="2026-06-01T22:00:00Z")
    res = api.create_occasion(
        create_occasion_payload(lic["id"], scheduled_start="2026-06-01T20:00:00Z",
                                scheduled_end="2026-06-01T23:00:00Z"),
        officer,
    )
    validate_error(res, "ERR_OCCASION_OVERLAP")


def test_adjacent_occasion_allowed(api):
    """PRD §3.3: "An occasion's scheduled window is treated as a half-open interval that
    includes its start and excludes its end, so two occasions on the same license that
    merely touch end-to-start do not collide."

    Design: Difficulty/resource_temporal_overlap/occasion_schedule_halfopen_overlap
    """
    org, lic = create_active_license()
    officer = make_orgofficer_headers(org["id"])
    schedule_occasion(org["id"], lic["id"], scheduled_start="2026-06-01T18:00:00Z",
                      scheduled_end="2026-06-01T22:00:00Z")
    res = api.create_occasion(
        create_occasion_payload(lic["id"], scheduled_start="2026-06-01T22:00:00Z",
                                scheduled_end="2026-06-01T23:00:00Z"),
        officer,
    )
    adjacent = validate_success(res, 201)
    assert adjacent["status"] == "SCHEDULED"


# ─── Corner: occasion invalid state transitions & time validity ──────
def test_hold_already_held_invalid_state(api):
    """PRD §3.4: "An `OrgOfficer` marks a scheduled occasion as held once it has taken
    place, advancing it from `SCHEDULED` to `HELD`. This is permitted only when the occasion
    is `SCHEDULED` (else `ERR_INVALID_STATE`) and only while the owning license is `ACTIVE`
    (else `ERR_LICENSE_NOT_ACTIVE`)."

    Design: Corner/state_machines/hold_already_held_returns_invalid_state
    """
    org, lic = create_active_license()
    officer = make_orgofficer_headers(org["id"])
    occ = create_held_occasion(org["id"], lic["id"])
    res = api.hold_occasion(occ["id"], officer)
    validate_error(res, "ERR_INVALID_STATE")
    fetched = validate_success(api.get_occasion(occ["id"], officer), 200)
    assert fetched["status"] == "HELD"


def test_cancel_reported_occasion_invalid_state(api):
    """PRD §3.3: "An `OrgOfficer` may cancel a `SCHEDULED` occasion, advancing it from
    `SCHEDULED` to `CANCELLED` (permitted only from `SCHEDULED`, else `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/cancel_reported_occasion_returns_invalid_state
    """
    org, lic = create_active_license()
    officer = make_orgofficer_headers(org["id"])
    occ = create_reported_occasion(
        org["id"], lic["id"],
        occasion_overrides={"planned_prize_pool_cents": 20_000},
        report_overrides={"gross_receipts_cents": 90_000, "prizes_paid_cents": 20_000,
                          "expenses_cents": 5_000},
    )
    res = api.cancel_occasion(occ["id"], officer)
    validate_error(res, "ERR_INVALID_STATE")
    fetched = validate_success(api.get_occasion(occ["id"], officer), 200)
    assert fetched["status"] == "REPORTED"


def test_occasion_end_before_start_rejected(api):
    """PRD §3.3: "The `scheduled_end` must be strictly after `scheduled_start`; otherwise
    the request is rejected with `ERR_OCCASION_TIME_INVALID`."

    Design: Corner/validations/occasion_end_before_start_rejected
    """
    org, lic = create_active_license()
    officer = make_orgofficer_headers(org["id"])
    res = api.create_occasion(
        create_occasion_payload(lic["id"], scheduled_start="2026-06-01T22:00:00Z",
                                scheduled_end="2026-06-01T18:00:00Z"),
        officer,
    )
    validate_error(res, "ERR_OCCASION_TIME_INVALID")
