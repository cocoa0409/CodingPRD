"""
The shape of the wire-form API's answers: the envelope, the paged and filtered
listings, the computed reads and the one action endpoint that owns the clock.

Nothing here is about a business rule for its own sake. These tests pin what a
caller sees at the edge: that a success and a failure on the same program read
carry the same `meta` block, that a listing echoes the page it actually served
and counts the rows the filter matched before that page was cut, that the
amortization read answers both recovery policies for a hypothetical lot without
posting either of them, that advancing the logical shop clock moves no row, and
that a shipment stamps the clock the plant is running on rather than the host's
wall time. Where a listing exists as the reverse leg of a foreign key — tooling
under its design, inspection records under their run — the filter is exercised
against a sibling row that must stay out of the answer.
"""

from datetime import datetime

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ERR_INVALID_REQUEST, ERR_PROGRAM_NOT_FOUND
from test_helpers.test_users import (
    DESIGN_ENGINEER_HEADERS,
    ENGINEERING_MANAGER_HEADERS,
    PLANT_ADMIN_HEADERS,
    PROGRAM_MANAGER_HEADERS,
    QUALITY_INSPECTOR_HEADERS,
    QUALITY_INSPECTOR_PRIMARY,
)

# The morning after the canonical setup day: an instant the shop clock has to be
# driven to explicitly, so a wall-clock stamp could never coincide with it.
_SHIPPING_MORNING = "2026-08-06T09:00:00Z"

# The hypothetical lot the amortization read is asked about.
_HYPOTHETICAL_PIECES = 1_000


