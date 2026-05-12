# Legal Case Management API — Product Requirements Document

## 1. Introduction

Law firms operate at the intersection of strict procedural compliance and the messy realities of multi-party disputes. A single matter accumulates an evolving roster of parties, a shifting library of draft pleadings, court-issued hearing dates that may collide with another partner's calendar, evidence that must be traceable from collection to courtroom, time logged by lawyers at different ranks and rates, and ultimately a bill that must reconcile court-imposed fees with the firm's chosen attorney-fee model. When any of these threads is mishandled — a draft signed off by its own author, an evidence chain broken by an out-of-order custody event, a hearing scheduled while a partner is already in another courtroom — the consequences ripple through every other thread. Manual coordination scales poorly and produces inconsistent records.

This document specifies the **Legal Case Management API**, a service that unifies case registration, party management with multi-role binding, template-driven document drafting with multi-level review, hearing scheduling with cross-case lawyer conflict detection, evidence and chain-of-custody tracking, lawyer time billing under three pricing modes, and event-driven synchronization with external court-filing, payment, and electronic-signature systems. The API enforces conflict-of-interest at intake, segregation of duties across the document review lifecycle, deterministic court-fee tiering, and a chronological settlement reconstruction at case close. All of this is offered to PartnerLawyer, SeniorLawyer, JuniorLawyer, IntakeClerk, and SystemIntegrator clients through a single REST surface mounted under `/cases` and its sibling paths described in §4.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must arrive with two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming that principal's role. Both headers are mandatory; if either is missing, the request is rejected with `ERR_AUTH_REQUIRED` (HTTP 401). When the headers are present but the supplied role is not authorized for the requested endpoint per the matrix in §4, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

Five roles exist:

- **`PartnerLawyer`** — partner-rank lawyer (the underlying `Lawyer.role` is `PARTNER`); the sole role for partner-signoff, draft locking, bill voiding, settlement marking, evidence exclusion, rebuttal upholding, case activation, hold, resume, close, lawyer registration (including assignment of `full_name`, `bar_number`, `role`, and `hourly_rate_cents`), template registration, bill creation, bill issuance, time-entry write-off, and audit-log access.
- **`SeniorLawyer`** — senior-rank lawyer (the underlying `Lawyer.role` is `SENIOR`) authorized to pass review and request revisions, but not to partner-signoff.
- **`JuniorLawyer`** — junior-rank lawyer (the underlying `Lawyer.role` is `JUNIOR`) authorized to draft, log time, collect evidence, and file rebuttals, but not to review or approve.
- **`IntakeClerk`** — non-lawyer staff handling case intake, party administration, identity verification, and hearing scheduling.
- **`SystemIntegrator`** — external-system role used by court-filing, payment, and signature integrations, plus the clock-advance and sweep test-driving endpoints.

