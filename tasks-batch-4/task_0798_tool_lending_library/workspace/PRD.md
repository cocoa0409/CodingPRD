# Tool-Lending-Library API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the **Tool & Gear Lending Library** API, the operational backbone of a community nonprofit that lends tools, outdoor equipment, and kitchen gear to its members. The library must reconcile a small, finite pool of physical copies against a steady stream of reservations, walk-up borrowing, waitlists, donations, and repairs — all while keeping members' outstanding balances honest and their borrowing privileges fair.

The system is best understood as a quota-allocation engine layered over time. Every catalog title owns a handful of physical copies, and each copy travels along two independent tracks at once: whether it is free to lend and what physical condition it is in. Reservations claim capacity inside a future window; loans consume it; late returns accrue fees; damaged or lost gear triggers depreciation-based replacement charges; and a member who falls too far into debt is automatically suspended until they settle up. Because much of this motion is driven by the passage of time rather than by direct user action, the library runs on a **logical clock** that a coordinator advances explicitly, and a housekeeping batch that fires every clock-gated transition in one sweep.

This API is the sole contract between the library's front desk software and its data. It governs membership, the catalog and its physical copies, reservations and loans, holds and the waitlist, fees and the member ledger, donations and intake, and maintenance and retirement of gear, along with a coordinator-only usage report.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting invariants that apply to every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly three roles: `Member`, `Volunteer`, and `Coordinator`. If either header is missing, or if `X-User-Role` names a role the system does not recognize, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The three roles form a hierarchical override chain: a `Member` is an ordinary borrower, a `Volunteer` is a desk operator, and a `Coordinator` is a superset operator who may perform everything a `Volunteer` may plus the administrative catalog, member-registration, fee-waiver, reporting, clock, and housekeeping operations.

Identity binding differs by role and determines ownership checks:

- When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member` entity. Ownership checks on any resource that references a member compare the resource's `member_id` to `X-User-ID`. A member acting on a reservation cancel, a loan renew, a fee payment, or a hold may only touch resources whose `member_id` equals their own `X-User-ID`; a mismatch is rejected with `ERR_FORBIDDEN_NOT_OWNER` (HTTP 403).
- When `X-User-Role` is `Volunteer`, `X-User-ID` is the `id` of the acting `Volunteer` entity. At checkout the server records this identifier on the loan's `checked_out_by_volunteer_id` field for audit purposes only; it is not otherwise compared to any resource's `id`, and volunteers are not subject to the member-ownership restriction (they may cancel, renew, and pay against any member's resources).
- When `X-User-Role` is `Coordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it in an audit capacity but does not compare it to any entity's `id`.

The validation pipeline is strictly ordered, and earlier checks mask later ones. Authentication (presence and validity of headers) is evaluated first, then role authorization, then existence of every referenced resource, then member-ownership, then request-body shape and enumeration validity, then the domain-specific state, capacity, limit, fiscal, and concurrency checks described throughout §2 and §3. The precise relative ordering of the domain checks is called out where each rule is introduced.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of matching items to skip and defaults to 0.

Unless a specific endpoint says otherwise, every list endpoint returns resources sorted by their `created_at` timestamp in ascending order. Each list response reports `limit`, `offset`, `total_count`, and `has_more` in the envelope's `meta` object, where `total_count` is the number of items matching the filter before pagination and `has_more` indicates whether items remain beyond the returned page.

### 2.4. Common Resource Properties and Versioning

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix, along with a `created_at` timestamp recorded in ISO 8601 UTC with three fractional digits. All entities in this system — members, volunteers, items, copies, reservations, loans, holds, fees, donations, and maintenance tickets — also carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) and an integer `version`. Whenever the server mutates a resource, it refreshes that resource's `updated_at` and increments its `version` by one. A resource's `version` begins at 1 on creation.

Derived fields are first-class mutations. When a copy changes status and the system recomputes an `Item`'s availability counts, that recomputation is a mutation of the item: it refreshes the item's `updated_at` and increments the item's `version`. The same holds for a member whose ledger counters are recomputed. These automatic, server-initiated transitions occur without an explicit client request against the affected resource.

### 2.5. The Logical Clock and Time-Driven Housekeeping

The library does not read wall-clock time. It keeps a **logical clock** whose value is the authoritative "now" for every time comparison — due dates, reservation windows, claim deadlines, membership expiry, and fee accrual. On server startup the clock defaults to `2026-03-01T00:00:00Z`, and it never falls back to real time. A coordinator advances the clock by supplying a `to_iso8601` instant; setting the clock returns the new `current_utc` and by itself fires no state transitions.

