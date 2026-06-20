# Merchant Payment Processing Gateway API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for a Merchant Payment Processing Gateway — a Stripe/Square-style acquiring platform that takes a business from its first underwriting review all the way through card authorization, capture, settlement, funding, refunds, chargeback disputes, rolling reserves, payouts, and year-end tax reporting. The platform sits between merchants and the card networks: it prices each captured transaction, batches captures into daily settlements, withholds a rolling reserve sized to the merchant's risk, releases funds on a delayed funding schedule, and keeps a strict double-account ledger from which every merchant balance is derived.

The hard problems this system solves are reconciliation problems. A merchant's spendable money (its **available balance**) and the money the platform is holding back against future losses (its **reserved balance**) are never stored as free-standing editable numbers; they are always recomputed from an immutable ledger so that no operation can silently drift a balance away from the sum of its postings. Layered on top of that ledger are dual-variant fee pricing (a flat plan versus an interchange-plus plan that discounts at higher monthly volume), a parallel-axis charge lifecycle where authorization and settlement evolve independently, a cyclic dispute-and-representment process, and a set of time-gated sweeps (authorization expiry, funding maturity, reserve release, payout scheduling) that only fire once the platform's logical clock has advanced far enough.

Because money movement must be auditable and deterministic, the platform exposes a controllable logical clock and explicit operator-driven sweeps rather than relying on wall-clock time. This makes the entire funding and reserve timeline reproducible: a platform operator advances the clock, the corresponding maturities fire, and the ledger reflects exactly the postings those maturities imply.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request other than anonymous merchant registration and fee-plan creation must be authenticated with two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the operational capacity under which the request is made. When either header is missing or malformed on a protected endpoint, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes four roles, spelled exactly as follows: `MerchantUser`, `UnderwritingOfficer`, `PlatformOperator`, and `Anonymous`.

A `MerchantUser` is entity-backed by a `Merchant`: when `X-User-Role` is `MerchantUser`, the value of `X-User-ID` is the `id` of the acting `Merchant`. Ownership checks on any resource that references a `Merchant` compare that resource's merchant linkage back to `X-User-ID`. A `MerchantUser` may act only on resources that belong to its own merchant — that is, the `merchant_id` chain of the targeted charge, refund, dispute, settlement batch, reserve entry, ledger entry, payout, tax form, or webhook event must resolve to the merchant named by `X-User-ID`. A `MerchantUser` reaching a resource owned by another merchant is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

A `UnderwritingOfficer` and a `PlatformOperator` are both opaque operator identities: when `X-User-Role` is `UnderwritingOfficer` or `PlatformOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, and the server does not compare it to any entity's `id`. The underwriting officer owns the risk-review lifecycle (approving and rejecting reviews, suspending and reinstating merchants). The platform operator runs the money-movement back office: fee plans, settlement sweeps and settlement, funding, refund settlement and failure, dispute reopen and resolution, reserve releases, payout marking and return, 1099-K generation, webhook emission, and clock control. `Anonymous` is the unauthenticated caller and is permitted exactly one action — registering a new merchant — which carries no authentication headers.

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

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_` followed by 20 random alphanumeric characters.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits; it is taken from real wall-clock time at the moment the response is built and is **not** governed by the logical clock of §3.12.
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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. A supplied `limit` outside that range is not rejected but clamped into it: a value below 1 is treated as 1 and a value above 100 is treated as 100. The `offset` parameter is the number of items to skip from the front of the result set and defaults to 0; a negative `offset` is clamped to 0. A `limit` or `offset` that is present but not parseable as an integer is rejected with `ERR_VALIDATION` (HTTP 400).

When a list endpoint accepts a filter whose values come from one of the enumerations of §2.8, a supplied filter value outside that enumeration is rejected with `ERR_INVALID_ENUM` (HTTP 422); this applies to `onboarding_status`, `auth_status`, `settlement_status`, `batch_status`, `payout_status`, `reserve_status`, `account`, and `event_type`. The ledger `entry_type` and `source_type` filters and the `fee_plan_id`, `merchant_id`, and `settlement_batch_id` filters are matched literally without enum validation, so an unrecognized value for one of those simply matches no records rather than raising an error. The 1099-K `tax_year` filter must be an integer-parseable string, otherwise the request is rejected with `ERR_VALIDATION` (HTTP 400). Unless an endpoint states otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order; because `created_at` may collide under the logical clock, ordering is broken deterministically by a monotonic per-record insertion sequence so that the effective order is the order in which records were created. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the size of the full filtered result set before pagination and `has_more` is true exactly when `offset` plus the number of items in this page is strictly less than `total_count`.

### 2.4. Common Resource Properties and Versioning

Most entities are full first-class resources and carry a standard system-managed property set: an `id` that is a server-minted UUID (a standard random version-4 UUID string) with no type prefix; a `created_at` ISO 8601 UTC timestamp with three fractional digits set once at creation; an `updated_at` ISO 8601 UTC timestamp that is refreshed on every mutation; and a `version` integer that starts at 1 and increments by one on every mutation of the resource. Both `created_at` and `updated_at` are read from the logical clock of §3.12 (which defaults to real wall-clock time at process boot until an operator sets or advances it), so under operator clock control these timestamps move with the logical clock rather than with real time. The merchant, fee plan, charge, refund, dispute, settlement batch, payout, reserve entry, 1099-K form, and risk review all carry this full property set.

Two entities are append-only audit records and deliberately carry **only** `id` and `created_at` — they have no `updated_at` and no `version`: the `LedgerEntry` and the `WebhookEvent`. Once written, a ledger posting is never modified, and a webhook event is never mutated.

The `version` field is the lever for optimistic concurrency control described in §2.10. Whenever a mutation changes any persisted field of a resource — including the recomputation of a merchant's derived balances when a ledger posting lands — that mutation refreshes `updated_at` and increments `version` on the affected resource.

### 2.5. The Ledger as Single Source of Truth

