# Rent-To-Own Home API — Product Requirements Document

## 1. Introduction

Rent-to-own (also called lease-purchase) arrangements sit awkwardly between two financial worlds: a tenancy that accrues rent month after month, and a future home purchase whose price is locked in advance. The economics are unforgiving and easy to get wrong by hand — a sliver of each monthly payment is meant to accrue as purchase credit, but only payments made on time should count toward what the buyer can ultimately apply at closing, and the moment a buyer misses too many payments the entire accrued credit can evaporate. This API provides the system of record for that arrangement, modelling the full journey from a landlord listing a home, through the drafting and activation of a lease-purchase agreement, the monthly rhythm of rent payments and the credit they earn, the disposition of maintenance work, and finally either the exercise of the purchase option and conversion to a mortgage, or the agreement's collapse into default or expiry.

The system is fundamentally a **ledger reconciliation** engine wrapped in a **compliance and audit** discipline. Every monetary figure is carried in integer cents to avoid floating-point drift, and the accrual of purchase credit is computed by rounding each period independently and then summing — never by summing raw figures and rounding once. Three parties interact with the system: the seller who owns the home and runs the agreement, the buyer-in-waiting who pays and ultimately exercises the option, and a neutral closing officer who converts a settled exercise into a mortgage. Because several of these parties may act on the same property concurrently, the system applies optimistic concurrency control at the one point where two agreements could collide over a single home.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that govern every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity under which they are acting. The system recognizes exactly three roles, spelled precisely as follows: `Landlord`, `Tenant`, and `EscrowAgent`. If the `X-User-Role` header is missing or carries a value that is not one of these three known roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the role is not permitted to perform the requested operation — or an ownership check fails — the request is rejected with `ERR_FORBIDDEN`.

Two of the three roles are backed by persisted entities, which ties `X-User-ID` to resource ownership. When `X-User-Role` is `Landlord`, `X-User-ID` is the `id` of the acting `Landlord`; ownership checks on any resource that references a `Landlord` (a `Property` via its `landlord_id`, or an `Agreement` via its `landlord_id`) compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `Tenant`, `X-User-ID` is the `id` of the acting `Tenant`; ownership checks on any resource that references a `Tenant` (an `Agreement` via its `tenant_id`, and the `RentPayment`, `MaintenanceTicket`, and `OptionExercise` rows under such an agreement) compare the resource's owning tenant to `X-User-ID`. When `X-User-Role` is `EscrowAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. The escrow agent is a neutral closer whose sole privileged action is converting a settled exercise into a mortgage.

Authorization is evaluated ahead of any business logic. The presence and validity of the role header is checked first; the role's permission for the operation (including the ownership requirement for the two entity-backed roles) is checked next; only then does the system proceed to resource existence and the remaining business rules.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order.

List responses carry the pagination bookkeeping in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource in this system — `Landlord`, `Tenant`, `Property`, `Agreement`, `RentPayment`, `MaintenanceTicket`, `OptionExercise`, and `Mortgage` — carries a standard set of system-managed fields:

