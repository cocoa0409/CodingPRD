"""Lifecycle transitions along the certified pre-owned spine.

The programme is a chain of small state machines that push each other: a checklist
template moves from draft to published and retires its predecessors, an inspection
opens in draft and either passes, needs repairs, fails or is voided by a superseding
one, a certification is submitted, priced and later withdrawn, a listing is published
and force-withdrawn, a complaint is answered by a re-inspection whose own verdict
resolves it, and a vehicle walks two independent axes that gate each other at a single
declared point. This module exercises those transitions: the legal moves and their full
side-effect sets, the self-loops that legitimately repeat, and the backwards moves that
every terminal row must refuse with the error naming its own state.
"""

from test_helpers import (
    ADMIN,
    ADMIN_USER_ID,
    AGE_SURCHARGE_CENTS_PER_YEAR,
    ApiErrorId,
    BASE_FEE_CENTS,
    CLOCK_EPOCH,
    INSPECTION_SLOT_MINUTES,
    LISTING_REMOVAL_SLA_HOURS,
    MILEAGE_SURCHARGE_CENTS_PER_10K,
    REINSPECTION_DEADLINE_DAYS,
    WARRANTY_EXTENSION_MILES,
    WARRANTY_TOTAL_CAP_MILES,
    active_certification,
    add_item,
    adjudication_payload,
    approve_certification,
    assert_instant_equals,
    audit_finding_payload,
    audit_samples_of,
    checklist_item_payload,
    claim_adjudication_payload,
    clean_attempt_rows,
    complete_reconditioning,
    complete_reconditioning_payload,
    create_certification_payload,
    create_claim_payload,
    create_complaint_payload,
    create_draft_template,
    create_inspection_payload,
    create_listing,
    create_listing_payload,
    create_template,
    create_vehicle,
    days_between,
    decertify_payload,
    deny_claim,
    file_claim,
    file_complaint,
    history_event_payload,
    iso_shift,
    item_b1_payload,
    item_p1_payload,
    item_s1_payload,
    open_inspection,
    open_inspection_for,
    publish_template,
    read_certification,
    read_complaint,
    read_dealer,
    read_inspection,
    read_vehicle,
    record_finding,
    record_history_event,
    record_results,
    reconditioning_item_for,
    reimbursable_for,
    result_row,
    results_payload,
    sample_certification,
    submit_inspection,
    syndicate_listing,
    syndicate_payload,
    syndicated_listing,
    validate_error,
    validate_paginated,
    validate_success,
    vehicle_version,
    waive_reconditioning,
    waive_reconditioning_payload,
)

# §3.7 priced for the canonical car: the 89900-cent base fee, one chargeable age
# year at 12500, and two whole 10000-mile blocks at 9000 each, a 30500-cent
# surcharge that sits under the 31465-cent cap, with the zero-percent volume tier.
_CANONICAL_FEE_CHARGED_CENTS = (
    BASE_FEE_CENTS + AGE_SURCHARGE_CENTS_PER_YEAR + 2 * MILEAGE_SURCHARGE_CENTS_PER_10K
)

# The per-item reconditioning ceiling the canonical `S1` safety point declares.
_S1_ITEM_CEILING_CENTS = 200000


def _read_template(api, template_id, headers=None):
    return validate_success(api.get_checklist_template(template_id, headers or ADMIN))


def _draft_with_critical_point(api, effective_from, headers=None):
    """Author a draft template carrying one CRITICAL point, so publishing it is legal."""
    template = create_template(api, headers=headers, effective_from=effective_from)
    add_item(api, template["id"], item_p1_payload(), headers=headers)
    return template


def _technician_row(api, dealer_id, technician_id, headers=None):
    """The roster listing under a dealer is the discovery channel for a technician."""
    rows, _ = validate_paginated(api.list_technicians(dealer_id, headers or ADMIN))
    matches = [row for row in rows if row["id"] == technician_id]
    assert matches, "the dealer's roster must list the technician it registered"
    return matches[0]


def _reconditioning_walk(api, program):
    """Drive one inspection to RECONDITIONING_REQUIRED with a CRITICAL and a MAJOR repair."""
    walk = open_inspection_for(api, program)
    record_results(
        api,
        walk.inspection_id,
        program.technician_headers,
        [
            result_row("P1", "PASS"),
            result_row("S1", "FAIL"),
            result_row("B1", "FAIL", measured_value=2.0),
        ],
    )
    walk.inspection = submit_inspection(api, walk.inspection_id, program.dealer_headers)
    return walk


def test_publishing_retires_only_templates_effective_on_or_before_the_new_one(
    api, admin_headers
):
    """Publication sweeps the catalogue one way, so a back-dated checklist retires nothing.

    PRD §3.1: "Publishing moves a template `DRAFT → PUBLISHED`"
    PRD §3.1: "every *other* template that is currently `PUBLISHED`"
    PRD §3.1: "is moved `PUBLISHED → RETIRED`"
    PRD §3.1: "`RETIRED` is terminal for a template."

    Design: Corner/state_machines/checklist_template_publish_retires_earlier_published_template
    """
    earlier = _draft_with_critical_point(api, "2026-01-01", admin_headers)
    later = _draft_with_critical_point(api, "2026-06-01", admin_headers)
    back_dated = _draft_with_critical_point(api, "2025-01-01", admin_headers)

    # Creation, one added point and the publication are three mutations of the row.
    first = publish_template(api, earlier["id"], admin_headers)
    assert first["status"] == "PUBLISHED"
    assert first["version"] == 3
    assert_instant_equals(first["published_at"], CLOCK_EPOCH, "published_at")

    second = publish_template(api, later["id"], admin_headers)
    assert second["status"] == "PUBLISHED"
    assert second["version"] == 3

    retired = _read_template(api, earlier["id"], admin_headers)
    assert retired["status"] == "RETIRED"
    assert retired["version"] == first["version"] + 1
    assert_instant_equals(retired["published_at"], CLOCK_EPOCH, "published_at")

    third = publish_template(api, back_dated["id"], admin_headers)
    assert third["status"] == "PUBLISHED"
    assert third["version"] == 3

    survivor = _read_template(api, later["id"], admin_headers)
    assert survivor["status"] == "PUBLISHED"
    assert survivor["version"] == second["version"]

    still_retired = _read_template(api, earlier["id"], admin_headers)
    assert still_retired["status"] == "RETIRED"
    assert still_retired["version"] == retired["version"]