The platform keeps a single immutable ledger, and every merchant balance is a projection of it rather than an independently mutable counter. Each `LedgerEntry` records the `merchant_id` it affects, the `account` it posts to (either `AVAILABLE` or `RESERVE`), a signed `amount_cents` (a positive value credits the merchant, a negative value debits the merchant), an `entry_type` describing the accounting category, and a polymorphic `source_type` plus `source_id` pointing back at whichever entity generated it. The `source_id` is null when `source_type` is `MANUAL`; otherwise it resolves against the entity kind named by `source_type`, which is one of `CHARGE`, `REFUND`, `DISPUTE`, `SETTLEMENT_BATCH`, `RESERVE_ENTRY`, `PAYOUT`, or `MANUAL`. The `entry_type` is one of `FUNDING`, `FEE`, `REFUND`, `CHARGEBACK`, `CHARGEBACK_REVERSAL`, `RESERVE_HOLD`, `RESERVE_RELEASE`, `PAYOUT`, `PAYOUT_RETURN`, or `ADJUSTMENT`. Note that the `FEE` entry type is posted only for the non-refundable chargeback fee at the moment a dispute opens; ordinary processing fees are never posted as a standalone `FEE` entry because they are netted inside the `FUNDING` posting at funding time, which keeps them from being counted twice.

A merchant's `available_balance_cents` is the signed sum of `amount_cents` across all of that merchant's ledger entries whose `account` is `AVAILABLE`. A merchant's `reserved_balance_cents` is the signed sum of `amount_cents` across all of that merchant's ledger entries whose `account` is `RESERVE`. The available balance may legitimately go negative (for example, after a chargeback debit larger than the spendable balance). The reserved balance is always at least zero by construction, because every reserve release is bounded by the reserve holds that preceded it. These two derived fields on the merchant are recomputed from the ledger every time a posting is made; capture is the one money-event that posts nothing to the ledger, and therefore capture never moves a balance.

All amounts in this system are integer cents. There are no fractional cents anywhere in stored fields or response bodies. Where a calculation needs to convert a basis-points rate into cents, the result is rounded using the round-half-up convention, as detailed per calculation in §3. Basis points are hundredths of a percent, so a rate expressed in basis points is applied by multiplying the base amount by the rate and dividing by 10000.

### 2.6. Hierarchical Consistency and Cascading Effects

Several operations mutate more than one entity in a single action, and the secondary effects are as much a part of the contract as the primary state change. Settling a batch, for example, does not merely flip the batch's own status; it advances each batched charge, pins the batch's financial aggregates, creates a reserve hold, posts to the ledger, and bumps the merchant's version. Whenever a settlement, funding, refund settlement, dispute posting, reserve release, or payout movement writes a ledger entry, the owning merchant's `available_balance_cents` and/or `reserved_balance_cents` are recomputed immediately, and that recomputation is itself a merchant mutation that refreshes `updated_at` and increments the merchant's `version`. The precise cascades are described inline with each workflow in §3.

### 2.7. Nested Resource Retrieval and Path Validation

Many paths address a resource nested under a parent — a risk review under a merchant, refunds under a charge, reserve entries under a settlement batch. For any such request, the server validates each path identifier left to right and rejects the first one that does not resolve to an existing resource with `ERR_NOT_FOUND` (HTTP 404). For instance, a request for a risk-review action under a non-existent merchant fails on the merchant identifier before the risk review is ever examined. Beyond path identifiers, any foreign-key field carried in a request body — such as `fee_plan_id` at merchant registration, or the `charge_id` and `merchant_id` linkages on creation endpoints — must reference an existing resource; a dangling body foreign key is rejected with `ERR_FK_NOT_FOUND` (HTTP 404).

### 2.8. Request Validation and Enumerations

