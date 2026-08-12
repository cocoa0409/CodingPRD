"""Consent record lifecycle: filing defaults, withdrawal grace, rescind, amendment OCC, sweep timing."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    COORD_HEADERS,
    create_donor,
    create_donor_with_consent,
    create_in_stock_kit,
    withdraw_consent_and_finalize,
    set_clock_to,
    run_sweep,
    get_consent,
    get_kit,
)


def test_consent_record_defaults_applied(api):
    """PRD §3.1: "Two optional fields refine the grant: `excluded_uses`, a subset of the
    same enum carved back out of the permitted set, which defaults to an empty list, and
    `allow_reidentification`, which defaults to false and governs whether the
    re-identification key of §3.8 may ever be revealed. A freshly filed consent record
    is `ACTIVE`."

    Design: Corner/entities/consent_record_defaults_applied
    """
    donor = create_donor("D-ENT2")
    resp = api.create_consent_record(
        donor["id"],
        {"permitted_uses": ["GENERAL_RESEARCH", "DISEASE_SPECIFIC"],
         "effective_from": "2026-05-01T00:00:00Z"},
        COORD_HEADERS,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE"
    assert data["excluded_uses"] == []
    assert data["allow_reidentification"] is False
    assert data["grace_deadline"] is None


def test_withdraw_increments_version_and_sets_grace_deadline(api):
    """PRD §3.1: "Recording a withdrawal moves the consent from `ACTIVE` to
    `WITHDRAWAL_PENDING`, stamps `withdrawal_requested_at` with the current time,
    computes `grace_deadline` as exactly 72 hours after `withdrawal_requested_at`, and
    increments the record's `version` by one."

    Design: Corner/cross_cutting_layers/version_increments_on_withdraw
    """
    _, consent = create_donor_with_consent()
    pre_version = consent["version"]
    resp = api.withdraw_consent(consent["id"], {}, COORD_HEADERS)
    data = validate_success(resp, expected_status=200)
    assert data["version"] == pre_version + 1, (
        f"withdraw must bump version by exactly 1: {pre_version} -> {data['version']}")
    assert data["status"] == "WITHDRAWAL_PENDING"
    assert data["grace_deadline"] == "2026-05-04T00:00:00Z"


def test_withdraw_from_withdrawn_rejected(api):
    """PRD §3.1: "the consent must be `ACTIVE` and already effective, failing otherwise
    with `ERR_CONSENT_NOT_ACTIVE`."

    Design: Corner/state_machines/consent_withdraw_from_withdrawn_rejected
    """
    _, consent = create_donor_with_consent()
    sweep = withdraw_consent_and_finalize(consent["id"])
    assert sweep["withdrawals_finalized"] == 1
    resp = api.withdraw_consent(consent["id"], {}, COORD_HEADERS)
    validate_error(resp, ApiErrorId.ERR_CONSENT_NOT_ACTIVE)
    assert get_consent(consent["id"])["status"] == "WITHDRAWN"


def test_rescind_after_grace_expired_rejected(api):
    """PRD §3.1: "A rescind attempted at or after the grace deadline is rejected with
    `ERR_WITHDRAWAL_GRACE_EXPIRED` (HTTP 409); a rescind attempted on a consent that is
    not `WITHDRAWAL_PENDING` is rejected with `ERR_CONSENT_NOT_ACTIVE`."

    Design: Corner/state_machines/rescind_after_grace_expired_rejected
    """
    _, consent = create_donor_with_consent()
    resp = api.withdraw_consent(consent["id"], {}, COORD_HEADERS)
    validate_success(resp, expected_status=200)
    set_clock_to("2026-05-04T00:00:00Z")  # exactly the grace deadline; no sweep run
    resp = api.rescind_withdrawal(consent["id"], {}, COORD_HEADERS)
    validate_error(resp, ApiErrorId.ERR_WITHDRAWAL_GRACE_EXPIRED)
    assert get_consent(consent["id"])["status"] == "WITHDRAWAL_PENDING"


def test_occ_stale_consent_version_on_amend_rejected(api):
    """PRD §2.7: "Because an amendment supersedes the prior record and bumps its
    version, a second amendment attempted against the same observed version must fail
    on the stale version alone — it is rejected with `ERR_STALE_VERSION` (HTTP 412)
    even though the record it targets has already been superseded."

    Design: Corner/cross_cutting_layers/occ_stale_consent_version_on_amend_rejected
    """
    _, consent = create_donor_with_consent()
    observed_version = consent["version"]
    amend_payload = {
        "permitted_uses": ["GENERAL_RESEARCH", "DISEASE_SPECIFIC"],
        "effective_from": "2026-05-01T00:00:00Z",
        "expected_consent_record_version": observed_version,
    }
    resp = api.amend_consent(consent["id"], amend_payload, COORD_HEADERS)
    new_consent = validate_success(resp, expected_status=201)
    old_consent = get_consent(consent["id"])
    assert old_consent["status"] == "SUPERSEDED"
    assert old_consent["version"] == observed_version + 1
    assert new_consent["status"] == "ACTIVE"
    assert new_consent["supersedes_consent_id"] == consent["id"]
    # Second amendment replaying the same observed version: stale-version rejection.
    resp = api.amend_consent(
        consent["id"],
        {"permitted_uses": ["GENERAL_RESEARCH"],
         "effective_from": "2026-05-01T00:00:00Z",
         "expected_consent_record_version": observed_version},
        COORD_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_withdrawal_grace_boundary_inclusive(api):
    """PRD §2.5: "A withdrawal finalizes when the current time is at or after the
    consent's `grace_deadline`."

    Design: Corner/calculations/withdrawal_grace_boundary_inclusive
    """
    _, consent = create_donor_with_consent()
    resp = api.withdraw_consent(consent["id"], {}, COORD_HEADERS)
    validate_success(resp, expected_status=200)
    set_clock_to("2026-05-04T00:00:00Z")  # exactly grace_deadline (72h after 2026-05-01T00:00:00Z)
    sweep = run_sweep()
    assert sweep["withdrawals_finalized"] == 1, "deadline is inclusive: sweep must finalize"
    assert get_consent(consent["id"])["status"] == "WITHDRAWN"


def test_sweep_does_not_finalize_early(api):
    """PRD §2.5: "A withdrawal finalizes when the current time is at or after the
    consent's `grace_deadline`."

    Design: Corner/cross_cutting_layers/sweep_does_not_finalize_early
    """
    _, consent = create_donor_with_consent()
    resp = api.withdraw_consent(consent["id"], {}, COORD_HEADERS)
    validate_success(resp, expected_status=200)
    set_clock_to("2026-05-03T23:00:00Z")  # one hour before the 2026-05-04T00:00:00Z deadline
    sweep = run_sweep()
    assert sweep["withdrawals_finalized"] == 0, "before the deadline nothing may finalize"
    assert get_consent(consent["id"])["status"] == "WITHDRAWAL_PENDING"


def test_sweep_summary_counts(api):
    """PRD §2.5: "The sweep response reports how many items each job processed, via the
    counters `withdrawals_finalized`, `kits_expired`, `agreements_expired`,
    `grants_expired`, and `reservations_completed`."

    Design: Corner/endpoints/sweep_summary_counts
    """
    _, consent = create_donor_with_consent()
    resp = api.withdraw_consent(consent["id"], {}, COORD_HEADERS)
    validate_success(resp, expected_status=200)
    kit = create_in_stock_kit(kit_type="SALIVA", expires_at="2026-05-02T00:00:00Z")
    set_clock_to("2026-05-04T00:00:00Z")  # both the withdrawal and the kit are due
    sweep = run_sweep()
    assert sweep["withdrawals_finalized"] == 1
    assert sweep["kits_expired"] == 1
    assert get_consent(consent["id"])["status"] == "WITHDRAWN"
    assert get_kit(kit["id"])["status"] == "EXPIRED"
