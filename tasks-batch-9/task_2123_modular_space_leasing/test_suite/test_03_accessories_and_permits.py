"""Steps and ramps, ADA compliance scoring, and the permitting workflow."""
from test_helpers import (
    DALLAS,
    ApiErrorId,
    assert_accessory_package,
    assert_permit_application,
    attach_accessory_package,
    book_job,
    create_jurisdiction,
    create_lease,
    create_permit,
    decide_permit,
    get_branch,
    get_lease,
    get_permit,
    get_unit,
    make_branch_ops_headers,
    make_fleet_admin_headers,
    make_leasing_agent_headers,
    set_clock,
    setup_dallas_catalog,
    setup_dallas_lease,
    setup_rural_lease,
    submit_permit,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import TX_RUR, create_accessory_package_payload

GHOST_JURISDICTION = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"


# ─── ADA ramp compliance at the exact boundary ───────────────────────────────

def test_ramp_run_exactly_meeting_the_requirement_is_compliant(api):
    """PRD §3.5: "The system first converts the building's finished-floor height
    to a rise in feet by dividing the model's `floor_height_in` by twelve, then
    multiplies that rise by the jurisdiction's `min_ramp_run_ratio` to obtain
    the run the authority requires."
    PRD §3.5: "The package is `COMPLIANT` only when all three conditions hold
    together — the `package_type` is `RAMP_ADA` or `COMBO`, the supplied ramp
    run is greater than or equal to the required run, and the supplied
    `landing_count` is greater than or equal to the required landing count."
    PRD §3.5: "Both comparisons are inclusive: a run that exactly equals the
    requirement passes, and a landing count that exactly equals the requirement
    passes."

    PRD §3.5: "The package's `monthly_accessory_rate_cents` is the sum of three
    parts: a base rent for the kit type — $125.00 for `STEPS`, $475.00 for
    `RAMP_ADA`, and $550.00 for `COMBO` — plus a ramp component charging $38.00
    for each four-foot segment of ramp run, where the segment count is the run
    in feet divided by four and rounded up to a whole number, plus a landing
    component charging $62.00 for each landing supplied."
    PRD §3.5: "The computed accessory rent is mirrored onto the lease's own
    `monthly_accessory_rate_cents`; the forward projection described in §3.4 is
    re-run so that `quoted_total_cents` absorbs the accessory rent across the
    full contracted term; and the lease's `version` is incremented by one."

    Design: Difficulty/boundary_precision_check/ada_ramp_run_is_inclusive_at_the_exact_required_run
    """
    ctx = setup_dallas_catalog(
        unit_count=1, customer_overrides={"credit_limit_cents": 9_000_000})
    lease = create_lease(ctx["customer"]["id"], ctx["unit"]["id"],
                         ctx["jurisdiction"]["id"], ctx["config"]["id"],
                         site_address="400 Commerce St, Dallas TX",
                         start_date="2026-09-01", term_months=12)

    # floor_height_in 36 -> a 3.0 ft rise; 3.0 * 12.0 -> exactly 36.0 ft of run.
    response = api.create_accessory_package(
        create_accessory_package_payload(lease["id"], "COMBO", ramp_run_ft=36.0,
                                         landing_count=2, step_count=4),
        make_leasing_agent_headers())
    package = validate_success(response, 201)
    assert_accessory_package(package)

    assert package["compliance_status"] == "COMPLIANT", (
        f"a run of exactly the required {DALLAS['REQUIRED_RAMP_RUN_FT']} ft must "
        f"pass, got {package['compliance_status']}")
    assert package["monthly_accessory_rate_cents"] == 101_600, (
        f"Expected 55000 + 9 * 3800 + 2 * 6200 = 101600, got "
        f"{package['monthly_accessory_rate_cents']}")

    refreshed = get_lease(lease["id"])
    assert refreshed["monthly_accessory_rate_cents"] == 101_600, (
        f"the accessory rent must be mirrored onto the lease, got "
        f"{refreshed['monthly_accessory_rate_cents']}")
    assert refreshed["quoted_total_cents"] == DALLAS["QUOTED_TOTAL_CENTS"], (
        f"Expected the projection to absorb the accessory rent and reach "
        f"3668170, got {refreshed['quoted_total_cents']}")


def test_ramp_run_just_under_the_requirement_is_not_compliant(api):
    """PRD §3.5: "The package is `COMPLIANT` only when all three conditions hold
    together — the `package_type` is `RAMP_ADA` or `COMBO`, the supplied ramp
    run is greater than or equal to the required run, and the supplied
    `landing_count` is greater than or equal to the required landing count."
    PRD §3.5: "If any of the three fails — including any steps-only package,
    which can never be accessible — the status is `NON_COMPLIANT`."
    PRD §3.5: "The package's `monthly_accessory_rate_cents` is the sum of three
    parts: a base rent for the kit type — $125.00 for `STEPS`, $475.00 for
    `RAMP_ADA`, and $550.00 for `COMBO` — plus a ramp component charging $38.00
    for each four-foot segment of ramp run, where the segment count is the run
    in feet divided by four and rounded up to a whole number, plus a landing
    component charging $62.00 for each landing supplied."

    Design: Difficulty/boundary_precision_check/ada_ramp_run_is_inclusive_at_the_exact_required_run
    """
    ctx = setup_dallas_catalog(
        unit_count=2, customer_overrides={"credit_limit_cents": 9_000_000})
    lease_at = create_lease(ctx["customer"]["id"], ctx["units"][0]["id"],
                            ctx["jurisdiction"]["id"], ctx["config"]["id"],
                            site_address="400 Commerce St, Dallas TX",
                            start_date="2026-09-01", term_months=12)
    lease_below = create_lease(ctx["customer"]["id"], ctx["units"][1]["id"],
                               ctx["jurisdiction"]["id"], ctx["config"]["id"],
                               site_address="402 Commerce St, Dallas TX",
                               start_date="2026-09-01", term_months=12)

    at_boundary = attach_accessory_package(lease_at["id"], "COMBO", ramp_run_ft=36.0,
                                           landing_count=2, step_count=4)
    below_boundary = attach_accessory_package(lease_below["id"], "COMBO",
                                              ramp_run_ft=35.5, landing_count=2,
                                              step_count=4)

    assert at_boundary["compliance_status"] == "COMPLIANT"
    assert below_boundary["compliance_status"] == "NON_COMPLIANT", (
        f"a 35.5 ft run falls short of the required 36.0 ft, got "
        f"{below_boundary['compliance_status']}")

    # Both price identically — nine started four-foot segments either way — so
    # the rent cannot stand in for the compliance verdict.
    assert at_boundary["monthly_accessory_rate_cents"] == 101_600
    assert below_boundary["monthly_accessory_rate_cents"] == 101_600, (
        f"35.5 ft still bills nine four-foot segments, got "
        f"{below_boundary['monthly_accessory_rate_cents']}")


# ─── Dispatch gated on the permit's state ────────────────────────────────────

def test_delivery_dispatch_is_blocked_while_the_permit_is_only_submitted(api):
    """PRD §3.8: "For a `DELIVERY_INSTALL` job, the lease's billing axis must be
    `ACCRUING` — an unactivated lease is refused with `ERR_LEASE_NOT_ACTIVATED`
    — and, where the jurisdiction's `permit_required` is true, there must be a
    permit application on that lease sitting at `APPROVED`, failing which the
    dispatch is refused with `ERR_PERMIT_NOT_APPROVED`; a jurisdiction that does
    not require a permit imposes no such condition."
    PRD §3.6: "Filing it with the authority moves it `DRAFT → SUBMITTED`, and it
    may only be filed while the lease's occupancy axis is still `PENDING`."

    Design: Difficulty/cross_entity_state_dependency/delivery_dispatch_gated_on_permit_application_state
    """
    ctx = setup_dallas_lease()
    permit = create_permit(ctx["lease"]["id"], ctx["jurisdiction"]["id"],
                           "PIER_FOUNDATION")
    submitted = submit_permit(permit["id"])
    assert submitted["status"] == "SUBMITTED", (
        f"Expected the filed permit to sit at SUBMITTED, got {submitted['status']}")

    validate_success(api.activate_lease(ctx["lease"]["id"],
                                        make_leasing_agent_headers()))
    job = book_job(ctx["lease"]["id"], ctx["branch"]["id"],
                   job_type="DELIVERY_INSTALL", scheduled_date="2026-09-01",
                   mileage_miles=180, crew_hours=6.5)

    blocked = api.dispatch_logistics_job(
        job["id"], make_branch_ops_headers(ctx["branch"]["id"]))
    validate_error(blocked, ApiErrorId.ERR_PERMIT_NOT_APPROVED.value)

    assert validate_success(api.get_logistics_job(
        job["id"], make_fleet_admin_headers()))["status"] == "SCHEDULED", (
        "the refused dispatch must leave the job SCHEDULED")
    assert get_unit(ctx["unit"]["id"])["status"] == "RESERVED", (
        "the refused dispatch must leave the unit in the yard as RESERVED")


def test_delivery_dispatch_succeeds_once_the_permit_is_approved(api):
    """PRD §3.6: "`SUBMITTED → APPROVED` unlocks the delivery dispatch that a
    permit-requiring jurisdiction would otherwise block, and it makes the
    application's `permit_fee_cents` a chargeable component of the lease's final
    settlement."
    PRD §3.8: "On success the unit moves `RESERVED → IN_TRANSIT`, its `version`
    is incremented, and its custody branch's `units_in_yard`, `units_available`
    and `utilization_pct` are all recomputed, with the in-yard count dropping by
    one as the building leaves the fence."

    Design: Difficulty/cross_entity_state_dependency/delivery_dispatch_gated_on_permit_application_state
    """
    ctx = setup_dallas_lease()
    permit = create_permit(ctx["lease"]["id"], ctx["jurisdiction"]["id"],
                           "PIER_FOUNDATION")
    submit_permit(permit["id"])
    validate_success(api.activate_lease(ctx["lease"]["id"],
                                        make_leasing_agent_headers()))
    job = book_job(ctx["lease"]["id"], ctx["branch"]["id"],
                   job_type="DELIVERY_INSTALL", scheduled_date="2026-09-01",
                   mileage_miles=180, crew_hours=6.5)
    validate_error(
        api.dispatch_logistics_job(job["id"],
                                   make_branch_ops_headers(ctx["branch"]["id"])),
        ApiErrorId.ERR_PERMIT_NOT_APPROVED.value)

    approved = decide_permit(permit["id"], "APPROVED", "Pier plan stamped.")
    assert approved["status"] == "APPROVED", (
        f"Expected APPROVED after the decision, got {approved['status']}")

    dispatched = validate_success(api.dispatch_logistics_job(
        job["id"], make_branch_ops_headers(ctx["branch"]["id"])))
    assert dispatched["status"] == "DISPATCHED", (
        f"the same call must now succeed, got {dispatched['status']}")
    assert get_unit(ctx["unit"]["id"])["status"] == "IN_TRANSIT", (
        "dispatch takes the unit RESERVED -> IN_TRANSIT")
    assert get_branch(ctx["branch"]["id"])["units_in_yard"] == 0, (
        "the in-yard count must drop by one as the building leaves the fence")


# ─── Corner coverage: accessory packages ─────────────────────────────────────

def test_accessory_package_defaults_its_three_optional_figures_to_zero(api):
    """PRD §3.5: "Three optional figures describe the kit: `ramp_run_ft`, the
    horizontal run of the ramp in feet, which is 0 for a steps-only package;
    `landing_count`, the number of intermediate and top landings supplied; and
    `step_count`, the number of treads in the step unit. All three default to 0
    and none may be negative."
    PRD §3.5: "If any of the three fails — including any steps-only package,
    which can never be accessible — the status is `NON_COMPLIANT`."
    PRD §3.5: "The computed accessory rent is mirrored onto the lease's own
    `monthly_accessory_rate_cents`; the forward projection described in §3.4 is
    re-run so that `quoted_total_cents` absorbs the accessory rent across the
    full contracted term; and the lease's `version` is incremented by one."

    Design: Corner/entities/accessory_package_omitting_ramp_fields_applies_declared_defaults
    """
    ctx = setup_rural_lease()

    response = api.create_accessory_package(
        {"lease_id": ctx["lease"]["id"], "package_type": "STEPS"},
        make_leasing_agent_headers())
    package = validate_success(response, 201)
    assert_accessory_package(package)

    assert float(package["ramp_run_ft"]) == 0, (
        f"Expected ramp_run_ft to default to 0, got {package['ramp_run_ft']}")
    assert package["landing_count"] == 0, (
        f"Expected landing_count to default to 0, got {package['landing_count']}")
    assert package["step_count"] == 0, (
        f"Expected step_count to default to 0, got {package['step_count']}")
    assert package["monthly_accessory_rate_cents"] == 12_500, (
        f"a bare STEPS kit prices at its $125.00 base alone, got "
        f"{package['monthly_accessory_rate_cents']}")
    assert package["compliance_status"] == "NON_COMPLIANT", (
        f"a steps-only package can never be accessible, got "
        f"{package['compliance_status']}")

    lease = get_lease(ctx["lease"]["id"])
    assert lease["monthly_accessory_rate_cents"] == 12_500
    assert lease["quoted_total_cents"] == 2_026_280, (
        f"Expected 351500 + (127065 + 12500) * 12 = 2026280, got "
        f"{lease['quoted_total_cents']}")


def test_second_accessory_package_on_a_lease_is_rejected(api):
    """PRD §3.5: "A `LeasingAgent` attaches at most one **accessory package** to
    a lease by naming the `lease_id` and the `package_type`, which is `STEPS`
    for a step unit alone, `RAMP_ADA` for an accessible ramp, or `COMBO` for
    both."
    PRD §3.5: "A second attempt to attach a package to a lease that already
    carries one is rejected with `ERR_ACCESSORY_ALREADY_ATTACHED`."

    Design: Corner/validations/second_accessory_package_on_a_lease_is_rejected
    """
    ctx = setup_rural_lease()
    attach_accessory_package(ctx["lease"]["id"], "STEPS", step_count=4)

    second = api.create_accessory_package(
        create_accessory_package_payload(ctx["lease"]["id"], "RAMP_ADA",
                                         ramp_run_ft=24.0, landing_count=1),
        make_leasing_agent_headers())
    validate_error(second, ApiErrorId.ERR_ACCESSORY_ALREADY_ATTACHED.value)

    _, meta = validate_paginated(api.list_accessory_packages(
        make_leasing_agent_headers(), params={"lease_id": ctx["lease"]["id"]}))
    assert meta["total_count"] == 1, (
        f"Expected exactly one package on the lease, got {meta['total_count']}")

    lease = get_lease(ctx["lease"]["id"])
    assert lease["monthly_accessory_rate_cents"] == 12_500, (
        f"the rejected package must not re-rate the lease, got "
        f"{lease['monthly_accessory_rate_cents']}")
    assert lease["quoted_total_cents"] == 2_026_280


# ─── Corner coverage: permits ────────────────────────────────────────────────

def test_permit_foundation_type_must_match_the_jurisdictions_anchoring_standard(api):
    """PRD §3.6: "The authority named on the application must be the authority
    named on the lease — a mismatch between the application's `jurisdiction_id`
    and the lease's `jurisdiction_id` is rejected with
    `ERR_ENTITY_LINK_MISMATCH` — and the proposed foundation must be exactly the
    class the authority mandates in its `anchoring_standard`, with any deviation
    refused as `ERR_ANCHORING_STANDARD_MISMATCH`."

    Design: Corner/validations/permit_foundation_type_must_match_the_jurisdiction_anchoring_standard
    """
    ctx = setup_dallas_lease(with_package=False)

    response = api.create_permit_application(
        {"lease_id": ctx["lease"]["id"], "jurisdiction_id": ctx["jurisdiction"]["id"],
         "foundation_type": "GROUND_ANCHOR"},
        make_leasing_agent_headers())
    validate_error(response, ApiErrorId.ERR_ANCHORING_STANDARD_MISMATCH.value)

    _, meta = validate_paginated(api.list_permit_applications(
        make_leasing_agent_headers(), params={"lease_id": ctx["lease"]["id"]}))
    assert meta["total_count"] == 0, (
        f"the rejected application must not persist, got {meta['total_count']}")


def test_permit_jurisdiction_must_match_the_lease_jurisdiction(api):
    """PRD §3.6: "The authority named on the application must be the authority
    named on the lease — a mismatch between the application's `jurisdiction_id`
    and the lease's `jurisdiction_id` is rejected with
    `ERR_ENTITY_LINK_MISMATCH` — and the proposed foundation must be exactly the
    class the authority mandates in its `anchoring_standard`, with any deviation
    refused as `ERR_ANCHORING_STANDARD_MISMATCH`."
    PRD §2.7: "Foreign keys supplied in a request body are resolved after path
    identifiers, and they are resolved **in the order the fields are declared
    for that operation** — the first unresolvable reference decides the
    response."

    Design: Corner/validations/permit_jurisdiction_must_match_the_lease_jurisdiction
    """
    ctx = setup_dallas_lease(with_package=False)
    other_authority = create_jurisdiction(**TX_RUR)

    # The anchoring agreement sits at rank 11 of the §2.9 ladder and the
    # cross-entity link agreement at rank 13, so the proposed foundation must
    # be the class the *addressed* authority mandates (TX-RUR mandates
    # GROUND_ANCHOR) for the link disagreement to be the deciding check.
    wrong_authority = api.create_permit_application(
        {"lease_id": ctx["lease"]["id"], "jurisdiction_id": other_authority["id"],
         "foundation_type": "GROUND_ANCHOR"},
        make_leasing_agent_headers())
    validate_error(wrong_authority, ApiErrorId.ERR_ENTITY_LINK_MISMATCH.value)

    never_minted = api.create_permit_application(
        {"lease_id": ctx["lease"]["id"], "jurisdiction_id": GHOST_JURISDICTION,
         "foundation_type": "PIER_FOUNDATION"},
        make_leasing_agent_headers())
    validate_error(never_minted, ApiErrorId.ERR_JURISDICTION_NOT_FOUND.value)

    _, meta = validate_paginated(api.list_permit_applications(
        make_leasing_agent_headers(), params={"lease_id": ctx["lease"]["id"]}))
    assert meta["total_count"] == 0, (
        f"neither rejected application may persist, got {meta['total_count']}")


def test_permit_filed_inside_the_lead_window_is_rejected(api):
    """PRD §3.6: "The lead-time rule bites here: the number of whole days
    between the logical clock's calendar date and the lease's `start_date` must
    be greater than or equal to the jurisdiction's `permit_lead_days`, and an
    application filed too late for the authority to turn it around is refused
    with `ERR_PERMIT_LEAD_TIME_VIOLATION`."
    PRD §3.6: "On a successful filing the system stamps `submitted_on` with the
    logical clock's calendar date."
    PRD §3.6: "The filing fee is derived into `permit_fee_cents` as the
    authority's flat `permit_fee_cents` plus an area component of $15.00 for
    each hundred-square-foot block of the building's `floor_area_sqft`, where
    the block count is the floor area divided by one hundred and rounded up to a
    whole number."

    Design: Corner/validations/permit_submitted_inside_the_lead_window_is_rejected
    """
    ctx = setup_dallas_lease(with_package=False)
    permit = create_permit(ctx["lease"]["id"], ctx["jurisdiction"]["id"],
                           "PIER_FOUNDATION")
    assert_permit_application(permit)
    assert permit["status"] == "DRAFT"
    assert permit["permit_fee_cents"] == DALLAS["PERMIT_FEE_CENTS"], (
        f"Expected 145000 + 15 blocks * 1500 = 167500, got "
        f"{permit['permit_fee_cents']}")

    # TX-DAL demands 21 whole days of lead; on 2026-08-20 only 12 remain before
    # the 2026-09-01 start.
    set_clock("2026-08-20T00:00:00Z")
    response = api.submit_permit_application(permit["id"],
                                             make_leasing_agent_headers())
    validate_error(response, ApiErrorId.ERR_PERMIT_LEAD_TIME_VIOLATION.value)

    after = get_permit(permit["id"])
    assert after["status"] == "DRAFT", (
        f"the refused filing must leave the application in DRAFT, got "
        f"{after['status']}")
    assert after["submitted_on"] is None, (
        f"submitted_on is stamped only on a successful filing, got "
        f"{after['submitted_on']}")
    assert after["permit_fee_cents"] == DALLAS["PERMIT_FEE_CENTS"]
