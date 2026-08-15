# Photo Desk & Image Rights Management API — Product Requirements Document

## 1. Introduction

A news organization's photo desk sits at the intersection of editorial urgency and rights-management discipline. Editors must decide, for every story, whether to commission original photography or source from wire and stock archives; rights managers must ensure that every published image is properly licensed, credited, released for the people and property it depicts, and not embroiled in unresolved infringement disputes; and finance must pay photographers accurately under two very different compensation models — a guaranteed day rate for staffers and a per-use royalty for freelancers — while clawing back earnings when a claim is upheld.

This document specifies the Photo Desk & Image Rights Management API. It governs the full lifecycle from story art request through sourcing decision, assignment fulfillment, image clearance, licensing, publication, claim resolution, and payment. The system enforces editorial metadata standards, embargo windows, exclusivity constraints, rights reversion, segregation of duties between claim intake and claim resolution, and optimistic concurrency on operations that silently supersede prior state.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, boilerplate, and cross-cutting principles that apply to every endpoint.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers: `X-User-ID` identifies the acting user, and `X-User-Role` identifies their operational capacity. The system recognizes six roles, spelled exactly as follows: `PhotoEditor`, `Photographer`, `RightsManager`, `Archivist`, `FinanceAdmin`, and `PlatformAdmin`.

Missing or invalid headers — either header absent, or a role value that is not one of the six declared roles — are rejected with `ERR_UNAUTHENTICATED` (HTTP 401). An authenticated caller attempting an operation outside their role's permission set is rejected with `ERR_FORBIDDEN` (HTTP 403).

Role identity semantics:

- When `X-User-Role` is `Photographer`, `X-User-ID` is the `id` of the acting `Photographer` record. Ownership checks on any resource that references a `Photographer` — an `Assignment`'s `photographer_id`, an `Image`'s `photographer_id`, a `PaymentRun`'s `photographer_id` — compare that field to `X-User-ID`. A photographer may submit images only to assignments they own, submit only their own assignments for review, and read only their own payment runs; attempts against another photographer's resources are rejected with `ERR_FORBIDDEN`.
- When `X-User-Role` is `PhotoEditor`, `RightsManager`, `Archivist`, `FinanceAdmin`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow requires an audit stamp — for example, `intaken_by_user_id` and `resolved_by_user_id` on an `InfringementClaim` — but does not compare it against any entity's `id` for ownership.

One additional access rule: the archive search's `include_archived` flag may be set to `true` only by `Archivist` and `RightsManager`; any other role passing `include_archived=true` is rejected with `ERR_FORBIDDEN`. The flag counts as true only when the query value is the string `true` in any letter case; any other value (including `1` or `yes`) is treated as false.

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

List endpoints paginate via the `limit` and `offset` query parameters. `limit` is the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` is the number of items skipped and defaults to 0. Out-of-range values are clamped to the nearest bound rather than rejected (a `limit` above 100 becomes 100, below 1 becomes 1; a negative `offset` becomes 0); a non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`.

All list endpoints return resources sorted by `created_at` in ascending order unless otherwise specified.

Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope. `total_count` is the number of items matching the request's filters before pagination, and `has_more` is true exactly when `offset + limit` is less than `total_count`.

### 2.4. Logical Clock and Time Semantics

The system does not use wall-clock time. A logical clock, initialized to exactly `2026-08-01T00:00:00Z` at server startup, supplies the current instant for every time-dependent evaluation: embargo checks, license expiry, release expiry, rights reversion, and payment-period filtering. A `PlatformAdmin` may advance the logical clock by supplying a `to_iso8601` instant; the capability exists for testing and operational simulation and returns the new `current_utc`. The supplied instant is accepted without any monotonicity check, so the clock may also be set to an earlier instant.

Two lazy-derivation rules depend on the logical clock and are recomputed on every read and evaluation rather than stored as transitions:

- A `License` in `ACTIVE` status whose `valid_to` is at or before the logical now reads as `EXPIRED`. When this lazy expiry is observed, the license's `fee_cents` is released from its story's `committed_cents` if it charges one.
- A `ReleaseRecord` in `ACTIVE` status whose `expires_at` is non-null and at or before the logical now reads as `EXPIRED`. A null `expires_at` means the release is perpetual.

Once either lazy expiry is observed, the resulting `EXPIRED` status is latched: the record is mutated with the usual `updated_at` refresh and `version` increment, so moving the logical clock backward afterward does not resurrect an expired license or release, and a budget released by a lapsed license is not re-committed.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` — a server-generated UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` — an ISO 8601 UTC timestamp refreshed on every mutation.
- `version` — an integer starting at 1 on creation and incrementing by exactly 1 on every mutation of the resource, including mutations driven by cascade side effects from operations on other resources.

The `UsageRun` resource is the single exception: it is an immutable ledger entry carrying `id` and `created_at` only. It has no `updated_at` and no `version` field.

### 2.6. Monetary Values, Integer Cents, and Rounding

All monetary quantities are represented as integer cents. Every monetary calculation — license fee quotes, payout totals, kill fees, settlement splits, per-use royalty lines — rounds half-up to integer cents, and rounding is applied exactly once at the final step of each formula unless a calculation explicitly pins a different rounding point. Where a per-line royalty is summed into a total, each line is rounded half-up to integer cents first and the rounded lines are then summed; the system never sums raw values and then rounds.

### 2.7. Optimistic Concurrency Control

Two write operations mutate state silently as a side effect — creating a license can supersede and revoke an existing `ACTIVE` license, and creating a payment run can auto-void an overlapping `DRAFT` run. Because a writer holding a stale view of the parent resource would revoke or void state it never observed, both endpoints require explicit optimistic concurrency:

