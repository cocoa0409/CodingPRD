"""Per-computation constants, truncation sites and input-selection rules."""

from test_helpers import (
    accept_offer,
    agreement_version,
    approve_network,
    create_affiliation_agreement,
    create_distributor,
    create_election,
    create_interim_extension_payload,
    create_station,
    create_subscriber_report,
    execute_agreement,
    file_election,
    negotiation_of_election,
    read_agreement,
    read_offer,
    reject_offer_payload,
    setup_negotiation_with_report,
    submit_distributor_offer,
    submit_station_offer,
    validate_success,
)


def test_notice_days_and_the_deadline_are_selected_off_distributor_type(api):
    """A CABLE slot gets 30 days of notice and a VMVPD slot only 14.

    PRD §3.6: "the required notice period is 30 days for a distributor whose
    `distributor_type` is `CABLE`, `DBS` or `TELCO`, and 14 days for a `VMVPD`,
    which is exactly the value carried on the distributor as
    `required_blackout_notice_days`; the deadline instant,
    `blackout_notice_deadline_utc`, is the parent election's
    `incumbent_expiry_utc` with that many whole days subtracted."

    Design: Corner/calculations/corner_notice_window_constants_differ_by_distributor_type
    """
    station = create_station()
    create_affiliation_agreement(station["id"])
    cable = create_distributor(name="Cascade Cable", distributor_type="CABLE")
    vmvpd = create_distributor(
        name="StreamFront TV",
        distributor_type="VMVPD",
        subscriber_measurement_method="WEIGHTED_STREAMING_DEVICES",
        video_household_count=90000,
    )
    assert cable["required_blackout_notice_days"] == 30
    assert vmvpd["required_blackout_notice_days"] == 14

    cable_election = create_election(
        station["id"], cable["id"], incumbent_rate_per_sub_cents=220
    )
    vmvpd_election = create_election(
        station["id"], vmvpd["id"], incumbent_rate_per_sub_cents=180
    )
    file_election(cable_election["id"], station["id"])
    file_election(vmvpd_election["id"], station["id"])

    cable_negotiation = negotiation_of_election(cable_election["id"])
    vmvpd_negotiation = negotiation_of_election(vmvpd_election["id"])

    assert cable_negotiation["blackout_notice_deadline_utc"] == "2026-12-02T00:00:00Z"
    assert vmvpd_negotiation["blackout_notice_deadline_utc"] == "2026-12-18T00:00:00Z"
    assert cable_negotiation["notice_compliance_status"] == "NOT_REQUIRED"


def test_streaming_device_basis_truncates_at_two_and_a_half_devices(api):
    """250004 devices are 100001 households, never the 100002 rounding would give.

    PRD §3.4: "Under `WEIGHTED_STREAMING_DEVICES` the basis converts devices into
    households by multiplying the adjusted count by 10, dividing by 25, and
    truncating any remainder toward negative infinity - an integer-exact rendering
    of dividing by two and a half devices per household, so 25 devices yield 10
    households and 24 devices also yield 9, never 10."

    Design: Corner/calculations/corner_streaming_device_basis_floors_at_two_point_five_devices
    """
    station = create_station()
    distributor = create_distributor(
        name="StreamFront TV",
        distributor_type="VMVPD",
        subscriber_measurement_method="WEIGHTED_STREAMING_DEVICES",
        video_household_count=90000,
    )

    report = create_subscriber_report(
        station["id"],
        distributor["id"],
        reported_subscriber_count=250009,
        excluded_free_trial_count=5,
    )

    assert report["measurement_method_snapshot"] == "WEIGHTED_STREAMING_DEVICES"
    assert report["adjusted_subscriber_count"] == 250004
    assert report["billable_subscriber_basis"] == 100001
    assert report["as_reported_basis"] == 100001
    assert report["audit_adjustment_subscribers"] == 0
    assert report["status"] == "REPORTED"


