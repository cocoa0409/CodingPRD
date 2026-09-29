"""Composite setup builders.

Everything here drives the API through its own declared endpoints only: no
database access, no mocking, no privileged back doors. Each builder returns the
resource dictionaries it created so a test can assert against live server state.

The canonical chain to an authorised licence is: configure a jurisdiction,
register a licensee, open an application, submit it, have the regulator of record
start the review and approve it, discover the minted licence by filtering the
licence register on ``application_id`` (PRD 3.3 returns the application, not the
licence), then post the surety bond that moves the licence ``PENDING_BOND ->
ACTIVE``.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import MoneyTransmitterApiClient
from .constants import CA_CONFIG, SEED_CLOCK
from .factories import (
    application_payload,
    background_check_payload,
    bond_payload,
    call_report_payload,
    change_of_control_payload,
    clock_payload,
    control_person_payload,
    delegate_authorization_payload,
    delegate_payload,
    disposition_payload,
    enforcement_payload,
    enforcement_resolution_payload,
    enforcement_response_payload,
    exam_payload,
    exam_status_payload,
    financials_payload,
    information_request_payload,
    information_response_payload,
    investment_holding_payload,
    investment_test_payload,
    jurisdiction_payload,
    licensee_payload,
    obligations_payload,
    oversight_review_payload,
    review_action_payload,
)
from .test_users import (
    ADMIN_HEADERS,
    CHIEF_HEADERS,
    MANAGER_HEADERS,
    OFFICER_HEADERS,
    make_delegate_operator_headers,
    make_state_regulator_headers,
)

Api = MoneyTransmitterApiClient


# ---------------------------------------------------------------------------
# Scenario container
# ---------------------------------------------------------------------------


@dataclass
class Scenario:
    """The ids produced by a composite setup, plus the headers they imply."""

    jurisdiction_id: str
    licensee_id: str
    application_id: Optional[str] = None
    license_id: Optional[str] = None
    delegate_id: Optional[str] = None
    authorization_id: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def regulator_headers(self) -> Dict[str, str]:
        return make_state_regulator_headers(self.jurisdiction_id)

    @property
    def operator_headers(self) -> Dict[str, str]:
        if self.delegate_id is None:
            raise ValueError("scenario has no delegate to act as")
        return make_delegate_operator_headers(self.delegate_id)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


def set_clock(api: Api, instant: str) -> Dict[str, Any]:
    """Move the server's logical clock to an exact instant."""
    return get_success_data(api.set_clock(clock_payload(instant), ADMIN_HEADERS))


def reset_clock(api: Api) -> Dict[str, Any]:
    """Put the logical clock back at its process-start instant."""
    return set_clock(api, SEED_CLOCK)


# ---------------------------------------------------------------------------
# Reference data and the licensee of record
# ---------------------------------------------------------------------------


def create_jurisdiction(
    api: Api, config: Optional[Dict[str, Any]] = None, **overrides: Any
) -> Dict[str, Any]:
    """Configure one state's statutory parameters."""
    payload = jurisdiction_payload(**{**(config or CA_CONFIG), **overrides})
    return get_success_data(api.create_jurisdiction(payload, ADMIN_HEADERS), 201)


def create_licensee(api: Api, **overrides: Any) -> Dict[str, Any]:
    """Register the money services business."""
    return get_success_data(
        api.create_licensee(licensee_payload(**overrides), MANAGER_HEADERS), 201
    )


def update_financials(api: Api, licensee_id: str, **overrides: Any) -> Dict[str, Any]:
    """Refresh the reported tangible net worth and its statement date."""
    return get_success_data(
        api.update_licensee_financials(licensee_id, financials_payload(**overrides), MANAGER_HEADERS)
    )


def get_licensee(api: Api, licensee_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_licensee(licensee_id, MANAGER_HEADERS))


def get_coverage_summary(api: Api, licensee_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_coverage_summary(licensee_id, MANAGER_HEADERS))


def get_assessment_summary(api: Api, licensee_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_assessment_summary(licensee_id, MANAGER_HEADERS))


# ---------------------------------------------------------------------------
# Control persons
# ---------------------------------------------------------------------------


def create_control_person(api: Api, licensee_id: str, **overrides: Any) -> Dict[str, Any]:
    """Record a holder or an intermediate holding company."""
    return get_success_data(
        api.create_control_person(
            control_person_payload(licensee_id, **overrides), MANAGER_HEADERS
        ),
        201,
    )