- **`id`** — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at`** — an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was first created.
- **`updated_at`** — an ISO 8601 UTC timestamp recording the most recent modification. It is refreshed on every mutation of the resource.
- **`version`** — a system-managed integer that begins at its initial value and increments by one on every mutation of the resource. It underpins optimistic concurrency control (§2.7).

All eight entity types in this system carry the full set above; none is created as an immutable, version-less record. Whenever a derived value is recomputed and persisted — for example, an `Agreement`'s accrual figures, or a `Property`'s status flipping during a cascade — that recomputation counts as a mutation: it refreshes `updated_at` and increments `version`.

### 2.5. Money, Precision, and the Round-Then-Sum Discipline

All monetary amounts are stored and returned as integer cents; there are no fractional cents and no floating-point currency values in any response body. Wherever a calculation produces a non-integer cent amount, the result is rounded **half up** to the nearest whole cent.

The order of rounding is contractual and must not be reorganized for convenience. Purchase credit is computed **per payment first, then summed**: each `RentPayment` independently rounds its own credit portion to whole cents, and the agreement-level accruals are the sum of those already-rounded per-period values. The system never sums raw `amount_cents` × `credit_pct` products across periods and rounds once at the end. The maintenance cost split, by contrast, involves no rounding at all — it is a pure split at an integer threshold breakpoint, and the tenant's share plus the landlord's share always reconstitutes the full cost exactly, with no drift. The settlement and amortization calculations each round half up at the single step noted in their respective rules (§3).

### 2.6. Hierarchical Consistency and Cascading State

The central contract is the `Agreement`; a `Property` is its subject, and `RentPayment`, `MaintenanceTicket`, `OptionExercise`, and `Mortgage` rows hang off it. When an agreement changes state, the change frequently cascades to the property and, in the default case, to child payment rows — and each cascaded mutation is a genuine mutation of the affected resource, bumping that resource's `version` and refreshing its `updated_at`.

Activating an agreement takes its property under agreement: the property moves from `AVAILABLE` to `UNDER_AGREEMENT`, which itself increments the property's `version` by one. Converting an exercised agreement sells the property: it moves from `UNDER_AGREEMENT` to `SOLD`, again incrementing the property's `version`. When an agreement collapses into default or expiry, the property is released back from `UNDER_AGREEMENT` to `AVAILABLE`, incrementing the property's `version`. These property transitions are driven entirely by the system as cascades from the agreement's lifecycle; there is no direct endpoint that flips a property's status on its own. The `Property` lifecycle therefore runs `AVAILABLE → UNDER_AGREEMENT`, then either `UNDER_AGREEMENT → SOLD` (terminal) or `UNDER_AGREEMENT → AVAILABLE` (released for a future agreement).

### 2.7. Optimistic Concurrency Control on Property Activation

Because two distinct agreements can be drafted against the same available home, the moment one of them is activated must be protected against a stale view of the property. Activating a draft agreement requires the request to carry `expected_property_version`, a non-optional field that must equal the target property's current `version`. If another writer has advanced the property's version since the activating client last observed it — for example, a competing agreement on the same property was already activated and legitimately took the home under agreement — the activation is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a property it has not freshly observed. This stale-version check is evaluated **before** the property-availability and agreement-state business checks, so an activation carrying a mismatched `expected_property_version` fails with 412 even when the property has in the meantime become `UNDER_AGREEMENT`. Activation is the only endpoint that takes a version field; no other operation in the system accepts or requires one.

### 2.8. Validation Ordering and the Error Precedence Ladder

When several checks could fire on a single request, they are evaluated in a fixed priority order so that the returned error is deterministic. The ladder, from highest precedence downward, is:

1. **Authentication** — the `X-User-Role` header must be present and a known role, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the role must be permitted for the operation per §2.1, and an entity-backed actor must own the targeted resource, else `ERR_FORBIDDEN` (403).
3. **Existence** — every resource referenced by the path or body must exist; these are validated left-to-right, and the first missing one yields `ERR_NOT_FOUND` (404).
4. **Request well-formedness** — on writes, required body fields must be present and well-typed, enum values must be in their allowed sets, and numeric ranges must hold (for example `credit_pct` between 0 and 1 inclusive, `credit_score` between 300 and 850 inclusive, and every `*_cents` amount non-negative); a violation yields `ERR_INVALID_REQUEST` (422).
5. **Referential consistency** — foreign-key relationships that must agree (the property's landlord matching the acting landlord on agreement issuance, and the option exercise belonging to the path agreement on conversion) yield `ERR_REFERENCE_MISMATCH` (409) when inconsistent.
6. **Optimistic concurrency** — on activation, `expected_property_version` must equal the current property `version`, else `ERR_STALE_VERSION` (412); as noted in §2.7 this is deliberately ranked above the property-availability and state checks below it.
7. **State** — the target resource must be in the correct state for the requested transition, else `ERR_INVALID_STATE` (409).
8. **Domain-specific business rules** — the property-availability gate, temporal option windows, safety gates, threshold gates, and uniqueness, each with its own error identifier as detailed in §3.

Within the domain-specific tier, the property-availability check on activation (`ERR_PROPERTY_NOT_AVAILABLE`, 409) is evaluated only after the OCC version match has passed.

### 2.9. Nested Resource Retrieval and Path Validation

Several create operations are addressed under a parent agreement (for example, scheduling a rent payment, filing a maintenance ticket, exercising the option, or converting to a mortgage all name an agreement in the path). For any such request, the path identifiers are validated left-to-right: the parent agreement's existence is confirmed before any child resource is located or created, and the first identifier in the path that does not resolve to an existing resource produces `ERR_NOT_FOUND`. Child resources such as rent payments, maintenance tickets, option exercises, and mortgages are also individually fetchable and listable by their own identifiers; list endpoints accept filters that narrow results to a particular agreement (and, where noted, to other foreign keys).

### 2.10. The Test-Driving Clock

Temporal checks in this system — whether an option exercise falls on or before its deadline, and whether an agreement is past its deadline for manual expiry — are evaluated against the server's logical current UTC time rather than wall-clock time. An administrative test-driving capability allows any authenticated role to set the server's current UTC clock to a supplied instant via the `to_iso8601` field. This capability has no state machine of its own; it simply repositions the clock that the temporal business rules consult.

## 3. Business Logic & Workflows

### 3.1. Parties and the Listed Home

Three parties bootstrap the system. A `Landlord` registers themselves by supplying a `legal_name`, an `email` (which must be unique among landlords), and a `payout_account_ref`, an opaque external reference to where sale proceeds are eventually routed. A `Tenant` registers by supplying a `legal_name`, an `email` (unique among tenants), and a `credit_score` — a FICO-style integer that must lie between 300 and 850 inclusive, and which later gates eligibility to convert into a mortgage. Both `Landlord` and `Tenant` records are fetchable individually by any of the three roles.

A landlord lists a home for rent-to-own by creating a `Property`. The creation payload names the `landlord_id` (which must identify the acting landlord), the `address` (unique among properties), and the `list_price_cents`, the owner's asking price in integer cents, which must be greater than zero. A new property is born in the `AVAILABLE` state; its `status` is system-managed and walks the values `AVAILABLE`, `UNDER_AGREEMENT`, and `SOLD` as agreements come and go. Properties are individually fetchable and listable; the list endpoint can be filtered by `landlord_id` and by `status`.

### 3.2. Drafting and Activating the Lease-Purchase Agreement

The heart of the system is the `Agreement`. A landlord drafts one against an available home, and the draft fixes the entire commercial bargain up front. The drafting payload supplies the `property_id` of the subject home and the `tenant_id` of the buyer-in-waiting, along with the `locked_price_cents` — the purchase price held fixed for the option term, which must be greater than zero. The landlord declares the `option_fee_cents`, an up-front option fee that must be at least zero, and `option_fee_creditable`, a boolean that decides whether that fee credits toward the purchase at exercise; when omitted it defaults to true. The recurring economics are set by `monthly_payment_cents` (the total the tenant pays each month, rent plus credit combined, which must be greater than zero) and `credit_pct`, the fraction of each monthly payment that accrues as purchase credit, which must be between 0 and 1 inclusive.

Several agreement parameters govern protective ceilings and tolerances and round out the draft. `max_credit_pct` caps the total credit that can ever be applied, expressed as a fraction of `locked_price_cents`; it must be greater than 0 and at most 1, and defaults to 0.20 when omitted. `grace_days` is the number of days after a payment's due date within which a payment still earns its credit; it must be at least zero and defaults to 5. `maintenance_threshold_cents` is the per-ticket cost split point — the tenant bears repair cost up to this figure and the landlord bears any excess; it must be at least zero and defaults to 50000 (five hundred dollars). Finally the draft anchors the option clock with `lease_start`, an ISO 8601 UTC commencement timestamp, and `option_term_months`, the number of months the purchase option remains exercisable counting from `lease_start`, which must be at least 1.

When an agreement is created it is born in `DRAFT`. The system does not accept a landlord on the agreement directly; instead `landlord_id` is copied from the chosen property's `landlord_id` at creation, and the issuing landlord must in fact own that property — if the property's landlord does not match the acting landlord, the draft is rejected with `ERR_REFERENCE_MISMATCH`. At creation the system also computes the `option_deadline`, defined as `lease_start` advanced by `option_term_months` months; this is the instant after which an exercise is refused. A fetched agreement always reports its computed accrual fields freshly recomputed: `missed_payment_count` (the count of its forfeited payment rows), `gross_credit_accrued_cents` (the provisional credit pool), `available_credit_cents` (the finalized credit), and `option_deadline`. Agreements are listable with optional filters on `property_id`, `tenant_id`, `landlord_id`, and `status`.

Activation is the landlord's act of bringing the contract to life. It is permitted only when the agreement is in `DRAFT`; an attempt against any other agreement state is rejected with `ERR_INVALID_STATE`. As described in §2.7, activation carries `expected_property_version` and is gated first by the optimistic-concurrency match against the property's `version` (`ERR_STALE_VERSION`, 412). Once the version matches, the property must be `AVAILABLE`; if it is not, activation is rejected with `ERR_PROPERTY_NOT_AVAILABLE`. When both gates pass, the agreement transitions `DRAFT → ACTIVE`, its `option_deadline` is settled, and the cascade takes the property `AVAILABLE → UNDER_AGREEMENT` (which bumps the property's `version`); the agreement's own `version` increments as well.

### 3.3. The Monthly Rhythm: Scheduling Payments and Splitting Each Into Rent and Credit

Once an agreement is `ACTIVE`, the landlord schedules the monthly billing by creating `RentPayment` rows. Each scheduled period names a `period_index` — a 1-based month index within the lease that must be at least 1 — and a `due_date`, the ISO 8601 UTC date that period's payment is owed. The pair of agreement and `period_index` must be unique among non-superseded payment rows; scheduling a second row for an already-billed period is rejected with `ERR_DUPLICATE_PERIOD`. A scheduling payload may also carry `supersedes_payment_id`, a back-reference to an earlier `RentPayment` when this row re-bills a cured or forfeited period; superseded rows are excluded from uniqueness checks and from accrual sums. The payment row does not accept its own amount: `amount_cents` is copied from the agreement's `monthly_payment_cents` at creation.

At creation, the period's split is computed once. The credit portion, `credit_portion_cents`, is the payment amount multiplied by the agreement's `credit_pct`, rounded half up to whole cents. The rent portion, `rent_portion_cents`, is whatever remains — the payment amount minus the credit portion. This per-period rounding is the contractual unit of rounding: each period rounds its own credit portion before any summing happens. A freshly scheduled payment is born `PENDING`, and its `credit_portion_cents` immediately joins the agreement's provisional credit pool — `gross_credit_accrued_cents` rises by that period's credit portion. Its `late_fee_cents` starts at zero, and a `paid_at` timestamp is not yet set.

Provisional and final credit are two different sums, and the distinction is the spine of the whole product. The provisional figure, `gross_credit_accrued_cents`, is optimistic: it is the sum of `credit_portion_cents` over every payment row whose status is `PENDING`, `PAID`, or `LATE` — every row that has not been forfeited — counting credit as if all of it will ultimately be earned. The finalized figure, `available_credit_cents`, is strict: it is the sum of `credit_portion_cents` over only those rows in `PAID` status. Rows in `LATE` and `FORFEITED` contribute nothing to the finalized figure. Both sums are taken over the already-rounded per-period values, in keeping with the round-then-sum discipline, and superseded rows are excluded from both.

### 3.4. Recording, Curing, and Forfeiting Payments

When a tenant remits, they record the payment by supplying the `paid_at` timestamp. Recording is permitted only on a `PENDING` row (otherwise `ERR_PAYMENT_NOT_PENDING`) and only while the agreement is `ACTIVE` (otherwise `ERR_AGREEMENT_NOT_ACTIVE`). The outcome forks on how late the money arrived. The system measures lateness as the whole number of days between the due date and the payment instant, taking the floor of the elapsed time in days. If that number of days late is at most the agreement's `grace_days`, the payment is on time: the row transitions `PENDING → PAID`, its `late_fee_cents` stays zero, its `credit_portion_cents` is earned, and the agreement's `available_credit_cents` rises by that credit portion. If instead the days late exceed `grace_days`, the row transitions `PENDING → LATE`: a late fee is assessed, the credit is not yet earned, and `available_credit_cents` is unchanged. The boundary is exact — a payment exactly `grace_days` days late is still on time and becomes `PAID` with no fee, whereas a payment one day beyond `grace_days` becomes `LATE` with a fee.

The late fee, `late_fee_cents`, when assessed, is the payment amount multiplied by a late-fee rate of five percent, rounded half up to whole cents. (On the on-time `PENDING → PAID` branch the fee is zero.)

A `LATE` payment is not lost — it can be cured. The landlord cures a late payment, which transitions it `LATE → PAID`; this is permitted only on a row currently in `LATE` (otherwise `ERR_PAYMENT_NOT_LATE`) and only while the agreement is `ACTIVE` (otherwise `ERR_AGREEMENT_NOT_ACTIVE`). On cure, the period's `credit_portion_cents` is now earned and is added to the agreement's `available_credit_cents`, compensating for the credit that was withheld while the row sat in `LATE`.

When a period is missed past any chance of cure, the landlord forfeits it. Forfeiture can act on a row in `PENDING` (otherwise `ERR_PAYMENT_NOT_PENDING` when the row is not pending) or on a row in `LATE` (otherwise `ERR_PAYMENT_NOT_LATE` when the row is not late), and in both cases only while the agreement is `ACTIVE` (otherwise `ERR_AGREEMENT_NOT_ACTIVE`). Both the `PENDING → FORFEITED` and the `LATE → FORFEITED` transition behave identically: the row moves to `FORFEITED`, its credit portion is lost, the agreement's `missed_payment_count` rises by one, and the agreement's `gross_credit_accrued_cents` falls by that period's `credit_portion_cents` as the forfeited row leaves the provisional pool. A `RentPayment` reaches its terminal life in either `PAID` or `FORFEITED`. Payments are individually fetchable and listable, with optional filters on `agreement_id`, `supersedes_payment_id`, and `status`.

### 3.5. Maintenance Tickets and the Threshold Split

A tenant files maintenance under an active agreement by opening a `MaintenanceTicket` with a `summary` describing the issue and an `estimated_cost_cents`, the initial repair estimate, which must be at least zero. A new ticket is born `OPEN`. From there the landlord disposes of it: a ticket may be rejected outright, or approved, and an approved ticket is later resolved with the real cost.

Approval is permitted only on an `OPEN` ticket (otherwise `ERR_TICKET_NOT_OPEN`) and only while the agreement is `ACTIVE` (otherwise `ERR_AGREEMENT_NOT_ACTIVE`); it transitions the ticket `OPEN → APPROVED` and computes the cost split from the **estimate**. Rejection is also permitted only on an `OPEN` ticket (otherwise `ERR_TICKET_NOT_OPEN`); it transitions `OPEN → REJECTED` and is terminal. Resolution acts only on an `APPROVED` ticket (otherwise `ERR_TICKET_NOT_APPROVED`); the resolving call supplies `actual_cost_cents` — the final repair cost, which must be at least zero — transitions the ticket `APPROVED → RESOLVED`, and recomputes the split from the **actual** cost, overriding the provisional estimate-based split. `RESOLVED` and `REJECTED` are the two terminal states.

The split itself is a clean cut at the agreement's `maintenance_threshold_cents`. For whichever cost figure applies — the `estimated_cost_cents` at approval, or the `actual_cost_cents` at resolution — the tenant's portion, `tenant_share_cents`, is the smaller of that cost and the threshold, and the landlord's portion, `landlord_share_cents`, is the cost minus the threshold but never below zero. By construction the two shares always sum exactly to the full cost, with no rounding and no drift. Maintenance tickets are individually fetchable and listable with optional filters on `agreement_id` and `status`.

### 3.6. Exercising the Purchase Option and Settling the Numbers

The tenant exercises the purchase option on their own active agreement by supplying the `exercised_at` timestamp. Three gates guard the exercise, each with its own rejection. The agreement must be `ACTIVE` (otherwise `ERR_AGREEMENT_NOT_ACTIVE`). The `exercised_at` instant must be on or before the agreement's `option_deadline`; an exercise after the deadline is rejected with `ERR_OPTION_EXPIRED`. And the agreement must carry no outstanding default risk — its `missed_payment_count` must be exactly zero; if any payment has been forfeited, the exercise is blocked with `ERR_OPTION_BLOCKED_BY_DEFAULT`.

A successful exercise creates an `OptionExercise` row in `PENDING` and immediately settles it, freezing the closing numbers and advancing the agreement `ACTIVE → EXERCISED`. The settlement is computed in a pinned order, each step depending only on those before it. First, `locked_price_snapshot_cents` is snapshotted from the agreement's `locked_price_cents`. Second, the credit ceiling `max_credit_cap_cents` is computed as that snapshot price multiplied by the agreement's `max_credit_pct`, rounded half up to whole cents. Third, the credit actually applied, `credit_applied_cents`, is the smaller of the agreement's finalized `available_credit_cents` (taken at the exercise instant) and that cap — so the buyer can never apply more credit than the ceiling permits. Fourth, the option-fee credit, `option_fee_credit_cents`, is the agreement's `option_fee_cents` when `option_fee_creditable` is true, and zero otherwise. Fifth and finally, the `net_due_at_closing_cents` is the snapshot price minus the applied credit minus the option-fee credit. The settled exercise moves `PENDING → SETTLED`, and its frozen `available_credit_cents`-derived figure is what later funds the mortgage. The exercise record's `status` walks `PENDING`, `SETTLED`, and `VOIDED`. Option exercises are individually fetchable and listable, filterable by `agreement_id` and `status`.

### 3.7. Conversion to Mortgage at Closing

The escrow agent closes the deal by converting an exercised agreement into a `Mortgage`. The conversion payload names the `option_exercise_id` of the settled exercise being closed, plus the financing terms: `annual_rate_bps`, the annual interest rate in basis points (where 100 basis points equal one percent), which must be at least zero; and `term_months`, the amortization term in months, which must be at least 1. Three preconditions gate conversion: the agreement must be `EXERCISED` (otherwise `ERR_AGREEMENT_NOT_EXERCISED`); a `SETTLED` option exercise must exist for the agreement and the supplied `option_exercise_id` must in fact belong to the path agreement (a mismatch is `ERR_REFERENCE_MISMATCH`); and the tenant's `credit_score` must be at least 620, the minimum conversion score — a lower score is rejected with `ERR_CREDIT_SCORE_TOO_LOW`.

On success the system mints a `Mortgage` in `ACTIVE` — the only state a mortgage ever holds. Its `principal_cents` is copied from the settled exercise's `net_due_at_closing_cents`. Its `monthly_installment_cents` is the amortized monthly payment derived from the principal, the annual rate, and the term. The monthly rate is the annual basis-point rate divided by ten thousand to make it a fraction, then divided by twelve to make it monthly. When that monthly rate is zero, the monthly installment is simply the principal divided by the number of months, rounded half up to whole cents. When the monthly rate is positive, the monthly installment is the principal multiplied by the monthly rate, multiplied by the quantity one plus the monthly rate raised to the power of the number of months, all divided by the quantity (one plus the monthly rate raised to the power of the number of months) minus one — rounded half up to whole cents on the final installment. Conversion advances the agreement `EXERCISED → CONVERTED` and cascades the property `UNDER_AGREEMENT → SOLD` (bumping the property's `version`), and increments the agreement's `version`. The mortgage references its origin through `agreement_id` and `option_exercise_id`; mortgages are individually fetchable and listable, filterable by `agreement_id`, `option_exercise_id`, and `status`.

### 3.8. Default, Expiry, and the Collapse of Credit

Two terminal collapses can befall an active agreement, and both release the property back to `AVAILABLE`. Default is the landlord's declaration that the tenant has failed too many times. A manual default is permitted only while the agreement is `ACTIVE` (otherwise `ERR_AGREEMENT_NOT_ACTIVE`) and only once the `missed_payment_count` has reached at least three (the maximum tolerated missed payments); a manual default attempted below that threshold is rejected with `ERR_DEFAULT_THRESHOLD_NOT_MET`. Declaring default transitions the agreement `ACTIVE → DEFAULTED` and triggers a punishing cascade: every non-terminal payment row — that is, every row still in `PENDING` or `LATE` — is forced to `FORFEITED`, all earned credit evaporates so that `available_credit_cents` is recomputed to zero, the property is released `UNDER_AGREEMENT → AVAILABLE` (bumping its `version`), and any `OptionExercise` still sitting in `PENDING` is voided to `VOIDED`. The agreement's `version` increments.

Expiry is the gentler collapse: an option that was never exercised and whose window has closed. Manual expiry is permitted only while the agreement is `ACTIVE` (otherwise `ERR_AGREEMENT_NOT_ACTIVE`) and only when the server's current clock is strictly past the agreement's `option_deadline`; an expiry attempted at or before the deadline is rejected with `ERR_OPTION_NOT_YET_EXPIRED`. Expiry transitions the agreement `ACTIVE → EXPIRED` and forces every non-terminal payment row (those in `PENDING` or `LATE`) to `FORFEITED`, then cascades the property `UNDER_AGREEMENT → AVAILABLE` (bumping its `version`) and increments the agreement's `version`. The terminal agreement states are `CONVERTED`, `DEFAULTED`, and `EXPIRED`, alongside the intermediate `EXERCISED` that precedes conversion.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — registering a party, listing a property, drafting an agreement, scheduling a payment, filing a ticket, exercising an option, or converting to a mortgage — return `201 Created`. Operations that modify an existing resource, including every state-transition action (activate, default, expire, record, cure, forfeit, approve, reject, resolve) and the clock control, return `200 OK`. The complete request and response semantics for each endpoint are specified in the workflow narratives of §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/landlords` | Register a landlord/seller | Landlord |
| GET | `/landlords/{id}` | Fetch a landlord | Landlord, Tenant, EscrowAgent |
| POST | `/tenants` | Register a tenant/buyer | Tenant |
| GET | `/tenants/{id}` | Fetch a tenant | Landlord, Tenant, EscrowAgent |
| POST | `/properties` | List a property for rent-to-own | Landlord |
| GET | `/properties/{id}` | Fetch a property | Landlord, Tenant, EscrowAgent |
| GET | `/properties` | List properties (filterable by landlord, status) | Landlord, Tenant, EscrowAgent |
| POST | `/agreements` | Draft a lease-purchase agreement | Landlord |
| GET | `/agreements/{id}` | Fetch an agreement with computed accrual fields | Landlord, Tenant, EscrowAgent |
| GET | `/agreements` | List agreements (filterable by property, tenant, landlord, status) | Landlord, Tenant, EscrowAgent |
| POST | `/agreements/{id}/activate` | Activate a DRAFT agreement (OCC on property version) | Landlord |
| POST | `/agreements/{id}/default` | Declare default once missed payments reach threshold | Landlord |
| POST | `/agreements/{id}/expire` | Expire an unexercised agreement past its deadline | Landlord |
| POST | `/agreements/{id}/rent-payments` | Schedule a monthly rent payment row for a period | Landlord |
| GET | `/rent-payments/{id}` | Fetch a rent payment | Landlord, Tenant, EscrowAgent |
| GET | `/rent-payments` | List rent payments (filterable by agreement, supersession, status) | Landlord, Tenant, EscrowAgent |
| POST | `/rent-payments/{id}/record` | Tenant records payment; on-time PAID, past grace LATE | Tenant |
| POST | `/rent-payments/{id}/cure` | Landlord cures a LATE payment, restoring its credit | Landlord |
| POST | `/rent-payments/{id}/forfeit` | Landlord forfeits a missed PENDING/LATE payment | Landlord |
| POST | `/agreements/{id}/maintenance-tickets` | File a maintenance ticket against an agreement | Tenant |
| GET | `/maintenance-tickets/{id}` | Fetch a maintenance ticket | Landlord, Tenant, EscrowAgent |
| GET | `/maintenance-tickets` | List maintenance tickets (filterable by agreement, status) | Landlord, Tenant, EscrowAgent |
| POST | `/maintenance-tickets/{id}/approve` | Approve a ticket; compute estimate split | Landlord |
| POST | `/maintenance-tickets/{id}/reject` | Reject a ticket | Landlord |
| POST | `/maintenance-tickets/{id}/resolve` | Resolve an approved ticket with actual cost | Landlord |
| POST | `/agreements/{id}/option-exercises` | Exercise the purchase option; creates and settles an exercise | Tenant |
| GET | `/option-exercises/{id}` | Fetch an option exercise | Landlord, Tenant, EscrowAgent |
| GET | `/option-exercises` | List option exercises (filterable by agreement, status) | Landlord, Tenant, EscrowAgent |
| POST | `/agreements/{id}/mortgage` | Convert a settled exercise into a mortgage | EscrowAgent |
| GET | `/mortgages/{id}` | Fetch a mortgage | Landlord, Tenant, EscrowAgent |
| GET | `/mortgages` | List mortgages (filterable by agreement, exercise, status) | Landlord, Tenant, EscrowAgent |
| POST | `/_clock/set_current_utc` | Set the server's current UTC clock (test-driving) | Landlord, Tenant, EscrowAgent |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_REFERENCE_MISMATCH` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PROPERTY_NOT_AVAILABLE` | 409 |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 |
| `ERR_AGREEMENT_NOT_EXERCISED` | 409 |
| `ERR_OPTION_EXPIRED` | 409 |
| `ERR_OPTION_NOT_YET_EXPIRED` | 409 |
| `ERR_OPTION_BLOCKED_BY_DEFAULT` | 409 |
| `ERR_DEFAULT_THRESHOLD_NOT_MET` | 409 |
| `ERR_CREDIT_SCORE_TOO_LOW` | 409 |
| `ERR_DUPLICATE_PERIOD` | 409 |
| `ERR_PAYMENT_NOT_PENDING` | 409 |
| `ERR_PAYMENT_NOT_LATE` | 409 |
| `ERR_TICKET_NOT_OPEN` | 409 |
| `ERR_TICKET_NOT_APPROVED` | 409 |
| `ERR_STALE_VERSION` | 412 |
