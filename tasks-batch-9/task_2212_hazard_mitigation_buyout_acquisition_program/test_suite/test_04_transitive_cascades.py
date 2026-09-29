"""Transitive cascades: one call travelling four levels, constructively and destructively."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories, fixtures
from test_helpers.test_users import TEST_USERS, make_subrecipient_coordinator_headers


# ─── The constructive cascade: recording the deed ─────────────────────────────

DEMOLITION_TONNAGE = {"total_debris_tons": 40.00, "recycled_tons": 20.00}

RECORDING_INPUTS = {
    "recording_reference": "BK1234-PG567",
    "maintenance_responsible_party": "Riverbend Parks Department",
}


def _demolished_parcel_of_one_and_a_quarter_acres(api):
    return fixtures.parcel_demolished(
        api,
        parcel_overrides={"acreage": 1.25},
        complete_overrides=DEMOLITION_TONNAGE,
    )


def _record_the_deed(api, state):
    closing = validate_success(
        api.record_closing_deed(
            state["closing"]["id"],
            factories.record_deed_payload(state["closing"]["id"], **RECORDING_INPUTS),
            make_subrecipient_coordinator_headers(state["project"]["id"]),
        )
    )
    restrictions, _meta = validate_paginated(
        api.list_deed_restrictions(
            TEST_USERS["program_administrator_headers"],
            params={"parcel_id": state["parcel"]["id"]},
        )
    )
    return closing, restrictions


def test_recording_the_deed_creates_a_restriction_that_did_not_exist_before(api):
    """One recording call mints the perpetual restriction with its own derived clock.

    "Link one creates a `DeedRestriction`, described in §3.8."

    "The restriction records the `parcel_id` it encumbers, the
    `closing_record_id` whose recording produced it, a `restriction_type` that
    can only ever be `OPEN_SPACE_PERPETUAL`, a `prohibited_uses` array copied as
    the four codes `NEW_STRUCTURE`, `FILL_PLACEMENT`, `RESALE_FOR_DEVELOPMENT`
    and `PERMANENT_STORAGE`, a `recorded_on` taken as the date part of the
    logical clock at the recording call, a `monitoring_interval_months` of 36,
    and the `maintenance_responsible_party` supplied at recording."

    "At creation the anchor is `recorded_on`."

    Design: Difficulty/transitive_cascade/deed_recording_cascades_four_levels_into_project_open_space_acreage
    """
    state = _demolished_parcel_of_one_and_a_quarter_acres(api)
    assert float(state["work_order"]["diversion_pct"]) == 50.00

    closing, restrictions = _record_the_deed(api, state)

    assert closing["status"] == "RECORDED"
    assert closing["recording_reference"] == "BK1234-PG567"
    assert closing["purchase_price_cents"] == 21_400_000

    assert len(restrictions) == 1
    restriction = restrictions[0]
    assert restriction["status"] == "RECORDED"
    assert restriction["restriction_type"] == "OPEN_SPACE_PERPETUAL"
    assert restriction["recorded_on"] == "2026-08-01"
    assert restriction["monitoring_interval_months"] == 36
    assert restriction["next_monitoring_due_date"] == "2029-08-01"
    assert restriction["maintenance_responsible_party"] == "Riverbend Parks Department"
    assert len(restriction["prohibited_uses"]) == 4
    assert sorted(restriction["prohibited_uses"]) == sorted(
        ["NEW_STRUCTURE", "FILL_PLACEMENT", "RESALE_FOR_DEVELOPMENT", "PERMANENT_STORAGE"]
    )


def test_the_project_acreage_only_moves_once_the_new_restriction_exists(api):
    """The fourth level is unreachable until the second level's row is created.

    "Link two: the creation of that restriction moves the parcel's
    `acquisition_status` from `DEMOLISHED` to `OPEN_SPACE_RECORDED`. Link three:
    the parcel arriving at `OPEN_SPACE_RECORDED` recomputes the project's
    `protected_open_space_acres`."

    "`protected_open_space_acres` is the sum of `acreage` over every parcel of
    the project whose `acquisition_status` is `OPEN_SPACE_RECORDED` and whose
    deed restriction has a `status` **other than** `TERMINATED` - that is,
    `RECORDED`, `IN_COMPLIANCE`, `VIOLATION_OPEN` or `CURED` all count."

    Design: Difficulty/transitive_cascade/deed_recording_cascades_four_levels_into_project_open_space_acreage
    """
    state = _demolished_parcel_of_one_and_a_quarter_acres(api)

    before = validate_success(
        api.get_mitigation_project(
            state["project"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert float(before["protected_open_space_acres"]) == 0.00

    _record_the_deed(api, state)

    parcel = validate_success(
        api.get_parcel(
            state["parcel"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert parcel["acquisition_status"] == "OPEN_SPACE_RECORDED"

    after = validate_success(
        api.get_mitigation_project(
            state["project"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert float(after["protected_open_space_acres"]) == 1.25


# ─── The destructive cascade: withdrawing after confirming ────────────────────

def _withdraw_participation(api, state):
    return validate_success(
        api.record_participation(
            state["parcel"]["id"],
            factories.participation_payload(state["parcel"]["id"], "WITHDRAW"),
            make_subrecipient_coordinator_headers(state["project"]["id"]),
        )
    )


def test_withdrawing_cancels_the_acquisition_dimension_and_kills_the_presented_offer(api):
    """The withdrawal travels from participation through acquisition into the offer.

    "From `VOLUNTARY_CONFIRMED` a decision of `WITHDRAW` moves
    `participation_status` to `WITHDRAWN`, which is terminal - there is no path
    out."

    "Otherwise the withdrawal runs the same cascade as a decline from
    `INTERESTED` - `acquisition_status` to `ACQUISITION_CANCELLED` when it is in
    one of the five pre-closing states, all `DRAFT` and `PRESENTED` offers on the
    parcel to `WITHDRAWN`, each releasing its federal share out of
    `federal_obligated_cents`."

    Design: Difficulty/transitive_cascade/participation_withdrawal_cascades_four_levels_into_federal_deobligation
    """
    state = fixtures.parcel_with_presented_offer(api)
    assert state["offer"]["status"] == "PRESENTED"
    assert state["offer"]["net_offer_cents"] == 21_400_000

    parcel = _withdraw_participation(api, state)

    assert parcel["participation_status"] == "WITHDRAWN"
    assert parcel["acquisition_status"] == "ACQUISITION_CANCELLED"

    offer = validate_success(
        api.get_purchase_offer(
            state["offer"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert offer["status"] == "WITHDRAWN"
    assert offer["net_offer_cents"] == 21_400_000


def test_withdrawal_deobligates_the_exact_share_and_is_not_counted_as_a_holdout(api):
    """The obligation returns to zero while the withdrawn parcel leaves both counts.

    "Link three: each offer arriving at `WITHDRAWN` leaves the obligation
    ledger's offer group, so the project's `federal_obligated_cents` is
    recomputed and falls by exactly the rounded federal share that offer had
    contributed."

    "The denominator is `participating_parcel_count`, the count of parcels of
    this project whose `participation_status` is `NOT_CONTACTED`, `INTERESTED`,
    `VOLUNTARY_CONFIRMED` or `DECLINED` - that is, every parcel except those that
    have withdrawn."

    "`holdout_parcel_count` is separately the count of parcels of this project
    whose `participation_status` is exactly `DECLINED`."

    Design: Difficulty/transitive_cascade/participation_withdrawal_cascades_four_levels_into_federal_deobligation
    """
    state = fixtures.parcel_with_presented_offer(api)
    assert state["project"]["federal_obligated_cents"] == 16_050_000
    assert state["project"]["participating_parcel_count"] == 1

    _withdraw_participation(api, state)

    project = validate_success(
        api.get_mitigation_project(
            state["project"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert project["federal_obligated_cents"] == 0
    assert project["participating_parcel_count"] == 0
    assert project["holdout_parcel_count"] == 0
    assert float(project["neighborhood_viability_ratio"]) == 0
    assert project["viability_status"] == "NONVIABLE"