def clear_background_check(
    api: Api, control_person_id: str, jurisdiction_id: str
) -> Dict[str, Any]:
    """Adjudicate a pending background check with an outcome of CLEARED."""
    return get_success_data(
        api.adjudicate_background_check(
            control_person_id,
            background_check_payload("CLEARED"),
            make_state_regulator_headers(jurisdiction_id),
        )
    )


def adjudicate_adverse(
    api: Api, control_person_id: str, jurisdiction_id: str
) -> Dict[str, Any]:
    """Adjudicate a pending background check adversely and disqualifyingly."""
    return get_success_data(
        api.adjudicate_background_check(
            control_person_id,
            background_check_payload("ADVERSE", disqualifying_finding=True),
            make_state_regulator_headers(jurisdiction_id),
        )
    )


def decide_change_of_control(
    api: Api, control_person_id: str, jurisdiction_id: str, decision: str
) -> Dict[str, Any]:
    """Record one state's change-of-control decision."""
    return get_success_data(
        api.decide_change_of_control(
            control_person_id,
            change_of_control_payload(decision),
            make_state_regulator_headers(jurisdiction_id),
        )
    )


# ---------------------------------------------------------------------------
# Applications and issuance
# ---------------------------------------------------------------------------


def create_application(
    api: Api, licensee_id: str, jurisdiction_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_application(
            application_payload(licensee_id, jurisdiction_id, **overrides), MANAGER_HEADERS
        ),
        201,
    )


def submit_application(api: Api, application_id: str) -> Dict[str, Any]:
    return get_success_data(api.submit_application(application_id, MANAGER_HEADERS))


def review_application(
    api: Api, application_id: str, jurisdiction_id: str, action: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.review_application(
            application_id,
            review_action_payload(action, **overrides),
            make_state_regulator_headers(jurisdiction_id),
        )
    )


def find_license_by_application(api: Api, application_id: str) -> Dict[str, Any]:
    """Discover the licence an approval minted by filtering on application_id."""
    data = get_success_data(
        api.list_state_licenses(MANAGER_HEADERS, params={"application_id": application_id})
    )
    assert data, f"no licence was minted for application {application_id}"
    return data[0]


def get_license(api: Api, license_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_state_license(license_id, MANAGER_HEADERS))


def post_bond(api: Api, license_id: str, amount_cents: Optional[int] = None) -> Dict[str, Any]:
    """Post a bond at least equal to the licence's current requirement."""
    if amount_cents is None:
        amount_cents = get_license(api, license_id)["bond_requirement_cents"]
    return get_success_data(
        api.post_bond(license_id, bond_payload(amount_cents), MANAGER_HEADERS)
    )


def setup_pending_bond_license(
    api: Api,
    jurisdiction_config: Optional[Dict[str, Any]] = None,
    licensee_overrides: Optional[Dict[str, Any]] = None,
    application_overrides: Optional[Dict[str, Any]] = None,
) -> Scenario:
    """Carry one application all the way to an approved, unbonded licence."""
    jurisdiction = create_jurisdiction(api, jurisdiction_config)
    licensee = create_licensee(api, **(licensee_overrides or {}))
    application = create_application(
        api, licensee["id"], jurisdiction["id"], **(application_overrides or {})
    )
    submit_application(api, application["id"])
    review_application(api, application["id"], jurisdiction["id"], "START_REVIEW")
    review_application(api, application["id"], jurisdiction["id"], "APPROVE")
    license_row = find_license_by_application(api, application["id"])
    return Scenario(
        jurisdiction_id=jurisdiction["id"],
        licensee_id=licensee["id"],
        application_id=application["id"],
        license_id=license_row["id"],
        extra={"jurisdiction": jurisdiction, "licensee": licensee, "license": license_row},
    )


def setup_active_license(
    api: Api,
    jurisdiction_config: Optional[Dict[str, Any]] = None,
    licensee_overrides: Optional[Dict[str, Any]] = None,
    application_overrides: Optional[Dict[str, Any]] = None,
    bond_amount_cents: Optional[int] = None,
) -> Scenario:
    """The full chain: jurisdiction, licensee, application, approval and bond."""
    scenario = setup_pending_bond_license(
        api, jurisdiction_config, licensee_overrides, application_overrides
    )
    license_row = post_bond(api, scenario.license_id, bond_amount_cents)
    scenario.extra["license"] = license_row
    return scenario


