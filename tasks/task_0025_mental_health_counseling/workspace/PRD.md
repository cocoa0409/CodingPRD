# Mental Health Counseling API — Product Requirements Document

## 1. Introduction

The Mental Health Counseling Platform exists to deliver licensed, regulated mental-health care over an online channel where the patient pool, the practitioner pool, and the moment of clinical contact are all separated by network distance. The product brings together five concerns that are usually handled by independent systems — practitioner credentialing, patient scheduling, encrypted clinical record-keeping, crisis-response escalation, and revenue settlement — into a single API surface so that the audit trail, the consent boundary, and the financial ledger remain in sync as a session moves from booking to completion.

Three pressures shape the design. First, the work is regulated: every counselor must hold a current license, accumulate a fixed number of supervised hours and continuing-education hours per cycle, and be removable from the active roster the moment any of those guarantees lapses. Second, the work is clinical: a counselor reading a session note, or a keyword detector running over one, may discover that the client is at imminent risk; the platform must have a deterministic path from "risk detected" to "follow-up tracked" that no operator can short-circuit. Third, the work is commercial: counselors earn a share of session revenue, the platform owes tax, refunds depend on cancellation timing, and a settled payout cannot quietly move money to a counselor who has just been disqualified.

This document specifies the behaviours an implementation must guarantee for the platform to satisfy those three pressures simultaneously. It is written for an engineer who will build the API server; the product manager has organised it so that global contracts (response shape, authentication, pagination, common fields) are stated once at the top, business workflows are described in narrative form in the middle, and the endpoint and error catalogues at the end exist only to enumerate routes and error identifiers — never to define behaviour.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting rules that apply to every endpoint. Each subsection here is a contract: an implementer must satisfy it everywhere unless an explicit business rule in §3 overrides it.

### 2.1. User and Role-Based Access Control