def test_average_monthly_unique_basis_rounds_the_discount_half_up(api):
    """88 percent of 100003 uniques is 88002.64, which carries up to 88003.

    PRD §3.4: "Under `AVERAGE_MONTHLY_UNIQUE` the basis discounts the adjusted
    count to 8,800 basis points of itself - that is, to 88 percent - by multiplying
    by 8,800, dividing by 10,000, and rounding half up."

    Design: Corner/calculations/corner_average_monthly_unique_basis_rounds_half_up
    """
    station = create_station()
    distributor = create_distributor(
        name="Unique Reach TV",
        distributor_type="VMVPD",
        subscriber_measurement_method="AVERAGE_MONTHLY_UNIQUE",
        video_household_count=90000,
    )

    report = create_subscriber_report(
        station["id"],
        distributor["id"],
        reported_subscriber_count=100005,
        excluded_free_trial_count=2,
    )

    assert report["measurement_method_snapshot"] == "AVERAGE_MONTHLY_UNIQUE"
    assert report["adjusted_subscriber_count"] == 100003
    assert report["billable_subscriber_basis"] == 88003


def test_midpoint_extension_ranks_every_station_offer_by_round_number(api):
    """The rejected round-3 offer of 240 outranks the expired round-1 offer of 250.

    PRD §3.8: "Those candidates are ranked by `round_number` descending, and where
    two candidates share a `round_number`, by creation timestamp descending; the
    `base_rate_per_sub_cents` of the top-ranked candidate is the last station offer
    rate."

    PRD §3.8: "Under `MIDPOINT` it is the prior rate plus the last station offer
    rate, divided by two, with any remainder truncated toward negative infinity -
    the midpoint always floors and never rounds half up."

    Design: Corner/calculations/corner_midpoint_extension_ranks_station_offers_by_round_number
    """
    ctx = setup_negotiation_with_report()
    negotiation_id = ctx["negotiation"]["id"]
    station_id = ctx["station"]["id"]
    distributor_id = ctx["distributor"]["id"]
    report_id = ctx["report"]["id"]
    assert ctx["election"]["incumbent_rate_per_sub_cents"] == 220

    first = submit_station_offer(negotiation_id, station_id, report_id)
    submit_distributor_offer(
        negotiation_id,
        distributor_id,
        report_id,
        base_rate_per_sub_cents=200,
        escalator_bp_per_year=400,
        penetration_commitment_bp=3800,
    )
    third = submit_station_offer(
        negotiation_id,
        station_id,
        report_id,
        base_rate_per_sub_cents=240,
        penetration_commitment_bp=4100,
    )
    assert first["round_number"] == 1
    assert third["round_number"] == 3

    validate_success(
        api.reject_offer(
            third["id"],
            reject_offer_payload(
                rejection_reason="Rate still above our EXPANDED_BASIC budget"
            ),
            ctx["rep_headers"],
        ),
        200,
    )
    fourth = submit_distributor_offer(
        negotiation_id,
        distributor_id,
        report_id,
        base_rate_per_sub_cents=210,
        escalator_bp_per_year=500,
        penetration_commitment_bp=3900,
    )
    agreement = accept_offer(fourth["id"], negotiation_id)
    approve_network(agreement["id"])
    execute_agreement(agreement["id"])

    response = api.create_interim_extension(
        agreement["id"],
        create_interim_extension_payload(
            agreement_version(agreement["id"]),
            extension_days=30,
            extension_start_utc="2030-01-01T00:00:00Z",
            extension_rate_basis="MIDPOINT",
        ),
        ctx["negotiator_headers"],
    )
    extension = validate_success(response, 201)

    assert extension["effective_rate_per_sub_cents"] == 230
    assert extension["effective_rate_per_sub_cents"] != 235
    assert extension["effective_rate_per_sub_cents"] != 210
    assert extension["extension_end_utc"] == "2030-01-31T00:00:00Z"
    assert extension["status"] == "ACTIVE"

    assert read_offer(first["id"])["status"] == "EXPIRED"
    assert read_offer(third["id"])["status"] == "REJECTED"
    assert read_agreement(agreement["id"])["consumed_extension_days"] == 30
