"""Precondition builders.

Every test starts against an empty database, so each scenario is assembled from
scratch through the published endpoints. :class:`Builder` drives one workflow
step per method, asserts the step succeeded and hands back the stored row; the
module-level scenario functions chain those steps into the audit waves the
specification's deadlines are written against, so a test body contains only the
step under test plus its assertions.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from . import factories as f
from .api_client import ApiClient
from .constants import CLOCK_ORIGIN
from .test_users import (
    ANALYST,
    PROGRAM_ADMIN,
    RECOVERY_AGENT,
    REVIEWER,
    employee_headers,
)
from .types import Ctx, Headers, Json

# ------------------------------------------------------------- the scenario calendar
# The logical clock a freshly started process reports.
ORIGIN_INSTANT = CLOCK_ORIGIN
# The announcement instant every wave below is published on.
ANNOUNCE_INSTANT = "2026-09-01T00:00:00Z"
# announcement + amnesty_days 21.
AMNESTY_END_INSTANT = "2026-09-22T00:00:00Z"
# One day past the amnesty end: a sweep here runs step one only.
RESPONSE_WINDOW_INSTANT = "2026-09-23T00:00:00Z"
# A working instant inside the response window, after the amnesty has closed.
REVIEW_INSTANT = "2026-09-24T00:00:00Z"
# announcement + response_days 45.
RESPONSE_DEADLINE_INSTANT = "2026-10-16T00:00:00Z"
# One day past the response deadline: a sweep here escalates.
ESCALATION_INSTANT = "2026-10-17T00:00:00Z"
# Past the 2026-10-31 effective date: a sweep here finalises the notices.
FINALIZE_INSTANT = "2026-11-01T00:00:00Z"
# A working instant inside the 30-day appeal window on a 2026-10-17 notice.
APPEAL_INSTANT = "2026-11-05T00:00:00Z"
# The last instant of that appeal window.
APPEAL_WINDOW_END_INSTANT = "2026-11-16T00:00:00Z"
# One day past it: a sweep here closes the case and reconciles the program.
RECONCILE_INSTANT = "2026-11-17T00:00:00Z"
# The termination effective date and the coverage end date it writes.
EFFECTIVE_DATE = "2026-10-31"
# The continuation election deadline on a 2026-10-17 notice.
ELECTION_DEADLINE_INSTANT = "2026-12-16T00:00:00Z"

DEFAULT_ONSET_DATE = "2026-09-01"


class Builder:
    """Drives the published endpoints to assemble scenario preconditions."""

    def __init__(self, client: ApiClient) -> None:
        self.client = client
        self._employee_index = 0
        self._dependent_index = 0
        self._claim_index = 0

    # ------------------------------------------------------------------- plumbing
    @staticmethod
    def _created(response) -> Json:
        return validate_success(response, expected_status=201)

    @staticmethod
    def _ok(response) -> Json:
        return validate_success(response, expected_status=200)

    @staticmethod
    def _setup(response) -> Json:
        return get_success_data(response)

    # ---------------------------------------------------------------------- clock
    def set_clock(self, instant: str = ORIGIN_INSTANT, headers: Headers = PROGRAM_ADMIN) -> Json:
        """Pin the deterministic logical clock every window check reads."""
        return self._ok(self.client.set_clock(f.clock_payload(instant), headers))

    # ------------------------------------------------------------------ employees
    def employee(self, headers: Headers = PROGRAM_ADMIN, **overrides: Any) -> Json:
        payload = f.employee_payload(index=self._employee_index, **overrides)
        self._employee_index += 1
        return self._created(self.client.create_employee(payload, headers))

    def employees(self, count: int, **overrides: Any) -> List[Json]:
        return [self.employee(**overrides) for _ in range(count)]

    def read_employee(self, employee_id: str, headers: Headers = PROGRAM_ADMIN) -> Json:
        return self._ok(self.client.get_employee(employee_id, headers))

    # ----------------------------------------------------------------- dependents
    def dependent(
        self,
        employee_id: str,
        relationship_type: str = "SPOUSE",
        headers: Headers = PROGRAM_ADMIN,
        **overrides: Any,
    ) -> Json:
        payload = f.dependent_payload(
            relationship_type, index=self._dependent_index, **overrides
        )
        self._dependent_index += 1
        return self._created(
            self.client.create_dependent(employee_id, payload, headers)
        )

    def read_dependent(self, dependent_id: str, headers: Headers = PROGRAM_ADMIN) -> Json:
        return self._ok(self.client.get_dependent(dependent_id, headers))

    def dependents_of(self, employee_id: str, headers: Headers = PROGRAM_ADMIN) -> List[Json]:
        data, _meta = validate_paginated(
            self.client.list_employee_dependents(employee_id, headers)
        )
        return data

    def paid_claim(
        self,
        dependent_id: str,
        service_date: str = "2026-09-20",
        paid_cents: int = 150000,
        headers: Headers = PROGRAM_ADMIN,
        **overrides: Any,
    ) -> Json:
        self._claim_index += 1
        payload = f.paid_claim_payload(
            service_date, paid_cents, index=self._claim_index, **overrides
        )
        return self._created(
            self.client.create_paid_claim(dependent_id, payload, headers)
        )

    # -------------------------------------------------------------- audit programs
    def program(self, headers: Headers = PROGRAM_ADMIN, **overrides: Any) -> Json:
        return self._created(
            self.client.create_program(f.program_payload(**overrides), headers)
        )

    def read_program(self, program_id: str, headers: Headers = PROGRAM_ADMIN) -> Json:
        return self._ok(self.client.get_program(program_id, headers))

    def doc_rule(
        self,
        program_id: str,
        relationship_type: str = "SPOUSE",
        phase: str = "AUDIT",
        headers: Headers = PROGRAM_ADMIN,
        **overrides: Any,
    ) -> Json:
        payload = f.documentation_rule_payload(relationship_type, phase, **overrides)
        return self._created(
            self.client.create_documentation_rule(program_id, payload, headers)
        )

    def doc_rules(
        self,
        program_id: str,
        relationship_types: Iterable[str],
        phase: str = "AUDIT",
        overrides_by_relationship: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[Json]:
        """One rule per distinct relationship class, in the order given."""
        seen: List[str] = []
        rules: List[Json] = []
        for relationship_type in relationship_types:
            if relationship_type in seen:
                continue
            seen.append(relationship_type)
            extra = (overrides_by_relationship or {}).get(relationship_type, {})
            rules.append(self.doc_rule(program_id, relationship_type, phase, **extra))
        return rules

    def scope(
        self,
        program_id: str,
        scope_type: str = "FULL_CENSUS",
        headers: Headers = PROGRAM_ADMIN,
        expected_program_version: Optional[int] = None,
        **overrides: Any,
    ) -> Json:
        """Decide scope, reading the program's current version unless one is given."""
        if expected_program_version is None:
            expected_program_version = self.read_program(program_id)["version"]
        payload = f.scope_payload(expected_program_version, scope_type, **overrides)
        return self._ok(self.client.run_scope(program_id, payload, headers))

    def communicate(
        self, program_id: str, headers: Headers = PROGRAM_ADMIN, **overrides: Any
    ) -> Json:
        return self._ok(
            self.client.communicate(program_id, f.communicate_payload(**overrides), headers)
        )

    def sweep(self, program_id: str, headers: Headers = PROGRAM_ADMIN) -> Json:
        """Run the deferred-action checkpoint against the current clock."""
        return self._ok(self.client.run_sweep(program_id, {}, headers))

    def measure_savings(
        self, program_id: str, variant: str = "PROVISIONAL", headers: Headers = PROGRAM_ADMIN
    ) -> Json:
        return self._ok(
            self.client.measure_savings(program_id, f.savings_payload(variant), headers)
        )

    def close_program(self, program_id: str, headers: Headers = PROGRAM_ADMIN) -> Json:
        return self._ok(self.client.close_program(program_id, {}, headers))

    # ----------------------------------------------------------------- audit cases
    def cases(self, program_id: str, headers: Headers = PROGRAM_ADMIN) -> List[Json]:
        data, _meta = validate_paginated(
            self.client.list_cases(headers, params={"program_id": program_id})
        )
        return data

    def case(self, program_id: str, index: int = 0, headers: Headers = PROGRAM_ADMIN) -> Json:
        return self.cases(program_id, headers)[index]

    def read_case(self, case_id: str, headers: Headers = PROGRAM_ADMIN) -> Json:
        return self._ok(self.client.get_case(case_id, headers))

    def reminder(
        self, case_id: str, headers: Headers = ANALYST, **overrides: Any
    ) -> Json:
        return self._ok(
            self.client.send_reminder(case_id, f.reminder_payload(**overrides), headers)
        )

    def communications(
        self, case_id: str, headers: Headers = PROGRAM_ADMIN, **params: Any
    ) -> Tuple[List[Json], Json]:
        return validate_paginated(
            self.client.list_case_communications(case_id, headers, params=params or None)
        )

    # ------------------------------------------------------------ proof submissions
    def submit_proof(
        self,
        case_id: str,
        dependent_id: str,
        employee_id: Optional[str] = None,
        proof_type: str = "MARRIAGE_CERTIFICATE",
        headers: Optional[Headers] = None,
        **overrides: Any,
    ) -> Json:
        """Lodge one proof document, by default as the owning employee."""
        acting = headers or employee_headers(employee_id or "")
        payload = f.proof_submission_payload(
            case_id, dependent_id, proof_type, **overrides
        )
        return self._created(self.client.create_proof_submission(payload, acting))

    def read_submission(self, submission_id: str, headers: Headers = ANALYST) -> Json:
        return self._ok(self.client.get_proof_submission(submission_id, headers))

    def submissions(self, headers: Headers = ANALYST, **params: Any) -> Tuple[List[Json], Json]:
        return validate_paginated(
            self.client.list_proof_submissions(headers, params=params or None)
        )

    def decide_proof(
        self,
        submission_id: str,
        decision: str = "ACCEPT",
        reason_code: Optional[str] = None,
        headers: Headers = ANALYST,
        **overrides: Any,
    ) -> Json:
        payload = f.decision_payload(decision, reason_code, **overrides)
        return self._ok(
            self.client.decide_proof_submission(submission_id, payload, headers)
        )

    def accept_proof(
        self, submission_id: str, headers: Headers = ANALYST, **overrides: Any
    ) -> Json:
        return self.decide_proof(
            submission_id, "ACCEPT", "VERIFIED_MATCH", headers, **overrides
        )

    def reject_proof(
        self, submission_id: str, headers: Headers = ANALYST, **overrides: Any
    ) -> Json:
        return self.decide_proof(
            submission_id, "REJECT", "INSUFFICIENT_PROOF", headers, **overrides
        )

    def request_redaction(
        self, submission_id: str, headers: Headers = ANALYST, **overrides: Any
    ) -> Json:
        return self.decide_proof(
            submission_id, "REQUEST_REDACTION", None, headers, **overrides
        )

    def upload_redaction(
        self,
        submission_id: str,
        employee_id: Optional[str] = None,
        headers: Optional[Headers] = None,
        **overrides: Any,
    ) -> Json:
        acting = headers or (
            employee_headers(employee_id) if employee_id else ANALYST
        )
        return self._ok(
            self.client.upload_redaction(
                submission_id, f.redaction_payload(**overrides), acting
            )
        )

    # ------------------------------------------------------------- amnesty removals
    def amnesty_removal(
        self,
        dependent_id: str,
        case_id: str,
        employee_id: Optional[str] = None,
        headers: Optional[Headers] = None,
        **overrides: Any,
    ) -> Json:
        acting = headers or (
            employee_headers(employee_id) if employee_id else PROGRAM_ADMIN
        )
        payload = f.amnesty_removal_payload(dependent_id, case_id, **overrides)
        return self._created(self.client.create_amnesty_removal(payload, acting))

    def dependent_removals(
        self, dependent_id: str, headers: Headers = PROGRAM_ADMIN, **params: Any
    ) -> Tuple[List[Json], Json]:
        return validate_paginated(
            self.client.list_dependent_amnesty_removals(
                dependent_id, headers, params=params or None
            )
        )

    def case_removals(
        self, case_id: str, headers: Headers = PROGRAM_ADMIN, **params: Any
    ) -> Tuple[List[Json], Json]:
        return validate_paginated(
            self.client.list_case_amnesty_removals(case_id, headers, params=params or None)
        )

    # --------------------------------------------------------------------- appeals
    def appeal(
        self,
        case_id: str,
        dependent_id: str,
        employee_id: str,
        grounds: str = "ADMINISTRATIVE_ERROR",
        headers: Optional[Headers] = None,
        **overrides: Any,
    ) -> Json:
        acting = headers or employee_headers(employee_id)
        payload = f.appeal_payload(case_id, dependent_id, grounds, **overrides)
        return self._created(self.client.create_appeal(payload, acting))

    def read_appeal(self, appeal_id: str, headers: Headers = REVIEWER) -> Json:
        return self._ok(self.client.get_appeal(appeal_id, headers))

    def appeals(self, headers: Headers = REVIEWER, **params: Any) -> Tuple[List[Json], Json]:
        return validate_paginated(self.client.list_appeals(headers, params=params or None))

    def assign_appeal(self, appeal_id: str, headers: Headers = REVIEWER) -> Json:
        return self._ok(self.client.assign_appeal(appeal_id, {}, headers))

    def decide_appeal(
        self,
        appeal_id: str,
        decision: str = "GRANT",
        headers: Headers = REVIEWER,
        **overrides: Any,
    ) -> Json:
        payload = f.appeal_decision_payload(decision, **overrides)
        return self._ok(self.client.decide_appeal(appeal_id, payload, headers))

    def resubmit_appeal(
        self,
        appeal_id: str,
        employee_id: str,
        headers: Optional[Headers] = None,
        **overrides: Any,
    ) -> Json:
        acting = headers or employee_headers(employee_id)
        return self._ok(
            self.client.resubmit_appeal(
                appeal_id, f.appeal_resubmit_payload(**overrides), acting
            )
        )

    # ---------------------------------------------------------- termination notices
    def notices(self, headers: Headers = RECOVERY_AGENT, **params: Any) -> List[Json]:
        data, _meta = validate_paginated(
            self.client.list_notices(headers, params=params or None)
        )
        return data

    def notice_for(self, dependent_id: str, headers: Headers = RECOVERY_AGENT) -> Json:
        rows = self.notices(headers, dependent_id=dependent_id)
        assert rows, f"no termination notice exists for dependent {dependent_id}"
        return rows[0]

    def read_notice(self, notice_id: str, headers: Headers = RECOVERY_AGENT) -> Json:
        return self._ok(self.client.get_notice(notice_id, headers))

    def continuation_election(
        self,
        notice_id: str,
        election: str = "ELECT",
        employee_id: Optional[str] = None,
        headers: Optional[Headers] = None,
    ) -> Json:
        acting = headers or (
            employee_headers(employee_id) if employee_id else PROGRAM_ADMIN
        )
        return self._ok(
            self.client.continuation_election(
                notice_id, f.continuation_election_payload(election), acting
            )
        )

    # ---------------------------------------------------------- claims recoveries
    def open_recovery(
        self,
        dependent_id: str,
        termination_notice_id: str,
        recovery_variant: str = "STRICT",
        ineligibility_onset_date: str = DEFAULT_ONSET_DATE,
        expected_dependent_version: Optional[int] = None,
        headers: Headers = RECOVERY_AGENT,
        **overrides: Any,
    ) -> Json:
        """Open a recovery, reading the dependent's current version unless given."""
        if expected_dependent_version is None:
            expected_dependent_version = self.read_dependent(
                dependent_id, headers
            )["version"]
        payload = f.claim_recovery_payload(
            dependent_id,
            termination_notice_id,
            expected_dependent_version,
            recovery_variant,
            ineligibility_onset_date,
            **overrides,
        )
        return self._created(self.client.create_claim_recovery(payload, headers))

    def issue_demand(
        self,
        recovery_id: str,
        waiver_credit_cents: int = 0,
        headers: Headers = RECOVERY_AGENT,
    ) -> Json:
        return self._ok(
            self.client.issue_demand(
                recovery_id, f.issue_demand_payload(waiver_credit_cents), headers
            )
        )

    def payment(
        self,
        recovery_id: str,
        amount_cents: int,
        received_date: str = "2026-11-02",
        headers: Headers = RECOVERY_AGENT,
    ) -> Json:
        return self._ok(
            self.client.record_payment(
                recovery_id, f.payment_payload(amount_cents, received_date), headers
            )
        )

    def read_recovery(self, recovery_id: str, headers: Headers = RECOVERY_AGENT) -> Json:
        return self._ok(self.client.get_claim_recovery(recovery_id, headers))

    def recoveries(
        self, headers: Headers = RECOVERY_AGENT, **params: Any
    ) -> Tuple[List[Json], Json]:
        return validate_paginated(
            self.client.list_claim_recoveries(headers, params=params or None)
        )