When `X-User-Role` is `PartnerLawyer`, `SeniorLawyer`, or `JuniorLawyer`, the value of `X-User-ID` is the `id` of the acting `Lawyer` row; ownership and segregation-of-duties checks on any resource that references a `Lawyer` (such as `lead_lawyer_id`, `drafter_lawyer_id`, `senior_reviewer_lawyer_id`, `partner_signoff_lawyer_id`, `collected_by_lawyer_id`, `actor_lawyer_id`, `filed_by_lawyer_id`, or `lawyer_id`) compare those foreign-key fields to `X-User-ID`. When `X-User-Role` is `IntakeClerk` or `SystemIntegrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it on `AuditLog.actor_id` for audited mutations, but does not compare it to any entity's `id`.

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

### 2.3. Pagination

List endpoints accept two query parameters: `limit` and `offset`. The default `limit` is 10, the minimum is 1, and the maximum is 100; values outside that range are rejected as input validation errors. The default `offset` is 0. Results are sorted by `created_at` ascending unless an endpoint's documentation specifies otherwise. The list envelope's `meta` block carries `limit`, `offset`, `total_count` (the total number of matching rows before the limit/offset window is applied), and `has_more` (true when more rows remain past the current window).

### 2.4. Common Resource Properties and Identifiers

Every persisted entity carries an `id` that is a server-minted UUID; identifiers are opaque strings without a type prefix and are immutable for the life of the row. All entities also carry `created_at`, an ISO 8601 UTC timestamp with three fractional digits set when the row is first persisted.

Entities flagged as carrying common fields — `Lawyer`, `Case`, `Party`, `DocumentTemplate`, `DocumentDraft`, `Hearing`, `Evidence`, `TimeEntry`, and `Bill` — additionally carry `updated_at` (an ISO 8601 UTC timestamp with three fractional digits, refreshed on every server-side mutation of the row) and `version` (an integer that starts at 1 on creation and is incremented by exactly one on every mutation, including system-driven mutations such as posture recomputation or status cascades). The history-style child rows `CustodyEvent`, `EvidenceRebuttal`, and the immutable record `AuditLog` are append-only logs that carry only `id` and `created_at`; both `updated_at` and `version` are absent from those responses and they are never the target of an OCC check.

The `Case.case_number` is server-assigned at registration and never thereafter mutated; the `Case.intake_document_id` carries the same immutability — it must be supplied at intake and may not change once the case has transitioned out of `INTAKE`.

### 2.5. Optimistic Concurrency Control

Mutating endpoints accept an optional `version` field in the request body. When present, the server compares it to the row's stored `version` and, on mismatch, rejects the request with `ERR_VERSION_MISMATCH` (HTTP 409). When absent, the OCC check is skipped and the mutation proceeds against whatever row is current. Successful mutations increment the affected row's `version` by one and refresh its `updated_at`. Cascaded mutations — for example, the SCHEDULED hearings cancelled when a case enters hold, or the SIGNED_OFF drafts locked when a case enters AWAITING_SETTLEMENT — likewise increment those rows' `version` and refresh their `updated_at`.

### 2.6. Validation Priority and Header Pre-Checks

Every request runs through a fixed validation ladder. Authentication header presence is checked first (priority 1, `ERR_AUTH_REQUIRED`); next the role's permission to call the endpoint (priority 2, `ERR_FORBIDDEN`); then the existence of every path-segment id, resolved left-to-right so that an unknown `caseId` in `/cases/{caseId}/parties` surfaces before an unknown party context (priority 3, `ERR_NOT_FOUND`); then the existence of every foreign key in the request body (priority 4, `ERR_REFERENCED_NOT_FOUND`).

Beyond those four universal checks, each business endpoint runs domain-specific checks in priority order. At case registration, the conflict-of-interest checks (priorities 5 and 6, both surfacing `ERR_CONFLICT_OF_INTEREST`) run before any other body validation; the lead-lawyer client-history check is evaluated first, and only when it passes does the system check that the client and opposing identity hashes are not identical. State-transition validity (priority 7, `ERR_INVALID_STATE`) is checked before any sub-resource side effects fire, and the archival guard (priority 8, `ERR_CASE_ARCHIVED`) wraps every mutation against a case-scoped sub-resource so that an archived case cannot be touched even if the immediate target is in a transitionable state. Segregation of duties (priority 9, `ERR_SEGREGATION_OF_DUTIES`) and custody-chain integrity (priority 10, `ERR_CUSTODY_CHAIN_BROKEN`) precede the temporal and constraint checks they share endpoints with. The remaining priorities cover hearing temporal sanity (11, 12), hearing capacity (13, 14), party verification (15), posture gating (16), template/case-type matching (17), reviewer rank (18), bill-mode validity (19), time-entry adjustment math (20), claim-amount sanity (21), and external event payload sanity (22, 23). When two checks would both fail on the same request, the lower-numbered priority wins and its `error_id` is returned.

### 2.7. Hearing Capacity, Court Rooms, and the Travel Buffer

Hearing scheduling is the system's most heavily contested resource because two independent capacities must be respected on every creation and reschedule. **Court-room capacity** is governed by half-open intervals: two SCHEDULED hearings sharing the same `court_room` may not have overlapping `[scheduled_start, scheduled_end)` windows, but a hearing whose `scheduled_start` equals the previous hearing's `scheduled_end` is allowed (touching does not overlap). Violations surface `ERR_HEARING_ROOM_CONFLICT`. **Lead-lawyer capacity** is stricter: two SCHEDULED hearings that share the same `lead_lawyer_id` — even across different cases and different rooms — must be separated by a 30-minute travel buffer, so the next hearing's `scheduled_start` must be greater than or equal to the previous hearing's `scheduled_end` plus 30 minutes. Violations surface `ERR_LAWYER_SCHEDULE_CONFLICT`. The lawyer-side check is cross-case: two clerks scheduling the same partner into back-to-back rooms in two unrelated matters will collide.

### 2.8. Case Posture as a Cross-Cutting Gate

Every case carries a derived `posture` flag — `OPEN`, `RESTRICTED`, or `FROZEN` — that is recomputed automatically on every Evidence, Hearing, and EvidenceRebuttal mutation that touches the case, and that is never directly settable. The posture is determined in priority order: if the case has any `Evidence` row whose `status` is `REBUTTED`, the posture is `RESTRICTED`; otherwise, if the case has any `Hearing` whose `status` is `SCHEDULED` and whose `scheduled_start` lies in the interval starting at the current server time and ending strictly less than 24 hours after it, the posture is `RESTRICTED`; otherwise, if `Case.status` is `ON_HOLD`, the posture is `FROZEN`; otherwise, the posture is `OPEN`. A `FROZEN` posture forbids creating new `TimeEntry`, `Evidence`, `Hearing`, or `DocumentDraft` rows on the case, and any such attempt is rejected with `ERR_CASE_POSTURE_FROZEN`.

### 2.9. Cascades and Hierarchical Consistency

Mutations frequently cascade. When a case transitions from `ACTIVE` to `ON_HOLD`, every `Hearing` row on the case whose `status` is `SCHEDULED` is moved to `CANCELLED` and the case posture is recomputed; the cascade increments each affected hearing's `version` and refreshes its `updated_at`. When a case transitions from `ACTIVE` to `AWAITING_SETTLEMENT`, every `DocumentDraft` on the case whose `status` is `SIGNED_OFF` is moved to `LOCKED`. When a case transitions from `AWAITING_SETTLEMENT` to `CLOSED`, the system stamps `closed_at`, computes `settlement_total_cents`, transitions every `EvidenceRebuttal` whose `status` is `OPEN` to `DISMISSED`, and retires every `DocumentDraft` whose `status` is in `DRAFTING`, `IN_REVIEW`, or `REVISING` to `RETIRED`. After a case has been closed for at least 30 days — measured against the server's logical clock, which advances either by real time or by the test-driving capability — the case is auto-transitioned to `ARCHIVED`. Once a case is `ARCHIVED`, every mutation against the case or any of its sub-resources is rejected with `ERR_CASE_ARCHIVED`, regardless of the immediate sub-resource's own state.

### 2.10. Audit, Precision, and Currency Handling

Document and evidence flows are audited. A small set of mutations — draft creation, review submission, senior pass, review rejection, partner signoff, lock, retirement, custody append, evidence collection, evidence submission, evidence exclusion, evidence rebuttal, and external court filing — append a row to the audit log. Each audit row records `subject_type` (one of `DOCUMENT_DRAFT`, `EVIDENCE`, or `CUSTODY_EVENT`), `subject_id`, `actor_role`, `actor_id`, `action` (a verb such as `DRAFT_CREATED`, `REVIEW_PASSED`, `EVIDENCE_SUBMITTED`), `payload_snapshot` (a compact JSON snapshot of pre/post values for the change), and `occurred_at` (a server-assigned UTC timestamp). The audit log is append-only and queryable only by a partner.

All monetary fields are integer cents — `claim_amount_cents`, `hourly_rate_cents`, `hourly_rate_cents_pinned`, `fixed_fee_cents`, `recovered_amount_cents`, `expense_reimbursement_cents`, `cost_recovery_cents`, `court_fee_cents`, `attorney_fee_cents`, `total_due_cents`, and `settlement_total_cents`. Wherever a calculation produces a fractional cent, the result is rounded half-up (a value whose fractional part is exactly 0.5 rounds away from zero). Cents are never stored or returned as decimal values; the rounding policy applies only at the documented per-step rounding points described in §3.

## 3. Business Logic & Workflows

### 3.1. Case Registration, Conflict-of-Interest, and Activation

A case begins life when an `IntakeClerk` or `PartnerLawyer` submits a registration payload containing `case_type`, `title`, `claim_amount_cents`, `lead_lawyer_id`, `client_identity_hash`, `opposing_identity_hash`, and `intake_document_id`. The `case_type` value must be one of `CIVIL`, `CRIMINAL`, `ADMINISTRATIVE`, or `ARBITRATION`; this single classification governs which template library the case can draw from later, which court-fee schedule applies at billing, and which prep-task variant a hearing inherits. The `claim_amount_cents` must be 0 for `CRIMINAL` and `ADMINISTRATIVE` matters (where there is no monetary dispute) and must be strictly greater than 0 for `CIVIL` and `ARBITRATION` matters; a violation is rejected with `ERR_CLAIM_AMOUNT_INVALID`.

Before the case row is persisted, two conflict-of-interest checks run, in this order. First, the system inspects the lead lawyer's `client_history` array — every entry there is a hash of a client the lawyer has previously represented — and rejects the request with `ERR_CONFLICT_OF_INTEREST` if the case's `opposing_identity_hash` appears in that array. Only when that check passes does the system run the secondary check, rejecting with the same `ERR_CONFLICT_OF_INTEREST` if `client_identity_hash` and `opposing_identity_hash` are equal (a defensive check against the client and the opposing party being the same identity). The lead lawyer must also reference a `Lawyer` row whose `status` is `ACTIVE`; a `Lawyer` whose `status` is `SUSPENDED` cannot be assigned, and a newly registered `Lawyer` defaults to `status` `ACTIVE`. On success, the system mints a `case_number` of the form `<YEAR>-<TYPE_CODE>-<SEQ6>`: `YEAR` is the current UTC year, `TYPE_CODE` is `CIV` for `CIVIL`, `CRM` for `CRIMINAL`, `ADM` for `ADMINISTRATIVE`, and `ARB` for `ARBITRATION`, and `SEQ6` is a zero-padded six-digit sequence number that starts at `000001` for each `(YEAR, TYPE_CODE)` pair and increases by exactly one for each subsequent registration in that pair. Concurrent inserts in the same `(YEAR, TYPE_CODE)` partition serialize so the sequence is gap-free; an example assignment for the third civil case of 2026 is `2026-CIV-000003`. The new case enters status `INTAKE` with posture `OPEN`, and the supplied `intake_document_id` becomes immutable from this moment forward.

Activation of an `INTAKE` case to `ACTIVE` is a partner-only action. Activation requires that the case has at least one `Party` whose `party_role` is `PLAINTIFF`, at least one `Party` whose `party_role` is `DEFENDANT`, that `lead_lawyer_id` still references an `ACTIVE` `Lawyer`, and that the conflict-of-interest check recorded at registration remains satisfied; failure to meet any precondition surfaces `ERR_INVALID_STATE`. Activation recomputes the case posture as a side effect. From `ACTIVE`, a partner may move the case to `ON_HOLD` (cancelling every `SCHEDULED` hearing on the case as a cascade, then recomputing posture) provided the current posture is `OPEN` or `RESTRICTED`; a `FROZEN` posture cannot itself be the source of a hold transition because an already-on-hold case carries `FROZEN`. From `ON_HOLD`, the same partner role may resume the case to `ACTIVE`, which simply re-evaluates the posture. Once the lead lawyer judges the matter ripe, the case may move from `ACTIVE` to `AWAITING_SETTLEMENT` provided the posture is `OPEN` and every `Hearing` on the case has already settled into either `COMPLETED` or `CANCELLED`; this transition cascades to lock every `SIGNED_OFF` `DocumentDraft` on the case. Finally, a partner closes the case from `AWAITING_SETTLEMENT` to `CLOSED` only when exactly one `Bill` exists for the case with `status` in `PAID` or `SETTLED` and every `Evidence` row has `status` in `SUBMITTED`, `EXCLUDED`, or `REBUTTED`; closing stamps `closed_at`, computes `settlement_total_cents` chronologically (see §3.6), retires every non-terminal draft, and dismisses every open rebuttal.

### 3.2. Parties, Multi-Role Binding, and Identity Verification

Once a case exists, an intake clerk, a senior, or a partner adds parties to it via a payload carrying `party_role`, `full_name`, `id_document_number`, `contact_email`, `contact_phone`, optionally `agency_lawyer_id` when the party retains representation, and optionally `access_level`. The `party_role` is one of `PLAINTIFF`, `DEFENDANT`, `THIRD_PARTY`, or `WITNESS`; the same natural person may be bound to multiple cases under different `party_role` values, so multi-role binding is achieved through multiple `Party` rows rather than a list of roles on a single row. The `contact_email` must satisfy the standard RFC 5322 simple-address shape, and `contact_phone` must be between 7 and 20 characters inclusive. The `access_level` defaults to `STANDARD` and may be `STANDARD`, `RESTRICTED`, or `NONE`, controlling what case data the party itself may read.

A newly created party always has `identity_verified` equal to false. An intake clerk or partner verifies a party's identity in a separate operation that flips `identity_verified` to true; this verification is a precondition for two later actions: a party may not appear inside a `DocumentDraft.variable_overrides` map, and a party may not be cited as a hearing witness, until they are verified, with the rejection surfacing `ERR_PARTY_NOT_VERIFIED`. The `agency_lawyer_id` is optional and, when supplied, simply records which lawyer represents the party; it does not by itself confer any access on that lawyer.

### 3.3. The Document-Drafting Cycle

Document drafting is the system's most state-rich workflow because it is deliberately cyclic: a draft can return from `REVISING` to `DRAFTING`, can pass through senior review back to `DRAFTING` for partner-signoff submission, and only after a partner signs off does it move forward to `LOCKED`.

Templates are registered ahead of time by partners with a payload carrying `template_code` (a stable globally unique code such as `"CIV-COMPLAINT-V3"`), `case_type`, `name`, `variables` (an array of variable names like `"{{case_number}}"` and `"{{plaintiff_name}}"` that will be auto-filled when a draft is rendered), and `body_template` (the template text itself with `{{variable}}` placeholders). A template's own `status` is `ACTIVE` by default and may transition to `RETIRED`. A draft is created against a single template by supplying `case_id`, `template_id`, `drafter_lawyer_id`, and an optional `variable_overrides` object that maps variable names to override values. The template's `case_type` must equal the case's `case_type`; otherwise the draft is rejected with `ERR_TEMPLATE_CASE_TYPE_MISMATCH`. On creation, the system pins the template's current `version` into the draft's `template_version_pinned` field (so that any subsequent template edit cannot alter the rendered output), assigns a per-`(case_id, template_id)` sequential `version_number` starting at 1, and produces `rendered_body` by substituting each variable from the case, parties, and the supplied overrides.

A draft moves through `DRAFTING → IN_REVIEW → REVISING → DRAFTING → IN_REVIEW → SIGNED_OFF → LOCKED`, possibly with multiple cycles back to `DRAFTING`. The drafter submits for review, transitioning the draft from `DRAFTING` to `IN_REVIEW`; this requires the underlying case to be in `ACTIVE` status and `rendered_body` to be non-empty. From `IN_REVIEW`, three forward branches exist, each gated by the acting lawyer's identity. A senior may **request revisions**, returning the draft to `REVISING` and stamping the next iteration's `version_number`; the acting `Lawyer.role` must be `SENIOR` or `PARTNER` and must not be the `drafter_lawyer_id`. A senior may instead **pass review**, returning the draft to `DRAFTING` and recording the acting lawyer's id in `senior_reviewer_lawyer_id` so that the next round can advance to partner signoff; the same rank requirement and the same not-the-drafter rule apply. From `REVISING`, only the original drafter may **resume drafting**, which moves the draft back to `DRAFTING`; the acting `X-User-ID` must equal `drafter_lawyer_id`. **Partner signoff** moves the draft from `IN_REVIEW` to `SIGNED_OFF`; it requires the acting `Lawyer.role` to be exactly `PARTNER`, the acting lawyer to not be the drafter, and `senior_reviewer_lawyer_id` to be set (so that a senior pass occurred at some point in the draft's history). On signoff, the system records `partner_signoff_lawyer_id` and stamps `signed_off_at`. From `SIGNED_OFF`, a partner may **lock** the draft, transitioning it to `LOCKED`; locking re-verifies that `template_version_pinned` is still set, after which any further mutation against the draft is rejected with `ERR_DRAFT_LOCKED`.

The reviewer-rank rule and the segregation-of-duties rule apply across four endpoints — request revisions, senior pass, partner signoff, and lock. In all four, an attempt by the drafter against their own draft surfaces `ERR_SEGREGATION_OF_DUTIES`. The rank check surfaces `ERR_REVIEWER_RANK_INSUFFICIENT` when a junior attempts senior pass or request revisions, or when a senior attempts partner signoff. The `ERR_DRAFT_LOCKED` code applies to attempted mutation of an already-`LOCKED` draft.

When the parent case closes while a draft is non-terminal, the draft is auto-retired: any draft in `DRAFTING`, `IN_REVIEW`, or `REVISING` transitions to `RETIRED` via a system actor, with a `RETIRED_BY_CASE_CLOSE` audit row. Two simultaneous partner-signoff attempts on the same `IN_REVIEW` draft serialize so that exactly one wins; the loser observes the draft as no longer `IN_REVIEW` and is rejected with `ERR_INVALID_STATE`. The same outcome applies when a senior pass races a request-for-revisions on the same draft.

### 3.4. Hearing Scheduling, Conflicts, and Prep-Task Generation

Hearings are scheduled by a partner, a senior, or an intake clerk by submitting `case_id`, `court_room`, `scheduled_start`, and `scheduled_end`. Both timestamps are ISO 8601 UTC; `scheduled_end` must be strictly greater than `scheduled_start` (rejected as `ERR_HEARING_INVALID_INTERVAL`), and `scheduled_start` must be strictly greater than the current server time (rejected as `ERR_HEARING_PAST_TIME`). At scheduling, the new hearing's `lead_lawyer_id` is copied from the case's `lead_lawyer_id` and is then pinned for the lifetime of that hearing row — even if the case's lead lawyer changes later, the pinned value defines the conflict scope for this hearing.

Two capacity checks then run, as described in §2.7: a court-room overlap check (half-open intervals must not overlap, but touching is allowed) and a lead-lawyer overlap check (cross-case, with a 30-minute travel buffer). Either failure surfaces the corresponding `ERR_HEARING_ROOM_CONFLICT` or `ERR_LAWYER_SCHEDULE_CONFLICT`. Two clerks who race to schedule the same room into the same window will see the second receive `ERR_HEARING_ROOM_CONFLICT`; two clerks who race to schedule the same lawyer into different rooms with overlapping windows will see the second receive `ERR_LAWYER_SCHEDULE_CONFLICT`.

On successful scheduling, the system generates a deterministic prep-task checklist as a side effect and sets `prep_tasks_generated` to true. The checklist always begins with a confirmation task for `court_room` and arrival time, then a briefing task for every `Party` whose `party_role` is `PLAINTIFF` or `DEFENDANT`. The next item depends on `case_type`: for `CIVIL`, prepare the civil witness list; for `CRIMINAL`, coordinate with prosecution discovery; for `ADMINISTRATIVE`, file the administrative-law brief; for `ARBITRATION`, confirm arbitrator panel composition. The checklist closes with a re-verification task for the count of `Evidence` rows on the case whose `status` is `SUBMITTED` at scheduling time. Reading the prep-task checklist returns the same deterministic list. If a hearing is later rescheduled, the prep tasks are regenerated against the new hearing.

A scheduled hearing may transition to `RESCHEDULED` (the partner or senior supplies a new room and window; the original hearing's `status` becomes `RESCHEDULED` while a new hearing row with `status` `SCHEDULED` is created and its `previous_hearing_id` points at the original), to `CANCELLED` (either by explicit action or as a cascade when the case enters hold), or to `COMPLETED` (after the server's logical clock has advanced to or past the hearing's `scheduled_end`, and the parent case is in `ACTIVE` or `AWAITING_SETTLEMENT`). Each terminal transition recomputes the case posture; a cascade-cancelled hearing is handled by the system actor rather than by an explicit user. The reschedule action re-runs both capacity checks against the new window and refuses to create the replacement if either fails. The `previous_hearing_id` field is set only on a `RESCHEDULED` hearing; for the initial scheduling and for a non-replacement creation, it is null.

### 3.5. Evidence, Chain of Custody, and Rebuttal Cycles

Evidence collection begins when a partner, senior, or junior lawyer records a new piece of evidence on a case with `evidence_type` (one of `DOCUMENTARY`, `PHYSICAL`, `DIGITAL`, or `TESTIMONIAL`), `collected_at`, `collected_by_lawyer_id`, and an optional `case_fact_refs` array of free-form case-fact identifiers the evidence supports. On creation, the system auto-appends an initial `CustodyEvent` whose `action` is `COLLECTED`, whose `actor_lawyer_id` is the supplied `collected_by_lawyer_id`, and whose `occurred_at` equals `collected_at`. The `Evidence.status` is `COLLECTED` initially; `submitted_at` is null and `rebuttal_count` is 0.

Subsequent custody events are appended to track movement of the physical or digital artifact. Each event carries `actor_lawyer_id`, `action` (one of `COLLECTED`, `TRANSFERRED`, `EXAMINED`, `SUBMITTED`, or `RETURNED`), `occurred_at`, and `location`. The custody chain integrity rule is strict: every new event's `occurred_at` must be strictly greater than the most recent event's `occurred_at` for the same evidence — equality is forbidden, not merely uncommon. A violation surfaces `ERR_CUSTODY_CHAIN_BROKEN`. Two lawyers who race to append a custody event with the same `occurred_at` will see the second rejected for the same reason; the rule serves both as a per-request validator and as the serialization point for concurrent appends.

Submission of evidence to the court is a senior- or partner-only action. Submission requires the parent case to be in `ACTIVE` status, the case posture to be `OPEN` or `RESTRICTED` (a `FROZEN` posture forbids submission), the custody chain to be unbroken (every prior `CustodyEvent.occurred_at` strictly increasing and the most recent `action` not equal to `RETURNED`), and `Evidence.collected_at` to be less than or equal to the current server time. On successful submission, the system stamps `submitted_at`, appends an additional `CustodyEvent` whose `action` is `SUBMITTED` and whose actor is the acting lawyer, and the evidence transitions from `COLLECTED` to `SUBMITTED`.

Once submitted, evidence may enter a contested cycle. Any lawyer may file an `EvidenceRebuttal` carrying `filed_by_lawyer_id` and a free-text `ground` between 1 and 500 characters; each rebuttal starts with `status` `OPEN`. The first rebuttal against a `SUBMITTED` evidence increments the evidence's `rebuttal_count` and transitions the evidence from `SUBMITTED` to `REBUTTED`; subsequent rebuttals against the same evidence simply increment the count and append. While at least one rebuttal on the case is `REBUTTED`-class — that is, while at least one evidence carries `REBUTTED` status — the case posture is recomputed as `RESTRICTED`. A partner may **uphold** a rebuttal, marking it `UPHELD`; if the upheld rebuttal is the latest still-open rebuttal against an evidence in `SUBMITTED` or `REBUTTED`, the evidence transitions to `EXCLUDED`. A partner or senior may **dismiss** a rebuttal, marking it `DISMISSED`; once every rebuttal on a `REBUTTED` evidence has resolved into either `UPHELD` or `DISMISSED`, the evidence falls back from `REBUTTED` to `SUBMITTED`. Either action recomputes the case posture as a side effect. A partner also retains a direct exclusion path: from `COLLECTED`, a partner may exclude an evidence (typically before it ever reaches court), moving it to `EXCLUDED`.

The case posture rule that watches this workflow is the one defined in §2.8: any `REBUTTED` evidence on the case forces `RESTRICTED`; otherwise an imminent SCHEDULED hearing whose start lies in the next 24 hours forces `RESTRICTED`; otherwise an `ON_HOLD` case is `FROZEN`; otherwise the case is `OPEN`. As an example, a case that has just had its first rebuttal filed will go from posture `OPEN` to `RESTRICTED` at exactly the moment the rebuttal is created.

### 3.6. Time Logging, Bill Generation, and Settlement

Time entries are logged on a case by any lawyer rank with a payload carrying `lawyer_id`, `task_label`, `minutes`, and `billable`. The `minutes` value must be greater than 0 and less than or equal to 1440 (one day). At creation, the system pins the lawyer's current `hourly_rate_cents` into the entry's `hourly_rate_cents_pinned` field; this pinned rate is the one used for the final billed calculation, and it is never recomputed even if the lawyer's `hourly_rate_cents` changes later. The entry's initial `status` is `LOGGED` and `adjustment_minutes` is 0.

Adjustments and write-offs follow. A partner or senior may patch the adjustment via `adjustment_minutes` (a signed integer); the resulting `minutes + adjustment_minutes` must be in the range 0 to 1440 inclusive, and a violation surfaces `ERR_TIME_ENTRY_ADJUSTMENT_INVALID`. A successful adjustment moves the entry from `LOGGED` to `ADJUSTED`. A partner-only write-off moves the entry from `LOGGED` or `ADJUSTED` to `WRITTEN_OFF`.

A partner may read a **provisional running cost** for a case at any time. The provisional figure aggregates every time entry on the case whose `billable` is true, regardless of `status` (so `LOGGED`, `ADJUSTED`, `WRITTEN_OFF`, and `BILLED` entries are all included), and uses the lawyer's **current** `hourly_rate_cents` rather than the entry's pinned rate. For each entry, the billable minutes are the maximum of zero and `minutes + adjustment_minutes`; the entry's per-entry cost is those billable minutes multiplied by the current hourly rate, divided by 60, then rounded half-up to the nearest cent; the provisional total is the sum of those per-entry costs. The provisional view is purposefully forward-looking and will diverge from the final billed total whenever a lawyer's rate has changed since entries were logged or whenever any entry was written off — in both cases, the final-billed calculation will use the pinned rate and exclude written-off entries.

Bills are created by a partner against a case in `AWAITING_SETTLEMENT` status, with a payload carrying `billing_mode`, optional `fixed_fee_cents`, optional `contingent_rate_bps`, optional `recovered_amount_cents`, optional `expense_reimbursement_cents`, and optional `cost_recovery_cents`. The `billing_mode` must be one of `HOURLY`, `FIXED`, or `CONTINGENT`. If `billing_mode` is `FIXED`, `fixed_fee_cents` must be supplied and strictly greater than 0. If `billing_mode` is `CONTINGENT`, `contingent_rate_bps` must be supplied and lie between 1 and 5000 inclusive (basis points, with 5000 representing the firm's hard 50% cap). Violations surface `ERR_BILLING_MODE_INVALID`. A new bill enters `DRAFT` status; from `DRAFT` it may move to `ISSUED` (which computes the three monetary fields) or to `VOIDED` (which reverts every `BILLED` time entry on the case back to `ADJUSTED`).

Issuance of a bill is a partner action and runs three calculations in sequence. The first is the **court fee**, a tiered computation based on `case_type` and `claim_amount_cents`. For `CRIMINAL` matters the court fee is a flat 50,000 cents ($500); for `ADMINISTRATIVE` matters it is a flat 30,000 cents ($300). For `CIVIL` and `ARBITRATION` matters the court fee is computed from a marginal-bracket ladder applied to `claim_amount_cents`: the first 10,000 dollars of claim (the cents range from 0 up to 1,000,000 inclusive on the upper boundary) is charged at 5% (500 basis points); the slice from 10,000 to 100,000 dollars (cents 1,000,000 to 10,000,000) at 3%; the slice from 100,000 to 1,000,000 dollars (cents 10,000,000 to 100,000,000) at 2%; and any amount above one million dollars (cents above 100,000,000, up to a 9,999,999,999-cent ceiling) at 1%. The evaluation order is fixed: walk the brackets in ascending order; for each bracket, the slice in cents is the smaller of the remaining claim amount and the bracket width (`upper - lower`); the per-bracket subtotal is the slice times the bracket's basis-point rate divided by 10,000, **rounded half-up to the nearest cent before being added to the running total**. Sum-then-round is forbidden: each bracket's contribution is rounded individually and only then added. For an `ARBITRATION` matter, the system applies a final 50% discount to the bracket-ladder total **after** the per-bracket rounding has occurred (so the discount is applied once to the summed integer-cent total and then rounded half-up, not applied bracket-by-bracket); a `CIVIL` matter receives no discount.

Issuance also requires that every `TimeEntry` row on the case has a `status` other than `LOGGED` — that is, every entry must already be `ADJUSTED`, `WRITTEN_OFF`, or already `BILLED`; a single still-`LOGGED` entry blocks issuance. The second calculation, the **attorney fee**, depends on `billing_mode`. For `HOURLY`, the system aggregates every `TimeEntry` on the case where `billable` is true and `status` is in `ADJUSTED` or `BILLED` (so `WRITTEN_OFF` entries are excluded and `LOGGED` entries cannot exist at issuance time anyway). For each such entry, the billable minutes are the maximum of zero and `minutes + adjustment_minutes`; the per-entry fee is those billable minutes multiplied by the entry's `hourly_rate_cents_pinned`, divided by 60, then rounded half-up to the nearest cent. The attorney fee is the sum of those per-entry rounded amounts; the rounding order is pinned to per-entry first and then sum, never sum first and then round. For `FIXED`, the attorney fee is `fixed_fee_cents` returned verbatim, with no rounding step and with all time entries ignored. For `CONTINGENT`, the attorney fee is `recovered_amount_cents` multiplied by `contingent_rate_bps`, divided by 10,000, then rounded half-up to the nearest cent in a single rounding step.

The third calculation, **total due**, sums the already-cents-rounded `court_fee_cents`, the already-cents-rounded `attorney_fee_cents`, and the input-supplied `expense_reimbursement_cents` (which is already in cents and never rounded), then subtracts `cost_recovery_cents`; if the result would be negative, it is clamped to zero. The order is fixed: court fee plus attorney fee plus expense reimbursement, then minus cost recovery, then clamp. Issuance also cascades: every `TimeEntry` on the case whose `status` is `ADJUSTED` is moved to `BILLED`. A subsequent void of the bill (only legal from `DRAFT`, not from `ISSUED`) reverses the cascade by moving every `BILLED` entry back to `ADJUSTED`.

An issued bill terminates in one of two ways. An external payment event with matching `bill_id` and `amount_cents` exactly equal to `total_due_cents` transitions the bill from `ISSUED` to `PAID`; if `amount_cents` does not match or the bill is not in `ISSUED`, the event is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`. Two simultaneous payment events for the same bill serialize so that exactly one wins; the loser is rejected with `ERR_PAYMENT_DUPLICATE`. Alternatively, a partner may mark an issued bill as `SETTLED` provided the bill has either `recovered_amount_cents` strictly greater than zero or `cost_recovery_cents` strictly greater than zero (a settlement requires evidence that something was recovered).

