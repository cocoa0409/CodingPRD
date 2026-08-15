# Patient Portal Inbox API — Product Requirements Document

## 1. Introduction

Ambulatory practices are drowning in portal traffic. Patients send everything from chest-pain complaints to refill requests to billing questions through the same inbox, and the practice must answer each one quickly, by the right person, at the right cost. Unmanaged, this inbox creates three distinct risks: clinically urgent messages wait too long, providers burn out on uncompensated after-hours work, and the practice either bills for services it cannot defend or fails to bill for legitimate e-visits.

This document specifies the Patient Portal Inbox API, the system of record for an ambulatory practice's inbox team. The API governs the full lifecycle of a portal message: intake and education gating, triage by clinical urgency, routing into staffed pools with per-urgency response-time targets, claiming under coverage and delegation rules, after-hours escalation to an on-call provider, supervised completion with a cosign protocol for non-provider clinical work, billable e-visit determination with patient consent to a disclosed charge, and the downstream claim lifecycle from draft through adjudication, denial-driven rework, or write-off. Alongside the workflow, the system measures provider inbox burden and enforces response-time SLAs so that operational risk is visible rather than anecdotal.

All resources are mounted under the `/inbox` path prefix. Every timestamp the system records or evaluates — message receipt, triage, deadlines, coverage containment, on-call selection, SLA breach — is read from a single logical clock (§2.5), never from wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. Header values are stripped of surrounding whitespace before use. A request missing either header, or carrying an empty or whitespace-only value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Each operation is restricted to designated roles; a caller whose role is not authorized for the operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognizes six roles, spelled exactly as follows: `Patient`, `TriageNurse`, `FrontDesk`, `Provider`, `BillingSpecialist`, and `PracticeAdmin`. Any other role string is authorized for no operation and is likewise rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

Role identity is bound to persisted entities for five of the six roles. When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient`; ownership checks on any resource that references a patient compare the resource's `patient_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_PATIENT_OWNERSHIP_MISMATCH`. A `Patient` caller reading a single record may only read their own record — their own patient profile, their own messages, their own consent records, their own claims, their own education notices — and when calling a list endpoint must pass a `patient_id` filter equal to their own `X-User-ID`; omitting it or naming another patient is likewise rejected with `ERR_PATIENT_OWNERSHIP_MISMATCH`. A `Patient` caller whose `X-User-ID` names no persisted `Patient` fails every ownership check with `ERR_PATIENT_OWNERSHIP_MISMATCH`. When `X-User-Role` is `TriageNurse`, `FrontDesk`, `Provider`, or `BillingSpecialist`, `X-User-ID` is the `id` of the acting `StaffMember`; caller-identity checks compare resource fields such as `assignee_id`, `provider_id`, or `delegator_provider_id` to `X-User-ID`.

The four staff-backed roles carry an additional consistency obligation: the referenced `StaffMember` must exist and its `staff_type` must agree with the role — `TriageNurse` requires `NURSE`, `FrontDesk` requires `FRONT_DESK`, `Provider` requires `PROVIDER`, and `BillingSpecialist` requires `BILLING_SPECIALIST`. A disagreement is rejected with `ERR_ROLE_STAFF_MISMATCH`. When `X-User-Role` is `PracticeAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id` and the role is exempt from the staff-consistency check, so that the first administrator can bootstrap master data before any staff record exists.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits. The envelope timestamp is read from the server's wall clock; it is the one timestamp exempt from the logical-clock discipline of §2.5, which governs resource and workflow timestamps only.
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

Requests to an undefined path, or to a defined path with an unsupported method, are rejected with `ERR_NOT_FOUND` (404). A request body that parses to a non-object JSON value is rejected with `ERR_INVALID_REQUEST`; an absent or unparseable body is treated as an empty object, so any required-field failures then surface.

---

### 2.3. Pagination

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped; it defaults to 0 and must be at least 0. A non-integer value for either parameter, a `limit` outside the 1–100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`. All list endpoints return resources sorted by `created_at` in ascending order; because the logical clock can stand still, creation-timestamp ties are possible, and they break by `id` in ascending order. List responses carry the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

So that every related record remains reachable from the entity it references, list endpoints accept optional foreign-key and status filters; the specific filters each list supports are named in the workflow narratives of §3.

### 2.4. Common Resource Properties

Every resource in the system — patients, staff members, pools, coverage windows, on-call shifts, delegation grants, portal messages, staff time entries, consent records, e-visit claims, escalations, and patient education notices — carries the same four system-managed properties:

- **`id` (string):** a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording the last modification; it is refreshed on any change to the resource.
- **`version` (integer):** a system-managed integer that starts at 1 on creation and increments on every mutation of the resource, including system-driven recomputation of derived fields.

### 2.5. The Logical Clock

The system never reads wall-clock time. A single logical clock governs every recorded timestamp and every temporal evaluation: `received_at`, `triaged_at`, `responded_at`-style stamps, `requested_at`, `submitted_at`, `adjudicated_at`, `acknowledged_at`, `revoked_at`, response-deadline computation, coverage-window and on-call-shift containment, overlap checks, the on-call selector, and SLA breach math. At server startup, before any administrative intervention, the logical clock reads exactly `2026-08-01T00:00:00Z`. It moves only when a `PracticeAdmin` invokes the clock-setting capability with a `to_iso8601` instant — any parseable instant is accepted, earlier or later than the current value, with no monotonicity constraint — and the capability responds with the resulting `current_utc`. The logical clock never falls back to wall-clock time under any circumstance.

### 2.6. Validation Order and Error Selection

When several checks could reject the same request, the server evaluates them in a fixed priority order and reports the first failure. The tiers, in order:

