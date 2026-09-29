"""The two interval geometries of the system, exercised at their exact boundaries.

Licence terms are half-open, so adjacency is legal and a single day of intersection
is not; depiction windows are closed and widened by a quiet buffer before they are
compared, and only live releases are compared at all.
"""
from test_helpers import (
    CLEARANCE_SUPERVISOR,
    PRODUCTION_ADMIN,
    assert_posture,
    create_archive_with_rate_card,
    create_asset_with_selected_source,
    create_and_execute_license,
    create_license_payload,
    create_live_subject_release,
    create_production_in_clearance,
    create_subject_release_payload,
    get_production,
    validate_error,
    validate_paginated,
    validate_success,
)

# A 45-second BROADCAST / WORLD / 12-month all-media licence on the standard card:
# 60000 * 2 units * 1.25 * 1.15 * 1.50 * 1.00 (term factor 1) = 258750 cents.
TWELVE_MONTH_FEE_CENTS = 258750

INCUMBENT_TERM_START = "2026-08-15"
INCUMBENT_TERM_END = "2027-08-15"


def _setup_executed_twelve_month_footage_license(api):
    """One footage asset holding an EXECUTED licence over [2026-08-15, 2027-08-15)."""
    production = create_production_in_clearance(api, title="Back To Back Terms",
                                                delivery_deadline_date="2027-12-31")
    archive, card = create_archive_with_rate_card(api)
    asset, candidate = create_asset_with_selected_source(
        api, production["id"], archive["id"], title="Market street")
    license_row = create_and_execute_license(
        api, production["id"], asset["id"], archive["id"], TWELVE_MONTH_FEE_CENTS,
        term_months=12, term_start_date=INCUMBENT_TERM_START,
        term_end_date=INCUMBENT_TERM_END)
    return {
        "production": production,
        "archive": archive,
        "rate_card": card,
        "asset": asset,
        "source_candidate": candidate,
        "license": license_row,
    }


def _second_term_payload(scenario, term_start_date, term_end_date, territory="WORLD"):
    return create_license_payload(
        scenario["production"]["id"], scenario["asset"]["id"], scenario["archive"]["id"],
        rights_leg="FOOTAGE", media="BROADCAST", territory=territory,
        window_class="ALL_MEDIA_WINDOW", term_months=12,
        term_start_date=term_start_date, term_end_date=term_end_date)


def _count_licenses_of_asset(api, asset_id):
    _rows, meta = validate_paginated(
        api.list_licenses(CLEARANCE_SUPERVISOR,
                          params={"asset_id": asset_id, "limit": 100}))
    return meta["total_count"]


def _setup_live_and_refused_releases(api):
    """A SENT release for one subject and a REFUSED release for another."""
    production = create_production_in_clearance(api, title="Quiet Buffer",
                                                delivery_deadline_date="2027-03-31")
    walsh = create_live_subject_release(
        api, production["id"], "walsh-eileen", release_type="SUBJECT_RELEASE",
        depiction_from_date="2026-03-01", depiction_to_date="2026-03-31")
    dunne = create_live_subject_release(
        api, production["id"], "dunne-martin", to_status="REFUSED",
        release_type="LIFE_RIGHTS",
        depiction_from_date="2026-06-01", depiction_to_date="2026-06-30")
    return {"production": production, "walsh_release": walsh, "dunne_release": dunne}


def test_one_day_intersection_on_the_same_tuple_is_refused(api):
    """PRD §3.3: "A new licence is refused with `ERR_LICENSE_TERM_OVERLAP` when there
    already exists a licence on the same `asset_id`, with the same `rights_leg`, whose
    `status` is one of `DRAFT`, `QUOTED`, `COUNTERED`, `EXECUTED`, `ACTIVE` or `EXPIRING`,
    whose media overlaps the requested media, whose territory overlaps the requested
    territory, and whose half-open term interval intersects the requested one."

    Design: Difficulty/resource_temporal_overlap/license_term_adjacency_allowed_but_one_day_intersection_refused
    """
    scenario = _setup_executed_twelve_month_footage_license(api)

    response = api.create_license(
        _second_term_payload(scenario, "2027-08-14", "2028-08-14"), CLEARANCE_SUPERVISOR)
    validate_error(response, "ERR_LICENSE_TERM_OVERLAP")

    assert _count_licenses_of_asset(api, scenario["asset"]["id"]) == 1
    production = get_production(api, scenario["production"]["id"])
    assert production["committed_fee_cents"] == TWELVE_MONTH_FEE_CENTS


def test_domestic_request_still_overlaps_the_incumbent_world_term(api):
    """PRD §3.3: "Territory overlap means the two `territory` values are identical, or
    either side is `WORLD`."

    Design: Difficulty/resource_temporal_overlap/license_term_adjacency_allowed_but_one_day_intersection_refused
    """
    scenario = _setup_executed_twelve_month_footage_license(api)

    response = api.create_license(
        _second_term_payload(scenario, "2027-08-14", "2028-08-14", territory="DOMESTIC"),
        CLEARANCE_SUPERVISOR)
    validate_error(response, "ERR_LICENSE_TERM_OVERLAP")

    assert _count_licenses_of_asset(api, scenario["asset"]["id"]) == 1