Every request to the API — except the public counselor-browse endpoints called out in §3 — must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, identifying the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_AUTH_MISSING` and HTTP 401. A request whose role is not authorised for the targeted endpoint is rejected with `ERR_FORBIDDEN` and HTTP 403.

The platform recognises six roles: `Public`, `Client`, `Counselor`, `Supervisor`, `CrisisResponder`, and `PlatformAdmin`. Each role's identity is interpreted differently when ownership is checked, and the implementer must apply the matching rule:

- When `X-User-Role` is `Client`, `X-User-ID` is the `id` of a persisted Client record. Ownership checks on any resource that references a Client (an Appointment's `client_id`, a CounselingRecord's `client_id`, a CrisisIncident's `client_id`) compare the resource's foreign-key field to `X-User-ID`. A `Client` may only act on appointments where `X-User-ID` equals `client_id`, on their own client profile, on their own risk summary, and on their own refund estimates.
- When `X-User-Role` is `Counselor`, `X-User-ID` is the `id` of a persisted Counselor record. A `Counselor` may only act on availability slots, appointments, counseling records, supervision sessions, CE records, certification cycles, and counselor-profile updates whose `counselor_id` matches `X-User-ID`.
- When `X-User-Role` is `Supervisor`, `X-User-ID` is also the `id` of a persisted Counselor record (a senior counselor acting in supervisory capacity). Ownership checks for supervision approval/rejection compare `X-User-ID` to the SupervisionSession's `supervisor_id`; visibility into counseling records is limited to records of supervisees whose own SupervisionSession rows list this `X-User-ID` as supervisor.
- When `X-User-Role` is `CrisisResponder`, `X-User-ID` is an opaque crisis-team operator identifier not tied to any persisted entity. The server records it on a CrisisIncident's `assigned_responder_id` at handover but does not compare it to any entity's `id`.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque platform-operator identifier not tied to any persisted entity. The server records it on a CertificationCycle's `decided_by_user_id` when an admin decides a cycle, but does not compare it to any entity's `id`.
- When `X-User-Role` is `Public`, `X-User-ID` is an opaque visitor identifier; only the public catalogue endpoints accept this role.

The role names above are case-sensitive and must match these exact spellings throughout the system, including in the AuditLogEntry's `actor_role` field.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

---

### 2.3. Pagination

List endpoints accept two query parameters that control paging. The `limit` parameter caps the number of items returned; if omitted it defaults to 10, has a minimum of 1 and a maximum of 100. The `offset` parameter skips the first N items; if omitted it defaults to 0 and may not be negative. Values outside these bounds — `limit` below 1, `limit` above 100, or `offset` below 0 — are rejected with `ERR_PAGINATION_INVALID`.

Unless an endpoint's narrative explicitly states otherwise, list responses are sorted by `created_at` ascending. The pagination block of the response `meta` carries four fields — `limit`, `offset`, `total_count`, and `has_more` — for every list response.

### 2.4. Common Resource Properties and Versioning

Every primary resource that participates in mutation — Counselor, Client, CertificationCycle, AvailabilitySlot, Appointment, CrisisIncident, Payout, SupervisionSession, ContinuingEducationRecord — carries the same four system-managed fields:

- `id` is a server-minted UUID without any type prefix.
- `created_at` is an ISO 8601 UTC timestamp with three fractional digits, set at creation and never modified.
- `updated_at` is an ISO 8601 UTC timestamp with three fractional digits that the server refreshes on every mutation of the resource. Cascaded mutations driven by another resource's transition (for example, a Counselor disqualification that releases that counselor's availability slots) are mutations for this purpose: the affected resources have their `updated_at` refreshed.
- `version` is an integer that starts at 1 on creation and increments by 1 on every mutation, including cascaded mutations.

Two entities are immutable enough that they carry only `id` and `created_at`, with no `updated_at` and no `version`: `CounselingRecord` (whose mutability is governed by the redaction state machine and the `last_accessed_at` field rather than a version counter) and `SettlementLedger` (whose rows are append-only — once a CHARGE or REFUND row is written it is never updated) and `AuditLogEntry` (which is append-only by definition). For these three, callers MUST NOT supply a `version` in any request, and the server MUST NOT return one.

### 2.5. Optimistic Concurrency Control

For every PATCH endpoint and every action endpoint that targets a versioned resource, the request body MAY include the latest known `version` of the resource. When supplied, the server compares it against the current stored value: a match allows the mutation to proceed (and increments `version` by 1); a mismatch rejects the request with `ERR_VERSION_CONFLICT` and HTTP 409. When `version` is omitted, the server applies the mutation without an OCC check.

### 2.6. Nested Resource Retrieval and Path Validation

When a path contains multiple identifiers — for example, an action that targets a specific certification cycle of a specific counselor — the server resolves them strictly left to right and rejects with `ERR_NOT_FOUND` and HTTP 404 the moment the first non-existent identifier is encountered. Body-referenced foreign keys (such as a slot identifier inside an appointment-creation payload, or an appointment identifier inside a counseling-record payload) are validated after path resolution; an unresolvable body reference is rejected with `ERR_REF_NOT_FOUND` and HTTP 422. Any field-level format problem — a missing required field, an unparseable timestamp, a string where an integer was expected — falls through to the generic `ERR_VALIDATION` and HTTP 422.

### 2.7. Validation Priority and Evaluation Order

Validations are applied in a fixed priority order, lowest priority number first, and the first failing rule determines the response. The order is: (1) authentication header presence (`ERR_AUTH_MISSING`), (2) role authorisation (`ERR_FORBIDDEN`), (3) path-parameter existence (`ERR_NOT_FOUND`), (4) body-referenced foreign-key existence (`ERR_REF_NOT_FOUND`), then (5) state validity for the requested transition (`ERR_INVALID_STATE`), then (6) the counselor-must-be-`ACTIVE` gate that protects slot creation, booking and session start (`ERR_COUNSELOR_NOT_ACTIVE`), then the safety, eligibility, channel, temporal, fiscal and concurrency rules in numbered priority. The intended consequence is that an authentication failure always preempts a state failure, a state failure always preempts a fiscal one, and the counselor-active gate fires before any of the more specific scheduling or pricing checks. Whenever two rules could both apply, the lower priority number wins.

### 2.8. Monetary Precision and Per-Component Rounding

All monetary amounts in the system are denominated in integer USD cents. Tax is computed at a basis-point rate of 875 (representing 8.75%); the constant `TAX_BPS` lives in the platform settlement engine and is referenced directly by every charge and refund calculation. Counselor revenue share is similarly stored in basis points on the counselor's `revenue_share_bps` field, with a default of 7000 (70%) and a permitted range from 0 to 10000.

The platform pins one rounding rule everywhere money is computed: round half up to the nearest cent. When a calculation produces multiple components — a tax amount, a counselor share, a platform share — each component is rounded independently, in the order written in the calculation, and the platform share is then derived as the residual rather than recomputed from a complementary basis-points fraction. This per-component rounding order is observable: for the same gross amount, the result of "round counselor share, then platform share = gross minus counselor share" can differ by one cent from the result of "round platform share directly from the residual basis points", and the platform requires the former.

### 2.9. Hierarchical State Cascade and Audit

Many transitions in this system have effects that reach beyond the resource being acted on. A counselor moving to `SUSPENDED` or `DISQUALIFIED` reaches into that counselor's `OPEN` and `HELD` availability slots, into their `HOLD` and `CONFIRMED` appointments, and ultimately into the settlement ledger. A crisis incident moving to `HANDED_OVER` reaches into the in-flight appointment that surfaced it. A certification cycle being approved reaches into the counselor that owns it and into the next cycle that gets auto-created. Every such cascade refreshes `updated_at` and increments `version` on every resource it touches, and the platform appends an `AuditLogEntry` whose `actor_role` is the role of the requester (or `system` for sweep-driven transitions), whose `actor_user_id` mirrors `X-User-ID` at the time of action, whose `action` is drawn from the audit catalogue (`RECORD_READ`, `RECORD_EXPORT`, `RECORD_PURGE`, `CRISIS_DETECTED`, `CRISIS_HANDOVER`, `CRISIS_NOTIFY`, `COUNSELOR_DISQUALIFIED`, `RECERT_DECISION`), whose `target_entity` names the affected entity type, whose `target_id` carries the affected entity's `id`, and whose `payload_summary` is a small JSON object with action-specific keys carrying no PHI and ciphertext references only.

### 2.10. Encrypted Storage and Retention

Counseling records are end-to-end encrypted at the application boundary. The server stores only ciphertext: the `encrypted_note_blob` field carries the base64-encoded ciphertext supplied by the counselor, and the `content_key_wrapped` field carries that record's per-record content key wrapped by the platform KMS. Neither field is ever returned in list responses, and the wrapped content key is never returned to any client.

Each record carries a `retention_expires_at` that the server sets at creation to seven years after `created_at`. A retention sweep compares this timestamp against current time and, when it has been reached, transitions the record from `ACTIVE` to `PURGED`: `encrypted_note_blob` is set to null, `content_key_wrapped` is set to null, and `redaction_status` is set to `PURGED`. Subsequent reads or exports of a `PURGED` record return HTTP 410 with `ERR_RECORD_PURGED`.

Every authorised read of a record refreshes its `last_accessed_at` field (which is null until the first read) and appends an `AuditLogEntry` with action `RECORD_READ`. Every authorised export appends an entry with action `RECORD_EXPORT`. Every retention purge appends an entry with action `RECORD_PURGE`.

### 2.11. Time Zones, Working Hours, and Rest Intervals

Every Counselor and every Client carries an IANA `timezone` field (for example `America/Los_Angeles`). The platform's daily working-hour cap is evaluated in the counselor's local calendar day, not in UTC: a slot whose UTC range crosses local midnight has its sixty minutes split between the two local days for the purpose of the daily cap. The weekly cap is evaluated in the counselor's ISO calendar week. Slot start and end timestamps themselves are recorded in UTC.

All availability slots have a fixed duration of exactly sixty minutes — `end_at` MUST equal `start_at` plus sixty minutes — and the platform enforces three further temporal invariants on every slot the counselor creates. First, the proposed slot must not overlap any other slot of the same counselor in `OPEN`, `HELD`, or `BOOKED` status when overlap is evaluated as a half-open interval intersection (so two slots that touch end-to-start at exactly the same instant are adjacent, not overlapping). Second, the gap from the proposed slot to its nearest neighbouring slot of the same counselor must be either zero (fully adjacent) or at least fifteen minutes; any gap strictly greater than zero and strictly less than fifteen minutes violates the rest interval. Third, the cumulative minutes of slots overlapping the same local calendar day plus the proposed sixty must not exceed eight hours, and the cumulative minutes of slots overlapping the same ISO week plus the proposed sixty must not exceed thirty hours. The thresholds are applied with strict greater-than-cap rejection: a day total landing exactly on eight hours is permitted, eight hours and one minute is not.

### 2.12. Concurrency and Serialization Guarantees

The platform serialises a small number of high-contention operations to keep its invariants intact. The implementer is required to enforce each of the following serialisations and to return the named error to the loser:

- When two clients race to create an appointment against the same `OPEN` availability slot, exactly one wins the `OPEN` to `HELD` transition; the loser is rejected with `ERR_SLOT_TAKEN` and HTTP 409.
- When a confirm and a cancel race on the same `HOLD` appointment, exactly one succeeds and the loser sees the new state with `ERR_INVALID_STATE` and HTTP 409.
- When two supervisors race to approve the same SupervisionSession, exactly one becomes `APPROVED`; the loser is rejected with `ERR_INVALID_STATE` and HTTP 409.
- When a counselor disqualification completes while an appointment confirm is in flight, the in-flight confirm is rejected with `ERR_COUNSELOR_NOT_ACTIVE` and HTTP 409 because the counselor is no longer `ACTIVE` at the moment the confirm reaches its state check.
- When two counselors race to write a counseling record for the same appointment, the unique constraint on `appointment_id` admits exactly one; the loser is rejected with `ERR_RECORD_ALREADY_EXISTS` and HTTP 409.
- When two crisis responders both invoke handover on the same `DETECTED` incident, exactly one wins; the loser is rejected with `ERR_INVALID_STATE` and HTTP 409.
- When a reschedule lands at the moment the appointment crosses the twenty-four-hour pre-start window, the reschedule rechecks the temporal precondition after acquiring the resource lock. If by the time it acquires the lock the appointment's `start_at` is at or within twenty-four hours of the current time, the reschedule is rejected with `ERR_RESCHEDULE_WINDOW_CLOSED` and HTTP 409.
- When two payout creations target the same counselor with overlapping windows, only one is admitted; the loser is rejected with `ERR_PAYOUT_WINDOW_OVERLAP` and HTTP 409.

## 3. Business Logic & Workflows

The following subsections describe the platform's behaviour from the perspective of the people who use it. Each subsection focuses on one cluster of resources or one stage of a counselor's working life; cross-cutting consequences are stated in whichever subsection makes the most narrative sense, even when the resource being mutated lives elsewhere.

### 3.1. Bringing a Counselor onto the Platform

A new counselor record is created by a `PlatformAdmin`. The submitted payload carries the counselor's `full_name`, the unique lowercase `email` they will use to sign in and to receive payouts, the government-issued `license_number` (which must be unique across all counselors who are not `DISQUALIFIED`), the `license_expires_at` instant after which the counselor's licence ceases to be honoured, an array of `specialty_tags` drawn from the platform-defined enumeration `ANXIETY`, `DEPRESSION`, `TRAUMA`, `FAMILY`, `ADDICTION`, `ADOLESCENT`, `EATING_DISORDER`, `GRIEF` (the array must be non-empty), an array of `supported_channels` drawn from `TEXT`, `AUDIO`, `VIDEO` (also non-empty), the IANA `timezone` in which the counselor authors their availability, and an optional `revenue_share_bps` overriding the default of 7000.

On registration the counselor's `status` begins at `PENDING_CERT`. The platform automatically opens that counselor's first `CertificationCycle` in the `OPEN` state with `cycle_index` of 1, `required_supervision_hours` of 40 (frozen at cycle creation — the first cycle's bar is forty supervision hours, every subsequent cycle's bar is twenty), `required_ce_hours` of 12, `window_start_at` equal to the counselor's `created_at`, and `window_end_at` equal to that instant plus 365 days. Both `total_supervision_hours` and `total_ce_hours` on the counselor begin at zero and are recomputed whenever a SupervisionSession is approved or a ContinuingEducationRecord is approved.

A counselor can update their own profile through a PATCH that admits any combination of `specialty_tags`, `supported_channels`, `timezone`, `license_expires_at`, and a `version` for optimistic concurrency. A `PlatformAdmin` may make the same edits on any counselor. Shrinking `supported_channels` does not retroactively cancel existing slots or appointments; bookings that already reference a now-dropped channel remain legal until they cancel naturally.

### 3.2. The Certification and Recertification Lifecycle

A `CertificationCycle` exists to gate the moments at which a counselor may take clients. Each cycle has a `status` that begins at `OPEN`, may move to `UNDER_REVIEW` when the counselor submits it, and ultimately reaches one of three terminal outcomes — `APPROVED`, `EXPIRED`, or `REJECTED`.

Submission, performed by the counselor, is permitted only while the cycle is `OPEN` and only when four things are simultaneously true: the current time is strictly before `window_end_at`; the sum of `duration_hours` over SupervisionSession rows that reached `APPROVED` whose approval timestamp falls within the half-closed range `[window_start_at, window_end_at]` for this counselor is at least the cycle's `required_supervision_hours`; the sum of `hours_credited` over ContinuingEducationRecord rows that reached `APPROVED` whose approval timestamp falls within the same range is at least the cycle's `required_ce_hours`; and the counselor's `license_expires_at` is strictly after the current time. The supervision and CE hours are evaluated in steps of half-hour granularity and the comparisons are non-strict (at least, not greater than). When all four checks pass, the cycle transitions to `UNDER_REVIEW`. When any one fails the request is rejected with `ERR_INVALID_STATE`.

A `PlatformAdmin` then either approves or rejects the cycle. Approval is permitted only while the cycle is `UNDER_REVIEW` and is itself gated by a segregation-of-duties rule: the admin acting as `decided_by_user_id` must not have created any of the SupervisionSession rows that contributed to this cycle's eligibility — otherwise the request is rejected with `ERR_RECERT_SOD` and HTTP 403. On approval, the cycle's `decided_at` is set to current time and `decided_by_user_id` is set to `X-User-ID`; the counselor's `status` advances per its own state machine (`PENDING_CERT` to `ACTIVE` for cycle 1, `SUSPENDED` to `ACTIVE` for any later cycle); a fresh CertificationCycle is auto-created in `OPEN` with `cycle_index` equal to the previous index plus one, with `window_start_at` equal to the just-approved cycle's `window_end_at`, with `window_end_at` equal to that boundary plus seven hundred and thirty days, with `required_supervision_hours` of twenty and `required_ce_hours` of twelve; and an `AuditLogEntry` with action `RECERT_DECISION` is appended. Rejection sets `decided_at` and `decided_by_user_id` but does not change the counselor's status and does not auto-create a new cycle: the counselor must explicitly request the start of a new cycle from a `PlatformAdmin`.

When current time crosses `window_end_at` while the cycle is still `OPEN`, a system-driven recertification sweep transitions the cycle to `EXPIRED` with `decided_at` set to current time and `decided_by_user_id` set to null. If at that instant the counselor is `ACTIVE`, the same sweep cascades into the counselor's own state machine and moves the counselor from `ACTIVE` to `SUSPENDED`. The same sweep also catches cycles that are still `UNDER_REVIEW` more than fourteen days past `window_end_at`, transitioning those to `EXPIRED` with the same effects. The `ACTIVE` to `SUSPENDED` cascade has its own consequences: every `OPEN` availability slot of that counselor auto-transitions to `BLOCKED`, every appointment of that counselor still in `HOLD` auto-cancels with `cancellation_reason` set to `COUNSELOR_CANCEL`, and any `CONFIRMED` future appointments remain in place (an admin must manually cancel them to issue refunds). When the counselor later submits and gets approved on a subsequent cycle, the `SUSPENDED` to `ACTIVE` transition fires; previously `BLOCKED` slots are NOT auto-restored — the counselor must create new slots.

A counselor may be removed from the platform entirely via a disqualification action by a `PlatformAdmin`. This is permitted while the counselor is in `ACTIVE` or `SUSPENDED` and moves the counselor to the terminal `DISQUALIFIED` state. The cascade reaches three layers deep: every `OPEN` and `HELD` availability slot of that counselor moves to `RELEASED`; every appointment in `HOLD` cancels with `cancellation_reason` of `COUNSELOR_CANCEL`; every `CONFIRMED` future appointment cancels with `cancellation_reason` of `COUNSELOR_CANCEL`, has `refund_state` set to `FULL_REFUNDED`, and gets a corresponding REFUND row written to `SettlementLedger`; and an `AuditLogEntry` with action `COUNSELOR_DISQUALIFIED` is appended. The disqualify request body may carry an optional free-text `reason`.

### 3.3. Onboarding a Client and the First-Visit Assessment

A client record is also created by a `PlatformAdmin`. The payload carries the client's `full_name`, the unique lowercase `email`, the client's IANA `timezone` (used when rendering slot times in the browse experience), and the two emergency-contact fields `emergency_contact_name` and `emergency_contact_phone`. The phone must match the E.164 pattern of a leading plus sign followed by a digit between 1 and 9 and then six to fourteen further digits. On registration `assessment_status` begins at `PENDING`, `package_balance_sessions` begins at zero, and `risk_flag` begins at `NONE`.

A `PENDING` assessment status is a hard gate on what kind of appointment the client may book. Until the client has completed an `INTAKE` appointment, every other `appointment_type` is rejected: a client whose `assessment_status` is `PENDING` and who attempts to book a `STANDARD` or `FOLLOW_UP` appointment is rejected with `ERR_INTAKE_REQUIRED`. Symmetrically, a client whose `assessment_status` is `IN_PROGRESS` (meaning their intake appointment is confirmed but not yet completed) may not book a second `INTAKE` — the request is rejected with `ERR_INTAKE_ALREADY_IN_PROGRESS`. The system advances `assessment_status` from `PENDING` to `IN_PROGRESS` at the moment the intake appointment confirms, and from `IN_PROGRESS` to `COMPLETED` at the moment the intake session completes.

A client (or their administrator) may update their own profile through a PATCH carrying `emergency_contact_name`, `emergency_contact_phone`, `timezone`, and `version` for OCC. A `PlatformAdmin` may also credit prepaid sessions to the client's package by submitting a payload with `sessions` and `version`; this increments `package_balance_sessions` by the supplied count.

### 3.4. Authoring Availability and the Booking Window

A counselor publishes the times at which they will see clients by creating availability slots. Each slot carries `counselor_id`, `start_at`, `end_at`, and `channel`, with `start_at` and `end_at` recorded in UTC. The creation request is gated by the counselor being `ACTIVE` (otherwise `ERR_COUNSELOR_NOT_ACTIVE`) and by the chosen `channel` being one of the values listed in that counselor's `supported_channels` (otherwise `ERR_CHANNEL_NOT_SUPPORTED`). The slot's duration is then checked: `end_at` must equal `start_at` plus exactly sixty minutes, with anything else rejected as `ERR_INVALID_SLOT_DURATION`. The same payload is then run through the four scheduling invariants of §2.11 — overlap (`ERR_SLOT_OVERLAP`), rest interval (`ERR_REST_INTERVAL`), daily cap (`ERR_DAILY_CAP_EXCEEDED`) and weekly cap (`ERR_WEEKLY_CAP_EXCEEDED`). On success the slot is persisted with `status` of `OPEN` and both `held_until` and `held_appointment_id` null.

A counselor may delete a slot they own as long as it is still `OPEN`; the delete returns 204 No Content and transitions `status` to `RELEASED`. A delete on a slot in `HELD`, `BOOKED`, `BLOCKED`, or `RELEASED` is rejected with `ERR_INVALID_STATE`.

A client browsing the catalogue calls the public counselor list and the public availability list. The counselor list accepts query filters `specialty_tag`, `channel`, and `timezone`, paginated by `limit` and `offset`, and returns only `ACTIVE` counselors. The availability list accepts `counselor_id`, `status`, `channel`, `from`, and `to` along with pagination parameters.

A booking is initiated by a `Client` who submits an appointment with `counselor_id`, `client_id`, `slot_id`, `appointment_type`, and `payment_mode`. Five preconditions are enforced before the slot's `OPEN` to `HELD` transition fires: the counselor must be `ACTIVE`, the current time must be strictly less than `start_at` minus one hour (otherwise `ERR_BOOKING_TOO_LATE`), either the client's `assessment_status` must be `COMPLETED` or the chosen `appointment_type` must be `INTAKE` (otherwise the assessment-gate errors of §3.3 apply), the slot's `channel` must be in the counselor's `supported_channels`, and the working-hour and rest-interval invariants must continue to hold for this counselor. On success the slot transitions to `HELD` with `held_until` set to current time plus fifteen minutes and `held_appointment_id` set to the new appointment's `id`, the appointment is persisted in `HOLD` with `channel` mirrored from the slot, and the response carries the new appointment.

A `Client` may then confirm. The confirm action transitions slot from `HELD` to `BOOKED` and appointment from `HOLD` to `CONFIRMED`, and is only valid while current time is strictly less than the slot's `held_until` (otherwise `ERR_HOLD_EXPIRED`) and while the linked appointment is still in `HOLD`. Payment must clear: for `PAY_PER_SESSION` the platform's payment authorisation must succeed; for `PACKAGE` the client's `package_balance_sessions` must be at least 1 (otherwise `ERR_INSUFFICIENT_PACKAGE_BALANCE`). On confirmation, `confirmed_at` is set to current time, the slot becomes `BOOKED`, a CHARGE row is written to `SettlementLedger`, and if the payment mode is `PACKAGE` the client's `package_balance_sessions` is decremented by one. When the appointment is an `INTAKE` and the client's `assessment_status` was `PENDING` at confirmation, the same operation flips `assessment_status` to `IN_PROGRESS`.

If the hold expires before confirmation, a periodic hold-expiry sweep runs across all `HELD` slots whose `held_until` has elapsed, transitioning the slot from `HELD` back to `OPEN` and the appointment from `HOLD` to `CANCELLED` with `cancellation_reason` set to `NO_SHOW_AUTO`. The same sweep clears `held_until` and `held_appointment_id` on the slot. A manual cancellation while still in `HOLD`, by contrast, sets `cancellation_reason` to `CLIENT_CANCEL` and moves the slot to `RELEASED` rather than back to `OPEN` — the manual exit consumes the slot. Neither path writes a SettlementLedger entry because no charge was ever issued.

### 3.5. The Confirmed Appointment: Reschedule, Cancellation, and Refund

A `CONFIRMED` appointment is the platform's centre of gravity. From here it has five possible departures: reschedule to a different slot, cancel before start, start the session, advance to no-show by sweep, or cancel mid-session because of crisis handover.

Rescheduling is performed by either the `Client` or the owning `Counselor` and is admitted only while current time is strictly less than the appointment's confirmed `start_at` minus twenty-four hours; closer than that, the request is rejected with `ERR_RESCHEDULE_WINDOW_CLOSED`. The request body carries `new_slot_id`, the identifier of an `OPEN` slot belonging to the same counselor that satisfies all the booking validations of §3.4. Reschedule also enforces a fiscal rule: if the platform's current `list_price_cents` for that counselor differs from the `list_price_cents` frozen on the original appointment, the reschedule is rejected with `ERR_PRICE_DRIFT` and the client must cancel and rebook. On success, the old slot is released, the new slot transitions `OPEN` to `HELD` to `BOOKED` in a single operation, and the appointment's `slot_id` is replaced; during the operation the appointment is briefly visible in the transient `RESCHEDULED` state, but the operation completes by returning the appointment to `CONFIRMED` on the new slot. No new charge is written and no refund is issued when the price has not drifted.

Cancellation of a `CONFIRMED` appointment is permitted to the `Client`, the owning `Counselor`, or a `PlatformAdmin`. The request body may carry an optional `reason`. The transition sets `cancellation_reason`, releases the slot, and triggers the refund calculation. The refund engine first measures hours-to-start as `start_at` minus current time expressed in hours. The refund decision then depends on `cancellation_reason`: if the reason is `COUNSELOR_CANCEL` or `CRISIS_HANDOVER`, `refund_state` is `FULL_REFUNDED` and the refund's gross amount is the appointment's frozen `list_price_cents`; if the reason is `CLIENT_CANCEL`, hours-to-start at least twenty-four yields `FULL_REFUNDED` with gross equal to `list_price_cents`, hours-to-start less than twenty-four but at least two yields `PARTIAL_REFUNDED` with gross equal to `list_price_cents` multiplied by one half and rounded half up to the nearest cent, and hours-to-start less than two yields `NON_REFUNDABLE` with gross of zero. The tax amount on the refund is the refund gross multiplied by the basis-points tax rate `TAX_BPS` of 875 divided by 10000, rounded half up; the counselor's share of the refund is the refund gross multiplied by the counselor's `revenue_share_bps` divided by 10000, rounded half up; the platform's share is the refund gross minus the counselor's share. All three components are recorded with negative sign on the REFUND row of `SettlementLedger`. When `refund_state` is `FULL_REFUNDED` or `PARTIAL_REFUNDED` and the appointment had been paid by `PACKAGE`, the client's `package_balance_sessions` is incremented by one as part of the same operation.

The platform also exposes a forward-looking refund estimate. A read-only forecast computes the same decision tree but uses strict greater-than comparisons rather than the inclusive comparisons of the final transition: hours-to-start strictly greater than twenty-four returns `FULL`, strictly greater than two returns `PARTIAL`, otherwise `NON_REFUNDABLE`. The boundary case is intentional: at hours-to-start of exactly 24.0, the forward estimate reports `PARTIAL_REFUNDED` while the actual cancellation transition would land on `FULL_REFUNDED`.

Starting the session is a counselor action. The transition from `CONFIRMED` to `IN_SESSION` is admitted only while current time is at or after `start_at` minus five minutes and strictly before `start_at` plus fifteen minutes, and only while the counselor is `ACTIVE`; on success `started_at` is set to current time. If the counselor never starts and current time advances to at least `start_at` plus thirty minutes while still `CONFIRMED`, the no-show sweep moves the appointment to `NO_SHOW` with `cancellation_reason` of `NO_SHOW_AUTO`, sets `refund_state` to `NON_REFUNDABLE`, and releases the slot.

Completing the session is also a counselor action. The transition from `IN_SESSION` to `COMPLETED` is permitted only when a CounselingRecord already exists for this `appointment_id` (otherwise the implicit completion gate triggers `ERR_INVALID_STATE`). On completion, `ended_at` is set to current time, and if `assessment_status` was `IN_PROGRESS` and `appointment_type` was `INTAKE`, `assessment_status` flips to `COMPLETED`.

A mid-session crisis handover transitions the appointment from `IN_SESSION` to `CANCELLED` with `cancellation_reason` set to `CRISIS_HANDOVER`. The same operation sets `refund_state` to `FULL_REFUNDED`, writes the REFUND row, and credits one session back to `package_balance_sessions` for `PACKAGE` payments. This branch is described in §3.7.

### 3.6. Counseling Records and Risk-Keyword Detection

After a session completes, the counselor writes a single counseling record for that session. The request body carries `appointment_id`, the encrypted `encrypted_note_blob` containing the session's clinical content, and an optional `crisis_acknowledged` flag whose role is described below. The platform validates that the appointment is the counselor's own and has reached `COMPLETED`, and that no record already exists for this `appointment_id` (the unique constraint surfaces a duplicate as `ERR_RECORD_ALREADY_EXISTS`). On success the record is persisted with `redaction_status` of `ACTIVE`, `retention_expires_at` of `created_at` plus seven years, and `last_accessed_at` of null.

Before the write commits, the platform runs a risk-keyword scan over the supplied note. The keyword set includes the phrases `"suicide"`, `"self-harm"`, `"kill myself"`, and `"end it"` (case-insensitive). When any keyword matches and `crisis_acknowledged` is not `true`, the platform refuses the write: it auto-creates a CrisisIncident with `detection_source` set to `KEYWORD_DETECTOR`, `status` set to `DETECTED`, `appointment_id` and `client_id` mirrored from the appointment, and surfaces the new incident's `id` in the rejection response, returning HTTP 422 with `error_id` of `ERR_CRISIS_AUTO_RAISED`. The counselor must then re-submit the same record with `crisis_acknowledged` set to `true` to commit the note.

Reading a record is permitted to its owning counselor, to the supervisors of that counselor (whose own SupervisionSession rows list them as `supervisor_id` for that counselor), and to a `PlatformAdmin`. Each authorised read refreshes `last_accessed_at` to current time and appends an `AuditLogEntry` with action `RECORD_READ`. The list endpoint accepts query filters `counselor_id`, `client_id`, `redaction_status`, `limit`, and `offset`, and never returns the encrypted blob — only metadata.

Exporting a record is permitted to the owning counselor and to a `PlatformAdmin`. The export request body MUST carry `export_consent` set to `true`; absence of the field, or a value of `false`, is rejected with `ERR_EXPORT_CONSENT_MISSING`. A successful export appends an `AuditLogEntry` with action `RECORD_EXPORT`. Export of a record whose `redaction_status` is `PURGED` is rejected with `ERR_RECORD_PURGED` and HTTP 410, exactly like a read.

### 3.7. Crisis Detection, Handover, and Follow-Up

A CrisisIncident is created either by the keyword auto-raise of §3.6 or directly by a counselor through a counselor-triggered escalation. The direct creation request carries `appointment_id`, `detection_source` (one of `KEYWORD_DETECTOR` or `COUNSELOR_TRIGGERED`), an optional `trigger_keyword` (which is required when `detection_source` is `KEYWORD_DETECTOR` — absence rejects with `ERR_TRIGGER_KEYWORD_MISSING`), and an optional initial `severity`. On creation the incident's `status` is `DETECTED`, `severity` defaults to `MEDIUM`, and `client_id` is mirrored from the appointment; an `AuditLogEntry` with action `CRISIS_DETECTED` is appended.

A `CrisisResponder` then takes ownership through the handover action, which transitions the incident from `DETECTED` to `HANDED_OVER`. The action sets `assigned_responder_id` to the responder's `X-User-ID`, sets `handover_at` to current time, sets `follow_up_due_at` to current time plus seventy-two hours, accepts the responder-set `severity` from the request body, and — if the incident's appointment is currently `IN_SESSION` — cascades to that appointment, transitioning it from `IN_SESSION` to `CANCELLED` with `cancellation_reason` of `CRISIS_HANDOVER`, setting `refund_state` to `FULL_REFUNDED`, writing the REFUND row to `SettlementLedger`, and crediting `package_balance_sessions` if the payment mode was `PACKAGE`. An `AuditLogEntry` with action `CRISIS_HANDOVER` is appended.

The post-handover path then forks on severity. When `severity` is `MEDIUM` or `HIGH`, the responder is expected to dispatch the emergency-contact notification: the action transitions the incident from `HANDED_OVER` to `EMERGENCY_NOTIFIED`, sets `emergency_notified_at` to current time, requires that the linked client's `emergency_contact_phone` be present (otherwise `ERR_NO_EMERGENCY_CONTACT`), appends an `AuditLogEntry` with action `CRISIS_NOTIFY`, and emits an external `emergency_contact_notify` event. Attempting the same notification when `severity` is `LOW` is rejected with `ERR_NOTIFY_NOT_REQUIRED` because the protocol skips emergency notification at low severity. From `EMERGENCY_NOTIFIED` the responder schedules the follow-up, transitioning the incident to `FOLLOW_UP_SCHEDULED`; the request may carry an optional `follow_up_due_at` to override the original 72-hour due time. When `severity` is `LOW`, the responder skips notification and goes directly from `HANDED_OVER` to `FOLLOW_UP_SCHEDULED`, recording `follow_up_due_at`.

The incident is closed by a resolve action that transitions from `FOLLOW_UP_SCHEDULED` to the terminal `RESOLVED`. The request body carries `follow_up_completed_at`, which must be at or before current time; the platform sets the field to the supplied value and triggers a recomputation of the linked client's `risk_flag`.

The `risk_flag` is computed by a weighted scoring rule over the last ninety days of CrisisIncident rows for the client. The relevant set comprises every incident with `created_at` within the lookback whose `status` is not yet `RESOLVED`, plus every `RESOLVED` incident whose `follow_up_completed_at` falls within the lookback. The incidents are processed oldest first (with ties broken by ascending `id`); each contributes points to a running score: a `severity` of `HIGH` contributes five points, `MEDIUM` contributes three, `LOW` contributes one, and an additional one point is added when `detection_source` is `COUNSELOR_TRIGGERED`. The final `risk_flag` is `ACUTE` when the score is at least eight, `ELEVATED` when the score is at least four (and below eight), and `NONE` otherwise. The recomputation also fires for any non-resolve crisis transition and for the periodic risk sweep.

A risk-summary endpoint exposes this score with one variant of disclosure. A client viewing their own summary, a `CrisisResponder`, and a `PlatformAdmin` see the raw score and the resulting `risk_flag`. A counselor viewing the same client receives a rounded view: the score is rounded to the nearest even integer with ties broken to even, while the underlying recompute that drives `risk_flag` continues to use the raw score. The two views may therefore disagree on the displayed integer, but the categorical `risk_flag` is identical at the threshold boundaries because the rounding does not move the score across an integer threshold.

### 3.8. Settlement Charges and the Two Payment Modes

When an appointment confirms, the platform writes a `CHARGE` row to `SettlementLedger`. The row carries `appointment_id` and `direction`, with `(appointment_id, direction)` unique across the table. The amounts on the row depend on `payment_mode`:

For `PAY_PER_SESSION`, `gross_amount_cents` equals the appointment's frozen `list_price_cents` (default 12000 cents). The tax component `tax_cents` is `gross_amount_cents` multiplied by the basis-points tax rate `TAX_BPS` of 875 divided by 10000, rounded half up. The counselor's portion `counselor_share_cents` is `gross_amount_cents` multiplied by the counselor's `revenue_share_bps` divided by 10000, rounded half up. The platform's portion `platform_share_cents` is then `gross_amount_cents` minus `counselor_share_cents`, with no further rounding.

For `PACKAGE`, the consumer has already paid for the session through the prepaid package, so the ledger's `gross_amount_cents` is zero and `tax_cents` is zero. The counselor still earns a share, however, computed against an imputed shadow rate `SHADOW_PACKAGE_RATE` of 9000 cents per session: `counselor_share_cents` equals 9000 multiplied by `revenue_share_bps` divided by 10000, rounded half up. Because there is no concurrent gross to draw from, the platform absorbs that share from prior package revenue, so `platform_share_cents` equals the negative of `counselor_share_cents`.

The same per-component rounding rule applies for refunds, with each component recorded as a negative integer on the REFUND row. The `payout_id` on every freshly written ledger row is null until that row is rolled into a payout.

### 3.9. Periodic Payouts to Counselors

A `PlatformAdmin` rolls up unrolled ledger rows into a `Payout` for a given counselor over a window. The request body carries `counselor_id`, `period_start_at`, and `period_end_at` (with `period_end_at` strictly greater than `period_start_at`); the new payout's window must not overlap any existing `PENDING` or `PAID` payout for the same counselor, otherwise `ERR_PAYOUT_WINDOW_OVERLAP`. The aggregation gathers every SettlementLedger row whose linked appointment has `counselor_id` equal to the target counselor, whose linked appointment's `ended_at` falls in the half-open range starting at `period_start_at` and ending strictly before `period_end_at`, whose `payout_id` is null, and whose linked appointment's status is one of `COMPLETED`, `NO_SHOW`, or `CANCELLED` (a `NO_SHOW` charge counts because the appointment was non-refundable). The payout's `total_counselor_share_cents` is the sum of `counselor_share_cents` across those rows (CHARGE rows positive, REFUND rows negative); `total_tax_cents` is the corresponding sum of `tax_cents`. Each contributing ledger row's `payout_id` is set to the new payout's `id` atomically with creation. A payout creation against a counselor whose `status` is `DISQUALIFIED` is rejected with `ERR_COUNSELOR_DISQUALIFIED`.

A new payout is born in `PENDING`. A `PlatformAdmin` then marks it paid, which is permitted only while it is `PENDING` and only while linked SettlementLedger rows are complete (no orphan refunds in window) and the counselor is not `DISQUALIFIED`; on success `paid_at` is set to current time and the payout becomes `PAID`. Settlement ledger rows are immutable across this transition. A paid payout may be reversed by a `PlatformAdmin` while current time is strictly less than `paid_at` plus seven days, transitioning the payout to `REVERSED`; the reverse request body carries a `reason`. Reversal does not delete the underlying ledger rows — they remain unrolled at the data layer and a new `PENDING` payout for the same window must be explicitly re-created by an admin once the underlying issue is resolved.

### 3.10. Supervision and Continuing Education

A counselor logs each supervision session by submitting a SupervisionSession row with `counselor_id` (the counselor being supervised, which the platform validates equals `X-User-ID`), `supervisor_id` (the senior counselor providing supervision), `case_appointment_id` (the appointment under discussion, which must already be `COMPLETED` and must be the supervisee's own — otherwise `ERR_INVALID_CASE`), `scheduled_at` (the supervision discussion timestamp), `duration_hours` (a number at least 0.5 and at most 4.0), and `discussion_notes` (plaintext, no PHI by policy). At creation the row's `status` is `PENDING_REVIEW` and `evaluation_score` is null.

Two referential checks gate creation. First, the supervisor's `id` must not equal the supervisee's `id`, and the supervisor's `specialty_tags` must overlap the supervisee's `specialty_tags`; otherwise `ERR_SUPERVISOR_INELIGIBLE`. Second, the platform pins a segregation-of-duties rule: the supervisor named on the row is also the only role permitted to subsequently approve it — the eventual approver's `X-User-ID` must equal `supervisor_id`. A request that attempts to create a SupervisionSession in a way that would violate this future-approval constraint (for example, listing a `supervisor_id` whose role does not entitle them to approve) is rejected with `ERR_SUPERVISION_SOD`. A supervisor cannot also be the cycle-deciding admin for any cycle whose required hours include this row — see §3.2.

A scheduling check applies on creation: the proposed supervision must not collide with another non-`REJECTED` SupervisionSession for the same `supervisor_id` whose 30-minute symmetric buffer overlaps. The buffer for both rows is the half-open interval starting at `scheduled_at` minus 30 minutes and ending strictly before `scheduled_at` plus 30 minutes; an intersection with another such buffer surfaces as `ERR_INVALID_STATE`. (Note that the supervision buffer is symmetric, in contrast to the slot rest-interval rule which only enforces the gap and not a pre-buffer.)

The supervisor approves or rejects the row. Approval is permitted only while `status` is `PENDING_REVIEW`, only when `X-User-ID` equals `supervisor_id`, and only when the request body carries an `evaluation_score` between 1 and 5 inclusive. On approval the row's `status` becomes `APPROVED`, and the counselor's `total_supervision_hours` is incremented by `duration_hours`, but only when the approval timestamp falls within the counselor's currently-open CertificationCycle window. Rejection requires `X-User-ID` equal to `supervisor_id`, sets `status` to `REJECTED`, and accumulates no hours.

Continuing-education records follow a parallel two-step pattern with a different approver. A counselor submits a ContinuingEducationRecord carrying `counselor_id`, `course_title`, `completed_at`, and `hours_claimed` (greater than zero and at most 40). At creation `status` is `PENDING_REVIEW`, `hours_credited` is zero. A `PlatformAdmin` then approves or rejects. Approval requires `status` to be `PENDING_REVIEW`, sets `hours_credited` to `hours_claimed`, and increments the counselor's `total_ce_hours` by that amount when the approval timestamp falls within the counselor's currently-open CertificationCycle window. Rejection sets `hours_credited` to zero. Approving and rejecting CE records are admin actions; approving and rejecting supervision sessions are supervisor actions — the actor split is deliberate.

### 3.11. Audit Log and System-Driven Sweeps

The audit log is a read-only catalogue of platform-significant events that a `PlatformAdmin` may filter by `action`, `target_entity`, `actor_role`, `from`, `to`, and the usual pagination parameters. Each entry records the `actor_role` of the requester, the `actor_user_id` mirrored from `X-User-ID`, the `action` from the catalogue, the `target_entity` and `target_id` of the affected resource, and a small JSON `payload_summary` carrying action-specific metadata that excludes PHI and references ciphertext only.

Five system-driven sweeps run on demand; each is exposed as an admin-only test-driving capability so that automated tests can exercise time-gated transitions deterministically. The hold-expiry sweep transitions every `HELD` slot whose `held_until` has elapsed back to `OPEN` and cancels its linked appointment. The no-show sweep transitions every `CONFIRMED` appointment past `start_at` plus thirty minutes to `NO_SHOW`. The recertification sweep transitions every cycle past its window deadline (or fourteen days past for `UNDER_REVIEW`) to `EXPIRED`, cascading the counselor's status. The retention sweep transitions every `ACTIVE` CounselingRecord past `retention_expires_at` to `PURGED`. The risk sweep recomputes `risk_flag` for clients with non-`RESOLVED` incidents in the lookback. A separate admin-only test-driving capability advances the simulated clock to a supplied `to` instant, which must be strictly greater than current internal time. An additional event-emission endpoint accepts an `event_type` and a `payload` to acknowledge external IM, payment, and emergency-contact synchronisation, appending an `AuditLogEntry` for the external sync.

## 4. Endpoint Definitions

Operations that create a brand-new resource — a counselor, a client, an availability slot, an appointment, a counseling record, a crisis incident, a supervision session, a CE record, a payout, or an auto-created next certification cycle — return HTTP 201. Operations that modify an existing resource return HTTP 200. The only exception is slot deletion, which returns HTTP 204 with no body.

| Method | Path                                                              | Description                                                              | Authorized Role(s)                                       |
| ------ | ----------------------------------------------------------------- | ------------------------------------------------------------------------ | -------------------------------------------------------- |
| POST   | `/counseling/counselors`                                          | Register a counselor; auto-creates first certification cycle             | PlatformAdmin                                            |
| GET    | `/counseling/counselors`                                          | Public catalogue browse with specialty/channel/timezone filters          | Public, Client, Counselor, Supervisor, PlatformAdmin     |
| GET    | `/counseling/counselors/{id}`                                     | Counselor detail                                                         | Public, Client, Counselor, Supervisor, PlatformAdmin     |
| PATCH  | `/counseling/counselors/{id}`                                     | Update counselor profile                                                 | Counselor, PlatformAdmin                                 |
| POST   | `/counseling/counselors/{id}/disqualify`                          | Disqualify a counselor                                                   | PlatformAdmin                                            |
| POST   | `/counseling/clients`                                             | Register a client                                                        | PlatformAdmin                                            |
| GET    | `/counseling/clients/{id}`                                        | Client detail                                                            | Client, Counselor, CrisisResponder, PlatformAdmin        |
| PATCH  | `/counseling/clients/{id}`                                        | Update client profile                                                    | Client, PlatformAdmin                                    |
| POST   | `/counseling/clients/{id}/credit-package`                         | Credit prepaid package sessions                                          | PlatformAdmin                                            |
| GET    | `/counseling/clients/{id}/risk-summary`                           | Computed risk summary; counselor sees rounded view                       | Client, Counselor, CrisisResponder, PlatformAdmin        |
| POST   | `/counseling/counselors/{id}/certification-cycles`                | Create a new OPEN certification cycle                                    | PlatformAdmin                                            |
| POST   | `/counseling/certification-cycles/{id}/submit`                    | Counselor submits cycle for review                                       | Counselor                                                |
| POST   | `/counseling/certification-cycles/{id}/approve`                   | Admin approves cycle                                                     | PlatformAdmin                                            |
| POST   | `/counseling/certification-cycles/{id}/reject`                    | Admin rejects cycle                                                      | PlatformAdmin                                            |
| GET    | `/counseling/certification-cycles`                                | List cycles                                                              | Counselor, PlatformAdmin                                 |
| POST   | `/counseling/availability-slots`                                  | Create an availability slot                                              | Counselor                                                |
| GET    | `/counseling/availability-slots`                                  | List slots                                                               | Public, Client, Counselor, PlatformAdmin                 |
| DELETE | `/counseling/availability-slots/{id}`                             | Release an OPEN slot                                                     | Counselor                                                |
| POST   | `/counseling/appointments`                                        | Create appointment in HOLD; locks slot                                   | Client                                                   |
| POST   | `/counseling/appointments/{id}/confirm`                           | Confirm an appointment within hold window                                | Client                                                   |
| GET    | `/counseling/appointments/{id}/refund-estimate`                   | Forward-looking refund estimate (strict >)                               | Client, Counselor, PlatformAdmin                         |
| POST   | `/counseling/appointments/{id}/cancel`                            | Cancel an appointment (HOLD or CONFIRMED)                                | Client, Counselor, PlatformAdmin                         |
| POST   | `/counseling/appointments/{id}/reschedule`                        | Reschedule a confirmed appointment to a new slot                         | Client, Counselor                                        |
| POST   | `/counseling/appointments/{id}/start`                             | Counselor starts the session                                             | Counselor                                                |
| POST   | `/counseling/appointments/{id}/complete`                          | Counselor completes the session                                          | Counselor                                                |
| GET    | `/counseling/appointments`                                        | List appointments                                                        | Client, Counselor, PlatformAdmin                         |
| GET    | `/counseling/appointments/{id}`                                   | Get appointment detail                                                   | Client, Counselor, PlatformAdmin                         |
| POST   | `/counseling/counseling-records`                                  | Create encrypted record after session completion                         | Counselor                                                |
| GET    | `/counseling/counseling-records/{id}`                             | Read a record                                                            | Counselor, Supervisor, PlatformAdmin                     |
| POST   | `/counseling/counseling-records/{id}/export`                      | Authorised export with consent                                           | Counselor, PlatformAdmin                                 |
| GET    | `/counseling/counseling-records`                                  | List records (metadata only)                                             | Counselor, Supervisor, PlatformAdmin                     |
| POST   | `/counseling/crisis-incidents`                                    | Counselor-triggered escalation                                           | Counselor                                                |
| POST   | `/counseling/crisis-incidents/{id}/handover`                      | Crisis-response team takes ownership                                     | CrisisResponder                                          |
| POST   | `/counseling/crisis-incidents/{id}/notify-emergency`              | Dispatch emergency-contact notification                                  | CrisisResponder                                          |
| POST   | `/counseling/crisis-incidents/{id}/schedule-follow-up`            | Set follow-up due date                                                   | CrisisResponder                                          |
| POST   | `/counseling/crisis-incidents/{id}/resolve`                       | Mark incident resolved                                                   | CrisisResponder                                          |
| GET    | `/counseling/crisis-incidents`                                    | List incidents                                                           | Counselor, CrisisResponder, PlatformAdmin                |
| POST   | `/counseling/supervision-sessions`                                | Counselor logs a supervision session                                     | Counselor                                                |
| POST   | `/counseling/supervision-sessions/{id}/approve`                   | Supervisor approves session                                              | Supervisor                                               |
| POST   | `/counseling/supervision-sessions/{id}/reject`                    | Supervisor rejects session                                               | Supervisor                                               |
| GET    | `/counseling/supervision-sessions`                                | List supervision sessions                                                | Counselor, Supervisor, PlatformAdmin                     |
| POST   | `/counseling/ce-records`                                          | Counselor logs a continuing-education record                             | Counselor                                                |
| POST   | `/counseling/ce-records/{id}/approve`                             | Admin approves CE record                                                 | PlatformAdmin                                            |
| POST   | `/counseling/ce-records/{id}/reject`                              | Admin rejects CE record                                                  | PlatformAdmin                                            |
| GET    | `/counseling/settlement-ledger`                                   | List settlement-ledger entries                                           | Counselor, PlatformAdmin                                 |
| POST   | `/counseling/payouts`                                             | Roll up unrolled ledger rows for a counselor in a window                 | PlatformAdmin                                            |
| POST   | `/counseling/payouts/{id}/mark-paid`                              | Mark a payout PAID                                                       | PlatformAdmin                                            |
| POST   | `/counseling/payouts/{id}/reverse`                                | Reverse a paid payout within seven days                                  | PlatformAdmin                                            |
| GET    | `/counseling/payouts`                                             | List payouts                                                             | Counselor, PlatformAdmin                                 |
| GET    | `/counseling/audit-log`                                           | List audit-log entries                                                   | PlatformAdmin                                            |
| POST   | `/counseling/_clock/advance`                                      | Advance the simulated clock to a target instant                          | PlatformAdmin                                            |
| POST   | `/counseling/_sweep/holds`                                        | Run the hold-expiry sweep                                                | PlatformAdmin                                            |
| POST   | `/counseling/_sweep/no-show`                                      | Run the no-show sweep                                                    | PlatformAdmin                                            |
| POST   | `/counseling/_sweep/recert`                                       | Run the recertification sweep                                            | PlatformAdmin                                            |
| POST   | `/counseling/_sweep/retention`                                    | Run the retention sweep                                                  | PlatformAdmin                                            |
| POST   | `/counseling/_sweep/risk`                                         | Recompute client risk flags                                              | PlatformAdmin                                            |
| POST   | `/counseling/_events/emit`                                        | Synthetic external event for IM/payment/emergency-contact sync           | PlatformAdmin                                            |

## 5. Error Code Catalogue

| Error ID                          | HTTP Status |
| --------------------------------- | ----------- |
| `ERR_AUTH_MISSING`                | 401         |
| `ERR_FORBIDDEN`                   | 403         |
| `ERR_NOT_FOUND`                   | 404         |
| `ERR_REF_NOT_FOUND`               | 422         |
| `ERR_INVALID_STATE`               | 409         |
| `ERR_COUNSELOR_NOT_ACTIVE`        | 409         |
| `ERR_COUNSELOR_DISQUALIFIED`      | 409         |
| `ERR_CRISIS_AUTO_RAISED`          | 422         |
| `ERR_NO_EMERGENCY_CONTACT`        | 422         |
| `ERR_INTAKE_REQUIRED`             | 422         |
| `ERR_INTAKE_ALREADY_IN_PROGRESS`  | 422         |
| `ERR_CHANNEL_NOT_SUPPORTED`       | 422         |
| `ERR_INVALID_SLOT_DURATION`       | 422         |
| `ERR_SLOT_OVERLAP`                | 422         |
| `ERR_REST_INTERVAL`               | 422         |
| `ERR_DAILY_CAP_EXCEEDED`          | 422         |
| `ERR_WEEKLY_CAP_EXCEEDED`         | 422         |
| `ERR_BOOKING_TOO_LATE`            | 422         |
| `ERR_RESCHEDULE_WINDOW_CLOSED`    | 409         |
| `ERR_HOLD_EXPIRED`                | 409         |
| `ERR_INSUFFICIENT_PACKAGE_BALANCE`| 422         |
| `ERR_PRICE_DRIFT`                 | 422         |
| `ERR_SUPERVISOR_INELIGIBLE`       | 422         |
| `ERR_SUPERVISION_SOD`             | 422         |
| `ERR_INVALID_CASE`                | 422         |
| `ERR_RECERT_SOD`                  | 403         |
| `ERR_TRIGGER_KEYWORD_MISSING`     | 422         |
| `ERR_NOTIFY_NOT_REQUIRED`         | 422         |
| `ERR_EXPORT_CONSENT_MISSING`      | 422         |
| `ERR_RECORD_PURGED`               | 410         |
| `ERR_PAYOUT_WINDOW_OVERLAP`       | 409         |
| `ERR_PAGINATION_INVALID`          | 422         |
| `ERR_RECORD_ALREADY_EXISTS`       | 409         |
| `ERR_SLOT_TAKEN`                  | 409         |
| `ERR_VERSION_CONFLICT`            | 409         |
| `ERR_VALIDATION`                  | 422         |