def _instant(value: str) -> datetime:
    """The instant an ISO 8601 UTC timestamp names, whatever its fraction shows."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_amortization_read_answers_both_bases_and_leaves_the_ledger_untouched(
    api: ApiClient,
) -> None:
    """Both recovery policies for one hypothetical lot, with nothing posted behind them.

    The customer's full approval armed TL-1 over the program's 500 000 committed
    pieces, so the frozen per-piece figure is 4 800 000 divided by 500 000 rounded
    up: 10 cents. A hypothetical 1 000-piece lot therefore recovers 10 000 cents on
    the forecast basis and 4 800 000 x 1.5 x 1 000 / 500 000 = 14 400 cents on the
    accelerated basis, while the tool itself has shipped nothing and still carries
    the whole 4 800 000 as unamortized.

    PRD §3.4: "A computed read on the program exposes them side by side for a hypothetical lot of a stated `piece_count`, returning the program's own `amortization_method`, the `tooling_asset_id` of the newest tooling asset by `created_at` for the program's most recently quoted design, that tool's `original_cost_cents`, `recovered_cents` and `unamortized_cents`, the program's live `open_commitment_pieces`, and then both hypothetical figures: `forecast_basis_recovery_cents` and `actual_basis_recovery_cents`."
    PRD §3.4: "The `PENDING → AMORTIZING` promotion fires as a system event when the tool's design reaches `PRODUCTION_RELEASED`, and it is the moment the amortization basis is frozen: `amortization_basis_pieces` takes the owning program's `committed_pieces`, and `amort_per_piece_cents` becomes `original_cost_cents` divided by that basis, rounded **up** to the next whole cent."
    PRD §3.4: "Under `FORECAST_BASIS` — a straight-line forecast recovery — the amount is the lot's `piece_count` multiplied by the tool's frozen `amort_per_piece_cents`, capped at the tool's live `unamortized_cents`; whichever of the two is smaller is posted."
    PRD §3.4: "Under `ACTUAL_BASIS` — an accelerated declining recovery — the amount starts from the tool's live `unamortized_cents` multiplied by an acceleration factor of 1.5, multiplied by the lot's `piece_count`, divided by the program's `open_commitment_pieces` (or by 1 if that figure is zero or lower, so the division is always defined), rounded **up** toward positive infinity to a whole cent, and then capped at the tool's live `unamortized_cents`; again the smaller of the two is posted."
    PRD §3.4: "Once armed, each shipment posts a recovery into `recovered_cents` and out of `unamortized_cents`; when a posting drives `unamortized_cents` to exactly 0, the tool transitions `AMORTIZING → FULLY_AMORTIZED`."
    Design: Corner/endpoints/tooling_amortization_read_returns_both_bases_without_mutating_the_ledger
    """
    world = X.approved_world(api)

    response = api.get_tooling_amortization(
        world.program_id,
        PROGRAM_MANAGER_HEADERS,
        params={"piece_count": _HYPOTHETICAL_PIECES},
    )
    data = validate_success(response)

    assert response.json()["response_type"] == "object", (
        "the computed read answers for one program, so it is a single resource"
    )
    assert data["amortization_method"] == C.FORECAST_BASIS, (
        "the read echoes the program's own amortization method"
    )
    assert data["tooling_asset_id"] == world.tooling_id, (
        "the tool consulted is the newest asset of the most recently quoted design"
    )
    assert data["original_cost_cents"] == 4_800_000, (
        "original_cost_cents is fixed at capitalisation"
    )
    assert data["recovered_cents"] == 0, (
        "nothing has shipped, so no recovery has been posted"
    )
    assert data["unamortized_cents"] == 4_800_000, (
        "recovered_cents and unamortized_cents always sum to original_cost_cents"
    )
    assert data["open_commitment_pieces"] == 500_000, (
        "the live commitment is untouched while no lot has been allocated"
    )
    assert data["forecast_basis_recovery_cents"] == 10_000, (
        "the forecast basis is piece_count x amort_per_piece_cents = 1000 x 10"
    )
    assert data["actual_basis_recovery_cents"] == 14_400, (
        "the actual basis is ceil(4800000 x 1.5 x 1000 / 500000) = 14400"
    )

    tool = X.refresh_tooling(api, world.tooling_id)
    assert tool["recovered_cents"] == 0, (
        "a hypothetical figure is not a posting: recovery moves only on a shipment"
    )
    assert tool["unamortized_cents"] == 4_800_000, (
        "the read leaves the unamortized balance exactly where it stood"
    )
    assert tool["amortization_status"] == C.AMORT_AMORTIZING, (
        "the tool reaches FULLY_AMORTIZED only when a posting zeroes its balance"
    )


def test_design_listing_filters_on_release_status_under_a_page_limit(
    api: ApiClient,
) -> None:
    """One DRAFT sibling behind a released prototype, fetched by status on a page of one.

    D1 has been carried to `PROTOTYPE_RELEASED`; D2 is a fresh draft on the same
    program and grade. Filtering on `DRAFT` matches D2 alone, so a page limited to
    one row is the whole answer: `total_count` is 1 and `has_more` is false, and
    the echoed page is the one that was asked for.

    PRD §3.2: "Designs may be listed filtered by `program_id`, `material_spec_id` and `release_status`."
    PRD §3.2: "On acceptance the server stamps `created_by_user_id` with the incoming `X-User-ID`, leaves `reviewed_by_user_id` null, sets `current_revision_no` to 1 with `superseded_revision_no` null, sets `release_status` to `DRAFT`, and then runs the complete engineering stack."
    PRD §2.3: "`limit` controls page size; it defaults to 10 when omitted, has a minimum of 1 and a maximum of 100."
    PRD §2.3: "`offset` controls how many rows are skipped before the page begins; it defaults to 0 and has a minimum of 0 with no upper bound."
    PRD §2.3: "The `meta` object of every list response carries `limit` and `offset` echoing the effective values in force, `total_count` giving the number of rows matching the filters before pagination is applied, and `has_more` set true exactly when rows remain beyond the current page."
    Design: Corner/endpoints/design_listing_filters_on_release_status_and_honours_the_page_limit
    """
    world = X.build_world(api, "prototype")
    draft = X.draft_design(
        api,
        world.program_id,
        world.material_id,
        DESIGN_ENGINEER_HEADERS,
        part_number="D2",
    )

    assert world.design["release_status"] == C.RELEASE_PROTOTYPE, (
        "the first design was carried through the engineering verdict"
    )
    assert draft["release_status"] == C.RELEASE_DRAFT, (
        "a newly created design opens in DRAFT"
    )

    response = api.list_designs(
        DESIGN_ENGINEER_HEADERS,
        params={"release_status": C.RELEASE_DRAFT, "limit": 1},
    )
    rows, meta = validate_paginated(response)

    assert len(rows) == 1, "the DRAFT filter matches the sibling design alone"
    assert rows[0]["id"] == draft["id"], (
        "the released prototype is excluded by the release_status filter"
    )
    assert rows[0]["part_number"] == "D2", "the row returned is the draft sibling"
    assert meta["total_count"] == 1, (
        "total_count counts the rows matching the filter before the page is cut"
    )
    assert meta["has_more"] is False, (
        "has_more is true exactly when rows remain beyond this page, and none do"
    )
    assert meta["limit"] == 1, "meta echoes the limit in force"
    assert meta["offset"] == 0, "offset defaults to 0 when omitted"


def test_program_read_and_unknown_program_share_the_meta_envelope(
    api: ApiClient,
) -> None:
    """The same two meta fields on the 200 and on the 404 of one program read.

    A freshly opened program reads back as a single resource with no granted
    approval on file, so its posture is `BLOCKED`. The very next read, aimed at an
    identifier no program owns, cannot resolve its leftmost path segment and comes
    back as an error — and that error still carries the request identifier and the
    request timestamp, and nothing else in `meta`.

    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
    PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits."
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
    PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."
    PRD §3.1: "`delivery_posture` starts at `BLOCKED`, which is simply what the posture rule below returns for a program with no granted approval on file."
    PRD §2.8: "Path parameters are resolved strictly left to right, and the leftmost unresolvable segment decides the answer."
    PRD §2.8: "6. `ERR_PROGRAM_NOT_FOUND` — on `GET`/`POST /customer-programs/{id}/*`, `POST /spring-designs`, `POST /qualification-submissions`, `POST /shipment-lots`."
    Design: Corner/endpoints/success_and_error_responses_share_the_meta_envelope
    """
    program = X.open_program(api)

    found = api.get_program(program["id"], PLANT_ADMIN_HEADERS)
    data = validate_success(found)
    body = found.json()
    meta = body["meta"]

    assert body["response_type"] == "object", (
        "one program is a single resource, so response_type is 'object'"
    )
    assert meta["api_request_id"].startswith("req_"), (
        "the server-generated request identifier starts with req_"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), (
        "the request timestamp is an ISO 8601 UTC timestamp"
    )
    assert data["id"] == program["id"], "the read answers the program that was asked for"
    assert data["program_code"] == C.CANONICAL_PROGRAM_CODE, (
        "program_code is the customer-facing identifier declared at opening"
    )
    assert data["delivery_posture"] == C.POSTURE_BLOCKED, (
        "a program with no granted approval on file is BLOCKED"
    )

    missing = api.get_program(NON_EXISTENT_UUID, PLANT_ADMIN_HEADERS)
    error = validate_error(missing, ERR_PROGRAM_NOT_FOUND, 404)
    error_body = missing.json()
    error_meta = error_body["meta"]

    assert error_body["response_type"] == "error", (
        "an error answer declares response_type 'error'"
    )
    assert error["message"].strip(), (
        "the error carries a human-readable explanation of what went wrong"
    )
    assert error_meta["api_request_id"].startswith("req_"), (
        "the error envelope carries the same request identifier as a success"
    )
    assert is_iso8601_timestamp(error_meta["api_request_timestamp"]), (
        "the error envelope carries the same request timestamp as a success"
    )
    assert set(error_meta) == {"api_request_id", "api_request_timestamp"}, (
        "the meta of an error response contains only those two fields"
    )


def test_clock_advance_answers_the_success_envelope_and_mutates_no_entity(
    api: ApiClient,
) -> None:
    """The plant admin drives the shop clock forward and no row moves with it.

    The clock is the only state this endpoint touches. A program read before and
    after the advance is identical field for field — same counters, same posture,
    same revision counter and same `updated_at` — because the advance is not a
    mutation of any entity, and the answer still arrives inside the standard
    envelope.

    PRD §2.5: "A `PlantAdmin` advances it by supplying a `to_iso8601` instant to the clock-setting endpoint; the clock is monotonic, so a requested instant earlier than the current reading is rejected with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422) and the clock is left untouched."
    PRD §2.5: "Advancing the clock mutates no entity."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
    PRD §4: "Creation endpoints return HTTP 201 with the new resource; reads, lists and state-changing operations on an existing resource return HTTP 200 with the affected resource."
    Design: Corner/endpoints/clock_advance_is_an_action_endpoint_that_returns_no_body_data
    """
    program = X.open_program(api)
    before = X.refresh_program(api, program["id"])

    response = api.set_clock(
        F.clock_payload(C.CLOCK_SETUP_DAY_START), PLANT_ADMIN_HEADERS
    )
    validate_success(response)
    meta = response.json()["meta"]

    assert meta["api_request_id"].startswith("req_"), (
        "the clock setter answers inside the standard envelope like every endpoint"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), (
        "the envelope's own timestamp is an ISO 8601 UTC timestamp"
    )

    after = X.refresh_program(api, program["id"])
    assert after == before, (
        "advancing the clock mutates no entity, so the program row is unchanged"
    )


def test_ship_stamps_shipped_at_from_the_logical_clock(api: ApiClient) -> None:
    """A lot packed on the fifth ships on the sixth, because the shop clock says so.

    The clock is driven to 09:00 on 2026-08-06 before the lot is presented, an
    instant no wall clock could be sitting on, and that is the instant `shipped_at`
    records. The same request posts the forecast-basis recovery for 1 000 pieces at
    10 cents a piece: 10 000 cents onto the tool's recovered balance and out of its
    unamortized balance, leaving 4 790 000, and moves the program's 1 000 pieces
    from allocated to shipped.

    PRD §2.5: "Time in this system is a logical value the server holds, never the host's wall clock."
    PRD §2.5: "Every temporal gate in the specification reads this clock and nothing else: whether a setup window lies in the past, whether a setup may be activated now, whether an oven batch may be charged, and what instant is stamped into `decided_at` on a qualification verdict and `shipped_at` on a shipment."
    PRD §3.11: "The lot becomes `SHIPPED` with `shipped_at` stamped from the logical clock, and `delivery_posture` is re-derived."
    PRD §3.11: "Success records the method and moves the lot `ALLOCATED → PACKED`."
    PRD §3.11: "Shipping then posts the tooling recovery computed under the program's `amortization_method` as described in section 3.4, writes it to the lot's `tooling_recovery_cents`, adds it to the tool's `recovered_cents` and subtracts it from `unamortized_cents`, and takes the tool `AMORTIZING → FULLY_AMORTIZED` if that leaves `unamortized_cents` at zero."
    PRD §3.11: "On the program, `allocated_pieces` decreases by `piece_count` and `shipped_pieces` increases by it — `open_commitment_pieces` is untouched, because the commitment was consumed at allocation."
    PRD §3.4: "Under `FORECAST_BASIS` — a straight-line forecast recovery — the amount is the lot's `piece_count` multiplied by the tool's frozen `amort_per_piece_cents`, capped at the tool's live `unamortized_cents`; whichever of the two is smaller is posted."
    Design: Corner/endpoints/ship_stamps_shipped_at_from_the_logical_clock_not_from_wall_time
    """
    world = X.packed_world(api)
    X.pin_clock(api, _SHIPPING_MORNING)

    lot = validate_success(api.ship_lot(world.lot_id, PROGRAM_MANAGER_HEADERS))

    assert lot["lot_status"] == C.LOT_SHIPPED, "a shipped lot leaves PACKED for SHIPPED"
    assert is_iso8601_timestamp(lot["shipped_at"]), (
        "shipped_at is an ISO 8601 UTC timestamp"
    )
    assert _instant(lot["shipped_at"]) == _instant(_SHIPPING_MORNING), (
        "shipped_at is stamped from the logical clock, not from the host's wall clock"
    )
    assert lot["packaging_method"] == C.PACK_TANGLE_FREE_TRAY, (
        "shipping does not disturb the packaging method recorded at packing"
    )
    assert lot["piece_count"] == _HYPOTHETICAL_PIECES, (
        "the lot carries the 1 000 pieces it was allocated"
    )
    assert lot["tooling_recovery_cents"] == 10_000, (
        "the forecast basis posts piece_count x amort_per_piece_cents = 1000 x 10"
    )

    tool = X.refresh_tooling(api, world.tooling_id)
    assert tool["recovered_cents"] == 10_000, (
        "the recovery is added to the tool's recovered_cents"
    )
    assert tool["unamortized_cents"] == 4_790_000, (
        "the same recovery is subtracted from the tool's unamortized_cents"
    )

    program = X.refresh_program(api, world.program_id)
    assert program["shipped_pieces"] == _HYPOTHETICAL_PIECES, (
        "shipped_pieces increases by the lot's piece_count"
    )
    assert program["allocated_pieces"] == 0, (
        "allocated_pieces decreases by the same piece_count"
    )


def test_tooling_listing_filters_on_the_owning_design(api: ApiClient) -> None:
    """Two designs, one tool each: the design filter is the reverse leg of the key.

    TL-1 was capitalised against the released D1 and TL-2 against a draft sibling
    D2. Filtering the tooling listing on D1 answers TL-1 alone, still opened at
    `PENDING` with its whole cost outstanding because no customer approval has
    armed it yet.

    PRD §3.4: "Coiling tools are capitalised by an `EngineeringManager` against a design, through a payload naming the `design_id`, a tool-room `tool_code` that must be unique across all tooling, and `original_cost_cents`, the capitalised cost in cents, which must be greater than zero and which is the conserved quantity of the amortization ledger."
    PRD §3.4: "A newly capitalised tool opens in `amortization_status` `PENDING` with `recovered_cents` at 0 and `unamortized_cents` equal to `original_cost_cents`."
    PRD §3.4: "Tooling assets may also be listed filtered by `design_id` and `amortization_status`."
    PRD §2.3: "The `meta` object of every list response carries `limit` and `offset` echoing the effective values in force, `total_count` giving the number of rows matching the filters before pagination is applied, and `has_more` set true exactly when rows remain beyond the current page."
    Design: Corner/endpoints/tooling_listing_is_reachable_from_the_owning_design
    """
    world = X.build_world(api, "tooling")
    sibling = X.draft_design(
        api,
        world.program_id,
        world.material_id,
        DESIGN_ENGINEER_HEADERS,
        part_number="D2",
    )
    sibling_tool = X.capitalise_tooling(
        api, sibling["id"], ENGINEERING_MANAGER_HEADERS, tool_code="TL-2"
    )

    response = api.list_tooling_assets(
        ENGINEERING_MANAGER_HEADERS, params={"design_id": world.design_id}
    )
    rows, meta = validate_paginated(response)

    assert len(rows) == 1, "only the tool whose design_id is D1 matches the filter"
    assert meta["total_count"] == 1, (
        "total_count counts the rows matching the design filter"
    )
    assert rows[0]["id"] == world.tooling_id, "the row returned is TL-1"
    assert rows[0]["id"] != sibling_tool["id"], (
        "the sibling design's tool is excluded by the design_id filter"
    )
    assert rows[0]["tool_code"] == C.CANONICAL_TOOL_CODE, (
        "the tool-room code identifies the tool capitalised against D1"
    )
    assert rows[0]["design_id"] == world.design_id, (
        "the filter matches on the tool's own design_id"
    )
    assert rows[0]["amortization_status"] == C.AMORT_PENDING, (
        "a newly capitalised tool opens at PENDING"
    )
    assert rows[0]["recovered_cents"] == 0, "nothing has been recovered on it"
    assert rows[0]["unamortized_cents"] == 4_800_000, (
        "unamortized_cents opens equal to original_cost_cents"
    )


def test_interim_approval_records_the_cap_and_promotes_nothing(api: ApiClient) -> None:
    """The capped conditional release moves the posture and nothing else.

    The customer grants an interim verdict for 5 000 pieces. The submission records
    the cap, the program's posture leaves `BLOCKED` for `ON_TRACK` because a granted
    verdict is now on file and no lot is quarantined and no run is held — but the
    design is still only a released prototype and its tool is still `PENDING` with
    no basis frozen, and the commercial terms are still open.

    PRD §3.10: "`INTERIM_APPROVE` is a capped, conditional release for a customer who wants first pieces before the full package is signed off."
    PRD §3.10: "It requires an `interim_piece_cap` in the body that is present and greater than zero; a missing or non-positive cap is a malformed request and answers `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.10: "The submission moves to `INTERIM_APPROVED` with the cap recorded, and `delivery_posture` is re-derived — an interim verdict counts as an approval for posture purposes, so a blocked program becomes `ON_TRACK` or `AT_RISK`."
    PRD §3.10: "What it deliberately does **not** do is promote anything: the design stays `PROTOTYPE_RELEASED` and every tooling asset stays `PENDING`, because only a full `APPROVE` arms amortization."
    PRD §3.10: "Hop four sets the program's `quote_frozen` to true — the commercial terms are now contractual and no further quote may be run — and re-derives `delivery_posture`, which reaches `ON_TRACK` on a program with no quarantined lots and no held run."
    PRD §3.4: "Both `amortization_basis_pieces` and `amort_per_piece_cents` stay null: until the customer has granted full approval, nobody knows over how many pieces the tool will be recovered."
    PRD §3.1: "`quote_frozen` starts false and every quoted figure — `quoted_qty`, `quoted_pre_discount_subtotal_cents`, `quoted_volume_discount_pct`, `quoted_tooling_amort_per_piece_cents`, `quoted_unit_price_cents` and `quoted_total_cents` — starts null."
    PRD §3.1: "Otherwise, if `quarantined_lot_count` is at least 1 **or** such a held run exists, the posture is `AT_RISK`."
    PRD §3.1: "Otherwise the posture is `ON_TRACK`."
    Design: Corner/endpoints/interim_approval_requires_the_piece_cap_that_a_plain_approval_must_omit
    """
    world = X.submitted_world(api)

    submission = validate_success(
        api.review_submission(
            world.submission_id,
            {"decision": C.DECISION_INTERIM_APPROVE, "interim_piece_cap": 5_000},
            world.customer,
        )
    )

    assert submission["submission_status"] == C.SUBMISSION_INTERIM_APPROVED, (
        "the interim verdict moves the submission to INTERIM_APPROVED"
    )
    assert submission["interim_piece_cap"] == 5_000, (
        "the cap supplied in the body is recorded on the submission"
    )

    design = X.refresh_design(api, world.design_id)
    assert design["release_status"] == C.RELEASE_PROTOTYPE, (
        "an interim verdict promotes nothing: the design stays PROTOTYPE_RELEASED"
    )

    tool = X.refresh_tooling(api, world.tooling_id)
    assert tool["amortization_status"] == C.AMORT_PENDING, (
        "only a full APPROVE arms amortization, so the tool stays PENDING"
    )
    assert tool["amortization_basis_pieces"] is None, (
        "the amortization basis is frozen only when the tool is armed"
    )
    assert tool["amort_per_piece_cents"] is None, (
        "the per-piece figure is frozen only when the tool is armed"
    )

    program = X.refresh_program(api, world.program_id)
    assert program["quote_frozen"] is False, (
        "quote_frozen is set true by the full-approval cascade alone"
    )
    assert program["delivery_posture"] == C.POSTURE_ON_TRACK, (
        "a granted verdict with no quarantined lot and no held run reads ON_TRACK"
    )


def test_interim_approval_without_a_piece_cap_is_malformed(api: ApiClient) -> None:
    """The cap is not optional on the interim branch.

    An `INTERIM_APPROVE` body carrying no `interim_piece_cap` is a malformed
    request, so the verdict never lands: the submission is still the `SUBMITTED`
    package it was when it was filed, with no cap recorded against it.

    PRD §3.10: "It requires an `interim_piece_cap` in the body that is present and greater than zero; a missing or non-positive cap is a malformed request and answers `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.10: "The submission moves to `INTERIM_APPROVED` with the cap recorded, and `delivery_posture` is re-derived — an interim verdict counts as an approval for posture purposes, so a blocked program becomes `ON_TRACK` or `AT_RISK`."
    PRD §3.10: "A successful filing opens at `round_no` 1 in `submission_status` `SUBMITTED` with `submitted_by_user_id` stamped from the header, `interim_piece_cap`, `reviewed_by_program_id` and `decided_at` all null."
    Design: Corner/endpoints/interim_approval_requires_the_piece_cap_that_a_plain_approval_must_omit
    """
    world = X.submitted_world(api)

    response = api.review_submission(
        world.submission_id,
        {"decision": C.DECISION_INTERIM_APPROVE},
        world.customer,
    )
    validate_error(response, ERR_INVALID_REQUEST, 400)

    submission = X.refresh_submission(api, world.submission_id)
    assert submission["submission_status"] == C.SUBMISSION_SUBMITTED, (
        "a malformed verdict leaves the package where the filing put it"
    )
    assert submission["interim_piece_cap"] is None, (
        "no cap was recorded, because no interim verdict landed"
    )


def test_wire_lot_create_read_and_filtered_list_agree_on_one_heat(
    api: ApiClient,
) -> None:
    """One heat described three times: at receipt, on its read, and through the filter.

    HT-800 arrives as 800.000 kg with every kilogram free, is tested at 1930 MPa
    against the 1900 MPa grade it was purchased on and so moves to `CERTIFIED`, and
    the listing filtered to `CERTIFIED` answers that single row with the same
    three-bucket ledger the read exposes.

    PRD §3.5: "The receiving payload names the `material_spec_id`, the mill's `heat_number` — unique across all wire lots — and `received_kg`, the kilograms received, which must be greater than zero and is carried to three decimal places."
    PRD §3.5: "At receipt the three buckets are opened with all mass free: `on_hand_kg` equals `received_kg`, while `reserved_kg` and `consumed_kg` both start at 0.000."
    PRD §3.5: "`certification_status` starts at `UNCERTIFIED`, and both `tensile_test_mpa` and `certified_by_user_id` are null."
    PRD §3.5: "Both outcomes record the supplied `tensile_test_mpa` on the lot and stamp `certified_by_user_id` with the inspector's `X-User-ID`."
    PRD §3.5: "The outcomes differ only in the comparison against the grade: when the measured value is at least the linked material specification's `tensile_grade_mpa`, the lot moves `UNCERTIFIED → CERTIFIED`; when the measured value falls below that grade, the lot moves `UNCERTIFIED → REJECTED` and no run may ever draw from it."
    PRD §3.5: "Wire lots may be listed filtered by `material_spec_id` and `certification_status`, and each read exposes the full three-bucket ledger."
    Design: Corner/endpoints/wire_lot_create_read_and_filtered_list_agree_on_the_same_row
    """
    material = X.register_material(api)

    received = X.receive_wire(api, material["id"])
    assert received["certification_status"] == C.CERT_UNCERTIFIED, (
        "a heat books in as UNCERTIFIED"
    )
    assert received["received_kg"] == 800.0, "received_kg is the mass booked in"
    assert received["on_hand_kg"] == 800.0, "on_hand_kg opens equal to received_kg"
    assert received["reserved_kg"] == 0.0, "reserved_kg opens at 0.000"
    assert received["consumed_kg"] == 0.0, "consumed_kg opens at 0.000"
    assert received["tensile_test_mpa"] is None, (
        "no tensile figure is on file before the incoming test"
    )

    certified = X.certify_wire(api, received["id"])
    assert certified["id"] == received["id"], (
        "certification decides the heat that was received, not a new row"
    )
    assert certified["certification_status"] == C.CERT_CERTIFIED, (
        "1930 MPa is at least the 1900 MPa grade, so the heat is CERTIFIED"
    )

    read = validate_success(api.get_wire_lot(received["id"], QUALITY_INSPECTOR_HEADERS))
    assert read["id"] == received["id"], "the read answers the same heat"
    assert read["certification_status"] == C.CERT_CERTIFIED, (
        "the read agrees with the certification verdict"
    )
    assert read["certified_by_user_id"] == QUALITY_INSPECTOR_PRIMARY, (
        "certified_by_user_id is stamped with the inspector's X-User-ID"
    )

    response = api.list_wire_lots(
        QUALITY_INSPECTOR_HEADERS, params={"certification_status": C.CERT_CERTIFIED}
    )
    rows, meta = validate_paginated(response)

    assert response.json()["response_type"] == "array", "a listing answers an array"
    assert len(rows) == 1, "one heat has cleared its test, so one row matches"
    assert meta["total_count"] == 1, "total_count counts the rows matching the filter"
    assert rows[0]["id"] == received["id"], (
        "the filtered row is the heat the create and the read describe"
    )
    assert rows[0]["heat_number"] == C.CANONICAL_HEAT_NUMBER, (
        "heat_number is the mill identifier the heat was booked in under"
    )
    assert rows[0]["certification_status"] == C.CERT_CERTIFIED, (
        "the filter matches on the lot's own certification_status"
    )
    assert rows[0]["tensile_test_mpa"] == 1930, (
        "the measured tensile figure is recorded on the lot"
    )
    assert rows[0]["received_kg"] == 800.0, "received_kg is fixed at receipt"
    assert rows[0]["on_hand_kg"] == 800.0, (
        "no run has drawn on the heat, so every kilogram is still on hand"
    )
    assert rows[0]["reserved_kg"] == 0.0, "nothing is reserved against the heat"


def test_inspection_listing_separates_the_fai_row_from_the_spc_rows(
    api: ApiClient,
) -> None:
    """Three records on one run, and the record_kind filter returns exactly two.

    The first article and both production subgroups measure the same free length
    at [59.95, 60.0, 60.05] against 59.5/60.5 limits, so every row carries a Cpk of
    0.5 / (3 x 0.05) = 3.333. The pooled figure is what separates them: the first
    in-process row pools three readings and reads 3.727 once six readings are in the
    pool, while the first-article row it was measured beside carries no pooled figure
    at all.

    PRD §3.7: "The server stamps `record_kind` as `FAI` from the endpoint itself; `record_kind` is never accepted from a request body."
    PRD §3.7: "`sigma_value` is the Bessel-corrected sample standard deviation: take each measurement's deviation from the **unrounded** mean, square it, sum the squares, divide by one less than the subgroup size, take the square root, and round half up to six decimal places."
    PRD §3.7: "`cpk_value` is the short-run capability of this subgroup: take the characteristic's `usl` minus the unrounded mean, and the unrounded mean minus the characteristic's `lsl`, keep whichever of those two distances is **smaller**, divide it by three times the unrounded standard deviation, and round half up to three decimal places."
    PRD §3.7: "`ppk_value` is the pooled long-run capability and is **null on every first-article record**."
    PRD §3.7: "On an in-process record it is computed by pooling every measurement of every inspection record whose `record_kind` is `SPC` and which shares both this record's `run_id` and its `characteristic_id`, including the record being created, into one single sample; records belonging to other runs never pool in, and the order in which records are pooled does not change the result."
    PRD §3.7: "Each record keeps the pooled figure it was stamped with at its own creation — earlier rows are never restamped when a later subgroup arrives."
    PRD §3.7: "`control_state` is `OUT_OF_CONTROL` when the **rounded** `cpk_value` is below the characteristic's `cpk_floor`, or when any single measurement in the subgroup lies above `usl` or below `lsl`; it is `IN_CONTROL` otherwise."
    PRD §3.7: "Inspection records may be read individually and listed filtered by `run_id`, `characteristic_id`, `record_kind` and `control_state`."
    PRD §3.8: "The server stamps `record_kind` as `SPC` — again from the endpoint, never from the body — stamps `inspected_by_user_id`, and computes the full statistic set of section 3.7 including the pooled `ppk_value`."
    PRD §2.3: "Unless a subsection states otherwise, list endpoints return rows sorted by `created_at` in ascending order, so the oldest row appears first and paging forward walks the collection chronologically."
    Design: Corner/endpoints/inspection_record_listing_separates_the_fai_row_from_the_spc_rows
    """
    world = X.build_world(api, "spc")
    X.record_spc_subgroup(api, world.run_id, world.characteristics[0])
    X.complete_run(api, world.run_id)

    response = api.list_inspection_records(
        QUALITY_INSPECTOR_HEADERS,
        params={"run_id": world.run_id, "record_kind": C.RECORD_KIND_SPC},
    )
    rows, meta = validate_paginated(response)

    assert response.json()["response_type"] == "array", "a listing answers an array"
    assert len(rows) == 2, "the run carries two in-process subgroups"
    assert meta["total_count"] == 2, (
        "the first-article row is excluded by the record_kind filter"
    )
    for row in rows:
        assert row["record_kind"] == C.RECORD_KIND_SPC, (
            "record_kind is stamped by the in-process endpoint that wrote the row"
        )
        assert row["control_state"] == C.CONTROL_IN_CONTROL, (
            "a Cpk of 3.333 clears the 1.333 floor and no reading leaves the band"
        )
        assert row["cpk_value"] == 3.333, (
            "the short-run index is 0.5 / (3 x 0.05) rounded to three decimals"
        )

    assert rows[0]["ppk_value"] == 3.333, (
        "the earlier row pooled its own three readings alone"
    )
    assert rows[1]["ppk_value"] == 3.727, (
        "the later row pools all six readings of the run's SPC records"
    )

    unfiltered = api.list_inspection_records(
        QUALITY_INSPECTOR_HEADERS, params={"run_id": world.run_id}
    )
    all_rows, all_meta = validate_paginated(unfiltered)

    assert all_meta["total_count"] == 3, (
        "dropping the record_kind filter adds the first-article row back"
    )
    first_article = [
        row for row in all_rows if row["record_kind"] == C.RECORD_KIND_FAI
    ]
    assert len(first_article) == 1, "the run took one first-article subgroup"
    assert first_article[0]["ppk_value"] is None, (
        "the pooled figure is null on every first-article record"
    )
    assert first_article[0]["cpk_value"] == 3.333, (
        "the first article measured the same subgroup, so its short-run index matches"
    )
