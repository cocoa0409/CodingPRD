"""Two entity pairs whose gate lives on a third record's state, in opposite directions."""
from test_helpers import ApiErrorId, assert_mix_figures, validate_error
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import LEASING_AGENT


def _restricted_building_with_two_ready_leases(api):
    """An anchor lease already executed, plus an affiliated and an independent lease ready to go."""
    building = fx.register_building(api)
    anchor_suite = fx.register_suite(api, building["id"], suite_number="100", floor=1,
                                     rentable_sf=12000, suite_class="STANDARD_EXAM",
                                     power_amps_available=400)
    affiliated_suite = fx.register_suite(api, building["id"], suite_number="310", floor=3,
                                         rentable_sf=4000, suite_class="PROCEDURE",
                                         power_amps_available=300, medical_gas_available=True)
    independent_suite = fx.register_suite(api, building["id"], suite_number="210", floor=2,
                                          rentable_sf=5000, suite_class="STANDARD_EXAM",
                                          power_amps_available=200)
    anchor_tenant = fx.register_tenant(api, legal_name="Meridian Health System Clinics",
                                       affiliation="HEALTH_SYSTEM_ANCHOR",
                                       primary_specialty="PRIMARY_CARE")
    affiliated_tenant = fx.register_tenant(api, legal_name="Meridian Cardiovascular Associates",
                                           affiliation="HEALTH_SYSTEM_AFFILIATED",
                                           primary_specialty="CARDIOLOGY")
    independent_tenant = fx.register_tenant(api, legal_name="Northgate Medical Group PC",
                                            affiliation="INDEPENDENT_PRACTICE",
                                            primary_specialty="GASTROENTEROLOGY")

    anchor_lease = fx.draft_lease(api, building["id"], anchor_suite["id"], anchor_tenant["id"],
                                 term_start="2026-09-01", term_end="2031-08-31",
                                 base_rent_psf_annual=28.00)
    fx.file_attestation(api, anchor_lease["id"], "SIGNED_LEASE")
    fx.submit_for_review(api, anchor_lease["id"], "Anchor")
    fx.certify(api, anchor_lease["id"], "28.00 psf inside [24.00, 34.50]")
    fx.execute(api, anchor_lease["id"], "Executed while BALANCED")

    affiliated_lease = fx.draft_lease(api, building["id"], affiliated_suite["id"],
                                      affiliated_tenant["id"], term_start="2026-09-01",
                                      term_end="2031-08-31", base_rent_psf_annual=34.25)
    fx.file_attestation(api, affiliated_lease["id"], "SIGNED_LEASE")
    fx.submit_for_review(api, affiliated_lease["id"], "Affiliated cardiology")
    affiliated_lease = fx.certify(api, affiliated_lease["id"],
                                  "34.25 psf inside [27.40, 39.39]")

    independent_lease = fx.draft_lease(api, building["id"], independent_suite["id"],
                                       independent_tenant["id"], term_start="2026-09-01",
                                       term_end="2029-08-31", base_rent_psf_annual=30.00)
    fx.file_attestation(api, independent_lease["id"], "SIGNED_LEASE")
    fx.submit_for_review(api, independent_lease["id"], "Independent diluting lease")
    independent_lease = fx.certify(api, independent_lease["id"],
                                   "30.00 psf inside [24.00, 34.50]")

    return {
        "building": building,
        "affiliated_suite": affiliated_suite,
        "anchor_lease": anchor_lease,
        "affiliated_lease": affiliated_lease,
        "independent_lease": independent_lease,
    }


def test_an_internally_perfect_affiliated_lease_is_refused_by_the_buildings_posture(api):
    """The refusal comes from the Building record, not from anything on the lease itself.

    PRD: "Where the tenant's `affiliation` is `HEALTH_SYSTEM_ANCHOR` or
    `HEALTH_SYSTEM_AFFILIATED`, the building's `tenant_mix_posture` is not `RESTRICTED`; and for
    the same reason a reinstatement decision on a `SUSPENDED_MIX_REVIEW` lease is refused while
    the posture is still `RESTRICTED`. A violation is `ERR_BUILDING_MIX_RESTRICTED` (422),
    guarding `POST /leases/{id}/execute` and `POST /leases/{id}/compliance-decisions`."

    Design: Difficulty/cross_entity_state_dependency/lease_execute_blocked_by_building_restricted_posture
    """
    ctx = _restricted_building_with_two_ready_leases(api)
    before = fx.read_building(api, ctx["building"]["id"])
    assert_mix_figures(before, anchor_sf=12000, independent_sf=0, leased_sf=12000,
                       vacant_sf=88000, anchor_share_pct=1.0000, posture="RESTRICTED")
    assert ctx["affiliated_lease"]["status"] == "FMV_CERTIFIED"
    assert ctx["affiliated_lease"]["signed_lease_on_file"] is True

    refused = api.execute_lease(ctx["affiliated_lease"]["id"],
                               {"execution_note": "Building is RESTRICTED"}, LEASING_AGENT)
    validate_error(refused, ApiErrorId.ERR_BUILDING_MIX_RESTRICTED)

    assert fx.read_lease(api, ctx["affiliated_lease"]["id"])["status"] == "FMV_CERTIFIED"
    assert fx.read_suite(api, ctx["affiliated_suite"]["id"])["occupancy_status"] == "VACANT"


