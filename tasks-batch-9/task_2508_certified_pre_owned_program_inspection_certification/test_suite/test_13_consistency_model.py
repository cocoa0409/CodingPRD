"""Approval is one atomic write, and its own response is the proof.

Activating a certification is the densest single write the programme performs.
One request settles the certifying fee, chooses the anchor of the coverage
interval and both of its ends, fixes the documentation retention date, mints the
programme label, pins the configuration generation the certification was priced
under, stamps the retention date onto every document of record, flips the
vehicle's programme standing and refreshes half a dozen dealer counters. The
programme's consistency model forbids any of that being computed lazily by a
later read handler, so every figure has to be present in the approval's own
response body, and the next read of the certification — by a different role —
has to agree with it field for field.
"""

from test_helpers import (
    ADVOCATE,
    AUDITOR,
    BASE_FEE_CENTS,
    CLOCK_EPOCH,
    approve_certification,
    assert_calendar_date,
    assert_certification,
    assert_certification_document,
    assert_certification_number,
    assert_dealer,
    assert_instant_equals,
    assert_vehicle,
    certification_documents,
    create_vehicle,
    read_certification,
    read_config,
    read_dealer,
    read_vehicle,
    submitted_certification,
)

#: A car three years and change into service, well under the mileage floor, so
#: both surcharge terms land on zero and the factory basic term has just lapsed.
_IN_SERVICE_DATE = "2023-05-10"
_ODOMETER_MILES = 30000

#: The whole derived set the approval response must publish for that car.
_DERIVED_FIELDS = (
    "status",
    "activated_at",
    "certification_number",
    "program_config_version",
    "fee_surcharge_cents",
    "fee_discount_cents",
    "fee_charged_cents",
    "fee_credited_cents",
    "warranty_anchor_variant",
    "warranty_start_date",
    "warranty_end_date",
    "warranty_end_miles",
    "retention_expires_at",
    "document_count",
    "audit_sampled",
    "approved_claim_count",
    "approved_claim_amount_cents",
)


def _submitted_certification_for_a_zero_surcharge_car(api, program):
    """Walk one car with no surcharge and no discount up to `SUBMITTED`."""
    vehicle = create_vehicle(
        api,
        in_service_date=_IN_SERVICE_DATE,
        odometer_miles=_ODOMETER_MILES,
        model_year=2023,
    )
    return submitted_certification(
        api, program, vehicle=vehicle, odometer_at_inspection=_ODOMETER_MILES
    )


def test_approval_publishes_every_derived_figure_in_its_own_response(api, program):
    """The activating response already carries the fee, the coverage and the label.

    PRD §3.7: "Chargeable age years are the whole age years minus the programme's
    free-year allowance — three years by default — with a negative result treated
    as zero."
    PRD §3.7: "When the factory warranty has lapsed on either axis,
    `warranty_start_date` is the activation date and `warranty_anchor_variant` is
    `CERTIFICATION_ANCHORED`, so coverage begins immediately."
    PRD §3.7: "`warranty_end_miles` is the smaller of that figure and the
    absolute odometer cap of 100000 miles"
    PRD §3.7: "`retention_expires_at` is `warranty_end_date` advanced by the
    documentation retention period in calendar years — seven years by default"

    Design: Corner/consistency model/every_derived_field_is_visible_in_the_approval_response_itself
    """
    walk = _submitted_certification_for_a_zero_surcharge_car(api, program)
    pinned_generation = read_config(api)["version"]

    approved = approve_certification(api, walk.certification_id)
    assert_certification(approved)
    assert approved["status"] == "ACTIVE"
    assert_instant_equals(approved["activated_at"], CLOCK_EPOCH, "activated_at")

    assert approved["fee_surcharge_cents"] == 0, (
        "three whole age years is exactly the free allowance, and 30000 miles is "
        "below the free-mileage floor"
    )
    assert approved["fee_discount_cents"] == 0, "the dealer's first activation earns no tier"
    assert approved["fee_charged_cents"] == 89900
    assert approved["fee_charged_cents"] == BASE_FEE_CENTS
    assert approved["fee_credited_cents"] == 0

    assert approved["warranty_anchor_variant"] == "CERTIFICATION_ANCHORED", (
        "the factory basic term lapsed on 2026-05-10, before the activation date"
    )
    assert_calendar_date(approved["warranty_start_date"], "warranty_start_date")
    assert_calendar_date(approved["warranty_end_date"], "warranty_end_date")
    assert approved["warranty_start_date"] == "2026-08-01"
    assert approved["warranty_end_date"] == "2027-08-01"
    assert approved["warranty_end_miles"] == 42000
    assert approved["retention_expires_at"][:10] == "2034-08-01"

    assert approved["certification_number"] is not None
    assert_certification_number(
        approved["certification_number"], program.dealer["franchise_code"], 1
    )
    assert approved["program_config_version"] == pinned_generation
    assert approved["program_config_version"] == 1

    assert approved["audit_sampled"] is False
    assert approved["approved_claim_count"] == 0
    assert approved["approved_claim_amount_cents"] == 0
    assert approved["rejection_reason"] is None
    assert approved["decertified_at"] is None
    assert approved["decertification_reason"] is None
    for field in _DERIVED_FIELDS:
        assert approved[field] is not None, (
            f"{field} must be settled by the approval, not by a later read"
        )

    documents = certification_documents(api, walk.certification_id)
    assert len(documents) == 3
    assert approved["document_count"] == 3
    for row in documents:
        assert_certification_document(row)
        assert row["retained_until"][:10] == "2034-08-01"
        assert row["retained_until"] == approved["retention_expires_at"], (
            "every document of record inherits the certification's retention date"
        )


