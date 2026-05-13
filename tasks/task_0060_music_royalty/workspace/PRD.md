# Music Royalty Distribution API — Product Requirements Document

## 1. Introduction

Modern music distribution moves revenue from streaming services, broadcasters, public venues, and live promoters into the hands of composers, lyricists, performers, recording owners, and the publishers, labels, and collective management organisations that represent them. The accounting glue between those two endpoints — what each play is worth, who is owed what fraction, whose money is frozen because a co-creator contests authorship, which jurisdiction's tax rate applies, and which payment channel a Japanese organisation versus a Chinese individual versus a European publisher uses — is the responsibility of this Royalty Distribution platform. The system serves five operational personas (a `PlatformAdmin` configuring infrastructure, a `RegistrationReviewer` vetting incoming work registrations, a `FinanceOps` operator running quarterly settlement cycles, a `DisputeOfficer` arbitrating contested claims, and a `RightsHolder` registering works and tracking earnings) plus a sixth machine persona (`PlaybackSource`) representing the external reporting feeds.

This document specifies a synchronous, immediately-consistent REST API mounted under `/royalty`. The pipeline it describes is fundamentally a pricing engine wrapped in workflow orchestration: works are registered and approved, shares are declared and audited, playback events arrive and are validated, royalty pools are computed at end-of-period, distribution rules translate pool money into per-share allocations, dispute postures freeze and unfreeze that money, and payout batches finally convert RELEASED distributions into Payments routed through the appropriate banking channel. The platform must be deterministic enough to reproduce a settlement penny-for-penny on demand, auditable enough that every change to a share or distribution is recoverable from history, and safe enough that a minor's earnings cannot escape guardian routing and a disputed work's funds cannot leak out before resolution.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must include two headers: `X-User-Role` and `X-User-ID`. Either header missing yields `ERR_AUTH_REQUIRED` with HTTP 401, as does an `X-User-Role` value that is not one of the six declared roles. When an authenticated caller invokes an endpoint they are not permitted to use, the request is rejected with `ERR_FORBIDDEN` and HTTP 403.

Six roles are recognised, spelled exactly as follows:

- **`PlatformAdmin`** — the administrative operator who provisions rights-holders, publishes distribution rules, performs forfeitures, and operates the test-driving facilities (PSP callback, clock advance, retry sweep, external-sync inspection). `X-User-ID` for this role is an opaque operator identifier not tied to any persisted entity; the server may record it in audit fields (for example, as `changed_by_id` on a `ShareChangeAudit`) but does not compare it to any entity's `id`.
- **`RightsHolder`** — an author, performer, or organisation that owns works and shares. When `X-User-Role` is `RightsHolder`, `X-User-ID` is the `id` of the acting `RightsHolder`; ownership checks on any resource that references a `RightsHolder` compare the resource's foreign-key field to `X-User-ID`. A holder may only submit, withdraw, share-edit, or dispute-withdraw on resources whose owner identifier matches their `X-User-ID`.
- **`RegistrationReviewer`** — the operator who takes works under review, approves them, rejects them, or returns them to draft. `X-User-ID` for this role is an opaque operator identifier not tied to any persisted entity; the server records it as `reviewer_id` on the reviewed `Work` but does not compare it to any entity's `id`.
- **`FinanceOps`** — the operator who opens, patches, closes, and finalises royalty pools and runs payout batches. `X-User-ID` for this role is an opaque operator identifier not tied to any persisted entity; the server may record it on audit-style fields but does not compare it to any entity's `id`.
- **`DisputeOfficer`** — the operator who runs the dispute workflow and issues mediation and arbitration decisions. `X-User-ID` for this role is an opaque operator identifier not tied to any persisted entity; the server records it as `arbitrator_id` on a resolved `Dispute` but does not compare it to any entity's `id`.
- **`PlaybackSource`** — the external reporting source ingesting playback batches under HMAC authentication. `X-User-ID` for this role is an opaque operator identifier not tied to any persisted entity (a stable source label such as a streaming service handle); the server may record it on the submitted batch but does not compare it to any entity's `id`.

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

All list endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10 when omitted; it must be an integer between 1 (minimum) and 100 (maximum) inclusive. The `offset` parameter defaults to 0 and must be a non-negative integer. List results are ordered by `created_at` ascending. The pagination block in the response `meta` reports the four fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the size of the unpaginated result set and `has_more` is `true` whenever further pages exist beyond the current window.

### 2.4. Common Resource Properties and Versioning

Every resource that this PRD treats as common-fields-bearing — `Work`, `RightsHolder`, `AgencyBinding`, `RightsShare`, `PlaybackBatch`, `RoyaltyPool`, `Distribution`, `MicroBalance`, `Dispute`, `PayoutBatch`, `Payment` — carries the standard four-tuple: an `id` that is a server-minted UUID with no type prefix; a `created_at` timestamp formatted as an ISO 8601 UTC string with three fractional digits, set at row creation and never mutated; an `updated_at` timestamp in the same format, refreshed on every mutation of the row; and an integer `version` that starts at 1 at creation and increments by exactly one each time the row is mutated. Four scaffold entities are deliberately leaner — `ShareChangeAudit`, `PlaybackEvent`, `DistributionRuleVersion`, and `ExternalSyncEvent` — these carry only `id` and `created_at`; both `updated_at` and `version` are absent on them, reflecting their append-only or immutable nature.

The `version` field participates in Optimistic Concurrency Control. Every mutating endpoint accepts an optional `version` in the request body. When the client supplies `version`, the server compares it against the current row's `version`; a mismatch is rejected with `ERR_VERSION_CONFLICT` (HTTP 409). When the client omits `version`, the OCC check is skipped and the mutation proceeds with last-write-wins semantics. Successful mutations bump `version` by one and refresh `updated_at`.

### 2.5. Nested Path Resolution

Several endpoints expose nested resources — for example, `/royalty/works/{id}/shares/{share_id}` and `/royalty/works/{id}/shares/{share_id}/audit`. Existence checks proceed left-to-right along the path: the platform first resolves the outer `id` (in the example, the `Work`), and only after confirming the parent exists does it resolve the inner `share_id` (the `RightsShare`) and verify that the share actually belongs to the parent work. Any failure along this chain returns `ERR_NOT_FOUND` (HTTP 404) keyed to the first segment that fails. The same left-to-right discipline applies to referenced foreign keys in request bodies (`rights_holder_id`, `agency_binding_id`, `work_id`, `playback_batch_id`, `royalty_pool_id`, `rights_share_id`, `payout_batch_id`, `claimant_rights_holder_id`, `related_entity_id`, `guardian_holder_id`, `distribution_rule_version_id`) — non-resolvable identifiers yield `ERR_NOT_FOUND`.

### 2.6. Money, Currency, and Precision

All monetary amounts on the wire are integer **whole cents** (or the smallest unit of the named currency — JPY uses whole yen, not sub-yen units, but the field is still named in cents-form for uniformity). The platform supports five payout currencies: `USD`, `EUR`, `GBP`, `JPY`, and `CNY`. All rounding throughout the platform — platform-share deduction, mechanical/performance split, per-work allocation, per-share allocation, agency commission, admin tier fee, tax withholding — uses **round half up** at **zero decimal places** (whole cents). The single non-cent monetary quantity is `commission_percent` on `AgencyBinding`, which is a percent with two decimal places; it is used as a percentage in calculations, never as a cent amount.

Tax withholding follows a per-jurisdiction table keyed by `RightsHolder.tax_jurisdiction` (an ISO 3166-1 alpha-2 country code): United States is 30%, the United Kingdom is 20%, Germany is 26%, Japan is 20%, China is 10%, France is 25%, Ireland is 20%, and any jurisdiction not enumerated defaults to 30%.