- Creating a license against an image accepts `expected_image_version` in the request body, carrying the image's `version` as the client last observed it. When the field is supplied and the image's current `version` has advanced beyond it — for any reason, including another license's supersession cascade — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). When the field is omitted, no concurrency check is performed and the create proceeds.
- Creating a payment run against a photographer accepts `expected_photographer_version` in the request body, carrying the photographer's `version` as the client last observed it. When the field is supplied and the photographer's current `version` has advanced beyond it — for example, by a claim clawback debit or a prior payment-run creation — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). When the field is omitted, no concurrency check is performed and the create proceeds.

Endpoints not listed above do not take a version field.

### 2.8. Validation Priority Ordering

When a request would trip multiple rules, the system reports violations in a fixed priority order so callers see the most fundamental problem first. Evaluated in order:

1. Authentication — headers present and role declared; else `ERR_UNAUTHENTICATED`.
2. Authorization and ownership — role permitted for the endpoint, entity-backed ownership for `Photographer`, `include_archived` restricted to `Archivist`/`RightsManager`; else `ERR_FORBIDDEN`.
3. Request shape — required fields, types, enum ranges, and conditional requirements; else `ERR_INVALID_REQUEST`.
4. Resource existence — path parameters and body-referenced foreign keys resolve to existing resources, validated left-to-right, each surfacing its resource-specific not-found code (`ERR_PHOTOGRAPHER_NOT_FOUND`, `ERR_STORY_REQUEST_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_IMAGE_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`, `ERR_RELEASE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_PAYMENT_RUN_NOT_FOUND`). One exception: the optional `story_request_id` on license creation is not resolved (§3.5).
5. State-machine from-state preconditions for action endpoints; terminal states reject all further transitions; else `ERR_INVALID_STATE`.
6. Image editorial gate — license creation, usage-run creation, and a `WIRE_STOCK` sourcing decision all require the image to be in `CLEARED`, `PUBLISHED`, or `ARCHIVED`; else `ERR_IMAGE_NOT_CLEARED`.
7. Story request must be `OPEN` to decide; else `ERR_STORY_ALREADY_DECIDED`.
8. Release gate; else `ERR_RELEASE_REQUIRED`.
9. Segregation of duties on claim resolution; else `ERR_SEGREGATION_OF_DUTIES`.
10. Exclusivity overlap on license activation; else `ERR_EXCLUSIVE_LICENSE_CONFLICT`.
11. Photographer double-booking on a `COMMISSION` decision; else `ERR_PHOTOGRAPHER_DOUBLE_BOOKED`.
12. Commissioned photographer must be `ACTIVE`; else `ERR_PHOTOGRAPHER_SUSPENDED`.
13. Assignment image-count ceiling; else `ERR_IMAGE_LIMIT_EXCEEDED`.
14. Caption/credit metadata standard on clear; else `ERR_INCOMPLETE_METADATA`.
15. Embargo on usage-run publication; else `ERR_EMBARGO_ACTIVE`.
16. License validity window on usage-run publication; else `ERR_LICENSE_WINDOW_VIOLATION`.
17. Rights-reversion gate on new licenses for reverted assignment images; else `ERR_RIGHTS_REVERTED`.
18. Restriction gate — no open claim on the image; else `ERR_IMAGE_UNDER_CLAIM`.
19. License-to-image referential match on usage runs; else `ERR_LICENSE_IMAGE_MISMATCH`.
20. Channel-to-scope match on usage runs; else `ERR_SCOPE_NOT_LICENSED`.
21. License must be `ACTIVE` to authorize a usage run; else `ERR_LICENSE_NOT_ACTIVE`.
22. Minimum-image floor on assignment submission; else `ERR_MIN_IMAGES_NOT_MET`.
23. Payment period lock; else `ERR_PAYMENT_PERIOD_LOCKED`.
24. Story budget ceiling on license activation; else `ERR_BUDGET_EXCEEDED`.
25. Optimistic concurrency; else `ERR_STALE_VERSION`.

Within a single endpoint, these priorities resolve ties: for example, on license activation the release gate surfaces before the exclusivity conflict, which surfaces before the budget check; on a usage-run creation, embargo, window, restriction, referential, scope, and license-active checks are reported in that relative order after the editorial gate.

Three endpoint-specific refinements pin where the global order cannot be applied literally. First, entity-backed `Photographer` ownership (priority 2) is evaluated as soon as the owning reference is available: on photographer-rooted paths (`/photographers/{id}` and its sub-paths) the path id itself is compared to `X-User-ID` before any record is loaded, so an ownership failure surfaces ahead of not-found; on assignment-scoped endpoints the assignment must be loaded to learn its owner, so `ERR_ASSIGNMENT_NOT_FOUND` surfaces ahead of ownership, and on image submission the payload shape (caption and credit line) is validated before the assignment is even loaded. Second, on the sourcing-decision endpoint the story request's `OPEN` check fires immediately after the story request itself resolves — ahead of branch-payload shape validation and the branch's foreign-key lookups — so a story already decided always yields `ERR_STORY_ALREADY_DECIDED` regardless of branch-payload defects. Third, on claim resolution the state check and the segregation-of-duties check fire before the `UPHELD`-specific `settlement_amount_cents` validation, so a same-user resolve attempt yields `ERR_SEGREGATION_OF_DUTIES` even when the settlement amount is missing or invalid.

### 2.9. Cascading Side Effects and Cross-Aggregate Consistency

