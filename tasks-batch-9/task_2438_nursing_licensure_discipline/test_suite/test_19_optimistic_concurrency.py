"""The two version-guarded writes, and the counter that only writes advance."""
from test_helpers import (
    ANALYST,
    ApiClient,
    ApiErrorId,
    complaint_version,
    disciplinary_proceeding_payload,
    license_version,
    make_board_member_headers,
    renewal_application_payload,
    reread_complaint,
    reread_license,
    reread_renewal,
    seed_active_license,
    seed_proceeding,
    seed_referred_context,
    seed_renewal,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_replaying_a_pre_supersede_credential_version_is_a_stale_write(api: ApiClient):
    """PRD §2.8: "Creating a renewal filing requires `expected_license_version` as a
    mandatory input field carrying the `version` of the target credential that the
    client last observed."

    PRD §2.8: "If that value does not equal the credential's current `version`, the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    PRD §2.8: "A successful create advances the credential's `version` by one, which
    is what makes a repeat of the same request fail."

    PRD §3.4: "Because only one non-terminal filing may exist per credential, every
    other renewal filing on the same credential still at `DRAFT` or `SUBMITTED` is
    moved to `WITHDRAWN`, and each superseded filing's `fee_applied_cents` is added
    to the nurse's `fee_credit_cents` and then zeroed."

    Design: Corner/complexity_layers/stale_license_version_on_renewal_create_returns_stale_version
    """
    ctx = seed_active_license(api)
    stale_version = ctx["license"]["version"]
    assert stale_version == 1
    first = seed_renewal(api, ctx["license_id"], clock=None,
                        attested_practice_hours=1000)
    fresh_version = license_version(api, ctx["license_id"])
    assert fresh_version == 2, (
        f"The first create bumped the parent credential, got {fresh_version}"
    )

    refused = api.create_renewal_application(
        renewal_application_payload(ctx["license_id"], stale_version,
                                    attested_practice_hours=1100),
        ANALYST,
    )

    validate_error(refused, ApiErrorId.ERR_STALE_VERSION.value)
    rows, meta = validate_paginated(
        api.list_license_renewal_applications(ctx["license_id"], ANALYST)
    )
    assert meta["total_count"] == 1, (
        f"The refused write created no second filing, got {meta['total_count']}"
    )
    assert rows[0]["id"] == first["id"]
    assert rows[0]["renewal_status"] == "DRAFT", (
        "The predecessor was not superseded by a refused create"
    )
    assert reread_license(api, ctx["license_id"])["version"] == 2

    replayed = validate_success(
        api.create_renewal_application(
            renewal_application_payload(ctx["license_id"], fresh_version,
                                        attested_practice_hours=1100),
            ANALYST,
        ),
        201,
    )
    assert replayed["id"] != first["id"]
    assert reread_renewal(api, first["id"])["renewal_status"] == "WITHDRAWN", (
        "The refreshed create legitimately supersedes the DRAFT predecessor"
    )
    assert reread_license(api, ctx["license_id"])["version"] == 3


def test_a_stale_complaint_version_answers_before_the_state_check(api: ApiClient):
    """PRD §2.8: "Opening a disciplinary proceeding requires
    `expected_complaint_version` as a mandatory input field carrying the `version` of
    the referred complaint that the client last observed."

    PRD §2.8: "Both stale-version rejections happen before the state-machine check
    described in §2.11, so a request that is both stale and state-invalid reports
    `ERR_STALE_VERSION`."

    PRD §2.8: "A successful open advances the complaint's `version` by one."

    PRD §3.8: "The complaint moves from `REFERRED_FOR_HEARING` to
    `PROCEEDING_OPENED` and its `version` is advanced by one."

    Design: Corner/complexity_layers/stale_complaint_version_on_proceeding_open_returns_stale_version
    """
    ctx = seed_referred_context(api)
    stale_version = complaint_version(api, ctx["complaint_id"])
    first = seed_proceeding(api, ctx["complaint_id"])
    fresh_version = complaint_version(api, ctx["complaint_id"])
    assert fresh_version == stale_version + 1
    assert reread_complaint(api, ctx["complaint_id"])["status"] == "PROCEEDING_OPENED"

    refused = api.create_disciplinary_proceeding(
        disciplinary_proceeding_payload(
            ctx["complaint_id"], stale_version,
            seated_member_user_ids=["bm-c9d", "bm-c9e", "bm-c9f"],
            hearing_date="2026-09-20T00:00:00Z",
        ),
        make_board_member_headers("bm-c9"),
    )

    error = validate_error(refused, ApiErrorId.ERR_STALE_VERSION.value)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_STATE.value, (
        "The complaint is both a version behind and no longer referred; the version "
        "guard answers first"
    )
    rows, meta = validate_paginated(
        api.list_complaint_disciplinary_proceedings(ctx["complaint_id"],
                                                    make_board_member_headers())
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]

    validate_error(
        api.create_disciplinary_proceeding(
            disciplinary_proceeding_payload(
                ctx["complaint_id"], fresh_version,
                seated_member_user_ids=["bm-c9d", "bm-c9e", "bm-c9f"],
                hearing_date="2026-09-20T00:00:00Z",
            ),
            make_board_member_headers("bm-c9"),
        ),
        ApiErrorId.ERR_INVALID_STATE.value,
    )


def test_the_version_counter_moves_on_writes_only(api: ApiClient):
    """PRD §2.6: "`version` (integer): a counter that starts at 1 when the record is
    created and increments by exactly 1 on every mutation, including mutations that
    only touch derived fields."

    PRD §2.6: "Because derived fields count as mutations, a credential whose
    `open_encumbrance_count` is recomputed, or whose `multistate_privilege_status` is
    rewritten, has both its `updated_at` refreshed and its `version` advanced — which
    is precisely what makes the stale-view protections of §2.8 meaningful."

    PRD §3.3: "The result is written to three fields: `multistate_privilege_status`,
    which is one of `NOT_ELIGIBLE`, `SINGLE_STATE`, `MULTISTATE`, or
    `PRIVILEGE_REVOKED`; `privilege_variant`, which records whether
    `RESIDENCY_DECLARED` or `RESIDENCY_EVIDENCED` was used; and
    `privilege_basis_state`, which records the primary state of residence the
    determination resolved to."

    PRD §3.3: "If the candidate pool is empty — because the array is empty, or
    because every entry's `effective_date` is still in the future — the determination
    falls back to the nurse's `declared_primary_state`."

    Design: Corner/complexity_layers/license_version_increments_once_per_write_and_never_on_a_read
    """
    ctx = seed_active_license(api)
    assert ctx["license"]["version"] == 1

    first_read = validate_success(api.get_license(ctx["license_id"], ANALYST))
    first_write = validate_success(
        api.run_privilege_determination(ctx["license_id"],
                                        {"variant": "RESIDENCY_EVIDENCED"}, ANALYST)
    )
    second_read = validate_success(api.get_license(ctx["license_id"], ANALYST))
    second_write = validate_success(
        api.run_privilege_determination(ctx["license_id"],
                                        {"variant": "RESIDENCY_DECLARED"}, ANALYST)
    )

    assert first_read["version"] == 1, (
        f"A read is not a mutation, got {first_read['version']}"
    )
    assert first_write["version"] == 2
    assert second_read["version"] == 2, (
        f"Nor is the read between two writes, got {second_read['version']}"
    )
    assert second_write["version"] == 3
    assert first_write["privilege_variant"] == "RESIDENCY_EVIDENCED"
    assert second_write["privilege_variant"] == "RESIDENCY_DECLARED"

    guarded = validate_success(
        api.create_renewal_application(
            renewal_application_payload(ctx["license_id"], second_write["version"],
                                        attested_practice_hours=1000),
            ANALYST,
        ),
        201,
    )
    assert guarded["license_id"] == ctx["license_id"], (
        "A client holding the post-write counter may still perform a guarded create"
    )
    final = reread_license(api, ctx["license_id"])
    assert final["version"] == 4
    assert final["multistate_privilege_status"] == "MULTISTATE", (
        "With no residency documents on file both variants fall back to the "
        "declared state, which is the issuing board's own"
    )