# ---------------------------------------------------------------------------------
# Scenario waves
# ---------------------------------------------------------------------------------
STAGES = (
    "DRAFT",
    "SCOPED",
    "ANNOUNCED",
    "RESPONSE_WINDOW",
    "ESCALATION",
    "FINALIZED",
)


def _stage_at_least(stage: str, target: str) -> bool:
    return STAGES.index(stage) >= STAGES.index(target)


def audit_wave(
    b: Builder,
    *,
    stage: str = "ANNOUNCED",
    relationships: Sequence[str] = ("SPOUSE",),
    employee_overrides: Optional[Dict[str, Any]] = None,
    dependent_overrides: Optional[Sequence[Dict[str, Any]]] = None,
    program_overrides: Optional[Dict[str, Any]] = None,
    rule_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
    extra_rules: Optional[Sequence[Dict[str, Any]]] = None,
    claims: Optional[Sequence[Dict[str, Any]]] = None,
    scope_type: str = "FULL_CENSUS",
    scope_overrides: Optional[Dict[str, Any]] = None,
    announce_at: str = ANNOUNCE_INSTANT,
    origin_at: str = ORIGIN_INSTANT,
) -> Ctx:
    """Assemble one audit wave and stop at ``stage``.

    ``DRAFT`` stops with the census, the program and its documentation rules in
    place; ``SCOPED`` runs the scope decision; ``ANNOUNCED`` publishes the
    announcement at ``announce_at``; ``RESPONSE_WINDOW`` sweeps once past the
    amnesty end; ``ESCALATION`` sweeps once past the response deadline; and
    ``FINALIZED`` sweeps again past the notices' effective date.
    """
    assert stage in STAGES, stage
    b.set_clock(origin_at)

    employee = b.employee(**(employee_overrides or {}))
    dependents: List[Json] = []
    for index, relationship_type in enumerate(relationships):
        extra: Dict[str, Any] = {}
        if dependent_overrides and index < len(dependent_overrides):
            extra = dict(dependent_overrides[index])
        dependents.append(b.dependent(employee["id"], relationship_type, **extra))

    for claim in claims or ():
        spec = dict(claim)
        target = dependents[spec.pop("dependent_index", 0)]
        b.paid_claim(target["id"], **spec)

    program = b.program(**(program_overrides or {}))
    rules = b.doc_rules(
        program["id"], relationships, "AUDIT", rule_overrides or {}
    )
    for spec in extra_rules or ():
        extra_rule = dict(spec)
        rules.append(
            b.doc_rule(
                program["id"],
                extra_rule.pop("relationship_type"),
                extra_rule.pop("phase", "AUDIT"),
                **extra_rule,
            )
        )

    ctx = Ctx(
        employee=employee,
        dependents=dependents,
        dep=dependents[0] if dependents else None,
        program=program,
        rules=rules,
        case=None,
        cases=[],
        notices={},
    )
    for position, dependent in enumerate(dependents, start=1):
        ctx[f"dep{position}"] = dependent

    if stage == "DRAFT":
        return ctx

    b.scope(program["id"], scope_type, **(scope_overrides or {}))
    ctx.program = b.read_program(program["id"])
    ctx.cases = b.cases(program["id"])
    ctx.case = ctx.cases[0] if ctx.cases else None
    if stage == "SCOPED":
        return ctx

    b.set_clock(announce_at)
    b.communicate(program["id"])
    ctx.program = b.read_program(program["id"])
    ctx.cases = b.cases(program["id"])
    ctx.case = ctx.cases[0] if ctx.cases else None
    if stage == "ANNOUNCED":
        return ctx

    b.set_clock(RESPONSE_WINDOW_INSTANT)
    b.sweep(program["id"])
    if stage == "RESPONSE_WINDOW":
        ctx.program = b.read_program(program["id"])
        ctx.cases = b.cases(program["id"])
        ctx.case = ctx.cases[0] if ctx.cases else None
        return ctx

    b.set_clock(ESCALATION_INSTANT)
    b.sweep(program["id"])
    if stage == "FINALIZED":
        b.set_clock(FINALIZE_INSTANT)
        b.sweep(program["id"])

    ctx.program = b.read_program(program["id"])
    ctx.cases = b.cases(program["id"])
    ctx.case = ctx.cases[0] if ctx.cases else None
    ctx.notices = {row["dependent_id"]: row for row in b.notices()}
    if dependents and dependents[0]["id"] in ctx.notices:
        ctx.notice = ctx.notices[dependents[0]["id"]]
    return ctx


