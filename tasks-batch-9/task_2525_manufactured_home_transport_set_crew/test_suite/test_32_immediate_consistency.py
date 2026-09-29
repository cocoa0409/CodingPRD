"""Every derived field is already correct in the response that wrote it.

The API is immediately consistent: the resource object returned by a write
carries the recomputed verdicts, counters and balances, and an immediately
following read returns exactly the same figures (PRD §2.2, §3.3, §3.9).
"""

from test_helpers import (
    SITE_INSPECTOR_USER_ID,
    adjudicate_damage_claim_payload,
    api_client,
    assert_allocation_sums_exactly,
    make_claims_adjuster_headers,
    make_inspector_headers,
    open_damage_claim,
    open_order,
    read_order_summary,
    readiness_inspection_payload,
    record_section,
    register_hauler,
    register_plant,
    register_set_crew,
    register_site,
    review_damage_claim,
    set_logical_clock,
    validate_success,
)


def test_a_readiness_verdict_is_already_recomputed_in_the_response_that_wrote_it():
    """PRD §3.3: "`blocking_defect_count` is then the number of those three
    dimensions that are **not** satisfied, so it always lands between 0 and 3
    inclusive, and the site reads `READY` when the count is 0 and
    `READINESS_FAILED` otherwise." PRD §2.2: "Unless otherwise noted, operations
    that create or modify a resource will return the created or updated resource
    object in the data field."

    Design: Corner/consistency_model/immediate_consistency_derived_fields_visible_in_the_writing_response
    """
    set_logical_clock()
    plant = register_plant(state_code="AZ")
    order = open_order(plant["id"], section_count=1, destination_state="AZ", wind_zone="I")
    record_section(order["id"], plant["id"], section_index=1)
    site = register_site(order["id"], pad_type="RUNNER", pier_count=6)
    inspector = make_inspector_headers(SITE_INSPECTOR_USER_ID)

    assert site["readiness_status"] == "READINESS_PENDING", (
        f"a new site opens at READINESS_PENDING, got {site['readiness_status']}"
    )
    assert site["inspection_round"] == 0, (
        f"a new site opens with inspection_round at 0, got {site['inspection_round']}"
    )
    assert site["blocking_defect_count"] == 0, (
        f"a new site opens with blocking_defect_count at 0, got {site['blocking_defect_count']}"
    )
    assert site["last_inspector_user_id"] is None, (
        f"a new site opens with last_inspector_user_id null, got {site['last_inspector_user_id']}"
    )

    failed = validate_success(
        api_client.inspect_site_readiness(
            site["id"], readiness_inspection_payload(pier_plan_pass=False), inspector
        ),
        200,
    )
    assert failed["readiness_status"] == "READINESS_FAILED", (
        "the writing response already carries the failed verdict, got "
        f"{failed['readiness_status']}"
    )
    assert failed["blocking_defect_count"] == 1, (
        "only the pier-plan dimension is unsatisfied, expected 1, got "
        f"{failed['blocking_defect_count']}"
    )
    assert failed["inspection_round"] == 1, (
        f"the first inspection is round 1, got {failed['inspection_round']}"
    )
    assert failed["last_inspector_user_id"] == SITE_INSPECTOR_USER_ID, (
        "the acting principal is stamped in the same response, got "
        f"{failed['last_inspector_user_id']}"
    )

    read_back = validate_success(api_client.get_site(site["id"], inspector), 200)
    for field in (
        "readiness_status",
        "blocking_defect_count",
        "inspection_round",
        "last_inspector_user_id",
        "version",
    ):
        assert read_back[field] == failed[field], (
            f"the immediately following read must agree on {field}: wrote "
            f"{failed[field]}, read {read_back[field]}"
        )

    unbooked = validate_success(api_client.get_order(order["id"], inspector), 200)
    assert unbooked["posture"] == "OPEN", (
        "with no set job booked the unready site leaves the order at OPEN, got "
        f"{unbooked['posture']}"
    )

    passed = validate_success(
        api_client.inspect_site_readiness(
            site["id"], readiness_inspection_payload(), inspector
        ),
        200,
    )
    assert passed["readiness_status"] == "READY", (
        f"a clean re-inspection moves READINESS_FAILED -> READY, got {passed['readiness_status']}"
    )
    assert passed["blocking_defect_count"] == 0, (
        f"a clean verdict writes 0 defects, got {passed['blocking_defect_count']}"
    )
    assert passed["inspection_round"] == 2, (
        f"the re-inspection is round 2, got {passed['inspection_round']}"
    )

    read_again = validate_success(api_client.get_site(site["id"], inspector), 200)
    for field in ("readiness_status", "blocking_defect_count", "inspection_round", "version"):
        assert read_again[field] == passed[field], (
            f"the immediately following read must agree on {field}: wrote "
            f"{passed[field]}, read {read_again[field]}"
        )