Several single operations mutate more than one resource. Where this document describes a cascade, every hop is part of the same atomic operation: the operation either applies all of its cascades or none. Cascade hops that touch another resource mutate it, refresh its `updated_at`, and increment its `version` — a rule with concrete consequences for the optimistic-concurrency checks above, since a claim resolution that debits a photographer advances that photographer's `version` and invalidates any stale `expected_photographer_version` a finance client may be holding.

## 3. Business Logic & Workflows

### 3.1. Photographer Roster and Standing

The photo desk maintains a roster of `Photographer` records. A `PhotoEditor` onboards a photographer by supplying `full_name`, `email`, `photographer_type`, `day_rate_cents`, `per_image_fee_cents`, and `royalty_rate_per_use_cents`; `rights_reversion_months` is optional and defaults to 24 calendar months, with an explicit null also falling back to the default. The `email` is stored as supplied; the system does not enforce its uniqueness across the roster. The `photographer_type` is either `STAFF` or `FREELANCE` and selects the payout variant used at payment time — `STAFF` maps to the `GUARANTEE` method and `FREELANCE` maps to the `ROYALTY` method.

Every photographer carries two lifetime ledgers. `accrued_earnings_cents` accumulates per-image clearance fees and usage royalties and is debited by claim clawbacks, never falling below zero on any single decrement. `paid_out_cents` accumulates the `total_cents` of payment runs as they reach `PAID`, and is debited back when a `PAID` run is voided. Both start at zero.

A photographer's `status` begins at `ACTIVE`. A `PhotoEditor` may suspend a photographer — moving `ACTIVE` to `SUSPENDED` — and later reactivate them back to `ACTIVE`. A `SUSPENDED` photographer cannot be commissioned: a sourcing decision naming a suspended photographer is rejected with `ERR_PHOTOGRAPHER_SUSPENDED`. A photographer record may be read by any of the desk roles; a `Photographer` reading the record must be reading their own.

### 3.2. Story Requests and the Sourcing Decision

Editorial need enters the system as a `StoryRequest`. A `PhotoEditor` opens one with a `headline`, a `slug` (stored as supplied; its uniqueness across story requests is not enforced), an editorial deadline `needed_by` that must parse as a valid ISO 8601 instant, and an art budget `budget_cents`. The request opens in `OPEN` status with `decision` null, both `commissioned_assignment_id` and `sourced_image_id` null, and `committed_cents` at zero.

The sourcing decision transitions `OPEN` to `DECIDED` and comes in two mutually exclusive branches, chosen by the `decision` field:

- **COMMISSION.** The editor supplies `photographer_id`, `brief`, `shoot_start`, and `shoot_end` — all four required, with `shoot_end` at or after `shoot_start` — and may optionally tune `min_image_count` (default 1) and `max_image_count` (default 10). The photographer must exist and be `ACTIVE`. The desk also enforces a travel-buffer double-booking rule: the commissioned shoot window padded by one calendar day on each side — computed by subtracting exactly 24 hours from the `shoot_start` instant and adding exactly 24 hours to the `shoot_end` instant, not by truncating to calendar dates — must not intersect the similarly padded window of any other assignment of the same photographer in `COMMISSIONED`, `IN_PROGRESS`, `SUBMITTED`, or `REVISION_REQUESTED` status; the padded intervals are compared as closed intervals, so touching at a buffer endpoint counts as a conflict and is rejected with `ERR_PHOTOGRAPHER_DOUBLE_BOOKED`. On success the system creates an `Assignment` in `COMMISSIONED` status, computes its `day_count` as the number of calendar days from `shoot_start` through `shoot_end` inclusive, and records the new assignment's id on the story request as `commissioned_assignment_id`.
- **WIRE_STOCK.** The editor supplies `image_id` referencing an existing image. The image must already be cleared — that is, in `CLEARED`, `PUBLISHED`, or `ARCHIVED` status; an `INGESTED` image is rejected with `ERR_IMAGE_NOT_CLEARED`. On success the image's id is recorded as `sourced_image_id`. An optional `decision_notes` field may accompany either branch; it is accepted but not stored on the story request.

Calling the decision on a request no longer `OPEN` is rejected with `ERR_STORY_ALREADY_DECIDED`. Missing branch-required fields, an out-of-order shoot window, or any other malformed payload is rejected with `ERR_INVALID_REQUEST`; a `photographer_id` that does not resolve surfaces as `ERR_PHOTOGRAPHER_NOT_FOUND`, and an unresolvable `image_id` as `ERR_IMAGE_NOT_FOUND`.

Cancellation from `OPEN` simply moves the request to `CANCELLED`. Cancellation from `DECIDED` cascades: a commissioned assignment still in `COMMISSIONED`, `IN_PROGRESS`, `SUBMITTED`, or `REVISION_REQUESTED` is moved to `CANCELLED` with the kill-fee rule of §3.4 applied, and every license charging this story that is still `DRAFT` or `ACTIVE` is moved to `REVOKED`, with the story's `committed_cents` decreased by the `fee_cents` of each revoked license that was `ACTIVE` — a `DRAFT` license never charged the story and releases nothing, and a license that has already lapsed to `EXPIRED` under §2.4 has already released its budget and is left `EXPIRED` rather than revoked. Both `FULFILLED` and `CANCELLED` are terminal.

A story request reaches `FULFILLED` automatically: when a usage run is recorded under a license whose `story_request_id` is this request, the system moves the request from `DECIDED` to `FULFILLED` without any explicit editor action.

### 3.3. Images: Ingest, Metadata Standards, Embargo, and Archive