Case closure runs the **final settlement** calculation, which is deliberately distinct from `total_due`. Where `total_due` is a forward-looking aggregation that subtracts `cost_recovery_cents` once at the end and clamps only the final result, `final_settlement` is a chronological replay that walks the case's events in `created_at` order — every `TimeEntry` whose `status` is `BILLED` (contributing its per-entry fee using the pinned rate, with the same per-entry rounding rule as the hourly attorney fee), then every expense reimbursement record (added to the running balance as a positive contribution), then every recovery record (subtracted from the running balance, with the running balance clamped to zero whenever a recovery would push it negative) — and finally adds `court_fee_cents` at the close instant. The clamp is applied to the **interim** balance after each recovery event, not only to the final result; this is what makes the chronological figure differ from the aggregation snapshot whenever recoveries are recorded against a balance that cannot fully absorb them. The output of this replay is written into the case's `settlement_total_cents`.

### 3.7. External Synchronization Events and Test-Driving Capabilities

Three external systems push events into the API through the `SystemIntegrator` role. A **payment event** (carrying `bill_id`, `amount_cents`, and `external_payment_id`) drives the `ISSUED → PAID` transition described above. A **document signature event** (carrying `draft_id`, `signature_kind`, and `external_signature_id`) records that an external signature service has signed a `SIGNED_OFF` or `LOCKED` draft; `signature_kind` must be one of `DRAFT_LOCKED` or `BILL_ISSUED`, and a payload missing a required field or carrying an invalid `signature_kind` is rejected with `ERR_EVENT_PAYLOAD_INVALID`. A **court-filing event** (carrying `evidence_id` and `court_filing_id`) records that the court has acknowledged an evidence submission. The signature and court-filing events both produce audit log rows but do not themselves move state machines.

