# Commercial Lease Abstraction API — Product Requirements Document

## 1. Introduction

Lease administration teams sit at the intersection of legal documents, accounting ledgers, and calendar-driven risk. A single commercial lease generates decades of obligations: base rent schedules with escalation clauses, recovery structures that determine which operating expense pools can be billed back to the tenant, critical dates for options and renewals that lapse silently if nobody acts, and an annual reconciliation cycle in which estimated billings are trued up against actual incurred costs — often under the tenant's contractual right to audit. Today these workflows live in spreadsheets and side calendars, where a missed notice deadline or a mis-applied gross-up rule turns directly into lost revenue or litigation.

This document specifies the Commercial Lease Abstraction API, a system that manages the full administrative lifecycle of commercial leases from document abstraction through portfolio reporting. The platform governs how lease documents are abstracted into certified key data points under segregation of duties, how rent schedules and escalation steps produce the current rent roll, how recovery pools are budgeted, billed as estimates, and reconciled against actuals at fiscal year-end, and how tenant challenges and audit rights are processed through bounded negotiation rounds. A logical clock drives all date-sensitive behavior — expirations, lapses, and time-bars — so that the passage of time is itself an auditable, controllable input rather than an ambient accident.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes six distinct roles: `PlatformAdmin`, `PortfolioManager`, `PropertyManager`, `LeaseAccountant`, `Abstractor`, and `Certifier`. If the `X-User-Role` header is missing or carries a value outside this declared set, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but not authorized for the target endpoint per the authorization matrix in §4, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

For every role in this system, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it against any entity's `id`. The server does, however, record it on specific resources where a transition writes it: when `X-User-Role` is `Abstractor`, the submitting operator's `X-User-ID` is stored as `abstractor_user_id` on the Lease; when `X-User-Role` is `Certifier`, the certifying operator's `X-User-ID` is stored as `certifier_user_id`; when `X-User-Role` is `LeaseAccountant` posting a reconciliation, the operator's `X-User-ID` is stored as `posted_by_user_id`; and when `X-User-Role` is `PortfolioManager` approving a reconciliation, the operator's `X-User-ID` is stored as `approved_by_user_id`. The `PlatformAdmin`, `PortfolioManager`, `PropertyManager`, and `LeaseAccountant` roles otherwise act under opaque identifiers that the system may record for audit but does not resolve to entity rows.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system — Property, Lease, RentScheduleLine, EscalationStep, RecoveryPool, RecoveryBilling, Reconciliation, CriticalDate, ComplianceDoc, Amendment, TenantChallenge, and AuditRight — carries a standard set of system-managed fields:

- **`id` (string):** A unique, server-minted identifier for the resource, formatted as a UUID with no type prefix.
- **`created_at` (string):** An ISO 8601 timestamp in UTC with three fractional digits (e.g., `2026-05-01T00:00:00.000Z`), set when the resource is first created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp with three fractional digits, refreshed upon any change to the resource's properties.
- **`version` (integer):** A system-managed integer that increments by one with every mutation of the resource. This field is the basis of optimistic concurrency control where an endpoint elects to require it.

Any mutation of a resource — including mutations driven by cascades from a related entity, such as a lease's cached figures being recomputed when a schedule line changes — refreshes that resource's `updated_at` and increments its `version`. Child collections foreign-keyed to a parent, such as the `lease_id` on a RentScheduleLine or the `property_id` on a RecoveryPool, are system-populated from the URL context at creation and are never accepted as client input.

### 2.5. Nested Resource Retrieval

The API enforces a strict, hierarchical validation protocol for all requests that target nested resources. When an endpoint path contains multiple resource identifiers, the system validates the existence of each identifier in a sequential, left-to-right order: `property_id` before `lease_id` before the child identifier (such as `line_id`, `step_id`, `pool_id`, `billing_id`, `recon_id`, `cd_id`, `doc_id`, `amendment_id`, `challenge_id`, or `audit_id`). The request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) corresponding to the first identifier in the path that does not resolve to an existing resource. A request addressed to a child beneath a non-existent parent therefore fails on the parent before the child is ever examined.

### 2.6. Monetary Precision, Rounding, and Basis Points

All monetary amounts in the system are carried as integer cents; there are no fractional-cent values anywhere in the API. Wherever a calculation produces a fractional cent, the result is rounded to whole cents — zero decimal places — using the round-half-up method. Percentages that must be exact are expressed in basis points, where a denominator of 10000 basis points equals one hundred percent; this convention governs `pro_rata_share_bps`, `pct_bps`, and `gross_up_floor_pct_bps` alike.

Rounding order is significant and is pinned by the system: per-line amounts are rounded individually first, and any aggregate total is a sum of already-rounded line amounts, never a rounding of the summed raw values. Per-line rounding followed by summation can legitimately produce different cents than summing raw values and rounding once at the end; the system always chooses the former.

### 2.7. The Logical Clock and the Fiscal Calendar

The server maintains a logical UTC clock that governs every date-sensitive rule in the system. At server startup the logical clock defaults to `2026-05-01T00:00:00Z` and does not fall back to wall-clock time; the only way time advances is through an admin-only test-driving capability that sets the logical clock to a supplied `to_iso8601` instant and reports the resulting `current_utc`. Advancing the clock is not a passive read: it triggers all date-driven system transitions whose thresholds have been crossed, including lease expiration, critical-date lapsing, compliance-document expiry, and audit-right time-barring, each as described in §3.

Each Property declares its own fiscal calendar through `fiscal_year_end_month`, an integer from 1 to 12 identifying the month in which the property's fiscal year ends. The four-digit label Y denotes the fiscal year that ends on the last day of that month within calendar year Y and begins the day after the prior fiscal year's end; every fiscal-year span is treated as half-open — running from its first day up to but not including the day after its last day — so "the fiscal year's start" is that first day and "the fiscal year's end" in the overlap tests of §3 is the exclusive end boundary, the day after that last day. "The current fiscal year" at any moment is the labeled fiscal year whose span contains the current logical date. Fiscal-year boundaries derived from this month determine which RentScheduleLine rows overlap "the current fiscal year" for cached-rent purposes, and fiscal years are referenced by their four-digit calendar label `fiscal_year` throughout billing, pooling, and reconciliation.

### 2.8. Derived State Dimensions and Hierarchical Consistency

