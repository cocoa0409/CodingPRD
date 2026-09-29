"""Proof of performance, adjudication and the ROI/ROO reporting surface."""

from test_helpers import (
    ACTIVATION_USER_ID,
    ApiErrorId,
    AUDITOR_USER_ID,
    TEST_USERS,
    adjudicate_proof,
    assert_proof_of_performance,
    assert_roi_report,
    assign_staff,
    book_asset,
    capture_proof,
    create_staff_member,
    make_auditor_headers,
    read_booking,
    read_contract,
    read_entitlement,
    setup_active_contract_with_booking,
    setup_contract_scenario,
    setup_delivered_booking,
    setup_delivered_booking_with_mixed_evidence,
    setup_two_delivered_bookings_with_proofs,
    validate_error,
    validate_paginated,
    validate_success,
)

ACTIVATION = TEST_USERS["activation_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# The two adjudication branches carry disjoint consequences
# ---------------------------------------------------------------------------
def test_verified_proof_raises_impressions_without_moving_delivered_units(api):
    """PRD §3.8: "A verification drives the proof `SUBMITTED → VERIFIED`, stamps
    `adjudicated_by_user_id` with the auditor's `X-User-ID`, and — when the
    evidence type is `IMPRESSIONS` or `SOCIAL` — raises the booking's
    `verified_impressions` by that proof's `measured_value`, so that
    `verified_impressions` is always the sum of `measured_value` across the
    booking's verified impressions-or-social proofs."
    PRD §3.8: "Nothing else moves: `delivered_units` is unchanged, because a
    delivered, non-deficient booking was already being counted before the evidence
    was verified."

    Design: Difficulty/non_linear_state_machine/proof_verify_branch_versus_reject_branch_side_effects
    """
    scenario = setup_two_delivered_bookings_with_proofs()
    before = read_entitlement(scenario["entitlement"]["id"])
    assert before["delivered_units"] == 7

    verified = adjudicate_proof(scenario["proof_one"]["id"], "VERIFIED")
    assert_proof_of_performance(verified)
    assert verified["status"] == "VERIFIED"
    assert verified["adjudicated_by_user_id"] == AUDITOR_USER_ID

    booking = read_booking(scenario["booking_one"]["id"])
    assert booking["proof_state"] == "VERIFIED"
    assert booking["verified_impressions"] == 500_000

    after = read_entitlement(scenario["entitlement"]["id"])
    assert after["delivered_units"] == 7, (
        "verification leaves delivered_units untouched, got "
        f"{after['delivered_units']}"
    )


def test_rejected_proof_makes_the_booking_deficient_and_unwinds_its_units(api):
    """PRD §3.8: "A rejection drives the proof `SUBMITTED → REJECTED`, stamps
    `adjudicated_by_user_id`, stores the `reject_reason`, and then cascades in
    four hops. The booking's `proof_state` becomes `DEFICIENT`, and rejection
    dominates: a `VERIFIED` sibling proof does not restore the booking, and the
    deficiency is not reversible. That booking's units therefore leave the owning
    entitlement's `delivered_units`, so `delivery_pct` and the entitlement
    `status` are recomputed downward by the delivery rollup."
    PRD §3.8: "In the same rollup the contract's `delivered_media_value_cents` is
    set to the sum, over that contract's bookings whose `status` is `DELIVERED`
    and whose `proof_state` is not `DEFICIENT`, of `units_booked` multiplied by
    the owning entitlement's `unit_value_cents`."

    Design: Difficulty/non_linear_state_machine/proof_verify_branch_versus_reject_branch_side_effects
    """
    scenario = setup_two_delivered_bookings_with_proofs()
    adjudicate_proof(scenario["proof_one"]["id"], "VERIFIED")

    rejected = adjudicate_proof(
        scenario["proof_two"]["id"], "REJECTED",
        reject_reason="Screenshot does not show the ribbon",
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["reject_reason"] == "Screenshot does not show the ribbon"

    booking = read_booking(scenario["booking_two"]["id"])
    assert booking["proof_state"] == "DEFICIENT"
    assert booking["verified_impressions"] == 0
    assert booking["status"] == "DELIVERED", (
        "rejection changes proof_state only, never the booking status"
    )

    entitlement = read_entitlement(scenario["entitlement"]["id"])
    assert entitlement["delivered_units"] == 4
    assert entitlement["delivery_pct"] == 40.00
    assert entitlement["status"] == "PARTIAL"

    contract = read_contract(scenario["contract"]["id"])
    assert contract["delivered_media_value_cents"] == 1_350_000


# ---------------------------------------------------------------------------
# The reporting projection on an empty evidence set
# ---------------------------------------------------------------------------
def test_roi_report_with_no_evidence_returns_null_cost_per_thousand(api):
    """PRD §3.9: "`cost_per_thousand_impressions_cents` is null when
    `impressions_total` is 0, and otherwise the contract's
    `total_recognized_value_cents` divided by the number of thousands of
    impressions — that is, by `impressions_total` divided by 1000 — rounded half
    up to 2 decimal places."
    PRD §3.9: "`media_value_cents` is the sum, over the contributing bookings, of
    `units_booked` multiplied by the owning entitlement's `unit_value_cents`.
    `impressions_total` is the sum of `measured_value` over the contributing
    proofs. `roi_ratio` is 0.0 when the contract's `total_recognized_value_cents`
    is 0, and otherwise `media_value_cents` divided by
    `total_recognized_value_cents`, rounded half up to 4 decimal places."
    PRD §3.9: "The caller may supply a `basis` query parameter of either
    `VERIFIED` or `GROSS`; when it is omitted the basis is `VERIFIED`."

    Design: Difficulty/boundary_precision_check/roi_report_with_empty_evidence_set_returns_null_cpm
    """
    scenario = setup_contract_scenario(
        stage="ACTIVE", contract_overrides={"exclusivity_scope": "CATEGORY"}
    )

    response = api.get_roi_report(scenario["contract"]["id"], AUDITOR)
    report = validate_success(response)
    assert_roi_report(report)

    assert report["basis"] == "VERIFIED"
    assert report["media_value_cents"] == 0
    assert report["impressions_total"] == 0
    assert report["roi_ratio"] == 0.0
    assert report["cost_per_thousand_impressions_cents"] is None


def test_roi_report_with_no_evidence_reports_zero_attainment_under_both_bases(api):
    """PRD §3.9: "`roo_attainment_pct` measures promise attainment rather than
    money: it is 100.00 when the contract's non-`WAIVED` entitlements promise
    nothing, and otherwise 100 multiplied by the sum over those entitlements of
    the lesser of `delivered_units` and `promised_units`, divided by the sum of
    their `promised_units`, rounded half up to 2 decimal places — capping each
    clause at its own promise so that over-delivery on one clause cannot mask a
    shortfall on another."
    PRD §3.9: "`cost_per_thousand_impressions_cents` is null when
    `impressions_total` is 0, and otherwise the contract's
    `total_recognized_value_cents` divided by the number of thousands of
    impressions — that is, by `impressions_total` divided by 1000 — rounded half
    up to 2 decimal places."

    Design: Difficulty/boundary_precision_check/roi_report_with_empty_evidence_set_returns_null_cpm
    """
    scenario = setup_contract_scenario(
        stage="ACTIVE", contract_overrides={"exclusivity_scope": "CATEGORY"}
    )

    verified_response = api.get_roi_report(scenario["contract"]["id"], AUDITOR)
    verified = validate_success(verified_response)
    assert verified_response.status_code == 200
    assert verified["roo_attainment_pct"] == 0.00, (
        "no unit of the ten promised has been delivered"
    )

    gross_response = api.get_roi_report(
        scenario["contract"]["id"], AUDITOR, {"basis": "GROSS"}
    )
    gross = validate_success(gross_response)
    assert gross_response.status_code == 200
    assert gross["basis"] == "GROSS"
    assert gross["impressions_total"] == 0
    assert gross["cost_per_thousand_impressions_cents"] is None


def test_roi_report_verified_basis_diverges_from_gross_basis(api):
    """PRD §3.9: "Under the verified basis only adjudicated evidence counts: the
    bookings that contribute are the contract's bookings whose `status` is
    `DELIVERED` and whose `proof_state` is exactly `VERIFIED`, and the proofs that
    contribute are those of the contract's bookings whose `evidence_type` is
    `IMPRESSIONS` or `SOCIAL` and whose own `status` is `VERIFIED`. Under the
    gross basis unadjudicated evidence counts too: contributing bookings are those
    with `status` `DELIVERED` and `proof_state` of `NONE`, `PENDING_REVIEW` or
    `VERIFIED`, and contributing proofs are the impressions-or-social proofs whose
    `status` is `SUBMITTED` or `VERIFIED`."
    PRD §3.9: "`cost_per_thousand_impressions_cents` is null when
    `impressions_total` is 0, and otherwise the contract's
    `total_recognized_value_cents` divided by the number of thousands of
    impressions — that is, by `impressions_total` divided by 1000 — rounded half
    up to 2 decimal places."

    Design: Corner/calculations/roi_report_verified_basis_diverges_from_gross_basis
    """
    scenario = setup_delivered_booking_with_mixed_evidence()
    contract_id = scenario["contract"]["id"]
    assert scenario["contract"]["total_recognized_value_cents"] == 3_881_250

    verified = validate_success(api.get_roi_report(contract_id, AUDITOR))
    assert_roi_report(verified)
    assert verified["media_value_cents"] == 1_350_000
    assert verified["impressions_total"] == 500_000
    assert verified["roi_ratio"] == 0.3478
    assert verified["roo_attainment_pct"] == 40.00
    assert verified["cost_per_thousand_impressions_cents"] == 7762.50

    gross = validate_success(
        api.get_roi_report(contract_id, AUDITOR, {"basis": "GROSS"})
    )
    assert_roi_report(gross)
    assert gross["impressions_total"] == 700_000, (
        "the still-SUBMITTED proof counts under the gross basis"
    )
    assert gross["cost_per_thousand_impressions_cents"] == 5544.64
    assert gross["media_value_cents"] == verified["media_value_cents"]
    assert gross["roi_ratio"] == verified["roi_ratio"]


def test_photo_proof_with_nonzero_measured_value_is_rejected(api):
    """PRD §3.8: "Photographic evidence measures nothing, so a `PHOTO` proof
    carrying a non-zero `measured_value` is rejected with
    `ERR_VALIDATION_FAILED`."
    PRD §3.8: "The proof records its `asset_booking_id` from the request path,
    opens at `SUBMITTED`, stamps `captured_by_user_id` with the caller's
    `X-User-ID`, and leaves `adjudicated_by_user_id` and `reject_reason` null.
    Capturing evidence moves the booking's `proof_state` to `PENDING_REVIEW`
    unless it already stands at `VERIFIED` or `DEFICIENT`."

    Design: Corner/validations/photo_proof_with_nonzero_measured_value_returns_422
    """
    scenario = setup_active_contract_with_booking(
        units_booked=4, contract_overrides={"exclusivity_scope": "CATEGORY"}
    )
    booking_id = scenario["booking"]["id"]

    rejected = api.create_proof(
        booking_id,
        {
            "evidence_type": "PHOTO",
            "measured_value": 4_200,
            "media_uri": "s3://pop/photo.jpg",
        },
        ACTIVATION,
    )
    validate_error(rejected, ApiErrorId.ERR_VALIDATION_FAILED.value)
    assert rejected.status_code == 422

    accepted = validate_success(
        api.create_proof(
            booking_id,
            {
                "evidence_type": "PHOTO",
                "measured_value": 0,
                "media_uri": "s3://pop/photo.jpg",
            },
            ACTIVATION,
        ),
        201,
    )
    assert accepted["status"] == "SUBMITTED"
    assert accepted["adjudicated_by_user_id"] is None

    assert read_booking(booking_id)["proof_state"] == "PENDING_REVIEW"

    proofs = validate_success(api.list_proofs(booking_id, ACTIVATION))
    assert len(proofs) == 1, (
        f"the rejected capture must not persist, got {len(proofs)} proofs"
    )


def test_filtered_and_subresource_reads_scope_by_foreign_key(api):
    """PRD §3.3: "Assets can be enumerated and narrowed by `property_id`, by
    `asset_class` or by `status`."
    PRD §3.7: "Assignments can be enumerated and narrowed by `asset_booking_id`,
    by `staff_member_id` or by `status`."
    PRD §3.8: "The proof records its `asset_booking_id` from the request path,
    opens at `SUBMITTED`, stamps `captured_by_user_id` with the caller's
    `X-User-ID`, and leaves `adjudicated_by_user_id` and `reject_reason` null."

    Design: Corner/endpoints/filtered_and_subresource_reads_scope_by_foreign_key
    """
    scenario = setup_contract_scenario(
        stage="ACTIVE",
        asset_specs=[
            {
                "name": "North LED Ribbon",
                "asset_class": "DIGITAL_BOARD",
                "capacity_units": 6,
                "changeover_buffer_minutes": 30,
            },
            {
                "name": "South Fascia Board",
                "asset_class": "SIGNAGE",
                "capacity_units": 3,
            },
        ],
        contract_overrides={"exclusivity_scope": "CATEGORY"},
    )
    booking = book_asset(
        scenario["entitlement"]["id"], scenario["asset"]["id"], units_booked=4
    )
    staffer = create_staff_member()
    assignment = assign_staff(
        booking["id"], staffer["id"],
        shift_start="2026-09-10T18:00:00Z",
        shift_end="2026-09-10T21:00:00Z",
    )
    proof = capture_proof(
        booking["id"], evidence_type="IMPRESSIONS", measured_value=500_000,
        media_uri="s3://pop/p1.json",
    )

    assets, assets_meta = validate_paginated(
        api.list_inventory_assets(
            ACTIVATION, {"property_id": scenario["property"]["id"]}
        )
    )
    assert assets_meta["total_count"] == 2
    assert {row["id"] for row in assets} == {
        scenario["assets"][0]["id"], scenario["assets"][1]["id"]
    }

    proofs_response = api.list_proofs(booking["id"], AUDITOR)
    proofs = validate_success(proofs_response)
    assert proofs_response.json()["response_type"] == "array"
    assert len(proofs) == 1
    assert proofs[0]["id"] == proof["id"]
    assert proofs[0]["asset_booking_id"] == booking["id"]

    by_staffer, by_staffer_meta = validate_paginated(
        api.list_staff_assignments(ACTIVATION, {"staff_member_id": staffer["id"]})
    )
    assert by_staffer_meta["total_count"] == 1
    assert by_staffer[0]["id"] == assignment["id"]
    assert by_staffer[0]["asset_booking_id"] == booking["id"]

    by_booking, by_booking_meta = validate_paginated(
        api.list_staff_assignments(
            ACTIVATION,
            {"asset_booking_id": booking["id"], "status": "ASSIGNED"},
        )
    )
    assert by_booking_meta["total_count"] == 1
    assert by_booking[0]["id"] == assignment["id"]


def test_proof_capture_and_adjudication_are_role_exclusive_and_segregated(api):
    """PRD §2.1: "Once the caller is authenticated, the role is matched against
    the roles authorized for the requested endpoint in §4; a caller whose role is
    not listed there is rejected with `ERR_ROLE_NOT_PERMITTED` (403)."
    PRD §2.10: "A contract may not be countersigned by the operator whose
    `X-User-ID` was recorded as `submitted_by_user_id` when the contract was last
    submitted, and a proof of performance may not be adjudicated by the operator
    whose `X-User-ID` was recorded as `captured_by_user_id` when the evidence was
    captured. In both cases the offending request is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (403)."
    PRD §3.8: "A verification drives the proof `SUBMITTED → VERIFIED`, stamps
    `adjudicated_by_user_id` with the auditor's `X-User-ID`, and — when the
    evidence type is `IMPRESSIONS` or `SOCIAL` — raises the booking's
    `verified_impressions` by that proof's `measured_value`, so that
    `verified_impressions` is always the sum of `measured_value` across the
    booking's verified impressions-or-social proofs."

    Design: Corner/rbac/proof_capture_and_adjudication_roles_are_exclusive_and_segregated
    """
    scenario = setup_delivered_booking(
        units_booked=4, contract_overrides={"exclusivity_scope": "CATEGORY"}
    )
    proof = capture_proof(
        scenario["booking"]["id"], evidence_type="IMPRESSIONS",
        measured_value=500_000, media_uri="s3://pop/p1.json",
    )
    assert proof["captured_by_user_id"] == ACTIVATION_USER_ID

    auditor_capture = api.create_proof(
        scenario["booking"]["id"],
        {
            "evidence_type": "SOCIAL",
            "measured_value": 900,
            "media_uri": "s3://pop/p2.json",
        },
        AUDITOR,
    )
    validate_error(auditor_capture, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)

    manager_adjudicates = api.adjudicate_proof(
        proof["id"], {"decision": "VERIFIED"}, ACTIVATION
    )
    validate_error(manager_adjudicates, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)

    same_operator = api.adjudicate_proof(
        proof["id"], {"decision": "VERIFIED"},
        make_auditor_headers(ACTIVATION_USER_ID),
    )
    validate_error(same_operator, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert same_operator.status_code == 403

    verified = validate_success(
        api.adjudicate_proof(proof["id"], {"decision": "VERIFIED"}, AUDITOR)
    )
    assert verified["status"] == "VERIFIED"
    assert verified["adjudicated_by_user_id"] == AUDITOR_USER_ID
    assert read_booking(scenario["booking"]["id"])["verified_impressions"] == 500_000
