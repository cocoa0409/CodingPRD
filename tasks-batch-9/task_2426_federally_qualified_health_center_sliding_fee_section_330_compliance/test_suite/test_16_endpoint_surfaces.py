"""Endpoint surfaces: the round trip, the metadata action, the computed read and the bulk sweep."""

import pytest

from test_helpers import (
    ADMIN,
    BILLER,
    OFFICER,
    ApiErrorId,
    advance_clock,
    annual_review_payload,
    api_client,
    bill_encounter,
    claim_wraparound_payload,
    create_board_member_payload,
    record_payment_payload,
    refresh_encounter,
    refresh_fee_schedule,
    refresh_finding,
    refresh_health_center,
    resign_board_member_payload,
    same_instant,
    seed_poverty_guidelines,
    setup_board_seat,
    setup_boot_core,
    setup_boot_pt,
    setup_draft_scope_change_request,
    setup_encounter,
    setup_grantee,
    setup_open_finding,
    setup_proposed_site,
    validate_error,
    validate_paginated,
    validate_success,
)

CORNER_2026_GUIDELINE = ((2026, 1620000, 570000),)


def test_a_board_seat_round_trips_through_create_read_list_and_resign():
    """The write surface is create plus resign, and a resigned seat stays listable.

    PRD 3.2: "A `ComplianceOfficer` seats a **board member** on a grantee's board by
    supplying a `seat_number` of at least 1, a `seat_type`, a `term_start` and a
    `term_end`, optionally naming the owning grantee as `health_center_id` in the body.
    A seated member's `status` begins at `SEATED` and its `resignation_date` begins
    null."

    PRD 3.2: "A `NON_PATIENT` seat must carry an `expertise_category` — one of
    `FINANCE`, `LEGAL`, `COMMUNITY` or `HEALTH_PROFESSION` — and must leave `patient_id`
    null."

    PRD 3.2: "The transition is `SEATED → RESIGNED`; it truncates `term_end` down to the
    `resignation_date`, thereby freeing the `seat_number` for a new term, and it
    recomputes the grantee's `seated_board_count`, `patient_seat_pct` and
    `governance_posture` with a `version` increment."

    PRD 3.2: "Board seats may be listed and filtered by `health_center_id`,
    `patient_id`, `status`, `seat_type` and `seat_number`."

    Design: Corner/endpoints/board_member_create_read_and_list_round_trip
    """
    seed_poverty_guidelines(CORNER_2026_GUIDELINE)
    grantee = setup_grantee(
        legal_name="Corner Community Health",
        grant_number="H80CS00500",
        pps_base_rate_cents=20000,
    )
    setup_board_seat(grantee["id"])

    created = validate_success(
        api_client.create_board_member(
            grantee["id"],
            create_board_member_payload(
                seat_number=2,
                seat_type="NON_PATIENT",
                expertise_category="HEALTH_PROFESSION",
                term_start="2026-02-01T00:00:00Z",
                term_end="2029-01-31T00:00:00Z",
            ),
            OFFICER,
        ),
        201,
    )
    assert created["status"] == "SEATED"
    assert created["seat_number"] == 2
    assert created["expertise_category"] == "HEALTH_PROFESSION"
    assert created["version"] == 1, (
        f"a freshly created row starts at version 1, got {created['version']}"
    )

    read_back = validate_success(api_client.get_board_member(created["id"], OFFICER))
    assert read_back["status"] == "SEATED"
    assert read_back["patient_id"] is None, "a non-patient seat names no patient"

    rows, meta = validate_paginated(
        api_client.list_board_members(
            OFFICER, {"health_center_id": grantee["id"], "status": "SEATED"}
        )
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert meta["limit"] == 10, (
        f"the omitted limit defaults to 10, got {meta['limit']}"
    )
    assert meta["offset"] == 0
    assert len(rows) == 2

    resigned = validate_success(
        api_client.resign_board_member(
            created["id"],
            resign_board_member_payload(resignation_date="2026-07-01T00:00:00Z"),
            OFFICER,
        )
    )
    assert resigned["status"] == "RESIGNED"
    assert same_instant(resigned["resignation_date"]) == "2026-07-01T00:00:00Z"
    assert resigned["version"] == 2, (
        f"the resignation is the row's second mutation, got {resigned['version']}"
    )

    _, seated_meta = validate_paginated(
        api_client.list_board_members(
            OFFICER, {"health_center_id": grantee["id"], "status": "SEATED"}
        )
    )
    assert seated_meta["total_count"] == 1, (
        "the resigned seat leaves the seated filter but remains a row"
    )
    assert refresh_health_center(grantee["id"])["seated_board_count"] == 1


def test_an_annual_review_restamps_the_metadata_without_moving_the_status():
    """The review is a metadata action, so the schedule keeps its adoption stamps.

    PRD 3.3: "A `ComplianceOfficer` records an **annual review** of a schedule by
    supplying `reviewed_against_guideline_year`, the guideline year the tiers were just
    compared against. The review stamps `last_reviewed_at` with the logical clock,
    stores the supplied year, and recomputes `review_status`."

    PRD 3.3: "The day boundary is strict — 365 elapsed days is still `CURRENT`, and 366
    is `REVIEW_DUE`."

    Design: Corner/endpoints/fee_schedule_annual_review_action_stamps_review_metadata
    """
    ctx = setup_boot_core()
    advance_clock("2026-12-01T00:00:00Z")

    reviewed = validate_success(
        api_client.annual_review_fee_schedule(
            ctx["fee_schedule_id"], annual_review_payload(2026), OFFICER
        )
    )

    assert reviewed["review_status"] == "CURRENT", (
        "2026 is still the latest published guideline year and the elapsed days are far "
        f"short of 365, got {reviewed['review_status']}"
    )
    assert same_instant(reviewed["last_reviewed_at"]) == "2026-12-01T00:00:00Z"
    assert reviewed["reviewed_against_guideline_year"] == 2026
    assert reviewed["status"] == "ADOPTED", "a review is not a state transition"

    stored = refresh_fee_schedule(ctx["fee_schedule_id"])
    assert same_instant(stored["adopted_at"]) == "2026-08-01T00:00:00Z", (
        "the adoption stamp is untouched by the review"
    )
    assert refresh_health_center(ctx["health_center_id"])["version"] == 5, (
        "the review touches the schedule, not the grantee"
    )


def test_the_governance_summary_recomputes_every_intermediate_of_the_majority_test():
    """The read exposes the whole calculation, not just the verdict.

    PRD 3.2: "A read-only governance summary is also available for a grantee, exposing
    every intermediate the majority test uses — `health_center_id`,
    `seated_board_count`, `qualified_patient_seat_count`, `non_patient_seat_count`,
    `healthcare_industry_seat_count`, `patient_seat_pct`, `governance_posture` and the
    grantee's current `version` — so that an operator can see *why* a board reads
    deficient rather than merely that it does."

    Design: Corner/endpoints/governance_summary_computed_read_matches_the_governance_calculation
    """
    ctx = setup_boot_core()

    summary = validate_success(
        api_client.get_governance_summary(ctx["health_center_id"], OFFICER)
    )

    assert summary["health_center_id"] == ctx["health_center_id"]
    assert summary["seated_board_count"] == 1
    assert summary["qualified_patient_seat_count"] == 0
    assert summary["non_patient_seat_count"] == 1
    assert summary["healthcare_industry_seat_count"] == 0
    assert summary["patient_seat_pct"] == pytest.approx(0.00, abs=0.01), (
        "an empty qualified set lands on 0.00 rather than dividing by zero, got "
        f"{summary['patient_seat_pct']}"
    )
    assert summary["governance_posture"] == "GOVERNANCE_DEFICIENT"
    assert summary["version"] == 5, (
        "the summary mirrors the grantee's own version, got "
        f"{summary['version']}"
    )
    assert (
        refresh_health_center(ctx["health_center_id"])["governance_posture"]
        == "GOVERNANCE_DEFICIENT"
    )


def test_the_wraparound_can_be_claimed_received_and_then_never_touched_again():
    """The wraparound dimension moves on its own until the confirmed receipt couples them.

    PRD 3.7: "Claiming the wraparound is the same operation as recording its receipt,
    distinguished by an optional `receipt_confirmed` flag. Without the flag, or with it
    false, the transition is `PENDING → CLAIMED` or `REBILL_REQUIRED → CLAIMED` — the
    second of these being the re-claim edge that closes the cycle after a residual
    changed underneath an outstanding claim. With `receipt_confirmed` set to true, the
    transition is `CLAIMED → RECEIVED`. A confirmed receipt is the one place the two
    dimensions couple: when the wraparound reaches `RECEIVED` while `pps_claim_status`
    is `PAID`, the claim also moves `PAID → RECONCILED`"

    Design: Corner/endpoints/claim_wraparound_is_allowed_only_while_a_wraparound_is_outstanding
    """
    ctx = setup_boot_pt()
    encounter = setup_encounter(
        ctx,
        ctx["patient_id"],
        encounter_date="2026-03-15T00:00:00Z",
        payer_type="MEDICAID_MCO",
        gross_charge_cents=8000,
    )
    bill_encounter(encounter, "CLM-M1")
    paid = validate_success(
        api_client.record_encounter_payment(
            encounter["id"], record_payment_payload(14000), BILLER
        )
    )
    assert paid["wraparound_due_cents"] == 3500, (
        "20000 less the 14000 payment less the 2500 counted patient portion is 3500, "
        f"got {paid['wraparound_due_cents']}"
    )
    assert paid["wraparound_status"] == "PENDING"

    claimed = validate_success(
        api_client.claim_wraparound(encounter["id"], BILLER, claim_wraparound_payload())
    )
    assert claimed["wraparound_status"] == "CLAIMED"
    assert claimed["pps_claim_status"] == "PAID", (
        "claiming the wraparound leaves the claim dimension alone"
    )

    received = validate_success(
        api_client.claim_wraparound(
            encounter["id"], BILLER, claim_wraparound_payload(receipt_confirmed=True)
        )
    )
    assert received["wraparound_status"] == "RECEIVED"
    assert received["pps_claim_status"] == "RECONCILED", (
        "the confirmed receipt is the one place the two dimensions couple"
    )

    validate_error(
        api_client.claim_wraparound(
            encounter["id"], BILLER, claim_wraparound_payload(receipt_confirmed=True)
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        409,
    )

    final = refresh_encounter(encounter["id"])
    assert final["wraparound_status"] == "RECEIVED"
    assert final["pps_claim_status"] == "RECONCILED"
    assert (
        refresh_health_center(ctx["health_center_id"])["wraparound_receivable_cents"]
        == 0
    ), "a received wraparound contributes nothing to the receivable"


def test_a_request_and_its_target_site_are_visible_from_both_directions():
    """The polymorphic link is queryable from the request side and the site side.

    PRD 3.8: "Requests may be listed and filtered by `health_center_id`,
    `target_site_id`, `target_service_definition_id`, `status` and `request_type`."

    PRD 3.1: "Sites may be listed for a grantee and filtered by `status` and
    `site_type`."

    Design: Corner/endpoints/scope_change_request_link_binds_the_target_site_on_both_sides
    """
    ctx = setup_boot_core()
    annex = setup_proposed_site(
        ctx,
        site_name="Corner Annex Clinic",
        address_line="2 Corner Ave",
        weekly_service_hours=20,
    )
    request = setup_draft_scope_change_request(
        ctx,
        request_type="ADD_SITE",
        target_site_id=annex["id"],
        justification="Annex clinic opens to absorb overflow primary-care demand",
    )

    request_rows, request_meta = validate_paginated(
        api_client.list_scope_change_requests(OFFICER, {"target_site_id": annex["id"]})
    )
    assert request_meta["total_count"] == 1
    assert request_rows[0]["id"] == request["id"]
    assert request_rows[0]["health_center_id"] == ctx["health_center_id"]
    assert request_rows[0]["target_site_id"] == annex["id"]

    site_rows, site_meta = validate_paginated(
        api_client.list_health_center_service_sites(
            ctx["health_center_id"], OFFICER, {"status": "PROPOSED"}
        )
    )
    assert site_meta["total_count"] == 1
    assert site_rows[0]["id"] == annex["id"]
    assert refresh_health_center(ctx["health_center_id"])["in_scope_site_count"] == 1, (
        "the proposed target is visible without joining the scope of project"
    )


def test_the_sweep_escalates_the_due_finding_and_leaves_the_other_alone():
    """The sweep is skip-not-rollback: an undue row is untouched in the same pass.

    PRD 3.9: "Step two escalates findings: every site visit finding whose `severity` is
    `CONDITION`, whose `status` is `OPEN` or `CAP_SUBMITTED`, whose `cap_due_at` is at
    or before the logical clock, and which has no accepted corrective action plan,
    escalates and fires the five-hop escalation cascade of section 3.8."

    Design: Corner/endpoints/compliance_sweep_skips_rows_that_are_not_yet_due
    """
    ctx = setup_boot_core()
    due = setup_open_finding(
        ctx,
        requirement_code="REQ_SLIDING_FEE_16",
        severity="CONDITION",
        cap_due_days=1,
        service_site_id=ctx["site_id"],
        finding_summary="Sliding fee schedule not posted at the point of service",
    )
    not_yet_due = setup_open_finding(
        ctx,
        requirement_code="REQ_BOARD_AUTHORITY_19",
        severity="CONDITION",
        cap_due_days=30,
        service_site_id=ctx["site_id"],
        finding_summary="Governing board lacks patient-majority composition",
    )
    advance_clock("2026-08-02T00:00:00Z")

    sweep = validate_success(api_client.run_compliance_sweep(ADMIN))

    assert sweep["escalated_finding_count"] == 1, (
        f"only the finding due 2026-08-02 escalates, got {sweep['escalated_finding_count']}"
    )
    assert sweep["expired_verification_count"] == 0
    assert sweep["expired_fee_schedule_count"] == 0

    escalated = refresh_finding(due["id"])
    assert escalated["status"] == "ESCALATED"
    assert same_instant(escalated["escalated_at"]) == "2026-08-02T00:00:00Z"

    skipped = refresh_finding(not_yet_due["id"])
    assert skipped["status"] == "OPEN", (
        "the finding due 2026-08-31 is left exactly where it was"
    )
    assert skipped["escalated_at"] is None

    health_center = refresh_health_center(ctx["health_center_id"])
    assert health_center["open_condition_count"] == 1
    assert health_center["scope_posture"] == "CHANGE_FROZEN"
