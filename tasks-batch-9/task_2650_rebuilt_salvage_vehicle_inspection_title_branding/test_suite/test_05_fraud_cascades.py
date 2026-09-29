"""The program's two deepest fraud cascades, side effect by side effect.

A single stolen-component finding reaches the cited receipt, the application's
documented parts cost, a synthesised identity-tampering referral, the vehicle's
fraud posture and the rebuilder's referral counter. Substantiating a referral
reaches further still: the vehicle's title, every live application of that
vehicle, the escrow those applications held, the attempts booked against them
and the rebuilder's licence.
"""

from test_helpers import (
    api_client,
    assert_fee_ledger_closes,
    create_finding_payload,
    investigate_fraud_referral,
    make_fraud_investigator_headers,
    make_inspector_headers,
    make_state_title_clerk_headers,
    open_fraud_referral,
    read_application,
    read_inspection,
    read_inspector,
    read_parts_document,
    read_rebuilder,
    read_station,
    read_title,
    read_vehicle,
    resolve_fraud_referral,
    resolve_referral_payload,
    setup_inspection_in_progress,
    setup_scheduled_inspection,
    validate_paginated,
    validate_success,
)

api = api_client
CLERK_HEADERS = make_state_title_clerk_headers()

# STRUCTURAL 200000 + RESTRAINT 50000 + LIGHTING 30000 are all verified before
# the cascade withdraws the restraint receipt.
DOCUMENTED_COST_BEFORE_CENTS = 280_000
DOCUMENTED_COST_AFTER_CENTS = 230_000
ESCROWED_CHARGE_CENTS = 20_000
DEPOSIT_CENTS = 500_000
BALANCE_WITH_ESCROW_CENTS = 480_000

STOLEN_DESCRIPTION = "airbag module serial appears on the stolen-parts register"


def _attempt_in_progress() -> dict:
    """A complete SEDAN package carried to an attempt the inspector has started."""
    env = setup_inspection_in_progress()
    application = read_application(env["application_id"])
    assert application["documented_parts_cost_cents"] == DOCUMENTED_COST_BEFORE_CENTS, (
        f"expected {DOCUMENTED_COST_BEFORE_CENTS} documented before the cascade, "
        f"got {application['documented_parts_cost_cents']}"
    )
    vehicle = read_vehicle(env["vehicle_id"])
    assert vehicle["fraud_hold"] == "NONE", (
        f"expected a clean fraud posture before the cascade, got {vehicle['fraud_hold']}"
    )
    return env


def _cite_the_restraint_receipt_as_stolen(env: dict):
    """Record the CRITICAL stolen-component finding against the restraint receipt."""
    return api.create_finding(
        env["inspection_id"],
        create_finding_payload(
            category="STOLEN_COMPONENT",
            severity="CRITICAL",
            description=STOLEN_DESCRIPTION,
            parts_document_id=env["documents"]["RESTRAINT"]["id"],
        ),
        make_inspector_headers(env["inspector_id"]),
    )


def test_a_critical_stolen_component_finding_is_recorded_as_blocking():
    """The inspector's stolen-part observation lands as an unresolved blocker.

    PRD: "The server writes `recorded_by_inspector_id` from the acting principal, sets `resolved` to false, and computes the finding's `blocking` flag, which is true exactly when `severity` is `CRITICAL` or `category` is `STOLEN_COMPONENT` or `VIN_ALTERATION`, and false otherwise."

    Design: Difficulty/transitive_cascade/stolen_component_finding_cascades_document_referral_vehicle_and_rebuilder
    """
    env = _attempt_in_progress()

    response = _cite_the_restraint_receipt_as_stolen(env)
    finding = validate_success(response, expected_status=201)

    assert finding["blocking"] is True, (
        f"a CRITICAL STOLEN_COMPONENT finding must be blocking, got {finding['blocking']}"
    )
    assert finding["resolved"] is False, (
        f"a freshly recorded finding is unresolved, got {finding['resolved']}"
    )
    assert finding["recorded_by_inspector_id"] == env["inspector_id"], (
        f"expected recorded_by_inspector_id {env['inspector_id']}, "
        f"got {finding['recorded_by_inspector_id']}"
    )
    assert finding["category"] == "STOLEN_COMPONENT", (
        f"expected the STOLEN_COMPONENT category to be stored, got {finding['category']}"
    )


