# Residential Property Management API — Product Requirements Document

## 1. Introduction

Operating a residential rental portfolio means holding several streams of money and obligation in balance at once: prospective tenants must be screened against credit and affordability thresholds, leases must be signed, renewed, and eventually wound down, rent must be billed and collected with predictable late-fee mechanics, and every dollar that flows through a property has to be reconciled back to the owner who actually owns the building. This API is the system of record for that entire lifecycle. It governs applicant screening, lease origination and renewal, the rent roll and its late-fee sweep, state-mandated security-deposit accounting, maintenance work orders, owner statements and trust distributions, the eviction process, and the vacancy-turnover work that readies a unit for the next tenant.

Two financial disciplines run through everything the system does. The first is a per-property **trust ledger**: collected rent flows in, maintenance and refunds and distributions flow out, and the ledger may never go negative. The second is a body of jurisdiction-specific rules — deposit interest and eviction cure periods both depend on the US state the property sits in — that must be applied mechanically and identically every time. The design goal is that an operator never has to remember a state's interest rate or cure window, never has to manually compute a payment waterfall, and never has to wonder whether a distribution would overdraw an owner's trust account. The system computes all of it, records the derivation, and refuses any action that would violate solvency, sequencing, or the lease's own state machine.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, conventions, and contracts that apply across every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID`, an identifier for the acting user, and `X-User-Role`, the role under which they are acting. A request that omits `X-User-Role` or supplies a value that is not one of the five recognized roles is rejected with `ERR_UNAUTHENTICATED`. When the header is present and valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly five roles: `PropertyManager`, `Owner`, `Tenant`, `Applicant`, and `ComplianceOfficer`.

The `PropertyManager` is the day-to-day operator. When `X-User-Role` is `PropertyManager`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may accept and record it but does not compare it to any entity's `id`. The same is true for the `ComplianceOfficer`: when `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is likewise an opaque legal-operator identifier not backed by any stored entity, and the server never matches it against an entity `id`. These two roles are operator roles distinguished only by which operations they may invoke.

The remaining three roles are entity-backed, meaning the caller's `X-User-ID` is the `id` of a specific stored record and ownership checks compare a resource's foreign key to that value. When `X-User-Role` is `Owner`, `X-User-ID` is the `id` of the acting `Owner`; visibility into any property and its descendant resources is granted by comparing the property's `owner_id` (directly, or transitively through the unit and lease that a resource hangs from) to `X-User-ID`. When `X-User-Role` is `Tenant`, `X-User-ID` is the `id` of the acting `Tenant`, and read access to a lease, its charges, payments, deposit, and unit is granted on the basis of that tenant's relationship to those resources. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Applicant`, and an applicant may act on or read only the application record whose `id` equals `X-User-ID`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless an endpoint states otherwise, list results are sorted by the resource's creation timestamp, `created_at`, in ascending order.

Every list response reports `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Identity

Every top-level resource in this system carries a server-managed `id` formatted as a UUID, with no type prefix, minted by the server at creation. Each resource also carries a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, recorded once when the resource is first created.

Because every resource in this domain is mutable and subject to consistency reconciliation, all of them additionally carry an `updated_at` timestamp and an integer `version`. The `updated_at` field follows the same ISO 8601 UTC format and is refreshed on any mutation. The `version` begins at 1 on creation and increments by one with every subsequent mutation of the resource, including mutations driven indirectly by cascades and by recomputation of derived fields. There are no creation-only, immutable resources in this domain; every entity exposes all four common fields.

### 2.5. Flat Topology and Reverse Reachability

All resources are addressed through top-level collections; the API has no nested-ownership URLs. A unit is not reached "through" its property in the path, and a lease is not reached "through" its unit — each lives at its own collection and references its parents by foreign keys carried in the request body (`owner_id`, `property_id`, `unit_id`, `applicant_id`, `lease_id`, `renewed_from_lease_id`). To navigate from a parent to its children, callers use filtered list endpoints: properties can be listed by `owner_id`, units by `property_id`, applicants by `unit_id`, leases by `unit_id`, `applicant_id`, or `renewed_from_lease_id`, rent charges and payments and deposits and evictions by `lease_id`, work orders and turnovers by `unit_id`, statements by `property_id`, and tenants by `applicant_id`. Several list endpoints also accept a `status` filter, and rent charges additionally accept a `charge_type` filter.

When a request addresses a resource by an `id` in its path and no such resource exists, the request is rejected with `ERR_NOT_FOUND`. When a creation request carries a foreign key in its body that does not resolve to an existing record — any of `owner_id`, `property_id`, `unit_id`, `applicant_id`, `lease_id`, or `renewed_from_lease_id` — the request is rejected with `ERR_FK_NOT_FOUND`.

### 2.6. Validation Ordering

When several conditions could reject a request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication is checked first: a missing or unknown role yields `ERR_UNAUTHENTICATED`. Authorization is checked second: a known role that lacks permission for the operation yields `ERR_FORBIDDEN`. Existence of the path resource is checked third, yielding `ERR_NOT_FOUND`. Body foreign-key resolution is checked fourth, yielding `ERR_FK_NOT_FOUND`. Request-shape validation — required fields present, types and enum members valid, and numeric ranges respected (for example a `credit_score` between 300 and 850 inclusive, monetary amounts strictly greater than zero where required, and an `end_date` strictly after `start_date`) — is checked fifth, yielding `ERR_INVALID_REQUEST`. Only after all of these pass does the system evaluate concurrency and business state.

