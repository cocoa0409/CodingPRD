"""Corner cases in the program's derived quantities.

Documentation completeness over an empty and a partially covered required-class
list, brand carry-forward across a predecessor chain, the odometer replay that
flags a rollback, and the empty-set convention of the record-keeping score.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    file_parts_document,
    license_rebuilder,
    read_application,
    read_parts_document,
    read_rebuilder,
    read_title,
    read_vehicle,
    record_conveyance,
    setup_draft_application,
    setup_salvage_titled_vehicle,
    validate_paginated,
    validate_success,
    verify_parts_document,
)

ADMIN_HEADERS = TEST_USERS["program_admin_headers"]


def test_trailer_documentation_completeness_is_vacuously_one_hundred():
    """A trailer requires no part classes, so its package reads complete at once.

    PRD: "A `TRAILER` requires none at all, and an empty required list is vacuously complete, so a trailer's `documentation_completeness_pct` is 100.00 from the moment the application exists."

    Design: Corner/calculations/documentation_completeness_is_vacuously_one_hundred_for_a_trailer
    """
    env = setup_draft_application(body_class="TRAILER", declared_repair_cost_cents=320_000)
    application = env["application"]

    assert application["status"] == "DRAFT", (
        f"expected DRAFT, got {application['status']} for a freshly opened application"
    )
    assert application["documentation_completeness_pct"] == pytest.approx(100.00, abs=0.01), (
        "a trailer requires no part classes, so expected 100.00, got "
        f"{application['documentation_completeness_pct']}"
    )
    assert application["documented_parts_cost_cents"] == 0, (
        f"expected 0, got {application['documented_parts_cost_cents']} with no documents on file"
    )
    assert application["photo_view_count"] == 0, (
        f"expected 0, got {application['photo_view_count']} with no photographs on file"
    )

    read_back = read_application(env["application_id"])
    assert read_back["documentation_completeness_pct"] == pytest.approx(100.00, abs=0.01), (
        "the vacuous completeness must survive a re-read, got "
        f"{read_back['documentation_completeness_pct']}"
    )

    documents, meta = validate_paginated(
        api_client.list_parts_documents(
            ADMIN_HEADERS, {"application_id": env["application_id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"expected 0 parts documents, got {meta['total_count']} on the trailer application"
    )
    assert documents == [], f"expected no parts document rows, got {len(documents)}"


def test_motorcycle_completeness_counts_only_verified_part_classes():
    """A motorcycle with only its lighting receipt verified sits at half coverage.

    PRD: "When the required list is non-empty, the program counts how many of the required classes are covered — a class counts as covered when at least one document of this application has that `part_class` and `status` of `VERIFIED` — then divides the covered count by the size of the required list, multiplies by 100 and rounds half up to two decimal places."

    Design: Corner/calculations/motorcycle_completeness_is_fifty_percent_with_only_lighting_verified
    """
    env = setup_draft_application(body_class="MOTORCYCLE")
    structural = file_parts_document(
        env["application_id"],
        env["rebuilder_id"],
        doc_type="RECEIPT",
        part_class="STRUCTURAL",
        source_type="NEW",
        amount_cents=150_000,
    )
    lighting = file_parts_document(
        env["application_id"],
        env["rebuilder_id"],
        doc_type="RECEIPT",
        part_class="LIGHTING",
        source_type="NEW",
        amount_cents=20_000,
    )

    verified = verify_parts_document(lighting["id"], env["inspector_id"])
    assert verified["status"] == "VERIFIED", (
        f"expected VERIFIED, got {verified['status']} after the inspector accepted the lamp receipt"
    )
    assert read_parts_document(structural["id"])["status"] == "SUBMITTED", (
        "the structural receipt must still be SUBMITTED, got "
        f"{read_parts_document(structural['id'])['status']}"
    )

    application = read_application(env["application_id"])
    assert application["documentation_completeness_pct"] == pytest.approx(50.00, abs=0.01), (
        "one of two required classes is verified, so expected 50.00, got "
        f"{application['documentation_completeness_pct']}"
    )
    assert application["documented_parts_cost_cents"] == 20_000, (
        "only the verified lamp receipt may count, expected 20000, got "
        f"{application['documented_parts_cost_cents']}"
    )

    rows, meta = validate_paginated(
        api_client.list_parts_documents(
            ADMIN_HEADERS,
            {"application_id": env["application_id"], "status": "VERIFIED"},
        )
    )
    assert meta["total_count"] == 1, (
        f"expected exactly 1 verified document, got {meta['total_count']}"
    )
    assert rows[0]["id"] == lighting["id"], (
        f"expected the lamp receipt {lighting['id']}, got {rows[0]['id']}"
    )


def test_conveyance_carries_the_most_severe_brand_on_the_chain():
    """Selling a salvage-branded car mints a successor title that still says SALVAGE.

    PRD: "Otherwise `carried_brand_code` is the single member of the set with the highest brand severity; because the five severity values are distinct integers, that maximum is unique and no tie-break is required."

    Design: Corner/calculations/brand_carry_forward_takes_the_max_severity_across_the_predecessor_chain
    """
    env = setup_salvage_titled_vehicle(report_overrides={"odometer_reading_miles": 68_000})
    assert env["salvage_title"]["brand_code"] == "SALVAGE", (
        f"setup expected a SALVAGE title, got {env['salvage_title']['brand_code']}"
    )

    transfer = record_conveyance(
        env["salvage_title_id"],
        buyer_name="Nolan Pryce",
        # At the logical clock exactly, and at the outgoing title's issued_at, so the
        # conveyance's effective instant is "at or before the logical clock" and its
        # disclosure therefore enters the vehicle's last_odometer_miles.
        transfer_effective_at="2026-08-01T00:00:00Z",
        odometer_reading_miles=68_500,
        sale_price_cents=250_000,
    )

    assert transfer["carried_brand_code"] == "SALVAGE", (
        f"expected SALVAGE carried forward, got {transfer['carried_brand_code']}"
    )
    assert transfer["odometer_flag"] == "OK", (
        f"68500 miles exceeds the prior 68000, expected OK, got {transfer['odometer_flag']}"
    )
    assert transfer["status"] == "RECORDED", (
        f"expected RECORDED, got {transfer['status']} for an accepted conveyance"
    )

    outgoing = read_title(env["salvage_title_id"])
    assert outgoing["status"] == "SUPERSEDED", (
        f"expected SUPERSEDED, got {outgoing['status']} after the successor was minted"
    )
    assert outgoing["is_current"] is False, (
        f"expected is_current false, got {outgoing['is_current']} on the superseded title"
    )

    successor = read_title(transfer["to_title_id"])
    assert successor["brand_code"] == "SALVAGE", (
        f"expected the successor to carry SALVAGE, got {successor['brand_code']}"
    )
    assert successor["brand_severity"] == 30, (
        f"SALVAGE sits at severity 30, got {successor['brand_severity']}"
    )
    assert successor["brand_history"] == ["SALVAGE"], (
        f"expected ['SALVAGE'], got {successor['brand_history']} on the successor title"
    )
    assert successor["predecessor_title_id"] == env["salvage_title_id"], (
        f"expected predecessor {env['salvage_title_id']}, got {successor['predecessor_title_id']}"
    )
    assert successor["transfer_sequence"] == 1, (
        f"the successor sits one row down the chain, expected 1, got {successor['transfer_sequence']}"
    )
    assert successor["is_current"] is True, (
        f"expected is_current true, got {successor['is_current']} on the new title"
    )

    vehicle = read_vehicle(env["vehicle_id"])
    assert vehicle["last_odometer_miles"] == 68_500, (
        f"expected 68500, got {vehicle['last_odometer_miles']} after the conveyance disclosure"
    )
    assert vehicle["fraud_hold"] == "NONE", (
        f"an increasing odometer raises nothing, expected NONE, got {vehicle['fraud_hold']}"
    )


def test_conveyance_below_the_prior_reading_is_flagged_as_a_rollback():
    """A sale disclosing fewer miles than the carrier saw is stamped as suspected rollback.

    PRD: "Otherwise the program takes the highest `odometer_reading_miles` among the retained prior events and compares the new disclosure against it: the tolerance is zero miles, so `odometer_flag` is `ROLLBACK_SUSPECTED` exactly when the new `odometer_reading_miles` is strictly less than that prior maximum, and `OK` when it equals or exceeds it."

    Design: Corner/calculations/odometer_rollback_on_transfer_flags_the_transfer_and_opens_an_auto_referral
    """
    env = setup_salvage_titled_vehicle(report_overrides={"odometer_reading_miles": 68_000})

    transfer = record_conveyance(
        env["salvage_title_id"],
        buyer_name="Nolan Pryce",
        transfer_effective_at="2026-08-05T00:00:00Z",
        odometer_reading_miles=60_000,
        sale_price_cents=250_000,
    )

    assert transfer["odometer_flag"] == "ROLLBACK_SUSPECTED", (
        "60000 miles is strictly below the prior maximum of 68000, expected "
        f"ROLLBACK_SUSPECTED, got {transfer['odometer_flag']}"
    )
    assert transfer["status"] == "RECORDED", (
        f"the conveyance is recorded, not refused, expected RECORDED, got {transfer['status']}"
    )
    assert transfer["carried_brand_code"] == "SALVAGE", (
        f"expected SALVAGE carried forward, got {transfer['carried_brand_code']}"
    )


def test_odometer_rollback_opens_an_auto_cascade_referral():
    """A suspected rollback raises an odometer referral and puts the vehicle on hold.

    PRD: "And when `odometer_flag` comes out `ROLLBACK_SUSPECTED`, it synthesises a fraud referral with `referral_type` of `ODOMETER` and `origin` of `AUTO_CASCADE`, which drives the vehicle's `fraud_hold` to `UNDER_REFERRAL`, which in turn cancels every attempt still in `SCHEDULED` belonging to that vehicle's non-terminal applications."

    Design: Corner/calculations/odometer_rollback_on_transfer_flags_the_transfer_and_opens_an_auto_referral
    """
    env = setup_salvage_titled_vehicle(report_overrides={"odometer_reading_miles": 68_000})

    transfer = record_conveyance(
        env["salvage_title_id"],
        buyer_name="Nolan Pryce",
        transfer_effective_at="2026-08-05T00:00:00Z",
        odometer_reading_miles=60_000,
        sale_price_cents=250_000,
    )
    assert transfer["odometer_flag"] == "ROLLBACK_SUSPECTED", (
        f"setup expected ROLLBACK_SUSPECTED, got {transfer['odometer_flag']}"
    )

    referrals, meta = validate_paginated(
        api_client.list_fraud_referrals(ADMIN_HEADERS, {"vehicle_id": env["vehicle_id"]})
    )
    assert meta["total_count"] == 1, (
        f"expected exactly 1 synthesised referral, got {meta['total_count']}"
    )
    referral = referrals[0]
    assert referral["referral_type"] == "ODOMETER", (
        f"expected ODOMETER, got {referral['referral_type']} on the cascaded referral"
    )
    assert referral["origin"] == "AUTO_CASCADE", (
        f"expected AUTO_CASCADE, got {referral['origin']} on the cascaded referral"
    )
    assert referral["status"] == "OPEN", (
        f"expected OPEN, got {referral['status']} on a freshly synthesised referral"
    )

    vehicle = read_vehicle(env["vehicle_id"])
    assert vehicle["fraud_hold"] == "UNDER_REFERRAL", (
        f"expected UNDER_REFERRAL, got {vehicle['fraud_hold']} after the rollback cascade"
    )


def test_rebuilder_with_no_parts_paperwork_scores_one_hundred():
    """A rebuilder who has never filed a part reads a perfect record-keeping grade.

    PRD: "Within the chosen set, if there are no documents at all the score is 100.00 by convention."

    Design: Corner/calculations/recordkeeping_score_with_no_documents_is_one_hundred
    """
    rebuilder = license_rebuilder()

    data = validate_success(api_client.get_rebuilder(rebuilder["id"], ADMIN_HEADERS))

    assert data["recordkeeping_score_rolling"] == pytest.approx(100.00, abs=0.01), (
        "the empty document set scores 100.00 by convention, got "
        f"{data['recordkeeping_score_rolling']}"
    )
    assert data["recordkeeping_score_lifetime"] == pytest.approx(100.00, abs=0.01), (
        "the empty lifetime set scores 100.00 by convention, got "
        f"{data['recordkeeping_score_lifetime']}"
    )
    assert data["license_status"] == "ACTIVE", (
        f"a newly licensed rebuilder starts ACTIVE, got {data['license_status']}"
    )

    fresh = read_rebuilder(rebuilder["id"])
    assert fresh["recordkeeping_score_rolling"] == pytest.approx(100.00, abs=0.01), (
        f"every single-rebuilder read reports the convention, got {fresh['recordkeeping_score_rolling']}"
    )
