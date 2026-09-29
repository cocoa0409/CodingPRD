"""Lifecycle machines: initial states, undefined triggers, terminal lockdown,
cyclic retries, the closing rollup and the cascades that fire across rows.
"""
from test_helpers import (
    ADMIN,
    COMPLIANCE,
    CUSTOMER,
    DOCS,
    SAFETY,
    TECHNICIAN_USER_ID,
    api_client,
    assertions,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_success,
)


def _read_revision(revision_id, headers=DOCS):
    return get_success_data(api_client.get_manual_revision(revision_id, headers))


def _read_certification(certification_id):
    return get_success_data(api_client.get_training_certification(certification_id, ADMIN))


# --------------------------------------------------------------------------- #
# Publishing a part is what drags the model's documentation posture
# --------------------------------------------------------------------------- #
def test_publishing_a_second_part_leaves_the_current_guide_with_a_coverage_gap():
    """PRD §3.3: "Publication then reaches outward: for every product model that holds
    an in-window compatibility row for this part, the model's `documentation_posture`
    is re-derived, and a model whose published disassembly guide does not list this
    part's `sku` flips from `CURRENT` to `STALE`."
    PRD §3.4: "The gap is the required SKUs that do not appear in the published guide's
    `covered_part_skus`, and the size of that gap is written to the guide's
    `coverage_gap_sku_count`. When the gap is non-empty the posture is `STALE`."

    Design: Corner/state_machines/publishing_a_second_part_flips_the_model_documentation_posture_to_stale
    """
    setup = fixtures.build_orderable_setup(
        region_overrides={"region_code": "US-CA"},
        model_overrides={
            "model_code": "CRX-S200",
            "product_family": "CRX",
            "market_release_date": "2024-01-01T00:00:00Z",
            "repairability_tier": "TIER_A_SELF_SERVICE",
        },
        part_overrides={"sku": "SKU-S200-FAN", "list_price_cents": 1000},
        compatibility_overrides={
            "effective_from": "2024-02-01T00:00:00Z",
            "install_minutes": 20,
        },
    )
    assert setup["model"]["documentation_posture"] == "CURRENT", (
        f"Expected the guide to cover the only published part, got "
        f"{setup['model']['documentation_posture']}"
    )

    second = fixtures.create_part(sku="SKU-S200-CELL", list_price_cents=2500)
    fixtures.create_compatibility(
        second["id"],
        setup["model"]["id"],
        effective_from="2024-02-01T00:00:00Z",
        install_minutes=30,
    )
    assert fixtures.read_model(setup["model"]["id"])["documentation_posture"] == "CURRENT", (
        "a draft part is outside the required-SKU set, so registering its fitment "
        "must not move the posture"
    )

    response = api_client.publish_part_catalog_item(second["id"], ADMIN)
    published = validate_success(response, 200)
    assert published["status"] == "PUBLISHED", published["status"]

    model = fixtures.read_model(setup["model"]["id"])
    assert model["documentation_posture"] == "STALE", (
        f"the newly published SKU is undocumented, got {model['documentation_posture']}"
    )
    assert model["published_disassembly_revision_number"] == 1, (
        f"the guide itself never moved, got "
        f"{model['published_disassembly_revision_number']}"
    )

    guide = _read_revision(setup["guide"]["id"])
    assert guide["coverage_gap_sku_count"] == 1, (
        f"Expected exactly the one undocumented SKU in the gap, got "
        f"{guide['coverage_gap_sku_count']}"
    )
    assert guide["status"] == "PUBLISHED", (
        f"the gap does not unpublish the guide, got {guide['status']}"
    )


