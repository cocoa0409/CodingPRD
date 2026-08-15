# Rural Electric Cooperative Member Services API — Product Requirements Document

## 1. Introduction

Rural electric cooperatives occupy an unusual position in the utility world: they are owned by the very members they serve, and every dollar of operating margin ultimately belongs to those members as patronage capital. Managing that relationship at scale — across membership onboarding, rate design, seasonal and irrigation load, outage response, easement acquisition, load-management incentives, capital-credit allocation and retirement, and democratic board governance — has historically lived in filing cabinets, spreadsheets, and institutional memory. This document specifies an API that brings the full member-services operation of a Touchstone Energy–style distribution cooperative into a single, consistent, auditable system.

The requirements that follow are written for the engineering team building the service. They cover the cooperative's fiscal machinery (the patronage pool, kWh-weighted and flat allocation methods, FIFO and pro-rata retirement runs, and the escheatment of unclaimed checks), the operational machinery (service orders and aid-to-construction pricing, right-of-way consent and condemnation, meter reading and dual-variant invoicing, outage folding and member notification), and the democratic machinery (districted board elections with quorum certification). Two concerns cut across everything: money is always accounted in integer cents with explicit rounding rules, and the cooperative's fiscal record is guarded by optimistic concurrency and segregation-of-duties controls so that no single operator can both propose and approve a movement of member capital.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resources are mounted under the `/coop` prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request whose `X-User-Role` header is missing or does not name a declared role is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, the role is checked against the permission matrix in §4; an actor whose role is not authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes ten roles. `PlatformAdmin` is the bootstrap operator responsible for cooperative configuration and the test clock. `MemberServicesRep` is front-office staff handling membership, capital credits, service orders, and aid-to-construction invoicing. `BoardDirector` is an elected director who approves allocations and retirements. `BoardSecretary` is the corporate secretary administering elections and the annual meeting. `RateAnalyst` owns rate schedule design. `BillingClerk` runs metering, invoicing, payments, and write-offs. `FieldOpsCoordinator` directs field work — energizing and disconnecting locations, construction, devices, right-of-way recording, and outage restoration. `Dispatcher` handles the outage desk: acknowledgement, crew dispatch, duplicate folding, and cancellation. `LegalCounsel` acts on easement condemnation. `Member` is a cooperative member acting on their own account.

For nine of these roles — `PlatformAdmin`, `MemberServicesRep`, `BoardDirector`, `BoardSecretary`, `RateAnalyst`, `BillingClerk`, `FieldOpsCoordinator`, `Dispatcher`, and `LegalCounsel` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `reported_by_member_id` on an `OutageReport` where a staff member files on a member's behalf, or as the proposing or approving actor on a segregation-of-duties workflow) but does not compare it to any entity's `id`.