def test_an_adjudication_response_already_carries_the_ledger_move_it_caused():
    """PRD §3.9: "Second, because the allocation was posted, the affected trading
    partners' `chargeback_balance_cents` are recomputed — under the `STAGE` basis
    this touches the single charged party, under the `EVIDENCE` basis all three —
    and `Plant.status`, `Hauler.status` and `SetCrew.status` are refreshed."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."

    Design: Corner/consistency_model/immediate_consistency_derived_fields_visible_in_the_writing_response
    """
    set_logical_clock()
    plant = register_plant(state_code="AZ")
    hauler = register_hauler(endorsed_states=["AZ"])
    set_crew = register_set_crew()
    order = open_order(plant["id"], section_count=1, destination_state="AZ", wind_zone="I")
    section = record_section(order["id"], plant["id"], section_index=1)
    adjuster = make_claims_adjuster_headers()

    claim = open_damage_claim(
        order["id"],
        section["id"],
        hauler["id"],
        set_crew["id"],
        headers=adjuster,
        discovered_stage="PLANT_QC",
        claimed_amount_cents=100000,
        blocks_set=False,
    )
    review_damage_claim(claim["id"])

    settled = validate_success(
        api_client.adjudicate_damage_claim(
            claim["id"], adjudicate_damage_claim_payload("STAGE"), adjuster
        ),
        200,
    )
    assert settled["status"] == "ADJUDICATED", (
        f"the writing response already reads ADJUDICATED, got {settled['status']}"
    )
    assert settled["allocation_basis"] == "STAGE", (
        f"the chosen basis is written back, got {settled['allocation_basis']}"
    )
    assert settled["approved_amount_cents"] == 90000, (
        "ninety percent of 100000 cents is 90000, got "
        f"{settled['approved_amount_cents']}"
    )
    assert settled["plant_charge_cents"] == 90000, (
        "damage found at PLANT_QC is charged wholly to the plant, got "
        f"{settled['plant_charge_cents']}"
    )
    assert settled["hauler_charge_cents"] == 0, (
        f"the other two charges stay at 0, got {settled['hauler_charge_cents']}"
    )
    assert settled["installer_charge_cents"] == 0, (
        f"the other two charges stay at 0, got {settled['installer_charge_cents']}"
    )
    assert_allocation_sums_exactly(settled)

    read_back = validate_success(api_client.get_damage_claim(claim["id"], adjuster), 200)
    for field in (
        "status",
        "allocation_basis",
        "approved_amount_cents",
        "plant_charge_cents",
        "hauler_charge_cents",
        "installer_charge_cents",
        "version",
    ):
        assert read_back[field] == settled[field], (
            f"the immediately following read must agree on {field}: wrote "
            f"{settled[field]}, read {read_back[field]}"
        )

    charged = validate_success(api_client.get_plant(plant["id"], adjuster), 200)
    assert charged["chargeback_balance_cents"] == 90000, (
        "the plant's balance is visible on the very next read, expected 90000, got "
        f"{charged['chargeback_balance_cents']}"
    )
    assert charged["status"] == "ACTIVE", (
        f"90000 cents is far below the probation line, got {charged['status']}"
    )

    summary = read_order_summary(order["id"])
    assert summary["network_chargeback_cents"] == 90000, (
        "the conserved network total is visible immediately, expected 90000, got "
        f"{summary['network_chargeback_cents']}"
    )
