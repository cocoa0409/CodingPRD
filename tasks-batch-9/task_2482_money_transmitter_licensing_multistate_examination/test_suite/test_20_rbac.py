"""Role, identity and scope enforcement on the licensing estate.

Each test here pins exactly one rung of the PRD 2.7 evaluation ladder:
authentication before role authorization, role authorization before entity-backed
scope, and scope before the state and business rules that sit underneath. The
rejection tests read the target row back afterwards to prove that a refused
request moved nothing, and the shared-permission tests drive the same operation
with both of the roles the PRD authorizes for it.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import MoneyTransmitterApiClient
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_APPLICATION_INVALID_STATE,
    ERR_FORBIDDEN_SCOPE,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)
from test_helpers.test_users import (
    CHIEF_HEADERS,
    MANAGER_HEADERS,
    OFFICER_HEADERS,
    make_delegate_operator_headers,
    make_headers_without_role,
    make_headers_without_user_id,
    make_state_regulator_headers,
)

# ---------------------------------------------------------------------------
# Role authorization (ladder step 2)
# ---------------------------------------------------------------------------


def test_registering_a_licensee_as_a_state_regulator_returns_unauthorized(
    api: MoneyTransmitterApiClient,
) -> None:
    """The role rung outranks both jurisdiction reference resolution and the entity-backed scope rung: a StateRegulator posting to the LicensingManager-only registration endpoint is refused for its role even though its X-User-ID is not a Jurisdiction that exists at all.

    PRD 2.1: "A well-identified caller invoking an operation that its role is not authorized for is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD 2.1: "`LicensingManager` is the licensee-side owner of the estate — it registers the business, files applications, posts bonds, adjusts obligations, files call reports and renewals, appoints delegates and answers enforcement actions."
    PRD 2.1: "When `X-User-Role` is `StateRegulator`, `X-User-ID` is the `id` of the acting `Jurisdiction`; ownership checks compare the resource's jurisdiction-of-record field to `X-User-ID`."
    PRD 2.1: "Any scope violation on a `StateRegulator` or `DelegateOperator` write is rejected with `ERR_FORBIDDEN_SCOPE` (HTTP 403)."
    PRD 2.7: "When several rules could reject the same request, the system evaluates them in a fixed order and returns the error of the first rule that fails."
    PRD 3.1: "A `Licensee` is created with its `legal_name` and its nine-digit `ein`, which must be unique across licensees — a second registration under an existing employer identification number is rejected with `ERR_DUPLICATE_EIN`."

    Design: Corner/rbac/licensee_side_writes_by_a_regulator_returns_unauthorized
    """
    rejected = api.create_licensee(
        F.licensee_payload(), make_state_regulator_headers(NON_EXISTENT_UUID)
    )
    validate_error(rejected, ERR_UNAUTHORIZED)

    # Nothing was registered: the seed employer identification number is still
    # free, so the very same body succeeds for the role that owns the operation.
    created = validate_success(
        api.create_licensee(F.licensee_payload(), MANAGER_HEADERS), 201
    )
    assert created["legal_name"] == C.SEED_LICENSEE_NAME
    assert created["ein"] == C.SEED_LICENSEE_EIN, "the refused attempt must not have taken the ein"


def test_certifying_a_prepared_test_as_a_compliance_officer_returns_unauthorized(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """The role rung outranks the segregation-of-duties rung that would also have fired: the ComplianceOfficer who prepared the test is refused certification for its role, and the ChiefComplianceOfficer then certifies the untouched PREPARED row.

    PRD 3.7: "Certification is the `ChiefComplianceOfficer`'s alone and carries an optional `attestation_note`."
    PRD 2.1: "A well-identified caller invoking an operation that its role is not authorized for is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD 2.10: "The certifying identity must differ from the preparing identity; a certification attempt whose `X-User-ID` equals the recorded `prepared_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."
    PRD 2.7: "When several rules could reject the same request, the system evaluates them in a fixed order and returns the error of the first rule that fails."
    PRD 2.10: "`prepared_by_user_id` records the `X-User-ID` of whoever ran the prepare step; `certified_by_user_id` records the `X-User-ID` of whoever certified."
    PRD 2.4: "Almost every resource additionally carries an `updated_at` — refreshed on every mutation, in the same format — and a `version`, an integer that starts at 1 on creation and increments by one on every mutation of that row."
    PRD 3.7: "`obligations_cents` snapshots the licensee's `aggregate_outstanding_obligations_cents`; `investment_value_cents` snapshots the permissible investment value computed under this row's own `method`; `coverage_ratio_bps` is that value multiplied by 10000 divided by `obligations_cents` and rounded down, or exactly 10000 when `obligations_cents` is zero; `shortfall_cents` is `obligations_cents` minus `investment_value_cents`, or zero when that difference would be negative — never a negative number; and `result` becomes `PASS` when `coverage_ratio_bps` is at least 10000 and `SHORTFALL` otherwise, having been null until preparation."

    Design: Corner/rbac/certification_by_the_preparer_role_returns_unauthorized
    """
    fx.record_holding(api, licensee["id"], "CASH", "First Republic Trust", 4_000_000, 4_000_000)
    test = fx.open_investment_test(api, licensee["id"], "ELIGIBLE_MARKET")
    prepared = fx.prepare_investment_test(api, test["id"], OFFICER_HEADERS)
    assert prepared["status"] == "PREPARED"
    assert prepared["prepared_by_user_id"] == OFFICER_HEADERS["X-User-ID"]

    rejected = api.certify_investment_test(test["id"], OFFICER_HEADERS, F.certify_payload())
    validate_error(rejected, ERR_UNAUTHORIZED)

    held = validate_success(api.get_investment_test(test["id"], OFFICER_HEADERS))
    assert held["status"] == "PREPARED", "a refused certification must not move the test"
    assert held["version"] == prepared["version"]
    assert held.get("certified_by_user_id") != OFFICER_HEADERS["X-User-ID"]

    certified = validate_success(
        api.certify_investment_test(test["id"], CHIEF_HEADERS, F.certify_payload())
    )
    assert certified["status"] == "CERTIFIED"
    assert certified["certified_by_user_id"] == CHIEF_HEADERS["X-User-ID"]
    assert certified["result"] == "PASS"
    assert certified["coverage_ratio_bps"] == 10_000


def test_preparing_a_test_is_shared_by_the_officer_and_the_chief_officer(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """Preparation is shared while certification is exclusive: the ComplianceOfficer and the ChiefComplianceOfficer each prepare a test of their own and each is recorded as its preparer, so the role rung admits both identities on this step.

    PRD 2.10: "Because only a `ChiefComplianceOfficer` may certify, and both a `ComplianceOfficer` and a `ChiefComplianceOfficer` may prepare, the practical effect is that a chief compliance officer who prepared a test must hand certification to a colleague."
    PRD 2.10: "`prepared_by_user_id` records the `X-User-ID` of whoever ran the prepare step; `certified_by_user_id` records the `X-User-ID` of whoever certified."
    PRD 3.7: "Preparation, admissible only from `DRAFT`, is where the numbers are frozen."
    PRD 2.1: "`ChiefComplianceOfficer` holds the certification right and shares the holdings and test-creation rights with the `ComplianceOfficer`."

    Design: Corner/rbac/certification_by_the_preparer_role_returns_unauthorized
    """
    second_licensee = fx.create_licensee(
        api, legal_name="Cascade Remit Inc", ein="741100002"
    )

    officer_test = fx.open_investment_test(api, licensee["id"], "ELIGIBLE_MARKET")
    by_officer = validate_success(
        api.prepare_investment_test(officer_test["id"], OFFICER_HEADERS)
    )
    assert by_officer["status"] == "PREPARED"
    assert by_officer["prepared_by_user_id"] == OFFICER_HEADERS["X-User-ID"]

    chief_test = fx.open_investment_test(api, second_licensee["id"], "BOOK_VALUE")
    by_chief = validate_success(
        api.prepare_investment_test(chief_test["id"], CHIEF_HEADERS)
    )
    assert by_chief["status"] == "PREPARED"
    assert by_chief["prepared_by_user_id"] == CHIEF_HEADERS["X-User-ID"]


# ---------------------------------------------------------------------------
# Authentication (ladder step 1)
# ---------------------------------------------------------------------------


def test_a_request_without_x_user_id_is_unauthenticated_despite_an_empty_body(
    api: MoneyTransmitterApiClient,
) -> None:
    """The identity rung outranks the request-shape rung: a registration carrying no X-User-ID and an empty body reports the missing identity rather than the missing legal_name and ein, and no licensee row is created.

    PRD 2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which it acts."
    PRD 2.1: "A request missing either header, or presenting a role string that is not one of the six declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD 2.7: "When several rules could reject the same request, the system evaluates them in a fixed order and returns the error of the first rule that fails."
    PRD 2.7: "**Request shape** — required fields present, enum values inside their declared sets, money and count fields integers no less than zero, ISO 8601 datetimes well formed, `limit` within 1 through 100 and `offset` no less than zero: `ERR_INVALID_REQUEST`."
    PRD 3.1: "A `Licensee` is created with its `legal_name` and its nine-digit `ein`, which must be unique across licensees — a second registration under an existing employer identification number is rejected with `ERR_DUPLICATE_EIN`."

    Design: Corner/rbac/request_missing_x_user_id_headers_returns_unauthenticated
    """
    rejected = api.create_licensee({}, make_headers_without_user_id(C.ROLE_LICENSING_MANAGER))
    validate_error(rejected, ERR_UNAUTHENTICATED)

    created = validate_success(
        api.create_licensee(F.licensee_payload(), MANAGER_HEADERS), 201
    )
    assert created["legal_name"] == C.SEED_LICENSEE_NAME
    assert created["ein"] == C.SEED_LICENSEE_EIN, "the refused attempt must not have taken the ein"


def test_a_request_without_x_user_role_is_unauthenticated_despite_an_empty_body(
    api: MoneyTransmitterApiClient,
) -> None:
    """The identity rung outranks the request-shape rung on the other half of the header pair too: a registration that names a principal but declares no role reports the missing identity rather than the missing body fields.

    PRD 2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which it acts."
    PRD 2.1: "A request missing either header, or presenting a role string that is not one of the six declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD 2.7: "When several rules could reject the same request, the system evaluates them in a fixed order and returns the error of the first rule that fails."
    PRD 3.1: "A `Licensee` is created with its `legal_name` and its nine-digit `ein`, which must be unique across licensees — a second registration under an existing employer identification number is rejected with `ERR_DUPLICATE_EIN`."

    Design: Corner/rbac/request_missing_x_user_id_headers_returns_unauthenticated
    """
    rejected = api.create_licensee({}, make_headers_without_role(MANAGER_HEADERS["X-User-ID"]))
    validate_error(rejected, ERR_UNAUTHENTICATED)

    created = validate_success(
        api.create_licensee(F.licensee_payload(), MANAGER_HEADERS), 201
    )
    assert created["legal_name"] == C.SEED_LICENSEE_NAME
    assert created["ein"] == C.SEED_LICENSEE_EIN, "the refused attempt must not have taken the ein"


# ---------------------------------------------------------------------------
# Regulatory scope (ladder step 5)
# ---------------------------------------------------------------------------


def test_review_action_on_another_states_application_returns_forbidden_scope(
    api: MoneyTransmitterApiClient, ca_jurisdiction: dict, licensee: dict
) -> None:
    """The scope rung is the only rung that can fail here: the Texas regulator holds the same authorized role, the application resolves and is squarely UNDER_REVIEW, yet only the California regulator of record can approve it and mint the licence.

    PRD 2.1: "Concretely, the acting jurisdiction must equal the application's `jurisdiction_id`, the licence's `jurisdiction_id`, the exam's `lead_jurisdiction_id`, the information request's `jurisdiction_id`, or the enforcement action's `jurisdiction_id`, depending on the target."
    PRD 2.1: "Any scope violation on a `StateRegulator` or `DelegateOperator` write is rejected with `ERR_FORBIDDEN_SCOPE` (HTTP 403)."
    PRD 3.3: "A `StateRegulator` whose `X-User-ID` equals the application's `jurisdiction_id` posts a review `action` with an optional `note`."
    PRD 3.3: "Approval stamps `decision_at` and mints a licence."
    PRD 3.3: "It starts with `license_status` `PENDING_BOND`, `reporting_status` `CURRENT`, `expansion_gate` `BLOCKED`, `bond_status` `NONE`, `outstanding_obligations_cents` zero, and `bond_requirement_cents` copied from the application's `required_bond_cents`."
    PRD 3.3: "The new `StateLicense` records its `licensee_id`, its `jurisdiction_id` and the `application_id` of the approved application; it copies `license_class` from the application; it receives a server-minted `license_number` of the form `MT-` followed by the jurisdiction's `state_code`, a second hyphen, and a six-digit sequence number that starts at `000001` and advances independently within each jurisdiction."
    PRD 3.3: "The approval response returns the application, not the licence, so the minted licence is discovered by filtering the licence register on its `application_id`."
    PRD 2.4: "Almost every resource additionally carries an `updated_at` — refreshed on every mutation, in the same format — and a `version`, an integer that starts at 1 on creation and increments by one on every mutation of that row."

    Design: Corner/rbac/review_action_by_another_state_returns_forbidden
    """
    texas = fx.create_jurisdiction(api, C.TX_CONFIG)
    application = fx.create_application(api, licensee["id"], ca_jurisdiction["id"])
    fx.submit_application(api, application["id"])
    under_review = fx.review_application(
        api, application["id"], ca_jurisdiction["id"], "START_REVIEW"
    )
    assert under_review["status"] == "UNDER_REVIEW"

    rejected = api.review_application(
        application["id"],
        F.review_action_payload("APPROVE"),
        make_state_regulator_headers(texas["id"]),
    )
    validate_error(rejected, ERR_FORBIDDEN_SCOPE)

    held = validate_success(api.get_application(application["id"], MANAGER_HEADERS))
    assert held["status"] == "UNDER_REVIEW", "an out-of-scope review must not move the application"
    assert held["version"] == under_review["version"]
    rows, meta = validate_paginated(
        api.list_state_licenses(MANAGER_HEADERS, params={"application_id": application["id"]})
    )
    assert rows == [] and meta["total_count"] == 0, "no licence may be minted by another state"

    approved = validate_success(
        api.review_application(
            application["id"],
            F.review_action_payload("APPROVE"),
            make_state_regulator_headers(ca_jurisdiction["id"]),
        )
    )
    assert approved["status"] == "APPROVED"
    minted, minted_meta = validate_paginated(
        api.list_state_licenses(MANAGER_HEADERS, params={"application_id": application["id"]})
    )
    assert minted_meta["total_count"] == 1, "the approval mints exactly one licence"
    assert minted[0]["license_status"] == "PENDING_BOND"
    assert minted[0]["jurisdiction_id"] == ca_jurisdiction["id"]


def test_scope_outranks_application_state_for_another_states_regulator(
    api: MoneyTransmitterApiClient, ca_jurisdiction: dict, licensee: dict
) -> None:
    """The scope rung outranks the state-admissibility rung: the Texas regulator approving a merely SUBMITTED California application is refused on scope, while the California regulator making the identical call is refused on the application's state, proving the lower rung was live.

    PRD 2.1: "Concretely, the acting jurisdiction must equal the application's `jurisdiction_id`, the licence's `jurisdiction_id`, the exam's `lead_jurisdiction_id`, the information request's `jurisdiction_id`, or the enforcement action's `jurisdiction_id`, depending on the target."
    PRD 2.1: "Any scope violation on a `StateRegulator` or `DelegateOperator` write is rejected with `ERR_FORBIDDEN_SCOPE` (HTTP 403)."
    PRD 3.3: "Approval and outright denial both come out of `UNDER_REVIEW`."
    PRD 2.7: "And because state admissibility precedes fiscal sufficiency, an approval on an application that is not `UNDER_REVIEW` reports the invalid state rather than a net-worth shortfall, even when both conditions hold."
    PRD 2.4: "Almost every resource additionally carries an `updated_at` — refreshed on every mutation, in the same format — and a `version`, an integer that starts at 1 on creation and increments by one on every mutation of that row."

    Design: Corner/rbac/review_action_by_another_state_returns_forbidden
    """
    texas = fx.create_jurisdiction(api, C.TX_CONFIG)
    application = fx.create_application(api, licensee["id"], ca_jurisdiction["id"])
    submitted = fx.submit_application(api, application["id"])
    assert submitted["status"] == "SUBMITTED"

    out_of_scope = api.review_application(
        application["id"],
        F.review_action_payload("APPROVE"),
        make_state_regulator_headers(texas["id"]),
    )
    validate_error(out_of_scope, ERR_FORBIDDEN_SCOPE)

    in_scope_wrong_state = api.review_application(
        application["id"],
        F.review_action_payload("APPROVE"),
        make_state_regulator_headers(ca_jurisdiction["id"]),
    )
    validate_error(in_scope_wrong_state, ERR_APPLICATION_INVALID_STATE)

    held = validate_success(api.get_application(application["id"], MANAGER_HEADERS))
    assert held["status"] == "SUBMITTED", "neither refusal may move the application"
    assert held["version"] == submitted["version"]


def test_oversight_review_for_another_delegate_returns_forbidden_scope(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """The scope rung is the only rung that can fail here: the DelegateOperator role is authorized for oversight reviews and the target delegate resolves, so scoring a sibling delegate is refused purely on identity scope and leaves that delegate's score null.

    PRD 2.1: "When `X-User-Role` is `DelegateOperator`, `X-User-ID` is the `id` of the acting `Delegate`; an oversight review may only be submitted for the delegate whose `id` equals `X-User-ID`, and the delegate's own read access is likewise limited to its own rows."
    PRD 2.1: "Any scope violation on a `StateRegulator` or `DelegateOperator` write is rejected with `ERR_FORBIDDEN_SCOPE` (HTTP 403)."
    PRD 3.6: "A `DelegateOperator` submitting for a delegate other than the one its `X-User-ID` names is rejected with `ERR_FORBIDDEN_SCOPE`."
    PRD 3.6: "Crucially, `oversight_score` starts null and `last_oversight_review_at` starts null, so a freshly appointed delegate cannot be put to work until someone has actually reviewed it."
    PRD 3.6: "The row starts in `ONBOARDING`, the other statuses being `ACTIVE`, `SUSPENDED` and the terminal `TERMINATED`."
    PRD 2.4: "Almost every resource additionally carries an `updated_at` — refreshed on every mutation, in the same format — and a `version`, an integer that starts at 1 on creation and increments by one on every mutation of that row."

    Design: Corner/rbac/oversight_review_of_another_delegate_returns_forbidden
    """
    first = fx.create_delegate(api, licensee["id"], legal_name=C.SEED_DELEGATE_NAME)
    second = fx.create_delegate(
        api, licensee["id"], legal_name="Copper Kettle Grocery", delegate_type="AGENT"
    )

    rejected = api.submit_oversight_review(
        first["id"],
        F.oversight_review_payload(100, 100, 100),
        make_delegate_operator_headers(second["id"]),
    )
    validate_error(rejected, ERR_FORBIDDEN_SCOPE)

    held = validate_success(api.get_delegate(first["id"], MANAGER_HEADERS))
    assert held["oversight_score"] is None, "a refused review must leave the score null"
    assert held["last_oversight_review_at"] is None
    assert held["version"] == first["version"]
    assert held["status"] == "ONBOARDING"


def test_oversight_review_is_shared_by_the_officer_and_the_delegates_own_operator(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """Both roles the endpoint authorizes succeed on the same operation: the operator scores its own delegate row and the ComplianceOfficer scores a delegate it does not own, each score being the floored weighted sum of the three components.

    PRD 3.6: "Either a `ComplianceOfficer` — for any delegate — or a `DelegateOperator` acting for its own delegate row submits three component scores, each on a nought-to-one-hundred scale: `training_score`, `aml_test_score` and `recordkeeping_score`."
    PRD 3.6: "The resulting `oversight_score` is the training score weighted at 4000 basis points, plus the anti-money-laundering test score weighted at 3500 basis points, plus the recordkeeping score weighted at 2500 basis points, that sum divided by 10000 and rounded down to a whole number."
    PRD 3.6: "`last_oversight_review_at` is stamped from the logical clock."
    PRD 2.1: "`DelegateOperator` is an agent's own operator and may self-report oversight metrics for its own delegate row only."

    Design: Corner/rbac/oversight_review_of_another_delegate_returns_forbidden
    """
    first = fx.create_delegate(api, licensee["id"], legal_name=C.SEED_DELEGATE_NAME)
    second = fx.create_delegate(
        api, licensee["id"], legal_name="Copper Kettle Grocery", delegate_type="AGENT"
    )

    self_reported = validate_success(
        api.submit_oversight_review(
            second["id"],
            F.oversight_review_payload(100, 100, 100),
            make_delegate_operator_headers(second["id"]),
        )
    )
    assert self_reported["oversight_score"] == 100
    assert self_reported["last_oversight_review_at"].startswith("2026-08-01T00:00:00")

    by_officer = validate_success(
        api.submit_oversight_review(
            first["id"], F.oversight_review_payload(80, 80, 80), OFFICER_HEADERS
        )
    )
    assert by_officer["oversight_score"] == 80
    assert by_officer["last_oversight_review_at"].startswith("2026-08-01T00:00:00")


# ---------------------------------------------------------------------------
# Genuinely shared licensee-side operations
# ---------------------------------------------------------------------------


def test_information_request_response_is_shared_by_manager_and_officer(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """Both licensee-side roles answer sibling requests on one examination and both land in RESPONDED, and because a RESPONDED request is still an open matter the exam's open_request_count holds at two rather than falling.

    PRD 3.8: "A `LicensingManager` or `ComplianceOfficer` responds with a `submitted_item_count` and a `narrative`."
    PRD 3.8: "On success the request moves to `RESPONDED`, `submitted_item_count` is stored and `responded_at` is stamped."
    PRD 3.8: "`open_request_count` does not move: a `RESPONDED` request is still an open matter as far as the exam is concerned, which is exactly why responding to every request is not enough to let the lead draft its report — each one must also be accepted."
    PRD 3.8: "The row starts in `OPEN` — the other statuses being `RESPONDED`, `OVERDUE` and the terminal `ACCEPTED` — with `reopen_count` and `submitted_item_count` at zero and `responded_at` null."
    PRD 3.8: "Because `open_request_count` is by definition the number of the exam's requests sitting in `OPEN`, `OVERDUE` or `RESPONDED`, opening a request raises it by one."
    PRD 2.4: "Every deadline, window and `*_at` stamp in the specification reads that clock — response windows, certification windows, deficiency deadlines, bond-cancellation notice periods, call-report lateness and enforcement response windows are all evaluated against it."

    Design: Corner/rbac/information_response_is_shared_between_the_two_licensee_side_roles
    """
    regulator = make_state_regulator_headers(active_license.jurisdiction_id)
    exam = fx.setup_exam_in_fieldwork(
        api, active_license.licensee_id, active_license.jurisdiction_id
    )
    assert exam["status"] == "FIELDWORK"

    first_request = fx.open_information_request(
        api,
        exam["id"],
        active_license.jurisdiction_id,
        subject="Delegate settlement ledgers",
        requested_item_count=1,
    )
    second_request = fx.open_information_request(
        api,
        exam["id"],
        active_license.jurisdiction_id,
        subject="Permissible investment schedule",
        requested_item_count=1,
    )
    assert first_request["status"] == "OPEN" and second_request["status"] == "OPEN"

    before = validate_success(api.get_exam(exam["id"], regulator))
    assert before["open_request_count"] == 2, "each opened request raises the open count by one"

    by_manager = validate_success(
        api.respond_to_information_request(
            first_request["id"], F.information_response_payload(1), MANAGER_HEADERS
        )
    )
    assert by_manager["status"] == "RESPONDED"
    assert by_manager["submitted_item_count"] == 1
    assert by_manager["responded_at"].startswith("2026-08-01T00:00:00")

    by_officer = validate_success(
        api.respond_to_information_request(
            second_request["id"], F.information_response_payload(1), OFFICER_HEADERS
        )
    )
    assert by_officer["status"] == "RESPONDED"
    assert by_officer["submitted_item_count"] == 1
    assert by_officer["responded_at"].startswith("2026-08-01T00:00:00")

    after = validate_success(api.get_exam(exam["id"], regulator))
    assert after["open_request_count"] == 2, "a RESPONDED request is still an open matter"
    assert after["status"] == "FIELDWORK", "responding does not advance the examination"
