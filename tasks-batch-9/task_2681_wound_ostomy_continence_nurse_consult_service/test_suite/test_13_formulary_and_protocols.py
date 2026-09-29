"""The formulary and the standing dressing protocol: the tier that decides both the
surcharge and the paperwork, the floor that turns 8.4 changes into 8, and the two
directions in which an archived product still matters."""
from test_helpers import (
    assert_dressing_protocol,
    assert_formulary_product,
    approve_order,
    archive_product_payload,
    cancel_consult_payload,
    create_dressing_protocol_payload,
    create_formulary_product_payload,
    create_order,
    create_product,
    create_surface,
    get_success_data,
    setup_assigned_consult,
    setup_plan_active_consult,
    setup_validated_assessment,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import make_director_headers, make_nurse_headers


DIRECTOR = make_director_headers()


def _product(api, product_id):
    """Re-read one formulary product."""
    return get_success_data(api.get_formulary_product(product_id, DIRECTOR))


def _protocol(api, protocol_id):
    """Re-read one dressing protocol."""
    return get_success_data(api.get_dressing_protocol(protocol_id, DIRECTOR))


def _consult(api, consult_id):
    """Re-read one consult request."""
    return get_success_data(api.get_consult_request(consult_id, DIRECTOR))


def _order(api, order_id):
    """Re-read one rental order."""
    return get_success_data(api.get_support_surface_order(order_id, DIRECTOR))


def _unit(api, unit_id):
    """Re-read one unit and its rental ledger."""
    return get_success_data(api.get_unit(unit_id, DIRECTOR))


def _file_protocol(api, consult, product, nurse, **overrides):
    """Attempt the protocol filing as the nurse and hand back the raw response."""
    return api.create_dressing_protocol(
        create_dressing_protocol_payload(consult["id"], product["id"], **overrides),
        make_nurse_headers(nurse["id"]),
    )


def test_a_product_without_a_unit_cost_never_reaches_the_uniqueness_check(api):
    """The one omitted field is caught by shape, so the sku it named stays free.

    PRD §3.9: "A `WocProgramDirector` curates the product catalogue, adding a
    product with a `sku`, a `name`, a `category`, a `unit_cost_cents` and a
    `formulary_tier`."
    PRD §3.9: "`unit_cost_cents` is the cost of a single unit, at least 0 and at
    most 1000000."
    PRD §2.10 rung 3: "Request-body and query-string schema conformance: every
    required field present, every type correct, every enum member legal, every
    numeric range and string length honored, `limit` within 1 through 100 and
    `offset` at least 0 — `ERR_INVALID_REQUEST` (400), on every endpoint."

    Design: Corner/entities/formulary_product_create_missing_required_unit_cost_rejected
    """
    response = api.create_formulary_product(
        {
            "sku": "FOAM-99",
            "name": "Silicone foam dressing",
            "category": "FOAM",
            "formulary_tier": "PREFERRED",
        },
        DIRECTOR,
    )
    validate_error(response, "ERR_INVALID_REQUEST", expected_status=400)

    _rows, meta = validate_paginated(api.list_formulary_products(DIRECTOR))
    assert meta["total_count"] == 0, "the rejected create persisted nothing"

    accepted = get_success_data(
        api.create_formulary_product(
            create_formulary_product_payload(
                sku="FOAM-99",
                name="Silicone foam dressing",
                category="FOAM",
                unit_cost_cents=1200,
                formulary_tier="PREFERRED",
            ),
            DIRECTOR,
        )
    )
    assert_formulary_product(accepted)
    assert accepted["sku"] == "FOAM-99", (
        "the shape failure never claimed the natural key, so the same sku is "
        "still available"
    )
    assert accepted["unit_cost_cents"] == 1200
    assert accepted["status"] == "ACTIVE"


def test_a_revision_leaves_exactly_one_live_protocol_on_the_consult(api):
    """Halving the change interval doubles neither cost nor the count of live rows.

    PRD §3.9: "`changes_per_week` is 168 hours — one week — divided by
    `change_frequency_hours`, discarding any remainder, so a 12-hour interval
    yields 14 changes and a 5-day interval yields 1."
    PRD §3.9: "`weekly_cost_cents` is then `changes_per_week` multiplied by the
    product's `unit_cost_cents` multiplied by `units_per_change`."
    PRD §3.9: "Any protocol already `ACTIVE` on the same consult moves `ACTIVE →
    SUPERSEDED` and is versioned, so a consult never carries two live protocols."
    PRD §3.9: "And the consult advances, `ASSESSED → PLAN_ACTIVE` on a first
    protocol or holding at `PLAN_ACTIVE` on a revision, and is versioned."

    Design: Corner/state_machines/revised_dressing_protocol_supersedes_prior_active_protocol
    """
    scenario = setup_plan_active_consult(
        api=api,
        unit_overrides={"unit_code": "3E", "name": "Three East", "bed_count": 18},
        patient_overrides={"mrn": "MRN-H5", "admitted_at": "2026-07-31T12:00:00Z"},
        assessment_overrides={"present_on_admission_claimed": True},
        present_on_admission_confirmed=True,
        product_overrides={
            "sku": "FOAM-02",
            "name": "Silicone foam dressing 15x15",
            "category": "FOAM",
            "unit_cost_cents": 1250,
            "formulary_tier": "PREFERRED",
        },
        protocol_overrides={"change_frequency_hours": 48, "units_per_change": 2},
    )
    first = scenario["protocol"]
    assert_dressing_protocol(first)
    assert first["status"] == "ACTIVE"
    assert first["changes_per_week"] == 3, "168 divided by 48 discarding the remainder"
    assert first["weekly_cost_cents"] == 7500, "3 changes at 1250 cents for 2 units"

    before = _consult(api, scenario["consult"]["id"])
    assert before["status"] == "PLAN_ACTIVE"

    revision = validate_success(
        _file_protocol(
            api,
            scenario["consult"],
            scenario["product"],
            scenario["nurse"],
            change_frequency_hours=24,
            units_per_change=1,
        ),
        expected_status=201,
    )
    assert revision["status"] == "ACTIVE"
    assert revision["changes_per_week"] == 7, "168 divided by 24 exactly"
    assert revision["weekly_cost_cents"] == 8750, (
        "7 changes at 1250 cents for 1 unit; a PREFERRED tier carries no surcharge"
    )
    assert _protocol(api, first["id"])["status"] == "SUPERSEDED"

    after = _consult(api, scenario["consult"]["id"])
    assert after["status"] == "PLAN_ACTIVE", "a revision holds the consult where it is"
    assert after["version"] == before["version"] + 1, (
        "the self-transition still versions the consult"
    )

    live, meta = validate_paginated(
        api.list_dressing_protocols(
            DIRECTOR,
            {"consult_request_id": scenario["consult"]["id"], "status": "ACTIVE"},
        )
    )
    assert meta["total_count"] == 1, "a consult never carries two live protocols"
    assert live[0]["id"] == revision["id"]

    assert (
        get_success_data(
            api.get_skin_assessment(scenario["assessment"]["id"], DIRECTOR)
        )["validation_status"]
        == "VALIDATED"
    ), "filing a protocol never touches the assessment behind it"


def test_the_same_regimen_costs_twenty_percent_more_off_formulary(api):
    """Two protocols identical but for the product's tier, and a 20-hour floor.

    PRD §3.9: "`changes_per_week` is 168 hours — one week — divided by
    `change_frequency_hours`, discarding any remainder, so a 12-hour interval
    yields 14 changes and a 5-day interval yields 1."
    PRD §3.9: "On a `PREFERRED` or `RESTRICTED` product that product is the answer
    exactly, with no rounding needed."
    PRD §3.9: "On a `NON_FORMULARY` product a 20 percent surcharge is applied: the
    base figure is multiplied by 1.20 and the result rounded half up to whole
    cents."

    Design: Corner/calculations/dressing_protocol_non_formulary_surcharge_and_floor_applied
    """
    scenario = setup_validated_assessment(
        api=api,
        unit_overrides={"unit_code": "3E", "name": "Three East", "bed_count": 18},
        patient_overrides={"mrn": "MRN-N1", "admitted_at": "2026-07-31T12:00:00Z"},
        assessment_overrides={"present_on_admission_claimed": True},
        present_on_admission_confirmed=True,
    )
    on_formulary = create_product(
        api=api,
        sku="BARR-01",
        name="Hydrocolloid barrier 10x10",
        category="HYDROCOLLOID",
        unit_cost_cents=1000,
        formulary_tier="RESTRICTED",
    )
    off_formulary = create_product(
        api=api,
        sku="BARR-02",
        name="Silver hydrocolloid barrier 10x10",
        category="HYDROCOLLOID",
        unit_cost_cents=1000,
        formulary_tier="NON_FORMULARY",
    )

    restricted = validate_success(
        _file_protocol(
            api,
            scenario["consult"],
            on_formulary,
            scenario["nurse"],
            change_frequency_hours=20,
            units_per_change=1,
        ),
        expected_status=201,
    )
    assert restricted["changes_per_week"] == 8, (
        "168 over 20 is 8.4 changes, and the remainder is discarded"
    )
    assert restricted["changes_per_week"] != 9, "a ceiling would have given 9"
    assert restricted["weekly_cost_cents"] == 8000, (
        "8 changes at 1000 cents for 1 unit, with no surcharge on formulary"
    )

    non_formulary = validate_success(
        _file_protocol(
            api,
            scenario["consult"],
            off_formulary,
            scenario["nurse"],
            change_frequency_hours=20,
            units_per_change=1,
            justification=(
                "Documented sensitivity to the formulary hydrocolloid; silver "
                "barrier required for 14 days."
            ),
        ),
        expected_status=201,
    )
    assert non_formulary["changes_per_week"] == 8, "the identical floor on both rows"
    assert non_formulary["weekly_cost_cents"] == 9600, (
        "8000 multiplied by 1.20 and rounded half up to whole cents"
    )
    assert non_formulary["weekly_cost_cents"] != 10800, (
        "10800 is what a ceiling-based 9 changes with the surcharge would cost"
    )
    assert (
        non_formulary["weekly_cost_cents"] - restricted["weekly_cost_cents"] == 1600
    ), "the whole difference between the two rows is the tier"

    retired = _protocol(api, restricted["id"])
    assert retired["status"] == "SUPERSEDED"
    assert retired["weekly_cost_cents"] == 8000, (
        "supersession does not recompute the retired protocol's cost"
    )
    assert _consult(api, scenario["consult"]["id"])["status"] == "PLAN_ACTIVE"


def test_whether_a_justification_is_required_is_a_property_of_the_product(api):
    """One byte-identical request, accepted or refused by the tier it points at.

    PRD §3.9: "On an on-formulary product the `justification` remains optional,
    and where supplied it is still bounded at 1 to 500 characters."
    PRD §3.9: "Separately, when the selected product's `formulary_tier` is
    `NON_FORMULARY`, a `justification` of 1 to 500 non-blank characters is
    mandatory, and its absence, nullity or blankness is refused with
    `ERR_NON_FORMULARY_JUSTIFICATION_REQUIRED`."
    PRD §2.10 rung 56: "A non-blank `justification` of 1 to 500 characters is
    present whenever the selected product's `formulary_tier` is `NON_FORMULARY` —
    `ERR_NON_FORMULARY_JUSTIFICATION_REQUIRED` (422), on
    `POST /dressing-protocols`."

    Design: Corner/validations/non_formulary_protocol_without_justification_rejected
    """
    scenario = setup_validated_assessment(
        api=api,
        unit_overrides={"unit_code": "3E", "name": "Three East", "bed_count": 18},
        patient_overrides={"mrn": "MRN-U1", "admitted_at": "2026-07-31T12:00:00Z"},
        assessment_overrides={"present_on_admission_claimed": True},
        present_on_admission_confirmed=True,
    )
    restricted_product = create_product(
        api=api,
        sku="DRSG-10",
        name="Foam dressing 10x10",
        category="FOAM",
        unit_cost_cents=1000,
        formulary_tier="RESTRICTED",
    )
    non_formulary_product = create_product(
        api=api,
        sku="DRSG-11",
        name="Silver foam dressing 10x10",
        category="SILVER_ANTIMICROBIAL",
        unit_cost_cents=1000,
        formulary_tier="NON_FORMULARY",
    )

    silent_but_accepted = validate_success(
        _file_protocol(
            api,
            scenario["consult"],
            restricted_product,
            scenario["nurse"],
            change_frequency_hours=24,
            units_per_change=1,
        ),
        expected_status=201,
    )
    assert silent_but_accepted["changes_per_week"] == 7
    assert silent_but_accepted["weekly_cost_cents"] == 7000, (
        "7 changes at 1000 cents for 1 unit, and RESTRICTED is on formulary"
    )
    held = _consult(api, scenario["consult"]["id"])
    assert held["status"] == "PLAN_ACTIVE"

    refused = _file_protocol(
        api,
        scenario["consult"],
        non_formulary_product,
        scenario["nurse"],
        change_frequency_hours=24,
        units_per_change=1,
    )
    validate_error(
        refused, "ERR_NON_FORMULARY_JUSTIFICATION_REQUIRED", expected_status=422
    )

    _rows, meta = validate_paginated(
        api.list_dressing_protocols(
            DIRECTOR, {"consult_request_id": scenario["consult"]["id"]}
        )
    )
    assert meta["total_count"] == 1, "the refused revision wrote no protocol row"
    assert _protocol(api, silent_but_accepted["id"])["status"] == "ACTIVE", (
        "a failed revision must not supersede the incumbent"
    )
    unmoved = _consult(api, scenario["consult"]["id"])
    assert unmoved["status"] == "PLAN_ACTIVE"
    assert unmoved["version"] == held["version"], (
        "the refusal left the consult exactly where the first protocol put it"
    )

    with_justification = validate_success(
        _file_protocol(
            api,
            scenario["consult"],
            non_formulary_product,
            scenario["nurse"],
            change_frequency_hours=24,
            units_per_change=1,
            justification=(
                "Documented foam sensitivity; silver antimicrobial approved by the "
                "WOC director for 14 days."
            ),
        ),
        expected_status=201,
    )
    assert with_justification["weekly_cost_cents"] == 8400, (
        "7000 base multiplied by 1.20 on the non-formulary branch"
    )
    assert _protocol(api, silent_but_accepted["id"])["status"] == "SUPERSEDED", (
        "only the accepted filing supersedes the incumbent"
    )


def test_archiving_blocks_the_next_protocol_and_cannot_be_repeated(api):
    """The archived row keeps its old protocol and refuses every new one.

    PRD §3.9: "A product starts `ACTIVE` and may be archived by the director with
    a `reason`, moving it `ACTIVE → ARCHIVED`."
    PRD §3.9: "Archiving is forward-looking only: dressing protocols already
    written against the product keep their status and their computed cost
    untouched, and only *new* protocol authorship is blocked — naming an
    `ARCHIVED` product on a new protocol is refused with
    `ERR_RESOURCE_NOT_ACTIVE`."
    PRD §2.10 rung 17: "Catalogue rows are live: the referenced support surface's
    `status` is not `RETIRED`, the referenced formulary product's `status` is
    `ACTIVE`, and a surface being retired has no order on it whose
    `fulfillment_status` is `REQUESTED`, `APPROVED` or `DELIVERED` —
    `ERR_RESOURCE_NOT_ACTIVE` (409), on `POST /support-surface-orders`,
    `POST /support-surfaces/{surface_id}/retire`, `POST /dressing-protocols` and
    `POST /formulary-products/{product_id}/archive`."

    Design: Corner/endpoints/archived_product_conditional_action_rejects_protocol_and_second_archive
    """
    scenario = setup_plan_active_consult(
        api=api,
        unit_overrides={"unit_code": "3E", "name": "Three East", "bed_count": 18},
        patient_overrides={"mrn": "MRN-AF1", "admitted_at": "2026-07-31T12:00:00Z"},
        assessment_overrides={"present_on_admission_claimed": True},
        present_on_admission_confirmed=True,
        product_overrides={
            "sku": "DRSG-30",
            "name": "Foam dressing 10x10",
            "category": "FOAM",
            "unit_cost_cents": 1000,
            "formulary_tier": "PREFERRED",
        },
        protocol_overrides={"change_frequency_hours": 24, "units_per_change": 1},
    )
    doomed = scenario["product"]
    incumbent = scenario["protocol"]
    assert incumbent["weekly_cost_cents"] == 7000

    successor_product = create_product(
        api=api,
        sku="DRSG-31",
        name="Foam dressing 15x15",
        category="FOAM",
        unit_cost_cents=1000,
        formulary_tier="PREFERRED",
    )

    archived = validate_success(
        api.archive_formulary_product(
            doomed["id"],
            archive_product_payload(reason="Vendor discontinued the 10x10 foam."),
            DIRECTOR,
        )
    )
    assert archived["status"] == "ARCHIVED"

    kept = _protocol(api, incumbent["id"])
    assert kept["status"] == "ACTIVE", "archiving looks forward only"
    assert kept["weekly_cost_cents"] == 7000, "the stored cost is left untouched"
    assert kept["formulary_product_id"] == doomed["id"], (
        "the archived product still resolves for the protocol that cites it"
    )

    before = _consult(api, scenario["consult"]["id"])
    refused_protocol = _file_protocol(
        api,
        scenario["consult"],
        doomed,
        scenario["nurse"],
        change_frequency_hours=12,
        units_per_change=1,
    )
    validate_error(refused_protocol, "ERR_RESOURCE_NOT_ACTIVE", expected_status=409)

    _rows, meta = validate_paginated(
        api.list_dressing_protocols(
            DIRECTOR, {"consult_request_id": scenario["consult"]["id"]}
        )
    )
    assert meta["total_count"] == 1, "the refused authorship created no row"
    assert _protocol(api, incumbent["id"])["status"] == "ACTIVE"
    unmoved = _consult(api, scenario["consult"]["id"])
    assert unmoved["status"] == "PLAN_ACTIVE"
    assert unmoved["version"] == before["version"]

    second_archive = api.archive_formulary_product(
        doomed["id"],
        archive_product_payload(
            reason="Duplicate archive request from the formulary committee."
        ),
        DIRECTOR,
    )
    validate_error(second_archive, "ERR_RESOURCE_NOT_ACTIVE", expected_status=409)
    assert _product(api, doomed["id"])["status"] == "ARCHIVED"

    accepted = validate_success(
        _file_protocol(
            api,
            scenario["consult"],
            successor_product,
            scenario["nurse"],
            change_frequency_hours=12,
            units_per_change=1,
        ),
        expected_status=201,
    )
    assert accepted["changes_per_week"] == 14, "168 divided by 12"
    assert accepted["weekly_cost_cents"] == 14000, (
        "14 changes at 1000 cents for 1 unit, the same arithmetic the archived "
        "product would have earned"
    )
    assert _protocol(api, incumbent["id"])["status"] == "SUPERSEDED", (
        "only the accepted filing supersedes the incumbent"
    )
    assert _consult(api, scenario["consult"]["id"])["status"] == "PLAN_ACTIVE"


def test_only_the_linked_rental_is_released_when_the_consult_is_cancelled(api):
    """Two identical encumbrances, and the optional link decides which one returns.

    PRD §3.8: "Either a `MaterialsCoordinator` or a `WocNurse` may raise a rental
    order, naming the `patient_id`, the `unit_id` whose ledger will be charged,
    the `support_surface_id` of the physical asset, a `rental_start`, a
    `rental_end` and an `authorized_days` figure; a `consult_request_id` may
    optionally be supplied to tie the rental to the consult that justifies it."
    PRD §3.4: "The second hop follows from the cancellation: every rental order
    that names this consult in its `consult_request_id` and whose `billing_status`
    is `ENCUMBERED` has its `billing_status` moved `ENCUMBERED → RELEASED`, and
    every such order whose `fulfillment_status` is still `REQUESTED` additionally
    moves `REQUESTED → DENIED` with its `denial_reason` recorded as the literal
    string `CONSULT_CANCELLED`; each affected order row is versioned."
    PRD §3.4: "The third hop follows from the second: for every order whose
    billing moved to `RELEASED`, that order's unit has its
    `rental_encumbered_cents` reduced by the order's `authorized_cost_cents`, its
    `rental_released_cents` raised by the same `authorized_cost_cents`, its
    `rental_available_cents` recomputed, and its row versioned — the money is
    returned to headroom and simultaneously written into the lifetime release
    counter."

    Design: Corner/endpoints/optional_consult_link_scopes_the_cancel_release
    """
    scenario = setup_assigned_consult(
        api=api,
        unit_overrides={
            "unit_code": "3E",
            "name": "Three East",
            "bed_count": 18,
            "rental_budget_cap_cents": 200000,
        },
        patient_overrides={"mrn": "MRN-AD1", "admitted_at": "2026-07-31T00:00:00Z"},
        consult_overrides={
            "clinical_note": "Sacral wound; specialty surface requested."
        },
    )
    unit = scenario["unit"]
    patient = scenario["patient"]
    consult = scenario["consult"]

    linked_surface = create_surface(
        api=api,
        asset_tag="BED-205",
        surface_class="LOW_AIR_LOSS",
        daily_rate_cents=10000,
        vendor_name="AirBeds Inc",
    )
    lone_surface = create_surface(
        api=api,
        asset_tag="BED-206",
        surface_class="LOW_AIR_LOSS",
        daily_rate_cents=10000,
        vendor_name="AirBeds Inc",
    )

    linked_order = create_order(
        unit,
        patient,
        linked_surface,
        api=api,
        rental_start="2026-08-01T00:00:00Z",
        rental_end="2026-08-04T00:00:00Z",
        authorized_days=3,
        consult_request_id=consult["id"],
    )
    lone_order = create_order(
        unit,
        patient,
        lone_surface,
        api=api,
        rental_start="2026-08-01T00:00:00Z",
        rental_end="2026-08-04T00:00:00Z",
        authorized_days=3,
    )
    assert linked_order["consult_request_id"] == consult["id"]
    assert lone_order["consult_request_id"] is None, (
        "the omitted optional input took its declared default"
    )

    linked_order = approve_order(linked_order, unit, api=api)
    lone_order = approve_order(lone_order, unit, api=api)
    for order in (linked_order, lone_order):
        assert order["fulfillment_status"] == "APPROVED"
        assert order["billing_status"] == "ENCUMBERED"
        assert order["authorized_cost_cents"] == 32400, (
            "3 days at 10000 cents is 30000, plus 8 percent of that pre-fee figure"
        )

    encumbered = _unit(api, unit["id"])
    assert encumbered["rental_encumbered_cents"] == 64800
    assert encumbered["rental_released_cents"] == 0
    assert encumbered["rental_available_cents"] == 135200, "200000 cap less 64800"

    cancelled = validate_success(
        api.cancel_consult_request(
            consult["id"],
            cancel_consult_payload(
                reason=(
                    "Patient transferred to another facility before the surface "
                    "arrived."
                )
            ),
            DIRECTOR,
        )
    )
    assert cancelled["status"] == "CANCELLED"

    released = _order(api, linked_order["id"])
    assert released["billing_status"] == "RELEASED", (
        "the link is the only reason this order is in the cascade"
    )
    assert released["fulfillment_status"] == "APPROVED", (
        "the denial hop only reaches orders still sitting at REQUESTED"
    )

    untouched = _order(api, lone_order["id"])
    assert untouched["billing_status"] == "ENCUMBERED", (
        "it shares the unit, the patient, the interval and the amount, and still "
        "keeps its money"
    )
    assert untouched["version"] == lone_order["version"], (
        "an order outside the cascade is not even versioned"
    )

    settled = _unit(api, unit["id"])
    assert settled["rental_encumbered_cents"] == 32400
    assert settled["rental_released_cents"] == 32400
    assert settled["rental_available_cents"] == 167600, (
        "exactly one order's worth of money came back to headroom"
    )