An `Image` enters the desk by one of two routes. Assignment submissions (§3.4) create images with `source_type` `ASSIGNMENT`, linked to their assignment and photographer, with `base_license_fee_cents` forced to zero. Independently, a `RightsManager` ingests wire and stock imagery directly, supplying `source_type` of `WIRE` or `STOCK`, the `agency_name` (required for these two sources), and a `base_license_fee_cents` agency base fee that feeds the license fee quote. Submitting `ASSIGNMENT` as the `source_type` on direct ingest is rejected with `ERR_INVALID_REQUEST`. Wire and stock images carry null `photographer_id` and `assignment_id`.

At ingest, `caption`, `credit_line`, `keywords` (defaulting to an empty list), `has_identifiable_people`, and `has_private_property` (both defaulting to false) may all be supplied; caption and credit line are optional at this stage. The `embargo_until` field, when set, bars publication strictly before that instant; a publication exactly at the embargo instant is allowed, and a null `embargo_until` means no embargo. A `RightsManager` may later set or clear the embargo — passing null clears it — via the embargo-update capability, which increments the image's `version` by one.

Clearance is the desk's metadata gate. A `RightsManager` clears an `INGESTED` image only when its `caption` is present and at least ten characters long and its `credit_line` is present and non-empty after trimming surrounding whitespace (a whitespace-only credit line counts as empty); otherwise the clear is rejected with `ERR_INCOMPLETE_METADATA`. (An image that reaches clearance through the assignment-acceptance cascade of §3.4 clears without this manual check.) Clearance moves the image from `INGESTED` to `CLEARED`. From `CLEARED`, a `RightsManager` may archive the image, moving it to `ARCHIVED`; the same archive action is available from `PUBLISHED`. Archiving is a soft removal: archived images are excluded from default archive search results unless the caller passes `include_archived=true`, a flag honored only for `Archivist` and `RightsManager`. `ARCHIVED` is terminal for the editorial lifecycle, but an archived image remains licensable and publishable.

Archive search lets any desk role filter images by `q` (a case-insensitive substring match against the caption and against the space-joined keyword list), `status`, `source_type`, `photographer_id`, or `assignment_id`, with `limit` and `offset` pagination. Reading a single image returns its computed rights fields alongside its stored ones.

### 3.4. Assignments: Shoot, Submit, Review, Accept, and Kill Fees

An `Assignment` created by a `COMMISSION` decision starts in `COMMISSIONED` with `revision_count` at zero, `accepted_at` null, and `kill_fee_cents` at zero. Its `story_request_id` and `photographer_id` are fixed at creation from the decision. Assignments may be listed with filters on `story_request_id`, `photographer_id`, and `status`; a `Photographer` sees only their own assignments in these views.

The commissioned photographer submits images to the assignment with a payload carrying `caption`, `credit_line`, and optionally `keywords`, `has_identifiable_people`, `has_private_property`, and `embargo_until`. The acting photographer must own the assignment — the assignment's `photographer_id` must equal `X-User-ID` — or the submission is rejected with `ERR_FORBIDDEN`. Each submission creates an `Image` with `source_type` `ASSIGNMENT` in `INGESTED` status. The first submission to a `COMMISSIONED` assignment moves it to `IN_PROGRESS`; a submission while the assignment is `REVISION_REQUESTED` likewise returns it to `IN_PROGRESS`. The assignment accepts at most `max_image_count` images; a submission that would exceed the ceiling is rejected with `ERR_IMAGE_LIMIT_EXCEEDED`.

When the photographer believes the take is complete, they submit the assignment for review. Submission requires at least `min_image_count` images in `INGESTED` status on the assignment; otherwise it is rejected with `ERR_MIN_IMAGES_NOT_MET`. The assignment moves `IN_PROGRESS` to `SUBMITTED`.

The editor then either accepts or requests revisions. Requesting a revision moves `SUBMITTED` to `REVISION_REQUESTED`, increments `revision_count` by one, and may carry an optional `feedback` note, which is accepted but not stored on the assignment; the photographer's next image submission cycles the assignment back to `IN_PROGRESS`. Acceptance moves `SUBMITTED` to `ACCEPTED` and fires a two-hop cascade: the assignment's `accepted_at` is set to the logical now; every image on the assignment still `INGESTED` moves to `CLEARED`; and the photographer's `accrued_earnings_cents` increases by that photographer's `per_image_fee_cents` for each image so cleared, applied as a single ledger addition with the photographer's `version` incrementing once for the cascade as a whole. `ACCEPTED` is terminal.

A `PhotoEditor` may cancel an assignment from `COMMISSIONED` or `IN_PROGRESS` with no fee consequence. Cancelling from `SUBMITTED` or `REVISION_REQUESTED` runs the kill-fee rule: `kill_fee_cents` is set to the photographer's `day_rate_cents` multiplied by the assignment's `day_count`, multiplied by one half, rounded half-up to integer cents, and that amount is added to the photographer's `accrued_earnings_cents`. Cancelling from the two earlier states leaves `kill_fee_cents` at zero. An optional `reason` may be supplied with any cancellation; it is accepted but not stored on the assignment. `CANCELLED` is terminal.

### 3.5. Licensing: Quoting, Exclusivity, Budgets, and Supersession

A `License` grants a `usage_scope` — one of `PRINT`, `DIGITAL`, `SOCIAL`, or `SYNDICATION` — over a window from `valid_from` through `valid_to`. The window is inclusive at both ends for publication checks, but treated as half-open — including `valid_from`, excluding `valid_to` — for exclusivity overlap tests. A `valid_to` earlier than `valid_from` is rejected with `ERR_INVALID_REQUEST`. A license may optionally name a `story_request_id` whose budget it charges, a `territory` of `DOMESTIC`, `INTERNATIONAL`, or `GLOBAL` (default `DOMESTIC`), and an `exclusive` flag (default false). The named story request is not looked up at creation; a `story_request_id` that resolves to no story request is stored as-is, leaves the activation budget gate inert, and never accrues or releases a commitment.

