# Tenant Rights Hotline API — Product Requirements Document

## 1. Introduction

A HUD-approved housing counseling agency operates a tenant-rights hotline whose callers are frequently in acute distress: a pay-or-quit notice taped to a door, a landlord who will not fix a failed heating system, a security deposit that was never returned. The hotline's value rests on three promises. The guidance a counselor reads aloud must be current and correct for the caller's exact jurisdiction. A caller facing imminent eviction must be followed up, not forgotten. And a caller's identity must be guarded with the same rigor as their case, because the tenants most in need of help are often those most exposed to retaliation.

This document specifies the API through which the agency's counselors, supervisors, privacy officers, administrators, and analysts deliver on those promises. The system covers pseudonymous caller registration and consent capture; call intake and triage across eviction, habitability, and deposit issues; jurisdiction-aware script governance that separates authorship from publication; interpreter booking for callers whose language no available counselor covers; case management with a computed priority score and a tiered follow-up cadence; dispatch of referrals to legal-aid organizations operating under weekly capacity limits; retention-policy-driven purge of personal data; and aggregated call-volume analytics that feed policy advocacy without ever exposing caller-identified records. A single logical clock governs every time-dependent rule in the system, and scheduled maintenance sweeps advance consent expirations, follow-up deadlines, referral service-level deadlines, and purge-job creation in a pinned order. All resources are mounted under the `/hotline` URL prefix; two operator-only capabilities for clock control and time sweeps live outside it.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, principles, and boilerplate that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry the `X-User-Role` header naming one of the declared roles and — for every role except `Anonymous` — the `X-User-ID` header identifying the acting party. The recognized roles, spelled exactly, are `Anonymous`, `Caller`, `Counselor`, `HotlineSupervisor`, `DataProtectionOfficer`, `AgencyAdmin`, and `Analyst`. A request whose role header is missing or names an undeclared role, or whose `X-User-ID` is missing where required, is rejected with `ERR_UNAUTHENTICATED`. Each endpoint admits a defined set of roles (see §4); an authenticated party attempting an operation outside that set is rejected with `ERR_FORBIDDEN`. Certain transitions are narrower than their endpoint's role list — case de-escalation, every transition to `CLOSED`, script retirement from `PUBLISHED`, and resource retirement are `HotlineSupervisor`-only even where the endpoint itself also admits counselors.

