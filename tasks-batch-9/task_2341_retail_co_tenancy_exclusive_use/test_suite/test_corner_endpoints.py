"""Endpoint-surface behaviour: list filtering and pagination, the read-only
prohibited-use screen, the compliance sweep, the logical clock, the dispute
sub-resources, notice cure, certificate rejection and the remaining filtered
collection reads.
"""
from typing import Any, Dict

from test_helpers import (
    ASSET_MANAGER_USER_ID,
    COMPLIANCE_ENFORCER_USER_ID,
    COMPLIANCE_OFFICER_USER_ID,
    COMPLIANCE_SWEEPER_USER_ID,
    DEFAULT_CLOCK_UTC,
    LENDER_REP_USER_ID,
    Scenario,
    add_clause,
    add_condition,
    assert_center_quantities,
    assert_lease_dimensions,
    assert_null,
    assert_pagination_meta,
    assert_pct,
    assert_screen_decision_shape,
    assert_sweep_report_shape,
    build_center_with_leases,
    create_tenant,
    cure_notice,
    draft_lease,
    elect_remedy,
    factories,
    fetch_center,
    fetch_certificate,
    fetch_dispute,
    fetch_lease,
    fetch_measurement,
    fetch_notice,
    file_dispute,
    go_dark,
    ids_of,
    issue_notice,
    make_asset_manager_headers,
    make_compliance_officer_headers,
    make_lease_administrator_headers,
    make_lender_rep_headers,
    plan_redevelopment,
    prepare_measurement,
    request_certificate,
    run_sweep,
    set_clock,
    sign_certificate,
    validate_paginated,
    validate_success,
)

# --------------------------------------------------------------------------
# Shared preconditions, built from scratch through the API for every test
# --------------------------------------------------------------------------
FIVE_SUITE_SPECS = (
    {
        "suite_code": "A1",
        "gla_sqft": 120000,
        "parcel_kind": "ANCHOR_BOX",
        "primary_use_code": "DISCOUNT_DEPT",
        "base_rent_monthly_cents": 6000000,
        "expiration_date": "2036-12-31",
    },
    {
        "suite_code": "A2",
        "gla_sqft": 100000,
        "parcel_kind": "ANCHOR_BOX",
        "primary_use_code": "GROCERY",
        "base_rent_monthly_cents": 4000000,
        "expiration_date": "2036-12-31",
    },
    {
        "suite_code": "I1",
        "gla_sqft": 2000,
        "primary_use_code": "COFFEE",
        "base_rent_monthly_cents": 1000000,
        "expiration_date": "2036-12-31",
    },
    {
        "suite_code": "I2",
        "gla_sqft": 3000,
        "primary_use_code": "BOOKS",
        "base_rent_monthly_cents": 1200000,
        "expiration_date": "2036-12-31",
    },
    {
        "suite_code": "I3",
        "gla_sqft": 30000,
        "primary_use_code": "FITNESS",
        "base_rent_monthly_cents": 1500000,
        "expiration_date": "2036-12-31",
    },
)


def _five_suite_center(api) -> Scenario:
    """A 300,000 sqft center with two open anchors and three open inline suites.

    Counted area is 255,000 sqft, so ``open_occupancy_pct`` is 85.00 and the
    center is `COMPLIANT` (PRD §2.5, §2.6).
    """
    return build_center_with_leases(
        api,
        [dict(spec) for spec in FIVE_SUITE_SPECS],
        total_gla_sqft=300000,
        occupancy_grace_days=30,
        clock=DEFAULT_CLOCK_UTC,
    )


def _assert_instant(value: Any, expected_prefix: str, label: str) -> None:
    """Instants are ISO 8601 UTC with three fractional digits (PRD §2.4)."""
    assert value is not None, f"{label} should be stamped, got null"
    assert str(value).startswith(expected_prefix), (
        f"{label} is {value!r}, expected the instant {expected_prefix}"
    )


def _center_wide_clause(api, lease_id: str, use_code: str) -> Dict[str, Any]:
    return add_clause(
        api,
        lease_id,
        protected_use_codes=[use_code],
        exclusivity_scope="CENTER_WIDE",
        effective_from_date="2026-01-01",
        effective_through_date="2036-12-31",
        gla_carve_out_sqft=0,
        incidental_sales_pct_cap=0.0,
    )