Creating a license against an image is an OCC-guarded write (§2.7): when the request supplies `expected_image_version` it must match the image's current `version`, else the create is rejected with `ERR_STALE_VERSION` (HTTP 412); when the field is omitted, no version check is performed. The image must be in `CLEARED`, `PUBLISHED`, or `ARCHIVED` status, else `ERR_IMAGE_NOT_CLEARED`. A further temporal gate applies to assignment images: once an `ASSIGNMENT` image's `rights_reverted` flag is true, no new license may be created on it — the attempt is rejected with `ERR_RIGHTS_REVERTED`.

At creation the license's fee is quoted and frozen on `fee_cents`, and its `pricing_variant` is set to `REUSE` when the image's `times_used` is greater than zero at that moment, else `FIRST_USE`. The quote proceeds in a pinned order. Start from the image's `base_license_fee_cents`. Apply the scope multiplier: 1.0 for `PRINT`, 1.2 for `DIGITAL`, 0.8 for `SOCIAL`, 1.5 for `SYNDICATION`. Apply the territory multiplier to the result: 1.0 for `DOMESTIC`, 1.3 for `INTERNATIONAL`, 1.6 for `GLOBAL`. If the license is exclusive, double the result; otherwise leave it unchanged. Finally, for a `REUSE` license, apply the reuse discount by multiplying by 0.6 — that is, a 40 percent discount applied after the exclusivity multiplier — and round half-up to integer cents; a `FIRST_USE` license skips the discount and rounds half-up directly. Rounding happens exactly once, at this final step, so identical terms price lower on reuse than on first use.

A new license starts in `DRAFT`. If an `ACTIVE` license with the same `usage_scope` already exists on the image, creating the new license supersedes it: the old license moves to `REVOKED`, its `superseded_by_id` is set to the new license's id, and any story budget it held is released. Creation also increments the image's `version` by one.

Activation moves `DRAFT` to `ACTIVE` and enforces three gates, evaluated in this order:

1. **Release gate.** An image whose `has_identifiable_people` is true requires an `ACTIVE`, non-expired `MODEL` release on the image; an image whose `has_private_property` is true requires an `ACTIVE`, non-expired `PROPERTY` release. Missing or lapsed releases reject the activation with `ERR_RELEASE_REQUIRED`.
2. **Exclusivity gate.** If another `ACTIVE` exclusive license exists on the same image whose half-open window overlaps this license's window, activation is rejected with `ERR_EXCLUSIVE_LICENSE_CONFLICT`. If this license is itself exclusive, any other `ACTIVE` license of any kind with an overlapping window triggers the same rejection. Overlap uses half-open semantics, so adjacency — one window's `valid_from` equal to the other's `valid_to` — does not conflict.
3. **Budget gate.** When the license names a `story_request_id`, the story's `committed_cents` plus the license's `fee_cents` must not exceed the story's `budget_cents`; otherwise activation is rejected with `ERR_BUDGET_EXCEEDED`.

On successful activation, the license's `fee_cents` is added to the story's `committed_cents` when a story is named.

Revocation is available from both `DRAFT` and `ACTIVE`. Revoking an `ACTIVE` license compensates the story budget: `committed_cents` decreases by the license's `fee_cents`. Licenses charging a story are also revoked by the story-cancellation cascade of §3.2 and by the claim-resolution cascade of §3.8, each time releasing the budget they held. A license whose window closes lapses to `EXPIRED` by lazy derivation (§2.4), likewise releasing its budget commitment at the moment expiry is observed. Licenses may be listed filtered by `image_id`, `story_request_id`, or `status`.

### 3.6. Releases: Model and Property Clearances

A `ReleaseRecord` documents that a person depicted in an image, or the owner of depicted private property, has signed a release. A `RightsManager` registers a release on an image with a `subject_type` of `MODEL` or `PROPERTY`, the `subject_name`, a `document_ref` pointing at the signed document, the `signed_at` date, and an optional `expires_at`. A null `expires_at` means the release is perpetual; otherwise the release lapses to `EXPIRED` when the logical now reaches `expires_at` (§2.4). Releases start `ACTIVE`; a `RightsManager` may revoke one, moving it to `REVOKED`. Both `REVOKED` and `EXPIRED` are terminal.

The release gate fires twice in the lifecycle: at license activation (§3.5) and again at usage-run creation (§3.7). In both places the same rule applies — identifiable people require a live `MODEL` release, private property requires a live `PROPERTY` release — and the same `ERR_RELEASE_REQUIRED` rejection results.

### 3.7. Publication: Usage Runs, Royalties, and Rights Reversion

Recording a publication creates a `UsageRun` against an image, authorized by a license. Both `PhotoEditor` and `RightsManager` may record runs. The payload carries `license_id`, `channel`, `story_slug`, and `published_at`. The compliance gate is extensive, and violations surface in the relative order given in §2.8: the image must be in `CLEARED`, `PUBLISHED`, or `ARCHIVED` (`ERR_IMAGE_NOT_CLEARED`); the release gate of §3.6 applies (`ERR_RELEASE_REQUIRED`); `published_at` must not be strictly before the image's `embargo_until`, with publication exactly at the embargo instant allowed (`ERR_EMBARGO_ACTIVE`); `published_at` must fall within the license's window inclusive at both ends, so a publication exactly at `valid_to` is allowed (`ERR_LICENSE_WINDOW_VIOLATION`); the image must have no open claim against it — its `restriction_status` must be `NONE` (`ERR_IMAGE_UNDER_CLAIM`); the named license must belong to the path's image (`ERR_LICENSE_IMAGE_MISMATCH`); the run's `channel` must equal the license's `usage_scope` (`ERR_SCOPE_NOT_LICENSED`); and the license must be `ACTIVE` — `DRAFT`, `EXPIRED`, and `REVOKED` licenses cannot authorize publication (`ERR_LICENSE_NOT_ACTIVE`).

