"""Composite state builders and pytest fixtures.

The harness resets the database before every individual test, so nothing here may
assume state left behind by an earlier test: each fixture drives the public API
from an empty database up to the precondition the test needs.

`LicensureSetup` is the workhorse.  It wraps the client with one method per
setup step, always reading a parent's current `version` immediately before a
write that demands it, so a chain never carries a stale view by accident.
"""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import ApiClient, api_client
from .constants import (
    CATEGORY_MOS_TRAINING,
    CLOCK_STARTUP_UTC,
    DECISION_APPROVE,
    DISCIPLINE_CLEAR,
    EXAM_JURISPRUDENCE,
    EXAM_NATIONAL,
    MILITARY_NONE,
    MILITARY_SPOUSE,
    PATHWAY_ENDORSEMENT,
    PATHWAY_MILITARY_SPOUSE_EXPEDITED,
    PATHWAY_UNIVERSAL_RECOGNITION,
    SCOPE_EQUIVALENT,
)
from .test_users import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    ANALYST_USER_ID,
    DEPUTY_HEADERS,
    make_applicant_headers,
    make_evaluator_headers,
    make_analyst_headers,
)


class LicensureSetup:
    """High-level setup driver for the Licensure Portability API."""

    def __init__(self, client: ApiClient):
        self.api = client

    # ─── Logical clock ────────────────────────────────

    def set_clock(self, to_iso8601: str) -> Dict[str, Any]:
        return get_success_data(self.api.set_clock(to_iso8601, ADMIN_HEADERS))

    # ─── Regulatory frame ─────────────────────────────

    def profession(self, **overrides: Any) -> Dict[str, Any]:
        payload = factories.profession_payload(**overrides)
        return get_success_data(self.api.create_profession(payload, ADMIN_HEADERS))

    def compact(self, profession_id: str, **overrides: Any) -> Dict[str, Any]:
        payload = factories.reciprocal_agreement_payload(**overrides)
        return get_success_data(
            self.api.create_reciprocal_agreement(profession_id, payload, ADMIN_HEADERS)
        )

    def evaluator(self, **overrides: Any) -> Dict[str, Any]:
        payload = factories.evaluator_payload(**overrides)
        return get_success_data(self.api.create_evaluator(payload, ADMIN_HEADERS))

    # ─── Intake ───────────────────────────────────────

    def applicant(self, **overrides: Any) -> Dict[str, Any]:
        payload = factories.applicant_payload(**overrides)
        return get_success_data(self.api.create_applicant(payload, ADMIN_HEADERS))

    def credential(self, applicant_id: str, **overrides: Any) -> Dict[str, Any]:
        payload = factories.credential_payload(**overrides)
        return get_success_data(
            self.api.create_credential(applicant_id, payload, make_applicant_headers(applicant_id))
        )

    def training_record(self, applicant_id: str, **overrides: Any) -> Dict[str, Any]:
        payload = factories.training_record_payload(**overrides)
        return get_success_data(
            self.api.create_training_record(
                applicant_id, payload, make_applicant_headers(applicant_id)
            )
        )

    def disciplinary_record(self, applicant_id: str, **overrides: Any) -> Dict[str, Any]:
        payload = factories.disciplinary_record_payload(applicant_id, **overrides)
        return get_success_data(self.api.create_disciplinary_record(payload, ADMIN_HEADERS))

    def resolve_disciplinary_record(self, record_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.resolve_disciplinary_record(record_id, {}, ADMIN_HEADERS))

    # ─── Applications ─────────────────────────────────

    def application(
        self,
        applicant_id: str,
        profession_id: str,
        credential_id: str,
        **overrides: Any,
    ) -> Dict[str, Any]:
        payload = factories.application_payload(
            applicant_id, profession_id, credential_id, **overrides
        )
        return get_success_data(
            self.api.create_application(payload, make_applicant_headers(applicant_id))
        )

    def submit(self, application_id: str, applicant_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.submit_application(application_id, {}, make_applicant_headers(applicant_id))
        )

    def pay(self, application_id: str, applicant_id: str, amount_cents: int) -> Dict[str, Any]:
        return get_success_data(
            self.api.create_payment(
                application_id,
                factories.payment_payload(amount_cents),
                make_applicant_headers(applicant_id),
            )
        )

    def pay_off(self, application_id: str, applicant_id: str) -> int:
        """Settle the whole outstanding balance; returns the amount tendered."""
        balance = self.read_application(application_id)["fee_balance_cents"]
        if balance > 0:
            self.pay(application_id, applicant_id, balance)
        return max(balance, 0)

    def record_exam_result(
        self, application_id: str, passed: bool = True, exam_kind: str = EXAM_NATIONAL, **overrides: Any
    ) -> Dict[str, Any]:
        payload = factories.exam_result_payload(passed=passed, exam_kind=exam_kind, **overrides)
        return get_success_data(
            self.api.record_exam_result(application_id, payload, ADMIN_HEADERS)
        )

    def record_deficiency(self, application_id: str, **overrides: Any) -> Dict[str, Any]:
        payload = factories.deficiency_payload(**overrides)
        return get_success_data(
            self.api.record_deficiency(application_id, payload, ANALYST_HEADERS)
        )

    def cure(self, application_id: str, applicant_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.api.cure_application(application_id, {}, make_applicant_headers(applicant_id))
        )

    def decide(
        self, application_id: str, decision: str = DECISION_APPROVE, headers: Optional[Dict] = None
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.issue_decision(
                application_id, factories.decision_payload(decision), headers or DEPUTY_HEADERS
            )
        )

    # ─── Evaluations ──────────────────────────────────

    def evaluation(self, application_id: str, credential_id: str) -> Dict[str, Any]:
        payload = factories.evaluation_payload(application_id, credential_id)
        return get_success_data(self.api.create_evaluation(payload, ANALYST_HEADERS))

    def scope_review(
        self, evaluation_id: str, decision: str = SCOPE_EQUIVALENT, user_id: str = ANALYST_USER_ID
    ) -> Dict[str, Any]:
        return get_success_data(
            self.api.record_scope_review(
                evaluation_id, factories.scope_review_payload(decision), make_analyst_headers(user_id)
            )
        )

    def discipline_finding(
        self,
        evaluation_id: str,
        evaluator_id: str,
        finding: str = DISCIPLINE_CLEAR,
        databases_checked: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        payload = factories.discipline_finding_payload(finding, databases_checked)
        return get_success_data(
            self.api.record_discipline_finding(
                evaluation_id, payload, make_evaluator_headers(evaluator_id)
            )
        )

    def finalize(self, evaluation_id: str, user_id: str = ANALYST_USER_ID) -> Dict[str, Any]:
        return get_success_data(
            self.api.finalize_evaluation(evaluation_id, {}, make_analyst_headers(user_id))
        )

    # ─── Credit awards ────────────────────────────────

    def credit_award(self, application_id: str, training_record_id: str) -> Dict[str, Any]:
        payload = factories.credit_award_payload(application_id, training_record_id)
        return get_success_data(self.api.create_credit_award(payload, ANALYST_HEADERS))

    def revoke_credit_award(self, award_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.revoke_credit_award(award_id, {}, ANALYST_HEADERS))

    # ─── Permits ──────────────────────────────────────

    def permit(self, application_id: str, effective_at: str, expected_version: Optional[int] = None):
        """Issue a permit, reading the application's current `version` when not supplied."""
        version = (
            expected_version
            if expected_version is not None
            else self.application_version(application_id)
        )
        payload = factories.temporary_permit_payload(application_id, effective_at, version)
        return get_success_data(self.api.create_temporary_permit(payload, ANALYST_HEADERS))

    def revoke_permit(self, permit_id: str, reason_code: str = "APPLICANT_WITHDREW") -> Dict[str, Any]:
        return get_success_data(
            self.api.revoke_temporary_permit(
                permit_id, factories.permit_revocation_payload(reason_code), DEPUTY_HEADERS
            )
        )

    def run_permit_expiry(self) -> Dict[str, Any]:
        return get_success_data(self.api.run_permit_expiry({}, ADMIN_HEADERS))

    # ─── Review assignments ───────────────────────────

    def review_assignment(
        self,
        evaluator_id: str,
        application_id: str,
        window_start_at: str,
        window_end_at: str,
        expected_version: Optional[int] = None,
    ) -> Dict[str, Any]:
        version = (
            expected_version
            if expected_version is not None
            else self.evaluator_version(evaluator_id)
        )
        payload = factories.review_assignment_payload(
            evaluator_id, application_id, window_start_at, window_end_at, version
        )
        return get_success_data(self.api.create_review_assignment(payload, ANALYST_HEADERS))

    # ─── Reads ────────────────────────────────────────

    def read_application(self, application_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_application(application_id, ANALYST_HEADERS))

    def application_version(self, application_id: str) -> int:
        return self.read_application(application_id)["version"]

    def read_applicant(self, applicant_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_applicant(applicant_id, ANALYST_HEADERS))

    def read_evaluator(self, evaluator_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_evaluator(evaluator_id, ANALYST_HEADERS))

    def evaluator_version(self, evaluator_id: str) -> int:
        return self.read_evaluator(evaluator_id)["version"]

    def read_evaluation(self, evaluation_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_evaluation(evaluation_id, ANALYST_HEADERS))

    def read_assignment(self, assignment_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_review_assignment(assignment_id, ANALYST_HEADERS))

    def read_credit_award(self, award_id: str) -> Dict[str, Any]:
        return get_success_data(self.api.get_credit_award(award_id, ANALYST_HEADERS))

    def read_ledger(self, application_id: str, **params: Any) -> List[Dict[str, Any]]:
        response = self.api.list_fee_ledger_entries(
            application_id, ANALYST_HEADERS, params or {"limit": 100}
        )
        return get_success_data(response)

    def ledger_meta(self, application_id: str, **params: Any) -> Dict[str, Any]:
        response = self.api.list_fee_ledger_entries(
            application_id, ANALYST_HEADERS, params or {"limit": 100}
        )
        get_success_data(response)
        return response.json()["meta"]

    def read_permits(self, application_id: str, **params: Any) -> List[Dict[str, Any]]:
        return get_success_data(
            self.api.list_application_permits(application_id, ANALYST_HEADERS, params or None)
        )

    def read_licenses(self, **params: Any) -> List[Dict[str, Any]]:
        return get_success_data(self.api.list_licenses(ANALYST_HEADERS, params or None))

    def read_assignments(self, **params: Any) -> List[Dict[str, Any]]:
        return get_success_data(self.api.list_review_assignments(ANALYST_HEADERS, params or None))

    # ─── Composite chains ─────────────────────────────

    def frame_with_applicant(
        self,
        profession_overrides: Optional[Dict[str, Any]] = None,
        applicant_overrides: Optional[Dict[str, Any]] = None,
        credential_overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Profession + applicant + one out-of-state credential."""
        profession = self.profession(**(profession_overrides or {}))
        applicant = self.applicant(**(applicant_overrides or {}))
        credential = self.credential(applicant["id"], **(credential_overrides or {}))
        return {
            "profession": profession,
            "prof_id": profession["id"],
            "applicant": applicant,
            "ap_id": applicant["id"],
            "credential": credential,
            "cred_id": credential["id"],
        }

    def draft_application(
        self,
        pathway: str = PATHWAY_ENDORSEMENT,
        expedited: bool = False,
        profession_overrides: Optional[Dict[str, Any]] = None,
        applicant_overrides: Optional[Dict[str, Any]] = None,
        credential_overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Regulatory frame, intake and one DRAFT application on the given pathway."""
        env = self.frame_with_applicant(
            profession_overrides, applicant_overrides, credential_overrides
        )
        application = self.application(
            env["ap_id"], env["prof_id"], env["cred_id"], pathway=pathway, expedited=expedited
        )
        env["application"] = application
        env["app_id"] = application["id"]
        return env

    def submitted_application(self, **kwargs: Any) -> Dict[str, Any]:
        """A DRAFT application carried across the submission gate."""
        env = self.draft_application(**kwargs)
        env["submitted"] = self.submit(env["app_id"], env["ap_id"])
        return env

    def settled_application(self, **kwargs: Any) -> Dict[str, Any]:
        """A submitted application whose balance has been paid down to zero."""
        env = self.submitted_application(**kwargs)
        env["paid_cents"] = self.pay_off(env["app_id"], env["ap_id"])
        return env

    def under_review_application(self, settle: bool = True, **kwargs: Any) -> Dict[str, Any]:
        """A submitted application driven to UNDER_REVIEW by opening its evaluation."""
        env = self.settled_application(**kwargs) if settle else self.submitted_application(**kwargs)
        evaluation = self.evaluation(env["app_id"], env["cred_id"])
        env["evaluation"] = evaluation
        env["eval_id"] = evaluation["id"]
        return env

    def assigned_review(
        self,
        window_start_at: str = "2026-08-10T00:00:00Z",
        window_end_at: str = "2026-08-20T00:00:00Z",
        evaluator_overrides: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """An application under review with an evaluator booked onto its calendar."""
        env = self.under_review_application(**kwargs)
        overrides = dict(evaluator_overrides or {})
        overrides.setdefault("profession_code", env["profession"]["profession_code"])
        evaluator = self.evaluator(**overrides)
        assignment = self.review_assignment(
            evaluator["id"], env["app_id"], window_start_at, window_end_at
        )
        env["evaluator"] = evaluator
        env["evr_id"] = evaluator["id"]
        env["assignment"] = assignment
        env["assignment_id"] = assignment["id"]
        return env

    def completed_evaluation(
        self,
        scope_decision: str = SCOPE_EQUIVALENT,
        discipline_finding: str = DISCIPLINE_CLEAR,
        scope_user_id: str = ANALYST_USER_ID,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Both parallel dimensions resolved and the evaluation finalised to COMPLETE."""
        env = self.assigned_review(**kwargs)
        self.scope_review(env["eval_id"], scope_decision, scope_user_id)
        self.discipline_finding(env["eval_id"], env["evr_id"], discipline_finding)
        env["finalized"] = self.finalize(env["eval_id"], scope_user_id)
        return env


# ─── Tier 1: client and setup driver ──────────────────

@pytest.fixture
def api() -> ApiClient:
    """The shared HTTP client pointed at the API under test."""
    return api_client


@pytest.fixture
def setup(api: ApiClient) -> LicensureSetup:
    """Setup driver for building preconditions through the public API."""
    return LicensureSetup(api)


# ─── Tier 2: simple entities ──────────────────────────

@pytest.fixture
def rn_profession(setup: LicensureSetup) -> Dict[str, Any]:
    """The Registered Nurse profession with its published fee schedule."""
    return setup.profession()


@pytest.fixture
def civilian_applicant(setup: LicensureSetup) -> Dict[str, Any]:
    """A non-military Texas applicant with 24 months of residency."""
    return setup.applicant()


@pytest.fixture
def military_spouse_applicant(setup: LicensureSetup) -> Dict[str, Any]:
    """A military-spouse applicant, eligible for the expedited pathway."""
    return setup.applicant(full_name="Rhea Calloway", military_status=MILITARY_SPOUSE)


@pytest.fixture
def rn_evaluator(setup: LicensureSetup) -> Dict[str, Any]:
    """An ACTIVE contract evaluator credentialed to review RN files."""
    return setup.evaluator()


# ─── Tier 3: composite application states ─────────────

@pytest.fixture
def endorsement_draft(setup: LicensureSetup) -> Dict[str, Any]:
    """RN frame, civilian applicant, verified credential, DRAFT ENDORSEMENT application."""
    return setup.draft_application()


@pytest.fixture
def endorsement_submitted(setup: LicensureSetup) -> Dict[str, Any]:
    """The same file carried across the submission gate."""
    return setup.submitted_application()


@pytest.fixture
def endorsement_settled(setup: LicensureSetup) -> Dict[str, Any]:
    """A submitted ENDORSEMENT application with a zero fee balance."""
    return setup.settled_application()


@pytest.fixture
def endorsement_under_review(setup: LicensureSetup) -> Dict[str, Any]:
    """A settled ENDORSEMENT application whose evaluation is open (UNDER_REVIEW)."""
    return setup.under_review_application()


@pytest.fixture
def endorsement_with_assignment(setup: LicensureSetup) -> Dict[str, Any]:
    """An ENDORSEMENT file under review with an evaluator booked onto it."""
    return setup.assigned_review()


FULL_RN_SCOPE = ["ASSESS", "TREAT", "PRESCRIBE", "SUPERVISE"]


@pytest.fixture
def endorsement_evaluation_complete(setup: LicensureSetup) -> Dict[str, Any]:
    """An ENDORSEMENT file whose evaluation has been finalised to COMPLETE.

    The credential grants the whole required scope, so the analyst's EQUIVALENT
    opinion is admissible.
    """
    return setup.completed_evaluation(credential_overrides={"scope_elements": FULL_RN_SCOPE})


@pytest.fixture
def universal_recognition_under_review(setup: LicensureSetup) -> Dict[str, Any]:
    """A UNIVERSAL_RECOGNITION file settled and under review."""
    return setup.under_review_application(pathway=PATHWAY_UNIVERSAL_RECOGNITION)


@pytest.fixture
def military_spouse_submitted(setup: LicensureSetup) -> Dict[str, Any]:
    """A MILITARY_SPOUSE_EXPEDITED file submitted by a military-spouse applicant."""
    return setup.submitted_application(
        pathway=PATHWAY_MILITARY_SPOUSE_EXPEDITED,
        applicant_overrides={"full_name": "Rhea Calloway", "military_status": MILITARY_SPOUSE},
    )


# ─── Tier 4: factory fixtures ─────────────────────────

@pytest.fixture
def make_application(setup: LicensureSetup):
    """Callable building an arbitrary application chain from scratch."""

    def _make(**kwargs: Any) -> Dict[str, Any]:
        return setup.draft_application(**kwargs)

    return _make


@pytest.fixture
def make_verified_training_record(setup: LicensureSetup):
    """Callable filing a verified training record against an applicant."""

    def _make(applicant_id: str, documented_hours: int, category: str = CATEGORY_MOS_TRAINING, **kw: Any):
        return setup.training_record(
            applicant_id, category=category, documented_hours=documented_hours, **kw
        )

    return _make


# ─── Tier 5: multi-entity scenarios ───────────────────

@pytest.fixture
def approvable_application(setup: LicensureSetup) -> Dict[str, Any]:
    """A file that clears every APPROVE gate: complete evaluation, hours satisfied,
    both examinations recorded as passed and a settled balance."""
    env = setup.completed_evaluation(
        profession_overrides={"requirement_hours_total": 240.0},
        applicant_overrides={"military_status": MILITARY_NONE},
        credential_overrides={"scope_elements": FULL_RN_SCOPE},
    )
    total = env["profession"]["requirement_hours_total"]
    # 0.75 per documented hour of MOS_TRAINING; 320 documented hours clear 240.0.
    record = setup.training_record(
        env["ap_id"], category=CATEGORY_MOS_TRAINING, documented_hours=int(total / 0.75) + 1
    )
    env["training_record"] = record
    env["award"] = setup.credit_award(env["app_id"], record["id"])
    setup.record_exam_result(env["app_id"], passed=True, exam_kind=EXAM_NATIONAL)
    setup.record_exam_result(env["app_id"], passed=True, exam_kind=EXAM_JURISPRUDENCE)
    setup.pay_off(env["app_id"], env["ap_id"])
    return env


@pytest.fixture
def clock_at_startup(setup: LicensureSetup) -> str:
    """The logical clock's documented startup instant, asserted to be readable."""
    return CLOCK_STARTUP_UTC
