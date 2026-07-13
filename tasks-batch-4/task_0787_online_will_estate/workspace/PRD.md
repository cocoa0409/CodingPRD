# Online Will & Estate Planning API — Product Requirements Document

## 1. Introduction

Estate planning has historically demanded expensive attorney hours before a member ever sees a signed will, and the resulting documents are frequently out of date the moment a member moves states, marries, or acquires new property. This API powers a subscription-based estate-planning product that replaces that friction with a guided, self-service experience: members answer a state-aware questionnaire, generate legally-shaped documents (a will, a living trust, a power of attorney, or a healthcare directive), optionally route those documents through a licensed attorney for review, and finally have them notarized and witnessed for execution. Around each document the platform also maintains the surrounding estate context — beneficiaries and their residuary shares, an asset inventory with funding status, nominated executors, and secure shares that grant a trusted party access to an executed document.

The product is organized as an annual subscription. A member selects a plan tier, optionally bundles a spouse and an attorney-support add-on, and pays a signup charge that unlocks a full coverage year. Subscriptions renew on a loyalty-rewarding schedule, may lapse into a suspended grace period on a failed renewal, and can be cancelled with a prorated refund. Because the lifecycle of an estate plan touches money, legal state, and downstream artifacts, the system is built around immediate, cascading consistency: cancelling a subscription unwinds its documents, share grants, and executors; executing a new version of a document supersedes and locks down the old one.

This document specifies the complete contract for that API — the request/response envelope, the role model, every state machine and its transitions, the pricing and estate-distribution calculations, and the validation rules (with their relative precedence) that guard each operation. It is the sole specification an implementer should need; every field, rule, threshold, and error is described in prose below.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply uniformly across every endpoint. The entire API is mounted under the `/v1` prefix.

### 2.1. User and Role-Based Access Control

