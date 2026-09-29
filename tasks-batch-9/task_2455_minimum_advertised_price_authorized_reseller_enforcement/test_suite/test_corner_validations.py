"""Rejection-order corners, part one: authentication, role, request shape, path
existence, body foreign keys and resource ownership.

Each test drives a request that breaks exactly one rule at the priority under
examination, or breaks two so that the higher-priority code is the one observed.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ANALYST_HEADERS,
    BCM_HEADERS,
    ApiErrorId,
    api_client,
    make_headers,
    make_reseller_headers,
)
from test_helpers.assertions import assert_same_instant, violation_points
from test_helpers.constants import EVIDENCE_HASH_1, EVIDENCE_HASH_3
from test_helpers.factories import (
    agreement_payload,
    bundle_component,
    chargeback_payload,
    notice_payload,
    observation_payload,
    pricing_policy_payload,
    serial_capture_payload,
    ship_downstream_payload,
)
from test_helpers.fixtures import (
    capture_observation,
    capture_purchase_serial,
    confirm_unauthorized,
    create_active_agreement,
    create_detected_violation,
    create_distributor,
    create_product,
    create_published_policy,
    create_reseller,
    create_serial_unit,
    current_distributor_version,
    current_reseller_version,
    evaluate_observation,
    issue_notice,
    order_test_purchase,
    pin_clock,
    read_notice,
    read_reseller,
    read_serial_unit,
    read_test_purchase,
)

CLOCK_AUG_01 = "2026-08-01T00:00:00Z"
CLOCK_AUG_20 = "2026-08-20T00:00:00Z"
OBSERVED_AUG_18 = "2026-08-18T00:00:00Z"
TERM_ENDS = "2027-06-30T00:00:00Z"
SUSPENSION_STARTS = "2026-09-01T00:00:00Z"
SUSPENSION_ENDS_90_DAYS = "2026-11-30T00:00:00Z"
SUSPENSION_ENDS_105_DAYS = "2026-12-15T00:00:00Z"

NO_AUTH_HEADERS = {"Content-Type": "application/json"}
UNDECLARED_ROLE_HEADERS = make_headers("auditor-1", "BrandAuditor")

STANDARD_FLOOR = 15000
UPPERCASE_EVIDENCE_HASH = EVIDENCE_HASH_1.upper()


# --------------------------------------------------------------------------- #
# Shared spine
# --------------------------------------------------------------------------- #
def _published_policy():
    """The published unilateral policy every other row hangs off."""
    pin_clock(CLOCK_AUG_01)
    return create_published_policy(effective_from=CLOCK_AUG_01)


def _headphones(policy_id):
    return create_product(
        policy_id,
        sku="SKU-AUDIO-1",
        name="Studio Headphones",
        msrp_cents=20000,
        standard_map_floor_cents=STANDARD_FLOOR,
    )


def _authorized_acme(policy_id):
    """Acme Retail on the marketplace, authorized with an ACTIVE agreement."""
    reseller = create_reseller(
        legal_name="Acme Retail LLC",
        contact_email="ops@acme.example",
        primary_channel="MARKETPLACE",
    )
    agreement = create_active_agreement(
        reseller["id"],
        policy_id,
        permitted_channels=["MARKETPLACE", "OWN_WEBSITE"],
        quality_obligations=["AUTHENTICITY_LABELING"],
        term_ends_at=TERM_ENDS,
    )
    return reseller, agreement


def _authorized_bravo(policy_id):
    """A second, entirely separate authorized reseller on the retailer channel."""
    reseller = create_reseller(
        legal_name="Bravo Outlets Inc",
        contact_email="ops@bravo.example",
        primary_channel="RETAILER_SITE",
    )
    agreement = create_active_agreement(
        reseller["id"],
        policy_id,
        permitted_channels=["RETAILER_SITE"],
        quality_obligations=["AUTHENTICITY_LABELING"],
        term_ends_at=TERM_ENDS,
    )
    return reseller, agreement


def _warned_acme():
    """Acme carrying an ISSUED WARNING for a 14000 marketplace listing."""
    policy = _published_policy()
    product = _headphones(policy["id"])
    reseller, agreement = _authorized_acme(policy["id"])
    pin_clock(CLOCK_AUG_20)
    violation, observation, _evaluation = create_detected_violation(
        product["id"],
        reseller["id"],
        listed_price_cents=14000,
        channel="MARKETPLACE",
        observed_at=OBSERVED_AUG_18,
        seller_display_name="Acme Store",
        listing_url="https://mkt.example/l/1",
        evidence_hash=EVIDENCE_HASH_1,
    )
    notice = issue_notice(reseller["id"], violation["id"])
    return {
        "policy": policy,
        "product": product,
        "reseller": reseller,
        "agreement": agreement,
        "violation": violation,
        "observation": observation,
        "notice": notice,
    }


def _warned_acme_with_second_breach():
    """Acme warned once, then a 9000 marketplace listing detected but not noticed."""
    world = _warned_acme()
    violation2, _observation2, _evaluation2 = create_detected_violation(
        world["product"]["id"],
        world["reseller"]["id"],
        listed_price_cents=9000,
        channel="MARKETPLACE",
        observed_at=OBSERVED_AUG_18,
        seller_display_name="Acme Store",
        listing_url="https://mkt.example/l/2",
        evidence_hash=EVIDENCE_HASH_3,
    )
    world["violation2"] = violation2
    return world


# --------------------------------------------------------------------------- #
# Priority 1 — authentication
# --------------------------------------------------------------------------- #
def test_a_policy_draft_with_no_authentication_headers_is_unauthenticated():
    """Missing headers are refused before the body is even considered.

    PRD: "If either header is absent, or if `X-User-Role` is not one of the six
    declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/policy_create_without_headers_returns_unauthenticated
    """
    pin_clock(CLOCK_AUG_01)
    validate_error(
        api_client.create_pricing_policy({"policy_code": "MAP-2026-A"}, NO_AUTH_HEADERS),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )

    rows, meta = validate_paginated(api_client.list_pricing_policies(BCM_HEADERS))
    assert meta["total_count"] == 0
    assert rows == []


def test_a_role_string_outside_the_six_declared_roles_is_unauthenticated():
    """An unrecognised role value is an authentication failure, not a 403.

    PRD: "If either header is absent, or if `X-User-Role` is not one of the six
    declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/unknown_role_value_returns_unauthenticated
    """
    pin_clock(CLOCK_AUG_01)
    validate_error(
        api_client.create_pricing_policy(
            {"policy_code": "MAP-2026-A"}, UNDECLARED_ROLE_HEADERS
        ),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )


# --------------------------------------------------------------------------- #
# Priority 2 — role authorization
# --------------------------------------------------------------------------- #
def test_a_monitoring_analyst_may_not_draft_a_pricing_policy():
    """Policy drafting is a channel-manager act only.

    PRD: "If both headers are well formed but the named role does not appear in the
    authorized-role list published for the requested endpoint in §4, the request is
    rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/validations/monitoring_analyst_creating_a_policy_rejected
    """
    pin_clock(CLOCK_AUG_01)
    validate_error(
        api_client.create_pricing_policy({"policy_code": "MAP-2026-A"}, ANALYST_HEADERS),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
    )

    rows, meta = validate_paginated(api_client.list_pricing_policies(BCM_HEADERS))
    assert meta["total_count"] == 0
    assert rows == []


def test_a_forbidden_role_on_an_absent_policy_reports_the_role_failure():
    """The role gate closes before the path lookup can leak existence.

    PRD: "When a single request violates several rules, exactly one error is returned,
    and which one is fully determined."

    Design: Corner/validations/role_check_precedes_path_existence_rejected
    """
    pin_clock(CLOCK_AUG_01)
    validate_error(
        api_client.submit_policy_review(
            NON_EXISTENT_UUID, make_headers("res-ghost", "Reseller")
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
    )


# --------------------------------------------------------------------------- #
# Priority 3 — request shape
# --------------------------------------------------------------------------- #
def test_a_product_without_a_standard_floor_is_a_validation_failure():
    """The standard floor is a required input, not a defaulted one.

    PRD: "Required body fields present, types correct, enum members drawn from the
    declared sets, numeric ranges honoured, `evidence_hash` exactly 64 lowercase
    hexadecimal characters, `permitted_channels` members distinct, `bundle_components`
    well formed whenever `is_bundle` is true, a suspension window no longer than 90
    days, and `diverted_units` at least 1 — else `ERR_VALIDATION` (400)."

    Design: Corner/validations/product_create_missing_standard_floor_rejected
    """
    policy = _published_policy()
    validate_error(
        api_client.create_product(
            {
                "sku": "SKU-AUDIO-1",
                "name": "Studio Headphones",
                "msrp_cents": 20000,
                "governing_policy_id": policy["id"],
            },
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_VALIDATION.value,
    )

    rows, meta = validate_paginated(api_client.list_products(BCM_HEADERS))
    assert meta["total_count"] == 0
    assert rows == []


def test_an_observation_naming_an_undeclared_channel_is_a_validation_failure():
    """Enum membership is settled before any floor is resolved.

    PRD: "Each captured listing names the monitored SKU by `product_id`, the `channel`
    on which it was seen (one of `MARKETPLACE`, `RETAILER_SITE`, `OWN_WEBSITE` or
    `PHYSICAL_RETAIL`), the storefront's `seller_display_name`, the evidence
    `listing_url`, the `listed_price_cents` as displayed (which must be at least 0), the
    `observed_at` instant, and an `evidence_hash` that must be exactly 64 lowercase
    hexadecimal characters — the SHA-256 digest of the captured screenshot."

    Design: Corner/validations/observation_with_unknown_channel_enum_rejected
    """
    policy = _published_policy()
    product = _headphones(policy["id"])
    pin_clock(CLOCK_AUG_20)

    validate_error(
        api_client.create_observation(
            observation_payload(
                product["id"],
                channel="TELEVISION",
                seller_display_name="GreyBox Deals",
                listing_url="https://tv.example/l/1",
                listed_price_cents=14000,
                observed_at=OBSERVED_AUG_18,
                evidence_hash=EVIDENCE_HASH_1,
            ),
            ANALYST_HEADERS,
        ),
        ApiErrorId.ERR_VALIDATION.value,
    )

    rows, meta = validate_paginated(api_client.list_observations(BCM_HEADERS))
    assert meta["total_count"] == 0
    assert rows == []


def test_an_uppercase_evidence_digest_is_a_validation_failure():
    """Case is part of the digest format rule.

    PRD: "Required body fields present, types correct, enum members drawn from the
    declared sets, numeric ranges honoured, `evidence_hash` exactly 64 lowercase
    hexadecimal characters, `permitted_channels` members distinct, `bundle_components`
    well formed whenever `is_bundle` is true, a suspension window no longer than 90
    days, and `diverted_units` at least 1 — else `ERR_VALIDATION` (400)."

    Design: Corner/validations/observation_with_uppercase_evidence_hash_rejected
    """
    policy = _published_policy()
    product = _headphones(policy["id"])
    pin_clock(CLOCK_AUG_20)

    assert len(UPPERCASE_EVIDENCE_HASH) == 64
    validate_error(
        api_client.create_observation(
            observation_payload(
                product["id"],
                channel="MARKETPLACE",
                seller_display_name="GreyBox Deals",
                listing_url="https://mkt.example/l/1",
                listed_price_cents=14000,
                observed_at=OBSERVED_AUG_18,
                evidence_hash=UPPERCASE_EVIDENCE_HASH,
            ),
            ANALYST_HEADERS,
        ),
        ApiErrorId.ERR_VALIDATION.value,
    )


def test_an_agreement_repeating_a_permitted_channel_is_a_validation_failure():
    """The permitted-channel array members must be distinct.

    PRD: "Required body fields present, types correct, enum members drawn from the
    declared sets, numeric ranges honoured, `evidence_hash` exactly 64 lowercase
    hexadecimal characters, `permitted_channels` members distinct, `bundle_components`
    well formed whenever `is_bundle` is true, a suspension window no longer than 90
    days, and `diverted_units` at least 1 — else `ERR_VALIDATION` (400)."

    Design: Corner/validations/agreement_with_repeated_permitted_channel_rejected
    """
    policy = _published_policy()
    reseller = create_reseller(
        legal_name="Acme Retail LLC",
        contact_email="ops@acme.example",
        primary_channel="MARKETPLACE",
    )

    validate_error(
        api_client.create_agreement(
            agreement_payload(
                reseller["id"],
                policy["id"],
                permitted_channels=["MARKETPLACE", "MARKETPLACE"],
                quality_obligations=["AUTHENTICITY_LABELING"],
                term_ends_at=TERM_ENDS,
            ),
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_VALIDATION.value,
    )

    rows, meta = validate_paginated(api_client.list_agreements(BCM_HEADERS))
    assert meta["total_count"] == 0
    assert rows == []


def test_a_bundle_listing_with_a_single_component_is_a_validation_failure():
    """A bundle needs at least two evidenced components before allocation runs.

    PRD: "When `is_bundle` is true — it defaults to false — the capture must also supply
    `bundle_total_price_cents`, the advertised price of the whole bundle, which must be
    strictly greater than zero, and `bundle_components`, an array of at least two
    distinct objects each carrying a `sku` string and an `msrp_cents` integer strictly
    greater than zero."

    Design: Corner/validations/bundle_observation_with_one_component_rejected
    """
    policy = _published_policy()
    product = _headphones(policy["id"])
    pin_clock(CLOCK_AUG_20)

    validate_error(
        api_client.create_observation(
            observation_payload(
                product["id"],
                channel="MARKETPLACE",
                seller_display_name="GreyBox Deals",
                listing_url="https://mkt.example/b/1",
                listed_price_cents=10000,
                observed_at=OBSERVED_AUG_18,
                evidence_hash=EVIDENCE_HASH_1,
                is_bundle=True,
                bundle_total_price_cents=10000,
                bundle_components=[bundle_component("SKU-AUDIO-1", 20000)],
            ),
            ANALYST_HEADERS,
        ),
        ApiErrorId.ERR_VALIDATION.value,
    )


def test_a_policy_asking_for_a_zero_day_cure_window_is_a_validation_failure():
    """An explicit out-of-range figure does not fall back to the default.

    PRD: "`cure_window_days` is the number of days a reseller has to cure a noticed
    violation before it escalates; it must be between 1 and 60 inclusive and defaults to
    10."

    Design: Corner/validations/policy_with_cure_window_zero_rejected
    """
    pin_clock(CLOCK_AUG_01)
    validate_error(
        api_client.create_pricing_policy(
            pricing_policy_payload(policy_code="MAP-2026-A", cure_window_days=0),
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_VALIDATION.value,
    )

    rows, meta = validate_paginated(api_client.list_pricing_policies(BCM_HEADERS))
    assert meta["total_count"] == 0
    assert rows == []


def _confirmed_grey_trace():
    """A confirmed unauthorized trace back to Northwind's own shipping record."""
    policy = _published_policy()
    product = _headphones(policy["id"])
    distributor = create_distributor(
        legal_name="Northwind Distribution", annual_chargeback_cap_cents=500000
    )
    unit = create_serial_unit(
        product["id"], distributor["id"], serial_number="SN-0001", lot_code="LOT-A"
    )
    pin_clock(CLOCK_AUG_20)
    observation = capture_observation(
        product["id"],
        channel="MARKETPLACE",
        seller_display_name="GreyBox Deals",
        listing_url="https://mkt.example/l/9",
        listed_price_cents=9000,
        observed_at=OBSERVED_AUG_18,
        evidence_hash=EVIDENCE_HASH_1,
    )
    evaluate_observation(observation["id"])
    purchase = order_test_purchase(
        observation["id"], ordered_at="2026-08-19T00:00:00Z", purchase_price_cents=9000
    )
    return {
        "product": product,
        "distributor": distributor,
        "unit": unit,
        "observation": observation,
        "purchase": purchase,
    }


