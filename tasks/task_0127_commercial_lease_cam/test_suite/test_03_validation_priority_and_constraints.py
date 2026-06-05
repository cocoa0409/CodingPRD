"""Validation-priority conflicts, boundary precision, cross-entity state
dependencies, and temporal-overlap conflicts (depth queue A).
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_example_b_posted, setup_minimal_reconciliation, setup_lease_with_sales,
    create_property, create_tenant, create_active_lease, create_lease, create_pool,
    add_line_item, create_reconciliation, create_in_review_reconciliation,
    post_reconciliation, get_reconciliation_version, submit_reconciliation,
    make_property_manager_headers, make_accountant_headers,
    PM_HEADERS, ACCT_HEADERS, ACCT_ID,
)


# ─── Rule 5: priority_pair / state_beats_pool_locked_on_post ───────────────

def test_draft_recon_on_locked_pool_returns_invalid_state(api):
    """PRD §2.9: "After a well-formed, authorized request reaches the resource, the
    state guard fires if the target is not in a state that permits the transition
    (ERR_INVALID_STATE), and on the reconciliation post the optimistic-concurrency
    check (ERR_STALE_VERSION) follows. Business-rule checks specific to each
    operation — year match, pool-lock, denominator, capacity, duplicate period,
    percentage-rent-already-run, TI allowance, estoppel balance, and dispute-note
    presence — are evaluated after the structural checks above."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_pool_locked_on_post
    """
    # Pool locked by anchor lease's posted recon; subject recon left DRAFT.
    ctx = setup_example_b_posted()
    pool_id = ctx["pool"]["id"]
    subj_lease = ctx["subject_lease"]["id"]
    # A new (DRAFT) reconciliation against the same now-LOCKED pool, never submitted.
    # subject lease already has a POSTED recon for 2025, so use the anchor lease
    # for a fresh DRAFT recon on the locked pool.
    anchor_lease = ctx["anchor_lease"]["id"]
    recon_b = create_reconciliation(anchor_lease, pool_id, 2025)
    version = get_reconciliation_version(recon_b["id"])
    res = api.post_reconciliation(
        recon_b["id"], {"expected_reconciliation_version": version},
        make_accountant_headers("acct-009"))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    recon_after = validate_success(api.get_reconciliation(recon_b["id"], ACCT_HEADERS), 200)
    assert recon_after["status"] == "DRAFT"


def test_draft_state_check_precedes_pool_lock_check(api):
    """PRD §2.9: "the state guard fires if the target is not in a state that permits
    the transition (ERR_INVALID_STATE) ... Business-rule checks specific to each
    operation — year match, pool-lock, denominator ... are evaluated after the
    structural checks above."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_pool_locked_on_post
    """
    ctx = setup_example_b_posted()
    pool_id = ctx["pool"]["id"]
    anchor_lease = ctx["anchor_lease"]["id"]
    recon_b = create_reconciliation(anchor_lease, pool_id, 2025)
    version = get_reconciliation_version(recon_b["id"])
    # DRAFT (state) + pool LOCKED (business): the state error wins.
    res = api.post_reconciliation(
        recon_b["id"], {"expected_reconciliation_version": version},
        make_accountant_headers("acct-010"))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Rule 5: priority_pair / segregation_beats_invalid_state_on_post ───────

def test_same_user_draft_post_returns_segregation_of_duties(api):
    """PRD §2.8: "the Accountant who posts a reconciliation must not be the same
    X-User-ID that submitted it. A post by the submitting user, even if that user
    legitimately holds the Accountant role, is rejected with
    ERR_SEGREGATION_OF_DUTIES."
    PRD §2.9: "for the two tenant-restricted actions, lease ownership
    (ERR_NOT_LEASE_OWNER), then — on the reconciliation post specifically — the
    segregation-of-duties guard (ERR_SEGREGATION_OF_DUTIES)."

    Design: Difficulty/priority_pair_validation_conflict/segregation_beats_invalid_state_on_post
    """
    # Recon left in DRAFT (returned), posted by the same id that submitted it.
    prop = create_property(total_rentable_sqft=10000, name="SegProp")
    tenant = create_tenant("SegTen", "sg@x.com")
    lease = create_active_lease(prop["id"], tenant["id"], leased_sqft=2500,
                                base_rent_cents_annual=0, estimated_cam_cents_monthly=15000)
    pool = create_pool(prop["id"], pool_year=2025, admin_fee_pct=0)
    add_line_item(pool["id"], "UTILITIES", 800000, "RECOVERABLE", is_variable=False)
    shared_pm = make_property_manager_headers("shared-user-9")
    recon = get_success_data(api.create_reconciliation(
        {"lease_id": lease["id"], "pool_id": pool["id"], "recon_year": 2025}, shared_pm))
    get_success_data(api.submit_reconciliation(recon["id"], shared_pm))
    returned = get_success_data(api.return_reconciliation(
        recon["id"], make_accountant_headers("acct-009")))
    # Now DRAFT (not IN_REVIEW) AND poster == submitter id: segregation wins.
    res = api.post_reconciliation(
        recon["id"], {"expected_reconciliation_version": returned["version"]},
        make_accountant_headers("shared-user-9"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)
    recon_after = validate_success(api.get_reconciliation(recon["id"], ACCT_HEADERS), 200)
    assert recon_after["status"] == "DRAFT"


def test_segregation_check_precedes_state_check_on_post(api):
    """PRD §2.8: "A post by the submitting user, even if that user legitimately
    holds the Accountant role, is rejected with ERR_SEGREGATION_OF_DUTIES."

    Design: Difficulty/priority_pair_validation_conflict/segregation_beats_invalid_state_on_post
    """
    prop = create_property(total_rentable_sqft=10000, name="SegProp2")
    tenant = create_tenant("SegTen2", "sg2@x.com")
    lease = create_active_lease(prop["id"], tenant["id"], leased_sqft=2500,
                                base_rent_cents_annual=0, estimated_cam_cents_monthly=15000)
    pool = create_pool(prop["id"], pool_year=2025, admin_fee_pct=0)
    add_line_item(pool["id"], "UTILITIES", 800000, "RECOVERABLE", is_variable=False)
    shared_pm = make_property_manager_headers("shared-user-7")
    recon = get_success_data(api.create_reconciliation(
        {"lease_id": lease["id"], "pool_id": pool["id"], "recon_year": 2025}, shared_pm))
    get_success_data(api.submit_reconciliation(recon["id"], shared_pm))
    returned = get_success_data(api.return_reconciliation(
        recon["id"], make_accountant_headers("acct-008")))
    res = api.post_reconciliation(
        recon["id"], {"expected_reconciliation_version": returned["version"]},
        make_accountant_headers("shared-user-7"))
    # DRAFT state would give ERR_INVALID_STATE, but segregation (higher priority) wins.
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)


# ─── Rule 6: boundary_precision / percentage_rent_at_breakpoint_yields_zero ─

def test_percentage_rent_at_breakpoint_yields_zero(api):
    """PRD §3.5: "The breakpoint boundary is strict: only sales that exceed the
    breakpoint accrue rent, so sales exactly equal to the breakpoint produce zero
    excess and zero percentage rent."

    Design: Difficulty/boundary_precision_check/percentage_rent_at_breakpoint_yields_zero
    """
    prop, tenant, lease, sr = setup_lease_with_sales(
        pct_rent_rate=0.06, pct_rent_breakpoint_cents=3000000,
        gross_sales_cents=3000000, period_year=2025)
    validate_success(api.run_percentage_rent(lease["id"], {"period_year": 2025}, PM_HEADERS), 200)
    after = validate_success(api.get_lease(lease["id"], PM_HEADERS), 200)
    assert after["outstanding_balance_cents"] == 0


def test_percentage_rent_one_cent_above_breakpoint_charges(api):
    """PRD §3.5: "The excess is the report's gross_sales_cents minus the lease's
    pct_rent_breakpoint_cents, and if that difference is negative the excess is
    zero. The percentage-rent charge is that excess multiplied by the lease's
    pct_rent_rate, rounded half-up to whole cents."

    Design: Difficulty/boundary_precision_check/percentage_rent_at_breakpoint_yields_zero
    """
    # Just above the breakpoint: excess 100 -> charge round_half_up(100*0.06)=6.
    prop, tenant, lease, sr = setup_lease_with_sales(
        pct_rent_rate=0.06, pct_rent_breakpoint_cents=3000000,
        gross_sales_cents=3000100, period_year=2025)
    validate_success(api.run_percentage_rent(lease["id"], {"period_year": 2025}, PM_HEADERS), 200)
    after = validate_success(api.get_lease(lease["id"], PM_HEADERS), 200)
    assert after["outstanding_balance_cents"] == 6


# ─── Rule 6: boundary_precision / empty_denominator_zero_occupancy ─────────

def test_empty_denominator_on_preview_zero_occupancy(api):
    """PRD §3.7: "if the selected denominator (total_rentable_sqft or occupied_sqft
    per the pool's pro_rata_denominator) is zero, the share is undefined and the
    post is rejected with ERR_EMPTY_DENOMINATOR; the same denominator guard
    protects the read-only preview."

    Design: Difficulty/boundary_precision_check/empty_denominator_zero_occupancy_on_preview
    """
    empty_prop = create_property(total_rentable_sqft=10000, name="EmptyProp")
    host_prop = create_property(total_rentable_sqft=10000, name="HostProp")
    tenant = create_tenant("DenTen", "d@x.com")
    lease = create_active_lease(host_prop["id"], tenant["id"], leased_sqft=2500,
                                base_rent_cents_annual=0, estimated_cam_cents_monthly=15000)
    pool = create_pool(empty_prop["id"], pool_year=2025,
                       pro_rata_denominator="OCCUPIED", admin_fee_pct=0)
    add_line_item(pool["id"], "UTILITIES", 800000, "RECOVERABLE", is_variable=False)
    recon = create_reconciliation(lease["id"], pool["id"], 2025)
    res = api.preview_reconciliation(recon["id"], ACCT_HEADERS)
    validate_error(res, "ERR_EMPTY_DENOMINATOR", expected_status=422)


def test_empty_denominator_blocks_post_zero_occupancy(api):
    """PRD §3.7: "Choosing OCCUPIED yields a smaller denominator and therefore a
    larger share; a zero occupancy under that basis raises ERR_EMPTY_DENOMINATOR."

    Design: Difficulty/boundary_precision_check/empty_denominator_zero_occupancy_on_preview
    """
    empty_prop = create_property(total_rentable_sqft=10000, name="EmptyProp2")
    host_prop = create_property(total_rentable_sqft=10000, name="HostProp2")
    tenant = create_tenant("DenTen2", "d2@x.com")
    lease = create_active_lease(host_prop["id"], tenant["id"], leased_sqft=2500,
                                base_rent_cents_annual=0, estimated_cam_cents_monthly=15000)
    pool = create_pool(empty_prop["id"], pool_year=2025,
                       pro_rata_denominator="OCCUPIED", admin_fee_pct=0)
    add_line_item(pool["id"], "UTILITIES", 800000, "RECOVERABLE", is_variable=False)
    recon = create_in_review_reconciliation(lease["id"], pool["id"], 2025)
    res = api.post_reconciliation(
        recon["id"], {"expected_reconciliation_version": recon["version"]}, ACCT_HEADERS)
    validate_error(res, "ERR_EMPTY_DENOMINATOR", expected_status=422)


# ─── Rule 7: cross_entity_state_dependency / recon_post_requires_pool_open ─

def test_post_on_locked_pool_from_in_review_returns_pool_locked(api):
    """PRD §3.7: "The referenced pool must still be OPEN; a pool already locked by
    another reconciliation yields ERR_POOL_LOCKED."

    Design: Difficulty/cross_entity_state_dependency/recon_post_requires_pool_open
    """
    prop = create_property(total_rentable_sqft=10000, gross_up_occupancy_pct=0.95, name="X7Prop")
    ta = create_tenant("A7", "a7@x.com")
    tb = create_tenant("B7", "b7@x.com")
    lease_a = create_active_lease(prop["id"], ta["id"], leased_sqft=4000,
                                  base_rent_cents_annual=0, estimated_cam_cents_monthly=1000)
    lease_b = create_active_lease(prop["id"], tb["id"], leased_sqft=5500,
                                  base_rent_cents_annual=0, estimated_cam_cents_monthly=1000)
    pool = create_pool(prop["id"], pool_year=2025,
                       pro_rata_denominator="TOTAL_RENTABLE", admin_fee_pct=0)
    add_line_item(pool["id"], "UTILITIES", 800000, "RECOVERABLE", is_variable=False)
    # First recon posts and locks the pool.
    recon_a = create_in_review_reconciliation(lease_a["id"], pool["id"], 2025)
    post_reconciliation(recon_a["id"], recon_a["version"], "acct-001")
    # Second recon, driven to IN_REVIEW, posts against the now-LOCKED pool.
    recon_b = create_in_review_reconciliation(lease_b["id"], pool["id"], 2025)
    res = api.post_reconciliation(
        recon_b["id"], {"expected_reconciliation_version": recon_b["version"]},
        make_accountant_headers("acct-002"))
    validate_error(res, "ERR_POOL_LOCKED", expected_status=409)
    recon_after = validate_success(api.get_reconciliation(recon_b["id"], ACCT_HEADERS), 200)
    assert recon_after["status"] == "IN_REVIEW"


def test_post_on_open_pool_succeeds_then_blocks_second(api):
    """PRD §3.7: "The referenced pool must still be OPEN; a pool already locked by
    another reconciliation yields ERR_POOL_LOCKED."

    Design: Difficulty/cross_entity_state_dependency/recon_post_requires_pool_open
    """
    prop = create_property(total_rentable_sqft=10000, gross_up_occupancy_pct=0.95, name="X7Prop2")
    ta = create_tenant("A7b", "a7b@x.com")
    tb = create_tenant("B7b", "b7b@x.com")
    lease_a = create_active_lease(prop["id"], ta["id"], leased_sqft=4000,
                                  base_rent_cents_annual=0, estimated_cam_cents_monthly=1000)
    lease_b = create_active_lease(prop["id"], tb["id"], leased_sqft=5500,
                                  base_rent_cents_annual=0, estimated_cam_cents_monthly=1000)
    pool = create_pool(prop["id"], pool_year=2025,
                       pro_rata_denominator="TOTAL_RENTABLE", admin_fee_pct=0)
    add_line_item(pool["id"], "UTILITIES", 800000, "RECOVERABLE", is_variable=False)
    recon_a = create_in_review_reconciliation(lease_a["id"], pool["id"], 2025)
    posted = post_reconciliation(recon_a["id"], recon_a["version"], "acct-001")
    assert posted["status"] == "POSTED"
    recon_b = create_in_review_reconciliation(lease_b["id"], pool["id"], 2025)
    res = api.post_reconciliation(
        recon_b["id"], {"expected_reconciliation_version": recon_b["version"]},
        make_accountant_headers("acct-002"))
    validate_error(res, "ERR_POOL_LOCKED", expected_status=409)


# ─── Rule 7: cross_entity_state_dependency / lease_terminate_blocked ───────

def test_terminate_blocked_by_in_review_reconciliation(api):
    """PRD §3.3: "Termination advances a lease from ACTIVE or HOLDOVER to
    TERMINATED. It is blocked while any reconciliation for that lease is still open
    — that is, in DRAFT, IN_REVIEW, or DISPUTED — so a tenancy cannot be closed out
    with an unresolved reconciliation pending."

    Design: Difficulty/cross_entity_state_dependency/lease_terminate_blocked_by_open_reconciliation
    """
    prop = create_property(total_rentable_sqft=10000, name="TermProp")
    tenant = create_tenant("TermTen", "t@x.com")
    lease = create_active_lease(prop["id"], tenant["id"], leased_sqft=2500,
                                base_rent_cents_annual=0, estimated_cam_cents_monthly=1000)
    pool = create_pool(prop["id"], pool_year=2025, admin_fee_pct=0)
    add_line_item(pool["id"], "UTILITIES", 800000, "RECOVERABLE", is_variable=False)
    create_in_review_reconciliation(lease["id"], pool["id"], 2025)
    res = api.terminate_lease(lease["id"], PM_HEADERS)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_lease(lease["id"], PM_HEADERS), 200)
    assert after["status"] == "ACTIVE"


def test_terminate_allowed_once_reconciliation_posted(api):
    """PRD §3.3: "It is blocked while any reconciliation for that lease is still
    open — that is, in DRAFT, IN_REVIEW, or DISPUTED"

    Design: Difficulty/cross_entity_state_dependency/lease_terminate_blocked_by_open_reconciliation
    """
    # A POSTED reconciliation is NOT open, so termination is allowed.
    ctx = setup_example_b_posted()
    lease_id = ctx["subject_lease"]["id"]
    terminated = validate_success(api.terminate_lease(lease_id, PM_HEADERS), 200)
    assert terminated["status"] == "TERMINATED"


# ─── Rule 8: resource_temporal_overlap / duplicate_recon_period ────────────

def test_duplicate_recon_period_collides_with_posted_year(api):
    """PRD §3.7: "A second reconciliation for a lease-and-year pair already covered
    by a posted reconciliation is rejected with ERR_DUPLICATE_RECON_PERIOD."

    Design: Difficulty/resource_temporal_overlap/duplicate_recon_period_posted_year_collides
    """
    ctx = setup_example_b_posted()
    subj_lease = ctx["subject_lease"]["id"]
    pool_id = ctx["pool"]["id"]
    res = api.create_reconciliation(
        {"lease_id": subj_lease, "pool_id": pool_id, "recon_year": 2025}, PM_HEADERS)
    validate_error(res, "ERR_DUPLICATE_RECON_PERIOD", expected_status=409)


def test_first_recon_period_creation_succeeds(api):
    """PRD §3.7: "A second reconciliation for a lease-and-year pair already covered
    by a posted reconciliation is rejected with ERR_DUPLICATE_RECON_PERIOD."

    Design: Difficulty/resource_temporal_overlap/duplicate_recon_period_posted_year_collides
    """
    # Before any POSTED recon, the first creation for (lease, 2025) succeeds.
    prop = create_property(total_rentable_sqft=10000, name="DupProp2")
    tenant = create_tenant("DupSubj2", "ds2@x.com")
    lease = create_active_lease(prop["id"], tenant["id"], leased_sqft=2500,
                                base_rent_cents_annual=0, estimated_cam_cents_monthly=15000)
    pool = create_pool(prop["id"], pool_year=2025, admin_fee_pct=0)
    add_line_item(pool["id"], "UTILITIES", 800000, "RECOVERABLE", is_variable=False)
    first = validate_success(api.create_reconciliation(
        {"lease_id": lease["id"], "pool_id": pool["id"], "recon_year": 2025}, PM_HEADERS), 201)
    assert first["status"] == "DRAFT"


# ─── Rule 8: resource_temporal_overlap / percentage_rent_run_already_run ───

def test_percentage_rent_run_twice_collides(api):
    """PRD §3.5: "A second run for a lease-and-year pair that has already been run
    is rejected with ERR_PCT_RENT_ALREADY_RUN."

    Design: Difficulty/resource_temporal_overlap/percentage_rent_run_year_already_run_collides
    """
    prop, tenant, lease, sr = setup_lease_with_sales(
        pct_rent_rate=0.06, pct_rent_breakpoint_cents=3000000,
        gross_sales_cents=5000000, period_year=2025)
    validate_success(api.run_percentage_rent(lease["id"], {"period_year": 2025}, PM_HEADERS), 200)
    res = api.run_percentage_rent(lease["id"], {"period_year": 2025}, PM_HEADERS)
    validate_error(res, "ERR_PCT_RENT_ALREADY_RUN", expected_status=409)
    after = validate_success(api.get_lease(lease["id"], PM_HEADERS), 200)
    assert after["outstanding_balance_cents"] == 120000


def test_first_percentage_rent_run_charges_excess(api):
    """PRD §3.5: "The percentage-rent charge is that excess multiplied by the
    lease's pct_rent_rate, rounded half-up to whole cents."

    Design: Difficulty/resource_temporal_overlap/percentage_rent_run_year_already_run_collides
    """
    # excess 5000000-3000000=2000000 *0.06 = 120000.
    prop, tenant, lease, sr = setup_lease_with_sales(
        pct_rent_rate=0.06, pct_rent_breakpoint_cents=3000000,
        gross_sales_cents=5000000, period_year=2025)
    validate_success(api.run_percentage_rent(lease["id"], {"period_year": 2025}, PM_HEADERS), 200)
    after = validate_success(api.get_lease(lease["id"], PM_HEADERS), 200)
    assert after["outstanding_balance_cents"] == 120000
