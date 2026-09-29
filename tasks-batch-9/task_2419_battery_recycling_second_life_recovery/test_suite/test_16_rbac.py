"""Role separation: the nine exclusive lanes, the deny list and the two duty splits."""
from test_helpers import (
    assert_supplier_obligation_invariant,
    factories as f,
    fixtures as fx,
    make_compliance_officer_headers,
    make_plant_operator_headers,
    make_supplier_rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import (
    ASSAY_TECHNICIAN_USER_ID,
    CLOCK_INTAKE,
    CLOCK_PROCESS,
    CO_CLOSER_USER_ID,
    CO_SUBMITTER_USER_ID,
    TRIAGE_ENGINEER_USER_ID,
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


# --------------------------------------------------------------------------
# Nine roles, nine lanes, one shipment
# --------------------------------------------------------------------------

def test_nine_roles_hand_one_shipment_down_the_line_each_in_its_own_lane(api):
    """Every step of the journey is taken by the one role that owns it, each acting on a
    row the previous role created, and two shared reads still cross the lanes freely.

    PRD §2.1: "An `IntakeClerk` books arriving shipments, records the chemistry confirmed
    at the identification bench, and books dismantled modules against a shipment."; "A
    `PlantOperator` runs the plant floor: discharge measurements, packaging, custody
    release, module shipping, campaign scheduling and start and cancellation, lot opening,
    lot charging and lot voiding."

    Design: Corner/rbac/each_role_performs_its_own_exclusive_operations_end_to_end
    """
    clock = fx.move_clock(api, CLOCK_PROCESS, headers=fx.ADMIN)
    assert clock["current_utc"] == CLOCK_PROCESS, "only a PlatformAdmin drives the clock"
    facility = fx.create_facility(api, headers=fx.ADMIN)
    supplier = fx.create_supplier(api, headers=fx.ADMIN)
    quote = fx.publish_quote(
        api, "NI", 1600, "2026-07-01T00:00:00.000Z", headers=fx.ANALYST
    )
    assert quote["price_cents_per_kg"] == 1600, "the price feed is the analyst's only write"
    line = fx.create_line(api, facility["id"], headers=fx.ADMIN, **_HUNDRED_KG_HOUR_LINE)

    intake = fx.book_intake(
        api,
        supplier["id"],
        facility["id"],
        headers=fx.CLERK,
        gross_mass_kg=110.0,
        packaging_tare_kg=10.0,
        declared_ni_pct=30.0,
    )
    intake_id = intake["id"]
    fx.identify_chemistry(api, intake_id, "NMC622", headers=fx.CLERK)
    module = fx.add_module(api, intake_id, "M-1", headers=fx.CLERK)

    fx.discharge(api, intake_id, soc_pct=12.0, headers=fx.OPERATOR)
    fx.package(api, intake_id, headers=fx.OPERATOR)

    decision = fx.triage_module(api, module["id"], headers=fx.ENGINEER)
    assert decision["disposition"] == "MATERIAL_RECOVERY"
    assert decision["decided_by_user_id"] == TRIAGE_ENGINEER_USER_ID

    manifest = fx.submit_manifest(api, intake_id, headers=fx.SUBMITTER)
    assert manifest["submitted_by_user_id"] == CO_SUBMITTER_USER_ID
    closed = fx.close_manifest(api, intake_id, manifest["id"], headers=fx.CLOSER)
    assert closed["closed_by_user_id"] == CO_CLOSER_USER_ID

    released = fx.release(api, intake_id, headers=fx.OPERATOR)
    assert released["custody_state"] == "RELEASED"

    campaign = fx.create_campaign(
        api, line["id"], headers=fx.OPERATOR, **dict(_ONE_DAY_WINDOW)
    )
    fx.start_campaign(api, campaign["id"], headers=fx.OPERATOR)
    lot = fx.open_lot(api, campaign["id"], lot_code="LOT-1", headers=fx.OPERATOR)
    charged = fx.charge_lot(api, lot["id"], [module["id"]], headers=fx.OPERATOR)
    assert charged["status"] == "CHARGED"

    nickel = fx.book_output(api, lot["id"], "NI", 30.0, 99.0, headers=fx.TECHNICIAN)
    assert nickel["recorded_by_user_id"] == ASSAY_TECHNICIAN_USER_ID
    fx.book_output(api, lot["id"], "MN", 10.0, 96.0, headers=fx.TECHNICIAN)
    finalized = fx.finalize_lot(api, lot["id"], 57.0, headers=fx.TECHNICIAN)
    assert finalized["status"] == "FINALIZED"
    assert float(finalized["recycled_content_pct"]) == 40.00

    allotment = fx.create_allotment(
        api, facility["id"], headers=fx.SUBMITTER, permit_no="NV-W-001"
    )
    event = fx.book_discharge_event(
        api,
        lot["id"],
        allotment["id"],
        "2026-08-20T09:00:00.000Z",
        5.0,
        headers=fx.SUBMITTER,
    )
    assert event["status"] == "POSTED"

    passport = fx.issue_passport(
        api, lot["id"], headers=fx.CERTIFIER, passport_code="BP-1", customer_name="Aurora Cathode"
    )
    assert passport["status"] == "ISSUED"

    settlement = fx.settlement_for_intake(api, intake_id, headers=fx.ACCOUNTANT)
    posted = fx.post_settlement(api, settlement["id"], headers=fx.ACCOUNTANT)
    assert posted["state"] == "POSTED"
    assert posted["variant"] == "FINAL"
    assert posted["posted_amount_cents"] == settlement["net_payable_cents"]

    counterparty = fx.read_supplier(api, supplier["id"], headers=fx.ACCOUNTANT)
    assert counterparty["payable_balance_cents"] == posted["posted_amount_cents"]
    assert_supplier_obligation_invariant(counterparty, [posted])

    shared_lot_read = validate_success(api.get_lot(lot["id"], fx.CERTIFIER))
    assert shared_lot_read["id"] == lot["id"], "a read surface may list many roles at once"
    shared_intake_read = validate_success(api.get_intake(intake_id, fx.TECHNICIAN))
    assert shared_intake_read["id"] == intake_id


# --------------------------------------------------------------------------
# The deny list is per endpoint, and it is consulted early
# --------------------------------------------------------------------------

def test_seven_foreign_roles_are_turned_away_from_seven_exclusive_operations(api):
    """Each attempt is made by a role that has no business on that endpoint, two of them
    would also have failed a later tier, and the world is byte-identical afterwards.

    PRD §2.1: "If both headers are well formed but the named role is not among the roles
    authorised for the endpoint being called, the request is rejected with
    `ERR_FORBIDDEN_ROLE` and HTTP 403."

    PRD §2.7: "Checks are evaluated in the following thirteen tiers, and the **first**
    tier that fails determines the response; no later tier can mask an earlier one."

    Design: Corner/rbac/foreign_roles_are_forbidden_on_other_roles_exclusive_operations
    """
    ctx = fx.bootstrap_network(api, clock=CLOCK_INTAKE, quotes=None)
    facility_id = ctx["facility"]["id"]
    supplier_id = ctx["supplier"]["id"]
    walked = fx.advance_intake(ctx, stop_after="manifest", intake={"declared_ni_pct": 30.0})
    intake_id = walked["intake"]["id"]
    manifest_id = walked["manifest"]["id"]
    module_id = walked["modules"][0]["id"]

    validate_error(
        api.create_intake(
            f.create_intake_payload(
                supplier_id, facility_id, gross_mass_kg=50.0, packaging_tare_kg=5.0
            ),
            fx.ENGINEER,
        ),
        "ERR_FORBIDDEN_ROLE",
        403,
    )
    validate_error(api.release_intake(intake_id, fx.CLERK), "ERR_FORBIDDEN_ROLE", 403)
    validate_error(
        api.create_triage_decision(
            module_id, f.create_triage_decision_payload("CONSERVATIVE"), fx.OPERATOR
        ),
        "ERR_FORBIDDEN_ROLE",
        403,
    )
    validate_error(
        api.close_manifest(
            intake_id, manifest_id, make_plant_operator_headers(CO_SUBMITTER_USER_ID)
        ),
        "ERR_FORBIDDEN_ROLE",
        403,
    )
    validate_error(
        api.create_quality_strike(
            supplier_id, f.create_quality_strike_payload("QA-001"), fx.OPERATOR
        ),
        "ERR_FORBIDDEN_ROLE",
        403,
    )
    validate_error(
        api.create_facility(
            f.create_facility_payload(
                name="Rogue Campus",
                mech_capacity_kg_per_day=10.0,
                hydro_capacity_kg_per_day=10.0,
            ),
            fx.SUBMITTER,
        ),
        "ERR_FORBIDDEN_ROLE",
        403,
    )
    validate_error(
        api.create_metal_index_price(
            f.create_metal_index_price_payload("NI", 1, "2026-07-01T00:00:00.000Z"),
            fx.ACCOUNTANT,
        ),
        "ERR_FORBIDDEN_ROLE",
        403,
    )

    _, intake_meta = validate_paginated(api.list_intakes(fx.ADMIN))
    assert intake_meta["total_count"] == 1, "the forbidden booking created no shipment"
    intake = fx.read_intake(api, intake_id)
    assert intake["custody_state"] == "PACKAGED", (
        "the forbidden release reports the role, not the compliance state that also blocked it"
    )
    assert intake["compliance_state"] == "MANIFEST_SUBMITTED", (
        "the forbidden close reports the role, not the duty split that also blocked it"
    )
    assert validate_success(api.get_module(module_id, fx.ENGINEER))["status"] == "PENDING_TRIAGE"
    assert fx.read_supplier(api, supplier_id)["quality_strike_count"] == 0
    _, quote_meta = validate_paginated(api.list_metal_index_prices(fx.ANALYST))
    assert quote_meta["total_count"] == 0


# --------------------------------------------------------------------------
# The two duty splits: one on identity, one structural
# --------------------------------------------------------------------------

def test_the_officer_who_signed_the_manifest_may_not_counter_sign_it(api):
    """The role is right and the paperwork is in the right state, yet the close is refused
    on identity alone, and the same call from a colleague of the same role goes through.

    PRD §2.1: "Closing a hazardous-material manifest requires that the `X-User-ID`
    performing the close differs from the `submitted_by_user_id` recorded when the manifest
    was submitted; if they are equal the request is rejected with
    `ERR_SEGREGATION_OF_DUTIES` and HTTP 403, even though both actors hold the
    `ComplianceOfficer` role."

    Design: Corner/rbac/one_officer_cannot_both_submit_and_close_a_manifest
    """
    first_officer = make_compliance_officer_headers("co-1")
    second_officer = make_compliance_officer_headers("co-2")

    ctx = fx.bootstrap_network(api, clock=CLOCK_INTAKE)
    walked = fx.advance_intake(
        ctx, stop_after="manifest", modules=(), submitter=first_officer
    )
    intake_id = walked["intake"]["id"]
    manifest_id = walked["manifest"]["id"]
    assert walked["manifest"]["submitted_by_user_id"] == "co-1"
    assert walked["manifest"]["version"] == 1

    validate_error(
        api.close_manifest(intake_id, manifest_id, first_officer),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )

    refused, meta = validate_paginated(api.list_manifests(intake_id, first_officer))
    assert meta["total_count"] == 1
    assert refused[0]["status"] == "SUBMITTED"
    assert refused[0]["closed_by_user_id"] is None
    assert refused[0]["version"] == 1
    assert fx.read_intake(api, intake_id)["compliance_state"] == "MANIFEST_SUBMITTED"

    closed = validate_success(api.close_manifest(intake_id, manifest_id, second_officer))
    assert closed["status"] == "CLOSED"
    assert closed["closed_by_user_id"] == "co-2", "same role, different actor, duty split met"
    assert closed["version"] == 2

    released = validate_success(api.release_intake(intake_id, fx.OPERATOR))
    assert released["custody_state"] == "RELEASED", (
        "the refused close was the only thing holding the shipment up"
    )


def test_the_assay_bench_and_the_cash_desk_cannot_reach_into_each_other(api):
    """Four denials in two directions on rows both roles may read, and the same four
    operations succeed the moment each is attempted by its owning role.

    PRD §2.1: "The equivalent separation between assay work and money work is enforced
    structurally rather than by comparing identifiers: `AssayTechnician` is simply not
    authorised on any settlement posting, cash-settlement or voiding endpoint, and
    `SettlementAccountant` is not authorised on recovery-output booking or lot
    finalization."

    Design: Corner/rbac/assay_technician_cannot_post_the_settlement_its_yields_priced
    """
    ctx = fx.charged_lot(
        api,
        network={"clock": CLOCK_PROCESS, "quotes": _JULY_NICKEL},
        intake={"intake": {"declared_ni_pct": 30.0}},
        processing={"line": _HUNDRED_KG_HOUR_LINE, "campaign": dict(_ONE_DAY_WINDOW)},
    )
    lot_id = ctx["lot"]["id"]
    supplier_id = ctx["supplier"]["id"]

    visible, _ = validate_paginated(
        api.list_settlements(fx.TECHNICIAN, params={"intake_id": ctx["intake"]["id"]})
    )
    settlement_id = visible[0]["id"]
    assert visible[0]["state"] == "DRAFT", "the technician may read what it may not move"
    assert visible[0]["version"] == 1

    validate_error(
        api.post_settlement(settlement_id, fx.TECHNICIAN), "ERR_FORBIDDEN_ROLE", 403
    )
    validate_error(
        api.void_settlement(
            settlement_id, f.void_settlement_payload("Assay technician tidying up"), fx.TECHNICIAN
        ),
        "ERR_FORBIDDEN_ROLE",
        403,
    )
    validate_error(
        api.create_recovery_output(
            lot_id, f.create_recovery_output_payload("NI", 30.0, 99.0), fx.ACCOUNTANT
        ),
        "ERR_FORBIDDEN_ROLE",
        403,
    )
    validate_error(
        api.finalize_lot(lot_id, f.finalize_lot_payload(67.0), fx.ACCOUNTANT),
        "ERR_FORBIDDEN_ROLE",
        403,
    )

    untouched = fx.read_settlement(api, settlement_id)
    assert untouched["state"] == "DRAFT"
    assert untouched["posted_amount_cents"] == 0
    assert untouched["version"] == 1
    assert fx.read_supplier(api, supplier_id)["payable_balance_cents"] == 0
    still_charged = fx.read_lot(api, lot_id)
    assert still_charged["status"] == "CHARGED"
    assert float(still_charged["recovered_mass_kg"]) == 0.0
    _, ledger_meta = validate_paginated(api.list_recovery_outputs(lot_id, fx.TECHNICIAN))
    assert ledger_meta["total_count"] == 0

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
    posted = validate_success(api.post_settlement(settlement_id, fx.ACCOUNTANT))
    assert posted["state"] == "POSTED"
    assert posted["variant"] == "FINAL"
    assert fx.read_supplier(api, supplier_id)["payable_balance_cents"] == (
        posted["posted_amount_cents"]
    )


# --------------------------------------------------------------------------
# The one entity-backed role: ownership, not membership
# --------------------------------------------------------------------------

def test_a_rival_counterparty_cannot_dispute_a_settlement_it_does_not_own(api):
    """Both representatives hold the same role on the same endpoint, so only the identity
    comparison separates them, and the owner's identical challenge is accepted at once.

    PRD §2.1: "Concretely, when a `SupplierRep` disputes a settlement, the settlement's
    `supplier_id` must equal `X-User-ID`, and a mismatch is rejected with `ERR_NOT_OWNER`
    and HTTP 403."

    Design: Corner/rbac/another_suppliers_representative_cannot_dispute_this_settlement
    """
    ctx = fx.bootstrap_network(api, clock=CLOCK_PROCESS, quotes=_JULY_NICKEL)
    rival = fx.create_supplier(
        api, legal_name="Rival Metals", channel="DISMANTLER", credit_limit_cents=100_000
    )
    shipper_id = ctx["supplier"]["id"]
    fx.advance_intake(ctx, intake={"declared_ni_pct": 12.0})
    fx.advance_processing(
        ctx,
        line=_HUNDRED_KG_HOUR_LINE,
        campaign=dict(_ONE_DAY_WINDOW),
        outputs=(("NI", 30.0, 99.0),),
        residue_mass_kg=67.0,
    )
    settlement_id = ctx["settlement"]["id"]
    assert ctx["settlement"]["variant"] == "FINAL"
    assert float(ctx["settlement"]["max_variance_pp"]) == 18.00

    posted = fx.post_settlement(api, settlement_id)
    assert posted["state"] == "POSTED"
    assert posted["version"] == 3, "created at release, re-priced at finalize, posted here"
    owed = fx.read_supplier(api, shipper_id)["payable_balance_cents"]

    validate_error(
        api.dispute_settlement(
            settlement_id,
            f.dispute_settlement_payload("Rival Metals objects on principle"),
            make_supplier_rep_headers(rival["id"]),
        ),
        "ERR_NOT_OWNER",
        403,
    )
    refused = fx.read_settlement(api, settlement_id)
    assert refused["state"] == "POSTED"
    assert refused["dispute_round"] == 0
    assert refused["dispute_reason"] is None
    assert refused["version"] == 3

    disputed = validate_success(
        api.dispute_settlement(
            settlement_id,
            f.dispute_settlement_payload("Northstar contests the nickel yield"),
            make_supplier_rep_headers(shipper_id),
        )
    )
    assert disputed["state"] == "DISPUTED"
    assert disputed["dispute_round"] == 1
    assert disputed["dispute_reason"] == "Northstar contests the nickel yield"
    assert disputed["version"] == 4

    assert fx.read_supplier(api, shipper_id)["payable_balance_cents"] == owed, (
        "a disputed amount is still owed"
    )
    assert fx.read_supplier(api, rival["id"])["version"] == 1
