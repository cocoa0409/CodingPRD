# Warranty-Claim & Recall Concierge API — Product Requirements Document

## 1. Introduction

The Warranty-Claim & Recall Concierge is a platform that sits between households, the manufacturers of the products they own, and a concierge team that shepherds warranty and safety-recall matters to completion. A household registers the products it owns, subscribes to a service tier, and relies on the platform to notice when one of those products becomes the subject of a manufacturer recall, to file and document warranty or recall claims, and to track the resulting refund or replacement all the way through manufacturer coordination and settlement. The system therefore has to reconcile three distinct concerns at once: a product registry that answers "is this unit still under warranty or caught by a recall?", a claim-adjudication workflow with a documentation revision cycle and a strict separation between the reviewer and the approver of a claim, and a financial settlement engine whose refund, shipping-reimbursement, and concierge-fee arithmetic depends on the household's subscription tier.

This document specifies the REST API that backs that platform. It defines every entity and its lifecycle, the cascading side effects that keep household-level risk scores and subscription usage ledgers consistent as recalls are published and claims move through review, the dual-variant calculations that govern recall exposure and refund amounts, and the role-based access rules — including the segregation-of-duties constraint on claim approval — that determine who may do what. Because the platform reasons about warranty windows and recall effective periods, all time-dependent evaluation is performed against a server-controlled logical clock rather than wall-clock time, so that coverage and eligibility are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts — authentication, response shape, pagination, common resource properties, concurrency, temporal evaluation, monetary precision, cascade consistency, and validation ordering — that apply uniformly across every endpoint described in Section 3 and catalogued in Section 4.

### 2.1. User and Role-Based Access Control

Every request other than the small set of open self-service operations must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the operational capacity in which they act. When either header is missing or malformed on an endpoint that requires authentication, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are present and well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes six roles, spelled exactly as follows: `Anonymous`, `HouseholdOwner`, `HouseholdMember`, `ConciergeAgent`, `ManufacturerAgent`, and `PlatformAdmin`.

- `Anonymous` is an unauthenticated self-service caller and carries no persisted identity; its `X-User-ID` is an opaque token not tied to any stored entity. Anonymous access is limited to creating a household and, when a household has no members yet, creating that household's first `OWNER` member.
- `HouseholdOwner` and `HouseholdMember` are both entity-backed by `Member`: when `X-User-Role` is either of these, `X-User-ID` is the `id` of the acting `Member`, and any ownership check on a household-owned resource (a product, claim, subscription, or recall match) compares that resource's owning household against the household referenced by the acting member's `household_id`. If an entity-backed household principal acts on a resource whose household they do not belong to, the request is rejected with `ERR_NOT_HOUSEHOLD_MEMBER`. `HouseholdOwner` is the single `OWNER`-role member of a household and additionally manages subscriptions, membership, the registry, and match dismissals; `HouseholdMember` is any `ADULT` or `MINOR` member and may register products, file and manage claims, and acknowledge alerts.
- `ConciergeAgent` is an opaque operator identity: `X-User-ID` is a platform-agent identifier not tied to any persisted entity. The server records it where a transition demands — for example, as `reviewed_by_user_id` on a claim when review begins — but never compares it to any entity's `id` for ownership. The concierge triages, reviews, approves or rejects claims, and drives resolutions.
- `ManufacturerAgent` is entity-backed by `Manufacturer`: when `X-User-Role` is `ManufacturerAgent`, `X-User-ID` is the `id` of the acting `Manufacturer`. This role drafts, publishes, and closes recall notices and authorizes RMAs.
- `PlatformAdmin` is an opaque operator identity used for platform provisioning: registering manufacturers, marking subscriptions past-due for billing lapse, and controlling the logical clock.

The precise catalogue of which role may invoke each endpoint appears in Section 4.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Nearly every resource in the system is a first-class, addressable entity that carries a standard set of system-managed fields:

