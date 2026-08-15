"""Build distribution: key issuance gates, expiry boundaries, exposure journal,
cohort retention across builds."""
import pytest

from test_helpers import (
    ApiErrorId,
    apply_to_study,
    approve_application,
    assert_access_key,
    assert_exposure_record,
    create_build,
    create_released_build,
    enroll_participant,
    get_build,
    get_pending_signature,
    get_success_data,
    issue_key,
    list_exposures,
    make_participant_headers,
    register_participant,
    run_expiry_sweep,
    set_clock,
    setup_enrolled_participant,
    setup_study_with_published_nda,
    sign_signature,
    start_review,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
RESEARCHER = TEST_USERS["researcher_headers"]
LEGAL = TEST_USERS["legal_headers"]


def _approved_participant(study_id, email):
    """ACTIVE participant walked to APPROVED (PENDING signature, unsigned)."""
    participant = register_participant(email=email)
    app = start_review(apply_to_study(study_id, participant["id"])["id"])
    app = approve_application(app["id"])
    assert app["status"] == "APPROVED"
    return participant, app


class TestKeyIssueRequiresReleasedBuild:
    def test_issue_against_staged_build_rejected(self, api):
        """PRD §3.4: "The build must be `RELEASED` (`ERR_BUILD_NOT_RELEASED`)."

        Design: Difficulty/cross_entity_state_dependency/key_issue_requires_released_build
        """
        ctx = setup_enrolled_participant(email="ce2-p@x.com")
        build = create_build(ctx["study"]["id"])  # STAGED
        resp = api.create_access_key(
            {"build_id": build["id"], "participant_id": ctx["participant"]["id"]}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_BUILD_NOT_RELEASED)
        keys = get_success_data(api.list_access_keys(
            ADMIN, params={"build_id": build["id"]}))
        assert keys == [], "no key is created against a STAGED build"

    def test_issue_succeeds_once_build_released(self, api):
        """PRD §3.4: "A successful issuance mints a unique `key_code` — the
        literal KEY- followed by twelve uppercase alphanumeric characters —
        sets the key `ISSUED` with `expires_at` at the issuance instant plus
        the build's `key_ttl_hours`, increments `keys_active_count` by one, and
        appends a `KEY_ISSUED` record to the exposure journal."

        Design: Difficulty/cross_entity_state_dependency/key_issue_requires_released_build
        """
        set_clock("2026-08-01T00:00:00Z")
        ctx = setup_enrolled_participant(email="ce2-p@x.com")
        build = create_build(ctx["study"]["id"])
        get_success_data(api.release_build(build["id"], ADMIN))
        key = validate_success(api.create_access_key(
            {"build_id": build["id"], "participant_id": ctx["participant"]["id"]},
            ADMIN), expected_status=201)
        assert_access_key(key)
        assert key["status"] == "ISSUED"
        assert get_build(build["id"])["keys_active_count"] == 1


class TestKeyIssueSafetyBeatsQuota:
    def _setup(self, api):
        """A enrolled+signed holding the only key of a max_keys=1 build;
        B APPROVED with a PENDING (unsigned) signature."""
        study, nda = setup_study_with_published_nda(code="PP2")
        pa = register_participant(email="pp2-a@x.com")
        enroll_participant(study["id"], pa)
        build = create_released_build(study["id"], build_label="1.0.0", max_keys=1)
        issue_key(build["id"], pa["id"])
        assert get_build(build["id"])["keys_active_count"] == 1, "quota is full"
        pb, _app_b = _approved_participant(study["id"], "pp2-b@x.com")
        return study, build, pa, pb

    def test_nda_not_signed_outranks_quota_exceeded(self, api):
        """PRD §3.4: "The recipient must hold a `SIGNED` signature on the
        study's currently `PUBLISHED` agreement — this safety gate outranks the
        quota check — else `ERR_NDA_NOT_SIGNED`."

        Design: Difficulty/priority_pair_validation_conflict/key_issue_safety_beats_quota_constraint
        """
        _study, build, _pa, pb = self._setup(api)
        resp = api.create_access_key(
            {"build_id": build["id"], "participant_id": pb["id"]}, ADMIN)
        # Both ERR_NDA_NOT_SIGNED and ERR_KEY_QUOTA_EXCEEDED hold; safety wins.
        validate_error(resp, ApiErrorId.ERR_NDA_NOT_SIGNED)
        assert resp.status_code == 422
        assert resp.json()["data"]["error_id"] != "ERR_KEY_QUOTA_EXCEEDED"

    def test_rejected_issuance_persists_nothing(self, api):
        """PRD §3.4: "The build's `keys_active_count` must be strictly below
        `max_keys`, with equality meaning the quota is exhausted
        (`ERR_KEY_QUOTA_EXCEEDED`)."
        PRD §2.5: "All state changes are atomic and immediately consistent"

        Design: Difficulty/priority_pair_validation_conflict/key_issue_safety_beats_quota_constraint
        """
        _study, build, _pa, pb = self._setup(api)
        validate_error(api.create_access_key(
            {"build_id": build["id"], "participant_id": pb["id"]}, ADMIN),
            ApiErrorId.ERR_NDA_NOT_SIGNED)
        assert get_build(build["id"])["keys_active_count"] == 1
        keys_b = get_success_data(api.list_access_keys(
            ADMIN, params={"participant_id": pb["id"]}))
        assert keys_b == [], "the rejected issuance minted no key"


def test_key_quota_exceeded_at_boundary(api):
    """PRD §3.4: "The build's `keys_active_count` must be strictly below
    `max_keys`, with equality meaning the quota is exhausted
    (`ERR_KEY_QUOTA_EXCEEDED`)."

    Design: Corner/validations/key_quota_exceeded_at_boundary
    """
    study, _nda = setup_study_with_published_nda(code="KQ1")
    pa = register_participant(email="kq-a@x.com")
    enroll_participant(study["id"], pa)
    pb = register_participant(email="kq-b@x.com", age_years=27)
    enroll_participant(study["id"], pb)
    build = create_released_build(study["id"], build_label="q1", max_keys=1)
    issue_key(build["id"], pa["id"])
    resp = api.create_access_key(
        {"build_id": build["id"], "participant_id": pb["id"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_KEY_QUOTA_EXCEEDED)


def test_duplicate_key_rejected(api):
    """PRD §3.4: "an existing key in `ISSUED` or `REDEEMED` blocks issuance
    with `ERR_DUPLICATE_KEY`, while an `EXPIRED` or `REVOKED` key does not."

    Design: Corner/validations/duplicate_key_rejected
    """
    ctx = setup_enrolled_participant(email="dk-p@x.com")
    build = create_released_build(ctx["study"]["id"], build_label="dk1", max_keys=5)
    issue_key(build["id"], ctx["participant"]["id"])
    resp = api.create_access_key(
        {"build_id": build["id"], "participant_id": ctx["participant"]["id"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY)


def test_redeem_at_exact_expiry_returns_key_expired(api):
    """PRD §3.4: "Redemption is owner-only (`ERR_FORBIDDEN` for anyone but the
    key's participant) and requires the key still `ISSUED` with the redemption
    instant strictly before `expires_at` — equality is expired and rejected
    with `ERR_KEY_EXPIRED`."

    Design: Corner/validations/redeem_at_exact_expiry_returns_key_expired
    """
    set_clock("2026-08-01T00:00:00Z")
    ctx = setup_enrolled_participant(email="ke-p@x.com")
    build = create_released_build(ctx["study"]["id"], build_label="ke1",
                                  max_keys=5, key_ttl_hours=72)
    key = issue_key(build["id"], ctx["participant"]["id"])
    set_clock("2026-08-04T00:00:00Z")  # exactly expires_at
    resp = api.redeem_access_key(key["id"],
                                 make_participant_headers(ctx["participant"]["id"]))
    validate_error(resp, ApiErrorId.ERR_KEY_EXPIRED)
    current = get_success_data(api.get_access_key(key["id"], ADMIN))
    assert current["status"] == "ISSUED", (
        "a rejected redeem changes nothing; only the sweep flips the key")


def test_expiry_sweep_boundary_expires_keys_then_signatures(api):
    """PRD §2.4: "Each run expires every `PENDING` NDA signature whose
    `expires_at` is at or before the current logical instant — a signature
    whose `expires_at` equals the current instant expires — and every `ISSUED`
    access key whose `expires_at` is at or before the current instant, with the
    same boundary rule. Each expired key appends a `KEY_EXPIRED` record to the
    exposure journal and decrements the owning build's `keys_active_count` by
    one; expired signatures have no further side effects. The sweep response
    reports how many of each resource it processed via `signatures_expired` and
    `keys_expired`."

    Design: Corner/validations/expiry_sweep_boundary_expires_keys_then_signatures
    """
    set_clock("2026-08-01T00:00:00Z")
    study, nda = setup_study_with_published_nda(code="SW1")
    pa = register_participant(email="sw-a@x.com")
    enroll_participant(study["id"], pa)
    pb, app_b = _approved_participant(study["id"], "sw-b@x.com")
    sig_b = get_pending_signature(pb["id"])
    build = create_released_build(study["id"], build_label="sw1", max_keys=5,
                                  key_ttl_hours=72)
    key = issue_key(build["id"], pa["id"])
    # Key issued at 2026-08-01T00:00:00Z + 72h expires 2026-08-04T00:00:00Z.
    set_clock("2026-08-04T00:00:00Z")
    sweep1 = run_expiry_sweep()
    assert sweep1["keys_expired"] == 1, "at the key's exact expiry the key flips"
    assert sweep1["signatures_expired"] == 0, (
        "the signature's deadline (T0 + 7 days) is still ahead")
    assert get_success_data(api.get_access_key(key["id"], ADMIN))["status"] == "EXPIRED"
    assert get_build(build["id"])["keys_active_count"] == 0
    expired_records = list_exposures(participant_id=pa["id"], build_id=build["id"],
                                     event_type="KEY_EXPIRED")
    assert len(expired_records) == 1, "the expired key appended a KEY_EXPIRED record"
    # B's PENDING signature (created at T0, +7 days) expires 2026-08-08T00:00:00Z.
    set_clock("2026-08-08T00:00:00Z")
    sweep2 = run_expiry_sweep()
    assert sweep2["signatures_expired"] == 1
    assert sweep2["keys_expired"] == 0, "no ISSUED keys remain"
    sig_now = get_success_data(api.get_nda_signature(sig_b["id"], LEGAL))
    assert sig_now["status"] == "EXPIRED"
    app_now = get_success_data(api.get_application(app_b["id"], RESEARCHER))
    assert app_now["status"] == "APPROVED", (
        "signature expiry has no further side effects on the application")


class TestIssueRevokeConservesKeyPool:
    def _setup(self, api):
        ctx = setup_enrolled_participant(email="ci2-p@x.com")
        build = create_released_build(ctx["study"]["id"], build_label="3.1.0",
                                      max_keys=2)
        assert get_build(build["id"])["keys_active_count"] == 0
        return ctx, build

    def test_issue_then_revoke_restores_counter(self, api):
        """PRD §3.4: "Manual revocation by a `ResearchOpsAdmin` or
        `LegalCounsel` moves `ISSUED` → `REVOKED` with a `KEY_REVOKED` record
        and a one-count decrement"
        PRD §3.4: "The `keys_active_count` counter always reflects keys in
        `ISSUED` or `REDEEMED`."

        Design: Difficulty/compensating_invariant/issue_revoke_conserves_key_pool
        """
        ctx, build = self._setup(api)
        key = issue_key(build["id"], ctx["participant"]["id"])
        assert get_build(build["id"])["keys_active_count"] == 1, (
            "forward action: ISSUED enters the active set")
        revoked = get_success_data(api.revoke_access_key(key["id"], ADMIN))
        assert revoked["status"] == "REVOKED"
        assert get_build(build["id"])["keys_active_count"] == 0, (
            "issue + revoke leaves the pool unchanged")

    def test_issue_revoke_journal_and_reconciliation(self, api):
        """PRD §3.4: "appends a `KEY_ISSUED` record to the exposure journal"
        PRD §3.4: "Manual revocation by a `ResearchOpsAdmin` or `LegalCounsel`
        moves `ISSUED` → `REVOKED` with a `KEY_REVOKED` record and a one-count
        decrement"
        PRD §3.4: "The `keys_active_count` counter always reflects keys in
        `ISSUED` or `REDEEMED`."

        Design: Difficulty/compensating_invariant/issue_revoke_conserves_key_pool
        """
        ctx, build = self._setup(api)
        pid = ctx["participant"]["id"]
        key = issue_key(build["id"], pid)
        get_success_data(api.revoke_access_key(key["id"], ADMIN))
        records = list_exposures(participant_id=pid, build_id=build["id"])
        event_types = [r["event_type"] for r in records]
        assert sorted(event_types) == ["KEY_ISSUED", "KEY_REVOKED"], (
            "exactly one KEY_ISSUED and one KEY_REVOKED were journaled")
        for record in records:
            assert_exposure_record(record)
        still_active = get_success_data(api.list_access_keys(
            ADMIN, params={"build_id": build["id"], "status": "ISSUED"}))
        redeemed = get_success_data(api.list_access_keys(
            ADMIN, params={"build_id": build["id"], "status": "REDEEMED"}))
        assert len(still_active) + len(redeemed) == 0
        assert get_build(build["id"])["keys_active_count"] == 0


def test_exposure_record_is_append_only_without_version(api):
    """PRD §2.5: "The `ExposureRecord` is an append-only event journal: it
    carries `id` and `created_at` only — both `updated_at` and `version` are
    absent — because no endpoint ever mutates an exposure record."
    PRD §2.5: "each record holds `participant_id`, `build_id`, a denormalized
    `study_id` copied from the build, an `event_type` drawn from `KEY_ISSUED`,
    `KEY_REDEEMED`, `KEY_REVOKED`, and `KEY_EXPIRED`, and a `recorded_at`
    timestamp taken from the logical clock at the moment the event was
    recorded."

    Design: Corner/entities/exposure_record_immutability_no_version
    """
    ctx = setup_enrolled_participant(email="im1-p@x.com")
    build = create_released_build(ctx["study"]["id"], build_label="9.9.9", max_keys=5)
    issue_key(build["id"], ctx["participant"]["id"])
    records = list_exposures(participant_id=ctx["participant"]["id"],
                             build_id=build["id"])
    assert len(records) == 1
    record = records[0]
    assert_exposure_record(record)  # asserts id + created_at, NO updated_at/version
    assert record["event_type"] == "KEY_ISSUED"
    assert record["study_id"] == ctx["study"]["id"], (
        "study_id is denormalized from the build")


def test_cohort_summary_retention_across_builds(api):
    """PRD §3.4: "Only builds with `released_at` set appear — `STAGED` builds
    are excluded — ordered by `released_at` ascending with `created_at`
    ascending as the tie-break. For each build the summary reports
    `keys_issued`, the count of `KEY_ISSUED` journal records for that build,
    and `keys_redeemed`, the count of `KEY_REDEEMED` records. Retention is
    computed between adjacent builds in that order: for the first build, or
    whenever the immediately previous build issued zero keys,
    `retained_from_previous` and `retention_pct` are null; otherwise
    `retained_from_previous` is the number of distinct participants holding a
    `KEY_ISSUED` record on both the previous build and the current one, and
    `retention_pct` is that count divided by the previous build's
    `keys_issued`, multiplied by 100, and rounded half-up to two decimal
    places."

    Design: Corner/calculations/cohort_summary_retention_across_builds
    """
    set_clock("2026-08-01T00:00:00Z")
    study, _nda = setup_study_with_published_nda(code="CALC4")
    p1 = register_participant(email="calc4-a@x.com")
    enroll_participant(study["id"], p1)
    p2 = register_participant(email="calc4-b@x.com", age_years=27)
    enroll_participant(study["id"], p2)
    b1 = create_released_build(study["id"], build_label="b1", max_keys=10)
    k1 = issue_key(b1["id"], p1["id"])
    get_success_data(api.redeem_access_key(k1["id"], make_participant_headers(p1["id"])))
    issue_key(b1["id"], p2["id"])
    b2 = create_released_build(study["id"], build_label="b2", max_keys=10)
    issue_key(b2["id"], p1["id"])
    summary = validate_success(api.get_cohort_summary(study["id"], ADMIN))
    builds = summary["builds"]
    assert [b["build_id"] for b in builds] == [b1["id"], b2["id"]]
    first, second = builds
    assert first["keys_issued"] == 2 and first["keys_redeemed"] == 1
    assert first["retained_from_previous"] is None and first["retention_pct"] is None, (
        "the first released build has no predecessor")
    assert second["keys_issued"] == 1 and second["keys_redeemed"] == 0
    assert second["retained_from_previous"] == 1, "only P1 holds a key on both builds"
    assert second["retention_pct"] == pytest.approx(50.0, abs=0.01)