Each accepted run computes a per-line royalty and stores it on the run as `royalty_cents`. The line's ordinal is the image's `times_used` before this run plus one — runs are counted in `created_at` order, ties broken by ascending `created_at`, never by id. The tier multiplier is 1.5 when the ordinal is ten or higher, else 1.0. For wire and stock images, whose `photographer_id` is null, no desk royalty is owed and `royalty_cents` is zero. For assignment images, the line is the photographer's `royalty_rate_per_use_cents` multiplied by the channel multiplier — 1.0 for `PRINT`, 1.25 for `DIGITAL`, 0.5 for `SOCIAL`, 2.0 for `SYNDICATION` — multiplied by the tier, rounded half-up to integer cents. The line is then added to the photographer's `accrued_earnings_cents`, and the image's `times_used` increments by one; a line that computes to zero changes nothing and leaves the photographer record (including its `version`) untouched.

The first run on an image moves it from `CLEARED` to `PUBLISHED`, stamps `first_published_at` with that run's `published_at`, and — for assignment images only — projects the rights-reversion date: `rights_reversion_at` is `first_published_at` plus the photographer's `rights_reversion_months` calendar months. These first-run effects fire only when the image is `CLEARED` at recording time; a run recorded against an `ARCHIVED` image (permitted by the editorial gate) leaves the image `ARCHIVED`, stamps no `first_published_at`, and projects no reversion date, though its royalty line and `times_used` increment still apply. Wire and stock images never carry a reversion date; theirs stays null. The `rights_reverted` flag derives from the logical clock: it is true exactly when `rights_reversion_at` is non-null and the logical now is at or after it — rights have reverted at the exact reversion instant. Once `rights_reverted` is true, §3.5's gate bars new licenses on the image.

When the authorizing license names a `story_request_id`, recording the run moves that story request from `DECIDED` to `FULFILLED`. Runs may be listed per image or per license.

Before committing to a re-use, desk staff may invoke the archive re-use check, supplying a `channel` and an optional `published_at`. The check returns `eligible`, a list of `blocking_reasons`, a `fee_quote_cents` computed by the same fee-quote rule as §3.5 against the image's current state, the `pricing_variant` that would apply, and the booleans `requires_model_release` and `requires_property_release` reflecting the image's depictions. The quote assumes a non-exclusive `DOMESTIC` license, and if `channel` is absent or not a valid usage scope the quote is computed as `PRINT`. `blocking_reasons` is drawn from the tokens `IMAGE_NOT_CLEARED` (image not in `CLEARED`, `PUBLISHED`, or `ARCHIVED`), `IMAGE_UNDER_CLAIM` (restriction latched), `RIGHTS_REVERTED` (rights reverted), and `EMBARGO_ACTIVE` (a supplied `published_at` falls strictly before the embargo), appended in that check order, with `eligible` true exactly when the list is empty.

### 3.8. Infringement Claims: Intake, Negotiation, and Resolution

A claim against an image enters through a `RightsManager` supplying `image_id`, `claimant_name`, `claim_type` (one of `UNLICENSED_USE`, `COPYRIGHT_DISPUTE`, `MODEL_RELEASE_VIOLATION`), a `description`, and the `claimed_amount_cents`. Intake stamps the claim's `intaken_by_user_id` with the caller's `X-User-ID`, opens the claim in `INTAKE` status, and latches the image's `restriction_status` from `NONE` to `RESTRICTED`, blocking new usage runs under §3.7's gate.

From `INTAKE`, a `RightsManager` moves the claim to `UNDER_REVIEW`. The negotiation cycle then runs between two states: offering a settlement — payload `settlement_offer_cents` — moves `UNDER_REVIEW` to `SETTLEMENT_OFFERED` and records the offer on `proposed_settlement_cents`; recording the claimant's counter — payload `counter_amount_cents` — moves `SETTLEMENT_OFFERED` to `COUNTERED` and overwrites `proposed_settlement_cents` with the counter; a renewed offer from `COUNTERED` returns the claim to `SETTLEMENT_OFFERED` with `proposed_settlement_cents` updated again. Escalation toward litigation is available from `UNDER_REVIEW`, `SETTLEMENT_OFFERED`, or `COUNTERED`, moving the claim to `ESCALATED`.

Resolution is restricted by segregation of duties: the resolving `RightsManager`'s `X-User-ID` must differ from the claim's `intaken_by_user_id`, or the resolve is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Resolution carries an `outcome` of `UPHELD` or `DISMISSED` and is available from `UNDER_REVIEW`, `SETTLEMENT_OFFERED`, `COUNTERED`, or `ESCALATED`.

- **UPHELD.** The payload must include `settlement_amount_cents`, greater than zero and no more than `claimed_amount_cents`, else `ERR_INVALID_REQUEST`. The claim's `resolution_outcome` is set to `UPHELD`, `resolved_at` to the logical now, and `resolved_by_user_id` to the caller. The settlement split then runs in a pinned order. First, the photographer's share is computed from the settlement alone: for an `ASSIGNMENT` image, `photographer_clawback_cents` is 30 percent of `settlement_amount_cents` rounded half-up to integer cents; for wire and stock images it is zero, and the organization absorbs the remainder either way. Second, the cascades fire: the image's `restriction_status` latches to `RESTRICTED`; every `ACTIVE` license on the image moves to `REVOKED`; and each revoked license that named a story releases its `fee_cents` from that story's `committed_cents`. Third — last — the photographer's `accrued_earnings_cents` is debited by `photographer_clawback_cents`, flooring at zero.
- **DISMISSED.** The claim's `resolution_outcome` is set to `DISMISSED` with `resolved_at` and `resolved_by_user_id` stamped. As compensation, the image's `restriction_status` returns to `NONE` — but only when no other open claim (in `INTAKE`, `UNDER_REVIEW`, `SETTLEMENT_OFFERED`, `COUNTERED`, or `ESCALATED`) still references the image.