- `id` — a unique, server-minted identifier formatted as a UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first created.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` — an integer that begins at 1 and increments by one on every mutation. It is the basis for optimistic concurrency control described in Section 2.5.

`Household`, `Member`, `Subscription`, `Manufacturer`, `Product`, `RecallNotice`, `RecallMatch`, `Claim`, and `Resolution` all carry the full set above. The one exception is `ClaimDocument`, which is immutable once created: it carries only `id` and `created_at`, and has neither an `updated_at` nor a `version` field.

A resource's `version` and `updated_at` advance not only on direct edits but on every reconciliation the server performs on it. When a household's `recall_exposure_score` or `active_claim_count` is recomputed, when a subscription's `claims_used` is incremented or decremented, when a product's `recall_status` is rolled up from a recall match, or when a claim's `settlement_total_cents` is mirrored from its resolution, that owning resource is mutated — its `updated_at` is refreshed and its `version` is incremented.

### 2.5. Optimistic Concurrency Control

Changing a subscription's tier is guarded by optimistic concurrency control. A plan-change request must carry `expected_subscription_version`, a non-optional field holding the `version` of the target `Subscription` that the client last observed. If that value does not match the subscription's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and the tier is left unchanged. The intent is that a plan change legitimately supersedes the prior tier configuration; if the subscription's version has advanced since the client last read it, a second change carrying a stale `expected_subscription_version` reflects a view that some earlier change already superseded, and the system refuses to let it overwrite a plan it has not observed. A successful plan change sets the new `tier` and increments the subscription's `version` by one. No other endpoint takes a version field; concurrency control applies only to the plan-change operation.

### 2.6. The Logical Clock and Temporal Evaluation

All time-dependent evaluation — warranty expiry, subscription coverage windows, recall effective periods, and the age used in prorated refunds — is performed against a server-controlled **logical clock**, never against wall-clock time. On startup the clock reads exactly `2026-05-01T00:00:00Z`, and until a `PlatformAdmin` advances it, every temporal comparison uses that default; the server never falls back to real time. An administrative clock-set capability moves the clock to a supplied `to_iso8601` instant, and all subsequent warranty, subscription-period, and recall-window evaluations use the new value.

### 2.7. Monetary Precision and Component Rounding

All monetary amounts are stored and returned as integer **cents** (`purchase_price_cents`, `shipping_cost_cents`, `refund_amount_cents`, `shipping_reimbursement_cents`, `concierge_fee_cents`, `settlement_total_cents`). Wherever a percentage or fraction produces a non-integer number of cents, the result is rounded to a whole cent using the round-half-up method (a value exactly halfway between two cents rounds up).

A settlement total is assembled from three parts, and the order of rounding is significant: each component is rounded to whole cents **independently** and only then combined — the system never sums raw products and rounds once at the end. The details of which components are rounded and how they combine are given in Section 3.8.

### 2.8. Cascading Consistency and Derived-Field Reconciliation

Several fields are **derived** rather than directly written, and the system keeps them immediately consistent with the facts they summarize. A household's `recall_exposure_score` and `active_claim_count`, a subscription's `claims_used`, a product's `recall_status`, `warranty_expires_at`, and `coverage_status`, a recall notice's `matched_product_count`, and a claim's `settlement_total_cents` are all reconciled by the server as a side effect of the operations that change their underlying inputs. These reconciliations can chain several levels deep: publishing a recall creates recall matches, each match flips its product's `recall_status`, and each affected household's `recall_exposure_score` is then recomputed — a single publish therefore mutates products and households transitively. Completing a resolution likewise cascades from the resolution to its claim, and for recall claims onward to the recall match, its product, and the household's exposure score. Each entity touched in a cascade is mutated in place, refreshing its `updated_at` and incrementing its `version` per Section 2.4. The concrete cascades are described in Section 3.

### 2.9. Nested Resource Retrieval and Validation Ordering

When a request references resources by id — whether in the URL path or in the request body — the system validates those references left-to-right and rejects the first one that does not resolve to an existing resource with `ERR_NOT_FOUND`. For a path such as a member listing scoped to a household, the container is checked before any child.

Across the whole API, checks are applied in a fixed order of precedence, and the first failing check determines the error returned:

1. **Authentication** — headers present and well-formed, else `ERR_UNAUTHENTICATED`.
2. **Authorization** — the acting role is permitted for the operation, else `ERR_UNAUTHORIZED`.
3. **Household membership** — for entity-backed household roles acting on a household-owned resource, `X-User-ID` must be a member of that resource's household, else `ERR_NOT_HOUSEHOLD_MEMBER`.
4. **Existence** — every referenced id resolves, else `ERR_NOT_FOUND`.
5. **State** — the target resource is in a state from which the requested transition is defined, else `ERR_INVALID_STATE`.
6. **Business rules** — the domain-specific preconditions described in Section 3, each with its own error.
7. **Request well-formedness** — required fields present, enum values in range, integer amounts non-negative, `serial_range_start` not greater than `serial_range_end`, and `period_start` strictly before `period_end`; a malformed body is rejected with `ERR_INVALID_REQUEST`.

Where several business rules guard the same endpoint, their relative order is stated with the workflow in Section 3 so that the earlier-priority rule surfaces its error rather than being masked by a later one.

## 3. Business Logic & Workflows

### 3.1. Households, Members, and Household-Level Risk Exposure

A household is the root of the ownership graph. Anyone may open one through the self-service registration path by supplying a `primary_email` and a `display_name`; an optional `exposure_scoring_mode` selects which recall-exposure algorithm the household uses and defaults to `WEIGHTED` when omitted (the only other accepted value is `COUNT`). A newly created household starts with `status` of `ACTIVE` (the only account status the system uses), a `recall_exposure_score` of 0, and an `active_claim_count` of 0.

Membership is layered on top. Each `Member` belongs to exactly one household via `household_id` and is described by a `full_name`, an `email`, and a `role` that is one of `OWNER`, `ADULT`, or `MINOR`. Exactly one `OWNER` exists per household — the creator. Because a brand-new household has no members, its first member (the `OWNER`) may be created by an `Anonymous` caller; once any member exists, only the existing `HouseholdOwner` may add further members, and those additions are `ADULT` or `MINOR`. Every member is created with `status` of `ACTIVE`. Members can be read individually or listed, and the member list may be narrowed to a single household by supplying a `household_id` filter.

The household's `recall_exposure_score` is a live measure of how much open recall risk the household is carrying, recomputed by the server whenever that risk changes — when a recall publish creates a match, when a match is dismissed, when an acknowledged match is remedied, and when a resolution for a recall claim completes (acknowledging a match, by contrast, does not change the score). The computation looks at every `RecallMatch` whose product belongs to the household and whose `status` is in the **open set** — that is, `MATCHED` or `ACKNOWLEDGED`. Under the `WEIGHTED` mode, the score is the sum of the `severity_weight` of those open matches, where a `LOW` recall weighs 1, a `HIGH` recall weighs 3, and a `CRITICAL` recall weighs 5. Under the `COUNT` mode, the score is simply the number of open matches, ignoring severity entirely. The score is always a whole number.

The household's `active_claim_count` is a second derived figure, recomputed on every claim transition. It counts the household's claims — those filed against any product the household owns — whose `status` is non-terminal, meaning `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `NEEDS_DOCS`, or `APPROVED`. Claims that have reached `REJECTED`, `RESOLVED`, or `WITHDRAWN` no longer count toward it. This differs deliberately from the subscription's `claims_used` ledger described in Section 3.2, which retains rejected and resolved claims.

