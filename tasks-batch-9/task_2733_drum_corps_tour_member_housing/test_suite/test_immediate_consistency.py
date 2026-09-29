"""One write, every dependent aggregate already moved.

The specification promises no deferred reconciliation anywhere, so a single bed
booking has to be visible in the agreement, the school and the season on the
very next read.
"""

from test_helpers import (
    BUSINESS_MANAGER_HEADERS,
    HousingStatus,
    LedgerStatus,
    MEMBERSHIP_COORDINATOR_HEADERS,
    UsageType,
    assert_facility_agreement,
    assert_host_school,
    assert_housing_assignment,
    assert_season,
    factories as f,
    fixtures as fx,
    validate_success,
)


def test_one_bed_booking_is_already_visible_in_three_other_aggregates(api):
    """No sweep publishes the housing cost; the write itself does.

    PRD: "Consistency is immediate; there is no deferred or eventual reconciliation anywhere in this specification."

    Design: Corner/consistency_model/every_derived_field_is_visible_in_the_same_response
    """
    season = fx.create_season(api)
    built = fx.signed_agreement_with_school(
        api,
        season["id"],
        UsageType.SPRING_TRAINING,
        school_overrides={
            "name": "Rockford High School",
            "city": "Rockford",
            "state_code": "IL",
            "sleeping_space_count": 30,
            "capacity_per_space": 12,
        },
        nightly_rate_cents=500,
        minimum_billable_beds=0,
    )
    agreement_id = built["agreement"]["id"]
    school_id = built["school"]["id"]
    member = fx.contracted_member(api, season["id"], full_name="Avery Nakamura")["member"]
    agreement_version = fx.get_agreement(api, agreement_id)["version"]

    assignment = validate_success(
        api.create_housing_assignment(
            f.housing_assignment_payload(
                agreement_id, member["id"], 7, "2027-05-12", "2027-05-22", agreement_version
            ),
            MEMBERSHIP_COORDINATOR_HEADERS,
        ),
        201,
    )
    assert_housing_assignment(
        assignment,
        facility_agreement_id=agreement_id,
        member_id=member["id"],
        space_index=7,
        check_in_date="2027-05-12",
        check_out_date="2027-05-22",
        nights=10,
        occupant_is_minor=False,
        status=HousingStatus.ACTIVE,
        version=1,
    )

    assert_facility_agreement(
        fx.get_agreement(api, agreement_id),
        occupied_bed_nights=10,
        billable_bed_nights=10,
        billable_cents=5000,
        version=agreement_version + 1,
    )
    assert_host_school(
        validate_success(api.get_host_school(school_id, MEMBERSHIP_COORDINATOR_HEADERS)),
        reserved_bed_nights=10,
    )
    assert_season(
        validate_success(api.get_season(season["id"], BUSINESS_MANAGER_HEADERS)),
        housing_cost_cents=5000,
        ledger_status=LedgerStatus.OPEN,
        billing_epoch=0,
    )