### 2.7. Dispute Posture and Money Safety

A `Work` carries a derived `dispute_posture` of either `CLEAR` or `FROZEN`. Posture is `FROZEN` if and only if there exists at least one `Dispute` on this work whose status is one of `OPEN`, `UNDER_INVESTIGATION`, `MEDIATION`, or `ARBITRATION`; otherwise the posture is `CLEAR`. Posture is recomputed on every dispute open and on every dispute resolution event (resolve, withdraw). When posture flips from `CLEAR` to `FROZEN`, every `PENDING` `Distribution` on that work flips to `FROZEN`; when posture flips from `FROZEN` to `CLEAR`, every `FROZEN` `Distribution` on that work flips to `RELEASED`. This guarantees money belonging to a disputed work cannot be paid out while the dispute is alive, and money is automatically released the moment the last open dispute settles.

### 2.8. Source Authentication for Playback Ingest

Every playback batch submitted by a `PlaybackSource` carries an HMAC-SHA256 hex digest as `source_signature`. The platform recomputes `HMAC-SHA256(canonical_payload, source_secret)` using the secret pre-registered against the reporting `source_identifier` and compares the result to `source_signature`. A mismatch yields `ERR_PLAYBACK_SIGNATURE_INVALID` (HTTP 403); the batch is recorded with `validity_status` set to `INVALID_SIGNATURE` and `total_events_accepted` of 0.

### 2.9. Cascade Semantics and Audit Trails

Mutations that propagate across rows are explicit and depth-bounded by the scaffold. Every cascade refreshes `updated_at` and bumps `version` on each touched row that carries common fields. Every mutation of a `RightsShare` writes a `ShareChangeAudit` row capturing the actor (`changed_by_role`, `changed_by_id`), the change kind (one of `CREATED`, `PERCENT_UPDATED`, `STATUS_TRANSITION`, `AGENCY_REBOUND`, `TERMINATED`), and a `before_snapshot` and `after_snapshot` over the tuple `{share_percent, share_status, agency_binding_id}` (the `before_snapshot` is null for the `CREATED` kind). Audit rows are append-only and carry only `id` and `created_at`.

### 2.10. Validation Priority

When multiple validations apply to one request, they are evaluated in a fixed priority order. The first violation found halts the request and is the one returned to the caller; later checks are not consulted. The ordering, from highest to lowest precedence:

1. Both `X-User-Role` and `X-User-ID` headers must be present; missing yields `ERR_AUTH_REQUIRED` (401).
2. `X-User-Role` must be one of the six declared roles; an unknown value also yields `ERR_AUTH_REQUIRED` (401).
3. The role must be permitted to invoke this endpoint per the RBAC matrix; a forbidden role yields `ERR_FORBIDDEN` (403).
4. Every path-referenced resource must exist (resolved left-to-right); a missing resource yields `ERR_NOT_FOUND` (404).
5. On share-creation and share-mutation endpoints, every referenced `rights_holder_id`, `agency_binding_id`, and `work_id` must also resolve to an existing entity; missing yields `ERR_NOT_FOUND` (404).
6. On work-action endpoints, the target work must be in the correct state for the action — submit requires `DRAFT`, approve and reject require `UNDER_REVIEW`, take-review requires `SUBMITTED`; a state mismatch yields `ERR_INVALID_STATE` (409).
7. To terminate a share via holder-initiated request, the work's `dispute_posture` must be `CLEAR`; a frozen posture yields `ERR_WORK_FROZEN` (409).
8. To close a pool, the pool's `status` must be `OPEN` and the current server time must be at or after `period_end`; otherwise `ERR_INVALID_STATE` (409).
9. To finalise a pool, the pool's `status` must be `CLOSED` and no `Distribution` under it may carry `status` of `FROZEN`; a frozen distribution yields `ERR_POOL_HAS_FROZEN_DISTRIBUTIONS` (409).
10. Creating a `RightsHolder` whose `holder_kind` is `INDIVIDUAL` and who is a minor requires a valid `guardian_holder_id`; otherwise `ERR_MINOR_REQUIRES_GUARDIAN` (422).
11. Payouts targeting a minor must route to the guardian's bank account; a minor lacking an active guardian binding yields `ERR_MINOR_PAYOUT_BLOCKED` (422).
12. Playback ingest requires the HMAC signature to match; otherwise `ERR_PLAYBACK_SIGNATURE_INVALID` (403).
13. On work registration, both `isrc` (when supplied) and `iswc` (when supplied) must be unique across all existing works whose corresponding field is non-null; collision yields `ERR_DUPLICATE_IDENTIFIER` (409).
14. On submit, the sum of `contribution_percent` across `co_creators` must equal exactly 100.00; otherwise `ERR_COCREATOR_SUM_INVALID` (422).
15. On approve, the sum of `share_percent` across all `ACTIVE` `RightsShare` rows for the work must equal exactly 100.00; otherwise `ERR_SHARE_SUM_INVALID` (422).
16. On share create or share update, a supplied `agency_binding_id` must reference an `AgencyBinding` whose `rights_holder_id` equals the share's `rights_holder_id`, whose `status` is `ACTIVE`, and whose `territory` is either `WW` or matches the pool region the share would draw from; otherwise `ERR_AGENCY_BINDING_INAPPLICABLE` (422).
17. When creating a `DistributionRuleVersion` with `distribution_mode` of `HYBRID`, the sum of `per_play_weight` and `per_duration_weight` must equal exactly 1.00; otherwise `ERR_RULE_WEIGHTS_INVALID` (422).
18. At pool close, the pinned `DistributionRuleVersion.effective_from` must be strictly less than the pool's `period_end`; otherwise `ERR_RULE_NOT_EFFECTIVE` (422).
19. On agency binding creation, `effective_from` must be strictly less than `effective_until` when `effective_until` is supplied, and a new binding for the same `(rights_holder_id, agency_kind, territory)` triple must not overlap an existing `ACTIVE` binding's half-open interval; an overlap yields `ERR_AGENCY_BINDING_OVERLAP` (409).
20. A successor binding for the same `(rights_holder_id, agency_kind)` and territory must start at or after the predecessor's `effective_until` — strictly earlier is rejected with `ERR_AGENCY_BINDING_OVERLAP` (409). No buffer is required between predecessor end and successor start.
21. On playback ingest, the reporting window must satisfy `reporting_period_end` strictly greater than `reporting_period_start`, `reporting_period_end` at or before the current server time, and a duration of at most 31 days; otherwise `ERR_PLAYBACK_RANGE_INVALID` (422).
22. On playback ingest, a batch from the same `source_identifier` covering exactly the same `[reporting_period_start, reporting_period_end)` window that already exists in the system with `validity_status` of `VALID` yields `ERR_DUPLICATE_BATCH` (409).
23. On payout-batch generation, a generated `Payment` whose `gross_cents` is below `minimum_payout_cents` and whose accumulated micro-balance has not exceeded the cap must not be created; an attempt that violates this yields `ERR_BELOW_MIN_PAYOUT` (422).
24. On payout-batch generation, `cycle_tag` must be unique across all `PayoutBatch` rows; otherwise `ERR_DUPLICATE_CYCLE` (409).
25. On distribution forfeit, the holding rights-holder must have either a payment whose `status` is `FAILED` or `ABANDONED`, or a revoked `bank_account_token`; otherwise `ERR_DISTRIBUTION_NOT_FORFEITABLE` (409).
26. OCC: when the client supplies `version` on a mutating endpoint, the server compares it to the current `version` and rejects mismatches with `ERR_VERSION_CONFLICT` (409).
27. On dispute resolve, the body must carry an `outcome` of either `UPHELD` or `DISMISSED` and an `arbitration_decision`; missing or malformed yields `ERR_RESOLUTION_INVALID` (422).
28. Generic input shape validation (missing required fields, wrong types, out-of-range numerics) runs after all of the above and yields `ERR_VALIDATION` (422).

