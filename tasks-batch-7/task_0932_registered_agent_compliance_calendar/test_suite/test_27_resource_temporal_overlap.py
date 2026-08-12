"""Half-open occupancy on a jurisdiction, and forward-only rule versions."""
from test_helpers import (
    ADMIN,
    AGENT,
    DE_RULE_FULL,
    DE_RULE_SAME_DAY_COLLISION,
    DE_RULE_V2_JULY,
    OFFICER,
    TX_RULE_FULL,
    ApiErrorId,
    accept_appointment,
    activate_registration,
    api_client,
    assert_filing_total,
    capture,
    draft_standalone_filing,
    new_certificate,
    new_clearance,
    new_client,
    new_entity,
    new_home_registration,
    new_obligation,
    new_payment,
    propose_appointment,
    publish_rule,
    qualify_foreign,
    read_registration,
    record_filing_outcome,
    set_clock,
    setup_active_home_registration,
    submit_filing,
    validate_error,
    validate_paginated,
    validate_success,
)


def _occupied_texas_scene():
    """A Delaware home registration plus an ACTIVE Texas qualification opened on
    2026-06-15."""
    publish_rule(DE_RULE_FULL)
    publish_rule(TX_RULE_FULL)
    client = new_client()
    entity = new_entity(client["id"])
    home = new_home_registration(entity["id"])
    home_appointment = propose_appointment(home)
    accept_appointment(home_appointment["id"])
    activate_registration(home["id"])
    certificate = new_certificate(home["id"], issued_on="2026-06-01")
    clearance = new_clearance(entity["id"], result="AVAILABLE", state_code="TX")

    set_clock("2026-06-15T00:00:00Z")
    texas = qualify_foreign(entity["id"], "TX", clearance["id"], certificate["id"])
    texas_appointment = propose_appointment(
        texas, provider_name="Lone Star Agents", appointed_on="2026-06-15"
    )
    accept_appointment(texas_appointment["id"])
    activate_registration(texas["id"])
    return {
        "client": client,
        "entity": entity,
        "home": home,
        "texas": texas,
        "certificate": certificate,
        "clearance": clearance,
    }


def _withdraw_texas(scene):
    """Lodge and accept the withdrawal filing, then withdraw the Texas registration."""
    filing = draft_standalone_filing(
        scene["texas"]["id"], "WITHDRAWAL", expedite_tier="NONE"
    )
    payment = new_payment(scene["client"]["id"], 6400)
    capture(payment["id"], 6400, filing["id"])
    submit_filing(filing["id"])
    record_filing_outcome(filing["id"], "ACCEPTED")
    validate_success(api_client.withdraw_registration(scene["texas"]["id"], AGENT))
    return filing


def _rule_version_scene():
    """One open Delaware rule version and one obligation pinned to it."""
    scene = setup_active_home_registration(DE_RULE_FULL)
    scene["obligation_v1"] = new_obligation(
        scene["registration"]["id"], "ANNUAL_REPORT", 2027
    )
    return scene


def test_a_second_registration_in_an_occupied_state_is_refused(api):
    """PRD §2.9: "no other registration for the same combination of legal entity and
    `state_code` currently occupies the interval. A row in status `PENDING`, `ACTIVE`,
    `DELINQUENT` or `ADMIN_DISSOLVED` blocks outright; a closed row blocks when the new
    registration's start date is strictly before that row's `closed_on`."
    PRD §3.7: "For a standalone filing, `state_fee_cents` comes from the jurisdiction
    rule by kind: `foreign_qualification_fee_cents` for a `FOREIGN_QUALIFICATION`,
    `withdrawal_fee_cents` for a `WITHDRAWAL`, `dissolution_fee_cents` for a
    `DISSOLUTION`, and for a `REINSTATEMENT` the `back_fee_total_cents` already assessed
    on the reinstatement case; and `service_fee_cents` is the base service charge of
    4900 cents."

    Design: Difficulty/resource_temporal_overlap/registration_occupancy_interval_is_half_open_per_state
    """
    scene = _occupied_texas_scene()

    response = api.create_foreign_qualification(
        scene["entity"]["id"],
        {
            "state_code": "TX",
            "name_clearance_id": scene["clearance"]["id"],
            "good_standing_certificate_id": scene["certificate"]["id"],
        },
        OFFICER,
    )

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_DUPLICATE_REGISTRATION.value)

    filing = draft_standalone_filing(
        scene["texas"]["id"], "WITHDRAWAL", expedite_tier="NONE"
    )
    # Texas charges 1500 to withdraw; the platform charges its 4900 base service fee.
    assert filing["state_portion_cents"] == 1500
    assert filing["service_portion_cents"] == 4900
    assert filing["total_fee_cents"] == 6400
    assert_filing_total(filing)


