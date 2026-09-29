"""Corner coverage for cross-cutting layers (OCC, cascades, pagination, clock) and read-after-write."""
import pytest

from test_helpers import (
    TEST_USERS,
    award_cycle,
    build_rating_spine,
    create_enrolled_provider,
    create_provider_payload,
    create_reliable_observer,
    create_staff_credential_payload,
    declare_domains,
    documentation_for,
    enter_six_scores,
    finalize_visit,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_provider_headers,
    open_cycle,
    points_map,
    run_expiry_run,
    schedule_visit,
    set_clock,
    setup_open_grant,
    submit_expenditure,
    submit_self_assessment,
    validate_error,
    validate_paginated,
    validate_success,
    verification_approve_payload,
)

ADMIN = TEST_USERS["admin_headers"]

TIER_ONE_POINTS = points_map(learning=12, staff=8)


# --- cross-cutting layers ----------------------------------------------------


def test_replayed_grant_version_is_rejected_after_the_first_expenditure_commits(api):
    """PRD §2.5: "Submitting an expenditure against an improvement grant — the `POST
    /improvement-grants/{improvement_grant_id}/expenditures` request — requires a non-optional
    `expected_grant_version` field carrying the client's last observed `version` of the
    targeted grant. A value that does not equal the grant's current `version` is rejected with
    `ERR_STALE_VERSION` and HTTP 412."
    PRD §3.8: "An accepted submission creates the line in `SUBMITTED` with
    `reimbursable_cents` and `disallowed_cents` at 0, adds its amount to `committed_cents`,
    subtracts it from `available_cents`, adds it to that category's entry in
    `category_spend_cents`, and increments the grant's `version` by 1."

    Design: Corner/cross_cutting_layers/occ_expenditure_create_stale_grant_version_rejected_after_first_commit
    """
    ctx, grant = setup_open_grant(awarded_amount_cents=1_000_000)
    provider_id = ctx["provider"]["id"]
    opened = validate_success(api.get_improvement_grant(grant["id"], ADMIN))
    stale_version = opened["version"]

    first = submit_expenditure(
        provider_id, grant["id"], category="EQUIPMENT", amount_cents=400_000,
        invoice_date="2026-09-10", expected_grant_version=stale_version,
    )
    assert first["status"] == "SUBMITTED"
    assert first["reimbursable_cents"] == 0
    assert first["disallowed_cents"] == 0

    validate_error(
        api.create_expenditure(
            grant["id"],
            {
                "category": "PROF_DEV",
                "amount_cents": 100_000,
                "invoice_date": "2026-09-11",
                "expected_grant_version": stale_version,
            },
            make_provider_headers(provider_id),
        ),
        "ERR_STALE_VERSION",
        412,
    )

    after = validate_success(api.get_improvement_grant(grant["id"], ADMIN))
    assert after["version"] == stale_version + 1, (
        f"the accepted line bumped the version once, got {after['version']}"
    )
    assert after["committed_cents"] == 400_000, (
        f"only the first line committed funds, got {after['committed_cents']}"
    )
    assert after["available_cents"] == 600_000, (
        f"availability reflects one commit only, got {after['available_cents']}"
    )
    assert after["category_spend_cents"]["EQUIPMENT"] == 400_000
    assert after["category_spend_cents"]["PROF_DEV"] == 0, (
        "the rejected replay must not touch the professional development category, got "
        f"{after['category_spend_cents']['PROF_DEV']}"
    )
    lines, meta = validate_paginated(
        api.list_grant_expenditures(ADMIN, params={"improvement_grant_id": grant["id"]})
    )
    assert meta["total_count"] == 1, (
        f"the stale replay created no line, got {meta['total_count']}"
    )
    assert lines[0]["id"] == first["id"]