The ordering matters in practice: an unauthenticated request to a work whose state is wrong returns `ERR_AUTH_REQUIRED`, not `ERR_INVALID_STATE`. A minor without guardian binding on a request that also has invalid co-creator sums returns `ERR_MINOR_REQUIRES_GUARDIAN`, not `ERR_COCREATOR_SUM_INVALID`. State checks always dominate generic input-shape checks, and OCC mismatches dominate input-shape checks but defer to state checks.

### 2.11. Concurrency Serialisation

The platform serialises five contended operations and returns specific error identifiers for each loser:

- Two `RegistrationReviewer` approvals on the same work race; exactly one succeeds. The loser sees the work no longer in `UNDER_REVIEW` and receives `ERR_INVALID_STATE` (HTTP 409). Serialisation is first-writer-wins on the `Work.registration_status` transition out of `UNDER_REVIEW`.
- Two competing `RightsShare` modifications race on the same share; OCC on the share's `version` determines the winner. The loser receives `ERR_VERSION_CONFLICT` (HTTP 409).
- A `PlaybackBatch` ingest collides with an identical-window batch from the same `source_identifier`. At most one becomes `VALID` per `(source_identifier, [period_start, period_end))`; the second receives `ERR_DUPLICATE_BATCH` (HTTP 409) and is recorded with `validity_status` of `DEDUPED_REJECTED`.
- Two pool-close attempts on the same `RoyaltyPool` race; exactly one succeeds. The loser sees the pool already `CLOSED` and receives `ERR_INVALID_STATE` (HTTP 409). Serialisation is first-writer-wins on the `RoyaltyPool.status` transition out of `OPEN`.
- Two payout-batch executions on the same `PayoutBatch` race; exactly one succeeds. The loser sees the batch already `RUNNING` and receives `ERR_INVALID_STATE` (HTTP 409). Serialisation is first-writer-wins on the `PayoutBatch.status` transition from `PENDING` to `RUNNING`.
- A dispute resolution races with a fresh dispute opening on the same work. The platform recomputes `Work.dispute_posture` atomically; if any open dispute remains after both operations settle, posture stays `FROZEN`. The loser of the OCC contention on `Work.version` receives `ERR_VERSION_CONFLICT` (HTTP 409).

## 3. Business Logic & Workflows

### 3.1. Registering a Work

A `RightsHolder` initiates the lifecycle by registering a new musical work. The submission identifies the work by its `title`, declares its `duration_seconds` (a positive integer up to 7200 — two hours — and at least 1), and assigns one of four `rights_type` values: `COMPOSITION`, `LYRICS`, `RECORDING`, or `PERFORMANCE`. The two industry identifiers — `isrc` and `iswc` — interlock with the type: an `isrc` (exactly 12 alphanumeric characters) is required when `rights_type` is `RECORDING` or `PERFORMANCE`, and an `iswc` (exactly 11 characters matching the pattern of a leading `T` followed by ten digits) is required when `rights_type` is `COMPOSITION` or `LYRICS`. Both identifiers are unique across the `Work` table where they are non-null; a duplicate `isrc` or duplicate `iswc` at create time is rejected with `ERR_DUPLICATE_IDENTIFIER`. The registration also captures `co_creators` — a list of one to sixteen entries, each describing a `full_name`, a `role` from the set `{COMPOSER, LYRICIST, PRODUCER, PERFORMER}`, and a `contribution_percent` — and an `original_proof_url` that points to an HTTP or HTTPS artefact of the originality proof (a notarised manuscript scan, for example). The newly-created work lives in state `DRAFT`, with `registration_status` set to `DRAFT`, `dispute_posture` initialised to `CLEAR`, and `reject_reason` and `reviewer_id` both null.

While still in `DRAFT`, the holder may add `RightsShare` rows declaring who owns what fraction of the work. Each share carries a `work_id`, a `rights_holder_id`, a `share_percent` with two decimal places between 0.01 and 100.00 inclusive, a derived `share_status` (defaulting to `ACTIVE`), and an optional `agency_binding_id` that — when set — pins which `AgencyBinding` will deduct commission from this share's distributions. Creating a share emits a `ShareChangeAudit` row with `change_kind` of `CREATED` and an `after_snapshot` capturing the initial `{share_percent, share_status, agency_binding_id}` triple (the `before_snapshot` is null on creation).

When the holder is ready, they trigger the submission, advancing the work from `DRAFT` to `SUBMITTED`. The transition checks four preconditions: the required metadata (`title`, `duration_seconds`, `rights_type`) is present; the `isrc`/`iswc` interlock with `rights_type` is satisfied; the sum of `contribution_percent` across all `co_creators` equals exactly 100.00 (otherwise `ERR_COCREATOR_SUM_INVALID`); and `original_proof_url` is supplied. The side effect is to set `registration_status` to `SUBMITTED`.

### 3.2. Review, Approval, and Rejection

A `RegistrationReviewer` who picks up a `SUBMITTED` work advances it to `UNDER_REVIEW`, with the only side effect being to stamp `reviewer_id` with their `X-User-ID`. From `UNDER_REVIEW`, the reviewer has three outcomes. Approval flips the work to `APPROVED`; this is gated on a single business precondition — at least one `RightsShare` must exist for this work whose `share_status` is `ACTIVE`, and the sum of `share_percent` across all such active shares must equal exactly 100.00. If the shares do not cover the work, the approval is rejected with `ERR_SHARE_SUM_INVALID`. On success, the work's `registration_status` becomes `APPROVED` and `dispute_posture` is set to `CLEAR` as its initial posture.

Rejection requires the reviewer to supply a `reject_reason` of 1 to 500 characters and produces a layered cascade. The work's `registration_status` flips to `REJECTED`; every `RightsShare` row on this work whose `share_status` is `ACTIVE` transitions to `TERMINATED` (cascade depth 2); and each of those terminated shares emits a `ShareChangeAudit` row with `change_kind` of `TERMINATED` capturing the pre-termination and post-termination snapshots (cascade depth 3). The reject reason is persisted on the work itself.

Returning a submission to draft is a revision loop: from `SUBMITTED`, the reviewer can move the work back to `DRAFT` so the holder may amend metadata before re-submission. This carries no preconditions and the only side effect is the state flip. The owning holder may also withdraw a work directly from `DRAFT`, transitioning it to the terminal `WITHDRAWN` state with no cascades.

The two terminal states for the registration lifecycle are `REJECTED` and `WITHDRAWN`.

### 3.3. Share Ownership and the Audit Ledger

Once a work is `APPROVED`, share manipulation continues to be available to the owning holder (and, on override, to `PlatformAdmin`). A share's `share_status` lifecycle is `ACTIVE` → `DISPUTED` (set on disputes that target this specific share) → `TERMINATED`, with `ACTIVE` → `TERMINATED` as the direct termination path; `ACTIVE` is the initial value, and `TERMINATED` is the terminal value. A share update may target one or more of three writable attributes: `share_percent` (re-allocating the holder's fraction of the work), `agency_binding_id` (rebinding to a different agency or unbinding entirely), and `share_status` (typically to drive a `TERMINATED` transition or to mark a share `DISPUTED` for the duration of an active dispute). Each update kind writes a `ShareChangeAudit` row with the corresponding `change_kind` — `PERCENT_UPDATED`, `AGENCY_REBOUND`, `STATUS_TRANSITION`, or `TERMINATED` — and snapshots both the pre-change and post-change `{share_percent, share_status, agency_binding_id}` triple.

