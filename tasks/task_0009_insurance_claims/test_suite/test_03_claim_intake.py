"""Claim intake workflow.

Pinned to PRD §2.4 (claim_number minting), §2.6 (validation cascade), §3.1
(filing), §3.9 (Customer ownership semantics).
"""
import re
from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID,
    build_user_headers, TEST_USERS, CLAIM_NUMBER_RE,
    create_claim_payload, create_policy_payload,
    create_policy, file_claim, setup_basic_world,
    patch_policy_status, get_claim, days_ago, days_ahead,
    make_customer_headers,
    assert_claim,
)


# ─── §3.1 happy-path intake ───────────────────────────────────────
def test_intake_succeeds_returns_201_and_claim_envelope(api):
    """PRD §4 endpoints table: "Operations that create a new, distinct
    resource (a policy, an adjuster, a repair shop, a claim, an investigation,
    an estimate line item, a primary review decision, a payout, an appeal,
    a secondary review decision, or a fraud flag) return HTTP `201 Created`."

    Claim: POST /claims returns 201 with a Claim object in INTAKE status.
    """
    world = setup_basic_world()
    payload = create_claim_payload(
        policy_id=world["policy"]["id"],
        idempotency_key="claim-intake-201",
        loss_date=days_ago(1),
    )
    res = api.create_claim(payload, make_customer_headers(world["insured_party_id"]))
    claim = validate_success(res, expected_status=201)
    assert claim["status"] == "INTAKE"
    assert claim["claimant_id"] == world["insured_party_id"]
    assert_claim(claim)


def test_intake_records_claimant_id_from_x_user_id(api):
    """PRD §3.1: "The `claimant_id` on the new claim is the `X-User-ID` of
    the calling customer."

    Claim: Claim.claimant_id == X-User-ID supplied at intake.
    """
    world = setup_basic_world()
    claim = file_claim(world)
    assert claim["claimant_id"] == world["insured_party_id"]


def test_claim_number_format_and_unique(api):
    """PRD §2.4: "This identifier is server-minted on intake in the form
    `CLM-YYYYMMDD-NNNN`, where `YYYYMMDD` is the UTC date on which the claim
    was created and `NNNN` is a zero-padded four-digit decimal sequence
    equal to one plus the count of claims already created with the same
    UTC `created_at` date. The first claim of a given UTC date receives
    sequence `0001`. The sequence resets to `0001` at the start of each
    new UTC date. `claim_number` is unique across the system."

    Claim: claim_number matches the CLM-YYYYMMDD-NNNN pattern, and two
    claims minted on the same UTC date receive distinct claim_numbers.
    """
    world = setup_basic_world()
    c1 = file_claim(world, idempotency_key="cn-1")
    c2 = file_claim(world, idempotency_key="cn-2")
    assert CLAIM_NUMBER_RE.match(c1["claim_number"]), c1["claim_number"]
    assert CLAIM_NUMBER_RE.match(c2["claim_number"]), c2["claim_number"]
    assert c1["claim_number"] != c2["claim_number"]


def test_intake_stamps_reported_at(api):
    """PRD §3.1: "The server stamps `reported_at` from its own clock at the
    moment intake completes"

    Claim: Claim.reported_at is present and ISO 8601 immediately after
    intake.
    """
    world = setup_basic_world()
    claim = file_claim(world)
    assert claim["reported_at"], "reported_at must be populated at intake"


def test_intake_default_salvage_value_zero_when_omitted(api):
    """PRD §3.1: "The customer may also supply `salvage_value_cents` upfront
    if salvage is already known; if omitted, salvage defaults to 0."

    Claim: omitting salvage_value_cents -> Claim.salvage_value_cents == 0.
    """
    world = setup_basic_world()
    payload = create_claim_payload(
        policy_id=world["policy"]["id"],
        idempotency_key="no-salvage-1",
        loss_date=days_ago(1),
        salvage_value_cents=None,
    )
    res = api.create_claim(payload, make_customer_headers(world["insured_party_id"]))
    claim = validate_success(res, expected_status=201)
    assert claim["salvage_value_cents"] == 0


# ─── §2.6 validation cascade ──────────────────────────────────────
def test_intake_with_inactive_policy_rejected(api):
    """PRD §2.6: "the referenced `Policy` must exist and have `status` equal
    to `ACTIVE` (a non-active policy yields `ERR_POLICY_INACTIVE`)"

    Claim: filing against a SUSPENDED policy -> ERR_POLICY_INACTIVE.
    """
    world = setup_basic_world()
    patch_policy_status(world["policy"]["id"], "SUSPENDED", version=world["policy"]["version"])
    payload = create_claim_payload(
        policy_id=world["policy"]["id"],
        idempotency_key="inactive-1",
        loss_date=days_ago(1),
    )
    res = api.create_claim(payload, make_customer_headers(world["insured_party_id"]))
    validate_error(res, "ERR_POLICY_INACTIVE")