State that depends on the passage of time only changes when a coordinator runs the housekeeping batch. A single housekeeping run, evaluated against the current logical clock, performs all of the following clock-gated transitions and reports counts of each: it moves each `ACTIVE` loan past its `due_date` to `OVERDUE` (`overdue_count`); it declares sufficiently stale overdue loans `LOST` (`lost_count`); it expires reservations whose window has closed (`expired_reservations`); it promotes eligible waitlisted holds (`promoted_holds`); it expires promoted holds past their claim deadline (`expired_holds`); it reinstates members who have cleared their balance (`reinstated_members`); it expires memberships past their expiry instant (`expired_members`); it accrues late fees on overdue loans; and it starts scheduled maintenance whose window has begun. The mechanics of each of these transitions are detailed in §3.

### 2.6. Physical Copies: Dual-Axis Status and Availability Counts

Each catalog `Item` owns zero or more physical copies, modeled as `ItemCopy` records. A copy is described by two **independent** status axes. The `availability_status` axis tracks whether the copy is free to lend and is one of `AVAILABLE`, `RESERVED`, or `ON_LOAN`. The `condition_status` axis tracks physical condition and is one of `GOOD`, `NEEDS_MAINTENANCE`, `UNDER_MAINTENANCE`, or `RETIRED`. The two axes move separately: a copy returned with damage is set back to `AVAILABLE` on the availability axis yet `NEEDS_MAINTENANCE` on the condition axis, so it is not lendable until repaired.

An item exposes six derived counts, each recomputed whenever any of its copies changes on either axis (on reservation create, cancel, or expiry; on checkout; on return; on donation acceptance; on maintenance resolution; and on loan-loss retirement):

- `serviceable_copies_count` is the number of copies whose `condition_status` is anything other than `RETIRED`.
- `available_copies_count` is the number of copies that are simultaneously `AVAILABLE` on the availability axis and `GOOD` on the condition axis.
- `reserved_count` is the number of copies whose `availability_status` is `RESERVED`.
- `on_loan_count` is the number of copies whose `availability_status` is `ON_LOAN`.
- `maintenance_count` is the number of copies whose `condition_status` is either `NEEDS_MAINTENANCE` or `UNDER_MAINTENANCE`.
- `waitlist_length` is the number of holds on the item whose status is `PENDING` or `PROMOTED`.

These counts obey a conservation invariant: for the serviceable pool, `available_copies_count` plus `reserved_count` plus `on_loan_count` plus `maintenance_count` always equals `serviceable_copies_count`. All six are integer counts computed over every copy of the item, with `RETIRED` copies excluded only from `serviceable_copies_count`.

### 2.7. The Member Fee Ledger

Every fee the library raises against a member is an accountable entry, and a member exposes four rolled-up ledger counters, all in integer cents, recomputed whenever a fee is created, finalized, paid, or waived. `outstanding_balance_cents` is the sum of `amount_cents` across the member's fees whose status is `ACCRUING` or `PENDING`. `total_assessed_cents` is the lifetime sum of `amount_cents` across the member's **finalized** fees — those whose status is `PENDING`, `PAID`, or `WAIVED` (an `ACCRUING` fee counts toward the outstanding balance but not toward the assessed total until it is finalized). `total_paid_cents` is the lifetime sum of `amount_cents` across the member's `PAID` fees, and `total_waived_cents` is the lifetime sum across the member's `WAIVED` fees.

The ledger is conserved: a member's `total_assessed_cents` always equals the sum of their still-outstanding finalized (`PENDING`) fees plus `total_paid_cents` plus `total_waived_cents`. A member also carries a `balance_limit_cents` value; this is an informational soft limit shown to the member and is never itself used to gate any operation.

### 2.8. Optimistic Concurrency at Checkout

Checking out a copy is guarded by optimistic concurrency control on the parent `Item`. A checkout request must carry `expected_item_version`, a non-optional field holding the `version` of the `Item` the client last observed. Before creating the loan, the server compares `expected_item_version` against the item's current `version`. If another writer has advanced the item's `version` since the client last read it — for example by consuming the last serviceable copy under the quota model — the client's view of which copies remain available is stale, and the checkout is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful checkout increments the item's `version` by one. No other endpoint takes a version field; checkout is the only OCC-guarded write.

### 2.9. Nested Resource Retrieval and Existence Ordering