### 3.2. Subscriptions and Plan Coverage

A `HouseholdOwner` gives a household its service coverage by creating a `Subscription` for it. The request supplies a `tier` — one of `BASIC`, `PLUS`, or `PREMIUM` — together with a `period_start` and `period_end` that bound the coverage period, and an optional `auto_renew` flag that defaults to true. The coverage period is treated as the **half-open** interval running from `period_start` inclusive up to `period_end` exclusive. A new subscription is created with `status` of `ACTIVE` and `claims_used` of 0.

Coverage periods for one household may not collide. When a subscription is created, the system rejects it with `ERR_SUBSCRIPTION_PERIOD_OVERLAP` if the household already has any non-`CANCELLED` subscription whose half-open period overlaps the new one. Because the intervals are half-open, two periods that merely touch at an endpoint — one ending exactly where the next begins — do **not** overlap and are both allowed. This non-overlap guarantee is what lets the system resolve a household's single `ACTIVE` subscription unambiguously: the active subscription is the one whose `status` is `ACTIVE` and whose half-open period contains the current logical-clock instant, and at most one can qualify.

A subscription moves through a small lifecycle. A `PlatformAdmin` may mark an `ACTIVE` subscription `PAST_DUE` to reflect a billing lapse; from `PAST_DUE` the `HouseholdOwner` may reinstate it back to `ACTIVE`. The owner may cancel a subscription from either `ACTIVE` or `PAST_DUE`, moving it to the terminal `CANCELLED` state. Each of these transitions is defined only from the state named, so requesting one from any other state is rejected with `ERR_INVALID_STATE`. A `PAST_DUE` subscription is significant beyond billing: because a claim can be submitted only while the household's subscription is `ACTIVE`, a lapse blocks new submissions (see Section 3.6).

Changing tier is a distinct operation from these lifecycle transitions. A `HouseholdOwner` supplies a new `tier` and the `expected_subscription_version` guard described in Section 2.5; on success the subscription's `tier` is replaced and its `version` increments, and on a version mismatch the change is rejected with `ERR_STALE_VERSION`.

The tier a household holds drives five downstream quantities, and it is worth stating them together even though each is exercised in a different workflow later:

- **Included claims per year** — the ceiling on the subscription's `claims_used`: `BASIC` allows 2, `PLUS` allows 5, and `PREMIUM` allows 20 claims per period.
- **Extended-warranty bonus months** — added to a product's base warranty length: `BASIC` adds 0 months, `PLUS` adds 6 months, and `PREMIUM` adds 12 months.
- **Refund proration** — whether refunds are prorated by remaining warranty: `BASIC` prorates refunds, while `PLUS` and `PREMIUM` refund the full purchase price.
- **Shipping reimbursement** — the fraction of return-shipping cost reimbursed at settlement: `BASIC` reimburses 0%, `PLUS` reimburses 50%, and `PREMIUM` reimburses 100%.
- **Concierge fee** — the fraction of the refund deducted as the platform's fee: `BASIC` charges 10%, `PLUS` charges 5%, and `PREMIUM` charges nothing.

The `claims_used` counter is a conserved ledger tied to claim activity rather than to any single request field. It is incremented by one when a claim is first submitted and decremented by one when a claim is withdrawn before approval (that is, withdrawn out of `SUBMITTED`, `UNDER_REVIEW`, or `NEEDS_DOCS`); it never drops below zero. Re-submitting a claim after a documentation request — the `NEEDS_DOCS` back to `SUBMITTED` step — does not increment it a second time, because the allowance was already consumed on the first submission. Equivalently, `claims_used` equals the number of the household's claims whose `status` is `SUBMITTED`, `UNDER_REVIEW`, `NEEDS_DOCS`, `APPROVED`, `RESOLVED`, or `REJECTED`; note that rejected and resolved claims stay counted, which is why `claims_used` and `active_claim_count` diverge.