Every request other than public member registration must be authenticated by two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the operational capacity in which they act. When either header is missing, or when `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes five roles: `Anonymous`, `Member`, `Attorney`, `Notary`, and `PlatformAdmin`.

- `Anonymous` is the unauthenticated public caller. Its only capability is registering a new member account, which is therefore the single endpoint that does not require the authentication headers.
- When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; this is what ties the caller to resource ownership. Ownership checks on any resource that references a `Member` — directly, or transitively through its owning `Subscription` — compare the resource's owning member to `X-User-ID`. A member acting on a resource whose subscription chain does not resolve to their own member id is rejected with `ERR_UNAUTHORIZED` (HTTP 403).
- When `X-User-Role` is `Attorney`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `attorney_user_id` on an `AttorneyReview` when the attorney starts a review — but it never compares it to any entity's `id`.
- When `X-User-Role` is `Notary`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The `PlatformAdmin` operates the plan catalog, the logical clock, and payment simulation, and may read any resource.

Read endpoints for member-owned data are shared between the owning `Member` and `PlatformAdmin`; the attorney-reviews listing for a document is additionally readable by an `Attorney`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. Unless a specific endpoint states otherwise, list endpoints return their resources sorted by `created_at` in ascending order.

Every list response echoes the pagination state inside the envelope's `meta` object through the fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the full count of matching resources before the window is applied and `has_more` indicates whether items remain beyond the current page.

### 2.4. Common Resource Properties and the Plan Catalog Exception

Most resources carry a common set of system-managed properties. The `id` is a server-minted UUID with no type prefix; it is identity only and is never itself an input to a business decision. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, set once when the resource is created. Resources that can be mutated after creation additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at its initial value and increments by one on every mutation. The `version` field is the basis for optimistic concurrency control described in §2.7.

The `Member`, `Subscription`, `Questionnaire`, `EstateDocument`, `Beneficiary`, `Asset`, `Executor`, `ShareGrant`, and `AttorneyReview` resources all carry the full common set including `updated_at` and `version`. Every resource that has a lifecycle exposes its current lifecycle position in a `status` field whose permitted values are the exact state strings named in that resource's workflow below. The `PlanCatalog` resource is the exception: it carries only `id` and `created_at`, and does not have `updated_at` or `version`. Catalog rows are configuration and are not mutated in place.

### 2.5. The Logical Clock and Temporal Semantics

All time-based logic in the system is driven by a logical clock rather than wall-clock time. On server startup the clock reads exactly `2026-03-01T00:00:00Z`, and before the clock is ever set it remains at that default and never falls back to real time. A `PlatformAdmin` advances the clock to a supplied instant provided as `to_iso8601`. Every timestamp the system stamps — a subscription's coverage window, a document's `execution_date`, the evaluation of a renewal window or a share-grant window — reads "now" from this logical clock. This makes coverage periods, grace windows, and expiries fully deterministic and testable.

### 2.6. Monetary Values, Counts, and Rounding

All monetary amounts are stored and returned as integer cents; there are no fractional cents anywhere in the system. Where a calculation multiplies by a non-integer factor (a bundle multiplier, a loyalty discount, a proration ratio, or a percentage), the result is rounded to a whole number of cents using the round-half-up method — a value exactly at the half-cent boundary rounds up. Each pricing calculation performs its multiplication and then applies a single rounding step; intermediate sums are not pre-rounded.

Two calculations are exceptions to rounding because they are inherently integer or per-item. Questionnaire completeness is a percentage carried to two decimal places (round-half-up). The estate-distribution waterfall works entirely in integer cents using floor division followed by an explicit one-cent-at-a-time residual assignment, and must not be computed as round-each-share-then-sum; its exact procedure is specified in §3.9. Witness counts and required-field counts are plain integers.

### 2.7. Optimistic Concurrency Control on Plan Changes

Changing a subscription's plan is guarded by optimistic concurrency control. The change-plan operation requires a non-optional `expected_subscription_version` field carrying the client's last observed `version` of the target `Subscription`. If `expected_subscription_version` does not equal the subscription's current `version` — that is, if any other writer has advanced the subscription since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no plan change or price recomputation occurs. A plan change legitimately supersedes the prior plan and recomputes the locked price, so a change carrying a stale version would be operating on an out-of-date view of the subscription and is refused. No other endpoint takes a version field; only the change-plan operation participates in this concurrency check.

### 2.8. Cascading Consistency and Hierarchical Revocation

The estate plan is a web of peer resources linked by foreign keys, and several operations mutate more than one resource in a single, immediate cascade. Two cascade chains are central to the system, and every hop of each chain independently mutates the affected resource — refreshing its `updated_at` and incrementing its `version`.

**Cascade chain one — cancellation.** When a subscription is cancelled, every non-terminal `EstateDocument` of that subscription transitions to `REVOKED`. Each document reaching `REVOKED` in turn revokes its own dependents: every `ACTIVE` `ShareGrant` whose `document_id` points at that document transitions to `REVOKED`, and any `AttorneyReview` of that document in a non-terminal status transitions to `CLOSED`. In the same cancellation fan-out, every `Executor` of the subscription in `NOMINATED` or `ACCEPTED` status transitions to `REVOKED`.

**Cascade chain two — supersession.** When a document reaches `EXECUTED` and a prior `EstateDocument` of the same subscription and same `document_type` was already `EXECUTED`, that prior document transitions to `SUPERSEDED`. The superseded document records the newer document's id in `superseded_by_id`, revokes every `ACTIVE` `ShareGrant` pointing at it, and closes any of its non-terminal `AttorneyReview` records.

These cascades are performed by the server automatically as a consequence of the triggering operation; a client never issues a separate request against the child resources.

### 2.9. Nested Reads and Left-to-Right Existence Checking

Many resources are reachable through sub-resource list endpoints that reverse a foreign key — for example, listing a subscription's documents, a document's share grants, or a beneficiary's earmarked assets. For any request whose path contains a resource identifier, the system validates the existence of each path identifier from left to right and rejects the request at the first identifier that does not resolve, returning the not-found error appropriate to that resource type (`ERR_MEMBER_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_QUESTIONNAIRE_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_BENEFICIARY_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`, `ERR_EXECUTOR_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, or `ERR_SHARE_GRANT_NOT_FOUND`, each HTTP 404), before any deeper resource or business rule is considered.

### 2.10. Validation Precedence

When several checks could reject the same request, they are evaluated in a fixed global priority order so that the returned error is deterministic. The order is: (1) authentication of the `X-User-ID` and `X-User-Role` headers (`ERR_UNAUTHENTICATED`); (2) role authorization for the endpoint (`ERR_UNAUTHORIZED`); (3) existence of path-referenced resources, checked left to right (the appropriate not-found error); (4) member ownership of the target resource for member mutations (`ERR_UNAUTHORIZED`); (5) that the target resource is in a state from which the requested transition is legal (`ERR_INVALID_STATE`); (6) that document generation and execution act on an `ACTIVE` subscription (`ERR_SUBSCRIPTION_NOT_ACTIVE`); (7) that the target is not already in a terminal state for operations such as cancel, revoke, respond, decision, and execute (`ERR_ALREADY_TERMINAL`); (8) then the request-body referential checks; and finally the remaining domain-specific business, temporal, fiscal, and concurrency rules described alongside their workflows in §3. Field-shape problems — a missing required field, a malformed value, or an invalid enum member — surface as `ERR_VALIDATION` (HTTP 400). Where a specific ordering matters within a single endpoint, it is called out in that endpoint's workflow narrative.

