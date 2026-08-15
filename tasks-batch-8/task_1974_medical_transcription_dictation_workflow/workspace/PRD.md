# Medical Transcription API — Product Requirements Document

## 1. Introduction

Clinics increasingly outsource the conversion of dictated clinical notes into finished, signed documentation, and the vendor that performs this work lives or dies by two numbers: turnaround time and per-line billing accuracy. This document specifies the vendor-side platform that sits between a provider's microphone and the clinic's chart — a system that captures dictations, routes them through an editor pool by turnaround priority, drafts them with speech recognition, puts every submission through quality review with error-severity scoring, returns finished transcripts to the record for signature, and invoices the clinic per sixty-five-character line with service-level credits when turnaround targets are missed.

Three pressures shape the design. First, turnaround commitments differ by priority, so STAT work must be able to preempt routine work already in production when the pool has no spare capacity, and jobs that approach their deadline must escalate visibly before they breach. Second, quality is enforced structurally rather than by policy memo: the quality reviewer is always someone other than the transcript's author, an editor's recent accuracy drives a standing ladder that widens or shrinks how much work they may hold at once, and providers who let unsigned reports pile up are progressively warned and then suspended from uploading new dictations. Third, money and time must be auditable — two different clinics may measure the same turnaround against different baselines, billing amounts are computed twice (a provisional estimate at period close and a final figure at finalize), and an unpaid overdue invoice quietly closes the tap on new dictation uploads until it is settled. A vendor-operated logical clock makes all of this deterministic: aging, escalation, suspension, and billing-hold evaluation are pure functions of that clock.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes five distinct roles: `VendorAdmin`, `ClientAdmin`, `Provider`, `Editor`, and `QASupervisor`. Failure to provide valid headers, or presenting a role the system does not recognize, results in an `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` error. Access to specific operations is further restricted by role; an attempt to perform an action outside the caller's designated role is rejected with `ERR_UNAUTHORIZED_ROLE`.

Role responsibilities divide along the vendor/clinic boundary. A `VendorAdmin` runs the transcription vendor's operations: clinic onboarding, SLA policy configuration, editor pool management, the billing lifecycle, and the logical clock. A `ClientAdmin` is the clinic-side administrator, responsible for the provider roster, lifting signature-compliance suspensions, and disputing invoices. A `Provider` is a dictating clinician who owns dictation jobs, templates, and macros, and who signs, returns, or amends transcripts of their own jobs. An `Editor` is a medical transcriptionist who claims, edits, and submits jobs and declares their own availability windows. A `QASupervisor` scores submitted work with error-severity counts and may never review a transcript authored by the same `X-User-ID`. All five roles may use the read endpoints; mutating capabilities are enumerated per endpoint in §4.

Two of the roles are entity-backed. When `X-User-Role` is `Provider`, `X-User-ID` is the `id` of the acting Provider; ownership checks on any resource that references a Provider compare the resource's foreign-key field to `X-User-ID`, and for transcript-level actions the comparison is made against the owning job's provider. When `X-User-Role` is `Editor`, `X-User-ID` is the `id` of the acting Editor; ownership checks compare the request's `editor_id` (when claiming a job or declaring an availability window) or the job's `claimed_by_editor_id` (when submitting or releasing a claimed job) to `X-User-ID`. The remaining three roles are opaque: when `X-User-Role` is `VendorAdmin`, `ClientAdmin`, or `QASupervisor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `reviewer_user_id` on a QA review — but does not compare it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and the System Sweep

All server-stamped timestamps — `created_at`, `claimed_at`, `submitted_at`, `delivered_at`, `signed_at`, `finalized_at`, and every derived deadline such as `due_at` — are read from a single server-side logical clock, never from wall-clock time. Before it has ever been set, the logical clock reads the fixed default instant 2026-08-01T00:00:00Z, and it never falls back to wall-clock time thereafter.

A `VendorAdmin` advances the logical clock by supplying a `to_iso8601` instant; the response reports the resulting `current_utc`. Setting the clock is not a mere read of time — it triggers the full system sweep, executed in a pinned order: first unsigned-transcript aging tiers are recomputed, then per-provider unsigned counts and provider compliance statuses, then each clinic's `suspended_provider_count`, then each clinic's `billing_hold`, and finally job escalation levels, including any STAT preemptions that critical escalation fires. Within that last step, STAT preemptions are processed in job creation order, earliest `created_at` first. The business content of each sweep phase is specified in §3.7 and §3.9.

### 2.5. Common Resource Properties

All primary resources in the system — clinic accounts, SLA policies, providers, editors, shift windows, dictation jobs, transcripts, templates, macros, billing periods, and line items — carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits, recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp updated upon any change to the resource's properties.
- `version` (integer): a system-managed integer that increments with every modification to the resource, and which anchors optimistic concurrency control where §2.7 applies.

Any mutation of a resource — including system-driven mutations such as a preemption clearing a job's claim fields, a sweep rewriting a provider's status, or a template supersession bumping a provider — refreshes that resource's `updated_at` and increments its `version`.

The QA review is the single exception. It is an append-only event record and carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.6. The Validation Pipeline

Every request is validated against an ordered pipeline, and the order is part of the contract: a failure surfaces the earliest applicable rejection, not an arbitrary one.

First, the presence and recognizability of the `X-User-ID` and `X-User-Role` headers is checked; a missing or unrecognized context yields `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Second, the role's permission to invoke the endpoint is checked, yielding `ERR_UNAUTHORIZED_ROLE`. Immediately after role authorization — and before any existence lookup — the request body schema is validated: required fields must be present, types must match, enum members must be valid, and numeric ranges must be respected (for example, `audio_duration_seconds` must be greater than zero, error counts must be non-negative, `tat_minutes` must be greater than zero, `breach_credit_pct` must lie within zero to one hundred inclusive, a dispute-resolution `outcome` must be `UPHELD` or `REVERSED`, and interval bounds must be parseable). Any schema failure yields `ERR_INVALID_REQUEST`.