def test_the_first_blocking_finding_latches_the_attempts_forced_fail_flag():
    """One blocking finding is enough to doom the attempt whatever it scores.

    PRD: "The first time `blocking_findings_count` reaches 1 or more, the attempt's `forced_fail` latches to true, and once latched it stays true for the remainder of that attempt and forces a `FAIL` result no matter what the adequacy arithmetic says."

    Design: Difficulty/transitive_cascade/stolen_component_finding_cascades_document_referral_vehicle_and_rebuilder
    """
    env = _attempt_in_progress()
    before = read_inspection(env["inspection_id"])
    assert before["blocking_findings_count"] == 0, (
        f"expected no blockers before the finding, got {before['blocking_findings_count']}"
    )
    assert before["forced_fail"] is False, (
        f"expected the latch open before the finding, got {before['forced_fail']}"
    )

    _cite_the_restraint_receipt_as_stolen(env)

    inspection = read_inspection(env["inspection_id"])
    assert inspection["blocking_findings_count"] == 1, (
        f"expected blocking_findings_count 1 after the finding, "
        f"got {inspection['blocking_findings_count']}"
    )
    assert inspection["forced_fail"] is True, (
        f"expected forced_fail latched to true, got {inspection['forced_fail']}"
    )


def test_the_cited_receipt_is_rejected_and_its_amount_leaves_the_documented_cost():
    """Impeaching a verified receipt withdraws the money it documented.

    PRD: "The cited parts document, if it was `VERIFIED`, moves `VERIFIED → REJECTED` with `rejection_reason` set to `STOLEN_COMPONENT`, and because a verified amount has been withdrawn the owning application's `documented_parts_cost_cents` falls by that document's `amount_cents`."

    Design: Difficulty/transitive_cascade/stolen_component_finding_cascades_document_referral_vehicle_and_rebuilder
    """
    env = _attempt_in_progress()
    restraint = env["documents"]["RESTRAINT"]
    assert restraint["status"] == "VERIFIED", (
        f"the restraint receipt must be VERIFIED before the cascade, got {restraint['status']}"
    )

    _cite_the_restraint_receipt_as_stolen(env)

    document = read_parts_document(restraint["id"])
    assert document["status"] == "REJECTED", (
        f"expected the cited receipt to move to REJECTED, got {document['status']}"
    )
    assert document["rejection_reason"] == "STOLEN_COMPONENT", (
        f"expected rejection_reason STOLEN_COMPONENT, got {document['rejection_reason']}"
    )

    application = read_application(env["application_id"])
    assert application["documented_parts_cost_cents"] == DOCUMENTED_COST_AFTER_CENTS, (
        f"expected the documented cost to fall from {DOCUMENTED_COST_BEFORE_CENTS} to "
        f"{DOCUMENTED_COST_AFTER_CENTS}, got {application['documented_parts_cost_cents']}"
    )