Both `RESOLVED` and `DISMISSED` are terminal. Claims may be listed filtered by `image_id` or `status`.

### 3.9. Photographer Payment: Guarantee versus Royalty

A `FinanceAdmin` settles photographer compensation by creating a `PaymentRun` for a period from `period_start` (inclusive) to `period_end` (exclusive); `period_end` must be strictly after `period_start`. Creation is the second OCC-guarded write (§2.7): when the request supplies `expected_photographer_version` it must match the photographer's current `version`, else the create is rejected with `ERR_STALE_VERSION` (HTTP 412); when the field is omitted, no version check is performed.

The payout computation aggregates three components over the half-open period window, scoped to the photographer. `guarantee_amount_cents` sums, over assignments of this photographer that reached `ACCEPTED` with `accepted_at` inside the window, the photographer's `day_rate_cents` multiplied by each assignment's `day_count`, plus one `per_image_fee_cents` for every image cleared by those in-period acceptances. `royalty_amount_cents` sums the stored per-line `royalty_cents` over usage runs of this photographer's images whose `published_at` falls inside the window — recalling that each line was already rounded half-up at creation, so the total is a sum of rounded lines, never a rounded sum. `clawback_cents` sums `photographer_clawback_cents` over claims against this photographer's images that resolved `UPHELD` with `resolved_at` inside the window.

The `method` derives from the photographer's type: `GUARANTEE` for `STAFF`, `ROYALTY` for `FREELANCE`. Both amount fields are always computed and stored, but the run pays only the chosen method's amount: `total_cents` is the chosen amount minus `clawback_cents`, floored at zero. A staff photographer's royalties never enter their payout, and a freelancer's day rates never enter theirs — identical period activity prices differently under the two variants.

The payment period lock prevents double-paying a period: the new run's half-open window must not overlap the window of any `APPROVED` or `PAID` run for the same photographer — adjacency is allowed — and a violation is rejected with `ERR_PAYMENT_PERIOD_LOCKED`. An overlapping `DRAFT` run is not an error; it is auto-voided to `VOIDED` as a supersession. Creating the run increments the photographer's `version` by one.