Role identity is interpreted as follows. When `X-User-Role` is `Caller`, `X-User-ID` is the `id` of the acting `Caller`; ownership checks on any caller-scoped resource compare the path's caller identifier — or a consent's `caller_id` — to `X-User-ID`. When `X-User-Role` is `Counselor`, `X-User-ID` is the `id` of the acting `Counselor`; ownership checks on scripts compare `author_counselor_id` to `X-User-ID`, and segregation-of-duties checks compare it against the relevant counterparty field. When `X-User-Role` is `Anonymous`, `HotlineSupervisor`, `DataProtectionOfficer`, `AgencyAdmin`, or `Analyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it where a transition writes the acting party, but it is never compared to any entity's `id`.

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

List endpoints paginate through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp in ascending order. The `meta` envelope of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource — jurisdictions, scripts, self-help resources, counselors, interpreters, callers, consents, call sessions, cases, follow-ups, legal-aid organizations, referrals, retention policies, and purge jobs — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID that serves as identity only and is never used in business decisions; it carries no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): starts at 1 at creation and increments by one on every mutation, including mutations caused by cascaded side effects originating elsewhere.

The single exception is the `CaseNote`. Case notes form an immutable, append-only log: a note carries only `id` and `created_at`; `updated_at` and `version` are absent entirely, and no update or delete operation exists for notes.

Beyond these common fields, most workflow resources carry a state field — named `status` on scripts, self-help resources, counselors, consents, cases, follow-ups, legal-aid organizations, referrals, retention policies, and purge jobs, and split into the parallel pair `session_status` and `interpretation_status` on call sessions — whose exact enumeration values are defined per entity in §3.

### 2.5. The Logical Clock and the Scheduled Time Sweep

All time-dependent behavior in the system reads a server-side logical clock, never wall-clock time. At startup, before any operator intervention, the logical clock reads exactly 2026-08-01T00:00:00Z. An `AgencyAdmin` may set the clock to a supplied `to_iso8601` instant; the response echoes the new reading as `current_utc`. Once set, the clock never falls back to wall-clock time on its own.

A second `AgencyAdmin`-only capability runs the time sweep at the current logical instant. One sweep advances every clock-driven transition in the system in a pinned processing order: consent expirations first, then follow-up due/missed evaluation in ascending `scheduled_for` order with ties broken by ascending `created_at`, then referral expirations in ascending `created_at` order, and finally purge-job creation for retention-eligible callers in ascending caller `created_at` order. The sweep response is a summary object with the counters `consents_expired`, `follow_ups_due`, `follow_ups_missed`, `referrals_expired`, and `purge_jobs_created`.

### 2.6. Optimistic Concurrency Control

Three write operations guard against lost updates through a client-supplied expectation of the parent resource's `version`. Appending a note to a case requires the request to carry `expected_case_version`; proposing a referral on a case likewise requires `expected_case_version`; and granting a consent on a caller requires `expected_caller_version`. In each case the supplied value must equal the parent resource's current `version` as the client last observed it. If the parent's version has advanced since that observation — because another writer appended a note, proposed a referral, edited case facts, or triggered a cascade that legitimately mutated the parent — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful guarded write itself advances the parent's `version` by one. No endpoint outside these three accepts a version field.

### 2.7. Numeric Precision, Rounding, and Units

Monetary amounts are represented as integer cents throughout. The deposit-exposure estimate rounds each of its components half-up to whole cents before summation, and that rounding order is pinned: summing unrounded components and rounding once at the end is non-conformant and yields different cents. The case priority score is an integer clamped to the inclusive range 0 to 100; where the score's eviction component is halved, the halving rounds down to a whole number of points. The escalation rate reported by analytics is a number rounded half-up to four decimal places, with a zero denominator yielding a rate of 0. Queue wait is reported in whole seconds. Interpreter booking windows are compared at minute granularity on their ISO timestamps, and consent/follow-up time-to-live checks evaluate at second granularity.

### 2.8. Nested Resource Retrieval and Path Validation

Requests that target nested resources are validated left-to-right along the path. The system confirms each path identifier in sequence — jurisdiction, caller, session, case, note parent, follow-up, organization, referral, script, resource, counselor, interpreter, consent, policy, or purge job — and rejects the request immediately with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource, before evaluating any later identifier or any business rule.

### 2.9. Cascades, Compensations, and Cross-Entity Consistency

State changes in this system rarely stay on one row. Publishing a script can supersede its predecessor, outdate every self-help resource derived from that predecessor, and cancel still-proposed referrals pointing at those resources — three links of one cascade. Revoking a consent can cancel scheduled follow-ups, bubble a waiting case back into active counseling, cancel legal-aid referrals, and release organization capacity slots. Every such cascade is atomic within the request that triggered it, and every resource mutated along the way — including resources mutated only as cascade targets — has its `updated_at` refreshed and its `version` incremented. Where an operation consumes a scarce resource, a defined compensating action releases it: referral dispatch consumes an organization's weekly slot, and decline, expiry, or cancellation releases it. Terminal states are absolute: a resource in a terminal state rejects every further transition, and a call session reaching a terminal state freezes both of its status dimensions. All state-transition operations across the system share one payload shape: the request names the desired target state in `to_status`, accompanied by any transition-specific fields the workflows of §3 define.

### 2.10. The Validation Pipeline and Its Priority Order

When several checks could reject the same request, the server evaluates them in a fixed priority order and the first failing check determines the error returned; ordering matters because an early rejection masks later ones.

1. **Authentication.** `X-User-Role` must be present and name a declared role, and `X-User-ID` must be present for every role except `Anonymous` — otherwise `ERR_UNAUTHENTICATED`.
2. **Authorization and ownership.** The role must be admitted by the endpoint, transition-level actor restrictions apply (de-escalation, closure, and retirement transitions are supervisor-only), a `Caller` may act only on their own record, a counselor may submit or withdraw only their own scripts, and the actor recording a training certification must differ from the subject counselor — otherwise `ERR_FORBIDDEN`.
3. **Segregation of duties.** Script publication requires a reviewer who is not the author, and case verification requires a verifier who is not the opener — otherwise `ERR_SCRIPT_REVIEWER_CONFLICT`.
4. **Existence.** Path identifiers must exist, validated left-to-right — otherwise `ERR_NOT_FOUND`.
5. **Schema and shape.** Required fields must be present, unknown payload fields are rejected, enums must be members, and types must match — otherwise `ERR_INVALID_REQUEST`. This family also covers the 422 variants: jurisdiction level/parent inconsistency (`ERR_JURISDICTION_LEVEL_MISMATCH`) and referral type/target incoherence (`ERR_REFERRAL_TARGET_MISMATCH`). An anonymous caller registered with a non-null phone, or a case whose `caller_id` does not equal the referenced session's caller, fails here as `ERR_INVALID_REQUEST`.
6. **Optimistic concurrency.** A stale `expected_case_version` or `expected_caller_version` is rejected with `ERR_STALE_VERSION` — before any state-machine question is considered.
7. **State-machine legality.** The requested transition must be listed for the resource's current state, terminal states reject everything, a session cannot go active while an interpreter request is pending, a case can only be opened from a session that is active or wrapped up, notes and referrals attach only to cases in an open counseling state, and manual escalation is reserved for critical cases — otherwise `ERR_INVALID_STATE`.
8. **Verification gate.** Manual escalation additionally requires the case to be verified — otherwise `ERR_CASE_NOT_VERIFIED`.
9. **Safety and compliance gates**, evaluated in this order: an anonymous caller receiving a follow-up or granting follow-up consent (`ERR_ANONYMOUS_FOLLOW_UP_FORBIDDEN`); an action on a caller whose PII has been purged (`ERR_CALLER_PII_PURGED`); a counselor who is not active (`ERR_COUNSELOR_INACTIVE`); an expired counselor certification (`ERR_CERTIFICATION_EXPIRED`); counselor training not current on the published script (`ERR_TRAINING_NOT_CURRENT`); a counselor/caller language gap without a connected interpreter (`ERR_LANGUAGE_UNSUPPORTED`); and an interpreter whose language does not match the caller's (`ERR_INTERPRETER_LANGUAGE_MISMATCH`).
10. **Temporal deadlines and windows.** Dispatch after the service-level deadline (`ERR_SLA_BREACHED`), a follow-up scheduled too close to a sibling (`ERR_FOLLOW_UP_TOO_SOON`), and purge before retention expiry (`ERR_RETENTION_NOT_EXPIRED`).
11. **Referenced-entity state.** Missing or lapsed legal-aid-release consent (`ERR_CONSENT_REQUIRED`), no published script for the pair (`ERR_SCRIPT_NOT_PUBLISHED`), a self-help resource that is not current (`ERR_RESOURCE_OUTDATED`), a paused organization (`ERR_ORG_NOT_ACCEPTING`), an organization that does not cover the case's jurisdiction and category (`ERR_ORG_COVERAGE_MISMATCH`), and resolution with open follow-ups or referrals (`ERR_CASE_HAS_OPEN_ITEMS`).
12. **Aggregate and constraint rules last.** Buffered interpreter overlap (`ERR_INTERPRETER_OVERLAP`), a previously failed interpreter (`ERR_INTERPRETER_PREVIOUSLY_FAILED`), exhausted weekly organization capacity (`ERR_ORG_CAPACITY_FULL`), a duplicate published script for the pair (`ERR_DUPLICATE_PUBLISHED_SCRIPT`), and a broken supersession chain (`ERR_SCRIPT_VERSION_CHAIN_BROKEN`).

### 2.11. Confidentiality and Pseudonymity Commitments

Real names are never stored: a caller is known to the system only through an `alias`. Callers who opt into anonymity cannot be called back, cannot grant follow-up consent, and cannot be followed up. Notes flagged confidential are excluded from anything exported toward the caller. A caller who withdraws data-sharing consent disappears from every analytics denominator. And at the end of the retention lifecycle, an executed purge irreversibly scrubs the callback number and alias. Privacy operations are segregated from counseling: retention policies and purge execution belong to the `DataProtectionOfficer`, who cannot modify cases or sessions, while counseling staff cannot execute purges.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Jurisdictions, Counselors, Interpreters, and Legal-Aid Organizations

Before the hotline can answer a single call, an `AgencyAdmin` seeds the reference data. A **jurisdiction** is created with a unique `code` (for example `CA`, `CA-LA`, or `CA-LA-001`), a display `name`, a `level` of `STATE`, `COUNTY`, or `CITY`, and the statutory parameters that drive triage and scoring: `eviction_notice_days` (the statutory minimum pay-or-quit notice period), `habitability_repair_days` (the landlord's cure period for habitability complaints), `deposit_cap_months` (the security-deposit cap expressed as a multiple of monthly rent, such as 1.5), `deposit_interest_required`, and `deposit_interest_rate_pct` (the annual rate in percent, ignored when interest is not required). The hierarchy is anchored through `parent_jurisdiction_id`: a `STATE` has a null parent, a `COUNTY`'s parent must be a `STATE`, and a `CITY`'s parent must be a `COUNTY`; any mismatch is rejected with `ERR_JURISDICTION_LEVEL_MISMATCH` (HTTP 422). The level of a child is always exactly one deeper than its parent, and because the hierarchy is create-only — no re-parenting endpoint exists — cycles are structurally impossible.

Counselors join the roster with a `display_name`, the `languages` they can serve without an interpreter, the `certified_jurisdiction_codes` they are HUD-certified to counsel on, their `certified_categories`, and a `certification_expires_at` timestamp; assignment and session start both require that expiry to lie after the current logical time. The `is_script_reviewer` flag (defaulting to false) qualifies a counselor to review and publish scripts. A new counselor starts `ACTIVE` with `trained_script_ids` empty. An administrator update can refresh any profile field, renew the certification, or move the counselor `ACTIVE` → `SUSPENDED` → `ACTIVE`, or from either `ACTIVE` or `SUSPENDED` to the terminal `INACTIVE`.

Training is recorded per script version: a `HotlineSupervisor` submits the `script_id` and the achieved `score`, and the acting supervisor's identifier must differ from the subject counselor's (`ERR_FORBIDDEN` otherwise). When the `score` is at least 80 and the named script is `PUBLISHED` or `SUPERSEDED`, the script id is appended to the counselor's `trained_script_ids`, idempotently within the array. Interpreters are registered more simply, with a `display_name` and the single `language_code` they cover.

A **legal-aid organization** is registered with a `name`, the `covered_jurisdiction_codes` it serves, the `accepted_categories` it takes, and a `weekly_capacity` bounding new referrals dispatched per ISO week. Organizations start `ACTIVE`; an administrator may pause one (`ACTIVE` → `PAUSED`), reactivate it, or adjust `weekly_capacity`. A `PAUSED` organization rejects new dispatches with `ERR_ORG_NOT_ACCEPTING`, while referrals already in flight as `DISPATCHED` are unaffected.

### 3.2. Script Governance: Authoring, Review, and the Publication Chain

Counselor-facing guidance lives in versioned **rights scripts**, one chain per pairing of jurisdiction and issue category (`EVICTION`, `HABITABILITY`, or `DEPOSIT`). A `Counselor` authors a new version by supplying `jurisdiction_id`, `issue_category`, `version_no`, the counselor-facing `body` text, and — for every version after the first — the `supersedes_script_id` of the currently published version it replaces. The new script is born `DRAFT`, and `author_counselor_id` is taken from the author's `X-User-ID`. Version numbering is monotonic within a chain: when superseding, `version_no` must equal the superseded script's `version_no` plus one; otherwise it must be 1.

Only the author can submit a draft for review, moving it `DRAFT` → `IN_REVIEW` (an actor whose `X-User-ID` differs from `author_counselor_id` is rejected with `ERR_FORBIDDEN`). A reviewer — a counselor with `is_script_reviewer` set to true — may return the script `IN_REVIEW` → `DRAFT` for rework, or publish it.

Publication is the most heavily guarded transition in the system, and its checks evaluate in the pipeline order of §2.10. The publisher must hold `is_script_reviewer` and must not be the author — segregation of duties, enforced as `ERR_SCRIPT_REVIEWER_CONFLICT`. The payload's `effective_from` must be present, must not lie after the current logical time, and, when the script supersedes another, must be strictly after the superseded script's `effective_from`; violations surface as `ERR_INVALID_REQUEST`. When `supersedes_script_id` is set, its target must be `PUBLISHED` at publish time, must belong to the same (`jurisdiction_id`, `issue_category`) pair, and the new `version_no` must be exactly one greater than the target's — a chain break is rejected with `ERR_SCRIPT_VERSION_CHAIN_BROKEN`. When `supersedes_script_id` is null, `version_no` must be 1 and no other `PUBLISHED` script may exist for the pair, or the publish fails with `ERR_DUPLICATE_PUBLISHED_SCRIPT`.

A successful publish writes `reviewer_counselor_id` from the publisher's `X-User-ID` and sets the script `PUBLISHED`. The cascade then runs in three links: the superseded script (if any) moves to `SUPERSEDED` with its `effective_until` set to the new script's `effective_from`; every self-help resource still `CURRENT` whose `linked_script_id` names the superseded script becomes `OUTDATED`; and every referral still `PROPOSED` that references one of those newly outdated resources is `CANCELLED` with `cancel_reason` `SCRIPT_OUTDATED`. Two invariants are conserved across every publish pair: at most one script per (`jurisdiction_id`, `issue_category`) pair is `PUBLISHED` at any time, and the half-open windows from `effective_from` (inclusive) to `effective_until` (exclusive) across a chain never overlap and never gap — each superseded window's `effective_until` equals its successor's `effective_from`. The current script for a pair at an instant is selected as the `PUBLISHED` script whose `effective_from` is on or before that instant and whose `effective_until` is either null or strictly after it; the invariants make that selection unique.

Retirement closes the chain. A `HotlineSupervisor` may retire a `PUBLISHED` script, which runs the same second and third cascade links — linked `CURRENT` resources become `OUTDATED` and their `PROPOSED` referrals cancel with `SCRIPT_OUTDATED` — while call sessions that already pinned the script keep their `pinned_script_id` unchanged, grandfathered for audit. The author alone may also withdraw a `DRAFT` to `RETIRED`. `SUPERSEDED` and `RETIRED` are terminal.

### 3.3. Self-Help Resources and Content Currency

Caller-facing self-help content rides on the script chain. A `Counselor` or `HotlineSupervisor` creates a resource with `jurisdiction_id`, `issue_category`, a `title`, the caller-facing `body`, the content's ISO `language_code`, and the `linked_script_id` of the script version it derives from; the linked script must be `PUBLISHED` at link time, or creation fails with `ERR_SCRIPT_NOT_PUBLISHED`. A resource starts `CURRENT`.

Content currency is enforced by the cascade of §3.2: when the linked script is superseded or retired, the resource flips `CURRENT` → `OUTDATED` with no human intervention, and any `PROPOSED` referral pointing at it is cancelled with `cancel_reason` `SCRIPT_OUTDATED`. An outdated resource is refreshed back to `CURRENT` by supplying a new `linked_script_id` naming a `PUBLISHED` script for the resource's own (`jurisdiction_id`, `issue_category`) pair — `ERR_SCRIPT_NOT_PUBLISHED` if none qualifies — which updates `linked_script_id` in place. A `HotlineSupervisor` may retire a resource from either `CURRENT` or `OUTDATED`; either way, referrals still `PROPOSED` against it are cancelled with `cancel_reason` `OPERATOR`.

### 3.4. Caller Intake, Pseudonymity, and Consent

Intake is public. An unauthenticated caller — role `Anonymous` — registers with a pseudonymous `alias`, an optional `phone` callback number, a `preferred_language`, a contact `channel` of `PHONE`, `CHAT`, `TTY`, or `VIDEO`, optional `accessibility_needs` flags such as TTY, ASL, or LARGE_PRINT (defaulting to an empty list), and the `is_anonymous` flag. Anonymous callers must have a null `phone`; a non-null value is rejected as `ERR_INVALID_REQUEST`. New callers begin with `pii_purged` false and `do_not_aggregate` false. The caller entity has no status enumeration; its `version` and `updated_at` advance when consent grants, revocations, or purge side effects mutate it.

Consent is granular and self-expiring. A `Caller` grants a consent on their own record by naming a `consent_type` — `RECORDING`, `FOLLOW_UP`, `LEGAL_AID_RELEASE`, or `DATA_SHARING` — together with the optimistic-concurrency field `expected_caller_version` (see §2.6). The record is created `GRANTED` with `granted_at` set to the current logical time and `expires_at` computed as `granted_at` plus the type's time-to-live: seven days for `RECORDING`, thirty days for `FOLLOW_UP`, ninety days for `LEGAL_AID_RELEASE`, and three hundred sixty-five days for `DATA_SHARING`. Each grant increments the caller's `version` by one. Two guards apply at grant time: a `FOLLOW_UP` grant for an anonymous caller is refused with `ERR_ANONYMOUS_FOLLOW_UP_FORBIDDEN` (HTTP 422), and any grant for a caller whose PII has been purged is refused with `ERR_CALLER_PII_PURGED`. Purged callers likewise cannot intake new sessions or open new cases.

Revocation is immediate and cascaded. The caller themself (whose `X-User-ID` must equal the consent's `caller_id`, else `ERR_FORBIDDEN`) or a `DataProtectionOfficer` revokes a `GRANTED` consent, stamping `revoked_at` and bumping the caller's `version`. The cascade depends on the type. A revoked `FOLLOW_UP` consent cancels every `SCHEDULED` follow-up on the caller's cases, and any of those cases sitting in `PENDING_FOLLOW_UP` with no remaining non-terminal follow-ups bubbles back to `IN_PROGRESS`. A revoked `LEGAL_AID_RELEASE` consent cancels `PROPOSED` and `DISPATCHED` legal-aid referrals on the caller's cases with `cancel_reason` `CONSENT_REVOKED`, and each `DISPATCHED` cancellation releases its organization slot, decrementing the reserved count by one. A revoked `DATA_SHARING` consent sets the caller's `do_not_aggregate` true, excluding them from analytics denominators.

Expiry is the sweep's mirror of revocation. When the logical clock moves strictly past a consent's `expires_at`, the record transitions `GRANTED` → `EXPIRED`; exactly at `expires_at` it remains `GRANTED`. The `FOLLOW_UP` and `DATA_SHARING` cascades are identical to revocation's. The `LEGAL_AID_RELEASE` cascade is deliberately narrower on expiry: only `PROPOSED` referrals are cancelled, with `cancel_reason` `CONSENT_EXPIRED`, while `DISPATCHED` referrals are allowed to conclude. `REVOKED` and `EXPIRED` are both terminal.

### 3.5. Call Sessions: Triage, Assignment, and Interpreter Coordination

A call session begins at intake — again through the public `Anonymous` channel — with a `caller_id`, the triaged `jurisdiction_id`, the triage outcome `issue_category`, and optional `triage_notes`. The session is born with `session_status` `QUEUED` and `interpretation_status` `NOT_REQUIRED`: two independent dimensions carried on one row, and the session may not go active while an interpreter request is in flight.

Assignment moves the session `QUEUED` → `ASSIGNED` under a `Counselor` or `HotlineSupervisor`, naming the target counselor in the payload's `counselor_id`. Four gates apply: the counselor must be `ACTIVE` (`ERR_COUNSELOR_INACTIVE`); the counselor's `certification_expires_at` must lie after the current logical time (`ERR_CERTIFICATION_EXPIRED`); the counselor's `certified_jurisdiction_codes` must contain the session jurisdiction's `code` and `certified_categories` must contain the session's `issue_category`, with a wrong certification scope rejected as `ERR_INVALID_REQUEST`; and a `PUBLISHED` script must exist for the session's (`jurisdiction_id`, `issue_category`) pair whose id appears in the counselor's `trained_script_ids` (`ERR_TRAINING_NOT_CURRENT`). Language compatibility is deliberately not evaluated at assignment — it is a start-time gate.

Starting the session (`ASSIGNED` → `ACTIVE`) re-evaluates the live gates: the interpretation dimension must not be `REQUESTED` (`ERR_INVALID_STATE` — a session cannot start while awaiting an interpreter); the assigned counselor must be `ACTIVE` at this moment (`ERR_COUNSELOR_INACTIVE`) with unexpired certification (`ERR_CERTIFICATION_EXPIRED`); and the language rule fires — either the counselor's `languages` contain the caller's `preferred_language`, or the interpretation dimension stands at `CONNECTED`, failing which the start is rejected with `ERR_LANGUAGE_UNSUPPORTED`. The training gate repeats against the currently published script: none published for the pair yields `ERR_SCRIPT_NOT_PUBLISHED`, and a counselor whose `trained_script_ids` lacks it yields `ERR_TRAINING_NOT_CURRENT`. On a successful start, `actual_start_at` is stamped from the logical clock, `queue_wait_seconds` is computed as the whole-second difference between `actual_start_at` and `created_at` (sessions that never reach `ACTIVE` report 0), and `pinned_script_id` is set to the current published script for the pair per the §3.2 selector. Later supersession never rewrites the pin — the record of which script guided the call is permanent.

From `ACTIVE`, the session ends `WRAPPED_UP` when the counseling completes or `DROPPED` when the line is lost; both stamp `actual_end_at`. A caller who hangs up before service moves the session from `QUEUED` or `ASSIGNED` to `ABANDONED`. `WRAPPED_UP`, `DROPPED`, and `ABANDONED` are terminal, and reaching any of them freezes both status dimensions.

The interpretation dimension runs its own small machine. While the session is `QUEUED` or `ASSIGNED` (otherwise `ERR_INVALID_STATE`), an interpretation request moves it `NOT_REQUIRED` → `REQUESTED`, naming an `interpreter_id` and a booking window from `scheduled_start_at` to `scheduled_end_at`. The interpreter's `language_code` must equal the caller's `preferred_language` (`ERR_INTERPRETER_LANGUAGE_MISMATCH`); the window's end must be strictly after its start (`ERR_INVALID_REQUEST`); and the window must survive the buffered-overlap check against the interpreter's existing book — every other session of the same interpreter whose interpretation stands at `REQUESTED` or `CONNECTED` while the session itself is `QUEUED`, `ASSIGNED`, or `ACTIVE`. Windows are half-open, and a ten-minute buffer is added to each end: a conflict exists when the new window's start is earlier than an existing window's end plus ten minutes and the existing window's start is earlier than the new window's end plus ten minutes. Consequently a back-to-back booking conflicts, while one starting exactly ten minutes after an existing window's end does not; a conflict is rejected with `ERR_INTERPRETER_OVERLAP`. Once requested, the bridge either connects — `REQUESTED` → `CONNECTED` — or fails. A failure (`REQUESTED` → `FAILED`) appends the interpreter to the session's `failed_interpreter_ids` and clears the booked window. A retry (`FAILED` → `REQUESTED`) must name an interpreter absent from `failed_interpreter_ids` (`ERR_INTERPRETER_PREVIOUSLY_FAILED`) and passes the same language, window, and overlap checks as the initial request. Finally, the caller may opt to proceed without an interpreter, returning the dimension `FAILED` → `NOT_REQUIRED`.

### 3.6. Case Facts, Verification, and the Priority Score

A case is opened from a call session that is `ACTIVE` or `WRAPPED_UP` — opening from any other session state is rejected with `ERR_INVALID_STATE` — by a `Counselor` or `HotlineSupervisor` supplying `caller_id`, `opened_from_session_id`, `jurisdiction_id`, `issue_category`, and any known facts: `eviction_notice_date` (the ISO date of the eviction deadline stated on the notice), `notice_served_at`, `habitability_reported_at`, `deposit_amount_cents`, `monthly_rent_cents`, `deposit_days_held`, and `legal_hold` (default false). The case's `caller_id` must equal the referenced session's caller, failing `ERR_INVALID_REQUEST`. The opener is recorded in `opened_by_counselor_id` from `X-User-ID`. The case starts `OPEN` with `score_variant` `PROVISIONAL`, and `priority_score`, `urgency_tier`, `required_follow_up_count`, and `deposit_exposure_cents` are computed in the same request.

The **priority score** accumulates components onto a base of zero, in a pinned order. First the eviction component, which applies only when `eviction_notice_date` is set: the number of whole calendar days from the current date to the stated deadline — which may be negative when the deadline has already passed — selects a tier: five days or fewer contributes 50 points; more than five but at most fourteen days contributes 30 points; more than fourteen but at most thirty days contributes 15 points; and more than thirty days contributes nothing. Under the `VERIFIED` variant only, a defective-notice halving then applies to that contribution: when `notice_served_at` is set, the notice period actually given is the whole days between the served date and the stated deadline, and if that period is shorter than the jurisdiction's `eviction_notice_days`, the eviction contribution is halved, rounding down to a whole number of points. Second, the habitability component, which applies when `habitability_reported_at` is set: if the issue has stood unremedied for strictly more than twice the jurisdiction's `habitability_repair_days`, 25 points are added; if it has stood for strictly more than the repair period but at most twice that period, 15 points are added. Third, the deposit component: when both `deposit_amount_cents` and `monthly_rent_cents` are set and the deposit exceeds the monthly rent multiplied by the jurisdiction's `deposit_cap_months`, 10 points are added. Fourth, history: five points per missed follow-up (`missed_follow_up_count`), plus — under the `VERIFIED` variant only — eight points per recorded escalation (`escalation_level`). The final `priority_score` is the accumulated base clamped to the inclusive range 0 to 100.

The two variants differ only in what they trust. `PROVISIONAL` — scored at intake and on every fact edit before verification — is built on self-reported facts alone: it ignores `notice_served_at` (no defective-notice halving) and ignores `escalation_level`. `VERIFIED` applies the halving and the escalation history, so identical stored facts can yield a different score once verified.

The **urgency tier** maps the score immediately, in the same request: a score of at least 70 is `CRITICAL`, at least 40 is `ELEVATED`, and anything lower is `STANDARD`. Boundaries are inclusive-up — exactly 70 is `CRITICAL`, exactly 40 is `ELEVATED`, exactly 39 is `STANDARD`. The tier in turn fixes the follow-up cadence: `required_follow_up_count` is 1 for `STANDARD`, 2 for `ELEVATED`, and 3 for `CRITICAL`. The evaluation order score → tier → required count is pinned, which is what breaks the otherwise-circular dependency: missed follow-ups raise the next score recompute, a higher tier raises the required count, but each existing follow-up is always classified against the `required_count_at_schedule` captured when it was scheduled — a tier change never retroactively reclassifies an existing follow-up.

The **deposit exposure estimate** answers how much money is at stake, computed whenever `deposit_amount_cents`, `monthly_rent_cents`, and `deposit_days_held` are all set — otherwise `deposit_exposure_cents` is null. Rounding is pinned per component, each rounded half-up to whole cents before any summation: the statutory cap in cents is the monthly rent multiplied by the jurisdiction's `deposit_cap_months`, rounded half-up; the over-cap portion is the excess of the deposit over that cap, floored at zero; interest applies only when the jurisdiction's `deposit_interest_required` is true, computed as the deposit times the jurisdiction's `deposit_interest_rate_pct` times `deposit_days_held`, divided by 36500 and rounded half-up; and the penalty portion is the over-cap portion multiplied by 1.5, rounded half-up. `deposit_exposure_cents` is the sum of the over-cap portion, the interest, and the penalty.

Fact edits arrive through a case update carrying any subset of the fact fields; each edit recomputes score, tier, cadence, and exposure under the variant currently in force and increments the case's `version`. Edits to a `CLOSED` case are rejected with `ERR_INVALID_STATE`, with one carve-out: a `legal_hold`-only toggle is permitted on a closed case, because litigation holds legitimately attach after closure.

Verification is the second pair of eyes. A `Counselor` or `HotlineSupervisor` whose identifier differs from `opened_by_counselor_id` verifies the case — segregation of duties, enforced as `ERR_SCRIPT_REVIEWER_CONFLICT` — which records the verifier in `verified_by_counselor_id`, flips `score_variant` to `VERIFIED`, and immediately recomputes the score under the verified variant.

### 3.7. The Follow-Up Cadence, Escalation, and Case Closure

Moving a case `OPEN` → `IN_PROGRESS` requires a `PUBLISHED` rights script for the case's (`jurisdiction_id`, `issue_category`) pair — there is no counseling without current, accurate information, and its absence is rejected with `ERR_SCRIPT_NOT_PUBLISHED`.

Follow-ups pace the engagement. A follow-up is scheduled on a case in `IN_PROGRESS`, `PENDING_FOLLOW_UP`, or `ESCALATED` — other states reject with `ERR_INVALID_STATE` — with a `scheduled_for` instant that must lie strictly after the current logical time (a past instant is `ERR_INVALID_REQUEST`) and must stand at least 24 hours away from every other non-terminal follow-up on the same case: a gap of strictly less than 24 hours is rejected with `ERR_FOLLOW_UP_TOO_SOON`, while exactly 24 hours passes. Scheduling for a case whose caller is anonymous is refused with `ERR_ANONYMOUS_FOLLOW_UP_FORBIDDEN`. A new follow-up starts `SCHEDULED`, pins `required_count_at_schedule` to the case's then-current `required_follow_up_count`, and — when the case was `IN_PROGRESS` — auto-transitions the case to `PENDING_FOLLOW_UP`.

The sweep advances follow-ups through their deadlines: a `SCHEDULED` follow-up becomes `DUE` when the logical time is on or after `scheduled_for` (the boundary is inclusive), and a `DUE` follow-up becomes `MISSED` when the logical time is strictly more than 48 hours past `scheduled_for` — exactly at the 48-hour edge it stays `DUE`. A single sweep may walk one follow-up through both transitions.

Completion is a human act: a `Counselor` or `HotlineSupervisor` moves a `DUE` follow-up to `COMPLETED` with a mandatory `outcome` text (`ERR_INVALID_REQUEST` if absent), stamping `completed_at`. Two cascade links follow: a system-generated `CaseNote` — `system_generated` true, `counselor_id` null — is appended to the parent case, bumping the case's `version`; and if the case was `PENDING_FOLLOW_UP` and no other non-terminal follow-ups remain, it bubbles back to `IN_PROGRESS`. Cancellation of a `SCHEDULED` follow-up, whether manual or by cascade (consent revocation or expiry, or de-escalation), performs the same bubble-up.

A miss is the serious event. The case's `missed_follow_up_count` increases by one, and the priority score is recomputed with the five-points-per-miss history component. If the recompute crosses into `CRITICAL`, `required_follow_up_count` updates for future scheduling only — existing follow-ups keep their `required_count_at_schedule`. And when the case is `VERIFIED`, the new tier is `CRITICAL`, and the case sits in `IN_PROGRESS` or `PENDING_FOLLOW_UP`, the system auto-escalates it with exactly the same side effects as a manual escalation; a case already `ESCALATED` does not re-escalate, and an unverified case recomputes its score but does not auto-escalate.

Manual escalation moves `IN_PROGRESS` → `ESCALATED` and is reserved for the worst cases: `score_variant` must be `VERIFIED` (`ERR_CASE_NOT_VERIFIED`) and `urgency_tier` must be `CRITICAL` (`ERR_INVALID_STATE` — only imminent-eviction-grade cases escalate manually). Escalation increments `escalation_level` by one, stamps `last_escalated_at`, auto-creates a follow-up scheduled 24 hours out with `auto_created` true and `required_count_at_schedule` pinned from the case, and appends a system-generated case note recording the event (which bumps the case's `version`). De-escalation back to `IN_PROGRESS` is a `HotlineSupervisor`-only act and carries the compensating half: every `SCHEDULED` follow-up with `auto_created` true is cancelled.

Resolution requires a clean desk. From `IN_PROGRESS`, `PENDING_FOLLOW_UP`, or `ESCALATED`, a case may move to `RESOLVED` only when no follow-up stands in `SCHEDULED` or `DUE` and no referral stands in `PROPOSED` or `DISPATCHED` — otherwise `ERR_CASE_HAS_OPEN_ITEMS`. A resolved case may be reopened to `IN_PROGRESS`, which recomputes `priority_score` while retaining the accumulated `missed_follow_up_count`. Closure is supervisor-only in both its forms: `RESOLVED` → `CLOSED` after resolution, and `OPEN` → `CLOSED` as a no-merit close; either way `closed_at` is stamped from the logical clock, anchoring retention eligibility. `CLOSED` is terminal.

The case's working record is its note log. A `Counselor` or `HotlineSupervisor` appends a note under a case — the note's `case_id` comes from the path — with a `body`, an `is_confidential` flag (confidential notes are excluded from caller-facing exports), and the `expected_case_version` guard of §2.6 — a stale expectation is rejected with `ERR_STALE_VERSION`, and a successful append increments the case's `version` by one. The note's `counselor_id` is taken from the actor's `X-User-ID`, except on system-generated notes where it is null. Notes may only be appended while the case is in an open counseling state; an append against a case that has left those states is rejected with `ERR_INVALID_STATE`. Notes are immutable once written — there is no edit and no delete — and a quality-review read lets a `HotlineSupervisor` or `DataProtectionOfficer` list all notes authored by a given counselor across cases.

### 3.8. Referrals: Legal-Aid Dispatch and Self-Help Signposting

A referral commits case facts to an outside hand, so it is proposed on a case in `IN_PROGRESS`, `PENDING_FOLLOW_UP`, or `ESCALATED` (otherwise `ERR_INVALID_STATE`) under the `expected_case_version` guard of §2.6. The proposal names a `referral_type` of `LEGAL_AID` or `SELF_HELP`, and the target must cohere with the type: `LEGAL_AID` requires a `legal_aid_org_id` and forbids a `self_help_resource_id`; `SELF_HELP` requires the reverse. Incoherence is rejected with `ERR_REFERRAL_TARGET_MISMATCH` (HTTP 422). For a legal-aid referral, the organization must cover the case's jurisdiction and category through its `covered_jurisdiction_codes` and `accepted_categories` (`ERR_ORG_COVERAGE_MISMATCH`, HTTP 422), and the caller must hold a `GRANTED` `LEGAL_AID_RELEASE` consent — absent, expired, or revoked consent fails with `ERR_CONSENT_REQUIRED`. For a self-help referral, the resource must be `CURRENT`; an `OUTDATED` or `RETIRED` resource fails with `ERR_RESOURCE_OUTDATED`. A created referral records its `case_id` from the path and stands at `PROPOSED`, and its dispatch deadline `sla_dispatch_by` is set at creation from the case's tier at proposal time: 24 hours for `CRITICAL`, 72 hours for `ELEVATED`, 168 hours for `STANDARD`. Creating the referral increments the case's `version` by one.

Dispatch (`PROPOSED` → `DISPATCHED`) races the service-level clock: it must occur on or before `sla_dispatch_by`, or it fails with `ERR_SLA_BREACHED`. For legal aid, the organization must be `ACTIVE` (`ERR_ORG_NOT_ACCEPTING`) and must have headroom — its `current_week_reserved` must be strictly below its `weekly_capacity`, with equality rejected as `ERR_ORG_CAPACITY_FULL` and a count one below capacity taking the last slot. A successful dispatch stamps `dispatched_at` from the logical clock — which fixes the referral's ISO week for capacity accounting — sets `accept_by` to 96 hours after dispatch, and consumes one slot, incrementing `current_week_reserved`.

Weekly capacity is an aggregate invariant over the ISO week, not a pairwise check. The week runs from Monday 00:00:00.000Z inclusive to the next Monday 00:00:00.000Z exclusive, and a dispatch exactly at Monday midnight belongs to the new week. `current_week_reserved` counts the organization's referrals whose `dispatched_at` falls in the current ISO week and whose current status is `DISPATCHED` or `ACCEPTED`. Acceptance (`DISPATCHED` → `ACCEPTED`) keeps the slot consumed. The compensating half of the invariant is that departure from the counted set releases the slot immediately: a decline (`DISPATCHED` → `DECLINED`) appends the organization to the referral's `declined_org_ids` and decrements `current_week_reserved` by one; expiry or cancellation of a `DISPATCHED` referral releases the slot the same way.

A declined referral can be re-routed `DECLINED` → `PROPOSED` by naming a new `legal_aid_org_id`. The new organization must be present and absent from `declined_org_ids` (`ERR_INVALID_REQUEST`), must cover the case's jurisdiction and category (`ERR_ORG_COVERAGE_MISMATCH`), and the caller's `LEGAL_AID_RELEASE` consent must stand at `GRANTED` (`ERR_CONSENT_REQUIRED`). Re-routing re-bases `sla_dispatch_by` to the current time plus the tier's service-level hours.

Two expirations belong to the sweep: a `PROPOSED` referral whose `sla_dispatch_by` has passed becomes `EXPIRED`, and a `DISPATCHED` referral whose `accept_by` has passed becomes `EXPIRED` with its slot released. Cancellation is manual or cascaded: `PROPOSED` referrals cancel under consent revocation or expiry, resource outdatedness or retirement, or operator action; `DISPATCHED` referrals cancel under operator action or `LEGAL_AID_RELEASE` revocation specifically. Every cancellation records a `cancel_reason` of `OPERATOR`, `CONSENT_REVOKED`, `CONSENT_EXPIRED`, or `SCRIPT_OUTDATED`, and cancelling a `DISPATCHED` referral releases its slot. `ACCEPTED`, `EXPIRED`, and `CANCELLED` are terminal.

### 3.9. Retention, Purge, and Call-Volume Analytics

The `DataProtectionOfficer` authors **retention policies**, each pairing an optional `jurisdiction_id` with an optional `issue_category` — null on either axis means it applies to all — and a `retention_days` count of the days after a caller's most recent case closure until PII must be purged. Policies are born `ACTIVE`, and creating an `ACTIVE` policy for an already-occupied (`jurisdiction_id`, `issue_category`) pair automatically deactivates the prior one to `INACTIVE`.

Which policy applies to a caller follows a precedence chain over `ACTIVE` policies only, keyed on the anchoring case's jurisdiction and category: first the exact pair match, then the jurisdiction row with a null category, then the null-jurisdiction row with the matching category, and finally the all-null agency default. The first match wins; if no `ACTIVE` policy matches at any level, the caller is not eligible for purge. Eligibility itself is anchored on the latest `closed_at` among the caller's `CLOSED` cases — with no closed case there is no anchor and no eligibility. A caller becomes eligible when the current logical time is on or after the anchor plus the applicable policy's `retention_days` (the boundary is inclusive — exactly at that instant counts), while `pii_purged` remains false, and no `PENDING` purge job already exists for the caller (sweep-side deduplication). The time sweep creates `PENDING` purge jobs for eligible callers — jobs are created only by the sweep, with `created_by_sweep` true.

Execution belongs to the `DataProtectionOfficer` alone. If any case of the caller carries `legal_hold` true, the job does not error — it transitions `PENDING` → `BLOCKED_BY_HOLD` with `blocked_reason` set to `LEGAL_HOLD`, and can be re-executed after the hold is lifted, at which point the same eligibility checks and the same scrub side effects apply as for a direct execution. Otherwise, eligibility is re-checked at execution time and a caller who is not yet eligible is rejected with `ERR_RETENTION_NOT_EXPIRED`. An executed purge scrubs the caller: `phone` is nulled, `alias` is overwritten with the literal 'purged', `pii_purged` is set true (mutating the caller and advancing its `version` and `updated_at` per §2.4), the caller's remaining `GRANTED` consents are moved to `EXPIRED` with their normal expiry cascades of §3.4, and `executed_at` is stamped. `EXECUTED` is terminal. Thereafter the purged caller is inert: consent grants, session intake, and case opening are all refused with `ERR_CALLER_PII_PURGED`.

Analytics serve policy advocacy without exposing callers. The call-volume read computes over a half-open window from `from_iso8601` inclusive to `to_iso8601` exclusive, with optional `jurisdiction_id` and `issue_category` filters, on read — no snapshot is persisted. Eligible sessions are those that reached `ACTIVE` at least once (their `session_status` stands at `ACTIVE`, `WRAPPED_UP`, or `DROPPED`) with `actual_start_at` inside the window; sessions that only ever queued, and abandoned sessions that never started, are excluded. Sessions whose caller has `do_not_aggregate` true are excluded from both views. Under the default `RAW` view, `call_count` counts every eligible session. Under the `DEDUPLICATED` view, `call_count` counts each identified caller — `is_anonymous` false — once, plus one for every anonymous session, because anonymous callers cannot be deduplicated. `escalated_case_count` counts cases whose `last_escalated_at` falls inside the window under the same filters. The `escalation_rate` is 0 when `call_count` is 0, and otherwise the escalated count divided by the call count, rounded half-up to four decimal places; the same window and filters under the two views can therefore legitimately report different rates. The response carries `call_count`, `escalated_case_count`, `escalation_rate`, and the echoed `view`. This read is available to `Analyst`, `HotlineSupervisor`, and `AgencyAdmin` — analysts see aggregates only and never caller-identified resources.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — state transitions, profile updates, revocations, executions — and all reads return `200 OK`. Request and response payloads are not repeated in this table; they are defined by the workflows of §3 and the contracts of §2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/hotline/jurisdictions` | Create a jurisdiction (STATE/COUNTY/CITY with statutory parameters) | AgencyAdmin |
| GET | `/hotline/jurisdictions/{id}` | Get one jurisdiction | AgencyAdmin, Counselor, HotlineSupervisor, DataProtectionOfficer, Analyst |
| GET | `/hotline/jurisdictions` | List jurisdictions with filters | AgencyAdmin, Counselor, HotlineSupervisor, DataProtectionOfficer, Analyst |
| POST | `/hotline/scripts` | Author a new script version (DRAFT); author taken from the acting counselor | Counselor |
| GET | `/hotline/scripts/{id}` | Get one script | Counselor, HotlineSupervisor, AgencyAdmin, DataProtectionOfficer, Analyst |
| GET | `/hotline/scripts` | List scripts with filters | Counselor, HotlineSupervisor, AgencyAdmin, DataProtectionOfficer, Analyst |
| POST | `/hotline/scripts/{id}/state` | Transition a script (submit by author; publish by a reviewer who is not the author; return for rework; retire) | Counselor, HotlineSupervisor |
| POST | `/hotline/self-help-resources` | Create a caller-facing resource linked to a published script | Counselor, HotlineSupervisor |
| GET | `/hotline/self-help-resources/{id}` | Get one resource | Counselor, HotlineSupervisor, AgencyAdmin, Analyst |
| GET | `/hotline/self-help-resources` | List resources with filters | Counselor, HotlineSupervisor, AgencyAdmin, Analyst |
| POST | `/hotline/self-help-resources/{id}/state` | Refresh (relink to a current published script) or retire a resource | Counselor, HotlineSupervisor |
| POST | `/hotline/counselors` | Register a counselor | AgencyAdmin |
| GET | `/hotline/counselors/{id}` | Get one counselor | AgencyAdmin, Counselor, HotlineSupervisor, DataProtectionOfficer |
| PATCH | `/hotline/counselors/{id}` | Update counselor profile, certification, scopes, or status | AgencyAdmin |
| POST | `/hotline/counselors/{id}/training-certifications` | Record completed training on a script version (score at least 80 appends to trained scripts) | HotlineSupervisor |
| POST | `/hotline/interpreters` | Register an interpreter | AgencyAdmin |
| GET | `/hotline/interpreters/{id}` | Get one interpreter | AgencyAdmin, Counselor, HotlineSupervisor |
| POST | `/hotline/callers` | Register a pseudonymous caller (public intake) | Anonymous |
| GET | `/hotline/callers/{id}` | Get one caller (own record for the Caller role) | Caller, Counselor, HotlineSupervisor, DataProtectionOfficer |
| POST | `/hotline/callers/{id}/consents` | Grant a consent (OCC on the caller version; expiry computed from the type's TTL) | Caller |
| GET | `/hotline/callers/{id}/consents` | List a caller's consents | Caller, Counselor, HotlineSupervisor, DataProtectionOfficer |
| POST | `/hotline/consents/{id}/revoke` | Revoke a granted consent (own caller or privacy officer) | Caller, DataProtectionOfficer |
| POST | `/hotline/sessions` | Intake a call (queued, interpretation not required) | Anonymous |
| GET | `/hotline/sessions/{id}` | Get one session | Counselor, HotlineSupervisor |
| GET | `/hotline/sessions` | List sessions with filters | Counselor, HotlineSupervisor |
| POST | `/hotline/sessions/{id}/state` | Transition the session (assign with a counselor; start pins the script and computes queue wait; wrap up; drop; abandon) | Counselor, HotlineSupervisor |
| POST | `/hotline/sessions/{id}/interpretation` | Transition the interpretation dimension (request with interpreter and window; connect; fail; retry; proceed without) | Counselor, HotlineSupervisor |
| POST | `/hotline/cases` | Open a case from a session; provisional score, tier, cadence, and exposure computed | Counselor, HotlineSupervisor |
| GET | `/hotline/cases/{id}` | Get one case | Counselor, HotlineSupervisor, DataProtectionOfficer |
| GET | `/hotline/cases` | List cases with filters | Counselor, HotlineSupervisor, DataProtectionOfficer |
| PATCH | `/hotline/cases/{id}` | Update case facts (recomputes under the current score variant); legal-hold-only toggle allowed on closed cases | Counselor, HotlineSupervisor |
| POST | `/hotline/cases/{id}/verify` | Verify case facts (verifier differs from opener); switches to the verified score variant | Counselor, HotlineSupervisor |
| POST | `/hotline/cases/{id}/state` | Transition the case (start work; escalate; supervisor-only de-escalate and close; resolve; reopen) | Counselor, HotlineSupervisor |
| POST | `/hotline/cases/{id}/notes` | Append an immutable case note (OCC on the case version) | Counselor, HotlineSupervisor |
| GET | `/hotline/cases/{id}/notes` | List the notes of a case (append-only log) | Counselor, HotlineSupervisor, DataProtectionOfficer |
| GET | `/hotline/counselors/{id}/notes` | Audit read: notes authored by a counselor across cases | HotlineSupervisor, DataProtectionOfficer |
| POST | `/hotline/cases/{id}/follow-ups` | Schedule a follow-up (24-hour spacing; case auto-moves to pending-follow-up) | Counselor, HotlineSupervisor |
| GET | `/hotline/cases/{id}/follow-ups` | List the follow-ups of a case | Counselor, HotlineSupervisor |
| POST | `/hotline/follow-ups/{id}/state` | Complete (outcome required) or cancel a follow-up | Counselor, HotlineSupervisor |
| POST | `/hotline/legal-aid-orgs` | Register a legal-aid organization | AgencyAdmin |
| GET | `/hotline/legal-aid-orgs/{id}` | Get one organization including computed weekly reserved count | AgencyAdmin, Counselor, HotlineSupervisor |
| PATCH | `/hotline/legal-aid-orgs/{id}` | Pause or activate an organization, or adjust weekly capacity | AgencyAdmin |
| POST | `/hotline/cases/{id}/referrals` | Propose a referral (OCC on the case version; SLA baseline from the current tier) | Counselor, HotlineSupervisor |
| GET | `/hotline/referrals/{id}` | Get one referral | Counselor, HotlineSupervisor |
| GET | `/hotline/referrals` | List referrals with filters | Counselor, HotlineSupervisor |
| POST | `/hotline/referrals/{id}/state` | Transition a referral (dispatch; accept; decline; re-route from declined with a new organization; cancel) | Counselor, HotlineSupervisor |
| POST | `/hotline/retention-policies` | Create a retention policy (auto-deactivates the prior active policy for the same pair) | DataProtectionOfficer |
| GET | `/hotline/retention-policies/{id}` | Get one retention policy | DataProtectionOfficer, HotlineSupervisor, AgencyAdmin |
| GET | `/hotline/retention-policies` | List retention policies with filters | DataProtectionOfficer, HotlineSupervisor, AgencyAdmin |
| GET | `/hotline/purge-jobs/{id}` | Get one purge job | DataProtectionOfficer, HotlineSupervisor |
| GET | `/hotline/purge-jobs` | List purge jobs with filters | DataProtectionOfficer, HotlineSupervisor |
| POST | `/hotline/purge-jobs/{id}/execute` | Execute a purge (scrubs caller PII and expires granted consents; a legal hold blocks instead of erroring) | DataProtectionOfficer |
| GET | `/hotline/analytics/call-volume` | Call-volume and escalation metrics over a half-open window; raw or deduplicated view | Analyst, HotlineSupervisor, AgencyAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock (startup default is exactly 2026-08-01T00:00:00Z; never falls back to wall-clock) | AgencyAdmin |
| POST | `/_ops/run_time_sweep` | Advance all clock-driven transitions at the current logical time in the pinned processing order | AgencyAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined where the rule lives in §2 and §3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_SCRIPT_REVIEWER_CONFLICT` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CASE_NOT_VERIFIED` | 409 Conflict |
| `ERR_CASE_HAS_OPEN_ITEMS` | 409 Conflict |
| `ERR_SCRIPT_VERSION_CHAIN_BROKEN` | 409 Conflict |
| `ERR_DUPLICATE_PUBLISHED_SCRIPT` | 409 Conflict |
| `ERR_SCRIPT_NOT_PUBLISHED` | 409 Conflict |
| `ERR_RESOURCE_OUTDATED` | 409 Conflict |
| `ERR_COUNSELOR_INACTIVE` | 409 Conflict |
| `ERR_CERTIFICATION_EXPIRED` | 409 Conflict |
| `ERR_TRAINING_NOT_CURRENT` | 409 Conflict |
| `ERR_LANGUAGE_UNSUPPORTED` | 409 Conflict |
| `ERR_INTERPRETER_LANGUAGE_MISMATCH` | 409 Conflict |
| `ERR_INTERPRETER_OVERLAP` | 409 Conflict |
| `ERR_INTERPRETER_PREVIOUSLY_FAILED` | 409 Conflict |
| `ERR_CALLER_PII_PURGED` | 409 Conflict |
| `ERR_CONSENT_REQUIRED` | 409 Conflict |
| `ERR_ORG_NOT_ACCEPTING` | 409 Conflict |
| `ERR_ORG_CAPACITY_FULL` | 409 Conflict |
| `ERR_SLA_BREACHED` | 409 Conflict |
| `ERR_FOLLOW_UP_TOO_SOON` | 409 Conflict |
| `ERR_RETENTION_NOT_EXPIRED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_JURISDICTION_LEVEL_MISMATCH` | 422 Unprocessable Entity |
| `ERR_ANONYMOUS_FOLLOW_UP_FORBIDDEN` | 422 Unprocessable Entity |
| `ERR_ORG_COVERAGE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_REFERRAL_TARGET_MISMATCH` | 422 Unprocessable Entity |