For state-bearing writes the remaining checks run in this order: the optimistic-concurrency version check (`ERR_STALE_VERSION`) precedes the general state-admissibility check (`ERR_INVALID_STATE`), which precedes the domain-specific business guards. Among those domain guards the ordering is: the screening gate (`ERR_SCREENING_FAILED`), then the cure-window temporal check (`ERR_CURE_WINDOW_CLOSED` / `ERR_CURE_WINDOW_OPEN`), then the eviction-notice window-overlap check (`ERR_EVICTION_WINDOW_OVERLAP`), then the lease-not-ended check (`ERR_LEASE_NOT_ENDED`), then the lease-term-overlap check (`ERR_LEASE_OVERLAP`), then unit availability (`ERR_UNIT_NOT_AVAILABLE`), then the waiver-target check (`ERR_CANNOT_WAIVE_RENT`), then the open-work-order check (`ERR_OPEN_WORK_ORDERS`), and finally trust solvency (`ERR_TRUST_INSUFFICIENT`). The practical consequence is that a stale version is always reported before a state error, and a structural problem with the request is always reported before any business rule is consulted.

### 2.7. Monetary Values, Ratios, and Rounding

Every monetary amount in this system is an integer count of cents; there are no fractional-cent values and no floating-point currency. Field names that end in `_cents` are always whole-cent integers. Allocations and waterfalls — the payment waterfall and the deposit-deduction waterfall — are exact integer arithmetic with no rounding at all.

Where a calculation multiplies cents by a rate, the result is rounded to a whole number of cents using the round-half-up convention (a value exactly halfway between two integers rounds up to the larger magnitude). This applies to the late-fee percentage component, to deposit interest, and to the owner management fee. Two computed ratios on an application — `rent_to_income_ratio` and `dti_ratio` — are instead carried as decimal numbers rounded half-up to four decimal places.

### 2.8. The Property Trust Ledger

Each `Property` maintains a trust ledger expressed by three integer-cent fields. `trust_balance_cents` is the live balance: it starts at 0 and is credited by collected rent and by manual operator fundings, and debited by owner-charged maintenance, deposit refunds, make-ready costs, and owner distributions. The trust balance may never be driven below zero — any debit that would do so is refused with `ERR_TRUST_INSUFFICIENT` and the underlying operation does not proceed. `reserve_floor_cents` is an owner-specified minimum the trust must retain; it defaults to 0 and may not be negative. `distributable_cents` is derived and is recomputed on every trust mutation as the trust balance minus the reserve floor, floored at zero — that is, it equals the trust balance less the reserve floor when that difference is positive, and zero otherwise. Because `trust_balance_cents`, `distributable_cents`, and `unit_count` on a property are server-computed, a freshly created property reports a trust balance of 0, a distributable amount of 0, a unit count of 0, and a `version` of 1.

### 2.9. Optimistic Concurrency on Guarded Writes

Two specific writes are guarded by optimistic concurrency control against a parent resource's `version`, and both reject a stale write with `ERR_STALE_VERSION` (HTTP 412).

The first guards renewal-lease creation against the prior lease's version. Creating a renewal lease — a lease whose `renewed_from_lease_id` points at a prior lease — requires the request to carry `expected_lease_version` holding the version of that prior lease the client last observed. If another writer has advanced the prior lease's `version` since the client read it, the client's view of which lease is current is out of date, and the create is rejected with `ERR_STALE_VERSION`. On a successful renewal create, the prior lease's `version` is itself incremented by one, so that any second renewal create still carrying the now-superseded version is rejected.

The second guards owner distribution against the property's version. Distributing a finalized owner statement requires the request to carry `expected_property_version` holding the property's last-observed `version`. If another distribution or trust debit has advanced the property's `version` since the client read it, the distributable amount the client believes it can pay out is stale, and the distribution is rejected with `ERR_STALE_VERSION`. A successful distribution increments the property's `version`.

Endpoints other than renewal-lease creation, the renewal offer/retract toggle, and statement distribution do not take a version field and perform no concurrency check.

## 3. Business Logic & Workflows

### 3.1. Owners, Properties, Units, and the Trust Account

The portfolio is rooted in the `Owner`. A `PropertyManager` registers an owner by supplying the owner's `legal_name`, contact `email`, and `management_fee_pct`, which is the decimal fraction of gross rent the management company charges on owner statements — for example 0.08 expresses an eight-percent fee — and must lie between 0 and 0.5 inclusive. The owner also declares a `distribution_method` of either `ACH` or `CHECK`, governing how distributions are paid out; this defaults to `ACH` when not supplied.