## 3. Business Logic & Workflows

### 3.1. The Plan Catalog and Membership Foundations

Before any member subscribes, a `PlatformAdmin` populates the plan catalog. Each catalog entry is identified by its `plan_tier`, one of `BASIC`, `PLUS`, or `PREMIER`, and `plan_tier` is unique across catalog rows; subscriptions reference the catalog by tier, not by the catalog's `id`. A catalog entry carries a `base_price_cents` (the annual base price before add-ons and any bundle multiplier, which must be zero or greater), an `included_document_types` list (a non-empty subset of `WILL`, `TRUST`, `POA`, and `HEALTHCARE_DIRECTIVE` that the plan permits generating), a `max_documents` cap (at least 1) on how many non-`REVOKED` documents a subscription on this plan may hold, and an `allows_trust` boolean gating whether `TRUST` documents may be generated. As reference points, the product's standard base prices are $100.00 for `BASIC` (10000 cents), $200.00 for `PLUS` (20000 cents), and $350.00 for `PREMIER` (35000 cents), though the authoritative base for any calculation is whatever `base_price_cents` the catalog row currently holds.

Membership begins with public registration. Anyone may register a `Member` by supplying an `email` (unique across members and used for login and contact), a `full_name` (the member's legal full name), and a `state_code` (a two-uppercase-letter US state of residence that drives state-specific document rules). A registered member and a `PlatformAdmin` may fetch a member record, and both may list that member's subscriptions.

### 3.2. Subscription Signup, Pricing, and Activation

A `Member` opens a subscription by naming the `member_id` of the account holder and a `plan_tier` that must match an existing catalog row — a tier with no catalog entry is rejected with `ERR_PLAN_NOT_FOUND`. The member may also choose a `bundle_type` of `INDIVIDUAL` (the default, covering the member alone) or `COUPLE` (bundling a spouse), supply a `spouse_name` (required when the bundle is `COUPLE`) and an optional `spouse_email`, and turn on the `attorney_support` add-on (default off), which is the paid capability that later enables attorney review of documents.

At creation the subscription's signup price is computed and stored in `price_cents`, and that same amount is placed in `pending_charge_cents` as the outstanding charge awaiting settlement. The signup price is computed as follows: take the catalog `base_price_cents` for the chosen tier, add an attorney add-on of 15000 cents ($150.00) when `attorney_support` is enabled and nothing otherwise, then multiply that sum by the bundle multiplier — 1.0 for an `INDIVIDUAL` bundle and 1.6 for a `COUPLE` bundle — and round the product half-up to whole cents in a single rounding step. A new subscription is created in `PENDING_PAYMENT` status. Before the period is set, the system also verifies the prospective coverage window will not overlap another of the member's non-terminal subscriptions, as described below under activation.

A subscription's outstanding charge is settled only through payment simulation, which a `PlatformAdmin` drives against a nominated `subscription_id` with an `outcome`. When a `PENDING_PAYMENT` subscription receives a `SUCCEEDED` outcome, it transitions to `ACTIVE`: `current_period_start` is set to the logical clock's current instant, `current_period_end` is set to one year (365 days, the term length) after that start and is treated as exclusive, the settled amount in `pending_charge_cents` is added to `paid_to_date_cents`, and `pending_charge_cents` is reset to 0. Activation is refused with `ERR_SUBSCRIPTION_PERIOD_OVERLAP` (HTTP 409) if the resulting half-open window `[current_period_start, current_period_end)` would overlap the coverage window of any other non-terminal subscription belonging to the same member; adjacency is allowed, so a new window whose start equals an existing window's end does not overlap. When a `PENDING_PAYMENT` subscription instead receives a `FAILED` outcome, it transitions to `EXPIRED` and `pending_charge_cents` is cleared to 0. Simulating a payment against a subscription that has no outstanding charge or is otherwise in an incompatible state is rejected with `ERR_PAYMENT_ALREADY_SETTLED` (HTTP 409).

### 3.3. Renewal, Loyalty Pricing, Suspension, and Reinstatement

An `ACTIVE` subscription is renewed by its `Member` in two steps: an initiation that quotes and stakes an outstanding charge, and a settlement that actually charges it. Renewal initiation is permitted only when the subscription is `ACTIVE`, `renewal_pending` is currently false, and the logical clock now falls within the renewal window — that is, now is at or after `current_period_end` minus a 30-day renewal window and at or before `current_period_end` plus a 30-day grace period. Initiating too early (before the 30-day window opens) is rejected with `ERR_RENEWAL_WINDOW_NOT_OPEN` (HTTP 422); initiating too late (after the 30-day grace period has elapsed) is rejected with `ERR_RENEWAL_TOO_LATE` (HTTP 422). On a valid initiation the subscription remains `ACTIVE`, `renewal_pending` is set to true, and `pending_charge_cents` is set to the renewal provisional quote.

The provisional quote is computed exactly like the signup price but using the catalog base price for the current tier at quote time: the current `base_price_cents`, plus the 15000-cent attorney add-on when `attorney_support` is on, multiplied by the bundle multiplier (1.0 individual, 1.6 couple), rounded half-up to whole cents. Crucially, no loyalty discount is applied at quote time — the provisional quote equals the undiscounted list price.

Renewal settlement occurs when a `PlatformAdmin` simulates a payment against a subscription that is `ACTIVE` with `renewal_pending` true. On a `SUCCEEDED` outcome the renewal settles: `renewal_count` is incremented by one, and the amount actually charged — the final charge — is the provisional quote reduced by the loyalty discount, where the discount is determined from the post-increment renewal count. If the incremented count is 1 or 2 the discount is 10 percent; if it is 3 or more the discount is 20 percent. The final charge is therefore the stored `pending_charge_cents` multiplied by one minus the loyalty rate, rounded half-up to whole cents, and it is strictly lower than the provisional quote whenever the loyalty rate is above zero. That final charge is added to `paid_to_date_cents`; `current_period_start` advances to the prior `current_period_end`, `current_period_end` advances to one year (365 days) after the new start, `renewal_pending` returns to false, and `pending_charge_cents` is cleared to 0. The same period-overlap guard that applies at activation applies here at renewal settlement: if the new window would overlap another non-terminal subscription of the member, the settlement is rejected with `ERR_SUBSCRIPTION_PERIOD_OVERLAP`.

If the renewal settlement payment instead `FAILED`, the subscription transitions from `ACTIVE` to `SUSPENDED`. Both `renewal_pending` and `pending_charge_cents` are deliberately retained so that a later successful payment can reinstate the subscription. A `SUSPENDED` subscription that receives a `SUCCEEDED` payment while the logical clock is still at or before `current_period_end` plus the 30-day grace period is reinstated to `ACTIVE`, applying exactly the same settlement side effects as a successful renewal — `renewal_count` incremented, the loyalty-discounted final charge added to `paid_to_date_cents`, the period rolled forward by another 365 days, and `renewal_pending` and `pending_charge_cents` cleared. A `SUSPENDED` subscription that receives a `FAILED` payment after the grace period has elapsed (now beyond `current_period_end` plus 30 days) transitions to `EXPIRED`, clearing `pending_charge_cents`.

A `Member` may change the plan tier of an `ACTIVE` subscription. The request supplies the target `new_plan_tier` and, as required by the optimistic-concurrency rule in §2.7, an `expected_subscription_version`. The subscription must be `ACTIVE`, the supplied version must equal the current `version` (otherwise `ERR_STALE_VERSION`, HTTP 412), and `new_plan_tier` must exist in the catalog (otherwise `ERR_PLAN_NOT_FOUND`). On success the subscription's `plan_tier` becomes the new tier and `price_cents` is recomputed with the signup-price formula for the new tier; the subscription stays `ACTIVE`.

### 3.4. Cancellation and Prorated Refunds

A `Member` may cancel a subscription that is in `PENDING_PAYMENT`, `ACTIVE`, or `SUSPENDED` status; attempting to cancel a subscription already in a terminal state (`CANCELLED` or `EXPIRED`) is rejected with `ERR_ALREADY_TERMINAL`. Cancelling a `PENDING_PAYMENT` subscription simply moves it to `CANCELLED` and clears its `pending_charge_cents`, with no refund because nothing was ever settled.

Cancelling an `ACTIVE` or `SUSPENDED` subscription moves it to `CANCELLED` and issues a prorated refund. The refund is zero when `current_period_end` is null (no paid period exists). Otherwise the refund is the most recently applicable list price — the subscription's `price_cents` — multiplied by the number of remaining days in the coverage window divided by the 365-day term, rounded half-up to whole cents. The remaining days are the number of whole days from now until `current_period_end`, taken as the ceiling of that difference and floored at zero so a fully elapsed period yields no remaining days. The computed refund is then capped so it never exceeds `paid_to_date_cents`. The final refund amount is added to `refunded_cents` and subtracted from `paid_to_date_cents`. Cancellation also triggers cascade chain one described in §2.8: every non-terminal `EstateDocument` is revoked (in turn revoking its share grants and closing its attorney reviews), and every `NOMINATED` or `ACCEPTED` `Executor` is revoked.

### 3.5. The Guided Questionnaire

Each document begins life as a guided questionnaire, or intake. A `Member` starts one against a `subscription_id`, choosing the `document_type` to be produced (`WILL`, `TRUST`, `POA`, or `HEALTHCARE_DIRECTIVE`) and the `state_code` whose rules will apply. At creation the intake is fixed with a `required_field_count` derived from the document type — 5 for a `WILL`, 7 for a `TRUST`, 4 for a `POA`, and 4 for a `HEALTHCARE_DIRECTIVE` — and it starts in `IN_PROGRESS` with an empty `answers` map, an `answered_field_count` of 0, and a `completeness_pct` of 0.

A member submits answers as an `answers` payload that is merged into the intake's accumulated `answers` object. After each merge the system recomputes progress: `answered_field_count` is the count of distinct required keys present in the merged answers, capped at `required_field_count`, and `completeness_pct` is that answered count divided by the required count times 100, rounded half-up to two decimals. While the recomputed completeness is below 100, the intake remains `IN_PROGRESS`. When the recomputed completeness reaches exactly 100 — meaning every required field has been answered — the intake transitions to `COMPLETED`. A completed intake is later frozen: generating a document from it transitions the intake from `COMPLETED` to the terminal `LOCKED` status.

### 3.6. Document Generation and State-Specific Requirements

Once an intake is `COMPLETED`, its owning `Member` generates the actual document by referencing the `questionnaire_id`. Generation copies the intake's `document_type` and `state_code` onto the new `EstateDocument`, copies the owning `subscription_id`, and computes several derived fields, before locking the source intake to `LOCKED`. Generation is subject to several checks. The owning subscription must be `ACTIVE`, or the request is rejected with `ERR_SUBSCRIPTION_NOT_ACTIVE`. The source intake must be `COMPLETED` (its `completeness_pct` at 100), or the request is rejected with `ERR_QUESTIONNAIRE_INCOMPLETE`. The requested `document_type` must be among the plan's `included_document_types`, and a `TRUST` additionally requires the plan's `allows_trust` to be true; otherwise the request is rejected with `ERR_DOCUMENT_TYPE_NOT_IN_PLAN`. Finally, the number of non-`REVOKED` documents already on the subscription must be strictly less than the plan's `max_documents` before generation proceeds, or the request is rejected with `ERR_DOCUMENT_QUOTA_EXCEEDED`.

The new document starts in `GENERATED` status. Its `doc_version` is a sequence number equal to one plus the count of prior `EstateDocuments` sharing the same `subscription_id` and `document_type`, regardless of those priors' status. Two derived legal requirements are computed at creation. A document `requires_notary` when its `document_type` is either `TRUST` or `POA`, or when its `state_code` is `LA`. The `witness_count_required` is a base count for the document type — 2 witnesses for a `WILL`, 0 for a `TRUST`, 1 for a `POA`, and 1 for a `HEALTHCARE_DIRECTIVE` — plus a surcharge of 1 additional witness when the `state_code` is either `LA` or `VT`, and no surcharge otherwise. The document's `witnesses_count` starts at 0, its `execution_date` is null, and its `superseded_by_id` is null until it is superseded.

### 3.7. Attorney Review Loop

A `Member` whose subscription carries the `attorney_support` add-on may submit a `GENERATED` document for attorney review. Submitting requires that add-on: without it, the submission is rejected with `ERR_ATTORNEY_SUPPORT_NOT_ENABLED`. On submission the document transitions from `GENERATED` to `IN_REVIEW`. If the document has no non-terminal `AttorneyReview`, the system creates one against the document's `document_id` in `REQUESTED` status; if the document already has an `AttorneyReview` sitting in `CHANGES_REQUESTED` (a member re-submission after requested changes), that same review is reused and no new review is created.

An `Attorney` advances a review through a single decision endpoint whose `action` is one of `START_REVIEW`, `REQUEST_CHANGES`, or `APPROVE`, with optional `notes`. A `REQUESTED` review moves to `IN_REVIEW` on `START_REVIEW`, recording the acting `X-User-ID` as `attorney_user_id`. From `IN_REVIEW`, a `REQUEST_CHANGES` decision moves the review to `CHANGES_REQUESTED`, stores the supplied `notes`, and drives the owning document back from `IN_REVIEW` to `GENERATED` so the member can revise it — this is the revision loop `GENERATED → IN_REVIEW → GENERATED`. When the member re-submits the revised document (taking it back to `IN_REVIEW`), the attorney may issue `START_REVIEW` again on a `CHANGES_REQUESTED` review to return it to `IN_REVIEW`; that re-review is permitted only when the owning document is itself back in `IN_REVIEW`, forming the re-review loop `IN_REVIEW → CHANGES_REQUESTED → IN_REVIEW`. From `IN_REVIEW`, an `APPROVE` decision moves the review to the terminal `APPROVED` status and drives the owning document from `IN_REVIEW` to `PENDING_EXECUTION`. Should the owning document be revoked or superseded while a review is in `REQUESTED`, `IN_REVIEW`, or `CHANGES_REQUESTED`, that review is automatically moved to the terminal `CLOSED` status. Both a `Member` and an `Attorney` (and a `PlatformAdmin`) may list a document's attorney reviews.

### 3.8. Execution, Notarization, and Supersession

A `Notary` executes a document. Execution is legal from two states: a `GENERATED` document that never went through attorney review, or a `PENDING_EXECUTION` document that an attorney has approved; from any other state the request is rejected with `ERR_INVALID_STATE`, and a terminal document yields `ERR_ALREADY_TERMINAL`. Execution requires that the owning subscription be `ACTIVE` (otherwise `ERR_SUBSCRIPTION_NOT_ACTIVE`). The notary supplies a `witnesses_count`, which must be at least the document's `witness_count_required`; a shortfall is rejected with `ERR_WITNESS_REQUIREMENT_NOT_MET`. Additionally, executing a `WILL` requires that the subscription have at least one non-contingent `Beneficiary`; executing a will with zero non-contingent beneficiaries is rejected with `ERR_NO_BENEFICIARIES`.

On a successful execution the document moves to `EXECUTED`, its `witnesses_count` is set from the payload, and its `execution_date` is set to the logical clock's current instant. Execution then triggers cascade chain two from §2.8: if a prior `EstateDocument` of the same `subscription_id` and same `document_type` was already `EXECUTED`, that prior document transitions to `SUPERSEDED`, records the newly executed document's id in its `superseded_by_id`, revokes every `ACTIVE` `ShareGrant` pointing at it, and closes any of its non-terminal attorney reviews. The sequence `GENERATED → EXECUTED → SUPERSEDED` (or `PENDING_EXECUTION → EXECUTED` for the reviewed path) is thus how a member's newest will or trust replaces its predecessor while cleanly retiring the old document's shares.

### 3.9. Beneficiaries, Assets, and the Estate Summary

A `Member` builds the estate's substance by adding beneficiaries and assets to a subscription. A `Beneficiary` is created against a `subscription_id` with a `full_name`, a `relationship` (one of `SPOUSE`, `CHILD`, `RELATIVE`, `CHARITY`, or `OTHER`), an `allocation_pct` (a residuary share, zero to one hundred, with up to two decimals), and an `is_contingent` flag (default false). Contingent beneficiaries do not consume the primary allocation pool; only non-contingent beneficiaries count toward it. When adding a beneficiary, the sum of `allocation_pct` across all non-contingent beneficiaries including the new one must not exceed 100.00 — exactly 100.00 is allowed, and anything above it is rejected with `ERR_ALLOCATION_EXCEEDED`. Each beneficiary carries an `allocated_cents` field, which is the beneficiary's computed share of the estate and is 0 for contingent beneficiaries.

An `Asset` is created against a `subscription_id` with an `asset_type` (one of `REAL_ESTATE`, `BANK`, `INVESTMENT`, `VEHICLE`, `PERSONAL`, or `BUSINESS`), a `description`, an `estimated_value_cents` (fair value in cents, zero or greater), a `funding_status` (one of `UNFUNDED` — the default — `PENDING`, or `FUNDED`, indicating whether it has been funded into a trust and is thus non-probate), and an optional `assigned_beneficiary_id` earmarking the asset as a specific bequest. An asset's earmark may also be set or changed afterward through the assign-beneficiary operation, which takes a `beneficiary_id` that must reference an existing `Beneficiary` of the same subscription (otherwise `ERR_BENEFICIARY_NOT_FOUND`). An asset that is already `FUNDED` cannot carry a probate earmark: assigning a beneficiary to a funded asset is rejected with `ERR_ASSET_ALREADY_FUNDED`.

The residuary distribution recorded in each beneficiary's `allocated_cents` is recomputed whenever a beneficiary is created and whenever an asset is created or assigned in a way that changes the gross estate value. It is computed as a waterfall over the pool equal to the gross estate value (the sum of every asset's `estimated_value_cents` on the subscription). For each non-contingent (primary) beneficiary, a floor share is computed as the pool multiplied by that beneficiary's `allocation_pct` divided by 100, taking the floor to whole cents. The residual — the pool minus the sum of all floor shares — is then distributed one cent at a time to the primary beneficiaries ordered by `created_at` ascending, cycling through them in that order until the residual is exhausted. Each primary beneficiary's `allocated_cents` is its floor share plus any residual cents it received; contingent beneficiaries receive 0. This ordering (floor-per-beneficiary first, then residual by creation order) is authoritative and must not be replaced by rounding each share independently and summing.