Two test-driving capabilities round out the surface. An admin-only logical-clock-advance capability moves the server's logical clock to a supplied `target_timestamp` and, as side effects, auto-transitions any case whose `closed_at` is at least 30 days before the new clock to `ARCHIVED`, and recomputes the case posture for any case whose imminent-hearing window has now flipped (a hearing that was outside the 24-hour window may now be inside it, or vice versa). A second admin-only sweep capability force-runs every auto-transition check at any clock time — case archival, evidence-rebuttal resolution cascades, and posture recomputation — and is idempotent with respect to repeated invocation. Both capabilities are restricted to `SystemIntegrator` and exist purely to drive scheduled deferred behavior in tests.

Generic input violations not covered by a more specific code (for example, a string field too short, a number field out of range, a malformed enum value, or a malformed timestamp) surface `ERR_VALIDATION_FAILED`.

## 4. Endpoint Definitions

Every endpoint adheres to the global validation ladder of §2.6 and the response envelope of §2.2. Endpoints that create a new resource return HTTP 201; endpoints that modify or read an existing resource return HTTP 200. The response body always carries the affected primary resource (the row created, or the row whose state changed) unless the description in §3 indicates otherwise.

| Method | Path | Description | Authorized Roles |
| --- | --- | --- | --- |
| POST | /cases | Register a new case (intake); runs conflict-of-interest check and case-number assignment. | PartnerLawyer, IntakeClerk |
| GET | /cases/{id} | Read case. | PartnerLawyer, SeniorLawyer, JuniorLawyer, IntakeClerk |
| GET | /cases | List cases with optional status / case_type / lead_lawyer_id filters. | PartnerLawyer, SeniorLawyer, JuniorLawyer, IntakeClerk |
| POST | /cases/{id}/activate | Transition INTAKE → ACTIVE. | PartnerLawyer |
| POST | /cases/{id}/hold | Transition ACTIVE → ON_HOLD; cancels SCHEDULED hearings. | PartnerLawyer |
| POST | /cases/{id}/resume | Transition ON_HOLD → ACTIVE. | PartnerLawyer |
| POST | /cases/{id}/await-settlement | Transition ACTIVE → AWAITING_SETTLEMENT; locks SIGNED_OFF drafts. | PartnerLawyer, SeniorLawyer |
| POST | /cases/{id}/close | Transition AWAITING_SETTLEMENT → CLOSED; computes final settlement. | PartnerLawyer |
| POST | /cases/{caseId}/parties | Add a party to a case. | IntakeClerk, PartnerLawyer, SeniorLawyer |
| POST | /parties/{id}/verify-identity | Mark a party identity_verified. | IntakeClerk, PartnerLawyer |
| GET | /cases/{caseId}/parties | List parties on a case. | PartnerLawyer, SeniorLawyer, JuniorLawyer, IntakeClerk |
| POST | /document-templates | Register a document template. | PartnerLawyer |
| GET | /document-templates | List templates. | PartnerLawyer, SeniorLawyer, JuniorLawyer |
| POST | /document-drafts | Create a draft (auto-fills variables; pins template version). | PartnerLawyer, SeniorLawyer, JuniorLawyer |
| POST | /document-drafts/{id}/submit-for-review | Transition DRAFTING → IN_REVIEW. | PartnerLawyer, SeniorLawyer, JuniorLawyer |
| POST | /document-drafts/{id}/senior-pass | Transition IN_REVIEW → DRAFTING with senior_reviewer_lawyer_id set. | PartnerLawyer, SeniorLawyer |
| POST | /document-drafts/{id}/request-revisions | Transition IN_REVIEW → REVISING. | PartnerLawyer, SeniorLawyer |
| POST | /document-drafts/{id}/resume-drafting | Transition REVISING → DRAFTING (drafter-only). | PartnerLawyer, SeniorLawyer, JuniorLawyer |
| POST | /document-drafts/{id}/partner-signoff | Transition IN_REVIEW → SIGNED_OFF. | PartnerLawyer |
| POST | /document-drafts/{id}/lock | Transition SIGNED_OFF → LOCKED. | PartnerLawyer |
| GET | /document-drafts/{id} | Read draft including rendered_body. | PartnerLawyer, SeniorLawyer, JuniorLawyer |
| POST | /hearings | Schedule a hearing; runs room and lawyer capacity checks; generates prep tasks. | PartnerLawyer, SeniorLawyer, IntakeClerk |
| POST | /hearings/{id}/reschedule | Reschedule (creates new hearing pointing back via previous_hearing_id). | PartnerLawyer, SeniorLawyer |
| POST | /hearings/{id}/cancel | Transition SCHEDULED → CANCELLED. | PartnerLawyer, SeniorLawyer |
| POST | /hearings/{id}/complete | Transition SCHEDULED → COMPLETED (after scheduled_end). | PartnerLawyer, SeniorLawyer |
| GET | /hearings/{id}/prep-tasks | Read deterministic prep-task checklist. | PartnerLawyer, SeniorLawyer, JuniorLawyer |
| GET | /cases/{caseId}/hearings | List hearings on a case. | PartnerLawyer, SeniorLawyer, JuniorLawyer, IntakeClerk |
| POST | /evidence | Record an evidence collection; appends initial CustodyEvent. | PartnerLawyer, SeniorLawyer, JuniorLawyer |
| POST | /evidence/{id}/custody-events | Append a custody-chain event. | PartnerLawyer, SeniorLawyer, JuniorLawyer |
| POST | /evidence/{id}/submit | Transition COLLECTED → SUBMITTED. | PartnerLawyer, SeniorLawyer |
| POST | /evidence/{id}/exclude | Transition COLLECTED → EXCLUDED (partner-only veto). | PartnerLawyer |
| POST | /evidence/{id}/rebuttals | File a rebuttal against a SUBMITTED evidence. | PartnerLawyer, SeniorLawyer, JuniorLawyer |
| POST | /rebuttals/{id}/uphold | Mark rebuttal UPHELD; may exclude the underlying evidence. | PartnerLawyer |
| POST | /rebuttals/{id}/dismiss | Mark rebuttal DISMISSED. | PartnerLawyer, SeniorLawyer |
| GET | /evidence/{id} | Read evidence with its custody chain. | PartnerLawyer, SeniorLawyer, JuniorLawyer |
| POST | /cases/{caseId}/time-entries | Log a time entry on a case (rate pinned at creation). | PartnerLawyer, SeniorLawyer, JuniorLawyer |
| PATCH | /time-entries/{id}/adjust | Apply adjustment_minutes (LOGGED → ADJUSTED). | PartnerLawyer, SeniorLawyer |
| POST | /time-entries/{id}/write-off | Transition LOGGED or ADJUSTED → WRITTEN_OFF. | PartnerLawyer |
| GET | /cases/{caseId}/time-entries/summary | Provisional running cost. | PartnerLawyer, SeniorLawyer |
| POST | /cases/{caseId}/bills | Create a bill (DRAFT). | PartnerLawyer |
| POST | /bills/{id}/issue | Transition DRAFT → ISSUED; computes court_fee, attorney_fee, total_due. | PartnerLawyer |
| POST | /bills/{id}/mark-settled | Transition ISSUED → SETTLED. | PartnerLawyer |
| POST | /bills/{id}/void | Transition DRAFT → VOIDED; reverts BILLED time entries. | PartnerLawyer |
| POST | /lawyers | Register a lawyer. | PartnerLawyer |
| GET | /lawyers/{id} | Read lawyer. | PartnerLawyer, SeniorLawyer, JuniorLawyer, IntakeClerk |
| POST | /_events/payment-received | External payment event; transitions Bill ISSUED → PAID. | SystemIntegrator |
| POST | /_events/document-signed | External signature event against a SIGNED_OFF or LOCKED draft. | SystemIntegrator |
| POST | /_events/court-filed | External court-filing event acknowledging evidence submission. | SystemIntegrator |
| GET | /audit-logs | Read audit log with subject_type / subject_id / actor_id filters. | PartnerLawyer |
| POST | /_clock/advance | Advance the server's logical clock; triggers time-gated transitions. | SystemIntegrator |
| POST | /_sweep/run | Force-run scheduled sweeps (case archival, rebuttal resolution, posture recomputation). | SystemIntegrator |

