"""The plain read and write surface, and the shape every failure comes back in.

The one partial-update endpoint, the one child collection a public reader may
write to, the read-only view of a filing's immutable lines, the envelope sampled
once per status class the program can emit, and one endpoint walked down its whole
rejection ladder with a single defect repaired per call.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as u
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_clock_stamp,
    assert_error_envelope_shape,
    assert_submission_totals,
)
from test_helpers.types import (
    PlantStatus,
    PurchaseType,
    ReportCategory,
    Species,
    SubmissionStatus,
)

PLANT_HISTORY = {
    "2021": 120000,
    "2022": 124000,
    "2023": 126000,
    "2024": 128000,
    "2025": 132000,
}
UNKNOWN_PLANT_ID = NON_EXISTENT_UUID
UNKNOWN_WINDOW_ID = "00000000-0000-0000-0000-0000000000bb"


def test_01_an_amendment_touches_only_what_it_names_and_re_derives_the_flag(api):
    """One pound short of the floor, then exactly on it, then a status change.

    The first amendment carries only the wholesale volume and lifts it onto the
    thousand-ton floor, so the authorization flag is recomputed rather than frozen
    at creation; the second carries only the operating status and leaves that volume
    untouched. Each accepted amendment moves the plant's version by exactly one and
    the owning firm's version not at all.

    PRD §3.1: "A plant's operating status, slaughter history, wholesale volume and
    forward commitment cap may all be amended later by a `ProgramAdmin`, each of
    `status`, `annual_head_history`, `boxed_beef_volume_lbs_prior_year` and
    `forward_commitment_cap_head` being individually optional in the amendment
    payload; any amendment recomputes `wholesale_reporting_required` from the value
    then in force and increments the plant's `version` by 1."

    Design: Corner/endpoints/patch_plant_recomputes_flag_and_bumps_version
    """
    entity = fx.create_entity(api, legal_name="Alpha Packing")
    plant = fx.create_plant(
        api,
        entity["id"],
        plant_code="EST-101",
        annual_head_history=dict(PLANT_HISTORY),
        boxed_beef_volume_lbs_prior_year=k.BOXED_BEEF_WHOLESALE_FLOOR_LBS - 1,
        forward_commitment_cap_head=3000,
    )
    assert plant["wholesale_reporting_required"] is False, plant
    assert plant["version"] == 1, plant
    entity_version = fx.entity_version(api, entity["id"])

    authorized = validate_success(
        api.update_plant(
            plant["id"],
            f.plant_patch_payload(
                boxed_beef_volume_lbs_prior_year=k.BOXED_BEEF_WHOLESALE_FLOOR_LBS
            ),
            u.PROGRAM_ADMIN,
        )
    )
    assert (
        authorized["boxed_beef_volume_lbs_prior_year"]
        == k.BOXED_BEEF_WHOLESALE_FLOOR_LBS
    ), authorized
    assert authorized["wholesale_reporting_required"] is True, authorized
    assert authorized["version"] == 2, authorized

    closed = validate_success(
        api.update_plant(
            plant["id"],
            f.plant_patch_payload(status=PlantStatus.CLOSED.value),
            u.PROGRAM_ADMIN,
        )
    )
    assert closed["status"] == PlantStatus.CLOSED.value, closed
    assert closed["version"] == 3, closed
    assert (
        closed["boxed_beef_volume_lbs_prior_year"]
        == k.BOXED_BEEF_WHOLESALE_FLOOR_LBS
    ), closed

    final = fx.read_plant(api, plant["id"])
    assert final["plant_code"] == "EST-101", final
    assert final["species"] == Species.CATTLE.value, final
    assert final["forward_commitment_cap_head"] == 3000, final
    assert final["annual_head_history"] == PLANT_HISTORY, final
    assert final["reporting_entity_id"] == entity["id"], final
    assert final["version"] == 3, final
    assert final["wholesale_reporting_required"] is True, final

    assert fx.entity_version(api, entity["id"]) == entity_version


def test_02_a_comment_links_to_its_own_docket_and_counts_only_there(api):
    """Two dockets, three comments, two independent counters.

    Comments filed by two different roles land on the same docket and lift its
    counter to two, while a third on the sibling docket lifts only that one. Each
    comment carries the docket it was filed against and its receipt instant, and the
    child listing narrows by stance and pages within one docket without ever
    returning the sibling's row.

    PRD §3.9: "The platform stamps `received_at` from the logical clock and
    increments the docket's `comment_count` by 1."

    Design: Corner/endpoints/public_comment_creation_links_and_counts_on_the_docket
    """
    entity = fx.create_entity(api, legal_name="Alpha Packing")
    first_docket = fx.open_docket(
        api,
        change_code="MC-2026-A",
        affected_category=ReportCategory.LIVE_STEER_HEIFER.value,
    )
    second_docket = fx.open_docket(
        api,
        change_code="MC-2026-B",
        affected_category=ReportCategory.LIVE_COW_BULL.value,
    )

    supporting = get_success_data(
        api.create_public_comment(
            first_docket["id"],
            f.public_comment_payload(
                commenter_reference="state-cattlemen",
                comment_text="weight weighting reflects the carcass trade",
                stance="SUPPORT",
            ),
            u.PUBLIC_USER,
        ),
        expected_status=201,
    )
    assert (
        fx.read_methodology_change(api, first_docket["id"])["comment_count"] == 1
    )

    opposing = get_success_data(
        api.create_public_comment(
            first_docket["id"],
            f.public_comment_payload(
                commenter_reference="alpha-packing-regulatory",
                comment_text="transition cost is material for smaller plants",
                stance="OPPOSE",
            ),
            u.reporter_agent(entity["id"]),
        ),
        expected_status=201,
    )
    assert (
        fx.read_methodology_change(api, first_docket["id"])["comment_count"] == 2
    )

    sibling = get_success_data(
        api.create_public_comment(
            second_docket["id"],
            f.public_comment_payload(
                commenter_reference="independent-economist",
                comment_text="no position",
                stance="NEUTRAL",
            ),
            u.PUBLIC_USER,
        ),
        expected_status=201,
    )
    assert (
        fx.read_methodology_change(api, second_docket["id"])["comment_count"] == 1
    )

    for comment, docket_id in (
        (supporting, first_docket["id"]),
        (opposing, first_docket["id"]),
        (sibling, second_docket["id"]),
    ):
        assert comment["methodology_change_id"] == docket_id, comment
        assert_clock_stamp(comment["received_at"], k.CLOCK_BASE_UTC, "received_at")
        assert "version" not in comment, comment

    opposed_rows, opposed_meta = validate_paginated(
        api.list_public_comments(
            first_docket["id"], u.PROGRAM_ADMIN, params={"stance": "OPPOSE"}
        )
    )
    assert [row["id"] for row in opposed_rows] == [opposing["id"]], opposed_rows
    assert opposed_meta["total_count"] == 1, opposed_meta
    assert opposed_meta["has_more"] is False, opposed_meta

    paged_rows, paged_meta = validate_paginated(
        api.list_public_comments(
            first_docket["id"], u.PUBLIC_USER, params={"limit": 1, "offset": 1}
        )
    )
    assert len(paged_rows) == 1, paged_rows
    assert paged_meta["total_count"] == 2, paged_meta
    assert paged_meta["has_more"] is False, paged_meta

    all_rows, _all_meta = validate_paginated(
        api.list_public_comments(first_docket["id"], u.PUBLIC_USER)
    )
    assert sibling["id"] not in [row["id"] for row in all_rows], all_rows


def test_03_each_listed_line_carries_its_own_value_and_the_totals_are_their_sum(api):
    """Three lines whose booked totals are the per-line figures added up.

    The listing is a read of immutable records: each line reports the value it
    computed for itself, the elements a purchase type does not carry come back null,
    the purchase-type filter separates formula trade from negotiated trade inside one
    filing, and the filing's booked totals are exactly the already-rounded per-line
    figures summed.

    PRD §3.5: "A transaction line's `line_value_dollars` is its `head_count`
    multiplied by its `avg_carcass_weight_cwt` multiplied by its
    `avg_net_price_per_cwt`, that single product rounded half up to 2 decimals at the
    line."

    Design: Corner/endpoints/transaction_listing_is_a_computed_read_of_line_values
    """
    firm = fx.obligated_firm(api, legal_name="Alpha Packing")
    entity_id = firm["entity"]["id"]
    window = fx.create_standard_window(api)
    filing = fx.draft_filing(api, entity_id, firm["plant"]["id"], window["id"])

    first = fx.add_transaction(
        api,
        entity_id,
        filing["id"],
        f.transaction_payload(
            head_count=100, avg_net_price_per_cwt=280.00, avg_carcass_weight_cwt=8.00
        ),
    )
    second = fx.add_transaction(
        api,
        entity_id,
        filing["id"],
        f.transaction_payload(
            head_count=50, avg_net_price_per_cwt=279.50, avg_carcass_weight_cwt=8.10
        ),
    )
    third = fx.add_transaction(
        api,
        entity_id,
        filing["id"],
        f.formula_transaction_payload(
            formula_base_reference="CME_LIVE_CATTLE_INDEX",
            head_count=200,
            avg_net_price_per_cwt=290.00,
            avg_carcass_weight_cwt=9.00,
        ),
    )

    rows, meta = validate_paginated(api.list_transactions(filing["id"], u.MARKET_ANALYST))
    assert [row["id"] for row in rows] == [
        first["id"],
        second["id"],
        third["id"],
    ], rows
    assert meta["total_count"] == 3, meta
    assert meta["has_more"] is False, meta

    by_id = {row["id"]: row for row in rows}
    assert by_id[first["id"]]["line_value_dollars"] == 224000.00, by_id
    assert by_id[second["id"]]["line_value_dollars"] == 113197.50, by_id
    assert by_id[third["id"]]["line_value_dollars"] == 522000.00, by_id

    assert (
        by_id[third["id"]]["formula_base_reference"] == "CME_LIVE_CATTLE_INDEX"
    ), by_id
    for line_id in (first["id"], second["id"]):
        assert by_id[line_id]["formula_base_reference"] is None, by_id
    for row in rows:
        assert row["grid_premium_discount_per_cwt"] is None, row
        assert row["forward_delivery_start"] is None, row
        assert row["forward_delivery_end"] is None, row

    formula_rows, formula_meta = validate_paginated(
        api.list_transactions(
            filing["id"],
            u.MARKET_ANALYST,
            params={"purchase_type": PurchaseType.FORMULA.value},
        )
    )
    assert [row["id"] for row in formula_rows] == [third["id"]], formula_rows
    assert formula_meta["total_count"] == 1, formula_meta

    assert_submission_totals(
        fx.read_submission(api, filing["id"]),
        reported_head=350,
        reported_cwt=3005.00,
        reported_value_dollars=859197.50,
        reported_pounds=0.00,
        reported_load_count=0,
    )


def test_04_every_status_class_comes_back_in_the_same_error_envelope(api):
    """Seven failures across seven status classes, one body shape.

    A malformed page argument, a headerless read, a role the endpoint does not list,
    an unknown identifier, a business-state refusal, a stale version and a missing
    data element are each answered with the same envelope: the error response type,
    a meta block of exactly two keys, and a data object of exactly an error id and a
    human-readable message -- never a partial resource, a field-level error list or a
    status number inside the body.

    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/errors/error_envelope_shape_uniform_across_status_classes
    """
    firm = fx.obligated_firm(api, legal_name="Alpha Packing")
    entity_id = firm["entity"]["id"]
    window = fx.create_standard_window(api)
    filing = fx.draft_filing(api, entity_id, firm["plant"]["id"], window["id"])
    reporter = u.reporter_agent(entity_id)
    stale_version = fx.window_version(api, window["id"]) - 1

    samples = [
        (
            api.list_plants(u.PROGRAM_ADMIN, params={"limit": 0}),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        ),
        (
            api.get_plant(firm["plant"]["id"], u.HEADERS_WITHOUT_ROLE),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            401,
        ),
        (
            api.get_reporting_entity(entity_id, u.PUBLIC_USER),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        ),
        (
            api.get_submission(NON_EXISTENT_UUID, u.PROGRAM_ADMIN),
            ApiErrorId.ERR_SUBMISSION_NOT_FOUND.value,
            404,
        ),
        (
            api.submit_submission(filing["id"], reporter),
            ApiErrorId.ERR_EMPTY_SUBMISSION.value,
            409,
        ),
        (
            api.create_submission(
                f.submission_payload(
                    firm["plant"]["id"], window["id"], stale_version
                ),
                reporter,
            ),
            ApiErrorId.ERR_STALE_WINDOW_VERSION.value,
            412,
        ),
        (
            api.add_transaction(
                filing["id"],
                f.transaction_payload(
                    purchase_type=PurchaseType.FORMULA.value,
                    head_count=100,
                    avg_net_price_per_cwt=290.00,
                    avg_carcass_weight_cwt=9.00,
                ),
                reporter,
            ),
            ApiErrorId.ERR_MISSING_PURCHASE_TYPE_ELEMENT.value,
            422,
        ),
    ]

    for response, error_id, status in samples:
        validate_error(response, error_id, status)
        assert_error_envelope_shape(response)


def test_05_the_filing_creation_ladder_is_climbed_one_repaired_defect_at_a_time(api):
    """Eight calls to one endpoint, each repairing exactly the last complaint.

    Identity comes first, then the role list, then the shape of the body, then the
    two body foreign keys in their declared order, then ownership of the named plant,
    then the window's version -- and only the call with nothing left wrong writes.
    Every call before the last would have failed further down the ladder as well, so
    the sequence pins the order and not merely the existence of the rungs.

    PRD §2.8: "Foreign keys carried in a request body are resolved after every path
    segment, in declaration order: `reporting_entity_id` yields
    `ERR_REPORTING_ENTITY_NOT_FOUND`, `plant_id` yields `ERR_PLANT_NOT_FOUND`,
    `reporting_window_id` yields `ERR_REPORTING_WINDOW_NOT_FOUND`,
    `supersedes_submission_id` and `submission_id` both yield
    `ERR_SUBMISSION_NOT_FOUND`, and `audit_case_id` yields
    `ERR_AUDIT_CASE_NOT_FOUND`."

    Design: Corner/errors/submission_create_error_ladder_peels_off_one_rung_at_a_time
    """
    alpha = fx.obligated_firm(api, legal_name="Alpha Packing")
    bravo = fx.create_entity(api, legal_name="Bravo Beef")
    plant_id = alpha["plant"]["id"]
    window = fx.create_standard_window(api)
    window_version = fx.window_version(api, window["id"])
    owner = u.reporter_agent(alpha["entity"]["id"])
    intruder = u.reporter_agent(bravo["id"])
    well_formed = f.submission_payload(plant_id, window["id"], window_version)

    ladder = [
        (
            api.create_submission(dict(well_formed), u.HEADERS_WITHOUT_ROLE),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            401,
        ),
        (
            api.create_submission(dict(well_formed), u.PUBLIC_USER),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        ),
        (
            api.create_submission(
                {
                    "plant_id": plant_id,
                    "expected_window_version": window_version,
                },
                owner,
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        ),
        (
            api.create_submission(
                f.submission_payload(
                    UNKNOWN_PLANT_ID, UNKNOWN_WINDOW_ID, window_version
                ),
                owner,
            ),
            ApiErrorId.ERR_PLANT_NOT_FOUND.value,
            404,
        ),
        (
            api.create_submission(
                f.submission_payload(plant_id, UNKNOWN_WINDOW_ID, window_version),
                owner,
            ),
            ApiErrorId.ERR_REPORTING_WINDOW_NOT_FOUND.value,
            404,
        ),
        (
            api.create_submission(dict(well_formed), intruder),
            ApiErrorId.ERR_FOREIGN_REPORTING_ENTITY.value,
            403,
        ),
        (
            api.create_submission(
                f.submission_payload(plant_id, window["id"], window_version - 1),
                owner,
            ),
            ApiErrorId.ERR_STALE_WINDOW_VERSION.value,
            412,
        ),
    ]
    for response, error_id, status in ladder:
        validate_error(response, error_id, status)

    created = get_success_data(
        api.create_submission(dict(well_formed), owner), expected_status=201
    )
    assert created["status"] == SubmissionStatus.DRAFT.value, created
    assert created["is_late"] is False, created
    assert created["resubmission_count"] == 0, created
    assert fx.window_version(api, window["id"]) == window_version + 1