A request whose body is malformed, missing a required field, or carries a value of the wrong scalar type is rejected with `ERR_VALIDATION` (HTTP 400). A request that supplies an enumerated field with a value outside its permitted set is rejected with `ERR_INVALID_ENUM` (HTTP 422). The enumerations enforced by the system are: a merchant's `onboarding_status` is one of `PENDING_REVIEW`, `APPROVED`, `REJECTED`, or `SUSPENDED`; a merchant's `risk_band` (and a risk review's `assigned_risk_band`) is one of `LOW`, `MEDIUM`, or `HIGH`; a merchant's `payout_method` is either `BANK_ACCOUNT` or `DEBIT_CARD`; a fee plan's `pricing_model` is either `FLAT` or `INTERCHANGE_PLUS`; a charge's `auth_status` is one of `AUTHORIZED`, `CAPTURED`, `VOIDED`, or `EXPIRED`; a charge's `settlement_status` is one of `PENDING`, `BATCHED`, `SETTLED`, or `REVERSED`; a refund's `refund_status` is one of `PENDING`, `SETTLED`, or `FAILED`; a refund's `reason` is one of `REQUESTED_BY_CUSTOMER`, `DUPLICATE`, or `FRAUDULENT`; a dispute's `dispute_status` is one of `OPEN`, `UNDER_REVIEW`, `REPRESENTED`, `WON`, `LOST`, or `ACCEPTED`; a batch's `batch_status` is one of `OPEN`, `SETTLED`, or `FUNDED`; a payout's `payout_status` is one of `REQUESTED`, `PAID`, or `RETURNED`; a reserve entry's `reserve_status` is either `HELD` or `RELEASED`; a risk review's `decision` is one of `OPEN`, `APPROVED`, or `REJECTED`; a ledger entry's `account` is `AVAILABLE` or `RESERVE`; and a webhook event's `event_type` is one of `CHARGE_CAPTURED`, `REFUND_SETTLED`, `DISPUTE_OPENED`, `DISPUTE_RESOLVED`, `BATCH_FUNDED`, `PAYOUT_PAID`, or `RESERVE_RELEASED`.

### 2.9. State Transition Discipline and Validation Priority

Every action endpoint that drives a state machine first checks that the target resource is in a state from which the requested transition is defined; if it is not, the request is rejected with `ERR_INVALID_STATE` (HTTP 409). When several checks could fire on one request, they are evaluated in a fixed priority order so that the failure reported is deterministic. The global ordering is: first the authentication of the request headers (`ERR_UNAUTHENTICATED`); then whether the acting role is permitted at all (`ERR_FORBIDDEN_ROLE`); then, for a `MerchantUser`, whether it owns the targeted resource (`ERR_NOT_RESOURCE_OWNER`); then left-to-right existence of every path identifier (`ERR_NOT_FOUND`); then existence of body foreign keys (`ERR_FK_NOT_FOUND`); then that the transition is legal from the current state (`ERR_INVALID_STATE`); and only after all of those do the domain-specific business rules described in §3 apply. The ownership-before-path-existence ordering applies when ownership is determinable directly from the path — that is, when the path names a merchant identifier; for a resource addressed directly by its own identifier (a charge, refund, dispute, settlement batch, payout, or 1099-K form addressed at the top level), ownership can only be evaluated after the resource has been loaded, so for those endpoints the resource's own existence is resolved first (`ERR_NOT_FOUND` when it is absent) and the `MerchantUser` ownership check (`ERR_NOT_RESOURCE_OWNER`) is applied second against the loaded resource's merchant linkage. Request-body validation — a malformed body, a missing required field, or a wrong-typed scalar (`ERR_VALIDATION`), and an enumerated value outside its permitted set (`ERR_INVALID_ENUM`) — is applied after authentication, role, ownership, and path-identifier existence have all passed, but before body foreign-key existence (`ERR_FK_NOT_FOUND`), before the state-transition legality check (`ERR_INVALID_STATE`), and before the domain business rules. Where two business rules guard the same endpoint, their relative ordering is stated within the workflow that owns them in §3.

### 2.10. Optimistic Concurrency on Batch Settlement

Settling a batch is the one write in this system that is guarded by optimistic concurrency control against the merchant. The settle action both reads the merchant's reserve terms (its reserve rate and funding delay) to price the reserve hold and bumps the merchant's `version` as a side effect. To make sure the operator is settling against the reserve terms it actually observed, settling a batch requires the request to carry `expected_merchant_version`, the merchant `version` the operator last read. If the merchant's current `version` no longer equals the supplied `expected_merchant_version` — because the merchant was re-underwritten or otherwise mutated since the operator read it — the settle is rejected with `ERR_STALE_MERCHANT_VERSION` (HTTP 412), preventing the batch from settling against out-of-date reserve terms. No other endpoint takes a version field, and no other endpoint performs this stale-version check.

## 3. Business Logic & Workflows

### 3.1. Fee Plans: Pricing the Platform

Before any merchant can process money, a `PlatformOperator` defines the **fee plans** that price captures. Fee-plan creation is exempt from the mandatory-authentication rule of §2.1: a request to create a fee plan that carries no `X-User-ID`/`X-User-Role` headers is accepted. When authentication headers are supplied on this endpoint, however, they are still enforced — a present-but-unrecognized role is rejected with `ERR_UNAUTHENTICATED` (HTTP 401), and a recognized role other than `PlatformOperator` is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). A fee plan carries a human-readable `name`, a `pricing_model`, and a `chargeback_fee_cents` — the non-refundable fee debited from a merchant when a dispute opens, defaulting to 1500 cents when not supplied. The pricing model determines which fields the plan must carry, and a plan that omits the fields its model requires is rejected with `ERR_FEE_PLAN_INCOMPLETE` (HTTP 422).

A `FLAT` plan prices every capture with a single percentage component plus a fixed component, and therefore must provide both `flat_pct_bps` (the percentage in basis points, where 290 means 2.90%) and `flat_fixed_cents` (the per-transaction fixed amount in cents). An `INTERCHANGE_PLUS` plan passes the network interchange cost straight through and adds a platform markup on top, and therefore must provide its markup fields: `markup_pct_bps` (the platform markup in basis points applied to the captured amount) and `markup_fixed_cents` (the platform per-transaction fixed markup in cents). An interchange-plus plan additionally supports a monthly-volume discount tier through `volume_tier_threshold_cents` and `discounted_markup_pct_bps`: once the merchant's settled volume in the current calendar month strictly exceeds the threshold, subsequent captures that month are marked up at the discounted rate instead. All four of `markup_pct_bps`, `markup_fixed_cents`, `volume_tier_threshold_cents`, and `discounted_markup_pct_bps` default to 0, as do `flat_pct_bps` and `flat_fixed_cents`; completeness is judged on the fields the chosen model needs, not on whether a value happens to be zero.

### 3.2. Merchant Onboarding and Underwriting

Onboarding begins anonymously. Registration is unauthenticated and carries no role gate at all: any authentication headers that happen to be supplied are ignored rather than validated, so registration is never rejected for an authentication or role reason. A prospective merchant registers by supplying its `legal_name`, its `mcc` (a Merchant Category Code that must be exactly four ASCII digits), the `fee_plan_id` of the plan it will price under, and its self-declared `requested_monthly_volume_cents` (the expected monthly processing volume in cents, which must be at least 0). The registrant may also choose a `payout_method`, either `BANK_ACCOUNT` (the default) or `DEBIT_CARD`. Registration creates the merchant with `onboarding_status` set to `PENDING_REVIEW` and, as a side effect, opens an associated risk review with its `decision` set to `OPEN`. At registration the merchant's `risk_band` is unset, its `reserve_rate_bps` and `available_balance_cents` and `reserved_balance_cents` are 0, and its `funding_delay_days` is 2 until underwriting pins the real values.

