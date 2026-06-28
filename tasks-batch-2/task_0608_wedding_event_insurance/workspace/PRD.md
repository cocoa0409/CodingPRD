# Wedding & Event Insurance API — Product Requirements Document

## 1. Introduction

Couples and event hosts routinely sink large, non-refundable deposits into venues, caterers, florists, and entertainers months before the day itself, only to be exposed when a vendor collapses, a named storm makes landfall, or an unforeseen circumstance forces an outright cancellation. This API powers a specialty insurance product, in the spirit of WedSafe and Markel's event programs, that lets a couple quote and bind tailored coverage against precisely those risks: trip-style cancellation, host liability, liquor liability, scheduled-property protection for rings and attire, and additional-insured certificates that satisfy venue contract requirements.

The platform models the full commercial lifecycle of a single-event or annual event-insurance policy. A policyholder assembles a quote — declaring the covered event window, the expected headcount, and the coverage lines and riders they want — and an underwriting agent prices and binds it. Once premium is paid the policy goes in force, certificates are issued to venues, and mid-term endorsements can adjust the contract. When something goes wrong, the policyholder files a claim that a claims adjuster adjudicates through a documentation-driven revision loop, settling indemnity against the relevant coverage line's remaining limit. Throughout, the carrier maintains an immutable money ledger, enforces named-storm cutoff and force-majeure window rules, and reconciles premium so that the figures a client sees always agree with the underlying coverage and rider lines.

The requirements below define the system's global contracts first — authentication, response envelope, pagination, concurrency, money precision, and cross-cutting consistency rules — and then describe the business workflows in detail. The structural contracts must be honored exactly; the business logic is deliberately narrative and must be assembled by reading §3 as a whole.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. The `X-User-ID` header identifies the acting user, and the `X-User-Role` header declares the operational capacity under which the request is made. If either header is missing or malformed, the request is rejected with `ERR_MISSING_USER_CONTEXT`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognizes exactly four roles, spelled precisely as follows: `PlatformAdmin`, `UnderwritingAgent`, `Policyholder`, and `ClaimsAdjuster`.

A `PlatformAdmin` is an operator who manages reference data — coverage products, vendors, and force-majeure perils — together with the logical clock and the administrative lifecycle steps such as retiring products, flagging or defaulting vendors, activating or expiring perils, and expiring a policy. An `UnderwritingAgent` prices and binds policies, puts paid policies in force, issues and revokes certificates, and drafts, applies, or rejects endorsements. A `ClaimsAdjuster` adjudicates claims, requesting more information, approving, denying, and paying them. A `Policyholder` is the insured party who creates and owns a policy and drives its lifecycle.

All four roles carry an **opaque** identity: in every case `X-User-ID` is an operator or party identifier that is not the primary key of any persisted reference entity. For the `Policyholder` role specifically, the server records the acting `X-User-ID` on the policy at creation time as `policyholder_id`; this captured value is the ownership key for the policy and is never compared against any entity's own `id`. For `PlatformAdmin`, `UnderwritingAgent`, and `ClaimsAdjuster`, the `X-User-ID` is likewise an opaque actor identifier that authorizes the action but is not matched against a stored entity.

Certain policyholder-scoped write operations additionally require that the acting `Policyholder` actually own the target policy — that is, that the request's `X-User-ID` equals the policy's stored `policyholder_id`. This ownership check guards paying the premium, cancelling the policy, resubmitting a claim, and attaching documents to a claim. When a policyholder acts on a policy they do not own, the request is rejected with `ERR_NOT_POLICY_OWNER`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order.

List responses surface the pagination state inside the `meta` object of the envelope through four fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Most resources in this system carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp recording the last modification; it is refreshed on every mutation. The `version` field is an integer that starts at its initial value and increments by one on every mutation to the resource; it is the basis for optimistic concurrency control described in §2.7.

Two entities are immutable append-only records and therefore carry **only** `id` and `created_at` — they have no `updated_at` and no `version`. These are the `ClaimDocument` (documentation attached to a claim) and the `PremiumLedgerEntry` (a money ledger row). Every other entity — `CoverageProduct`, `Vendor`, `ForceMajeureEvent`, `Policy`, `EventProfile`, `Coverage`, `Rider`, `Certificate`, `Endorsement`, and `Claim` — carries the full set of `id`, `created_at`, `updated_at`, and `version`.

All time-based reasoning in the system is performed against a **logical clock** rather than wall-clock time. At server startup the logical clock reads exactly `2026-01-01T00:00:00Z`, and until it is explicitly moved it remains at that default and never falls back to wall-clock time. An administrative test-driving capability advances the clock to a supplied instant; the request carries a `to_iso8601` value and the response reports the new `current_utc`. Bind timestamps, free-look windows, event-window checks, and force-majeure landfall checks all read this logical clock.

### 2.5. Premium Money, Precision, and the Ledger

All monetary values in this system are integer counts of cents; there are no fractional cents and no floating-point money. Field names ending in `_cents` are always whole-number cents. Where a calculation introduces a fraction — for example multiplying a scheduled value by a percentage rate — the rule that produces it states explicitly whether the intermediate result is rounded up to the next whole cent (`ceil`) or down to the whole cent below (`floor`); these directions are part of the calculation contracts in §3 and must be followed exactly, with no additional or substitute rounding.