Only then does existence validation run: path identifiers are validated left to right, and body foreign-key references (`dictation_job_id`, `clinic_account_id`, `provider_id`, `editor_id`, `template_id`) must also resolve. Each missing resource raises its own not-found error — `ERR_CLINIC_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_EDITOR_NOT_FOUND`, `ERR_JOB_NOT_FOUND`, `ERR_TRANSCRIPT_NOT_FOUND`, `ERR_TEMPLATE_NOT_FOUND`, `ERR_MACRO_NOT_FOUND`, or `ERR_BILLING_PERIOD_NOT_FOUND`. Existence strictly precedes ownership: a resource that does not exist can raise no ownership check.

Ownership comes next for the entity-backed roles, as described in §2.1, and a mismatch yields `ERR_FORBIDDEN_OWNERSHIP`. One subtlety governs the comparison: when the owner field being compared is null — for example, the `claimed_by_editor_id` of an unclaimed job — the ownership check is vacuous and evaluation proceeds to the state gates, so a submission attempted on a job that is still `QUEUED` fails with `ERR_JOB_NOT_EDITING`, not with an ownership error.

Optimistic concurrency checks (§2.7) run after existence and before all business rules, yielding `ERR_STALE_PROVIDER_VERSION` or `ERR_STALE_TEMPLATE_VERSION`. Resource-state preconditions follow — the job, transcript, editor, provider, or billing period must be in the state its action requires — and the relevant failures are the `ERR_JOB_NOT_QUEUED`, `ERR_JOB_NOT_EDITING`, `ERR_JOB_NOT_SUBMITTED`, `ERR_JOB_NOT_CANCELLABLE`, `ERR_TRANSCRIPT_NOT_DELIVERED`, `ERR_TRANSCRIPT_NOT_SIGNED`, `ERR_PROVIDER_SUSPENDED`, `ERR_EDITOR_NOT_ACTIVE`, `ERR_BILLING_PERIOD_NOT_OPEN`, `ERR_BILLING_PERIOD_NOT_CLOSED`, `ERR_BILLING_PERIOD_NOT_FINALIZED`, `ERR_BILLING_PERIOD_NOT_DISPUTED`, and `ERR_UNSIGNED_REPORTS_REMAIN` family.

Business rules close the pipeline, again in a fixed relative order: the segregation-of-duties check on quality review (`ERR_SELF_REVIEW_FORBIDDEN`) precedes the probationary-editor STAT gate (`ERR_PROBATION_STAT_FORBIDDEN`), which precedes editor capacity (`ERR_EDITOR_CAPACITY_FULL`), which precedes uniqueness constraints (`ERR_DUPLICATE_MACRO_SHORTCUT`, `ERR_DUPLICATE_SLA_POLICY`), which precede interval well-formedness (`ERR_INVALID_WINDOW`) and the temporal checks (`ERR_SHIFT_WINDOW_OVERLAP`, `ERR_OUTSIDE_SHIFT_WINDOW`, `ERR_BILLING_PERIOD_OVERLAP`), which precede the referential requirements that an SLA policy exist (`ERR_SLA_POLICY_MISSING`) and that a supplied template bind correctly to the job (`ERR_TEMPLATE_PROVIDER_MISMATCH`, `ERR_TEMPLATE_WORK_TYPE_MISMATCH`). The fiscal gate — a clinic under billing hold may not upload new dictations — is evaluated last among them and yields `ERR_CLINIC_BILLING_HOLD`.

### 2.7. Optimistic Concurrency Control

Two write operations in the system are guarded by optimistic concurrency, and only those two.

Creating a new template version for a provider requires the request to carry `expected_provider_version`, holding the `version` of that Provider as the client last observed it. If the provider's current `version` has advanced since that observation — for instance because another writer has just created a template for the same provider and work type, legitimately superseding the prior active one — the create is rejected with `ERR_STALE_PROVIDER_VERSION` (HTTP 412), preventing the client from acting on a stale view of the provider.

Updating an existing template's name or body likewise requires `expected_template_version`, holding the `version` of the ProviderTemplate as last observed. A mismatch with the template's current `version` is rejected with `ERR_STALE_TEMPLATE_VERSION` (HTTP 412).

Both version fields are non-optional on their respective endpoints. Endpoints not named here take no version field at all.

### 2.8. Numeric Precision and Rounding

Quality scores — the per-review `accuracy_score` and each editor's `rolling_quality_score` — are carried to exactly two decimal places using round-half-up. Monetary amounts are integer cents throughout; SLA credits are rounded half-up per line item before any summation takes place, and §3.9 pins that ordering. Line counts and other tallies are integers, produced by rounding division up to a whole number where the underlying measure does not divide evenly. Timestamps are ISO 8601 UTC; deadline and breach comparisons are made at second precision.

### 2.9. Interval Semantics: Availability Windows and Billing Periods

Two kinds of time intervals exist in the system, and they follow deliberately different overlap conventions.

An editor's availability window is a half-open interval: `start_at` is inclusive, `end_at` is exclusive, and `end_at` must be strictly after `start_at`, with violations rejected as `ERR_INVALID_WINDOW`. A new window for an editor is rejected with `ERR_SHIFT_WINDOW_OVERLAP` exactly when it begins before an existing window of that same editor ends and that existing window begins before the new window ends. Two windows that merely touch — one ending at the precise instant the other begins — do not overlap and are allowed. Availability windows are immutable once declared; there is no update operation for them.