def test_diluting_the_anchor_share_admits_the_byte_identical_retry(api):
    """Executing an unrelated independent lease is the only thing that changes, and it is enough.

    PRD: "`anchor_share_pct` is `anchor_rentable_sf` divided by `leased_rentable_sf`, rounded
    half up to 4 decimal places; when `leased_rentable_sf` is zero the share reads 0.0000 rather
    than being undefined."

    PRD: "Otherwise, if `anchor_share_pct` is strictly greater than 0.7500 the posture is
    `RESTRICTED`; otherwise, if it is strictly greater than 0.6000 the posture is
    `ANCHOR_CONCENTRATED`; otherwise it is `BALANCED`."

    Design: Difficulty/cross_entity_state_dependency/lease_execute_blocked_by_building_restricted_posture
    """
    ctx = _restricted_building_with_two_ready_leases(api)
    validate_error(
        api.execute_lease(ctx["affiliated_lease"]["id"],
                          {"execution_note": "Building is RESTRICTED"}, LEASING_AGENT),
        ApiErrorId.ERR_BUILDING_MIX_RESTRICTED)

    fx.execute(api, ctx["independent_lease"]["id"], "Independent dilutes the anchor share")
    diluted = fx.read_building(api, ctx["building"]["id"])
    assert_mix_figures(diluted, anchor_sf=12000, independent_sf=5000, leased_sf=17000,
                       vacant_sf=83000, anchor_share_pct=0.7059,
                       posture="ANCHOR_CONCENTRATED")

    admitted = fx.execute(api, ctx["affiliated_lease"]["id"], "Building is RESTRICTED")
    assert admitted["status"] == "EXECUTED"
    assert fx.read_suite(api, ctx["affiliated_suite"]["id"])["occupancy_status"] == "RESERVED"

    final = fx.read_building(api, ctx["building"]["id"])
    assert_mix_figures(final, anchor_sf=16000, independent_sf=5000, leased_sf=21000,
                       vacant_sf=79000, anchor_share_pct=0.7619, posture="RESTRICTED")


def _permitted_imaging_project_on_a_draft_lease(api):
    """A project with both dimensions approved, sitting in PERMITTED under a DRAFT lease."""
    ctx = fx.drafted_lease(api)
    ctx["project"] = fx.ti_project_permitted(
        api, ctx["lease"]["id"], ctx["suite"]["id"],
        line_items=[{"description": "Lead shielding, walls and ceiling",
                     "category": "SHIELDING", "cost_amount": 88000.00}],
        lead_thickness_verified_mm=2.5,
        target_suite_class="IMAGING", lead_thickness_mm=2.5, power_amps_requested=150,
        medical_gas_requested=False, authorized_allowance_total=500000.00,
        landlord_share_pct=0.60)
    return ctx


def test_construction_cannot_start_while_the_owning_lease_is_still_a_draft(api):
    """The project is internally ready; the refusal lives entirely on the parent lease's status.

    PRD: "`START_CONSTRUCTION` moves the project `PERMITTED → CONSTRUCTION` and requires the
    owning lease to be in `EXECUTED` or `ACTIVE` — no construction proceeds on a lease that has
    not been executed, and a violation is `ERR_TI_PROJECT_NOT_COMPLETE` — as well as an
    `allowance_remaining` of zero or more."

    Design: Difficulty/cross_entity_state_dependency/ti_construction_start_requires_lease_executed_or_active
    """
    ctx = _permitted_imaging_project_on_a_draft_lease(api)
    assert ctx["project"]["status"] == "PERMITTED"
    assert ctx["project"]["shielding_review_status"] == "APPROVED"
    assert ctx["project"]["utility_review_status"] == "APPROVED"
    assert fx.read_lease(api, ctx["lease"]["id"])["status"] == "DRAFT"

    refused = api.transition_ti_project(
        ctx["project"]["id"],
        f.ti_transition_payload("START_CONSTRUCTION", "Attempt while the lease is DRAFT"),
        LEASING_AGENT)
    validate_error(refused, ApiErrorId.ERR_TI_PROJECT_NOT_COMPLETE)
    assert fx.read_project(api, ctx["project"]["id"])["status"] == "PERMITTED"


def test_executing_the_lease_without_touching_the_project_admits_the_transition(api):
    """The gate is on the lease, so only the lease has to move; the utility draw never shifts.

    PRD: "Approving the utility dimension requires the suite's `power_amps_available` to be at
    least the project's `power_amps_requested`, refused as `ERR_INSUFFICIENT_UTILITY_CAPACITY`,
    and requires the suite's `medical_gas_available` to be true whenever `medical_gas_requested`
    is true, refused as `ERR_SHIELDING_CERTIFICATION_MISSING`; it then sets
    `utility_review_status` to `APPROVED`, reduces the suite's `power_amps_available` by
    `power_amps_requested`, records the amount actually drawn in the project's
    `power_amps_drawn`, and advances the suite's `version`."

    Design: Difficulty/cross_entity_state_dependency/ti_construction_start_requires_lease_executed_or_active
    """
    ctx = _permitted_imaging_project_on_a_draft_lease(api)
    validate_error(
        api.transition_ti_project(
            ctx["project"]["id"],
            f.ti_transition_payload("START_CONSTRUCTION", "Attempt while the lease is DRAFT"),
            LEASING_AGENT),
        ApiErrorId.ERR_TI_PROJECT_NOT_COMPLETE)
    assert fx.read_suite(api, ctx["suite"]["id"])["power_amps_available"] == 50

    fx.file_attestation(api, ctx["lease"]["id"], "SIGNED_LEASE")
    fx.submit_for_review(api, ctx["lease"]["id"], "Corporate practice")
    fx.certify(api, ctx["lease"]["id"], "30.00 psf inside [24.00, 34.50]")
    executed = fx.execute(api, ctx["lease"]["id"], "Executed")
    assert executed["status"] == "EXECUTED"

    started = fx.ti_transition(api, ctx["project"]["id"], "START_CONSTRUCTION",
                               "Identical retry with the lease EXECUTED")
    assert started["status"] == "CONSTRUCTION"
    assert fx.read_suite(api, ctx["suite"]["id"])["power_amps_available"] == 50