# --------------------------------------------------------------------------- #
# The catalog publication and restriction transitions
# --------------------------------------------------------------------------- #
def test_rental_kit_cannot_be_published_without_a_pool_size():
    """PRD §3.3: "A rental kit additionally requires a `concurrent_rental_capacity`
    that is not null and is at least 1, otherwise the publication is refused with
    `ERR_INVALID_RANGE`; a part whose `core_return_required` is true additionally
    requires a `core_credit_cents` of at least 1, likewise refused with
    `ERR_INVALID_RANGE`."
    PRD §3.3: "`concurrent_rental_capacity` is the number of kits in the rental pool
    and defaults to null, which is what non-rental classes carry."

    Design: Corner/state_machines/rental_kit_publish_without_a_capacity_is_rejected
    """
    kit = fixtures.create_part(
        sku="SKU-S201-KIT",
        part_class="RENTAL_KIT",
        list_price_cents=0,
        rental_deposit_cents=3500,
    )
    assert kit["concurrent_rental_capacity"] is None, (
        f"the pool size was deliberately omitted, got "
        f"{kit['concurrent_rental_capacity']}"
    )

    response = api_client.publish_part_catalog_item(kit["id"], ADMIN)
    validate_error(response, "ERR_INVALID_RANGE", 422)

    stored = fixtures.read_part(kit["id"])
    assert stored["status"] == "DRAFT", (
        f"the guard sits on the transition, so the row stays in DRAFT, got "
        f"{stored['status']}"
    )
    assert stored["version"] == 1, (
        f"a refused publication increments nothing, got {stored['version']}"
    )


def test_publishing_an_already_published_part_is_an_undefined_trigger():
    """PRD §3.3: "Publication makes a part orderable and brings it inside documentation
    coverage checks. It requires the part to be in `DRAFT`."
    PRD §2.9: "The generic undefined-trigger refusal in band 7 covers any action that
    the entity's current state does not define, including repeating an action that has
    already been consumed and any action attempted out of a terminal state."

    Design: Corner/state_machines/second_publish_of_the_same_part_is_rejected
    """
    part = fixtures.create_part(sku="SKU-S202-BRD", list_price_cents=1800)
    published = fixtures.publish_part(part["id"])
    version_after_publish = published["version"]

    response = api_client.publish_part_catalog_item(part["id"], ADMIN)
    validate_error(response, "ERR_INVALID_STATE_TRANSITION", 409)

    stored = fixtures.read_part(part["id"])
    assert stored["status"] == "PUBLISHED", stored["status"]
    assert stored["version"] == version_after_publish, (
        f"Expected the version frozen at {version_after_publish} by the refusal, got "
        f"{stored['version']}"
    )


