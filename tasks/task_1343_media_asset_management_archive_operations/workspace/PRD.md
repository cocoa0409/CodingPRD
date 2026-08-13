# Media Archive Operations API — Product Requirements Document

## 1. Introduction

A broadcast archive department is the memory of the network: decades of news tape, film reels, audio masters, and born-digital files that must be ingested, cataloged, rights-cleared, stored at the cheapest appropriate tier, retrieved on deadline for production, and — when the law or the license demands — preserved or destroyed on a defensible schedule. Each of those duties pulls against the others. Legal wants nothing touched while a matter is open; finance wants royalties computed to the cent; production wants a deep-archive tape recalled and staged within hours; engineering wants the oldest formats digitized before the playback decks fail. The system specified here exists to arbitrate those tensions with explicit state machines, computed rights and hold postures, and segregation of duties between the people who submit work and the people who approve it.

This document defines the Media Archive Operations API, mounted under `/archive`. It covers ingest batching and standardized metadata tagging, proxy rendition and search visibility, rights grants with time-boxed windows, legal holds, retention policy and disposal orders, retrieval request fulfillment, usage reporting with royalty accrual and statement settlement, storage tier migration with cost accounting, and a preservation digitization lab with workstation scheduling. All temporal behavior — rights windows, retention clocks, staging deadlines, statement periods — is evaluated against a controllable logical clock rather than the wall clock, so that operators and auditors can replay any sequence of events deterministically. The intended reader is the engineer implementing the service; every rule below is normative.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the role under which that user acts. A request where either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted to perform the operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Eleven roles exist, spelled exactly as follows: `SystemAdmin`, `IngestCoordinator`, `MetadataCataloger`, `MetadataLibrarian`, `ArchivistLead`, `RightsManager`, `LegalCounsel`, `AccessOfficer`, `Requester`, `FinanceOfficer`, and `LabTechnician`. Their capabilities are summarized here and enumerated per endpoint in Section 4.

- `SystemAdmin` — platform operator: staff registry, retention policies, workstations, and the logical clock.
- `IngestCoordinator` — runs ingest batches and asset intake, and may queue proxy renditions.
- `MetadataCataloger` — edits and submits standardized descriptive metadata.
- `MetadataLibrarian` — approves or rejects metadata submissions, segregated from the submitter.
- `ArchivistLead` — archives assets and owns disposal orders, migration jobs, and digitization tickets.
- `RightsManager` — manages rights grants and revocations.
- `LegalCounsel` — places and releases legal holds, with release segregated from the placer.
- `AccessOfficer` — reviews and fulfills retrieval requests.
- `Requester` — a broadcast staff member requesting retrievals and reporting usage.
- `FinanceOfficer` — verifies usage events and runs royalty statements.
- `LabTechnician` — runs proxy rendering, migration execution, and the digitization lab.

Identity semantics differ by role. When `X-User-Role` is `Requester`, `X-User-ID` is the `id` of the acting `StaffMember`; ownership checks on any resource that references a `StaffMember` — a retrieval request's `requester_id`, a usage event's `reported_by_id` — compare that foreign-key field to `X-User-ID`. When `X-User-Role` is any of the other ten roles (`SystemAdmin`, `IngestCoordinator`, `MetadataCataloger`, `MetadataLibrarian`, `ArchivistLead`, `RightsManager`, `LegalCounsel`, `AccessOfficer`, `FinanceOfficer`, `LabTechnician`), `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `metadata_submitted_by_user_id` on an asset, `placed_by_user_id` or `released_by_user_id` on a legal hold, `created_by_user_id` or `approved_by_user_id` on a disposal order — but it never compares that value to any entity's `id`.

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

List endpoints accept two query parameters: `limit` (default 10, minimum 1, maximum 100) and `offset` (default 0). Results are always sorted by `created_at` in ascending order unless a subsection states otherwise. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`, where `has_more` reports whether additional rows exist beyond the returned window. Many list endpoints also expose domain filters as optional query parameters — for example `email` on the staff list, `status` on batches, `ingest_batch_id`, `source_asset_id`, `catalog_status`, `storage_tier`, and `format_class` on assets, `asset_id` and `status` on proxies, holds, migration jobs, and disposal orders, `grant_type` on rights grants, `media_type` on retention policies, `requester_id` on retrieval requests, `reported_by_id` and `statement_id` on usage events, `rights_holder` on royalty statements, and `workstation_id` on digitization tickets.

### 2.4. The Logical Clock and Time-Driven Sweeps

The service keeps a logical clock that governs every time-dependent rule in this document: rights-window effectiveness, retention eligibility, staging deadlines, statement periods, schedule conflicts, accrual periods, and all recorded timestamps. At startup, before any operator action, the logical clock reads exactly 2026-08-01T00:00:00Z. The clock never falls back to the wall clock; it advances only when a `SystemAdmin` sets it through the test-driving capability mounted at the clock endpoint, supplying the target instant as `to_iso8601` and receiving the new `current_utc` back.

Setting the clock triggers a time-based sweep: every retrieval request sitting in `STAGED` whose `staged_at` lies more than 72 hours in the past relative to the new clock value transitions to `EXPIRED`. No other sweep exists; every other time-triggered rule in this document is evaluated lazily, at the moment a read or a validation needs the answer.

### 2.5. Resource Identity, Timestamps, and Version Semantics

Every one of the fourteen resources in this system — `StaffMember`, `IngestBatch`, `Asset`, `ProxyRendition`, `RightsGrant`, `LegalHold`, `RetentionPolicy`, `DisposalOrder`, `RetrievalRequest`, `UsageEvent`, `RoyaltyStatement`, `MigrationJob`, `DigitizationTicket`, and `Workstation` — carries four common properties. The `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `created_at` is fixed at creation and `updated_at` refreshes on every mutation. The `version` is an integer that increments by exactly one on every mutation of the resource, and it is the basis of the optimistic-concurrency and version-pinning rules described in §2.7 and §3.5. There are no reduced-property resources: all fourteen entities expose the full common set.

### 2.6. Request Validation Order

When several checks could reject the same request, the server evaluates them in a fixed order and returns the first failure encountered. The order, from first to last, is:

1. **Authentication context.** Both `X-User-ID` and `X-User-Role` present and non-empty; otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Applies to every endpoint.
2. **Authorization.** The role is permitted to perform the operation per the RBAC matrix; otherwise `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). Applies to every endpoint.
3. **Existence.** Path identifiers are validated left to right, then body foreign-key references; the first unknown id yields that resource's not-found error (HTTP 404): `ERR_STAFF_MEMBER_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`, `ERR_PROXY_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_RETRIEVAL_REQUEST_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`, `ERR_JOB_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, or `ERR_WORKSTATION_NOT_FOUND`, as appropriate to the resource.
4. **State preconditions.** The target resource's current state must admit the requested transition; otherwise the transition's state-specific rejection (HTTP 409) — for example `ERR_INVALID_CATALOG_TRANSITION`, `ERR_DISPOSAL_ORDER_NOT_PENDING`, `ERR_ASSET_NOT_RETRIEVABLE`, `ERR_ASSET_DISPOSED`, `ERR_ASSET_NOT_ARCHIVED`, `ERR_ASSET_LOCKED`, the `ERR_REQUEST_*`, `ERR_EVENT_*`, `ERR_JOB_*`, `ERR_TICKET_*`, `ERR_BATCH_*`, and `ERR_PROXY_*` families, `ERR_STATEMENT_NOT_OPEN`, `ERR_STATEMENT_NOT_CLOSED`, `ERR_GRANT_ALREADY_REVOKED`, `ERR_HOLD_ALREADY_RELEASED`, `ERR_RETRY_BUDGET_EXHAUSTED`, `ERR_WORKSTATION_BUSY`, `ERR_ACTIVE_DISPOSAL_ORDER_EXISTS`, or `ERR_JOB_IN_PROGRESS_EXISTS`.
5. **Optimistic concurrency.** On the two asset-pinned creation operations named in §2.7, `expected_asset_version` must equal the asset's current `version`; otherwise `ERR_STALE_ASSET_VERSION` (HTTP 412).
6. **Safety and segregation.** Legal-hold gates and segregation-of-duties rules: `ERR_LEGAL_HOLD_ACTIVE` and `ERR_ASSET_UNDER_LEGAL_HOLD` (HTTP 409), and the four `ERR_SOD_*` rejections (HTTP 403).
7. **Temporal rules.** Rights windows, delivery deadlines, schedule due times, disposal due dates, statement periods, and workstation buffers — `ERR_RIGHTS_WINDOW_PAST`, `ERR_EXCLUSIVE_GRANT_OVERLAP`, `ERR_DELIVERY_DEADLINE_PAST`, `ERR_DELIVERY_BEYOND_RIGHTS_WINDOW`, `ERR_RIGHTS_EXPIRED_FOR_PURPOSE`, `ERR_TICKET_NOT_DUE`, `ERR_DISPOSAL_NOT_YET_DUE`, `ERR_STATEMENT_PERIOD_OVERLAP`, and `ERR_WORKSTATION_SCHEDULE_CONFLICT` (HTTP 422). Malformed windows and other request-shape defects surface earlier as `ERR_INVALID_REQUEST` (HTTP 400).
8. **Constraint rules.** Metadata completeness, format obsolescence, workstation format support, one non-terminal disposal order per asset, at most one in-progress migration per asset, uniqueness of retention policy per media type, workstation name, and staff email, and retention elapsed (or override): `ERR_METADATA_INCOMPLETE`, `ERR_FORMAT_NOT_OBSOLETE`, `ERR_WORKSTATION_FORMAT_UNSUPPORTED`, `ERR_ACTIVE_DISPOSAL_ORDER_EXISTS`, `ERR_JOB_IN_PROGRESS_EXISTS`, `ERR_DUPLICATE_MEDIA_TYPE_POLICY`, `ERR_DUPLICATE_WORKSTATION_NAME`, `ERR_DUPLICATE_STAFF_EMAIL`, `ERR_RETENTION_NOT_ELAPSED` (HTTP 422), and `ERR_NO_ELIGIBLE_TICKET` (HTTP 409) for the auto-assign empty-pool fallback.
9. **Fiscal gates.** The statement payout minimum, `ERR_PAYOUT_BELOW_MINIMUM` (HTTP 402), evaluated last so that every cheaper defect surfaces first.