# --------------------------------------------------------------------------
# GET /leases — filtering and pagination
# --------------------------------------------------------------------------
def test_lease_listing_reports_the_filtered_total_and_the_requested_page(api):
    """A filtered lease page reports the pre-pagination filtered total, the echoed window and has_more.

    PRD: "List responses carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of records matching the filters before pagination is applied and `has_more` indicates whether records remain beyond the current page."

    Design: Corner/endpoints/leases_list_filters_by_status_and_paginates
    """
    scenario = _five_suite_center(api)
    go_dark(api, scenario.lease_id("I3"))

    res = api.list_leases(
        make_lease_administrator_headers(),
        params={
            "center_id": scenario.center_id,
            "premises_status": "OPEN",
            "limit": 2,
            "offset": 1,
        },
    )
    rows, meta = validate_paginated(res)

    # Four of the five leases are still OPEN, so the filtered total is 4, not 5.
    assert_pagination_meta(
        meta,
        expected_total=4,
        expected_limit=2,
        expected_offset=1,
        expected_has_more=True,
    )
    assert len(rows) == 2, f"expected exactly 2 rows on the page, got {len(rows)}"
    assert res.json()["response_type"] == "array"


def test_lease_listing_filtered_on_premises_status_omits_the_dark_lease(api):
    """Filtering leases on premises_status returns only rows in that status.

    PRD: "List endpoints accept the query parameters named in §3 alongside `limit` and `offset`: centers filter on `compliance_posture`; leases on `center_id`, `tenant_id`, `replacement_for_lease_id`, `premises_status`, `remedy_status`, and `parcel_kind`; co-tenancy conditions on `lease_id`, `last_evaluated_measurement_id`, `condition_kind`, and `status`; anchor requirements on `condition_id` and `anchor_lease_id`; exclusive-use clauses on `lease_id`, `suspended_by_plan_id`, `status`, and `exclusivity_scope`; radius restrictions on `lease_id`, `status`, and `recapture_basis`; notices on `violating_lease_id`, `clause_id`, `radius_restriction_id`, `notice_kind`, and `status`; disputes on `notice_id`, `filed_by_tenant_id`, `status`, and `grounds_code`; elections on `lease_id`, `condition_id`, `source_notice_id`, `election_kind`, and `status`; measurements on `center_id`, `variant`, and `status`; estoppel certificates on `lease_id`, `measurement_id`, and `status`; and redevelopment plans on `center_id`, `pad_parcel_lease_id`, `plan_kind`, and `status`."

    Design: Corner/endpoints/leases_list_filters_by_status_and_paginates
    """
    scenario = _five_suite_center(api)
    dark_lease_id = scenario.lease_id("I3")
    go_dark(api, dark_lease_id)

    res = api.list_leases(
        make_lease_administrator_headers(),
        params={
            "center_id": scenario.center_id,
            "premises_status": "OPEN",
            "limit": 2,
            "offset": 1,
        },
    )
    rows, _ = validate_paginated(res)

    for row in rows:
        assert row["premises_status"] == "OPEN", (
            f"lease {row['id']} came back with premises_status {row['premises_status']}"
        )
    assert dark_lease_id not in ids_of(rows), "the DARK lease leaked into an OPEN filter"


# --------------------------------------------------------------------------
# POST /leases/{id}/screen-use
# --------------------------------------------------------------------------
def _screening_scenario(api):
    """Three BOOKS clauses of different scopes, plus a DRAFT BOOKS candidate."""
    scenario = _five_suite_center(api)
    protected_lease_id = scenario.lease_id("I2")
    clauses = {}
    for scope in ("PAD_EXCLUDED", "RADIUS_INCLUSIVE", "CENTER_WIDE"):
        clauses[scope] = add_clause(
            api,
            protected_lease_id,
            protected_use_codes=["BOOKS"],
            exclusivity_scope=scope,
            effective_from_date="2026-01-01",
            effective_through_date="2036-12-31",
            gla_carve_out_sqft=0,
            incidental_sales_pct_cap=0.0,
        )
    candidate_tenant = create_tenant(
        api, legal_name="Chapter Two Books LLC", primary_use_code="BOOKS"
    )
    candidate = draft_lease(
        api,
        scenario.center_id,
        candidate_tenant["id"],
        suite_code="I8",
        gla_sqft=4000,
        parcel_kind="INLINE",
        primary_use_code="BOOKS",
        base_rent_monthly_cents=900000,
        commencement_date="2026-10-01",
        expiration_date="2036-09-30",
    )
    return scenario, clauses, candidate


