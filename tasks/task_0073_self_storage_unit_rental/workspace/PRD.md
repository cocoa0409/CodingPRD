# Self-Storage Unit Rental API — Product Requirements Document

## 1. Introduction

This document specifies the backend service for a Public-Storage-style self-storage operation. The platform manages the full commercial lifecycle of a storage business: physical facilities and the individual units inside them, the tenants who rent those units, the leases that bind a tenant to a unit, the recurring billing that produces invoices, the payments that settle them, and the immutable financial ledger that underlies every dollar of activity. Storage is a cash-flow business with sharp legal edges, and the system is built to honor both halves of that reality at once.

Two concerns dominate the design. The first is a precise **pricing and billing engine**: rent is tiered by unit footprint, climate-controlled units carry a configurable premium, the first month is prorated to the move-in day, optional insurance premiums fold into each bill, late fees attach when an invoice ages past a grace boundary, and payments allocate across open invoices oldest-debt-first. The second is the **lien and auction legal process** that storage operators are statutorily entitled to pursue against a tenant who defaults: when a lease falls far enough past due, an administrator may send notice, file a lien, schedule a public sale, and ultimately auction the contents — with strict statutory waiting periods at each step and a surplus-distribution waterfall that returns any leftover proceeds to the tenant. A delinquent tenant always retains the right to cure or redeem until the gavel falls.

Because money and legal status must never drift, the system maintains a denormalized running balance on every lease alongside an append-only ledger that can be replayed for reconciliation, and it guards concurrent relocation and foreclosure actions with optimistic concurrency control so that one operator's stale view of a lease cannot silently overwrite another's completed work.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is missing or carries an unrecognized value, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the role is not permitted to perform the requested operation — or a tenant attempts to act on a lease that is not theirs — the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

There are exactly three roles, spelled exactly as follows: `FacilityManager`, `Tenant`, and `LienAdministrator`.