The estate summary is a computed read available to the owning `Member` and to a `PlatformAdmin`. It reports `gross_estate_value_cents`, the sum of `estimated_value_cents` across all of the subscription's assets, and `net_probate_estate_cents`, the sum of `estimated_value_cents` over only those assets that are not `FUNDED` and have no `assigned_beneficiary_id` — the same asset rows, but excluding in-trust (non-probate) assets and assets already earmarked to a beneficiary, which is why the net probate figure is generally smaller than the gross. The summary also reports `total_assigned_value_cents`, the sum of `estimated_value_cents` across assets that carry an `assigned_beneficiary_id`; `total_allocated_cents`, the sum of `allocated_cents` across the subscription's beneficiaries; and `primary_beneficiary_count`, the number of non-contingent beneficiaries.

### 3.10. Executors

A `Member` nominates an `Executor` for a subscription with a `full_name`, an `email`, and a `priority_order` — an integer of at least 1 where 1 designates the primary executor, 2 the first alternate, and so on, unique per subscription. A nominated executor starts in `NOMINATED` status. The member records the executor's response through the respond operation, whose `decision` is either `ACCEPT`, moving the executor from `NOMINATED` to `ACCEPTED`, or `DECLINE`, moving it from `NOMINATED` to the terminal `DECLINED` status. As noted in §3.4, cancelling the owning subscription revokes every executor still in `NOMINATED` or `ACCEPTED` status, moving it to the terminal `REVOKED` status.