Every policy owns an append-only money ledger composed of `PremiumLedgerEntry` records. Each entry has an `entry_kind` that is one of `PREMIUM_CHARGE`, `ENDORSEMENT_CHARGE`, `REFUND`, or `INDEMNITY_PAYOUT`, a signed `amount_cents`, and an optional free-text `memo`. By convention, premium and endorsement charges are recorded as positive amounts while refunds and indemnity payouts are recorded as negative amounts relative to the carrier's balance. Ledger entries are written as side effects of binding, applying endorsements, refunding on cancellation, and paying claims; they are never edited or deleted once written.

The premium figures shown on a policy are reconciled derived fields. A policy exposes `base_premium_cents` (the sum of rated coverage-line premium), `rider_premium_cents` (the sum of rider premium), `total_premium_cents` (the reconciled grand total), `premium_earned_cents` (the portion the carrier retains on cancellation or expiry), and `refund_due_cents` (the amount owed back on cancellation). These are kept consistent with the underlying coverage and rider lines as described in §3.

### 2.6. Hierarchical Consistency, Cascades, and Nested Retrieval

The `Policy` is the aggregate root. Its children — `EventProfile`, `Coverage`, `Rider`, `Certificate`, `Endorsement`, `Claim`, and the policy's ledger entries — are addressed beneath it, and a `ClaimDocument` is addressed beneath its owning claim. `Vendor` and `ForceMajeureEvent` are flat top-level peers referenced by the policy's children across the aggregate boundary.

For any request that targets a nested resource, the system validates the path identifiers strictly left to right. The parent policy's existence and operational status are confirmed before any child is located, and a child claim is confirmed before its documents are located. The first identifier in the path that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` before any deeper identifier is examined.

Mutations propagate consistently across the hierarchy. When an operation changes more than one entity — for example, a bind that rates and activates coverage lines, or a cancellation that voids children — every affected entity has its own `updated_at` refreshed and its own `version` incremented, and the precise cascades are detailed in the workflow narratives of §3. The server may also transition a parent automatically when its children collectively satisfy a completion condition, without an explicit client request against the parent; the in-force-to-claimed-out bubble-up described in §3 is one such automatic transition.

### 2.7. Optimistic Concurrency Control on Endorsement Apply

Applying a drafted endorsement is the one write in this system guarded by optimistic concurrency control, because each apply legitimately mutates the policy's premium and advances the policy's `version`. The apply request must carry a non-optional `expected_policy_version` field holding the policy `version` the client last observed. The system compares that value against the target policy's current `version`. If they do not match — which happens when some other endorsement apply has already advanced the policy's version since the client read it — the apply is rejected with `ERR_STALE_POLICY_VERSION` and HTTP status 412. The rejection protects a client from applying a second still-`DRAFT` endorsement on top of a policy whose premium has already moved underneath it without the client having observed the change. No other endpoint takes a version field, and only this endorsement-apply write performs the version comparison.

### 2.8. Parallel Policy State Dimensions

A policy carries two independent state dimensions that evolve separately. The first is its `lifecycle_status`, which moves through `QUOTED`, `BOUND`, `IN_FORCE`, and the terminal states `EXPIRED`, `CANCELLED`, and `CLAIMED_OUT`. The second is its `billing_status`, which moves through `UNPAID`, `PAID`, and the terminal states `REFUNDED` and `EARNED`. The two dimensions are deliberately decoupled: paying the premium advances `billing_status` from `UNPAID` to `PAID` while `lifecycle_status` remains `BOUND`, and only a subsequent action that requires the premium to be `PAID` advances the lifecycle to `IN_FORCE`. The exact preconditions and side effects of each transition are described in §3.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Products, Vendors, and Perils

Before any policy can be assembled, a `PlatformAdmin` populates the catalog of reference data. A **CoverageProduct** is a sellable coverage line identified by a `coverage_type` — one of `CANCELLATION`, `LIABILITY`, or `LIQUOR_LIABILITY` — paired with a `tier` of `BASIC`, `STANDARD`, or `PREMIER`. No two `ACTIVE` products may share the same `coverage_type`. Each product fixes a `base_premium_cents` flat base (which must be zero or greater), a `per_guest_premium_cents` marginal amount added per attendee during rating (zero or greater), and a `coverage_limit_cents` maximum indemnity payable under one claim against the product (strictly greater than zero). It also declares a `deposit_sublimit_pct`, a fraction strictly above 0 and at most 1 that bounds how much of the coverage limit deposit and vendor-failure losses may consume; this sublimit fraction applies to `CANCELLATION` products only. The boolean `liquor_required` flag — defaulting to false — marks products that may only be selected when the event serves alcohol. A product's `status` is system-managed, initialized to `ACTIVE`, and may later be moved to `RETIRED`; retiring a product transitions it from `ACTIVE` to `RETIRED`, and a `RETIRED` product can no longer be added to a policy.

A **Vendor** is a flat top-level record describing a wedding vendor whose failure or deposit loss a policy may protect. A vendor has a `legal_name`, a `category` that is one of `VENUE`, `CATERER`, `FLORIST`, `PHOTOGRAPHER`, `ENTERTAINMENT`, or `OTHER`, and a `deposit_paid_cents` recording the non-refundable deposit the insured has paid that vendor (zero or greater). Either a `PlatformAdmin` or an `UnderwritingAgent` may create a vendor; on creation the vendor's `status` is initialized to `SOLVENT`. A vendor's solvency lifecycle is administrative. Flagging a solvent vendor advances it from `SOLVENT` to `FLAGGED`, and is rejected with `ERR_VENDOR_NOT_SOLVENT` if the vendor is not `SOLVENT`. From `FLAGGED`, a vendor may be defaulted, advancing it to `DEFAULTED`, or cleared, returning it to `SOLVENT`; both the default and clear actions require the vendor to currently be `FLAGGED` and are otherwise rejected with `ERR_VENDOR_NOT_FLAGGED`. Reaching `DEFAULTED` is what later unlocks vendor-failure claim approval against that vendor.