A Lease carries three parallel state dimensions that evolve independently: `status` (the primary lifecycle: `DRAFT`, `ACTIVE`, `EXPIRED`, `TERMINATED`), `abstraction_status` (data quality: `PENDING`, `ABSTRACTED`, `CERTIFIED`), and `billing_posture` (financial health: `CURRENT`, `FROZEN`, `DELINQUENT`). The third dimension is never set directly; it is a derived recomputation triggered by changes in child collections. When any RecoveryBilling of the lease enters `DISPUTED`, the lease's `billing_posture` transitions to `FROZEN`; when every RecoveryBilling has exited `DISPUTED`, the posture returns to `CURRENT`. Independently, when any `ISSUED` RecoveryBilling remains unpaid more than 60 days past its `issued_at` timestamp, the posture transitions to `DELINQUENT`; once all past-due `ISSUED` rows have reached `PAID` or `VOID`, the posture returns to `CURRENT`. Each recomputation of `billing_posture` is a mutation of the Lease and therefore refreshes `updated_at` and increments `version`.

Derivation also flows upward across the hierarchy. A Property's `posture` is `SUSPENDED` whenever at least one `ACTIVE` lease on that property has `billing_posture` equal to `FROZEN`, and `OPERATING` otherwise; it is recomputed whenever a relevant child event occurs — a billing becoming disputed or undisputed, a lease activating, or a lease terminating. More broadly, when a parent resource undergoes a transition that ends its operational life, the system resolves dependent child resources in the same atomic request — there is no asynchronous reconciliation — and conversely, child mutations that bear on a parent's derived fields cause the parent to be recomputed immediately.

### 2.9. Segregation of Duties

Two transitions in the system are segregation-controlled: the person who performed the preparatory work may not be the person who signs it off. Certification of a lease abstraction requires that the acting operator's `X-User-ID` differ from the lease's recorded `abstractor_user_id`; approval of a posted reconciliation requires that the acting operator's `X-User-ID` differ from the reconciliation's recorded `posted_by_user_id`. A same-user attempt on either transition is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). The recorded counterpart fields — `certifier_user_id` on the Lease and `approved_by_user_id` on the Reconciliation — are populated by the system at the moment the segregated transition succeeds, and `certifier_user_id` must always differ from `abstractor_user_id` on a certified lease.

### 2.10. Optimistic Concurrency Control

Exactly two write endpoints in the system are guarded by optimistic concurrency control against the Lease's `version`: approval of an Amendment, and reopening of a certified abstraction. Each of these requests must carry `expected_lease_version`, a non-optional input field holding the client's last observed `version` of the parent Lease. If the value does not match the Lease's current `version` — because another writer has advanced the lease since the client last read it, for example by approving a different amendment against the same lease — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a lease state it has not observed. Endpoints not named here do not take a version field at all.

### 2.11. Validation Pipeline Ordering

Every request passes through a fixed validation pipeline, and the order is part of the contract: an earlier failure masks every later check, so the error a client observes is always the earliest applicable one. The pipeline runs in this sequence. First, authentication: the `X-User-Role` header must be present and one of the declared roles, else `ERR_UNAUTHENTICATED`. Second, authorization: the role must be permitted on the endpoint, else `ERR_FORBIDDEN`. Third, existence: path-templated identifiers must resolve, validated left-to-right as described in §2.5, else `ERR_NOT_FOUND`. Fourth, request shape: required request-body fields must be present and well-typed — dates in ISO `YYYY-MM-DD` form, enum values within their declared sets, integers within their declared ranges — else `ERR_INVALID_REQUEST` (HTTP 400). Fifth, temporal well-formedness on entity-creation endpoints and amendment application: a `period_start` must precede its `period_end`, a `commencement_date` must precede the `expiration_date`, a new CriticalDate's `due_date` must not be in the past, and an amendment's `effective_date` must not precede the lease's `commencement_date`, else `ERR_INVALID_DATE_RANGE` (HTTP 422). Sixth, state-machine legality on every state-transition endpoint, else `ERR_INVALID_STATE` (HTTP 409). Seventh, segregation of duties as defined in §2.9. Eighth, referential integrity of cross-referenced entities, else `ERR_REFERENTIAL_INTEGRITY` (HTTP 422). Ninth, the schedule-overlap guard on rent-schedule-line creation. Tenth, the coverage-overlap guard on compliance-document acceptance. Eleventh, the aggregate-capacity guard on expansion amendments. Twelfth, the fiscal gates on activation, termination, and reconciliation close. Thirteenth, the notification, exercise, and audit window checks. Fourteenth, and last, the OCC precondition on the two version-guarded endpoints. Business rules named at each stage are detailed in the workflow narratives of §3.

## 3. Business Logic & Workflows

### 3.1. Portfolio Foundation: Properties and Leases

Everything begins with the Property. A `PlatformAdmin` creates a Property by supplying a display `name`, a street `address`, the `total_rentable_sf` (an integer of at least 1), and the `fiscal_year_end_month`. A new Property's `posture` starts at `OPERATING`. At any time, an authorized operator may retrieve a computed occupancy report for a property and fiscal year, which returns the `occupied_sf`, the `total_rentable_sf`, and the derived `occupancy_rate_bps`. Occupied square footage is the sum of `leased_sf` over all leases on the property that are `ACTIVE` and whose term overlaps the fiscal year — that is, whose `commencement_date` falls before the fiscal year's end and whose `expiration_date` falls after the fiscal year's start. The occupancy rate in basis points is the occupied square footage multiplied by 10000 and divided by the property's total rentable square footage, rounded half-up to a whole basis point; when nothing is occupied, the rate is 0.

