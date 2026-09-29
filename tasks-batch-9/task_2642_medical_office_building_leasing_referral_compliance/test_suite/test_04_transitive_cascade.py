"""Two independent multi-hop cascades: lease termination and the delinquency close."""
from test_helpers import (
    assert_delinquency_freeze,
    assert_invoice_breakdown,
    assert_mix_figures,
    expected_invoice_total,
    get_success_data,
    validate_paginated,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import COMPLIANCE_OFFICER, PROPERTY_MANAGER


def _building_with_anchor_independent_and_affiliated_draft(api):
    """An anchor lease, an independent lease and an untouched affiliated draft with a project."""
    building = fx.register_building(api)
    anchor_suite = fx.register_suite(api, building["id"], suite_number="100", floor=1,
                                     rentable_sf=12000, suite_class="STANDARD_EXAM",
                                     power_amps_available=400)
    independent_suite = fx.register_suite(api, building["id"], suite_number="210", floor=2,
                                          rentable_sf=5000, suite_class="STANDARD_EXAM",
                                          power_amps_available=200)
    peer_suite = fx.register_suite(api, building["id"], suite_number="310", floor=3,
                                   rentable_sf=4000, suite_class="PROCEDURE",
                                   power_amps_available=300, medical_gas_available=True)
    anchor_tenant = fx.register_tenant(api, legal_name="Meridian Health System Clinics",
                                       affiliation="HEALTH_SYSTEM_ANCHOR",
                                       primary_specialty="PRIMARY_CARE")
    independent_tenant = fx.register_tenant(api, legal_name="Northgate Medical Group PC",
                                            affiliation="INDEPENDENT_PRACTICE",
                                            primary_specialty="GASTROENTEROLOGY")
    peer_tenant = fx.register_tenant(api, legal_name="Meridian Cardiovascular Associates",
                                     affiliation="HEALTH_SYSTEM_AFFILIATED",
                                     primary_specialty="CARDIOLOGY")

    anchor_lease = fx.draft_lease(api, building["id"], anchor_suite["id"], anchor_tenant["id"],
                                 term_start="2026-09-01", term_end="2031-08-31",
                                 base_rent_psf_annual=28.00)
    fx.file_attestation(api, anchor_lease["id"], "SIGNED_LEASE")
    fx.submit_for_review(api, anchor_lease["id"], "Anchor renewal")
    fx.certify(api, anchor_lease["id"], "28.00 psf inside [24.00, 34.50]")
    anchor_lease = fx.execute(api, anchor_lease["id"],
                              "Anchor executed while the posture is BALANCED")

    independent_lease = fx.draft_lease(api, building["id"], independent_suite["id"],
                                       independent_tenant["id"], term_start="2026-09-01",
                                       term_end="2029-08-31", base_rent_psf_annual=30.00)
    fx.file_attestation(api, independent_lease["id"], "SIGNED_LEASE")
    fx.submit_for_review(api, independent_lease["id"], "Independent GI practice")
    fx.certify(api, independent_lease["id"], "30.00 psf inside [24.00, 34.50]")
    independent_lease = fx.execute(api, independent_lease["id"], "Independent executed")

    peer_lease = fx.draft_lease(api, building["id"], peer_suite["id"], peer_tenant["id"],
                                term_start="2027-01-01", term_end="2032-12-31",
                                base_rent_psf_annual=34.25)
    project = fx.open_ti_project(api, peer_lease["id"], peer_suite["id"],
                                 target_suite_class="PROCEDURE", power_amps_requested=60,
                                 medical_gas_requested=False,
                                 authorized_allowance_total=250000.00,
                                 landlord_share_pct=0.50)

    fx.set_clock_date(api, "2026-09-01")
    independent_lease = fx.commence(api, independent_lease["id"],
                                    "Independent practice occupies")
    return {
        "building": building,
        "anchor_suite": anchor_suite,
        "independent_suite": independent_suite,
        "peer_suite": peer_suite,
        "anchor_lease": anchor_lease,
        "independent_lease": independent_lease,
        "peer_lease": peer_lease,
        "project": project,
    }


def test_terminating_the_independent_lease_vacates_its_suite_and_restricts_the_building(api):
    """Hops 1 and 2: the suite leaves the counted set and the anchor share becomes total.

    PRD: "**Hop 1** stamps `terminated_on` with the clock date, moves the demised suite to
    `VACANT`, sets that suite's `last_vacated_on` to the clock date and advances the suite's
    `version`."

    PRD: "**Hop 2**, fired because the suite has left the counted set, recomputes the
    building's `anchor_rentable_sf`, `independent_rentable_sf`, `leased_rentable_sf`,
    `vacant_rentable_sf`, `anchor_share_pct` and `tenant_mix_posture`, and advances the
    building's `version`."

    Design: Difficulty/transitive_cascade/lease_termination_cascades_through_building_posture_to_peer_lease_and_ti_hold
    """
    ctx = _building_with_anchor_independent_and_affiliated_draft(api)

    before = fx.read_building(api, ctx["building"]["id"])
    assert_mix_figures(before, anchor_sf=12000, independent_sf=5000, leased_sf=17000,
                       vacant_sf=83000, anchor_share_pct=0.7059,
                       posture="ANCHOR_CONCENTRATED")
    assert fx.read_lease(api, ctx["peer_lease"]["id"])["status"] == "DRAFT"
    assert fx.read_project(api, ctx["project"]["id"])["status"] == "DESIGN"

    terminated = fx.terminate(api, ctx["independent_lease"]["id"], "MUTUAL",
                              termination_note="Practice merged and relocated")
    assert terminated["status"] == "TERMINATED"
    assert terminated["terminated_on"] == "2026-09-01"

    vacated = fx.read_suite(api, ctx["independent_suite"]["id"])
    assert vacated["occupancy_status"] == "VACANT"
    assert vacated["last_vacated_on"] == "2026-09-01"

    after = fx.read_building(api, ctx["building"]["id"])
    assert_mix_figures(after, anchor_sf=12000, independent_sf=0, leased_sf=12000,
                       vacant_sf=88000, anchor_share_pct=1.0000, posture="RESTRICTED")
    assert after["version"] > before["version"]


def test_the_restricted_posture_suspends_the_unrelated_affiliated_draft_and_holds_its_project(api):
    """Hops 3 and 4: a peer lease sharing no tenant, suite or project is swept up.

    PRD: "**Hop 3** fires if and only if hop 2 moved `tenant_mix_posture` to `RESTRICTED`:
    every lease in that building whose status is `DRAFT` or `PENDING_FMV_REVIEW` and whose
    tenant's `affiliation` is `HEALTH_SYSTEM_ANCHOR` or `HEALTH_SYSTEM_AFFILIATED` is
    suspended, processed in `created_at` ascending order."

    PRD: "**Hop 4** fires if and only if hop 3 suspended at least one lease: for each
    suspended lease, every tenant-improvement project on it whose status is `DESIGN`,
    `IN_REVIEW` or `PERMITTED`, processed in `created_at` ascending order, records its current
    status into `on_hold_from_status`, moves to `ON_HOLD` and advances its `version` by 1."

    Design: Difficulty/transitive_cascade/lease_termination_cascades_through_building_posture_to_peer_lease_and_ti_hold
    """
    ctx = _building_with_anchor_independent_and_affiliated_draft(api)
    peer_before = fx.read_lease(api, ctx["peer_lease"]["id"])
    project_before = fx.read_project(api, ctx["project"]["id"])
    assert project_before["on_hold_from_status"] is None

    fx.terminate(api, ctx["independent_lease"]["id"], "MUTUAL",
                 termination_note="Practice merged and relocated")

    peer_after = fx.read_lease(api, ctx["peer_lease"]["id"])
    assert peer_after["status"] == "SUSPENDED_MIX_REVIEW"
    assert peer_after["fmv_certification_status"] == "NOT_STARTED"
    assert peer_after["version"] == peer_before["version"] + 1

    project_after = fx.read_project(api, ctx["project"]["id"])
    assert project_after["status"] == "ON_HOLD"
    assert project_after["on_hold_from_status"] == "DESIGN"
    assert project_after["version"] == project_before["version"] + 1

    assert fx.read_lease(api, ctx["anchor_lease"]["id"])["status"] == "EXECUTED"


def _tenant_sixty_three_days_in_arrears(api):
    """An ACTIVE lease with after-hours access, a future booking and one unpaid invoice."""
    ctx = fx.bookable_lease(
        api,
        space_overrides={"name": "Second Floor Shared Waiting Room",
                         "space_type": "WAITING_ROOM", "capacity_seats": 24,
                         "opens_at": "07:00", "closes_at": "19:00"},
        lease_overrides={"base_rent_psf_annual": 32.00},
    )
    lease_id = ctx["lease"]["id"]
    ctx["lease"] = fx.authorize_after_hours(api, lease_id, True)
    ctx["booking"] = fx.book(api, ctx["shared_space"]["id"], lease_id,
                             "2026-12-01T09:00:00Z", "2026-12-01T11:00:00Z", 10)
    ctx["invoice"] = fx.issue_invoice(api, lease_id, "2026-09-01", "2026-09-30", "2026-09-05")
    fx.set_clock_date(api, "2026-11-07")
    return ctx


def test_the_close_flags_the_invoice_and_lifts_both_tenant_scores_to_fifty(api):
    """Hops 1 and 2: a 63-day count freezes the top tier weight and rescores the tenant.

    PRD: "The weight tiers are keyed on the day count itself rather than on days past grace,
    which means the day an invoice becomes delinquent it is already worth 15 points: a day
    count of at most 30 carries a weight of 15, a count of at most 60 carries 30, and a count
    beyond 60 carries 50."

    PRD: "**Hop 1** writes `days_past_due` and `days_past_due_at_flag` from the day count and
    freezes `delinquency_tier_weight` at the corresponding tier. **Hop 2** increases the
    tenant's `delinquency_event_count` by 1, recomputes both `referral_compliance_risk_score`
    and `strict_cumulative_risk_score`, and advances the tenant's `version`."

    Design: Difficulty/transitive_cascade/daily_close_delinquency_cascades_to_watch_case_concession_lock_and_booking_cancellation
    """
    ctx = _tenant_sixty_three_days_in_arrears(api)
    assert_invoice_breakdown(ctx["invoice"],
                             expected_invoice_total(160000.00, 9.60, 5000))
    assert ctx["invoice"]["status"] == "ISSUED"

    fx.run_daily_close(api)

    delinquent, meta = validate_paginated(
        api.list_lease_rent_invoices(ctx["lease"]["id"], PROPERTY_MANAGER,
                                     params={"status": "DELINQUENT"}))
    assert meta["total_count"] == 1
    assert delinquent[0]["id"] == ctx["invoice"]["id"]
    assert delinquent[0]["days_past_due"] == 63
    assert_delinquency_freeze(delinquent[0], 63)
    assert delinquent[0]["delinquency_tier_weight"] == 50

    tenant = fx.read_tenant(api, ctx["tenant"]["id"], COMPLIANCE_OFFICER)
    assert tenant["delinquency_event_count"] == 1
    assert tenant["referral_compliance_risk_score"] == 50
    assert tenant["strict_cumulative_risk_score"] == 50


def test_the_rolling_score_raises_watch_and_sweeps_the_lease_book_and_future_booking(api):
    """Hops 3 and 3b: one case opens, concessions lock, access is revoked, the booking dies.

    PRD: "**Hop 3** fires when the recomputed **rolling** score is at least 45: the tenant's
    `compliance_watch_status` becomes `WATCH` and the system opens a compliance case against
    that tenant with `case_type` `RENT_DELINQUENCY` in status `OPEN`, at `HIGH` severity when
    the recomputed rolling score is at least 90 and `MEDIUM` otherwise, with `scoring_variant`
    `ROLLING_12M`, `risk_score_at_open` set to that recomputed rolling score, `opened_on` set
    to the clock date, `opened_by_user_id` recorded as the literal value `system`, and
    `remediation_due_on` set to the clock date plus 30 days."

    PRD: "every lease of that tenant whose status is anything other than `TERMINATED` or
    `WITHDRAWN` — drafts and certified deals very much included, because a pending deal is
    exactly where an improper concession would be granted — is processed in `created_at`
    ascending order to set `rent_concession_locked` to true, clear `after_hours_authorized` to
    false and advance that lease's `version` by 1; and on each of those leases, every
    shared-space booking still in `BOOKED` whose `window_start` is later than the current clock
    moves to `CANCELLED` with `cancellation_source` recorded as `COMPLIANCE_CASCADE`."

    Design: Difficulty/transitive_cascade/daily_close_delinquency_cascades_to_watch_case_concession_lock_and_booking_cancellation
    """
    ctx = _tenant_sixty_three_days_in_arrears(api)
    assert ctx["lease"]["after_hours_authorized"] is True
    assert ctx["lease"]["rent_concession_locked"] is False
    assert ctx["booking"]["status"] == "BOOKED"

    fx.run_daily_close(api)

    tenant = fx.read_tenant(api, ctx["tenant"]["id"], COMPLIANCE_OFFICER)
    assert tenant["compliance_watch_status"] == "WATCH"

    cases, meta = validate_paginated(
        api.list_tenant_compliance_cases(ctx["tenant"]["id"], COMPLIANCE_OFFICER,
                                         params={"case_type": "RENT_DELINQUENCY"}))
    assert meta["total_count"] == 1
    case = cases[0]
    assert case["status"] == "OPEN"
    assert case["severity"] == "MEDIUM"
    assert case["scoring_variant"] == "ROLLING_12M"
    assert case["risk_score_at_open"] == 50
    assert case["opened_on"] == "2026-11-07"
    assert case["opened_by_user_id"] == "system"
    assert case["remediation_due_on"] == "2026-12-07"

    lease = fx.read_lease(api, ctx["lease"]["id"])
    assert lease["rent_concession_locked"] is True
    assert lease["after_hours_authorized"] is False

    booking = get_success_data(api.get_booking(ctx["booking"]["id"], PROPERTY_MANAGER))
    assert booking["status"] == "CANCELLED"
    assert booking["cancellation_source"] == "COMPLIANCE_CASCADE"
