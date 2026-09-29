"""What each lifecycle move does besides changing a status.

Close-out clearing an obligation, a teardown that ends children without spawning
new ones, a cascade hop that is conditional on who the individual is, and an
accommodation walked through its provisioning window.
"""

from test_helpers import (
    HR_ADMIN,
    PRIVACY_OFFICER,
    VENDOR_MANAGER,
    accommodation_payload,
    accommodations_for_subject,
    assert_asset_state,
    assert_instant_equals,
    assert_program_state,
    assert_two_decimal_value,
    baseline_with_active_asset,
    create_consent,
    create_data_subject,
    create_program,
    create_vendor,
    create_vendor_contract,
    read_asset,
    read_consent,
    read_program,
    read_subject,
    set_clock,
    validate_paginated,
    validate_success,
    vendor_operated_active_asset,
)

CERTIFICATE_REF = "cert-clockpoint-0001"


def test_closing_out_a_terminated_contract_clears_the_deletion_obligation(api):
    """The certificate is stored and the obligation stops weighing on posture.

    PRD §2.6: "The **open deletion obligations** are those vendor contracts,
    reachable through the program's vendors, whose status is `TERMINATED` and whose
    `deletion_certificate_ref` is still null; their count is published as
    `open_deletion_obligation_count`."

    PRD §3.2: "Successful close-out stores the certificate reference, recomputes
    `open_deletion_obligation_count` and recomputes `posture` — typically the step
    that lifts a program back out of `FROZEN`."

    PRD §3.2: "Four clauses carry point values: thirty-five points for
    `prohibits_sale`, twenty-five points for `restricts_disclosure`, thirty points
    for `requires_deletion_on_termination`, and ten points for a deletion deadline
    that is at most thirty days."

    All four clauses are present and the attestation has been received, so the
    unpenalized score is the full one hundred; the termination stamps stay exactly
    where the termination put them, since close-out does not re-time the obligation
    it discharges.

    Design: Corner/state_machines/contract_closeout_stores_certificate_and_clears_the_deletion_obligation
    """
    program = create_program(api)
    vendor = create_vendor(api, program["id"], attestation_status="RECEIVED")
    contract = create_vendor_contract(api, vendor["id"], target_status="TERMINATED")

    assert_program_state(
        read_program(api, program["id"]),
        open_deletion_obligation_count=1,
        posture="RESTRICTED",
    )
    assert_instant_equals(contract["terminated_at"], "2026-08-01T00:00:00.000Z", "terminated_at")
    assert_instant_equals(
        contract["deletion_deadline_at"], "2026-08-31T00:00:00.000Z", "deletion_deadline_at"
    )

    set_clock(api, "2026-08-31T00:00:00Z")

    closed = validate_success(
        api.transition_vendor_contract(
            contract["id"],
            {"to_status": "CLOSED_OUT", "deletion_certificate_ref": CERTIFICATE_REF},
            VENDOR_MANAGER,
        )
    )

    assert closed["status"] == "CLOSED_OUT"
    assert closed["deletion_certificate_ref"] == CERTIFICATE_REF
    assert_instant_equals(closed["terminated_at"], "2026-08-01T00:00:00.000Z", "terminated_at")
    assert_instant_equals(
        closed["deletion_deadline_at"], "2026-08-31T00:00:00.000Z", "deletion_deadline_at"
    )
    assert_two_decimal_value(closed["compliance_score"], 100.00, "compliance_score")

    assert_program_state(
        read_program(api, program["id"]),
        open_deletion_obligation_count=0,
        posture="OPEN",
    )


