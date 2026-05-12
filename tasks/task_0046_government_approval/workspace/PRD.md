# Government One-Stop Approval Platform API — Product Requirements Document

## 1. Introduction

Modern citizen-facing government services suffer from a familiar pattern of fragmentation: each department maintains its own catalog of approvable matters, its own intake forms, its own review queues, and its own signing apparatus, leaving applicants to retrace the same identity, payment, and document-collection steps for every request. This document specifies a one-stop approval platform that consolidates that surface area behind a single API. The platform owns a versioned matter catalog, a typed library of material and certificate templates, an applicant-facing submission flow, a multi-department joint-review workflow with both serial and parallel routing, a correction-notice loop with bounded retries, time-limit monitoring against statutory and committed clocks, electronic certificate issuance with verification codes, and an event ingress that absorbs identity-verification, electronic-signature, payment-settlement, and inter-department data-sharing notifications from neighboring platforms.

The system is built around segregation of duties: catalog authoring, departmental review, escalation arbitration, and certificate operations are distinct roles that may not collapse into one another. It is also built around traceability — every consequential action is mirrored into an audit log keyed by actor and target — and around determinism: identical inputs replayed in the same order must produce identical certificate serial numbers, identical fee breakdowns, and identical deadline computations. The API surface described below is the only contract between the platform and its callers; clients (applicants, departmental reviewers, certificate officers, the platform-admin console, and the ingress adapters for external platforms) all interact exclusively through it.

## 2. Global Specifications & System-Wide Principles

This section defines the structural contract that every endpoint in the platform must obey: how callers identify themselves, the JSON envelope that wraps every response, pagination conventions, and the cross-cutting domain principles that apply uniformly across catalog management, the application lifecycle, and certificate operations.

### 2.1. User and Role-Based Access Control

Every request must include two HTTP headers: `X-User-ID`, an opaque string identifying the acting principal, and `X-User-Role`, a string naming the principal's role. Either header missing or empty is rejected with `ERR_AUTH_MISSING` and HTTP status 401. A header pair that is well-formed but whose role lacks permission for the requested endpoint is rejected with `ERR_FORBIDDEN` and HTTP status 403.

The platform recognises six roles, spelled exactly as follows:

- `PlatformAdmin` — the cross-platform operator. Responsible for registering departments, resolving escalations, ingesting external events, running the periodic sweep, advancing the test clock, querying the audit log, and producing SLA-performance reports. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it on every audit-log entry as `actor_id` but does not compare it to any entity's `id`.
- `CatalogManager` — owns the matter catalog and the material-template library. When `X-User-Role` is `CatalogManager`, `X-User-ID` is the `id` of the acting `Department`; ownership checks (for example, "may this manager edit this matter?") compare the matter's `owning_department_id` to `X-User-ID`.
- `Reviewer` — a departmental reviewer who decides assigned review tasks and issues correction notices. When `X-User-Role` is `Reviewer`, `X-User-ID` is the `id` of the acting `Department`; a reviewer may only act on a `ReviewTask` whose `department_id` equals `X-User-ID`.
- `LeadReviewer` — a designated reviewer in the lead department of a routing definition. Carries every Reviewer capability plus the right to escalate disagreements. When `X-User-Role` is `LeadReviewer`, `X-User-ID` is the `id` of the acting `Department`; the same `department_id` ownership check applies, with the additional constraint that the department must be the routing's lead department to escalate.
- `CertificateOfficer` — owns certificate templates and the reissue workflow. Cannot review applications or escalate (segregation of duties). When `X-User-Role` is `CertificateOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it on audit entries but does not match it against any department.
- `Applicant` — an end user submitting and tracking applications. When `X-User-Role` is `Applicant`, `X-User-ID` is an opaque applicant identifier not tied to any persisted entity; the server records it on each submitted `Application` as `applicant_user_id`, and ownership checks on application-scoped reads and on withdrawal and resubmission compare `applicant_user_id` to `X-User-ID`.

A single physical user acting as a `Reviewer` or `LeadReviewer` on an application may not also be that application's applicant — the server compares `X-User-ID` against the application's `applicant_user_id` at decide-time, correction-issue-time, and escalate-time, and rejects the action with `ERR_FORBIDDEN` when the two coincide.

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

For endpoints that return lists of resources, pagination is controlled by two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, has a minimum of 1, and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0.

Unless an endpoint description says otherwise, list endpoints return resources sorted by `created_at` in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Most top-level resources (`Department`, `Matter`, `MatterVersion`, `MaterialTemplate`, `Application`, `ReviewTask`, `CertificateTemplate`, `Certificate`) carry a uniform set of system-managed fields:

- `id` — a server-minted UUID with no type prefix; immutable.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set once at creation.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` — an integer that starts at 1 on creation and increments by 1 on every mutation, including the cascading mutations described in §2.5 (for example, when the publication of a new `MatterVersion` flips a previously published sibling to `SUPERSEDED`, both versions and the parent `Matter` each receive a `version` increment).

Two resources are deliberately log-shaped and carry only `id` and `created_at` — `updated_at` and `version` are absent because they are append-only and never mutated after insert: `CorrectionNotice` (the notice itself is immutable; its lifecycle status is updated through resubmit/expire transitions that nevertheless preserve the create-time semantics described in §3 — the server still tracks `status` and `resolved_at` as documented but no `version` field is exposed) — and `ExternalEvent` and `AuditLog`. To eliminate ambiguity: `CorrectionNotice` and `ExternalEvent` and `AuditLog` all omit both `updated_at` and `version`.

### 2.5. Hierarchical Consistency and Cascading Side Effects