A **ForceMajeureEvent** is a flat top-level record declaring a named-storm or force-majeure peril. It carries a human `peril_name`, a `peril_type` of `NAMED_STORM`, `PANDEMIC`, `WILDFIRE`, or `CIVIL_AUTHORITY`, a binding `cutoff_at` instant, and a `landfall_at` instant marking when the peril actually struck. A peril's `status` is initialized to `WATCH`. Activating a peril advances it from `WATCH` to `ACTIVE` and is rejected with `ERR_PERIL_NOT_WATCH` unless it is currently `WATCH`; expiring a peril advances it from `ACTIVE` to `EXPIRED` and is rejected with `ERR_PERIL_NOT_ACTIVE` unless it is currently `ACTIVE`. Only an `ACTIVE` peril supports a force-majeure payout. The significance of `cutoff_at` and `landfall_at` is taken up in the claim narrative of §3.7.

### 3.2. Quoting a Policy and Describing the Event

A `Policyholder` opens the process by creating a quoted policy. They declare the `policy_form`, which is either `SINGLE_EVENT` or `ANNUAL`; a `SINGLE_EVENT` policy covers exactly one event, while an `ANNUAL` policy may cover many. They may declare `serves_alcohol` (defaulting to false), which gates liquor coverage, and a `free_look_days` count (defaulting to 15, and never negative) that sets the length of the free-look refund window measured from the bind instant. A newly created policy begins with `lifecycle_status` of `QUOTED` and `billing_status` of `UNPAID`, and the acting user's identifier is captured as its `policyholder_id`. The policy's computed money fields — `base_premium_cents`, `rider_premium_cents`, `total_premium_cents`, `premium_earned_cents`, and `refund_due_cents` — all start at zero, and `bind_at` is empty until the policy is bound.

Against a quoted policy, the policyholder adds one or more **event profiles** describing the covered events. An `EventProfile` records an `event_name`, a `venue_vendor_id` referencing the vendor that hosts the event, an `expected_attendance` headcount (at least 1, used in per-guest premium rating), and the covered window bounded by `event_start_at` and `event_end_at`. The window must be coherent: `event_end_at` must be strictly after `event_start_at`, and `event_start_at` must be strictly after the moment the policy was created; a window that violates either condition is rejected with `ERR_INVALID_EVENT_WINDOW`. The venue reference is checked twice over — the `venue_vendor_id` must resolve to an existing vendor, and that vendor's `category` must be `VENUE`; a non-venue reference is rejected with `ERR_VENUE_VENDOR_REQUIRED`. Because a `SINGLE_EVENT` policy covers exactly one event, attempting to add a second event profile to such a policy is rejected with `ERR_SINGLE_EVENT_MULTIPLE_PROFILES`; the same single-event constraint is re-checked at bind time. Event profiles are reverse-reachable as a list beneath the policy, exposing each profile's owning `policy_id`.

### 3.3. Selecting Coverage Lines and Riders

Coverage lines and riders are selected against a quoted policy and define what the premium will ultimately be. Either a `Policyholder` or an `UnderwritingAgent` may add them.

A **Coverage** line is an instance of a chosen product. Its request carries a `coverage_product_id` referencing the `CoverageProduct` and tier selected, and optionally a `protected_vendor_id` referencing the vendor whose deposit or failure this line protects. A coverage line records its owning `policy_id`, and exposes a computed `rated_premium_cents` (zero until rated) and a `consumed_limit_cents` running tally of indemnity already paid against it (also zero initially). Its `status` begins at `SELECTED` and moves to `ACTIVE` at bind, later possibly to `EXHAUSTED` or `VOIDED`. Several rules guard a coverage add. The referenced product must exist, or the request is rejected with `ERR_REFERENCE_NOT_FOUND`. A `RETIRED` product cannot be added and yields `ERR_PRODUCT_RETIRED`. A `protected_vendor_id` may be supplied only when the product's `coverage_type` is `CANCELLATION`; supplying it on any other coverage type is rejected with `ERR_PROTECTED_VENDOR_NOT_ALLOWED`. A `LIQUOR_LIABILITY` coverage may be added only when the policy's `serves_alcohol` is true; otherwise the request is rejected with `ERR_LIQUOR_REQUIRES_ALCOHOL`, and this same alcohol requirement is re-evaluated at bind time. Finally, a policy may hold at most one coverage line per product, identified by its `coverage_type` and `tier` combination; a duplicate add is rejected with `ERR_DUPLICATE_COVERAGE`. Coverage lines are reverse-reachable as a list beneath the policy and are individually retrievable, exposing their `rated_premium_cents` and `consumed_limit_cents`.

A **Rider** schedules a high-value item for protection. Its request carries a `rider_type` of `RINGS`, `ATTIRE`, `GIFTS`, or `SPECIAL_PROPERTY`, and a `scheduled_value_cents` declared insured value (strictly greater than zero). A rider records its owning `policy_id`, exposes a computed `rider_premium_cents` (zero until rated), and has a `status` that begins at `SELECTED`, becomes `ACTIVE` once the policy is bound, and may later become `VOIDED`. Riders are reverse-reachable as a list beneath the policy.

