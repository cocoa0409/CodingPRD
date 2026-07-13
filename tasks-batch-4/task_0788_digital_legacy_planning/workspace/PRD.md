# Digital-Legacy Planning API — Product Requirements Document

## 1. Introduction

Families rarely learn where a loved one kept the passwords, the deed, the insurance policy, or the funeral wishes until the moment those things are hardest to find. The Digital-Legacy Planning API is the backend for an end-of-life planning service (in the spirit of Everplans and Cake) that lets an estate owner assemble everything an executor will eventually need — accounts, assets, and documents — into a single secure vault, name the people who should be able to reach it, and record the advance directives and wishes that should guide decisions once the owner can no longer speak for themselves.

The system is built around a central tension: while the owner is alive and well, almost nothing should be readable by anyone else, yet the instant a verified life event occurs — an incapacity or a death — the right deputies must gain read access to exactly the right material, and named beneficiaries must receive their allocated share of each asset. This document specifies the entities, lifecycles, calculations, and access rules that make that controlled hand-off both safe and auditable. It governs the vault itself, the designation and release process for deputies and executors, the beneficiary contact tree, subscription-based seat limits and external sharing, integrations with external will and insurance registries, and the periodic review reminders that keep a plan current.

Because the platform manages both irreversible releases of sensitive material and monetary allocations to beneficiaries, every state transition, quorum rule, refund calculation, and concurrency check described below is a contract. Implementers should treat the business narrative in Section 3 as the authoritative source for how each workflow behaves, and Sections 4 and 5 as the transport-level summary.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across every endpoint. All resources live under the `/legacy` mount, are peers of one another, and are linked by foreign keys carried in request bodies rather than by nesting in URL paths.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming their operational capacity. The system recognizes exactly three roles: `Owner`, `Deputy`, and `PlatformAdmin`. A request that omits either header, or whose `X-User-Role` is not one of these three known roles, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the acting role is not permitted to invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The `Owner` role represents the estate owner and is entity-backed by the `Plan`: when `X-User-Role` is `Owner`, `X-User-ID` is the `id` of the acting owner's `Plan`. Ownership checks on any resource that references a plan compare the resource's `plan_id` to `X-User-ID`; an owner acting on a resource whose `plan_id` does not equal their `X-User-ID` is rejected with `ERR_FORBIDDEN_SCOPE`.

The `Deputy` role is entity-backed by the `Deputy`: when `X-User-Role` is `Deputy`, `X-User-ID` is the `id` of the acting `Deputy` record, and ownership checks compare a deputy against the plan it serves — a deputy may act only where its own `plan_id` matches the target resource's plan, and is otherwise rejected with `ERR_FORBIDDEN_SCOPE`.

The `PlatformAdmin` role is an operational role whose `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`; it is trusted to verify life events, verify, deny, and grant release requests, record billing outcomes, set the logical clock, and run review sweeps.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of leading items to skip and defaults to 0. Unless a specific workflow states otherwise, list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Every resource in the system carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp expressed in ISO 8601 UTC with three fractional digits. All ten entity types in this system — `Plan`, `VaultItem`, `Deputy`, `Beneficiary`, `Directive`, `ReleaseRequest`, `Subscription`, `Share`, `Integration`, and `ReviewReminder` — additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) and an integer `version`. The `updated_at` field is refreshed on every mutation, and `version` starts at 1 on creation and increments by one on every subsequent mutation of that resource, including mutations the server performs automatically as a side effect of another operation. A newly created resource is returned with HTTP 201; an operation that modifies an existing resource is returned with HTTP 200.

### 2.5. The Logical Clock and Deferred Lifecycle Sweeps

The platform runs on a logical clock rather than wall-clock time. On server startup the clock reads exactly `2026-03-01T00:00:00Z`, and until an administrator explicitly sets it, every time-dependent computation uses that default; the server never falls back to real wall-clock time. An administrator advances the clock by supplying a target instant as `to_iso8601`. All time-derived values — a release request's expiry, a share's access window, a subscription's billing period, and a reminder's due date — are evaluated against the current logical clock.

Certain lifecycle transitions are deferred rather than immediate: they do not fire when a deadline passes but when an administrator runs a review sweep for a plan. A sweep re-evaluates that plan's review reminders, active shares, and open release requests against the current clock (see Sections 3.6 and 3.8 for the exact reclassifications).