### 2.7. Optimistic Concurrency on Asset-Pinned Writes

Two creation operations are pinned to the client's last observed version of an asset, because each would otherwise succeed silently against a stale read. Creating a disposal order and creating a migration job both require a non-optional input field, `expected_asset_version`, carrying the `version` the client last read from the target asset. If the asset's current `version` no longer equals the supplied value — because another writer edited the asset's metadata, placed a hold on it, or created another pinned write against it in the meantime — the request is rejected with `ERR_STALE_ASSET_VERSION` (HTTP 412). No other endpoint accepts a version field; optimistic concurrency applies nowhere else in the API.

### 2.8. Segregation of Duties and Ownership-Scoped Actions

Four approvals are segregated from the person who originated the work; in each case the rejection is HTTP 403. Metadata approval must come from a `MetadataLibrarian` whose `X-User-ID` differs from the asset's `metadata_submitted_by_user_id` (`ERR_SOD_METADATA_SELF_APPROVE`). Disposal approval must come from an `ArchivistLead` whose `X-User-ID` differs from the order's `created_by_user_id` (`ERR_SOD_DISPOSAL_SELF_APPROVE`). Retrieval approval must come from an `AccessOfficer` whose `X-User-ID` differs from the request's `requester_id` (`ERR_SOD_RETRIEVAL_SELF_APPROVE`). Releasing a legal hold must come from a `LegalCounsel` whose `X-User-ID` differs from the hold's `placed_by_user_id` (`ERR_SOD_HOLD_SELF_RELEASE`).

Three further actions are scoped by ownership rather than segregated. A `Requester` may cancel only their own retrieval requests — the request's `requester_id` must equal `X-User-ID` — while an `AccessOfficer` may cancel any non-terminal request. A `Requester` may resubmit only their own disputed usage events — the event's `reported_by_id` must equal `X-User-ID`. A disposal order may be withdrawn only by the `ArchivistLead` who created it — the order's `created_by_user_id` must equal `X-User-ID`. Each ownership violation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

### 2.9. Monetary Precision and Rounding

All money in this system is integer cents. Fee quotes, royalty accruals, statement totals, and storage costs are all expressed as whole-cent integers. Where a calculation produces a fraction, it is rounded half up — a fraction of exactly one half rounds away from zero — and the rounding is always applied at the finest grain before any summation: per usage event for royalties, per residency interval for storage cost, never to a summed total. The per-event royalty floor is 25 cents; the minimum payout for a statement to post is 1,000 cents. Storage is rated per gigabyte per day at 4 cents for `ONLINE`, 1.5 cents for `NEARLINE`, and 0.25 cents for `DEEP_ARCHIVE`; delivery fees are built from a per-tier base plus 10 cents per whole gigabyte. The storage-cost read also returns a `currency` label alongside the two cent-denominated figures.

### 2.10. Windows, Intervals, and Buffers

Time intervals in this system are half-open: a rights grant is effective from its `window_start` inclusive up to but not including its `window_end`; a royalty statement sweeps usage whose `aired_at` is at or after `period_start` and strictly before `period_end`. Expiration is end-exclusive — a grant whose window ends exactly now is no longer effective — and adjacency is not overlap for exclusive grants: a new exclusive window beginning exactly when an existing one ends conflicts with nothing. Workstation scheduling uses a different, stricter convention: a turnaround buffer of 30 minutes must be left on both sides of every occupied slot, so a zero-minute gap is a conflict while a gap of exactly 30 minutes is allowed. Retention years are always 365-day years. Royalty billing quantizes usage into 30-second units, rounded up. Staged retrievals live for 72 hours before the clock sweep expires them, and the digitization auto-assigner books a four-hour slot starting now. These conventions recur throughout Section 3 and are restated where they bind.

## 3. Business Logic & Workflows

### 3.1. Staff Registry, Ingest Batches, and the Cataloging Pipeline

Before any work can be attributed, a `SystemAdmin` registers each member of the archive staff with an `email`, a `full_name`, and a free-form `department` label; the `active` flag defaults to true and may be supplied explicitly at registration. Staff email addresses are unique across the registry — a duplicate `email` is rejected with `ERR_DUPLICATE_STAFF_EMAIL` (HTTP 422). Registered staff members are the identity backbone for the `Requester` role described in §2.1.

Intake begins when an `IngestCoordinator` opens an ingest batch with a `batch_name` and a `source_department`. A new batch is `OPEN` and its `asset_count` is zero; `asset_count` is a computed figure, always equal to the number of assets whose `ingest_batch_id` references the batch, and it grows by one each time an asset is ingested under the batch. Finalizing a batch moves it from `OPEN` to `FINALIZED` and is permitted only when the batch contains at least one asset (otherwise `ERR_EMPTY_BATCH`, HTTP 409) and no asset in the batch still sits in `METADATA_DRAFT` (otherwise `ERR_BATCH_ASSETS_UNRESOLVED`, HTTP 409). `FINALIZED` is terminal: once a batch is finalized, any further asset ingest targeting it is rejected with `ERR_BATCH_NOT_OPEN` (HTTP 409).

Assets enter the system through ingest against an `OPEN` batch. The coordinator supplies `ingest_batch_id`, `title`, `description`, `media_type` (one of `VIDEO`, `AUDIO`, `FILM`, `PHOTO`, `DOCUMENT`), `format_class` (one of `BETACAM_SP`, `UMATIC`, `VHS`, `FILM_16MM`, `AUDIO_REEL`, `AUDIO_DAT`, `DIGITAL_FILE`, `PRORES_FILE`), `duration_seconds`, `size_gb`, and `rights_holder` — the rights-holder label that later drives royalty sweeps. Both `duration_seconds` and `size_gb` must be positive; a non-positive value, a missing required field, a wrong type, or an unknown enum value anywhere in the payload is a malformed request rejected with `ERR_INVALID_REQUEST` (HTTP 400). `keywords` defaults to an empty list and `content_rating` defaults to `NR`; `source_asset_id` is system-set and stays null for originals — it is populated only on derivative assets produced by the digitization lab (§3.9). A freshly ingested asset has `catalog_status` `METADATA_DRAFT`, `storage_tier` `ONLINE`, and no `metadata_submitted_by_user_id`.

Descriptive metadata remains editable while the asset is in `METADATA_DRAFT` or `IN_REVIEW`: a `MetadataCataloger` may patch `title`, `description`, `keywords`, `content_rating`, and `rights_holder`, and each successful edit increments the asset's `version` and refreshes `updated_at`. Once the asset has advanced past review — `CATALOGED`, `ARCHIVED`, or beyond — the same edit is rejected with `ERR_ASSET_LOCKED` (HTTP 409).