def test_credential_compliance_reconciles_after_create_link_and_expiry(api):
    """PRD §3.2: "The numerator is the sum of the `fte` values of the provider's staff
    credential records that satisfy all four of these conditions at once: the record belongs to
    that provider, its `employment_status` is `ACTIVE`, its `registry_status` is `VERIFIED`, its
    `expires_on` is on or after the logical clock date, and its `credential_level` is at least
    the minimum for its `role_type`."
    PRD §3.2: "Records that are `UNLINKED`, `PENDING`, or `EXPIRED` contribute nothing, and
    `SEPARATED` records are excluded from the numerator but never from the denominator."
    PRD §3.2: "The denominator is always the provider's declared `active_staff_fte`."
    PRD §3.2: "This figure is recomputed on every credential registration, on every registry
    write, on approval of an enrollment application, on every expiry run, on the computed
    compliance read, and immediately before the per-domain points award is computed inside any
    scoring request."

    Design: Corner/cross_cutting_layers/credential_compliance_reconciles_after_create_link_and_expiry
    """
    set_clock("2026-08-03T00:00:00Z")
    provider = create_enrolled_provider(active_staff_fte=2.00)
    provider_id = provider["id"]

    def compliance():
        return validate_success(api.get_provider(provider_id, ADMIN))["credential_compliance_pct"]

    first = validate_success(
        api.create_staff_credential(
            provider_id,
            create_staff_credential_payload(
                staff_registry_id="REG-CC-1", role_type="DIRECTOR",
                credential_level=5, fte=1.00,
            ),
            ADMIN,
        ),
        201,
    )
    assert first["registry_status"] == "UNLINKED"
    assert compliance() == pytest.approx(0.00, abs=0.005), (
        f"an UNLINKED record contributes nothing, got {compliance()}"
    )

    validate_success(
        api.registry_link(
            first["id"],
            {"registry_status": "VERIFIED", "verified_on": "2026-08-03",
             "expires_on": "2030-01-01"},
            ADMIN,
        )
    )
    assert compliance() == pytest.approx(50.00, abs=0.005), (
        f"1.00 qualifying fte over a denominator of 2.00 is 50.00, got {compliance()}"
    )

    second = validate_success(
        api.create_staff_credential(
            provider_id,
            create_staff_credential_payload(
                staff_registry_id="REG-CC-2", role_type="LEAD_TEACHER",
                credential_level=4, fte=1.00,
            ),
            ADMIN,
        ),
        201,
    )
    assert compliance() == pytest.approx(50.00, abs=0.005), (
        f"the second record is still UNLINKED, so nothing moves, got {compliance()}"
    )

    validate_success(
        api.registry_link(
            second["id"],
            {"registry_status": "VERIFIED", "verified_on": "2026-08-03",
             "expires_on": "2030-01-01"},
            ADMIN,
        )
    )
    assert compliance() == pytest.approx(100.00, abs=0.005), (
        f"2.00 qualifying fte over 2.00 is 100.00, got {compliance()}"
    )
    computed = validate_success(api.get_credential_compliance(provider_id, ADMIN))
    assert computed["credential_compliance_pct"] == pytest.approx(100.00, abs=0.005), (
        f"the computed read agrees with the stored figure, got {computed}"
    )

    expired = validate_success(
        api.registry_link(second["id"], {"registry_status": "EXPIRED"}, ADMIN)
    )
    assert expired["registry_status"] == "EXPIRED"
    assert compliance() == pytest.approx(50.00, abs=0.005), (
        f"an EXPIRED record contributes nothing again, got {compliance()}"
    )
    rows, meta = validate_paginated(
        api.list_staff_credentials(
            ADMIN, params={"provider_id": provider_id, "registry_status": "VERIFIED"}
        )
    )
    assert meta["total_count"] == 1, (
        f"only the director record is still VERIFIED, got {meta['total_count']}"
    )
    assert rows[0]["id"] == first["id"]