Under an owner sits one or more properties. A property is created against an `owner_id` and carries a display `name`, a street `address`, and a `state_code` — one of `CA`, `NY`, `TX`, `IL`, or `FL` — which is the jurisdiction that governs the property's deposit-interest and eviction-cure rules. At creation the operator may set `reserve_floor_cents`, the minimum trust balance the owner wants retained; it defaults to 0. The trust ledger fields `trust_balance_cents`, `distributable_cents`, and the `unit_count` are all maintained by the system as described in the trust-ledger principle. An operator may inject money into a property's trust directly — recording, for instance, an owner capital contribution — by supplying an `amount_cents` funding, which credits the trust balance and triggers recomputation of the distributable figure.

Each property contains units. A unit is created under a `property_id` with a `label` such as "Apt 2B" and a `market_rent_cents` listing the advertised monthly rent, which must be strictly greater than zero. Creating a unit increments its property's `unit_count`. A unit's `occupancy_status` is system-managed and begins life as `VACANT_READY`; over the unit's life it moves between `VACANT_READY`, `OCCUPIED`, and `VACANT_TURN` as leases activate and end. A unit also exposes `active_lease_id`, a computed forward pointer to the `id` of the lease currently occupying it, or null when none does; it is a denormalized convenience, not an ownership key.

### 3.2. Applicant Screening

A prospective tenant — or a `PropertyManager` acting on their behalf — submits an application by providing `full_name`, `email` (which doubles as the screening identity), the `unit_id` applied for, self-reported `annual_income_cents`, a submitted `credit_score`, and the proposed `requested_rent_cents`. An optional `monthly_debt_cents` captures existing monthly debt obligations and defaults to 0. The credit score must be in the inclusive range 300 to 850, income and debt must be non-negative, and requested rent must be positive. A new application opens in `SUBMITTED` status, with `screening_decision`, `rent_to_income_ratio`, and `dti_ratio` all unset.

Screening is run by a `PropertyManager` on an application that is still in `SUBMITTED`, advancing it to `SCREENED`. Screening computes two ratios and a pass/fail verdict. The rent-to-income ratio is the requested monthly rent multiplied by twelve, divided by annual income, rounded half-up to four decimal places. The debt-to-income ratio is the sum of monthly debt and requested rent, multiplied by twelve, divided by annual income, again rounded half-up to four decimal places. The application passes screening only when all three of the following hold together: the credit score is at least 620, the rent-to-income ratio is at most 0.40, and the debt-to-income ratio is at most 0.45. Because the credit threshold is an at-least test and the two ratio thresholds are at-most tests, an application landing exactly on a boundary — a score of exactly 620, a rent-to-income of exactly 0.40, a debt-to-income of exactly 0.45 — passes that particular check. When all three hold, `screening_decision` is set to `PASS`; otherwise it is set to `FAIL`. There is one special case: if annual income is zero, the division is undefined, so both ratios are set to the sentinel value 999.9999 and the decision is `FAIL` regardless of the credit score.

Once screened, the application can be decided by a `PropertyManager`, who submits a `decision` of either `APPROVE` or `DENY`. The application must be in `SCREENED` for a decision to be accepted. Approval moves the application to `APPROVED`, but only if two conditions hold: the screening decision must be `PASS` — attempting to approve an application whose `screening_decision` is `FAIL` is refused with `ERR_SCREENING_FAILED` — and the unit named by the application's `unit_id` must currently be `VACANT_READY`, failing which the approval is refused with `ERR_UNIT_NOT_AVAILABLE`. A `DENY` decision moves a screened application to `DENIED`, which is terminal.

At any point while an application is in `SUBMITTED`, `SCREENED`, or `APPROVED`, it may be withdrawn, moving it to the terminal `WITHDRAWN` state; this action is available to the `Applicant` themselves or to a `PropertyManager`. An approved application is consumed when a lease created from it is signed: at that moment the system advances the application to its terminal `LEASED` state.

### 3.3. Lease Origination