Submitting metadata for review moves the asset from `METADATA_DRAFT` to `IN_REVIEW` and is a `MetadataCataloger` action. Attempting it from any other state is rejected with `ERR_INVALID_CATALOG_TRANSITION` (HTTP 409). The submission is completeness-gated: `description` must be non-empty, `keywords` must contain at least one entry, and `content_rating` must be something other than `NR` (one of `G`, `PG`, `PG13`, `R`); a shortfall on any of the three is rejected with `ERR_METADATA_INCOMPLETE` (HTTP 422). A successful submission stamps `metadata_submitted_by_user_id` with the caller's `X-User-ID`, establishing the identity that the approver must later differ from.

Review belongs to the `MetadataLibrarian`. Approving moves `IN_REVIEW` to `CATALOGED`; the approver's `X-User-ID` must differ from `metadata_submitted_by_user_id`, otherwise the approval is rejected with `ERR_SOD_METADATA_SELF_APPROVE` (HTTP 403). Rejecting returns the asset from `IN_REVIEW` to `METADATA_DRAFT` for rework, records the librarian's `reason`, and clears `metadata_submitted_by_user_id` back to null. Either action attempted from a state other than `IN_REVIEW` is rejected with `ERR_INVALID_CATALOG_TRANSITION`.

Archiving is an `ArchivistLead` action that moves a `CATALOGED` asset to `ARCHIVED`. Two readiness gates guard it: at least one proxy rendition for the asset must be in `READY` (otherwise `ERR_PROXY_NOT_READY`, HTTP 409), and at least one rights-grant row must exist for the asset in any status, active or revoked (otherwise `ERR_NO_RIGHTS_GRANT_ON_RECORD`, HTTP 409). An archived asset can later be reopened for metadata rework: recataloging moves `ARCHIVED` back to `IN_REVIEW` and clears `metadata_submitted_by_user_id` so that the fresh review round starts without a pinned submitter. The remaining catalog states — `DISPOSAL_SCHEDULED` and the terminal `DISPOSED` — are never reached by direct catalog actions; they are driven by the disposal pipeline in §3.5.

### 3.2. Proxy Renditions and Search Visibility

Proxy renditions make archived media findable. An `IngestCoordinator` or a `LabTechnician` queues proxy generation for an asset by supplying its `asset_id` and, optionally, a `rendition_type` — `PROXY_LOWRES` (the default) or `PROXY_HIGHRES`. A new rendition starts `QUEUED` with `retry_count` zero, no `proxy_url`, no `indexed_at`, and no `failure_reason`.

The rendering lifecycle belongs to the `LabTechnician`. Claiming moves a rendition from `QUEUED` to `RENDERING` (from any other state, `ERR_PROXY_NOT_QUEUED`, HTTP 409). From `RENDERING` the technician either completes the rendition — which mints a system-generated `proxy_url`, stamps `indexed_at` with the current logical time, and moves it to the terminal `READY` state, entering the asset into the proxy search index — or marks it failed, which moves it to `FAILED` and records the operator-supplied `reason` in `failure_reason`. Both completion and failure attempted from a state other than `RENDERING` are rejected with `ERR_PROXY_NOT_RENDERING` (HTTP 409). The presence of a `proxy_url` on a `READY` rendition is precisely what makes the asset searchable via proxy, and at least one `READY` rendition is the proxy gate on archiving described in §3.1.

A failed rendition may be retried: the technician sends it from `FAILED` back to `QUEUED`, which increments `retry_count` by one. The retry budget is capped at 3 — attempting a retry when `retry_count` has already reached the cap is rejected with `ERR_RETRY_BUDGET_EXHAUSTED` (HTTP 409), and attempting it from any state other than `FAILED` is rejected with `ERR_PROXY_NOT_FAILED` (HTTP 409).

### 3.3. Rights Grants, Windows, and the Computed Rights Posture

Rights management is the `RightsManager`'s domain. Creating a grant requires the `asset_id`, a `grant_type` (`BROADCAST`, `STREAMING`, `SYNDICATION`, or `ARCHIVAL_ONLY`), a `territory` (`DOMESTIC`, `REGIONAL`, or `GLOBAL`), and the window endpoints `window_start` and `window_end`. The `exclusive` flag defaults to false, and `restriction_flags` defaults to an empty list; when populated it carries zero or more of `EDITORIAL_ONLY`, `NO_RERUN`, `NEWS_USE_ONLY`, and `GEO_BLOCKED`, with an empty list meaning unrestricted. The window must be well formed — `window_start` strictly before `window_end`, otherwise `ERR_INVALID_REQUEST` (HTTP 400) — and it must reach into the future: a grant whose `window_end` is at or before the current logical time is rejected with `ERR_RIGHTS_WINDOW_PAST` (HTTP 422). A newly created grant is `ACTIVE`.

Exclusive grants carry an additional non-overlap rule. When `exclusive` is true, creation is rejected with `ERR_EXCLUSIVE_GRANT_OVERLAP` (HTTP 422) if any other `ACTIVE` exclusive grant exists for the same asset with the same `grant_type` and `territory` whose window intersects the new one. Intersection follows the half-open convention of §2.10: the windows conflict only when the new window starts strictly before the existing window's end and the existing window starts strictly before the new window's end, so a new window beginning exactly at the existing window's end is adjacency, not conflict, and is allowed.

Revocation moves a grant from `ACTIVE` to the terminal `REVOKED`; revoking an already-revoked grant is rejected with `ERR_GRANT_ALREADY_REVOKED` (HTTP 409). Expiration is never a state: a grant remains `ACTIVE` even after its window passes, and whether it currently confers rights is derived from the window against the logical clock on every read.

That derivation produces the asset's `rights_posture`, recomputed on every read of the asset and at every validation that references it. The effective grant set consists of the asset's `ACTIVE` grants whose window contains the current logical instant — `window_start` at or before now, `window_end` strictly after now; `REVOKED` grants are excluded, and a grant whose `window_end` equals now is already outside its window. If the effective set is empty, the posture is `EXPIRED`. Otherwise, if at least one effective grant carries an empty `restriction_flags` list, the posture is `CLEARED` — `CLEARED` beats `RESTRICTED` whenever even one unrestricted effective grant exists. Only when every effective grant carries at least one restriction flag is the posture `RESTRICTED`. The posture is consumed by the retrieval purpose gate in §3.6.

### 3.4. Legal Holds and Archive-Wide Safety Cascades

When counsel flags an asset as evidence, a `LegalCounsel` places a legal hold by supplying the `asset_id`, a `matter_reference` docket label, and a `reason`. The hold is created `ACTIVE`, with `placed_by_user_id` captured from the caller's `X-User-ID`; `released_by_user_id` and `released_at` remain null until release.

Placing a hold cascades across the archive in the same transaction. The asset's `hold_status` becomes `HELD` and the asset's `version` increments by one. Any disposal order for the asset sitting in `PENDING_APPROVAL` or `APPROVED` is forced to `BLOCKED`, and if the blocked order was `APPROVED` — meaning it had already scheduled the asset — the asset's `catalog_status` reverts from `DISPOSAL_SCHEDULED` back to `ARCHIVED`. Any migration job for the asset sitting in `QUEUED` is paused to `HOLD_PAUSED`.

The asset's `hold_status` is itself derived, never stored as an independent write: it is `HELD` if at least one `ACTIVE` legal hold exists for the asset and `CLEAR` otherwise, recomputed on read and at every validation that references it.

Releasing a hold is also a `LegalCounsel` action, but segregated: the releaser's `X-User-ID` must differ from `placed_by_user_id` (otherwise `ERR_SOD_HOLD_SELF_RELEASE`, HTTP 403), and the hold must still be `ACTIVE` (otherwise `ERR_HOLD_ALREADY_RELEASED`, HTTP 409). Release stamps `released_by_user_id` with the caller and `released_at` with the current logical time, and moves the hold to the terminal `RELEASED` state. When the released hold was the last `ACTIVE` hold on the asset, two further cascades fire: the asset's `hold_status` returns to `CLEAR`, and every migration job paused in `HOLD_PAUSED` for that asset resumes to `QUEUED`. Disposal orders sitting in `BLOCKED` are deliberately not resurrected by release — they stay `BLOCKED` until an archivist manually resubmits them per §3.5.

An active hold gates five operations elsewhere in this document: disposal-order approve, execute, and resubmit, and migration-job creation are rejected with `ERR_LEGAL_HOLD_ACTIVE` (HTTP 409) while the asset is `HELD`; retrieval-request creation and approval are rejected with `ERR_ASSET_UNDER_LEGAL_HOLD` (HTTP 409). Disposal-order creation likewise requires the asset to be `CLEAR` of holds.

