"""Gates that live on an entity other than the one being written.

Both scenarios drive a target resource that is itself flawless and change only the
state of a neighbouring entity, so the refusal and the success differ in nothing
but that neighbour's status.
"""
from test_helpers import (
    ARCHIVE_RESEARCHER,
    CLEARANCE_SUPERVISOR,
    PRODUCTION_ADMIN,
    assert_asset_dimensions,
    assert_license_money_ledger,
    assert_posture,
    assert_production_counters,
    create_archive_with_rate_card,
    create_asset_with_selected_source,
    create_license,
    create_production_in_clearance,
    create_rate_card_payload,
    get_asset,
    get_delivery_package,
    get_license,
    get_production,
    open_delivery_package,
    open_eo_application,
    quote_license,
    record_both_eo_reviews,
    reinstate_archive,
    setup_pinned_chart_production,
    state_payload,
    submit_eo_application,
    suspend_archive,
    validate_delivery_package,
    validate_error,
    validate_paginated,
    validate_success,
)

# The 45-second BROADCAST / WORLD / 36-month all-media licence of the PRD §3.3
# worked example: 60000 * 2 units * 1.25 * 1.15 * 1.50 * 1.00 = 362250 cents.
ALL_MEDIA_FEE_CENTS = 362250

# PRD §3.7 rating of a single CLEARED / LICENSED row against a 4000000-cent limit
# with a 100000-cent retention: 50000 base + 40000 loading - 30000 credit.
EXPECTED_PREMIUM_CENTS = 60000


def _setup_quoted_license_against_suspended_archive(api):
    """A flawless QUOTED licence whose holder has since been suspended."""
    production = create_production_in_clearance(api, title="Suspended Vault",
                                                delivery_deadline_date="2027-10-31")
    archive, card = create_archive_with_rate_card(api)
    asset, candidate = create_asset_with_selected_source(
        api, production["id"], archive["id"], title="Dockside crane")
    license_row = create_license(api, production["id"], asset["id"], archive["id"])
    quote_license(api, license_row["id"], archive["id"], ALL_MEDIA_FEE_CENTS)
    suspend_archive(api, archive["id"])
    return {
        "production": production,
        "archive": archive,
        "rate_card": card,
        "asset": asset,
        "source_candidate": candidate,
        "license": license_row,
    }


def _setup_cleared_to_bind_with_validated_package(api):
    """A VALIDATED package alongside an E&O application one flip short of BOUND."""
    scenario = setup_pinned_chart_production(api)
    application = open_eo_application(api, scenario["production"]["id"],
                                      scenario["chart"]["id"])
    submit_eo_application(api, application["id"])
    scenario["eo_application"] = record_both_eo_reviews(api, application["id"])
    package = open_delivery_package(api, scenario["production"]["id"],
                                    scenario["chart"]["id"])
    scenario["delivery_package"] = validate_delivery_package(api, package["id"])
    return scenario


def test_execution_refused_while_the_holder_archive_is_suspended(api):
    """PRD §3.2: "What suspension blocks is new commitment — a new licence against the
    holder, an execution against the holder, and the publication of a new rate card for
    the holder are each refused with `ERR_ARCHIVE_SUSPENDED`." PRD §3.4 pins the same
    gate on execution: "the holder's archive must be `ACTIVE`, so a licence cannot be
    executed against a suspended holder (`ERR_ARCHIVE_SUSPENDED`)".

    Design: Difficulty/cross_entity_state_dependency/archive_suspension_blocks_execution_of_an_otherwise_valid_quoted_license
    """
    scenario = _setup_quoted_license_against_suspended_archive(api)
    license_id = scenario["license"]["id"]

    archive = validate_success(api.get_archive(scenario["archive"]["id"], CLEARANCE_SUPERVISOR))
    assert archive["status"] == "SUSPENDED"

    response = api.set_license_state(license_id, state_payload("EXECUTED"),
                                     CLEARANCE_SUPERVISOR)
    validate_error(response, "ERR_ARCHIVE_SUSPENDED")

    refused = get_license(api, license_id)
    assert refused["status"] == "QUOTED"
    assert refused["executed_fee_cents"] is None
    assert refused["current_proposed_fee_cents"] == ALL_MEDIA_FEE_CENTS

    production = get_production(api, scenario["production"]["id"])
    assert production["committed_fee_cents"] == 0
    assert_asset_dimensions(get_asset(api, scenario["asset"]["id"]),
                            licensing_status="IN_NEGOTIATION",
                            rights_basis="UNDETERMINED")
    assert_license_money_ledger(api, production["id"], CLEARANCE_SUPERVISOR)


