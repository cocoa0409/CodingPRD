"""Optimistic concurrency control on study amendment and session reschedule."""
from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    create_remote_session,
    create_study,
    get_session,
    get_study,
    get_success_data,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
RESEARCHER = TEST_USERS["researcher_headers"]


def test_study_amend_occ_stale_version(api):
    """PRD §2.7: "`PATCH /playtests/studies/{id}` requires the request body to
    carry `expected_study_version`, a non-optional field holding the `version`
    of the study as the client last observed it. If the study's current
    `version` does not match — because another writer's amendment has advanced
    it since the client last read the study — the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412), and no field of the study changes."
    PRD §2.5: "The `version` field is an integer that increments by one on
    every mutation of the resource"

    Design: Corner/complexity_layers/study_amend_occ_stale_version
    """
    study = create_study(open_recruitment=False, code="OCC1", title="OCC1 Study")
    observed = study["version"]
    amended = validate_success(api.amend_study(
        study["id"], {"expected_study_version": observed,
                      "incentive_budget_cents": 2000000}, ADMIN))
    assert amended["version"] == observed + 1, "a successful amendment increments version"
    assert amended["incentive_budget_cents"] == 2000000
    # Replaying the stale observed version is rejected.
    resp = api.amend_study(study["id"], {"expected_study_version": observed,
                                         "title": "Hijacked title"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    now = get_study(study["id"])
    assert now["title"] == "OCC1 Study", "the losing write changed nothing"
    assert now["incentive_budget_cents"] == 2000000
    assert now["version"] == observed + 1


def test_session_reschedule_occ_stale_version(api):
    """PRD §2.7: "`PATCH /playtests/sessions/{id}/reschedule` likewise requires
    `expected_session_version`, compared against the session's current
    `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412) and
    the window is left untouched."
    PRD §3.5: "Rescheduling moves the window while the session is `SCHEDULED`:
    the request carries `expected_session_version` under the OCC rule of §2.7
    alongside the new `starts_at` and `ends_at`, re-validates the window rule"

    Design: Corner/complexity_layers/session_reschedule_occ_stale_version
    """
    study = create_study(code="OCC2")
    session = create_remote_session(study["id"], "2026-08-10T10:00:00Z",
                                    "2026-08-10T11:00:00Z", seat_capacity=4)
    observed = session["version"]
    moved = validate_success(api.reschedule_session(
        session["id"], {"expected_session_version": observed,
                        "starts_at": "2026-08-11T10:00:00Z",
                        "ends_at": "2026-08-11T11:00:00Z"}, RESEARCHER))
    assert moved["version"] == observed + 1
    assert_instant_equals(moved["starts_at"], "2026-08-11T10:00:00Z", "starts_at")
    # Replaying the stale observed version is rejected and the window stays put.
    resp = api.reschedule_session(
        session["id"], {"expected_session_version": observed,
                        "starts_at": "2026-08-12T10:00:00Z",
                        "ends_at": "2026-08-12T11:00:00Z"}, RESEARCHER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    now = get_session(session["id"])
    assert_instant_equals(now["starts_at"], "2026-08-11T10:00:00Z", "starts_at")
    assert now["version"] == observed + 1