The premium for each rider is set when the rider is rated. The system multiplies the rider's `scheduled_value_cents` by the rider rate of 1.5 percent and rounds that product up to the next whole cent; this rounded-up figure is then clamped so that it is never below a floor of 2,500 cents and never above a ceiling of 50,000 cents. The rounding up to whole cents happens before the clamp, and the clamp itself does not re-round. The clamped result becomes the rider's `rider_premium_cents`.

### 3.4. Binding the Policy and Reconciling Premium

When the quote is complete, an `UnderwritingAgent` binds the policy, transitioning its `lifecycle_status` from `QUOTED` to `BOUND`. Binding is the moment premium is computed and charged, and it is the origin of the deepest cascade in the system. Several preconditions must hold. The policy must currently be `QUOTED`, or the request is rejected with `ERR_POLICY_NOT_QUOTED`. There must be at least one event profile, or `ERR_NO_EVENT_PROFILE` is returned. There must be at least one coverage line in `SELECTED` status, or `ERR_NO_COVERAGE_SELECTED` is returned. If the policy form is `SINGLE_EVENT`, there must be exactly one event profile, or `ERR_SINGLE_EVENT_MULTIPLE_PROFILES` is returned. And if any selected coverage line's product is of type `LIQUOR_LIABILITY`, the policy's `serves_alcohol` must be true, or `ERR_LIQUOR_REQUIRES_ALCOHOL` is returned.

Once the preconditions pass, the bind performs its cascade. Every `SELECTED` coverage line is rated and flipped to `ACTIVE`, every `SELECTED` rider is rated and flipped to `ACTIVE`, the policy's premium fields are reconciled, the policy's `bind_at` is set to the current logical-clock instant, a premium charge is written to the ledger, and the policy's `version` is incremented.

Rating a coverage line computes its premium from the product and the total attendance. The **total attendance** is the sum of `expected_attendance` across all event profiles on the policy — for an annual policy this sums every profile's headcount. A coverage line's `rated_premium_cents` is the product's `base_premium_cents` plus its `per_guest_premium_cents` multiplied by that total attendance. All inputs are already whole cents, so no rounding is required.

Reconciling the policy premium aggregates the rated lines in a pinned order. First, every coverage line is rated; second, every rider is rated; only then are the line subtotals summed. The policy's `base_premium_cents` is the sum of `rated_premium_cents` over coverage lines whose status is `SELECTED` or `ACTIVE` (lines that are `VOIDED` or `EXHAUSTED` are excluded). The policy's `rider_premium_cents` is the sum of `rider_premium_cents` over riders whose status is `SELECTED` or `ACTIVE` (`VOIDED` riders are excluded). The policy's `total_premium_cents` is the sum of those two aggregates. Because each rider line is already a clamped whole-cent figure and each coverage line is already a whole-cent figure, the reconciliation is strictly a sum of already-rounded line subtotals, performed in that pinned order — sum-of-rounded-lines, never round-of-sum. The premium charge written to the ledger at bind is a `PREMIUM_CHARGE` entry whose `amount_cents` equals the positive `total_premium_cents`.

### 3.5. Paying, Activating, and the Money Dimension