def test_provider_listing_pagination_and_filters_stay_consistent_under_mutation(api):
    """PRD §2.3: "Unless a specific endpoint states otherwise, list results are ordered by
    `created_at` ascending. The `meta` object of a list response carries `limit` (the effective
    page size), `offset` (the effective starting position), `total_count` (the number of records
    matching the filters before pagination), and `has_more` (true when records remain beyond
    the current page)."
    PRD §3.1: "Providers may be listed and filtered by `status`, by `county_code`, or by
    `current_rating_cycle_id`."
    PRD §2.10: "Cascades run to completion inside the request that triggers them; the system
    offers no eventual consistency and no deferred settlement."

    Design: Corner/cross_cutting_layers/provider_list_pagination_and_filter_stay_consistent_under_mutation
    """
    set_clock("2026-08-03T00:00:00Z")
    first = create_enrolled_provider(legal_name="Alpha Center", county_code="DANE")
    second = create_enrolled_provider(legal_name="Bravo Center", county_code="DANE")
    applied = validate_success(
        api.create_provider(
            create_provider_payload(legal_name="Charlie Center", county_code="IOWA"), ADMIN
        ),
        201,
    )

    page_one, meta_one = validate_paginated(
        api.list_providers(ADMIN, params={"status": "ENROLLED", "limit": 1, "offset": 0})
    )
    assert meta_one["total_count"] == 2, (
        f"two providers are ENROLLED, got {meta_one['total_count']}"
    )
    assert meta_one["has_more"] is True, "one enrolled provider remains beyond page one"
    assert len(page_one) == 1, f"limit 1 returns one row, got {len(page_one)}"

    page_two, meta_two = validate_paginated(
        api.list_providers(ADMIN, params={"status": "ENROLLED", "limit": 1, "offset": 1})
    )
    assert meta_two["total_count"] == 2, (
        f"total_count counts matches before pagination, got {meta_two['total_count']}"
    )
    assert meta_two["has_more"] is False, "no enrolled provider remains beyond page two"
    assert len(page_two) == 1
    assert {row["id"] for row in page_one} | {row["id"] for row in page_two} == {
        first["id"], second["id"]
    }, "the two pages must partition the ENROLLED set exactly"

    applied_rows, applied_meta = validate_paginated(
        api.list_providers(ADMIN, params={"status": "APPLIED"})
    )
    assert applied_meta["total_count"] == 1, (
        f"the third provider is the only APPLIED one, got {applied_meta['total_count']}"
    )
    assert applied_rows[0]["id"] == applied["id"]

    fourth = create_enrolled_provider(legal_name="Delta Center", county_code="DANE")
    tail, tail_meta = validate_paginated(
        api.list_providers(ADMIN, params={"status": "ENROLLED", "limit": 2, "offset": 2})
    )
    assert tail_meta["total_count"] == 3, (
        f"the new approval is visible in the same breath, got {tail_meta['total_count']}"
    )
    assert tail_meta["has_more"] is False
    assert len(tail) == 1, f"one row remains past offset 2, got {len(tail)}"
    assert tail[0]["id"] in {first["id"], second["id"], fourth["id"]}

    _, county_meta = validate_paginated(
        api.list_providers(ADMIN, params={"county_code": "DANE"})
    )
    assert county_meta["total_count"] == 3, (
        f"three providers sit in DANE, got {county_meta['total_count']}"
    )


def test_expiry_run_activates_the_award_only_once_the_effective_date_has_arrived(api):
    """PRD §3.5: "Whether the award takes effect immediately depends on the calendar. When the
    computed `effective_date` is already at or before the logical clock date, the cycle
    continues `AWARDED → ACTIVE` inside the same request; otherwise it waits, and the next
    expiry run occurring on or after the effective date promotes it."
    PRD §3.5: "The provider's `current_rating_cycle_id` and `current_tier` are repointed at the
    new cycle, which is also what carries a first-time provider from `ENROLLED` to `ACTIVE`."
    PRD §3.5: "`validity_months` is 36 when `awarded_tier` is at least 4 and 24 otherwise."
    PRD §3.5: "`rerating_window_opens_on` is the expiry date minus 90 calendar days at midnight
    UTC — the earliest date on which a re-rating cycle may be opened."

    Design: Corner/cross_cutting_layers/expiry_run_activates_the_award_only_on_the_effective_date
    """
    ctx = build_rating_spine(
        stop_at="AWARDED",
        claimed=TIER_ONE_POINTS,
        verified=TIER_ONE_POINTS,
        award_clock="2026-08-11T00:00:00Z",
    )
    cycle_id = ctx["cycle"]["id"]
    provider_id = ctx["provider"]["id"]
    assert ctx["cycle"]["effective_date"] == "2026-09-01T00:00:00.000Z", (
        f"a 2026-08-11 award takes effect on 2026-09-01, got {ctx['cycle']['effective_date']}"
    )

    set_clock("2026-08-31T23:59:59Z")
    run_expiry_run()
    waiting = validate_success(api.get_rating_cycle(cycle_id, ADMIN))
    assert waiting["status"] == "AWARDED", (
        f"a run before the effective date promotes nothing, got {waiting['status']}"
    )
    still_enrolled = validate_success(api.get_provider(provider_id, ADMIN))
    assert still_enrolled["status"] == "ENROLLED", (
        f"the provider is not ACTIVE yet, got {still_enrolled['status']}"
    )
    assert still_enrolled["current_tier"] is None
    assert still_enrolled["current_rating_cycle_id"] is None

    set_clock("2026-09-01T00:00:00Z")
    run_expiry_run()
    promoted = validate_success(api.get_rating_cycle(cycle_id, ADMIN))
    assert promoted["status"] == "ACTIVE", (
        f"the first run on or after the effective date promotes the cycle, got {promoted['status']}"
    )
    assert promoted["validity_months"] == 24, (
        f"tier 1 carries 24 months of validity, got {promoted['validity_months']}"
    )
    assert promoted["expires_on"] == "2028-08-31T23:59:59.999Z", (
        f"24 months from 2026-09-01 less one day is 2028-08-31, got {promoted['expires_on']}"
    )
    assert promoted["rerating_window_opens_on"] == "2028-06-02T00:00:00.000Z", (
        f"2028-08-31 minus 90 days is 2028-06-02, got {promoted['rerating_window_opens_on']}"
    )
    active = validate_success(api.get_provider(provider_id, ADMIN))
    assert active["status"] == "ACTIVE", (
        f"promotion carries the provider ENROLLED -> ACTIVE, got {active['status']}"
    )
    assert active["current_tier"] == 1, (
        f"current_tier is repointed at the new cycle's award, got {active['current_tier']}"
    )
    assert active["current_rating_cycle_id"] == cycle_id
    _, meta = validate_paginated(api.list_rating_cycles(ADMIN, params={"status": "ACTIVE"}))
    assert meta["total_count"] == 1, (
        f"exactly one cycle is ACTIVE, got {meta['total_count']}"
    )


