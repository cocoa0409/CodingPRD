# Restaurant POS — Product Requirements Document

## 1. Introduction

This document specifies the API for a full-service restaurant point-of-sale and table-management platform. The system is the operational backbone of a single dining room: it tracks every party from the moment they are quoted at the door, through seating and ordering, to the final settled check and the end-of-day distribution of pooled gratuities. Four distinct front- and back-of-house roles share the floor — a host managing the waitlist and seating, servers running orders and checks for their own tables, kitchen staff working the kitchen-display stream, and a manager owning configuration, comps, voids, and the books — and the API enforces a clean separation of duties between them.

Two characteristics make the domain demanding. First, money is computed twice: a **provisional** subtotal moves live as items are fired, voided, and comped while a check is still open, and a **final** subtotal is locked when the bill is presented by re-deriving every line's price from the happy-hour schedule. The two are usually equal, but the platform must compute each independently and never confuse one for the other. Second, the floor is a web of cascades — clearing a seating frees a table, bussing that table promotes the head of the waitlist onto it, voiding an item restores the portion count it consumed, and closing a check feeds the day's tip pool. Each cascade must complete atomically within the request that triggers it.

All amounts in this system are integer cents and all rates are expressed in basis points, so the platform never performs floating-point money arithmetic. Time is governed by a per-restaurant server clock that test harnesses advance explicitly, which lets happy-hour pricing and shift-overlap logic be exercised deterministically.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request other than the two bootstrap operations — creating a restaurant and setting a restaurant's clock — must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is missing or blank on a protected endpoint, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If both headers are present but the role named in `X-User-Role` is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly four roles, spelled precisely as follows: `Manager`, `Server`, `Host`, and `KitchenStaff`. These are peer roles — no role is a superset of another. A `Manager` owns back-of-house authority: menu, schedule, table, and staff configuration; comps; item, check, and payment voids; and tip-pool distribution. A `Server` owns the order workflow for checks: courses, items, modifiers, firing, presenting, reopening, closing, splitting, and tendering payments. A `Host` owns the front of house: the waitlist, seating, clearing, and bussing. `KitchenStaff` owns the kitchen-display action of marking a fired item served. All four roles may issue read (GET) requests against the endpoints enumerated in §4.

Role identity binds to `X-User-ID` as follows. When `X-User-Role` is `Server`, `X-User-ID` is the `id` of the acting `StaffMember`; ownership checks on any resource that references a `StaffMember` compare that resource's staff foreign-key field to `X-User-ID`. When `X-User-Role` is `Manager`, `Host`, or `KitchenStaff`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it against any entity's `id`.

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

All list endpoints accept two optional query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, has a minimum of 1, and a maximum of 100; a requested limit above the maximum is capped at 100. The `offset` parameter defaults to 0 and has a minimum of 0. List results are ordered by `created_at` ascending unless a specific endpoint's narrative states otherwise. The `meta` block of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` reflects the full size of the filtered set before pagination and `has_more` indicates whether additional records remain beyond the current page.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource is assigned a server-minted `id` formatted as a UUID with no type prefix, and every resource records a `created_at` timestamp as an ISO 8601 UTC value with three fractional digits. Most resources additionally carry an `updated_at` timestamp and an integer `version`: `updated_at` is refreshed on every mutation, and `version` starts at its initial value and increments by one on each mutation. These mutation semantics apply even when only a computed field changes — for example, when an item void revises a check's `provisional_subtotal_cents`, the check's `updated_at` advances and its `version` increments.

Two entities are immutable line-detail records and therefore carry only `id` and `created_at`, with no `updated_at` and no `version`: the **item modifier** and the **tip allocation**. Every other entity in the system carries the full `id`, `created_at`, `updated_at`, and `version` set.

The server clock referenced throughout this document, `current_utc`, is a per-restaurant value. It is initialized to the Unix epoch when a restaurant is created and only ever advances when an operator explicitly sets it. Every system-assigned timestamp in the system — a seating's `seated_at`, a course's `fired_at`, a waitlist entry's `quoted_at`, and so on — is read from `current_utc` at the moment of the triggering operation, and all happy-hour evaluation reads from it as well.

### 2.5. Monetary and Time Units, Precision, and Rounding

