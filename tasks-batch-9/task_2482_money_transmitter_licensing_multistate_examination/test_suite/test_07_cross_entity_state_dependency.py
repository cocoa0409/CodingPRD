"""Cross-entity state dependencies: one entity's own state is valid, yet the
operation is refused because a *different* entity is not in the state the
contract demands, and the identical call succeeds once that other entity moves.

Two dependency pairs are covered here. A `DelegateAuthorization` activation
depends on its `StateLicense`'s derived `expansion_gate`, which the reporting
dimension can block without touching the authorisation dimension. A
`LicenseApplication` approval depends on the `background_check_status` of every
`CONTROL` `ControlPerson` of the licensee, mediated by the licensee-level
`control_chain_status`.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import MoneyTransmitterApiClient
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_BACKGROUND_CHECK_INCOMPLETE,
    ERR_EXPANSION_GATE_BLOCKED,
)
from test_helpers.test_users import MANAGER_HEADERS, make_state_regulator_headers


# ---------------------------------------------------------------------------
# DelegateAuthorization -> StateLicense.expansion_gate
# ---------------------------------------------------------------------------


def _delinquent_license_with_pending_authorization(
    api: MoneyTransmitterApiClient, scenario: fx.Scenario
) -> dict:
    """Drive the licence's reporting dimension delinquent, then park an agent.

    The 2026Q1 label pins ``period_end`` at 2026-03-31 and therefore ``due_at``
    at 2026-05-15, which the seed clock of 2026-08-01 is strictly past, so the
    filing is LATE and the reporting dimension leaves CURRENT. The delegate and
    its authorization are created afterwards, so the authorization has had no
    opportunity to move out of its own creation status.
    """
    report = fx.file_call_report(api, scenario.license_id, "2026Q1", 40_000_000, 900)
    assert report["status"] == "LATE"

    delegate = fx.create_delegate(api, scenario.licensee_id)
    fx.review_delegate(
        api,
        delegate["id"],
        training_score=90,
        aml_test_score=90,
        recordkeeping_score=70,
    )
    authorization = fx.create_authorization(
        api,
        delegate["id"],
        scenario.license_id,
        "2026-09-01T00:00:00Z",
        "2027-08-31T00:00:00Z",
    )
    return {"delegate": delegate, "authorization": authorization, "report": report}


def test_activation_refused_because_the_licence_expansion_gate_is_blocked(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """A PENDING_OVERSIGHT authorization with a passing score cannot activate over a BLOCKED gate.

    PRD 3.6: "Activation is the gated step."
    PRD 3.6: "The underlying licence's `license_status` must be `ACTIVE` (`ERR_LICENSE_NOT_ACTIVE`), its `expansion_gate` must be `OPEN` (`ERR_EXPANSION_GATE_BLOCKED`), the delegate's `oversight_score` must be non-null and at least 70 (`ERR_OVERSIGHT_SCORE_INSUFFICIENT`) — a score of exactly 70 satisfies the gate, 69 does not — and the delegate and licence must share a licensee."
    PRD 2.8: "It is `OPEN` exactly when all five of the following hold: `license_status` is `ACTIVE`, `bond_status` is `POSTED`, `reporting_status` is `CURRENT`, `exam_findings_open` is false, and the owning licensee's `coverage_posture` is either `COMPLIANT` or `WATCH`."
    PRD 3.5: "A `LATE` report moves `reporting_status` from `CURRENT` to `DELINQUENT`."
    PRD 3.5: "Any `reporting_status` other than `CURRENT` forces `expansion_gate` to `BLOCKED`."
    PRD 2.8: "A suspended licence still files call reports and its `reporting_status` still moves; a licence whose `reporting_status` is `DELINQUENT` is still authorised to transmit."
    PRD 3.6: "A new authorization starts in `PENDING_OVERSIGHT` and moves no counter — only activation makes a delegate count against the bond."

    Design: Difficulty/cross_entity_state_dependency/authorization_activation_depends_on_license_expansion_gate
    """
    built = _delinquent_license_with_pending_authorization(api, active_license)

    blocked_license = fx.get_license(api, active_license.license_id)
    assert blocked_license["reporting_status"] == "DELINQUENT"
    assert blocked_license["expansion_gate"] == "BLOCKED"
    # The authorisation dimension is untouched: only the reporting dimension moved.
    assert blocked_license["license_status"] == "ACTIVE"
    assert blocked_license["bond_status"] == "POSTED"

    # The delegate itself satisfies its own gate: 90*4000 + 90*3500 + 70*2500 = 850000,
    # divided by 10000 and rounded down = 85, which is at least 70.
    scored = get_success_data(api.get_delegate(built["delegate"]["id"], MANAGER_HEADERS))
    assert scored["oversight_score"] == 85

    response = api.activate_authorization(built["authorization"]["id"], MANAGER_HEADERS)
    validate_error(response, ERR_EXPANSION_GATE_BLOCKED)

    parked = get_success_data(
        api.get_delegate_authorization(built["authorization"]["id"], MANAGER_HEADERS)
    )
    assert parked["status"] == "PENDING_OVERSIGHT"
    assert parked["activated_at"] is None
    assert parked["oversight_score_at_activation"] is None

    unmoved = fx.get_license(api, active_license.license_id)
    assert unmoved["active_delegate_count"] == 0
    assert unmoved["license_status"] == "ACTIVE"
    unmoved_delegate = get_success_data(
        api.get_delegate(built["delegate"]["id"], MANAGER_HEADERS)
    )
    assert unmoved_delegate["status"] == "ONBOARDING"
    assert unmoved_delegate["authorized_state_count"] == 0


def test_activation_succeeds_once_the_licence_reporting_status_returns_to_current(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """The identical activation call is admitted once the other entity's gate re-derives to OPEN.

    PRD 3.5: "Recovery from `DELINQUENT` back to `CURRENT` is stricter: the new report must be filed on or before the `due_at` of its own, later, period, and no other call report of the licence may still be `LATE` for a period label greater than the one being filed; when both hold, the new report is `FILED` and `reporting_status` returns to `CURRENT`."
    PRD 2.8: "The gate is what stops growth: it is re-derived on every event that touches one of its five inputs."
    PRD 2.8: "It is `OPEN` exactly when all five of the following hold: `license_status` is `ACTIVE`, `bond_status` is `POSTED`, `reporting_status` is `CURRENT`, `exam_findings_open` is false, and the owning licensee's `coverage_posture` is either `COMPLIANT` or `WATCH`."
    PRD 3.6: "On success, and identically for both admissible source statuses, the authorization moves to `ACTIVE`, `activated_at` is stamped from the logical clock, and `oversight_score_at_activation` pins the delegate's `oversight_score` as it stood at that instant."
    PRD 3.6: "The licence's `active_delegate_count` increases by one and its `bond_requirement_cents` is recomputed with the new delegate count — which is how onboarding an agent can raise a bond requirement above the posted bond."
    PRD 3.6: "The first successful activation moves the delegate `ONBOARDING → ACTIVE`; an activation out of `SUSPENDED_BY_POSTURE` for a delegate that had been parked moves it `SUSPENDED → ACTIVE` and clears `oversight_hold` to false."

    Design: Difficulty/cross_entity_state_dependency/authorization_activation_depends_on_license_expansion_gate
    """
    built = _delinquent_license_with_pending_authorization(api, active_license)
    blocked = api.activate_authorization(built["authorization"]["id"], MANAGER_HEADERS)
    validate_error(blocked, ERR_EXPANSION_GATE_BLOCKED)

    # 2026Q2 pins period_end at 2026-06-30 and due_at at 2026-08-14, which the
    # 2026-08-01 clock has not passed, and no LATE report carries a label above
    # "2026Q2", so the reporting dimension recovers.
    recovery = fx.file_call_report(api, active_license.license_id, "2026Q2", 60_000_000, 1_100)
    assert recovery["status"] == "FILED"

    reopened = fx.get_license(api, active_license.license_id)
    assert reopened["reporting_status"] == "CURRENT"
    assert reopened["expansion_gate"] == "OPEN"

    activated = validate_success(
        api.activate_authorization(built["authorization"]["id"], MANAGER_HEADERS)
    )
    assert activated["status"] == "ACTIVE"
    assert activated["activated_at"] is not None
    # 90*4000 + 90*3500 + 70*2500 = 850000, floored over 10000 = 85.
    assert activated["oversight_score_at_activation"] == 85

    delegate = get_success_data(api.get_delegate(built["delegate"]["id"], MANAGER_HEADERS))
    assert delegate["status"] == "ACTIVE"
    assert delegate["authorized_state_count"] == 1

    counted = fx.get_license(api, active_license.license_id)
    assert counted["active_delegate_count"] == 1
    # The dependency was on expansion_gate, never on the authorisation dimension.
    assert counted["license_status"] == "ACTIVE"
    # max(base_bond 5_000_000, tier-one 2_500_000 + 1 * per_delegate 100_000) = 5_000_000,
    # times the MONEY_TRANSMISSION multiplier of 10000 bps, capped at 40_000_000.
    assert counted["bond_requirement_cents"] == 5_000_000


# ---------------------------------------------------------------------------
# LicenseApplication -> ControlPerson.background_check_status
# ---------------------------------------------------------------------------


def _application_under_review(
    api: MoneyTransmitterApiClient, jurisdiction: dict, licensee: dict
) -> dict:
    """Carry one application to UNDER_REVIEW with nothing else outstanding."""
    application = fx.create_application(api, licensee["id"], jurisdiction["id"])
    submitted = fx.submit_application(api, application["id"])
    # required_net_worth_cents copies CA's min_net_worth_cents of 50_000_000.
    assert submitted["required_net_worth_cents"] == 50_000_000
    # max(base_bond 5_000_000, tier-one 2_500_000 + 0 * 100_000) = 5_000_000, times
    # the MONEY_TRANSMISSION multiplier of 10000 bps, capped at 40_000_000.
    assert submitted["required_bond_cents"] == 5_000_000
    return fx.review_application(api, application["id"], jurisdiction["id"], "START_REVIEW")


def test_approval_refused_while_a_control_person_background_check_is_pending(
    api: MoneyTransmitterApiClient, ca_jurisdiction: dict, licensee: dict
) -> None:
    """A validly UNDER_REVIEW application with ample net worth is refused over a third entity's PENDING check.

    PRD 3.2: "`control_determination` is `CONTROL` when `attributed_ownership_bps` is at least 2500 basis points **or** the holder's `role_title` is one of the four officer titles `CEO`, `CFO`, `COO` or `CCO`; otherwise it is `NON_CONTROL`."
    PRD 3.2: "`background_check_status` is set to `PENDING` for a control person and to `NOT_REQUIRED` otherwise; its full value set is `NOT_REQUIRED`, `PENDING`, `CLEARED` and `ADVERSE`, and it defaults to `NOT_REQUIRED`."
    PRD 3.2: "`change_of_control_status` is set to `PENDING_APPROVAL` when the holder is a control person **and** the licensee's `active_license_count` is greater than zero, and to `NOT_REQUIRED` in every other case; its value set is `NOT_REQUIRED`, `PENDING_APPROVAL`, `APPROVED` and `DENIED`."
    PRD 3.3: "The action `APPROVE` carries three substantive preconditions on top of the state and scope checks: the licensee's `reported_tangible_net_worth_cents` must be at least the application's pinned `required_net_worth_cents`, or the approval is rejected with `ERR_NET_WORTH_INSUFFICIENT`; every non-`REMOVED` control person of the licensee whose `control_determination` is `CONTROL` must have `background_check_status` of `CLEARED`, or the approval is rejected with `ERR_BACKGROUND_CHECK_INCOMPLETE`, which is the per-holder statement of the licensee-level condition that `control_chain_status` be `VERIFIED`; and the licensee's `coverage_posture` must not be `FROZEN`."

    Design: Difficulty/cross_entity_state_dependency/application_approval_depends_on_control_person_clearance
    """
    reviewed = _application_under_review(api, ca_jurisdiction, licensee)
    assert reviewed["status"] == "UNDER_REVIEW"

    holder = fx.create_control_person(
        api,
        licensee["id"],
        full_name="Dana Whitfield",
        role_title="ENTITY_HOLDER",
        direct_ownership_bps=5000,
    )
    # A direct holder attributes its own stake: 5000 bps, at or above the 2500 bps
    # control threshold, so the row is CONTROL and owes a background check.
    assert holder["attributed_ownership_bps"] == 5000
    assert holder["control_determination"] == "CONTROL"
    assert holder["background_check_status"] == "PENDING"
    # The licensee had zero ACTIVE licences when the row was created.
    assert holder["change_of_control_status"] == "NOT_REQUIRED"

    pending_chain = fx.get_licensee(api, licensee["id"])
    assert pending_chain["control_chain_status"] == "PENDING_CHECKS"
    # 500_000_000 reported against a pinned requirement of 50_000_000: net worth
    # is not what stops this approval.
    assert pending_chain["reported_tangible_net_worth_cents"] == 500_000_000
    assert pending_chain["coverage_posture"] == "COMPLIANT"

    response = api.review_application(
        reviewed["id"],
        F.review_action_payload("APPROVE"),
        make_state_regulator_headers(ca_jurisdiction["id"]),
    )
    validate_error(response, ERR_BACKGROUND_CHECK_INCOMPLETE)

    unmoved = get_success_data(api.get_application(reviewed["id"], MANAGER_HEADERS))
    assert unmoved["status"] == "UNDER_REVIEW"
    assert unmoved["decision_at"] is None
    licenses = get_success_data(
        api.list_state_licenses(MANAGER_HEADERS, params={"application_id": reviewed["id"]})
    )
    assert licenses == []


def test_approval_succeeds_once_the_control_person_is_cleared(
    api: MoneyTransmitterApiClient, ca_jurisdiction: dict, licensee: dict
) -> None:
    """Clearing the third entity unblocks the identical approval and mints the licence.

    PRD 2.1: "For control-person adjudications and change-of-control decisions the test is broader: `X-User-ID` must be a jurisdiction in which the licensee either holds a `StateLicense` whose `license_status` is `ACTIVE` or has a `LicenseApplication` in a non-terminal status."
    PRD 3.2: "An `outcome` of `CLEARED` sets `background_check_status` to `CLEARED`."
    PRD 3.2: "A holder becomes `SEATED` — the system's way of saying the appointment is effective — when its `background_check_status` is either `NOT_REQUIRED` or `CLEARED` **and** its `change_of_control_status` is either `NOT_REQUIRED` or `APPROVED`, while the row itself is still `PROPOSED`."
    PRD 3.2: "It is recomputed on every control-person creation, every background-check adjudication and every change-of-control decision, by this precedence: `BLOCKED` if any such holder has `background_check_status` of `ADVERSE` or `change_of_control_status` of `DENIED`; otherwise `PENDING_CHECKS` if any such holder has `background_check_status` of `PENDING` or `change_of_control_status` of `PENDING_APPROVAL`; otherwise `VERIFIED`."
    PRD 3.3: "Approval stamps `decision_at` and mints a licence."
    PRD 3.3: "It starts with `license_status` `PENDING_BOND`, `reporting_status` `CURRENT`, `expansion_gate` `BLOCKED`, `bond_status` `NONE`, `outstanding_obligations_cents` zero, and `bond_requirement_cents` copied from the application's `required_bond_cents`."

    Design: Difficulty/cross_entity_state_dependency/application_approval_depends_on_control_person_clearance
    """
    reviewed = _application_under_review(api, ca_jurisdiction, licensee)
    holder = fx.create_control_person(
        api,
        licensee["id"],
        full_name="Dana Whitfield",
        role_title="ENTITY_HOLDER",
        direct_ownership_bps=5000,
    )
    refused = api.review_application(
        reviewed["id"],
        F.review_action_payload("APPROVE"),
        make_state_regulator_headers(ca_jurisdiction["id"]),
    )
    validate_error(refused, ERR_BACKGROUND_CHECK_INCOMPLETE)

    # CA hosts a non-terminal application of this licensee, so its regulator may
    # adjudicate even though no licence has been issued there yet.
    cleared = fx.clear_background_check(api, holder["id"], ca_jurisdiction["id"])
    assert cleared["background_check_status"] == "CLEARED"
    assert cleared["status"] == "SEATED"
    verified = fx.get_licensee(api, licensee["id"])
    assert verified["control_chain_status"] == "VERIFIED"

    approved = validate_success(
        api.review_application(
            reviewed["id"],
            F.review_action_payload("APPROVE"),
            make_state_regulator_headers(ca_jurisdiction["id"]),
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["decision_at"] is not None

    minted = fx.find_license_by_application(api, reviewed["id"])
    assert minted["license_status"] == "PENDING_BOND"
    assert minted["reporting_status"] == "CURRENT"
    assert minted["expansion_gate"] == "BLOCKED"
    assert minted["bond_status"] == "NONE"
    assert minted["outstanding_obligations_cents"] == 0
    # Copied from the application's pinned required_bond_cents: max(base_bond
    # 5_000_000, tier-one 2_500_000 + 0 * 100_000) = 5_000_000, unchanged by the
    # MONEY_TRANSMISSION multiplier of 10000 bps and under the 40_000_000 cap.
    assert minted["bond_requirement_cents"] == 5_000_000


def test_a_non_control_holder_with_no_check_does_not_block_approval(
    api: MoneyTransmitterApiClient, ca_jurisdiction: dict, licensee: dict
) -> None:
    """The dependency reaches only CONTROL holders: a NON_CONTROL holder owes no check and blocks nothing.

    PRD 3.2: "`control_determination` is `CONTROL` when `attributed_ownership_bps` is at least 2500 basis points **or** the holder's `role_title` is one of the four officer titles `CEO`, `CFO`, `COO` or `CCO`; otherwise it is `NON_CONTROL`."
    PRD 3.2: "A `DIRECTOR`, an `ENTITY_HOLDER` and a `PASSIVE_INVESTOR` are officers for no purpose here — they reach `CONTROL` only through the attributed stake."
    PRD 3.2: "`background_check_status` is set to `PENDING` for a control person and to `NOT_REQUIRED` otherwise; its full value set is `NOT_REQUIRED`, `PENDING`, `CLEARED` and `ADVERSE`, and it defaults to `NOT_REQUIRED`."
    PRD 3.3: "The action `APPROVE` carries three substantive preconditions on top of the state and scope checks: the licensee's `reported_tangible_net_worth_cents` must be at least the application's pinned `required_net_worth_cents`, or the approval is rejected with `ERR_NET_WORTH_INSUFFICIENT`; every non-`REMOVED` control person of the licensee whose `control_determination` is `CONTROL` must have `background_check_status` of `CLEARED`, or the approval is rejected with `ERR_BACKGROUND_CHECK_INCOMPLETE`, which is the per-holder statement of the licensee-level condition that `control_chain_status` be `VERIFIED`; and the licensee's `coverage_posture` must not be `FROZEN`."

    Design: Difficulty/cross_entity_state_dependency/application_approval_depends_on_control_person_clearance
    """
    reviewed = _application_under_review(api, ca_jurisdiction, licensee)
    holder = fx.create_control_person(
        api,
        licensee["id"],
        full_name="Ilya Sorensen",
        role_title="PASSIVE_INVESTOR",
        direct_ownership_bps=1000,
    )
    # 1000 bps attributed is below the 2500 bps threshold and PASSIVE_INVESTOR is
    # not one of the four officer titles.
    assert holder["attributed_ownership_bps"] == 1000
    assert holder["control_determination"] == "NON_CONTROL"
    assert holder["background_check_status"] == "NOT_REQUIRED"
    assert holder["status"] == "SEATED"

    verified = fx.get_licensee(api, licensee["id"])
    assert verified["control_chain_status"] == "VERIFIED"

    approved = validate_success(
        api.review_application(
            reviewed["id"],
            F.review_action_payload("APPROVE"),
            make_state_regulator_headers(ca_jurisdiction["id"]),
        )
    )
    assert approved["status"] == "APPROVED"

    minted = fx.find_license_by_application(api, reviewed["id"])
    assert minted["license_status"] == "PENDING_BOND"
    # Same arithmetic as the cleared-CONTROL case: base_bond 5_000_000 dominates
    # tier-one 2_500_000 with no delegates.
    assert minted["bond_requirement_cents"] == 5_000_000
    assert minted["jurisdiction_id"] == ca_jurisdiction["id"]
    assert minted["license_class"] == "MONEY_TRANSMISSION"