Holder-initiated termination of a share is blocked while the parent work's `dispute_posture` is `FROZEN`; an attempt is rejected with `ERR_WORK_FROZEN`. This is the dispute system's guard rail against losing ownership context mid-arbitration; a `PlatformAdmin` retains the override path. Share-percent updates and agency rebindings continue to be available even while the work is frozen, because they do not destroy share-history continuity; only termination is gated.

The audit ledger is exposed as a paginated, ascending-`created_at`-ordered list per share, viewable by `PlatformAdmin`, the owning `RightsHolder`, or a `DisputeOfficer` investigating a related claim. Audit rows themselves carry only `id` and `created_at` — no `updated_at`, no `version` — because they are append-only history.

### 3.4. Agency Bindings, Territories, and Commission

A `RightsHolder` may attach themselves to one or more agency representations: a `PUBLISHER`, a `LABEL`, or a `CMO` (collective management organisation). Each binding declares a `rights_holder_id`, an `agency_kind`, a human-readable `agency_name` of 1 to 200 characters, a `territory` (an ISO 3166-1 alpha-2 country code or the literal `WW` for worldwide), a `commission_percent` between 0.00 and 50.00 inclusive at two decimal places, an inclusive UTC `effective_from`, and an optional exclusive UTC `effective_until`. The binding's derived `status` is `ACTIVE` while the current time lies within the half-open `[effective_from, effective_until)` window and `TERMINATED` after explicit termination.

Two anti-overlap rules govern the binding timeline for the same `(rights_holder_id, agency_kind, territory)` triple. First, on creation, the new binding's interval must not overlap any existing `ACTIVE` binding on the same triple; an overlap yields `ERR_AGENCY_BINDING_OVERLAP`. Second, a successor binding for the same `(rights_holder_id, agency_kind)` in the same territory must start at or after its predecessor's `effective_until` — strictly earlier is rejected with the same `ERR_AGENCY_BINDING_OVERLAP`; the rule allows zero buffer (immediate handover at the same instant is valid). The binding's `effective_from` must also be strictly less than `effective_until` when both are supplied. Explicit termination through the terminate operation flips `status` to `TERMINATED`.

A `RightsShare` may reference an `AgencyBinding` by `agency_binding_id`. The reference is applicable only when the binding belongs to the share's holder (`rights_holder_id` matches), is `ACTIVE`, and its `territory` is either `WW` or matches the region of the pool from which the share will draw. An inapplicable reference at share-create or share-update time is rejected with `ERR_AGENCY_BINDING_INAPPLICABLE`. When applicable, the binding's `commission_percent` is deducted from each distribution's gross before tax.

### 3.5. Holders, Minors, Tax, and Payment Routing

A `PlatformAdmin` provisions every `RightsHolder` with their `legal_name` (1 to 200 characters), a `holder_kind` of either `INDIVIDUAL` or `ORGANIZATION`, a `tax_jurisdiction` (exactly two uppercase letters, the ISO country code that determines withholding), a `payout_currency` from the set `{USD, EUR, GBP, JPY, CNY}`, and a tokenised `bank_account_token` of 1 to 64 characters from the payment system. For individuals, the `date_of_birth` must also be supplied as an ISO 8601 `YYYY-MM-DD` date; for organisations, the field is left null.

The platform computes `is_minor` at creation time as a frozen boolean: it is true if and only if the holder is an `INDIVIDUAL` and the elapsed time between `date_of_birth` and the current date is strictly less than 18 years on the date the record was created. The boolean is frozen at creation — it does not age into adulthood inside the system; an aged-out holder requires an administrative refresh, but the system itself never re-evaluates `is_minor` after creation. When `is_minor` evaluates to true at create time, a `guardian_holder_id` must be supplied and must reference an existing `RightsHolder` that is either an `ORGANIZATION` or an `INDIVIDUAL` whose own `is_minor` is false; a missing or invalid guardian rejects creation with `ERR_MINOR_REQUIRES_GUARDIAN`.

Minor holders may earn royalties, but the payout layer refuses to route any payment to a minor's own `bank_account_token`. Payouts targeting a minor must be routed through the guardian's bank account; if a minor has no active guardian binding at payout time, the batch generation rejects with `ERR_MINOR_PAYOUT_BLOCKED`.

### 3.6. Playback Ingest, Validity, and Event Classification

A `PlaybackSource` reports activity through the playback batch ingest. Each batch declares its `channel` (one of `STREAMING`, `RADIO`, `TV`, `PUBLIC_VENUE`, `LIVE`), a stable `source_identifier` of 1 to 64 characters (such as `spotify-us` or `bbc-r2`), a 64-hex-character `source_signature` carrying the HMAC-SHA256 digest, the reporting window as a `reporting_period_start` (inclusive UTC) and `reporting_period_end` (exclusive UTC), a self-reported `total_events_submitted`, and the embedded `events` array.

The batch enters the system in `validity_status` of `PENDING` and is then classified into one of four terminal validity states. If the HMAC does not match, the batch transitions `PENDING` → `INVALID_SIGNATURE`, `total_events_accepted` is set to 0, and the response carries `ERR_PLAYBACK_SIGNATURE_INVALID`. If the signature is valid but the reporting window fails any of the three temporal checks — `reporting_period_end` at or before `reporting_period_start`, the window's duration exceeding 31 days, or `reporting_period_end` strictly in the future — the batch transitions `PENDING` → `INVALID_RANGE` and the response carries `ERR_PLAYBACK_RANGE_INVALID`. If signature and window are valid but a prior batch from the same `source_identifier` covering the same `[reporting_period_start, reporting_period_end)` window already exists with `validity_status` of `VALID`, the new batch transitions `PENDING` → `DEDUPED_REJECTED` and the response carries `ERR_DUPLICATE_BATCH`. Only when signature, range, and uniqueness all pass does the batch transition `PENDING` → `VALID`.

On the `VALID` transition, the platform processes each event in the embedded `events` payload. Each event carries a `playback_batch_id` (set by the platform), an optional `work_id`, optional `isrc` and `iswc` resolvers (at least one of which must be present when `work_id` is null), a UTC `played_at` timestamp, a `play_duration_seconds` integer strictly greater than zero and at most the referenced work's `duration_seconds`, an ISO 3166-1 alpha-2 `region` of two uppercase letters, a server-computed `dedup_key`, and a derived `status`. The `dedup_key` is the SHA-256 hex digest of the concatenation `(source_identifier|work_id|played_at_ms)`; an event whose `dedup_key` already exists for the same source within a 24-hour window is marked `DUPLICATE_DROPPED`. An event whose `work_id` is null but whose `isrc` or `iswc` uniquely resolves an `APPROVED` work has its `work_id` filled in and is marked `SUPPLEMENTED`. An event whose `work_id` cannot be resolved at all is marked `REJECTED`. All remaining events are marked `ACCEPTED`. The batch's `total_events_accepted` is then set to the count of events whose final status is `ACCEPTED` or `SUPPLEMENTED`. Per-event `PlaybackEvent` rows are leaner — they carry only `id` and `created_at`; neither `updated_at` nor `version` is exposed.

### 3.7. Distribution Rules and Their Versioning