def test_a_registration_starting_on_the_closing_boundary_is_accepted(api):
    """PRD §3.2: "The occupancy interval a registration holds is half-open: it starts on
    `qualified_on` and runs up to but not including `closed_on`."
    PRD §3.12: "On success the registration moves `ACTIVE → WITHDRAWN` and `closed_on`
    is stamped with the current clock date."
    PRD §2.9: "a closed row blocks when the new registration's start date is strictly
    before that row's `closed_on`."

    Design: Difficulty/resource_temporal_overlap/registration_occupancy_interval_is_half_open_per_state
    """
    scene = _occupied_texas_scene()
    _withdraw_texas(scene)

    withdrawn = read_registration(scene["texas"]["id"])
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["closed_on"] == "2026-06-15"

    # The clock still reads 2026-06-15, so the new row starts exactly on the closed
    # row's closed_on — adjacency at the closing boundary, not overlap.
    successor = validate_success(
        api.create_foreign_qualification(
            scene["entity"]["id"],
            {
                "state_code": "TX",
                "name_clearance_id": scene["clearance"]["id"],
                "good_standing_certificate_id": scene["certificate"]["id"],
            },
            OFFICER,
        ),
        201,
    )
    assert successor["state_code"] == "TX"
    assert successor["registration_kind"] == "FOREIGN"
    assert successor["status"] == "PENDING"

    _rows, meta = validate_paginated(
        api.list_registrations(
            ADMIN,
            params={"legal_entity_id": scene["entity"]["id"], "state_code": "TX"},
        )
    )
    assert meta["total_count"] == 2


def test_republishing_on_the_incumbents_own_date_is_refused(api):
    """PRD §2.6: "A new row's `effective_from` must be strictly later than the
    `effective_from` of the currently open row for the same `state_code`; a value equal
    to or earlier than the incumbent's is rejected with `ERR_EFFECTIVE_DATE_OVERLAP` and
    HTTP 409."
    PRD §2.6: "The new row is created with `effective_to` null, and the row that was
    previously open for that same `state_code` has its `effective_to` stamped with the
    new row's `effective_from`, closing it."

    Design: Difficulty/resource_temporal_overlap/state_rule_effective_interval_must_progress_strictly_forward
    """
    scene = _rule_version_scene()
    version_one_id = scene["obligation_v1"]["governing_rule_id"]

    collision = api.create_state_rule(DE_RULE_SAME_DAY_COLLISION, ADMIN)
    assert collision.status_code == 409
    validate_error(collision, ApiErrorId.ERR_EFFECTIVE_DATE_OVERLAP.value)

    version_two = validate_success(api.create_state_rule(DE_RULE_V2_JULY, ADMIN), 201)
    assert version_two["effective_to"] is None

    rows, _meta = validate_paginated(api.list_state_rules(ADMIN, params={"limit": 100}))
    closed = [row for row in rows if row["id"] == version_one_id]
    assert len(closed) == 1
    assert closed[0]["effective_to"] == "2026-07-01"


def test_the_new_version_prices_new_rows_and_never_moves_the_old_one(api):
    """PRD §2.6: "Publishing a rule row never rewrites `governing_rule_id` on any
    existing `ComplianceObligation`."
    PRD §2.6: "A rule version published in a later year does not move an obligation that
    was already determined, and a calendar rebuild explicitly re-derives dates under the
    obligation's own pinned rule rather than under today's."
    PRD §3.5: "for `ANNUAL_REPORT` and for `FINAL_REPORT` it is the rule's
    `annual_report_fee_cents`; for `FRANCHISE_TAX` it is the rule's
    `franchise_tax_filing_fee_cents`; and for `BOI_INITIAL` and `BOI_UPDATE` it is 0,
    because the beneficial-ownership registry charges no state filing fee."

    Design: Difficulty/resource_temporal_overlap/state_rule_effective_interval_must_progress_strictly_forward
    """
    scene = _rule_version_scene()
    version_one_id = scene["obligation_v1"]["governing_rule_id"]

    version_two = validate_success(api.create_state_rule(DE_RULE_V2_JULY, ADMIN), 201)
    set_clock("2026-08-01T00:00:00Z")
    obligation_v2 = new_obligation(
        scene["registration"]["id"], "ANNUAL_REPORT", 2028
    )

    # The 2027 row was determined on 2026-05-01 and keeps version one's 3/1 date and
    # its 5000 annual-report fee.
    assert scene["obligation_v1"]["governing_rule_id"] == version_one_id
    assert scene["obligation_v1"]["due_date"] == "2027-03-01"
    assert scene["obligation_v1"]["state_fee_cents"] == 5000

    # The 2028 row is determined on 2026-08-01 under version two: 4/15 in 2028 is a
    # Saturday, which rolls forward to Monday 2028-04-17, and the fee is 12000.
    assert obligation_v2["governing_rule_id"] == version_two["id"]
    assert obligation_v2["due_date"] == "2028-04-17"
    assert obligation_v2["state_fee_cents"] == 12000