### 3.5. Retention Policy and the Disposal Pipeline

Disposal is the most heavily gated workflow in the archive, and it begins with policy. A `SystemAdmin` records a retention policy per `media_type` — one of `VIDEO`, `AUDIO`, `FILM`, `PHOTO`, `DOCUMENT` — carrying `min_retention_years` and an optional `requires_legal_review` flag that defaults to false and is informational for downstream review routing. Only one policy may exist per media type; a duplicate is rejected with `ERR_DUPLICATE_MEDIA_TYPE_POLICY` (HTTP 422). Retention years are counted as 365-day years, and when no policy row exists for an asset's media type, a default of 7 years applies.

An asset becomes retention-eligible once the logical clock has reached the instant computed by adding the applicable retention years — each year counted as 365 days — to the asset's `created_at`. Eligibility is inclusive at the boundary: an asset whose eligibility instant equals now is eligible. Creating a disposal order before that instant is rejected with `ERR_RETENTION_NOT_ELAPSED` (HTTP 422) unless the caller sets `retention_override` to true, which skips the elapsed check entirely; an override without a justification is a malformed request, so `override_reason` — null by default — is required whenever `retention_override` is true, and its absence is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The override flag itself defaults to false.

Creating a disposal order is an `ArchivistLead` action with several layers of gating, evaluated in the order of §2.6. The target asset must be in `ARCHIVED` — any other catalog state is rejected with `ERR_ASSET_NOT_ARCHIVED` (HTTP 409). The asset must be clear of legal holds (`ERR_LEGAL_HOLD_ACTIVE`). At most one non-terminal disposal order may exist per asset — non-terminal meaning `DRAFT`, `PENDING_APPROVAL`, `APPROVED`, or `BLOCKED`; a second live order is rejected with `ERR_ACTIVE_DISPOSAL_ORDER_EXISTS` (HTTP 409). The `scheduled_execution_date` must lie strictly in the future relative to the logical clock; a date at or before now is a malformed request (`ERR_INVALID_REQUEST`). And the create is one of the two asset-pinned writes of §2.7: it must carry `expected_asset_version` equal to the asset's current `version`, otherwise `ERR_STALE_ASSET_VERSION` (HTTP 412). On success the order is created in `DRAFT`, `created_by_user_id` is captured from the caller, and the asset's `version` increments by one as part of the same write; the order's `pinned_asset_version` records the asset's version after that increment — exactly one more than the `expected_asset_version` the client supplied — and is re-checked at approve and at execute.

Submission moves a `DRAFT` order to `PENDING_APPROVAL`; from any other state the submit is rejected with `ERR_DISPOSAL_ORDER_NOT_DRAFT` (HTTP 409).

Approval is where the pipeline's safeguards concentrate, and the checks are evaluated in §2.6 order — state first, then the hold gate, then the version pin, then segregation. The order must be in `PENDING_APPROVAL` (otherwise `ERR_DISPOSAL_ORDER_NOT_PENDING`, HTTP 409); the asset's `hold_status` must be `CLEAR` (otherwise `ERR_LEGAL_HOLD_ACTIVE`); the asset's current `version` must still equal the order's `pinned_asset_version` — any drift, such as a metadata edit or a migration completion since the order was created, is rejected with `ERR_ASSET_VERSION_DRIFT` (HTTP 409); and the approver must not be the order's creator (otherwise `ERR_SOD_DISPOSAL_SELF_APPROVE`, HTTP 403). A successful approval records `approved_by_user_id` and moves the asset's `catalog_status` from `ARCHIVED` to `DISPOSAL_SCHEDULED` — this is the system-driven `ARCHIVED` → `DISPOSAL_SCHEDULED` transition of the asset lifecycle. Rejection is the sibling exit from `PENDING_APPROVAL`: it records the supplied `reason` in `reject_reason`, moves the order to the terminal `REJECTED` state, and leaves the asset untouched.

Execution is allowed only once the logical clock has reached the order's `scheduled_execution_date` — earlier execution is rejected with `ERR_DISPOSAL_NOT_YET_DUE` (HTTP 422) — and only from `APPROVED` (otherwise `ERR_DISPOSAL_ORDER_NOT_APPROVED`, HTTP 409), with the hold gate and the version pin re-checked exactly as at approve (`ERR_LEGAL_HOLD_ACTIVE`, `ERR_ASSET_VERSION_DRIFT`). Executing moves the order to the terminal `EXECUTED` state and the asset from `DISPOSAL_SCHEDULED` to `DISPOSED`, and the disposal cascades outward: every retrieval request for the asset in `SUBMITTED`, `UNDER_REVIEW`, `RECALLING`, or `STAGED` is cancelled to `CANCELLED`; every migration job for the asset in `QUEUED` or `HOLD_PAUSED` is cancelled to `CANCELLED`; and every digitization ticket for the asset in `QUEUED` or `ASSIGNED` is cancelled to `CANCELLED`.

Withdrawal is the creator's escape hatch. Only the `ArchivistLead` whose `X-User-ID` equals the order's `created_by_user_id` may withdraw (otherwise `ERR_INSUFFICIENT_PERMISSIONS`, HTTP 403), and only from `DRAFT` or `APPROVED` (otherwise `ERR_DISPOSAL_ORDER_NOT_WITHDRAWABLE`, HTTP 409). Withdrawing a `DRAFT` order leaves the asset untouched; withdrawing an `APPROVED` order reverts the asset from `DISPOSAL_SCHEDULED` back to `ARCHIVED`. `WITHDRAWN` is terminal in both cases.

Finally, the `BLOCKED` branch. When a legal hold activates on the asset (§3.4), an order in `PENDING_APPROVAL` is forced to `BLOCKED` with no asset change, and an order in `APPROVED` is forced to `BLOCKED` with the asset reverted from `DISPOSAL_SCHEDULED` to `ARCHIVED`. A blocked order can be resubmitted once the hold picture clears: resubmission requires the order to be in `BLOCKED` (otherwise `ERR_DISPOSAL_ORDER_NOT_BLOCKED`, HTTP 409) and the asset's `hold_status` to be `CLEAR` (otherwise `ERR_LEGAL_HOLD_ACTIVE`), returns the order to `PENDING_APPROVAL`, and re-pins `pinned_asset_version` to the asset's current `version`, discarding the stale pin.

### 3.6. Retrieval Requests: Review, Staging, Deep-Archive Recall, and Delivery

Production staff pull material out of the archive through retrieval requests. A `Requester` creates one by supplying `asset_id`, their own staff identity as `requester_id`, a `purpose` (`BROADCAST`, `INTERNAL_REVIEW`, or `EXHIBITION`), and a `requested_delivery_by` deadline; `delivery_tier` defaults to `STANDARD` and may be set to `EXPEDITE`. Creation is gated in §2.6 order. The asset must be retrievable: a `DISPOSED` asset is rejected with `ERR_ASSET_DISPOSED` (HTTP 409), and any catalog status other than `CATALOGED` or `ARCHIVED` is rejected with `ERR_ASSET_NOT_RETRIEVABLE` (HTTP 409). The asset must be clear of legal holds (`ERR_ASSET_UNDER_LEGAL_HOLD`, HTTP 409). The purpose gate checks the asset's current `rights_posture`: a `BROADCAST` purpose requires `CLEARED`; `INTERNAL_REVIEW` and `EXHIBITION` accept either `CLEARED` or `RESTRICTED`; an `EXPIRED` posture rejects every purpose — any failure is `ERR_RIGHTS_EXPIRED_FOR_PURPOSE` (HTTP 422). The deadline must lie strictly in the future (otherwise `ERR_DELIVERY_DEADLINE_PAST`, HTTP 422), and for `BROADCAST` requests it must also fall strictly before the `window_end` of every effective rights grant the delivery would rely on — a deadline exactly equal to a grant's window end is already beyond the window, since windows are end-exclusive, and is rejected with `ERR_DELIVERY_BEYOND_RIGHTS_WINDOW` (HTTP 422). A successfully created request is `SUBMITTED` with `return_count` zero and no quoted fee.

Review belongs to the `AccessOfficer`. Starting review moves `SUBMITTED` to `UNDER_REVIEW`; from any other state it is rejected with `ERR_REQUEST_NOT_SUBMITTED` (HTTP 409).