A `FacilityManager` is an operator who runs the day-to-day business: creating facilities and units, opening and activating leases, running billing cycles, waiving invoices, reversing payments, and orchestrating transfers. When `X-User-Role` is `FacilityManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it as an actor on operations it performs but does not compare it to any entity's `id`.

A `LienAdministrator` is a lien/auction officer who runs the foreclosure legal process and is deliberately segregated from facility-manager operations. When `X-User-Role` is `LienAdministrator`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.

A `Tenant` is the renter and is entity-backed. When `X-User-Role` is `Tenant`, `X-User-ID` is the `id` of the acting `Tenant`; ownership checks on any resource that references a tenant compare the resource's tenant foreign key to `X-User-ID`. A tenant may read and act only on leases whose `tenant_id` equals their own `id`, along with the invoices, payments, policies, auction proceedings, and transfer orders that belong to those leases. A tenant acting on another tenant's lease is rejected with `ERR_FORBIDDEN`.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` defaults to 0 and has no upper bound. Results are always returned sorted by `created_at` in ascending order. The pagination fields surfaced in the `meta` object are `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the count of all records matching the query before pagination and `has_more` indicates whether records remain beyond the current page.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource carries a server-minted `id` that is a UUID with no type prefix. Most resources also carry three further common properties: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that begins at 1 when the resource is created and increments by one on every mutation. The entities `Facility`, `Unit`, `Tenant`, `Lease`, `Invoice`, `Payment`, `InsurancePolicy`, `AuctionProceeding`, and `TransferOrder` all carry the full set of common properties.

The `LedgerEntry` is the one exception. A ledger entry is immutable once written and therefore carries only `id` and `created_at` — it has no `updated_at` and no `version`. There is no endpoint that mutates a ledger entry after creation.

Whenever an operation changes a resource, that resource's `updated_at` is refreshed and its `version` is incremented. When a single operation cascades changes across several resources — for example a billing cycle that overdue-flags an invoice and pushes its lease into delinquency — each mutated resource independently has its `updated_at` refreshed and its `version` bumped.

### 2.5. Monetary Precision and Rounding

All money in the system is expressed in integer cents; there are no fractional-cent fields. Wherever a calculation produces a non-integer cent value before storage — proration, the climate premium, a transfer rate adjustment — the result is rounded to whole cents using the round-half-up convention (a value at exactly the half-cent rounds away from zero). The specific point in each formula at which rounding occurs is described with that formula in §3; the rule that matters globally is that the stored value is always a whole number of cents rounded half-up.

### 2.6. The Immutable Ledger and the Denormalized Balance

Every money movement on a lease is recorded as an immutable `LedgerEntry` whose `entry_type` is one of `CHARGE`, `LATE_FEE`, `PAYMENT`, `CREDIT`, `REVERSAL`, or `AUCTION_SETTLEMENT`. Each entry records a signed `amount_cents`: a `CHARGE` and a `LATE_FEE` are positive and increase the balance; a `PAYMENT`, a `CREDIT`, and an `AUCTION_SETTLEMENT` are negative and decrease the balance; a `REVERSAL` re-adds the amount of a previously recorded payment. Each entry also records a `source_type` — one of `INVOICE`, `PAYMENT`, `AUCTION`, or `MANUAL` — and a `source_id` pointing to the originating invoice, payment, or auction proceeding, plus the `lease_id` it belongs to.

A lease's outstanding `balance_cents` is maintained as a denormalized running total: it is adjusted incrementally on every ledger append rather than recomputed from scratch, and this denormalized value is the authoritative figure the API returns on the lease. Because a denormalized running total and a from-scratch recomputation are two independent reads of the same underlying data, they can drift if the running total is ever maintained incorrectly. For that reason a reconciliation read is offered that replays the ledger: it sums the signed `amount_cents` over every `LedgerEntry` for the lease, processed in `created_at` ascending order, and returns the resulting figure. When the system is internally consistent this replayed balance equals the denormalized `balance_cents`; exposing the replay makes any drift observable.

### 2.7. Optimistic Concurrency on Lease-Superseding Writes

Two operations create a child record whose validity depends on the lease's current shape, and both therefore require the caller to pin the lease version they last observed. Opening an auction proceeding requires a non-optional `expected_lease_version` field, and requesting a transfer order requires a non-optional `expected_lease_version` field.

When a request to open an auction proceeding arrives, `expected_lease_version` must equal the target lease's current `version`. If another writer has advanced the lease's version since the client last read it — for instance a payment that cured the delinquency and moved the lease back toward `ACTIVE` — then the client's belief that the lease is still eligible for foreclosure is stale, and the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Likewise, when a request to create a transfer order arrives, `expected_lease_version` must equal the target lease's current `version`; if a prior writer has already relocated the lease (changing its `unit_id` and rate), the source and destination units this request names are stale, and the request is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a version field. Successfully opening an auction proceeding increments the lease's `version` by one, and successfully requesting a transfer order increments the lease's `version` by one — so a second stale write that pinned the pre-write version will correctly fail.

### 2.8. Nested Reference Validation and the Order of Checks

Resources reference one another by foreign key across flat collections rather than through nested URL ownership chains. When a request names several resources, existence is validated left to right, and any referenced facility, unit, tenant, lease, invoice, policy, auction proceeding, or transfer order that does not exist yields `ERR_NOT_FOUND` (HTTP 404).

Validation across the system follows a fixed priority so that the same failure always surfaces the same error. Authentication is checked first: missing or unrecognized headers give `ERR_UNAUTHENTICATED`. Authorization is checked second: a role not permitted for the operation, or a tenant acting on a lease it does not own, gives `ERR_FORBIDDEN`. Existence of all referenced resources is checked third, giving `ERR_NOT_FOUND`. Request well-formedness is checked fourth: missing required fields, bad enum values, and out-of-range numbers — a `billing_day` outside 1 through 28, an `amount_cents` not greater than zero, a `climate_premium_pct` outside the range 0 through 1 inclusive — give `ERR_INVALID_REQUEST` (HTTP 422). For state-transition endpoints, the target resource being in a state from which the requested transition is not defined is checked fifth, giving `ERR_INVALID_STATE` (HTTP 409). Beyond these, the domain-specific business rules described in §3 apply; each names the precise error it raises. A request body that is not even parseable JSON is rejected with `ERR_VALIDATION` (HTTP 400).

### 2.9. The Logical Clock

The system's billing, late-fee, and statutory-window logic all measure elapsed time against a single server-maintained logical clock. An administrative test-driving capability lets a `FacilityManager` set the current UTC clock to a supplied instant via the `to_iso8601` field; setting the clock mutates no entity by itself. Time-dependent effects — generating due invoices, assessing late fees, advancing delinquency, opening the statutory windows — take effect only when the next billing-cycle run or window-gated operation is invoked at the new clock position.

## 3. Business Logic & Workflows

### 3.1. Facilities, Units, and the Occupancy Counter

A storage operation begins with a `FacilityManager` creating a `Facility`, supplying its `name` and its two-letter `state_code`, which governs the lien default window and notice rules for leases at that facility. Four pricing and dunning parameters may be supplied or left to default: `climate_premium_pct`, the surcharge fraction applied to base rent for climate-controlled units, which defaults to 0.20 and must be at least 0 and no more than 1; `lien_default_days`, the number of days a lease must be past due before it becomes auction-eligible, which defaults to 90 and must be at least 1; `late_fee_grace_days`, the number of days an invoice may be past due before a late fee is assessed, which defaults to 5 and must be at least 0; and `late_fee_cents`, the flat fee charged once per invoice when it crosses the grace boundary, which defaults to 2000 and must be at least 0. A facility also exposes `occupied_unit_count`, which is initialized to zero at creation.

The `occupied_unit_count` is a computed reflection of physical occupancy: it is always the number of units belonging to the facility whose `status` equals `OCCUPIED`, and it is recomputed from scratch on every unit status change — activation, transfer completion, auction sale, and lease close. When a unit becomes occupied the count rises; when a unit is released it falls; and a transfer that vacates one unit while occupying another within the same facility leaves the count unchanged.

Within a facility a `FacilityManager` creates `Unit` records, each supplying its `facility_id`, a `unit_number` that serves as a human label and must be unique within that facility, a `size_class` of `SIZE_5X5`, `SIZE_10X10`, or `SIZE_10X20`, and a `monthly_rate_cents` base street rate that must be greater than zero. A unit may optionally be flagged `climate_controlled`, which defaults to false. Attempting to create a second unit with a `unit_number` already used in the same facility is rejected with `ERR_DUPLICATE_UNIT_NUMBER` (HTTP 409). A newly created unit starts with `status` equal to `AVAILABLE` and `current_lease_id` of null. The `status` field tracks physical occupancy through the values `AVAILABLE`, `OCCUPIED`, and `VACATING`, and `current_lease_id` holds the id of the lease currently occupying the unit, or null when the unit is `AVAILABLE`.

### 3.2. Tenants and the Lease Binding

A `Tenant` is registered with an `email` that must be unique across all tenants, a `full_name`, a `state_code` giving the tenant's state of residence, and an optional `phone` that defaults to null. Registering with an email already on file is rejected with `ERR_DUPLICATE_EMAIL` (HTTP 409). A tenant may self-register, and a `FacilityManager` may register a tenant on their behalf.

A `FacilityManager` opens a `Lease` by binding a tenant to a unit, supplying the `unit_id`, the `tenant_id`, the `start_date` (the intended move-in instant in ISO 8601 UTC, which drives first-month proration), and the `billing_day` — the day of month, from 1 through 28, on which a monthly invoice is generated. The lease may optionally set `insurance_required`, which defaults to true; when true the lease must carry an active insurance policy before it can be activated. On creation the lease's `status` is `PENDING`, its `facility_id` is copied from the unit's facility, and its `balance_cents` is zero. Its `end_date` is null while occupying. A lease created against a unit whose closed occupancy interval `[start_date, end_date]` intersects the interval of an existing lease on that same unit is rejected with `ERR_UNIT_OCCUPANCY_OVERLAP` (HTTP 409); two leases may not occupy the same unit over intersecting closed date intervals.

The lease also carries fields that are not supplied at creation but populated later by the system: `monthly_rate_cents` and `climate_controlled` are snapshotted from the unit at activation; `days_past_due` is a computed measure of delinquency; and the lease's `status` walks the values `PENDING`, `ACTIVE`, `DELINQUENT`, `PRE_LIEN`, `LIEN`, `AUCTION_SCHEDULED`, `AUCTIONED`, `TRANSFERRED`, and `CLOSED` across its life.

### 3.3. Activation, the Snapshot, and the First Prorated Invoice

Activating a lease is the pivotal event that turns a reservation into a live, billing tenancy, and a `FacilityManager` performs it. Activation is only defined from the `PENDING` state; attempting it from any other state gives `ERR_INVALID_STATE`. Three preconditions must hold. The lease must be `PENDING`. The bound unit's `status` must be `AVAILABLE` — if it is not, activation is rejected with `ERR_UNIT_NOT_AVAILABLE` (HTTP 409). And when the lease's `insurance_required` is true, an `InsurancePolicy` with `status` equal to `ACTIVE` must already exist for this lease; if none does, activation is rejected with `ERR_INSURANCE_REQUIRED` (HTTP 409).

On a successful activation the lease moves `PENDING → ACTIVE`. The bound unit moves `AVAILABLE → OCCUPIED`, its `current_lease_id` is set to this lease, and the facility's `occupied_unit_count` is recomputed. The lease snapshots the unit's pricing: `monthly_rate_cents` is copied from the unit's `monthly_rate_cents` and `climate_controlled` is copied from the unit's climate flag, so that later edits to the unit's street rate do not retroactively change this lease. A first invoice is generated covering occupancy from the `start_date` to the next billing day, with its base rent prorated to the move-in day. A `CHARGE` ledger entry is appended for that first invoice's total, and the lease's `balance_cents` is set to that first invoice total.

The monthly charge for a full period is assembled from three components, each rounded independently to whole cents before they are summed. The base component is the lease's snapshot `monthly_rate_cents`. The climate component is zero when the lease is not climate-controlled; when it is climate-controlled, it is the snapshot `monthly_rate_cents` multiplied by the facility's `climate_premium_pct`, rounded half-up to whole cents. The insurance component is the `monthly_premium_cents` of the lease's active insurance policy when one exists, and zero otherwise. The full monthly total is the sum of these three already-rounded components — the components are each rounded first, then added, never summed as fractions and rounded once.

The first invoice prorates that full monthly total to the portion of the month the tenant occupies. Let the number of days in the calendar month of `start_date` be the month's day count, and let the days occupied be that day count minus the day-of-month of `start_date` plus one, so the move-in day itself counts as occupied. The prorated base is the full monthly total multiplied by the days occupied, divided by the days in the month, with a single round-half-up applied to whole cents after that day-fraction multiply.

### 3.4. Invoice Structure, Billing Cycles, and Late Fees

Every `Invoice` records the `lease_id` it bills, a `period_start` and a `period_end` describing the half-open billing window `[period_start, period_end)`, and a `due_date` against which delinquency is measured. Its monetary breakdown is carried in `base_amount_cents` (the base rent for the period, prorated for the first period), `climate_amount_cents` (the climate premium component, zero when the lease is not climate-controlled), `insurance_amount_cents` (the insurance premium component snapshotted from the active policy, zero when none), and `late_fee_cents` (the flat late fee, which defaults to 0 and is added once if the invoice ages past grace). The `total_amount_cents` is the sum of the base, climate, insurance, and late-fee components for that invoice. The `amount_paid_cents`, defaulting to 0, accumulates payments applied via waterfall allocation. An invoice's `status` is one of `OPEN`, `PARTIAL`, `OVERDUE`, `PAID`, or `WAIVED`.

A `FacilityManager` advances the business by running a billing cycle for a facility at the current clock. A billing run performs several effects in sequence. For each `ACTIVE` or `DELINQUENT` lease whose `billing_day` is due, it generates a monthly invoice using the three-component monthly charge and appends a `CHARGE` ledger entry, raising the lease's `balance_cents` accordingly. It then assesses late fees: for each invoice still in `OPEN` or `PARTIAL` status, it measures `days_past_due` as the whole number of days from the invoice's `due_date` to the current clock (the floor of the elapsed days), and when that count is at least the facility's `late_fee_grace_days` and the invoice has not yet been charged a late fee, it sets that invoice's `late_fee_cents` to the facility's `late_fee_cents`, recomputes the invoice total, moves the invoice `OPEN → OVERDUE` or `PARTIAL → OVERDUE`, and appends a `LATE_FEE` ledger entry, raising the lease's balance by the fee. The grace boundary is inclusive: a late fee attaches when days past due is at least the grace days, not strictly greater. The flat fee is added at most once per invoice.

The billing run also advances lease delinquency and lapses unpaid insurance, as described in §3.5, and recomputes `days_past_due` on every affected lease. The lease-level `days_past_due` is the whole number of days between the current clock and the `due_date` of the oldest invoice still in `OPEN`, `PARTIAL`, or `OVERDUE` status, and is zero when nothing is past due.

A `FacilityManager` may also waive an invoice that is `OPEN`, `PARTIAL`, or `OVERDUE`. Waiving moves the invoice to `WAIVED`, appends a `CREDIT` ledger entry for the invoice's unpaid remainder, and decreases the lease's `balance_cents` by that same unpaid remainder. Waiving from any other invoice state gives `ERR_INVALID_STATE`.

### 3.5. The Delinquency Cycle and Insurance Lapse

A lease's slide into default unfolds across billing cycles. When a billing run flags an invoice on an `ACTIVE` lease as overdue — that is, when an invoice on the lease has reached at least `late_fee_grace_days` past due — the lease moves `ACTIVE → DELINQUENT`. As delinquency deepens, when a `DELINQUENT` lease's `days_past_due` reaches at least 30 and is still below the facility's `lien_default_days`, the lease moves `DELINQUENT → PRE_LIEN`. The `PRE_LIEN` status marks a lease that is seriously past due but not yet eligible for foreclosure.

Insurance follows delinquency. When the invoice that carries an active policy's premium becomes `OVERDUE`, that `InsurancePolicy` moves `ACTIVE → LAPSED` on the billing run, and its coverage limit is no longer payable while lapsed.

The cure path runs the other direction. When a tenant pays enough to bring the lease's `balance_cents` to zero, a delinquent or pre-lien lease cures: a lease in `DELINQUENT` or `PRE_LIEN` status moves back to `ACTIVE`, all its overdue invoices that the payment fully covers settle to `PAID`, and the lease's `days_past_due` resets to zero. The cure also cascades outward — any open auction proceeding on the lease in `NOTICE_SENT` or `LIEN_FILED` status moves to `CANCELLED`, and a `LAPSED` insurance policy returns to `ACTIVE` once the arrears are cured and the balance reaches zero. These cure effects are described in full alongside the payment workflow in §3.6.

### 3.6. Payments, Waterfall Allocation, and Reversal

A payment is recorded by a `Tenant` against their own lease or by a `FacilityManager`, supplying the `lease_id` and an `amount_cents` that must be greater than zero; a non-positive amount is rejected with `ERR_BALANCE_NOT_CLEARED` (HTTP 409). On creation a `Payment` has `status` `APPLIED`, an `allocation` array describing how it was distributed, and an `overpay_credit_cents` figure that defaults to 0.

Allocation is oldest-debt-first. The lease's invoices in `OPEN`, `PARTIAL`, or `OVERDUE` status are ordered by `due_date` ascending, with ties broken by `created_at` ascending — never by id. The payment amount is consumed across that ordered list: each invoice receives the smaller of the remaining payment and that invoice's own unpaid remainder (its `total_amount_cents` minus its `amount_paid_cents`); the applied amount is added to the invoice's `amount_paid_cents` and subtracted from the remaining payment; and the invoice moves to `PAID` if it is now fully covered or to `PARTIAL` if only partly covered. The `allocation` array records, in this order, one `{invoice_id, applied_cents}` entry per invoice touched. A `PAYMENT` ledger entry is appended for the covered amount and the lease's `balance_cents` decreases accordingly. If any payment remains after every open invoice is covered, that remainder becomes `overpay_credit_cents` and is recorded as a `CREDIT` ledger entry, held as an account credit.

A successful payment that drives the lease's balance to zero triggers the full cure cascade: a `DELINQUENT` or `PRE_LIEN` lease returns to `ACTIVE` with `days_past_due` reset to zero, any open auction proceeding in `NOTICE_SENT` or `LIEN_FILED` is `CANCELLED`, and a `LAPSED` insurance policy returns to `ACTIVE`.

A `FacilityManager` may reverse an `APPLIED` payment as a compensating action. Reversal moves the payment `APPLIED → REVERSED`, appends a `REVERSAL` ledger entry that re-adds the payment amount, raises the lease's `balance_cents` back to its pre-payment value, and reverts the invoices the payment had covered from `PAID` or `PARTIAL` back to `OPEN` or `PARTIAL` as appropriate. Reversing a payment not in `APPLIED` status gives `ERR_INVALID_STATE`.

### 3.7. Insurance Policies

A tenant on their own lease, or a `FacilityManager`, binds an `InsurancePolicy` by supplying the `lease_id`, a `coverage_tier`, and a `coverage_start`. The tier is one of `BASIC`, `STANDARD`, or `PREMIUM`, and it deterministically fixes two derived figures. The `monthly_premium_cents` is 1000 for `BASIC`, 1500 for `STANDARD`, and 2500 for `PREMIUM`. The `coverage_limit_cents` is 200000 for `BASIC`, 500000 for `STANDARD`, and 1500000 for `PREMIUM`. A new policy is created with `status` `ACTIVE`, a null `coverage_end` while active, and the supplied `coverage_start` marking the inclusive start of coverage; `coverage_end`, when set, marks the exclusive end of the half-open coverage interval `[coverage_start, coverage_end)`. While a policy is `ACTIVE`, its `monthly_premium_cents` is folded into each generated invoice. A policy whose half-open coverage interval intersects an existing policy interval on the same lease is rejected with `ERR_COVERAGE_OVERLAP` (HTTP 409); adjacency, where one interval's end equals the next interval's start, is permitted because the intervals do not overlap.

A policy's `status` is one of `ACTIVE`, `LAPSED`, or `CANCELLED`. It lapses when its premium invoice goes overdue and returns to active when the arrears are cured, as described in §3.5. It can be cancelled by a tenant or facility manager, which moves it from `ACTIVE` or `LAPSED` to `CANCELLED` and sets its `coverage_end` to the current clock. The system also cancels any active policy automatically when the lease is auctioned or closed, again setting `coverage_end` to the clock.

### 3.8. The Lien and Auction Legal Process

When a lease's delinquency reaches the statutory threshold, a `LienAdministrator` may begin foreclosure by opening an `AuctionProceeding` against it, supplying the `lease_id` and `expected_lease_version`. Opening is permitted only when the lease is in `PRE_LIEN` status and its `days_past_due` is at least the facility's `lien_default_days` — the at-least-90-day default boundary; a lease that has not yet reached that day count is rejected with `ERR_WINDOW_NOT_ELAPSED` (HTTP 409). If a non-terminal auction proceeding already exists for the lease, the open is rejected with `ERR_PROCEEDING_EXISTS` (HTTP 409). The `expected_lease_version` must match the lease's current `version` or the open is rejected with `ERR_STALE_VERSION`, as covered in §2.7. On a successful open the proceeding is created with `status` `NOTICE_SENT`, its `notice_sent_date` set to the current clock, the lease moves `PRE_LIEN → LIEN`, and the lease's `version` increments by one. At this moment the proceeding's `redemption_amount_cents` is seeded from the lease's current unpaid invoice remainders plus the fixed lien administration cost.

A proceeding's `status` walks `NOTICE_SENT`, `LIEN_FILED`, `SCHEDULED`, and then forks to one of three terminal outcomes — `SOLD`, `REDEEMED`, or `CANCELLED`. Each step has its own statutory waiting period, and the proceeding also records `lien_filed_date`, `scheduled_sale_date`, `sale_proceeds_cents`, and `surplus_cents`.

The administrator files the lien once the statutory notice period has elapsed. Filing is defined only from `NOTICE_SENT`, and is permitted only when the current clock is at least 14 days after the `notice_sent_date`; an earlier attempt gives `ERR_WINDOW_NOT_ELAPSED`. Filing moves the proceeding `NOTICE_SENT → LIEN_FILED`, sets `lien_filed_date` to the current clock, and freezes the lien-date redemption snapshot described below.

The administrator then schedules the public sale, supplying a `scheduled_sale_date`. Scheduling is defined only from `LIEN_FILED`, and the supplied `scheduled_sale_date` must be at least 14 days after the `lien_filed_date` — a cooling-off window; an earlier date gives `ERR_WINDOW_NOT_ELAPSED`. Scheduling records the `scheduled_sale_date`, moves the proceeding `LIEN_FILED → SCHEDULED`, and moves the lease `LIEN → AUCTION_SCHEDULED`.

The administrator completes the sale by recording the winning bid as `sale_proceeds_cents`, which must be greater than zero; a bid not greater than zero gives `ERR_BALANCE_NOT_CLEARED`. Completing the sale is defined only from `SCHEDULED`. On completion the proceeding moves `SCHEDULED → SOLD` and the surplus-distribution waterfall runs against the proceeds. The lease's `balance_cents` is set to zero and an `AUCTION_SETTLEMENT` ledger entry is appended. The lease moves `AUCTION_SCHEDULED → AUCTIONED` and its `end_date` is set to the current clock. The vacated unit moves to `AVAILABLE`, its `current_lease_id` is cleared to null, and the facility's `occupied_unit_count` is recomputed. Any active insurance policy on the lease is cancelled with its `coverage_end` set to the current clock.

The administrator may instead administratively cancel a proceeding that has not yet sold. Cancellation moves a proceeding in `NOTICE_SENT` or `LIEN_FILED` status to `CANCELLED`, closing it without a sale and returning the lease to `ACTIVE` once the balance is cleared.

### 3.9. Redemption Math and the Surplus Waterfall

The amount a tenant must pay to redeem is computed in two distinct ways for two distinct purposes, and the two can legitimately diverge. Both start from the same two ingredients: the outstanding sum, which is the total of `total_amount_cents` minus `amount_paid_cents` across the lease's invoices in `OPEN`, `PARTIAL`, or `OVERDUE` status, and the fixed lien administration cost of 15000 cents.

The first variant is the **lien-date snapshot**: at the moment the lien is filed, the redemption amount is frozen as the outstanding sum measured as of the `lien_filed_date` plus the lien administration cost, and late fees that accrue after the lien-filed date are excluded from it. This snapshot is computed and stored when the lien is filed. The second variant is the **accruing-today** amount: the live figure returned when the proceeding is read, computed as the outstanding sum measured as of the current clock — including any late fees assessed after the lien was filed — plus the lien administration cost. Once any post-lien late fee has been assessed, the accruing-today amount is at least the lien-date snapshot and may exceed it. A read of an auction proceeding returns the accruing-today value in `redemption_amount_cents`.

A `Tenant` redeems their own lease by clearing the balance. Redemption requires that a payment covering the redemption amount has been applied so that the lease's `balance_cents` equals zero; a redemption attempted while the balance is non-zero is rejected with `ERR_BALANCE_NOT_CLEARED`. Redemption is defined while the proceeding is in `NOTICE_SENT`, `LIEN_FILED`, or `SCHEDULED` status and the lease is in `LIEN` or `AUCTION_SCHEDULED`; it moves the proceeding to `REDEEMED`, returns the lease to `ACTIVE`, and resets `days_past_due` to zero, with no unit or insurance change.

When a sale completes, the gross `sale_proceeds_cents` are distributed through an ordered waterfall whose buckets are filled in strict priority. The first bucket takes the smaller of the remaining proceeds and the outstanding rent, climate, and insurance remainders. The second bucket then takes the smaller of what now remains and the outstanding late fees. The third bucket then takes the smaller of what now remains and the lien administration cost of 15000 cents. Whatever proceeds remain after those three buckets are the tenant's `surplus_cents`. All amounts are whole cents with no rounding remainder, and the four quantities — the three bucket payments and the surplus — always sum exactly to `sale_proceeds_cents`.

### 3.10. Transfers and Relocation

A `FacilityManager` relocates a tenant by first requesting a `TransferOrder`, supplying the `lease_id`, the `to_unit_id` destination, and `expected_lease_version`. The destination unit must be `AVAILABLE`; if it is not, the request is rejected with `ERR_UNIT_NOT_AVAILABLE`. The lease whose contents move must be `ACTIVE`. The `expected_lease_version` must match the lease's current `version`, or the request is rejected with `ERR_STALE_VERSION` as covered in §2.7. A lease with a non-terminal auction proceeding cannot be transferred, which is rejected with `ERR_LEASE_HAS_ACTIVITY` (HTTP 409). On a successful request the order is created with `status` `REQUESTED`, its `from_unit_id` is captured as the lease's current `unit_id`, and the lease's `version` increments by one. The order also carries a `prorated_adjustment_cents` figure computed at completion. The destination unit is held against the requested move.

A `FacilityManager` then completes the transfer. Completion is defined only from `REQUESTED`; the order must still be `REQUESTED`, the lease must still be `ACTIVE`, and the destination unit must still be `AVAILABLE`, else the relevant state or availability error is raised. On completion the order moves `REQUESTED → COMPLETED`. The old unit is released to `AVAILABLE` with its `current_lease_id` cleared, and the new unit becomes `OCCUPIED` with its `current_lease_id` set to the lease. The lease's `unit_id` is updated to the destination, and its snapshot `monthly_rate_cents` and `climate_controlled` are updated to the new unit's rate and climate flag. Because one unit is vacated as another is occupied within the facility, the facility's `occupied_unit_count` is unchanged across the move. The lease itself remains `ACTIVE` bound to the new unit.

The move applies a prorated rent adjustment for the remainder of the current billing period. The `prorated_adjustment_cents` is the difference between the new unit's full monthly total and the old unit's full monthly total, multiplied by the days remaining — the days from the current clock (exclusive) to the current period's `period_end` (exclusive) — divided by the number of days in the current billing period, with a single round-half-up applied to whole cents. When the new rate exceeds the old, the signed adjustment is positive and a `CHARGE` ledger entry is appended; when the new rate is lower, the adjustment is negative and a `CREDIT` ledger entry is appended; the lease's `balance_cents` is adjusted by the signed amount in either direction.

A requested transfer may instead be cancelled by a `FacilityManager`, which moves the order `REQUESTED → CANCELLED`, releases the destination unit from its hold, and changes no rate. Cancellation is defined only from `REQUESTED`.

### 3.11. Closing a Lease

A `FacilityManager` closes a lease at move-out. Closing is defined from `ACTIVE` or `DELINQUENT` status only, and requires that the lease's `balance_cents` is already zero; a non-zero balance is rejected with `ERR_BALANCE_NOT_CLEARED`. A lease that carries a non-terminal auction proceeding cannot be closed and is rejected with `ERR_LEASE_HAS_ACTIVITY`. On close the lease moves to `CLOSED` and its `end_date` is set to the current clock; the occupied unit is released to `AVAILABLE` with its `current_lease_id` cleared, and the facility's `occupied_unit_count` is recomputed. Any active insurance policy on the lease is cancelled with its `coverage_end` set to the current clock. The statuses `AUCTIONED`, `TRANSFERRED`, and `CLOSED` are the terminal states of a lease.

## 4. Endpoint Definitions

Creation endpoints that mint a new resource return HTTP 201; all other successful reads, mutations, and state transitions return HTTP 200. The table below lists each endpoint's method, path, purpose, and the roles permitted to call it. Request bodies, response payloads, and side effects are not repeated here — they are described in the §3 workflow narratives.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/facilities` | Create a storage facility | FacilityManager |
| GET | `/facilities/{facility_id}` | Get a facility (includes occupied unit count) | FacilityManager, LienAdministrator, Tenant |
| POST | `/facilities/{facility_id}/billing-cycles` | Run automatic billing at the current clock | FacilityManager |
| POST | `/units` | Create a physical unit in a facility | FacilityManager |
| GET | `/units/{unit_id}` | Get a unit | FacilityManager, LienAdministrator, Tenant |
| GET | `/units` | List units; filter by facility, status, current lease | FacilityManager, LienAdministrator, Tenant |
| POST | `/tenants` | Register a tenant | FacilityManager, Tenant |
| GET | `/tenants/{tenant_id}` | Get a tenant | FacilityManager, Tenant |
| POST | `/leases` | Create a PENDING lease binding a tenant to a unit | FacilityManager |
| GET | `/leases/{lease_id}` | Get a lease | FacilityManager, LienAdministrator, Tenant |
| GET | `/leases` | List leases; filter by facility, unit, tenant, status | FacilityManager, LienAdministrator, Tenant |
| GET | `/leases/{lease_id}/ledger-balance` | Recompute the lease balance by replaying the ledger | FacilityManager, LienAdministrator, Tenant |
| POST | `/leases/{lease_id}/activate` | Activate a PENDING lease | FacilityManager |
| POST | `/leases/{lease_id}/close` | Close a lease with zero balance | FacilityManager |
| GET | `/invoices/{invoice_id}` | Get an invoice | FacilityManager, LienAdministrator, Tenant |
| GET | `/invoices` | List invoices; filter by lease, status | FacilityManager, LienAdministrator, Tenant |
| POST | `/invoices/{invoice_id}/waive` | Waive the unpaid remainder of an invoice | FacilityManager |
| POST | `/payments` | Record a tenant payment | Tenant, FacilityManager |
| GET | `/payments/{payment_id}` | Get a payment (includes allocation) | FacilityManager, Tenant |
| GET | `/payments` | List payments; filter by lease | FacilityManager, Tenant |
| POST | `/payments/{payment_id}/reverse` | Reverse an applied payment | FacilityManager |
| GET | `/ledger-entries/{ledger_entry_id}` | Get a single immutable ledger entry | FacilityManager, LienAdministrator, Tenant |
| GET | `/ledger-entries` | List immutable ledger entries; filter by lease | FacilityManager, LienAdministrator, Tenant |
| POST | `/insurance-policies` | Bind an insurance policy to a lease | FacilityManager, Tenant |
| GET | `/insurance-policies/{policy_id}` | Get an insurance policy | FacilityManager, LienAdministrator, Tenant |
| GET | `/insurance-policies` | List insurance policies; filter by lease, status | FacilityManager, LienAdministrator, Tenant |
| DELETE | `/insurance-policies/{policy_id}` | Cancel an insurance policy | FacilityManager, Tenant |
| POST | `/auction-proceedings` | Open a lien/auction proceeding | LienAdministrator |
| GET | `/auction-proceedings/{auction_id}` | Get an auction proceeding (accruing redemption) | FacilityManager, LienAdministrator, Tenant |
| GET | `/auction-proceedings` | List auction proceedings; filter by lease | FacilityManager, LienAdministrator, Tenant |
| POST | `/auction-proceedings/{auction_id}/file-lien` | File the lien after the notice period | LienAdministrator |
| POST | `/auction-proceedings/{auction_id}/schedule` | Schedule the public sale | LienAdministrator |
| POST | `/auction-proceedings/{auction_id}/complete-sale` | Record the winning bid and distribute | LienAdministrator |
| POST | `/auction-proceedings/{auction_id}/redeem` | Tenant redeems by clearing the balance | Tenant |
| POST | `/auction-proceedings/{auction_id}/cancel` | Administratively cancel a proceeding | LienAdministrator |
| POST | `/transfer-orders` | Request a relocation of an active lease | FacilityManager |
| GET | `/transfer-orders/{transfer_order_id}` | Get a transfer order | FacilityManager, Tenant |
| GET | `/transfer-orders` | List transfer orders; filter by lease, units | FacilityManager, Tenant |
| POST | `/transfer-orders/{transfer_order_id}/complete` | Complete the relocation | FacilityManager |
| POST | `/transfer-orders/{transfer_order_id}/cancel` | Cancel a requested transfer | FacilityManager |
| POST | `/_clock/set_current_utc` | Set the server's current UTC clock (test-driving) | FacilityManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_UNIT_NOT_AVAILABLE | 409 |
| ERR_INSURANCE_REQUIRED | 409 |
| ERR_WINDOW_NOT_ELAPSED | 409 |
| ERR_UNIT_OCCUPANCY_OVERLAP | 409 |
| ERR_COVERAGE_OVERLAP | 409 |
| ERR_BALANCE_NOT_CLEARED | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_DUPLICATE_UNIT_NUMBER | 409 |
| ERR_DUPLICATE_EMAIL | 409 |
| ERR_PROCEEDING_EXISTS | 409 |
| ERR_LEASE_HAS_ACTIVITY | 409 |
| ERR_VALIDATION | 400 |
</content>
</invoke>