def test_screen_use_names_the_center_wide_clause_as_controlling(api):
    """The controlling clause of three conflicting scopes is the CENTER_WIDE one.

    PRD: "When there is at least one conflict the `decision` is `CONFLICT` and `controlling_clause_id` names the single controlling clause, chosen by ranking the conflicts on three keys in order: scope severity descending, where `CENTER_WIDE` ranks 3, `RADIUS_INCLUSIVE` ranks 2, and `PAD_EXCLUDED` ranks 1; then `gla_carve_out_sqft` ascending; then `created_at` ascending."

    Design: Corner/endpoints/screen_use_is_a_read_only_computed_endpoint
    """
    _, clauses, candidate = _screening_scenario(api)

    res = api.screen_use(
        candidate["id"],
        None,
        make_compliance_officer_headers(COMPLIANCE_OFFICER_USER_ID),
    )
    decision = validate_success(res, 200)
    assert_screen_decision_shape(decision)

    assert decision["decision"] == "CONFLICT"
    assert decision["controlling_clause_id"] == clauses["CENTER_WIDE"]["id"]
    assert decision["screened_use_code"] == "BOOKS"
    # No carve-out can suppress a candidate whose own incidental list is empty.
    assert decision["eligible_clause_count"] == 3
    assert decision["conflicting_clause_count"] == 3
    assert decision["carve_out_applied"] is False


def test_screen_use_mutates_nothing(api):
    """Screening is a read-only decision: the candidate lease and the center are untouched.

    PRD: "The **prohibited-use screen** is the heart of this subsection, and it can be run as a read-only decision by a `LeaseAdministrator` or a `ComplianceOfficer` before anyone commits, as well as being applied as a hard gate inside lease execution."

    Design: Corner/endpoints/screen_use_is_a_read_only_computed_endpoint
    """
    scenario, _, candidate = _screening_scenario(api)

    api.screen_use(
        candidate["id"],
        None,
        make_compliance_officer_headers(COMPLIANCE_OFFICER_USER_ID),
    )

    after = fetch_lease(api, candidate["id"])
    assert after["premises_status"] == "DRAFT"
    assert after["version"] == 1, "screening must not bump the candidate's version"

    notices = api.list_notices(
        make_compliance_officer_headers(),
        params={"violating_lease_id": candidate["id"]},
    )
    _, notice_meta = validate_paginated(notices)
    assert notice_meta["total_count"] == 0, "screening must not mint a notice"

    assert_center_quantities(
        fetch_center(api, scenario.center_id), compliance_posture="COMPLIANT"
    )


# --------------------------------------------------------------------------
# POST /centers/{id}/compliance-sweep
# --------------------------------------------------------------------------
def _sweep_scenario(api):
    """One notice past its cure deadline and one notice under a pending dispute."""
    scenario = _five_suite_center(api)
    coffee_clause = _center_wide_clause(api, scenario.lease_id("I1"), "COFFEE")
    books_clause = _center_wide_clause(api, scenario.lease_id("I2"), "BOOKS")
    expired_notice = issue_notice(
        api,
        scenario.lease_id("I3"),
        notice_kind="EXCLUSIVE_USE",
        clause_id=coffee_clause["id"],
        narrative="Espresso bar in the fitness premises.",
        cure_period_days=30,
        user_id=COMPLIANCE_ENFORCER_USER_ID,
    )
    disputed_notice = issue_notice(
        api,
        scenario.lease_id("I3"),
        notice_kind="EXCLUSIVE_USE",
        clause_id=books_clause["id"],
        narrative="Retail book wall in the fitness premises.",
        cure_period_days=30,
        user_id=COMPLIANCE_ENFORCER_USER_ID,
    )
    dispute = file_dispute(
        api,
        disputed_notice["id"],
        scenario.tenant_id("I3"),
        grounds_code="SCOPE_INAPPLICABLE",
        narrative="Titles are training manuals.",
        cure_extension_days=0,
    )
    set_clock(api, "2026-09-01T00:00:00Z")
    return scenario, coffee_clause, expired_notice, disputed_notice, dispute