def test_term_starting_on_the_incumbents_end_date_is_adjacent_and_accepted(api):
    """PRD §3.3: "Term intersection is evaluated on the half-open convention of §2.11, so
    adjacency is permitted: a term starting exactly on an existing term's `term_end_date`
    does not overlap that term, and both licences may stand."

    Design: Difficulty/resource_temporal_overlap/license_term_adjacency_allowed_but_one_day_intersection_refused
    """
    scenario = _setup_executed_twelve_month_footage_license(api)

    validate_error(
        api.create_license(_second_term_payload(scenario, "2027-08-14", "2028-08-14"),
                           CLEARANCE_SUPERVISOR),
        "ERR_LICENSE_TERM_OVERLAP")

    adjacent = validate_success(
        api.create_license(_second_term_payload(scenario, INCUMBENT_TERM_END, "2028-08-15"),
                           CLEARANCE_SUPERVISOR), 201)
    assert adjacent["status"] == "DRAFT"
    assert adjacent["rate_card_fee_cents"] == TWELVE_MONTH_FEE_CENTS
    assert adjacent["term_start_date"] == INCUMBENT_TERM_END
    assert adjacent["executed_fee_cents"] is None

    assert _count_licenses_of_asset(api, scenario["asset"]["id"]) == 2
    production = get_production(api, scenario["production"]["id"])
    assert production["committed_fee_cents"] == TWELVE_MONTH_FEE_CENTS


def test_widened_window_touching_the_incumbents_closing_day_is_refused(api):
    """PRD §3.6: "Before a release is created, the requested window is widened by a quiet
    buffer of 30 days on each side — its from-date pushed 30 days earlier and its to-date
    pushed 30 days later — and the widened window is tested for intersection against the
    closed depiction window of every existing release on the same production carrying the
    same `subject_person_key` whose `status` is `SENT`, `REVISION_REQUESTED`, `SIGNED` or
    `APPROVAL_GRANTED`. Any intersection is refused with `ERR_DEPICTION_WINDOW_CONFLICT`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/depiction_window_thirty_day_quiet_buffer_and_status_filtered_blockers
    """
    scenario = _setup_live_and_refused_releases(api)

    response = api.create_subject_release(
        scenario["production"]["id"],
        create_subject_release_payload("walsh-eileen", release_type="DEPICTION_AGREEMENT",
                                       depiction_from_date="2026-04-30",
                                       depiction_to_date="2026-05-31"),
        PRODUCTION_ADMIN)
    validate_error(response, "ERR_DEPICTION_WINDOW_CONFLICT")

    _rows, meta = validate_paginated(
        api.list_subject_releases(PRODUCTION_ADMIN,
                                  params={"production_id": scenario["production"]["id"],
                                          "limit": 100}))
    assert meta["total_count"] == 2


def test_one_day_later_the_widened_window_clears_the_incumbent(api):
    """PRD §3.6: "Before a release is created, the requested window is widened by a quiet
    buffer of 30 days on each side — its from-date pushed 30 days earlier and its to-date
    pushed 30 days later — and the widened window is tested for intersection against the
    closed depiction window of every existing release on the same production carrying the
    same `subject_person_key` whose `status` is `SENT`, `REVISION_REQUESTED`, `SIGNED` or
    `APPROVAL_GRANTED`."

    Design: Difficulty/resource_temporal_overlap/depiction_window_thirty_day_quiet_buffer_and_status_filtered_blockers
    """
    scenario = _setup_live_and_refused_releases(api)

    created = validate_success(
        api.create_subject_release(
            scenario["production"]["id"],
            create_subject_release_payload("walsh-eileen",
                                           release_type="DEPICTION_AGREEMENT",
                                           depiction_from_date="2026-05-01",
                                           depiction_to_date="2026-05-31"),
            PRODUCTION_ADMIN), 201)
    assert created["status"] == "DRAFT"
    assert created["subject_person_key"] == "walsh-eileen"
    assert created["depiction_from_date"] == "2026-05-01"
    assert created["revision_round_count"] == 0

    reread = validate_success(api.get_subject_release(created["id"], PRODUCTION_ADMIN))
    assert reread["status"] == "DRAFT"
    assert reread["cut_reference"] is None


def test_refused_release_never_blocks_an_identical_depiction_window(api):
    """PRD §3.6: "Releases in `DRAFT`, `REFUSED` or `APPROVAL_WITHHELD` are not live and
    never block a new paper." PRD §2.8 rule 1: "If the production has no assets at all,
    posture is `OPEN`."

    Design: Difficulty/resource_temporal_overlap/depiction_window_thirty_day_quiet_buffer_and_status_filtered_blockers
    """
    scenario = _setup_live_and_refused_releases(api)
    refused = scenario["dunne_release"]
    assert refused["status"] == "REFUSED"

    duplicate = validate_success(
        api.create_subject_release(
            scenario["production"]["id"],
            create_subject_release_payload("dunne-martin", release_type="LIFE_RIGHTS",
                                           depiction_from_date=refused["depiction_from_date"],
                                           depiction_to_date=refused["depiction_to_date"]),
            PRODUCTION_ADMIN), 201)
    assert duplicate["status"] == "DRAFT"
    assert duplicate["depiction_from_date"] == refused["depiction_from_date"]
    assert duplicate["depiction_to_date"] == refused["depiction_to_date"]

    second_walsh = validate_success(
        api.create_subject_release(
            scenario["production"]["id"],
            create_subject_release_payload("walsh-eileen",
                                           release_type="DEPICTION_AGREEMENT",
                                           depiction_from_date="2026-05-01",
                                           depiction_to_date="2026-05-31"),
            PRODUCTION_ADMIN), 201)
    assert second_walsh["status"] == "DRAFT"

    _rows, meta = validate_paginated(
        api.list_subject_releases(PRODUCTION_ADMIN,
                                  params={"production_id": scenario["production"]["id"],
                                          "limit": 100}))
    assert meta["total_count"] == 4

    production = get_production(api, scenario["production"]["id"])
    assert production["asset_count"] == 0
    assert_posture(production, "OPEN")