def test_the_stolen_component_finding_synthesises_an_identity_tampering_referral():
    """The cascade raises the fraud allegation the inspector did not have to file.

    PRD: "Because that document was impeached as stolen, a fraud referral is synthesised against the vehicle with `referral_type` of `IDENTITY_TAMPERING`, `origin` of `AUTO_CASCADE` and `status` of `OPEN`, whose `opened_by_user_id` is the cascading inspector's `X-User-ID`, and the vehicle's `fraud_hold` moves `NONE → UNDER_REFERRAL`."

    Design: Difficulty/transitive_cascade/stolen_component_finding_cascades_document_referral_vehicle_and_rebuilder
    """
    env = _attempt_in_progress()

    _cite_the_restraint_receipt_as_stolen(env)

    response = api.list_fraud_referrals(CLERK_HEADERS, params={"vehicle_id": env["vehicle_id"]})
    referrals, meta = validate_paginated(response)
    assert meta["total_count"] == 1, (
        f"expected exactly one referral against the vehicle, got {meta['total_count']}"
    )
    referral = referrals[0]
    assert referral["referral_type"] == "IDENTITY_TAMPERING", (
        f"expected referral_type IDENTITY_TAMPERING, got {referral['referral_type']}"
    )
    assert referral["origin"] == "AUTO_CASCADE", (
        f"expected origin AUTO_CASCADE, got {referral['origin']}"
    )
    assert referral["status"] == "OPEN", (
        f"expected the synthesised referral to open in OPEN, got {referral['status']}"
    )
    assert referral["opened_by_user_id"] == env["inspector_id"], (
        f"expected opened_by_user_id {env['inspector_id']} from the cascading inspector, "
        f"got {referral['opened_by_user_id']}"
    )

    vehicle = read_vehicle(env["vehicle_id"])
    assert vehicle["fraud_hold"] == "UNDER_REFERRAL", (
        f"expected the vehicle fraud_hold to move to UNDER_REFERRAL, got {vehicle['fraud_hold']}"
    )


def test_the_cascaded_referral_raises_the_rebuilders_open_referral_count():
    """A single allegation counts against the rebuilder but does not yet bite.

    PRD: "Because that referral now exists and is attached to an application, the owning rebuilder's `open_referral_count` rises by one, and the moment that count reaches 2 the rebuilder's licence moves `ACTIVE → PROBATION` of its own accord."

    Design: Difficulty/transitive_cascade/stolen_component_finding_cascades_document_referral_vehicle_and_rebuilder
    """
    env = _attempt_in_progress()
    before = read_rebuilder(env["rebuilder_id"])
    assert before["open_referral_count"] == 0, (
        f"expected no open referrals before the cascade, got {before['open_referral_count']}"
    )

    _cite_the_restraint_receipt_as_stolen(env)

    rebuilder = read_rebuilder(env["rebuilder_id"])
    assert rebuilder["open_referral_count"] == 1, (
        f"expected open_referral_count to rise to 1, got {rebuilder['open_referral_count']}"
    )
    assert rebuilder["license_status"] == "ACTIVE", (
        f"probation waits for a second open referral, so the licence must still read ACTIVE, "
        f"got {rebuilder['license_status']}"
    )


def _referral_under_investigation() -> dict:
    """A booked attempt on a vehicle whose odometer referral is under investigation."""
    env = setup_scheduled_inspection()
    referral = open_fraud_referral(
        env["vehicle_id"],
        referral_type="ODOMETER",
        evidence_summary="title history shows a 30000-mile rollback",
        application_id=env["application_id"],
    )
    env["referral"] = investigate_fraud_referral(referral["id"])
    env["referral_id"] = referral["id"]
    assert env["referral"]["status"] == "INVESTIGATING", (
        f"expected the referral to be under investigation before the trigger, "
        f"got {env['referral']['status']}"
    )
    return env