def test_sweep_escalates_the_expired_notice_and_skips_the_disputed_one(api):
    """The sweep escalates the notice whose deadline passed and leaves the disputed notice alone.

    PRD: "Every notice of the center whose cure deadline has passed and against which no dispute is `PENDING` is escalated with the full four-hop cascade of §3.6; notices with a pending dispute are **skipped rather than failed**."

    Design: Corner/endpoints/compliance_sweep_escalates_expired_notices_and_reports_counts
    """
    scenario, _, expired_notice, disputed_notice, dispute = _sweep_scenario(api)

    report = run_sweep(api, scenario.center_id, user_id=COMPLIANCE_SWEEPER_USER_ID)
    assert_sweep_report_shape(report)

    _assert_instant(report["as_of"], "2026-09-01T00:00:00", "sweep as_of")
    assert report["escalated_notice_count"] == 1
    assert report["cured_condition_count"] == 0
    assert report["breached_condition_count"] == 0
    assert report["compliance_posture"] == "WATCH"

    escalated = fetch_notice(api, expired_notice["id"])
    assert escalated["status"] == "ESCALATED"
    _assert_instant(escalated["escalated_at"], "2026-09-01T00:00:00", "escalated_at")

    skipped = fetch_notice(api, disputed_notice["id"])
    assert skipped["status"] == "DISPUTED"
    assert_null(skipped["escalated_at"], "escalated_at of the skipped notice")
    assert fetch_dispute(api, dispute["id"])["status"] == "PENDING"

    assert_lease_dimensions(
        fetch_lease(api, scenario.lease_id("I3")),
        use_compliance_status="IN_VIOLATION",
    )
    center = fetch_center(api, scenario.center_id)
    assert_center_quantities(
        center, open_violation_count=2, compliance_posture="WATCH"
    )
    _assert_instant(center["last_sweep_at"], "2026-09-01T00:00:00", "last_sweep_at")


def test_sweep_escalation_makes_the_benefited_lease_remedy_eligible(api):
    """Escalating an exclusive-use notice inside the sweep makes the benefited lease ELIGIBLE.

    PRD: "Separately from that hop chain, an `EXCLUSIVE_USE` notice fans out to the benefited lease of its `clause_id`, moving that lease's `remedy_status` from `NONE` to `ELIGIBLE` with `remedy_eligible_at` stamped at the sweep instant — opening the door to a substitute-rent election — and the center's posture is re-derived."

    Design: Corner/endpoints/compliance_sweep_escalates_expired_notices_and_reports_counts
    """
    scenario, _, _, _, _ = _sweep_scenario(api)

    report = run_sweep(api, scenario.center_id, user_id=COMPLIANCE_SWEEPER_USER_ID)

    assert report["newly_eligible_lease_count"] == 1
    benefited = fetch_lease(api, scenario.lease_id("I1"))
    assert_lease_dimensions(benefited, remedy_status="ELIGIBLE")
    _assert_instant(
        benefited["remedy_eligible_at"], "2026-09-01T00:00:00", "remedy_eligible_at"
    )


# --------------------------------------------------------------------------
# POST /_clock/set_current_utc
# --------------------------------------------------------------------------
def test_clock_advance_alone_does_not_escalate_a_live_notice(api):
    """Repositioning the clock inside a cure period leaves the notice ISSUED and un-escalated.

    PRD: "Repositioning the clock re-runs the abatement ledger and the effective-rent recomputation for every lease that has an active reduction, and re-derives estoppel-certificate staleness — but it never escalates a notice and never changes a co-tenancy condition's status."

    Design: Corner/endpoints/clock_advance_alone_does_not_escalate_a_live_notice
    """
    scenario = _five_suite_center(api)
    coffee_clause = _center_wide_clause(api, scenario.lease_id("I1"), "COFFEE")
    notice = issue_notice(
        api,
        scenario.lease_id("I3"),
        notice_kind="EXCLUSIVE_USE",
        clause_id=coffee_clause["id"],
        narrative="Espresso bar in the fitness premises.",
        cure_period_days=30,
        user_id=COMPLIANCE_ENFORCER_USER_ID,
    )

    clock = set_clock(api, "2026-08-20T00:00:00Z")
    _assert_instant(clock["current_utc"], "2026-08-20T00:00:00", "current_utc")

    after = fetch_notice(api, notice["id"])
    assert after["status"] == "ISSUED"
    assert_null(after["escalated_at"], "escalated_at")
    assert after["cure_restart_count"] == 0
    # issued_at 2026-08-01 plus the 30-day cure period.
    _assert_instant(after["cure_deadline_at"], "2026-08-31T00:00:00", "cure_deadline_at")

    assert_lease_dimensions(
        fetch_lease(api, scenario.lease_id("I3")), use_compliance_status="UNDER_NOTICE"
    )
    assert_lease_dimensions(
        fetch_lease(api, scenario.lease_id("I1")), remedy_status="NONE"
    )
    assert_center_quantities(
        fetch_center(api, scenario.center_id),
        open_violation_count=1,
        compliance_posture="WATCH",
    )