When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` compare the resource's foreign-key field to `X-User-ID`. For resources owned through a service location — such as a right-of-way agreement or a load-management device — the check compares the `id` of the `Member` who owns that location to `X-User-ID`. A member acting on a resource they do not own is rejected with `ERR_FORBIDDEN`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order.

The `meta` object of a list response always carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp records when the resource was first persisted, and `updated_at` records the most recent mutation; both are ISO 8601 UTC timestamps with three fractional digits. The `version` is an integer that starts low and increments on every mutation of the resource, including mutations driven by cascades or derived-field recomputation; any such mutation also refreshes `updated_at`.

Two resources are deliberately append-only and break this pattern. A `MeterReading` and a `Ballot` each carry only `id` and `created_at`; both `updated_at` and `version` are absent from these resources, because neither is ever mutated after creation.

### 2.5. The Cooperative Logical Clock

All time-sensitive business rules — election windows, write-off aging, payout claim deadlines, escheatment sweeps — are evaluated against a server-side logical clock, never against wall-clock time. Before any operator sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and the server must not fall back to wall-clock time under any circumstance.

A `PlatformAdmin` advances the clock through an admin-only test-driving capability that accepts a `to_iso8601` timestamp and returns the resulting `current_utc`. Advancing the clock is not a neutral read operation: the moment the clock moves, the escheatment sweep fires — every `CapitalCreditPayout` sitting in `UNCLAIMED` whose `claim_deadline` falls at or before the new clock value transitions to `ESCHEATED`. Payouts still in `ISSUED` are explicitly not auto-transitioned by clock advancement; they await either a cash event or an operator's mark-unclaimed action.

### 2.6. Monetary Precision and Rounding

All money in the system is accounted in integer cents. Fields such as `capital_credits_pool_cents`, `capital_credit_balance_cents`, `total_due_cents`, `aid_to_construction_cents`, and every other `*_cents` field are integers, never floats.

Rounding policy is pinned per calculation, and the order of rounding matters. The tiered energy charge rounds each tier line half-up to whole cents first and only then sums the lines — summing unrounded lines and rounding once at the end is a different (and non-compliant) algorithm. The aid-to-construction estimate rounds its final figure half-up to whole cents. Where shares or credits must be divided — capital-credit allocation shares, retirement payout amounts, prorated load-management credits — the system floors to integer cents and distributes or drops the remainder exactly as the relevant workflow in §3 specifies. Demand quantities are carried to a precision of 0.01 kW. Quorum arithmetic operates on integer member counts, with the quorum threshold itself rounded up to a whole member.

### 2.7. Optimistic Concurrency Control on the Cooperative

Three write operations touch the cooperative's fiscal or electoral posture and therefore require the caller to prove they are acting on a current view of the `Cooperative` resource. Each takes a non-optional request field `expected_cooperative_version` carrying the cooperative's `version` as the client last observed it. If that value does not match the cooperative's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

The protected operations are: posting an approved capital-credit allocation (`POST /coop/capital-credit-allocations/{id}/post`), executing a board-approved retirement run (`POST /coop/capital-credit-retirements/{id}/execute`), and opening voting on a board election (`POST /coop/board-elections/{id}/open-voting`). The first guards the case where another writer has already posted an allocation that zeroed the same fiscal-year pool; the second guards the case where another writer has just executed or configured something that legitimately changes the co-op's fiscal posture; the third guards the case where another writer has flipped the cooperative's `active_election_id` to a different election under the one-active-election rule. Endpoints not listed here do not take a version field.

### 2.8. Request Validation Order

When several checks could reject the same request, the server evaluates them in a fixed priority order so that the surfaced error is deterministic. Authentication comes first: a missing or undeclared `X-User-Role` yields `ERR_UNAUTHENTICATED`. Second, role authorization: an authenticated role not permitted for the endpoint yields `ERR_FORBIDDEN`. Third, path existence: every identifier in the URL must exist, validated left to right, with the first missing identifier producing `ERR_NOT_FOUND`. Fourth, entity-backed ownership: on member-scoped endpoints, a `Member` actor may act only on their own resources, else `ERR_FORBIDDEN`. Fifth, state validity: the target resource must be in a legitimate from-state for the requested transition, else `ERR_INVALID_STATE`. Sixth, segregation of duties on the allocation-approval and retirement-approval steps, else `ERR_SOD_VIOLATION`. Seventh, temporal-window checks — the election voting window, the 180-day write-off age, payout claim deadlines — evaluated against the logical clock. Eighth, structural business rules: rate-schedule overlap, ballot uniqueness, district and eligibility, device rate-class gating, right-of-way recording, and construction completion. Ninth and last, fiscal arithmetic: allocation-pool match, retirement-budget sufficiency, and cooperative-version freshness.

Independently of this ordering, a request body missing a required field or carrying a malformed value is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.9. Hierarchical Consistency and Cascading Effects

The resource graph runs from the cooperative down through members, service locations, and the operational records beneath them. When a parent undergoes a transition that changes what its children may do, the server propagates the effect itself rather than leaving children stranded: terminating a member disconnects energized locations and unenrolls load-management devices; energizing a location completes the service order that built it; restoring an outage restores every report folded into it as a duplicate. Conversely, derived values on parents — a member's patronage base, an outage's notified count, an election's quorum flag — are recomputed by the server as the underlying events land. Each such cascade or reconciliation mutates the affected resource, refreshing its `updated_at` and incrementing its `version` per §2.4. The server may perform these transitions without an explicit client request on the affected resource, whenever the governing criteria are satisfied.

### 2.10. Nested Resource Retrieval

Requests that address a resource nested beneath another validate path identifiers in strict left-to-right order. The first identifier that does not correspond to an existing resource determines the error: the server returns `ERR_NOT_FOUND` (HTTP 404) for that identifier without examining anything further along the path. Creation and listing operations under a parent observe the same discipline — the parent's existence is confirmed before any child-level rule is consulted, consistent with the priority order in §2.8.

## 3. Business Logic & Workflows

### 3.1. Membership: From Application to Termination

A membership begins when a `MemberServicesRep` creates a `Member` record with a `legal_name`, a `member_type` of `RESIDENTIAL`, `COMMERCIAL`, or `IRRIGATION`, and the `district_id` — an integer from 1 to 7 naming the board district of the member's primary service location, which later determines ballot eligibility per seat. A new member starts as an `APPLICANT`, and the roster of members can be listed with optional filters on `status` or `district_id`.

Activation moves the member from `APPLICANT` to `ACTIVE` and is permitted only once the member has at least one service location in `PENDING_CONSTRUCTION` or `ENERGIZED` status. The transition stamps `joined_at` and increments the member's `version`.

Suspension is available against an `ACTIVE` member, but only when no invoice for any of the member's locations is still in `PROVISIONAL` status; a lingering provisional bill blocks the move with `ERR_MEMBER_PROVISIONAL_INVOICE`. Suspending a member cascades: every load-management device of theirs in `ENROLLED` or `ACTIVE` drops to `SUSPENDED`, and while outage reports already in `REPORTED`, `ACKNOWLEDGED`, or `CREW_DISPATCHED` for their locations remain on the books, no new outage reports may be filed for a suspended member's locations. Reinstatement returns a `SUSPENDED` member to `ACTIVE` once every `FINALIZED` invoice across their locations has been `PAID` — an unpaid finalized bill blocks it with `ERR_MEMBER_PAST_DUE` — and cascades their devices from `SUSPENDED` back to `ACTIVE`, restoring credit eligibility.

Termination is the terminal state. From `ACTIVE`, it requires that the member hold no invoice in `PROVISIONAL` status and no `FINALIZED` invoice still unpaid; otherwise the request fails with `ERR_MEMBER_UNPAID_FINAL`. From `SUSPENDED`, termination requires that all `FINALIZED` invoices are either `PAID` or `WRITTEN_OFF`. Termination stamps `terminated_at` (null while the member is non-terminal), disconnects every `ENERGIZED` location, unenrolls every device still in `ENROLLED`, `ACTIVE`, or `SUSPENDED`, and converts any of the member's payouts sitting in `ISSUED` to `UNCLAIMED`, with the escheat clock continuing to run from each payout's existing `claim_deadline`. Two things deliberately survive termination: the member's `capital_credit_balance_cents` stays on the books because capital-credit claims outlive membership, and the member's `deposit_cents` — the deposit held against the account — is refunded net of the final bill at termination.

Beyond status, each member record accumulates three patronage ledgers over its lifetime: `patronage_base_kwh` for consumption on non-irrigation rate classes, `patronage_base_irrigation_kwh` for consumption on the `IRRIGATION` rate class (later allocated at reduced weight), and `unclaimed_credit_cents` for retired-but-unclaimed amounts held pending escheatment.

### 3.2. Building Service: Locations, Orders, and Aid-to-Construction

Front-office staff create a `ServiceLocation` for a member by supplying the `member_id`, the service `address`, a `rate_class` of `RESIDENTIAL`, `COMMERCIAL_GENERAL`, `COMMERCIAL_DEMAND`, `IRRIGATION`, or `SEASONAL`, and — for irrigation services — the `irrigation_connected_load_kw` nameplate figure that drives demand charging. A location begins life in `PENDING_CONSTRUCTION`. Locations on the `SEASONAL` rate class carry a computed `seasonal_active` flag that is true while the location sits inside its declared active window and gates whether billing applies at all.

Physical work is tracked by a `ServiceOrder`, created with the `service_location_id`, an `order_type` of `NEW_SERVICE`, `UPGRADE`, `RELOCATION`, or `TEMPORARY`, the `distance_ft` of the line extension, and a `requires_road_bore` flag. The order starts in `DRAFT`; orders may be listed filtered by `service_location_id`, `status`, or the `row_agreement_id` of their associated easement.

When a `FieldOpsCoordinator` estimates an order, two things happen at once. First, the member's `aid_to_construction_cents` contribution is computed: the base cost is 1,200 cents per foot of `distance_ft`, plus a flat 150,000-cent charge when a road bore is required; for a `TEMPORARY` order the base is raised to a floor of 50,000 cents if it would otherwise fall below that. The cooperative grants the first 250 feet free — an allowance of 250 times the per-foot rate, 300,000 cents, is subtracted from the base, and the contribution is the excess, never below zero. When that excess exceeds 200,000 cents, a nonlinear overhead of ten percent of the portion above 200,000 cents is added. The final contribution is rounded half-up to whole cents. Second, if the location has no right-of-way agreement yet, one is auto-created in `REQUESTED` status and the order records it as `row_agreement_id`.

Collection then forks on whether money is actually owed. An order with a positive `aid_to_construction_cents` is invoiced to the member, moving `ESTIMATED → ATC_INVOICED`; attempting that step on a zero-contribution order is rejected with `ERR_ATC_ZERO_NOT_INVOICABLE`. A zero-contribution order skips invoicing entirely — marking it paid moves it `ESTIMATED → PAID` directly, a path available only when the contribution is exactly zero. An invoiced order moves `ATC_INVOICED → PAID` on the same mark-paid action without further preconditions.

Scheduling construction (`PAID → SCHEDULED`) is gated on land rights: the location's right-of-way agreement must be `RECORDED` or in `CONDEMNATION`, else `ERR_ROW_NOT_RECORDED`. Field crews then mark the work constructed (`SCHEDULED → CONSTRUCTED`). The order's final step is not taken on the order itself — energizing the service location cascades the order from `CONSTRUCTED` to `ENERGIZED`.

An order may be cancelled while in `DRAFT` or `ESTIMATED`; in either case, if its auto-created right-of-way agreement is still sitting in `REQUESTED`, that agreement is released as part of the cancellation.

The location's own lifecycle runs in parallel. Energizing from `PENDING_CONSTRUCTION` requires both a `ServiceOrder` for the location in `CONSTRUCTED` status (`ERR_SERVICE_NOT_CONSTRUCTED` otherwise) and a right-of-way agreement in `RECORDED` status (`ERR_ROW_NOT_RECORDED` otherwise); success stamps `energized_at` and completes the order as described above. Disconnecting an `ENERGIZED` location suspends its `ENROLLED` or `ACTIVE` devices. Re-energizing a `DISCONNECTED` location requires the owning member to be `ACTIVE`. Removal — `DISCONNECTED → REMOVED` — is reserved for locations whose member has been `TERMINATED`.

### 3.3. Right-of-Way: Consent, Contest, and Condemnation

Line extensions cross member land, and the cooperative acquires easements through a `RightOfWayAgreement`. A `FieldOpsCoordinator` requests one against a location by supplying the `service_location_id` and the requested `easement_width_ft`; the agreement opens in `REQUESTED`. Agreements can be listed filtered by `service_location_id` or `status`.

The member's answer decides the path. Consent — from `REQUESTED → MEMBER_CONSENTED` — may be given only by the `Member` who owns the location (anyone else is refused with `ERR_FORBIDDEN`) and only while that member is `ACTIVE`; the consent stamps `consented_at`. Alternatively the owning member may contest the request, moving `REQUESTED → CONTESTED`. A contested easement is not a dead end: the member may later consent after all (`CONTESTED → MEMBER_CONSENTED`, again stamping `consented_at`), or `LegalCounsel` may pursue condemnation, moving `CONTESTED → CONDEMNATION`.

A consented agreement is recorded with the county by field operations (`MEMBER_CONSENTED → RECORDED`, stamping `recorded_at`), or released back to the member (`MEMBER_CONSENTED → RELEASED`). `RECORDED`, `CONDEMNATION`, and `RELEASED` are terminal. As §3.2 describes, scheduling construction accepts either `RECORDED` or `CONDEMNATION` as sufficient land rights, while energizing a new location insists on `RECORDED`.

### 3.4. Rates, Metering, and the Two Flavors of an Invoice

Rate design belongs to the `RateAnalyst`. A `RateSchedule` is created as a `DRAFT` carrying a unique `code` (such as RS-1, GS-D, or IR-2), the `rate_class` it prices, an `effective_from` timestamp, an optional `effective_to` (null means open-ended), a fixed monthly `customer_charge_cents`, an ordered list of `tiers` — each an `up_to_kwh` bound paired with a `cents_per_kwh` price, where the final tier's `up_to_kwh` is null meaning unbounded — a `demand_charge_cents_per_kw` (zero for classes without demand billing), an `irrigation_offseason_discount_pct`, and a `load_management_credit_cents` amount paid per enrolled device per month.

Publishing a schedule (`DRAFT → PUBLISHED`) enforces rate hygiene: no other `PUBLISHED` schedule for the same `rate_class` may have an effectiveness window — the half-open interval from `effective_from` to `effective_to` — overlapping this one's, on pain of `ERR_RATE_OVERLAP`. Supersession is the mechanism for rate changes: the request names a `replacement_id` identifying a `DRAFT` schedule for the same `rate_class` (anything else yields `ERR_INVALID_STATE`), and the replacement's `effective_from` must be at or before the incumbent's own `effective_from` (a later date yields `ERR_INVALID_REQUEST`). The supersede is atomic — the incumbent moves `PUBLISHED → SUPERSEDED` while the replacement moves `DRAFT → PUBLISHED` in the same step, with the replacement's overlap check excluding the schedule being superseded — and every `PROVISIONAL` invoice for affected locations is recomputed against the new schedule.

Meter data arrives as `MeterReading` submissions from a `BillingClerk` or `FieldOpsCoordinator`, each recording the `service_location_id`, the `reading_at` timestamp, the cumulative `kwh_register`, the peak `demand_kw` since the prior reading, and a `source` of `AMR`, `MANUAL`, or `ESTIMATED`. Readings are immutable records — they carry only `id` and `created_at` per §2.4 — and can be listed filtered by `service_location_id`.

Billing runs per location and period. Generating an invoice requires the `service_location_id`, an inclusive `billing_period_start`, and an exclusive `billing_period_end`; invoices may be listed by `service_location_id` or `status`. The invoice is born `PROVISIONAL` in both senses: its `status` is `PROVISIONAL` and its `variant` is the `PROVISIONAL` flavor, a forward-looking estimate in which `kwh_billed` is projected from the average daily consumption of the prior three `FINALIZED` invoices prorated to the period length, and demand is estimated as the maximum of those same three.

Finalization converts the estimate into truth. It is blocked until the location has a meter reading whose `reading_at` is at or after `billing_period_end` — otherwise `ERR_READING_MISSING`. On finalize, the `variant` flips to `FINAL` and every charge is recomputed from the register: `kwh_billed` becomes the current register reading minus the prior register reading, and billed demand becomes the actual period maximum. Finalization also feeds the patronage ledgers — the invoice's `kwh_billed` is added to the member's `patronage_base_kwh` for non-irrigation classes or to `patronage_base_irrigation_kwh` for the `IRRIGATION` class.

The energy charge itself walks the schedule's `tiers` in order. Each tier absorbs the kilowatt-hours between its predecessor's upper bound and its own `up_to_kwh` — the last tier being unbounded — and each tier line is that consumption multiplied by the tier's `cents_per_kwh`, rounded half-up to whole cents per line before the lines are summed. When the location is on the `IRRIGATION` rate class and the billing period's month falls outside the cooperative's declared irrigation season — the inclusive window from `irrigation_season_start_month` through `irrigation_season_end_month` on the `Cooperative` — the summed energy charge is then reduced by the schedule's `irrigation_offseason_discount_pct`. The result is recorded as `energy_charge_cents`.

Billed demand follows class-specific floors and ratchets before pricing. The `demand_kw_billed` starts from the peak `demand_kw` registered by readings in the period; `IRRIGATION` locations are billed for at least 5.0 kW even when actual peak demand is lower, and `COMMERCIAL_DEMAND` locations are subject to a ratchet under which billed demand is the greater of the period peak and 85 percent of the highest billed demand across the prior eleven months, evidenced by the prior `FINALIZED` invoices. The `demand_charge_cents` component is billed demand multiplied by the schedule's `demand_charge_cents_per_kw`.

The invoice's bottom line, `total_due_cents`, is the customer charge plus `energy_charge_cents` plus `demand_charge_cents` minus `load_management_credit_cents`, floored at zero so a heavy credit month never produces a negative bill.

A `FINALIZED` invoice is collected by marking it paid (`FINALIZED → PAID`), or — once its `billing_period_end` lies more than 180 days in the past — written off (`FINALIZED → WRITTEN_OFF`); attempting an earlier write-off is refused with `ERR_WRITE_OFF_TOO_EARLY`. Writing off is a compensating event, not amnesia: the invoice's kilowatt-hours are backed out of the member's patronage bases, undoing the allocation weight they would otherwise have conferred. A `PROVISIONAL` invoice that should never have existed can be voided (`PROVISIONAL → VOID`).

### 3.5. Load Management: Devices and the Credits They Earn

The cooperative pays members to let it shave peak load. A `LoadManagementDevice` is enrolled against a location by the owning `Member` or by a `MemberServicesRep`, supplying the `service_location_id` and a `device_type` of `WATER_HEATER`, `IRRIGATION_INTERRUPTIBLE`, or `AC_CYCLER`; enrollment stamps `enrolled_at` and leaves the device in `ENROLLED`. Devices can be listed by `service_location_id` or `status`.

Activation is a field-operations step with two guards: the location must be `ENERGIZED`, and an `IRRIGATION_INTERRUPTIBLE` device may only live on an `IRRIGATION`-class location — a mismatch is rejected with `ERR_LMD_RATE_CLASS_MISMATCH`. At the moment of activation the device's `monthly_credit_cents` is snapshotted from the currently `PUBLISHED` rate schedule for the location's `rate_class`, so later rate redesigns do not retroactively rewrite the device's entitlement.

Devices can be suspended directly by field operations (`ACTIVE → SUSPENDED`), and suspension also arrives by cascade — a member suspension or a location disconnect drops `ENROLLED` and `ACTIVE` devices to `SUSPENDED`. Credits stop accruing from the suspension date. Reactivation (`SUSPENDED → ACTIVE`) requires both an `ACTIVE` member and an `ENERGIZED` location. The owning member may unenroll a device at any point: from `ENROLLED` the device simply leaves the program, while unenrolling from `ACTIVE` applies a final prorated credit to the next invoice.

At invoice time the credit accrual works as follows. Each device `ACTIVE` for the full billing period contributes its `monthly_credit_cents`. A device that transitioned mid-period earns a prorated share — its monthly credit multiplied by its active days inside the period, divided by the total days in the period, floored to whole cents. The invoice's `load_management_credit_cents` is the sum across the location's devices, using the schedule in effect at `billing_period_start` for the location's rate class.

### 3.6. Outages: Reporting, Folding, and Restoration

When the lights go out, an `OutageReport` is filed against a location by the owning `Member`, the `Dispatcher`, or a `MemberServicesRep`, capturing the `service_location_id`, a `cause` of `WEATHER`, `EQUIPMENT`, `VEGETATION`, `ANIMAL`, or `UNKNOWN`, and optionally a `parent_outage_id` when the caller already knows the report belongs to a larger event. The reporting party is recorded as `reported_by_member_id`, and the report opens in `REPORTED`. Reports can be listed with filters on `service_location_id`, `status`, `reported_by_member_id`, or `parent_outage_id`.

The dispatcher's desk drives the workflow. Acknowledgement (`REPORTED → ACKNOWLEDGED`) logs a member-communication entry and increments the report's `notified_member_count` for the reporting member. Dispatch moves `ACKNOWLEDGED → CREW_DISPATCHED`. Restoration is a field-operations act (`CREW_DISPATCHED → RESTORED`) that stamps `restored_at`, cascades every `DUPLICATE` report whose `parent_outage_id` points at this one into `RESTORED` as well, and recomputes `notified_member_count` across the parent plus all of its duplicates.

Duplicate folding keeps the event tree honest. A report in `REPORTED` may be folded into a parent by supplying the `parent_outage_id`, but only while the parent is itself still open — in `REPORTED`, `ACKNOWLEDGED`, or `CREW_DISPATCHED`; folding into a terminal parent is rejected with `ERR_PARENT_OUTAGE_TERMINAL`. A successful fold moves the report to `DUPLICATE` and increments the parent's `notified_member_count`. A report that was simply mistaken can be cancelled from `REPORTED` to `CANCELLED`. Recall from §3.1 that a suspended member's locations accept no new reports at all.

### 3.7. Patronage Capital: The Pool and the Annual Allocation

The `Cooperative` resource anchors the fiscal model. A `PlatformAdmin` creates it with the legal `name`, the `fiscal_year_end_month` (1–12) on which the co-op's fiscal year ends, the `retirement_methods_allowed` set the board may draw on (`FIFO_OLDEST`, `PRO_RATA_PERCENTAGE`, or both), the `unclaimed_dormancy_years` after which an unclaimed retired-credit check escheats to the state fund, the `annual_meeting_quorum_pct` (for example 0.05 for five percent), and the irrigation-season bounds `irrigation_season_start_month` and `irrigation_season_end_month`. Its computed `capital_credits_pool_cents` is the unallocated patronage margin available for allocation runs, and its `active_election_id` points at the election currently in `NOMINATION_OPEN` or `VOTING_OPEN`, or null when none is — the cooperative list can be filtered by that `active_election_id`.

At year-end close, a `MemberServicesRep` posts the patronage margin by supplying the `fiscal_year` and `margin_cents`; the pool is credited by that amount and the cooperative's `version` increments.

Allocating the pool is a three-step ceremony with a deliberate separation of hands. A `MemberServicesRep` creates a `CapitalCreditAllocation` run in `DRAFT`, naming the `cooperative_id`, the `fiscal_year` being allocated, and a `method` of `PATRONAGE_WEIGHTED` or `FLAT_PER_MEMBER`; creation computes the run's `CapitalCreditAllocationLine` rows. Each line ties an `allocation_id` to a `member_id` and records this member's `allocated_cents` share for the year along with the `weight_kwh_effective` that produced it — the member's `patronage_base_kwh` plus one-half of their `patronage_base_irrigation_kwh`. Allocations may be listed filtered by `cooperative_id`, `fiscal_year`, or `status`, and individual lines by `member_id` or `allocation_id`.

Eligibility and share arithmetic work as follows. Eligible members are those in `ACTIVE` or `TERMINATED` status who had at least one kilowatt-hour billed during the fiscal year; a finalized invoice's kilowatt-hours are attributed to the fiscal year containing its `billing_period_end`, and fiscal year N ends on the last day of month `fiscal_year_end_month` of calendar year N. Under `PATRONAGE_WEIGHTED`, each member's raw share is the pool multiplied by the member's effective weight and divided by the total effective weight summed over members who were `ACTIVE` at any point during the fiscal year; each raw share is floored to whole cents, and the leftover cents are dealt out one at a time to members in descending order of their raw share's fractional part — ties broken by the earliest member `created_at` — until the remainder is exhausted. Under `FLAT_PER_MEMBER`, every eligible member receives the floored equal division of the pool, with remainder cents again distributed one at a time in ascending member `created_at` order. Either way, the run's `total_allocated_cents` is the sum across its lines.

Board approval (`DRAFT → APPROVED`) enforces two checks, and per §2.8 segregation of duties is evaluated before the fiscal arithmetic: the `BoardDirector` approving must not be the same `X-User-ID` as the `MemberServicesRep` who created the draft — a violation is `ERR_SOD_VIOLATION` — and the run's `total_allocated_cents` must exactly equal the cooperative's current `capital_credits_pool_cents`, else `ERR_ALLOCATION_POOL_MISMATCH`.

Posting (`APPROVED → POSTED`) is the money movement, and it carries the optimistic-concurrency obligation of §2.7: the request must include `expected_cooperative_version` matching the cooperative's current `version`, with a mismatch rejected as `ERR_STALE_VERSION` (HTTP 412). Posting credits every line's `allocated_cents` to its member's `capital_credit_balance_cents`, debits the pool to zero for that fiscal year, increments the `version` of every affected member, and increments the cooperative's `version`. A draft run that should not proceed can be voided (`DRAFT → VOIDED`).

### 3.8. Retiring Capital: Payouts, Dormancy, and Escheatment

Where allocation builds member equity, retirement pays it out. A `MemberServicesRep` proposes a `CapitalCreditRetirement` run with the `cooperative_id`, a `method`, the target `total_retire_cents`, and — when the method is `PRO_RATA_PERCENTAGE` — the `pro_rata_pct` fraction of each member's balance to retire. Retirements may be listed by `cooperative_id` or `status`.

Board approval (`PROPOSED → BOARD_APPROVED`) layers three checks. The proposed `method` must appear in the cooperative's `retirement_methods_allowed`, else `ERR_RETIREMENT_METHOD_NOT_ALLOWED`. A `PRO_RATA_PERCENTAGE` run must carry a `pro_rata_pct` greater than zero and at most one. And segregation of duties again applies — the approving `BoardDirector` must differ from the proposing `MemberServicesRep`, else `ERR_SOD_VIOLATION`.

Execution (`BOARD_APPROVED → EXECUTING`) is the second OCC-guarded fiscal operation: the request carries `expected_cooperative_version` and is rejected with `ERR_STALE_VERSION` (HTTP 412) when the cooperative's `version` has advanced past what the client observed. Execution also requires that `total_retire_cents` not exceed the sum of `capital_credit_balance_cents` across all members, else `ERR_RETIREMENT_BUDGET_EXCEEDED`. A successful execution stamps `executed_at`, increments the cooperative's `version`, and generates one `CapitalCreditPayout` row per payee according to the method. Under `FIFO_OLDEST`, members are walked in order of their oldest unretired allocation vintage — the earliest allocation `fiscal_year` with remaining balance, ties broken by ascending member `created_at` — and each is paid up to their full balance until the target total is exhausted; the final member in the walk may be partially paid, and any remainder below one cent is dropped. Under `PRO_RATA_PERCENTAGE`, every member with a positive balance is paid the floor of `pro_rata_pct` times their `capital_credit_balance_cents`; if that computed total exceeds `total_retire_cents`, each payout is scaled by the ratio of the target to the computed total and floored again, and the dropped cents remain in member balances. A run may instead be aborted from either `PROPOSED` or `BOARD_APPROVED`.

Each payout ties a `retirement_id` to a `member_id` with a computed `payout_cents`. On execution the payout moves `PENDING → ISSUED`, stamping `issued_at` and computing its `claim_deadline` as `issued_at` plus the cooperative's `unclaimed_dormancy_years`. From there, three fates await. A member who deposits the check has it marked cashed (`ISSUED → CASHED`) — allowed only while the logical clock reads strictly before the `claim_deadline`, with a stale check refused as `ERR_PAYOUT_STALE` — and the member's `capital_credit_balance_cents` is decremented by the payout amount. A member who cannot be reached has the payout marked unclaimed (`ISSUED → UNCLAIMED`), which moves the money rather than erasing it: `unclaimed_credit_cents` is incremented and `capital_credit_balance_cents` decremented by the same `payout_cents`. Finally, when the logical clock reaches or passes the `claim_deadline`, the escheatment sweep of §2.5 moves the payout `UNCLAIMED → ESCHEATED`, decrements the member's `unclaimed_credit_cents`, and writes an escheat ledger entry for audit.

The run itself settles automatically: once every payout of the run has reached `CASHED`, `UNCLAIMED`, or `ESCHEATED`, the retirement transitions `EXECUTING → SETTLED` and its `total_disbursed_cents` — the sum actually disbursed across payout lines — is finalized. Members can review their own payout history, and staff can list a run's payouts.

### 3.9. Board Elections and the Annual Meeting

Cooperative democracy runs on districted elections administered by the `BoardSecretary`. Creating a `BoardElection` takes the `cooperative_id`, the election `year`, the list of `seats` — the district integers contested this year — and the `voting_opens_at` and `voting_closes_at` timestamps. The election starts in `DRAFT`; elections may be listed by `cooperative_id` or `status`.

Opening nominations (`DRAFT → NOMINATION_OPEN`) installs the election as the cooperative's `active_election_id`. Closing nominations takes the declared `candidate_names` and requires every contested seat to have at least one declared candidate; a seat without a candidate blocks the close with `ERR_ELECTION_NO_CANDIDATE`, leaving the election in `NOMINATION_OPEN`.

Opening the vote is the third OCC-guarded operation of §2.7: the request must carry `expected_cooperative_version` equal to the cooperative's current `version`, else `ERR_STALE_VERSION` (HTTP 412), because another writer may have flipped `active_election_id` to a different election. Opening is also gated on time — the logical clock must have reached `voting_opens_at`, else `ERR_ELECTION_WINDOW` — and it initializes the election's `quorum_met` flag to false.

While voting is open, members cast ballots. A `Ballot` records the `election_id`, the `district` seat being voted, the `candidate_name` selected, and an `is_proxy` flag for ballots cast by proxy at the annual meeting; `cast_at` records when the ballot was cast, and as an append-only event the ballot carries only `id` and `created_at` per §2.4. Casting is guarded by four rules: the election must be in `VOTING_OPEN` with the logical clock inside the half-open window from `voting_opens_at` to `voting_closes_at` — outside it the cast is rejected with `ERR_ELECTION_WINDOW`; the casting member must be `ACTIVE`, else `ERR_BALLOT_MEMBER_INACTIVE`; a non-proxy ballot's `district` must equal the member's own `district_id`, else `ERR_BALLOT_DISTRICT_MISMATCH`, while proxy ballots may be cast for any district provided `is_proxy` is true; and only one ballot may exist per election, member, and district — a repeat cast is rejected with `ERR_BALLOT_ALREADY_CAST`. Ballots are visible to the `BoardSecretary`, listable by `election_id`, `district`, or `member_id`.

Closing the vote (`VOTING_OPEN → VOTING_CLOSED`) requires the logical clock to have reached `voting_closes_at` — `ERR_ELECTION_WINDOW` otherwise — and recomputes `quorum_met`: the count of distinct members who cast ballots must be at least the ceiling of `annual_meeting_quorum_pct` multiplied by the number of `ACTIVE` members at the moment of closing.

Certification (`VOTING_CLOSED → CERTIFIED`) is permitted only when quorum was met; without it the attempt fails with `ERR_ELECTION_NO_QUORUM`. Certification clears the cooperative's `active_election_id`. An election whose vote is compromised can instead be voided from `VOTING_CLOSED`, which likewise clears `active_election_id`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — lifecycle transitions, configuration postings, clock advancement — return `200 OK`. Request and response bodies are not repeated here; §2 and §3 define the fields and behaviors each operation carries.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/coop/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |
| POST | `/coop/cooperatives` | Create the cooperative config | PlatformAdmin |
| GET | `/coop/cooperatives/{id}` | Get cooperative | PlatformAdmin, MemberServicesRep, BoardDirector, BoardSecretary, RateAnalyst, BillingClerk, FieldOpsCoordinator, Dispatcher, LegalCounsel |
| GET | `/coop/cooperatives` | List cooperatives, optionally filtered by active election | PlatformAdmin, MemberServicesRep, BoardDirector, BoardSecretary |
| POST | `/coop/cooperatives/{id}/post-margin` | Post year-end patronage margin into the allocation pool | MemberServicesRep |
| POST | `/coop/members` | Create a member (APPLICANT) | MemberServicesRep |
| GET | `/coop/members/{id}` | Get member | MemberServicesRep, BoardDirector, BoardSecretary, BillingClerk, Member |
| GET | `/coop/members` | List members | MemberServicesRep, BoardDirector, BoardSecretary, BillingClerk |
| POST | `/coop/members/{id}/activate` | Activate APPLICANT member | MemberServicesRep |
| POST | `/coop/members/{id}/suspend` | Suspend ACTIVE member | MemberServicesRep |
| POST | `/coop/members/{id}/reinstate` | Reinstate SUSPENDED member | MemberServicesRep |
| POST | `/coop/members/{id}/terminate` | Terminate member | MemberServicesRep |
| GET | `/coop/members/{id}/service-locations` | List member's service locations | MemberServicesRep, BillingClerk, FieldOpsCoordinator, Member |
| GET | `/coop/members/{id}/capital-credit-payouts` | List member's capital credit payouts | MemberServicesRep, BoardDirector, Member |
| POST | `/coop/service-locations` | Create service location for a member | MemberServicesRep |
| GET | `/coop/service-locations/{id}` | Get service location | MemberServicesRep, BillingClerk, FieldOpsCoordinator, Dispatcher, Member |
| POST | `/coop/service-locations/{id}/energize` | Energize a location | FieldOpsCoordinator |
| POST | `/coop/service-locations/{id}/disconnect` | Disconnect a location | FieldOpsCoordinator |
| POST | `/coop/service-locations/{id}/remove` | Remove a location | FieldOpsCoordinator |
| POST | `/coop/rate-schedules` | Create rate schedule (DRAFT) | RateAnalyst |
| GET | `/coop/rate-schedules/{id}` | Get rate schedule | RateAnalyst, MemberServicesRep, BillingClerk |
| POST | `/coop/rate-schedules/{id}/publish` | Publish a schedule | RateAnalyst |
| POST | `/coop/rate-schedules/{id}/supersede` | Supersede a PUBLISHED schedule with a DRAFT replacement | RateAnalyst |
| POST | `/coop/meter-readings` | Submit a meter reading | BillingClerk, FieldOpsCoordinator |
| GET | `/coop/meter-readings/{id}` | Get a single meter reading | BillingClerk, FieldOpsCoordinator, MemberServicesRep |
| GET | `/coop/meter-readings` | List readings, optionally by location | BillingClerk, FieldOpsCoordinator, MemberServicesRep |
| POST | `/coop/invoices` | Generate a PROVISIONAL invoice for a location/period | BillingClerk |
| GET | `/coop/invoices/{id}` | Get invoice | BillingClerk, MemberServicesRep, Member |
| GET | `/coop/invoices` | List invoices | BillingClerk, MemberServicesRep |
| POST | `/coop/invoices/{id}/finalize` | Finalize a PROVISIONAL invoice using register-true readings | BillingClerk |
| POST | `/coop/invoices/{id}/pay` | Pay a FINALIZED invoice | BillingClerk |
| POST | `/coop/invoices/{id}/write-off` | Write off a stale FINALIZED invoice | BillingClerk |
| POST | `/coop/invoices/{id}/void` | Void a PROVISIONAL invoice | BillingClerk |
| POST | `/coop/capital-credit-allocations` | Create a DRAFT allocation run | MemberServicesRep |
| GET | `/coop/capital-credit-allocations/{id}` | Get allocation | MemberServicesRep, BoardDirector |
| GET | `/coop/capital-credit-allocations` | List allocations, optionally by cooperative | MemberServicesRep, BoardDirector |
| GET | `/coop/capital-credit-allocations/{id}/lines` | List allocation lines | MemberServicesRep, BoardDirector |
| GET | `/coop/capital-credit-allocation-lines/{id}` | Get a single allocation line | MemberServicesRep, BoardDirector |
| GET | `/coop/capital-credit-allocation-lines` | List allocation lines, optionally by member or allocation | MemberServicesRep, BoardDirector |
| POST | `/coop/capital-credit-allocations/{id}/approve` | Board approves allocation | BoardDirector |
| POST | `/coop/capital-credit-allocations/{id}/post` | Post allocation to member balances (OCC on Cooperative) | MemberServicesRep |
| POST | `/coop/capital-credit-allocations/{id}/void` | Void a DRAFT allocation | MemberServicesRep |
| POST | `/coop/capital-credit-retirements` | Propose a retirement run | MemberServicesRep |
| GET | `/coop/capital-credit-retirements/{id}` | Get retirement | MemberServicesRep, BoardDirector |
| GET | `/coop/capital-credit-retirements` | List retirements, optionally by cooperative | MemberServicesRep, BoardDirector |
| POST | `/coop/capital-credit-retirements/{id}/board-approve` | Board approves retirement | BoardDirector |
| POST | `/coop/capital-credit-retirements/{id}/execute` | Execute retirement run (OCC on Cooperative) | MemberServicesRep |
| POST | `/coop/capital-credit-retirements/{id}/abort` | Abort a proposed/approved run | MemberServicesRep |
| GET | `/coop/capital-credit-retirements/{id}/payouts` | List payouts of a run | MemberServicesRep, BoardDirector |
| POST | `/coop/capital-credit-payouts/{id}/cash` | Mark payout cashed | MemberServicesRep |
| POST | `/coop/capital-credit-payouts/{id}/mark-unclaimed` | Mark payout unclaimed | MemberServicesRep |
| POST | `/coop/outage-reports` | Member or staff reports an outage | Member, Dispatcher, MemberServicesRep |
| GET | `/coop/outage-reports/{id}` | Get outage report | Dispatcher, FieldOpsCoordinator, MemberServicesRep, Member |
| GET | `/coop/outage-reports` | List outage reports | Dispatcher, FieldOpsCoordinator, MemberServicesRep |
| POST | `/coop/outage-reports/{id}/acknowledge` | Acknowledge report | Dispatcher |
| POST | `/coop/outage-reports/{id}/dispatch` | Dispatch crew | Dispatcher |
| POST | `/coop/outage-reports/{id}/restore` | Mark restored | FieldOpsCoordinator |
| POST | `/coop/outage-reports/{id}/mark-duplicate` | Fold into parent outage | Dispatcher |
| POST | `/coop/outage-reports/{id}/cancel` | Cancel a report | Dispatcher |
| POST | `/coop/right-of-way-agreements` | Request an easement for a location | FieldOpsCoordinator |
| GET | `/coop/right-of-way-agreements/{id}` | Get ROW agreement | FieldOpsCoordinator, LegalCounsel, MemberServicesRep, Member |
| GET | `/coop/right-of-way-agreements` | List ROW agreements | FieldOpsCoordinator, LegalCounsel, MemberServicesRep |
| POST | `/coop/right-of-way-agreements/{id}/consent` | Member consents | Member |
| POST | `/coop/right-of-way-agreements/{id}/record` | Record with county | FieldOpsCoordinator |
| POST | `/coop/right-of-way-agreements/{id}/contest` | Member contests | Member |
| POST | `/coop/right-of-way-agreements/{id}/condemn` | Legal condemnation | LegalCounsel |
| POST | `/coop/right-of-way-agreements/{id}/release` | Release easement | FieldOpsCoordinator |
| POST | `/coop/load-management-devices` | Enroll a device | Member, MemberServicesRep |
| GET | `/coop/load-management-devices/{id}` | Get device | FieldOpsCoordinator, MemberServicesRep, Member |
| GET | `/coop/load-management-devices` | List devices | FieldOpsCoordinator, MemberServicesRep |
| POST | `/coop/load-management-devices/{id}/activate` | Activate an enrolled device | FieldOpsCoordinator |
| POST | `/coop/load-management-devices/{id}/suspend` | Suspend a device | FieldOpsCoordinator |
| POST | `/coop/load-management-devices/{id}/reactivate` | Reactivate a suspended device | FieldOpsCoordinator |
| POST | `/coop/load-management-devices/{id}/unenroll` | Member unenrolls a device | Member |
| POST | `/coop/service-orders` | Create a service order | MemberServicesRep |
| GET | `/coop/service-orders/{id}` | Get service order | MemberServicesRep, FieldOpsCoordinator, Member |
| GET | `/coop/service-orders` | List service orders | MemberServicesRep, FieldOpsCoordinator |
| POST | `/coop/service-orders/{id}/estimate` | Compute aid-to-construction estimate | FieldOpsCoordinator |
| POST | `/coop/service-orders/{id}/invoice-atc` | Invoice the member for ATC | MemberServicesRep |
| POST | `/coop/service-orders/{id}/mark-paid` | Mark ATC paid | MemberServicesRep |
| POST | `/coop/service-orders/{id}/schedule` | Schedule construction | FieldOpsCoordinator |
| POST | `/coop/service-orders/{id}/construct` | Mark constructed | FieldOpsCoordinator |
| POST | `/coop/service-orders/{id}/cancel` | Cancel an order | FieldOpsCoordinator |
| POST | `/coop/board-elections` | Create an election | BoardSecretary |
| GET | `/coop/board-elections/{id}` | Get election | BoardSecretary, BoardDirector, MemberServicesRep |
| GET | `/coop/board-elections` | List elections, optionally by cooperative | BoardSecretary, BoardDirector, MemberServicesRep |
| POST | `/coop/board-elections/{id}/open-nominations` | Open nominations | BoardSecretary |
| POST | `/coop/board-elections/{id}/close-nominations` | Close nominations | BoardSecretary |
| POST | `/coop/board-elections/{id}/open-voting` | Open voting (OCC on Cooperative) | BoardSecretary |
| POST | `/coop/board-elections/{id}/close-voting` | Close voting | BoardSecretary |
| POST | `/coop/board-elections/{id}/certify` | Certify results | BoardSecretary |
| POST | `/coop/board-elections/{id}/void` | Void election | BoardSecretary |
| POST | `/coop/ballots` | Cast a ballot | Member |
| GET | `/coop/ballots/{id}` | Get a single ballot | BoardSecretary |
| GET | `/coop/ballots` | List ballots | BoardSecretary |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the §2 and §3 narratives where the guarded workflow lives.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SOD_VIOLATION` | 409 Conflict |
| `ERR_ALLOCATION_POOL_MISMATCH` | 409 Conflict |
| `ERR_RETIREMENT_METHOD_NOT_ALLOWED` | 409 Conflict |
| `ERR_RETIREMENT_BUDGET_EXCEEDED` | 409 Conflict |
| `ERR_PAYOUT_STALE` | 409 Conflict |
| `ERR_MEMBER_PROVISIONAL_INVOICE` | 409 Conflict |
| `ERR_MEMBER_PAST_DUE` | 409 Conflict |
| `ERR_MEMBER_UNPAID_FINAL` | 409 Conflict |
| `ERR_RATE_OVERLAP` | 409 Conflict |
| `ERR_READING_MISSING` | 409 Conflict |
| `ERR_WRITE_OFF_TOO_EARLY` | 409 Conflict |
| `ERR_LMD_RATE_CLASS_MISMATCH` | 409 Conflict |
| `ERR_ROW_NOT_RECORDED` | 409 Conflict |
| `ERR_SERVICE_NOT_CONSTRUCTED` | 409 Conflict |
| `ERR_ATC_ZERO_NOT_INVOICABLE` | 409 Conflict |
| `ERR_PARENT_OUTAGE_TERMINAL` | 409 Conflict |
| `ERR_ELECTION_WINDOW` | 409 Conflict |
| `ERR_ELECTION_NO_CANDIDATE` | 409 Conflict |
| `ERR_ELECTION_NO_QUORUM` | 409 Conflict |
| `ERR_BALLOT_ALREADY_CAST` | 409 Conflict |
| `ERR_BALLOT_DISTRICT_MISMATCH` | 409 Conflict |
| `ERR_BALLOT_MEMBER_INACTIVE` | 409 Conflict |