def test_template_publication_demands_a_point_and_a_critical_point(api, admin_headers):
    """An empty checklist and a checklist of one major point are both unpublishable.

    PRD §3.1: "A new template is born in `DRAFT` with `published_at` null"
    PRD §3.1: "`ERR_TEMPLATE_NOT_PUBLISHABLE` when the template carries no points at all"
    PRD §2.10: "a checklist template is publishable only when it carries at least one point"

    Design: Corner/state_machines/template_publish_without_critical_item_rejected
    """
    template = create_template(api, headers=admin_headers)
    born = _read_template(api, template["id"], admin_headers)
    assert born["status"] == "DRAFT"
    assert born["published_at"] is None
    assert born["point_count"] == 0
    assert born["critical_item_count"] == 0

    validate_error(
        api.publish_checklist_template(template["id"], admin_headers),
        ApiErrorId.ERR_TEMPLATE_NOT_PUBLISHABLE,
    )
    empty = _read_template(api, template["id"], admin_headers)
    assert empty["status"] == "DRAFT"
    assert empty["published_at"] is None
    assert empty["point_count"] == 0

    add_item(api, template["id"], item_b1_payload(), headers=admin_headers)
    validate_error(
        api.publish_checklist_template(template["id"], admin_headers),
        ApiErrorId.ERR_TEMPLATE_NOT_PUBLISHABLE,
    )
    major_only = _read_template(api, template["id"], admin_headers)
    assert major_only["status"] == "DRAFT"
    assert major_only["published_at"] is None
    assert major_only["point_count"] == 1
    assert major_only["critical_item_count"] == 0

    add_item(api, template["id"], item_s1_payload(), headers=admin_headers)
    published = publish_template(api, template["id"], admin_headers)
    assert published["status"] == "PUBLISHED"
    assert published["point_count"] == 2
    assert published["critical_item_count"] == 1
    assert_instant_equals(published["published_at"], CLOCK_EPOCH, "published_at")


def test_new_inspection_opens_in_draft_with_frozen_snapshots(
    api, program, vehicle, auditor_headers
):
    """Opening an inspection zeroes every counter, freezes two snapshots, and moves the car.

    PRD §3.3: "A successful open creates the inspection in `DRAFT` with `attempt_count` 0"
    PRD §3.3: "Two derived snapshots are frozen at this moment and never recomputed"
    PRD §3.3: "`slot_end_at` equal to `started_at` plus that slot length"
    PRD §3.3: "`cpo_state` goes `NOT_CERTIFIED → CERTIFICATION_PENDING`"

    Design: Corner/state_machines/inspection_initial_state_is_draft_with_zero_attempts
    """
    started_at = program.next_start()
    inspection = open_inspection(
        api,
        program.dealer_headers,
        vehicle["id"],
        program.technician_id,
        program.template_id,
        started_at=started_at,
    )

    assert inspection["status"] == "DRAFT"
    assert inspection["purpose"] == "INITIAL"
    assert inspection["attempt_count"] == 0
    assert inspection["version"] == 1
    for counter in (
        "recorded_item_count",
        "failed_critical_count",
        "failed_recon_count",
        "total_recon_cost_cents",
        "total_reimbursable_cents",
    ):
        assert inspection[counter] == 0, f"{counter} starts at its floor"
    assert inspection["submitted_at"] is None
    assert inspection["failure_reason"] is None
    assert inspection["parent_inspection_id"] is None
    assert inspection["complaint_id"] is None
    assert_instant_equals(
        inspection["slot_end_at"],
        iso_shift(started_at, minutes=INSPECTION_SLOT_MINUTES),
        "slot_end_at",
    )
    assert inspection["vehicle_age_days_at_inspection"] == days_between(
        vehicle["in_service_date"], started_at[:10]
    )
    assert inspection["dealer_id"] == program.dealer_id

    moved = read_vehicle(api, vehicle["id"])
    assert moved["cpo_state"] == "CERTIFICATION_PENDING"
    assert moved["inventory_state"] == "IN_INVENTORY"
    assert moved["version"] == vehicle["version"] + 1

    rows, meta = validate_paginated(api.list_results(inspection["id"], auditor_headers))
    assert rows == []
    assert meta["total_count"] == 0