def announced_wave(b: Builder, **kwargs: Any) -> Ctx:
    """A published announcement: program in AMNESTY_OPEN, case NOTIFIED."""
    return audit_wave(b, stage="ANNOUNCED", **kwargs)


def response_window_wave(b: Builder, **kwargs: Any) -> Ctx:
    """The amnesty has closed: program in RESPONSE_WINDOW, decisions permitted."""
    return audit_wave(b, stage="RESPONSE_WINDOW", **kwargs)


def escalated_wave(b: Builder, **kwargs: Any) -> Ctx:
    """The response deadline has passed: notices ISSUED, case ESCALATED."""
    return audit_wave(b, stage="ESCALATION", **kwargs)


def finalized_wave(b: Builder, **kwargs: Any) -> Ctx:
    """The notices went FINAL and their dependents reached TERMINATED."""
    return audit_wave(b, stage="FINALIZED", **kwargs)


def verified_dependent_wave(
    b: Builder,
    *,
    proof_type: Optional[str] = None,
    submit_at: str = REVIEW_INSTANT,
    **kwargs: Any,
) -> Ctx:
    """One dependent documented and accepted, so it reaches VERIFIED."""
    ctx = response_window_wave(b, **kwargs)
    b.set_clock(submit_at)
    offered = proof_type or f.ACCEPTABLE_PROOF_TYPES[ctx.dep["relationship_type"]][0]
    submission = b.submit_proof(
        ctx.case["id"], ctx.dep["id"], ctx.employee["id"], offered
    )
    ctx.submission = b.accept_proof(submission["id"])
    ctx.dep = b.read_dependent(ctx.dep["id"])
    ctx.dependents[0] = ctx.dep
    ctx.case = b.read_case(ctx.case["id"])
    ctx.program = b.read_program(ctx.program["id"])
    return ctx