All monetary values are stored and returned as integer cents; the system performs no floating-point money arithmetic. Rates are expressed in basis points, where 10000 basis points equal 100 percent — so a value of 875 means 8.75 percent and a value of 2000 means 20 percent. Whenever a basis-point rate is applied to a cent amount, the result is rounded to a whole cent using the round-half-up convention (a fractional remainder of exactly one-half rounds up). Tax and auto-gratuity are each rounded half-up independently of one another. Where a calculation specifies flooring rather than rounding — as the tip-pool and check-split allocations do — the floor is taken first and any leftover cent is redistributed exactly as that calculation's narrative directs, so that the parts always sum back to the whole with no drift.

Several time values are expressed as **minutes after midnight** in the range 0 to 1440: happy-hour window bounds and staff clock-in and clock-out marks all use this convention. Weekdays use the ISO numbering where 1 is Monday and 7 is Sunday.

### 2.6. Filtered-List Retrieval and Reference Validation

The system uses a flat resource topology: every collection lives at its own root path and cross-entity relationships are expressed through foreign-key fields on the request body, never through nested URL paths. A child resource is therefore reached not by path nesting but by a filtered list — for example, the courses of a check are retrieved by listing courses filtered on `check_id`, and the order items of a course by listing order items filtered on `course_id`. List endpoints accept the filter parameters named in their §4 description, including `restaurant_id`, `status`, `table_id`, `seating_id`, `waitlist_entry_id`, `check_id`, `server_staff_id`, `course_id`, `menu_item_id`, `order_item_id`, `staff_id`, `business_date`, `tip_pool_id`, and `staff_shift_id` where applicable.

When a request references resources by identifier — whether a path identifier or a foreign key in the body — each referenced resource must exist. References are validated left to right in the order they appear, and the first identifier that resolves to no existing resource causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404) before any later reference is checked. Once existence is confirmed, the body itself is validated: every required field must be present and well-typed and every enum-valued field must carry a legal value, failing which the request is rejected with `ERR_INVALID_REQUEST` (HTTP 422).

### 2.7. Validation Ordering