Paying the premium advances the policy's `billing_status` from `UNPAID` to `PAID` and is performed by the owning `Policyholder`. The payment request carries an `amount_cents`. Three preconditions apply: the policy's `lifecycle_status` must be `BOUND`, or the request is rejected with `ERR_POLICY_NOT_BOUND`; the policy's `billing_status` must be `UNPAID`, or it is rejected with `ERR_PREMIUM_ALREADY_PAID`; and the submitted `amount_cents` must exactly equal the policy's `total_premium_cents`, or it is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`. A successful payment increments the policy's `version`. Note that payment moves only the billing dimension — the lifecycle remains `BOUND`.

With the premium paid, an `UnderwritingAgent` puts the policy in force, advancing its `lifecycle_status` from `BOUND` to `IN_FORCE`. This step is gated on the billing dimension: the policy must be `BOUND`, or `ERR_POLICY_NOT_BOUND` is returned, and its `billing_status` must be `PAID`, or `ERR_PREMIUM_UNPAID` is returned. Putting the policy in force increments its `version`.

After all of a policy's covered events have ended, a `PlatformAdmin` expires the in-force policy, advancing its `lifecycle_status` from `IN_FORCE` to `EXPIRED`. The policy must currently be `IN_FORCE`, or `ERR_POLICY_NOT_IN_FORCE` is returned, and the current logical clock must be strictly after every event profile's `event_end_at`, or `ERR_EVENT_NOT_ENDED` is returned. Expiry settles the money: the policy's `billing_status` becomes `EARNED`, its `premium_earned_cents` is set equal to its `total_premium_cents` (the full premium is earned), and its `version` increments.

### 3.6. Cancellation, the Free-Look Window, and Refund Settlement

The owning `Policyholder` may cancel a policy whose `lifecycle_status` is either `BOUND` or `IN_FORCE`; a cancel attempt against a policy in any other lifecycle state is rejected with `ERR_POLICY_NOT_CANCELLABLE`. Cancellation is barred while the policy has any open claim — that is, any claim whose status is `SUBMITTED`, `INFO_REQUESTED`, or `APPROVED` — and such an attempt is rejected with `ERR_OPEN_CLAIM_BLOCKS_CANCEL`. A successful cancellation moves the `lifecycle_status` to `CANCELLED`.

Cancellation computes a refund-versus-earned split that turns on the free-look window. The system measures the elapsed time since the policy was bound: the number of whole days since bind is the difference between the current logical clock and the policy's `bind_at`, expressed in seconds, divided by 86,400 seconds per day and taken down to the whole day below. If that number of whole days is less than or equal to the policy's `free_look_days`, the cancellation falls inside the free-look window: the entire premium is refunded, so `refund_due_cents` is set to `total_premium_cents` and `premium_earned_cents` is set to zero. The boundary is inclusive — a cancellation on exactly the free-look day still receives the full refund. If instead the number of whole days exceeds `free_look_days`, the free-look window has passed and a pro-rata earned amount applies: the carrier retains an earned amount equal to the `total_premium_cents` multiplied by the minimum earned ratio of 25 percent, rounded up to the next whole cent, recorded as `premium_earned_cents`; the `refund_due_cents` is then the `total_premium_cents` minus that earned amount, computed exactly with no further rounding.

The cancellation then settles the billing dimension and cascades to children. If `refund_due_cents` is greater than zero, the policy's `billing_status` becomes `REFUNDED` and a `REFUND` ledger entry is appended whose `amount_cents` is the negative of `refund_due_cents`; otherwise the `billing_status` becomes `EARNED`. Regardless of the split, the cascade fans out across the aggregate: every `ACTIVE` coverage line is flipped to `VOIDED`, every `ACTIVE` rider is flipped to `VOIDED`, and every `ISSUED` certificate is flipped to `REVOKED`. The policy's `version` is incremented as part of the cancellation.

### 3.7. Filing and Adjudicating Claims

A `Policyholder` files a **Claim** against a coverage line. The claim request carries a `coverage_id` identifying the coverage line the claim draws against, a `claim_type` of `CANCELLATION`, `VENDOR_FAILURE`, `FORCE_MAJEURE`, or `PROPERTY`, and a `claimed_amount_cents` loss amount (strictly greater than zero). It optionally carries a `vendor_id` — required for a vendor-failure claim — and a `force_majeure_event_id` — required for a force-majeure claim. A claim records its owning `policy_id`, exposes a computed `approved_amount_cents` (zero until approved), tracks a `revision_count` loop counter starting at zero, and has a `status` beginning at `SUBMITTED`. Each referenced foreign key in the body — the coverage, the vendor, the peril — must resolve to an existing entity, or the request is rejected with `ERR_REFERENCE_NOT_FOUND`. Claims are reverse-reachable as a list beneath the policy and individually retrievable, exposing their `approved_amount_cents` and `revision_count`.

Documentation drives adjudication. The owning `Policyholder` attaches a **ClaimDocument** to a claim as an append-only record. Each document has a `doc_type` of `INVOICE`, `RECEIPT`, `POLICE_REPORT`, `VENDOR_CONTRACT`, or `PHOTO`, an opaque `file_uri`, and an optional polymorphic subject. The subject is described by a `subject_kind` discriminator — one of `VENDOR`, `COVERAGE`, or `NONE` — and a `subject_ref` reference identifier that resolves to a vendor when the kind is `VENDOR` and to a coverage line when the kind is `COVERAGE`. A document records its owning `claim_id` and is reverse-reachable as a list beneath its claim.

Adjudication is a cyclic, revision-driven loop. A `ClaimsAdjuster` may request more information on a submitted claim, advancing it from `SUBMITTED` to `INFO_REQUESTED`; this requires the claim to be `SUBMITTED`, otherwise `ERR_CLAIM_NOT_SUBMITTED` is returned, and it increments the claim's `version`. The owning `Policyholder` then resubmits, advancing the claim from `INFO_REQUESTED` back to `SUBMITTED`. Resubmission requires the claim to be `INFO_REQUESTED`, otherwise `ERR_CLAIM_NOT_INFO_REQUESTED` is returned, and it requires that at least one new `ClaimDocument` has been added since the claim last entered `INFO_REQUESTED`, otherwise `ERR_NO_NEW_DOCUMENTATION` is returned. The revision loop is bounded: a claim's `revision_count` may legally climb to a maximum of 3, and resubmission is barred once the count has already reached 3 — the attempt that would push it past the cap is rejected with `ERR_REVISION_CAP_EXCEEDED`. When a resubmission is allowed, the claim's `revision_count` is increased by one and its `version` is incremented.

A `ClaimsAdjuster` resolves a submitted claim by approving or denying it. Denial advances the claim from `SUBMITTED` to `DENIED`, requires the claim to be `SUBMITTED` (otherwise `ERR_CLAIM_NOT_SUBMITTED`), and increments the claim's `version`. Approval, which advances the claim from `SUBMITTED` to `APPROVED`, is the most heavily guarded transition and carries an ordered battery of preconditions described next.

The approval checks are evaluated in this order. The claim must be `SUBMITTED`, or `ERR_CLAIM_NOT_SUBMITTED` is returned. The owning policy's `lifecycle_status` must be `IN_FORCE`, or `ERR_POLICY_NOT_IN_FORCE` is returned. The claim's coverage line must be `ACTIVE`, or `ERR_COVERAGE_NOT_ACTIVE` is returned; a draw against a coverage line that has already reached `EXHAUSTED` is rejected with `ERR_COVERAGE_LIMIT_EXCEEDED`. For a `VENDOR_FAILURE` claim, the referenced vendor must be `DEFAULTED` at approval time, or `ERR_VENDOR_NOT_DEFAULTED` is returned. For a `FORCE_MAJEURE` claim, three temporal and status conditions hold together: the referenced peril must be `ACTIVE`, or `ERR_FORCE_MAJEURE_NOT_COVERED` is returned; the policy's `bind_at` must be strictly before the peril's `cutoff_at` — a policy bound at or after the cutoff is rejected with `ERR_BOUND_AFTER_CUTOFF`, which is the named-storm cutoff rule — and the peril's `landfall_at` must fall within the `event_start_at`-to-`event_end_at` window of some event profile on the policy, or `ERR_LANDFALL_OUTSIDE_WINDOW` is returned. Finally, at least one `ClaimDocument` must be attached to the claim, or `ERR_INSUFFICIENT_DOCUMENTATION` is returned.

Once approval succeeds, the indemnity is computed and the coverage ledger is bumped. The approved indemnity is the smallest of three integer quantities, taken in a pinned evaluation order. First the system computes the **remaining line limit** as the product's `coverage_limit_cents` minus the coverage line's current `consumed_limit_cents`. Second it computes the **sublimit cap**: when the claim type is `VENDOR_FAILURE` or `CANCELLATION`, the cap is the product's `coverage_limit_cents` multiplied by its `deposit_sublimit_pct`, taken down to the whole cent below; for any other claim type, the cap is simply the product's full `coverage_limit_cents` with no deposit sublimit applied. Third it takes the minimum of the `claimed_amount_cents`, the remaining line limit, and the sublimit cap, and records that as the claim's `approved_amount_cents`. The approval then adds the `approved_amount_cents` to the coverage line's `consumed_limit_cents`; if that running total reaches or exceeds the product's `coverage_limit_cents`, the coverage line flips from `ACTIVE` to `EXHAUSTED`. The claim's `version` is incremented. As a bubble-up consequence, if every coverage line on the policy is now in `EXHAUSTED` or `VOIDED` and at least one is `EXHAUSTED`, the policy's `lifecycle_status` advances automatically from `IN_FORCE` to `CLAIMED_OUT`, incrementing the policy's `version`.

Settlement closes the loop. A `ClaimsAdjuster` pays an approved claim, advancing it from `APPROVED` to `PAID`; this requires the claim to be `APPROVED`, otherwise `ERR_CLAIM_NOT_APPROVED` is returned. Paying the claim appends an `INDEMNITY_PAYOUT` ledger entry whose `amount_cents` is the negative of the claim's `approved_amount_cents` and increments the claim's `version`.

### 3.8. Additional-Insured Certificates

A `Policyholder` or an `UnderwritingAgent` requests an additional-insured **Certificate** naming a vendor — typically the venue — as an additional insured on the policy. The certificate request carries a `vendor_id` identifying the vendor to be named and an `additional_insured_name` to print on the certificate. The certificate records its owning `policy_id`, holds a system-minted `certificate_number` (empty until issued), and begins with a `status` of `REQUESTED`. The referenced vendor must exist, or the request is rejected with `ERR_REFERENCE_NOT_FOUND`. Certificates are reverse-reachable as a list beneath the policy.

An `UnderwritingAgent` issues a requested certificate, advancing it from `REQUESTED` to `ISSUED`. Issuance requires the certificate to currently be `REQUESTED`, or `ERR_CERTIFICATE_NOT_REQUESTED` is returned; it requires the policy's `lifecycle_status` to be `BOUND` or `IN_FORCE`, or `ERR_POLICY_NOT_BOUND` is returned; and it requires the policy to hold at least one `ACTIVE` coverage line whose product `coverage_type` is `LIABILITY`, or `ERR_NO_LIABILITY_COVERAGE` is returned. Issuing the certificate mints its `certificate_number` and increments its `version`. An `UnderwritingAgent` may also revoke an issued certificate, advancing it from `ISSUED` to `REVOKED`; revocation requires the certificate to be `ISSUED`, or `ERR_CERTIFICATE_NOT_ISSUED` is returned, and increments its `version`. As noted in §3.6, cancelling the policy also revokes every issued certificate as part of its cascade.

### 3.9. Mid-Term Endorsements

A bound or in-force policy can be adjusted mid-term through an **Endorsement**, drafted by an `UnderwritingAgent`. The draft request carries an `endorsement_type` of `ADD_COVERAGE`, `RAISE_ATTENDANCE`, or `ADD_RIDER`, and a `payload_json` object holding the type-specific change details (for example a coverage product reference for `ADD_COVERAGE`, or a new attendance figure for `RAISE_ATTENDANCE`). The endorsement records its owning `policy_id`, exposes a computed `premium_delta_cents` (zero until applied), and begins with a `status` of `DRAFT`. Endorsements are reverse-reachable as a list beneath the policy.

Applying a draft endorsement advances it from `DRAFT` to `APPLIED` and is the OCC-guarded write described in §2.7. Applying requires the endorsement to be `DRAFT`, or `ERR_ENDORSEMENT_NOT_DRAFT` is returned; it requires the policy's `lifecycle_status` to be `BOUND` or `IN_FORCE`, or `ERR_POLICY_NOT_BOUND` is returned; and it requires the request's `expected_policy_version` to equal the policy's current `version`, failing which the apply is rejected with `ERR_STALE_POLICY_VERSION` at HTTP status 412. On a successful apply, the system carries out the change described by `payload_json` according to the endorsement type, computes the `premium_delta_cents` that change adds, increases the policy's `total_premium_cents` by that delta, appends an `ENDORSEMENT_CHARGE` ledger entry whose `amount_cents` is the positive delta, increments the policy's `version`, and increments the endorsement's `version`.

The premium delta depends on the endorsement type. For an `ADD_COVERAGE` endorsement, the delta is the rated premium of the new coverage line, computed using the current total attendance exactly as a coverage line is rated at bind. For an `ADD_RIDER` endorsement, the delta is the new rider's premium, computed exactly as a rider is rated at bind. For a `RAISE_ATTENDANCE` endorsement, the system first snapshots the old total attendance as the current sum of `expected_attendance` across all event profiles, then sets the named event profile's `expected_attendance` to the new attendance figure, then recomputes the new total attendance as the new sum; the delta is the sum, over all `ACTIVE` coverage lines, of each line's product `per_guest_premium_cents` multiplied by the increase in total attendance (the new total minus the old total). The old total is captured before the mutation and the new total after it. Because applying any endorsement advances the policy's `version`, a second still-`DRAFT` endorsement carrying the version observed before the first apply is operating on a stale view and fails the OCC check. An `UnderwritingAgent` may instead reject a draft endorsement, advancing it from `DRAFT` to `REJECTED`; rejection requires the endorsement to be `DRAFT`, or `ERR_ENDORSEMENT_NOT_DRAFT` is returned, and increments its `version`.

### 3.10. Validation Ordering and General Guards

Across all endpoints, validations are applied in a consistent priority order so that the most fundamental failures surface first. Authentication is checked before anything else: a missing or malformed `X-User-ID` or `X-User-Role` produces `ERR_MISSING_USER_CONTEXT`. Role authorization is checked next, producing `ERR_INSUFFICIENT_PERMISSIONS` when the declared role may not perform the operation. Policyholder ownership is checked after role authorization on the four owner-scoped writes — paying, cancelling, resubmitting a claim, and attaching a claim document — producing `ERR_NOT_POLICY_OWNER` when the acting policyholder does not own the policy. Existence of every path-referenced resource is then confirmed left to right, producing `ERR_NOT_FOUND`, followed by resolution of every body foreign key (such as `coverage_product_id`, `vendor_id`, `venue_vendor_id`, `coverage_id`, and `force_majeure_event_id`), producing `ERR_REFERENCE_NOT_FOUND`. Business-referential checks such as the venue-category and protected-vendor rules come next. Only then are state-transition preconditions evaluated; a transition attempted from a state in which it is not defined and which has no more specific error produces the generic `ERR_INVALID_STATE`. Finally the business-constraint, safety, temporal, and fiscal checks described throughout §3 are applied. Any request whose body is malformed, missing a required field, of the wrong type, or carrying an invalid enum value is rejected with `ERR_INVALID_REQUEST`.

## 4. Endpoint Definitions

Operations that create a new, standalone resource or add a new resource to a collection return a `201 Created` status code. Operations that modify an existing resource — including every state-transition action and the clock-setting capability — return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |
| POST | `/coverage-products` | Create a sellable coverage product | PlatformAdmin |
| GET | `/coverage-products` | List coverage products | PlatformAdmin, UnderwritingAgent, Policyholder, ClaimsAdjuster |
| POST | `/coverage-products/{productId}/retire` | Retire a coverage product | PlatformAdmin |
| POST | `/vendors` | Create a vendor | PlatformAdmin, UnderwritingAgent |
| GET | `/vendors` | List vendors | PlatformAdmin, UnderwritingAgent, Policyholder, ClaimsAdjuster |
| POST | `/vendors/{vendorId}/flag` | Flag a vendor | PlatformAdmin |
| POST | `/vendors/{vendorId}/default` | Declare a vendor in default | PlatformAdmin |
| POST | `/vendors/{vendorId}/clear` | Clear a flagged vendor | PlatformAdmin |
| POST | `/force-majeure-events` | Declare a force-majeure peril | PlatformAdmin |
| GET | `/force-majeure-events` | List force-majeure events | PlatformAdmin, UnderwritingAgent, Policyholder, ClaimsAdjuster |
| POST | `/force-majeure-events/{eventId}/activate` | Activate a peril | PlatformAdmin |
| POST | `/force-majeure-events/{eventId}/expire` | Expire a peril | PlatformAdmin |
| POST | `/policies` | Create a quoted policy | Policyholder |
| GET | `/policies` | List policies | PlatformAdmin, UnderwritingAgent, Policyholder, ClaimsAdjuster |
| GET | `/policies/{id}` | Get a policy | PlatformAdmin, UnderwritingAgent, Policyholder, ClaimsAdjuster |
| POST | `/policies/{id}/bind` | Bind a quoted policy | UnderwritingAgent |
| POST | `/policies/{id}/pay` | Pay the bound premium | Policyholder |
| POST | `/policies/{id}/activate-coverage` | Put a paid policy in force | UnderwritingAgent |
| POST | `/policies/{id}/cancel` | Cancel a bound/in-force policy | Policyholder |
| POST | `/policies/{id}/expire` | Expire an in-force policy | PlatformAdmin |
| GET | `/policies/{id}/ledger` | List the policy's ledger entries | PlatformAdmin, UnderwritingAgent, Policyholder, ClaimsAdjuster |
| POST | `/policies/{id}/event-profiles` | Add an event profile | Policyholder |
| GET | `/policies/{id}/event-profiles` | List event profiles | PlatformAdmin, UnderwritingAgent, Policyholder, ClaimsAdjuster |
| POST | `/policies/{id}/coverages` | Add a coverage line | Policyholder, UnderwritingAgent |
| GET | `/policies/{id}/coverages` | List coverage lines | PlatformAdmin, UnderwritingAgent, Policyholder, ClaimsAdjuster |
| GET | `/policies/{id}/coverages/{coverageId}` | Get a coverage line | PlatformAdmin, UnderwritingAgent, Policyholder, ClaimsAdjuster |
| POST | `/policies/{id}/riders` | Add a scheduled-property rider | Policyholder, UnderwritingAgent |
| GET | `/policies/{id}/riders` | List riders | PlatformAdmin, UnderwritingAgent, Policyholder, ClaimsAdjuster |
| POST | `/policies/{id}/certificates` | Request an additional-insured certificate | Policyholder, UnderwritingAgent |
| GET | `/policies/{id}/certificates` | List certificates | PlatformAdmin, UnderwritingAgent, Policyholder, ClaimsAdjuster |
| POST | `/policies/{id}/certificates/{certificateId}/issue` | Issue a requested certificate | UnderwritingAgent |
| POST | `/policies/{id}/certificates/{certificateId}/revoke` | Revoke an issued certificate | UnderwritingAgent |
| POST | `/policies/{id}/endorsements` | Draft a mid-term endorsement | UnderwritingAgent |
| GET | `/policies/{id}/endorsements` | List endorsements | PlatformAdmin, UnderwritingAgent, Policyholder, ClaimsAdjuster |
| POST | `/policies/{id}/endorsements/{endorsementId}/apply` | Apply a draft endorsement | UnderwritingAgent |
| POST | `/policies/{id}/endorsements/{endorsementId}/reject` | Reject a draft endorsement | UnderwritingAgent |
| POST | `/policies/{id}/claims` | File a claim | Policyholder |
| GET | `/policies/{id}/claims` | List claims | PlatformAdmin, UnderwritingAgent, Policyholder, ClaimsAdjuster |
| GET | `/policies/{id}/claims/{claimId}` | Get a claim | PlatformAdmin, UnderwritingAgent, Policyholder, ClaimsAdjuster |
| POST | `/policies/{id}/claims/{claimId}/documents` | Attach a document to a claim | Policyholder |
| GET | `/policies/{id}/claims/{claimId}/documents` | List a claim's documents | PlatformAdmin, UnderwritingAgent, Policyholder, ClaimsAdjuster |
| POST | `/policies/{id}/claims/{claimId}/request-info` | Request more info on a claim | ClaimsAdjuster |
| POST | `/policies/{id}/claims/{claimId}/resubmit` | Resubmit a claim with new docs | Policyholder |
| POST | `/policies/{id}/claims/{claimId}/approve` | Approve a claim | ClaimsAdjuster |
| POST | `/policies/{id}/claims/{claimId}/deny` | Deny a claim | ClaimsAdjuster |
| POST | `/policies/{id}/claims/{claimId}/pay` | Pay an approved claim | ClaimsAdjuster |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 401 Unauthorized |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_POLICY_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_POLICY_NOT_QUOTED` | 409 Conflict |
| `ERR_POLICY_NOT_BOUND` | 409 Conflict |
| `ERR_POLICY_NOT_IN_FORCE` | 409 Conflict |
| `ERR_POLICY_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_PREMIUM_UNPAID` | 409 Conflict |
| `ERR_PREMIUM_ALREADY_PAID` | 409 Conflict |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_EVENT_NOT_ENDED` | 409 Conflict |
| `ERR_OPEN_CLAIM_BLOCKS_CANCEL` | 409 Conflict |
| `ERR_NO_EVENT_PROFILE` | 422 Unprocessable Entity |
| `ERR_NO_COVERAGE_SELECTED` | 422 Unprocessable Entity |
| `ERR_SINGLE_EVENT_MULTIPLE_PROFILES` | 422 Unprocessable Entity |
| `ERR_INVALID_EVENT_WINDOW` | 422 Unprocessable Entity |
| `ERR_VENUE_VENDOR_REQUIRED` | 422 Unprocessable Entity |
| `ERR_PRODUCT_RETIRED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_COVERAGE` | 409 Conflict |
| `ERR_PROTECTED_VENDOR_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_LIQUOR_REQUIRES_ALCOHOL` | 422 Unprocessable Entity |
| `ERR_CERTIFICATE_NOT_REQUESTED` | 409 Conflict |
| `ERR_CERTIFICATE_NOT_ISSUED` | 409 Conflict |
| `ERR_NO_LIABILITY_COVERAGE` | 422 Unprocessable Entity |
| `ERR_ENDORSEMENT_NOT_DRAFT` | 409 Conflict |
| `ERR_STALE_POLICY_VERSION` | 412 Precondition Failed |
| `ERR_CLAIM_NOT_SUBMITTED` | 409 Conflict |
| `ERR_CLAIM_NOT_INFO_REQUESTED` | 409 Conflict |
| `ERR_CLAIM_NOT_APPROVED` | 409 Conflict |
| `ERR_COVERAGE_NOT_ACTIVE` | 409 Conflict |
| `ERR_INSUFFICIENT_DOCUMENTATION` | 422 Unprocessable Entity |
| `ERR_NO_NEW_DOCUMENTATION` | 422 Unprocessable Entity |
| `ERR_REVISION_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_VENDOR_NOT_DEFAULTED` | 422 Unprocessable Entity |
| `ERR_BOUND_AFTER_CUTOFF` | 422 Unprocessable Entity |
| `ERR_LANDFALL_OUTSIDE_WINDOW` | 422 Unprocessable Entity |
| `ERR_FORCE_MAJEURE_NOT_COVERED` | 422 Unprocessable Entity |
| `ERR_COVERAGE_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_VENDOR_NOT_SOLVENT` | 409 Conflict |
| `ERR_VENDOR_NOT_FLAGGED` | 409 Conflict |
| `ERR_PERIL_NOT_WATCH` | 409 Conflict |
| `ERR_PERIL_NOT_ACTIVE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