`PlatformAdmin` publishes distribution rules as `DistributionRuleVersion` rows. Each version is identified by a unique 1-to-32-character `version_tag` such as `v2026.05`, a `channel` matching one of `{STREAMING, RADIO, TV, PUBLIC_VENUE, LIVE, SYNC, MECHANICAL_LICENSE}`, a `distribution_mode` of `PER_PLAY`, `PER_DURATION`, or `HYBRID`, a `per_play_weight` between 0.00 and 1.00 (required when the mode is `PER_PLAY` or `HYBRID`), a `per_duration_weight` between 0.00 and 1.00 (required when the mode is `PER_DURATION` or `HYBRID`), a `playback_type_weights` object mapping each of `FULL_PLAY`, `SKIP`, `BACKGROUND`, and `FOREGROUND` to a multiplier between 0.00 and 2.00, a `minimum_payout_cents` (a non-negative integer cents floor below which earnings accumulate instead of paying), a `micro_accumulation_cap_cents` (a non-negative integer at least equal to `minimum_payout_cents` beyond which accumulated micro-balance is force-paid), and an inclusive UTC `effective_from`. When the mode is `HYBRID`, the sum of `per_play_weight` and `per_duration_weight` must equal exactly 1.00, otherwise `ERR_RULE_WEIGHTS_INVALID` is returned. `DistributionRuleVersion` rows carry only `id` and `created_at` — they are versioned by `version_tag` and immutable once published.

### 3.8. Opening, Pricing, and Closing a Royalty Pool

A `FinanceOps` operator opens a `RoyaltyPool` by declaring the reporting window as `period_start` (inclusive UTC) and `period_end` (exclusive UTC), the `revenue_source` (matching one of the channels declared for distribution rules), a `region` (a two-letter country code or `WW` for worldwide aggregation), the `gross_revenue_cents` collected during the window, a `platform_share_percent` between 0.00 and 40.00 inclusive at two decimal places, a `pool_currency` from the five-currency set, a `mechanical_split_percent` between 0.00 and 100.00 inclusive that allocates the corresponding fraction of the net distributable to the mechanical sub-pool (the remainder flowing to performance), and an optional `distribution_rule_version_id` pinning the rule version that will be used at close. The pool is born in status `OPEN`. Before close, the operator may patch `gross_revenue_cents` or rebind `distribution_rule_version_id`; both are routine pre-close adjustments.