1. **Header presence** — `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (§2.1).
2. **Role permission** — the caller's role must be authorized for the operation, else `ERR_INSUFFICIENT_PERMISSIONS`.
3. **Role–staff consistency** — staff-backed roles must resolve to a matching `StaffMember`, else `ERR_ROLE_STAFF_MISMATCH`.
4. **Patient ownership** — a `Patient` caller acting on another patient's resource, or listing without their own `patient_id` filter, is rejected with `ERR_PATIENT_OWNERSHIP_MISMATCH`.
5. **Existence** — path- and body-referenced resources must exist, validated left to right (§2.8), else `ERR_NOT_FOUND`.
6. **Optimistic concurrency** — on OCC-guarded writes the presented version must match, else `ERR_STALE_VERSION` (§2.7).
7. **From-state validity** — the target resource must be in a state that permits the action: message-state failures surface `ERR_MESSAGE_INVALID_STATE`, claim-state failures `ERR_CLAIM_INVALID_STATE`, consent responses outside `REQUESTED` surface `ERR_CONSENT_ALREADY_RESPONDED`, notice acknowledgements outside `ISSUED` surface `ERR_NOTICE_ALREADY_ACKNOWLEDGED`, grant revocations outside `ACTIVE` surface `ERR_GRANT_ALREADY_REVOKED`, escalation acknowledgements outside `OPEN` surface `ERR_ESCALATION_INVALID_STATE`, and cosign attempts on a message not awaiting cosign surface `ERR_NOT_AWAITING_COSIGN`.
8. **Business rules in ascending priority** — safety rules (the education gate `ERR_EDUCATION_ACK_REQUIRED`; the chargeable-message requirement `ERR_MESSAGE_NOT_CHARGEABLE`; cosigner identity `ERR_NOT_AUTHORIZED_COSIGNER`; the clinical-category requirement `ERR_CATEGORY_NOT_CLINICAL`), then referential rules (pool-kind eligibility `ERR_POOL_ROLE_MISMATCH`; assignee identity `ERR_NOT_ASSIGNEE`; on-call provider type `ERR_ONCALL_PROVIDER_TYPE`; delegation target validity `ERR_INVALID_DELEGATION_TARGET`; rendering-provider participation `ERR_RENDERING_PROVIDER_NOT_ON_THREAD`; grant ownership `ERR_NOT_GRANT_OWNER`), then temporal rules (time-range validity `ERR_INVALID_TIME_RANGE`; coverage-window overlap `ERR_COVERAGE_WINDOW_OVERLAP`; on-call-shift overlap `ERR_ONCALL_SHIFT_OVERLAP`; delegation-window overlap `ERR_DELEGATION_WINDOW_OVERLAP`; active coverage at claim time `ERR_NO_ACTIVE_COVERAGE`; the seven-day e-visit dedupe `ERR_EVISIT_DUPLICATE_WITHIN_7_DAYS`), then constraint rules (escalation urgency `ERR_URGENCY_NOT_ESCALATABLE`; on-call selector non-empty `ERR_NO_ONCALL_COVERAGE`; single pending consent `ERR_CONSENT_REQUEST_PENDING`; single active claim `ERR_CLAIM_ALREADY_EXISTS`; claim-in-flight blocks `ERR_CLAIM_IN_FLIGHT`), then fiscal rules (e-visit minimum minutes `ERR_EVISIT_MINUTES_BELOW_MINIMUM`; disclosed-fee ceiling `ERR_DISCLOSED_FEE_EXCEEDED`).
9. **Input shape** — malformed bodies (missing required fields, invalid enum members, out-of-range integers, unmet conditional fields) are reported as `ERR_INVALID_REQUEST`. A required field that is absent, null, or an empty or whitespace-only string counts as missing; an optional field carrying an empty or whitespace-only string is treated as omitted; booleans are not accepted where an integer or number is required. Rather than running last as a separate pass, body fields are validated at the moment the endpoint's logic first reads them, and a shape failure is reported immediately — ahead of any ownership, from-state, business-rule, or body-referential check that has not yet run. Three ordering guarantees nonetheless hold without exception: tiers 1–3 (headers, role permission, role–staff consistency) run first; the existence of every path identifier is validated before any body field is read, so when both a body-field error and a path-existence error apply, the existence tier wins and the request is rejected with `ERR_NOT_FOUND`; and on the two OCC-guarded endpoints the version check of §2.7 — including the presence and integer shape of `expected_message_version` — runs before the from-state check and before any other body field is read.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control: `POST /inbox/portal-messages/{id}/triage` and `POST /inbox/portal-messages/{id}/determine-billing`. Each request must carry `expected_message_version`, a non-optional field holding the caller's last observed `version` of the target `PortalMessage`; a request that omits it, or carries a non-integer value, is rejected with `ERR_INVALID_REQUEST`, and this shape check is evaluated together with the concurrency gate, ahead of the from-state check. If the presented value does not equal the message's current `version` — because another writer has advanced the message since the caller last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), so a client cannot reclassify or re-determine a message whose classification or disposition it has not observed. Re-triage and re-determination are both legitimate sequential operations (§3.3, §3.6), which is precisely why the stale-version guard, rather than a state check, is the serialization point between writers. No other endpoint accepts a version field.

### 2.8. Nested Resource Retrieval

For any request whose path or body references multiple resources, the server validates existence in a strict left-to-right order and rejects with `ERR_NOT_FOUND` (HTTP 404) at the first identifier — message, patient, staff member, pool, coverage window, on-call shift, delegation grant, consent record, claim, escalation, or education notice — that does not correspond to an existing resource. Later references are not examined once an earlier one has failed.

### 2.9. Scheduling Windows: Interval Semantics and Overlap Rules

Three resource kinds describe time spans, with two different containment conventions. A **coverage window** is a half-open interval: it covers an instant `t` when `start_utc` is at or before `t` and `end_utc` is strictly after `t`. An **on-call shift** and a **delegation grant** are closed intervals: they cover `t` when `start_utc` is at or before `t` and `end_utc` is at or after `t`. For all three kinds, `end_utc` must be strictly later than `start_utc`; otherwise creation fails with `ERR_INVALID_TIME_RANGE`.

Overlap rules mirror the containment conventions. Two coverage windows for the same `staff_id` may not intersect, but adjacency is allowed: a new window whose `start_utc` equals an existing window's `end_utc` (or whose `end_utc` equals an existing window's `start_utc`) does not conflict; a genuine intersection is rejected with `ERR_COVERAGE_WINDOW_OVERLAP`. Two on-call shifts for the same `provider_id` may not intersect under closed-interval semantics, and touching endpoints count as overlap — a new shift starting exactly when an existing one ends is rejected with `ERR_ONCALL_SHIFT_OVERLAP`. Two `ACTIVE` delegation grants for the same delegator–delegate pair likewise may not intersect under closed-interval semantics, touching endpoints included, else `ERR_DELEGATION_WINDOW_OVERLAP`.

### 2.10. Monetary Precision

All monetary quantities are integer numbers of cents: `fee_cents`, `disclosed_fee_cents`, `patient_responsibility_cents`, `outstanding_billed_cents`, and `copay_cents`. Rounding is pinned to a single order of operations. Each individual claim's patient responsibility is rounded to integer cents using round-half-up at the moment the claim is created or reworked; patient-level totals such as `outstanding_billed_cents` are then plain integer sums of those already-rounded per-claim values. The system must never sum unrounded products and round once at the end — the two orders diverge. For example, two claims each with a 5000-cent fee and a coinsurance fraction of 0.3333 yield a per-claim responsibility of round-half-up of 1666.5, that is 1667 cents, for a patient total of 3334 cents; summing the unrounded products first would incorrectly yield 3333 cents.

### 2.11. Inbox Load Accounting

Each `StaffMember` carries `open_inbox_count`, the number of portal messages whose `assignee_id` names that staff member and whose `status` is one of the counted statuses: `ASSIGNED`, `IN_REVIEW`, `PENDING_CONSENT`, `PENDING_COSIGN`, `ESCALATED`, or `REOPENED`. Messages in `RECEIVED`, `TRIAGED`, `RESOLVED`, or `CLOSED` — and messages with no assignee — do not count. The count is maintained incrementally on every transition that changes an assignee or moves a message into or out of the counted set, and reassignment-style operations (re-route, escalation, delegation-revoke cascade) are zero-sum across staff: the global sum of `open_inbox_count` over all staff always equals the number of messages in counted statuses with a non-null assignee.

Whenever `open_inbox_count` changes, the boolean `inbox_overloaded` is re-evaluated: it is true exactly when the count is five or more. At the boundary, a count of five flags the staff member as overloaded; a count of four does not.

### 2.12. Response Deadlines and SLA Discipline

Every triaged message carries `response_due_at`, computed from the routing pool's per-urgency targets and deadline policy (§3.3). A message is SLA-breached when its effective response moment — `first_response_at` if a staff reply has been sent, otherwise the current logical-clock time — is strictly later than `response_due_at`. Landing exactly on the deadline is not a breach. Messages whose `response_due_at` is still null (never yet triaged, or cleared by a reopen) are skipped by all breach evaluation.

The `sla_breached` flag is sticky: once true it remains true forever, including across re-triage, reopen, and reassignment. The flag is latched at two moments — when a staff reply is recorded and when the message reaches `RESOLVED` — and a `PracticeAdmin` may also invoke the SLA sweep capability, which evaluates every message not in `RESOLVED` or `CLOSED` with a non-null `response_due_at`, persists newly detected breaches, and reports `swept_count` (messages evaluated) and `newly_breached_count` (messages newly flagged).

## 3. Business Logic & Workflows

### 3.1. Patients, Staff, and Routing Pools

Before any message can flow, a `PracticeAdmin` registers the practice's master data. Registering a patient requires a `full_name` and a `plan_type` of `COPAY` or `COINSURANCE`, which selects the patient's cost-sharing model for later e-visit responsibility math. A `date_of_birth` may optionally be recorded; its value is stored exactly as supplied, without format validation. The cost-sharing fields are plan-conditional: `copay_cents`, the patient's flat copay in cents, is required if and only if `plan_type` is `COPAY`, and `coinsurance_pct`, a fractional rate greater than zero and at most one, is required if and only if `plan_type` is `COINSURANCE`; the inapplicable field must be omitted entirely and is stored as null, so supplying `copay_cents` under `COINSURANCE` or `coinsurance_pct` under `COPAY` is a violation just as a missing required field is. Violations of these conditionals are rejected with `ERR_INVALID_REQUEST`. A newly registered patient starts with `outstanding_billed_cents` at zero and `education_gate_open` false.

Staff onboarding follows the same administrative path. Each `StaffMember` is created with a `full_name` and a `staff_type` drawn from `PROVIDER`, `NURSE`, `FRONT_DESK`, `BILLING_SPECIALIST`, or `PRACTICE_ADMIN`. The staff type is the linchpin of the role-consistency rule of §2.1, of pool-kind eligibility at claim time, and of the cosign protocol, so it must reflect the person's real function. New staff members begin with `open_inbox_count` at zero and `inbox_overloaded` false.

Routing pools complete the intake configuration. A `PracticeAdmin` creates each pool with a display `name`, a `pool_kind` of `NURSE_TRIAGE`, `PROVIDER_INBOX`, `FRONT_DESK`, or `BILLING`, and three integer response-time targets in minutes: `target_minutes_emergent`, `target_minutes_urgent`, and `target_minutes_routine`. The pool's `deadline_policy`, either `FROM_RECEIPT` or `FROM_TRIAGE`, selects which of the two response-deadline variants applies to every message routed into it (§3.3).

### 3.2. Coverage Scheduling, On-Call Rosters, and Delegation

Pool staffing is expressed through coverage windows. A `PracticeAdmin` creates each window with the `pool_id` being staffed, the covering `staff_id`, and a `start_utc`/`end_utc` pair interpreted as a half-open interval (§2.9). Creation validates the time range first — `end_utc` must be strictly later than `start_utc`, else `ERR_INVALID_TIME_RANGE` — and then checks overlap: for the same staff member, the new window must not intersect any existing window, though back-to-back windows that merely touch are allowed; a true intersection is rejected with `ERR_COVERAGE_WINDOW_OVERLAP`. The coverage-window list supports filtering by `pool_id` and `staff_id`.

The on-call roster determines who receives after-hours escalations. An administrator creates an `OnCallShift` with a `provider_id` and a closed `start_utc`/`end_utc` interval. Three checks run in order: the referenced staff member must have `staff_type` `PROVIDER`, else `ERR_ONCALL_PROVIDER_TYPE`; the range must be strictly positive, else `ERR_INVALID_TIME_RANGE`; and the closed interval must not intersect — touching endpoints included — any existing shift for the same provider, else `ERR_ONCALL_SHIFT_OVERLAP`. The shift list supports filtering by `provider_id`.

A provider who will be away can delegate their inbox coverage. Creating a `DelegationGrant` names a `delegate_staff_id`, a `pool_id`, and a closed `start_utc`/`end_utc` window; the server stamps `delegator_provider_id` from the creating provider's `X-User-ID` and opens the grant in `ACTIVE` status. The delegation target must be valid: the delegate must differ from the delegator, the delegate must exist, and the named pool must exist with `pool_kind` `PROVIDER_INBOX` — any failure is `ERR_INVALID_DELEGATION_TARGET`. The range check follows, then a closed-interval overlap check among `ACTIVE` grants for the same delegator–delegate pair, where touching endpoints count as overlap (`ERR_DELEGATION_WINDOW_OVERLAP`). Grant lists may be filtered by `delegator_provider_id`, `delegate_staff_id`, `pool_id`, and `status`.

Revoking a grant is the provider's recall of that authority, and it has teeth. Revocation is permitted only while the grant is `ACTIVE` — an already-revoked grant fails with `ERR_GRANT_ALREADY_REVOKED` — and only for the grant's own delegator, with anyone else rejected as `ERR_NOT_GRANT_OWNER`. Revocation stamps `revoked_at`, moves the grant to `REVOKED`, and cascades: every portal message currently assigned to the delegate within that pool and sitting in `ASSIGNED`, `IN_REVIEW`, or `PENDING_COSIGN` is reassigned to the delegator with its status retained. The delegate's `open_inbox_count` drops by the number of reassigned messages and the delegator's rises by the same amount — a zero-sum shift per §2.11 — and `inbox_overloaded` is re-evaluated for both parties.

### 3.3. Intake, Triage, and Routing

A patient initiates the workflow by sending a portal message with a `subject` and a `body`; the server records `patient_id` from the caller's `X-User-ID`, stamps `received_at` from the logical clock, and opens the message in `RECEIVED` status with `urgency` and `category` unset, `billing_disposition` at `UNDETERMINED`, `clinical_minutes_total` and `reopen_count` at zero, and `sla_breached` false. Intake is gated by the education protocol of §3.7: while the patient's education gate is open, message creation is rejected with `ERR_EDUCATION_ACK_REQUIRED`.

Classification belongs to the `TriageNurse`. The triage call carries the message's `urgency` (`EMERGENT`, `URGENT`, or `ROUTINE`), its `category` (`CLINICAL` or `ADMINISTRATIVE`), the target `pool_id`, and the OCC field `expected_message_version` (§2.7). Triage is valid from exactly three statuses: from `RECEIVED` it performs the initial classification, from `TRIAGED` a re-triage supersedes the prior classification, overwriting `urgency`, `category`, and `assigned_pool_id`, and from `REOPENED` it readmits a reopened thread as described below; a message in any other status fails with `ERR_MESSAGE_INVALID_STATE`. Either way `triaged_at` is set to the logical now and the message's `version` increments by one. A `REOPENED` message is also triageable, with one extra side effect: its `assignee_id` is cleared and the message returns to the pool queue, so the prior assignee's `open_inbox_count` falls by one — `TRIAGED` is not a counted status — and their `inbox_overloaded` flag is re-evaluated.

Triage is what arms the response clock. The message's `response_due_at` is computed as a base instant plus the target for the newly assigned urgency: the pool's `target_minutes_emergent` for an `EMERGENT` message, `target_minutes_urgent` for `URGENT`, and `target_minutes_routine` for `ROUTINE`. The base depends on the pool's `deadline_policy`. Under `FROM_RECEIPT` the base is the message's original `received_at`, and it never moves — re-triage does not shift it, and a reopened message re-triaged later may legitimately come out already past due. Under `FROM_TRIAGE` the base is the latest `triaged_at`, so each re-triage slides the deadline forward. The result is expressed in the same three-fractional-digit ISO 8601 UTC format as every other system timestamp; the due instant is exactly the base plus the target, with no rounding. Re-triage never clears `sla_breached`.

From `TRIAGED`, the nurse routes work by assigning. The assign call accepts an optional `staff_id`: when present, the named staff member becomes the `assignee_id`, their `open_inbox_count` rises by one, and the message enters `ASSIGNED`; when absent, the message enters `ASSIGNED` with no assignee and simply waits on the pool queue. Assignment is also the re-route mechanism — from `ASSIGNED` back to `ASSIGNED` — where the previous assignee, if any, loses one from their count and the new assignee, if a `staff_id` is presented, gains one, keeping the global tally zero-sum. The message's own state is validated before an optional `staff_id` is resolved, so a nonexistent `staff_id` presented for a message outside `TRIAGED`/`ASSIGNED` surfaces `ERR_MESSAGE_INVALID_STATE` rather than `ERR_NOT_FOUND`. The message list endpoint supports filtering by `patient_id`, `assigned_pool_id`, `assignee_id`, `pending_cosign_by_id`, `resolved_by_id`, and `status`, with `Patient` callers restricted per §2.1.

### 3.4. Claiming, Working, and Closing the Loop

Work begins when a staff member claims a message off its pool queue, moving it from `ASSIGNED` to `IN_REVIEW`; a message in any other state is rejected with `ERR_MESSAGE_INVALID_STATE`. Claiming enforces two gates, evaluated in this order after the state check. First, pool-kind eligibility: `NURSE_TRIAGE` pools accept `NURSE` staff, `FRONT_DESK` pools accept `FRONT_DESK` staff, `BILLING` pools accept `BILLING_SPECIALIST` staff, and `PROVIDER_INBOX` pools accept `PROVIDER` staff — or any staff member who is the delegate on an `ACTIVE` delegation grant for that pool whose window covers the logical now; ineligible callers are rejected with `ERR_POOL_ROLE_MISMATCH`. Second, active coverage: the caller must either hold a coverage window for the message's assigned pool that covers the logical now, or be the delegate on an `ACTIVE` grant for that pool whose window covers now, else `ERR_NO_ACTIVE_COVERAGE`. Claiming takes ownership only when the message is unowned: if `assignee_id` is null, the caller becomes the assignee and their `open_inbox_count` rises by one; if the caller already is the assignee, nothing changes; the claim can never seize a message from a different owner — attempting to claim a message owned by someone else is rejected with `ERR_NOT_ASSIGNEE`.

Once work is underway, nurses, front-desk staff, and providers record their effort as time entries with a `message_id`, an `entry_kind` of `CLINICAL_REVIEW` or `ADMINISTRATIVE`, a whole-number `minutes` value of at least 1 and at most 480 (violations are `ERR_INVALID_REQUEST`), and an optional free-text `note`; the server stamps `staff_id` from the caller's identity. Care is team-based, so logging time is not restricted to the assignee — but the message must be in a working status: `IN_REVIEW`, `PENDING_CONSENT`, `PENDING_COSIGN`, `ESCALATED`, or `REOPENED`; on any other status the entry is rejected with `ERR_MESSAGE_INVALID_STATE`. Each new entry recomputes the message's `clinical_minutes_total`, which sums `minutes` over the message's `CLINICAL_REVIEW` entries whose author has `staff_type` `PROVIDER`; `ADMINISTRATIVE` entries and clinical-review entries by non-providers are excluded, with no time window. Time-entry lists may be filtered by `message_id`, `staff_id`, and `entry_kind`.

Replies are the visible heartbeat of the thread. Every reply call, patient or staff, must carry a `body`. A staff reply must come from the message's assignee — anyone else is rejected with `ERR_NOT_ASSIGNEE`, a check applied before any state check — and the message must stand in one of the six open statuses `ASSIGNED`, `IN_REVIEW`, `PENDING_CONSENT`, `PENDING_COSIGN`, `ESCALATED`, or `REOPENED`; a staff reply on a message in any other status is rejected with `ERR_MESSAGE_INVALID_STATE`. The first staff reply stamps `first_response_at` exactly once; later replies leave it untouched. Every staff reply also re-evaluates the SLA latch of §2.12. A patient reply means something different: on their own message in `RESOLVED` status, it reopens the thread, moving the message to `REOPENED`, incrementing `reopen_count`, retaining `resolved_by_id` and `resolved_at` as history, restoring one to the retained assignee's `open_inbox_count` with `inbox_overloaded` re-evaluated, and clearing `response_due_at` until the next triage. A patient reply on a message in any non-`RESOLVED` status — including `REOPENED` itself — is rejected with `ERR_MESSAGE_INVALID_STATE`; a reopened message exits only through triage. Patient replies on others' messages fail ownership with `ERR_PATIENT_OWNERSHIP_MISMATCH`.

Completion acts on an `IN_REVIEW` message — any other status fails with `ERR_MESSAGE_INVALID_STATE` — and belongs to the assignee alone, with any other caller rejected as `ERR_NOT_ASSIGNEE`; the call records a `resolution_summary`. What happens next depends on supervision. Cosign is required exactly when the message's `category` is `CLINICAL` and the assignee's `staff_type` is not `PROVIDER`. When required, completion routes the message to `PENDING_COSIGN` and designates the cosigner: `pending_cosign_by_id` is set to the `delegator_provider_id` of the `ACTIVE` delegation grant that links the assignee to the message's assigned pool and whose window covers the logical now, or left null when no such grant exists — in which case any provider may cosign. Ownership counts do not change, since `PENDING_COSIGN` is a counted status. When cosign is not required, completion resolves the message outright: `resolved_by_id` records the caller, `resolved_at` stamps the logical now, the assignee's `open_inbox_count` falls by one with `inbox_overloaded` re-evaluated, and the SLA flag latches per §2.12.

The cosign decision itself belongs to a `Provider` acting on a `PENDING_COSIGN` message — any other state is `ERR_NOT_AWAITING_COSIGN` — and when `pending_cosign_by_id` names a specific provider, only that provider may act (`ERR_NOT_AUTHORIZED_COSIGNER`). The call carries an `action`: `COSIGN` moves the message to `RESOLVED` with `resolved_by_id` set to the cosigning provider and `resolved_at` stamped, the assignee's count falling by one with overload re-evaluated and the SLA flag latched, and `pending_cosign_by_id` retained on the resolved message as a record of the designation; `RETURN` sends the message back to `IN_REVIEW`, clears `pending_cosign_by_id`, and retains the assignee with no count change, since both statuses are counted.

Closure is the terminal act. A `TriageNurse` or `Provider` may close a message only from `RESOLVED` (else `ERR_MESSAGE_INVALID_STATE`) and only while no e-visit claim for the message sits in `DRAFT`, `SUBMITTED`, or `DENIED` — an in-flight claim blocks closure with `ERR_CLAIM_IN_FLIGHT`. A successful close lands the message in `CLOSED`, its terminal state. A message can also reach `CLOSED` without any explicit call: when a submitted claim is adjudicated `PAID` while its message stands `RESOLVED`, the message closes automatically (§3.6).

### 3.5. After-Hours Escalation and the On-Call Selector

Some messages cannot wait for the next staffed window. A `TriageNurse` or `Provider` may escalate a message standing in `TRIAGED`, `ASSIGNED`, or `IN_REVIEW` — any other state fails with `ERR_MESSAGE_INVALID_STATE` — by supplying a `reason`. Three gates then apply in order: the state gate just named; an urgency gate requiring `urgency` to be `URGENT` or `EMERGENT` (`ROUTINE` messages are rejected with `ERR_URGENCY_NOT_ESCALATABLE`); and the on-call selector, which must yield a provider or the escalation fails with `ERR_NO_ONCALL_COVERAGE`.

The selector is deterministic. Its candidates are staff members with `staff_type` `PROVIDER` who hold an on-call shift covering the logical now under closed-interval containment — `start_utc` at or before now and `end_utc` at or after now. Candidates are ranked by their covering shift's `start_utc`, earliest-starting first; ties break by the covering shift's `created_at`, earliest-created first; and any tie still remaining — possible only when two covering shifts share both stamps — breaks by the covering shift's `id`, smallest first. The provider's `id` never participates in ranking or tie-breaking. An empty candidate set is the `ERR_NO_ONCALL_COVERAGE` fallback above.

A successful escalation creates an `Escalation` resource in `OPEN` status with the reason, the message's `message_id`, and a `provider_id` chosen by the selector — the call therefore returns `201 Created`. The message itself moves to `ESCALATED` and its `assignee_id` becomes the on-call provider: the previous assignee, if any, loses one from their `open_inbox_count`, the on-call provider gains one, and `inbox_overloaded` is re-evaluated for both.

Acknowledgement closes the loop. The escalation must still be `OPEN` — an already-acknowledged one fails with `ERR_ESCALATION_INVALID_STATE` — and the caller must be the on-call provider named on it, with anyone else rejected as `ERR_NOT_ASSIGNEE`. The escalation moves to `ACKNOWLEDGED` with `acknowledged_at` stamped, and the message returns to `IN_REVIEW` with the assignee retained and counts unchanged, both being counted statuses. Escalation lists may be filtered by `message_id`, `provider_id`, and `status`.

### 3.6. E-Visit Billing: Determination, Consent, and the Claim Lifecycle

Billable e-visit determination is a provider-only judgment made on an `IN_REVIEW` message, carrying a `disposition` and the OCC field `expected_message_version` (§2.7). Two dispositions exist. A determination of `NOT_BILLABLE` keeps the message `IN_REVIEW`, sets `billing_disposition` to `NOT_BILLABLE`, supersedes any earlier `GRANTED` or `DECLINED` consent record on the message (moving it to `SUPERSEDED`), and increments the message `version` by one; it is refused while a consent request is still `REQUESTED` (`ERR_CONSENT_REQUEST_PENDING`) or while a claim for the message stands in `SUBMITTED` or `DENIED` (`ERR_CLAIM_IN_FLIGHT`) — note that a `DRAFT` claim does not block re-determination, though it does block closure.

A determination of `BILLABLE_CANDIDATE` runs a longer gauntlet of checks, evaluated in this order after the concurrency and state gates of §2.6: the message's `category` must be `CLINICAL`, else `ERR_CATEGORY_NOT_CLINICAL`; no other message of the same patient may hold `billing_disposition` `CHARGEABLE` with a `received_at` inside the trailing 168-hour window ending at this message's `received_at` — the lower bound is exclusive, so another chargeable message received exactly 168 hours earlier does not block, while one received any time after that moment, up to and including this message's own receipt instant, does — else `ERR_EVISIT_DUPLICATE_WITHIN_7_DAYS`; no consent record for this message may stand in `REQUESTED` (`ERR_CONSENT_REQUEST_PENDING`); no claim may stand in `SUBMITTED` or `DENIED` (`ERR_CLAIM_IN_FLIGHT`); and `clinical_minutes_total` must be at least five minutes, else `ERR_EVISIT_MINUTES_BELOW_MINIMUM`. On success, the message moves to `PENDING_CONSENT`, `billing_disposition` becomes `BILLABLE_CANDIDATE`, any prior `GRANTED` or `DECLINED` consent is superseded, and a fresh `ConsentRecord` is created in `REQUESTED` status with `patient_id` copied from the message, `requested_at` stamped from the logical clock, and — crucially — `disclosed_code` and `disclosed_fee_cents` pinned to the e-visit tier at the current `clinical_minutes_total`. Those disclosed values are version-pinned: later minute accrual does not rewrite what the patient was told, though it constrains the claim at submit time. Although a `BILLABLE_CANDIDATE` determination creates the `ConsentRecord`, the call itself records a decision on the message and therefore returns `200 OK` with the updated message — not the new consent record — in `data`.

The tier schedule maps provider clinical minutes to a code and fee in integer cents. Below five minutes, a message is not billable at all. Five through ten minutes — both bounds inclusive — selects `CPT_99421` with a 5000-cent fee. Eleven through twenty minutes, again inclusive at both ends, selects `CPT_99422` at 8000 cents. Twenty-one minutes or more selects `CPT_99423` at 12000 cents. Boundary values belong to the band containing them: ten minutes yields `CPT_99421`, eleven yields `CPT_99422`, twenty stays `CPT_99422`, and twenty-one moves to `CPT_99423`.

Consent belongs to the patient. Responding to their own `REQUESTED` consent — another patient's consent fails with `ERR_PATIENT_OWNERSHIP_MISMATCH`, and an already-answered record with `ERR_CONSENT_ALREADY_RESPONDED` — carries a `decision` of `GRANTED` or `DECLINED`. Granting sets the message's `billing_disposition` to `CHARGEABLE`; declining sets it to `NOT_BILLABLE`. Either way `responded_at` is stamped and the message returns from `PENDING_CONSENT` to `IN_REVIEW` with its assignee retained and counts unchanged, both being counted statuses. At most one consent record per message may stand in `REQUESTED` at any time. Consent lists support filtering by `message_id`, `patient_id`, and `status`.

With a chargeable message in hand, a `BillingSpecialist` opens the claim. Claim creation requires the message to stand in `RESOLVED` — else `ERR_MESSAGE_NOT_RESOLVED` — and to carry `billing_disposition` `CHARGEABLE`, meaning consent was granted and never superseded, else `ERR_MESSAGE_NOT_CHARGEABLE`. The remaining checks follow the §2.6 order: the named `rendering_provider_id` must reference a `PROVIDER` who logged at least one `CLINICAL_REVIEW` time entry on the message, else `ERR_RENDERING_PROVIDER_NOT_ON_THREAD`; no other claim for the message may stand in `DRAFT`, `SUBMITTED`, or `DENIED`, else `ERR_CLAIM_ALREADY_EXISTS`; `clinical_minutes_total` must be at least five (`ERR_EVISIT_MINUTES_BELOW_MINIMUM`); and the computed `fee_cents` must not exceed the `disclosed_fee_cents` on the message's granted, non-superseded consent, else `ERR_DISCLOSED_FEE_EXCEEDED`. At creation the server denormalizes `patient_id` from the message, computes `code` and `fee_cents` from the tier schedule above, computes `patient_responsibility_cents` as described next, and opens the claim in `DRAFT`.

Patient responsibility splits on the patient's cost-sharing model. Under `COPAY`, `patient_responsibility_cents` is the lesser of the patient's `copay_cents` and the claim's `fee_cents`. Under `COINSURANCE`, it is the lesser of `fee_cents` and the product of `fee_cents` and `coinsurance_pct` rounded half-up to integer cents. The rounding order of §2.10 applies: round per claim at creation or rework, then sum rounded values — never the reverse.

The claim lifecycle then runs through billing's hands. Submitting moves a `DRAFT` claim to `SUBMITTED` (any other state is `ERR_CLAIM_INVALID_STATE`), re-checks the disclosed-fee ceiling against the message's non-superseded consent record — the `GRANTED` one, or the `REQUESTED` one when a re-determination has since superseded the granted record and opened a fresh request — (`ERR_DISCLOSED_FEE_EXCEEDED`), stamps `submitted_at`, and debits the patient's `outstanding_billed_cents` by the claim's `patient_responsibility_cents`. Recording adjudication requires `SUBMITTED` and takes an `outcome`: `PAID` stamps `adjudicated_at`, credits `outstanding_billed_cents` back by the responsibility amount, and — when the message stands `RESOLVED` — cascades the message to `CLOSED`; `DENIED` additionally requires a `denial_reason` (absent it, `ERR_INVALID_REQUEST`), records the `denial_reason` on the claim, stamps `adjudicated_at`, leaves `outstanding_billed_cents` unchanged because a denied claim remains in the outstanding set, and — only while the message still stands `RESOLVED` — fires a three-hop cascade: the message moves from `RESOLVED` to `REOPENED` with `assignee_id` set to the claim's rendering provider, `reopen_count` incremented, and `response_due_at` cleared until the next triage; the rendering provider's `open_inbox_count` rises by one; and if that count reaches five or more their `inbox_overloaded` flips true. If the message has already left `RESOLVED` (for example, reopened by a patient reply), the claim still turns `DENIED` but no cascade fires and no count changes.

Denial is not the end. A `DENIED` claim may be returned to `DRAFT` via rework — from any other claim state, `ERR_CLAIM_INVALID_STATE`, a check that runs first — once the message has been worked back to `RESOLVED`; a rework attempted earlier fails with `ERR_MESSAGE_NOT_RESOLVED`. Rework recomputes `code`, `fee_cents`, and `patient_responsibility_cents` from the message's current `clinical_minutes_total`, which must again reach the five-minute floor, else `ERR_EVISIT_MINUTES_BELOW_MINIMUM` and the claim stays `DENIED`; it also clears `denial_reason`, does not re-evaluate the disclosed-fee ceiling (that ceiling is enforced at claim creation and re-checked at submit), and the patient's outstanding balance is credited by the old responsibility amount as the claim leaves the outstanding set. Alternatively, a claim in `DRAFT` or `DENIED` may be voided as a write-off; voiding from `DRAFT` leaves the outstanding balance untouched, while voiding from `DENIED` credits it by the responsibility amount. `PAID` and `VOID` are terminal.

The patient's `outstanding_billed_cents` is always the sum of `patient_responsibility_cents` over their claims standing in `SUBMITTED` or `DENIED`. This makes the conservation property plain: a submit followed by a payment nets zero, as does a denial followed by a void. Claim lists may be filtered by `message_id`, `patient_id`, `rendering_provider_id`, and `status`.

### 3.7. Patient Education and the Intake Gate

Appropriate-use education is the practice's lever against inbox misuse. A `TriageNurse` issues a `PatientEducationNotice` tied to the triggering message by `message_id` — the message may stand in any status, and issuing a notice does not alter it — choosing a `notice_kind` of `EMERGENT_MISUSE`, `PORTAL_SCOPE_GUIDANCE`, or `BILLING_EXPLAINER`, supplying the education `body`, and optionally setting `blocking` — which defaults to true when omitted. The server copies `patient_id` from the message and issues the notice in `ISSUED` status.

The gate arithmetic is deliberately simple: a patient's `education_gate_open` is true exactly when at least one of their notices has `blocking` true and `status` `ISSUED`, and it is recomputed whenever a notice is created or acknowledged. While the gate stands open, the patient's attempts to send a new portal message are refused with `ERR_EDUCATION_ACK_REQUIRED` until they have acknowledged what they were sent.

Acknowledgement is the patient's act, on their own notice (`ERR_PATIENT_OWNERSHIP_MISMATCH`), and only from `ISSUED` (`ERR_NOTICE_ALREADY_ACKNOWLEDGED`). It moves the notice to `ACKNOWLEDGED`, stamps `acknowledged_at`, and recomputes the gate, which closes as soon as no blocking `ISSUED` notices remain. Notice lists may be filtered by `message_id`, `patient_id`, and `status`, with `Patient` callers restricted to their own records per §2.1.

### 3.8. Measuring Provider Inbox Burden

Leadership reads workload through the burden summary, which is computed on read over all time — there is no window. The summary reports the staff member's stored `open_inbox_count` and `inbox_overloaded`, and adds three aggregates: `attributed_resolutions`, counting messages whose `resolved_by_id` names the staff member and whose `status` is `RESOLVED` or `CLOSED`; `touched_resolutions`, counting the distinct messages on which the staff member logged any time entry, whatever their current status and regardless of who — if anyone — resolved them; and `clinical_minutes`, the sum of `minutes` over the staff member's own `CLINICAL_REVIEW` entries. An optional `metric` query parameter names the counting perspective: `ATTRIBUTED`, the default, counts only messages the staff member personally resolved, while `TOUCHED` counts every message they logged time on — so a message resolved by another provider but worked by this one counts under `TOUCHED` and not under `ATTRIBUTED`. The summary always reports both aggregates regardless of `metric`; an unrecognized `metric` value is rejected with `ERR_INVALID_REQUEST`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; this includes escalation, which creates the `Escalation` record even though it also moves the message. Operations that modify an existing resource, record a decision, or merely read data return `200 OK`. Request and response bodies for every operation are reconstructed from the narratives of §2 and §3; the table below fixes only the HTTP contract and the authorized roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/inbox/patients` | Register a patient | PracticeAdmin |
| GET | `/inbox/patients/{id}` | Get a patient (Patient role: own record only) | PracticeAdmin, TriageNurse, FrontDesk, Provider, BillingSpecialist, Patient |
| POST | `/inbox/staff` | Create a staff member | PracticeAdmin |
| GET | `/inbox/staff/{id}` | Get a staff member | PracticeAdmin, TriageNurse, FrontDesk, Provider, BillingSpecialist |
| GET | `/inbox/staff/{id}/burden-summary` | Provider inbox burden measurement (both counting variants returned) | PracticeAdmin, TriageNurse, FrontDesk, Provider, BillingSpecialist |
| POST | `/inbox/pools` | Create a routing pool with response-time targets and deadline policy | PracticeAdmin |
| GET | `/inbox/pools/{id}` | Get a pool | PracticeAdmin, TriageNurse, FrontDesk, Provider, BillingSpecialist |
| POST | `/inbox/coverage-windows` | Create a coverage window (half-open interval, per-staff overlap check) | PracticeAdmin |
| GET | `/inbox/coverage-windows` | List coverage windows | PracticeAdmin, TriageNurse, FrontDesk, Provider, BillingSpecialist |
| GET | `/inbox/coverage-windows/{id}` | Get a coverage window | PracticeAdmin, TriageNurse, FrontDesk, Provider, BillingSpecialist |
| POST | `/inbox/on-call-shifts` | Create an on-call shift (closed interval, per-provider touch-is-overlap check) | PracticeAdmin |
| GET | `/inbox/on-call-shifts` | List on-call shifts | PracticeAdmin, TriageNurse, FrontDesk, Provider, BillingSpecialist |
| GET | `/inbox/on-call-shifts/{id}` | Get an on-call shift | PracticeAdmin, TriageNurse, FrontDesk, Provider, BillingSpecialist |
| POST | `/inbox/delegation-grants` | Delegate coverage of a PROVIDER_INBOX pool to another staff member | Provider |
| GET | `/inbox/delegation-grants` | List delegation grants | PracticeAdmin, TriageNurse, FrontDesk, Provider, BillingSpecialist |
| GET | `/inbox/delegation-grants/{id}` | Get a delegation grant | PracticeAdmin, TriageNurse, FrontDesk, Provider, BillingSpecialist |
| POST | `/inbox/delegation-grants/{id}/revoke` | Revoke a grant; cascade reassigns the delegate's in-flight messages in that pool to the delegator | Provider |
| POST | `/inbox/portal-messages` | Patient sends a portal message; blocked while the patient's education gate is open | Patient |
| GET | `/inbox/portal-messages` | List messages with filters (Patient role must pass own patient_id) | PracticeAdmin, TriageNurse, FrontDesk, Provider, BillingSpecialist, Patient |
| GET | `/inbox/portal-messages/{id}` | Get a message (Patient role: own only) | PracticeAdmin, TriageNurse, FrontDesk, Provider, BillingSpecialist, Patient |
| POST | `/inbox/portal-messages/{id}/triage` | Classify urgency and category and route to a pool; re-triage supersedes; OCC-guarded | TriageNurse |
| POST | `/inbox/portal-messages/{id}/assign` | Assign to a specific staff member or leave on the pool queue; re-route allowed from ASSIGNED | TriageNurse |
| POST | `/inbox/portal-messages/{id}/start-review` | Claim the message from its pool queue; pool-kind eligibility and active coverage required | TriageNurse, FrontDesk, Provider |
| POST | `/inbox/portal-messages/{id}/reply` | Staff reply (assignee only) or patient reply reopening an own RESOLVED message | Patient, TriageNurse, FrontDesk, Provider |
| POST | `/inbox/portal-messages/{id}/complete` | Assignee completes work; routes to PENDING_COSIGN when cosign is required, else RESOLVED | TriageNurse, FrontDesk, Provider |
| POST | `/inbox/portal-messages/{id}/cosign` | Provider cosigns (COSIGN) or returns (RETURN) a PENDING_COSIGN message | Provider |
| POST | `/inbox/portal-messages/{id}/escalate` | Escalate an URGENT or EMERGENT message to the on-call provider; creates the Escalation record | TriageNurse, Provider |
| POST | `/inbox/portal-messages/{id}/determine-billing` | Provider determines e-visit billability; BILLABLE_CANDIDATE creates a version-pinned consent request; OCC-guarded | Provider |
| POST | `/inbox/portal-messages/{id}/close` | Close a RESOLVED message with no claim in flight (terminal) | TriageNurse, Provider |
| POST | `/inbox/time-entries` | Log work minutes on a message in a working status (team-based care; not assignee-restricted) | TriageNurse, FrontDesk, Provider |
| GET | `/inbox/time-entries` | List time entries | PracticeAdmin, TriageNurse, FrontDesk, Provider, BillingSpecialist |
| GET | `/inbox/time-entries/{id}` | Get a time entry | PracticeAdmin, TriageNurse, FrontDesk, Provider, BillingSpecialist |
| POST | `/inbox/education-notices` | Issue a patient-education notice tied to a message; blocking notices open the education gate | TriageNurse |
| GET | `/inbox/education-notices` | List education notices (Patient role must pass own patient_id) | PracticeAdmin, TriageNurse, FrontDesk, Provider, BillingSpecialist, Patient |
| GET | `/inbox/education-notices/{id}` | Get an education notice (Patient role: own only) | PracticeAdmin, TriageNurse, FrontDesk, Provider, BillingSpecialist, Patient |
| POST | `/inbox/education-notices/{id}/acknowledge` | Patient acknowledges a notice; the gate closes when no blocking ISSUED notices remain | Patient |
| GET | `/inbox/consent-records` | List consent records (Patient role must pass own patient_id) | PracticeAdmin, TriageNurse, FrontDesk, Provider, BillingSpecialist, Patient |
| GET | `/inbox/consent-records/{id}` | Get a consent record (Patient role: own only) | PracticeAdmin, TriageNurse, FrontDesk, Provider, BillingSpecialist, Patient |
| POST | `/inbox/consent-records/{id}/respond` | Patient grants or declines the charge consent; message disposition and status update accordingly | Patient |
| POST | `/inbox/e-visit-claims` | Create a DRAFT claim from a RESOLVED and CHARGEABLE message; code, fee, and responsibility computed at creation | BillingSpecialist |
| GET | `/inbox/e-visit-claims` | List claims (Patient role must pass own patient_id) | PracticeAdmin, TriageNurse, FrontDesk, Provider, BillingSpecialist, Patient |
| GET | `/inbox/e-visit-claims/{id}` | Get a claim | PracticeAdmin, TriageNurse, FrontDesk, Provider, BillingSpecialist, Patient |
| POST | `/inbox/e-visit-claims/{id}/submit` | Submit a DRAFT claim; disclosed-fee ceiling re-checked; debits patient outstanding | BillingSpecialist |
| POST | `/inbox/e-visit-claims/{id}/record-adjudication` | Record payer adjudication; PAID credits outstanding and auto-closes a RESOLVED message; DENIED cascades a reopen to the rendering provider | BillingSpecialist |
| POST | `/inbox/e-visit-claims/{id}/rework` | Return a DENIED claim to DRAFT after the message is RESOLVED again; code, fee, and responsibility recomputed from current minutes | BillingSpecialist |
| POST | `/inbox/e-visit-claims/{id}/void` | Void a claim in DRAFT or DENIED (write-off); voiding from DENIED credits outstanding | BillingSpecialist |
| GET | `/inbox/escalations` | List escalations | PracticeAdmin, TriageNurse, FrontDesk, Provider, BillingSpecialist |
| GET | `/inbox/escalations/{id}` | Get an escalation | PracticeAdmin, TriageNurse, FrontDesk, Provider, BillingSpecialist |
| POST | `/inbox/escalations/{id}/acknowledge` | On-call provider acknowledges; the message moves from ESCALATED to IN_REVIEW | Provider |
| POST | `/inbox/_clock/set_current_utc` | Set the logical clock (startup default is exactly 2026-08-01T00:00:00Z; never falls back to wall-clock) | PracticeAdmin |
| POST | `/inbox/_sla/sweep` | Run the SLA sweep, persisting sla_breached for non-terminal messages past their deadline | PracticeAdmin |

