"""Optimistic concurrency on shared parents and derived-field reconciliation.

Each test builds its own estate through declared endpoints only: the harness
restarts the service before every test, so the logical clock reads
2026-08-01T00:00:00Z and no rows survive from a previous test.
"""
from test_helpers import (
    ApiErrorId,
    COMPLIANCE_OFFICER,
    LEASING_AGENT,
    PROPERTY_MANAGER,
    assert_line_split,
    assert_money_equals,
    assert_parking_counters,
    assert_project_rollups,
    assert_total_count,
    factories as fac,
    round_money,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


def test_filing_an_appraisal_makes_a_pending_lease_amendment_stale(api):
    """Both writers guard the same lease counter, so a child create invalidates a PATCH.

    PRD §2.4: "`version` is an integer that begins at 1 when the row is created and
    increases by exactly 1 on every mutation, again including cascaded mutations."
    PRD §2.7: "Filing an appraisal against a lease — `POST /leases/{id}/appraisals` —
    requires `expected_lease_version` to equal that lease's current `version`."
    PRD §2.7: "An opinion of value is only meaningful against the rent and term the
    appraiser saw, so if the lease has been amended, attested, certified or touched by a
    cascade since the client read it, the file is rejected with `ERR_STALE_LEASE_VERSION`
    (HTTP 412) and the client must re-read before retrying."
    PRD §2.7: "Amending a lease — `PATCH /leases/{id}` — likewise requires
    `expected_lease_version` to equal the lease's current `version`, and a mismatch is
    rejected with `ERR_STALE_LEASE_VERSION` (HTTP 412)."
    PRD §3.3: "A new lease is created in status `DRAFT` with `fmv_certification_status`
    reading `NOT_STARTED`, `revision_round` at 0 and `version` at 1."
    PRD §3.3: "Changing only `radius_restriction_miles` is non-material: it advances
    `version` and leaves both `status` and `fmv_certification_status` exactly as they
    were."
    PRD §3.4: "The new row begins in `SUBMITTED` with `is_controlling` false,
    `decision_reason` null, and the owning lease's `version` advances by 1 because the
    lease now has new evidence attached to it."

    Design: Corner/complexity_layers/a_sibling_appraisal_invalidates_the_editors_lease_read
    """
    ctx = fx.drafted_lease(
        api,
        tenant_overrides={"is_physician_owned": True},
        lease_overrides={"term_start": "2026-11-01", "term_end": "2029-10-31"})
    lease_id = ctx["lease"]["id"]
    v1 = ctx["lease"]["version"]
    assert v1 == 1, "a new lease is created with version 1, got {}".format(v1)

    # The first amendment succeeds against the version the client actually read.
    amended = validate_success(
        api.patch_lease(lease_id, fac.patch_lease_payload(v1, base_rent_psf_annual=31.00),
                        LEASING_AGENT),
        200)
    v2 = amended["version"]
    assert v2 == 2, "one mutation advances the lease version to 2, got {}".format(v2)
    assert_money_equals(amended["base_rent_psf_annual"], 31.00, "base_rent_psf_annual")

    # Replaying the same version is refused, and the rent is not overwritten.
    validate_error(
        api.patch_lease(lease_id, fac.patch_lease_payload(v1, base_rent_psf_annual=32.00),
                        LEASING_AGENT),
        ApiErrorId.ERR_STALE_LEASE_VERSION)
    assert_money_equals(fx.read_lease(api, lease_id)["base_rent_psf_annual"], 31.00,
                        "base_rent_psf_annual after the refused amendment")

    # An appraisal filed on the same stale read is refused too, and creates no row.
    validate_error(
        api.create_appraisal(lease_id, fac.create_appraisal_payload(v1), COMPLIANCE_OFFICER),
        ApiErrorId.ERR_STALE_LEASE_VERSION)
    _rows, meta = validate_paginated(api.list_lease_appraisals(lease_id, COMPLIANCE_OFFICER))
    assert_total_count(meta, 0)

    # Filed against the current version it lands, and it advances the lease itself.
    appraisal = validate_success(
        api.create_appraisal(lease_id, fac.create_appraisal_payload(v2), COMPLIANCE_OFFICER),
        201)
    assert appraisal["status"] == "SUBMITTED", (
        "a filed appraisal begins in SUBMITTED, got {}".format(appraisal["status"]))
    v3 = fx.read_lease(api, lease_id)["version"]
    assert v3 == 3, (
        "filing an appraisal advances the owning lease to version 3, got {}".format(v3))

    # The editor's read is now stale even though the appraisal touched no field the
    # amendment addresses.
    validate_error(
        api.patch_lease(lease_id, fac.patch_lease_payload(v2, radius_restriction_miles=2.00),
                        LEASING_AGENT),
        ApiErrorId.ERR_STALE_LEASE_VERSION)

    # Re-reading and retrying succeeds; the non-material change advances only the version.
    retried = validate_success(
        api.patch_lease(lease_id, fac.patch_lease_payload(v3, radius_restriction_miles=2.00),
                        LEASING_AGENT),
        200)
    assert retried["version"] == 4, (
        "the successful retry advances the lease to version 4, got {}".format(
            retried["version"]))
    assert float(retried["radius_restriction_miles"]) == 2.00, (
        "the amendment records radius_restriction_miles 2.00, got {}".format(
            retried["radius_restriction_miles"]))
    assert retried["status"] == "DRAFT", (
        "a version conflict is never a state transition, got {}".format(retried["status"]))
    assert retried["fmv_certification_status"] == "NOT_STARTED", (
        "a non-material amendment leaves fmv_certification_status alone, got {}".format(
            retried["fmv_certification_status"]))

    # Exactly one appraisal was ever persisted.
    rows, meta = validate_paginated(api.list_lease_appraisals(lease_id, COMPLIANCE_OFFICER))
    assert_total_count(meta, 1)
    assert rows[0]["id"] == appraisal["id"], "only the accepted appraisal is persisted"


def test_a_revocation_invalidates_a_building_read_taken_before_it(api):
    """The building counter moves under suite creation, occupancy, allocation and revocation.

    PRD §2.7: "Allocating parking stalls — `POST /parking-allocations` — requires
    `expected_building_version` to equal the referenced building's current `version`."
    PRD §2.7: "Stalls are drawn from a pool shared by every lease in the building, and
    that pool moves on every allocation, revocation, lease execution and lease
    termination; a create carrying an older value is rejected with
    `ERR_STALE_BUILDING_VERSION` (HTTP 412)."
    PRD §3.1: "Every new suite begins `VACANT` with `last_vacated_on` null, and adding a
    suite advances the owning building's `version` by 1."
    PRD §3.5: "Because the lease has entered the counted set, the building's
    `anchor_rentable_sf`, `independent_rentable_sf`, `leased_rentable_sf`,
    `vacant_rentable_sf`, `anchor_share_pct` and `tenant_mix_posture` are all recomputed
    and the building's `version` advances by 1."
    PRD §3.5: "On success the suite moves `RESERVED → OCCUPIED` with its `version`
    advanced, the building's tenant mix is recomputed with the building's `version`
    advanced, and the lease's `version` advances."
    PRD §3.9: "The building's three derived counters are then recomputed:
    `staff_allocated_stalls` is the summed `stall_count` of active staff allocations,
    `patient_allocated_stalls` the summed `stall_count` of active patient allocations,
    and `unallocated_stalls` is `total_parking_stalls` less those two sums."
    PRD §3.9: "A `PropertyManager` may revoke an allocation with an optional
    `revocation_note`, which moves it to `REVOKED`, stamps `revoked_on` with the clock
    date, returns the stalls to the pool by recomputing the three counters, and advances
    the building's `version`."

    Design: Corner/complexity_layers/the_building_pool_counter_moves_under_every_writer_not_just_parking
    """
    ctx = fx.active_lease(api)
    building_id = ctx["building"]["id"]
    lease_id = ctx["lease"]["id"]

    v4 = fx.read_building(api, building_id)["version"]
    assert v4 == 4, (
        "registration, the suite, the execution and the commencement each advance the "
        "building once, so it stands at version 4, got {}".format(v4))

    def allocate(expected_version, stall_count=20, category="STAFF"):
        return api.create_parking_allocation(
            fac.create_parking_allocation_payload(expected_version, building_id, lease_id,
                                                 category, stall_count),
            PROPERTY_MANAGER)

    first = validate_success(allocate(v4), 201)
    assert first["status"] == "ACTIVE", (
        "a new allocation is created in ACTIVE, got {}".format(first["status"]))
    building = fx.read_building(api, building_id)
    v5 = building["version"]
    assert v5 == 5, "the first allocation advances the building to version 5, got {}".format(v5)
    assert_parking_counters(building, 20, 0, 380)

    # Replaying the pre-allocation read is refused and moves no stalls.
    validate_error(allocate(v4), ApiErrorId.ERR_STALE_BUILDING_VERSION)
    assert_parking_counters(fx.read_building(api, building_id), 20, 0, 380)

    second = validate_success(allocate(v5), 201)
    building = fx.read_building(api, building_id)
    assert_parking_counters(building, 40, 0, 360)
    assert building["version"] == 6, (
        "the second allocation advances the building to version 6, got {}".format(
            building["version"]))

    # A revocation is a version-bumping write on the same parent.
    revoked = validate_success(
        api.revoke_parking_allocation(first["id"], fac.revoke_allocation_payload(),
                                      PROPERTY_MANAGER),
        200)
    assert revoked["status"] == "REVOKED", (
        "revocation moves the allocation to REVOKED, got {}".format(revoked["status"]))
    building = fx.read_building(api, building_id)
    assert building["version"] == 7, (
        "the revocation advances the building to version 7, got {}".format(
            building["version"]))
    assert_parking_counters(building, 20, 0, 380)

    # The freed stalls would have fitted the request, but the read behind it is stale.
    validate_error(allocate(v5), ApiErrorId.ERR_STALE_BUILDING_VERSION)

    building = fx.read_building(api, building_id)
    assert building["version"] == 7, (
        "a refused allocation advances nothing, got version {}".format(building["version"]))
    assert_parking_counters(building, 20, 0, 380)

    rows, meta = validate_paginated(
        api.list_parking_allocations(PROPERTY_MANAGER,
                                    {"building_id": building_id, "status": "ACTIVE"}))
    assert_total_count(meta, 1)
    assert rows[0]["id"] == second["id"], (
        "only the second allocation is still ACTIVE in the pool")


def test_a_stale_project_read_is_reported_before_the_wrong_project_state(api):
    """A stale line-item append reads 412; only a current read learns the project has moved.

    PRD §2.7: "Appending a construction line item — `POST /ti-projects/{id}/line-items` —
    requires `expected_ti_project_version` to equal the addressed project's current
    `version`."
    PRD §2.7: "A line item consumes a fixed allowance and is cost-shared against the
    project's default landlord share, so a caller who read the project before another
    line item landed, or before the default share was amended, holds a stale value and is
    rejected with `ERR_STALE_TI_PROJECT_VERSION` (HTTP 412)."
    PRD §2.8: "When it does, the response is determined by the **first** breach in the
    ladder below and no later check is evaluated."
    PRD §2.8: "The addressed tenant-improvement project occupies a status from which the
    requested transition is declared — `DESIGN` for a review submission and for appending
    a line item, `IN_REVIEW` for recording a review, `PERMITTED` for starting
    construction, `CONSTRUCTION` for close-out, and `DESIGN`, `IN_REVIEW` or `PERMITTED`
    for cancellation — and the review dimension being addressed is `PENDING`. A violation
    is `ERR_INVALID_TI_STATE` (409)."
    PRD §3.6: "Appending a line also increments `line_item_count` by 1 and advances the
    project's `version` by 1."
    PRD §3.6: "The project's totals are then sums of the **already-rounded** per-line
    figures, taken over the lines in `sequence_no` order: `landlord_committed_amount`
    sums the per-line landlord amounts, `tenant_committed_amount` sums the per-line
    tenant amounts, and `allowance_remaining` is `authorized_allowance_total` less
    `landlord_committed_amount`."
    PRD §3.6: "It then sets **both** `shielding_review_status` and
    `utility_review_status` to `PENDING` in the same transition and advances `version`."

    Design: Corner/complexity_layers/the_stale_project_version_answers_before_the_wrong_project_state
    """
    ctx = fx.drafted_lease(
        api, lease_overrides={"term_start": "2026-11-01", "term_end": "2029-10-31"})
    project = fx.open_ti_project(api, ctx["lease"]["id"], ctx["suite"]["id"])
    project_id = project["id"]
    v1 = project["version"]
    assert v1 == 1, "a new project is created with version 1, got {}".format(v1)

    def append(expected_version, category, cost_amount, description):
        return api.create_ti_line_item(
            project_id,
            fac.create_ti_line_item_payload(expected_version, category=category,
                                            cost_amount=cost_amount,
                                            description=description),
            LEASING_AGENT)

    validate_success(append(v1, "FINISHES", 50000.00, "Procedure room casework"), 201)
    read = fx.read_project(api, project_id)
    v2 = read["version"]
    assert v2 == 2, "the first append advances the project to version 2, got {}".format(v2)
    assert_project_rollups(read, 30000.00, 20000.00, 70000.00, 1)

    # Replaying the pre-append read is refused and appends nothing.
    validate_error(append(v1, "POWER", 50000.00, "Replay of a stale read"),
                   ApiErrorId.ERR_STALE_TI_PROJECT_VERSION)
    assert fx.read_project(api, project_id)["line_item_count"] == 1, (
        "a refused append must not increment line_item_count")

    validate_success(append(v2, "POWER", 50000.00, "Panel upgrade"), 201)
    read = fx.read_project(api, project_id)
    v3 = read["version"]
    assert v3 == 3, "the second append advances the project to version 3, got {}".format(v3)
    assert_project_rollups(read, 60000.00, 40000.00, 40000.00, 2)

    submitted = fx.ti_transition(api, project_id, "SUBMIT_REVIEWS", "Design set complete")
    assert submitted["status"] == "IN_REVIEW", (
        "SUBMIT_REVIEWS moves the project DESIGN -> IN_REVIEW, got {}".format(
            submitted["status"]))
    assert submitted["shielding_review_status"] == "PENDING", (
        "SUBMIT_REVIEWS sets shielding_review_status PENDING, got {}".format(
            submitted["shielding_review_status"]))
    assert submitted["utility_review_status"] == "PENDING", (
        "SUBMIT_REVIEWS sets utility_review_status PENDING, got {}".format(
            submitted["utility_review_status"]))
    v4 = submitted["version"]
    assert v4 == 4, "the review submission advances the project to version 4, got {}".format(v4)

    # The stale read is reported first, so this caller never learns the project has left
    # DESIGN.
    validate_error(append(v3, "PLUMBING", 5000.00, "Late scope with a stale read"),
                   ApiErrorId.ERR_STALE_TI_PROJECT_VERSION)

    # The identical append carrying the current version reports the real reason.
    validate_error(append(v4, "PLUMBING", 5000.00, "Late scope with a current read"),
                   ApiErrorId.ERR_INVALID_TI_STATE)

    rows, meta = validate_paginated(api.list_ti_line_items(project_id, LEASING_AGENT))
    assert_total_count(meta, 2)
    assert [row["sequence_no"] for row in rows] == [1, 2], (
        "no refused append consumed a sequence number, got {}".format(
            [row["sequence_no"] for row in rows]))


def test_cancelling_a_project_zeroes_the_rollups_but_keeps_the_line_items(api):
    """Cancellation resets the money rollups and the amperage while the line items survive.

    PRD §3.6: "Line items are immutable and are never deleted, so the input set only ever
    grows; a project's lines are readable in `sequence_no` order and can be narrowed by
    `category`."
    PRD §3.6: "From the resolved share, `landlord_share_amount` is the line's
    `cost_amount` multiplied by `effective_share_pct`, rounded half up to 2 decimal
    places, and `tenant_share_amount` is the line's `cost_amount` **less** that rounded
    landlord amount."
    PRD §3.6: "Approving the utility dimension requires the suite's
    `power_amps_available` to be at least the project's `power_amps_requested`, refused as
    `ERR_INSUFFICIENT_UTILITY_CAPACITY`, and requires the suite's `medical_gas_available`
    to be true whenever `medical_gas_requested` is true, refused as
    `ERR_SHIELDING_CERTIFICATION_MISSING`; it then sets `utility_review_status` to
    `APPROVED`, reduces the suite's `power_amps_available` by `power_amps_requested`,
    records the amount actually drawn in the project's `power_amps_drawn`, and advances
    the suite's `version`."
    PRD §3.6: "Cancellation applies the same compensation from whichever of `DESIGN`,
    `IN_REVIEW` or `PERMITTED` the project occupied, and the three cancellation routes are
    identical in effect."
    PRD §3.6: "Any drawn electrical capacity is added back to the suite's
    `power_amps_available` and `power_amps_drawn` is reset to 0; if
    `shielding_review_status` reads `APPROVED`, the suite's `shielding_certified` is set
    back to false and its `lead_thickness_mm` to null; the suite's `version` advances."
    PRD §3.6: "On the project itself, `landlord_committed_amount` and
    `tenant_committed_amount` are reset to 0.00 and `allowance_remaining` is restored to
    the full `authorized_allowance_total`, and `version` advances."
    PRD §3.6: "It is the moment the suite legally becomes what it was built to be: the
    suite's `suite_class` is overwritten with the project's `target_suite_class`, and
    where `medical_gas_requested` was true the suite's `medical_gas_available` is set to
    true."

    Design: Corner/complexity_layers/cancelling_a_project_zeroes_the_rollups_but_keeps_the_line_items
    """
    ctx = fx.drafted_lease(
        api, lease_overrides={"term_start": "2026-11-01", "term_end": "2029-10-31"})
    suite_id = ctx["suite"]["id"]
    project = fx.ti_project_in_review(
        api, ctx["lease"]["id"], suite_id,
        line_items=[
            {"category": "FINISHES", "cost_amount": 40000.00,
             "description": "Procedure room casework"},
            {"category": "POWER", "cost_amount": 30000.00,
             "description": "Sub-panel and feeders"},
        ])
    project_id = project["id"]
    fx.ti_review(api, project_id, "UTILITY", "APPROVE")

    before = fx.read_project(api, project_id)
    assert before["status"] == "IN_REVIEW", (
        "one approved dimension leaves the project IN_REVIEW, got {}".format(
            before["status"]))
    assert before["utility_review_status"] == "APPROVED", (
        "the utility dimension reads APPROVED, got {}".format(
            before["utility_review_status"]))
    assert before["shielding_review_status"] == "PENDING", (
        "the shielding dimension is untouched at PENDING, got {}".format(
            before["shielding_review_status"]))
    assert_project_rollups(before, 42000.00, 28000.00, 58000.00, 2)
    assert before["power_amps_drawn"] == 120, (
        "the utility approval records 120 amps drawn, got {}".format(
            before["power_amps_drawn"]))
    suite_before = fx.read_suite(api, suite_id)
    assert suite_before["power_amps_available"] == 80, (
        "the approval reduces the suite from 200 amps to 80, got {}".format(
            suite_before["power_amps_available"]))

    cancelled = fx.ti_transition(api, project_id, "CANCEL", "Tenant withdrew the scope")
    assert cancelled["status"] == "CANCELLED", (
        "CANCEL moves the project to CANCELLED, got {}".format(cancelled["status"]))

    after = fx.read_project(api, project_id)
    assert_project_rollups(after, 0.00, 0.00, 100000.00, 2)
    assert after["power_amps_drawn"] == 0, (
        "cancellation resets power_amps_drawn to 0, got {}".format(after["power_amps_drawn"]))
    suite_after = fx.read_suite(api, suite_id)
    assert suite_after["power_amps_available"] == 200, (
        "the reserved amperage is handed back to the suite, got {}".format(
            suite_after["power_amps_available"]))
    assert suite_after["suite_class"] == "STANDARD_EXAM", (
        "only a close-out reclassifies the suite, got {}".format(
            suite_after["suite_class"]))
    assert suite_after["shielding_certified"] == suite_before["shielding_certified"], (
        "the shielding dimension never read APPROVED, so its compensation must not fire: "
        "expected shielding_certified {}, got {}".format(
            suite_before["shielding_certified"], suite_after["shielding_certified"]))
    assert suite_after["lead_thickness_mm"] == suite_before["lead_thickness_mm"], (
        "the shielding dimension never read APPROVED, so lead_thickness_mm must not be "
        "cleared: expected {}, got {}".format(
            suite_before["lead_thickness_mm"], suite_after["lead_thickness_mm"]))

    rows, meta = validate_paginated(api.list_ti_line_items(project_id, LEASING_AGENT))
    assert_total_count(meta, 2)
    assert_line_split(rows[0], 0.6000, 24000.00, 16000.00)
    assert_line_split(rows[1], 0.6000, 18000.00, 12000.00)
    surviving_landlord_total = (round_money(rows[0]["landlord_share_amount"])
                                + round_money(rows[1]["landlord_share_amount"]))
    assert_money_equals(surviving_landlord_total, 42000.00,
                        "the immutable line items keep their resolved landlord shares")
    assert_money_equals(after["landlord_committed_amount"], 0.00,
                        "the cancelled project's landlord rollup")