### 2.6. Optimistic Concurrency on Directive Activation

Activating a directive is guarded by optimistic concurrency control against the owning plan. The activation request must carry `expected_plan_version`, a non-optional field holding the `version` of the `Plan` that the client last observed. Because activating a directive supersedes any prior active directive of the same type and increments the plan's `version`, a client working from a stale view could otherwise silently supersede a directive it never saw. Therefore, if `expected_plan_version` does not equal the plan's current `version`, the activation is rejected with `ERR_STALE_VERSION` (HTTP 412). Only the directive-activation operation takes a version field; no other endpoint in this system requires one.

### 2.7. Monetary Values and Precision

All monetary amounts are stored and returned as integer cents. Two computations round to whole cents using the round-half-up method: the beneficiary allocation of a released asset, and the subscription refund produced at cancel time. Where a computation floors an intermediate value (as in the per-beneficiary allocation described in Section 3.4), that flooring is part of the specified algorithm and is distinct from the final round-half-up rule. Readiness scores are integer percentages, likewise rounded half up. Seat counts and approval counts are plain integers.

### 2.8. Request Validation Ordering, Ownership, and Referential Integrity

When multiple checks could reject a request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication is checked first: absent or unknown-role headers yield `ERR_UNAUTHENTICATED`. Next, endpoint-level role authorization is checked, yielding `ERR_UNAUTHORIZED`. Third, the request body and query are checked for well-formedness — required fields present, enum values within range, numeric amounts non-negative, and `allocation_pct` within the inclusive range from 0 to 100 — with any failure returning `ERR_VALIDATION`. Fourth, existence is checked: every id in the path and every foreign key in the body must resolve to an existing resource, evaluated left to right, returning `ERR_NOT_FOUND` (the catalogue also defines entity-specific not-found codes such as `ERR_PLAN_NOT_FOUND`, `ERR_VAULT_ITEM_NOT_FOUND`, `ERR_DEPUTY_NOT_FOUND`, `ERR_RELEASE_REQUEST_NOT_FOUND`, `ERR_DIRECTIVE_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, and `ERR_SHARE_NOT_FOUND`, used where a specific referenced resource is missing). Fifth, ownership/scope is checked: the acting principal must own or serve the target plan, returning `ERR_FORBIDDEN_SCOPE`; this applies to all mutating endpoints and to deputy reads. Sixth, for state-transition endpoints, the target must be in a state from which the requested transition is defined, otherwise `ERR_INVALID_STATE`.

Beyond that ordered core, several referential rules apply to specific creates. A foreign key supplied in a body must belong to the same plan as the target resource — for example, a share's `vault_item_id` must sit under the same plan as the share's `plan_id`, and a release request's `requested_by_deputy_id` must serve the same plan — and a cross-plan reference is rejected with `ERR_CROSS_PLAN_REFERENCE` (HTTP 422) on share creation, release-request creation, and beneficiary creation.

### 2.9. Seat Accounting and Subscription Gating

Each plan may have a single subscription that grants a seat allowance. Seats are consumed by two things: deputies that count against the limit and active shares. The consumed seat count, `seats_used`, is the number of deputies on the plan whose status is `INVITED` or `ACCEPTED` and whose `consumes_seat` is true, plus the number of shares on the plan whose status is `ACTIVE`. The allowance, `seat_limit`, is granted by the subscription tier — `FREE` grants 1 seat, `PLUS` grants 5, and `FAMILY` grants 10 — and is treated as 0 when the plan has no subscription. The plan's `seats_available` is the seat limit minus seats used, but never below zero. These figures are recomputed on demand — whenever a deputy is created, accepted, or revoked, whenever a share is created, revoked, or expired, and whenever the plan is read.

### 2.10. Secure Access to Released Material

The entire point of the platform is that deputies gain read access only after a life event releases the right material. When the acting role is `Deputy`, a read of a vault item — whether fetching one item or listing items — is permitted only when all of the following hold for that item: its status is `RELEASED`, its `kind` is contained in the deputy's `access_scope`, and there exists a `GRANTED` release request filed by this deputy whose released scope covers the item's `kind`. A deputy read that fails any of these conditions is rejected with `ERR_ACCESS_NOT_RELEASED`. Owners and administrators are not subject to this gate.

## 3. Business Logic & Workflows

### 3.1. The Estate Plan and Its Readiness Score

Everything begins with an estate `Plan`. An owner (or an administrator acting on their behalf) creates one by supplying the `owner_full_name` and `owner_email`. A new plan starts with its `life_status` set to `ACTIVE` and its `version` at 1, and its `life_evidence_ref` is null while the owner is `ACTIVE`. The `life_status` field is a system-managed lifecycle whose only forward path is `ACTIVE → INCAPACITATED → DECEASED`; `DECEASED` is terminal.

Only an administrator may record a life event, by posting a `new_status` together with an `evidence_ref` that documents it. The `evidence_ref` must be present, and the transition must follow the permitted order: from `ACTIVE` a plan may move to `INCAPACITATED` or directly to `DECEASED`, and from `INCAPACITATED` it may move to `DECEASED`. Any other requested life-status change — for instance moving backward, or supplying a status outside the `ACTIVE`/`INCAPACITATED`/`DECEASED` set — is rejected with `ERR_INVALID_LIFE_EVENT`. On a successful change the plan's `life_evidence_ref` is set to the supplied evidence reference and the plan's `version` increments by one. When a plan transitions to `DECEASED`, every review reminder on that plan whose status is `SCHEDULED`, `DUE`, or `OVERDUE` is cascaded to `DISMISSED` as part of the same operation.

A plan continuously exposes a readiness score, `completeness_pct`, an integer from 0 to 100 recomputed each time the plan (or its dedicated completeness read) is fetched, alongside the recomputed `seats_used` and `seats_available`. The score is a weighted blend of four signals measured on the plan: the number of vault items that are `SEALED` or `RELEASED` (`sealed_item_count`), the number of directives that are `ACTIVE` (`active_directive_count`), the number of deputies that are `ACCEPTED` (`accepted_deputy_count`), and the number of beneficiaries whose status is `NOMINATED` or `VESTED` (`beneficiary_count`). Each signal is normalized against a target and capped at full credit: the vault signal is the sealed-or-released item count divided by a target of 5 items, capped at 1; the directive signal is the active-directive count divided by a target of 2 directives, capped at 1; the deputy signal is 1 if at least one deputy is accepted and 0 otherwise; and the beneficiary signal is the beneficiary count divided by a target of 3 beneficiaries, capped at 1.

The four normalized signals are combined with tier-dependent weights drawn from the plan's subscription. For a `FAMILY`-tier plan the weights for (vault, directive, deputy, beneficiary) are 30, 20, 20, and 30 respectively; for every other tier (and when there is no subscription) they are 40, 20, 20, and 20. The raw score is the sum of each weight multiplied by its normalized signal, and `completeness_pct` is that raw score rounded half up to the nearest integer.

### 3.2. Building the Vault

The vault holds the material an executor will eventually need. An owner adds a `VaultItem` by supplying its `plan_id`, its `kind` (one of `ACCOUNT`, `ASSET`, or `DOCUMENT`), a free-text `category`, a human `title`, and a `secret_ref` pointing at the encrypted payload. The owner may also set a `sensitivity` of `LOW`, `MEDIUM`, or `HIGH`, defaulting to `MEDIUM` when omitted. Every item is created in `DRAFT` status.

Asset items carry monetary detail. For an item whose `kind` is `ASSET`, the owner may supply `gross_value_cents` (which must be zero or greater), a `liability_cents` debt attached to the asset that defaults to 0 and must be zero or greater, and a `distribution_basis` of `NET` or `GROSS` that defaults to `NET`. The system derives `net_value_cents` as the gross value minus the liability, floored at zero so it is never negative; `net_value_cents` is null for any item whose kind is not `ASSET`.

An item's `status` follows the lifecycle `DRAFT → SEALED → RELEASED`, with `ARCHIVED` as a terminal soft-delete reachable from either `DRAFT` or `SEALED`. An owner seals a draft item to make it eligible for release. Sealing an asset requires that its `gross_value_cents` be present, and if beneficiaries are already linked to that asset, the sum of `allocation_pct` across the item's `NOMINATED` beneficiaries must not exceed 100 at the moment of sealing — a violation is rejected with `ERR_ALLOCATION_EXCEEDS_100`. An owner or administrator may recall a released item back to `SEALED`; recalling an asset compensates its distribution by reverting every linked `VESTED` beneficiary back to `NOMINATED` and resetting each one's `allocated_value_cents` to 0, which conserves the asset's distributable value. An owner may archive a draft or sealed item, which excludes it from default listings. The transition from `SEALED` to `RELEASED` is never requested directly on the item; it happens only as a cascade when a release request is granted (see Section 3.6).

### 3.3. Deputies and Delegated Authority

An owner delegates scoped access by designating a `Deputy`, supplying the `plan_id`, the deputy's `full_name` and `email`, a `deputy_role` of `EXECUTOR`, `HEALTHCARE_PROXY`, `GUARDIAN`, or `VIEWER`, and an `access_scope` that is a subset of `ACCOUNT`, `ASSET`, and `DOCUMENT` describing which kinds of released material this deputy may read. Each designation also declares a `release_trigger` of `ON_DEATH`, `ON_INCAPACITY`, or `IMMEDIATE`, describing the life event that unlocks the deputy's access, and a term of authority bounded by `authority_start_at` and `authority_end_at` (both inclusive, ISO 8601 UTC). By default a deputy counts against the subscription's seat allowance, but the owner may set `consumes_seat` to false to exempt them. A deputy is created in `INVITED` status.

Two guards apply at designation time. First, seat capacity: adding a seat-consuming deputy is rejected with `ERR_SEAT_LIMIT_REACHED` when `seats_used` already equals or exceeds `seat_limit`. Second, term overlap: for the same plan and `deputy_role`, an existing non-`REVOKED` deputy's closed term (from its `authority_start_at` through its `authority_end_at`) plus a seven-day buffer must not overlap the proposed term — the gap between terms of the same role must exceed seven days — and a violation is rejected with `ERR_DEPUTY_TERM_OVERLAP`.

A deputy accepts their own designation, moving `INVITED → ACCEPTED`, which makes them an active voter for release quorum. An owner may revoke a deputy from either `INVITED` or `ACCEPTED`, moving it to the terminal `REVOKED` state; revocation frees the deputy's seat (seat accounting recomputes) and, as a cascade, moves every release request in `PENDING` or `VERIFIED` status whose `requested_by_deputy_id` is this deputy to `DENIED`.

### 3.4. The Beneficiary Contact Tree and Asset Allocation

Beneficiaries form a contact tree and, for asset items, the allocation targets. An owner adds a `Beneficiary` with a `plan_id`, `full_name`, and `relationship` (for example "spouse" or "child"), optionally a `contact_email`, and optionally an `allocation_pct` (a percentage in the inclusive range 0 to 100, defaulting to 0). A beneficiary may be positioned in the tree by supplying `parent_beneficiary_id` — the id of another beneficiary that is its parent node, left null for a root node — and may be linked to a specific asset by supplying `asset_vault_item_id`, the vault item whose value it shares, left null when unlinked. A beneficiary starts in `NOMINATED` status and carries an `allocated_value_cents` that stays 0 until the linked asset is released and the beneficiary vests.

When a linked asset item transitions from `SEALED` to `RELEASED` (as a cascade of a granted release), the allocation runs and each linked `NOMINATED` beneficiary moves to `VESTED` with its `allocated_value_cents` set. The basis for distribution is chosen by the asset's `distribution_basis`: a `NET` asset distributes its `net_value_cents` (gross minus liability, floored at zero), while a `GROSS` asset distributes its `gross_value_cents` outright, ignoring the liability. The eligible beneficiaries are those linked to the item whose status is `NOMINATED`, taken in ascending `created_at` order.

The rounding order is fixed: floor each beneficiary first, then distribute the remainder. For each beneficiary, compute the raw share as the basis value multiplied by that beneficiary's `allocation_pct` divided by 100, and take its floor as the beneficiary's provisional cents. Then compute the total distributable pool as the floor of the basis value multiplied by the sum of all the beneficiaries' `allocation_pct` divided by 100, and subtract the sum of the floored provisional cents to obtain the leftover remainder. Distribute that remainder one cent at a time to beneficiaries in ascending `created_at` order — the first beneficiary in creation order receives one extra cent, then the next, and so on until the remainder is exhausted — so that the earliest-created beneficiaries absorb the rounding leftovers. Beneficiaries not reached by the remainder pass keep exactly their floored share. Ordering is always by `created_at`, never by `id`. An owner may remove a beneficiary while it is `NOMINATED`, moving it to the terminal `REMOVED` state and excluding it from future allocations.

### 3.5. Advance Directives and Wishes

An owner records advance directives and wishes as `Directive` records, each created with a `plan_id`, a `directive_type` of `MEDICAL`, `FUNERAL`, `DNR`, or `ORGAN_DONATION`, and the `content` text. A directive begins in `DRAFT` status with its `version_number` at 1. Its lifecycle is `DRAFT | UNDER_REVISION → ACTIVE`, with `ACTIVE → UNDER_REVISION` for edits, and `SUPERSEDED` and `REVOKED` as terminal states.

Activating a directive (from `DRAFT` or `UNDER_REVISION`) is restricted to the owner and requires that the plan's `life_status` be `ACTIVE` — an owner cannot activate a new directive once the plan is `INCAPACITATED` or `DECEASED`. Activation also carries the optimistic-concurrency guard described in Section 2.6: the request must include `expected_plan_version`, and a mismatch with the plan's current `version` is rejected with `ERR_STALE_VERSION`. On a successful activation, any other directive of the same `directive_type` that is currently `ACTIVE` on the plan is superseded (moved to `SUPERSEDED`), and the plan's `version` increments by one. Revising an active directive moves it to `UNDER_REVISION` and increments its `version_number` by one. An owner may revoke a directive from `DRAFT`, `ACTIVE`, or `UNDER_REVISION`, moving it to the terminal `REVOKED` state.

### 3.6. The Release Workflow

Release is the controlled hand-off that unlocks the vault. An accepted deputy files a `ReleaseRequest` by supplying the `plan_id`, a `trigger_type` of `ON_DEATH` or `ON_INCAPACITY` asserted as the basis for release, and a `scope_kinds` array naming which of `ACCOUNT`, `ASSET`, and `DOCUMENT` should be released on grant. The request records the filing deputy in `requested_by_deputy_id` (bound to the acting deputy), starts with an empty `approver_deputy_ids` list, and begins in `PENDING` status. Its lifecycle branches: `PENDING → VERIFIED` or `PENDING → DENIED`; then `VERIFIED → APPROVED` or `VERIFIED → DENIED`; then `APPROVED → GRANTED`; with `GRANTED`, `DENIED`, and `EXPIRED` all terminal.

An administrator verifies a pending request, but only when the plan's `life_status` actually satisfies the asserted trigger: an `ON_DEATH` request requires the plan to be `DECEASED`, and an `ON_INCAPACITY` request requires the plan to be `INCAPACITATED` or `DECEASED`. A verify attempted against an unsatisfied life status is rejected with `ERR_RELEASE_NOT_TRIGGERED`. Verification pins the approval quorum and sets an expiry: `required_approvals` is fixed at verify time to the number of accepted deputies on the plan multiplied by one-half, rounded up to the next whole number, with a floor of 1 (so at least one approval is always required), and `expires_at` is set to the current clock plus 14 days.

Once verified, accepted deputies vote by submitting a `decision` of `APPROVE` or `REJECT`, optionally with a `note`. A deputy may vote only once on a given request; a second vote by the same deputy is rejected with `ERR_DUPLICATE_APPROVAL`. Each `APPROVE` vote appends the deputy to `approver_deputy_ids` and increments the distinct-approver count `approval_count`; the request moves from `VERIFIED` to `APPROVED` the instant `approval_count` reaches or exceeds `required_approvals` (the boundary is inclusive — exactly meeting the quorum approves). A single `REJECT` vote vetoes the request, moving it directly from `VERIFIED` to `DENIED`. An administrator may also deny a request outright from either `PENDING` or `VERIFIED`.

An administrator grants an approved request to actually release material. Granting requires that at least one `SEALED` vault item exists on the plan whose `kind` is in the request's `scope_kinds`; if there is nothing eligible to release, the grant is rejected with `ERR_NOTHING_TO_RELEASE`. Granting also requires that the plan's subscription not be `PAST_DUE`; a grant against a past-due subscription is rejected with `ERR_SUBSCRIPTION_PAST_DUE`. If an administrator attempts to grant a request that is `VERIFIED` but has not yet reached its quorum (its `approval_count` is below `required_approvals`), the grant is rejected with `ERR_QUORUM_NOT_MET`; a grant attempted from any state other than `APPROVED` (or the quorum-pending `VERIFIED` case just described) is rejected with `ERR_INVALID_STATE`. On a successful grant, the request moves `APPROVED → GRANTED`, and as a two-link cascade every `SEALED` vault item on the plan whose `kind` is in `scope_kinds` moves to `RELEASED`, and each released `ASSET` item in turn vests its linked beneficiaries by running the allocation described in Section 3.4.

Open requests do not linger forever. During a review sweep, any request still in `PENDING` or `VERIFIED` whose `expires_at` is set and whose expiry is at or before the current clock is moved to the terminal `EXPIRED` state.

### 3.7. Subscriptions, Billing, and External Sharing

A plan's capabilities are governed by a `Subscription`. An owner creates one with a `plan_id`, a `tier` of `FREE`, `PLUS`, or `FAMILY`, and an optional `refund_policy` of `IMMEDIATE_PRORATA` or `FORFEIT` that defaults to `IMMEDIATE_PRORATA`. The tier fixes two derived values: the `seat_limit` (1 for `FREE`, 5 for `PLUS`, 10 for `FAMILY`) and the `monthly_fee_cents` (0 for `FREE`, 1200 for `PLUS`, 2400 for `FAMILY`). A new subscription begins in `TRIALING` status with `period_start` set to the current clock and `period_end` set to 30 days after `period_start`, and its `last_refund_cents` starts at 0. The lifecycle is `TRIALING | PAST_DUE → ACTIVE`, `ACTIVE → PAST_DUE`, and any of `TRIALING`, `ACTIVE`, or `PAST_DUE` to the terminal `CANCELED`.

An administrator records billing outcomes by posting an `outcome`. A `SUCCEEDED` outcome moves the subscription to `ACTIVE` and advances the billing period: `period_start` moves to the prior `period_end` (or to the current clock if that is later), and `period_end` becomes the new `period_start` plus 30 days. A `FAILED` outcome moves an `ACTIVE` subscription to `PAST_DUE`.

An owner may cancel a subscription. Cancellation computes a refund into `last_refund_cents` according to the `refund_policy`. Under `IMMEDIATE_PRORATA`, the refund returns the unused portion of the current 30-day period by whole remaining days: the remaining days are the floor of the number of whole days between the current clock and `period_end`, never below zero, and the refund is the `monthly_fee_cents` multiplied by those remaining days divided by 30, rounded half up to whole cents. Under `FORFEIT`, the refund is zero and access simply continues until `period_end`. Cancellation also cascades: every `ACTIVE` share on the plan is moved to `REVOKED`.

Sharing lets an owner grant outside read access. An owner creates a `Share` with a `plan_id`, a `shared_with_email` recipient, a `scope` of `ITEM` or `PLAN`, and a half-open access window bounded by an inclusive `effective_at` and an exclusive `expires_at`. When the scope is `ITEM`, the owner supplies the `vault_item_id` being shared; that field is left null for a whole-plan share. A share is created in `ACTIVE` status and consumes a seat. External sharing is a paid feature: creating a share requires the plan's subscription to be a paid tier (not `FREE`) and in `ACTIVE` status, otherwise the request is rejected with `ERR_SUBSCRIPTION_REQUIRED`. Seat capacity applies as in Section 3.3 — a share that would exceed the seat allowance is rejected with `ERR_SEAT_LIMIT_REACHED`. Overlap is also guarded: for the same `vault_item_id` and `shared_with_email`, an existing `ACTIVE` share's half-open window from its `effective_at` up to its `expires_at` must not overlap the new window, though touching ends (where one window's end equals the other's start) are allowed; an overlap is rejected with `ERR_SHARE_WINDOW_OVERLAP`. An owner may revoke an active share, moving it `ACTIVE → REVOKED` and freeing its seat. During a review sweep, an `ACTIVE` share whose `expires_at` is at or before the current clock is moved to the terminal `EXPIRED` state.

### 3.8. Integrations and Review Reminders

A plan can link external records through an `Integration`. An owner creates one with a `plan_id`, a `provider_type` of `WILL_REGISTRY` or `LIFE_INSURANCE`, a `provider_name`, an `external_ref` (the policy or registry reference number at the provider), and an optional `coverage_cents` declaring the coverage or benefit amount, which defaults to 0 and must be zero or greater. An integration is created with `sync_status` of `LINKED` and a null `last_synced_at`. An owner or administrator may trigger a sync, which moves `sync_status` from `LINKED` to `SYNCING` and, as the sync completes within the same request, back to `LINKED`, setting `last_synced_at` to the current clock.

Finally, the platform keeps a plan current through `ReviewReminder` records. An owner schedules one with a `plan_id`, a `subject_kind` of `VAULT`, `DIRECTIVE`, `BENEFICIARY`, or `SUBSCRIPTION`, an optional `interval_days` (at least 1, defaulting to 180), and a `last_reviewed_at` anchor instant. The reminder's `due_at` is computed as the anchor `last_reviewed_at` plus `interval_days` days, and it starts in `SCHEDULED` status. Its status is reclassified only during a review sweep, by comparing the current clock against `due_at` with a 30-day grace window: while the clock is before `due_at` the reminder stays `SCHEDULED`; once the clock is at or after `due_at` but still before `due_at` plus 30 days it becomes `DUE`; and once the clock reaches `due_at` plus 30 days or later it becomes `OVERDUE`. An owner marks a reminder complete from any of `SCHEDULED`, `DUE`, or `OVERDUE`, which moves it to the terminal `COMPLETED` state, sets its `last_reviewed_at` to the current clock, and recomputes `due_at` for the record snapshot. As noted in Section 3.1, reminders that are `SCHEDULED`, `DUE`, or `OVERDUE` are cascaded to the terminal `DISMISSED` state when the plan becomes `DECEASED`.

## 4. Endpoint Definitions

Operations that create a new resource return HTTP 201 Created. Operations that read a resource or drive a state transition on an existing resource return HTTP 200 OK. The request body, response body, and side effects of each operation are described in the workflows of Section 3; the table below is only a routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/legacy/plans` | Create an estate plan | Owner, PlatformAdmin |
| GET | `/legacy/plans/{plan_id}` | Get a plan (with computed readiness and seats) | Owner, PlatformAdmin, Deputy |
| GET | `/legacy/plans/{plan_id}/completeness` | Computed read of the plan readiness score | Owner, PlatformAdmin |
| POST | `/legacy/plans/{plan_id}/life-status` | Record a verified owner life event | PlatformAdmin |
| POST | `/legacy/vault-items` | Create a vault item | Owner |
| GET | `/legacy/vault-items` | List vault items (filterable) | Owner, PlatformAdmin, Deputy |
| GET | `/legacy/vault-items/{item_id}` | Get a vault item | Owner, PlatformAdmin, Deputy |
| POST | `/legacy/vault-items/{item_id}/seal` | Seal a vault item | Owner |
| POST | `/legacy/vault-items/{item_id}/recall` | Recall a released item back to sealed | Owner, PlatformAdmin |
| POST | `/legacy/vault-items/{item_id}/archive` | Archive (soft-delete) a vault item | Owner |
| POST | `/legacy/deputies` | Designate a deputy/executor | Owner |
| GET | `/legacy/deputies` | List deputies (filterable) | Owner, PlatformAdmin |
| GET | `/legacy/deputies/{deputy_id}` | Get a deputy | Owner, PlatformAdmin, Deputy |
| POST | `/legacy/deputies/{deputy_id}/accept` | Deputy accepts the designation | Deputy |
| POST | `/legacy/deputies/{deputy_id}/revoke` | Owner revokes a deputy | Owner |
| POST | `/legacy/beneficiaries` | Add a beneficiary/contact | Owner |
| GET | `/legacy/beneficiaries` | List beneficiaries (filterable) | Owner, PlatformAdmin |
| GET | `/legacy/beneficiaries/{beneficiary_id}` | Get a beneficiary | Owner, PlatformAdmin |
| POST | `/legacy/beneficiaries/{beneficiary_id}/remove` | Remove a beneficiary | Owner |
| POST | `/legacy/directives` | Draft an advance directive / wish | Owner |
| GET | `/legacy/directives` | List directives (filterable) | Owner, PlatformAdmin, Deputy |
| GET | `/legacy/directives/{directive_id}` | Get a directive | Owner, PlatformAdmin, Deputy |
| POST | `/legacy/directives/{directive_id}/activate` | Activate a directive (OCC on plan version) | Owner |
| POST | `/legacy/directives/{directive_id}/revise` | Open a directive for revision | Owner |
| POST | `/legacy/directives/{directive_id}/revoke` | Revoke a directive | Owner |
| POST | `/legacy/release-requests` | Deputy files a release request | Deputy |
| GET | `/legacy/release-requests` | List release requests (filterable) | Owner, PlatformAdmin, Deputy |
| GET | `/legacy/release-requests/{release_request_id}` | Get a release request | Owner, PlatformAdmin, Deputy |
| POST | `/legacy/release-requests/{release_request_id}/verify` | Verify the life-trigger; pin quorum and expiry | PlatformAdmin |
| POST | `/legacy/release-requests/{release_request_id}/approve` | Deputy casts an APPROVE or REJECT vote | Deputy |
| POST | `/legacy/release-requests/{release_request_id}/deny` | Admin denies a release request | PlatformAdmin |
| POST | `/legacy/release-requests/{release_request_id}/grant` | Admin grants an approved release | PlatformAdmin |
| POST | `/legacy/subscriptions` | Create a subscription for a plan | Owner |
| GET | `/legacy/subscriptions` | List subscriptions (filterable) | Owner, PlatformAdmin |
| GET | `/legacy/subscriptions/{subscription_id}` | Get a subscription | Owner, PlatformAdmin |
| POST | `/legacy/subscriptions/{subscription_id}/cancel` | Cancel a subscription | Owner |
| POST | `/legacy/subscriptions/{subscription_id}/record-payment` | Record a billing outcome | PlatformAdmin |
| POST | `/legacy/shares` | Share an item or the whole plan with a contact | Owner |
| GET | `/legacy/shares` | List shares (filterable) | Owner, PlatformAdmin |
| GET | `/legacy/shares/{share_id}` | Get a share | Owner, PlatformAdmin |
| POST | `/legacy/shares/{share_id}/revoke` | Revoke a share | Owner |
| POST | `/legacy/integrations` | Link an external will/insurance record | Owner |
| GET | `/legacy/integrations` | List integrations (filterable) | Owner, PlatformAdmin |
| GET | `/legacy/integrations/{integration_id}` | Get an integration | Owner, PlatformAdmin |
| POST | `/legacy/integrations/{integration_id}/sync` | Sync an external record | Owner, PlatformAdmin |
| POST | `/legacy/review-reminders` | Schedule a review reminder | Owner |
| GET | `/legacy/review-reminders` | List review reminders (filterable) | Owner, PlatformAdmin |
| GET | `/legacy/review-reminders/{reminder_id}` | Get a review reminder | Owner, PlatformAdmin |
| POST | `/legacy/review-reminders/{reminder_id}/complete` | Mark a review complete | Owner |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/_ops/run-review-sweep` | Advance clock-driven lifecycles for a plan | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FORBIDDEN_SCOPE` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ACCESS_NOT_RELEASED` | 403 |
| `ERR_RELEASE_NOT_TRIGGERED` | 409 |
| `ERR_CROSS_PLAN_REFERENCE` | 422 |
| `ERR_SHARE_WINDOW_OVERLAP` | 409 |
| `ERR_DEPUTY_TERM_OVERLAP` | 409 |
| `ERR_SEAT_LIMIT_REACHED` | 409 |
| `ERR_ALLOCATION_EXCEEDS_100` | 422 |
| `ERR_DUPLICATE_APPROVAL` | 409 |
| `ERR_QUORUM_NOT_MET` | 409 |
| `ERR_NOTHING_TO_RELEASE` | 422 |
| `ERR_SUBSCRIPTION_PAST_DUE` | 402 |
| `ERR_SUBSCRIPTION_REQUIRED` | 402 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PLAN_NOT_FOUND` | 404 |
| `ERR_VAULT_ITEM_NOT_FOUND` | 404 |
| `ERR_DEPUTY_NOT_FOUND` | 404 |
| `ERR_RELEASE_REQUEST_NOT_FOUND` | 404 |
| `ERR_DIRECTIVE_NOT_FOUND` | 404 |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 |
| `ERR_SHARE_NOT_FOUND` | 404 |
| `ERR_INVALID_LIFE_EVENT` | 422 |