## 5. Error Code Catalogue

| Error ID | HTTP Status |
| --- | --- |
| ERR_AUTH_REQUIRED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCED_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_CASE_ARCHIVED | 409 |
| ERR_CASE_POSTURE_FROZEN | 409 |
| ERR_CONFLICT_OF_INTEREST | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_REVIEWER_RANK_INSUFFICIENT | 403 |
| ERR_DRAFT_LOCKED | 409 |
| ERR_TEMPLATE_CASE_TYPE_MISMATCH | 422 |
| ERR_HEARING_INVALID_INTERVAL | 422 |
| ERR_HEARING_PAST_TIME | 422 |
| ERR_HEARING_ROOM_CONFLICT | 409 |
| ERR_LAWYER_SCHEDULE_CONFLICT | 409 |
| ERR_PARTY_NOT_VERIFIED | 409 |
| ERR_CUSTODY_CHAIN_BROKEN | 409 |
| ERR_BILLING_MODE_INVALID | 422 |
| ERR_TIME_ENTRY_ADJUSTMENT_INVALID | 422 |
| ERR_CLAIM_AMOUNT_INVALID | 422 |
| ERR_PAYMENT_AMOUNT_MISMATCH | 422 |
| ERR_PAYMENT_DUPLICATE | 409 |
| ERR_EVENT_PAYLOAD_INVALID | 422 |
| ERR_VERSION_MISMATCH | 409 |
| ERR_VALIDATION_FAILED | 422 |