### 3.3. The Product Registry and Warranty Coverage

Products live in a household's registry. A `HouseholdOwner` or `HouseholdMember` registers a unit by supplying its `household_id`, the `manufacturer_id` of its maker, a `model_number`, a numeric `serial_number`, the `purchase_date`, the `purchase_price_cents` paid, and the base `warranty_months` offered by the manufacturer. A registered product starts with `registration_status` of `REGISTERED` and `recall_status` of `NONE`, and its computed `warranty_expires_at` and `coverage_status` are derived immediately. Products can be read individually or listed, and the product list may be filtered by `household_id`, by `manufacturer_id`, or both.

Every manufacturer is provisioned by a `PlatformAdmin` with a `name` and a `contact_email`, plus two coordination flags: `coordination_enabled`, defaulting to true, controls whether the manufacturer participates in RMA coordination at all, and `rma_required`, also defaulting to true, controls whether a replacement resolution needs an authorized RMA before it may be dispatched. Manufacturers can be read individually.

**Warranty coverage** is recomputed whenever a product is fetched or evaluated (including at claim submission and refund calculation) against the current logical clock, and it proceeds in two steps. First, the effective warranty length is the base `warranty_months` plus the extended-warranty bonus of the household's `ACTIVE` subscription — 0 additional months for `BASIC`, 6 for `PLUS`, 12 for `PREMIUM` — or plus nothing at all when the household has no active subscription at the current clock. The `warranty_expires_at` is then the `purchase_date` advanced by that effective number of calendar months; when the target month has no matching day, the date is clamped to the last day of that month. Second, the `coverage_status` is decided with the recall override taking precedence: if the product has any open `RecallMatch` — one whose `status` is `MATCHED` or `ACKNOWLEDGED` — the status is `COVERED_BY_RECALL` regardless of dates; otherwise, if the current clock is on or before `warranty_expires_at` the status is `UNDER_WARRANTY` (a product exactly at its expiry instant is still covered); otherwise it is `EXPIRED`. The date comparison is made at whole-day granularity in UTC.

