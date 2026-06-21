# Insurance Agency Management API — Product Requirements Document

## 1. Introduction

An independent insurance agency lives and dies by the integrity of two things: its **book of business** — the set of client accounts and the policies placed for them across many carriers — and its **premium trust**, the fiduciary money it holds on behalf of insureds and carriers before it is remitted or disbursed. This document specifies a back-office platform that unifies both. It tracks carriers and the products they underwrite, the producers who write business and the licenses and carrier appointments that authorize them to do so, the policies themselves through bind, activation, cancellation, reinstatement and renewal, the commission those policies generate and how it is split among producers, and the trust-accounting ledger that records every movement of premium money.

The platform is, at its core, a reconciliation engine. Commission earned must reconcile against commission paid; trust-account balances must reconcile against the sum of their postings; a cancellation that refunds unearned premium to an insured must simultaneously claw back the commission already accrued on that premium, and a later reinstatement must reverse both movements exactly. Layered on top of the money is a compliance surface: a producer may not bind a policy in a state where they hold no active license, nor with a carrier they are not appointed with, and the agency may never let a fiduciary trust account fall below its regulatory floor. The sections that follow define the contract precisely where the API's shape is concerned, and describe the business rules — license validity, commission tiers, dual-variant return-premium math, renewal pipelines — in narrative form, so that an implementer can reconstruct the complete behavior from this document alone.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API (with the single exception noted below) must carry two headers identifying the caller: `X-User-ID`, an opaque or entity-bound identifier for the acting user, and `X-User-Role`, naming the caller's role. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are present but the named role is not permitted to invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

There are exactly four roles, spelled precisely as follows: `AgencyAdmin`, `Producer`, `AccountManager`, and `TrustAccountant`.

- `AgencyAdmin` is the agency administrator and operational super-user for the configuration surface — carriers, products, producers, licenses, appointments, and the test-driving clock. When `X-User-Role` is `AgencyAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.
- `Producer` is a licensed producer who writes and binds their own policies and proposes commission splits. When `X-User-Role` is `Producer`, `X-User-ID` is the `id` of the acting `Producer`; ownership checks on any resource that references a `Producer` compare the resource's producer foreign-key field to `X-User-ID`.
- `AccountManager` services the book — activating, cancelling, reinstating, expiring and non-renewing policies, and driving the renewal pipeline. When `X-User-Role` is `AccountManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.
- `TrustAccountant` owns the premium-trust accounts, the ledger postings against them, and the commission-statement lifecycle (finalize, reopen, pay), segregated from the producers whose money they handle. When `X-User-Role` is `TrustAccountant`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

The one exception to the universal-authentication rule concerns the test-driving clock endpoint: it still requires authentication and still requires the `AgencyAdmin` role; it is never anonymous. The §4 table is authoritative for which roles may call each endpoint; all read (GET) operations are broadly shared, while the write operations are partitioned among the roles as the narrative in §3 describes.

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