Underwriting is owned by the `UnderwritingOfficer`, who reads the open risk review, records free-text `notes` if desired, and either approves or rejects it. The approve and reject actions both address the review through a two-part path naming the merchant and then the review identifier `rid`, so the review is resolved within the context of its merchant. Each risk review carries the `merchant_id` it concerns, its `decision`, the `assigned_risk_band` the officer chooses on approval (which stays null while the review is `OPEN`), and the `notes`. Approval drives the merchant from `PENDING_REVIEW` to `APPROVED`: it is permitted only while the merchant's `onboarding_status` is `PENDING_REVIEW` and an `OPEN` risk review exists for the merchant, otherwise the request is rejected with `ERR_INVALID_STATE`. On approval, the officer supplies an `assigned_risk_band`; the system sets the merchant's `risk_band` to that value, pins the merchant's `reserve_rate_bps` from the risk band (a `LOW` band carries a 0 basis-point reserve, a `MEDIUM` band carries 500 basis points, i.e. 5%, and a `HIGH` band carries 1000 basis points, i.e. 10%), pins the merchant's `funding_delay_days` from the risk band (a `LOW` band funds on a one-day delay, while `MEDIUM` and `HIGH` bands both fund on a two-day delay), sets the risk review's `decision` to `APPROVED`, and increments the merchant's `version` by one.

A risk-policy guard protects approval: the high-risk Merchant Category Codes are 5933, 5967, 7995, and 5122. When the merchant's `mcc` is one of these high-risk codes, the officer must assign the `HIGH` band; approving such a merchant with an `assigned_risk_band` other than `HIGH` is rejected with `ERR_RISK_BAND_POLICY_VIOLATION` (HTTP 422). This policy check fires only on the approve action.

Rejection drives the merchant from `PENDING_REVIEW` to `REJECTED`, which is a terminal onboarding state; it is permitted only while the merchant is `PENDING_REVIEW` with an `OPEN` risk review present, sets the risk review's `decision` to `REJECTED`, and increments the merchant's `version` by one. After approval, an officer may suspend a merchant, driving it from `APPROVED` to `SUSPENDED` (permitted only from `APPROVED`), and may later reinstate it, driving it from `SUSPENDED` back to `APPROVED` (permitted only from `SUSPENDED`); each of suspension and reinstatement increments the merchant's `version` by one. Suspension blocks new authorizations and captures but does not block refunds or dispute handling. Both the suspend and reinstate actions, like approval and rejection, accept optional `notes`.

### 3.3. Authorizing, Capturing, and Voiding Charges

A `MerchantUser` initiates payment by authorizing a charge against a card. Authorization requires that the merchant's `onboarding_status` be `APPROVED`; an authorization (and likewise a capture or a payout request) attempted while the merchant is `PENDING_REVIEW`, `REJECTED`, or `SUSPENDED` is rejected with `ERR_MERCHANT_NOT_APPROVED` (HTTP 409). The merchant user supplies the `auth_amount_cents` (the amount held against the card, which must be at least 1) and the `card_last4` (exactly four ASCII digits, kept for display only). The new charge belongs to the merchant via its `merchant_id` and begins life on two independent axes: its `auth_status` is `AUTHORIZED` and its `settlement_status` is `PENDING`. Its `captured_amount_cents`, `refunded_amount_cents`, and `processing_fee_cents` all start at 0, and its `settlement_batch_id` is null until a sweep claims it.

Capturing the charge advances the authorization axis from `AUTHORIZED` to `CAPTURED` while leaving the settlement axis at `PENDING`. Capture is permitted only when the charge's `auth_status` is `AUTHORIZED` and the merchant is `APPROVED`. The merchant user names the capture `amount_cents`, which must be at least 1 and at most the charge's `auth_amount_cents`; a capture amount below 1 or above the authorized amount is rejected with `ERR_CAPTURE_EXCEEDS_AUTH` (HTTP 422). On a successful capture the charge's `captured_amount_cents` is set to the captured amount, and the `processing_fee_cents` is computed once (see §3.4) and never recomputed; this fee is non-refundable. Capture writes no ledger entry — the processing fee is deducted later, at funding, inside the net funding amount, so the fee is counted exactly once.

A charge that has not been captured can be voided, driving `auth_status` from `AUTHORIZED` to the terminal `VOIDED` while the settlement axis remains `PENDING`; voiding is permitted only while `auth_status` is `AUTHORIZED` and posts nothing to the ledger. Separately, an authorization that is never captured expires: when the logical clock's date reaches or passes the charge's creation date plus the seven-day authorization hold window, the authorization-expiry sweep (run as part of advancing the clock) moves the charge's `auth_status` from `AUTHORIZED` to the terminal `EXPIRED`, again with the settlement axis untouched and no ledger postings. Charges are readable individually and as a filtered list; the list supports filtering by `merchant_id`, `settlement_batch_id`, `auth_status`, and `settlement_status`.

### 3.4. Pricing a Capture: the Processing Fee Calculation

The `processing_fee_cents` recorded at capture is computed from the merchant's active fee plan, and the formula depends on the plan's `pricing_model`. In both variants the base is the capture amount being processed, and all amounts are integer cents.

Under a `FLAT` plan, the percentage component is the capture amount multiplied by `flat_pct_bps` divided by 10000, rounded half-up to whole cents; the fee is that rounded percentage component plus `flat_fixed_cents`. There is no interchange passthrough and no volume tier under a flat plan.

Under an `INTERCHANGE_PLUS` plan, the fee is the sum of an interchange passthrough and a platform markup. The interchange passthrough is the capture amount multiplied by the interchange rate of 165 basis points divided by 10000, rounded half-up to whole cents, plus a fixed interchange amount of 10 cents. The platform markup uses an effective markup rate that depends on the merchant's settled volume so far this calendar month: if the merchant's prior settled volume in the current calendar month — defined as the sum of `captured_amount_cents` over this merchant's charges whose `settlement_status` is `SETTLED` and whose settle posting fell in the current calendar month, excluding the charge now being captured — strictly exceeds the plan's `volume_tier_threshold_cents`, then the effective markup rate is `discounted_markup_pct_bps`; otherwise it is `markup_pct_bps`. The markup component is the capture amount multiplied by that effective markup rate divided by 10000, rounded half-up to whole cents, plus `markup_fixed_cents`. The total interchange-plus fee is the interchange passthrough plus the markup component.

The rounding discipline is round-then-sum: each percentage component is rounded half-up to whole cents on its own before the components are added together, and the resulting fee is pinned onto the charge at capture. Because the two pricing models differ, an identical capture amount yields a different fee under a flat plan than under an interchange-plus plan.