# --------------------------------------------------------------------------
# The two dispute sub-resources
# --------------------------------------------------------------------------
def _two_disputes_scenario(api):
    """Two notices against two different leases, each with its own pending dispute."""
    scenario = _five_suite_center(api)
    coffee_clause = _center_wide_clause(api, scenario.lease_id("I1"), "COFFEE")
    fitness_clause = _center_wide_clause(api, scenario.lease_id("I3"), "FITNESS")
    notice_one = issue_notice(
        api,
        scenario.lease_id("I3"),
        notice_kind="EXCLUSIVE_USE",
        clause_id=coffee_clause["id"],
        narrative="Espresso bar in the fitness premises.",
        cure_period_days=30,
        user_id=COMPLIANCE_ENFORCER_USER_ID,
    )
    notice_two = issue_notice(
        api,
        scenario.lease_id("I2"),
        notice_kind="EXCLUSIVE_USE",
        clause_id=fitness_clause["id"],
        narrative="Yoga studio inside the bookstore.",
        cure_period_days=30,
        user_id=COMPLIANCE_ENFORCER_USER_ID,
    )
    dispute_one = file_dispute(
        api,
        notice_one["id"],
        scenario.tenant_id("I3"),
        grounds_code="CARVE_OUT_APPLIES",
        narrative="Coffee is ancillary.",
        cure_extension_days=0,
    )
    dispute_two = file_dispute(
        api,
        notice_two["id"],
        scenario.tenant_id("I2"),
        grounds_code="SCOPE_INAPPLICABLE",
        narrative="Free author events only.",
        cure_extension_days=0,
    )
    return scenario, notice_one, dispute_one, dispute_two


def test_notice_disputes_subresource_returns_only_that_notices_disputes(api):
    """A notice's dispute listing carries only the dispute whose parent notice it is.

    PRD: "The dispute is created `PENDING` with `filed_by_tenant_id` copied from `X-User-ID`, `adjudicated_by_user_id` null, and `adjudicated_at` null; the parent notice moves `ISSUED → DISPUTED`, its `use_compliance_status` contribution becomes `UNDER_NOTICE`, and its cure clock is suspended — `cure_deadline_at` is frozen where it stands, so escalation is blocked until adjudication."

    Design: Corner/endpoints/notice_disputes_subresource_returns_only_that_notices_disputes
    """
    _, notice_one, dispute_one, dispute_two = _two_disputes_scenario(api)

    res = api.list_notice_disputes(
        notice_one["id"], make_compliance_officer_headers(COMPLIANCE_ENFORCER_USER_ID)
    )
    rows, meta = validate_paginated(res)

    assert meta["total_count"] == 1
    assert ids_of(rows) == [dispute_one["id"]]
    assert dispute_two["id"] not in ids_of(rows)
    assert rows[0]["notice_id"] == notice_one["id"]
    assert rows[0]["status"] == "PENDING"


def test_tenant_dispute_listing_returns_only_that_tenants_disputes(api):
    """A tenant's dispute listing carries only the disputes stamped with that tenant's id.

    PRD: "When a tenant files a dispute, the server stamps `filed_by_tenant_id` from `X-User-ID` rather than accepting it from the body."

    Design: Corner/endpoints/notice_disputes_subresource_returns_only_that_notices_disputes
    """
    scenario, _, dispute_one, dispute_two = _two_disputes_scenario(api)

    res = api.list_tenant_disputes(
        scenario.tenant_id("I2"), make_lease_administrator_headers()
    )
    rows, meta = validate_paginated(res)

    assert meta["total_count"] == 1
    assert ids_of(rows) == [dispute_two["id"]]
    assert rows[0]["filed_by_tenant_id"] == scenario.tenant_id("I2")
    assert (
        fetch_dispute(api, dispute_one["id"])["filed_by_tenant_id"]
        == scenario.tenant_id("I3")
    )


# --------------------------------------------------------------------------
# POST /use-violation-notices/{id}/cure
# --------------------------------------------------------------------------
def _noticed_scenario(api):
    """A healthy center holding one issued notice, so the center sits at WATCH."""
    scenario = _five_suite_center(api)
    coffee_clause = _center_wide_clause(api, scenario.lease_id("I1"), "COFFEE")
    notice = issue_notice(
        api,
        scenario.lease_id("I3"),
        notice_kind="EXCLUSIVE_USE",
        clause_id=coffee_clause["id"],
        narrative="Espresso bar in the fitness premises.",
        cure_period_days=30,
        user_id=COMPLIANCE_ENFORCER_USER_ID,
    )
    return scenario, notice