### 3.11. Secure Sharing of Executed Documents

Once a document is `EXECUTED`, its owning `Member` may securely share it with a trusted party by creating a `ShareGrant` referencing the document's `document_id`, the `grantee_email` of the person being granted access, a `scope` of `VIEW`, `FULL`, or `EXECUTOR_ACCESS`, and an `expires_at` instant (a logical-clock time, exclusive, at which the grant stops being usable). The target document must exist (otherwise `ERR_DOCUMENT_NOT_FOUND`) and must be in `EXECUTED` status; sharing a document that has not been executed is rejected with `ERR_DOCUMENT_NOT_EXECUTED`. A share grant starts in `ACTIVE` status. To keep overlapping access windows from stacking, a new `ACTIVE` grant for the same `grantee_email` and `document_id` is rejected with `ERR_SHARE_WINDOW_OVERLAP` when its closed validity window from `created_at` to `expires_at` touches or overlaps the window of an existing `ACTIVE` grant for that same grantee and document — adjacency is not allowed here, so even touching windows conflict.

A `Member` may revoke an `ACTIVE` share grant, moving it to the terminal `REVOKED` status; revoking a grant that is already revoked is rejected with `ERR_ALREADY_TERMINAL`. As described in §2.8, share grants are also revoked automatically when their document is revoked (through a subscription cancellation) or superseded (through a newer document's execution).

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including state transitions and payment simulation — return `200 OK`, as do read operations. The clock-set and payment-simulation utilities return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/plan-catalog` | Create a plan catalog entry | PlatformAdmin |
| POST | `/v1/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/v1/_payments/simulate` | Simulate a payment result driving activation, renewal, reinstatement, or expiry | PlatformAdmin |
| POST | `/v1/members` | Register a member account | Anonymous |
| GET | `/v1/members/{id}` | Fetch a member | Member, PlatformAdmin |
| GET | `/v1/members/{id}/subscriptions` | List a member's subscriptions | Member, PlatformAdmin |
| POST | `/v1/subscriptions` | Create a subscription in PENDING_PAYMENT | Member |
| GET | `/v1/subscriptions/{id}` | Fetch a subscription | Member, PlatformAdmin |
| POST | `/v1/subscriptions/{id}/change-plan` | Change plan tier (OCC-guarded); recomputes price | Member |
| POST | `/v1/subscriptions/{id}/cancel` | Cancel the subscription; refund and cascade revocation | Member |
| POST | `/v1/subscriptions/{id}/renew` | Initiate renewal within the renewal window | Member |
| GET | `/v1/subscriptions/{id}/questionnaires` | List a subscription's questionnaires | Member, PlatformAdmin |
| GET | `/v1/subscriptions/{id}/documents` | List a subscription's documents | Member, PlatformAdmin |
| GET | `/v1/subscriptions/{id}/beneficiaries` | List a subscription's beneficiaries | Member, PlatformAdmin |
| GET | `/v1/subscriptions/{id}/assets` | List a subscription's assets | Member, PlatformAdmin |
| GET | `/v1/subscriptions/{id}/executors` | List a subscription's executors | Member, PlatformAdmin |
| GET | `/v1/subscriptions/{id}/estate-summary` | Computed gross/net-probate valuation and allocation totals | Member, PlatformAdmin |
| POST | `/v1/questionnaires` | Start a guided intake for a document type | Member |
| GET | `/v1/questionnaires/{id}` | Fetch a questionnaire | Member, PlatformAdmin |
| POST | `/v1/questionnaires/{id}/answers` | Submit answers; recompute completeness | Member |
| GET | `/v1/questionnaires/{id}/documents` | List documents generated from a questionnaire | Member, PlatformAdmin |
| POST | `/v1/documents` | Generate a document from a completed questionnaire | Member |
| GET | `/v1/documents/{id}` | Fetch a document | Member, PlatformAdmin |
| POST | `/v1/documents/{id}/submit-review` | Send a generated document to attorney review | Member |
| POST | `/v1/documents/{id}/execute` | Notarize, witness, and execute the document | Notary |
| GET | `/v1/documents/{id}/share-grants` | List a document's share grants | Member, PlatformAdmin |
| GET | `/v1/documents/{id}/attorney-reviews` | List a document's attorney reviews | Member, Attorney, PlatformAdmin |
| POST | `/v1/attorney-reviews/{id}/decision` | Advance a review (START_REVIEW / REQUEST_CHANGES / APPROVE) | Attorney |
| POST | `/v1/beneficiaries` | Add a beneficiary; enforce the 100.00% allocation cap | Member |
| GET | `/v1/beneficiaries/{id}` | Fetch a beneficiary | Member, PlatformAdmin |
| GET | `/v1/beneficiaries/{id}/assets` | List assets earmarked to a beneficiary | Member, PlatformAdmin |
| POST | `/v1/assets` | Add an asset to the inventory | Member |
| POST | `/v1/assets/{id}/assign-beneficiary` | Earmark an asset to a beneficiary | Member |
| POST | `/v1/executors` | Nominate an executor | Member |
| POST | `/v1/executors/{id}/respond` | Record the executor's acceptance or declination | Member |
| POST | `/v1/share-grants` | Securely share an executed document | Member |
| POST | `/v1/share-grants/{id}/revoke` | Revoke an active share grant | Member |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 Not Found |
| `ERR_QUESTIONNAIRE_NOT_FOUND` | 404 Not Found |
| `ERR_DOCUMENT_NOT_FOUND` | 404 Not Found |
| `ERR_BENEFICIARY_NOT_FOUND` | 404 Not Found |
| `ERR_ASSET_NOT_FOUND` | 404 Not Found |
| `ERR_EXECUTOR_NOT_FOUND` | 404 Not Found |
| `ERR_REVIEW_NOT_FOUND` | 404 Not Found |
| `ERR_SHARE_GRANT_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SUBSCRIPTION_NOT_ACTIVE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SUBSCRIPTION_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_SHARE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_DOCUMENT_NOT_EXECUTED` | 409 Conflict |
| `ERR_RENEWAL_WINDOW_NOT_OPEN` | 422 Unprocessable Entity |
| `ERR_RENEWAL_TOO_LATE` | 422 Unprocessable Entity |
| `ERR_QUESTIONNAIRE_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_DOCUMENT_TYPE_NOT_IN_PLAN` | 422 Unprocessable Entity |
| `ERR_DOCUMENT_QUOTA_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_ALLOCATION_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_NO_BENEFICIARIES` | 422 Unprocessable Entity |
| `ERR_WITNESS_REQUIREMENT_NOT_MET` | 422 Unprocessable Entity |
| `ERR_ATTORNEY_SUPPORT_NOT_ENABLED` | 422 Unprocessable Entity |
| `ERR_ASSET_ALREADY_FUNDED` | 422 Unprocessable Entity |
| `ERR_PAYMENT_ALREADY_SETTLED` | 409 Conflict |