### 3.5. Refunds

A `MerchantUser` may refund all or part of a captured charge by naming the refund `amount_cents` (at least 1) and an optional `reason` (`REQUESTED_BY_CUSTOMER` by default, or `DUPLICATE`, or `FRAUDULENT`); each refund records the `charge_id` it targets. A refund may be created only when the charge's `auth_status` is `CAPTURED` (otherwise `ERR_INVALID_STATE`, HTTP 409). Two fiscal and referential guards then apply at creation, and the referential dispute-block guard is evaluated before the fiscal headroom guard, so when both could fire the request reports `ERR_REFUND_BLOCKED_BY_DISPUTE`. First, a refund may not be created while the charge has a live dispute: if a `Dispute` in any non-terminal status (`OPEN`, `UNDER_REVIEW`, or `REPRESENTED`) exists on the charge, the refund is rejected with `ERR_REFUND_BLOCKED_BY_DISPUTE` (HTTP 409). Second, the running total of refunds must stay within the captured amount: the charge's existing `refunded_amount_cents` plus the new refund `amount_cents` must not exceed the charge's `captured_amount_cents`, and a refund that would push the cumulative refunded total above the captured amount is rejected with `ERR_REFUND_EXCEEDS_CAPTURED` (HTTP 422). A successful creation produces a refund in `PENDING` status and immediately increments the charge's `refunded_amount_cents` by the refund amount, reserving that headroom.

A pending refund is resolved by a `PlatformOperator` along one of two branches. Settling the refund drives its `refund_status` from `PENDING` to `SETTLED`: it posts a `REFUND` ledger entry against the `AVAILABLE` account for the negative of the refund's `amount_cents` (a debit) with `source_type` `REFUND`, then recomputes the merchant's `available_balance_cents`. Failing the refund instead drives its `refund_status` from `PENDING` to `FAILED`: it posts no ledger entry and compensates by decrementing the charge's `refunded_amount_cents` by the refund's `amount_cents`, which restores the refundable headroom that was reserved at creation. Both branches are permitted only while the refund's `refund_status` is `PENDING`. Refunds are readable individually and listable per charge.

### 3.6. Chargeback Disputes and Representment

When a cardholder disputes a charge, a `MerchantUser` opens a **dispute** by naming the `disputed_amount_cents`, which records the `charge_id` it concerns. A dispute can be opened only on a charge whose `auth_status` is `CAPTURED` and whose `settlement_status` is `SETTLED`, and only when no non-terminal dispute already exists on that charge. The disputed amount must exactly equal the charge's net captured amount — that is, the charge's `captured_amount_cents` minus its `refunded_amount_cents` — at the moment of opening; a disputed amount that does not equal net captured is rejected with `ERR_DISPUTE_AMOUNT_MISMATCH` (HTTP 422), and an open attempt against a charge whose status does not permit it is rejected with `ERR_INVALID_STATE`.

Opening a dispute sets its `dispute_status` to `OPEN`, copies the merchant fee plan's `chargeback_fee_cents` onto the dispute's own `chargeback_fee_cents`, and sets the dispute's `evidence_due_at` to the current clock plus a fourteen-day evidence window. It also drives two ledger debits on the `AVAILABLE` account, both with `source_type` `DISPUTE`: a `CHARGEBACK` entry for the negative of `disputed_amount_cents`, and a `FEE` entry for the negative of the chargeback fee. Because the open requires the disputed amount to equal net captured, opening a dispute drives the charge's `settlement_status` from `SETTLED` to `REVERSED`. The dispute's `representment_round` begins at 0. After the postings, the merchant's `available_balance_cents` is recomputed.

The dispute then runs a cyclic representment process. The merchant acknowledges the dispute, moving it from `OPEN` to `UNDER_REVIEW` (no ledger effect). From `UNDER_REVIEW`, the merchant submits representment evidence, moving the dispute to `REPRESENTED` and incrementing `representment_round` by one; representment is permitted only while the dispute is `UNDER_REVIEW`, only while the current clock is at or before `evidence_due_at` (a submission after the deadline is rejected with `ERR_EVIDENCE_WINDOW_CLOSED`, HTTP 422), and only while `representment_round` is strictly less than the cap of two rounds (a submission once two rounds have already been used is rejected with `ERR_REPRESENTMENT_LIMIT_REACHED`, HTTP 422). When more than one of these guards could fire, the evidence-window check precedes the round-limit check. From `REPRESENTED`, the network may ask for more evidence: a `PlatformOperator` reopens the dispute back to `UNDER_REVIEW`, which is permitted only while the dispute is `REPRESENTED` and `representment_round` is strictly less than two, and which extends `evidence_due_at` by another fourteen days. This `UNDER_REVIEW` to `REPRESENTED` to `UNDER_REVIEW` loop may cycle up to the two-round cap.

A represented dispute is resolved by a `PlatformOperator` with an `outcome` of either `WON` or `LOST`; the `outcome` field is required, and a request that omits it (or supplies a non-string) is rejected with `ERR_VALIDATION` (HTTP 400). An `outcome` that is a string outside the `WON`/`LOST` pair is rejected with `ERR_RESOLVE_OUTCOME_INVALID` (HTTP 422), and resolution is permitted only while the dispute is `REPRESENTED`; the `outcome`-validity check is applied before the `REPRESENTED`-state check, so an invalid outcome on a non-`REPRESENTED` dispute reports `ERR_RESOLVE_OUTCOME_INVALID` rather than `ERR_INVALID_STATE`. Resolving `WON` drives the dispute to the terminal `WON` state, posts a `CHARGEBACK_REVERSAL` ledger entry on the `AVAILABLE` account for the positive of `disputed_amount_cents` (a credit) with `source_type` `DISPUTE`, and — because the chargeback fee is retained even on a win — does not reverse the `chargeback_fee_cents`. If the charge's `settlement_status` had been driven to `REVERSED` by the open, winning restores it to `SETTLED`. The merchant's `available_balance_cents` is then recomputed. Resolving `LOST` drives the dispute to the terminal `LOST` state with no further ledger postings, so the chargeback debit is retained. The merchant may also concede at any time before resolution by accepting liability, which drives the dispute to the terminal `ACCEPTED` state from either `OPEN` or `UNDER_REVIEW` with no further ledger postings and the chargeback debit retained.