A billing period, by contrast, is a closed interval: both `period_start` and `period_end` are members, for overlap and for membership of delivered work alike. `period_end` must be strictly after `period_start`, again enforced as `ERR_INVALID_WINDOW`. A new period for a clinic is rejected with `ERR_BILLING_PERIOD_OVERLAP` exactly when its start falls on or before an existing period's end and that existing period's start falls on or before the new period's end. Unlike availability windows, two billing periods whose endpoints merely touch are in conflict.

### 2.10. Resource Addressing and Collection Listings

All resources are top-level; relationships between them are expressed through foreign-key references carried in payloads and query filters rather than through deeply nested paths. Where an endpoint path does contain more than one identifier segment, existence is validated left to right, and the request is rejected with the not-found error of the first identifier that does not resolve.

Reverse lookups are provided as filtered collection listings. A clinic's providers, SLA policies, and billing periods are listable from the clinic; a provider's templates and macros from the provider (macros defaulting to active ones only, with an `include_archived` query flag to include archived ones); an editor's availability windows from the editor; the quality reviews of a job or of a transcript from each parent; and the line items of a billing period or billing a given transcript from each parent. The dictation-job listing supports filters by `provider_id`, `clinic_account_id`, `claimed_by_editor_id`, `template_id`, and `workflow_status`, and the transcript listing by `dictation_job_id` and `editor_id`; both accept the standard `limit` and `offset` pagination parameters of §2.3.

## 3. Business Logic & Workflows

### 3.1. Clinic Onboarding and SLA Policy Configuration

Everything begins when a `VendorAdmin` onboards a clinic account. The only required input is the organization's `name`; four policy knobs carry defaults that the administrator may override at creation. The `unsigned_report_threshold` — how many aged unsigned transcripts a single provider may accumulate before suspension — defaults to 3 and must be at least 1. The two aging boundaries, `aging_tier1_hours` and `aging_tier2_hours`, default to 24 and 72 hours respectively; the first must be at least 1 and strictly less than the second. The `payment_grace_days` knob, the number of days a finalized invoice may sit unpaid before the clinic is cut off from new dictation uploads, defaults to 14. A freshly created clinic has `billing_hold` false and a `suspended_provider_count` of zero.

With the clinic in place, the `VendorAdmin` configures its service-level policies, one row per priority band. Each policy names the owning `clinic_account_id`, the `priority` it governs — one of `STAT`, `URGENT`, or `ROUTINE` — and four commercial terms: `tat_minutes`, the turnaround target in minutes, which must be greater than zero; `rate_per_line_cents`, the billed rate per sixty-five-character line at this priority, also greater than zero; `breach_credit_pct`, the percentage of a breaching line item's final amount that is credited back to the clinic, between zero and one hundred inclusive; and `measurement_basis`, which selects how turnaround compliance is measured at billing time and must be either `END_TO_END` or `PRODUCTION_WINDOW`. At most one policy may exist for a given clinic-and-priority pair; a duplicate create is rejected with `ERR_DUPLICATE_SLA_POLICY`.

The choice of `measurement_basis` is consequential. `END_TO_END` measures wall-clock time from dictation upload to delivery, so queue wait counts against the vendor. `PRODUCTION_WINDOW` measures only the span from a job's first-ever claim to the final accepted submission, excluding queue wait entirely — the very same job data can be compliant under `PRODUCTION_WINDOW` while breaching under `END_TO_END`. The exact breach predicates are defined with the billing workflow in §3.9.

### 3.2. Provider Roster, Templates, and Macros

A `ClientAdmin` builds the clinic's roster by creating providers. Each provider is created with its employing `clinic_account_id`, a `full_name`, and a `specialty` of `RADIOLOGY`, `CARDIOLOGY`, `ORTHOPEDICS`, or `GENERAL`. A new provider starts with `status` `ACTIVE`, both unsigned counters — `unsigned_tier1_count` and `unsigned_aged_count` — at zero, and `suspension_reason` null.