def add_license_in_jurisdiction(
    api: Api,
    licensee_id: str,
    jurisdiction_config: Dict[str, Any],
    application_overrides: Optional[Dict[str, Any]] = None,
    bond_amount_cents: Optional[int] = None,
) -> Dict[str, Any]:
    """Give an existing licensee a second authorised licence in another state."""
    jurisdiction = create_jurisdiction(api, jurisdiction_config)
    application = create_application(
        api, licensee_id, jurisdiction["id"], **(application_overrides or {})
    )
    submit_application(api, application["id"])
    review_application(api, application["id"], jurisdiction["id"], "START_REVIEW")
    review_application(api, application["id"], jurisdiction["id"], "APPROVE")
    license_row = find_license_by_application(api, application["id"])
    license_row = post_bond(api, license_row["id"], bond_amount_cents)
    return {
        "jurisdiction": jurisdiction,
        "application": application,
        "license": license_row,
    }


# ---------------------------------------------------------------------------
# Obligations and call reports
# ---------------------------------------------------------------------------


def adjust_obligations(api: Api, license_id: str, delta_cents: int, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.adjust_obligations(
            license_id, obligations_payload(delta_cents, **overrides), MANAGER_HEADERS
        )
    )


def file_call_report(
    api: Api,
    license_id: str,
    period_label: str,
    transmission_volume_cents: int,
    transaction_count: int,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.file_call_report(
            call_report_payload(
                license_id,
                period_label,
                transmission_volume_cents,
                transaction_count,
                **overrides,
            ),
            MANAGER_HEADERS,
        ),
        201,
    )


# ---------------------------------------------------------------------------
# Delegates and authorizations
# ---------------------------------------------------------------------------


def create_delegate(api: Api, licensee_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_delegate(delegate_payload(licensee_id, **overrides), MANAGER_HEADERS), 201
    )


def review_delegate(
    api: Api,
    delegate_id: str,
    training_score: int = 90,
    aml_test_score: int = 85,
    recordkeeping_score: int = 80,
) -> Dict[str, Any]:
    """Score a delegate's oversight so that it can be put to work."""
    return get_success_data(
        api.submit_oversight_review(
            delegate_id,
            oversight_review_payload(training_score, aml_test_score, recordkeeping_score),
            OFFICER_HEADERS,
        )
    )


def create_authorization(
    api: Api,
    delegate_id: str,
    license_id: str,
    effective_date: str,
    expiry_date: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_delegate_authorization(
            delegate_authorization_payload(
                delegate_id, license_id, effective_date, expiry_date, **overrides
            ),
            MANAGER_HEADERS,
        ),
        201,
    )


def activate_authorization(api: Api, authorization_id: str) -> Dict[str, Any]:
    return get_success_data(api.activate_authorization(authorization_id, MANAGER_HEADERS))


def terminate_authorization(api: Api, authorization_id: str) -> Dict[str, Any]:
    return get_success_data(api.terminate_authorization(authorization_id, MANAGER_HEADERS))


