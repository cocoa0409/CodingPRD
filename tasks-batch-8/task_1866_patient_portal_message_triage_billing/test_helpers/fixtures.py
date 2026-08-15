"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: TriageNurse/FrontDesk/Provider/BillingSpecialist calls are
entity-backed by StaffMember and Patient calls are entity-backed by Patient, so
every call is made with headers built from the real entity id via the make_*
builders. PracticeAdmin is an opaque operator identity.
"""
from prd_bench_local_runner.testing import (
    build_user_headers,
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .constants import (
    DEFAULT_COPAY_CENTS,
    NURSE_TARGET_EMERGENT,
    NURSE_TARGET_ROUTINE,
    NURSE_TARGET_URGENT,
    PROVIDER_TARGET_EMERGENT,
    PROVIDER_TARGET_ROUTINE,
    PROVIDER_TARGET_URGENT,
    WIDE_COVERAGE_END,
    WIDE_COVERAGE_START,
    WORKFLOW_CLOCK,
)
from .factories import (
    assign_payload,
    complete_payload,
    cosign_payload,
    create_coverage_window_payload,
    create_delegation_grant_payload,
    create_education_notice_payload,
    create_evisit_claim_payload,
    create_on_call_shift_payload,
    create_patient_payload,
    create_pool_payload,
    create_portal_message_payload,
    create_staff_payload,
    create_time_entry_payload,
    determine_billing_payload,
    escalate_payload,
    record_adjudication_payload,
    reply_payload,
    respond_consent_payload,
    triage_payload,
)
from .test_users import TEST_USERS, make_patient_headers

ADMIN = TEST_USERS["practice_admin_headers"]

# Role each staff_type drives (PRD §2.1 role-staff consistency).
ROLE_FOR_STAFF_TYPE = {
    "NURSE": "TriageNurse",
    "FRONT_DESK": "FrontDesk",
    "PROVIDER": "Provider",
    "BILLING_SPECIALIST": "BillingSpecialist",
    "PRACTICE_ADMIN": "PracticeAdmin",
}


def staff_headers(staff: dict) -> dict:
    """Headers for a staff-backed call, bound to the StaffMember's real id."""
    return build_user_headers(staff["id"], ROLE_FOR_STAFF_TYPE[staff["staff_type"]])


def patient_headers(patient: dict) -> dict:
    """Headers for a Patient call, bound to the Patient's real id."""
    return make_patient_headers(patient["id"])