def test_inspection_against_an_unpublished_checklist_is_refused(
    api, program, vehicle, admin_headers
):
    """A complete but still draft checklist cannot back an inspection, and the car does not move.

    PRD §3.1: "naming a template that is `DRAFT` or `RETIRED` when opening an inspection"
    PRD §3.2: "A new vehicle starts with `cpo_state` `NOT_CERTIFIED`"

    Design: Corner/state_machines/inspection_on_draft_template_rejected
    """
    draft = create_draft_template(api)
    assert draft["status"] == "DRAFT"

    validate_error(
        api.create_inspection(
            create_inspection_payload(
                vehicle["id"],
                program.technician_id,
                draft["id"],
                started_at=program.next_start(),
            ),
            program.dealer_headers,
        ),
        ApiErrorId.ERR_TEMPLATE_NOT_PUBLISHED,
    )

    untouched = read_vehicle(api, vehicle["id"])
    assert untouched["cpo_state"] == "NOT_CERTIFIED"
    assert untouched["version"] == vehicle["version"]

    rows, meta = validate_paginated(
        api.list_inspections(admin_headers, params={"vehicle_id": vehicle["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_backwards_moves_on_a_live_certification_are_refused(
    api, program, active_walk, admin_headers, auditor_headers
):
    """Every row of a completed walk refuses the move it has already made, naming its own state.

    PRD §3.1: "Adding a point to a template that has left `DRAFT` is rejected"
    PRD §3.4: "Recording results on an inspection that has already reached `PASSED`"
    PRD §3.7: "The certification must be `SUBMITTED`; adjudicating one in any other status"
    PRD §3.6: "The named inspection must be `PASSED`; naming one in any other status is rejected"
    PRD §3.8: "a certification may hold at most one listing per channel that is not `WITHDRAWN`"

    Design: Corner/state_machines/wrong_state_transitions_rejected_on_live_certification
    """
    published = _read_template(api, program.template_id, admin_headers)
    assert published["status"] == "PUBLISHED"
    assert published["point_count"] == 3

    validate_error(
        api.add_checklist_item(
            program.template_id,
            checklist_item_payload(
                item_code="X9",
                category="INTERIOR",
                severity="MINOR",
                pass_criteria="added after publication",
            ),
            admin_headers,
        ),
        ApiErrorId.ERR_TEMPLATE_NOT_DRAFT,
    )
    validate_error(
        api.publish_checklist_template(program.template_id, admin_headers),
        ApiErrorId.ERR_TEMPLATE_NOT_DRAFT,
    )
    assert _read_template(api, program.template_id, admin_headers)["point_count"] == 3

    passed = read_inspection(api, active_walk.inspection_id)
    assert passed["status"] == "PASSED"
    assert passed["attempt_count"] == 1
    validate_error(
        api.record_results(
            active_walk.inspection_id,
            results_payload(clean_attempt_rows()),
            program.technician_headers,
        ),
        ApiErrorId.ERR_INSPECTION_TERMINAL,
    )
    validate_error(
        api.submit_inspection(active_walk.inspection_id, program.dealer_headers),
        ApiErrorId.ERR_INSPECTION_TERMINAL,
    )
    unmoved = read_inspection(api, active_walk.inspection_id)
    assert unmoved["attempt_count"] == 1
    assert unmoved["submitted_at"] == passed["submitted_at"]

    validate_error(
        api.adjudicate_certification(
            active_walk.certification_id, adjudication_payload("APPROVE"), admin_headers
        ),
        ApiErrorId.ERR_CERTIFICATION_NOT_SUBMITTED,
    )
    live = read_certification(api, active_walk.certification_id)
    assert live["status"] == "ACTIVE"
    assert live["fee_charged_cents"] == _CANONICAL_FEE_CHARGED_CENTS

    listing = create_listing(api, program.dealer_headers, active_walk.certification_id)
    validate_error(
        api.create_listing(
            create_listing_payload(active_walk.certification_id, price_cents=2400000),
            program.dealer_headers,
        ),
        ApiErrorId.ERR_DUPLICATE_RESOURCE,
    )

    unfinished = open_inspection_for(
        api, program, technician_id=program.other_technician_id
    )
    assert unfinished.inspection["status"] == "DRAFT"
    validate_error(
        api.create_certification(
            create_certification_payload(
                unfinished.vehicle_id,
                unfinished.inspection_id,
                vehicle_version(api, unfinished.vehicle_id, program.dealer_headers),
            ),
            program.dealer_headers,
        ),
        ApiErrorId.ERR_INSPECTION_NOT_PASSED,
    )

    rows, meta = validate_paginated(
        api.list_listings(active_walk.certification_id, auditor_headers)
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [listing["id"]]

    dealer = read_dealer(api, program.dealer_id)
    assert dealer["lifetime_submitted_count"] == 1


def test_terminal_rows_lock_down_after_a_post_audit_failure(
    api, program, admin_headers, auditor_headers, advocate_headers
):
    """A post-audit failure credits the fee and leaves every touched row unable to move again.

    PRD §3.10: "sets its `fee_credited_cents` equal to its `fee_charged_cents`"
    PRD §3.10: "The certification must be `ACTIVE` or `UNDER_AUDIT`"
    PRD §3.8: "syndicating a withdrawn listing is rejected with `ERR_LISTING_WITHDRAWN`"
    PRD §2.10: "the state-conflict identifier for that resource type"
    PRD §3.9: "adjudicating one already `APPROVED` or `DENIED` is rejected"
    PRD §3.10: "a finding on one already `PASSED` or `FAILED` is rejected"
    PRD §3.9: "The certification must be live, otherwise `ERR_CERTIFICATION_NOT_ACTIVE`."

    Design: Corner/state_machines/wrong_state_transitions_rejected_on_closed_records
    """
    walk = active_certification(api, program)
    claim = file_claim(api, program.dealer_headers, walk.certification_id)
    deny_claim(api, claim["id"], "NOT_COVERED_COMPONENT")
    listing = syndicated_listing(api, walk)
    sample = sample_certification(api, walk.certification_id)
    record_finding(api, sample["id"], "FAIL", "DOCUMENTATION_MISSING")

    decertified = read_certification(api, walk.certification_id)
    assert decertified["status"] == "DECERTIFIED"
    assert decertified["decertification_reason"] == "POST_AUDIT_FAIL"
    assert decertified["fee_credited_cents"] == _CANONICAL_FEE_CHARGED_CENTS

    validate_error(
        api.decertify_certification(
            walk.certification_id, decertify_payload("ADMIN_ACTION"), admin_headers
        ),
        ApiErrorId.ERR_CERTIFICATION_TERMINAL,
    )
    still_audit_failed = read_certification(api, walk.certification_id)
    assert still_audit_failed["decertification_reason"] == "POST_AUDIT_FAIL"

    # The guard value is the certification's true current generation, so the refusal
    # can only come from the listing's own state.
    validate_error(
        api.syndicate_listing(
            listing["id"],
            syndicate_payload(still_audit_failed["version"]),
            program.dealer_headers,
        ),
        ApiErrorId.ERR_LISTING_WITHDRAWN,
    )

    validate_error(
        api.adjudicate_warranty_claim(
            claim["id"], claim_adjudication_payload("APPROVE"), admin_headers
        ),
        ApiErrorId.ERR_CLAIM_ALREADY_ADJUDICATED,
    )
    claim_rows, claim_meta = validate_paginated(
        api.list_warranty_claims(walk.certification_id, admin_headers)
    )
    assert claim_meta["total_count"] == 1
    assert claim_rows[0]["status"] == "DENIED"
    assert claim_rows[0]["approved_amount_cents"] == 0

    validate_error(
        api.record_audit_finding(
            sample["id"], audit_finding_payload("PASS"), auditor_headers
        ),
        ApiErrorId.ERR_AUDIT_SAMPLE_ALREADY_REVIEWED,
    )
    reviewed = audit_samples_of(api, walk.certification_id, auditor_headers)
    assert [row["status"] for row in reviewed] == ["FAILED"]
    assert reviewed[0]["finding_code"] == "DOCUMENTATION_MISSING"

    validate_error(
        api.create_listing(
            create_listing_payload(walk.certification_id, channel="DEALER_SITE"),
            program.dealer_headers,
        ),
        ApiErrorId.ERR_CERTIFICATION_NOT_ACTIVE,
    )
    validate_error(
        api.create_warranty_claim(
            create_claim_payload(walk.certification_id, component_category="POWERTRAIN"),
            program.dealer_headers,
        ),
        ApiErrorId.ERR_CERTIFICATION_NOT_ACTIVE,
    )
    validate_error(
        api.create_complaint(
            create_complaint_payload(
                walk.certification_id, category="UNDISCLOSED_DAMAGE"
            ),
            advocate_headers,
        ),
        ApiErrorId.ERR_CERTIFICATION_NOT_ACTIVE,
    )

    dealer = read_dealer(api, program.dealer_id)
    assert dealer["fee_credited_cents_total"] == _CANONICAL_FEE_CHARGED_CENTS
    assert dealer["fee_balance_cents"] == 0
    assert dealer["audit_fail_count"] == 1
    assert dealer["privilege_status"] == "ACTIVE"

    listing_rows, listing_meta = validate_paginated(
        api.list_listings(walk.certification_id, auditor_headers)
    )
    assert listing_meta["total_count"] == 1
    assert listing_rows[0]["status"] == "WITHDRAWN"
    complaint_rows, complaint_meta = validate_paginated(
        api.list_complaints(walk.certification_id, admin_headers)
    )
    assert complaint_rows == []
    assert complaint_meta["total_count"] == 0


def test_resyndication_refreshes_while_repeat_history_events_are_refused(api, program):
    """Republishing an advertisement is a legal self-loop; repeating a disposition event is not.

    PRD §3.8: "or `SYNDICATED → SYNDICATED` on a refresh"
    PRD §3.8: "records `syndicated_snapshot_version` as the certification's `version`"
    PRD §3.2: "is rejected with `ERR_VEHICLE_HISTORY_EVENT_INVALID`"

    Design: Corner/state_machines/repeat_transitions_idempotent_or_rejected
    """
    walk = active_certification(api, program)
    listing = create_listing(api, program.dealer_headers, walk.certification_id)
    before = read_certification(api, walk.certification_id)

    first = syndicate_listing(
        api, listing["id"], program.dealer_headers, before["version"]
    )
    assert first["status"] == "SYNDICATED"
    assert first["syndicated_snapshot_version"] == before["version"] + 1

    republished_from = read_certification(api, walk.certification_id)
    assert republished_from["version"] == before["version"] + 1

    second = syndicate_listing(
        api, listing["id"], program.dealer_headers, republished_from["version"]
    )
    assert second["status"] == "SYNDICATED"
    assert second["version"] == first["version"] + 1
    assert_instant_equals(second["syndicated_at"], CLOCK_EPOCH, "syndicated_at")
    assert (
        second["syndicated_snapshot_version"]
        == first["syndicated_snapshot_version"] + 1
    )

    uncertified = create_vehicle(api)
    sale_reading = uncertified["odometer_miles"] + 400
    sold = record_history_event(
        api,
        uncertified["id"],
        "RETAIL_SOLD",
        program.dealer_headers,
        odometer_miles=sale_reading,
    )
    assert sold["inventory_state"] == "RETAIL_SOLD"
    assert sold["odometer_miles"] == sale_reading
    assert sold["last_history_event_type"] == "RETAIL_SOLD"

    validate_error(
        api.create_history_event(
            uncertified["id"],
            history_event_payload("RETAIL_SOLD", odometer_miles=sale_reading + 100),
            program.dealer_headers,
        ),
        ApiErrorId.ERR_VEHICLE_HISTORY_EVENT_INVALID,
    )
    absorbed_nothing = read_vehicle(api, uncertified["id"])
    assert absorbed_nothing["odometer_miles"] == sale_reading
    assert absorbed_nothing["cpo_state"] == "NOT_CERTIFIED"

    validate_error(
        api.create_history_event(
            walk.vehicle_id,
            history_event_payload("RETURNED_TO_INVENTORY"),
            program.dealer_headers,
        ),
        ApiErrorId.ERR_VEHICLE_HISTORY_EVENT_INVALID,
    )
    assert read_vehicle(api, walk.vehicle_id)["inventory_state"] == "IN_INVENTORY"


def test_retail_sale_decertifies_the_badge_and_keeps_the_fee(
    api, program, auditor_headers, advocate_headers
):
    """One recorded sale withdraws the badge, the advert and the complaint, but refunds nothing.

    PRD §3.2: "because the programme keeps the fee on a retail sale"
    PRD §3.10: "every other reason leaves `fee_credited_cents` at 0"
    PRD §3.8: "a `removal_due_at` equal to `withdrawn_at` plus the programme's takedown window"
    PRD §3.11: "moves to `DISMISSED` with `resolved_at` set to the logical clock"
    PRD §3.2: "`fee_balance_cents` is the billed total minus the credited total"

    Design: Corner/state_machines/retail_sale_cascade_decertifies_and_keeps_fee
    """
    walk = active_certification(api, program)
    listing = syndicated_listing(api, walk)
    complaint = file_complaint(
        api, walk.certification_id, category="MARKETING_MISREPRESENTATION"
    )
    priced = read_certification(api, walk.certification_id)
    sale_reading = walk.vehicle["odometer_miles"] + 400

    sold = record_history_event(
        api,
        walk.vehicle_id,
        "RETAIL_SOLD",
        program.dealer_headers,
        odometer_miles=sale_reading,
    )
    assert sold["inventory_state"] == "RETAIL_SOLD"
    assert sold["cpo_state"] == "DECERTIFIED"
    assert sold["certified_certification_id"] is None
    assert sold["odometer_miles"] == sale_reading
    assert_instant_equals(sold["decertified_at"], CLOCK_EPOCH, "decertified_at")

    withdrawn_badge = read_certification(api, walk.certification_id)
    assert withdrawn_badge["status"] == "DECERTIFIED"
    assert withdrawn_badge["decertification_reason"] == "RETAIL_SOLD"
    assert_instant_equals(
        withdrawn_badge["decertified_at"], CLOCK_EPOCH, "decertified_at"
    )
    assert withdrawn_badge["fee_charged_cents"] == _CANONICAL_FEE_CHARGED_CENTS
    assert withdrawn_badge["fee_credited_cents"] == 0
    assert withdrawn_badge["warranty_end_date"] == priced["warranty_end_date"]
    assert withdrawn_badge["warranty_end_miles"] == priced["warranty_end_miles"]
    assert withdrawn_badge["retention_expires_at"] == priced["retention_expires_at"]

    rows, meta = validate_paginated(
        api.list_listings(walk.certification_id, auditor_headers)
    )
    assert meta["total_count"] == 1
    pulled = rows[0]
    assert pulled["id"] == listing["id"]
    assert pulled["status"] == "WITHDRAWN"
    assert pulled["withdrawal_reason"] == "CERTIFICATION_DECERTIFIED"
    assert_instant_equals(pulled["withdrawn_at"], CLOCK_EPOCH, "withdrawn_at")
    assert_instant_equals(
        pulled["removal_due_at"],
        iso_shift(CLOCK_EPOCH, hours=LISTING_REMOVAL_SLA_HOURS),
        "removal_due_at",
    )

    dismissed = read_complaint(api, complaint["id"], advocate_headers)
    assert dismissed["status"] == "DISMISSED"
    assert_instant_equals(dismissed["resolved_at"], CLOCK_EPOCH, "resolved_at")

    dealer = read_dealer(api, program.dealer_id)
    assert dealer["fee_billed_cents_total"] == _CANONICAL_FEE_CHARGED_CENTS
    assert dealer["fee_credited_cents_total"] == 0
    assert dealer["fee_balance_cents"] == _CANONICAL_FEE_CHARGED_CENTS
    assert dealer["active_certification_count"] == 0
    assert dealer["lifetime_activated_count"] == 1


def test_approval_waits_for_the_car_to_return_to_inventory(
    api, program, submitted_walk, admin_headers
):
    """A sale under a pending submission blocks approval until the car comes back.

    PRD §3.7: "The vehicle's `inventory_state` must be `IN_INVENTORY`"
    PRD §3.2: "It deliberately leaves `cpo_state` alone"
    PRD §3.7: "`warranty_end_miles` is the smaller of that figure and the absolute odometer cap"

    Design: Corner/state_machines/approval_after_retail_sale_not_in_inventory_rejected
    """
    sale_reading = submitted_walk.vehicle["odometer_miles"] + 100
    sold = record_history_event(
        api,
        submitted_walk.vehicle_id,
        "RETAIL_SOLD",
        program.dealer_headers,
        odometer_miles=sale_reading,
    )
    assert sold["inventory_state"] == "RETAIL_SOLD"
    assert sold["cpo_state"] == "CERTIFICATION_PENDING"
    assert read_certification(api, submitted_walk.certification_id)["status"] == "SUBMITTED"

    validate_error(
        api.adjudicate_certification(
            submitted_walk.certification_id,
            adjudication_payload("APPROVE"),
            admin_headers,
        ),
        ApiErrorId.ERR_VEHICLE_NOT_IN_INVENTORY,
    )
    blocked = read_certification(api, submitted_walk.certification_id)
    assert blocked["status"] == "SUBMITTED"
    assert blocked["activated_at"] is None
    assert blocked["fee_charged_cents"] == 0

    returned = record_history_event(
        api,
        submitted_walk.vehicle_id,
        "RETURNED_TO_INVENTORY",
        program.dealer_headers,
    )
    assert returned["inventory_state"] == "IN_INVENTORY"
    assert returned["cpo_state"] == "CERTIFICATION_PENDING"

    approved = approve_certification(api, submitted_walk.certification_id)
    assert approved["status"] == "ACTIVE"
    assert_instant_equals(approved["activated_at"], CLOCK_EPOCH, "activated_at")
    assert approved["fee_charged_cents"] == _CANONICAL_FEE_CHARGED_CENTS

    worksheet_reading = read_inspection(api, submitted_walk.inspection_id)[
        "odometer_at_inspection"
    ]
    assert approved["warranty_end_miles"] == min(
        worksheet_reading + WARRANTY_EXTENSION_MILES, WARRANTY_TOTAL_CAP_MILES
    )


def test_superseding_inspection_voids_its_parent(
    api, program, open_walk, auditor_headers, admin_headers
):
    """Naming the in-flight inspection as parent is the only way to open a second one on the car.

    PRD §3.3: "the request is rejected with `ERR_INSPECTION_ALREADY_OPEN`"
    PRD §3.3: "it is `RE_INSPECTION` when either `parent_inspection_id` or `complaint_id`"
    PRD §3.5: "moves to `VOIDED` with a `failure_reason` of `SUPERSEDED_BY_REINSPECTION`"
    PRD §3.4: "Earlier attempts remain visible forever."

    Design: Corner/state_machines/superseding_inspection_voids_parent_inspection
    """
    record_results(
        api, open_walk.inspection_id, program.technician_headers, [result_row("P1", "PASS")]
    )
    assert read_inspection(api, open_walk.inspection_id)["status"] == "IN_PROGRESS"

    validate_error(
        api.create_inspection(
            create_inspection_payload(
                open_walk.vehicle_id,
                program.technician_id,
                program.template_id,
                started_at=program.next_start(),
                odometer_at_inspection=open_walk.vehicle["odometer_miles"] + 50,
            ),
            program.dealer_headers,
        ),
        ApiErrorId.ERR_INSPECTION_ALREADY_OPEN,
    )

    child = open_inspection(
        api,
        program.dealer_headers,
        open_walk.vehicle_id,
        program.technician_id,
        program.template_id,
        started_at=program.next_start(),
        odometer_at_inspection=open_walk.vehicle["odometer_miles"] + 50,
        parent_inspection_id=open_walk.inspection_id,
    )
    assert child["purpose"] == "RE_INSPECTION"
    assert child["parent_inspection_id"] == open_walk.inspection_id
    assert child["complaint_id"] is None
    assert child["status"] == "DRAFT"
    assert child["attempt_count"] == 0

    voided = read_inspection(api, open_walk.inspection_id, auditor_headers)
    assert voided["status"] == "VOIDED"
    assert voided["failure_reason"] == "SUPERSEDED_BY_REINSPECTION"
    assert voided["submitted_at"] is None

    rows, meta = validate_paginated(
        api.list_results(
            open_walk.inspection_id, auditor_headers, params={"attempt_index": 1}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["item_code"] == "P1"

    assert read_vehicle(api, open_walk.vehicle_id)["cpo_state"] == "CERTIFICATION_PENDING"
    inspector = _technician_row(
        api, program.dealer_id, program.technician_id, admin_headers
    )
    assert inspector["completed_inspection_count"] == 0


def test_waiver_and_completion_close_repairs_differently(
    api, program, admin_headers, auditor_headers
):
    """A waived repair costs the programme nothing; a completed one is reimbursed at its share.

    PRD §3.5: "A waived item keeps `actual_cost_cents` null and `reimbursable_cents` 0."
    PRD §3.5: "`closed_by_user_id` to the acting `X-User-ID`"
    PRD §3.5: "round that product half up to whole cents"
    PRD §3.5: "Waived repairs contribute nothing and never enter the sum"
    PRD §3.5: "closing an item already `COMPLETED` or `WAIVED` is `ERR_RECONDITIONING_ITEM_CLOSED`"

    Design: Corner/state_machines/reconditioning_item_waived_by_administrator
    """
    walk = _reconditioning_walk(api, program)
    assert walk.inspection["status"] == "RECONDITIONING_REQUIRED"
    assert walk.inspection["failed_recon_count"] == 2

    major = reconditioning_item_for(api, walk.inspection_id, "B1")
    critical = reconditioning_item_for(api, walk.inspection_id, "S1")
    assert major["severity"] == "MAJOR"
    assert major["status"] == "REQUIRED"
    assert critical["severity"] == "CRITICAL"
    assert critical["status"] == "REQUIRED"

    waiver_reason = "pad thickness within OEM tolerance after re-measurement"
    waived = waive_reconditioning(api, major["id"], waiver_reason, admin_headers)
    assert waived["status"] == "WAIVED"
    assert waived["actual_cost_cents"] is None
    assert waived["reimbursable_cents"] == 0
    assert waived["waiver_reason"] == waiver_reason
    assert waived["closed_by_user_id"] == ADMIN_USER_ID
    assert_instant_equals(waived["completed_at"], CLOCK_EPOCH, "completed_at")

    expected_reimbursement = reimbursable_for(50000, _S1_ITEM_CEILING_CENTS)
    completed = complete_reconditioning(
        api, critical["id"], 50000, program.other_technician_headers
    )
    assert completed["status"] == "COMPLETED"
    assert completed["actual_cost_cents"] == 50000
    assert completed["reimbursable_cents"] == expected_reimbursement
    assert completed["closed_by_user_id"] == program.other_technician_id
    assert_instant_equals(completed["completed_at"], CLOCK_EPOCH, "completed_at")

    totals = read_inspection(api, walk.inspection_id, auditor_headers)
    assert totals["total_recon_cost_cents"] == 50000
    assert totals["total_reimbursable_cents"] == expected_reimbursement
    assert totals["status"] == "RECONDITIONING_REQUIRED"

    validate_error(
        api.complete_reconditioning_item(
            major["id"],
            complete_reconditioning_payload(40000),
            program.other_technician_headers,
        ),
        ApiErrorId.ERR_RECONDITIONING_ITEM_CLOSED,
    )
    still_waived = reconditioning_item_for(api, walk.inspection_id, "B1")
    assert still_waived["status"] == "WAIVED"
    assert still_waived["actual_cost_cents"] is None


def test_critical_repair_can_never_be_waived_or_closed_by_the_wrong_role(
    api, program, admin_headers, auditor_headers
):
    """A critical repair must be performed, and each resolution belongs to exactly one role.

    PRD §3.5: "an attempt to waive one is rejected with `ERR_CRITICAL_RECONDITIONING_NOT_WAIVABLE`"
    PRD §2.1: "a `resolution` of `COMPLETED` is `InspectionTechnician`-exclusive"
    PRD §2.1: "is rejected with `ERR_ROLE_FORBIDDEN` even though both roles appear"

    Design: Corner/state_machines/waive_critical_reconditioning_item_rejected
    """
    walk = _reconditioning_walk(api, program)
    major = reconditioning_item_for(api, walk.inspection_id, "B1")
    critical = reconditioning_item_for(api, walk.inspection_id, "S1")

    validate_error(
        api.complete_reconditioning_item(
            critical["id"],
            waive_reconditioning_payload("customer declined the airbag module replacement"),
            admin_headers,
        ),
        ApiErrorId.ERR_CRITICAL_RECONDITIONING_NOT_WAIVABLE,
    )
    assert reconditioning_item_for(api, walk.inspection_id, "S1")["status"] == "REQUIRED"

    validate_error(
        api.complete_reconditioning_item(
            major["id"],
            waive_reconditioning_payload("technician judged the pads serviceable"),
            program.other_technician_headers,
        ),
        ApiErrorId.ERR_ROLE_FORBIDDEN,
    )
    validate_error(
        api.complete_reconditioning_item(
            major["id"], complete_reconditioning_payload(40000), admin_headers
        ),
        ApiErrorId.ERR_ROLE_FORBIDDEN,
    )

    for item_code in ("S1", "B1"):
        outstanding = reconditioning_item_for(api, walk.inspection_id, item_code)
        assert outstanding["status"] == "REQUIRED"
        assert outstanding["reimbursable_cents"] == 0

    unchanged = read_inspection(api, walk.inspection_id, auditor_headers)
    assert unchanged["status"] == "RECONDITIONING_REQUIRED"
    assert unchanged["total_reimbursable_cents"] == 0
    assert unchanged["total_recon_cost_cents"] == 0


def test_clean_reinspection_upholds_the_complaint_and_keeps_the_badge(
    api, program, advocate_headers, admin_headers
):
    """A complaint is resolved by the re-inspection's own verdict, and a clean one holds the badge.

    PRD §3.11: "a derived `reinspection_deadline_at` equal to `filed_at` plus five days"
    PRD §3.11: "moves the complaint `OPEN → REINSPECTION_ORDERED`"
    PRD §3.11: "opening a re-inspection leaves the vehicle's `cpo_state` at `CERTIFIED`"
    PRD §3.11: "the complaint moves `REINSPECTION_ORDERED → RESOLVED_UPHELD`"
    PRD §3.11: "one already ordered, resolved, or dismissed is rejected"

    Design: Corner/state_machines/complaint_reinspection_upheld_resolution
    """
    walk = active_certification(api, program)
    complaint = file_complaint(
        api, walk.certification_id, category="INSPECTION_ITEM_FAILURE"
    )
    assert complaint["status"] == "OPEN"
    assert_instant_equals(complaint["filed_at"], CLOCK_EPOCH, "filed_at")
    assert_instant_equals(
        complaint["reinspection_deadline_at"],
        iso_shift(CLOCK_EPOCH, days=REINSPECTION_DEADLINE_DAYS),
        "reinspection_deadline_at",
    )
    assert complaint["reinspection_ordered_at"] is None
    assert complaint["resolved_at"] is None

    priced = read_certification(api, walk.certification_id)

    reinspection = open_inspection(
        api,
        program.dealer_headers,
        walk.vehicle_id,
        program.other_technician_id,
        program.template_id,
        started_at=CLOCK_EPOCH,
        complaint_id=complaint["id"],
    )
    assert reinspection["purpose"] == "RE_INSPECTION"
    assert reinspection["complaint_id"] == complaint["id"]
    assert reinspection["parent_inspection_id"] is None

    ordered = read_complaint(api, complaint["id"], advocate_headers)
    assert ordered["status"] == "REINSPECTION_ORDERED"
    assert_instant_equals(
        ordered["reinspection_ordered_at"], CLOCK_EPOCH, "reinspection_ordered_at"
    )
    assert read_vehicle(api, walk.vehicle_id)["cpo_state"] == "CERTIFIED"

    record_results(
        api,
        reinspection["id"],
        program.other_technician_headers,
        clean_attempt_rows(),
    )
    closed = submit_inspection(api, reinspection["id"], program.dealer_headers)
    assert closed["status"] == "PASSED"
    reinspector = _technician_row(
        api, program.dealer_id, program.other_technician_id, admin_headers
    )
    assert reinspector["completed_inspection_count"] == 1

    upheld = read_complaint(api, complaint["id"], advocate_headers)
    assert upheld["status"] == "RESOLVED_UPHELD"
    assert_instant_equals(upheld["resolved_at"], CLOCK_EPOCH, "resolved_at")

    intact = read_certification(api, walk.certification_id)
    assert intact["status"] == "ACTIVE"
    assert intact["fee_charged_cents"] == _CANONICAL_FEE_CHARGED_CENTS
    assert intact["warranty_end_date"] == priced["warranty_end_date"]
    assert intact["warranty_end_miles"] == priced["warranty_end_miles"]

    validate_error(
        api.create_inspection(
            create_inspection_payload(
                walk.vehicle_id,
                program.other_technician_id,
                program.template_id,
                started_at=program.next_start(),
                complaint_id=complaint["id"],
            ),
            program.dealer_headers,
        ),
        ApiErrorId.ERR_COMPLAINT_NOT_OPEN,
    )


def test_failed_reinspection_decertifies_the_complained_about_certification(
    api, program, advocate_headers, auditor_headers
):
    """A failed re-inspection resolves the complaint against the dealer and unwinds the badge.

    PRD §3.5: "A car that fails an uncurable critical point is out"
    PRD §3.5: "the `failure_reason` is set to `CRITICAL_ITEM_FAIL`"
    PRD §3.11: "the complaint moves `REINSPECTION_ORDERED → RESOLVED_DECERTIFIED`"
    PRD §3.11: "`decertification_reason` `COMPLAINT_REINSPECTION_FAIL`"
    PRD §3.11: "moves the vehicle's `cpo_state` to `DECERTIFIED`"

    Design: Corner/state_machines/complaint_reinspection_failure_cascade_decertifies
    """
    walk = active_certification(api, program)
    listing = syndicated_listing(api, walk)
    complaint = file_complaint(
        api, walk.certification_id, category="UNDISCLOSED_DAMAGE"
    )
    reinspection = open_inspection(
        api,
        program.dealer_headers,
        walk.vehicle_id,
        program.other_technician_id,
        program.template_id,
        started_at=CLOCK_EPOCH,
        complaint_id=complaint["id"],
    )
    record_results(
        api,
        reinspection["id"],
        program.other_technician_headers,
        [
            result_row("P1", "FAIL"),
            result_row("S1", "PASS"),
            result_row("B1", "PASS", measured_value=8.0),
        ],
    )

    failed = submit_inspection(api, reinspection["id"], program.dealer_headers)
    assert failed["status"] == "FAILED"
    assert failed["failure_reason"] == "CRITICAL_ITEM_FAIL"
    assert_instant_equals(failed["submitted_at"], CLOCK_EPOCH, "submitted_at")

    repairs, repair_meta = validate_paginated(
        api.list_reconditioning_items(reinspection["id"], auditor_headers)
    )
    assert repairs == []
    assert repair_meta["total_count"] == 0

    resolved = read_complaint(api, complaint["id"], advocate_headers)
    assert resolved["status"] == "RESOLVED_DECERTIFIED"
    assert_instant_equals(resolved["resolved_at"], CLOCK_EPOCH, "resolved_at")

    decertified = read_certification(api, walk.certification_id)
    assert decertified["status"] == "DECERTIFIED"
    assert decertified["decertification_reason"] == "COMPLAINT_REINSPECTION_FAIL"
    assert decertified["fee_credited_cents"] == 0

    rows, meta = validate_paginated(
        api.list_listings(walk.certification_id, auditor_headers)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == listing["id"]
    assert rows[0]["status"] == "WITHDRAWN"
    assert rows[0]["withdrawal_reason"] == "CERTIFICATION_DECERTIFIED"
    assert_instant_equals(
        rows[0]["removal_due_at"],
        iso_shift(CLOCK_EPOCH, hours=LISTING_REMOVAL_SLA_HOURS),
        "removal_due_at",
    )

    car = read_vehicle(api, walk.vehicle_id, auditor_headers)
    assert car["cpo_state"] == "DECERTIFIED"
    assert car["certified_certification_id"] is None
    assert car["inventory_state"] == "IN_INVENTORY"

    dealer = read_dealer(api, program.dealer_id)
    assert dealer["fee_balance_cents"] == _CANONICAL_FEE_CHARGED_CENTS
    assert dealer["active_certification_count"] == 0