def test_intake_with_loss_date_before_effective_from_rejected(api):
    """PRD §2.6: "the supplied `loss_date` must lie at or after the policy's
    `effective_from` and strictly before `effective_to` (otherwise
    `ERR_LOSS_OUTSIDE_POLICY_PERIOD`)"

    Claim: loss_date one day BEFORE effective_from -> ERR_LOSS_OUTSIDE_POLICY_PERIOD.
    """
    world = setup_basic_world()
    # Policy was created with effective_from = days_ago(365); pick a date older.
    payload = create_claim_payload(
        policy_id=world["policy"]["id"],
        idempotency_key="early-loss-1",
        loss_date=days_ago(400),
    )
    res = api.create_claim(payload, make_customer_headers(world["insured_party_id"]))
    validate_error(res, "ERR_LOSS_OUTSIDE_POLICY_PERIOD")


def test_intake_loss_date_at_effective_from_inclusive(api):
    """PRD §2.6: "the supplied `loss_date` must lie at or after the policy's
    `effective_from`"

    Claim: loss_date == effective_from is INCLUDED (boundary).
    """
    # Build a policy with a fixed effective_from so we can hit it exactly.
    eff_from = "2024-01-01T00:00:00.000Z"
    eff_to = "2030-01-01T00:00:00.000Z"
    insured = "customer-bound-from-1"
    policy = create_policy(
        insured_party_id=insured,
        effective_from=eff_from, effective_to=eff_to,
        reporting_window_days=10_000,  # don't trip the reporting-window check
    )
    payload = create_claim_payload(
        policy_id=policy["id"],
        idempotency_key="bound-from-1",
        loss_date=eff_from,
    )
    res = api.create_claim(payload, make_customer_headers(insured))
    claim = validate_success(res, expected_status=201)
    assert claim["status"] == "INTAKE"


def test_intake_loss_date_at_effective_to_excluded(api):
    """PRD §2.6: "and strictly before `effective_to` (otherwise
    `ERR_LOSS_OUTSIDE_POLICY_PERIOD`)"

    Claim: loss_date == effective_to is EXCLUDED (half-open) ->
    ERR_LOSS_OUTSIDE_POLICY_PERIOD.

    # difficulty: resource_temporal_overlap/policy_period_half_open_interval
    """
    eff_from = "2024-01-01T00:00:00.000Z"
    eff_to = "2024-12-31T23:59:59.999Z"
    insured = "customer-bound-to-1"
    policy = create_policy(
        insured_party_id=insured,
        effective_from=eff_from, effective_to=eff_to,
        reporting_window_days=10_000,
    )
    payload = create_claim_payload(
        policy_id=policy["id"],
        idempotency_key="bound-to-1",
        loss_date=eff_to,
    )
    res = api.create_claim(payload, make_customer_headers(insured))
    validate_error(res, "ERR_LOSS_OUTSIDE_POLICY_PERIOD")


def test_intake_reporting_window_exceeded_rejected(api):
    """PRD §2.6: "the number of whole days between `loss_date` and the
    server-stamped `reported_at` must be at most the policy's
    `reporting_window_days` (otherwise `ERR_REPORTING_WINDOW_EXCEEDED`)"

    Claim: with reporting_window_days=30 on the policy, a loss_date 60
    days before now -> ERR_REPORTING_WINDOW_EXCEEDED.
    """
    insured = "customer-rw-1"
    policy = create_policy(
        insured_party_id=insured, reporting_window_days=30,
        effective_from=days_ago(365), effective_to=days_ahead(365),
    )
    payload = create_claim_payload(
        policy_id=policy["id"],
        idempotency_key="rw-exceeded-1",
        loss_date=days_ago(60),
    )
    res = api.create_claim(payload, make_customer_headers(insured))
    validate_error(res, "ERR_REPORTING_WINDOW_EXCEEDED")


def test_intake_duplicate_idempotency_within_24h_rejected(api):
    """PRD §2.6: "the combination of `claimant_id` and `idempotency_key`
    must not already exist for any claim created in the previous 24 hours
    (otherwise `ERR_DUPLICATE_CLAIM_INTAKE`)"

    Claim: two intakes by the same claimant with the same idempotency_key
    within 24h -> the second is rejected with ERR_DUPLICATE_CLAIM_INTAKE.
    """
    world = setup_basic_world()
    file_claim(world, idempotency_key="dup-key-1")
    payload = create_claim_payload(
        policy_id=world["policy"]["id"],
        idempotency_key="dup-key-1",
        loss_date=days_ago(1),
    )
    res = api.create_claim(payload, make_customer_headers(world["insured_party_id"]))
    validate_error(res, "ERR_DUPLICATE_CLAIM_INTAKE")