The run then walks its lifecycle under `FinanceAdmin` control: `DRAFT` to `APPROVED` on approval; `APPROVED` to `PAID` on payment, which stamps `paid_at` with the logical now and adds `total_cents` to the photographer's `paid_out_cents`; and voiding from `DRAFT`, `APPROVED`, or `PAID` moves the run to `VOIDED`. Voiding a `PAID` run is the compensation path and debits `total_cents` back out of `paid_out_cents`. `VOIDED` is terminal. A photographer may read their own payment runs; a `FinanceAdmin` reads any, and may filter a photographer's runs by `status`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — state transitions, setting an embargo, recording negotiation steps — return `200 OK`. Reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/photographers` | Onboard a photographer | PhotoEditor |
| GET | `/photographers/{id}` | Read a photographer (computed ledgers included) | PhotoEditor, RightsManager, FinanceAdmin, Archivist, Photographer |
| POST | `/photographers/{id}/suspend` | Suspend a photographer | PhotoEditor |
| POST | `/photographers/{id}/reactivate` | Reactivate a suspended photographer | PhotoEditor |
| GET | `/photographers/{id}/payment-runs` | List payment runs for a photographer | FinanceAdmin, Photographer |
| POST | `/photographers/{id}/payment-runs` | Create a DRAFT payment run for a period (OCC-guarded) | FinanceAdmin |
| POST | `/story-requests` | Open a story art request | PhotoEditor |
| GET | `/story-requests/{id}` | Read a story request | PhotoEditor, RightsManager, Archivist |
| POST | `/story-requests/{id}/decide` | Sourcing decision: COMMISSION creates an Assignment; WIRE_STOCK links an existing cleared image | PhotoEditor |
| POST | `/story-requests/{id}/cancel` | Cancel a story request; cascades to its assignment and linked licenses | PhotoEditor |
| GET | `/assignments` | List/filter assignments | PhotoEditor, RightsManager, Photographer |
| GET | `/assignments/{id}` | Read an assignment | PhotoEditor, RightsManager, Photographer |
| POST | `/assignments/{id}/images` | Photographer submits an image to an own assignment | Photographer |
| GET | `/assignments/{id}/images` | List images of an assignment | PhotoEditor, RightsManager, Photographer |
| POST | `/assignments/{id}/submit` | Photographer submits the assignment for editor review | Photographer |
| POST | `/assignments/{id}/accept` | Editor accepts: images clear, per-image fees accrue | PhotoEditor |
| POST | `/assignments/{id}/request-revision` | Editor requests revisions | PhotoEditor |
| POST | `/assignments/{id}/cancel` | Cancel an assignment; kill fee applies from SUBMITTED/REVISION_REQUESTED | PhotoEditor |
| POST | `/images` | Ingest a wire/stock image | RightsManager |
| GET | `/images` | Archive search with filters; ARCHIVED excluded unless include_archived=true | PhotoEditor, RightsManager, Archivist, FinanceAdmin, Photographer |
| GET | `/images/{id}` | Read an image (computed rights fields included) | PhotoEditor, RightsManager, Archivist, FinanceAdmin, Photographer |
| POST | `/images/{id}/clear` | Rights review: INGESTED → CLEARED; enforces metadata standard | RightsManager |
| POST | `/images/{id}/archive` | Archive an image (soft removal from default search) | RightsManager |
| PUT | `/images/{id}/embargo` | Set or clear embargo_until (null clears) | RightsManager |
| GET | `/images/{id}/reuse-check` | Archive re-use license check: eligibility, blocking reasons, fee quote, release requirements | PhotoEditor, RightsManager, Archivist |
| POST | `/images/{id}/usage-runs` | Record a publication under a license; full compliance gate | PhotoEditor, RightsManager |
| GET | `/images/{id}/usage-runs` | List usage runs of an image | PhotoEditor, RightsManager, Archivist, FinanceAdmin |
| POST | `/images/{id}/licenses` | Create a DRAFT license (fee quoted; supersedes ACTIVE same-scope; OCC-guarded) | RightsManager |
| GET | `/images/{id}/licenses` | List licenses of an image | PhotoEditor, RightsManager, Archivist |
| GET | `/licenses` | List/filter licenses | PhotoEditor, RightsManager, Archivist, FinanceAdmin |
| GET | `/licenses/{id}` | Read a license | PhotoEditor, RightsManager, Archivist, FinanceAdmin |
| GET | `/licenses/{id}/usage-runs` | List usage runs authorized by a license | RightsManager, Archivist, FinanceAdmin |
| POST | `/licenses/{id}/activate` | Activate a DRAFT license (release, exclusivity, budget gates) | RightsManager |
| POST | `/licenses/{id}/revoke` | Revoke a DRAFT or ACTIVE license (budget released) | RightsManager |
| POST | `/images/{id}/releases` | Register a model/property release | RightsManager |
| GET | `/images/{id}/releases` | List releases of an image | PhotoEditor, RightsManager, Archivist |
| POST | `/releases/{id}/revoke` | Revoke a release | RightsManager |
| POST | `/infringement-claims` | Intake an infringement claim; latches the image RESTRICTED | RightsManager |
| GET | `/infringement-claims` | List/filter claims | RightsManager, PhotoEditor, FinanceAdmin |
| GET | `/infringement-claims/{id}` | Read a claim | RightsManager, PhotoEditor, FinanceAdmin |
| POST | `/infringement-claims/{id}/review` | INTAKE → UNDER_REVIEW | RightsManager |
| POST | `/infringement-claims/{id}/offer` | Offer settlement (UNDER_REVIEW or COUNTERED → SETTLEMENT_OFFERED) | RightsManager |
| POST | `/infringement-claims/{id}/counter` | Record claimant counter (SETTLEMENT_OFFERED → COUNTERED) | RightsManager |
| POST | `/infringement-claims/{id}/escalate` | Escalate toward litigation | RightsManager |
| POST | `/infringement-claims/{id}/resolve` | Resolve claim (UPHELD runs settlement split and cascades; DISMISSED lifts restriction); SoD-enforced | RightsManager |
| GET | `/payment-runs/{id}` | Read a payment run | FinanceAdmin |
| POST | `/payment-runs/{id}/approve` | DRAFT → APPROVED | FinanceAdmin |
| POST | `/payment-runs/{id}/pay` | APPROVED → PAID; credits paid_out_cents | FinanceAdmin |
| POST | `/payment-runs/{id}/void` | DRAFT/APPROVED/PAID → VOIDED; voiding PAID debits paid_out_cents back | FinanceAdmin |
| POST | `/_clock/set_current_utc` | Advance the logical clock (default at startup 2026-08-01T00:00:00Z) | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_PHOTOGRAPHER_NOT_FOUND` | 404 |
| `ERR_STORY_REQUEST_NOT_FOUND` | 404 |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_IMAGE_NOT_FOUND` | 404 |
| `ERR_LICENSE_NOT_FOUND` | 404 |
| `ERR_RELEASE_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_PAYMENT_RUN_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_IMAGE_NOT_CLEARED` | 409 |
| `ERR_LICENSE_NOT_ACTIVE` | 409 |
| `ERR_STORY_ALREADY_DECIDED` | 409 |
| `ERR_EXCLUSIVE_LICENSE_CONFLICT` | 409 |
| `ERR_PHOTOGRAPHER_DOUBLE_BOOKED` | 409 |
| `ERR_PHOTOGRAPHER_SUSPENDED` | 409 |
| `ERR_RIGHTS_REVERTED` | 409 |
| `ERR_IMAGE_UNDER_CLAIM` | 409 |
| `ERR_PAYMENT_PERIOD_LOCKED` | 409 |
| `ERR_EMBARGO_ACTIVE` | 422 |
| `ERR_RELEASE_REQUIRED` | 422 |
| `ERR_LICENSE_WINDOW_VIOLATION` | 422 |
| `ERR_SCOPE_NOT_LICENSED` | 422 |
| `ERR_BUDGET_EXCEEDED` | 422 |
| `ERR_IMAGE_LIMIT_EXCEEDED` | 422 |
| `ERR_MIN_IMAGES_NOT_MET` | 422 |
| `ERR_INCOMPLETE_METADATA` | 422 |
| `ERR_LICENSE_IMAGE_MISMATCH` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_STALE_VERSION` | 412 |

Two fallback errors sit outside the domain catalogue: requests to an undefined path receive `ERR_NOT_FOUND` (HTTP 404, or HTTP 405 when the path exists but the method is not supported), and an unexpected server fault receives `ERR_INTERNAL` (HTTP 500); both use the standard error envelope of §2.2.