def test_curing_the_only_notice_returns_the_lease_to_clear(api):
    """Accepting the cure drives the notice CURED, clears the lease and decrements the count.

    PRD: "A cure is accepted from `ISSUED` or `ESCALATED` and requires that no dispute of the notice is still `PENDING`; the notice reaches the terminal `CURED`, the lease's `use_compliance_status` returns to `CLEAR` when no other notice against it remains `ISSUED`, `DISPUTED`, or `ESCALATED`, the center's `open_violation_count` decrements, and posture is re-derived."

    Design: Corner/endpoints/notice_cure_clears_the_lease_and_relaxes_posture
    """
    scenario, notice = _noticed_scenario(api)

    cured = cure_notice(api, notice["id"], cure_evidence_code="USE_DISCONTINUED")

    assert cured["status"] == "CURED"
    assert fetch_notice(api, notice["id"])["status"] == "CURED"
    assert_lease_dimensions(
        fetch_lease(api, scenario.lease_id("I3")),
        premises_status="OPEN",
        use_compliance_status="CLEAR",
    )
    assert_center_quantities(
        fetch_center(api, scenario.center_id), open_violation_count=0
    )


def test_curing_the_only_notice_relaxes_the_posture_to_compliant(api):
    """With no open violation left and occupancy at 85.00 the center falls out of WATCH.

    PRD: "Otherwise the posture is `WATCH` when `open_violation_count` is at least one, or when the center is assessable and its `open_occupancy_pct` is strictly below 70.00."

    Design: Corner/endpoints/notice_cure_clears_the_lease_and_relaxes_posture
    """
    scenario, notice = _noticed_scenario(api)
    before = fetch_center(api, scenario.center_id)
    assert_center_quantities(before, compliance_posture="WATCH")

    cure_notice(api, notice["id"], cure_evidence_code="USE_DISCONTINUED")

    after = fetch_center(api, scenario.center_id)
    assert_center_quantities(
        after,
        open_violation_count=0,
        open_occupancy_pct=85.00,
        compliance_posture="COMPLIANT",
    )


# --------------------------------------------------------------------------
# POST /estoppel-certificates/{id}/reject
# --------------------------------------------------------------------------
def _signed_certificate_scenario(api):
    """A certificate on the open inline suite I1, requested by a lender and signed."""
    scenario = _five_suite_center(api)
    certificate = request_certificate(
        api,
        scenario.lease_id("I1"),
        expedite_requested=False,
        user_id=LENDER_REP_USER_ID,
    )
    signed = sign_certificate(api, certificate["id"], scenario.tenant_id("I1"))
    return scenario, signed


def test_rejecting_a_signed_certificate_is_terminal_and_never_accepted(api):
    """A lender rejection drives a TENANT_SIGNED certificate to REJECTED with accepted_at null.

    PRD: "A `LenderRep` or `AssetManager` rejects a certificate that is `REQUESTED`, `TENANT_SIGNED`, or `STALE` by supplying a `rejection_reason_code`, driving it to the terminal `REJECTED`."

    Design: Corner/endpoints/certificate_rejection_is_a_terminal_lender_action
    """
    scenario, signed = _signed_certificate_scenario(api)
    assert signed["status"] == "TENANT_SIGNED"

    res = api.reject_certificate(
        signed["id"],
        factories.reject_certificate_payload("DISCLOSURE_INCOMPLETE"),
        make_lender_rep_headers(LENDER_REP_USER_ID),
    )
    rejected = validate_success(res, 200)

    assert rejected["status"] == "REJECTED"
    assert_null(rejected["accepted_at"], "accepted_at")
    _assert_instant(rejected["signed_at"], "2026-08-01T00:00:00", "signed_at")
    # The estopped lease is untouched by the lender's exit.
    assert_lease_dimensions(
        fetch_lease(api, scenario.lease_id("I1")),
        premises_status="OPEN",
        effective_rent_monthly_cents=1000000,
    )
    assert_center_quantities(
        fetch_center(api, scenario.center_id), compliance_posture="COMPLIANT"
    )


