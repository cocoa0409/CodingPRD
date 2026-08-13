"""Drops: OCC stale version, validation priority, accept-side effects,
immediate consistency, filtered listings, invalid transitions, revocation."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_and_accept_drop,
    create_drop_at_site,
    create_drop_payload,
    create_host_agreement_payload,
    get_site_version,
    get_success_data,
    make_participant_headers,
    setup_program_with_operational_site,
    setup_verified_participant_with_grant,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]
HOST = TEST_USERS["site_host_headers"]


def _basic_setup(api):
    ids = setup_program_with_operational_site()
    part = setup_verified_participant_with_grant(ids["prog_id"], ids["site_id"])
    return ids, part


# ---------------------------------------------------------------------------
# Corner: cross_cutting_layers/occ_stale_site_version_on_drop (1 test)
# ---------------------------------------------------------------------------

def test_second_drop_with_stale_site_version_rejected(api):
    """PRD §2.5: "Recording a drop at a site requires the request to carry
    `expected_site_version`, holding the `version` of the parent `Site` the
    client last observed."
    PRD §2.5: "If the site's current `version` has advanced since that read —
    because another writer recorded a drop, a pickup completed, or a
    posture-affecting report or complaint landed — the request is rejected
    with `ERR_STALE_VERSION` (HTTP 412)"
    PRD §3.4: "Recording the drop immediately adds its `provisional_net_kg` to
    the site's `stored_kg`, recomputes the site's posture, and increments the
    site's `version` by 1"

    Design: Corner/cross_cutting_layers/occ_stale_site_version_on_drop
    """
    ids, part = _basic_setup(api)
    prog_id, site_id, mat_id = ids["prog_id"], ids["site_id"], ids["mat_id"]
    ph = part["part_headers"]

    sv = get_site_version(prog_id, site_id)
    validate_success(api.create_drop(
        prog_id, site_id,
        create_drop_payload(part["part_id"], part["grant_id"], mat_id, sv,
                            gross_weight_kg=5.00,
                            occurred_at="2026-07-01T10:00:00Z"),
        ph), expected_status=201)

    # Second drop reuses the now-stale version
    resp = api.create_drop(
        prog_id, site_id,
        create_drop_payload(part["part_id"], part["grant_id"], mat_id, sv,
                            gross_weight_kg=5.00,
                            occurred_at="2026-07-01T11:00:00Z"),
        ph)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict /
#             referential_vs_temporal_priority (2 tests)
# ---------------------------------------------------------------------------

def _setup_revoked_grant_scenario(api):
    """Agreement term [2026-06-01, 2027-01-01); grant issued then revoked."""
    ids = setup_program_with_operational_site(
        agreement_overrides={"term_start": "2026-06-01T00:00:00Z"})
    part = setup_verified_participant_with_grant(ids["prog_id"], ids["site_id"])
    get_success_data(api.revoke_grant(
        ids["prog_id"], part["part_id"], part["grant_id"], ADMIN))
    return ids, part


def test_revoked_grant_drop_fails_access_grant_check_not_timing(api):
    """PRD §2.9: "the server evaluates them in a fixed priority order, and the
    first failure determines the error returned" — access-grant validity (8)
    precedes drop timing (9).
    PRD §2.9: "Access-grant validity on drop creation: the grant must be
    `ACTIVE`, belong to the participant, reference the site, and have bucket
    headroom — otherwise `ERR_ACCESS_GRANT_INVALID` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/referential_vs_temporal_priority
    """
    ids, part = _setup_revoked_grant_scenario(api)
    prog_id, site_id, mat_id = ids["prog_id"], ids["site_id"], ids["mat_id"]

    sv = get_site_version(prog_id, site_id)
    # occurred_at 2026-05-01 is also outside the agreement term — but the
    # revoked grant must be reported first.
    resp = api.create_drop(
        prog_id, site_id,
        create_drop_payload(part["part_id"], part["grant_id"], mat_id, sv,
                            gross_weight_kg=1.00,
                            occurred_at="2026-05-01T10:00:00Z"),
        part["part_headers"])
    validate_error(resp, ApiErrorId.ERR_ACCESS_GRANT_INVALID)


def test_out_of_term_drop_with_valid_grant_fails_timing_check(api):
    """PRD §2.9: "Drop timing: `occurred_at` must not be in the future and
    must fall within the site's agreement term — otherwise
    `ERR_DROP_OUTSIDE_AGREEMENT_TERM` (HTTP 409)."
    PRD §2.9: "the first failure determines the error returned" — with a valid
    grant, the temporal check is the one that fires.

    Design: Difficulty/priority_pair_validation_conflict/referential_vs_temporal_priority
    """
    ids = setup_program_with_operational_site(
        agreement_overrides={"term_start": "2026-06-01T00:00:00Z"})
    part = setup_verified_participant_with_grant(ids["prog_id"], ids["site_id"])
    prog_id, site_id, mat_id = ids["prog_id"], ids["site_id"], ids["mat_id"]

    sv = get_site_version(prog_id, site_id)
    resp = api.create_drop(
        prog_id, site_id,
        create_drop_payload(part["part_id"], part["grant_id"], mat_id, sv,
                            gross_weight_kg=1.00,
                            occurred_at="2026-05-01T10:00:00Z"),
        part["part_headers"])
    validate_error(resp, ApiErrorId.ERR_DROP_OUTSIDE_AGREEMENT_TERM)


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine /
#             drop_event_parallel_credit_and_verification_dims (2 tests)
# ---------------------------------------------------------------------------

def test_contamination_report_flags_drop_but_credits_stay_uncredited(api):
    """PRD §3.4: "The audit loop runs on two parallel dimensions that never
    collapse into one: `verification_state` (`PENDING_AUDIT`, `ACCEPTED`,
    `FLAGGED_CONTAMINATED`, `REJECTED`) and `credit_state` (`UNCREDITED`,
    `PROVISIONALLY_CREDITED`, `FINALLY_CREDITED`, `REVOKED`)."
    PRD §3.4: "if it references a drop, that drop's `verification_state`
    automatically moves from `PENDING_AUDIT` to `FLAGGED_CONTAMINATED` while
    its `credit_state` stays `UNCREDITED` until the finding is resolved."

    Design: Difficulty/non_linear_state_machine/drop_event_parallel_credit_and_verification_dims
    """
    from test_helpers import create_contamination_report_payload
    ids, part = _basic_setup(api)
    prog_id, site_id, mat_id = ids["prog_id"], ids["site_id"], ids["mat_id"]

    drop = create_drop_at_site(prog_id, site_id, part["part_id"],
                               part["grant_id"], mat_id,
                               gross_weight_kg=10.00, contamination_kg=1.00)

    validate_success(api.create_contamination_report(
        prog_id, site_id,
        create_contamination_report_payload(
            drop_event_id=drop["id"], severity="MINOR",
            finding_note="plastic bag"),
        AUDITOR_HEADERS), expected_status=201)

    got = validate_success(api.get_drop(prog_id, site_id, drop["id"], ADMIN))
    assert got["verification_state"] == "FLAGGED_CONTAMINATED"
    assert got["credit_state"] == "UNCREDITED", (
        "credit_state is an independent dimension; flagging must not grant "
        "or revoke credits")


def test_flagged_drop_grants_no_credits_until_resolved(api):
    """PRD §3.4: "while its `credit_state` stays `UNCREDITED` until the
    finding is resolved."
    PRD §3.4: "the participant's `bucket_credit_balance` increases by the
    provisional net kilograms multiplied by the program's
    `diversion_credit_rate`" (acceptance only)

    Design: Difficulty/non_linear_state_machine/drop_event_parallel_credit_and_verification_dims
    """
    from test_helpers import create_contamination_report_payload
    ids, part = _basic_setup(api)
    prog_id, site_id, mat_id = ids["prog_id"], ids["site_id"], ids["mat_id"]

    drop = create_drop_at_site(prog_id, site_id, part["part_id"],
                               part["grant_id"], mat_id,
                               gross_weight_kg=10.00, contamination_kg=1.00)
    validate_success(api.create_contamination_report(
        prog_id, site_id,
        create_contamination_report_payload(
            drop_event_id=drop["id"], severity="MINOR",
            finding_note="plastic bag"),
        AUDITOR_HEADERS), expected_status=201)

    participant = validate_success(api.get_participant(
        prog_id, part["part_id"], ADMIN))
    assert participant["bucket_credit_balance"] == 0, (
        "no credits are granted while the drop sits FLAGGED_CONTAMINATED")


# ---------------------------------------------------------------------------
# Corner: state_machines/invalid_transition_reject_on_pending_drop (1 test)
# ---------------------------------------------------------------------------

def test_reject_on_pending_audit_drop_is_invalid_state(api):
    """PRD §2.9: "From-state: the target resource is in a valid from-state for
    the requested transition — otherwise `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.4: "Rejection — whether by dismissal of a `CRITICAL` report or by a
    `SiteHost` explicitly rejecting a flagged drop — moves
    `verification_state` to `REJECTED`"

    Design: Corner/state_machines/invalid_transition_reject_on_pending_drop
    """
    ids, part = _basic_setup(api)
    prog_id, site_id, mat_id = ids["prog_id"], ids["site_id"], ids["mat_id"]
    drop = create_drop_at_site(prog_id, site_id, part["part_id"],
                               part["grant_id"], mat_id, gross_weight_kg=5.00)

    resp = api.reject_drop(prog_id, site_id, drop["id"], HOST)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ---------------------------------------------------------------------------
# Corner: consistency_model/drop_accept_immediately_reflects_credit (1 test)
# ---------------------------------------------------------------------------

def test_drop_accept_immediately_reflects_credit(api):
    """PRD §3.4: "acceptance moves `verification_state` from `PENDING_AUDIT`
    to `ACCEPTED`, flips `credit_state` from `UNCREDITED` to
    `PROVISIONALLY_CREDITED`, and grants credits: the participant's
    `bucket_credit_balance` increases by the provisional net kilograms
    multiplied by the program's `diversion_credit_rate`, rounded half-up to a
    whole credit"

    Design: Corner/consistency_model/drop_accept_immediately_reflects_credit
    """
    ids, part = _basic_setup(api)
    prog_id, site_id, mat_id = ids["prog_id"], ids["site_id"], ids["mat_id"]
    drop = create_drop_at_site(prog_id, site_id, part["part_id"],
                               part["grant_id"], mat_id,
                               gross_weight_kg=10.00, contamination_kg=1.00)

    validate_success(api.accept_drop(prog_id, site_id, drop["id"], HOST))

    participant = validate_success(api.get_participant(
        prog_id, part["part_id"], ADMIN))
    assert participant["bucket_credit_balance"] == 9, (
        f"accept must grant 9 credits (9.00 kg net * 1.0), got "
        f"{participant['bucket_credit_balance']}")


# ---------------------------------------------------------------------------
# Corner: endpoints/list_drops_filtered_by_participant (1 test)
# ---------------------------------------------------------------------------

def test_list_drops_filtered_by_participant(api):
    """PRD §3.4: "Drop listings support filtering by `participant_id`,
    `verification_state`, and `credit_state`."
    PRD §2.3: "List responses include the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object."

    Design: Corner/endpoints/list_drops_filtered_by_participant
    """
    ids = setup_program_with_operational_site()
    prog_id, site_id, mat_id = ids["prog_id"], ids["site_id"], ids["mat_id"]
    pa = setup_verified_participant_with_grant(prog_id, site_id, email="a@x.com")
    pb = setup_verified_participant_with_grant(prog_id, site_id, email="b@x.com")

    create_drop_at_site(prog_id, site_id, pa["part_id"], pa["grant_id"],
                        mat_id, gross_weight_kg=5.00,
                        occurred_at="2026-07-01T10:00:00Z")
    create_drop_at_site(prog_id, site_id, pb["part_id"], pb["grant_id"],
                        mat_id, gross_weight_kg=7.00,
                        occurred_at="2026-07-01T11:00:00Z")

    data, meta = validate_paginated(api.list_drops(
        prog_id, site_id, ADMIN, params={"participant_id": pa["part_id"]}))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(data) == 1
    assert data[0]["participant_id"] == pa["part_id"]


# ---------------------------------------------------------------------------
# Corner: errors/error_buckets_still_out_on_revoke (1 test)
# ---------------------------------------------------------------------------

def test_grant_revoke_succeeds_with_zero_buckets_out(api):
    """PRD §3.3: "Revoking a grant moves it to `REVOKED` and is blocked while
    `buckets_checked_out` is greater than 0, failing with
    `ERR_BUCKETS_STILL_OUT` (HTTP 409)"

    Design: Corner/errors/error_buckets_still_out_on_revoke
    """
    ids, part = _basic_setup(api)

    resp = api.revoke_grant(ids["prog_id"], part["part_id"], part["grant_id"],
                            ADMIN)
    grant = validate_success(resp)
    assert grant["status"] == "REVOKED"
    assert grant["buckets_checked_out"] == 0


AUDITOR_HEADERS = TEST_USERS["municipal_auditor_headers"]