def test_a_chargeback_for_zero_diverted_units_is_a_validation_failure():
    """The unit count is bounded at the shape gate, far ahead of the ceiling check.

    PRD: "A `BrandChannelManager` assesses one by naming the accountable
    `distributor_id`, the originating `test_purchase_id`, the number of `diverted_units`
    charged for this event (at least 1), and the `expected_distributor_version` demanded
    by §2.8."

    Design: Corner/validations/chargeback_with_zero_diverted_units_rejected
    """
    world = _confirmed_grey_trace()
    capture_purchase_serial(world["purchase"]["id"], "SN-0001")
    confirm_unauthorized(
        world["purchase"]["id"], outcome_reason="Seller has no agreement on file"
    )

    validate_error(
        api_client.assess_chargeback(
            chargeback_payload(
                world["distributor"]["id"],
                world["purchase"]["id"],
                current_distributor_version(world["distributor"]["id"]),
                diverted_units=0,
            ),
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_VALIDATION.value,
    )

    distributor = validate_success(
        api_client.get_distributor(world["distributor"]["id"], BCM_HEADERS)
    )
    assert distributor["chargeback_balance_cents"] == 0


def test_a_suspension_window_longer_than_ninety_days_is_a_validation_failure():
    """The duration ceiling sits with the shape rules, not the window rules.

    PRD: "The window's duration, measured from `suspension_starts_at` to
    `suspension_ends_at`, may not exceed 90 days."

    Design: Corner/validations/suspension_window_longer_than_ninety_days_rejected
    """
    world = _warned_acme_with_second_breach()
    validate_error(
        api_client.issue_notice(
            notice_payload(
                world["reseller"]["id"],
                world["violation2"]["id"],
                current_reseller_version(world["reseller"]["id"]),
                rung="SUSPENSION",
                suspension_starts_at=SUSPENSION_STARTS,
                suspension_ends_at=SUSPENSION_ENDS_105_DAYS,
            ),
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_VALIDATION.value,
    )

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["authorization_status"] == "AUTHORIZED"


def test_a_suspension_window_of_exactly_ninety_days_issues_cleanly():
    """The ceiling is inclusive, so ninety days is inside the permitted duration.

    PRD: "The window's duration, measured from `suspension_starts_at` to
    `suspension_ends_at`, may not exceed 90 days."

    Design: Corner/validations/suspension_window_of_exactly_ninety_days_is_accepted
    """
    world = _warned_acme_with_second_breach()
    notice = validate_success(
        api_client.issue_notice(
            notice_payload(
                world["reseller"]["id"],
                world["violation2"]["id"],
                current_reseller_version(world["reseller"]["id"]),
                rung="SUSPENSION",
                suspension_starts_at=SUSPENSION_STARTS,
                suspension_ends_at=SUSPENSION_ENDS_90_DAYS,
            ),
            BCM_HEADERS,
        ),
        expected_status=201,
    )

    assert notice["rung"] == "SUSPENSION"
    assert notice["assessed_points"] == violation_points(STANDARD_FLOOR, 9000, "MARKETPLACE", 1) == 11
    assert notice["cumulative_points_at_issue"] == 14
    assert_same_instant(
        notice["suspension_ends_at"], SUSPENSION_ENDS_90_DAYS, "notice suspension_ends_at"
    )

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["authorization_status"] == "SUSPENDED"
    assert_same_instant(
        reseller["suspension_ends_at"], SUSPENSION_ENDS_90_DAYS, "reseller suspension_ends_at"
    )


def test_a_malformed_cure_submission_against_an_absent_violation_reports_the_shape():
    """The body schema is checked before the path identifier is resolved.

    PRD: "When a single request violates several rules, exactly one error is returned,
    and which one is fully determined."

    Design: Corner/validations/schema_check_precedes_path_existence_rejected
    """
    policy = _published_policy()
    _headphones(policy["id"])
    reseller, _agreement = _authorized_acme(policy["id"])

    validate_error(
        api_client.submit_cure(
            NON_EXISTENT_UUID,
            {
                "cure_evidence_url": "https://acme.example/proof/x",
                "corrected_price_cents": 15000,
            },
            make_reseller_headers(reseller["id"]),
        ),
        ApiErrorId.ERR_VALIDATION.value,
    )


# --------------------------------------------------------------------------- #
# Priority 4 — path existence
# --------------------------------------------------------------------------- #
def test_submitting_an_absent_policy_for_review_is_a_policy_not_found():
    """Each missing path resource yields its own not-found code.

    PRD: "The code is the not-found code of the resource type that is missing:
    `ERR_POLICY_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_RESELLER_NOT_FOUND`,
    `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_OBSERVATION_NOT_FOUND`,
    `ERR_VIOLATION_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_EXCEPTION_NOT_FOUND`,
    `ERR_SERIAL_UNIT_NOT_FOUND`, `ERR_TEST_PURCHASE_NOT_FOUND` or
    `ERR_CHARGEBACK_NOT_FOUND`, each HTTP 404."

    Design: Corner/validations/submit_review_on_unknown_policy_returns_not_found
    """
    pin_clock(CLOCK_AUG_01)
    validate_error(
        api_client.submit_policy_review(NON_EXISTENT_UUID, BCM_HEADERS),
        ApiErrorId.ERR_POLICY_NOT_FOUND.value,
    )


def test_acknowledging_an_absent_notice_is_a_notice_not_found():
    """Existence is settled before ownership, so the reseller sees a 404.

    PRD: "The code is the not-found code of the resource type that is missing:
    `ERR_POLICY_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_RESELLER_NOT_FOUND`,
    `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_OBSERVATION_NOT_FOUND`,
    `ERR_VIOLATION_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_EXCEPTION_NOT_FOUND`,
    `ERR_SERIAL_UNIT_NOT_FOUND`, `ERR_TEST_PURCHASE_NOT_FOUND` or
    `ERR_CHARGEBACK_NOT_FOUND`, each HTTP 404."

    Design: Corner/validations/acknowledge_unknown_notice_returns_not_found
    """
    policy = _published_policy()
    reseller, _agreement = _authorized_acme(policy["id"])

    validate_error(
        api_client.acknowledge_notice(
            NON_EXISTENT_UUID, make_reseller_headers(reseller["id"])
        ),
        ApiErrorId.ERR_NOTICE_NOT_FOUND.value,
    )


def test_an_absent_path_unit_outranks_an_absent_body_reseller():
    """Path resolution finishes before the body foreign keys are swept.

    PRD: "Every resource named by a path parameter exists, validated left to right, so
    that on a nested path the leftmost missing resource determines the error."

    Design: Corner/validations/path_existence_precedes_body_fk_existence_rejected
    """
    pin_clock(CLOCK_AUG_01)
    distributor = create_distributor(
        legal_name="Northwind Distribution", annual_chargeback_cap_cents=500000
    )

    validate_error(
        api_client.ship_downstream(
            NON_EXISTENT_UUID,
            ship_downstream_payload("00000000-0000-0000-0000-0000000000ee"),
            make_headers(distributor["id"], "Distributor"),
        ),
        ApiErrorId.ERR_SERIAL_UNIT_NOT_FOUND.value,
    )


# --------------------------------------------------------------------------- #
# Priority 5 — body foreign keys
# --------------------------------------------------------------------------- #
def test_an_observation_for_an_absent_product_is_a_product_not_found():
    """The first unresolved body reference wins, before the matched reseller is read.

    PRD: "Every foreign key supplied in the request body resolves to an existing row,
    validated in the order the fields are listed for that endpoint in §4's companion
    narrative, again yielding the not-found code of the missing type (and
    `ERR_SERIAL_NOT_REGISTERED`, HTTP 404, when a submitted `serial_number` matches no
    registered serialized unit)."

    Design: Corner/validations/observation_for_unknown_product_returns_not_found
    """
    _published_policy()
    pin_clock(CLOCK_AUG_20)

    validate_error(
        api_client.create_observation(
            observation_payload(
                NON_EXISTENT_UUID,
                channel="MARKETPLACE",
                seller_display_name="GreyBox Deals",
                listing_url="https://mkt.example/l/1",
                listed_price_cents=14000,
                observed_at=OBSERVED_AUG_18,
                evidence_hash=EVIDENCE_HASH_1,
                matched_reseller_id="00000000-0000-0000-0000-0000000000ee",
            ),
            ANALYST_HEADERS,
        ),
        ApiErrorId.ERR_PRODUCT_NOT_FOUND.value,
    )


def test_capturing_a_serial_that_was_never_registered_is_a_not_registered_failure():
    """A natural-key reference gets its own not-found code.

    PRD: "A serial that matches no registered unit is rejected with
    `ERR_SERIAL_NOT_REGISTERED`; a serial that resolves to a unit whose custody state is
    neither `SHIPPED_TO_DISTRIBUTOR` nor `SHIPPED_TO_RESELLER` is rejected with
    `ERR_SERIAL_NOT_TRACEABLE`, since a unit already traced or recalled cannot ground a
    fresh trace."

    Design: Corner/validations/serial_capture_of_unregistered_serial_rejected
    """
    world = _confirmed_grey_trace()
    validate_error(
        api_client.capture_serial(
            world["purchase"]["id"], serial_capture_payload("SN-9999"), ANALYST_HEADERS
        ),
        ApiErrorId.ERR_SERIAL_NOT_REGISTERED.value,
    )

    purchase = read_test_purchase(world["purchase"]["id"])
    assert purchase["status"] == "ORDERED"
    assert purchase["traced_serial_unit_id"] is None


def test_notice_body_references_are_resolved_in_their_declared_order():
    """With both references bogus the reseller is the one reported.

    PRD: "Every foreign key supplied in the request body resolves to an existing row,
    validated in the order the fields are listed for that endpoint in §4's companion
    narrative, again yielding the not-found code of the missing type (and
    `ERR_SERIAL_NOT_REGISTERED`, HTTP 404, when a submitted `serial_number` matches no
    registered serialized unit)."

    Design: Corner/validations/notice_body_fks_are_checked_in_input_order_rejected
    """
    policy = _published_policy()
    reseller = create_reseller(
        legal_name="Acme Retail LLC",
        contact_email="ops@acme.example",
        primary_channel="MARKETPLACE",
    )
    assert reseller["authorization_status"] == "APPLIED"
    assert policy["status"] == "PUBLISHED"

    validate_error(
        api_client.issue_notice(
            notice_payload(
                NON_EXISTENT_UUID,
                "00000000-0000-0000-0000-0000000000ee",
                current_reseller_version(reseller["id"]),
            ),
            BCM_HEADERS,
        ),
        ApiErrorId.ERR_RESELLER_NOT_FOUND.value,
    )


# --------------------------------------------------------------------------- #
# Priority 6 — resource ownership
# --------------------------------------------------------------------------- #
def test_a_reseller_may_not_acknowledge_another_resellers_notice():
    """A legal Reseller role is still bounded by the row's owning reference.

    PRD: "A violation of either ownership rule is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/validations/reseller_acknowledging_another_resellers_notice_rejected
    """
    policy = _published_policy()
    product = _headphones(policy["id"])
    acme, _acme_agreement = _authorized_acme(policy["id"])
    bravo, _bravo_agreement = _authorized_bravo(policy["id"])

    pin_clock(CLOCK_AUG_20)
    violation, _observation, _evaluation = create_detected_violation(
        product["id"],
        acme["id"],
        listed_price_cents=14000,
        channel="MARKETPLACE",
        observed_at=OBSERVED_AUG_18,
        seller_display_name="Acme Store",
        listing_url="https://mkt.example/l/1",
    )
    notice = issue_notice(acme["id"], violation["id"])

    validate_error(
        api_client.acknowledge_notice(notice["id"], make_reseller_headers(bravo["id"])),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
    )

    unchanged = read_notice(notice["id"])
    assert unchanged["status"] == "ISSUED"
    assert unchanged["acknowledged_at"] is None


def test_the_owning_reseller_acknowledges_its_own_notice():
    """The ownership check compares identity rather than refusing the role.

    PRD: "A reseller may acknowledge a notice, moving it `ISSUED → ACKNOWLEDGED` with
    `acknowledged_at` stamped from the current clock and the notice's `version`
    advanced."

    Design: Corner/validations/owning_reseller_acknowledging_its_own_notice_is_accepted
    """
    world = _warned_acme()
    acknowledged = validate_success(
        api_client.acknowledge_notice(
            world["notice"]["id"], make_reseller_headers(world["reseller"]["id"])
        )
    )

    assert acknowledged["status"] == "ACKNOWLEDGED"
    assert_same_instant(acknowledged["acknowledged_at"], CLOCK_AUG_20, "acknowledged_at")


def test_a_distributor_may_not_ship_another_distributors_unit():
    """Unit custody is owned by the distributor named on the shipping record.

    PRD: "Three preconditions apply: the unit must be in `SHIPPED_TO_DISTRIBUTOR`, the
    acting distributor's `X-User-ID` must equal the unit's `shipped_distributor_id`, and
    the target reseller's `supply_status` must be `OPEN` — a distributor may not ship to
    a reseller the brand has put on hold or cut off, which is precisely the mechanism a
    supply hold is meant to be."

    Design: Corner/validations/distributor_shipping_another_distributors_unit_rejected
    """
    policy = _published_policy()
    product = _headphones(policy["id"])
    acme, _agreement = _authorized_acme(policy["id"])
    northwind = create_distributor(
        legal_name="Northwind Distribution", annual_chargeback_cap_cents=500000
    )
    southpaw = create_distributor(
        legal_name="Southpaw Supply Co", annual_chargeback_cap_cents=500000
    )
    unit = create_serial_unit(
        product["id"], northwind["id"], serial_number="SN-0002", lot_code="LOT-A"
    )

    validate_error(
        api_client.ship_downstream(
            unit["id"],
            ship_downstream_payload(acme["id"]),
            make_headers(southpaw["id"], "Distributor"),
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
    )

    unchanged = read_serial_unit(unit["id"])
    assert unchanged["status"] == "SHIPPED_TO_DISTRIBUTOR"
    assert unchanged["downstream_reseller_id"] is None