Against a Property, a `PortfolioManager` creates a Lease by providing the `tenant_legal_name`, the `suite` identifier, the `leased_sf` (at least 1 and no greater than the owning property's total rentable square footage), the `commencement_date` and `expiration_date`, the `base_rent_annual_cents` (zero or greater), the `escalation_type` (one of `NONE`, `FIXED_PCT`, `CPI`, or `STEPPED`), the `recovery_structure` (one of `NNN`, `MODIFIED_GROSS`, or `GROSS`), the `pro_rata_share_bps` (from 0 to 10000), and the `security_deposit_cents` (zero or greater). A new Lease begins with `status` of `DRAFT`, `abstraction_status` of `PENDING`, and `billing_posture` of `CURRENT`. The lease collection supports filtering by `property_id`, `status`, `abstraction_status`, or `billing_posture`, and a property's leases can also be listed as a sub-resource of the property itself. Two derived figures ride along on every Lease: `cached_annual_rent_cents`, the current-fiscal-year scheduled base rent derived from its rent schedule and refreshed on any schedule mutation, and `cached_recovery_ytd_cents`, the year-to-date total of recovery billings in `ISSUED` or `PAID` status for the current fiscal year.

### 3.2. Abstraction, Certification, and Reopening

Before a lease may go live, its document must be abstracted and the abstraction independently certified. An `Abstractor` submits the abstraction for a lease still in `DRAFT` status, moving `abstraction_status` from `PENDING` to `ABSTRACTED`; the submission is rejected with `ERR_INVALID_STATE` if the lease is no longer in `DRAFT`. Upon submission, the acting operator's identifier is recorded as the lease's `abstractor_user_id`, and the lease's `version` increments.

A `Certifier` then reviews and certifies, moving `abstraction_status` from `ABSTRACTED` to `CERTIFIED`. Certification is segregation-controlled per §2.9: if the certifier's `X-User-ID` equals the recorded `abstractor_user_id`, the attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`. A successful certification records `certifier_user_id` and increments the lease's `version`.

If a certified abstraction turns out to be wrong while the lease is still in `DRAFT`, a `PortfolioManager` may reopen it, returning `abstraction_status` from `CERTIFIED` to `PENDING` and clearing both `abstractor_user_id` and `certifier_user_id` to null. Reopening is one of the two OCC-guarded writes in the system: the request must carry `expected_lease_version` matching the lease's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), since an intervening amendment approval may have advanced the lease past the state the reopener observed. Reopening after activation is not possible — the lease must already be in `DRAFT`, and a request against any other status is rejected with `ERR_INVALID_STATE`; once a lease is live, corrections travel through the amendment process instead. A successful reopen increments the lease's `version`.

### 3.3. Rent Schedules, Escalation Steps, and Activation Gates

The rent schedule is the financial spine of the lease. A `PortfolioManager` adds a RentScheduleLine to a lease with a `period_start` (inclusive), a `period_end` (exclusive, so each line is the half-open interval from start to end), a `base_rent_cents` for the period (zero or greater, pre-escalation), and an optional `escalation_step_id` that is null when no escalation applies. Two guards protect the schedule's integrity. First, temporal well-formedness: the period start must precede the period end, else `ERR_INVALID_DATE_RANGE`. Second, exclusivity: a new line must not overlap any existing line on the same lease under the half-open overlap test — the new line's start falling before an existing line's end while the new line's end falls after that existing line's start constitutes overlap and is rejected with `ERR_SCHEDULE_OVERLAP` (HTTP 409). RentScheduleLine rows are immutable after creation and carry no state machine.

EscalationSteps are created on the lease with a 1-based `step_index` that is unique within the lease, a `kind` of `FIXED_PCT`, `CPI_LOOKUP`, or `STEPPED_AMOUNT`, an `effective_on` date, and exactly one accompanying magnitude: `pct_bps` (from 0 to 100000) is required if and only if the kind is `FIXED_PCT` or `CPI_LOOKUP`, while `amount_cents` (zero or greater) is required if and only if the kind is `STEPPED_AMOUNT`. Referential integrity binds the two entities: the `escalation_step_id` on a schedule line must reference an existing EscalationStep belonging to the same lease, else creation is rejected with `ERR_REFERENTIAL_INTEGRITY`. When an EscalationStep is created after lines already reference it — rare, since steps are typically defined first — each referencing line is recomputed.

Each line's `effective_rent_cents` is computed in a pinned evaluation order. The base is the line's own `base_rent_cents`; if no escalation step is attached, the effective rent equals the base and computation stops. For a `FIXED_PCT` step, the effective rent is the base multiplied by the sum of 10000 and the step's `pct_bps`, divided by 10000, rounded half-up to whole cents. For a `CPI_LOOKUP` step, the same percentage formula applies but with the index value supplied by a deterministic lookup table pinned at 250 basis points for any date. For a `STEPPED_AMOUNT` step, the effective rent is the base plus the step's `amount_cents`. Per §2.6, every line is rounded individually; the lease's `cached_annual_rent_cents` is then the sum of `effective_rent_cents` over all lines overlapping the current logical fiscal year — a line overlaps when its `period_start` falls before the fiscal year's end and its `period_end` falls after the fiscal year's start — with no pro-ration: a line that overlaps the fiscal year at all contributes its full amount. This cache is refreshed on line creation or deletion, on lease activation, and when a rent-change amendment is applied.

Activation is the moment a drafted lease goes live, performed by a `PortfolioManager` and guarded by three fiscal and data-quality gates evaluated after the basic state check. First, the abstraction dimension must be `CERTIFIED`, else `ERR_ABSTRACTION_NOT_CERTIFIED`. Second, the rent schedule must cover the full span from `commencement_date` to `expiration_date` with no gap, else `ERR_SCHEDULE_GAP`. Third, billing must be initialized: at least one RecoveryBilling for the current fiscal year must already exist in `DRAFT` or `ISSUED` status, else `ERR_BILLING_NOT_INITIALIZED`. A successful activation moves `status` from `DRAFT` to `ACTIVE`, recomputes `cached_annual_rent_cents` from the schedule, recomputes the owning property's `posture`, and increments the lease's `version`.

### 3.4. Termination, Expiration, and the End of the Lease

A lease ends one of two ways. Natural expiration is system-driven: when the logical clock reaches or passes the lease's `expiration_date`, an `ACTIVE` lease transitions to `EXPIRED` without any client request. The expiration cascade resolves the lease's open obligations in the same instant: every `PENDING` CriticalDate whose `due_date` has been reached or passed transitions to `LAPSED`; every Reconciliation still `OPEN` or `POSTED` auto-closes to `CLOSED`; and every ComplianceDoc still `SUBMITTED` or `UNDER_REVIEW` transitions to `EXPIRED`.

Early termination is a deliberate act by a `PortfolioManager`, gated by two fiscal checks. Termination is rejected with `ERR_OUTSTANDING_BILLING` if any RecoveryBilling of the lease is in `ISSUED` status with an unpaid amount greater than zero, and with `ERR_OPEN_RECONCILIATION` if any Reconciliation is `OPEN` or `CHALLENGED`. A successful termination moves `status` from `ACTIVE` to `TERMINATED`, transitions all `PENDING` CriticalDate rows to `WAIVED`, voids all `DRAFT` RecoveryBilling rows, recomputes the property's `posture`, and increments the lease's `version`. Both `EXPIRED` and `TERMINATED` are terminal.

### 3.5. Recovery Pools and Estimate Billing

Recovery billing starts at the property level, where a `LeaseAccountant` creates a RecoveryPool for a `category` — one of `CAM`, `TAX`, `INSURANCE`, `UTILITIES`, or `MANAGEMENT_FEE` — and a `fiscal_year` (from 2000 to 2100), with the `budgeted_cents` for that pool-year. Each pool also carries a `gross_up_floor_pct_bps`, an occupancy threshold in basis points from 0 to 10000 that defaults to 9500 when not supplied; its meaning is defined in §3.6. The pool's `actual_cents` (zero or greater) stays null until year-end close, when a `LeaseAccountant` records actuals against the pool, which makes the pool eligible for reconciliation posting. The pool collection is filterable by `property_id`, `fiscal_year`, or `category`.

Against these pools, a `LeaseAccountant` creates RecoveryBilling rows for a lease, one per pool and period, supplying the `pool_id`, the `fiscal_year`, and the `period_index` — 1 through 12 for monthly billing. On creation the system computes the `estimate_cents` for the row and the billing begins in `DRAFT`. The estimate projects the full-year budget into the period: the pool's `budgeted_cents` is multiplied by the lease's `pro_rata_share_bps`, divided by 10000, divided by the twelve billing periods of the year, and rounded half-up to whole cents. Which pools are recoverable at all depends on the lease's `recovery_structure`: under `NNN` all five categories are recoverable; under `MODIFIED_GROSS` only `CAM` and `TAX`; under `GROSS` no recoveries are billed at all. Creating a RecoveryBilling against a pool whose category is not recoverable under the lease's `recovery_structure` is rejected with `ERR_REFERENTIAL_INTEGRITY`. Each RecoveryBilling row stores the per-pool estimate. The billing collection is filterable by `lease_id`, `pool_id`, `fiscal_year`, or `status`.

Issuing is the act that makes a draft bill collectible: a `LeaseAccountant` issues a `DRAFT` billing, which requires the lease's `status` to be `ACTIVE` (else `ERR_LEASE_NOT_ACTIVE`) and computes the estimate from the pool's current `budgeted_cents`. Issuing stamps `issued_at` with the current logical UTC time, adds the `estimate_cents` to the lease's `cached_recovery_ytd_cents`, recomputes the lease's `billing_posture`, and moves the billing to `ISSUED`. From `ISSUED`, a billing is either marked `PAID` by a `LeaseAccountant` — which recomputes `billing_posture` and may clear a `DELINQUENT` condition — or voided. Voiding is available from `DRAFT` without conditions and from `ISSUED` only while the billing remains unpaid; voiding an issued billing subtracts its `estimate_cents` from the lease's `cached_recovery_ytd_cents` and recomputes `billing_posture`. `PAID` and `VOID` are terminal. A billing also leaves `ISSUED` for `DISPUTED` when a tenant challenge specifically links it, as described in §3.9, and returns from `DISPUTED` to `ISSUED` when that challenge is withdrawn or resolved.

### 3.6. Year-End Reconciliation and True-Up

At fiscal year-end, a `LeaseAccountant` opens a Reconciliation for a lease and `fiscal_year`; it begins in `OPEN`. Posting is the computational heart of the system. A `LeaseAccountant` may post the reconciliation only when every RecoveryPool on the lease's property for that fiscal year has its `actual_cents` populated, else the post is rejected with `ERR_POOL_NOT_CLOSED`. Posting computes the `final_cents` of every RecoveryBilling for the lease and fiscal year through the following steps.

First, the property's occupancy rate for the fiscal year is computed exactly as in §3.1, yielding `occupancy_rate_bps`. Second, the gross-up rule is evaluated per pool: if the occupancy rate is below the pool's `gross_up_floor_pct_bps` and the pool's category is one of the variable categories `CAM` or `UTILITIES`, the pool's actual is scaled up — the `actual_cents` multiplied by the floor in basis points and divided by the observed occupancy rate in basis points, rounded half-up to whole cents — and the gross-up is recorded as having fired for that pool; in all other cases the pool's unadjusted `actual_cents` is used. Because scaling by the ratio of floor to observed occupancy raises the recoverable base, gross-up yields a higher tenant charge precisely when occupancy is low. Third, each pool's final yearly share for the lease is its (possibly grossed-up) actual multiplied by the lease's `pro_rata_share_bps` and divided by 10000, rounded half-up to whole cents. Fourth, that yearly share is allocated across the pool's billing rows as a waterfall keyed on each row's `period_index`: rows with `period_index` one through eleven each receive the yearly share divided by twelve and rounded half-up, and the row with `period_index` twelve receives the remainder — the yearly share minus eleven times the rounded monthly amount — so when all twelve monthly rows are present the rows sum to the yearly share exactly, the twelfth period absorbing all rounding residue. Fifth, the reconciliation's `true_up_cents` is the signed delta of the sum of all `final_cents` minus the sum of all `estimate_cents` across the year's billing rows; a negative value is a credit owed back to the tenant. The reconciliation's `gross_up_applied` flag records whether any pool's gross-up rule fired. Posting also records the acting operator as `posted_by_user_id`, moves the reconciliation to `POSTED`, and — when the true-up is positive, meaning the tenant underpaid — generates one additional RecoveryBilling for the delta in `DRAFT` status with `period_index` 13, the true-up period. Until a reconciliation is posted, every billing's `final_cents` remains null.

Approval is segregation-controlled: a `PortfolioManager` approves a `POSTED` reconciliation, but only if the approver's `X-User-ID` differs from `posted_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; approval records `approved_by_user_id` and moves the reconciliation to `APPROVED`. Closing an `APPROVED` reconciliation requires that no TenantChallenge referencing it is in `OPEN`, `UNDER_REVIEW`, or `ESCALATED` status, else `ERR_OPEN_CHALLENGE`. When a reconciliation reaches `CLOSED`, audit windows open: any AuditRight invoked against it computes its `window_close_date` from the close. A reconciliation that has been `APPROVED` may also be knocked back to `CHALLENGED` by a freshly opened tenant challenge, and a `CHALLENGED` reconciliation can be closed once every linked challenge has reached `RESOLVED_ACCEPTED`, `RESOLVED_REJECTED`, or `WITHDRAWN`. `CLOSED` is terminal. The reconciliation collection is filterable by `lease_id`, `fiscal_year`, or `status`.

### 3.7. Critical Dates and Tenant Compliance

A `PropertyManager` maintains the lease's critical date calendar by creating CriticalDate rows with a `kind` — one of `OPTION_EXERCISE`, `NOTICE_DEADLINE`, `EXPIRATION`, `RENEWAL_WINDOW_OPEN`, `RENEWAL_WINDOW_CLOSE`, or `AUDIT_WINDOW_CLOSE` — a `due_date` that must not be in the past at creation, an `advance_notice_days` count (zero or greater), and an optional `linked_amendment_id` that stays null until the date is exercised. New dates begin `PENDING`. The calendar collection is filterable by `lease_id`, `linked_amendment_id`, `kind`, or `status`.

Notification marks that the tenant or landlord has been reminded ahead of the deadline: a `PropertyManager` notifies a `PENDING` date, moving it to `NOTIFIED`, only inside the notification window — the current logical date must be at least `advance_notice_days` before the `due_date`, else `ERR_NOTIFICATION_NOT_YET_DUE`, and must still be earlier than the `due_date` itself, else `ERR_NOTIFICATION_WINDOW_MISSED`. Exercising is the substantive act and is available from either `PENDING` or `NOTIFIED`: only dates of kind `OPTION_EXERCISE`, `RENEWAL_WINDOW_OPEN`, or `RENEWAL_WINDOW_CLOSE` are exercisable at all (else `ERR_NOT_EXERCISABLE`); the request must carry a `linked_amendment_id` referencing an Amendment that has already reached `APPLIED` (else `ERR_AMENDMENT_NOT_APPLIED`); and the current logical date must not have passed the `due_date` (else `ERR_DATE_PASSED`). A successful exercise persists the `linked_amendment_id` and moves the date to `EXERCISED`. Dates that pass unexercised lapse: when the logical clock moves beyond a `PENDING` or `NOTIFIED` date's `due_date`, the system transitions it to `LAPSED`, and a `PropertyManager` may also lapse such a date manually once its due date has passed. A `PortfolioManager` may instead waive a `PENDING` or `NOTIFIED` date, moving it to `WAIVED`. `EXERCISED`, `LAPSED`, and `WAIVED` are terminal.

Tenant compliance paperwork runs on a parallel track. A `PropertyManager` submits a ComplianceDoc with a `kind` of `INSURANCE_CERT`, `ESTOPPEL`, `FINANCIAL_STMT`, or `SNDA`, and a coverage window from `period_start` (inclusive) to `period_end` (exclusive); the document begins `SUBMITTED` and moves to `UNDER_REVIEW` when a `PropertyManager` starts the review. Acceptance is guarded by a coverage exclusivity rule: no other `ACCEPTED` document of the same kind on the same lease may have an overlapping coverage window, else `ERR_COVERAGE_OVERLAP`; accepting an insurance certificate whose period covers the current date leaves the lease's lifecycle untouched, as does any other acceptance. Rejection requires a non-empty `rejection_reason` in the request, else `ERR_REJECTION_REASON_REQUIRED` (HTTP 400), and moves the document to `REJECTED`. Time also acts on documents: when the logical clock reaches or passes a document's `period_end`, a `SUBMITTED` or `ACCEPTED` document transitions to `EXPIRED`; an expiring insurance certificate may leave the lease uncovered, so the lease's `billing_posture` is recomputed at that point. `ACCEPTED`, `REJECTED`, and `EXPIRED` are terminal. The compliance collection is filterable by `lease_id`, `kind`, or `status`.

### 3.8. Amendments and Assignment Processing

Once a lease is `ACTIVE`, changes to its terms travel through amendments. A `PortfolioManager` proposes an Amendment with a `kind` of `EXTENSION`, `CONTRACTION`, `EXPANSION`, `ASSIGNMENT`, `RENT_CHANGE`, or `USE_CHANGE`, plus an `effective_date` that must not precede the lease's `commencement_date`. Each kind carries its own payload requirement: `new_expiration_date` is required if and only if the kind is `EXTENSION`; `new_leased_sf` (at least 1) is required if and only if the kind is `EXPANSION` or `CONTRACTION`; `new_base_rent_annual_cents` (zero or greater) is required if and only if the kind is `RENT_CHANGE`; and `new_tenant_legal_name` is required if and only if the kind is `ASSIGNMENT`. A proposed amendment begins `PROPOSED`, and the amendment collection is filterable by `lease_id`, `kind`, or `status`.

Approval is the second OCC-guarded write in the system: approving requires the lease to be `ACTIVE` (else `ERR_LEASE_NOT_ACTIVE`) and requires the request's `expected_lease_version` to match the lease's current `version`, else `ERR_STALE_VERSION` (HTTP 412). A successful approval moves the amendment from `PROPOSED` to `APPROVED` and increments the lease's `version` — which is precisely the advancement that invalidates any other client's stale view of the same lease.

Application is where terms take effect, and each kind is validated in its own direction. An `EXTENSION` must set a `new_expiration_date` strictly later than the lease's current `expiration_date`, else `ERR_EXTENSION_MUST_EXTEND`. An `EXPANSION` must set a `new_leased_sf` greater than the current `leased_sf`, else `ERR_EXPANSION_MUST_EXPAND`, and must not overcommit the property: the new square footage plus the sum of `leased_sf` over all other `ACTIVE` leases on the same property must not exceed the property's `total_rentable_sf`, else `ERR_PROPERTY_OVERCOMMITTED`. A `CONTRACTION` must set a `new_leased_sf` smaller than the current `leased_sf`, else `ERR_CONTRACTION_MUST_CONTRACT`. On a successful apply, the lease's fields are rewritten per kind — `expiration_date` for an extension, `leased_sf` for an expansion or contraction, `base_rent_annual_cents` for a rent change, `tenant_legal_name` for an assignment — and the lease's `version` increments again. Two cascades fire from application. An applied `EXTENSION` transitions any `PENDING` CriticalDate of kind `EXPIRATION` whose `due_date` equals the old expiration date to `WAIVED` and creates a fresh `EXPIRATION` CriticalDate at the new expiration date. An applied `RENT_CHANGE` recomputes every RentScheduleLine whose `period_start` falls on or after the amendment's `effective_date` using the new annual base rent, which cascades into escalation recomputation per line, and refreshes the lease's `cached_annual_rent_cents`. Either a `PROPOSED` or an `APPROVED` amendment may instead be rejected by a `PortfolioManager`, moving it to `REJECTED`; `APPLIED` and `REJECTED` are terminal, so an amendment that has already been applied can no longer be rejected.

### 3.9. Challenges, Audit Rights, and Portfolio Reporting

When a tenant disputes a reconciliation, a `PropertyManager` opens a TenantChallenge on the lease, supplying the `reconciliation_id` being challenged, an optional `recovery_billing_id` to narrow the dispute to one line (null challenges the whole reconciliation), a `reason_code` of `GROSS_UP_DISPUTE`, `PRO_RATA_DISPUTE`, `AUDIT_FINDING`, `MATH_ERROR`, or `POOL_MISCLASS`, and the `claimed_overbilling_cents` (strictly greater than zero). A referenced `recovery_billing_id` must resolve to a billing in `ISSUED` status, else `ERR_REFERENTIAL_INTEGRITY`. A new challenge begins `OPEN` with `round_index` at 0, and its arrival reconfigures the neighborhood: the linked reconciliation moves from `APPROVED` to `CHALLENGED`, a specifically linked billing moves from `ISSUED` to `DISPUTED`, the lease's `billing_posture` is recomputed — typically transitioning to `FROZEN` — and the property's `posture` recomputes in turn.

Negotiation proceeds in bounded rounds. A `LeaseAccountant` starts review, moving the challenge from `OPEN` to `UNDER_REVIEW`. If review stalls, the accountant may reopen the challenge back to `OPEN`, which increments `round_index` by one; reopening is allowed only while `round_index` is below 3, else `ERR_MAX_ROUNDS_REACHED`, so a challenge may cycle through at most three negotiation rounds. Resolution is a `PortfolioManager` act carrying an `outcome` and a `resolution_delta_cents`, with sign rules enforced symmetrically: an accepted outcome requires a delta of zero or less — an accepted challenge means money back to the tenant, so a positive delta is rejected with `ERR_INVALID_RESOLUTION_SIGN` — while a rejected outcome requires a delta of exactly zero, any other value drawing the same error. When the challenge is linked to a reconciliation, the magnitude of the delta may not exceed the magnitude of that reconciliation's `true_up_cents`, else `ERR_RESOLUTION_EXCEEDS_TRUE_UP`. An accepted resolution adjusts the reconciliation's `true_up_cents` by the delta, adjusts the lease's `cached_recovery_ytd_cents` accordingly, moves the challenge to `RESOLVED_ACCEPTED`, and returns any linked `DISPUTED` billing to `ISSUED`; a rejected resolution performs no adjustment, moves the challenge to `RESOLVED_REJECTED`, and likewise releases any disputed billing back to `ISSUED`.

Escalation invokes the audit track. A `PropertyManager` escalates an `UNDER_REVIEW` challenge to `ESCALATED`, which starts a 30-day deadline: an AuditRight must be invoked against the same reconciliation within 30 days of escalation, or the challenge automatically reverts to `UNDER_REVIEW`. A `PropertyManager` invokes an AuditRight against a closed reconciliation by supplying the `reconciliation_id` and the `invoked_on` date; the right begins `INVOKED`, and its `window_close_date` is computed as the date the reconciliation reached `CLOSED` plus 365 days — a fixed calendar rule with no rolling forward when the landing date falls on a weekend, and a strict boundary in which action attempted on the window-close date itself is already too late. From `INVOKED`, a `PropertyManager` starts fieldwork, moving the right to `FIELDWORK`, only while the current logical date is strictly before `window_close_date`, else `ERR_AUDIT_WINDOW_CLOSED`; issuing findings from `FIELDWORK` carries the same window guard and requires a `findings_delta_cents` in the payload, which is persisted as the signed amount the auditor found owing — negative meaning a credit to the tenant — moving the right to `FINDINGS_ISSUED`.

Settlement closes the loop: a `PortfolioManager` settles a right whose findings are issued, moving it to `SETTLED`. Settlement cascades across every `ESCALATED` TenantChallenge linked to the same reconciliation — each resolves to `RESOLVED_ACCEPTED` when the `findings_delta_cents` is negative (the audit found in the tenant's favor, and the challenge's `resolution_delta_cents` takes on the findings value) or to `RESOLVED_REJECTED` when the findings are zero or positive — while the reconciliation's `true_up_cents` and the lease's `cached_recovery_ytd_cents` are adjusted by the findings delta. If the logical clock reaches the `window_close_date` while the right is still `INVOKED` or in `FIELDWORK`, the right transitions to `TIME_BARRED` and every `ESCALATED` challenge on the same reconciliation reverts to `UNDER_REVIEW`, the audit window having been missed. `SETTLED` and `TIME_BARRED` are terminal. Finally, a challenge still `OPEN` may be withdrawn by a `PropertyManager`, moving it to `WITHDRAWN`; withdrawal releases a linked `DISPUTED` billing back to `ISSUED` and, if the linked reconciliation was `CHALLENGED` and no other open challenges remain, returns the reconciliation to `APPROVED`. Both the challenge collection and the audit-right collection are filterable by their foreign keys — `lease_id`, `reconciliation_id`, and for challenges also `recovery_billing_id` — plus `status`.

Reporting closes the loop on the portfolio. A rent-roll report for a lease and `fiscal_year` returns the `fiscal_year`, the `basis` used, the `total_rent_cents`, and the lease's `recovery_ytd_cents`. The default `cash` basis reports the lease's `cached_annual_rent_cents` — the sum of scheduled, per-line-rounded `effective_rent_cents` overlapping the fiscal year as defined in §3.3. The `straight_line` basis instead smooths rent evenly across the entire lease term per GAAP: the total term rent is the sum of `effective_rent_cents` over all schedule lines, the term length is the total number of days across all lines, and the fiscal-year allocation is the total term rent multiplied by the number of in-term days falling inside the fiscal-year window and divided by the total term days, with the intermediate division kept as an exact rational and only the final figure rounded half-up to whole cents. The two bases diverge whenever escalations are non-flat, because straight-lining spreads each escalation across the whole term.

## 4. Endpoint Definitions

All endpoints are mounted under the `/lease-admin` prefix. Operations that create a new resource — a Property, Lease, schedule line, escalation step, recovery pool, billing, reconciliation, critical date, compliance document, amendment, challenge, or audit right — return a `201 Created` status code. Operations that modify an existing resource or drive a state transition return `200 OK`. The table below is a navigational summary only; the complete request and response contract for each endpoint is defined by the workflows in §3 and the global rules in §2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/lease-admin/_clock/set_current_utc` | Set the server's logical UTC clock | PlatformAdmin |
| POST | `/lease-admin/properties` | Create a Property | PlatformAdmin |
| GET | `/lease-admin/properties/{property_id}` | Get one Property | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant, Abstractor, Certifier |
| GET | `/lease-admin/properties` | List Properties (paginated) | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant, Abstractor, Certifier |
| GET | `/lease-admin/properties/{property_id}/occupancy-report` | Computed occupancy for a fiscal year | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant |
| POST | `/lease-admin/properties/{property_id}/leases` | Create a Lease (starts DRAFT / PENDING abstraction) | PortfolioManager |
| GET | `/lease-admin/leases/{lease_id}` | Get one Lease | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant, Abstractor, Certifier |
| GET | `/lease-admin/leases` | List Leases (paginated, filterable) | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant, Abstractor, Certifier |
| GET | `/lease-admin/properties/{property_id}/leases` | List Leases of a Property | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant, Abstractor, Certifier |
| POST | `/lease-admin/leases/{lease_id}/abstract` | Submit abstraction (PENDING → ABSTRACTED) | Abstractor |
| POST | `/lease-admin/leases/{lease_id}/certify` | Certify abstraction (ABSTRACTED → CERTIFIED) | Certifier |
| POST | `/lease-admin/leases/{lease_id}/reopen-abstraction` | Reopen certified abstraction (OCC-guarded) | PortfolioManager |
| POST | `/lease-admin/leases/{lease_id}/activate` | Activate a DRAFT Lease | PortfolioManager |
| POST | `/lease-admin/leases/{lease_id}/terminate` | Terminate an ACTIVE Lease early | PortfolioManager |
| GET | `/lease-admin/leases/{lease_id}/rent-roll` | Computed rent roll for a fiscal year; cash or straight-line basis | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant |
| POST | `/lease-admin/leases/{lease_id}/rent-schedule-lines` | Create a RentScheduleLine on a Lease | PortfolioManager |
| GET | `/lease-admin/leases/{lease_id}/rent-schedule-lines` | List schedule lines for a Lease | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant, Abstractor, Certifier |
| GET | `/lease-admin/rent-schedule-lines/{line_id}` | Get one RentScheduleLine | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant, Abstractor, Certifier |
| POST | `/lease-admin/leases/{lease_id}/escalation-steps` | Create an EscalationStep | PortfolioManager |
| GET | `/lease-admin/leases/{lease_id}/escalation-steps` | List escalation steps for a Lease | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant, Abstractor, Certifier |
| GET | `/lease-admin/escalation-steps/{step_id}` | Get one EscalationStep | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant, Abstractor, Certifier |
| POST | `/lease-admin/properties/{property_id}/recovery-pools` | Create a RecoveryPool (budget) | LeaseAccountant |
| PUT | `/lease-admin/recovery-pools/{pool_id}/actuals` | Record actuals at year-end close | LeaseAccountant |
| GET | `/lease-admin/properties/{property_id}/recovery-pools` | List RecoveryPools for a Property | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant |
| GET | `/lease-admin/recovery-pools/{pool_id}` | Get one RecoveryPool | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant |
| POST | `/lease-admin/leases/{lease_id}/recovery-billings` | Create a RecoveryBilling (computes estimate) | LeaseAccountant |
| GET | `/lease-admin/leases/{lease_id}/recovery-billings` | List RecoveryBillings for a Lease | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant |
| GET | `/lease-admin/recovery-billings/{billing_id}` | Get one RecoveryBilling | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant |
| POST | `/lease-admin/recovery-billings/{billing_id}/issue` | Issue a DRAFT billing | LeaseAccountant |
| POST | `/lease-admin/recovery-billings/{billing_id}/mark-paid` | Mark an ISSUED billing as PAID | LeaseAccountant |
| POST | `/lease-admin/recovery-billings/{billing_id}/void` | Void a DRAFT or ISSUED billing | LeaseAccountant |
| POST | `/lease-admin/leases/{lease_id}/reconciliations` | Open a Reconciliation for a fiscal year | LeaseAccountant |
| GET | `/lease-admin/leases/{lease_id}/reconciliations` | List Reconciliations for a Lease | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant |
| GET | `/lease-admin/reconciliations/{recon_id}` | Get one Reconciliation | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant |
| POST | `/lease-admin/reconciliations/{recon_id}/post` | Post a Reconciliation (compute final amounts) | LeaseAccountant |
| POST | `/lease-admin/reconciliations/{recon_id}/approve` | Approve a posted reconciliation | PortfolioManager |
| POST | `/lease-admin/reconciliations/{recon_id}/close` | Close an APPROVED or CHALLENGED reconciliation | PortfolioManager |
| POST | `/lease-admin/leases/{lease_id}/critical-dates` | Create a CriticalDate | PropertyManager |
| GET | `/lease-admin/leases/{lease_id}/critical-dates` | List CriticalDates for a Lease | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant, Abstractor, Certifier |
| GET | `/lease-admin/critical-dates/{cd_id}` | Get one CriticalDate | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant, Abstractor, Certifier |
| POST | `/lease-admin/critical-dates/{cd_id}/notify` | Mark notification sent | PropertyManager |
| POST | `/lease-admin/critical-dates/{cd_id}/exercise` | Exercise an option/renewal date | PropertyManager |
| POST | `/lease-admin/critical-dates/{cd_id}/lapse` | Manually lapse a date past its due | PropertyManager |
| POST | `/lease-admin/critical-dates/{cd_id}/waive` | Waive a PENDING/NOTIFIED date | PortfolioManager |
| POST | `/lease-admin/leases/{lease_id}/compliance-docs` | Submit a ComplianceDoc | PropertyManager |
| GET | `/lease-admin/leases/{lease_id}/compliance-docs` | List ComplianceDocs for a Lease | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant, Abstractor, Certifier |
| GET | `/lease-admin/compliance-docs/{doc_id}` | Get one ComplianceDoc | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant, Abstractor, Certifier |
| POST | `/lease-admin/compliance-docs/{doc_id}/start-review` | Move SUBMITTED → UNDER_REVIEW | PropertyManager |
| POST | `/lease-admin/compliance-docs/{doc_id}/accept` | Accept a ComplianceDoc (overlap check applies) | PropertyManager |
| POST | `/lease-admin/compliance-docs/{doc_id}/reject` | Reject a ComplianceDoc | PropertyManager |
| POST | `/lease-admin/leases/{lease_id}/amendments` | Propose an Amendment | PortfolioManager |
| GET | `/lease-admin/leases/{lease_id}/amendments` | List Amendments for a Lease | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant |
| GET | `/lease-admin/amendments/{amendment_id}` | Get one Amendment | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant |
| POST | `/lease-admin/amendments/{amendment_id}/approve` | Approve an Amendment (OCC-guarded) | PortfolioManager |
| POST | `/lease-admin/amendments/{amendment_id}/apply` | Apply an APPROVED Amendment | PortfolioManager |
| POST | `/lease-admin/amendments/{amendment_id}/reject` | Reject a PROPOSED or APPROVED Amendment | PortfolioManager |
| POST | `/lease-admin/leases/{lease_id}/tenant-challenges` | Open a TenantChallenge against a Reconciliation | PropertyManager |
| GET | `/lease-admin/leases/{lease_id}/tenant-challenges` | List TenantChallenges for a Lease | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant |
| GET | `/lease-admin/tenant-challenges/{challenge_id}` | Get one TenantChallenge | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant |
| POST | `/lease-admin/tenant-challenges/{challenge_id}/start-review` | OPEN → UNDER_REVIEW | LeaseAccountant |
| POST | `/lease-admin/tenant-challenges/{challenge_id}/reopen` | UNDER_REVIEW → OPEN (negotiation round) | LeaseAccountant |
| POST | `/lease-admin/tenant-challenges/{challenge_id}/resolve` | Resolve a challenge (accept or reject) | PortfolioManager |
| POST | `/lease-admin/tenant-challenges/{challenge_id}/escalate` | UNDER_REVIEW → ESCALATED | PropertyManager |
| POST | `/lease-admin/tenant-challenges/{challenge_id}/withdraw` | OPEN → WITHDRAWN | PropertyManager |
| POST | `/lease-admin/leases/{lease_id}/audit-rights` | Invoke an AuditRight against a closed Reconciliation | PropertyManager |
| GET | `/lease-admin/leases/{lease_id}/audit-rights` | List AuditRights for a Lease | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant |
| GET | `/lease-admin/audit-rights/{audit_id}` | Get one AuditRight | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant |
| POST | `/lease-admin/audit-rights/{audit_id}/start-fieldwork` | INVOKED → FIELDWORK | PropertyManager |
| POST | `/lease-admin/audit-rights/{audit_id}/issue-findings` | FIELDWORK → FINDINGS_ISSUED | PropertyManager |
| POST | `/lease-admin/audit-rights/{audit_id}/settle` | FINDINGS_ISSUED → SETTLED; cascades to escalated challenges | PortfolioManager |
| GET | `/lease-admin/rent-schedule-lines` | Filtered list of RentScheduleLines | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant, Abstractor, Certifier |
| GET | `/lease-admin/escalation-steps` | Filtered list of EscalationSteps | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant, Abstractor, Certifier |
| GET | `/lease-admin/recovery-pools` | Filtered list of RecoveryPools | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant |
| GET | `/lease-admin/recovery-billings` | Filtered list of RecoveryBillings | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant |
| GET | `/lease-admin/reconciliations` | Filtered list of Reconciliations | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant |
| GET | `/lease-admin/critical-dates` | Filtered list of CriticalDates | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant, Abstractor, Certifier |
| GET | `/lease-admin/compliance-docs` | Filtered list of ComplianceDocs | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant, Abstractor, Certifier |
| GET | `/lease-admin/amendments` | Filtered list of Amendments | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant |
| GET | `/lease-admin/tenant-challenges` | Filtered list of TenantChallenges | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant |
| GET | `/lease-admin/audit-rights` | Filtered list of AuditRights | PlatformAdmin, PortfolioManager, PropertyManager, LeaseAccountant |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_DATE_RANGE` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_REFERENTIAL_INTEGRITY` | 422 |
| `ERR_SCHEDULE_OVERLAP` | 409 |
| `ERR_SCHEDULE_GAP` | 409 |
| `ERR_COVERAGE_OVERLAP` | 409 |
| `ERR_PROPERTY_OVERCOMMITTED` | 409 |
| `ERR_ABSTRACTION_NOT_CERTIFIED` | 409 |
| `ERR_BILLING_NOT_INITIALIZED` | 409 |
| `ERR_OUTSTANDING_BILLING` | 409 |
| `ERR_OPEN_RECONCILIATION` | 409 |
| `ERR_OPEN_CHALLENGE` | 409 |
| `ERR_POOL_NOT_CLOSED` | 409 |
| `ERR_LEASE_NOT_ACTIVE` | 409 |
| `ERR_NOTIFICATION_NOT_YET_DUE` | 409 |
| `ERR_NOTIFICATION_WINDOW_MISSED` | 409 |
| `ERR_DATE_PASSED` | 409 |
| `ERR_NOT_EXERCISABLE` | 409 |
| `ERR_AMENDMENT_NOT_APPLIED` | 409 |
| `ERR_EXTENSION_MUST_EXTEND` | 409 |
| `ERR_EXPANSION_MUST_EXPAND` | 409 |
| `ERR_CONTRACTION_MUST_CONTRACT` | 409 |
| `ERR_AUDIT_WINDOW_CLOSED` | 409 |
| `ERR_MAX_ROUNDS_REACHED` | 409 |
| `ERR_INVALID_RESOLUTION_SIGN` | 409 |
| `ERR_RESOLUTION_EXCEEDS_TRUE_UP` | 409 |
| `ERR_REJECTION_REASON_REQUIRED` | 400 |
