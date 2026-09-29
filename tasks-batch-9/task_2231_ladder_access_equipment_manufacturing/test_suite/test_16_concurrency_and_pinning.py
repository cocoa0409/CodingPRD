"""Optimistic-concurrency guards, version accounting, rate-threshold escalation,
revision pinning, and the immediacy of a cascade's effects."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant_equals,
    approve_mandated_documents,
    create_corrective_action_payload,
    create_design_revision_payload,
    create_draft_revision,
    create_listing_body,
    create_product,
    create_submitted_revision,
    create_test_bench,
    file_listing_record,
    freeze_design_payload,
    get_incident_data,
    get_lot_data,
    get_product_data,
    get_registration_data,
    get_revision_data,
    make_certification_body_headers,
    open_lot,
    plan_audit_campaign,
    quarantine_payload,
    review_design_revision_payload,
    run_audit_campaign,
    run_campaign_to_passed,
    setup_frozen_product,
    setup_incident_root_cause,
    setup_released_lot,
    setup_shipping_product_with_registered_units,
    start_lot_production,
    submit_revision,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS
from test_helpers.test_users import DESIGN_ENGINEER_USER_ID

ENGINEER = TEST_USERS["design_engineer_headers"]
APPROVER = TEST_USERS["design_approver_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
SUPERVISOR = TEST_USERS["production_supervisor_headers"]

FIBERGLASS = {"material": "FIBERGLASS_PULTRUSION"}


def test_a_stale_expected_product_version_blocks_the_revision_create():
    """PRD §2.8: "Creating a design revision requires `expected_product_version`
    in the request body, carrying the `version` of the parent product as the client
    last observed it. If that value does not equal the product's current `version`,
    the create is rejected with `ERR_STALE_PRODUCT_VERSION` and HTTP 412."
    PRD §2.8: "A successful create increments the product's `version` by one."

    Design: Corner/complexity_layers/stale_product_version_on_design_revision_create_rejected
    """
    product = create_product()
    observed_version = product["version"]
    # Another engineer legitimately adds a revision, which moves the product on.
    create_draft_revision(product["id"])
    assert get_product_data(product["id"])["version"] == observed_version + 1

    stale = api_client.create_design_revision(
        create_design_revision_payload(product["id"], observed_version), ENGINEER
    )
    validate_error(stale, ApiErrorId.ERR_STALE_PRODUCT_VERSION.value, 412)

    refreshed = get_product_data(product["id"])["version"]
    accepted = validate_success(
        api_client.create_design_revision(
            create_design_revision_payload(product["id"], refreshed), ENGINEER
        ),
        201,
    )

    assert accepted["status"] == "DRAFT"
    assert accepted["product_id"] == product["id"]
    assert get_product_data(product["id"])["version"] == refreshed + 1, (
        "only the accepted create moved the parent version"
    )

    _, meta = validate_paginated(
        api_client.list_design_revisions(ENGINEER, {"product_id": product["id"]})
    )
    assert meta["total_count"] == 2, "the rejected create left no row behind"


def test_a_stale_expected_incident_version_blocks_the_corrective_action_create():
    """PRD §2.8: "Creating a corrective action requires
    `expected_field_incident_version` in the request body, carrying the `version` of
    the parent field incident as the client last observed it. If that value does not
    equal the incident's current `version`, the create is rejected with
    `ERR_STALE_INCIDENT_VERSION` and HTTP 412."
    PRD §2.8: "A successful create increments the incident's `version` by one."

    Design: Corner/complexity_layers/stale_incident_version_on_corrective_action_create_rejected
    """
    product = create_product()
    incident = setup_incident_root_cause(
        product["id"],
        "HINGE_STOP_GEOMETRY",
        incident_type="HINGE_FAILURE",
        injury_severity="MINOR",
    )
    assert incident["status"] == "ROOT_CAUSE_IDENTIFIED"
    assert incident["requires_capa"] is True
    live_version = incident["version"]
    assert live_version >= 2, "reporting and investigating already moved the version"

    stale = api_client.create_corrective_action(
        create_corrective_action_payload(incident["id"], live_version - 1), ENGINEER
    )
    validate_error(stale, ApiErrorId.ERR_STALE_INCIDENT_VERSION.value, 412)
    assert get_incident_data(incident["id"])["status"] == "ROOT_CAUSE_IDENTIFIED"

    action = validate_success(
        api_client.create_corrective_action(
            create_corrective_action_payload(incident["id"], live_version), ENGINEER
        ),
        201,
    )

    assert action["status"] == "OPEN"
    assert action["authored_by_user_id"] == DESIGN_ENGINEER_USER_ID
    reread = get_incident_data(incident["id"])
    assert reread["status"] == "CAPA_OPENED"
    assert reread["version"] == live_version + 1
    # MINOR weight 4 times HINGE_FAILURE weight 2.0, still at full weight because
    # no corrective action has been verified.
    assert float(reread["incident_points"]) == 8.00
    assert float(get_product_data(product["id"])["risk_score_gross"]) == 8.00


def test_the_model_version_advances_once_per_write_that_touches_it():
    """PRD §2.2: "Most resources additionally carry `updated_at`, an ISO 8601 UTC
    timestamp refreshed on every mutation, and `version`, an integer that increments
    by one on every mutation"
    PRD §3.7: "On success `design_status` moves `DRAFT` → `DESIGN_FROZEN`,
    `design_frozen_at` is stamped with the logical clock, `frozen_revision_id` is
    recorded, the model's `version` increments"
    PRD §3.7: "Releasing a model to the retail channel belongs to a
    `ComplianceOfficer` and moves `market_status` `NOT_RELEASED` →
    `RETAIL_RELEASED`, stamping `market_status_changed_at` with the logical clock and
    incrementing the model's `version`."

    Design: Corner/complexity_layers/product_version_increments_on_every_write
    """
    product = create_product(**FIBERGLASS)
    version_at_create = product["version"]

    revision = create_draft_revision(product["id"])
    assert get_product_data(product["id"])["version"] == version_at_create + 1
    revision = submit_revision(revision["id"])
    revision = validate_success(
        api_client.review_design_revision(
            revision["id"], review_design_revision_payload("APPROVE"), APPROVER
        )
    )
    bench = create_test_bench()
    run_campaign_to_passed(
        get_product_data(product["id"]),
        revision["id"],
        "DESIGN_QUALIFICATION",
        bench["id"],
    )

    version_before_freeze = get_product_data(product["id"])["version"]
    frozen = validate_success(
        api_client.freeze_design(
            product["id"], freeze_design_payload(revision["id"]), APPROVER
        )
    )
    assert frozen["version"] == version_before_freeze + 1

    body = create_listing_body()
    record = file_listing_record(product["id"], body["id"])
    run_campaign_to_passed(
        get_product_data(product["id"]),
        revision["id"],
        "CERTIFICATION_LISTING",
        bench["id"],
    )
    record = validate_success(
        api_client.grant_listing(
            record["id"], make_certification_body_headers(body["id"])
        )
    )
    assert record["status"] == "LISTED"
    approve_mandated_documents(product["id"])

    version_before_retail = get_product_data(product["id"])["version"]
    released = validate_success(api_client.release_to_retail(product["id"], OFFICER))

    assert released["version"] == version_before_retail + 1
    assert released["design_status"] == "DESIGN_FROZEN"
    assert released["market_status"] == "RETAIL_RELEASED"


def test_a_forty_percent_prior_failure_rate_lands_on_the_second_tier():
    """PRD §3.5: "Otherwise it is `TIER_1` when `prior_failure_rate_pct` is 20.00
    or less, `TIER_2` when it is 40.00 or less, and `TIER_3` above that."
    PRD §3.5: "Otherwise it is the prior campaign's `failed_test_count` divided by
    the prior campaign's `audit_sample_size`, expressed as a percentage, rounded half
    up to two decimal places."
    PRD §3.5: "it is the base audit sample of 5 units plus the tier adder —
    nothing for `TIER_0`, three more units for `TIER_1`, eight more for `TIER_2`, and
    fifteen more for `TIER_3`."

    Design: Corner/complexity_layers/audit_escalation_reaches_tier_two_at_forty_percent_prior_rate
    """
    ctx, lot = setup_released_lot(produced_units=400)

    prior = run_audit_campaign(
        ctx, lot["id"], "2026-08-05T00:00:00Z", "2026-08-09T00:00:00Z", failing_tests=2
    )
    assert prior["status"] == "FAILED"
    assert prior["audit_sample_size"] == 5
    assert prior["failed_test_count"] == 2

    planned = plan_audit_campaign(
        ctx, lot["id"], "2026-08-11T00:00:00Z", "2026-08-15T00:00:00Z"
    )

    assert planned["status"] == "PLANNED"
    # Two failures out of a five-unit sample, on the upper edge of TIER_2.
    assert float(planned["prior_failure_rate_pct"]) == 40.00
    assert planned["escalation_tier"] == "TIER_2"
    assert planned["audit_sample_size"] == 13, (
        "a TIER_1 reading would give 8 and a TIER_3 reading 20"
    )


def test_approving_a_later_revision_leaves_the_frozen_pin_alone():
    """PRD §3.2: "Approval also carries one cascade: if this revision names a
    `supersedes_revision_id` and the revision so named is itself in `APPROVED`, that
    older revision moves `APPROVED` → `SUPERSEDED` and its `superseded_at` is stamped
    with the logical clock."
    PRD §3.6: "A `ProductionSupervisor` opens a **production lot** with a payload
    naming the `product_id` being built, the `design_revision_id` pinned to the lot at
    creation, a globally unique `lot_code` for traceability, and a `planned_units`
    count greater than zero."

    Design: Corner/complexity_layers/frozen_revision_pinning_survives_a_later_approval
    """
    ctx = setup_frozen_product(**FIBERGLASS)
    first = ctx["revision"]
    lot = open_lot(ctx["product"], first["id"])
    lot = start_lot_production(lot["id"], 400)
    assert lot["design_revision_id"] == first["id"]

    second = create_submitted_revision(ctx["product"]["id"])
    approved = validate_success(
        api_client.review_design_revision(
            second["id"], review_design_revision_payload("APPROVE"), APPROVER
        )
    )

    assert approved["status"] == "APPROVED"
    assert approved["supersedes_revision_id"] is None

    older = get_revision_data(first["id"])
    assert older["status"] == "APPROVED", "no supersede target was named"
    assert older["superseded_at"] is None

    product = get_product_data(ctx["product"]["id"])
    assert product["frozen_revision_id"] == first["id"]
    assert product["design_status"] == "DESIGN_FROZEN"

    reread_lot = get_lot_data(lot["id"])
    assert reread_lot["design_revision_id"] == first["id"]
    assert reread_lot["status"] == "IN_PROCESS"


def test_the_quarantine_cascade_is_already_visible_in_the_same_response():
    """PRD §3.6: "**Hop one:** every consumer registration whose
    `production_lot_id` is this lot and whose `registration_status` is `REGISTERED` or
    `NOTIFIED` has `hold_flag` set to true."
    PRD §3.6: "**Hop two,** caused by hop one: because registrations were flagged,
    the model's `held_registration_count` is recomputed as the number of its
    registrations with `hold_flag` true, and when that count becomes greater than 0
    while the model's `market_status` is `RETAIL_RELEASED`, the model moves
    `RETAIL_RELEASED` → `STOP_SHIP` with `stop_ship_reason_code` set to
    `LOT_QUARANTINE`."
    PRD §2.4: "The clock starts at `2026-08-01T00:00:00Z` when the process starts,
    never advances on its own"

    Design: Corner/consistency_model/quarantine_cascade_is_visible_in_the_same_response_and_immediate_reads
    """
    ctx = setup_shipping_product_with_registered_units(
        registration_count=1, produced_units=400
    )
    registration = ctx["registrations"][0]
    assert ctx["product"]["market_status"] == "RETAIL_RELEASED"
    assert registration["registration_status"] == "REGISTERED"
    assert registration["hold_flag"] is False

    quarantined = validate_success(
        api_client.quarantine_production_lot(
            ctx["lot"]["id"], quarantine_payload("JOINT_INTEGRITY"), SUPERVISOR
        )
    )

    assert quarantined["status"] == "QUARANTINED"
    assert quarantined["units_quarantined"] == 400
    assert quarantined["units_released"] == 0
    assert quarantined["quarantine_reason_code"] == "JOINT_INTEGRITY"

    product = get_product_data(ctx["product"]["id"])
    assert product["market_status"] == "STOP_SHIP"
    assert product["stop_ship_reason_code"] == "LOT_QUARANTINE"
    assert product["held_registration_count"] == 1
    assert product["design_status"] == "DESIGN_FROZEN"

    reread_registration = get_registration_data(registration["id"])
    assert reread_registration["hold_flag"] is True
    assert reread_registration["registration_status"] == "REGISTERED"

    assert_instant_equals(
        quarantined["updated_at"], "2026-08-01T00:00:00Z", "lot updated_at"
    )
    assert_instant_equals(
        product["market_status_changed_at"],
        "2026-08-01T00:00:00Z",
        "market_status_changed_at",
    )