All list endpoints are paginated through two query parameters, `limit` and `offset`. The `limit` controls how many records a single page returns: it defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` is the zero-based index of the first record to return; it defaults to 0 and may not be negative. List results are sorted by `created_at` in ascending order (oldest first) before pagination is applied. Each list response reports `limit`, `offset`, `total_count` (the total number of records matching the query before pagination), and `has_more` (true when records beyond the current page remain) inside the `meta` object.

### 2.4. Common Resource Properties and Identity

Every primary resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp rendered as an ISO 8601 UTC instant with three fractional digits, fixed at creation. Most resources additionally carry an `updated_at` timestamp — refreshed on every mutation to that resource — and a `version`, an integer that begins at 1 on creation and increments by exactly one on every mutation. The `version` is the basis of optimistic concurrency control (see §2.7).

Two resources are deliberately leaner. A `TrustLedgerEntry` is immutable once posted: it carries only an `id` and a `created_at`, and has neither an `updated_at` nor a `version`. The `SystemClock` is likewise a singleton control record carrying only its `current_utc` value; it has neither `updated_at` nor `version`. Every other entity — `Carrier`, `Product`, `Producer`, `License`, `Appointment`, `Account`, `Policy`, `CommissionSplit`, `TrustAccount`, `CommissionStatement`, and `RenewalTask` — carries the full quartet of `id`, `created_at`, `updated_at`, and `version`.

### 2.5. Resource Resolution and Referential Integrity

Many operations reference other resources by identifier, both in URL path segments and in request bodies. The server resolves these identifiers left to right; the first identifier that names no existing resource causes the whole request to fail with `ERR_NOT_FOUND` (HTTP 404) before any business rule is evaluated. For write operations, once existence is confirmed, the body must parse, every required field must be present, every field must be of the correct type, every enumerated field must carry a permitted value, and every numeric field must fall within its declared range; any violation yields `ERR_INVALID_REQUEST` (HTTP 400).

### 2.6. The Premium-Trust Ledger Principle

Premium money the agency holds in fiduciary trust is never represented by a mutable balance field that the system writes directly. Instead, each `TrustAccount` keeps a derived `balance_cents` that is always exactly the sum of the `amount_cents` of every `TrustLedgerEntry` posted to it, recomputed on every posting (derived-field reconciliation). Ledger amounts are signed integers in cents. The sign of an entry is fixed by its `entry_type`: a `PREMIUM_RECEIPT` and an `OPENING_BALANCE` are positive (money entering trust), while a `CARRIER_REMITTANCE`, a `COMMISSION_DISBURSEMENT`, and a `RETURN_PREMIUM_REFUND` are negative (money leaving trust). Because the balance is derived, the only way to change it is to post another entry; there is no direct balance write anywhere in the system.

Every trust account also carries a `minimum_balance_cents` fiduciary floor. No disbursement — whether a commission payment or a manually posted negative entry — may drop `balance_cents` below that floor; an attempt to do so is rejected with `ERR_TRUST_MINIMUM_BREACH` (HTTP 422). There is exactly one trust account per US state, keyed by its two-letter `state_code`; attempting to create a second account for a state already held is a uniqueness violation (see §2.8).

### 2.7. Monetary Precision and Rounding

All monetary quantities — premiums, commissions, return premiums, ledger amounts, statement figures — are stored and exchanged as integer cents, never as floating decimals. Wherever a calculation produces a fractional cent, the result is rounded to a whole cent using the round-half-up rule (a value exactly halfway between two cents rounds up to the larger cent). Each calculation below states precisely where rounding is applied; the governing principle is that rounding happens once at each declared step, never silently mid-stream, so that a reader can reproduce every stored figure to the exact cent.

### 2.8. Uniqueness Constraints

Three fields are unique across their entity collections. A `Carrier` must have a `naic_code` distinct from every other carrier's; a `Producer` must have an `npn` distinct from every other producer's; and a `TrustAccount` must have a `state_code` distinct from every other trust account's. Any creation that would duplicate one of these values is rejected with `ERR_DUPLICATE` (HTTP 409).

### 2.9. Optimistic Concurrency Control

State-changing operations on a versioned resource guard against lost updates with optimistic concurrency control. The operations that take a version field require it as a non-optional input; the field is named `expected_<entity>_version` after the entity it guards — `expected_carrier_version`, `expected_producer_version`, `expected_appointment_version`, `expected_policy_version`, `expected_commissionstatement_version`, `expected_renewaltask_version`, and `expected_trustaccount_version`. When such an operation runs, the supplied value must equal the target resource's current `version`. If another writer has advanced the resource's `version` since the client last read it, the values no longer match and the request is rejected with `ERR_STALE_VERSION` (HTTP 412), evaluated after state-machine eligibility but before the operation's business effects. Endpoints that do not declare a version field perform no such check.

Two creation endpoints carry a version check against a *parent* rather than the resource being created. Adding a commission split is guarded against a stale view of the policy it allocates: a request to add a `CommissionSplit` must carry `expected_policy_version` matching the target `Policy`'s current `version`. If another writer has advanced the policy's `version` since the client last read it — for example by activating the policy, which locks the existing splits and bumps `Policy.version` — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client cannot append a split against a policy whose mutable-split state it has not observed. Likewise, posting a manual ledger entry is guarded against a stale view of the trust balance: a request to post a `TrustLedgerEntry` must carry `expected_trustaccount_version` matching the target `TrustAccount`'s current `version`. If another posting — such as a return-premium-refund cascade — has advanced the account's `version` since the client last read the balance, the post is rejected with `ERR_STALE_VERSION` (HTTP 412), so a disbursement cannot be computed against a balance the client has not observed.

### 2.10. Validation Ordering

When several checks could fail a single request, they are evaluated in a fixed priority order, and the first failing check determines the error returned. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then authorization (`ERR_UNAUTHORIZED`), then existence of every referenced resource (`ERR_NOT_FOUND`), then request well-formedness (`ERR_INVALID_REQUEST`), then — for state-transition endpoints — whether the target is in a state from which the transition is legal (`ERR_INVALID_STATE`, HTTP 409), then the optimistic-concurrency version match (`ERR_STALE_VERSION`). Only after all of these pass are the domain-specific business rules (uniqueness, licensing, appointment, split allocation, temporal windows, fiscal floors, and the rest described throughout §3) evaluated. This ordering matters: a request that is both malformed and made against a resource in the wrong state reports the malformed-request error, not the state error, because well-formedness is checked first.

### 2.11. The Authoritative Clock

Several rules depend on the current moment — license and appointment validity, the renewal window, cancellation and reinstatement timing, and statement-period closure. The system reads "now" from an authoritative server clock (`current_utc`) rather than from wall-clock time wherever such a rule applies. For deterministic testing, an `AgencyAdmin` may set this clock to any instant by supplying the target moment as `to_iso8601`; until it is set, it defaults to real wall-clock time. Every subsequent now-dependent computation reads the clock's `current_utc`.

## 3. Business Logic & Workflows

### 3.1. Carriers and the Products They Underwrite

The configuration surface begins with **carriers** — the insurance companies whose paper the agency places. An `AgencyAdmin` creates a carrier by supplying its legal `name`, a `naic_code` (the carrier's NAIC company identifier, which must be exactly five digits and unique across all carriers), an optional `download_supported` flag indicating whether the carrier offers an ACORD policy-download feed (defaulting to false when omitted), and two default commission rates: `default_new_business_commission_pct` and `default_renewal_commission_pct`. Both rates are expressed as fractions between 0 and 1 inclusive and act as the agency's fallback commission terms when a product does not override them. A newly created carrier begins in the `PROSPECTIVE` state.

A carrier moves through a small lifecycle, all transitions reserved to the `AgencyAdmin`. Activating a `PROSPECTIVE` carrier moves it to `ACTIVE`, but only if its `naic_code` is present and five digits and the supplied `expected_carrier_version` matches the carrier's current `version`. An `ACTIVE` carrier may be suspended, transitioning `ACTIVE → SUSPENDED`; while suspended, no new policy may be bound against any of that carrier's products. A `SUSPENDED` carrier may be re-activated, transitioning `SUSPENDED → ACTIVE` again. Both suspend and re-activate require the matching `expected_carrier_version`. Termination is available from either `ACTIVE` or `SUSPENDED`, moving the carrier to the terminal `TERMINATED` state; it requires the matching `expected_carrier_version` and is permitted only when no policy under any of the carrier's products is currently in `ACTIVE`, `PENDING_RENEWAL`, or `REINSTATED` status. When a carrier is terminated, the effect cascades downward: every appointment naming that carrier whose status is `REQUESTED`, `APPROVED`, or `ACTIVE` is itself transitioned to `TERMINATED`, and each such appointment's `version` increments. Each carrier transition also increments the carrier's own `version`.

A **product** is a specific line of insurance a carrier underwrites. An `AgencyAdmin` creates one by naming the underwriting carrier through a `carrier_id`, choosing the `line_of_business` (one of `AUTO`, `HOME`, `GL`, `WC`, or `UMBRELLA`), giving it a display `name`, and choosing a `cancellation_basis` of either `PRO_RATA` or `SHORT_RATE` that governs how return premium is computed when a policy on this product is cancelled. A product may optionally override the carrier's commission defaults with its own `new_business_commission_pct` and `renewal_commission_pct`; each is either null (the default, meaning fall back to the carrier's corresponding default rate) or a fraction between 0 and 1 inclusive. Products may be listed filtered by `carrier_id` or by `line_of_business`.

### 3.2. Producers, Licenses, and Carrier Appointments — the Compliance Spine

A **producer** is a licensed agent. An `AgencyAdmin` registers one with a `full_name`, a National Producer Number `npn` (which must be non-empty and unique across producers), and a `default_split_pct` — the fraction between 0 and 1 inclusive of agency commission this producer ordinarily receives on policies they personally write, used to seed the writing-producer split. A producer is created `ACTIVE` and may later be deactivated to `INACTIVE`; deactivation requires `expected_producer_version`. An `INACTIVE` producer can no longer be assigned commission splits.

Authorization to transact rests on two independent credentials, both tracked as resources. A **license** records that a producer is licensed in a given state for a given line of business. It is created with the holding `producer_id`, a `state_code` (exactly two uppercase letters), a `line_of_business`, an `effective_date`, and an `expiration_date`. A license carries no stored status; instead its validity is computed against the authoritative clock at read time: it is `ACTIVE` when the current moment is at or after its `effective_date` and strictly before its `expiration_date`, `EXPIRED` once the current moment reaches or passes its `expiration_date`, and `PENDING` while the current moment is still before its `effective_date`. The `expiration_date` is exclusive — a license is valid for instants strictly earlier than it. A license's `effective_date` must be strictly before its `expiration_date`, or the creation is rejected with `ERR_INVALID_DATE_RANGE`. Furthermore, a producer may not hold two licenses for the same state and line of business whose validity intervals overlap: when a new license is recorded, its half-open interval from `effective_date` (inclusive) to `expiration_date` (exclusive) must not intersect that of any existing license for the same producer, state, and line of business. Touching at the boundary is explicitly permitted — if an existing license's `expiration_date` equals the new license's `effective_date`, the intervals merely abut and do not overlap — but any true intersection is rejected with `ERR_LICENSE_OVERLAP` (HTTP 409). Licenses can be listed filtered by `producer_id`, `state_code`, and `line_of_business`.

An **appointment** records that a producer is authorized to place business with a particular carrier in a particular state — the carrier's grant of agency to the producer. An `AgencyAdmin` requests one by supplying the `carrier_id`, the `producer_id`, and the `state_code` (two uppercase letters); the appointment is created `REQUESTED` and stamped with a `requested_at` server timestamp. Appointments advance through their lifecycle under the `AgencyAdmin`. Approving a `REQUESTED` appointment moves it `REQUESTED → APPROVED`, but only if the named carrier is currently `ACTIVE` and the named producer is currently `ACTIVE`. Activating an `APPROVED` appointment moves it `APPROVED → ACTIVE`, but only if the appointed producer holds a license in the appointment's `state_code` whose computed status is `ACTIVE` at the current moment — a cross-entity dependency on the producer's licenses; absent such a license the activation is rejected with `ERR_LICENSE_NOT_ACTIVE` (HTTP 422). An appointment may be terminated from `REQUESTED`, `APPROVED`, or `ACTIVE`, moving it to the terminal `TERMINATED` state with no precondition beyond the transition's legality. Approve, activate, and terminate each take `expected_appointment_version` and increment the appointment's `version`. Appointments may be listed filtered by `carrier_id`, `producer_id`, `state_code`, and `status`.

### 3.3. Accounts and the Birth of a Policy

An **account** is a book-of-business client. Either an `AgencyAdmin` or an `AccountManager` opens one with a client `name`, a `servicing_producer_id` naming the producer who services the account, and an `account_type` of either `PERSONAL` or `COMMERCIAL`. An account tracks a derived `active_policy_count` — the number of policies under it whose status is either `ACTIVE` or `PENDING_RENEWAL` — which starts at 0 and is recomputed on every policy state change that could affect it. Accounts may be listed filtered by `servicing_producer_id` and `account_type`.

A **policy** is the central revenue-bearing entity. An `AgencyAdmin`, `Producer`, or `AccountManager` creates one by supplying the `account_id` it belongs to, the `product_id` underwriting it, the `writing_producer_id` of record, the two-letter `state_code` where the risk is located, the full-term gross written premium `annual_premium_cents` (a positive integer in cents), and the term boundaries `effective_date` (inclusive term start) and `expiration_date` (exclusive term end). The `effective_date` must be strictly before the `expiration_date`, or creation fails with `ERR_INVALID_DATE_RANGE`. Two optional inputs shape how the policy is born. If `renewed_from_policy_id` is supplied, it names the prior-term policy this one renews from, forming the self-referential renewal chain; its presence sets the policy's `term_kind` to `RENEWAL`, while its absence sets `term_kind` to `NEW_BUSINESS`. If `acord_download` is supplied as true, the policy represents a record arriving from the carrier's ACORD download feed: its `download_source` is recorded as `ACORD_DOWNLOAD` and it is created already in `BOUND` status, skipping the manual bind step; otherwise `download_source` is `MANUAL` and the policy is created in `QUOTED` status, the policy lifecycle's initial state.

Every policy also exposes computed fields that remain at their defaults until cancellation: `return_premium_cents` and `earned_premium_cents` both start at 0, `cancellation_date` and `cancellation_reason` both start null. Policies may be listed filtered by `account_id`, `product_id`, `writing_producer_id`, `renewed_from_policy_id`, and `status`.

### 3.4. Binding, Activation, and Commission Accrual

A `QUOTED` policy created manually must be **bound** before it can come on risk, an action reserved to the `Producer` role. Binding transitions the policy `QUOTED → BOUND` and is gated by the full compliance check, evaluated against the writing producer named on the policy. The carrier underwriting the policy's product must be `ACTIVE`; if it is not, the bind is rejected with `ERR_CARRIER_NOT_ACTIVE` (HTTP 422) — and recall that a `SUSPENDED` carrier blocks new binds for exactly this reason. The writing producer must hold a license whose computed status is `ACTIVE` matching both the policy's `state_code` and the product's `line_of_business`; absent such a license the bind is rejected with `ERR_LICENSE_NOT_ACTIVE` (HTTP 422). And an appointment with status `ACTIVE` must exist for the combination of that writing producer, the product's carrier, and the policy's `state_code`; absent it, the bind is rejected with `ERR_NOT_APPOINTED` (HTTP 422). Among these three business checks the carrier-active check is evaluated first, then the license check, then the appointment check. Binding also requires `expected_policy_version` and increments the policy's `version`.

Once bound, a policy is brought **active** by an `AccountManager`, transitioning `BOUND → ACTIVE`. Activation is allowed only when the current moment is at or after the policy's `effective_date`, and it requires `expected_policy_version`. Activation is the pivotal moment for commission: all of the policy's commission-split rows transition from `DRAFT` to `LOCKED` (a cascade down to the splits, each becoming immutable), the writing producer's commission accrual is computed (see §3.5) and becomes eligible to roll into the next open commission statement, and the owning account's `active_policy_count` is recomputed and bubbled up. The policy's `version` increments. The activation timestamp is the moment used later to decide which statement period a policy's commission belongs to.

### 3.5. Commission Splits and the Accrual Calculation

The agency commission a policy earns is divided among producers through **commission splits**. Either an `AgencyAdmin` or a `Producer` adds a split by supplying the `policy_id`, the receiving `producer_id`, a `split_pct` (a fraction strictly greater than 0 and at most 1), and a `role` of `WRITING`, `SERVICING`, or `OVERRIDE`. A split is created in `DRAFT` status; it locks to `LOCKED` only when the policy first becomes `ACTIVE`, after which it is immutable. Adding a split also requires `expected_policy_version` matching the policy's current `version` (the optimistic-concurrency guard of §2.9) and increments that `Policy.version`. A split may not target a producer whose status is `INACTIVE`; such an attempt is rejected with `ERR_PRODUCER_INACTIVE` (HTTP 422). The `WRITING` and `SERVICING` shares on a policy together represent the full agency commission and so their `split_pct` values may sum to at most 1.0; an `OVERRIDE` split is paid on top and is excluded from that cap. Adding a split whose inclusion would push the sum of `WRITING` plus `SERVICING` percentages above 1.0 is rejected with `ERR_SPLIT_OVER_ALLOCATED` (HTTP 422). Splits may be listed filtered by `policy_id` and `producer_id`.

The **producer commission accrual** is computed at the moment a policy transitions `BOUND → ACTIVE`, against the policy's now-locked splits. It proceeds in four steps. First, the base agency rate is selected by term kind: if the policy's `term_kind` is `NEW_BUSINESS`, the base rate is the product's `new_business_commission_pct` when that override is not null, and otherwise the carrier's `default_new_business_commission_pct`; if the `term_kind` is `RENEWAL`, the base rate is instead the product's `renewal_commission_pct` when not null, and otherwise the carrier's `default_renewal_commission_pct` (renewal rates are normally the lower of the two). Second, the agency commission on the term is the policy's `annual_premium_cents` multiplied by that base rate, rounded half-up to whole cents. Third, a volume-tier multiplier is applied based on this policy's own `annual_premium_cents`: when the annual premium is below one thousand dollars (that is, below 100,000 cents) the multiplier is 1.00; when it is at least one thousand dollars but below five thousand dollars (at least 100,000 cents and below 500,000 cents) the multiplier is 1.05; and when it is at least five thousand dollars (500,000 cents or more, with the boundary value of exactly 500,000 cents falling in this top tier) the multiplier is 1.10 — the post-tier agency commission is the previously rounded agency commission multiplied by the chosen multiplier, rounded half-up to whole cents again. Fourth, each producer's per-split accrual is that post-tier agency commission multiplied by the split's `split_pct`, rounded half-up to whole cents independently for each split line. Because every line is rounded on its own before any summation, a statement that later totals a producer's lines sums already-rounded figures rather than rounding a grand total.

### 3.6. Cancellation, Return Premium, and Chargeback

An `ACTIVE` (or `REINSTATED`) policy may be **cancelled** by an `AccountManager`, transitioning it to `CANCELLED`. The request supplies a `cancellation_date` and a `cancellation_reason` of `INSURED_REQUEST`, `NON_PAYMENT`, or `UNDERWRITING`, together with `expected_policy_version`. The `cancellation_date` must fall within the policy's term — at or after `effective_date` and strictly before `expiration_date`; a date outside that half-open window is rejected with `ERR_CANCEL_OUT_OF_TERM` (HTTP 422). On cancellation the policy's `status` becomes `CANCELLED`, its `cancellation_date` and `cancellation_reason` are recorded, and the return premium is computed as described next; the `version` increments.

The **return premium** is the unearned portion of premium refunded to the insured, and it is computed in one of two variants. First compute two whole-day spans: the term length in whole days from the policy's `effective_date` to its `expiration_date`, and the unearned span in whole days from the `cancellation_date` (counted as still unearned) to the `expiration_date`. The applicable basis is `PRO_RATA` whenever the cancellation reason is `NON_PAYMENT` — a non-payment cancellation always refunds pro-rata regardless of the product's configured basis — and otherwise is the product's own `cancellation_basis`. Under the `PRO_RATA` variant, the return premium is the policy's `annual_premium_cents` multiplied by the unearned days and divided by the term days, with that single result rounded half-up to whole cents; the full unearned fraction is refunded with no penalty. Under the `SHORT_RATE` variant, the carrier retains a short-rate penalty: first take the same pro-rata unearned amount (annual premium times unearned days divided by term days), multiply it by one minus the short-rate penalty of 0.10 — that is, refund ninety percent of the pro-rata unearned amount — and round that result half-up to whole cents once at the end. In both variants rounding is applied exactly once, at the end of the chosen branch. The retained `earned_premium_cents` is then the policy's `annual_premium_cents` minus the computed `return_premium_cents`.

Cancellation also drives two cross-entity movements. A `RETURN_PREMIUM_REFUND` ledger entry for the negative of the return premium posts to the trust account held for the policy's state, moving that money out of trust and triggering recomputation of the account's `balance_cents`. And the writing producer's commission on this policy is clawed back in proportion to the unearned fraction: the chargeback reverses the share of accrued commission corresponding to the part of the term that is being refunded, so a policy refunded halfway through its term claws back roughly half its commission. The owning account's `active_policy_count` is recomputed.

### 3.7. Reinstatement as Compensation

A `CANCELLED` policy may be **reinstated** by an `AccountManager`, transitioning `CANCELLED → REINSTATED`, provided the cancellation can be undone: reinstatement is allowed only while the current moment is strictly before the policy's `expiration_date` and only when the `cancellation_reason` was not `UNDERWRITING` (underwriting cancellations are never reinstatable). A request violating either condition is rejected with `ERR_REINSTATE_NOT_ALLOWED` (HTTP 422). Reinstatement requires `expected_policy_version`. A reinstated policy behaves exactly like an `ACTIVE` policy for coverage and renewal eligibility.

Reinstatement is a precise compensation of the cancellation's financial effects. The policy's `return_premium_cents` and `earned_premium_cents` are both reset to 0. A reversing `PREMIUM_RECEIPT` ledger entry for the positive of the previously refunded amount posts to the state's trust account, restoring exactly the money the refund removed and triggering recomputation of `balance_cents` — the compensation invariant that leaves the ledger whole. The prior commission chargeback is reversed, restoring the producer's accrual to its pre-cancellation value. And the account's `active_policy_count` is recomputed. The policy's `version` increments.

### 3.8. The Renewal Pipeline

As a policy nears the end of its term, it enters the renewal pipeline. A renewal may be opened only inside the **renewal window**, which opens sixty days before expiration: the current moment must be at or after the policy's `expiration_date` minus sixty days. An `AccountManager` opens a **renewal task** for an `ACTIVE` or `REINSTATED` policy by supplying the `policy_id` and a `target_effective_date` (the intended start of the renewal term, typically the expiring policy's `expiration_date`). Opening a renewal task before the window opens is rejected with `ERR_RENEWAL_WINDOW_CLOSED` (HTTP 422), and at most one non-terminal renewal task — one whose stage is neither `COMPLETED` nor `LOST` — may exist for a given policy at a time; a second is rejected with `ERR_DUPLICATE_RENEWAL_TASK` (HTTP 409). For this creation these checks run in a fixed order that overrides the generic §2.10 sequencing: the renewal-window check first, then the duplicate-non-terminal-task check, and only last the policy-state eligibility check (the policy must be `ACTIVE` or `REINSTATED`, otherwise `ERR_INVALID_STATE`, HTTP 409). Consequently a second open against a policy already moved to `PENDING_RENEWAL` by its first task reports `ERR_DUPLICATE_RENEWAL_TASK`, not the `ERR_INVALID_STATE` that the policy's non-`ACTIVE`/`REINSTATED` status would otherwise raise. Creating the task moves the linked policy from `ACTIVE` (or `REINSTATED`) to `PENDING_RENEWAL` and increments the policy's `version`; a policy in `PENDING_RENEWAL` still counts toward its account's `active_policy_count`. The renewal task itself is created in stage `IDENTIFIED`. Renewal tasks may be listed filtered by `policy_id`, `successor_policy_id`, and `stage`.

The renewal task advances through stages `IDENTIFIED → REVIEW → QUOTED → OFFERED`, one forward step per advance action by the `AccountManager`. The very first advance, `IDENTIFIED → REVIEW`, is permitted only while the linked policy is in `PENDING_RENEWAL`; the later forward advances carry no additional precondition. From the `OFFERED` stage the task can cycle back: a **re-quote** moves it `OFFERED → REVIEW` to model a renegotiation round, incrementing the task's `requote_count` each time it does so (the count starts at 0 and rises by one on every such cycle). A task may also be marked **lost** — moving to the terminal `LOST` stage — from either `REVIEW` or `OFFERED`. Every advance, re-quote, completion, and loss increments the task's `version`.

Completing a renewal task is the moment the successor policy is born. **Completion** is available only from the `OFFERED` stage, requires that the linked policy still be in `PENDING_RENEWAL`, and requires `expected_renewaltask_version`. The `AccountManager` supplies the successor term's `annual_premium_cents`, `effective_date`, and `expiration_date`. The successor term must abut the expiring term exactly: the successor's `effective_date` must equal the expiring policy's `expiration_date` to the instant — adjacency, not mere non-overlap. A successor that would start before the prior term ends (an overlap) or after it ends (a gap) is rejected with `ERR_RENEWAL_TERM_NOT_ADJACENT` (HTTP 422). On completion, a successor `Policy` is created directly in `BOUND` status with `term_kind` set to `RENEWAL` and `renewed_from_policy_id` pointing at the expiring policy (extending the renewal chain); the task's `successor_policy_id` is set to the new policy's id; the task's stage becomes `COMPLETED`; the expiring policy is cascaded `PENDING_RENEWAL → EXPIRED`; and the owning account's `active_policy_count` is recomputed.

A policy that does not renew leaves `PENDING_RENEWAL` one of two ways, both driven by the `AccountManager`. It may simply **expire** to the terminal `EXPIRED` state once the current moment has reached or passed its `expiration_date`, recomputing the account count and incrementing the policy's `version`. Or, when its renewal task has been marked `LOST`, it may be **non-renewed** to the terminal `NON_RENEWED` state — this transition requires that the linked renewal task be in stage `LOST` and requires `expected_policy_version`; it likewise recomputes the account count and increments the policy's `version`.

### 3.9. Trust Accounting and Manual Ledger Postings

A `TrustAccountant` establishes a **trust account** for a state with a display `name`, the two-letter `state_code` it is held for, and an optional `minimum_balance_cents` floor (defaulting to 0, and never negative). The account's `balance_cents` begins at 0 and is, thereafter, always the sum of its postings. Beyond the system-generated entries that cancellation, reinstatement and commission payment produce, a `TrustAccountant` may post a **manual ledger entry** — for instance an `OPENING_BALANCE` to seed a freshly opened account, or a `PREMIUM_RECEIPT` recording premium collected from an insured. A manual posting supplies the `entry_type`, the signed `amount_cents`, an optional `policy_id` relating the movement to a policy (null for opening-balance entries), and `expected_trustaccount_version` for the optimistic-concurrency guard. The sign of `amount_cents` must agree with the type as described in §2.6. Posting an entry recomputes the account's `balance_cents` and increments the account's `version`; and a posting that would drop `balance_cents` below the account's `minimum_balance_cents` is rejected with `ERR_TRUST_MINIMUM_BREACH` (HTTP 422). Ledger entries can be listed for a given trust account, and across the system filtered by `policy_id`, `trust_account_id`, and `entry_type`.

### 3.10. Commission Statements: Roll-up, Finalize, Pay

A **commission statement** pays a producer for a period. A `TrustAccountant` opens one by naming the `producer_id` and the period bounds `period_start` (inclusive) and `period_end` (exclusive); `period_start` must be strictly before `period_end`, or creation fails with `ERR_INVALID_DATE_RANGE`. A statement begins `OPEN`, and while open its figures are recomputed live on every read. Statements may be listed filtered by `producer_id` and `status`.

The **statement roll-up** computes three figures. The `gross_commission_cents` is the sum, over the producer's `LOCKED` splits whose policy became `ACTIVE` within the period (its activation timestamp falling at or after `period_start` and strictly before `period_end`), of each split's per-line producer accrual computed exactly as in §3.5 — already-rounded per-line figures summed, not a re-rounded total. The `chargeback_cents` is the sum, over the producer's splits on policies that were cancelled within the period (their `cancellation_date` falling at or after `period_start` and strictly before `period_end`), of each split's accrual multiplied by the policy's return-premium fraction — that is, multiplied by `return_premium_cents` divided by `annual_premium_cents` — with each such per-policy clawback rounded half-up to whole cents before summation. The `net_payable_cents` is then `gross_commission_cents` minus `chargeback_cents`, which may be negative when chargebacks in the period exceed accruals.

A statement is **finalized** by a `TrustAccountant`, transitioning `OPEN → FINALIZED`; this freezes `gross_commission_cents`, `chargeback_cents`, and `net_payable_cents` at their currently computed values so they no longer move even if underlying policies later cancel. Finalization is permitted only once the period has ended — the statement's `period_end` must be at or before the current moment, otherwise it is rejected with `ERR_VALIDATION_PERIOD_NOT_ENDED` (HTTP 422) — and requires `expected_commissionstatement_version`. A finalized but unpaid statement may be **reopened** by a `TrustAccountant`, transitioning `FINALIZED → OPEN` so an accountant can correct a premature finalize; this is permitted only while the statement is `FINALIZED` (not yet `PAID`), requires `expected_commissionstatement_version`, and returns the statement to live recomputation on its next read.

Finally, a `FINALIZED` statement is **paid** by a `TrustAccountant`, transitioning `FINALIZED → PAID`. Payment names the `trust_account_id` to disburse from and supplies `expected_commissionstatement_version`. A statement whose `net_payable_cents` is zero or negative cannot be paid and is rejected with `ERR_NOTHING_PAYABLE` (HTTP 422). Payment posts a `COMMISSION_DISBURSEMENT` ledger entry for the negative of `net_payable_cents` to the named trust account and recomputes that account's `balance_cents`; the disbursement may not drop the balance below the account's `minimum_balance_cents` floor, and an attempt that would breach it is rejected with `ERR_TRUST_MINIMUM_BREACH` (HTTP 422). On success the statement's `status` becomes `PAID` and its `version` increments.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — every state transition, every activation, every posting against an existing account — return `200 OK`. Reads return `200 OK`. Refer to the §3 narratives for each operation's full request body, preconditions, and side effects; the table below gives only the routing contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/carriers` | Create a carrier (starts PROSPECTIVE) | AgencyAdmin |
| GET | `/carriers/{id}` | Fetch a carrier | AgencyAdmin, Producer, AccountManager, TrustAccountant |
| GET | `/carriers` | List carriers (optional status filter) | AgencyAdmin, Producer, AccountManager, TrustAccountant |
| POST | `/carriers/{id}/activate` | Activate a PROSPECTIVE or SUSPENDED carrier | AgencyAdmin |
| POST | `/carriers/{id}/suspend` | Suspend an ACTIVE carrier | AgencyAdmin |
| POST | `/carriers/{id}/terminate` | Terminate a carrier; cascades appointments | AgencyAdmin |
| POST | `/products` | Create a product under a carrier | AgencyAdmin |
| GET | `/products/{id}` | Fetch a product | AgencyAdmin, Producer, AccountManager, TrustAccountant |
| GET | `/products` | List products (filter by carrier_id, line_of_business) | AgencyAdmin, Producer, AccountManager, TrustAccountant |
| POST | `/producers` | Create a producer (ACTIVE) | AgencyAdmin |
| GET | `/producers/{id}` | Fetch a producer | AgencyAdmin, Producer, AccountManager, TrustAccountant |
| GET | `/producers` | List producers (optional status filter) | AgencyAdmin, Producer, AccountManager, TrustAccountant |
| POST | `/producers/{id}/deactivate` | Mark a producer INACTIVE | AgencyAdmin |
| POST | `/licenses` | Record a producer license | AgencyAdmin |
| GET | `/licenses/{id}` | Fetch a license (status computed at server-now) | AgencyAdmin, Producer, AccountManager, TrustAccountant |
| GET | `/licenses` | List licenses (filter by producer_id, state_code, line_of_business) | AgencyAdmin, Producer, AccountManager, TrustAccountant |
| POST | `/appointments` | Request a carrier appointment | AgencyAdmin |
| GET | `/appointments/{id}` | Fetch an appointment | AgencyAdmin, Producer, AccountManager, TrustAccountant |
| GET | `/appointments` | List appointments (filter by carrier_id, producer_id, state_code, status) | AgencyAdmin, Producer, AccountManager, TrustAccountant |
| POST | `/appointments/{id}/approve` | Approve a REQUESTED appointment | AgencyAdmin |
| POST | `/appointments/{id}/activate` | Activate an APPROVED appointment | AgencyAdmin |
| POST | `/appointments/{id}/terminate` | Terminate an appointment | AgencyAdmin |
| POST | `/accounts` | Create a book-of-business account | AgencyAdmin, AccountManager |
| GET | `/accounts/{id}` | Fetch an account (active_policy_count computed) | AgencyAdmin, Producer, AccountManager, TrustAccountant |
| GET | `/accounts` | List accounts (filter by servicing_producer_id, account_type) | AgencyAdmin, Producer, AccountManager, TrustAccountant |
| POST | `/policies` | Create a policy (manual QUOTED, or BOUND via ACORD download) | AgencyAdmin, Producer, AccountManager |
| GET | `/policies/{id}` | Fetch a policy with computed fields | AgencyAdmin, Producer, AccountManager, TrustAccountant |
| GET | `/policies` | List policies (filter by account_id, product_id, writing_producer_id, renewed_from_policy_id, status) | AgencyAdmin, Producer, AccountManager, TrustAccountant |
| POST | `/policies/{id}/bind` | Bind a QUOTED policy (license + appointment + carrier checks) | Producer |
| POST | `/policies/{id}/activate` | Activate a BOUND policy; lock splits, accrue commission | AccountManager |
| POST | `/policies/{id}/cancel` | Cancel a policy; compute return premium, post refund, charge back | AccountManager |
| POST | `/policies/{id}/reinstate` | Reinstate a CANCELLED policy; reverse refund and chargeback | AccountManager |
| POST | `/policies/{id}/expire` | Expire a PENDING_RENEWAL policy | AccountManager |
| POST | `/policies/{id}/non-renew` | Non-renew a PENDING_RENEWAL policy whose renewal task is LOST | AccountManager |
| POST | `/commission-splits` | Add a commission split to a policy (OCC on Policy.version) | AgencyAdmin, Producer |
| GET | `/commission-splits` | List commission splits (filter by policy_id, producer_id) | AgencyAdmin, Producer, AccountManager, TrustAccountant |
| GET | `/commission-splits/{id}` | Fetch one commission split | AgencyAdmin, Producer, AccountManager, TrustAccountant |
| POST | `/trust-accounts` | Create a premium trust account for a state | TrustAccountant |
| GET | `/trust-accounts/{id}` | Fetch a trust account (balance_cents computed) | AgencyAdmin, TrustAccountant |
| GET | `/trust-accounts` | List trust accounts (filter by state_code) | AgencyAdmin, TrustAccountant |
| POST | `/trust-accounts/{id}/entries` | Post a manual ledger entry (OCC on TrustAccount.version) | TrustAccountant |
| GET | `/trust-accounts/{id}/entries` | List ledger entries for a trust account | AgencyAdmin, TrustAccountant |
| GET | `/trust-ledger-entries` | List ledger entries (filter by policy_id, trust_account_id, entry_type) | AgencyAdmin, TrustAccountant |
| GET | `/trust-ledger-entries/{id}` | Fetch one ledger entry | AgencyAdmin, TrustAccountant |
| POST | `/commission-statements` | Open a commission statement for a producer over a period | TrustAccountant |
| GET | `/commission-statements/{id}` | Fetch a statement (OPEN recomputes; FINALIZED/PAID frozen) | AgencyAdmin, Producer, TrustAccountant |
| GET | `/commission-statements` | List statements (filter by producer_id, status) | AgencyAdmin, Producer, TrustAccountant |
| POST | `/commission-statements/{id}/finalize` | Freeze a statement's figures (period must have ended) | TrustAccountant |
| POST | `/commission-statements/{id}/reopen` | Revert a FINALIZED (unpaid) statement to OPEN | TrustAccountant |
| POST | `/commission-statements/{id}/pay` | Pay a FINALIZED statement; post a disbursement to trust | TrustAccountant |
| POST | `/renewal-tasks` | Open a renewal task (moves policy to PENDING_RENEWAL) | AccountManager |
| GET | `/renewal-tasks/{id}` | Fetch a renewal task | AgencyAdmin, AccountManager, Producer |
| GET | `/renewal-tasks` | List renewal tasks (filter by policy_id, successor_policy_id, stage) | AgencyAdmin, AccountManager, Producer |
| POST | `/renewal-tasks/{id}/advance` | Advance a renewal task one forward stage | AccountManager |
| POST | `/renewal-tasks/{id}/requote` | Cycle an OFFERED task back to REVIEW | AccountManager |
| POST | `/renewal-tasks/{id}/complete` | Complete an OFFERED task; create successor policy, expire prior | AccountManager |
| POST | `/renewal-tasks/{id}/lose` | Mark a renewal task LOST | AccountManager |
| POST | `/_clock/set_current_utc` | Test-driving: set the server's authoritative current_utc | AgencyAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_DUPLICATE | 409 |
| ERR_LICENSE_NOT_ACTIVE | 422 |
| ERR_NOT_APPOINTED | 422 |
| ERR_CARRIER_NOT_ACTIVE | 422 |
| ERR_INVALID_DATE_RANGE | 422 |
| ERR_PRODUCER_INACTIVE | 422 |
| ERR_SPLIT_OVER_ALLOCATED | 422 |
| ERR_CANCEL_OUT_OF_TERM | 422 |
| ERR_REINSTATE_NOT_ALLOWED | 422 |
| ERR_RENEWAL_WINDOW_CLOSED | 422 |
| ERR_DUPLICATE_RENEWAL_TASK | 409 |
| ERR_TRUST_MINIMUM_BREACH | 422 |
| ERR_NOTHING_PAYABLE | 422 |
| ERR_VALIDATION_PERIOD_NOT_ENDED | 422 |
| ERR_LICENSE_OVERLAP | 409 |
| ERR_RENEWAL_TERM_NOT_ADJACENT | 422 |