class Scenario:
    """Procedural precondition builder over the PRD endpoints.

    Every step uses the lenient setup validator so a broken precondition fails
    with a clear "Setup step failed" message naming the server response.
    """

    def __init__(self):
        self.admin = ADMIN

    # ------------------------------------------------------------------
    # Master data
    # ------------------------------------------------------------------
    def add_patient(self, full_name="Pat", plan_type="COPAY",
                    copay_cents=DEFAULT_COPAY_CENTS, coinsurance_pct=None):
        return get_success_data(api_client.create_patient(
            create_patient_payload(
                full_name=full_name, plan_type=plan_type,
                copay_cents=copay_cents, coinsurance_pct=coinsurance_pct),
            self.admin))

    def add_staff(self, staff_type, full_name="Staff"):
        return get_success_data(api_client.create_staff(
            create_staff_payload(full_name=full_name, staff_type=staff_type),
            self.admin))

    def add_pool(self, pool_kind="PROVIDER_INBOX", deadline_policy="FROM_TRIAGE",
                 name="Pool", target_minutes_emergent=PROVIDER_TARGET_EMERGENT,
                 target_minutes_urgent=PROVIDER_TARGET_URGENT,
                 target_minutes_routine=PROVIDER_TARGET_ROUTINE):
        return get_success_data(api_client.create_pool(
            create_pool_payload(
                name=name, pool_kind=pool_kind, deadline_policy=deadline_policy,
                target_minutes_emergent=target_minutes_emergent,
                target_minutes_urgent=target_minutes_urgent,
                target_minutes_routine=target_minutes_routine),
            self.admin))

    def add_coverage(self, pool_id, staff_id, start_utc=WIDE_COVERAGE_START,
                     end_utc=WIDE_COVERAGE_END):
        return get_success_data(api_client.create_coverage_window(
            create_coverage_window_payload(pool_id, staff_id, start_utc, end_utc),
            self.admin))

    def add_on_call_shift(self, provider_id, start_utc, end_utc):
        return get_success_data(api_client.create_on_call_shift(
            create_on_call_shift_payload(provider_id, start_utc, end_utc),
            self.admin))

    def add_grant(self, delegator, delegate_staff_id, pool_id,
                  start_utc=WIDE_COVERAGE_START, end_utc=WIDE_COVERAGE_END):
        """Provider creates a DelegationGrant; delegator is stamped from the
        caller's identity (PRD §3.2)."""
        return get_success_data(api_client.create_delegation_grant(
            create_delegation_grant_payload(delegate_staff_id, pool_id,
                                            start_utc, end_utc),
            staff_headers(delegator)))

    def set_clock(self, to_iso8601):
        return get_success_data(api_client.set_clock(to_iso8601, self.admin))

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def get_message(self, message_id, headers=None):
        return get_success_data(
            api_client.get_portal_message(message_id, headers or self.admin))

    def get_patient(self, patient_id, headers=None):
        return get_success_data(
            api_client.get_patient(patient_id, headers or self.admin))

    def get_staff(self, staff_id, headers=None):
        return get_success_data(
            api_client.get_staff(staff_id, headers or self.admin))

    def get_grant(self, grant_id, headers=None):
        return get_success_data(
            api_client.get_delegation_grant(grant_id, headers or self.admin))

    def get_claim(self, claim_id, headers=None):
        return get_success_data(
            api_client.get_evisit_claim(claim_id, headers or self.admin))

    def get_consent(self, consent_id, headers=None):
        return get_success_data(
            api_client.get_consent_record(consent_id, headers or self.admin))

    def burden(self, staff_id, headers=None, metric=None):
        params = {"metric": metric} if metric else None
        return get_success_data(api_client.get_burden_summary(
            staff_id, headers or self.admin, params=params))

    def list_consents(self, message_id, status=None):
        params = {"message_id": message_id}
        if status is not None:
            params["status"] = status
        data, _meta = validate_paginated(
            api_client.list_consent_records(self.admin, params=params))
        return data

    def find_consent(self, message_id, status=None):
        """Exactly one consent record must match (created_at ties possible)."""
        data = self.list_consents(message_id, status=status)
        assert len(data) == 1, (
            f"Expected exactly one consent for message {message_id} "
            f"(status={status}), got {len(data)}"
        )
        return data[0]

    def list_claims(self, **filters):
        return validate_paginated(
            api_client.list_evisit_claims(self.admin, params=filters or None))

    def list_escalations(self, **filters):
        return validate_paginated(
            api_client.list_escalations(self.admin, params=filters or None))

    # ------------------------------------------------------------------
    # Message workflow steps
    # ------------------------------------------------------------------
    def send_message(self, patient, subject="S", body="B"):
        return get_success_data(api_client.create_portal_message(
            create_portal_message_payload(subject=subject, body=body),
            patient_headers(patient)))

    def triage(self, message_id, nurse, urgency, category, pool_id,
               expected_version=None):
        """OCC-guarded triage; re-reads the current version unless given one."""
        if expected_version is None:
            expected_version = self.get_message(message_id)["version"]
        return get_success_data(api_client.triage_message(
            message_id,
            triage_payload(urgency, category, pool_id, expected_version),
            staff_headers(nurse)))

    def assign(self, message_id, nurse, staff_id=None):
        return get_success_data(api_client.assign_message(
            message_id, assign_payload(staff_id), staff_headers(nurse)))

    def start_review(self, message_id, staff):
        return get_success_data(
            api_client.start_review(message_id, staff_headers(staff)))

    def reply(self, message_id, headers, body="reply"):
        return get_success_data(
            api_client.reply_message(message_id, reply_payload(body), headers))

    def log_time(self, message_id, staff, minutes, entry_kind="CLINICAL_REVIEW",
                 note=None):
        return get_success_data(api_client.create_time_entry(
            create_time_entry_payload(message_id, entry_kind, minutes, note),
            staff_headers(staff)))

    def determine_billing(self, message_id, provider, disposition,
                          expected_version=None):
        """OCC-guarded determination; re-reads the current version unless given."""
        if expected_version is None:
            expected_version = self.get_message(message_id)["version"]
        return get_success_data(api_client.determine_billing(
            message_id,
            determine_billing_payload(disposition, expected_version),
            staff_headers(provider)))

    def respond_consent(self, consent_id, patient, decision):
        return get_success_data(api_client.respond_consent(
            consent_id, respond_consent_payload(decision),
            patient_headers(patient)))

    def complete(self, message_id, staff, summary="done"):
        return get_success_data(api_client.complete_message(
            message_id, complete_payload(summary), staff_headers(staff)))

    def cosign(self, message_id, provider, action):
        return get_success_data(api_client.cosign_message(
            message_id, cosign_payload(action), staff_headers(provider)))

    def escalate(self, message_id, staff, reason="escalation"):
        """Returns the created Escalation (201)."""
        return get_success_data(api_client.escalate_message(
            message_id, escalate_payload(reason), staff_headers(staff)))

    def acknowledge_escalation(self, escalation_id, provider):
        return get_success_data(api_client.acknowledge_escalation(
            escalation_id, staff_headers(provider)))

    def close(self, message_id, staff):
        return get_success_data(
            api_client.close_message(message_id, staff_headers(staff)))

    # ------------------------------------------------------------------
    # Claim lifecycle steps
    # ------------------------------------------------------------------
    def create_claim(self, message_id, rendering_provider_id, biller):
        return get_success_data(api_client.create_evisit_claim(
            create_evisit_claim_payload(message_id, rendering_provider_id),
            staff_headers(biller)))

    def submit_claim(self, claim_id, biller):
        return get_success_data(
            api_client.submit_claim(claim_id, staff_headers(biller)))

    def adjudicate(self, claim_id, biller, outcome, denial_reason=None):
        return get_success_data(api_client.record_adjudication(
            claim_id, record_adjudication_payload(outcome, denial_reason),
            staff_headers(biller)))

    def rework_claim(self, claim_id, biller):
        return get_success_data(
            api_client.rework_claim(claim_id, staff_headers(biller)))

    def void_claim(self, claim_id, biller):
        return get_success_data(
            api_client.void_claim(claim_id, staff_headers(biller)))

    # ------------------------------------------------------------------
    # Education notices
    # ------------------------------------------------------------------
    def issue_notice(self, message_id, nurse, notice_kind="EMERGENT_MISUSE",
                     body="education", blocking=None):
        return get_success_data(api_client.create_education_notice(
            create_education_notice_payload(message_id, notice_kind, body,
                                            blocking=blocking),
            staff_headers(nurse)))

    def acknowledge_notice(self, notice_id, patient):
        return get_success_data(api_client.acknowledge_education_notice(
            notice_id, patient_headers(patient)))


