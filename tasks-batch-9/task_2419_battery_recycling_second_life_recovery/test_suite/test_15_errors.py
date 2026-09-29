"""Error surfaces: the distinct 404 codes, authentication, and the state guards."""
from test_helpers import (
    assert_supplier_obligation_invariant,
    factories as f,
    fixtures as fx,
    make_headers,
    make_supplier_rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import (
    CLOCK_INTAKE,
    CLOCK_PROCESS,
    CO_CLOSER_USER_ID,
    CO_THIRD_USER_ID,
    CO_SUBMITTER_USER_ID,
)

_JULY_NICKEL = [
    {"metal": "NI", "effective_date": "2026-07-01T00:00:00.000Z", "price_cents_per_kg": 1600}
]
_HUNDRED_KG_HOUR_LINE = {
    "line_code": "HYD-1",
    "line_type": "HYDROMET",
    "chemistry_family": "NICKEL_RICH",
    "throughput_kg_per_hour": 100.0,
}
_ONE_DAY_WINDOW = {
    "window_start": "2026-08-20T00:00:00.000Z",
    "window_end": "2026-08-21T00:00:00.000Z",
    "planned_input_kg": 1000.0,
}
_MISSING = "aaaaaaaa-0000-4000-8000-0000000000{:02d}"


def _settlements_of(api, supplier_id):
    data, _ = validate_paginated(
        api.list_settlements(fx.ACCOUNTANT, params={"supplier_id": supplier_id})
    )
    return data


# --------------------------------------------------------------------------
# Not-found codes and authentication
# --------------------------------------------------------------------------

def test_each_unknown_identifier_reports_the_entity_it_could_not_resolve(api):
    """Ten sibling reads and one nested action each answer with their own 404 code, and
    the nested manifest lookup wins over the state guard that would also have refused it.

    PRD §2.6: "The corresponding 404 responses are `ERR_FACILITY_NOT_FOUND`,
    `ERR_SUPPLIER_NOT_FOUND`, `ERR_INTAKE_NOT_FOUND`, `ERR_MANIFEST_NOT_FOUND`,
    `ERR_MODULE_NOT_FOUND`, `ERR_LINE_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`,
    `ERR_LOT_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`,
    `ERR_DISCHARGE_EVENT_NOT_FOUND` and `ERR_PASSPORT_NOT_FOUND`."

    Design: Corner/errors/every_unknown_path_id_returns_its_own_not_found_error
    """
    ctx = fx.bootstrap_network(api, clock=CLOCK_INTAKE, quotes=None)
    walked = fx.advance_intake(ctx, stop_after="manifest", modules=())
    intake_id = walked["intake"]["id"]
    manifest_id = walked["manifest"]["id"]
    assert walked["manifest"]["status"] == "SUBMITTED"

    lookups = (
        (api.get_facility(_MISSING.format(1), fx.ADMIN), "ERR_FACILITY_NOT_FOUND"),
        (api.get_supplier(_MISSING.format(2), fx.ACCOUNTANT), "ERR_SUPPLIER_NOT_FOUND"),
        (api.get_module(_MISSING.format(3), fx.ENGINEER), "ERR_MODULE_NOT_FOUND"),
        (api.get_processing_line(_MISSING.format(4), fx.OPERATOR), "ERR_LINE_NOT_FOUND"),
        (api.get_campaign(_MISSING.format(5), fx.OPERATOR), "ERR_CAMPAIGN_NOT_FOUND"),
        (api.get_lot(_MISSING.format(6), fx.TECHNICIAN), "ERR_LOT_NOT_FOUND"),
        (api.get_settlement(_MISSING.format(7), fx.ACCOUNTANT), "ERR_SETTLEMENT_NOT_FOUND"),
        (api.get_permit_allotment(_MISSING.format(8), fx.SUBMITTER), "ERR_PERMIT_NOT_FOUND"),
        (
            api.get_discharge_event(_MISSING.format(9), fx.SUBMITTER),
            "ERR_DISCHARGE_EVENT_NOT_FOUND",
        ),
        (api.get_passport(_MISSING.format(10), fx.CERTIFIER), "ERR_PASSPORT_NOT_FOUND"),
    )
    for response, expected_error_id in lookups:
        validate_error(response, expected_error_id, 404)

    validate_error(
        api.close_manifest(intake_id, _MISSING.format(11), fx.CLOSER),
        "ERR_MANIFEST_NOT_FOUND",
        404,
    )

    manifests, meta = validate_paginated(api.list_manifests(intake_id, fx.SUBMITTER))
    assert meta["total_count"] == 1
    assert manifests[0]["id"] == manifest_id
    assert manifests[0]["status"] == "SUBMITTED", "no refused lookup mutated anything"
    intake = fx.read_intake(api, intake_id)
    assert intake["compliance_state"] == "MANIFEST_SUBMITTED"
    assert intake["custody_state"] == "PACKAGED"


def test_authentication_is_settled_before_any_other_tier_is_consulted(api):
    """A missing role header, a missing identity header and an undeclared role all answer
    401, even when the target is absent and the body is out of range.

    PRD §2.7: "1. **Header authentication** — both `X-User-ID` and `X-User-Role` present
    and the role declared. `ERR_UNAUTHENTICATED`, 401. Applies to every endpoint."

    Design: Corner/errors/request_without_a_declared_role_header_returns_unauthenticated
    """
    fx.move_clock(api, CLOCK_INTAKE)
    facility = fx.create_facility(api)

    no_role = {"X-User-ID": "test-platform-admin-1", "Content-Type": "application/json"}
    no_identity = {"X-User-Role": "PlantOperator", "Content-Type": "application/json"}
    undeclared_role = make_headers("wk-1", "WarehouseKeeper")

    validate_error(api.get_facility(facility["id"], no_role), "ERR_UNAUTHENTICATED", 401)
    validate_error(api.get_facility(facility["id"], no_identity), "ERR_UNAUTHENTICATED", 401)
    validate_error(
        api.get_facility("bbbbbbbb-0000-4000-8000-000000000001", undeclared_role),
        "ERR_UNAUTHENTICATED",
        401,
    )
    validate_error(
        api.create_intake(
            f.create_intake_payload(
                "bbbbbbbb-0000-4000-8000-000000000002",
                facility["id"],
                declared_chemistry="LTO",
                declared_ni_pct=f.OMIT,
            ),
            undeclared_role,
        ),
        "ERR_UNAUTHENTICATED",
        401,
    )

    _, meta = validate_paginated(api.list_intakes(fx.ADMIN))
    assert meta["total_count"] == 0, "no unauthenticated call had any effect"


# --------------------------------------------------------------------------
# State guards on the compliance and processing machines
# --------------------------------------------------------------------------

def test_a_closed_manifest_refuses_both_a_second_close_and_a_rejection(api):
    """CLOSED is terminal for a paperwork revision, so the same code answers a repeat
    close and a late rejection, and neither drags the shipment back out of compliance.

    PRD §3.3: "It requires the manifest's `status` to be `SUBMITTED` — otherwise
    `ERR_MANIFEST_NOT_SUBMITTED` — and it requires the shipment's `custody_state` to be
    `PACKAGED`, because there is nothing to sign off until the cells are actually in
    their drums."

    Design: Corner/errors/manifest_close_and_reject_both_require_the_submitted_status
    """
    ctx = fx.bootstrap_network(api, clock=CLOCK_INTAKE, quotes=None)
    walked = fx.advance_intake(ctx, stop_after="manifest", modules=())
    intake_id = walked["intake"]["id"]
    manifest_id = walked["manifest"]["id"]
    assert walked["manifest"]["revision"] == 1
    assert walked["manifest"]["status"] == "SUBMITTED"
    assert walked["manifest"]["submitted_by_user_id"] == CO_SUBMITTER_USER_ID

    closed = validate_success(api.close_manifest(intake_id, manifest_id, fx.CLOSER))
    assert closed["status"] == "CLOSED"
    assert closed["closed_by_user_id"] == CO_CLOSER_USER_ID
    assert closed["version"] == 2
    assert fx.read_intake(api, intake_id)["compliance_state"] == "MANIFEST_CLOSED"

    third = fx.make_compliance_officer_headers(CO_THIRD_USER_ID)
    validate_error(
        api.close_manifest(intake_id, manifest_id, third),
        "ERR_MANIFEST_NOT_SUBMITTED",
        409,
    )
    validate_error(
        api.reject_manifest(
            intake_id, manifest_id, f.reject_manifest_payload("Transporter licence expired"), third
        ),
        "ERR_MANIFEST_NOT_SUBMITTED",
        409,
    )

    listed, meta = validate_paginated(
        api.list_manifests(intake_id, fx.SUBMITTER, params={"status": "CLOSED"})
    )
    assert meta["total_count"] == 1
    assert listed[0]["id"] == manifest_id
    assert listed[0]["status"] == "CLOSED"
    assert listed[0]["version"] == 2
    assert listed[0]["rejection_reason"] is None

    intake = fx.read_intake(api, intake_id)
    assert intake["compliance_state"] == "MANIFEST_CLOSED"
    assert intake["custody_state"] == "PACKAGED", "a refused reject performs no quarantine"


def test_the_assay_ledger_is_writable_only_inside_the_charged_window(api):
    """One code guards both assay endpoints on both sides of the window: an open lot
    takes neither an assay line nor a finalize, and a finalized lot takes no further line.

    PRD §3.7: "The lot's `status` must be `CHARGED`, otherwise `ERR_LOT_NOT_CHARGED`."

    Design: Corner/errors/assay_writes_require_a_lot_in_the_charged_state
    """
    ctx = fx.build_world(
        api,
        stop_after="lot",
        network={"clock": CLOCK_PROCESS, "quotes": _JULY_NICKEL},
        intake={"intake": {"declared_ni_pct": 30.0}},
        processing={"line": _HUNDRED_KG_HOUR_LINE, "campaign": dict(_ONE_DAY_WINDOW)},
    )
    lot_id = ctx["lot"]["id"]
    module_id = ctx["modules"][0]["id"]
    assert ctx["lot"]["status"] == "OPEN"
    assert ctx["lot"]["version"] == 1

    validate_error(
        api.create_recovery_output(
            lot_id, f.create_recovery_output_payload("NI", 30.0, 99.0), fx.TECHNICIAN
        ),
        "ERR_LOT_NOT_CHARGED",
        409,
    )
    _, empty_meta = validate_paginated(api.list_recovery_outputs(lot_id, fx.TECHNICIAN))
    assert empty_meta["total_count"] == 0

    validate_error(
        api.finalize_lot(lot_id, f.finalize_lot_payload(67.0), fx.TECHNICIAN),
        "ERR_LOT_NOT_CHARGED",
        409,
    )

    charged = validate_success(
        api.charge_lot(lot_id, f.charge_lot_payload([module_id], 1), fx.OPERATOR)
    )
    assert charged["status"] == "CHARGED"
    assert charged["version"] == 2

    validate_success(
        api.create_recovery_output(
            lot_id, f.create_recovery_output_payload("NI", 30.0, 99.0), fx.TECHNICIAN
        ),
        expected_status=201,
    )
    finalized = validate_success(
        api.finalize_lot(lot_id, f.finalize_lot_payload(67.0), fx.TECHNICIAN)
    )
    assert finalized["status"] == "FINALIZED"
    assert float(finalized["mass_balance_pct"]) == 97.00

    validate_error(
        api.create_recovery_output(
            lot_id, f.create_recovery_output_payload("CO", 1.0, 90.0), fx.TECHNICIAN
        ),
        "ERR_LOT_NOT_CHARGED",
        409,
    )
    closed_lot = fx.read_lot(api, lot_id)
    assert float(closed_lot["recovered_mass_kg"]) == 30.000
    assert float(closed_lot["recycled_content_pct"]) == 30.00
    _, final_meta = validate_paginated(api.list_recovery_outputs(lot_id, fx.TECHNICIAN))
    assert final_meta["total_count"] == 1


# --------------------------------------------------------------------------
# The settlement machine's four state guards
# --------------------------------------------------------------------------

def test_each_settlement_action_names_the_state_it_needed(api):
    """A draft settlement refuses the umpire pair with two different codes, accepts one
    posting, and then refuses the second posting with a third code.

    PRD §3.9: "Posting a settlement takes no payload and requires its `state` to be
    `DRAFT`, otherwise `ERR_SETTLEMENT_NOT_DRAFT`."; "The settlement's `state` must be
    `DISPUTED`, otherwise `ERR_SETTLEMENT_NOT_DISPUTED`, and an assay line must already
    exist for the requested metal on the contributing lot."

    Design: Corner/errors/settlement_actions_each_demand_their_own_state
    """
    ctx = fx.released_intake(
        api,
        network={"clock": CLOCK_INTAKE, "quotes": _JULY_NICKEL},
        intake={"intake": {"declared_ni_pct": 30.0}, "modules": ()},
    )
    settlement = fx.settlement_for_intake(api, ctx["intake"]["id"])
    settlement_id = settlement["id"]
    assert settlement["state"] == "DRAFT"
    assert settlement["gross_cents"] == 31920
    assert settlement["net_payable_cents"] == 26685
    assert settlement["version"] == 1

    validate_error(
        api.record_umpire_assay(
            settlement_id, f.umpire_assay_payload("NI", 29.0), fx.TECHNICIAN
        ),
        "ERR_SETTLEMENT_NOT_DISPUTED",
        409,
    )
    validate_error(
        api.apply_umpire(settlement_id, fx.ACCOUNTANT),
        "ERR_SETTLEMENT_NOT_IN_UMPIRE_ROUND",
        409,
    )
    untouched = fx.read_settlement(api, settlement_id)
    assert untouched["state"] == "DRAFT"
    assert untouched["version"] == 1
    assert untouched["umpire_metal"] is None
    assert untouched["umpire_contained_kg"] is None

    posted = validate_success(api.post_settlement(settlement_id, fx.ACCOUNTANT))
    assert posted["state"] == "POSTED"
    assert posted["posted_amount_cents"] == 26685
    assert posted["version"] == 2

    validate_error(
        api.post_settlement(settlement_id, fx.ACCOUNTANT), "ERR_SETTLEMENT_NOT_DRAFT", 409
    )
    again = fx.read_settlement(api, settlement_id)
    assert again["posted_amount_cents"] == 26685, "the ledger is not double counted"
    assert again["version"] == 2

    supplier = fx.read_supplier(api, ctx["supplier"]["id"])
    assert supplier["payable_balance_cents"] == 26685
    assert supplier["credit_hold"] is False
    assert supplier["version"] == 2
    assert_supplier_obligation_invariant(supplier, _settlements_of(api, supplier["id"]))


def _finalized_world_declaring(api, declared_ni_pct):
    """One finalized lot recovering exactly thirty kilogrammes of nickel from a hundred
    kilogramme charge, against a shipment that declared the given nickel percentage."""
    return fx.finalized_lot(
        api,
        network={"clock": CLOCK_PROCESS, "quotes": _JULY_NICKEL},
        intake={"intake": {"declared_ni_pct": declared_ni_pct}},
        processing={
            "line": _HUNDRED_KG_HOUR_LINE,
            "campaign": dict(_ONE_DAY_WINDOW),
            "outputs": (("NI", 30.0, 99.0),),
            "residue_mass_kg": 67.0,
        },
    )


def test_a_truthful_declaration_leaves_the_counterparty_nothing_to_dispute(api):
    """A declared thirty percent confirmed by a thirty-kilogramme recovery gives a zero
    variance, and the strictly-greater gate then locks the dispute path entirely.

    PRD §3.9: "the settlement's `max_variance_pp` must be strictly greater than 0.50
    percentage points, otherwise `ERR_VARIANCE_WITHIN_TOLERANCE`; and the settlement's
    `dispute_round` must be below the limit of 3, otherwise
    `ERR_DISPUTE_ROUNDS_EXHAUSTED`."

    Design: Corner/errors/dispute_needs_variance_strictly_above_the_tolerance
    """
    ctx = _finalized_world_declaring(api, 30.0)
    supplier_id = ctx["supplier"]["id"]
    settlement = ctx["settlement"]
    assert settlement["variant"] == "FINAL"
    assert float(settlement["max_variance_pp"]) == 0.00

    posted = fx.post_settlement(api, settlement["id"])
    assert posted["state"] == "POSTED"
    assert fx.read_supplier(api, supplier_id)["quality_strike_count"] == 0, (
        "0.00 is not strictly greater than the severe-variance threshold"
    )

    validate_error(
        api.dispute_settlement(
            settlement["id"],
            f.dispute_settlement_payload("We believe the nickel yield was understated"),
            make_supplier_rep_headers(supplier_id),
        ),
        "ERR_VARIANCE_WITHIN_TOLERANCE",
        422,
    )

    after = validate_success(
        api.get_settlement(settlement["id"], make_supplier_rep_headers(supplier_id))
    )
    assert after["state"] == "POSTED"
    assert after["dispute_round"] == 0
    assert after["dispute_reason"] is None
    assert after["version"] == posted["version"], "the refused dispute wrote nothing"


def test_the_third_umpire_round_is_the_last_one_the_counterparty_gets(api):
    """The commercial cycle is walked three times, the round counter survives every
    return to draft, and the fourth challenge is refused on the round limit alone.

    PRD §3.9: "On success the `dispute_reason` is recorded, `dispute_round` increases by
    1, the settlement moves `POSTED → DISPUTED`, and its `version` increments by 1."

    Design: Corner/errors/three_dispute_rounds_exhaust_the_umpire_cycle
    """
    ctx = _finalized_world_declaring(api, 12.0)
    supplier_id = ctx["supplier"]["id"]
    settlement_id = ctx["settlement"]["id"]
    assert ctx["settlement"]["variant"] == "FINAL"
    assert float(ctx["settlement"]["max_variance_pp"]) == 18.00
    assert ctx["settlement"]["dispute_round"] == 0
    assert fx.read_supplier(api, supplier_id)["quality_strike_count"] == 1

    for expected_round, umpire_kg in ((1, 29.0), (2, 28.0), (3, 27.0)):
        posted = fx.post_settlement(api, settlement_id)
        assert posted["state"] == "POSTED"

        disputed = fx.dispute_settlement(
            api, settlement_id, supplier_id, f"Round {expected_round}: nickel assay contested"
        )
        assert disputed["state"] == "DISPUTED"
        assert disputed["dispute_round"] == expected_round

        umpire = fx.record_umpire_assay(api, settlement_id, "NI", umpire_kg)
        assert umpire["state"] == "UMPIRE_ROUND"
        assert float(umpire["umpire_contained_kg"]) == umpire_kg

        applied = fx.apply_umpire(api, settlement_id)
        assert applied["state"] == "DRAFT"
        assert applied["posted_amount_cents"] == 0
        assert applied["dispute_round"] == expected_round, (
            "returning to DRAFT does not reset the dispute counter"
        )
        assert fx.read_supplier(api, supplier_id)["payable_balance_cents"] == 0

    fourth = fx.post_settlement(api, settlement_id)
    assert fourth["state"] == "POSTED", "the fourth post is legal because the state is DRAFT"

    validate_error(
        api.dispute_settlement(
            settlement_id,
            f.dispute_settlement_payload("Round 4: still contested"),
            make_supplier_rep_headers(supplier_id),
        ),
        "ERR_DISPUTE_ROUNDS_EXHAUSTED",
        409,
    )

    final = fx.read_settlement(api, settlement_id)
    assert final["state"] == "POSTED"
    assert final["dispute_round"] == 3
    supplier = fx.read_supplier(api, supplier_id)
    assert supplier["payable_balance_cents"] == final["posted_amount_cents"]
    assert_supplier_obligation_invariant(supplier, _settlements_of(api, supplier_id))