The net cash effect of a dispute is precise and intentional. Opening debits the available account by the disputed amount plus the chargeback fee. A subsequent win credits back only the disputed amount; the chargeback fee is never returned. Therefore a full open-then-won cycle leaves the merchant's available balance lower by exactly the chargeback fee — this drift is the designed, conserved cost of being disputed even when the merchant prevails. Disputes are readable individually and listable per charge.

### 3.7. Settlement Batches: Sweep, Settle, and Fund

Captured charges reach the merchant's balance through a three-step settlement pipeline run by a `PlatformOperator`. The pipeline opens with a sweep: the operator opens a settlement batch for a merchant by naming a `business_date` (a YYYY-MM-DD calendar date), and the batch belongs to the merchant via its `merchant_id`. Opening a batch is permitted only when the merchant's `onboarding_status` is `APPROVED` or `SUSPENDED`, and only when at least one charge with `auth_status` `CAPTURED` and `settlement_status` `PENDING` exists for that merchant; if no such eligible charge exists, the open is rejected with `ERR_NO_ELIGIBLE_CHARGES` (HTTP 409). On opening, the batch's `batch_status` is `OPEN`, and every eligible captured-and-pending charge is swept into it: each such charge has its `settlement_status` moved from `PENDING` to `BATCHED` and its `settlement_batch_id` set to the new batch. A batch starts with its `gross_captured_cents`, `total_fees_cents`, `total_refunds_cents`, `reserve_held_cents`, and `net_funding_cents` all at 0; these are pinned at settle.

Settling the batch advances it from `OPEN` to `SETTLED` and triggers the funding cascade. Settle is permitted only while the batch's `batch_status` is `OPEN` and requires `expected_merchant_version` to match the merchant's current `version`, as described in §2.10. The cascade proceeds in order: first, every batched charge has its `settlement_status` moved from `BATCHED` to `SETTLED`. Next, the batch's aggregates are pinned (see §3.8 for the formula): `gross_captured_cents`, `total_fees_cents`, and `total_refunds_cents`. Then the reserve hold is computed and a `ReserveEntry` in `HELD` status is created for it, and a `RESERVE_HOLD` ledger entry is posted on the `RESERVE` account for the positive of the reserve amount with `source_type` `RESERVE_ENTRY`. The batch's `net_funding_cents` is computed, the merchant's `version` is incremented by one, and the merchant's `reserved_balance_cents` is recomputed. Settling does not yet move money to the available account; that happens only at funding.

Funding the batch advances it from `SETTLED` to the terminal `FUNDED`. Funding is permitted only while the batch's `batch_status` is `SETTLED` and only once the clock's date has reached or passed the batch's `business_date` plus the merchant's `funding_delay_days`; an attempt to fund before that maturity is rejected with `ERR_FUNDING_DATE_NOT_REACHED` (HTTP 409). Funding posts a single `FUNDING` ledger entry on the `AVAILABLE` account for the positive of the batch's `net_funding_cents` with `source_type` `SETTLEMENT_BATCH`, then recomputes the merchant's `available_balance_cents`. Because the processing fees were subtracted inside `net_funding_cents`, this funding posting is where the fees are finally deducted — they are never posted separately. Batches are readable individually and listable per merchant, filterable by `batch_status`.

### 3.8. Pinning the Batch: the Settlement Summary Calculation

At settle time the batch's financial aggregates are pinned from its constituent charges and the refunds against them, all in integer cents. The `gross_captured_cents` is the sum of `captured_amount_cents` over every charge whose `settlement_batch_id` is this batch. The `total_fees_cents` is the sum of `processing_fee_cents` over those same charges. The `total_refunds_cents` is the sum of `amount_cents` over refunds that are in `SETTLED` status, that sit on charges belonging to this batch, and whose settle date is on or before the batch's `business_date`; these refunds are accumulated in ascending order of their `created_at` for determinism.

The `reserve_held_cents` is computed once on the gross total: it is the `gross_captured_cents` multiplied by the merchant's `reserve_rate_bps` divided by 10000, rounded half-up — this is sum-then-round on the aggregate, rounded a single time. Finally the `net_funding_cents` is the `gross_captured_cents` minus the `total_fees_cents` minus the `total_refunds_cents` minus the `reserve_held_cents`. All five pinned values are frozen onto the batch at settle and are not recomputed afterward.

### 3.9. Rolling Reserve: Holds and the Release Sweep