def test_the_approval_response_and_the_next_read_agree_field_for_field(api, program):
    """Nothing the approval derived is materialised by the read handler instead.

    PRD §2.7: "within the single request that triggers them, every downstream row
    is brought to its consistent state before the response is written"
    PRD §3.7: "On the dealer, `lifetime_activated_count`,
    `window_activated_count`, `fee_billed_cents_total`, `fee_balance_cents`,
    `claim_ratio_variant`, `claim_ratio_effective`, and `risk_score` are all
    recomputed."
    PRD §3.7: "On the vehicle, `cpo_state` moves `CERTIFICATION_PENDING →
    CERTIFIED` and `certified_certification_id` is set to the approved
    certification."

    Design: Corner/consistency model/every_derived_field_is_visible_in_the_approval_response_itself
    """
    walk = _submitted_certification_for_a_zero_surcharge_car(api, program)
    approved = approve_certification(api, walk.certification_id)

    reread = read_certification(api, walk.certification_id, AUDITOR)
    for field in _DERIVED_FIELDS + ("id", "version", "updated_at", "submitted_at"):
        assert reread[field] == approved[field], (
            f"{field} differs between the approval response and the next read"
        )
        assert reread[field] is not None, f"{field} is null in the re-read view"

    dealer = read_dealer(api, program.dealer_id)
    assert dealer["lifetime_submitted_count"] == 1
    assert dealer["lifetime_activated_count"] == 1
    assert dealer["window_activated_count"] == 1
    assert dealer["active_certification_count"] == 1
    assert dealer["claim_ratio_variant"] == "LIFETIME_CUMULATIVE"
    assert dealer["claim_ratio_effective"] == 0.00
    assert dealer["audit_fail_rate"] == 0.00
    assert dealer["risk_score"] == 0
    assert dealer["fee_billed_cents_total"] == 89900
    assert dealer["fee_credited_cents_total"] == 0
    assert dealer["fee_balance_cents"] == 89900
    assert dealer["privilege_status"] == "ACTIVE"
    assert_dealer(dealer)

    vehicle = read_vehicle(api, walk.vehicle_id, ADVOCATE)
    assert vehicle["cpo_state"] == "CERTIFIED"
    assert vehicle["active_certification_count"] == 1
    assert vehicle["certified_certification_id"] == walk.certification_id
    assert vehicle["inventory_state"] == "IN_INVENTORY", (
        "the commercial axis is untouched by programme standing"
    )
    assert vehicle["decertified_at"] is None
    assert_vehicle(vehicle)