Approval is the fork point, and it re-checks everything that could have drifted since creation, in §2.6 order: the request must be `UNDER_REVIEW` (otherwise `ERR_REQUEST_NOT_UNDER_REVIEW`, HTTP 409); the approver's `X-User-ID` must differ from `requester_id` (otherwise `ERR_SOD_RETRIEVAL_SELF_APPROVE`, HTTP 403); the asset must still be clear of holds (otherwise `ERR_ASSET_UNDER_LEGAL_HOLD`); and the purpose gate is re-evaluated against the asset's current `rights_posture` (otherwise `ERR_RIGHTS_EXPIRED_FOR_PURPOSE`). If the asset's `storage_tier` is anything other than `DEEP_ARCHIVE`, approval moves the request straight to `STAGED` and stamps `staged_at` with the current logical time. If the asset sits in `DEEP_ARCHIVE`, approval instead moves the request to `RECALLING` — the tape must be physically recalled before staging. On either branch the approval quotes the delivery fee into `quoted_fee_cents` from the asset's tier and size at approve time: a base of 0 cents for `ONLINE`, 500 cents for `NEARLINE`, or 1,500 cents for `DEEP_ARCHIVE`, plus 10 cents for each whole gigabyte of `size_gb` rounded up; an `EXPEDITE` delivery tier then doubles the quoted figure. The fee is integer cents and needs no further rounding once `size_gb` has been rounded up.

Two officer actions loop or terminate a request under review. Returning moves `UNDER_REVIEW` back to `SUBMITTED`, increments `return_count` by one, and records the supplied `note` in `review_note`. Rejecting moves `UNDER_REVIEW` to the terminal `REJECTED` and likewise records the `note` in `review_note`. Both require the request to be `UNDER_REVIEW` (otherwise `ERR_REQUEST_NOT_UNDER_REVIEW`).

Deep-archive recalls are completed by the lab. A `LabTechnician` marking the recall complete moves the request from `RECALLING` to `STAGED` — from any other state, `ERR_REQUEST_NOT_RECALLING` (HTTP 409) — and stamps `staged_at` with the current logical time. The system provides a second, automatic path: when a migration job for the asset completes into any tier other than `DEEP_ARCHIVE` (§3.8), every request of that asset sitting in `RECALLING` moves to `STAGED` with `staged_at` set to the migration's completion time.

Delivery is the terminal act: an `AccessOfficer` delivers a `STAGED` request (from any other state, `ERR_REQUEST_NOT_STAGED`, HTTP 409), which stamps `delivered_at` with the current logical time and moves the request to `DELIVERED`. Delivery must happen inside the stage-hold window of 72 hours measured from `staged_at`; a request whose stage hold has lapsed has already been moved to the terminal `EXPIRED` state by the clock sweep of §2.4, so a late deliver attempt meets `ERR_REQUEST_NOT_STAGED` rather than a live request.

Cancellation closes a live request from any of `SUBMITTED`, `UNDER_REVIEW`, `RECALLING`, or `STAGED`; cancelling a request already in `DELIVERED`, `REJECTED`, `CANCELLED`, or `EXPIRED` is rejected with `ERR_REQUEST_TERMINAL` (HTTP 409). A `Requester` may cancel only their own requests — `requester_id` equal to `X-User-ID`, otherwise `ERR_INSUFFICIENT_PERMISSIONS` — while an `AccessOfficer` may cancel any non-terminal request. Recall also that disposal execution (§3.5) force-cancels every non-terminal request for the disposed asset.

### 3.7. Usage Reporting and Royalty Settlement

Airing archived material creates a royalty obligation, tracked as usage events. A `Requester` reports usage with `asset_id`, their staff identity as `reported_by_id`, a `usage_type` (`BROADCAST`, `REBROADCAST`, `STREAMING`, or `PROMO`), the `market_size` of the audience, the `duration_seconds_used`, and the `aired_at` timestamp of the airing. Both `market_size` and `duration_seconds_used` must be positive, otherwise `ERR_INVALID_REQUEST` (HTTP 400). A new event is `REPORTED`, with both accrual fields null and no `statement_id`.

Verification belongs to the `FinanceOfficer` and moves `REPORTED` to `VERIFIED` (from any other state, `ERR_EVENT_NOT_REPORTED`, HTTP 409). Verification computes the event's `provisional_accrual_cents` — the provisional variant of the royalty accrual. Usage is billed in 30-second units: the event's `duration_seconds_used` divided by 30, rounded up to a whole unit. The per-unit rate depends on the market tier selected by `market_size`: below 1,000,000 is the small market at 100 cents per unit; at least 1,000,000 but below 5,000,000 is the medium market at 250 cents per unit; 5,000,000 and above is the large market at 500 cents per unit. The usage multiplier scales by type: 1.0 for `BROADCAST`, 0.5 for `REBROADCAST`, 0.75 for `STREAMING`, and 0.25 for `PROMO`. The raw accrual is units times rate times multiplier, rounded half up to integer cents, and the provisional accrual is that rounded figure or the 25-cent per-event floor, whichever is greater. The provisional variant uses only event-local inputs — no volume discount.

Disputes move an event from `REPORTED` or `VERIFIED` to `DISPUTED` (from any other state, `ERR_EVENT_NOT_DISPUTABLE`, HTTP 409) and record the supplied `reason` in `dispute_reason`. Disputing a `VERIFIED` event has a delayed consequence: if the event has already been swept into a closed statement, that statement's posting will fail the still-verified re-validation with `ERR_STATEMENT_EVENTS_DIRTY` (HTTP 409), as described below. Resubmission returns a `DISPUTED` event to `REPORTED` (from any other state, `ERR_EVENT_NOT_DISPUTED`, HTTP 409), resets `provisional_accrual_cents` to null so the event must be verified afresh, and may be performed only by the original reporter — the `Requester` whose `X-User-ID` equals `reported_by_id`, otherwise `ERR_INSUFFICIENT_PERMISSIONS`.

Statements aggregate a rights holder's verified usage over a period. A `FinanceOfficer` creates one with the `rights_holder` label, an inclusive `period_start`, and an exclusive `period_end` that must lie strictly after `period_start` (otherwise `ERR_INVALID_REQUEST`). Creation is rejected with `ERR_STATEMENT_PERIOD_OVERLAP` (HTTP 422) when the new period intersects the period of any non-terminal statement — one in `OPEN` or `CLOSED` — for the same rights holder; intersection follows the half-open convention, so back-to-back periods that merely touch are allowed. A new statement is `OPEN` with `event_ids` empty, `total_verified_seconds` zero, `volume_tier` null, and both totals null.

Closing a statement sweeps and prices the period. Close requires `OPEN` (otherwise `ERR_STATEMENT_NOT_OPEN`, HTTP 409) and requires at least one matching event: a `VERIFIED` usage event whose asset's `rights_holder` equals the statement's `rights_holder` and whose `aired_at` falls at or after `period_start` and strictly before `period_end` (otherwise `ERR_STATEMENT_EMPTY`, HTTP 409). The sweep then runs in a fixed, non-recomputable order. First the matching events are collected. Second, `total_verified_seconds` is computed as the sum of `duration_seconds_used` across the swept set — this step must fully complete before the next. Third, the `volume_tier` is derived from that total: fewer than 3,600 seconds (one hour of verified usage) is `TIER_0`; at least 3,600 but fewer than 36,000 seconds (ten hours) is `TIER_1`; 36,000 seconds or more is `TIER_2`. Fourth, each swept event's `final_accrual_cents` is recomputed with the final variant of the accrual: the event's raw accrual — units, market rate, and multiplier exactly as at verification — is multiplied by one minus the volume discount, where the discount is 0 percent for `TIER_0`, 10 percent for `TIER_1`, and 20 percent for `TIER_2`; the result is rounded half up to integer cents per event and floored at the same 25-cent per-event minimum. Fifth, `total_accrual_cents` is the sum of those per-event finals. Sixth, `provisional_total_cents` is the sum of the events' provisional accruals over the same swept set — no discount — so the provisional view is always at least the final total, and strictly greater whenever the tier carries a discount and at least one event sits above the floor. Because the final variant discounts against the statement's volume tier, identical event data yields a lower final accrual whenever the tier is not `TIER_0`. The close snapshots the swept ids into `event_ids` and stamps each swept event's `statement_id` with this statement.

A closed statement can be reopened — from `CLOSED` only, otherwise `ERR_STATEMENT_NOT_CLOSED` (HTTP 409) — which empties `event_ids`, clears every swept event's `statement_id` back to null, and resets the computed totals to null, returning the statement to `OPEN` for a fresh close.