def test_rejected_certificate_keeps_its_fee(api):
    """Rejection neither refunds nor zeroes the certificate fee.

    PRD: "The fee survives rejection: `total_fee_cents` is neither refunded nor zeroed."

    Design: Corner/endpoints/certificate_rejection_is_a_terminal_lender_action
    """
    _, signed = _signed_certificate_scenario(api)

    api.reject_certificate(
        signed["id"],
        factories.reject_certificate_payload("DISCLOSURE_INCOMPLETE"),
        make_lender_rep_headers(LENDER_REP_USER_ID),
    )

    after = fetch_certificate(api, signed["id"])
    assert after["status"] == "REJECTED"
    # No disclosed clause and no disclosed breach, so the subtotal is the base fee
    # alone; expedite was not requested, so no surcharge is added.
    assert after["base_fee_cents"] == 25000
    assert after["total_fee_cents"] == 25000


# --------------------------------------------------------------------------
# The remaining filtered collection reads
# --------------------------------------------------------------------------
def _collections_scenario(api) -> Dict[str, Any]:
    """One row per remaining collection, each distinguishable by its filter keys."""
    scenario = _five_suite_center(api)
    benefited_lease_id = scenario.lease_id("I1")
    condition = add_condition(
        api,
        benefited_lease_id,
        condition_kind="ONGOING",
        measurement_basis="GLA_PCT",
        required_occupancy_pct=81.67,
        required_anchor_count=2,
        grace_period_days=0,
        cure_period_days=30,
        remedy_type="RENT_REDUCTION_THEN_TERMINATION",
        max_reduction_pct=25.0,
    )
    # Suite I3 going dark drops occupancy to 75.00, breaching the condition and
    # making the benefited lease eligible immediately on a zero grace period.
    go_dark(api, scenario.lease_id("I3"))
    election = elect_remedy(
        api,
        benefited_lease_id,
        scenario.tenant_id("I1"),
        election_kind="RENT_REDUCTION",
        window_from_date="2026-08-01",
        window_through_date="2026-11-01",
        condition_id=condition["id"],
    )
    measurement = prepare_measurement(
        api,
        scenario.center_id,
        variant="SNAPSHOT_STRICT",
        window_from_date="2026-07-01",
        window_through_date="2026-08-02",
        user_id=COMPLIANCE_OFFICER_USER_ID,
    )
    certificate = request_certificate(
        api,
        scenario.lease_id("I2"),
        expedite_requested=False,
        user_id=LENDER_REP_USER_ID,
    )
    plan = plan_redevelopment(
        api,
        scenario.center_id,
        plan_kind="EXPANSION",
        removed_gla_sqft=0,
        user_id=ASSET_MANAGER_USER_ID,
    )
    coffee_clause = _center_wide_clause(api, benefited_lease_id, "COFFEE")
    notice = issue_notice(
        api,
        scenario.lease_id("I3"),
        notice_kind="EXCLUSIVE_USE",
        clause_id=coffee_clause["id"],
        narrative="Espresso bar in the fitness premises.",
        cure_period_days=30,
        user_id=COMPLIANCE_ENFORCER_USER_ID,
    )
    dispute = file_dispute(
        api,
        notice["id"],
        scenario.tenant_id("I3"),
        grounds_code="CARVE_OUT_APPLIES",
        narrative="Coffee is ancillary.",
        cure_extension_days=0,
    )
    return {
        "scenario": scenario,
        "condition": condition,
        "election": election,
        "measurement": measurement,
        "certificate": certificate,
        "plan": plan,
        "notice": notice,
        "dispute": dispute,
    }


