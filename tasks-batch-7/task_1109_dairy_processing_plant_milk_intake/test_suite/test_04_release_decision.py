"""The release decision: SCC boundary, permit gating, state-vs-business
priority, OCC on the producer version, and immediate response consistency."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_producer,
    get_success_data,
    make_hauler,
    make_permit,
    make_producer,
    make_receipt,
    record_lab_result,
    release_receipt,
    set_clock,
    setup_intake_env,
    setup_releasable_receipt,
    setup_rejected_receipt,
    validate_error,
    validate_success,
)

PC = TEST_USERS["plant_controller_headers"]
QA = TEST_USERS["qa_manager_headers"]
SI = TEST_USERS["state_inspector_headers"]


class TestSccBoundary750000Exclusive:
    def test_scc_exactly_750000_rejected(self, api):
        """PRD §3.3: "The receipt's `scc_cells_per_ml` must be below 750000
        cells per millilitre, otherwise `ERR_SCC_EXCEEDED`." — 750000 is not
        below 750000, so release must fail.

        Design: Difficulty/boundary_precision_check/scc_boundary_750000_exclusive
        """
        env = setup_intake_env()
        receipt = setup_releasable_receipt(
            env["producer"]["id"], env["hauler"]["id"], scc=750000
        )
        producer = get_producer(env["producer"]["id"])
        res = api.release_tanker_receipt(
            receipt["id"], {"expected_producer_version": producer["version"]}, QA
        )
        validate_error(res, ApiErrorId.ERR_SCC_EXCEEDED)

    def test_scc_749999_released(self, api):
        """PRD §3.3: "The receipt's `scc_cells_per_ml` must be below 750000
        cells per millilitre, otherwise `ERR_SCC_EXCEEDED`." — 749999 is below
        the threshold, so with all other preconditions met the release succeeds.

        Design: Difficulty/boundary_precision_check/scc_boundary_750000_exclusive
        """
        env = setup_intake_env()
        receipt = setup_releasable_receipt(
            env["producer"]["id"], env["hauler"]["id"], scc=749999
        )
        released = release_receipt(receipt["id"], env["producer"]["id"])
        assert released["disposition"] == "RELEASED_FOR_PROCESSING"


class TestReleaseGatedOnPermit:
    def test_release_blocked_when_permit_under_review(self, api):
        """PRD §3.3: "And the plant's most recent `GradeAPermit` must be in
        `ACTIVE` `status` and not expired, otherwise `ERR_PERMIT_NOT_ACTIVE`."
        PRD §3.9: a failing inspection (score below 90) moves the permit "from
        `ACTIVE` to `UNDER_REVIEW`".

        Design: Difficulty/cross_entity_state_dependency/receipt_release_gated_on_permit
        """
        env = setup_intake_env()
        receipt = setup_releasable_receipt(env["producer"]["id"], env["hauler"]["id"])
        reviewed = get_success_data(
            api.record_inspection(
                env["permit"]["id"], {"inspection_score": 75, "violations_found": 3}, SI
            )
        )
        assert reviewed["status"] == "UNDER_REVIEW"

        producer = get_producer(env["producer"]["id"])
        res = api.release_tanker_receipt(
            receipt["id"], {"expected_producer_version": producer["version"]}, QA
        )
        validate_error(res, ApiErrorId.ERR_PERMIT_NOT_ACTIVE)

    def test_release_blocked_when_permit_expired(self, api):
        """PRD §3.3: "And the plant's most recent `GradeAPermit` must be in
        `ACTIVE` `status` and not expired, otherwise `ERR_PERMIT_NOT_ACTIVE`."
        The permit below expired before both the logical clock and the
        receipt's `arrived_at`.

        Design: Difficulty/cross_entity_state_dependency/receipt_release_gated_on_permit
        """
        env = setup_intake_env()
        # Replace the healthy permit with an already-expired one.
        expired = make_permit(
            permit_number="GA-EXPIRED",
            issued_at="2025-01-01T00:00:00Z",
            expires_at="2026-04-01T00:00:00Z",
        )
        assert expired["status"] == "ACTIVE"  # status flag alone does not cure expiry
        receipt = setup_releasable_receipt(env["producer"]["id"], env["hauler"]["id"])
        producer = get_producer(env["producer"]["id"])
        res = api.release_tanker_receipt(
            receipt["id"], {"expected_producer_version": producer["version"]}, QA
        )
        validate_error(res, ApiErrorId.ERR_PERMIT_NOT_ACTIVE)


class TestStateBeatsBusinessSafetyOnRelease:
    def test_state_error_beats_antibiotic_positive(self, api):
        """PRD §2.10: "The order, from first-evaluated to last, is:
        authentication presence (missing or malformed headers →
        `ERR_MISSING_AUTH`), then role authorization for the endpoint (→
        `ERR_UNAUTHORIZED_ROLE`), then path-existence resolution left-to-right
        (→ `ERR_NOT_FOUND`), then state-machine precondition (→
        `ERR_INVALID_STATE`), then the business-rule checks enumerated for that
        endpoint in §3, and finally any field-shape or enum-violation check (→
        `ERR_INVALID_INPUT`)." A REJECTED receipt whose antibiotic result is
        POSITIVE therefore reports `ERR_INVALID_STATE`, not
        `ERR_ANTIBIOTIC_POSITIVE`.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_release
        """
        env = setup_intake_env()
        # Rejected via antibiotic POSITIVE (business-safety evidence on record).
        receipt = setup_rejected_receipt(env["producer"]["id"], env["hauler"]["id"], antibiotic=5)
        assert receipt["disposition"] == "REJECTED"
        assert receipt["antibiotic_result"] == "POSITIVE"

        producer = get_producer(env["producer"]["id"])
        res = api.release_tanker_receipt(
            receipt["id"], {"expected_producer_version": producer["version"]}, QA
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_state_error_beats_scc_exceeded(self, api):
        """PRD §2.10: "then state-machine precondition (→ `ERR_INVALID_STATE`),
        then the business-rule checks enumerated for that endpoint in §3". A
        REJECTED receipt whose SCC result exceeded the threshold reports
        `ERR_INVALID_STATE`, not `ERR_SCC_EXCEEDED`.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_release
        """
        env = setup_intake_env()
        receipt = make_receipt(env["producer"]["id"], env["hauler"]["id"])
        record_lab_result(receipt["id"], "ANTIBIOTIC", 0)
        record_lab_result(receipt["id"], "SCC", 800000)
        rejected = get_success_data(api.reject_tanker_receipt(receipt["id"], {}, QA))
        assert rejected["disposition"] == "REJECTED"

        producer = get_producer(env["producer"]["id"])
        res = api.release_tanker_receipt(
            receipt["id"], {"expected_producer_version": producer["version"]}, QA
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_stale_producer_version_rejected(api):
    """PRD §2.7: "If the producer's current `version` does not match — because
    another writer has since advanced it, for example by rejecting a different
    tanker for the same producer and cascading `quality_flag` to `PROBATION` or
    `status` to `SUSPENDED` — the release is rejected with
    `ERR_STALE_PRODUCER_VERSION` (HTTP 412)."

    Design: Corner/validations/stale_producer_version_returns_412
    """
    env = setup_intake_env()
    pid = env["producer"]["id"]
    stale_version = get_producer(pid)["version"]

    # First release advances Producer.version (PRD §3.3).
    r1 = setup_releasable_receipt(pid, env["hauler"]["id"])
    release_receipt(r1["id"], pid)
    assert get_producer(pid)["version"] == stale_version + 1

    # Second release attempted with the stale pre-release version.
    r2 = setup_releasable_receipt(
        pid, env["hauler"]["id"], arrived_at="2026-05-06T08:00:00Z"
    )
    res = api.release_tanker_receipt(
        r2["id"], {"expected_producer_version": stale_version}, QA
    )
    validate_error(res, ApiErrorId.ERR_STALE_PRODUCER_VERSION)


def test_release_increments_producer_version(api):
    """PRD §3.3: "The producer's `version` is incremented by 1 — this is the
    mutation the OCC guard on release is designed to serialize against."

    Design: Corner/cross_cutting/occ_producer_version_increments_on_release
    """
    env = setup_intake_env()
    pid = env["producer"]["id"]
    assert env["producer"]["version"] == 1

    receipt = setup_releasable_receipt(pid, env["hauler"]["id"])
    release_receipt(receipt["id"], pid)

    after = get_producer(pid)
    assert after["version"] == 2, (
        f"release must increment Producer.version by exactly 1, got {after['version']}"
    )


def test_release_response_immediately_reflects_state(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field." PRD §3.3: "On a successful release, several cascades fire together.
    The receipt's `disposition` becomes `RELEASED_FOR_PROCESSING`".

    Design: Corner/consistency_model/release_response_reflects_new_state_immediately
    """
    env = setup_intake_env()
    receipt = setup_releasable_receipt(
        env["producer"]["id"], env["hauler"]["id"], gross=50000, tare=30000
    )
    producer = get_producer(env["producer"]["id"])
    res = api.release_tanker_receipt(
        receipt["id"], {"expected_producer_version": producer["version"]}, QA
    )
    body = validate_success(res, 200)
    assert body["disposition"] == "RELEASED_FOR_PROCESSING"
    assert body["net_weight_lbs"] == 20000
