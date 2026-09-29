"""Referential-integrity validations: jurisdiction match, participation, multistate
eligibility and the change-of-control approval quorum.

Every test drives a live server through PRD-declared endpoints only. The runner
restarts the server before each test, so the database starts empty and the logical
clock starts at 2026-08-01T00:00:00Z.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import MoneyTransmitterApiClient
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_DUPLICATE_APPROVAL,
    ERR_JURISDICTION_MISMATCH,
    ERR_JURISDICTION_NOT_MULTISTATE,
    ERR_JURISDICTION_NOT_PARTICIPATING,
)
from test_helpers.test_users import MANAGER_HEADERS, make_state_regulator_headers


def test_enforcement_action_naming_another_state_is_a_jurisdiction_mismatch(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """Texas may not police a California licence, but California may.

    PRD 3.9: "When an examination finding or an operational failure warrants it, a `StateRegulator` issues an `EnforcementAction` against a `state_license_id`."
    PRD 3.9: "The action names its own `jurisdiction_id`, which must equal the target licence's `jurisdiction_id` — a state may not police another state's licence, and the attempt is rejected with `ERR_JURISDICTION_MISMATCH` (HTTP 422)."
    PRD 3.9: "The action starts in `ISSUED` and `issued_at` is stamped from the logical clock, which starts a twenty-day response window."

    Design: Corner/validations/enforcement_action_naming_another_state_rejects_with_jurisdiction_mismatch
    """
    ca_id = active_license.jurisdiction_id
    license_id = active_license.license_id
    texas = fx.create_jurisdiction(api, C.TX_CONFIG)

    before = fx.get_license(api, license_id)
    assert before["license_status"] == "ACTIVE"
    assert before["jurisdiction_id"] == ca_id

    # Texas names itself as the issuing state against a licence held in California.
    rejected = api.create_enforcement_action(
        F.enforcement_payload(
            license_id,
            texas["id"],
            basis="UNAUTHORIZED_DELEGATE",
            penalty_cents=1_000_000,
            remediation_deadline_at="2026-10-01T00:00:00Z",
        ),
        make_state_regulator_headers(texas["id"]),
    )
    validate_error(rejected, ERR_JURISDICTION_MISMATCH)

    empty, empty_meta = validate_paginated(
        api.list_enforcement_actions(MANAGER_HEADERS, params={"state_license_id": license_id})
    )
    assert empty == []
    assert empty_meta["total_count"] == 0

    after_rejection = fx.get_license(api, license_id)
    A.assert_license_state(after_rejection, license_status="ACTIVE", bond_status="POSTED")
    A.assert_version_unchanged(before, after_rejection)

    # The adjacent accepted case: the state that holds the licence issues the action.
    accepted = validate_success(
        api.create_enforcement_action(
            F.enforcement_payload(
                license_id,
                ca_id,
                basis="UNAUTHORIZED_DELEGATE",
                penalty_cents=1_000_000,
                remediation_deadline_at="2026-10-01T00:00:00Z",
            ),
            make_state_regulator_headers(ca_id),
        ),
        201,
    )
    A.assert_audit_stamps(accepted)
    assert accepted["jurisdiction_id"] == ca_id
    assert accepted["state_license_id"] == license_id
    assert accepted["status"] == "ISSUED"
    assert accepted["penalty_cents"] == 1_000_000
    assert accepted["issued_at"][:19] == "2026-08-01T00:00:00"  # the seeded logical clock

    listed, listed_meta = validate_paginated(
        api.list_enforcement_actions(MANAGER_HEADERS, params={"state_license_id": license_id})
    )
    assert [row["id"] for row in listed] == [accepted["id"]]
    assert listed_meta["total_count"] == 1


def test_information_request_from_a_non_participating_state_rejects(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """Nevada is neither the lead nor a participant, so it may not demand records.

    PRD 3.8: "The requesting state must be the exam's lead or appear in `participating_jurisdiction_ids`; an outsider's request is rejected with `ERR_JURISDICTION_NOT_PARTICIPATING` (HTTP 422)."
    PRD 3.8: "Its `due_at` is the current logical clock plus the requesting jurisdiction's `response_window_days`, expressed as that many exact twenty-four-hour periods."
    PRD 3.8: "Because `open_request_count` is by definition the number of the exam's requests sitting in `OPEN`, `OVERDUE` or `RESPONDED`, opening a request raises it by one."

    Design: Corner/validations/information_request_from_a_non_participating_state_rejects
    """
    ca_id = active_license.jurisdiction_id
    nevada = fx.create_jurisdiction(api, C.NV_CONFIG)

    exam = fx.setup_exam_in_fieldwork(
        api,
        active_license.licensee_id,
        ca_id,
        fieldwork_start="2026-09-01T00:00:00Z",
        fieldwork_end="2026-09-15T00:00:00Z",
        participating_jurisdiction_ids=[ca_id],
    )
    assert exam["status"] == "FIELDWORK"
    assert exam["participating_state_count"] == 1
    assert exam["open_request_count"] == 0

    rejected = api.create_information_request(
        F.information_request_payload(
            exam["id"], nevada["id"], subject="Nevada agent list", requested_item_count=1
        ),
        make_state_regulator_headers(nevada["id"]),
    )
    validate_error(rejected, ERR_JURISDICTION_NOT_PARTICIPATING)

    empty, empty_meta = validate_paginated(
        api.list_information_requests(MANAGER_HEADERS, params={"exam_id": exam["id"]})
    )
    assert empty == []
    assert empty_meta["total_count"] == 0

    after_rejection = validate_success(
        api.get_exam(exam["id"], make_state_regulator_headers(ca_id))
    )
    assert after_rejection["open_request_count"] == 0
    assert after_rejection["participating_state_count"] == 1
    A.assert_version_unchanged(exam, after_rejection)

    # The adjacent accepted case: the lead state, which is also a participant, asks.
    accepted = validate_success(
        api.create_information_request(
            F.information_request_payload(
                exam["id"], ca_id, subject="Transmission ledger extracts", requested_item_count=1
            ),
            make_state_regulator_headers(ca_id),
        ),
        201,
    )
    assert accepted["status"] == "OPEN"
    assert accepted["jurisdiction_id"] == ca_id
    # 2026-08-01T00:00:00Z plus California's response_window_days of 15.
    assert accepted["due_at"][:19] == "2026-08-16T00:00:00"

    after_accepted = validate_success(
        api.get_exam(exam["id"], make_state_regulator_headers(ca_id))
    )
    assert after_accepted["open_request_count"] == 1


def test_exam_naming_a_non_multistate_state_rejects(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """Nevada holds an ACTIVE licence but does not participate in coordinated exams.

    PRD 3.1: "Two further fields shape process rather than arithmetic: `participates_in_multistate`, a boolean defaulting to true that says whether the state may join a coordinated examination, and `call_report_frequency`, which is either `QUARTERLY` or `ANNUAL` and fixes the shape of the reporting calendar for every licence issued there."
    PRD 3.8: "Every listed participant must be eligible — its `participates_in_multistate` must be true and the examined licensee must hold a `StateLicense` there whose `license_status` is `ACTIVE`; a participant failing either test is rejected with `ERR_JURISDICTION_NOT_MULTISTATE` (HTTP 422)."
    PRD 3.8: "On success the exam starts in `SCHEDULED` and `participating_state_count` is set to the distinct count of participating jurisdictions including the lead."

    Design: Corner/validations/exam_naming_a_non_multistate_state_rejects
    """
    ca_id = active_license.jurisdiction_id
    licensee_id = active_license.licensee_id

    nevada_setup = fx.add_license_in_jurisdiction(api, licensee_id, C.NV_CONFIG)
    nv_id = nevada_setup["jurisdiction"]["id"]
    nv_license_before = fx.get_license(api, nevada_setup["license"]["id"])
    ca_license_before = fx.get_license(api, active_license.license_id)
    assert nv_license_before["license_status"] == "ACTIVE"
    assert ca_license_before["license_status"] == "ACTIVE"
    # Nevada: tier-one bond 2,500,000 against a base bond of 1,000,000, cap 20,000,000.
    assert nv_license_before["bond_requirement_cents"] == 2_500_000

    rejected = api.create_exam(
        F.exam_payload(
            licensee_id,
            ca_id,
            "2026-09-01T00:00:00Z",
            "2026-09-15T00:00:00Z",
            participating_jurisdiction_ids=[ca_id, nv_id],
        ),
        make_state_regulator_headers(ca_id),
    )
    validate_error(rejected, ERR_JURISDICTION_NOT_MULTISTATE)

    empty, empty_meta = validate_paginated(
        api.list_exams(MANAGER_HEADERS, params={"licensee_id": licensee_id})
    )
    assert empty == []
    assert empty_meta["total_count"] == 0

    for before in (ca_license_before, nv_license_before):
        after = fx.get_license(api, before["id"])
        A.assert_license_state(after, license_status="ACTIVE")
        assert after["exam_findings_open"] is False
        A.assert_version_unchanged(before, after)

    # The adjacent accepted case: California alone is an eligible participant.
    accepted = validate_success(
        api.create_exam(
            F.exam_payload(
                licensee_id,
                ca_id,
                "2026-09-01T00:00:00Z",
                "2026-09-15T00:00:00Z",
                participating_jurisdiction_ids=[ca_id],
            ),
            make_state_regulator_headers(ca_id),
        ),
        201,
    )
    A.assert_audit_stamps(accepted)
    assert accepted["status"] == "SCHEDULED"
    assert accepted["participating_state_count"] == 1  # the lead, counted once
    assert accepted["open_request_count"] == 0
    assert accepted["findings_count"] == 0


def test_second_decision_from_the_same_state_rejects_as_duplicate_approval(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """One state approves once; its second approval never counts twice.

    PRD 3.2: "`control_determination` is `CONTROL` when `attributed_ownership_bps` is at least 2500 basis points **or** the holder's `role_title` is one of the four officer titles `CEO`, `CFO`, `COO` or `CCO`; otherwise it is `NON_CONTROL`."
    PRD 3.2: "At the same moment the server pins `required_approval_count` to the licensee's `active_license_count` as it stands at creation time — the quorum is frozen then and does not move as licences come and go."
    PRD 3.2: "An `APPROVED` decision from a jurisdiction that is not yet present in `approving_jurisdiction_ids` appends that jurisdiction's `id` to the array and leaves the holder in `PROPOSED` — a self-loop that repeats once per approving state."
    PRD 3.2: "Only when the length of `approving_jurisdiction_ids` reaches `required_approval_count` does `change_of_control_status` flip to `APPROVED`."
    PRD 3.2: "A second decision from a jurisdiction that has already decided on this holder is rejected with `ERR_DUPLICATE_APPROVAL` (HTTP 409)."

    Design: Corner/validations/second_decision_from_the_same_state_rejects_as_duplicate_approval
    """
    ca_id = active_license.jurisdiction_id
    licensee_id = active_license.licensee_id

    texas_setup = fx.add_license_in_jurisdiction(api, licensee_id, C.TX_CONFIG)
    tx_id = texas_setup["jurisdiction"]["id"]
    licensee = fx.get_licensee(api, licensee_id)
    assert licensee["active_license_count"] == 2  # one CA licence plus one TX licence

    holder = fx.create_control_person(
        api,
        licensee_id,
        full_name="Dana Whitfield",
        role_title="ENTITY_HOLDER",
        direct_ownership_bps=5000,
    )
    assert holder["control_determination"] == "CONTROL"  # 5000 bps attributed >= 2500
    assert holder["change_of_control_status"] == "PENDING_APPROVAL"
    assert holder["required_approval_count"] == 2  # pinned to active_license_count
    assert holder["approving_jurisdiction_ids"] == []

    first = fx.decide_change_of_control(api, holder["id"], ca_id, "APPROVED")
    assert first["approving_jurisdiction_ids"] == [ca_id]
    assert first["change_of_control_status"] == "PENDING_APPROVAL"  # 1 of 2 approvals
    assert first["status"] == "PROPOSED"

    rejected = api.decide_change_of_control(
        holder["id"],
        F.change_of_control_payload("APPROVED", rationale="California clears it again."),
        make_state_regulator_headers(ca_id),
    )
    validate_error(rejected, ERR_DUPLICATE_APPROVAL)

    after_rejection = validate_success(
        api.get_control_person(holder["id"], MANAGER_HEADERS)
    )
    assert after_rejection["approving_jurisdiction_ids"] == [ca_id]
    assert after_rejection["change_of_control_status"] == "PENDING_APPROVAL"
    assert after_rejection["status"] == "PROPOSED"
    A.assert_version_unchanged(first, after_rejection)
    assert fx.get_licensee(api, licensee_id)["control_chain_status"] == "PENDING_CHECKS"

    # The adjacent accepted case: a state that has not yet decided completes the quorum.
    second = fx.decide_change_of_control(api, holder["id"], tx_id, "APPROVED")
    assert second["approving_jurisdiction_ids"] == [ca_id, tx_id]
    assert second["change_of_control_status"] == "APPROVED"  # 2 of 2 approvals
    assert second["status"] == "PROPOSED"  # the background check is still PENDING
    assert second["background_check_status"] == "PENDING"