def test_remaining_collection_reads_return_only_the_filtered_row(api):
    """Each remaining collection route, and the center-scoped measurement route, returns its one matching row.

    PRD: "List endpoints accept the query parameters named in §3 alongside `limit` and `offset`: centers filter on `compliance_posture`; leases on `center_id`, `tenant_id`, `replacement_for_lease_id`, `premises_status`, `remedy_status`, and `parcel_kind`; co-tenancy conditions on `lease_id`, `last_evaluated_measurement_id`, `condition_kind`, and `status`; anchor requirements on `condition_id` and `anchor_lease_id`; exclusive-use clauses on `lease_id`, `suspended_by_plan_id`, `status`, and `exclusivity_scope`; radius restrictions on `lease_id`, `status`, and `recapture_basis`; notices on `violating_lease_id`, `clause_id`, `radius_restriction_id`, `notice_kind`, and `status`; disputes on `notice_id`, `filed_by_tenant_id`, `status`, and `grounds_code`; elections on `lease_id`, `condition_id`, `source_notice_id`, `election_kind`, and `status`; measurements on `center_id`, `variant`, and `status`; estoppel certificates on `lease_id`, `measurement_id`, and `status`; and redevelopment plans on `center_id`, `pad_parcel_lease_id`, `plan_kind`, and `status`."

    Design: Corner/endpoints/remaining_collection_reads_return_only_the_filtered_row
    """
    built = _collections_scenario(api)
    scenario = built["scenario"]
    headers = make_asset_manager_headers(ASSET_MANAGER_USER_ID)

    reads = (
        (
            "disputes",
            api.list_disputes(
                headers,
                params={"notice_id": built["notice"]["id"], "status": "PENDING"},
            ),
            built["dispute"]["id"],
        ),
        (
            "measurements",
            api.list_measurements(
                headers,
                params={
                    "center_id": scenario.center_id,
                    "variant": "SNAPSHOT_STRICT",
                    "status": "DRAFT",
                },
            ),
            built["measurement"]["id"],
        ),
        (
            "center measurements",
            api.list_center_measurements(
                scenario.center_id, headers, params={"status": "DRAFT"}
            ),
            built["measurement"]["id"],
        ),
        (
            "elections",
            api.list_elections(
                headers,
                params={"lease_id": scenario.lease_id("I1"), "status": "ELECTED"},
            ),
            built["election"]["id"],
        ),
        (
            "certificates",
            api.list_certificates(
                headers,
                params={"lease_id": scenario.lease_id("I2"), "status": "REQUESTED"},
            ),
            built["certificate"]["id"],
        ),
        (
            "plans",
            api.list_plans(
                headers,
                params={"center_id": scenario.center_id, "plan_kind": "EXPANSION"},
            ),
            built["plan"]["id"],
        ),
    )

    for label, res, expected_id in reads:
        rows, meta = validate_paginated(res)
        assert res.json()["response_type"] == "array", f"{label} is not an array read"
        assert meta["total_count"] == 1, (
            f"{label} reported total_count {meta['total_count']}, expected 1"
        )
        assert ids_of(rows) == [expected_id], (
            f"{label} returned {ids_of(rows)}, expected [{expected_id}]"
        )


def test_elected_reduction_pct_is_the_rounded_tier_product(api):
    """The pinned reduction_pct is the shortfall times its tier multiplier, rounded once.

    PRD: "The shortfall is multiplied by the tier multiplier and that product is rounded half up to two decimal places; then, if any named anchor requirement of the breached condition is unsatisfied under the controlling figures — the named anchor not counted open and no qualifying substitute available — a flat 10.00 percentage points is added on top."

    Design: Corner/endpoints/remaining_collection_reads_return_only_the_filtered_row
    """
    built = _collections_scenario(api)
    election = built["election"]

    # Required 81.67 against a controlling 75.00 leaves a 6.67 point shortfall,
    # which sits in the 1.5 tier: 6.67 * 1.5 = 10.005, rounded half up to 10.01.
    assert_pct(
        election["shortfall_pct_at_election"], 6.67, "shortfall_pct_at_election"
    )
    assert election["anchor_bonus_applied"] is False
    assert_pct(election["reduction_pct"], 10.01, "reduction_pct")


def test_draft_strict_measurement_leaves_the_dark_lease_out_of_the_numerator(api):
    """A SNAPSHOT_STRICT measurement counts only the open premises, so it reports 75.00.

    PRD: "Under the **`SNAPSHOT_STRICT`** variant, a lease counts open only when its `premises_status` is `OPEN` **and** its tenant's `status` is `ACTIVE`."

    Design: Corner/endpoints/remaining_collection_reads_return_only_the_filtered_row
    """
    built = _collections_scenario(api)

    measurement = fetch_measurement(api, built["measurement"]["id"])

    assert measurement["variant"] == "SNAPSHOT_STRICT"
    assert measurement["status"] == "DRAFT"
    assert measurement["total_gla_sqft"] == 300000
    # 255,000 counted less the 30,000 sqft dark suite.
    assert measurement["occupied_gla_sqft"] == 225000
    assert_pct(measurement["gla_occupancy_pct"], 75.00, "gla_occupancy_pct")


def test_expansion_plan_that_impacts_nothing_needs_no_consent(api):
    """A plan whose impact counts are both zero is created without a consent requirement.

    PRD: "`consent_required` is true when either count is greater than zero."

    Design: Corner/endpoints/remaining_collection_reads_return_only_the_filtered_row
    """
    built = _collections_scenario(api)

    plan = built["plan"]
    assert plan["impacted_clause_count"] == 0
    assert plan["impacted_condition_count"] == 0
    assert plan["consent_required"] is False
    # An EXPANSION removes no area, so the post-plan denominator is unchanged.
    assert plan["gla_after_sqft"] == 300000