def test_provisional_preview_and_final_award_diverge_on_the_same_cycle(api):
    """PRD §3.5: "Both stages exist in a **provisional** and a **final** variant, and the same
    stored data can legitimately produce a higher tier under the provisional variant than under
    the final one."
    PRD §3.5: "Under the final variant that number is the verified value the state confirmed
    for that domain code; under the provisional variant it is the value the provider claimed."
    PRD §3.5: "That fraction is 1.00 when the composite is at least 6.00, 0.80 when it is at
    least 5.00, 0.60 when it is at least 4.00, 0.40 when it is at least 3.00, and 0.20
    otherwise."
    PRD §3.3: "The preview accepts an optional `variant` naming either the provisional or the
    final scoring run, defaults to the provisional run, persists nothing at all, and returns a
    cycle representation carrying that variant's `weighted_total`, `block_clearance`,
    `highest_block_cleared`, `points_tier`, and `awarded_tier` as a projection rather than as
    stored state."

    Design: Corner/cross_cutting_layers/provisional_preview_and_final_award_diverge_on_the_same_cycle
    """
    claimed = points_map(learning=20, staff=20)
    ctx = build_rating_spine(
        stop_at="DOCS_VERIFIED", claimed=claimed, verified=TIER_ONE_POINTS
    )
    cycle_id = ctx["cycle"]["id"]

    preview = validate_success(
        api.get_score_preview(cycle_id, ADMIN, params={"variant": "PROVISIONAL"})
    )
    assert preview["weighted_total"] == pytest.approx(50.00, abs=0.005), (
        f"the claimed 20/20 pair weighs 50.00 provisionally, got {preview['weighted_total']}"
    )
    assert preview["points_tier"] == 2, (
        f"50.00 lands in the tier-2 band, got {preview['points_tier']}"
    )
    assert preview["highest_block_cleared"] == 1, (
        f"blocks two and three carry no claimed points, got {preview['highest_block_cleared']}"
    )
    clearance = preview["block_clearance"]
    assert clearance.get("1", clearance.get(1)) == "CLEARED"
    assert clearance.get("2", clearance.get(2)) == "NOT_CLEARED"
    assert clearance.get("3", clearance.get(3)) == "NOT_CLEARED"
    assert preview["awarded_tier"] == 2, (
        f"the block-one ceiling is tier 2, got {preview['awarded_tier']}"
    )

    lead = create_reliable_observer("Lead Observer One")
    visit = schedule_visit(cycle_id, lead["id"], "2026-08-06T09:00:00Z", "2026-08-06T13:00:00Z")
    set_clock("2026-08-06T09:00:00Z")
    enter_six_scores(visit["id"], lead["id"], 4.0)
    finalize_visit(visit["id"])
    set_clock("2026-08-11T00:00:00Z")
    awarded = award_cycle(cycle_id, "FINAL")

    assert awarded["score_variant"] == "FINAL"
    assert awarded["observation_composite"] == pytest.approx(4.00, abs=0.005), (
        f"six raw scores of 4.0 average to 4.00, got {awarded['observation_composite']}"
    )
    assert awarded["reliability_pct"] is None, (
        "the single-observer branch leaves the cycle's reliability_pct null, got "
        f"{awarded['reliability_pct']}"
    )
    assert awarded["domain_points"]["LEARNING_ENVIRONMENT"] == 12, (
        "a composite of 4.00 buys 0.60 of the 20-point ceiling, got "
        f"{awarded['domain_points']['LEARNING_ENVIRONMENT']}"
    )
    assert awarded["domain_points"]["STAFF_QUALIFICATIONS"] == 8, (
        "the final variant credits the verified 8, not the claimed 20, got "
        f"{awarded['domain_points']['STAFF_QUALIFICATIONS']}"
    )
    assert awarded["weighted_total"] == pytest.approx(26.00, abs=0.005), (
        f"the final run weighs 26.00 against the provisional 50.00, got "
        f"{awarded['weighted_total']}"
    )
    assert awarded["points_tier"] == 1
    assert awarded["awarded_tier"] == 1, (
        f"the final award is tier 1 where the preview projected tier 2, got "
        f"{awarded['awarded_tier']}"
    )
    assert awarded["highest_block_cleared"] == 1
    assert preview["awarded_tier"] > awarded["awarded_tier"], (
        "the same stored rows must produce a higher provisional tier than final tier"
    )
    self_assessment = validate_success(
        api.get_self_assessment(ctx["self_assessment"]["id"], ADMIN)
    )
    assert self_assessment["claimed_points"]["LEARNING_ENVIRONMENT"] == 20, (
        "the award never rewrites what the provider claimed, got "
        f"{self_assessment['claimed_points']['LEARNING_ENVIRONMENT']}"
    )
    assert self_assessment["verified_points"]["LEARNING_ENVIRONMENT"] == 12