def test_substantiating_the_referral_confirms_the_vehicles_fraud_hold():
    """The investigator's finding of fact turns the hold into a permanent one.

    PRD: "`resolved_at` is stamped from the logical clock and the vehicle's `fraud_hold` moves to `CONFIRMED`, which is sticky and never walked back."

    Design: Difficulty/transitive_cascade/substantiated_referral_cascades_title_void_application_void_and_suspension
    """
    env = _referral_under_investigation()

    response = api.resolve_fraud_referral(
        env["referral_id"],
        resolve_referral_payload(
            "SUBSTANTIATED", resolution_note="odometer tampering confirmed by the service history"
        ),
        make_fraud_investigator_headers(),
    )
    resolved = validate_success(response, expected_status=200)

    assert resolved["status"] == "SUBSTANTIATED", (
        f"expected the referral to reach SUBSTANTIATED, got {resolved['status']}"
    )
    assert resolved["resolved_at"] is not None, "resolved_at must be stamped on resolution"

    vehicle = read_vehicle(env["vehicle_id"])
    assert vehicle["fraud_hold"] == "CONFIRMED", (
        f"expected the vehicle fraud_hold to read CONFIRMED, got {vehicle['fraud_hold']}"
    )


def test_confirmed_fraud_voids_the_vehicles_active_title_but_keeps_its_history():
    """The instrument is voided while the brand it carried stays on the record.

    PRD: "Because `fraud_hold` became `CONFIRMED`, the vehicle's `ACTIVE` title record moves `ACTIVE → VOID` with `is_current` driven to false while its `brand_history` is retained for audit; if that title's `recognition_state` was `RECOGNITION_PENDING` it becomes `STALE`."

    Design: Difficulty/transitive_cascade/substantiated_referral_cascades_title_void_application_void_and_suspension
    """
    env = _referral_under_investigation()

    resolve_fraud_referral(env["referral_id"], "SUBSTANTIATED")

    title = read_title(env["salvage_title_id"])
    assert title["status"] == "VOID", (
        f"expected the ACTIVE title to move to VOID, got {title['status']}"
    )
    assert title["is_current"] is False, (
        f"expected is_current driven to false on the voided title, got {title['is_current']}"
    )
    assert "SALVAGE" in title["brand_history"], (
        f"the voided title must retain SALVAGE for audit, got {title['brand_history']}"
    )


def test_the_fraud_void_terminates_the_live_application_and_refunds_its_escrow():
    """A void reaches the live application and hands the escrow back.

    PRD: "Because the vehicle's title was voided, every one of the vehicle's applications whose `status` is not already `TITLE_ISSUED`, `DENIED_FINAL`, `WITHDRAWN` or `VOID_FRAUD` moves to `VOID_FRAUD` with `terminal_at` stamped, and each of those refunds its escrow — the rebuilder's `fee_balance_cents` rises by that application's `fee_escrowed_cents`, which is then zeroed, so `escrowed_fee_total_cents` falls by the refunded amount."

    Design: Difficulty/transitive_cascade/substantiated_referral_cascades_title_void_application_void_and_suspension
    """
    env = _referral_under_investigation()
    before_application = read_application(env["application_id"])
    before_rebuilder = read_rebuilder(env["rebuilder_id"])
    assert before_application["fee_escrowed_cents"] == ESCROWED_CHARGE_CENTS, (
        f"expected {ESCROWED_CHARGE_CENTS} in escrow before the void, "
        f"got {before_application['fee_escrowed_cents']}"
    )
    assert before_rebuilder["fee_balance_cents"] == BALANCE_WITH_ESCROW_CENTS, (
        f"expected fee_balance_cents {BALANCE_WITH_ESCROW_CENTS} before the void, "
        f"got {before_rebuilder['fee_balance_cents']}"
    )

    resolve_fraud_referral(env["referral_id"], "SUBSTANTIATED")

    application = read_application(env["application_id"])
    rebuilder = read_rebuilder(env["rebuilder_id"])
    assert application["status"] == "VOID_FRAUD", (
        f"expected the application to move to VOID_FRAUD, got {application['status']}"
    )
    assert application["terminal_at"] is not None, (
        "terminal_at must be stamped when the application is voided for fraud"
    )
    assert application["fee_escrowed_cents"] == 0, (
        f"expected the escrow zeroed on the voided application, "
        f"got {application['fee_escrowed_cents']}"
    )
    expected_balance = (
        before_rebuilder["fee_balance_cents"] + before_application["fee_escrowed_cents"]
    )
    assert rebuilder["fee_balance_cents"] == expected_balance, (
        f"expected fee_balance_cents to rise by the refunded escrow to {expected_balance}, "
        f"got {rebuilder['fee_balance_cents']}"
    )
    assert rebuilder["fee_balance_cents"] == DEPOSIT_CENTS, (
        f"expected the whole deposit spendable again, got {rebuilder['fee_balance_cents']}"
    )
    assert rebuilder["escrowed_fee_total_cents"] == 0, (
        f"expected escrowed_fee_total_cents 0 after the refund, "
        f"got {rebuilder['escrowed_fee_total_cents']}"
    )
    assert_fee_ledger_closes(rebuilder)