Posting settles the statement and is gated three ways after the state check: the statement must be `CLOSED` (otherwise `ERR_STATEMENT_NOT_CLOSED`); the logical clock must have reached `period_end` (otherwise `ERR_PERIOD_NOT_ENDED`, HTTP 422); `total_accrual_cents` must be at least the 1,000-cent payout minimum (otherwise `ERR_PAYOUT_BELOW_MINIMUM`, HTTP 402); and every event snapshotted in `event_ids` must still be `VERIFIED` — an event disputed after close trips `ERR_STATEMENT_EVENTS_DIRTY` (HTTP 409). A successful post moves the statement to the terminal `POSTED` state and transitions every swept event from `VERIFIED` to `ROYALTY_POSTED`, the terminal state of the usage-event lifecycle.

### 3.8. Storage Tiering, Migration Jobs, and Cost Accounting

An asset's `storage_tier` — `ONLINE`, `NEARLINE`, or `DEEP_ARCHIVE` — is a dimension parallel to its catalog status. The catalog lifecycle of §3.1 never changes the tier, and tier migration never changes `catalog_status`; the only writer of `storage_tier` is a completed migration job.

An `ArchivistLead` creates a migration job with the `asset_id`, a `target_tier`, and the asset-pinned `expected_asset_version` of §2.7. The target tier must differ from the asset's current tier — migrating to the tier the asset already occupies is a malformed request rejected with `ERR_INVALID_REQUEST` (HTTP 400). The asset must not be `DISPOSED` (`ERR_ASSET_DISPOSED`, HTTP 409), must be clear of legal holds (`ERR_LEGAL_HOLD_ACTIVE`, HTTP 409), and must not already have another migration job `IN_PROGRESS` (`ERR_JOB_IN_PROGRESS_EXISTS`, HTTP 409). The stale-version check rejects the create with `ERR_STALE_ASSET_VERSION` (HTTP 412) when the client's `expected_asset_version` no longer matches the asset's current `version`. Creating a job also supersedes the queue: any existing `QUEUED` migration job for the same asset moves to the terminal `SUPERSEDED` state, and the asset's `version` increments by one as part of the create. The new job starts `QUEUED` with `retry_count` zero.

Execution belongs to the `LabTechnician`. Starting moves `QUEUED` to `IN_PROGRESS` (from any other state, `ERR_JOB_NOT_QUEUED`, HTTP 409). Completing requires `IN_PROGRESS` (otherwise `ERR_JOB_NOT_IN_PROGRESS`, HTTP 409), records the operator-supplied `checksum_sha256`, moves the job to the terminal `COMPLETED` state, writes the asset's `storage_tier` to the job's `target_tier`, and increments the asset's `version` by one — the residency change that the storage-cost calculation keys on. If the completed target is anything other than `DEEP_ARCHIVE`, completion additionally stages the asset's waiting recalls: every retrieval request in `RECALLING` moves to `STAGED` with `staged_at` set to the migration's completion time (§3.6). Failing requires `IN_PROGRESS` as well (otherwise `ERR_JOB_NOT_IN_PROGRESS`), records the supplied `reason` in `failure_reason`, and moves the job to `FAILED`.

A failed job can be retried from `FAILED` back to `QUEUED` (from any other state, `ERR_JOB_NOT_FAILED`, HTTP 409), incrementing `retry_count` by one; the migration retry budget is capped at 2, and a retry at the cap is rejected with `ERR_RETRY_BUDGET_EXHAUSTED` (HTTP 409). An `ArchivistLead` may cancel a job while it is `QUEUED` or `HOLD_PAUSED` — from any other state, `ERR_JOB_NOT_CANCELLABLE` (HTTP 409) — moving it to the terminal `CANCELLED` state; disposal execution (§3.5) cancels such jobs automatically. The legal-hold interplay of §3.4 pauses `QUEUED` jobs to `HOLD_PAUSED` when a hold activates on the asset and resumes them to `QUEUED` when the last active hold is released.

Storage cost is a computed read available to `SystemAdmin`, `ArchivistLead`, and `FinanceOfficer`, returning both variants for the current UTC calendar month as `projected_cost_cents`, `actual_cost_cents`, and a `currency` label. The tier rates are 4 cents per gigabyte per day for `ONLINE`, 1.5 for `NEARLINE`, and 0.25 for `DEEP_ARCHIVE`.

The projected variant is forward-looking and ignores migration history: it prices keeping the asset at its current tier for the rest of the current calendar month. The days remaining count today inclusively — the number of days in the month minus the current day of the month plus one — and the projected cost is `size_gb` times the current tier's rate times the days remaining, rounded half up once to integer cents.

The actual variant is chronological month-to-date. The asset's `COMPLETED` migration jobs are replayed in `created_at` order to build tier-residency intervals inside the current month, intersected with the window from the month start up to but not including now. The first interval opens at the asset's creation time — or at the month start if the asset was created earlier — at the tier the asset held then, which is `ONLINE` unless a migration moved it. Each interval is priced independently: its length in hours (the interval span in seconds divided by 3,600), multiplied by `size_gb` and the interval tier's daily rate divided by 24, rounded half up to integer cents per interval. The actual cost is the sum of those per-interval figures — each interval rounded before any summation. The two variants diverge precisely when a migration changed the asset's tier partway through the month.

### 3.9. Preservation Digitization: Tickets, Workstations, and Derivative Assets

Obsolete carriers are a fire drill with a queue. The lab's capacity is modeled as workstations: a `SystemAdmin` registers each with a unique `name` — a duplicate is rejected with `ERR_DUPLICATE_WORKSTATION_NAME` (HTTP 422) — and a `supported_formats` list naming the subset of `format_class` values the station can digitize. A workstation is created `ACTIVE`. Taking it down to `MAINTENANCE` is blocked while any ticket on the station is `ASSIGNED` or `DIGITIZING` (`ERR_WORKSTATION_BUSY`, HTTP 409); bringing it back to `ACTIVE` carries no precondition.

An `ArchivistLead` opens a digitization ticket for an asset whose `format_class` belongs to the obsolete set — `BETACAM_SP`, `UMATIC`, `VHS`, `FILM_16MM`, `AUDIO_REEL`, or `AUDIO_DAT`; a ticket for any other format is rejected with `ERR_FORMAT_NOT_OBSOLETE` (HTTP 422), and a ticket for a `DISPOSED` asset is rejected with `ERR_ASSET_DISPOSED` (HTTP 409). The create supplies `asset_id`, the planned slot `scheduled_start` and `scheduled_end` — end must lie strictly after start, otherwise `ERR_INVALID_REQUEST` — and the `output_format` of the derivative, either `PRORES_FILE` or `H264_FILE`. The ticket is created `QUEUED` with `rework_count` zero, no `workstation_id`, and its `priority_score` computed.

The priority score weighs decay against demand and is recomputed on read and inside auto-assign ranking. The asset's age in days is the elapsed logical time since its `created_at`, truncated down to whole days; the age in years truncates those days down to whole 365-day years. Demand counts the asset's delivered retrievals: retrieval requests in `DELIVERED` whose `delivered_at` falls inside the trailing 365-day window — the window excludes instants at or before now minus 365 days and includes instants up to and including now. The score is the decay risk of the asset's `format_class` times the age in years, plus ten times the delivered count. Decay risk by format: `BETACAM_SP` 90, `UMATIC` 85, `VHS` 70, `FILM_16MM` 95, `AUDIO_REEL` 80, `AUDIO_DAT` 75, `DIGITAL_FILE` 10, `PRORES_FILE` 5. All arithmetic is integer, with the day and year truncations being the only rounding.

Assignment is the lab's scheduling act, performed by a `LabTechnician` either manually per ticket or through the auto-assigner; both paths enforce the same four gates. The ticket must be `QUEUED` (otherwise `ERR_TICKET_NOT_QUEUED`, HTTP 409). The target workstation must be `ACTIVE` (otherwise `ERR_WORKSTATION_UNAVAILABLE`, HTTP 409). The asset's `format_class` must appear in the workstation's `supported_formats` (otherwise `ERR_WORKSTATION_FORMAT_UNSUPPORTED`, HTTP 422). And the buffered schedule rule must hold: for every ticket on the workstation in `ASSIGNED` or `DIGITIZING`, the new slot must end at least 30 minutes before the existing slot's start or start at least 30 minutes after the existing slot's end — a gap of exactly 30 minutes is allowed, while touching adjacency is a conflict rejected with `ERR_WORKSTATION_SCHEDULE_CONFLICT` (HTTP 422). Manual assignment takes the target `workstation_id` and keeps the ticket's planned slot; the auto-assigner takes a `workstation_id`, selects among `QUEUED` tickets whose asset format the station supports the one with the highest `priority_score` — ties broken toward the earliest `created_at` — and books the slot as now through now plus four hours, setting `scheduled_start` and `scheduled_end` accordingly. When no eligible ticket exists for the station, the auto-assigner is rejected with `ERR_NO_ELIGIBLE_TICKET` (HTTP 409). Either path sets the ticket's `workstation_id` and moves it to `ASSIGNED`.

