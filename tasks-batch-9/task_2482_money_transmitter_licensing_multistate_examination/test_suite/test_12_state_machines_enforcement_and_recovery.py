"""Enforcement, surrender, information-request and posture-recovery state machines.

Every scenario is built through the API's own declared endpoints against a live
server: the runner restarts the process before each test, so each one starts from
an empty database with the logical clock at 2026-08-01T00:00:00Z.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import MoneyTransmitterApiClient
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CONTROL_PERSON_INVALID_STATE,
    ERR_ENFORCEMENT_INVALID_STATE,
)
from test_helpers.test_users import MANAGER_HEADERS, make_state_regulator_headers


# ---------------------------------------------------------------------------
# Local reading helpers (no persistence access: every read is a GET endpoint)
# ---------------------------------------------------------------------------


def _assert_instant(actual: str, expected: str, label: str) -> None:
    """Compare an ISO 8601 UTC stamp to an instant, ignoring fractional digits."""

    def norm(value: str) -> str:
        return value.replace("Z", "").split(".")[0]

    assert norm(actual) == norm(expected), f"{label} is {actual}, expected {expected}"


def _get_action(api: MoneyTransmitterApiClient, action_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_enforcement_action(action_id, MANAGER_HEADERS))


def _get_authorization(api: MoneyTransmitterApiClient, authorization_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_delegate_authorization(authorization_id, MANAGER_HEADERS))


def _get_delegate(api: MoneyTransmitterApiClient, delegate_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_delegate(delegate_id, MANAGER_HEADERS))


def _get_request(api: MoneyTransmitterApiClient, request_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_information_request(request_id, MANAGER_HEADERS))


def _get_exam(api: MoneyTransmitterApiClient, exam_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_exam(exam_id, MANAGER_HEADERS))


# ---------------------------------------------------------------------------
# Composite setups shared by two tests each
# ---------------------------------------------------------------------------


def _contested_action_over_a_working_licence(
    api: MoneyTransmitterApiClient,
) -> Dict[str, Any]:
    """An ACTIVE licence with obligations, one ACTIVE delegate and a CONTESTED action."""
    scenario = fx.setup_active_license(api, C.CA_CONFIG)
    fx.record_holding(
        api,
        scenario.licensee_id,
        asset_class="CASH",
        counterparty_name="First Republic Trust",
        book_value_cents=8_000_000,
        market_value_cents=8_000_000,
    )
    fx.adjust_obligations(api, scenario.license_id, 4_000_000, memo="Settlement float")
    appointed = fx.setup_active_authorization(
        api,
        scenario,
        scores={"training_score": 90, "aml_test_score": 90, "recordkeeping_score": 70},
    )
    action = fx.issue_enforcement_action(
        api,
        scenario.license_id,
        scenario.jurisdiction_id,
        basis="UNAUTHORIZED_DELEGATE",
        penalty_cents=5_000_000,
    )
    contested = fx.respond_to_enforcement_action(api, action["id"], "CONTEST")
    return {
        "scenario": scenario,
        "delegate": appointed["delegate"],
        "authorization": appointed["authorization"],
        "action": contested,
    }


def _parked_authorization_after_a_posture_drop(
    api: MoneyTransmitterApiClient,
) -> Dict[str, Any]:
    """A DEFICIENT licensee whose only authorization sits in SUSPENDED_BY_POSTURE."""
    scenario = fx.setup_active_license(api, C.CA_CONFIG)
    fx.record_holding(
        api,
        scenario.licensee_id,
        asset_class="CASH",
        counterparty_name="First Republic Trust",
        book_value_cents=10_000_000,
        market_value_cents=10_000_000,
    )
    delegate = fx.create_delegate(api, scenario.licensee_id)
    # 90*4000 + 90*3500 + 70*2500 = 8500000, floor(8500000 / 10000) = 85.
    fx.review_delegate(api, delegate["id"], training_score=90, aml_test_score=90, recordkeeping_score=70)
    authorization = fx.create_authorization(
        api,
        delegate["id"],
        scenario.license_id,
        "2026-09-01T00:00:00Z",
        "2027-08-31T00:00:00Z",
    )
    fx.adjust_obligations(
        api, scenario.license_id, 85_000_000, memo="Settlement float spike"
    )
    return {
        "scenario": scenario,
        "delegate": delegate,
        "authorization": authorization,
    }


# ---------------------------------------------------------------------------
# Enforcement responses
# ---------------------------------------------------------------------------


def test_replayed_response_on_a_consent_order_action_is_rejected(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """A second response on a settled action is refused and suspends nothing twice.

    PRD 3.9: "Either branch requires the action to be in `ISSUED` — a response to anything else is rejected with `ERR_ENFORCEMENT_INVALID_STATE` — and requires the logical clock to be on or before `issued_at` plus twenty days, a late response being rejected with `ERR_ENFORCEMENT_RESPONSE_WINDOW_CLOSED`."
    PRD 3.9: "Settling also costs the licence its authorisation: the target `StateLicense` moves `ACTIVE → SUSPENDED`, `expansion_gate` becomes `BLOCKED`, the licensee's `active_license_count` drops by one, every `ACTIVE` `DelegateAuthorization` of the licence moves to `SUSPENDED` with `active_delegate_count` reset to zero and `bond_requirement_cents` recomputed with no delegates, and each affected `Delegate` has `authorized_state_count` reduced by one and moves to `SUSPENDED` when that count reaches zero."

    Design: Corner/state_machines/second_response_on_a_consent_order_rejects
    """
    action = fx.issue_enforcement_action(
        api,
        active_license.license_id,
        active_license.jurisdiction_id,
        basis="DELINQUENT_REPORTING",
        penalty_cents=2_500_000,
    )
    settled = fx.respond_to_enforcement_action(
        api,
        action["id"],
        "CONSENT_ORDER",
        remediation_plan_narrative="Backfill all delinquent call reports within 30 days.",
    )
    assert settled["status"] == "CONSENT_ORDER"

    licence_after_settlement = fx.get_license(api, active_license.license_id)
    assert licence_after_settlement["license_status"] == "SUSPENDED"
    assert licence_after_settlement["expansion_gate"] == "BLOCKED"
    licensee_after_settlement = fx.get_licensee(api, active_license.licensee_id)
    # One licence was activated by the bond and the consent order took it back.
    assert licensee_after_settlement["active_license_count"] == 0

    replay = api.respond_to_enforcement_action(
        action["id"], F.enforcement_response_payload("CONTEST"), MANAGER_HEADERS
    )
    validate_error(replay, ERR_ENFORCEMENT_INVALID_STATE)

    action_after = _get_action(api, action["id"])
    assert action_after["status"] == "CONSENT_ORDER"
    assert (
        action_after["remediation_plan_narrative"]
        == "Backfill all delinquent call reports within 30 days."
    )
    assert action_after["version"] == settled["version"]

    licence_after = fx.get_license(api, active_license.license_id)
    assert licence_after["license_status"] == "SUSPENDED"
    assert licence_after["expansion_gate"] == "BLOCKED"
    assert licence_after["version"] == licence_after_settlement["version"]

    licensee_after = fx.get_licensee(api, active_license.licensee_id)
    # The refused replay may not decrement the counter a second time.
    assert licensee_after["active_license_count"] == 0


def test_second_adjudication_of_a_removed_control_person_is_rejected(
    api: MoneyTransmitterApiClient, ca_jurisdiction: dict, licensee: dict
) -> None:
    """REMOVED is terminal: a re-adjudication cannot turn an ADVERSE finding into CLEARED.

    PRD 3.2: "`control_determination` is `CONTROL` when `attributed_ownership_bps` is at least 2500 basis points **or** the holder's `role_title` is one of the four officer titles `CEO`, `CFO`, `COO` or `CCO`; otherwise it is `NON_CONTROL`."
    PRD 3.2: "`background_check_status` is set to `PENDING` for a control person and to `NOT_REQUIRED` otherwise; its full value set is `NOT_REQUIRED`, `PENDING`, `CLEARED` and `ADVERSE`, and it defaults to `NOT_REQUIRED`."
    PRD 3.2: "An `outcome` of `ADVERSE` accompanied by `disqualifying_finding` true sets `background_check_status` to `ADVERSE`, sets the row's `disqualifying_finding` to true, and drives the holder from `PROPOSED` straight to the terminal `REMOVED`; the licensee's `control_chain_status` is then forced to `BLOCKED`, and every child holder whose `parent_control_person_id` names the removed row has both `effective_ownership_bps` and `attributed_ownership_bps` recomputed to zero and is itself set to `REMOVED`."
    PRD 3.2: "Adjudication requires the row's `background_check_status` to be `PENDING`; an adjudication aimed at a `SEATED` or `REMOVED` holder is rejected with `ERR_CONTROL_PERSON_INVALID_STATE`."

    Design: Corner/state_machines/adjudicating_a_removed_control_person_rejects
    """
    application = fx.create_application(api, licensee["id"], ca_jurisdiction["id"])
    fx.submit_application(api, application["id"])

    holder = fx.create_control_person(
        api,
        licensee["id"],
        full_name="Dana Whitfield",
        role_title="ENTITY_HOLDER",
        direct_ownership_bps=5000,
    )
    # A direct holder's attributed stake of 5000 bps is at or above 2500.
    assert holder["control_determination"] == "CONTROL"
    assert holder["background_check_status"] == "PENDING"

    removed = fx.adjudicate_adverse(api, holder["id"], ca_jurisdiction["id"])
    assert removed["status"] == "REMOVED"
    assert removed["background_check_status"] == "ADVERSE"
    assert removed["disqualifying_finding"] is True

    retry = api.adjudicate_background_check(
        holder["id"],
        F.background_check_payload("CLEARED"),
        make_state_regulator_headers(ca_jurisdiction["id"]),
    )
    validate_error(retry, ERR_CONTROL_PERSON_INVALID_STATE)

    holder_after = get_success_data(api.get_control_person(holder["id"], MANAGER_HEADERS))
    assert holder_after["status"] == "REMOVED"
    assert holder_after["background_check_status"] == "ADVERSE"
    assert holder_after["disqualifying_finding"] is True
    assert holder_after["version"] == removed["version"]


def test_contest_branch_moves_only_the_action_and_leaves_the_estate_untouched(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """CONTEST stamps the action and nothing else in the estate moves at all.

    PRD 3.9: "A `response` of `CONTEST` litigates instead: the action moves `ISSUED → CONTESTED` and `response_at` is stamped, and that is the entire effect."
    PRD 3.9: "The licence is **not** suspended, no delegate authorization is touched, `expansion_gate` is unchanged, `active_license_count` is unchanged, and the licence's `version` is not bumped."

    Design: Corner/state_machines/contest_branch_leaves_the_license_active
    """
    appointed = fx.setup_active_authorization(
        api,
        active_license,
        scores={"training_score": 90, "aml_test_score": 90, "recordkeeping_score": 70},
    )
    licence_before = fx.get_license(api, active_license.license_id)
    licensee_before = fx.get_licensee(api, active_license.licensee_id)
    assert licence_before["license_status"] == "ACTIVE"
    assert licence_before["expansion_gate"] == "OPEN"
    assert licensee_before["active_license_count"] == 1

    action = fx.issue_enforcement_action(
        api,
        active_license.license_id,
        active_license.jurisdiction_id,
        basis="PERMISSIBLE_INVESTMENT_SHORTFALL",
        penalty_cents=1_500_000,
    )
    assert action["status"] == "ISSUED"

    contested = fx.respond_to_enforcement_action(api, action["id"], "CONTEST")
    assert contested["status"] == "CONTESTED"
    _assert_instant(contested["response_at"], "2026-08-01T00:00:00Z", "response_at")
    assert contested.get("remediation_plan_narrative") is None

    licence_after = fx.get_license(api, active_license.license_id)
    assert licence_after["license_status"] == "ACTIVE"
    assert licence_after["expansion_gate"] == "OPEN"
    assert licence_after["bond_status"] == "POSTED"
    assert licence_after["active_delegate_count"] == 1
    # max(base 5000000, tier-one 2500000 + 1 delegate * 100000) * 10000 / 10000, capped
    # at 40000000: the statutory floor still dominates, so the requirement holds.
    assert licence_after["bond_requirement_cents"] == 5_000_000
    assert licence_after["version"] == licence_before["version"]

    licensee_after = fx.get_licensee(api, active_license.licensee_id)
    assert licensee_after["active_license_count"] == 1

    authorization_after = _get_authorization(api, appointed["authorization"]["id"])
    assert authorization_after["status"] == "ACTIVE"
    assert authorization_after["version"] == appointed["authorization"]["version"]

    delegate_after = _get_delegate(api, appointed["delegate"]["id"])
    assert delegate_after["status"] == "ACTIVE"
    assert delegate_after["authorized_state_count"] == 1
    assert delegate_after["oversight_hold"] is False


# ---------------------------------------------------------------------------
# Revocation out of CONTESTED
# ---------------------------------------------------------------------------


def test_revocation_out_of_contested_terminates_authorization_and_delegate(
    api: MoneyTransmitterApiClient,
) -> None:
    """A REVOCATION resolution revokes the licence and terminates its agent chain.

    PRD 3.9: "An `outcome` of `REVOCATION` is admissible from either `CONSENT_ORDER` or `CONTESTED` and is the end of the licence."
    PRD 3.9: "The action moves to the terminal `REVOCATION` and the licence runs the full four-level revocation cascade of §2.9: `license_status` becomes the terminal `REVOKED`, `expansion_gate` becomes `BLOCKED`, `bond_status` becomes `CANCELLED`, and `active_license_count` drops by one when — and only when — the licence had been `ACTIVE` immediately before, so revoking an already-suspended licence moves no counter; every non-`TERMINATED` `DelegateAuthorization` of the licence moves to `TERMINATED` with `active_delegate_count` reset to zero; each `Delegate` that had an `ACTIVE` authorization has `authorized_state_count` reduced by one and moves `ACTIVE → TERMINATED` when it has no non-`TERMINATED` authorization left anywhere; and, because the licence has left the obligation aggregate set, the licensee's `aggregate_outstanding_obligations_cents`, `coverage_ratio_bps` and `coverage_posture` are recomputed."
    PRD 3.9: "`StateLicense.version` is bumped."

    Design: Corner/state_machines/revocation_terminates_authorizations_and_the_delegate
    """
    built = _contested_action_over_a_working_licence(api)
    scenario = built["scenario"]

    licence_before = fx.get_license(api, scenario.license_id)
    assert licence_before["license_status"] == "ACTIVE"
    assert licence_before["active_delegate_count"] == 1
    assert built["action"]["status"] == "CONTESTED"

    resolved = fx.resolve_enforcement_action(
        api, built["action"]["id"], scenario.jurisdiction_id, "REVOCATION"
    )
    assert resolved["status"] == "REVOCATION"
    _assert_instant(resolved["resolved_at"], "2026-08-01T00:00:00Z", "resolved_at")

    licence_after = fx.get_license(api, scenario.license_id)
    assert licence_after["license_status"] == "REVOKED"
    assert licence_after["expansion_gate"] == "BLOCKED"
    assert licence_after["bond_status"] == "CANCELLED"
    assert licence_after["active_delegate_count"] == 0
    assert licence_after["version"] == licence_before["version"] + 1

    authorization_after = _get_authorization(api, built["authorization"]["id"])
    assert authorization_after["status"] == "TERMINATED"
    assert authorization_after["version"] == built["authorization"]["version"] + 1

    delegate_after = _get_delegate(api, built["delegate"]["id"])
    assert delegate_after["status"] == "TERMINATED"
    assert delegate_after["authorized_state_count"] == 0

    licensee_after = fx.get_licensee(api, scenario.licensee_id)
    # The bond had raised the count to one; the revocation of an ACTIVE licence
    # takes it back down.
    assert licensee_after["active_license_count"] == 0


def test_revocation_drops_the_revoked_licence_from_the_obligation_aggregate(
    api: MoneyTransmitterApiClient,
) -> None:
    """The revoked licence leaves the aggregate set, so the ratio goes vacuously perfect.

    PRD 3.4: "The aggregate itself is the exact sum, in integer cents with no rounding, of `outstanding_obligations_cents` over the licensee's licences whose `license_status` is `PENDING_BOND`, `ACTIVE`, `SUSPENDED` or `SURRENDER_REQUESTED`."
    PRD 3.4: "A licence that reaches `SURRENDERED` or `REVOKED` leaves the set and its obligations stop being counted as needing coverage, which is why both of those transitions force a recomputation of the aggregate, the ratio and the posture."
    PRD 3.7: "The haircuts, in basis points, are: `CASH` none, `US_TREASURY` 200, `MONEY_MARKET_FUND` 300, `AGENCY_BOND` 500 and `RECEIVABLE_FROM_DELEGATE` 1000."
    PRD 3.7: "Holdings in the uncapped classes — `CASH` and `US_TREASURY` — accumulate into a single uncapped total."
    PRD 3.7: "A coverage ratio in basis points is derived from an investment value the same way for both variants: it is exactly 10000 when the licensee's `aggregate_outstanding_obligations_cents` is zero, and otherwise the investment value multiplied by 10000, divided by the obligations, rounded down."

    Design: Corner/state_machines/revocation_terminates_authorizations_and_the_delegate
    """
    built = _contested_action_over_a_working_licence(api)
    scenario = built["scenario"]

    licensee_before = fx.get_licensee(api, scenario.licensee_id)
    assert licensee_before["aggregate_outstanding_obligations_cents"] == 4_000_000
    assert licensee_before["eligible_investment_value_cents"] == 8_000_000
    # 8000000 * 10000 / 4000000 = 20000, floored, and 20000 >= 10000 is COMPLIANT.
    assert licensee_before["coverage_ratio_bps"] == 20000
    assert licensee_before["coverage_posture"] == "COMPLIANT"

    fx.resolve_enforcement_action(
        api, built["action"]["id"], scenario.jurisdiction_id, "REVOCATION"
    )

    licence_after = fx.get_license(api, scenario.license_id)
    assert licence_after["license_status"] == "REVOKED"
    # The licence keeps its own recorded balance; it simply stops being aggregated.
    assert licence_after["outstanding_obligations_cents"] == 4_000_000

    licensee_after = fx.get_licensee(api, scenario.licensee_id)
    assert licensee_after["aggregate_outstanding_obligations_cents"] == 0
    assert licensee_after["eligible_investment_value_cents"] == 8_000_000
    # Zero obligations make the ratio exactly 10000, which is COMPLIANT.
    assert licensee_after["coverage_ratio_bps"] == 10000
    assert licensee_after["coverage_posture"] == "COMPLIANT"


# ---------------------------------------------------------------------------
# Surrender compensation
# ---------------------------------------------------------------------------


def test_denied_surrender_decision_returns_the_licence_to_active(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """A DENIED surrender decision undoes the request and reopens the expansion gate.

    PRD 3.4: "On success the licence moves to `SURRENDER_REQUESTED`, `expansion_gate` is set to `BLOCKED`, `version` is bumped, and `active_license_count` is reduced by one — but only when the prior status was `ACTIVE`; surrendering an already-suspended licence moves no counter, because the suspension already decremented it."
    PRD 3.4: "A `decision` of `DENIED` puts the licence back to work: it moves `SURRENDER_REQUESTED → ACTIVE`, requires `bond_status` to be `POSTED`, increases `active_license_count` by one, and re-derives `expansion_gate`, which becomes `OPEN` when the licensee's `coverage_posture` is `COMPLIANT` or `WATCH` and the other gate conditions hold."
    PRD 3.4: "Either decision bumps the licence's `version`."

    Design: Corner/state_machines/denied_surrender_returns_the_license_to_active
    """
    bonded = fx.get_license(api, active_license.license_id)
    assert bonded["license_status"] == "ACTIVE"
    assert bonded["outstanding_obligations_cents"] == 0

    requested = get_success_data(
        api.request_surrender(
            active_license.license_id,
            F.surrender_request_payload(
                bonded["version"],
                effective_date="2026-09-30T00:00:00Z",
                wind_down_narrative="Exiting the state.",
            ),
            MANAGER_HEADERS,
        )
    )
    assert requested["license_status"] == "SURRENDER_REQUESTED"
    assert requested["expansion_gate"] == "BLOCKED"
    assert requested["version"] == bonded["version"] + 1
    licensee_mid = fx.get_licensee(api, active_license.licensee_id)
    # The request decremented the single ACTIVE licence out of the count.
    assert licensee_mid["active_license_count"] == 0

    decided = get_success_data(
        api.decide_surrender(
            active_license.license_id,
            F.surrender_decision_payload(
                "DENIED", rationale="Open examination in progress."
            ),
            make_state_regulator_headers(active_license.jurisdiction_id),
        )
    )
    assert decided["license_status"] == "ACTIVE"

    licence_after = fx.get_license(api, active_license.license_id)
    assert licence_after["license_status"] == "ACTIVE"
    assert licence_after["expansion_gate"] == "OPEN"
    assert licence_after["bond_status"] == "POSTED"
    assert licence_after["bond_posted_cents"] == 5_000_000
    assert licence_after["reporting_status"] == "CURRENT"
    assert licence_after["exam_findings_open"] is False
    assert licence_after["version"] == requested["version"] + 1

    licensee_after = fx.get_licensee(api, active_license.licensee_id)
    # Back to the exact value that held before the request: zero plus one.
    assert licensee_after["active_license_count"] == 1
    assert licensee_after["coverage_posture"] == "COMPLIANT"


# ---------------------------------------------------------------------------
# Information-request dispositions
# ---------------------------------------------------------------------------


def test_rejected_disposition_from_responded_reopens_with_a_five_day_window(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """A rejected answer reopens the request on a fresh five-day clock, not the state's.

    PRD 3.8: "Its `due_at` is the current logical clock plus the requesting jurisdiction's `response_window_days`, expressed as that many exact twenty-four-hour periods."
    PRD 3.8: "`open_request_count` does not move: a `RESPONDED` request is still an open matter as far as the exam is concerned, which is exactly why responding to every request is not enough to let the lead draft its report — each one must also be accepted."
    PRD 3.8: "A `decision` of `REJECTED` from `RESPONDED` sends the request back to `OPEN`: `reopen_count` increases by one, `submitted_item_count` is reset to zero, and `due_at` is re-armed to the current logical clock plus five days — a deliberately short second clock, and notably not the jurisdiction's own `response_window_days`."
    PRD 3.8: "The request never leaves the open set on this path, so `open_request_count` is unchanged."

    Design: Corner/state_machines/rejected_information_request_reopens_with_a_five_day_window
    """
    exam = fx.setup_exam_in_fieldwork(
        api,
        active_license.licensee_id,
        active_license.jurisdiction_id,
        fieldwork_start="2026-09-01T00:00:00Z",
        fieldwork_end="2026-09-15T00:00:00Z",
    )
    request = fx.open_information_request(
        api,
        exam["id"],
        active_license.jurisdiction_id,
        subject="Delegate settlement ledgers",
        requested_item_count=3,
    )
    # Clock 2026-08-01 plus California's response_window_days of 15.
    _assert_instant(request["due_at"], "2026-08-16T00:00:00Z", "due_at")
    assert request["status"] == "OPEN"

    answered = fx.respond_to_information_request(
        api, request["id"], 3, narrative="Three ledgers attached."
    )
    assert answered["status"] == "RESPONDED"
    assert answered["submitted_item_count"] == 3
    assert answered["reopen_count"] == 0
    exam_before = _get_exam(api, exam["id"])
    # One request opened, and a RESPONDED request is still in the open set.
    assert exam_before["open_request_count"] == 1

    fx.set_clock(api, "2026-08-06T00:00:00Z")

    rejected = fx.disposition_information_request(
        api,
        request["id"],
        active_license.jurisdiction_id,
        "REJECTED",
        rationale="Ledgers are unsigned.",
    )
    assert rejected["status"] == "OPEN"
    assert rejected["reopen_count"] == 1
    assert rejected["submitted_item_count"] == 0

    request_after = _get_request(api, request["id"])
    assert request_after["status"] == "OPEN"
    assert request_after["reopen_count"] == 1
    assert request_after["submitted_item_count"] == 0
    # Clock 2026-08-06 plus five days, not the jurisdiction's fifteen.
    _assert_instant(request_after["due_at"], "2026-08-11T00:00:00Z", "due_at")

    exam_after = _get_exam(api, exam["id"])
    assert exam_after["open_request_count"] == 1


def test_moving_the_clock_past_due_at_does_not_flip_the_request(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """A clock move alone is not an event: the request is still OPEN past its due_at.

    PRD 2.4: "Moving the clock is not itself an event: pushing the clock past an information request's `due_at` does not flip that request to `OVERDUE`; the flip happens on the next disposition call."

    Design: Corner/state_machines/rejected_disposition_past_due_at_flips_request_to_overdue
    """
    exam = fx.setup_exam_in_fieldwork(
        api,
        active_license.licensee_id,
        active_license.jurisdiction_id,
        fieldwork_start="2026-09-01T00:00:00Z",
        fieldwork_end="2026-09-15T00:00:00Z",
    )
    request = fx.open_information_request(
        api,
        exam["id"],
        active_license.jurisdiction_id,
        subject="Permissible investment schedules",
        requested_item_count=2,
    )
    # Clock 2026-08-01 plus California's response_window_days of 15.
    _assert_instant(request["due_at"], "2026-08-16T00:00:00Z", "due_at")

    moved = fx.set_clock(api, "2026-08-17T00:00:00Z")
    _assert_instant(moved["current_utc"], "2026-08-17T00:00:00Z", "current_utc")

    request_after = _get_request(api, request["id"])
    assert request_after["status"] == "OPEN"
    assert request_after["responded_at"] is None
    assert request_after["reopen_count"] == 0
    assert request_after["version"] == request["version"]
    _assert_instant(request_after["due_at"], "2026-08-16T00:00:00Z", "due_at")

    exam_after = _get_exam(api, exam["id"])
    assert exam_after["open_request_count"] == 1


def test_rejected_disposition_past_due_at_flips_the_open_request_to_overdue(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """The OPEN to OVERDUE edge fires on a rejection taken after the due instant.

    PRD 3.8: "A `decision` of `REJECTED` taken while the request is still `OPEN` and the logical clock has already passed `due_at` moves it `OPEN → OVERDUE`; this is the only way a request becomes overdue, since moving the clock alone never flips a status."
    PRD 3.8: "Because `open_request_count` is by definition the number of the exam's requests sitting in `OPEN`, `OVERDUE` or `RESPONDED`, opening a request raises it by one."

    Design: Corner/state_machines/rejected_disposition_past_due_at_flips_request_to_overdue
    """
    exam = fx.setup_exam_in_fieldwork(
        api,
        active_license.licensee_id,
        active_license.jurisdiction_id,
        fieldwork_start="2026-09-01T00:00:00Z",
        fieldwork_end="2026-09-15T00:00:00Z",
    )
    request = fx.open_information_request(
        api,
        exam["id"],
        active_license.jurisdiction_id,
        subject="Permissible investment schedules",
        requested_item_count=2,
    )
    _assert_instant(request["due_at"], "2026-08-16T00:00:00Z", "due_at")

    fx.set_clock(api, "2026-08-17T00:00:00Z")

    overdue = fx.disposition_information_request(
        api,
        request["id"],
        active_license.jurisdiction_id,
        "REJECTED",
        rationale="No response received.",
    )
    assert overdue["status"] == "OVERDUE"

    request_after = _get_request(api, request["id"])
    assert request_after["status"] == "OVERDUE"
    assert request_after["responded_at"] is None
    assert request_after["submitted_item_count"] == 0
    assert request_after["reopen_count"] == 0

    exam_after = _get_exam(api, exam["id"])
    # An OVERDUE request is still one of the exam's open matters.
    assert exam_after["open_request_count"] == 1


# ---------------------------------------------------------------------------
# Posture recovery and reactivation
# ---------------------------------------------------------------------------


def test_posture_recovery_reopens_the_gate_but_leaves_the_authorization_parked(
    api: MoneyTransmitterApiClient,
) -> None:
    """Settling the obligations restores COMPLIANT and re-derives the gate to OPEN.

    PRD 3.7: "A coverage ratio in basis points is derived from an investment value the same way for both variants: it is exactly 10000 when the licensee's `aggregate_outstanding_obligations_cents` is zero, and otherwise the investment value multiplied by 10000, divided by the obligations, rounded down."
    PRD 3.7: "Holdings in the uncapped classes — `CASH` and `US_TREASURY` — accumulate into a single uncapped total."
    PRD 3.7: "From it, and from `consecutive_failed_test_count`, the licensee's `coverage_posture` is determined by a strictly ordered test: the posture is `FROZEN` if `consecutive_failed_test_count` is at least 2, regardless of the ratio; otherwise `COMPLIANT` if `coverage_ratio_bps` is at least 10000; otherwise `WATCH` if `coverage_ratio_bps` is at least 9500; otherwise `DEFICIENT`."
    PRD 2.9: "The **posture cascade** begins whenever a licensee's `coverage_posture` becomes `DEFICIENT` or `FROZEN`. Every `StateLicense` of that licensee whose `license_status` is `ACTIVE` has `expansion_gate` set to `BLOCKED`. Every `DelegateAuthorization` of those licences whose `status` is `PENDING_OVERSIGHT` moves to `SUSPENDED_BY_POSTURE`. Every `Delegate` that is left with no `ACTIVE` authorization has its `status` set to `SUSPENDED` and its `oversight_hold` set to true."
    PRD 3.4: "If the posture recovers to `COMPLIANT` or `WATCH`, `expansion_gate` is re-derived on every `ACTIVE` licence of the licensee against the five conditions of §2.8 — and that recovery is precisely what makes a `SUSPENDED_BY_POSTURE` authorization activatable again."

    Design: Corner/state_machines/suspended_by_posture_authorization_reactivates_once_posture_clears
    """
    built = _parked_authorization_after_a_posture_drop(api)
    scenario = built["scenario"]

    licensee_deficient = fx.get_licensee(api, scenario.licensee_id)
    assert licensee_deficient["aggregate_outstanding_obligations_cents"] == 85_000_000
    # 10000000 * 10000 / 85000000 = 1176.47..., floored to 1176, below 9500.
    assert licensee_deficient["coverage_ratio_bps"] == 1176
    assert licensee_deficient["coverage_posture"] == "DEFICIENT"

    licence_blocked = fx.get_license(api, scenario.license_id)
    assert licence_blocked["license_status"] == "ACTIVE"
    assert licence_blocked["expansion_gate"] == "BLOCKED"

    parked = _get_authorization(api, built["authorization"]["id"])
    assert parked["status"] == "SUSPENDED_BY_POSTURE"

    delegate_parked = _get_delegate(api, built["delegate"]["id"])
    assert delegate_parked["status"] == "SUSPENDED"
    assert delegate_parked["oversight_hold"] is True
    assert delegate_parked["authorized_state_count"] == 0

    fx.adjust_obligations(
        api, scenario.license_id, -85_000_000, memo="Float settled in full"
    )

    licensee_recovered = fx.get_licensee(api, scenario.licensee_id)
    assert licensee_recovered["aggregate_outstanding_obligations_cents"] == 0
    # Zero obligations make the ratio exactly 10000, which is COMPLIANT.
    assert licensee_recovered["coverage_ratio_bps"] == 10000
    assert licensee_recovered["coverage_posture"] == "COMPLIANT"

    licence_recovered = fx.get_license(api, scenario.license_id)
    assert licence_recovered["license_status"] == "ACTIVE"
    assert licence_recovered["expansion_gate"] == "OPEN"
    assert licence_recovered["outstanding_obligations_cents"] == 0

    # Recovery re-derives the gate; it does not itself revive the parked rows.
    still_parked = _get_authorization(api, built["authorization"]["id"])
    assert still_parked["status"] == "SUSPENDED_BY_POSTURE"
    delegate_still_parked = _get_delegate(api, built["delegate"]["id"])
    assert delegate_still_parked["status"] == "SUSPENDED"
    assert delegate_still_parked["oversight_hold"] is True


def test_authorization_activates_out_of_suspended_by_posture_and_revives_the_delegate(
    api: MoneyTransmitterApiClient,
) -> None:
    """Once the gate is OPEN again the parked authorization activates and frees its agent.

    PRD 3.6: "Activation is the gated step. It is admissible from `PENDING_OVERSIGHT` or from `SUSPENDED_BY_POSTURE`, and from nothing else — an attempt from `ACTIVE`, `SUSPENDED` or `TERMINATED` is rejected with `ERR_AUTHORIZATION_INVALID_STATE`."
    PRD 3.6: "On success, and identically for both admissible source statuses, the authorization moves to `ACTIVE`, `activated_at` is stamped from the logical clock, and `oversight_score_at_activation` pins the delegate's `oversight_score` as it stood at that instant."
    PRD 3.6: "The licence's `active_delegate_count` increases by one and its `bond_requirement_cents` is recomputed with the new delegate count — which is how onboarding an agent can raise a bond requirement above the posted bond."
    PRD 3.6: "The delegate's `authorized_state_count` increases by one. The first successful activation moves the delegate `ONBOARDING → ACTIVE`; an activation out of `SUSPENDED_BY_POSTURE` for a delegate that had been parked moves it `SUSPENDED → ACTIVE` and clears `oversight_hold` to false."

    Design: Corner/state_machines/suspended_by_posture_authorization_reactivates_once_posture_clears
    """
    built = _parked_authorization_after_a_posture_drop(api)
    scenario = built["scenario"]
    assert _get_authorization(api, built["authorization"]["id"])["status"] == "SUSPENDED_BY_POSTURE"
    assert _get_delegate(api, built["delegate"]["id"])["status"] == "SUSPENDED"

    fx.adjust_obligations(
        api, scenario.license_id, -85_000_000, memo="Float settled in full"
    )
    assert fx.get_license(api, scenario.license_id)["expansion_gate"] == "OPEN"

    activated = fx.activate_authorization(api, built["authorization"]["id"])
    assert activated["status"] == "ACTIVE"
    _assert_instant(activated["activated_at"], "2026-08-01T00:00:00Z", "activated_at")
    # 90*4000 + 90*3500 + 70*2500 = 8500000, floor(8500000 / 10000) = 85.
    assert activated["oversight_score_at_activation"] == 85

    authorization_after = _get_authorization(api, built["authorization"]["id"])
    assert authorization_after["status"] == "ACTIVE"

    delegate_after = _get_delegate(api, built["delegate"]["id"])
    assert delegate_after["status"] == "ACTIVE"
    assert delegate_after["oversight_hold"] is False
    assert delegate_after["authorized_state_count"] == 1

    licence_after = fx.get_license(api, scenario.license_id)
    assert licence_after["active_delegate_count"] == 1
    # max(base 5000000, tier-one 2500000 + 1 delegate * 100000 = 2600000) is 5000000;
    # MONEY_TRANSMISSION multiplies by 10000/10000 and the 40000000 cap does not bite.
    assert licence_after["bond_requirement_cents"] == 5_000_000