# ---------------------------------------------------------------------------
# Tier 1/2: practice shells (master data + pool + coverage + clock)
# ---------------------------------------------------------------------------

def provider_pool_practice(plan_type="COPAY", copay_cents=DEFAULT_COPAY_CENTS,
                           coinsurance_pct=None, deadline_policy="FROM_TRIAGE",
                           targets=(PROVIDER_TARGET_EMERGENT,
                                    PROVIDER_TARGET_URGENT,
                                    PROVIDER_TARGET_ROUTINE),
                           clock=WORKFLOW_CLOCK, with_biller=True,
                           with_coverage=True):
    """Scenario + nurse + provider (+ billing specialist) + PROVIDER_INBOX pool
    + patient + wide provider coverage window; logical clock pinned.

    Returns a context dict: scn, nurse, provider, biller, pool, patient.
    """
    scn = Scenario()
    nurse = scn.add_staff("NURSE", "Nurse N")
    provider = scn.add_staff("PROVIDER", "Dr P")
    ctx = {"scn": scn, "nurse": nurse, "provider": provider}
    if with_biller:
        ctx["biller"] = scn.add_staff("BILLING_SPECIALIST", "Bill S")
    ctx["pool"] = scn.add_pool(
        "PROVIDER_INBOX", deadline_policy, name="ProvInbox",
        target_minutes_emergent=targets[0], target_minutes_urgent=targets[1],
        target_minutes_routine=targets[2])
    ctx["patient"] = scn.add_patient(plan_type=plan_type, copay_cents=copay_cents,
                                     coinsurance_pct=coinsurance_pct)
    if clock is not None:
        scn.set_clock(clock)
    if with_coverage:
        scn.add_coverage(ctx["pool"]["id"], provider["id"])
    return ctx