Closing the pool gates on three preconditions: the current server time must be at or after `period_end`; `distribution_rule_version_id` must be set and reference a `DistributionRuleVersion` whose `channel` equals the pool's `revenue_source`; and that rule version's `effective_from` must be at or before `period_end` (a stricter ordering is enforced by `ERR_RULE_NOT_EFFECTIVE` — the rule's `effective_from` must be strictly less than `period_end`). The pool's `status` flips to `CLOSED`, `closed_at` is stamped with the current time, and the platform computes the money chain.

The money chain begins with the platform-take deduction. The platform-take is the gross revenue multiplied by the platform's share, expressed as a fraction with two decimal places of precision, then rounded to whole cents using round half up. The net distributable is the gross revenue minus this rounded platform-take, evaluated as an integer subtraction (no further rounding). The rounding order is pinned: the platform-take is rounded **before** subtraction, so that the small remainder produced by the rounding step lodges with the net distributable rather than with the platform-take.

Next, a tiered admin fee is computed from the **gross revenue** (not from the net distributable; using the net would create a circular self-reference between the fee and tier detection). The tiers are half-open intervals on `gross_revenue_cents`: the first tier covers strictly less than 100,000.00 dollars-or-equivalent (10,000,000 cents) and charges 5% flat; the second tier covers the half-open interval from 10,000,000 cents up to but not including 100,000,000 cents (99,999,999 cents as the high water mark, where 1,000,000.00 dollars-or-equivalent is 100,000,000 cents) and charges 4% on the portion above the prior tier's cap; the third tier covers gross revenues at or above 100,000,000 cents and charges 3% on the portion above the prior tier's cap. The boundaries are half-open `[low, high)`, so a pool whose `gross_revenue_cents` is exactly 10,000,000 enters tier 2. The cumulative admin fee is computed by walking the tiers in order: each per-tier slice (the portion of gross revenue that falls within that tier's interval) is multiplied by the tier's rate, then **rounded to whole cents using round half up** before being added to the running sum. The round-then-sum ordering produces a slightly different result than sum-then-round at boundary inputs; the round-per-slice order is the canonical one.

After computing the admin fee, the platform recomputes the final `net_distributable_cents` as `gross_revenue_cents` minus the rounded platform-take minus the rounded admin fee, in that order, as a plain integer subtraction. This pinned three-step evaluation order — compute platform-take from gross, compute admin fee from gross, then subtract both from gross — avoids any cross-dependency between the two deductions.

The net distributable is then split into two sub-pools. The mechanical-take is the net distributable multiplied by the mechanical split percent (as a fraction with two decimal places of precision) and rounded to whole cents using round half up. The performance-take is the net distributable minus the rounded mechanical-take, evaluated as an integer subtraction. The mechanical-take is rounded **before** subtraction, so that the small remainder produced by the rounding step lodges with the performance-take, not the mechanical-take.

### 3.9. Distributing the Pools to Works and Shares

In the same close operation, the platform cascades distribution-row creation (cascade depth 2) and per-row gross computation (cascade depth 3). The eligibility filter selects every `PlaybackEvent` whose parent batch's `validity_status` is `VALID`, whose event-level `status` is `ACCEPTED` or `SUPPLEMENTED`, whose `region` matches the pool's `region` (the literal `WW` matches any region), whose `played_at` falls in the half-open `[period_start, period_end)` window, and whose `work_id` resolves to an `APPROVED` work whose source channel equals the pool's `revenue_source`. A frozen work is not excluded at this stage — frozen works still receive a `PENDING` distribution that is immediately flipped to `FROZEN` by the dispute-posture cascade described below.

For each eligible work, weighted play units are computed according to the pinned `DistributionRuleVersion.distribution_mode`. Under `PER_PLAY` mode, the work's units are the count of eligible events multiplied by the average of the playback-type weight assigned to each event. Under `PER_DURATION` mode, the work's units are the sum, across eligible events, of each event's `play_duration_seconds` multiplied by that event's playback-type weight. Under `HYBRID` mode, the work's units are the sum of two terms: the `per_play_weight` multiplied by the count of events weighted by their playback-type weight, plus the `per_duration_weight` multiplied by the sum of duration-times-type-weight across events. Each event's playback-type weight is drawn from the rule's `playback_type_weights` map after classifying the event into one of four types: `FULL_PLAY` when `play_duration_seconds` is at least 95% of the work's `duration_seconds`, `SKIP` when it is strictly less than 30% of `duration_seconds`, `BACKGROUND` for events explicitly tagged as background activity, and `FOREGROUND` for the remainder.

A work's sub-pool target is the mechanical-take when its `rights_type` is `COMPOSITION` or `LYRICS`, otherwise the performance-take (when `rights_type` is `RECORDING` or `PERFORMANCE`). Within the sub-pool, the per-work cents allocation is the sub-pool's total cents multiplied by the work's fraction of total units in that sub-pool (the work's units divided by the sum of units across every work in the sub-pool), then rounded to whole cents using round half up. The rounding is performed **per work first**, then the residual cents — the difference between the sub-pool total and the sum of rounded per-work allocations — is lodged with the work whose units count is highest in the sub-pool, with ties broken in favour of the lexicographically lowest `Work.id`.

For each work, the per-share allocation distributes the work's cents to its active `RightsShare` rows. Each share receives the work's per-work cents multiplied by `share_percent` divided by 100, rounded to whole cents using round half up. The rounding is performed **per share first**, then the residual cents — the difference between the work's per-work cents and the sum of rounded per-share allocations — is lodged with the share whose `share_percent` is highest, with ties broken in favour of the lexicographically lowest `RightsShare.id`. Each `Distribution` row carries `royalty_pool_id`, `work_id`, `rights_holder_id`, `rights_share_id`, a derived `sub_pool` of `MECHANICAL` or `PERFORMANCE` matching the work's category, the computed `gross_amount_cents`, and an initial `status` of `PENDING`.

Agency commission is then applied per row. When the share's `agency_binding_id` is set and the binding's `status` is `ACTIVE` and the current time lies within the binding's `[effective_from, effective_until)` window, the `commission_cents` is the `gross_amount_cents` multiplied by the binding's `commission_percent` divided by 100, rounded to whole cents using round half up; otherwise `commission_cents` is zero. The `net_after_commission_cents` is the `gross_amount_cents` minus the `commission_cents`, as a plain integer subtraction.

If at close time any eligible work has `dispute_posture` equal to `FROZEN`, the freshly-created `PENDING` distributions for that work immediately cascade to `FROZEN` — the freeze cascade is the same machinery as the dispute-driven freeze described below, applied here to handle dispute-while-pool-was-open.

### 3.10. Finalising the Pool

Once distributions exist, `FinanceOps` finalises the pool, advancing its `status` from `CLOSED` to `DISTRIBUTED`. The single precondition is that no `Distribution` under the pool may carry `status` of `FROZEN`; an attempt to finalise with even one frozen distribution is rejected with `ERR_POOL_HAS_FROZEN_DISTRIBUTIONS`. On success, every `PENDING` distribution in the pool flips to `RELEASED` (the system-event transition); `FROZEN` distributions are not touched by the finalise step because they remain hostage to dispute resolution. `DISTRIBUTED` is the pool's terminal state.

### 3.11. Disputes, Freezing, and Resolution

A `RightsHolder` opens a dispute on a work by declaring a `work_id`, a `dispute_kind` from the set `{SHARE_RATIO, OWNERSHIP, ORIGINALITY, AGENCY_AUTHORITY}`, and a free-text `claim_summary` of 1 to 2000 characters. The newly-created dispute lives in status `OPEN` with an empty `evidence_items` list, a null `arbitration_decision`, and a null `arbitrator_id`. The platform records the opening dispute, and the cascade fires: the work's `dispute_posture` is recomputed and, because at least one open dispute now exists, flips from `CLEAR` to `FROZEN`; the work's `version` is bumped and `updated_at` is refreshed; and every `PENDING` distribution on this work flips to `FROZEN` (cascade depth 2). Any subsequent attempt to terminate a share on this work via holder-initiated mutation is rejected with `ERR_WORK_FROZEN`, and any adoption-style operation that depends on a stable share roster is similarly blocked.

Parties may attach evidence to an `OPEN` or in-progress dispute. Each evidence submission appends an entry to `evidence_items` carrying `submitter_role`, `submitter_id`, the evidence `url`, and a `submitted_at` timestamp; the list is append-only. The submitter may be either a `RightsHolder` or a `DisputeOfficer` collecting evidence on behalf of an external party.

A `DisputeOfficer` advances the dispute through investigation. From `OPEN`, the officer starts the investigation, flipping `status` to `UNDER_INVESTIGATION`. From `UNDER_INVESTIGATION`, the officer may advance to `MEDIATION` once `evidence_items` contains at least two entries — the platform requires at least two parties to have submitted evidence before mediation. Within mediation, the officer may either advance forward to `ARBITRATION`, or reopen the investigation by flipping the status back to `UNDER_INVESTIGATION` (the cyclic loop allows further evidence collection). From `ARBITRATION`, the officer issues a resolution: the request body carries an `outcome` of either `UPHELD` or `DISMISSED` and a free-text `arbitration_decision`; a malformed body lacking either of these is rejected with `ERR_RESOLUTION_INVALID`. On a successful resolution, the dispute's `status` becomes either `RESOLVED_UPHELD` or `RESOLVED_DISMISSED` according to the supplied outcome, `arbitrator_id` is stamped with the officer's `X-User-ID`, and the work's `dispute_posture` is recomputed (cascade depth 1) — if no other open dispute remains on this work, posture flips to `CLEAR` (cascade depth 2) and every `FROZEN` distribution on this work flips to `RELEASED` (cascade depth 3). When the resolution is an `UPHELD` `SHARE_RATIO` dispute and the body contains `new_share_percentages`, every affected `RightsShare` is updated to the supplied percentages and a `ShareChangeAudit` row is written for each update with `change_kind` of `PERCENT_UPDATED`.

A claimant may withdraw their own `OPEN` dispute, transitioning it to `WITHDRAWN`. The cascade is the same as a resolution: the work's `dispute_posture` is recomputed; if no other open dispute remains, posture flips to `CLEAR` and every `FROZEN` distribution on this work flips to `RELEASED`. Withdrawal is gated on the caller's `X-User-ID` matching the dispute's `claimant_rights_holder_id`.

The system also exposes a holder-level dispute-exposure score on demand. Two variants are available: the default `forward_looking` variant aggregates a 0.6-weighted count of currently-open disputes touching the holder (either as claimant or as a share-bearer on a disputed work) plus a 0.4-weighted contribution from the ratio of frozen distribution cents over total lifetime paid cents, where the ratio is multiplied by 100 and then rounded up to a whole number using ceiling; the score is then rounded to a whole integer using round half up. The frozen-exposure ratio's denominator is the larger of 1 and the holder's total lifetime paid cents, to avoid division by zero for never-paid holders. The alternative `chronological` variant replays each dispute event in `created_at` order, decaying the contribution of each earlier dispute by 0.9 per subsequent dispute (so the oldest dispute contributes the deepest discount), then sums the decayed contributions. Identical inputs produce strictly different numbers under the two variants except when there is exactly one dispute on the holder.

### 3.12. Generating and Aggregating Payouts

A `FinanceOps` operator generates a `PayoutBatch` by supplying a unique `cycle_tag` of 1 to 32 characters (such as `2026-Q2-W2`) and a `scheduled_run_at` UTC moment after which the batch becomes eligible for execution. A duplicate `cycle_tag` is rejected with `ERR_DUPLICATE_CYCLE`. The newly-created batch lives in status `PENDING` with `total_payments` of 0 and `total_paid_cents_by_currency` as an empty map.

On generation, the platform computes a `Payment` candidate for each `(rights_holder_id, currency)` pair drawn from the universe of `RELEASED` `Distribution` rows whose parent `RoyaltyPool` has `status` of `DISTRIBUTED`. The candidate distribution set for a holder-currency pair is those `Distribution` rows whose `status` is `RELEASED`, whose `rights_holder_id` equals the holder's `id`, and whose pool currency equals the holder's `payout_currency` (mismatched currencies are excluded and routed to a separate currency-mismatch queue rather than included with a conversion). The base amount for the candidate is the sum of `net_after_commission_cents` across the candidate distributions. The drained micro-amount is the existing `MicroBalance.balance_cents` for this `(rights_holder_id, currency)`, where `MicroBalance` carries `rights_holder_id`, `currency`, and a non-negative integer `balance_cents`. The candidate `gross_cents` is the base amount plus the drained micro-amount.

The decision branch runs in **pinned evaluation order**: the micro-accumulation cap check runs **first**, the minimum-payout threshold check runs **second**. Reversing the order would create rows that should have been paid. Concretely:

- If the candidate gross is strictly less than the rule's `minimum_payout_cents`, the platform checks whether `drained_micro` plus the base amount strictly exceeds `micro_accumulation_cap_cents`. If yes (the cap is exceeded), a forced payout fires: a `Payment` row is created with `gross_cents` equal to the candidate gross, the holder's `MicroBalance` for this currency is drained to 0, and the candidate distributions are marked toward `PAID` upon PSP success. If no (the cap is not exceeded), no `Payment` row is created; instead, `MicroBalance.balance_cents` is incremented by the base amount and the candidate distributions are marked as `PAID` immediately (their cents are consumed into the micro-balance).
- If the candidate gross is at or above `minimum_payout_cents`, a `Payment` row is created with `gross_cents` equal to the candidate gross, the holder's `MicroBalance` for this currency is drained to 0, and the candidate distributions are marked toward `PAID` upon PSP success.

Any attempt to create a `Payment` whose `gross_cents` is strictly less than `minimum_payout_cents` and whose micro-cap has not been exceeded is rejected with `ERR_BELOW_MIN_PAYOUT`.

For every created `Payment`, the platform computes `tax_withheld_cents` as the `gross_cents` multiplied by the holder's jurisdiction tax rate (drawn from the per-country table in §2.6), rounded to whole cents using round half up. The `net_payable_cents` is `gross_cents` minus `tax_withheld_cents`, as an integer subtraction. The `routing_channel` is selected from the set `{SWIFT, SEPA, ACH, LOCAL_JP, LOCAL_CN}` per the holder's currency and bank-token routing rules.

Minor holders cannot route to their own `bank_account_token`; the payment's effective routing must use the guardian's bank token. A minor without an active guardian binding at the moment of batch generation rejects the entire batch with `ERR_MINOR_PAYOUT_BLOCKED`.

### 3.13. Executing the Batch and Reconciling with the PSP

Once the batch is `PENDING` and the current time is at or after its `scheduled_run_at`, a `FinanceOps` operator executes the batch. The batch's `status` flips from `PENDING` to `RUNNING`, every `Payment` in the batch flips from `QUEUED` to `SENT`, and one `ExternalSyncEvent` row is created per payment with `event_kind` of `PAYMENT_INITIATED`, `target_system` of `PAYMENT_PSP`, `related_entity_kind` of `Payment`, and `related_entity_id` set to the payment's `id`; a `payload` mirrors the outbound request to the external payment processor. `ExternalSyncEvent` rows carry only `id` and `created_at` and are append-only.

The external PSP eventually calls back with a per-payment outcome. The platform exposes a test-driving facility that receives the callback with a `payment_id`, an `outcome` of `SUCCESS` or `FAILURE`, and an optional `reason` (used to populate `last_failure_reason` on failure). On `SUCCESS`, the payment flips from `SENT` to `SUCCEEDED`; every `Distribution` associated with this payment cascades from `RELEASED` to `PAID` (cascade depth 2); and the holder's `MicroBalance` for this currency, having been drained at batch generation, remains at 0 — the platform records the drained cents as `drained_micro_balance_cents` at the moment of batch generation so the reset is deterministic. On `FAILURE`, the payment flips from `SENT` to `FAILED` and `last_failure_reason` is stamped from the callback body.

A `FAILED` payment may be retried up to three times. The retry operation transitions the payment from `FAILED` to `RETRYING` and increments `retry_count` by one; the precondition is `retry_count` strictly less than 3. A background retry executor picks up `RETRYING` payments and transitions them back to `SENT` for the next attempt. Once `retry_count` reaches 3 and the payment is still `FAILED`, the operator may abandon it: the payment flips from `FAILED` to `ABANDONED`, and the underlying `Distribution` rows are either reverted from `RELEASED` to `FORFEITED` or returned to `MicroBalance` according to the supplied `policy` in the abandon body. The two terminal payment states are `SUCCEEDED` and `ABANDONED`.

### 3.14. Forfeitures, Sweeps, and Test-Driving

A `PlatformAdmin` may forfeit a `RELEASED` `Distribution` whose holding rights-holder is in a state where payment is permanently impossible. Forfeiture is gated: the holding holder must have a payment whose `status` is `FAILED` or `ABANDONED`, or their `bank_account_token` must be revoked; otherwise `ERR_DISTRIBUTION_NOT_FORFEITABLE` is returned. On success, the distribution's `status` flips to `FORFEITED` and its `gross_amount_cents` is reabsorbed into the parent pool's `net_distributable_cents` (the reabsorption mechanic ensures forfeit cents do not vanish from the ledger).

For test-driving and operational maintenance, the platform exposes three admin-only capabilities. A clock-advance capability moves the server's logical clock to a supplied UTC moment `to`; the clock drives all time comparisons (window checks, binding effectivity, scheduled-run gates, micro-accumulation aging) but does not by itself trigger any state machine. A sweep capability runs the retry executor and the dispute-posture recomputation across all approved works; it is idempotent and returns the counts of swept payments and swept works. A PSP-callback capability — used to drive the payment lifecycle in tests — receives an external callback describing a payment outcome and advances the corresponding payment as described above.

External sync events are recorded for every payment initiated, every payment success or failure relayed back, every bank reconciliation event, and every CMO share push or revenue pull. The `target_system` field labels which downstream system the event is mirrored to or received from: `PAYMENT_PSP` for payment processor traffic, `BANK` for bank reconciliation, and `CMO_GATEWAY` for collective-management-organisation integration. The `event_kind` enumerates the canonical event types: `PAYMENT_INITIATED`, `PAYMENT_SUCCEEDED`, `PAYMENT_FAILED`, `BANK_RECONCILIATION`, `CMO_SHARE_PUSH`, and `CMO_REVENUE_PULL`. The `related_entity_kind` is one of `Payment`, `PayoutBatch`, `RightsShare`, or `RoyaltyPool`, and `related_entity_id` carries the referenced entity's `id`. The free-form `payload` object mirrors the wire data.

### 3.15. Reading State

Read endpoints return the resource shape declared by the entity definitions in §2.4 (the common-fields four-tuple where applicable, plus the entity's domain fields). Lists are paginated under the rules of §2.3 and accept the filters declared per endpoint in §4 — for instance, the works list accepts `registration_status`, `dispute_posture`, and `rights_type` filters; the rights-holders list accepts `holder_kind`, `is_minor`, and `tax_jurisdiction`; the playback-batches' events list accepts a `status` filter over the event lifecycle; the pools' distributions list accepts `status`, `work_id`, and `rights_holder_id`; the payout-batches' payments list accepts `status`; the external-sync list accepts `target_system`, `event_kind`, and `related_entity_id`. The per-holder micro-balance read returns a list of `MicroBalance` rows (one per currency) for that holder. The per-holder dispute-exposure read returns an object `{ score, mode }` carrying the computed integer score and the variant label (`forward_looking` or `chronological`) selected via the `mode` query parameter.

## 4. Endpoint Definitions

Endpoints follow REST conventions over the standard envelope of §2.2. Resource-creation endpoints return HTTP 201; modifying actions (state transitions, patches, lifecycle operations) return HTTP 200; read endpoints return HTTP 200. Every endpoint lives under the system mount `/royalty`. Pagination on list endpoints follows §2.3 (`limit`, `offset` query parameters). OCC-bearing mutations accept an optional `version` in the request body as described in §2.4. Request bodies, response bodies, and side effects are derived from the §3 narrative for each operation.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/royalty/rights-holders` | Create a rights-holder (individual or organisation). Minors require guardian binding. | `PlatformAdmin` |
| GET | `/royalty/rights-holders/{id}` | Read a rights-holder. | `PlatformAdmin`, `RightsHolder`, `FinanceOps`, `RegistrationReviewer`, `DisputeOfficer` |
| GET | `/royalty/rights-holders` | List rights-holders. | `PlatformAdmin`, `FinanceOps` |
| GET | `/royalty/rights-holders/{id}/dispute-exposure` | Compute dispute exposure score for a holder. Supports `?mode=forward_looking` (default) or `?mode=chronological`. | `PlatformAdmin`, `FinanceOps` |
| POST | `/royalty/agency-bindings` | Create an agency binding for a rights-holder. | `PlatformAdmin`, `RightsHolder` |
| POST | `/royalty/agency-bindings/{id}/terminate` | Terminate an active agency binding. | `PlatformAdmin`, `RightsHolder` |
| POST | `/royalty/works` | Register a new work in `DRAFT`. | `RightsHolder` |
| GET | `/royalty/works/{id}` | Read a work. | `PlatformAdmin`, `RightsHolder`, `RegistrationReviewer`, `DisputeOfficer`, `FinanceOps` |
| GET | `/royalty/works` | List works with filters. | `PlatformAdmin`, `RegistrationReviewer`, `FinanceOps` |
| POST | `/royalty/works/{id}/submit` | Submit a `DRAFT` work for review. | `RightsHolder` |
| POST | `/royalty/works/{id}/take-review` | Reviewer takes a `SUBMITTED` work into `UNDER_REVIEW`. | `RegistrationReviewer` |
| POST | `/royalty/works/{id}/approve` | Approve an `UNDER_REVIEW` work. | `RegistrationReviewer` |
| POST | `/royalty/works/{id}/reject` | Reject an `UNDER_REVIEW` work. | `RegistrationReviewer` |
| POST | `/royalty/works/{id}/withdraw` | Owner withdraws a `DRAFT` work. | `RightsHolder` |
| POST | `/royalty/works/{id}/return-to-draft` | Return a `SUBMITTED` work to `DRAFT` for amendment (revision loop). | `RegistrationReviewer` |
| POST | `/royalty/works/{id}/shares` | Add a `RightsShare` to a work. | `RightsHolder`, `PlatformAdmin` |
| PATCH | `/royalty/works/{id}/shares/{share_id}` | Update a `RightsShare` (percent, agency binding, or terminate). | `RightsHolder`, `PlatformAdmin` |
| GET | `/royalty/works/{id}/shares/{share_id}/audit` | Read the share-change audit history for a share. | `PlatformAdmin`, `RightsHolder`, `DisputeOfficer` |
| POST | `/royalty/playback-batches` | Ingest a playback batch. Validates HMAC signature, range, dedup; classifies and supplements events. | `PlaybackSource` |
| GET | `/royalty/playback-batches/{id}` | Read a playback batch with its validity status. | `PlatformAdmin`, `FinanceOps`, `PlaybackSource` |
| GET | `/royalty/playback-batches/{id}/events` | List events in a batch with their per-event status. | `PlatformAdmin`, `FinanceOps` |
| POST | `/royalty/distribution-rules` | Create a new `DistributionRuleVersion`. | `PlatformAdmin` |
| GET | `/royalty/distribution-rules` | List distribution rule versions. | `PlatformAdmin`, `FinanceOps` |
| POST | `/royalty/pools` | Open a royalty pool for a period × revenue source × region. | `FinanceOps` |
| PATCH | `/royalty/pools/{id}` | Patch a pool's `distribution_rule_version_id` or `gross_revenue_cents` before close. | `FinanceOps` |
| POST | `/royalty/pools/{id}/close` | Close an `OPEN` pool. Computes `net_distributable_cents`, admin tier fee, creates `Distribution` rows. | `FinanceOps` |
| POST | `/royalty/pools/{id}/finalize` | Finalize a `CLOSED` pool: flip all `PENDING` distributions to `RELEASED`. | `FinanceOps` |
| GET | `/royalty/pools/{id}` | Read a pool. | `PlatformAdmin`, `FinanceOps` |
| GET | `/royalty/pools/{id}/distributions` | List distributions under a pool. | `PlatformAdmin`, `FinanceOps`, `RightsHolder` |
| POST | `/royalty/distributions/{id}/forfeit` | Forfeit a `RELEASED` distribution that cannot be paid; cents reabsorb into pool. | `PlatformAdmin` |
| POST | `/royalty/disputes` | Open a dispute on a work. | `RightsHolder` |
| POST | `/royalty/disputes/{id}/submit-evidence` | Submit an evidence item (URL) on a dispute. | `RightsHolder`, `DisputeOfficer` |
| POST | `/royalty/disputes/{id}/start-investigation` | Move dispute `OPEN` → `UNDER_INVESTIGATION`. | `DisputeOfficer` |
| POST | `/royalty/disputes/{id}/advance-to-mediation` | Move dispute `UNDER_INVESTIGATION` → `MEDIATION`. | `DisputeOfficer` |
| POST | `/royalty/disputes/{id}/reopen-investigation` | Move dispute `MEDIATION` → `UNDER_INVESTIGATION` (cyclic loop). | `DisputeOfficer` |
| POST | `/royalty/disputes/{id}/advance-to-arbitration` | Move dispute `MEDIATION` → `ARBITRATION`. | `DisputeOfficer` |
| POST | `/royalty/disputes/{id}/resolve` | Resolve a dispute (`UPHELD` or `DISMISSED`). | `DisputeOfficer` |
| POST | `/royalty/disputes/{id}/withdraw` | Claimant withdraws an `OPEN` dispute. | `RightsHolder` |
| POST | `/royalty/payout-batches` | Generate a `PayoutBatch` with payments aggregated from `RELEASED` distributions and drained micro-balance. | `FinanceOps` |
| POST | `/royalty/payout-batches/{id}/execute` | Execute a `PENDING` batch (after `scheduled_run_at`). Marks payments `SENT` and emits `ExternalSyncEvent` rows. | `FinanceOps` |
| GET | `/royalty/payout-batches/{id}` | Read a payout batch. | `PlatformAdmin`, `FinanceOps` |
| GET | `/royalty/payout-batches/{id}/payments` | List payments in a batch. | `PlatformAdmin`, `FinanceOps` |
| POST | `/royalty/payments/{id}/retry` | Retry a `FAILED` payment. | `FinanceOps` |
| POST | `/royalty/payments/{id}/abandon` | Abandon a `FAILED` payment after retries exhausted. | `FinanceOps` |
| POST | `/royalty/_events/psp-callback` | Test-driving endpoint: receive an external PSP callback to advance payment state. | `PlatformAdmin` |
| GET | `/royalty/_events/external-sync` | List `ExternalSyncEvent` rows for verification. | `PlatformAdmin` |
| POST | `/royalty/_clock/advance` | Test-driving endpoint: advance the server logical clock to a UTC moment. | `PlatformAdmin` |
| POST | `/royalty/_sweep/run` | Test-driving endpoint: run the retry executor and the dispute-posture recomputation sweep. | `PlatformAdmin` |
| GET | `/royalty/rights-holders/{id}/micro-balance` | Read a holder's per-currency `MicroBalance`. | `PlatformAdmin`, `RightsHolder`, `FinanceOps` |

## 5. Error Code Catalogue

Every error response uses the envelope defined in §2.2. The trigger conditions for each error are scattered through the validation order in §2.10 and the workflow narrative in §3 — this catalogue lists only the identifier and HTTP status pair.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_AUTH_REQUIRED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_WORK_FROZEN` | 409 |
| `ERR_POOL_HAS_FROZEN_DISTRIBUTIONS` | 409 |
| `ERR_DISTRIBUTION_NOT_FORFEITABLE` | 409 |
| `ERR_MINOR_REQUIRES_GUARDIAN` | 422 |
| `ERR_MINOR_PAYOUT_BLOCKED` | 422 |
| `ERR_PLAYBACK_SIGNATURE_INVALID` | 403 |
| `ERR_PLAYBACK_RANGE_INVALID` | 422 |
| `ERR_DUPLICATE_BATCH` | 409 |
| `ERR_DUPLICATE_IDENTIFIER` | 409 |
| `ERR_COCREATOR_SUM_INVALID` | 422 |
| `ERR_SHARE_SUM_INVALID` | 422 |
| `ERR_AGENCY_BINDING_INAPPLICABLE` | 422 |
| `ERR_AGENCY_BINDING_OVERLAP` | 409 |
| `ERR_RULE_WEIGHTS_INVALID` | 422 |
| `ERR_RULE_NOT_EFFECTIVE` | 422 |
| `ERR_BELOW_MIN_PAYOUT` | 422 |
| `ERR_DUPLICATE_CYCLE` | 409 |
| `ERR_RESOLUTION_INVALID` | 422 |