def test_decommissioning_ends_live_children_without_spawning_replacements(api):
    """The teardown expires and ends, but creates nothing.

    PRD §3.5: "`GATED` → `DECOMMISSIONED` is always permitted, and that path is a
    full teardown: `templates_destroyed_at` is stamped from the current logical
    clock; every consent record for the point whose status is `SOLICITED`, `GRANTED`
    or `RESOLICIT_REQUIRED` transitions to `EXPIRED`, and **no** accommodation is
    auto-created for any of those expiries because the collection point being
    bypassed no longer exists; every accommodation for the point whose status is
    `REQUESTED`, `PROVISIONED` or `ACTIVE` transitions to `ENDED`; and the program's
    `gated_asset_count`, `consent_gap_count`, inventory completeness and `posture`
    are all recomputed."

    PRD §2.9: "`consent_gap_count` on a collection point is the count of its consent
    records whose status is `SOLICITED`, `RESOLICIT_REQUIRED` or `EXPIRED` — a
    `DECLINED` record and a `REVOKED` record are lawful outcomes and are explicitly
    **not** gaps, and a registered data subject who has no consent record at all is
    likewise not a gap until a record is actually solicited."

    PRD §2.6: "`consent_gap_count` on the program is the sum of the per-point
    `consent_gap_count` values across those of its collection points whose status is
    `ACTIVE` or `GATED`."

    PRD §3.5: "The denominator is every collection point of the program whose status
    is not `DECOMMISSIONED`; when that set is empty the figure is exactly `100.00` by
    convention rather than an undefined division."

    One individual had enrolled and one had refused. The refusal is already terminal
    and is left alone; the enrollment expires and counts as a gap on the point, yet
    the point has left the program's own gap scope, so the program comes out clean.

    Design: Corner/state_machines/asset_decommission_expires_consents_and_ends_accommodations_without_spawning_new_ones
    """
    ctx = baseline_with_active_asset(api, activation_clock="2026-08-15T00:00:00Z")
    enrolled = create_data_subject(api, ctx["program_id"], ctx["jurisdiction_id"], "EMP-0001")
    refuser = create_data_subject(api, ctx["program_id"], ctx["jurisdiction_id"], "EMP-0002")
    granted = create_consent(
        api,
        enrolled["id"],
        ctx["asset_id"],
        target_status="GRANTED",
        written_release_acknowledged=True,
        signature_ref="sig-emp1",
    )
    declined = create_consent(api, refuser["id"], ctx["asset_id"], target_status="DECLINED")
    validate_success(api.transition_asset(ctx["asset_id"], {"to_status": "GATED"}, PRIVACY_OFFICER))

    torn_down = validate_success(
        api.transition_asset(ctx["asset_id"], {"to_status": "DECOMMISSIONED"}, PRIVACY_OFFICER)
    )

    assert torn_down["status"] == "DECOMMISSIONED"
    assert_instant_equals(
        torn_down["templates_destroyed_at"], "2026-08-15T00:00:00.000Z", "templates_destroyed_at"
    )
    assert read_consent(api, granted["id"])["status"] == "EXPIRED"
    assert read_consent(api, declined["id"])["status"] == "DECLINED"

    rows, meta = validate_paginated(api.list_accommodations(HR_ADMIN, {"asset_id": ctx["asset_id"]}))
    assert meta["total_count"] == 1, "no accommodation was created for the expiry"
    assert rows[0]["origin"] == "AUTO_DECLINE"
    assert rows[0]["status"] == "ENDED"
    assert not [row for row in rows if row["origin"] == "AUTO_CONSENT_EXPIRY"]

    assert_asset_state(
        read_asset(api, ctx["asset_id"]), enrolled_subject_count=0, consent_gap_count=1
    )
    assert_program_state(
        read_program(api, ctx["program_id"]),
        gated_asset_count=0,
        consent_gap_count=0,
        inventory_completeness_pct=100.00,
        posture="OPEN",
    )


def test_terminating_a_contract_spawns_no_accommodation_for_a_shopper(api):
    """The fourth hop of the termination cascade is conditional on who was enrolled.

    PRD §3.2: "The contract's `terminated_at` is stamped from the current logical
    clock and its `deletion_deadline_at` is set to `terminated_at` plus
    `deletion_deadline_days`."

    PRD §3.2: "**Hop 4**: because those consents expired, each expired consent whose
    data subject has a `subject_type` of `EMPLOYEE` spawns one alternative
    accommodation in `REQUESTED` status with `origin` set to `AUTO_CONSENT_EXPIRY`.
    Consents belonging to `CUSTOMER` subjects spawn nothing."

    PRD §2.9: "`enrollment_status` on a data subject is derived in a strict priority
    order: it is `OPTED_OUT` if any of that subject's consent records is `DECLINED`
    or `REVOKED` and none is `GRANTED`; otherwise `ENROLLED` if any is `GRANTED`;
    otherwise `ALTERNATIVE` if any of the subject's accommodations is `PROVISIONED`
    or `ACTIVE`; otherwise `NOT_ENROLLED`."

    The shopper's consent still expires with the lane, but an expiry is not a
    refusal and no bypass is provisioned, so the individual falls all the way back to
    not being enrolled at all.

    Design: Corner/state_machines/cascade_a_spawns_no_accommodation_for_customer_subjects
    """
    ctx = vendor_operated_active_asset(
        api,
        program_overrides={"org_type": "RETAILER"},
        notice_overrides={"audience": "CUSTOMER"},
        vendor_overrides={"name": "LaneVision Analytics"},
        asset_overrides={
            "system_category": "CUSTOMER_FACING",
            "modality": "FACE_GEOMETRY",
            "subject_class": "CUSTOMER",
            "template_storage_location": "lane-vault-01",
        },
        activation_clock="2026-08-15T00:00:00Z",
    )
    shopper = create_data_subject(
        api,
        ctx["program_id"],
        ctx["jurisdiction_id"],
        "LOY-0001",
        subject_type="CUSTOMER",
        preferred_locale="es",
    )
    consent = create_consent(
        api,
        shopper["id"],
        ctx["asset_id"],
        target_status="GRANTED",
        locale="es",
        written_release_acknowledged=True,
        signature_ref="sig-loy1",
    )

    terminated = validate_success(
        api.transition_vendor_contract(
            ctx["contract_id"], {"to_status": "TERMINATED"}, VENDOR_MANAGER
        )
    )

    assert terminated["status"] == "TERMINATED"
    assert_instant_equals(terminated["terminated_at"], "2026-08-15T00:00:00.000Z", "terminated_at")
    assert_instant_equals(
        terminated["deletion_deadline_at"], "2026-09-14T00:00:00.000Z", "deletion_deadline_at"
    )

    assert_asset_state(read_asset(api, ctx["asset_id"]), status="GATED")
    assert read_consent(api, consent["id"])["status"] == "EXPIRED"
    assert accommodations_for_subject(api, shopper["id"]) == []

    reread = read_subject(api, shopper["id"])
    assert reread["enrollment_status"] == "NOT_ENROLLED"
    assert reread["active_accommodation_count"] == 0

    assert_program_state(
        read_program(api, ctx["program_id"]),
        gated_asset_count=1,
        open_deletion_obligation_count=1,
        posture="RESTRICTED",
    )