def nurse_pool_practice(deadline_policy="FROM_TRIAGE",
                        targets=(NURSE_TARGET_EMERGENT, NURSE_TARGET_URGENT,
                                 NURSE_TARGET_ROUTINE),
                        clock=WORKFLOW_CLOCK, with_coverage=True):
    """Scenario + nurse + NURSE_TRIAGE pool + patient + wide nurse coverage.

    Returns a context dict: scn, nurse, pool, patient.
    """
    scn = Scenario()
    nurse = scn.add_staff("NURSE", "Nurse N")
    ctx = {"scn": scn, "nurse": nurse}
    ctx["pool"] = scn.add_pool(
        "NURSE_TRIAGE", deadline_policy, name="NurseTriage",
        target_minutes_emergent=targets[0], target_minutes_urgent=targets[1],
        target_minutes_routine=targets[2])
    ctx["patient"] = scn.add_patient()
    if clock is not None:
        scn.set_clock(clock)
    if with_coverage:
        scn.add_coverage(ctx["pool"]["id"], nurse["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: full-lifecycle shortcuts (message pipeline)
# ---------------------------------------------------------------------------

def message_in_review(ctx, urgency="URGENT", category="CLINICAL", subject="S",
                      assignee_key="provider", work=()):
    """Send -> triage -> assign -> start-review -> log time entries.

    work: list of (staff_key, entry_kind, minutes) tuples logged in order.
    Returns the freshly read message.
    """
    scn = ctx["scn"]
    msg = scn.send_message(ctx["patient"], subject=subject,
                           body=f"{subject} body")
    scn.triage(msg["id"], ctx["nurse"], urgency, category, ctx["pool"]["id"])
    assignee_id = ctx[assignee_key]["id"] if assignee_key else None
    scn.assign(msg["id"], ctx["nurse"], staff_id=assignee_id)
    if assignee_key:
        scn.start_review(msg["id"], ctx[assignee_key])
    for staff_key, entry_kind, minutes in work:
        scn.log_time(msg["id"], ctx[staff_key], minutes, entry_kind=entry_kind)
    return scn.get_message(msg["id"])


def message_in_review_with_minutes(ctx, minutes=8, urgency="URGENT",
                                   category="CLINICAL", subject="S",
                                   assignee_key="provider"):
    """message_in_review with the provider logging `minutes` CLINICAL_REVIEW."""
    work = [("provider", "CLINICAL_REVIEW", minutes)] if minutes else []
    return message_in_review(ctx, urgency=urgency, category=category,
                             subject=subject, assignee_key=assignee_key,
                             work=work)


def chargeable_message(ctx, minutes=8, urgency="URGENT", subject="S"):
    """IN_REVIEW message determined BILLABLE_CANDIDATE with consent GRANTED.

    Returns (message, consent): message is back IN_REVIEW and CHARGEABLE;
    consent is the freshly read GRANTED record with its pinned disclosed
    code/fee.
    """
    scn = ctx["scn"]
    msg = message_in_review_with_minutes(ctx, minutes=minutes, urgency=urgency,
                                         subject=subject)
    scn.determine_billing(msg["id"], ctx["provider"], "BILLABLE_CANDIDATE")
    consent = scn.find_consent(msg["id"], status="REQUESTED")
    scn.respond_consent(consent["id"], ctx["patient"], "GRANTED")
    return scn.get_message(msg["id"]), scn.get_consent(consent["id"])


def resolved_chargeable_message(ctx, minutes=8, urgency="URGENT", subject="S"):
    """chargeable_message + provider completion. Returns (message, consent);
    the message stands RESOLVED and CHARGEABLE."""
    scn = ctx["scn"]
    msg, consent = chargeable_message(ctx, minutes=minutes, urgency=urgency,
                                      subject=subject)
    scn.complete(msg["id"], ctx["provider"], summary=f"{subject} treated")
    return scn.get_message(msg["id"]), consent


def draft_claim(ctx, minutes=8, urgency="URGENT", subject="S"):
    """resolved_chargeable_message + DRAFT claim rendered by the provider.
    Returns (message, consent, claim)."""
    scn = ctx["scn"]
    msg, consent = resolved_chargeable_message(ctx, minutes=minutes,
                                               urgency=urgency, subject=subject)
    claim = scn.create_claim(msg["id"], ctx["provider"]["id"], ctx["biller"])
    return scn.get_message(msg["id"]), consent, claim


def submitted_claim(ctx, minutes=8, urgency="URGENT", subject="S"):
    """draft_claim + submit. Returns (message, consent, claim); the claim
    stands SUBMITTED and the patient's outstanding balance was debited."""
    scn = ctx["scn"]
    msg, consent, claim = draft_claim(ctx, minutes=minutes, urgency=urgency,
                                      subject=subject)
    claim = scn.submit_claim(claim["id"], ctx["biller"])
    return msg, consent, claim