A lease is the contract binding a tenant to a unit, and it begins in `DRAFT`. A `PropertyManager` drafts a lease against a `unit_id`, with a term defined by `start_date` and `end_date` (ISO dates, the end exclusive and required to be strictly after the start), a `monthly_rent_cents` greater than zero, and several rent-roll parameters described in the rent-collection workflow. There are two flavors of lease creation. An **original** lease must name an `applicant_id` identifying the approved applicant it is built from. A **renewal** lease instead carries a `renewed_from_lease_id` pointing at the prior lease, omits `applicant_id` entirely (it inherits the prior lease's tenant), and must carry `expected_lease_version` for the concurrency check described in the OCC principle. The lease exposes a computed `tenant_id` pointer that is null in `DRAFT` and set at signing, and a computed `superseded_by_lease_id` pointer that is filled in when a later renewal replaces this lease.

When a lease is created, two temporal guards apply. A new lease's half-open term — covering `start_date` up to but not including `end_date` — must not overlap the term of any existing `ACTIVE` or `RENEWAL_OFFERED` lease on the same unit, except the very prior lease being renewed; pure adjacency, where the previous lease's `end_date` equals the new lease's `start_date`, is allowed because the half-open intervals do not actually intersect. A violation is rejected with `ERR_LEASE_OVERLAP`. For a non-renewal lease the unit must additionally be `VACANT_READY` at creation, or the create is refused with `ERR_UNIT_NOT_AVAILABLE`; a renewal whose `renewed_from_lease_id` equals the unit's `active_lease_id` is exempt from this availability requirement, because signing it will supersede the lease currently occupying the unit.

Before a draft can be signed, a security deposit must already have been collected for it (see deposit accounting). Signing is performed by a `PropertyManager` and advances the lease from `DRAFT` to `ACTIVE`. Signing is gated by several preconditions evaluated together. For an original lease, the applicant named by `applicant_id` must be in `APPROVED`, or the sign is refused with `ERR_APPLICANT_NOT_APPROVED`; a renewal performs no applicant check because it inherits its tenant from the prior lease. The unit must be `VACANT_READY`, unless this is a renewal whose `renewed_from_lease_id` equals the unit's `active_lease_id`, in which case the renewal exemption applies and the still-`OCCUPIED` unit is acceptable; otherwise the sign is refused with `ERR_UNIT_NOT_AVAILABLE`. A `SecurityDeposit` in `HELD` status must exist for the lease, or the sign is refused with `ERR_DEPOSIT_REQUIRED`.

Signing drives a chain of cascading effects. For an original lease, the system mints a `Tenant` from the source applicant and sets the lease's `tenant_id` to that new tenant; for a renewal, the lease's `tenant_id` is set to the prior lease's `tenant_id`, so the same tenant carries forward and stays `CURRENT`. For an original lease, the source application is advanced to `LEASED`, driven by the lease activation. The unit is then driven to `OCCUPIED` and its `active_lease_id` is pointed at this lease. Finally, if this is a renewal, the prior lease is advanced to `EXPIRED` and its `superseded_by_lease_id` is set to this lease's `id`, completing the supersession of the old contract by the new one.

### 3.4. The Renewal Cycle and Lease Wind-Down

A standing renewal offer is a reversible state on an active lease. A `PropertyManager` may extend a renewal offer on a lease that is `ACTIVE`, moving it to `RENEWAL_OFFERED`; the same operation, invoked on a lease already in `RENEWAL_OFFERED`, retracts the standing offer and returns the lease to `ACTIVE`. This forms a cyclic edge `ACTIVE → RENEWAL_OFFERED → ACTIVE`. Either direction of the toggle requires `expected_lease_version` to match the lease's current `version`, failing which the request is rejected with `ERR_STALE_VERSION`, and either direction increments the lease's `version` by one.

An active lease whose term has run out can be expired by a `PropertyManager` once the supplied `as_of_date` is on or after the lease's `end_date`; expiring before the term has ended — an `as_of_date` earlier than `end_date` — is refused with `ERR_LEASE_NOT_ENDED`. Expiry advances the lease from `ACTIVE` to the terminal `EXPIRED` state and cascades: the unit is driven to `VACANT_TURN` and its `active_lease_id` is cleared to null, and the tenant on the lease is advanced to `FORMER`.

A lease may also be terminated, but never by direct request — termination is exclusively a downstream effect of an eviction being enforced, described in the eviction workflow. The `TERMINATED` state, like `EXPIRED`, is terminal.

### 3.5. Rent Roll, Payments, and the Late-Fee Sweep

Several lease-level parameters configure how rent is billed and when it falls late. The `rent_due_day` is the day of the month rent is due; it defaults to 1 and must lie between 1 and 28 inclusive. The `grace_period_days` is the number of days after a charge's due date before a late fee applies (defaulting to 5 and never negative), and the late-fee amount is built from a flat component, `late_fee_flat_cents` (defaulting to 0, never negative), plus a percentage component, `late_fee_pct` (defaulting to 0, a decimal fraction between 0 and 0.25 inclusive).

Rent is billed through charges and settled through payments. A `PropertyManager` posts a rent charge against a `lease_id`, declaring the billing `period_label` (for example "2026-06" for a rent charge), a `due_date`, an `amount_cents` strictly greater than zero, and a `charge_type` that defaults to `RENT`. A rent charge is created `OPEN`, and posting it recomputes the lease's outstanding balance. Each charge tracks `amount_paid_cents` (cumulative payment applied), `amount_outstanding_cents` (the charge amount less what has been paid, never negative), a `late_fee_assessed` boolean recording whether the late-fee sweep has already generated a fee for it, and a `status` among `OPEN`, `PARTIAL`, `PAID`, and `WAIVED`. The lease's own `balance_due_cents` is the sum of `amount_outstanding_cents` across its charges that are still `OPEN` or `PARTIAL`.

Late fees are generated by an explicit sweep that a `PropertyManager` runs against a lease as of a supplied `as_of_date`. The sweep walks every `RENT` charge on the lease that is still `OPEN` or `PARTIAL` and whose `late_fee_assessed` flag is still false. For each such charge it computes the late cutoff as the charge's `due_date` plus the lease's `grace_period_days`; the grace period is inclusive, so the cutoff day itself is still on time. Only when the sweep date is strictly after that cutoff is a fee owed — a sweep landing exactly on the last grace day, where `as_of_date` equals `due_date` plus `grace_period_days`, produces nothing. When a fee is owed, its amount is the lease's `monthly_rent_cents` multiplied by the lease's `late_fee_pct`, rounded half-up to whole cents, and then the lease's `late_fee_flat_cents` is added on top of that rounded figure. If the resulting fee is positive, the system creates a new `LATE_FEE` charge whose `amount_cents` is that fee, whose `due_date` is the sweep date, and whose `period_label` is null, and it sets the source rent charge's `late_fee_assessed` flag to true so the same charge is never assessed twice. After processing all eligible charges, the lease's balance due is recomputed.

A payment is recorded by a `PropertyManager` or by the `Tenant` against a `lease_id`, with an `amount_cents` greater than zero and a `received_date`. The payment is distributed across the lease's open charges by a fixed waterfall. The candidate set is every charge on the lease that is `OPEN` or `PARTIAL`. Those candidates are ordered by, first, charge type — `LATE_FEE` charges (rank 0) are paid before `RENT` charges (rank 1) — then by `due_date` ascending, then by `created_at` ascending as the final tie-break; the charge `id` is never used for ordering. The system then walks the ordered charges, applying to each the smaller of the payment's remaining amount and that charge's outstanding amount, recording each application as a `{charge_id, applied_cents}` entry appended to the payment's `applied_breakdown`, and reducing the remaining amount accordingly until either the charges are exhausted or the payment runs out. As each charge receives money it advances through its own state machine: a charge that receives part but not all of its outstanding amount moves from `OPEN` to `PARTIAL`; a charge whose cumulative `amount_paid_cents` reaches its `amount_cents` moves to `PAID` (whether it gets there in one application from `OPEN` or across applications from `PARTIAL`), and its outstanding amount becomes zero. Every charge that changes triggers recomputation of the lease's balance due.

The waterfall also feeds the trust ledger. As money lands on charges, the portion applied to `RENT` charges is summed into the payment's `applied_to_rent_cents`; that rent portion is credited to the owning property's `trust_balance_cents` and the property's distributable amount is recomputed. Any money left after every open charge is fully covered is recorded as the payment's `unapplied_cents` and retained as a tenant credit — it is never automatically refunded.

A `LATE_FEE` charge that an operator decides to forgive can be waived by a `PropertyManager`. Waiving is permitted only while the charge is `OPEN` or `PARTIAL`, and only on a charge whose `charge_type` is `LATE_FEE`; attempting to waive a `RENT` charge is refused with `ERR_CANNOT_WAIVE_RENT`. A successful waiver drives the charge to the terminal `WAIVED` state, zeroes its outstanding amount, and recomputes the lease's balance due.

### 3.6. Security Deposits and State Interest

A deposit is collected by a `PropertyManager` before a lease is signed. Collection records the `lease_id` it secures, the `collected_cents` taken (which must be non-negative), and the `collected_date`. A new deposit opens in `HELD`. The deposit also carries computed fields filled in only at settlement: `interest_accrued_cents`, `deductions_cents`, `refund_cents`, and the `settlement_date`.

Settlement is run by a `PropertyManager` and may proceed only once the lease the deposit secures has reached `EXPIRED` or `TERMINATED`; attempting to settle while the lease is still active is refused with `ERR_LEASE_STILL_ACTIVE`. The operator supplies the `settlement_date` and optionally `damage_deductions_cents` (defaulting to 0). Settlement runs two calculations in sequence.

First, state interest accrues. The applicable annual simple-interest rate is determined by the owning property's `state_code` — reached from the deposit's lease, to the lease's unit, to that unit's property. New York accrues at 0.0150 and Illinois at 0.0050; California, Florida, and Texas accrue nothing at all, so a deposit on a property in any of those three states earns zero interest no matter how long it was held. Only fully completed 365-day years accrue: the number of accruing years is the count of whole days between the collection date and the settlement date, divided by 365 and taken as the floor (its whole-number part), so a partial year contributes nothing. The accrued interest is the collected principal multiplied by the state rate multiplied by that whole-year count, rounded half-up to whole cents, and is stored in `interest_accrued_cents`.

Second, the deduction waterfall runs against the available amount, which is the collected principal plus the accrued interest. Deductions are taken in a fixed order: first, outstanding lease arrears — the smaller of the available amount and the lease's current `balance_due_cents` — is taken; then from what remains, requested damages — the smaller of the still-available amount and `damage_deductions_cents` — is taken. The two together are recorded as `deductions_cents`, and whatever remains after both is the `refund_cents`. If the refund is positive the deposit settles: its status becomes `SETTLED`, and the refund is debited from the property's `trust_balance_cents` (with the distributable amount recomputed); should the trust lack the funds for that refund, the settlement is refused with `ERR_TRUST_INSUFFICIENT`. If instead the computed refund is zero and the total deductions exactly consume the entire available amount — that is, deductions equal the collected principal plus accrued interest — the deposit is `FORFEITED` instead: the full balance is retained against arrears and damages, no refund is paid, and no trust debit occurs. A common path into forfeiture is when arrears alone meet or exceed the principal-plus-interest, leaving nothing for damages and nothing to refund.

### 3.7. Maintenance Work Orders

Maintenance begins with a work order, which may be opened by a `PropertyManager` or by a `Tenant`. The request names the `unit_id` needing attention, a `category` (one of `PLUMBING`, `ELECTRICAL`, `HVAC`, `APPLIANCE`, `STRUCTURAL`, or `OTHER`), and a free-text `description`. The caller may set a `priority` of `EMERGENCY`, `URGENT`, or `ROUTINE` (defaulting to `ROUTINE`), an `estimate_cents` of the expected cost (defaulting to 0), and a `charge_to_owner` flag (defaulting to true) that decides whether the eventual actual cost is billed to the property trust. A work order opens in `OPEN`.

A `PropertyManager` assigns an open work order to a vendor, advancing it from `OPEN` to `ASSIGNED`. Completion, also by a `PropertyManager`, requires the work order to be `ASSIGNED` and requires the request to supply `actual_cost_cents` — completion without it is refused with `ERR_ACTUAL_COST_REQUIRED`. Completion records that actual cost and the `completed_date`, and advances the order to the terminal `COMPLETED` state. If the order's `charge_to_owner` flag is set, the actual cost is debited from the property's `trust_balance_cents` and the distributable figure is recomputed; if the trust cannot cover the debit, completion is refused with `ERR_TRUST_INSUFFICIENT`. A work order may instead be cancelled by a `PropertyManager` from either `OPEN` or `ASSIGNED`, moving it to the terminal `CANCELLED` state with no financial effect.

### 3.8. The Eviction Process

An eviction begins when a `PropertyManager` serves a notice against a `lease_id`, declaring the `reason` (one of `NONPAYMENT`, `LEASE_VIOLATION`, or `HOLDOVER`) and the `notice_date`. Serving the notice computes the cure deadline and snapshots the arrears. The cure window in whole days is looked up from the owning property's `state_code` and the eviction reason, and the `cure_deadline_date` is the notice date plus that many days. The state-and-reason cure tables differ markedly: for nonpayment the cure window is 3 days in California, Texas, and Florida, 5 days in Illinois, and 14 days in New York; for a lease violation it is 3 days in California and Texas, 7 in Florida, and 10 in New York and Illinois; for a holdover it is 30 days in California, New York, and Illinois, 15 in Florida, and 3 in Texas. The lease's `balance_due_cents` at the moment the notice is served is snapshotted into `arrears_at_notice_cents`. A new notice opens in `NOTICE_SERVED`.

Serving a notice is blocked when it would overlap an in-flight case on the same lease. If any existing non-terminal eviction case on the lease has a closed window running from its `notice_date` through its `cure_deadline_date`, and the new notice's `notice_date` falls anywhere inside that window — inclusive of both the opening and closing endpoints — the new notice is rejected with `ERR_EVICTION_WINDOW_OVERLAP`.

From `NOTICE_SERVED` the case can branch. A `PropertyManager` may mark the case cured, moving it to `CURED`, but only while the cure window is still open — the supplied `as_of_date` must be on or before the `cure_deadline_date`, otherwise the cure is refused with `ERR_CURE_WINDOW_CLOSED` — and, when the reason is `NONPAYMENT`, only once the lease's `balance_due_cents` has been brought to zero, failing which it is refused with `ERR_ARREARS_NOT_CLEARED`. Alternatively, a `ComplianceOfficer` may file the case, moving it to `FILED`, but only after the cure window has closed — the supplied `as_of_date` must be strictly after the `cure_deadline_date`, and attempting to file while the window is still open is refused with `ERR_CURE_WINDOW_OPEN`.

A `ComplianceOfficer` enforces a filed case, advancing it to the terminal `ENFORCED` state, but only while the underlying lease is still `ACTIVE` — enforcing against a lease in any other status is refused with `ERR_INVALID_STATE`. Enforcement drives the lease from `ACTIVE` to `TERMINATED`, and that lease termination cascades exactly as the eviction-driven wind-down: the tenant is advanced to `FORMER`, the unit is driven to `VACANT_TURN` with its `active_lease_id` cleared to null, and a turnover project is automatically opened for the unit, with its `opened_date` set to the enforcement date and its `target_ready_date` set to that date plus the default turnaround of 14 days. Finally, a `ComplianceOfficer` may dismiss a case that is either `CURED` or `FILED`, moving it to the terminal `DISMISSED` state.

### 3.9. Vacancy Turnover

When a lease ends — whether by ordinary expiry or by eviction enforcement — its unit lands in `VACANT_TURN` and the make-ready work is tracked by a turnover project. Eviction enforcement opens this project automatically, as just described; for an ordinary expiry a `PropertyManager` opens it by naming the `unit_id`, the `opened_date`, a `target_ready_date` (which must be on or after the opened date), and an optional `make_ready_cost_cents` (defaulting to 0). A turnover opens in `OPEN`.

A `PropertyManager` starts the make-ready work, advancing the project from `OPEN` to `IN_PROGRESS`, then completes it, advancing it from `IN_PROGRESS` to the terminal `READY` state. Completion is blocked while the unit still has any work order in `OPEN` or `ASSIGNED` status; such open maintenance refuses the completion with `ERR_OPEN_WORK_ORDERS`. On successful completion the unit is returned to `VACANT_READY`, making it leasable again, and if a `make_ready_cost_cents` greater than zero was recorded, that cost is debited from the property's `trust_balance_cents` (with the distributable amount recomputed); a trust too thin to absorb the make-ready cost refuses completion with `ERR_TRUST_INSUFFICIENT`.

### 3.10. Owner Statements and Distributions

Periodically the manager reconciles a property's activity to its owner through a statement. A `PropertyManager` creates a statement against a `property_id` for a given `period_label` and a `basis` of either `CASH` or `ACCRUAL` (defaulting to `CASH`). The statement opens in `DRAFT` with its money fields unset, and it exposes computed `gross_cents`, `management_fee_cents`, `maintenance_cents`, `net_to_owner_cents`, and `distribution_cents`.

Finalizing the statement, by a `PropertyManager`, freezes its figures and advances it from `DRAFT` to `FINALIZED`. The set of leases in scope is every lease whose unit belongs to the statement's property. The gross depends on the basis. On a cash basis the gross is the sum of the rent actually collected in the period — that is, the `applied_to_rent_cents` of every payment on those leases whose `received_date` falls within the month named by the period. On an accrual basis the gross is instead the sum of `amount_cents` over the `RENT` charges on those leases whose `period_label` equals the statement's period, counting rent that was billed regardless of whether it was paid — generally a different figure from the cash gross for the same property and period. The management fee is the gross multiplied by the owner's `management_fee_pct`, rounded half-up to whole cents once on the gross total. The maintenance figure is the sum of `actual_cost_cents` over the work orders on those units that are `COMPLETED`, carry `charge_to_owner` true, and whose `completed_date` falls within the period's month. The net to owner is the gross minus the management fee minus the maintenance, floored at zero so it never goes negative.

Distributing a finalized statement is the act of actually paying the owner. It is performed by a `PropertyManager`, requires the statement to be `FINALIZED`, and is guarded by the property-version concurrency check: the request must carry `expected_property_version` matching the property's current `version`, or it is rejected with `ERR_STALE_VERSION`. There must also be something to pay — the property's `distributable_cents` must be at least 1, otherwise the distribution is refused with `ERR_NOTHING_TO_DISTRIBUTE`. The amount actually paid, recorded as `distribution_cents`, is the smaller of the statement's `net_to_owner_cents` and the property's current `distributable_cents`, so a distribution can never exceed what the trust is permitted to release. That amount is debited from the property's `trust_balance_cents`, the distributable amount is recomputed, the property's `version` is incremented, and the statement advances to the terminal `DISTRIBUTED` state. A distribution can never drive the trust below zero; were the computed debit to do so it would be refused with `ERR_TRUST_INSUFFICIENT`.

### 3.11. Tenants

A `Tenant` is not created directly through the API; a tenant record is minted as a side effect of signing an original lease, carrying the `applicant_id` it was promoted from, the `full_name` and `email` copied from that application, and a `status` that begins at `CURRENT`. A tenant moves to `FORMER` when the lease that the tenant holds ends, whether through expiry or through eviction enforcement. Tenant records are readable by a `PropertyManager` and, for their own record, by the `Tenant`, and may be listed filtered by `applicant_id`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including all state transitions and all settlement, sweep, distribution, and funding actions — return `200 OK`. List and single-resource reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/owners` | Create an owner | PropertyManager |
| GET | `/owners/{ownerId}` | Get an owner | PropertyManager, Owner |
| POST | `/properties` | Create a property under an owner | PropertyManager |
| GET | `/properties/{propertyId}` | Get a property, including trust ledger and version | PropertyManager, Owner |
| GET | `/properties` | List properties, optionally filtered by `owner_id` | PropertyManager, Owner |
| POST | `/properties/{propertyId}/trust-deposits` | Record a manual trust funding | PropertyManager |
| POST | `/units` | Create a unit under a property | PropertyManager |
| GET | `/units/{unitId}` | Get a unit | PropertyManager, Owner, Tenant |
| GET | `/units` | List units, optionally filtered by `property_id` | PropertyManager, Owner |
| POST | `/applicants` | Submit a rental application | PropertyManager, Applicant |
| GET | `/applicants/{applicantId}` | Get an applicant, including screening outputs | PropertyManager, Applicant |
| GET | `/applicants` | List applicants, filtered by `unit_id` or `status` | PropertyManager |
| POST | `/applicants/{applicantId}/screen` | Run tenant screening | PropertyManager |
| POST | `/applicants/{applicantId}/decide` | Approve or deny a screened applicant | PropertyManager |
| POST | `/applicants/{applicantId}/withdraw` | Withdraw an application | Applicant, PropertyManager |
| POST | `/leases` | Create a draft lease (original or renewal) | PropertyManager |
| GET | `/leases/{leaseId}` | Get a lease, including balance due and version | PropertyManager, Owner, Tenant |
| GET | `/leases` | List leases, filtered by `unit_id`, `applicant_id`, `renewed_from_lease_id`, or `status` | PropertyManager, Owner |
| POST | `/leases/{leaseId}/sign` | Sign a draft lease, activating it | PropertyManager |
| POST | `/leases/{leaseId}/offer-renewal` | Offer or retract a renewal | PropertyManager |
| POST | `/leases/{leaseId}/expire` | Expire an active lease whose term has ended | PropertyManager |
| POST | `/leases/{leaseId}/assess-late-fees` | Run the late-fee sweep as of a date | PropertyManager |
| POST | `/rent-charges` | Post a rent charge on a lease | PropertyManager |
| GET | `/rent-charges/{chargeId}` | Get a rent charge | PropertyManager, Owner, Tenant |
| GET | `/rent-charges` | List rent charges, filtered by `lease_id`, `status`, or `charge_type` | PropertyManager, Owner, Tenant |
| POST | `/rent-charges/{chargeId}/waive` | Waive a late-fee charge | PropertyManager |
| POST | `/payments` | Record a payment; runs the allocation waterfall | PropertyManager, Tenant |
| GET | `/payments/{paymentId}` | Get a payment, including applied breakdown | PropertyManager, Owner, Tenant |
| GET | `/payments` | List payments, filtered by `lease_id` | PropertyManager, Owner, Tenant |
| POST | `/security-deposits` | Collect a security deposit for a lease | PropertyManager |
| GET | `/security-deposits/{depositId}` | Get a security deposit | PropertyManager, Owner, Tenant |
| GET | `/security-deposits` | List security deposits, filtered by `lease_id` | PropertyManager, Owner, Tenant |
| POST | `/security-deposits/{depositId}/settle` | Settle a deposit: accrue interest, deduct, refund | PropertyManager |
| POST | `/work-orders` | Open a maintenance work order | PropertyManager, Tenant |
| GET | `/work-orders/{workOrderId}` | Get a work order | PropertyManager, Owner, Tenant |
| GET | `/work-orders` | List work orders, filtered by `unit_id` or `status` | PropertyManager, Owner, Tenant |
| POST | `/work-orders/{workOrderId}/assign` | Assign an open work order | PropertyManager |
| POST | `/work-orders/{workOrderId}/complete` | Complete a work order with actual cost | PropertyManager |
| POST | `/work-orders/{workOrderId}/cancel` | Cancel a work order | PropertyManager |
| POST | `/evictions` | Serve an eviction notice | PropertyManager |
| GET | `/evictions/{evictionId}` | Get an eviction case | PropertyManager, ComplianceOfficer, Owner |
| GET | `/evictions` | List eviction cases, filtered by `lease_id` or `status` | PropertyManager, ComplianceOfficer, Owner |
| POST | `/evictions/{evictionId}/cure` | Mark an eviction cured within the window | PropertyManager |
| POST | `/evictions/{evictionId}/file` | File the eviction after the cure window closes | ComplianceOfficer |
| POST | `/evictions/{evictionId}/enforce` | Enforce a filed eviction; terminates the lease | ComplianceOfficer |
| POST | `/evictions/{evictionId}/dismiss` | Dismiss an eviction case | ComplianceOfficer |
| POST | `/owner-statements` | Create a draft owner statement | PropertyManager |
| GET | `/owner-statements/{statementId}` | Get an owner statement | PropertyManager, Owner |
| GET | `/owner-statements` | List statements, filtered by `property_id` or `status` | PropertyManager, Owner |
| POST | `/owner-statements/{statementId}/finalize` | Finalize a statement; computes its figures | PropertyManager |
| POST | `/owner-statements/{statementId}/distribute` | Distribute net to owner, bounded by trust | PropertyManager |
| POST | `/turnovers` | Open a vacancy turnover for a unit | PropertyManager |
| GET | `/turnovers/{turnoverId}` | Get a turnover project | PropertyManager, Owner |
| GET | `/turnovers` | List turnovers, filtered by `unit_id` or `status` | PropertyManager, Owner |
| POST | `/turnovers/{turnoverId}/start` | Start make-ready work | PropertyManager |
| POST | `/turnovers/{turnoverId}/complete` | Complete turnover; returns the unit to ready | PropertyManager |
| GET | `/tenants/{tenantId}` | Get a tenant | PropertyManager, Tenant |
| GET | `/tenants` | List tenants, filtered by `applicant_id` | PropertyManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SCREENING_FAILED` | 409 |
| `ERR_APPLICANT_NOT_APPROVED` | 409 |
| `ERR_UNIT_NOT_AVAILABLE` | 409 |
| `ERR_DEPOSIT_REQUIRED` | 409 |
| `ERR_LEASE_NOT_ENDED` | 409 |
| `ERR_LEASE_OVERLAP` | 409 |
| `ERR_EVICTION_WINDOW_OVERLAP` | 409 |
| `ERR_LEASE_STILL_ACTIVE` | 409 |
| `ERR_CANNOT_WAIVE_RENT` | 409 |
| `ERR_CURE_WINDOW_CLOSED` | 409 |
| `ERR_CURE_WINDOW_OPEN` | 409 |
| `ERR_ARREARS_NOT_CLEARED` | 409 |
| `ERR_OPEN_WORK_ORDERS` | 409 |
| `ERR_ACTUAL_COST_REQUIRED` | 422 |
| `ERR_TRUST_INSUFFICIENT` | 409 |
| `ERR_NOTHING_TO_DISTRIBUTE` | 409 |