# --- consistency model -------------------------------------------------------


def test_create_response_and_immediate_read_agree_with_no_lag(api):
    """PRD §3.1: "A newly registered provider begins in `APPLIED` with
    `credential_compliance_pct` at 0, `reimbursement_adjustment_cents` at 0,
    `public_listing_visible` false, `enrolled_on`, `current_rating_cycle_id` and `current_tier`
    all null, and `version` 1."
    PRD §3.1: "An optional `weekly_onsite_cap_hours` value, greater than zero with one decimal
    place, sets how many on-site coaching hours the site is willing to host in any ISO calendar
    week and defaults to 12 when omitted."
    PRD §2.4: "Every persisted resource carries a server-minted `id`, which is a UUID string
    with no type prefix of any kind, and a `created_at` timestamp in ISO 8601 UTC format with
    exactly three fractional digits."
    PRD §2.10: "Cascades run to completion inside the request that triggers them; the system
    offers no eventual consistency and no deferred settlement."

    Design: Corner/consistency_model/create_response_and_immediate_read_agree_with_no_lag
    """
    set_clock("2026-08-03T00:00:00Z")
    created = validate_success(
        api.create_provider(
            create_provider_payload(legal_name="Readback Center", county_code="DANE"), ADMIN
        ),
        201,
    )
    assert is_valid_uuid(created["id"]), f"id must be a bare UUID, got {created['id']}"
    assert is_iso8601_timestamp(created["created_at"])
    assert created["status"] == "APPLIED", (
        f"a newly registered provider begins in APPLIED, got {created['status']}"
    )
    assert created["version"] == 1, f"version begins at 1, got {created['version']}"
    assert created["credential_compliance_pct"] == pytest.approx(0.00, abs=0.005)
    assert created["reimbursement_adjustment_cents"] == 0
    assert created["public_listing_visible"] is False
    assert created["enrolled_on"] is None
    assert created["current_rating_cycle_id"] is None
    assert created["current_tier"] is None
    assert float(created["weekly_onsite_cap_hours"]) == pytest.approx(12.0, abs=0.05), (
        f"weekly_onsite_cap_hours defaults to 12 when omitted, got "
        f"{created['weekly_onsite_cap_hours']}"
    )

    read = validate_success(api.get_provider(created["id"], ADMIN))
    assert read["id"] == created["id"]
    assert read["status"] == "APPLIED", (
        f"the immediate read agrees with the create response, got {read['status']}"
    )
    assert read["version"] == 1
    assert read["created_at"] == created["created_at"], (
        f"created_at must not drift between the write and the read, got {read['created_at']}"
    )
    assert read["updated_at"] == created["updated_at"]
    assert read["credential_compliance_pct"] == pytest.approx(0.00, abs=0.005)
    assert read["public_listing_visible"] is False
    assert read["current_tier"] is None

    rows, meta = validate_paginated(api.list_providers(ADMIN, params={"status": "APPLIED"}))
    assert meta["total_count"] == 1, (
        f"the row is immediately listable with no settlement lag, got {meta['total_count']}"
    )
    assert rows[0]["id"] == created["id"]


