"""Program design cycle, acceptance cascade (supersede + target_coc freeze +
setpoint recompute), feed-rate formula, OCC on accept, the delivery
program-accepted gate, and range_status judged against the accepted design."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    arrive_at_stop,
    bring_station_online,
    create_accepted_design,
    create_account,
    create_asset,
    create_pending_order,
    create_product,
    create_proposed_design,
    create_published_route,
    create_station,
    make_customer_contact_headers,
    record_result,
    schedule_order,
    set_clock,
    setup_commissioned_asset,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

MANAGER = TEST_USERS["manager_headers"]
CHEMIST = TEST_USERS["chemist_headers"]

# Feed-rate fixture shared by several tests: recirc 500 gpm, evaporation
# factor 0.0085, drift factor 0.0002, inhibitor target 5 ppm, active 10%,
# station cap 50 ml/min continuous.
FEED_ASSET = {"recirculation_rate_gpm": 500, "system_volume_gal": 9000}
FEED_PRODUCT = {"active_pct": 10, "container_size_gal": 55}
FEED_DESIGN = {"proposed_coc": 4.0, "inhibitor_target_ppm": 5,
               "ph_min": 7.0, "ph_max": 9.5, "conductivity_max_umhos": 4000}


def test_revision_cycle_increments_revision_number(api):
    """PRD §3.2: "A design's `revision_number` starts at 1 and increments by
    one each time the design cycles through `REVISE_REQUESTED` back to
    `SURVEYED`." "after which a `WaterChemist` reopens the survey, returning
    the design to `SURVEYED` and incrementing `revision_number` by one."

    Design: Difficulty/non_linear_state_machine/program_design_revision_cycle_increments_revision_number
    """
    account = create_account(account_name="Cycle Co")
    asset = create_asset(account["id"], asset_tag="CT-C", recirculation_rate_gpm=300)
    design = create_proposed_design(asset["id"])
    assert design["revision_number"] == 1

    validate_success(
        api_client.request_revision(design["id"], make_customer_contact_headers(account["id"]))
    )
    reopened = validate_success(api_client.reopen_survey(design["id"], CHEMIST))
    assert reopened["status"] == "SURVEYED"
    assert reopened["revision_number"] == 2, (
        f"one full revision loop must move revision_number 1 -> 2, got {reopened['revision_number']}"
    )


def test_revision_cycle_can_be_redrafted_and_accepted(api):
    """PRD §3.2: "The design's lifecycle is a cycle, not a line:
    `SURVEY_SCHEDULED` → `SURVEYED` → `DRAFTED` → `PROPOSED`, and from
    `PROPOSED` either forward to `ACCEPTED`, back into the cycle via
    `REVISE_REQUESTED`, or out to `WITHDRAWN`." "the asset's `target_coc` is
    frozen to the accepted `proposed_coc`".

    Design: Difficulty/non_linear_state_machine/program_design_revision_cycle_increments_revision_number
    """
    account = create_account(account_name="Cycle Co 2")
    asset = create_asset(account["id"], asset_tag="CT-C2", recirculation_rate_gpm=300)
    design = create_proposed_design(asset["id"], proposed_coc=4.0)

    validate_success(
        api_client.request_revision(design["id"], make_customer_contact_headers(account["id"]))
    )
    validate_success(api_client.reopen_survey(design["id"], CHEMIST))
    validate_success(
        api_client.draft_design(
            design["id"],
            {
                "proposed_coc": 5.0,
                "inhibitor_target_ppm": 6,
                "ph_min": 7.2,
                "ph_max": 9.0,
                "conductivity_max_umhos": 3500,
                "service_rate_cents_per_month": 1200,
            },
            CHEMIST,
        )
    )
    proposed = validate_success(api_client.propose_design(design["id"], CHEMIST))
    accepted = validate_success(
        api_client.accept_design(
            design["id"],
            {"expected_program_design_version": proposed["version"]},
            make_customer_contact_headers(account["id"]),
        )
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["revision_number"] == 2

    asset_after = validate_success(api_client.get_asset(asset["id"], CHEMIST))
    assert asset_after["target_coc"] == pytest.approx(5.0)


def test_accept_recomputes_station_setpoint_from_frozen_target_coc(api):
    """PRD §3.3: "Fifth, the clamp: the commanded `setpoint_ml_per_min` is the
    smaller of `capacity_cap_ml_per_min` and the greater of zero and the raw
    dose, stored to 4 decimal places rounded half up." PRD §3.2: "the asset's
    `target_coc` is frozen to the accepted `proposed_coc`, ending the 3.0
    baseline era; every feed station of the asset has its
    `setpoint_ml_per_min` recomputed by the feed-rate calculation of §3.3
    against the new target".

    Design: Difficulty/combinatorial_formula/feed_setpoint_mode_a_nested_minmax_mode_branch
    """
    set_clock("2026-08-01T00:00:00Z")
    account = create_account(account_name="Combo A")
    asset = create_asset(account["id"], asset_tag="CT-9", **FEED_ASSET)
    product = create_product(product_code="C2-INH", **FEED_PRODUCT,
                             unit_price_cents_per_gal=100, contract_price_cents_per_gal=90)
    station = create_station(asset["id"], product["id"], capacity_cap_ml_per_min=50,
                             feed_mode="CONTINUOUS")
    proposed = create_proposed_design(asset["id"], **FEED_DESIGN,
                                      service_rate_cents_per_month=1000)

    validate_success(
        api_client.accept_design(
            proposed["id"],
            {"expected_program_design_version": proposed["version"]},
            make_customer_contact_headers(account["id"]),
        )
    )

    station_after = validate_success(api_client.get_feed_station(station["id"], CHEMIST))
    # evaporation 4.25 gpm, drift 0.1, blowdown 4.25/3 - 0.1 = 1.3167 gpm;
    # raw = 5 * 1.3167 * 3785.411 / 1000 = 24.9206 ml/min; clamp not engaged.
    assert station_after["setpoint_ml_per_min"] == pytest.approx(24.9206, abs=1e-4)
    assert station_after["setpoint_ml_per_min"] < station_after["capacity_cap_ml_per_min"]


def test_accept_freezes_asset_target_coc(api):
    """PRD §3.2: "the asset's `target_coc` is frozen to the accepted
    `proposed_coc`, ending the 3.0 baseline era". PRD §3.2: "A new asset
    enters `COMMISSIONING`, starts with `posture` `COMPLIANT`, runs on a
    baseline `target_coc` of 3.0 cycles of concentration, and carries a
    `consecutive_out_of_range_count` of zero."

    Design: Difficulty/combinatorial_formula/feed_setpoint_mode_a_nested_minmax_mode_branch
    """
    set_clock("2026-08-01T00:00:00Z")
    account = create_account(account_name="Combo A2")
    asset = create_asset(account["id"], asset_tag="CT-9B", **FEED_ASSET)
    before = validate_success(api_client.get_asset(asset["id"], CHEMIST))
    assert before["target_coc"] == pytest.approx(3.0), "baseline before any acceptance"

    proposed = create_proposed_design(asset["id"], **FEED_DESIGN)
    validate_success(
        api_client.accept_design(
            proposed["id"],
            {"expected_program_design_version": proposed["version"]},
            make_customer_contact_headers(account["id"]),
        )
    )
    after = validate_success(api_client.get_asset(asset["id"], CHEMIST))
    assert after["target_coc"] == pytest.approx(4.0)


def test_accept_supersedes_prior_accepted_design(api):
    """PRD §3.2: "any *other* design of the same asset currently `ACCEPTED`
    transitions automatically to `SUPERSEDED`".

    Design: Difficulty/transitive_cascade/program_accept_cascade_depth3_supersede_and_setpoint_reprice
    """
    set_clock("2026-08-01T00:00:00Z")
    account = create_account(account_name="Supersede Co")
    asset = create_asset(account["id"], asset_tag="CT-S", **FEED_ASSET)
    d1 = create_accepted_design(asset["id"], account["id"], proposed_coc=3.0,
                                inhibitor_target_ppm=5, conductivity_max_umhos=4000)
    d2 = create_proposed_design(asset["id"], proposed_coc=4.0, inhibitor_target_ppm=5,
                                conductivity_max_umhos=4000)

    accepted = validate_success(
        api_client.accept_design(
            d2["id"],
            {"expected_program_design_version": d2["version"]},
            make_customer_contact_headers(account["id"]),
        )
    )
    assert accepted["status"] == "ACCEPTED"

    d1_after = validate_success(api_client.get_program_design(d1["id"], CHEMIST))
    assert d1_after["status"] == "SUPERSEDED"

    asset_after = validate_success(api_client.get_asset(asset["id"], CHEMIST))
    assert asset_after["target_coc"] == pytest.approx(4.0)


def test_accept_reprices_station_setpoint_through_cascade(api):
    """PRD §3.2: "every feed station of the asset has its
    `setpoint_ml_per_min` recomputed by the feed-rate calculation of §3.3
    against the new target". PRD §3.3: "the required blowdown flow is the
    greater of zero and the quantity: the evaporation flow divided by
    (`target_coc` minus one), minus the drift flow".

    Design: Difficulty/transitive_cascade/program_accept_cascade_depth3_supersede_and_setpoint_reprice
    """
    set_clock("2026-08-01T00:00:00Z")
    account = create_account(account_name="Supersede Co 2")
    asset = create_asset(account["id"], asset_tag="CT-S2", **FEED_ASSET)
    product = create_product(product_code="SUP-INH", **FEED_PRODUCT,
                             unit_price_cents_per_gal=100, contract_price_cents_per_gal=90)
    station = create_station(asset["id"], product["id"], capacity_cap_ml_per_min=50,
                             feed_mode="CONTINUOUS")
    d1 = create_accepted_design(asset["id"], account["id"], proposed_coc=3.0,
                                inhibitor_target_ppm=5, conductivity_max_umhos=4000)
    mid = validate_success(api_client.get_feed_station(station["id"], CHEMIST))
    # Under target_coc 3.0: blowdown = 4.25/2 - 0.1 = 2.025; raw = 38.3273 ml/min.
    assert mid["setpoint_ml_per_min"] == pytest.approx(38.3273, abs=1e-4)

    d2 = create_proposed_design(asset["id"], proposed_coc=4.0, inhibitor_target_ppm=5,
                                conductivity_max_umhos=4000)
    validate_success(
        api_client.accept_design(
            d2["id"],
            {"expected_program_design_version": d2["version"]},
            make_customer_contact_headers(account["id"]),
        )
    )
    after = validate_success(api_client.get_feed_station(station["id"], CHEMIST))
    assert after["setpoint_ml_per_min"] == pytest.approx(24.9206, abs=1e-4)


def test_occ_stale_version_on_program_accept(api):
    """PRD §2.7: "A `POST /wt/program-designs/{designId}/accept` request must
    carry `expected_program_design_version` equal to the design's current
    `version`."; "if that value no longer equals the entity's current
    `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.2: "the accepted design's own `version` increments by one."

    Design: Corner/cross_cutting_layers/occ_stale_version_on_program_accept
    """
    account = create_account(account_name="OCC Co")
    asset = create_asset(account["id"], asset_tag="CT-X1", asset_type="BOILER",
                         recirculation_rate_gpm=100, system_volume_gal=500)
    proposed = create_proposed_design(asset["id"], proposed_coc=3.0)
    stale_version = proposed["version"]

    # Advance the design through a full revision cycle (every mutation bumps version).
    validate_success(
        api_client.request_revision(proposed["id"], make_customer_contact_headers(account["id"]))
    )
    validate_success(api_client.reopen_survey(proposed["id"], CHEMIST))
    validate_success(
        api_client.draft_design(
            proposed["id"],
            {
                "proposed_coc": 3.5,
                "inhibitor_target_ppm": 4,
                "ph_min": 7.0,
                "ph_max": 9.5,
                "conductivity_max_umhos": 3000,
                "service_rate_cents_per_month": 0,
            },
            CHEMIST,
        )
    )
    current = validate_success(api_client.propose_design(proposed["id"], CHEMIST))

    resp = api_client.accept_design(
        proposed["id"],
        {"expected_program_design_version": stale_version},
        make_customer_contact_headers(account["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert resp.status_code == 412

    accepted = validate_success(
        api_client.accept_design(
            proposed["id"],
            {"expected_program_design_version": current["version"]},
            make_customer_contact_headers(account["id"]),
        )
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["version"] == current["version"] + 1


def test_delivery_schedule_rejected_while_design_not_accepted(api):
    """PRD §3.9: "the destination station's asset must have an `ACCEPTED`
    program design (`ERR_PROGRAM_NOT_ACCEPTED`)".

    Design: Difficulty/cross_entity_state_dependency/delivery_schedule_requires_program_accepted
    """
    set_clock("2026-08-01T00:00:00Z")
    account = create_account(account_name="XDep Co")
    asset = create_asset(account["id"], asset_tag="CT-X7", recirculation_rate_gpm=300)
    product = create_product()
    station = create_station(asset["id"], product["id"], capacity_cap_ml_per_min=50)
    bring_station_online(station["id"])
    # Design reaches PROPOSED but is never accepted.
    create_proposed_design(asset["id"], proposed_coc=3.0)

    order = create_pending_order(account["id"], station["id"], 55)
    resp = api_client.schedule_delivery_order(
        order["id"],
        {"scheduled_for": "2026-08-10T00:00:00Z",
         "expected_delivery_order_version": order["version"]},
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACCEPTED)
    assert resp.status_code == 409

    after = validate_success(api_client.get_delivery_order(order["id"], MANAGER))
    assert after["status"] == "PENDING"


def test_delivery_schedule_succeeds_after_design_accepted(api):
    """PRD §3.9: "A successful schedule stores the supplied `scheduled_for`
    and increments the order's `version` by one."

    Design: Difficulty/cross_entity_state_dependency/delivery_schedule_requires_program_accepted
    """
    set_clock("2026-08-01T00:00:00Z")
    account = create_account(account_name="XDep Co 2")
    asset = create_asset(account["id"], asset_tag="CT-X8", recirculation_rate_gpm=300)
    product = create_product()
    station = create_station(asset["id"], product["id"], capacity_cap_ml_per_min=50)
    bring_station_online(station["id"])
    proposed = create_proposed_design(asset["id"], proposed_coc=3.0)

    order = create_pending_order(account["id"], station["id"], 55)
    blocked = api_client.schedule_delivery_order(
        order["id"],
        {"scheduled_for": "2026-08-10T00:00:00Z",
         "expected_delivery_order_version": order["version"]},
        MANAGER,
    )
    validate_error(blocked, ApiErrorId.ERR_PROGRAM_NOT_ACCEPTED)

    validate_success(
        api_client.accept_design(
            proposed["id"],
            {"expected_program_design_version": proposed["version"]},
            make_customer_contact_headers(account["id"]),
        )
    )
    fresh = validate_success(api_client.get_delivery_order(order["id"], MANAGER))
    scheduled = schedule_order(order["id"], "2026-08-10T00:00:00Z", fresh["version"])
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["scheduled_for"].startswith("2026-08-10T00:00:00")


def test_field_constraint_coc_out_of_band(api):
    """PRD §2.6 tier 10: "`proposed_coc` must lie between 1.5 and 12.0
    inclusive" — violations fail with `ERR_FIELD_CONSTRAINT` (HTTP 422).

    Design: Corner/validations/field_constraint_coc_out_of_band
    """
    account = create_account(account_name="Band Co")
    asset = create_asset(account["id"], asset_tag="CT-V2", asset_type="BOILER",
                         recirculation_rate_gpm=100, system_volume_gal=500)
    design = validate_success(
        api_client.create_program_design({"asset_id": asset["id"]}, CHEMIST),
        expected_status=201,
    )
    validate_success(api_client.record_survey(design["id"], {"survey_notes": "s"}, CHEMIST))

    resp = api_client.draft_design(
        design["id"],
        {
            "proposed_coc": 13.0,
            "inhibitor_target_ppm": 4,
            "ph_min": 7.0,
            "ph_max": 9.5,
            "conductivity_max_umhos": 3000,
            "service_rate_cents_per_month": 0,
        },
        CHEMIST,
    )
    validate_error(resp, ApiErrorId.ERR_FIELD_CONSTRAINT)
    assert resp.status_code == 422

    after = validate_success(api_client.get_program_design(design["id"], CHEMIST))
    assert after["status"] == "SURVEYED"


def test_range_status_filters_by_accepted_design_ranges(api):
    """PRD §3.4: "Every result also carries a `range_status`, `IN_RANGE` or
    `OUT_OF_RANGE`, judged against the asset's accepted control ranges — the
    `ph_min`/`ph_max` band, `conductivity_max_umhos`, and
    `inhibitor_target_ppm` of the asset's `ACCEPTED` program design."
    PRD §3.5: "When a result is created with `range_status` `IN_RANGE`, the
    counter is reset to 0 and the posture is recomputed".

    Design: Corner/calculations/range_status_filters_by_accepted_design_ranges
    """
    subtree = setup_commissioned_asset(
        account_name="Range Co",
        design_overrides={"proposed_coc": 3.0, "inhibitor_target_ppm": 4,
                          "ph_min": 7.0, "ph_max": 9.5, "conductivity_max_umhos": 3000},
    )
    account_id, asset_id = subtree["account"]["id"], subtree["asset"]["id"]
    route, stops = create_published_route(
        account_id,
        asset_id,
        [("2026-08-02T00:00:00Z", "2026-08-02T06:00:00Z"),
         ("2026-08-02T06:00:00Z", "2026-08-02T12:00:00Z")],
    )
    # ph 9.8 exceeds the accepted band's ph_max 9.5 -> OUT_OF_RANGE.
    set_clock("2026-08-02T01:00:00Z")
    first = arrive_and_record_out_of_range_ph(stops[0]["id"], asset_id)
    assert first["range_status"] == "OUT_OF_RANGE"

    # Supersede with a wider band [7.0, 10.0]; the same ph 9.8 is now in range.
    d2 = create_proposed_design(asset_id, proposed_coc=3.0, inhibitor_target_ppm=4,
                                ph_min=7.0, ph_max=10.0, conductivity_max_umhos=3000)
    validate_success(
        api_client.accept_design(
            d2["id"],
            {"expected_program_design_version": d2["version"]},
            make_customer_contact_headers(account_id),
        )
    )
    set_clock("2026-08-02T07:00:00Z")
    second = arrive_and_record_out_of_range_ph(stops[1]["id"], asset_id)
    assert second["range_status"] == "IN_RANGE"

    asset_after = validate_success(api_client.get_asset(asset_id, CHEMIST))
    assert asset_after["consecutive_out_of_range_count"] == 0


def arrive_and_record_out_of_range_ph(stop_id, asset_id):
    """ph 9.8 with all other measurements comfortably mid-band."""
    arrive_at_stop(stop_id)
    return record_result(
        stop_id,
        asset_id,
        ph=9.8,
        conductivity_umhos=2000,
        calcium_ppm=300,
        alkalinity_ppm=150,
        temperature_f=90,
        inhibitor_residual_ppm=4,
    )
