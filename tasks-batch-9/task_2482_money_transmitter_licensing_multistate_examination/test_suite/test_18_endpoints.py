"""Endpoint round trips: creates, single reads, filtered lists, computed reads,
action dispatch and a conditionally admissible decision.

Every test drives a live server through PRD-declared endpoints only. The runner
restarts the server before each test, so the database starts empty and the logical
clock starts at 2026-08-01T00:00:00Z.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from test_helpers import MoneyTransmitterApiClient
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_LICENSE_NOT_ACTIVE, ERR_LICENSE_TERMINAL
from test_helpers.test_users import (
    CHIEF_HEADERS,
    MANAGER_HEADERS,
    OFFICER_HEADERS,
    make_state_regulator_headers,
)


def test_delegate_create_read_and_filtered_list_round_trip(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """A freshly appointed delegate reads back unchanged and the roster filters partition it.

    PRD 3.6: "A `LicensingManager` appoints an agent by creating a `Delegate` under a `licensee_id` with the agent's `legal_name` and a `delegate_type` of either `AGENT` or `AUTHORIZED_DELEGATE`."
    PRD 3.6: "Crucially, `oversight_score` starts null and `last_oversight_review_at` starts null, so a freshly appointed delegate cannot be put to work until someone has actually reviewed it."
    PRD 3.6: "`authorized_state_count` starts at zero and `oversight_hold`, the flag that records that every one of the delegate's authorizations has been suspended by a posture or licence cascade, starts false."
    PRD 2.3: "The delegate roster filters on `licensee_id` and `status`; the authorization register filters on `delegate_id`, `state_license_id` and `status`."
    PRD 2.3: "Unless a specific endpoint says otherwise, every list is sorted by `created_at` ascending."

    Design: Corner/endpoints/delegate_create_read_and_filtered_list_round_trip
    """
    first = validate_success(
        api.create_delegate(
            F.delegate_payload(
                licensee["id"],
                legal_name=C.SEED_DELEGATE_NAME,
                delegate_type="AUTHORIZED_DELEGATE",
            ),
            MANAGER_HEADERS,
        ),
        201,
    )
    A.assert_audit_stamps(first)
    assert first["version"] == 1
    assert first["licensee_id"] == licensee["id"]
    assert first["legal_name"] == C.SEED_DELEGATE_NAME
    assert first["delegate_type"] == "AUTHORIZED_DELEGATE"
    assert first["status"] == "ONBOARDING"
    assert first["oversight_score"] is None
    assert first["last_oversight_review_at"] is None
    assert first["authorized_state_count"] == 0
    assert first["oversight_hold"] is False

    second = validate_success(
        api.create_delegate(
            F.delegate_payload(
                licensee["id"], legal_name="Copper Kettle Grocery", delegate_type="AGENT"
            ),
            MANAGER_HEADERS,
        ),
        201,
    )
    assert second["delegate_type"] == "AGENT"
    assert second["status"] == "ONBOARDING"

    # A second licensee's agent must never leak into the first licensee's roster.
    other_licensee = fx.create_licensee(
        api, legal_name="Cascade Remit Corp", ein="741100002"
    )
    outsider = fx.create_delegate(api, other_licensee["id"], legal_name="Outside Agent LLC")

    read_back = validate_success(api.get_delegate(first["id"], MANAGER_HEADERS))
    assert read_back == first

    onboarding, meta = validate_paginated(
        api.list_delegates(
            MANAGER_HEADERS, params={"licensee_id": licensee["id"], "status": "ONBOARDING"}
        )
    )
    assert [row["id"] for row in onboarding] == [first["id"], second["id"]]
    assert outsider["id"] not in [row["id"] for row in onboarding]
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert meta["limit"] == 10  # PRD 2.3 default
    assert meta["offset"] == 0

    active, active_meta = validate_paginated(
        api.list_delegates(
            MANAGER_HEADERS, params={"licensee_id": licensee["id"], "status": "ACTIVE"}
        )
    )
    assert active == []
    assert active_meta["total_count"] == 0


def test_financials_patch_replaces_net_worth_and_bumps_the_version(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """The financials patch overwrites the reported figure and moves the version by one.

    PRD 3.1: "A freshly created licensee starts with `version` at 1, `coverage_posture` at `COMPLIANT`, `coverage_ratio_bps` at 10000 — vacuously perfect, since there are no obligations yet — `control_chain_status` at `VERIFIED`, and every counter at zero: `aggregate_outstanding_obligations_cents`, `eligible_investment_value_cents`, `book_investment_value_cents`, `consecutive_failed_test_count` and `active_license_count`."
    PRD 3.1: "Refreshing the financial statement is its own operation: a `LicensingManager` supplies a new `reported_tangible_net_worth_cents` and `net_worth_statement_date`, and the licensee's `version` is bumped."
    PRD 2.4: "Almost every resource additionally carries an `updated_at` — refreshed on every mutation, in the same format — and a `version`, an integer that starts at 1 on creation and increments by one on every mutation of that row."

    Design: Corner/endpoints/financials_patch_replaces_net_worth_and_bumps_the_version
    """
    assert licensee["version"] == 1
    assert licensee["reported_tangible_net_worth_cents"] == 500_000_000
    assert licensee["aggregate_outstanding_obligations_cents"] == 0

    patched = validate_success(
        api.update_licensee_financials(
            licensee["id"],
            F.financials_payload(
                reported_tangible_net_worth_cents=60_000_000,
                net_worth_statement_date="2026-07-31T00:00:00Z",
            ),
            MANAGER_HEADERS,
        )
    )
    A.assert_audit_stamps(patched)
    # A replacement, not an accumulation: 60,000,000 rather than 500,000,000 + 60,000,000.
    assert patched["reported_tangible_net_worth_cents"] == 60_000_000
    assert patched["net_worth_statement_date"][:19] == "2026-07-31T00:00:00"
    A.assert_version_bumped(licensee, patched)
    assert patched["version"] == 2
    assert patched["aggregate_outstanding_obligations_cents"] == 0

    read_back = fx.get_licensee(api, licensee["id"])
    assert read_back == patched


def test_coverage_summary_is_a_pure_computed_read(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """The coverage summary recomputes both variants on read and writes nothing.

    PRD 3.7: "The `BOOK_VALUE` variant is the generous one: `book_investment_value_cents` is simply the sum of `book_value_cents` over the candidate set."
    PRD 3.7: "First, the concentration cap is fixed for this licensee as its `aggregate_outstanding_obligations_cents` multiplied by 1000 basis points — ten percent — divided by 10000 and rounded down; that figure is exposed as `concentration_cap_cents`."
    PRD 3.7: "Every other holding contributes an adjusted amount equal to its `market_value_cents` multiplied by 10000 minus its class haircut, divided by 10000 and rounded down at that step."
    PRD 3.7: "The haircuts, in basis points, are: `CASH` none, `US_TREASURY` 200, `MONEY_MARKET_FUND` 300, `AGENCY_BOND` 500 and `RECEIVABLE_FROM_DELEGATE` 1000."
    PRD 3.7: "A coverage ratio in basis points is derived from an investment value the same way for both variants: it is exactly 10000 when the licensee's `aggregate_outstanding_obligations_cents` is zero, and otherwise the investment value multiplied by 10000, divided by the obligations, rounded down."
    PRD 3.7: "From it, and from `consecutive_failed_test_count`, the licensee's `coverage_posture` is determined by a strictly ordered test: the posture is `FROZEN` if `consecutive_failed_test_count` is at least 2, regardless of the ratio; otherwise `COMPLIANT` if `coverage_ratio_bps` is at least 10000; otherwise `WATCH` if `coverage_ratio_bps` is at least 9500; otherwise `DEFICIENT`."
    PRD 3.7: "A licensee-level coverage read exposes both variants side by side over identical holdings — `obligations_cents`, `book_investment_value_cents`, `book_coverage_ratio_bps`, `eligible_investment_value_cents`, `coverage_ratio_bps`, `concentration_cap_cents`, `coverage_posture` and `consecutive_failed_test_count` — so that the divergence is observable in a single response."

    Design: Corner/endpoints/coverage_summary_is_a_pure_computed_read
    """
    licensee_id = active_license.licensee_id
    fx.record_holding(api, licensee_id, "CASH", "First Republic Trust", 2_000_000, 2_000_000)
    fx.record_holding(api, licensee_id, "US_TREASURY", "US Treasury Direct", 2_000_000, 2_000_000)
    fx.adjust_obligations(api, active_license.license_id, 4_000_000)

    before = fx.get_licensee(api, licensee_id)
    assert before["aggregate_outstanding_obligations_cents"] == 4_000_000
    assert before["coverage_ratio_bps"] == 9900  # the ELIGIBLE_MARKET ratio, never the book one
    assert before["coverage_posture"] == "WATCH"

    summary = validate_success(api.get_coverage_summary(licensee_id, CHIEF_HEADERS))
    assert summary["obligations_cents"] == 4_000_000
    # Book variant: 2,000,000 cash + 2,000,000 treasury, no haircut at all.
    assert summary["book_investment_value_cents"] == 4_000_000
    assert summary["book_coverage_ratio_bps"] == 10000  # 4,000,000 * 10000 / 4,000,000
    # Eligible variant: cash 2,000,000 plus treasury 2,000,000 * 9800 / 10000 = 1,960,000.
    assert summary["eligible_investment_value_cents"] == 3_960_000
    assert summary["coverage_ratio_bps"] == 9900  # 3,960,000 * 10000 / 4,000,000, floored
    assert summary["concentration_cap_cents"] == 400_000  # 4,000,000 * 1000 / 10000
    assert summary["coverage_posture"] == "WATCH"  # 9900 is below 10000 but at least 9500
    assert summary["consecutive_failed_test_count"] == 0

    after = fx.get_licensee(api, licensee_id)
    A.assert_version_unchanged(before, after)
    A.assert_fields_unchanged(
        before,
        after,
        (
            "updated_at",
            "coverage_ratio_bps",
            "coverage_posture",
            "aggregate_outstanding_obligations_cents",
            "eligible_investment_value_cents",
            "book_investment_value_cents",
        ),
    )


def test_authorization_creation_links_one_delegate_to_one_state_license(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """The junction row is reachable from both ends and moves no counter before activation.

    PRD 3.6: "The appointment is made concrete per state by a `DelegateAuthorization`, which pairs a `delegate_id` with a `state_license_id` and defines a period and a limit: `effective_date` is the first day of the authorization period, `expiry_date` is the last day and may not precede the effective date, and `monthly_volume_cap_cents` is the contractual monthly transmission cap, which must be strictly greater than zero."
    PRD 3.6: "A new authorization starts in `PENDING_OVERSIGHT` and moves no counter — only activation makes a delegate count against the bond."
    PRD 3.6: "The remaining statuses are `ACTIVE`, `SUSPENDED_BY_POSTURE`, `SUSPENDED` and the terminal `TERMINATED`; `activated_at` and `oversight_score_at_activation` both start null."
    PRD 2.3: "The delegate roster filters on `licensee_id` and `status`; the authorization register filters on `delegate_id`, `state_license_id` and `status`."

    Design: Corner/endpoints/authorization_creation_links_one_delegate_to_one_state_license
    """
    license_before = fx.get_license(api, active_license.license_id)
    assert license_before["active_delegate_count"] == 0
    # California: tier-one bond 2,500,000 lifted to the 5,000,000 statutory base bond.
    assert license_before["bond_requirement_cents"] == 5_000_000

    delegate = fx.create_delegate(api, active_license.licensee_id)
    validate_success(
        api.submit_oversight_review(
            delegate["id"],
            F.oversight_review_payload(90, 90, 70),
            OFFICER_HEADERS,
        )
    )

    created = validate_success(
        api.create_delegate_authorization(
            F.delegate_authorization_payload(
                delegate["id"],
                active_license.license_id,
                "2026-09-01T00:00:00Z",
                "2027-08-31T00:00:00Z",
            ),
            MANAGER_HEADERS,
        ),
        201,
    )
    A.assert_audit_stamps(created)
    assert created["version"] == 1
    assert created["delegate_id"] == delegate["id"]
    assert created["state_license_id"] == active_license.license_id
    assert created["monthly_volume_cap_cents"] == C.SEED_MONTHLY_CAP_CENTS
    assert created["effective_date"][:19] == "2026-09-01T00:00:00"
    assert created["expiry_date"][:19] == "2027-08-31T00:00:00"
    assert created["status"] == "PENDING_OVERSIGHT"
    assert created["activated_at"] is None
    assert created["oversight_score_at_activation"] is None

    read_back = validate_success(
        api.get_delegate_authorization(created["id"], MANAGER_HEADERS)
    )
    assert read_back == created

    by_delegate, by_delegate_meta = validate_paginated(
        api.list_delegate_authorizations(
            MANAGER_HEADERS, params={"delegate_id": delegate["id"]}
        )
    )
    assert [row["id"] for row in by_delegate] == [created["id"]]
    assert by_delegate_meta["total_count"] == 1

    by_license, by_license_meta = validate_paginated(
        api.list_delegate_authorizations(
            MANAGER_HEADERS, params={"state_license_id": active_license.license_id}
        )
    )
    assert [row["id"] for row in by_license] == [created["id"]]
    assert by_license_meta["total_count"] == 1

    delegate_after = validate_success(api.get_delegate(delegate["id"], MANAGER_HEADERS))
    assert delegate_after["status"] == "ONBOARDING"
    assert delegate_after["authorized_state_count"] == 0

    license_after = fx.get_license(api, active_license.license_id)
    assert license_after["active_delegate_count"] == 0
    assert license_after["bond_requirement_cents"] == 5_000_000  # no delegate counts yet


def test_review_action_endpoint_dispatches_on_the_action_enum(
    api: MoneyTransmitterApiClient, ca_jurisdiction: dict, licensee: dict
) -> None:
    """One URL drives START_REVIEW then DENY, and a denial mints no licence.

    PRD 3.3: "A `StateRegulator` whose `X-User-ID` equals the application's `jurisdiction_id` posts a review `action` with an optional `note`."
    PRD 3.3: "The action `START_REVIEW` moves `SUBMITTED → UNDER_REVIEW` and refreshes `updated_at`."
    PRD 3.3: "The action `DENY` moves `UNDER_REVIEW → DENIED` with `denial_reason` recorded as `REGULATOR_DENIAL` and `decision_at` stamped."
    PRD 3.3: "Approval stamps `decision_at` and mints a licence."
    PRD 3.3: "`deficiency_round_count` is deliberately **not** reset: it is the loop counter that eventually forces the automatic denial, and an application may therefore bounce between `UNDER_REVIEW` and `DEFICIENT` at most three times."

    Design: Corner/endpoints/review_action_endpoint_dispatches_on_the_action_enum
    """
    application = fx.create_application(api, licensee["id"], ca_jurisdiction["id"])
    submitted = fx.submit_application(api, application["id"])
    assert submitted["status"] == "SUBMITTED"
    assert submitted["deficiency_round_count"] == 0

    fx.set_clock(api, "2026-08-05T12:00:00Z")
    regulator = make_state_regulator_headers(ca_jurisdiction["id"])

    under_review = validate_success(
        api.review_application(
            application["id"], F.review_action_payload("START_REVIEW"), regulator
        )
    )
    assert under_review["status"] == "UNDER_REVIEW"
    A.assert_version_bumped(submitted, under_review)
    assert under_review.get("decision_at") is None  # START_REVIEW decides nothing

    denied = validate_success(
        api.review_application(
            application["id"],
            F.review_action_payload("DENY", note="Insufficient AML controls."),
            regulator,
        )
    )
    assert denied["status"] == "DENIED"
    assert denied["denial_reason"] == "REGULATOR_DENIAL"
    assert denied["decision_at"][:19] == "2026-08-05T12:00:00"  # the logical clock
    assert denied["deficiency_round_count"] == 0  # DENY is not a deficiency round
    A.assert_version_bumped(under_review, denied)

    read_back = validate_success(api.get_application(application["id"], MANAGER_HEADERS))
    assert read_back == denied

    licenses, license_meta = validate_paginated(
        api.list_state_licenses(MANAGER_HEADERS, params={"licensee_id": licensee["id"]})
    )
    assert licenses == []
    assert license_meta["total_count"] == 0
    assert fx.get_licensee(api, licensee["id"])["active_license_count"] == 0


def test_surrender_decision_is_available_only_while_a_request_is_pending(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """A surrender decision is admissible only out of SURRENDER_REQUESTED, and only once.

    PRD 2.7: "**Entity state admissibility**, in this order: application status (`ERR_APPLICATION_INVALID_STATE`), licence authorisation status (`ERR_LICENSE_NOT_ACTIVE`), licence terminality (`ERR_LICENSE_TERMINAL`), coverage-test status (`ERR_TEST_INVALID_STATE`), authorization status (`ERR_AUTHORIZATION_INVALID_STATE`), examination status (`ERR_EXAM_INVALID_STATE`), information-request status (`ERR_INFO_REQUEST_INVALID_STATE`), enforcement status (`ERR_ENFORCEMENT_INVALID_STATE`), control-person status (`ERR_CONTROL_PERSON_INVALID_STATE`)."
    PRD 2.8: "Only `license_status` reaching `SURRENDERED` or `REVOKED` stops filings altogether, and any attempt to mutate such a licence — including filing a call report against it, running any licence-level operation on it, or issuing a new enforcement action against it — is rejected with `ERR_LICENSE_TERMINAL`."
    PRD 3.4: "On success the licence moves to `SURRENDER_REQUESTED`, `expansion_gate` is set to `BLOCKED`, `version` is bumped, and `active_license_count` is reduced by one — but only when the prior status was `ACTIVE`; surrendering an already-suspended licence moves no counter, because the suspension already decremented it."
    PRD 3.4: "The regulator of record then decides."
    PRD 3.4: "A `decision` of `APPROVED`, with an optional `rationale`, moves `SURRENDER_REQUESTED → SURRENDERED`, which is terminal, sets `bond_status` to `CANCELLED`, drives every non-`TERMINATED` `DelegateAuthorization` of the licence to `TERMINATED`, decrements the licensee's `active_license_count`, and — because the licence has left the aggregate set — recomputes the licensee's `aggregate_outstanding_obligations_cents`, `coverage_ratio_bps` and `coverage_posture`."

    Design: Corner/endpoints/surrender_decision_is_available_only_while_a_request_is_pending
    """
    license_id = active_license.license_id
    regulator = make_state_regulator_headers(active_license.jurisdiction_id)

    before = fx.get_license(api, license_id)
    A.assert_license_state(before, license_status="ACTIVE", bond_status="POSTED")
    assert before["outstanding_obligations_cents"] == 0
    assert fx.get_licensee(api, active_license.licensee_id)["active_license_count"] == 1

    premature = api.decide_surrender(
        license_id,
        F.surrender_decision_payload("APPROVED", rationale="Premature decision."),
        regulator,
    )
    validate_error(premature, ERR_LICENSE_NOT_ACTIVE)

    unmoved = fx.get_license(api, license_id)
    A.assert_license_state(unmoved, license_status="ACTIVE", bond_status="POSTED")
    A.assert_version_unchanged(before, unmoved)
    assert fx.get_licensee(api, active_license.licensee_id)["active_license_count"] == 1

    requested = validate_success(
        api.request_surrender(
            license_id,
            F.surrender_request_payload(
                unmoved["version"], effective_date="2026-09-30T00:00:00Z"
            ),
            MANAGER_HEADERS,
        )
    )
    assert requested["license_status"] == "SURRENDER_REQUESTED"
    assert requested["expansion_gate"] == "BLOCKED"
    A.assert_version_bumped(unmoved, requested)
    # The request itself decrements the count because the prior status was ACTIVE.
    assert fx.get_licensee(api, active_license.licensee_id)["active_license_count"] == 0

    decided = validate_success(
        api.decide_surrender(
            license_id,
            F.surrender_decision_payload("APPROVED", rationale="Wind-down plan accepted."),
            regulator,
        )
    )
    assert decided["license_status"] == "SURRENDERED"
    assert decided["bond_status"] == "CANCELLED"
    A.assert_version_bumped(requested, decided)

    # A second decision has nothing left to decide. PRD 2.8 names
    # ERR_LICENSE_TERMINAL for a mutation of a SURRENDERED licence, while the
    # PRD 2.7 ladder places the authorisation-status band
    # (ERR_LICENSE_NOT_ACTIVE) above the terminality band, and this decision
    # is admissible only from SURRENDER_REQUESTED. Both bands are violated, so
    # either error is a faithful reading.
    repeated = api.decide_surrender(
        license_id,
        F.surrender_decision_payload("DENIED", rationale="Change of heart."),
        regulator,
    )
    validate_error_is_one_of(repeated, [ERR_LICENSE_TERMINAL, ERR_LICENSE_NOT_ACTIVE])

    final = fx.get_license(api, license_id)
    assert final["license_status"] == "SURRENDERED"
    assert final["bond_status"] == "CANCELLED"
    A.assert_version_unchanged(decided, final)
