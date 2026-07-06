# Bath Remodel API — Product Requirements Document

## 1. Introduction

The Bath Remodel API is the operational backbone for a one-day bathroom-remodeling business built on the "measure today, install in a single day" model made familiar by companies such as Bath Fitter and Re-Bath. A homeowner's journey runs from a first phone call through an in-home design-and-measure visit, a priced quote for an acrylic wall system in a chosen color, optional financing and accessibility upgrades, a permit where the jurisdiction requires one, the one-day install itself, and — long after the crew has left — a lifetime warranty and the occasional referral of a friend.

This document specifies the behavior an implementation must exhibit so that every stage of that journey is deterministic and auditable. The domain is deceptively rich: a project moves through a ten-state lifecycle whose path forks on whether a permit is needed; a quote carries two independent status dimensions (its presentation state and its financing state); acrylic-system pricing is tiered by wall area; financing terms cascade from deposit to amortized monthly payment; install crews are a scarce, date-bucketed resource; and referral rewards must be credited and, when a sale unwinds, cleanly reversed. The rules below are written for the engineer who will build the service, favoring domain intent first and mechanics second, but every threshold, rounding step, and state precondition is stated precisely because the system's correctness depends on them.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across every endpoint. Because all resources in this system are top-level collections linked to one another by foreign keys, there is no single URL nesting prefix; each collection lives at the root of the API.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. If either header is absent, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_MISSING_USER_CONTEXT`. When a syntactically valid caller attempts an operation their role is not permitted to perform, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognizes exactly five roles: `Customer`, `Designer`, `FinanceOfficer`, `InstallCoordinator`, and `PlatformAdmin`.

Two of these roles are **entity-backed**, meaning their identity is tied to a persisted record, and ownership of resources is enforced against that record:

- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`. Ownership checks on any resource that references a `Customer` compare that resource's owning customer to `X-User-ID`: a homeowner owns their `Project` (through `customer_id`) and, transitively, the `Quote`, `InstallBooking`, and `WarrantyClaim` records derived from it, as well as the `Referral` records they issued (through `referrer_customer_id`).
- When `X-User-Role` is `Designer`, `X-User-ID` is the `id` of the acting `Designer`. Ownership checks on a `DesignAppointment` or a `Quote` compare the project's assigned `designer_id` to `X-User-ID`.

The other three roles are **opaque operator identities** not tied to any persisted entity. When `X-User-Role` is `FinanceOfficer`, `InstallCoordinator`, or `PlatformAdmin`, `X-User-ID` is an operator identifier the server may log but does not compare against any entity's `id`; these roles are authorized purely by role, not by ownership. A `FinanceOfficer` reviews financing applications; an `InstallCoordinator` runs operations (intake, crews, install scheduling, permit decisions, and warranty review); a `PlatformAdmin` administers the catalog, the logical clock, and referral voids.

When an entity-backed caller is authorized for an operation by role but is not the owner of the target resource, the request is rejected with `ERR_NOT_RESOURCE_OWNER`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum accepted value of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. A `limit` outside the 1–100 range, a negative `offset`, or a non-integer value supplied for either parameter is rejected with `ERR_VALIDATION` (the values are not clamped). Beyond `limit` and `offset`, each list endpoint also accepts optional exact-match filters on selected fields — `/projects` by `customer_id`, `designer_id`, or `status`; `/design-appointments` by `project_id`, `designer_id`, or `status`; `/quotes` by `project_id` or `status`; `/install-bookings` by `project_id`, `crew_id`, or `status`; `/warranty-claims` by `project_id` or `status`; and `/referrals` by `referrer_customer_id`, `referred_customer_id`, `referred_project_id`, or `status` — and any unrecognized query parameter is ignored.

Unless a specific endpoint states otherwise, every list response is sorted by the resource's creation timestamp in ascending order — that is, oldest first, with ties broken by order of creation.

List responses carry the pagination bookkeeping in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in this system — `Customer`, `Designer`, `Crew`, `Project`, `DesignAppointment`, `Quote`, `InstallBooking`, `WarrantyClaim`, and `Referral` — carries a standard set of system-managed fields:

- `id`: a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was first created.
- `updated_at`: an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version`: an integer that starts at 1 on creation and increments by one on every mutation. It is the basis for optimistic concurrency control (§2.8).

Every entity in this domain carries the full set above; none is create-only. Whenever a derived or system-managed field on a resource changes — for example, a project's `status`, `permit_status`, or `warranty_status`, or a customer's `referral_credit_cents` — that counts as a mutation of the resource and refreshes `updated_at` and increments `version`.

### 2.5. Request Validation Order and Precedence

When a request could fail more than one check, the checks are evaluated in a fixed precedence so that the reported error is deterministic. The order is:

1. **User context.** The `X-User-ID` and `X-User-Role` headers must be present and the role known; otherwise `ERR_MISSING_USER_CONTEXT` (400).
2. **Authorization.** The role must be permitted to perform the operation; otherwise `ERR_INSUFFICIENT_PERMISSIONS` (403).
3. **Body shape.** On mutating endpoints, required fields must be present with correct types, enum values must be members of their allowed set, monetary and area amounts must be positive, and where a time interval is supplied `scheduled_end` must be strictly after `scheduled_start`; any violation is `ERR_VALIDATION` (422).
4. **Existence.** Every identifier carried in the path or body must resolve to a live resource, checked left-to-right in the order the identifiers appear. The first unresolved identifier determines the error: `ERR_CUSTOMER_NOT_FOUND`, `ERR_DESIGNER_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, or `ERR_REFERRAL_NOT_FOUND` (all 404).
5. **Ownership.** For entity-backed roles, the acting user must own the target: a `Customer` acting on a project or its derived quote, booking, or claim must equal the project's `customer_id`; a `Designer` acting on an appointment or quote must equal the assigned `designer_id`. A mismatch is `ERR_NOT_RESOURCE_OWNER` (403).
6. **Optimistic concurrency.** Where a write is OCC-guarded, the supplied expected version must match the parent's current `version`; a mismatch is `ERR_STALE_PROJECT_VERSION` (412). See §2.8.
7. **State preconditions.** The target (or its parent) must be in a state that permits the requested transition; otherwise the transition-specific conflict error applies (§3), such as `ERR_PROJECT_INVALID_STATE`, `ERR_PROJECT_NOT_INSTALL_READY`, `ERR_QUOTE_INVALID_STATE`, `ERR_APPOINTMENT_INVALID_STATE`, `ERR_BOOKING_INVALID_STATE`, `ERR_CLAIM_INVALID_STATE`, `ERR_REFERRAL_INVALID_STATE`, or `ERR_FINANCING_NOT_REQUESTED` (all 409).
8. **Cross-entity gates.** Business preconditions that depend on the state of a related entity are checked next (all 409): `ERR_FINANCING_NOT_APPROVED`, `ERR_CREW_NOT_CERTIFIED`, `ERR_WARRANTY_NOT_ACTIVE`, `ERR_PERMIT_NOT_REQUIRED`, `ERR_DESIGNER_INACTIVE`, and `ERR_CREW_INACTIVE`.
9. **Temporal-resource conflicts.** Scheduling conflicts are evaluated after the gates above (all 409): `ERR_DESIGNER_SLOT_CONFLICT`, `ERR_CREW_AT_CAPACITY`, and `ERR_INSTALL_LEAD_TIME`.
10. **Financing amount coherence.** When a financing plan is requested at quote creation, the requested amount must reconcile with the computed financed amount; a mismatch is `ERR_FINANCING_AMOUNT_MISMATCH` (422).
11. **Financing amount bounds and affordability.** The requested amount must fall within the chosen plan's bounds and, at approval, the debt-to-income ratio must be within tolerance: `ERR_FINANCING_AMOUNT_BELOW_MIN`, `ERR_FINANCING_AMOUNT_EXCEEDS_MAX`, and `ERR_DTI_EXCEEDED` (all 422).

The practical consequence of this ordering is that a missing header is reported before an authorization failure, a malformed body is reported before a lookup of the ids it contains, and a stale-version conflict surfaces only after the target has been resolved and ownership confirmed.

### 2.6. Monetary Values and Precision

All monetary amounts in this system are stored and returned as **integer counts of whole cents**; there are no fractional-cent values on any resource. Wherever a calculation produces a non-integer intermediate — a percentage of a price, an amortized payment — the result is rounded to a whole number of cents using the **round-half-up** convention (a value exactly halfway between two cents rounds up to the larger cent). Each calculation rule in §3 states exactly where rounding occurs, because in tiered and per-line-item computations the order of rounding versus summation changes the final cent.

Interest rates are carried as integer **basis points** (hundredths of a percent), and durations such as loan terms are carried as whole months.

### 2.7. Consistency, Cascades, and Version Semantics

Many operations in this domain touch more than one resource. Accepting a quote, for example, does not merely mark that quote accepted — it advances the project, supersedes rival quotes, and may reward a referral. The system applies all such secondary effects synchronously and immediately as part of the triggering operation, so that a client reading any affected resource afterward sees a fully reconciled state. Each resource that is mutated as part of a cascade independently refreshes its own `updated_at` and increments its own `version`, exactly as a direct edit would.

Cascades run in both directions of the hierarchy. A parent moving to a terminal state pushes its dependent children to terminal states (project cancellation sweeps appointments, bookings, quotes, and referrals; see §3.8). Conversely, a child transition can advance its parent (completing a measure visit advances the project out of the design stage; completing the install advances the project to installed and activates the warranty). Where a cascade releases a scarce resource — a designer's time slot, a crew's date capacity, or a customer's referral credit — the release is applied as part of the same operation so that the conserved quantity is restored exactly.

### 2.8. Optimistic Concurrency Control

One write in this system is guarded against acting on a stale view of its parent: **creating a quote against a project**. A `Quote` legitimately supersedes any prior active quote on the same `Project`, so a client that drafts a quote from an out-of-date reading of the project would silently overwrite a quote it never saw. To prevent this, a quote-creation request must include `expected_project_version` as a required field, carrying the `version` of the target `Project` that the client last observed (a project's current `version` is available by fetching it). If `expected_project_version` does not equal the project's current `version` — for instance because another writer has since created a superseding quote and thereby advanced the project's `version` — the creation is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412), and the client must re-read the project before retrying. Creating a quote is the only endpoint that takes a version field; no other endpoint accepts one, and none other performs this check.

### 2.9. The Logical Clock

Time-sensitive rules — most importantly the install lead-time minimum in §3.6 — are evaluated against a **server logical clock**, never the wall clock. On startup the clock reads `2026-05-01T00:00:00Z`, and it never falls back to real time. An administrative test-driving capability lets a `PlatformAdmin` set the clock to a supplied `to_iso8601` instant; from then on the clock holds that value until set again. Any date comparison in this specification — such as whether an `install_date` satisfies the minimum lead time — is taken relative to the current logical-clock instant. Beyond comparisons, every server-generated timestamp the system emits is read from this logical clock rather than wall-clock time: the envelope's `api_request_timestamp` and each resource's `created_at`, `updated_at`, `completed_at`, and `warranty_issued_date` all reflect the current logical-clock instant at the moment they are written.

## 3. Business Logic & Workflows

### 3.1. Catalog Setup and Customer Intake

Before any remodel can be sold, the operational catalog must exist. A `PlatformAdmin` registers each in-home **designer** with a `full_name`, an `email`, and a `region_state_code` (their primary two-letter service state); a designer's `active` flag governs whether they accept new appointments and defaults to true. The same administrator registers each install **crew** with a `crew_name`, a `home_state_code`, and a `max_installs_per_day` (the aggregate number of installs the crew can perform on any single calendar date, which must be at least 1). A crew's `accessibility_certified` flag — false unless set — records whether it is qualified to install walk-in tubs and barrier-free showers, and its `active` flag, true unless set, records whether it accepts new bookings.

Homeowners enter the system through intake, performed by a `PlatformAdmin` or an `InstallCoordinator`. A new `Customer` is created with `full_name`, `email`, `phone`, `street_address`, `city`, `state_code` (a two-letter US state code), and `postal_code`. A customer's `referral_credit_cents` begins at 0. Intake may optionally carry a `referral_code_used`: when it is supplied and matches the `referral_code` of a referral that is still in `ISSUED` status, that referral registers — it advances from `ISSUED` to `REGISTERED` and its `referred_customer_id` is set to the newly created customer (see §3.7).

### 3.2. Opening a Project and Booking the Design Visit

A remodel begins when an `InstallCoordinator`, `PlatformAdmin`, or `Designer` opens a **project** for a homeowner. Creation takes the `customer_id`, the jurisdiction `state_code`, and the `bathroom_type`, which is one of `FULL_BATH`, `SHOWER_ONLY`, or `TUB_ONLY`. A fresh project starts in `LEAD` status with no assigned `designer_id`, its `warranty_status` at `NONE`, and its `permit_status` at `NOT_APPLICABLE`.

The next step is the in-home design-and-measure visit. A `Customer` (on their own project) or an `InstallCoordinator` books a **design appointment** by supplying the `project_id`, the `designer_id` to visit, and the visit window as `scheduled_start` and `scheduled_end`. The window is a half-open interval — occupied from `scheduled_start` inclusive up to `scheduled_end` exclusive — and `scheduled_end` must be strictly later than `scheduled_start`, else `ERR_VALIDATION`. Booking is permitted only while the project is still in `LEAD`; otherwise `ERR_PROJECT_INVALID_STATE`. The chosen designer must be active, or the booking is refused with `ERR_DESIGNER_INACTIVE`.

Because a designer cannot be in two homes at once, the booking is also checked against that designer's existing `SCHEDULED` appointments. The requested window must neither overlap any such appointment nor fall within a 60-minute (one-hour) buffer of one — there must be a gap of at least 60 minutes on either side between the new visit and every existing scheduled visit for that designer. A violation is rejected with `ERR_DESIGNER_SLOT_CONFLICT`. On success the appointment is created in `SCHEDULED` status, the project's `designer_id` is set to the booked designer, and the project advances `LEAD → DESIGN_SCHEDULED`.

At the visit, the assigned designer completes the appointment and records the measured wall area, supplying `measured_wall_area_sqft`, which must be greater than zero (`ERR_VALIDATION`). Completion is allowed only by the designer assigned to the project (`ERR_NOT_RESOURCE_OWNER`) and only while the appointment is still `SCHEDULED` (`ERR_APPOINTMENT_INVALID_STATE`). Completion advances the appointment `SCHEDULED → COMPLETED`, copies the measured area onto the project's own `measured_wall_area_sqft`, and advances the project `DESIGN_SCHEDULED → DESIGN_COMPLETE`. A scheduled visit that will not happen can instead be cancelled by the owning `Customer` or an `InstallCoordinator`; cancellation is allowed only from `SCHEDULED` (`ERR_APPOINTMENT_INVALID_STATE`), moves the appointment `SCHEDULED → CANCELLED`, and releases the designer's time slot.

### 3.3. Building the Quote: System Pricing, Add-ons, and Promotions

Once a project reaches `DESIGN_COMPLETE`, a `Designer` drafts a **quote**. Creation carries the `project_id`, the acrylic `wall_system` tier (`SMOOTH_ACRYLIC`, `TILE_LOOK_ACRYLIC`, or `STONE_LOOK_ACRYLIC`), the system `color` (`WHITE`, `BONE`, `GREY`, or `SANDSTONE`), and an optional `accessibility_addon` (`NONE`, `GRAB_BARS`, `BARRIER_FREE_SHOWER`, or `WALK_IN_TUB`, defaulting to `NONE`). Because pricing depends on the measured area, the quote takes a `wall_area_sqft` snapshot of the project's `measured_wall_area_sqft` at the moment of creation and prices against that snapshot thereafter. A new quote is created in `DRAFT` status with its `revision_round` starting at 0 and, because it supersedes any earlier active quote on the same project, its creation is guarded by the optimistic-concurrency rule of §2.8: the request must carry `expected_project_version`, and creating the quote increments the project's `version` by one and moves every sibling quote on that project that is still in `DRAFT`, `PRESENTED`, or `REVISION_REQUESTED` to `SUPERSEDED`.

The **system price** (`system_price_cents`) is computed by marginal area tiering against a per-square-foot base rate fixed by the wall-system tier: 3750 cents per square foot for `SMOOTH_ACRYLIC`, 5900 for `TILE_LOOK_ACRYLIC`, and 8250 for `STONE_LOOK_ACRYLIC`. The snapshot area is split across two breakpoints at 40 and 80 square feet: the first 40 square feet are billed at the full base rate; the portion above 40 square feet and up to and including 80 square feet — the next 40 square feet — is billed at 90% of the base rate; and any area strictly beyond 80 square feet is billed at 80% of the base rate. (An area of exactly 80 square feet therefore falls entirely in the middle tier.) The three tier subtotals are added together and the sum is rounded half-up to a whole cent in a single, final rounding step.

The **add-on price** (`addon_price_cents`) is a flat amount fixed by the accessibility add-on: 0 cents for `NONE`, 29900 cents for `GRAB_BARS`, 249900 cents for `BARRIER_FREE_SHOWER`, and 449900 cents for `WALK_IN_TUB`.

Promotions apply through an optional `promo_code`; the only recognized code is `SPRING750`, worth a 7.5% discount, and any other value grants nothing. The **discount** (`discount_cents`) is computed **per line item with the rounding order pinned**: when `SPRING750` is present, the system-price line and the add-on-price line are each multiplied by 7.5% and each rounded half-up to a whole cent independently, and only then are the two rounded line discounts summed to give the total discount; when no recognized code is present, the discount is 0. Summing the two raw line discounts before rounding is not equivalent and must not be used, because it can differ by a cent. The **net price** (`net_price_cents`) is the system price plus the add-on price minus the discount.

While a quote is only being drafted, its `permit_surcharge_cents` and `final_total_cents` are not yet determined and remain null; the amount the customer is shown at this stage — the estimate — is simply the net price. The three priced fields above are (re)computed both when the quote is created and whenever it is presented, so that presentation always reflects the current inputs.

A drafted quote is shown to the homeowner when the `Designer` presents it: presentation is allowed only from `DRAFT` (`ERR_QUOTE_INVALID_STATE`), advances the quote `DRAFT → PRESENTED`, and advances the project `DESIGN_COMPLETE → QUOTED`. If the homeowner wants changes, the owning `Customer` requests a revision: this is allowed only while the quote is `PRESENTED` (`ERR_QUOTE_INVALID_STATE`) and only by the project's owner (`ERR_NOT_RESOURCE_OWNER`). Requesting a revision moves the quote `PRESENTED → REVISION_REQUESTED`, increments its `revision_round` by one, and drops the project back `QUOTED → DESIGN_COMPLETE` so the designer can author a fresh, superseding quote.

### 3.4. Financing the Remodel

A homeowner may finance the job rather than pay in full. Financing is requested at quote creation by supplying a `financing_plan_code` — one of `PLAN_12_0`, `PLAN_60_999`, or `PLAN_120_1299`; leaving it null means pay-in-full and leaves the quote's `financing_status` at `NONE`. When a plan code is present, the quote's `financing_status` starts at `REQUESTED` and two further inputs become required: `requested_amount_cents`, the amount to finance, and `stated_annual_income_cents`, the applicant's stated annual income.

The financing figures are derived in a pinned sequence, each step feeding the next. First, the **deposit** (`deposit_cents`) is 10% of the net price, rounded half-up to a whole cent. Second, the **financed amount** (`financed_amount_cents`) is the net price minus the deposit. The applicant's `requested_amount_cents` must equal this financed amount exactly; if it does not, the request is rejected with `ERR_FINANCING_AMOUNT_MISMATCH`.

Each plan defines a base annual rate in basis points, a term in months, and the amount band it will finance:

- `PLAN_12_0`: base APR 0 basis points, term 12 months, financing at least 100000 cents and at most 1500000 cents.
- `PLAN_60_999`: base APR 999 basis points, term 60 months, financing at least 300000 cents and at most 5000000 cents.
- `PLAN_120_1299`: base APR 1299 basis points, term 120 months, financing at least 500000 cents and at most 8000000 cents.

The requested amount must lie within the chosen plan's band: below the minimum it is rejected with `ERR_FINANCING_AMOUNT_BELOW_MIN`, and above the maximum with `ERR_FINANCING_AMOUNT_EXCEEDS_MAX`.

The application sits until a `FinanceOfficer` decides it, which is permitted only while `financing_status` is `REQUESTED` (`ERR_FINANCING_NOT_REQUESTED`). On a decline decision, the officer moves `financing_status` `REQUESTED → DECLINED` and nothing further is computed. On an approve decision, the system first evaluates affordability by the **debt-to-income ratio**: the financed amount divided by the stated annual income. That ratio selects an APR surcharge tier, with the upper bound of each tier inclusive — a ratio of at most 0.20 adds 0 basis points; a ratio above 0.20 but at most 0.35 adds 250 basis points; a ratio above 0.35 but at most 0.50 adds 600 basis points; and a ratio above 0.50 is not financeable and the approval is refused with `ERR_DTI_EXCEEDED`. The **approved APR** (`approved_apr_bps`) is the plan's base APR plus the selected tier's surcharge, in basis points, and `financing_status` moves `REQUESTED → APPROVED`.

The **monthly payment** (`monthly_payment_cents`) is then the standard amortization of the financed amount over the plan's term. Let the monthly rate be the approved APR in basis points divided by 10000 (converting basis points to a decimal annual rate) and then divided by 12. When that monthly rate is greater than zero, the monthly payment equals the financed amount multiplied by the monthly rate, multiplied by (one plus the monthly rate) raised to the power of the number of term months, divided by the quantity (one plus the monthly rate) raised to the power of the number of term months minus one, with the result rounded half-up to a whole cent. When the monthly rate is exactly zero — as it is for the zero-APR plan — the monthly payment is instead the financed amount divided by the number of term months, rounded half-up to a whole cent.

### 3.5. Closing the Sale: Acceptance, Permits, and Referral Rewards

The sale closes when the owning `Customer` accepts a presented quote. Acceptance is allowed only by the project's owner (`ERR_NOT_RESOURCE_OWNER`), only while the quote is `PRESENTED` (`ERR_QUOTE_INVALID_STATE`), and only when the quote's `financing_status` is either `NONE` (pay-in-full) or `APPROVED`; a quote whose financing is still `REQUESTED` or was `DECLINED` cannot be accepted and is refused with `ERR_FINANCING_NOT_APPROVED`.

At acceptance the **final total** is computed. Whether a permit is required is determined by the accepted quote's `accessibility_addon`: a permit is required exactly when that add-on is `WALK_IN_TUB` or `BARRIER_FREE_SHOWER`, and is not required for `NONE` or `GRAB_BARS`. When a permit is required, a `permit_surcharge_cents` applies, tiered on the net price (evaluated first, so the tiering never depends on the total it feeds): if the net price is at most 500000 cents the surcharge is 15000 cents, and if the net price is greater than 500000 cents the surcharge is 30000 cents. When no permit is required, the surcharge is 0. The `final_total_cents` is the net price plus this permit surcharge; it is set only now, at acceptance, and differs from the earlier estimate (which was just the net price) precisely by the surcharge whenever a permit is required.

Acceptance drives a cascade. The quote moves `PRESENTED → ACCEPTED`; the project moves `QUOTED → SOLD`; the project's `permit_required` and `requires_accessible_crew` flags are both set from the permit condition above (both true together when the add-on triggers a permit, both false otherwise); and the project's `accepted_quote_total_cents` is set to the quote's `final_total_cents`. Every sibling quote on the project still in `DRAFT`, `PRESENTED`, or `REVISION_REQUESTED` is moved to `SUPERSEDED` (and any of those siblings whose financing was still `REQUESTED` has that financing moved to `DECLINED`). The project then forks automatically on `permit_required`: when a permit is required it advances `SOLD → PERMIT_PENDING` and its `permit_status` moves to `PENDING`; when none is required it advances `SOLD → INSTALL_READY` and its `permit_status` stays `NOT_APPLICABLE`. Finally, if a referral is `REGISTERED` for this customer or project, that referral is rewarded as described in §3.7.

For a permit-bound project, an `InstallCoordinator` records the jurisdiction's decision by supplying an `outcome` of either `APPROVED` or `REJECTED`. This capability requires the project's `permit_required` to be true (`ERR_PERMIT_NOT_REQUIRED`) and the project to be in `PERMIT_PENDING` (`ERR_PROJECT_INVALID_STATE`); the `permit_required` gate is evaluated before the `PERMIT_PENDING` state check, so a project that is neither permit-required nor `PERMIT_PENDING` reports `ERR_PERMIT_NOT_REQUIRED`. An `APPROVED` outcome sets `permit_status` to `APPROVED` and advances the project `PERMIT_PENDING → INSTALL_READY`. A `REJECTED` outcome sets `permit_status` to `REJECTED` but leaves the project in `PERMIT_PENDING`, so a corrected permit may be resubmitted and resolved again.

### 3.6. The One-Day Install and Lifetime Warranty

Once a project is `INSTALL_READY`, an `InstallCoordinator` schedules the one-day install as an **install booking**, supplying the `project_id`, the `crew_id`, and the `install_date` (the calendar date, at UTC midnight, whose date component is the occupancy bucket). Scheduling is permitted only from `INSTALL_READY`; from any other state it is refused with `ERR_PROJECT_NOT_INSTALL_READY`. The chosen crew must be active (`ERR_CREW_INACTIVE`). If the project's `requires_accessible_crew` flag is true, the crew must be `accessibility_certified`, or the booking is refused with `ERR_CREW_NOT_CERTIFIED` — this is how a walk-in tub or barrier-free shower is steered to a qualified crew (the permit requirement itself is already enforced by the `INSTALL_READY` gate). The `install_date` must be at least three days after the current logical-clock date; a date sooner than that minimum lead time is rejected with `ERR_INSTALL_LEAD_TIME`.

Crew capacity is a conserved, per-date quantity. For a given crew and `install_date`, the number of slots already consumed is the count of that crew's install bookings on that date that are currently in `BOOKED` status; bookings that are `COMPLETED` or `CANCELLED` do not consume capacity. A new booking is refused with `ERR_CREW_AT_CAPACITY` when the count of `BOOKED` bookings for that crew and date already equals the crew's `max_installs_per_day`. When all checks pass, the booking is created in `BOOKED` status and the project advances `INSTALL_READY → INSTALL_SCHEDULED`.

On install day, the `InstallCoordinator` marks the booking complete, which is allowed only while the booking is `BOOKED` (`ERR_BOOKING_INVALID_STATE`). Completion moves the booking `BOOKED → COMPLETED` and stamps its `completed_at`, advances the project `INSTALL_SCHEDULED → INSTALLED`, sets the project's `warranty_status` to `ACTIVE`, and stamps its `warranty_issued_date` with the completion instant. If instead the appointment must be called off, an `InstallCoordinator` or the owning `Customer` cancels the booking; cancellation is allowed only from `BOOKED` (`ERR_BOOKING_INVALID_STATE`), moves the booking `BOOKED → CANCELLED`, releases the crew's slot for that date, and — when it is the booking that is cancelled directly — returns the project `INSTALL_SCHEDULED → INSTALL_READY` so a new install can be scheduled. Because a booked slot that is later cancelled leaves capacity exactly as it was before the booking, the book-then-cancel pair is a no-op on a crew's available slots for that date.

The lifetime warranty comes to life only after installation. The owning `Customer` files a **warranty claim** against a project by supplying the `project_id`, a `defect_type` (`CRACK`, `LEAK`, `DISCOLORATION`, or `HARDWARE_FAILURE`), and a free-text `description`. A claim can be filed only when the project's `warranty_status` is `ACTIVE`; otherwise it is refused with `ERR_WARRANTY_NOT_ACTIVE`. A new claim opens in `SUBMITTED`. An `InstallCoordinator` then decides it, which is allowed only from `SUBMITTED` (`ERR_CLAIM_INVALID_STATE`) and carries a `decision`. An approve decision requires a `resolution` of either `REPAIR` or `REPLACE` (`ERR_VALIDATION`), records that `resolution` together with any `review_notes`, and moves the claim `SUBMITTED → APPROVED`. A reject decision moves the claim `SUBMITTED → REJECTED`, sets its `resolution` to `DENIED`, and records any `review_notes`.

### 3.7. The Referral Program and Credit Accounting

Existing homeowners can refer friends. A `Customer` (for themselves) or a `PlatformAdmin` issues a **referral** by supplying the `referrer_customer_id` and an optional `program_tier` of `STANDARD` (the default) or `PREMIUM`. Issuing generates a unique `referral_code` (for example, of the form `REF-XXXX`), starts the referral in `ISSUED` status, and sets its `reward_cents` to 0. The friend later registers by using that code as their `referral_code_used` at intake (§3.1), which advances the referral `ISSUED → REGISTERED` and records the friend as `referred_customer_id`.

The reward is earned when the referred friend's project is sold. As part of the acceptance cascade (§3.5), a referral that is `REGISTERED` for that customer or project advances `REGISTERED → REWARDED`, has its `referred_project_id` set to the sold project, and has its `reward_cents` computed by program tier. For a `STANDARD` tier the reward is a flat 50000 cents, regardless of the project's value. For a `PREMIUM` tier the reward is 3% of the referred project's `accepted_quote_total_cents`, rounded half-up to a whole cent — so the same sold project yields a different reward under `PREMIUM` than under `STANDARD`. When a referral becomes `REWARDED`, its computed `reward_cents` is added to the referrer's `referral_credit_cents`.

A referral can be voided — either explicitly by a `PlatformAdmin` or `InstallCoordinator`, or automatically when the referred project is cancelled (§3.8). Voiding is allowed from any non-void status (`ERR_REFERRAL_INVALID_STATE` if it is already `VOID`) and moves the referral to `VOID`. Crucially, if the referral had already reached `REWARDED`, voiding it reverses the compensation: the referrer's `referral_credit_cents` is reduced by that same `reward_cents`. A customer's `referral_credit_cents` is thus, by construction, the sum of the rewards of all referrals they own that are currently `REWARDED`; it rises when one of their referrals becomes rewarded and falls by the same amount when a rewarded referral is voided. It is floored at zero and never goes negative.

### 3.8. Cancelling a Project

A project can be cancelled at almost any point in its life by the owning `Customer`, an `InstallCoordinator`, or a `PlatformAdmin`. Cancellation is permitted from any state except the two terminal ones — a project that is already `INSTALLED` or `CANCELLED` cannot be cancelled again, and the attempt is refused with `ERR_PROJECT_INVALID_STATE`. The cancellation records the supplied `cancel_reason` (an optional field; it may be omitted, in which case it is stored as null) on the project and moves it to `CANCELLED`, then unwinds everything still in flight beneath it: every `SCHEDULED` design appointment is moved to `CANCELLED` (releasing the designer's slot); every `BOOKED` install booking is moved to `CANCELLED` (releasing the crew's date slot); every quote still in `DRAFT`, `PRESENTED`, or `REVISION_REQUESTED` is moved to `SUPERSEDED`, and any such quote whose financing was still `REQUESTED` has that financing moved to `DECLINED`; and every `REWARDED` referral tied to this project is moved to `VOID`, which reverses the referrer's credit exactly as an explicit void would. Every one of these dependent mutations refreshes that resource's own `updated_at` and `version`, and every released quantity — designer time, crew capacity, referral credit — is restored to its pre-commitment value.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify or transition an existing resource, including the state-change actions, return `200 OK`. All read operations return `200 OK`. The request and response payloads for each endpoint are described narratively in §3; the table below is only a routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Create a homeowner customer (lead intake); may register a referral | PlatformAdmin, InstallCoordinator |
| GET | `/customers/{id}` | Fetch a customer | All roles |
| POST | `/designers` | Register an in-home designer | PlatformAdmin |
| GET | `/designers/{id}` | Fetch a designer | All roles |
| POST | `/crews` | Register an install crew | PlatformAdmin |
| GET | `/crews/{id}` | Fetch a crew | All roles |
| POST | `/projects` | Open a remodel project (lead) | InstallCoordinator, PlatformAdmin, Designer |
| GET | `/projects` | List/filter projects | All roles |
| GET | `/projects/{id}` | Fetch a project (source of `version` for OCC) | All roles |
| POST | `/projects/{id}/resolve-permit` | Record a permit decision for a permit-required project | InstallCoordinator |
| POST | `/projects/{id}/cancel` | Cancel a project (cascades to children) | Customer, InstallCoordinator, PlatformAdmin |
| POST | `/design-appointments` | Book an in-home design & measure visit | Customer, InstallCoordinator |
| GET | `/design-appointments` | List/filter design appointments | All roles |
| GET | `/design-appointments/{id}` | Fetch a design appointment | All roles |
| POST | `/design-appointments/{id}/complete` | Complete the visit; record measured wall area | Designer |
| POST | `/design-appointments/{id}/cancel` | Cancel a scheduled visit | Customer, InstallCoordinator |
| POST | `/quotes` | Create a quote draft (OCC-guarded on project version) | Designer |
| GET | `/quotes` | List/filter quotes | All roles |
| GET | `/quotes/{id}` | Fetch a quote | All roles |
| POST | `/quotes/{id}/present` | Present the quote to the customer | Designer |
| POST | `/quotes/{id}/request-revision` | Request changes to a presented quote | Customer |
| POST | `/quotes/{id}/finance-decide` | Approve or decline requested financing | FinanceOfficer |
| POST | `/quotes/{id}/accept` | Accept the quote (sell the project) | Customer |
| POST | `/install-bookings` | Schedule the one-day install on a crew for a date | InstallCoordinator |
| GET | `/install-bookings` | List/filter install bookings | All roles |
| GET | `/install-bookings/{id}` | Fetch an install booking | All roles |
| POST | `/install-bookings/{id}/complete` | Mark the install complete; issue the lifetime warranty | InstallCoordinator |
| POST | `/install-bookings/{id}/cancel` | Cancel a booking; release the crew slot | InstallCoordinator, Customer |
| POST | `/warranty-claims` | File a lifetime-warranty claim | Customer |
| GET | `/warranty-claims` | List/filter warranty claims | All roles |
| GET | `/warranty-claims/{id}` | Fetch a warranty claim | All roles |
| POST | `/warranty-claims/{id}/decide` | Approve (REPAIR/REPLACE) or reject (DENIED) a claim | InstallCoordinator |
| POST | `/referrals` | Issue a referral code for an existing customer | Customer, PlatformAdmin |
| GET | `/referrals` | List/filter referrals | All roles |
| GET | `/referrals/{id}` | Fetch a referral | All roles |
| POST | `/referrals/{id}/void` | Void a referral; reverse credit if already rewarded | PlatformAdmin, InstallCoordinator |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_DESIGNER_NOT_FOUND` | 404 |
| `ERR_CREW_NOT_FOUND` | 404 |
| `ERR_PROJECT_NOT_FOUND` | 404 |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 |
| `ERR_QUOTE_NOT_FOUND` | 404 |
| `ERR_BOOKING_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_REFERRAL_NOT_FOUND` | 404 |
| `ERR_STALE_PROJECT_VERSION` | 412 |
| `ERR_PROJECT_INVALID_STATE` | 409 |
| `ERR_PROJECT_NOT_INSTALL_READY` | 409 |
| `ERR_QUOTE_INVALID_STATE` | 409 |
| `ERR_APPOINTMENT_INVALID_STATE` | 409 |
| `ERR_BOOKING_INVALID_STATE` | 409 |
| `ERR_CLAIM_INVALID_STATE` | 409 |
| `ERR_REFERRAL_INVALID_STATE` | 409 |
| `ERR_FINANCING_NOT_REQUESTED` | 409 |
| `ERR_FINANCING_NOT_APPROVED` | 409 |
| `ERR_CREW_NOT_CERTIFIED` | 409 |
| `ERR_WARRANTY_NOT_ACTIVE` | 409 |
| `ERR_PERMIT_NOT_REQUIRED` | 409 |
| `ERR_DESIGNER_INACTIVE` | 409 |
| `ERR_CREW_INACTIVE` | 409 |
| `ERR_DESIGNER_SLOT_CONFLICT` | 409 |
| `ERR_CREW_AT_CAPACITY` | 409 |
| `ERR_INSTALL_LEAD_TIME` | 409 |
| `ERR_FINANCING_AMOUNT_MISMATCH` | 422 |
| `ERR_FINANCING_AMOUNT_EXCEEDS_MAX` | 422 |
| `ERR_FINANCING_AMOUNT_BELOW_MIN` | 422 |
| `ERR_DTI_EXCEEDED` | 422 |