When several checks could fail on one request, the system evaluates them in a fixed priority order and returns the first failure encountered. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN`), then existence of every referenced resource (`ERR_NOT_FOUND`), then request-body well-formedness and enum legality (`ERR_INVALID_REQUEST`), then whether the target resource is in a state from which the requested transition is legal (`ERR_INVALID_STATE`, HTTP 409), and then — on the one operation it guards — the optimistic-concurrency version check (`ERR_STALE_TABLE_VERSION`, HTTP 412). Business rules are evaluated only after all of the foregoing pass; among the business rules, the domain-specific orderings called out in §3 apply.

### 2.8. Occupancy Cascades and Atomic Consistency

The floor's physical state is held in a single chain of cascading effects, and every link in a cascade completes within the response of the request that triggers it. Clearing a seating frees its table to a soiled state; bussing that table both returns it to service and, in the same atomic operation, promotes the head of the waitlist onto it, seats that party, and marks the table occupied again. Likewise, voiding a fired item restores the menu portions it had consumed, and closing a check contributes its tip to the day's pool. None of these secondary effects is deferred; a reader of any entity immediately after a triggering request sees the fully settled result. The precise transition pairs, preconditions, and downstream effects of each cascade are specified in §3.

### 2.9. Optimistic Concurrency on Table Bussing

Bussing a soiled table is the one operation in this system guarded by optimistic concurrency control, because the act of bussing also claims the freed table for the head of the waitlist — a create-with-supersede that must not run against a stale view of the table. The buss request therefore requires a non-optional `expected_table_version` field carrying the client's last observed `version` of the target `DiningTable`. If `expected_table_version` does not equal the table's current `version` — meaning another writer has advanced the table since the client read it, for instance by already bussing and re-seating it — the request is rejected with `ERR_STALE_TABLE_VERSION` (HTTP 412), and no promotion occurs. No other endpoint in the system accepts or requires a version field.

## 3. Business Logic & Workflows

### 3.1. Provisioning the Restaurant, Menu, and Happy-Hour Schedule

Everything begins with a restaurant, created by a `Manager` who supplies its `name` and a sales-tax rate `tax_rate_bps` (between 0 and 2000 basis points). The creator may also override four pricing-policy defaults: `large_party_threshold`, the party size at or above which auto-gratuity applies, which defaults to 8 and must be at least 2; `auto_gratuity_bps`, the gratuity rate for large parties, defaulting to 2000 and capped at 5000; `comp_cap_bps`, the ceiling on total comps for one check as a fraction of its pre-comp subtotal, defaulting to 10000 (one hundred percent) and never above 10000; and `min_rest_minutes`, the minimum rest gap between two shifts of the same staff member, defaulting to 0 and never negative. A newly created restaurant's `current_utc` is the epoch until advanced.

Because happy-hour pricing and all timestamps key off the clock, a `Manager` advances a restaurant's clock through a dedicated test-driving capability that names the target restaurant via `restaurant_id` and supplies the new instant as `to_iso8601`; this writes `current_utc` and returns the restaurant. This is one of the two bootstrap operations exempt from the authentication header requirement.

A `Manager` populates the menu. Each menu item belongs to a restaurant via `restaurant_id` and carries a `name`, a kitchen-routing `station` that is one of `GRILL`, `FRY`, `SAUTE`, `COLD`, `BAR`, or `EXPO`, a regular `base_price_cents` (zero or more), and a `happy_hour_price_cents` that must be at least zero and no greater than `base_price_cents`. The menu item also defines its starting eighty-six count through `initial_available_count` (zero or more), which seeds the live `available_count`. The computed flag `is_86` is true exactly when `available_count` reaches zero. The conserved invariant for portions is that `available_count` plus the total `quantity` across all of this menu item's order items that are currently fired, served, or comped always equals `initial_available_count`.

To configure discounts, a `Manager` creates happy-hour windows. Each window cites its `restaurant_id`, a `day_of_week` from 1 (Monday) through 7 (Sunday), and a half-open minute span: `start_minute` is the inclusive lower bound and `end_minute` the exclusive upper bound, both in minutes after midnight, with `start_minute` strictly less than `end_minute` and `end_minute` no greater than 1440. A course that fires at exactly `end_minute` falls outside the window. A given fire moment is inside a window when there exists a window for the same restaurant whose `day_of_week` equals the weekday of the course's `fired_at`, whose `start_minute` is less than or equal to the minute-of-day of `fired_at`, and whose `end_minute` is strictly greater than that minute-of-day.

### 3.2. The Waitlist and the Door

A `Host` quotes an arriving party by adding it to the waitlist with a `restaurant_id`, the `party_name` it is quoted under, and a `party_size` of at least one. A new entry's `status` is `WAITING` and its `quoted_at` is stamped from `current_utc`; its `seating_id` remains null until it is promoted. The `quoted_at` value is the FIFO ordering key for promotion: among eligible waiting parties the earliest `quoted_at` is served first, with `created_at` ascending as the tie-break.

While a party is still `WAITING`, a `Host` may cancel it, moving its `status` to `CANCELLED`. Cancellation is legal only from `WAITING`; attempting it from any other state is rejected with `ERR_INVALID_STATE`. A waiting party leaves the queue in one of two terminal ways: cancelled, or seated. The promotion path — `WAITING` to `PROMOTED` to `SEATED` — is driven entirely as a side effect of freeing a table, described in §3.3, or by a host directly seating the party. When listing the waitlist, a `Host` or `Manager` may filter by `restaurant_id`, by `status`, and by `seating_id`.

### 3.3. Tables, Seatings, and the Clear–Free–Promote Cascade

A `Manager` creates dining tables, each with a `restaurant_id`, a `table_number` that is unique within its restaurant, and a `capacity` of at least one. A table's `occupancy_status` begins at `AVAILABLE` and moves through `SEATED` while occupied, to `DIRTY` once its seating is cleared but before it is bussed, and back to `AVAILABLE` when bussed.

A `Host` seats a party by creating a seating, citing the `restaurant_id`, the `table_id` of the physical table, the `party_size` to be seated, and optionally the `waitlist_entry_id` of a party being seated from the queue (omitted for a walk-in). Seating is permitted only when the table's `occupancy_status` is `AVAILABLE` and no open seating already references that table; otherwise the create is rejected with `ERR_INVALID_STATE`. The seated `party_size` must not exceed the table's `capacity`, and the seating's table must belong to the same restaurant as the seating — a violation of the capacity rule is rejected with `ERR_CAPACITY_EXCEEDED` (HTTP 409). A new seating must also not collide on the floor: its occupation interval, the half-open span from `seated_at` up to but not including `cleared_at`, must not overlap any other seating interval on the same table, with no buffer between them; an overlap is rejected with `ERR_TABLE_DOUBLE_BOOKED` (HTTP 409). On success the seating is created with `status` `OPEN`, its `seated_at` stamped from `current_utc` and its `cleared_at` null, the table advances from `AVAILABLE` to `SEATED`, and if a `waitlist_entry_id` was cited that entry becomes `SEATED`.

When the meal ends, a `Host` clears the seating. Clearing is legal only when the seating's `status` is `OPEN` and every check belonging to that seating is already `CLOSED` or `VOID`; otherwise it is rejected with `ERR_INVALID_STATE`. Clearing stamps the seating's `cleared_at` from `current_utc` — closing the half-open occupation interval — moves the seating's `status` from `OPEN` to `CLEARED`, and transitions the owning table from `SEATED` to `DIRTY`. Promotion does not happen here; it happens on the subsequent buss. A `Host`, `Server`, or `Manager` may list seatings filtered by `restaurant_id`, `table_id`, or `waitlist_entry_id`.

Bussing is where the deepest cascade originates, and it is the operation guarded by the version check of §2.9. A `Host` busses a table that is `DIRTY`; the request carries `expected_table_version`, which must match the table's current `version` or the buss is rejected with `ERR_STALE_TABLE_VERSION`. A buss legal only from `DIRTY` (otherwise `ERR_INVALID_STATE`) does three things in one atomic step. First, it returns the table from `DIRTY` to `AVAILABLE` and increments the table's `version` by one. Second, having freed the table, it auto-promotes the head of the waitlist: among `WAITING` entries whose `party_size` is less than or equal to this table's `capacity`, it selects the entry with the earliest `quoted_at` (tie-broken by earliest `created_at`); if such an entry exists, that entry moves from `WAITING` to `PROMOTED`. Third, the promotion creates a new seating with `status` `OPEN` on this table, sets the table's `occupancy_status` back to `SEATED`, records the new seating's id on the entry's `seating_id`, and advances the entry from `PROMOTED` to `SEATED`. If no eligible waiting party exists, the table simply remains `AVAILABLE`.

### 3.4. Building and Firing Courses

A `Server` opens a check on a seating, supplying the `restaurant_id`, the `seating_id`, the `server_staff_id` of the owning server, and the billable `party_size` (copied from the seating but overridable, and at least one). A new check's `status` is `OPEN` with all monetary fields at zero. The `party_size` on the check drives auto-gratuity, as described in §3.6.

Within an open check, the `Server` structures the meal into courses. Each course cites its `restaurant_id`, its `check_id`, and a `course_number` of at least one that sets coursing order — appetizers as 1, entrées as 2, and so on, with lower numbers intended to fire first. A new course's `status` is `BUILDING` and its `fired_at` is null. The `Server` adds order items to a building course, each citing `restaurant_id`, the `course_id`, the `menu_item_id` ordered, and a `quantity` of at least one; a new item's `status` is `PENDING`. The `Server` may attach modifiers to an item — each modifier supplies `restaurant_id`, the `order_item_id` it decorates, a `name` such as "extra cheese" or "no onions", and a per-portion `surcharge_cents` of zero or more (zero for a free modifier).

Firing a course sends it to the kitchen and is legal only when the course's `status` is `BUILDING`, its owning check's `status` is `OPEN`, and the course holds at least one `PENDING` order item — a course with no pending items cannot fire and is rejected with `ERR_EMPTY_COURSE` (HTTP 409). The eighty-six guard is also evaluated at fire: for every `PENDING` item in the course, the corresponding menu item's `available_count` must be at least that item's `quantity`; if any item would drive a count below zero, the entire fire is rejected with `ERR_ITEM_86` (HTTP 409) and nothing changes. On a successful fire, the course's `fired_at` is stamped from `current_utc` and its `status` moves from `BUILDING` to `FIRED`. Each `PENDING` item in it transitions to `FIRED`; its per-portion price `unit_price_cents` is snapshotted at this instant as `happy_hour_price_cents` if `fired_at` falls inside an active happy-hour window for the restaurant (per §3.1) and `base_price_cents` otherwise; its `line_subtotal_cents` is computed as `quantity` times that snapshotted unit price plus `quantity` times the sum of its modifiers' `surcharge_cents`; and the menu item's `available_count` is decremented by `quantity` with `is_86` recomputed. Finally the owning check's `provisional_subtotal_cents` is recomputed. A `Server`, `Manager`, or `KitchenStaff` may list courses filtered by `restaurant_id` and `check_id`, and list order items filtered by `restaurant_id`, `course_id`, `menu_item_id`, and `status` — the latter is how the kitchen display pulls its station-routed stream.

### 3.5. The Kitchen Display: Serving, Voiding, and Comping

Once an item is `FIRED`, it forks three ways, and the three branches diverge sharply in their side effects.

The first branch is service. `KitchenStaff` mark a fired item done, moving it from `FIRED` to `SERVED`. This is purely a status change — no pricing recomputation, no portion restoration — legal only when the item's `status` is `FIRED`.

The second branch is the void, performed by a `Manager`. An item may be voided either from `FIRED` or from `SERVED`, and in both cases the precondition is identical: the item is in the respective state and its owning check is `OPEN` or `PRESENTED`. Voiding is the compensating action for the eighty-six count: it restores the menu item's `available_count` by the item's `quantity`, recomputes `is_86`, sets the item's `status` to `VOIDED`, and recomputes the owning check's `provisional_subtotal_cents` so the line drops out of the gross subtotal entirely. The void from `FIRED` and the void from `SERVED` are specified identically here precisely because they behave identically.

The third branch is the comp, also a `Manager` action, and it is deliberately not a void. An item may be comped from `FIRED` or from `SERVED`; the precondition in both cases is that the item is in the respective state, its owning check is `OPEN` or `PRESENTED`, and the resulting comp would not breach the comp cap. Comping sets the item's `comp_amount_cents` to its full `line_subtotal_cents`, moves its `status` to `COMPED`, and recomputes the owning check's `comp_total_cents` and the downstream auto-gratuity, tax, and total. Crucially, a comp does **not** restore `available_count` — the portion was prepared and consumed, so it stays decremented. This is the one substantive difference between a comp and a void: the void restores the count and removes the line from the subtotal, while the comp leaves the count consumed, keeps the line in the gross subtotal, and instead subtracts it through `comp_total_cents`. The comp-from-`FIRED` and comp-from-`SERVED` cases are governed by the identical rule stated here.

The comp cap is a fiscal guard. The total of all comps on a check, `comp_total_cents`, may never exceed `comp_cap_bps` of the check's pre-comp subtotal; concretely the cap is the pre-comp subtotal multiplied by `comp_cap_bps` divided by 10000 and floored to a whole cent. A comp whose addition would push `comp_total_cents` above that cap is rejected with `ERR_COMP_CAP_EXCEEDED` (HTTP 409).

### 3.6. Provisional and Final Pricing, Comps, Gratuity, and Tax

The provisional subtotal is the live figure that moves while a check is open, recomputed on every line change — each course fire, each item void, and each item comp. It is the gross sum, computed per line and then totaled in that pinned order: for each order item on the check whose `status` is `FIRED`, `SERVED`, or `COMPED`, the line value is `quantity` times the item's snapshotted `unit_price_cents` plus `quantity` times the sum of that item's modifiers' `surcharge_cents`; these per-line integer-cent values are summed into `provisional_subtotal_cents`. Comped lines are included at their gross value here — the comp deduction is handled separately through `comp_total_cents`. Voided lines and not-yet-fired pending lines are excluded. The provisional pass trusts the `unit_price_cents` snapshot taken at fire time and does not re-consult the happy-hour schedule.

The final subtotal is computed and locked when the bill is presented and recomputed at close. It re-derives each line's price rather than trusting the snapshot. Courses on the check that are `FIRED` are processed in order of `fired_at` ascending, with `created_at` ascending as the tie-break; for each such course the system re-evaluates whether its `fired_at` falls inside an active happy-hour window for the restaurant. For every order item in that course whose `status` is `FIRED`, `SERVED`, or `COMPED`, the per-line price is `happy_hour_price_cents` if the course is in-window and `base_price_cents` otherwise; the line value is `quantity` times that price plus `quantity` times the sum of the item's modifiers' `surcharge_cents`; and these per-line values are summed, in the identical round-per-line-then-sum order as the provisional pass, into `final_subtotal_cents`. Voided lines are excluded and comped lines are included at gross, exactly as in the provisional pass. The `final_subtotal_cents` field is null until the check is first presented; reopening a presented check clears it back to null.

From whichever subtotal is current — provisional while open, the locked final once presented — the check's downstream money is resolved in a single pinned order, because the figures depend on one another. First the base subtotal is taken. Then `comp_total_cents` is set to the smaller of the sum of `comp_amount_cents` across the check's comped items and the comp cap (the base subtotal times `comp_cap_bps` divided by 10000, floored). Then the comped subtotal is the base subtotal minus `comp_total_cents` — this is the figure both gratuity and tax key off. Then `auto_gratuity_cents` is set: when the check's `party_size` is greater than or equal to the restaurant's `large_party_threshold`, it is the comped subtotal times `auto_gratuity_bps` divided by 10000, rounded half-up; otherwise it is exactly zero. Then `tax_cents` is the comped subtotal times `tax_rate_bps` divided by 10000, rounded half-up, computed independently of gratuity. Finally `total_due_cents` is the comped subtotal plus `tax_cents` plus `auto_gratuity_cents` — the amount the guest owes.

A check carries two further computed money fields fed by payments: `amount_paid_cents` is the sum of `amount_cents` across the check's settled payments, and `tip_cents` is the sum of `tip_cents` across those settled payments.

### 3.7. Presenting, Reopening, Closing, Splitting, and Voiding a Check

Presenting the bill is a `Server` action legal only when the check's `status` is `OPEN` and no course on it is still `BUILDING` — all coursing must have fired. Presenting computes and locks `final_subtotal_cents` and recomputes `comp_total_cents`, `auto_gratuity_cents`, `tax_cents`, and `total_due_cents` on that locked subtotal, moving the check from `OPEN` to `PRESENTED`. The check is cyclic here: a `Server` may reopen a presented check, but only while its `amount_paid_cents` is zero — that is, before any settled payment exists. Reopening moves the check from `PRESENTED` back to `OPEN` and clears `final_subtotal_cents` to null, making the check editable again. An illegal present or reopen is rejected with `ERR_INVALID_STATE`.

Payment is tendered by a `Server`, who creates a payment citing the `restaurant_id`, the `check_id`, the principal `amount_cents` (zero or more, excluding tip), the `tip_cents` paid with it (zero or more), and the `method`, one of `CASH`, `CARD`, or `GIFT`. A new payment's `status` is `SETTLED`, and on creation the owning check's `amount_paid_cents` and `tip_cents` are recomputed. A `Manager` may void a settled payment, but only while the owning check is `OPEN` or `PRESENTED` — never on a closed check; voiding moves the payment from `SETTLED` to `VOIDED` and recomputes the check's `amount_paid_cents` and `tip_cents` so the reversed payment drops out.

Closing is a `Server` action legal only when the check is `PRESENTED` and fully tendered — its `amount_paid_cents` must be greater than or equal to its `total_due_cents`, failing which it is rejected with `ERR_UNDERPAID` (HTTP 409). Closing moves the check from `PRESENTED` to `CLOSED` and contributes the check's `tip_cents` to the tip pool for the close-day business date: the relevant pool is located (or created if none exists yet) and its `pooled_cents` is increased by the check's `tip_cents`. Once every check on a seating is `CLOSED` or `VOID`, the seating becomes eligible to be cleared.

A `Manager` may void an entire check while it is `OPEN` or `PRESENTED`, provided its `amount_paid_cents` is zero. Voiding moves the check to `VOID` and, as a cascade, voids every order item on the check that is not already voided, restoring each affected menu item's `available_count` by the voided quantity — the same compensating restore that a single item void performs.

Finally, a `Server` may split a check evenly into child checks. The split count `n` must satisfy two-or-more and at most the check's `party_size`; a count outside that range is rejected with `ERR_INVALID_SPLIT` (HTTP 422). An even split divides the parent's `total_due_cents` by `n` using integer division to get each child's base amount, computes the leftover remainder as `total_due_cents` minus that base times `n`, and assigns one extra cent to each of the first `remainder` children in creation order, so that the children's amounts sum exactly to the parent's `total_due_cents` with no drift.

### 3.8. Staff, Shifts, and End-of-Day Tip Pooling

A `Manager` registers staff members, each with a `restaurant_id`, a `name`, a `role` that is one of `SERVER`, `BARTENDER`, or `BUSSER`, and a `tip_weight_bps` of zero or more that sets the member's relative weight under role-weighted distribution. A `Manager` then clocks a staff member onto a shift, supplying the `restaurant_id`, the `staff_id`, the `business_date` as a YYYY-MM-DD string that bins the shift into a day's pool, and the closed interval of the shift as `clock_in_minute` and `clock_out_minute` (minutes after midnight, with the in-mark strictly before the out-mark and the out-mark no greater than 1440). The shift's `hours_worked_x100` is computed as the duration in minutes — `clock_out_minute` minus `clock_in_minute` — multiplied by 100 and divided by 60, rounded half-up to an integer; this is the hours basis, scaled by one hundred, used for tip distribution. A new shift must not collide with another shift of the same staff member on the same business date: each shift's closed interval is expanded by `min_rest_minutes` on each side, and if that expanded interval touches or overlaps another shift of the same member that day, the new shift is rejected with `ERR_SHIFT_OVERLAP` (HTTP 409). A `Manager` may list shifts filtered by `restaurant_id`, `staff_id`, and `business_date`.

Tips accumulate into a tip pool, which a `Manager` creates for a `restaurant_id` and a `business_date` (unique per restaurant and date) with an optional `distribution_mode` that is `EVEN_BY_HOURS` (the default) or `WEIGHTED_BY_ROLE`. A new pool's `status` is `ACCUMULATING` with `pooled_cents` at zero; its `pooled_cents` is the running sum of `tip_cents` over closed, non-void checks whose close fell on its business date, and `distributed_cents` is zero until distribution. The pool's `status` becomes `DISTRIBUTED` — a terminal state — once it is paid out.

Distribution is a `Manager` action legal only when the pool's `status` is `ACCUMULATING`, at least one staff shift exists for the pool's `restaurant_id` and `business_date`, and `pooled_cents` is greater than zero; a pool with no eligible tips or no shifts that day cannot distribute and is rejected with `ERR_POOL_EMPTY` (HTTP 409). Distribution computes one tip allocation per staff shift on the pool's business date, each citing the `restaurant_id`, the `tip_pool_id`, the `staff_shift_id` it credits, and the `amount_cents` it pays. The shifts are taken in `created_at` ascending order, and each shift receives a weight: under `EVEN_BY_HOURS` the weight is the shift's `hours_worked_x100` alone, while under `WEIGHTED_BY_ROLE` the weight is the shift's `hours_worked_x100` multiplied by the staff member's `tip_weight_bps` — so two staff who worked identical hours can be paid differently. Each shift's raw share is `pooled_cents` times its weight divided by the sum of all weights; each raw share is floored to a whole cent; the leftover remainder, `pooled_cents` minus the sum of the floors, is then handed out one cent at a time to shifts in descending order of the fractional part of their raw share, with `created_at` ascending as the tie-break (never the id). After distribution the pool's `distributed_cents` is set to the sum of all allocation `amount_cents`, which must equal `pooled_cents` exactly, and the pool's `status` becomes `DISTRIBUTED`. A `Manager` may list tip pools by `restaurant_id` and `business_date`, and tip allocations by `restaurant_id`, `tip_pool_id`, and `staff_shift_id`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that read a resource or drive a state transition or other modification return `200 OK`. All endpoints emit the standard envelope of §2.2 and, except for the two bootstrap operations noted in §2.1, require the `X-User-ID` and `X-User-Role` headers.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/restaurants` | Create the restaurant and its pricing config | Manager |
| GET | `/restaurants/{id}` | Read a restaurant and its pricing config | Manager, Server, Host, KitchenStaff |
| POST | `/_clock/set_current_utc` | Set the restaurant's server clock | Manager |
| POST | `/menu-items` | Create a menu item with station, prices, and 86-count | Manager |
| GET | `/menu-items/{id}` | Read a menu item including live count and 86 flag | Manager, Server, Host, KitchenStaff |
| GET | `/menu-items` | List menu items, filterable by restaurant | Manager, Server, Host, KitchenStaff |
| POST | `/happy-hour-windows` | Create a happy-hour window | Manager |
| GET | `/happy-hour-windows/{id}` | Read a happy-hour window | Manager, Server |
| GET | `/happy-hour-windows` | List happy-hour windows, filterable by restaurant | Manager, Server |
| POST | `/tables` | Create a dining table | Manager |
| GET | `/tables/{id}` | Read a dining table including occupancy and version | Manager, Server, Host |
| GET | `/tables` | List dining tables, filterable by restaurant | Manager, Server, Host |
| POST | `/tables/{id}/buss` | Buss a dirty table; auto-promote the head waitlist entry | Host |
| POST | `/waitlist` | Add a party to the waitlist | Host |
| GET | `/waitlist/{id}` | Read a waitlist entry | Manager, Host |
| GET | `/waitlist` | List waitlist entries, filterable by restaurant, status, seating | Manager, Host |
| POST | `/waitlist/{id}/cancel` | Cancel a waiting entry | Host |
| POST | `/seatings` | Seat a party at a table | Host |
| GET | `/seatings/{id}` | Read a seating including interval and status | Manager, Server, Host |
| GET | `/seatings` | List seatings, filterable by restaurant, table, waitlist entry | Manager, Server, Host |
| POST | `/seatings/{id}/clear` | End a seating; free the table to dirty | Host |
| POST | `/staff-members` | Create a staff member | Manager |
| GET | `/staff-members/{id}` | Read a staff member | Manager, Server |
| GET | `/staff-members` | List staff members, filterable by restaurant | Manager |
| POST | `/staff-shifts` | Clock a staff member onto a shift | Manager |
| GET | `/staff-shifts/{id}` | Read a staff shift | Manager |
| GET | `/staff-shifts` | List staff shifts, filterable by restaurant, staff, date | Manager |
| POST | `/checks` | Open a check on a seating | Server |
| GET | `/checks/{id}` | Read a check including computed totals | Manager, Server |
| GET | `/checks` | List checks, filterable by restaurant, seating, server, status | Manager, Server |
| POST | `/checks/{id}/present` | Present the bill; lock final subtotal and totals | Server |
| POST | `/checks/{id}/reopen` | Reopen a presented check for editing | Server |
| POST | `/checks/{id}/close` | Close a fully tendered check; feed the day's tip pool | Server |
| POST | `/checks/{id}/void` | Void an entire unpaid check; restore item counts | Manager |
| POST | `/checks/{id}/split` | Split a check evenly into n child checks | Server |
| POST | `/courses` | Create a coursing slot on a check | Server |
| GET | `/courses/{id}` | Read a course | Manager, Server, KitchenStaff |
| GET | `/courses` | List courses, filterable by restaurant, check | Manager, Server, KitchenStaff |
| POST | `/courses/{id}/fire` | Fire a course; snapshot prices, decrement counts | Server |
| POST | `/order-items` | Add an item line to a building course | Server |
| GET | `/order-items/{id}` | Read an order item including price snapshot and comp | Manager, Server, KitchenStaff |
| GET | `/order-items` | List order items, filterable by restaurant, course, menu item, status | Manager, Server, KitchenStaff |
| POST | `/order-items/{id}/serve` | Mark a fired item served | KitchenStaff |
| POST | `/order-items/{id}/void` | Void an item; restore its count and drop it from the subtotal | Manager |
| POST | `/order-items/{id}/comp` | Comp an item; lower the comped subtotal | Manager |
| POST | `/item-modifiers` | Attach a modifier to a pending order item | Server |
| GET | `/item-modifiers/{id}` | Read a single item modifier | Manager, Server, KitchenStaff |
| GET | `/item-modifiers` | List modifiers, filterable by restaurant, order item | Manager, Server, KitchenStaff |
| POST | `/payments` | Tender a payment toward a check's total | Server |
| GET | `/payments/{id}` | Read a payment | Manager, Server |
| GET | `/payments` | List payments, filterable by restaurant, check | Manager, Server |
| POST | `/payments/{id}/void` | Void a settled payment on a non-closed check | Manager |
| POST | `/tip-pools` | Create a tip pool for a business date | Manager |
| GET | `/tip-pools/{id}` | Read a tip pool including pooled and distributed cents | Manager |
| GET | `/tip-pools` | List tip pools, filterable by restaurant, date | Manager |
| POST | `/tip-pools/{id}/distribute` | Distribute a pool across the day's staff shifts | Manager |
| GET | `/tip-allocations/{id}` | Read a single tip allocation | Manager |
| GET | `/tip-allocations` | List tip allocations, filterable by restaurant, pool, shift | Manager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_TABLE_VERSION` | 412 |
| `ERR_CAPACITY_EXCEEDED` | 409 |
| `ERR_ITEM_86` | 409 |
| `ERR_EMPTY_COURSE` | 409 |
| `ERR_COMP_CAP_EXCEEDED` | 409 |
| `ERR_UNDERPAID` | 409 |
| `ERR_TABLE_DOUBLE_BOOKED` | 409 |
| `ERR_SHIFT_OVERLAP` | 409 |
| `ERR_INVALID_SPLIT` | 422 |
| `ERR_POOL_EMPTY` | 409 |