Starting the work requires the ticket to be `ASSIGNED` (otherwise `ERR_TICKET_NOT_ASSIGNED`, HTTP 409) and the logical clock to have reached `scheduled_start` (otherwise `ERR_TICKET_NOT_DUE`, HTTP 422); it moves the ticket to `DIGITIZING`. Submitting for quality control moves `DIGITIZING` to `QC_REVIEW` (from any other state, `ERR_TICKET_NOT_DIGITIZING`, HTTP 409).

Quality control has three exits. Passing — optionally annotated with `qc_notes` — requires `QC_REVIEW` (otherwise `ERR_TICKET_NOT_IN_QC`, HTTP 409), moves the ticket to the terminal `COMPLETED` state, and creates the derivative asset: its `source_asset_id` set to the original asset's `id`, its `format_class` set to the ticket's `output_format`, its `ingest_batch_id` set to the original's batch — a system exception that is permitted even though the batch is `FINALIZED` — its `catalog_status` starting at `METADATA_DRAFT`, and its `storage_tier` at `ONLINE`. Failing requires the same state and a mandatory `qc_notes`. While `rework_count` is below the cap of 2, a failure loops the ticket back to `QUEUED`, increments `rework_count` by one, and clears `workstation_id` so the slot is freed; when `rework_count` has already reached 2, the next failure instead moves the ticket to the terminal `QC_FAILED` state and likewise clears `workstation_id`.

An `ArchivistLead` may cancel a ticket while it is `QUEUED` or `ASSIGNED` — from any other state, `ERR_TICKET_NOT_CANCELLABLE` (HTTP 409) — moving it to the terminal `CANCELLED` state; disposal execution (§3.5) cancels such tickets automatically.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201 on success; endpoints that modify an existing resource, trigger a state transition, or perform a computed read return HTTP 200. All request and response bodies conform to the envelope of §2.2, all list endpoints paginate per §2.3, and every endpoint enforces the validation order of §2.6. Request payloads, preconditions, side effects, and calculations are specified in the Section 3 narratives; this table is only an index.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /archive/_clock/set_current_utc | Set the logical clock; triggers the staged-request expiry sweep | SystemAdmin |
| POST | /archive/staff-members | Register a staff member | SystemAdmin |
| GET | /archive/staff-members | List staff members | All roles |
| GET | /archive/staff-members/{id} | Get a staff member | All roles |
| POST | /archive/ingest-batches | Create an ingest batch (OPEN) | IngestCoordinator |
| GET | /archive/ingest-batches | List ingest batches | All roles |
| GET | /archive/ingest-batches/{id} | Get an ingest batch | All roles |
| POST | /archive/ingest-batches/{id}/finalize | Finalize a batch | IngestCoordinator |
| POST | /archive/assets | Ingest an asset into an OPEN batch | IngestCoordinator |
| GET | /archive/assets | List assets with filters | All roles |
| GET | /archive/assets/{id} | Get an asset (postures computed at read time) | All roles |
| PATCH | /archive/assets/{id} | Edit descriptive metadata while editable | MetadataCataloger |
| POST | /archive/assets/{id}/submit-metadata | Submit metadata for review | MetadataCataloger |
| POST | /archive/assets/{id}/metadata-approve | Approve metadata (segregated from submitter) | MetadataLibrarian |
| POST | /archive/assets/{id}/metadata-reject | Reject metadata back to draft | MetadataLibrarian |
| POST | /archive/assets/{id}/archive | Archive a CATALOGED asset | ArchivistLead |
| POST | /archive/assets/{id}/recatalog | Reopen an ARCHIVED asset for metadata rework | ArchivistLead |
| GET | /archive/assets/{id}/storage-cost | Both storage-cost variants for the current month | SystemAdmin, ArchivistLead, FinanceOfficer |
| POST | /archive/proxy-renditions | Queue proxy generation for an asset | IngestCoordinator, LabTechnician |
| GET | /archive/proxy-renditions | List proxy renditions | All roles |
| GET | /archive/proxy-renditions/{id} | Get a proxy rendition | All roles |
| POST | /archive/proxy-renditions/{id}/claim | Claim a queued rendition | LabTechnician |
| POST | /archive/proxy-renditions/{id}/complete | Mark rendering complete | LabTechnician |
| POST | /archive/proxy-renditions/{id}/fail | Mark rendering failed | LabTechnician |
| POST | /archive/proxy-renditions/{id}/retry | Retry a failed rendition | LabTechnician |
| POST | /archive/rights-grants | Create a rights grant | RightsManager |
| GET | /archive/rights-grants | List rights grants | All roles |
| GET | /archive/rights-grants/{id} | Get a rights grant | All roles |
| POST | /archive/rights-grants/{id}/revoke | Revoke a grant | RightsManager |
| POST | /archive/legal-holds | Place a legal hold (cascades) | LegalCounsel |
| GET | /archive/legal-holds | List legal holds | All roles |
| GET | /archive/legal-holds/{id} | Get a legal hold | All roles |
| POST | /archive/legal-holds/{id}/release | Release a hold (segregated from placer) | LegalCounsel |
| POST | /archive/retention-policies | Create a retention policy (one per media type) | SystemAdmin |
| GET | /archive/retention-policies | List retention policies | All roles |
| POST | /archive/disposal-orders | Create a disposal order (version-pinned) | ArchivistLead |
| GET | /archive/disposal-orders | List disposal orders | All roles |
| GET | /archive/disposal-orders/{id} | Get a disposal order | All roles |
| POST | /archive/disposal-orders/{id}/submit | Submit an order for approval | ArchivistLead |
| POST | /archive/disposal-orders/{id}/approve | Approve an order; schedules the asset | ArchivistLead |
| POST | /archive/disposal-orders/{id}/reject | Reject an order | ArchivistLead |
| POST | /archive/disposal-orders/{id}/resubmit | Resubmit a BLOCKED order after hold release | ArchivistLead |
| POST | /archive/disposal-orders/{id}/execute | Execute an APPROVED order at/past its date | ArchivistLead |
| POST | /archive/disposal-orders/{id}/withdraw | Withdraw own order from DRAFT or APPROVED | ArchivistLead |
| POST | /archive/retrieval-requests | Create a retrieval request | Requester |
| GET | /archive/retrieval-requests | List retrieval requests | All roles |
| GET | /archive/retrieval-requests/{id} | Get a retrieval request | All roles |
| POST | /archive/retrieval-requests/{id}/start-review | Begin review | AccessOfficer |
| POST | /archive/retrieval-requests/{id}/approve | Approve; forks by storage tier and quotes the fee | AccessOfficer |
| POST | /archive/retrieval-requests/{id}/return | Return for more information | AccessOfficer |
| POST | /archive/retrieval-requests/{id}/reject | Reject the request | AccessOfficer |
| POST | /archive/retrieval-requests/{id}/stage-complete | Complete a deep-archive recall | LabTechnician |
| POST | /archive/retrieval-requests/{id}/deliver | Deliver a staged request | AccessOfficer |
| POST | /archive/retrieval-requests/{id}/cancel | Cancel a non-terminal request | Requester (own), AccessOfficer |
| POST | /archive/usage-events | Report a usage event | Requester |
| GET | /archive/usage-events | List usage events | All roles |
| GET | /archive/usage-events/{id} | Get a usage event | All roles |
| POST | /archive/usage-events/{id}/verify | Verify an event; computes provisional accrual | FinanceOfficer |
| POST | /archive/usage-events/{id}/dispute | Dispute an event | FinanceOfficer |
| POST | /archive/usage-events/{id}/resubmit | Resubmit a disputed event (original reporter only) | Requester |
| POST | /archive/royalty-statements | Create a statement (OPEN) | FinanceOfficer |
| GET | /archive/royalty-statements | List royalty statements | All roles |
| GET | /archive/royalty-statements/{id} | Get a royalty statement | All roles |
| POST | /archive/royalty-statements/{id}/close | Close: sweep verified events, compute tier and totals | FinanceOfficer |
| POST | /archive/royalty-statements/{id}/reopen | Reopen a CLOSED statement; clears the snapshot | FinanceOfficer |
| POST | /archive/royalty-statements/{id}/post | Post a CLOSED statement | FinanceOfficer |
| POST | /archive/migration-jobs | Create a migration job (version-pinned; supersedes queue) | ArchivistLead |
| GET | /archive/migration-jobs | List migration jobs | All roles |
| GET | /archive/migration-jobs/{id} | Get a migration job | All roles |
| POST | /archive/migration-jobs/{id}/start | Start a queued job | LabTechnician |
| POST | /archive/migration-jobs/{id}/complete | Complete a job; updates the asset's tier | LabTechnician |
| POST | /archive/migration-jobs/{id}/fail | Fail an in-progress job | LabTechnician |
| POST | /archive/migration-jobs/{id}/retry | Retry a failed job | LabTechnician |
| POST | /archive/migration-jobs/{id}/cancel | Cancel a QUEUED or HOLD_PAUSED job | ArchivistLead |
| POST | /archive/digitization-tickets | Create a digitization ticket for an obsolete-format asset | ArchivistLead |
| GET | /archive/digitization-tickets | List digitization tickets | All roles |
| GET | /archive/digitization-tickets/{id} | Get a digitization ticket | All roles |
| POST | /archive/digitization-tickets/{id}/assign | Assign a queued ticket to a workstation | LabTechnician |
| POST | /archive/digitization-tickets/auto-assign | Auto-assign the highest-priority eligible ticket | LabTechnician |
| POST | /archive/digitization-tickets/{id}/start | Start digitizing | LabTechnician |
| POST | /archive/digitization-tickets/{id}/submit-qc | Submit for quality control | LabTechnician |
| POST | /archive/digitization-tickets/{id}/qc-pass | Pass QC; creates the derivative asset | LabTechnician |
| POST | /archive/digitization-tickets/{id}/qc-fail | Fail QC; rework loop or terminal failure | LabTechnician |
| POST | /archive/digitization-tickets/{id}/cancel | Cancel a QUEUED or ASSIGNED ticket | ArchivistLead |
| POST | /archive/workstations | Create a workstation (ACTIVE) | SystemAdmin |
| GET | /archive/workstations | List workstations | All roles |
| GET | /archive/workstations/{id} | Get a workstation | All roles |
| PATCH | /archive/workstations/{id} | Toggle workstation status ACTIVE / MAINTENANCE | SystemAdmin |

