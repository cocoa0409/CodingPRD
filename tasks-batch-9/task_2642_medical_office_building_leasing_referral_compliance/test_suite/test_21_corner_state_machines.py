"""Status machines: declared initial states, declared hops, and refused transitions.

Time-driven hops are exercised through the daily close rather than through the
clock alone. Every test starts against an empty database and builds its own state.
"""
from test_helpers import (
    ApiErrorId,
    COMPLIANCE_OFFICER,
    FACILITIES_ENGINEER,
    LEASING_AGENT,
    PORTFOLIO_ADMIN,
    PROPERTY_MANAGER,
    assert_certified_band,
    assert_certified_rent_variant,
    assert_invoice_breakdown,
    assert_mix_figures,
    assert_money_equals,
    assert_parking_counters,
    assert_project_rollups,
    assert_provisional_rent_variant,
    assert_share_equals,
    assert_total_count,
    certified_band,
    expected_invoice_total,
    factories,
    published_psf,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


def _appraisal_rows(api, lease_id):
    """Read a lease's appraisal roster."""
    rows, _meta = validate_paginated(api.list_lease_appraisals(lease_id, COMPLIANCE_OFFICER))
    return rows


def _case_rows(api, tenant_id):
    """Read a tenant's compliance case roster."""
    rows, _meta = validate_paginated(
        api.list_tenant_compliance_cases(tenant_id, COMPLIANCE_OFFICER))
    return rows


def _booking(api, booking_id):
    """Read one shared-space booking."""
    return validate_success(api.get_booking(booking_id, LEASING_AGENT))


def _allocation(api, allocation_id):
    """Read one parking allocation."""
    return validate_success(api.get_parking_allocation(allocation_id, PROPERTY_MANAGER))


def test_lease_ti_project_and_appraisal_start_in_their_declared_initial_states(api):
    """Newly created leases, appraisals and projects carry their declared opening values.

    "A new lease is created in status `DRAFT` with `fmv_certification_status` reading
    `NOT_STARTED`, `revision_round` at 0 and `version` at 1."
    "`opinion_midpoint_psf` is the mean of the two ends, rounded half up to 2 decimal
    places." "`expires_on` is `appraisal_date` plus 365 days, expressed as a UTC date —
    an opinion of value is stale after a year." "The new row begins in `SUBMITTED` with
    `is_controlling` false, `decision_reason` null, and the owning lease's `version`
    advances by 1 because the lease now has new evidence attached to it."
    "A new project starts in `DESIGN` with both review dimensions reading
    `NOT_SUBMITTED`, `line_item_count` at 0, `landlord_committed_amount` and
    `tenant_committed_amount` at 0.00, `allowance_remaining` equal to
    `authorized_allowance_total`, `power_amps_drawn` at 0 and `on_hold_from_status` null."
    "Every new suite begins `VACANT` with `last_vacated_on` null, and adding a suite
    advances the owning building's `version` by 1."

    Design: Corner/state_machines/lease_ti_project_and_appraisal_start_in_declared_initial_states
    """
    building = fx.register_building(api)
    suite = fx.register_suite(api, building["id"])
    tenant = fx.register_tenant(api, is_physician_owned=True,
                                primary_specialty="RADIOLOGY")

    assert suite["occupancy_status"] == "VACANT"
    assert suite["last_vacated_on"] is None

    lease = validate_success(
        api.create_lease(
            factories.create_lease_payload(building["id"], suite["id"], tenant["id"]),
            LEASING_AGENT),
        201)
    assert lease["status"] == "DRAFT"
    assert lease["fmv_certification_status"] == "NOT_STARTED"
    assert lease["revision_round"] == 0
    assert lease["version"] == 1

    appraisal = validate_success(
        api.create_appraisal(
            lease["id"],
            factories.create_appraisal_payload(lease["version"]),
            COMPLIANCE_OFFICER),
        201)
    assert appraisal["status"] == "SUBMITTED"
    assert appraisal["is_controlling"] is False
    assert appraisal["decision_reason"] is None
    assert_money_equals(appraisal["opinion_midpoint_psf"], 31.00, "opinion_midpoint_psf")
    assert appraisal["expires_on"] == "2027-07-15"
    assert fx.read_lease(api, lease["id"])["version"] == lease["version"] + 1

    project = validate_success(
        api.create_ti_project(
            lease["id"],
            factories.create_ti_project_payload(suite["id"], target_suite_class="IMAGING",
                                                lead_thickness_mm=2.5,
                                                authorized_allowance_total=250000.00),
            LEASING_AGENT),
        201)
    assert project["status"] == "DESIGN"
    assert project["shielding_review_status"] == "NOT_SUBMITTED"
    assert project["utility_review_status"] == "NOT_SUBMITTED"
    assert project["line_item_count"] == 0
    assert_money_equals(project["landlord_committed_amount"], 0.00,
                        "landlord_committed_amount")
    assert_money_equals(project["tenant_committed_amount"], 0.00, "tenant_committed_amount")
    assert_money_equals(project["allowance_remaining"], 250000.00, "allowance_remaining")
    assert project["power_amps_drawn"] == 0
    assert project["on_hold_from_status"] is None

    # None of that paperwork moved the suite: occupancy answers only to lease transitions.
    assert fx.read_suite(api, suite["id"])["occupancy_status"] == "VACANT"


def test_lease_lifecycle_walks_every_declared_hop_from_draft_to_active(api):
    """Each forward hop is taken one at a time and drags its suite and building with it.

    "Submitting a draft for fair-market-value review moves it `DRAFT →
    PENDING_FMV_REVIEW` and accepts an optional `submission_note`."
    "On success, `fmv_certification_status` becomes `PENDING`, the acting `X-User-ID` is
    recorded as `fmv_submitted_by_user_id` — the comparand the certifier will be checked
    against — the provisional rent is recomputed and frozen at the rate card as it stands
    at that moment, and `version` advances by 1."
    "For a tenant whose `is_physician_owned` is false, that published pair **is** the
    band: `certified_fmv_floor_psf` is the published floor and `certified_fmv_ceiling_psf`
    is the published ceiling, and no appraisal is consulted."
    "It accepts an optional `execution_note` and moves a certified lease `FMV_CERTIFIED →
    EXECUTED`." "The demised suite moves `VACANT → RESERVED`, its `updated_at` is
    refreshed and its `version` advances by 1."
    "Commencement is the `PropertyManager`'s act, accepts an optional
    `commencement_note`, and moves a lease `EXECUTED → ACTIVE`."
    "On success the suite moves `RESERVED → OCCUPIED` with its `version` advanced, the
    building's tenant mix is recomputed with the building's `version` advanced, and the
    lease's `version` advances."

    Design: Corner/state_machines/lease_lifecycle_draft_to_active_walks_every_declared_hop
    """
    ctx = fx.leasing_baseline(api)
    building_id, suite_id = ctx["building"]["id"], ctx["suite"]["id"]
    lease = fx.draft_lease(api, building_id, suite_id, ctx["tenant"]["id"])
    lease_id = lease["id"]
    assert lease["status"] == "DRAFT"
    assert_provisional_rent_variant(lease, 150000.00)
    fx.file_attestation(api, lease_id, "SIGNED_LEASE")

    lease = validate_success(
        api.submit_fmv_review(lease_id, {"submission_note": "Rate card applied"},
                              LEASING_AGENT))
    assert lease["status"] == "PENDING_FMV_REVIEW"
    assert lease["fmv_certification_status"] == "PENDING"
    assert lease["fmv_submitted_by_user_id"] == "agent-001"
    assert_provisional_rent_variant(lease, 150000.00)
    assert fx.read_suite(api, suite_id)["occupancy_status"] == "VACANT"

    lease = validate_success(
        api.certify_fmv(lease_id, {"certification_note": "Within published band"},
                        COMPLIANCE_OFFICER))
    assert lease["status"] == "FMV_CERTIFIED"
    assert lease["fmv_certification_status"] == "CERTIFIED"
    floor, ceiling = certified_band(30.00, "STANDARD_EXAM")
    assert (floor, ceiling) == (24.00, 34.50)
    assert_certified_band(lease, floor, ceiling)
    assert_certified_rent_variant(lease, 150000.00, 150000.00)
    assert fx.read_suite(api, suite_id)["occupancy_status"] == "VACANT"

    lease = validate_success(
        api.execute_lease(lease_id, {"execution_note": "Countersigned"}, LEASING_AGENT))
    assert lease["status"] == "EXECUTED"
    assert fx.read_suite(api, suite_id)["occupancy_status"] == "RESERVED"
    assert_mix_figures(fx.read_building(api, building_id), 0, 5000, 5000, 95000,
                       0.0000, "BALANCED")

    fx.set_clock_date(api, "2026-09-01")
    lease = validate_success(
        api.commence_lease(lease_id, {"commencement_note": "Keys handed over"},
                           PROPERTY_MANAGER))
    assert lease["status"] == "ACTIVE"
    assert fx.read_suite(api, suite_id)["occupancy_status"] == "OCCUPIED"
    assert_mix_figures(fx.read_building(api, building_id), 0, 5000, 5000, 95000,
                       0.0000, "BALANCED")


def test_lease_submit_fmv_review_and_certification_are_refused_once_executed(api):
    """The review hops are unavailable once the lease has reached EXECUTED.

    "The addressed lease occupies a status from which the requested transition is
    declared: `DRAFT` for review submission, amendment and withdrawal;
    `PENDING_FMV_REVIEW` for certification and for a return-for-revision decision;
    `FMV_CERTIFIED` for amendment and execution; `EXECUTED` for commencement; `EXECUTED`,
    `ACTIVE` or `HOLDOVER` for termination; `SUSPENDED_MIX_REVIEW` for a reinstatement
    decision; and any status other than `TERMINATED` or `WITHDRAWN` for filing
    attestations, appraisals, projects, invoices, bookings and allocations. A violation is
    `ERR_INVALID_LEASE_STATE` (409)."

    Design: Corner/state_machines/lease_submit_fmv_review_from_executed_rejected
    """
    ctx = fx.executed_lease(api)
    lease_id = ctx["lease"]["id"]
    assert ctx["lease"]["status"] == "EXECUTED"

    validate_error(
        api.submit_fmv_review(lease_id, {"submission_note": "Second bite"}, LEASING_AGENT),
        ApiErrorId.ERR_INVALID_LEASE_STATE)
    validate_error(
        api.certify_fmv(lease_id, {"certification_note": "Re-certify"}, COMPLIANCE_OFFICER),
        ApiErrorId.ERR_INVALID_LEASE_STATE)

    lease = fx.read_lease(api, lease_id)
    assert lease["status"] == "EXECUTED"
    assert lease["fmv_certification_status"] == "CERTIFIED"
    assert lease["revision_round"] == 0


def test_terminated_lease_is_locked_against_every_further_transition(api):
    """TERMINATED is terminal: no second termination, no amendment, no new invoice.

    "The addressed lease occupies a status from which the requested transition is
    declared: `DRAFT` for review submission, amendment and withdrawal;
    `PENDING_FMV_REVIEW` for certification and for a return-for-revision decision;
    `FMV_CERTIFIED` for amendment and execution; `EXECUTED` for commencement; `EXECUTED`,
    `ACTIVE` or `HOLDOVER` for termination; `SUSPENDED_MIX_REVIEW` for a reinstatement
    decision; and any status other than `TERMINATED` or `WITHDRAWN` for filing
    attestations, appraisals, projects, invoices, bookings and allocations. A violation is
    `ERR_INVALID_LEASE_STATE` (409)."
    "Both routes back to `VACANT` stamp `last_vacated_on` with the clock date and advance
    the suite's `version`."

    Design: Corner/state_machines/terminated_lease_is_locked_against_further_transitions
    """
    ctx = fx.active_lease(api)
    lease_id, suite_id = ctx["lease"]["id"], ctx["suite"]["id"]
    lease = fx.terminate(api, lease_id, "MUTUAL")
    assert lease["status"] == "TERMINATED"
    assert lease["terminated_on"] == "2026-09-01"

    validate_error(
        api.terminate_lease(lease_id, factories.terminate_payload("MUTUAL"),
                            PROPERTY_MANAGER),
        ApiErrorId.ERR_INVALID_LEASE_STATE)
    # The supplied version is the row's current one, so only the status can be at fault.
    validate_error(
        api.patch_lease(lease_id,
                        factories.patch_lease_payload(lease["version"],
                                                      base_rent_psf_annual=31.00),
                        LEASING_AGENT),
        ApiErrorId.ERR_INVALID_LEASE_STATE)
    validate_error(
        api.create_rent_invoice(
            lease_id,
            factories.create_rent_invoice_payload("2026-09-01", "2026-09-30", "2026-10-01"),
            PROPERTY_MANAGER),
        ApiErrorId.ERR_INVALID_LEASE_STATE)

    after = fx.read_lease(api, lease_id)
    assert after["status"] == "TERMINATED"
    assert after["terminated_on"] == "2026-09-01"
    suite = fx.read_suite(api, suite_id)
    assert suite["occupancy_status"] == "VACANT"
    assert suite["last_vacated_on"] == "2026-09-01"


def test_appraisal_cannot_be_qualified_after_it_has_been_disqualified(api):
    """DISQUALIFIED is terminal for an appraisal, and the lease is left without evidence.

    "The addressed appraisal, rent invoice, compliance case or shared-space booking
    occupies a status from which the requested transition is declared — `SUBMITTED` to
    qualify; `SUBMITTED` or `QUALIFIED` to disqualify; `ISSUED` or `DELINQUENT` to accept a
    payment; `DELINQUENT` to write off; `OPEN` or `REMEDIATION_PLANNED` to cure; `OPEN` to
    record a remediation plan or to report; `BOOKED` to cancel. A violation is
    `ERR_INVALID_RECORD_STATE` (409)."
    "Disqualifying a row that was **not** controlling — including any row still in
    `SUBMITTED` — has no lease-side effect at all: the row moves to `DISQUALIFIED`, records
    its `decision_reason`, and nothing else changes."
    "And where the tenant's `is_physician_owned` is true, at least one appraisal on the
    lease must be `QUALIFIED` with an `expires_on` on or after the clock date, otherwise
    `ERR_NO_QUALIFYING_APPRAISAL`; a tenant that is not physician-owned needs no appraisal
    at all."

    Design: Corner/state_machines/appraisal_qualify_after_disqualify_rejected
    """
    ctx = fx.drafted_lease(
        api,
        suite_overrides={"suite_class": "IMAGING", "rentable_sf": 8000,
                         "shielding_certified": True, "lead_thickness_mm": 2.5},
        tenant_overrides={"is_physician_owned": True, "primary_specialty": "RADIOLOGY"},
        lease_overrides={"base_rent_psf_annual": 38.00})
    lease_id = ctx["lease"]["id"]
    appraisal = fx.file_appraisal(api, lease_id, ctx["lease"]["version"],
                                  opinion_low_psf=38.00, opinion_high_psf=42.00)
    assert appraisal["status"] == "SUBMITTED"

    disqualified = validate_success(
        api.decide_appraisal(appraisal["id"],
                             factories.appraisal_decision_payload(
                                 "DISQUALIFY", "Comparables not medical office"),
                             COMPLIANCE_OFFICER))
    assert disqualified["status"] == "DISQUALIFIED"
    assert disqualified["decision_reason"] == "Comparables not medical office"
    assert disqualified["is_controlling"] is False
    assert fx.read_lease(api, lease_id)["status"] == "DRAFT"

    validate_error(
        api.decide_appraisal(appraisal["id"],
                             factories.appraisal_decision_payload("QUALIFY"),
                             COMPLIANCE_OFFICER),
        ApiErrorId.ERR_INVALID_RECORD_STATE)
    assert _appraisal_rows(api, lease_id)[0]["status"] == "DISQUALIFIED"

    # With no qualified opinion left, the physician-owned lease cannot enter review.
    validate_error(
        api.submit_fmv_review(lease_id, {"submission_note": "Ready for band check"},
                              LEASING_AGENT),
        ApiErrorId.ERR_NO_QUALIFYING_APPRAISAL)
    lease = fx.read_lease(api, lease_id)
    assert lease["status"] == "DRAFT"
    assert lease["fmv_certification_status"] == "NOT_STARTED"


def test_ti_project_cancellation_is_refused_once_construction_has_started(api):
    """CONSTRUCTION is outside the cancellation window, so nothing is compensated.

    "The addressed tenant-improvement project occupies a status from which the requested
    transition is declared — `DESIGN` for a review submission and for appending a line
    item, `IN_REVIEW` for recording a review, `PERMITTED` for starting construction,
    `CONSTRUCTION` for close-out, and `DESIGN`, `IN_REVIEW` or `PERMITTED` for
    cancellation — and the review dimension being addressed is `PENDING`. A violation is
    `ERR_INVALID_TI_STATE` (409)."
    "`CANCEL` is admissible from `DESIGN`, `IN_REVIEW` or `PERMITTED` and moves the project
    to `CANCELLED`."
    "Approving the utility dimension requires the suite's `power_amps_available` to be at
    least the project's `power_amps_requested`, refused as
    `ERR_INSUFFICIENT_UTILITY_CAPACITY`, and requires the suite's `medical_gas_available`
    to be true whenever `medical_gas_requested` is true, refused as
    `ERR_SHIELDING_CERTIFICATION_MISSING`; it then sets `utility_review_status` to
    `APPROVED`, reduces the suite's `power_amps_available` by `power_amps_requested`,
    records the amount actually drawn in the project's `power_amps_drawn`, and advances the
    suite's `version`."

    Design: Corner/state_machines/ti_project_cancel_from_construction_rejected
    """
    ctx = fx.executed_lease(api)
    project = fx.ti_project_in_construction(
        api, ctx["lease"]["id"], ctx["suite"]["id"],
        line_items=[{"category": "FINISHES", "cost_amount": 120000.00}],
        target_suite_class="PROCEDURE", power_amps_requested=150,
        authorized_allowance_total=300000.00, landlord_share_pct=0.60)
    assert project["status"] == "CONSTRUCTION"
    assert project["power_amps_drawn"] == 150
    assert fx.read_suite(api, ctx["suite"]["id"])["power_amps_available"] == 50

    validate_error(
        api.transition_ti_project(project["id"], factories.ti_transition_payload("CANCEL"),
                                  LEASING_AGENT),
        ApiErrorId.ERR_INVALID_TI_STATE)
    validate_error(
        api.transition_ti_project(project["id"],
                                  factories.ti_transition_payload("SUBMIT_REVIEWS"),
                                  LEASING_AGENT),
        ApiErrorId.ERR_INVALID_TI_STATE)

    after = fx.read_project(api, project["id"])
    assert after["status"] == "CONSTRUCTION"
    assert after["power_amps_drawn"] == 150
    # A refused cancellation compensates nothing: the drawn amperage stays drawn.
    assert fx.read_suite(api, ctx["suite"]["id"])["power_amps_available"] == 50


def test_ti_review_rejection_compensates_the_already_approved_utility_branch(api):
    """A rejection on one dimension unwinds the other dimension's suite effects.

    "Each approval leaves the project in `IN_REVIEW`, advances the project's `version`, and
    joins: if the **other** dimension already reads `APPROVED`, the same request also moves
    the project to `PERMITTED`."
    "Rejecting either dimension cycles the project `IN_REVIEW → DESIGN` with full
    compensation, so that no drift accumulates across review rounds."
    "The addressed dimension is set to `REJECTED` and the other dimension is reset to
    `NOT_SUBMITTED`."
    "If the other dimension had already been approved, its effects on the suite are
    reversed: an approved shielding branch is compensated by setting the suite's
    `shielding_certified` back to false and its `lead_thickness_mm` back to null, and an
    approved utility branch is compensated by adding `power_amps_drawn` back to the suite's
    `power_amps_available` and resetting `power_amps_drawn` to 0."
    "First, the category rule: a line whose `category` is `SHIELDING` on a project whose
    `target_suite_class` is `IMAGING` is borne entirely by the landlord, so its
    `effective_share_pct` is 1.0000 — the landlord pays 100% of radiation shielding in an
    imaging build-out regardless of anything else the project or the line says."

    Design: Corner/state_machines/ti_review_reject_compensates_the_already_approved_utility_branch
    """
    ctx = fx.drafted_lease(api)
    suite_id = ctx["suite"]["id"]
    project = fx.ti_project_in_review(
        api, ctx["lease"]["id"], suite_id,
        line_items=[{"description": "Lead-lined walls", "category": "SHIELDING",
                     "cost_amount": 88000.00}],
        target_suite_class="IMAGING", lead_thickness_mm=2.5, power_amps_requested=150,
        authorized_allowance_total=500000.00, landlord_share_pct=0.60)
    assert project["shielding_review_status"] == "PENDING"
    assert project["utility_review_status"] == "PENDING"

    approved = validate_success(
        api.review_ti_project(project["id"],
                              factories.ti_review_payload("UTILITY", "APPROVE"),
                              FACILITIES_ENGINEER))
    assert approved["status"] == "IN_REVIEW"
    assert approved["utility_review_status"] == "APPROVED"
    assert approved["power_amps_drawn"] == 150
    assert fx.read_suite(api, suite_id)["power_amps_available"] == 50

    rejected = validate_success(
        api.review_ti_project(project["id"],
                              factories.ti_review_payload(
                                  "SHIELDING", "REJECT",
                                  review_note="Lead detail insufficient at door frames"),
                              FACILITIES_ENGINEER))
    assert rejected["status"] == "DESIGN"
    assert rejected["shielding_review_status"] == "REJECTED"
    assert rejected["utility_review_status"] == "NOT_SUBMITTED"
    assert rejected["power_amps_drawn"] == 0
    assert_project_rollups(rejected, 88000.00, 0.00, 412000.00, 1)

    suite = fx.read_suite(api, suite_id)
    assert suite["power_amps_available"] == 200
    assert suite["shielding_certified"] is False
    assert suite["lead_thickness_mm"] is None


def test_reinstatement_restores_a_suspended_lease_and_its_on_hold_project(api):
    """SUSPENDED_MIX_REVIEW is reversible, but only once the posture has recovered.

    "**Hop 3** fires if and only if hop 2 moved `tenant_mix_posture` to `RESTRICTED`: every
    lease in that building whose status is `DRAFT` or `PENDING_FMV_REVIEW` and whose
    tenant's `affiliation` is `HEALTH_SYSTEM_ANCHOR` or `HEALTH_SYSTEM_AFFILIATED` is
    suspended, processed in `created_at` ascending order."
    "A suspended draft moves `DRAFT → SUSPENDED_MIX_REVIEW`, has its
    `fmv_certification_status` reset to `NOT_STARTED` and advances its `version` by 1; a
    suspended lease already in review moves `PENDING_FMV_REVIEW → SUSPENDED_MIX_REVIEW`,
    has its `fmv_certification_status` reset to `NOT_STARTED`, additionally has
    `fmv_submitted_by_user_id` cleared to null because the submission it recorded is no
    longer live, and advances its `version` by 1."
    "Through the same disposition surface that carries `RETURN_FOR_REVISION`, a
    `ComplianceOfficer` may issue a `REINSTATE` action with a `decision_note`, moving a
    lease `SUSPENDED_MIX_REVIEW → DRAFT`."
    "Reinstatement is admissible only while the building's `tenant_mix_posture` is neither
    `RESTRICTED` nor `FROZEN`; attempting it while the posture is still `RESTRICTED` is
    refused with `ERR_BUILDING_MIX_RESTRICTED`."
    "Reinstatement also unwinds hop 4: every tenant-improvement project on that lease
    sitting in `ON_HOLD`, processed in `created_at` ascending order, returns to the status
    recorded in its `on_hold_from_status`, has that field cleared to null and advances its
    `version` by 1 — a project held from `DESIGN` returns `ON_HOLD → DESIGN`, one held from
    `IN_REVIEW` returns `ON_HOLD → IN_REVIEW`, and one held from `PERMITTED` returns
    `ON_HOLD → PERMITTED`."
    "Reinstatement deliberately leaves `revision_round` untouched, because a suspension was
    never the agent's fault."

    Design: Corner/state_machines/lease_reinstate_restores_suspended_lease_and_its_on_hold_project
    """
    building = fx.register_building(api)
    building_id = building["id"]
    suite_anchor = fx.register_suite(api, building_id, suite_number="301", floor=3,
                                     rentable_sf=10000)
    suite_independent = fx.register_suite(api, building_id, suite_number="302", floor=3,
                                          rentable_sf=5000)
    suite_affiliated = fx.register_suite(api, building_id, suite_number="303", floor=3,
                                         rentable_sf=6000)
    suite_reserve = fx.register_suite(api, building_id, suite_number="304", floor=3,
                                      rentable_sf=5000)
    anchor = fx.register_tenant(api, legal_name="Cedar Health System",
                                affiliation="HEALTH_SYSTEM_ANCHOR",
                                primary_specialty="PRIMARY_CARE")
    independent = fx.register_tenant(api, legal_name="Northgate Digestive PC",
                                     primary_specialty="GASTROENTEROLOGY")
    affiliated = fx.register_tenant(api, legal_name="Cedar Cardiology Associates",
                                    affiliation="HEALTH_SYSTEM_AFFILIATED",
                                    primary_specialty="CARDIOLOGY")
    reserve = fx.register_tenant(api, legal_name="Lakeside Eye Partners PC",
                                 primary_specialty="OPHTHALMOLOGY")

    anchor_lease = fx.draft_lease(api, building_id, suite_anchor["id"], anchor["id"])
    fx.drive_to_active(api, anchor_lease, anchor, advance_clock=False)
    independent_lease = fx.draft_lease(api, building_id, suite_independent["id"],
                                       independent["id"])
    fx.drive_to_active(api, independent_lease, independent, advance_clock=False)
    assert_mix_figures(fx.read_building(api, building_id), 10000, 5000, 15000, 85000,
                       0.6667, "ANCHOR_CONCENTRATED")

    affiliated_lease = fx.draft_lease(api, building_id, suite_affiliated["id"],
                                      affiliated["id"])
    project = fx.open_ti_project(api, affiliated_lease["id"], suite_affiliated["id"],
                                 target_suite_class="PROCEDURE")
    assert project["status"] == "DESIGN"

    reserve_lease = fx.draft_lease(api, building_id, suite_reserve["id"], reserve["id"])
    fx.file_attestation(api, reserve_lease["id"], "SIGNED_LEASE")
    fx.submit_for_review(api, reserve_lease["id"])
    fx.certify(api, reserve_lease["id"])

    # Losing the independent tenant tips the anchor share past 0.7500 and cascades.
    fx.terminate(api, independent_lease["id"], "MUTUAL")
    assert_mix_figures(fx.read_building(api, building_id), 10000, 0, 10000, 90000,
                       1.0000, "RESTRICTED")
    suspended = fx.read_lease(api, affiliated_lease["id"])
    assert suspended["status"] == "SUSPENDED_MIX_REVIEW"
    assert suspended["fmv_certification_status"] == "NOT_STARTED"
    assert suspended["revision_round"] == 0
    held = fx.read_project(api, project["id"])
    assert held["status"] == "ON_HOLD"
    assert held["on_hold_from_status"] == "DESIGN"

    validate_error(
        api.lease_compliance_decision(
            affiliated_lease["id"],
            factories.lease_compliance_decision_payload("REINSTATE", "Mix reviewed"),
            COMPLIANCE_OFFICER),
        ApiErrorId.ERR_BUILDING_MIX_RESTRICTED)
    assert fx.read_lease(api, affiliated_lease["id"])["status"] == "SUSPENDED_MIX_REVIEW"

    fx.execute(api, reserve_lease["id"])
    assert_mix_figures(fx.read_building(api, building_id), 10000, 5000, 15000, 85000,
                       0.6667, "ANCHOR_CONCENTRATED")

    reinstated = validate_success(
        api.lease_compliance_decision(
            affiliated_lease["id"],
            factories.lease_compliance_decision_payload("REINSTATE", "Mix rebalanced"),
            COMPLIANCE_OFFICER))
    assert reinstated["status"] == "DRAFT"
    assert reinstated["fmv_certification_status"] == "NOT_STARTED"
    assert reinstated["revision_round"] == 0
    restored = fx.read_project(api, project["id"])
    assert restored["status"] == "DESIGN"
    assert restored["on_hold_from_status"] is None


def test_suite_returns_from_reserved_to_vacant_when_an_executed_lease_terminates(api):
    """A signed deal that collapses before possession releases its suite without occupying it.

    "It is derived entirely from the lease transitions that reference the suite: `VACANT →
    RESERVED` when a lease over that suite is executed (admissible only when no other lease
    holds the suite in `EXECUTED`, `ACTIVE` or `HOLDOVER`), `RESERVED → OCCUPIED` when that
    lease commences and reaches `ACTIVE`, `OCCUPIED → VACANT` when an active or holdover
    lease terminates, and `RESERVED → VACANT` when an executed lease is terminated before it
    ever commenced."
    "Terminating a lease that was executed but never commenced runs the same hops 1 through
    4, with one difference: hop 1 releases the suite from `RESERVED` rather than from
    `OCCUPIED`, since the tenant never took possession, and `last_vacated_on` is still
    stamped with the clock date."
    "The counted lease set for a building comprises the leases whose `building_id` is that
    building, whose status is `EXECUTED`, `ACTIVE` or `HOLDOVER`, and whose `lease_type` is
    `DIRECT` or `MASTER`."

    Design: Corner/state_machines/suite_returns_from_reserved_to_vacant_when_an_executed_lease_terminates
    """
    ctx = fx.executed_lease(api, lease_overrides={"term_start": "2026-10-01",
                                                  "term_end": "2029-09-30"})
    suite_id = ctx["suite"]["id"]
    assert fx.read_suite(api, suite_id)["occupancy_status"] == "RESERVED"
    assert_mix_figures(fx.read_building(api, ctx["building"]["id"]), 0, 5000, 5000, 95000,
                       0.0000, "BALANCED")

    lease = validate_success(
        api.terminate_lease(ctx["lease"]["id"],
                            factories.terminate_payload("MUTUAL",
                                                        termination_note="Deal collapsed"),
                            PROPERTY_MANAGER))
    assert lease["status"] == "TERMINATED"
    assert lease["terminated_on"] == "2026-08-01"

    suite = fx.read_suite(api, suite_id)
    assert suite["occupancy_status"] == "VACANT"
    assert suite["last_vacated_on"] == "2026-08-01"
    assert_mix_figures(fx.read_building(api, ctx["building"]["id"]), 0, 0, 0, 100000,
                       0.0000, "BALANCED")


def test_active_lease_rolls_to_holdover_on_the_daily_close_and_reprices(api):
    """Passing term_end changes nothing until a close runs; the close then reprices the rent.

    "Advancing the clock changes the reference instant for lease commencement, appraisal
    expiry, invoice aging, the rolling risk window, remediation deadlines and shared-space
    windows — but it changes no entity's status by itself."
    "When a daily close finds the clock date strictly past the `term_end` of a lease in
    status `ACTIVE`, the lease moves `ACTIVE → HOLDOVER`, `holdover_premium_applied` is set
    to true, `effective_base_rent_annual` is recomputed as `certified_base_rent_annual`
    multiplied by 1.50 and rounded half up to 2 decimal places, and `version` advances."
    "The suite stays `OCCUPIED` and the building's tenant mix does not move, because
    `HOLDOVER` is one of the counted statuses."
    "The requested period may not overlap the period of any existing invoice on the same
    lease that is not written off, and it must lie inside the lease term unless the lease
    has rolled into `HOLDOVER`; a violation is `ERR_INVOICE_PERIOD_OVERLAP`."

    Design: Corner/state_machines/active_lease_rolls_to_holdover_on_daily_close_and_reprices
    """
    ctx = fx.active_lease(api, lease_overrides={"term_end": "2027-08-31"})
    lease_id, suite_id = ctx["lease"]["id"], ctx["suite"]["id"]
    assert ctx["lease"]["status"] == "ACTIVE"

    fx.set_clock_date(api, "2027-09-01")
    lease = fx.read_lease(api, lease_id)
    assert lease["status"] == "ACTIVE"
    assert lease["holdover_premium_applied"] is False
    assert_certified_rent_variant(lease, 150000.00, 150000.00)

    validate_success(api.run_daily_close(PORTFOLIO_ADMIN, {"close_note": "Month-end roll"}))
    lease = fx.read_lease(api, lease_id)
    assert lease["status"] == "HOLDOVER"
    assert lease["holdover_premium_applied"] is True
    assert_certified_rent_variant(lease, 150000.00, 150000.00, holdover=True)
    assert_money_equals(lease["effective_base_rent_annual"], 225000.00,
                        "effective_base_rent_annual")
    assert fx.read_suite(api, suite_id)["occupancy_status"] == "OCCUPIED"
    assert_mix_figures(fx.read_building(api, ctx["building"]["id"]), 0, 5000, 5000, 95000,
                       0.0000, "BALANCED")

    # A period beyond term_end is admissible precisely because the lease is in HOLDOVER.
    invoice = validate_success(
        api.create_rent_invoice(
            lease_id,
            factories.create_rent_invoice_payload("2027-09-01", "2027-09-30", "2027-10-01"),
            PROPERTY_MANAGER),
        201)
    assert invoice["status"] == "ISSUED"
    assert_invoice_breakdown(invoice, expected_invoice_total(225000.00, 9.60, 5000))
    assert_money_equals(invoice["total_amount"], 22750.00, "total_amount")


def test_booked_shared_space_completes_on_the_daily_close_after_its_window_ends(api):
    """The close completes only the bookings whose window has already closed.

    "The booking is created in `BOOKED` and its `is_after_hours` flag is derived: it is true
    when any part of the requested window falls outside the space's operating window, and
    false only when the whole window sits inside it."
    "Separately, each daily close moves every booking still in `BOOKED` whose `window_end`
    is at or before the clock to `COMPLETED`, advancing `version`; `CANCELLED` and
    `COMPLETED` are both terminal, and both leave the seat-load input set."
    "Bookings can be listed and narrowed by `shared_space_id`, by `lease_id` and by
    `status`, which is the only channel through which cascade-cancelled bookings become
    visible."

    Design: Corner/state_machines/booked_shared_space_completes_on_daily_close_after_window_end
    """
    ctx = fx.drafted_lease(api)
    lease_id = ctx["lease"]["id"]
    space = fx.register_shared_space(api, ctx["building"]["id"],
                                     name="Level 2 Waiting Room",
                                     space_type="WAITING_ROOM", capacity_seats=24)
    fx.file_attestation(api, lease_id, "SPACE_SHARING_SCHEDULE")

    early = fx.book(api, space["id"], lease_id, "2026-08-05T09:00:00Z",
                    "2026-08-05T11:00:00Z", 4)
    later = fx.book(api, space["id"], lease_id, "2026-08-10T09:00:00Z",
                    "2026-08-10T11:00:00Z", 4)
    assert early["status"] == "BOOKED"
    assert early["is_after_hours"] is False
    assert later["status"] == "BOOKED"

    fx.set_clock_date(api, "2026-08-06")
    validate_success(api.run_daily_close(PORTFOLIO_ADMIN, {"close_note": "Daily sweep"}))

    assert _booking(api, early["id"])["status"] == "COMPLETED"
    assert _booking(api, later["id"])["status"] == "BOOKED"

    rows, meta = validate_paginated(
        api.list_bookings(LEASING_AGENT, {"lease_id": lease_id, "status": "BOOKED"}))
    assert_total_count(meta, 1)
    assert [row["id"] for row in rows] == [later["id"]]


def test_qualified_appraisal_expires_on_the_close_and_marks_the_lease_stale(api):
    """An opinion ageing out unwinds the certification's figures but not the lease status.

    "When a daily close finds the clock date past a `QUALIFIED` appraisal's `expires_on`,
    the row moves `QUALIFIED → EXPIRED`, its `is_controlling` flag is cleared, and its
    `version` advances."
    "If the expiring row was the controlling opinion behind a lease sitting in
    `FMV_CERTIFIED`, that lease's `fmv_certification_status` becomes `STALE` and its
    `version` advances — but its `status` is deliberately left at `FMV_CERTIFIED`, because
    an appraisal simply ageing out is not a compliance finding and opens no case."
    "For a physician-owned tenant, the controlling appraisal supplies a second band — 90% of
    `opinion_midpoint_psf` as its floor and 110% of that midpoint as its ceiling, each
    rounded half up to 2 decimal places — and the two bands are then intersected:
    `certified_fmv_floor_psf` is the **greater** of the appraisal floor and the published
    floor, and `certified_fmv_ceiling_psf` is the **lesser** of the appraisal ceiling and
    the published ceiling."
    "Before certification — that is, while `fmv_certification_status` reads `NOT_STARTED`,
    `PENDING` or `STALE` — the lease is carried at the rate card:
    `provisional_base_rent_annual` is the published per-square-foot figure (market rate card
    plus the suite class premium) multiplied by the suite's `rentable_sf`, rounded half up
    to 2 decimal places; `effective_base_rent_annual`, the figure actually billed, equals
    it; and `certified_base_rent_annual`, `fmv_variance_annual` and `fmv_variance_pct` are
    all null."

    Design: Corner/state_machines/qualified_appraisal_expires_on_close_and_marks_the_lease_stale
    """
    ctx = fx.drafted_lease(
        api,
        suite_overrides={"suite_class": "IMAGING", "rentable_sf": 8000,
                         "shielding_certified": True, "lead_thickness_mm": 2.5},
        tenant_overrides={"is_physician_owned": True, "primary_specialty": "RADIOLOGY"},
        lease_overrides={"base_rent_psf_annual": 38.00})
    lease_id = ctx["lease"]["id"]
    appraisal = fx.file_appraisal(api, lease_id, ctx["lease"]["version"],
                                  opinion_low_psf=38.00, opinion_high_psf=42.00)
    assert_money_equals(appraisal["opinion_midpoint_psf"], 40.00, "opinion_midpoint_psf")
    appraisal = fx.qualify_appraisal(api, appraisal["id"])
    assert appraisal["status"] == "QUALIFIED"
    assert appraisal["expires_on"] == "2027-07-15"

    fx.submit_for_review(api, lease_id)
    lease = fx.certify(api, lease_id)
    assert lease["status"] == "FMV_CERTIFIED"
    assert lease["fmv_certification_status"] == "CERTIFIED"
    provisional = published_psf(30.00, "IMAGING") * 8000
    assert_money_equals(provisional, 292000.00, "published annual figure")
    assert_certified_band(lease, 36.00, 41.98)
    assert_certified_rent_variant(lease, 304000.00, 292000.00)
    assert_money_equals(lease["fmv_variance_annual"], 12000.00, "fmv_variance_annual")
    assert_share_equals(lease["fmv_variance_pct"], 0.0411, "fmv_variance_pct")
    assert _appraisal_rows(api, lease_id)[0]["is_controlling"] is True

    fx.set_clock_date(api, "2027-07-16")
    validate_success(api.run_daily_close(PORTFOLIO_ADMIN, {"close_note": "Appraisal sweep"}))

    expired = _appraisal_rows(api, lease_id)[0]
    assert expired["status"] == "EXPIRED"
    assert expired["is_controlling"] is False
    stale = fx.read_lease(api, lease_id)
    assert stale["status"] == "FMV_CERTIFIED"
    assert stale["fmv_certification_status"] == "STALE"
    assert_provisional_rent_variant(stale, 292000.00)
    # Ageing out is not a compliance finding, so no case is opened against the tenant.
    assert _case_rows(api, ctx["tenant"]["id"]) == []


def test_lapsed_remediation_plan_reopens_the_case_with_reopen_count_one(api):
    """The plan deadline is tested strictly, so the due date itself is still safe.

    "A manually opened case begins in `OPEN` with `reopen_count` at 0, `opened_on` stamped
    with the clock date, `opened_by_user_id` taken from the `X-User-ID` header,
    `risk_score_at_open` frozen to the tenant's score **under the requested variant**, and
    `remediation_due_on` set to the clock date plus 30 days."
    "Although `severity` is accepted on the request, the stored value is always derived from
    `risk_score_at_open`: a frozen score of at least 90 is `HIGH`, at least 45 is `MEDIUM`,
    and anything lower is `LOW`."
    "Opening a case by hand always puts the tenant on `WATCH` and advances the tenant's
    `version`, whatever the score says."
    "`REMEDIATION_PLAN` is admissible only from `OPEN`, requires a non-empty
    `remediation_summary`, records that text, resets `remediation_due_on` to the clock date
    plus 30 days, advances `version`, and moves the case `OPEN → REMEDIATION_PLANNED`."
    "When a daily close finds a case in `REMEDIATION_PLANNED` whose `remediation_due_on` is
    strictly earlier than the clock date, the case moves `REMEDIATION_PLANNED → OPEN`,
    `reopen_count` increases by 1, the tenant's `compliance_watch_status` is forced back to
    `WATCH` with the tenant's `version` advanced, and the case's own `version` advances."

    Design: Corner/state_machines/lapsed_remediation_plan_reopens_the_case_with_reopen_count_one
    """
    tenant = fx.register_tenant(api)
    case = validate_success(
        api.create_compliance_case(
            factories.create_compliance_case_payload(
                tenant["id"], case_type="SUBLEASE_DOCUMENTATION",
                basis="Sublease consent not evidenced", severity="HIGH"),
            COMPLIANCE_OFFICER),
        201)
    assert case["status"] == "OPEN"
    assert case["reopen_count"] == 0
    assert case["opened_on"] == "2026-08-01"
    assert case["opened_by_user_id"] == "compliance-001"
    assert case["severity"] == "LOW"
    assert case["remediation_due_on"] == "2026-08-31"
    assert fx.read_tenant(api, tenant["id"])["compliance_watch_status"] == "WATCH"

    planned = validate_success(
        api.transition_compliance_case(
            case["id"],
            factories.case_transition_payload(
                "REMEDIATION_PLAN",
                remediation_summary="Consent letter to be countersigned by the health system"),
            COMPLIANCE_OFFICER))
    assert planned["status"] == "REMEDIATION_PLANNED"
    assert planned["remediation_due_on"] == "2026-08-31"
    assert planned["reopen_count"] == 0

    # On the due date itself the plan has not lapsed: the test is strictly earlier.
    fx.set_clock_date(api, "2026-08-31")
    fx.run_daily_close(api)
    on_due_date = _case_rows(api, tenant["id"])[0]
    assert on_due_date["status"] == "REMEDIATION_PLANNED"
    assert on_due_date["reopen_count"] == 0

    fx.set_clock_date(api, "2026-09-01")
    validate_success(api.run_daily_close(PORTFOLIO_ADMIN, {"close_note": "Remediation sweep"}))
    reopened = _case_rows(api, tenant["id"])[0]
    assert reopened["status"] == "OPEN"
    assert reopened["reopen_count"] == 1
    assert reopened["remediation_summary"] == (
        "Consent letter to be countersigned by the health system")
    assert fx.read_tenant(api, tenant["id"])["compliance_watch_status"] == "WATCH"


def test_utility_review_refuses_a_request_above_the_suites_available_amperage(api):
    """A refused utility approval leaves its dimension PENDING and the panel untouched.

    "Approving the utility dimension requires the suite's `power_amps_available` to be at
    least the project's `power_amps_requested`, refused as
    `ERR_INSUFFICIENT_UTILITY_CAPACITY`, and requires the suite's `medical_gas_available` to
    be true whenever `medical_gas_requested` is true, refused as
    `ERR_SHIELDING_CERTIFICATION_MISSING`; it then sets `utility_review_status` to
    `APPROVED`, reduces the suite's `power_amps_available` by `power_amps_requested`, records
    the amount actually drawn in the project's `power_amps_drawn`, and advances the suite's
    `version`."
    "Each approval leaves the project in `IN_REVIEW`, advances the project's `version`, and
    joins: if the **other** dimension already reads `APPROVED`, the same request also moves
    the project to `PERMITTED`."

    Design: Corner/state_machines/ti_utility_review_rejects_a_request_above_the_suites_amperage
    """
    ctx = fx.drafted_lease(api)
    suite_id = ctx["suite"]["id"]
    project = fx.ti_project_in_review(
        api, ctx["lease"]["id"], suite_id,
        line_items=[{"description": "Dedicated infusion panel", "category": "POWER",
                     "cost_amount": 60000.00}],
        target_suite_class="INFUSION", power_amps_requested=250,
        authorized_allowance_total=400000.00, landlord_share_pct=0.50)
    assert project["status"] == "IN_REVIEW"
    assert fx.read_suite(api, suite_id)["power_amps_available"] == 200

    validate_error(
        api.review_ti_project(project["id"],
                              factories.ti_review_payload("UTILITY", "APPROVE"),
                              FACILITIES_ENGINEER),
        ApiErrorId.ERR_INSUFFICIENT_UTILITY_CAPACITY)

    after = fx.read_project(api, project["id"])
    assert after["status"] == "IN_REVIEW"
    assert after["utility_review_status"] == "PENDING"
    assert after["power_amps_drawn"] == 0
    assert fx.read_suite(api, suite_id)["power_amps_available"] == 200

    # The other dimension is genuinely independent and still available.
    shielded = validate_success(
        api.review_ti_project(project["id"],
                              factories.ti_review_payload("SHIELDING", "APPROVE"),
                              FACILITIES_ENGINEER))
    assert shielded["status"] == "IN_REVIEW"
    assert shielded["shielding_review_status"] == "APPROVED"
    assert shielded["utility_review_status"] == "PENDING"


def test_commencement_is_refused_before_term_start_and_admitted_on_the_start_date(api):
    """Commencement waits for the clock to reach term_start, to the day.

    "Commencement is the `PropertyManager`'s act, accepts an optional `commencement_note`,
    and moves a lease `EXECUTED → ACTIVE`."
    "The clock date must have reached `term_start`; an earlier attempt is refused with
    `ERR_TERM_NOT_YET_STARTED`."
    "On success the suite moves `RESERVED → OCCUPIED` with its `version` advanced, the
    building's tenant mix is recomputed with the building's `version` advanced, and the
    lease's `version` advances."

    Design: Corner/state_machines/commence_before_term_start_rejected_then_accepted_on_the_start_date
    """
    ctx = fx.executed_lease(api)
    lease_id, suite_id = ctx["lease"]["id"], ctx["suite"]["id"]
    assert ctx["lease"]["term_start"] == "2026-09-01"

    validate_error(
        api.commence_lease(lease_id, {"commencement_note": "Early keys"}, PROPERTY_MANAGER),
        ApiErrorId.ERR_TERM_NOT_YET_STARTED)
    assert fx.read_suite(api, suite_id)["occupancy_status"] == "RESERVED"

    fx.set_clock_date(api, "2026-08-31")
    validate_error(
        api.commence_lease(lease_id, {"commencement_note": "One day early"},
                           PROPERTY_MANAGER),
        ApiErrorId.ERR_TERM_NOT_YET_STARTED)
    assert fx.read_lease(api, lease_id)["status"] == "EXECUTED"
    assert fx.read_suite(api, suite_id)["occupancy_status"] == "RESERVED"

    fx.set_clock_date(api, "2026-09-01")
    lease = validate_success(
        api.commence_lease(lease_id, {"commencement_note": "Possession taken"},
                           PROPERTY_MANAGER))
    assert lease["status"] == "ACTIVE"
    assert fx.read_suite(api, suite_id)["occupancy_status"] == "OCCUPIED"


def test_termination_revokes_parking_and_cancels_the_bookings_still_standing(api):
    """The dependents cascade reaches active allocations and BOOKED rows, nothing else.

    "Every parking allocation on the lease still in status `ACTIVE`, processed in
    `created_at` ascending order, moves to `REVOKED` with `revoked_on` set to the clock date,
    after which the building's `staff_allocated_stalls`, `patient_allocated_stalls` and
    `unallocated_stalls` are recomputed."
    "Every shared-space booking on the lease still in status `BOOKED`, processed in
    `created_at` ascending order, moves to `CANCELLED` with `cancellation_source` recorded as
    `LEASE_TERMINATION`."
    "`after_hours_authorized` is cleared to false."
    "Separately, each daily close moves every booking still in `BOOKED` whose `window_end` is
    at or before the clock to `COMPLETED`, advancing `version`; `CANCELLED` and `COMPLETED`
    are both terminal, and both leave the seat-load input set."

    Design: Corner/state_machines/terminate_revokes_parking_and_cancels_only_future_bookings
    """
    ctx = fx.executed_lease(api)
    lease_id, building_id = ctx["lease"]["id"], ctx["building"]["id"]
    space = fx.register_shared_space(api, building_id, name="Level 2 Waiting Room",
                                     space_type="WAITING_ROOM", capacity_seats=24)
    fx.file_attestation(api, lease_id, "SPACE_SHARING_SCHEDULE")
    settled = fx.book(api, space["id"], lease_id, "2026-08-05T09:00:00Z",
                      "2026-08-05T11:00:00Z", 4)
    fx.set_clock_date(api, "2026-08-06")
    fx.run_daily_close(api)
    assert _booking(api, settled["id"])["status"] == "COMPLETED"

    fx.set_clock_date(api, "2026-09-01")
    fx.commence(api, lease_id)
    staff = fx.allocate_stalls(api, building_id, lease_id, "STAFF", 20)
    patient = fx.allocate_stalls(api, building_id, lease_id, "PATIENT", 30)
    standing = fx.book(api, space["id"], lease_id, "2026-09-02T09:00:00Z",
                       "2026-09-02T11:00:00Z", 6)
    lease = fx.authorize_after_hours(api, lease_id, True)
    assert lease["after_hours_authorized"] is True
    assert_parking_counters(fx.read_building(api, building_id), 20, 30, 350)

    lease = validate_success(
        api.terminate_lease(lease_id, factories.terminate_payload("MUTUAL"),
                            PROPERTY_MANAGER))
    assert lease["status"] == "TERMINATED"
    assert lease["after_hours_authorized"] is False

    for allocation_id in (staff["id"], patient["id"]):
        allocation = _allocation(api, allocation_id)
        assert allocation["status"] == "REVOKED"
        assert allocation["revoked_on"] == "2026-09-01"
    assert_parking_counters(fx.read_building(api, building_id), 0, 0, 400)

    cancelled = _booking(api, standing["id"])
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancellation_source"] == "LEASE_TERMINATION"
    # The already-completed booking is no longer BOOKED, so the cascade leaves it alone.
    assert _booking(api, settled["id"])["status"] == "COMPLETED"


def test_master_lease_termination_terminates_its_executed_sublease(api):
    """A collapsing master drags its executed sublease, both suites and the mix with it.

    "And where the terminating lease's `lease_type` is `MASTER`, every sublease naming it
    through `master_lease_id` that stands in `EXECUTED`, `ACTIVE` or `HOLDOVER` is itself
    terminated, in `created_at` ascending order, inheriting the master's `termination_reason`
    and running its own hop 1 and hop 2 — so a hospital master lease collapsing takes its
    subtenants' suites and the building's mix figures with it."
    "Leases of type `SUBLEASE` are deliberately excluded: the master lease already counts
    that area, and counting both would double-count the same square feet."
    "Both routes back to `VACANT` stamp `last_vacated_on` with the clock date and advance the
    suite's `version`."
    "`anchor_share_pct` is `anchor_rentable_sf` divided by `leased_rentable_sf`, rounded half
    up to 4 decimal places; when `leased_rentable_sf` is zero the share reads 0.0000 rather
    than being undefined."

    Design: Corner/state_machines/master_lease_termination_terminates_its_executed_sublease
    """
    building = fx.register_building(api)
    building_id = building["id"]
    master_suite = fx.register_suite(api, building_id, suite_number="401", floor=4,
                                     rentable_sf=12000)
    sub_suite = fx.register_suite(api, building_id, suite_number="402", floor=4,
                                  rentable_sf=5000)
    health_system = fx.register_tenant(api, legal_name="Cedar Health System",
                                       affiliation="HEALTH_SYSTEM_ANCHOR",
                                       primary_specialty="PRIMARY_CARE")
    subtenant = fx.register_tenant(api, legal_name="Northgate Digestive PC",
                                   primary_specialty="GASTROENTEROLOGY")

    master = fx.draft_lease(api, building_id, master_suite["id"], health_system["id"],
                            lease_type="MASTER", term_start="2026-09-01",
                            term_end="2031-08-31", base_rent_psf_annual=28.00)
    master = fx.drive_to_active(api, master, health_system)
    assert master["status"] == "ACTIVE"

    sublease = fx.draft_lease(api, building_id, sub_suite["id"], subtenant["id"],
                              lease_type="SUBLEASE", master_lease_id=master["id"],
                              term_start="2027-01-01", term_end="2030-12-31")
    fx.file_attestation(api, sublease["id"], "SIGNED_LEASE")
    fx.file_attestation(api, sublease["id"], "MASTER_LEASE_CONSENT")
    fx.submit_for_review(api, sublease["id"])
    fx.certify(api, sublease["id"])
    sublease = fx.execute(api, sublease["id"])
    assert sublease["status"] == "EXECUTED"
    assert fx.read_suite(api, master_suite["id"])["occupancy_status"] == "OCCUPIED"
    assert fx.read_suite(api, sub_suite["id"])["occupancy_status"] == "RESERVED"
    # The sublease area is not counted: only the master's 12000 sf is on the mix.
    assert_mix_figures(fx.read_building(api, building_id), 12000, 0, 12000, 88000,
                       1.0000, "RESTRICTED")

    terminated_master = validate_success(
        api.terminate_lease(master["id"], factories.terminate_payload("MUTUAL"),
                            PROPERTY_MANAGER))
    assert terminated_master["status"] == "TERMINATED"

    fallen = fx.read_lease(api, sublease["id"])
    assert fallen["status"] == "TERMINATED"
    assert fallen["termination_reason"] == "MUTUAL"
    assert fallen["terminated_on"] == "2026-09-01"

    for suite_id in (master_suite["id"], sub_suite["id"]):
        suite = fx.read_suite(api, suite_id)
        assert suite["occupancy_status"] == "VACANT"
        assert suite["last_vacated_on"] == "2026-09-01"
    assert_mix_figures(fx.read_building(api, building_id), 0, 0, 0, 100000,
                       0.0000, "BALANCED")