def test_restricting_a_draft_part_is_refused_and_fires_no_cascade_hop():
    """PRD §3.3: "It moves a part from `PUBLISHED` to the terminal `RESTRICTED`, taking
    a replacement `safety_class` — which must be something other than `UNRESTRICTED` —
    and a `restriction_reason`."
    PRD §3.3: "The second hop, caused by the first, finds every compatibility row for
    this part whose `self_service_eligible` was true, forces that flag to false, and
    raises `superseded_by_safety_restriction` to true on those rows."

    Design: Corner/state_machines/restrict_on_a_draft_part_is_rejected
    """
    fixtures.create_region(region_code="US-CA")
    model = fixtures.create_model(
        model_code="CRX-S203",
        product_family="CRX",
        market_release_date="2024-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )
    part = fixtures.create_part(sku="SKU-S203-HV", list_price_cents=4000)
    compatibility = fixtures.create_compatibility(
        part["id"],
        model["id"],
        effective_from="2024-02-01T00:00:00Z",
        self_service_eligible=True,
        install_minutes=40,
    )

    response = api_client.restrict_part_catalog_item(
        part["id"],
        factories.restriction_payload(
            safety_class="SAFETY_RESTRICTED_HIGH_VOLTAGE",
            restriction_reason="premature",
        ),
        SAFETY,
    )
    validate_error(response, "ERR_INVALID_STATE_TRANSITION", 409)

    stored = fixtures.read_part(part["id"])
    assert stored["status"] == "DRAFT", (
        f"RESTRICTED is only reachable from PUBLISHED, got {stored['status']}"
    )
    assert stored["safety_class"] == "UNRESTRICTED", (
        f"the refused call must not overwrite the safety class, got "
        f"{stored['safety_class']}"
    )
    assert stored["restriction_reason"] is None, (
        f"no reason is stored by a refused restriction, got "
        f"{stored['restriction_reason']}"
    )

    row = get_success_data(
        api_client.get_part_compatibility(compatibility["id"], ADMIN)
    )
    assert row["self_service_eligible"] is True, (
        f"hop two must not fire, got {row['self_service_eligible']}"
    )
    assert row["superseded_by_safety_restriction"] is False, (
        f"hop two must not fire, got {row['superseded_by_safety_restriction']}"
    )


# --------------------------------------------------------------------------- #
# The initial state of a manual revision, and per-pair numbering
# --------------------------------------------------------------------------- #
def test_first_revision_for_a_model_and_doc_type_opens_as_draft_number_one():
    """PRD §3.4: "The server assigns `revision_number` itself, as one more than the
    highest existing revision number for the same model and document type, starting
    at 1."
    PRD §3.4: "The new row begins in `DRAFT` with `authored_by_user_id` taken from the
    caller's `X-User-ID`, `reviewed_by_user_id` null, `rejection_cycle_count` at zero,
    `effective_from` and `published_at` null, and `coverage_gap_sku_count` computed
    against the model's current required-SKU set."

    Design: Corner/state_machines/new_manual_revision_starts_in_draft_at_revision_number_one
    """
    model = fixtures.create_model(
        model_code="CRX-S204",
        product_family="CRX",
        market_release_date="2024-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )
    version_before = fixtures.model_version(model["id"])

    first = fixtures.create_draft_revision(
        model["id"],
        DOCS,
        doc_type="DISASSEMBLY_GUIDE",
        covered_part_skus=["SKU-S204-FAN"],
        safety_warning_count=3,
    )
    assert first["revision_number"] == 1, (
        f"the first revision of a pair is number 1, got {first['revision_number']}"
    )
    assert first["status"] == "DRAFT", first["status"]
    assert first["authored_by_user_id"] == "user_docs_001", (
        f"Expected the caller identity as author, got {first['authored_by_user_id']}"
    )
    assert first["reviewed_by_user_id"] is None, (
        f"no reviewer has seen it yet, got {first['reviewed_by_user_id']}"
    )
    assert first["rejection_cycle_count"] == 0, first["rejection_cycle_count"]
    assert first["published_at"] is None, first["published_at"]
    assert first["effective_from"] is None, first["effective_from"]

    version_after = fixtures.model_version(model["id"])
    assert version_after != version_before, (
        "the first create touched the parent model, which is why the second create "
        f"has to re-read the guard; got {version_before} then {version_after}"
    )

    second = fixtures.create_draft_revision(
        model["id"],
        DOCS,
        doc_type="DISASSEMBLY_GUIDE",
        covered_part_skus=["SKU-S204-FAN"],
        safety_warning_count=4,
    )
    assert second["revision_number"] == 2, (
        f"numbering runs per model and document type, got "
        f"{second['revision_number']}"
    )


# --------------------------------------------------------------------------- #
# Provider authorization: a terminal revocation and its credit sweep
# --------------------------------------------------------------------------- #
def _authorized_provider_with_six_granted_credits():
    """A provider holding one active certification, authorized, balance four of six."""
    fixtures.create_region(region_code="US-CA")
    provider = fixtures.create_provider(
        "US-CA",
        ADMIN,
        legal_name="Sunrise Device Repair",
        requested_access_tier="TIER_2_SAFETY",
        technician_count=4,
    )
    fixtures.begin_training(provider["id"], 6, ADMIN)
    certification = fixtures.file_certification(
        provider["id"],
        TECHNICIAN_USER_ID,
        ADMIN,
        valid_from="2026-07-01T00:00:00Z",
        valid_until="2027-07-01T00:00:00Z",
        exam_score=92,
    )
    fixtures.decide_authorization(
        provider["id"],
        "AUTHORIZE",
        ADMIN,
        decision_reason="coverage met",
        granted_access_tier="TIER_2_SAFETY",
    )
    return {"provider": provider, "certification": certification}


def test_revoking_a_provider_sweeps_the_whole_remaining_balance_into_forfeited():
    """PRD §3.8: "Revoking is a `ComplianceOfficer` decision available from any state
    other than `REVOKED`; it is terminal, it sets `parts_access_tier` to null, and it
    sweeps the whole of `training_credit_balance` into `training_credit_forfeited_total`,
    leaving the balance at zero."
    PRD §2.10: "For every `RepairProvider`, the sum of `training_credit_balance`, the
    `credits_consumed` totals of that provider's certifications whose `status` is
    `ACTIVE` or `EXPIRED`, and `training_credit_forfeited_total` must equal
    `training_credit_granted_total` at all times."

    Design: Corner/state_machines/revoking_authorization_sweeps_the_training_credit_balance_into_forfeited
    """
    bundle = _authorized_provider_with_six_granted_credits()

    before = fixtures.read_provider(bundle["provider"]["id"])
    assert before["training_credit_granted_total"] == 6, (
        before["training_credit_granted_total"]
    )
    assert before["training_credit_balance"] == 4, (
        f"the one filing consumed two of six, got {before['training_credit_balance']}"
    )

    response = api_client.decide_provider_authorization(
        bundle["provider"]["id"],
        factories.authorization_decision_payload(
            "REVOKE", decision_reason="counterfeit parts sourcing"
        ),
        COMPLIANCE,
    )
    revoked = validate_success(response, 200)

    assert revoked["authorization_status"] == "REVOKED", revoked["authorization_status"]
    assert revoked["training_credit_balance"] == 0, (
        f"the sweep empties the balance, got {revoked['training_credit_balance']}"
    )
    assert revoked["training_credit_forfeited_total"] == 4, (
        f"Expected the whole remaining balance forfeited, got "
        f"{revoked['training_credit_forfeited_total']}"
    )
    assert revoked["parts_access_tier"] is None, (
        f"a revoked provider holds no parts access, got {revoked['parts_access_tier']}"
    )

    certification = _read_certification(bundle["certification"]["id"])
    assert certification["status"] == "ACTIVE", (
        f"the sweep does not void certifications, got {certification['status']}"
    )
    assert certification["credits_consumed"] == 2, certification["credits_consumed"]

    assertions.assert_training_credit_balanced(
        fixtures.read_provider(bundle["provider"]["id"]),
        fixtures.list_provider_certifications(bundle["provider"]["id"]),
    )


def test_a_revoked_provider_cannot_be_reinstated():
    """PRD §3.8: "The authorization lifecycle runs `APPLIED` to `TRAINING_IN_PROGRESS`
    to `AUTHORIZED`, with a cycle through `SUSPENDED` and back to `AUTHORIZED` that may
    repeat any number of times, and a terminal `REVOKED` reachable from any of the four
    earlier states."
    PRD §3.8: "Authorizing moves `TRAINING_IN_PROGRESS` to `AUTHORIZED` and reinstating
    moves `SUSPENDED` back to `AUTHORIZED`; both require `active_cert_count` to be at
    least `required_cert_count`, otherwise the decision is refused with
    `ERR_TRAINING_COVERAGE_INSUFFICIENT`."

    Design: Corner/state_machines/revoked_provider_cannot_be_reinstated
    """
    bundle = _authorized_provider_with_six_granted_credits()
    revoked = fixtures.decide_authorization(
        bundle["provider"]["id"],
        "REVOKE",
        COMPLIANCE,
        decision_reason="counterfeit parts sourcing",
    )
    version_after_revoke = revoked["version"]

    response = api_client.decide_provider_authorization(
        bundle["provider"]["id"],
        factories.authorization_decision_payload(
            "REINSTATE", decision_reason="appeal granted"
        ),
        COMPLIANCE,
    )
    validate_error(response, "ERR_INVALID_STATE_TRANSITION", 409)

    provider = fixtures.read_provider(bundle["provider"]["id"])
    assert provider["authorization_status"] == "REVOKED", (
        f"revocation is terminal, got {provider['authorization_status']}"
    )
    assert provider["version"] == version_after_revoke, (
        f"Expected the version frozen at {version_after_revoke}, got "
        f"{provider['version']}"
    )
    assert provider["training_credit_balance"] == 0, (
        f"the appeal must not restore swept credit, got "
        f"{provider['training_credit_balance']}"
    )
    assert provider["training_credit_forfeited_total"] == 4, (
        provider["training_credit_forfeited_total"]
    )
    assert provider["parts_access_tier"] is None, provider["parts_access_tier"]


# --------------------------------------------------------------------------- #
# Ending support reaches across into the model's rulings
# --------------------------------------------------------------------------- #
def test_ending_support_expires_the_models_valid_rulings():
    """PRD §3.1: "Ending support stores `support_end_date`, closes every obligation
    still in `OPEN`, `AT_RISK`, or `ATTESTED` whose mandated parts deadline already
    lies in the past, expires every eligibility assessment of the model that was still
    `VALID`, and blocks any further manual-revision approval for that model from then
    on."
    PRD §3.6: "The referenced assessment must still be in `VALID` status: an assessment
    that is `EXPIRED`, `REVOKED_BY_SAFETY`, or already `CONSUMED` by another order is
    refused with `ERR_ASSESSMENT_NOT_VALID`, and an assessment whose `decision` is any
    of the blocked values is refused with `ERR_ASSESSMENT_BLOCKED`."

    Design: Corner/state_machines/ending_support_expires_the_models_valid_assessments
    """
    setup = fixtures.build_orderable_setup(
        region_overrides={"region_code": "US-CA"},
        model_overrides={
            "model_code": "CRX-S207",
            "product_family": "CRX",
            "market_release_date": "2020-01-01T00:00:00Z",
            "repairability_tier": "TIER_A_SELF_SERVICE",
            "end_of_production_date": "2024-06-01T00:00:00Z",
        },
        part_overrides={"sku": "SKU-S207-FAN", "list_price_cents": 1500},
        compatibility_overrides={
            "effective_from": "2020-02-01T00:00:00Z",
            "install_minutes": 20,
        },
        safety_warning_count=2,
    )
    assert setup["model"]["support_state"] == "LEGACY_SUPPORT", (
        "an end-of-production date supplied at registration starts the model in "
        f"legacy support, got {setup['model']['support_state']}"
    )
    assessment = fixtures.create_assessment(
        setup["model"]["id"], setup["part"]["id"], "US-CA", CUSTOMER
    )
    assert assessment["status"] == "VALID", assessment["status"]

    response = api_client.end_support(
        setup["model"]["id"],
        factories.end_support_payload(support_end_date="2026-08-01T00:00:00Z"),
        ADMIN,
    )
    model = validate_success(response, 200)
    assert model["support_state"] == "SUPPORT_ENDED", model["support_state"]
    assert model["support_end_date"].startswith("2026-08-01T00:00:00"), (
        f"Expected the submitted end date stored, got {model['support_end_date']}"
    )

    expired = fixtures.read_assessment(assessment["id"])
    assert expired["status"] == "EXPIRED", (
        f"the ruling is expired in the same request, got {expired['status']}"
    )
    assert expired["decision"] == "ELIGIBLE", (
        f"only the status moved, not the ruling itself, got {expired['decision']}"
    )

    refused = api_client.create_parts_order(
        factories.parts_order_payload(assessment["id"], "US-CA"), CUSTOMER
    )
    validate_error(refused, "ERR_ASSESSMENT_NOT_VALID", 409)


# --------------------------------------------------------------------------- #
# The closing rollup and the conservation guard on a second core booking
# --------------------------------------------------------------------------- #
def _delivered_order_owing_a_core():
    """A delivered consumer order for one core-required part worth 900 cents."""
    setup = fixtures.build_orderable_setup(
        region_overrides={"region_code": "US-CA"},
        model_overrides={
            "model_code": "CRX-S208",
            "product_family": "CRX",
            "market_release_date": "2024-01-01T00:00:00Z",
            "repairability_tier": "TIER_A_SELF_SERVICE",
        },
        part_overrides={
            "sku": "SKU-S208-MOD",
            "list_price_cents": 5000,
            "core_return_required": True,
            "core_credit_cents": 900,
        },
        compatibility_overrides={
            "effective_from": "2024-02-01T00:00:00Z",
            "install_minutes": 30,
        },
        safety_warning_count=2,
    )
    bundle = fixtures.build_delivered_order(setup, 1, CUSTOMER)
    bundle["setup"] = setup
    return bundle


def test_a_delivered_order_owing_a_core_closes_only_once_the_core_settles():
    """PRD §3.7: "An order rolls up from `DELIVERED` to the terminal `CLOSED` on its
    own, with no client request, as soon as two conditions hold together: every line
    has `authentication_status` in `NOT_REQUIRED` or `AUTHENTIC` and
    `calibration_status` in `NOT_REQUIRED` or `CALIBRATION_PASSED`, and the core
    dimension sits in `NOT_REQUIRED`, `CORE_CREDIT_ISSUED`, or `CORE_FORFEITED`."
    PRD §3.7: "Otherwise `core_credit_final_cents` is the face value multiplied by the
    condition multiplier and then by the lateness decay, rounded half up to whole
    cents, and the dimension continues from `CORE_RECEIVED` to `CORE_CREDIT_ISSUED`."

    Design: Corner/state_machines/order_reaches_closed_only_once_the_core_dimension_settles
    """
    bundle = _delivered_order_owing_a_core()

    delivered = bundle["order"]
    assert delivered["fulfillment_status"] == "DELIVERED", (
        f"the outstanding core blocks the rollup, got "
        f"{delivered['fulfillment_status']}"
    )
    assert delivered["core_return_status"] == "PENDING_CORE", (
        delivered["core_return_status"]
    )
    assert delivered["core_credit_provisional_cents"] == 900, (
        f"the ungraded face value is held at confirmation, got "
        f"{delivered['core_credit_provisional_cents']}"
    )
    assert delivered["core_return_due_at"].startswith("2026-08-31T00:00:00"), (
        f"Expected confirmation plus thirty days, got {delivered['core_return_due_at']}"
    )

    settled = fixtures.book_core_return(
        bundle["order"]["id"], "2026-08-01T00:00:00Z", "INTACT", ADMIN
    )
    assert settled["core_return_status"] == "CORE_CREDIT_ISSUED", (
        settled["core_return_status"]
    )
    assert settled["fulfillment_status"] == "CLOSED", (
        f"the settled core releases the rollup, got {settled['fulfillment_status']}"
    )
    assert settled["core_days_late"] == 0, (
        f"the core arrived thirty days early, got {settled['core_days_late']}"
    )
    assert settled["core_credit_final_cents"] == 900, (
        f"an intact and punctual core grades at full face value, got "
        f"{settled['core_credit_final_cents']}"
    )

    part = fixtures.read_part(bundle["setup"]["part"]["id"])
    assertions.assert_core_ledger_aggregates(part, 900, 0, 900, 0)


def test_a_second_core_booking_is_refused_by_the_conservation_guard():
    """PRD §2.9: "It has exactly one exemption: a second core-return booking against an
    order whose core dimension has already settled is a *declared but guarded* action,
    so it is not reported as an undefined trigger — it falls all the way through to the
    conservation refusal in band 11."
    PRD §2.10: "Any operation that would drive the outstanding total below zero is
    refused with `ERR_CORE_LEDGER_INVARIANT` (409)."

    Design: Corner/state_machines/second_core_return_filing_is_rejected_by_the_conservation_guard
    """
    bundle = _delivered_order_owing_a_core()
    settled = fixtures.book_core_return(
        bundle["order"]["id"], "2026-08-01T00:00:00Z", "INTACT", ADMIN
    )
    version_after_settlement = settled["version"]

    response = api_client.book_core_return(
        bundle["order"]["id"],
        factories.core_return_payload("2026-08-01T00:00:00Z", "INTACT"),
        ADMIN,
    )
    validate_error(response, "ERR_CORE_LEDGER_INVARIANT", 409)

    order = fixtures.read_order(bundle["order"]["id"])
    assert order["core_return_status"] == "CORE_CREDIT_ISSUED", (
        f"the refusal must not re-open the core dimension, got "
        f"{order['core_return_status']}"
    )
    assert order["version"] == version_after_settlement, (
        f"Expected the version frozen at {version_after_settlement}, got "
        f"{order['version']}"
    )

    part = fixtures.read_part(bundle["setup"]["part"]["id"])
    assert part["core_credit_settled_cents"] == 900, (
        f"the same face value must not settle twice, got "
        f"{part['core_credit_settled_cents']}"
    )
    assertions.assert_core_ledger_aggregates(part, 900, 0, 900, 0)


# --------------------------------------------------------------------------- #
# The two per-line service dimensions
# --------------------------------------------------------------------------- #
def test_a_mismatched_pairing_token_succeeds_and_escalates_the_calibration():
    """PRD §3.7: "Any other token value moves the line to `COUNTERFEIT_SUSPECT`, which
    is terminal for the authentication dimension and, when calibration was required,
    forces the calibration dimension straight to `CALIBRATION_ESCALATED`."
    PRD §3.7: "Every line whose part has `requires_authentication` true moves its
    `authentication_status` from `NOT_REQUIRED` to `PENDING_AUTHENTICATION` and has a
    `pairing_token` minted onto it — the token is readable through the order's line
    listing."

    Design: Corner/state_machines/authenticating_with_a_mismatched_token_marks_the_line_counterfeit_and_escalates_calibration
    """
    setup = fixtures.build_orderable_setup(
        region_overrides={"region_code": "US-CA"},
        model_overrides={
            "model_code": "CRX-S206",
            "product_family": "CRX",
            "market_release_date": "2024-01-01T00:00:00Z",
            "repairability_tier": "TIER_A_SELF_SERVICE",
        },
        part_overrides={
            "sku": "SKU-S206-CAM",
            "list_price_cents": 3000,
            "requires_authentication": True,
            "requires_calibration": True,
        },
        compatibility_overrides={
            "effective_from": "2024-02-01T00:00:00Z",
            "install_minutes": 35,
        },
        safety_warning_count=2,
    )
    bundle = fixtures.build_delivered_order(setup, 1, CUSTOMER)
    line = bundle["lines"][0]

    assert line["authentication_status"] == "PENDING_AUTHENTICATION", (
        line["authentication_status"]
    )
    assert line["calibration_status"] == "CALIBRATION_REQUIRED", (
        line["calibration_status"]
    )
    assert line["pairing_token"], (
        f"delivery mints a readable token, got {line['pairing_token']}"
    )
    assert line["pairing_token"] != "NOT-THE-MINTED-TOKEN", (
        "the token submitted below must genuinely differ from the minted one"
    )

    response = api_client.authenticate_line(
        bundle["order"]["id"],
        line["id"],
        factories.authenticate_payload("NOT-THE-MINTED-TOKEN"),
        CUSTOMER,
    )
    authenticated = validate_success(response, 200)
    assert authenticated["authentication_status"] == "COUNTERFEIT_SUSPECT", (
        f"a mismatch is a punitive success, not an error, got "
        f"{authenticated['authentication_status']}"
    )
    assert authenticated["calibration_status"] == "CALIBRATION_ESCALATED", (
        f"the mismatch drags calibration in the same request, got "
        f"{authenticated['calibration_status']}"
    )

    order = fixtures.read_order(bundle["order"]["id"])
    assert order["fulfillment_status"] == "DELIVERED", (
        f"the rollup to CLOSED is now unreachable through this line, got "
        f"{order['fulfillment_status']}"
    )


def test_calibration_retries_twice_and_escalates_on_the_third_failure():
    """PRD §3.7: "When it exceeds 150 and `calibration_attempt_count` is still below
    three, the dimension continues to `CALIBRATION_FAILED` and the line remains
    retryable. When it exceeds 150 on the attempt that brings
    `calibration_attempt_count` to three, the dimension continues to the terminal
    `CALIBRATION_ESCALATED`, and the parent order can never reach `CLOSED` through that
    line."
    PRD §3.7: "A first attempt moves `calibration_status` from `CALIBRATION_REQUIRED`
    to `CALIBRATION_IN_PROGRESS`; a retry moves it from `CALIBRATION_FAILED` back to
    `CALIBRATION_IN_PROGRESS`."

    Design: Corner/state_machines/calibration_cycles_twice_and_escalates_on_the_third_failure
    """
    setup = fixtures.build_orderable_setup(
        region_overrides={"region_code": "US-CA"},
        model_overrides={
            "model_code": "CRX-S210",
            "product_family": "CRX",
            "market_release_date": "2024-01-01T00:00:00Z",
            "repairability_tier": "TIER_A_SELF_SERVICE",
        },
        part_overrides={
            "sku": "SKU-S210-SENS",
            "list_price_cents": 2200,
            "requires_calibration": True,
        },
        compatibility_overrides={
            "effective_from": "2024-02-01T00:00:00Z",
            "install_minutes": 25,
        },
        safety_warning_count=2,
    )
    fixtures.publish_calibration_procedure(
        setup["model"]["id"], ["SKU-S210-SENS"], safety_warning_count=2
    )
    bundle = fixtures.build_delivered_order(setup, 1, CUSTOMER)
    line = bundle["lines"][0]
    assert line["calibration_status"] == "CALIBRATION_REQUIRED", (
        line["calibration_status"]
    )
    assert line["calibration_attempt_count"] == 0, line["calibration_attempt_count"]

    expected = [
        ("CALIBRATION_FAILED", 1),
        ("CALIBRATION_FAILED", 2),
        ("CALIBRATION_ESCALATED", 3),
    ]
    for expected_status, expected_count in expected:
        response = api_client.calibrate_line(
            bundle["order"]["id"],
            line["id"],
            factories.calibrate_payload(400),
            CUSTOMER,
        )
        attempt = validate_success(response, 200)
        assert attempt["calibration_attempt_count"] == expected_count, (
            f"Expected attempt {expected_count}, got "
            f"{attempt['calibration_attempt_count']}"
        )
        assert attempt["calibration_status"] == expected_status, (
            f"on attempt {expected_count} expected {expected_status}, got "
            f"{attempt['calibration_status']}"
        )

    final = fixtures.list_lines(bundle["order"]["id"])[0]
    assert final["last_measured_offset_ppm"] == 400, (
        f"the stored reading never changed, got {final['last_measured_offset_ppm']}"
    )
    assert final["authentication_status"] == "NOT_REQUIRED", (
        f"this part needs no authentication, got {final['authentication_status']}"
    )

    order = fixtures.read_order(bundle["order"]["id"])
    assert order["fulfillment_status"] == "DELIVERED", (
        f"an escalated line bars the rollup for good, got "
        f"{order['fulfillment_status']}"
    )