def test_intake_validation_cascade_state_beats_referential(api):
    """PRD §2.6: "All claim intake checks are evaluated in a strict priority
    sequence. Authentication runs first, followed by authorisation, followed
    by existence of path-referenced resources, followed by the requirement
    that the `Claim` (or other action target) be in the correct state for
    the requested action; then the domain checks specific to intake apply
    in this order: the referenced `Policy` must exist and have `status`
    equal to `ACTIVE` (a non-active policy yields `ERR_POLICY_INACTIVE`);
    the supplied `loss_date` must lie at or after the policy's
    `effective_from` and strictly before `effective_to` (otherwise
    `ERR_LOSS_OUTSIDE_POLICY_PERIOD`)"

    Claim: when both ERR_POLICY_INACTIVE and ERR_LOSS_OUTSIDE_POLICY_PERIOD
    would apply, the higher-priority ERR_POLICY_INACTIVE wins.
    """
    world = setup_basic_world()
    patch_policy_status(world["policy"]["id"], "SUSPENDED", version=world["policy"]["version"])
    payload = create_claim_payload(
        policy_id=world["policy"]["id"],
        idempotency_key="cascade-priority-1",
        loss_date=days_ago(400),  # also outside-period
    )
    res = api.create_claim(payload, make_customer_headers(world["insured_party_id"]))
    validate_error(res, "ERR_POLICY_INACTIVE")


# ─── §3.9 Customer ownership ──────────────────────────────────────
def test_intake_customer_must_match_policy_insured_party(api):
    """PRD §2.1: "a customer may only act on a claim where `Claim.claimant_id`
    equals `X-User-ID`, may only appeal as the original claimant, and may
    only intake a claim against a `Policy` whose `insured_party_id` equals
    `X-User-ID`"

    Claim: a Customer whose X-User-ID does not equal Policy.insured_party_id
    cannot file an intake against that policy.
    """
    world = setup_basic_world()  # policy.insured_party_id == world["insured_party_id"]
    foreign_customer_id = "foreign-customer-id-9999"
    payload = create_claim_payload(
        policy_id=world["policy"]["id"],
        idempotency_key="foreign-1",
        loss_date=days_ago(1),
    )
    res = api.create_claim(payload, make_customer_headers(foreign_customer_id))
    body = res.json()
    assert res.status_code >= 400, f"Foreign customer must not file: {body}"


def test_intake_unknown_role_for_endpoint_rejected(api):
    """PRD §4 endpoints table: POST /claims authorised role is Customer.

    Claim: Adjuster calling POST /claims -> ERR_FORBIDDEN.
    """
    world = setup_basic_world()
    payload = create_claim_payload(
        policy_id=world["policy"]["id"],
        idempotency_key="rbac-intake-1",
        loss_date=days_ago(1),
    )
    res = api.create_claim(payload, build_user_headers("a", "Adjuster"))
    validate_error(res, "ERR_FORBIDDEN")


# ─── §2.6 generic body validation lowest priority ─────────────────
def test_intake_missing_policy_id_rejected(api):
    """PRD §2.6: "Generic body validation (missing fields, wrong types,
    out-of-range values) returns `ERR_VALIDATION_FAILED` and is the
    lowest-priority check."

    Claim: omitting policy_id -> ERR_VALIDATION_FAILED.
    """
    world = setup_basic_world()
    payload = create_claim_payload(
        policy_id=None,
        idempotency_key="missing-policy-1",
        loss_date=days_ago(1),
    )
    res = api.create_claim(payload, make_customer_headers(world["insured_party_id"]))
    validate_error(res, "ERR_VALIDATION_FAILED")


def test_intake_claimed_amount_zero_rejected(api):
    """PRD §3.1: "states a `claimed_amount_cents` strictly greater than zero."

    Claim: claimed_amount_cents = 0 -> ERR_VALIDATION_FAILED.
    """
    world = setup_basic_world()
    payload = create_claim_payload(
        policy_id=world["policy"]["id"],
        idempotency_key="zero-amount-1",
        loss_date=days_ago(1),
        claimed_amount_cents=0,
    )
    res = api.create_claim(payload, make_customer_headers(world["insured_party_id"]))
    validate_error(res, "ERR_VALIDATION_FAILED")


def test_intake_invalid_report_channel_rejected(api):
    """PRD §3.1: "declares an intake channel through `report_channel` (one
    of `WEB`, `MOBILE`, `PHONE`, or `AGENT`)"

    Claim: report_channel = "FAX" -> ERR_VALIDATION_FAILED.
    """
    world = setup_basic_world()
    payload = create_claim_payload(
        policy_id=world["policy"]["id"],
        idempotency_key="bad-channel-1",
        loss_date=days_ago(1),
        report_channel="FAX",
    )
    res = api.create_claim(payload, make_customer_headers(world["insured_party_id"]))
    validate_error(res, "ERR_VALIDATION_FAILED")