Providers personalize their drafts through templates. A provider creates a template version by supplying the owning `provider_id` (which must equal the caller's `X-User-ID`), a `work_type` drawn from `CONSULT`, `OP_NOTE`, `DISCHARGE_SUMMARY`, `CLINIC_NOTE`, or `RADIOLOGY_REPORT`, a `name`, and the `body_text` containing whatever macro placeholders the provider uses. Exactly one template per provider-and-work-type pair is active at a time: creating a new template for a pair that already has an active one flips the prior template's `is_active` to false, and this supersession is a mutation of the provider itself — the provider's `version` increments by one. Because of that, creation carries the OCC guard of §2.7 through `expected_provider_version`. An existing template's `name` or `body_text` may be revised by its owning provider; either field may be omitted from the update, the template's `version` increments by one on success, and the update is OCC-guarded through `expected_template_version`.

Macros are the provider's shorthand expansions. Creating one takes the owning `provider_id`, a `shortcut` trigger, and the `expansion_text` it expands to; the macro starts in `ACTIVE` status. Among a provider's `ACTIVE` macros the `shortcut` must be unique — a duplicate create is rejected with `ERR_DUPLICATE_MACRO_SHORTCUT`. Archiving is a soft delete: the macro moves to `ARCHIVED`, disappears from default listings unless the caller passes `include_archived`, and its shortcut is freed for reuse in a new active macro.

### 3.3. Dictation Capture and Job Routing

A dictation enters the system when a `Provider` uploads one. The payload carries the dictating `provider_id` — which must equal the caller's `X-User-ID` — the `work_type`, the `priority` band (`STAT`, `URGENT`, or `ROUTINE`), the captured `audio_duration_seconds`, which must be greater than zero, and optionally a `template_id` to apply to the draft.

Several guards stand between the upload and the queue, in the pipeline order of §2.6. A provider whose `status` is `SUSPENDED` cannot upload at all and is rejected with `ERR_PROVIDER_SUSPENDED`. A clinic under billing hold is likewise closed for new dictations, rejected with `ERR_CLINIC_BILLING_HOLD`. An SLA policy must exist for the job's clinic-and-priority combination, or the upload fails with `ERR_SLA_POLICY_MISSING`. When a `template_id` is supplied, it must belong to the same provider as the job — otherwise `ERR_TEMPLATE_PROVIDER_MISMATCH` — and its work type must equal the job's `work_type`, otherwise `ERR_TEMPLATE_WORK_TYPE_MISMATCH`.

A job that passes the guards is created with its `clinic_account_id` copied from the provider's record, `workflow_status` `QUEUED`, and `escalation_level` `NONE`. Speech recognition runs inline at capture: the draft size estimate `asr_char_estimate` is exactly twice the `audio_duration_seconds`, at two characters per second of audio. The deadline `due_at` is fixed at creation as the job's `created_at` plus the governing policy's `tat_minutes`, and it is never recomputed afterwards — rework, preemption, and provider returns all leave the original deadline untouched. The bookkeeping counters `rework_count` and `preempted_count` start at zero, and the timestamps `claimed_at`, `first_claimed_at`, `submitted_at`, and `delivered_at` — together with `claimed_by_editor_id` — remain null until the corresponding events occur.

STAT work gets one more piece of routing. When a `STAT` job is created and the editor pool has zero free capacity, the STAT preemption routine of §3.7 runs immediately, inline with the creation, potentially force-releasing a routine or urgent job already in production and auto-assigning the STAT job to the freed editor.

A queued or in-progress job may be cancelled by its owning provider or by a `VendorAdmin`; a job in any other state is rejected with `ERR_JOB_NOT_CANCELLABLE`. Cancelling a `QUEUED` job simply moves it to `CANCELLED`. Cancelling an `EDITING` job additionally performs claim compensation: `claimed_by_editor_id` and `claimed_at` are cleared, and the holding editor's `active_claim_count` is decremented. `CANCELLED` is terminal.

### 3.4. Editor Availability, Claiming, and Capacity

The vendor's production capacity lives in its editor pool. A `VendorAdmin` onboards an editor with nothing more than a `display_name`; the new editor starts `ACTIVE`, with a `rolling_quality_score` of 100.0, a `qa_review_count` of zero, a provisional `skill_tier` of `TIER_2` until five reviews have accumulated, a `max_concurrent_claims` of 3, and an `active_claim_count` of zero.

Editors declare when they are available. An editor declares an availability window for their own `editor_id`, while a `VendorAdmin` may declare one for any editor; the window carries `start_at` and `end_at` and follows the half-open semantics of §2.9 — malformed bounds yield `ERR_INVALID_WINDOW`, and a window colliding with an existing one of the same editor yields `ERR_SHIFT_WINDOW_OVERLAP`, while back-to-back adjacency is allowed. Windows are immutable once declared.

Claiming is how work leaves the queue. An editor claims a job by passing their `editor_id`, which must equal the caller's `X-User-ID`. The claim is gated by a strict battery of checks: the job must be `QUEUED` (`ERR_JOB_NOT_QUEUED`); the editor must not be `SUSPENDED` (`ERR_EDITOR_NOT_ACTIVE`); if the job's priority is `STAT`, the editor's status must be `ACTIVE` — a `PROBATION` editor is a quality risk and is refused with `ERR_PROBATION_STAT_FORBIDDEN`; the editor's `active_claim_count` must be strictly below their `max_concurrent_claims` (`ERR_EDITOR_CAPACITY_FULL`); and the current logical time must fall inside at least one declared availability window of that editor (`ERR_OUTSIDE_SHIFT_WINDOW`).

A successful claim moves the job from `QUEUED` to `EDITING`, stamps `claimed_by_editor_id` with the editor and `claimed_at` with the current time, sets `first_claimed_at` if it has never been set — that first-claim instant is the anchor of the `PRODUCTION_WINDOW` turnaround measurement — and increments the editor's `active_claim_count` by one.

Releasing is the compensating action of claiming, available to the editor holding the job or to a `VendorAdmin`, and valid only while the job is `EDITING` (`ERR_JOB_NOT_EDITING`). The job returns from `EDITING` to `QUEUED`, its claim fields are cleared, and the editor's `active_claim_count` is decremented. The same `EDITING`-to-`QUEUED` transition is also fired by the system itself during preemption; in that case the job's `preempted_count` is additionally incremented, as §3.6 and §3.7 describe.

### 3.5. Editing, Submission, and Quality Review

Work in `EDITING` belongs to one editor. When the editing is complete, the holding editor submits the job with the polished `final_text`; the job must be `EDITING` and `claimed_by_editor_id` must equal the caller's `X-User-ID`, with violations surfacing as `ERR_JOB_NOT_EDITING` or `ERR_FORBIDDEN_OWNERSHIP`.

Submission creates a new transcript version. The transcript records its owning `dictation_job_id`, the authoring `editor_id` — the claiming editor at submit time, which becomes the segregation-of-duties anchor for quality review — and a `version_number` that starts at 1 for the job's first submission and increases by one with each subsequent submission. The transcript lands in `SUBMITTED` status. Its length is measured two ways from `final_text`: `visible_char_count` is the length of the text after removing every whitespace character — spaces, tabs, and newlines — and `line_count` is that visible length divided into sixty-five-character lines, rounded up to a whole line, with zero characters yielding zero lines. The job's `submitted_at` is stamped with the current time and its `workflow_status` moves from `EDITING` to `SUBMITTED`.

Every submitted job then passes through quality review, recorded by a `QASupervisor`. The review payload names the `dictation_job_id` under review — the job must be `SUBMITTED`, otherwise `ERR_JOB_NOT_SUBMITTED` — and three error tallies: `critical_error_count`, `major_error_count`, and `minor_error_count`, each of which must be zero or greater. Segregation of duties is hard-enforced: the reviewer's `X-User-ID` must differ from the transcript's `editor_id`, and a self-review is rejected with `ERR_SELF_REVIEW_FORBIDDEN`. The recorded review binds the job's current `SUBMITTED` transcript as its `transcript_id`, captures the caller as `reviewer_user_id`, and receives an `editor_sequence` — a per-editor monotonic ordinal, 1, 2, 3, and so on across the reviews of that editor's work — which serves as the tie-break inside same-timestamp rolling windows. The review itself is append-only.

From the three tallies the system computes the review's `accuracy_score`: start from 100, subtract 25 points for every critical error, 5 points for every major error, and 1 point for every minor error, floor the result at zero, and round half-up to two decimal places. The review's `outcome` is `PASS` exactly when the score is at least 80.0 and the critical error count is zero; otherwise it is `FAIL`. The critical-error clause is independent of the number — a single critical error fails the review no matter how high the arithmetic score.

The outcome drives the job in opposite directions. On a `PASS`, the transcript moves from `SUBMITTED` to `DELIVERED`, its `delivered_at` is stamped, and its `aging_tier` initializes to `NONE` as the signature-queue aging clock of §3.7 starts ticking. The parent job moves from `SUBMITTED` to `DELIVERED` in step: its own `delivered_at` is stamped, `claimed_by_editor_id` and `claimed_at` are cleared, the editor's `active_claim_count` is decremented, and the editor-standing cascade of §3.6 runs. On a `FAIL`, the current transcript version moves to `REJECTED`, the job returns from `SUBMITTED` to `EDITING` while remaining claimed by the same editor — so `active_claim_count` does not change — and the job's `rework_count` is incremented by one. The standing cascade still runs, and if the review drags the editor's standing down far enough to shrink capacity, this very job may be preempted out of the editor's hands immediately afterwards.

### 3.6. Editor Standing, Skill Tiers, and Capacity Preemption

Quality review feeds a rolling reputation for each editor. After every recorded review, the system takes the twenty most recent reviews of that editor's transcripts — any outcome counts — ordered by creation time descending with `editor_sequence` descending as the tie-break, and sets `rolling_quality_score` to the mean of the `accuracy_score` values across that window, rounded half-up to two decimal places. The lifetime `qa_review_count` is recomputed alongside.

Standing transitions are evaluated only once an editor has at least five reviews; before that, the editor's standing is not disturbed and the `skill_tier` remains its provisional `TIER_2`. From `ACTIVE`, an editor falls to `PROBATION` when the rolling score drops below 85, and falls directly to `SUSPENDED` when it drops below 70. From `PROBATION`, an editor climbs back to `ACTIVE` when the rolling score reaches at least 90, but drops to `SUSPENDED` when the rolling score is below 75 or when the latest review contains any critical error at all. A `SUSPENDED` editor never recovers automatically: only a `VendorAdmin` reinstatement returns the editor to `ACTIVE` — attempted on an editor who is not `SUSPENDED` it fails with `ERR_EDITOR_NOT_ACTIVE` — and reinstatement leaves the `rolling_quality_score` untouched while re-deriving the tier and capacity from the current score.

Once standing is evaluated, the `skill_tier` follows from the rolling score: `TIER_3` at 95 or above, `TIER_2` at 85 or above but below 95, and `TIER_1` below 85. Capacity follows from the tier: a `TIER_1` editor may hold 1 concurrent claim, a `TIER_2` editor 3, a `TIER_3` editor 5, and a `SUSPENDED` editor 0.

Because standing can shrink capacity beneath the work an editor already holds, every standing change — whether from a review or from reinstatement — triggers a capacity reevaluation with a pinned evaluation order: the rolling score (already recomputed by the caller), then the standing transition, then the `skill_tier`, then `max_concurrent_claims`, and only then preemption. If the editor's `active_claim_count` now exceeds `max_concurrent_claims`, the excess number of the editor's `EDITING` jobs is force-released. The preemption selector ranks that editor's `EDITING` jobs by priority ascending — `ROUTINE` first, then `URGENT`, then `STAT` — breaking ties by `claimed_at` descending so the most recently claimed job is released first, and any remaining ties by job `created_at` descending. Each preempted job moves from `EDITING` back to `QUEUED`, its `claimed_by_editor_id` and `claimed_at` are cleared, its `preempted_count` is incremented, and the editor's `active_claim_count` is decremented accordingly.

### 3.7. Escalation, Unsigned-Report Aging, and Provider Suspension

Alongside its workflow status, every job carries a second, parallel axis: the `escalation_level`, one of `NONE`, `ESCALATED`, or `CRITICAL`. The axis is monotonic — the level never decreases — it is driven entirely by the clock sweep rather than by any direct action, and it is frozen once a job reaches `DELIVERED` or `CANCELLED`. On each sweep, every job whose `workflow_status` is `QUEUED`, `EDITING`, or `SUBMITTED` is re-evaluated. A job whose deadline has already arrived or passed — the current time is at or after `due_at` — is `CRITICAL`. A job not yet at its deadline but within its escalation buffer is `ESCALATED`; the buffer is one quarter of the governing policy's `tat_minutes`, computed by integer division in whole minutes with any fractional minute discarded, so the `ESCALATED` band opens when the current time reaches `due_at` minus that quarter-turnaround buffer and remains open until the deadline itself. Everything earlier stays at `NONE`. Because the sweep evaluates both predicates against the same instant, a job first swept after its deadline moves directly from `NONE` to `CRITICAL`.

Escalation has teeth where STAT work is concerned. The STAT preemption routine runs in two situations: inline at the creation of a `STAT` job (as §3.3 notes), and from the sweep whenever a `QUEUED` `STAT` job enters `CRITICAL`. The routine first measures the pool's free capacity: the sum, over every editor whose status is `ACTIVE`, of that editor's remaining headroom — `max_concurrent_claims` minus `active_claim_count`, floored at zero. If free capacity is zero, the routine looks for a victim among jobs currently `EDITING` whose priority is `ROUTINE` or `URGENT`, ranked by priority ascending — `ROUTINE` before `URGENT` — with ties broken by `claimed_at` descending and further ties by `created_at` descending. When a victim exists, it is preempted: moved from `EDITING` to `QUEUED`, its claim fields cleared, its `preempted_count` incremented, and its editor's `active_claim_count` decremented. The STAT job is then auto-assigned to the victim's former editor: it moves straight to `EDITING` with `claimed_by_editor_id` set to that editor, `claimed_at` stamped, `first_claimed_at` set if it was still null, and the editor's `active_claim_count` incremented — bypassing both the shift-window gate and the capacity ceiling that a manual claim would face. When no victim exists, the STAT job simply remains `QUEUED`; the preemption is deferred and no error is raised. Within a single sweep, multiple STAT preemptions are processed in job creation order, earliest `created_at` first.

The same sweep runs the unsigned-report aging that disciplines providers. Every transcript still in `DELIVERED` status — delivered but unsigned — is aged by the whole hours elapsed since its `delivered_at`. Its `aging_tier` becomes `TIER_2` once that age reaches the clinic's `aging_tier2_hours`, `TIER_1` once it reaches `aging_tier1_hours`, and `NONE` before that; the boundary is inclusive, so a transcript aged to exactly a threshold crosses into that tier. Each provider's counters follow immediately whenever any of their transcripts changes tier or status, and on every sweep: `unsigned_tier1_count` is the number of the provider's `DELIVERED` transcripts sitting at `TIER_1`, and `unsigned_aged_count` the number at `TIER_2`.

Those counters drive the provider's compliance status. When the aged count reaches the clinic's `unsigned_report_threshold`, the provider is suspended from either `ACTIVE` or `WARNING`: the status becomes `SUSPENDED`, `suspension_reason` is set to `UNSIGNED_REPORT_AGING`, and the clinic's `suspended_provider_count` is recomputed. When the two unsigned counts sum to at least one but the suspension threshold is not met, the provider moves from `ACTIVE` to `WARNING`, which is advisory and leaves clinic counters untouched. When both counts return to zero, a provider in `WARNING` recovers to `ACTIVE` automatically. Suspension, by contrast, never lifts itself: signing down the backlog reduces the counts but leaves a `SUSPENDED` provider suspended until a `ClientAdmin` reinstates them, and reinstatement is refused while any aged unsigned report remains — `unsigned_aged_count` must be zero, otherwise `ERR_UNSIGNED_REPORTS_REMAIN`. A successful reinstatement returns the provider to `ACTIVE`, clears `suspension_reason` to null, and recomputes the clinic's `suspended_provider_count`.

The sweep's pinned order, restated from §2.4 because the phases interact, is: aging tiers first, then provider counts and statuses, then the clinic `suspended_provider_count`, then `billing_hold`, then escalation levels with their STAT preemptions. The billing-hold phase evaluates each clinic for overdue invoices — the rule itself lives with the billing workflow in §3.9 — and because the hold is also evaluated inline at dictation upload time, a clinic can find its upload path closing mid-session the moment a grace window expires.

### 3.8. The Signature Queue: Signing, Returns, and Addenda

A delivered transcript lands in the dictating provider's signature queue, where it both awaits a signature and quietly ages per §3.7. Three provider actions and one vendor-or-provider action close out the lifecycle.

Signing is the happy path. The provider whose job owns the transcript signs it; the transcript must be `DELIVERED` (`ERR_TRANSCRIPT_NOT_DELIVERED`), and the caller must be that provider (`ERR_FORBIDDEN_OWNERSHIP`). The transcript moves from `DELIVERED` to `SIGNED`, its `signed_at` is stamped, and its `aging_tier` freezes — a signed transcript stops aging immediately. The provider's unsigned counters are recomputed right away, which is how a provider in `WARNING` earns an immediate return to `ACTIVE` without waiting for the next sweep.

Returning is the rejection path. The provider sends a `DELIVERED` transcript back, moving it to `RETURNED`, which is terminal for that version, and the provider's unsigned counters are recomputed. The parent job reopens in step: it moves from `DELIVERED` back to `EDITING`, its `rework_count` is incremented, and the system re-claims it to the transcript's authoring `editor_id` with a fresh `claimed_at`. This system re-claim deliberately bypasses the capacity ceiling and the shift-window gate, and it does not trigger any preemption; the re-claimed editor's `active_claim_count` is simply incremented.

Addenda handle post-signature corrections. A provider may amend a transcript that is `SIGNED` — anything else yields `ERR_TRANSCRIPT_NOT_SIGNED`, with the usual ownership check — by supplying `addendum_text`. The transcript moves from `SIGNED` to `AMENDED`, the addendum is stored, and billing is untouched: addenda never re-bill, and any line items already generated for the transcript remain as they are.

### 3.9. Billing Periods, Line Items, and Dispute Resolution

Billing runs on closed periods that a `VendorAdmin` opens per clinic. Creating a period takes the `clinic_account_id`, a `period_start`, and a `period_end`, following the closed-interval semantics of §2.9: reversed or empty bounds yield `ERR_INVALID_WINDOW`, and any overlap with an existing period of the same clinic — including periods that merely touch at an endpoint — yields `ERR_BILLING_PERIOD_OVERLAP`. A new period starts `OPEN` with `gross_amount_cents`, `credit_amount_cents`, and `net_amount_cents` all zero and `finalized_at` null.

Closing a period snapshots the billable work. A `VendorAdmin` closes an `OPEN` period — any other state yields `ERR_BILLING_PERIOD_NOT_OPEN` — and the system generates one provisional line item per qualifying job: for each job, the latest transcript version whose `delivered_at` falls within the closed bounds of the period and whose status is `DELIVERED`, `SIGNED`, or `AMENDED`; a job with no such transcript contributes no item. Items are generated in job creation order, earliest `created_at` first, so that list reads are deterministic. Each item records its containing `billing_period_id` and billed `transcript_id`, snapshots the job's `priority` and the policy's `rate_per_line_cents` as they stand at close, and computes provisional figures from the speech-recognition estimate: `provisional_line_count` is the job's `asr_char_estimate` divided into sixty-five-character lines, rounded up, and `provisional_amount_cents` is that count times the snapshotted rate. The item starts in `PROVISIONAL` status, and its final fields — `final_line_count`, `final_amount_cents`, `sla_breach`, and `credit_cents` — stay null until finalize.

Finalizing converts estimates into an invoice. A `VendorAdmin` finalizes a `CLOSED` period (`ERR_BILLING_PERIOD_NOT_CLOSED` otherwise), and each item is settled against reality: `final_line_count` is taken from the billed transcript's own `line_count` — the edited text, not the recognition estimate, so the two amounts diverge whenever the editor's text diverges from the machine draft — and `final_amount_cents` is that count times the snapshotted rate. Turnaround compliance is then judged per the clinic policy's `measurement_basis`. Under `END_TO_END`, the item breaches when the transcript's `delivered_at` is strictly after the job's `due_at`; delivery exactly at the deadline is not a breach. Under `PRODUCTION_WINDOW`, the item breaches when the elapsed time from the job's `first_claimed_at` to the accepted transcript's `submitted_at` strictly exceeds `tat_minutes`; again, exactly at the target is compliant. A breaching item earns the clinic a credit: `credit_cents` is the item's `final_amount_cents` multiplied by the policy's `breach_credit_pct` percent, rounded half-up; a compliant item's credit is zero.

The rounding order at finalize is pinned and non-negotiable: round each item's credit half-up first, then sum. Summing first and rounding once is forbidden — two items of 105 cents each at a 10 percent credit yield 11 plus 11, totaling 22 cents, not the 21 that rounding a pooled 210-cent base would produce. The period rollups follow: `gross_amount_cents` is the sum of all items' `final_amount_cents`, `credit_amount_cents` is the sum of the per-item credits, and `net_amount_cents` is gross minus credit, preserving the invariant that gross equals net plus credit. Every item moves to `FINAL`, the period moves to `FINALIZED`, `finalized_at` is stamped — and from that stamp the clinic's payment grace clock runs for the billing-hold evaluation, which is recomputed on subsequent sweeps.

The billing hold itself is a derived clinic flag: `billing_hold` is true exactly when the clinic has a `FINALIZED` period whose payment window has lapsed — the current logical time at or after that period's `finalized_at` plus `payment_grace_days` days, each day counted as 86,400 seconds, with the exact boundary counting as overdue. Periods in `OPEN`, `CLOSED`, `DISPUTED`, or `SETTLED` never contribute to a hold. While the hold is true, §3.3's fiscal gate refuses new dictation uploads with `ERR_CLINIC_BILLING_HOLD`.

Disputes give the clinic a formal objection channel. A `ClientAdmin` disputes a `FINALIZED` period — anything else yields `ERR_BILLING_PERIOD_NOT_FINALIZED` — moving it to `DISPUTED`. A `VendorAdmin` then resolves a `DISPUTED` period (`ERR_BILLING_PERIOD_NOT_DISPUTED` otherwise) by supplying an `outcome`. Under `UPHELD`, all amounts stand as finalized and the period simply returns to `FINALIZED`. Under `REVERSED`, every item's `credit_cents` is zeroed, every item moves to `CREDIT_REVERSED`, the period's `credit_amount_cents` becomes zero, and `net_amount_cents` is set equal to `gross_amount_cents`, again returning the period to `FINALIZED`. Finally, a `VendorAdmin` settles a `FINALIZED` period (`ERR_BILLING_PERIOD_NOT_FINALIZED` otherwise), moving it to `SETTLED` — the terminal state — and recomputing the clinic's `billing_hold`, since a settled period never holds.

Throughout the lifecycle, the period's line items remain readable from the period, and the items billing any given transcript remain readable from the transcript, per the reverse-listing conventions of §2.10.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources (a clinic account, an SLA policy, a provider, an editor, an availability window, a dictation job, a quality review, a template, a macro, or a billing period) return a `201 Created` status code. Operations that modify an existing resource or transition it between states return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock and run the full system sweep | VendorAdmin |
| POST | `/clinic-accounts` | Create a clinic account | VendorAdmin |
| GET | `/clinic-accounts/{id}` | Get a clinic account | All roles |
| GET | `/clinic-accounts/{id}/providers` | List providers of a clinic | All roles |
| GET | `/clinic-accounts/{id}/sla-policies` | List SLA policies of a clinic | All roles |
| GET | `/clinic-accounts/{id}/billing-periods` | List billing periods of a clinic | All roles |
| POST | `/sla-policies` | Create an SLA policy row (unique per clinic and priority) | VendorAdmin |
| POST | `/providers` | Create a provider under a clinic | ClientAdmin |
| GET | `/providers/{id}` | Get a provider | All roles |
| POST | `/providers/{id}/reinstate` | Lift a signature-compliance suspension | ClientAdmin |
| GET | `/providers/{id}/templates` | List templates of a provider | All roles |
| GET | `/providers/{id}/macros` | List macros of a provider (archived excluded unless requested) | All roles |
| POST | `/editors` | Create an editor (pool member) | VendorAdmin |
| GET | `/editors/{id}` | Get an editor | All roles |
| POST | `/editors/{id}/reinstate` | Reinstate a SUSPENDED editor | VendorAdmin |
| GET | `/editors/{id}/shift-windows` | List shift windows of an editor | All roles |
| POST | `/editor-shift-windows` | Declare an editor availability window | Editor, VendorAdmin |
| POST | `/dictation-jobs` | Capture a dictation and create a job | Provider |
| GET | `/dictation-jobs/{id}` | Get a dictation job | All roles |
| GET | `/dictation-jobs` | List and filter dictation jobs | All roles |
| POST | `/dictation-jobs/{id}/claim` | Editor claims a queued job | Editor |
| POST | `/dictation-jobs/{id}/release` | Release a claimed job back to the pool | Editor, VendorAdmin |
| POST | `/dictation-jobs/{id}/submit` | Submit the edited transcript, creating the next version | Editor |
| POST | `/dictation-jobs/{id}/cancel` | Cancel a QUEUED or EDITING job | Provider, VendorAdmin |
| GET | `/transcripts/{id}` | Get a transcript | All roles |
| GET | `/transcripts` | List and filter transcripts | All roles |
| POST | `/transcripts/{id}/sign` | Provider signs a delivered transcript | Provider |
| POST | `/transcripts/{id}/return` | Provider returns a delivered transcript for rework | Provider |
| POST | `/transcripts/{id}/addend` | Provider amends a signed transcript | Provider |
| POST | `/qa-reviews` | Score a SUBMITTED job with error-severity counts | QASupervisor |
| GET | `/dictation-jobs/{id}/qa-reviews` | List QA reviews for a job | All roles |
| GET | `/transcripts/{id}/qa-reviews` | List QA reviews for a transcript | All roles |
| POST | `/provider-templates` | Create a template version, superseding the prior active one | Provider |
| PUT | `/provider-templates/{id}` | Update a template's name or body | Provider |
| POST | `/macros` | Create a provider macro | Provider |
| POST | `/macros/{id}/archive` | Soft-delete a macro | Provider |
| POST | `/billing-periods` | Create a billing period | VendorAdmin |
| GET | `/billing-periods/{id}` | Get a billing period | All roles |
| POST | `/billing-periods/{id}/close` | Close the period and generate provisional line items | VendorAdmin |
| POST | `/billing-periods/{id}/finalize` | Finalize amounts, SLA breach evaluation, credits, and rollups | VendorAdmin |
| POST | `/billing-periods/{id}/dispute` | Clinic disputes a finalized period | ClientAdmin |
| POST | `/billing-periods/{id}/resolve-dispute` | Resolve a dispute (upheld or reversed) | VendorAdmin |
| POST | `/billing-periods/{id}/settle` | Settle a finalized period | VendorAdmin |
| GET | `/billing-periods/{id}/line-items` | List line items of a period | All roles |
| GET | `/transcripts/{id}/line-items` | List line items billing a transcript | All roles |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_CLINIC_NOT_FOUND` | 404 Not Found |
| `ERR_PROVIDER_NOT_FOUND` | 404 Not Found |
| `ERR_EDITOR_NOT_FOUND` | 404 Not Found |
| `ERR_JOB_NOT_FOUND` | 404 Not Found |
| `ERR_TRANSCRIPT_NOT_FOUND` | 404 Not Found |
| `ERR_TEMPLATE_NOT_FOUND` | 404 Not Found |
| `ERR_MACRO_NOT_FOUND` | 404 Not Found |
| `ERR_BILLING_PERIOD_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_PROVIDER_VERSION` | 412 Precondition Failed |
| `ERR_STALE_TEMPLATE_VERSION` | 412 Precondition Failed |
| `ERR_PROVIDER_SUSPENDED` | 409 Conflict |
| `ERR_EDITOR_NOT_ACTIVE` | 409 Conflict |
| `ERR_JOB_NOT_QUEUED` | 409 Conflict |
| `ERR_JOB_NOT_EDITING` | 409 Conflict |
| `ERR_JOB_NOT_SUBMITTED` | 409 Conflict |
| `ERR_JOB_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_TRANSCRIPT_NOT_DELIVERED` | 409 Conflict |
| `ERR_TRANSCRIPT_NOT_SIGNED` | 409 Conflict |
| `ERR_UNSIGNED_REPORTS_REMAIN` | 409 Conflict |
| `ERR_BILLING_PERIOD_NOT_OPEN` | 409 Conflict |
| `ERR_BILLING_PERIOD_NOT_CLOSED` | 409 Conflict |
| `ERR_BILLING_PERIOD_NOT_FINALIZED` | 409 Conflict |
| `ERR_BILLING_PERIOD_NOT_DISPUTED` | 409 Conflict |
| `ERR_SELF_REVIEW_FORBIDDEN` | 403 Forbidden |
| `ERR_PROBATION_STAT_FORBIDDEN` | 403 Forbidden |
| `ERR_EDITOR_CAPACITY_FULL` | 409 Conflict |
| `ERR_DUPLICATE_MACRO_SHORTCUT` | 409 Conflict |
| `ERR_DUPLICATE_SLA_POLICY` | 409 Conflict |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_SHIFT_WINDOW_OVERLAP` | 422 Unprocessable Entity |
| `ERR_OUTSIDE_SHIFT_WINDOW` | 422 Unprocessable Entity |
| `ERR_BILLING_PERIOD_OVERLAP` | 422 Unprocessable Entity |
| `ERR_TEMPLATE_PROVIDER_MISMATCH` | 422 Unprocessable Entity |
| `ERR_TEMPLATE_WORK_TYPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_SLA_POLICY_MISSING` | 422 Unprocessable Entity |
| `ERR_CLINIC_BILLING_HOLD` | 402 Payment Required |