## 5. Error Code Catalogue

The catalogue below maps every error identifier to its HTTP status code. The conditions under which each error is raised are specified in the narratives of Sections 2 and 3.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_STAFF_MEMBER_NOT_FOUND | 404 |
| ERR_BATCH_NOT_FOUND | 404 |
| ERR_ASSET_NOT_FOUND | 404 |
| ERR_PROXY_NOT_FOUND | 404 |
| ERR_GRANT_NOT_FOUND | 404 |
| ERR_HOLD_NOT_FOUND | 404 |
| ERR_ORDER_NOT_FOUND | 404 |
| ERR_RETRIEVAL_REQUEST_NOT_FOUND | 404 |
| ERR_EVENT_NOT_FOUND | 404 |
| ERR_STATEMENT_NOT_FOUND | 404 |
| ERR_JOB_NOT_FOUND | 404 |
| ERR_TICKET_NOT_FOUND | 404 |
| ERR_WORKSTATION_NOT_FOUND | 404 |
| ERR_BATCH_NOT_OPEN | 409 |
| ERR_EMPTY_BATCH | 409 |
| ERR_BATCH_ASSETS_UNRESOLVED | 409 |
| ERR_INVALID_CATALOG_TRANSITION | 409 |
| ERR_ASSET_LOCKED | 409 |
| ERR_PROXY_NOT_READY | 409 |
| ERR_NO_RIGHTS_GRANT_ON_RECORD | 409 |
| ERR_PROXY_NOT_QUEUED | 409 |
| ERR_PROXY_NOT_RENDERING | 409 |
| ERR_PROXY_NOT_FAILED | 409 |
| ERR_RETRY_BUDGET_EXHAUSTED | 409 |
| ERR_GRANT_ALREADY_REVOKED | 409 |
| ERR_HOLD_ALREADY_RELEASED | 409 |
| ERR_ACTIVE_DISPOSAL_ORDER_EXISTS | 409 |
| ERR_DISPOSAL_ORDER_NOT_DRAFT | 409 |
| ERR_DISPOSAL_ORDER_NOT_PENDING | 409 |
| ERR_DISPOSAL_ORDER_NOT_APPROVED | 409 |
| ERR_DISPOSAL_ORDER_NOT_BLOCKED | 409 |
| ERR_DISPOSAL_ORDER_NOT_WITHDRAWABLE | 409 |
| ERR_ASSET_DISPOSED | 409 |
| ERR_ASSET_NOT_RETRIEVABLE | 409 |
| ERR_ASSET_NOT_ARCHIVED | 409 |
| ERR_REQUEST_NOT_SUBMITTED | 409 |
| ERR_REQUEST_NOT_UNDER_REVIEW | 409 |
| ERR_REQUEST_NOT_RECALLING | 409 |
| ERR_REQUEST_NOT_STAGED | 409 |
| ERR_REQUEST_TERMINAL | 409 |
| ERR_EVENT_NOT_REPORTED | 409 |
| ERR_EVENT_NOT_DISPUTABLE | 409 |
| ERR_EVENT_NOT_DISPUTED | 409 |
| ERR_STATEMENT_NOT_OPEN | 409 |
| ERR_STATEMENT_NOT_CLOSED | 409 |
| ERR_STATEMENT_EMPTY | 409 |
| ERR_STATEMENT_EVENTS_DIRTY | 409 |
| ERR_JOB_NOT_QUEUED | 409 |
| ERR_JOB_NOT_IN_PROGRESS | 409 |
| ERR_JOB_NOT_FAILED | 409 |
| ERR_JOB_NOT_CANCELLABLE | 409 |
| ERR_JOB_IN_PROGRESS_EXISTS | 409 |
| ERR_TICKET_NOT_QUEUED | 409 |
| ERR_TICKET_NOT_ASSIGNED | 409 |
| ERR_TICKET_NOT_DIGITIZING | 409 |
| ERR_TICKET_NOT_IN_QC | 409 |
| ERR_TICKET_NOT_CANCELLABLE | 409 |
| ERR_WORKSTATION_UNAVAILABLE | 409 |
| ERR_WORKSTATION_BUSY | 409 |
| ERR_LEGAL_HOLD_ACTIVE | 409 |
| ERR_ASSET_UNDER_LEGAL_HOLD | 409 |
| ERR_SOD_METADATA_SELF_APPROVE | 403 |
| ERR_SOD_DISPOSAL_SELF_APPROVE | 403 |
| ERR_SOD_RETRIEVAL_SELF_APPROVE | 403 |
| ERR_SOD_HOLD_SELF_RELEASE | 403 |
| ERR_ASSET_VERSION_DRIFT | 409 |
| ERR_RIGHTS_WINDOW_PAST | 422 |
| ERR_EXCLUSIVE_GRANT_OVERLAP | 422 |
| ERR_DELIVERY_DEADLINE_PAST | 422 |
| ERR_DELIVERY_BEYOND_RIGHTS_WINDOW | 422 |
| ERR_RIGHTS_EXPIRED_FOR_PURPOSE | 422 |
| ERR_TICKET_NOT_DUE | 422 |
| ERR_DISPOSAL_NOT_YET_DUE | 422 |
| ERR_PERIOD_NOT_ENDED | 422 |
| ERR_STATEMENT_PERIOD_OVERLAP | 422 |
| ERR_WORKSTATION_SCHEDULE_CONFLICT | 422 |
| ERR_METADATA_INCOMPLETE | 422 |
| ERR_FORMAT_NOT_OBSOLETE | 422 |
| ERR_WORKSTATION_FORMAT_UNSUPPORTED | 422 |
| ERR_DUPLICATE_MEDIA_TYPE_POLICY | 422 |
| ERR_DUPLICATE_WORKSTATION_NAME | 422 |
| ERR_DUPLICATE_STAFF_EMAIL | 422 |
| ERR_RETENTION_NOT_ELAPSED | 422 |
| ERR_NO_ELIGIBLE_TICKET | 409 |
| ERR_PAYOUT_BELOW_MINIMUM | 402 |
| ERR_STALE_ASSET_VERSION | 412 |