def test_a_manual_accommodation_is_provisioned_and_activated_inside_its_window(api):
    """The bypass is provisioned in time and becomes the individual's live process.

    PRD §3.7: "The request lands in `REQUESTED` with `origin` of `MANUAL`,
    `created_from_consent_id` null, `sla_breached` false, and `sla_due_at` set to
    five days after the current logical clock — the deadline for reaching
    `PROVISIONED`."

    PRD §3.7: "An `HRAdministrator` drives `REQUESTED` → `PROVISIONED`, which
    re-checks that the recorded `method` is the permitted method for the collection
    point's `system_category` (else `ERR_ACCOMMODATION_METHOD_NOT_PERMITTED`) and
    sets `sla_breached` to true when the current logical clock is **strictly after**
    `sla_due_at`; provisioning exactly at the deadline is on time."

    PRD §2.9: "`active_accommodation_count` on a data subject is the count of its
    accommodations whose status is `PROVISIONED` or `ACTIVE`."

    Provisioning happens on 18 August, two days inside the 20 August deadline, and
    activation happens after the window has opened. The individual never had a
    consent record, so the collection point's tallies stay at zero throughout.

    Design: Corner/state_machines/accommodation_provisioned_then_activated_within_the_sla
    """
    ctx = baseline_with_active_asset(api, activation_clock="2026-08-15T00:00:00Z")
    subject = create_data_subject(
        api, ctx["program_id"], ctx["jurisdiction_id"], "EMP-0001", accommodation_needed=True
    )

    requested = validate_success(
        api.create_accommodation(
            accommodation_payload(
                subject["id"],
                ctx["asset_id"],
                starts_at="2026-08-15T00:00:00Z",
                ends_at="2026-09-15T00:00:00Z",
            ),
            HR_ADMIN,
        ),
        expected_status=201,
    )
    assert requested["status"] == "REQUESTED"
    assert requested["origin"] == "MANUAL"
    assert_instant_equals(requested["sla_due_at"], "2026-08-20T00:00:00.000Z", "sla_due_at")
    assert read_subject(api, subject["id"])["enrollment_status"] == "NOT_ENROLLED"

    set_clock(api, "2026-08-18T00:00:00Z")

    provisioned = validate_success(
        api.transition_accommodation(requested["id"], {"to_status": "PROVISIONED"}, HR_ADMIN)
    )
    assert provisioned["status"] == "PROVISIONED"
    assert provisioned["sla_breached"] is False
    assert read_subject(api, subject["id"])["enrollment_status"] == "ALTERNATIVE"

    activated = validate_success(
        api.transition_accommodation(requested["id"], {"to_status": "ACTIVE"}, HR_ADMIN)
    )
    assert activated["status"] == "ACTIVE"

    reread = read_subject(api, subject["id"])
    assert reread["active_accommodation_count"] == 1
    assert reread["enrollment_status"] == "ALTERNATIVE"
    assert_asset_state(
        read_asset(api, ctx["asset_id"]), enrolled_subject_count=0, consent_gap_count=0
    )