def test_the_fraud_void_cancels_the_booked_attempt_and_releases_the_bay():
    """Voiding the application releases the inspector's hour and the station bay.

    PRD: "Because those applications were voided, each of their attempts sitting in `SCHEDULED` or `IN_PROGRESS` moves to `CANCELLED` with `cancellation_reason` set to `FRAUD_HOLD`, releasing its inspector interval and its station bay by decrementing the inspector's `scheduled_inspection_count` and the station's `scheduled_occupancy_count`."

    Design: Difficulty/transitive_cascade/substantiated_referral_cascades_title_void_application_void_and_suspension
    """
    env = _referral_under_investigation()
    assert read_inspector(env["inspector_id"])["scheduled_inspection_count"] == 1, (
        "the booked attempt must occupy the inspector's calendar before the void"
    )
    assert read_station(env["station_id"])["scheduled_occupancy_count"] == 1, (
        "the booked attempt must occupy a station bay before the void"
    )

    resolve_fraud_referral(env["referral_id"], "SUBSTANTIATED")

    inspection = read_inspection(env["inspection_id"])
    assert inspection["status"] == "CANCELLED", (
        f"expected the SCHEDULED attempt to be CANCELLED, got {inspection['status']}"
    )
    assert inspection["cancellation_reason"] == "FRAUD_HOLD", (
        f"expected cancellation_reason FRAUD_HOLD, got {inspection['cancellation_reason']}"
    )
    assert read_inspector(env["inspector_id"])["scheduled_inspection_count"] == 0, (
        f"expected the inspector interval released, got "
        f"{read_inspector(env['inspector_id'])['scheduled_inspection_count']}"
    )
    assert read_station(env["station_id"])["scheduled_occupancy_count"] == 0, (
        f"expected the station bay released, got "
        f"{read_station(env['station_id'])['scheduled_occupancy_count']}"
    )


def test_a_substantiated_referral_suspends_the_rebuilders_licence():
    """One substantiated allegation is enough to take the licence down.

    PRD: "And the rebuilder's `substantiated_referral_count` rises by one; the moment it reaches 1 the licence moves to `SUSPENDED`."

    Design: Difficulty/transitive_cascade/substantiated_referral_cascades_title_void_application_void_and_suspension
    """
    env = _referral_under_investigation()
    before = read_rebuilder(env["rebuilder_id"])
    assert before["substantiated_referral_count"] == 0, (
        f"expected substantiated_referral_count 0 before the resolution, "
        f"got {before['substantiated_referral_count']}"
    )
    assert before["license_status"] in ("ACTIVE", "PROBATION"), (
        f"expected a live licence before the resolution, got {before['license_status']}"
    )

    resolve_fraud_referral(env["referral_id"], "SUBSTANTIATED")

    rebuilder = read_rebuilder(env["rebuilder_id"])
    assert rebuilder["substantiated_referral_count"] == 1, (
        f"expected substantiated_referral_count 1, got {rebuilder['substantiated_referral_count']}"
    )
    assert rebuilder["license_status"] == "SUSPENDED", (
        f"expected the licence to move to SUSPENDED, got {rebuilder['license_status']}"
    )