def setup_active_authorization(
    api: Api,
    scenario: Scenario,
    effective_date: str = "2026-09-01T00:00:00Z",
    expiry_date: str = "2026-09-30T00:00:00Z",
    delegate_overrides: Optional[Dict[str, Any]] = None,
    scores: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Appoint an agent, score it, authorise it for the licence and activate."""
    delegate = create_delegate(api, scenario.licensee_id, **(delegate_overrides or {}))
    review_delegate(api, delegate["id"], **(scores or {}))
    authorization = create_authorization(
        api, delegate["id"], scenario.license_id, effective_date, expiry_date
    )
    authorization = activate_authorization(api, authorization["id"])
    scenario.delegate_id = delegate["id"]
    scenario.authorization_id = authorization["id"]
    return {"delegate": delegate, "authorization": authorization}


# ---------------------------------------------------------------------------
# Holdings and coverage tests
# ---------------------------------------------------------------------------


def record_holding(
    api: Api,
    licensee_id: str,
    asset_class: str,
    counterparty_name: str,
    book_value_cents: int,
    market_value_cents: int,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_investment_holding(
            investment_holding_payload(
                licensee_id,
                asset_class,
                counterparty_name,
                book_value_cents,
                market_value_cents,
                **overrides,
            ),
            OFFICER_HEADERS,
        ),
        201,
    )


def record_holdings(
    api: Api, licensee_id: str, holdings: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Record a whole holding set in the order given."""
    return [record_holding(api, licensee_id, **holding) for holding in holdings]


def dispose_holding(api: Api, holding_id: str) -> Dict[str, Any]:
    return get_success_data(api.dispose_investment_holding(holding_id, OFFICER_HEADERS))


def open_investment_test(
    api: Api, licensee_id: str, method: str, **overrides: Any
) -> Dict[str, Any]:
    """Open a coverage test, reading the licensee version the guard demands."""
    expected_version = overrides.pop(
        "expected_licensee_version", get_licensee(api, licensee_id)["version"]
    )
    return get_success_data(
        api.create_investment_test(
            investment_test_payload(licensee_id, method, expected_version, **overrides),
            OFFICER_HEADERS,
        ),
        201,
    )


def prepare_investment_test(api: Api, test_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.prepare_investment_test(test_id, headers or OFFICER_HEADERS)
    )


def certify_investment_test(api: Api, test_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(api.certify_investment_test(test_id, headers or CHIEF_HEADERS))


def certify_shortfall_test(api: Api, licensee_id: str, method: str = "ELIGIBLE_MARKET") -> Dict[str, Any]:
    """Run one whole test cycle to a certified verdict on the current figures."""
    test = open_investment_test(api, licensee_id, method)
    prepare_investment_test(api, test["id"])
    return certify_investment_test(api, test["id"])


# ---------------------------------------------------------------------------
# Examinations, information requests and enforcement
# ---------------------------------------------------------------------------


def schedule_exam(
    api: Api,
    licensee_id: str,
    lead_jurisdiction_id: str,
    fieldwork_start: str,
    fieldwork_end: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_exam(
            exam_payload(
                licensee_id, lead_jurisdiction_id, fieldwork_start, fieldwork_end, **overrides
            ),
            make_state_regulator_headers(lead_jurisdiction_id),
        ),
        201,
    )


def change_exam_status(
    api: Api, exam_id: str, lead_jurisdiction_id: str, to_status: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.change_exam_status(
            exam_id,
            exam_status_payload(to_status, **overrides),
            make_state_regulator_headers(lead_jurisdiction_id),
        )
    )


def setup_exam_in_fieldwork(
    api: Api,
    licensee_id: str,
    lead_jurisdiction_id: str,
    fieldwork_start: str = "2026-09-01T00:00:00Z",
    fieldwork_end: str = "2026-09-30T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """Schedule an examination and move it into FIELDWORK."""
    exam = schedule_exam(
        api, licensee_id, lead_jurisdiction_id, fieldwork_start, fieldwork_end, **overrides
    )
    return change_exam_status(api, exam["id"], lead_jurisdiction_id, "FIELDWORK")


def open_information_request(
    api: Api, exam_id: str, jurisdiction_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_information_request(
            information_request_payload(exam_id, jurisdiction_id, **overrides),
            make_state_regulator_headers(jurisdiction_id),
        ),
        201,
    )


def respond_to_information_request(
    api: Api, request_id: str, submitted_item_count: int, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.respond_to_information_request(
            request_id,
            information_response_payload(submitted_item_count, **overrides),
            MANAGER_HEADERS,
        )
    )


def disposition_information_request(
    api: Api, request_id: str, jurisdiction_id: str, decision: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.disposition_information_request(
            request_id,
            disposition_payload(decision, **overrides),
            make_state_regulator_headers(jurisdiction_id),
        )
    )


def issue_enforcement_action(
    api: Api, license_id: str, jurisdiction_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_enforcement_action(
            enforcement_payload(license_id, jurisdiction_id, **overrides),
            make_state_regulator_headers(jurisdiction_id),
        ),
        201,
    )


def respond_to_enforcement_action(
    api: Api, action_id: str, response: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.respond_to_enforcement_action(
            action_id, enforcement_response_payload(response, **overrides), MANAGER_HEADERS
        )
    )


def resolve_enforcement_action(
    api: Api, action_id: str, jurisdiction_id: str, outcome: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.resolve_enforcement_action(
            action_id,
            enforcement_resolution_payload(outcome, **overrides),
            make_state_regulator_headers(jurisdiction_id),
        )
    )