def test_verification_decision_is_visible_across_entities_in_the_same_response(api):
    """PRD §3.3: "On approval the self-assessment moves to `VERIFIED`, `verified_on` is stamped
    from the logical clock, the cycle advances `SELF_ASSESSMENT_SUBMITTED → DOCS_VERIFIED`, and
    the cycle's `domain_points` map is provisionally recomputed under the provisional scoring
    variant described in §3.5."
    PRD §3.3: "The created self-assessment starts in `SUBMITTED` with `return_count` at 0,
    `verified_points` null, `verified_on` null, and `documented_domains` derived as the set of
    distinct domain codes appearing at least once in the evidence array."
    PRD §2.10: "Cascades run to completion inside the request that triggers them; the system
    offers no eventual consistency and no deferred settlement."

    Design: Corner/consistency_model/verification_decision_is_visible_across_entities_in_the_same_response
    """
    set_clock("2026-08-03T00:00:00Z")
    declare_domains()
    provider = create_enrolled_provider()
    provider_id = provider["id"]
    set_clock("2026-08-05T00:00:00Z")
    cycle = open_cycle(provider_id)
    submitted = submit_self_assessment(
        provider_id,
        cycle["id"],
        claimed=TIER_ONE_POINTS,
        documentation=documentation_for(["LEARNING_ENVIRONMENT", "STAFF_QUALIFICATIONS"]),
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["return_count"] == 0
    assert submitted["verified_points"] is None
    assert submitted["verified_on"] is None
    assert set(submitted["documented_domains"]) == {
        "LEARNING_ENVIRONMENT", "STAFF_QUALIFICATIONS"
    }, (
        "documented_domains is the distinct set of evidenced domain codes, got "
        f"{submitted['documented_domains']}"
    )

    decided = validate_success(
        api.decide_verification(
            submitted["id"], verification_approve_payload(verified=TIER_ONE_POINTS), ADMIN
        )
    )
    assert decided["status"] == "VERIFIED", (
        f"approval moves the self-assessment to VERIFIED, got {decided['status']}"
    )
    assert decided["verified_on"] is not None, "verified_on is stamped from the logical clock"
    assert decided["verified_points"]["LEARNING_ENVIRONMENT"] == 12
    assert decided["verified_points"]["STAFF_QUALIFICATIONS"] == 8
    assert decided["verified_points"]["FAMILY_PARTNERSHIP"] == 0
    assert decided["return_count"] == 0

    cycle_read = validate_success(api.get_rating_cycle(cycle["id"], ADMIN))
    assert cycle_read["status"] == "DOCS_VERIFIED", (
        "the same request that verified the documentation advanced the cycle, got "
        f"{cycle_read['status']}"
    )
    assert cycle_read["observation_composite"] is None
    assert cycle_read["awarded_tier"] is None

    provider_view = validate_success(
        api.get_self_assessment(submitted["id"], make_provider_headers(provider_id))
    )
    assert provider_view["status"] == "VERIFIED", (
        f"the provider sees the same decision immediately, got {provider_view['status']}"
    )
    assert provider_view["verified_points"]["LEARNING_ENVIRONMENT"] == 12
    assert provider_view["verified_points"]["STAFF_QUALIFICATIONS"] == 8

    rows, meta = validate_paginated(
        api.list_self_assessments(
            ADMIN, params={"rating_cycle_id": cycle["id"], "status": "VERIFIED"}
        )
    )
    assert meta["total_count"] == 1, (
        f"the verified row is immediately listable, got {meta['total_count']}"
    )
    assert rows[0]["id"] == submitted["id"]