Some paths address a resource beneath a parent, such as the copies of an item. When a path or request body names more than one resource identifier, the server validates them left to right and rejects the request at the first identifier that does not resolve to an existing resource, returning the not-found error specific to that resource type. The not-found errors are `ERR_MEMBER_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_COPY_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`, `ERR_LOAN_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, `ERR_FEE_NOT_FOUND`, `ERR_DONATION_NOT_FOUND`, and `ERR_TICKET_NOT_FOUND`, each HTTP 404. This existence sweep runs after authentication and authorization but before any body-shape or business-state check.

### 2.10. Monetary Precision and Rounding

All monetary amounts are integer cents. Fee arithmetic that is purely additive or multiplicative over integer cents (such as multiplying a per-day rate by a whole number of days) needs no rounding. The depreciation calculation, however, involves percentage factors: wherever a replacement value is multiplied by a rate, the result is rounded to a whole number of cents using the **round half up** convention, and — critically — the rounding is applied at the pinned per-year and salvage-floor steps described in §3, not deferred to the end. All derived counts elsewhere in the system are plain integers.

## 3. Business Logic & Workflows

### 3.1. Membership Lifecycle

A `Coordinator` registers a member by supplying their `name`, contact `email` (unique across members), and membership `tier`, which is one of `BASIC` or `PLUS`. The registration may optionally set `max_active_loans`, `max_active_holds`, `balance_limit_cents`, and `membership_expires_at`; when omitted, `max_active_loans` defaults to 5, `max_active_holds` defaults to 3, and `balance_limit_cents` defaults to 2000. A newly registered member starts in `ACTIVE` status with every ledger counter — `outstanding_balance_cents`, `total_assessed_cents`, `total_paid_cents`, and `total_waived_cents` — at zero. A member's `status` is one of `ACTIVE`, `SUSPENDED`, or `EXPIRED`.

Suspension is automatic and fiscal. Whenever a fee finalization — a loan return, an overdue accrual during housekeeping, or a replacement charge — pushes a member's `outstanding_balance_cents` to at least the suspension threshold of 2000 cents, that member transitions from `ACTIVE` to `SUSPENDED`. Suspension cascades: all of the member's `PENDING` reservations move to `CANCELLED`, each releasing its assigned copy from `RESERVED` back to `AVAILABLE` and triggering the item's count recomputation; and all of the member's `PENDING` and `PROMOTED` holds move to `EXPIRED`, with a `PROMOTED` hold additionally releasing its promoted copy back to `AVAILABLE`.

Reinstatement runs during housekeeping. When a `SUSPENDED` member's `outstanding_balance_cents` has returned to exactly zero — every fee either `PAID` or `WAIVED` — the next housekeeping run transitions that member from `SUSPENDED` back to `ACTIVE`. This suspend-then-reinstate loop may repeat any number of times over a member's life.

Membership also expires by time. During housekeeping, any member — whether `ACTIVE` or `SUSPENDED` — whose `membership_expires_at` instant is at or before the current logical clock transitions to `EXPIRED`, which is terminal. Expiry cascades the same way suspension does: the member's `PENDING` reservations are `CANCELLED` and their `PENDING` and `PROMOTED` holds are `EXPIRED`, with each affected copy released back to `AVAILABLE`.

Desk staff are modeled separately as `Volunteer` records, which a `Coordinator` creates by supplying a `name`, a `role_level` of `VOLUNTEER` or `COORDINATOR`, and an optional `active` flag that defaults to true and governs whether that volunteer may perform desk operations.

Wherever an operation requires the acting or target member to be in good standing — reserving, checking out, joining a waitlist, or renewing — a member who is `SUSPENDED` or `EXPIRED` causes the request to be rejected with `ERR_MEMBER_NOT_ACTIVE` (HTTP 409).

### 3.2. Catalog, Copies, and Donation Intake

A `Coordinator` builds the catalog by creating an `Item` with a `name`, a `category` of `TOOL`, `OUTDOOR`, or `KITCHEN`, a `replacement_value_cents`, a `loan_period_days` used to compute due dates, and a `daily_late_fee_cents` late-fee rate. The optional `max_renewals` defaults to 2. A freshly created item has all six derived counts at zero and `version` 1.

Physical copies enter the catalog two ways. A `Volunteer` or `Coordinator` may add a copy directly to an item by supplying an `asset_tag` and an `acquired_on` acquisition date, with an optional `origin` of `PURCHASE` or `DONATION` that defaults to `PURCHASE`. A copy added this way starts `AVAILABLE` on the availability axis and `GOOD` on the condition axis, and the parent item's counts and `version` are recomputed. The `item_id` linking a copy to its title is established at creation, and the copies of an item can be listed for reverse lookup.

Alternatively, copies arrive through donation. Any member, volunteer, or coordinator may record a donation offer against a catalog item by supplying the `donor_name`, the `item_id` of the title it contributes to, and a `proposed_condition` of `GOOD` or `FAIR`; an optional `donor_member_id` records the donor's membership when applicable (donors are often non-members, so this is audit-only and never treated as an ownership link). A donation begins in `OFFERED` status, which is one of `OFFERED`, `ACCEPTED`, or `REJECTED`. A `Volunteer` or `Coordinator` reviews the offer, which is addressable by its `donation_id`. Accepting it — permitted only while the referenced item still exists — mints a new `ItemCopy` under that item with availability `AVAILABLE`, condition `GOOD`, and `origin` of `DONATION`; the intake supplies the new copy's `asset_tag` and an optional `acquired_on` (defaulting to the acquisition instant). The minted copy's identifier is recorded on the donation's `created_copy_id`, the item's `serviceable_copies_count`, `available_copies_count`, and `version` are recomputed, and because a new copy has just become available the waitlist-promotion cascade may promote the item's next waiting hold. Rejecting an offer simply moves it to `REJECTED` with no inventory effect and may carry an optional `reason`.

### 3.3. Reservations and Windowed Capacity

A `Member` reserves a copy of an item for a future window by naming the `member_id` (which must be their own), the `item_id`, and a half-open window defined by `window_start` (inclusive) and `window_end` (exclusive). The window must be well-formed: if `window_start` is not strictly before `window_end`, the request is rejected with `ERR_INVALID_WINDOW` (HTTP 400). The server, not the client, chooses which physical copy to assign: it picks a serviceable copy that is `GOOD` and free across the requested window and records its identifier on the reservation's server-assigned `copy_id`. A reservation records its `source` — `MEMBER` for a directly created reservation, or `WAITLIST_PROMOTION` for one minted by hold promotion — and its `status`, one of `PENDING`, `FULFILLED`, `CANCELLED`, or `EXPIRED`. On creation the reservation is `PENDING`, the assigned copy moves from `AVAILABLE` to `RESERVED` (which requires the copy's condition to be `GOOD`), and the item's `reserved_count`, `available_copies_count`, and `version` are recomputed.

Two capacity checks guard reservation creation. First, the item must have at least one serviceable copy free across the requested window; if the candidate set is empty, the request is rejected with `ERR_NO_COPY_AVAILABLE` (HTTP 409). Second, honoring the reservation must not push the item over its serviceable capacity at any instant within the half-open window `[window_start, window_end)` when aggregated against existing commitments that overlap that window; a window that would exceed capacity is rejected with `ERR_ITEM_NO_CAPACITY_FOR_WINDOW` (HTTP 409). Of the two, the aggregate-window capacity check is the temporal-overlap guard, evaluated before the empty-candidate fallback.

A `PENDING` reservation may be cancelled by the owning member, a volunteer, or a coordinator, and reservations also expire by time. Cancellation moves the reservation to `CANCELLED`; expiry, which occurs during housekeeping once the logical clock reaches or passes `window_end` on a still-unfulfilled reservation, moves it to `EXPIRED`. In both cases the assigned copy is released from `RESERVED` back to `AVAILABLE`, the item's `reserved_count`, `available_copies_count`, and `version` are recomputed, and because a copy has just freed up the waitlist-promotion cascade may promote the item's next waiting hold. A reservation that is fulfilled by a checkout instead moves to `FULFILLED`, as described next.

### 3.4. Checkout and the Loan Lifecycle

A `Volunteer` or `Coordinator` checks out a copy — either a walk-up loan or the fulfillment of an existing reservation — by supplying the borrower's `member_id`, the `copy_id` to lend, the `expected_item_version` for the concurrency check of §2.8, and an optional `reservation_id` when fulfilling a reservation. On success the server records the checkout: the loan's `item_id` is mirrored from the copy for convenience, `checked_out_at` is stamped from the logical clock, `due_date` is computed as `checked_out_at` plus the item's `loan_period_days`, `renewals_used` starts at 0, the loan's `status` becomes `ACTIVE`, and `checked_out_by_volunteer_id` records the operator's `X-User-ID`. The copy moves to `ON_LOAN` (from `RESERVED` when fulfilling a reservation, or from `AVAILABLE` for a walk-up), the item's `on_loan_count` and remaining counts are recomputed, and the item's `version` is incremented by one. A loan's `status` is one of `ACTIVE`, `OVERDUE`, `RETURNED`, or `LOST`. When a `reservation_id` is supplied, that reservation must belong to the same member as the loan; the reservation transitions to `FULFILLED`, and if that reservation was itself minted by a waitlist promotion, the originating hold also transitions to `FULFILLED`.

Checkout is gated by a stack of preconditions beyond the concurrency check. The target member must be `ACTIVE` (else `ERR_MEMBER_NOT_ACTIVE`). The chosen copy must be lendable — either `AVAILABLE`, or `RESERVED` to this member's own reservation — and `GOOD` on the condition axis; a copy that is otherwise reserved, on loan, or not in good condition is rejected with `ERR_COPY_NOT_AVAILABLE` (HTTP 409). The member's count of currently `ACTIVE` or `OVERDUE` loans must be strictly below their `max_active_loans`, or the checkout is rejected with `ERR_LOAN_LIMIT_EXCEEDED` (HTTP 409). And the member's `outstanding_balance_cents` must be strictly below the suspension threshold of 2000 cents at checkout time; a member at or above that balance is refused with `ERR_BALANCE_LIMIT_EXCEEDED` (HTTP 402). Among the checkout guards the order is: member-active state, then copy availability, then the loan-limit quota, then the fiscal balance check, and finally the stale-version concurrency check that carries `ERR_STALE_VERSION`.

A loan may be renewed by the owning member, a volunteer, or a coordinator, forming a cyclic `ACTIVE → ACTIVE` loop that pushes the return date out. A renewal advances `due_date` by another `loan_period_days` and increments `renewals_used` by one. Renewal is permitted only when three conditions all hold: the loan is still `ACTIVE` and has not yet slipped to `OVERDUE` (otherwise `ERR_LOAN_NOT_ACTIVE`, HTTP 409); `renewals_used` is strictly less than the item's `max_renewals` (otherwise `ERR_RENEWAL_LIMIT_EXCEEDED`, HTTP 409); and there is no `PENDING` or `PROMOTED` hold waiting on the loan's item, since renewing would be unfair to those waiting (otherwise `ERR_RENEWAL_BLOCKED_WAITLIST`, HTTP 409). The renewing member must also be `ACTIVE` (`ERR_MEMBER_NOT_ACTIVE`) and, like checkout, must be below the balance threshold (`ERR_BALANCE_LIMIT_EXCEEDED`).

Overdue and loss are time-driven. During housekeeping, an `ACTIVE` loan whose `due_date` has passed the current logical clock transitions to `OVERDUE`, and the run creates (or keeps) an `ACCRUING` `LATE` fee whose amount is recomputed against the clock. An `OVERDUE` loan that has been overdue for at least the loss threshold of 30 days transitions to `LOST`: its copy is `RETIRED`, its `ACCRUING` late fee is finalized to `PENDING`, and a `REPLACEMENT` fee is assessed via the depreciation calculation of §3.5.

### 3.5. Returns, Condition, and Damage Charges

A `Volunteer` or `Coordinator` checks a loan back in by supplying a `return_condition`, one of `GOOD`, `MINOR_DAMAGE`, `MAJOR_DAMAGE`, or `LOST`. Return is permitted only when the loan is `ACTIVE` or `OVERDUE` (otherwise `ERR_LOAN_NOT_ACTIVE`). On checkin the loan's `status` becomes `RETURNED`, `returned_at` is stamped from the logical clock, and any `ACCRUING` late fee on the loan is finalized to `PENDING` with its amount frozen as described in §3.6.

What happens to the copy depends on the reported condition. A `GOOD` return moves the copy from `ON_LOAN` back to `AVAILABLE`, recomputes the item's counts, and — because a copy just freed up — may promote the item's next waiting hold. A `MINOR_DAMAGE` or `MAJOR_DAMAGE` return leaves the copy `AVAILABLE` on the availability axis but drops its condition from `GOOD` to `NEEDS_MAINTENANCE`, so it is excluded from `available_copies_count` until repaired; the system auto-opens a `MaintenanceTicket` (with `reason` of `DAMAGE`, `source` of `DAMAGE_INTAKE`, and a `severity` derived from the reported damage) and assesses a damage charge. A `LOST` return retires the copy outright — condition `RETIRED` — and assesses a replacement charge. In every non-`GOOD` case the item's derived counts are recomputed, and if the resulting fee finalization pushes the member's `outstanding_balance_cents` to at least 2000 cents, the member is suspended per §3.1.

**Damage and replacement pricing.** The charge amount rests on a depreciated replacement value. First compute the copy's age in whole years as the number of full 365-day spans between the copy's `acquired_on` and the observation instant (the loan's `returned_at`, or the housekeeping instant for a loss declaration), discarding any partial year. The per-year depreciation is the item's `replacement_value_cents` multiplied by the annual depreciation rate of 10 percent, rounded half up to whole cents. The depreciated value is then the `replacement_value_cents` minus that rounded per-year depreciation multiplied by the age in years — the rounding of the per-year amount happens first, then the multiplication by age, then the subtraction, in that pinned order. Separately, a salvage floor is the `replacement_value_cents` multiplied by 20 percent, rounded half up to whole cents. The full replacement charge is the larger of the depreciated value and the salvage floor.

From that full replacement figure the two damage variants diverge. A `MINOR_DAMAGE` return is billed as a repair: its `amount_cents` is the smaller of the flat repair charge of 1500 cents and the full replacement figure, and the resulting fee's `fee_type` is `DAMAGE`. A `MAJOR_DAMAGE` return, a `LOST` return, and a housekeeping loss declaration are all billed at the full replacement figure itself, and the resulting fee's `fee_type` is `REPLACEMENT`. In all cases the amount is integer cents.

### 3.6. Late Fees, Overdue Accrual, and Finalization

A late fee has two lives. While a loan is `OVERDUE` and not yet returned, its `LATE` fee stays in `ACCRUING` status and is recomputed on every housekeeping run against the current clock, so the amount grows as time passes. When the loan is returned or declared lost, the same computation is evaluated one last time — against `returned_at`, or the housekeeping instant for a loss — and the amount is frozen as the fee moves to `PENDING`.

The amount is computed as follows. The number of whole days overdue is the floor of the elapsed seconds between the loan's `due_date` and the observation instant divided by 86,400 (the seconds in a day). Billable days are the days overdue reduced by a grace period of 2 days, but never less than zero. The raw fee is the item's `daily_late_fee_cents` multiplied by the billable days. The final `amount_cents` is capped at the item's `replacement_value_cents` — that is, the smaller of the raw fee and the replacement value — so a late fee can never exceed the cost of simply replacing the item. A fee's `fee_type` for this charge is `LATE`, and its `status` is one of `ACCRUING`, `PENDING`, `PAID`, or `WAIVED`; `LATE` fees begin `ACCRUING` while damage and replacement fees are created directly in `PENDING`. Each fee records the `member_id` charged, the originating `loan_id` (absent for a manually raised fee), and the `assessed_at` instant it was first created.

### 3.7. Holds and the Waitlist

When every serviceable copy of an item is spoken for, a `Member` may join the item's waitlist by naming their own `member_id` and the `item_id`. Two conditions gate joining. The item must currently have zero `AVAILABLE` serviceable copies — if a lendable copy exists right now, joining is refused with `ERR_COPY_AVAILABLE_NO_HOLD` (HTTP 409), since the member should simply reserve or borrow it. And the member must not already hold a `PENDING` or `PROMOTED` hold on the same item; a second hold is rejected with `ERR_DUPLICATE_HOLD` (HTTP 409). The member must be `ACTIVE`, and their count of currently `PENDING` or `PROMOTED` holds must be strictly below their `max_active_holds`, or the request is refused with `ERR_HOLD_LIMIT_EXCEEDED` (HTTP 409). A new hold starts in `PENDING` status — one of `PENDING`, `PROMOTED`, `FULFILLED`, or `EXPIRED` — and the item's `waitlist_length` is recomputed.

Promotion is chronological. Whenever a copy of the item becomes `AVAILABLE` — through a good checkin, a reservation cancel or expiry, a maintenance return-to-service, or a donation acceptance — the system considers the item's `PENDING` holds whose member is currently `ACTIVE`, and if that candidate set is non-empty it promotes the single earliest one ordered by `created_at` ascending; `created_at` is the sole ordering key and the resource `id` is never used to break ties. If no such candidate exists, the freed copy simply stays `AVAILABLE` and no promotion occurs. Promoting a hold mints a new `Reservation` with `source` `WAITLIST_PROMOTION` that assigns the now-available copy (moving it from `AVAILABLE` to `RESERVED`), sets the hold's `claim_deadline` to the promotion instant plus the configured claim window, records the new reservation's identifier on the hold's `promoted_reservation_id`, and moves the hold to `PROMOTED`.

A promoted hold resolves in one of two ways, and any single hold — addressable by its `hold_id` — may be retrieved for inspection. If the member checks out against the promoted reservation, the hold moves to `FULFILLED`. If the member lets the claim lapse, the next housekeeping run past the hold's `claim_deadline` moves the hold to `EXPIRED`, cancels the promoted reservation (releasing its copy from `RESERVED` back to `AVAILABLE`), and the resulting free copy drives promotion of the next `PENDING` hold in line. A `PENDING` hold whose member is suspended or expires is moved directly to `EXPIRED` as part of that member's cascade.

### 3.8. Maintenance and Retirement

Copies needing service are tracked by `MaintenanceTicket` records. A `Volunteer` or `Coordinator` opens a ticket by naming the `copy_id` and a `reason` of `DAMAGE`, `ROUTINE`, or `INSPECTION`, with an optional `severity` of `MINOR` or `MAJOR` (used when the reason is `DAMAGE`) and an optional planned window given by `scheduled_start` and `scheduled_end`. A ticket records its `source` — `MANUAL` when opened by hand, or `DAMAGE_INTAKE` when auto-created at a damaged checkin — and its `status`, one of `OPEN`, `IN_PROGRESS`, or `RESOLVED`. A manually opened ticket starts `OPEN`; if it represents immediate service, the copy's condition moves from `GOOD` to `NEEDS_MAINTENANCE`. A planned maintenance window must not overlap the copy's active loan period, and the loan period is widened by a buffer of the configured buffer days on each side (a closed interval plus buffer); an overlapping window is rejected with `ERR_MAINTENANCE_WINDOW_CONFLICT` (HTTP 409).

Tickets advance through service. During housekeeping, an `OPEN` ticket whose `scheduled_start` has been reached moves to `IN_PROGRESS` and drives the copy's condition to `UNDER_MAINTENANCE`, refreshing the item's `maintenance_count`. A `Volunteer` or `Coordinator` resolves a ticket — identified by its `ticket_id` — that is `OPEN` or `IN_PROGRESS` by supplying an `outcome`. An outcome of `RETURN_TO_SERVICE` returns the copy to `GOOD` on the condition axis and `AVAILABLE` on the availability axis, recomputes the item's counts, and — because a serviceable copy just reappeared — may promote the next waiting hold. An outcome of `SCRAP` retires the copy to `RETIRED`, shrinking the serviceable pool and recomputing `serviceable_copies_count` and `available_copies_count`. Resolving a ticket that is already `RESOLVED` is rejected as an invalid state transition with `ERR_INVALID_STATE` (HTTP 409). The condition axis may also reach `RETIRED` when a maintenance resolution scraps a copy, when housekeeping declares an overdue loan `LOST`, or when a copy is returned `LOST`.

### 3.9. Fee Settlement and Usage Reporting

Fees are settled two ways, each acting on a specific fee identified by its `fee_id`. Any member (their own fee only), volunteer, or coordinator may pay a `PENDING` fee in full; payment moves the fee to `PAID`, subtracts its `amount_cents` from the member's `outstanding_balance_cents`, and adds it to `total_paid_cents`, keeping the ledger conserved. Paying a fee that is not `PENDING` is rejected as an invalid state with `ERR_INVALID_STATE`. Only a `Coordinator` may waive a fee, optionally recording a `reason`; a waiver may act on an `ACCRUING` or `PENDING` fee, moves it to `WAIVED`, subtracts its `amount_cents` from the member's `outstanding_balance_cents`, and adds it to `total_waived_cents`. Because both settlement paths reduce the outstanding balance, clearing a suspended member's balance to zero is what makes them eligible for reinstatement on the next housekeeping run.

A `Coordinator` may pull a usage report over an optional window and category. The window is the inclusive range from `from_date` to `to_date`, defaulting to the beginning of time through the current logical clock when a bound is omitted, and an optional `category` narrows the loan tallies. The report returns, in `loans_by_category`, the count of loans per category whose `checked_out_at` falls inside the window; `active_loans`, the count of loans whose status is `ACTIVE` or `OVERDUE`; `overdue_loans`, the count of loans whose status is `OVERDUE`; `fees_collected_cents`, the sum of `amount_cents` across `PAID` fees whose `assessed_at` falls inside the window; and `copies_retired`, the count of copies whose condition is `RETIRED`.

## 4. Endpoint Definitions

Endpoints that create a brand-new resource return `201 Created`; endpoints that modify, transition, or act upon an existing resource return `200 OK`. Request and response payloads are not repeated here — the fields each operation reads and writes are described in the §3 narratives above.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/library/members` | Register a member (starts ACTIVE) | Coordinator |
| GET | `/library/members/{member_id}` | Get a member | Member, Volunteer, Coordinator |
| POST | `/library/volunteers` | Create a volunteer/staff record | Coordinator |
| POST | `/library/items` | Create a catalog item | Coordinator |
| GET | `/library/items/{id}` | Get an item with derived counts and version | Member, Volunteer, Coordinator |
| POST | `/library/items/{id}/copies` | Add a physical copy to an item | Volunteer, Coordinator |
| GET | `/library/items/{id}/copies` | List copies of an item | Member, Volunteer, Coordinator |
| GET | `/library/copies/{copy_id}` | Get a physical copy | Member, Volunteer, Coordinator |
| POST | `/library/reservations` | Reserve a copy for a window (server assigns a copy) | Member |
| GET | `/library/reservations/{reservation_id}` | Get a reservation | Member, Volunteer, Coordinator |
| GET | `/library/reservations` | List/filter reservations | Member, Volunteer, Coordinator |
| POST | `/library/reservations/{reservation_id}/cancel` | Cancel a PENDING reservation | Member, Volunteer, Coordinator |
| POST | `/library/loans` | Check out a copy (walk-up or fulfilling a reservation) | Volunteer, Coordinator |
| GET | `/library/loans/{loan_id}` | Get a loan | Member, Volunteer, Coordinator |
| GET | `/library/loans` | List/filter loans | Member, Volunteer, Coordinator |
| POST | `/library/loans/{loan_id}/renew` | Renew a loan | Member, Volunteer, Coordinator |
| POST | `/library/loans/{loan_id}/return` | Check in a copy with a condition | Volunteer, Coordinator |
| POST | `/library/holds` | Join the waitlist for an item | Member |
| GET | `/library/holds/{hold_id}` | Get a hold | Member, Volunteer, Coordinator |
| GET | `/library/holds` | List/filter holds | Member, Volunteer, Coordinator |
| GET | `/library/fees/{fee_id}` | Get a fee | Member, Volunteer, Coordinator |
| GET | `/library/fees` | List/filter fees | Member, Volunteer, Coordinator |
| POST | `/library/fees/{fee_id}/pay` | Pay a PENDING fee in full | Member, Volunteer, Coordinator |
| POST | `/library/fees/{fee_id}/waive` | Waive a fee | Coordinator |
| POST | `/library/donations` | Record a donation offer | Member, Volunteer, Coordinator |
| GET | `/library/donations/{donation_id}` | Get a donation | Volunteer, Coordinator |
| GET | `/library/donations` | List/filter donations | Volunteer, Coordinator |
| POST | `/library/donations/{donation_id}/accept` | Accept a donation and mint a copy | Volunteer, Coordinator |
| POST | `/library/donations/{donation_id}/reject` | Reject a donation offer | Volunteer, Coordinator |
| POST | `/library/maintenance-tickets` | Open a maintenance ticket for a copy | Volunteer, Coordinator |
| GET | `/library/maintenance-tickets/{ticket_id}` | Get a maintenance ticket | Volunteer, Coordinator |
| GET | `/library/maintenance-tickets` | List/filter maintenance tickets | Volunteer, Coordinator |
| POST | `/library/maintenance-tickets/{ticket_id}/resolve` | Resolve a ticket (return to service or scrap) | Volunteer, Coordinator |
| GET | `/library/reports/usage` | Usage report | Coordinator |
| POST | `/library/_clock/set_current_utc` | Set the logical clock | Coordinator |
| POST | `/library/_ops/run` | Run the housekeeping batch | Coordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_FORBIDDEN_NOT_OWNER` | 403 Forbidden |
| `ERR_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_COPY_NOT_FOUND` | 404 Not Found |
| `ERR_RESERVATION_NOT_FOUND` | 404 Not Found |
| `ERR_LOAN_NOT_FOUND` | 404 Not Found |
| `ERR_HOLD_NOT_FOUND` | 404 Not Found |
| `ERR_FEE_NOT_FOUND` | 404 Not Found |
| `ERR_DONATION_NOT_FOUND` | 404 Not Found |
| `ERR_TICKET_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INVALID_ENUM` | 400 Bad Request |
| `ERR_INVALID_WINDOW` | 400 Bad Request |
| `ERR_MEMBER_NOT_ACTIVE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_LOAN_NOT_ACTIVE` | 409 Conflict |
| `ERR_COPY_NOT_AVAILABLE` | 409 Conflict |
| `ERR_NO_COPY_AVAILABLE` | 409 Conflict |
| `ERR_ITEM_NO_CAPACITY_FOR_WINDOW` | 409 Conflict |
| `ERR_MAINTENANCE_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_LOAN_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_HOLD_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_RENEWAL_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_RENEWAL_BLOCKED_WAITLIST` | 409 Conflict |
| `ERR_DUPLICATE_HOLD` | 409 Conflict |
| `ERR_COPY_AVAILABLE_NO_HOLD` | 409 Conflict |
| `ERR_BALANCE_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