Each settle creates one rolling-reserve hold, captured as a `ReserveEntry` that records the `merchant_id` it is held against, the `settlement_batch_id` that contributed it, the `amount_cents` held (equal to the batch's `reserve_held_cents`), a `release_date`, and a `reserve_status` that begins at `HELD`. The `release_date` is the contributing batch's `business_date` plus the ninety-day reserve hold window. The corresponding `RESERVE_HOLD` ledger posting at settle is what raises the merchant's `reserved_balance_cents`.

Reserves are returned to spendable money by a release sweep run by a `PlatformOperator` for a merchant. The sweep releases every `HELD` reserve entry whose `release_date` has been reached or passed by the clock's date; an entry is eligible only while its `reserve_status` is `HELD` and only when the clock's date is at or after its `release_date`. Releasing an entry moves its `reserve_status` from `HELD` to `RELEASED` and posts two ledger entries, both with `source_type` `RESERVE_ENTRY`: a `RESERVE_RELEASE` entry on the `RESERVE` account for the negative of the held `amount_cents`, and an `ADJUSTMENT` entry on the `AVAILABLE` account for the positive of the same `amount_cents` — together moving the funds from the reserve account into the available account. After the sweep, the merchant's `reserved_balance_cents` and `available_balance_cents` are both recomputed (and only when at least one entry was released). Eligible entries are released in ascending creation order, and the sweep responds with HTTP 200 and an array `data` payload (`response_type` is `"array"`) containing the reserve-entry resources released by this sweep in that same order; when no entry was eligible the array is empty. Reserve entries are listable both per merchant (filterable by `reserve_status`) and per settlement batch.

### 3.10. Payouts

Once a merchant has spendable money, a `MerchantUser` requests a **payout** against its available balance by naming the payout `amount_cents` (at least 1) and a `scheduled_for` date (a YYYY-MM-DD calendar date); the payout belongs to the merchant via its `merchant_id`. A payout may be requested only while the merchant's `onboarding_status` is `APPROVED`, and the requested amount must not exceed the merchant's `available_balance_cents`; a request for more than the available balance is rejected with `ERR_INSUFFICIENT_BALANCE` (HTTP 422), and a request while the merchant is not approved is rejected with `ERR_MERCHANT_NOT_APPROVED`. Requesting a payout debits the money immediately: it sets the payout's `payout_status` to `REQUESTED`, posts a `PAYOUT` ledger entry on the `AVAILABLE` account for the negative of the payout `amount_cents` with `source_type` `PAYOUT`, and recomputes the merchant's `available_balance_cents`.

A `PlatformOperator` resolves a requested payout along one of two branches. Marking it paid drives `payout_status` from `REQUESTED` to the terminal `PAID`; it is permitted only while the payout is `REQUESTED` and only once the clock's date has reached or passed the payout's `scheduled_for` date, with an early attempt rejected by `ERR_PAYOUT_DATE_NOT_REACHED` (HTTP 409). Marking paid posts no ledger entry, because the funds were already debited at request time. Returning the payout — used when the bank rejects it — drives `payout_status` from `REQUESTED` to the terminal `RETURNED`; it is permitted only while the payout is `REQUESTED`, posts a compensating `PAYOUT_RETURN` ledger entry on the `AVAILABLE` account for the positive of the payout `amount_cents` with `source_type` `PAYOUT`, and recomputes the merchant's `available_balance_cents`, restoring the debited funds. Payouts are readable individually and listable per merchant, filterable by `payout_status`.

### 3.11. The Ledger, 1099-K Reporting, and Webhooks

Every merchant's ledger is readable as a list filterable by `account`, `entry_type`, and `source_type`, which exposes the full audit trail behind the derived balances. From that settled history the platform generates tax forms. A `PlatformOperator` generates (or regenerates) a 1099-K form for a merchant and a given `tax_year`; the form records the `merchant_id`, the `tax_year`, the computed `gross_amount_cents`, the `transaction_count`, and the `reportable` flag.

The 1099-K gross is a threshold calculation over settled captures, with no netting of refunds, fees, or chargebacks. The included set is every charge of the merchant whose `settlement_status` is `SETTLED` and whose settle posting fell within the requested `tax_year`. The `gross_amount_cents` is the sum of `captured_amount_cents` over that included set, the `transaction_count` is the number of charges in the included set, and the `reportable` flag is true exactly when `gross_amount_cents` strictly exceeds the reporting threshold of 250000 cents. The comparison is strict: a gross of exactly 250000 cents is not reportable, while 250001 cents is. Tax forms are readable individually and listable per merchant, filterable by `tax_year`.

The platform also emits domain events as **webhook events**. A `PlatformOperator` emits an event for a merchant by supplying the `event_type`, a `source_id` naming the entity the event concerns (display only), and an `idempotency_key`. Emission is idempotent on the key: a repeated emit carrying an `idempotency_key` that has already been used returns the existing event rather than creating a new one (and responds with HTTP 200 instead of 201). Idempotency is scoped per merchant — the `idempotency_key` is matched only against webhook events already recorded for the same merchant, so the same key reused under a different merchant creates a new event. When an existing event is returned, it is returned unchanged regardless of whether the repeated request's `event_type` or `source_id` differ. A webhook event records the `merchant_id` it concerns. Webhook events are listable per merchant, filterable by `event_type`.

### 3.12. The Logical Clock

All time-gated behavior in the system is driven by a controllable logical clock rather than wall-clock time, and only a `PlatformOperator` may manipulate it. One capability sets the clock to a fixed UTC instant supplied as `to_iso8601`; this is the clock consulted for evidence windows, funding maturities, reserve release dates, payout scheduling, and the calendar year that a settle posting is attributed to. A second capability advances the clock to a supplied `to_iso8601` instant and, as part of advancing, runs the authorization-expiry sweep that moves any `AUTHORIZED` charge older than the seven-day authorization hold window to `EXPIRED`, as described in §3.3.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`. Operations that act on or modify an existing resource — captures, voids, state transitions, settlement, funding, releases, payouts, clock control — return `200 OK`. The idempotent webhook emit returns `201 Created` when it creates a new event and `200 OK` when a previously used `idempotency_key` causes the existing event to be returned. The request and response payloads for each endpoint are reconstructed from the §3 narratives above; the table below is the routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/fee-plans` | Create a fee plan (FLAT or INTERCHANGE_PLUS) | PlatformOperator |
| GET | `/fee-plans/{id}` | Fetch a fee plan | PlatformOperator, UnderwritingOfficer, MerchantUser |
| GET | `/fee-plans` | List fee plans | PlatformOperator, UnderwritingOfficer |
| POST | `/merchants` | Register a new merchant (anonymous); creates an OPEN risk review | Anonymous |
| GET | `/merchants/{id}` | Fetch a merchant including derived balances | PlatformOperator, UnderwritingOfficer, MerchantUser |
| GET | `/merchants` | List merchants, filterable by fee plan and onboarding status | PlatformOperator, UnderwritingOfficer |
| GET | `/merchants/{id}/risk-reviews` | List risk reviews for a merchant | PlatformOperator, UnderwritingOfficer |
| POST | `/merchants/{id}/risk-reviews/{rid}/approve` | Approve underwriting; assign risk band, reserve rate, funding delay | UnderwritingOfficer |
| POST | `/merchants/{id}/risk-reviews/{rid}/reject` | Reject underwriting | UnderwritingOfficer |
| POST | `/merchants/{id}/suspend` | Suspend an approved merchant | UnderwritingOfficer |
| POST | `/merchants/{id}/reinstate` | Reinstate a suspended merchant | UnderwritingOfficer |
| POST | `/merchants/{id}/charges` | Authorize a charge against the card | MerchantUser |
| GET | `/charges/{id}` | Fetch a charge with both status axes | PlatformOperator, MerchantUser |
| GET | `/charges` | List charges, filterable by merchant, batch, and status axes | PlatformOperator, MerchantUser |
| POST | `/charges/{id}/capture` | Capture all or part of an authorization; computes processing fee | MerchantUser |
| POST | `/charges/{id}/void` | Void an uncaptured authorization | MerchantUser |
| POST | `/charges/{id}/refunds` | Create a refund (full or partial) against a captured charge | MerchantUser |
| GET | `/refunds/{id}` | Fetch a refund | PlatformOperator, MerchantUser |
| GET | `/charges/{id}/refunds` | List refunds on a charge | PlatformOperator, MerchantUser |
| POST | `/refunds/{id}/settle` | Settle a pending refund (posts merchant debit) | PlatformOperator |
| POST | `/refunds/{id}/fail` | Mark a pending refund failed; restores refundable headroom | PlatformOperator |
| POST | `/charges/{id}/disputes` | Open a chargeback dispute on a settled charge | MerchantUser |
| GET | `/disputes/{id}` | Fetch a dispute | PlatformOperator, MerchantUser |
| GET | `/charges/{id}/disputes` | List disputes on a charge | PlatformOperator, MerchantUser |
| POST | `/disputes/{id}/acknowledge` | Acknowledge a dispute (OPEN to UNDER_REVIEW) | MerchantUser |
| POST | `/disputes/{id}/represent` | Submit representment evidence | MerchantUser |
| POST | `/disputes/{id}/reopen` | Network requests more evidence (cycle) | PlatformOperator |
| POST | `/disputes/{id}/resolve` | Resolve a represented dispute WON or LOST | PlatformOperator |
| POST | `/disputes/{id}/accept` | Accept liability; chargeback retained | MerchantUser |
| POST | `/merchants/{id}/settlement-batches` | Open a settlement batch; sweep eligible captured charges | PlatformOperator |
| GET | `/settlement-batches/{id}` | Fetch a settlement batch with pinned aggregates | PlatformOperator, MerchantUser |
| GET | `/merchants/{id}/settlement-batches` | List settlement batches for a merchant | PlatformOperator, MerchantUser |
| POST | `/settlement-batches/{id}/settle` | Settle the batch: cascade, pin aggregates, hold reserve (OCC) | PlatformOperator |
| POST | `/settlement-batches/{id}/fund` | Fund a settled batch on/after T+N | PlatformOperator |
| GET | `/merchants/{id}/reserve-entries` | List reserve entries for a merchant | PlatformOperator, MerchantUser |
| GET | `/settlement-batches/{id}/reserve-entries` | List reserve entries from a batch | PlatformOperator, MerchantUser |
| POST | `/merchants/{id}/reserve-releases` | Run the reserve release sweep | PlatformOperator |
| POST | `/merchants/{id}/payouts` | Request a payout against available balance | MerchantUser |
| GET | `/payouts/{id}` | Fetch a payout | PlatformOperator, MerchantUser |
| GET | `/merchants/{id}/payouts` | List payouts for a merchant | PlatformOperator, MerchantUser |
| POST | `/payouts/{id}/mark-paid` | Mark a requested payout paid on/after scheduled date | PlatformOperator |
| POST | `/payouts/{id}/return` | Return a requested payout; restores available balance | PlatformOperator |
| GET | `/merchants/{id}/ledger-entries` | List ledger entries for a merchant | PlatformOperator, MerchantUser |
| POST | `/merchants/{id}/tax-1099k` | Generate (or regenerate) the 1099-K form for a tax year | PlatformOperator |
| GET | `/tax-1099k/{id}` | Fetch a generated 1099-K form | PlatformOperator, MerchantUser |
| GET | `/merchants/{id}/tax-1099k` | List 1099-K forms for a merchant | PlatformOperator, MerchantUser |
| POST | `/merchants/{id}/webhook-events` | Emit a webhook event with idempotency | PlatformOperator |
| GET | `/merchants/{id}/webhook-events` | List webhook events for a merchant | PlatformOperator, MerchantUser |
| POST | `/_clock/set` | Set the system clock to a fixed UTC instant | PlatformOperator |
| POST | `/_clock/advance` | Advance the clock and run the authorization-expiry sweep | PlatformOperator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_FK_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INVALID_ENUM` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_MERCHANT_NOT_APPROVED` | 409 Conflict |
| `ERR_RISK_BAND_POLICY_VIOLATION` | 422 Unprocessable Entity |
| `ERR_CAPTURE_EXCEEDS_AUTH` | 422 Unprocessable Entity |
| `ERR_REFUND_EXCEEDS_CAPTURED` | 422 Unprocessable Entity |
| `ERR_REFUND_BLOCKED_BY_DISPUTE` | 409 Conflict |
| `ERR_DISPUTE_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_EVIDENCE_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_REPRESENTMENT_LIMIT_REACHED` | 422 Unprocessable Entity |
| `ERR_FUNDING_DATE_NOT_REACHED` | 409 Conflict |
| `ERR_PAYOUT_DATE_NOT_REACHED` | 409 Conflict |
| `ERR_INSUFFICIENT_BALANCE` | 422 Unprocessable Entity |
| `ERR_STALE_MERCHANT_VERSION` | 412 Precondition Failed |
| `ERR_FEE_PLAN_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_NO_ELIGIBLE_CHARGES` | 409 Conflict |
| `ERR_RESOLVE_OUTCOME_INVALID` | 422 Unprocessable Entity |
