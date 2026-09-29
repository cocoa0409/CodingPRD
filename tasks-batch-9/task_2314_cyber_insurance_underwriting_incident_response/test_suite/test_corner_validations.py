"""Validation corner cases on the underwriting side of the file.

Every test builds the whole world it needs from scratch through the public API:
the control catalog, the insured account, the application, the attestations, the
scan and the quote. The harness restarts the server with an empty database
before each test, so nothing is shared.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    ADJUSTER_HEADERS,
    UNDERWRITER_2_HEADERS,
    UNDERWRITER_HEADERS,
    ErrorId,
    constants as C,
    factories as F,
    fixtures,
)
from test_helpers.assertions import (
    assert_money,
    assert_score_2dp,
    get_total_count,
)

# The scan contradicts the applicant on one control only: EMAIL_FILTERING is
# attested FULL but observed PARTIAL, so the verified basis lands on 87.50.
EMAIL_FILTERING_PARTIAL = [F.scan_finding("EMAIL_FILTERING", "HIGH", "PARTIAL")]

# The bindable premium of the Aurora Health application built by `_quoted_aurora`
# below: a 9,000 healthcare base rate at revenue tier 1.00 over 3.4 layer units
# is a 30,600.00 gross premium, and a verified score of 87.50 (-0.05), a 250,000
# retention (-0.10) and a CSP_ALPHA dependency (+0.08) multiply it by 0.93.
AURORA_PREMIUM_USD = 28458.00


def _quoted_aurora(api, **overrides):
    """Catalog, Aurora Health account, application, attestations, scan, quote."""
    fixtures.set_clock(api, C.DEFAULT_CLOCK)
    return fixtures.quoted_application(
        api,
        account_spec=C.ACCOUNT_AURORA,
        attestations=C.ATTEST_95,
        findings=EMAIL_FILTERING_PARTIAL,
        **overrides,
    )


def test_second_attestation_for_the_same_control_is_refused(api):
    """PRD §3.2: "Only one attestation may exist for a given application and control pairing; a second is refused with `ERR_DUPLICATE_ATTESTATION`."
    PRD §3.2: "Each attestation write recomputes the application's `attested_control_score` and increments the application's `version` by 1."

    Design: Corner/validations/second_attestation_for_the_same_control_returns_422
    """
    fixtures.set_clock(api, C.DEFAULT_CLOCK)
    fixtures.seed_catalog(api)
    account = fixtures.create_account(api, C.ACCOUNT_AURORA)
    application = fixtures.create_application(api, account["id"])
    fixtures.attest_controls(api, application["id"], {"MFA_PRIVILEGED": "FULL"})

    response = api.create_control_attestation(
        application["id"],
        F.control_attestation_payload("MFA_PRIVILEGED", "PARTIAL"),
        UNDERWRITER_HEADERS,
    )
    validate_error(response, ErrorId.DUPLICATE_ATTESTATION)

    rows, meta = validate_paginated(
        api.list_application_control_attestations(application["id"], UNDERWRITER_HEADERS)
    )
    assert meta["total_count"] == 1, (
        f"the refused attestation must not be stored: total_count {meta['total_count']}"
    )
    assert rows[0]["control_key"] == "MFA_PRIVILEGED"
    assert rows[0]["attested_level"] == "FULL", (
        f"the first attestation must survive: {rows[0]['attested_level']}"
    )

    after = fixtures.read_application(api, application["id"])
    assert_score_2dp(after["attested_control_score"], 30.00, "attested_control_score")
    assert after["version"] == 2, (
        f"only the accepted attestation may bump the version: {after['version']}"
    )


def test_aggregate_limit_off_the_increment_is_refused(api):
    """PRD §3.2: "Those two rules fail differently and the distinction matters: a figure below the 250,000 floor is a schema violation reported as `ERR_INVALID_REQUEST`, whereas a figure at or above the floor that is not a whole multiple of the 250,000 increment — 300,000, say — is refused later in the sequence with `ERR_INVALID_LIMIT_INCREMENT`."

    Design: Corner/validations/aggregate_limit_off_the_increment_returns_422
    """
    fixtures.set_clock(api, C.DEFAULT_CLOCK)
    fixtures.seed_catalog(api)
    account = fixtures.create_account(api, C.ACCOUNT_AURORA)

    # 5,100,000 clears the 250,000 floor and is a positive whole number, so the
    # schema layer has nothing to say about it.
    response = api.create_application(
        F.application_payload(
            account["id"],
            requested_aggregate_limit_usd=5100000,
            requested_retention_usd=250000,
            dependent_bi_definition="NAMED_PLUS_SUPPLY_CHAIN",
        ),
        UNDERWRITER_HEADERS,
    )
    validate_error(response, ErrorId.INVALID_LIMIT_INCREMENT)

    assert get_total_count(api.list_applications(UNDERWRITER_HEADERS)) == 0, (
        "no application row may survive a refused opening"
    )


def test_bind_without_a_first_party_response_section_is_refused(api):
    """PRD §3.5: "Structurally the tower must include a `FIRST_PARTY_RESPONSE` section and must not repeat a `section_key` or an `erosion_priority`; any of those three faults is `ERR_INVALID_TOWER_STRUCTURE`."

    Design: Corner/validations/tower_without_a_first_party_response_section_returns_422
    """
    chain = _quoted_aurora(api)
    application = chain["application"]

    tower = [
        {
            "section_key": "BUSINESS_INTERRUPTION",
            "sublimit_usd": 2000000,
            "waiting_period_hours": 12,
            "coinsurance_pct": 0.1,
            "erosion_priority": 20,
        }
    ]
    response = api.bind_application(
        application["id"],
        F.bind_payload(
            application["version"],
            coverage_sections=tower,
            named_dependency_keys=["CSP_ALPHA"],
        ),
        UNDERWRITER_2_HEADERS,
    )
    validate_error(response, ErrorId.INVALID_TOWER_STRUCTURE)

    assert (
        get_total_count(
            api.list_policies(
                UNDERWRITER_HEADERS, params={"application_id": application["id"]}
            )
        )
        == 0
    ), "a refused bind must mint no policy"

    after = fixtures.read_application(api, application["id"])
    assert after["status"] == "QUOTED", f"application status drifted to {after['status']}"
    assert_money(after["premium_usd"], AURORA_PREMIUM_USD, "premium_usd")
    assert after["version"] == application["version"], (
        f"version moved from {application['version']} to {after['version']}"
    )


def test_bind_with_a_duplicate_erosion_priority_is_refused(api):
    """PRD §3.5: "Structurally the tower must include a `FIRST_PARTY_RESPONSE` section and must not repeat a `section_key` or an `erosion_priority`; any of those three faults is `ERR_INVALID_TOWER_STRUCTURE`."
    PRD §3.5: "`erosion_priority` is an integer of at least 1 and at most 99 that fixes the section's place in the allocation order, ascending, and must be unique within the policy."

    Design: Corner/validations/duplicate_erosion_priority_in_the_tower_returns_422
    """
    chain = _quoted_aurora(api)
    application = chain["application"]

    tower = [
        {
            "section_key": "FIRST_PARTY_RESPONSE",
            "sublimit_usd": 1000000,
            "waiting_period_hours": None,
            "coinsurance_pct": 0.0,
            "erosion_priority": 10,
        },
        {
            "section_key": "THIRD_PARTY_LIABILITY",
            "sublimit_usd": 3000000,
            "waiting_period_hours": None,
            "coinsurance_pct": 0.0,
            "erosion_priority": 10,
        },
    ]
    response = api.bind_application(
        application["id"],
        F.bind_payload(
            application["version"],
            coverage_sections=tower,
            named_dependency_keys=["CSP_ALPHA"],
        ),
        UNDERWRITER_2_HEADERS,
    )
    validate_error(response, ErrorId.INVALID_TOWER_STRUCTURE)

    assert (
        get_total_count(
            api.list_policies(
                UNDERWRITER_HEADERS, params={"application_id": application["id"]}
            )
        )
        == 0
    ), "a refused bind must mint no policy"
    assert get_total_count(api.list_coverage_sections(UNDERWRITER_HEADERS)) == 0, (
        "no tower section may be created by a refused bind"
    )

    after = fixtures.read_application(api, application["id"])
    assert after["status"] == "QUOTED", f"application status drifted to {after['status']}"
    assert after["version"] == application["version"], (
        f"version moved from {application['version']} to {after['version']}"
    )


def test_bind_with_a_sublimit_above_the_aggregate_is_refused(api):
    """PRD §3.5: "Fiscally, the sum of `sublimit_usd` across the `BUSINESS_INTERRUPTION` and `DEPENDENT_BI` sections must not exceed the policy aggregate, and no single section's `sublimit_usd` may exceed it either; a breach is `ERR_SUBLIMIT_EXCEEDS_AGGREGATE`."
    PRD §2.10: "15. **Money and limit constraints, checked last** (422) — `ERR_RATE_EXCEEDS_PRE_APPROVED`, `ERR_AUTHORIZED_HOURS_EXCEEDED`, `ERR_SUBLIMIT_EXCEEDS_AGGREGATE`, `ERR_INVALID_LIMIT_INCREMENT`, and `ERR_AGGREGATE_LIMIT_EXHAUSTED`."

    Design: Corner/validations/business_interruption_sublimit_above_the_aggregate_returns_422
    """
    chain = _quoted_aurora(api)
    application = chain["application"]

    # Structurally sound — FIRST_PARTY_RESPONSE is present and the priorities are
    # distinct — but the BI sublimit is larger than the 5,000,000 aggregate.
    tower = [
        {
            "section_key": "FIRST_PARTY_RESPONSE",
            "sublimit_usd": 1000000,
            "waiting_period_hours": None,
            "coinsurance_pct": 0.0,
            "erosion_priority": 10,
        },
        {
            "section_key": "BUSINESS_INTERRUPTION",
            "sublimit_usd": 6000000,
            "waiting_period_hours": 12,
            "coinsurance_pct": 0.1,
            "erosion_priority": 20,
        },
    ]
    response = api.bind_application(
        application["id"],
        F.bind_payload(
            application["version"],
            coverage_sections=tower,
            named_dependency_keys=["CSP_ALPHA"],
        ),
        UNDERWRITER_2_HEADERS,
    )
    validate_error(response, ErrorId.SUBLIMIT_EXCEEDS_AGGREGATE)

    assert (
        get_total_count(
            api.list_policies(
                UNDERWRITER_HEADERS, params={"application_id": application["id"]}
            )
        )
        == 0
    ), "a refused bind must mint no policy"

    after = fixtures.read_application(api, application["id"])
    assert after["status"] == "QUOTED", f"application status drifted to {after['status']}"


def test_unauthorized_role_outranks_an_unknown_application_id(api):
    """PRD §2.1: "This check runs before any identifier in the URL is resolved, so an unauthorised role calling an endpoint with a path id that does not exist still receives 403, never 404."
    PRD §2.10: "2. **Role authorisation** — `X-User-Role` is one of the five declared roles and is permitted for this endpoint; otherwise `ERR_UNAUTHORIZED` (403). Raised before any path identifier is resolved."
    PRD §2.10: "3. **Path existence** — every identifier in the URL resolves, left to right, as described in §2.9; otherwise the matching 404."

    Design: Corner/validations/unauthorized_role_outranks_an_unknown_path_id_returns_403
    """
    fixtures.set_clock(api, C.DEFAULT_CLOCK)
    fixtures.seed_catalog(api)
    fixtures.create_account(api, C.ACCOUNT_AURORA)

    # Quoting is an Underwriter operation, and no application carries this id.
    response = api.quote_application(
        NON_EXISTENT_UUID, F.quote_payload(1), ADJUSTER_HEADERS
    )
    validate_error(response, ErrorId.UNAUTHORIZED)

    assert get_total_count(api.list_applications(UNDERWRITER_HEADERS)) == 0, (
        "the refused call must not create an application"
    )


def test_stale_application_version_outranks_the_undraftable_state(api):
    """PRD §2.10: "When several checks could reject the same request, the order in which they are evaluated determines which error the client sees, and that order is fixed."
    PRD §2.10: "8. **Stale-read protection** — the declared version field carries the parent's current `version`, per §2.7; otherwise the matching 412."
    PRD §2.10: "9. **Own state** — the addressed row is in a state from which the requested transition is declared in §3; terminal states admit no transition at all."
    PRD §2.7: "`POST /cyber/applications/{application_id}/quote` requires `expected_application_version`, carrying the client's last observed `version` of the target `Application`. A mismatch is rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412)."

    Design: Corner/validations/stale_version_outranks_the_invalid_application_state_returns_412
    """
    fixtures.set_clock(api, C.DEFAULT_CLOCK)
    fixtures.seed_catalog(api)
    account = fixtures.create_account(api, C.ACCOUNT_AURORA)
    application = fixtures.create_application(api, account["id"])
    fixtures.attest_controls(api, application["id"], C.ATTEST_95)

    current = fixtures.read_application(api, application["id"])
    assert current["status"] == "DRAFT", (
        f"the application must still be DRAFT, not {current['status']}"
    )

    # The application is both unquotable (DRAFT) and addressed from a stale read.
    response = api.quote_application(
        application["id"], F.quote_payload(current["version"] - 1), UNDERWRITER_HEADERS
    )
    validate_error(response, ErrorId.STALE_APPLICATION_VERSION)

    after = fixtures.read_application(api, application["id"])
    assert after["status"] == "DRAFT", f"application status drifted to {after['status']}"
    assert after["version"] == current["version"], (
        f"version moved from {current['version']} to {after['version']}"
    )
    assert after.get("premium_usd") is None, (
        f"a refused quote must write no premium: {after.get('premium_usd')}"
    )
    assert after.get("quote_expires_at") is None, (
        f"a refused quote must set no expiry: {after.get('quote_expires_at')}"
    )