def test_identical_execution_succeeds_once_the_archive_is_reinstated(api):
    """PRD §3.2: "A `ClearanceSupervisor` moves an archive `ACTIVE → SUSPENDED` — typically
    during a chain-of-title dispute — and back `SUSPENDED → ACTIVE` once the dispute is
    resolved; neither direction has preconditions and each increments the archive's
    `version`." PRD §3.4: "Executing the single `FOOTAGE` leg of an archival-footage asset
    completes its required set and moves the asset `IN_NEGOTIATION → CLEARED`, setting
    `rights_basis` to `LICENSED`, raising `cleared_asset_count` by one and lowering
    `open_asset_count` by one, recomputing the production's posture and flipping every
    `PINNED` chart pinning the asset to `STALE`."

    Design: Difficulty/cross_entity_state_dependency/archive_suspension_blocks_execution_of_an_otherwise_valid_quoted_license
    """
    scenario = _setup_quoted_license_against_suspended_archive(api)
    license_id = scenario["license"]["id"]

    validate_error(
        api.set_license_state(license_id, state_payload("EXECUTED"), CLEARANCE_SUPERVISOR),
        "ERR_ARCHIVE_SUSPENDED")

    reinstated = reinstate_archive(api, scenario["archive"]["id"])
    assert reinstated["status"] == "ACTIVE"

    executed = validate_success(
        api.set_license_state(license_id, state_payload("EXECUTED"), CLEARANCE_SUPERVISOR))
    assert executed["status"] == "EXECUTED"
    assert executed["executed_fee_cents"] == ALL_MEDIA_FEE_CENTS

    production = get_production(api, scenario["production"]["id"])
    assert production["committed_fee_cents"] == ALL_MEDIA_FEE_CENTS
    assert_production_counters(production, asset_count=1, cleared_asset_count=1,
                               open_asset_count=0)
    assert_asset_dimensions(get_asset(api, scenario["asset"]["id"]),
                            licensing_status="CLEARED",
                            rights_basis="LICENSED")
    assert_license_money_ledger(api, production["id"], CLEARANCE_SUPERVISOR)


def test_rate_card_publication_refused_while_the_archive_is_suspended(api):
    """PRD §2.12 rung 16: "The referenced archive's `status` is `ACTIVE` — otherwise
    `ERR_ARCHIVE_SUSPENDED`. A suspended holder may not receive a new licence, may not be
    executed against, and may not have a new rate card issued. Applies to licence
    creation, licence status changes to `QUOTED` or `EXECUTED`, and rate-card
    publication."

    Design: Difficulty/cross_entity_state_dependency/archive_suspension_blocks_execution_of_an_otherwise_valid_quoted_license
    """
    scenario = _setup_quoted_license_against_suspended_archive(api)
    archive_id = scenario["archive"]["id"]

    response = api.create_rate_card(
        archive_id, create_rate_card_payload(effective_from_date="2026-07-01"),
        ARCHIVE_RESEARCHER)
    validate_error(response, "ERR_ARCHIVE_SUSPENDED")

    cards, meta = validate_paginated(
        api.list_archive_rate_cards(archive_id, ARCHIVE_RESEARCHER, params={"limit": 100}))
    assert meta["total_count"] == 1
    assert cards[0]["id"] == scenario["rate_card"]["id"]
    assert cards[0]["status"] == "ACTIVE"


def test_delivery_refused_while_the_eo_application_is_only_cleared_to_bind(api):
    """PRD §3.8: "and it requires the production to hold an E&O application in `BOUND`,
    refusing an uninsured delivery with `ERR_EO_NOT_BOUND`."

    Design: Difficulty/cross_entity_state_dependency/unbound_eo_application_blocks_delivery_of_a_fully_validated_package
    """
    scenario = _setup_cleared_to_bind_with_validated_package(api)
    application = scenario["eo_application"]
    package = scenario["delivery_package"]

    assert application["status"] == "CLEARED_TO_BIND"
    assert application["legal_review_status"] == "PASSED"
    assert application["underwriting_review_status"] == "PASSED"
    assert application["premium_cents"] == EXPECTED_PREMIUM_CENTS

    production = get_production(api, scenario["production"]["id"])
    assert_posture(production, "OPEN")
    assert package["status"] == "VALIDATED"
    version_before = package["version"]

    response = api.set_delivery_package_state(package["id"], state_payload("DELIVERED"),
                                              CLEARANCE_SUPERVISOR)
    validate_error(response, "ERR_EO_NOT_BOUND")

    refused = get_delivery_package(api, package["id"])
    assert refused["status"] == "VALIDATED"
    assert refused["version"] == version_before


def test_delivery_succeeds_once_the_eo_application_is_bound(api):
    """PRD §2.12 rung 28: "The production has an E&O application in `BOUND` — otherwise
    `ERR_EO_NOT_BOUND`. Applies to moving a delivery package to `DELIVERED`."

    Design: Difficulty/cross_entity_state_dependency/unbound_eo_application_blocks_delivery_of_a_fully_validated_package
    """
    scenario = _setup_cleared_to_bind_with_validated_package(api)
    application_id = scenario["eo_application"]["id"]
    package_id = scenario["delivery_package"]["id"]

    validate_error(
        api.set_delivery_package_state(package_id, state_payload("DELIVERED"),
                                       CLEARANCE_SUPERVISOR),
        "ERR_EO_NOT_BOUND")

    bound = validate_success(
        api.set_eo_application_state(application_id,
                                     state_payload("BOUND", policy_number="EO-2026-55"),
                                     PRODUCTION_ADMIN))
    assert bound["status"] == "BOUND"
    assert bound["policy_number"] == "EO-2026-55"
    assert bound["premium_cents"] == EXPECTED_PREMIUM_CENTS

    delivered = validate_success(
        api.set_delivery_package_state(package_id, state_payload("DELIVERED"),
                                       CLEARANCE_SUPERVISOR))
    assert delivered["status"] == "DELIVERED"
    assert get_delivery_package(api, package_id)["status"] == "DELIVERED"
    assert_posture(get_production(api, scenario["production"]["id"]), "OPEN")