A `HouseholdOwner` may archive a product to soft-remove it from the registry, moving its `registration_status` from `REGISTERED` to the terminal `ARCHIVED`. Archiving is refused with `ERR_INVALID_STATE` if the product is not currently `REGISTERED`, and refused with `ERR_PRODUCT_HAS_ACTIVE_CLAIM` if any claim on the product is still in a non-terminal state — that is, in `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `NEEDS_DOCS`, or `APPROVED`. Note that `recall_status` is an independent system field set by recall-match side effects and is not part of this lifecycle; a product may be `RECALLED` or `REMEDIED` while still `REGISTERED`.

### 3.4. Manufacturers, Recall Notices, and the Publish Cascade

A recall begins as a draft authored by a `ManufacturerAgent`. Drafting a `RecallNotice` supplies the issuing `manufacturer_id`, the `affected_model_number` the recall targets, the inclusive serial bounds `serial_range_start` and `serial_range_end`, a `severity` of `LOW`, `HIGH`, or `CRITICAL`, a prescribed `remedy_type` of `REPAIR`, `REPLACE`, or `REFUND`, and the effective window bounded by `effective_from` and `effective_to`. The effective window is a **closed** interval, inclusive of both `effective_from` and `effective_to`. A new notice is created with `status` of `DRAFT` and `matched_product_count` of 0. Recall notices can be read individually or listed, and the list may be filtered by `manufacturer_id`.

Publishing a draft is the pivotal event. Before it proceeds, the system enforces a temporal exclusivity rule: a publish is rejected with `ERR_RECALL_WINDOW_OVERLAP` if any other already-`PUBLISHED` recall notice from the same `manufacturer_id` and the same `affected_model_number` has a closed effective interval that overlaps this notice's window. Because both intervals are closed, two windows that merely touch at a shared endpoint **do** overlap and the publish is rejected. Publishing a notice that is not in `DRAFT` is instead refused with `ERR_INVALID_STATE`.

When a publish succeeds, it drives a cascade three levels deep. First, for every product that is still `REGISTERED` and whose `manufacturer_id` equals the recall's issuer, whose `model_number` equals the recall's `affected_model_number`, and whose `serial_number` falls within the inclusive serial range (at least `serial_range_start` and at most `serial_range_end`), the system creates a `RecallMatch` with `status` of `MATCHED` and a `severity_weight` snapshotting the recall's severity — 1 for `LOW`, 3 for `HIGH`, 5 for `CRITICAL`. The notice's `matched_product_count` is then set to the number of matches created. Second, each matched product's `recall_status` is set to `RECALLED`. Third, each affected household's `recall_exposure_score` is recomputed over its open matches as described in Section 3.1. The recall notice itself moves to `PUBLISHED`.

A `ManufacturerAgent` closes a `PUBLISHED` recall to move it to the terminal `CLOSED` state; closing one that is not `PUBLISHED` is refused with `ERR_INVALID_STATE`. Closing frees the manufacturer-plus-model interval so that a superseding recall covering an overlapping window may later be published without tripping the overlap rule.

### 3.5. Recall Matches: Safety Alerts and Their Fork

A `RecallMatch` is the junction that ties a published `RecallNotice` to a specific `Product`; it records the `recall_notice_id` that produced it, the `product_id` it flagged, the `severity_weight` snapshotted at match time, and a `status` that begins at `MATCHED`. Matches can be read individually or listed, and the list may be filtered by `recall_notice_id`, by `product_id`, or both. A match's lifecycle is a fork out of `MATCHED` with two divergent branches, plus a remedy path.

A member of the household — either the `HouseholdOwner` or a `HouseholdMember` — acknowledges a match to move it from `MATCHED` to `ACKNOWLEDGED`, signalling the household has seen the safety alert. Acknowledgement carries a cross-entity precondition: the parent `RecallNotice` must still be `PUBLISHED` (the safety notice must be live), and if it is not, the request is rejected with `ERR_RECALL_NOT_LIVE`. Acknowledging does **not** change the household's `recall_exposure_score`, because an `ACKNOWLEDGED` match is still part of the open set that feeds the score.

The first fork branch is dismissal. Only the `HouseholdOwner` may dismiss a match, moving it from `MATCHED` to the terminal `DISMISSED` state. Dismissal removes the match from the open set, so it carries a side effect the acknowledge path does not: the household's `recall_exposure_score` is recomputed, dropping this match's contribution.

The second branch is remedy, the terminal outcome of an acknowledged alert. A `ManufacturerAgent` or a `ConciergeAgent` may remedy a match that is `ACKNOWLEDGED`, moving it to `REMEDIED`. Remedying carries two side effects beyond the status change: the matched product's `recall_status` is set to `REMEDIED`, and the household's `recall_exposure_score` is recomputed — a compensating adjustment that removes the severity weight this match added when it was created. Each of the three transitions is defined only from the state named (`MATCHED` for acknowledge and dismiss, `ACKNOWLEDGED` for remedy), so requesting one from any other state is refused with `ERR_INVALID_STATE`.

### 3.6. Filing a Claim: Documentation and the Review Cycle

A claim is how a household seeks redress for a faulty or recalled product. A `HouseholdOwner` or `HouseholdMember` opens one against a product by supplying the `product_id`, the `filed_by_member_id` of the member creating it, a `claim_type` of either `WARRANTY` (a standard claim) or `RECALL` (one tied to a recall), a `resolution_preference` of `REPLACEMENT` or `REFUND`, and an `issue_description` of the fault. Two inputs are optional: `recall_match_id`, which links the claim to a specific `RecallMatch` and is set only for `RECALL` claims (it defaults to null), and `shipping_cost_cents`, the claimant's return-shipping outlay, which defaults to 0 and is later carried onto the resolution for reimbursement. A new claim is created in `DRAFT`, and creating it recomputes the household's `active_claim_count`. Claims can be read individually or listed, with the list filterable by `product_id`, by `filed_by_member_id`, or by `recall_match_id`.

Supporting documents are attached to a claim as it is prepared. A `HouseholdOwner` or `HouseholdMember` uploads a `ClaimDocument` by supplying a `doc_type` — one of `RECEIPT`, `PHOTO`, `SERIAL_PROOF`, or `OTHER` — and the `file_uri` where the file is stored; each document also records the `claim_id` it supports. Documents are immutable once created and can be read individually or listed by `claim_id`.

Submitting a claim advances it from `DRAFT` to `SUBMITTED` and is the gate where the platform's eligibility rules bite. Beyond the base checks (authentication, authorization, household membership, existence, and the state check that the claim is actually in `DRAFT` — or in `NEEDS_DOCS` for a re-submission — else `ERR_INVALID_STATE`), submission enforces four business preconditions, and where more than one fails the earlier one in this list is the one reported. First, the product must still be `REGISTERED`; submitting against an archived product is rejected with `ERR_PRODUCT_ARCHIVED`. Next, at least one qualifying `ClaimDocument` must exist for the claim, else `ERR_MISSING_DOCUMENTATION`. Then the household's subscription must be `ACTIVE`; a `PAST_DUE` or `CANCELLED` subscription blocks the submission with `ERR_SUBSCRIPTION_NOT_ACTIVE`. Finally, the subscription must have allowance remaining: if `claims_used` has already reached the tier's included-claims ceiling (2 for `BASIC`, 5 for `PLUS`, 20 for `PREMIUM`), the submission is rejected with `ERR_CLAIM_ALLOWANCE_EXCEEDED`; allowance remains only while `claims_used` is strictly below that ceiling. A successful first submission sets the claim to `SUBMITTED`, increments the subscription's `claims_used` by one, and recomputes `active_claim_count`.

The review cycle gives the concierge a way to send a claim back for more evidence. A `ConciergeAgent` begins review of a `SUBMITTED` claim, moving it to `UNDER_REVIEW` and recording their `X-User-ID` as the claim's `reviewed_by_user_id` — the value that anchors the segregation-of-duties rule in Section 3.7. From `UNDER_REVIEW`, the concierge may request more documentation, moving the claim to `NEEDS_DOCS` and opening the revision cycle. The claimant then attaches additional documents and re-submits: the `NEEDS_DOCS` back to `SUBMITTED` step requires that a `ClaimDocument` was added *after* the claim entered `NEEDS_DOCS` (a document created later than the moment of that transition), and if no such fresh document exists the re-submission is rejected with `ERR_MISSING_DOCUMENTATION`. Crucially, this re-submission does **not** increment `claims_used` again — the allowance was consumed on the first submission.

At any point before resolution, the claimant may withdraw the claim. Withdrawal is defined from `SUBMITTED`, `UNDER_REVIEW`, or `NEEDS_DOCS`, and moves the claim to the terminal `WITHDRAWN` state; each of these pre-approval withdrawals decrements the subscription's `claims_used` by one (the compensating half of the allowance ledger) and recomputes `active_claim_count`. Requesting withdrawal from a state where it is not defined is refused with `ERR_INVALID_STATE`.

### 3.7. Claim Adjudication and Segregation of Duties

Adjudication happens only from `UNDER_REVIEW`, and it is governed by a **segregation-of-duties** rule: the concierge who moved a claim into review may not be the one who decides it. When a `ConciergeAgent` approves or rejects a claim, the system compares the acting `X-User-ID` against the claim's `reviewed_by_user_id`; if they are equal the decision is refused with `ERR_SEGREGATION_OF_DUTIES`. A second, distinct concierge must therefore act. Both decisions also require the claim to be in `UNDER_REVIEW`, else `ERR_INVALID_STATE`; when both the state and duties checks would apply, the state check is evaluated first.

Rejection moves the claim to the terminal `REJECTED` state and recomputes the household's `active_claim_count`. A rejected claim continues to count against `claims_used` — the allowance was spent when the claim was submitted and is not refunded on rejection (only a pre-approval withdrawal returns allowance).

Approval moves the claim to `APPROVED` and sets off a cascade. The system creates a `Resolution` for the claim, copying the claim's `resolution_preference` into the resolution's `mode` and starting it in `PENDING`. When the mode is `REFUND`, approval also computes the resolution's `refund_amount_cents` and, from it, the full settlement figure described in Section 3.8, so that the financial outcome is fixed at approval time. Approval then recomputes `active_claim_count`. Because approval is the moment the resolution is born, everything in Section 3.8 flows from it.

The **refund amount** itself is a dual-variant calculation selected by the household's active subscription tier. The tier used at approval is that of the subscription active at the current logical clock; if the clock has advanced past every subscription's period so that none is active, the household's earliest-created subscription whose `status` is `ACTIVE` supplies the tier, and if the household has no such subscription at all, `BASIC` terms apply. For a tier that does not prorate refunds — `PLUS` and `PREMIUM` — the `refund_variant` is `FULL` and the `refund_amount_cents` equals the product's full `purchase_price_cents`, regardless of how much warranty has elapsed. For a tier that prorates — `BASIC` — the `refund_variant` is `PRORATED` and the refund is the purchase price scaled by the fraction of warranty still remaining: the system takes the total warranty span in whole days (from `purchase_date` to `warranty_expires_at`) and the elapsed span in whole days (from `purchase_date` to the current logical clock), computes the remaining days as the total minus the elapsed but never less than zero, and sets `refund_amount_cents` to the `purchase_price_cents` multiplied by remaining days divided by total days, rounded half-up to a whole cent; in the degenerate case where the total warranty span is zero whole days (so the divisor would be zero), `refund_amount_cents` is set to 0. When the resolution mode is `REPLACEMENT`, no refund is computed and `refund_amount_cents` remains null.

### 3.8. Resolutions: Settlement, Replacement, and Manufacturer Coordination

A `Resolution` is the fulfilment record created when a claim is approved. It references its `claim_id`, carries the `mode` copied from the claim (`REPLACEMENT` or `REFUND`), and holds the computed `refund_variant`, `refund_amount_cents`, and the financial fields below. It also copies the claim's shipping outlay into its own `shipping_cost_cents` at creation, and it tracks a `replacement_product_id` (the newly registered replacement unit, null until a replacement is dispatched), an `rma_status` that starts at `NONE`, and a `status` that starts at `PENDING`. Resolutions can be read individually or listed, filterable by `claim_id` or by `replacement_product_id`.

The **settlement total** is assembled from three independently rounded components, and the per-component rounding order is deliberate. The refund component is the `refund_amount_cents` (already a whole cent from Section 3.7). The shipping-reimbursement component, stored as `shipping_reimbursement_cents`, is the resolution's `shipping_cost_cents` multiplied by the tier's shipping-reimbursement fraction — 0% for `BASIC`, 50% for `PLUS`, 100% for `PREMIUM` — rounded half-up to a whole cent on its own. The concierge-fee component, stored as `concierge_fee_cents`, is the `refund_amount_cents` multiplied by the tier's concierge-fee fraction — 10% for `BASIC`, 5% for `PLUS`, 0% for `PREMIUM` — likewise rounded half-up to a whole cent on its own. The `settlement_total_cents` is then the refund component plus the shipping-reimbursement component minus the concierge-fee component. Each piece is rounded before the addition and subtraction, never summed as raw products and rounded once at the end.

Manufacturer coordination governs replacements. For a `REPLACEMENT` resolution, a `ConciergeAgent` first requests an RMA from the manufacturer; this is allowed only when the product's `Manufacturer.coordination_enabled` is true, and otherwise the request is rejected with `ERR_COORDINATION_DISABLED`. A successful request sets the resolution's `rma_status` to `REQUESTED`. The `ManufacturerAgent` then authorizes the RMA, setting `rma_status` to `AUTHORIZED` and recording an `rma_number` on the resolution.

Dispatching moves the resolution from `PENDING` to `DISPATCHED` and is performed by a `ConciergeAgent`. For a `REPLACEMENT`, the request supplies the `replacement_product_id` of the unit being shipped, and dispatching a replacement without one is rejected with `ERR_INVALID_REQUEST`. Dispatch also enforces the coordination gate: when the mode is `REPLACEMENT` and the product's `Manufacturer.rma_required` is true, the resolution's `rma_status` must be `AUTHORIZED`, and if it is not the dispatch is rejected with `ERR_RMA_NOT_AUTHORIZED`. A resolution that is not `PENDING` cannot be dispatched, else `ERR_INVALID_STATE`.

Completing a dispatched resolution is the terminal success path and triggers the second deep cascade in the system. A `ConciergeAgent` completes a `DISPATCHED` resolution, moving it to `COMPLETED`. This sets the linked claim's `status` to `RESOLVED` and mirrors the resolution's `settlement_total_cents` onto the claim's own `settlement_total_cents`. If the claim is a `RECALL` claim, completion cascades further: the linked `RecallMatch` is set to `REMEDIED`, that match's product has its `recall_status` set to `REMEDIED`, and the household's `recall_exposure_score` is recomputed to drop the now-closed match. Finally, `active_claim_count` is recomputed. A resolution may instead be failed by a `ConciergeAgent` from either `PENDING` or `DISPATCHED`, moving it to the terminal `FAILED` state; failing from any other state is refused with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

The table below summarizes every endpoint. Operations that create a new, stand-alone resource (a household, member, subscription, manufacturer, product, recall notice, claim, or claim document) return `201 Created`. Operations that modify or transition an existing resource return `200 OK`. Request bodies, response bodies, and side effects are intentionally not repeated here; they are specified in the Section 3 narratives.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/households` | Create a household account | Anonymous |
| POST | `/households/{id}/members` | Add a member (first OWNER by Anonymous; ADULT/MINOR by owner) | Anonymous, HouseholdOwner |
| GET | `/households/{id}` | Read a household with computed exposure and claim counts | HouseholdOwner, HouseholdMember, ConciergeAgent, ManufacturerAgent, PlatformAdmin |
| GET | `/members/{id}` | Read a member | HouseholdOwner, HouseholdMember, ConciergeAgent, PlatformAdmin |
| GET | `/members` | List members, filterable by household | HouseholdOwner, HouseholdMember, ConciergeAgent, PlatformAdmin |
| POST | `/households/{id}/subscriptions` | Create a subscription for a household | HouseholdOwner |
| POST | `/subscriptions/{id}/change-plan` | Change subscription tier (OCC-guarded) | HouseholdOwner |
| POST | `/subscriptions/{id}/mark-past-due` | Mark a subscription PAST_DUE | PlatformAdmin |
| POST | `/subscriptions/{id}/reinstate` | Reinstate a PAST_DUE subscription | HouseholdOwner |
| POST | `/subscriptions/{id}/cancel` | Cancel a subscription | HouseholdOwner |
| GET | `/subscriptions/{id}` | Read a subscription | HouseholdOwner, HouseholdMember, ConciergeAgent, PlatformAdmin |
| GET | `/subscriptions` | List subscriptions, filterable by household | HouseholdOwner, HouseholdMember, ConciergeAgent, PlatformAdmin |
| POST | `/manufacturers` | Register a manufacturer | PlatformAdmin |
| GET | `/manufacturers/{id}` | Read a manufacturer | HouseholdOwner, HouseholdMember, ConciergeAgent, ManufacturerAgent, PlatformAdmin |
| POST | `/products` | Register a product in a household's registry | HouseholdOwner, HouseholdMember |
| POST | `/products/{id}/archive` | Archive a product | HouseholdOwner |
| GET | `/products/{id}` | Read a product with computed warranty fields | HouseholdOwner, HouseholdMember, ConciergeAgent, ManufacturerAgent, PlatformAdmin |
| GET | `/products` | List products, filterable by household or manufacturer | HouseholdOwner, HouseholdMember, ConciergeAgent, ManufacturerAgent, PlatformAdmin |
| POST | `/recall-notices` | Draft a recall notice | ManufacturerAgent |
| POST | `/recall-notices/{id}/publish` | Publish a recall; match products and cascade exposure | ManufacturerAgent |
| POST | `/recall-notices/{id}/close` | Close a published recall | ManufacturerAgent |
| GET | `/recall-notices/{id}` | Read a recall notice | HouseholdOwner, HouseholdMember, ConciergeAgent, ManufacturerAgent, PlatformAdmin |
| GET | `/recall-notices` | List recall notices, filterable by manufacturer | HouseholdOwner, HouseholdMember, ConciergeAgent, ManufacturerAgent, PlatformAdmin |
| POST | `/recall-matches/{id}/acknowledge` | Acknowledge a safety-alert match | HouseholdOwner, HouseholdMember |
| POST | `/recall-matches/{id}/dismiss` | Dismiss a match (removes it from exposure) | HouseholdOwner |
| POST | `/recall-matches/{id}/remedy` | Mark an acknowledged match remedied | ManufacturerAgent, ConciergeAgent |
| GET | `/recall-matches/{id}` | Read a recall match | HouseholdOwner, HouseholdMember, ConciergeAgent, ManufacturerAgent, PlatformAdmin |
| GET | `/recall-matches` | List recall matches, filterable by notice or product | HouseholdOwner, HouseholdMember, ConciergeAgent, ManufacturerAgent, PlatformAdmin |
| POST | `/claims` | Create a claim in DRAFT | HouseholdOwner, HouseholdMember |
| POST | `/claims/{id}/submit` | Submit a claim for review | HouseholdOwner, HouseholdMember |
| POST | `/claims/{id}/documents` | Attach a supporting document to a claim | HouseholdOwner, HouseholdMember |
| POST | `/claims/{id}/review` | Begin review (records reviewer for SoD) | ConciergeAgent |
| POST | `/claims/{id}/request-docs` | Request more documentation (revision cycle) | ConciergeAgent |
| POST | `/claims/{id}/approve` | Approve a claim; create its resolution | ConciergeAgent |
| POST | `/claims/{id}/reject` | Reject a claim | ConciergeAgent |
| POST | `/claims/{id}/withdraw` | Withdraw a claim before resolution | HouseholdOwner, HouseholdMember |
| GET | `/claims/{id}` | Read a claim | HouseholdOwner, HouseholdMember, ConciergeAgent, ManufacturerAgent, PlatformAdmin |
| GET | `/claims` | List claims, filterable by product, filer, or recall match | HouseholdOwner, HouseholdMember, ConciergeAgent, ManufacturerAgent, PlatformAdmin |
| GET | `/claim-documents/{id}` | Read a claim document | HouseholdOwner, HouseholdMember, ConciergeAgent, PlatformAdmin |
| GET | `/claim-documents` | List claim documents, filterable by claim | HouseholdOwner, HouseholdMember, ConciergeAgent, PlatformAdmin |
| POST | `/resolutions/{id}/request-rma` | Request a manufacturer RMA for a replacement | ConciergeAgent |
| POST | `/resolutions/{id}/authorize-rma` | Authorize the RMA | ManufacturerAgent |
| POST | `/resolutions/{id}/dispatch` | Dispatch the resolution (ship replacement or issue refund) | ConciergeAgent |
| POST | `/resolutions/{id}/complete` | Complete the resolution; cascade claim and recall closure | ConciergeAgent |
| POST | `/resolutions/{id}/fail` | Mark the resolution failed | ConciergeAgent |
| GET | `/resolutions/{id}` | Read a resolution with computed refund/settlement fields | HouseholdOwner, HouseholdMember, ConciergeAgent, ManufacturerAgent, PlatformAdmin |
| GET | `/resolutions` | List resolutions, filterable by claim or replacement product | HouseholdOwner, HouseholdMember, ConciergeAgent, ManufacturerAgent, PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_HOUSEHOLD_MEMBER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PRODUCT_ARCHIVED` | 409 |
| `ERR_PRODUCT_HAS_ACTIVE_CLAIM` | 409 |
| `ERR_RECALL_NOT_LIVE` | 409 |
| `ERR_RECALL_WINDOW_OVERLAP` | 409 |
| `ERR_SUBSCRIPTION_PERIOD_OVERLAP` | 409 |
| `ERR_SUBSCRIPTION_NOT_ACTIVE` | 409 |
| `ERR_MISSING_DOCUMENTATION` | 409 |
| `ERR_CLAIM_ALLOWANCE_EXCEEDED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_COORDINATION_DISABLED` | 409 |
| `ERR_RMA_NOT_AUTHORIZED` | 409 |
| `ERR_STALE_VERSION` | 412 |
