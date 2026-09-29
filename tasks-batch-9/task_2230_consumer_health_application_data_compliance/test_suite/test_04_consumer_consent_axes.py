"""Consent architecture: three independent axes, one grant at a time.

Covers the consent record's parallel axis dimensions, the withdrawal cascade,
the conserved product-level share counter, the grant precedence ladder, and the
optimistic-concurrency guard that protects a consent record's supersession.
"""

from __future__ import annotations

from typing import Any

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiClient,
    ApiErrorId,
    assert_consent_record,
    assert_consumer,
    assert_timestamp_format,
    consumer_version,
    create_consumer,
    create_consumer_payload,
    create_product,
    grant_axes,
    make_consumer_headers,
    make_platform_admin_headers,
    make_privacy_officer_headers,
    open_consent_record,
    read_product,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _instant(value: str) -> str:
    """A server instant rendered without its optional zero fractional part."""
    assert_timestamp_format(value)
    return value.replace(".000Z", "Z")


def _share_count(app_product_id: str, api: ApiClient) -> int:
    """The product's current active_share_consent_count."""
    return int(read_product(app_product_id, api)["active_share_consent_count"])


def _consumer_with_axes(
    api: ApiClient, axes: tuple[str, ...], **consumer_overrides: Any
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """A product, a consumer on it, and an ACTIVE consent record with axes granted."""
    product = create_product(api)
    consumer = create_consumer(product["id"], api, **consumer_overrides)
    record = open_consent_record(consumer["id"], api)
    for axis in axes:
        record = grant_axes(record["id"], consumer["id"], [axis], api)
    return product, consumer, record


# ---------------------------------------------------------------------------
# The sale axis revokes on its own, leaving collection and sharing intact
# ---------------------------------------------------------------------------


def test_sale_revocation_leaves_the_collection_and_sharing_axes_intact(api: ApiClient) -> None:
    """A SELL withdrawal touches only the sale axis.

    PRD §3.5: "Withdrawing `SELL` requires `sale_state` to currently be `AUTHORIZED`. It sets `sale_state` to `REVOKED`, `last_withdrawn_axis` to `SELL`, and the two instant fields, and it leaves both `collection_state` and `sharing_state` unchanged."

    PRD §3.5: "Every accepted withdrawal, whichever axis it names, records `last_withdrawn_axis` as that axis, stamps `last_withdrawn_at` with the logical clock, and sets `processing_halt_deadline_at` to fifteen days after `last_withdrawn_at` — the operator has that fortnight-and-a-day to stop the processing the withdrawn axis had authorised."

    Design: Difficulty/non_linear_state_machine/consent_record_parallel_axes_sell_revocation_leaves_collect_and_share_intact
    """
    set_clock("2026-08-20T00:00:00Z", api)
    _product, consumer, record = _consumer_with_axes(
        api, ("COLLECT", "SHARE", "SELL"), residency_state_code="NV"
    )

    response = api.withdraw_consent(
        record["id"], {"axis": "SELL"}, make_consumer_headers(consumer["id"])
    )
    withdrawn = validate_success(response)
    assert_consent_record(withdrawn)

    assert withdrawn["sale_state"] == "REVOKED"
    assert withdrawn["collection_state"] == "GRANTED"
    assert withdrawn["sharing_state"] == "GRANTED"
    assert withdrawn["last_withdrawn_axis"] == "SELL"
    assert _instant(withdrawn["last_withdrawn_at"]) == "2026-08-20T00:00:00Z"
    assert _instant(withdrawn["processing_halt_deadline_at"]) == "2026-09-04T00:00:00Z"
    assert withdrawn["record_state"] == "ACTIVE"


def test_sale_revocation_leaves_the_active_share_consent_count_untouched(api: ApiClient) -> None:
    """The share counter is blind to sale-axis movement.

    PRD §3.5: "Because `sharing_state` does not leave `GRANTED`, `active_share_consent_count` is untouched."

    PRD §2.11: "`active_share_consent_count` is the number of consent records belonging to the product's consumers whose `record_state` is `ACTIVE` and whose `sharing_state` is `GRANTED`."

    Design: Difficulty/non_linear_state_machine/consent_record_parallel_axes_sell_revocation_leaves_collect_and_share_intact
    """
    set_clock("2026-08-20T00:00:00Z", api)
    product, consumer, record = _consumer_with_axes(
        api, ("COLLECT", "SHARE", "SELL"), residency_state_code="NV"
    )
    assert _share_count(product["id"], api) == 1

    response = api.withdraw_consent(
        record["id"], {"axis": "SELL"}, make_consumer_headers(consumer["id"])
    )
    withdrawn = validate_success(response)

    assert withdrawn["sharing_state"] == "GRANTED"
    assert _share_count(product["id"], api) == 1


# ---------------------------------------------------------------------------
# The share counter is a conserved quantity across grant and withdrawal
# ---------------------------------------------------------------------------


def test_share_grant_then_withdrawal_returns_the_share_counter_to_zero(api: ApiClient) -> None:
    """The SHARE increment and its compensating decrement cancel exactly.

    PRD §3.5: "The product's `active_share_consent_count` is a conserved quantity: a `SHARE` grant increments it by exactly one and the compensating `SHARE` withdrawal decrements it by exactly one, so the counter always equals the number of live `ACTIVE` records on the product with `sharing_state` `GRANTED`."

    Design: Difficulty/compensating_invariant/share_consent_grant_then_withdrawal_conserves_active_share_consent_count
    """
    set_clock("2026-08-12T00:00:00Z", api)
    product = create_product(api)
    assert _share_count(product["id"], api) == 0

    consumer = create_consumer(product["id"], api)
    record = open_consent_record(consumer["id"], api)
    grant_axes(record["id"], consumer["id"], ["COLLECT"], api)
    assert _share_count(product["id"], api) == 0

    grant_axes(record["id"], consumer["id"], ["SHARE"], api)
    assert _share_count(product["id"], api) == 1

    response = api.withdraw_consent(
        record["id"], {"axis": "SHARE"}, make_consumer_headers(consumer["id"])
    )
    withdrawn = validate_success(response)

    assert withdrawn["sharing_state"] == "WITHDRAWN"
    assert _share_count(product["id"], api) == 0


def test_share_withdrawal_leaves_the_other_two_axes_without_residue(api: ApiClient) -> None:
    """A SHARE withdrawal spares collection and never authorised sale.

    PRD §3.5: "Withdrawing `SHARE` requires `sharing_state` to currently be `GRANTED`. It sets `sharing_state` to `WITHDRAWN`, `last_withdrawn_axis` to `SHARE`, and the two instant fields; it moves `sale_state` from `AUTHORIZED → REVOKED` if it was `AUTHORIZED`; and it decrements the product's `active_share_consent_count` by one. It leaves `collection_state` alone — a consumer may keep using the product while refusing disclosure."

    Design: Difficulty/compensating_invariant/share_consent_grant_then_withdrawal_conserves_active_share_consent_count
    """
    set_clock("2026-08-12T00:00:00Z", api)
    product, consumer, record = _consumer_with_axes(api, ("COLLECT", "SHARE"))

    response = api.withdraw_consent(
        record["id"], {"axis": "SHARE"}, make_consumer_headers(consumer["id"])
    )
    withdrawn = validate_success(response)
    assert_consent_record(withdrawn)

    assert withdrawn["sharing_state"] == "WITHDRAWN"
    assert withdrawn["collection_state"] == "GRANTED"
    assert withdrawn["sale_state"] == "NOT_REQUESTED"
    assert withdrawn["last_withdrawn_axis"] == "SHARE"
    assert _instant(withdrawn["processing_halt_deadline_at"]) == "2026-08-27T00:00:00Z"
    assert withdrawn["record_state"] == "ACTIVE"
    assert _share_count(product["id"], api) == 0


# ---------------------------------------------------------------------------
# Consumer registration mints its own verification token
# ---------------------------------------------------------------------------


def test_consumer_registration_rejects_a_caller_supplied_verification_token(
    api: ApiClient,
) -> None:
    """The verification token is server-minted, never accepted from the body.

    PRD §3.5: "Registration mints a server-issued `verification_token`, which the consumer later presents to prove identity on a rights request, and initialises `deletion_completed_count` to zero; that counter tracks how many of the consumer's `DELETE` requests have reached `FULFILLED`."

    PRD §2.4: "Fields marked as computed or system-managed anywhere in this specification are never accepted from a request body. Supplying one is a malformed request and yields `ERR_INVALID_REQUEST`."

    Design: Corner/entities/system_fields_supplied_verification_token_returns_400
    """
    product = create_product(api)

    response = api.create_consumer(
        create_consumer_payload(
            product["id"],
            external_ref="acct-1",
            verification_token="chosen-by-caller",
        ),
        make_platform_admin_headers(),
    )
    validate_error(response, ApiErrorId.INVALID_REQUEST.value)


# ---------------------------------------------------------------------------
# Withdrawing collection drags the whole ladder down
# ---------------------------------------------------------------------------


def test_collection_withdrawal_cascades_across_all_three_axes(api: ApiClient) -> None:
    """One COLLECT withdrawal withdraws sharing and revokes sale in the same call.

    PRD §3.5: "Withdrawing `COLLECT` requires `collection_state` to currently be `GRANTED`. Hop one sets `collection_state` to `WITHDRAWN`, `last_withdrawn_axis` to `COLLECT`, and the two instant fields as above. Hop two, because collection consent was withdrawn, moves `sharing_state` from `GRANTED → WITHDRAWN` if it was `GRANTED`. Hop three, because sharing consent was withdrawn by hop two, moves `sale_state` from `AUTHORIZED → REVOKED` if it was `AUTHORIZED`. Hop four, because `sharing_state` left `GRANTED` in hop two, decrements the product's `active_share_consent_count` by one."

    Design: Corner/state_machines/parallel_shape_collect_withdrawal_cascades_across_all_three_axes
    """
    set_clock("2026-08-20T00:00:00Z", api)
    product, consumer, record = _consumer_with_axes(api, ("COLLECT", "SHARE", "SELL"))
    assert _share_count(product["id"], api) == 1

    response = api.withdraw_consent(
        record["id"], {"axis": "COLLECT"}, make_consumer_headers(consumer["id"])
    )
    withdrawn = validate_success(response)
    assert_consent_record(withdrawn)

    assert withdrawn["collection_state"] == "WITHDRAWN"
    assert withdrawn["sharing_state"] == "WITHDRAWN"
    assert withdrawn["sale_state"] == "REVOKED"
    assert withdrawn["last_withdrawn_axis"] == "COLLECT"
    assert _instant(withdrawn["processing_halt_deadline_at"]) == "2026-09-04T00:00:00Z"
    assert withdrawn["record_state"] == "ACTIVE"
    assert _share_count(product["id"], api) == 0


# ---------------------------------------------------------------------------
# A new record supersedes the incumbent and re-syncs the share ledger
# ---------------------------------------------------------------------------


def test_new_consent_record_supersedes_predecessor_and_syncs_the_share_count(
    api: ApiClient,
) -> None:
    """Opening a second record retires the first and gives back its share grant.

    PRD §3.5: "Creating it also moves the consumer's incumbent record, if one exists with `record_state` `ACTIVE`, from `ACTIVE → SUPERSEDED`; and if that outgoing record's `sharing_state` was `GRANTED`, the product's `active_share_consent_count` is decremented by one."

    PRD §3.5: "A new record is created with all three axes at their unrequested defaults — `collection_state` `NOT_REQUESTED`, `sharing_state` `NOT_REQUESTED`, `sale_state` `NOT_REQUESTED` — with `record_state` `ACTIVE`, with all four instant fields (`collection_granted_at`, `sharing_granted_at`, `sale_authorized_at`, `last_withdrawn_at`) null, with `last_withdrawn_axis` unset, and with `processing_halt_deadline_at` null."

    Design: Corner/state_machines/ledger_sync_new_consent_record_supersedes_predecessor_and_syncs_share_count
    """
    set_clock("2026-08-12T00:00:00Z", api)
    product, consumer, first = _consumer_with_axes(api, ("COLLECT", "SHARE"))
    assert _share_count(product["id"], api) == 1

    response = api.create_consent_record(
        {
            "consumer_id": consumer["id"],
            "expected_consumer_version": consumer_version(consumer["id"], api),
        },
        make_privacy_officer_headers(),
    )
    second = validate_success(response, 201)
    assert_consent_record(second)

    assert second["record_state"] == "ACTIVE"
    assert second["collection_state"] == "NOT_REQUESTED"
    assert second["sharing_state"] == "NOT_REQUESTED"
    assert second["sale_state"] == "NOT_REQUESTED"

    incumbent = validate_success(
        api.get_consent_record(first["id"], make_privacy_officer_headers())
    )
    assert incumbent["record_state"] == "SUPERSEDED"
    assert incumbent["sharing_state"] == "GRANTED"

    assert _share_count(product["id"], api) == 0


# ---------------------------------------------------------------------------
# Re-granting the share axis replays the posture forward
# ---------------------------------------------------------------------------


def test_share_axis_regrant_replays_to_granted_and_keeps_the_withdrawal_event(
    api: ApiClient,
) -> None:
    """Grant, withdraw, re-grant on the sharing axis restores the counter.

    PRD §3.5: "Granting `SHARE` requires the record's `collection_state` to already be `GRANTED` — you cannot authorise disclosure of data you have not authorised the collection of, and the attempt is refused with `ERR_COLLECTION_CONSENT_REQUIRED` — and requires the record's own `sharing_state` to be `NOT_REQUESTED` or `WITHDRAWN`. It sets `sharing_state` to `GRANTED`, stamps `sharing_granted_at` with the logical clock, and increments the product's `active_share_consent_count` by exactly one."

    Design: Corner/calculations/projection_consent_posture_replays_grant_withdraw_regrant_on_the_share_axis
    """
    set_clock("2026-08-20T00:00:00Z", api)
    product, consumer, record = _consumer_with_axes(api, ("COLLECT", "SHARE"))
    consumer_headers = make_consumer_headers(consumer["id"])
    validate_success(api.withdraw_consent(record["id"], {"axis": "SHARE"}, consumer_headers))
    assert _share_count(product["id"], api) == 0

    set_clock("2026-08-22T00:00:00Z", api)
    regranted = validate_success(
        api.grant_consent(record["id"], {"axes": ["SHARE"]}, consumer_headers)
    )
    assert_consent_record(regranted)

    assert regranted["collection_state"] == "GRANTED"
    assert regranted["sharing_state"] == "GRANTED"
    assert _instant(regranted["sharing_granted_at"]) == "2026-08-22T00:00:00Z"
    assert regranted["sale_state"] == "NOT_REQUESTED"
    assert regranted["last_withdrawn_axis"] == "SHARE"
    assert _instant(regranted["last_withdrawn_at"]) == "2026-08-20T00:00:00Z"
    assert _instant(regranted["processing_halt_deadline_at"]) == "2026-09-04T00:00:00Z"
    assert _share_count(product["id"], api) == 1


# ---------------------------------------------------------------------------
# Grant-time validation precedence
# ---------------------------------------------------------------------------


def test_bundled_axes_grant_is_refused_before_the_collection_consent_check(
    api: ApiClient,
) -> None:
    """Two axes in one grant is bundling, which masks the collection prerequisite.

    PRD §3.5: "Supplying two or more axes — or none — is bundled consent, which the regime forbids, and the call is refused with `ERR_CONSENT_BUNDLING_PROHIBITED`."

    PRD §2.7: "Lower-numbered checks therefore mask higher-numbered ones: a caller with the wrong role never learns that its payload was also malformed, and a caller acting on a policy that is not under review never learns that the policy's completeness score was also too low."

    PRD §3.5: "Where several of these checks could fire at once on a `SELL` grant, the precedence of §2.7 settles which the caller sees: the from-state check first, then the minor-sale prohibition, then the bundling check, then the collection-consent prerequisite, then the sharing-consent prerequisite."

    Design: Corner/validations/cascading_validation_bundled_axes_rejected_before_the_collection_consent_check
    """
    set_clock("2026-08-20T00:00:00Z", api)
    product = create_product(api)
    consumer = create_consumer(product["id"], api, external_ref="acct-1")
    record = open_consent_record(consumer["id"], api)

    response = api.grant_consent(
        record["id"],
        {"axes": ["COLLECT", "SHARE"]},
        make_consumer_headers(consumer["id"]),
    )
    validate_error(response, ApiErrorId.CONSENT_BUNDLING_PROHIBITED.value)

    unchanged = validate_success(
        api.get_consent_record(record["id"], make_privacy_officer_headers())
    )
    assert unchanged["collection_state"] == "NOT_REQUESTED"
    assert unchanged["sharing_state"] == "NOT_REQUESTED"
    assert unchanged["sale_state"] == "NOT_REQUESTED"
    assert _share_count(product["id"], api) == 0


def test_minor_cannot_authorize_a_sale(api: ApiClient) -> None:
    """A teenaged consumer may share but never authorise a sale.

    PRD §3.5: "Granting `SELL` requires the record's `sharing_state` to already be `GRANTED`, failing which the refusal is `ERR_SHARING_CONSENT_REQUIRED`; requires the record's own `sale_state` to be `NOT_REQUESTED` or `REVOKED`; and requires the consumer's `age_band` to be `ADULT`."

    PRD §3.5: "A sale authorisation for a consumer in the `MINOR_13_16` or `UNDER_13` band is prohibited outright and refused with `ERR_MINOR_SALE_PROHIBITED`."

    Design: Corner/validations/violation_to_error_minor_cannot_authorize_a_sale
    """
    set_clock("2026-08-20T00:00:00Z", api)
    product, consumer, record = _consumer_with_axes(
        api, ("COLLECT", "SHARE"), external_ref="acct-teen", age_band="MINOR_13_16"
    )

    response = api.grant_consent(
        record["id"], {"axes": ["SELL"]}, make_consumer_headers(consumer["id"])
    )
    validate_error(response, ApiErrorId.MINOR_SALE_PROHIBITED.value)

    unchanged = validate_success(
        api.get_consent_record(record["id"], make_privacy_officer_headers())
    )
    assert unchanged["sale_state"] == "NOT_REQUESTED"
    assert unchanged["sharing_state"] == "GRANTED"
    assert _share_count(product["id"], api) == 1


# ---------------------------------------------------------------------------
# Error triggerability on the consent and consumer endpoints
# ---------------------------------------------------------------------------


def test_unknown_consumer_on_consent_record_create_returns_consumer_not_found(
    api: ApiClient,
) -> None:
    """The body's consumer_id is resolved before the concurrency guard runs.

    PRD §2.6: "Foreign keys inside a request body are resolved after the body's shape has been validated, and they too are resolved in a fixed order rather than in whatever order the client happened to serialise them: `app_product_id`, then `applicability_assessment_id`, then `consumer_id`, then `data_element_id`, then `derived_from_element_id`, then `processing_purpose_id`, then `vendor_id`, then `subprocessor_of_id`, then `geofence_zone_id`, then `consumer_request_id`."

    PRD §2.6: "Each unresolved key maps to the same per-entity 404 code listed above."

    Design: Corner/errors/error_consumer_not_found_on_consent_record_create
    """
    product = create_product(api)
    consumer = create_consumer(product["id"], api, external_ref="acct-1")

    response = api.create_consent_record(
        {
            "consumer_id": NON_EXISTENT_UUID,
            "expected_consumer_version": consumer["version"],
        },
        make_privacy_officer_headers(),
    )
    validate_error(response, ApiErrorId.CONSUMER_NOT_FOUND.value)


def test_share_grant_without_collection_consent_is_refused(api: ApiClient) -> None:
    """Sharing cannot be authorised before collection has been.

    PRD §3.5: "Granting `SHARE` requires the record's `collection_state` to already be `GRANTED` — you cannot authorise disclosure of data you have not authorised the collection of, and the attempt is refused with `ERR_COLLECTION_CONSENT_REQUIRED` — and requires the record's own `sharing_state` to be `NOT_REQUESTED` or `WITHDRAWN`."

    Design: Corner/errors/error_collection_consent_required_on_share_grant
    """
    set_clock("2026-08-20T00:00:00Z", api)
    product = create_product(api)
    consumer = create_consumer(product["id"], api, external_ref="acct-1")
    record = open_consent_record(consumer["id"], api)

    response = api.grant_consent(
        record["id"], {"axes": ["SHARE"]}, make_consumer_headers(consumer["id"])
    )
    validate_error(response, ApiErrorId.COLLECTION_CONSENT_REQUIRED.value)

    unchanged = validate_success(
        api.get_consent_record(record["id"], make_privacy_officer_headers())
    )
    assert unchanged["sharing_state"] == "NOT_REQUESTED"
    assert _share_count(product["id"], api) == 0


def test_sale_grant_without_sharing_consent_is_refused(api: ApiClient) -> None:
    """The sale axis sits above the sharing rung of the ladder.

    PRD §3.5: "Granting `SELL` requires the record's `sharing_state` to already be `GRANTED`, failing which the refusal is `ERR_SHARING_CONSENT_REQUIRED`; requires the record's own `sale_state` to be `NOT_REQUESTED` or `REVOKED`; and requires the consumer's `age_band` to be `ADULT`."

    Design: Corner/errors/error_sharing_consent_required_on_sell_grant
    """
    set_clock("2026-08-20T00:00:00Z", api)
    _product, consumer, record = _consumer_with_axes(
        api, ("COLLECT",), external_ref="acct-1"
    )

    response = api.grant_consent(
        record["id"], {"axes": ["SELL"]}, make_consumer_headers(consumer["id"])
    )
    validate_error(response, ApiErrorId.SHARING_CONSENT_REQUIRED.value)

    unchanged = validate_success(
        api.get_consent_record(record["id"], make_privacy_officer_headers())
    )
    assert unchanged["collection_state"] == "GRANTED"
    assert unchanged["sale_state"] == "NOT_REQUESTED"


def test_duplicate_consumer_ref_within_a_product_is_refused(api: ApiClient) -> None:
    """An external_ref collides only inside its own product.

    PRD §3.5: "A `PlatformAdmin` registers each **consumer** of the product with the owning `app_product_id`, an operator-side pseudonymous account reference in `external_ref` that must be unique within the product — a collision is refused with `ERR_DUPLICATE_CONSUMER_REF` — the two-letter state code of the person's residence in `residency_state_code` (one of `WA`, `NV`, `CT`, `CA`, `TX`), and the bracket used by the minor-sale prohibition in `age_band` (`ADULT`, `MINOR_13_16`, or `UNDER_13`)."

    Design: Corner/errors/error_duplicate_consumer_ref_within_product
    """
    product_a = create_product(api)
    product_b = create_product(
        api,
        product_name="MoodTrack",
        company_legal_name="MoodTrack Inc",
        primary_state_code="TX",
        consumer_count=20000,
        annual_revenue_cents=400000000,
        hipaa_covered_transaction_ratio=0.00,
    )
    create_consumer(product_a["id"], api, external_ref="acct-1")
    consumer_b = create_consumer(
        product_b["id"], api, external_ref="acct-1", residency_state_code="TX"
    )

    response = api.create_consumer(
        create_consumer_payload(product_a["id"], external_ref="acct-1"),
        make_platform_admin_headers(),
    )
    validate_error(response, ApiErrorId.DUPLICATE_CONSUMER_REF.value)

    survivor = validate_success(
        api.get_consumer(consumer_b["id"], make_platform_admin_headers())
    )
    assert_consumer(survivor)
    assert survivor["external_ref"] == "acct-1"

    rows, meta = validate_paginated(
        api.list_consumers(
            make_platform_admin_headers(), {"app_product_id": product_a["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# Optimistic concurrency on consent record creation
# ---------------------------------------------------------------------------


def test_stale_consumer_version_on_consent_record_create_is_rejected(api: ApiClient) -> None:
    """The first record consumes the registration version, so replaying it fails.

    PRD §2.4: "Creating a consent record increments the owning consumer's `version` by one."

    PRD §2.8: "Opening a consent record — `POST /health-data/consent-records` — must carry `expected_consumer_version`, likewise required, holding the consumer `version` whose consent posture the caller intends to replace. A mismatch with the consumer's current `version` is rejected with `ERR_STALE_CONSUMER_VERSION` (HTTP 412), because a stale version means the posture about to be superseded is not the posture the caller observed."

    Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_stale_consumer_version_on_consent_record_create_rejected
    """
    set_clock("2026-08-20T00:00:00Z", api)
    product = create_product(api)
    consumer = create_consumer(product["id"], api, external_ref="acct-1")
    stale_version = int(consumer["version"])
    first = open_consent_record(consumer["id"], api)

    response = api.create_consent_record(
        {"consumer_id": consumer["id"], "expected_consumer_version": stale_version},
        make_privacy_officer_headers(),
    )
    validate_error(response, ApiErrorId.STALE_CONSUMER_VERSION.value)

    incumbent = validate_success(
        api.get_consent_record(first["id"], make_privacy_officer_headers())
    )
    assert incumbent["record_state"] == "ACTIVE"

    rows, meta = validate_paginated(
        api.list_consent_records(
            make_privacy_officer_headers(), {"consumer_id": consumer["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1