A single client request frequently touches multiple resources, and the platform is responsible for keeping the resulting graph self-consistent. Three concrete patterns recur. First, publishing a draft `MatterVersion` flips the previously published sibling — if any — to `SUPERSEDED` in the same request, repoints `Matter.current_published_version_id` to the newly published version, and sets `Matter.status` to `PUBLISHED`; the prior `MatterVersion` becomes read-only but in-flight applications keep their pinned `matter_version_id` and continue against the rules they snapshotted. Second, retiring a `PUBLISHED` or `SUPERSEDED` version requires that no application whose `review_status` is outside `{APPROVED, REJECTED, WITHDRAWN}` references it; if the retired version was the current published version, `Matter.current_published_version_id` is cleared, and if no other `PUBLISHED` version exists for the matter, `Matter.status` flips to `ARCHIVED`. Third, terminal application transitions cascade: when an `Application` reaches `REJECTED`, `WITHDRAWN`, or `APPROVED` via escalation, every non-terminal `ReviewTask` of that application is flipped to `SKIPPED` in the same request; refund cascades on `payment_status` are described in §3.

Every cascade above is a real mutation: each affected resource has its `updated_at` refreshed and its `version` incremented (where `version` is part of that resource's contract per §2.4). Cascades are a serialization point — see §2.10 for the optimistic-concurrency consequences of doing work against a stale resource version.

### 2.6. Nested Resource Retrieval

Many endpoints address a child resource through its parent — for example `/matters/{matter_id}/versions/{version_id}` or `/applications/{id}/correction-notices/{cid}/resubmit`. Path parameters are validated strictly left-to-right: the parent `Matter`, `Application`, or `Certificate` is resolved first, and only if it exists does the server attempt to resolve the child. A missing parent yields `ERR_NOT_FOUND` for the parent identifier, never a child-level error. The same ordering governs validation: existence (priority 3) is checked before state (priority 4), and state is checked before any business-referential or business-constraint rule, regardless of the order in which fields appear in the request body.

### 2.7. Validation Priority

When a single endpoint is guarded by multiple validation rules, the server evaluates them in a fixed priority order so that the same request always produces the same `error_id`. The ordering, from highest priority (evaluated first) to lowest, is: authentication header presence, then role permission, then path-parameter existence, then target-resource state, then SERIAL-routing stage ordering for review-task decisions, then the application-submission referential and constraint checks (every required material covered, then each material type and its template's published status, then e-form schema completeness for ONLINE applications, then channel allowed by routing), then resubmit temporal validity, then per-correction round budget, then deficiency coverage on resubmit, then the publish-time template and time-limit and routing constraints, then deficiency well-formedness on issuance, then escalation eligibility, then certificate-already-reissued, then optimistic concurrency check, then idempotency key handling for inbound external events. A higher-priority failure short-circuits — the lower-priority checks are not evaluated and their `error_id` cannot surface for that request.

Generic field-level format and presence problems that fall outside the named business rules (for instance, a string supplied where an integer is required, or a missing required input on a body that otherwise reaches the validation pipeline) are reported as `ERR_VALIDATION_FAILED` with HTTP status 422. Unique-field collisions — Department `code`, Matter `code`, MatterVersion `version_label` within a matter, MaterialTemplate `code`, CertificateTemplate `code` — are reported as `ERR_DUPLICATE_RESOURCE` with HTTP status 409.

### 2.8. Time, Working Days, and Precision

The platform models time at integer-second resolution; no fractional seconds are stored on derived deadline or paused-window values. A "working day" is exactly eight hours, i.e. 28,800 seconds (`WORKING_DAY_SECONDS`); whenever the catalog speaks of a time-limit in working days, the system multiplies by this constant before working in seconds. Percentages computed from elapsed time use integer division (truncated) — for example, an `active_elapsed` of 99% of `committed_seconds` rounds down to 99, never up to 100. Boundary semantics for time-limit comparisons are uniformly inclusive on the upper edge: a percentage of exactly 100 is already `OVERDUE`, and a percentage of exactly the configured `warning_threshold_pct` is already `WARNING`; an `expires_at` that is exactly equal to the current server time has reached expiry.

Monetary fee amounts are integer cents end-to-end. The fee breakdown is computed via a pinned-order ceiling rule (see §3), and the result is the literal sum of integer-cent components. `version` values are always integers; `id` values are always UUIDs without any type prefix.

### 2.9. Working-Day Arithmetic for Correction Windows and Stage Deadlines

`correction_window_days` (default 7, range 1–30) on each `MatterVersion` defines, in working days, how long an applicant has to resubmit a given `CorrectionNotice`. The resulting `due_at` is `issued_at` plus that many working days converted into seconds — so a window of 7 working days is 201,600 seconds added to `issued_at`. Per-stage SLA deadlines (`stage_due_at` on each `ReviewTask`) are computed identically: the routing's `sla_days` for that stage, multiplied by `WORKING_DAY_SECONDS`, added to the time the stage entered `IN_PROGRESS`.

### 2.10. Optimistic Concurrency Control

Every mutation endpoint that targets a resource carrying a `version` field accepts an optional `version` integer in the request body. When supplied, it must equal the resource's current `version`; mismatch is rejected with `ERR_VERSION_CONFLICT` and HTTP status 409. When the field is omitted, the server skips the optimistic-concurrency check and applies the mutation against the current state — callers that care about losing-write detection are expected to submit `version`. Cascading mutations described in §2.5 are themselves serialization points: a write that proceeded without `version` and was then beaten to a cascade may still fail the cascade's downstream state precondition, surfacing as `ERR_INVALID_STATE`.

### 2.11. Concurrency Resolution

Several races between simultaneous writers have explicit, named outcomes. When two reviewers in different departments race on the only outstanding `ReviewTask` of a SERIAL routing, only the writer holding the lowest `stage_index` PENDING-or-IN_PROGRESS task can decide; any later-stage attempt is rejected with `ERR_REVIEW_OUT_OF_ORDER`. When a reviewer issues a correction notice while another reviewer simultaneously decides AGREED on the same application, exactly one operation succeeds — the loser observes that the application's `review_status` has changed and is rejected with `ERR_INVALID_STATE`. When an applicant resubmits at the boundary while a system sweep marks the same `CorrectionNotice` `EXPIRED`, the resubmit succeeds only if its server-side `now()` is at or before `due_at`; otherwise it is rejected with `ERR_CORRECTION_EXPIRED`. When two reissue requests fire concurrently on the same source `Certificate`, at most one new `Certificate` is created — the loser sees that `superseded_by_certificate_id` is already set and is rejected with `ERR_CERTIFICATE_ALREADY_REISSUED`. When a `CatalogManager` publishes a draft version V2 while another retires V1 of the same matter, exactly one transition wins on `Matter.current_published_version_id`: if V1 retires first, publishing V2 succeeds and V1 is already `RETIRED` so no auto-supersede occurs; if V2 publishes first, V1 auto-transitions from `PUBLISHED` to `SUPERSEDED` before the retire request arrives, and the retire is honoured against the `SUPERSEDED` state. When the loser of either race violates a state precondition, the response is `ERR_INVALID_STATE`.

### 2.12. Idempotent External-Event Ingress

Inbound notifications from neighbouring platforms — identity verification, electronic signature, payment settlement, inter-department data sharing — flow through a single ingress endpoint. Each event carries an `event_type`, an `idempotency_key` that the source platform guarantees unique within `event_type`, a `subject_application_id`, and a free-form `payload`. A duplicate `(event_type, idempotency_key)` pair is absorbed: the server returns the previously stored `ExternalEvent` unchanged with HTTP status 200, `processed` reflecting the original outcome, and no side effects are re-applied. The first delivery for a given `(event_type, idempotency_key)` is processed exactly once; the duplicate-on-second-delivery contract holds across server restarts.

### 2.13. Audit Trail

Consequential actions write a single `AuditLog` row capturing `actor_role` (the snapshot of `X-User-Role` at the moment of action), `actor_id` (the snapshot of `X-User-ID`), the `action` enum, `target_entity` (the entity name, e.g., `Application`), `target_id` (the affected entity's `id`), and a sanitized `payload_snapshot` of the request body. The `action` enum covers `APPLICATION_SUBMIT`, `REVIEW_DECIDE`, `CORRECTION_ISSUE`, `CORRECTION_RESUBMIT`, `ESCALATE`, `APPROVE`, `REJECT`, `CERT_ISSUE`, `CERT_REISSUE`, and `CERT_REVOKE`. Audit log rows are append-only — `created_at` is recorded; `updated_at` and `version` are absent, as called out in §2.4.

### 2.14. Test-Driving the Logical Clock

To make time-gated state transitions observable in automated tests, the platform exposes two administrative endpoints. A test-only clock-advance capability (admin-restricted) accepts a `seconds` integer and advances the server's logical `now()` by that amount; correction-window expirations and certificate-validity expirations become immediately observable as a result. A test-only sweep capability (also admin-restricted) runs the periodic sweep on demand: every `OPEN` `CorrectionNotice` whose `due_at` is now past flips to `EXPIRED` and cascades its application to `REJECTED`; every `ACTIVE` `Certificate` whose `expires_at` is at or before `now()` flips to `EXPIRED`; and the time-limit warning evaluator is recomputed for every in-flight application.

## 3. Business Logic & Workflows

This section is organised by lifecycle stage rather than by entity. We follow the journey of a matter from authoring through publication, then the journey of an application from submission through a final certificate, weaving in the cross-cutting concerns — fees, deadlines, escalations, certificate operations, audit — at the points where they bind to a workflow event.

### 3.1. Authoring the Matter Catalog

A `Department` is the unit of organisational identity behind every catalog and review action. Each carries a stable `code` (uppercase letters and underscores, 3–32 characters, unique across the platform), a human-readable `name`, an optional `parent_department_id` that points at a parent department for hierarchical override and escalation routing (null at the top of the hierarchy), and a `status` of either `ACTIVE` or `ARCHIVED` defaulting to `ACTIVE`. A new department is registered by `PlatformAdmin` and may be filtered by `parent_department_id` and `status` in the list endpoint.


A `CatalogManager` opens a new matter by minting a `Matter` shell with a stable `code` (4–64 characters, unique across the catalog), a `theme` drawn from `BIRTH`, `EDUCATION`, `BUSINESS`, `HOUSING`, `TRANSPORT`, `SOCIAL_SECURITY`, or `OTHER`, and an `owning_department_id` that points at the department responsible for the matter. The new shell's `status` is `DRAFT_ONLY` and its `current_published_version_id` is null until the first version is published. The shell occupies the URL slot `matter_id` for every nested address — for example, the create-version path embeds `matter_id` and a fresh `version_id` is minted as the version's primary key.

A `Matter` in isolation is inert; its substance lives in successive `MatterVersion` rows. Each version carries a `matter_id` linking it back to its parent and a `version_label` that is unique within that parent matter (1–32 characters; collisions are rejected with `ERR_DUPLICATE_RESOURCE`). Version content combines a regulatory and operational profile: a free-text `legal_basis` block, free-text `conditions` describing eligibility, an ordered `required_material_template_ids` listing every material an applicant must submit, two time-limit dimensions (`statutory_time_limit_days` between 1 and 365, and `committed_time_limit_days` between 1 and the version's `statutory_time_limit_days` — a publish that violates this inequality is rejected with `ERR_TIME_LIMIT_INVERSION`), a `warning_threshold_pct` between 50 and 99 (default 80) that drives the time-limit warning evaluator, a `fee_amount_cents` defaulting to 0 with a non-negative constraint, a non-empty `channels` subset of `{ONLINE, OFFLINE}`, a `review_routing` object detailed in §3.2, a `max_correction_rounds` between 1 and 5 (default 2), a `correction_window_days` between 1 and 30 (default 7), and a `certificate_template_id` pointing at the certificate-template the version will issue on approval. New versions begin in `DRAFT` with `published_at` null.

Publishing the version is the flip from `DRAFT` to `PUBLISHED`. The publish request enforces a constellation of preconditions: every `MaterialTemplate` referenced in `required_material_template_ids` must already be in `status` `PUBLISHED` and the referenced `CertificateTemplate` must likewise be `PUBLISHED`, otherwise the request is rejected with `ERR_DEPENDENT_TEMPLATE_UNPUBLISHED`; the routing must satisfy the rules in §3.2; and `committed_time_limit_days` must remain at or below `statutory_time_limit_days`. On success, `published_at` is set to the server's current time, `Matter.current_published_version_id` repoints to this version, and `Matter.status` becomes `PUBLISHED`. If a previously `PUBLISHED` sibling existed, it is auto-cascaded from `PUBLISHED` to `SUPERSEDED` in the same request — that sibling becomes read-only but in-flight applications retain their pinned `matter_version_id` and continue against the rules they snapshotted at submission.

A `PUBLISHED` or `SUPERSEDED` version may be retired by the same `CatalogManager` role. Retirement requires that no application whose `review_status` falls outside `{APPROVED, REJECTED, WITHDRAWN}` still references the version; retirement of a `PUBLISHED` version that equals the matter's `current_published_version_id` clears that pointer, and if the matter then has no surviving `PUBLISHED` version its `status` flips to `ARCHIVED`. `RETIRED` is terminal.

### 3.2. Routing Definitions: Who Decides, In What Order

The `review_routing` object on each `MatterVersion` defines how reviews are coordinated across departments. It has four keys: `mode`, `lead_department_id`, `stages`, and `aggregation_rule`. `mode` is either `SERIAL` or `PARALLEL`. `stages` is an ordered array of one or more stage objects, each carrying a `department_id` and an `sla_days` (per-stage working-day deadline). `lead_department_id` must equal the `department_id` of one of the entries in `stages`. `aggregation_rule` is required when `mode` is `PARALLEL` and must be one of `ALL_AGREE`, `MAJORITY`, or `LEAD_DECIDES`; when `mode` is `SERIAL`, `aggregation_rule` must be null and a single rejection at any stage ends the review. Any deviation from these rules is rejected with `ERR_ROUTING_INVALID` at version-create time and again at publish time.

When an application enters review, the platform deep-copies `review_routing` into the application's `pinned_routing_snapshot` and creates one `ReviewTask` per stage, each pinned to its `stage_index` (0-based into `pinned_routing_snapshot.stages`) and its `department_id`, and with `is_lead` set to true exactly when `department_id` equals `pinned_routing_snapshot.lead_department_id`. From that point on, even if the underlying `MatterVersion`'s routing were edited (it cannot be — published versions are read-only), the application would continue against the snapshot.

For `SERIAL` routing only the `stage_index` 0 task transitions from `PENDING` to `IN_PROGRESS` immediately; later stages stay `PENDING` and become `IN_PROGRESS` one at a time as the predecessor stage transitions to `AGREED`. Any attempt to decide a later stage before its predecessor has agreed is rejected with `ERR_REVIEW_OUT_OF_ORDER`. For `PARALLEL` routing every stage's task transitions to `IN_PROGRESS` at once.

### 3.3. Material and Certificate Templates

The catalog draws on two template libraries authored independently from any specific matter. A `MaterialTemplate` carries a stable `code` (4–64 characters, unique), a display `title`, a `material_type` of `ORIGINAL`, `COPY`, or `NOTARIZED`, an optional `form_url` for downloading a blank template, an optional `example_url` for reference samples, and an optional `e_form_schema` JSON-Schema-shaped object; when `e_form_schema` is present, ONLINE applications using this template must attach a payload conforming to the listed required keys. New templates start in `DRAFT`; a separate publish step transitions them to `PUBLISHED`. `RETIRED` is terminal but is not directly addressed by an API — withdrawn templates are cleared from active versions through the catalog flow.

A `CertificateTemplate` carries a stable `code`, a Mustache-style `body_template` whose placeholders are listed in `required_variables` (every entry of `required_variables` must appear in `body_template`), a `validity_days` integer (default 0, non-negative; 0 means the issued certificate has no expiration), and an `official_seal_id` identifying the seal asset embedded on issuance. Templates begin in `DRAFT`; only `PUBLISHED` certificate templates can be referenced from a `MatterVersion`'s `certificate_template_id` at publish time.

### 3.4. Submitting an Application

An applicant initiates an application by referencing a `matter_version_id` (which is pinned at submission and will not change for the life of the application), choosing a `channel` of `ONLINE` or `OFFLINE`, and providing `submitted_materials`. Each submitted-material entry is a small object with a `material_template_id`, an `attachment_ref`, and an optional `e_form_payload`. The submission endpoint enforces a sequence of business-referential and business-constraint checks in fixed order (per §2.7): every entry of the pinned version's `required_material_template_ids` must be covered by exactly one matching `submitted_materials` entry (failure is `ERR_MATERIAL_MISSING`); each submitted entry's `material_template_id` must reference a `MaterialTemplate` whose `status` is `PUBLISHED` and whose `material_type` matches the submitted material type (failure is `ERR_MATERIAL_TYPE_MISMATCH`); when the `channel` is `ONLINE` and any covered template carries an `e_form_schema`, the corresponding `e_form_payload` must include every required key listed in that schema (failure is `ERR_EFORM_INCOMPLETE`); and the chosen `channel` must appear in the pinned version's `channels` set (failure is `ERR_CHANNEL_NOT_ALLOWED`).

A successful submit creates an `Application` whose `review_status` is `SUBMITTED`, whose `applicant_user_id` is the `X-User-ID` of the submitting principal, and whose `correction_round` is 0. The application's `payment_status` begins at `PENDING` unless the pinned version's `fee_amount_cents` is 0, in which case `payment_status` is set to `PAID` immediately at create time (the only legal value transitions are `PENDING → PAID` and a refund cascade `PAID → REFUNDED`). `identity_verified` is false at create time. `clock_started_at`, `deadline_at`, and `pinned_routing_snapshot` remain null until the application transitions to `UNDER_REVIEW`. `total_paused_seconds` starts at 0. The submission writes an `AuditLog` row with `action` `APPLICATION_SUBMIT`.

An applicant may withdraw before review begins or while review is under way, but with a guardrail: withdrawal from `SUBMITTED` is unconditional, while withdrawal from `UNDER_REVIEW` requires that no `ReviewTask` has yet reached `DISAGREED` — this prevents an applicant from dodging an imminent rejection. Both withdrawal paths flip the application's `review_status` to `WITHDRAWN`, cascade every non-terminal `ReviewTask` to `SKIPPED`, and — when `payment_status` is `PAID` and the pinned version's `fee_amount_cents` is greater than 0 — refund the payment by setting `payment_status` to `REFUNDED`. Withdrawal from `SUBMITTED` while no `ReviewTask` rows exist still applies the refund cascade unconditionally if the application was paid up front because of a zero-fee version-then-fee race — but in that case the refund is a no-op since the fee is 0. Withdrawal of an application that has already reached a terminal state is rejected with `ERR_INVALID_STATE`.

### 3.5. The Identity-and-Payment Gate, and Entry Into Review

An application sits in `SUBMITTED` until two facts are independently true: `identity_verified` is true and `payment_status` is `PAID`. Both flips arrive over the inbound external-event ingress (§2.12). An `IDENTITY_VERIFIED` event flips `identity_verified` to true on the named application; a `PAYMENT_SETTLED` event flips `payment_status` from `PENDING` to `PAID`. Each event also sets its own `processed` field to true after the side effect lands; `SIGNATURE_AFFIXED` and `DATA_SHARED` events are accepted, recorded, and acknowledged but do not directly drive the state machine — they are kept on the application's audit-adjacent timeline for downstream consumers.

The instant both prerequisites hold — and provided the pinned `MatterVersion`'s `status` is in `{PUBLISHED, SUPERSEDED}` so that the version is still legally usable — the system transitions the application from `SUBMITTED` to `UNDER_REVIEW`. That transition takes a deep copy of `MatterVersion.review_routing` into `pinned_routing_snapshot`, creates the `ReviewTask` rows described in §3.2, sets `clock_started_at` to the server's current time, and computes the initial `deadline_at` using the committed-variant of the deadline calculation described in §3.7.

### 3.6. The Joint-Review Loop

A reviewer eligible for a given `ReviewTask` (a principal whose role is `Reviewer` or `LeadReviewer` and whose `X-User-ID` equals the task's `department_id`) decides by submitting a `decision` of `AGREED` or `DISAGREED` and an optional `opinion_text`. The decision is rejected with `ERR_INVALID_STATE` if the application is not currently `UNDER_REVIEW`, or if any `OPEN` `CorrectionNotice` exists for the application — open corrections pause every `IN_PROGRESS` task. On success, the task records `decided_at` as the server's current time and stores the `opinion_text` (which becomes part of the audit-adjacent record for that task). The decision then triggers the opinion-aggregation rule (§3.8); if aggregation returns a final verdict, the application transitions accordingly in the same request.

For `SERIAL` routing, an `AGREED` decision on the current stage promotes the next stage's task from `PENDING` to `IN_PROGRESS` and arms its `stage_due_at` per §2.9. For `PARALLEL` routing every task is already `IN_PROGRESS`, so an `AGREED` decision merely shrinks the set of outstanding tasks. A `DISAGREED` decision in `SERIAL` short-circuits the review (see §3.8). Every decision writes an `AuditLog` row with `action` `REVIEW_DECIDE`.

A reviewer who finds the application incomplete issues a `CorrectionNotice` instead of deciding. The issuance request takes a non-empty `deficiencies` array — each entry naming a `material_template_id` and a `reason` — and an `issued_by_review_task_id` identifying the reviewer's own task. The issuance is rejected with `ERR_DEFICIENCY_INVALID` if `deficiencies` is empty or if any `material_template_id` is not present in the pinned version's `required_material_template_ids`; with `ERR_MAX_ROUNDS_REACHED` if `correction_round` already equals the pinned version's `max_correction_rounds`; and with `ERR_INVALID_STATE` if the issuing `ReviewTask`'s status is not `IN_PROGRESS`. On success, a new `CorrectionNotice` row is created with `round_number` equal to the application's `correction_round` plus one, the application's `correction_round` is incremented by one, the application's `review_status` flips to `AWAITING_CORRECTION`, the notice's `issued_at` is set to the server's current time, the notice's `due_at` is set to `issued_at` plus `correction_window_days` working days as defined in §2.9, and every `IN_PROGRESS` `ReviewTask` is paused until the application returns to `UNDER_REVIEW`. The notice's initial `status` is `OPEN` and `resolved_at` is null. The issuance writes an `AuditLog` row with `action` `CORRECTION_ISSUE`.

The applicant resolves an open notice by resubmitting materials. The resubmit request addresses the notice through the URL slot `cid` and takes an updated `submitted_materials` array. It is rejected with `ERR_CORRECTION_EXPIRED` if the current server time is past the notice's `due_at` (the comparison is inclusive of equality on the early side: a resubmit at exactly `due_at` is still on time); with `ERR_INVALID_STATE` if the notice is not currently `OPEN`; and with `ERR_DEFICIENCY_UNRESOLVED` if any deficiency listed on the notice is not addressed by a matching entry in the new `submitted_materials`. On success, the notice's `status` becomes `RESOLVED`, its `resolved_at` is set, the application's `total_paused_seconds` is increased by the integer number of seconds elapsed between `issued_at` and the current server time, the application's `deadline_at` is recomputed via the deadline calculation, every previously paused `ReviewTask` resumes at the same status it held when the notice was issued, and the application's `review_status` flips back to `UNDER_REVIEW`. The resubmit writes an `AuditLog` row with `action` `CORRECTION_RESUBMIT`.

A notice that is left `OPEN` past its `due_at` is swept to `EXPIRED` (either organically by the periodic sweep capability or by the test-only sweep). Expiration cascades the application from `AWAITING_CORRECTION` to `REJECTED`, every non-terminal `ReviewTask` is flipped to `SKIPPED`, and an `AuditLog` row with `action` `REJECT` and a reason describing correction failure is recorded.

### 3.7. Time-Limit Monitoring: Two Variants of the Same Clock

Every application that has entered `UNDER_REVIEW` carries `clock_started_at`, set once and never modified, plus a monotonically increasing `total_paused_seconds` that absorbs every correction window the application sits in `AWAITING_CORRECTION`. From these two values plus the pinned `MatterVersion`'s time-limit configuration, the platform derives the application's `deadline_at` and a real-time time-limit warning indicator.

The deadline calculation runs in two variants. The committed variant — used for all SLA monitoring, all warning-threshold computations, and any escalation alert that drives state transitions — uses `committed_time_limit_days` as its base; the statutory variant — used only for governance reporting and overtime escalation alerts that do not drive automated rejection — uses `statutory_time_limit_days`. In both variants the calculation is the same: take the pinned version's days field, multiply by `WORKING_DAY_SECONDS` (28,800) to obtain `base_window_seconds`, anchor on `clock_started_at` to obtain a `raw_deadline` of `clock_started_at` plus `base_window_seconds`, and then push the deadline outward by the application's current `total_paused_seconds` to obtain `adjusted_deadline`. The result, evaluated under the committed variant, is written back to `Application.deadline_at`. Because `committed_time_limit_days` is at most equal to `statutory_time_limit_days`, the committed variant always yields the earlier deadline and the statutory variant always yields the later deadline; the statutory deadline never drives a rejection but does drive admin-only governance alerts.

The deadline is recomputed on two specific events: when the application first enters `UNDER_REVIEW` (where `total_paused_seconds` is zero), and again whenever a correction window closes by either resubmit or expire — so a long correction window pushes the deadline outward by exactly the seconds the application waited.

The time-limit warning evaluator runs whenever an SLA snapshot is read, and again at every clock-advance. It computes `total_elapsed` as the difference in seconds between the current server time and `clock_started_at`, then `active_elapsed` as `total_elapsed` minus `total_paused_seconds`, then `committed_seconds` as `committed_time_limit_days` times `WORKING_DAY_SECONDS`, and finally `pct` as `active_elapsed` multiplied by 100, divided by `committed_seconds` using integer division (the fractional part is dropped). The status returned is `ON_TRACK` when `pct` is strictly less than `warning_threshold_pct`, `WARNING` when `pct` is at least `warning_threshold_pct` and strictly less than 100, and `OVERDUE` when `pct` is at least 100 — a `pct` of exactly 100 is already `OVERDUE`. A `pct` at or above 150 (`ESCALATION_PCT`) additionally schedules an admin-side escalation alert; if the statutory variant is also breached the alert is annotated accordingly. Applications that have not yet entered `UNDER_REVIEW` have `clock_started_at` null; for them the SLA snapshot reports an elapsed of 0 and a status of `NOT_STARTED`.

### 3.8. Aggregating Opinions Into a Final Verdict

Each time a `ReviewTask` reaches `AGREED` or `DISAGREED`, the platform runs the opinion-aggregation rule across every non-`SKIPPED` `ReviewTask` for the same application, ordered by `stage_index` ascending and then by `created_at` ascending. The rule consults `pinned_routing_snapshot.mode` and, for `PARALLEL`, `pinned_routing_snapshot.aggregation_rule`. The result is one of three discrete values: `AGREED`, `DISAGREED`, or `PENDING`.

Under `SERIAL` routing, a single `DISAGREED` task short-circuits the result to `DISAGREED` immediately — the remaining stages do not need to decide. If every task has reached `AGREED`, the result is `AGREED`. Otherwise the result is `PENDING`.

Under `PARALLEL` routing with `aggregation_rule` `ALL_AGREE`, a single `DISAGREED` task short-circuits to `DISAGREED`; if every task has reached `AGREED` the result is `AGREED`; otherwise `PENDING`. Under `MAJORITY`, the result remains `PENDING` until every non-`SKIPPED` task has decided (i.e., the number of `AGREED` tasks plus the number of `DISAGREED` tasks equals the count of non-`SKIPPED` tasks); when that happens, the result is `AGREED` if the count of `AGREED` tasks is strictly greater than the count of `DISAGREED` tasks, and `DISAGREED` otherwise (equal counts resolve to `DISAGREED`). Under `LEAD_DECIDES`, the result is `AGREED` as soon as the lead task — the unique task whose `is_lead` is true — reaches `AGREED`, `DISAGREED` as soon as the lead task reaches `DISAGREED`, and `PENDING` otherwise; the non-lead tasks' statuses do not change the verdict.

When the aggregator returns `AGREED`, the application transitions from `UNDER_REVIEW` to `APPROVED` in the same request, the certificate-issuance routine of §3.10 runs, and an `AuditLog` row with `action` `APPROVE` is written. When the aggregator returns `DISAGREED`, the application transitions from `UNDER_REVIEW` to `REJECTED`; if `payment_status` is `PAID` and the pinned `fee_amount_cents` is greater than 0, the payment is refunded by setting `payment_status` to `REFUNDED`; an `AuditLog` row with `action` `REJECT` is written. When the aggregator returns `PENDING`, no transition occurs.

### 3.9. Escalation: Resolving Disagreements That Aggregation Alone Cannot

A `LeadReviewer` of the lead department of a `PARALLEL` routing whose `aggregation_rule` is not `LEAD_DECIDES` may escalate when at least one `ReviewTask` for the application has reached `AGREED` and at least one has reached `DISAGREED` — that is, a real disagreement exists. Any escalation that does not satisfy these three preconditions (PARALLEL routing, aggregation rule different from `LEAD_DECIDES`, current disagreement among decided tasks) is rejected with `ERR_ESCALATION_NOT_PERMITTED`.

The escalation request flips the application from `UNDER_REVIEW` to `ESCALATED`, pauses every `IN_PROGRESS` `ReviewTask` (no further opinions are accepted while `ESCALATED`), and routes the dispute to the parent of the routing's lead department if such a parent exists, or to `PlatformAdmin` if the lead department is at the top of the hierarchy. An `AuditLog` row with `action` `ESCALATE` is written.

A `PlatformAdmin` resolves the escalation by submitting a `decision` of either `AGREED` or `DISAGREED`. An `AGREED` resolution transitions the application from `ESCALATED` to `APPROVED`, marks every still-`PENDING` or `IN_PROGRESS` `ReviewTask` as `AGREED` with a system-attributed opinion, runs the certificate-issuance routine of §3.10, and writes an `APPROVE` audit row. A `DISAGREED` resolution transitions the application from `ESCALATED` to `REJECTED`, marks every still-`PENDING` or `IN_PROGRESS` `ReviewTask` as `DISAGREED` with a system-attributed opinion, refunds the payment by setting `payment_status` to `REFUNDED` when `payment_status` is `PAID` and the pinned `fee_amount_cents` is greater than 0, and writes a `REJECT` audit row.

### 3.10. Certificate Issuance, Verification, Revocation, and Reissuance

When an application transitions to `APPROVED` — whether organically through aggregation or through escalation resolution — the platform issues a `Certificate` against the `CertificateTemplate` named on the pinned `MatterVersion.certificate_template_id`. Issuance proceeds in five steps. First, the platform looks up each variable name in the template's `required_variables` against the application and its pinned matter version, and renders each value into `rendered_vars`; numeric variables are rounded to 2 decimal places using round-half-up before substitution, while string and datetime variables are formatted directly. Second, every `{{name}}` placeholder in the template's `body_template` is literally substituted with the matching entry from `rendered_vars`, and the result is stored as `rendered_body`. Third, `serial_number` is generated as `GOV-{matter.code}-{YYMMDD}-{6-digit zero-padded sequence}`, where the sequence is the next-per-day sequence for that matter code in UTC. Fourth, `verification_code` is generated as a 16-character alphanumeric string derived from a UUID4 combined with the serial number and base32-encoded; the leading 16 characters of the encoded result form the value. Fifth, `expires_at` is set to null when the template's `validity_days` is 0; otherwise it is computed as `issued_at` plus `validity_days` multiplied by the day-in-seconds constant of 86,400. The new `Certificate` records its `application_id`, the pinned `certificate_template_id`, the generated `serial_number`, `verification_code`, and `rendered_body`, the `issued_at` timestamp, the computed `expires_at`, an initial `status` of `ACTIVE`, and a null `superseded_by_certificate_id`. A `CERT_ISSUE` audit row is written.

A public verification endpoint accepts a `verification_code` and returns a minimal status snapshot — sufficient for an external party to confirm the certificate exists and report its current `status`, `issued_at`, and `expires_at`. The verification surface deliberately omits the rendered body and the audit-adjacent metadata.

An `ACTIVE` `Certificate` whose `expires_at` is at or before the current server time transitions automatically to `EXPIRED` when the periodic sweep (or the test-only sweep) runs. A `PlatformAdmin` may also revoke an `ACTIVE` certificate explicitly by submitting an optional `reason`; the certificate flips from `ACTIVE` to `REVOKED` and a `CERT_REVOKE` audit row is written.

A `CertificateOfficer` may reissue a certificate that is `ACTIVE` or `EXPIRED`, provided the underlying application's `review_status` is `APPROVED`. Reissue creates a fresh `Certificate` row using the same `certificate_template_id` as the source, with a fresh `serial_number`, a fresh `verification_code`, a fresh `issued_at`, and a fresh `expires_at` derived from the new `issued_at`; the source certificate's `superseded_by_certificate_id` is then set to the new certificate's `id` and its `status` flips from its prior value to `REISSUED`. A reissue request against a source whose `superseded_by_certificate_id` is already non-null is rejected with `ERR_CERTIFICATE_ALREADY_REISSUED`. The action writes a `CERT_REISSUE` audit row.

### 3.11. The Fee Breakdown

For every application, the platform exposes a fee-breakdown projection that itemises what the applicant will be charged. The breakdown has four components: the base fee, a per-correction surcharge subtotal, an independently-computed handling line, and an independently-computed administrative-overhead line.

The base fee in cents equals the pinned `MatterVersion`'s `fee_amount_cents`. The per-correction surcharge subtotal in cents is 0 when the application's `correction_round` is 0; for `correction_round` between 1 and 2 inclusive it equals the per-round surcharge constant of 500 cents (i.e., 5.00 yuan per round) multiplied by `correction_round`; and for `correction_round` strictly greater than 2 it is capped at the surcharge cap of 1,000 cents (i.e., 10.00 yuan).

Two percentage lines are computed independently and each rounded by ceiling to integer cents before any addition. The handling line in cents equals the base fee in cents multiplied by the handling-rate basis points (200 basis points, i.e., 2.00%), divided by 10,000, and ceilinged to the next integer cent. The administrative-overhead line in cents equals the surcharge subtotal in cents multiplied by the overhead-rate basis points (500 basis points, i.e., 5.00%), divided by 10,000, and ceilinged to the next integer cent.

The total in cents is then the literal sum of four integer values: the base fee, the handling line, the surcharge subtotal, and the administrative-overhead line — in that order. The order of operations is mandatory: each percentage line must be ceilinged to integer cents on its own multiplicand before being added into the total. The naive alternative — adding base and surcharge first, applying the combined rate to that sum, and ceiling-rounding once at the end — produces a different cents value for many inputs and is the wrong answer.

The breakdown has two reporting variants. The provisional variant is the form reported while the application is still in `SUBMITTED`, `UNDER_REVIEW`, `AWAITING_CORRECTION`, or `ESCALATED`: `correction_round` is the current running count and the total may rise as new corrections are issued. The final variant is the form reported once the application is in `APPROVED`, `REJECTED`, or `WITHDRAWN`: the breakdown is frozen at the `correction_round` value at the moment of the terminal transition and never recomputes thereafter.

### 3.12. Reading the Application

Reading the application detail returns the full `Application` resource with its current `review_status`, `payment_status`, `correction_round`, `deadline_at`, `clock_started_at`, `total_paused_seconds`, and `pinned_routing_snapshot`, supplemented by the SLA snapshot of §3.7 and the fee breakdown of §3.11. A separate SLA endpoint exposes only the time-limit evaluator output; a separate review-tasks endpoint lists the application's `ReviewTask` rows with their `stage_index`, `is_lead`, `status`, `decided_at`, `stage_due_at`, and `opinion_text`; a separate correction-notices endpoint lists the application's notices, optionally filtered by `status`. Each of these reads honours the role-and-ownership rules of §2.1: an applicant only sees their own applications, a reviewer only sees applications routed to their department, and a `PlatformAdmin` sees everything.

### 3.13. Audit Log Queries and SLA Performance Reports

A `PlatformAdmin` may query the audit log filtered by `target_entity`, `target_id`, and `action`, paginated as in §2.3. A separate SLA-performance reporting capability returns aggregate metrics for matters and departments over a window bounded by optional `since` and `until` timestamps, and may be filtered by `matter_id` and `department_id`. The performance report is the sole consumer of the statutory variant of the deadline calculation and never drives state transitions — its output is governance signal only.

## 4. Endpoint Definitions

All endpoints are mounted under the platform's root and exposed over JSON HTTP. Endpoint paths are written below as patterns; concrete resource ids are server-minted UUIDs without type prefixes. New-resource creations return HTTP 201 with the created resource in the envelope's `data` field; modifications, reads, and idempotent absorptions return HTTP 200. List endpoints return arrays under `data` with pagination fields populated in `meta`.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /departments | Register a new department. | PlatformAdmin |
| GET | /departments | List departments with optional filters. | PlatformAdmin, CatalogManager, Reviewer, LeadReviewer, CertificateOfficer, Applicant |
| POST | /matters | Create a Matter shell. | CatalogManager |
| GET | /matters | List matters; filter by theme, owning_department_id, status. | PlatformAdmin, CatalogManager, Reviewer, LeadReviewer, CertificateOfficer, Applicant |
| GET | /matters/{matter_id} | Read a matter (returns the current published version pointer). | PlatformAdmin, CatalogManager, Reviewer, LeadReviewer, CertificateOfficer, Applicant |
| POST | /matters/{matter_id}/versions | Create a DRAFT MatterVersion. | CatalogManager |
| GET | /matters/{matter_id}/versions/{version_id} | Read a single matter version. | PlatformAdmin, CatalogManager, Reviewer, LeadReviewer, CertificateOfficer, Applicant |
| POST | /matters/{matter_id}/versions/{version_id}/publish | Publish a draft version (auto-supersedes the prior PUBLISHED version). | CatalogManager |
| POST | /matters/{matter_id}/versions/{version_id}/retire | Retire a published or superseded version. | CatalogManager |
| POST | /material-templates | Create a draft material template. | CatalogManager |
| POST | /material-templates/{id}/publish | Publish a material template. | CatalogManager |
| GET | /material-templates | List material templates. | PlatformAdmin, CatalogManager, Reviewer, LeadReviewer, CertificateOfficer, Applicant |
| POST | /certificate-templates | Create a draft certificate template. | CertificateOfficer |
| POST | /certificate-templates/{id}/publish | Publish a certificate template. | CertificateOfficer |
| GET | /certificate-templates | List certificate templates. | PlatformAdmin, CatalogManager, CertificateOfficer |
| POST | /applications | Submit a new application against a published MatterVersion. | Applicant |
| GET | /applications/{id} | Read application detail (includes SLA snapshot and fee breakdown). | Applicant, Reviewer, LeadReviewer, PlatformAdmin |
| GET | /applications/{id}/sla | Time-limit monitoring snapshot. | Applicant, Reviewer, LeadReviewer, PlatformAdmin |
| POST | /applications/{id}/withdraw | Applicant withdraws (allowed only before any DISAGREED decision). | Applicant |
| POST | /applications/{id}/escalate | Lead reviewer escalates a disagreement. | LeadReviewer |
| POST | /applications/{id}/escalation-resolve | PlatformAdmin resolves the escalation (final AGREED or DISAGREED). | PlatformAdmin |
| GET | /applications/{id}/review-tasks | List review tasks for an application. | Reviewer, LeadReviewer, PlatformAdmin, Applicant |
| POST | /review-tasks/{id}/decide | Reviewer files an opinion (AGREED or DISAGREED). | Reviewer, LeadReviewer |
| POST | /applications/{id}/correction-notices | Reviewer issues a correction notice. | Reviewer, LeadReviewer |
| GET | /applications/{id}/correction-notices | List correction notices for an application. | Applicant, Reviewer, LeadReviewer, PlatformAdmin |
| POST | /applications/{id}/correction-notices/{cid}/resubmit | Applicant resubmits materials for an open correction notice. | Applicant |
| GET | /applications/{id}/certificate | Read the active Certificate for an application (if APPROVED). | Applicant, PlatformAdmin, CertificateOfficer |
| POST | /certificates/{id}/reissue | Reissue a certificate; supersedes the source. | CertificateOfficer |
| POST | /certificates/{id}/revoke | Revoke an active certificate. | PlatformAdmin |
| GET | /certificates/verify/{verification_code} | Public verification by verification_code. | Applicant, PlatformAdmin, CertificateOfficer, Reviewer, LeadReviewer, CatalogManager |
| POST | /_events/emit | Inbound event ingress; idempotent. | PlatformAdmin |
| GET | /audit-logs | Query audit log. | PlatformAdmin |
| POST | /_clock/advance | Test-only: advance the server clock by N seconds. | PlatformAdmin |
| POST | /_sweep/run | Test-only: run the periodic sweep. | PlatformAdmin |
| GET | /reports/sla-performance | Aggregate SLA performance across applications. | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_AUTH_MISSING | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_REVIEW_OUT_OF_ORDER | 409 |
| ERR_CORRECTION_EXPIRED | 409 |
| ERR_MAX_ROUNDS_REACHED | 409 |
| ERR_ESCALATION_NOT_PERMITTED | 409 |
| ERR_CERTIFICATE_ALREADY_REISSUED | 409 |
| ERR_DUPLICATE_RESOURCE | 409 |
| ERR_MATERIAL_MISSING | 422 |
| ERR_MATERIAL_TYPE_MISMATCH | 422 |
| ERR_EFORM_INCOMPLETE | 422 |
| ERR_CHANNEL_NOT_ALLOWED | 422 |
| ERR_DEFICIENCY_INVALID | 422 |
| ERR_DEFICIENCY_UNRESOLVED | 422 |
| ERR_DEPENDENT_TEMPLATE_UNPUBLISHED | 422 |
| ERR_TIME_LIMIT_INVERSION | 422 |
| ERR_ROUTING_INVALID | 422 |
| ERR_VALIDATION_FAILED | 422 |