def appeal_wave(
    b: Builder,
    *,
    grounds: str = "ADMINISTRATIVE_ERROR",
    stage: str = "FINALIZED",
    appeal_at: str = APPEAL_INSTANT,
    assign: bool = True,
    reviewer: Headers = REVIEWER,
    appeal_overrides: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Ctx:
    """A terminated dependent with an appeal on file, taken for review by default."""
    ctx = audit_wave(b, stage=stage, **kwargs)
    b.set_clock(appeal_at)
    ctx.appeal = b.appeal(
        ctx.case["id"],
        ctx.dep["id"],
        ctx.employee["id"],
        grounds,
        **(appeal_overrides or {}),
    )
    if assign:
        ctx.appeal = b.assign_appeal(ctx.appeal["id"], reviewer)
    return ctx


DEFAULT_CLAIM = {"service_date": "2026-09-20", "paid_cents": 150000}


def recovery_wave(
    b: Builder,
    *,
    claims: Sequence[Dict[str, Any]] = (DEFAULT_CLAIM,),
    recovery_variant: str = "STRICT",
    ineligibility_onset_date: str = DEFAULT_ONSET_DATE,
    issue: bool = False,
    waiver_credit_cents: int = 0,
    **kwargs: Any,
) -> Ctx:
    """A finalised termination with an OPEN claims recovery against its notice."""
    ctx = finalized_wave(b, claims=claims, **kwargs)
    ctx.notice = b.notice_for(ctx.dep["id"])
    ctx.recovery = b.open_recovery(
        ctx.dep["id"],
        ctx.notice["id"],
        recovery_variant,
        ineligibility_onset_date,
    )
    if issue:
        ctx.recovery = b.issue_demand(ctx.recovery["id"], waiver_credit_cents)
    ctx.program = b.read_program(ctx.program["id"])
    return ctx


def demand_wave(b: Builder, **kwargs: Any) -> Ctx:
    """A priced, issued recovery demand."""
    return recovery_wave(b, issue=True, **kwargs)


def reconciled_wave(
    b: Builder, *, reconcile_at: str = RECONCILE_INSTANT, **kwargs: Any
) -> Ctx:
    """A wave swept past the appeal window, so the program sits in RECONCILIATION."""
    ctx = finalized_wave(b, **kwargs)
    b.set_clock(reconcile_at)
    b.sweep(ctx.program["id"])
    ctx.program = b.read_program(ctx.program["id"])
    ctx.cases = b.cases(ctx.program["id"])
    ctx.case = ctx.cases[0] if ctx.cases else None
    return ctx


def poe_wave(
    b: Builder,
    *,
    poe_relationship: str = "CHILD_BIOLOGICAL",
    grace_days: int = 30,
    auto_terminate_on_lapse: bool = True,
    enroll_at: str = ANNOUNCE_INSTANT,
    poe_rule_overrides: Optional[Dict[str, Any]] = None,
    program_overrides: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Ctx:
    """An announced program that governs point-of-enrollment adds.

    The wave publishes a program with `poe_verification_enabled` true and a
    `POINT_OF_ENROLLMENT` rule for ``poe_relationship``, then enrolls a fresh
    dependent of that class so the selector binds it to the program.
    """
    overrides = dict(program_overrides or {})
    overrides.setdefault("poe_verification_enabled", True)
    rule_extra = dict(poe_rule_overrides or {})
    rule_extra.setdefault("relationship_type", poe_relationship)
    rule_extra.setdefault("phase", "POINT_OF_ENROLLMENT")
    rule_extra.setdefault("grace_days", grace_days)
    rule_extra.setdefault("auto_terminate_on_lapse", auto_terminate_on_lapse)
    ctx = announced_wave(
        b, program_overrides=overrides, extra_rules=[rule_extra], **kwargs
    )
    ctx.poe_rule = ctx.rules[-1]
    b.set_clock(enroll_at)
    ctx.poe_dependent = b.dependent(ctx.employee["id"], poe_relationship)
    ctx.program = b.read_program(ctx.program["id"])
    return ctx