## 5. Error Code Catalogue

The trigger condition for each error is defined in the narratives of §2 and §3; this catalogue fixes only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_ROLE_STAFF_MISMATCH` | 403 Forbidden |
| `ERR_PATIENT_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_MESSAGE_INVALID_STATE` | 409 Conflict |
| `ERR_CLAIM_INVALID_STATE` | 409 Conflict |
| `ERR_CONSENT_ALREADY_RESPONDED` | 409 Conflict |
| `ERR_NOTICE_ALREADY_ACKNOWLEDGED` | 409 Conflict |
| `ERR_GRANT_ALREADY_REVOKED` | 409 Conflict |
| `ERR_ESCALATION_INVALID_STATE` | 409 Conflict |
| `ERR_NOT_AWAITING_COSIGN` | 409 Conflict |
| `ERR_EDUCATION_ACK_REQUIRED` | 403 Forbidden |
| `ERR_MESSAGE_NOT_CHARGEABLE` | 409 Conflict |
| `ERR_MESSAGE_NOT_RESOLVED` | 409 Conflict |
| `ERR_NOT_AUTHORIZED_COSIGNER` | 403 Forbidden |
| `ERR_CATEGORY_NOT_CLINICAL` | 422 Unprocessable Entity |
| `ERR_POOL_ROLE_MISMATCH` | 403 Forbidden |
| `ERR_NOT_ASSIGNEE` | 403 Forbidden |
| `ERR_ONCALL_PROVIDER_TYPE` | 422 Unprocessable Entity |
| `ERR_INVALID_DELEGATION_TARGET` | 422 Unprocessable Entity |
| `ERR_RENDERING_PROVIDER_NOT_ON_THREAD` | 422 Unprocessable Entity |
| `ERR_NOT_GRANT_OWNER` | 403 Forbidden |
| `ERR_INVALID_TIME_RANGE` | 400 Bad Request |
| `ERR_COVERAGE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_ONCALL_SHIFT_OVERLAP` | 409 Conflict |
| `ERR_DELEGATION_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_NO_ACTIVE_COVERAGE` | 409 Conflict |
| `ERR_EVISIT_DUPLICATE_WITHIN_7_DAYS` | 409 Conflict |
| `ERR_URGENCY_NOT_ESCALATABLE` | 409 Conflict |
| `ERR_NO_ONCALL_COVERAGE` | 409 Conflict |
| `ERR_CONSENT_REQUEST_PENDING` | 409 Conflict |
| `ERR_CLAIM_ALREADY_EXISTS` | 409 Conflict |
| `ERR_CLAIM_IN_FLIGHT` | 409 Conflict |
| `ERR_EVISIT_MINUTES_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_DISCLOSED_FEE_EXCEEDED` | 422 Unprocessable Entity |
